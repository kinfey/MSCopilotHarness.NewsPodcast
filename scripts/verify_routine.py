"""Verify a new automatic edition or a requested published bilingual edition."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/resilient-research"))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument(
        "--edition-id",
        help="Verify this edition instead of waiting for a new automatic one",
    )
    parser.add_argument(
        "--catalog",
        choices=("data/catalog.json", "data/manual-catalog.json"),
        default="data/catalog.json",
    )
    parser.add_argument(
        "--editorial-format",
        help="Require the new scheduled edition to use this editorial format",
    )
    args = parser.parse_args()
    process = await asyncio.to_thread(
        subprocess.run,
        ["azd", "env", "get-values", "--output", "json"],
        cwd=ROOT,
        env={**os.environ, "AZURE_DEV_USER_AGENT": "microsoft_foundry_skill"},
        check=True,
        capture_output=True,
        text=True,
    )
    os.environ.update(
        {key: str(value) for key, value in json.loads(process.stdout).items()}
    )
    from station.storage import BlobStore

    store = BlobStore.from_env()
    result_name = (
        "manual-smoke.json"
        if args.catalog == "data/manual-catalog.json"
        else "routine-smoke.json"
    )
    output = ROOT / f"src/resilient-research/.foundry/results/{result_name}"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        baseline = await store.get_json(args.catalog, public=True) or {"editions": []}
        latest = baseline["editions"][0]["slot"] if not args.edition_id else None
        deadline = time.monotonic() + args.timeout
        print(
            "Waiting for edition"
            if args.edition_id
            else "Waiting for an automatic edition newer than",
            args.edition_id or latest,
            flush=True,
        )
        while time.monotonic() < deadline:
            feed = await store.get_json(args.catalog, public=True) or {"editions": []}
            newer = [
                entry
                for entry in feed["editions"]
                if (
                    entry["id"] == args.edition_id
                    if args.edition_id
                    else entry["slot"] > latest
                )
            ]
            if newer:
                entry = newer[0]
                if args.catalog == "data/manual-catalog.json":
                    state = await store.get_json(f"jobs/{entry['id']}/status.json")
                    if entry.get("publication_trigger") != "manual":
                        raise RuntimeError("Expected a manually published edition")
                    if not state or state.get("status") != "completed":
                        await asyncio.sleep(20)
                        continue
                durations = {
                    lang: entry["languages"][lang]["duration"] for lang in ("cn", "en")
                }
                if not all(0 < value <= 1200 for value in durations.values()):
                    raise RuntimeError(
                        "Automatically generated edition failed duration verification"
                    )
                result = {
                    "status": "passed",
                    "edition_id": entry["id"],
                    "slot": entry["slot"],
                    "published_at": entry["published_at"],
                    "durations": durations,
                    "publication_trigger": entry.get(
                        "publication_trigger", "scheduled"
                    ),
                }
                if args.editorial_format:
                    if entry.get("editorial_format") != args.editorial_format:
                        raise RuntimeError(
                            "The scheduled edition still used a different editorial format"
                        )
                    from station.models import (
                        NewsBriefs,
                        Script,
                        validate_briefs,
                        validate_script,
                    )

                    root = f"jobs/{entry['id']}"
                    package = await store.get_json(f"{root}/expanded-evidence.json")
                    briefs = NewsBriefs.model_validate(
                        await store.get_json(f"{root}/briefs.json")
                    )
                    validate_briefs(briefs, package["evidence"], ready=True)
                    for lang in ("cn", "en"):
                        script = Script.model_validate(
                            await store.get_json(f"{root}/{lang}/script.json")
                        )
                        validate_script(script, package["evidence"], lang, briefs)
                        if [
                            c["category"] for c in entry["languages"][lang]["chapters"]
                        ] != ["domestic", "international"]:
                            raise RuntimeError(
                                "Published audio metadata contains unexpected news sections"
                            )
                        offset = 0
                        expected = {}
                        from station.audio import duration

                        with tempfile.TemporaryDirectory(
                            prefix="meridian-timeline-"
                        ) as tmp:
                            for index, turn in enumerate(
                                t for c in script.chapters for t in c.turns
                            ):
                                path = Path(tmp) / f"{index:03d}.wav"
                                path.write_bytes(
                                    await store.get_bytes(
                                        f"{root}/{lang}/turns/{index:03d}.wav"
                                    )
                                )
                                seconds = await asyncio.to_thread(duration, path)
                                if turn.kind == "fact":
                                    timing = expected.setdefault(
                                        turn.topic_id, {"start": offset}
                                    )
                                    timing["end"] = offset + seconds
                                offset += seconds
                        previous_end = 0
                        for chapter in entry["languages"][lang]["chapters"]:
                            for headline in chapter["headlines"]:
                                timing = expected[headline["topic_id"]]
                                start, seconds = headline["start"], headline["duration"]
                                if (
                                    abs(start - timing["start"]) > 0.01
                                    or abs(seconds - (timing["end"] - timing["start"]))
                                    > 0.01
                                    or start < previous_end
                                    or seconds <= 0
                                    or start + seconds
                                    > entry["languages"][lang]["duration"]
                                    or not headline["sources"]
                                ):
                                    raise RuntimeError(
                                        "Story timestamps do not match the synthesized speech tracks"
                                    )
                                previous_end = start + seconds
                        if len(entry["languages"][lang]["hosts"]) != 2:
                            raise RuntimeError("Expected exactly two published hosts")
                    result["editorial_format"] = entry["editorial_format"]
                    result["topics"] = {
                        s.category: len(s.topics) for s in briefs.sections
                    }
                    result["focused_searches"] = len(package.get("expansions", []))
                    result["story_timestamps"] = (
                        "verified against actual synthesized WAV durations"
                    )
                    if entry["editorial_format"] in (
                        "two-host-balanced-v4",
                        "two-host-managed-v5",
                    ):
                        chapters = entry["languages"]["cn"]["chapters"]
                        counts = Counter(
                            h["sources"][0]["agency"]
                            for c in chapters
                            for h in c["headlines"]
                        )
                        international = Counter(
                            h["sources"][0]["agency"] for h in chapters[1]["headlines"]
                        )
                        if (
                            dict(counts) != entry["primary_source_counts"]
                            or max(international.values()) > 2
                            or len(chapters[0]["headlines"]) > 2
                            or (
                                sum(counts.values()) - counts.get("xinhua", 0) >= 2
                                and counts.get("xinhua", 0) * 2 > sum(counts.values())
                            )
                        ):
                            raise RuntimeError(
                                "Published source distribution does not match the balanced rundown"
                            )
                        result["primary_source_counts"] = dict(counts)
                    if entry["editorial_format"] == "two-host-managed-v5":
                        from station.harness import native_tools

                        execution = entry["editorial_execution"]
                        if execution["mode"] != "managed-copilot-harness":
                            raise RuntimeError(
                                "Expected actual managed Harness editorial production"
                            )
                        observed = set()
                        for phase in (
                            "collect",
                            "topics",
                            "expand",
                            "briefs",
                            "script-cn",
                            "script-en",
                        ):
                            receipt = await store.get_json(
                                f"{root}/harness/{phase}.json"
                            )
                            if not receipt or receipt["agent"] != execution["agent"]:
                                raise RuntimeError(
                                    "Missing managed Harness production record"
                                )
                            stage_tools = native_tools(
                                [
                                    item
                                    for response in receipt["responses"]
                                    for item in response["output"]
                                ]
                            )
                            if phase in ("collect", "expand"):
                                expected = (
                                    "collect_news"
                                    if phase == "collect"
                                    else "expand_news"
                                )
                                if expected not in receipt["adapter_tools"]:
                                    raise RuntimeError(
                                        "WebIQ adapter was not executed by the Harness"
                                    )
                            elif not {"task", "shell"} <= stage_tools:
                                raise RuntimeError(
                                    "No native delegation or sandbox execution in editorial stage"
                                )
                            observed.update(stage_tools)
                        if observed != set(execution["native_tools"]):
                            raise RuntimeError(
                                "Published capabilities differ from actual runtime events"
                            )
                        result["editorial_execution"] = execution
                output.write_text(json.dumps(result, indent=2))
                print(json.dumps(result), flush=True)
                return
            await asyncio.sleep(20)
        result = {
            "status": "unverified",
            "message": "No requested edition within verification window"
            if args.edition_id
            else "No new automatic edition within verification window",
            "baseline_slot": latest,
        }
        output.write_text(json.dumps(result, indent=2))
        raise TimeoutError(result["message"])
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
