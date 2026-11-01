import { availableEditions, chooseEdition, nextOnEnded, mediaURL, programmeURL, clockTime, userTimeZone, calendarDay, formatTimestamp } from "./player.js?v=5";
import { animateGlobe } from "./globe.js?v=3";
import { renderArchitecture } from "./architecture.js?v=10";

const $ = id => document.getElementById(id);
const i18n = {
  cn: {
    tagline:"新闻不间断，视野无边界。",eyebrow:"你的 24 小时全球新闻台",hero:"世界在转动。|听见每一次变化。",
    description:"一男一女两位主持，全天候为你连贯播报中国国内与国际新闻。以事实为主，以来源为据。",
    continuous:"全天候收听",refresh:"每半小时更新",bilingual:"中英双语节目",sourceLabel:"新闻检索来源",
    discover:"发现节目",listenNow:"现在收听",architecture:"系统架构",
    architectureIntro:"沿数据节点查看整条链路：定时触发 → 托管 Microsoft Copilot Harness 与子 agent → 沙箱脚本 → 双语音频 → Blob → 网页收听。",
    retention:"仅保留北京时间当天节目；00:00 清理前日目录、音频与制作文件。显示时间仍使用你的本地时区。",
    dayRollover:"前日节目已过期，正在等待今天的首期新闻。",
    latest:"最新一期",history:"历史回听",localZone:"本地时区",waiting:"正在连接新闻台…",loading:"正在获取节目列表",
    returnLive:"回到最新节目 ↗",share:"分享节目",rundown:"本期节目",next:"下次更新",onDemand:"随时回听",archive:"新闻档案",
    date:"选择日期",empty:"暂无已发布节目。",editorial:"先整理事实，再连贯播报。",
    disclosure:"本台为独立 AI 生成新闻播客，与上述通讯社无隶属关系。中国国内与国际报道按主题整理、补充检索后生成原创事实摘要，不播报体育，不以评论填补资料缺口。热点排序参考检索相关性、时效和跨来源覆盖，不代表真实收听热度。",
    footer:"世界的此刻，与你同频。",headlines:"新闻速览",domestic:"中国新闻",international:"国际新闻",
    maleRole:"男主播",femaleRole:"女主播",ready:"点击播放收听 · 浏览器可能限制自动播放",
    listenStory:"收听这条新闻",viewSource:"查看来源",noStoryTiming:"旧录音暂无逐条定位信息",
    otherSources:"其余来源",
    legacyRecording:"这期仍是改版前三主持录音，两主持新版发布后将移除。",
    failed:"连接暂时中断，保留当前节目。稍后自动重试。",audioFailed:"音频暂不可用，请点击播放重试或选择其他节目。",
    replay:"暂无新一期，正在循环当前节目",playing:"正在收听 · 新节目就绪后将在本期结束时切换",
    historicalPlaying:"历史点播 · 本期结束后循环播放",newReady:"新一期已就绪，可点击「回到最新节目」收听",
    pending:"新一期制作中，继续播放最近完成的节目",copied:"节目链接已复制",copyFailed:"无法复制，请使用 Facebook 或 X 分享。",
    missing:"本期未获取到：",unknown:"来源时间未提供",updated:"来源更新",cutoff:"新闻检索截至",archiveState:"ARCHIVE",
    absent:"当前语言暂无已发布音频",min:"分钟",play:"播放",pause:"暂停",seek:"播放进度",mute:"静音",unmute:"取消静音",
  },
  en: {
    tagline:"Always informed. Always connected.",eyebrow:"YOUR 24-HOUR GLOBAL NEWS STATION",hero:"The world turns.|Stay in the know.",
    description:"Two anchors. Around-the-clock China and international news, organized into one coherent bulletin. Sourced facts.",
    continuous:"Around the clock",refresh:"Fresh every half hour",bilingual:"Chinese & English",sourceLabel:"SOURCE SEARCH",
    discover:"Discover",listenNow:"Listen now",architecture:"Architecture",
    architectureIntro:"Follow the data nodes: scheduled trigger → managed Microsoft Copilot Harness and subagents → sandbox scripts → bilingual audio → Blob → web listening.",
    retention:"Only the current Beijing day's programmes are retained. At 00:00, remove older catalogues, audio and production files. Display times remain local.",
    dayRollover:"Yesterday's programme has expired. Waiting for today's first bulletin.",
    latest:"LATEST EDITION",history:"ON DEMAND",localZone:"LOCAL TIME ZONE",waiting:"Connecting to the newsroom…",loading:"Loading broadcasts",
    returnLive:"Back to latest ↗",share:"SHARE",rundown:"IN THIS EDITION",next:"Next update",onDemand:"LISTEN ON YOUR TIME",archive:"The news archive",
    date:"Select date",empty:"No published broadcasts yet.",editorial:"Facts first. A coherent bulletin.",
    disclosure:"An independent AI-generated news podcast, not affiliated with the named agencies. China and international reports are grouped by topic and researched for missing details before original factual summaries are written. No sports or opinion padding. Selection uses relevance, recency and cross-source coverage, not measured audience popularity.",
    footer:"A world in motion. A signal to share.",headlines:"HEADLINES",domestic:"China briefing",international:"World affairs",
    maleRole:"Male anchor",femaleRole:"Female anchor",ready:"Press play to listen · Your browser may restrict autoplay",
    listenStory:"Listen to this story",viewSource:"View source",noStoryTiming:"Story timestamps unavailable in this older recording",
    otherSources:"Additional sources",
    legacyRecording:"This is an older three-host recording. It will be removed after the two-host edition is published.",
    failed:"Connection interrupted. Your current broadcast is retained. Retrying automatically.",audioFailed:"Audio unavailable. Press play to retry or select another edition.",
    replay:"No newer edition yet. Repeating this broadcast.",playing:"Listening · A newer edition will start after this broadcast",
    historicalPlaying:"On demand · This edition repeats when it ends",newReady:"A new edition is ready. Choose “Back to latest” to listen.",
    pending:"Next edition in production. Playing the most recently completed broadcast.",copied:"Programme link copied",copyFailed:"Copy unavailable. Use Facebook or X to share.",
    missing:"Sources unavailable this edition: ",unknown:"Source time unavailable",updated:"Source updated",cutoff:"News retrieved through",archiveState:"ARCHIVE",
    absent:"No published audio in this language yet",min:"min",play:"Play",pause:"Pause",seek:"Playback position",mute:"Mute",unmute:"Unmute",
  },
};
const agencyNames = {
  cn:{xinhua:"新华社",ap:"美联社 AP",afp:"法新社 AFP",bloomberg:"彭博社 Bloomberg"},
  en:{xinhua:"Xinhua",ap:"Associated Press",afp:"AFP",bloomberg:"Bloomberg"},
};
const params = new URLSearchParams(location.search);
let lang = params.get("lang") === "en" ? "en" : "cn";
let editions = [], selected = null, live = !params.has("edition"), preferred = params.get("edition"), generation = 0;
let hasLoadedAudio = false, manuallyPaused = false;
let pendingSeek = null;
const audio = $("audio");
const t = key => i18n[lang][key] || key;
const agencyName = name => agencyNames[lang][name] || name;
function text(id, value) { $(id).textContent = value; }
function element(tag, cls, value) { const e = document.createElement(tag); if (cls) e.className = cls; if (value !== undefined) e.textContent = value; return e; }
function dateTime(value, full = true) {
  return value ? formatTimestamp(value,lang,full) || t("unknown") : t("unknown");
}
function sourceLink(source) {
  try {
    const url = new URL(source.url);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    const link = element("a","story-source",`${agencyName(source.agency)} · ${source.title || t("viewSource")} ↗`);
    link.href = url.href;link.target = "_blank";link.rel = "noopener noreferrer";
    link.title = source.title || t("viewSource");
    return link;
  } catch { return null; }
}
function applyPendingSeek() {
  if (pendingSeek?.token === generation && audio.readyState >= 2) {
    for (let i = 0; i < audio.seekable.length; i++) {
      if (pendingSeek.start >= audio.seekable.start(i) && pendingSeek.start < audio.seekable.end(i)) {
        audio.currentTime = pendingSeek.start;pendingSeek = null;updatePlayer();return;
      }
    }
  }
}
async function seekTo(start, target) {
  if (!selected || !Number.isFinite(start) || start < 0 || start >= selected.languages[lang].duration) return;
  const token = generation;
  pendingSeek = {start,token};manuallyPaused = false;
  applyPendingSeek();await play();
  if (token !== generation) return;
  applyPendingSeek();updatePlayer();
  if (target) {
    const story = $(target);
    story?.scrollIntoView({block:"center",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
    story?.querySelector(".story-jump")?.focus({preventScroll:true});
  }
}
function translate() {
  document.documentElement.lang = lang === "cn" ? "zh-CN" : "en";
  document.title = lang === "cn" ? "Meridian 24 · 全球新闻电台" : "Meridian 24 · Global News Radio";
  document.querySelectorAll("[data-i18n]").forEach(e => {
    const value = t(e.dataset.i18n);
    if (e.dataset.i18n === "hero") {
      const [first,second] = value.split("|");
      e.replaceChildren(document.createTextNode(first),element("br"),element("em","",second));
    } else e.textContent = value;
  });
  text("language", lang === "cn" ? "中文 / EN" : "EN / 中文");
  $("seek").setAttribute("aria-label",t("seek"));
  $("archive-date").setAttribute("aria-label",t("date"));
  text("timezone",`${t("localZone")} · ${userTimeZone}`);
  document.querySelectorAll("[data-agency]").forEach(e => e.textContent = agencyName(e.dataset.agency));
  renderArchitecture(lang);
  renderArchive(); renderProgramme(); updatePlayer(); updateClock();
}
function renderHosts() {
  $("hosts").replaceChildren();
  const names = lang === "cn" ? ["Wei","Mei"] : ["Grant","Harper"];
  names.forEach((name,i) => {
    const host = element("div","host"), avatar = element("span","host-avatar",name.slice(0,2).toUpperCase()), label = element("div");
    label.append(element("strong","",name),element("small","",t(["maleRole","femaleRole"][i])));
    host.append(avatar,label); $("hosts").append(host);
  });
}
function renderProgramme() {
  renderHosts();
  $("chapters").replaceChildren();
  const programme = selected?.languages[lang];
  $("legacy-notice").hidden = selected?.editorial_format !== "neutral-news-v2";
  text("legacy-notice",t("legacyRecording"));
  if (!programme) {
    text("programme-title",t("absent"));text("edition-time","—");text("next-update","—");
    text("dock-title",t("absent"));text("dock-edition","Meridian 24");
    text("source-gaps","");$("ticker-track").replaceChildren(element("span","",t("empty")));
    ["share-x","share-facebook"].forEach(id => $(id).removeAttribute("href"));
    $("play").disabled = true;$("seek").disabled = true;return;
  }
  text("programme-title",programme.title);text("edition-time",dateTime(selected.slot));text("mode",t(live ? "latest" : "history"));
  text("dock-title",programme.title);text("dock-edition",`${dateTime(selected.slot)} · ${lang === "cn" ? "中文" : "English"}`);
  const overdue = Date.now() > Date.parse(selected.next_slot);
  text("next-update",dateTime(selected.next_slot,false) + (overdue ? (lang === "cn" ? " · 制作中" : " · pending") : ""));
  $("next-update").classList.toggle("stale",overdue);
  $("play").disabled = false;$("seek").disabled = false;text("duration",clockTime(programme.duration));
  const track = $("ticker-track");track.replaceChildren();
  programme.chapters.forEach((chapter,i) => {
    const section = element("section","story-section");
    const button = element("button","chapter"),copy = element("span","chapter-copy");
    button.dataset.start = chapter.start;button.dataset.end = chapter.start + chapter.duration;
    copy.append(element("strong","",t(chapter.category)),element("small","",chapter.title));
    button.append(element("span","chapter-index",`0${i+1}`),copy,element("span","chapter-time",clockTime(chapter.start)));
    button.setAttribute("aria-label",`${t(chapter.category)} ${clockTime(chapter.start)}`);
    button.addEventListener("click",() => seekTo(chapter.start));
    section.append(button);
    chapter.headlines.forEach((headline,j) => {
      const id = `story-${i}-${j}`, story = element("article","story-item");
      const start = Number.isFinite(headline.start) ? headline.start : null;
      story.id = id;
      const jump = element("button","story-jump");
      jump.append(element("span","story-title",headline.title),element("span","story-position",start === null ? "—" : `▶ ${clockTime(start)}`));
      jump.disabled = start === null;jump.title = t(start === null ? "noStoryTiming" : "listenStory");
      jump.setAttribute("aria-label",`${t("listenStory")}: ${headline.title}`);
      if (start !== null) {
        jump.dataset.start = start;jump.dataset.end = start + headline.duration;
        jump.addEventListener("click",() => seekTo(start));
      }
      const stamp = element("time","story-updated",headline.reported_at ? `${t("updated")} ${dateTime(headline.reported_at)}` : t("unknown"));
      if (headline.reported_at) stamp.dateTime = headline.reported_at;
      const sources = element("div","story-sources");
      const linkedSources = (headline.sources || []).map(source => ({source,link:sourceLink(source)})).filter(item => item.link);
      const uniqueSources = [...new Map(linkedSources.map(item => {
        const url = new URL(item.link.href);
        return [`${url.origin}${url.pathname}`,item];
      })).values()];
      if (uniqueSources.length) sources.append(uniqueSources[0].link);
      if (uniqueSources.length > 1) {
        const more = element("details","additional-sources");
        more.append(element("summary","",`${t("otherSources")} (${uniqueSources.length-1})`));
        uniqueSources.slice(1).forEach(item => more.append(item.link));
        sources.append(more);
      }
      story.append(jump,stamp,sources);section.append(story);
      const tickerItem = element("span","ticker-item");
      const tickerTime = element("time","",headline.reported_at ? `${t("updated")} ${dateTime(headline.reported_at)}` : `${t("unknown")} · ${dateTime(selected.slot)}`);
      tickerTime.dateTime = headline.reported_at || selected.slot;
      const tickerJump = element("button","ticker-jump",headline.title);
      tickerJump.disabled = start === null;
      if (start !== null) {tickerJump.dataset.start = start;tickerJump.dataset.target = id;}
      tickerItem.append(tickerTime,element("b","",t(chapter.category)),tickerJump);
      if (uniqueSources.length) {
        const source = uniqueSources[0].source, link = sourceLink(source);
        link.className = "ticker-source";link.textContent = `${agencyName(source.agency)} ↗`;tickerItem.append(link);
      }
      track.append(tickerItem);
    });
    $("chapters").append(section);
  });
  const gaps = selected.missing_agencies || [];
  text("source-gaps",`${t("cutoff")} ${dateTime(selected.news_cutoff)} · ${userTimeZone}${gaps.length ? " · "+t("missing")+gaps.map(agencyName).join(", ") : ""}`);
  [...track.children].forEach(item => {
    const clone = item.cloneNode(true);clone.setAttribute("aria-hidden","true");
    clone.querySelectorAll("button,a").forEach(e => e.tabIndex = -1);track.append(clone);
  });
  const shareURL = programmeURL(location.href,selected.id,lang);
  $("share-x").href = "https://x.com/intent/post?"+new URLSearchParams({text:programme.title+" · Meridian 24",url:shareURL});
  $("share-facebook").href = "https://www.facebook.com/sharer/sharer.php?"+new URLSearchParams({u:shareURL});
  updatePlayer();
}
function renderArchive() {
  const list = $("archive-list");list.replaceChildren();
  const date = $("archive-date").value;
  const available = availableEditions(editions,lang).filter(e => !date || calendarDay(e.slot) === date);
  if (!available.length) { list.append(element("p","status",t("empty")));return; }
  for (const edition of available) {
    const programme = edition.languages[lang], button = element("button","archive-card");
    button.classList.toggle("selected",selected?.id === edition.id);
    const artwork = element("span","card-art","24");artwork.setAttribute("aria-hidden","true");
    button.append(artwork,element("span","card-time",dateTime(edition.slot)),element("span","card-arrow","▶"),
      element("span","card-title",programme.title),element("span","card-meta",`${Math.ceil(programme.duration/60)} ${t("min")} · ${lang === "cn" ? "中文" : "English"} · AI PODCAST`));
    button.addEventListener("click",() => { live = false;choose(edition,true); });
    list.append(button);
  }
}
async function choose(edition, autoplay = false) {
  if (edition && !availableEditions(editions,lang).some(e => e.id === edition.id)) edition = chooseEdition(editions,lang,null);
  const token = ++generation;
  pendingSeek = null;
  selected = edition;
  if (!edition) {
    audio.pause();audio.removeAttribute("src");audio.load();hasLoadedAudio = false;
    const url = new URL(location.href);url.searchParams.delete("edition");url.searchParams.set("lang",lang);
    history.replaceState(null,"",url.href);renderProgramme();renderArchive();updatePlayer();return;
  }
  try {
    audio.src = mediaURL(edition.languages[lang].audio_url,location.href);
    audio.load();hasLoadedAudio = true;
    history.replaceState(null,"",programmeURL(location.href,edition.id,lang));
    renderProgramme();renderArchive();text("status",t("ready"));
    if (autoplay && token === generation) await play();
  } catch { text("status",t("audioFailed")); }
}
async function play() {
  if (selected && !availableEditions(editions,lang).some(e => e.id === selected.id)) {
    await choose(null);text("status",t("dayRollover"));return;
  }
  try {
    if (audio.error && selected) { audio.src = mediaURL(selected.languages[lang].audio_url,location.href);audio.load(); }
    await audio.play();
    text("status",t(live ? "playing" : "historicalPlaying"));
  } catch { text("status",t("ready"));updatePlayer(); }
}
function updatePlayer() {
  const playing = !audio.paused && !audio.ended;
  document.body.classList.toggle("playing",playing);
  text("play-icon",playing ? "Ⅱ" : "▶");$("play").setAttribute("aria-label",t(playing ? "pause" : "play"));
  text("elapsed",clockTime(audio.currentTime));
  const total = Number.isFinite(audio.duration) ? audio.duration : selected?.languages[lang]?.duration || 0;
  text("duration",clockTime(total));$("seek").value = total ? audio.currentTime / total * 100 : 0;
  $("seek").setAttribute("aria-valuetext",`${clockTime(audio.currentTime)} / ${clockTime(total)}`);
  $("mute").setAttribute("aria-label",t(audio.muted ? "unmute" : "mute"));
  text("mute",audio.muted ? "◖×" : "◖))");
  document.querySelectorAll(".chapter").forEach(e => e.classList.toggle("active",audio.currentTime >= +e.dataset.start && audio.currentTime < +e.dataset.end));
  document.querySelectorAll(".story-jump[data-start]").forEach(e => {
    const active = audio.currentTime >= +e.dataset.start && audio.currentTime < +e.dataset.end;
    e.closest(".story-item").classList.toggle("active",active);
    if (active) e.setAttribute("aria-current","true");else e.removeAttribute("aria-current");
  });
}
async function refresh() {
  try {
    const feeds = await Promise.all(["catalog","manual-catalog"].map(async name => {
      const result = await fetch(`data/${name}.json?t=${Date.now()}`,{cache:"no-store"});
      if (result.status === 404) return [];
      if (!result.ok) throw new Error("catalog unavailable");
      const data = await result.json();
      if (!Array.isArray(data.editions)) throw new Error("bad catalog");
      return data.editions;
    }));
    editions = feeds.flat();
    const latest = chooseEdition(editions,lang,null);
    if (selected && !availableEditions(editions,lang).some(e => e.id === selected.id)) {
      preferred = null;live = true;await choose(latest,!manuallyPaused);
      if (!latest) text("status",t("empty"));
      renderArchive();updateClock();return;
    }
    if (!selected) {
      const edition = chooseEdition(editions,lang,preferred);preferred = null;
      if (edition) {
        $("archive-date").value = calendarDay(edition.slot);
        await choose(edition,!manuallyPaused);
      } else text("status",t("empty"));
    } else if (live && latest && latest.id !== selected.id) {
      if (audio.paused && !manuallyPaused) await choose(latest,true);
      else text("status",t("newReady"));
    } else if (live && latest && Date.now() > Date.parse(latest.next_slot) + 10*60000) {
      text("status",t("pending"));
    }
    renderArchive();updateClock();
  } catch { text("status",t("failed")); }
}
function updateClock() {
  if (selected && calendarDay(selected.slot,"Asia/Shanghai") !== calendarDay(Date.now(),"Asia/Shanghai")) {
    live = true;preferred = null;$("archive-date").value = "";
    choose(chooseEdition(editions,lang,null),!manuallyPaused);
    text("status",t("dayRollover"));refresh();
  }
  text("clock",`${calendarDay(Date.now())} ${dateTime(Date.now(),false)} · ${userTimeZone}`);
  const latest = chooseEdition(editions,lang,null), stale = !latest || Date.now() - Date.parse(latest.slot) > 90*60000;
  text("station-state",stale ? t("archiveState") : "ON AIR");$("station-state").classList.toggle("stale",stale);
}
$("play").addEventListener("click",async () => { if (!hasLoadedAudio) return; if (audio.paused || audio.currentTime === 0) { manuallyPaused = false;await play(); } else { manuallyPaused = true;audio.pause(); } });
$("seek").addEventListener("input",() => { if (Number.isFinite(audio.duration)) audio.currentTime = +$("seek").value / 100 * audio.duration; });
$("mute").addEventListener("click",() => { audio.muted = !audio.muted;updatePlayer(); });
$("archive-date").addEventListener("change",renderArchive);
$("go-live").addEventListener("click",() => { live = true;manuallyPaused = false;const latest = chooseEdition(editions,lang,null);if (latest) {$("archive-date").value=calendarDay(latest.slot);choose(latest,true);} });
$("language").addEventListener("click",async () => {
  const wasPlaying = !audio.paused,id = selected?.id;
  lang = lang === "cn" ? "en" : "cn";
  translate();const target = chooseEdition(editions,lang,id);await choose(target,wasPlaying);
});
$("share-native").addEventListener("click",async () => {
  if (!selected) return;
  const url = programmeURL(location.href,selected.id,lang),title = selected.languages[lang].title;
  try { if (navigator.share) await navigator.share({title,url});else {await navigator.clipboard.writeText(url);text("status",t("copied"));} }
  catch (e) { if (e.name !== "AbortError") text("status",t("copyFailed")); }
});
$("ticker-pause").addEventListener("click",() => { const paused = document.querySelector(".ticker").classList.toggle("paused");text("ticker-pause",paused ? "▶" : "Ⅱ");$("ticker-pause").setAttribute("aria-label",t(paused ? "play" : "pause")); });
$("ticker-track").addEventListener("click",event => {
  const button = event.target.closest(".ticker-jump[data-start]");
  if (button) seekTo(+button.dataset.start,button.dataset.target);
});
["loadedmetadata","loadeddata","canplay","progress"].forEach(event => audio.addEventListener(event,applyPendingSeek));
["timeupdate","play","pause","loadedmetadata","volumechange"].forEach(event => audio.addEventListener(event,updatePlayer));
audio.addEventListener("error",() => { text("status",t("audioFailed"));updatePlayer(); });
audio.addEventListener("ended",async () => {
  const next = nextOnEnded(editions,lang,selected,live);
  if (!next) return;
  if (next.id === selected.id) {audio.currentTime = 0;await play();text("status",t("replay"));}
  else await choose(next,true);
});
document.addEventListener("visibilitychange",() => { if (!document.hidden) refresh(); });
animateGlobe($("globe"));translate();refresh();
setInterval(refresh,45000);setInterval(updateClock,1000);
