"""Exercise the real frontend with isolated test media/catalogue, without publishing fake news."""

import argparse
import copy
import json
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright


def catalogue():
    now = datetime.now(UTC)
    slot = now.replace(
        minute=(now.minute // 30) * 30, second=0, microsecond=0
    ) - timedelta(minutes=30)
    editions = []
    for index, delta in enumerate(
        [timedelta(), -timedelta(minutes=30), timedelta(days=1)]
    ):
        stamp = slot + delta
        edition_id = stamp.strftime("%Y%m%d/%H%M")
        languages = {}
        categories = ["domestic", "international"]
        for language in ["cn", "en"]:
            languages[language] = {
                "title": f"UI service test {index} {language}",
                "duration": 3,
                "audio_url": f"media/{language}/{edition_id}.mp4",
                "chapters": [
                    {
                        "category": c,
                        "title": f"UI test {c}",
                        "start": i * 3 / len(categories),
                        "duration": 3 / len(categories),
                        "headlines": [
                            {
                                "title": f"UI test headline {c} {j}",
                                "topic_id": f"{c}-{j}",
                                "start": i * 1.5
                                + 0.25
                                + j * 0.65
                                + (0.05 if language == "en" else 0),
                                "duration": 0.5,
                                "reported_at": stamp.isoformat(),
                                "sources": [
                                    {
                                        "agency": "ap",
                                        "title": f"Source article {c} {j}",
                                        "url": f"https://apnews.com/article/{c}-{j}",
                                    },
                                    {
                                        "agency": "afp",
                                        "title": "A related source",
                                        "url": f"https://afp.com/en/news/{c}-{j}",
                                    },
                                ],
                            }
                            for j in range(2)
                        ],
                    }
                    for i, c in enumerate(categories)
                ],
            }
        editions.append(
            {
                "id": edition_id,
                "slot": stamp.isoformat(),
                "next_slot": (stamp + timedelta(minutes=30)).isoformat(),
                "news_cutoff": slot.isoformat(),
                "missing_agencies": ["afp"],
                "editorial_format": "two-host-news-v3",
                "languages": languages,
            }
        )
    return {"editions": editions}


def serve_media(route, payload):
    headers = {"Accept-Ranges": "bytes"}
    requested = route.request.headers.get("range")
    if requested:
        first, last = requested.removeprefix("bytes=").split("-", 1)
        start = int(first or 0)
        end = min(int(last) if last else len(payload) - 1, len(payload) - 1)
        headers["Content-Range"] = f"bytes {start}-{end}/{len(payload)}"
        route.fulfill(
            status=206,
            content_type="audio/mp4",
            headers=headers,
            body=payload[start : end + 1],
        )
    else:
        route.fulfill(content_type="audio/mp4", headers=headers, body=payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--screenshot-dir")
    parser.add_argument(
        "--real",
        action="store_true",
        help="Verify published MP4 playback instead of isolated fixtures",
    )
    args = parser.parse_args()
    if args.real:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(args.url)
            page.wait_for_function("!document.querySelector('#play').disabled")
            page.locator("#play").click()
            page.wait_for_function(
                "document.querySelector('#audio').currentTime > 1", timeout=30000
            )
            for language in ["cn", "en"]:
                if language == "en":
                    page.locator("#language").click()
                    page.wait_for_function(
                        "document.documentElement.lang === 'en' && document.querySelector('#audio').currentTime > 1",
                        timeout=30000,
                    )
                state = page.evaluate("""() => {
                    const a = document.querySelector('#audio');
                    return {duration:a.duration,time:a.currentTime,error:a.error?.code||null,src:a.src};
                }""")
                assert (
                    0 < state["duration"] <= 1200
                    and state["time"] > 1
                    and state["error"] is None
                ), state
                assert f"/media/{language}/" in state["src"]
                assert page.locator("#hosts .host").count() == 2
                assert page.locator(".story-jump:disabled").count() == 0
                for sources in page.locator(".story-sources").all():
                    assert sources.locator(".story-source:visible").count() == 1
                assert (
                    page.locator(".ticker-source").count()
                    == page.locator(".ticker-jump").count()
                )
                for index in (0, 1):
                    button = page.locator(".story-jump").nth(index)
                    start = float(button.get_attribute("data-start"))
                    button.click()
                    page.wait_for_function(
                        """start => Math.abs(document.querySelector('#audio').currentTime-start)<1.5
                        && document.querySelector('.story-jump[aria-current="true"]')?.dataset.start === String(start)""",
                        arg=start,
                    )
                    assert button.get_attribute("aria-current") == "true"
                assert start > float(
                    page.locator(".story-jump").first.get_attribute("data-start")
                )
                print(
                    f"PASS real {language} MP4: {state['duration']:.1f} seconds, decoded playback advancing and independent story seeking"
                )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
            if args.screenshot_dir:
                folder = Path(args.screenshot_dir)
                folder.mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(folder / "real-station-mobile.png"), full_page=True
                )
            browser.close()
        return
    data = catalogue()
    manual_data = {"editions": []}
    with tempfile.TemporaryDirectory(prefix="meridian-ui-") as tmp:
        media = Path(tmp) / "test.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=3",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-movflags",
                "+faststart",
                str(media),
            ],
            check=True,
        )
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for width, height in [(320, 740), (390, 844), (1280, 900)]:
                zone = "Asia/Tokyo" if width == 1280 else "America/Los_Angeles"
                page = browser.new_page(
                    viewport={"width": width, "height": height}, timezone_id=zone
                )
                errors = []
                page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                page.route(
                    "**/data/catalog.json*",
                    lambda route: route.fulfill(
                        content_type="application/json", body=json.dumps(data)
                    ),
                )
                page.route(
                    "**/data/manual-catalog.json*",
                    lambda route: route.fulfill(
                        content_type="application/json", body=json.dumps(manual_data)
                    ),
                )
                page.context.route(
                    "https://apnews.com/**",
                    lambda route: route.fulfill(
                        content_type="text/html", body="<title>Source link test</title>"
                    ),
                )
                page.route(
                    "**/media/**",
                    lambda route: serve_media(route, media.read_bytes()),
                )
                page.goto(args.url)
                page.wait_for_function(
                    "document.querySelector('#programme-title').textContent.includes('UI service test')"
                )
                assert (
                    page.locator("#programme-title").inner_text()
                    == "UI service test 0 cn"
                )
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
                assert page.evaluate(
                    "document.querySelector('#globe').getBoundingClientRect().bottom "
                    "<= document.querySelector('.broadcast-panel').getBoundingClientRect().top"
                )
                assert page.locator(".chapter").count() == 2
                assert page.locator(".architecture-component").count() == 4
                assert page.locator(".data-node").count() == 10
                assert page.locator(".process-node").count() == 15
                assert page.locator(".flow-edge").count() >= 18
                assert (
                    page.locator(".edge-label").count()
                    == page.locator(".flow-edge").count()
                )
                assert page.locator(".native-role .agent-port").count() == 6
                assert page.locator(".native-role details[open]").count() == 3
                assert page.locator(".harness-runtime [data-node='P03']").count() == 1
                assert "00:00" in page.locator(".retention-flow").inner_text()
                assert "WebIQ" in page.locator(".flow-branch").inner_text()
                assert (
                    "microsoft_copilot_preview"
                    in page.locator(".architecture-boundary").inner_text()
                )
                assert page.evaluate(
                    "!/(?<!Microsoft Copilot )\\bHarness\\b/.test(document.querySelector('#architecture').innerText)"
                )
                assert page.locator(".native-role").count() == 3
                assert "隔离沙箱" in page.locator(".sandbox-boundary").inner_text()
                assert page.evaluate(
                    "document.querySelector('.architecture-overview').getBoundingClientRect().top "
                    "< document.querySelector('#architecture-flow').getBoundingClientRect().top"
                )
                page.locator(".flow-toggle").evaluate("e => e.click()")
                assert (
                    page.locator(".flow-toggle").get_attribute("aria-pressed") == "true"
                )
                assert page.locator(".flow-edge").first.evaluate(
                    "e => getComputedStyle(e,'::after').animationPlayState === 'paused'"
                )
                page.emulate_media(reduced_motion="reduce")
                assert page.locator(".flow-edge").first.evaluate(
                    "e => getComputedStyle(e,'::after').animationName === 'none'"
                )
                page.emulate_media(reduced_motion="no-preference")
                assert page.locator("#ticker-track time").count() == 8
                assert page.locator("#ticker-track .ticker-source").count() == 8
                assert (
                    page.locator(".story-sources")
                    .first.locator(".story-source:visible")
                    .count()
                    == 1
                )
                page.locator(".additional-sources summary").first.click()
                assert (
                    page.locator(".story-sources")
                    .first.locator(".story-source:visible")
                    .count()
                    == 2
                )
                page.locator(".additional-sources summary").first.click()
                assert (
                    page.locator(".story-sources")
                    .first.locator(".story-source:visible")
                    .count()
                    == 1
                )
                assert page.locator("#hosts .host").count() == 2
                assert zone in page.locator("#timezone").inner_text()
                assert zone in page.locator("#clock").inner_text()
                assert "GMT" in page.locator(".story-updated").first.inner_text()
                for index in (0, 1):
                    button = page.locator(".story-jump").nth(index)
                    start = float(button.get_attribute("data-start"))
                    button.click()
                    page.wait_for_function(
                        """start => Math.abs(document.querySelector('#audio').currentTime-start)<0.15
                        && document.querySelector('.story-jump[aria-current="true"]')?.dataset.start === String(start)""",
                        arg=start,
                    )
                    page.evaluate("document.querySelector('#audio').pause()")
                    assert button.get_attribute("aria-current") == "true"
                before = page.evaluate("document.querySelector('#audio').currentTime")
                with page.expect_popup() as popup:
                    page.locator(".story-source").first.click()
                assert "/article/domestic-0" in popup.value.url
                popup.value.close()
                assert (
                    abs(
                        page.evaluate("document.querySelector('#audio').currentTime")
                        - before
                    )
                    < 0.1
                )
                for index in (1, 5):
                    ticker = page.locator(".ticker-jump").nth(index)
                    start = float(ticker.get_attribute("data-start"))
                    ticker.evaluate("e => e.click()")
                    page.wait_for_function(
                        """start => Math.abs(document.querySelector('#audio').currentTime-start)<0.15
                        && document.querySelector('.story-jump[aria-current="true"]')?.dataset.start === String(start)""",
                        arg=start,
                    )
                    page.wait_for_function(
                        "document.activeElement?.closest('.story-item')?.id === 'story-0-1'"
                    )
                    page.evaluate("document.querySelector('#audio').pause()")
                assert "202" not in page.locator("#share-x").get_attribute(
                    "href"
                ) or "edition" in page.locator("#share-x").get_attribute("href")
                page.locator("#play").click()
                page.locator("#language").click()
                page.wait_for_function("document.documentElement.lang === 'en'")
                assert (
                    page.locator("#architecture-title").inner_text() == "Architecture"
                )
                assert page.locator("#architecture-flow-title").inner_text() == (
                    "Application execution data-node diagram"
                )
                assert (
                    "actually executes native subagents"
                    in page.locator(".architecture-boundary").inner_text()
                )
                assert page.evaluate(
                    "!/(?<!Microsoft Copilot )\\bHarness\\b/.test(document.querySelector('#architecture').innerText)"
                )
                assert (
                    page.locator(".flow-toggle").inner_text() == "Resume flow animation"
                )
                assert (
                    page.locator(".flow-toggle").get_attribute("aria-pressed") == "true"
                )
                page.locator(".flow-toggle").evaluate("e => e.click()")
                assert page.locator(".flow-edge").first.evaluate(
                    "e => getComputedStyle(e,'::after').animationPlayState === 'running'"
                )
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
                assert (
                    page.locator("#programme-title").inner_text()
                    == "UI service test 0 en"
                )
                assert (
                    page.locator("#hosts .host strong").nth(1).inner_text() == "Harper"
                )
                assert "lang%3Den" in page.locator("#share-facebook").get_attribute(
                    "href"
                )
                module_result = page.evaluate("""async () => {
                  const m = await import('./player.js?v=5');
                  const result = await fetch('data/catalog.json').then(r=>r.json());
                  const es = result.editions;
                  const latest = m.chooseEdition(es,'en',null);
                  const old = es.find(e=>e.id !== latest.id && Date.parse(e.slot)<Date.now());
                  let blocked = false;try{m.mediaURL('https://evil.test/a.mp4',location.href)}catch{blocked=true}
                  return {futureExcluded:latest.id===es[0].id,archiveLoops:m.nextOnEnded(es,'en',old,false).id===old.id,
                    liveAdvances:m.nextOnEnded(es,'en',old,true).id===latest.id,blocked,
                    encoded:m.programmeURL(location.href,'20261016/0000','cn').includes('20261016%2F0000'),
                    dateFilter:document.querySelector('#archive-date').value===m.calendarDay(es[0].slot),
                    midnight:m.calendarDay('2026-11-01T00:00:00+08:00','America/Los_Angeles')==='2026-10-31',
                    dstBefore:m.formatTimestamp('2026-11-01T08:30:00Z','en',true,'America/Los_Angeles').includes('GMT-7'),
                    dstAfter:m.formatTimestamp('2026-11-01T09:30:00Z','cn',true,'America/Los_Angeles').includes('GMT-8')};
                }""")
                assert all(module_result.values()), module_result
                page.locator("#archive-date").fill("")
                page.locator(".archive-card").nth(1).click()
                assert page.locator("#mode").inner_text() == "ON DEMAND"
                assert page.locator(".chapter").count() == 2
                page.evaluate(
                    "document.querySelector('#audio').dispatchEvent(new Event('ended'))"
                )
                page.wait_for_timeout(200)
                assert (
                    page.locator("#programme-title").inner_text()
                    == "UI service test 1 en"
                )
                page.locator("#go-live").click()
                assert (
                    page.locator("#programme-title").inner_text()
                    == "UI service test 0 en"
                )
                assert page.locator(".chapter").count() == 2
                assert (
                    page.locator("#hosts .host strong").nth(1).inner_text() == "Harper"
                )
                page.locator("#ticker-pause").click()
                assert page.locator(".ticker").evaluate(
                    "e=>e.classList.contains('paused')"
                )
                assert (
                    page.locator("#dock-title").inner_text()
                    == page.locator("#programme-title").inner_text()
                )
                assert page.locator("#play").evaluate(
                    "e => e.closest('.playback-dock') !== null"
                )
                assert page.locator(".playback-dock").evaluate(
                    "e => e.getBoundingClientRect().bottom <= document.querySelector('.ticker').getBoundingClientRect().top"
                )
                assert page.evaluate(
                    "getComputedStyle(document.documentElement).colorScheme === 'light'"
                )
                assert not errors, errors
                if args.screenshot_dir:
                    out = Path(args.screenshot_dir)
                    out.mkdir(parents=True, exist_ok=True)
                    page.screenshot(
                        path=str(out / f"station-{width}.png"), full_page=True
                    )
                    page.evaluate(
                        "document.querySelector('#architecture').scrollIntoView({block:'start',behavior:'instant'})"
                    )
                    page.screenshot(path=str(out / f"architecture-{width}.png"))
                    page.evaluate(
                        "document.querySelector('.dataflow-heading').scrollIntoView({block:'start',behavior:'instant'})"
                    )
                    page.screenshot(path=str(out / f"dataflow-{width}.png"))
                manual = copy.deepcopy(data["editions"][0])
                stamp = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(
                    minutes=1
                )
                manual["id"] = stamp.strftime("%Y%m%d/%H%M")
                manual["slot"] = stamp.isoformat()
                manual["publication_trigger"] = "manual"
                for language, edition in manual["languages"].items():
                    edition["title"] = f"Manual extra {language}"
                    edition["audio_url"] = f"media/{language}/{manual['id']}.mp4"
                manual_data["editions"] = [manual]
                page.evaluate(
                    "document.querySelector('#audio').pause();document.dispatchEvent(new Event('visibilitychange'))"
                )
                page.wait_for_function(
                    "document.querySelector('#programme-title').textContent === 'Manual extra en'"
                )
                page.locator("#archive-date").fill("")
                assert page.locator(".archive-card").count() == 3
                manual_data["editions"] = []
                page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                page.wait_for_function(
                    "document.querySelector('#programme-title').textContent === 'UI service test 0 en'"
                )
                original_editions = data["editions"]
                data["editions"] = [original_editions[1]]
                page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                page.wait_for_function(
                    "document.querySelector('#programme-title').textContent === 'UI service test 1 en'"
                )
                data["editions"] = []
                page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                page.wait_for_function("document.querySelector('#play').disabled")
                assert page.locator("#audio").get_attribute("src") is None
                assert page.locator("#ticker-track time").count() == 0
                assert page.locator("#source-gaps").inner_text() == ""
                assert page.locator("#share-x").get_attribute("href") is None
                data["editions"] = original_editions
                before_midnight = copy.deepcopy(original_editions[0])
                before_midnight["slot"] = "2026-11-01T23:30:00+08:00"
                before_midnight["id"] = "20261101/2330"
                data["editions"] = [before_midnight]
                page.clock.set_fixed_time(datetime(2026, 11, 1, 15, 59, 58, tzinfo=UTC))
                page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                page.wait_for_function("!document.querySelector('#play').disabled")
                assert page.locator("#audio").get_attribute("src") is not None
                # Failed refresh must not keep a cached previous-day recording alive.
                page.route("**/data/*.json*", lambda route: route.abort())
                page.clock.set_fixed_time(datetime(2026, 11, 1, 16, 0, 0, tzinfo=UTC))
                page.wait_for_function(
                    "document.querySelector('#play').disabled", timeout=5000
                )
                assert page.locator("#audio").get_attribute("src") is None
                assert page.locator(".archive-card").count() == 0
                assert page.locator("#ticker-track time").count() == 0
                assert page.evaluate("""async () => {
                    const m = await import('./player.js?v=5');
                    const e = {slot:'2026-11-01T23:30:00+08:00',languages:{cn:{audio_url:'media/cn/20261101/2330.mp4'}}};
                    return m.availableEditions([e],'cn',Date.parse('2026-11-01T15:59:59Z')).length === 1
                        && m.availableEditions([e],'cn',Date.parse('2026-11-01T16:00:00Z')).length === 0
                        && m.nextOnEnded([e],'cn',e,false,Date.parse('2026-11-01T16:00:00Z')) === null;
                }""")
                data["editions"] = original_editions
                print(
                    f"PASS {width}px: connected data nodes and subagent contracts, pause/reduced motion, two hosts, story/ticker seeking, source links, local timezone/DST, bilingual playback, archive loop/deletion, exact Beijing midnight expiry even when refresh fails"
                )
                page.close()
            browser.close()


if __name__ == "__main__":
    main()
