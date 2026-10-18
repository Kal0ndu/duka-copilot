"""Security test: the malicious-statement fixture (spec section 7.4's named
injection test case) must be detected and never treated as an instruction.

Uploaded statement content is untrusted data. The architecture's defence is
core.redaction.Redactor's injection scan plus wrap_untrusted() — not the
chat-prompt jailbreak phrase list in agent/policy_guard.py, which is a
separate layer for conversational input, not statement rows.
"""
import csv
from pathlib import Path

import pytest

from core.redaction import Redactor, wrap_untrusted

FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "mock_data" / "malicious_statement.csv"


def _load_rows():
    with open(FIXTURE_PATH, newline="") as f:
        return list(csv.DictReader(f))


class TestMaliciousStatementInjection:
    def test_fixture_exists_and_has_rows(self):
        rows = _load_rows()
        assert len(rows) > 0

    def test_fixture_contains_the_injection_payload(self):
        rows = _load_rows()
        hits = [r for r in rows if "IGNORE ALL PREVIOUS INSTRUCTIONS" in r["Details"].upper()]
        assert len(hits) == 1, "expected exactly one injection row in the fixture"

    def test_injection_row_is_flagged_by_redaction_scan(self):
        rows = _load_rows()
        hit = next(r for r in rows if "IGNORE ALL PREVIOUS INSTRUCTIONS" in r["Details"].upper())

        redactor = Redactor()
        result = redactor.redact(hit["Details"])

        assert "INSTRUCTION_OVERRIDE" in result.injection_flags, (
            "the injection scan must flag override attempts hidden in statement rows"
        )

    def test_clean_rows_are_not_flagged(self):
        rows = _load_rows()
        clean = [r for r in rows if "IGNORE ALL PREVIOUS INSTRUCTIONS" not in r["Details"].upper()]
        redactor = Redactor()
        flagged = [
            r for r in clean[:50]
            if redactor.redact(r["Details"]).injection_flags
        ]
        assert flagged == [], f"false positives on clean rows: {flagged}"

    def test_injection_payload_is_wrapped_as_untrusted_data(self):
        """Even once flagged, statement content must be delimited as data,
        never concatenated into something the LLM could read as an instruction."""
        rows = _load_rows()
        hit = next(r for r in rows if "IGNORE ALL PREVIOUS INSTRUCTIONS" in r["Details"].upper())

        wrapped = wrap_untrusted(hit["Details"], label="uploaded_file")

        assert wrapped.startswith("<uploaded_file>")
        assert wrapped.strip().endswith("</uploaded_file>")
