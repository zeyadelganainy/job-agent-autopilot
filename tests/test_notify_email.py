from jobagent import notify, pipeline


def test_format_email_sections():
    summary = {"scanned": 10, "scored": 8, "matched": 3,
               "generated": [{"title": "Dev", "company": "Acme", "score": 90, "url": "http://a"}],
               "attention": [{"title": "WD Role", "company": "Beta", "reason": "Manual portal",
                              "url": "http://b", "kind": "manual_portal"}],
               "error": None}
    html = pipeline.format_email(summary)
    assert "Ready to apply" in html and "Dev" in html
    assert "Needs your attention" in html and "Manual portal" in html
    assert "Scanned 10" in html


def test_send_email_unconfigured(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("EMAIL_TO", raising=False)
    assert notify.send_email("s", "<p>x</p>") is False


def test_send_email_sends(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("EMAIL_TO", "me@test")
    monkeypatch.setenv("SMTP_USER", "u")
    monkeypatch.setenv("SMTP_PASS", "p")
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=30):
            sent["host"], sent["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, u, p):
            sent["login"] = (u, p)

        def send_message(self, msg):
            sent["subject"] = msg["Subject"]

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    assert notify.send_email("Hello", "<p>hi</p>") is True
    assert sent["host"] == "smtp.test" and sent["subject"] == "Hello"
    assert sent["login"] == ("u", "p")
