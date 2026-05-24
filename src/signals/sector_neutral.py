"""TASK-S1-E3 — sector classification + neutralization + momentum helpers.

Designed for the C2 cross-sectional momentum experiment. Kept research-only
(not imported by SignalEngine). Sector classification is heuristic: TWSE
4-digit codes intentionally cluster industries within the first two digits
(11xx 水泥 / 12xx 食品 / 23-25xx 電子 / 28xx 金融 / ...). For pre-promotion
research this is precise enough.
"""

from __future__ import annotations

import pandas as pd


__all__ = [
    "compute_12_1m_return",
    "compute_forward_return",
    "cost_adjusted_decile_spread",
    "decile_spread",
    "infer_sector",
    "sector_neutralize",
]


# ── sector classification ──────────────────────────────────────────────────


def infer_sector(stock_id: str) -> str:
    """Return the 2-digit industry bucket label for a TWSE stock id."""
    sid = str(stock_id).strip()
    if not sid:
        return "unknown"
    digits = "".join(ch for ch in sid if ch.isdigit())
    if len(digits) < 2:
        return "unknown"
    return digits[:2]


# ── momentum helpers ───────────────────────────────────────────────────────


def _to_wide(series: pd.Series) -> pd.DataFrame:
    return series.unstack("stock_id").sort_index()


def _to_long(wide: pd.DataFrame, *, name: str) -> pd.Series:
    out = wide.stack(future_stack=True)
    out.index = out.index.set_names(["date", "stock_id"])
    out.name = name
    return out.sort_index()


def compute_12_1m_return(
    closes: pd.Series,
    *,
    skip: int = 21,
    lookback: int = 252,
) -> pd.Series:
    """Jegadeesh–Titman style 12-1m momentum at each (date, stock_id).

    Defined as ``close.shift(skip) / close.shift(lookback) - 1`` so that the
    most recent ``skip`` trading days are excluded (avoids 1-month reversal).
    """
    wide = _to_wide(closes.astype(float))
    mom = wide.shift(skip) / wide.shift(lookback) - 1.0
    return _to_long(mom, name="mom_12_1m")


def compute_forward_return(
    closes: pd.Series,
    *,
    horizon: int = 21,
) -> pd.Series:
    """Forward log-free return over ``horizon`` trading days."""
    wide = _to_wide(closes.astype(float))
    fwd = wide.shift(-horizon) / wide - 1.0
    return _to_long(fwd, name=f"fwd_{horizon}d")


# ── neutralization ─────────────────────────────────────────────────────────


def sector_neutralize(
    feature: pd.Series,
    sectors: pd.Series,
) -> pd.Series:
    """Subtract per-(date, sector) mean from ``feature``."""
    df = pd.DataFrame({"f": feature.astype(float), "sector": sectors.astype(object)})
    df = df.dropna(subset=["f"])
    if df.empty:
        return pd.Series(dtype=float, index=feature.index, name=feature.name)
    df.index = df.index.set_names(["date", "stock_id"])
    group_mean = df.groupby([df.index.get_level_values("date"), "sector"])["f"].transform("mean")
    out = (df["f"] - group_mean).reindex(feature.index)
    out.name = feature.name
    return out


# ── decile spread ──────────────────────────────────────────────────────────


def _per_date_decile_spread(
    df: pd.DataFrame,
    *,
    n_buckets: int,
) -> pd.Series:
    spreads: dict[pd.Timestamp, float] = {}
    for ts, group in df.groupby(level="date"):
        clean = group.dropna()
        if len(clean) < n_buckets:
            continue
        try:
            buckets = pd.qcut(clean["f"], q=n_buckets, labels=False, duplicates="drop")
        except ValueError:
            continue
        clean = clean.assign(bucket=buckets)
        bucket_means = clean.groupby("bucket")["r"].mean()
        if bucket_means.empty:
            continue
        top = bucket_means.iloc[-1]
        bottom = bucket_means.iloc[0]
        spreads[ts] = float(top - bottom)
    if not spreads:
        return pd.Series(dtype=float)
    return pd.Series(spreads).sort_index()


def decile_spread(
    feature: pd.Series,
    forward_return: pd.Series,
    *,
    n_buckets: int = 10,
) -> float:
    """Mean of per-date (top-bucket return − bottom-bucket return)."""
    df = pd.concat(
        [feature.rename("f"), forward_return.rename("r")], axis=1
    ).dropna()
    if df.empty:
        return float("nan")
    spreads = _per_date_decile_spread(df, n_buckets=n_buckets)
    if spreads.empty:
        return float("nan")
    return float(spreads.mean())


def cost_adjusted_decile_spread(
    feature: pd.Series,
    forward_return: pd.Series,
    *,
    n_buckets: int = 10,
    monthly_cost: float = 0.006,
) -> float:
    """Decile spread minus assumed per-rebalance round-trip cost."""
    raw = decile_spread(feature, forward_return, n_buckets=n_buckets)
    if pd.isna(raw):
        return raw
    return float(raw - monthly_cost)
