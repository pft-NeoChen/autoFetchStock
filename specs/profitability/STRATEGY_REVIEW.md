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

## 修改歷史

- 2026-05-24：建立 — V1 §6.1 第六次判決後 retrospective。
- 2026-05-24：補 A.0「策略類別與經典脈絡」（CAN SLIM / SEPA / Darvas Box / Turtle / 籌碼派 lineage）+ C1-C5 學名與藍本 references。澄清 S1 是 task 代號非策略名稱。
