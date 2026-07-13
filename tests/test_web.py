import base64

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("WEB_USERNAME", "admin")
    monkeypatch.setenv("WEB_PASSWORD", "secret")
    import jobagent.config as config
    import jobagent.web.app as webapp

    monkeypatch.setattr(webapp, "start_scheduler", lambda *a, **k: None)

    real_load = config.load_config

    def fake_load(path="config.yaml"):
        cfg = dict(real_load(path))
        cfg["paths"] = dict(cfg["paths"])
        cfg["paths"]["db"] = str(tmp_path / "t.db")
        cfg["paths"]["output"] = str(tmp_path / "out")
        cfg["schedule"] = {"enabled": False}
        return cfg

    monkeypatch.setattr(webapp, "load_config", fake_load)
    # isolate the per-session demo sandbox DBs into the tmp dir (default lives at .demo/)
    monkeypatch.setattr(webapp.demoer, "DEMO_DIR", tmp_path / "demo")
    from fastapi.testclient import TestClient
    return TestClient(webapp.app)


def _auth(u="admin", p="secret"):
    token = base64.b64encode(f"{u}:{p}".encode()).decode()
    return {"Authorization": "Basic " + token}


def test_requires_auth(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_login_page_public(client):
    r = client.get("/login")
    assert r.status_code == 200 and "View the demo" in r.text


def test_login_grants_cookie_session(client):
    r = client.post("/login", data={"username": "admin", "password": "secret"},
                    follow_redirects=False)
    assert r.status_code == 303 and "ja_session" in r.headers.get("set-cookie", "")
    # the cookie now authenticates without a Basic header
    assert client.get("/").status_code == 200


def test_login_bad_password_redirects_with_error(client):
    r = client.post("/login", data={"username": "admin", "password": "nope"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?error=1"


def test_dashboard_ok_with_auth(client):
    r = client.get("/", headers=_auth())
    assert r.status_code == 200 and "Dashboard" in r.text


def test_wrong_password_rejected(client):
    assert client.get("/", headers=_auth(p="nope")).status_code == 401


def test_download_path_traversal_blocked(client):
    r = client.get("/download", params={"path": "D:/Windows/System32/x"}, headers=_auth())
    assert r.status_code in (403, 404)


def test_tracker_page_renders(client):
    r = client.get("/tracker", headers=_auth())
    assert r.status_code == 200 and "Application tracker" in r.text


def test_manual_tracker_add_defaults_to_today_and_counts(client):
    import jobagent.web.app as webapp
    # "Today" per the app = the configured-timezone local day (here UTC, the fixture default).
    today = webapp._local_day_window(webapp.load_config())[2]
    r = client.post("/tracker/add", headers=_auth(),
                    data={"company": "Acme", "role": "SWE"},   # no applied_date
                    follow_redirects=False)
    assert r.status_code == 303
    s = webapp._store()
    try:
        row = next(a for a in s.list_applications() if a["company"] == "Acme")
        assert row["applied_date"] == today          # blank date filled with today
        assert s.today_stats(local_date=today)["applied"] >= 1   # shows in "applied today"
    finally:
        s.close()


def test_settings_page_renders(client):
    r = client.get("/settings", headers=_auth())
    assert r.status_code == 200 and "Search settings" in r.text
    # Timezone is a dropdown, with the configured zone present and preselected.
    assert '<select name="schedule_timezone">' in r.text
    assert 'America/Vancouver' in r.text


def test_insights_page_renders(client):
    r = client.get("/insights", headers=_auth())
    assert r.status_code == 200 and "Applications over time" in r.text and "By stage" in r.text


def test_dashboard_is_agent_home(client):
    r = client.get("/", headers=_auth())
    assert r.status_code == 200 and "Ready to apply" in r.text and "Recent runs" in r.text


def test_apply_records_and_opens_posting(client):
    import jobagent.web.app as webapp
    from jobagent.models import Job
    s = webapp._store()
    j = Job(source="s", title="X Role", company="C", url="http://posting")
    s.upsert_job(j)
    s.record_docs(j.job_id, ["/o/r.docx"])
    s.close()
    r = client.post(f"/jobs/{j.job_id}/apply", headers=_auth(), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "http://posting"
    s = webapp._store()
    assert s.get(j.job_id)["status"] == "applied"
    logged = [a for a in s.list_applications() if a["company"] == "C"]
    assert logged and logged[0]["source"] == "jobpilot"   # tagged so it isn't double-counted
    s.close()


def test_jobs_filters_render(client):
    r = client.get("/jobs?min_score=70&sort=date&dir=asc", headers=_auth())
    assert r.status_code == 200


def test_jobs_remove_dismisses(client):
    import jobagent.web.app as webapp
    from jobagent.models import Job
    s = webapp._store()
    j = Job(source="s", title="Unwanted Role", company="c", url="u-rm")
    s.upsert_job(j)
    s.set_status(j.job_id, "sent")
    s.close()
    assert "Unwanted Role" in client.get("/jobs", headers=_auth()).text
    client.post("/jobs/remove", data={"job_ids": [j.job_id]}, headers=_auth())
    assert "Unwanted Role" not in client.get("/jobs", headers=_auth()).text


# ---- demo mode -------------------------------------------------------------
def test_demo_seeds_and_is_isolated_from_real_db(client):
    r = client.post("/demo", follow_redirects=False)
    assert r.status_code == 303 and "ja_session" in r.headers.get("set-cookie", "")
    # demo cookie now authenticates; the board shows the 3 seeded jobs + the demo badge
    assert "DEMO MODE" in client.get("/").text            # badge in the sidebar
    assert "Stripe" in client.get("/jobs").text           # seeded board job
    # the real DB is untouched (no demo jobs leaked into it)
    import jobagent.web.app as webapp
    s = webapp._store()
    assert not any(j["company"] == "Stripe" for j in s.by_status("sent"))
    s.close()


def test_demo_scan_adds_two_then_notices(client):
    from urllib.parse import unquote
    client.post("/demo")
    assert "Figma" not in client.get("/").text            # not added yet
    # first run adds 2 matches + prepares docs (no live calls)
    r1 = client.post("/agent/run", follow_redirects=False)
    assert r1.status_code == 303 and "Demo run complete" in unquote(r1.headers["location"])
    # the two new matches show up — Figma got docs (Ready to apply), 1Password on the board
    assert "Figma" in client.get("/").text
    assert "1Password" in client.get("/jobs").text
    # second run just tells the user it's a demo (no new work)
    r2 = client.post("/agent/run", follow_redirects=False)
    assert "simulation" in unquote(r2.headers["location"])


def test_demo_sessions_are_isolated(client):
    """One visitor wrecking their sandbox must not affect another's."""
    import jobagent.web.app as webapp
    from fastapi.testclient import TestClient
    other = TestClient(webapp.app)
    client.post("/demo")
    other.post("/demo")
    # visitor A dismisses a seeded job from their own board
    client.post("/jobs/demo-1/dismiss", follow_redirects=False)
    assert "Stripe" not in client.get("/jobs").text          # gone for A
    assert "Stripe" in other.get("/jobs").text               # still there for B


def test_demo_settings_are_read_only(client, monkeypatch):
    import jobagent.web.app as webapp
    called = {"n": 0}
    monkeypatch.setattr(webapp.settings_io, "write", lambda *a, **k: called.__setitem__("n", 1))
    client.post("/demo")
    r = client.post("/settings", data={"keywords": "x"}, follow_redirects=False)
    assert r.status_code == 303 and called["n"] == 0      # never wrote real config
