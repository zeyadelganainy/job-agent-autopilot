from jobagent import settings_io


def test_read_has_expected_keys():
    s = settings_io.read()
    for k in ("keywords", "locations", "threshold", "claude", "gemini",
              "schedule_time", "greenhouse"):
        assert k in s


def test_write_roundtrip_and_preserves_comments(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        "# my config\nsearch:\n  keywords:\n    - a   # kw comment\n  locations: []\n"
        "scoring:\n  threshold: 60\n", encoding="utf-8")
    monkeypatch.setattr(settings_io, "PATH", p)

    settings_io.write({
        "keywords": ["x", "y"], "locations": ["Toronto"],
        "block_companies": ["Bad Recruiters"], "remote_ok": True,
        "max_age_days": 7, "greenhouse": ["d2l"], "lever": [], "ashby": [],
        "boards_enabled": False, "threshold": 50, "digest_size": 10,
        "max_to_score": 25, "claude": "claude-x", "gemini": "gemini-x",
        "schedule_enabled": True, "schedule_time": "09:00",
        "schedule_timezone": "America/Vancouver",
    })
    out = settings_io.read()
    assert out["keywords"] == ["x", "y"] and out["threshold"] == 50
    assert out["claude"] == "claude-x" and out["schedule_time"] == "09:00"
    assert out["greenhouse"] == ["d2l"] and out["remote_ok"] is True
    assert out["block_companies"] == ["Bad Recruiters"]
    assert "# my config" in p.read_text(encoding="utf-8")   # comments survived
