import re
from datetime import datetime

from station.timeutil import BEIJING

DATED_BLOB = re.compile(r"^(?:jobs|retired|cn|en|media/cn|media/en)/(\d{8})/")


class BroadcastExpiredError(ValueError):
    pass


def today_key() -> str:
    return datetime.now(BEIJING).strftime("%Y%m%d")


def slot_day(slot: datetime) -> str:
    if slot.tzinfo is None:
        raise ValueError("Retention requires a timezone-aware slot")
    return slot.astimezone(BEIJING).strftime("%Y%m%d")


def require_current(slot: datetime):
    if slot_day(slot) != today_key():
        raise BroadcastExpiredError("Only today's broadcasts are retained, in Asia/Shanghai")


def blob_day(name: str) -> str | None:
    match = DATED_BLOB.match(name)
    if match:
        value = match[1]
        datetime.strptime(value, "%Y%m%d")
        return value
    return None
