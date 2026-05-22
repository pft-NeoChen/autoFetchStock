# Backtest Report

## ⚠️ 報告限制

- **Chip / news / margin features 沿用 neutral defaults**（local data ≤ 15 天 vs. 2 年 OHLC）
  → entry chip filter (foreign_net_streak ≥ 3 OR margin_5d_change < 0) 幾乎全失敗
  → 預期極少甚至零訊號。**這是已知資料缺口,非策略本身失敗**.
- **Benchmarks**: weighted_index / 0050 / ma_strategy 為 placeholder（0.0），equal_weight 為 universe 平均報酬
- **OOS/IS ratio / regime coverage / alpha**: 均為 placeholder（0），需 V2 §6.1 二輪實跑（含 IS 評估、regime 標記、含息 benchmark 接入）才能 fairly 評估
- **本報告為 D03c gating logic 端對端 smoke + Phase 3 結案artifact**,非 V2 §6.1 正式判決

---

**Verdict**: ❌ FAIL

## Manifest

- **strategy**: long_entry_v1
- **universe_size**: 39
- **data_span_start**: 2024-06-26
- **data_span_end**: 2026-05-22
- **is_months**: 12
- **oos_months**: 3
- **embargo_business_days**: 15
- **initial_cash_per_stock**: 1000000.0
- **target_shares**: 1000
- **caveats**: chip/news/margin features defaulted (local data sparse)
- **n_trades**: 0
- **n_windows**: 3
- **experiment_id**: 80248fbebe94c624

## Performance Metrics

| 指標 | 值 |
|------|----|
| 交易次數 | 0 |
| 總報酬 | 2.63% |
| Sharpe (年化) | 1.15 |
| Sortino (年化) | 7.23 |
| Max Drawdown | 97.37% |
| 勝率 | 0.00% |
| Profit Factor | 0.00 |
| 每筆期望值 (bp) | 0.00 |
| Turnover | 0.00 |

## Benchmark 對照

| Benchmark | 期間報酬 |
|-----------|---------|
| weighted_index (placeholder) | 0.00% |
| etf_0050 (placeholder) | 0.00% |
| equal_weight_universe | 300.19% |
| ma_strategy (placeholder) | 0.00% |
| cash | 0.00% |

## V2 §6.1 量化門檻

| Check | Pass |
|-------|------|
| expectancy_bp | ❌ |
| profit_factor | ❌ |
| max_drawdown | ❌ |
| sharpe | ✅ |
| oos_is_ratio | ❌ |
| top5_excluded | ✅ |
| beats_benchmarks | ❌ |
| oos_alpha | ❌ |
| regime_coverage | ❌ |
| n_trades | ❌ |

### 失敗原因

- expectancy_bp 0.00 < 5.0
- profit_factor 0.00 < 1.3
- max_drawdown 97.37% > 20%
- oos_is_ratio 0.00 < 0.7
- did not beat both weighted_index and 0050
- oos_alpha -297.55% ≤ 0
- regime coverage incomplete (bull=0, bear=0, range=0)
- n_trades 0 < 50

**結論**: ❌ FAIL
