# Profitability Development — Session 入口

> **後續 session 對話開頭只要說「讀取 specs/profitability/README.md」**或「**讀取 profitability README**」，即可載入本工作流全部脈絡並接手繼續開發。
> 本檔是**單一入口**。內容刻意冗長，因為它的目的是讓冷啟動的 AI agent 一次取得所有上下文。

---

## 0. 你是誰、你在做什麼

你（Claude / AI agent）即將協助使用者把 `autoFetchStock`（台股即時看盤與資料系統）
**從「資料/視覺化工具」演進為「可驗證、可控風險的交易系統」**。

整體目標：**先做到能盈利的訊號/回測/風控閉環，最後才接實單下單。**

**重要態度**：
- 不直接接實單。
- 不直接調 UI 或單一評分權重就以為能賺錢。
- 一切以「資料能回答 → 才往下走」為原則。
- 嚴格 TDD：**先寫測試 → 再寫實作 → 再重構**。
- 跨 session 開發：每次工作完必更新 `PROGRESS.md`，下一個 session 才能無縫接手。

---

## 1. 必讀清單（依此順序讀完才能動工）

```
1. specs/profitability/README.md          ← 你正在讀的這份（總入口）
2. CLAUDE.md                              ← 專案規範（語言、Git、Figma 等強制要求）
3. specs/profitability/PROGRESS.md        ← 目前進度、當前 task、上次 session log
4. specs/profitability/IMPLEMENTATION_PLAN.md  ← 38 個 task 的拆解與 TDD 流程
5. specs/profitability/PROFITABILITY_PLAN_V2.md ← 規格正本（spec）
6. specs/profitability/PROFITABILITY_PLAN.md   ← V1 意圖原檔（唯讀，背景參考用）
```

讀完後**第一個動作**：
- 開 `specs/profitability/PROGRESS.md` → 看「Quick Status」找當前/下一個 task
- 對應到 `specs/profitability/IMPLEMENTATION_PLAN.md §5` 看 task 詳細規格
- 對應到 V2 看 spec 來源章節
- 開始 TDD 的 RED 階段

---

## 2. 檔案關係地圖

```
specs/
├── profitability/                       ← 本工作流的所有檔案
│   ├── README.md                        ← 本檔。Session 入口、唯一單一進入點
│   ├── PROGRESS.md                      ← 狀態追蹤器（每 session 必更）
│   ├── IMPLEMENTATION_PLAN.md           ← 執行手冊（38 task / TDD 流程 / 銜接協定）
│   ├── PROFITABILITY_PLAN_V2.md         ← 規格正本（spec）
│   └── PROFITABILITY_PLAN.md            ← V1 意圖原檔（唯讀）
│
├── REQUIREMENTS.md / DESIGN.md / TASK.md  ← 舊系統的 cc-sdd 規格（與本工作流無關）
└── history/                             ← 舊規格歸檔（背景參考）
```

**衝突解決順序**：V2 > IMPLEMENTATION_PLAN > PROGRESS。
若 V2 與 PLAN 衝突 → 改 PLAN；若 PLAN 與 PROGRESS 衝突 → 改 PROGRESS。

**修改頻率**：

| 檔案 | 頻率 |
|------|------|
| V1 | 永不改 |
| V2 | 偶爾改（spec 演進，要明確 commit `docs(spec): ...`） |
| IMPLEMENTATION_PLAN | 偶爾改（task 增刪、流程調整） |
| PROGRESS | **每次 session 必更** |
| README（本檔） | 結構性大改時才動 |

---

## 3. 當前狀態（快取，可能略舊；以 PROGRESS.md 為準）

> 本段每次大里程碑時手動同步。**真實狀態以 `PROGRESS.md` Quick Status 表為準。**

- **Phase**: Phase 0 + 1 + 2 + 3 + 4 + 5 ✅；Phase 6 R03 DONE，總計 **31/41**
- **Spec 狀態**: V2 已含 8 項微調建議（已套用）；B04 走自製 backtester 取代 vectorbt（spec drift 記在 PROGRESS）
- **下一 task**: **TASK-S05 Regime gating 接入 SignalEngine**；或先補 chip/news/margin 至 ≥2 年再回頭做 V1 正式 V2 §6.1 判決
- **Blocked**: 無
- **Pytest**: R03 7/7 GREEN；完整 pytest 542/542 GREEN（12 warnings）
- **IC 決策摘要**: 5d/20d 多 feature 過門檻；1d 全敗 → 第一版策略只做 5d~20d holding，不做日內
- **Phase 2 訊號邏輯**: Signal dataclass (無 risk) + evaluate_long_entry (V2 §2 6 條件) + evaluate_exit (V2 §2 出場 5 條件)，皆為 pure evaluator
- **Phase 3 V1 實跑**: 39 stocks × 3 walk-forward windows → 0 trades（chip filter 被 neutral default 卡住，已知 chip/news 本地資料 ≤15 天）→ verdict ❌ FAIL，但報告 caveats 已明列為「結案 smoke artifact,非正式 V2 §6.1 判決」。正式判決前須補：(1) chip/news/margin backfill (2) 含息 weighted_index/0050 benchmark (3) regime classifier (4) IS pass for oos_is_ratio

若實際狀態與此段不符 → 以 PROGRESS 為準，並順手更新本段。

---

## 4. 開工流程（每個 session 都跑一次）

### 4.1 Session 開始 checklist

```
□ 1. 讀 specs/profitability/README.md（本檔）
□ 2. 讀 CLAUDE.md
□ 3. 讀 specs/profitability/PROGRESS.md → 找 Quick Status + V2 修訂候選
□ 4. 讀 specs/profitability/IMPLEMENTATION_PLAN.md（首次或忘了流程時讀）
□ 5. 讀 specs/profitability/PROFITABILITY_PLAN_V2.md 對應章節（看當前 task 的 source）
□ 6. 跑 `git status` + `git log -5` 確認上次 commit
□ 7. 跑 `pytest -q` 確認既有測試綠
□ 8. 確認當前 task 的 status：
       - IN_PROGRESS → 讀 session log 續做
       - 無 IN_PROGRESS → 從 PROGRESS 找下一個 NOT_STARTED 且依賴全 DONE 的 task
□ 9. 跟用戶確認要做的 task（避免猜錯）
```

### 4.2 Session 結束 checklist

```
□ 1. 跑 pytest，記下結果
□ 2. 更新 PROGRESS：
       - Quick Status 表上方欄位
       - Phase Summary 計數
       - 當前 task 的 Status / Last updated
       - 該 task 「Session log」append 一行
       - 若有 V2 修訂建議 → append 到「V2 修訂候選」
       - Global Session Log append 一行
□ 3. Commit 所有變動（含 PROGRESS）
□ 4. 同步本 README §3「當前狀態」（如有大進展）
□ 5. 在最後一句話告訴用戶下一個 session 該做什麼
```

---

## 5. TDD 流程（每 task 強制）

```
[RED]
  1. 讀 task spec（IMPLEMENTATION_PLAN §5）+ V2 對應章節
  2. 寫測試（必須 fail）
  3. pytest → 確認 RED
  4. commit: test(<task-id>): add failing tests for <feature>

[GREEN]
  5. 寫最小實作讓測試過
  6. pytest → 確認 GREEN
  7. commit: feat(<task-id>): minimal implementation

[REFACTOR]
  8. 清重複 / 命名 / 型別 / docstring
  9. pytest 仍 GREEN
  10. commit: refactor(<task-id>): clean up

[DONE]
  11. 更新 PROGRESS：status=DONE / last_updated / session log
  12. commit: chore(<task-id>): mark done in PROGRESS
```

### Status 機器

```
NOT_STARTED → RED → GREEN → REFACTORED → DONE
                ↘ BLOCKED ↗
```

### 測試規則

- 單元測試：`tests/test_<module>/test_<file>.py`、`@pytest.mark.unit`
- 整合測試：`tests/test_integration/`、`@pytest.mark.integration`
- **禁用**：連外網（除非 mock）、依賴 Shioaji 真實登入（cert 不存在則 skip）、用真實 `data/` 內容（用 `tmp_path` + fixture）

### Commit 規範

- 透過 `git-branch-commit-manager` 代理（CLAUDE.md 強制）
- 格式：`<type>(<task-id>): <subject>`
- type ∈ {test, feat, refactor, chore, docs, fix}

---

## 6. 38 個 Task 路線圖（速覽）

> 詳細見 `IMPLEMENTATION_PLAN.md §4`。決策點（D 系列）為 phase 出口。

```
Phase 0 — 資料盤點 + Universe + Feature Store
  D01 → U01 → F01/F02 → F03 → F04..F08 + B03
  ⤷ Phase 0 出口：可對某日期產出完整 feature DataFrame + manifest + benchmark

Phase 1 — IC / decay 分析
  S01 → D02（決策點：feature 是否過門檻）

Phase 2 — SignalEngine
  S02 → S03 → S04

Phase 3 — Backtester
  B01 → B02 → B04 → B05 → J04 → D03（決策點：V2 §6.1 量化門檻）

Phase 4 — Risk + Sizing
  R01 → R02

Phase 5 — Journal + Performance
  J01 → J02 → J03

Phase 6 — Portfolio
  R03 → S05

Phase 7 — UI
  UI01

Phase 8 — Paper Trading
  P01 → P02 → D04（決策點：V2 §8.3 升級門檻）

Phase 9 — Monitor
  M01 → M02

Phase 10 — OrderExecutor
  X01 → X02 → X03（實單，最後）
```

**任一 D-task 未通過 → 不可進下一 phase。**

---

## 7. 緊急停止條件（任一成立即停手）

立即停止實作 → 回頭討論：

- IC 全敗：所有 feature 都不過門檻
- 回測 OOS 期望值為負且偏離 IS > 50%
- Benchmark 全期間皆優於策略
- Paper 與回測差距 > 50%
- 任何 look-ahead bias 被測試偵測到

---

## 8. 關鍵約束（不能違反）

| 規則 | 來源 | 原因 |
|------|------|------|
| 用 backward-adjusted OHLC | V2 §0.4 / V2 修訂建議 #1 | 避免除權息誤判 |
| Feature available_at ≤ signal timestamp | V2 §0.5 | 避免 look-ahead |
| Backtest cost 含手續費雙邊 + 稅 + tick slippage | V2 §3.2 | 避免高估報酬 |
| 訊號 T 收盤產生 → T+1 開盤成交 | V2 §3.3 | 避免偷看 |
| AI advisor 短期不入訊號路徑 | V2 §5 | 無 forward return 對照 |
| SignalEngine 輸出**不含** risk 欄位 | V2 §2 修訂 | sizing/risk 在 PositionSizer / RiskManager |
| 所有 Git 操作透過 `git-branch-commit-manager` 代理 | CLAUDE.md | 全域強制 |
| 全部對話與文件使用繁體中文 | CLAUDE.md | 全域強制 |

---

## 9. 常用指令速查

```bash
# 跑全部測試
pytest -q

# 只跑 profitability 相關（後續會多）
pytest tests/test_universe tests/test_features tests/test_signals \
       tests/test_backtest tests/test_portfolio tests/test_journal \
       tests/test_paper tests/test_monitor tests/test_execution -v

# 覆蓋率
pytest --cov=src --cov-report=term-missing

# 啟動 app（驗證 UI 任務時用）
python -m src.main

# Shioaji 連線測試
python scripts/test_shioaji_login.py
```

---

## 10. 後續 Session 的「魔法句」

冷啟動 session 中，你（AI agent）應主動把以下流程當預設行為：

> **使用者說「讀取 README」/「讀取 specs/profitability/README.md」/「讀取 profitability README」/「繼續開發」→ 立即執行 §4.1 開工 checklist 全部 9 步，然後跟使用者報告：**
>
> 1. 上次 session 做了什麼（從 PROGRESS Global Session Log 取最後一筆）
> 2. 當前 task 是什麼、狀態為何
> 3. 下一個動作建議（RED / GREEN / REFACTOR / 換 task）
> 4. 是否有 V2 修訂候選需要批准
> 5. 跟使用者確認再開動

不要直接動 code。**先報告 → 等用戶 confirm → 才開做。**

---

## 11. FAQ

**Q：用戶說「我有新想法」要改 spec？**
→ 不要直接改 V2。在 PROGRESS「V2 修訂候選」append 一條，session 結束彙整，待用戶明確說「批准」才改 V2 並 commit `docs(spec): ...`。

**Q：跑到一半發現 task 太大？**
→ 把目前 task 標 `BLOCKED: split`，新增 1~N 個子 task 到 PROGRESS（不必先改 IMPLEMENTATION_PLAN），子 task ID 用 `TASK-XXX-a/b/c`。

**Q：測試一直 RED 怎辦？**
→ 別硬撐到 GREEN。檢查是否：(a) 測試寫錯、(b) spec 模糊（→ V2 修訂候選）、(c) 依賴 task 未真正 DONE。

**Q：要用什麼 backtest 框架？**
→ vectorbt（IMPLEMENTATION_PLAN §7 已指定）。需要時 `pip install vectorbt` + 改 `pyproject.toml`。

**Q：要不要用既有 `data/` 內的真實資料？**
→ 不在單元測試用。用 `tmp_path` + 自製 fixture。整合測試可用，但需 mark `@pytest.mark.integration`。

**Q：advisor.py 的 LLM 評分能用嗎？**
→ 短期**不入訊號**。同時開始蒐集 advisor 快照 → 3~6 個月後做 IC 分析才決定。

**Q：Shioaji 怎麼 mock？**
→ 用 `unittest.mock`。實際登入測試只在 `scripts/` 跑，不在 pytest。

---

## 12. 變更歷史（本檔自身）

- 2026-05-22：初版建立。Bootstrap session 完成 V2 spec + IMPLEMENTATION_PLAN + PROGRESS + 本 README。
