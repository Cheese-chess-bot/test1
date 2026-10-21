"""Exchange-clock scheduling; never infer market holidays from weekdays."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


def timestamp(value: str) -> float:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Exchange timestamps must include a timezone")
    return dt.timestamp()


def describe_clock(clock: dict) -> str:
    key = "next_close" if clock["is_open"] else "next_open"
    dt = datetime.fromtimestamp(timestamp(clock[key]), timezone.utc)
    ny = dt.astimezone(ZoneInfo("America/New_York"))
    india = dt.astimezone(ZoneInfo("Asia/Kolkata"))
    return f"{'closes' if clock['is_open'] else 'opens'} {ny:%a %Y-%m-%d %H:%M %Z} / {india:%a %Y-%m-%d %H:%M %Z}"


def closed_wait(clock: dict, now: float) -> float:
    # Recheck for changed schedules at least every 30 seconds, and wake at open.
    return max(1.0, min(30.0, timestamp(clock["next_open"]) - now))


def next_stock_bar(clock: dict, now: float, seconds: float, settle: float) -> float:
    """Session-anchored bars, including a short final bar on early-close days."""
    close = timestamp(clock["next_close"])
    date = datetime.fromtimestamp(close, ZoneInfo("America/New_York")).date()
    opened = datetime.combine(date, time(9, 30), ZoneInfo("America/New_York")).timestamp()
    import math
    boundary = opened + max(1, math.floor((now - settle - opened) / seconds) + 1) * seconds
    # At session close the loop wakes and checks the clock again; no after-hours orders.
    return min(boundary + settle, close)
