# Duka Copilot

An AI finance copilot for small businesses that run on mobile money. Built for the **Shenzhen FinTechathon 2026 International Track, Topic E (SME Finance Copilot)**.

"Duka" means "shop" in Swahili.
> **Test data:** every statement in `data/mock_data/` (including the M-Pesa PDF) and the bundled databases are AI-generated. All names, phone numbers and transactions are fictional. 

## Quick Start

### 1. Prerequisites

- Python 3.11 or higher
- pip (Python package manager)
- A Google Gemini API key (get free credits at [ai.google.dev](https://ai.google.dev))
- Git (to clone the repository)

### 2. Installation

**Clone the repository:**

```bash
git clone https://github.com/Kal0ndu/duka-copilot.git
cd duka-copilot
git checkout  improved
```

**Create a virtual environment:**

```bash
# On macOS/Linux
python3 -m venv .venv
source .venv/bin/activate

# On Windows
python -m venv .venv
.venv\Scripts\activate
```

**Install dependencies:**

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

**Copy the example environment file:**

```bash
cp .env.example .env
```

**Edit `.env` with your API key:**

```bash
# On macOS/Linux
nano .env

# On Windows
notepad .env
```

**Add your Gemini API key:**

```env
LLM_API_KEY=your_gemini_api_key_here
MODEL_NAME=gemini-3.8-flash  # or another available model
CAP_PER_TXN=25000            # KES, per-transaction limit
CAP_DAILY=50000              # KES, daily limit
```

### 4. Set Up the Database

The database (`data/duka.db`) is **not** committed to git — build it with:

```bash
python3 db/migrate.py
```

See [Database Setup](#database-setup) below for details and reset instructions.

### 5. Generate Sample Data (Optional but Recommended)

**Create synthetic database and CSV seed data for testing:**

```bash
python data/generate_synthetic.py --db data/synthetic.db --output both --seed 400 --reset
```

This creates `data/synthetic.db` from `db/schema.sql` and one portable CSV
per populated table in `data/seed_csv/`. Use `--output database` or
`--output csv` when only one format is needed.

For a larger relational seed set with at least 1,000 rows in each
business-linked relation:

```bash
python data/generate_synthetic.py --output csv --csv-dir data/seed_csv_1000 \
  --rows-per-table 1000 --days 30 --seed 400
```

Reference tables such as `currency`, `category`, and `platform` retain the
canonical rows from `db/schema.sql`; generated business-linked tables scale
to the requested size with valid foreign keys.

This creates three test personas:

- Grocery shop (amina_grocery_*)
- Salon (grace_salon_*)
- Transport operator (otieno_transport_*)

### 6. Launch the Application

**Start the Streamlit app:**

```bash
streamlit run app/main.py
```

The app will open at `http://localhost:8501` in your default browser.

**If it doesn't open automatically, visit:**

```
http://localhost:8501
```

### 7. First Steps in the App

1. **Upload Statement** → Upload an M-Pesa PDF (password-protected is fine) or CSV, or use a file from `data/mock_data/`. It is saved to your ledger and becomes the assistant's context.
2. **Review Ledger** → Verify categorizations, correct as needed
3. **View Insights** → See revenue, costs, margins, best trading days
4. **Forecast** → Check 14-30 day balance forecast with alerts
5. **Financing** → Compare credit options by cost
6. **Standing Orders** → Set up regular payments; Duka ranks and reminds, you authorize each one
7. **Chat** → Ask the AI copilot questions about your business

**Administrator.** Every account created by sign-up is a regular user. One account can be the
administrator, the only one that can open **Admin Security** (audit trail, security events, accounts).
Set it on the server after that person has signed up:

```bash
python scripts/set_admin.py 0712345678              # first admin
python scripts/set_admin.py 0712345678 --transfer   # hand over to someone else
python scripts/set_admin.py --show
```

The database allows only one admin, and no account can be created as admin.

### 8. Standing Orders: M-Pesa Daraja and Twilio

Duka never pays on its own. For each due payment it sends an in-app and SMS
reminder ranked by priority. The owner taps **Authorize & pay**, which sends an
M-Pesa STK prompt to their own phone, and the money only moves once they
enter their PIN.

#### M-PESA Daraja Setup

**Sandbox (Test) Mode — Use These Credentials:**

1. Go to https://developer.safaricom.co.ke and register a new app
2. In `.env`, use these test credentials:
   ```env
   DARAJA_ENV=sandbox
   DARAJA_CONSUMER_KEY=testapi
   DARAJA_CONSUMER_SECRET=testapi
   DARAJA_INITIATOR_NAME=testapi
   DARAJA_INITIATOR_PASSWORD=Safaricom123!!
   DARAJA_PARTY_A=600988
   DARAJA_PARTY_B=600000
   DARAJA_PHONE_NUMBER=254708374149
   DARAJA_SHORTCODE=174379
   DARAJA_PASSKEY=bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919
   ```

3. To generate a **Security Credential** for API calls:
   - Visit https://developer.safaricom.co.ke (Developer Portal)
   - Navigate to **Security Credential** generator
   - Enter your **Initiator Password** (e.g., `Safaricom123!!`)
   - Select environment (**Sandbox** or **Production**)
   - Copy the generated **Security Credential**
   - Example output for sandbox:
     ```
     FRw7pQ2Y1an7ra66v/PrWVgCMGvSjgiyB5fj5o6K1epWRcbPZ0vxmcaQqXYHLP2HrS0ifeCMxueJKz09yzcPKtUhWZx/0zY5D6ybx5yy1ut/DJb9pQ1MJ7jJbWdzK947Gvyeqk3bPRQ+1VCiqpR5GdZlH641bXh54wAK6R7t7pGBnnPqQvHaVTsYO9AjYd8x1hOIkwbPnQ3EH2ziu35/PDmW3ud/2Ct462lPPoLTHlngqT5cueE9FIqJmNl7/SubAOFZqqpMziSqDa+1ZEppl7fvAX/A7srujdPLYDLfL8Qu90+R4MovLSV7V3cf8C5ErFE8LrcRQwzjEQiSwdHeeQ==
     ```

**Production Mode — Use Your Own Credentials:**

1. Register your business at https://www.safaricom.co.ke/business/m-pesa/m-pesa-for-business
2. Create a new app in the M-PESA portal (https://developer.safaricom.co.ke)
3. Set `DARAJA_ENV=production` in `.env`
4. Fill in your production credentials (keep them secret — never commit to git)
5. Generate your production Security Credential using the same portal tool

**Test User for Sandbox:**

- **Name**: Musindi Kyule
- **Party A** (Receiver): 600988
- **Party B** (Payer/Shortcode): 600000
- **Phone**: 254708374149
- **Business ShortCode**: 174379

#### SMS Notifications (Twilio)

For SMS reminders, set `SMS_PROVIDER=twilio` plus your Twilio credentials in `.env`:

```env
SMS_PROVIDER=twilio
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_FROM=+1234567890
```

Note: Twilio trial accounts can only text verified phone numbers.

#### Final Steps

1. In the app, open **Standing Orders → Notification settings** and save your
   login phone number. Prompts can only go to that number.
2. Schedule reminders so they go out even when nobody opens the app:
   ```bash
   # crontab -e : every day at 07:00
   0 7 * * * cd /path/to/duka && .venv/bin/python -m core.standing_orders
   ```

---

## Development Workflow

### Local Development

**Run with auto-reload:**

```bash
streamlit run app/main.py --logger.level=debug
```

**Test as you develop:**

```bash
# In another terminal, keep this running
pytest --watch
```

### Common Development Tasks

**Add a new page:**

```bash
touch app/app_pages/feature_name.py
```

Then register it in `app/main.py`, which builds the menu with `st.navigation`:
add an `_page("feature_name.py", "Feature name", ":material/icon:", "Feature_Name")`
entry to the right section. Pages start with `require_auth()`; the menu is
hidden until the user logs in.

**Run specific tests:**

```bash
# Unit tests only
pytest tests/unit/ -v

# Security tests only
pytest tests/security/ -v

# End-to-end tests
pytest tests/e2e/ -v

# Run with coverage
pytest --cov=core --cov=agent --cov=sandbox
```

**Debug a specific test:**

```bash
pytest tests/unit/test_categoriser.py::test_rule_match -v -s
```

**Check code quality:**

```bash
# If you have linters installed
flake8 core/ agent/ sandbox/
black core/ agent/ sandbox/ --check
```

---

## Database Setup

The database is not committed to git (`*.db` is in `.gitignore`) — after cloning,
build it with the migration runner:

```bash
python3 db/migrate.py
```

This loads `db/schema.sql` as the base schema (if the target file has no
tables yet), then applies any pending files in `db/migrations/` in order,
tracked in the `schema_migration` table. It's safe to re-run — already
applied migrations are skipped.

By default it operates on `data/duka.db` (`Config.DB_PATH` / `DUKA_DB_PATH`
env var). Check status or point it at a different file:

```bash
python3 db/migrate.py --status                 # show applied / pending migrations
DUKA_DB_PATH=data/other.db python3 db/migrate.py  # migrate a different file
```

To reset from scratch:

```bash
rm data/duka.db
python3 db/migrate.py
```

To inspect the database:

```bash
sqlite3 data/duka.db
> .tables                    # list all tables
> SELECT COUNT(*) FROM transaction_ledger;  # check record count
> .quit                      # exit
```

---

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'streamlit'"

**Solution:** Make sure your virtual environment is activated:

```bash
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate     # Windows
```

### Issue: "API key not found" or "Authentication failed"

**Solution:** Check your `.env` file:

```bash
cat .env  # verify LLM_API_KEY is set
echo $LLM_API_KEY  # on macOS/Linux, check if it's accessible
```

### Issue: Port 8501 already in use

**Solution:** Run Streamlit on a different port:

```bash
streamlit run app/main.py --server.port 8502
```

### Issue: Database locked error

**Solution:** The SQLite database can only have one writer. Make sure:

- Only one instance of the app is running
- No other processes have the database open
- Clear old processes: `pkill -f streamlit`

### Issue: Tests fail with "database is locked"

**Solution:** Run tests sequentially (not in parallel):

```bash
pytest -n 0  # disable xdist parallel execution
```

---

## Environment Variables Reference

```env
# Required
LLM_API_KEY=your_gemini_api_key

# Optional (defaults provided)
MODEL_NAME=gemini-3.8-flash
CAP_PER_TXN=25000
CAP_DAILY=50000
DB_PATH=duka.db
LOG_LEVEL=INFO
SEED=42
```

---

## Production Deployment

### Before Deploying

- [ ] Test all security tests pass: `pytest tests/security/`
- [ ] Verify audit log integrity: check `verify_audit()` in `db/audit.py`
- [ ] Update `.env` with production API key
- [ ] Set appropriate caps for your market
- [ ] Review all policies in `agent/policy_guard.py`

### Deployment Options

**Streamlit Cloud (easiest):**

```bash
# Connect your GitHub repo to Streamlit Cloud at https://share.streamlit.io
# Streamlit auto-deploys on each push to main
```

**Docker:**

```bash
docker build -t duka-copilot .
docker run -p 8501:8501 -e LLM_API_KEY=$LLM_API_KEY duka-copilot
```

**Traditional Server (Ubuntu/Linux):**

```bash
# Install Python and dependencies
sudo apt-get update
sudo apt-get install python3.11 python3-pip
pip install -r requirements.txt

# Run with systemd
sudo systemctl start duka-copilot
sudo systemctl enable duka-copilot  # auto-start on reboot
```

---

## Documentation

For detailed technical documentation, see:

- **Architecture**: `docs/architecture.tex` (compile with `pdflatex`)
- **Database Gaps & Analysis**: `docs/DATABASE_GAPS_AND_RECOMMENDATIONS.md`
- **Business Vision**: `docs/VISION_SME_FINANCIAL_PLATFORM.md`
- **Implementation Guide**: `docs/IMPLEMENTATION_GUIDE.md`

---

## Running Tests

```bash
pytest                          # all tests
pytest tests/unit               # unit tests only
pytest tests/security           # security tests
pytest -m "not slow"            # skip slow tests
```

## Architecture

```
Streamlit UI -> Orchestrator (Gemini + tool calling) -> Redaction -> Gemini API
                      |
                 Policy guard (code)
                      |
 Tools: parser+adapters, categoriser, analytics, forecaster, cost engine,
        drafter, RAG retriever, chart builder, proposal tools
                      |
        SQLite (ledger, forecasts, offers, KB, approvals, audit)   Sandbox
```

- **Permission tiers**: T0 (read), T1 (suggest), T2 (execute with approval), T3 (forbidden)
- **Stack**: Python 3.11, Streamlit, pandas, numpy, statsmodels, SQLite+FTS5, pytest, pydantic, Altair, Google Gemini
- **Security**: policy guard in code (fail-closed), redaction before LLM, append-only hash-chained audit log, synthetic data only
- **Money**: always integer minor units; Decimal for fractions; round only for display

## Project Structure

```
duka/
  README.md
  requirements.txt
  .env.example
  app/                    # Streamlit UI
    main.py
    pages/                # chat, ledger, insights, forecast, financing, approvals, audit
  core/                   # Business logic (no UI, no LLM)
    adapters/             # Statement parsers (mobile_money_ke.py, base.py)
    redaction.py
    categoriser.py
    analytics.py
    forecaster.py
    cost_engine.py
    drafter.py
    charts.py
    rag/                  # ingest.py, retrieve.py, kb/*.md
  agent/                  # LLM orchestration
    orchestrator.py
    llm_client.py         # Gemini provider + disk cache
    tools.py              # Registry, specs, tiers
    policy_guard.py
    verify_numbers.py
  sandbox/                # Simulated execution environment
    account.py
    mock_lender.py
  db/                     # Database layer
    schema.sql
    audit.py
  data/                   # Synthetic data generation
    generate_synthetic.py
  tests/
    unit/  security/  e2e/
  docs/                   # Architecture, security report, evidence
```
 something to work on :
 Next Steps: Navigate using the sidebar to explore 2. Analytics, 3. Cashflow Forecast, 4. Party Intelligence, 5. Working Capital, and 6. Financing Advisor.
## License

This project is built for competition evaluation. All data is synthetic.
