# Cohort Analysis

A Claude Code plugin that generates interactive cohort analysis dashboards. Point it at a CSV, Excel file, or PostgreSQL database and get live charts — engagement retention, revenue/GP cohorts, CAC/LTV payback, and more.

Built by [Fergana Labs](https://ferganalabs.com).

## Install

Add the Fergana Labs marketplace and install the plugin:

```
/plugin marketplace add Fergana-Labs/fergana-plugins
/plugin install cohort-analysis@fergana-labs
```

Then run the skill:

```
/cohort-analysis
```

Claude Code will walk you through connecting your data and launch the dashboard.

## Quick Start (without plugin)

If you prefer to clone and run directly:

```bash
git clone https://github.com/Fergana-Labs/cohort-analysis.git
cd cohort-analysis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app/server.py
# Open http://localhost:8000
```

## Using with Claude Code

After installing the plugin, paste one of these prompts:

**For CSV/Excel files:**
```
I want to analyze my cohort data.
Here's my data file: [filename.csv or filename.xlsx].
Please run /cohort-analysis to set it up and launch the dashboard.
```

**For a PostgreSQL database:**
```
I want to analyze my cohort data.
My database connection string is: postgresql://user:pass@host:port/dbname
Please run /cohort-analysis to explore my schema, set it up, and launch the dashboard.
```

Claude Code will:
1. Detect your data files or explore your database schema
2. Ask you to confirm column mappings (customer ID, dates, revenue, etc.)
3. Ask about accrual vs cash revenue recognition if relevant
4. Calculate cohort dates from each customer's first appearance (default)
5. Generate the config, install dependencies, and launch the dashboard at http://localhost:8000

## Multiple Analyses

You can run analyses for different companies or products side by side. Each time you run the skill, it asks for a profile name. Switch between profiles using the dropdown in the dashboard header.

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
If your data doesn't have an explicit cohort date column, the tool calculates it automatically as each customer's **first appearance date**, floored to the start of the month.

## Supported Data Sources
- **CSV** files (`.csv`)
- **Excel** files (`.xlsx`) — including multi-sheet workbooks
- **PostgreSQL** — provide a connection string (`postgresql://user:pass@host:port/db`)

## Views

### Core
1. **Engagement** — User retention, total actions, active users, avg cumulative actions per user (all by cohort)
2. **Revenue & GP** — Monthly revenue/GP layer cakes, lifetime $/customer, GP/user, active paying customers, paying customer retention
3. **CAC/LTV Payback** — CAC per cohort, cumulative GP vs spend, payback triangles, time to 2x/3x

### Advanced
- GP → CAC layer cake (cumulative payback progression)
- Dollar retention / net revenue retention (NRR)
- Customer concentration (Pareto / top 100)
- Unique active customers over time (new vs returning)

## Retention Modes

Both engagement and revenue retention charts support two counting methods:
- **Standard** — was the user active in that specific period?
- **Future** — was the user active in that period or any later period?

Toggle between them directly on the retention charts.
