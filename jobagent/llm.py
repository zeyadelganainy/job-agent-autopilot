"""One chat() interface over Claude (primary) and a free fallback provider.

Both are BYOK from .env. Model names come from config so you can swap them without
touching code. Claude is the Anthropic SDK; the fallback is any OpenAI-compatible REST
endpoint (default: OpenRouter) used when Claude errors or its key is unset. Point
FALLBACK_BASE_URL at Groq / Cerebras / etc. to switch providers without code changes.
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

# Free fallback provider — any OpenAI-compatible endpoint. Default: OpenRouter (free
# `:free` models, no card). Override the host via FALLBACK_BASE_URL to use Groq, Cerebras, etc.
_FALLBACK_BASE_URL = "https://openrouter.ai/api/v1"

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

# Substrings marking a "this model id is gone" error (renamed/deprecated/decommissioned),
# so _call_fallback can try the next configured model instead of giving up. Kept narrow so
# a transient "unavailable"/overload (retryable) is never mistaken for a dead model.
_MODEL_GONE_MARKERS = (
    "model not found", "model_not_found", "does not exist", "no such model",
    "unknown model", "invalid model", "decommissioned", "deprecated",
)


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


def _call_claude(system: str, user: str, models: dict) -> str:
    resp = _anthropic().messages.create(
        model=models["claude"],
        max_tokens=int(_settings()["max_tokens"]),
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _fallback_models(models: dict) -> list:
    """Fallback model ids to try in order. `models['fallback']` may be a single id, a
    comma-separated string ('gpt-oss-120b, zai-glm-4.7'), or a YAML list — so a dead or
    renamed model id falls through to the next without a code change."""
    raw = models.get("fallback") or ""
    ids = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    return [s for s in (str(m).strip() for m in ids) if s]


def _call_fallback(system: str, user: str, models: dict) -> str:
    import requests
    base = (env("FALLBACK_BASE_URL") or _FALLBACK_BASE_URL).rstrip("/")
    key = env("FALLBACK_API_KEY", required=True)
    model_ids = _fallback_models(models)
    if not model_ids:
        raise RuntimeError("No fallback model configured (set models.fallback).")

    last_exc = None
    for model in model_ids:
        try:
            resp = requests.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={
                    "model": model,
                    "max_tokens": int(_settings()["max_tokens"]),
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=120,
            )
            resp.raise_for_status()   # HTTPError carries .response (status+headers) for _retry
            return (resp.json()["choices"][0]["message"]["content"]) or ""
        except Exception as e:
            # Advance to the next model when this one is gone (404) OR transiently failing
            # (rate limit / overload / network) — free pools like OpenRouter's routinely 429
            # a busy model while another is up. A hard error (bad key, 400) stops us instead;
            # the outer _retry then backs off and re-runs the whole list if all were transient.
            if not (_is_model_gone(e) or _is_retryable(e)):
                raise
            print(f"[llm] fallback model '{model}' unavailable ({_describe(e)}); trying next…")
            last_exc = e
    raise last_exc   # every configured fallback model was unavailable


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


def _is_model_gone(e: Exception) -> bool:
    """True when the error means the requested model id is unavailable (404, or a
    'no such model' message) — a signal to try the next fallback model, not to retry."""
    if _status_code(e) == 404:
        return True
    msg = str(e).lower()
    return "model" in msg and any(m in msg for m in _MODEL_GONE_MARKERS)


def _retry_after(e: Exception):
    """Server-suggested delay (seconds) if the error carries one, else None."""
    # Anthropic / OpenAI-style: Retry-After header on the response (Claude + fallback).
    resp = getattr(e, "response", None)
    headers = getattr(resp, "headers", None)
    if headers:
        try:
            ra = headers.get("retry-after") or headers.get("Retry-After")
            if ra is not None:
                return float(ra)
        except (TypeError, ValueError):
            pass
    return None


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
    """Return the model's text. Tries Claude first, then the fallback, each with backoff.
    If both fail (or aren't configured), raises LLMError naming what went wrong."""
    attempts = []
    try:
        return _retry(lambda: _call_claude(system, user, models), "Claude")
    except Exception as e:
        reason = _describe(e)
        attempts.append((f"Claude ({models.get('claude', '?')})", reason))
        print(f"[llm] Claude unavailable: {reason}; trying fallback…")

    if env("FALLBACK_API_KEY"):
        try:
            return _retry(lambda: _call_fallback(system, user, models), "fallback")
        except Exception as e:
            reason = _describe(e)
            attempts.append((f"Fallback ({models.get('fallback', '?')})", reason))
            print(f"[llm] Fallback unavailable: {reason}")
    else:
        attempts.append(("Fallback", "not configured (no FALLBACK_API_KEY)"))

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
