# Profitability Implementation Progress

> **State of the world.** 每次 session 開始**先讀此檔**，結束**必更新**。
> 規格：`specs/profitability/PROFITABILITY_PLAN_V2.md`。流程：`specs/profitability/IMPLEMENTATION_PLAN.md`。

---

## Quick Status

| 欄位 | 值 |
|------|----|
| 上次更新 | 2026-05-22 |
| 上次 session | TASK-F02 完成（RED → GREEN → REFACTOR → DONE）；Feature Availability 規則表已建立 |
| 當前 phase | Phase 0 |
| 當前 task | — |
| 下一個建議 task | **TASK-F01**（Corporate Actions / Adjusted OHLC，解鎖 TASK-F03 前置依賴） |
| 全域 blocked | ⚠️ 39 檔股票全數**未達 2 年日線**（最長 ~9 個月，2025-09~2026-05）。Phase 3 回測啟動前須補抓歷史日線。 |
| Pytest 狀態 | profitability 相關 27/27 GREEN；完整 pytest 250 passed / 5 failed（既有 shioaji/market_strip 5 fails，pre-existing） |
| 檔案位置 | `specs/profitability/` + `src/features/availability.py` + `src/universe/filter.py` + `scripts/audit_local_data.py` + `analysis/local_data_audit.md` |
| Repo 是否乾淨 | main：TASK-F02 RED/GREEN/REFACTOR/DONE 已完成；未 push；仍有未追蹤 `.antigravitycli/`、`.claude/` |

---

## Phase Summary

| Phase | Tasks | DONE | IN_PROGRESS | NOT_STARTED | BLOCKED |
|-------|-------|------|-------------|-------------|---------|
| 0 — Universe + Feature Store | 11 | 3 | 0 | 8 | 0 |
| 1 — IC 分析 | 2 | 0 | 0 | 2 | 0 |
| 2 — SignalEngine | 3 | 0 | 0 | 3 | 0 |
| 3 — Backtester | 6 | 0 | 0 | 6 | 0 |
| 4 — Risk + Sizing | 2 | 0 | 0 | 2 | 0 |
| 5 — Journal + Perf | 3 | 0 | 0 | 3 | 0 |
| 6 — Portfolio | 2 | 0 | 0 | 2 | 0 |
| 7 — UI | 1 | 0 | 0 | 1 | 0 |
| 8 — Paper | 3 | 0 | 0 | 3 | 0 |
| 9 — Monitor | 2 | 0 | 0 | 2 | 0 |
| 10 — OrderExecutor | 3 | 0 | 0 | 3 | 0 |
| **總計** | **38** | **3** | **0** | **35** | **0** |

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
- **Status**: `NOT_STARTED`
- **Depends**: TASK-D01
- **Files (planned)**:
  - `src/features/corporate_actions.py`
  - `tests/test_features/test_corporate_actions.py`
- **Acceptance**: backward-adjusted；無 events 不變；含 flag column
- **Tests (RED list)**: ≥ 6 項
- **DoD**: 至少 3 檔股票 smoke test
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

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
- **Status**: `NOT_STARTED`
- **Depends**: TASK-F01, TASK-F02
- **Files (planned)**:
  - `src/features/store.py`
  - `src/features/manifest.py`
  - `tests/test_features/test_store.py`
- **Acceptance**: build → DataFrame；manifest 完整；拒絕 look-ahead
- **Tests (RED list)**: 正確性 / manifest / look-ahead exception / 重現性
- **DoD**: manifest 寫入 `data/cache/feature_store/manifest_<hash>.json`
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-F04

- **Name**: Price Features（MA / return / ATR / vol）
- **Source**: V2 §0.3
- **Status**: `NOT_STARTED`
- **Depends**: TASK-F01, TASK-F03
- **Files (planned)**:
  - `src/features/price_features.py`
  - `tests/test_features/test_price_features.py`
- **Acceptance**: 計算 MA5/10/20/60、daily return、ATR14、20d vol；對齊 store schema
- **Tests (RED list)**: 每個 feature 至少 1 個 known 對照 + 邊界
- **DoD**: 接入 store
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-F05

- **Name**: Volume Features（包 spike detector）
- **Source**: V2 §0.3
- **Status**: `NOT_STARTED`
- **Depends**: TASK-F03
- **Files (planned)**:
  - `src/features/volume_features.py`
  - `tests/test_features/test_volume_features.py`
- **Acceptance**: 包裝 `processor/volume_spike_detector.py`，輸出 spike_severity / volume_ratio / baseline_low_confidence column
- **Tests (RED list)**: 不偷看（baseline 只用 T 之前）+ 各 severity
- **DoD**: 與既有 detector 行為一致
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-F06

- **Name**: Chip Features
- **Source**: V2 §0.3
- **Status**: `NOT_STARTED`
- **Depends**: TASK-F03
- **Files (planned)**:
  - `src/features/chip_features.py`
  - `tests/test_features/test_chip_features.py`
- **Acceptance**: 三大法人 net buy / 連續日數 / 融資融券 5日變化
- **Tests (RED list)**: 缺資料 / 邊界 / available_at = T+1 開盤前
- **DoD**: 接 store
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-F07

- **Name**: News Features
- **Source**: V2 §0.3
- **Status**: `NOT_STARTED`
- **Depends**: TASK-F03
- **Files (planned)**:
  - `src/features/news_features.py`
  - `tests/test_features/test_news_features.py`
- **Acceptance**: news_impact.severity 聚合到 stock-day；anomaly flag
- **Tests (RED list)**: published_at 限制 / 多新聞合併 / 無新聞
- **DoD**: 接 store
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-F08

- **Name**: Regime Features
- **Source**: V2 §6.1
- **Status**: `NOT_STARTED`
- **Depends**: TASK-F04
- **Files (planned)**:
  - `src/features/regime_features.py`
  - `tests/test_features/test_regime_features.py`
- **Acceptance**: 大盤 MA60、ADX14、30d vol 分位
- **Tests (RED list)**: ≥ 4 項
- **DoD**: 接 store
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-B03

- **Name**: Benchmark engine
- **Source**: V2 §3.5
- **Status**: `NOT_STARTED`
- **Depends**: TASK-F04
- **Files (planned)**:
  - `src/backtest/benchmark.py`
  - `tests/test_backtest/test_benchmark.py`
  - `analysis/benchmarks.html`
- **Acceptance**: 五條基準（加權報酬指數 / 0050 含息 / 等權 universe / MA20>MA60 / cash）
- **Tests (RED list)**: ≥ 6 項
- **DoD**: 全期間累積報酬曲線 + plot
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

---

## Phase 1 — IC 分析

### TASK-S01

- **Name**: IC / decay / 單調性分析
- **Source**: V2 §1
- **Status**: `NOT_STARTED`
- **Depends**: TASK-F03 ~ F08
- **Files (planned)**:
  - `src/signals/ic_analysis.py`
  - `tests/test_signals/test_ic_analysis.py`
- **Acceptance**:
  - `compute_ic(feature, returns) -> {ic_mean, ic_std, ic_ir, p_value}`
  - `decay_curve(holding_days=[1,5,20])`
  - `monotonicity_test(n_groups=5)`
  - 門檻：1d ≥ 0.02 / 5d ≥ 0.03 / 20d ≥ 0.04
- **Tests (RED list)**: random ≈ 0 / perfect = 1 / NaN robust / decay 單調
- **DoD**: 產出 `analysis/ic_report.md`
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-D02

- **Name**: IC 報告決策點
- **Source**: V2 §8
- **Status**: `NOT_STARTED`
- **Depends**: TASK-S01
- **Files (planned)**:
  - `analysis/ic_report.md`（更新決策）
- **Acceptance**:
  - PROGRESS 記錄哪些 feature 過門檻
  - 「進 Phase 2」或「回頭調 feature」二選一明寫
- **Tests**: 不適用（純決策）
- **DoD**: PROGRESS 與本檔同步
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

---

## Phase 2 — SignalEngine

### TASK-S02

- **Name**: Signal dataclass + Engine 框架
- **Source**: V2 §2
- **Status**: `NOT_STARTED`
- **Depends**: TASK-F03
- **Files (planned)**:
  - `src/signals/engine.py`
  - `tests/test_signals/test_engine.py`
- **Acceptance**: Signal dataclass 無 risk 欄位；Engine 可子類化；空輸入回 []
- **Tests (RED list)**: ≥ 5 項
- **DoD**: API 凍結
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-S03

- **Name**: Long-entry rule（爆量 + 趨勢 + 籌碼）
- **Source**: V2 §2 第一版策略
- **Status**: `NOT_STARTED`
- **Depends**: TASK-S02, TASK-F04~F08
- **Files (planned)**:
  - `src/signals/rules/long_entry.py`
  - `tests/test_signals/test_long_entry.py`
- **Acceptance**: 同時滿足 6 條件；輸出 Signal with reasons
- **Tests (RED list)**: 每個條件單獨缺一 → no signal；全滿足 → signal
- **DoD**: 對 sample 股票歷史能跑出訊號清單
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-S04

- **Name**: Exit rules（停損 / 停利 / 時間）
- **Source**: V2 §2 出場
- **Status**: `NOT_STARTED`
- **Depends**: TASK-S03
- **Files (planned)**:
  - `src/signals/rules/exits.py`
  - `tests/test_signals/test_exits.py`
- **Acceptance**: 五條出場條件 + 任一觸發即出
- **Tests (RED list)**: 每條件一個 case
- **DoD**: 與 entry 串接整合測試
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

---

## Phase 3 — Backtester

### TASK-B01

- **Name**: Cost model
- **Source**: V2 §3.2
- **Status**: `NOT_STARTED`
- **Depends**: —
- **Files (planned)**:
  - `src/backtest/cost_model.py`
  - `tests/test_backtest/test_cost_model.py`
- **Acceptance**: 現股 / 當沖 / tick rounding / slippage
- **Tests (RED list)**: ≥ 8 項（含 tick rounding 各段）
- **DoD**: GREEN
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-B02

- **Name**: Execution model
- **Source**: V2 §3.3, §3.7
- **Status**: `NOT_STARTED`
- **Depends**: TASK-B01
- **Files (planned)**:
  - `src/backtest/execution_model.py`
  - `tests/test_backtest/test_execution_model.py`
- **Acceptance**: T→T+1 / 漲跌停作廢 / 流動性 cap / partial fill / 整股 / cash ledger T+2
- **Tests (RED list)**: ≥ 10 項
- **DoD**: GREEN
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-B04

- **Name**: vectorbt 整合 + 單股回測
- **Source**: V2 §3.1, §3.7
- **Status**: `NOT_STARTED`
- **Depends**: TASK-S03, TASK-B02, TASK-B03
- **Files (planned)**:
  - `src/backtest/engine.py`
  - `tests/test_backtest/test_engine.py`
- **Acceptance**: 單股全期間回測 → 報酬曲線 + 交易明細
- **Tests (RED list)**: ≥ 5 項
- **DoD**: 跑 sample 股票，比對 benchmark
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-B05

- **Name**: Walk-forward + embargo
- **Source**: V2 §3.4
- **Status**: `NOT_STARTED`
- **Depends**: TASK-B04
- **Files (planned)**:
  - `src/backtest/walk_forward.py`
  - `tests/test_backtest/test_walk_forward.py`
- **Acceptance**: IS/OOS rolling + embargo；OOS 交易 < 10 筆 → 合併下一窗
- **Tests (RED list)**: ≥ 5 項
- **DoD**: 全 universe 跑出 OOS 報告
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-J04

- **Name**: Experiment registry
- **Source**: V2 §3.8
- **Status**: `NOT_STARTED`
- **Depends**: TASK-B04
- **Files (planned)**:
  - `src/journal/experiment_registry.py`
  - `tests/test_journal/test_experiment_registry.py`
- **Acceptance**: 每次跑回測自動記錄 manifest + 結果摘要；失敗也記
- **Tests (RED list)**: ≥ 4 項
- **DoD**: registry 可查詢、可 dedupe
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-D03

- **Name**: 首次完整回測報告（Phase 3 出口）
- **Source**: V2 §6.1
- **Status**: `NOT_STARTED`
- **Depends**: TASK-B05, TASK-J04
- **Files (planned)**:
  - `analysis/backtest_v1_report.md`
- **Acceptance**:
  - 量化門檻全評估（V2 §6.1 表）
  - 達標 → 進 Phase 4；未達 → PROGRESS 寫明回頭調哪個 task
- **Tests**: 不適用
- **DoD**: PROGRESS 同步決策
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

---

## Phase 4 — Risk + Sizing

### TASK-R01

- **Name**: RiskManager
- **Source**: V2 §4.2
- **Status**: `NOT_STARTED`
- **Depends**: TASK-S02
- **Files (planned)**:
  - `src/portfolio/risk_manager.py`
  - `tests/test_portfolio/test_risk_manager.py`
- **Acceptance**: 單筆 / 每日 / 連虧冷卻
- **Tests (RED list)**: ≥ 8 項
- **DoD**: GREEN
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-R02

- **Name**: PositionSizer
- **Source**: V2 §4.1
- **Status**: `NOT_STARTED`
- **Depends**: TASK-F04, TASK-R01
- **Files (planned)**:
  - `src/portfolio/position_sizer.py`
  - `tests/test_portfolio/test_position_sizer.py`
- **Acceptance**: vol-target / ATR-based 兩種策略
- **Tests (RED list)**: ≥ 6 項
- **DoD**: GREEN
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

---

## Phase 5 — Journal + Performance

### TASK-J01

- **Name**: TradeJournal
- **Source**: V2 §5.1
- **Status**: `NOT_STARTED`
- **Depends**: TASK-B04
- **Files (planned)**:
  - `src/journal/trade_journal.py`
  - `tests/test_journal/test_trade_journal.py`
- **Acceptance**: 每筆完整快照 + cash ledger
- **Tests (RED list)**: ≥ 6 項
- **DoD**: GREEN
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-J02

- **Name**: SignalLog（含未進場）
- **Source**: V2 §5.2
- **Status**: `NOT_STARTED`
- **Depends**: TASK-R01
- **Files (planned)**:
  - `src/journal/signal_log.py`
  - `tests/test_journal/test_signal_log.py`
- **Acceptance**: 訊號 + 是否進場 + 過濾原因
- **Tests (RED list)**: ≥ 5 項
- **DoD**: GREEN
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-J03

- **Name**: Performance metrics
- **Source**: V2 §5.3
- **Status**: `NOT_STARTED`
- **Depends**: TASK-J01
- **Files (planned)**:
  - `src/journal/performance.py`
  - `tests/test_journal/test_performance.py`
- **Acceptance**: 全指標 + benchmark alpha + turnover
- **Tests (RED list)**: ≥ 10 項
- **DoD**: 輸出 markdown 報告
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

---

## Phase 6 — 投組層

### TASK-R03

- **Name**: Correlation Filter
- **Source**: V2 §6.2
- **Status**: `NOT_STARTED`
- **Depends**: TASK-F04, TASK-R02
- **Files (planned)**:
  - `src/portfolio/correlation_filter.py`
  - `tests/test_portfolio/test_correlation_filter.py`
- **Acceptance**: 產業 + 相關性聚類；同 cluster ≤ 2 檔
- **Tests (RED list)**: ≥ 5 項
- **DoD**: GREEN
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

### TASK-S05

- **Name**: Regime gating 接入 SignalEngine
- **Source**: V2 §6.1
- **Status**: `NOT_STARTED`
- **Depends**: TASK-F08, TASK-S03
- **Files (planned)**:
  - `src/signals/rules/regime_gate.py`
  - `tests/test_signals/test_regime_gate.py`
- **Acceptance**: 弱勢 regime 停做多；高波動部位減半
- **Tests (RED list)**: ≥ 4 項
- **DoD**: 整合測試與 engine 串接
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

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
- **Status**: `NOT_STARTED`
- **Depends**: —
- **Files (planned)**:
  - `src/monitor/data_freshness_guard.py`
  - `tests/test_monitor/test_data_freshness_guard.py`
- **Acceptance**: 延遲 / 跳點 / 斷流 → 停訊號
- **Tests (RED list)**: ≥ 5 項
- **DoD**: GREEN
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

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
- **Status**: `NOT_STARTED`
- **Depends**: —
- **Files (planned)**:
  - `src/execution/order_router.py`
  - `tests/test_execution/test_order_router.py`
- **Acceptance**: Protocol + DryRunRouter 實作
- **Tests (RED list)**: ≥ 4 項
- **DoD**: GREEN
- **Last updated**: 2026-05-22
- **Session log**: _尚無_

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
