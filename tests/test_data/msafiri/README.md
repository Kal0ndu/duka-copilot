# Test dataset: business 6 ("myplan", owner Msafiri, 0702122031)

A small internet-service business, 1 Jul – 17 Oct 2026: home and business
plans, hotspot vouchers, installations and network hardware. Every file is
written by `generate.py` from a fixed seed, so regenerating gives identical
bytes. Money is KES.

| File | Load it in | What it covers |
|---|---|---|
| `products.csv` | Invoicing → Import CSV → Products | 24 products: plans, vouchers, services, hardware; VAT-exempt items, 0-cost items, prices like 19.99 / 3999.99, zero stock, stock at the reorder level |
| `customers.csv` | Invoicing → Import CSV → Customers | 55 customers: 25 loyal monthly subscribers, 5 who stopped in August, 4 new in October, 6 business accounts, 15 hardware buyers; phones in 4 formats |
| `sales.csv` | Invoicing → Import CSV → Past sales | 612 sales / 661 lines: subscriptions, credit bills, daily vouchers, multi-line hardware sales with 5–12.5% discounts and a negotiated price |
| `statement_combined.csv` | Upload Statement | The M-Pesa wallet, money in and out, one running balance (670 rows) |
| `statement_income.csv`, `statement_expenses.csv` | Upload Statement | The same receipts split in two. After the combined file they must load **0 new rows** (duplicate detection) |
| `statement_edge_cases.csv` | Upload Statement | 25 parser edge cases: date formats, Failed/Pending/Reversed rows, zero and 1-cent amounts, thousands separators, duplicate receipt, prompt injection, non-ASCII names |
| `statement_malformed.csv` | Upload Statement | Wrong columns: must be rejected |
| `*_edge_cases.csv` (products, customers, sales) | Invoicing → Import CSV | Rows that must be rejected, each with the expected reason |

Scenarios in the statement: fixed monthly rent (paybill, 7th), three staff paid by
person-to-person transfer (1st/5th/6th), variable electricity and water, weekly
bandwidth (cost of sales), irregular hardware restocks, KRA turnover tax, a
business permit, loan repayments, Fuliza overdraft draws and repayments,
charges on each paybill/transfer, airtime, fuel, boda deliveries, family support,
agent withdrawals, school fees, an M-Shwari deposit, a bank top-up, a reversal,
and a refund to a customer. Kilimani Towers is >20% of revenue (concentration
risk); Liquid Bandwidth is >20% of spending (supplier dependency).

## Answer keys

* `expected_statement_rows.csv`: one row per receipt with the **intended**
  category (the true economics) and the **expected app** category and review flag
  (what Duka's rules are specified to give, e.g. salaries paid person-to-person
  land in *Family transfer* for review until the owner teaches the payee).
* `expected_import_errors.csv`: line-by-line outcome of the edge-case imports.
* `expected_summary.json`: totals, KPIs before and after teaching, detected
  obligations (as of 2026-10-19), recurring-expense patterns, party
  intelligence, stock after import, VAT by month.

These are written from the scenario design, not by running Duka; a difference
is a finding.

## Manual testing in the app

1. Log in as Msafiri. On **Upload Statement**, remove the two statements already
   saved, so only this dataset is in the ledger (otherwise the analytics include
   the older data and won't match the key).
2. Upload `statement_combined.csv`, then `statement_income.csv` and
   `statement_expenses.csv` (expect "Loaded 0 of …").
3. Import in this order: products → customers → sales. Sales reduce stock, so
   products must exist first. Importing a file twice adds nothing.
4. Compare the pages against `expected_summary.json`.

Obligation due dates and "days since" depend on the run date; the key uses
2026-10-19. Statement rows older than 180 days stop counting toward detected
obligations, so after about 28 Dec 2026 regenerate with later dates.

## Automated

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/e2e/test_msafiri_dataset.py

builds a fresh database, loads everything through the real ingestor and
importers, checks every answer key, and builds it a second time to confirm the
output is identical.

    .venv/bin/python tests/test_data/msafiri/generate.py [output_dir]

regenerates the files.
