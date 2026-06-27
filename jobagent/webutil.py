"""Small helpers for the web UI: pagination, date parsing, and a 'next scan in…' string."""
import re
from datetime import datetime, timezone

from .ingest.runner import _parse_date  # ISO 8601 / epoch-ms tolerant parser

_SLASH = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$")


def to_dt(s):
    """Tolerant date parse for tracker/insights: ISO 8601, epoch-ms, and human
    slash/dash formats (M/D/Y, D/M/Y, Y/M/D) — e.g. Google Sheets '10/14/2025'."""
    dt = _parse_date(s)
    if dt:
        return dt
    if not s:
        return None
    text = str(s).strip()
    try:                                   # 2025/10/14 (slashes; fromisoformat won't take these)
        return datetime.strptime(text, "%Y/%m/%d").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    m = _SLASH.match(text)
    if not m:
        return None
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    if a > 12 and b <= 12:                 # 14/10/2025 → day-first
        mon, day = b, a
    else:                                  # default US month-first (10/14/2025)
        mon, day = a, b
        if mon > 12:                       # both >12 is invalid; give up
            return None
    try:
        return datetime(y, mon, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def paginate(rows, page, per_page=20):
    """Slice `rows` for the given 1-based page. Returns (page_rows, meta)."""
    rows = list(rows)
    total = len(rows)
    pages = max(1, (total + per_page - 1) // per_page)
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    meta = {"page": page, "pages": pages, "total": total, "per_page": per_page,
            "start": start + 1 if total else 0, "end": min(start + per_page, total)}
    return rows[start:start + per_page], meta


def human_until(dt) -> str:
    """'in 3h 12m' / 'in 14m' / 'due now' / 'off' from a tz-aware datetime."""
    if not dt:
        return "off"
    now = datetime.now(dt.tzinfo or timezone.utc)
    secs = int((dt - now).total_seconds())
    if secs <= 0:
        return "due now"
    h, m = secs // 3600, (secs % 3600) // 60
    if h >= 24:
        d = h // 24
        return f"in {d}d {h % 24}h"
    return f"in {h}h {m}m" if h else f"in {m}m"
