from typing import Optional
from datetime import datetime, timedelta


UTC3_OFFSET = timedelta(hours=3)


def now_utc() -> datetime:
    return datetime.utcnow()


def now_utc3() -> datetime:
    return now_utc() + UTC3_OFFSET


def utc3_to_utc(dt_utc3: datetime) -> datetime:
    return dt_utc3 - UTC3_OFFSET


def parse_utc3_input_to_utc_iso(text: str) -> str:
    raw = text.strip()
    low = raw.lower()

    if low in ("сейчас", "now"):
        return now_utc().replace(microsecond=0).isoformat()

    if len(raw) == 5 and raw[2] == ":":
        hh, mm = raw.split(":")
        if not (hh.isdigit() and mm.isdigit()):
            raise ValueError("bad time")
        base = now_utc3()
        candidate = base.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if candidate <= base:
            candidate = candidate + timedelta(days=1)
        return utc3_to_utc(candidate).replace(microsecond=0).isoformat()

    dt_utc3 = datetime.strptime(raw, "%d.%m.%Y %H:%M").replace(second=0, microsecond=0)
    return utc3_to_utc(dt_utc3).replace(microsecond=0).isoformat()


def parse_utc_iso(s: str) -> datetime:
    s = (s or "").replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=None).replace(tzinfo=None)
    return dt


def utc_iso_to_utc3_human(s: Optional[str]) -> str:
    if not s:
        return "—"
    dt_utc = parse_utc_iso(s)
    dt_utc3 = dt_utc + UTC3_OFFSET
    return dt_utc3.strftime("%d.%m.%Y %H:%M")


def buttons_status(buttons: Optional[list]) -> str:
    return "🟢" if buttons else "🔴"


def status_emoji(status: str) -> str:
    return {
        "draft": "📝",
        "scheduled": "⏳",
        "sending": "📡",
        "sent": "✅",
        "failed": "❌",
        "cancelled": "🛑",
    }.get(status or "", "•")


def short_text(s: Optional[str], n: int = 60) -> str:
    if not s:
        return ""
    s = s.strip()
    return s if len(s) <= n else s[:n] + "…"
