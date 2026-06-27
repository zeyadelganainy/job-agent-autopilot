"""Send a one-off message to your Telegram chat (used by run_scan.py)."""
import requests

from .config import env


def send_message(text: str):
    token = env("TELEGRAM_BOT_TOKEN", required=True)
    chat_id = env("TELEGRAM_CHAT_ID", required=True)
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=20,
    )
    if not resp.ok:
        print(f"[notify] telegram error: {resp.text}")
