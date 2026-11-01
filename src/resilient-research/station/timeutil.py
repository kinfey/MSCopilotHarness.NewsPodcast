from datetime import datetime
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")


def current_slot(now: datetime | None = None) -> datetime:
    now = now or datetime.now(BEIJING)
    if now.tzinfo is None:
        raise ValueError("Timezone is required")
    now = now.astimezone(BEIJING)
    return now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)


def manual_slot(now: datetime | None = None) -> datetime:
    now = now or datetime.now(BEIJING)
    if now.tzinfo is None:
        raise ValueError("Timezone is required")
    return now.astimezone(BEIJING).replace(second=0, microsecond=0)


def parse_slot(value: str, *, aligned: bool = True) -> datetime:
    slot = datetime.fromisoformat(value)
    if slot.tzinfo is None:
        raise ValueError("Timezone is required")
    slot = slot.astimezone(BEIJING)
    if (aligned and slot.minute not in (0, 30)) or slot.second or slot.microsecond:
        raise ValueError("Use whole minutes; scheduled slots must be aligned to half an hour")
    return slot
