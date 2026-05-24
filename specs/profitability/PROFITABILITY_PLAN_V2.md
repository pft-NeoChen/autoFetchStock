# 盈利能力演進計畫 V2

> 本檔為 `PROFITABILITY_PLAN.md` V1 的修訂與擴充版。
> V1 方向正確（先訊號 → 回測 → 風控 → 日誌 → paper → live），但缺料、過料、可改處皆有。
> V2 補上資料盤點、防偷看、台股成本、量化門檻、既有模組整合、組合與監控層。

## Changelog

- **2026-05-22**：套用 8 項微調 — backward-adjusted OHLC（§0.4）、含息 benchmark（§3.5 / §6.1）、walk-forward + embargo + plateau 定義 + OOS < 10 筆合併 + Purged K-Fold 移至 §1（§3.4）、台交所 tick rule 明列（§3.3）、T+2 cash ledger 簡化（§3.7）、IC 門檻分 horizon（§1）。

---

## 0. 與 V1 的差異總表

| 維度 | V1 | V2 |
|------|----|----|
| 起點 | 直接做 SignalEngine | 先做資料盤點 + Feature Store + Universe |
| 訊號輸出 | 訊號內含 `risk`（停損/停利/部位） | 訊號只輸出 score/confidence/reasons；sizing/risk 分離 |
| 回測 | 模糊敘述 | 指定 vectorbt + 台股成本模型 + walk-forward + benchmark 對照 |
| 成本 | 「手續費、證交稅、滑價」一句帶過 | 具體公式與 tick-level 滑價 |
| 風控 | 列規則但耦合在訊號內 | PositionSizer + RiskManager 分離模組 |
| 既有模組 | 未明確整合 | 明列 spike detector / chips / news / advisor / Shioaji sim 接法 |
| AI advisor 角色 | 模糊 | 明定：短期僅資訊面板，蒐集快照 3~6 個月後再決定是否入訊號 |
| 投組層 | 缺 | 新增 Correlation Filter、產業上限、機會成本日誌 |
| 升級門檻 | 「正期望值」 | 具體數字門檻（期望值、PF、DD、Sharpe、OOS/IS、regime 涵蓋） |
| 監控 | 缺 | Data Freshness Guard + Live↔Backtest Consistency Monitor |
| OrderExecutor | 過早展開細項 | 只先定抽象介面（dry-run / paper / live 三模式） |
| 回測可信度 | 缺 | 補除權息調整、資料可得時間、成交限制、現金/交割、資料版本、實驗紀錄 |

---

## 1. 現況實況（比 V1 更精確的盤點）

| 領域 | 檔案 / 路徑 | 狀態 |
|------|-------------|------|
| 訊號 stub | `src/data/signals.py` | UNUSED，硬寫敘述字串，**不可直接接 UI 或產線** |
| AI advisor | `src/data/advisor.py` (509 行) + `advisor_llm.py` + `advisor_cache.py` + `advisor_quota.py` | 已含 Gemini LLM + heuristic fallback，**沒有歷史回測** |
| 爆量偵測 | `src/processor/volume_spike_detector.py` (168 行) | 法 A/B baseline 完整，**僅單 bar，未結合趨勢/籌碼/大盤** |
| 籌碼 | `src/fetcher/chips_fetcher.py` (600 行) + `storage/chips_storage.py` | 已抓三大法人、融資融券 |
| 新聞 | `src/news/` 含 fetcher / processor / impact / anomaly / rag / summarizer | 已成型但未串訊號 |
| 行情 | `fetcher/data_fetcher.py` (TWSE) + `shioaji_fetcher.py` (即時串流) | 雙來源已通 |
| 分鐘 K | `fetcher/minute_kbar_warmup.py` + `storage/minute_kbar_storage.py` | 本地 192 檔（不足回測） |
| 日線 | `data/stocks/*.json` | 本地 41 檔（嚴重不足） |
| 分時 | `data/intraday/*.json` | 594 檔 |
| 排程 | `scheduler/scheduler.py` + `volume_spike_job.py` | 已可定時 |
| **無** | backtest / position / portfolio / order_executor / trade_journal / performance / feature_store / universe_filter | 全缺 |

### 1.1 關鍵風險（V1 未識別）

1. **資料樣本不足**：41 檔日線 × 任意時間長度 → 無法做廣樣本回測。
2. **Survivorship bias**：本地檔案是「曾經關注過的股票」，非完整歷史 universe。
3. **Look-ahead bias 風險**：MA、爆量基線、籌碼若取「當日」資料當訊號 → 必須改成 T-1 收盤後可得版本。
4. **AI advisor 無 forward return 對照**：直接拿 advisor 分數當訊號 = 用未驗證指標。
5. **Corporate action bias**：除權息、減資、拆併股若未調整，會把價格跳空誤判為跌破均線、停損或重大利空。
6. **Benchmark 缺失**：策略有正報酬但輸給台灣 50、加權指數或等權 universe，仍不值得部署。
7. **執行假設過度理想化**：若未處理漲跌停、集合競價、partial fill、整股/零股與 tick rounding，回測會高估可成交性。
8. **實驗挑選偏誤**：大量調參後只保留漂亮結果，會造成多重測試偏誤。

---

## 2. 模組架構（V2 版）

```
src/
├── universe/           # 新：universe filter（流動性、剔 ETN/F/警示/處置）
├── features/           # 新：feature store；backtest + live 共用
│   ├── price_features.py      # MA、return、vol、ATR
│   ├── corporate_actions.py   # 除權息/減資/拆併股調整，輸出 adjusted OHLC
│   ├── volume_features.py     # 直接呼叫 processor/volume_spike_detector
│   ├── chip_features.py       # 直接吃 chips_storage
│   ├── news_features.py       # 直接吃 news/news_impact, news_anomaly
│   ├── regime_features.py     # 大盤 MA、ADX、波動帶
│   ├── availability.py        # 每個資料源的 published_at/processed_at/available_at
│   └── store.py               # 統一輸出 DataFrame；point-in-time correct + manifest
├── signals/            # 新：SignalEngine
│   ├── engine.py              # 純訊號：action/side/score/confidence/reasons/invalidations
│   ├── rules/                 # 各別策略
│   └── ic_analysis.py         # 單因子 IC / decay
├── portfolio/          # 新
│   ├── position_sizer.py      # vol-target / ATR-based / fixed-fraction
│   ├── risk_manager.py        # 單筆風險、每日最大虧損、暫停冷卻
│   └── correlation_filter.py  # 同產業上限、相關性聚類
├── backtest/           # 新
│   ├── engine.py              # vectorbt 為核心
│   ├── cost_model.py          # 台股費稅 + tick-level 滑價 + 漲跌停
│   ├── execution_model.py     # bar T 訊號 → bar T+1 開盤成交
│   ├── benchmark.py           # TWII/0050/simple MA/equal-weight baseline
│   └── walk_forward.py        # IS/OOS、purged k-fold、參數穩健度
├── journal/            # 新
│   ├── trade_journal.py       # 每筆成交（含快照）
│   ├── signal_log.py          # 含被風控/相關性過濾掉的訊號（機會成本）
│   ├── performance.py         # 勝率/盈虧比/期望值/MDD/Sharpe/資金曲線
│   └── experiment_registry.py # 記錄參數、資料版本、失敗實驗，避免只挑漂亮結果
├── paper/              # 新
│   ├── shioaji_sim_router.py  # 第一層 paper：用 Shioaji 模擬環境
│   └── memory_router.py       # 第二層：純記憶體模擬
├── monitor/            # 新
│   ├── data_freshness_guard.py# 來源斷流/延遲/跳點 → 停止訊號
│   └── consistency_check.py   # live 訊號 vs 回測 ±2σ 監控
└── execution/          # 新（最後做）
    └── order_router.py        # 抽象介面 dry-run/paper/live
```

---

## 3. 優先級（V2 版）

> V1 步驟 1 之前**插入兩步**，並把 RiskManager 從訊號內拆出。

```
0. 資料盤點 + Universe Filter + Feature Store + Corporate Actions
1. 單因子 IC / decay 分析
2. SignalEngine（純訊號；不含 sizing）
3. Backtester（vectorbt + 台股成本 + benchmark + walk-forward）
4. PositionSizer + RiskManager（分離）
5. TradeJournal + SignalLog（含未進場）+ Performance
6. Regime Filter + Correlation Filter（投組層）
7. UI 顯示績效、近期訊號、未進場機會成本
8. Paper Trading：先 Shioaji sim → 再純記憶體
9. Data Freshness Guard + Consistency Monitor
10. OrderExecutor（接 Shioaji 實單）
```

---

## 4. 各階段具體規格

### 階段 0：資料盤點 + Universe Filter + Feature Store

**目標**：在做任何訊號前，先確保資料足夠、無偏、可重現。

#### 0.1 資料盤點
- 列出本地所有股票的日線 / 分時 / 分鐘 K 覆蓋區間。
- 缺料股票補抓（建議至少 ≥ 100 檔 × 2 年日線；分鐘 K 至少 ≥ 50 檔 × 6 個月）。
- 標註「曾下市/曾停牌」名單，避免 survivorship。

#### 0.2 Universe Filter
過濾規則（每日重算）：

| 條件 | 門檻 |
|------|------|
| 過去 20 日平均成交額 | ≥ 5,000 萬 |
| 上市/上櫃滿 | ≥ 60 個交易日 |
| 剔除 | F 股、ETN、認購/售權證、處置股、警示股、全額交割 |
| 價格 | ≥ 5 元（避免低價股雜訊） |

#### 0.3 Feature Store

- 統一輸出 `pd.DataFrame`，index = (date, stock_id)，columns = 各 feature。
- **Point-in-time correct**：每個 feature 標註「該值在哪個 timestamp 之後可得」，回測一律用該 timestamp 之後的版本。
- 直接複用既有模組（不重做）：
  - `volume_features.py` → 包 `processor/volume_spike_detector.py`
  - `chip_features.py` → 包 `storage/chips_storage.py`
  - `news_features.py` → 包 `news/news_impact.py` + `news/news_anomaly.py`

#### 0.4 Corporate Actions / Adjusted OHLC

- 日線回測一律使用 **backward-adjusted OHLC**（最新價不動，往回乘調整因子），至少處理：
  - 除權息。
  - 現金減資。
  - 股票分割 / 合併。
  - 重大資本變動造成的價格斷點。
- 採 backward-adjusted 的理由：最新收盤價與 live 報價一致，方便 live ↔ backtest 對齊；歷史價會隨新事件持續被調整，須在 manifest 記錄調整版本。
- 未調整價格只可用於「實際成交價」、盤中顯示與 cash ledger，不可直接拿來計算長期均線、停損或 forward return。
- 爆量偵測已可在除權息日跳過 spike 判斷；Feature Store 仍需保存 corporate action flag，讓策略可選擇避開事件日前後 N 日。

#### 0.5 資料可得時間表

每個 feature 必須有 `published_at`、`processed_at`、`available_at` 三種時間。

| 資料源 | 回測使用原則 |
|--------|--------------|
| 日線 OHLC | T 日收盤後才可用於 T+1 訊號 |
| 分鐘 K / tick | 只可使用當下已完成 bar，不可偷看未完成 bar 的 high/low/close |
| 三大法人 | 通常盤後公布，預設最早 T+1 可用 |
| 融資融券 | 通常盤後公布，預設最早 T+1 可用 |
| 財報 / 月營收 | 以正式公告時間後才可用 |
| 新聞 | `published_at` 後才可用；若本系統延遲處理，使用 `processed_at` |
| AI advisor | 以 `generated_at` 後才可用；短期仍不入訊號 |

Backtest engine 必須拒絕使用 `available_at > signal_timestamp` 的 feature。

#### 0.6 資料版本與可重現性

每次建立 Feature Store 與每次回測，都產生 manifest：

- raw data 範圍與 hash。
- universe 版本與篩選條件。
- feature schema 版本。
- corporate action 調整版本。
- strategy config。
- cost model / execution model 版本。
- 程式 git commit 或 dirty diff 摘要。

回測報告若沒有 manifest，視為不可採信。

---

### 階段 1：單因子 IC / decay 分析

> V1 未提，但**不做這層後續會砸時間優化雜訊**。

對每個 feature，計算對 forward `1d / 5d / 20d` 報酬的：
- **IC (Information Coefficient)**：rank correlation。
- **IC decay**：IC 隨 holding period 衰減曲線。
- **單調性**：分 5 組看 forward return 是否單調。
- **Purged K-Fold cross-validation**（López de Prado）：對 IC 估計做穩健性檢驗，避免序列相關造成假陽性。注意：Purged K-Fold 屬 ML CV 工具，僅用於 feature/IC 階段；策略整體驗證仍用 walk-forward + embargo（見 §3.4）。

IC 門檻（**分 horizon**）：

| Forward horizon | IC 門檻 |
|-----------------|---------|
| 1d | ≥ 0.02 |
| 5d | ≥ 0.03 |
| 20d | ≥ 0.04 |

達門檻且分組單調 → 入候選 feature；其餘剔除。產出表格存 `analysis/ic_report.md`。

---

### 階段 2：SignalEngine（純訊號）

**輸出欄位**（**移除 V1 的 `risk` 欄位**，sizing/risk 在後段獨立模組）：

```python
@dataclass
class Signal:
    timestamp: datetime
    stock_id: str
    action: Literal["entry", "exit", "hold", "avoid"]
    side: Literal["long", "short", "none"]
    score: float            # 綜合分數
    confidence: float       # 0~1
    reasons: list[str]      # 觸發理由（短碼，非敘述）
    invalidations: list[str]  # 訊號失效條件
    features_snapshot: dict # 觸發時的 feature 快照（給 journal）
```

#### 第一版策略（沿用 V1，但收緊條件）

**多方進場**（須**同時**滿足）：
1. 收盤站上 MA20 與 MA60
2. 當日（或最新分鐘 K）`spike_severity ≥ MID`
3. 爆量 K 線收紅（close > open）或突破 20 日高
4. 三大法人連 3 日 net buy 至少一邊 > 0 或融資 5 日減幅 < 0
5. **不**處於漲停板鎖死狀態

> **2026-05-24 R1 amendment（autonomous 批准）**：原第 5 條「大盤（加權指數）站上 MA60」已移除，由 Plan D `make_per_stock_regime_gated_entry_factory`（per-stock MA50/MA200 regime gate）取代。原條件用 universe-mean 與 per-stock gate 雙層 market filter 且 proxy 不一致，造成 universe-market 脫鉤情境策略凍結。`EntryConditions.market_close` / `market_ma_60` 欄位暫保留（back-compat）。

**避免進場**：
- 爆量收黑或上影線 > K 線實體 1.5 倍
- 收盤跌破 MA20
- 流動性不足（日均額 < universe 門檻）
- 當日新聞 `news_impact.severity` 為負面重大
- 今日已觸發 daily-loss-limit 或連續虧損冷卻

**出場**：
- 固定停損：進場價 - 1.5 × ATR(14)
- 跌破 MA10
- 爆量長黑（severity ≥ HIGH 且收黑且實體 > ATR）
- 移動停利：高點回落 1.0 × ATR
- 持有 > 10 交易日仍未延續趨勢

---

### 階段 3：Backtester

#### 3.1 框架選型

- **vectorbt**（首選）：vectorised、配 pandas 自然、cost model 可客製。
- 不要自幹完整 backtest（重造輪子且易錯）。

#### 3.2 成本模型（台股）

```python
# src/backtest/cost_model.py
COMMISSION_RATE = 0.001425       # 手續費單邊
COMMISSION_DISCOUNT = 0.38       # 永豐折扣（依實際調整）
TRANSACTION_TAX_NORMAL = 0.003   # 證交稅（現股賣方）
TRANSACTION_TAX_DAYTRADE = 0.0015 # 證交稅（當沖賣方）

def round_trip_cost(price_in, price_out, is_daytrade=False):
    fee_in  = price_in  * COMMISSION_RATE * COMMISSION_DISCOUNT
    fee_out = price_out * COMMISSION_RATE * COMMISSION_DISCOUNT
    tax     = price_out * (TRANSACTION_TAX_DAYTRADE if is_daytrade
                           else TRANSACTION_TAX_NORMAL)
    return fee_in + fee_out + tax

# 滑價：tick × k + spread fraction（用本地 bid/ask 估）
def slippage(price, side, tick_size, spread):
    return tick_size * 1.0 + spread * 0.5 * (1 if side=="buy" else -1)
```

#### 3.3 執行模型

- 訊號於 bar T 收盤後產生 → bar T+1 開盤成交（不可用 T 開盤）。
- 漲停板鎖死 → 該訊號作廢，記錄為「無法成交」。
- 單筆下單量 ≤ 當日成交量 5%（流動性 cap）。
- 現股整股預設以 1 張為最小單位；零股交易另開模式，不混入同一份績效。
- 所有價格需依台股 tick size rounding 到合法價格。**台交所 tick rule（2020 後新版）**：

  | 價格區間（元） | Tick |
  |----------------|------|
  | < 10 | 0.01 |
  | 10 ~ 50 | 0.05 |
  | 50 ~ 100 | 0.1 |
  | 100 ~ 500 | 0.5 |
  | 500 ~ 1000 | 1 |
  | ≥ 1000 | 5 |

  `round_to_tick(price)` 必須依此表 rounding，回測下單價也須合法化。

- 支援 partial fill：成交量不足時只成交可成交部分，剩餘取消或掛單依策略設定。
- 明確區分市價、限價、開盤集合競價、收盤集合競價。

#### 3.4 Walk-Forward + Embargo

- **Walk-forward + embargo 為策略驗證標配**（必做）。Purged K-Fold 留給 §1 feature/IC 階段使用，不用於策略整體驗證（兩者目的不同）。
- IS 12 個月 → OOS 3 個月，rolling。
- **Embargo**：IS 與 OOS 之間留 `holding_period × 1.5` 個交易日（如最長持有 10 日 → embargo 15 日），避免訊號序列相關造成洩漏。
- **OOS 樣本不足合併規則**：若該 OOS 窗內交易筆數 < 10，合併下一窗統計，避免小樣本誤判。合併後仍 < 10 → 標 `LOW_CONFIDENCE`，不計入升 paper 判斷。
- **Plateau 選參數規則**：對 parameter grid，最佳參數 `θ*` 的 ±1 step 鄰居（含對角）中，**≥ 75% 鄰居在 OOS 也達 §6.1 量化門檻** → 認定為 plateau。孤立峰值（鄰居全敗）→ 拒用。
- 不選 plateau 一律視為「過擬合候選」，不可進 Phase 8 paper。

#### 3.5 Benchmark / Baseline

每次回測至少要輸出以下 benchmark，**全部使用含息（total return）版本**，避免高估策略 alpha：

- **加權報酬指數**（TWII total return / 發行量加權股價報酬指數）— 含息。
- **0050 含息 buy-and-hold**（配息再投入）。
- **同 universe 等權持有**（每月或每日 rebalance），含息。
- 簡單 MA 策略（例如 MA20 > MA60 做多大盤），含息。
- 現金不交易（零報酬基準）。

策略通過「正報酬」仍不足夠；至少要在 OOS 期打敗**含息**加權報酬指數與 0050，並在風險調整後報酬上有合理優勢。
未指定含息版本的 benchmark report 視為不合格。

#### 3.6 EOD 與 Intraday 策略分流

不要讓日線策略與盤中策略共用同一套成交假設：

- **EOD strategy**：收盤後產生訊號，隔日開盤或 VWAP 模擬成交。
- **Intraday strategy**：分鐘級或 tick 級產生訊號，必須納入延遲、bid/ask spread、order book、斷線與部分成交。

第一階段建議先做 EOD；盤中策略等 Data Freshness Guard、order book 與 partial fill 模型穩定後再做。

#### 3.7 現金、交割與帳戶限制

- Backtest 必須追蹤可用現金，不可只用抽象權重。
- **T+2 cash ledger（第一版簡化模型）**：
  - 賣出股票 → 該筆現金 **T+2 才入「可用餘額」**，可用餘額決定下一筆下單可否成交。
  - 帳面總資產（含未交割現金）正常計算 P&L。
  - 不模擬交割失敗、違約交割、券源短缺等高階情境（留待 live 真正遇到時再補）。
- 當沖與非當沖需分開計稅與交易紀錄。
- 若使用融資融券，必須另建 margin interest、維持率與追繳風險模型；第一版先不開。

#### 3.8 實驗紀錄與多重測試防線

- 每一次參數 grid、規則調整、feature 刪改都記錄到 `experiment_registry`。
- 失敗實驗也要保存摘要，避免只留下漂亮版本。
- 報告需列出本次共測了多少參數組合與策略變體。
- 選參數時優先 plateau，不選單點最高收益。

---

### 階段 4：PositionSizer + RiskManager（分離）

> V1 把 risk 塞進訊號 → V2 拆開。

#### 4.1 PositionSizer
- 預設 **vol-target**：目標年化波動 X%，依個股 20 日波動反算部位。
- 替代：**ATR-based**：部位 = (帳戶風險預算) / (k × ATR)。
- 禁用 Kelly（樣本不足易爆倉）。

#### 4.2 RiskManager
- 單筆最大風險：帳戶 0.5%（保守）~ 1%。
- 最大同時持股：5~8 檔。
- 單股最大資金占比：15%。
- 每日最大虧損：帳戶 -2% → 當日剩餘訊號全擋。
- 連續 3 次虧損 → 部位減半，連續 5 次 → 暫停 1 個交易日。

---

### 階段 5：TradeJournal + SignalLog + Performance

#### 5.1 TradeJournal（成交）
每筆記錄：
- 訊號 timestamp + Signal 物件完整快照
- 觸發時的 quote / K 線 / 爆量 / 籌碼 / 新聞 / advisor 快照
- 進場價、出場價、持有時間、出場原因
- 已實現損益（毛 + 淨，含成本明細）
- 交易所合法價格 rounding、成交股數、partial fill 明細
- cash ledger 變化與交割日

#### 5.2 SignalLog（**含未進場**，V1 缺）
- 記錄**所有觸發但被風控/資金/相關性過濾擋掉**的訊號
- 後續可分析機會成本，判斷「策略爛」vs「風控太緊」

#### 5.3 Performance 指標
| 指標 | 用途 |
|------|------|
| 勝率 | 基礎 |
| 平均盈虧比 | 基礎 |
| 期望值（bp/trade，扣成本） | 升 paper 主門檻 |
| Profit Factor | 升 paper 副門檻 |
| Max Drawdown | 風控門檻 |
| Sharpe（年化） | 風險調整後 |
| Sortino | 下檔風險 |
| OOS / IS 比 | 過擬合偵測 |
| Top-5 交易剔除後報酬 | 避免少數極端撐起 |
| Benchmark alpha | 是否真的打敗被動持有 |
| Turnover | 成本敏感度 |

---

### 階段 6：Regime + Correlation Filter

#### 6.1 Regime Filter
- 大盤加權指數 MA60 + ADX(14) + 30 日波動分位。
- 弱勢 regime（指數 < MA60 且 ADX < 20）→ 停做多。
- 高波動 regime（vol 分位 > 0.8）→ 部位減半。

> **2026-05-24 R2 amendment（autonomous 批准）**：`RegimeGateConfig.allowed` 預設由 `{BULL}` 改為 `{BULL, RANGE}`。理由：BULL 嚴格定義（close>MA200 AND MA50>MA200）在 V 字底時 close 雖已轉折但仍 < MA200，被誤標 BEAR 過早封鎖。RANGE 涵蓋「sideways consolidation」場景，BEAR（明確下跌趨勢）仍擋。
>
> **2026-05-24 R-Plan D amendment（已執行）**：實作層 regime gate 由 market-wide 改 per-stock —`make_per_stock_regime_gated_entry_factory(inner_factory, feature_frames, config)` 用各股自身 OHLC 做分類。當 universe 與 market_index proxy 脫鉤（e.g. 小型股 vs 0050）時，per-stock gate 不會把策略完全凍結。market-wide gate 仍可用（保留 `make_regime_gated_entry_factory`），但建議用於與大盤高度相關的 universe。

#### 6.2 Correlation Filter
- 候選池做產業聚類 + 60 日 return 相關性聚類。
- 同 cluster 持有 ≤ 2 檔。
- 整體投組 β ≤ 1.2。

---

### 階段 7：UI

新增頁面 `pages/strategy.py`：
- 策略績效曲線、回撤、勝率分布
- 近期訊號清單（含未進場原因）
- 機會成本表
- Regime 狀態指示

---

### 階段 8：Paper Trading（雙層）

#### 8.1 第一層：Shioaji sim 環境
- 利用既有 `SHIOAJI_SIMULATION=true`。
- 真實 OMS 流程（送單、回報、成交、餘額）。
- 唯一缺點：sim 成交不一定真實 → 滑價需自行模擬。

#### 8.2 第二層：純記憶體 paper
- 即時資料跑同一套 SignalEngine。
- 不送 Shioaji，只算「假設成交」損益。
- 與第一層交叉驗證。

#### 8.3 升級門檻（→ live）
- Paper 期間 ≥ 60 個交易日且 ≥ 100 筆成交
- 涵蓋至少 1 多頭 + 1 空頭 + 1 盤整 regime
- Paper vs 回測 IS 期望值差距 ≤ 30%
- 滑價實際 vs 模型差距 ≤ 20%
- Live 連線、斷線、補單流程演練過

---

### 階段 9：監控層（V1 缺）

#### 9.1 Data Freshness Guard
- 監控 TWSE / Shioaji 資料新鮮度。
- 延遲 > 閾值 / 跳點 / 斷流 → **立即停止訊號生成**，現有部位轉手動。

#### 9.2 Live ↔ Backtest Consistency Check（每日批次）
- 將今日 live 訊號當作歷史，跑回測引擎模擬。
- 訊號數量、成交價、滑價分布是否落在回測 ±2σ 內。
- 落外 → 警示 + 自動退回 paper-only 模式。

---

### 階段 10：OrderExecutor / OrderRouter

> V1 過早展開細項。V2 只先定介面。

```python
class OrderRouter(Protocol):
    def submit(self, order: Order) -> OrderID: ...
    def cancel(self, order_id: OrderID) -> None: ...
    def query(self, order_id: OrderID) -> OrderStatus: ...
    def positions(self) -> list[Position]: ...

# 三種實作：
class DryRunRouter(OrderRouter):    ...  # 只記 log
class ShioajiSimRouter(OrderRouter): ... # paper 第一層
class ShioajiLiveRouter(OrderRouter):... # 實單
```

實單下單前置條件（V1 已寫，V2 補強）：
- 階段 3 回測通過數值門檻（見「成功判準」章節）
- 階段 8 雙層 paper 通過升級門檻
- 階段 9 監控層運作 ≥ 30 天無重大誤報
- 斷線、停電、API 限流時的 fail-safe 路徑演練過
- 法務 / 個人風險承受度確認

---

## 5. AI Advisor 角色決策（V1 含糊）

`src/data/advisor.py` 已含 Gemini + heuristic。但：
- LLM 評分**無歷史時間序列**，無法回測。
- 直接當訊號 = 用未驗證指標。

**V2 明定**：
- **短期（階段 0~7）**：advisor **不入訊號路徑**，僅作 UI 資訊面板。
- **同時開始蒐集** advisor 快照 → forward 1d/5d/20d return 對照表。
- **3~6 個月後**做 IC / decay 分析（階段 1 工具直接套用）。
- IC ≥ 0.03 且穩定 → 才考慮當 feature 加入 SignalEngine。
- 否則永久維持資訊面板角色。

---

## 6. 成功判準（量化門檻）

### 6.1 階段 3（回測）→ 階段 8（paper）

**全部達標**才升 paper：

| 指標 | 門檻 |
|------|------|
| 扣成本每筆期望值 | ≥ +5 bp |
| Profit Factor | ≥ 1.3 |
| Max Drawdown | ≤ 20% |
| Sharpe（年化） | ≥ 1.0 |
| OOS / IS 期望值比 | ≥ 0.7 |
| Top-5 大賺交易剔除後 | 仍正報酬 |
| 主要 benchmark | OOS 期至少打敗**含息**加權報酬指數與 0050（配息再投入） |
| Benchmark alpha | OOS 年化 alpha > 0（對含息 benchmark） |
| Regime 涵蓋 | 至少 1 多 + 1 空 + 1 盤整 |
| 交易次數 | ≥ 50 筆（避免樣本太小） |

### 6.2 階段 8（paper）→ 階段 10（live）

見階段 8.3。

---

## 7. 與 V1 的對照（哪些保留、哪些改）

### V1 保留（仍正確）
- 整體優先級方向（先訊號 → 回測 → 風控 → 日誌 → paper → live）
- 第一版策略方向（爆量 + 趨勢 + 籌碼）
- 不直接接實單的態度
- 「先回答能否盈利再討論下單」的判準精神

### V1 修改
- **SignalEntry 移除 `risk` 欄位** → 拆到 PositionSizer + RiskManager
- **OrderExecutor 章節**改為只定抽象介面
- **「正期望值」**改為具體數值門檻
- **「比對落差」**改為自動化 Consistency Check

### V1 新增
- 階段 0：資料盤點 + Universe + Feature Store
- 階段 1：IC / decay 分析
- 階段 6：Regime + Correlation Filter
- 階段 9：Data Freshness Guard + Consistency Monitor
- 既有模組明確接法（spike / chips / news / advisor / Shioaji sim）
- AI advisor 角色三段式決策
- 台股成本模型具體公式
- 除權息 / 減資 / 拆併股 adjusted OHLC
- 資料可得時間表（published_at / processed_at / available_at）
- Benchmark / baseline 對照
- EOD 與 intraday 策略分流
- 現金、交割與帳戶限制
- Dataset manifest 與 experiment registry
- Walk-forward + Purged K-Fold

---

## 8. 第一步建議實作順序（給未來 task breakdown）

1. `src/universe/filter.py`：先把 universe 條件寫死成函式 + 每日輸出名單檔。
2. `src/features/corporate_actions.py`：先建立 adjusted OHLC 介面；沒有完整資料時，至少用 flag 避開事件日前後。
3. `src/features/availability.py`：建立 `available_at` 規則表，先覆蓋日線、法人、融資融券。
4. `src/features/store.py`：建 DataFrame schema + manifest + 一個 demo feature（如 MA20 上穿）。
5. `src/backtest/benchmark.py`：先輸出加權指數、0050、等權 universe baseline。
6. `src/signals/ic_analysis.py`：對該 demo feature 跑 IC report。
7. **跑出第一份 IC report + baseline report → 評估再決定要不要繼續做 SignalEngine。**

> 不要一次寫完 10 個階段。每階段都要有「跑得出來 + 看得到數字 + 決定要不要往下」的 checkpoint。

---

## 9. 失敗模式預警

| 失敗模式 | 預防 |
|---------|------|
| 過擬合（IS 漂亮 OOS 崩） | Walk-forward + Plateau + OOS/IS 比門檻 |
| Look-ahead 偷看 | Feature Store point-in-time + 回測引擎強制 T → T+1 執行 |
| Survivorship | Universe 來源用「當時」上市清單，不用「現在」 |
| 除權息誤判 | adjusted OHLC + corporate action flag |
| 資料公布時間偷看 | 每個 feature 強制 `available_at <= signal_timestamp` |
| 成本低估 | 雙邊費 + 稅 + tick × k 滑價 + spread + 漲跌停 |
| 成交過度理想化 | tick rounding + partial fill + 集合競價 / 限價 / 市價分流 |
| 策略賺錢但輸 benchmark | 每次報告強制 benchmark alpha |
| Live 與回測背離 | Consistency Check 每日跑 |
| 資料源異常下單 | Data Freshness Guard |
| 同類股全壓 | Correlation Filter |
| 連續虧損未停手 | RiskManager 自動冷卻 |
| AI advisor 誤用為訊號 | 明定資訊面板，3~6 個月 IC 驗證後才可入訊號 |
| 樣本太小判斷有效 | 交易次數門檻（≥ 50 筆）+ Top-5 剔除測試 |
| 多重測試後挑漂亮結果 | experiment_registry 保存所有嘗試與失敗摘要 |
| 回測不可重現 | dataset manifest + strategy/cost/execution 版本記錄 |
| 現金不可用仍下單 | cash ledger + T+2 交割模擬 |
