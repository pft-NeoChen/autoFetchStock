# S1 Sprint 1 Comparison Report

- **Sprint window**: 2026-05-24（單日完成 4 個 experiment + V1 bootstrap）
- **規格來源**: `specs/profitability/STRATEGY_REVIEW.md §D`
- **判決出口**: `specs/profitability/STRATEGY_REVIEW.md §D.5`
- **Universe**: 139 檔（39 hand-picked + 100 random sample）/ 4yr OHLC（2022-05 ~ 2026-05）
- **Pytest 狀態**: 完整 **751/751 GREEN**

---

## 1. Experiment 比較表

| # | Task | 策略類別 | Verdict | 主要指標 | Gate 細節 |
|---|------|---------|---------|---------|---------|
| 1 | **TASK-S1-E0** | V1 trend-following bootstrap | **UNCERTAIN** | OOS expectancy_bp 點 **−41.58** / CI **[−290, +250]**；OOS sharpe 點 **−0.04** / CI **[−0.41, +0.20]**；OOS pf 點 **0.88** / CI **[0.31, 1.91]** | CI 全跨 0（profit_factor CI 跨 1.0），1000 iter trade-level resample (with replacement) |
| 2 | **TASK-S1-E1** | C0a Chip event-driven (4 triggers) | **FAIL** (4/4 triggers) | 最佳 `invtrust_anomaly_buy`：cost_adj_mean_5d 84.71 bp ✓ / cost_adj_median_5d **−13.73 bp** ✗ / spread 3.17 pp ✗ | 5 項 gate 至少 1 fail；其餘 3 triggers 多項 fail |
| 3 | **TASK-S1-E2** | C1-safe Mean reversion (BULL/RANGE) | **FAIL** (single criterion) | n_events 1265 ✓ / hit-rate 0.556 vs 0.476 spread 8 pp ✓ / cost_adj_mean_5d 55.77 bp ✓ / cost_adj_median_5d 26.14 bp ✓ / **top5pct_excluded_mean_5d −4.40 bp ✗** | 4/5 過，去 top 5% 後 mean 翻負 → edge 靠 outliers（與 V1 §6.1 同 fail mode） |
| 4 | **TASK-S1-E3** | C2 Cross-sectional momentum (12-1m) | **PASS** (raw + sector-neutral) | Raw ic_mean **0.0996** ✓ / cost-adj decile spread **3.93%** ✓；Sector-neutral ic_mean **0.0834** ✓ / cost-adj decile spread **4.69%** ✓ | 兩 variant 全過；sector-neutral spread 高於 raw → alpha 非純 sector beta |

**Sprint 1 命中率**：4 個 experiment 中 **1 個 PASS**（E3 momentum）；1 個 UNCERTAIN（E0 V1 baseline）；2 個 FAIL（E1 chip / E2 mean reversion）。

---

## 2. 各 Verdict 對應的 §D.5 出口分支

### 2.1 E0 UNCERTAIN → V1 留 baseline（不降級）

§D.5 規定「E0 V1 bootstrap CI 上界 < 0 → 把 V1 從 PROGRESS 降為 baseline-only」。我們的 CI 上界 **+250bp（OOS）/ +119bp（IS）**，遠在 0 上方 → **不觸發降級**。

**處置**：
- V1 `long_entry_v1` rule + tests + journal 保留 active
- V1 §6.1 第六次判決的「V1 缺真實 edge」結論 **被 sampling noise 弱化**（−41bp 點估計落在 CI 中段，可能只是抽樣噪音）
- 不再做 V1 內 grid search / 微調（§D.6 禁區）；但 V1 在 paper runner / live 比較中保留為 baseline
- D04 paper 60d 評估時 V1 仍是基準對照

### 2.2 E1 FAIL → C0a 全 trigger 不搬 + 不啟動 C1-panic

§D.5「任一 E1/E2 過 gate → 搬 `src/signals/rules/`」未觸發。
§D.5「C0a 過 + C1-safe 過 → 啟動 C1-panic 探索」未觸發（C0a 未過）。

**處置**：
- 4 個 chip triggers 不搬到 `src/signals/rules/chip_event_v1.py`
- C0b / C0c 不開探索（§D.6 禁區，sprint 1 期間）
- C1-panic 不開探索
- E1 報告 archive 在 `analysis/s1_e1_chip_event_report.md`，列為「籌碼事件 short-window forward drift 在 4yr / 139 檔 universe 上無 robust edge」結論

### 2.3 E2 FAIL → C1-safe 不搬 + C1-panic 不探索

同 §D.5：E2 fail by single criterion (`top5pct_excluded_mean_5d`)，與 V1 §6.1 一致的 outlier-driven failure mode。

**處置**：
- `mean_reversion_v1` 不搬到 `src/signals/rules/`
- C1-panic 不開探索（C1-safe 未過）
- E2 報告 archive 在 `analysis/s1_e2_mean_reversion_report.md`
- BEAR skip diagnostic 1938 筆作背景參考，但 §D.4 強制 BEAR hard-skip 為 spec，不重新評估

### 2.4 E3 PASS → 進入 sprint 2 cross-sectional ranking pipeline

**唯一觸發的 §D.5 正向分支**：

> E3 過 IC + decile spread → 建立 cross-sectional ranking infra（與 V1/C0a/C1 機制不同，需新 portfolio formation pipeline）→ 加入 sprint 2

E3 PASS 的關鍵差異：**raw 與 sector-neutral 雙過**，且 sector-neutral spread (4.69%) 高於 raw (3.93%) → alpha 不能用「sector beta 偽裝」解釋。J–T 12-1m momentum 是學術上已驗證的全球 anomaly，這個結果與文獻一致。

**但有四項 caveats 必須跟入 sprint 2**：

1. **Sector mapping 太粗**：50 buckets / 139 檔 → 平均 2.78 檔/bucket，多數是 singleton 或 2 檔；singleton bucket 的 sector-neutral 等於 raw。需用真實 TWSE 產業別替換 4-digit prefix heuristic。
2. **Universe survivorship bias**：39 檔 hand-picked 全是事後贏家。需擴大 universe 並做 backtest survivorship-bias-aware sampling。
3. **In-sample only**：4yr 全段一次計算 IC + decile spread，未做 walk-forward 切分。Sprint 2 必須加 walk-forward。
4. **Cost-adj spread 4.69%/月 年化 ~56%**：理論上太樂觀，主要肇因於 overlap (daily decile spread × 21d forward return) + universe bias。實際可實現約年化 8-15%（業界典型）。

---

## 3. Sprint 2 規劃

### 3.1 主軸：Cross-sectional Ranking Pipeline (基於 E3)

新增任務群（提案，待 V2 spec 修訂時正式收錄）：

| 任務 ID（暫定） | 目標 | 主要產出 |
|---|---|---|
| **TASK-S2-SECTOR** | 真實 TWSE 產業別 fetcher | `src/universe/sector_mapping.py` + `data/cache/sector_map.json` |
| **TASK-S2-WALKFWD** | E3 momentum 加 walk-forward IC | `scripts/run_s2_walkfwd_momentum.py` + `analysis/s2_walkfwd_momentum_report.md` |
| **TASK-S2-UNIVERSE** | survivorship-bias-aware universe（含已下市股、剔除事後贏家偏差） | `src/universe/historical_universe.py` |
| **TASK-S2-PORTFOLIO** | cross-sectional portfolio formation engine（per-rebalance top/bottom decile long-only） | `src/portfolio/cross_sectional_engine.py` |
| **TASK-S2-RANK-SE** | 新 SignalEngine adapter：接 ranking 訊號（與 V1 per-stock binary 訊號不同） | `src/signals/cross_sectional_engine.py` |
| **TASK-S2-BACKTEST** | E3 walk-forward backtest + V2 §6.1 完整判決 | `analysis/s2_momentum_backtest_report.md` |

**依賴**：
- SECTOR → WALKFWD（需正確 sector 才能算 walk-forward sector-neutral）
- UNIVERSE → WALKFWD（需歷史 universe 修正 survivorship）
- WALKFWD → PORTFOLIO（需確認 alpha 在 walk-forward 仍存在才動工 portfolio infra）
- PORTFOLIO + RANK-SE → BACKTEST

### 3.2 不做：multi-strategy allocator

§D.5「C0a 過 + C1-safe 過 → 同時規劃 multi-strategy allocation」未觸發。Sprint 2 維持單一策略路徑。

### 3.3 不做：C1-panic / C0b / C0c / C3

§D.6 禁區 + 兩個前置策略均 FAIL → 不啟動。Sprint 2 全力 cross-sectional。

### 3.4 並行已部署 infrastructure 維持

- **S2 advisor cron** (`scripts/snapshot_advisor_scores.py`)：繼續累積 daily heuristic Advisor 分數，3-6 月後評估 C4 advisor IC
- **P01 memory paper router**：等任一策略過 V2 §6.1 完整判決後再啟用
- **M01 + M02 monitor**：data freshness / live-vs-backtest consistency 持續守護

---

## 4. Sprint 2 出口 / 失敗預案

| 場景 | 動作 |
|---|---|
| TASK-S2-WALKFWD 顯示 E3 alpha 在 walk-forward 仍 robust | 推進 PORTFOLIO + RANK-SE + BACKTEST → 過 V2 §6.1 → 接 P01 paper runner → D04 |
| TASK-S2-WALKFWD 顯示 E3 alpha 大幅衰減（< IC threshold） | E3 列入 "in-sample artifact" 歷史紀錄；sprint 3 候選改 advisor IC（C4，需 3-6 月累積）或 補 infra (P02/X02) |
| 任一 sprint 2 task 暴露 sector mapping / universe 致命錯 | 回頭調 universe / sector 基礎建設，sprint 2 延展 |

---

## 5. Pytest / Code 變更摘要

| 項目 | sprint 1 前 | sprint 1 後 | 變化 |
|---|---:|---:|---|
| Pytest 通過數 | 701 | **751** | +50 tests |
| Active S1 tasks DONE | 1 / 7 (DOC) | **7 / 7** | sprint 1 全完成 |
| 總任務進度 | 42 / 52 | **48 / 52** | +6 (S1 sprint) |
| 新增 modules | — | `src/research/{event_study, trade_bootstrap}.py`、`src/features/rsi.py`、`src/signals/sector_neutral.py` | 4 個 |
| 新增 scripts | — | `run_s1_e0_v1_bootstrap.py`、`run_s1_e1_chip_event.py`、`run_s1_e2_mean_reversion.py`、`run_s1_e3_momentum_ic.py` | 4 個 |
| 新增 reports | — | `s1_e0_v1_bootstrap_report.md`、`s1_e1_chip_event_report.md`、`s1_e2_mean_reversion_report.md`、`s1_e3_momentum_ic_report.md`、`s1_sprint1_comparison_report.md` | 5 個 |
| `run_backtest_v1.py` | — | 加 `--dump-trades` + `_trade_to_dict` | +21 LOC |

---

## 6. 結論

**Sprint 1 目標達成度**：依 §D.5 完整跑完 4 個 experiment，產出單一明確的 sprint 2 方向（**cross-sectional momentum pipeline**）。

**關鍵發現**：
1. V1 trend-following 的「缺真實 edge」結論被 bootstrap CI 弱化 → 留 baseline
2. 籌碼事件 + 短線超賣兩個 timing strategy 都不過 gate → 不投資源
3. **J–T 12-1m momentum 是唯一通過的 alpha 候選**，且 sector-neutral 後反而更強

**下一步**：開動 sprint 2 = cross-sectional ranking pipeline。首要先解 sector mapping + survivorship-aware universe + walk-forward 三個基礎建設，再決定是否真正建 portfolio formation engine。
