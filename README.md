# Cohort Analysis

A Claude Code plugin that generates interactive cohort analysis dashboards. Point it at a CSV, Excel file, or PostgreSQL database and get live charts — engagement retention, revenue/GP cohorts, CAC/LTV payback, and more.

Built by [Fergana Labs](https://ferganalabs.com).

Note: Runs locally on your computer. Requirements are Python and Claude Code (preferred but other coding agent like Codex or Cursor can work as well).

## Install

**Step 1:** Add the Fergana Labs marketplace:
```
/plugin marketplace add Fergana-Labs/fergana-plugins
```

**Step 2:** Install the plugin:
```
/plugin install cohort-analysis@fergana-labs
```

**Step 3:** Restart Claude Code, then run the skill:
```
/cohort-analysis
```

Claude Code will walk you through connecting your data and launch the dashboard.

## Tips

- **Something not working?** Just tell Claude Code what's wrong — it can debug and fix issues on the fly.
- **Want a different view or chart?** Ask Claude Code to add, modify, or rearrange dashboard views to fit your needs.
- **Data not mapping correctly?** Describe your columns and Claude Code will re-map them.
- **Need help interpreting results?** Ask Claude Code to explain what the charts mean for your business.
- **Want to connect a different data source?** Just run `/cohort-analysis` again with a new file or database.

Claude Code has full context on how this plugin works — if you get stuck at any point, just ask it.

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

## Technical Details

### Architecture

The plugin is a three-tier system: a React frontend, a FastAPI backend, and a Python data processing pipeline.

```
bling_cohorts/
├── app/
│   ├── server.py            # FastAPI server & API routes
│   ├── cohort_engine.py     # Core analytics computation
│   ├── data_processor.py    # Data loading & normalization
│   └── static/
│       └── index.html       # Self-contained React SPA
├── data/
│   ├── config.json          # Default config
│   └── configs/             # Named profile configs
├── skills/
│   └── cohort-analysis/
│       └── SKILL.md         # Claude Code skill definition
├── .claude-plugin/
│   └── plugin.json          # Plugin metadata
├── .claude/
│   └── settings.local.json  # Claude Code permissions
└── requirements.txt         # Python dependencies
```

### How It Works

1. **Skill invocation** — When you run `/cohort-analysis`, Claude Code follows the interactive guide in `skills/cohort-analysis/SKILL.md`. It walks through data source detection, column mapping, accrual vs cash recognition, cohort date calculation, and profile naming.

2. **Config generation** — A JSON config is written to `data/configs/{profile}.json` mapping your source columns to the internal schema (`customer_id`, `action_month`, `revenue`, `gp`, etc.).

3. **Data loading** — On server startup, `data_processor.py` loads your data (CSV, Excel, or PostgreSQL), parses dates (including Excel serial numbers), buckets them to month or week, and calculates cohort dates as each customer's first appearance.

4. **Computation** — `cohort_engine.py` computes all metrics in-memory from normalized DataFrames: retention rates, revenue/GP layer cakes, CAC payback milestones, dollar retention, customer concentration, and more.

5. **API serving** — `server.py` exposes endpoints like `/api/engagement`, `/api/revenue`, `/api/cac`, `/api/retention`, etc. Results are cached in memory after initial load; profile switches trigger a reload via `/api/reload`.

6. **Frontend rendering** — `index.html` is a single-file React app (no build step) using Recharts for charts and Tailwind for styling, all loaded via CDN. It fetches from the API endpoints and renders interactive charts with hover highlighting, legend toggling, and cohort filtering.

### API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/api/config` | Current config |
| `/api/profiles` | List available profiles |
| `/api/reload` | Switch profile & reload data |
| `/api/engagement` | Engagement cohort analysis |
| `/api/revenue` | Revenue & GP cohorts |
| `/api/cac` | CAC/LTV payback analysis |
| `/api/retention` | Retention rates (standard & future) |
| `/api/layer-cake` | Cumulative GP vs CAC payback |
| `/api/dollar-retention` | Net revenue retention |
| `/api/customers` | Customer concentration (Pareto) |
| `/api/active-customers` | New vs returning active users |

All endpoints accept query parameters for filtering: `period` (month/week), `include_current`, `start`, `end`, `mode` (standard/future), `basis` (accrual/cash).

### Config Schema

```json
{
  "period": "month",
  "engagement": {
    "source_type": "file",
    "filepath": "data.xlsx",
    "sheet": "Engagement",
    "calculate_cohort": true,
    "column_map": {
      "customer_id": "User ID",
      "action_month": "Event Date",
      "event_type": "Event",
      "event_count": "Count"
    }
  },
  "revenue": {
    "source_type": "file",
    "filepath": "data.xlsx",
    "sheet": "Accrual",
    "cash_sheet": "Cash",
    "calculate_cohort": true,
    "column_map": {
      "customer_id": "Customer ID",
      "action_month": "Date",
      "revenue": "Amount",
      "gp": "Gross Profit"
    }
  },
  "inputs": {
    "filepath": "data.xlsx",
    "sheet": "Inputs"
  }
}
```

For PostgreSQL, replace `filepath`/`sheet` with `connection_string` and `query`.

### Dependencies

**Python:** FastAPI, Uvicorn, Pandas, openpyxl, psycopg2-binary

**Frontend (CDN):** React 18, Recharts, Tailwind CSS, Babel

### Extending

- **New endpoint:** Add a compute function in `cohort_engine.py`, wire it in `server.py`, add a React component in `index.html`.
- **New data source:** Implement a reader in `data_processor.py` that returns a normalized DataFrame with the required columns.
- **Styling:** Modify the `COHORT_COLORS` array or Tailwind classes in `index.html`.
