"""Balance forecaster: weekday-aware bootstrap with obligation overlay."""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


@dataclass
class ForecastResult:
    run_id: int
    as_of_date: str
    horizon_days: int
    opening_balance_minor: int
    buffer_minor: int
    method: str
    seed: int
    n_paths: int
    points: List[Dict] = field(default_factory=list)  # day_offset, date, p10, p50, p90, expected


@dataclass
class ShortfallAlert:
    date: str
    day_offset: int
    gap_minor: int  # how far below the buffer
    probability_bp: int  # basis points
    suggested_actions: List[str]


class BalanceForecaster:
    """Forecast daily balance using weekday-aware bootstrap."""

    def __init__(self, seed: int = 42):
        self.rng = np.random.RandomState(seed)
        self.seed = seed

    def forecast(
        self,
        daily_flows: pd.DataFrame,
        obligations: List[Dict],
        opening_balance: int,
        buffer_minor: int = 500000,
        horizon_days: int = 14,
        n_paths: int = 1000,
        as_of: Optional[datetime] = None,
    ) -> ForecastResult:
        """Generate a bootstrap forecast.

        Args:
            daily_flows: DataFrame with columns [local_date, weekday, inflow_minor, outflow_minor]
            obligations: List of {due_date, amount_minor, label}
        """
        # Separate weekday pools
        pools_in = {}
        pools_out = {}
        for wd in range(7):
            wd_data_in = daily_flows[daily_flows["weekday"] == wd]["inflow_minor"]
            wd_data_out = daily_flows[daily_flows["weekday"] == wd]["outflow_minor"]
            pools_in[wd] = wd_data_in.values if len(wd_data_in) > 0 else np.array([0])
            pools_out[wd] = wd_data_out.values if len(wd_data_out) > 0 else np.array([0])

        as_of = as_of or datetime.now()
        paths = np.zeros((n_paths, horizon_days + 1), dtype=np.int64)
        paths[:, 0] = opening_balance

        # Scheduled obligations by date. One already due (before day 1) is
        # still unpaid, so it lands on day 1 instead of being dropped. A
        # variable bill (tolerance_pct > 0) is drawn per path within its band.
        first_day = (as_of + timedelta(days=1)).strftime("%Y-%m-%d")
        obl_by_date: Dict[str, int] = {}
        variable_by_date: Dict[str, List[Tuple[int, float]]] = {}
        for obl in obligations:
            due = str(obl.get("due_date") or "")[:10]
            if not due:
                continue
            due = max(due, first_day)
            tol = (obl.get("tolerance_pct") or 0) / 100.0
            if tol > 0:
                variable_by_date.setdefault(due, []).append((obl.get("amount_minor", 0), tol))
            else:
                obl_by_date[due] = obl_by_date.get(due, 0) + obl.get("amount_minor", 0)

        for day in range(1, horizon_days + 1):
            date = as_of + timedelta(days=day)
            wd = date.weekday()

            in_samples = self.rng.choice(pools_in[wd], size=n_paths, replace=True)
            out_samples = self.rng.choice(pools_out[wd], size=n_paths, replace=True)

            key = date.strftime("%Y-%m-%d")
            obl_amt = obl_by_date.get(key, 0)
            for amt, tol in variable_by_date.get(key, []):
                obl_amt = obl_amt + np.round(amt * self.rng.uniform(1 - tol, 1 + tol, size=n_paths)).astype(np.int64)

            paths[:, day] = paths[:, day - 1] + in_samples - out_samples - obl_amt

        points = []
        for day in range(horizon_days + 1):
            date = as_of + timedelta(days=day)
            col = paths[:, day]
            points.append({
                "day_offset": day,
                "date": date.strftime("%Y-%m-%d"),
                "p10": int(np.percentile(col, 10)),
                "p50": int(np.percentile(col, 50)),
                "p90": int(np.percentile(col, 90)),
                "expected": int(col.mean()),
            })

        return ForecastResult(
            run_id=0,
            as_of_date=as_of.strftime("%Y-%m-%d"),
            horizon_days=horizon_days,
            opening_balance_minor=opening_balance,
            buffer_minor=buffer_minor,
            method="weekday_bootstrap",
            seed=self.seed,
            n_paths=n_paths,
            points=points,
        )

    def detect_shortfalls(self, forecast: ForecastResult) -> List[ShortfallAlert]:
        """Find days where p10 balance drops below buffer."""
        alerts = []
        for pt in forecast.points:
            if pt["p10"] < forecast.buffer_minor:
                gap = forecast.buffer_minor - pt["p10"]
                # Probability estimate: fraction of paths below buffer
                # We approximate from p10: if p10 is below, at least 10% of paths breach
                prob = 1000  # minimum 10% = 1000 bp
                if pt["p50"] < forecast.buffer_minor:
                    prob = 5000  # at least 50%

                suggestions = self._suggest_actions(
                    gap_minor=gap,
                    day_offset=pt["day_offset"],
                    has_obligations=pt.get("obligations_minor", 0) > 0,
                )

                alerts.append(ShortfallAlert(
                    date=pt["date"],
                    day_offset=pt["day_offset"],
                    gap_minor=gap,
                    probability_bp=prob,
                    suggested_actions=suggestions,
                ))

        return alerts

    def _suggest_actions(self, gap_minor: int, day_offset: int,
                         has_obligations: bool) -> List[str]:
        """Generate suggested actions for a shortfall."""
        actions = []
        gap_kes = gap_minor / 100

        if has_obligations and day_offset > 3:
            actions.append(
                f"Delay non-essential spending by {day_offset} days "
                f"to cover the KES {gap_kes:,.0f} gap"
            )
        if gap_minor < 500000:
            actions.append(
                f"Reduce personal withdrawals by KES {gap_kes:,.0f} "
                f"this week to stay above the safety buffer"
            )
        if gap_minor >= 200000:
            actions.append(
                f"Consider a short-term overdraft of KES {gap_kes:,.0f} "
                f"— compare options in the Financing tab"
            )
        actions.append(
            "Chase outstanding customer credit if any is overdue"
        )
        return actions


# ---- Tool wrapper functions for agent dispatch ----

from typing import Optional
import json
import sqlite3

OVERDRAFT_ACCESS_FEE = 0.01     # 1% of the amount when drawn (Fuliza-style)
OVERDRAFT_DAILY_FEE = 0.005     # 0.5% of the amount owed per day
CALC_VERSION = "v2-true-position"


def overdraft_owed_by_day(events, dates):
    """Overdraft owed (with fees) at the end of each date.

    events: [(date, 'in'|'out', amount_minor)] for channel='overdraft' rows,
    where 'in' is a drawdown and 'out' a repayment. Assumes nothing was owed
    before the statement starts."""
    by_day = {}
    for d, direction, amount in events:
        by_day.setdefault(d, []).append((direction, amount))
    owed, fees_until, result = 0.0, None, {}
    for d in dates:
        for direction, amount in by_day.get(d, []):
            if owed > 0:            # add daily fees since they were last added
                owed += round(owed * OVERDRAFT_DAILY_FEE * (d - fees_until).days)
            fees_until = d
            if direction == "in":
                owed += round(amount * (1 + OVERDRAFT_ACCESS_FEE))
            else:
                owed = max(0.0, owed - amount)
        pending = round(owed * OVERDRAFT_DAILY_FEE * (d - fees_until).days) if owed else 0
        result[d] = int(owed + pending)
    return result


def _ledger_rows(conn, business_id, until=None):
    sql = """SELECT t.local_date, t.direction, t.amount_minor, t.channel,
                    t.balance_after_minor, c.code AS category
             FROM transaction_ledger t
             LEFT JOIN category c ON c.category_id = t.category_id
             WHERE t.business_id = ? AND t.voided = 0"""
    params = [business_id]
    if until:
        sql += " AND t.local_date <= ?"
        params.append(until)
    sql += " ORDER BY t.local_date, t.ts, t.txn_id"
    return conn.execute(sql, params).fetchall()


def true_position(conn, business_id, as_of=None) -> dict:
    """Balance minus overdraft owed (with fees), at the end of as_of
    (default: the statement's last day). Money in the account isn't really
    the owner's while an overdraft is unpaid."""
    rows = _ledger_rows(conn, business_id, as_of)
    if not rows:
        return {"as_of": None, "balance_minor": 0, "overdraft_owed_minor": 0, "true_position_minor": 0}
    last = as_of or rows[-1]["local_date"]
    balance = next((r["balance_after_minor"] for r in reversed(rows)
                    if r["balance_after_minor"] is not None), None)
    if balance is None:     # statement without a balance column
        balance = sum(r["amount_minor"] if r["direction"] == "in" else -r["amount_minor"] for r in rows)
    start = datetime.strptime(rows[0]["local_date"], "%Y-%m-%d").date()
    end = datetime.strptime(last, "%Y-%m-%d").date()
    dates = [start + timedelta(days=k) for k in range((end - start).days + 1)]
    events = [(datetime.strptime(r["local_date"], "%Y-%m-%d").date(), r["direction"], r["amount_minor"])
              for r in rows if r["channel"] == "overdraft"]
    owed = overdraft_owed_by_day(events, dates)[end] if dates else 0
    return {"as_of": last, "balance_minor": int(balance), "overdraft_owed_minor": owed,
            "true_position_minor": int(balance) - owed}


# Borrowing reacts to shortfalls, so the forecast leaves it out (as the
# overdraft is already counted in the true position).
_BORROWING_CATEGORIES = {"LOAN_DISBURSEMENT", "OVERDRAFT_FEE"}


def _daily_flows(rows) -> "pd.DataFrame":
    """One row per calendar day (quiet days count as 0), borrowing excluded."""
    flows = {}
    for r in rows:
        if r["channel"] == "overdraft" or r["category"] in _BORROWING_CATEGORIES:
            continue
        f = flows.setdefault(r["local_date"], [0, 0])
        f[0 if r["direction"] == "in" else 1] += r["amount_minor"]
    if not rows:
        return pd.DataFrame(columns=["local_date", "weekday", "inflow_minor", "outflow_minor"])
    start = datetime.strptime(rows[0]["local_date"], "%Y-%m-%d")
    end = datetime.strptime(rows[-1]["local_date"], "%Y-%m-%d")
    days = []
    for k in range((end - start).days + 1):
        d = start + timedelta(days=k)
        key = d.strftime("%Y-%m-%d")
        inflow, outflow = flows.get(key, (0, 0))
        days.append({"local_date": key, "weekday": d.weekday(),
                     "inflow_minor": inflow, "outflow_minor": outflow})
    return pd.DataFrame(days)


def _obligations(db_path, business_id, start=None, end=None):
    """Bills the forecast subtracts: open standing-order payments plus the
    owner's recurring expenses due in [start, end] (overdue ones on start)."""
    from core.standing_orders import StandingOrderService
    try:
        payments = StandingOrderService(db_path).priorities_for_agent(business_id)
    except Exception:
        payments = []
    out = [{"due_date": p.get("due_date", ""), "amount_minor": int(round(p.get("amount_kes", 0) * 100)),
            "label": p.get("label", "Payment"), "source": "standing_order"} for p in payments]
    if start is not None and end is not None:
        from core.expense_tracker import RecurringExpenseManager
        try:
            out += RecurringExpenseManager(db_path).obligations_between(business_id, start, end)
        except sqlite3.Error:
            pass  # no recurring_expense table on this database
    return out


def _without_scheduled_bills(rows, obligations):
    """Drop past payments of the owner's recurring bills from the history,
    so the forecast does not count them twice (once in the sampled daily
    spending, once as a scheduled bill). A payment matches a bill when the
    amounts agree within 2% (within 10% for a variable bill)."""
    bills = {(o["amount_minor"], max(0.02, (o.get("tolerance_pct") or 0) / 100.0))
             for o in obligations if o.get("source") == "recurring_expense"}
    if not bills:
        return rows
    def is_bill(r):
        return r["direction"] == "out" and any(abs(r["amount_minor"] - a) <= a * t for a, t in bills)
    return [r for r in rows if not is_bill(r)]


def forecast_balance(args, business_id: Optional[int] = None,
                    db_path: Optional[str] = None) -> dict:
    """Forecast daily balance with p10/p50/p90 band.

    Starts from the TRUE POSITION (balance minus overdraft owed with fees)
    on the statement's last day, uses the owner's own safety buffer, and
    saves the run to forecast_run / forecast_point so detect_shortfalls and
    check_affordability can use it.
    
    Args:
        args: ForecastBalanceArgs with horizon_days (1-90)
        business_id: Active business ID
        db_path: Database path
    
    Returns:
        dict with daily p10/p50/p90 balance, obligations list
    """
    from core.config import Config
    from core.owner_settings import load_settings
    
    if db_path is None:
        db_path = Config.DB_PATH
    if business_id is None:
        return {"error": "business_id required"}
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = _ledger_rows(conn, business_id)
        if not rows:
            conn.close()
            return {"error": "No transaction data available for forecast. Upload a statement first."}
        position = true_position(conn, business_id)
        conn.close()

        buffer_minor = load_settings(db_path, business_id).safety_buffer_minor
        horizon = args.horizon_days or 14
        as_of = datetime.strptime(position["as_of"], "%Y-%m-%d")
        obligations = _obligations(db_path, business_id, as_of.date() + timedelta(days=1),
                                   as_of.date() + timedelta(days=horizon))
        daily_df = _daily_flows(_without_scheduled_bills(rows, obligations))

        forecaster = BalanceForecaster(seed=42)
        forecast = forecaster.forecast(
            daily_flows=daily_df,
            obligations=obligations,
            opening_balance=position["true_position_minor"],
            buffer_minor=buffer_minor,
            horizon_days=horizon,
            n_paths=1000,
            as_of=as_of,
        )
        
        # Persist to database
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        run_id = conn.execute("""
            INSERT INTO forecast_run (business_id, as_of_date, horizon_days, method, params_json,
                seed, n_paths, opening_balance_minor, buffer_minor, data_start, data_end, calc_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            business_id, forecast.as_of_date, forecast.horizon_days, forecast.method,
            json.dumps({"overdraft_owed_minor": position["overdraft_owed_minor"],
                        "balance_minor": position["balance_minor"]}),
            forecast.seed, forecast.n_paths, forecast.opening_balance_minor, buffer_minor,
            rows[0]["local_date"], rows[-1]["local_date"], CALC_VERSION,
        )).lastrowid
        obligations_by_date = {}
        first_day = forecast.points[1]["date"] if len(forecast.points) > 1 else forecast.as_of_date
        for o in obligations:
            if not o["due_date"]:
                continue
            due = max(o["due_date"][:10], first_day)
            obligations_by_date[due] = obligations_by_date.get(due, 0) + o["amount_minor"]
        conn.executemany("""
            INSERT INTO forecast_point (run_id, day_offset, date, expected_minor, p10_minor,
                p50_minor, p90_minor, obligations_minor) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [(run_id, p["day_offset"], p["date"], p["expected"], p["p10"], p["p50"], p["p90"],
               obligations_by_date.get(p["date"], 0)) for p in forecast.points])
        conn.commit()
        conn.close()

        lowest = min(forecast.points[1:], key=lambda p: p["p10"]) if len(forecast.points) > 1 else forecast.points[0]
        return {
            "forecast_run_id": run_id,
            "as_of_date": forecast.as_of_date,
            "horizon_days": forecast.horizon_days,
            "balance_kes": position["balance_minor"] / 100.0,
            "overdraft_owed_kes": position["overdraft_owed_minor"] / 100.0,
            "true_position_kes": position["true_position_minor"] / 100.0,
            "opening_balance_kes": forecast.opening_balance_minor / 100.0,
            "buffer_kes": buffer_minor / 100.0,
            "lowest_low_kes": lowest["p10"] / 100.0,
            "lowest_low_date": lowest["date"],
            "days_below_buffer": sum(1 for p in forecast.points[1:] if p["p10"] < buffer_minor),
            "points": [{"date": p["date"], "low_kes": p["p10"] / 100.0, "expected_kes": p["p50"] / 100.0,
                        "high_kes": p["p90"] / 100.0} for p in forecast.points[1:]],
            "obligations": [{"due_date": o["due_date"], "label": o["label"],
                             "amount_kes": o["amount_minor"] / 100.0,
                             "source": o.get("source", "standing_order"),
                             "days_overdue": o.get("days_overdue", 0)} for o in obligations],
        }
    
    except Exception as e:
        return {"error": f"Forecast failed: {e}"}


def detect_shortfalls(args, business_id: Optional[int] = None,
                     db_path: Optional[str] = None) -> dict:
    """Detect dates where forecast balance drops below safety buffer.
    
    Args:
        args: DetectShortfallsArgs with forecast_run_id
        business_id: Active business ID
        db_path: Database path
    
    Returns:
        dict with Alert: date, gap, probability, suggested actions
    """
    from core.config import Config
    
    if db_path is None:
        db_path = Config.DB_PATH
    if business_id is None:
        return {"error": "business_id required"}
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # Scoped to the active business: another business's run is "not found".
        run = conn.execute(
            "SELECT * FROM forecast_run WHERE run_id = ? AND business_id = ?",
            (args.forecast_run_id, business_id),
        ).fetchone()
        if not run:
            conn.close()
            return {"error": "Forecast not found"}
        points = [
            {"day_offset": p["day_offset"], "date": p["date"], "p10": p["p10_minor"],
             "p50": p["p50_minor"], "p90": p["p90_minor"], "expected": p["expected_minor"],
             "obligations_minor": p["obligations_minor"]}
            for p in conn.execute(
                "SELECT * FROM forecast_point WHERE run_id = ? AND day_offset > 0 ORDER BY day_offset",
                (args.forecast_run_id,),
            )
        ]
        conn.close()
        
        forecast = ForecastResult(
            run_id=args.forecast_run_id,
            as_of_date=run["as_of_date"],
            horizon_days=run["horizon_days"],
            opening_balance_minor=run["opening_balance_minor"],
            buffer_minor=run["buffer_minor"],
            method=run["method"],
            seed=run["seed"] or 0,
            n_paths=run["n_paths"] or 0,
            points=points,
        )
        
        forecaster = BalanceForecaster()
        alerts = forecaster.detect_shortfalls(forecast)
        worst = min(alerts, key=lambda a: -a.gap_minor) if alerts else None
        
        return {
            "forecast_run_id": args.forecast_run_id,
            "buffer_kes": run["buffer_minor"] / 100.0,
            "shortfall_count": len(alerts),
            "first_date": alerts[0].date if alerts else None,
            "worst_date": worst.date if worst else None,
            "amount_needed_kes": worst.gap_minor / 100.0 if worst else 0.0,
            "alerts": [
                {
                    "date": a.date,
                    "day_offset": a.day_offset,
                    "gap_kes": a.gap_minor / 100.0,
                    "probability_pct": a.probability_bp / 100.0,
                    "suggested_actions": a.suggested_actions,
                }
                for a in alerts
            ],
        }
    
    except Exception as e:
        return {"error": f"Shortfall detection failed: {e}"}


def forecast_backtest(args, business_id: Optional[int] = None,
                      db_path: Optional[str] = None) -> dict:
    """How accurate is the forecast? Hide the last `horizon_days` of history,
    forecast them from what came before, and compare with what really
    happened (the true position each day, and total sales)."""
    from core.config import Config

    if db_path is None:
        db_path = Config.DB_PATH
    if business_id is None:
        return {"error": "business_id required"}
    days = getattr(args, "horizon_days", None) or 14

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = _ledger_rows(conn, business_id)
        if not rows:
            conn.close()
            return {"error": "No transaction data available."}
        end = datetime.strptime(rows[-1]["local_date"], "%Y-%m-%d")
        start = datetime.strptime(rows[0]["local_date"], "%Y-%m-%d")
        if (end - start).days < days * 2:
            conn.close()
            return {"error": f"Need at least {days * 2} days of history to test a {days}-day forecast."}
        cutoff = end - timedelta(days=days)
        cutoff_s = cutoff.strftime("%Y-%m-%d")
        history = [r for r in rows if r["local_date"] <= cutoff_s]
        start_position = true_position(conn, business_id, cutoff_s)["true_position_minor"]
        hidden_dates = [(cutoff + timedelta(days=k)).strftime("%Y-%m-%d") for k in range(1, days + 1)]
        actual = {d: true_position(conn, business_id, d)["true_position_minor"] for d in hidden_dates}
        sales_actual = sum(r["amount_minor"] for r in rows
                           if r["local_date"] > cutoff_s and r["direction"] == "in"
                           and r["channel"] != "overdraft" and r["category"] not in _BORROWING_CATEGORIES)
        conn.close()

        history_df = _daily_flows(history)
        forecast = BalanceForecaster(seed=42).forecast(
            daily_flows=history_df, obligations=[], opening_balance=start_position,
            horizon_days=days, n_paths=1000, as_of=cutoff,
        )
        predicted = forecast.points[1:]
        errors = [p["p50"] - actual[p["date"]] for p in predicted]
        inside = sum(p["p10"] <= actual[p["date"]] <= p["p90"] for p in predicted)
        # Expected sales: weekday averages from history over the hidden days
        wd_avg = history_df.groupby("weekday")["inflow_minor"].mean().to_dict()
        sales_forecast = sum(wd_avg.get(datetime.strptime(d, "%Y-%m-%d").weekday(), 0) for d in hidden_dates)
        sales_error_pct = ((sales_forecast - sales_actual) / sales_actual * 100) if sales_actual else None

        return {
            "test_start": hidden_dates[0],
            "test_end": hidden_dates[-1],
            "days": days,
            "final_balance_error_kes": errors[-1] / 100.0,
            "mean_abs_error_kes": sum(abs(e) for e in errors) / len(errors) / 100.0,
            "days_inside_range": inside,
            "sales_forecast_kes": round(sales_forecast / 100.0, 2),
            "sales_actual_kes": sales_actual / 100.0,
            "sales_error_pct": round(sales_error_pct, 1) if sales_error_pct is not None else None,
        }
    except Exception as e:
        return {"error": f"Backtest failed: {e}"}
