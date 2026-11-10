"""Rolling-origin (expanding window), 1-step-ahead backtests. Each fn returns a list of result rows."""
import numpy as np
from .baselines import naive, ma
from .config import FIRST_TEST_WEEK, FIRST_TEST_MONTH
from .data import weekly_panel, monthly_panel
from .hierarchy import allocate_by_share
from .metrics import wape, bias
from .models import ml_forecast


def _row(level, model, A, P):
    return dict(level=level, model=model, WAPE=round(wape(A, np.array(P)), 3), bias=round(bias(A, np.array(P)), 3))


def weekly_level(df, level):
    w_df, ev_df = weekly_panel(df, level)
    w, ev = w_df.values, ev_df.values
    tests = range(FIRST_TEST_WEEK, w.shape[1])
    A = np.array([w[:, t] for t in tests])
    P = {
        "naive": [naive(w, t) for t in tests],
        "ma4": [ma(w, t, 4) for t in tests],
        "ma8": [ma(w, t, 8) for t in tests],
        "ridge": [ml_forecast(w, ev, t, "ridge") for t in tests],
        "gbm": [ml_forecast(w, ev, t, "gbm") for t in tests],
    }
    return [_row(f"weekly_{level}", k, A, v) for k, v in P.items()]


def weekly_sku_allocated(df):
    sku_w, _ = weekly_panel(df, "item_code")
    fam_w, ev_df = weekly_panel(df, "family")
    S, f_w, ev = sku_w.values, fam_w.values, ev_df.values
    sku_family = df.drop_duplicates("item_code").set_index("item_code").family
    fam_index = {f: i for i, f in enumerate(fam_w.index)}
    tests = range(FIRST_TEST_WEEK, f_w.shape[1])
    A = np.array([S[:, t] for t in tests])
    P = {"ma8": [ma(S, t, 8) for t in tests], "ma4": [ma(S, t, 4) for t in tests]}
    for kind in ["ridge", "gbm"]:
        P[f"family-{kind}->alloc"] = [
            allocate_by_share(ml_forecast(f_w, ev, t, kind), fam_index, sku_w.index, sku_family, S[:, t - 8:t].sum(axis=1))
            for t in tests]
    return [_row("weekly_sku", k, A, v) for k, v in P.items()]


def monthly_sku(df):
    m = monthly_panel(df, "item_code").values
    ts = range(FIRST_TEST_MONTH, m.shape[1])
    A = np.array([m[:, t] for t in ts])
    P = {"naive": [m[:, t - 1] for t in ts], "expanding_mean": [m[:, :t].mean(axis=1) for t in ts]}
    return [_row("monthly_sku", k, A, v) for k, v in P.items()]