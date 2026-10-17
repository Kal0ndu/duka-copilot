"""Adapter for Kenyan mobile money statements (CSV format)."""
import io
import pandas as pd
from .base import StatementAdapter, CANONICAL_COLUMNS


class MobileMoneyKeAdapter(StatementAdapter):
    """Parses the standard mobile-money CSV export format used in Kenya."""

    platform = "mobile_money_ke"

    # Expected CSV columns from a typical mobile-money statement.
    EXPECTED_HEADERS = [
        "Receipt No.",
        "Completion Time",
        "Details",
        "Transaction Status",
        "Paid In",
        "Withdrawn",
        "Balance",
    ]

    def detect(self, file_bytes: bytes) -> bool:
        """Heuristic: first line contains expected headers."""
        try:
            first_line = file_bytes.split(b"\n")[0].decode("utf-8", errors="ignore")
            return "Receipt No" in first_line and "Completion Time" in first_line
        except Exception:
            return False

    def parse(self, file_content) -> list:
        """Parse CSV content (bytes or str) into normalized transaction dicts."""
        if isinstance(file_content, bytes):
            text = file_content.decode("utf-8", errors="ignore")
        else:
            text = str(file_content)

        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        if not lines:
            return []

        header = [c.strip() for c in lines[0].split(",")]

        # Case 1: Synthetic test format (msisdn, date, time, amount, category, counterparty, type)
        if "msisdn" in header and "amount" in header and "type" in header:
            df = pd.read_csv(io.StringIO(text))
            df.columns = [c.strip() for c in df.columns]
            if len(df) == 0:
                return []
            records = []
            for _, row in df.iterrows():
                amt = float(row.get("amount", 0))
                txn_type = str(row.get("type", "credit" if amt > 0 else "debit")).lower()
                records.append({
                    "msisdn": str(row.get("msisdn", "")),
                    "date": str(row.get("date", "")),
                    "time": str(row.get("time", "")),
                    "amount": amt,
                    "category": str(row.get("category", "uncategorised")),
                    "counterparty": str(row.get("counterparty", "")),
                    "type": txn_type,
                    "direction": "in" if amt > 0 or txn_type == "credit" else "out",
                    "amount_minor": int(round(abs(amt) * 100)),
                })
            return records

        # Case 2: Standard M-Pesa CSV
        if any("receipt" in h.lower() for h in header) and (any("paid in" in h.lower() for h in header) or any("details" in h.lower() for h in header)):
            df = pd.read_csv(io.StringIO(text))
            df.columns = [c.strip() for c in df.columns]
            records = []
            for _, row in df.iterrows():
                paid_in = self._parse_kes(row.get("Paid In", row.get("Money In", 0)))
                withdrawn = self._parse_kes(row.get("Withdrawn", row.get("Money Out", 0)))
                balance = self._parse_kes(row.get("Balance", 0))
                details = str(row.get("Details", row.get("Description", "")))
                receipt = str(row.get("Receipt No.", row.get("Receipt", "")))
                ts = str(row.get("Completion Time", row.get("Date", "")))
                time_str = str(row.get("Time", ""))

                if paid_in > 0:
                    amount_val = paid_in / 100.0
                    direction = "in"
                    txn_type = "credit"
                elif withdrawn > 0:
                    amount_val = - (withdrawn / 100.0)
                    direction = "out"
                    txn_type = "debit"
                else:
                    continue

                channel = self._infer_channel(details)
                date_str = ts.split()[0] if " " in ts else ts

                records.append({
                    "date": date_str,
                    "time": time_str,
                    "ts": ts,
                    "receipt": receipt,
                    "reference": receipt,
                    "amount": amount_val,
                    "amount_minor": int(round(abs(amount_val) * 100)),
                    "direction": direction,
                    "type": txn_type,
                    "balance": balance / 100.0,
                    "balance_after_minor": balance,
                    "counterparty": details,
                    "counterparty_raw": details,
                    "description": details,
                    "description_raw": details,
                    "channel": channel,
                    "category": str(row.get("Category", channel)),
                })
            return records

        # If missing required columns, raise ValueError
        raise ValueError(f"Unrecognized CSV format. Headers found: {header}")

    def get_summary(self, rows: list) -> dict:
        """Calculate high-level summary metrics from parsed transactions."""
        if not rows:
            return {"count": 0, "credits": 0, "debits": 0, "net": 0}
        credits = sum(r["amount"] for r in rows if r.get("amount", 0) > 0)
        debits = sum(abs(r["amount"]) for r in rows if r.get("amount", 0) < 0)
        return {
            "count": len(rows),
            "credits": credits,
            "debits": debits,
            "net": credits - debits,
        }

    @staticmethod
    def _parse_kes(val) -> int:
        """Parse a KES amount to integer minor units (cents)."""
        if pd.isna(val):
            return 0
        if isinstance(val, (int, float)):
            return int(round(float(val) * 100))
        s = str(val).replace(",", "").replace("KES", "").replace("Ksh", "").strip()
        try:
            return int(round(float(s) * 100))
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _infer_channel(details: str) -> str:
        """Infer the channel from transaction details text."""
        d = details.lower()
        if "till" in d or "buy goods" in d or "lipa na" in d:
            return "till"
        if "send" in d or "sent to" in d or "transfer to" in d:
            return "send"
        if "receive" in d or "received from" in d:
            return "receive"
        if "withdraw" in d or "agent" in d:
            return "withdraw"
        if "deposit" in d:
            return "deposit"
        if "bill" in d or "paybill" in d:
            return "bill"
        if "airtime" in d:
            return "airtime"
        if "overdraft" in d or "fuliza" in d:
            return "overdraft"
        if "loan" in d or "mshwari" in d or "kcb" in d:
            return "loan"
        if "fee" in d or "charge" in d or "cost" in d:
            return "fee"
        if "reversal" in d:
            return "reversal"
        return "other"


# Alias for compatibility
MobileMoneyKEAdapter = MobileMoneyKeAdapter
