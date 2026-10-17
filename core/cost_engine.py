"""Effective cost engine: EAR computation, TCC, affordability check."""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import math
from scipy.optimize import brentq


@dataclass
class FeeComponent:
    kind: str  # upfront_pct, upfront_flat, periodic_pct, periodic_flat
    basis: str  # principal, outstanding, flat
    rate_bp: Optional[int] = None
    flat_minor: Optional[int] = None
    period_days: Optional[int] = None


@dataclass
class CreditProduct:
    product_id: int
    code: str
    type: str
    name: str
    repayment_style: str  # single, equal_installments, revolving
    min_amount_minor: int
    max_amount_minor: int
    min_term_days: int
    max_term_days: int
    fees: List[FeeComponent]


@dataclass
class CostResult:
    product_code: str
    product_name: str
    principal_minor: int
    term_days: int
    net_received_minor: int
    total_repayment_minor: int
    tcc_minor: int  # total cost of credit
    ear: float  # 0.41 = 41%
    periodic_rate: float
    fits_forecast: bool = False
    min_margin_minor: int = 0
    rank: int = 0


class CostEngine:
    """Compute total cost of credit (TCC) and effective annual rate (EAR)."""

    def compute_ear_single(self, principal: int, total_repayable: int,
                           term_days: int) -> Tuple[float, float]:
        """
        For single-payment loans: EAR = (R/P)^(365/d) - 1.
        Returns (periodic_rate, ear).
        """
        r = total_repayable / principal
        ear = r ** (365.0 / term_days) - 1.0
        return (r - 1.0), ear

    def compute_ear_installments(self, principal: int, installment_amount: int,
                                  n_installments: int, period_days: int) -> Tuple[float, float]:
        """
        For equal-installment loans: solve IRR via Brent's method.
        period_days is the interval between installments.
        """
        def npv(rate):
            pv = -principal
            for i in range(1, n_installments + 1):
                pv += installment_amount / ((1 + rate) ** i)
            return pv

        try:
            periodic_rate = brentq(npv, 0.0, 2.0, maxiter=100)
        except (ValueError, RuntimeError):
            # Fallback: approximate
            total = installment_amount * n_installments
            periodic_rate = (total / principal) ** (1.0 / n_installments) - 1.0

        periods_per_year = 365.0 / period_days
        ear = (1 + periodic_rate) ** periods_per_year - 1.0
        return periodic_rate, ear

    def price_product(self, product: CreditProduct, principal: int = 0,
                      term_days: int = 30, principal_minor: Optional[int] = None) -> CostResult:
        """Price a credit product for a given principal and term."""
        if principal_minor is not None:
            principal = principal_minor

        total_fees = 0
        upfront_flat = 0
        upfront_pct = 0.0
        periodic_flat = 0
        periodic_pct = 0.0

        for fee in product.fees:
            if fee.kind == "upfront_flat":
                upfront_flat += fee.flat_minor or 0
            elif fee.kind == "upfront_pct":
                upfront_pct += (fee.rate_bp or 0) / 10000.0
            elif fee.kind == "periodic_flat":
                periods = term_days / (fee.period_days or 30)
                periodic_flat += (fee.flat_minor or 0) * int(periods)
            elif fee.kind == "periodic_pct":
                periodic_pct += (fee.rate_bp or 0) / 10000.0

        # Net received = principal minus upfront fees
        upfront_fee = int(round(principal * upfront_pct)) + upfront_flat
        net_received = principal - upfront_fee

        if product.repayment_style == "single":
            # Total repayment = principal + periodic interest
            # Single-payment: charge periodic_pct on principal for the term
            periods = term_days / 30.0  # monthly equivalent
            interest = int(round(principal * periodic_pct * periods))
            total_repayment = principal + interest + periodic_flat
            periodic_rate, ear = self.compute_ear_single(
                net_received, total_repayment, term_days
            )
        elif product.repayment_style == "equal_installments":
            n = max(1, term_days // 30)  # monthly installments
            # Amortise principal + interest
            monthly_rate = periodic_pct
            if monthly_rate > 0:
                installment = int(round(
                    principal * monthly_rate * (1 + monthly_rate) ** n
                    / ((1 + monthly_rate) ** n - 1)
                ))
            else:
                installment = principal // n
            total_repayment = installment * n + periodic_flat
            periodic_rate, ear = self.compute_ear_installments(
                net_received, installment, n, 30
            )
        else:
            # Revolving: simple approximation
            total_repayment = principal + int(round(principal * periodic_pct))
            periodic_rate, ear = self.compute_ear_single(
                net_received, total_repayment, term_days
            )

        tcc = total_repayment - net_received

        return CostResult(
            product_code=product.code,
            product_name=product.name,
            principal_minor=principal,
            term_days=term_days,
            net_received_minor=net_received,
            total_repayment_minor=total_repayment,
            tcc_minor=tcc,
            ear=ear,
            periodic_rate=periodic_rate,
        )

    def compare_products(self, products: List[CreditProduct], principal: int = 0,
                         term_days: int = 30, principal_minor: Optional[int] = None) -> List[CostResult]:
        """Rank products by total cost of credit."""
        if principal_minor is not None:
            principal = principal_minor
        results = []
        for p in products:
            if principal < p.min_amount_minor or principal > p.max_amount_minor:
                continue
            if term_days < p.min_term_days or term_days > p.max_term_days:
                continue
            results.append(self.price_product(p, principal=principal, term_days=term_days))

        results.sort(key=lambda r: r.tcc_minor)
        for i, r in enumerate(results):
            r.rank = i + 1
        return results

    def check_affordability(self, item, *args, **kwargs):
        """Check if repayment fits. Supports both (result, forecast_points, buffer) and (product, principal_minor, term_days, daily_surplus_minor)."""
        if isinstance(item, CreditProduct):
            principal = kwargs.get("principal_minor", args[0] if len(args) > 0 else 0)
            term_days = kwargs.get("term_days", args[1] if len(args) > 1 else 30)
            daily_surplus = kwargs.get("daily_surplus_minor", args[2] if len(args) > 2 else 0)
            cost = self.price_product(item, principal=principal, term_days=term_days)
            daily_repay = cost.total_repayment_minor / max(1, term_days)
            return bool(daily_surplus >= daily_repay)

        # Standard check with forecast points
        forecast_points = args[0] if len(args) > 0 else kwargs.get("forecast_points", [])
        buffer_minor = args[1] if len(args) > 1 else kwargs.get("buffer_minor", 0)
        if not forecast_points:
            return True, 0

        repayment_day = min(item.term_days, len(forecast_points) - 1)
        pt = forecast_points[repayment_day]
        margin = pt["p10"] - item.total_repayment_minor - buffer_minor
        return margin >= 0, int(margin)

    def affordability_check(self, daily_repayment: int, avg_daily_profit: int, buffer_minor: int = 0) -> dict:
        """Simple rule-based check for daily repayment against profit and buffer."""
        affordable = avg_daily_profit >= daily_repayment
        return {
            "affordable": bool(affordable),
            "daily_repayment": daily_repayment,
            "avg_daily_profit": avg_daily_profit,
            "buffer_minor": buffer_minor,
            "reason": "Affordable based on current profit" if affordable else f"Repayment KES {daily_repayment:,.0f}/day exceeds profit KES {avg_daily_profit:,.0f}/day",
        }

    def detect_shortfalls(self, balances: List[int], buffer: int = 0) -> List[int]:
        """Detect any balances dropping below safety buffer."""
        return [b for b in balances if b < buffer]


# Default illustrative products (from seed data)
DEFAULT_PRODUCTS = [
    CreditProduct(
        product_id=1, code="MOBILE_OVERDRAFT", type="mobile_overdraft",
        name="Mobile overdraft", repayment_style="single",
        min_amount_minor=10000, max_amount_minor=10000000,
        min_term_days=1, max_term_days=30,
        fees=[FeeComponent(kind="upfront_pct", basis="principal", rate_bp=600)],
    ),
    CreditProduct(
        product_id=2, code="MOBILE_MICROLOAN", type="mobile_microloan",
        name="Mobile micro-loan", repayment_style="single",
        min_amount_minor=50000, max_amount_minor=20000000,
        min_term_days=7, max_term_days=60,
        fees=[FeeComponent(kind="upfront_pct", basis="principal", rate_bp=900)],
    ),
    CreditProduct(
        product_id=3, code="SACCO_LOAN", type="sacco_loan",
        name="SACCO loan", repayment_style="equal_installments",
        min_amount_minor=500000, max_amount_minor=100000000,
        min_term_days=30, max_term_days=730,
        fees=[
            FeeComponent(kind="periodic_pct", basis="outstanding", rate_bp=150, period_days=30),
            FeeComponent(kind="upfront_flat", basis="flat", flat_minor=50000),
        ],
    ),
    CreditProduct(
        product_id=4, code="BANK_SME_LOAN", type="bank_sme_loan",
        name="Bank SME loan", repayment_style="equal_installments",
        min_amount_minor=1000000, max_amount_minor=500000000,
        min_term_days=90, max_term_days=1095,
        fees=[
            FeeComponent(kind="periodic_pct", basis="outstanding", rate_bp=120, period_days=30),
            FeeComponent(kind="upfront_pct", basis="principal", rate_bp=200),
        ],
    ),
]
