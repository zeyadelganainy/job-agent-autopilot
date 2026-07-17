import pytest

from jobagent import score
from jobagent.llm import LLMError
from jobagent.models import Job


def _job():
    return Job(source="s", title="t", company="c", url="u", description="d")


def test_score_job_reraises_llmerror(monkeypatch):
    def boom(*a, **k):
        raise LLMError("No LLM could respond — Fallback: rate limit or quota exhausted.")
    monkeypatch.setattr(score, "chat", boom)
    with pytest.raises(LLMError):
        score.score_job(_job(), {}, {"claude": "c", "fallback": "f"})


def test_score_job_handles_unparseable(monkeypatch):
    monkeypatch.setattr(score, "chat", lambda s, u, m: "not json at all")
    j = _job()
    score.score_job(j, {}, {"claude": "c", "fallback": "f"})
    assert j.score == 0 and "scoring failed" in j.reasons
