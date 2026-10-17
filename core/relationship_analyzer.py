"""Party Relationship Intelligence: customer segmentation, concentration risk, and churn analysis."""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, date
import pandas as pd


@dataclass
class PartyRelationshipMetrics:
    party_id: str
    party_name: str
    party_type: str  # 'customer' or 'supplier'
    transaction_count: int
    total_volume_kes: float
    inflow_kes: float
    outflow_kes: float
    avg_transaction_kes: float
    first_interaction: str
    last_interaction: str
    days_since_interaction: int
    concentration_pct: float
    is_concentration_risk: bool
    segment: str  # 'High Value', 'Growth', 'At Risk', 'Dormant'
    churn_risk_score: int  # 0 to 100
    recommendation: str


class RelationshipAnalyzer:
    """Analyze customer & supplier relationships from transactions."""

    def __init__(self, data=None):
        if isinstance(data, pd.DataFrame):
            self.df = data.copy()
        elif isinstance(data, list):
            self.df = pd.DataFrame(data)
        else:
            self.df = pd.DataFrame()
        self._prepare_data()

    def _prepare_data(self):
        if self.df.empty:
            return

        # Normalize party column
        if "counterparty" not in self.df.columns:
            for alt in ["counterparty_token", "counterparty_raw", "details"]:
                if alt in self.df.columns:
                    self.df["counterparty"] = self.df[alt]
                    break
            if "counterparty" not in self.df.columns:
                self.df["counterparty"] = "Walk-in Customer"

        self.df["counterparty"] = self.df["counterparty"].fillna("Walk-in Customer").astype(str)

        # Normalize date
        if "local_date" not in self.df.columns:
            if "date" in self.df.columns:
                self.df["local_date"] = self.df["date"].astype(str).str.slice(0, 10)
            elif "ts" in self.df.columns:
                self.df["local_date"] = pd.to_datetime(self.df["ts"], errors="coerce").dt.strftime("%Y-%m-%d")
            else:
                self.df["local_date"] = datetime.today().strftime("%Y-%m-%d")

        # Amount in KES
        if "amount_kes" not in self.df.columns:
            if "amount_minor" in self.df.columns:
                self.df["amount_kes"] = pd.to_numeric(self.df["amount_minor"], errors="coerce").fillna(0).abs() / 100.0
            elif "amount" in self.df.columns:
                self.df["amount_kes"] = pd.to_numeric(self.df["amount"], errors="coerce").fillna(0).abs()
            else:
                self.df["amount_kes"] = 0.0

        # Direction
        if "direction" not in self.df.columns:
            if "type" in self.df.columns:
                self.df["direction"] = self.df["type"].apply(
                    lambda t: "in" if str(t).lower() in ("credit", "in") else "out"
                )
            elif "amount" in self.df.columns:
                self.df["direction"] = self.df["amount"].apply(lambda a: "in" if a > 0 else "out")
            else:
                self.df["direction"] = "out"

    def analyze_parties(self) -> List[PartyRelationshipMetrics]:
        """Compute metrics for all counterparties."""
        if self.df.empty:
            return []

        # Reference date is maximum transaction date in dataset
        try:
            max_date = pd.to_datetime(self.df["local_date"]).max()
            if pd.isna(max_date):
                max_date = datetime.now()
        except Exception:
            max_date = datetime.now()

        total_inflow = self.df[self.df["direction"] == "in"]["amount_kes"].sum()
        total_outflow = self.df[self.df["direction"] == "out"]["amount_kes"].sum()

        results = []
        for party, group in self.df.groupby("counterparty"):
            inflows = group[group["direction"] == "in"]["amount_kes"].sum()
            outflows = group[group["direction"] == "out"]["amount_kes"].sum()
            total_vol = inflows + outflows
            count = len(group)

            first_seen = str(group["local_date"].min())
            last_seen = str(group["local_date"].max())

            try:
                last_dt = pd.to_datetime(last_seen)
                days_since = max(0, (max_date - last_dt).days)
            except Exception:
                days_since = 0

            # Determine party type
            party_type = "customer" if inflows >= outflows else "supplier"

            # Concentration calculation
            ref_total = total_inflow if party_type == "customer" else total_outflow
            concentration_pct = (inflows / total_inflow * 100.0) if party_type == "customer" and total_inflow > 0 else (
                (outflows / total_outflow * 100.0) if total_outflow > 0 else 0.0
            )
            is_concentration_risk = concentration_pct >= 20.0 and count >= 3

            # Churn risk scoring (0 to 100)
            if party_type == "customer":
                if days_since > 60:
                    churn_risk = min(100, 75 + (days_since - 60))
                elif days_since > 30:
                    churn_risk = min(75, 40 + (days_since - 30))
                elif days_since > 14:
                    churn_risk = 25
                else:
                    churn_risk = 5
            else:
                churn_risk = 0  # Churn risk is less relevant for suppliers

            # Segmentation
            if concentration_pct >= 15.0 or (inflows > 0.1 * total_inflow and count >= 5):
                segment = "High Value"
            elif days_since > 45:
                segment = "Dormant"
            elif days_since > 21:
                segment = "At Risk"
            else:
                segment = "Growth"

            # Actionable recommendations
            if is_concentration_risk:
                rec = "⚠️ Represents >20% of your revenue. Build relationships with more buyers to reduce reliance."
            elif segment == "High Value":
                rec = "⭐ Top customer. Offer priority service or wholesale loyalty perks to maintain loyalty."
            elif segment == "At Risk":
                rec = "⏳ Buying frequency is slowing down. Reach out via SMS or check-in call with a special promo."
            elif segment == "Dormant":
                rec = "💤 Inactive for over 45 days. Follow up to enquire if their needs changed or provide a win-back offer."
            else:
                rec = "✅ Active regular customer. Continue standard engagement."

            metrics = PartyRelationshipMetrics(
                party_id=party,
                party_name=party,
                party_type=party_type,
                transaction_count=count,
                total_volume_kes=round(total_vol, 2),
                inflow_kes=round(inflows, 2),
                outflow_kes=round(outflows, 2),
                avg_transaction_kes=round(total_vol / count, 2) if count > 0 else 0.0,
                first_interaction=first_seen,
                last_interaction=last_seen,
                days_since_interaction=days_since,
                concentration_pct=round(concentration_pct, 1),
                is_concentration_risk=is_concentration_risk,
                segment=segment,
                churn_risk_score=churn_risk,
                recommendation=rec,
            )
            results.append(metrics)

        return results

    def get_customers(self) -> List[PartyRelationshipMetrics]:
        """Return customers sorted by revenue contribution."""
        parties = self.analyze_parties()
        customers = [p for p in parties if p.party_type == "customer"]
        return sorted(customers, key=lambda c: c.inflow_kes, reverse=True)

    def get_suppliers(self) -> List[PartyRelationshipMetrics]:
        """Return suppliers sorted by spend."""
        parties = self.analyze_parties()
        suppliers = [p for p in parties if p.party_type == "supplier"]
        return sorted(suppliers, key=lambda s: s.outflow_kes, reverse=True)

    def get_concentration_risks(self) -> List[PartyRelationshipMetrics]:
        """Customers or suppliers with >20% concentration."""
        return [p for p in self.analyze_parties() if p.is_concentration_risk]

    def get_churn_risks(self) -> List[PartyRelationshipMetrics]:
        """Customers at risk of leaving (score >= 40)."""
        customers = self.get_customers()
        return [c for c in customers if c.churn_risk_score >= 40]
