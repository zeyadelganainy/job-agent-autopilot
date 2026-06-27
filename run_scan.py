#!/usr/bin/env python3
"""One-off scan: ingest -> score -> push a digest to your Telegram.

Run this on a schedule (cron / Task Scheduler) for a daily digest, or call /scan
from the bot. Then reply to the digest in Telegram with `/pick <numbers>`.
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")   # Windows console is cp1252
except Exception:
    pass

from jobagent.notify import send_message
from jobagent.pipeline import format_digest, pending, scan

if __name__ == "__main__":
    try:
        scan()                   # ingest -> score -> mark matches 'sent'
    except Exception as e:
        print(f"Scan failed — {e}")
        raise SystemExit(1)
    jobs = pending()             # everything awaiting your decision, numbered
    text = format_digest(jobs)
    print(text)
    try:
        send_message(text)
        print(f"\nPushed {len(jobs)} pending job(s) to Telegram.")
    except Exception as e:
        print(f"\nCould not push to Telegram: {e}")
