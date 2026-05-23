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
- **本報告 V1 §6.1 第三次量化判決（post equity-fix / real-benchmark / per-stock regime gate）**。剩餘 FAIL 主因：(1) n_trades 仍 < 50（資料 span 僅 2 年 × 39 檔，OOS 9mo 內訊號自然有限）(2) universe survivorship bias 推高 benchmark (3) 0050 OOS 全 BEAR → regime_coverage 不滿足 1+1+1。

---

**Verdict**: ❌ FAIL

## Manifest

- **strategy**: long_entry_v1
- **universe_size**: 39
- **data_span_start**: 2022-07-26
- **data_span_end**: 2026-05-22
- **is_months**: 12
- **oos_months**: 3
- **embargo_business_days**: 15
- **initial_cash_per_stock**: 1000000.0
- **target_shares**: 1000
- **caveats**: chip/news/margin features defaulted (local data sparse)
- **n_trades**: 43
- **n_windows**: 11
- **experiment_id**: 38a8ccc08dc451df

## Performance Metrics

| 指標 | 值 |
|------|----|
| 交易次數 | 43 |
| 總報酬 | -0.88% |
| Sharpe (年化) | -0.11 |
| Sortino (年化) | -0.09 |
| Max Drawdown | 2.58% |
| 勝率 | 30.23% |
| Profit Factor | 1.69 |
| 每筆期望值 (bp) | 33.49 |
| Turnover | 0.31 |

## Benchmark 對照

| Benchmark | 期間報酬 |
|-----------|---------|
| weighted_index (0050 proxy) | -23.10% |
| etf_total_return (0050 proxy) | -23.10% |
| equal_weight_universe | 408.81% |
| ma_strategy (on 0050) | -36.50% |
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
| beats_benchmarks | ✅ |
| oos_alpha | ✅ |
| regime_coverage | ❌ |
| n_trades | ❌ |

### 失敗原因

- sharpe -0.11 < 1.0
- oos_is_ratio -0.28 < 0.7
- top5_excluded_return -0.47% ≤ 0
- regime coverage incomplete (bull=7, bear=4, range=0)
- n_trades 43 < 50

**結論**: ❌ FAIL
