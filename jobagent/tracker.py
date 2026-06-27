"""Import a Google Sheets application tracker (exported as CSV) into the view-only
`applications` table. Auto-maps common column names; re-import upserts (no dupes)."""
import csv
import io

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
