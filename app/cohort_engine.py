"""
Cohort computation engine: engagement, revenue/GP, CAC/LTV, retention modes, advanced views.
"""

from datetime import datetime
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _month_offset(cohort_month: pd.Timestamp, action_month: pd.Timestamp) -> int:
    """Number of months between cohort start and action month."""
    return (action_month.year - cohort_month.year) * 12 + (action_month.month - cohort_month.month)


def _filter_date_range(df: pd.DataFrame, start: str | None, end: str | None,
                       cohort_col: str = "cohort_month") -> pd.DataFrame:
    """Filter dataframe by cohort date range."""
    if start:
        df = df[df[cohort_col] >= pd.Timestamp(start)]
    if end:
        df = df[df[cohort_col] <= pd.Timestamp(end)]
    return df


def _cohort_sizes(df: pd.DataFrame) -> pd.DataFrame:
    """Get cohort sizes (distinct customers per cohort_month)."""
    return df.groupby("cohort_month")["customer_id"].nunique().reset_index()


def _month_label(ts: pd.Timestamp) -> str:
    """Label for a period. Monthly: Mar'24. Weekly: 3/4'24."""
    if ts.day == 1:
        return ts.strftime("%b'%y")
    return ts.strftime("%-m/%-d'%y")


def _month_key(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-01")


# ---------------------------------------------------------------------------
# View 1: User Engagement Cohorts
# ---------------------------------------------------------------------------

def compute_engagement(df: pd.DataFrame, mode: str = "standard",
                       start: str = None, end: str = None) -> dict:
    """
    Compute engagement cohort data.

    Returns:
        cohorts: [{month, label, size, retention: [...], cumulative_actions: [...]}]
        max_offsets: int
        actions_by_month: [{month, label, cohort1: n, ...}]  (layer cake)
        active_by_month: [{month, label, cohort1: n, ...}]   (layer cake)
    """
    df = _filter_date_range(df, start, end)
    if df.empty:
        return {"cohorts": [], "max_offsets": 0, "actions_by_month": [], "active_by_month": []}

    cohort_months = sorted(df["cohort_month"].unique())
    all_action_months = sorted(df["action_month"].unique())

    # Cohort sizes
    sizes = df.groupby("cohort_month")["customer_id"].nunique().to_dict()

    # Max offset
    if len(cohort_months) > 0 and len(all_action_months) > 0:
        max_offset = _month_offset(cohort_months[0], all_action_months[-1])
    else:
        max_offset = 0

    cohorts = []
    for cm in cohort_months:
        cohort_df = df[df["cohort_month"] == cm]
        size = sizes[cm]
        cm_label = _month_label(cm)

        # Per-offset metrics
        retention = []
        cumulative_actions = []
        cum_total = 0

        for offset in range(max_offset + 1):
            target_month = cm + pd.DateOffset(months=offset)
            target_month = pd.Timestamp(target_month.year, target_month.month, 1)

            if mode == "future":
                # Active in this month or any future month
                active_df = cohort_df[cohort_df["action_month"] >= target_month]
            else:
                # Active in exactly this month
                active_df = cohort_df[cohort_df["action_month"] == target_month]

            active_users = active_df["customer_id"].nunique()
            ret_pct = round(active_users / size * 100, 1) if size > 0 else 0

            # For cumulative actions, always use exact month (non-cumulative action count
            # is summed cumulatively over offsets)
            exact_month_df = cohort_df[cohort_df["action_month"] == target_month]
            month_actions = exact_month_df["event_count"].sum() if "event_count" in exact_month_df.columns else len(exact_month_df)
            cum_total += month_actions
            avg_cum = round(cum_total / size, 1) if size > 0 else 0

            # Check if this offset is in the future (beyond available data)
            if target_month > all_action_months[-1]:
                retention.append(None)
                cumulative_actions.append(None)
            else:
                retention.append(ret_pct)
                cumulative_actions.append(avg_cum)

        cohorts.append({
            "month": _month_key(cm),
            "label": cm_label,
            "size": int(size),
            "retention": retention,
            "cumulative_actions": cumulative_actions,
        })

    # Layer cake data: actions by calendar month
    actions_by_month = []
    active_by_month = []
    for am in all_action_months:
        am_label = _month_label(am)
        action_point = {"month": _month_key(am), "label": am_label}
        active_point = {"month": _month_key(am), "label": am_label}

        for cm in cohort_months:
            cm_key = _month_key(cm)
            cohort_am_df = df[(df["cohort_month"] == cm) & (df["action_month"] == am)]
            action_point[cm_key] = int(cohort_am_df["event_count"].sum()) if "event_count" in cohort_am_df.columns else len(cohort_am_df)
            active_point[cm_key] = int(cohort_am_df["customer_id"].nunique())

        actions_by_month.append(action_point)
        active_by_month.append(active_point)

    return {
        "cohorts": cohorts,
        "max_offsets": max_offset,
        "actions_by_month": actions_by_month,
        "active_by_month": active_by_month,
    }


# ---------------------------------------------------------------------------
# View 2: Revenue & GP Cohorts
# ---------------------------------------------------------------------------

def compute_revenue_gp(df: pd.DataFrame, metric: str = "revenue",
                       start: str = None, end: str = None) -> dict:
    """
    Compute revenue/GP cohort data.

    Returns:
        cohorts: [{month, label, size,
                   monthly_values: [...],      (non-cumulative per month offset)
                   lifetime_per_user: [...],   (cumulative / cohort_size)
                   active_customers: [...],    (distinct customers per offset)
                   paying_retention: [...]}]   (% of cohort paying per offset)
        max_offsets: int
        value_by_month: [{month, label, cohort1: $, ...}]  (revenue/GP layer cake)
        customers_by_month: [{month, label, cohort1: n, ...}]  (active customers layer cake)
    """
    df = _filter_date_range(df, start, end)
    if df.empty:
        return {"cohorts": [], "max_offsets": 0, "value_by_month": [], "customers_by_month": []}

    value_col = "gp" if metric == "gp" else "revenue"
    if value_col not in df.columns:
        return {"cohorts": [], "max_offsets": 0, "value_by_month": [], "customers_by_month": [],
                "error": f"Column '{value_col}' not found in data"}

    cohort_months = sorted(df["cohort_month"].unique())
    all_action_months = sorted(df["action_month"].unique())
    sizes = df.groupby("cohort_month")["customer_id"].nunique().to_dict()

    max_offset = _month_offset(cohort_months[0], all_action_months[-1]) if cohort_months and all_action_months else 0

    cohorts = []
    for cm in cohort_months:
        cohort_df = df[df["cohort_month"] == cm]
        size = sizes[cm]

        monthly_values = []
        lifetime_per_user = []
        active_customers = []
        paying_retention = []
        cum_value = 0

        for offset in range(max_offset + 1):
            target_month = cm + pd.DateOffset(months=offset)
            target_month = pd.Timestamp(target_month.year, target_month.month, 1)

            month_df = cohort_df[cohort_df["action_month"] == target_month]

            if target_month > all_action_months[-1]:
                monthly_values.append(None)
                lifetime_per_user.append(None)
                active_customers.append(None)
                paying_retention.append(None)
            else:
                month_val = float(month_df[value_col].sum())
                cum_value += month_val
                active = int(month_df["customer_id"].nunique())
                ret_pct = round(active / size * 100, 1) if size > 0 else 0

                monthly_values.append(round(month_val, 2))
                lifetime_per_user.append(round(cum_value / size, 2) if size > 0 else 0)
                active_customers.append(active)
                paying_retention.append(ret_pct)

        cohorts.append({
            "month": _month_key(cm),
            "label": _month_label(cm),
            "size": int(size),
            "monthly_values": monthly_values,
            "lifetime_per_user": lifetime_per_user,
            "active_customers": active_customers,
            "paying_retention": paying_retention,
        })

    # Layer cake: value by calendar month
    value_by_month = []
    customers_by_month = []
    for am in all_action_months:
        val_point = {"month": _month_key(am), "label": _month_label(am)}
        cust_point = {"month": _month_key(am), "label": _month_label(am)}

        for cm in cohort_months:
            cm_key = _month_key(cm)
            cohort_am_df = df[(df["cohort_month"] == cm) & (df["action_month"] == am)]
            val_point[cm_key] = round(float(cohort_am_df[value_col].sum()), 2)
            cust_point[cm_key] = int(cohort_am_df["customer_id"].nunique())

        value_by_month.append(val_point)
        customers_by_month.append(cust_point)

    return {
        "cohorts": cohorts,
        "max_offsets": max_offset,
        "value_by_month": value_by_month,
        "customers_by_month": customers_by_month,
    }


# ---------------------------------------------------------------------------
# View 3: CAC / LTV Payback
# ---------------------------------------------------------------------------

def compute_cac_payback(df: pd.DataFrame, inputs: dict,
                        start: str = None, end: str = None) -> dict:
    """
    Compute CAC/LTV payback data.

    inputs: {"sm_spend": {month_key: amount}, "gross_margin": {month_key: pct}}

    Returns:
        cohorts: [{month, label, customers_added, sm_spend, cac,
                   cumulative_gp: [...], payback_month, time_to_2x, time_to_3x}]
    """
    df = _filter_date_range(df, start, end)
    if df.empty:
        return {"cohorts": []}

    sm_spend = inputs.get("sm_spend", {})

    # Ensure GP column exists
    if "gp" not in df.columns:
        if "revenue" in df.columns and "margin_pct" in df.columns:
            df = df.copy()
            df["gp"] = df["revenue"] * df["margin_pct"]
        else:
            return {"cohorts": [], "error": "Need GP or (revenue + margin) columns"}

    cohort_months = sorted(df["cohort_month"].unique())
    all_action_months = sorted(df["action_month"].unique())
    max_offset = _month_offset(cohort_months[0], all_action_months[-1]) if cohort_months and all_action_months else 0

    cohorts = []
    for cm in cohort_months:
        cohort_df = df[df["cohort_month"] == cm]
        cm_key = _month_key(cm)

        customers_added = int(cohort_df["customer_id"].nunique())
        spend = sm_spend.get(cm_key, 0)
        cac = round(spend / customers_added, 2) if customers_added > 0 else 0

        cumulative_gp = []
        gp_per_cust_net_cac = []  # Triangle 1: (cumulative GP / customers) - CAC
        gp_cac_ratio = []          # Triangle 2: cumulative GP / total S&M spend
        cum_gp = 0
        payback_month = None
        time_to_2x = None
        time_to_3x = None

        for offset in range(max_offset + 1):
            target_month = cm + pd.DateOffset(months=offset)
            target_month = pd.Timestamp(target_month.year, target_month.month, 1)

            if target_month > all_action_months[-1]:
                cumulative_gp.append(None)
                gp_per_cust_net_cac.append(None)
                gp_cac_ratio.append(None)
            else:
                month_df = cohort_df[cohort_df["action_month"] == target_month]
                cum_gp += float(month_df["gp"].sum())
                cumulative_gp.append(round(cum_gp, 2))

                # Triangle 1: cumulative GP per customer minus CAC
                gp_per_cust = cum_gp / customers_added if customers_added > 0 else 0
                net_cac = round(gp_per_cust - cac, 2)
                gp_per_cust_net_cac.append(net_cac)

                # Triangle 2: cumulative GP / total S&M spend (ratio)
                ratio = round(cum_gp / spend, 4) if spend > 0 else None
                gp_cac_ratio.append(ratio)

                # Check payback milestones
                if spend > 0:
                    if payback_month is None and cum_gp >= spend:
                        payback_month = offset
                    if time_to_2x is None and cum_gp >= spend * 2:
                        time_to_2x = offset
                    if time_to_3x is None and cum_gp >= spend * 3:
                        time_to_3x = offset

        cohorts.append({
            "month": cm_key,
            "label": _month_label(cm),
            "customers_added": customers_added,
            "sm_spend": round(spend, 2),
            "cac": cac,
            "cumulative_gp": cumulative_gp,
            "gp_per_cust_net_cac": gp_per_cust_net_cac,
            "gp_cac_ratio": gp_cac_ratio,
            "payback_month": payback_month,
            "time_to_2x": time_to_2x,
            "time_to_3x": time_to_3x,
        })

    return {"cohorts": cohorts, "max_offsets": max_offset}


# ---------------------------------------------------------------------------
# View 4: Retention with toggle (standard vs future)
# ---------------------------------------------------------------------------

def compute_retention(df: pd.DataFrame, mode: str = "standard",
                      data_type: str = "engagement",
                      start: str = None, end: str = None) -> dict:
    """
    Compute retention with standard or future mode.

    For engagement: "active" = had any event
    For revenue: "active" = had any revenue > 0

    Returns:
        cohorts: [{month, label, size, standard: [...], future: [...]}]
        max_offsets: int
    """
    df = _filter_date_range(df, start, end)
    if df.empty:
        return {"cohorts": [], "max_offsets": 0}

    # For revenue, filter to positive revenue
    if data_type == "revenue" and "revenue" in df.columns:
        active_df = df[df["revenue"] > 0]
    else:
        active_df = df

    cohort_months = sorted(active_df["cohort_month"].unique())
    all_action_months = sorted(active_df["action_month"].unique())
    sizes = active_df.groupby("cohort_month")["customer_id"].nunique().to_dict()

    max_offset = _month_offset(cohort_months[0], all_action_months[-1]) if cohort_months and all_action_months else 0

    cohorts = []
    for cm in cohort_months:
        cohort_df = active_df[active_df["cohort_month"] == cm]
        size = sizes[cm]

        standard_retention = []
        future_retention = []

        for offset in range(max_offset + 1):
            target_month = cm + pd.DateOffset(months=offset)
            target_month = pd.Timestamp(target_month.year, target_month.month, 1)

            if target_month > all_action_months[-1]:
                standard_retention.append(None)
                future_retention.append(None)
            else:
                # Standard: active in exactly this month
                std_active = cohort_df[cohort_df["action_month"] == target_month]["customer_id"].nunique()
                standard_retention.append(round(std_active / size * 100, 1) if size > 0 else 0)

                # Future: active in this month or any later
                fut_active = cohort_df[cohort_df["action_month"] >= target_month]["customer_id"].nunique()
                future_retention.append(round(fut_active / size * 100, 1) if size > 0 else 0)

        cohorts.append({
            "month": _month_key(cm),
            "label": _month_label(cm),
            "size": int(size),
            "standard": standard_retention,
            "future": future_retention,
        })

    return {"cohorts": cohorts, "max_offsets": max_offset}


# ---------------------------------------------------------------------------
# Advanced: GP → CAC Layer Cake
# ---------------------------------------------------------------------------

def compute_gp_cac_layer_cake(df: pd.DataFrame, inputs: dict,
                              start: str = None, end: str = None) -> dict:
    """Cumulative GP / CAC ratio by cohort over time."""
    df = _filter_date_range(df, start, end)
    if df.empty:
        return {"cohorts": []}

    sm_spend = inputs.get("sm_spend", {})

    if "gp" not in df.columns:
        if "revenue" in df.columns and "margin_pct" in df.columns:
            df = df.copy()
            df["gp"] = df["revenue"] * df["margin_pct"]
        else:
            return {"cohorts": [], "error": "Need GP data"}

    cohort_months = sorted(df["cohort_month"].unique())
    all_action_months = sorted(df["action_month"].unique())
    max_offset = _month_offset(cohort_months[0], all_action_months[-1]) if cohort_months and all_action_months else 0

    cohorts = []
    for cm in cohort_months:
        cohort_df = df[df["cohort_month"] == cm]
        cm_key = _month_key(cm)
        spend = sm_spend.get(cm_key, 0)

        gp_by_offset = []
        cum_gp = 0

        for offset in range(max_offset + 1):
            target_month = cm + pd.DateOffset(months=offset)
            target_month = pd.Timestamp(target_month.year, target_month.month, 1)

            if target_month > all_action_months[-1]:
                gp_by_offset.append(None)
            else:
                month_df = cohort_df[cohort_df["action_month"] == target_month]
                cum_gp += float(month_df["gp"].sum())
                ratio = round(cum_gp / spend, 2) if spend > 0 else None
                gp_by_offset.append({"cumulative_gp": round(cum_gp, 2), "ratio": ratio})

        cohorts.append({
            "month": cm_key,
            "label": _month_label(cm),
            "sm_spend": round(spend, 2),
            "gp_by_offset": gp_by_offset,
        })

    return {"cohorts": cohorts, "max_offsets": max_offset}


# ---------------------------------------------------------------------------
# Advanced: Dollar Retention / NRR
# ---------------------------------------------------------------------------

def compute_dollar_retention(df: pd.DataFrame,
                             start: str = None, end: str = None) -> dict:
    """Net revenue retention per cohort."""
    df = _filter_date_range(df, start, end)
    if df.empty or "revenue" not in df.columns:
        return {"cohorts": [], "max_offsets": 0, "revenue_by_month": []}

    cohort_months = sorted(df["cohort_month"].unique())
    all_action_months = sorted(df["action_month"].unique())
    max_offset = _month_offset(cohort_months[0], all_action_months[-1]) if cohort_months and all_action_months else 0

    cohorts = []
    for cm in cohort_months:
        cohort_df = df[df["cohort_month"] == cm]

        # Month 0 revenue (baseline)
        m0_revenue = float(cohort_df[cohort_df["action_month"] == cm]["revenue"].sum())

        nrr = []
        for offset in range(max_offset + 1):
            target_month = cm + pd.DateOffset(months=offset)
            target_month = pd.Timestamp(target_month.year, target_month.month, 1)

            if target_month > all_action_months[-1]:
                nrr.append(None)
            else:
                month_rev = float(cohort_df[cohort_df["action_month"] == target_month]["revenue"].sum())
                pct = round(month_rev / m0_revenue * 100, 1) if m0_revenue > 0 else 0
                nrr.append(pct)

        cohorts.append({
            "month": _month_key(cm),
            "label": _month_label(cm),
            "initial_revenue": round(m0_revenue, 2),
            "nrr": nrr,
        })

    # Revenue layer cake by calendar month
    revenue_by_month = []
    for am in all_action_months:
        point = {"month": _month_key(am), "label": _month_label(am)}
        for cm in cohort_months:
            cm_key = _month_key(cm)
            val = float(df[(df["cohort_month"] == cm) & (df["action_month"] == am)]["revenue"].sum())
            point[cm_key] = round(val, 2)
        revenue_by_month.append(point)

    return {"cohorts": cohorts, "max_offsets": max_offset, "revenue_by_month": revenue_by_month}


# ---------------------------------------------------------------------------
# Advanced: Customer Concentration (Pareto)
# ---------------------------------------------------------------------------

def compute_customer_concentration(df: pd.DataFrame, value_col: str = "revenue",
                                   start: str = None, end: str = None) -> dict:
    """Top customers and Pareto distribution."""
    df = _filter_date_range(df, start, end, cohort_col="cohort_month")

    if value_col not in df.columns:
        if value_col == "revenue":
            value_col = "event_count" if "event_count" in df.columns else None
        if value_col is None:
            return {"top_customers": [], "pareto": []}

    # Aggregate per customer
    customer_totals = df.groupby("customer_id").agg(
        total_value=(value_col, "sum"),
        cohort_month=("cohort_month", "first"),
        months_active=("action_month", "nunique"),
    ).reset_index()

    if "plan" in df.columns:
        plans = df.groupby("customer_id")["plan"].first().reset_index()
        customer_totals = customer_totals.merge(plans, on="customer_id", how="left")

    customer_totals = customer_totals.sort_values("total_value", ascending=False)

    # Top 100
    top_100 = customer_totals.head(100).copy()
    top_100["cohort_label"] = top_100["cohort_month"].apply(
        lambda x: _month_label(x) if pd.notna(x) else ""
    )
    top_customers = top_100[["customer_id", "total_value", "cohort_label", "months_active"]].copy()
    top_customers["total_value"] = top_customers["total_value"].round(2)
    if "plan" in top_100.columns:
        top_customers["plan"] = top_100["plan"].fillna("")
    top_customers = top_customers.fillna("").to_dict("records")

    # Pareto curve
    sorted_vals = customer_totals["total_value"].sort_values(ascending=False).values
    total = sorted_vals.sum()
    cum = np.cumsum(sorted_vals)
    n = len(sorted_vals)
    pareto = []
    # Sample ~100 points for the chart
    step = max(1, n // 100)
    for i in range(0, n, step):
        pareto.append({
            "pct_customers": round((i + 1) / n * 100, 1),
            "pct_value": round(cum[i] / total * 100, 1) if total > 0 else 0,
        })
    if pareto and pareto[-1]["pct_customers"] < 100:
        pareto.append({"pct_customers": 100, "pct_value": 100})

    # Histogram buckets
    vals = customer_totals["total_value"].values
    if len(vals) > 0:
        hist_counts, hist_edges = np.histogram(vals, bins=min(30, len(vals)))
        histogram = [
            {"bin_start": round(float(hist_edges[i]), 2),
             "bin_end": round(float(hist_edges[i + 1]), 2),
             "count": int(hist_counts[i])}
            for i in range(len(hist_counts))
        ]
    else:
        histogram = []

    return {
        "top_customers": top_customers,
        "pareto": pareto,
        "histogram": histogram,
        "total_customers": n,
    }


# ---------------------------------------------------------------------------
# Advanced: Unique Active Customers Over Time
# ---------------------------------------------------------------------------

def compute_active_customers_over_time(df: pd.DataFrame,
                                       start: str = None, end: str = None) -> dict:
    """Active customers by calendar month, split by new vs returning."""
    df = _filter_date_range(df, start, end)
    if df.empty:
        return {"months": [], "months_purchased_histogram": []}

    all_action_months = sorted(df["action_month"].unique())
    cohort_months = sorted(df["cohort_month"].unique())

    # Stacked active customers by cohort
    active_stacked = []
    for am in all_action_months:
        point = {"month": _month_key(am), "label": _month_label(am)}
        for cm in cohort_months:
            cm_key = _month_key(cm)
            active = int(df[(df["cohort_month"] == cm) & (df["action_month"] == am)]["customer_id"].nunique())
            point[cm_key] = active
        active_stacked.append(point)

    # New vs returning by month
    new_vs_returning = []
    for am in all_action_months:
        month_df = df[df["action_month"] == am]
        new_count = int(month_df[month_df["cohort_month"] == am]["customer_id"].nunique())
        total_active = int(month_df["customer_id"].nunique())
        returning_count = total_active - new_count
        new_vs_returning.append({
            "month": _month_key(am),
            "label": _month_label(am),
            "new": new_count,
            "returning": returning_count,
        })

    # Months purchased histogram
    months_per_customer = df.groupby("customer_id")["action_month"].nunique()
    if len(months_per_customer) > 0:
        max_months = int(months_per_customer.max())
        histogram = []
        for m in range(1, max_months + 1):
            count = int((months_per_customer == m).sum())
            histogram.append({"months": m, "count": count})
    else:
        histogram = []

    return {
        "active_stacked": active_stacked,
        "new_vs_returning": new_vs_returning,
        "months_purchased_histogram": histogram,
        "cohort_months": [_month_key(cm) for cm in cohort_months],
    }
