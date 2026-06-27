"""Shared fixtures. Tests are hermetic: no network, LLM, or Telegram calls."""
import pytest


@pytest.fixture
def cfg(tmp_path):
    """A minimal config dict pointing the DB/output at a temp dir."""
    return {
        "paths": {
            "db": str(tmp_path / "t.db"),
            "output": str(tmp_path / "out"),
            "profile": "profile/profile.yaml",
            "master": "profile/master.md",
            "template": "profile/resume.docx",
            "samples": "profile/samples",
        },
        "models": {"claude": "claude-x", "gemini": "gemini-x"},
        "scoring": {"threshold": 60, "digest_size": 10, "max_to_score": 25},
        "llm": {"max_retries": 3, "base_delay_seconds": 0, "max_delay_seconds": 0,
                "max_tokens": 256, "gen_delay_seconds": 0},
        "search": {"keywords": ["engineer"], "locations": ["Remote"]},
        "sources": {"ats": {}, "boards": {"enabled": False}},
    }
