# job-agent-autopilot — project memory

A free, self-hosted, BYOK **autonomous job-application prep agent** (V2). Forked from
job-agent v1.2. Single-user; designed to run always-on on a small cloud VM. See README.md
for setup/deploy; this file is the behavioral contract.

## The loop (do not break this shape)
scan → score → **agent auto-selects the best matches and auto-generates** a tailored resume +
cover letter → **email digest** + web monitoring console → **user reviews and APPLIES manually**.

The agent is autonomous up to *preparing* documents. The human always performs the final
application. A scheduled daily run does the whole cycle; "Run agent now" triggers it on demand.

## Hard rules
- **Never add auto-apply / auto-submit.** The human stays in the loop for the final
  application. The "Apply" button only *records* that the user applied (and opens the posting);
  it never submits. This is a deliberate safety + account-ban decision.
- **ATS feeds (Greenhouse/Lever/Ashby) are the primary source** — public JSON, no scraping.
- **Job boards via JobSpy are ToS-grey and can get the user IP-blocked.** Don't enable/expand
  scrapers without flagging the tradeoff first.
- **BYOK only.** Keys + SMTP creds live in `.env` (gitignored). Never hardcode a secret.
  The repo is **public** — never commit `.env` or `profile/` (personal data); they reach the
  VM via `deploy/sync-secrets.sh` (scp), not git.
- **Model names come from `config.yaml` `models:`.** Never hardcode a model string.
- All LLM calls go through `jobagent/llm.py:chat()`. Don't call provider SDKs directly elsewhere.
- **Autonomy needs a release valve:** anything the agent can't finish (LLM quota/API error, or a
  manual external portal) is flagged into the **triage queue** (`status='needs_attention'` +
  `flag_reason`), never silently dropped.

## Architecture
- `run_agent.py` — CLI entry: one autonomous `agent_run` + email (cron-friendly alternative).
- `run_web.py` + `jobagent/web/` — FastAPI monitoring console: agent dashboard (today's stats,
  Ready-to-apply, triage, run history), manual jobs/generate/docs/tracker/insights/settings.
  HTTP Basic auth (`WEB_USERNAME`/`WEB_PASSWORD`); Swagger disabled so `/docs` is the doc library.
- `jobagent/pipeline.py` — `scan()` (fills optional `stats`), `agent_run()` (the autonomous
  cycle: scan → select `score>=agent.min_score`, cap `agent.daily_cap` → `pick_and_generate`,
  flagging triage), `needs_manual_apply()` (external-portal heuristic), `format_email()`,
  `generate_for_jd(text|url)` (ad-hoc), `pick_and_generate`.
- `jobagent/store.py` — SQLite. Job status flow: new → scored → sent → generated → applied
  (branch: needs_attention / skipped). Columns incl. `applied_at`, `flag_reason`. `agent_runs`
  table for run history; `applications` table = editable tracker. WAL + per-request connections.
- `jobagent/notify.py` — **email only** (`send_email` via SMTP, BYOK `SMTP_*`); no-op if unset.
- `jobagent/score.py` — LLM scores a job vs profile → JSON {score, reasons, gaps}; re-raises
  `LLMError` so a run surfaces a clear provider-named message.
- `jobagent/generate.py` — tailored resume (structured JSON → user's `profile/resume.docx`
  template) + cover letter in the user's voice (`profile/samples/`), from `profile/master.md`.
- `jobagent/llm.py` — Claude primary, free fallback via any OpenAI-compatible REST endpoint
  (default OpenRouter; set `FALLBACK_API_KEY`/`FALLBACK_BASE_URL`); `LLMError` names which provider
  failed and why. `jobagent/scheduler.py` — APScheduler daily `agent_run` → email.
- `jobagent/ingest/` — `ats.py`, `boards.py`, `runner.py` (gather + filter + blocklist + dedupe).
- `deploy/` — Oracle Cloud Always Free: `install.sh`, `jobagent.service` (systemd), `Caddyfile`
  (DuckDNS + auto-HTTPS), `sync-secrets.sh` (scp `.env`+`profile/`).
- `config.yaml` — `search` (+ `block_companies`), `sources`, `scoring`, **`agent`**
  (enabled/min_score/daily_cap), `models`, `llm`, `web`, `schedule`.

## Conventions
- Python 3.10+. Keep deps to requirements.txt (email uses stdlib `smtplib` — no new dep).
- Parse model JSON via `llm.extract_json` — model output isn't trusted.
- Don't commit: `.env`, `output/`, `*.db*`, `profile/*`, `.claude/`.
- Tests in `tests/` (pytest, hermetic — stub network/LLM/SMTP). Add tests for new logic; `pytest`.

## Done (V2)
- Autonomous `agent_run` (auto-select + auto-generate, caps via `agent.min_score`/`daily_cap`).
- Triage queue (LLMError + external-portal flagging) with Retry/Apply/Dismiss.
- Email-only digest (`notify.send_email` + `pipeline.format_email`); Telegram removed.
- Web console: agent dashboard, Apply (records + opens posting), Insights agent-activity chart.
- Oracle Cloud Always Free deploy assets under `deploy/`.
- Auth: `/login` page (signed session cookie; HTTP Basic still accepted for scripts/tests),
  `/logout`. Cookie signed via stdlib HMAC with `SESSION_SECRET` (falls back to `WEB_PASSWORD`).
- **Demo mode** (`jobagent/web/demo.py`): "View the demo" on /login opens a no-live-calls
  sandbox — its own seeded `demo.db` + premade `.docx` under `output/demo`. Routes that would
  make live calls (agent run, pick/generate, settings write) are intercepted and *simulated*:
  first "Run agent now" adds 2 matches + prepares docs; pressing it again returns a demo notice.
  Reseeded fresh on each demo entry. Never touches the real `jobs.db` or `config.yaml`.

## Known TODOs (backlog)
- Response/interview-rate analytics; time-to-response; per-company outcomes.
