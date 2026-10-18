"""Financial health scoring: liquidity, leverage, runway, and overall health index."""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import pandas as pd
import numpy as np


@dataclass
class FinancialHealthReport:
    """Structured financial health assessment."""

    # Liquidity
    current_ratio: float
    quick_ratio: float
    cash_balance_kes: float
    total_current_assets_kes: float
    total_current_liabilities_kes: float

    # Runway & Burn
    days_of_cash: int
    monthly_burn_rate_kes: float
    monthly_revenue_kes: float
    burn_multiple: float  # burn / revenue; lower is better

    # Leverage
    debt_to_revenue_ratio: float
    debt_service_coverage: float  # operating cashflow / debt obligations

    # Profitability
    gross_margin_pct: float
    operating_margin_pct: float
    net_margin_pct: float
    revenue_growth_pct: Optional[float]  # period-over-period

    # Stability
    revenue_volatility_pct: float  # CV of daily revenue
    revenue_concentration_pct: float  # top customer share

    # Composite
    health_score: int  # 0-100
    health_label: str  # Excellent / Good / Fair / At Risk / Critical
    risk_flags: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Period info
    period_start: str = ""
    period_end: str = ""
    txn_count: int = 0


class FinancialHealthAnalyzer:
    """Computes comprehensive financial health metrics from transaction data.

    Designed for Kenyan micro and small businesses running on mobile money.
    Uses heuristics suitable for informal cash-based businesses where
    formal balance sheets may not exist.
    """

    def __init__(self, transactions=None):
        if isinstance(transactions, pd.DataFrame):
            self.df = transactions.copy()
        elif isinstance(transactions, list):
            self.df = pd.DataFrame(transactions)
        else:
            self.df = pd.DataFrame()
        self._prepare_data()

    def _prepare_data(self):
        if self.df.empty:
            return

        if "amount_kes" not in self.df.columns:
            if "amount_minor" in self.df.columns:
                self.df["amount_kes"] = (
                    pd.to_numeric(self.df["amount_minor"], errors="coerce").fillna(0).abs() / 100.0
                )
            elif "amount" in self.df.columns:
                self.df["amount_kes"] = pd.to_numeric(self.df["amount"], errors="coerce").fillna(0).abs()
            else:
                self.df["amount_kes"] = 0.0

        if "direction" not in self.df.columns:
            if "type" in self.df.columns:
                self.df["direction"] = self.df["type"].apply(
                    lambda t: "in" if str(t).lower() in ("credit", "in") else "out"
                )
            else:
                self.df["direction"] = "out"

        if "local_date" not in self.df.columns:
            if "date" in self.df.columns:
                self.df["local_date"] = self.df["date"].astype(str).str.slice(0, 10)
            elif "ts" in self.df.columns:
                self.df["local_date"] = pd.to_datetime(self.df["ts"], errors="coerce").dt.strftime("%Y-%m-%d")
            else:
                self.df["local_date"] = datetime.today().strftime("%Y-%m-%d")

    def assess(self) -> FinancialHealthReport:
        """Run full financial health assessment and return a scored report."""
        if self.df.empty:
            return FinancialHealthReport(
                current_ratio=0.0,
                quick_ratio=0.0,
                cash_balance_kes=0.0,
                total_current_assets_kes=0.0,
                total_current_liabilities_kes=0.0,
                days_of_cash=0,
                monthly_burn_rate_kes=0.0,
                monthly_revenue_kes=0.0,
                burn_multiple=0.0,
                debt_to_revenue_ratio=0.0,
                debt_service_coverage=0.0,
                gross_margin_pct=0.0,
                operating_margin_pct=0.0,
                net_margin_pct=0.0,
                revenue_growth_pct=None,
                revenue_volatility_pct=0.0,
                revenue_concentration_pct=0.0,
                health_score=0,
                health_label="No Data",
                risk_flags=["No transaction data available."],
                recommendations=["Upload a mobile money statement to get started."],
                period_start="",
                period_end="",
                txn_count=0,
            )

        inflows = self.df[self.df["direction"] == "in"]
        outflows = self.df[self.df["direction"] == "out"]

        total_revenue = inflows["amount_kes"].sum()
        total_outflow = outflows["amount_kes"].sum()
        dates = pd.to_datetime(self.df["local_date"], format='mixed', dayfirst=True)
        unique_days = self.df["local_date"].nunique()

        period_start = str(self.df["local_date"].min())
        period_end = str(self.df["local_date"].max())
        txn_count = len(self.df)

        risk_flags: List[str] = []
        recommendations: List[str] = []

        # --- LIQUIDITY ---
        cash_balance = self._estimate_cash_balance()
        # Estimate current liabilities from outgoing obligations patterns
        daily_outflow = total_outflow / max(1, unique_days)
        current_liabilities = daily_outflow * 30  # 30 days of obligations as proxy
        current_assets = cash_balance + (total_revenue * 0.15)  # cash + ~15% receivables estimate

        current_ratio = current_assets / max(1.0, current_liabilities)
        quick_ratio = cash_balance / max(1.0, current_liabilities)

        # --- RUNWAY & BURN ---
        monthly_burn = daily_outflow * 30
        monthly_revenue = (total_revenue / max(1, unique_days)) * 30
        days_of_cash = int(cash_balance / max(1.0, daily_outflow))
        burn_multiple = monthly_burn / max(1.0, monthly_revenue)

        if days_of_cash < 7:
            risk_flags.append(f"Critical: only {days_of_cash} days of cash remaining at current burn rate.")
            recommendations.append("Reduce non-essential spending immediately. Chase outstanding customer credits aggressively.")
        elif days_of_cash < 30:
            risk_flags.append(f"Low runway: {days_of_cash} days of cash. Less than 30 days buffer.")
            recommendations.append("Build a cash reserve of at least 30 days of operating expenses.")
        elif days_of_cash < 90:
            recommendations.append("Consider setting aside excess cash in a separate savings account or SACCO.")

        # --- LEVERAGE ---
        # Estimate debt obligations from financing-related outflows
        if "category" in outflows.columns:
            financing_mask = outflows["category"].apply(
                lambda c: str(c).lower() in ("financing", "loan", "fuliza", "overdraft", "interest", "debt")
            )
            financing_out = outflows.loc[financing_mask, "amount_kes"].sum()
        else:
            financing_out = 0.0

        debt_to_revenue = financing_out / max(1.0, total_revenue)
        operating_cf = total_revenue - total_outflow + financing_out  # add back financing as it's not operating
        debt_service_coverage = operating_cf / max(1.0, financing_out) if financing_out > 0 else 999.0

        if debt_to_revenue > 0.25:
            risk_flags.append(f"High debt burden: {debt_to_revenue:.0%} of revenue goes to debt service.")
            recommendations.append("Prioritize paying down high-cost debt (Fuliza, M-Shwari) before taking new credit.")
        elif debt_to_revenue > 0.10:
            recommendations.append("Monitor debt levels; explore lower-cost financing options like SACCO loans.")

        # --- PROFITABILITY ---
        gross_margin = ((total_revenue - total_outflow + financing_out) / max(1.0, total_revenue)) * 100
        operating_margin = (operating_cf / max(1.0, total_revenue)) * 100
        net_margin = ((total_revenue - total_outflow) / max(1.0, total_revenue)) * 100

        if net_margin < 0:
            risk_flags.append("Business is operating at a net loss — expenses exceed revenue.")
            recommendations.append("Review all recurring expenses and identify at least 10% to cut or renegotiate.")
        elif net_margin < 5:
            recommendations.append("Thin margins: explore ways to increase prices or reduce COGS by buying in bulk.")

        # --- REVENUE GROWTH ---
        rev_growth = self._compute_revenue_growth()
        if rev_growth is not None:
            if rev_growth < -10:
                risk_flags.append(f"Revenue declining {rev_growth:.0f}% period-over-period.")
                recommendations.append("Diversify revenue streams or launch a promotion to boost sales.")
            elif rev_growth > 20:
                recommendations.append("Strong growth — ensure you have enough working capital to sustain expansion.")

        # --- STABILITY ---
        daily_in = inflows.groupby("local_date")["amount_kes"].sum()
        revenue_cv = (daily_in.std() / max(1.0, daily_in.mean())) * 100 if len(daily_in) > 1 else 0.0

        top_customer_share = self._top_customer_concentration()

        if revenue_cv > 60:
            risk_flags.append(f"Highly volatile revenue (CV={revenue_cv:.0f}%). Income is unpredictable day-to-day.")
            recommendations.append("Consider adding steadier revenue lines like contract supply agreements or membership models.")

        if top_customer_share > 30:
            risk_flags.append(f"Concentration risk: top customer represents {top_customer_share:.0f}% of revenue.")
            recommendations.append("Diversify your customer base to reduce dependency on any single buyer.")

        # --- COMPOSITE HEALTH SCORE ---
        health_score, health_label = self._compute_health_score(
            days_of_cash=days_of_cash,
            net_margin=net_margin,
            current_ratio=current_ratio,
            debt_to_revenue=debt_to_revenue,
            revenue_growth=rev_growth,
            revenue_cv=revenue_cv,
        )

        return FinancialHealthReport(
            current_ratio=round(current_ratio, 2),
            quick_ratio=round(quick_ratio, 2),
            cash_balance_kes=round(cash_balance, 0),
            total_current_assets_kes=round(current_assets, 0),
            total_current_liabilities_kes=round(current_liabilities, 0),
            days_of_cash=days_of_cash,
            monthly_burn_rate_kes=round(monthly_burn, 0),
            monthly_revenue_kes=round(monthly_revenue, 0),
            burn_multiple=round(burn_multiple, 2),
            debt_to_revenue_ratio=round(debt_to_revenue, 4),
            debt_service_coverage=round(debt_service_coverage, 1),
            gross_margin_pct=round(gross_margin, 1),
            operating_margin_pct=round(operating_margin, 1),
            net_margin_pct=round(net_margin, 1),
            revenue_growth_pct=round(rev_growth, 1) if rev_growth is not None else None,
            revenue_volatility_pct=round(revenue_cv, 1),
            revenue_concentration_pct=round(top_customer_share, 1),
            health_score=health_score,
            health_label=health_label,
            risk_flags=risk_flags,
            recommendations=recommendations,
            period_start=period_start,
            period_end=period_end,
            txn_count=txn_count,
        )

    def _estimate_cash_balance(self) -> float:
        """Estimate current cash position from net cumulative flow."""
        if self.df.empty:
            return 0.0

        inflow_total = self.df[self.df["direction"] == "in"]["amount_kes"].sum()
        outflow_total = self.df[self.df["direction"] == "out"]["amount_kes"].sum()

        # Assume 80% of net cumulative is available as cash
        net = inflow_total - outflow_total
        if net < 0:
            return max(0.0, inflow_total * 0.05)  # minimal cash if net negative

        return net * 0.80

    def _compute_revenue_growth(self) -> Optional[float]:
        """Compute period-over-period revenue growth by comparing first half to second half."""
        if self.df.empty:
            return None

        inflows = self.df[self.df["direction"] == "in"]
        if inflows.empty:
            return None

        dates_sorted = sorted(inflows["local_date"].unique())
        if len(dates_sorted) < 2:
            return None

        mid = len(dates_sorted) // 2
        first_half_dates = dates_sorted[:mid]
        second_half_dates = dates_sorted[mid:]

        first_rev = inflows[inflows["local_date"].isin(first_half_dates)]["amount_kes"].sum()
        second_rev = inflows[inflows["local_date"].isin(second_half_dates)]["amount_kes"].sum()

        # Normalize by days in each half
        first_days = len(first_half_dates)
        second_days = len(second_half_dates)

        if first_days == 0 or first_rev == 0:
            return None

        daily_first = first_rev / first_days
        daily_second = second_rev / second_days

        return ((daily_second - daily_first) / daily_first) * 100

    def _top_customer_concentration(self) -> float:
        """Compute what fraction of total revenue comes from the top customer."""
        inflows = self.df[self.df["direction"] == "in"]
        if inflows.empty:
            return 0.0

        total = inflows["amount_kes"].sum()
        if total == 0:
            return 0.0

        top = inflows.groupby("counterparty")["amount_kes"].sum().max()
        return (top / total) * 100

    def _compute_health_score(
        self,
        days_of_cash: int,
        net_margin: float,
        current_ratio: float,
        debt_to_revenue: float,
        revenue_growth: Optional[float],
        revenue_cv: float,
    ) -> Tuple[int, str]:
        """Compute a 0-100 composite health score with label."""

        def score_runway(days: int) -> float:
            if days >= 90:
                return 100.0
            if days >= 60:
                return 80.0
            if days >= 30:
                return 60.0
            if days >= 14:
                return 40.0
            if days >= 7:
                return 20.0
            return 0.0

        def score_margin(margin: float) -> float:
            if margin >= 20:
                return 100.0
            if margin >= 10:
                return 75.0
            if margin >= 5:
                return 50.0
            if margin >= 0:
                return 25.0
            return 0.0

        def score_liquidity(ratio: float) -> float:
            if ratio >= 2.0:
                return 100.0
            if ratio >= 1.5:
                return 80.0
            if ratio >= 1.0:
                return 50.0
            if ratio >= 0.5:
                return 25.0
            return 0.0

        def score_leverage(debt_pct: float) -> float:
            if debt_pct <= 0.05:
                return 100.0
            if debt_pct <= 0.10:
                return 80.0
            if debt_pct <= 0.20:
                return 50.0
            if debt_pct <= 0.35:
                return 25.0
            return 0.0

        def score_growth(growth: Optional[float]) -> float:
            if growth is None:
                return 50.0  # neutral if unknown
            if growth >= 20:
                return 100.0
            if growth >= 5:
                return 75.0
            if growth >= 0:
                return 50.0
            if growth >= -10:
                return 25.0
            return 0.0

        def score_stability(cv: float) -> float:
            if cv <= 20:
                return 100.0
            if cv <= 40:
                return 75.0
            if cv <= 60:
                return 50.0
            if cv <= 80:
                return 25.0
            return 0.0

        # Weighted composite
        weights = {
            "runway": 0.25,
            "margin": 0.25,
            "liquidity": 0.15,
            "leverage": 0.10,
            "growth": 0.15,
            "stability": 0.10,
        }

        raw = (
            weights["runway"] * score_runway(days_of_cash)
            + weights["margin"] * score_margin(net_margin)
            + weights["liquidity"] * score_liquidity(current_ratio)
            + weights["leverage"] * score_leverage(debt_to_revenue)
            + weights["growth"] * score_growth(revenue_growth)
            + weights["stability"] * score_stability(revenue_cv)
        )

        score = int(round(raw))

        if score >= 80:
            label = "Excellent"
        elif score >= 60:
            label = "Good"
        elif score >= 40:
            label = "Fair"
        elif score >= 20:
            label = "At Risk"
        else:
            label = "Critical"

        return score, label

    def daily_trend_df(self) -> pd.DataFrame:
        """Daily cashflow DataFrame for charting."""
        if self.df.empty:
            return pd.DataFrame(columns=["date", "inflow", "outflow", "net", "cumulative_net"])

        dates = sorted(self.df["local_date"].unique())
        rows = []
        cum = 0.0
        for d in dates:
            day = self.df[self.df["local_date"] == d]
            inflow = day[day["direction"] == "in"]["amount_kes"].sum()
            outflow = day[day["direction"] == "out"]["amount_kes"].sum()
            net = inflow - outflow
            cum += net
            rows.append({"date": d, "inflow": inflow, "outflow": outflow, "net": net, "cumulative_net": cum})
        return pd.DataFrame(rows)

    def weekly_summary(self) -> pd.DataFrame:
        """Weekly aggregated revenue and margin for trend analysis."""
        if self.df.empty:
            return pd.DataFrame()

        df = self.df.copy()
        df["date_dt"] = pd.to_datetime(df["local_date"], format='mixed', dayfirst=True)
        df["week"] = df["date_dt"].dt.to_period("W").astype(str)

        weekly = df.groupby("week").agg(
            revenue=("amount_kes", lambda x: x[df.loc[x.index, "direction"] == "in"].sum()),
            expenses=("amount_kes", lambda x: x[df.loc[x.index, "direction"] == "out"].sum()),
            txns=("amount_kes", "count"),
        ).reset_index()

        weekly["net"] = weekly["revenue"] - weekly["expenses"]
        weekly["margin_pct"] = (weekly["net"] / weekly["revenue"].replace(0, 1.0)) * 100
        return weekly
