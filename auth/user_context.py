"""User-scoped business context cache for LLM consumption.

Pre-aggregates transaction data per (user_id, business_id) so the LLM
receives clean, pre-processed summaries instead of raw DB queries.
Uses diskcache (already a dependency) for TTL-based caching.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from diskcache import Cache

from core.config import config


CACHE_DIR = config.LLM_CACHE_DIR or ".llm_cache"
CONTEXT_TTL_SECONDS = 300  # 5 minutes


def _context_cache() -> Cache:
    """Return a diskcache instance scoped to user contexts."""
    return Cache(f"{CACHE_DIR}/user_context")


def _cache_key(user_id: int, business_id: int) -> str:
    """Deterministic cache key."""
    return f"ctx:{user_id}:{business_id}"


@dataclass
class UserContext:
    """Pre-processed, cached business data for a single user+business pair."""

    user_id: int
    business_id: int
    db_path: str = field(default_factory=lambda: config.DB_PATH)

    # ---- public API ----

    def get(self) -> Dict[str, Any]:
        """Return cached context; compute + cache on miss."""
        cache = _context_cache()
        key = _cache_key(self.user_id, self.business_id)

        cached = cache.get(key)
        if cached is not None:
            return cached

        ctx = self._compute()
        cache.set(key, ctx, expire=CONTEXT_TTL_SECONDS)
        return ctx

    def refresh(self) -> Dict[str, Any]:
        """Force recompute and overwrite the cache entry."""
        cache = _context_cache()
        key = _cache_key(self.user_id, self.business_id)
        ctx = self._compute()
        cache.set(key, ctx, expire=CONTEXT_TTL_SECONDS)
        return ctx

    def invalidate(self) -> None:
        """Remove cached entry (e.g. on logout or data purge)."""
        cache = _context_cache()
        key = _cache_key(self.user_id, self.business_id)
        cache.delete(key)

    # ---- computation ----

    def _compute(self) -> Dict[str, Any]:
        """Aggregate all business data into a single LLM-ready dict."""
        summary = self._summary()
        obligations = self._obligations()
        forecast = self._forecast(obligations, summary.get("opening_balance_minor", 0))
        health = self._health_metrics(summary)
        risks = self._risk_flags(summary, obligations, health)
        sample = self._transaction_sample()

        return {
            "business_summary": {"business_id": self.business_id, "name": self._business_name()},
            "summary": summary,
            "top_expense_categories": self._top_expense_categories(),
            "health": health,
            "obligations": obligations,
            "forecast": forecast,
            "risks": risks,
            "recent_transactions": sample,
            "generated_at": datetime.utcnow().isoformat(),
        }

    # ---- sub-computations ----

    # The 30-day window ends at the latest transaction, not today, so an
    # uploaded statement that ended weeks ago still produces real figures.
    _WINDOW_START = (
        "date((SELECT MAX(local_date) FROM transaction_ledger "
        "WHERE business_id = ? AND voided = 0), '-30 days')"
    )

    def _summary(self) -> Dict[str, Any]:
        """Revenue, expenses, margins — the 30 days up to the latest transaction."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN direction='in' THEN amount_minor END), 0) AS revenue,
                 COALESCE(SUM(CASE WHEN direction='out' THEN amount_minor END), 0) AS expenses,
                 COUNT(*) AS txn_count
               FROM transaction_ledger
               WHERE business_id = ?
                 AND local_date >= """ + self._WINDOW_START + """
                 AND voided = 0""",
            (self.business_id, self.business_id),
        ).fetchone()

        span = conn.execute(
            """SELECT MIN(local_date), MAX(local_date) FROM transaction_ledger
               WHERE business_id = ? AND voided = 0""",
            (self.business_id,),
        ).fetchone()

        # Current balance (latest row in the ledger)
        bal_row = conn.execute(
            """SELECT balance_after_minor FROM transaction_ledger
               WHERE business_id = ? AND voided = 0 AND balance_after_minor IS NOT NULL
               ORDER BY local_date DESC, ts DESC, txn_id DESC LIMIT 1""",
            (self.business_id,),
        ).fetchone()
        conn.close()

        revenue = row["revenue"] if row else 0
        expenses = row["expenses"] if row else 0
        txn_count = row["txn_count"] if row else 0
        opening_balance = bal_row["balance_after_minor"] if bal_row else 0

        return {
            "period": "last_30_days_of_data",
            "data_from": span[0] if span else None,
            "data_to": span[1] if span else None,
            "revenue_kes": round(revenue / 100.0, 2),
            "expenses_kes": round(expenses / 100.0, 2),
            "net_kes": round((revenue - expenses) / 100.0, 2),
            "margin_pct": round((revenue - expenses) / max(1, revenue) * 100, 1),
            "transaction_count": txn_count,
            "opening_balance_kes": round(opening_balance / 100.0, 2),
            "opening_balance_minor": opening_balance,
        }

    def _obligations(self) -> List[Dict[str, Any]]:
        """Upcoming payments due in the next 14 days.

        Merges the three places bills are recorded: obligation (detected from
        statements), recurring_expense (entered in Business Setup) and
        standing_order (the Standing Orders page)."""
        sources = [
            ("detected", """SELECT label, amount_minor, next_due, cadence FROM obligation
                            WHERE business_id = ? AND active = 1
                              AND next_due <= date('now', '+14 days')"""),
            ("owner_entered", """SELECT description AS label, amount_minor, next_due, cadence
                                 FROM recurring_expense
                                 WHERE business_id = ? AND active = 1
                                   AND next_due <= date('now', '+14 days')"""),
            ("standing_order", """SELECT label, amount_minor, next_due, cadence FROM standing_order
                                  WHERE business_id = ? AND status = 'active'
                                    AND next_due <= date('now', '+14 days')"""),
            # Already-generated but unpaid instances (next_due has moved past them).
            ("awaiting_authorization", """SELECT s.label, p.amount_minor, p.due_date AS next_due, s.cadence
                                          FROM scheduled_payment p JOIN standing_order s USING (standing_order_id)
                                          WHERE p.business_id = ?
                                            AND p.status IN ('pending','notified','authorized','stk_sent','failed')"""),
        ]
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        out: List[Dict[str, Any]] = []
        for source, sql in sources:
            try:
                rows = conn.execute(sql, (self.business_id,)).fetchall()
            except sqlite3.OperationalError:
                continue  # table not created yet on this database
            out.extend(
                {
                    "label": r["label"],
                    "amount_kes": round(r["amount_minor"] / 100.0, 2),
                    "due_date": r["next_due"],
                    "frequency": r["cadence"],
                    "source": source,
                }
                for r in rows
            )
        conn.close()
        return sorted(out, key=lambda o: o["due_date"] or "")

    def _forecast(
        self,
        obligations: List[Dict[str, Any]],
        opening_balance_minor: int,
        horizon_days: int = 30,
    ) -> Dict[str, Any]:
        """Lightweight forecast using the forecaster if enough data, else fallback."""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            """SELECT local_date, amount_minor, direction
               FROM transaction_ledger
               WHERE business_id = ? AND voided = 0
               ORDER BY local_date""",
            conn,
            params=(self.business_id,),
        )
        conn.close()

        if df.empty or len(df) < 5:
            return {
                "horizon_days": horizon_days,
                "p10_end_kes": 0,
                "p50_end_kes": 0,
                "p90_end_kes": 0,
                "shortfall_risk": False,
                "note": "Insufficient transaction history for forecast",
            }

        try:
            from core.forecaster import BalanceForecaster

            df["weekday"] = pd.to_datetime(df["local_date"], format="mixed", dayfirst=True).dt.dayofweek
            daily = (
                df.groupby(["local_date", "weekday"])
                .agg(
                    inflow_minor=("amount_minor", lambda x: x[df.loc[x.index, "direction"] == "in"].sum()),
                    outflow_minor=("amount_minor", lambda x: x[df.loc[x.index, "direction"] == "out"].sum()),
                )
                .reset_index()
            )

            obl_for_forecast = [
                {"due_date": o["due_date"], "amount_minor": int(o["amount_kes"] * 100), "label": o["label"]}
                for o in obligations
            ]

            forecaster = BalanceForecaster(seed=config.SYNTHETIC_DATA_SEED)
            result = forecaster.forecast(
                daily_flows=daily,
                obligations=obl_for_forecast,
                opening_balance=opening_balance_minor,
                buffer_minor=config.SAFETY_BUFFER_MINOR,
                horizon_days=horizon_days,
                n_paths=200,
            )

            last = result.points[-1] if result.points else {}
            alerts = forecaster.detect_shortfalls(result)

            return {
                "horizon_days": horizon_days,
                "p10_end_kes": round(last.get("p10", 0) / 100.0, 2),
                "p50_end_kes": round(last.get("p50", 0) / 100.0, 2),
                "p90_end_kes": round(last.get("p90", 0) / 100.0, 2),
                "shortfall_risk": len(alerts) > 0,
                "shortfall_count": len(alerts),
            }
        except Exception:
            return {
                "horizon_days": horizon_days,
                "p10_end_kes": 0,
                "p50_end_kes": 0,
                "p90_end_kes": 0,
                "shortfall_risk": False,
                "note": "Forecast computation failed — using fallback",
            }

    def _health_metrics(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Derive health flags from summary data (heuristic, avoids full FinancialHealthAnalyzer)."""
        margin = summary.get("margin_pct", 0)
        balance = summary.get("opening_balance_kes", 0)
        expenses = summary.get("expenses_kes", 0)

        daily_burn = expenses / 30.0 if expenses > 0 else 0
        days_of_cash = int(balance / daily_burn) if daily_burn > 0 else 999

        if margin >= 20 and days_of_cash >= 30:
            status = "healthy"
        elif margin >= 5 and days_of_cash >= 14:
            status = "caution"
        else:
            status = "critical"

        margin_label = "good" if margin >= 10 else ("fair" if margin >= 5 else "poor")

        return {
            "status": status,
            "days_of_cash": days_of_cash,
            "burn_rate_daily_kes": round(daily_burn, 2),
            "margin_health": margin_label,
            "balance_kes": balance,
        }

    def _risk_flags(
        self,
        summary: Dict[str, Any],
        obligations: List[Dict[str, Any]],
        health: Dict[str, Any],
    ) -> List[str]:
        """High-priority alerts for the LLM to surface."""
        flags: List[str] = []

        margin = summary.get("margin_pct", 0)
        if margin < 5:
            flags.append(f"Low margins ({margin}%); explore cost reduction or pricing changes")

        if len(obligations) > 3:
            total_due = sum(o["amount_kes"] for o in obligations)
            flags.append(
                f"High obligation load: {len(obligations)} payments totalling "
                f"KES {total_due:,.0f} due in next 14 days"
            )

        days_cash = health.get("days_of_cash", 999)
        if days_cash < 7:
            flags.append(f"Critical runway: only {days_cash} days of cash remaining")

        txn_count = summary.get("transaction_count", 0)
        if txn_count < 10:
            flags.append("Very few recent transactions — data may be incomplete")

        return flags

    def _transaction_sample(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Last N transactions — minimal, redacted details for LLM context."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT t.local_date, t.channel, t.amount_minor, t.direction,
                      LOWER(COALESCE(c.code, 'unclassified')) AS category
               FROM transaction_ledger t
               LEFT JOIN category c ON c.category_id = t.category_id
               WHERE t.business_id = ? AND t.voided = 0
               ORDER BY t.local_date DESC, t.ts DESC, t.txn_id DESC LIMIT ?""",
            (self.business_id, limit),
        ).fetchall()
        conn.close()

        return [
            {
                "date": r["local_date"],
                "type": r["channel"],
                "amount_kes": round(r["amount_minor"] / 100.0, 2),
                "category": r["category"],
                "direction": r["direction"],
            }
            for r in rows
        ]

    def _top_expense_categories(self, limit: int = 6) -> List[Dict[str, Any]]:
        """Where the money went in the latest 30 days of data."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT LOWER(COALESCE(c.code, 'unclassified')) AS category,
                      SUM(t.amount_minor) AS total_minor, COUNT(*) AS n
               FROM transaction_ledger t
               LEFT JOIN category c ON c.category_id = t.category_id
               WHERE t.business_id = ? AND t.voided = 0 AND t.direction = 'out'
                 AND t.local_date >= """ + self._WINDOW_START + """
               GROUP BY category ORDER BY total_minor DESC LIMIT ?""",
            (self.business_id, self.business_id, limit),
        ).fetchall()
        conn.close()
        return [
            {"category": r["category"], "amount_kes": round(r["total_minor"] / 100.0, 2), "count": r["n"]}
            for r in rows
        ]

    def _business_name(self) -> str:
        """Fetch the business name for the context header."""
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT name_token FROM business WHERE business_id = ?",
                (self.business_id,),
            ).fetchone()
            conn.close()
            return row[0] if row else f"Business #{self.business_id}"
        except Exception:
            return f"Business #{self.business_id}"


def invalidate_user_cache(user_id: int, business_id: int) -> None:
    """Convenience function to invalidate a user's context cache."""
    UserContext(user_id=user_id, business_id=business_id).invalidate()


# ---- cache refresh hooks ----

def on_transaction_change(user_id: int, business_id: int) -> None:
    """Invalidate user context when transactions are added/modified."""
    invalidate_user_cache(user_id, business_id)


def on_business_update(user_id: int, business_id: int) -> None:
    """Invalidate user context when business profile changes."""
    invalidate_user_cache(user_id, business_id)


def on_obligation_change(user_id: int, business_id: int) -> None:
    """Invalidate user context when obligations change."""
    invalidate_user_cache(user_id, business_id)


# Convenience: invalidate by session
def invalidate_session_context(session) -> None:
    """Invalidate context for the user+business pair in a Session object."""
    if hasattr(session, 'user_id') and hasattr(session, 'business_id'):
        invalidate_user_cache(session.user_id, session.business_id)


def refresh_context_if_stale(user_id: int, business_id: int) -> Dict[str, Any]:
    """Force-refresh context; useful as a scheduled job or post-mutation hook."""
    ctx = UserContext(user_id=user_id, business_id=business_id)
    return ctx.refresh()
