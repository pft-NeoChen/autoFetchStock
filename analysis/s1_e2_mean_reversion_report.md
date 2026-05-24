# C1-safe Mean Reversion Experiment

- Universe size: **139** stocks
- Period: 2022-05-03 ~ 2026-05-22
- Trigger: 5d return < −1.5 × 20d vol AND RSI(14) < 30 AND regime ∈ {BULL, RANGE} AND not limit-down AND news_severity > −5
- Gate: n_events >= 100, cost-adjusted 5d mean >= 50bp, cost-adjusted 5d median > 0bp, hit-rate spread >= 5pp, top5% excluded mean > 0bp
- Generated: 2026-05-24T22:48:52

## Trigger Frequency

| trigger | raw_triggers | trigger_dates |
|---|---:|---:|
| mean_reversion_oversold | 1265 | 400 |

## BEAR skip diagnostic

Count of would-be triggers (every non-regime condition met) dropped solely
because per-stock regime was BEAR. C1-safe spec hard-skips BEAR; this row is
informational only and is **not** a gate input.

| trigger | bear_skipped |
|---|---:|
| mean_reversion_oversold | 1938 |

## Event Study Gate

| trigger | pass | n_events | hit_rate | base_rate | mean_5d_bp | median_5d_bp | cost_adj_mean_5d_bp | cost_adj_median_5d_bp | top5_excluded_5d_bp | reasons |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| mean_reversion_oversold | FAIL | 1265 | 0.556 | 0.476 | 96.94 | 67.20 | 55.77 | 26.14 | -4.40 | top5pct_excluded_mean_5d -4.40 <= 0 |
