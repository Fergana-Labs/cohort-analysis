# Cohort Analysis Tool

A standalone, locally runnable cohort analysis dashboard. Point it at a CSV, Excel file, or PostgreSQL database and get interactive cohort charts — engagement retention, revenue/GP cohorts, CAC/LTV payback, and more.

Built to be used with [Claude Code](https://claude.ai/code) via the `/cohort-analysis` skill, or run directly.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app/server.py
# Open http://localhost:8000
```

## Using with Claude Code

Paste one of these prompts into Claude Code:

**For CSV/Excel files:**
```
I have a cohort analysis tool in this directory. I want to analyze my data.
Here's my data file: [filename.csv or filename.xlsx].
Please run /cohort-analysis to set it up and launch the dashboard.
```

**For a PostgreSQL database:**
```
I have a cohort analysis tool in this directory. I want to analyze my data.
My database connection string is: postgresql://user:pass@host:port/dbname
Please run /cohort-analysis to explore my schema, set it up, and launch the dashboard.
```

Claude Code will:
1. Detect your data files or explore your database schema
2. Ask you to confirm column mappings (customer ID, dates, revenue, etc.)
3. Ask about accrual vs cash revenue recognition if relevant
4. Calculate cohort dates from each customer's first appearance (default)
5. Generate the config, install dependencies, and launch the dashboard

## Data Requirements

### Engagement Cohorts
- **Required:** user/customer ID, event/action date
- **Optional:** event type, event count, explicit cohort date

### Revenue & GP Cohorts
- **Required:** customer ID, action/transaction date, revenue amount
- **Optional:** gross margin % or GP column, plan/segment type, explicit cohort date

### CAC/LTV Payback
- **Required:** everything for Revenue & GP, plus monthly marketing spend data
- Marketing spend can be in a separate sheet/file or provided as a simple monthly table

### Cohort Date
If your data doesn't have an explicit cohort date column, the tool calculates it automatically as each customer's **first appearance date**, floored to the start of the month. This is the most common approach — a customer's cohort is the month they first showed up.

## Supported Data Sources
- **CSV** files (`.csv`)
- **Excel** files (`.xlsx`) — including multi-sheet workbooks
- **PostgreSQL** — provide a connection string (`postgresql://user:pass@host:port/db`)

## Views

### Core
1. **Engagement** — User retention, total actions, active users, avg cumulative actions per user (all by cohort)
2. **Revenue & GP** — Monthly revenue/GP layer cakes, lifetime $/customer, active paying customers, paying customer retention
3. **CAC/LTV Payback** — CAC per cohort, cumulative GP vs spend, payback period, time to 2x/3x
4. **Retention** — Toggle between "active in that period" vs "active in any future period" counting

### Advanced
- GP → CAC layer cake (cumulative payback progression)
- Dollar retention / net revenue retention (NRR)
- Customer concentration (Pareto / top 100)
- Unique active customers over time (new vs returning)
