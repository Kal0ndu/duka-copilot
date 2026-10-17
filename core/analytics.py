"""Business health analytics: revenue, costs, margin, trends."""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal
import pandas as pd
import numpy as np


@dataclass
class HealthMetrics:
    period_start: str
    period_end: str
    revenue_minor: int
    cogs_minor: int
    opex_minor: int
    financing_cost_minor: int
    personal_outflow_minor: int
    operating_cashflow_minor: int
    personal_mix_bp: int  # basis points
    txn_count: int
    best_day: str
    worst_day: str
    gross_margin_pct: float  # 0.0-100.0
    operating_margin_pct: float


def compute_business_health(
    df: pd.DataFrame,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
) -> HealthMetrics:
    """Compute business health metrics from a canonical ledger DataFrame.

    Expects columns: local_date, amount_minor, direction, category_kind, fee_minor
    """
    if period_start:
        df = df[df["local_date"] >= period_start]
    if period_end:
        df = df[df["local_date"] <= period_end]

    if len(df) == 0:
        return HealthMetrics(
            period_start=period_start or "",
            period_end=period_end or "",
            revenue_minor=0, cogs_minor=0, opex_minor=0,
            financing_cost_minor=0, personal_outflow_minor=0,
            operating_cashflow_minor=0, personal_mix_bp=0,
            txn_count=0, best_day="", worst_day="",
            gross_margin_pct=0.0, operating_margin_pct=0.0,
        )

    # Revenue: income kind, direction 'in'
    revenue = df[(df["category_kind"] == "income") & (df["direction"] == "in")]["amount_minor"].sum()

    # COGS: cogs kind, direction 'out'
    cogs = df[(df["category_kind"] == "cogs") & (df["direction"] == "out")]["amount_minor"].sum()

    # OPEX: opex kind + tax kind, direction 'out', including fees
    opex_mask = (df["category_kind"].isin(["opex", "tax"])) & (df["direction"] == "out")
    opex = (df.loc[opex_mask, "amount_minor"] + df.loc[opex_mask, "fee_minor"].fillna(0)).sum()

    # Financing costs: financing kind, direction 'out'
    fin_mask = (df["category_kind"] == "financing") & (df["direction"] == "out")
    fin_cost = (df.loc[fin_mask, "amount_minor"] + df.loc[fin_mask, "fee_minor"].fillna(0)).sum()

    # Personal outflows
    pers_mask = (df["category_kind"] == "personal") & (df["direction"] == "out")
    personal = df.loc[pers_mask, "amount_minor"].sum()

    # Operating cashflow
    op_cf = revenue - cogs - opex

    # Personal mix (basis points of total outflows)
    total_out = df[df["direction"] == "out"]["amount_minor"].sum()
    pers_mix_bp = int(round((personal / total_out) * 10000)) if total_out > 0 else 0

    # Margins
    gross_margin = ((revenue - cogs) / revenue * 100) if revenue > 0 else 0.0
    op_margin = (op_cf / revenue * 100) if revenue > 0 else 0.0

    # Best/worst day by daily operating cashflow
    daily = df.groupby("local_date").apply(
        lambda g: (
            g[(g["category_kind"] == "income") & (g["direction"] == "in")]["amount_minor"].sum()
            - g[(g["category_kind"].isin(["cogs", "opex", "tax"])) & (g["direction"] == "out")][
                ["amount_minor", "fee_minor"]
            ].fillna(0).sum().sum()
        )
    )
    if len(daily) > 0:
        best_day = str(daily.idxmax())
        worst_day = str(daily.idxmin())
    else:
        best_day = worst_day = ""

    return HealthMetrics(
        period_start=period_start or str(df["local_date"].min()),
        period_end=period_end or str(df["local_date"].max()),
        revenue_minor=int(revenue),
        cogs_minor=int(cogs),
        opex_minor=int(opex),
        financing_cost_minor=int(fin_cost),
        personal_outflow_minor=int(personal),
        operating_cashflow_minor=int(op_cf),
        personal_mix_bp=pers_mix_bp,
        txn_count=len(df),
        best_day=best_day,
        worst_day=worst_day,
        gross_margin_pct=round(gross_margin, 1),
        operating_margin_pct=round(op_margin, 1),
    )


def get_ledger_summary(df: pd.DataFrame, period: str = "month") -> List[Dict]:
    """Aggregate the ledger by category and period."""
    if "month" not in df.columns:
        df = df.copy()
        df["month"] = df["local_date"].str[:7]

    summary = (
        df.groupby(["month", "category_kind"])
        .agg(total_minor=("amount_minor", "sum"), txn_count=("amount_minor", "count"))
        .reset_index()
    )
    return summary.to_dict(orient="records")


def compute_weekday_factors(df: pd.DataFrame, window_weeks: int = 12) -> pd.DataFrame:
    """Compute weekday seasonality factors for the forecaster."""
    df = df.copy()
    df["weekday"] = pd.to_datetime(df["local_date"]).dt.dayofweek  # 0=Mon

    daily = (
        df.groupby(["local_date", "weekday"])
        .agg(
            inflow_minor=("amount_minor", lambda x: x[df.loc[x.index, "direction"] == "in"].sum()),
            outflow_minor=("amount_minor", lambda x: x[df.loc[x.index, "direction"] == "out"].sum()),
        )
        .reset_index()
    )

    avg_in = daily["inflow_minor"].mean()
    avg_out = daily["outflow_minor"].mean()

    factors = daily.groupby("weekday").agg(
        inflow_factor=("inflow_minor", lambda x: x.mean() / avg_in if avg_in > 0 else 1.0),
        outflow_factor=("outflow_minor", lambda x: x.mean() / avg_out if avg_out > 0 else 1.0),
    ).reset_index()

    return factors


class BusinessAnalytics:
    """Analytics engine for business transactions (accepts list of dicts or DataFrame)."""

    CATEGORY_MAP = {
        "sales": ("income", "Sales"),
        "sales_till": ("income", "Till Sales"),
        "sales_transfer": ("income", "Customer Transfer"),
        "fares": ("income", "Fares"),
        "printing": ("income", "Printing & Services"),
        "contracts": ("income", "Contracts"),
        "stock_purchase": ("cogs", "Stock & Inventory"),
        "stock_purchases": ("cogs", "Stock & Inventory"),
        "flour_sugar": ("cogs", "Raw Materials"),
        "charcoal": ("cogs", "Fuel & Energy"),
        "parts": ("cogs", "Spare Parts"),
        "fuel": ("cogs", "Fuel"),
        "water_bulk": ("cogs", "Bulk Water"),
        "bale_purchase": ("cogs", "Mitumba Bales"),
        "materials": ("cogs", "Raw Materials"),
        "labour": ("cogs", "Casual Labour"),
        "rent": ("opex", "Rent & Premises"),
        "utilities": ("opex", "Utilities & Power"),
        "electricity": ("opex", "Electricity"),
        "internet": ("opex", "Internet & Tech"),
        "airtime": ("opex", "Airtime & Data"),
        "airtime_data": ("opex", "Airtime & Data"),
        "wages": ("opex", "Staff Wages"),
        "repairs": ("opex", "Repairs & Maintenance"),
        "license_tax": ("tax", "Licenses & Taxes"),
        "tax": ("tax", "Taxes & Levies"),
        "txn_charges": ("opex", "Transaction Fees"),
        "fee": ("opex", "Transaction Fees"),
        "loan_repayment": ("financing", "Loan Repayment"),
        "overdraft_fee": ("financing", "Overdraft Interest"),
        "overdraft": ("financing", "Overdraft"),
        "personal": ("personal", "Personal Withdrawal"),
        "personal_withdrawal": ("personal", "Personal Withdrawal"),
        "family_transfer": ("personal", "Family Support"),
        "school_fees": ("personal", "School Fees"),
        "uncategorised": ("unknown", "Other / Uncategorised"),
        "unclassified": ("unknown", "Other / Uncategorised"),
    }

    def __init__(self, data):
        if isinstance(data, pd.DataFrame):
            self.df = data.copy()
        elif isinstance(data, list):
            self.df = pd.DataFrame(data)
        else:
            self.df = pd.DataFrame()

        self._normalize_df()

    def _normalize_df(self):
        if self.df.empty:
            self.df = pd.DataFrame(columns=[
                "date", "time", "local_date", "amount", "amount_minor", "direction",
                "category", "category_kind", "counterparty", "fee_minor"
            ])
            return

        # Normalize column names
        cols = {c: c.lower() for c in self.df.columns}
        self.df = self.df.rename(columns=cols)

        # Local date
        if "local_date" not in self.df.columns:
            if "date" in self.df.columns:
                self.df["local_date"] = self.df["date"].astype(str).str.slice(0, 10)
            elif "ts" in self.df.columns:
                self.df["local_date"] = pd.to_datetime(self.df["ts"], errors="coerce").dt.strftime("%Y-%m-%d")
            else:
                self.df["local_date"] = ""
        else:
            self.df["local_date"] = self.df["local_date"].astype(str).str.slice(0, 10)

        if "date" not in self.df.columns:
            self.df["date"] = self.df["local_date"]

        # Amounts
        if "amount_minor" in self.df.columns:
            self.df["amount_minor"] = pd.to_numeric(self.df["amount_minor"], errors="coerce").fillna(0).astype(int)
            if "amount" not in self.df.columns:
                self.df["amount"] = self.df["amount_minor"] / 100.0
        elif "amount" in self.df.columns:
            self.df["amount"] = pd.to_numeric(self.df["amount"], errors="coerce").fillna(0)
            self.df["amount_minor"] = (self.df["amount"].abs() * 100).round().astype(int)
        else:
            self.df["amount"] = 0.0
            self.df["amount_minor"] = 0

        # Direction
        if "direction" not in self.df.columns:
            if "type" in self.df.columns:
                self.df["direction"] = self.df["type"].apply(
                    lambda t: "in" if str(t).lower() in ("credit", "in") else "out"
                )
            else:
                self.df["direction"] = self.df["amount"].apply(lambda a: "in" if a > 0 else "out")

        # Fee minor
        if "fee_minor" not in self.df.columns:
            self.df["fee_minor"] = 0
        else:
            self.df["fee_minor"] = pd.to_numeric(self.df["fee_minor"], errors="coerce").fillna(0).astype(int)

        # Counterparty
        if "counterparty" not in self.df.columns:
            if "counterparty_token" in self.df.columns:
                self.df["counterparty"] = self.df["counterparty_token"]
            elif "counterparty_raw" in self.df.columns:
                self.df["counterparty"] = self.df["counterparty_raw"]
            elif "details" in self.df.columns:
                self.df["counterparty"] = self.df["details"]
            else:
                self.df["counterparty"] = "Unknown"
        self.df["counterparty"] = self.df["counterparty"].fillna("Unknown").astype(str)

        # Category and Category Kind
        if "category" not in self.df.columns:
            self.df["category"] = "uncategorised"

        def _infer_kind(row):
            cat_raw = str(row.get("category", "")).lower()
            if cat_raw in self.CATEGORY_MAP:
                return self.CATEGORY_MAP[cat_raw][0]
            if row.get("direction") == "in":
                return "income"
            return "opex"

        if "category_kind" not in self.df.columns:
            self.df["category_kind"] = self.df.apply(_infer_kind, axis=1)

    def kpi_summary(self) -> Dict:
        """Calculate executive business health KPIs."""
        if self.df.empty:
            return {
                "total_revenue": 0.0, "total_costs": 0.0, "cogs": 0.0, "opex": 0.0,
                "financing_cost": 0.0, "personal_outflow": 0.0, "net_profit": 0.0,
                "operating_cashflow": 0.0, "margin_pct": 0.0, "gross_margin_pct": 0.0,
                "operating_margin_pct": 0.0, "personal_mix_pct": 0.0, "personal_mix_bp": 0,
                "txn_count": 0, "avg_daily_revenue": 0.0, "best_day": "N/A", "worst_day": "N/A"
            }

        health = compute_business_health(self.df)
        revenue_kes = health.revenue_minor / 100.0
        cogs_kes = health.cogs_minor / 100.0
        opex_kes = health.opex_minor / 100.0
        financing_kes = health.financing_cost_minor / 100.0
        personal_kes = health.personal_outflow_minor / 100.0
        op_cashflow_kes = health.operating_cashflow_minor / 100.0
        total_costs_kes = cogs_kes + opex_kes + financing_kes

        unique_days = max(1, self.df["local_date"].nunique())
        avg_daily = revenue_kes / unique_days

        return {
            "total_revenue": revenue_kes,
            "total_costs": total_costs_kes,
            "cogs": cogs_kes,
            "opex": opex_kes,
            "financing_cost": financing_kes,
            "personal_outflow": personal_kes,
            "net_profit": revenue_kes - total_costs_kes,
            "operating_cashflow": op_cashflow_kes,
            "margin_pct": health.operating_margin_pct,
            "gross_margin_pct": health.gross_margin_pct,
            "operating_margin_pct": health.operating_margin_pct,
            "personal_mix_pct": round(health.personal_mix_bp / 100.0, 1),
            "personal_mix_bp": health.personal_mix_bp,
            "txn_count": health.txn_count,
            "avg_daily_revenue": avg_daily,
            "best_day": health.best_day or "N/A",
            "worst_day": health.worst_day or "N/A",
        }

    def category_breakdown(self) -> Dict[str, float]:
        """Outflow totals grouped by friendly category label."""
        outflows = self.df[self.df["direction"] == "out"]
        if outflows.empty:
            return {}

        breakdown = {}
        for cat, group in outflows.groupby("category"):
            label = self.CATEGORY_MAP.get(str(cat).lower(), ("opex", str(cat).title()))[1]
            amt_kes = group["amount_minor"].sum() / 100.0
            breakdown[label] = breakdown.get(label, 0.0) + amt_kes

        return dict(sorted(breakdown.items(), key=lambda x: x[1], reverse=True))

    def revenue_by_category(self) -> Dict[str, float]:
        """Inflow totals grouped by category."""
        inflows = self.df[self.df["direction"] == "in"]
        if inflows.empty:
            return {}
        rev = {}
        for cat, group in inflows.groupby("category"):
            label = self.CATEGORY_MAP.get(str(cat).lower(), ("income", str(cat).title()))[1]
            amt_kes = group["amount_minor"].sum() / 100.0
            rev[label] = rev.get(label, 0.0) + amt_kes
        return dict(sorted(rev.items(), key=lambda x: x[1], reverse=True))

    def daily_trend(self) -> Dict[str, float]:
        """Daily revenue trend dictionary {YYYY-MM-DD: KES}."""
        inflows = self.df[self.df["direction"] == "in"]
        if inflows.empty:
            return {}
        daily = inflows.groupby("local_date")["amount_minor"].sum() / 100.0
        return daily.to_dict()

    def daily_in_out_df(self) -> pd.DataFrame:
        """Daily DataFrame with inflow, outflow, net profit and cumulative net."""
        if self.df.empty:
            return pd.DataFrame(columns=["date", "inflow", "outflow", "net", "cumulative_net"])

        dates = sorted(self.df["local_date"].unique())
        rows = []
        cum = 0.0
        for d in dates:
            day_txns = self.df[self.df["local_date"] == d]
            inflow = day_txns[day_txns["direction"] == "in"]["amount_minor"].sum() / 100.0
            outflow = day_txns[day_txns["direction"] == "out"]["amount_minor"].sum() / 100.0
            net = inflow - outflow
            cum += net
            rows.append({
                "date": d,
                "inflow": inflow,
                "outflow": outflow,
                "net": net,
                "cumulative_net": cum,
            })
        return pd.DataFrame(rows)

    def weekday_distribution(self) -> pd.DataFrame:
        """Weekday performance (Monday=0 to Sunday=6)."""
        if self.df.empty:
            return pd.DataFrame()
        temp = self.df.copy()
        temp["weekday"] = pd.to_datetime(temp["local_date"]).dt.dayofweek
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        daily = temp.groupby(["local_date", "weekday"]).agg(
            inflow=("amount_minor", lambda x: x[temp.loc[x.index, "direction"] == "in"].sum() / 100.0),
            outflow=("amount_minor", lambda x: x[temp.loc[x.index, "direction"] == "out"].sum() / 100.0),
            txns=("amount_minor", "count")
        ).reset_index()

        summary = daily.groupby("weekday").agg(
            avg_inflow=("inflow", "mean"),
            avg_outflow=("outflow", "mean"),
            avg_txns=("txns", "mean")
        ).reset_index()

        summary["day_name"] = summary["weekday"].apply(lambda w: day_names[w])
        return summary.sort_values("weekday")

    def top_counterparties(self, n: int = 10, direction: Optional[str] = None) -> List[Tuple[str, float]]:
        """Top counterparties by total transaction value in KES."""
        df_sub = self.df
        if direction:
            df_sub = df_sub[df_sub["direction"] == direction]
        if df_sub.empty:
            return []

        grouped = df_sub.groupby("counterparty")["amount_minor"].sum() / 100.0
        top = grouped.sort_values(ascending=False).head(n)
        return [(str(k), float(v)) for k, v in top.items()]

    def to_dataframe(self) -> pd.DataFrame:
        return self.df

