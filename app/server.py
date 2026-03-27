"""
FastAPI server: serves API endpoints + static frontend.
"""

import os
import sys
from pathlib import Path

from contextlib import asynccontextmanager

import pandas as pd
import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data_processor import (
    load_config, load_engagement_data, load_revenue_data, load_inputs,
    list_profiles, rebucket_to_weeks, exclude_current_period,
)
from app import cohort_engine


@asynccontextmanager
async def lifespan(app):
    _load_data()
    yield

app = FastAPI(title="Cohort Analysis", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Data cache — loaded once on startup, reloaded on profile switch
# ---------------------------------------------------------------------------

_cache = {
    "config": {},
    "engagement_df": None,
    "revenue_df": None,
    "revenue_cash_df": None,
    "inputs": {},
}


def _apply_inputs_margin(cache: dict):
    """If revenue data has no GP/margin_pct columns, apply gross margin from Inputs sheet."""
    gross_margin = cache.get("inputs", {}).get("gross_margin", {})
    if not gross_margin:
        return
    for key in ("revenue_df", "revenue_cash_df"):
        df = cache.get(key)
        if df is None or "gp" in df.columns or "margin_pct" in df.columns:
            continue
        if "revenue" not in df.columns or "action_month" not in df.columns:
            continue
        df = df.copy()
        df["margin_pct"] = df["action_month"].apply(
            lambda d: gross_margin.get(d.strftime("%Y-%m-01") if hasattr(d, "strftime") else str(d), 0)
        )
        df["gp"] = df["revenue"] * df["margin_pct"]
        cache[key] = df


def _load_data(profile: str = None):
    """Load all data based on config profile."""
    config = load_config(profile)
    _cache["config"] = config
    _cache["engagement_df"] = None
    _cache["revenue_df"] = None
    _cache["revenue_cash_df"] = None
    _cache["inputs"] = {}

    try:
        _cache["engagement_df"] = load_engagement_data(config)
    except Exception as e:
        print(f"Warning: Could not load engagement data: {e}")

    try:
        _cache["revenue_df"] = load_revenue_data(config, basis="accrual")
    except Exception as e:
        print(f"Warning: Could not load revenue (accrual) data: {e}")

    try:
        _cache["revenue_cash_df"] = load_revenue_data(config, basis="cash")
    except Exception as e:
        print(f"Warning: Could not load revenue (cash) data: {e}")

    try:
        _cache["inputs"] = load_inputs(config)
    except Exception as e:
        print(f"Warning: Could not load inputs: {e}")

    # Apply inputs gross margin to revenue data if GP is missing
    _apply_inputs_margin(_cache)

    profile_name = config.get("_profile", "default")
    print(f"Data loaded (profile: {profile_name}).")
    if _cache["engagement_df"] is not None:
        print(f"  Engagement: {len(_cache['engagement_df'])} rows, "
              f"{_cache['engagement_df']['customer_id'].nunique()} users")
    if _cache["revenue_df"] is not None:
        print(f"  Revenue (accrual): {len(_cache['revenue_df'])} rows, "
              f"{_cache['revenue_df']['customer_id'].nunique()} customers")
    if _cache["revenue_cash_df"] is not None:
        print(f"  Revenue (cash): {len(_cache['revenue_cash_df'])} rows")




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_period() -> str:
    """Get default period from config."""
    return _cache.get("config", {}).get("period", "month")


def _prepare_df(df, period: str = None, include_current: bool = True):
    """Apply current-period exclusion. Period bucketing is done at load time."""
    if df is None:
        return None
    if period is None:
        period = _default_period()
    if not include_current:
        df = exclude_current_period(df, period)
    return df


# ---------------------------------------------------------------------------
# API: Config
# ---------------------------------------------------------------------------

@app.get("/api/config")
def get_config():
    return _cache["config"]


@app.get("/api/profiles")
def get_profiles():
    """List available config profiles."""
    profiles = list_profiles()
    current = _cache["config"].get("_profile", "default")
    return {"profiles": profiles, "current": current}


@app.post("/api/reload")
def reload_data(profile: str = Query(None)):
    """Reload data, optionally switching profile."""
    _load_data(profile)
    return {"status": "ok", "profile": _cache["config"].get("_profile", "default")}


# ---------------------------------------------------------------------------
# API: Engagement
# ---------------------------------------------------------------------------

@app.get("/api/engagement")
def get_engagement(
    mode: str = Query("standard", pattern="^(standard|future)$"),
    period: str = Query("month", pattern="^(month|week)$"),
    include_current: bool = Query(True),
    start: str = Query(None),
    end: str = Query(None),
):
    df = _prepare_df(_cache["engagement_df"], period, include_current)
    if df is None:
        return JSONResponse({"error": "No engagement data loaded"}, status_code=404)
    return cohort_engine.compute_engagement(df, mode=mode, start=start, end=end)


# ---------------------------------------------------------------------------
# API: Revenue & GP
# ---------------------------------------------------------------------------

@app.get("/api/revenue")
def get_revenue(
    basis: str = Query("accrual", pattern="^(accrual|cash)$"),
    metric: str = Query("revenue", pattern="^(revenue|gp)$"),
    period: str = Query("month", pattern="^(month|week)$"),
    include_current: bool = Query(True),
    start: str = Query(None),
    end: str = Query(None),
):
    df = _cache["revenue_cash_df"] if basis == "cash" else _cache["revenue_df"]
    df = _prepare_df(df, period, include_current)
    if df is None:
        return JSONResponse({"error": f"No revenue ({basis}) data loaded"}, status_code=404)
    return cohort_engine.compute_revenue_gp(df, metric=metric, start=start, end=end)


# ---------------------------------------------------------------------------
# API: CAC / LTV Payback
# ---------------------------------------------------------------------------

@app.get("/api/cac")
def get_cac(
    period: str = Query("month", pattern="^(month|week)$"),
    include_current: bool = Query(True),
    start: str = Query(None),
    end: str = Query(None),
):
    df = _prepare_df(_cache["revenue_df"], period, include_current)
    if df is None:
        return JSONResponse({"error": "No revenue data loaded"}, status_code=404)
    return cohort_engine.compute_cac_payback(df, _cache["inputs"], start=start, end=end)


# ---------------------------------------------------------------------------
# API: Retention
# ---------------------------------------------------------------------------

@app.get("/api/retention")
def get_retention(
    mode: str = Query("standard", pattern="^(standard|future)$"),
    type: str = Query("engagement", pattern="^(engagement|revenue)$"),
    period: str = Query("month", pattern="^(month|week)$"),
    include_current: bool = Query(True),
    start: str = Query(None),
    end: str = Query(None),
):
    if type == "revenue":
        df = _cache["revenue_df"]
    else:
        df = _cache["engagement_df"]
    df = _prepare_df(df, period, include_current)

    if df is None:
        return JSONResponse({"error": f"No {type} data loaded"}, status_code=404)

    return cohort_engine.compute_retention(df, mode=mode, data_type=type, start=start, end=end)


# ---------------------------------------------------------------------------
# API: Advanced — GP → CAC Layer Cake
# ---------------------------------------------------------------------------

@app.get("/api/layer-cake")
def get_layer_cake(
    period: str = Query("month", pattern="^(month|week)$"),
    include_current: bool = Query(True),
    start: str = Query(None),
    end: str = Query(None),
):
    df = _prepare_df(_cache["revenue_df"], period, include_current)
    if df is None:
        return JSONResponse({"error": "No revenue data loaded"}, status_code=404)
    return cohort_engine.compute_gp_cac_layer_cake(df, _cache["inputs"], start=start, end=end)


# ---------------------------------------------------------------------------
# API: Advanced — Dollar Retention
# ---------------------------------------------------------------------------

@app.get("/api/dollar-retention")
def get_dollar_retention(
    basis: str = Query("accrual", pattern="^(accrual|cash)$"),
    period: str = Query("month", pattern="^(month|week)$"),
    include_current: bool = Query(True),
    start: str = Query(None),
    end: str = Query(None),
):
    df = _cache["revenue_cash_df"] if basis == "cash" else _cache["revenue_df"]
    df = _prepare_df(df, period, include_current)
    if df is None:
        return JSONResponse({"error": "No revenue data loaded"}, status_code=404)
    return cohort_engine.compute_dollar_retention(df, start=start, end=end)


# ---------------------------------------------------------------------------
# API: Advanced — Customer Concentration
# ---------------------------------------------------------------------------

@app.get("/api/customers")
def get_customers(
    type: str = Query("revenue", pattern="^(revenue|engagement)$"),
    period: str = Query("month", pattern="^(month|week)$"),
    include_current: bool = Query(True),
    start: str = Query(None),
    end: str = Query(None),
):
    if type == "engagement":
        df = _cache["engagement_df"]
        value_col = "event_count"
    else:
        df = _cache["revenue_df"]
        value_col = "revenue"
    df = _prepare_df(df, period, include_current)

    if df is None:
        return JSONResponse({"error": f"No {type} data loaded"}, status_code=404)

    return cohort_engine.compute_customer_concentration(df, value_col=value_col, start=start, end=end)


# ---------------------------------------------------------------------------
# API: Advanced — Active Customers Over Time
# ---------------------------------------------------------------------------

@app.get("/api/active-customers")
def get_active_customers(
    basis: str = Query("accrual", pattern="^(accrual|cash)$"),
    period: str = Query("month", pattern="^(month|week)$"),
    include_current: bool = Query(True),
    start: str = Query(None),
    end: str = Query(None),
):
    df = _cache["revenue_cash_df"] if basis == "cash" else _cache["revenue_df"]
    if df is None:
        df = _cache["engagement_df"]
    df = _prepare_df(df, period, include_current)
    if df is None:
        return JSONResponse({"error": "No data loaded"}, status_code=404)

    return cohort_engine.compute_active_customers_over_time(df, start=start, end=end)


# ---------------------------------------------------------------------------
# Static files — serve index.html
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


# Mount static dir for any additional assets
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting Cohort Analysis server on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
