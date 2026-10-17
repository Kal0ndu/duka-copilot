"""Tests for agent/verify_numbers.py"""
from agent.verify_numbers import verify_numbers, extract_numbers


class TestExtractNumbers:
    def test_kes_amounts(self):
        found = extract_numbers("Your revenue is KES 15,000 this month")
        assert len(found) >= 1
        assert found[0][1] == 15000.0

    def test_ksh_amounts(self):
        found = extract_numbers("Balance: KSh 2,500.00")
        assert len(found) >= 1
        assert found[0][1] == 2500.0

    def test_percentage(self):
        found = extract_numbers("Your margin is 23.5%")
        assert len(found) >= 1
        assert abs(found[0][1] - 0.235) < 1e-9

    def test_no_numbers(self):
        found = extract_numbers("How is my business doing?")
        assert len(found) == 0


class TestVerifyNumbers:
    def test_passes_when_numbers_match(self):
        result = verify_numbers(
            "Your revenue is KES 15,000",
            {"analytics": {"total_revenue": 15000}},
        )
        assert result["passed"] is True

    def test_violations_when_mismatch(self):
        result = verify_numbers(
            "Your revenue is KES 15,000",
            {"analytics": {"total_revenue": 12000}},
        )
        assert result["passed"] is False
        assert len(result["violations"]) > 0

    def test_passes_when_no_numbers(self):
        result = verify_numbers(
            "Your business is doing well",
            {"analytics": {"total_revenue": 15000}},
        )
        assert result["passed"] is True

    def test_check_count_nonzero(self):
        result = verify_numbers(
            "Revenue KES 15,000, costs KES 8,000",
            {"analytics": {"total_revenue": 15000, "total_costs": 8000}},
        )
        assert result["checked_count"] > 0
