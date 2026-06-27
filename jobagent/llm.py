"""One chat() interface over Claude (primary) and Gemini (fallback).

Both are BYOK from .env. Model names come from config so you can swap them without
touching code. Claude is the Anthropic SDK; Gemini is the fallback when Claude
errors (or its key is unset).
"""
import json
import random
import re
import time

from .config import env, load_config


class LLMError(RuntimeError):
    """No configured LLM provider could return a response. Message names each
    provider tried and what went wrong; `.attempts` holds (provider, reason) pairs."""

    def __init__(self, message, attempts=None):
        super().__init__(message)
        self.attempts = attempts or []


_anthropic_client = None
_gemini_client = None

# Backoff + request defaults; overridden by config.yaml `llm:` when present.
_DEFAULTS = {
    "max_retries": 5,
    "base_delay_seconds": 2,
    "max_delay_seconds": 60,
    "max_tokens": 4096,
}
_settings_cache = None

# Substrings that mark a rate-limit / transient error worth retrying.
_RETRYABLE_MARKERS = (
    "rate limit", "ratelimit", "resource exhausted", "quota", "429",
    "overloaded", "unavailable", "timeout", "timed out", "connection",
)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}   # 529 = Anthropic overloaded


def _settings() -> dict:
    """Retry/request tunables from config.yaml `llm:`, falling back to _DEFAULTS.

    Cached; tolerant of a missing/unreadable config so chat() stays robust.
    """
    global _settings_cache
    if _settings_cache is None:
        cfg_llm = {}
        try:
            cfg_llm = load_config().get("llm") or {}
        except Exception:
            pass
        _settings_cache = {**_DEFAULTS, **cfg_llm}
    return _settings_cache


def _anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import Anthropic
        # max_retries=0: our own _retry() is the single source of backoff.
        _anthropic_client = Anthropic(
            api_key=env("ANTHROPIC_API_KEY", required=True), max_retries=0
        )
    return _anthropic_client


def _gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=env("GEMINI_API_KEY", required=True))
    return _gemini_client


def _call_claude(system: str, user: str, models: dict) -> str:
    resp = _anthropic().messages.create(
        model=models["claude"],
        max_tokens=int(_settings()["max_tokens"]),
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _call_gemini(system: str, user: str, models: dict) -> str:
    resp = _gemini().models.generate_content(
        model=models["gemini"],
        contents=f"{system}\n\n{user}",
    )
    return resp.text or ""


def _status_code(e: Exception):
    """Best-effort HTTP status code from a provider exception."""
    for attr in ("status_code", "code"):
        val = getattr(e, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(e, "response", None)
    val = getattr(resp, "status_code", None)
    return val if isinstance(val, int) else None


def _is_retryable(e: Exception) -> bool:
    """True for rate-limit / transient errors that backoff might clear."""
    if _status_code(e) in _RETRYABLE_STATUS:
        return True
    msg = str(e).lower()
    return any(m in msg for m in _RETRYABLE_MARKERS)


def _retry_after(e: Exception):
    """Server-suggested delay (seconds) if the error carries one, else None."""
    # Anthropic / OpenAI-style: Retry-After header on the response.
    resp = getattr(e, "response", None)
    headers = getattr(resp, "headers", None)
    if headers:
        try:
            ra = headers.get("retry-after") or headers.get("Retry-After")
            if ra is not None:
                return float(ra)
        except (TypeError, ValueError):
            pass
    # Gemini: a retry_delay attribute (seconds), when present.
    ra = getattr(e, "retry_delay", None)
    secs = getattr(ra, "seconds", None)
    if isinstance(secs, (int, float)):
        return float(secs)
    return float(ra) if isinstance(ra, (int, float)) else None


def _retry(fn, label: str):
    """Run fn(), retrying retryable errors with exponential backoff + jitter.

    Non-retryable errors are raised immediately; exhausting attempts re-raises
    the last error (so chat() can fall through to the other provider).
    """
    s = _settings()
    attempts = max(1, int(s["max_retries"]))
    base, cap = float(s["base_delay_seconds"]), float(s["max_delay_seconds"])
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            if not _is_retryable(e) or attempt == attempts - 1:
                raise
            backoff = min(cap, base * (2 ** attempt))
            delay = max(backoff, _retry_after(e) or 0.0) + random.uniform(0, 1)
            print(f"[llm] {label} rate-limited ({e}); retry "
                  f"{attempt + 1}/{attempts - 1} in {delay:.1f}s")
            time.sleep(delay)


def _describe(e: Exception) -> str:
    """Turn a provider exception into a short, human reason."""
    low = str(e).lower()
    code = _status_code(e)
    if "missing required env var" in low:
        return "not configured (API key missing)"
    if code == 429 or any(k in low for k in
                          ("resource_exhausted", "quota", "rate limit", "rate_limit", "429")):
        return "rate limit or quota exhausted"
    if code in (401, 403) or any(k in low for k in
                                 ("authentication", "permission", "unauthorized", "api key not valid")) \
            or ("invalid" in low and "key" in low):
        return "invalid or unauthorized API key"
    if code in (500, 502, 503, 504, 529) or "overloaded" in low or "unavailable" in low:
        return "provider overloaded or unavailable — try again shortly"
    if "timeout" in low or "timed out" in low or "connection" in low:
        return "network/connection problem"
    s = str(e).strip().replace("\n", " ")
    return (s[:140] + "…") if len(s) > 140 else (s or e.__class__.__name__)


def chat(system: str, user: str, models: dict) -> str:
    """Return the model's text. Tries Claude first, then Gemini, each with backoff.
    If both fail (or aren't configured), raises LLMError naming what went wrong."""
    attempts = []
    try:
        return _retry(lambda: _call_claude(system, user, models), "Claude")
    except Exception as e:
        reason = _describe(e)
        attempts.append((f"Claude ({models.get('claude', '?')})", reason))
        print(f"[llm] Claude unavailable: {reason}; trying Gemini…")

    if env("GEMINI_API_KEY"):
        try:
            return _retry(lambda: _call_gemini(system, user, models), "Gemini")
        except Exception as e:
            reason = _describe(e)
            attempts.append((f"Gemini ({models.get('gemini', '?')})", reason))
            print(f"[llm] Gemini unavailable: {reason}")
    else:
        attempts.append(("Gemini", "not configured (no GEMINI_API_KEY)"))

    raise LLMError("No LLM could respond — "
                   + "; ".join(f"{p}: {r}" for p, r in attempts) + ".", attempts)


def extract_json(text: str) -> dict:
    """Robustly pull a JSON object out of a model response (handles ``` fences)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)
