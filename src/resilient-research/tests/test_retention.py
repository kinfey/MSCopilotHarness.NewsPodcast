import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from azure.core.exceptions import HttpResponseError
from starlette.requests import Request
from test_station import MemoryStore

from station import pipeline, retention
from station.storage import BlobStore
from station.timeutil import parse_slot


class RetentionStore(MemoryStore):
    async def list_names(self, prefix, public=False):
        for flag, name in list(self.data):
            if flag == public and name.startswith(prefix):
                yield name

    async def delete(self, name, public=False):
        self.data.pop((public, name), None)


def test_retention_day_is_beijing_not_utc_or_browser_day(monkeypatch):
    monkeypatch.setattr(retention, "today_key", lambda: "20261102")
    retention.require_current(datetime(2026, 11, 1, 16, tzinfo=UTC))
    with pytest.raises(retention.BroadcastExpiredError):
        retention.require_current(datetime(2026, 11, 1, 15, 59, 59, tzinfo=UTC))
    with pytest.raises(ValueError):
        retention.slot_day(datetime(2026, 11, 2))
    for path in ("jobs/20261101/2330/cn/turns/000.wav", "media/en/20261101/2330.mp4"):
        assert retention.blob_day(path) == "20261101"
    for path in ("index.html", "data/catalog.json", "locks/publication.lock", "unrelated/20261101/file"):
        assert retention.blob_day(path) is None
    with pytest.raises(ValueError):
        retention.blob_day("jobs/20261301/0000/status.json")


async def test_midnight_sweeps_both_catalogues_and_all_expired_content_idempotently(monkeypatch):
    monkeypatch.setattr(retention, "today_key", lambda: "20261102")
    store = RetentionStore()
    old = {"id": "20261101/2330", "slot": "2026-11-01T23:30:00+08:00"}
    older = {"id": "20261016/0000", "slot": "2026-10-16T00:00:00+08:00"}
    current = {"id": "20261102/0000", "slot": "2026-11-02T00:00:00+08:00"}
    for public in (True, False):
        prefixes = ("media/cn/", "media/en/") if public else ("cn/", "en/", "jobs/", "retired/")
        for prefix in prefixes:
            for edition in (older, old, current):
                name = (
                    f"{prefix}{edition['id']}/file"
                    if prefix in ("jobs/", "retired/")
                    else f"{prefix}{edition['id']}.mp4"
                )
                store.data[public, name] = b"broadcast content"
    for edition in (older, old, current):
        store.data[False, f"invocations/{edition['id'].replace('/', '-')}.json"] = {"slot": edition["slot"]}
    for catalog in ("data/catalog.json", "data/manual-catalog.json"):
        store.data[True, catalog] = {"editions": [copy.deepcopy(current), old, older]}
    preserved = {
        (True, "index.html"): b"static website",
        (True, "styles.css"): b"CSS",
        (False, "locks/publication.lock"): b"",
        (False, "unrelated/20261101/keep.json"): {"not": "station content"},
    }
    store.data.update(preserved)
    result = await BlobStore.cleanup_day(store)
    assert result["status"] == "completed"
    assert result["output"]["deleted"] == {"public": 4, "private": 10}
    for catalog in ("data/catalog.json", "data/manual-catalog.json"):
        assert store.data[True, catalog]["editions"] == [current]
    assert all(store.data[key] == value for key, value in preserved.items())
    assert not any(
        "20261101" in name or "20261016" in name
        for _, name in store.data
        if name.startswith(("jobs/", "media/", "cn/", "en/", "retired/", "invocations/"))
    )
    repeat = await BlobStore.cleanup_day(store)
    assert repeat["output"]["deleted"] == {"public": 0, "private": 0}


async def test_first_new_day_has_no_yesterdays_fallback_even_without_new_audio(monkeypatch):
    monkeypatch.setattr(retention, "today_key", lambda: "20261102")
    store = RetentionStore()
    store.data[True, "data/manual-catalog.json"] = {"editions": [{"slot": "2026-11-01T23:59:00+08:00"}]}
    await BlobStore.cleanup_day(store)
    assert store.data[True, "data/manual-catalog.json"]["editions"] == []
    assert store.data[True, "data/catalog.json"]["editions"] == []
    with pytest.raises(retention.BroadcastExpiredError):
        await pipeline.produce(store, parse_slot("2026-11-01T23:30:00+08:00"))
    with pytest.raises(retention.BroadcastExpiredError):
        await BlobStore.publish(store, {"id": "old", "slot": "2026-11-01T23:30:00+08:00"})


async def test_stale_upload_is_rejected_inside_publication_fence(monkeypatch):
    day = "20261101"
    monkeypatch.setattr(retention, "today_key", lambda: day)
    store = MemoryStore()
    upload = AsyncMock()
    store._upload = upload
    day = "20261102"
    with pytest.raises(retention.BroadcastExpiredError):
        await BlobStore.put_bytes(store, "media/cn/20261101/2330.mp4", b"old audio", "audio/mp4", public=True)
    upload.assert_not_awaited()
    await BlobStore.put_bytes(store, "media/cn/20261102/0000.mp4", b"new audio", "audio/mp4", public=True)
    upload.assert_awaited_once()


async def test_job_crossing_midnight_cannot_save_results_or_failure_checkpoint(monkeypatch):
    day = "20261101"
    monkeypatch.setattr(retention, "today_key", lambda: day)
    monkeypatch.delenv("EDITORIAL_AGENT_NAME", raising=False)
    store = MemoryStore()

    async def collect():
        nonlocal day
        day = "20261102"
        return {"evidence": []}

    async def guarded_put(name, value, *args, **kwargs):
        if retention.blob_day(name) != day:
            raise retention.BroadcastExpiredError("Expired at Blob write")
        store.data[False, name] = value

    store.put_json = guarded_put
    monkeypatch.setattr(pipeline.news, "collect", collect)
    with pytest.raises(retention.BroadcastExpiredError):
        await pipeline.produce(store, parse_slot("2026-11-01T23:30:00+08:00"))
    assert (False, "jobs/20261101/2330/evidence.json") not in store.data
    assert store.data[False, "jobs/20261101/2330/status.json"]["status"] == "running"
    assert not store.published


async def test_blob_delete_includes_snapshots_and_does_not_hide_service_errors():
    client = SimpleNamespace(delete_blob=AsyncMock())

    async def versions(**kwargs):
        yield SimpleNamespace(name="media/cn/20261101/2330.mp4", version_id="old-version")
        yield SimpleNamespace(name="media/cn/20261101/2330.mp4.extra", version_id="unrelated")

    container = SimpleNamespace(list_blobs=versions, delete_blob=AsyncMock())
    store = SimpleNamespace(blob=lambda name, public: client, web=container)
    await BlobStore.delete(store, "media/cn/20261101/2330.mp4", True)
    client.delete_blob.assert_awaited_once_with(delete_snapshots="include")
    container.delete_blob.assert_awaited_once_with("media/cn/20261101/2330.mp4", version_id="old-version")
    client.delete_blob.side_effect = RuntimeError("Storage unavailable")
    with pytest.raises(RuntimeError, match="Storage unavailable"):
        await BlobStore.delete(store, "media/cn/20261101/2330.mp4", True)


async def test_publication_lease_waits_for_cleanup_but_other_lock_failures_surface():
    error = HttpResponseError("Lease busy")
    error.error_code = "LeaseAlreadyPresent"
    lease = SimpleNamespace(renew=AsyncMock(), release=AsyncMock())
    blob = SimpleNamespace(upload_blob=AsyncMock(), acquire_lease=AsyncMock(side_effect=[error, lease]))
    store = SimpleNamespace(blob=lambda name: blob)
    async with BlobStore.lock(store, "publication"):
        assert blob.acquire_lease.await_count == 2
    lease.release.assert_awaited_once()
    blob.acquire_lease = AsyncMock(side_effect=error)
    with pytest.raises(HttpResponseError):
        async with BlobStore.lock(store, "edition"):
            pytest.fail("A contested edition lock must not be silently accepted")


async def test_cleanup_endpoint_tracks_actual_result_independently_of_shared_report(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    import main

    monkeypatch.setattr(retention, "today_key", lambda: "20261102")
    stamp = parse_slot("2026-11-02T00:00:00+08:00")
    store = MemoryStore()
    start = AsyncMock()
    monkeypatch.setattr(main, "manual_slot", lambda: stamp)
    monkeypatch.setattr(main, "current_slot", lambda: stamp)
    monkeypatch.setattr(main.BlobStore, "from_env", lambda: store)
    monkeypatch.setattr(main, "cleanup", SimpleNamespace(start=start))

    def request(body):
        return Request(
            {"type": "http", "method": "POST", "path": "/", "headers": [], "state": {"invocation_id": "cleanup-test"}},
            AsyncMock(return_value={"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}),
        )

    response = await main.invoke(request({"action": "cleanup"}))
    assert response.status_code == 202
    assert start.await_args.kwargs["input"] == {"invocation_id": "cleanup-test"}
    assert json.loads((await main.get_invocation(request({}))).body)["status"] == "running"
    store.data[False, "invocations/cleanup-test.json"]["status"] = "completed"
    store.data[False, "maintenance/retention.json"] = {"status": "failed"}
    assert json.loads((await main.get_invocation(request({}))).body)["status"] == "completed"
    assert (await main.invoke(request({"action": "cleanup", "slot": "2026-11-01"}))).status_code == 400
    response = await main.invoke(request({"action": "generate", "slot": "2026-11-01T23:30:00+08:00"}))
    assert response.status_code == 410
