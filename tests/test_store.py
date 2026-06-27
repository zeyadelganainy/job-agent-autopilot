import json

from jobagent.models import Job
from jobagent.store import Store


def _job(title, url=None):
    return Job(source="s", title=title, company="c", url=url or f"u-{title}")


def _sent(store, title, score):
    j = _job(title)
    store.upsert_job(j)
    j.score, j.reasons, j.gaps = score, "", ""
    store.save_score(j)
    store.set_status(j.job_id, "sent")
    return j.job_id


def test_upsert_dedup(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    j = _job("A")
    assert s.upsert_job(j) is True
    assert s.upsert_job(j) is False     # already seen


def test_save_score_sets_status_scored(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    j = _job("A")
    s.upsert_job(j)
    j.score, j.reasons, j.gaps = 80, "good fit", ""
    s.save_score(j)
    row = s.get(j.job_id)
    assert row["score"] == 80 and row["status"] == "scored"


def test_by_status_orders_by_score_desc(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    for t, sc in [("low", 10), ("high", 90), ("mid", 50)]:
        _sent(s, t, sc)
    assert [r["title"] for r in s.by_status("sent")] == ["high", "mid", "low"]


def test_record_docs_sets_generated(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    j = _job("A")
    s.upsert_job(j)
    s.record_docs(j.job_id, ["a.md", "b.docx"])
    row = s.get(j.job_id)
    assert json.loads(row["docs"]) == ["a.md", "b.docx"]
    assert row["status"] == "generated"
