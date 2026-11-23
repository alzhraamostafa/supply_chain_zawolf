"""Alerts to people: restock needed, quote received, delivery late.

Channels (configure in messaging.json -> "alerts"):
  console   always
  email     alerts.email_to = ["buyer@company.com", ...]
  webhook   Slack / Microsoft Teams / Google Chat incoming-webhook URL in env var alerts.webhook_url_env
  telegram  bot token in env var alerts.telegram_token_env, chat id in alerts.telegram_chat_id
The same alert is not repeated within alerts.repeat_hours, unless it gets worse (warning -> critical).
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone

from db import now_utc, tx

RANK = {"info": 0, "warning": 1, "critical": 2}


class Notifier:
    def __init__(self, con, mailer, cfg: dict, echo=print):
        self.con, self.mailer, self.echo = con, mailer, echo
        self.cfg = cfg.get("alerts", {})

    def _recent(self, key):
        hours = float(self.cfg.get("repeat_hours", 24))
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
        row = self.con.execute("SELECT severity FROM ext_notifications WHERE dedupe_key=? AND created_at_utc>=? "
                               "ORDER BY notification_id DESC LIMIT 1", (key, since)).fetchone()
        return row[0] if row else None

    def notify(self, kind, key, severity, subject, body, force=False) -> bool:
        """Returns True if the alert went out, False if it was suppressed as a repeat."""
        prev = self._recent(key)
        if prev is not None and not force and RANK[severity] <= RANK.get(prev, 0):
            return False
        channels = ["console"]
        self.echo(f"[ALERT {severity.upper()}] {subject}")
        for to in self.cfg.get("email_to", []):
            self.mailer.send_email(self.con, f"alert:{kind}", key, to, f"[{severity.upper()}] {subject}", body)
            channels.append(f"email:{to}")
        hook = os.environ.get(self.cfg.get("webhook_url_env", "AGENT_ALERT_WEBHOOK"))
        if hook or self.cfg.get("webhook_always_log"):
            self.mailer.post_webhook(self.con, f"alert:{kind}", key, hook, {"text": f"*{subject}*\n{body}"})
            channels.append("webhook")
        token = os.environ.get(self.cfg.get("telegram_token_env", "AGENT_TELEGRAM_TOKEN"))
        chat = self.cfg.get("telegram_chat_id")
        if token and chat:
            self.mailer.post_webhook(self.con, f"alert:{kind}", key,
                                     f"https://api.telegram.org/bot{token}/sendMessage",
                                     {"chat_id": chat, "text": f"{subject}\n{body}"})
            channels.append("telegram")
        with tx(self.con):
            self.con.execute("INSERT INTO ext_notifications(dedupe_key,kind,severity,subject,body,channels,created_at_utc)"
                             " VALUES (?,?,?,?,?,?,?)", (key, kind, severity, subject, body, ",".join(channels), now_utc()))
        return True

    # ------------------------------------------------------------------ typed alerts
    def restock(self, result: dict) -> int:
        """One alert per material that needs ordering, plus one summary line with the purchase request."""
        sent = 0
        for a in result["alerts"]:
            qty = f"{a.order_qty / 1000:,.0f} kg" if a.unit == "g" else f"{a.order_qty:,} pcs"
            body = (f"Material: {a.material}\nStock on hand covers {a.cover_days:.1f} days; supplier lead time "
                    f"{a.lead_days} days.\nExpected stock-out: {a.stockout_date}. Order by: {a.order_by}.\n"
                    f"Suggested order: {qty} from {a.supplier_name or a.supplier_id}.\n"
                    f"Purchase request: {result.get('purchase_request_number') or '(existing open request)'}")
            sent += self.notify("restock", f"restock:{a.material}", a.severity,
                                f"Restock {a.material} ({a.severity}): order by {a.order_by}", body)
        return sent

    def late(self, items: list[dict]) -> int:
        sent = 0
        for it in items:
            sev = "critical" if it.get("days_late", 0) >= 3 else "warning"
            sent += self.notify("delivery", f"late:{it['po_number']}:{it['reason']}", sev,
                                f"{it['po_number']} ({it['supplier_id']}): {it['reason']}", it["detail"])
        return sent

    def quote(self, rfq_number, supplier, n_lines):
        return self.notify("quote", f"quote:{rfq_number}", "info",
                           f"Quote received for {rfq_number} from {supplier}",
                           f"{n_lines} priced line(s) extracted. A person must check and confirm them "
                           f"before they are used in a purchase order.", force=True)
