-- =====================================================================
-- Duka Copilot: full SME data model (SQLite 3.35+, FTS5 required)
-- Module tags:  [CORE] MVP   [EXT] should-have   [OPT] nice-to-have
-- Conventions:
--   * Money is INTEGER minor units (KES cents). Never floats.
--   * System timestamps: ISO 8601 UTC.
--   * Every tenant table carries business_id (tenant isolation).
--   * Facts are immutable; corrections are new rows or void flags.
--   * Run PRAGMA foreign_keys = ON on every connection.
-- =====================================================================
PRAGMA foreign_keys = ON;

-- #### DOMAIN: Reference and configuration
CREATE TABLE currency (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  minor_unit INTEGER NOT NULL DEFAULT 2
);

CREATE TABLE platform (
  platform_id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  country_code TEXT NOT NULL,
  adapter_name TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);

CREATE TABLE permission_tier (
  tier TEXT PRIMARY KEY CHECK (tier IN ('T0','T1','T2','T3')),
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  requires_approval INTEGER NOT NULL CHECK (requires_approval IN (0,1)),
  sandbox_only INTEGER NOT NULL CHECK (sandbox_only IN (0,1))
);

CREATE TABLE tool_registry (
  tool_name TEXT PRIMARY KEY,
  tier TEXT NOT NULL REFERENCES permission_tier(tier),
  description TEXT NOT NULL,
  args_schema_json TEXT,
  exposed_to_llm INTEGER NOT NULL DEFAULT 1 CHECK (exposed_to_llm IN (0,1)),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1))
);

CREATE TABLE action_transition (
  from_status TEXT NOT NULL,
  to_status TEXT NOT NULL,
  PRIMARY KEY (from_status, to_status)
);

CREATE TABLE schema_migration (
  version INTEGER PRIMARY KEY,
  description TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- #### DOMAIN: Tenancy and users
CREATE TABLE business (
  business_id INTEGER PRIMARY KEY,
  public_ref TEXT NOT NULL UNIQUE,
  name_token TEXT NOT NULL,
  sector TEXT NOT NULL CHECK (sector IN ('grocery','kiosk','salon','transport','restaurant','retail','agri','services','other')),
  sub_sector TEXT,
  country_code TEXT NOT NULL,
  currency_code TEXT NOT NULL REFERENCES currency(code),
  timezone TEXT NOT NULL DEFAULT 'Africa/Nairobi',
  registration_type TEXT NOT NULL DEFAULT 'informal' CHECK (registration_type IN ('informal','sole_proprietor','partnership','company')),
  tax_pin_token TEXT,
  start_date TEXT,
  employee_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','closed')),
  is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at TEXT
);

CREATE TABLE app_user (
  user_id INTEGER PRIMARY KEY,
  display_token TEXT NOT NULL,
  locale TEXT NOT NULL DEFAULT 'en',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE business_member (
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  user_id INTEGER NOT NULL REFERENCES app_user(user_id),
  role TEXT NOT NULL CHECK (role IN ('owner','manager','accountant','viewer')),
  PRIMARY KEY (business_id, user_id)
);

-- #### DOMAIN: Parties and payees
CREATE TABLE party (
  party_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  kind TEXT NOT NULL DEFAULT 'unknown' CHECK (kind IN ('customer','supplier','landlord','employee','lender','utility','government','family','other_business','unknown')),
  display_token TEXT NOT NULL,
  is_business_related INTEGER CHECK (is_business_related IN (0,1)),
  first_seen TEXT,
  last_seen TEXT,
  note TEXT,
  UNIQUE (business_id, display_token)
);

CREATE TABLE party_identifier (
  identifier_id INTEGER PRIMARY KEY,
  party_id INTEGER NOT NULL REFERENCES party(party_id),
  id_type TEXT NOT NULL CHECK (id_type IN ('phone_hash','till_no','paybill_no','account_no_hash','national_id_hash','email_hash')),
  value_hash TEXT NOT NULL,
  UNIQUE (party_id, id_type, value_hash)
);

CREATE TABLE payee (
  payee_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  party_id INTEGER NOT NULL REFERENCES party(party_id),
  label_token TEXT NOT NULL,
  verified INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0,1)),
  verified_by TEXT,
  verified_at TEXT,
  per_txn_cap_minor INTEGER,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE token_vault (
  token TEXT NOT NULL,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('PERSON','MERCHANT','PHONE','ID','REF','BUSINESS_NAME')),
  original_value TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  PRIMARY KEY (business_id, token)
);

-- #### DOMAIN: Accounts
CREATE TABLE financial_account (
  account_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  platform_id INTEGER REFERENCES platform(platform_id),
  kind TEXT NOT NULL CHECK (kind IN ('mobile_wallet','till','paybill','bank','cash_on_hand','sacco_savings','other')),
  label TEXT NOT NULL,
  currency_code TEXT NOT NULL REFERENCES currency(code),
  opening_balance_minor INTEGER NOT NULL DEFAULT 0,
  opening_date TEXT,
  is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
  is_sandbox INTEGER NOT NULL DEFAULT 0 CHECK (is_sandbox IN (0,1)),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','dormant','closed'))
);

CREATE TABLE balance_snapshot (
  snapshot_id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES financial_account(account_id),
  as_of TEXT NOT NULL,
  balance_minor INTEGER NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('statement','derived','owner_entered','sandbox')),
  UNIQUE (account_id, as_of, source)
);

-- #### DOMAIN: Ingestion
CREATE TABLE source_file (
  file_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  account_id INTEGER REFERENCES financial_account(account_id),
  platform_id INTEGER REFERENCES platform(platform_id),
  filename TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size_bytes INTEGER,
  media_type TEXT,
  adapter_name TEXT,
  adapter_version TEXT,
  uploaded_by INTEGER REFERENCES app_user(user_id),
  uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  period_start TEXT,
  period_end TEXT,
  row_count INTEGER,
  status TEXT NOT NULL DEFAULT 'received' CHECK (status IN ('received','parsed','validated','rejected','loaded')),
  risk_flag INTEGER NOT NULL DEFAULT 0 CHECK (risk_flag IN (0,1)),
  risk_reason TEXT,
  UNIQUE (business_id, sha256)
);

CREATE TABLE ingestion_run (
  run_id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id),
  started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  finished_at TEXT,
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','succeeded','failed')),
  rows_read INTEGER NOT NULL DEFAULT 0,
  rows_loaded INTEGER NOT NULL DEFAULT 0,
  rows_rejected INTEGER NOT NULL DEFAULT 0,
  validation_json TEXT
);

CREATE TABLE raw_statement_row (
  raw_id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id),
  row_no INTEGER NOT NULL,
  raw_json TEXT NOT NULL,
  UNIQUE (file_id, row_no)
);

CREATE TABLE injection_finding (
  finding_id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id),
  raw_id INTEGER REFERENCES raw_statement_row(raw_id),
  pattern_code TEXT NOT NULL,
  excerpt_redacted TEXT,
  detected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- #### DOMAIN: Ledger and categorisation
CREATE TABLE category (
  category_id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('income','cogs','opex','financing','personal','transfer','tax','unknown')),
  parent_id INTEGER REFERENCES category(category_id),
  is_business INTEGER NOT NULL CHECK (is_business IN (0,1)),
  sort_order INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);

CREATE TABLE categorisation_rule (
  rule_id INTEGER PRIMARY KEY,
  business_id INTEGER REFERENCES business(business_id),
  priority INTEGER NOT NULL,
  match_field TEXT NOT NULL CHECK (match_field IN ('description','counterparty','channel','amount_range','composite')),
  pattern TEXT NOT NULL,
  direction TEXT CHECK (direction IN ('in','out')),
  amount_min_minor INTEGER,
  amount_max_minor INTEGER,
  category_id INTEGER NOT NULL REFERENCES category(category_id),
  confidence REAL NOT NULL DEFAULT 0.95 CHECK (confidence BETWEEN 0 AND 1),
  created_by TEXT NOT NULL DEFAULT 'system' CHECK (created_by IN ('system','owner')),
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);

CREATE TABLE transaction_ledger (
  txn_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  account_id INTEGER NOT NULL REFERENCES financial_account(account_id),
  file_id INTEGER REFERENCES source_file(file_id),
  raw_id INTEGER REFERENCES raw_statement_row(raw_id),
  reference TEXT,
  ts TEXT NOT NULL,
  local_date TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
  fee_minor INTEGER NOT NULL DEFAULT 0 CHECK (fee_minor >= 0),
  direction TEXT NOT NULL CHECK (direction IN ('in','out')),
  balance_after_minor INTEGER,
  party_id INTEGER REFERENCES party(party_id),
  counterparty_token TEXT,
  description_redacted TEXT,
  channel TEXT NOT NULL CHECK (channel IN ('till','send','receive','withdraw','deposit','bill','airtime','overdraft','loan','fee','reversal','other')),
  category_id INTEGER REFERENCES category(category_id),
  category_source TEXT CHECK (category_source IN ('rule','llm','owner','system')),
  rule_id INTEGER REFERENCES categorisation_rule(rule_id),
  confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
  needs_review INTEGER NOT NULL DEFAULT 0 CHECK (needs_review IN (0,1)),
  source TEXT NOT NULL DEFAULT 'statement' CHECK (source IN ('statement','sandbox','owner_entered')),
  voided INTEGER NOT NULL DEFAULT 0 CHECK (voided IN (0,1)),
  void_reason TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX ux_txn_account_ref ON transaction_ledger(account_id, reference) WHERE reference IS NOT NULL;
CREATE INDEX ix_txn_biz_date ON transaction_ledger(business_id, local_date);
CREATE INDEX ix_txn_biz_cat ON transaction_ledger(business_id, category_id);
CREATE INDEX ix_txn_review ON transaction_ledger(business_id, needs_review) WHERE needs_review = 1;

-- #### DOMAIN: Obligations and planning
CREATE TABLE obligation (
  obligation_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  party_id INTEGER REFERENCES party(party_id),
  label TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('rent','loan_repayment','utility','wages','tax','school_fees','insurance','supplier_standing','savings','other')),
  amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
  amount_is_variable INTEGER NOT NULL DEFAULT 0 CHECK (amount_is_variable IN (0,1)),
  cadence TEXT NOT NULL CHECK (cadence IN ('daily','weekly','biweekly','monthly','quarterly','annual','one_off')),
  day_of_month INTEGER CHECK (day_of_month BETWEEN 1 AND 31),
  weekday INTEGER CHECK (weekday BETWEEN 0 AND 6),
  next_due TEXT,
  end_date TEXT,
  essential INTEGER NOT NULL DEFAULT 1 CHECK (essential IN (0,1)),
  source TEXT NOT NULL CHECK (source IN ('detected','owner')),
  confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);
CREATE INDEX ix_obl_due ON obligation(business_id, next_due) WHERE active = 1;

CREATE TABLE obligation_instance (
  instance_id INTEGER PRIMARY KEY,
  obligation_id INTEGER NOT NULL REFERENCES obligation(obligation_id),
  due_date TEXT NOT NULL,
  expected_minor INTEGER NOT NULL,
  matched_txn_id INTEGER REFERENCES transaction_ledger(txn_id),
  status TEXT NOT NULL DEFAULT 'expected' CHECK (status IN ('expected','paid','late','missed','skipped')),
  UNIQUE (obligation_id, due_date)
);

-- #### DOMAIN: Analytics, forecasting and alerts
CREATE TABLE metric_snapshot (
  snapshot_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  period_type TEXT NOT NULL CHECK (period_type IN ('day','week','month','quarter','custom')),
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  calc_version TEXT NOT NULL,
  computed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  revenue_minor INTEGER NOT NULL,
  cogs_minor INTEGER NOT NULL,
  opex_minor INTEGER NOT NULL,
  financing_cost_minor INTEGER NOT NULL DEFAULT 0,
  personal_outflow_minor INTEGER NOT NULL DEFAULT 0,
  operating_cashflow_minor INTEGER NOT NULL,
  personal_mix_bp INTEGER,
  txn_count INTEGER NOT NULL,
  best_day TEXT,
  worst_day TEXT,
  details_json TEXT,
  UNIQUE (business_id, period_type, period_start, period_end, calc_version)
);

CREATE TABLE weekday_factor (
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  computed_at TEXT NOT NULL,
  weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
  inflow_factor REAL NOT NULL,
  outflow_factor REAL NOT NULL,
  window_weeks INTEGER NOT NULL,
  PRIMARY KEY (business_id, computed_at, weekday)
);

CREATE TABLE forecast_run (
  run_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  parent_run_id INTEGER REFERENCES forecast_run(run_id),
  scenario_label TEXT,
  scenario_json TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  as_of_date TEXT NOT NULL,
  horizon_days INTEGER NOT NULL CHECK (horizon_days BETWEEN 1 AND 90),
  method TEXT NOT NULL CHECK (method IN ('weekday_bootstrap','holt_winters')),
  params_json TEXT,
  seed INTEGER,
  n_paths INTEGER,
  opening_balance_minor INTEGER NOT NULL,
  buffer_minor INTEGER NOT NULL,
  data_start TEXT,
  data_end TEXT,
  calc_version TEXT NOT NULL
);

CREATE TABLE forecast_point (
  run_id INTEGER NOT NULL REFERENCES forecast_run(run_id),
  day_offset INTEGER NOT NULL,
  date TEXT NOT NULL,
  expected_minor INTEGER NOT NULL,
  p10_minor INTEGER NOT NULL,
  p50_minor INTEGER NOT NULL,
  p90_minor INTEGER NOT NULL,
  inflow_expected_minor INTEGER,
  outflow_expected_minor INTEGER,
  obligations_minor INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, day_offset)
);

CREATE TABLE alert (
  alert_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  run_id INTEGER REFERENCES forecast_run(run_id),
  kind TEXT NOT NULL CHECK (kind IN ('shortfall','high_personal_mix','overdue_receivable','unusual_spend','loan_due','data_quality')),
  severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
  first_date TEXT,
  gap_minor INTEGER,
  probability_bp INTEGER CHECK (probability_bp BETWEEN 0 AND 10000),
  facts_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved','dismissed')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  acknowledged_at TEXT
);

CREATE TABLE alert_suggestion (
  suggestion_id INTEGER PRIMARY KEY,
  alert_id INTEGER NOT NULL REFERENCES alert(alert_id),
  kind TEXT NOT NULL CHECK (kind IN ('delay_purchase','split_purchase','finance','chase_receivable','reduce_withdrawals','other')),
  description TEXT NOT NULL,
  effect_json TEXT
);

-- #### DOMAIN: Financing
CREATE TABLE credit_product (
  product_id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL CHECK (type IN ('mobile_overdraft','mobile_microloan','sacco_loan','bank_sme_loan','supplier_credit')),
  name TEXT NOT NULL,
  repayment_style TEXT NOT NULL CHECK (repayment_style IN ('single','equal_installments','revolving')),
  min_amount_minor INTEGER NOT NULL,
  max_amount_minor INTEGER NOT NULL,
  min_term_days INTEGER NOT NULL,
  max_term_days INTEGER NOT NULL,
  eligibility_note TEXT,
  is_illustrative INTEGER NOT NULL DEFAULT 1 CHECK (is_illustrative IN (0,1)),
  version INTEGER NOT NULL DEFAULT 1,
  valid_from TEXT,
  valid_to TEXT,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);

CREATE TABLE credit_fee_component (
  component_id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES credit_product(product_id),
  kind TEXT NOT NULL CHECK (kind IN ('upfront_pct','upfront_flat','periodic_pct','periodic_flat','late_pct','tiered')),
  basis TEXT NOT NULL DEFAULT 'principal' CHECK (basis IN ('principal','outstanding','flat')),
  rate_bp INTEGER,
  flat_minor INTEGER,
  period_days INTEGER,
  tier_min_minor INTEGER,
  tier_max_minor INTEGER,
  description TEXT
);

CREATE TABLE financing_request (
  request_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  run_id INTEGER REFERENCES forecast_run(run_id),
  purpose TEXT NOT NULL CHECK (purpose IN ('stock','equipment','rent','working_capital','other')),
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  term_days INTEGER NOT NULL CHECK (term_days > 0),
  needed_by TEXT,
  via TEXT NOT NULL DEFAULT 'chat' CHECK (via IN ('chat','ui')),
  requested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE financing_offer (
  offer_id INTEGER PRIMARY KEY,
  request_id INTEGER NOT NULL REFERENCES financing_request(request_id),
  product_id INTEGER NOT NULL REFERENCES credit_product(product_id),
  principal_minor INTEGER NOT NULL,
  term_days INTEGER NOT NULL,
  net_received_minor INTEGER NOT NULL,
  total_repayment_minor INTEGER NOT NULL,
  tcc_minor INTEGER NOT NULL,
  periodic_rate REAL,
  ear REAL,
  fits_forecast INTEGER NOT NULL CHECK (fits_forecast IN (0,1)),
  min_margin_minor INTEGER,
  rank INTEGER,
  calc_version TEXT NOT NULL,
  computed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  explanation_json TEXT
);

CREATE TABLE offer_schedule_line (
  offer_id INTEGER NOT NULL REFERENCES financing_offer(offer_id),
  seq INTEGER NOT NULL,
  due_date TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('disbursement','fee','repayment')),
  PRIMARY KEY (offer_id, seq)
);

CREATE TABLE affordability_result (
  offer_id INTEGER PRIMARY KEY REFERENCES financing_offer(offer_id),
  run_id INTEGER NOT NULL REFERENCES forecast_run(run_id),
  buffer_minor INTEGER NOT NULL,
  min_p10_balance_minor INTEGER NOT NULL,
  breach_date TEXT,
  passed INTEGER NOT NULL CHECK (passed IN (0,1))
);

-- #### DOMAIN: Conversation and LLM interface
CREATE TABLE conversation (
  conversation_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  user_id INTEGER REFERENCES app_user(user_id),
  mode TEXT NOT NULL DEFAULT 'live' CHECK (mode IN ('live','mock_replay')),
  title TEXT,
  started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  ended_at TEXT
);

CREATE TABLE message (
  message_id INTEGER PRIMARY KEY,
  conversation_id INTEGER NOT NULL REFERENCES conversation(conversation_id),
  seq INTEGER NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user','assistant','tool','system')),
  content_redacted TEXT NOT NULL,
  numbers_verified INTEGER CHECK (numbers_verified IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  UNIQUE (conversation_id, seq)
);

CREATE TABLE guard_decision (
  decision_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  conversation_id INTEGER REFERENCES conversation(conversation_id),
  tool_name TEXT NOT NULL,
  tier TEXT,
  decision TEXT NOT NULL CHECK (decision IN ('allow','block')),
  reason_code TEXT,
  args_hash TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE tool_call (
  call_id INTEGER PRIMARY KEY,
  conversation_id INTEGER NOT NULL REFERENCES conversation(conversation_id),
  message_id INTEGER REFERENCES message(message_id),
  tool_name TEXT NOT NULL REFERENCES tool_registry(tool_name),
  args_json TEXT NOT NULL,
  guard_decision_id INTEGER REFERENCES guard_decision(decision_id),
  status TEXT NOT NULL CHECK (status IN ('ok','error','blocked')),
  result_json TEXT,
  error TEXT,
  started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  finished_at TEXT
);

CREATE TABLE llm_request_log (
  request_id INTEGER PRIMARY KEY,
  conversation_id INTEGER REFERENCES conversation(conversation_id),
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  purpose TEXT NOT NULL CHECK (purpose IN ('orchestration','categorisation','explanation','drafting')),
  payload_hash TEXT NOT NULL,
  outbound_scan_passed INTEGER NOT NULL CHECK (outbound_scan_passed IN (0,1)),
  cache_hit INTEGER NOT NULL DEFAULT 0 CHECK (cache_hit IN (0,1)),
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  latency_ms INTEGER,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- #### DOMAIN: Actions, approvals and sandbox
CREATE TABLE policy (
  policy_id INTEGER PRIMARY KEY,
  business_id INTEGER REFERENCES business(business_id),
  version INTEGER NOT NULL,
  per_txn_cap_minor INTEGER NOT NULL CHECK (per_txn_cap_minor > 0),
  daily_cap_minor INTEGER NOT NULL CHECK (daily_cap_minor > 0),
  approval_ttl_minutes INTEGER NOT NULL DEFAULT 15,
  rate_limit_per_min INTEGER NOT NULL DEFAULT 30,
  sandbox_only INTEGER NOT NULL DEFAULT 1 CHECK (sandbox_only = 1),
  changed_by TEXT NOT NULL,
  effective_from TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  UNIQUE (business_id, version)
);

CREATE TABLE proposed_action (
  action_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  conversation_id INTEGER REFERENCES conversation(conversation_id),
  kind TEXT NOT NULL CHECK (kind IN ('supplier_payment','loan_request')),
  payee_id INTEGER REFERENCES payee(payee_id),
  offer_id INTEGER REFERENCES financing_offer(offer_id),
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  currency_code TEXT NOT NULL REFERENCES currency(code),
  scheduled_for TEXT,
  payload_json TEXT,
  status TEXT NOT NULL DEFAULT 'PROPOSED' CHECK (status IN ('PROPOSED','PENDING_APPROVAL','APPROVED','EXECUTED','REJECTED','EXPIRED','BLOCKED')),
  guard_decision_id INTEGER REFERENCES guard_decision(decision_id),
  created_by TEXT NOT NULL DEFAULT 'agent' CHECK (created_by IN ('agent','owner_ui')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  expires_at TEXT NOT NULL,
  CHECK (kind <> 'supplier_payment' OR payee_id IS NOT NULL),
  CHECK (kind <> 'loan_request' OR offer_id IS NOT NULL)
);
CREATE INDEX ix_action_biz_status ON proposed_action(business_id, status);

CREATE TABLE approval (
  approval_id INTEGER PRIMARY KEY,
  action_id INTEGER NOT NULL UNIQUE REFERENCES proposed_action(action_id),
  decision TEXT NOT NULL CHECK (decision IN ('confirmed','rejected')),
  decided_by_user_id INTEGER REFERENCES app_user(user_id),
  ui_session_id TEXT NOT NULL,
  nonce TEXT NOT NULL UNIQUE,
  decided_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  nonce_used_at TEXT
);

CREATE TABLE sandbox_account (
  sandbox_account_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  account_id INTEGER REFERENCES financial_account(account_id),
  balance_minor INTEGER NOT NULL
);

CREATE TABLE sandbox_txn (
  sbx_id INTEGER PRIMARY KEY,
  action_id INTEGER NOT NULL UNIQUE REFERENCES proposed_action(action_id),
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  sandbox_account_id INTEGER NOT NULL REFERENCES sandbox_account(sandbox_account_id),
  kind TEXT NOT NULL CHECK (kind IN ('payment','loan_disbursement','loan_repayment')),
  payee_id INTEGER REFERENCES payee(payee_id),
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  executed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  receipt_ref TEXT NOT NULL UNIQUE,
  result TEXT NOT NULL CHECK (result IN ('success','failed')),
  balance_after_minor INTEGER
);

CREATE TABLE mock_lender_decision (
  decision_id INTEGER PRIMARY KEY,
  action_id INTEGER NOT NULL UNIQUE REFERENCES proposed_action(action_id),
  decision TEXT NOT NULL CHECK (decision IN ('approved','declined')),
  reference TEXT NOT NULL,
  reason TEXT,
  decided_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- #### DOMAIN: Knowledge base (RAG)
CREATE TABLE kb_document (
  doc_id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  doc_type TEXT NOT NULL CHECK (doc_type IN ('product_sheet','glossary','notice','faq','policy')),
  version INTEGER NOT NULL DEFAULT 1,
  source TEXT,
  content_hash TEXT,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);

CREATE TABLE kb_chunk (
  chunk_id INTEGER PRIMARY KEY,
  doc_id INTEGER NOT NULL REFERENCES kb_document(doc_id),
  chunk_no INTEGER NOT NULL,
  text TEXT NOT NULL,
  token_count INTEGER,
  meta_json TEXT,
  embedding BLOB,
  UNIQUE (doc_id, chunk_no)
);
CREATE VIRTUAL TABLE kb_chunk_fts USING fts5(text, content='kb_chunk', content_rowid='chunk_id');

-- #### DOMAIN: Security, audit and evidence
CREATE TABLE audit_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  business_id INTEGER,
  actor TEXT NOT NULL CHECK (actor IN ('agent','owner','guard','system')),
  event_type TEXT NOT NULL,
  tool TEXT,
  tier TEXT,
  decision TEXT,
  entity_type TEXT,
  entity_id INTEGER,
  details_json TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL
);

CREATE TABLE security_event (
  event_id INTEGER PRIMARY KEY,
  business_id INTEGER REFERENCES business(business_id),
  conversation_id INTEGER REFERENCES conversation(conversation_id),
  kind TEXT NOT NULL CHECK (kind IN ('injection_detected','cap_exceeded','forbidden_action','unverified_payee','redaction_block','approval_missing','rate_limited','audit_tamper')),
  severity TEXT NOT NULL CHECK (severity IN ('low','medium','high')),
  details_json TEXT,
  audit_seq INTEGER REFERENCES audit_log(seq),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE audit_checkpoint (
  checkpoint_id INTEGER PRIMARY KEY,
  seq INTEGER NOT NULL,
  hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE evidence_artifact (
  artifact_id INTEGER PRIMARY KEY,
  scenario TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('audit_export','sandbox_receipts','payload_capture','pytest_output','screenshot','video','report')),
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- #### DOMAIN: Synthetic data and ground truth
CREATE TABLE synthetic_run (
  run_id INTEGER PRIMARY KEY,
  persona TEXT NOT NULL CHECK (persona IN ('grocery','salon','transport','malicious')),
  seed INTEGER NOT NULL,
  generator_version TEXT NOT NULL,
  params_json TEXT,
  generated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE synthetic_ground_truth (
  run_id INTEGER NOT NULL REFERENCES synthetic_run(run_id),
  reference TEXT NOT NULL,
  true_category_code TEXT NOT NULL,
  PRIMARY KEY (run_id, reference)
);

-- =====================================================================
-- INTEGRITY TRIGGERS
-- =====================================================================
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER audit_chain_continuity BEFORE INSERT ON audit_log
BEGIN
  SELECT RAISE(ABORT, 'audit_log: prev_hash does not match chain head')
  WHERE NEW.prev_hash <> COALESCE((SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1), 'GENESIS');
END;

CREATE TRIGGER raw_no_update BEFORE UPDATE ON raw_statement_row
BEGIN SELECT RAISE(ABORT, 'raw_statement_row is immutable'); END;
CREATE TRIGGER raw_no_delete BEFORE DELETE ON raw_statement_row
BEGIN SELECT RAISE(ABORT, 'raw_statement_row is immutable'); END;

CREATE TRIGGER ledger_financial_immutable BEFORE UPDATE ON transaction_ledger
WHEN NEW.amount_minor <> OLD.amount_minor OR NEW.direction <> OLD.direction OR NEW.ts <> OLD.ts
  OR NEW.account_id <> OLD.account_id OR NEW.reference IS NOT OLD.reference OR NEW.fee_minor <> OLD.fee_minor
BEGIN SELECT RAISE(ABORT, 'ledger financial fields are immutable; void and re-insert instead'); END;
CREATE TRIGGER ledger_no_delete BEFORE DELETE ON transaction_ledger
BEGIN SELECT RAISE(ABORT, 'ledger rows cannot be deleted; set voided = 1'); END;

CREATE TRIGGER policy_no_update BEFORE UPDATE ON policy
BEGIN SELECT RAISE(ABORT, 'policy is versioned; insert a new version'); END;
CREATE TRIGGER policy_no_delete BEFORE DELETE ON policy
BEGIN SELECT RAISE(ABORT, 'policy cannot be deleted'); END;

CREATE TRIGGER action_status_transition BEFORE UPDATE OF status ON proposed_action
WHEN NEW.status <> OLD.status
BEGIN
  SELECT RAISE(ABORT, 'illegal proposed_action status transition')
  WHERE NOT EXISTS (SELECT 1 FROM action_transition WHERE from_status = OLD.status AND to_status = NEW.status);
END;
CREATE TRIGGER action_frozen_after_proposal BEFORE UPDATE ON proposed_action
WHEN OLD.status <> 'PROPOSED'
  AND (NEW.amount_minor <> OLD.amount_minor OR NEW.kind <> OLD.kind
       OR NEW.payee_id IS NOT OLD.payee_id OR NEW.offer_id IS NOT OLD.offer_id)
BEGIN SELECT RAISE(ABORT, 'proposed_action is frozen once submitted for approval'); END;

CREATE TRIGGER approval_requires_pending BEFORE INSERT ON approval
BEGIN
  SELECT RAISE(ABORT, 'approval: action is not PENDING_APPROVAL or has expired')
  WHERE NOT EXISTS (
    SELECT 1 FROM proposed_action
    WHERE action_id = NEW.action_id AND status = 'PENDING_APPROVAL'
      AND expires_at > strftime('%Y-%m-%dT%H:%M:%SZ','now'));
END;
CREATE TRIGGER approval_sets_status AFTER INSERT ON approval
BEGIN
  UPDATE proposed_action
     SET status = CASE NEW.decision WHEN 'confirmed' THEN 'APPROVED' ELSE 'REJECTED' END
   WHERE action_id = NEW.action_id;
END;
CREATE TRIGGER approval_immutable BEFORE UPDATE ON approval
WHEN NEW.decision <> OLD.decision OR NEW.action_id <> OLD.action_id OR NEW.nonce <> OLD.nonce
  OR OLD.nonce_used_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'approval is immutable (only nonce_used_at may be set, once)'); END;
CREATE TRIGGER approval_no_delete BEFORE DELETE ON approval
BEGIN SELECT RAISE(ABORT, 'approval cannot be deleted'); END;

CREATE TRIGGER sandbox_txn_requires_approval BEFORE INSERT ON sandbox_txn
BEGIN
  SELECT RAISE(ABORT, 'sandbox_txn: action is not APPROVED')
  WHERE NOT EXISTS (SELECT 1 FROM proposed_action WHERE action_id = NEW.action_id AND status = 'APPROVED');
  SELECT RAISE(ABORT, 'sandbox_txn: no confirmed approval on record')
  WHERE NOT EXISTS (SELECT 1 FROM approval WHERE action_id = NEW.action_id AND decision = 'confirmed');
  SELECT RAISE(ABORT, 'sandbox_txn: amount differs from the approved action')
  WHERE NEW.amount_minor <> (SELECT amount_minor FROM proposed_action WHERE action_id = NEW.action_id);
END;
CREATE TRIGGER sandbox_txn_sets_status AFTER INSERT ON sandbox_txn
BEGIN
  UPDATE proposed_action
     SET status = CASE NEW.result WHEN 'success' THEN 'EXECUTED' ELSE 'BLOCKED' END
   WHERE action_id = NEW.action_id;
END;
CREATE TRIGGER sandbox_no_update BEFORE UPDATE ON sandbox_txn
BEGIN SELECT RAISE(ABORT, 'sandbox_txn is immutable'); END;
CREATE TRIGGER sandbox_no_delete BEFORE DELETE ON sandbox_txn
BEGIN SELECT RAISE(ABORT, 'sandbox_txn is immutable'); END;

-- =====================================================================
-- VIEWS
-- =====================================================================
CREATE VIEW v_ledger_enriched AS
SELECT t.*, c.code AS category_code, c.name AS category_name, c.kind AS category_kind,
       COALESCE(c.is_business, 1) AS is_business_money
FROM transaction_ledger t LEFT JOIN category c ON c.category_id = t.category_id
WHERE t.voided = 0;

CREATE VIEW v_daily_flow AS
SELECT t.business_id, t.account_id, t.local_date,
  SUM(CASE WHEN t.direction = 'in'  THEN t.amount_minor ELSE 0 END) AS inflow_minor,
  SUM(CASE WHEN t.direction = 'out' THEN t.amount_minor + t.fee_minor ELSE 0 END) AS outflow_minor,
  SUM(CASE WHEN c.kind = 'income' AND t.direction = 'in' THEN t.amount_minor ELSE 0 END) AS sales_minor,
  SUM(CASE WHEN c.kind IN ('cogs','opex','tax') AND t.direction = 'out' THEN t.amount_minor + t.fee_minor ELSE 0 END) AS operating_outflow_minor,
  SUM(CASE WHEN c.kind = 'personal' AND t.direction = 'out' THEN t.amount_minor ELSE 0 END) AS personal_minor,
  COUNT(*) AS txn_count
FROM transaction_ledger t LEFT JOIN category c ON c.category_id = t.category_id
WHERE t.voided = 0 AND (c.kind IS NULL OR c.kind <> 'transfer')
GROUP BY t.business_id, t.account_id, t.local_date;

CREATE VIEW v_monthly_pnl AS
SELECT t.business_id, substr(t.local_date,1,7) AS month,
  SUM(CASE WHEN c.kind = 'income' THEN (CASE t.direction WHEN 'in' THEN t.amount_minor ELSE -t.amount_minor END) ELSE 0 END) AS revenue_minor,
  SUM(CASE WHEN c.kind = 'cogs'   AND t.direction = 'out' THEN t.amount_minor + t.fee_minor ELSE 0 END) AS cogs_minor,
  SUM(CASE WHEN c.kind IN ('opex','tax') AND t.direction = 'out' THEN t.amount_minor + t.fee_minor ELSE 0 END) AS opex_minor,
  SUM(CASE WHEN c.kind = 'financing' AND t.direction = 'out' THEN t.amount_minor + t.fee_minor ELSE 0 END) AS financing_outflow_minor,
  SUM(CASE WHEN c.kind = 'personal' AND t.direction = 'out' THEN t.amount_minor ELSE 0 END) AS personal_minor
FROM transaction_ledger t JOIN category c ON c.category_id = t.category_id
WHERE t.voided = 0
GROUP BY t.business_id, substr(t.local_date,1,7);

CREATE VIEW v_current_balance AS
SELECT t.account_id, t.business_id, t.balance_after_minor AS balance_minor, t.ts AS as_of
FROM transaction_ledger t
WHERE t.voided = 0 AND t.balance_after_minor IS NOT NULL
  AND t.txn_id = (SELECT x.txn_id FROM transaction_ledger x
                  WHERE x.account_id = t.account_id AND x.voided = 0 AND x.balance_after_minor IS NOT NULL
                  ORDER BY x.ts DESC, x.txn_id DESC LIMIT 1);

CREATE VIEW v_review_queue AS
SELECT t.txn_id, t.business_id, t.local_date, t.amount_minor, t.direction, t.counterparty_token,
       t.description_redacted, t.category_id, t.confidence
FROM transaction_ledger t
WHERE t.voided = 0 AND (t.needs_review = 1 OR t.category_id IS NULL
      OR (t.confidence IS NOT NULL AND t.confidence < 0.60 AND COALESCE(t.category_source,'') <> 'owner'));

CREATE VIEW v_upcoming_obligations AS
SELECT o.business_id, o.obligation_id, o.label, o.kind, o.amount_minor, o.next_due,
       CAST(julianday(o.next_due) - julianday(date('now')) AS INTEGER) AS days_until_due
FROM obligation o
WHERE o.active = 1 AND o.next_due IS NOT NULL
  AND julianday(o.next_due) - julianday(date('now')) BETWEEN 0 AND 30;

CREATE VIEW v_open_actions AS
SELECT a.action_id, a.business_id, a.kind, a.amount_minor, a.status, a.expires_at, a.payload_json
FROM proposed_action a WHERE a.status IN ('PROPOSED','PENDING_APPROVAL','APPROVED');

CREATE VIEW v_personal_mix AS
SELECT business_id, month,
  personal_minor,
  (cogs_minor + opex_minor + financing_outflow_minor + personal_minor) AS total_outflow_minor,
  CASE WHEN (cogs_minor + opex_minor + financing_outflow_minor + personal_minor) = 0 THEN 0
       ELSE personal_minor * 10000 / (cogs_minor + opex_minor + financing_outflow_minor + personal_minor) END AS personal_mix_bp
FROM v_monthly_pnl;

CREATE VIEW v_security_summary AS
SELECT event_type, COALESCE(decision,'n/a') AS decision, COUNT(*) AS events FROM audit_log GROUP BY event_type, decision;

-- =====================================================================
-- SEED / REFERENCE DATA
-- =====================================================================
INSERT INTO schema_migration(version, description) VALUES (1, 'Initial full SME data model');

INSERT INTO currency(code, name, minor_unit) VALUES ('KES','Kenyan shilling',2), ('USD','US dollar',2);
INSERT INTO platform(code, name, country_code, adapter_name) VALUES ('mobile_money_ke','Mobile money (Kenya)','KE','MobileMoneyKeAdapter');

INSERT INTO permission_tier(tier, name, description, requires_approval, sandbox_only) VALUES
 ('T0','Read','Read ledger, compute analytics and forecasts',0,0),
 ('T1','Suggest','Alerts, recommendations and draft documents; no money moves',0,0),
 ('T2','Execute with approval','Sandbox payments and loan requests after owner confirmation',1,1),
 ('T3','Forbidden','Change limits, add unverified payees, act outside the sandbox, send data externally',1,1);

INSERT INTO tool_registry(tool_name, tier, description, exposed_to_llm, enabled) VALUES
 ('ingest_statement','T0','Parse and validate an uploaded statement',1,1),
 ('categorise_transactions','T0','Categorise transactions (rules first, LLM fallback)',1,1),
 ('get_ledger_summary','T0','Totals by category and period',1,1),
 ('compute_business_health','T0','Revenue, costs, margin, best and worst days, personal mix',1,1),
 ('forecast_balance','T0','Forecast the balance with p10/p50/p90 band',1,1),
 ('check_affordability','T0','Test an offer against the forecast and buffer',1,1),
 ('search_knowledge','T0','Retrieve knowledge-base chunks',1,1),
 ('build_chart','T0','Return a chart specification and data',1,1),
 ('detect_shortfalls','T1','Raise a shortfall alert with suggested actions',1,1),
 ('compare_financing','T1','Rank credit options by total cost',1,1),
 ('draft_application_pack','T1','Draft a loan application pack',1,1),
 ('propose_supplier_payment','T2','Create a pending supplier payment proposal',1,1),
 ('propose_loan_request','T2','Create a pending loan request proposal',1,1),
 ('execute_approved_action','T2','Execute an approved action in the sandbox (UI only)',0,1),
 ('change_limits','T3','Change caps or policy (forbidden)',0,0),
 ('add_payee','T3','Add an unverified payee (forbidden)',0,0),
 ('send_data_external','T3','Send data outside the system (forbidden)',0,0);

INSERT INTO action_transition(from_status, to_status) VALUES
 ('PROPOSED','PENDING_APPROVAL'), ('PROPOSED','BLOCKED'),
 ('PENDING_APPROVAL','APPROVED'), ('PENDING_APPROVAL','REJECTED'), ('PENDING_APPROVAL','EXPIRED'),
 ('APPROVED','EXECUTED'), ('APPROVED','BLOCKED');

INSERT INTO policy(business_id, version, per_txn_cap_minor, daily_cap_minor, approval_ttl_minutes, rate_limit_per_min, sandbox_only, changed_by)
VALUES (NULL, 1, 2500000, 5000000, 15, 30, 1, 'seed');

INSERT INTO category(code, name, kind, is_business, sort_order) VALUES
 ('SALES_TILL','Sales (till)','income',1,10),
 ('SALES_TRANSFER','Sales (transfer)','income',1,11),
 ('CREDIT_RECOVERY','Customer credit recovered','income',1,12),
 ('OTHER_INCOME','Other income','income',1,19),
 ('STOCK_PURCHASES','Stock purchases','cogs',1,20),
 ('RENT','Rent','opex',1,30),
 ('UTILITIES','Utilities','opex',1,31),
 ('TRANSPORT','Transport and delivery','opex',1,32),
 ('WAGES','Wages','opex',1,33),
 ('AIRTIME_DATA','Airtime and data','opex',1,34),
 ('REPAIRS','Repairs and maintenance','opex',1,35),
 ('TXN_CHARGES','Mobile-money charges','opex',1,36),
 ('OTHER_OPEX','Other operating costs','opex',1,39),
 ('LICENSE_TAX','Licences and taxes','tax',1,40),
 ('LOAN_DISBURSEMENT','Loan received','financing',1,50),
 ('LOAN_REPAYMENT','Loan repayment','financing',1,51),
 ('OVERDRAFT_FEE','Overdraft fee','financing',1,52),
 ('INTEREST_FEES','Interest and credit fees','financing',1,53),
 ('PERSONAL_WITHDRAWAL','Personal withdrawal','personal',0,60),
 ('FAMILY_TRANSFER','Family transfer','personal',0,61),
 ('SCHOOL_FEES','School fees','personal',0,62),
 ('PERSONAL_OTHER','Other personal','personal',0,69),
 ('OWN_TRANSFER','Transfer between own accounts','transfer',0,70),
 ('SAVINGS_DEPOSIT','Savings deposit','transfer',0,71),
 ('UNCLASSIFIED','Unclassified','unknown',1,99);

INSERT INTO credit_product(code, type, name, repayment_style, min_amount_minor, max_amount_minor, min_term_days, max_term_days, eligibility_note, is_illustrative) VALUES
 ('MOBILE_OVERDRAFT','mobile_overdraft','Mobile overdraft','single',10000,10000000,1,30,'Instant; based on account activity',1),
 ('MOBILE_MICROLOAN','mobile_microloan','Mobile micro-loan','single',50000,20000000,7,60,'Instant; limit set by the platform',1),
 ('SACCO_LOAN','sacco_loan','SACCO loan','equal_installments',500000,100000000,30,730,'Membership and savings history usually required',1),
 ('BANK_SME_LOAN','bank_sme_loan','Bank SME loan','equal_installments',1000000,500000000,90,1095,'Records, registration and guarantor or collateral often required',1);

INSERT INTO credit_fee_component(product_id, kind, basis, rate_bp, flat_minor, period_days, description) VALUES
 ((SELECT product_id FROM credit_product WHERE code='MOBILE_OVERDRAFT'),'upfront_pct','principal',600,NULL,NULL,'Facility fee (illustrative)'),
 ((SELECT product_id FROM credit_product WHERE code='MOBILE_MICROLOAN'),'upfront_pct','principal',900,NULL,NULL,'Facility fee (illustrative)'),
 ((SELECT product_id FROM credit_product WHERE code='SACCO_LOAN'),'periodic_pct','outstanding',150,NULL,30,'Monthly interest (illustrative)'),
 ((SELECT product_id FROM credit_product WHERE code='SACCO_LOAN'),'upfront_flat','flat',NULL,50000,NULL,'Processing fee (illustrative)'),
 ((SELECT product_id FROM credit_product WHERE code='BANK_SME_LOAN'),'periodic_pct','outstanding',120,NULL,30,'Monthly interest (illustrative)'),
 ((SELECT product_id FROM credit_product WHERE code='BANK_SME_LOAN'),'upfront_pct','principal',200,NULL,NULL,'Arrangement fee (illustrative)');

-- =====================================================================
-- Duka Platform Evolution: Phase 1-3 schema extensions [EXT]
-- Added: 2026-10-17
-- All tables use IF NOT EXISTS for idempotent application.
-- =====================================================================

-- Business-specific category customization
CREATE TABLE IF NOT EXISTS business_category_config (
  config_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  global_category_id INTEGER NOT NULL REFERENCES category(category_id),
  display_name TEXT,
  is_tracking_active INTEGER NOT NULL DEFAULT 1 CHECK (is_tracking_active IN (0,1)),
  monthly_budget_minor INTEGER,
  alert_threshold_pct INTEGER NOT NULL DEFAULT 80 CHECK (alert_threshold_pct BETWEEN 1 AND 100),
  auto_categorize_keywords TEXT,
  UNIQUE (business_id, global_category_id)
);

-- Financial goals and targets
CREATE TABLE IF NOT EXISTS financial_goal (
  goal_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  goal_type TEXT NOT NULL CHECK (goal_type IN (
    'revenue_target','margin_target','expense_budget','personal_limit',
    'cash_buffer','savings','debt_reduction','growth'
  )),
  target_period TEXT NOT NULL CHECK (target_period IN ('monthly','quarterly','annual')),
  target_value_minor INTEGER NOT NULL,
  metric TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  priority INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Recurring expenses (enhanced obligation concept)
CREATE TABLE IF NOT EXISTS recurring_expense (
  expense_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  party_id INTEGER REFERENCES party(party_id),
  expense_type TEXT NOT NULL CHECK (expense_type IN (
    'rent','salary','utilities','insurance','supplier_credit',
    'loan_repayment','tax','maintenance','service_subscription','other'
  )),
  description TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  cadence TEXT NOT NULL CHECK (cadence IN (
    'daily','weekly','biweekly','monthly','quarterly','annual'
  )),
  day_of_month INTEGER CHECK (day_of_month BETWEEN 1 AND 31),
  next_due TEXT NOT NULL,
  end_date TEXT,
  is_variable INTEGER NOT NULL DEFAULT 0 CHECK (is_variable IN (0,1)),
  variable_formula TEXT,
  times_paid INTEGER NOT NULL DEFAULT 0,
  times_missed INTEGER NOT NULL DEFAULT 0,
  avg_actual_minor INTEGER,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Instances of recurring expenses (track when paid)
CREATE TABLE IF NOT EXISTS recurring_expense_instance (
  instance_id INTEGER PRIMARY KEY,
  expense_id INTEGER NOT NULL REFERENCES recurring_expense(expense_id),
  due_date TEXT NOT NULL,
  expected_amount_minor INTEGER NOT NULL,
  matched_txn_id INTEGER REFERENCES transaction_ledger(txn_id),
  actual_amount_minor INTEGER,
  status TEXT NOT NULL DEFAULT 'expected' CHECK (status IN (
    'expected','paid','late','missed','skipped'
  )),
  paid_date TEXT,
  notes TEXT,
  UNIQUE (expense_id, due_date)
);

-- Chart of accounts (Phase 3 population, Phase 1 schema)
CREATE TABLE IF NOT EXISTS chart_of_accounts (
  account_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  account_code TEXT NOT NULL,
  account_name TEXT NOT NULL,
  account_type TEXT NOT NULL CHECK (account_type IN (
    'asset','liability','equity','income','expense'
  )),
  parent_account_id INTEGER REFERENCES chart_of_accounts(account_id),
  description TEXT,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  UNIQUE (business_id, account_code)
);

-- Backward-compatible view over recurring_expense for existing obligation queries
CREATE VIEW IF NOT EXISTS v_obligation_compat AS
SELECT
  expense_id AS obligation_id,
  business_id,
  description AS label,
  amount_minor,
  cadence,
  day_of_month,
  next_due,
  active
FROM recurring_expense;
