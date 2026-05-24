# Backtest Report

## ⚠️ 報告限制

- **Chip 資料覆蓋**: 80971 檔；**Margin 資料覆蓋**: 2276 檔。
- **Universe vs market 脫鉤**: 39 檔小型股 OOS 9mo mean ≈ +233%；同期 0050 兩年 -38% 後 OOS 反彈 +67%。
  → universe 大幅 outperform 0050 → equal_weight 166% vs 0050 67%。survivorship bias + 大小盤脫鉤雙重影響。
  → 真正解法：接 TWSE 完整 listed + delisted 名單做 universe（V2 §0.2 全規則）。
- **Regime gate（Plan D）**: 改用 **per-stock regime**（每檔自己的 MA50/MA200）+ allowed={BULL, RANGE}；取代原市場 wide gate（0050）。修正 Plan A 「universe-market 脫鉤時 gate 變禁止交易」的 bug。
  → market-wide regime_coverage 仍取 0050 OHLC（V2 §6.1 是評估 backtest 跨 regime 多樣性，與 trade 開閘無關）。
- **News features 仍 neutral default**（TASK-D01d news cron 未實作，RSS 無歷史）→ news_severity / is_limit_up 永遠 0/False。
- **Benchmarks**: weighted_index / etf_total_return 兩槽位皆用 **0050 raw OHLC 作 proxy**（含息 IR0003 backfill 未做；0050 也未做 dividend adjustment）→ price-only 近似。
- **Top-N excluded return** 已採真實計算（sort by pnl 排除最賺 5 筆後 / initial_capital）。
- **本報告 V1 §6.1 第六次判決（R3-sample 100 stocks 加入）**。重要 finding：n_trades 47→59 PASS，但 expectancy_bp +33→**-41 翻負**；equal_weight 166%→110% 顯示 universe bias 減半。**原 39 檔 hand-picked 造成 expectancy 假陽性，broader universe 顯示 strategy 缺真實 edge**。

---

**Verdict**: ❌ FAIL

## Manifest

- **strategy**: long_entry_v1
- **universe_size**: 138
- **data_span_start**: 2022-07-26
- **data_span_end**: 2026-05-22
- **is_months**: 12
- **oos_months**: 3
- **embargo_business_days**: 15
- **initial_cash_per_stock**: 1000000.0
- **target_shares**: 1000
- **caveats**: chip/news/margin features defaulted (local data sparse)
- **n_trades**: 59
- **n_windows**: 11
- **experiment_id**: 585d233f0ef40d2f

## Performance Metrics

| 指標 | 值 |
|------|----|
| 交易次數 | 59 |
| 總報酬 | -0.29% |
| Sharpe (年化) | -0.14 |
| Sortino (年化) | -0.13 |
| Max Drawdown | 0.77% |
| 勝率 | 32.20% |
| Profit Factor | 1.41 |
| 每筆期望值 (bp) | -41.58 |
| Turnover | 0.10 |

## Benchmark 對照

| Benchmark | 期間報酬 |
|-----------|---------|
| weighted_index (0050 proxy) | -23.10% |
| etf_total_return (0050 proxy) | -23.10% |
| equal_weight_universe | 109.96% |
| ma_strategy (on 0050) | -36.50% |
| cash | 0.00% |

## V2 §6.1 量化門檻

| Check | Pass |
|-------|------|
| expectancy_bp | ❌ |
| profit_factor | ✅ |
| max_drawdown | ✅ |
| sharpe | ❌ |
| oos_is_ratio | ❌ |
| top5_excluded | ❌ |
| beats_benchmarks | ✅ |
| oos_alpha | ✅ |
| regime_coverage | ❌ |
| n_trades | ✅ |

### 失敗原因

- expectancy_bp -41.58 < 5.0
- sharpe -0.14 < 1.0
- oos_is_ratio -0.31 < 0.7
- top5_excluded_return -0.16% ≤ 0
- regime coverage incomplete (bull=7, bear=4, range=0)

**結論**: ❌ FAIL


## OOS-IS Window Diagnostic

| # | OOS span | regime | IS trades | OOS trades | IS return | OOS return | ratio |
|---|----------|--------|-----------|-----------|-----------|-----------|-------|
| 1 | 2023-08-16 ~ 2023-11-16 | bull | 4 | 4 | -0.01% | -0.01% | 0.53 |
| 2 | 2023-11-16 ~ 2024-02-16 | bull | 8 | 5 | -0.02% | -0.01% | 0.55 |
| 3 | 2024-02-16 ~ 2024-05-16 | bull | 14 | 4 | -0.03% | -0.05% | 1.37 |
| 4 | 2024-05-17 ~ 2024-08-17 | bull | 16 | 5 | -0.13% | -0.06% | 0.50 |
| 5 | 2024-08-16 ~ 2024-11-16 | bull | 20 | 1 | -0.03% | -0.02% | 0.73 |
| 6 | 2024-11-15 ~ 2025-02-15 | bull | 18 | 2 | 0.05% | 0.02% | 0.43 |
| 7 | 2025-02-14 ~ 2025-05-14 | bear | 16 | 2 | 0.08% | 0.02% | 0.28 |
| 8 | 2025-05-16 ~ 2025-08-16 | bear | 15 | 3 | -0.24% | -0.00% | 0.00 |
| 9 | 2025-08-15 ~ 2025-11-15 | bear | 12 | 12 | 0.24% | -0.03% | -0.14 |
| 10 | 2025-11-14 ~ 2026-02-14 | bear | 20 | 8 | 0.27% | -0.21% | -0.78 |
| 11 | 2026-02-16 ~ 2026-05-16 | bull | 26 | 13 | 0.78% | 0.06% | 0.07 |

**IS positive windows**: 5 / 11
**OOS positive windows**: 3 / 11

_Interpretation: large gap between IS+ and OOS+ counts → likely overfitting or regime mismatch. Equal counts with negative average ratio → consistent loss._