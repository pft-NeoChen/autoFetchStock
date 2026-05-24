# C2 Cross-sectional Momentum IC

- Universe size: **139** stocks across **50** sector buckets (2-digit TWSE stock-id prefix)
- Period: 2022-05-03 ~ 2026-05-22
- Feature: 12-1m return (skip=21, lookback=252 trading days)
- Forward return horizon: 21 trading days
- Gate: |ic_mean| >= 0.040 (V2 §1 horizon 20) AND cost-adjusted decile spread > 0
- Monthly turnover cost assumption: 60 bp / rebalance
- Generated: 2026-05-24T22:59:44

## Results (IC + Decile spread)

| variant | ic_mean | ic_ir | p_value | n_periods | decile_spread | decile_spread_cost_adj | passes_gate |
|---|---:|---:|---:|---:|---:|---:|---|
| raw | 0.0996 | 0.448 | 0.0000 | 710 | 0.0453 | 0.0393 | PASS |
| sector_neutral | 0.0834 | 0.453 | 0.0000 | 710 | 0.0529 | 0.0469 | PASS |

## Sector-neutral note

Sector buckets are inferred from TWSE 4-digit stock-id prefix (first two
digits). This is a coarse heuristic — accurate for the dominant industry
groupings (11xx 水泥, 12xx 食品, 23-24xx 電子/半導體, 28xx 金融, etc.) but
does not distinguish sub-industries. If raw IC passes and sector-neutral
fails, the alpha is likely sector beta and should be rejected.
