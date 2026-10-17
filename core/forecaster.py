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

        as_of = datetime.now()
        paths = np.zeros((n_paths, horizon_days + 1), dtype=np.int64)
        paths[:, 0] = opening_balance

        for day in range(1, horizon_days + 1):
            date = as_of + timedelta(days=day)
            wd = date.weekday()

            in_samples = self.rng.choice(pools_in[wd], size=n_paths, replace=True)
            out_samples = self.rng.choice(pools_out[wd], size=n_paths, replace=True)

            # Add scheduled obligations
            obl_amt = 0
            for obl in obligations:
                if obl.get("due_date", "") == date.strftime("%Y-%m-%d"):
                    obl_amt += obl.get("amount_minor", 0)

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
