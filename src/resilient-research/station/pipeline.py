import asyncio
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from station import audio, editor, harness, news, retention
from station.models import NewsBriefs, Script, topic_agency, validate_briefs, validate_script
from station.timeutil import current_slot


async def produce(store, slot: datetime, cancel=None, *, manual: bool = False) -> dict:
    retention.require_current(slot)
    slot_id = slot.strftime("%Y%m%d/%H%M")
    root = f"jobs/{slot_id}"
    managed = bool(os.environ.get("EDITORIAL_AGENT_NAME"))
    if await store.get_json(f"retired/{slot_id}.json"):
        raise ValueError("This broadcast has been permanently deleted")
    existing = await store.get_json(f"{root}/status.json")
    if existing and existing.get("status") == "completed":
        return existing
    # The SDK task identity prevents ordinary duplicate executions; the Blob lease
    # also fences operators invoking the same slot from different sessions/processes.
    async with store.lock(slot_id.replace("/", "-")) as renewal:

        async def checkpoint(phase):
            retention.require_current(slot)
            if cancel and cancel.is_set():
                raise asyncio.CancelledError()
            if renewal.done():
                renewal.result()
            await store.put_json(f"{root}/status.json", {"status": "running", "phase": phase, "slot": slot.isoformat()})

        def trace(phase):
            async def save(record):
                await store.put_json(f"{root}/harness/{phase}.json", record)

            return save if managed else None

        try:
            await checkpoint("collecting")
            package = await store.get_json(f"{root}/evidence.json")
            if package is None:
                package = await harness.research("collect", trace=trace("collect")) if managed else await news.collect()
                await store.put_json(f"{root}/evidence.json", package, immutable=True)
            await checkpoint("organizing")
            initial_data = await store.get_json(f"{root}/topics.json")
            if initial_data is None:
                initial = await editor.organize(package, trace=trace("topics"))
                initial_data = initial.model_dump()
                await store.put_json(f"{root}/topics.json", initial_data, immutable=True)
            initial = NewsBriefs.model_validate(initial_data)
            await checkpoint("expanding")
            expanded = await store.get_json(f"{root}/expanded-evidence.json")
            if expanded is None:
                expanded = (
                    await harness.research("expand", package=package, initial=initial, trace=trace("expand"))
                    if managed
                    else await news.expand(package, initial)
                )
                await store.put_json(f"{root}/expanded-evidence.json", expanded, immutable=True)
            package = expanded
            await checkpoint("briefing")
            briefs_data = await store.get_json(f"{root}/briefs.json")
            if briefs_data is None:
                briefs = await editor.organize(package, initial, trace=trace("briefs"))
                briefs_data = briefs.model_dump()
                await store.put_json(f"{root}/briefs.json", briefs_data, immutable=True)
            briefs = NewsBriefs.model_validate(briefs_data)
            validate_briefs(briefs, package["evidence"], ready=True)
            catalog = await store.get_json("data/catalog.json", public=True) or {"editions": []}
            extras = await store.get_json("data/manual-catalog.json", public=True) or {"editions": []}
            previous = max(
                (e for e in [*catalog["editions"], *extras["editions"]] if e["slot"] < slot.isoformat()),
                key=lambda e: e["slot"],
                default=None,
            )
            editions = {}
            chinese = None
            for language in ("cn", "en"):
                await checkpoint(f"script-{language}")
                script_data = await store.get_json(f"{root}/{language}/script.json")
                if script_data is None:
                    script = await editor.draft(
                        language,
                        package,
                        slot.isoformat(),
                        previous.get("continuity") if previous else None,
                        chinese,
                        briefs,
                        trace=trace(f"script-{language}"),
                    )
                    script_data = script.model_dump()
                    await store.put_json(f"{root}/{language}/script.json", script_data, immutable=True)
                script = Script.model_validate(script_data)
                validate_script(script, package["evidence"], language, briefs)
                if language == "cn":
                    chinese = script_data
                await checkpoint(f"audio-{language}")
                media_name = f"{language}/{slot_id}.mp4"
                meta = await store.get_json(f"{root}/{language}/audio.json")
                if meta is None:
                    with tempfile.TemporaryDirectory(prefix="meridian-") as temp:
                        folder = Path(temp)
                        tracks = []
                        chapters = []
                        offset = 0.0
                        by_id = {e["id"]: e for e in package["evidence"]}
                        primary_agencies = {t.id: topic_agency(t, by_id) for s in briefs.sections for t in s.topics}
                        turn_number = 0
                        for chapter in script.chapters:
                            chapter_start = offset
                            topic_times = {}
                            for turn in chapter.turns:
                                if turn.kind == "fact" and turn.topic_id not in topic_times:
                                    topic_times[turn.topic_id] = {"start": offset, "evidence_ids": []}
                                await checkpoint(f"audio-{language}-{turn_number}")
                                track_name = f"{root}/{language}/turns/{turn_number:03}.wav"
                                wav = await store.get_bytes(track_name)
                                if wav is None:
                                    wav = await audio.synthesize(turn.text, language, turn.speaker)
                                    await store.put_bytes(track_name, wav, "audio/wav", immutable=True)
                                path = folder / f"{turn_number:03}.wav"
                                path.write_bytes(wav)
                                offset += await asyncio.to_thread(audio.duration, path)
                                if turn.kind == "fact":
                                    topic_times[turn.topic_id]["end"] = offset
                                    topic_times[turn.topic_id]["evidence_ids"].extend(turn.evidence_ids)
                                tracks.append(path)
                                turn_number += 1
                            headlines = []
                            for headline in chapter.headlines:
                                timing = topic_times[headline.topic_id]
                                ref_ids = dict.fromkeys([*headline.evidence_ids, *timing["evidence_ids"]])
                                refs = [by_id[i] for i in ref_ids]
                                refs.sort(
                                    key=lambda r: (
                                        r["agency"] != primary_agencies[headline.topic_id],
                                        not r["reported_at"],
                                    )
                                )
                                headlines.append(
                                    {
                                        "topic_id": headline.topic_id,
                                        "title": headline.title,
                                        "start": timing["start"],
                                        "duration": timing["end"] - timing["start"],
                                        "reported_at": next((r["reported_at"] for r in refs if r["reported_at"]), None),
                                        "time_basis": "updated" if any(r["reported_at"] for r in refs) else "unknown",
                                        "sources": list(
                                            {
                                                r["url"]: {"agency": r["agency"], "url": r["url"], "title": r["title"]}
                                                for r in refs
                                            }.values()
                                        ),
                                    }
                                )
                            chapters.append(
                                {
                                    "category": chapter.category,
                                    "title": chapter.title,
                                    "start": chapter_start,
                                    "duration": offset - chapter_start,
                                    "headlines": headlines,
                                }
                            )
                        audio.check_duration(chapters, offset)
                        output = folder / "broadcast.mp4"
                        total = await audio.assemble(tracks, output)
                        audio.check_duration(chapters, total)
                        media = output.read_bytes()
                        await store.put_bytes(media_name, media, "audio/mp4", immutable=True)
                        # Public audio copies are intentionally published; source passages and
                        # intermediate checkpoints remain in the private broadcasts container.
                        await store.put_bytes(f"media/{media_name}", media, "audio/mp4", public=True, immutable=True)
                        meta = {
                            "title": script.title,
                            "duration": total,
                            "chapters": chapters,
                            "audio_url": f"media/{media_name}",
                            "continuity": script.continuity,
                            "hosts": ["Wei", "Mei"] if language == "cn" else ["Grant", "Harper"],
                            "speech_tempo": audio.VOICE_TEMPOS[language],
                        }
                        await store.put_json(f"{root}/{language}/audio.json", meta, immutable=True)
                editions[language] = meta
            await checkpoint("publishing")
            execution = {"mode": "hosted-model"}
            if managed:
                tools = set()
                for phase in ("collect", "topics", "expand", "briefs", "script-cn", "script-en"):
                    receipt = await store.get_json(f"{root}/harness/{phase}.json")
                    if not receipt or receipt["agent"] != os.environ["EDITORIAL_AGENT_NAME"]:
                        raise RuntimeError("Refuse managed publication without its actual Harness execution records")
                    observed = set(receipt["native_tools"])
                    if phase not in ("collect", "expand") and not {"task", "shell"} <= observed:
                        raise RuntimeError("Refuse managed publication without native subagents and sandbox execution")
                    tools.update(observed)
                execution = {
                    "mode": "managed-copilot-harness",
                    "agent": os.environ["EDITORIAL_AGENT_NAME"],
                    "harness": "microsoft_copilot_preview",
                    "native_tools": sorted(tools),
                }
            entry = {
                "id": slot_id,
                "slot": slot.isoformat(),
                "next_slot": (current_slot(slot) + timedelta(minutes=30)).isoformat(),
                "published_at": datetime.now(UTC).isoformat(),
                "news_cutoff": package["collected_at"],
                "missing_agencies": package["missing_agencies"],
                "source_gaps": package["failures"],
                "ranking_method": package["ranking_method"],
                "languages": editions,
                "continuity": {lang: editions[lang]["continuity"] for lang in editions},
                "ai_generated": True,
                "editorial_format": "two-host-managed-v5" if managed else "two-host-balanced-v4",
                "editorial_execution": execution,
                "publication_trigger": "manual" if manual else "scheduled",
                "primary_source_counts": dict(
                    Counter(h["sources"][0]["agency"] for c in editions["cn"]["chapters"] for h in c["headlines"])
                ),
            }
            await store.put_json(f"{root}/edition.json", entry, immutable=True)
            await store.publish(entry)
            result = {
                "status": "completed",
                "slot": slot.isoformat(),
                "output": {
                    "edition_id": slot_id,
                    "website": os.environ.get("WEBSITE_URL", ""),
                    "durations": {lang: editions[lang]["duration"] for lang in editions},
                },
            }
            await store.put_json(f"{root}/status.json", result)
            return result
        except asyncio.CancelledError:
            # Do not write a terminal failure during cooperative shutdown.
            raise
        except retention.BroadcastExpiredError:
            # Cleanup owns expiry; do not recreate yesterday's status or artifacts.
            raise
        except Exception as exc:
            await store.put_json(
                f"{root}/status.json",
                {
                    "status": "failed",
                    "slot": slot.isoformat(),
                    "error_type": type(exc).__name__,
                    "message": "Generation failed; previous broadcast remains available. Check hosted logs.",
                },
            )
            raise
