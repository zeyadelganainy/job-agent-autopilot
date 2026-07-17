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
    monkeypatch.setattr(llm, "_call_fallback",
                        _raise(AssertionError("fallback should not be called")))
    assert llm.chat("s", "u", {"claude": "c", "fallback": "f"}) == "from claude"


def test_chat_falls_back_to_fallback(monkeypatch):
    monkeypatch.setattr(llm, "_call_claude",
                        _raise(RuntimeError("Missing required env var: ANTHROPIC_API_KEY")))
    monkeypatch.setattr(llm, "_call_fallback", lambda s, u, m: "from fallback")
    monkeypatch.setenv("FALLBACK_API_KEY", "x")
    assert llm.chat("s", "u", {"claude": "c", "fallback": "f"}) == "from fallback"


def test_chat_reraises_when_no_fallback_key(monkeypatch):
    monkeypatch.setattr(llm, "_call_claude", _raise(RuntimeError("boom")))
    monkeypatch.delenv("FALLBACK_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        llm.chat("s", "u", {"claude": "c", "fallback": "f"})


# ---- _call_fallback: OpenAI-compatible request shape + response parsing ----
def test_call_fallback_builds_request_and_parses(monkeypatch):
    import requests
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "hi from fallback"}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return _Resp()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setenv("FALLBACK_API_KEY", "sk-test")
    monkeypatch.delenv("FALLBACK_BASE_URL", raising=False)

    out = llm._call_fallback("sys", "usr", {"fallback": "gpt-oss-120b"})

    assert out == "hi from fallback"
    assert captured["url"] == "https://api.cerebras.ai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"]["model"] == "gpt-oss-120b"
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]


def test_call_fallback_honors_base_url_override(monkeypatch):
    import requests
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(requests, "post",
                        lambda url, **k: captured.update(url=url) or _Resp())
    monkeypatch.setenv("FALLBACK_API_KEY", "sk-test")
    monkeypatch.setenv("FALLBACK_BASE_URL", "https://api.groq.com/openai/v1/")

    llm._call_fallback("s", "u", {"fallback": "llama-3.3-70b"})
    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"


# ---- _call_fallback: model fallthrough ----
def _fake_resp(content=None, status=200, message=""):
    """Fake requests.Response: 200 with content, or raise_for_status() -> HTTPError(status)."""
    import requests

    class _Resp:
        status_code = status

        def raise_for_status(self):
            if status >= 400:
                e = requests.HTTPError(message or f"HTTP {status}")
                e.response = type("R", (), {"status_code": status, "headers": {}})()
                raise e

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    return _Resp()


def test_fallback_models_parses_string_and_list():
    assert llm._fallback_models({"fallback": "a, b ,c"}) == ["a", "b", "c"]
    assert llm._fallback_models({"fallback": ["x", " y "]}) == ["x", "y"]
    assert llm._fallback_models({"fallback": "solo"}) == ["solo"]
    assert llm._fallback_models({"fallback": ""}) == []


def test_fallback_falls_through_dead_model_to_next(monkeypatch):
    import requests
    seen = []

    def fake_post(url, headers=None, json=None, timeout=None):
        model = json["model"]
        seen.append(model)
        if model == "dead-model":
            return _fake_resp(status=404, message="model dead-model does not exist")
        return _fake_resp(content="ok from " + model)

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setenv("FALLBACK_API_KEY", "sk")
    monkeypatch.delenv("FALLBACK_BASE_URL", raising=False)

    out = llm._call_fallback("s", "u", {"fallback": "dead-model, good-model"})
    assert out == "ok from good-model"
    assert seen == ["dead-model", "good-model"]   # tried in order, stopped at first success


def test_fallback_does_not_fall_through_on_rate_limit(monkeypatch):
    import requests
    seen = []

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.append(json["model"])
        return _fake_resp(status=429, message="rate limit exceeded")

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setenv("FALLBACK_API_KEY", "sk")

    with pytest.raises(Exception):
        llm._call_fallback("s", "u", {"fallback": "m1, m2"})
    assert seen == ["m1"]   # a rate limit is not a model problem — no fallthrough


def test_fallback_raises_when_all_models_gone(monkeypatch):
    import requests

    monkeypatch.setattr(requests, "post",
                        lambda url, **k: _fake_resp(status=404, message="no such model"))
    monkeypatch.setenv("FALLBACK_API_KEY", "sk")

    with pytest.raises(Exception):
        llm._call_fallback("s", "u", {"fallback": "a, b, c"})


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
    monkeypatch.delenv("FALLBACK_API_KEY", raising=False)
    with pytest.raises(llm.LLMError) as ei:
        llm.chat("s", "u", {"claude": "claude-opus-4-8", "fallback": "gpt-oss-120b"})
    msg = str(ei.value)
    assert "Claude (claude-opus-4-8)" in msg and "quota" in msg
    assert "Fallback" in msg and "not configured" in msg
