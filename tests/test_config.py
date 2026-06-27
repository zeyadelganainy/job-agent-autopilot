import pytest

from jobagent import config


def test_load_master_missing_returns_empty():
    assert config.load_master({"paths": {"master": "does_not_exist.md"}}) == ""


def test_env_required_raises_when_absent(monkeypatch):
    monkeypatch.delenv("NOPE_KEY_XYZ", raising=False)
    with pytest.raises(RuntimeError):
        config.env("NOPE_KEY_XYZ", required=True)


def test_env_optional_returns_none(monkeypatch):
    monkeypatch.delenv("NOPE_KEY_XYZ", raising=False)
    assert config.env("NOPE_KEY_XYZ") is None
