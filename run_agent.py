#!/usr/bin/env python3
"""Run one autonomous agent cycle now, then email the digest.

The deployed app runs this automatically via the in-process scheduler; use this for a
manual/cron run. Scans -> scores -> auto-generates docs for the best matches (never
applies), flags anything needing you, and emails the summary.
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")   # Windows console is cp1252
except Exception:
    pass

from jobagent.notify import send_email
from jobagent.pipeline import agent_run, format_email

if __name__ == "__main__":
    summary = agent_run()
    print(f"scanned={summary['scanned']} matched={summary['matched']} "
          f"prepared={len(summary['generated'])} needs_attention={len(summary['attention'])}"
          + (f" error={summary['error']}" if summary["error"] else ""))
    try:
        sent = send_email("job-agent — daily run", format_email(summary))
        print("emailed digest" if sent else "email not configured; skipped")
    except Exception as e:
        print(f"could not email digest: {e}")
