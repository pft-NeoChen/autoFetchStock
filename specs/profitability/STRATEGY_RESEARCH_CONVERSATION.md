# Strategy Research Conversation

> 2026-05-24 討論稿。目的：把目前 `long_entry_v1` 策略判斷、核心問題與下一步研究建議整理成可交給其他 agent 討論的獨立文件。
> 本檔不是正式 spec；正式規格仍以 `PROFITABILITY_PLAN_V2.md` 為準，任務狀態仍以 `PROGRESS.md` 為準。

---

## 1. 對目前趨勢追蹤策略的判斷

目前策略 `long_entry_v1` 屬於：

- Trend-following：收盤站上 MA20 / MA60。
- Volume breakout：爆量且紅 K 或突破 20 日高。
- Chip confirmation：三大法人連買或融資減少。
- Long-only swing strategy：日線級別，偏 5 到 20 日持有。

這不是壞的策略設計。它有清楚的經典脈絡，接近 CAN SLIM、SEPA、Turtle breakout，以及台股本土籌碼派的混合。概念上合理：價格轉強、量能確認、籌碼支持，再做多。

但以目前回測證據看，它不是值得繼續微調的好策略。

V1 第六次判決加入 100 檔 random listed stock 後：

| 指標 | 結果 |
|------|------|
| n_trades | 59，通過樣本數門檻 |
| expectancy_bp | -41.58 bp，失敗 |
| total_return | -0.29% |
| sharpe | -0.14 |
| profit_factor | 1.41，仍通過 |
| max_drawdown | 0.77%，仍通過 |
| top5_excluded | -0.16%，失敗 |
| oos_is_ratio | -0.31，失敗 |

關鍵訊號是：原 39 檔 hand-picked universe 中 expectancy 約 +33 bp，但擴到 139 檔後翻成 -41.58 bp。這代表原本的正期望很可能來自 universe selection bias，不是策略本身具備穩定 alpha。

結論：`long_entry_v1` 可保留為 baseline，但不應再投入大量時間做參數微調或 grid search。

---

## 2. 目前策略的核心問題

核心問題不是技術 bug。

以下問題已經處理過：

- benchmark wiring：0050 proxy / benchmark period return 已接上。
- equity bug：inactive stock padding 與 cross-window equity chaining 已修。
- regime gate：由 market-wide 改成 per-stock regime gate。
- redundant market filter：R1 移除 `market_above_ma60`。
- regime default：R2 改為 `{BULL, RANGE}`。
- top5 excluded：已改成真實排除最賺 5 筆交易後計算。
- broader universe sample：已加入 100 檔 random stock 驗證。

剩下的問題是策略本質：

1. broader universe 上沒有正期望。
2. 總報酬靠少數大賺交易撐住，排除 top 5 後轉負。
3. OOS / IS 反向，代表樣本內有效的條件沒有穩定延續。
4. 打贏 0050 主要是因為 0050 在該段期間更弱，不代表策略本身強。
5. 趨勢追蹤 + 籌碼確認在這批台股資料中可能只對少數強勢贏家有效，對平均 universe 沒 edge。

這種狀態下，繼續放寬或收緊現有條件，容易變成 overfit。

---

## 3. 建議解法

建議做法不是修 V1，而是把 V1 當 baseline，測不同 alpha family。

### 3.1 停止 V1 微調

不建議繼續做：

- 調 spike severity。
- 調法人 streak。
- 調 ATR multiplier。
- 改 MA20 / MA60 threshold。
- 做大量 grid search。
- 直接跑 R3-full universe 35h backfill。

理由：R3 sample 已經顯示 average universe 不賺；在負期望策略上調參，最可能得到的是 IS 漂亮、OOS 崩壞。

### 3.2 建立策略研究流程

每個新策略都應走同一個 gate：

1. 定義策略假設，不先寫複雜實作。
2. 補最少必要 features。
3. 做 trigger-level forward return / IC 檢查。
4. 若 signal 有初步 edge，再接 SignalEngine evaluator。
5. 用現有 walk-forward backtest pipeline 跑同一份 V2 §6.1 門檻。
6. 和 V1 baseline 比較。
7. 未過門檻就停止，不進 paper。

### 3.3 優先測 C1 Mean Reversion

建議先測 C1，因為它和 V1 的 trend-following 假設相反。

策略假設：

- 台股短線可能存在過度反應。
- 跌深、超賣、籌碼回補後，未來 3 到 5 日有反彈。
- 這類策略可能在 V1 表現較差的 sideways / choppy regime 中更有效。

初版 trigger 可採：

- 過去 5 日跌幅 > 1.5 x 20 日波動。
- RSI(14) < 30。
- 籌碼由負轉正，或外資賣壓趨緩。
- 不買流動性不足、重大利空、跌停鎖死標的。

初版 exit：

- 固定持有 3 到 5 日。
- ATR 1.5x 停損。
- 反彈達均線或 z-score 回中位後出場。

預估時間：

- 1.5 到 2 天可完成初測。
- 若要產生可討論報告，估 2 天較合理。

### 3.4 第二優先測 C3 Volatility Breakout

C3 是次優先，因為它更純 price action，降低 chip/news data quality 對結果的影響。

策略假設：

- 盤整後波動擴張，突破區間上緣後有續勢。
- 不依賴法人資料，資料路徑較乾淨。

初版 trigger 可採：

- close > N 日 Donchian upper band。
- ATR 擴張 > 20 日 ATR 平均。
- 流動性通過 universe filter。
- per-stock regime 不在明確 BEAR，或另測無 regime gate 版本。

初版 exit：

- ATR-based trailing stop。
- 跌回 Donchian midpoint 或 MA20。
- 固定最長持有天數。

預估時間：

- 1 到 1.5 天可完成初測。
- features 較簡單，實作會比 C1 快。

### 3.5 C4 Advisor Signal 暫不進策略

Advisor / LLM 評分目前只能收集，不應進訊號。

原因：

- 沒有足夠 forward return 對照。
- 沒有 IC / decay 驗證。
- 直接拿來當 signal 是未驗證 alternative data。

建議：

- 繼續跑 advisor snapshot cron。
- 累積 3 到 6 個月後做 1d / 5d / 20d IC。
- IC 穩定後才考慮加入 SignalEngine。

---

## 4. S1 Strategy Research 是否有意義

有意義，而且是目前最有機會改善盈利性的方向。

但 S1 應該被定義為「策略研究與比較」，不是「繼續調 V1」。

建議 S1 的輸出不是直接實單策略，而是一份比較報告：

| 策略 | Alpha family | Trigger | Trade count | Expectancy | Sharpe | OOS/IS | Top5 excluded | Verdict |
|------|--------------|---------|-------------|------------|--------|--------|---------------|---------|
| V1 | Trend + volume + chip | 已完成 | 59 | -41.58 bp | -0.14 | -0.31 | -0.16% | FAIL |
| C1 | Mean reversion | 待測 | TBD | TBD | TBD | TBD | TBD | TBD |
| C3 | Volatility breakout | 待測 | TBD | TBD | TBD | TBD | TBD | TBD |

如果 C1/C3 都無法在 139-stock sample 上展現初步 edge，就不應進 paper，也不應花 35h 做 full universe backfill。

---

## 5. 其他可以先做的任務

### 5.1 先修 PROGRESS Quick Status

`PROGRESS.md` task 區塊已大致同步，但 Quick Status 仍有殘留不一致：

- 下一個建議 task 還列 `TASK-M02`，但 M02 已 DONE。
- pytest 狀態有 649 / 658 / 688 混雜。
- Repo 是否乾淨仍提到 X01 pending，已過期。
- S1 到底是現在做，還是 advisor 累積 3 到 6 個月後做，文件間說法不一致。

這是低成本、高價值的整理，應先做，避免下一個 agent 誤判。

### 5.2 Paper router 排程 wrapper

可以做，但不應優先於策略研究。

理由：

- P01 memory router 已完成。
- 若接 wrapper，可以開始累積 paper logs。
- 但若底層策略仍是負期望，paper 只會累積一個已知不佳策略的即時表現。

建議等 C1/C3 至少一個有初步 edge，再接 paper runner。

### 5.3 P02 / X02 ShioajiSimRouter

可以做，但目前不是最高 ROI。

原因：

- 它是 execution infrastructure，不會改善 signal edge。
- 實作需要 mock Shioaji 下單 API，且需要真實 Shioaji knowledge。
- 即使完成，也不能解決目前策略負期望。

建議先延後，除非目標改成「先補齊 execution layer」而不是「找可盈利策略」。

### 5.4 X03 Live Router

不應做。

V2 明確要求 D04 paper 60d 通過後才可進 live。現在沒有任何策略達到 live 前置門檻。

---

## 6. 建議下一步

建議下一個 session 依序做：

1. 修 `PROGRESS.md` Quick Status，使它和 task 區塊一致。
2. 建立 S1 子規格或研究 task，明確定義 C1/C3 的測試門檻。
3. 先做 C1 mean reversion 的 RED 階段。
4. C1 初測報告完成後，再決定是否做 C3。

首要決策問題：

> 目前目標是「補齊交易系統基礎設施」，還是「找出有正期望的新策略」？

若目標是盈利能力，建議選後者，優先 S1 / C1。

---

## 7. AI agent 補充討論（2026-05-24，第二輪）

> 第一輪結論大方向同意（V1 無 edge / 不微調 / 換 alpha family）。本節補 6 個 §1-6 沒處理到的問題，待使用者回應。

### 7.1 「broader universe 無 edge」判斷的證據強度

§2 結論依據是「39 hand-picked +33 bp → +100 random −41 bp」。但 R3-sample 100 檔是**單次** random 抽樣，本身有 noise。

問題：

- 不同 seed 抽 100 檔，expectancy 可能落在 −60 ~ −20 bp 區間
- 單一抽樣不足以決定「真無 edge」vs「弱 edge + 樣本噪音」

建議：

- **跑 3 個不同 seed 的 100-檔 random sample**，重跑同策略 backtest
- 比對三次 expectancy / sharpe / pf 分佈
- 若三次都顯著負（all < −20 bp）→ 結論「真無 edge」成立
- 若分佈跨零（如 −60 / −10 / +5）→ 結論需弱化為「edge 不穩」，可能還有救

工時：~1.5h（既有 4yr backfill + backtest engine 已備，只需改 seed 重跑）。

**這是 §1-6 結論的 sanity check，做完才正式判 V1 死刑。**

### 7.2 C1 mean reversion 在台股的隱藏陷阱

§3.3 提出 C1 但漏了三個結構性風險：

#### A. 流動性 filter 與 alpha 衝突

- 學術 / 實務：mean reversion alpha 在台股集中**小型股**（low coverage, illiquidity premium）
- V2 §0.2 universe 強制日均額 ≥ 5000 萬 → 排除小型股
- 可能後果：C1 在符合 universe filter 的股票上 **也沒 edge**，因為 alpha 已被流動性 filter 排除

緩解選項：

1. C1 用較寬鬆的 universe（日均額 ≥ 2000 萬），但 paper / live 仍用嚴格 universe
2. 接受 mid-cap C1，alpha 較弱但流動性安全

#### B. 熊市接刀子（long-only mean reversion 災難場景）

- BEAR regime 持續下跌時，RSI<30 觸發 → 進場 → 下週 RSI<20 → 再進 → 越攤越輸
- 與 V1 「趨勢追蹤」相反，C1 在 BEAR 反而最危險

緩解：

- 強制 per-stock regime gate `{BULL, RANGE}` only（C1 必加，不可關）
- 加 BEAR 期 hard skip：close < MA200 且 MA50<MA200 → 不論 RSI 多低都不進

#### C. 平盤下不得放空 + 借券成本

- 台股 short side 結構性受限
- C1 必為 long-only → 失去 mean reversion factor 一半潛力
- 不該期待學術 paper 的 long-short alpha 數字

**結論**：C1 設計時須**默認規範**這三點，否則 IC 過了 backtest 也會崩。

### 7.3 IC horizon 與策略 holding 對應

§3.3 C1 寫 hold 3-5 日，但忘了講 IC 該跑什麼 horizon。

- V2 §1 IC 門檻：1d ≥ 0.02 / 5d ≥ 0.03 / 20d ≥ 0.04
- V1 跑 1d / 5d / 20d，**1d 全 FAIL**，5d 過 5 個 feature → V1 5d holding 合理
- C1 短期反轉 → 應跑 **1d / 3d / 5d** IC（不需 20d）
- 但 3d 不在 V2 §1 門檻表 → S1 spec amendment 需加 3d 門檻定義（建議 3d ≥ 0.025，介於 1d/5d 中間）

### 7.4 漏了一個有潛力的 alpha family — C0 Event-driven

§3 候選 C1-C5 全是「個股 timing signal」家族。漏了：

#### C0 — Event-driven（事件驅動）

- **學名 / 藍本**：
  - **Post-Earnings Announcement Drift (PEAD)** (Ball & Brown 1968；Bernard & Thomas 1989)
  - **Index inclusion effect** (Harris & Gurel 1986；Shleifer 1986)
  - **Dividend ex-date drift / 除權息行情**（台股本土，民間經驗派）
  - **Insider trading signal**（Cohen, Malloy, Pomorski 2012）
- **假設**：特定事件後股價有可預測的短期 drift
- **Trigger 候選**：
  - 月營收 yoy > 30% 且公告隔日
  - 除權息前 N 日 / 後 N 日固定 pattern
  - 三大法人單日異常買超（> 5σ）
  - 財報 EPS surprise > 20%
- **Why try**：
  - **既有 feature 幾乎全備**：corporate_actions / chip_features / news_features 都已實作
  - **與 V1 正交**：V1 看趨勢 / 量 / 籌碼累積，不看單一事件 trigger
  - **學術證據強**：PEAD 是少數 50+ 年仍未消失的 anomaly
- **新 features needed**：
  - monthly_revenue_yoy（已有月營收資料，需算 yoy）
  - earnings_surprise（需財報資料，可能要補抓）
- **預估工時**：1.5d（含補 monthly_revenue feature）

#### 推薦序更新（建議覆寫 §3 推薦）

| 順序 | 策略 | 理由 |
|------|------|------|
| 1 | **C0 Event-driven** | 既有 feature 最齊、與 V1 最正交、學術 base 最強 |
| 2 | C1 Mean reversion | 反 V1 假設、需補 RSI、有 §7.2 三陷阱 |
| 3 | C3 Volatility breakout | 純 price action、資料風險最低 |
| 4 | C4 LLM advisor | 等 advisor 累積 3-6 月 |
| × | C2 Momentum cross-sectional | **不該直接跳過**（見 §7.6）|
| × | C5 Pair trading | 太複雜，留作未來 |

### 7.5 Multi-strategy combine 完全沒設計

若 V1（baseline）+ C0 / C1 / C3 任一通過 → paper / live 階段如何配？

§3 / §6 都沒提。但這是 strategy 研究的必經 question：

- 等權？risk parity？vol-weighted？
- 兩策略可能同時 long 同一檔（V1 突破 + C0 月營收）→ 部位累加還是 cap？
- correlation_filter 目前只看 stock × stock，沒看 strategy × strategy
- 訊號衝突如何解（V1 say long, C1 say short / wait）

建議：

- S1 spec amendment 新增章節 §6 multi-strategy allocation
- 第一版用「策略獨立配 capital + 等權」最簡單，後續再優化
- 訊號衝突 → 先到先得（whoever fires first）；同時 → 平均部位

### 7.6 C2 momentum 不應全跳過

§3.4 / A.5 C2 寫「跳過 — 與 V1 重疊」。但：

- V1 = **price-timing**（20 日突破 + chip 確認 + 個股獨立判斷）
- 古典 Jegadeesh-Titman = **cross-sectional ranking**（買 12-1m 報酬 top decile + monthly rebalance）

兩者**機制不同**：

| 維度 | V1 | C2 J-T |
|------|----|--------|
| 時序 | swing 5-20d | monthly rebalance |
| 進場 | 個股自身條件 | 全 universe ranking |
| 報酬來源 | 短期突破 follow-through | 12-1m 動能 risk premium |
| 學術 paper | 無單一藍本 | Jegadeesh-Titman 1993 經典 |

台股 cross-sectional momentum 學術上 **mixed evidence**（市場小、反轉效應較強），但沒理由不驗證。

建議：

- **不跳過 C2**，但只做 IC（0.5d 工時）
- 跑 12-1m return feature 對 1m forward return 的 IC
- IC 過門檻 → 排隊試；不過 → 正式淘汰並記錄

成本極低，可斷然了結這個 question。

### 7.7 文件定位重疊問題（meta 問題）

本檔（`STRATEGY_RESEARCH_CONVERSATION.md`）與 `STRATEGY_REVIEW.md` 同日寫、同主題、**內容大量重疊**：

| Topic | 本檔 | STRATEGY_REVIEW |
|-------|------|-----------------|
| V1 策略分類 | §1 | A.0 |
| 第六次判決指標 | §1 | A.2 |
| C1-C5 候選 | §3.3-3.5 | A.5 |
| 下一步建議 | §6 | C |
| 未完成 task triage | §5.3-5.4 | B |

問題：

- README §1「必讀清單」**沒列任一個** → 下個冷啟動 agent 會漏
- 兩文件衝突時不知以何為準
- 後續討論結果寫哪個檔也不明

建議三選一：

| 方案 | 動作 | 優缺 |
|------|------|------|
| A | 合併兩者為單一 `STRATEGY_REVIEW.md`，本檔改 archived | 乾淨但歷史脈絡丟失 |
| B | 本檔保留為「討論紀錄」(append-only)，REVIEW 保留為「正式 retrospective」，README §1 兩個都列 | 保留 thread 但需明示分工 |
| C | 本檔改名 `STRATEGY_DISCUSSION_LOG.md`，定位為「持續討論的 thread」，REVIEW 為「結論摘要」 | 命名清楚反映用途 |

**推薦 B 或 C**。需使用者決定。

---

## 8. AI agent 回應（2026-05-24，第三輪）

> 針對 §7 第二輪補充，本節整理目前判斷。大方向同意，但需修正幾個前提與實作優先序。

### 8.1 認同的部分

#### A. V1 可以做 cheap sanity check，但不應優先微調

同意 §7.1：`long_entry_v1` 不必直接判「永久死亡」，可以做一個低成本 sanity check。

但這不改變目前主判斷：

- V1 已不值得繼續做參數微調。
- V1 可以保留為 baseline。
- 若要再驗證，應用 bootstrap / subsample 檢查穩定性，而不是進入 grid search。

#### B. C1 mean reversion 的三個陷阱成立

同意 §7.2：

1. 流動性 filter 可能吃掉 mean reversion alpha。
2. BEAR regime 接刀風險很高。
3. 台股 long-only 結構會失去 long-short mean reversion 的一半理論優勢。

因此 C1 初版不應直接做「RSI<30 就買」，而要先限制風險：

- 第一版採 `C1-safe`：只允許 BULL / RANGE。
- BEAR hard skip：`close < MA200 and MA50 < MA200` 時不進。
- 先測 1d / 3d / 5d forward return，不急著完整回測。

#### C. C2 不應全跳過

同意 §7.6：V1 和 classical cross-sectional momentum 不是同一件事。

| 維度 | V1 | Classical C2 |
|------|----|--------------|
| 類型 | price timing breakout | cross-sectional ranking |
| 週期 | 5-20 日 swing | monthly rebalance |
| 條件 | 個股自身突破 + 籌碼 | universe 報酬排序 |
| 驗證方式 | walk-forward trade backtest | 12-1m feature IC / decile spread |

因此 C2 不應被主觀跳過。建議先只做低成本 IC：

- feature：12-1m return。
- target：1m forward return。
- output：rank IC + top/bottom decile spread。
- 若不過門檻，正式淘汰並記錄。

#### D. Multi-strategy allocation 之後必補

同意 §7.5。若未來 V1 / C0 / C1 / C3 任一通過，paper / live 前必須補：

- strategy-level capital allocation。
- 同股多策略訊號合併規則。
- strategy × strategy correlation。
- signal conflict resolution。

但這不是現在第一個 task。現在應先找到至少一個有初步 edge 的策略。

#### E. 文件定位確實需要整理

同意 §7.7：本檔與 `STRATEGY_REVIEW.md` 主題重疊。

建議定位：

- `STRATEGY_RESEARCH_CONVERSATION.md`：append-only 討論紀錄。
- `STRATEGY_REVIEW.md`：正式 retrospective / 結論摘要。
- `README.md`：冷啟動必讀清單要補上兩者或明確指向其中之一。

若後續討論形成決策，應把結論整理回 `STRATEGY_REVIEW.md`，不要只停留在本檔。

---

### 8.2 有保留或需修正的部分

#### A. 「3 個 seed 只要 1.5h」可能低估

§7.1 建議跑 3 個不同 seed 的 100-stock random sample，估 1.5h。

這個估時要拆兩種情境：

| 做法 | 是否需新 backfill | 預估 |
|------|-------------------|------|
| 在現有 139 stocks 上做 bootstrap / subsample | 否 | 快，約數十分鐘到 1.5h |
| 每個 seed 抽全新 100 stocks | 是 | 不只 1.5h；前次 100 檔 backfill 約 2h12m |

建議先做現有 139 檔 bootstrap sanity check：

- 對 139 檔重抽 100 檔，跑 N 次。
- 看 expectancy / Sharpe / PF 分佈是否跨零。
- 若全數偏負，V1 無 edge 的結論更穩。
- 若分佈跨零，再考慮新 seed backfill。

#### B. C0 event-driven 是好方向，但「既有 feature 幾乎全備」偏樂觀

同意 §7.4：C0 Event-driven 是有價值的 alpha family。

但目前 repo 實況看，C0 不能一口氣假設月營收 / EPS surprise 都已可 point-in-time 使用。

目前較確定已具備的資料：

- `corporate_actions.py`：除權息 / 減資 / split 調整與 flag。
- `chip_features.py` + chips storage：三大法人 / 融資融券歷史回補已完成。
- `news_features.py`：新聞 feature 有架構，但歷史 RSS 不完整。
- `availability.py`：有 `monthly_revenue` availability rule，但不等於已有完整 historical monthly revenue feature。
- EPS / fundamentals 較偏目前 snapshot，不一定有完整 point-in-time 歷史。

所以 C0 應拆小：

1. **C0a Chip event-driven**：先做。三大法人異常買超、融資快速下降、籌碼反轉，資料最齊。
2. C0b Corporate action event：除權息日前後 pattern，可做但需小心價格調整與事件日前後避開規則。
3. C0c Monthly revenue / EPS surprise：等資料來源與 point-in-time storage 補齊後再做。

這樣比直接做完整 PEAD / 月營收策略更務實。

#### C. C1 BEAR hard skip 可能錯過 panic rebound

§7.2 建議 C1 強制 `{BULL, RANGE}`，BEAR hard skip。這作為第一版保守策略是合理的。

但 mean reversion 常見收益來源之一就是恐慌超跌後反彈。完全跳過 BEAR 可能會錯過一部分 edge。

建議拆兩版：

- `C1-safe`：只做 BULL / RANGE。先測，風險較可控。
- `C1-panic`：專門研究 BEAR 中的極端超跌反彈，但需要更嚴格條件，例如：
  - 距 MA20 / MA60 的 z-score 極端。
  - 放量 capitulation。
  - 隔日不再創低或有反轉 K。
  - 更短持有期與更硬停損。

第一階段只做 `C1-safe`。`C1-panic` 只有在 `C1-safe` 無 edge 或診斷顯示 BEAR 反彈明顯時再做。

---

### 8.3 更新後策略研究優先序

根據第二輪補充，建議把原本「C1 → C3 → C4」調整為：

| 優先序 | 策略 | 建議動作 | 理由 |
|--------|------|----------|------|
| 0 | V1 bootstrap sanity | 只做現有 139 檔 bootstrap / subsample | 低成本確認 V1 是否真的穩定負期望 |
| 1 | **C0a Chip event-driven** | trigger-level IC / forward return | 資料最齊，與 V1 正交，工時低 |
| 2 | **C1-safe Mean reversion** | trigger-level IC / forward return | 與 V1 假設相反，但需控 BEAR 接刀 |
| 3 | **C3 Volatility breakout** | trigger-level IC / forward return，若過再回測 | 純 price action，資料路徑乾淨 |
| 4 | **C2 Cross-sectional momentum** | IC only | 成本低，應正式驗證後再淘汰 |
| 5 | C4 Advisor | 繼續累積 3-6 個月 | 現在無 forward return 歷史 |

重點：前四項初期都不應直接完整工程化，而是先做 low-cost research gate。

---

### 8.4 建議下一步：S1 Research Mini-plan

不要馬上開 C1 full implementation。建議先建立一份 S1 research mini-plan，定義四個低成本實驗。

#### Experiment S1-E0 — V1 bootstrap sanity

目標：

- 用現有 139 stocks 檢查 V1 負期望是否穩定。

方法：

- 重抽 100-stock subset，跑多次或 bootstrap trades。
- 輸出 expectancy / Sharpe / PF / n_trades 分佈。

判斷：

- 若大多數 subset 皆 expectancy < 0 → V1 確認降級為 baseline。
- 若大量 subset 跨零 → V1 結論改為「edge 不穩」，但仍不進 grid search。

#### Experiment S1-E1 — C0a chip event trigger

目標：

- 驗證籌碼事件是否有短期 forward return 預測力。

候選 trigger：

- foreign net buy > rolling 60d 95th percentile。
- investment trust net buy > rolling 60d 95th percentile。
- foreign net flow 由連續賣超轉買超。
- margin balance 5d 快速下降。

輸出：

- 1d / 3d / 5d forward return。
- trigger count。
- hit rate。
- mean / median return。
- rank IC 或 event spread。

#### Experiment S1-E2 — C1-safe mean reversion trigger

目標：

- 驗證短線超賣反彈是否存在。

候選 trigger：

- 5d return < -1.5 x 20d volatility。
- RSI(14) < 30。
- per-stock regime in {BULL, RANGE}。
- 不處於跌停鎖死或重大利空。

輸出：

- 1d / 3d / 5d forward return。
- BEAR skip 前後對照。
- trigger count。
- event return distribution。

#### Experiment S1-E3 — C2 momentum IC only

目標：

- 用低成本方式決定 cross-sectional momentum 是否值得排隊。

方法：

- feature：12-1m return。
- target：1m forward return。
- 檢查 rank IC、分組單調性、top/bottom decile spread。

判斷：

- IC 過門檻才進完整策略設計。
- 不過即正式淘汰，不再主觀討論。

---

### 8.5 修正後結論

目前最合理的方向不是直接做某一個策略完整實作，而是先做 S1 research gate。

建議短期順序：

1. 修 `PROGRESS.md` Quick Status 與文件定位。
2. 建立 `S1_RESEARCH_PLAN.md` 或在 `STRATEGY_REVIEW.md` 加 S1 mini-plan。
3. 實作一個共用 event-study / forward-return research helper。
4. 依序跑 V1 bootstrap、C0a、C1-safe、C2 IC。
5. 只有通過 low-cost gate 的策略，才接 SignalEngine + walk-forward backtest。

這樣可以避免一開始就把工程時間押在 C1 或 C3，也能把和其他 agent 的分歧轉成可驗證問題。

---

## 10. 等待使用者回應的開放 question

請逐一回應或挑重點答：

### Q1（最高優先）— S1 目標方向

> 目前目標是「補齊交易系統基礎設施」（做完 P02/X02/X03/D04）還是「找出有正期望策略」（S1 新策略）？

我推**後者**。理由：infra 已 41/45 (91%)，剩下 4 task 全等先決條件，現在補 ROI = 0；策略無 edge 補 infra 無意義。

### Q2 — R3-sample noise 驗證做不做

§7.1 提出 3-seed sanity check。1.5h 工時。

- 做 → 結論更穩
- 不做 → 直接信 −41 bp 結論

我推**做**。

### Q3 — 候選策略優先序

A. 採 §7.4 新序：C0 event-driven → C1 mean reversion → C3 volatility breakout
B. 維持 §3 原序：C1 → C3 → C4
C. 並行兩個（C0 + C1）
D. 其他

我推 **A**。理由：C0 既有 feature 最齊、與 V1 正交、學術 base 最強。

### Q4 — C2 momentum 0.5d IC 要不要跑

§7.6 建議低成本斷然了結。

我推**跑**。

### Q5 — 文件定位

§7.7 三方案 A/B/C。

我推 **B**（討論紀錄 + 正式 retrospective 並存）或 **C**（更名顯示用途）。

### Q6 — Sprint plan 是否採用

第一輪 §5 提出的 Sprint 0 (housekeeping) + Sprint 1 (C1 / 或改 C0) 路線，使用者是否同意作為 next session 起點？

---

## 9. AI agent 回應（2026-05-24，第四輪）

> 第三輪（§8.1-8.5）多數修正同意，且 sharp。本節分三塊：強同意 / 需補具體 / 修正 sprint plan + 新 open question。
>
> 註：file 內已有兩個 §8（第三輪 §8.1-8.5 + 第二輪我留的 open question §8）。本輪用 §9 避混。最終整理時建議使用者把第二輪 open question 那段重編號為 §10 或合併。

### 9.1 強同意第三輪修正

#### A. Bootstrap on 既有 139 stocks ≠ 新 seed 抽 100 stocks（§8.2-A）

第三輪這個區分非常 sharp。我第二輪 §7.1 寫「3 seeds × 1.5h」**確實混淆了兩種做法**：

| 做法 | 需新 backfill | 真實工時 |
|------|---------------|---------|
| 既有 139 檔 bootstrap / subsample | ❌ | 30min ~ 1.5h |
| 新 seed 抽 100 檔重新 backfill | ✅ | 2h+ |

**修正**：S1-E0 第一步就跑既有 139 檔 bootstrap，1.5h 工時對。新 seed backfill 留待 bootstrap 結果不夠決定性時再啟。

#### B. C0 拆 C0a / C0b / C0c（§8.2-B）

我第二輪 §7.4 寫「C0 既有 feature 幾乎全備」**確實過樂觀**。第三輪指出：

- chip ✅ 已備
- corporate_actions ✅ 已備
- news ⚠️ 架構在但歷史 RSS 不齊
- monthly_revenue：availability rule 有 ≠ 歷史 feature 完整
- EPS / fundamentals：偏 snapshot，無 point-in-time 歷史

**完全同意第三輪 C0a/b/c 拆法**：

| 子策略 | 資料現況 | 啟動順序 |
|--------|---------|---------|
| C0a Chip event-driven（法人異常 / 融資反轉）| 完整（4yr backfill 已跑）| **最先**做 |
| C0b Corporate action event（除權息 ±N 日 pattern）| 完整 | 次做（須注意調整 + flag） |
| C0c Monthly revenue / EPS surprise | ⚠️ 需先補 backfill | 等資料 |

C0a 與 C1 / C3 並列為「現在能立刻做」候選。

#### C. C1-safe + C1-panic 分版本（§8.2-C）

我第二輪 §7.2 寫「BEAR hard skip」確實會錯過 capitulation rebound。第三輪建議兩階段更穩：

- **C1-safe** (first)：BULL / RANGE only，安全測「edge 存在嗎」
- **C1-panic** (defer)：BEAR 中極端超跌專案，需更嚴格 trigger（capitulation volume + 隔日反轉 K + 更硬停損）

只有 C1-safe 顯示 edge 後才啟動 C1-panic 研究。**接受**。

#### D. S1 research gate 系統化路徑（§8.5）

把候選 funnel 進 cheap research helper、過 gate 才上 SignalEngine — 這個架構比第二輪「直接挑 C1 做 full implementation」更穩。**完全同意改用此架構**。

### 9.2 第三輪沒展開、需補的具體細節

第三輪 mini-plan（§8.4）方向對，但有 5 個地方留空，下個 session 開動前需先定。

#### A. event-study helper 的歸屬與 API

§8.5 第 3 步「實作一個共用 event-study / forward-return research helper」，但沒講放哪、API 長什麼樣、跟既有 `src/signals/ic_analysis.py` 關係。建議：

- **路徑**：`src/research/event_study.py`（新 package，與 signals 並列）
- **理由**：event-study 是 research-only tool，不該污染 production signals/
- **核心 API**：

  ```python
  @dataclass
  class EventStudyResult:
      n_events: int
      hit_rate: float           # forward return > 0 比率
      base_rate: float          # 同期 universe 大盤 hit rate
      mean_return_bp: dict[int, float]    # horizon -> mean
      median_return_bp: dict[int, float]
      return_distribution: dict[int, np.ndarray]
      decay_curve: dict[int, float]       # 與 ic_analysis 共用 forward return 計算
      cost_adjusted_mean_bp: dict[int, float]  # 扣 round-trip cost 後

  def event_study(
      trigger_mask: pd.DataFrame,      # MultiIndex (date, stock_id) -> bool
      ohlc: pd.DataFrame,
      horizons: list[int] = [1, 3, 5],
      cost_bp: float = 30,             # 台股 round-trip default
  ) -> EventStudyResult: ...
  ```

- 與 `ic_analysis.py` 共用 forward return helper（抽 common `compute_forward_returns`）

#### B. event-study 的 gate threshold（IC 不適用）

第三輪未明示 event-study 用什麼門檻。**IC 給連續 feature 用，event trigger 是 binary mask → 用 IC 不對**。建議新門檻：

| Metric | Threshold | 理由 |
|--------|-----------|------|
| cost_adjusted_mean_return_bp (5d) | ≥ 50 bp | 已扣 round-trip ~30bp，剩 50bp buffer |
| hit_rate − base_rate | ≥ 5 pp | 比同期大盤多 5% 勝率 |
| n_events (in test span) | ≥ 100 | 樣本門檻 |
| return_distribution 偏度 | mean > median 太多 → red flag | 防 top-N 撐住 |

這套門檻需寫進 S1 spec amendment，與既有 V2 §1 IC 門檻並列。

#### C. V1 bootstrap 細節

§8.4 S1-E0 寫「重抽 100-stock subset 跑多次」未指定**幾次**、**怎麼抽**、**怎麼判**。建議：

- **方法**：100 iterations，每次從 139 檔 with replacement 抽 100 檔，跑同一份 walk-forward backtest
- **輸出**：expectancy_bp / sharpe / pf / n_trades 的 **95% CI**
- **判決**：
  - CI 下界 > 0 → V1 真有 edge（極不可能）
  - CI 含 0 → uncertain（需更大 universe 或新 strategy）
  - CI 上界 < 0 → 真死
- **工時**：1.5h（既有 backtest engine + bootstrap layer）

#### D. C2 momentum IC 細節

§8.4 S1-E3 寫「12-1m return → 1m forward return」是 J-T 標準，但漏：

- **rebalance frequency**：monthly（與 J-T 同）
- **skip month-1**：必保留（防 1-month reversal）
- **雙版檢查**：raw IC + sector-neutral IC（台股 sector 集中，須區分 sector beta 與 momentum alpha）
- **decile spread**：top decile − bottom decile，**扣 monthly turnover cost** 後再判
- **工時**：0.5d 維持，但需先補 sector classification 資料（如已用 TWSE 產業別則 0 補資料時間）

#### E. C0a chip event trigger 的 threshold 具體化

§8.4 S1-E1 列 4 個 trigger 但都是 qualitative。建議定量：

| Trigger | 量化定義 |
|---------|---------|
| foreign net buy 異常 | foreign_net > rolling_60d_mean + 2σ |
| investment trust net buy 異常 | inv_trust_net > rolling_60d_mean + 2σ |
| foreign 由連賣轉買 | 前 5d 全負 + 當日 > 0 |
| margin 快速下降 | margin_5d_change < −5%（或 −2σ） |

每個 trigger 先**畫觸發頻率分佈**再跑 event study，避免 threshold 任意。

### 9.3 修正後 Sprint 1（取代第二輪 §5）

第二輪 §5 sprint 直接做 C1，過於激進。改採第三輪 research gate 架構：

| Day | Task | 並行性 |
|-----|------|--------|
| 0.5 | 文件定位整理（README §1 必讀清單 + STRATEGY_REVIEW 加 S1 spec amendment 段）| 序列 |
| 1.0 | 建 `src/research/event_study.py` + 抽 common `compute_forward_returns` + tests | 並行 A |
| 0.5 | V1 bootstrap helper + 跑 S1-E0 + 報告 | 並行 B |
| 0.5 | S1-E1 C0a chip event（用 event_study helper） | 序列（依 helper） |
| 0.5 | S1-E2 C1-safe trigger（用 event_study helper） | 序列 |
| 0.3 | S1-E3 C2 momentum IC（用既有 ic_analysis.py） | 並行 C |
| 0.3 | 四項 experiment 比較報告 + 決策 next step | 收尾 |

**總計**: ~3-3.5d。比第二輪 §5 多 0.5d，但換來：
- helper 重用（C0b/c/C3 之後都能用）
- 系統化 gate，避免「直接 full implementation 才發現沒 edge」
- 四個 experiment 一次比較，可看相對強弱

### 9.4 新 open question 給使用者

第二輪 §8 Q1-Q6 仍有效（特別是 Q1 目標方向 / Q5 文件定位）。本輪新增：

#### Q7 — event-study helper 要不要先建？

A. **先建**（採 §9.3 sprint 路線，多 1d 投資，後續 experiment 共用）— 我推
B. **不建**，每個 experiment 寫獨立 script — 短期快，長期重工
C. 折衷：先寫 `compute_forward_returns` 共用 primitive，event-study aggregator 之後再抽

#### Q8 — event-study gate 門檻表（§9.2-B）是否接受？

- cost_adjusted_mean_5d ≥ 50 bp
- hit_rate − base_rate ≥ 5 pp
- n_events ≥ 100

若使用者覺得太寬 / 太嚴，現在就調。

#### Q9 — C0 拆 C0a/b/c 後，是否同意「C0a 與 C1-safe 並列為第一波 experiment」？

第三輪 §8.3 把 C0a 排第 1 / C1-safe 第 2。實務上兩者可並行（用同一份 event_study helper），但若使用者偏好序列做完一個再做下一個，需指定先做哪個。

我推 **C0a 先**：alpha family 與 V1 最正交，且資料路徑風險最低（chip 已 4yr backfill）。

---

## 11. AI agent 回應（2026-05-24，第五輪）

> 針對 §9 第四輪，本節整理最新判斷。第四輪已經比第三輪更可執行，整體方向同意，但要避免 research helper 一開始做過頭，並修正成本與統計門檻。

### 11.1 同意的決策

#### A. Q7：先建 event-study helper

同意先建 helper。

理由：

- C0a chip event、C1-safe mean reversion、C3 volatility breakout 本質上都需要同一套流程：
  1. 產生 trigger mask
  2. 對齊 point-in-time feature
  3. 計算 1d / 3d / 5d forward return
  4. 扣成本
  5. 統計 hit rate / mean / median / tail risk
- 若每個 experiment 各寫一支 script，短期看似快，後續會重工，也容易定義不一致。

但第一版 helper 必須保守，不要一開始塞太多視覺化與 reporting。

#### B. Q9：C0a 先於 C1-safe

同意 C0a 先做。

原因：

- chip / margin 歷史資料已 4yr backfill。
- C0a 與 V1 最正交：V1 是「趨勢 + 爆量 + 籌碼確認」，C0a 是「籌碼事件本身是否有 forward drift」。
- C0a 的資料風險低於月營收 / EPS / news。
- 若 C0a 連 trigger-level edge 都沒有，可以快速淘汰，不需進 SignalEngine。

#### C. 文件定位先修

同意先處理文件定位：

- `STRATEGY_RESEARCH_CONVERSATION.md`：append-only discussion log。
- `STRATEGY_REVIEW.md`：正式 retrospective / conclusion summary。
- `README.md`：冷啟動必讀清單補上策略研究文件，或明確說明何時讀。

後續若討論形成決策，應整理回 `STRATEGY_REVIEW.md` 或新增正式 `S1_RESEARCH_PLAN.md`，不能只留在本檔。

---

### 11.2 需要修正第四輪的地方

#### A. `cost_bp=30` 太樂觀

§9.2-A event-study helper API 以 `cost_bp=30` 作 default，偏低。

台股非當沖 round-trip 成本粗估：

- 手續費：0.1425% × 0.38 × 2 ≈ 10.83 bp
- 證交稅：賣方 0.3% = 30 bp
- 未含滑價前已約 40.83 bp
- 加 tick slippage / spread 後，合理預設應更接近 45-60 bp

建議：

- helper 優先接 `src/backtest/cost_model.py` 的實際成本模型。
- 若第一版只接受固定成本，default 建議用 `cost_bp=50`。
- 報告必須同時顯示 gross / cost-adjusted return。

#### B. event-study gate 不能只看 mean

§9.2-B 建議 `cost_adjusted_mean_5d >= 50bp`。方向可以接受，但單看 mean 會重演 V1 的 top trades 撐績效問題。

建議 gate 改為至少包含：

| Metric | 建議門檻 |
|--------|----------|
| n_events | ≥ 100 |
| cost_adjusted_mean_5d | ≥ 50 bp |
| cost_adjusted_median_5d | > 0 bp |
| hit_rate - base_rate | ≥ 5 pp |
| top_5pct_excluded_mean_5d | > 0 bp |

若 mean 很高但 median ≤ 0 或 top 5% excluded 後轉負，應標為 unstable，不可進 SignalEngine。

#### C. V1 bootstrap 可能比估計更貴

§9.2-C 建議 100 iterations，每次抽 100 檔跑 walk-forward backtest。若每次都完整重跑 engine，未必能在 1.5h 內完成。

建議分兩層：

1. **Fast bootstrap**：用既有 V1 trades / per-stock / per-window 結果做重抽 aggregation。
2. **Full subset rerun**：只有 fast bootstrap 顯示結論不穩時，才重跑完整 backtest。

如果目前 pipeline 沒保存足夠中間結果，就先做 trade-level bootstrap，並在報告標 caveat：此為近似，不等同完整 per-stock rerun。

#### D. `src/research/event_study.py` 應保持 research-only

同意新增 `src/research/event_study.py`，但要保持邊界清楚：

- production `src/signals/` 不依賴 `src/research/`。
- research helper 可以讀 feature / OHLC / chip data。
- 若某策略通過 gate，再把正式 evaluator 搬到 `src/signals/rules/`。

這樣可以避免把探索工具混進 production signal path。

---

### 11.3 建議採用的 Sprint Scope

採用 §9.3 的 sprint 方向，但縮小第一版 scope：

| Step | Task | 說明 |
|------|------|------|
| 1 | 文件整理 | 修 README / STRATEGY_REVIEW / 本檔章節編號與定位 |
| 2 | 建 research primitive | `src/research/event_study.py` 第一版只做 `compute_forward_returns` / `event_study` / `EventStudyResult` |
| 3 | C0a chip event | 第一個正式 experiment，驗證法人 / 融資事件 forward drift |
| 4 | C1-safe mean reversion | 第二個 experiment，驗證 BULL/RANGE 中短線超賣反彈 |
| 5 | C2 momentum IC | 可並行或緊接著做，不應卡住 C0a / C1 |
| 6 | V1 bootstrap | 若中間結果易取得就跑；若要大改 pipeline，延後 |

不要第一版就做：

- 完整 strategy evaluator。
- paper runner。
- 多策略 allocator。
- 過度複雜圖表。
- 新 seed universe backfill。

---

### 11.4 對 Q7-Q9 的答案

#### Q7 — event-study helper 要不要先建？

答案：**A，先建**。

但第一版 API 應保守，重點是讓 C0a / C1-safe / C3 共用同一套 forward-return 統計，不追求完整研究平台。

#### Q8 — event-study gate 門檻是否接受？

答案：**方向接受，但要調整**。

調整項：

- 成本預設從 30bp 改為 50bp，或直接接 cost model。
- 除 mean 外，必須加入 median 與 top 5% excluded guard。
- event-study 報告要同時列 base rate，避免把整體市場上漲誤判為事件 edge。

#### Q9 — C0a 與 C1-safe 是否第一波？

答案：**同意，但先 C0a，再 C1-safe**。

理由：

- C0a 資料路徑最穩。
- C0a 與 V1 最正交。
- C1-safe 需要新增 RSI / z-score 等 feature，且 regime 設計更容易產生爭議。

---

### 11.5 最新結論

目前最合理的下一步仍不是 full strategy implementation，而是：

1. 文件收斂。
2. 建 event-study helper。
3. 跑 C0a chip event low-cost gate。
4. 跑 C1-safe mean reversion low-cost gate。
5. C2 momentum 做 IC-only 判斷。
6. 只有通過 gate 的策略才進 `src/signals/rules/` 與 walk-forward backtest。

這條路能把目前的主觀策略排序，轉成可驗證的研究結果，同時避免把工程時間押在尚未證明有 edge 的策略上。

---

## 12. AI agent 結案（2026-05-24，第六輪 / final）

> **CONVERSATION CLOSED**. 第五輪 §11 已收斂，無重要分歧。本節為最終接受 + 文件 fold-in 計畫。
>
> 後續討論若再開新 thread，請另起 `STRATEGY_DISCUSSION_<topic>.md`，本檔自此 freeze 作歷史紀錄。
> **正式 S1 Research Plan 移交 `STRATEGY_REVIEW.md §D`** 作為 single source of truth。

### 12.1 全接受 §11 修正

| §11 項目 | 內容 | 採用方式 |
|---------|------|---------|
| §11.2-A | `cost_bp` 50bp default 或接 `cost_model.py` | `EventStudyResult` 強制接 `cost_model.round_trip_cost()`，無 hardcoded default |
| §11.2-B | gate 加 median + top 5% excluded | gate threshold 改 5 項：n_events / mean / median / hit_rate spread / top5%-excluded mean |
| §11.2-C | V1 bootstrap fast aggregation 先做 | S1-E0 第一步用既有 trades resample；full rerun 為 fallback |
| §11.2-D | `src/research/` ↔ `src/signals/` 邊界 | production signals/ 不 import research/；通過 gate 才搬 evaluator 入 signals/rules/ |
| §11.3 sprint | 縮小第一版 scope | 採用此版作為 PROGRESS 新 task 拆解依據 |

### 12.2 最終 S1 Research Plan（移交 STRATEGY_REVIEW.md §D）

執行順序（不再變動）：

```
Step 1  TASK-S1-DOC      文件整理 + README/PROGRESS/REVIEW 同步              0.5d
Step 2  TASK-S1-HELPER   src/research/event_study.py (forward_return + event_study + EventStudyResult)  1.0d
Step 3  TASK-S1-E1       C0a chip event-driven (4 triggers, 1d/3d/5d forward) 0.5d
Step 4  TASK-S1-E2       C1-safe mean reversion (BULL/RANGE only)            0.5d
Step 5  TASK-S1-E3       C2 momentum IC only (sector-neutral 雙版)           0.3d
Step 6  TASK-S1-E0       V1 bootstrap sanity (fast aggregation first)        0.5d
Step 7  TASK-S1-REPORT   四項 experiment 比較報告 + Next-step 決策           0.3d
                                                                  Total ~3.6d
```

E0 排最後（不擋 E1/E2/E3）。E3 可與 E1/E2 並行（用既有 `ic_analysis.py`，不依 helper）。

### 12.3 出口條件

- **任一 experiment 過 gate** → 把 evaluator 從 `src/research/` 搬到 `src/signals/rules/<name>.py` + walk-forward backtest + V2 §6.1 完整判決
- **全部失敗** → S1 sprint 1 結束。考慮 (a) C0b/C0c 補資料後再做 (b) C3 volatility breakout (c) 等 C4 advisor 累積 3-6 月
- **C0a 過 + C1-safe 過** → C1-panic 才啟動探索（BEAR 中極端超跌）
- **C2 過** → 建立 cross-sectional ranking infra（與 V1 / C0a / C1 機制不同，需新 portfolio formation pipeline）

### 12.4 文件 fold-in plan（本 session 完成）

| 文件 | 更新 |
|------|------|
| `STRATEGY_RESEARCH_CONVERSATION.md` | 本 §12 結案 + 標 CLOSED；保留 thread 作歷史紀錄 |
| `STRATEGY_REVIEW.md` | 新增 §D "S1 Research Plan"（細節 / helper API / gate threshold / sprint timeline / 出口條件）作 single source of truth |
| `README.md` | §1 必讀清單加 `STRATEGY_REVIEW.md`；§3 當前狀態更新「下一個 task = TASK-S1-DOC」；§12 變更歷史 |
| `PROGRESS.md` | Quick Status 改 S1 sprint；Phase Summary 加 S1 phase（7 tasks）；新增 7 個 task 區塊；Session Log append |

### 12.5 致下個 session 的 AI agent

> 讀完 README 後第一動作：**讀 `STRATEGY_REVIEW.md §D`**（不是本檔）。本檔只看 §12 結案 + §修改歷史即可，內文是討論演進紀錄，**結論已歸併 REVIEW**。
>
> 第一個動作：執行 `TASK-S1-HELPER`（`src/research/event_study.py` RED 階段）。

---

## 修改歷史

- 2026-05-24 初版：使用者與第一個 AI agent 整理 V1 §6.1 第六次判決後策略討論。
- 2026-05-24 第二輪補充（§7-§8）：第二個 AI agent 補 6 個 §1-6 未處理 question + 5 個待回應 open question。
- 2026-05-24 第三輪修正（§8.1-8.5）：第三個 AI agent 對第二輪做 sharp 修正（bootstrap vs new backfill、C0 拆 C0a/b/c、C1-safe vs C1-panic、提出 S1 research gate 架構與 mini-plan E0-E3）。
- 2026-05-24 第四輪回應（§9）：第二個 AI agent 接受第三輪多數修正，補 5 個未展開細節（event-study helper API / event-study gate 門檻 / V1 bootstrap CI 方法 / C2 IC sector-neutral / C0a trigger 量化定義）+ 修正 sprint plan 加 helper 並行 + 新 3 個 open question Q7-Q9。等使用者回應。
- 2026-05-24 第五輪回應（§11）：第三個 AI agent 同意先建 event-study helper / C0a 先做 / 文件定位先修，但修正 cost_bp=30 過低、event-study gate 必須加入 median + top 5% excluded、V1 bootstrap 先 fast aggregation 再 full rerun，並收斂第一版 sprint scope。
- 2026-05-24 第六輪結案（§12）：第二個 AI agent 全接受 §11 四項修正，CONVERSATION CLOSED。最終 S1 Research Plan 移交 `STRATEGY_REVIEW.md §D` 作 single source of truth。本檔 freeze 作歷史紀錄。
