# 新聞 Gemini 應用重構計畫

> 制定日期：2026-04-25
> 目的：重構 `src/news/news_summarizer.py`，將 LLM 從「逐篇摘要工具」提升為「聚合分析引擎」，產出可直接支援投資決策的結構化資訊。

---

## 背景

### 現況問題
- 每次 run 對每篇文章呼叫 Gemini（60+ 次 API call）
- 免費層 15 RPM 立即打爆，整輪約需 4~5 分鐘
- 產出是每篇「繁中摘要 + 股票標籤」，**未解決使用者真正的需求**：
  - ❌ 沒有全局重點總結
  - ❌ 沒有針對自選股的影響分析
  - ❌ 沒有市場情緒/板塊熱度等高價值訊號

### 使用者目標（2026-04-25 對話確認）
1. Gemini 精簡總結所有新聞重點
2. Gemini 根據所有新聞判斷股市可能影響

---

## 新架構方向

**核心原則**：LLM 只做「聚合分析」，不做「逐篇摘要」。單篇新聞的標題+excerpt 直接從 RSS 顯示即可。

### 每輪 run 的 Gemini 呼叫（2~3 次）

| Query | 輸入 | 輸出（結構化 JSON） |
|---|---|---|
| `summarize_global` | 所有分類新聞標題+excerpt | 全局重點 + 各分類要點 + 市場情緒分數 |
| `analyze_favorites_impact` | 所有新聞 + 我的最愛清單 | 每檔自選股 → 訊號（🟢🟡🔴） + 理由 + 引用新聞 |
| *（可選）* `generate_pre_market_brief` | 美股相關新聞 | 台股盤前 3 大觀察點 |

免費層 15 RPM 完全足夠，單次 run **< 10 秒**。

---

## Phase 1：聚合分析骨架 ⬅️ **當前進行中**

### 目標
重構 `NewsSummarizer`，改為聚合分析；更新資料模型；最小 UI 連接確認流程可用。

### 後端變更
- `src/news/news_models.py`：新增
  - `GlobalBrief` dataclass（今日重點 + 各分類要點 + 市場情緒 0~100）
  - `FavoriteSignal` dataclass（stock_id, signal, reason, referenced_urls）
  - `NewsRunResult` 新增 `global_brief` 與 `favorite_signals` 欄位
- `src/news/news_summarizer.py`：
  - 新增 `summarize_global(articles_by_category) -> GlobalBrief`
  - 新增 `analyze_favorites_impact(articles, favorites) -> List[FavoriteSignal]`
  - 保留舊方法暫不刪除（先走新流程，確認穩定再清理）
- `src/news/news_processor.py`：
  - `run()` 改呼叫新方法；不再對每篇文章呼叫 LLM
  - 文章的 `summary` 欄位填原始 RSS excerpt（非 LLM 輸出）
  - `related_stock_ids` 從 `FavoriteSignal.referenced_urls` 反查回填

### UI 變更（最小可用）
- `/news` 頁面頂部加「今日重點」卡片（顯示 `GlobalBrief.overall_summary` + 情緒分數）
- 主頁面新增「自選股訊號」橫幅區（顯示 `FavoriteSignal` 列表）

### 驗收標準
- [ ] 手動點「手動更新」10 秒內完成
- [ ] `data/news/latest.json` 包含 `global_brief` 與 `favorite_signals`
- [ ] `/news` 顯示今日重點卡片
- [ ] 主頁面顯示自選股訊號
- [ ] 單元測試 pass（新方法 + fallback 行為）

---

## Phase 2：情緒與板塊指標

- **市場情緒儀表板**：0~100 分 + Fear/Greed 式顏色標示
- **板塊熱度**：AI / 半導體 / 電動車 / 金融 / 傳產 等熱度排名
- 新增 UI 元件：情緒計儀表、板塊 heatmap

---

## Phase 3：歷史比對與 RAG 問答

- 新聞歷史資料保留 ≥ 30 日
- **事件 timeline**：同一議題跨多日的演進
- **問答介面**：側欄 chat，使用者自然語言詢問（RAG 架構）
- **異常偵測**：突然爆量的議題自動標記

---

## 進階構想（未排程）

- 個股深度報告（點擊股票 → 關聯新聞 + 影響分析 + 技術面交叉比對）
- 新聞去重 / 事件聚類（同一件事多媒體報導合併）
- 自動產生投組調整建議（⚠️ 投資建議合規問題）

---

## 技術備註

- Gemini context window：1M token，本專案新聞量（60+ 篇 × 標題+excerpt）約 10~30K token，綽綽有餘
- 建議 model：`gemini-3.1-flash-lite-preview`（聚合分析場景 CP 值最高）
- 結構化輸出使用 JSON schema，方便 UI 渲染
- 既有的 client-side throttle + 429 retry 機制保留作為保險
