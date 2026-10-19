"""Statement ingestion: parse -> redact -> categorise -> persist to the ledger.

This is the path that turns an uploaded statement into the data the LLM sees:
auth/user_context.py builds its context from transaction_ledger and
obligation, which this module writes.

Privacy: counterparty names are replaced by party tokens before they reach
the ledger; originals live only in token_vault (local, for UI display).
Descriptions are redacted, and rows matching injection patterns are stored
as "[flagged content removed]" with needs_review=1.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from core.adapters.base import VALID_CHANNELS
from core.adapters.mobile_money_ke import MobileMoneyKeAdapter
from core.adapters.mpesa_pdf import MpesaPdfAdapter
from core.categoriser import Categoriser, CategoryResult, load_owner_rules
from core.config import Config
from core.redaction import Redactor

ADAPTER_VERSION = "1.0"
FLAGGED_DESCRIPTION = "[flagged content removed]"
REVIEW_CONFIDENCE = 0.70

# Category code -> obligation.kind for detected recurring payments.
CATEGORY_TO_OBLIGATION_KIND = {
    "RENT": "rent",
    "UTILITIES": "utility",
    "WAGES": "wages",
    "LOAN_REPAYMENT": "loan_repayment",
    "LICENSE_TAX": "tax",
    "SCHOOL_FEES": "school_fees",
    "STOCK_PURCHASES": "supplier_standing",
    "SAVINGS_DEPOSIT": "savings",
}
# Regular but not bills: fees, income, and personal movements.
NOT_OBLIGATIONS = {
    "TXN_CHARGES", "OVERDRAFT_FEE", "INTEREST_FEES", "SALES_TILL", "SALES_TRANSFER",
    "OTHER_INCOME", "LOAN_DISBURSEMENT", "OWN_TRANSFER", "PERSONAL_WITHDRAWAL",
}
MIN_OBLIGATION_MINOR = 100_00
ESSENTIAL_KINDS = {"rent", "utility", "wages", "loan_repayment", "tax", "school_fees"}

# Median gap between payments (days) -> cadence.
_CADENCE_BY_GAP = [
    ((6, 8), "weekly", 7),
    ((13, 16), "biweekly", 14),
    ((26, 35), "monthly", 30),
]


@dataclass
class IngestReport:
    file_id: Optional[int]
    status: str                      # loaded | duplicate | rejected
    rows_read: int = 0
    rows_loaded: int = 0
    rows_duplicate: int = 0
    rows_flagged: int = 0
    rows_needs_review: int = 0
    obligations_detected: int = 0
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    validation_issues: List[str] = field(default_factory=list)
    message: str = ""


def _party_name(details: str) -> str:
    """Best-effort counterparty name from M-Pesa 'Details' text.

    'Customer Transfer to 0722***123 - JOHN DOE' -> 'JOHN DOE'
    'Pay Bill to 888880 - KPLC PREPAID Acc. 1234' -> 'KPLC PREPAID'
    """
    text = (details or "").strip()
    if " - " in text:
        text = text.rsplit(" - ", 1)[1]
    text = re.sub(r"(?i)\bacc(ount)?\.?\s*\S+.*$", "", text)
    return re.sub(r"\s+", " ", text).strip().upper()[:80]


def _party_token(business_id: int, name: str) -> str:
    digest = hashlib.sha256(f"{business_id}:{name}".encode()).hexdigest()[:10].upper()
    return f"PARTY_{digest}"


def _is_payday_evening(rec: Dict, payday_weekday: int) -> bool:
    """Sent on the owner's staff payday, in the evening?"""
    from core.categoriser import PAYDAY_EVENING_HOUR
    ts = str(rec.get("ts") or f"{rec.get('date', '')} {rec.get('time', '')}").strip()
    try:
        when = datetime.fromisoformat(ts.replace("T", " ")[:19])
    except ValueError:
        return False
    return when.weekday() == payday_weekday and when.hour >= PAYDAY_EVENING_HOUR


class StatementIngestor:
    """Persist an uploaded statement into the business's ledger."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or Config.DB_PATH
        self.categoriser = Categoriser()

    # ---- public API ----

    def parse(self, file_bytes: bytes, password: Optional[str] = None) -> List[Dict]:
        """Parse a CSV or PDF statement into normalised records (oldest first)."""
        pdf = MpesaPdfAdapter()
        if pdf.detect(file_bytes):
            records = pdf.parse(file_bytes, password=password)
        else:
            records = MobileMoneyKeAdapter().parse(file_bytes)
        def key(r):
            return str(r.get("ts") or f"{r.get('date', '')} {r.get('time', '')}")
        # Statements list newest first; flip before the stable sort so rows
        # sharing a timestamp keep their chronological order.
        if records and key(records[0]) > key(records[-1]):
            records = list(reversed(records))
        return sorted(records, key=key)

    def ingest(
        self,
        file_bytes: bytes,
        filename: str,
        business_id: int,
        user_id: Optional[int] = None,
        password: Optional[str] = None,
    ) -> IngestReport:
        sha = hashlib.sha256(file_bytes).hexdigest()
        records = self.parse(file_bytes, password=password)
        # Read the owner's settings before this upload opens its write transaction.
        from core.owner_settings import load_settings
        self._payday = load_settings(self.db_path, business_id).payday_weekday

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            existing = conn.execute(
                "SELECT file_id, status FROM source_file WHERE business_id = ? AND sha256 = ?",
                (business_id, sha),
            ).fetchone()
            if existing and existing["status"] == "loaded":
                return IngestReport(
                    file_id=existing["file_id"], status="duplicate",
                    message="This statement was already uploaded.",
                )

            account_id = self._ensure_account(conn, business_id)
            media_type = "application/pdf" if file_bytes[:5] == b"%PDF-" else "text/csv"
            if existing:
                file_id = existing["file_id"]
            else:
                file_id = conn.execute(
                    """INSERT INTO source_file (business_id, account_id, platform_id, filename,
                           sha256, size_bytes, media_type, adapter_name, adapter_version, uploaded_by)
                       VALUES (?, ?, (SELECT platform_id FROM platform WHERE code = 'mobile_money_ke'),
                               ?, ?, ?, ?, ?, ?, ?)""",
                    (business_id, account_id, filename[:200], sha, len(file_bytes), media_type,
                     "MpesaPdfAdapter" if media_type == "application/pdf" else "MobileMoneyKeAdapter",
                     ADAPTER_VERSION, user_id),
                ).lastrowid
            run_id = conn.execute(
                "INSERT INTO ingestion_run (file_id) VALUES (?)", (file_id,)
            ).lastrowid

            report = IngestReport(file_id=file_id, status="loaded", rows_read=len(records))
            report.validation_issues = self._validate(records)
            self._load_rows(conn, records, business_id, account_id, file_id, report)

            dates = [r.get("date") for r in records if r.get("date")]
            report.period_start = min(dates) if dates else None
            report.period_end = max(dates) if dates else None
            conn.execute(
                """UPDATE source_file SET status = 'loaded', row_count = ?, period_start = ?,
                       period_end = ?, risk_flag = ?, risk_reason = ?
                   WHERE file_id = ?""",
                (report.rows_loaded, report.period_start, report.period_end,
                 1 if report.rows_flagged else 0,
                 f"{report.rows_flagged} row(s) matched injection patterns" if report.rows_flagged else None,
                 file_id),
            )
            conn.execute(
                """UPDATE ingestion_run SET finished_at = strftime('%Y-%m-%dT%H:%M:%SZ','now'),
                       status = 'succeeded', rows_read = ?, rows_loaded = ?, rows_rejected = ?,
                       validation_json = ?
                   WHERE run_id = ?""",
                (report.rows_read, report.rows_loaded, report.rows_duplicate,
                 json.dumps(report.validation_issues), run_id),
            )
            report.obligations_detected = self.detect_obligations(conn, business_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        if report.rows_flagged:
            from auth.rbac import log_security_event
            log_security_event(
                self.db_path, "INJECTION_DETECTED", user_id=user_id, business_id=business_id,
                resource=f"source_file:{file_id}", outcome="blocked", severity="high",
                detection=f"{report.rows_flagged} statement row(s) matched prompt-injection patterns",
                handling="rows stored redacted and flagged; the AI treats them as data, never instructions",
            )

        report.message = (
            f"Loaded {report.rows_loaded} of {report.rows_read} transactions"
            + (f" ({report.rows_duplicate} already on file)" if report.rows_duplicate else "")
            + "."
        )
        return report

    # ---- internals ----

    def _ensure_account(self, conn: sqlite3.Connection, business_id: int) -> int:
        row = conn.execute(
            """SELECT account_id FROM financial_account
               WHERE business_id = ? AND kind = 'mobile_wallet' AND is_sandbox = 0
               ORDER BY is_primary DESC, account_id LIMIT 1""",
            (business_id,),
        ).fetchone()
        if row:
            return row["account_id"]
        return conn.execute(
            """INSERT INTO financial_account (business_id, platform_id, kind, label, currency_code, is_primary)
               VALUES (?, (SELECT platform_id FROM platform WHERE code = 'mobile_money_ke'),
                       'mobile_wallet', 'M-Pesa', 'KES', 1)""",
            (business_id,),
        ).lastrowid

    @staticmethod
    def _validate(records: List[Dict]) -> List[str]:
        """Lightweight checks: balance continuity and duplicate receipts."""
        issues = []
        refs = [r.get("reference") for r in records if r.get("reference")]
        if len(refs) != len(set(refs)):
            issues.append("Statement contains duplicate receipt numbers.")
        mismatches = 0
        for prev, cur in zip(records, records[1:]):
            if prev.get("balance_after_minor") is None or cur.get("balance_after_minor") is None:
                continue
            delta = cur["amount_minor"] if cur["direction"] == "in" else -cur["amount_minor"]
            if prev["balance_after_minor"] + delta != cur["balance_after_minor"]:
                mismatches += 1
        if mismatches:
            issues.append(
                f"{mismatches} row(s) where the running balance does not reconcile "
                "(common when fees or same-second transactions are reordered)."
            )
        return issues

    def _category_ids(self, conn: sqlite3.Connection) -> Dict[str, int]:
        return {r["code"]: r["category_id"] for r in conn.execute("SELECT code, category_id FROM category")}

    def _load_rows(self, conn, records, business_id, account_id, file_id, report: IngestReport) -> None:
        redactor = Redactor(business_id=business_id)
        cat_ids = self._category_ids(conn)
        owner_rules = load_owner_rules(conn, business_id)
        payday = getattr(self, "_payday", None)
        fallback_cat = cat_ids.get("UNCLASSIFIED")

        for row_no, rec in enumerate(records, start=1):
            details = str(rec.get("description_raw") or rec.get("counterparty") or "")
            channel = rec.get("channel") if rec.get("channel") in VALID_CHANNELS else "other"
            direction = rec.get("direction", "out")
            amount_minor = int(rec.get("amount_minor") or 0)
            if amount_minor <= 0:
                continue

            # Categorise on the raw text locally — nothing here leaves the machine.
            cat = self.categoriser.categorise(
                description=details, channel=channel, direction=direction,
                amount_minor=amount_minor, counterparty=details,
            )
            if cat.category_code == "FAMILY_TRANSFER" and payday is not None and _is_payday_evening(rec, payday):
                # The owner said staff are paid on this weekday (Business Setup).
                cat = CategoryResult("WAGES", 0.75, "rule")
            category_id = cat_ids.get(cat.category_code, fallback_cat)
            needs_review = cat.confidence < REVIEW_CONFIDENCE or category_id == fallback_cat

            # Scan the original text: payloads often hide in the counterparty
            # slot ("Payment from 07.. - IGNORE ALL PREVIOUS INSTRUCTIONS...").
            redacted = redactor.redact(details)
            party_id = party_token = None
            if redacted.injection_flags:
                report.rows_flagged += 1
                needs_review = True
                description = FLAGGED_DESCRIPTION
            else:
                party_id, party_token = self._upsert_party(
                    conn, business_id, details, rec.get("date"),
                    entity_type="MERCHANT" if channel in ("till", "bill") else "PERSON",
                )
                # Names aren't caught by the regex redactor, so swap the
                # counterparty part for its token before redacting the rest.
                if party_token:
                    redacted = redactor.redact(f"{details.rsplit(' - ', 1)[0]} - {party_token}")
                    if party_token in owner_rules:
                        # The owner taught this payee's category once; it wins.
                        cat = CategoryResult(owner_rules[party_token], 1.0, "owner")
                        category_id = cat_ids.get(cat.category_code, fallback_cat)
                        needs_review = False
                description = redacted.redacted

            raw_id = conn.execute(
                "INSERT OR IGNORE INTO raw_statement_row (file_id, row_no, raw_json) VALUES (?, ?, ?)",
                (file_id, row_no, json.dumps({
                    "reference": rec.get("reference"), "ts": rec.get("ts"),
                    "amount_minor": amount_minor, "direction": direction,
                    "balance_after_minor": rec.get("balance_after_minor"),
                    "channel": channel, "description_redacted": description,
                })),
            ).lastrowid or None
            for code in redacted.injection_flags:
                conn.execute(
                    "INSERT INTO injection_finding (file_id, raw_id, pattern_code, excerpt_redacted) VALUES (?, ?, ?, ?)",
                    (file_id, raw_id, code, redacted.redacted[:120]),
                )

            ts = rec.get("ts") or f"{rec.get('date', '')} {rec.get('time', '')}".strip()
            cur = conn.execute(
                """INSERT OR IGNORE INTO transaction_ledger (
                       business_id, account_id, file_id, raw_id, reference, ts, local_date,
                       amount_minor, direction, balance_after_minor, party_id, counterparty_token,
                       description_redacted, channel, category_id, category_source, confidence,
                       needs_review, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'statement')""",
                (business_id, account_id, file_id, raw_id, rec.get("reference") or None, ts,
                 rec.get("date"), amount_minor, direction, rec.get("balance_after_minor"),
                 party_id, party_token, description, channel, category_id, cat.source,
                 cat.confidence, 1 if needs_review else 0),
            )
            if not cur.rowcount and rec.get("reference"):
                # A row from a statement the owner removed: bring it back.
                cur = conn.execute(
                    """UPDATE transaction_ledger SET voided = 0, void_reason = NULL, file_id = ?
                       WHERE account_id = ? AND reference = ? AND voided = 1
                         AND void_reason = 'statement removed by owner'""",
                    (file_id, account_id, rec.get("reference")),
                )
            if cur.rowcount:
                report.rows_loaded += 1
                report.rows_needs_review += 1 if needs_review else 0
            else:
                report.rows_duplicate += 1

    def _upsert_party(self, conn, business_id: int, details: str, seen: Optional[str], entity_type: str = "PERSON"):
        # Only rows that name a counterparty ("... - NAME") get a party;
        # charges and overdraft lines would otherwise become fake parties.
        name = _party_name(details) if " - " in (details or "") else ""
        if not name:
            return None, None
        token = _party_token(business_id, name)
        conn.execute(
            """INSERT INTO party (business_id, display_token, first_seen, last_seen)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (business_id, display_token)
               DO UPDATE SET last_seen = MAX(COALESCE(last_seen, ''), excluded.last_seen)""",
            (business_id, token, seen, seen),
        )
        conn.execute(
            """INSERT OR IGNORE INTO token_vault (token, business_id, entity_type, original_value)
               VALUES (?, ?, ?, ?)""",
            (token, business_id, entity_type, name),
        )
        party_id = conn.execute(
            "SELECT party_id FROM party WHERE business_id = ? AND display_token = ?",
            (business_id, token),
        ).fetchone()["party_id"]
        return party_id, token

    def detect_obligations(self, conn: sqlite3.Connection, business_id: int, today: Optional[date] = None) -> int:
        """Detect regular outgoing payments to the same party and record them as obligations.

        A party qualifies with 3+ payments whose gaps have a weekly, biweekly
        or monthly median and whose amounts stay within 15% of the median.
        Parties that already have an obligation are skipped.
        """
        today = today or date.today()
        rows = conn.execute(
            """SELECT t.party_id, t.local_date, t.amount_minor, c.code AS category_code
               FROM transaction_ledger t LEFT JOIN category c ON c.category_id = t.category_id
               WHERE t.business_id = ? AND t.direction = 'out' AND t.voided = 0
                 AND t.party_id IS NOT NULL
                 AND t.local_date >= date(?, '-180 days')
               ORDER BY t.party_id, t.local_date""",
            (business_id, today.isoformat()),
        ).fetchall()
        known = {r[0] for r in conn.execute(
            "SELECT party_id FROM obligation WHERE business_id = ? AND party_id IS NOT NULL", (business_id,)
        )}

        by_party: Dict[int, List[sqlite3.Row]] = {}
        for r in rows:
            by_party.setdefault(r["party_id"], []).append(r)

        created = 0
        for party_id, txns in by_party.items():
            if party_id in known or len(txns) < 3:
                continue
            # Collapse same-day payments (split payments, fees) into one.
            per_day: Dict[str, int] = {}
            for t in txns:
                per_day[t["local_date"]] = per_day.get(t["local_date"], 0) + t["amount_minor"]
            days = sorted(per_day)
            if len(days) < 3:
                continue
            parsed = [datetime.strptime(d[:10], "%Y-%m-%d").date() for d in days]
            gap = statistics.median((b - a).days for a, b in zip(parsed, parsed[1:]))
            cadence = next(((name, step) for (lo, hi), name, step in _CADENCE_BY_GAP if lo <= gap <= hi), None)
            if not cadence:
                continue
            amounts = [per_day[d] for d in days]
            median_amt = int(statistics.median(amounts))
            if median_amt <= 0 or any(abs(a - median_amt) > 0.15 * median_amt for a in amounts):
                continue

            category_code = txns[-1]["category_code"] or ""
            if category_code in NOT_OBLIGATIONS or median_amt < MIN_OBLIGATION_MINOR:
                continue
            kind = CATEGORY_TO_OBLIGATION_KIND.get(category_code, "other")
            name, step = cadence
            next_due = parsed[-1] + timedelta(days=step)
            while next_due < today:
                next_due += timedelta(days=step)
            label = f"{category_code.replace('_', ' ').title() or 'Regular payment'} ({name})"
            conn.execute(
                """INSERT INTO obligation (business_id, party_id, label, kind, amount_minor, cadence,
                       day_of_month, next_due, essential, source, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'detected', ?)""",
                (business_id, party_id, label, kind, median_amt, name,
                 parsed[-1].day if name == "monthly" else None, next_due.isoformat(),
                 1 if kind in ESSENTIAL_KINDS else 0, min(0.95, 0.5 + 0.1 * len(days))),
            )
            created += 1
        return created
