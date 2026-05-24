# Strategy Review & Open Tasks

> 2026-05-24 — V1 §6.1 第六次判決後 retrospective。S1（策略重設計）暫緩之記錄；
> 等 advisor LLM 評分累積 3-6 個月後再以此文件為基礎開新 spec。

---

## A. S1 策略問題記錄

> **澄清**：S1 是「策略重設計」task 代號（與 S2 / S3 並列的 next-step option），**不是策略名稱**。當前在跑的策略叫 `long_entry_v1`（V2 §2 第一版）。S1 = 把 `long_entry_v1` 換掉或大改的動作，目前**還沒做**（等 S2 advisor 累積 3-6 月後啟動）。

### 0. 策略類別與經典脈絡

`long_entry_v1` 屬 **Trend-following + Volume Breakout + Chip Confirmation（趨勢追蹤 + 量價突破 + 籌碼確認）混合**，**不是復刻單一知名策略**，而是多套經典 idea 拼裝：

| 經典策略 | 提出者 / 出處 | 與 long_entry_v1 重疊 |
|----------|--------------|----------------------|
| **CAN SLIM** | William O'Neil（Investor's Business Daily 創辦人，1988 *How to Make Money in Stocks*）| 突破 20 日高 + 量能放大 + 法人買超（"I" + "L" + "I" 子要素）|
| **SEPA** (Specific Entry Point Analysis) | Mark Minervini（U.S. Investing Champion）| Stage 2 趨勢確認（MA20/MA60 多頭排列）+ Pocket Pivot 量價突破 |
| **Darvas Box** | Nicolas Darvas（1960s，*How I Made $2,000,000 in the Stock Market*）| 突破箱頂 + 帶量 ≈ V1 第 3 條件突破 20 日高 |
| **Turtle Trading** | Richard Dennis / William Eckhardt（1983 著名實驗）| 20/55 日 Donchian channel 突破 + ATR 止損 ≈ V1 MA60 + 出場 ATR 1.5× |
| **台股本土「籌碼派」** | 無單一作者；散見 PressPlay / Mr.Market 等部落格體系 | 第 4 條件三大法人 + 融資是典型台股風格 |

**特性總結**：
- **方向**：long-only（多方）
- **時序**：日線 / swing trade（5-20 日 holding）
- **alpha 來源假設**：（a）短期動能延續（trend）（b）爆量伴隨主力進場（volume 確認）（c）籌碼面領先價格（chip 領先指標）
- **risk profile**：低換手（turnover 0.31）、固定 ATR 停損、走勢 fail-fast

### 1. 使用什麼策略

**`long_entry_v1`**（V2 §2 第一版，定義於 `src/signals/rules/long_entry.py` + `src/signals/rules/exits.py`）：

- **進場（5 條件同時滿足，R1 後）**
  1. close > MA20 **AND** close > MA60
  2. spike_severity ≥ MID
  3. 紅 K（close > open）**OR** 突破 20 日高
  4. 三大法人 net buy streak ≥ 3 **OR** 融資 5 日減幅 < 0（chip filter）
  5. 不是漲停板鎖死

- **避免進場（任一觸發即擋）**
  - 上影線 > K 線實體 × 1.5
  - 嚴重利空（news_severity ≤ -5）
  - 今日已 breach daily-loss limit

- **出場（5 條件任一觸發）**
  - 固定停損：進場價 − 1.5 × ATR(14)
  - 跌破 MA10
  - 爆量長黑（severity ≥ HIGH 且收黑且實體 > ATR）
  - 移動停利：高點回落 1.0 × ATR
  - 持有 > 10 交易日仍未延續趨勢

- **Regime gate**（`make_per_stock_regime_gated_entry_factory`，Plan D 後）
  - 每股自己 MA50/MA200 分類 BULL/BEAR/RANGE
  - default allowed = {BULL, RANGE}（R2 後）

- **Position sizing**：vol-target 或 ATR-based（`src/portfolio/position_sizer.py`）
- **Risk gates**：單筆 / 每日 / 連虧冷卻（`src/portfolio/risk_manager.py`）
- **Correlation filter**：sector + 60d ρ 聚類，同 cluster ≤ 2、portfolio β ≤ 1.2

### 2. 遇到什麼問題

**V1 §6.1 第六次判決（4yr data, 139 stocks, real benchmark, per-stock regime gate, equity-fix all applied）**：

| Check | 值 | Pass |
|-------|----|------|
| expectancy_bp | −41.58 | ❌ |
| profit_factor | 1.41 | ✅ |
| max_drawdown | 0.77% | ✅ |
| sharpe | −0.14 | ❌ |
| oos_is_ratio | −0.31 | ❌ |
| top5_excluded | −0.16% | ❌ |
| beats_benchmarks | strategy −0.29% vs 0050 −23.10% | ✅ |
| oos_alpha | +22.81% | ✅ |
| regime_coverage | bull 7 / bear 4 / range **0** | ❌ |
| n_trades | 59 | ✅ |

**結論**：5/10 PASS。表面上看 beats benchmark 且 alpha 正，但實則：

1. **策略無真實 edge**：39 hand-picked universe expectancy +33 bp →加 100 random 後翻 −41 bp。原贏家集中造成假陽性。
2. **去除 top 5 即虧損**（top5_excluded −0.16%）：總報酬靠少數爆 trade 支撐，**非穩定收益**。
3. **OOS-IS 反向**（−0.31）：IS positive (5/11 windows) OOS positive (4/11 windows) 接近但 BEAR windows IS+ OOS− 顯示 bear 期 cherry-pick 不延續 → **regime concentration + 樣本噪音**。
4. **regime_coverage 缺 RANGE**：0050 四年 V 字底未經 sideways → 無法驗證策略在盤整期表現。
5. **sharpe 負**：總報酬 −0.29% 已是負，risk-adjusted 必然差。
6. **alpha 正是大盤更弱**（0050 −23%）而不是策略強。

### 3. 目前採用什麼方式處理

歷次處理（按時間序）：

| # | 處理 | 結果 |
|---|------|------|
| 1 | Plan A 接 real benchmark（0050 雙 proxy）| 暴露 regime gate 與 universe 脫鉤問題 |
| 2 | Plan D per-stock regime gate | n_trades 1 → 17 |
| 3 | Plan E 4yr backfill | n_trades 17 → 43；regime coverage 0+3+0 → 7+4+0 |
| 4 | R1 移 long_entry `market_above_ma60` 冗餘 | n_trades 43 → 47 |
| 5 | R2 RegimeGateConfig default `{BULL, RANGE}` | （script 已 override，影響為對齊預設） |
| 6 | R3-sample 100 random + 4yr | n_trades 47 → 59，**揭 universe bias** |
| 7 | D-investigate window-level 表 | 揭 non-typical overfit 屬 regime concentration |
| 8 | top5_excluded 真實計算 | 揭 top trades 撐住總報酬 |

**結論**：技術 bug 全修，gate / benchmark / equity / report 全對齊；剩下是 **策略本質問題**。

### 4. 有沒有優化方式（仍在 V1 框架內）

| 方案 | 內容 | 預估效果 |
|------|------|---------|
| O1 R3-full universe 全名單（35h backfill） | sample 已證 strategy 在 average universe 不賺 → 全跑 ROI 低 | 低 |
| O2 收緊 chip filter（streak ≥ 5 取代 ≥ 3） | 減 false signal，但 47 trades + expectancy −41 bp 已示問題在訊號品質非數量 | 低 |
| O3 multi-timeframe 雙確認（週線 + 日線） | 需新 feature；可能減 noise 但也減訊號 | 中 |
| O4 動態 position sizing（信號強度加倍） | PositionSizer 已支援 vol-target；strategy edge 不變 → sizing 無法救負期望 | 低 |
| O5 entry rule grid search（spike_severity / streak / ATR multiplier）| 容易 overfit IS 樣本 | 低/負 |

**判斷**：V1 框架內優化 ROI 低。本質問題 = entry signal 對 broader universe disconnected。

### 5. 有什麼更好的策略可以取代

候選 C1-C5，按建議優先序排列。每候選列出 **學名 / 經典藍本** 供 reference。

#### C1 — Mean reversion（短線反轉）★ 推薦先試

- **學名 / 藍本**：
  - **AQR 短期反轉 factor**（Asness, Moskowitz, Pedersen 2013 *Value and Momentum Everywhere* 反例）
  - **Andrew Lo's contrarian strategy**（Lo & MacKinlay 1990 *When Are Contrarian Profits Due to Stock Market Overreaction?*）
  - **台股當沖反手 / T+1 反彈**（坊間常見手法）
- **假設**：超賣後反彈
- **Trigger**：
  - 過去 5 日跌幅 > 1.5 × 20 日標準差
  - RSI(14) < 30
  - 籌碼回補（foreign_net_streak 由負轉正）
- **Hold**：3-5 日 fixed exit；ATR 1.5× 停損
- **Why try**：V1 trend-following 在 sideways/choppy 失敗；mean reversion 在 RANGE regime 有效。涵蓋 0050 4yr 內的反轉行情（多次出現）。
- **新 features needed**：RSI（簡單 implementation）
- **預估工時**：1d signal rule + 0.5d IC + 1d backtest tweaks

#### C2 — Momentum factor（52 週新高）

- **學名 / 藍本**：
  - **Jegadeesh & Titman (1993)** *Returns to Buying Winners and Selling Losers* — 學術 momentum factor 開山祖
  - **Mark Minervini's SEPA** Stage 2（與 V1 同源，純化版）
  - **Dual Momentum** (Gary Antonacci 2014)
- **假設**：新高有續勢
- **Trigger**：close > 52 週 high + 量能 ≥ 1.5×
- **Hold**：trailing stop 跌破 MA20
- **Why try**：V1 突破 20 日高已測，更高時間框架（52 週）filter 雜訊
- **缺點**：與 V1 trend-following 機制重疊太多，可能複現 V1 問題 → **跳過**

#### C3 — Volatility breakout (Donchian / Keltner) ★ 推薦次試

- **學名 / 藍本**：
  - **Turtle Trading System** (Richard Dennis 1983) — 20/55 日 Donchian channel + ATR 1.5× 止損 + 2N 加碼
  - **Keltner Channel** (Chester Keltner 1960) — EMA20 ± 2×ATR
  - **Bollinger Band Breakout** (John Bollinger 1980s)
- **假設**：盤整後突破跟單
- **Trigger**：close > N 日 Donchian upper band + ATR 擴張 > 20 日平均
- **Hold**：ATR-based trailing stop
- **Why try**：**純 price action**，不依賴 chip / news data quality（V1 主要弱點）；Turtle 在原始 paper 證明跨資產 robust
- **新 features needed**：Donchian channel（已有 high_20d 是 sub-set）
- **預估工時**：1d

#### C4 — LLM advisor signal（待 S2 累積 3-6 月後）

- **學名 / 藍本**：
  - **Alternative data signal** family（Eagle Alpha / Yipit）— 用非傳統資料源產生 alpha
  - **NLP sentiment factor**（Hutchinson 2019; Ke, Kelly, Xiu 2019 *Predicting Returns with Text Data*）
  - **Bloomberg ESG / Glassdoor employee sentiment** 等資料驅動 factor
- **假設**：LLM 多維度評分有預測力
- **Trigger**：overall_score > 7 + confidence > 0.6
- **Hold**：5 日 fixed
- **Why try**：利用既有 `src/data/advisor.py`；S2 cron（已部署）3-6 月後做 IC 分析驗證有無預測力。**此類 factor 學術界尚無共識**（部分 paper 顯示有 alpha 部分顯示無），自己 IC 是唯一答案。
- **Time-gate**：必須等 advisor 歷史累積夠長才能跑 IC

#### C5 — Pair trading（同產業 spread）

- **學名 / 藍本**：
  - **Statistical Arbitrage / StatArb** (Edward Thorp 1980s; Morgan Stanley 量化團隊 Tartaglia 1985-87 開拓)
  - **Long-Term Capital Management** convergence trades (1994-1998；終結於 1998 危機)
  - **Avellaneda & Lee (2010)** *Statistical Arbitrage in the U.S. Equities Market*
  - **Gatev, Goetzmann, Rouwenhorst (2006)** *Pairs Trading: Performance of a Relative-Value Arbitrage Rule*
- **假設**：同產業兩檔短期偏離回歸（cointegration）
- **Trigger**：pair z-score > 2σ → 多空 spread
- **Why try**：market-neutral，不受 universe survivorship 影響；經典量化套利 family
- **缺點**：pair selection 是另一大坑；需估計協整 / 半週期 / OU process；StatArb 自 2010 後 alpha 萎縮（高頻量化吃光）→ 留作未來研究方向

### 推薦試點順序

1. **C1 mean reversion** — 最反轉 V1 假設，且資料需求最低
2. **C3 volatility breakout** — 不依賴 chip/news，降資料風險
3. **C4 LLM advisor** — 等 S2 累積足夠後再上
4. C2 momentum — 與 V1 重疊，建議跳過
5. C5 pair — 太複雜，留作未來研究方向

---

## B. 未完成 / 卡關 task 記錄

依 `PROGRESS.md` Phase Summary 整理。

### B.1 標 `IN_PROGRESS` 但實際已完成（**修 PROGRESS 即可**）

| Task | 標籤現況 | 實際狀態 | 修法 |
|------|---------|---------|------|
| TASK-D01c | `IN_PROGRESS` | DONE — script + 14 tests GREEN，2024-05~2026-05 + 2022-05~2024-05 兩段 backfill 已 run 完，總 chips 971 / margin 970 | PROGRESS 改 IN_PROGRESS → DONE |

### B.2 標 `BLOCKED: split` 但子 task 全 DONE（**修 PROGRESS 即可**）

| Task | 標籤現況 | 實際狀態 | 修法 |
|------|---------|---------|------|
| TASK-D03 | `BLOCKED: split` | 子 task D03a/b/c/d/e 全 DONE；D03 占位用途已結束 | PROGRESS 改 BLOCKED → DONE（已 split 完成） |

### B.3 真正 NOT_STARTED — 等其他先決條件

| Task | 為何沒做 | 完成路徑 |
|------|---------|---------|
| **TASK-P02** ShioajiSimRouter (paper layer) | 需真實 Shioaji API knowledge + mock；autonomous 風險高 | (1) 讀 `src/fetcher/shioaji_fetcher.py` 學現有 sim 接法（Singleton + login flow）（2）寫 mock-based unit tests（patch `shioaji.Shioaji`）（3）實作 router 用 `shioaji.api` 物件（4）有 cert 環境下做 smoke integration test，無 cert 則 skip |
| **TASK-X02** ShioajiSimRouter (execution layer) | 與 P02 名稱重疊，職責有 overlap | **建議併入 P02**：實作放 `src/execution/shioaji_sim_router.py`，`src/paper/shioaji_sim_router.py` 簡單 wrapper or alias；spec 內把 X02 標 superseded by P02 |
| **TASK-X03** ShioajiLiveRouter | 等 D04 全通過（V2 §10 強制） | **不該做**：先 D04 PASS。即使做了也不能上線。 |
| **TASK-D04** paper 60d 報告 | 須 paper 跑滿 60 trading days + 100 trades | 時間累積型：(1) 啟 P01 paper router 接 SignalEngine 跑即時（需新 cron / scheduler）(2) 等 ~12 週 (3) 跑 V2 §8.3 評估升級門檻 |

### B.4 BLOCKED 不可動

無真實 blocked。`TASK-D03` 的 `BLOCKED: split` 是占位（見 B.2）。

### B.5 Strategy 範疇（S1）— 暫緩 6 月

- 不在 task table 內；屬「下一個建議」項。等 advisor snapshot 累積 3-6 月後做。
- 屆時可同時試 C1/C3/C4（見 A.5）。

### B.6 R3-full universe 全名單 backfill

- **不在 task table 內**；R3 endpoint 探勘已完成（`specs/profitability/PROGRESS.md` 2026-05-24 R3 endpoint 探勘 entry）。
- **不建議做**：R3-sample 已證 strategy 在 average universe 不賺，35h backfill ROI 低。
- 若 S1 改新策略後想重評，再啟動。

---

## C. 行動建議（按優先序）

1. **小修 PROGRESS**：D01c 改 DONE / D03 改 DONE（占位回收）
2. **啟 advisor cron 排程**：crontab 加 `0 16 * * 1-5` 開始累積（S2）
3. **啟 paper router 排程**：寫 wrapper script 接 P01 + SignalEngine + 即時 quote provider；跑即時、寫 TradeJournal（屬 D04 前置工作，需設計）
4. **6 個月後**：advisor IC 分析 + 試 C1 mean reversion + 試 C3 volatility breakout（S1）
5. **3 個月後**：D04 中期評估 — 看 paper trade 累積 + V1 策略真實表現
6. **不該做**：X02/X03 / R3-full / V1 內無底洞優化

---

## D. S1 Research Plan（2026-05-24，討論收斂正式版）

> **Single source of truth** for S1 strategy research sprint. 取代 `STRATEGY_RESEARCH_CONVERSATION.md` 中所有 sprint plan 提案。
> 來源：CONVERSATION §11-§12（第五輪 + 第六輪結案）。新 session 應**只讀本段** + `PROGRESS.md` 對應 task 即可開動。
>
> 設計原則：**先做 research gate，過 gate 才進 SignalEngine**。每個候選策略走同一套低成本實驗，避免直接 full implementation 才發現沒 edge。

### D.1 Sprint Scope（取代 §C 行動建議）

7 個 task，總工時 ~3.6d。依此順序：

| 順序 | Task ID | Name | Est | 依賴 |
|------|---------|------|-----|------|
| 1 | TASK-S1-DOC | 文件整理（README/PROGRESS/REVIEW 同步） | 0.5d | — |
| 2 | TASK-S1-HELPER | `src/research/event_study.py` (forward_return + event_study + gate) | 1.0d | TASK-S1-DOC |
| 3 | TASK-S1-E1 | C0a Chip event-driven（4 triggers, 1d/3d/5d forward） | 0.5d | TASK-S1-HELPER |
| 4 | TASK-S1-E2 | C1-safe Mean reversion（BULL/RANGE only） | 0.5d | TASK-S1-HELPER |
| 5 | TASK-S1-E3 | C2 Cross-sectional momentum IC（sector-neutral 雙版） | 0.3d | — (用既有 `ic_analysis.py`) |
| 6 | TASK-S1-E0 | V1 bootstrap sanity（fast aggregation first） | 0.5d | TASK-S1-HELPER（optional） |
| 7 | TASK-S1-REPORT | 四項 experiment 比較報告 + Next-step 決策 | 0.3d | E0/E1/E2/E3 |

執行 note：
- E0 排最後（不擋 E1/E2/E3）。
- E3 可與 E1/E2 並行（不依 helper，用既有 `src/signals/ic_analysis.py`）。
- 若 E1/E2 任一 task 暴露 helper 設計問題 → 回頭調 HELPER，不要為單一 experiment 硬撐。

### D.2 候選策略最終優先序（取代 §A.5）

| 序 | 策略 | 動作 | 理由 |
|----|------|------|------|
| 0 | V1 bootstrap | 既有 139 檔 bootstrap (S1-E0) | 確認 V1 −41bp 結論穩定性 |
| 1 | **C0a** Chip event-driven | trigger-level event-study (S1-E1) | 資料最齊（4yr backfill），與 V1 最正交 |
| 2 | **C1-safe** Mean reversion | trigger-level event-study (S1-E2)，BEAR hard skip | 反 V1 假設，需控接刀風險 |
| 3 | **C2** Cross-sectional momentum | IC only (S1-E3) | 機制與 V1 不同，低成本斷然了結 |
| — | C0b Corporate action event | defer | 資料齊但須謹慎處理事件日前後 |
| — | C1-panic | defer 至 C1-safe 過 gate | BEAR 中極端超跌專案，更嚴格 trigger |
| — | C3 Volatility breakout | defer 至 sprint 2 | 純 price action，待 C0a/C1 結果再排 |
| — | C0c Monthly revenue / EPS | defer | 需先補 point-in-time historical feature |
| — | C4 LLM advisor | 等 3-6 月 advisor 累積 | 無 forward return 對照 |
| × | C5 Pair trading | drop | 太複雜，留作未來研究 |

### D.3 event-study helper 設計

#### 路徑

`src/research/event_study.py`（**新 package** `src/research/`，與 `src/signals/` 並列）

#### 邊界規範

- production `src/signals/` **不 import** `src/research/`
- research helper 可讀 `src/features/` / `src/backtest/cost_model.py` / OHLC
- 策略過 gate → 把 evaluator 搬到 `src/signals/rules/<name>.py`（與 `long_entry.py` 同層）

#### 核心 API

```python
@dataclass
class EventStudyResult:
    n_events: int
    base_rate: float                                   # 同期 universe 大盤 hit rate
    hit_rate: float                                    # forward return > 0 比率
    mean_return_bp: dict[int, float]                   # horizon -> mean
    median_return_bp: dict[int, float]
    top5pct_excluded_mean_bp: dict[int, float]         # 排除 top 5% trades 後 mean
    return_distribution: dict[int, np.ndarray]
    cost_adjusted_mean_bp: dict[int, float]            # 扣 round-trip cost 後
    cost_adjusted_median_bp: dict[int, float]


def compute_forward_returns(
    ohlc: pd.DataFrame,
    horizons: list[int] = [1, 3, 5],
) -> pd.DataFrame: ...
# 與 src/signals/ic_analysis.py 共用此 helper（後者重構吃此函式）


def event_study(
    trigger_mask: pd.DataFrame,            # MultiIndex (date, stock_id) -> bool
    ohlc: pd.DataFrame,
    horizons: list[int] = [1, 3, 5],
    cost_model: Callable | None = None,    # 預設接 src/backtest/cost_model.round_trip_cost
) -> EventStudyResult: ...


def evaluate_event_study_gate(result: EventStudyResult, horizon: int = 5) -> GateVerdict: ...
# 回傳 PASS / FAIL + 失敗 reasons
```

#### Gate threshold（最終版，取代 CONVERSATION §9.2-B）

| Metric | Threshold | 理由 |
|--------|-----------|------|
| n_events | ≥ 100 | 樣本門檻 |
| cost_adjusted_mean_5d | ≥ 50 bp | 已扣 round-trip ~40bp + slippage buffer |
| cost_adjusted_median_5d | > 0 bp | 防 mean 被 outliers 撐高 |
| hit_rate − base_rate | ≥ 5 pp | 比同期大盤多 5pp 勝率 |
| top5pct_excluded_mean_5d | > 0 bp | 防 V2 §6.1 top5_excluded 同樣 fail mode |

**全 5 項都過才算 PASS**。任一 fail → unstable，不可進 SignalEngine。

**註**：cost 不用 hardcoded `cost_bp=30` default（過低）；強制接 `src/backtest/cost_model.round_trip_cost()`。

### D.4 各 Experiment 規格

#### TASK-S1-E0 — V1 bootstrap sanity

- **目標**: 用既有 139 檔結果驗證 V1 −41bp 是穩定信號還是抽樣噪音
- **方法（兩層）**:
  1. **Fast aggregation**（先做）: 用 `analysis/experiment_registry/` 內既有 V1 trades，做 trade-level resample bootstrap（100 iter，with replacement）
  2. **Full subset rerun**（fallback）: 若 fast 結論不穩，重抽 100 檔走完整 walk-forward backtest
- **輸出**: expectancy_bp / sharpe / pf / n_trades 的 **95% CI**
- **判決**:
  - CI 下界 > 0 → V1 有 edge（極不可能）
  - CI 含 0 → uncertain（V1 留 baseline，主力放新策略）
  - CI 上界 < 0 → 真死（V1 降級為純歷史對照）

#### TASK-S1-E1 — C0a Chip event-driven

- **目標**: 驗證籌碼事件是否有短期 forward drift
- **Trigger（4 個量化定義）**:

  | Trigger | 量化定義 |
  |---------|---------|
  | foreign_anomaly_buy | `foreign_net > rolling_60d_mean + 2σ` |
  | invtrust_anomaly_buy | `inv_trust_net > rolling_60d_mean + 2σ` |
  | foreign_reverse_to_buy | 前 5d 全負 + 當日 > 0 |
  | margin_rapid_drop | `margin_5d_change < −2σ` |

- **方法**: 每 trigger 先畫觸發頻率分佈，再跑 `event_study`，套 D.3 gate threshold
- **判決**: 任一 trigger 過 gate → C0a 通過 → 進 SignalEngine（搬到 `src/signals/rules/chip_event_v1.py`）

#### TASK-S1-E2 — C1-safe Mean reversion

- **目標**: 驗證短線超賣反彈在 BULL/RANGE regime 是否存在
- **Trigger**:
  - 5d return < −1.5 × 20d volatility
  - RSI(14) < 30
  - per-stock regime ∈ {BULL, RANGE}（強制；BEAR hard skip）
  - 不處於跌停鎖死 / news_severity ≤ −5
- **新 features needed**: RSI(14)（純函式，~30 行）
- **方法**: 同 D.3 event_study + gate
- **判決**: 過 gate → 搬 `src/signals/rules/mean_reversion_v1.py`；C1-panic 在 C1-safe 過後才探索

#### TASK-S1-E3 — C2 Cross-sectional momentum IC

- **目標**: 用 IC 斷然了結 C2 是否值得排隊
- **方法**:
  - feature: 12-1m return（skip month-1 防 1-month reversal，J-T 標準）
  - target: 1m forward return
  - **雙版 IC**: raw IC + sector-neutral IC（台股 sector 集中，必區分 sector beta 與 momentum alpha）
  - decile spread（top − bottom），**扣 monthly turnover cost** 後再判
- **工具**: 既有 `src/signals/ic_analysis.py` + 新增 sector-neutralization helper
- **資料需求**: sector classification（若已用 TWSE 產業別則零補資料）
- **判決**: IC ≥ V2 §1 對應 horizon 門檻 + decile spread > 0 (cost-adj) → 排入 sprint 2；不過即正式淘汰

### D.5 出口條件 / Next-step 決策樹

```
S1-REPORT 收尾時依結果分支：

任一 E1/E2 過 gate
  → 把該 evaluator 搬 src/signals/rules/
  → 接 walk-forward backtest 做 V2 §6.1 完整判決
  → 過 V2 §6.1 → 接 P01 paper runner（D04 前置）

E3 過 IC + decile spread
  → 建立 cross-sectional ranking infra（與 V1/C0a/C1 機制不同，需新 portfolio formation pipeline）
  → 加入 sprint 2

C0a 過 + C1-safe 過
  → 啟動 C1-panic 探索（BEAR 中極端超跌專案）
  → 同時規劃 multi-strategy allocation（CONVERSATION §7.5 議題）

全部失敗
  → S1 sprint 1 結束
  → sprint 2 候選：C0b corporate action / C3 volatility breakout / 等 C4 advisor 累積（3-6 月）
  → 若 sprint 2 仍全失敗 → 評估是否轉「補 infra」方向（P02/X02/D04）

E0 V1 bootstrap CI 上界 < 0
  → 把 V1 從 PROGRESS 降為 baseline-only（不再 active 維護）
  → 但 long_entry_v1 code / tests / journal 保留作歷史對照
```

### D.6 不該做的事（強化 §C）

- ❌ 任一 experiment 在 gate 過前 full SignalEngine implementation
- ❌ helper 第一版塞視覺化 / 過度 reporting
- ❌ 新 seed 抽 100 檔 backfill（除非 E0 fast bootstrap 結論不穩）
- ❌ C1-panic / C0b / C0c / C3 / R3-full universe（等 sprint 1 結果）
- ❌ V1 grid search / 微調 entry 參數
- ❌ paper runner / multi-strategy allocator（等至少一個策略過 gate）
- ❌ X02 / X03 / P02（屬實單前置，等 D04 PASS）

---

## §F S3 Sprint 3 Plan（縮版 universe 擴充 → E3 重判）

### F.1 為何 sprint 3 走縮版 universe expansion

Sprint 2 verdict UNCERTAIN（OOS sector-neutral ic_mean 0.0320 / t-stat 0.77）— alpha 不夠強但也未死。Sprint 1/2 結果都受 **39 hand-picked 倖存者偏差** 影響（sprint 1 universe 含 39 檔事後贏家 + 100 隨機）。在投資 PORTFOLIO/RANK-SE 等週級 infra 前，**先擴大 universe 觀察 E3 sector-neutral 是否仍存活**：
- 若擴大到 ~1900 上市/上櫃 universe 後 OOS ic_mean ≥ 0.04 → 真有 alpha，sprint 4 開始建 PORTFOLIO
- 若仍 UNCERTAIN/DEAD → E3 確認 marginal/artifact，sprint 4 改方向（advisor IC / C0b / 補 infra）

**縮版**：暫不抓已下市股（完整 survivorship-aware 多 2-3d 開發 + 50-80h backfill）。原 universe 已含 100 隨機抽，再擴到 1900 後 random sample 比例 ~95%，倖存者偏差大幅緩解。

### F.2 三 task 規格

#### TASK-S3-BACKFILL — Resumable wide-universe OHLC backfill

- **目標**: 從 `analysis/sector_map.json` 的 1967 mappings 抓出 universe，剔除 0050/9110/非個股、再剔除已在 `data/stocks/` 的 139 檔，**對剩餘 ~1800 檔做 4yr daily OHLC backfill**
- **Resume 要求**:
  - 狀態檔 `analysis/backfill_state_wide.json` 記錄：
    - `started_at` / `last_update` timestamps
    - 完整 `stock_ids` list（run start 時 frozen）
    - `completed` map: `{stock_id: status}`，status ∈ {ok, failed, skipped}
    - `current` 進行中的 stock_id
    - 失敗詳情 `errors` dict
  - 重跑時 `--resume` flag → 跳過 `completed` 狀態的股票；無 flag 從頭
  - 中斷安全：per-stock save 後 flush state；SIGINT 結束前再 flush 一次
- **沿用既有 month-level idempotent**: `scripts.backfill_historical_daily.run_backfill` 已支援 per-month skip；只要再加 stock-list-level 狀態追蹤
- **API**:
  ```python
  # scripts/backfill_wide_universe.py
  @dataclass
  class WideBackfillState:
      started_at: str
      last_update: str
      stock_ids: list[str]
      completed: dict[str, str]   # stock_id -> "ok" | "failed" | "skipped"
      current: str | None
      errors: dict[str, str]

  def select_wide_universe(sector_map_path: Path, data_dir: Path) -> list[str]: ...
  def load_state(state_path: Path) -> WideBackfillState | None: ...
  def save_state(state_path: Path, state: WideBackfillState) -> None: ...
  def run_wide_backfill(*, fetcher, storage, state_path, resume, ...) -> WideBackfillState: ...
  ```
- **Tests (RED list)**: ≥ 5 項
  - `select_wide_universe` 去除已有 + 非個股
  - `WideBackfillState` round-trip (save → load)
  - `--resume` 跳過已 ok 股票
  - SIGINT-equivalent：模擬中斷後狀態檔可恢復
  - smoke：mock fetcher 跑 3 檔通透
- **DoD**: 1800 檔 backfill 完成（或可分多次跑完）；新 universe 全 `data/stocks/*.json` 含 2022-05 起 4yr OHLC

#### TASK-S3-WALKFWD-WIDE — E3 walk-forward on expanded universe

- **目標**: 沿用 `scripts/run_s2_walkfwd_momentum.py`（不需重寫 orchestrator）在新 ~1900 universe 上重跑，產 `analysis/s3_walkfwd_wide_report.md`
- **預期工作**:
  - 確認 `load_daily_ohlc_panel` 在 1900 檔上 RAM 可容受（~50MB pandas frame；OK）
  - 輸出格式同 s2 但加 universe size + 與 s2 對照表
- **DoD**: report 產出；套 §E.3 gate verdict；PROGRESS 記錄
- **預估**: 0.5d（含跑 walk-forward ~10-20 min）

### F.3 Sprint 3 出口 gate（沿用 §E.3 但 universe 已擴大）

| OOS sector-neutral ic_mean | 動作 |
|---|---|
| **≥ 0.04** | **UNLOCK**：E3 有 robust alpha → sprint 4 啟動 PORTFOLIO/RANK-SE/BACKTEST |
| 0.02 - 0.04 | UNCERTAIN：universe 擴大也救不回 → E3 列 marginal，sprint 4 不投 portfolio infra |
| < 0.02 | DEAD：E3 in-sample artifact 確定 → 結束 E3，sprint 4 改 C4 advisor / C0b / 補 infra |

### F.4 Resume 操作協定（與 user 約定）

User 在新 session 通常會先說「讀取 README」再說「繼續 backfill」。
冷啟動 Claude 看到「繼續 backfill」一句指令時應立即執行：

1. **檢查當前狀態**（不打網路）:
   ```python
   from pathlib import Path
   from scripts.backfill_wide_universe import select_wide_universe, load_state
   targets = select_wide_universe(
       sector_map_path=Path("analysis/sector_map.json"),
       data_dir=Path("data"),
   )
   state = load_state(Path("analysis/backfill_state_wide.json"))
   ok = sum(1 for v in (state.completed if state else {}).values() if v == "ok")
   failed = sum(1 for v in (state.completed if state else {}).values() if v == "failed")
   ```
   回報「pending {len(targets)} / ok {ok} / failed {failed}」

2. **啟動背景 backfill**（用 Bash tool `run_in_background=true`）:
   ```bash
   .venv/bin/python -m scripts.backfill_wide_universe \
       --resume --years 4 --sleep-seconds 3 \
       > logs/backfill_wide.log 2>&1
   ```
   注意：
   - 無 `--background` flag，是 Bash tool 的 `run_in_background` 參數
   - state 路徑 default `analysis/backfill_state_wide.json` 不必傳
   - log 寫 `logs/backfill_wide.log`，可用 `tail -20 logs/backfill_wide.log` 查當前進度
   - 背景 task 隨 session 結束而終止，這是 expected — 中斷後再 resume 即可

3. **若 `len(targets) == 0`**（無 pending 股票）→ backfill 已全部結束，直接接 TASK-S3-WALKFWD-WIDE：
   ```bash
   .venv/bin/python -m scripts.run_s2_walkfwd_momentum \
       --data-dir data \
       --sector-map analysis/sector_map.json \
       --out analysis/s3_walkfwd_wide_report.md
   ```

4. **session 結束安全性**：每完成一檔 state file flush 一次（atomic write via tmp + `os.replace`）。中斷時若卡在 mid-stock，state 會有 `current=<sid>` 但 completed[sid] 未設 → resume 會重跑該股票，per-month idempotent 不重抓已有月份。**user 可隨時關閉 session**。

### F.5 修改歷史（§F 自身）

- 2026-05-25：建立 — sprint 2 UNCERTAIN 後規劃；用 resumable backfill 解 user 電腦不能一次跑 50h 限制。

---

## §E S2 Sprint 2 Plan（縮版兩 task validation）

### E.1 為何縮版

Sprint 1 唯一過 gate 的 E3（C2 cross-sectional momentum）有四項致命 caveats：
1. 50 sector buckets / 139 檔 → 多數 singleton bucket → sector-neutral 等於 raw
2. Universe 含 39 檔 hand-picked 倖存者偏差
3. In-sample only（4yr 全段一次計算 IC + decile spread）
4. Cost-adj 4.69%/月 年化 ~56%，與業界典型 8-15% 差距過大，高機率含 overlap × universe bias 雙重高估

**先做 cheap 驗證**（不立刻投資 portfolio + ranking SignalEngine 基礎建設），驗證 E3 alpha 在 walk-forward + 真實 sector 下仍存在，再決定是否進 full pipeline。失敗則 sprint 2 早收，省下週級 task 投資。

### E.2 兩 task 規格（gate-first）

#### TASK-S2-SECTOR — 真實 TWSE 產業別 fetcher

- **目標**: 用真實 TWSE 產業分類（28 類左右）替換 `infer_sector` 4-digit prefix heuristic
- **資料源**: TWSE ISIN endpoint `https://isin.twse.com.tw/isin/C_public.jsp?strMode=2`（公開股票基本資料含產業別欄位）
  - Fallback：若 endpoint 不可達，從 `data/cache/stock_list.json` 推 + 手動補一張 minimal mapping CSV
- **API**:
  ```python
  # src/universe/sector_mapping.py
  def fetch_twse_sectors(cache_path: Path) -> dict[str, str]: ...
  # stock_id -> sector_code (e.g. "24" 半導體業 / "28" 銀行業 / etc.)

  def load_sector_mapping(cache_path: Path) -> dict[str, str]: ...
  # 讀本地快取；不存在 → fetch

  def get_sector(stock_id: str, mapping: dict[str, str]) -> str: ...
  # 取代 src/signals/sector_neutral.infer_sector
  ```
- **Tests (RED list)**: ≥ 4 項
  - parse 已知 HTML/JSON 樣本（mock HTTP）
  - cache 寫入與讀回
  - fallback：mapping miss → "unknown"
  - 整合：sector_neutral.sector_neutralize 接 real mapping 還是 OK
- **DoD**: 139 universe 全部能 lookup 到非 unknown sector；mapping 寫入 `data/cache/sector_map.json`
- **預估**: ~0.5d

#### TASK-S2-WALKFWD — E3 momentum walk-forward IC + 真實 sector-neutral

- **目標**: 在既有 139 universe 上用 walk-forward 切分（IS 12mo / OOS 3mo，同 V1）+ 真實 sector 重評 E3 alpha
- **方法**:
  - 沿用 `src/backtest/walk_forward` 切分產 11 windows（同 V1 spec）
  - 每 window：用 IS 段算 IC 點估計，再在 OOS 段算 forward return → OOS IC
  - 同時跑 raw + 真實 sector-neutral 兩 variant
  - 各 metric 跨 11 windows 取 mean + std
- **API**:
  ```python
  # scripts/run_s2_walkfwd_momentum.py
  def run_walkfwd_momentum(*, data_dir, sector_mapping, output_path, ...) -> dict[str, dict]
  ```
- **報告**: `analysis/s2_walkfwd_momentum_report.md`
  - 11 windows OOS IC 表（raw + sector-neutral）
  - OOS mean ic_mean + std
  - 相對 sprint 1 in-sample IC 的衰減比例
  - 套 §E.3 gate
- **Tests (RED list)**: ≥ 3 項
  - walk-forward window 切分（沿用既有 helper 或薄 wrapper）
  - per-window IC 計算
  - smoke：3 windows minimal 配置產報告
- **預估**: ~1-2d

### E.3 Sprint 2 出口 gate

跑完 TASK-S2-WALKFWD 後依 OOS 平均 ic_mean 分支：

| OOS sector-neutral ic_mean | 動作 |
|---|---|
| **≥ 0.04**（達 V2 §1 horizon 20 門檻） | **解鎖** 剩餘 4 個 sprint 3 task（UNIVERSE / PORTFOLIO / RANK-SE / BACKTEST）；提案 spec 寫入 §F |
| 0.02 - 0.04 | UNCERTAIN — 評估是否擴 universe 或補 advisor IC（C4）後再戰；不直接建 PORTFOLIO infra |
| < 0.02 或翻負 | **E3 列 in-sample artifact**，sprint 2 結束；進 sprint 3 評估 C4 advisor / C0b / C3 / 補 infra |

### E.4 不該做的事（強化 §D.6）

- ❌ 在 SECTOR + WALKFWD 過 gate 前建 PORTFOLIO / RANK-SE / SignalEngine adapter（避免 in-sample artifact 上花週級 task）
- ❌ 大規模 universe 擴充（survivorship-aware）— 等 WALKFWD 結果決定是否值得做
- ❌ 改 IC threshold / gate（保 V2 §1 spec）
- ❌ E3 grid search（同 §D.6 V1 grid search 禁區）

### E.5 修改歷史（§E 自身）

- 2026-05-24：建立 — sprint 1 結束（E3 PASS but caveats）後縮版 sprint 2 規劃。先 2 task validate alpha，再決定是否投資 full pipeline。

---

## 修改歷史

- 2026-05-24：建立 — V1 §6.1 第六次判決後 retrospective。
- 2026-05-24：補 A.0「策略類別與經典脈絡」（CAN SLIM / SEPA / Darvas Box / Turtle / 籌碼派 lineage）+ C1-C5 學名與藍本 references。澄清 S1 是 task 代號非策略名稱。
- 2026-05-24：新增 §D「S1 Research Plan」— 收斂 `STRATEGY_RESEARCH_CONVERSATION.md` 六輪討論結論，定義 7 個 S1 task / event-study helper API / gate threshold / 各 experiment 規格 / 出口決策樹。作為新 session 的 single source of truth。
- 2026-05-24：S1 sprint 1 完成（7/7），新增 §E「S2 Sprint 2 Plan（縮版兩 task validation）」— SECTOR + WALKFWD 兩 task 先驗證 E3 alpha 在 walk-forward + 真實 sector 下是否仍存在，過 gate 才解鎖 PORTFOLIO/RANK-SE/UNIVERSE/BACKTEST 四個 follow-up。
- 2026-05-25：S2 sprint 2 完成（2/2），verdict UNCERTAIN（OOS sector-neutral ic_mean 0.0320），新增 §F「S3 Sprint 3 Plan（縮版 universe 擴充 → E3 重判）」— resumable backfill + walk-forward 重跑，解 user 電腦不能一次跑 50h 限制；過 §F.3 gate 才解鎖 portfolio infra。
