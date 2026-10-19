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
            """SELECT fo.*, fr.business_id, cp.repayment_style FROM financing_offer fo
               JOIN financing_request fr ON fr.request_id = fo.request_id
               JOIN credit_product cp ON cp.product_id = fo.product_id
               WHERE fo.offer_id = ?""",
            (args.offer_id,),
        ).fetchone()
        # Another business's offer is "not found", never shown.
        if offer is None or (business_id is not None and offer["business_id"] != business_id):
            return {"error": f"No financing offer found with offer_id={args.offer_id}"}

        run = conn.execute(
            """SELECT * FROM forecast_run WHERE business_id = ?
               ORDER BY run_id DESC LIMIT 1""",
            (offer["business_id"],),
        ).fetchone()

        from core.owner_settings import load_settings
        buffer_minor = load_settings(db_path, offer["business_id"]).safety_buffer_minor
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

        # Low estimate WITH the loan: the money comes in on day 0 and each
        # repayment leaves on its due day.
        schedule = repayment_schedule(offer["repayment_style"], offer["term_days"],
                                      offer["total_repayment_minor"])
        def with_loan(p):
            due = sum(amt for day, amt in schedule if day <= p["day_offset"])
            return p["p10_minor"] + offer["net_received_minor"] - due
        min_p10 = min(with_loan(p) for p in points)
        breach = next((p["date"] for p in points if with_loan(p) < buffer_minor), None)
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
            "forecast_days_checked": len(points) - 1,
            "repayments_beyond_forecast": sum(1 for day, _ in schedule if day > points[-1]["day_offset"]),
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
        if offer is None or (business_id is not None and offer["business_id"] != business_id):
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


# =====================================================================
# Loan fit check: does a loan fit the forecast, and what weekly personal
# spending would make it fit? (ported from duka-copilot main's credit.py)
# =====================================================================

RANGE_Z = 1.28          # ~80% band, like the forecast's p10..p90
ERROR_GROWTH_DAYS = 14  # the band widens for two weeks, then we assume a re-forecast
ROUND_TO_MINOR = 500_000  # recommend amounts in steps of KES 5,000


def repayment_schedule(repayment_style: str, term_days: int, total_repayment_minor: int):
    """[(day, amount_minor)] for a priced offer."""
    if repayment_style == "equal_installments":
        n = max(1, term_days // 30)
        each = total_repayment_minor // n
        days = [30 * (i + 1) for i in range(n)]
        amounts = [each] * (n - 1) + [total_repayment_minor - each * (n - 1)]
        return list(zip(days, amounts))
    return [(term_days, total_repayment_minor)]


def _cash_model(rows):
    """Average business net per weekday (sales minus business costs, no
    borrowing, no personal money), personal money per day, and the typical
    daily error."""
    import statistics
    from datetime import datetime as _dt, timedelta as _td
    from core.forecaster import _BORROWING_CATEGORIES

    personal_codes = {"PERSONAL_WITHDRAWAL", "FAMILY_TRANSFER", "SCHOOL_FEES", "PERSONAL_OTHER"}
    start = _dt.strptime(rows[0]["local_date"], "%Y-%m-%d")
    end = _dt.strptime(rows[-1]["local_date"], "%Y-%m-%d")
    days = [(start + _td(days=k)).strftime("%Y-%m-%d") for k in range((end - start).days + 1)]
    business = {d: 0 for d in days}
    personal = {d: 0 for d in days}
    for r in rows:
        if r["channel"] == "overdraft" or r["category"] in _BORROWING_CATEGORIES:
            continue
        signed = r["amount_minor"] if r["direction"] == "in" else -r["amount_minor"]
        if r["direction"] == "out" and r["category"] in personal_codes:
            personal[r["local_date"]] += r["amount_minor"]
        else:
            business[r["local_date"]] += signed
    by_wd = {}
    for d in days:
        by_wd.setdefault(_dt.strptime(d, "%Y-%m-%d").weekday(), []).append(business[d])
    wd_avg = {w: sum(v) / len(v) for w, v in by_wd.items()}
    personal_per_day = sum(personal.values()) / len(days)
    residuals = [business[d] - personal[d] - (wd_avg[_dt.strptime(d, "%Y-%m-%d").weekday()] - personal_per_day)
                 for d in days]
    return {"wd_avg": wd_avg, "personal_per_day": personal_per_day,
            "daily_error": statistics.pstdev(residuals) if len(residuals) > 1 else 0.0,
            "last_date": end}


def _lowest_low(model, position, net_received, schedule, personal_scale=1.0, horizon=None):
    """Lowest low estimate of cash over the loan's life (or `horizon` days)."""
    from datetime import timedelta as _td
    from math import sqrt
    due = {}
    for day, amt in schedule:
        due[day] = due.get(day, 0) + amt
    last_day = horizon or max(due) if due else (horizon or 14)
    cash = position + net_received
    lowest = None
    for k in range(1, last_day + 1):
        wd = (model["last_date"] + _td(days=k)).weekday()
        cash += model["wd_avg"].get(wd, 0) - model["personal_per_day"] * personal_scale - due.get(k, 0)
        low = cash - RANGE_Z * model["daily_error"] * sqrt(min(k, ERROR_GROWTH_DAYS))
        lowest = low if lowest is None else min(lowest, low)
    return lowest


def _personal_cap_scale(model, position, offer, buffer):
    """Largest share (0..1) of today's personal spending that still lets the
    offer fit; None if it can't fit even with no personal spending."""
    def ok(scale):
        return _lowest_low(model, position, offer["net_received_minor"], offer["schedule"], scale) >= buffer
    if ok(1.0):
        return 1.0
    if not ok(0.0):
        return None
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


def plain_advice(h: dict, lang: str = "en") -> str:
    """The recommendation in plain words (never 'raise your cap')."""
    kes = lambda m: f"KES {m / 100:,.0f}"
    best = h.get("best")
    if h.get("no_need"):
        if lang == "sw":
            return (f"Huhitaji mkopo sasa: utabiri wa siku 14 unabaki juu ya akiba yako ya usalama ya "
                    f"{kes(h['safety_buffer_minor'])}. Kukopa bila hitaji kungeongeza gharama tu.")
        return (f"You don't need a loan right now: the 14-day forecast stays above your "
                f"{kes(h['safety_buffer_minor'])} safety buffer. Borrowing without a need would only add cost.")
    if lang == "sw":
        if best is None:
            return (f"Hakuna mkopo ndani ya kikomo chako cha {kes(h['loan_cap_minor'])} unaoweza kulipwa "
                    f"kwa usalama, hata bila kutoa pesa za matumizi binafsi. Kukopa zaidi hakutasaidia.")
        lines = []
        if h["over_cap"]:
            lines.append(f"Unahitaji takriban {kes(h['needed_minor'])}, zaidi ya kikomo chako cha mkopo cha "
                         f"{kes(h['loan_cap_minor'])}. Mkopo mkubwa zaidi unaoweza kulipwa ndani ya kikomo ni "
                         f"{kes(h['amount_minor'])}.")
        if best["fits_now"]:
            lines.append(f"Pendekezo: {best['product_name']} ya {kes(h['amount_minor'])} kwa siku "
                         f"{h['term_days']}. Inafaa bila kubadilisha matumizi yako binafsi.")
        else:
            lines.append(f"Pendekezo: {best['product_name']} ya {kes(h['amount_minor'])} kwa siku "
                         f"{h['term_days']}, ukiweka pesa za matumizi binafsi kuwa "
                         f"{kes(best['max_weekly_personal_minor'])} kwa wiki (sasa "
                         f"{kes(h['weekly_personal_now_minor'])}).")
        lines.append("Viwango vya SACCO na benki ni mifano tu, si bei halisi.")
        return " ".join(lines)
    if best is None:
        return (f"No loan within your {kes(h['loan_cap_minor'])} loan cap can be repaid safely, even with "
                f"no personal money taken out. Borrowing more would not help.")
    lines = []
    if h["over_cap"]:
        lines.append(f"You need about {kes(h['needed_minor'])}, which is more than your loan cap of "
                     f"{kes(h['loan_cap_minor'])}. The largest affordable loan within your cap is "
                     f"{kes(h['amount_minor'])}.")
    if best["fits_now"]:
        lines.append(f"Recommended: {best['product_name']} of {kes(h['amount_minor'])} over "
                     f"{h['term_days']} days. It fits without changing your personal spending.")
    else:
        cut = h["weekly_personal_now_minor"] - best["max_weekly_personal_minor"]
        lines.append(f"Recommended: {best['product_name']} of {kes(h['amount_minor'])} over "
                     f"{h['term_days']} days, if you keep personal money to "
                     f"{kes(best['max_weekly_personal_minor'])} a week (now "
                     f"{kes(h['weekly_personal_now_minor'])}: down {kes(cut)}).")
    lines.append("SACCO and bank rates are illustrative, not real quotes.")
    return " ".join(lines)


def recommend_loan(args, business_id: Optional[int] = None,
                   db_path: Optional[str] = None) -> dict:
    """Check each loan option against the cash-flow forecast.

    For each option: does the low estimate stay above the owner's safety
    buffer for the whole loan, and if not, what weekly personal spending
    would make it fit. Recommends the cheapest option that can fit, never
    above the owner's loan cap. With no amount given it uses what the
    forecast says is needed to stay above the buffer."""
    from types import SimpleNamespace
    from core.config import Config
    from core.forecaster import _ledger_rows, true_position
    from core.owner_settings import load_settings

    db_path = db_path or Config.DB_PATH
    if business_id is None:
        return {"error": "business_id required"}
    lang = getattr(args, "language", None) or "en"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = _ledger_rows(conn, business_id)
        if len(rows) < 2:
            return {"error": "Upload a statement first: the loan check needs your cash-flow history."}
        position = true_position(conn, business_id)["true_position_minor"]
    finally:
        conn.close()
    settings = load_settings(db_path, business_id)
    buffer, loan_cap = settings.safety_buffer_minor, settings.loan_cap_minor
    model = _cash_model(rows)

    low14 = _lowest_low(model, position, 0, [], 1.0, horizon=14)
    needed = max(0, int(buffer - low14))
    if needed == 0 and not args.amount_minor:
        h = {"amount_minor": 0, "term_days": args.term_days, "needed_minor": 0, "no_need": True,
             "true_position_minor": position, "safety_buffer_minor": buffer, "loan_cap_minor": loan_cap,
             "over_cap": False, "weekly_personal_now_minor": int(model["personal_per_day"] * 7),
             "options": [], "best": None}
        h["advice"] = plain_advice(h, lang)
        return h
    target = args.amount_minor or max(ROUND_TO_MINOR, -(-needed // ROUND_TO_MINOR) * ROUND_TO_MINOR)
    top = min(target, loan_cap)
    amounts = [top] + [a for a in range((top // ROUND_TO_MINOR) * ROUND_TO_MINOR, 0, -ROUND_TO_MINOR) if a < top]
    if args.amount_minor:
        amounts = [top]

    products = {p.code: p for p in _load_products_from_db(db_path)}
    weekly_now = model["personal_per_day"] * 7
    chosen = None
    for amount in amounts:
        priced = compare_financing(
            SimpleNamespace(amount_minor=amount, term_days=args.term_days, purpose="stock"),
            business_id=business_id, db_path=db_path,
        )
        options = []
        for o in priced.get("offers", []):
            style = products[o["product_code"]].repayment_style if o["product_code"] in products else "single"
            o = dict(o, schedule=repayment_schedule(style, o["term_days"], o["total_repayment_minor"]))
            scale = _personal_cap_scale(model, position, o, buffer)
            o["fits_now"] = scale == 1.0
            o["max_weekly_personal_minor"] = None if scale is None else int(weekly_now * scale)
            del o["schedule"]
            options.append(o)
        fitting = [o for o in options if o["max_weekly_personal_minor"] is not None]
        chosen = (amount, options, min(fitting, key=lambda o: o["tcc_minor"]) if fitting else None)
        if fitting:
            break

    amount, options, best = chosen if chosen else (top, [], None)
    h = {
        "amount_minor": amount, "term_days": args.term_days, "needed_minor": needed,
        "true_position_minor": position, "safety_buffer_minor": buffer, "loan_cap_minor": loan_cap,
        "over_cap": target > loan_cap, "weekly_personal_now_minor": int(weekly_now),
        "options": options, "best": best,
    }
    h["advice"] = plain_advice(h, lang)
    h["note"] = "SACCO and bank rates are ILLUSTRATIVE, not real quotes."
    return h
