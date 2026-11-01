import json
import logging
from datetime import datetime

from azure.ai.agentserver.core.tasks import (
    RetryPolicy,
    TaskConflictError,
    TaskContext,
    set_resilient_tasks_enabled,
    task,
)
from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse

from station import retention
from station.pipeline import produce
from station.storage import BlobStore
from station.timeutil import current_slot, manual_slot, parse_slot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
set_resilient_tasks_enabled(True)
app = InvocationAgentServerHost()


@task(name="newsradio24-broadcast", retry=RetryPolicy(initial_delay=60, max_delay=180, max_attempts=3))
async def broadcast(ctx: TaskContext[dict]) -> dict:
    store = BlobStore.from_env()
    try:
        await store.cleanup_day()
        manual = ctx.input.get("manual", False)
        return await produce(store, parse_slot(ctx.input["slot"], aligned=not manual), ctx.cancel, manual=manual)
    finally:
        await store.close()


@task(name="newsradio24-retention", retry=RetryPolicy(initial_delay=60, max_delay=180, max_attempts=3))
async def cleanup(ctx: TaskContext[dict]) -> dict:
    store = BlobStore.from_env()
    name = f"invocations/{ctx.input['invocation_id']}.json"
    try:
        result = await store.cleanup_day()
        entry = await store.get_json(name)
        if entry is not None:
            await store.put_json(name, {**entry, **result})
        else:
            logger.info("Cleanup invocation mapping expired during a day transition")
        return result
    except Exception as exc:
        logger.exception("Daily broadcast cleanup failed")
        failure = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "message": "Daily cleanup failed; check hosted logs.",
        }
        await store.put_json("maintenance/retention.json", failure)
        entry = await store.get_json(name)
        if entry is not None:
            await store.put_json(name, {**entry, **failure})
        raise
    finally:
        await store.close()


@app.invoke_handler
async def invoke(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise TypeError("Expected a JSON object")
        action = body.get("action", "generate")
        if action == "health":
            return JSONResponse({"status": "completed", "output": {"ready": True}})
        if action == "cleanup":
            if set(body) != {"action"}:
                raise ValueError("Cleanup uses the server's current Beijing day and accepts no other parameters")
            stamp = manual_slot()
            store = BlobStore.from_env()
            try:
                await store.put_json(
                    f"invocations/{request.state.invocation_id}.json",
                    {"slot": stamp.isoformat(), "action": "cleanup", "status": "running"},
                )
            finally:
                await store.close()
            try:
                await cleanup.start(
                    task_id=f"retention-{request.state.invocation_id}",
                    input={"invocation_id": request.state.invocation_id},
                )
            except TaskConflictError:
                pass
            return JSONResponse({"status": "running", "invocation_id": request.state.invocation_id}, status_code=202)
        manual = action == "generate_now"
        if manual:
            if "slot" in body:
                raise ValueError("Manual editions use the current time, not a supplied slot")
            slot = manual_slot()
        elif action == "generate":
            slot = parse_slot(body["slot"]) if body.get("slot") else current_slot()
            if slot > current_slot():
                raise ValueError("Cannot generate a future slot")
        else:
            raise ValueError("Unknown action")
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return JSONResponse(
            {
                "error": "Use cleanup without extra parameters, generate_now without a slot, or generate with today's :00/:30 timestamp."
            },
            status_code=400,
        )
    slot_id = slot.strftime("%Y%m%d/%H%M")
    invocation_id = request.state.invocation_id
    store = BlobStore.from_env()
    try:
        try:
            retention.require_current(slot)
        except retention.BroadcastExpiredError:
            return JSONResponse({"error": "Broadcast expired; only today's programmes are available."}, status_code=410)
        if await store.get_json(f"retired/{slot_id}.json"):
            return JSONResponse({"error": "This broadcast has been permanently deleted."}, status_code=410)
        await store.put_json(f"invocations/{invocation_id}.json", {"slot": slot.isoformat()})
        existing = await store.get_json(f"jobs/{slot_id}/status.json")
        if existing and existing.get("status") == "completed":
            return JSONResponse({"status": "completed", "output": existing})
    finally:
        await store.close()
    try:
        await broadcast.start(
            task_id=f"broadcast-{slot_id.replace('/', '-')}", input={"slot": slot.isoformat(), "manual": manual}
        )
    except TaskConflictError:
        pass
    return JSONResponse(
        {"status": "running", "invocation_id": invocation_id, "slot": slot.isoformat()}, status_code=202
    )


@app.get_invocation_handler
async def get_invocation(request: Request):
    store = BlobStore.from_env()
    try:
        entry = await store.get_json(f"invocations/{request.state.invocation_id}.json")
        if entry is None:
            return JSONResponse({"error": "Invocation not found"}, status_code=404)
        slot = datetime.fromisoformat(entry["slot"])
        if entry.get("action") == "cleanup":
            return JSONResponse(entry)
        if retention.slot_day(slot) != retention.today_key():
            return JSONResponse(
                {"status": "expired", "message": "Broadcast removed by daily retention."}, status_code=410
            )
        state = await store.get_json(f"jobs/{slot.strftime('%Y%m%d/%H%M')}/status.json")
        return JSONResponse(state or {"status": "running", "slot": entry["slot"]})
    finally:
        await store.close()


if __name__ == "__main__":
    app.run()
