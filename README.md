# Meridian 24

A mobile-first, bilingual, AI-generated 24-hour news podcast station. A light Material-style podcast interface with programme artwork, archive cards and a persistent bottom player. Plain HTML, JavaScript and CSS3; no frontend framework, CDN or client-side credentials.

Read the illustrated project story: [中文博客](blog/cn.md) · [English blog](blog/en.md).

The page's **Architecture** section (`#architecture`) presents a system overview followed by a connected, bilingual production data-flow diagram, including the managed newsroom, native subagent roles, sandbox workspace, focused-search loop, checkpoints, Wei's tempo adjustment, measured timing and private/public Blob boundaries. Its pausable animation is explanatory, not live telemetry, and respects reduced-motion preferences.

## Production architecture

Foundry Routine (`0,30 * * * *`, `Asia/Shanghai`) → durable Hosted tool/audio bridge → managed Microsoft Copilot Harness Prompt Agent (`newsradio24-editor`, `gpt-6.1-sol`) → Microsoft Copilot Harness-triggered WebIQ discovery/expansion adapters → native subagents for China/world editorial work and verification → sandbox shell/workspace JSON checks → ordered validated briefs → coherent Chinese and matching English scripts → Hosted MAI Voice 2.1 PCM tracks → FFmpeg loudness-normalized AAC in MP4 → Blob archives → one atomic bilingual catalogue update.

The project combines both paths in the [official announcement](https://devblogs.microsoft.com/foundry/microsoft-copilot-harness-in-foundry/). The new editor is a separate `kind: prompt` agent with `harness.type: microsoft_copilot_preview`; the original `kind: hosted` agent is not converted. Foundry runs the editor's native `task` subagents, isolated sandbox shell and file tools. The Hosted bridge transports tool results and validates model outputs; it keeps speech/storage credentials outside prompts and sandbox files, and handles MAI, FFmpeg, durable checkpoints and publication.

`collect_news` and `expand_news` are non-strict read-only function tools with empty parameters. The Hosted caller executes the bound WebIQ adapter and returns `function_call_output` in the same conversation. Every editorial request starts a new managed conversation and uses only supported Microsoft Copilot Harness Responses fields; schemas are supplied as data and enforced by Pydantic afterward, not unsupported `text.format` settings. Native runtime events and response/conversation identifiers are saved privately under `jobs/<edition>/harness/`. Publication as `two-host-managed-v5` requires actual native delegation and shell execution records for all four editorial stages; response text claiming tool usage is insufficient. Managed failures retain the previous programme rather than silently falling back to direct model calls.

Native subagents are bounded runtime tasks, not extra deployed services. The sandbox is conversation-scoped working state, not durable output storage; validated briefs/scripts and execution records are checkpointed in Blob. Microsoft Copilot Harness tools are service-managed and public preview; shell has broad capabilities, so it must never receive credentials or treat retrieved pages as executable instructions.

The Hosted agent's **instance identity**, not the project's managed identity, needs the **Foundry User** role (`53ca6127-db72-4b80-b1b0-d745d6d5456d`) at the existing project scope to create managed conversations and invoke the editor. Grant only that project scope, allow role propagation, and verify the actual Hosted call. The managed editor needs no speech/storage credentials or Blob role; it only creates workspace files, not downloadable Foundry Files. See [Foundry permissions](https://learn.microsoft.com/en-us/azure/foundry/concepts/rbac-foundry).

| Edition | Male anchor | Female anchor |
| --- | --- | --- |
| Chinese | `zh-CN-Wei:MAI-Voice-2.1` | `zh-CN-Mei:MAI-Voice-2.1` |
| English | `en-US-Grant:MAI-Voice-2.1` | `en-US-Harper:MAI-Voice-2.1` |

Chinese Wei's synthesized PCM tracks use a pitch-preserving **1.25x tempo** before assembly; Mei and both English hosts stay at 1.0x. Story timestamps are measured after this adjustment, so news jumping remains aligned. Published language metadata records `speech_tempo`; existing archived recordings are not modified.

Target programme length is 12–16 minutes, with a **hard 1,200-second total and per-section publication gate measured from audio**, not a text-length estimate. Over-length content is rejected, never cut mid-sentence; previous published audio keeps playing.

New editions contain **only domestic China and international news**, with no sports section or third host. Both anchors report sourced facts and background, not commentary. Deterministic station frames introduce each host, greet listeners, disclose AI-generated voices, thank listeners and politely sign off with the next scheduled half-hour update. Facts take priority over length: sparse reporting produces a shorter bulletin, not speculative analysis or repetitive discussion of missing material.

## Blob layout and playback

Private `broadcasts` container:

```text
cn/20261016/0000.mp4
en/20261016/0000.mp4
jobs/20261016/0000/evidence.json
jobs/20261016/0000/topics.json
jobs/20261016/0000/expanded-evidence.json
jobs/20261016/0000/briefs.json
jobs/20261016/0000/cn/script.json
jobs/20261016/0000/cn/turns/000.wav
jobs/20261016/0000/en/...
jobs/20261016/0000/status.json
```

All slot paths use **Beijing time**. The example means 2026-10-16 00:00, not a hardcoded start date. The MP4 files really contain AAC audio, not renamed MP3 bytes.

Recorded station time announcements explicitly say Beijing time because one recording serves all listeners. All webpage clocks, episode/source update times and date filters use the user's browser timezone, including the applicable UTC offset through daylight-saving changes; no location permission is requested. ISO timestamps and archive paths are unchanged.

Each story publishes its title, agency/article links and measured audio start/duration derived from the actual synthesized WAV tracks, excluding the opening and sign-off. Clicking a story title seeks its audio; clicking a ticker title also scrolls and focuses the corresponding story. Each story/ticker displays **one primary article link**; additional citations are collapsed under “Additional sources”. Canonical duplicate links are merged. Source links open separately without changing playback. Older recordings without story timestamps do not pretend to provide exact seeking.

Collection reserves up to three candidates per agency instead of filling the input with the most abundant source. Underrepresented international AP, AFP and Bloomberg searches get bounded targeted news/web follow-ups. The editor prepares up to eight verified candidate stories per section; deterministic selection keeps up to two domestic and four international stories, prefers distinct domestic agencies when supported, reserves available AP/AFP/Bloomberg international topics, and limits any primary agency to two international stories. With at least two verified non-Xinhua stories selected, lower-priority Xinhua stories are omitted until Xinhua is no more than half the programme, preserving at least one story in each section. The primary agency comes from fresh factual citations, not undated background. Unsupported material is never used to fill a quota; scarce reporting produces fewer stories. The catalogue exposes the actual `primary_source_counts`, not a claim that all four agencies were available.

Public `$web` contains only the single-page application, `data/catalog.json` and intentional audio copies at `media/{cn|en}/YYYYMMDD/HHMM.mp4`. Raw passages, intermediate tracks and credentials are **not** public. Each audio version is completed before a single catalogue write exposes both. Stable episode links preserve language and archive selection. Browser autoplay policies may require one tap. Live playback switches to newer audio at an episode boundary; manual archive playback loops the selected recording. Missing or future slots never replace the latest completed recording.

**Daily retention:** only the current **Asia/Shanghai calendar day** is retained, not a rolling 24-hour window or each visitor's local day. A separate Foundry Routine (`0 0 * * *`) invokes the resilient `cleanup` task at midnight; every production also sweeps to catch missed runs. Under the publication lease, both catalogues are pruned before expired public/private MP4s, evidence, scripts, WAVs, runtime records and invocation mappings are deleted, including snapshots and stored versions. Static frontend assets and operational lease files are preserved. `maintenance/retention.json` records the latest cleanup result; failures are logged and retried, not reported as success.

The same lease fences dated Blob writes and publication against cleanup. Generation accepts only today's slots (HTTP 410 for expired dates), checkpoints recheck the day, and old tasks cannot recreate content after midnight. The browser excludes previous-day recordings even if catalogue refresh fails, stops old playback at rollover, and waits for today's first completed edition instead of looping yesterday. New MP4 uploads use `no-store`; previously downloaded copies cannot be recalled. Azure account-wide soft-delete/versioning protection is not silently disabled; if enabled, recoverable non-public copies may remain under that storage policy.

Explicit same-day deletions still use a private `retired/YYYYMMDD/HHMM.json` marker to prevent regeneration. Expired markers are removed during the daily sweep; the date guard continues to reject their old slots.

## Editorial controls and limitations

- Searches target Xinhua, AP, AFP and Bloomberg's official domains. No paywall bypass or unauthorized full-text redistribution. Search access is not a republication licence.
- Only original, neutral, source-attributed factual summaries and reported background are generated. No opinion padding, invented debate or unsupported implications. Sources are linked separately from each story and the ticker; unavailable agencies are disclosed on the page rather than repeatedly discussed on air.
- Agency homepages, advisories and headline-only results are discovery leads, not evidence of completed events. GPT first groups related reports and identifies missing details; bounded, topic-specific WebIQ news/web searches then seek fresh substantive articles on the four agencies' official domains. Unsupported topics are omitted, and a section without sufficient facts prevents publication.
- Search is run every half hour, but **this cannot guarantee the four agencies always offer accessible news**, nor zero-delay reporting. WebIQ ranking, recency and cross-agency headline overlap are a transparent *importance proxy*, not a real audience-popularity leaderboard.
- `lastUpdatedAt` is labelled **source updated**, not article publication time. `crawledAt` is never substituted for publication time. Unknown timestamps are disclosed, old/future timestamps are rejected, and every category needs verifiably fresh evidence.
- Briefing/script validation enforces source identifiers, fresh factual support, two-section order, exactly two host roles, opening/sign-off structure, topic coverage and completing each story before moving on. English follows the same prepared stories. It is not an independent fact-checking or semantic-neutrality guarantee: editorial oversight remains necessary.
- Retrieved passages are untrusted data. Instructions prohibit following page prompts, inventing quotes and reproducing source articles.
- The announcement calls hosted resilience GA, while the linked Learn resilience article and MAI page still contain preview notices. Verify the regional service terms/SLA before commercial 24/7 operation.

## Setup and deployment

Use your own Azure values; never copy a real resource group or cluster name into examples.

1. Log into Azure CLI and azd yourself. Select the existing Foundry project and verify the `gpt-6.1-sol` deployment. `azure.yaml` references `FOUNDRY_PROJECT_ENDPOINT`, rather than embedding a deployment's address.
2. Put a **rotated** WebIQ key into the ignored `.env`, following `.env.example`. Never commit `.env` or `.azure`, put secrets in frontend code, or share environment dumps.
3. From `src/resilient-research`, run `uv sync --frozen --python 3.12`. Python packages use `https://packagefeedproxy.microsoft.io/pypi/simple/`.
4. From the project root, run `AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd provision`. Container deployment uses remote ACR builds because FFmpeg is a system dependency; local Docker is not required.
5. Run `src/resilient-research/.venv/bin/python scripts/prepare_cloud.py`. It provisions the Blob static site/private archive, uploads only `web/`, and stores server-only Speech/WebIQ/Storage credentials in the ignored azd environment. It uses the selected project's Speech key, not a source-coded key.
6. Run `AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd deploy newsradio24 --no-prompt`.
7. Smoke-test with `AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai agent invoke newsradio24 --protocol invocations --input-file requests/generate.json`. Poll the invocation until `completed`; `202` alone is not successful generation.
8. Deploy the timer with `AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd deploy newsradio24-half-hour --no-prompt`, then verify its run history. Schedule only after a real audio-generation smoke test succeeds.
9. Deploy `newsradio24-midnight-cleanup` in the same way and verify its enabled `Asia/Shanghai` midnight schedule. Invoke `requests/cleanup.json` for an immediate sweep and confirm its completed result and absence of expired blobs; `202` alone is not deletion success.

`scripts/run_production.py` can run/resume the same pipeline locally against the selected Azure environment for debugging. `--check-services` probes the actual news source and all four voices. A supplied `--slot` must belong to the current Beijing day; future and expired slots are rejected. Never use historical slots to manufacture historical news: the metadata always records the actual retrieval cutoff.

`scripts/upload_web.py` updates HTML/CSS/JS without deleting generated media/catalogue.

For an immediate off-cycle edition, invoke the Hosted Agent with `requests/generate-now.json` (`action: generate_now`, no supplied slot). It uses the actual Beijing minute and the same durable generation/voice pipeline, with the next update still announced at the next :00/:30 boundary. Scheduled generation retains its alignment/future-slot checks. Existing recordings are never overwritten.

Completed manual editions use the same `cn|en/YYYYMMDD/HHMM.mp4` layout and a separate `data/manual-catalog.json`, so manual publication cannot be mistaken for a successful timer run. The website combines both catalogues for latest playback and archive selection; the next programme's continuity considers both. Ordinary half-hour scheduling is unchanged.

The current implementation uses server-only keys/connection strings for Speech and Blob, and managed identity for the Foundry model. Rotate exposed keys and move long-term secret management to Key Vault or supported identity auth before production. Secrets are not baked into images. Public MP4s are intentionally downloadable. Costs include models, Speech, WebIQ, Hosted Agent CPU/memory, ACR, storage and egress. The project's midnight retention routine deletes expired station content; do not apply it to unrelated containers.

## Validation

From `src/resilient-research`:

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests cover Beijing slot naming, provenance/freshness filtering, citation/two-host validation, greetings and midnight sign-offs, measured story boundaries excluding station frames, real MP4 encoding, duration rejection, retry/resume and atomic bilingual publication. Browser checks cover 320/390/1280px layouts, individual story and duplicated-ticker seeking, separate source links, local timezone/date filters and daylight-saving rollback, language switching, sharing, episode looping, future-slot exclusion and removal of deleted editions. Test media serve HTTP byte ranges like the published Blob MP4s.

From the project root, `src/resilient-research/.venv/bin/python scripts/validate_browser.py --url "<your-website-url>"` runs isolated mobile/desktop UI tests without publishing fixture news. Add `--real` to verify advancing playback of the actual published Chinese and English MP4 files. Chromium is installed with `uv run playwright install chromium` from the agent source folder.

`scripts/verify_routine.py --timeout 1200 --editorial-format two-host-balanced-v4` waits for a newer automatically published edition and verifies every story's timestamps against the actual private synthesized WAV durations, both hosts, the prepared news rundown and published primary-source counts/caps. It persists a smoke-test result under `.foundry/results/`; it does not manufacture a timer success from a `202` response. Initial publication and manual hosted-agent generation are separate validations.

Instruction-based evaluation generation is recorded in `src/resilient-research/eval.yaml` and `.foundry/agent-metadata.yaml`. Submitted generation jobs are not evaluation scores. Running an evaluation is an additional paid action and should be approved separately.

## References

- [Microsoft Copilot Harness and hosted long-running resilience announcement](https://devblogs.microsoft.com/foundry/microsoft-copilot-harness-in-foundry/)
- [Resilient tasks guide](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/agentserver/azure-ai-agentserver-core/docs/tasks-guide.md)
- [WebIQ API documentation](https://webiq.microsoft.ai/llms-full.txt)
- [MAI Voice 2.1 names and Speech API](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-voices)
