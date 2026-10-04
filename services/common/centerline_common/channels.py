"""The two notification channels (SDD §8, ADR-0023): Teams through a Power Automate flow, email through
the plant's SMTP relay. The notifier sends with them; the api checks the relay with them.

Each send returns an Outcome: whether the provider took the message, and what it said. What it
said is kept with the attempt, so it never contains a secret. The flow's URL carries its
signature, so it never appears in an outcome or a log.
"""

from __future__ import annotations

import json
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from email.utils import formatdate


@dataclass(frozen=True)
class Outcome:
    ok: bool
    response: str  # trimmed, never a secret


def _trim(text: str, n: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


class Teams:
    """POST the delivery's payload to the flow's HTTP trigger. Any 2xx (Power Automate answers 202) is Delivered.

    A timeout after sending leaves the outcome unknown: it's retried with the same dedup key (SDD §8)."""

    def __init__(self, url: str, timeout_s: float = 15):
        self.url, self.timeout_s = url, timeout_s
        parts = urllib.parse.urlsplit(url)
        self.where = f"{parts.scheme}://{parts.hostname or '?'}"  # what may be said about it: no path, no signature

    def _safe(self, text: str) -> str:
        return _trim(text.replace(self.url, self.where).replace(urllib.parse.urlsplit(self.url).query, "…"))

    def send(self, payload: dict) -> Outcome:
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "Centerline-notifier"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                return Outcome(200 <= r.status < 300, f"HTTP {r.status} from {self.where}")
        except urllib.error.HTTPError as e:
            body = e.read(200).decode("utf-8", "replace") if e.fp else ""
            return Outcome(False, self._safe(f"HTTP {e.code} {e.reason} from {self.where} {body}"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            return Outcome(False, self._safe(f"{self.where}: {getattr(e, 'reason', e)}"))


class Email:
    """One message per recipient through the relay. Submitted = 250 after the DATA body (NOT-06).

    A connection dropped before that 250 is retried with the same Message-ID. After it the message
    is never sent again, even if closing the connection fails."""

    def __init__(self, cfg: dict):
        self.host, self.port = cfg["host"], int(cfg.get("port") or 25)
        self.security = cfg.get("security") or "none"  # none | starttls | tls
        self.username, self.password = cfg.get("username") or "", cfg.get("password") or ""
        self.sender = cfg["sender"]
        self.timeout_s = float(cfg.get("timeout_s", 20))

    def _connect(self) -> smtplib.SMTP:
        if self.security == "tls":
            return smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout_s, context=ssl.create_default_context())
        smtp = smtplib.SMTP(self.host, self.port, timeout=self.timeout_s)
        if self.security == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        return smtp

    def message(self, to: str, subject: str, body: str, message_id: str) -> bytes:
        m = EmailMessage(policy=SMTP_POLICY)
        m["From"], m["To"], m["Subject"] = self.sender, to, subject
        m["Message-ID"], m["Date"] = message_id, formatdate(usegmt=True)
        m["Auto-Submitted"] = "auto-generated"
        m.set_content(body, cte="quoted-printable")
        return m.as_bytes()

    def check(self) -> Outcome:
        """Connect, greet and sign in, without sending anything (the Configuration page's test)."""
        try:
            smtp = self._connect()
            try:
                code, resp = smtp.ehlo()
                if self.username:
                    smtp.login(self.username, self.password)
                return Outcome(True, _trim(f"{self.host}:{self.port} answered {code} {resp.decode('utf-8', 'replace')}"))
            finally:
                try:
                    smtp.quit()
                except (smtplib.SMTPException, OSError):
                    pass
        except smtplib.SMTPResponseException as e:
            return Outcome(False, _trim(f"{e.smtp_code} {e.smtp_error.decode('utf-8', 'replace')}"))
        except (smtplib.SMTPException, OSError, ssl.SSLError) as e:
            return Outcome(False, _trim(f"{self.host}:{self.port}: {e}"))

    def send(self, to: str, subject: str, body: str, message_id: str) -> Outcome:
        data = self.message(to, subject, body, message_id)
        try:
            smtp = self._connect()
        except (smtplib.SMTPException, OSError, ssl.SSLError) as e:
            return Outcome(False, _trim(f"{self.host}:{self.port}: {e}"))
        outcome = Outcome(False, "not sent")
        try:
            smtp.ehlo()
            if self.username:
                smtp.login(self.username, self.password)
            code, resp = smtp.mail(self.sender)
            if code != 250:
                outcome = Outcome(False, _trim(f"MAIL FROM refused: {code} {resp.decode('utf-8', 'replace')}"))
            else:
                code, resp = smtp.rcpt(to)
                if code not in (250, 251):
                    outcome = Outcome(False, _trim(f"{to} refused: {code} {resp.decode('utf-8', 'replace')}"))
                else:
                    code, resp = smtp.data(data)
                    outcome = Outcome(code == 250, _trim(f"{'' if code == 250 else 'DATA refused: '}{code} "
                                                         f"{resp.decode('utf-8', 'replace')}"))
        except smtplib.SMTPResponseException as e:
            outcome = Outcome(False, _trim(f"{e.smtp_code} {e.smtp_error.decode('utf-8', 'replace')}"))
        except (smtplib.SMTPException, OSError, ssl.SSLError) as e:
            outcome = Outcome(False, _trim(f"{self.host}:{self.port}: {e}"))
        finally:
            try:
                smtp.quit()
            except (smtplib.SMTPException, OSError):
                smtp.close()  # after a 250 the message stays submitted all the same (NOT-06)
        return outcome
