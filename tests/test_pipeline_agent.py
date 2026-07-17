import jobagent.pipeline as pl
from jobagent.llm import LLMError
from jobagent.models import Job
from jobagent.store import Store


def _seed_sent(cfg, items):
    s = Store(cfg["paths"]["db"])
    for title, score, url in items:
        j = Job(source="s", title=title, company="c", url=url)
        s.upsert_job(j)
        j.score, j.reasons, j.gaps = score, "", ""
        s.save_score(j)
        s.set_status(j.job_id, "sent")
    s.close()


def _no_scan(monkeypatch):
    monkeypatch.setattr(pl, "scan", lambda c, stats=None:
                        stats.update(scanned=0, scored=0, matched=0) if stats is not None else None)


def test_needs_manual_apply():
    assert pl.needs_manual_apply({"url": "https://acme.wd1.myworkdayjobs.com/x"})
    assert pl.needs_manual_apply({"url": "https://jobs.lever.co/x"}) is False
    assert pl.needs_manual_apply({"url": ""}) is False


def test_agent_run_generates_top_and_respects_cap(cfg, monkeypatch):
    cfg["agent"] = {"enabled": True, "min_score": 80, "daily_cap": 2}
    _no_scan(monkeypatch)
    _seed_sent(cfg, [("A", 90, "u-a"), ("B", 85, "u-b"), ("C", 70, "u-c")])
    monkeypatch.setattr(pl, "pick_and_generate",
                        lambda ids, c: iter([({"job_id": ids[0]}, ["/out/r.docx"])]))
    summary = pl.agent_run(cfg)
    assert {g["title"] for g in summary["generated"]} == {"A", "B"}   # C below min_score; cap=2
    assert not summary["attention"] and summary["error"] is None


def test_agent_run_flags_on_llm_error(cfg, monkeypatch):
    cfg["agent"] = {"enabled": True, "min_score": 80, "daily_cap": 5}
    _no_scan(monkeypatch)
    _seed_sent(cfg, [("A", 90, "u-a"), ("B", 88, "u-b")])

    def boom(ids, c):
        raise LLMError("Fallback: rate limit or quota exhausted")
    monkeypatch.setattr(pl, "pick_and_generate", boom)

    summary = pl.agent_run(cfg)
    assert summary["error"] and not summary["generated"]
    assert len(summary["attention"]) == 2                 # current + remaining flagged
    s = Store(cfg["paths"]["db"])
    assert len(s.needs_attention()) == 2
    s.close()


def test_agent_run_flags_manual_portal(cfg, monkeypatch):
    cfg["agent"] = {"enabled": True, "min_score": 80, "daily_cap": 5}
    _no_scan(monkeypatch)
    _seed_sent(cfg, [("WD", 90, "https://x.myworkdayjobs.com/job/1")])
    monkeypatch.setattr(pl, "pick_and_generate",
                        lambda ids, c: iter([({"job_id": ids[0]}, ["/out/r.docx"])]))
    summary = pl.agent_run(cfg)
    assert not summary["generated"]
    assert len(summary["attention"]) == 1 and summary["attention"][0]["kind"] == "manual_portal"
