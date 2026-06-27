"""High-level operations shared by the CLI scan, the Telegram bot, and the web UI."""
import hashlib
import html
import time

from .config import load_config, load_master, load_profile, load_samples
from .generate import generate
from .ingest import ats
from .ingest.runner import gather
from .models import Job
from .score import score_job
from .store import Store


def _store(cfg) -> Store:
    return Store(cfg["paths"]["db"])


def scan(cfg=None) -> list[dict]:
    """Ingest -> score new jobs -> store. Returns the jobs newly added to the digest."""
    cfg = cfg or load_config()
    profile = load_profile(cfg)
    store = _store(cfg)
    models = cfg["models"]
    threshold = cfg["scoring"]["threshold"]
    cap = cfg["scoring"].get("max_to_score", 25)   # 0/None = unlimited

    new_digest = []
    scored = 0
    for j in gather(cfg):
        if cap and scored >= cap:       # stop *before* inserting — leaves the rest
            break                       # un-stored so the next scan picks them up
        if not store.upsert_job(j):     # already seen
            continue
        score_job(j, profile, models)
        store.save_score(j)
        scored += 1
        if (j.score or 0) >= threshold:
            store.set_status(j.job_id, "sent")
            new_digest.append(j.to_dict())

    new_digest.sort(key=lambda d: d["score"] or 0, reverse=True)
    return new_digest[: cfg["scoring"]["digest_size"]]


def _e(text) -> str:
    """HTML-escape for Telegram's HTML parse mode."""
    return html.escape(str(text or ""), quote=True)


def format_digest(jobs: list[dict]) -> str:
    """Numbered, spaced HTML digest. Reply with the numbers, not the ids."""
    if not jobs:
        return "No jobs waiting. Run /scan to find matches."
    out = ["<b>Job matches</b> — reply <code>/pick 1 2 3</code> to generate docs "
           "(or <code>/skip 1</code> to dismiss).", ""]
    for i, j in enumerate(jobs, 1):
        out.append(f"<b>{i}.</b> <b>{_e(j.get('title'))}</b> — {_e(j.get('company'))}")
        meta = f"    {j.get('score') or 0}% match"
        if j.get("location"):
            meta += f"  ·  {_e(j['location'])}"
        out.append(meta)
        if j.get("reasons"):
            out.append(f"    <i>{_e(j['reasons'])}</i>")
        if j.get("url"):
            out.append(f'    🔗 <a href="{_e(j["url"])}">Apply / view posting</a>')
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
