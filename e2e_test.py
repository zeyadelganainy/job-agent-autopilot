#!/usr/bin/env python3
"""Controlled end-to-end test of the loop, bounded so it won't burn free-tier quota.

Ingest -> score a small capped batch (Gemini fallback) -> push digest to Telegram
-> generate docs for the top job (exercises generate.py) -> send the resume back.

Usage:  python e2e_test.py [N]      # N = how many jobs to score (default 4)

Not part of the app — a throwaway harness for verifying the wiring live.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows console is cp1252

from jobagent.config import load_config, load_master, load_profile, load_samples
from jobagent.generate import generate
from jobagent.ingest.runner import gather
from jobagent.notify import send_message
from jobagent.pipeline import format_digest
from jobagent.score import score_job
from jobagent.store import Store

N = int(sys.argv[1]) if len(sys.argv) > 1 else 4


def main():
    cfg = load_config()
    profile = load_profile(cfg)
    store = Store(cfg["paths"]["db"])
    models = cfg["models"]

    print(f"== INGEST ==  (sources: {cfg['sources']['ats']})")
    jobs = gather(cfg)
    batch = jobs[:N]
    print(f"Scoring a capped batch of {len(batch)} (of {len(jobs)} matched).")

    print("\n== SCORE ==  (Claude unset -> Gemini fallback)")
    digest = []
    for j in batch:
        if not store.upsert_job(j):
            print(f"  - {j.job_id} already in db, skipping")
            continue
        score_job(j, profile, models)
        store.save_score(j)
        store.set_status(j.job_id, "sent")        # force into digest for the test
        digest.append(j.to_dict())
        print(f"  + {j.job_id}  {j.score:>3}%  {j.title[:50]} @ {j.company}")

    digest.sort(key=lambda d: d["score"] or 0, reverse=True)

    print("\n== DIGEST -> TELEGRAM ==")
    text = format_digest(digest)
    print(text)
    if digest:
        send_message(text)
        print("(sent digest to Telegram)")

    if not digest:
        print("\nNo jobs scored this run (all already in db?). "
              "Delete jobs.db to re-run from scratch.")
        return

    top = digest[0]
    print(f"\n== GENERATE (top job {top['job_id']}) ==")
    samples = load_samples(cfg)
    master = load_master(cfg)
    try:
        paths = generate(store.get(top["job_id"]), profile, samples, master,
                         models, cfg["paths"])
    except Exception as e:
        print(f"  generation failed (likely Gemini 503): {e}")
        print("\nIngest/score/digest validated; re-run later for the doc step.")
        return
    store.record_docs(top["job_id"], paths)
    for p in paths:
        print(f"  wrote {p}")

    print("\n== SEND DOCS -> TELEGRAM ==")
    import os
    import requests
    from jobagent.config import env
    token, chat_id = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    for p in paths:
        with open(p, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": chat_id}, files={"document": (os.path.basename(p), f)},
                timeout=30,
            )
        print(f"  sent {os.path.basename(p)}: {'ok' if r.ok else r.text}")

    print("\nDONE — check your Telegram for the digest + 3 files.")


if __name__ == "__main__":
    main()
