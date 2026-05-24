# E3 Momentum Walk-Forward IC

- Universe size: **139** stocks
- Windows: 11 (IS 12mo / OOS 3mo / embargo 15 business days)
- Feature: 12-1m return (skip=21, lookback=252)
- Forward return horizon: 21 trading days
- Gate (§E.3): UNLOCK ≥ 0.04; UNCERTAIN 0.02–0.04; DEAD < 0.02
- Generated: 2026-05-25T00:20:20

## Aggregate OOS IC (cross-window)

| variant | ic_mean | ic_std |
|---|---:|---:|
| Raw | 0.0887 | 0.1418 |
| Sector-neutral (real TWSE mapping) | 0.0320 | 0.1378 |

## Verdict: **UNCERTAIN**

Sector-neutral OOS ic_mean lands in the 0.02–0.04 grey zone — do NOT commit to PORTFOLIO/RANK-SE infrastructure; consider C4 advisor accumulation or wider universe before re-attempting.

## Per-window OOS IC

| # | oos_start | oos_end | raw ic_mean | sector-neutral ic_mean | n_periods |
|---:|---|---|---:|---:|---:|
| 1 | 2023-05-24 | 2023-08-24 | 0.2022 | 0.1354 | 64 |
| 2 | 2023-08-24 | 2023-11-24 | -0.0310 | -0.0575 | 64 |
| 3 | 2023-11-24 | 2024-02-24 | 0.2367 | 0.0747 | 58 |
| 4 | 2024-02-23 | 2024-05-23 | 0.0820 | -0.0257 | 61 |
| 5 | 2024-05-24 | 2024-08-24 | 0.2807 | 0.2619 | 63 |
| 6 | 2024-08-23 | 2024-11-23 | 0.1558 | 0.1284 | 61 |
| 7 | 2024-11-22 | 2025-02-22 | -0.2062 | -0.2889 | 58 |
| 8 | 2025-02-24 | 2025-05-24 | -0.0197 | 0.0187 | 61 |
| 9 | 2025-05-23 | 2025-08-23 | 0.0178 | 0.0120 | 65 |
| 10 | 2025-08-22 | 2025-11-22 | 0.0861 | 0.0464 | 62 |
| 11 | 2025-11-24 | 2026-02-24 | 0.1710 | 0.0469 | 57 |
