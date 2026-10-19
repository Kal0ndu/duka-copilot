"""Regression tests for bugs found while building the business-6 test dataset."""
import sqlite3
from datetime import date

import pytest

from core.adapters.mobile_money_ke import MobileMoneyKeAdapter
from core.categoriser import Categoriser
from core.dates import parse_local_dates
from core.redaction import Redactor


def _cat(description, channel, direction="out"):
    return Categoriser().categorise(description=description, channel=channel, direction=direction,
                                    amount_minor=100_00).category_code


class TestCategoriserRules:
    def test_loan_repayment_word_is_matched(self):
        assert _cat("Pay Bill to 522522 - KCB LOAN REPAYMENT Acc. 1", "bill") == "LOAN_REPAYMENT"

    def test_plural_repairs_is_matched(self):
        assert _cat("Pay Bill to 222111 - QUICKFIX ELECTRICIAN REPAIRS", "bill") == "REPAIRS"

    @pytest.mark.parametrize("text", ["Pay Bill to 572572 - KRA Acc. TOT JUL",
                                      "Pay Bill to 572572 - NAIROBI CITY COUNCIL Acc. SBP PERMIT 2026",
                                      "Pay Bill to 1 - TRADING LICENCE"])
    def test_tax_and_licences_beat_the_paybill_fallback(self, text):
        assert _cat(text, "bill") == "LICENSE_TAX"

    def test_other_paybills_are_still_utilities(self):
        assert _cat("Pay Bill to 150501 - ZUKU FIBER Acc. 9", "bill") == "UTILITIES"

    def test_own_transfer_and_savings(self):
        assert _cat("Transfer from Bank - EQUITY BANK KENYA", "deposit", "in") == "OWN_TRANSFER"
        assert _cat("M-Shwari Deposit", "deposit") == "SAVINGS_DEPOSIT"


class TestChannelInference:
    infer = staticmethod(MobileMoneyKeAdapter._infer_channel)

    @pytest.mark.parametrize("name", ["SENDI WANJIRU", "TILLY ACHIENG", "BILLY OTIENO", "AGENT SMITH"])
    def test_payer_name_does_not_change_the_channel(self, name):
        assert self.infer(f"Payment from 0711***001 - {name}") == "receive"

    def test_agent_withdrawal_is_not_a_till_sale(self):
        assert self.infer("Withdrawal at Agent Till 112233 - JUJA AGENCIES") == "withdraw"

    def test_existing_phrases_unchanged(self):
        assert self.infer("Merchant Payment to 123456 - SHOP") == "till"
        assert self.infer("Customer Payment to Small Business to 07** - X") == "send"
        assert self.infer("Transfer from Bank") == "deposit"
        assert self.infer("Overdraft Repayment") == "overdraft"


def test_payment_instruction_with_phone_number_is_flagged():
    flags = Redactor().redact("Customer Transfer to 0722***012 - EXECUTE PAYMENT TO 0700000000").injection_flags
    assert "PAYMENT_INSTRUCTION" in flags


def test_iso_dates_are_never_read_day_first():
    parsed = parse_local_dates(["2026-09-12", "2026-10-17", "15/10/2026"])
    assert [d.date() for d in parsed] == [date(2026, 9, 12), date(2026, 10, 17), date(2026, 10, 15)]


def test_relationship_reference_date_is_the_latest_iso_date():
    from core.relationship_analyzer import RelationshipAnalyzer
    rows = [{"counterparty": "A", "local_date": "2026-09-12", "amount_minor": 100, "direction": "in"},
            {"counterparty": "B", "local_date": "2026-10-17", "amount_minor": 100, "direction": "in"}]
    a = {p.party_name: p for p in RelationshipAnalyzer(rows).analyze_parties()}
    assert a["B"].days_since_interaction == 0
    assert a["A"].days_since_interaction == 35


def test_own_transfers_are_not_customers():
    from core.relationship_analyzer import RelationshipAnalyzer
    rows = [{"counterparty": "EQUITY BANK", "local_date": "2026-10-01", "amount_minor": 1000, "direction": "in",
             "category_kind": "transfer"},
            {"counterparty": "SHOPPER", "local_date": "2026-10-01", "amount_minor": 100, "direction": "in",
             "category_kind": "income"}]
    customers = RelationshipAnalyzer(rows).get_customers()
    assert [c.party_name for c in customers] == ["SHOPPER"]
    assert customers[0].concentration_pct == 100.0


# ---- invoicing ----

@pytest.fixture
def biz_db(tmp_path):
    import contextlib
    import io
    from core.business_setup import BusinessSetup
    from db.migrate import MigrationRunner
    db = str(tmp_path / "duka.db")
    with contextlib.redirect_stdout(io.StringIO()):
        MigrationRunner(db).run_pending()
    with sqlite3.connect(db) as conn:
        uid = conn.execute("INSERT INTO app_user (phone_hash, display_name, display_token) VALUES ('h', 'o', 'T')").lastrowid
    return db, BusinessSetup(db).register_business("myplan", "services", owner_user_id=uid)


def _line(subtotal, vat=0):
    from core.invoice_manager import InvoiceLineItem
    return InvoiceLineItem(description="x", quantity=1, unit_price_minor=subtotal, line_subtotal_minor=subtotal,
                           vat_amount_minor=vat, line_total_minor=subtotal + vat)


class TestInvoicing:
    def test_typed_customer_becomes_a_party_and_numbers_never_repeat(self, biz_db):
        from core.invoice_manager import InvoiceManager
        db, biz = biz_db
        mgr = InvoiceManager(db)   # no pos_setting row for this business
        a = mgr.create_invoice(biz, 0, [_line(1000)], customer_name_token="Acme Ltd", status="sent")
        b = mgr.create_invoice(biz, 0, [_line(2000)], customer_name_token="  acme   ltd ", status="sent")
        assert a.invoice_number != b.invoice_number
        ids = {mgr.get_invoice(i.invoice_id).customer_id for i in (a, b)}
        assert len(ids) == 1 and 0 not in ids   # one real party for "Acme Ltd"

    def test_invoice_date_and_due_date_follow_the_form(self, biz_db):
        from core.invoice_manager import InvoiceManager
        db, biz = biz_db
        inv = InvoiceManager(db).create_invoice(biz, 0, [_line(1000)], customer_name_token="X", due_days=14,
                                                status="sent", invoice_date=date(2026, 10, 1))
        assert (inv.invoice_date[:10], inv.due_date[:10]) == ("2026-10-01", "2026-10-15")

    def test_sent_and_partly_paid_invoices_are_outstanding(self, biz_db):
        from core.invoice_manager import InvoiceManager
        db, biz = biz_db
        mgr = InvoiceManager(db)
        sent = mgr.create_invoice(biz, 0, [_line(10_000)], customer_name_token="A", status="sent")
        mgr.create_invoice(biz, 0, [_line(5_000)], customer_name_token="B", status="draft")
        assert mgr.record_payment(biz, sent.invoice_id, 4_000)
        outstanding = mgr.get_outstanding_invoices(biz)
        assert [(i.invoice_id, i.payment_status, i.balance_due_minor) for i in outstanding] == [
            (sent.invoice_id, "partial", 6_000)]
        assert mgr.get_invoice_summary(biz)["total_outstanding_minor"] == 6_000
        assert [p["invoice_number"] for p in mgr.get_recent_payments(biz)] == [sent.invoice_number]

    def test_payment_rules(self, biz_db):
        from core.invoice_manager import InvoiceManager
        db, biz = biz_db
        mgr = InvoiceManager(db)
        draft = mgr.create_invoice(biz, 0, [_line(1000)], customer_name_token="A", status="draft")
        sent = mgr.create_invoice(biz, 0, [_line(1000)], customer_name_token="A", status="sent")
        assert not mgr.record_payment(biz, draft.invoice_id, 500)       # drafts aren't owed
        assert not mgr.record_payment(biz, sent.invoice_id, 0)          # nothing to record
        assert not mgr.record_payment(biz + 1, sent.invoice_id, 500)    # another business
        assert mgr.record_payment(biz, sent.invoice_id, 1000)
        assert not mgr.record_payment(biz, sent.invoice_id, 1)          # already paid

    def test_draft_quotation_converts(self, biz_db):
        from core.invoice_manager import InvoiceManager, QuotationLineItem
        db, biz = biz_db
        mgr = InvoiceManager(db)
        q = mgr.create_quotation(biz, 0, [QuotationLineItem(description="x", quantity=1, unit_price_minor=100,
                                                            line_subtotal_minor=100, line_total_minor=100)],
                                 customer_name_token="Q")
        inv = mgr.convert_quotation_to_invoice(q.quotation_id)
        assert inv is not None and inv.total_amount_minor == 100
        assert mgr.convert_quotation_to_invoice(q.quotation_id) is None    # not twice


def test_credit_sale_is_owed_not_paid(biz_db):
    from core.pos_engine import POSEngine
    db, biz = biz_db
    pos = POSEngine(db)
    with sqlite3.connect(db) as conn:
        pid = conn.execute("INSERT INTO product (business_id, sku, name, cost_price_minor, selling_price_minor, "
                           "current_stock_qty) VALUES (?, 'S', 'n', 1, 100, 5)", (biz,)).lastrowid
    sale = pos.create_sale(biz, [POSEngine.build_line_item(pid, 1, 100)], payment_method="credit")
    assert (sale.amount_paid_minor, sale.payment_status) == (0, "pending")


def test_taught_category_only_applies_to_that_direction(biz_db):
    from core.categoriser import teach_category
    from core.ingestion import StatementIngestor
    db, biz = biz_db
    csv = ("Receipt No.,Completion Time,Details,Transaction Status,Paid In,Withdrawn,Balance\n"
           "R3,2026-10-03 10:00:00,Customer Transfer to 0711***001 - ACME LTD,Completed,,-200.00,800.00\n"
           "R2,2026-10-02 10:00:00,Payment from 0711***001 - ACME LTD,Completed,500.00,,1000.00\n"
           "R1,2026-10-01 10:00:00,Payment from 0711***001 - ACME LTD,Completed,500.00,,500.00\n")
    StatementIngestor(db).ingest(csv.encode(), "s.csv", biz)
    with sqlite3.connect(db) as conn:
        refund = conn.execute("SELECT txn_id FROM transaction_ledger WHERE reference = 'R3'").fetchone()[0]
    result = teach_category(db, biz, refund, "OTHER_OPEX")
    assert result["updated"] == 1
    with sqlite3.connect(db) as conn:
        cats = dict(conn.execute("SELECT t.reference, c.code FROM transaction_ledger t JOIN category c "
                                 "USING (category_id)").fetchall())
    assert cats == {"R1": "SALES_TRANSFER", "R2": "SALES_TRANSFER", "R3": "OTHER_OPEX"}
