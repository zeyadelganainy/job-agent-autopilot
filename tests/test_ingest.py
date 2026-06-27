from datetime import datetime, timezone, timedelta

from jobagent.ingest import runner
from jobagent.ingest.ats import _clean
from jobagent.models import Job


def test_clean_strips_tags_and_entities():
    assert _clean("<p>Hello&nbsp;<b>World</b></p>") == "Hello World"


def test_clean_handles_none():
    assert _clean(None) == ""


def test_keyword_match():
    j = Job(source="s", title="Backend Engineer", company="c", url="u")
    assert runner._keyword_match(j, ["engineer"])      # case-insensitive
    assert not runner._keyword_match(j, ["designer"])
    assert runner._keyword_match(j, [])                # no keywords => match all


def test_gather_filters_and_dedupes(monkeypatch):
    jobs = [
        Job(source="s", title="Backend Engineer", company="c", url="u1"),
        Job(source="s", title="Backend Engineer", company="c", url="u1"),  # dup job_id
        Job(source="s", title="Designer", company="c", url="u2"),          # filtered out
    ]
    monkeypatch.setattr(runner.ats, "fetch_all", lambda c: list(jobs))
    monkeypatch.setattr(runner.boards, "fetch_all", lambda s, b: [])
    out = runner.gather({"search": {"keywords": ["engineer"]},
                         "sources": {"ats": {}, "boards": {}}})
    assert [j.title for j in out] == ["Backend Engineer"]


def test_blocked():
    j = Job(source="s", title="t", company="Sketchy Recruiters Inc", url="u")
    assert runner._blocked(j, ["recruiters"])      # case-insensitive substring
    assert not runner._blocked(j, ["acme"])
    assert not runner._blocked(j, [])


def test_gather_applies_blocklist(monkeypatch):
    jobs = [Job(source="s", title="Engineer", company="Acme Corp", url="a"),
            Job(source="s", title="Engineer", company="Sketchy Recruiters Inc", url="b")]
    monkeypatch.setattr(runner.ats, "fetch_all", lambda c: list(jobs))
    monkeypatch.setattr(runner.boards, "fetch_all", lambda s, b: [])
    out = runner.gather({"search": {"keywords": ["engineer"], "block_companies": ["recruiters"]},
                         "sources": {"ats": {}, "boards": {}}})
    assert [j.company for j in out] == ["Acme Corp"]


def test_location_match():
    canada = Job(source="s", title="t", company="c", url="u", location="Vancouver, BC")
    us = Job(source="s", title="t", company="c", url="u", location="New York, NY")
    unknown = Job(source="s", title="t", company="c", url="u", location="")
    locs = ["Canada", "Vancouver", "Toronto"]
    assert runner._location_match(canada, locs)
    assert not runner._location_match(us, locs)
    assert runner._location_match(unknown, locs)        # unknown kept
    assert runner._location_match(us, [])               # no filter => keep all


def test_parse_date_variants():
    assert runner._parse_date("2026-06-20T12:00:00Z") is not None
    assert runner._parse_date("2026-06-20T12:00:00-04:00") is not None
    assert runner._parse_date("1718884800000") is not None   # epoch ms (lever)
    assert runner._parse_date("not a date") is None
    assert runner._parse_date("") is None


def test_is_recent():
    now = datetime.now(timezone.utc)
    fresh = Job(source="s", title="t", company="c", url="u",
                posted=now.isoformat())
    stale = Job(source="s", title="t", company="c", url="u",
                posted=(now - timedelta(days=40)).isoformat())
    undated = Job(source="s", title="t", company="c", url="u", posted="")
    assert runner._is_recent(fresh, 7)
    assert not runner._is_recent(stale, 7)
    assert runner._is_recent(undated, 7)        # unknown date kept
    assert runner._is_recent(stale, 0)          # 0 = no recency filter


def test_gather_applies_location_and_recency(monkeypatch):
    now = datetime.now(timezone.utc)
    jobs = [
        Job(source="s", title="Engineer A", company="c", url="a",
            location="Toronto, ON", posted=now.isoformat()),
        Job(source="s", title="Engineer B", company="c", url="b",
            location="Toronto, ON", posted=(now - timedelta(days=30)).isoformat()),  # stale
        Job(source="s", title="Engineer C", company="c", url="cc",
            location="New York", posted=now.isoformat()),                            # non-CA
    ]
    monkeypatch.setattr(runner.ats, "fetch_all", lambda c: list(jobs))
    monkeypatch.setattr(runner.boards, "fetch_all", lambda s, b: [])
    out = runner.gather({
        "search": {"keywords": ["engineer"], "locations": ["Canada", "Toronto"],
                   "max_age_days": 7},
        "sources": {"ats": {}, "boards": {}},
    })
    assert [j.title for j in out] == ["Engineer A"]
