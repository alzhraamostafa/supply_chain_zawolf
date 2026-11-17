import sqlite3
import pytest
from common.audit import AuditLog


def test_record_and_read_back():
    log = AuditLog()
    row_id = log.record("demand_forecast", "forecast_created",
                        input_ref="fact_commercial_demand_m5", output_ref="env-1")
    entries = log.entries()
    assert row_id == 1 and len(entries) == 1
    assert entries[0]["approval_status"] == "not_required"
    assert entries[0]["ts"]


def test_filter_by_actor():
    log = AuditLog()
    log.record("demand_forecast", "forecast_created")
    log.record("procurement_agent", "rfq_drafted", approval_status="pending")
    assert [e["action"] for e in log.entries("procurement_agent")] == ["rfq_drafted"]


def test_update_is_blocked():
    log = AuditLog()
    log.record("a", "x")
    with pytest.raises(sqlite3.DatabaseError):
        log.con.execute("UPDATE audit_log SET actor = 'z' WHERE id = 1")


def test_delete_is_blocked():
    log = AuditLog()
    log.record("a", "x")
    with pytest.raises(sqlite3.DatabaseError):
        log.con.execute("DELETE FROM audit_log WHERE id = 1")


def test_invalid_approval_status_rejected():
    with pytest.raises(ValueError):
        AuditLog().record("a", "x", approval_status="maybe")


def test_actor_and_action_required():
    with pytest.raises(ValueError):
        AuditLog().record("", "x")
