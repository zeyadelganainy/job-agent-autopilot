"""FastAPI monitoring console for the autopilot agent (V2).

The dashboard surfaces the agent's work: today's stats, a "Ready to apply" queue, a
triage "Needs attention" queue, and recent run history. It also keeps manual tools
(jobs, ad-hoc generation, docs library, editable tracker, insights, settings).
Password-protected via a /login page (session cookie); HTTP Basic is also accepted so
scripts/tests can authenticate. A "View demo" button opens a no-live-calls sandbox for
recruiters (see jobagent/web/demo.py). Swagger disabled so /docs is the document library.
"""
import base64
import binascii
import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import notify, pipeline, settings_io, tracker, webutil
from ..config import ROOT, env, load_config
from ..scheduler import next_run_time, start_scheduler
from ..store import Store
from . import demo as demoer

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

app = FastAPI(title="JobPilot", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
security = HTTPBasic(auto_error=False)         # we combine it with the session cookie below

UTC_MIN = datetime.min.replace(tzinfo=timezone.utc)
COOKIE = "ja_session"
SESSION_TTL = 7 * 24 * 3600


class LoginRequired(Exception):
    """Raised when a browser request has no valid session — redirected to /login."""


# ---- session cookie (signed, stdlib only — no new dependency) ----
def _secret() -> bytes:
    return (env("SESSION_SECRET") or env("WEB_PASSWORD") or "dev-secret").encode()


def make_session(role: str, ttl: int = SESSION_TTL) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps({"role": role, "exp": int(time.time()) + ttl}).encode()).decode()
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_session(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, _, sig = token.rpartition(".")
    good = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body.encode()))
    except (ValueError, binascii.Error):
        return None
    if data.get("exp", 0) < time.time():
        return None
    return data


def _check_basic(creds: HTTPBasicCredentials | None) -> bool:
    user, pw = env("WEB_USERNAME") or "admin", env("WEB_PASSWORD")
    if not pw:
        raise HTTPException(status_code=500, detail="Set WEB_PASSWORD in .env to use the UI.")
    if creds is None:
        return False
    return (secrets.compare_digest(creds.username, user)
            and secrets.compare_digest(creds.password, pw))


def require_auth(request: Request,
                 creds: HTTPBasicCredentials = Depends(security)) -> dict:
    """Return the session dict ({"role": "user"|"demo"}). Accepts a signed session
    cookie or HTTP Basic; otherwise redirects a browser to /login (or 401s a failed
    Basic attempt)."""
    sess = read_session(request.cookies.get(COOKIE))
    if not sess:
        if creds is not None:
            if _check_basic(creds):
                sess = {"role": "user"}
            else:
                raise HTTPException(status_code=401, detail="Unauthorized",
                                    headers={"WWW-Authenticate": "Basic"})
        else:
            raise LoginRequired()
    request.state.session = sess
    return sess


@app.exception_handler(LoginRequired)
def _login_redirect(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


def _store(sess: dict = None) -> Store:
    if demoer.is_demo(sess):
        return Store(demoer.DEMO_DB)
    return Store(load_config()["paths"]["db"])


def _output_dir() -> Path:
    return (ROOT / load_config()["paths"]["output"])


def _notice_redirect(path: str, msg: str, status_code: int = 303) -> RedirectResponse:
    sep = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{sep}notice={quote(msg)}", status_code=status_code)


def render(request: Request, name: str, ctx: dict = None):
    ctx = dict(ctx or {})
    ctx["request"] = request
    ctx.setdefault("session", getattr(request.state, "session", None))
    ctx.setdefault("notice", request.query_params.get("notice"))
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


def _docfiles(row) -> list[dict]:
    """Parse a job row's stored docs JSON into [{name, path}, …]."""
    try:
        return [{"name": Path(p).name, "path": p} for p in json.loads(row.get("docs") or "[]")]
    except Exception:
        return []


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


# ---- auth pages (login / demo / logout) ----
@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str = None, next: str = "/"):
    if read_session(request.cookies.get(COOKIE)):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html",
                                      {"error": error, "next": next})


@app.post("/login")
def login_submit(request: Request, username: str = Form(""), password: str = Form(""),
                 next: str = Form("/")):
    creds = HTTPBasicCredentials(username=username, password=password)
    if not _check_basic(creds):
        return RedirectResponse("/login?error=1", status_code=303)
    resp = RedirectResponse(next or "/", status_code=303)
    resp.set_cookie(COOKIE, make_session("user"), httponly=True, samesite="lax",
                    max_age=SESSION_TTL)
    return resp


@app.post("/demo")
def enter_demo():
    """Reset + seed the sandbox, then drop the visitor into a demo session."""
    demoer.reset_and_seed(_output_dir())
    resp = _notice_redirect("/", demoer.DEMO_NOTICE)
    resp.set_cookie(COOKIE, make_session("demo"), httponly=True, samesite="lax",
                    max_age=SESSION_TTL)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/tasks/{tid}")
def task_status(tid: str, _=Depends(require_auth)):
    t = dict(TASKS.get(tid, {"status": "unknown"}))
    if t.get("started"):
        t["elapsed"] = round(time.time() - t["started"], 1)
        t.pop("started", None)
    return JSONResponse(t)


# ---- dashboard (agent home) ----
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, task: str = None, sess=Depends(require_auth)):
    s = _store(sess)
    try:
        stats = s.today_stats()
        ready = [dict(r) for r in s.ready_to_apply()]
        attention = [dict(r) for r in s.needs_attention()]
        runs = [dict(r) for r in s.list_runs(8)]
    finally:
        s.close()
    for r in ready:
        r["doc_files"] = _docfiles(r)
    nrt = next_run_time(getattr(app.state, "scheduler", None))
    return render(request, "dashboard.html", {
        "stats": stats, "ready": ready[:12], "attention": attention, "runs": runs,
        "next_run_h": webutil.human_until(nrt),
        "next_run": nrt.strftime("%b %d, %H:%M") if nrt else None, "task": task})


@app.post("/agent/run")
def do_agent_run(sess=Depends(require_auth)):
    """Run one autonomous cycle in the background, then email the digest."""
    if demoer.is_demo(sess):
        s = _store(sess)
        try:
            msg = demoer.run_scan(s, _output_dir())
        finally:
            s.close()
        return _notice_redirect("/", msg)

    def work():
        summary = pipeline.agent_run(load_config())
        try:
            notify.send_email("JobPilot — manual run", pipeline.format_email(summary))
        except Exception as e:
            print(f"[web] run email failed: {e}")
        return {"generated": len(summary["generated"]),
                "attention": len(summary["attention"]), "error": summary["error"]}

    tid = start_task("agent", work)
    return RedirectResponse(f"/?task={tid}", status_code=303)


# ---- jobs (filter / sort / paginate) ----
@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, company: str = "", location: str = "", min_score: str = "",
              max_age: str = "", sort: str = "match", dir: str = "desc",
              page: int = 1, task: str = None, sess=Depends(require_auth)):
    s = _store(sess)
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
def do_pick(job_ids: list[str] = Form(default=[]), sess=Depends(require_auth)):
    if not job_ids:
        return RedirectResponse("/jobs", status_code=303)
    if demoer.is_demo(sess):
        s = _store(sess)
        try:
            msg = demoer.simulate_generate(s, _output_dir(), job_ids)
        finally:
            s.close()
        return _notice_redirect("/", msg)
    tid = start_task("pick",
        lambda: [r["job_id"] for r, _ in pipeline.pick_and_generate(job_ids, load_config())])
    return RedirectResponse(f"/jobs?task={tid}", status_code=303)


@app.post("/jobs/remove")
def jobs_remove(job_ids: list[str] = Form(default=[]), sess=Depends(require_auth)):
    """Dismiss postings: mark 'skipped' so they leave the board and a re-scan
    won't bring them back (the job_id is already known)."""
    if job_ids:
        s = _store(sess)
        try:
            for jid in job_ids:
                s.set_status(jid, "skipped")
        finally:
            s.close()
    return RedirectResponse("/jobs", status_code=303)


# ---- autopilot actions (apply / retry / dismiss) ----
@app.post("/jobs/{job_id}/apply")
def job_apply(job_id: str, sess=Depends(require_auth)):
    """Record that *you* applied (never auto-submits) and open the posting to finish."""
    s = _store(sess)
    try:
        row = s.get(job_id)
        url = (row["url"] if row else "") or ""
        if row:
            s.mark_applied(job_id)
            s.add_application({
                "role": row["title"], "company": row["company"],
                "applied_date": datetime.now().strftime("%Y-%m-%d"), "stage": "Applied",
                "location": row["location"], "notes": "via JobPilot", "url": url})
    finally:
        s.close()
    return RedirectResponse(url or "/", status_code=303)


@app.post("/jobs/{job_id}/retry")
def job_retry(job_id: str, sess=Depends(require_auth)):
    """Clear a triage flag so the job is eligible again (e.g. once an API limit resets)."""
    s = _store(sess)
    try:
        s.retry_job(job_id)
    finally:
        s.close()
    return RedirectResponse("/", status_code=303)


@app.post("/jobs/{job_id}/dismiss")
def job_dismiss(job_id: str, sess=Depends(require_auth)):
    s = _store(sess)
    try:
        s.set_status(job_id, "skipped")
    finally:
        s.close()
    return RedirectResponse("/", status_code=303)


# ---- generate ----
@app.get("/generate", response_class=HTMLResponse)
def generate_form(request: Request, _=Depends(require_auth)):
    return render(request, "generate.html", {"result": None})


@app.post("/generate", response_class=HTMLResponse)
def do_generate(request: Request, source: str = Form(...), title: str = Form(None),
                company: str = Form(None), sess=Depends(require_auth)):
    if demoer.is_demo(sess):
        s = _store(sess)
        try:
            result = demoer.simulate_adhoc(s, _output_dir(), title, company)
        finally:
            s.close()
        return render(request, "generate.html", {"result": result})
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
                 sess=Depends(require_auth)):
    s = _store(sess)
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
def insights_page(request: Request, sess=Depends(require_auth)):
    s = _store(sess)
    try:
        apps = [dict(r) for r in s.list_applications()]
        prepared_rows = [dict(r) for r in s.all_docs()]            # agent-prepared (have docs)
        applied_rows = [dict(r) for r in s.by_status("applied")]   # you marked applied
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

    # Agent activity: documents prepared (by created_at) vs applications you made (applied_at)
    prep_m = Counter(d.strftime("%Y-%m") for d in
                     (webutil.to_dt(r.get("created_at")) for r in prepared_rows) if d)
    appl_m = Counter(d.strftime("%Y-%m") for d in
                     (webutil.to_dt(r.get("applied_at")) for r in applied_rows) if d)
    act_labels = sorted(set(prep_m) | set(appl_m))[-12:]

    return render(request, "insights.html", {
        "stage_labels": [k for k, _ in stage_counts],
        "stage_counts": [c for _, c in stage_counts],
        "m_labels": m_labels, "m_counts": m_counts, "avg": avg,
        "act_labels": act_labels,
        "act_prepared": [prep_m.get(k, 0) for k in act_labels],
        "act_applied": [appl_m.get(k, 0) for k in act_labels],
        "totals": {"apps": len(apps), "companies": companies, "avg": avg,
                   "this_month": months.get(datetime.now().strftime("%Y-%m"), 0)}})


# ---- tracker (editable + paginate) ----
@app.get("/tracker", response_class=HTMLResponse)
def tracker_page(request: Request, stage: str = "", company: str = "",
                 sort: str = "applied", dir: str = "desc", page: int = 1,
                 summary: str = None, sess=Depends(require_auth)):
    tcfg = load_config().get("tracker") or {}
    s = _store(sess)
    try:
        if tcfg.get("auto_ghost"):
            tracker.auto_ghost(s, tcfg.get("ghost_after_weeks", 4))
        allrows = [dict(r) for r in s.list_applications()]
    finally:
        s.close()
    active = sum(1 for r in allrows if tracker.is_active(r["stage"]))
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
        "total": len(allrows), "active": active,
        "f": {"stage": stage, "company": company, "sort": sort, "dir": dir}})


@app.post("/tracker/import", response_class=HTMLResponse)
async def tracker_import(request: Request, file: UploadFile = File(...),
                         sess=Depends(require_auth)):
    content = (await file.read()).decode("utf-8-sig", errors="replace")
    s = _store(sess)
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
                sess=Depends(require_auth)):
    if company or role:
        s = _store(sess)
        try:
            s.add_application(_app_fields(role, company, applied_date, stage, location, notes))
        finally:
            s.close()
    return RedirectResponse("/tracker", status_code=303)


@app.get("/tracker/{app_id}/edit", response_class=HTMLResponse)
def tracker_edit_form(request: Request, app_id: int, sess=Depends(require_auth)):
    s = _store(sess)
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
                      location: str = Form(""), notes: str = Form(""),
                      sess=Depends(require_auth)):
    s = _store(sess)
    try:
        s.update_application(app_id, _app_fields(role, company, applied_date, stage, location, notes))
    finally:
        s.close()
    return RedirectResponse("/tracker", status_code=303)


@app.post("/tracker/{app_id}/delete")
def tracker_delete(app_id: int, sess=Depends(require_auth)):
    s = _store(sess)
    try:
        s.delete_application(app_id)
    finally:
        s.close()
    return RedirectResponse("/tracker", status_code=303)


# ---- settings (edit config.yaml) ----
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str = None, sess=Depends(require_auth)):
    return render(request, "settings.html",
                  {"s": settings_io.read(), "saved": saved,
                   "email_ok": notify.email_configured()})


@app.post("/settings")
def settings_save(
    keywords: str = Form(""), locations: str = Form(""), block_companies: str = Form(""),
    remote_ok: str = Form(None), max_age_days: str = Form(""), greenhouse: str = Form(""),
    lever: str = Form(""), ashby: str = Form(""), boards_enabled: str = Form(None),
    threshold: str = Form(""), digest_size: str = Form(""), max_to_score: str = Form(""),
    agent_enabled: str = Form(None), min_score: str = Form(""), daily_cap: str = Form(""),
    auto_ghost: str = Form(None), ghost_after_weeks: str = Form(""),
    claude: str = Form(""), gemini: str = Form(""), schedule_enabled: str = Form(None),
    schedule_time: str = Form(""), schedule_timezone: str = Form(""),
    sess=Depends(require_auth),
):
    if demoer.is_demo(sess):
        return _notice_redirect("/settings", "Demo mode — settings are read-only here.")
    settings_io.write({
        "keywords": _lines(keywords), "locations": _lines(locations),
        "block_companies": _lines(block_companies),
        "remote_ok": bool(remote_ok), "max_age_days": _int(max_age_days, 7),
        "greenhouse": _lines(greenhouse), "lever": _lines(lever), "ashby": _lines(ashby),
        "boards_enabled": bool(boards_enabled),
        "threshold": _int(threshold, 60), "digest_size": _int(digest_size, 10),
        "max_to_score": _int(max_to_score, 25),
        "agent_enabled": bool(agent_enabled), "min_score": _int(min_score, 80),
        "daily_cap": _int(daily_cap, 5),
        "auto_ghost": bool(auto_ghost), "ghost_after_weeks": _int(ghost_after_weeks, 4),
        "claude": claude.strip(), "gemini": gemini.strip(),
        "schedule_enabled": bool(schedule_enabled), "schedule_time": schedule_time.strip() or "08:00",
        "schedule_timezone": schedule_timezone.strip(),
    })
    _reschedule()   # apply any schedule change immediately
    return RedirectResponse("/settings?saved=1", status_code=303)
