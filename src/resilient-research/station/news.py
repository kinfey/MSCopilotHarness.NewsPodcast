import asyncio
import hashlib
import os
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx

from station.http import post_with_retry

AGENCIES = {
    "xinhua": ("xinhuanet.com", "news.cn"),
    "ap": ("apnews.com",),
    "afp": ("afp.com",),
    "bloomberg": ("bloomberg.com",),
}
TOPICS = {
    "domestic": "China news",
    "international": "world news",
}
CHINESE_TOPICS = {"domestic": "中国 国内 新闻", "international": "国际 新闻"}


def agency_for(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    host = parsed.hostname.lower()
    return next(
        (a for a, domains in AGENCIES.items() if any(host == d or host.endswith("." + d) for d in domains)), None
    )


def normalize_result(item: dict, category: str, collected_at: datetime, rank: int) -> dict | None:
    url = item.get("url", "")
    agency = agency_for(url)
    title = item.get("title")
    content = item.get("content") or ""
    if not agency or item.get("isAdult") or not isinstance(title, str) or not title.strip():
        return None
    if not isinstance(content, str):
        return None
    if re.search(r"\b(sports?|soccer|football|basketball|tennis)\b|体育|足球|篮球|网球", title, re.IGNORECASE):
        return None
    if "/sports/" in urlsplit(url).path.lower():
        return None
    reported_at = None
    value = item.get("lastUpdatedAt")
    if value:
        try:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is None:
                # WebIQ documents lastUpdatedAt as UTC but sometimes omits its suffix.
                stamp = stamp.replace(tzinfo=UTC)
            stamp = stamp.astimezone(UTC)
            if stamp > collected_at + timedelta(minutes=5) or stamp < collected_at - timedelta(hours=24):
                return None
            reported_at = stamp.isoformat()
        except (ValueError, TypeError):
            return None
    parsed = urlsplit(url)
    article_date = re.search(r"/(20\d{2})(\d{2})(\d{2})/", parsed.path)
    if article_date:
        try:
            day = datetime(*map(int, article_date.groups()), tzinfo=UTC)
            if day.date() < (collected_at - timedelta(hours=24)).date() or day.date() > collected_at.date():
                return None
        except ValueError:
            return None
    canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    discovery_only = parsed.path.rstrip("/") in ("", "/en", "/en/homepage", "/home", "/world", "/china") or bool(
        re.search(r"homepage|news advisory|news hub|redirecting|新闻预告", title, re.IGNORECASE)
    )
    return {
        "id": hashlib.sha256(f"{category}:{canonical}".encode()).hexdigest()[:16],
        "category": category,
        "agency": agency,
        "title": title[:300],
        "url": url,
        "content": content[:3000],
        "discovery_only": discovery_only,
        "reported_at": reported_at,
        "time_basis": "updated" if reported_at else "unknown",
        "retrieved_at": collected_at.isoformat(),
        "search_rank": rank,
    }


def ranked(items: list[dict], now: datetime) -> list[dict]:
    unique = {item["id"]: item for item in reversed(items)}
    values = list(unique.values())
    tokens = [set(re.findall(r"[a-z]{4,}", x["title"].lower())) for x in values]
    for i, item in enumerate(values):
        corroborating = {
            other["agency"]
            for j, other in enumerate(values)
            if i != j and tokens[i] and len(tokens[i] & tokens[j]) / max(1, len(tokens[i] | tokens[j])) >= 0.3
        }
        age = 24.0
        if item["reported_at"]:
            age = max(0, (now - datetime.fromisoformat(item["reported_at"])).total_seconds() / 3600)
        item["selection_score"] = round(3 * len(corroborating) + 2 / (1 + age) + 1 / (1 + item["search_rank"]), 4)
    return sorted(values, key=lambda x: x["selection_score"], reverse=True)


async def collect() -> dict:
    now = datetime.now(UTC)
    key = os.environ["WEBIQ_API_KEY"]
    semaphore = asyncio.Semaphore(1)
    failures = []
    async with httpx.AsyncClient(timeout=60) as client:

        async def search(category, agency):
            domains = AGENCIES[agency]
            query = (
                f"{now.astimezone(ZoneInfo('Asia/Shanghai')):%Y年%m月%d日} {CHINESE_TOPICS[category]} 新华社"
                if agency == "xinhua"
                else f"{now:%Y-%m-%d} {TOPICS[category]} ({' OR '.join('site:' + d for d in domains)})"
            )
            payload = {
                "query": query,
                "maxResults": 8,
                "language": "zh" if agency == "xinhua" else "en",
                "region": "CN" if agency == "xinhua" else "US",
                "contentFormat": "passage",
                "maxLength": 3000,
            }
            async with semaphore:
                await asyncio.sleep(1)
                try:
                    response = await post_with_retry(
                        client,
                        "https://api.microsoft.ai/v3/search/news",
                        headers={"x-apikey": key},
                        json=payload,
                    )
                    raw = response.json().get("newsResults", [])
                    results = [
                        normalized
                        for i, item in enumerate(raw)
                        if (normalized := normalize_result(item, category, now, i)) and normalized["agency"] == agency
                    ]
                    if not any(x["content"].strip() and not x["discovery_only"] for x in results):
                        payload["query"] = (
                            f"{now.astimezone(ZoneInfo('Asia/Shanghai')):%Y年%m月%d日} "
                            f"{CHINESE_TOPICS[category]} site:{domains[-1]}"
                            if agency == "xinhua"
                            else query
                        )
                        response = await post_with_retry(
                            client,
                            "https://api.microsoft.ai/v3/search/web",
                            headers={"x-apikey": key},
                            json=payload,
                        )
                        results.extend(
                            normalized
                            for i, item in enumerate(response.json().get("webResults", []))
                            if (normalized := normalize_result(item, category, now, i))
                            and normalized["agency"] == agency
                            and normalized["reported_at"]
                        )
                    if category == "international" and agency != "xinhua":
                        for focus in ("politics diplomacy conflict", "economy business disasters"):
                            usable = {
                                r["id"]
                                for r in results
                                if r["reported_at"] and r["content"].strip() and not r["discovery_only"]
                            }
                            if len(usable) >= 2:
                                break
                            supplement = {
                                **payload,
                                "query": f"latest world news {focus} ({' OR '.join('site:' + d for d in domains)})",
                            }
                            for endpoint, field in (("news", "newsResults"), ("web", "webResults")):
                                await asyncio.sleep(1)
                                try:
                                    response = await post_with_retry(
                                        client,
                                        f"https://api.microsoft.ai/v3/search/{endpoint}",
                                        headers={"x-apikey": key},
                                        json=supplement,
                                    )
                                    found = [
                                        r
                                        for i, item in enumerate(response.json().get(field, []))
                                        if (r := normalize_result(item, category, now, i))
                                        and r["agency"] == agency
                                        and r["reported_at"]
                                        and r["content"].strip()
                                        and not r["discovery_only"]
                                    ]
                                    results.extend(found)
                                    if found:
                                        break
                                except (RuntimeError, httpx.HTTPError):
                                    failures.append(
                                        {
                                            "category": category,
                                            "agency": agency,
                                            "reason": "diversity_search_unavailable",
                                        }
                                    )
                    return results
                except (RuntimeError, httpx.HTTPError):
                    failures.append({"category": category, "agency": agency, "reason": "source_unavailable"})
                    return []

        batches = await asyncio.gather(*(search(c, a) for c in TOPICS for a in AGENCIES))
    evidence = [item for batch in batches for item in batch]
    selected = []
    for category in TOPICS:
        candidates = ranked([x for x in evidence if x["category"] == category], now)
        if not any(x["reported_at"] for x in candidates):
            raise RuntimeError(f"No verifiably fresh evidence for {category}; keep playing previous broadcast")
        chosen = []
        for agency in AGENCIES:
            options = [x for x in candidates if x["agency"] == agency]
            options.sort(
                key=lambda x: bool(x["reported_at"] and x["content"].strip() and not x["discovery_only"]), reverse=True
            )
            chosen.extend(options[:3])
        selected.extend(chosen)
    return {
        "collected_at": now.isoformat(),
        "evidence": selected,
        "failures": failures,
        "missing_agencies": [
            a
            for a in AGENCIES
            if not any(
                x["agency"] == a and x["reported_at"] and x["content"].strip() and not x["discovery_only"]
                for x in selected
            )
        ],
        "ranking_method": "Agency-balanced candidates, WebIQ relevance, recency and cross-agency headline overlap; not measured audience popularity",
    }


async def expand(package: dict, briefs) -> dict:
    """Search specific missing details, retaining only official-source, fresh results."""
    now = datetime.now(UTC)
    by_id = {item["id"]: item for item in package["evidence"]}
    requests = []
    for section in briefs.sections:
        for topic in section.topics:
            refs = [by_id[i] for i in topic.evidence_ids]
            thin = (
                len(topic.facts) < 3
                or not any(r["reported_at"] and not r.get("discovery_only") for r in refs)
                or all(len(r["content"].strip()) < 600 or r.get("discovery_only") for r in refs)
            )
            queries = topic.search_queries
            if thin and not queries:
                queries = [topic.title]
            for query in queries[:2]:
                requests.append((section.category, topic.id, query[:500]))
    if not requests:
        return package
    evidence = dict(by_id)
    expansions = []
    domains = " OR ".join(f"site:{d}" for agency_domains in AGENCIES.values() for d in agency_domains)
    async with httpx.AsyncClient(timeout=60) as client:
        for category, topic_id, query in requests:
            chinese = bool(re.search(r"[\u3400-\u9fff]", query))
            date = f"{now.astimezone(ZoneInfo('Asia/Shanghai')):%Y年%m月%d日}" if chinese else f"{now:%Y-%m-%d}"
            payload = {
                "query": f"{date} {query} ({domains})",
                "maxResults": 8,
                "language": "zh" if chinese else "en",
                "region": "CN" if chinese else "US",
                "contentFormat": "passage",
                "maxLength": 3000,
            }
            found = []
            failed = False
            for endpoint, field in (("news", "newsResults"), ("web", "webResults")):
                await asyncio.sleep(1)
                try:
                    response = await post_with_retry(
                        client,
                        f"https://api.microsoft.ai/v3/search/{endpoint}",
                        headers={"x-apikey": os.environ["WEBIQ_API_KEY"]},
                        json=payload,
                    )
                    found = [
                        result
                        for i, raw in enumerate(response.json().get(field, []))
                        if (result := normalize_result(raw, category, now, i))
                        and result["reported_at"]
                        and result["content"].strip()
                        and not result["discovery_only"]
                    ]
                    if found:
                        break
                except (RuntimeError, httpx.HTTPError):
                    failed = True
            for item in found:
                existing = evidence.get(item["id"])
                if existing is None or len(item["content"]) > len(existing["content"]):
                    evidence[item["id"]] = item
            expansions.append(
                {
                    "topic_id": topic_id,
                    "query": query,
                    "evidence_ids": [item["id"] for item in found],
                    "status": "found" if found else ("source_unavailable" if failed else "no_verified_detail"),
                }
            )
    selected = list(evidence.values())
    return {
        **package,
        "collected_at": now.isoformat(),
        "evidence": selected,
        "expansions": expansions,
        "missing_agencies": [
            a
            for a in AGENCIES
            if not any(x["agency"] == a and not x.get("discovery_only") and x["content"].strip() for x in selected)
        ],
    }
