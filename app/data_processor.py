"""
Data processing layer: parse CSV/Excel/DB, normalize columns, calculate cohort dates.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_PATH = DATA_DIR / "config.json"


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def excel_serial_to_date(serial) -> datetime:
    """Convert Excel serial number to Python datetime."""
    try:
        serial = float(serial)
    except (TypeError, ValueError):
        return pd.NaT
    if serial < 1:
        return pd.NaT
    return datetime(1899, 12, 30) + timedelta(days=int(serial))


def parse_date_column(series: pd.Series) -> pd.Series:
    """Auto-detect and convert a date column to datetime.

    Handles: Excel serial numbers, ISO strings, common date formats.
    """
    if series.empty:
        return pd.to_datetime(series)

    sample = series.dropna().iloc[:20]

    # Already datetime
    if pd.api.types.is_datetime64_any_dtype(series):
        return series

    # Check if values look like Excel serial numbers (large-ish floats/ints)
    try:
        numeric = pd.to_numeric(sample, errors="coerce")
        if numeric.notna().all() and (numeric > 30000).all() and (numeric < 100000).all():
            return series.apply(excel_serial_to_date)
    except Exception:
        pass

    # Try pandas automatic parsing
    try:
        return pd.to_datetime(series, infer_datetime_format=True)
    except Exception:
        pass

    # Try common formats
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%m-%d-%Y", "%d-%m-%Y"):
        try:
            return pd.to_datetime(series, format=fmt)
        except Exception:
            continue

    raise ValueError(f"Cannot parse dates from column. Sample values: {sample.tolist()[:5]}")


def floor_to_month(dt_series: pd.Series) -> pd.Series:
    """Floor datetime series to start of month."""
    return dt_series.dt.to_period("M").dt.to_timestamp()


def floor_to_week(dt_series: pd.Series) -> pd.Series:
    """Floor datetime series to start of week (Monday)."""
    return dt_series.dt.to_period("W").dt.start_time


def rebucket_to_weeks(df: pd.DataFrame) -> pd.DataFrame:
    """Re-bucket action_month and cohort_month columns from monthly to weekly."""
    df = df.copy()
    if "action_month" in df.columns:
        df["action_month"] = floor_to_week(df["action_month"])
    if "cohort_month" in df.columns:
        df["cohort_month"] = floor_to_week(df["cohort_month"])
    return df


def exclude_current_period(df: pd.DataFrame, period: str = "month") -> pd.DataFrame:
    """Remove rows from the latest (potentially incomplete) period in the data."""
    if "action_month" not in df.columns or df.empty:
        return df
    latest_period = df["action_month"].max()
    return df[df["action_month"] < latest_period]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIGS_DIR = DATA_DIR / "configs"


def list_profiles() -> list[str]:
    """List available config profiles."""
    profiles = []
    # Single config.json (legacy/default)
    if CONFIG_PATH.exists():
        profiles.append("default")
    # Named configs in data/configs/
    if CONFIGS_DIR.exists():
        for f in sorted(CONFIGS_DIR.glob("*.json")):
            profiles.append(f.stem)
    return profiles


def load_config(profile: str = None) -> dict:
    """Load data config by profile name.

    - None or "default": loads data/config.json
    - Named profile: loads data/configs/{profile}.json
    """
    if profile and profile != "default":
        path = CONFIGS_DIR / f"{profile}.json"
    else:
        path = CONFIG_PATH

    if not path.exists():
        return {}
    with open(path) as f:
        config = json.load(f)
    config["_profile"] = profile or "default"
    return config


def save_config(config: dict, profile: str = None):
    """Save data config. Named profiles go in data/configs/."""
    if profile and profile != "default":
        CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        path = CONFIGS_DIR / f"{profile}.json"
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = CONFIG_PATH

    # Don't save internal keys
    to_save = {k: v for k, v in config.items() if not k.startswith("_")}
    with open(path, "w") as f:
        json.dump(to_save, f, indent=2)


# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------

def read_excel_sheet(filepath: str, sheet_name: str = None) -> pd.DataFrame:
    """Read a sheet from an Excel file."""
    df = pd.read_excel(filepath, sheet_name=sheet_name, engine="openpyxl")
    return df


def read_csv(filepath: str) -> pd.DataFrame:
    """Read a CSV file."""
    return pd.read_csv(filepath)


def read_file(filepath: str, sheet_name: str = None) -> pd.DataFrame:
    """Read data from CSV or Excel file."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in (".xlsx", ".xls"):
        return read_excel_sheet(filepath, sheet_name=sheet_name)
    elif ext == ".csv":
        return read_csv(filepath)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def list_excel_sheets(filepath: str) -> list[str]:
    """List sheet names in an Excel file."""
    import openpyxl
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    names = wb.sheetnames
    wb.close()
    return names


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def read_db(connection_string: str, query: str) -> pd.DataFrame:
    """Read data from a PostgreSQL database."""
    import psycopg2
    conn = psycopg2.connect(connection_string)
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()
    return df


# ---------------------------------------------------------------------------
# Column normalization
# ---------------------------------------------------------------------------

def normalize_dataframe(df: pd.DataFrame, column_map: dict, period: str = "month") -> pd.DataFrame:
    """Rename columns according to the column map and parse dates.

    column_map maps internal names to source column names, e.g.:
        {"customer_id": "Customer ID", "action_month": "Action Month", ...}
    period: "month" or "week" — determines how dates are bucketed.
    """
    # Build rename mapping (source -> internal)
    rename = {}
    for internal_name, source_name in column_map.items():
        if source_name and source_name in df.columns:
            rename[source_name] = internal_name

    out = df.rename(columns=rename)

    # Parse date columns
    for col in ("action_month", "cohort_month", "event_date"):
        if col in out.columns:
            out[col] = parse_date_column(out[col])

    # Floor dates to the configured period
    floor_fn = floor_to_week if period == "week" else floor_to_month

    if "action_month" in out.columns:
        out["action_month"] = floor_fn(out["action_month"])
    if "cohort_month" in out.columns:
        out["cohort_month"] = floor_fn(out["cohort_month"])
    if "event_date" in out.columns and "action_month" not in out.columns:
        out["action_month"] = floor_fn(out["event_date"])

    return out


def calculate_cohort_month(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate cohort_month as first appearance per customer_id, floored to month."""
    if "customer_id" not in df.columns or "action_month" not in df.columns:
        raise ValueError("Need customer_id and action_month columns to calculate cohort_month")

    first_appearance = df.groupby("customer_id")["action_month"].min().reset_index()
    first_appearance.columns = ["customer_id", "cohort_month"]

    if "cohort_month" in df.columns:
        df = df.drop(columns=["cohort_month"])

    return df.merge(first_appearance, on="customer_id", how="left")


# ---------------------------------------------------------------------------
# Inputs / marketing spend
# ---------------------------------------------------------------------------

def read_inputs_sheet(filepath: str, sheet_name: str = "Inputs") -> dict:
    """Read the Inputs sheet for S&M spend and gross margin by month.

    Returns: {
        "sm_spend": {month_str: amount, ...},
        "gross_margin": {month_str: pct, ...}
    }
    """
    df = pd.read_excel(filepath, sheet_name=sheet_name, header=None, engine="openpyxl")

    result = {"sm_spend": {}, "gross_margin": {}}

    if df.shape[0] < 3 or df.shape[1] < 2:
        return result

    # Auto-detect: find the first row that has date-like values in column 1+
    date_row = None
    for row_idx in range(min(5, df.shape[0])):
        val = df.iloc[row_idx, 1] if df.shape[1] > 1 else None
        if pd.notna(val):
            try:
                if isinstance(val, datetime):
                    date_row = row_idx
                    break
                elif isinstance(val, (int, float)) and val > 30000:
                    date_row = row_idx
                    break
                else:
                    pd.to_datetime(val)
                    date_row = row_idx
                    break
            except Exception:
                continue

    if date_row is None:
        return result

    spend_row = date_row + 1
    margin_row = date_row + 2

    for col_idx in range(1, df.shape[1]):
        raw_date = df.iloc[date_row, col_idx]
        if pd.isna(raw_date):
            continue

        # Parse the date
        try:
            if isinstance(raw_date, (int, float)) and raw_date > 30000:
                dt = excel_serial_to_date(raw_date)
            elif isinstance(raw_date, datetime):
                dt = raw_date
            else:
                dt = pd.to_datetime(raw_date)
        except Exception:
            continue

        month_key = dt.strftime("%Y-%m-01")

        # S&M spend
        if df.shape[0] > spend_row:
            val = df.iloc[spend_row, col_idx]
            if pd.notna(val):
                try:
                    result["sm_spend"][month_key] = float(val)
                except (ValueError, TypeError):
                    pass

        # Gross margin
        if df.shape[0] > margin_row:
            val = df.iloc[margin_row, col_idx]
            if pd.notna(val):
                try:
                    result["gross_margin"][month_key] = float(val)
                except (ValueError, TypeError):
                    pass

    return result


# ---------------------------------------------------------------------------
# High-level data loading
# ---------------------------------------------------------------------------

def load_engagement_data(config: dict) -> pd.DataFrame | None:
    """Load and normalize engagement data based on config."""
    eng_config = config.get("engagement")
    if not eng_config:
        return None

    period = config.get("period", "month")
    source = eng_config.get("source_type", "file")

    if source == "db":
        conn_str = eng_config["connection_string"]
        query = eng_config.get("query", """
            SELECT u.id AS customer_id, ae.created_at AS action_month,
                   ae.event AS event_type, 1 AS event_count
            FROM users u
            JOIN analytics_events ae ON ae.user_id = u.id
        """)
        df = read_db(conn_str, query)
    else:
        filepath = eng_config["filepath"]
        sheet = eng_config.get("sheet")
        df = read_file(filepath, sheet_name=sheet)

    col_map = eng_config.get("column_map", {})
    df = normalize_dataframe(df, col_map, period=period)

    # Calculate cohort if needed
    if eng_config.get("calculate_cohort", False) or "cohort_month" not in df.columns:
        df = calculate_cohort_month(df)

    # Ensure event_count exists
    if "event_count" not in df.columns:
        df["event_count"] = 1

    return df


def load_revenue_data(config: dict, basis: str = "accrual") -> pd.DataFrame | None:
    """Load and normalize revenue data based on config."""
    rev_config = config.get("revenue")
    if not rev_config:
        return None

    period = config.get("period", "month")
    source = rev_config.get("source_type", "file")

    if source == "db":
        conn_str = rev_config["connection_string"]
        query = rev_config.get("query")
        df = read_db(conn_str, query)
    else:
        filepath = rev_config["filepath"]
        sheet_key = "cash_sheet" if basis == "cash" else "sheet"
        sheet = rev_config.get(sheet_key, rev_config.get("sheet"))
        df = read_file(filepath, sheet_name=sheet)

    col_map = rev_config.get("column_map", {})
    df = normalize_dataframe(df, col_map, period=period)

    # Calculate cohort if needed
    if rev_config.get("calculate_cohort", False) or "cohort_month" not in df.columns:
        df = calculate_cohort_month(df)

    # Calculate GP if not present but revenue and margin exist
    if "gp" not in df.columns and "revenue" in df.columns and "margin_pct" in df.columns:
        df["gp"] = df["revenue"] * df["margin_pct"]

    return df


def load_inputs(config: dict) -> dict:
    """Load S&M spend and margin inputs."""
    inputs_config = config.get("inputs")
    if not inputs_config:
        return {"sm_spend": {}, "gross_margin": {}}

    filepath = inputs_config["filepath"]
    sheet = inputs_config.get("sheet", "Inputs")
    return read_inputs_sheet(filepath, sheet_name=sheet)
