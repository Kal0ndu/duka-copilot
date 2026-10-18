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
    CategorisationRule(7, 7, "description", r"(?i)\b(school|fees|tuition|uniform)\b", "out", None, None, "SCHOOL_FEES", 0.90),
    CategorisationRule(8, 8, "description", r"(?i)\b(loan|mshwari|fuliza|overdraft|kcb.*mpesa)\b", "in", None, None, "LOAN_DISBURSEMENT", 0.85),
    CategorisationRule(9, 9, "channel", "overdraft", "in", None, None, "LOAN_DISBURSEMENT", 0.85),
    CategorisationRule(10, 10, "description", r"(?i)\b(loan.*repay|repay.*loan|mshwari.*pay|(overdraft|fuliza)\s+repay\w*)\b", "out", None, None, "LOAN_REPAYMENT", 0.85),
    CategorisationRule(11, 11, "channel", "overdraft", "out", None, None, "OVERDRAFT_FEE", 0.80),
    CategorisationRule(12, 12, "channel", "fee", "out", None, None, "TXN_CHARGES", 0.85),
    CategorisationRule(13, 13, "description", r"(?i)\b(stock|supplier|suppl(y|ies)|wholesale|purchase|distributor|buy)\b", "out", None, None, "STOCK_PURCHASES", 0.85),
    CategorisationRule(14, 14, "description", r"(?i)\b(family|personal|withdraw.*self|own\s*use)\b", "out", None, None, "PERSONAL_WITHDRAWAL", 0.80),
    CategorisationRule(15, 15, "description", r"(?i)\b(family|gift|relative|home|upcountry|school)\b", "out", None, None, "FAMILY_TRANSFER", 0.60),
    CategorisationRule(16, 16, "channel", "receive", "in", None, None, "SALES_TRANSFER", 0.70),
    CategorisationRule(17, 17, "channel", "bill", "out", None, None, "UTILITIES", 0.75),
    CategorisationRule(18, 18, "channel", "airtime", "out", None, None, "AIRTIME_DATA", 0.95),
    CategorisationRule(19, 19, "description", r"(?i)\b(repair|fix|maintenance|plumber|electrician)\b", "out", None, None, "REPAIRS", 0.85),
    CategorisationRule(20, 20, "description", r"(?i)\b(license|permit|council|tax|kra)\b", "out", None, None, "LICENSE_TAX", 0.85),
]


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
