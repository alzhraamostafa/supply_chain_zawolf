"""Demand loading with a column WHITELIST so leaky columns can never reach a model.
Never added on purpose: ai_predicted_demand_pcs, demand_forecast_variance_pcs,
ai_forecast_accuracy_rate, demand_anomaly_flag (derived from actuals), revenue/profit columns."""
import sqlite3
import numpy as np
import pandas as pd

ALLOWED = ["order_date", "item_code", "customer_id", "m5_calendar_event", "actual_orders_demanded_pcs"]
LEAKY = {"ai_predicted_demand_pcs", "demand_forecast_variance_pcs", "ai_forecast_accuracy_rate",
         "demand_anomaly_flag"}
EVENT_KEYS = {"Summer": "summer", "Ramadan": "ramadan", "Mother": "mothers_day",
              "Eid": "eid", "Friday": "friday_event"}


def load_demand(db_path: str) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cols = ", ".join(f"d.{c}" for c in ALLOWED)
    df = pd.read_sql(
        f"select {cols}, p.family, p.brand from fact_commercial_demand_m5 d "
        "join dim_products p using(item_code)", con)
    assert not (set(df.columns) & LEAKY), "leaky column reached the dataset"
    df["order_date"] = pd.to_datetime(df["order_date"])
    df = df.rename(columns={"actual_orders_demanded_pcs": "y"})
    return df


def event_flags(df: pd.DataFrame) -> pd.DataFrame:
    """One row per calendar date with 0/1 event flags (calendar info is known in advance)."""
    per_date = df.groupby("order_date")["m5_calendar_event"].agg(lambda s: s.mode().iat[0])
    out = pd.DataFrame(index=per_date.index)
    for key, name in EVENT_KEYS.items():
        out[name] = per_date.str.contains(key, regex=False).astype(float)
    return out.reindex(pd.date_range(df.order_date.min(), df.order_date.max())).fillna(0.0)


def weekly_panel(df: pd.DataFrame, level: str):
    """Return (series x full-week matrix, weekly event-share frame). Partial weeks are dropped."""
    df = df.copy()
    df["wk"] = df.order_date.dt.to_period("W-SUN").dt.start_time
    first, last = df.order_date.min(), df.order_date.max()
    weeks = sorted(df.wk.unique())
    if first.dayofweek != 0:
        weeks = weeks[1:]
    if last.dayofweek != 6:
        weeks = weeks[:-1]
    w = df[df.wk.isin(weeks)].groupby([level, "wk"]).y.sum().unstack(fill_value=0.0)
    w = w.reindex(columns=weeks, fill_value=0.0)
    ev = event_flags(df)
    ev["wk"] = ev.index.to_period("W-SUN").start_time
    evw = ev.groupby("wk").mean().reindex(weeks).fillna(0.0)
    return w, evw


def monthly_panel(df: pd.DataFrame, level: str) -> pd.DataFrame:
    df = df.copy()
    df["mo"] = df.order_date.dt.to_period("M")
    return df.groupby([level, "mo"]).y.sum().unstack(fill_value=0.0)
