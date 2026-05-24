# C0a Chip Event-Driven Experiment

- Universe size: **139** stocks
- Period: 2022-05-24 ~ 2026-05-22
- Gate: n_events >= 100, cost-adjusted 5d mean >= 50bp, cost-adjusted 5d median > 0bp, hit-rate spread >= 5pp, top5% excluded mean > 0bp
- Generated: 2026-05-24T22:30:04

## Trigger Frequency

| trigger | raw_triggers | trigger_dates |
|---|---:|---:|
| foreign_anomaly_buy | 1972 | 562 |
| invtrust_anomaly_buy | 1136 | 305 |
| foreign_reverse_to_buy | 3554 | 839 |
| margin_rapid_drop | 1794 | 424 |

## Event Study Gate

| trigger | pass | n_events | hit_rate | base_rate | mean_5d_bp | median_5d_bp | cost_adj_mean_5d_bp | cost_adj_median_5d_bp | top5_excluded_5d_bp | reasons |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| foreign_anomaly_buy | FAIL | 1965 | 0.480 | 0.481 | 65.09 | 0.00 | 24.03 | -40.83 | -50.66 | cost_adjusted_mean_5d 24.03 < 50.00; cost_adjusted_median_5d -40.83 <= 0; hit_rate_minus_base_rate -0.0007 < 0.0500; top5pct_excluded_mean_5d -50.66 <= 0 |
| invtrust_anomaly_buy | FAIL | 1136 | 0.519 | 0.488 | 125.98 | 27.19 | 84.71 | -13.73 | 22.37 | cost_adjusted_median_5d -13.73 <= 0; hit_rate_minus_base_rate 0.0317 < 0.0500 |
| foreign_reverse_to_buy | FAIL | 3517 | 0.493 | 0.484 | 60.13 | 0.00 | 19.08 | -40.83 | -43.05 | cost_adjusted_mean_5d 19.08 < 50.00; cost_adjusted_median_5d -40.83 <= 0; hit_rate_minus_base_rate 0.0098 < 0.0500; top5pct_excluded_mean_5d -43.05 <= 0 |
| margin_rapid_drop | FAIL | 1786 | 0.490 | 0.473 | 51.92 | 0.00 | 10.90 | -40.83 | -48.53 | cost_adjusted_mean_5d 10.90 < 50.00; cost_adjusted_median_5d -40.83 <= 0; hit_rate_minus_base_rate 0.0170 < 0.0500; top5pct_excluded_mean_5d -48.53 <= 0 |
