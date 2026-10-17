"""Shared setup for the tests: lets them import the project's modules."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analytics import DATA, load_ledger  # noqa: E402


@pytest.fixture(scope="session")
def amina_rows():
    return load_ledger(DATA / "amina_grocery_ledger.csv")
