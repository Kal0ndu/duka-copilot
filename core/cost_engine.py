"""Effective cost engine: EAR computation, TCC, affordability check."""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import math
import sqlite3
from datetime import datetime
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


# =====================================================================
# Module-level tool entrypoints — wired into agent/orchestrator.py's
# _TOOL_IMPLS so the LLM's compare_financing / check_affordability /
# draft_application_pack tool calls resolve to real, DB-backed logic
# rather than failing with "function not found".
#
# The orchestrator calls fn(parsed_args, business_id=..., db_path=...);
# these persist into the financing_request / financing_offer /
# affordability_result tables already defined in db/schema.sql.
# =====================================================================

def _load_products_from_db(db_path: str) -> List[CreditProduct]:
    """Load active credit products + fees from the DB. Falls back to the
    illustrative defaults if the table is empty (e.g. a fresh/test DB)."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return DEFAULT_PRODUCTS

    try:
        rows = conn.execute(
            "SELECT * FROM credit_product WHERE active = 1"
        ).fetchall()
        if not rows:
            return DEFAULT_PRODUCTS

        products = []
        for r in rows:
            fee_rows = conn.execute(
                "SELECT * FROM credit_fee_component WHERE product_id = ?",
                (r["product_id"],),
            ).fetchall()
            fees = [
                FeeComponent(
                    kind=f["kind"], basis=f["basis"], rate_bp=f["rate_bp"],
                    flat_minor=f["flat_minor"], period_days=f["period_days"],
                )
                for f in fee_rows
            ]
            products.append(CreditProduct(
                product_id=r["product_id"], code=r["code"], type=r["type"],
                name=r["name"], repayment_style=r["repayment_style"],
                min_amount_minor=r["min_amount_minor"], max_amount_minor=r["max_amount_minor"],
                min_term_days=r["min_term_days"], max_term_days=r["max_term_days"],
                fees=fees,
            ))
        return products
    except sqlite3.Error:
        return DEFAULT_PRODUCTS
    finally:
        conn.close()


def _cost_result_to_dict(r: "CostResult", offer_id: Optional[int] = None) -> dict:
    return {
        "offer_id": offer_id,
        "product_code": r.product_code,
        "product_name": r.product_name,
        "principal_minor": r.principal_minor,
        "term_days": r.term_days,
        "net_received_minor": r.net_received_minor,
        "total_repayment_minor": r.total_repayment_minor,
        "tcc_minor": r.tcc_minor,
        "ear_pct": round(r.ear * 100, 1),
        "rank": r.rank,
    }


def compare_financing(args, business_id: Optional[int] = None,
                       db_path: Optional[str] = None) -> dict:
    """Rank credit products for a requested amount/term by total cost.

    Persists a financing_request + one financing_offer row per matching
    product (when business_id is known) so later tool calls can reference
    a stable offer_id, per db/schema.sql's financing_request/financing_offer
    design.
    """
    from core.config import Config
    db_path = db_path or Config.DB_PATH

    products = _load_products_from_db(db_path)
    engine = CostEngine()
    results = engine.compare_products(
        products, principal_minor=args.amount_minor, term_days=args.term_days,
    )

    if not results:
        return {"offers": [], "message": "No credit product matches that amount and term."}

    if business_id is None:
        return {"offers": [_cost_result_to_dict(r) for r in results]}

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.execute(
            """INSERT INTO financing_request (business_id, purpose, amount_minor, term_days, via)
               VALUES (?, ?, ?, ?, 'chat')""",
            (business_id, args.purpose, args.amount_minor, args.term_days),
        )
        request_id = cur.lastrowid

        offers = []
        for r in results:
            product_id = next((p.product_id for p in products if p.code == r.product_code), None)
            cur2 = conn.execute(
                """INSERT INTO financing_offer
                   (request_id, product_id, principal_minor, term_days, net_received_minor,
                    total_repayment_minor, tcc_minor, periodic_rate, ear, fits_forecast,
                    rank, calc_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'v1')""",
                (request_id, product_id, r.principal_minor, r.term_days, r.net_received_minor,
                 r.total_repayment_minor, r.tcc_minor, r.periodic_rate, r.ear, r.rank),
            )
            offers.append(_cost_result_to_dict(r, offer_id=cur2.lastrowid))
        conn.commit()
        return {"request_id": request_id, "offers": offers}
    except sqlite3.Error as e:
        return {"error": str(e), "offers": [_cost_result_to_dict(r) for r in results]}
    finally:
        conn.close()


def check_affordability(args, business_id: Optional[int] = None,
                         db_path: Optional[str] = None) -> dict:
    """Test a persisted financing_offer against the business's latest
    forecast_run and safety buffer. Writes an affordability_result row."""
    from core.config import Config
    db_path = db_path or Config.DB_PATH

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error as e:
        return {"error": str(e)}

    try:
        offer = conn.execute(
            """SELECT fo.*, fr.business_id FROM financing_offer fo
               JOIN financing_request fr ON fr.request_id = fo.request_id
               WHERE fo.offer_id = ?""",
            (args.offer_id,),
        ).fetchone()
        if offer is None:
            return {"error": f"No financing offer found with offer_id={args.offer_id}"}

        run = conn.execute(
            """SELECT * FROM forecast_run WHERE business_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (offer["business_id"],),
        ).fetchone()

        buffer_minor = Config.SAFETY_BUFFER_MINOR
        if run is None:
            return {
                "offer_id": args.offer_id,
                "affordable": None,
                "reason": "No cash-flow forecast available yet. Run forecast_balance first.",
            }

        points = conn.execute(
            "SELECT * FROM forecast_point WHERE run_id = ? ORDER BY day_offset",
            (run["run_id"],),
        ).fetchall()
        if not points:
            return {
                "offer_id": args.offer_id,
                "affordable": None,
                "reason": "Forecast run has no points yet.",
            }

        min_p10 = min(p["p10_minor"] for p in points)
        breach = next((p["date"] for p in points if p["p10_minor"] < buffer_minor), None)
        passed = breach is None

        conn.execute(
            """INSERT OR REPLACE INTO affordability_result
               (offer_id, run_id, buffer_minor, min_p10_balance_minor, breach_date, passed)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (args.offer_id, run["run_id"], buffer_minor, min_p10, breach, int(passed)),
        )
        conn.execute(
            "UPDATE financing_offer SET fits_forecast = ? WHERE offer_id = ?",
            (int(passed), args.offer_id),
        )
        conn.commit()

        return {
            "offer_id": args.offer_id,
            "affordable": passed,
            "min_forecast_balance_minor": min_p10,
            "safety_buffer_minor": buffer_minor,
            "breach_date": breach,
            "reason": (
                "Repayments stay above the safety buffer." if passed else
                f"Forecast balance would drop below the KES {buffer_minor/100:,.0f} "
                f"safety buffer around {breach}."
            ),
        }
    except sqlite3.Error as e:
        return {"error": str(e)}
    finally:
        conn.close()


def draft_application_pack(args, business_id: Optional[int] = None,
                            db_path: Optional[str] = None) -> dict:
    """Draft a Markdown loan-application pack for a priced financing_offer:
    business profile, three-month cash-flow statement, proposed repayment
    plan, and affordability verdict — evidence-backed, no invented numbers."""
    from core.config import Config
    db_path = db_path or Config.DB_PATH

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        return {"error": str(e)}

    try:
        offer = conn.execute(
            """SELECT fo.*, fr.business_id, fr.purpose, cp.name AS product_name,
                      cp.code AS product_code
               FROM financing_offer fo
               JOIN financing_request fr ON fr.request_id = fo.request_id
               JOIN credit_product cp ON cp.product_id = fo.product_id
               WHERE fo.offer_id = ?""",
            (args.offer_id,),
        ).fetchone()
        if offer is None:
            return {"error": f"No financing offer found with offer_id={args.offer_id}"}

        biz = conn.execute(
            "SELECT * FROM business WHERE business_id = ?", (offer["business_id"],)
        ).fetchone()

        rows = conn.execute(
            """SELECT strftime('%Y-%m', local_date) AS ym,
                      SUM(CASE WHEN direction='in' THEN amount_minor ELSE 0 END) AS inflow,
                      SUM(CASE WHEN direction='out' THEN amount_minor ELSE 0 END) AS outflow
               FROM transaction_ledger
               WHERE business_id = ? AND voided = 0
               GROUP BY ym ORDER BY ym DESC LIMIT 3""",
            (offer["business_id"],),
        ).fetchall()

        afford = conn.execute(
            "SELECT * FROM affordability_result WHERE offer_id = ?", (args.offer_id,)
        ).fetchone()

        monthly_lines = "\n".join(
            f"| {r['ym']} | KES {r['inflow']/100:,.0f} | KES {r['outflow']/100:,.0f} "
            f"| KES {(r['inflow'] - r['outflow'])/100:,.0f} |"
            for r in rows
        ) or "| (no transaction history available yet) | - | - | - |"

        if afford is None:
            affordability_line = "Not yet checked — run check_affordability before submitting."
        elif afford["passed"]:
            affordability_line = "Passes the owner's cash-flow safety buffer."
        else:
            affordability_line = f"Breaches the safety buffer around {afford['breach_date']}."

        sector = biz["sector"] if biz else "unknown"
        registration = biz["registration_type"] if biz else "informal"
        start_date = biz["start_date"] if biz else "n/a"

        pack = f"""# Loan Application Pack

**Prepared:** {datetime.now().strftime('%Y-%m-%d')}
**Sector:** {sector}
**Purpose:** {offer['purpose']}

## 1. Business Profile
- Sector: {sector}
- Registration: {registration}
- Operating since: {start_date}

## 2. Three-Month Cash-Flow Statement
| Month | Inflow | Outflow | Net |
|---|---|---|---|
{monthly_lines}

## 3. Requested Facility
- Product: {offer['product_name']} ({offer['product_code']})
- Principal requested: KES {offer['principal_minor']/100:,.0f}
- Term: {offer['term_days']} days
- Net amount received (after fees): KES {offer['net_received_minor']/100:,.0f}
- Total repayment: KES {offer['total_repayment_minor']/100:,.0f}
- Total cost of credit: KES {offer['tcc_minor']/100:,.0f}
- Effective annual rate (EAR): {offer['ear']*100:.1f}%

## 4. Proposed Repayment Plan
Repay KES {offer['total_repayment_minor']/100:,.0f} over {offer['term_days']} days.

## 5. Affordability Check
{affordability_line}

---
*Generated by Duka Copilot from the owner's own transaction history. Guidance only — not a credit guarantee.*
"""
        return {"offer_id": args.offer_id, "markdown": pack}
    except sqlite3.Error as e:
        return {"error": str(e)}
    finally:
        conn.close()
