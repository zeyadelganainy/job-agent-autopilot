# job-agent

**An AI agent that takes the grind out of job applications — and keeps a human in the loop.**
It scans company job feeds, scores each role against *your* profile with an LLM, sends you
a ranked shortlist in Telegram, and writes a tailored résumé + cover letter (in your own
template and voice) for the ones you pick. You always apply manually.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/zeyadelganainy/job-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/zeyadelganainy/job-agent/actions/workflows/ci.yml)

<p align="center">
  <img src="docs/demo.gif" alt="job-agent: Telegram shortlist and a generated résumé" width="820">
</p>

```
scan  ─►  score  ─►  Telegram digest  ─►  you /pick 1 2 3  ─►  tailored docs  ─►  you apply
```

Everything runs on your machine, with your own API keys — your résumé data never leaves it.

---

## What it does

- 🔎 **Finds roles** from company ATS feeds (Greenhouse / Lever / Ashby) — public JSON, no scraping.
- 🧠 **Scores** each role 0–100 against your profile with an LLM, with reasons + gaps.
- 📨 **Shortlists** them in Telegram — a numbered digest, each with an Apply link.
- ✍️ **Writes** a tailored résumé + cover letter for the ones you `/pick`, rendered into
  *your own* `.docx` template, in *your* voice.
- ✅ **Hands off to you** — it never auto-submits an application.

## Engineering highlights

- **Human-in-the-loop by design** — never auto-applies. A deliberate safety + account-ban decision.
- **ATS feeds over scraping** — public JSON, no ToS-grey scraping for the primary source.
- **Resilient LLM layer** — Claude (Anthropic) primary, Gemini fallback, both BYOK, with
  exponential-backoff retry on rate-limit / transient errors, and clear, provider-named
  error messages when a model is rate-limited or unconfigured.
- **Optional web dashboard + analytics** — a professional FastAPI/Jinja UI over the same
  pipeline: scan/pick, ad-hoc generation, an editable application tracker (CSV import), and
  an Insights view with charts — no build step, no SPA.
- **Template-faithful generation** — opens your real résumé as a `.docx` template and fills
  in tailored content (fonts, margins, two-column layout, clickable links preserved).
- **Anti-fabrication guard** — generates only from a "source of truth" file and drops any
  link the model invents that isn't in it.
- **Config-driven & tested** — everything tunable from `config.yaml`; hermetic `pytest`
  suite (no network/LLM/Telegram) runs in CI.

> See [`docs/`](docs/) for how to add the demo image/GIF above.

---

## Setup

### 1. What you need
- **Python 3.10+**
- A **Telegram** account (the digest + files come to you there)
- At least one **LLM API key**:
  - **Gemini** — free tier, enough to start: https://aistudio.google.com/apikey
  - **Claude (Anthropic)** — paid, higher quality, *optional*:
    https://console.anthropic.com/settings/keys

Claude is used first when its key is set; otherwise it falls back to Gemini. You can run
**completely free on Gemini alone** by leaving the Claude key blank.

### 2. Install
```bash
pip install -r requirements.txt
```

### 3. Create a Telegram bot
1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the **bot token**.
2. Open a chat with your new bot and send it any message (e.g. `hi`).
3. Message [@userinfobot](https://t.me/userinfobot) → copy your numeric **chat ID**
   (a number like `6599293547`, **not** a `t.me/...` link).

### 4. Add your secrets
```bash
cp .env.example .env      # Windows: copy .env.example .env
```
```ini
# .env  (gitignored — never committed)
ANTHROPIC_API_KEY=        # leave blank to run free on Gemini
GEMINI_API_KEY=your_gemini_key
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=6599293547
```

### 5. Set up your profile and targets
- Fill in the files under `profile/` — see [Your profile](#your-profile).
- Edit `config.yaml` for your titles, locations, and target companies —
  see [Tailoring with config.yaml](#tailoring-with-configyaml).

### 6. Run it
```bash
python bot.py        # interactive: /scan, /list, /pick, /skip  (recommended)
# or
python run_scan.py   # one-off: scan + push a digest, then reply in the bot
```

---

## Day-to-day use

Run `python bot.py` and talk to your bot:

| Command | What it does |
|---------|--------------|
| `/scan` | Find new roles, score them, and show a numbered shortlist. |
| `/list` | Re-show the roles currently waiting on your decision. |
| `/pick 1 3 4` | Generate a résumé + cover letter for those numbers; files are sent back. |
| `/skip 2 5` | Dismiss those numbers. |

Reply with the **numbers** from the digest (not any IDs). Each entry shows the match %,
location, the scorer's reasoning, and an **Apply** link. Generated files land in
`output/<job_id>/`, named `[date]_[title]_[company]_resume.docx` and `..._coverLetter.docx`
(e.g. `20260625_software_developer_d2l_resume.docx`).

`run_scan.py` does a one-off scan and pushes a digest — handy for a daily cron / Task
Scheduler job; you then open the bot and `/pick`.

---

## Web UI

A full browser dashboard over the same engine — a clean, professional job-tracker
interface (Swiss-minimal blue/amber design, Fira typography). Run scans, pick jobs,
generate from any job description, browse generated docs, manage an editable application
tracker, see analytics, and edit your search settings — all without a build step.

```bash
pip install -r requirements.txt
# set WEB_USERNAME / WEB_PASSWORD in .env, then:
python run_web.py        # serves on the host/port from config.yaml `web:`
```

Log in with the `WEB_USERNAME` / `WEB_PASSWORD` from your `.env`. Pages:
- **Dashboard** — headline counts (each links through), the jobs awaiting your decision, and a live "next scan in …" countdown, with a "Run scan now" button.
- **Jobs** — filter (company / location / match / posted date), sort, and paginate; tick rows to generate docs (background task with live progress) or **remove** the ones you don't want.
- **Generate** — paste a job description **or** an ATS URL (Greenhouse/Lever/Ashby) → tailored résumé + cover letter `.docx`.
- **Docs** — every generated document, searchable by role/company and date, with downloads.
- **Tracker** — import your Google Sheets tracker (CSV with role, company, date applied, stage, location, notes); **editable** (add / edit / delete), sortable, paginated.
- **Insights** — an analytics dashboard: applications over time (line chart with an average line), applications by stage (doughnut), and headline stats.
- **Settings** — edit your search config (keywords, locations, target companies, scoring, models, schedule, and a **company blocklist** for recruiters/scams) from the browser; written back to `config.yaml` with comments preserved.

**Scheduled daily scans:** while the web app is running, it scans at `schedule.time`
(`config.yaml`) each day and pushes the digest to Telegram.

**Access & security:** set `web.host` to `0.0.0.0` for LAN/Tailscale access or `127.0.0.1`
for localhost only. Auth is a single username/password (HTTP Basic) over plain HTTP — keep
it on a trusted network, or put a TLS reverse proxy in front before any public exposure.
Run the web app **or** the Telegram bot (they share one SQLite DB; not meant to run at once).

## Tailoring with `config.yaml`

Point the agent at the jobs you want, then re-run a scan.

### `search` — what and where
```yaml
search:
  keywords:                 # keep a role if its title/description contains ANY of these
    - software engineer
    - backend engineer
    - new grad
  locations:                # keep a role if its location text contains ANY of these
    - Canada                #   (case-insensitive substring match)
    - Vancouver
    - Remote                # add only if you want remote roles regardless of country
  remote_ok: true           # used by the job-board search
  max_age_days: 7           # ignore postings older than this (when a date is available)
  block_companies: []       # never show roles from these companies (recruiters/scams);
                            #   case-insensitive substring — also editable in the web Settings page
```
- **keywords** decide *which kinds of roles* surface (coarse filter; the fine judgment of
  fit is the scorer's job, against your profile).
- **locations** restrict by place. A role with no location listed is kept. Want anywhere?
  Leave `locations` empty.

### `sources` — where the jobs come from
```yaml
sources:
  ats:                      # public company feeds — the preferred, ToS-safe source
    greenhouse: [stripe, figma, wealthsimple, clio]
    lever: []
    ashby: [1password]
  boards:                   # job boards via JobSpy — optional, see the warning
    enabled: false
    sites: [indeed, linkedin, zip_recruiter, google]
    results_per_site: 25
```
**ATS feeds are how you target specific companies.** Each company has a short **token** —
find it in the careers URL:

| Provider   | Careers URL looks like        | Token       |
|------------|-------------------------------|-------------|
| Greenhouse | `boards.greenhouse.io/stripe` | `stripe`    |
| Lever      | `jobs.lever.co/figma`         | `figma`     |
| Ashby      | `jobs.ashbyhq.com/1password`  | `1password` |

Add the companies you want to the matching list. (Quick check: open
`https://boards-api.greenhouse.io/v1/boards/<token>/jobs` — if you get JSON, it works.)

> **Boards are off by default for a reason.** JobSpy scrapes Indeed/LinkedIn/etc., which is
> ToS-grey and can get your IP blocked. ATS feeds avoid all that. If you enable boards, also
> `pip install python-jobspy` (else they're silently skipped) and accept the tradeoff.

### `scoring` — how picky, and how much to score
```yaml
scoring:
  threshold: 60        # only roles scoring >= this appear in the digest
  digest_size: 10      # max roles shown per digest
  max_to_score: 25     # cap NEW roles scored per scan (free-tier friendly); 0 = no cap
```
**max_to_score** stops one scan from trying to score hundreds of roles (which would blow
through free LLM limits). Unscored roles are picked up on the next scan.

### `models` — quality vs. cost
```yaml
models:
  claude: claude-opus-4-8    # primary (paid). Cheaper: claude-sonnet-4-6 / claude-haiku-4-5
  gemini: gemini-2.5-flash   # fallback (free tier)
```
Leave `ANTHROPIC_API_KEY` blank to run free on Gemini. See [Models & cost](#models--cost).

### `llm` / `paths`
`llm` holds rate-limit knobs (retries, backoff, `max_tokens`) — rarely need changing.
`paths` is the DB, output folder, and the four profile files (defaults are fine).

---

## Your profile

Four files under `profile/` describe you. They're **personal data and are gitignored** —
never committed. Each has a distinct job:

| File | Used for | What to put in it |
|------|----------|-------------------|
| **`profile/profile.yaml`** | **Scoring** every role | A compact, structured CV. Small on purpose — it's sent on every score call. |
| **`profile/master.md`** | **Generating** documents | Your full "source of truth": every role, project, bullet, metric — a pool to select from. The generator follows instructions you put at its top. |
| **`profile/samples/`** | **Voice** of the cover letter | 1–3 past cover letters or a bio (`.txt`/`.md`). Skipping these makes output sound generic. |
| **`profile/resume.docx`** | **Look** of the résumé | Your own résumé. Used as the template — output reuses its fonts, margins, and layout. |

**On a `/pick`:** the LLM selects/reorders/rephrases your real content from `master.md`
into a one-page résumé, renders it into a `.docx` styled like your `resume.docx`, and writes
a cover letter from those facts in your `samples/` voice. It only includes a project link
if that exact URL appears in `master.md` — no invented links.

> Keep `profile.yaml` and `master.md` factually identical: the short version for scoring,
> the long version for writing.

---

## Models & cost

- **Free path:** leave `ANTHROPIC_API_KEY` blank → everything runs on Gemini's free tier.
  Caveats: daily request caps (e.g. ~20/day on `gemini-2.5-flash`) and occasional `503`
  "high demand" errors. Backoff retries them, but heavy use in one day — especially the
  token-heavy generation step — can hit the wall.
- **Reliable path:** set `ANTHROPIC_API_KEY` and use Claude (each `/pick` is 2 calls). Use
  `claude-sonnet-4-6` / `claude-haiku-4-5` to cut cost.
- A practical mix: score on the free tier, set a Claude key so *generation* is dependable.

## Safety & honest notes

- **Never auto-applies** — a human always does the final submit.
- **ATS feeds are the safe primary source**; boards are optional and ToS-grey (see above).
- **Where your data goes:** your résumé is in every prompt. Anthropic doesn't train on API
  inputs/outputs. Gemini's *free* tier may use prompts to improve their models (the paid
  tier doesn't) — fine for personal use, just know it.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```
Tests are hermetic — no network, LLM, or Telegram calls. See `CLAUDE.md` for architecture
and conventions.

## Project layout
```
run_scan.py        # one-off scan -> digest
run_web.py         # launch the web UI (v1.1)
bot.py             # interactive Telegram bot
config.yaml        # search, sources, scoring, models, web, schedule  (you edit this)
profile/           # your data: profile.yaml, master.md, samples/, resume.docx  (gitignored)
jobagent/          # ingest/, score, generate, llm, store, pipeline, scheduler, tracker, web/
tests/             # pytest suite
```
