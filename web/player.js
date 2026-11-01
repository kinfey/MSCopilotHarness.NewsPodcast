export function availableEditions(editions, language, now = Date.now()) {
  return editions.filter(e => Date.parse(e.slot) <= now
    && calendarDay(e.slot, "Asia/Shanghai") === calendarDay(now, "Asia/Shanghai")
    && e.languages?.[language]?.audio_url)
    .sort((a, b) => Date.parse(b.slot) - Date.parse(a.slot));
}

export function chooseEdition(editions, language, id, now = Date.now()) {
  const available = availableEditions(editions, language, now);
  return available.find(e => e.id === id) || available[0] || null;
}

export function nextOnEnded(editions, language, selected, live, now = Date.now()) {
  return live ? chooseEdition(editions, language, null, now) : chooseEdition(editions, language, selected?.id, now);
}

export function mediaURL(value, base) {
  const url = new URL(value, base);
  if (url.origin !== new URL(base).origin || !url.pathname.startsWith("/media/") || !url.pathname.endsWith(".mp4")) {
    throw new Error("Unexpected media location");
  }
  return url.href;
}

export function programmeURL(base, id, language) {
  const url = new URL(base);
  url.search = "";
  url.hash = "";
  url.searchParams.set("edition", id);
  url.searchParams.set("lang", language);
  return url.href;
}

export function clockTime(seconds) {
  const safe = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}

export const userTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

export function calendarDay(value, timeZone = userTimeZone) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone, year:"numeric", month:"2-digit", day:"2-digit",
  }).format(new Date(value));
}

export function formatTimestamp(value, language, full = true, timeZone = userTimeZone) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  return new Intl.DateTimeFormat(language === "cn" ? "zh-CN" : "en-GB", {
    timeZone, ...(full ? {month:"2-digit",day:"2-digit"} : {}),
    hour:"2-digit",minute:"2-digit",hourCycle:"h23",timeZoneName:"shortOffset",
  }).format(date);
}
