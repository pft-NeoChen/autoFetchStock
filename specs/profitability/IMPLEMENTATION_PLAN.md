# Profitability Implementation Plan（TDD）

> **這份檔案是執行手冊。** 每次 session 開始先讀此檔 + `PROGRESS.md`，結束前更新 `PROGRESS.md`。
> 規格來源：`PROFITABILITY_PLAN.md` (V1)、`PROFITABILITY_PLAN_V2.md` (V2)。

---

## 0. 三份檔案的角色（必讀）

| 檔案 | 角色 | 修改頻率 |
|------|------|----------|
| `PROFITABILITY_PLAN.md` (V1) | **意圖原檔**。記錄最初動機與粗略方向。**唯讀**，不再更新。 | 永不改 |
| `PROFITABILITY_PLAN_V2.md` (V2) | **規格正本（spec）**。所有實作以此為準。發現缺漏 → 改 V2 → 同步本檔。 | 偶爾改（spec 演進） |
| `IMPLEMENTATION_PLAN.md` (本檔) | **執行手冊**。任務拆解、TDD 流程、依賴關係。 | 偶爾改（task 增刪） |
| `PROGRESS.md` | **狀態追蹤器**。每個 task 的 status + session log。**每次工作必更**。 | 每次 session |

**衝突解決順序**：V2 spec > 本檔 task 定義 > PROGRESS 狀態。
若 V2 與本檔衝突 → 改本檔；若本檔與 PROGRESS 衝突 → 改 PROGRESS。

---

## 1. Session 銜接協定（Resume Protocol）

### Session 開始

1. 讀 `CLAUDE.md`（專案規範）
2. 讀 `specs/profitability/IMPLEMENTATION_PLAN.md`（本檔，TDD 流程 + task 列表）
3. 讀 `specs/profitability/PROGRESS.md`（目前在哪一個 task、上次 session 留言）
4. 讀 `specs/profitability/PROFITABILITY_PLAN_V2.md` 對應章節（task `source` 指向的段落）
5. `git status` + `git log -5` 確認工作樹乾淨、上次 commit
6. 若 PROGRESS 顯示某 task `IN_PROGRESS`，先讀該 task 的 session log 與已產生檔案，再決定續做或重啟
7. 若無 `IN_PROGRESS`，從 PROGRESS 找下一個 `NOT_STARTED` 且依賴已滿足的 task

### Session 結束

1. 跑 `pytest`，確認測試狀態與 PROGRESS 一致
2. 更新該 task 的 `status` 與 `last_updated`
3. 在 PROGRESS 該 task 區塊 append session log：時間、commit SHA、做了什麼、卡在哪、下一步給後續 session 的 hint
4. `git status` 確認檔案都已 commit 或明確未 commit 原因
5. 若有 spec 變更，標註 V2 是否需要修改

### 任務粒度原則

- 每個 task 必須能在**單一 session 內完成 RED → GREEN**（≤ 4 小時、≤ 500 行 diff）
- 若估超出 → 拆 task
- 拆 task 不需先寫進本檔；可直接在 PROGRESS 把 task 標 `BLOCKED: split` 並新增子 task

---

## 2. TDD 流程（每個 task 強制）

```
[RED]    1. 讀 task spec + V2 對應章節
         2. 寫測試（必須 fail）
         3. pytest 確認 RED
         4. commit: test(<task-id>): add failing tests for <feature>

[GREEN]  5. 寫最小實作讓測試過
         6. pytest 確認 GREEN
         7. commit: feat(<task-id>): minimal implementation

[REFACTOR] 8. 整理重複 / 命名 / 型別 / 文件 string
           9. pytest 仍 GREEN
           10. commit: refactor(<task-id>): clean up

[DONE]   11. 更新 PROGRESS：status=DONE, last_updated, session log
         12. commit: chore(<task-id>): mark done in PROGRESS
```

### Status 機器：

```
NOT_STARTED → RED → GREEN → REFACTORED → DONE
                ↘ BLOCKED (any time) ↗
```

| 狀態 | 意思 |
|------|------|
| `NOT_STARTED` | 還沒開始 |
| `RED` | 測試寫好且 fail，尚未實作 |
| `GREEN` | 測試通過，未重構 |
| `REFACTORED` | 重構完，pytest 仍 GREEN |
| `DONE` | PROGRESS 已標、commit 已推、依賴 task 可解鎖 |
| `BLOCKED` | 卡住，需 PROGRESS 標明原因 |

### 測試原則

- 單元測試（`tests/test_<module>/test_<file>.py`）
  - 用 `@pytest.mark.unit`
  - 必須有：正常路徑、邊界、錯誤、空輸入
- 整合測試（`tests/test_integration/`）
  - `@pytest.mark.integration`
  - 跨多模組（如 feature_store + universe）
- 不可：
  - 連外網（除非 mock）
  - 依賴 Shioaji 登入（除非 sim 模式且 cert 存在 → skip）
  - 用真實 `data/` 內容（用 `tmp_path` + fixture）

### Commit 慣例

`<type>(<task-id>): <subject>`，type ∈ {test, feat, refactor, chore, docs, fix}。
所有 commit 透過 `git-branch-commit-manager` 代理（依 CLAUDE.md 規範）。

---

## 3. 模組路徑對照（與 V2 §2 一致）

```
src/
├── universe/filter.py                  # TASK-U01
├── features/
│   ├── corporate_actions.py            # TASK-F01
│   ├── availability.py                 # TASK-F02
│   ├── store.py                        # TASK-F03
│   ├── price_features.py               # TASK-F04
│   ├── volume_features.py              # TASK-F05
│   ├── chip_features.py                # TASK-F06
│   ├── news_features.py                # TASK-F07
│   └── regime_features.py              # TASK-F08
├── signals/
│   ├── engine.py                       # TASK-S02
│   ├── ic_analysis.py                  # TASK-S01
│   └── rules/                          # TASK-S03+
├── portfolio/
│   ├── position_sizer.py               # TASK-R02
│   ├── risk_manager.py                 # TASK-R01
│   └── correlation_filter.py           # TASK-R03
├── backtest/
│   ├── cost_model.py                   # TASK-B01
│   ├── execution_model.py              # TASK-B02
│   ├── benchmark.py                    # TASK-B03
│   ├── engine.py                       # TASK-B04
│   └── walk_forward.py                 # TASK-B05
├── journal/
│   ├── trade_journal.py                # TASK-J01
│   ├── signal_log.py                   # TASK-J02
│   ├── performance.py                  # TASK-J03
│   └── experiment_registry.py          # TASK-J04
├── paper/
│   ├── shioaji_sim_router.py           # TASK-P02
│   └── memory_router.py                # TASK-P01
├── monitor/
│   ├── data_freshness_guard.py         # TASK-M01
│   └── consistency_check.py            # TASK-M02
└── execution/
    └── order_router.py                 # TASK-X01
```

---

## 4. 任務總表（依執行順序）

> 每個 task 在 `PROGRESS.md` 有獨立區塊。本表只列 **task id / name / source / depends / 預估**。
> 詳細 acceptance / tests / files 見 §5。

### Phase 0 — 資料盤點 + Universe + Feature Store

| ID | Name | V2 source | depends | est |
|----|------|-----------|---------|-----|
| TASK-D01 | 資料盤點報告（local coverage scan） | §0.1 / §1 | — | 0.5d |
| TASK-U01 | Universe Filter | §0.2 / §4 階段0.2 | TASK-D01 | 1d |
| TASK-F01 | Corporate Actions / Adjusted OHLC | §0.4 / §2 模組架構 | TASK-D01 | 1.5d |
| TASK-F02 | Feature Availability 規則表 | §0.5 | — | 0.5d |
| TASK-F03 | Feature Store schema + manifest | §0.6 / §0.3 | TASK-F01, F02 | 1.5d |
| TASK-F04 | Price Features（MA / return / ATR / vol） | §0.3 | TASK-F01, F03 | 1d |
| TASK-F05 | Volume Features（包 spike detector） | §0.3 | TASK-F03 | 0.5d |
| TASK-F06 | Chip Features | §0.3 | TASK-F03 | 0.5d |
| TASK-F07 | News Features | §0.3 | TASK-F03 | 0.5d |
| TASK-F08 | Regime Features | §6.1 | TASK-F04 | 0.5d |
| TASK-B03 | Benchmark engine（加權報酬指數 / 0050 含息 / 等權） | §3.5 | TASK-F04 | 1d |

**Phase 0 出口準則**：能對單一日期產出完整 feature DataFrame + manifest + benchmark 報酬。

### Phase 1 — IC / decay 分析

| ID | Name | V2 source | depends | est |
|----|------|-----------|---------|-----|
| TASK-S01 | IC / decay / 單調性分析 | §1 | TASK-F03~F08 | 1d |
| TASK-D02 | 第一份 IC report（決策點） | §8 | TASK-S01 | 0.5d |

**Phase 1 出口準則**：產出 `analysis/ic_report.md`。IC 全低 → 回頭調 feature；至少 1 個 feature 達門檻 → 進 Phase 2。

### Phase 2 — SignalEngine

| ID | Name | V2 source | depends | est |
|----|------|-----------|---------|-----|
| TASK-S02 | Signal dataclass + Engine 框架 | §2 | TASK-F03 | 1d |
| TASK-S03 | Long-entry rule（爆量 + 趨勢 + 籌碼） | §2 第一版策略 | TASK-S02, F04-F08 | 1.5d |
| TASK-S04 | Exit rules（停損/停利/時間） | §2 出場 | TASK-S03 | 1d |

### Phase 3 — Backtester

| ID | Name | V2 source | depends | est |
|----|------|-----------|---------|-----|
| TASK-B01 | Cost model（手續費 / 稅 / 滑價） | §3.2 | — | 0.5d |
| TASK-B02 | Execution model（T→T+1、tick rounding、partial fill） | §3.3 | TASK-B01 | 1.5d |
| TASK-B04 | vectorbt 整合 + 單股回測 | §3.1 / §3.7 | TASK-S03, B02, B03 | 2d |
| TASK-B05 | Walk-forward + embargo | §3.4 | TASK-B04 | 1.5d |
| TASK-J04 | Experiment registry | §3.8 / §5 | TASK-B04 | 0.5d |
| TASK-D03 | 首次完整回測報告（決策點） | §6.1 | TASK-B05, J04 | 1d |

**Phase 3 出口準則**：達 V2 §6.1 全部量化門檻 → 進 Phase 4；否則回頭調規則 / feature。

### Phase 4 — PositionSizer + RiskManager

| ID | Name | V2 source | depends | est |
|----|------|-----------|---------|-----|
| TASK-R01 | RiskManager（單筆風險 / 每日虧損 / 連虧冷卻） | §4.2 | TASK-S02 | 1d |
| TASK-R02 | PositionSizer（vol-target / ATR） | §4.1 | TASK-F04, R01 | 1d |

### Phase 5 — Journal + Performance

| ID | Name | V2 source | depends | est |
|----|------|-----------|---------|-----|
| TASK-J01 | TradeJournal | §5.1 | TASK-B04 | 1d |
| TASK-J02 | SignalLog（含未進場） | §5.2 | TASK-R01 | 0.5d |
| TASK-J03 | Performance metrics | §5.3 | TASK-J01 | 1d |

### Phase 6 — 投組層

| ID | Name | V2 source | depends | est |
|----|------|-----------|---------|-----|
| TASK-R03 | Correlation Filter | §6.2 | TASK-F04, R02 | 1d |
| TASK-S05 | Regime gating 接入 SignalEngine | §6.1 | TASK-F08, S03 | 0.5d |

### Phase 7 — UI

| ID | Name | V2 source | depends | est |
|----|------|-----------|---------|-----|
| TASK-UI01 | `pages/strategy.py` 績效 + 訊號頁 | §7 | TASK-J03 | 1.5d |

### Phase 8 — Paper Trading

| ID | Name | V2 source | depends | est |
|----|------|-----------|---------|-----|
| TASK-P01 | Memory router（純記憶體 paper） | §8.2 | TASK-S03, R01, R02 | 1d |
| TASK-P02 | Shioaji sim router | §8.1 | TASK-P01, TASK-X01 | 1.5d |
| TASK-D04 | Paper 60d 報告（決策點） | §8.3 | TASK-P02, M01, M02 | — |

### Phase 9 — 監控

| ID | Name | V2 source | depends | est |
|----|------|-----------|---------|-----|
| TASK-M01 | Data Freshness Guard | §9.1 | — | 1d |
| TASK-M02 | Consistency Check（live vs backtest） | §9.2 | TASK-P01, B04 | 1.5d |

### Phase 10 — OrderExecutor

| ID | Name | V2 source | depends | est |
|----|------|-----------|---------|-----|
| TASK-X01 | OrderRouter 抽象介面 + DryRunRouter | §10 | — | 0.5d |
| TASK-X02 | ShioajiSimRouter 實作 | §10 | TASK-X01 | 1d |
| TASK-X03 | ShioajiLiveRouter 實作（最後） | §10 / §8.3 | TASK-D04 全通過 | 1.5d |

---

## 5. 任務詳細規格

> 每個 task 統一格式。Acceptance 必須可驗證；Tests 必須在 RED 階段先寫。
> 為控制檔案長度，只詳列 Phase 0 ~ Phase 3 前段。後續 task 進入時，根據 V2 + PROGRESS 補完。

### TASK-D01：資料盤點報告

- **Source**: V2 §0.1, §1
- **Goal**: 跑出 local 所有 stock 的 daily / intraday / minute_kbar 覆蓋情況。
- **Files**:
  - `scripts/audit_local_data.py`（一次性腳本）
  - `analysis/local_data_audit.md`（輸出報告）
- **Acceptance**:
  - 報告含每檔股票的 first_date / last_date / record_count
  - 報告區分 daily / intraday / minute_kbar
  - 報告含「資料夠回測（≥ 2 年日線）」候選名單
- **Tests**:
  - `tests/test_scripts/test_audit_local_data.py::test_audit_returns_per_stock_coverage`
  - `tests/test_scripts/test_audit_local_data.py::test_audit_flags_incomplete_stocks`
- **DoD**:
  - `python scripts/audit_local_data.py > analysis/local_data_audit.md` 跑得過
  - PROGRESS 記錄候選股票數

### TASK-U01：Universe Filter

- **Source**: V2 §0.2, §4 階段 0.2
- **Goal**: 給定日期，輸出可交易 universe（stock_id list）。
- **Files**:
  - `src/universe/__init__.py`
  - `src/universe/filter.py`
  - `tests/test_universe/test_filter.py`
- **Acceptance**:
  - `filter_universe(date, candidates, daily_data)` 回傳 list[str]
  - 條件：20 日均額 ≥ 5000 萬 / 上市 ≥ 60 日 / 價格 ≥ 5 / 剔除 F 股 ETN 警示處置
  - F 股判定先以 `stock_id.startswith` 或 `stock_name` 含 "F-" 作 placeholder（後續可換完整清單）
- **Tests** (≥ 8 項):
  - 流動性過濾：均額不足 → 剔除
  - 流動性過濾：邊界值（剛好 5000 萬）
  - 上市天數：少於 60 → 剔除
  - 價格：< 5 → 剔除
  - F 股 / ETN / 警示 / 處置 各一個 case
  - 空輸入回傳空 list
  - 同日期重複呼叫結果一致（pure function）
- **DoD**: 全部測試 GREEN + PROGRESS 更新

### TASK-F01：Corporate Actions / Adjusted OHLC

- **Source**: V2 §0.4
- **Goal**: 對歷史 OHLC 套用 backward-adjusted（除權息、減資、拆併股）。
- **Files**:
  - `src/features/corporate_actions.py`
  - `tests/test_features/test_corporate_actions.py`
  - `data/cache/corporate_actions/`（manual 維護）
- **Acceptance**:
  - `apply_backward_adjustment(ohlc_df, events)` 回傳 adjusted OHLC
  - **Backward-adjusted**（最新價不動，往回乘調整因子）
  - 無 events → 原樣回傳
  - 缺資料時可只用 flag（`is_event_day` column）標註，不調價
- **Tests** (≥ 6 項):
  - 無 events 不變
  - 單純現金股利
  - 純股票股利（拆股 1:2）
  - 現金減資
  - 多 events 連續發生（順序正確）
  - 事件日後第一天的 high/low/open/close 全部按比例調整
- **DoD**: 測試 GREEN + 至少 3 檔股票實際資料 smoke test

### TASK-F02：Feature Availability 規則表

- **Source**: V2 §0.5
- **Goal**: 統一定義「某 feature 在哪個 timestamp 之後可用於訊號」。
- **Files**:
  - `src/features/availability.py`
  - `tests/test_features/test_availability.py`
- **Acceptance**:
  - `availability_of(feature_name, ref_timestamp) -> available_at_timestamp`
  - 涵蓋：daily_ohlc / minute_kbar / chips_institutional / margin / monthly_revenue / news / advisor
  - 規則寫成 `dict[feature_name, callable]`，可擴充
- **Tests**:
  - 日線：T 日 13:30 後可用
  - 分鐘 K：bar 完成後才可用
  - 三大法人：T+1 開盤前（依 V2 §0.5 預設最早 T+1 可用）
  - 融資融券：T+1 開盤前（依 V2 §0.5 預設最早 T+1 可用）
  - 月營收：以正式公告 timestamp
  - 新聞 / advisor：以 published_at / processed_at / generated_at
  - 預設規則：未知 feature 拋例外
- **DoD**: 全測試 GREEN

### TASK-F03：Feature Store schema + manifest

- **Source**: V2 §0.3, §0.6
- **Goal**: 統一 DataFrame schema，產出 manifest，強制 point-in-time。
- **Files**:
  - `src/features/store.py`
  - `src/features/manifest.py`
  - `tests/test_features/test_store.py`
- **Acceptance**:
  - `FeatureStore(...).build(stock_ids, start, end) -> pd.DataFrame`
  - Index = (date, stock_id)；columns = 各 feature
  - `.manifest()` 輸出 dict 含：raw data range/hash, universe version, feature schema version, corporate action version, git commit
  - 拒絕 `available_at > index_timestamp` 的資料（raise `LookAheadError`）
- **Tests**:
  - 純函式正確性
  - Manifest 完整性
  - Look-ahead 觸發例外
  - 多次 build 同樣輸入結果一致
- **DoD**: 測試 GREEN + manifest 寫入 `data/cache/feature_store/manifest_<hash>.json`

### TASK-F04 ~ F08

> 規格在進入該 task 時補完。每個遵循同一模板：
>
> - 純函式：輸入 DataFrame / Series → 輸出新 columns
> - 接 Feature Store 介面
> - 至少 6 個測試（正常 / 邊界 / 缺資料 / 不偷看）

### TASK-B03：Benchmark engine

- **Source**: V2 §3.5
- **Goal**: 計算加權報酬指數、0050 含息、universe 等權、簡單 MA 策略、現金，五條基準。
- **Files**:
  - `src/backtest/benchmark.py`
  - `tests/test_backtest/test_benchmark.py`
  - `data/cache/benchmarks/`
- **Acceptance**:
  - `compute_benchmarks(start, end) -> dict[str, pd.Series]`，每條為累積報酬曲線
  - 等權 universe 每日 rebalance（或可選 monthly）
  - 簡單 MA：MA20 > MA60 做多大盤
- **Tests** (≥ 6 項):
  - 各 benchmark 序列長度 = trading days
  - Buy-and-hold 起點為 1.0
  - 等權與單股加權結果不同
  - 含息 vs 不含息差異
  - 缺資料時拋明確錯誤
- **DoD**: 跑得出全期間五條曲線 + plot 存 `analysis/benchmarks.html`

### TASK-S01：IC / decay 分析

- **Source**: V2 §1
- **Goal**: 對 feature store 中每個 feature 跑 forward return IC。
- **Files**:
  - `src/signals/ic_analysis.py`
  - `tests/test_signals/test_ic_analysis.py`
  - `analysis/ic_report.md`
- **Acceptance**:
  - `compute_ic(feature_series, returns_series) -> {ic_mean, ic_std, ic_ir, p_value}`
  - `decay_curve(feature, holding_days=[1,5,20])` 輸出 dict
  - `monotonicity_test(feature, returns, n_groups=5)` 輸出每組 mean return
  - 門檻：1d ≥ 0.02、5d ≥ 0.03、20d ≥ 0.04（V2 補充建議）
- **Tests**: random feature IC ≈ 0；perfect feature IC = 1；含 NaN robust
- **DoD**: 報告產出，PROGRESS 標明哪些 feature 過門檻

### TASK-D02：IC 報告決策點

- **Source**: V2 §8
- **Acceptance**: 在 PROGRESS 寫明「至少 N 個 feature 過門檻 → 進 Phase 2」或「全敗 → 回頭調整哪些 feature」
- **不寫 code**，但會生 markdown 報告

### TASK-S02：Signal dataclass + Engine 框架

- **Source**: V2 §2
- **Files**:
  - `src/signals/engine.py`
  - `tests/test_signals/test_engine.py`
- **Acceptance**:
  - `Signal` dataclass 欄位（**不含 risk**）：timestamp / stock_id / action / side / score / confidence / reasons / invalidations / features_snapshot
  - `SignalEngine` 抽象介面：`generate(feature_df) -> list[Signal]`
  - 子類化機制（Rule 可插拔）
- **Tests**: dataclass 序列化、Engine 子類化、空輸入

### TASK-B01：Cost model

- **Source**: V2 §3.2
- **Files**:
  - `src/backtest/cost_model.py`
  - `tests/test_backtest/test_cost_model.py`
- **Acceptance**:
  - 常數設於 module top，可被 monkeypatch
  - `round_trip_cost(price_in, price_out, shares, is_daytrade)` 回傳成本明細 dict
  - `slippage(price, side, tick_size, spread)` 純函式
  - **Tick rounding** 函式 `round_to_tick(price)` 依台交所規則（V2 審查表補充）
- **Tests**:
  - 一般現股：手續費雙邊 + 賣方 0.3% 稅
  - 當沖：稅率 0.15%
  - Tick rounding 各價格段邊界
  - 滑價對稱性（買在 ask、賣在 bid）

### TASK-B02：Execution model

- **Source**: V2 §3.3, §3.7
- **Files**:
  - `src/backtest/execution_model.py`
  - `tests/test_backtest/test_execution_model.py`
- **Acceptance**:
  - 訊號 timestamp = T 收盤後 → 成交 timestamp = T+1 開盤
  - 漲跌停判定（±10%，前一日收盤 × 1.1 / 0.9，rounded）→ 鎖死則訊號作廢
  - 流動性 cap：單筆 ≤ 當日成交量 5%
  - Partial fill 模擬
  - 整股 1 張為單位；零股另開模式
  - Cash ledger：賣出 T+2 入帳（V2 §3.7）

### TASK-B04 ~ B05、TASK-J01~J04、後續 task

> 進入該 task 前再展開細節。模板：source / files / acceptance / tests / DoD 五段必填。

---

## 6. PROGRESS.md 規範

見 `specs/profitability/PROGRESS.md`。要點：

- 每個 task 一個 H3 區塊，固定欄位
- Session log 用 append-only 列表
- 不刪舊紀錄（除非錯誤）
- 機器友善：可被 grep `^### TASK-` 撈所有 task

---

## 7. 工具與環境

| 用途 | 工具 |
|------|------|
| 測試 | `pytest` + `pytest-cov` |
| 資料 | pandas / numpy |
| 回測 | vectorbt（待 install） |
| 統計 | scipy.stats（IC p-value） |
| 圖表 | plotly（既有） |
| Git | 全部透過 `git-branch-commit-manager` 代理（CLAUDE.md 規範） |

新增 dependency 時：改 `pyproject.toml` → `pip install -e .[dev]` → commit。

---

## 8. 緊急停止條件

任一條成立 → 立即停止實作，回頭討論：

- IC 全敗：所有 feature 都不過門檻
- 回測 OOS 期望值為負且偏離 IS > 50%
- Benchmark 全期間皆優於策略
- Paper 與回測差距 > 50%
- 任何 look-ahead bias 被偵測（測試 fail）

---

## 9. V2 修訂程序

若實作中發現 V2 spec 有問題：

1. 在當前 session **不要直接動 V2**
2. 在 PROGRESS 該 task 開「V2 修訂建議」段，敘述問題
3. Session 結束時把建議匯總到 PROGRESS 頂部「V2 修訂候選」清單
4. 下次 session 開始（或用戶確認）後才改 V2，並 commit `docs(spec): ...`
5. 修 V2 後同步本檔（task source 章節對齊）

---

## 10. 第一步明確指令（給後續 session）

讀完本檔後，第一個動作：

```
1. 開 specs/profitability/PROGRESS.md
2. 找 TASK-D01（資料盤點）
3. 按 §2 TDD 流程開始 RED
```

若 TASK-D01 已 DONE，依 PROGRESS 找下一個 `NOT_STARTED` 且 depends 全 DONE 的 task。
