"""Gather from all enabled sources, apply keyword/location/recency filters, dedupe."""
from datetime import datetime, timezone, timedelta

from ..models import Job
from . import ats, boards


def _keyword_match(job: Job, keywords: list[str]) -> bool:
    if not keywords:
        return True
    hay = f"{job.title} {job.description}".lower()
    return any(k.lower() in hay for k in keywords)


def _blocked(job: Job, blocklist: list[str]) -> bool:
    """True if the job's company matches any blocked term (case-insensitive substring).
    Use for recruiters / staffing agencies / known scams you never want to see."""
    if not blocklist:
        return False
    co = (job.company or "").lower()
    return any(b.strip().lower() in co for b in blocklist if b.strip())


def _location_match(job: Job, locations: list[str]) -> bool:
    """Keep the job if its location text contains any configured location token.
    Unknown (empty) locations are kept — the human stays in the loop."""
    if not locations:
        return True
    loc = (job.location or "").lower()
    if not loc:
        return True
    return any(t.lower() in loc for t in locations)


def _parse_date(s: str):
    """Best-effort parse of ATS date strings (ISO 8601 or epoch-ms). None if unknown."""
    if not s:
        return None
    s = str(s).strip()
    if s.isdigit():                                   # lever: epoch milliseconds
        try:
            return datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    try:                                              # greenhouse/ashby: ISO 8601
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_recent(job: Job, max_age_days) -> bool:
    """Keep if within max_age_days. Unparseable/missing dates are kept."""
    if not max_age_days:
        return True
    dt = _parse_date(job.posted)
    if dt is None:
        return True
    return datetime.now(timezone.utc) - dt <= timedelta(days=max_age_days)


def gather(cfg: dict) -> list[Job]:
    search = cfg["search"]
    jobs = ats.fetch_all(cfg["sources"]["ats"])
    jobs += boards.fetch_all(search, cfg["sources"]["boards"])

    keywords = search.get("keywords", [])
    locations = search.get("locations", [])
    blocklist = search.get("block_companies", [])
    max_age = search.get("max_age_days")

    seen, filtered = set(), []
    for j in jobs:
        if _blocked(j, blocklist):
            continue
        if not _keyword_match(j, keywords):
            continue
        if not _location_match(j, locations):
            continue
        if not _is_recent(j, max_age):
            continue
        if j.job_id in seen:
            continue
        seen.add(j.job_id)
        filtered.append(j)

    print(f"[ingest] {len(filtered)} jobs after keyword/location/recency filter + dedupe")
    return filtered
