"""Scheduler timezone regression test.

The daily run must fire at the configured local time in the configured timezone,
not at that wall-clock time in the machine's local zone. A pre-built CronTrigger
defaults to the host's local zone, so on a UTC VM "08:00 America/Vancouver" would
otherwise fire at 08:00 UTC (= 1 AM Vancouver). See jobagent/scheduler.py.
"""
from zoneinfo import ZoneInfo

from jobagent.scheduler import start_scheduler


def _shutdown(sc):
    if sc:
        sc.shutdown(wait=False)


def test_trigger_uses_configured_timezone():
    cfg = {"schedule": {"enabled": True, "time": "08:00", "timezone": "America/Vancouver"}}
    sc = start_scheduler(cfg)
    try:
        job = sc.get_job("daily_run")
        # The trigger itself must carry the configured zone, not the host's local zone.
        assert job.trigger.timezone == ZoneInfo("America/Vancouver")
        # And the next fire must land at 08:00 local wall-clock time.
        assert job.next_run_time.hour == 8 and job.next_run_time.minute == 0
        assert str(job.next_run_time.tzinfo) == "America/Vancouver"
    finally:
        _shutdown(sc)


def test_trigger_uses_configured_time():
    """The fire time comes from config `schedule.time`, not a hardcoded 08:00."""
    cfg = {"schedule": {"enabled": True, "time": "14:30", "timezone": "America/Toronto"}}
    sc = start_scheduler(cfg)
    try:
        job = sc.get_job("daily_run")
        assert job.trigger.timezone == ZoneInfo("America/Toronto")
        assert job.next_run_time.hour == 14 and job.next_run_time.minute == 30
    finally:
        _shutdown(sc)


def test_disabled_schedule_returns_none():
    assert start_scheduler({"schedule": {"enabled": False}}) is None
