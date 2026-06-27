"""FastAPI web UI for job-agent (v1.1).

Wraps the existing pipeline/store: run scan/pick, generate from any JD (text or ATS
URL), browse + filter generated docs, run an editable application tracker, and edit
search settings. Password-protected (HTTP Basic). Swagger disabled so /docs is the
document library.
"""
import json
import secrets
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import pipeline, settings_io, tracker, webutil
from ..config import ROOT, env, load_config
from ..scheduler import next_run_time, start_scheduler
from ..store import Store

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

app = FastAPI(title="job-agent", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
security = HTTPBasic()

UTC_MIN = datetime.min.replace(tzinfo=timezone.utc)


def require_auth(creds: HTTPBasicCredentials = Depends(security)) -> bool:
    user, pw = env("WEB_USERNAME") or "admin", env("WEB_PASSWORD")
    if not pw:
        raise HTTPException(status_code=500, detail="Set WEB_PASSWORD in .env to use the UI.")
    ok = secrets.compare_digest(creds.username, user) and secrets.compare_digest(creds.password, pw)
    if not ok:
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "Basic"})
    return True


def _store() -> Store:
    return Store(load_config()["paths"]["db"])


def render(request: Request, name: str, ctx: dict = None):
    ctx = dict(ctx or {})
    ctx["request"] = request
    nrt = next_run_time(getattr(app.state, "scheduler", None))
    ctx.setdefault("next_scan", webutil.human_until(nrt))           # no-JS fallback
    ctx.setdefault("next_scan_ts", int(nrt.timestamp() * 1000) if nrt else "")
    return templates.TemplateResponse(request, name, ctx)


def _lines(text: str) -> list[str]:
    """Split a textarea (newline- or comma-separated) into a clean list."""
    parts = (text or "").replace(",", "\n").splitlines()
    return [p.strip() for p in parts if p.strip()]


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---- background tasks ----
TASKS: dict[str, dict] = {}


def start_task(kind: str, fn) -> str:
    tid = uuid.uuid4().hex[:8]
    TASKS[tid] = {"status": "running", "kind": kind, "result": None,
                  "error": None, "started": time.time()}

    def work():
        try:
            TASKS[tid]["result"] = fn()
            TASKS[tid]["status"] = "done"
        except Exception as e:
            TASKS[tid]["error"] = str(e)
            TASKS[tid]["status"] = "error"

    threading.Thread(target=work, daemon=True).start()
    return tid


def _reschedule():
    old = getattr(app.state, "scheduler", None)
    if old:
        try:
            old.shutdown(wait=False)
        except Exception:
            pass
    app.state.scheduler = start_scheduler()


@app.on_event("startup")
def _startup():
    app.state.scheduler = start_scheduler()


@app.get("/tasks/{tid}")
def task_status(tid: str, _=Depends(require_auth)):
    t = dict(TASKS.get(tid, {"status": "unknown"}))
    if t.get("started"):
        t["elapsed"] = round(time.time() - t["started"], 1)
        t.pop("started", None)
    return JSONResponse(t)


# ---- dashboard ----
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, task: str = None, _=Depends(require_auth)):
    s = _store()
    try:
        pend = [dict(r) for r in s.by_status("sent")]
        counts = {"pending": len(pend), "generated": len(s.all_docs()),
                  "applications": len(s.list_applications())}
    finally:
        s.close()
    nrt = next_run_time(getattr(app.state, "scheduler", None))
    return render(request, "dashboard.html", {
        "counts": counts, "pending": pend[:8],
        "next_run_h": webutil.human_until(nrt),
        "next_run": nrt.strftime("%b %d, %H:%M") if nrt else None, "task": task})


@app.post("/scan")
def do_scan(_=Depends(require_auth)):
    tid = start_task("scan", lambda: len(pipeline.scan(load_config())))
    return RedirectResponse(f"/?task={tid}", status_code=303)


# ---- jobs (filter / sort / paginate) ----
@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, company: str = "", location: str = "", min_score: str = "",
              max_age: str = "", sort: str = "match", dir: str = "desc",
              page: int = 1, task: str = None, _=Depends(require_auth)):
    s = _store()
    try:
        rows = [dict(r) for r in s.by_status("sent")]
    finally:
        s.close()

    if company:
        rows = [r for r in rows if company.lower() in (r["company"] or "").lower()]
    if location:
        rows = [r for r in rows if location.lower() in (r["location"] or "").lower()]
    ms = _int(min_score)
    if ms is not None:
        rows = [r for r in rows if (r["score"] or 0) >= ms]
    days = _int(max_age)
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = [r for r in rows if (webutil.to_dt(r.get("posted")) or cutoff) >= cutoff]

    keymap = {"match": lambda r: (r["score"] or 0),
              "location": lambda r: (r["location"] or "").lower(),
              "date": lambda r: (webutil.to_dt(r.get("posted")) or UTC_MIN)}
    rows.sort(key=keymap.get(sort, keymap["match"]), reverse=(dir == "desc"))

    page_rows, pg = webutil.paginate(rows, page, 20)
    return render(request, "jobs.html", {
        "jobs": page_rows, "pg": pg, "task": task,
        "f": {"company": company, "location": location, "min_score": min_score,
              "max_age": max_age, "sort": sort, "dir": dir}})


@app.post("/pick")
def do_pick(job_ids: list[str] = Form(default=[]), _=Depends(require_auth)):
    if not job_ids:
        return RedirectResponse("/jobs", status_code=303)
    tid = start_task("pick",
        lambda: [r["job_id"] for r, _ in pipeline.pick_and_generate(job_ids, load_config())])
    return RedirectResponse(f"/jobs?task={tid}", status_code=303)


@app.post("/jobs/remove")
def jobs_remove(job_ids: list[str] = Form(default=[]), _=Depends(require_auth)):
    """Dismiss postings: mark 'skipped' so they leave the board and a re-scan
    won't bring them back (the job_id is already known)."""
    if job_ids:
        s = _store()
        try:
            for jid in job_ids:
                s.set_status(jid, "skipped")
        finally:
            s.close()
    return RedirectResponse("/jobs", status_code=303)


# ---- generate ----
@app.get("/generate", response_class=HTMLResponse)
def generate_form(request: Request, _=Depends(require_auth)):
    return render(request, "generate.html", {"result": None})


@app.post("/generate", response_class=HTMLResponse)
def do_generate(request: Request, source: str = Form(...), title: str = Form(None),
                company: str = Form(None), _=Depends(require_auth)):
    try:
        row, paths = pipeline.generate_for_jd(source, load_config(),
                                              title=title or None, company=company or None)
        result = {"ok": True, "job": row,
                  "docs": [{"name": Path(p).name, "path": p} for p in paths]}
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    return render(request, "generate.html", {"result": result})


# ---- docs (search / paginate) ----
@app.get("/docs", response_class=HTMLResponse)
def docs_library(request: Request, q: str = "", since: str = "", page: int = 1,
                 _=Depends(require_auth)):
    s = _store()
    try:
        rows = [dict(r) for r in s.all_docs()]
    finally:
        s.close()
    if q:
        ql = q.lower()
        rows = [r for r in rows
                if ql in (r["title"] or "").lower() or ql in (r["company"] or "").lower()]
    days = _int(since)
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = [r for r in rows if (webutil.to_dt(r.get("created_at")) or cutoff) >= cutoff]
    rows.sort(key=lambda r: (webutil.to_dt(r.get("created_at")) or UTC_MIN), reverse=True)
    for r in rows:
        try:
            r["doc_files"] = [{"name": Path(p).name, "path": p}
                              for p in json.loads(r.get("docs") or "[]")]
        except Exception:
            r["doc_files"] = []
    page_rows, pg = webutil.paginate(rows, page, 15)
    return render(request, "docs.html",
                  {"jobs": page_rows, "pg": pg, "f": {"q": q, "since": since}})


@app.get("/download")
def download(path: str, _=Depends(require_auth)):
    base = (ROOT / load_config()["paths"]["output"]).resolve()
    target = Path(path).resolve()
    if not target.is_relative_to(base):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(str(target), filename=target.name)


# ---- insights (analytics) ----
@app.get("/insights", response_class=HTMLResponse)
def insights_page(request: Request, _=Depends(require_auth)):
    s = _store()
    try:
        apps = [dict(r) for r in s.list_applications()]
    finally:
        s.close()

    stage_counts = Counter((a["stage"] or "").strip() or "Unspecified" for a in apps).most_common()

    months = Counter()
    for a in apps:
        dt = webutil.to_dt(a.get("applied_date"))
        if dt:
            months[dt.strftime("%Y-%m")] += 1
    month_items = sorted(months.items())[-12:]
    m_labels = [k for k, _ in month_items]
    m_counts = [v for _, v in month_items]
    avg = round(sum(m_counts) / len(m_counts), 1) if m_counts else 0
    companies = len({(a["company"] or "").strip().lower() for a in apps if (a["company"] or "").strip()})

    return render(request, "insights.html", {
        "stage_labels": [k for k, _ in stage_counts],
        "stage_counts": [c for _, c in stage_counts],
        "m_labels": m_labels, "m_counts": m_counts, "avg": avg,
        "totals": {"apps": len(apps), "companies": companies, "avg": avg,
                   "this_month": months.get(datetime.now().strftime("%Y-%m"), 0)}})


# ---- tracker (editable + paginate) ----
@app.get("/tracker", response_class=HTMLResponse)
def tracker_page(request: Request, stage: str = "", company: str = "",
                 sort: str = "applied", dir: str = "desc", page: int = 1,
                 summary: str = None, _=Depends(require_auth)):
    s = _store()
    try:
        allrows = [dict(r) for r in s.list_applications()]
    finally:
        s.close()
    stages = sorted({(r["stage"] or "").strip() for r in allrows if (r["stage"] or "").strip()})
    rows = allrows
    if stage:
        rows = [r for r in rows if (r["stage"] or "").lower() == stage.lower()]
    if company:
        rows = [r for r in rows if company.lower() in (r["company"] or "").lower()]

    keymap = {"company": lambda r: (r["company"] or "").lower(),
              "role": lambda r: (r["role"] or "").lower(),
              "stage": lambda r: (r["stage"] or "").lower(),
              "location": lambda r: (r["location"] or "").lower(),
              "applied": lambda r: (webutil.to_dt(r.get("applied_date")) or UTC_MIN)}
    rows.sort(key=keymap.get(sort, keymap["applied"]), reverse=(dir == "desc"))

    page_rows, pg = webutil.paginate(rows, page, 25)
    return render(request, "tracker.html", {
        "apps": page_rows, "pg": pg, "stages": stages, "summary": summary,
        "f": {"stage": stage, "company": company, "sort": sort, "dir": dir}})


@app.post("/tracker/import", response_class=HTMLResponse)
async def tracker_import(request: Request, file: UploadFile = File(...), _=Depends(require_auth)):
    content = (await file.read()).decode("utf-8-sig", errors="replace")
    s = _store()
    try:
        summ = tracker.import_csv(content, s)
    finally:
        s.close()
    return RedirectResponse(
        f"/tracker?summary=Imported+{summ['inserted']}+new,+updated+{summ['updated']}",
        status_code=303)


def _app_fields(role, company, applied_date, stage, location, notes) -> dict:
    return {"role": role or "", "company": company or "", "applied_date": applied_date or "",
            "stage": stage or "", "location": location or "", "notes": notes or ""}


@app.post("/tracker/add")
def tracker_add(role: str = Form(""), company: str = Form(""), applied_date: str = Form(""),
                stage: str = Form(""), location: str = Form(""), notes: str = Form(""),
                _=Depends(require_auth)):
    if company or role:
        s = _store()
        try:
            s.add_application(_app_fields(role, company, applied_date, stage, location, notes))
        finally:
            s.close()
    return RedirectResponse("/tracker", status_code=303)


@app.get("/tracker/{app_id}/edit", response_class=HTMLResponse)
def tracker_edit_form(request: Request, app_id: int, _=Depends(require_auth)):
    s = _store()
    try:
        row = s.get_application(app_id)
    finally:
        s.close()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return render(request, "tracker_edit.html", {"a": dict(row)})


@app.post("/tracker/{app_id}/edit")
def tracker_edit_save(app_id: int, role: str = Form(""), company: str = Form(""),
                      applied_date: str = Form(""), stage: str = Form(""),
                      location: str = Form(""), notes: str = Form(""), _=Depends(require_auth)):
    s = _store()
    try:
        s.update_application(app_id, _app_fields(role, company, applied_date, stage, location, notes))
    finally:
        s.close()
    return RedirectResponse("/tracker", status_code=303)


@app.post("/tracker/{app_id}/delete")
def tracker_delete(app_id: int, _=Depends(require_auth)):
    s = _store()
    try:
        s.delete_application(app_id)
    finally:
        s.close()
    return RedirectResponse("/tracker", status_code=303)


# ---- settings (edit config.yaml) ----
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str = None, _=Depends(require_auth)):
    return render(request, "settings.html", {"s": settings_io.read(), "saved": saved})


@app.post("/settings")
def settings_save(
    keywords: str = Form(""), locations: str = Form(""), block_companies: str = Form(""),
    remote_ok: str = Form(None), max_age_days: str = Form(""), greenhouse: str = Form(""),
    lever: str = Form(""), ashby: str = Form(""), boards_enabled: str = Form(None),
    threshold: str = Form(""), digest_size: str = Form(""), max_to_score: str = Form(""),
    claude: str = Form(""), gemini: str = Form(""), schedule_enabled: str = Form(None),
    schedule_time: str = Form(""), schedule_timezone: str = Form(""), _=Depends(require_auth),
):
    settings_io.write({
        "keywords": _lines(keywords), "locations": _lines(locations),
        "block_companies": _lines(block_companies),
        "remote_ok": bool(remote_ok), "max_age_days": _int(max_age_days, 7),
        "greenhouse": _lines(greenhouse), "lever": _lines(lever), "ashby": _lines(ashby),
        "boards_enabled": bool(boards_enabled),
        "threshold": _int(threshold, 60), "digest_size": _int(digest_size, 10),
        "max_to_score": _int(max_to_score, 25), "claude": claude.strip(), "gemini": gemini.strip(),
        "schedule_enabled": bool(schedule_enabled), "schedule_time": schedule_time.strip() or "08:00",
        "schedule_timezone": schedule_timezone.strip(),
    })
    _reschedule()   # apply any schedule change immediately
    return RedirectResponse("/settings?saved=1", status_code=303)
