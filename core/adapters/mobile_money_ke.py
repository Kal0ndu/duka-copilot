"""Adapter for Kenyan mobile money statements (CSV format)."""
import io
import re
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
                status = str(row.get("Transaction Status", "Completed")).strip().lower()
                if status and status not in ("completed", "nan"):
                    continue
                paid_in = abs(self._parse_kes(row.get("Paid In", row.get("Money In", 0))))
                # Real exports write withdrawals as negative numbers ("-200.00").
                withdrawn = abs(self._parse_kes(row.get("Withdrawn", row.get("Money Out", 0))))
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
                # Exports mix "2026-10-15 21:58:49", "15/10/2026 21:51" and
                # "Oct 15, 2026 08:32 PM"; parse the whole timestamp, not its first word.
                ts, normalized_date = self._normalize_ts(ts)

                records.append({
                    "date": normalized_date,
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

    @classmethod
    def _normalize_ts(cls, ts: str) -> tuple:
        """Return (ISO timestamp 'YYYY-MM-DD HH:MM:SS', ISO date) for a raw timestamp."""
        raw = str(ts).strip()
        try:
            if re.match(r'^\d{4}-\d{2}-\d{2}', raw):
                parsed = pd.to_datetime(raw)
            else:
                parsed = pd.to_datetime(raw, format='mixed', dayfirst=True)
            return parsed.strftime('%Y-%m-%d %H:%M:%S'), parsed.strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            date_part = cls._normalize_date(raw.split()[0] if " " in raw else raw)
            return raw, date_part

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """Normalize date string to ISO format (YYYY-MM-DD).
        
        Handles formats like:
        - 2026-10-15 (ISO)
        - 15/10/2026 (DD/MM/YYYY)
        - 15-10-2026 (DD-MM-YYYY)
        """
        import re
        date_str = str(date_str).strip()
        
        # Already ISO format?
        if re.match(r'^\d{4}-\d{2}-\d{2}', date_str):
            return date_str[:10]
        
        # DD/MM/YYYY or DD-MM-YYYY format?
        if re.match(r'^\d{2}[/-]\d{2}[/-]\d{4}', date_str):
            parts = re.split(r'[/-]', date_str)
            if len(parts) >= 3:
                dd, mm, yyyy = parts[0], parts[1], parts[2]
                return f"{yyyy}-{mm}-{dd}"
        
        # Fallback: try pandas inference
        try:
            parsed = pd.to_datetime(date_str, format='mixed', dayfirst=True)
            return parsed.strftime('%Y-%m-%d')
        except Exception:
            return date_str

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
        if "till" in d or "buy goods" in d or "lipa na" in d or "merchant payment" in d:
            return "till"
        if "customer payment to" in d:  # Pochi la Biashara
            return "send"
        if "transfer from bank" in d:
            return "deposit"
        if "send" in d or "sent to" in d or "transfer to" in d:
            return "send"
        if "receive" in d or "received from" in d or "payment from" in d:
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
