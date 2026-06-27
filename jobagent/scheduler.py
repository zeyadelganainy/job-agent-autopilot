"""Embedded daily-scan scheduler for the web app.

Runs pipeline.scan at a configured local time and pushes the digest to Telegram via
the existing notify channel. Only active while the web app process is running.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import load_config
from .notify import send_message
from .pipeline import format_digest, pending, scan


def _daily_scan():
    cfg = load_config()
    print("[scheduler] running daily scan…")
    try:
        scan(cfg)
    except Exception as e:
        print(f"[scheduler] scan failed: {e}")
        try:
            send_message(f"Scheduled scan failed — {e}")
        except Exception:
            pass
        return
    try:
        send_message(format_digest(pending(cfg)))
        print("[scheduler] pushed digest to Telegram")
    except Exception as e:
        print(f"[scheduler] digest push failed: {e}")


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
    scheduler.add_job(_daily_scan, CronTrigger(hour=int(hh), minute=int(mm)),
                      id="daily_scan", replace_existing=True)
    scheduler.start()
    print(f"[scheduler] daily scan scheduled at {hh}:{mm} {sc.get('timezone') or 'UTC'}")
    return scheduler


def next_run_time(scheduler):
    if not scheduler:
        return None
    job = scheduler.get_job("daily_scan")
    return job.next_run_time if job else None
