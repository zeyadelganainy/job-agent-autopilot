# job-agent — project memory

A free, self-hosted, BYOK job-application assistant. Single-user, runs on the
owner's machine. See README.md for setup; this file is the behavioral contract.

## The loop (do not break this shape)
scan → score → Telegram digest → user replies `/pick <ids>` → generate tailored
resume + cover letter → user applies MANUALLY.

v1.1 adds a **web UI** (FastAPI) and **scheduled daily scans** as *additional* surfaces over
the same pipeline — same loop, same human-in-the-loop, no auto-apply. The web UI can also
generate docs for an **ad-hoc JD** (pasted text or ATS URL) and shows a **view-only** imported
application tracker.

## Hard rules
- **Never add auto-apply / auto-submit.** The human stays in the loop for the final
  application. This is a deliberate safety + account-ban decision, not an oversight.
- **ATS feeds (Greenhouse/Lever/Ashby) are the primary source** — public JSON, no
  scraping, no ToS issues. Lean on these.
- **Job boards via JobSpy are ToS-grey and can get the user IP-blocked.** They're
  off by default in config.yaml. Do not enable, expand, or add new scrapers without
  explicitly flagging the tradeoff to the user first.
- **BYOK only.** Keys live in `.env` (gitignored). Never hardcode a key anywhere.
- **Model names come from `config.yaml` `models:`.** Never hardcode a model string in
  code — free-tier model names get deprecated often.
- All LLM calls go through `jobagent/llm.py:chat()`. Don't call the Anthropic/Gemini
  SDKs directly from other modules.

## Architecture
- `run_scan.py` — CLI entry: ingest → score → push digest to Telegram (cron-friendly).
- `bot.py` — long-running Telegram bot: `/scan` `/list` `/pick` `/skip`.
- `jobagent/ingest/` — `ats.py` (Greenhouse/Lever/Ashby), `boards.py` (JobSpy),
  `runner.py` (gather + keyword/location/recency filter + dedupe).
- `jobagent/score.py` — LLM scores a job vs profile, returns JSON {score, reasons, gaps}.
- `jobagent/generate.py` — cover letter + tailored resume in the user's voice. Pulls
  content from `profile/master.md` (source of truth); resume comes back as structured
  JSON and is rendered into a `resume.docx` that matches the user's own
  `profile/resume.docx` template (fonts, margins, two-column rows). Uses writing samples
  in `profile/samples/` as voice exemplars for the cover letter.
- `jobagent/store.py` — SQLite state. Job status flow: new → scored → sent → picked →
  generated (or skipped); stable `job_id` (sha1 of url). Also a **view-only `applications`
  table** for the imported tracker. WAL + per-request connections so the web app is safe.
- `jobagent/llm.py` — Claude (Anthropic) primary, Gemini fallback, both BYOK. Falls
  back to Gemini when Claude errors or `ANTHROPIC_API_KEY` is unset.
- `jobagent/pipeline.py` — ties scan / digest / pick-and-generate together;
  `generate_for_jd(text|url)` powers ad-hoc generation (uses `ats.fetch_job` for ATS URLs).
- `run_web.py` + `jobagent/web/` — FastAPI web UI (v1.1): dashboard, scan/pick, ad-hoc
  generate, docs library + guarded downloads, CSV tracker import. HTTP Basic auth
  (`WEB_USERNAME`/`WEB_PASSWORD`); Swagger disabled so `/docs` is the document library.
- `jobagent/scheduler.py` — APScheduler daily scan (config `schedule:`) → digest via `notify`.
- `jobagent/tracker.py` — CSV (Google Sheets export) → upsert into the `applications` table.
- `config.yaml` — search keywords/locations, ATS company tokens, sources toggle, scoring
  threshold, model names, `web:`/`schedule:`. `profile/profile.yaml` — the user's structured CV.

## Conventions
- Python 3.10+. Keep dependencies to what's in requirements.txt.
- Bound LLM prompts (descriptions sliced to ~6000 chars) to stay inside free-tier limits.
- Parse model JSON via `llm.extract_json` (handles code fences) — model output isn't trusted.
- Don't commit: `.env`, `output/`, `*.db`, `profile/profile.yaml`, `profile/samples/*`.
- Tests live in `tests/` (pytest, hermetic — stub network/LLM/Telegram, never call them).
  Add tests for new logic; run `pytest`. Dev deps are in `requirements-dev.txt`.

## Known TODOs (backlog, not done)
- (none open)

## Done
- Rate-limit retry/backoff in `llm.py:chat()` (exponential backoff + jitter on 429s /
  transient errors, per provider, fallback intact) + a fixed inter-pick delay in
  `pipeline.pick_and_generate`. Tunables in `config.yaml` `llm:`.
- `resume.docx` now renders from structured JSON into the user's own template
  (`profile/resume.docx`) instead of plain styling. Content sourced from `profile/master.md`.
- LLM provider switch: Claude (Anthropic) primary, Gemini fallback (both BYOK).
- Scan scoring cap (`config.yaml` `scoring.max_to_score`) so free tiers aren't overrun;
  unscored matches roll over to the next scan.
- Telegram digest: numbered list (pick by `1 2 3`, not ids), apply links, HTML formatting.
- Tests: hermetic `pytest` suite under `tests/` (no network/LLM/Telegram). Run with
  `pip install -r requirements-dev.txt && pytest`.
- v1.1 web UI (`run_web.py`, `jobagent/web/`): FastAPI dashboard for scan/pick, ad-hoc
  generation from a pasted JD or ATS URL, docs library, view-only CSV tracker import, and an
  embedded daily-scan scheduler. Password-protected (`WEB_USERNAME`/`WEB_PASSWORD` in `.env`).