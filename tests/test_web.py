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
    from fastapi.testclient import TestClient
    return TestClient(webapp.app)


def _auth(u="admin", p="secret"):
    token = base64.b64encode(f"{u}:{p}".encode()).decode()
    return {"Authorization": "Basic " + token}


def test_requires_auth(client):
    assert client.get("/").status_code == 401


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


def test_settings_page_renders(client):
    r = client.get("/settings", headers=_auth())
    assert r.status_code == 200 and "Search settings" in r.text


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
    assert any(a["company"] == "C" for a in s.list_applications())   # logged to tracker
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
