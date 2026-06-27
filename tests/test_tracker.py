from jobagent import tracker
from jobagent.store import Store

CSV = (
    "role,company,date applied,stage,location,notes\n"
    "Backend Engineer,D2L,2026-06-01,Applied,Toronto,referred\n"
    "Software Engineer,Stripe,2026-06-02,Interview,Remote,\n"
)


def test_parse_and_guess_mapping():
    headers, rows = tracker.parse(CSV)
    assert headers == ["role", "company", "date applied", "stage", "location", "notes"]
    assert len(rows) == 2
    m = tracker.guess_mapping(headers)
    assert m["role"] == "role" and m["company"] == "company"
    assert m["applied_date"] == "date applied" and m["stage"] == "stage"
    assert m["location"] == "location" and m["notes"] == "notes"


def test_import_csv_inserts_then_upserts(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    r1 = tracker.import_csv(CSV, s)
    assert (r1["inserted"], r1["updated"], r1["total"]) == (2, 0, 2)
    assert len(s.list_applications()) == 2

    # re-import with a changed stage -> updates in place, no duplicates
    r2 = tracker.import_csv(CSV.replace("Applied", "Offer"), s)
    assert (r2["inserted"], r2["updated"]) == (0, 2)
    assert len(s.list_applications()) == 2
    stages = {a["company"]: a["stage"] for a in s.list_applications()}
    assert stages["D2L"] == "Offer"
    s.close()


def test_is_active():
    assert tracker.is_active("Applied") and tracker.is_active("Interview")
    assert not tracker.is_active("Rejected") and not tracker.is_active("ghosted")


def test_auto_ghost(tmp_path):
    from datetime import datetime, timedelta
    s = Store(str(tmp_path / "t.db"))
    old = (datetime.now() - timedelta(weeks=6)).strftime("%m/%d/%Y")
    recent = (datetime.now() - timedelta(weeks=1)).strftime("%m/%d/%Y")
    s.add_application({"role": "A", "company": "Old", "applied_date": old, "stage": "Applied"})
    s.add_application({"role": "B", "company": "Fresh", "applied_date": recent, "stage": "Applied"})
    s.add_application({"role": "C", "company": "Interviewing", "applied_date": old, "stage": "Interview"})

    n = tracker.auto_ghost(s, 4)
    assert n == 1                                  # only the old "Applied" one
    stages = {a["company"]: a["stage"] for a in s.list_applications()}
    assert stages["Old"] == "Ghosted"
    assert stages["Fresh"] == "Applied"            # too recent
    assert stages["Interviewing"] == "Interview"   # not at "Applied"
    s.close()
