"""High-level operations shared by the autopilot agent, the scheduler, and the web UI."""
import hashlib
import html
import time

from .config import env, load_config, load_master, load_profile, load_samples
from .generate import generate
from .ingest import ats
from .ingest.runner import gather
from .llm import LLMError
from .models import Job
from .score import score_job
from .store import Store

# Application portals the agent can't prep a clean apply for — flag for manual handling.
EXTERNAL_PORTALS = ("myworkdayjobs.com", "workday", "taleo", "icims", "successfactors",
                    "brassring", "jobvite", "smartrecruiters", "oraclecloud.com")


def _store(cfg) -> Store:
    return Store(cfg["paths"]["db"])


def scan(cfg=None, stats: dict = None) -> list[dict]:
    """Ingest -> score new jobs -> store. Returns the jobs newly added to the digest.

    If `stats` (a dict) is passed, it's filled with scanned/scored/matched counts for the
    run summary — behaviour is otherwise unchanged.
    """
    cfg = cfg or load_config()
    profile = load_profile(cfg)
    store = _store(cfg)
    models = cfg["models"]
    threshold = cfg["scoring"]["threshold"]
    cap = cfg["scoring"].get("max_to_score", 25)   # 0/None = unlimited

    new_digest = []
    scored = examined = 0
    for j in gather(cfg):
        if cap and scored >= cap:       # stop *before* inserting — leaves the rest
            break                       # un-stored so the next scan picks them up
        examined += 1
        if not store.upsert_job(j):     # already seen
            continue
        score_job(j, profile, models)
        store.save_score(j)
        scored += 1
        if (j.score or 0) >= threshold:
            store.set_status(j.job_id, "sent")
            new_digest.append(j.to_dict())

    new_digest.sort(key=lambda d: d["score"] or 0, reverse=True)
    if stats is not None:
        stats.update(scanned=examined, scored=scored, matched=len(new_digest))
    return new_digest[: cfg["scoring"]["digest_size"]]


def _e(text) -> str:
    """HTML-escape."""
    return html.escape(str(text or ""), quote=True)


def format_digest(jobs: list[dict]) -> str:
    """Numbered, spaced HTML digest of matched jobs (used in the run email)."""
    if not jobs:
        return "No jobs waiting. The agent will look again on its next run."
    out = ["<b>Job matches</b>", ""]
    for i, j in enumerate(jobs, 1):
        out.append(f"<b>{i}.</b> <b>{_e(j.get('title'))}</b> — {_e(j.get('company'))}")
        meta = f"    {j.get('score') or 0}% match"
        if j.get("location"):
            meta += f"  ·  {_e(j['location'])}"
        out.append(meta)
        if j.get("reasons"):
            out.append(f"    <i>{_e(j['reasons'])}</i>")
        if j.get("url"):
            out.append(f'    🔗 <a href="{_e(j["url"])}">View posting</a>')
        out.append("")
    return "\n".join(out).strip()


def pending(cfg=None) -> list[dict]:
    """Jobs sent but not yet picked/skipped, in the digest's display order."""
    cfg = cfg or load_config()
    return [dict(r) for r in _store(cfg).by_status("sent")]


def picks_to_ids(numbers, cfg=None):
    """Map 1-based digest positions to job_ids. Returns (ids, invalid_tokens)."""
    rows = pending(cfg)
    ids, bad = [], []
    for n in numbers:
        s = str(n)
        if s.isdigit() and 1 <= int(s) <= len(rows):
            ids.append(rows[int(s) - 1]["job_id"])
        else:
            bad.append(s)
    return ids, bad


def pick_and_generate(job_ids: list[str], cfg=None):
    """For each id: mark picked, generate docs. Yields (job_row, paths) as it goes."""
    cfg = cfg or load_config()
    profile = load_profile(cfg)
    samples = load_samples(cfg)
    master = load_master(cfg)
    store = _store(cfg)
    models = cfg["models"]
    gen_delay = (cfg.get("llm") or {}).get("gen_delay_seconds", 3)

    first = True
    for jid in job_ids:
        row = store.get(jid)
        if not row:
            yield {"job_id": jid, "title": "(unknown id)"}, []
            continue
        if not first:
            time.sleep(gen_delay)   # space out batches to ease free-tier rate limits
        first = False
        store.set_status(jid, "picked")
        paths = generate(row, profile, samples, master, models, cfg["paths"])
        store.record_docs(jid, paths)
        yield dict(row), paths


def generate_for_jd(source: str, cfg=None, title=None, company=None):
    """Generate docs for an ad-hoc job description: pasted text OR an ATS URL.

    Returns (job_row_dict, paths). Reuses generate() and the store so the job shows
    up in the docs library like any picked job.
    """
    cfg = cfg or load_config()
    source = (source or "").strip()
    if not source:
        raise ValueError("Provide a job description (pasted text or an ATS URL).")

    if source.lower().startswith(("http://", "https://")):
        job = ats.fetch_job(source)                       # raises on unsupported URLs
    else:
        job = Job(source="adhoc", title=(title or "Pasted role").strip(),
                  company=(company or "Pasted company").strip(), url="",
                  description=source)
        job.job_id = "adhoc" + hashlib.sha1(source.encode("utf-8")).hexdigest()[:10]

    store = _store(cfg)
    store.upsert_job(job)
    row = store.get(job.job_id)
    paths = generate(row, load_profile(cfg), load_samples(cfg), load_master(cfg),
                     cfg["models"], cfg["paths"])
    store.record_docs(job.job_id, paths)
    return dict(store.get(job.job_id)), paths


# ---------------------------------------------------------------------------
# Autopilot: the autonomous run + helpers
# ---------------------------------------------------------------------------
def _field(obj, key):
    try:
        return obj[key]
    except (KeyError, IndexError, TypeError):
        return getattr(obj, key, None)


def needs_manual_apply(job) -> bool:
    """True if the posting lives on an external application portal (Workday/Taleo/iCIMS/…)
    that the agent can't streamline — docs are still prepared, but you apply manually."""
    url = (_field(job, "url") or "").lower()
    return any(p in url for p in EXTERNAL_PORTALS)


def _att(row, reason, kind):
    return {"job_id": row["job_id"], "title": row["title"], "company": row["company"],
            "reason": reason, "kind": kind, "url": row["url"]}


def agent_run(cfg=None) -> dict:
    """One autonomous cycle: scan -> score -> auto-generate docs for the best matches.

    Never applies (the human always does that). Jobs the agent can't finish are flagged
    into the triage queue: an `LLMError` (quota/API) flags the current + remaining picks and
    stops; a manual external portal is flagged but keeps its docs. Returns a summary dict
    and records an `agent_runs` row for the monitoring console.
    """
    cfg = cfg or load_config()
    ag = cfg.get("agent") or {}
    min_score = ag.get("min_score", 80)
    daily_cap = ag.get("daily_cap", 5)
    store = _store(cfg)
    run_id = store.start_run()
    summary = {"scanned": 0, "scored": 0, "matched": 0,
               "generated": [], "attention": [], "error": None}
    try:
        stats = {}
        scan(cfg, stats)
        summary.update(scanned=stats.get("scanned", 0), scored=stats.get("scored", 0),
                       matched=stats.get("matched", 0))

        candidates = [r for r in store.by_status("sent")
                      if (r["score"] or 0) >= min_score and not r["docs"]][:daily_cap]
        for idx, row in enumerate(candidates):
            jid = row["job_id"]
            try:
                _, paths = next(iter(pick_and_generate([jid], cfg)))
            except LLMError as e:               # quota/API — flag the rest and stop
                for rest in candidates[idx:]:
                    store.flag_job(rest["job_id"], str(e))
                    summary["attention"].append(_att(rest, str(e), "llm_error"))
                summary["error"] = str(e)
                break
            gen = store.get(jid)
            if needs_manual_apply(gen):
                msg = "Manual application portal (Workday/external) — apply yourself"
                store.flag_job(jid, msg)
                summary["attention"].append(_att(gen, msg, "manual_portal"))
            else:
                summary["generated"].append(
                    {"job_id": jid, "title": row["title"], "company": row["company"],
                     "score": row["score"], "url": row["url"], "paths": paths})
    except LLMError as e:                        # scan/scoring failed wholesale
        summary["error"] = str(e)
    finally:
        store.finish_run(run_id, status="error" if summary["error"] else "ok",
                         scanned=summary["scanned"], scored=summary["scored"],
                         matched=summary["matched"], generated=len(summary["generated"]),
                         needs_attention=len(summary["attention"]), error=summary["error"])
    return summary


def format_email(summary: dict) -> str:
    """Build the HTML run digest emailed after each agent run."""
    g, a = summary.get("generated", []), summary.get("attention", [])
    parts = ["<h2 style='margin:0 0 4px'>job-agent — daily run</h2>",
             f"<p style='color:#555'>Scanned {summary.get('scanned', 0)} · "
             f"matched {summary.get('matched', 0)} · prepared {len(g)} · "
             f"needs attention {len(a)}</p>"]
    if g:
        parts.append("<h3>Ready to apply</h3><ul>")
        for j in g:
            link = f' — <a href="{_e(j["url"])}">posting</a>' if j.get("url") else ""
            parts.append(f"<li><b>{_e(j['title'])}</b> — {_e(j['company'])} "
                         f"({j.get('score') or 0}%){link}</li>")
        parts.append("</ul>")
    if a:
        parts.append("<h3>Needs your attention</h3><ul>")
        for j in a:
            link = f' — <a href="{_e(j["url"])}">posting</a>' if j.get("url") else ""
            parts.append(f"<li><b>{_e(j['title'])}</b> — {_e(j['company'])}: "
                         f"{_e(j['reason'])}{link}</li>")
        parts.append("</ul>")
    if summary.get("error"):
        parts.append(f"<p><b>Run error:</b> {_e(summary['error'])}</p>")
    if not g and not a:
        parts.append("<p>No new matches this run.</p>")
    app_url = env("APP_URL")
    if app_url:
        parts.append(f'<p><a href="{_e(app_url)}">Open the dashboard →</a></p>')
    return "\n".join(parts)
