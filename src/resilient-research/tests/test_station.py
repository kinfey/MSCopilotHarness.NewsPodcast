import asyncio
import copy
import json
import math
import struct
import wave
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.requests import Request

from station import audio, editor, news, pipeline, retention
from station.models import NewsBriefs, Script, TopicBrief, validate_briefs, validate_script
from station.storage import BlobStore
from station.timeutil import current_slot, manual_slot, parse_slot


@pytest.fixture(autouse=True)
def station_test_day(monkeypatch):
    monkeypatch.setattr(retention, "today_key", lambda: "20261016")


def test_slot_beijing_midnight_and_future_alignment():
    midnight = current_slot(datetime(2026, 10, 15, 16, 14, tzinfo=UTC))
    assert midnight.strftime("%Y%m%d/%H%M") == "20261016/0000"
    assert parse_slot("2026-10-16T00:30:00+08:00").minute == 30
    for value in ["2026-10-16T00:15:00+08:00", "2026-10-16T00:00:01+08:00", "2026-10-16T00:00:00"]:
        with pytest.raises(ValueError):
            parse_slot(value)


def test_manual_minute_keeps_automatic_alignment_and_next_update_boundary():
    stamp = manual_slot(datetime(2026, 10, 15, 16, 14, 29, tzinfo=UTC))
    with pytest.raises(ValueError):
        parse_slot(stamp.isoformat())
    assert parse_slot(stamp.isoformat(), aligned=False) == stamp
    with pytest.raises(ValueError):
        parse_slot("2026-10-16T00:14:01+08:00", aligned=False)
    script = editor.add_station_frames(Script.model_validate(script_data(framed=False)), stamp.isoformat())
    assert "0点14分" in script.chapters[0].turns[0].text
    assert "0点30分" in script.chapters[-1].turns[-2].text


def test_news_provenance_freshness_and_timestamp_meaning():
    now = datetime(2026, 10, 16, tzinfo=UTC)
    base = {
        "title": "Original news title",
        "url": "https://apnews.com/article/example",
        "content": "Grounding facts",
        "lastUpdatedAt": "2026-10-15T23:00:00Z",
    }
    item = news.normalize_result(base, "domestic", now, 0)
    assert item["agency"] == "ap" and item["time_basis"] == "updated"
    assert item["reported_at"].startswith("2026-10-15")
    for url in [
        "https://apnews.com.evil.test/a",
        "https://evil.test/a",
        "http://apnews.com/a",
        "https://user:password@apnews.com/a",
    ]:
        assert news.normalize_result({**base, "url": url}, "domestic", now, 0) is None
    for stamp in ["2026-10-14T23:00:00Z", "2026-10-17T00:00:00Z", "not-a-date"]:
        assert news.normalize_result({**base, "lastUpdatedAt": stamp}, "domestic", now, 0) is None
    unknown = news.normalize_result({**base, "lastUpdatedAt": None, "crawledAt": now.isoformat()}, "domestic", now, 0)
    assert unknown["reported_at"] is None and unknown["time_basis"] == "unknown"


def script_data(lang="cn", framed=True):
    chapters = []
    for category in ["domestic", "international"]:
        turns = [
            {
                "speaker": "male",
                "text": "First original factual summary.",
                "kind": "fact",
                "topic_id": category,
                "evidence_ids": [category],
            },
            {
                "speaker": "female",
                "text": "Another attributed factual detail.",
                "kind": "fact",
                "topic_id": category,
                "evidence_ids": [category],
            },
            {
                "speaker": "male",
                "text": "Previously reported factual background.",
                "kind": "fact",
                "topic_id": category,
                "evidence_ids": [category],
            },
            {
                "speaker": "female",
                "text": "We will return in the next edition.",
                "kind": "transition",
                "topic_id": None,
                "evidence_ids": [],
            },
        ]
        chapters.append(
            {
                "category": category,
                "title": category,
                "headlines": [{"title": category, "topic_id": category, "evidence_ids": [category]}],
                "turns": turns,
            }
        )
    data = {
        "language": lang,
        "title": "Service test broadcast",
        "chapters": chapters,
        "continuity": "A continuity note",
    }
    return (
        editor.add_station_frames(Script.model_validate(data), "2026-10-16T00:00:00+08:00").model_dump()
        if framed
        else data
    )


def evidence():
    return [
        {
            "id": c,
            "category": c,
            "agency": "ap",
            "title": c,
            "content": "Facts",
            "url": f"https://apnews.com/article/{c}",
            "reported_at": "2026-10-16T00:00:00+00:00",
            "time_basis": "updated",
        }
        for c in ["domestic", "international"]
    ]


def briefs_data():
    return {
        "sections": [
            {
                "category": item["category"],
                "topics": [
                    {
                        "id": item["id"],
                        "title": item["title"],
                        "evidence_ids": [item["id"]],
                        "facts": [
                            {"text": "Main reported development.", "evidence_ids": [item["id"]]},
                            {"text": "A sourced detail.", "evidence_ids": [item["id"]]},
                        ],
                        "missing_details": [],
                        "search_queries": [],
                    }
                ],
            }
            for item in evidence()
        ]
    }


def test_script_requires_citations_host_dialogue_and_section_order():
    valid = script_data()
    validate_script(Script.model_validate(valid), evidence(), "cn")
    for modify in [
        lambda s: s["chapters"][0]["turns"][2].update(evidence_ids=["made-up"]),
        lambda s: s["chapters"][0]["turns"][2].update(evidence_ids=[]),
        lambda s: s["chapters"][0]["turns"][2].update(evidence_ids=["international"]),
        lambda s: s["chapters"][0]["turns"][2].update(speaker="context"),
        lambda s: s["chapters"][0]["turns"][2].update(kind="analysis"),
        lambda s: s["chapters"][0]["turns"][3].update(speaker="male"),
        lambda s: s["chapters"][0]["turns"][5].update(evidence_ids=["domestic"]),
        lambda s: s["chapters"][0]["turns"][0].update(kind="transition"),
        lambda s: s["chapters"][1]["turns"][-1].update(kind="transition"),
        lambda s: s["chapters"][1]["turns"][3].update(kind="opening"),
        lambda s: s["chapters"].append({**s["chapters"][0], "category": "sports"}),
        lambda s: s["chapters"].reverse(),
    ]:
        invalid = copy.deepcopy(valid)
        modify(invalid)
        with pytest.raises(ValueError):
            validate_script(Script.model_validate(invalid), evidence(), "cn")


def test_briefs_reject_discovery_padding_and_unsubstantiated_topics():
    data = briefs_data()
    validate_briefs(NewsBriefs.model_validate(data), evidence(), ready=True)
    discovery = evidence()
    discovery[0]["discovery_only"] = True
    with pytest.raises(ValueError, match="cannot substantiate"):
        validate_briefs(NewsBriefs.model_validate(data), discovery)
    thin = copy.deepcopy(data)
    thin["sections"][0]["topics"][0]["facts"] = []
    validate_briefs(NewsBriefs.model_validate(thin), discovery)
    with pytest.raises(ValueError, match="Insufficient"):
        validate_briefs(NewsBriefs.model_validate(thin), discovery, ready=True)
    undated = evidence()
    undated[0]["reported_at"] = None
    with pytest.raises(ValueError, match="fresh"):
        validate_briefs(NewsBriefs.model_validate(data), undated, ready=True)
    repeated = evidence()
    repeated[1]["url"] = repeated[0]["url"]
    with pytest.raises(ValueError, match="Consolidate"):
        validate_briefs(NewsBriefs.model_validate(data), repeated, ready=True)
    wrong = copy.deepcopy(data)
    wrong["sections"][0]["topics"][0]["facts"][0]["evidence_ids"] = ["international"]
    with pytest.raises(ValueError, match="topic evidence"):
        validate_briefs(NewsBriefs.model_validate(wrong), evidence())


def test_script_completes_topics_in_brief_order_without_interleaving():
    data = script_data()
    extra = {**evidence()[0], "id": "domestic-second", "url": "https://apnews.com/article/second"}
    refs = [*evidence(), extra]
    chapter = data["chapters"][0]
    chapter["headlines"].append({"title": "Second event", "topic_id": "second", "evidence_ids": [extra["id"]]})
    second = {
        "speaker": "female",
        "text": "A separate factual event.",
        "kind": "fact",
        "topic_id": "second",
        "evidence_ids": [extra["id"]],
    }
    chapter["turns"].insert(5, second)
    validate_script(Script.model_validate(data), refs, "cn")
    chapter["turns"].insert(6, copy.deepcopy(chapter["turns"][2]))
    with pytest.raises(ValueError, match="jump back"):
        validate_script(Script.model_validate(data), refs, "cn")
    original = script_data()
    prepared = briefs_data()
    prepared["sections"][0]["topics"][0]["id"] = "different-topic"
    with pytest.raises(ValueError, match="prepared topic order"):
        validate_script(Script.model_validate(original), evidence(), "cn", NewsBriefs.model_validate(prepared))


def test_station_frames_introduce_both_hosts_and_roll_over_midnight():
    for language, names in (("cn", ("我是魏", "我是梅")), ("en", ("I'm Grant", "I'm Harper"))):
        script = editor.add_station_frames(
            Script.model_validate(script_data(language, framed=False)), "2026-10-16T23:30:00+08:00"
        )
        validate_script(script, evidence(), language)
        turns = [t for chapter in script.chapters for t in chapter.turns]
        assert names[0] in turns[0].text and names[1] in turns[1].text
        assert ("人工智能" if language == "cn" else "AI-generated") in turns[1].text
        assert ("10月17日0点整" if language == "cn" else "12:00 a.m. on October 17") in turns[-2].text
        assert ("感谢" if language == "cn" else "Thank you") in turns[-2].text
        assert ("再会" if language == "cn" else "Take care") in turns[-1].text


async def test_sparse_topic_expands_with_web_fallback_and_filters_unusable_results(monkeypatch):
    now = datetime.now(UTC)
    raw = {
        "title": "China registration rules updated",
        "url": "https://english.news.cn/article/details",
        "content": "",
        "lastUpdatedAt": now.isoformat(),
    }
    seed = news.normalize_result(raw, "domestic", now, 0)
    international_seed = news.normalize_result(raw, "international", now, 0)
    package = {
        "evidence": [seed, international_seed],
        "collected_at": now.isoformat(),
        "missing_agencies": [],
        "failures": [],
    }
    briefs = NewsBriefs.model_validate(
        {
            "sections": [
                {
                    "category": category,
                    "topics": [
                        {
                            "id": category,
                            "title": raw["title"],
                            "evidence_ids": [seed["id"] if category == "domestic" else international_seed["id"]],
                            "facts": [],
                            "missing_details": ["Specific new measures"],
                            "search_queries": [],
                        }
                    ],
                }
                for category in ["domestic", "international"]
            ]
        }
    )
    good = {**raw, "url": "https://apnews.com/article/registration-details", "content": "Substantive article details."}
    old = {**good, "url": "https://apnews.com/article/old", "lastUpdatedAt": "2020-01-01T00:00:00Z"}
    homepage = {**good, "title": "Homepage | AFP.com", "url": "https://www.afp.com/en/homepage"}
    fake = {**good, "url": "https://apnews.com.evil.test/a"}
    sport = {**good, "title": "Football tournament results"}
    request = AsyncMock(
        side_effect=[
            httpx.Response(200, json={"newsResults": [homepage, fake, old, sport]}),
            httpx.Response(200, json={"webResults": [good, homepage, old]}),
        ]
        * 2
    )
    monkeypatch.setenv("WEBIQ_API_KEY", "test-placeholder")
    monkeypatch.setattr(news, "post_with_retry", request)
    monkeypatch.setattr(news.asyncio, "sleep", AsyncMock())
    expanded = await news.expand(package, briefs)
    assert request.await_count == 4
    assert request.await_args_list[1].args[1].endswith("/search/web")
    assert raw["title"] in request.await_args_list[0].kwargs["json"]["query"]
    assert all("site:news.cn" in call.kwargs["json"]["query"] for call in request.await_args_list)
    added = [item for item in expanded["evidence"] if item["id"] not in {seed["id"], international_seed["id"]}]
    assert len(added) == 2 and all(item["url"] == good["url"] for item in added)
    assert all(item["status"] == "found" for item in expanded["expansions"])


async def test_collection_queries_only_domestic_and_international(monkeypatch):
    now = datetime.now(UTC).isoformat()

    async def result(client, endpoint, **kwargs):
        query = kwargs["json"]["query"]
        domain = next(
            (domains[0] for domains in news.AGENCIES.values() if f"site:{domains[0]}" in query),
            "news.cn",
        )
        return httpx.Response(
            200,
            json={
                "newsResults": [
                    {
                        "title": f"A factual report {index}",
                        "url": f"https://{domain}/article/report-{index}",
                        "content": "Article body facts",
                        "lastUpdatedAt": now,
                    }
                    for index in range(2)
                ]
            },
        )

    requests = AsyncMock(side_effect=result)
    monkeypatch.setenv("WEBIQ_API_KEY", "test-placeholder")
    monkeypatch.setattr(news, "post_with_retry", requests)
    monkeypatch.setattr(news.asyncio, "sleep", AsyncMock())
    package = await news.collect()
    assert {item["category"] for item in package["evidence"]} == {"domestic", "international"}
    assert requests.await_count == 8
    assert all("sports" not in call.kwargs["json"]["query"] for call in requests.await_args_list)


async def test_underrepresented_international_agencies_get_focused_searches(monkeypatch):
    now = datetime.now(UTC).isoformat()

    async def result(client, endpoint, **kwargs):
        query = kwargs["json"]["query"]
        agency = next((a for a, domains in news.AGENCIES.items() if f"site:{domains[0]}" in query), "xinhua")
        domain = news.AGENCIES[agency][0]
        focused = query.startswith("latest world news")
        articles = [
            {
                "title": f"Factual development {index}",
                "url": f"https://{domain}/article/report-{index}"
                if focused or agency == "xinhua"
                else f"https://{domain}/",
                "content": "Substantive reported facts.",
                "lastUpdatedAt": now,
            }
            for index in range(5 if agency == "xinhua" else 2)
        ]
        if focused:
            articles.append({**articles[0], "url": "https://apnews.com.evil.test/article/fake"})
        return httpx.Response(200, json={"newsResults" if endpoint.endswith("/news") else "webResults": articles})

    requests = AsyncMock(side_effect=result)
    monkeypatch.setenv("WEBIQ_API_KEY", "test-placeholder")
    monkeypatch.setattr(news, "post_with_retry", requests)
    monkeypatch.setattr(news.asyncio, "sleep", AsyncMock())
    package = await news.collect()
    focused = [
        call.kwargs["json"]["query"]
        for call in requests.await_args_list
        if call.kwargs["json"]["query"].startswith("latest")
    ]
    assert len(focused) == 3
    international = [r for r in package["evidence"] if r["category"] == "international"]
    assert {r["agency"] for r in international if not r["discovery_only"]} == set(news.AGENCIES)
    assert sum(r["agency"] == "xinhua" for r in international) == 3
    assert all(news.agency_for(r["url"]) for r in international)


def test_balanced_rundown_reserves_verified_alternative_agencies_without_padding():
    sections, refs = [], []
    for category, agencies in (
        ("domestic", ["xinhua"] * 3),
        ("international", ["xinhua"] * 5 + ["ap", "afp", "bloomberg"]),
    ):
        topics = []
        for index, agency in enumerate(agencies):
            ref = {
                **evidence()[0],
                "id": f"{category}-{index}",
                "category": category,
                "agency": agency,
                "url": f"https://{news.AGENCIES[agency][0]}/article/{category}-{index}",
            }
            refs.append(ref)
            topics.append(
                {
                    "id": ref["id"],
                    "title": f"Verified event {index}",
                    "evidence_ids": [ref["id"]],
                    "facts": [
                        {"text": text, "evidence_ids": [ref["id"]]}
                        for text in ("Main development.", "Reported detail.")
                    ],
                    "missing_details": [],
                    "search_queries": [],
                }
            )
        sections.append({"category": category, "topics": topics})
    candidates = NewsBriefs.model_validate({"sections": sections})
    validate_briefs(candidates, refs, ready=True)
    balanced = editor.balance_briefs(candidates, refs)
    by_id = {r["id"]: r for r in refs}
    assert len(balanced.sections[0].topics) == 2
    assert [editor.topic_agency(t, by_id) for t in balanced.sections[1].topics] == ["xinhua", "ap", "afp", "bloomberg"]
    sparse = copy.deepcopy(sections)
    sparse[1]["topics"] = sparse[1]["topics"][:6]
    reduced = editor.balance_briefs(NewsBriefs.model_validate({"sections": sparse}), refs)
    assert [editor.topic_agency(t, by_id) for t in reduced.sections[1].topics] == ["xinhua", "xinhua", "ap"]
    validate_briefs(reduced, refs, ready=True)
    supported_alternatives = copy.deepcopy(sections)
    supported_alternatives[1]["topics"] = supported_alternatives[1]["topics"][:7]
    not_dominated = editor.balance_briefs(NewsBriefs.model_validate({"sections": supported_alternatives}), refs)
    assert [editor.topic_agency(t, by_id) for t in not_dominated.sections[1].topics] == ["ap", "afp"]
    validate_briefs(not_dominated, refs, ready=True)
    dated_ap = balanced.sections[1].topics[1].model_dump()
    background = {**refs[3], "id": "undated-background", "reported_at": None}
    dated_ap["facts"].extend(
        [
            {"text": "Previously reported background.", "evidence_ids": [background["id"]]},
            {"text": "Further background.", "evidence_ids": [background["id"]]},
        ]
    )
    dated_ap = TopicBrief.model_validate(dated_ap)
    assert editor.topic_agency(dated_ap, {**by_id, background["id"]: background}) == "ap"


def test_mai_voices_escape_markup_and_duration_gate():
    for language, speakers in audio.VOICES.items():
        for speaker, voice in speakers.items():
            result = audio.ssml("A & B <news>", language, speaker)
            assert voice + ":MAI-Voice-2.1" in result
            assert "A &amp; B &lt;news&gt;" in result
    audio.check_duration([{"duration": 600}, {"duration": 600}], 1200)
    for total in [1200.01, 0, -1]:
        with pytest.raises(ValueError):
            audio.check_duration([{"duration": 10}], total)


def write_wav(path: Path, seconds=0.2):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(
            b"".join(
                struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 24000)))
                for i in range(int(24000 * seconds))
            )
        )


async def test_mp4_is_real_aac_audio_not_renamed_mp3(tmp_path):
    tracks = [tmp_path / "000.wav", tmp_path / "001.wav"]
    for track in tracks:
        write_wav(track)
    output = tmp_path / "broadcast.mp4"
    seconds = await audio.assemble(tracks, output)
    assert 0.3 < seconds < 1
    assert b"ftyp" in output.read_bytes()[:32]


async def test_only_chinese_wei_is_accelerated_without_pitch_shift(tmp_path, monkeypatch):
    original = tmp_path / "original.wav"
    write_wav(original, seconds=3)
    raw = original.read_bytes()
    monkeypatch.setenv("SPEECH_REGION", "swedencentral")
    monkeypatch.setenv("SPEECH_KEY", "test-key")
    monkeypatch.setattr(audio, "post_with_retry", AsyncMock(return_value=SimpleNamespace(content=raw)))
    for language, speakers in audio.VOICES.items():
        for speaker in speakers:
            rendered = await audio.synthesize("Test news.", language, speaker)
            if (language, speaker) != ("cn", "male"):
                assert rendered == raw
                continue
            output = tmp_path / "wei.wav"
            output.write_bytes(rendered)
            assert audio.duration(output) == pytest.approx(3 / 1.25, abs=0.05)
            with wave.open(str(output), "rb") as track:
                assert (track.getnchannels(), track.getsampwidth(), track.getframerate()) == (1, 2, 24000)
                samples = struct.unpack(f"<{track.getnframes()}h", track.readframes(track.getnframes()))
            crossings = sum(a <= 0 < b for a, b in pairwise(samples))
            assert crossings / (len(samples) / 24000) == pytest.approx(440, abs=3)


def test_wei_tempo_processing_errors_are_not_hidden():
    with pytest.raises(audio.subprocess.CalledProcessError):
        audio.apply_voice_tempo(b"RIFF-invalid", "cn", "male")


class MemoryStore:
    def __init__(self):
        self.data = {}
        self.published = []
        self.fail_publish = False

    async def get_json(self, name, public=False):
        return copy.deepcopy(self.data.get((public, name)))

    async def close(self):
        pass

    async def put_json(self, name, value, public=False, immutable=False):
        if not immutable or (public, name) not in self.data:
            self.data[public, name] = copy.deepcopy(value)

    async def get_bytes(self, name, public=False):
        return self.data.get((public, name))

    async def put_bytes(self, name, data, *args, public=False, immutable=False):
        if not immutable or (public, name) not in self.data:
            self.data[public, name] = data

    @asynccontextmanager
    async def lock(self, name):
        renewal = asyncio.create_task(asyncio.sleep(1000))
        try:
            yield renewal
        finally:
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)

    async def publish(self, edition):
        if self.fail_publish:
            raise RuntimeError("Simulated publication interruption")
        self.published.append(copy.deepcopy(edition))


@pytest.mark.parametrize("managed", [False, True])
async def test_pipeline_resumes_tracks_and_publishes_both_languages_atomically(monkeypatch, tmp_path, managed):
    if managed:
        monkeypatch.setenv("EDITORIAL_AGENT_NAME", "test-newsroom")
    else:
        monkeypatch.delenv("EDITORIAL_AGENT_NAME", raising=False)
    package = {
        "evidence": evidence(),
        "collected_at": "2026-10-16T00:00:00Z",
        "missing_agencies": ["afp"],
        "failures": [],
        "ranking_method": "proxy",
    }
    collection = AsyncMock(return_value=package)
    organize = AsyncMock(return_value=NewsBriefs.model_validate(briefs_data()))
    expand = AsyncMock(return_value=package)

    draft = AsyncMock(side_effect=lambda language, *args, **kwargs: Script.model_validate(script_data(language)))
    wav_path = tmp_path / "test.wav"
    write_wav(wav_path)
    synth = AsyncMock(return_value=wav_path.read_bytes())

    async def audit(trace):
        if trace:
            await trace({"agent": "test-newsroom", "native_tools": ["task", "shell"], "responses": []})

    async def managed_research(operation, *, trace, **_kwargs):
        await audit(trace)
        return await (collection() if operation == "collect" else expand())

    async def audited_organize(*args, trace):
        await audit(trace)
        return await organize(*args)

    async def audited_draft(*args, trace):
        await audit(trace)
        return await draft(*args)

    monkeypatch.setattr(pipeline.news, "collect", collection)
    monkeypatch.setattr(pipeline.news, "expand", expand)
    monkeypatch.setattr(pipeline.harness, "research", managed_research)
    monkeypatch.setattr(pipeline.editor, "organize", audited_organize)
    monkeypatch.setattr(pipeline.editor, "draft", audited_draft)
    monkeypatch.setattr(pipeline.audio, "synthesize", synth)
    store = MemoryStore()
    store.fail_publish = True
    slot = parse_slot("2026-10-16T00:00:00+08:00")
    with pytest.raises(RuntimeError):
        await pipeline.produce(store, slot)
    assert len(store.published) == 0
    assert synth.await_count == 24
    if managed:
        key = (False, "jobs/20261016/0000/harness/topics.json")
        receipt = store.data.pop(key)
        with pytest.raises(RuntimeError, match="actual Harness execution records"):
            await pipeline.produce(store, slot)
        store.data[key] = receipt
    store.fail_publish = False
    result = await pipeline.produce(store, slot)
    assert result["status"] == "completed"
    assert synth.await_count == 24 and collection.await_count == 1 and draft.await_count == 2
    assert organize.await_count == 2 and expand.await_count == 1
    assert draft.await_args_list[0].args[-1] == NewsBriefs.model_validate(briefs_data())
    assert set(store.published[0]["languages"]) == {"cn", "en"}
    assert store.published[0]["editorial_execution"]["mode"] == (
        "managed-copilot-harness" if managed else "hosted-model"
    )
    assert store.published[0]["languages"]["cn"]["audio_url"] == "media/cn/20261016/0000.mp4"
    assert {call.args[2] for call in synth.await_args_list} == {"male", "female"}
    for language in ("cn", "en"):
        metadata = store.published[0]["languages"][language]
        domestic, international = metadata["chapters"]
        assert domestic["headlines"][0]["start"] == pytest.approx(0.4)
        assert domestic["headlines"][0]["duration"] == pytest.approx(0.6)
        assert international["headlines"][0]["start"] == pytest.approx(1.2)
        assert international["headlines"][0]["duration"] == pytest.approx(0.6)
        assert international["headlines"][0]["start"] + international["headlines"][0]["duration"] < metadata["duration"]
    await pipeline.produce(store, slot)
    assert len(store.published) == 1
    extra_slot = parse_slot("2026-10-16T00:14:00+08:00", aligned=False)
    await pipeline.produce(store, extra_slot, manual=True)
    assert store.published[1]["publication_trigger"] == "manual"
    assert store.published[1]["next_slot"] == "2026-10-16T00:30:00+08:00"
    assert store.published[1]["languages"]["cn"]["audio_url"] == "media/cn/20261016/0014.mp4"
    assert store.published[0]["languages"]["cn"]["audio_url"] == "media/cn/20261016/0000.mp4"


async def test_publication_never_regresses_when_older_job_finishes_last():
    store = MemoryStore()
    store.data[True, "data/catalog.json"] = {"editions": [{"id": "new", "slot": "2026-10-16T01:00:00+08:00"}]}
    await BlobStore.publish(store, {"id": "old", "slot": "2026-10-16T00:30:00+08:00"})
    assert [e["id"] for e in store.data[True, "data/catalog.json"]["editions"]] == ["new", "old"]
    await BlobStore.publish(
        store, {"id": "manual", "slot": "2026-10-16T01:14:00+08:00", "publication_trigger": "manual"}
    )
    assert [e["id"] for e in store.data[True, "data/catalog.json"]["editions"]] == ["new", "old"]
    assert store.data[True, "data/manual-catalog.json"]["editions"][0]["id"] == "manual"


async def test_generate_now_is_current_minute_and_rejects_supplied_slots(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    import main

    store = MemoryStore()
    start = AsyncMock()
    stamp = parse_slot("2026-10-16T00:14:00+08:00", aligned=False)
    monkeypatch.setattr(main, "manual_slot", lambda: stamp)
    monkeypatch.setattr(main.BlobStore, "from_env", lambda: store)
    monkeypatch.setattr(main, "broadcast", SimpleNamespace(start=start))

    def request(body):
        return Request(
            {"type": "http", "method": "POST", "path": "/", "headers": [], "state": {"invocation_id": "manual-test"}},
            AsyncMock(return_value={"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}),
        )

    result = await main.invoke(request({"action": "generate_now"}))
    assert result.status_code == 202
    assert json.loads(result.body)["slot"] == stamp.isoformat()
    assert start.await_args.kwargs["input"] == {"slot": stamp.isoformat(), "manual": True}
    for body in (
        {"action": "generate_now", "slot": "2099-01-01T00:00:00+08:00"},
        {"action": "generate", "slot": stamp.isoformat()},
    ):
        assert (await main.invoke(request(body))).status_code == 400
    assert start.await_count == 1


async def test_deleted_broadcast_cannot_be_regenerated(monkeypatch):
    store = MemoryStore()
    store.data[False, "retired/20261016/0000.json"] = {"deleted": True}
    collection = AsyncMock()
    monkeypatch.setattr(pipeline.news, "collect", collection)
    with pytest.raises(ValueError, match="permanently deleted"):
        await pipeline.produce(store, parse_slot("2026-10-16T00:00:00+08:00"))
    collection.assert_not_awaited()
    assert store.published == []
