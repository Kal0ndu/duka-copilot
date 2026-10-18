"""Mock lender: simulates digital credit products for comparison."""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import date, timedelta
import math

from core.cost_engine import CostEngine


@dataclass
class LoanOffer:
    lender: str
    product: str
    principal_minor: int
    term_days: int
    interest_rate_flat_pct: float      # flat % of principal
    processing_fee_pct: float           # % of principal
    disbursed_minor: int                # principal - fees
    daily_repayment_minor: int
    total_repayable_minor: int
    ear_pct: float                      # effective annual rate
    tcc_pct: float                      # total cost of credit %


# ---- pre-baked products ----

PRODUCTS = {
    "mshwari": {
        "lender": "M-Shwari",
        "product": "KCB M-Shwari",
        "interest_rate_flat_pct": 7.5,
        "processing_fee_pct": 0.0,
    },
    "kcb_mpesa": {
        "lender": "KCB M-Pesa",
        "product": "KCB M-Pesa Loan",
        "interest_rate_flat_pct": 6.0,
        "processing_fee_pct": 1.0,
    },
    "fuliza": {
        "lender": "Fuliza",
        "product": "Fuliza Overdraft",
        "interest_rate_flat_pct": 1.0,    # daily fee 1% of amount
        "processing_fee_pct": 0.0,
    },
    "tala": {
        "lender": "Tala",
        "product": "Tala Digital Credit",
        "interest_rate_flat_pct": 15.0,
        "processing_fee_pct": 2.0,
    },
    "branch": {
        "lender": "Branch",
        "product": "Branch International",
        "interest_rate_flat_pct": 17.0,
        "processing_fee_pct": 2.0,
    },
    "equitel": {
        "lender": "Equitel",
        "product": "Equitel Eazzy Loan",
        "interest_rate_flat_pct": 6.5,
        "processing_fee_pct": 1.5,
    },
}


_cost_engine = CostEngine()


def compute_ear(principal: int, total_repayable: int, term_days: int) -> float:
    """Effective Annual Rate from total repayment, as a percentage.

    Delegates to CostEngine.compute_ear_single so both the named-lender
    comparison table and the generic financing-tool pipeline use the same
    EAR formula instead of two independently maintained copies.
    """
    if term_days <= 0 or principal <= 0:
        return 0.0
    _, ear = _cost_engine.compute_ear_single(principal, total_repayable, term_days)
    return ear * 100


def compute_tcc(principal: int, fees: int, interest: int) -> float:
    """Total Cost of Credit as % of principal."""
    if principal <= 0:
        return 0.0
    return ((fees + interest) / principal) * 100


class MockLender:
    """Generates and compares loan offers from Kenyan digital lenders."""

    @staticmethod
    def get_offer(product_key: str, principal_minor: int, term_days: int) -> LoanOffer:
        """Generate a loan offer for a specific product."""
        p = PRODUCTS[product_key]
        fee = int(principal_minor * p["processing_fee_pct"] / 100)
        interest = int(principal_minor * p["interest_rate_flat_pct"] / 100)

        disbursed = principal_minor - fee
        total_repayable = principal_minor + interest
        daily_payment = int(math.ceil(total_repayable / term_days))

        return LoanOffer(
            lender=p["lender"],
            product=p["product"],
            principal_minor=principal_minor,
            term_days=term_days,
            interest_rate_flat_pct=p["interest_rate_flat_pct"],
            processing_fee_pct=p["processing_fee_pct"],
            disbursed_minor=disbursed,
            daily_repayment_minor=daily_payment,
            total_repayable_minor=total_repayable,
            ear_pct=compute_ear(principal_minor, total_repayable, term_days),
            tcc_pct=compute_tcc(principal_minor, fee, interest),
        )

    @staticmethod
    def compare_all(principal_minor: int, term_days: int) -> List[LoanOffer]:
        """Get all available offers sorted by EAR (lowest first)."""
        offers = []
        for key in PRODUCTS:
            try:
                offer = MockLender.get_offer(key, principal_minor, term_days)
                offers.append(offer)
            except Exception:
                continue
        offers.sort(key=lambda o: o.ear_pct)
        return offers

    @staticmethod
    def best_offer(principal_minor: int, term_days: int,
                   affordability_daily_budget: int = 0) -> Optional[LoanOffer]:
        """Get the best affordable offer. Returns None if none affordable."""
        offers = MockLender.compare_all(principal_minor, term_days)
        if affordability_daily_budget > 0:
            offers = [o for o in offers if o.daily_repayment_minor <= affordability_daily_budget]
        return offers[0] if offers else None

    @staticmethod
    def offer_summary(offers: List[LoanOffer]) -> str:
        """Human-readable comparison of offers."""
        lines = ["| Lender | Product | KES/Day | Total Repay | EAR% | TCC% |",
                 "|--------|---------|---------|-------------|------|------|"]
        for o in offers:
            lines.append(
                f"| {o.lender} | {o.product} | {o.daily_repayment_minor:,} | "
                f"{o.total_repayable_minor:,} | {o.ear_pct:.1f} | {o.tcc_pct:.1f} |"
            )
        return "\n".join(lines)
