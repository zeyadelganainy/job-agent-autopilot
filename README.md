# job-agent-autopilot

**An autonomous job-application prep agent — with a human at the apply button.**
On a schedule (or on demand) it scans company job feeds, scores each role against *your*
profile with an LLM, **auto-selects the best matches, and auto-generates a tailored résumé +
cover letter** for each — then emails you a digest. You review in a web console and apply
yourself. It never submits an application for you.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/zeyadelganainy/job-agent-autopilot/actions/workflows/ci.yml/badge.svg)](https://github.com/zeyadelganainy/job-agent-autopilot/actions/workflows/ci.yml)

```
scan ─► score ─► auto-pick best ─► auto-generate docs ─► email digest + console ─► you apply
```

Built to run **always-on for free** on a small cloud VM, so the daily run happens whether or
not your laptop is on. Your résumé/profile and API keys stay in your own deployment.

> V2 of [job-agent](https://github.com/zeyadelganainy/job-agent) (which is human-driven:
> Telegram digest → you `/pick` → it generates). This repo is the autonomous, email-only,
> self-hosted evolution.

---

## What it does

- 🔎 **Finds roles** from company ATS feeds (Greenhouse / Lever / Ashby) — public JSON, no scraping.
- 🧠 **Scores** each role 0–100 against your profile with an LLM (reasons + gaps).
- 🤖 **Prepares automatically** — for matches at/above your `min_score` (up to a daily cap), it
  writes a tailored résumé + cover letter into *your own* `.docx` template, in *your* voice.
- 🛟 **Flags what it can't finish** — an LLM quota/API error, or a posting behind a manual portal
  (Workday/Taleo/iCIMS), lands in a **triage queue** for you, never silently dropped.
- 📧 **Emails you a digest** each run (what's ready to apply, what needs attention).
- 🖥️ **Monitoring console** — today's stats, a Ready-to-apply queue, triage, run history, an
  editable application tracker, and analytics.
- ✅ **You apply** — the Apply button records the application and opens the posting; it never submits.

## Engineering highlights

- **Autonomous, but safe by design** — auto-prepares; the human always submits. The "Apply"
  action only records + opens the posting.
- **Triage / release valve** — failures (quota/API) and manual-portal jobs are flagged with a
  reason and a Retry/Apply/Dismiss action.
- **Resilient LLM layer** — Claude primary, Gemini fallback (BYOK), exponential-backoff retry,
  and clear provider-named error messages.
- **Template-faithful generation** — fills your real résumé `.docx` (fonts, margins, two-column
  layout, clickable links) from a single source-of-truth file; drops any link the model invents.
- **No build step** — FastAPI + Jinja + a little vanilla JS / Chart.js; SQLite for state.
- **Always-on for $0** — deploy assets for an Oracle Cloud Always Free VM (systemd + Caddy HTTPS).
- **Config-driven & tested** — everything in `config.yaml`; hermetic `pytest` suite in CI.

---

## Setup

### 1. What you need
- **Python 3.10+**
- At least one **LLM API key**: [Gemini](https://aistudio.google.com/apikey) (free tier) and/or
  [Claude](https://console.anthropic.com/settings/keys) (paid, higher quality).
- An **SMTP mailbox** for the digest (e.g. Gmail with an App Password).

### 2. Install
```bash
pip install -r requirements.txt
```

### 3. Secrets — copy `.env.example` to `.env` (gitignored) and fill in
```ini
ANTHROPIC_API_KEY=        # leave blank to run free on Gemini
GEMINI_API_KEY=your_gemini_key
WEB_USERNAME=admin
WEB_PASSWORD=choose-a-strong-password
# Email digest (Gmail: smtp.gmail.com / 587 / App Password)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=your_app_password
EMAIL_FROM=you@gmail.com
EMAIL_TO=you@gmail.com
APP_URL=                  # your dashboard URL, used in the email link
```

### 4. Your profile (`profile/`, gitignored — personal data)
| File | Used for | What to put in it |
|------|----------|-------------------|
| `profile/profile.yaml` | scoring every role | a compact, structured CV (sent on every score call) |
| `profile/master.md` | generating documents | your full "source of truth" — every role, bullet, metric |
| `profile/samples/` | the cover-letter voice | 1–3 past cover letters or a bio (`.txt`/`.md`) |
| `profile/resume.docx` | the résumé's look | your real résumé; output reuses its fonts/margins/layout |

### 5. Targets + autonomy (`config.yaml`)
Set `search.keywords` / `locations`, your ATS company tokens under `sources.ats`, then the
**agent** knobs:
```yaml
agent:
  enabled: true     # scheduled runs do the full auto cycle
  min_score: 80     # auto-generate only at/above this match score
  daily_cap: 5      # max documents auto-generated per run (LLM-cost guard)
schedule:
  enabled: true
  time: "08:00"
  timezone: America/Vancouver
```

### 6. Run it
```bash
python run_web.py     # the console + the in-process daily scheduler
# or, one autonomous run from the CLI (cron-friendly):
python run_agent.py
```
Open the console, log in with your `.env` credentials, and click **Run agent now**.

---

## The console
- **Dashboard** — today's Scanned / Matched / Prepared / Applied; a **Ready to apply** queue
  (download docs, Apply, Dismiss); a **Needs attention** triage queue (Retry / Apply / Dismiss);
  recent run history; next-run countdown; **Run agent now**.
- **Jobs** — manual control: filter / sort / paginate, generate or remove.
- **Generate** — paste a JD or an ATS URL → tailored résumé + cover letter.
- **Docs** — every generated document, searchable, with downloads.
- **Tracker** — editable application history (CSV import from Google Sheets), sortable, paginated.
- **Insights** — applications over time, by stage, and agent activity (prepared vs. applied).
- **Settings** — edit search/scoring/agent/schedule config (written back to `config.yaml`),
  with an email-configured indicator.

---

## Deploy always-on (Oracle Cloud Always Free)
A single always-on VM runs the console **and** the daily agent for $0.

1. Create an **Always Free** Ubuntu VM; open ingress for ports **80** and **443** in the VCN.
2. Point a free [DuckDNS](https://www.duckdns.org) subdomain at the VM's public IP.
3. On the VM: `git clone … && bash deploy/install.sh` (installs Python, Caddy, the venv).
4. From your laptop: `./deploy/sync-secrets.sh ubuntu@<vm-ip>` to push `.env` + `profile/`
   (these stay out of the public repo).
5. Edit `deploy/Caddyfile` with your domain → `sudo cp deploy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy`.
6. `sudo cp deploy/jobagent.service /etc/systemd/system/ && sudo systemctl enable --now jobagent`.

Caddy provides automatic HTTPS; the console is protected by HTTP Basic (`WEB_PASSWORD`) — use a
strong password. The agent's daily run fires from the always-on service and emails you.

## Safety & honest notes
- **Never auto-applies** — a human always does the final submit; "Apply" only records it.
- **ATS feeds are the safe primary source**; job boards (JobSpy) are off by default and ToS-grey.
- **Public repo:** secrets and your profile are gitignored and delivered to the VM via `scp`,
  never committed.
- **Where your data goes:** your résumé is in every prompt. Anthropic doesn't train on API
  inputs/outputs; Gemini's *free* tier may use prompts to improve their models.

## Development
```bash
pip install -r requirements-dev.txt
pytest
```
Tests are hermetic — no network, LLM, or email. See `CLAUDE.md` for architecture and conventions.

## Project layout
```
run_web.py         # web console + in-process daily scheduler
run_agent.py       # one-off autonomous run + email (cron-friendly)
config.yaml        # search, sources, scoring, agent, models, web, schedule
profile/           # your data (gitignored): profile.yaml, master.md, samples/, resume.docx
jobagent/          # ingest/, score, generate, llm, store, pipeline, notify, scheduler, web/
deploy/            # Oracle Cloud Always Free: install.sh, jobagent.service, Caddyfile, sync-secrets.sh
tests/             # hermetic pytest suite
```
