"""Append-only audit log. Every component writes one row per action."""
import sqlite3
import threading
from datetime import datetime, timezone

APPROVAL_STATUSES = ("not_required", "pending", "approved", "rejected")

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    input_ref TEXT,
    output_ref TEXT,
    approval_status TEXT NOT NULL
        CHECK (approval_status IN ('not_required', 'pending', 'approved', 'rejected'))
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


class AuditLog:
    def __init__(self, path: str = ":memory:"):
        self.con = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self.con.executescript(SCHEMA)
        
    def close(self) -> None:
        self.con.close()

    def record(self, actor, action, input_ref=None, output_ref=None,
               approval_status="not_required") -> int:
        if not actor or not action:
            raise ValueError("actor and action are required")
        if approval_status not in APPROVAL_STATUSES:
            raise ValueError(f"approval_status must be one of {APPROVAL_STATUSES}")
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            cur = self.con.execute(
                "INSERT INTO audit_log (ts, actor, action, input_ref, output_ref, approval_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ts, actor, action, input_ref, output_ref, approval_status))
            self.con.commit()
            return cur.lastrowid

    def entries(self, actor=None) -> list[dict]:
        sql = "SELECT id, ts, actor, action, input_ref, output_ref, approval_status FROM audit_log"
        args = ()
        if actor:
            sql += " WHERE actor = ?"
            args = (actor,)
        with self._lock:
            cur = self.con.execute(sql + " ORDER BY id", args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]