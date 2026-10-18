"""Rank pending payments: what should be paid first.

Scores are computed by fixed rules, not by the LLM, so the ranking is
reproducible and auditable; the assistant only explains it. Score 0-100:

  urgency     overdue 40, due today 35, tomorrow 30, 2-3 days 22, 4-7 days 12, later 5
  kind        loan repayment 25, rent/tax 22, wages 20, utility/school fees 15, ...
  essential   +10 when the owner marked it essential
  penalty     up to +15 when paying late costs money
  cash        walking the list in score order against the current balance:
              a payment that would break the safety buffer gets +5 if
              essential (needs attention) or -10 if not (can wait)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

KIND_WEIGHT = {
    "loan_repayment": 25,
    "rent": 22,
    "tax": 22,
    "wages": 20,
    "utility": 15,
    "school_fees": 15,
    "insurance": 12,
    "supplier_standing": 10,
    "other": 8,
    "savings": 5,
}
KIND_REASON = {
    "loan_repayment": "Loan repayment — late payment adds penalties and hurts your credit score",
    "rent": "Rent — missing it risks your premises",
    "tax": "Tax — KRA charges penalties and interest when late",
    "wages": "Wages — staff depend on it",
    "utility": "Utility — late payment risks disconnection",
    "school_fees": "School fees",
}

BANDS = [(70, "critical"), (50, "high"), (30, "medium"), (0, "low")]


@dataclass
class PaymentCandidate:
    payment_id: int
    label: str
    kind: str
    amount_minor: int
    due_date: date
    essential: bool = True
    late_penalty_minor: int = 0


@dataclass
class Priority:
    payment_id: int
    score: int
    band: str
    reasons: List[str] = field(default_factory=list)
    covered: Optional[bool] = None   # None when the balance is unknown


def _urgency(days: int) -> tuple[int, str]:
    if days < 0:
        return 40, f"Overdue by {-days} day{'s' if days != -1 else ''}"
    if days == 0:
        return 35, "Due today"
    if days == 1:
        return 30, "Due tomorrow"
    if days <= 3:
        return 22, f"Due in {days} days"
    if days <= 7:
        return 12, f"Due in {days} days"
    return 5, f"Due in {days} days"


def band_for(score: int) -> str:
    return next(name for threshold, name in BANDS if score >= threshold)


def rank_payments(
    candidates: List[PaymentCandidate],
    today: date,
    balance_minor: Optional[int] = None,
    buffer_minor: int = 0,
) -> List[Priority]:
    """Return priorities sorted most-urgent first."""
    scored = []
    for c in candidates:
        days = (c.due_date - today).days
        score, urgency_reason = _urgency(days)
        reasons = [urgency_reason]

        score += KIND_WEIGHT.get(c.kind, KIND_WEIGHT["other"])
        if c.kind in KIND_REASON:
            reasons.append(KIND_REASON[c.kind])
        if c.essential:
            score += 10
        if c.late_penalty_minor > 0:
            # 1 point per 1% of the payment the penalty represents, capped at 15.
            score += min(15, max(1, round(100 * c.late_penalty_minor / max(1, c.amount_minor))))
            reasons.append(f"Late fee of KES {c.late_penalty_minor / 100:,.0f} if missed")
        scored.append([c, score, reasons, None])

    scored.sort(key=lambda s: (-s[1], s[0].due_date, s[0].payment_id))

    if balance_minor is not None:
        running = balance_minor
        for entry in scored:
            c = entry[0]
            if running - c.amount_minor >= buffer_minor:
                running -= c.amount_minor
                entry[3] = True
            else:
                entry[3] = False
                if c.essential:
                    entry[1] += 5
                    entry[2].append("Your balance may not cover this — top up or delay other payments")
                else:
                    entry[1] -= 10
                    entry[2].append("Can wait — paying now would push you below your safety buffer")

    out = []
    for c, score, reasons, covered in scored:
        score = max(0, min(100, score))
        out.append(Priority(c.payment_id, score, band_for(score), reasons, covered))
    out.sort(key=lambda p: -p.score)
    return out
