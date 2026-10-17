"""Spending advisor: purchase decisions and cash allocation guidance."""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import sqlite3
import pandas as pd
import numpy as np

from core.config import config
from core.forecaster import BalanceForecaster


@dataclass
class PurchaseAdvice:
    verdict: str  # "GO", "WAIT", "NO"
    confidence: int  # 0-100
    reasons: List[str] = field(default_factory=list)
    balance_before_minor: int = 0
    balance_after_minor: int = 0
    buffer_minor: int = 0
    days_of_cash_after: int = 0
    upcoming_obligations_minor: int = 0
    shortfall_risk_bp: int = 0
    suggested_actions: List[str] = field(default_factory=list)


@dataclass
class AllocationAdvice:
    allocations: List[Dict] = field(default_factory=list)  # {label, amount_minor, priority, rationale}
    warnings: List[str] = field(default_factory=list)
    available_cash_minor: int = 0
    total_obligations_minor: int = 0
    buffer_target_minor: int = 0
    surplus_minor: int = 0


class SpendingAdvisor:
    """Advise on purchase decisions and cash allocation priorities."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.DB_PATH

    # ------------------------------------------------------------------
    # Purchase advice
    # ------------------------------------------------------------------

    def advise_on_purchase(
        self,
        business_id: int,
        purchase_amount_minor: int,
        purchase_label: str = "",
        expected_roi_pct: float = 0.0,
    ) -> PurchaseAdvice:
        """Evaluate whether a purchase is advisable.

        Returns a PurchaseAdvice with verdict (GO/WAIT/NO), reasons,
        impact analysis, and confidence.
        """
        reasons: List[str] = []
        suggested: List[str] = []
        confidence_deduct = 0

        current_balance = self._get_current_balance(business_id)
        avg_daily_outflow = self._get_avg_daily_outflow(business_id)
        buffer_target = self._get_buffer_target(business_id)
        upcoming_obl = self._get_upcoming_obligations_total(business_id, days=14)
        raw_margin = self._get_gross_margin_pct(business_id)

        balance_after = current_balance - purchase_amount_minor
        days_of_cash = (balance_after / avg_daily_outflow) if avg_daily_outflow > 0 else 999
        shortfall_risk = 0

        # --- evidence gathering ---
        if avg_daily_outflow <= 0:
            confidence_deduct += 30
            reasons.append("Limited transaction history — cashflow estimates may be unreliable.")

        # --- verdict logic ---
        verdict = "GO"

        # Rule 1: Insufficient balance outright
        if purchase_amount_minor > current_balance:
            reasons.append(
                f"Insufficient balance: purchase (KES {purchase_amount_minor/100:,.0f}) "
                f"exceeds current balance (KES {current_balance/100:,.0f})."
            )
            suggested.append("Wait until more cash is available before making this purchase.")
            verdict = "NO"
            confidence_deduct += 40

        # Rule 2: Would drop below buffer
        if verdict != "NO" and balance_after < buffer_target:
            gap = buffer_target - balance_after
            reasons.append(
                f"After purchase, balance (KES {balance_after/100:,.0f}) would fall "
                f"KES {gap/100:,.0f} below the safety buffer (KES {buffer_target/100:,.0f})."
            )
            suggested.append(
                f"Build up at least KES {gap/100:,.0f} more in reserves first, "
                f"or consider a smaller purchase."
            )
            verdict = "NO"
            confidence_deduct += 10

        # Rule 3: Upcoming obligations risk
        if verdict != "NO" and upcoming_obl > 0:
            remaining_after_obl = balance_after - upcoming_obl
            if remaining_after_obl < buffer_target:
                reasons.append(
                    f"KES {upcoming_obl/100:,.0f} in obligations due within 14 days. "
                    f"After both purchase and obligations, buffer would be depleted."
                )
                suggested.append(
                    f"Wait until after the upcoming KES {upcoming_obl/100:,.0f} "
                    f"in obligations are paid, then re-evaluate."
                )
                verdict = "WAIT"
                confidence_deduct += 10
                shortfall_risk = max(0, min(10000, int((buffer_target - remaining_after_obl) / max(buffer_target, 1) * 10000)))

        # Rule 4: Cash runway assessment
        if verdict == "GO" and days_of_cash < 7:
            reasons.append(
                f"After purchase, you would have only {days_of_cash:.1f} days of cash "
                f"at current outflow rate. Consider waiting."
            )
            suggested.append("Monitor daily outflows closely after purchase.")
            confidence_deduct += 5

        # Rule 5: ROI check
        if expected_roi_pct < 0:
            reasons.append(
                f"Negative expected ROI ({expected_roi_pct:.1f}%). "
                f"This purchase may not generate positive returns."
            )
            if verdict == "GO":
                suggested.append(
                    "Proceed with caution — this purchase has negative expected returns."
                )
            confidence_deduct += 15
        elif expected_roi_pct > 20:
            reasons.append(
                f"Strong expected ROI ({expected_roi_pct:.1f}%) supports the investment."
            )

        # Rule 6: Margin context
        if raw_margin is not None and raw_margin < 15:
            if verdict == "GO":
                reasons.append(
                    f"Low gross margin ({raw_margin:.1f}%). "
                    f"Consider whether this purchase improves margins or adds risk."
                )
                confidence_deduct += 10

        # --- confidence ---
        confidence = max(0, min(100, 100 - confidence_deduct))
        if confidence < 40:
            reasons.insert(0, "⚠️ Low confidence — limited data available for this analysis.")

        return PurchaseAdvice(
            verdict=verdict,
            confidence=confidence,
            reasons=reasons,
            balance_before_minor=current_balance,
            balance_after_minor=balance_after,
            buffer_minor=buffer_target,
            days_of_cash_after=max(0, days_of_cash),
            upcoming_obligations_minor=upcoming_obl,
            shortfall_risk_bp=shortfall_risk,
            suggested_actions=suggested,
        )

    # ------------------------------------------------------------------
    # Cash allocation
    # ------------------------------------------------------------------

    def allocate_spending(
        self,
        business_id: int,
        available_cash_minor: Optional[int] = None,
    ) -> AllocationAdvice:
        """Allocate available cash across priority categories.

        Returns priority-ranked allocations with warnings.
        """
        warnings: List[str] = []

        if available_cash_minor is None:
            available_cash_minor = self._get_current_balance(business_id)

        total_obligations = self._get_upcoming_obligations_total(business_id, days=30)
        buffer_target = self._get_buffer_target(business_id)
        margin = self._get_gross_margin_pct(business_id)

        surplus = available_cash_minor - total_obligations

        if surplus < 0:
            warnings.append(
                f"⚠️ Obligations (KES {total_obligations/100:,.0f}) exceed available cash "
                f"(KES {available_cash_minor/100:,.0f}) by KES {abs(surplus)/100:,.0f}."
            )

        # Buffer gap
        buffer_gap = max(0, buffer_target - max(0, surplus))

        allocations = []

        # Priority 1: Cover obligations
        if total_obligations > 0:
            allocations.append({
                "label": "Cover upcoming obligations",
                "amount_minor": min(available_cash_minor, total_obligations),
                "priority": 1,
                "rationale": f"KES {total_obligations/100:,.0f} due in next 30 days.",
            })

        # Priority 2: Fill buffer
        if buffer_gap > 0 and surplus > 0:
            alloc_amt = min(buffer_gap, surplus)
            allocations.append({
                "label": "Top up safety buffer",
                "amount_minor": alloc_amt,
                "priority": 2,
                "rationale": (
                    f"Buffer is KES {buffer_gap/100:,.0f} below target of "
                    f"KES {buffer_target/100:,.0f}."
                ),
            })
        elif buffer_gap > 0:
            allocations.append({
                "label": "Top up safety buffer (deferred)",
                "amount_minor": 0,
                "priority": 2,
                "rationale": (
                    f"Buffer is KES {buffer_gap/100:,.0f} below target but "
                    f"no surplus available."
                ),
            })

        remaining = max(0, surplus - buffer_gap)

        # Priority 3: Stock / inventory
        stock_pct = 0.40 if (margin is not None and margin < 25) else 0.25
        stock_alloc = int(remaining * stock_pct)
        if stock_alloc > 0:
            allocations.append({
                "label": "Restock inventory",
                "amount_minor": stock_alloc,
                "priority": 3,
                "rationale": (
                    f"Allocate {stock_pct:.0%} of surplus to inventory "
                    f"{'(higher — low margin business)' if (margin is not None and margin < 25) else ''}"
                ),
            })

        # Priority 4: Growth / marketing
        growth_alloc = int(remaining * 0.25)
        if growth_alloc > 0:
            allocations.append({
                "label": "Growth & marketing",
                "amount_minor": growth_alloc,
                "priority": 4,
                "rationale": "Invest in customer acquisition and business growth.",
            })

        # Priority 5: Owner drawings / savings
        personal_alloc = int(remaining * 0.20)
        if personal_alloc > 0:
            allocations.append({
                "label": "Owner drawings / savings",
                "amount_minor": personal_alloc,
                "priority": 5,
                "rationale": "Personal income and emergency savings.",
            })

        # Any unallocated remainder
        total_allocated = sum(a["amount_minor"] for a in allocations)
        unallocated = remaining - total_allocated
        if unallocated > 0:
            allocations.append({
                "label": "Unallocated / discretionary",
                "amount_minor": unallocated,
                "priority": 6,
                "rationale": "Flexible reserve for unexpected opportunities.",
            })

        if surplus > 0 and surplus < buffer_target:
            warnings.append(
                f"⚠️ Surplus (KES {surplus/100:,.0f}) is below the buffer target "
                f"(KES {buffer_target/100:,.0f}). Prioritize building the buffer."
            )

        if margin is not None and margin < 10:
            warnings.append(
                f"⚠️ Gross margin is very low ({margin:.1f}%). "
                f"Review pricing and cost structure."
            )

        return AllocationAdvice(
            allocations=allocations,
            warnings=warnings,
            available_cash_minor=available_cash_minor,
            total_obligations_minor=total_obligations,
            buffer_target_minor=buffer_target,
            surplus_minor=surplus,
        )

    # ------------------------------------------------------------------
    # Cashflow forecast integration
    # ------------------------------------------------------------------

    def _get_cashflow_forecast(
        self,
        business_id: int,
        horizon_days: int = 14,
    ):
        """Construct daily-flow DataFrames from transaction_ledger and
        pass to BalanceForecaster.forecast().

        Per Architect requirement: couples SpendingAdvisor to BalanceForecaster
        explicitly through this method.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT local_date,
                   SUM(CASE WHEN direction = 'in' THEN amount_minor ELSE 0 END) as inflow,
                   SUM(CASE WHEN direction = 'out' THEN amount_minor ELSE 0 END) as outflow
            FROM transaction_ledger
            WHERE business_id = ? AND voided = 0
            GROUP BY local_date
            ORDER BY local_date
        """, (business_id,))

        rows = cursor.fetchall()

        if not rows:
            conn.close()
            forecaster = BalanceForecaster()
            empty_df = pd.DataFrame(columns=["local_date", "weekday", "inflow_minor", "outflow_minor"])
            return forecaster.forecast(
                daily_flows=empty_df,
                obligations=[],
                opening_balance=self._get_current_balance(business_id),
                horizon_days=horizon_days,
            )

        records = []
        for row in rows:
            try:
                dt = datetime.strptime(row["local_date"][:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            records.append({
                "local_date": dt.strftime("%Y-%m-%d"),
                "weekday": dt.weekday(),
                "inflow_minor": row["inflow"] or 0,
                "outflow_minor": row["outflow"] or 0,
            })

        conn.close()

        daily_flows = pd.DataFrame(records)

        # Get upcoming obligations
        obligations = self._get_obligations_for_forecast(business_id, horizon_days)

        opening_balance = self._get_current_balance(business_id)

        forecaster = BalanceForecaster()
        return forecaster.forecast(
            daily_flows=daily_flows,
            obligations=obligations,
            opening_balance=opening_balance,
            buffer_minor=self._get_buffer_target(business_id),
            horizon_days=horizon_days,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_current_balance(self, business_id: int) -> int:
        """Compute current balance from ledger."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
              COALESCE(SUM(CASE WHEN direction = 'in' THEN amount_minor ELSE -amount_minor END), 0)
            FROM transaction_ledger
            WHERE business_id = ? AND voided = 0
        """, (business_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0

    def _get_avg_daily_outflow(self, business_id: int) -> float:
        """Average daily outflow over the last 30 days with activity."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT AVG(daily_out) FROM (
                SELECT local_date, SUM(amount_minor) as daily_out
                FROM transaction_ledger
                WHERE business_id = ? AND direction = 'out' AND voided = 0
                  AND local_date >= date('now', '-30 days')
                GROUP BY local_date
            )
        """, (business_id,))
        row = cursor.fetchone()
        conn.close()
        return float(row[0]) if row and row[0] else 0.0

    def _get_buffer_target(self, business_id: int) -> int:
        """Get the safety buffer target for the business (default from config)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT buffer_minor FROM business
            WHERE business_id = ?
        """, (business_id,))
        row = cursor.fetchone()
        conn.close()

        if row and row[0] is not None:
            return row[0]
        return config.SAFETY_BUFFER_MINOR

    def _get_upcoming_obligations_total(
        self, business_id: int, days: int = 14
    ) -> int:
        """Total amount of obligations due in the next `days` days."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cutoff = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

        cursor.execute("""
            SELECT COALESCE(SUM(amount_minor), 0)
            FROM recurring_expense
            WHERE business_id = ? AND active = 1
              AND next_due BETWEEN ? AND ?
        """, (business_id, today, cutoff))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0

    def _get_obligations_for_forecast(
        self, business_id: int, horizon_days: int
    ) -> List[Dict]:
        """Get obligations formatted for BalanceForecaster."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cutoff = (datetime.now() + timedelta(days=horizon_days)).strftime("%Y-%m-%d")

        cursor.execute("""
            SELECT description, amount_minor, next_due as due_date
            FROM recurring_expense
            WHERE business_id = ? AND active = 1
              AND next_due BETWEEN ? AND ?
        """, (business_id, today, cutoff))
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "label": r["description"],
                "amount_minor": r["amount_minor"],
                "due_date": r["due_date"],
            }
            for r in rows
        ]

    def _get_gross_margin_pct(self, business_id: int) -> Optional[float]:
        """Estimate gross margin percentage from categorized transactions."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
              COALESCE(SUM(CASE WHEN direction = 'in' THEN amount_minor ELSE 0 END), 0) as revenue,
              COALESCE(SUM(CASE WHEN direction = 'out' AND c.kind = 'cogs' THEN tl.amount_minor ELSE 0 END), 0) as cogs
            FROM transaction_ledger tl
            LEFT JOIN category c ON c.category_id = tl.category_id
            WHERE tl.business_id = ? AND tl.voided = 0
        """, (business_id,))
        row = cursor.fetchone()
        conn.close()

        if not row or row[0] == 0:
            return None

        revenue = row[0]
        cogs = row[1] or 0

        if revenue == 0:
            return None

        return round((1 - cogs / revenue) * 100, 1)

    def get_forecast_summary(self, business_id: int, horizon_days: int = 14) -> Dict:
        """Get a human-readable forecast summary for the UI."""
        result = self._get_cashflow_forecast(business_id, horizon_days)

        lowest_p10 = min(result.points, key=lambda p: p["p10"]) if result.points else None
        final_p50 = result.points[-1]["p50"] if result.points else result.opening_balance_minor
        final_p10 = result.points[-1]["p10"] if result.points else result.opening_balance_minor

        shortfall_days = [
            p for p in result.points
            if p["p10"] < result.buffer_minor
        ]

        forecaster = BalanceForecaster()
        shortfalls = forecaster.detect_shortfalls(result)

        return {
            "as_of_date": result.as_of_date,
            "horizon_days": result.horizon_days,
            "opening_balance": result.opening_balance_minor,
            "buffer_minor": result.buffer_minor,
            "lowest_p10": lowest_p10["p10"] if lowest_p10 else result.opening_balance_minor,
            "lowest_p10_date": lowest_p10["date"] if lowest_p10 else result.as_of_date,
            "final_p50": final_p50,
            "final_p10": final_p10,
            "shortfall_days": len(shortfall_days),
            "shortfalls": [
                {
                    "date": s.date,
                    "gap_minor": s.gap_minor,
                    "probability_bp": s.probability_bp,
                    "actions": s.suggested_actions,
                }
                for s in shortfalls
            ],
            "points": result.points,
        }
