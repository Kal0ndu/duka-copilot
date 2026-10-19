"""Saved statements: what was uploaded, and the ledger built from them.

An uploaded statement is stored as its parsed, PII-redacted rows in
transaction_ledger plus one source_file row (name, size, period, row count,
SHA-256). The original file is not kept: it holds phone numbers and names
that the ledger stores only as tokens. Pages load the ledger from here, so
a statement uploaded once is there after logout, login and restarts.
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional


def list_statements(db_path: str, business_id: int) -> List[Dict]:
    """Statements uploaded for the business, newest first, with how many of
    their rows are in the ledger (0 once removed)."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT f.file_id, f.filename, f.uploaded_at, f.period_start, f.period_end,
                          f.row_count, f.size_bytes, f.risk_flag, f.risk_reason, f.status,
                          (SELECT COUNT(*) FROM transaction_ledger t
                            WHERE t.file_id = f.file_id AND t.voided = 0) AS active_rows
                   FROM source_file f WHERE f.business_id = ?
                   ORDER BY f.uploaded_at DESC, f.file_id DESC""",
                (business_id,),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


def remove_statement(db_path: str, business_id: int, file_id: int) -> int:
    """Take a statement's rows out of the ledger (voided, not deleted, so
    the audit trail stays). Returns the number of rows removed. Uploading
    the same file again later brings them back."""
    with sqlite3.connect(db_path) as conn:
        found = conn.execute("SELECT 1 FROM source_file WHERE file_id = ? AND business_id = ?",
                             (file_id, business_id)).fetchone()
        if not found:
            raise LookupError("That statement was not found for this business.")
        n = conn.execute(
            """UPDATE transaction_ledger SET voided = 1, void_reason = 'statement removed by owner'
               WHERE file_id = ? AND business_id = ? AND voided = 0""",
            (file_id, business_id),
        ).rowcount
        # Removing the fingerprint lets the owner upload the same file again.
        conn.execute("UPDATE source_file SET sha256 = sha256 || ':removed:' || file_id, status = 'rejected', "
                     "risk_reason = COALESCE(risk_reason, 'removed by owner') "
                     "WHERE file_id = ? AND business_id = ?", (file_id, business_id))
    return n


def ledger_version(db_path: str, business_id: int) -> tuple:
    """Changes whenever rows are added, removed or recategorised."""
    try:
        with sqlite3.connect(db_path) as conn:
            return tuple(conn.execute(
                """SELECT COUNT(*), COALESCE(MAX(txn_id), 0), COALESCE(SUM(voided), 0),
                          COALESCE(SUM(category_id), 0)
                   FROM transaction_ledger WHERE business_id = ?""",
                (business_id,),
            ).fetchone())
    except sqlite3.OperationalError:
        return (0, 0, 0, 0)


def load_ledger_records(db_path: str, business_id: int,
                        file_id: Optional[int] = None) -> List[Dict]:
    """The business's ledger in the record shape the analysis pages use
    (signed KES amount, date, direction, category, counterparty, ...),
    newest first. Counterparty names are the business's own, from its
    token vault; nothing here leaves the app."""
    sql = """SELECT t.txn_id, t.file_id, t.reference, t.ts, t.local_date, t.amount_minor, t.fee_minor,
                    t.direction, t.balance_after_minor, t.counterparty_token, t.description_redacted,
                    t.channel, LOWER(COALESCE(c.code, 'unclassified')) AS category,
                    c.kind AS category_kind, COALESCE(v.original_value, t.counterparty_token) AS counterparty
             FROM transaction_ledger t
             LEFT JOIN category c ON c.category_id = t.category_id
             LEFT JOIN token_vault v ON v.token = t.counterparty_token AND v.business_id = t.business_id
             WHERE t.business_id = ? AND t.voided = 0"""
    params: list = [business_id]
    if file_id is not None:
        sql += " AND t.file_id = ?"
        params.append(file_id)
    sql += " ORDER BY t.local_date DESC, t.ts DESC, t.txn_id DESC"
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        kes = r["amount_minor"] / 100.0
        balance = r["balance_after_minor"]
        out.append({
            "txn_id": r["txn_id"], "file_id": r["file_id"],
            "date": r["local_date"], "local_date": r["local_date"], "ts": r["ts"],
            "receipt": r["reference"], "reference": r["reference"],
            "amount": kes if r["direction"] == "in" else -kes,
            "amount_minor": r["amount_minor"], "fee_minor": r["fee_minor"] or 0,
            "direction": r["direction"], "type": "credit" if r["direction"] == "in" else "debit",
            "balance": balance / 100.0 if balance is not None else None,
            "balance_after_minor": balance,
            "counterparty": r["counterparty"] or "Unknown",
            "counterparty_token": r["counterparty_token"],
            "description": r["description_redacted"] or "",
            "channel": r["channel"], "category": r["category"],
            "category_kind": r["category_kind"] or ("income" if r["direction"] == "in" else "opex"),
        })
    return out
