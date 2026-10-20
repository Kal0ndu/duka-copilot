from datetime import datetime

import pytest

from analytics import DATA
from parser import clean_details, parse_amount, parse_statement, parse_time

HEADER = "Receipt No.,Completion Time,Details,Transaction Status,Paid In,Withdrawn,Balance\n"
# Newest first, like a real export: a duplicate, a failed row, mixed date formats,
# amounts as text and a description broken over two lines
MESSY = HEADER + (
    'R3,15/10/2026 10:00,Pay Bill to 111 - SOKO SUPPLIES Acc. 9,Completed,,"-1,000.00",600.00\n'
    'R3,15/10/2026 10:00,Pay Bill to 111 - SOKO SUPPLIES Acc. 9,Completed,,"-1,000.00",600.00\n'
    'R2F,"Oct 15, 2026 09:30 AM",Payment from 0712***345 - JOHN,Failed,200.00,,1800.00\n'
    'R2,"Oct 15, 2026 09:00 AM","Payment  from 0712***345 -\nJOHN",Completed,"1,500.00",,1600.00\n'
    'R1,2026-10-15 08:00:00,Payment from 0700***111 - ANN,Completed,100.00,,100.00\n'
)


def write(tmp_path, text):
    path = tmp_path / "statement.csv"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("text, expected", [
    ("2026-10-15 21:54:47", datetime(2026, 10, 15, 21, 54, 47)),
    ("15/10/2026 21:54", datetime(2026, 10, 15, 21, 54)),
    ("Oct 15, 2026 09:54 PM", datetime(2026, 10, 15, 21, 54)),
])
def test_parse_time_reads_all_three_formats(text, expected):
    assert parse_time(text) == expected


def test_parse_time_rejects_unknown_format():
    with pytest.raises(ValueError):
        parse_time("15th October")


@pytest.mark.parametrize("text, expected", [
    ("1,250.00", 1250.0), ("-2,680.00", 2680.0), ("", 0.0), (None, 0.0), (" 40 ", 40.0)])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_clean_details_joins_lines_and_spaces():
    assert clean_details("Payment  from\n 07 -  JOHN ") == "Payment from 07 - JOHN"


def test_messy_statement_is_cleaned(tmp_path):
    txns, report = parse_statement(write(tmp_path, MESSY))
    assert [t["receipt"] for t in txns] == ["R1", "R2", "R3"]      # oldest first
    assert report["failed_dropped"] == 1
    assert report["duplicates_dropped"] == 1
    assert report["balance_mismatches"] == 0
    assert txns[1]["details"] == "Payment from 0712***345 - JOHN"
    assert txns[2]["money_out"] == 1000.0


def test_corrupted_balance_is_detected(tmp_path):
    txns, report = parse_statement(write(tmp_path, MESSY.replace('"-1,000.00",600.00',
                                                                 '"-1,000.00",700.00')))
    assert report["balance_mismatches"] == 1


@pytest.mark.parametrize("business", ["amina_grocery", "grace_salon", "otieno_transport"])
def test_generated_statements_add_up(business):
    _, report = parse_statement(DATA / f"{business}_statement.csv")
    assert report["balance_mismatches"] == 0
