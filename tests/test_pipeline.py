import jobagent.pipeline as pl
from jobagent.models import Job
from jobagent.store import Store


def _seed(cfg, titles_scores):
    s = Store(cfg["paths"]["db"])
    for t, sc in titles_scores:
        j = Job(source="s", title=t, company="c", url=f"u-{t}")
        s.upsert_job(j)
        j.score, j.reasons, j.gaps = sc, "", ""
        s.save_score(j)
        s.set_status(j.job_id, "sent")
    return s


def test_format_digest_empty():
    assert "No jobs" in pl.format_digest([])


def test_format_digest_numbering_escaping_and_links():
    jobs = [
        {"title": "A & B <x>", "company": "c", "score": 40,
         "location": "Remote", "reasons": "r", "url": "http://u/1"},
        {"title": "B", "company": "c", "score": None},   # None score -> 0
    ]
    out = pl.format_digest(jobs)
    assert "<b>1.</b>" in out and "<b>2.</b>" in out
    assert "A &amp; B &lt;x&gt;" in out                  # HTML-escaped
    assert 'href="http://u/1"' in out
    assert "40% match" in out and "0% match" in out


def test_pending_is_in_display_order(cfg):
    _seed(cfg, [("low", 10), ("high", 90)])
    assert [r["title"] for r in pl.pending(cfg)] == ["high", "low"]


def test_picks_to_ids_maps_numbers_and_flags_bad(cfg):
    _seed(cfg, [("high", 90), ("low", 10)])
    rows = pl.pending(cfg)
    ids, bad = pl.picks_to_ids(["1", "2", "x", "5"], cfg)
    assert ids == [rows[0]["job_id"], rows[1]["job_id"]]
    assert bad == ["x", "5"]


def test_scan_caps_and_rolls_over(cfg, monkeypatch):
    fake = [Job(source="s", title=f"Engineer {i}", company="c",
                url=f"u{i}", description="engineer") for i in range(6)]
    monkeypatch.setattr(pl, "gather", lambda c: list(fake))
    monkeypatch.setattr(pl, "load_profile", lambda c: {})

    def fake_score(j, profile, models):
        j.score, j.reasons, j.gaps = 70, "", ""
        return j

    monkeypatch.setattr(pl, "score_job", fake_score)

    cfg["scoring"]["max_to_score"] = 2
    pl.scan(cfg)
    assert len(Store(cfg["paths"]["db"]).by_status("sent")) == 2
    pl.scan(cfg)   # leftovers picked up, not stranded
    assert len(Store(cfg["paths"]["db"]).by_status("sent")) == 4


def test_scan_cap_zero_is_unlimited(cfg, monkeypatch):
    fake = [Job(source="s", title=f"Engineer {i}", company="c",
                url=f"u{i}", description="engineer") for i in range(5)]
    monkeypatch.setattr(pl, "gather", lambda c: list(fake))
    monkeypatch.setattr(pl, "load_profile", lambda c: {})
    monkeypatch.setattr(pl, "score_job",
                        lambda j, p, m: (setattr(j, "score", 70) or j))
    cfg["scoring"]["max_to_score"] = 0
    pl.scan(cfg)
    assert len(Store(cfg["paths"]["db"]).by_status("sent")) == 5
