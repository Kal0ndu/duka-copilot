from datetime import date

from analytics import date_range, overdraft_owed_by_day, summarise, true_positions

D0 = date(2026, 10, 1)


def row(day, category, money_in=0.0, money_out=0.0, balance=0.0):
    return {"date": date(2026, 10, day), "Category": category, "in": money_in,
            "out": money_out, "balance": balance, "Confidence": "high"}


def test_date_range_includes_both_ends():
    days = date_range(D0, date(2026, 10, 3))
    assert days == [D0, date(2026, 10, 2), date(2026, 10, 3)]


def test_overdraft_owed_with_fees_and_repayment():
    rows = [row(1, "overdraft_drawdown", money_in=1000, balance=1000),
            row(3, "overdraft_repayment", money_out=1020, balance=0)]
    owed = overdraft_owed_by_day(rows, date_range(D0, date(2026, 10, 3)))
    assert owed[D0] == 1010                       # 1% when drawn
    assert owed[date(2026, 10, 2)] == 1015        # + 0.5% a day still pending
    assert owed[date(2026, 10, 3)] == 0           # 1010 + 10 fees, repaid 1020


def test_true_position_is_balance_minus_owed():
    rows = [row(1, "overdraft_drawdown", money_in=1000, balance=1000)]
    assert true_positions(rows, [D0])[D0] == 1000 - 1010


def test_amina_summary_is_consistent(amina_rows):
    s = summarise(amina_rows)
    sales = sum(r["in"] for r in amina_rows if r["Category"] == "sales")
    assert s["sales"]["total"] == round(sales, 2)
    assert s["profit"] == round(s["sales"]["total"] - s["costs"]["total"], 2)
    assert s["cash"]["true_position"] == s["cash"]["closing_balance"] - s["cash"]["overdraft_owed"]
    c = s["credit"]
    assert c["overdraft_fees"] == round(c["overdraft_repaid"] + c["overdraft_owed"]
                                        - c["overdraft_borrowed"], 2)
    assert "Sun" in s["sales"]["slow_weekdays"]


def test_amina_headline_figures(amina_rows):
    """Regression values from the fixed-seed synthetic data (see the docs)."""
    s = summarise(amina_rows)
    assert s["cash"]["overdraft_owed"] == 37_967
    assert s["credit"]["overdraft_fees"] == 9_114
