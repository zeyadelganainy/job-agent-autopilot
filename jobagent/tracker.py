"""Import a Google Sheets application tracker (exported as CSV) into the editable
`applications` table. Auto-maps common column names; re-import upserts (no dupes).
Also: 'active' classification + auto-ghosting of stale applications."""
import csv
import io
from datetime import datetime, timedelta, timezone

from . import webutil

# Stages that mean an application is no longer in play.
INACTIVE_STAGES = {"rejected", "ghosted", "declined", "withdrawn"}

# our field -> accepted header names (lowercased; substring match as a fallback)
FIELD_ALIASES = {
    "role": ["role", "title", "position", "job title", "job"],
    "company": ["company", "employer", "organization", "org"],
    "applied_date": ["date applied", "applied date", "applied", "application date", "date"],
    "stage": ["stage", "status"],
    "location": ["location", "city", "place"],
    "notes": ["notes", "note", "comments", "comment"],
    "url": ["url", "link", "posting", "job url", "listing"],
}


def parse(content: str):
    reader = csv.DictReader(io.StringIO(content))
    return (reader.fieldnames or []), [dict(r) for r in reader]


def guess_mapping(headers: list[str]) -> dict:
    """Map our fields to the CSV's header names. Exact match wins over substring."""
    norm = {h: (h or "").strip().lower() for h in headers}
    mapping = {}
    for field, aliases in FIELD_ALIASES.items():
        hit = next((h for h in headers if norm[h] in aliases), None)
        if not hit:
            hit = next((h for h in headers if any(a in norm[h] for a in aliases)), None)
        if hit:
            mapping[field] = hit
    return mapping


def _dedupe_key(role, company, url) -> str:
    if url and url.strip():
        return url.strip().lower()
    return f"{(company or '').strip().lower()}|{(role or '').strip().lower()}"


def to_application(row: dict, mapping: dict) -> dict:
    def g(field):
        return (row.get(mapping[field]) or "").strip() if field in mapping else ""
    role, company, url = g("role"), g("company"), g("url")
    return {
        "role": role, "company": company, "applied_date": g("applied_date"),
        "stage": g("stage"), "location": g("location"), "notes": g("notes"),
        "url": url, "source": "import", "dedupe_key": _dedupe_key(role, company, url),
    }


def import_csv(content: str, store) -> dict:
    """Parse + upsert. Returns {inserted, updated, total, mapping}."""
    headers, rows = parse(content)
    mapping = guess_mapping(headers)
    inserted = updated = 0
    for row in rows:
        app = to_application(row, mapping)
        if not (app["company"] or app["role"]):     # skip blank rows
            continue
        if store.upsert_application(app) == "inserted":
            inserted += 1
        else:
            updated += 1
    return {"inserted": inserted, "updated": updated, "total": len(rows), "mapping": mapping}


def is_active(stage) -> bool:
    """An application still in play (not rejected/ghosted/declined/withdrawn)."""
    return (stage or "").strip().lower() not in INACTIVE_STAGES


def auto_ghost(store, weeks: int) -> int:
    """Mark still-'Applied' applications older than `weeks` weeks as 'Ghosted'.

    Only touches rows whose stage is exactly 'Applied' (anything further along — interview,
    offer, etc. — is left alone). Returns how many were ghosted.
    """
    if not weeks or weeks <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(weeks=weeks)
    ghosted = 0
    for r in store.list_applications():
        if (r["stage"] or "").strip().lower() != "applied":
            continue
        dt = webutil.to_dt(r["applied_date"])
        if dt and dt < cutoff:
            store.set_application_stage(r["id"], "Ghosted")
            ghosted += 1
    return ghosted
