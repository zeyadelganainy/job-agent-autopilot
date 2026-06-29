#!/usr/bin/env python3
"""Launch the v1.1 web UI:  python run_web.py

Reads host/port from config.yaml `web:`. Log in with WEB_USERNAME / WEB_PASSWORD (.env).
"""
import uvicorn

from jobagent.config import load_config

if __name__ == "__main__":
    web = load_config().get("web") or {}
    host = web.get("host", "127.0.0.1")
    port = int(web.get("port", 8000))
    # 0.0.0.0 means "listen on all interfaces" — it is NOT a browsable address.
    shown = "localhost" if host in ("0.0.0.0", "::") else host
    print(f"\n  job-agent web UI → open http://{shown}:{port}"
          f"   (on this machine; from another device use this PC's LAN IP)")
    print("  log in with WEB_USERNAME / WEB_PASSWORD from your .env,")
    print("  or click “View the demo” for a no-live-calls sandbox.\n")
    uvicorn.run("jobagent.web.app:app", host=host, port=port)
