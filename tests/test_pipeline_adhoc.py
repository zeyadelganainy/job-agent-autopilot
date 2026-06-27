import json

from jobagent import pipeline
from jobagent.models import Job
from jobagent.store import Store


def _cfg(tmp_path):
    cfg = dict(pipeline.load_config())
    cfg["paths"] = dict(cfg["paths"])
    cfg["paths"]["db"] = str(tmp_path / "t.db")
    cfg["paths"]["output"] = str(tmp_path / "out")
    return cfg


def _stub_generation(monkeypatch, paths):
    monkeypatch.setattr(pipeline, "generate", lambda *a, **k: list(paths))
    monkeypatch.setattr(pipeline, "load_profile", lambda c: {"identity": {"name": "Z"}})
    monkeypatch.setattr(pipeline, "load_samples", lambda c: "")
    monkeypatch.setattr(pipeline, "load_master", lambda c: "master")


def test_generate_for_jd_pasted_text(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _stub_generation(monkeypatch, ["a_resume.docx", "a_coverLetter.docx"])
    row, paths = pipeline.generate_for_jd("Backend role at Acme, C#/.NET.", cfg,
                                          title="Backend Engineer", company="Acme")
    assert paths == ["a_resume.docx", "a_coverLetter.docx"]
    assert row["source"] == "adhoc" and row["company"] == "Acme" and row["status"] == "generated"
    s = Store(cfg["paths"]["db"])
    assert json.loads(s.get(row["job_id"])["docs"]) == paths
    s.close()


def test_generate_for_jd_url(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _stub_generation(monkeypatch, ["r.docx"])
    monkeypatch.setattr(pipeline.ats, "fetch_job",
                        lambda u: Job(source="greenhouse", title="SWE", company="d2l",
                                      url="https://x", description="jd text"))
    row, paths = pipeline.generate_for_jd("https://boards.greenhouse.io/d2l/jobs/1", cfg)
    assert paths == ["r.docx"] and row["company"] == "d2l" and row["title"] == "SWE"


def test_generate_for_jd_blank_raises(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        pipeline.generate_for_jd("   ", _cfg(tmp_path))
