from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["domestic", "international"]
Speaker = Literal["male", "female"]


class BriefFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(min_length=1)


class TopicBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=180)
    evidence_ids: list[str] = Field(min_length=1)
    facts: list[BriefFact] = Field(max_length=8)
    missing_details: list[str] = Field(max_length=3)
    search_queries: list[str] = Field(max_length=2)


class BriefSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    topics: list[TopicBrief] = Field(min_length=1, max_length=8)


class NewsBriefs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sections: list[BriefSection] = Field(min_length=2, max_length=2)


def validate_briefs(briefs: NewsBriefs, evidence: list[dict], ready=False) -> None:
    if [s.category for s in briefs.sections] != ["domestic", "international"]:
        raise ValueError("Expected domestic, international briefing order")
    by_id = {item["id"]: item for item in evidence}
    topic_ids = set()
    used_urls = set()
    for section in briefs.sections:
        for topic in section.topics:
            if topic.id in topic_ids:
                raise ValueError("Topic identifiers must be unique")
            topic_ids.add(topic.id)
            refs = []
            for evidence_id in topic.evidence_ids:
                if evidence_id not in by_id or by_id[evidence_id]["category"] != section.category:
                    raise ValueError("Unknown or cross-category briefing evidence")
                refs.append(by_id[evidence_id])
            for fact in topic.facts:
                if not set(fact.evidence_ids) <= set(topic.evidence_ids):
                    raise ValueError("Brief facts must cite their topic evidence")
                if any(by_id[i].get("discovery_only") or not by_id[i]["content"].strip() for i in fact.evidence_ids):
                    raise ValueError("Headlines, indexes and advisories cannot substantiate facts")
            if ready:
                if len(topic.facts) < 2:
                    raise ValueError("Insufficient verified facts; omit the topic instead of padding")
                factual_refs = [by_id[i] for fact in topic.facts for i in fact.evidence_ids]
                if not any(r["reported_at"] for r in factual_refs):
                    raise ValueError("Each reported topic needs fresh, substantive evidence")
                urls = {r["url"].split("?")[0] for r in factual_refs}
                if urls & used_urls:
                    raise ValueError("Consolidate overlapping topics instead of repeating the same report")
                used_urls.update(urls)


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speaker: Speaker
    text: str = Field(min_length=1, max_length=850)
    kind: Literal["fact", "transition", "opening", "closing"]
    topic_id: str | None
    evidence_ids: list[str]


class Headline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=180)
    topic_id: str
    evidence_ids: list[str] = Field(min_length=1)


class Chapter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    title: str
    headlines: list[Headline] = Field(min_length=1, max_length=4)
    turns: list[Turn] = Field(min_length=4, max_length=16)


class Script(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["cn", "en"]
    title: str
    chapters: list[Chapter] = Field(min_length=2, max_length=2)
    continuity: str = Field(max_length=1800)


def topic_agency(topic: TopicBrief, by_id: dict) -> str:
    refs = [i for fact in topic.facts for i in fact.evidence_ids] or topic.evidence_ids
    fresh = [i for i in refs if by_id[i]["reported_at"] and not by_id[i].get("discovery_only")]
    return Counter(by_id[i]["agency"] for i in fresh or refs).most_common(1)[0][0]


def validate_script(script: Script, evidence: list[dict], language: str, briefs: NewsBriefs | None = None) -> None:
    if script.language != language:
        raise ValueError("Wrong script language")
    if [c.category for c in script.chapters] != ["domestic", "international"]:
        raise ValueError("Expected domestic, international order")
    turns = [t for c in script.chapters for t in c.turns]
    if [(t.kind, t.speaker) for t in turns[:2]] != [("opening", "male"), ("opening", "female")]:
        raise ValueError("Begin with both hosts' station greetings and introductions")
    if [(t.kind, t.speaker) for t in turns[-2:]] != [("closing", "male"), ("closing", "female")]:
        raise ValueError("End with polite sign-offs from both hosts")
    if any(t.kind in ("opening", "closing") for t in turns[2:-2]):
        raise ValueError("Station greetings belong only at the beginning and end")
    by_id = {item["id"]: item for item in evidence}
    for chapter in script.chapters:
        speakers = {turn.speaker for turn in chapter.turns if turn.kind == "fact"}
        if not {"male", "female"} <= speakers:
            raise ValueError("Each chapter needs dialogue from both news hosts")
        topic_order = [h.topic_id for h in chapter.headlines]
        if len(set(topic_order)) != len(topic_order):
            raise ValueError("Consolidate duplicate headlines")
        topic_refs = {h.topic_id: set(h.evidence_ids) for h in chapter.headlines}
        if briefs:
            section = next(s for s in briefs.sections if s.category == chapter.category)
            if topic_order != [topic.id for topic in section.topics]:
                raise ValueError("Follow the prepared topic order without adding or dropping stories")
            for topic in section.topics:
                approved = {i for fact in topic.facts for i in fact.evidence_ids}
                if not topic_refs[topic.id] <= approved:
                    raise ValueError("Headlines must cite verified briefing facts")
                primary = topic_agency(topic, by_id)
                primary_ids = {i for i in approved if by_id[i]["agency"] == primary and by_id[i]["reported_at"]}
                if not topic_refs[topic.id] & primary_ids:
                    raise ValueError("Headlines must include their briefing's primary source")
                if not any(
                    turn.kind == "fact" and turn.topic_id == topic.id and bool(set(turn.evidence_ids) & primary_ids)
                    for turn in chapter.turns
                ):
                    raise ValueError("Report the briefing's primary source in factual speech")
        seen_topics = set()
        position = -1
        for item in [*chapter.headlines, *chapter.turns]:
            if isinstance(item, Turn) and item.kind == "fact" and not item.evidence_ids:
                raise ValueError("Facts need evidence")
            for evidence_id in item.evidence_ids:
                if evidence_id not in by_id or by_id[evidence_id]["category"] != chapter.category:
                    raise ValueError("Unknown or cross-category evidence")
                if by_id[evidence_id].get("discovery_only") or not by_id[evidence_id]["content"].strip():
                    raise ValueError("Report substantive articles, not discovery pages")
            if isinstance(item, Turn):
                if item.kind != "fact":
                    if item.evidence_ids or item.topic_id is not None:
                        raise ValueError("Station frames and transitions contain no news claims or topic citations")
                    continue
                if item.topic_id not in topic_refs or not set(item.evidence_ids) <= topic_refs[item.topic_id]:
                    raise ValueError("A factual turn must stay within its prepared topic")
                index = topic_order.index(item.topic_id)
                if index < position:
                    raise ValueError("Finish each story before moving on; do not jump back and forth")
                position = index
                seen_topics.add(item.topic_id)
        if seen_topics != set(topic_order):
            raise ValueError("Every headline needs substantive reporting")


from collections import Counter
