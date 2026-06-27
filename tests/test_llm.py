import pytest

import jobagent.llm as llm

_FAST = {"max_retries": 3, "base_delay_seconds": 0, "max_delay_seconds": 0, "max_tokens": 64}


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


@pytest.fixture(autouse=True)
def _fast_settings(monkeypatch):
    monkeypatch.setattr(llm, "_settings", lambda: dict(_FAST))
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


# ---- extract_json ----
def test_extract_json_plain():
    assert llm.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_code_fenced():
    assert llm.extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_surrounding_prose():
    assert llm.extract_json('Sure: {"a": 1} done') == {"a": 1}


# ---- retry classification ----
def test_status_code_from_attr_and_response():
    e = Exception(); e.status_code = 429
    assert llm._status_code(e) == 429

    class Resp:
        status_code = 503
    e2 = Exception(); e2.response = Resp()
    assert llm._status_code(e2) == 503


def test_is_retryable():
    e529 = Exception(); e529.status_code = 529
    assert llm._is_retryable(e529)                       # Anthropic overloaded
    assert llm._is_retryable(Exception("503 UNAVAILABLE"))
    assert llm._is_retryable(Exception("RESOURCE_EXHAUSTED quota"))
    assert not llm._is_retryable(Exception("invalid api key"))
    e400 = Exception(); e400.status_code = 400
    assert not llm._is_retryable(e400)


def test_retry_after_reads_header():
    class Resp:
        headers = {"retry-after": "7"}
    e = Exception(); e.response = Resp()
    assert llm._retry_after(e) == 7.0


# ---- _retry ----
def test_retry_recovers_after_retryable():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise Exception("503 unavailable")
        return "ok"

    assert llm._retry(fn, "X") == "ok"
    assert calls["n"] == 2


def test_retry_reraises_nonretryable_immediately():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ValueError("bad request 400")

    with pytest.raises(ValueError):
        llm._retry(fn, "X")
    assert calls["n"] == 1


def test_retry_exhausts_then_raises():
    with pytest.raises(Exception):
        llm._retry(_raise(Exception("503 unavailable")), "X")


# ---- chat routing ----
def test_chat_uses_claude_first(monkeypatch):
    monkeypatch.setattr(llm, "_call_claude", lambda s, u, m: "from claude")
    monkeypatch.setattr(llm, "_call_gemini",
                        _raise(AssertionError("gemini should not be called")))
    assert llm.chat("s", "u", {"claude": "c", "gemini": "g"}) == "from claude"


def test_chat_falls_back_to_gemini(monkeypatch):
    monkeypatch.setattr(llm, "_call_claude",
                        _raise(RuntimeError("Missing required env var: ANTHROPIC_API_KEY")))
    monkeypatch.setattr(llm, "_call_gemini", lambda s, u, m: "from gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert llm.chat("s", "u", {"claude": "c", "gemini": "g"}) == "from gemini"


def test_chat_reraises_when_no_gemini_key(monkeypatch):
    monkeypatch.setattr(llm, "_call_claude", _raise(RuntimeError("boom")))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        llm.chat("s", "u", {"claude": "c", "gemini": "g"})


def _exc(code=None, msg="boom"):
    e = Exception(msg)
    if code:
        e.status_code = code
    return e


def test_describe_classifies():
    assert "quota" in llm._describe(_exc(429))
    inv = llm._describe(_exc(401))
    assert "invalid" in inv or "unauthorized" in inv
    assert "overloaded" in llm._describe(_exc(503))
    assert "not configured" in llm._describe(
        RuntimeError("Missing required env var: ANTHROPIC_API_KEY"))


def test_chat_all_fail_raises_named_llmerror(monkeypatch):
    monkeypatch.setattr(llm, "_call_claude", _raise(_exc(429)))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(llm.LLMError) as ei:
        llm.chat("s", "u", {"claude": "claude-opus-4-8", "gemini": "gemini-2.5-flash"})
    msg = str(ei.value)
    assert "Claude (claude-opus-4-8)" in msg and "quota" in msg
    assert "Gemini" in msg and "not configured" in msg
