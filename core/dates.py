"""Parsing the ledger's local dates."""
import pandas as pd


def parse_local_dates(values) -> pd.Series:
    """Parse a column of dates. ISO 'YYYY-MM-DD...' values are read as ISO;
    anything else ('15/10/2026') day first. Never pass ISO dates through
    dayfirst=True: dateutil then reads '2026-09-12' as 9 December."""
    s = pd.Series(values).astype(str).str.strip()
    iso = s.str.match(r"^\d{4}-\d{2}-\d{2}")
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    if iso.any():
        out[iso] = pd.to_datetime(s[iso].str.slice(0, 10), format="%Y-%m-%d", errors="coerce")
    if (~iso).any():
        out[~iso] = pd.to_datetime(s[~iso], format="mixed", dayfirst=True, errors="coerce")
    return out
