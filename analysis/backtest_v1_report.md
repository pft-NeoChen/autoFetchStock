# Backtest Report

## ⚠️ 報告限制

- **Chip 資料覆蓋**: 78566 檔；**Margin 資料覆蓋**: 2253 檔。
- **Universe survivorship bias**: 39 檔皆為使用者手選清單，OOS 9 月 mean ≈ +233%、median ≈ +176%，皆贏家。
  → equal_weight benchmark 因此異常高（179%），策略小樣本選擇性買入難以 outperform。
  → 真正解法：接 TWSE 完整 listed + delisted 名單做 universe（V2 §0.2 全規則）。
- **News features 仍 neutral default**（TASK-D01d news cron 未實作，RSS 無歷史）→ news_severity / is_limit_up 永遠 0/False。
- **Benchmarks**: weighted_index / 0050 / ma_strategy 仍為 placeholder（0.0），需接含息系列才能 fairly alpha。
- **Regime coverage** 由 universe 平均 OHLC 跑 MA-based classifier；因 universe 全贏家，proxy 全期間 BULL → coverage 0+0+3。需接真實大盤指數。
- **Top-N excluded return** 採 naive 等同 total_return（未做真實 top-5 排除）。
- **本報告 V1 重判決（post-D01c backfill / IS-extended / regime-gated / equity-fix）**；屬 V2 §6.1 第一次量化判決。FAIL 主因為 universe bias + 樣本小（n_trades=19），非策略本質失敗。

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
- **n_trades**: 19
- **n_windows**: 3
- **experiment_id**: 80248fbebe94c624

## Performance Metrics

| 指標 | 值 |
|------|----|
| 交易次數 | 19 |
| 總報酬 | -0.42% |
| Sharpe (年化) | -0.14 |
| Sortino (年化) | -0.13 |
| Max Drawdown | 1.52% |
| 勝率 | 31.58% |
| Profit Factor | 2.15 |
| 每筆期望值 (bp) | 208.91 |
| Turnover | 0.15 |

## Benchmark 對照

| Benchmark | 期間報酬 |
|-----------|---------|
| weighted_index (placeholder) | 0.00% |
| etf_0050 (placeholder) | 0.00% |
| equal_weight_universe | 179.69% |
| ma_strategy (placeholder) | 0.00% |
| cash | 0.00% |

## V2 §6.1 量化門檻

| Check | Pass |
|-------|------|
| expectancy_bp | ✅ |
| profit_factor | ✅ |
| max_drawdown | ✅ |
| sharpe | ❌ |
| oos_is_ratio | ❌ |
| top5_excluded | ❌ |
| beats_benchmarks | ❌ |
| oos_alpha | ❌ |
| regime_coverage | ❌ |
| n_trades | ❌ |

### 失敗原因

- sharpe -0.14 < 1.0
- oos_is_ratio 0.43 < 0.7
- top5_excluded_return -0.42% ≤ 0
- did not beat both weighted_index and 0050
- oos_alpha -180.10% ≤ 0
- regime coverage incomplete (bull=3, bear=0, range=0)
- n_trades 19 < 50

**結論**: ❌ FAIL
