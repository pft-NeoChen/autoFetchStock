# Backtest Report

## ⚠️ 報告限制

- **Chip 資料覆蓋**: 78566 檔；**Margin 資料覆蓋**: 2253 檔。
- **Universe vs market 脫鉤**: 39 檔小型股 OOS 9mo mean ≈ +233%；同期 0050 兩年 -38% 後 OOS 反彈 +67%。
  → universe 大幅 outperform 0050 → equal_weight 166% vs 0050 67%。survivorship bias + 大小盤脫鉤雙重影響。
  → 真正解法：接 TWSE 完整 listed + delisted 名單做 universe（V2 §0.2 全規則）。
- **Regime gate 過嚴**: 改用 0050 OHLC 作 regime classifier 後，OOS 期間 0050 close<MA200 → 全 3 個 OOS window labeled BEAR → gate 擋下 18/19 訊號，剩 1 trade。
  → 當策略 universe 與 regime proxy 脫鉤時，gate 變成「禁止交易」開關。需重思 gate 設計（per-stock regime?或放寬 allowed regime?）。
- **News features 仍 neutral default**（TASK-D01d news cron 未實作，RSS 無歷史）→ news_severity / is_limit_up 永遠 0/False。
- **Benchmarks**: weighted_index / etf_total_return 兩槽位皆用 **0050 raw OHLC 作 proxy**（含息 IR0003 backfill 未做；0050 也未做 dividend adjustment）→ price-only 近似。
- **Top-N excluded return** 採 naive 等同 total_return（未做真實 top-5 排除）。
- **本報告 V1 重判決（post-D01c backfill / IS-extended / regime-gated / equity-fix / real-benchmark）**；屬 V2 §6.1 第二次量化判決。FAIL 主因為 universe-regime 脫鉤導致 n_trades=1，需重設計 regime gate 或 universe 選擇。

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
- **n_trades**: 1
- **n_windows**: 3
- **experiment_id**: 80248fbebe94c624

## Performance Metrics

| 指標 | 值 |
|------|----|
| 交易次數 | 1 |
| 總報酬 | -0.09% |
| Sharpe (年化) | -0.11 |
| Sortino (年化) | -0.03 |
| Max Drawdown | 0.74% |
| 勝率 | 0.00% |
| Profit Factor | 0.00 |
| 每筆期望值 (bp) | -1011.29 |
| Turnover | 0.01 |

## Benchmark 對照

| Benchmark | 期間報酬 |
|-----------|---------|
| weighted_index (0050 proxy) | 67.65% |
| etf_total_return (0050 proxy) | 67.65% |
| equal_weight_universe | 166.15% |
| ma_strategy (on 0050) | 57.70% |
| cash | 0.00% |

## V2 §6.1 量化門檻

| Check | Pass |
|-------|------|
| expectancy_bp | ❌ |
| profit_factor | ❌ |
| max_drawdown | ✅ |
| sharpe | ❌ |
| oos_is_ratio | ❌ |
| top5_excluded | ❌ |
| beats_benchmarks | ❌ |
| oos_alpha | ❌ |
| regime_coverage | ❌ |
| n_trades | ❌ |

### 失敗原因

- expectancy_bp -1011.29 < 5.0
- profit_factor 0.00 < 1.3
- sharpe -0.11 < 1.0
- oos_is_ratio 0.00 < 0.7
- top5_excluded_return -0.09% ≤ 0
- did not beat both weighted_index and 0050
- oos_alpha -67.74% ≤ 0
- regime coverage incomplete (bull=0, bear=3, range=0)
- n_trades 1 < 50

**結論**: ❌ FAIL
