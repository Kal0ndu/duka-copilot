"""Builds a real Duka database for the attack suite, the task evaluation and
scripts/key_numbers.py: base schema + every migration, two businesses with
their own owners, statements ingested through the real ingestor, an owner
PIN and a verified payee each. Nothing is mocked except the AI."""
from __future__ import annotations

import contextlib
import io
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "mock_data"
PIN = "2468"


@dataclass
class World:
    db: str
    amina_user: int
    amina: int          # business_id
    other_user: int
    other: int          # a second, unrelated business
    soko: int           # Amina's verified payee SOKO SUPPLIES
    file_id: int        # Amina's statement


def _user(conn, phone_hash, name):
    uid = conn.execute(
        "INSERT INTO app_user (phone_hash, display_name, display_token) VALUES (?, ?, 'TOK')",
        (phone_hash, name),
    ).lastrowid
    conn.commit()
    return uid


def build_world(tmp_dir, statement: str = "amina_grocery_statement.csv",
                other_statement: str = "grace_salon_statement.csv") -> World:
    from db.migrate import MigrationRunner
    from core.business_setup import BusinessSetup
    from core.ingestion import StatementIngestor
    from core.owner_settings import OwnerPin, add_payee

    db = str(Path(tmp_dir) / "duka.db")
    with contextlib.redirect_stdout(io.StringIO()):
        MigrationRunner(db).run_pending()
    conn = sqlite3.connect(db)
    amina_user = _user(conn, "hash-amina", "Amina")
    other_user = _user(conn, "hash-grace", "Grace")
    conn.close()

    setup = BusinessSetup(db)
    amina = setup.register_business("Amina Grocery", "grocery", owner_user_id=amina_user)
    other = setup.register_business("Grace Salon", "salon", owner_user_id=other_user)
    ingestor = StatementIngestor(db)
    report = ingestor.ingest((DATA / statement).read_bytes(), statement, amina, amina_user)
    ingestor.ingest((DATA / other_statement).read_bytes(), other_statement, other, other_user)

    pins = OwnerPin(db)
    pins.set_pin(amina, PIN)
    pins.set_pin(other, "1357")
    soko = add_payee(db, amina, "Soko Supplies", PIN)
    add_payee(db, other, "Beauty Hub Wholesale", "1357")
    return World(db, amina_user, amina, other_user, other, soko, report.file_id)


def fund_sandbox(db: str, business_id: int, balance_minor: int) -> None:
    """Give the sandbox account money so approved payments can run."""
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT 1 FROM sandbox_account WHERE business_id = ?", (business_id,)).fetchone()
        if row:
            conn.execute("UPDATE sandbox_account SET balance_minor = ? WHERE business_id = ?",
                         (balance_minor, business_id))
        else:
            conn.execute("INSERT INTO sandbox_account (business_id, balance_minor) VALUES (?, ?)",
                         (business_id, balance_minor))


def orchestrator_for(db: str):
    """An Orchestrator wired to this database (no API key: offline unless an
    LLM is injected)."""
    from core.config import Config
    from agent.orchestrator import Orchestrator

    class _Cfg(Config):
        DB_PATH = db
        LLM_API_KEY = ""

    return Orchestrator(_Cfg)


class ScriptedLLM:
    """Stands in for Gemini: returns pre-written decisions in order, and
    records the messages it was sent (to check what the AI could see)."""

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.seen = []

    def structured(self, messages, schema, max_retries=3):
        self.seen.append(messages)
        if not self.decisions:
            return {"final": True, "response": "Done."}
        nxt = self.decisions.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def with_llm(orch, llm):
    """Make the orchestrator use a scripted LLM (as if an API key were set)."""
    orch.cfg.LLM_API_KEY = "scripted"
    orch.llm = llm
    return orch
