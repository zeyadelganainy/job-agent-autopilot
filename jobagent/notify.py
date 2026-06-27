"""Email notifications (V2). Pushes the agent's run digest to you via SMTP (BYOK).

Configure in .env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_FROM, EMAIL_TO.
(Gmail: host smtp.gmail.com, port 587, and an App Password as SMTP_PASS.)
If SMTP isn't configured, sending is a logged no-op so a run never crashes on email.
"""
import smtplib
from email.message import EmailMessage

from .config import env


def email_configured() -> bool:
    return bool(env("SMTP_HOST") and env("EMAIL_TO"))


def send_email(subject: str, html: str) -> bool:
    """Send an HTML email via SMTP + STARTTLS. Returns True if sent, False if unconfigured."""
    host, to = env("SMTP_HOST"), env("EMAIL_TO")
    if not (host and to):
        print("[notify] email not configured (set SMTP_HOST + EMAIL_TO in .env); skipping")
        return False
    port = int(env("SMTP_PORT") or 587)
    user, pw = env("SMTP_USER"), env("SMTP_PASS")
    sender = env("EMAIL_FROM") or user or to

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content("This digest is best viewed as HTML.")
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(host, port, timeout=30) as s:
        s.ehlo()
        try:
            s.starttls()
            s.ehlo()
        except smtplib.SMTPException:
            pass  # server without STARTTLS support — proceed unencrypted (rare)
        if user and pw:
            s.login(user, pw)
        s.send_message(msg)
    print(f"[notify] emailed '{subject}' to {to}")
    return True
