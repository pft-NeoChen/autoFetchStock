# IC Report (TASK-S01)

- Universe size: **39** stocks
- Period: 2023-12-01 ~ 2026-05-22
- IC thresholds (V2 §1 修訂): {1: 0.02, 5: 0.03, 20: 0.04}

## Per-feature IC (Spearman, cross-sectional)

| feature | 1d_ic_mean | 1d_ic_ir | 1d_p | 1d_n | 1d_pass | 5d_ic_mean | 5d_ic_ir | 5d_p | 5d_n | 5d_pass | 20d_ic_mean | 20d_ic_ir | 20d_p | 20d_n | 20d_pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| atr_14 | 0.015 | 0.06 | 0.203 | 485 | FAIL | 0.050 | 0.19 | 0.000 | 481 | PASS | 0.099 | 0.35 | 0.000 | 466 | PASS |
| baseline_low_confidence | 0.015 | 0.10 | 0.550 | 40 | FAIL | 0.036 | 0.25 | 0.124 | 40 | FAIL | 0.094 | 1.12 | 0.000 | 40 | PASS |
| daily_return | -0.009 | -0.04 | 0.350 | 497 | FAIL | 0.004 | 0.02 | 0.706 | 493 | FAIL | 0.034 | 0.16 | 0.000 | 478 | FAIL |
| ma_10 | 0.015 | 0.06 | 0.194 | 489 | FAIL | 0.036 | 0.15 | 0.001 | 485 | PASS | 0.072 | 0.27 | 0.000 | 470 | PASS |
| ma_20 | 0.012 | 0.05 | 0.275 | 479 | FAIL | 0.031 | 0.13 | 0.005 | 475 | PASS | 0.068 | 0.25 | 0.000 | 460 | PASS |
| ma_5 | 0.014 | 0.06 | 0.219 | 494 | FAIL | 0.036 | 0.15 | 0.001 | 490 | PASS | 0.074 | 0.28 | 0.000 | 475 | PASS |
| ma_60 | 0.012 | 0.05 | 0.298 | 439 | FAIL | 0.030 | 0.12 | 0.013 | 435 | FAIL | 0.069 | 0.25 | 0.000 | 420 | PASS |
| vol_20 | 0.013 | 0.05 | 0.289 | 478 | FAIL | 0.062 | 0.22 | 0.000 | 474 | PASS | 0.108 | 0.38 | 0.000 | 459 | PASS |
| volume_ratio | -0.012 | -0.06 | 0.191 | 488 | FAIL | -0.014 | -0.07 | 0.119 | 484 | FAIL | 0.023 | 0.13 | 0.007 | 469 | FAIL |

## Notes

- IC is computed cross-sectionally per date, then summarised over the period.
- PASS = abs(ic_mean) ≥ horizon threshold AND p-value < 0.05.
- IC alone is not sufficient — check decay + monotonicity before trusting a feature.
- Generated: 2026-05-23T00:04:10
