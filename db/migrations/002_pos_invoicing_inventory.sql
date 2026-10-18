-- =====================================================================
-- Migration 002: POS, Invoicing, Inventory & Sales Tracking
-- Date: 2026-10-18
-- Description: Add POS, product, inventory, sales, invoicing,
--              quotation, payment, tax, and AI follow-up tables
-- =====================================================================

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS pos_setting (
  setting_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL UNIQUE REFERENCES business(business_id),
  pos_enabled INTEGER NOT NULL DEFAULT 0 CHECK (pos_enabled IN (0,1)),
  default_vat_pct REAL NOT NULL DEFAULT 16.0,
  invoice_prefix TEXT NOT NULL DEFAULT 'INV',
  quotation_prefix TEXT NOT NULL DEFAULT 'QT',
  invoice_sequence INTEGER NOT NULL DEFAULT 1000,
  quotation_sequence INTEGER NOT NULL DEFAULT 1000,
  receipt_printer_name TEXT,
  currency TEXT NOT NULL DEFAULT 'KES',
  business_name TEXT,
  business_address TEXT,
  business_phone TEXT,
  business_pin TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS product (
  product_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  sku TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  category TEXT,
  cost_price_minor INTEGER NOT NULL,
  selling_price_minor INTEGER NOT NULL,
  vat_applicable INTEGER NOT NULL DEFAULT 1 CHECK (vat_applicable IN (0,1)),
  vat_rate_pct REAL NOT NULL DEFAULT 16.0,
  current_stock_qty INTEGER NOT NULL DEFAULT 0,
  reorder_level_qty INTEGER NOT NULL DEFAULT 10,
  reorder_qty INTEGER NOT NULL DEFAULT 50,
  supplier_id INTEGER REFERENCES party(party_id),
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  barcode TEXT UNIQUE,
  image_url TEXT,
  last_restocked_at TEXT,
  margin_pct REAL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  UNIQUE (business_id, sku)
);
CREATE INDEX IF NOT EXISTS ix_product_business ON product(business_id);
CREATE INDEX IF NOT EXISTS ix_product_category ON product(business_id, category);
CREATE INDEX IF NOT EXISTS ix_product_low_stock ON product(business_id, current_stock_qty) WHERE current_stock_qty < reorder_level_qty;

CREATE TABLE IF NOT EXISTS inventory_transaction (
  txn_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  product_id INTEGER NOT NULL REFERENCES product(product_id),
  type TEXT NOT NULL CHECK (type IN ('purchase','sale','adjustment','return','damaged','loss')),
  quantity INTEGER NOT NULL,
  reference_id INTEGER,
  reference_type TEXT,
  notes TEXT,
  recorded_by TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_inv_txn_product ON inventory_transaction(product_id, created_at);

CREATE TABLE IF NOT EXISTS sale (
  sale_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  sale_number TEXT NOT NULL UNIQUE,
  sale_date TEXT NOT NULL,
  customer_id INTEGER REFERENCES party(party_id),
  customer_name_token TEXT,
  subtotal_minor INTEGER NOT NULL CHECK (subtotal_minor >= 0),
  vat_amount_minor INTEGER NOT NULL DEFAULT 0,
  total_amount_minor INTEGER NOT NULL CHECK (total_amount_minor >= 0),
  amount_paid_minor INTEGER NOT NULL DEFAULT 0,
  change_due_minor INTEGER NOT NULL DEFAULT 0,
  payment_method TEXT NOT NULL CHECK (payment_method IN ('cash','m_pesa','card','cheque','credit')),
  payment_status TEXT NOT NULL DEFAULT 'completed' CHECK (payment_status IN ('pending','partial','completed','refunded')),
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('completed','cancelled','refunded')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  created_by_user TEXT
);
CREATE INDEX IF NOT EXISTS ix_sale_date ON sale(business_id, sale_date);

CREATE TABLE IF NOT EXISTS sale_line_item (
  line_id INTEGER PRIMARY KEY,
  sale_id INTEGER NOT NULL REFERENCES sale(sale_id),
  product_id INTEGER NOT NULL REFERENCES product(product_id),
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price_minor INTEGER NOT NULL,
  line_subtotal_minor INTEGER NOT NULL,
  vat_applicable INTEGER NOT NULL CHECK (vat_applicable IN (0,1)),
  vat_rate_pct REAL NOT NULL,
  vat_amount_minor INTEGER NOT NULL DEFAULT 0,
  line_total_minor INTEGER NOT NULL,
  discount_pct REAL,
  discount_amount_minor INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_sli_sale ON sale_line_item(sale_id);

CREATE TABLE IF NOT EXISTS invoice (
  invoice_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  invoice_number TEXT NOT NULL UNIQUE,
  invoice_date TEXT NOT NULL,
  due_date TEXT NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES party(party_id),
  customer_name_token TEXT,
  customer_contact TEXT,
  subtotal_minor INTEGER NOT NULL,
  vat_amount_minor INTEGER NOT NULL,
  total_amount_minor INTEGER NOT NULL,
  amount_paid_minor INTEGER NOT NULL DEFAULT 0,
  balance_due_minor INTEGER NOT NULL,
  payment_status TEXT NOT NULL DEFAULT 'unpaid' CHECK (payment_status IN ('unpaid','partial','overdue','paid','cancelled')),
  last_payment_date TEXT,
  follow_up_status TEXT DEFAULT 'none' CHECK (follow_up_status IN ('none','reminder_sent','contacted','payment_promised','payment_received')),
  follow_up_count INTEGER NOT NULL DEFAULT 0,
  last_follow_up_date TEXT,
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','sent','overdue','paid','cancelled')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  created_by TEXT
);
CREATE INDEX IF NOT EXISTS ix_invoice_business_status ON invoice(business_id, payment_status);
CREATE INDEX IF NOT EXISTS ix_invoice_customer ON invoice(customer_id);
CREATE INDEX IF NOT EXISTS ix_invoice_due ON invoice(business_id, due_date) WHERE payment_status != 'paid';

CREATE TABLE IF NOT EXISTS invoice_line_item (
  line_id INTEGER PRIMARY KEY,
  invoice_id INTEGER NOT NULL REFERENCES invoice(invoice_id),
  product_id INTEGER REFERENCES product(product_id),
  description TEXT NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price_minor INTEGER NOT NULL,
  line_subtotal_minor INTEGER NOT NULL,
  vat_applicable INTEGER NOT NULL CHECK (vat_applicable IN (0,1)),
  vat_rate_pct REAL NOT NULL,
  vat_amount_minor INTEGER NOT NULL DEFAULT 0,
  line_total_minor INTEGER NOT NULL,
  discount_pct REAL,
  discount_amount_minor INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_ili_invoice ON invoice_line_item(invoice_id);

CREATE TABLE IF NOT EXISTS quotation (
  quotation_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  quotation_number TEXT NOT NULL UNIQUE,
  quotation_date TEXT NOT NULL,
  valid_until_date TEXT NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES party(party_id),
  customer_name_token TEXT,
  subtotal_minor INTEGER NOT NULL,
  vat_amount_minor INTEGER NOT NULL,
  total_minor INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','accepted','rejected','expired','converted_to_invoice')),
  converted_to_invoice_id INTEGER REFERENCES invoice(invoice_id),
  notes TEXT,
  terms TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  created_by TEXT
);
CREATE INDEX IF NOT EXISTS ix_quotation_status ON quotation(business_id, status);

CREATE TABLE IF NOT EXISTS quotation_line_item (
  line_id INTEGER PRIMARY KEY,
  quotation_id INTEGER NOT NULL REFERENCES quotation(quotation_id),
  product_id INTEGER REFERENCES product(product_id),
  description TEXT NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price_minor INTEGER NOT NULL,
  line_subtotal_minor INTEGER NOT NULL,
  vat_applicable INTEGER NOT NULL CHECK (vat_applicable IN (0,1)),
  vat_rate_pct REAL NOT NULL,
  vat_amount_minor INTEGER NOT NULL DEFAULT 0,
  line_total_minor INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_qli_quotation ON quotation_line_item(quotation_id);

CREATE TABLE IF NOT EXISTS payment_record (
  payment_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  payment_date TEXT NOT NULL,
  reference_number TEXT UNIQUE,
  invoice_id INTEGER REFERENCES invoice(invoice_id),
  sale_id INTEGER REFERENCES sale(sale_id),
  customer_id INTEGER NOT NULL REFERENCES party(party_id),
  amount_minor INTEGER NOT NULL,
  payment_method TEXT NOT NULL CHECK (payment_method IN ('cash','m_pesa','bank_transfer','cheque','card','other')),
  mpesa_reference TEXT,
  notes TEXT,
  recorded_by TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_payment_invoice ON payment_record(invoice_id);
CREATE INDEX IF NOT EXISTS ix_payment_date ON payment_record(business_id, payment_date);

CREATE TABLE IF NOT EXISTS tax_summary (
  summary_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  period_month TEXT NOT NULL,
  total_sales_with_vat_minor INTEGER NOT NULL DEFAULT 0,
  total_vat_collected_minor INTEGER NOT NULL DEFAULT 0,
  total_purchases_with_vat_minor INTEGER NOT NULL DEFAULT 0,
  total_vat_paid_minor INTEGER NOT NULL DEFAULT 0,
  net_vat_payable_minor INTEGER NOT NULL DEFAULT 0,
  total_withholding_tax_minor INTEGER NOT NULL DEFAULT 0,
  total_taxable_revenue_minor INTEGER NOT NULL DEFAULT 0,
  total_allowed_deductions_minor INTEGER NOT NULL DEFAULT 0,
  taxable_income_minor INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','submitted','approved','paid','amended')),
  kra_acknowledgement TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_tax_period ON tax_summary(business_id, period_month);

CREATE TABLE IF NOT EXISTS ai_follow_up_task (
  task_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('invoice','quotation')),
  entity_id INTEGER NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES party(party_id),
  customer_contact_token TEXT,
  task_type TEXT NOT NULL CHECK (task_type IN ('payment_reminder','quotation_follow_up','overdue_notice','win_back')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','in_progress','completed','failed','skipped')),
  scheduled_for_date TEXT NOT NULL,
  attempted_at TEXT,
  completed_at TEXT,
  message_template TEXT,
  ai_suggested_action TEXT,
  outcome TEXT,
  outcome_recorded_by TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_followup_pending ON ai_follow_up_task(business_id, status, scheduled_for_date);

COMMIT;
