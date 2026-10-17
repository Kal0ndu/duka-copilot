"""Statement adapter base class and canonical format definition."""
from typing import Protocol, runtime_checkable
import pandas as pd

# Canonical columns every adapter must produce.
CANONICAL_COLUMNS = [
    "ts",                  # datetime (UTC+3)
    "amount_minor",        # absolute amount in integer minor units (cents)
    "direction",           # 'in' or 'out'
    "balance_after_minor", # running balance after the transaction
    "counterparty_raw",    # free text (will be redacted)
    "description_raw",     # free text (will be redacted; untrusted)
    "reference",           # platform transaction code
    "channel",             # till, send, withdraw, bill, overdraft, loan, other
]

VALID_CHANNELS = {"till", "send", "receive", "withdraw", "deposit", "bill",
                  "airtime", "overdraft", "loan", "fee", "reversal", "other"}
VALID_DIRECTIONS = {"in", "out"}


@runtime_checkable
class StatementAdapter(Protocol):
    """Protocol for statement adapters. Each platform gets one implementation."""

    platform: str  # e.g. "mobile_money_ke"

    def detect(self, file_bytes: bytes) -> bool:
        """Return True if this adapter can parse the file."""
        ...

    def parse(self, file_bytes: bytes) -> pd.DataFrame:
        """Parse the file and return a DataFrame with CANONICAL_COLUMNS."""
        ...


def validate_canonical(df: pd.DataFrame) -> list[str]:
    """Validate a canonical DataFrame. Returns list of issue messages."""
    issues = []

    missing = set(CANONICAL_COLUMNS) - set(df.columns)
    if missing:
        issues.append(f"missing columns: {missing}")
        return issues

    # Check directions
    bad_dir = df[~df["direction"].isin(VALID_DIRECTIONS)]
    if len(bad_dir):
        issues.append(f"invalid directions at rows: {list(bad_dir.index[:10])}")

    # Check channels
    bad_chan = df[~df["channel"].isin(VALID_CHANNELS)]
    if len(bad_chan):
        issues.append(f"invalid channels at rows: {list(bad_chan.index[:10])}")

    # Check amounts are non-negative
    bad_amt = df[df["amount_minor"] < 0]
    if len(bad_amt):
        issues.append(f"negative amounts at rows: {list(bad_amt.index[:10])}")

    # Check timestamps are monotonic
    if not df["ts"].is_monotonic_increasing:
        issues.append("timestamps are not monotonic")

    # Check balance reconciliation
    for i in range(1, len(df)):
        prev_bal = df.iloc[i - 1]["balance_after_minor"]
        amt = df.iloc[i]["amount_minor"]
        direction = df.iloc[i]["direction"]
        expected = prev_bal + amt if direction == "in" else prev_bal - amt
        actual = df.iloc[i]["balance_after_minor"]
        if expected != actual:
            issues.append(
                f"balance mismatch at row {i}: "
                f"expected {expected}, got {actual}"
            )
            if len(issues) > 20:
                issues.append("...further balance checks skipped")
                break

    # Check duplicate references
    dupes = df[df["reference"].duplicated() & df["reference"].notna()]
    if len(dupes):
        issues.append(f"duplicate references at rows: {list(dupes.index[:10])}")

    return issues
