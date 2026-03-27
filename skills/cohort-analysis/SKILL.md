---
description: Set up and launch an interactive cohort analysis dashboard. Use when the user wants to analyze engagement retention, revenue/GP cohorts, CAC/LTV payback, or customer retention from CSV, Excel, or database data.
user-invocable: true
---

# Cohort Analysis Setup

You are setting up a cohort analysis dashboard. The app code lives at `${CLAUDE_SKILL_DIR}/../../app/` and data configs go in `${CLAUDE_SKILL_DIR}/../../data/configs/`.

Guide the user through data ingestion interactively.

## Step 1: Detect Data Sources

First, ask the user what they're working with:

> "What data source do you have? I can work with CSV files, Excel files (.xlsx), or connect directly to a PostgreSQL database."

### If files (CSV/Excel):
Scan the working directory for `.xlsx`, `.csv` files. List what you find and ask:
- Which file(s) contain **engagement/event data**? (user activity, events, actions)
- Which file(s) contain **revenue/transaction data**? (purchases, revenue, GP)
- Which file/sheet contains **marketing spend inputs**? (S&M spend by month, for CAC/LTV)

Any of these can be "none" — the dashboard only shows tabs for available data.

### If database (PostgreSQL):
1. Ask for the connection string: `postgresql://user:pass@host:port/dbname`
2. **Explore the schema first.** Run a Python script to connect and list tables:
   ```python
   import psycopg2
   conn = psycopg2.connect(connection_string)
   cur = conn.cursor()
   cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
   tables = [r[0] for r in cur.fetchall()]
   ```
3. For each relevant-looking table, fetch column names and sample rows:
   ```python
   cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}'")
   cur.execute(f"SELECT * FROM {table} LIMIT 5")
   ```
4. Present the schema to the user and ask which tables/columns map to engagement events, revenue transactions, user signups, etc.
5. Write the SQL query that joins the relevant tables and extracts the needed columns. The query should output columns matching the expected format: `customer_id`, `action_month` (timestamp), `event_type`, `event_count`, `revenue`, etc.
6. Store the connection string and query in the config (see Step 5).

The query runs at server startup and caches the results in memory, so the dashboard is fast after initial load. If the database is large, add `WHERE` clauses to limit the date range.

## Step 2: Read Headers & Auto-Suggest Column Mappings

For each selected file/sheet (or the query results for DB sources), read the first few rows to understand the schema. Then ask the user to confirm or correct these mappings:

### For Engagement Data:
- **Customer/User ID** — look for columns named: user_id, customer_id, User, Customer ID, id
- **Action/Event Date** — look for: event_date, action_month, event_month, date, created_at, Date
- **Event Type** (optional) — look for: event, event_type, type, action
- **Event Count** (optional) — look for: event_count, count, quantity (default to 1 if not present)

### For Revenue Data:
- **Customer ID** — look for: Customer ID, customer_id, id, User
- **Revenue** — look for: Total Revenue, revenue, amount, Revenue, Price
- **Action/Transaction Date** — look for: Action Month, transaction_date, date, Date
- **Gross Margin %** (optional) — look for: % Margin, margin, Margin
- **GP** (optional) — look for: GP ($), gross_profit, GP
- **Plan/Segment** (optional) — look for: Plan, plan, segment, tier

### For Marketing Spend (Inputs):
- Read the Inputs sheet. Expect row structure: dates in first row, S&M spend in second row, margin % in third row.
- If the file has a different format, ask the user to explain the layout.

## Step 3: Accrual vs Cash Revenue Recognition

This is important if the business has any revenue that spans multiple periods. Ask the user:

> "Does your revenue data represent **cash** (revenue recorded when payment is received) or **accrual** (revenue spread over the service period)? Would you like both views?"

Look for signals that accrual matters:
- **Subscription plans** — annual, quarterly, or multi-month plans where a single payment covers multiple months
- **Prepaid credits** — customers buy credits upfront and use them over time
- **Contracts with milestones** — revenue recognized at delivery, not payment
- **Deferred revenue** — setup fees, onboarding charges, or implementation fees that should be spread
- **Refunds/chargebacks** — may need to be allocated back to the original period
- **Usage-based billing** — billed monthly but usage accrues daily

If the founder wants both views:
1. Ask them to explain their specific accrual rules: "How should I spread the revenue? For example, should an annual plan's payment be divided evenly across 12 months? Are there setup fees that should be treated differently?"
2. Write a preprocessing function in `data_processor.py` that takes the cash data and generates an accrual version based on their rules
3. The function should handle edge cases the founder mentions (e.g., pro-rated first months, mid-month starts, refunds)
4. Both datasets get loaded at startup — the Accrual/Cash toggle in the Revenue & GP tab switches between them

If the data already has separate accrual and cash sheets/tables, just map them in the config (`"sheet"` for accrual, `"cash_sheet"` for cash).

If the founder only has one view and doesn't need both, skip this step.

## Step 4: Cohort Date Resolution

**Default: calculate cohort from first appearance.** Most datasets won't have an explicit cohort column. Set `calculate_cohort: true` — the tool derives `cohort_month = min(action_date)` per customer, floored to start of month (or week in weekly mode).

Only ask the user if you notice a column that looks like it could be a pre-set cohort date (e.g., 'Cohort Month', 'signup_date', 'cohort_week'). In that case, confirm:

> "I see a column called '[name]' — is this the cohort date you want to use, or should I calculate cohorts from each customer's first transaction?"

If the data has Excel serial numbers for dates (large numbers like 45322), the tool handles this automatically.

## Step 5: Write Config

Ask the user for a **profile name** (e.g., the company name, product name, or dataset label). This allows running multiple analyses side by side.

> "What should I call this analysis? (e.g., 'acme', 'q1-2025', 'product-a')"

Write the config to `${CLAUDE_SKILL_DIR}/../../data/configs/{profile_name}.json`. If this is the only analysis, also copy it to `${CLAUDE_SKILL_DIR}/../../data/config.json` as the default.

Example structure:

```json
{
  "engagement": {
    "source_type": "file",
    "filepath": "engagement_data.xlsx",
    "sheet": "Data",
    "calculate_cohort": true,
    "column_map": {
      "customer_id": "user_id",
      "action_month": "event_month",
      "event_type": "event",
      "event_count": "event_count"
    }
  },
  "revenue": {
    "source_type": "file",
    "filepath": "revenue_data.xlsx",
    "sheet": "Data",
    "cash_sheet": "Data_Cash",
    "calculate_cohort": true,
    "column_map": {
      "customer_id": "Customer ID",
      "revenue": "Total Revenue",
      "action_month": "Action Month",
      "margin_pct": "% Margin",
      "gp": "GP ($)",
      "plan": "Plan"
    }
  },
  "inputs": {
    "filepath": "revenue_data.xlsx",
    "sheet": "Inputs"
  }
}
```

For database connections:
```json
{
  "engagement": {
    "source_type": "db",
    "connection_string": "postgresql://user:pass@host:5432/dbname",
    "query": "SELECT u.id AS customer_id, ae.created_at AS action_month, ae.event AS event_type, 1 AS event_count FROM users u JOIN analytics_events ae ON ae.user_id = u.id",
    "calculate_cohort": true,
    "column_map": {}
  }
}
```

## Step 6: Monthly vs Weekly Mode

By default the dashboard runs in **monthly** mode. If the user's data has daily-level timestamps (not pre-aggregated by month) and they want weekly cohort analysis, set `"period": "week"` in the config:

```json
{
  "period": "week",
  "engagement": { ... },
  "revenue": { ... }
}
```

When `period` is `"week"`:
- Cohorts are bucketed by the week the customer first appeared (Monday start)
- All charts show weekly intervals instead of monthly
- X-axis labels show week-start dates
- The "Include latest week" toggle excludes the current incomplete week

**When to use weekly mode:**
- The source data has daily or per-event timestamps (e.g., from a database)
- The dataset covers a short time period (< 6 months) where monthly cohorts would be too few
- The founder wants more granular retention curves

**Do NOT use weekly mode when:**
- Source data is already aggregated by month (e.g., pre-bucketed Excel templates)
- Weekly would create too many cohorts to be readable

Ask the user: "Your data spans N months with daily timestamps. Would you like monthly or weekly cohorts?"

## Step 7: Install Dependencies & Launch

```bash
cd ${CLAUDE_SKILL_DIR}/../..
pip install -r requirements.txt
python app/server.py
```

Tell the user the dashboard is running at http://localhost:8000 and explain:
- Which tabs are available based on their data
- The profile name (visible in the dropdown if multiple profiles exist)
- How to switch profiles if they have multiple analyses

If the server is already running, call the reload endpoint instead:
```bash
curl -X POST 'http://localhost:8000/api/reload?profile={profile_name}'
```

Then tell the user to refresh the browser.
