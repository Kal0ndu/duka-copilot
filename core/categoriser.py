"""Transaction categoriser: deterministic rules first, LLM fallback."""
from typing import List, Tuple, Optional
from dataclasses import dataclass, field
import re


@dataclass
class CategoryResult:
    category_code: str
    confidence: float
    source: str  # 'rule' | 'llm' | 'owner'


@dataclass
class CategorisationRule:
    rule_id: int
    priority: int
    match_field: str  # description, counterparty, channel, amount_range, composite
    pattern: str
    direction: Optional[str]
    amount_min_minor: Optional[int]
    amount_max_minor: Optional[int]
    category_code: str
    confidence: float


# Built-in global rules (seeded, always active).
GLOBAL_RULES: List[CategorisationRule] = [
    CategorisationRule(1, 1, "channel", "till", "in", None, None, "SALES_TILL", 0.95),
    CategorisationRule(2, 2, "description", r"(?i)\brent\b|landlord|premises", "out", None, None, "RENT", 0.95),
    CategorisationRule(3, 3, "description", r"(?i)\b(kplc|power|electric|water|utility|zuku|safi)\b", "out", None, None, "UTILITIES", 0.95),
    CategorisationRule(4, 4, "description", r"(?i)\b(wage|salary|staff|worker|cashier)\b", "out", None, None, "WAGES", 0.90),
    CategorisationRule(5, 5, "description", r"(?i)\b(fare|transport|fuel|matatu|boda|nduthi)\b", "out", None, None, "TRANSPORT", 0.90),
    CategorisationRule(6, 6, "description", r"(?i)\b(airtime|safaricom|data|bundles)\b", "out", None, None, "AIRTIME_DATA", 0.95),
    CategorisationRule(7, 7, "description", r"(?i)\b(school|fees|tuition|uniform|academy|college)\b", "out", None, None, "SCHOOL_FEES", 0.90),
    CategorisationRule(8, 8, "description", r"(?i)\b(loan|mshwari|fuliza|overdraft|kcb.*mpesa)\b", "in", None, None, "LOAN_DISBURSEMENT", 0.85),
    CategorisationRule(9, 9, "channel", "overdraft", "in", None, None, "LOAN_DISBURSEMENT", 0.85),
    CategorisationRule(10, 10, "description", r"(?i)\b(loan.*repay|repay.*loan|mshwari.*pay|(overdraft|fuliza)\s+repay\w*)\b", "out", None, None, "LOAN_REPAYMENT", 0.85),
    CategorisationRule(11, 11, "channel", "overdraft", "out", None, None, "OVERDRAFT_FEE", 0.80),
    CategorisationRule(12, 12, "channel", "fee", "out", None, None, "TXN_CHARGES", 0.85),
    CategorisationRule(13, 13, "description", r"(?i)\b(stock|suppl(y|ies|iers?)|wholesal\w*|purchase|distribut\w*|buy)\b", "out", None, None, "STOCK_PURCHASES", 0.85),
    CategorisationRule(14, 14, "description", r"(?i)\b(family|personal|withdraw.*self|own\s*use)\b", "out", None, None, "PERSONAL_WITHDRAWAL", 0.80),
    CategorisationRule(15, 15, "description", r"(?i)\b(family|gift|relative|home|upcountry|school)\b", "out", None, None, "FAMILY_TRANSFER", 0.60),
    CategorisationRule(16, 16, "channel", "receive", "in", None, None, "SALES_TRANSFER", 0.70),
    CategorisationRule(17, 17, "channel", "bill", "out", None, None, "UTILITIES", 0.75),
    CategorisationRule(18, 18, "channel", "airtime", "out", None, None, "AIRTIME_DATA", 0.95),
    CategorisationRule(19, 19, "description", r"(?i)\b(repair|fix|maintenance|plumber|electrician)\b", "out", None, None, "REPAIRS", 0.85),
    CategorisationRule(20, 20, "description", r"(?i)\b(license|permit|council|tax|kra)\b", "out", None, None, "LICENSE_TAX", 0.85),
    # Ported from duka-copilot main: fee lines ("Pay Bill Charge") before the
    # bill->utilities rule, agent cash-outs, and person-to-person transfers.
    CategorisationRule(21, 0, "description", r"(?i)\bcharges?\b", "out", None, None, "TXN_CHARGES", 0.95),
    CategorisationRule(22, 21, "description", r"(?i)withdrawal at agent|agent withdrawal", "out", None, None, "PERSONAL_WITHDRAWAL", 0.85),
    # Wages or family? Medium confidence, so it lands in the owner's review
    # queue; core.ingestion turns it into WAGES on the owner's staff payday.
    CategorisationRule(23, 22, "description", r"(?i)^customer transfer to", "out", None, None, "FAMILY_TRANSFER", 0.60),
]

PAYDAY_EVENING_HOUR = 18


class Categoriser:
    """Categorise transactions using rules first, with LLM fallback."""

    def __init__(self, rules: List[CategorisationRule] = None):
        self.rules = sorted(rules or GLOBAL_RULES, key=lambda r: r.priority)

    def categorise(self, description: str = "", channel: str = "other", direction: str = "out",
                   amount_minor: int = 0, counterparty: str = "") -> CategoryResult:
        """Return the best category for a single transaction."""
        # Handle if called with a list or dict
        if isinstance(description, list):
            return self.categorise_batch(description)
        if isinstance(description, dict):
            txn = description
            return self.categorise(
                description=txn.get("description", txn.get("description_redacted", "")),
                channel=txn.get("channel", "other"),
                direction=txn.get("direction", "out"),
                amount_minor=txn.get("amount_minor", int(round(txn.get("amount", 0) * 100))),
                counterparty=txn.get("counterparty", txn.get("counterparty_token", "")),
            )

        for rule in self.rules:
            if rule.direction and rule.direction != direction:
                continue
            if rule.amount_min_minor is not None and amount_minor < rule.amount_min_minor:
                continue
            if rule.amount_max_minor is not None and amount_minor > rule.amount_max_minor:
                continue

            match_text = ""
            if rule.match_field == "description":
                match_text = description
            elif rule.match_field == "counterparty":
                match_text = counterparty
            elif rule.match_field == "channel":
                match_text = channel
            elif rule.match_field == "composite":
                match_text = f"{description} {counterparty} {channel}"

            if re.search(rule.pattern, match_text, re.IGNORECASE):
                return CategoryResult(
                    category_code=rule.category_code,
                    confidence=rule.confidence,
                    source="rule",
                )

        # No rule matched — needs LLM or owner review
        return CategoryResult(
            category_code="UNCATEGORISED",
            confidence=0.30,
            source="rule",
        )

    def categorise_batch(self, transactions: list) -> List[CategoryResult]:
        """Categorise a batch of transactions (dicts or tuples)."""
        results = []
        for txn in transactions:
            if isinstance(txn, (list, tuple)):
                desc = txn[0] if len(txn) > 0 else ""
                chan = txn[1] if len(txn) > 1 else "other"
                direct = txn[2] if len(txn) > 2 else "out"
                amt = txn[3] if len(txn) > 3 else 0
                cpty = txn[4] if len(txn) > 4 else ""
                results.append(self.categorise(desc, chan, direct, amt, cpty))
            elif isinstance(txn, dict):
                results.append(self.categorise(
                    description=txn.get("description", txn.get("description_redacted", "")),
                    channel=txn.get("channel", "other"),
                    direction=txn.get("direction", "out"),
                    amount_minor=txn.get("amount_minor", int(round(txn.get("amount", 0) * 100))),
                    counterparty=txn.get("counterparty", txn.get("counterparty_token", "")),
                ))
            else:
                results.append(self.categorise(str(txn)))
        return results


# ---- "Teach it once": the owner's own category rules ----
#
# Rules are keyed on the payee's party token (the redacted counterparty the
# ingestor stores), so one correction covers every past and future payment
# to that payee for this business only.

def load_owner_rules(conn, business_id: int) -> dict:
    """{party_token: category_code} for the owner's taught rules."""
    rows = conn.execute(
        """SELECT r.pattern, c.code FROM categorisation_rule r
           JOIN category c ON c.category_id = r.category_id
           WHERE r.business_id = ? AND r.created_by = 'owner' AND r.active = 1
             AND r.match_field = 'counterparty'
           ORDER BY r.rule_id""",
        (business_id,),
    ).fetchall()
    return {pattern: code for pattern, code in rows}


def teach_category(db_path: str, business_id: int, txn_id: int, category_code: str) -> dict:
    """Owner corrects one transaction's category. Saves a rule for its payee
    and re-labels every transaction from that payee. Returns what changed."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        cat = conn.execute("SELECT category_id FROM category WHERE code = ?", (category_code,)).fetchone()
        if cat is None:
            raise ValueError(f"Unknown category {category_code!r}")
        txn = conn.execute(
            "SELECT counterparty_token FROM transaction_ledger WHERE txn_id = ? AND business_id = ?",
            (txn_id, business_id),
        ).fetchone()
        if txn is None:
            raise ValueError("Transaction not found for this business")
        token = txn[0]

        if not token:
            # No identifiable payee (e.g. a fee line): fix just this row.
            conn.execute(
                """UPDATE transaction_ledger SET category_id = ?, category_source = 'owner',
                       confidence = 1.0, needs_review = 0 WHERE txn_id = ?""",
                (cat[0], txn_id),
            )
            conn.commit()
            return {"rule_saved": False, "updated": 1}

        # One active rule per payee: retire the old one, then save the new.
        conn.execute(
            """UPDATE categorisation_rule SET active = 0
               WHERE business_id = ? AND created_by = 'owner' AND match_field = 'counterparty'
                 AND pattern = ?""",
            (business_id, token),
        )
        conn.execute(
            """INSERT INTO categorisation_rule
               (business_id, priority, match_field, pattern, category_id, confidence, created_by)
               VALUES (?, 0, 'counterparty', ?, ?, 1.0, 'owner')""",
            (business_id, token, cat[0]),
        )
        updated = conn.execute(
            """UPDATE transaction_ledger SET category_id = ?, category_source = 'owner',
                   confidence = 1.0, needs_review = 0
               WHERE business_id = ? AND counterparty_token = ? AND voided = 0""",
            (cat[0], business_id, token),
        ).rowcount
        conn.commit()
        return {"rule_saved": True, "payee": token, "updated": updated}
    finally:
        conn.close()


def forget_category_rule(db_path: str, business_id: int, party_token: str) -> None:
    """Stop applying a taught rule (already-labelled rows keep their label)."""
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """UPDATE categorisation_rule SET active = 0
               WHERE business_id = ? AND created_by = 'owner' AND pattern = ?""",
            (business_id, party_token),
        )


# ---- Tool wrapper function for agent dispatch ----

def categorise_transactions(args, business_id: Optional[int] = None,
                           db_path: Optional[str] = None) -> dict:
    """Categorise transactions from a file using rules first, then LLM fallback.
    
    Args:
        args: CategoriseTransactionsArgs with file_id
        business_id: Active business ID
        db_path: Database path
    
    Returns:
        dict with counts per category, review-queue size
    """
    import sqlite3
    from core.config import config
    
    if db_path is None:
        db_path = config.DB_PATH
    if business_id is None:
        return {"error": "business_id required"}
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Re-run the rules (and the owner's taught rules) over this file's
        # rows that still need review. Confident upload-time categories and
        # rows the owner categorised by hand are never overwritten.
        # Categorise on the real payee name (from the local token vault), as
        # the ingestor does: the rules need "SOKO SUPPLIES", not its token.
        # This runs on the owner's machine; only the counts go back to the AI.
        cursor.execute("""
            SELECT t.txn_id, t.description_redacted, t.counterparty_token, t.channel, t.direction,
                   t.amount_minor, t.party_id, v.original_value AS payee_name
            FROM transaction_ledger t
            LEFT JOIN token_vault v ON v.token = t.counterparty_token AND v.business_id = t.business_id
            WHERE t.business_id = ? AND t.file_id = ? AND t.voided = 0
              AND COALESCE(t.category_source, '') <> 'owner'
              AND (t.needs_review = 1 OR t.category_id IS NULL)
            ORDER BY t.local_date DESC
        """, (business_id, args.file_id))
        
        txns = cursor.fetchall()
        
        if not txns:
            return {"message": "No transactions in this file need categorising", "categorised": 0}
        
        cat_ids = {r["code"]: r["category_id"] for r in cursor.execute("SELECT code, category_id FROM category")}
        fallback_cat = cat_ids.get("UNCLASSIFIED")
        owner_rules = load_owner_rules(conn, business_id)
        categoriser = Categoriser()
        category_counts = {}
        review_queue = []
        
        for txn in txns:
            learned = owner_rules.get(txn["counterparty_token"]) if txn["counterparty_token"] else None
            if learned:
                result = CategoryResult(category_code=learned, confidence=1.0, source="owner")
            else:
                text = txn["description_redacted"] or ""
                if txn["payee_name"] and txn["counterparty_token"]:
                    text = text.replace(txn["counterparty_token"], txn["payee_name"])
                result = categoriser.categorise(
                    description=text,
                    channel=txn["channel"] or "other",
                    direction=txn["direction"],
                    amount_minor=txn["amount_minor"],
                    counterparty=txn["payee_name"] or txn["counterparty_token"] or "",
                )
            category_id = cat_ids.get(result.category_code, fallback_cat)
            needs_review = result.confidence < 0.7 or category_id == fallback_cat
            
            # Update database
            cursor.execute("""
                UPDATE transaction_ledger
                SET category_id = ?, confidence = ?, category_source = ?, needs_review = ?
                WHERE txn_id = ?
            """, (category_id, result.confidence, result.source, int(needs_review), txn["txn_id"]))
            
            # Track counts
            category_counts[result.category_code] = category_counts.get(result.category_code, 0) + 1
            
            # Add low-confidence items to review queue
            if needs_review:
                review_queue.append({
                    "transaction_id": txn["txn_id"],
                    "description": txn["description_redacted"],
                    "suggested_category": result.category_code,
                    "confidence": result.confidence,
                })
        
        conn.commit()
        conn.close()
        
        return {
            "file_id": args.file_id,
            "categorised": len(txns),
            "category_breakdown": category_counts,
            "review_queue_size": len(review_queue),
            "review_queue_sample": review_queue[:5],  # First 5 for preview
        }
    
    except Exception as e:
        return {"error": f"Categorization failed: {e}"}
