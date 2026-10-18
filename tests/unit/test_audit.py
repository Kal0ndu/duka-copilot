"""Tests for db/audit.py: hash-chained append-only event log."""
import sqlite3
import tempfile
import os

import pytest

from db.audit import log_event, get_recent_events, verify_audit


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE audit_log (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          business_id INTEGER,
          actor TEXT NOT NULL CHECK (actor IN ('agent','owner','guard','system')),
          event_type TEXT NOT NULL,
          tool TEXT,
          tier TEXT,
          decision TEXT,
          entity_type TEXT,
          entity_id INTEGER,
          details_json TEXT NOT NULL,
          prev_hash TEXT NOT NULL,
          hash TEXT NOT NULL
        );
        CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
        CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
        CREATE TRIGGER audit_chain_continuity BEFORE INSERT ON audit_log
        BEGIN
          SELECT RAISE(ABORT, 'audit_log: prev_hash does not match chain head')
          WHERE NEW.prev_hash <> COALESCE((SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1), 'GENESIS');
        END;
    """)
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


class TestLogEvent:
    def test_first_event_chains_to_genesis(self, db_path):
        seq = log_event(db_path, actor="agent", event_type="TOOL_CALL", business_id=1, tool="forecast_balance")
        assert seq == 1
        events = get_recent_events(db_path, business_id=1)
        assert len(events) == 1
        assert events[0].prev_hash == "GENESIS"

    def test_events_chain_to_previous_hash(self, db_path):
        log_event(db_path, actor="agent", event_type="TOOL_CALL", business_id=1)
        log_event(db_path, actor="guard", event_type="INPUT_BLOCKED", business_id=1)
        events = get_recent_events(db_path, business_id=1, limit=10)
        # newest first
        assert events[0].prev_hash == events[1].hash

    def test_details_round_trip_as_json(self, db_path):
        log_event(db_path, actor="agent", event_type="TOOL_CALL", business_id=1,
                  details={"args": {"amount_minor": 50000}})
        events = get_recent_events(db_path, business_id=1)
        assert events[0].details == {"args": {"amount_minor": 50000}}

    def test_invalid_actor_fails_closed(self, db_path):
        # actor must be one of agent/owner/guard/system — anything else must
        # not silently write a corrupt row.
        seq = log_event(db_path, actor="attacker", event_type="TOOL_CALL", business_id=1)
        assert seq is None


class TestVerifyAudit:
    def test_empty_log_is_valid(self, db_path):
        result = verify_audit(db_path)
        assert result["valid"] is True
        assert result["checked"] == 0

    def test_untampered_chain_is_valid(self, db_path):
        for i in range(5):
            log_event(db_path, actor="agent", event_type="TOOL_CALL", business_id=1, tool=f"tool_{i}")
        result = verify_audit(db_path)
        assert result["valid"] is True
        assert result["checked"] == 5

    def test_tampered_row_breaks_verification(self, db_path):
        log_event(db_path, actor="agent", event_type="TOOL_CALL", business_id=1)
        log_event(db_path, actor="agent", event_type="TOOL_CALL", business_id=1)

        # Triggers block UPDATE/DELETE through normal SQL — simulate tampering
        # by rewriting the file directly below the app layer the triggers guard.
        conn = sqlite3.connect(db_path)
        conn.execute("DROP TRIGGER audit_no_update")
        conn.execute("UPDATE audit_log SET event_type = 'FORGED' WHERE seq = 1")
        conn.commit()
        conn.close()

        result = verify_audit(db_path)
        assert result["valid"] is False
        assert result["first_break_seq"] == 1

    def test_triggers_reject_update_and_delete(self, db_path):
        log_event(db_path, actor="agent", event_type="TOOL_CALL", business_id=1)
        conn = sqlite3.connect(db_path)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE audit_log SET event_type = 'FORGED' WHERE seq = 1")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM audit_log WHERE seq = 1")
        conn.close()
