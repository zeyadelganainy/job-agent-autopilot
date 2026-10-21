# JobPilot

A self-hosted agent that finds relevant job postings, scores them against your profile and prepares
a tailored résumé and cover letter for each strong match. You review and apply yourself.
**Live demo:** https://zeyad-jobs.duckdns.org (click **View the demo** for a sandbox that makes no live calls).

[![CI](https://github.com/zeyadelganainy/job-agent-autopilot/actions/workflows/ci.yml/badge.svg)](https://github.com/zeyadelganainy/job-agent-autopilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> The repository is named `job-agent-autopilot` for historical reasons. It is version 2 of
> [job-agent](https://github.com/zeyadelganainy/job-agent), which used a Telegram bot and a manual
> pick step.

## The problem

Applying well takes time: finding roles that fit, reading each posting, and rewriting a résumé and
cover letter for it. JobPilot does that preparation every day on its own, and leaves the decision
and the final submission to a person.

```
scan ATS feeds -> score each role -> pick the best matches -> generate documents -> email digest -> you apply
```

## Key design decisions

- **A human always submits.** The agent prepares documents but never applies. The Apply button only
  records the application and opens the posting. Automated submissions risk account bans, and the
  final decision should be the user's.
- **Nothing fails silently.** Anything the agent cannot finish, such as an LLM quota error or a
  posting behind a manual portal like Workday, Taleo or iCIMS, goes into a triage queue with the
  reason and Retry / Apply / Dismiss actions.
- **One source of truth for facts.** Documents are generated only from the user's `master.md`. The
  prompt forbids invented facts, and a code-level check removes any project link that does not
  appear verbatim in that file.
- **One entry point for every LLM call.** All calls go through `llm.chat()`: Claude first, then a
  free OpenAI-compatible fallback (OpenRouter by default) that tries the next model on rate limits,
  quota errors and transient failures. Errors name the provider that failed.
- **Public job data only.** Company ATS feeds (Greenhouse, Lever, Ashby) are the primary source
  because they are public JSON. Job boards (through JobSpy) are an optional extra source, a switch
  in `config.yaml`, because scraping them sits in a terms-of-service grey area and can get a server
  IP blocked.
- **Personal data stays out of git.** Keys live in `.env` and the profile lives in `profile/`, both
  gitignored and copied to the server with `scp`.

## Tech stack

Python, FastAPI, Jinja2, vanilla JavaScript and Chart.js (no front-end build step), APScheduler,
SQLite, python-docx, Anthropic Claude API, OpenRouter, SMTP email, pytest and GitHub Actions.
Deployed on an Oracle Cloud Always Free VM with systemd, Caddy (automatic HTTPS), DuckDNS and `uv`.

## Run it locally

Requires Python 3.10+, at least one LLM key (Claude, or a free OpenRouter key), and optionally an
SMTP mailbox for the digest.

```bash
pip install -r requirements.txt
cp .env.example .env        # add API keys, WEB_USERNAME / WEB_PASSWORD, SMTP settings
# put your profile in profile/: profile.yaml, master.md, resume.docx, samples/
python run_web.py           # console plus the daily scheduler
python run_agent.py         # or a single autonomous run, cron-friendly
```

Search terms, target companies, the score threshold (`agent.min_score`), the daily cap and the
schedule are all in `config.yaml` and can be edited from the Settings page. To run it always-on,
see [docs/DEPLOY.md](docs/DEPLOY.md).

## How it's tested

```bash
pip install -r requirements-dev.txt
pytest
```

117 pytest tests cover ingestion and filtering, scoring, the agent cycle and triage flagging,
document generation, the LLM fallback chain, email formatting, the tracker and the web routes. The
suite is hermetic: network, LLM and SMTP calls are stubbed. CI runs it on Python 3.10, 3.11 and
3.12 on every push.

## Known limitations and next steps

- **Scores come from an LLM**, so two runs can rate the same role slightly differently. There is no
  evaluation set yet that measures scoring quality; building one is the next step.
- **The free fallback is limited** (about 50 requests a day on OpenRouter's free models), so a
  Claude key is needed for dependable daily runs.
- **Manual-portal detection is a URL heuristic.** Postings on portals it does not recognise are
  treated as normal ones.
- **Single user.** One deployment serves one person's profile.
- The tracker does not yet report response or interview rates, or time to response.

## How it was built

I used Claude Code for implementation while making the architecture decisions and reviewing the
output myself. [CLAUDE.md](CLAUDE.md) is the behavioural contract that governed that work, including
the rule that the agent never submits applications.

## License

MIT. See [LICENSE](LICENSE).
