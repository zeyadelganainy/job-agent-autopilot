"""Embedded daily scheduler for the autopilot agent.

Runs the full autonomous cycle (pipeline.agent_run) at a configured local time and emails
you the digest. Active while the web app process is running (it stays up on the VM).
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import tracker
from .config import load_config
from .notify import send_email
from .pipeline import agent_run, format_email, format_digest, pending, scan
from .store import Store


def _daily_run():
    cfg = load_config()
    tcfg = cfg.get("tracker") or {}
    if tcfg.get("auto_ghost"):
        st = Store(cfg["paths"]["db"])
        try:
            n = tracker.auto_ghost(st, tcfg.get("ghost_after_weeks", 4))
            if n:
                print(f"[scheduler] auto-ghosted {n} stale application(s)")
        finally:
            st.close()
    agent_on = (cfg.get("agent") or {}).get("enabled", True)
    print("[scheduler] running daily agent…" if agent_on else "[scheduler] running daily scan…")
    try:
        if agent_on:
            summary = agent_run(cfg)
            send_email("JobPilot — daily run", format_email(summary))
        else:                                  # agent disabled → scan-only digest
            scan(cfg)
            send_email("JobPilot — new matches", format_digest(pending(cfg)))
        print("[scheduler] run complete; digest emailed")
    except Exception as e:
        print(f"[scheduler] run failed: {e}")
        try:
            send_email("JobPilot — run failed", f"<p>The scheduled run failed:</p><p>{e}</p>")
        except Exception:
            pass


def start_scheduler(cfg=None):
    """Start and return a BackgroundScheduler, or None if scheduling is disabled."""
    cfg = cfg or load_config()
    sc = cfg.get("schedule") or {}
    if not sc.get("enabled"):
        return None

    tz = None
    name = sc.get("timezone")
    if name:
        try:
            from zoneinfo import ZoneInfo  # needs `tzdata` on Windows (in requirements)
            tz = ZoneInfo(name)
        except Exception as e:
            print(f"[scheduler] timezone '{name}' unavailable ({e}); using system local time")

    hh, mm = (str(sc.get("time", "08:00")).split(":") + ["0"])[:2]
    scheduler = BackgroundScheduler(timezone=tz) if tz else BackgroundScheduler()
    scheduler.add_job(_daily_run, CronTrigger(hour=int(hh), minute=int(mm)),
                      id="daily_run", replace_existing=True)
    scheduler.start()
    print(f"[scheduler] daily run scheduled at {hh}:{mm} {sc.get('timezone') or 'UTC'}")
    return scheduler


def next_run_time(scheduler):
    if not scheduler:
        return None
    job = scheduler.get_job("daily_run")
    return job.next_run_time if job else None
