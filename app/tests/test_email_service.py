from app import email_service


class FakeSMTP:
    calls = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.started_tls = False
        FakeSMTP.calls.append(("init", self.__class__.__name__, host, port, timeout, context is not None))

    def __enter__(self):
        FakeSMTP.calls.append(("enter", self.__class__.__name__))
        return self

    def __exit__(self, exc_type, exc, tb):
        FakeSMTP.calls.append(("exit", self.__class__.__name__))

    def ehlo(self):
        FakeSMTP.calls.append(("ehlo", self.__class__.__name__))

    def starttls(self, context=None):
        self.started_tls = True
        FakeSMTP.calls.append(("starttls", self.__class__.__name__, context is not None))

    def login(self, username, password):
        FakeSMTP.calls.append(("login", username, password))

    def sendmail(self, from_addr, recipients, message):
        FakeSMTP.calls.append(("sendmail", from_addr, tuple(recipients), bool(message)))


class FakeSMTPSSL(FakeSMTP):
    pass


def _configure_common(monkeypatch, port, use_ssl, use_starttls):
    FakeSMTP.calls = []
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", FakeSMTPSSL)
    monkeypatch.setattr(email_service.settings, "SMTP_HOST", "mail.example.com")
    monkeypatch.setattr(email_service.settings, "SMTP_PORT", port)
    monkeypatch.setattr(email_service.settings, "SMTP_TIMEOUT", 120)
    monkeypatch.setattr(email_service.settings, "SMTP_USE_SSL", use_ssl)
    monkeypatch.setattr(email_service.settings, "SMTP_USE_STARTTLS", use_starttls)
    monkeypatch.setattr(email_service.settings, "SMTP_USERNAME", "sender@example.com")
    monkeypatch.setattr(email_service.settings, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(email_service.settings, "EMAIL_FROM", "sender@example.com")
    monkeypatch.setattr(email_service.settings, "EMAIL_RECIPIENTS", ["receiver@example.com"])


def test_port_465_uses_smtp_ssl(monkeypatch):
    _configure_common(monkeypatch, port=465, use_ssl=True, use_starttls=False)

    assert email_service.send_report_with_attachments("<p>Hello</p>", "Subject", None) is True

    assert ("init", "FakeSMTPSSL", "mail.example.com", 465, 120, True) in FakeSMTP.calls
    assert not any(call[0] == "starttls" for call in FakeSMTP.calls)
    assert any(call[0] == "sendmail" for call in FakeSMTP.calls)


def test_port_587_uses_starttls(monkeypatch):
    _configure_common(monkeypatch, port=587, use_ssl=False, use_starttls=True)

    assert email_service.send_report_with_attachments("<p>Hello</p>", "Subject", None) is True

    assert ("init", "FakeSMTP", "mail.example.com", 587, 120, False) in FakeSMTP.calls
    assert any(call[0] == "starttls" for call in FakeSMTP.calls)
    assert any(call[0] == "sendmail" for call in FakeSMTP.calls)
