# Profitability Implementation Progress

> **State of the world.** 每次 session 開始**先讀此檔**，結束**必更新**。
> 規格：`specs/profitability/PROFITABILITY_PLAN_V2.md`。流程：`specs/profitability/IMPLEMENTATION_PLAN.md`。

---

## Quick Status

| 欄位 | 值 |
|------|----|
| 上次更新 | 2026-05-23 |
| 上次 session | V1 重判決 plumbing prep — `scripts/run_backtest_v1.py` 加 chip/margin loaders + market_ohlc proxy + regime-gated entry factory + build_feature_frame 接真實 chip_df/margin_df + run() wire include_is=True + compute_oos_is_ratio_from_result + count_regime_coverage；10 unit tests GREEN；完整 pytest 629/629 GREEN；D01c backfill ~85%（408 chips，processing 2025-12-31，ETA ~20min） |
| 當前 phase | **V1 重判決 ready**（Phase 6/9/10 起步皆 DONE，plumbing 完成；等 backfill 完一鍵跑 `python -m scripts.run_backtest_v1`） |
| 當前 task | — |
| 下一個建議 task | backfill 完成 → 跑 `python -m scripts.run_backtest_v1` 產 V1 正式 V2 §6.1 判決報告；若 0 trades 或 FAIL → 檢視 caveats（chip 覆蓋 / news 仍 neutral / weighted_index 含息接入）|
| 全域 blocked | 無 |
| Pytest 狀態 | V1 prep 10/10 GREEN；完整 pytest 629/629 GREEN（12 warnings） |
| 檔案位置 | `specs/profitability/` + `src/features/*.py` + `src/signals/{ic_analysis,engine}.py` + `src/signals/rules/{long_entry,exits,regime_gate}.py` + `src/backtest/*.py` + `src/journal/*.py` + `src/portfolio/{risk_manager,position_sizer,correlation_filter}.py` + `src/monitor/data_freshness_guard.py` + `src/execution/order_router.py` + `src/universe/filter.py` + `scripts/{audit_local_data,backfill_historical_daily,backfill_historical_chips,run_ic_analysis,run_backtest_v1}.py` + `analysis/{local_data_audit,ic_report,backtest_v1_report}.md` |
| Repo 是否乾淨 | main：X01 RED+GREEN 待 commit；仍有 pre-existing analysis/.claude/.antigravitycli 未提交內容 |

---

## Phase Summary

| Phase | Tasks | DONE | IN_PROGRESS | NOT_STARTED | BLOCKED |
|-------|-------|------|-------------|-------------|---------|
| 0 — Universe + Feature Store | 13 | 12 | 1 | 0 | 0 |
| 1 — IC 分析 | 2 | 2 | 0 | 0 | 0 |
| 2 — SignalEngine | 3 | 3 | 0 | 0 | 0 |
| 3 — Backtester | 10 | 10 | 0 | 0 | 1 |
| 4 — Risk + Sizing | 2 | 2 | 0 | 0 | 0 |
| 5 — Journal + Perf | 3 | 3 | 0 | 0 | 0 |
| 6 — Portfolio | 2 | 2 | 0 | 0 | 0 |
| 7 — UI | 1 | 0 | 0 | 1 | 0 |
| 8 — Paper | 3 | 0 | 0 | 3 | 0 |
| 9 — Monitor | 2 | 1 | 0 | 1 | 0 |
| 10 — OrderExecutor | 3 | 1 | 0 | 2 | 0 |
| **總計** | **44** | **36** | **1** | **6** | **1** |

---

## V2 修訂候選

> 在實作中發現的 V2 微調建議。一律先列在此，session 結束彙整，下一 session 開始或用戶確認後才改 V2。

### 2026-05-22 — 用戶批准，已全部套用至 V2

- [x] V2 §0.4：明示用 **backward-adjusted**（最新價不動）
- [x] V2 §3.5：benchmark 指定**含息**版本（加權報酬指數 / 0050 配息再投入）
- [x] V2 §3.4：walk-forward + **embargo**（標配）；Purged K-Fold 移到 §1 IC 分析
- [x] V2 §3.4：OOS 期內交易 < 10 筆 → 合併下一窗
- [x] V2 §3.3：明列台交所 tick rule（< 10 / 10~50 / 50~100 / 100~500 / 500~1000 / > 1000 元 各段 tick）
- [x] V2 §3.7：T+2 cash ledger 第一版簡化為「賣出後 T+2 才入可用餘額」
- [x] V2 §3.4：plateau 定義為「最佳參數 ±1 step 鄰居 ≥ 75% 在 OOS 達標」
- [x] V2 §1：IC 門檻分 horizon：1d ≥ 0.02、5d ≥ 0.03、20d ≥ 0.04

> 後續新發現的 V2 修訂建議請開新區塊在此檔頂部。

---

## Global Session Log

> 每次 session 結束時 append 一行。格式：`YYYY-MM-DD | session-tag | 摘要`。

- 2026-05-22 | bootstrap | 建立 IMPLEMENTATION_PLAN.md / PROGRESS.md / README.md / 套用 V2 八項微調 / 全部文件搬至 `specs/profitability/` / commit + push 至 main
- 2026-05-22 | TASK-D01 | RED 9a38595 + GREEN a903983：scripts/audit_local_data.py + 4 unit tests GREEN + analysis/local_data_audit.md 產出（39 檔，0 檔達 2 年日線）。下一 session 建議：先決定補抓歷史日線，再做 TASK-U01。
- 2026-05-22 | TASK-U01 | RED 9076abb + GREEN 2a1b641：src/universe/filter.py + 12 unit tests GREEN。V2 §0.2 全規則實作。下一 session 接 TASK-F02 (availability) 或 TASK-F01 (corp actions)。
- 2026-05-22 | TASK-F02 | RED 1ee538c + GREEN 9256671 + REFACTOR ba23a7a：src/features/availability.py + 11 unit tests GREEN；依 V2 §0.5 將法人/融資融券預設為下一交易日 08:30 可用，並校正 IMPLEMENTATION_PLAN。下一 session 接 TASK-F01。
- 2026-05-22 | TASK-F01 | RED ee2c407 + GREEN 9b73a0d + REFACTOR 56a2f8a：src/features/corporate_actions.py + 6 unit tests GREEN；3 檔真實資料（2330/3036/8046）smoke OK。下一 session 接 TASK-F03。
- 2026-05-22 | TASK-F03 | RED aca77bd + GREEN c2961ad：src/features/{store,manifest}.py + 8 unit tests GREEN；FeatureStore 接 corporate_actions，拒絕 look-ahead，manifest 持久化 + hash 穩定。下一 session 接 TASK-F04（Price Features）。
- 2026-05-22 | TASK-F04 | RED f67627d + GREEN 8adea95：src/features/price_features.py 純函式 MA/return/ATR/vol + price_feature_providers() factory + 8 unit tests GREEN。下一 session 接 TASK-F05（Volume Features wrapper）。
- 2026-05-22 | TASK-F05 | RED aca5c16 + GREEN ecf36c8：src/features/volume_features.py daily baseline (shift 1 防 look-ahead) + ratio + severity 五級分類 + low_conf flag + provider factory + 12 unit tests GREEN。下一 session 接 TASK-F06（Chip Features）。
- 2026-05-22 | TASK-F06 | RED 1a99345 + GREEN 1bc18be：src/features/chip_features.py foreign_net_streak / rolling_net_buy / margin_n_day_change + chip_feature_providers (使用 T-1 chip 資料避免 look-ahead，available_at=08:30) + 8 unit tests GREEN。下一 session 接 TASK-F07（News Features）。
- 2026-05-22 | TASK-F07 | RED 6ff373d + GREEN ed6cde4：src/features/news_features.py NewsRecord + assign_effective_date (盤後/週末 roll 次日) + aggregate_news_by_day (count/severity/direction) + news_anomaly flag + 10 unit tests GREEN。下一 task 接 TASK-F08。
- 2026-05-22 | TASK-F08 | RED f79a2fb + GREEN d64db21：src/features/regime_features.py market_moving_average + 簡化 adx (平盤 DX=0) + vol_percentile_rank + regime_feature_providers (廣播同值) + 7 unit tests GREEN。下一 task 接 TASK-B03。
- 2026-05-22 | TASK-B03 | RED ed1c15e + GREEN 3ef072a：src/backtest/benchmark.py compute_benchmarks 五條基準 (weighted_index / etf_total_return / equal_weight_universe / ma_strategy / cash)；MA 策略 shift(1) 防 look-ahead + 8 unit tests GREEN。**Phase 0 全 11/11 DONE，下一 session 進 Phase 1 (TASK-S01 IC 分析)**。
- 2026-05-22 | TASK-D01b | RED ffc4420 + GREEN 9477345 + FIX cba24c8：scripts/backfill_historical_daily.py orchestrator + 10 unit tests GREEN。實跑 2 輪後 39/39 ok，**38 檔 ≥2 年日線**（7769 IPO 2025-11 上市無法回補）；FIX commit 改 per-month try/except + 修 DataFetcher 簽名 + StockDailyFile.daily_data 欄位名稱；新增 131 月份 / 1745 records。Blocked 解除，下一 session 進 TASK-S01。
- 2026-05-22 | TASK-D01b enhancement | 236002f：新增 `--stocks SID,SID` CLI flag + resolve_stock_ids helper + 2 unit tests，支援新股票直接 backfill 2 年。
- 2026-05-23 | TASK-S01 + D02 | primitives d4d0fb9/b3e35af + orchestrator ea1e129/4511fd9：src/signals/ic_analysis.py (compute_ic / decay_curve / monotonicity_test / meets_ic_threshold) + scripts/run_ic_analysis.py + analysis/ic_report.md。**21 unit tests GREEN**。實跑 39 stock 兩年日線結果：5d PASS = {ma_5, ma_10, ma_20, atr_14, vol_20}；20d 加 ma_60；1d 全 FAIL。**D02 決策：進 Phase 2，5d/20d holding，不做日內**。下一 session 接 TASK-S02。
- 2026-05-23 | TASK-S02 + S03 + S04 | Phase 2 全 DONE (30 tests GREEN)：
  - S02 ea69c09 + 4a48247：Signal dataclass (無 risk 欄位) + SignalEngine ABC + 7 tests
  - S03 7a415a8 + c3ed23e：evaluate_long_entry 進場 6 條件 + 避免進場 5 條件 + EntryConditions + 12 tests
  - S04 9647942 + b2b2929：evaluate_exit 出場 5 條件 + ExitConditions + 11 tests
  - 下一 session 接 Phase 3：TASK-B01 (Cost model)
- 2026-05-23 | TASK-B01 + B02 | Phase 3 進度 3/6 (37 tests GREEN)：
  - B01 2ca4ad7 + 163cb53：cost_model.py — tick rule 6 band + round_to_tick + commission + round_trip_cost (含 daytrade) + slippage + 23 tests
  - B02 a09d928 + f782c23：execution_model.py — Order/MarketBar/FillResult + simulate_fill (T→T+1, 漲跌停作廢, 流動性 cap, lot rounding, T+2 settlement) + 14 tests
  - 下一 session：**決策 B04 路線（vectorbt vs 自製）**，再 RED
- 2026-05-23 | TASK-B04 + B05 + J04 + D03a | Phase 3 進度 6/8 (32 tests GREEN，D03 拆 a/b/c)：
  - B04 0c810cb + a0950f0：engine.py 自製單股 backtester（無 vectorbt）— Position/Trade/BacktestResult + 日內迴圈 + T+2 cash ledger + mark-to-market + 10 tests
  - B05 17aa9e7 + 531ab47：walk_forward.py — IS/embargo/OOS rolling + merge_small_windows + classify_oos_confidence + 7 tests
  - J04 0ecaba7 + 40ff9ef：journal/experiment_registry.py — ExperimentRecord + Registry (record/lookup/list, sha256 dedupe, failed status) + 7 tests
  - D03 → split a/b/c
  - D03a 2793932 + 6a01d69：adapters/signal_adapter.py — build_entry/exit_conditions + make_entry/exit_decider + 8 tests
  - 下一 session：TASK-D03b (orchestrator)
- 2026-05-23 | TASK-D03b | Phase 3 進度 7/8 (9 tests GREEN，backtest suite 79/79 GREEN)：
  - a31523a (RED) + 189315f (GREEN)：src/backtest/walk_orchestrator.py — `run_walk_forward_backtest` 對 (universe × walk_forward windows) 切 OOS slice → 每股獨立 BacktestEngine.run → 彙總 trades + per_stock_equity + combined_equity → optional ExperimentRegistry.record（manifest 含 universe/windows，summary 含 trade_count/total_pnl）
  - 9 tests: per-stock×window engine call / OOS date slicing / multi-stock trade aggregation / empty slice skip / combined equity sum / registry record / no-registry → id=None / window_result fields / multi-window
  - 下一 session：TASK-D03c (performance + benchmark + report + V2 §6.1 量化門檻決策)
- 2026-05-23 | TASK-D03c | **Phase 3 全 8/8 DONE** (33 tests GREEN，profitability 268/268 GREEN)：
  - 62b52c7 (RED) + dfbbd07 (GREEN)：三個 journal module
  - `performance.py`：PerformanceMetrics + total_return/sharpe/sortino/max_drawdown/win_rate/profit_factor/expectancy_bp/turnover/summarize_performance (18 tests)
  - `decision.py`：evaluate_v2_thresholds 全 10 項 V2 §6.1 門檻（expectancy ≥5bp / pf ≥1.3 / mdd ≤20% / sharpe ≥1.0 / oos_is_ratio ≥0.7 / top5_excluded >0 / beats_benchmarks / oos_alpha >0 / regime_coverage 1+1+1 / n_trades ≥50），thresholds 提到 module top 方便 monkeypatch (11 tests)
  - `backtest_report.py`：render_backtest_report 產 markdown 含 Manifest/Performance/Benchmark對照/V2§6.1門檻表 + verdict (✅PASS/❌FAIL) + 失敗原因 (4 tests)
  - 實跑 `analysis/backtest_v1_report.md` 待接 D03b orchestrator + 真實 feature pipeline 後產出（gating logic 已完成可直接呼叫）
  - 下一 session：實跑回測 OR 進 Phase 4 (TASK-R01 RiskManager / TASK-R02 PositionSizer)
- 2026-05-23 | TASK-D03c 實跑 | d0bbf17：`scripts/run_backtest_v1.py` 端對端 + `analysis/backtest_v1_report.md` 產出
  - 39 stocks × 3 walk-forward windows (IS=12mo / OOS=3mo / embargo=15bd) on data span 2024-06-26 ~ 2026-05-22
  - **0 trades** (entry chip filter `foreign_net_streak ≥ 3 OR margin_5d_change < 0` 被 neutral default 卡住 — 已知 chip/news/margin 本地資料 ≤ 15 天)
  - 報告 verdict ❌ FAIL（10/10 checks 8 失敗），caveats block 已明列「Phase 3 結案 smoke,非正式 V2 §6.1 判決」
  - 重要 follow-up 須在 V1 正式判決前完成：
    1. backfill chip / news / margin 至 ≥ 2 年（可能要寫 TASK-D01c 對應 orchestrator）
    2. 接含息 weighted_index / 0050 真實 benchmark
    3. regime classifier 標記 OOS 期間 bull/bear/range（供 regime_coverage 評估）
    4. IS pass 計算 oos_is_ratio
  - 下一 session 建議：進 Phase 4（TASK-R01 RiskManager / TASK-R02 PositionSizer），實跑判決待資料補齊後再回來重跑
- 2026-05-23 | TASK-R01 | 88e5c5e (RED) + 26fbdc7 (GREEN)：`src/portfolio/risk_manager.py` + `src/portfolio/__init__.py` + 10 unit tests。實作單筆風險、最大持股數、單股 15% allocation cap、每日 -2% loss gate、連虧 3 次半倉、連虧 5 次暫停 1 交易日；相關 suite 45/45 GREEN。完整 pytest 受本機 Python 缺 `scipy` 影響無法 collection。下一 session 接 TASK-R02。
- 2026-05-23 | TASK-R02 | 26ef190 (RED) + cfb00a7 (GREEN)：`src/portfolio/position_sizer.py` + 8 unit tests。實作 vol-target（20 日波動年化反推部位）與 ATR-based（risk budget / k×ATR）兩種 sizing，支援 lot rounding、max notional cap、RiskManager multiplier、Feature row adapter，並拒絕 Kelly；相關 suite 61/61 GREEN。完整 pytest 仍受本機 Python 缺 `scipy` 影響無法 collection。Phase 4 完成，下一 session 接 TASK-J01。
- 2026-05-23 | full pytest fix | 1951947：安裝目前 pytest Python 環境的 scipy，補 `requirements.txt`；修 MarketStrip className 與 ShioajiFetcher lightweight test instance lazy state；完整 pytest 514/514 GREEN。
- 2026-05-23 | TASK-J01 | 13585a6 (RED) + c1c7563 (GREEN)：`src/journal/trade_journal.py` + 7 unit tests。實作 append-only JSONL TradeJournal、TradeJournalEntry、FillSnapshot、CostBreakdown、CashLedgerEntry、from_backtest_trade、list/filter/summary；完整 pytest 521/521 GREEN。下一 session 接 TASK-J02。
- 2026-05-23 | TASK-J02 | e90df41 (RED) + c4a4f60 (GREEN)：`src/journal/signal_log.py` + 7 unit tests。實作 append-only JSONL SignalLog、SignalLogEntry、from_signal、entered/filtered 狀態、filter reasons、RiskDecision snapshot、list filter、summary；完整 pytest 528/528 GREEN。下一 session 接 TASK-J03。
- 2026-05-23 | TASK-J03 | 7b241ae (RED) + b4e1f95 (GREEN)：`src/journal/performance.py` + tests/test_journal/test_performance.py 擴充至 25 tests。補平均盈虧比、OOS/IS ratio、Top-N excluded return、benchmark alpha、render_performance_report；完整 pytest 535/535 GREEN。Phase 5 完成，下一 session 接 TASK-R03。
- 2026-05-23 | TASK-R03 | 1f31cfb (RED) + a52b47d (GREEN)：`src/portfolio/correlation_filter.py` + 7 unit tests。實作 sector + 60d return correlation clustering、同 cluster ≤2 檔限制、portfolio beta ≤1.2 gate、public exports；完整 pytest 542/542 GREEN。下一 session 接 TASK-S05。
- 2026-05-23 | TASK-D01c | 6d2f81b (RED) + a0d7c79 (GREEN)：`scripts/backfill_historical_chips.py` + 14 unit tests。date-major orchestrator 走 weekdays × 4 endpoints (TWSE/TPEX × T86/Margin)，merge 後存 daily snapshot，per-endpoint 例外隔離 + sleep DI；完整 pytest 556/556 GREEN。**實跑待**：`python -m scripts.backfill_historical_chips --years 2`（~100 min），完成後重跑 run_backtest_v1 解 0 trades 困境。news 不在本 task（RSS 無歷史，另起 D01d 即時累積）。
- 2026-05-23 | TASK-D01c real-run | nohup PID 11925 啟動於 19:57，log `/tmp/backfill_chips.log`，背景跑 ~100 min。9 min 已寫 36 chip files，順利。
- 2026-05-23 | TASK-D03d | 7802934 (RED) + cff8f70 (GREEN)：`src/backtest/regime_classifier.py` + 13 unit tests。MA-based labeller (BULL=close>MA200 AND MA50>MA200；BEAR 反向；RANGE 含 flat) + classify_window Counter.most_common + count_regime_coverage 餵 DecisionInput.regime_coverage_*；解 backtest_v1_report caveats #3。完整 pytest 569/569 GREEN。S05 可直接吃 classify_regime。
- 2026-05-23 | TASK-S05 | c4526f8 (RED) + c258cef (GREEN)：`src/signals/rules/regime_gate.py` + 12 unit tests。RegimeGateConfig + gate_by_regime + evaluate_regime_for_signal；預設 allowed={BULL} → bear/range/unknown 全擋；reason 含 regime label 方便 journal lookup。**Phase 6 全 DONE**。完整 pytest 581/581 GREEN。下一步：等 backfill 跑完整合 walk_orchestrator + 重跑 V1。
- 2026-05-23 | TASK-D03e | fe70880 (RED) + 2d6e3ce (GREEN)：`src/backtest/walk_orchestrator.py` 擴 `include_is=True` flag + WindowResult/OrchestratorResult IS aggregate fields + `compute_oos_is_ratio_from_result` helper；7 new tests + 9 既有 regression GREEN。解 backtest_v1_report caveats #4。完整 pytest 588/588 GREEN。下一步：等 backfill 完 → 改 run_backtest_v1 加 include_is=True + 接 oos_is_ratio + regime_coverage。
- 2026-05-23 | TASK-M01 | `src/monitor/data_freshness_guard.py` + `src/monitor/__init__.py` + 16 unit tests。DataSource/HaltReason/FreshnessConfig/FreshnessStatus dataclasses + `check_staleness` + `detect_gaps` pure helpers + `DataFreshnessGuard` 狀態化（record_tick / check / should_halt）；偵測 NO_DATA / STALE / STREAM_STOP / GAP 四種 halt reason，per-source 獨立，out-of-order tick 取最新作 staleness，bounded `gap_history_window` deque。完整 pytest 604/604 GREEN。**Phase 9 起步**，下一步：等 backfill 完跑 V1 重判決，或續做 X01 (OrderRouter, 0.5d, 無依賴)。

---

# Tasks

> 機器友善：每個 task 一個 H3 區塊。grep `^### TASK-` 可列全部。
> 欄位順序固定。Session log append-only。

---

## Phase 0 — 資料盤點 + Universe + Feature Store

### TASK-D01

- **Name**: 資料盤點報告（local coverage scan）
- **Source**: V2 §0.1, §1
- **Status**: `DONE`
- **Depends**: —
- **Files**:
  - `scripts/audit_local_data.py` ✅
  - `analysis/local_data_audit.md` ✅
  - `tests/test_scripts/test_audit_local_data.py` ✅
  - `tests/test_scripts/__init__.py` ✅
- **Acceptance**:
  - 報告含每檔股票 first_date / last_date / record_count（daily / intraday / minute_kbar 分開）✅
  - 標明「可回測候選」（日線 span ≥ 730 天）✅
- **Tests (RED list)**:
  - `test_audit_returns_per_stock_coverage` ✅
  - `test_audit_flags_incomplete_stocks` ✅
  - `test_audit_separates_daily_and_minute` ✅
  - `test_render_markdown_report_includes_sections`（bonus）✅
- **DoD**:
  - 腳本可獨立跑出 markdown 報告 ✅
  - PROGRESS 候選股票數欄位：**39 檔股票掃出，0 檔達 2 年日線門檻** ⚠️
- **Key Findings**:
  - 39 檔股票有資料；最長日線約 9 個月（2025-09 ~ 2026-05）
  - intraday 覆蓋多數 ≥ 1 個月；minute_kbar 僅近 1~2 週
  - **Phase 3 回測前必須先補抓歷史日線**（至少 2 年，建議 3~5 年）
  - 此發現不改 V2 spec，但要寫入後續 task：新增「TASK-D01b：補抓歷史日線」？由用戶於下一 session 確認
- **Last updated**: 2026-05-22
- **Session log**:
  - 2026-05-22 9a38595 | RED：寫 4 個失敗測試（3 acceptance + 1 markdown smoke） | 接 GREEN
  - 2026-05-22 a903983 | GREEN：實作 audit_local_data + render_markdown_report + CLI；跑真實資料 39 stocks，0 backtest-ready | 等用戶決定是否新增補抓歷史日線 task，否則接 TASK-U01

### TASK-D01b

- **Name**: 歷史日線補抓 orchestrator（解鎖 Phase 1）
- **Source**: V2 §0.1（建議 ≥ 2 年日線）+ TASK-D01 發現 39 檔皆未達門檻
- **Status**: `DONE`（script + 實跑 + 修正完成）
- **Depends**: TASK-D01 ✅
- **Files**:
  - `scripts/backfill_historical_daily.py` ✅
  - `tests/test_scripts/test_backfill_historical_daily.py` ✅（10 tests）
- **Acceptance**:
  - Pure helpers (is_month_covered / compute_missing_months) 處理「當前月強制 refresh」「跳過已覆蓋過去月」 ✅
  - run_backfill 委派 DataFetcher.fetch_daily_history + DataStorage.save_daily_data（後者已有 dedupe + atomic）✅
  - sleep_fn 注入支援測試 + 真實 3 秒 rate limit ✅
  - 單檔錯誤不中斷整批 ✅
- **Tests (RED list)**: 10 項 全 GREEN
- **DoD**: Script + 實跑 + 修正全完成；**38/39 檔達 ≥2 年日線**（7769 IPO 上市時間不夠，內在限制）
- **Real-run results**:
  - 第一輪 35/39 ok（4 檔卡 API edge case：「查詢日期大於今日」/「上市前」）
  - FIX commit `cba24c8`：per-month try/except + DataFetcher 簽名 + StockDailyFile 欄位名
  - 第二輪 39/39 ok（idempotent，補 131 月份 / 1745 records）
  - 7769 = 2025-11-27 上市，5.8 月覆蓋，無法補
- **Last updated**: 2026-05-22
- **Session log**:
  - 2026-05-22 ffc4420 | RED：9 failing tests | 接 GREEN
  - 2026-05-22 9477345 | GREEN：scripts/backfill_historical_daily.py + 10 unit tests GREEN | 接實跑
  - 2026-05-22 cba24c8 | FIX：實跑暴露三 bug（DataFetcher 簽名、StockDailyFile.daily_data 欄位、per-stock try 太粗）；改 per-month try + 修簽名 + 修欄位後第二輪 39/39 ok | 接 TASK-S01

### TASK-D01c

- **Name**: chip + margin 歷史回補 orchestrator（解開 V1 0 trades）
- **Source**: V2 §0.1 / §0.5 + backtest_v1_report.md caveats (1)
- **Status**: `IN_PROGRESS`（script + tests DONE；實跑待跑）
- **Depends**: TASK-D01 ✅
- **Files**:
  - `scripts/backfill_historical_chips.py` ✅
  - `tests/test_scripts/test_backfill_historical_chips.py` ✅（14 tests）
- **Acceptance**:
  - Pure helpers (is_trading_day / compute_missing_dates) 處理週末跳過、雙 snapshot 缺一即補 ✅
  - date-major loop：每日 4 endpoints (TWSE/TPEX × T86/Margin) ✅
  - TWSE+TPEX merge 後存單一 daily snapshot ✅
  - per-endpoint 例外隔離（TWSE 掛不擋 TPEX）✅
  - sleep_fn 注入 + 3s rate limit between requests ✅
  - 雙 snapshot 都空 → 記 skipped_empty_days（假日 / 上市前）✅
- **Tests (RED list)**: 14 項 全 GREEN
  - is_trading_day weekday/weekend ×2
  - compute_missing_dates: empty / skips weekends / skips when both exist / includes when only one exists
  - run: 4 endpoints called / merges TWSE+TPEX / skips covered / skips weekends / continues on endpoint error / records empty day / respects sleep / report counts
- **DoD**: 14/14 GREEN + 完整 pytest 556/556 GREEN
- **Real-run pending**: 預估 ~500 trading days × 4 requests × 3s ≈ 100 min。背景跑，跑完接 run_backtest_v1 重判決
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 6d2f81b | RED：14 tests，8 fail (orchestrator NotImplementedError) + 6 pure helpers GREEN | 接 GREEN
  - 2026-05-23 a0d7c79 | GREEN：run_chips_backfill 實作（date-major + 4 endpoints merge + per-endpoint isolation + sleep DI）；14/14 GREEN，完整 pytest 556/556 GREEN | 接實跑 backfill

### TASK-U01

- **Name**: Universe Filter
- **Source**: V2 §0.2
- **Status**: `DONE`
- **Depends**: TASK-D01 ✅
- **Files**:
  - `src/universe/__init__.py` ✅
  - `src/universe/filter.py` ✅
  - `tests/test_universe/__init__.py` ✅
  - `tests/test_universe/test_filter.py` ✅（12 tests）
- **Acceptance**: V2 §0.2 全規則實作（流動性 / listing bars / 價格 / F股 / ETN / 警示 / 處置 / 全額交割 / warrant）✅
- **Tests (RED list)**: 12 項 全 GREEN
  - liquidity below / at threshold / listing_days / price / F-stock / ETN / warning / disposition / full_delivery / empty input / idempotent / point-in-time
- **DoD**: 12/12 GREEN + commits 9076abb + 2a1b641
- **Last updated**: 2026-05-22
- **Session log**:
  - 2026-05-22 9076abb | RED：12 failing tests + placeholder | 接 GREEN
  - 2026-05-22 2a1b641 | GREEN：filter_universe + StockMeta dataclass | 接 TASK-F01/F02

### TASK-F01

- **Name**: Corporate Actions / Adjusted OHLC
- **Source**: V2 §0.4
- **Status**: `DONE`
- **Depends**: TASK-D01
- **Files**:
  - `src/features/corporate_actions.py` ✅
  - `src/features/__init__.py` ✅
  - `tests/test_features/test_corporate_actions.py` ✅（6 tests）
- **Acceptance**: backward-adjusted；無 events 不變；含 flag column ✅
- **Tests (RED list)**: 6 項 全 GREEN
  - no events unchanged + flags false / cash dividend / 1:2 split / cash capital reduction / multiple events compound order / missing data flag-only
- **DoD**: 3 檔真實資料 smoke test OK（2330:102 rows, 3036:109 rows, 8046:129 rows）✅
- **Last updated**: 2026-05-22
- **Session log**:
  - 2026-05-22 ee2c407 | RED：6 failing tests（import error，corporate_actions module 尚未存在） | 接 GREEN
  - 2026-05-22 9b73a0d | GREEN：CorporateActionEvent + apply_backward_adjustment；保留 raw OHLC，新增 adj_* / is_corporate_action_day / corporate_action_factor | 接 REFACTOR
  - 2026-05-22 56a2f8a | REFACTOR：公開 corporate actions API；features tests 17/17 GREEN；3 檔真實資料 smoke OK | 接 TASK-F03

### TASK-F02

- **Name**: Feature Availability 規則表
- **Source**: V2 §0.5
- **Status**: `DONE`
- **Depends**: —
- **Files**:
  - `src/features/__init__.py` ✅
  - `src/features/availability.py` ✅
  - `tests/test_features/__init__.py` ✅
  - `tests/test_features/test_availability.py` ✅（11 tests）
- **Acceptance**: 涵蓋 daily_ohlc / minute_kbar / chips / margin / monthly_revenue / news / advisor ✅
- **Tests (RED list)**: 11 項 全 GREEN
  - daily close available_at / minute bar completion / chips T+1 pre-open / margin T+1 pre-open / weekend skip / monthly revenue announcement / news processed_at lag / news published_at / advisor generated_at / unknown feature exception / registry coverage
- **DoD**: `tests/test_features tests/test_universe tests/test_scripts` 27/27 GREEN ✅
- **Last updated**: 2026-05-22
- **Session log**:
  - 2026-05-22 1ee538c | RED：11 failing tests（import error，feature module 尚未存在） | 接 GREEN
  - 2026-05-22 9256671 | GREEN：availability_of + AVAILABILITY_RULES + UnknownFeatureError；daily/minute/chips/margin/monthly_revenue/news/advisor 規則通過 | 接 REFACTOR
  - 2026-05-22 ba23a7a | REFACTOR：公開 src.features API；27/27 related tests GREEN | 接 TASK-F01

### TASK-F03

- **Name**: Feature Store schema + manifest
- **Source**: V2 §0.3, §0.6
- **Status**: `DONE`
- **Depends**: TASK-F01 ✅, TASK-F02 ✅
- **Files**:
  - `src/features/store.py` ✅
  - `src/features/manifest.py` ✅
  - `tests/test_features/test_store.py` ✅（8 tests）
- **Acceptance**: build → MultiIndex(date, stock_id) DataFrame ✅；manifest 含 raw_range/hash + universe/schema/corp_action version + git_commit + generated_at + manifest_hash ✅；拒絕 available_at > signal_ts → LookAheadError ✅；接 backward-adjusted OHLC ✅
- **Tests (RED list)**: 8 項 全 GREEN
  - multi_index schema / provider columns / backward-adjusted OHLC / look-ahead error / deterministic build / manifest required fields / manifest persisted to cache_dir / manifest_hash stable across builds
- **DoD**: manifest 寫入 `cache_dir/manifest_<hash>.json` ✅；REFACTOR 跳過（無重複可清）
- **Last updated**: 2026-05-22
- **Session log**:
  - 2026-05-22 aca77bd | RED：8 failing tests（ModuleNotFoundError，store/manifest 模組尚未存在） | 接 GREEN
  - 2026-05-22 c2961ad | GREEN：FeatureStore + FeatureProvider + FeatureValue + LookAheadError + manifest helpers；providers 透過 adj_* 覆寫 OHLC 看到 backward-adjusted；manifest_hash 排除 generated_at 維持穩定 | 接 TASK-F04（Price Features）

### TASK-F04

- **Name**: Price Features（MA / return / ATR / vol）
- **Source**: V2 §0.3
- **Status**: `DONE`
- **Depends**: TASK-F01 ✅, TASK-F03 ✅
- **Files**:
  - `src/features/price_features.py` ✅
  - `tests/test_features/test_price_features.py` ✅（8 tests）
- **Acceptance**: MA5/10/20/60、daily return、ATR14、20d vol；provider factory 接 FeatureStore ✅
- **Tests (RED list)**: 8 項 全 GREEN
  - ma known values / ma window NaN / ma invalid window / daily return known / atr known TR / atr window guard / vol matches std of returns / providers integrate with FeatureStore
- **DoD**: 透過 `price_feature_providers()` factory 接 store；REFACTOR 跳過（純函式已乾淨）
- **Last updated**: 2026-05-22
- **Session log**:
  - 2026-05-22 f67627d | RED：8 failing tests（ModuleNotFoundError） | 接 GREEN
  - 2026-05-22 8adea95 | GREEN：moving_average / daily_return / atr / rolling_volatility + price_feature_providers factory；available_at = ref_date 13:30；first TR fallback = high-low | 接 TASK-F05

### TASK-F05

- **Name**: Volume Features（包 spike detector）
- **Source**: V2 §0.3
- **Status**: `DONE`
- **Depends**: TASK-F03 ✅
- **Files**:
  - `src/features/volume_features.py` ✅
  - `tests/test_features/test_volume_features.py` ✅（12 tests）
- **Acceptance**: 產出 volume_ratio / spike_severity / baseline_low_confidence；沿用 SPIKE_THRESHOLD_* / SpikeSeverity；shift(1) baseline 防 look-ahead ✅
- **Tests (RED list)**: 12 項 全 GREEN
  - baseline shift no look-ahead / low_conf when window未滿 / 完整視窗 not low_conf / ratio known / severity 五級 parametrize / min_abs_volume 抑制 / NaN safe / providers integrate with store
- **DoD**: 與既有 detector 共用閾值；day-level vs minute-level 分離（minute 版仍給 live UI 用）；REFACTOR 跳過
- **Note**: 沒有完全「重複包裝」既有 detector（minute K 需 storage backend），改在 day-level 重新實作同邏輯。如後續策略要 minute-level spike 入 feature，再開 TASK-F05b
- **Last updated**: 2026-05-22
- **Session log**:
  - 2026-05-22 aca5c16 | RED：12 failing tests（ModuleNotFoundError） | 接 GREEN
  - 2026-05-22 ecf36c8 | GREEN：daily_volume_baseline / daily_volume_ratio / classify_volume_severity + volume_feature_providers；以 ohlc.attrs 做 per-frame 記憶化 | 接 TASK-F06

### TASK-F06

- **Name**: Chip Features
- **Source**: V2 §0.3
- **Status**: `DONE`
- **Depends**: TASK-F03 ✅
- **Files**:
  - `src/features/chip_features.py` ✅
  - `tests/test_features/test_chip_features.py` ✅（8 tests）
- **Acceptance**: foreign_net 即時 + streak + 5d cumulative；margin_balance / short_balance + 5 日變化；provider 防 look-ahead；available_at=08:30 ✅
- **Tests (RED list)**: 8 項 全 GREEN
  - foreign streak positive run / breaks on negative / zero resets / rolling 5d / margin 5d change / provider 用 T-1 chip 防 look-ahead / 無資料回 NaN / 完整欄位接 store
- **DoD**: providers 透過 chips_by_stock + margin_by_stock dict 傳入；REFACTOR 跳過
- **Last updated**: 2026-05-22
- **Session log**:
  - 2026-05-22 1a99345 | RED：9 failing tests（ModuleNotFoundError） | 接 GREEN
  - 2026-05-22 1bc18be | GREEN：foreign_net_streak / rolling_net_buy / margin_n_day_change + chip_feature_providers；row 日期 T 取 chip[<T] 最後筆 + available_at=ref_date 08:30 滿足 V2 §0.5 pre-open 規則 | 接 TASK-F07

### TASK-F07

- **Name**: News Features
- **Source**: V2 §0.3, §0.5
- **Status**: `DONE`
- **Depends**: TASK-F03 ✅
- **Files**:
  - `src/features/news_features.py` ✅
  - `tests/test_features/test_news_features.py` ✅（10 tests）
- **Acceptance**: news_count / news_severity / news_direction_score / news_anomaly 接 store；published_at > 13:30 / 週末 roll 到下一交易日避免 look-ahead ✅
- **Tests (RED list)**: 10 項 全 GREEN
  - effective_date before/after close / Fri-after-close → Mon / weekend → Mon / aggregate counts+severity / direction up/down/neutral / no news → 0 / 盤後 roll 次日 / anomaly flag / 多檔股票分流
- **DoD**: NewsRecord 簡化欄位（stock_id/published_at/impact_score/direction），與既有 news_models.NewsArticle 解耦；REFACTOR 跳過
- **Last updated**: 2026-05-22
- **Session log**:
  - 2026-05-22 6ff373d | RED：10 failing tests（ModuleNotFoundError） | 接 GREEN
  - 2026-05-22 ed6cde4 | GREEN：NewsRecord + assign_effective_date + aggregate_news_by_day + news_feature_providers；anomaly flag = news_count > shift(1) rolling baseline × multiplier | 接 TASK-F08

### TASK-F08

- **Name**: Regime Features
- **Source**: V2 §6.1
- **Status**: `DONE`
- **Depends**: TASK-F04 ✅
- **Files**:
  - `src/features/regime_features.py` ✅
  - `tests/test_features/test_regime_features.py` ✅（7 tests）
- **Acceptance**: 大盤 MA / ADX / vol 分位 + provider 廣播到所有股票 ✅
- **Tests (RED list)**: 7 項 全 GREEN
  - market MA known / ADX 強趨勢 > 20 / 平盤 < 25 (DX=0 fallback) / vol_rank ∈ [0,1] / spike rank 安全 / providers 廣播同值 / 缺 market date 不 crash
- **DoD**: 簡化 ADX (rolling mean 代替 Wilder smoothing)；REFACTOR 跳過
- **Last updated**: 2026-05-22
- **Session log**:
  - 2026-05-22 f79a2fb | RED：7 failing tests | 接 GREEN
  - 2026-05-22 d64db21 | GREEN：market_moving_average + adx (含平盤 0 處置) + vol_percentile_rank + regime_feature_providers | 接 TASK-B03

### TASK-B03

- **Name**: Benchmark engine
- **Source**: V2 §3.5
- **Status**: `DONE`
- **Depends**: TASK-F04 ✅
- **Files**:
  - `src/backtest/benchmark.py` ✅
  - `tests/test_backtest/test_benchmark.py` ✅（8 tests）
  - `analysis/benchmarks.html` ⏸ (待真實 market data 接入後再生成)
- **Acceptance**: compute_benchmarks 回傳五條累積報酬曲線 (weighted_index / etf_total_return / equal_weight_universe / ma_strategy / cash)；MA 策略用 shift(1) 防 look-ahead ✅
- **Tests (RED list)**: 8 項 全 GREEN
  - 五條 key 全在 / 長度對齊 / buy-and-hold 起點 1.0 / cash 常數 1.0 / 等權 ≠ 市值權 / 含息 > 不含息 / MA 多頭趨勢正報酬 / 空 market_index raises
- **DoD**: 全期間累積曲線可生成；plot 留到 Phase 3 接真實資料；REFACTOR 跳過
- **Last updated**: 2026-05-22
- **Session log**:
  - 2026-05-22 ed1c15e | RED：8 failing tests | 接 GREEN
  - 2026-05-22 3ef072a | GREEN：compute_benchmarks + BenchmarkInputError；MA 策略 shift(1) 防 look-ahead；equal-weight = cross-section mean | Phase 0 全 DONE，下一 task 進 Phase 1 (TASK-S01 IC analysis)

---

## Phase 1 — IC 分析

### TASK-S01

- **Name**: IC / decay / 單調性分析
- **Source**: V2 §1
- **Status**: `DONE`
- **Depends**: TASK-F03~F08 ✅
- **Files**:
  - `src/signals/ic_analysis.py` ✅
  - `tests/test_signals/test_ic_analysis.py` ✅（16 tests）
  - `scripts/run_ic_analysis.py` ✅（orchestrator）
  - `tests/test_scripts/test_run_ic_analysis.py` ✅（5 tests）
  - `analysis/ic_report.md` ✅
- **Acceptance**: compute_ic / decay_curve / monotonicity_test / meets_ic_threshold ✅；IC_THRESHOLDS = {1: 0.02, 5: 0.03, 20: 0.04} 對齊 V2 §1 修訂 ✅；orchestrator 跑 38+1 真實 universe 產 markdown ✅
- **Tests (RED list)**: 21 項 全 GREEN
  - primitives 16: required fields / random ≈ 0 / perfect = 1 / NaN robust / negative=-1 / decay per-horizon dict / decay 衰減訊號遞減 / monotonicity n_groups / 強訊號遞增 / threshold 6 parametrize / IC_THRESHOLDS 符合 V2
  - orchestrator 5: load_daily_frames / forward_returns h=1,5 / render markdown / end-to-end run
- **Real-run findings (analysis/ic_report.md)**:
  - 1d horizon 全 FAIL（短期 IC 太弱）
  - 5d PASS：ma_5 / ma_10 / ma_20 / atr_14 / vol_20
  - 20d PASS：ma_5 / ma_10 / ma_20 / ma_60 / atr_14 / vol_20 / baseline_low_confidence (n=40 不可靠)
  - daily_return / volume_ratio 全 FAIL
- **DoD**: pure functions + orchestrator + 報告齊全；scipy 加入 pyproject.toml deps
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-22 d4d0fb9 | RED：13 failing tests + scipy 加 deps | 接 GREEN
  - 2026-05-22 b3e35af | GREEN primitives：compute_ic / decay_curve / monotonicity_test / meets_ic_threshold + IC_THRESHOLDS | 接 orchestrator
  - 2026-05-22 ea1e129 | RED orchestrator：5 failing tests | 接 GREEN
  - 2026-05-23 4511fd9 | GREEN orchestrator：load_daily_frames + forward_returns + render_ic_report + run_ic_analysis + 跑真實資料產 analysis/ic_report.md | 接 TASK-D02 決策

### TASK-D02

- **Name**: IC 報告決策點
- **Source**: V2 §8
- **Status**: `DONE`
- **Depends**: TASK-S01 ✅
- **Files**:
  - `analysis/ic_report.md` ✅
- **Decision**: **進 Phase 2（SignalEngine）**
- **理由**：
  - 至少 5 個 feature 過 5d 門檻：`ma_5`, `ma_10`, `ma_20`, `atr_14`, `vol_20`
  - 20d 多 6 個過門檻（含 `ma_60`）
  - 統計顯著（p < 0.05 多數情況），ic_mean 0.03~0.11 屬合理範圍
- **限制 / 後續注意**：
  1. **1d horizon 全 FAIL** → 第一版策略**不做日內訊號**，只做 5d/20d holding
  2. ic_mean 落在 0.03~0.11 屬「能用但不強」，需配合 cost model 與 walk-forward 才能定生死
  3. `daily_return` / `volume_ratio` 全 FAIL — 不單獨入訊號，但可做 reversal/confirmation 過濾條件
  4. `baseline_low_confidence` 20d PASS 但 n=40 樣本不足，不可信
  5. 尚未跑 chip / news / regime feature IC（orchestrator 暫只接 price/volume）— Phase 1.5 補
- **Action items 給 Phase 2**:
  - TASK-S03 long-entry：用 ma trend + atr 過濾 + vol regime；holding 目標 5~20d
  - TASK-S04 exits：基於 atr 停損 + 時間出場（5d~20d）
- **Tests**: 不適用（純決策）
- **DoD**: PROGRESS / README / ic_report 三方同步 ✅
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 | 依 analysis/ic_report.md 內容做決策；判定「進 Phase 2」並記錄 5d/20d PASS feature list 與限制 | 接 TASK-S02

---

## Phase 2 — SignalEngine

### TASK-S02

- **Name**: Signal dataclass + Engine 框架
- **Source**: V2 §2
- **Status**: `DONE`
- **Depends**: TASK-F03 ✅
- **Files**:
  - `src/signals/engine.py` ✅
  - `tests/test_signals/test_engine.py` ✅（7 tests）
- **Acceptance**: Signal dataclass 無 risk/stop_loss/position_size ✅；__post_init__ 驗證 action/side/confidence；to_dict/from_dict roundtrip；SignalEngine ABC 直接 instantiate 報 TypeError；子類化 generate 回 list；空輸入回 []
- **Tests (RED list)**: 7 項 全 GREEN
- **DoD**: API 凍結 — Signal + VALID_ACTIONS + VALID_SIDES
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 ea69c09 + 4a48247 | RED 7 tests + GREEN Signal dataclass + SignalEngine ABC | 接 TASK-S03

### TASK-S03

- **Name**: Long-entry rule（爆量 + 趨勢 + 籌碼）
- **Source**: V2 §2 第一版策略
- **Status**: `DONE`
- **Depends**: TASK-S02 ✅, TASK-F04~F08 ✅
- **Files**:
  - `src/signals/rules/long_entry.py` ✅
  - `tests/test_signals/test_long_entry.py` ✅（12 tests）
- **Acceptance**: V2 §2 進場 6 條件 + 避免進場 5 條件全實作；evaluate_long_entry 返回 (pass, reasons, invalidations)
- **Tests (RED list)**: 12 項 全 GREEN
  - all pass / close < ma_20 blocks / close < ma_60 blocks / no spike / red without breakout / red with breakout passes / weak chip / market < ma_60 / limit_up / long upper shadow / negative news / daily_loss breached
- **DoD**: invalidations 五項給 S04 使用；後續 LongEntryEngine 子類做 row-iteration
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 7a415a8 + c3ed23e | RED 12 tests + GREEN evaluate_long_entry + EntryConditions | 接 TASK-S04

### TASK-S04

- **Name**: Exit rules（停損 / 停利 / 時間）
- **Source**: V2 §2 出場
- **Status**: `DONE`
- **Depends**: TASK-S03 ✅
- **Files**:
  - `src/signals/rules/exits.py` ✅
  - `tests/test_signals/test_exits.py` ✅（11 tests）
- **Acceptance**: 五條出場條件獨立計算 + reasons 全列；should_exit = len(reasons) > 0 ✅
- **Tests (RED list)**: 11 項 全 GREEN
  - all clear / stop_atr / stop boundary / break_ma10 / bearish high spike / bearish low severity 不觸發 / trailing atr / trailing within atr 不觸發 / time_stop / trend still active 不觸發 / 多 reason
- **DoD**: 與 entry invalidations 對齊；後續整合測試在 Phase 3 Backtester
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 9647942 + b2b2929 | RED 11 tests + GREEN evaluate_exit + ExitConditions | Phase 2 全 DONE，接 Phase 3 (TASK-B01 Cost model)

---

## Phase 3 — Backtester

### TASK-B01

- **Name**: Cost model
- **Source**: V2 §3.2
- **Status**: `DONE`
- **Depends**: —
- **Files**:
  - `src/backtest/cost_model.py` ✅
  - `tests/test_backtest/test_cost_model.py` ✅（23 tests）
- **Acceptance**: 常數 module-top (monkeypatchable)；tick_size_for + round_to_tick + commission + round_trip_cost (含 daytrade 稅率) + slippage ✅
- **Tests (RED list)**: 23 項 全 GREEN
  - tick band 13 parametrize / round_to_tick 多區段 / commission 單邊 / round_trip normal+daytrade / slippage buy+sell / 無效 side raise / monkeypatch
- **DoD**: 全 GREEN
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 2ca4ad7 + 163cb53 | RED 22 tests + GREEN cost_model | 接 B02

### TASK-B02

- **Name**: Execution model
- **Source**: V2 §3.3, §3.7
- **Status**: `DONE`
- **Depends**: TASK-B01 ✅
- **Files**:
  - `src/backtest/execution_model.py` ✅
  - `tests/test_backtest/test_execution_model.py` ✅（14 tests）
- **Acceptance**: T→T+1 ✅ / 漲跌停作廢 ✅ / 流動性 cap 5% ✅ / partial fill ✅ / 整股 1000 股 ✅ / odd lot 另開 ✅ / settlement T+2 business days ✅
- **Tests (RED list)**: 14 項 全 GREEN
  - happy path / 鎖死兩向 / 流動性 cap / partial fill 不足取消 / lot rounding / odd lot / 結算 T+2 / 週末跳 / next_bar=None void / 常數對 spec
- **DoD**: 全 GREEN；cash ledger 的 T+2 計入由 settlement_date 表達，後續 Backtester orchestrator 接 ledger
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 a09d928 + f782c23 | RED 14 tests + GREEN Order/MarketBar/FillResult/simulate_fill/next_business_day | 接 B04（vectorbt 整合 或 自製簡易 backtester，待決策）

### TASK-B04

- **Name**: 單股回測引擎（自製，無 vectorbt）
- **Source**: V2 §3.1, §3.7
- **Status**: `DONE`
- **Depends**: TASK-S03 ✅, TASK-B02 ✅, TASK-B03 ✅
- **Files**:
  - `src/backtest/engine.py` ✅
  - `tests/test_backtest/test_engine.py` ✅（10 tests）
- **Decision**: 走自製簡易 backtester 而非 vectorbt（V2 §3.1 spec drift）。
  理由：(a) 直接綁 cost_model + execution_model 介面零摩擦；
  (b) 38 檔 × 2 年 pandas loop 跑得動；(c) 將來 grid search 需求大才上 vectorbt
- **Acceptance**: Position / Trade / BacktestResult dataclasses；run(stock_id, ohlc_df) 回 trades + equity_curve + cash_curve + final_equity；T+2 cash ledger；mark-to-market 計入 final_equity ✅
- **Tests (RED list)**: 10 項 全 GREEN
- **DoD**: cross-stock + walk-forward 整合 → 留 D03b
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 0c810cb + a0950f0 | RED 11 + GREEN BacktestEngine | 接 B05

### TASK-B05

- **Name**: Walk-forward + embargo
- **Source**: V2 §3.4
- **Status**: `DONE`
- **Depends**: TASK-B04 ✅
- **Files**:
  - `src/backtest/walk_forward.py` ✅
  - `tests/test_backtest/test_walk_forward.py` ✅（7 tests）
- **Acceptance**: walk_forward_windows IS 12mo / embargo / OOS 3mo rolling；merge_small_windows 小窗 trade<10 合併；classify_oos_confidence LOW_CONFIDENCE flag ✅
- **Tests (RED list)**: 7 項 全 GREEN
- **DoD**: 跨 universe 套用 → 留 D03b
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 17aa9e7 + 531ab47 | RED 7 + GREEN walk_forward windows / merge / classify | 接 J04

### TASK-J04

- **Name**: Experiment registry
- **Source**: V2 §3.8
- **Status**: `DONE`
- **Depends**: TASK-B04 ✅
- **Files**:
  - `src/journal/experiment_registry.py` ✅
  - `tests/test_journal/test_experiment_registry.py` ✅（7 tests）
- **Acceptance**: ExperimentRecord + ExperimentRegistry(record/lookup/list)；experiment_id = manifest sha256[:16]；同 manifest dedupe；status 支援 failed
- **Tests (RED list)**: 7 項 全 GREEN
- **DoD**: 留 D03b orchestrator 自動 record 每次跑
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 0ecaba7 + 40ff9ef | RED 7 + GREEN registry | 接 D03 (split 為 a/b/c)

### TASK-D03

- **Name**: 首次完整回測報告（Phase 3 出口）— **拆成 D03a / D03b / D03c**
- **Source**: V2 §6.1
- **Status**: `BLOCKED: split`（拆成 3 子 task）
- **Depends**: TASK-B05 ✅, TASK-J04 ✅
- **Sub-tasks**:
  - **TASK-D03a** ✅：Adapter（evaluate_long_entry/exit → BacktestEngine deciders）
  - **TASK-D03b**：跨股 × walk-forward × BacktestEngine orchestrator → trades + equity + 寫 experiment_registry
  - **TASK-D03c**：performance metrics + benchmark 對照 + markdown 報告 + V2 §6.1 量化門檻判定
- **Reason for split**: D03 估 3-5 hr + 多輪 debug 風險高；split 後每段 ≤ 1 session，中途錯不毀整批
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 | 拆分為 D03a/b/c。D03a 已 DONE。

### TASK-D03a

- **Name**: Signal-rule adapter（D03 拆分子 task）
- **Source**: V2 §6.1（D03 配套）
- **Status**: `DONE`
- **Depends**: TASK-S03 ✅, TASK-S04 ✅, TASK-B04 ✅
- **Files**:
  - `src/backtest/adapters/signal_adapter.py` ✅
  - `tests/test_backtest/test_signal_adapter.py` ✅（8 tests）
- **Acceptance**: build_entry_conditions / build_exit_conditions 從 feature row 提取（缺欄位安全預設 → 阻擋 signal）；make_entry_decider / make_exit_decider 產出 BacktestEngine 可吃的 callable
- **Tests (RED list)**: 8 項 全 GREEN
- **DoD**: 純函式 + closure；orchestrator 引用待 D03b
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 2793932 + 6a01d69 | RED 8 + GREEN adapter | 接 D03b

### TASK-D03b

- **Name**: Cross-stock walk-forward orchestrator（D03 拆分）
- **Source**: V2 §3.4 / §3.7（D03 配套）
- **Status**: `DONE`
- **Depends**: TASK-D03a ✅, TASK-B05 ✅, TASK-J04 ✅
- **Files**:
  - `src/backtest/walk_orchestrator.py` ✅
  - `tests/test_backtest/test_walk_orchestrator.py` ✅（9 tests）
- **Acceptance**:
  - `run_walk_forward_backtest` 對 universe × windows 切 OOS slice → 每股 BacktestEngine.run → 彙總 ✅
  - decider factory 注入（預設搭 signal_adapter.make_entry/exit_decider，但 API 允許任意 callable，方便 grid search） ✅
  - 空 OOS slice 不 crash ✅
  - combined_equity = 各股 equity sum 對齊 ✅
  - 可選 registry.record(manifest + summary) → experiment_id ✅
- **Tests (RED list)**: 9 項 全 GREEN
  - per-stock×window engine call / OOS date slicing / multi-stock trade aggregation / empty slice skip / combined equity sum / registry record / no-registry → id=None / window_result fields / multi-window
- **DoD**: 9/9 GREEN + backtest suite 79/79 GREEN；REFACTOR 跳過（pure func + closure 已乾淨）
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 a31523a | RED：9 failing tests + skeleton（NotImplementedError） | 接 GREEN
  - 2026-05-23 189315f | GREEN：run_walk_forward_backtest 全邏輯 + WindowResult/OrchestratorResult dataclass + manifest 自動補 universe/windows + summary={trade_count, n_windows, total_pnl} | 接 TASK-D03c

### TASK-D03c

- **Name**: Performance + benchmark + report + 決策（D03 拆分）
- **Source**: V2 §6.1
- **Status**: `DONE`（gating logic 完成；實跑報告留待接真實 feature pipeline）
- **Depends**: TASK-D03b ✅
- **Files**:
  - `src/journal/performance.py` ✅（PerformanceMetrics + 8 metric 函式 + summarize_performance）
  - `src/journal/decision.py` ✅（DecisionInput/Result + evaluate_v2_thresholds + module-top thresholds）
  - `src/journal/backtest_report.py` ✅（render_backtest_report markdown 渲染）
  - `tests/test_journal/test_performance.py` ✅（18 tests）
  - `tests/test_journal/test_decision.py` ✅（11 tests）
  - `tests/test_journal/test_backtest_report.py` ✅（4 tests）
  - `analysis/backtest_v1_report.md` ⏸（待接 D03b orchestrator + 真實 universe/feature_df 後執行）
- **Acceptance**:
  - metrics: 總報酬 / Sharpe / Sortino / max DD / win rate / profit factor / expectancy_bp / turnover ✅
  - V2 §6.1 全 10 項門檻判定 ✅（含 trade count ≥ 50 / regime coverage 1+1+1 / benchmark beat / oos_alpha）
  - markdown 報告含 verdict (PASS/FAIL) + 失敗原因 ✅
- **Tests (RED list)**: 33 項 全 GREEN
- **DoD**: gating + reporting 完成；實跑階段為 V2 §6.1 決策觸發點，需有真實 backtest 結果後執行
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 62b52c7 | RED：33 failing tests + 3 skeleton modules（NotImplementedError） | 接 GREEN
  - 2026-05-23 dfbbd07 | GREEN：performance.py + decision.py + backtest_report.py 全實作；profitability cross-suite 268/268 GREEN | Phase 3 全 8/8 DONE，下一階段：實跑 D03c 報告 OR 進 Phase 4

### TASK-D03d

- **Name**: Market regime classifier（D03 caveats #3 / Phase 6 S05 前置）
- **Source**: V2 §6.1（regime_coverage check）+ backtest_v1_report caveats (3)
- **Status**: `DONE`
- **Depends**: TASK-F08 ✅（regime_features 之上的 discrete labeller）
- **Files**:
  - `src/backtest/regime_classifier.py` ✅
  - `tests/test_backtest/test_regime_classifier.py` ✅（13 tests）
- **Acceptance**:
  - `Regime` enum {BULL, BEAR, RANGE} ✅
  - `RegimeCoverage` dataclass (bull/bear/range counts) ✅
  - `classify_regime(market_ohlc, ref_date)` MA-based labeller（BULL = close>MA200 AND MA50>MA200；BEAR 反向；RANGE 其餘含 flat）✅
  - `classify_window(market_ohlc, start, end)` Counter.most_common ✅
  - `count_regime_coverage(windows, market_ohlc)` 餵入 DecisionInput.regime_coverage_* ✅
  - 缺資料（slow MA NaN）/ 未知日期 → None ✅
- **Tests (RED list)**: 13 項 全 GREEN
  - enum sanity / BULL / BEAR / RANGE flat / unknown date / insufficient history / window dominant / window unclassifiable / window mixed / count single / count multi / count skips unclassifiable / count empty
- **DoD**: 13/13 GREEN + 完整 pytest 569/569 GREEN
- **Next**: 接 walk_orchestrator 把 OOS windows 餵入 count_regime_coverage，產出 regime_coverage_* 給 evaluate_v2_thresholds（留待 backfill 跑完重跑 run_backtest_v1 時整合）；S05 regime gating 可直接吃 classify_regime
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 7802934 | RED：13 tests，12 fail (stubs) + 1 enum GREEN | 接 GREEN
  - 2026-05-23 cff8f70 | GREEN：MA-based classifier 三函式 + flat-market range test fix；13/13 GREEN，完整 pytest 569/569 GREEN | 接 S05 OR backfill 跑完整合 walk_orchestrator

### TASK-D03e

- **Name**: Walk-forward IS extension + oos_is_ratio helper（D03 caveats #4）
- **Source**: V2 §6.1（oos_is_ratio decision check）+ backtest_v1_report caveats (4)
- **Status**: `DONE`
- **Depends**: TASK-D03b ✅, TASK-D03c performance.oos_is_ratio ✅
- **Files**:
  - `src/backtest/walk_orchestrator.py` ✅（extended）
  - `tests/test_backtest/test_walk_orchestrator_is_extension.py` ✅（7 tests）
- **Acceptance**:
  - WindowResult / OrchestratorResult 加 is_trades / is_per_stock_equity / is_combined_equity / is_all_trades（safe defaults，9 個既有 orchestrator test 不破）✅
  - `include_is=False` 預設保留舊行為 ✅
  - `include_is=True` 對每個 window 切 IS slice，跑同樣 decider factories，獨立 engine run ✅
  - Experiment manifest summary 在 include_is=True 時加 `is_trade_count` / `is_total_pnl` ✅
  - `compute_oos_is_ratio_from_result(result)` 接 performance.total_return + oos_is_ratio，empty / zero IS return → 0.0 ✅
  - 抽 `_run_slice` 共用 engine-driving loop，IS / OOS bit-identical ✅
- **Tests (RED list)**: 7 項 全 GREEN（+ 9 個既有 orchestrator test 不變）
  - default include_is False fields empty / IS slice engine call / aggregate fields populated / OOS not polluted regression / ratio helper math / zero IS handle / empty curve → 0
- **DoD**: 16/16 (7 new + 9 existing) GREEN，完整 pytest 588/588 GREEN
- **Next**: ~~scripts/run_backtest_v1 加 `include_is=True` + 把 `compute_oos_is_ratio_from_result` 接到 DecisionInput.oos_is_ratio；待 backfill 跑完一起做~~ **DONE 2026-05-23**（V1 重判決 plumbing prep；見 Global Session Log）
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 fe70880 | RED：7 tests，6 fail (IS extension + ratio helper) + 1 default-behaviour GREEN | 接 GREEN
  - 2026-05-23 2d6e3ce | GREEN：include_is flag + _run_slice + IS aggregate fields + ratio helper；7/7 + 9 既有 GREEN，完整 pytest 588/588 GREEN | 接 D01d news cron OR 等 backfill 完跑 V1

---

## Phase 4 — Risk + Sizing

### TASK-R01

- **Name**: RiskManager
- **Source**: V2 §4.2
- **Status**: `DONE`
- **Depends**: TASK-S02
- **Files**:
  - `src/portfolio/__init__.py` ✅
  - `src/portfolio/risk_manager.py` ✅
  - `tests/test_portfolio/__init__.py` ✅
  - `tests/test_portfolio/test_risk_manager.py` ✅（10 tests）
- **Acceptance**: 單筆 / 每日 / 連虧冷卻 ✅；另含最大持股數與單股 allocation cap ✅
- **Tests (RED list)**: 10 項 全 GREEN
  - 單筆風險允許 / 擋單 / reduce_to_fit ✅
  - 最大持股數（新股擋、既有股不重算）✅
  - 單股資金占比 15% 擋單 ✅
  - 每日虧損 -2% 擋當日剩餘訊號 ✅
  - 連虧 3 次 half-size、連虧 5 次 cooldown、獲利重置 ✅
- **DoD**: R01 10/10 GREEN；相關 suite 45/45 GREEN；完整 pytest 受本機缺 `scipy` 影響 collection 中斷
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 88e5c5e | RED：新增 10 個 RiskManager 測試，因 `src.portfolio` 尚未存在而 fail | 接 GREEN
  - 2026-05-23 26fbdc7 | GREEN：實作 RiskConfig/RiskState/RiskDecision/PositionSnapshot/RiskManager；R01 10/10 GREEN，相關 suite 45/45 GREEN | 接 TASK-R02

### TASK-R02

- **Name**: PositionSizer
- **Source**: V2 §4.1
- **Status**: `DONE`
- **Depends**: TASK-F04, TASK-R01
- **Files**:
  - `src/portfolio/position_sizer.py` ✅
  - `tests/test_portfolio/test_position_sizer.py` ✅（8 tests）
  - `src/portfolio/__init__.py` ✅（public exports）
- **Acceptance**: vol-target / ATR-based 兩種策略 ✅；禁用 Kelly ✅
- **Tests (RED list)**: 8 項 全 GREEN
  - vol-target 依 20 日日波動年化 sizing ✅
  - max notional cap ✅
  - lot rounding ✅
  - ATR-based = risk budget / (k × ATR) ✅
  - RiskManager multiplier ✅
  - rounded size zero → blocked ✅
  - invalid inputs raise ✅
  - feature-row adapter 支援 vol_target / atr_based 並拒絕 kelly ✅
- **DoD**: R02 8/8 GREEN；portfolio 18/18 GREEN；相關 suite 61/61 GREEN；完整 pytest 受本機缺 `scipy` 影響 collection 中斷
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 26ef190 | RED：新增 8 個 PositionSizer 測試，因 `src.portfolio.position_sizer` 尚未存在而 fail | 接 GREEN
  - 2026-05-23 cfb00a7 | GREEN：實作 PositionSizerConfig/Decision/vol_target/atr_based/size_from_features；相關 suite 61/61 GREEN | Phase 4 DONE，接 TASK-J01

---

## Phase 5 — Journal + Performance

### TASK-J01

- **Name**: TradeJournal
- **Source**: V2 §5.1
- **Status**: `DONE`
- **Depends**: TASK-B04
- **Files**:
  - `src/journal/trade_journal.py` ✅
  - `tests/test_journal/test_trade_journal.py` ✅（7 tests）
- **Acceptance**: 每筆完整快照 + cash ledger ✅；含成本拆分、partial fill metadata、settlement date ✅
- **Tests (RED list)**: 7 項 全 GREEN
  - gross/net P&L + holding days ✅
  - JSON dict roundtrip ✅
  - append-only JSONL record ✅
  - list sorted by signal timestamp ✅
  - stock_id filter ✅
  - from_backtest_trade 保留 costs + cash ledger ✅
  - summary aggregation ✅
- **DoD**: J01 7/7 GREEN；journal+backtest related 66/66 GREEN；完整 pytest 521/521 GREEN
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 13585a6 | RED：新增 7 個 TradeJournal 測試，因 `src.journal.trade_journal` 尚未存在而 fail | 接 GREEN
  - 2026-05-23 c1c7563 | GREEN：實作 TradeJournal dataclasses + append-only JSONL + from_backtest_trade + summary；完整 pytest 521/521 GREEN | 接 TASK-J02

### TASK-J02

- **Name**: SignalLog（含未進場）
- **Source**: V2 §5.2
- **Status**: `DONE`
- **Depends**: TASK-R01
- **Files**:
  - `src/journal/signal_log.py` ✅
  - `tests/test_journal/test_signal_log.py` ✅（7 tests）
- **Acceptance**: 訊號 + 是否進場 + 過濾原因 ✅；含 RiskDecision snapshot / linked trade id / summary ✅
- **Tests (RED list)**: 7 項 全 GREEN
  - 記錄 signal snapshot + entered state ✅
  - blocked signal 記錄 filter reasons + risk decision ✅
  - JSON dict roundtrip ✅
  - append-only JSONL record ✅
  - stock_id / entered filters ✅
  - summary counts + reason histogram ✅
  - from_signal + RiskDecision 建 blocked entry ✅
- **DoD**: J02 7/7 GREEN；journal+portfolio+signals related 79/79 GREEN；完整 pytest 528/528 GREEN
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 e90df41 | RED：新增 7 個 SignalLog 測試，因 `src.journal.signal_log` 尚未存在而 fail | 接 GREEN
  - 2026-05-23 c4a4f60 | GREEN：實作 SignalLogEntry + append-only JSONL + filtering + summary；完整 pytest 528/528 GREEN | 接 TASK-J03

### TASK-J03

- **Name**: Performance metrics
- **Source**: V2 §5.3
- **Status**: `DONE`
- **Depends**: TASK-J01
- **Files**:
  - `src/journal/performance.py` ✅
  - `tests/test_journal/test_performance.py` ✅（25 tests）
- **Acceptance**: 全指標 + benchmark alpha + turnover ✅；輸出 markdown 報告 ✅
- **Tests (RED list)**: 25 項 全 GREEN
  - total_return / sharpe / sortino / max_drawdown ✅
  - win_rate / profit_factor / expectancy_bp / turnover ✅
  - average_win_loss_ratio / oos_is_ratio / top_n_excluded_return / benchmark_alpha ✅
  - summarize_performance extended metrics ✅
  - render_performance_report markdown ✅
- **DoD**: J03 25/25 GREEN；journal+backtest related 80/80 GREEN；完整 pytest 535/535 GREEN
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 7b241ae | RED：補 J03 擴充指標 + markdown report 測試，缺 performance API 而 fail | 接 GREEN
  - 2026-05-23 b4e1f95 | GREEN：補平均盈虧比、OOS/IS、Top-N excluded return、benchmark alpha、performance report；完整 pytest 535/535 GREEN | Phase 5 DONE，接 TASK-R03

---

## Phase 6 — 投組層

### TASK-R03

- **Name**: Correlation Filter
- **Source**: V2 §6.2
- **Status**: `DONE`
- **Depends**: TASK-F04, TASK-R02
- **Files**:
  - `src/portfolio/correlation_filter.py` ✅
  - `tests/test_portfolio/test_correlation_filter.py` ✅（7 tests）
  - `src/portfolio/__init__.py` ✅（public exports）
- **Acceptance**: 產業 + 相關性聚類 ✅；同 cluster ≤ 2 檔 ✅；portfolio beta ≤ 1.2 ✅
- **Tests (RED list)**: 7 項 全 GREEN
  - 同 sector 高相關分群 ✅
  - 同 sector 低相關分離 ✅
  - cluster limit 擋單 ✅
  - 不同 cluster 放行 ✅
  - beta market-value weighted ✅
  - projected beta 超限擋單 ✅
  - unknown candidate 自成 cluster ✅
- **DoD**: R03 7/7 GREEN；portfolio+features related 40/40 GREEN；完整 pytest 542/542 GREEN
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 1f31cfb | RED：新增 7 個 CorrelationFilter 測試，因 `src.portfolio.correlation_filter` 尚未存在而 fail | 接 GREEN
  - 2026-05-23 a52b47d | GREEN：實作 CorrelationFilter / build_correlation_clusters / portfolio_beta_after_add；完整 pytest 542/542 GREEN | 接 TASK-S05

### TASK-S05

- **Name**: Regime gating 接入 SignalEngine
- **Source**: V2 §6.1
- **Status**: `DONE`（gate primitives；高波動部位減半併入 PositionSizer config，不在此 task）
- **Depends**: TASK-F08 ✅, TASK-S03 ✅, TASK-D03d ✅
- **Files**:
  - `src/signals/rules/regime_gate.py` ✅
  - `tests/test_signals/test_regime_gate.py` ✅（12 tests）
- **Acceptance**:
  - `RegimeGateConfig` dataclass (allowed set, pass_on_unknown, MA window overrides) ✅
  - `gate_by_regime(label, allowed, pass_on_unknown)` 純函式回 (passes, reason) ✅
  - `evaluate_regime_for_signal(market_ohlc, ref_date, config)` 整合 classify_regime + gate ✅
  - 預設 allowed = {BULL} → bear/range 擋下 ✅
  - reason 字串含 regime 名稱（`regime_bull_allowed` / `regime_bear_blocked` / `regime_unknown_blocked`）方便 journal lookup ✅
- **Tests (RED list)**: 12 項 全 GREEN
  - gate: bull pass / bear block / range block / unknown block / unknown pass via flag / custom allowed set / DEFAULT_ALLOWED_REGIMES sanity
  - evaluate: bull pass / bear block / insufficient history block / config overrides / default config
- **DoD**: 12/12 GREEN + 完整 pytest 581/581 GREEN
- **Next**: long_entry pipeline 在 features_snapshot 內已有 market_close/market_ma_60 簡版 gate；後續 LongEntryEngine 子類可以在 entry decider 前先呼叫 evaluate_regime_for_signal 做硬擋（整合測試留 backfill 跑完後做 walk_orchestrator 整合）
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 c4526f8 | RED：12 tests，11 fail (stubs) + 1 sanity GREEN | 接 GREEN
  - 2026-05-23 c258cef | GREEN：gate_by_regime + evaluate_regime_for_signal 實作；12/12 GREEN，完整 pytest 581/581 GREEN | Phase 6 全 DONE，下一階段：backfill 跑完接 walk_orchestrator 整合 + V1 重判決

---

## Phase 7 — UI

### TASK-UI01

- **Name**: 策略績效 + 訊號頁
- **Source**: V2 §7
- **Status**: `NOT_STARTED`
- **Depends**: TASK-J03
- **Files (planned)**:
  - `src/app/pages/strategy.py`
  - `src/app/callbacks_strategy.py`
- **Acceptance**: 績效曲線 / 回撤 / 訊號清單（含未進場原因） / regime 指示
- **Tests (RED list)**: smoke + callback 單元測試
- **DoD**: 主程式可開啟頁面、資料正確
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

---

## Phase 8 — Paper Trading

### TASK-P01

- **Name**: Memory router（純記憶體 paper）
- **Source**: V2 §8.2
- **Status**: `NOT_STARTED`
- **Depends**: TASK-S03, TASK-R01, TASK-R02
- **Files (planned)**:
  - `src/paper/memory_router.py`
  - `tests/test_paper/test_memory_router.py`
- **Acceptance**: 即時資料 → 假設成交 → 損益記錄
- **Tests (RED list)**: ≥ 6 項
- **DoD**: 與 SignalEngine 整合測試
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-P02

- **Name**: Shioaji sim router
- **Source**: V2 §8.1
- **Status**: `NOT_STARTED`
- **Depends**: TASK-P01, TASK-X01
- **Files (planned)**:
  - `src/paper/shioaji_sim_router.py`
  - `tests/test_paper/test_shioaji_sim_router.py`（含 cert 時跳過 skip）
- **Acceptance**: 真實 OMS 流程 sim 環境
- **Tests (RED list)**: ≥ 5 項 mock-based
- **DoD**: 與 memory_router 交叉驗證
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-D04

- **Name**: Paper 60d 報告（Phase 8 出口）
- **Source**: V2 §8.3
- **Status**: `NOT_STARTED`
- **Depends**: TASK-P02, TASK-M01, TASK-M02
- **Files (planned)**:
  - `analysis/paper_60d_report.md`
- **Acceptance**: V2 §8.3 升級門檻全評估
- **Tests**: 不適用
- **DoD**: PROGRESS 同步決策
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

---

## Phase 9 — 監控

### TASK-M01

- **Name**: Data Freshness Guard
- **Source**: V2 §9.1
- **Status**: `DONE`
- **Depends**: —
- **Files**:
  - `src/monitor/__init__.py` ✅
  - `src/monitor/data_freshness_guard.py` ✅
  - `tests/test_monitor/__init__.py` ✅
  - `tests/test_monitor/test_data_freshness_guard.py` ✅（16 tests）
- **Acceptance**:
  - `DataSource` enum (TWSE/SHIOAJI) ✅
  - `HaltReason` enum (NO_DATA / STALE / GAP / STREAM_STOP) ✅
  - `FreshnessConfig` (max_staleness_sec / max_gap_sec / stream_timeout_sec / gap_history_window) ✅
  - `check_staleness(last_ts, now, max_sec)` pure ✅（None → False；negative age clamp 0）
  - `detect_gaps(ts_series, max_gap_sec)` pure ✅（< 2 entries → []）
  - `DataFreshnessGuard.record_tick / check / should_halt` ✅（per-source bounded deque；out-of-order tick 取最新作 staleness；should_halt 無註冊來源也回 True）
- **Tests (RED list)**: 16 項 全 GREEN
  - pure 6：staleness fresh/stale/None / detect_gaps uniform/gap/short
  - guard 10：no_data / record-then-check fresh / stale / stream_stop / gap / per-source independent / should_halt true/false / out-of-order latest wins / history window trim
- **DoD**: 16/16 GREEN + 完整 pytest 604/604 GREEN
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 93722b7 | RED：16 failing tests + skeleton（NotImplementedError） | 接 GREEN
  - 2026-05-23 98838b3 | GREEN：DataFreshnessGuard 全實作；16/16 GREEN，完整 pytest 604/604 GREEN | 接 chore mark done
  - 2026-05-23 5285959 | chore：PROGRESS Phase 9 +1 DONE / 總計 35/44 | Phase 9 起步，下一步：等 backfill 完跑 V1 OR 做 X01
- 2026-05-23 | TASK-X01 | `src/execution/order_router.py` + `src/execution/__init__.py` + 15 unit tests。OrderID/OrderState enum + LiveOrder dataclass (__post_init__ 驗 shares>0 / market 禁 limit_price / limit 要 price) + OrderStatus / Position dataclasses + `OrderRouter` runtime-checkable Protocol + `DryRunRouter` (log-only：submit → unique id `<prefix>-NNNNNN` 並記 _DryRunLogEntry；cancel → terminal state raise；query → UnknownOrderError；positions → 永遠 []) + OrderRouterError / UnknownOrderError。完整 pytest 619/619 GREEN。下一步：等 backfill 完跑 V1 OR 做 X02 (ShioajiSimRouter 需 mock Shioaji)。
- 2026-05-23 | V1 重判決 plumbing prep | `scripts/run_backtest_v1.py` 大改 + 10 unit tests：
  - 新增 `load_chip_frames(data_dir)` / `load_margin_frames(data_dir)`：走 `data/chips/*.json` `data/margin/*.json` 組成 per-stock time series（容錯 invalid JSON / missing dir）
  - 新增 `build_market_ohlc_proxy(feature_frames)`：cross-section mean → OHLC DataFrame，供 regime classifier 用
  - 新增 `make_regime_gated_entry_factory(inner_factory, market_ohlc)`：wrap base entry decider，bear/range/unknown → 短路 return None，不呼叫內層
  - `build_feature_frame(ohlc, *, chip_df, margin_df)` 改吃可選 chip/margin DF：有資料 → `foreign_net_streak` + `margin_n_day_change`；無 → neutral default
  - `run()` 接 `include_is=True` + `compute_oos_is_ratio_from_result(result)` → `DecisionInput.oos_is_ratio` + `count_regime_coverage(oos_ranges, market_ohlc)` → `regime_coverage_*` + 用 `make_regime_gated_entry_factory` 包裝 entry
  - caveats block 改寫，標明此為「V1 重判決」非 smoke
  - 10 tests GREEN（chip loader 3 / margin loader 1 / market_ohlc proxy 2 / build_feature_frame 3 / regime gate factory 1）
  - 完整 pytest 629/629 GREEN
  - **不在 PROGRESS task list 中**（D03e Next: 的後續整合工作），歸 D03e 之延伸。
  - 下一步：backfill 完成（ETA ~22:20）→ `python -m scripts.run_backtest_v1` 一鍵產 V1 §6.1 判決

### TASK-M02

- **Name**: Consistency Check
- **Source**: V2 §9.2
- **Status**: `NOT_STARTED`
- **Depends**: TASK-P01, TASK-B04
- **Files (planned)**:
  - `src/monitor/consistency_check.py`
  - `tests/test_monitor/test_consistency_check.py`
- **Acceptance**: live 訊號 vs 回測 ±2σ；落外警示
- **Tests (RED list)**: ≥ 5 項
- **DoD**: GREEN
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

---

## Phase 10 — OrderExecutor

### TASK-X01

- **Name**: OrderRouter 抽象介面 + DryRunRouter
- **Source**: V2 §10
- **Status**: `DONE`
- **Depends**: —
- **Files**:
  - `src/execution/__init__.py` ✅
  - `src/execution/order_router.py` ✅
  - `tests/test_execution/__init__.py` ✅
  - `tests/test_execution/test_order_router.py` ✅（15 tests）
- **Acceptance**:
  - `OrderRouter` Protocol (runtime_checkable) — submit / cancel / query / positions ✅
  - `LiveOrder` dataclass — stock_id/side/shares/order_type/limit_price/tif/submitted_at/client_tag + __post_init__ 驗證 ✅
  - `OrderState` enum (PENDING/SUBMITTED/PARTIAL/FILLED/CANCELLED/REJECTED) + TERMINAL_STATES frozenset ✅
  - `OrderStatus` / `Position` dataclasses ✅
  - `DryRunRouter` log-only — unique id `<prefix>-NNNNNN`、_DryRunLogEntry 記錄 submit/cancel、positions 永遠空、terminal state cancel 拋 OrderRouterError、unknown id 拋 UnknownOrderError ✅
- **Tests (RED list)**: 15 項 全 GREEN
  - LiveOrder 4：market default / limit requires price / market forbids price / shares > 0
  - Protocol 1：DryRunRouter isinstance OrderRouter
  - DryRun 10：unique ids / custom prefix / log entry / query submitted / query unknown raises / cancel marks cancelled + log / cancel unknown raises / cancel terminal raises / positions empty / multi orders independent
- **DoD**: 15/15 GREEN + 完整 pytest 619/619 GREEN
- **Last updated**: 2026-05-23
- **Session log**:
  - 2026-05-23 e989047 | RED：15 tests，11 fail (DryRunRouter NotImplementedError) + 4 LiveOrder validation pass on skeleton dataclass | 接 GREEN
  - 2026-05-23 d56466a | GREEN：DryRunRouter 全實作 + docstring；15/15 GREEN，完整 pytest 619/619 GREEN | 接 chore mark done
  - 2026-05-23 283ea1f | chore：PROGRESS Phase 10 +1 DONE / 總計 36/44 | Phase 10 起步，下一步：X02 (ShioajiSimRouter) OR 等 backfill 完跑 V1

### TASK-X02

- **Name**: ShioajiSimRouter 實作
- **Source**: V2 §10
- **Status**: `NOT_STARTED`
- **Depends**: TASK-X01
- **Files (planned)**:
  - `src/execution/shioaji_sim_router.py`
  - `tests/test_execution/test_shioaji_sim_router.py`
- **Acceptance**: 串 Shioaji sim API；mock-based 測試
- **Tests (RED list)**: ≥ 5 項
- **DoD**: GREEN
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-X03

- **Name**: ShioajiLiveRouter 實作（最後）
- **Source**: V2 §10, §8.3
- **Status**: `NOT_STARTED`
- **Depends**: TASK-D04 全通過
- **Files (planned)**:
  - `src/execution/shioaji_live_router.py`
  - `tests/test_execution/test_shioaji_live_router.py`
- **Acceptance**: 含 fail-safe / kill-switch / 連線斷線處理
- **Tests (RED list)**: ≥ 8 項
- **DoD**: 演練 ≥ 30 天無重大誤報後才開
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

---

# 附錄

## A. 如何更新本檔（session 結束 checklist）

1. 更新「Quick Status」表上方欄位
2. 更新「Phase Summary」計數
3. 在每個有改動的 task 區塊更新 `Status` / `Last updated`
4. 在該 task 「Session log」append 一行：
   ```
   - YYYY-MM-DD <commit-sha> | <做了什麼> | <下一 session hint>
   ```
5. 若有 V2 修訂建議 → append 到「V2 修訂候選」
6. 「Global Session Log」append 一行
7. Commit 本檔

## B. Status 流轉指引

```
NOT_STARTED → 拉到 IN_PROGRESS（拿到 task）
IN_PROGRESS → RED（測試寫完且 fail）
RED         → GREEN（最小實作 pass）
GREEN       → REFACTORED（重構 + pytest GREEN）
REFACTORED  → DONE（commit + PROGRESS 更新）
任何狀態   → BLOCKED（卡住 + 明寫原因 + 開新 task）
```

## C. Phase 出口決策 task（D 系列）

| Task | 含義 |
|------|------|
| TASK-D01 | 資料夠不夠 |
| TASK-D02 | IC 過不過門檻 |
| TASK-D03 | 回測過不過 V2 §6.1 量化門檻 |
| TASK-D04 | Paper 過不過 V2 §8.3 升級門檻 |

任一 D-task 未通過 → 不可進下一 phase。
