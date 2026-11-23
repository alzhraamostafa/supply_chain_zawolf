"""Outgoing email / webhooks and incoming email.

mode "dry_run" (default): every message is written to outbox/ as an .eml file and logged in ext_outbox.
                          Nothing leaves the machine.
mode "live":              email goes out over SMTP, replies are read over IMAP, webhooks are posted.
Set it in messaging.json ("mode") or with the environment variable AGENT_SEND_MODE=live.
Passwords and tokens come ONLY from environment variables, never from files in the project.
"""
from __future__ import annotations
import email, email.policy, imaplib, json, os, re, smtplib
from email.message import EmailMessage
from email.utils import make_msgid, parsedate_to_datetime

from db import now_utc, tx

HERE = os.path.dirname(os.path.abspath(__file__))


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:80]


class Mailer:
    def __init__(self, cfg: dict, base_dir: str = HERE):
        self.cfg = cfg
        self.mode = os.environ.get("AGENT_SEND_MODE", cfg.get("mode", "dry_run"))
        self.outbox = os.path.join(base_dir, cfg.get("outbox_dir", "outbox"))
        self.inbox = os.path.join(base_dir, cfg.get("inbox_dir", "inbox"))
        self.from_addr = cfg.get("from_address") or "procurement@example.invalid"

    @property
    def live(self) -> bool:
        return self.mode == "live"

    # ------------------------------------------------------------------ outgoing
    def _log(self, con, kind, ref, channel, recipient, subject, body, status, path=None, error=None):
        with tx(con):
            cur = con.execute("INSERT INTO ext_outbox(kind,ref,channel,recipient,subject,body,status,file_path,error,"
                              "created_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (kind, ref, channel, recipient, subject, body, status, path, error, now_utc()))
        return cur.lastrowid

    def _write_eml(self, msg: EmailMessage, ref: str) -> str:
        os.makedirs(self.outbox, exist_ok=True)
        path = os.path.join(self.outbox, f"{now_utc()[:19].replace(':', '')}_{_safe(ref)}.eml")
        with open(path, "wb") as f:
            f.write(msg.as_bytes(policy=email.policy.SMTP))
        return path

    def send_email(self, con, kind, ref, to, subject, body) -> str:
        """Returns the status written to ext_outbox: dry_run | sent | failed."""
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.from_addr, to or "undisclosed", subject
        msg["Message-ID"] = make_msgid(domain="replenishment-agent")
        msg.set_content(body)
        path = self._write_eml(msg, ref)
        if not self.live or not to:
            self._log(con, kind, ref, "email", to, subject, body, "dry_run", path)
            return "dry_run"
        s = self.cfg.get("smtp", {})
        try:
            with smtplib.SMTP(s["host"], int(s.get("port", 587)), timeout=30) as smtp:
                if s.get("starttls", True):
                    smtp.starttls()
                if s.get("user"):
                    smtp.login(s["user"], os.environ.get(s.get("password_env", "AGENT_SMTP_PASSWORD"), ""))
                smtp.send_message(msg)
        except Exception as e:                          # keep the record, report the failure
            self._log(con, kind, ref, "email", to, subject, body, "failed", path, str(e))
            return "failed"
        self._log(con, kind, ref, "email", to, subject, body, "sent", path)
        return "sent"

    def save_manual(self, con, kind, ref, where, subject, body) -> str:
        """For suppliers who only accept a website form or a phone call: the text is prepared for a person."""
        os.makedirs(self.outbox, exist_ok=True)
        path = os.path.join(self.outbox, f"{now_utc()[:19].replace(':', '')}_{_safe(ref)}_MANUAL.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"SUBMIT MANUALLY AT: {where or '(no form URL configured)'}\nSUBJECT: {subject}\n\n{body}\n")
        self._log(con, kind, ref, "manual", where, subject, body, "manual", path)
        return path

    def post_webhook(self, con, kind, ref, url, payload: dict) -> str:
        body = json.dumps(payload, ensure_ascii=False)
        if not self.live or not url:
            self._log(con, kind, ref, "webhook", "(webhook)", kind, body, "dry_run")
            return "dry_run"
        import requests
        try:
            requests.post(url, json=payload, timeout=15).raise_for_status()
        except Exception as e:
            self._log(con, kind, ref, "webhook", "(webhook)", kind, body, "failed", error=str(e))
            return "failed"
        self._log(con, kind, ref, "webhook", "(webhook)", kind, body, "sent")
        return "sent"

    # ------------------------------------------------------------------ incoming
    @staticmethod
    def _text_of(msg) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and not part.get_filename():
                    return part.get_content()
            for part in msg.walk():                      # html only: strip the tags
                if part.get_content_type() == "text/html":
                    from bs4 import BeautifulSoup
                    return BeautifulSoup(part.get_content(), "html.parser").get_text("\n")
            return ""
        return msg.get_content()

    def _parse(self, raw: bytes, key: str) -> dict:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        try:
            when = parsedate_to_datetime(msg["Date"]).strftime("%Y-%m-%dT%H:%M:%SZ") if msg["Date"] else now_utc()
        except Exception:
            when = now_utc()
        return dict(key=msg["Message-ID"] or key, subject=str(msg["Subject"] or ""), sender=str(msg["From"] or ""),
                    date=when, text=self._text_of(msg))

    def fetch(self) -> list[dict]:
        """Live: unread messages from IMAP. Dry run: every .eml file dropped in inbox/ (for testing replies)."""
        out = []
        if self.live and self.cfg.get("imap", {}).get("host"):
            i = self.cfg["imap"]
            box = imaplib.IMAP4_SSL(i["host"])
            box.login(i["user"], os.environ.get(i.get("password_env", "AGENT_IMAP_PASSWORD"), ""))
            box.select(i.get("folder", "INBOX"))
            _, ids = box.search(None, "UNSEEN")
            for num in ids[0].split():
                _, data = box.fetch(num, "(RFC822)")
                out.append(self._parse(data[0][1], f"imap:{num.decode()}"))
            box.logout()
            return out
        if os.path.isdir(self.inbox):
            for name in sorted(os.listdir(self.inbox)):
                if name.lower().endswith(".eml"):
                    with open(os.path.join(self.inbox, name), "rb") as f:
                        out.append(self._parse(f.read(), f"file:{name}"))
        return out
