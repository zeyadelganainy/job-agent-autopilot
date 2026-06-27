import pytest

from jobagent.ingest import ats


class FakeResp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def test_fetch_job_greenhouse(monkeypatch):
    def fake_get(url, **k):
        assert "boards-api.greenhouse.io/v1/boards/d2l/jobs/123" in url
        return FakeResp({"title": "Software Developer - New Graduate",
                         "location": {"name": "Toronto, ON, Canada"},
                         "content": "<p>Build &amp; ship</p>",
                         "absolute_url": "https://d2l/x", "updated_at": "2026-06-25"})
    monkeypatch.setattr(ats.requests, "get", fake_get)
    j = ats.fetch_job("https://boards.greenhouse.io/d2l/jobs/123")
    assert j.source == "greenhouse" and j.company == "d2l"
    assert "Software Developer" in j.title and j.location == "Toronto, ON, Canada"
    assert "Build" in j.description and "ship" in j.description


def test_fetch_job_lever(monkeypatch):
    def fake_get(url, **k):
        assert "api.lever.co/v0/postings/acme/abc-123" in url
        return FakeResp({"text": "Backend Engineer", "categories": {"location": "Vancouver"},
                         "descriptionPlain": "Do backend work", "hostedUrl": "https://h",
                         "createdAt": 1718884800000})
    monkeypatch.setattr(ats.requests, "get", fake_get)
    j = ats.fetch_job("https://jobs.lever.co/acme/abc-123")
    assert j.source == "lever" and j.title == "Backend Engineer" and j.location == "Vancouver"


def test_fetch_job_ashby(monkeypatch):
    def fake_get(url, **k):
        return FakeResp({"jobs": [{"id": "uuid-1", "title": "SWE", "location": "Remote",
                                   "descriptionPlain": "x",
                                   "jobUrl": "https://jobs.ashbyhq.com/acme/uuid-1",
                                   "publishedAt": "2026-06-01"}]})
    monkeypatch.setattr(ats.requests, "get", fake_get)
    j = ats.fetch_job("https://jobs.ashbyhq.com/acme/uuid-1")
    assert j.source == "ashby" and j.title == "SWE"


def test_fetch_job_unsupported_url():
    with pytest.raises(ValueError):
        ats.fetch_job("https://example.com/careers/123")
