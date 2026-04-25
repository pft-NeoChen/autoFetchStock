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

## Phase 1：聚合分析骨架 ✅ **已完成**（commit `d737cf5`、後續強化 `1ea8f97`、`2010475`、`f354ad2`）

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

## Phase 2：情緒與板塊指標 ⬅️ **已完成**（2026-04-25）

### 目標
在不增加 Gemini API 呼叫次數的前提下，把 Phase 1 已產出的市場情緒升級為視覺化儀表，並新增「板塊熱度」面向。

### 後端變更
- `src/news/news_models.py`：
  - 新增 `SectorHeat` dataclass（`sector`, `heat_score 0~100`, `trend up/down/flat`, `summary ≤80 字`, `referenced_urls ≤3`），含 `to_dict` / `from_dict`（在 `from_dict` 內 clamp、白名單 trend、cap URL 數量）
  - `GlobalBrief` 新增 `sector_heats: List[SectorHeat]` 欄位；序列化向下相容（缺欄位回傳空清單）
- `src/news/news_summarizer.py`：
  - 擴充 `_GLOBAL_BRIEF_PROMPT`：要求 LLM 在同一次呼叫中額外輸出 5 個基礎板塊（AI / 半導體 / 電動車 / 金融 / 傳產），允許再加最多 2 個熱門板塊
  - `_parse_global_brief_response` 增加 `sector_heats` 解析：clamp `heat_score` 到 0~100、trend 落入白名單，否則 fallback `"flat"`、同名板塊 dedupe、`referenced_urls` 上限 3 個
  - **API 預算不變**：板塊熱度 piggyback 在 global brief 同一次呼叫上，仍是 2~3 calls / run

### UI 變更
- `src/app/layout.py`：/news 頁面新增 `market-dashboard` 雙欄區塊（左：`market-sentiment-gauge`；右：`sector-heatmap`），`dom_ids` 補上對應 key
- `src/app/callbacks.py`：
  - 新增 `render_sentiment_gauge` callback：使用 `plotly.graph_objects.Indicator` 畫 Fear/Greed 風格儀表，分 5 段配色（極度恐慌綠 → 中性黃 → 極度樂觀紅）並加白色 threshold 指針
  - 新增 `render_sector_heatmap` callback：使用 Plotly 橫條圖按 `heat_score` 由高至低排序，依 trend 上色（紅 ▲ / 綠 ▼ / 灰 —）
  - 新增 `_render_sentiment_gauge` / `_render_sector_heatmap` / `_sentiment_color` helpers，與 `import dcc` + `import plotly.graph_objects as go`
- `src/app/assets/style.css`：新增 `.market-dashboard` grid layout（900px 以下塌成單欄）、容器與標題樣式

### 測試
- `tests/test_news/test_news_models.py`：補 `SectorHeat` round-trip、score clamp、trend 白名單、URL 上限、`GlobalBrief.sector_heats` round-trip、舊版（無 `sector_heats`）payload 相容
- `tests/test_news/test_summarizer_aggregate.py`：補 sector_heats 解析、score clamp、trend 白名單、同名 dedupe、缺欄位 fallback
- 全套 news + app 測試 86 / 86 通過

### 驗收標準
- [x] `data/news/latest.json.global_brief` 包含 `sector_heats` 陣列
- [x] /news 頁面顯示市場情緒儀表（Fear/Greed gauge）
- [x] /news 頁面顯示板塊熱度橫條圖（依熱度排序、依 trend 上色）
- [x] Gemini 呼叫次數維持與 Phase 1 相同
- [x] 單元測試 pass（含 schema fallback 行為）

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
