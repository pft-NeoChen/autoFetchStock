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

## Phase 3：歷史化、事件演進、異常偵測與 RAG 問答

> Phase 3 不應一次做成一個大改版。它實際包含「歷史資料基礎建設」、「事件聚類」、「異常標記」、「RAG 問答」四條風險不同的工作流。落地順序以依賴關係為準：先讓歷史資料可讀、可清、可測；再產生穩定的事件資料；最後才把互動式問答接上。

### Phase 3 整體設計決策

- **資料來源標準化**：歷史分析只讀 `data/news/YYYYMMDD.json` 內的 `NewsDailyFile.runs`，先 flatten 成去重後的 article corpus。去重 key 優先使用 URL；同 URL 多次 run 只保留最新一次，避免每小時排程造成同一篇新聞被重複計數。
- **歷史分析不阻塞每小時新聞收集**：`NewsProcessor.run()` 維持 Phase 1/2 的即時新聞流程；timeline、anomaly、RAG index 走獨立 job 或手動方法，避免手動更新新聞時被 7 日歷史分析拖慢。
- **事件檔獨立於 latest.json**：`latest.json` 仍只放最新新聞 run；事件 timeline 寫入 `data/news/events.json`，RAG index 寫入 `data/news/rag_embeddings.npz` 與 `data/news/rag_metadata.json`。Dash 前端新增獨立 store 載入事件資料，不把 events 塞進 `news-data-store`。
- **LLM 呼叫預算分層**：每小時新聞 run 維持目前呼叫；事件聚類每日最多 1 次 Gemini call；異常偵測純統計、0 LLM call；RAG 預設關閉，只有啟用後才做 embedding 與 answer call。
- **可回復與可降級**：任何歷史檔損毀、LLM 失敗、RAG index 不存在，都應回空資料或停用 UI，不影響現有新聞頁與主頁自選股訊號。

### Phase 3a：歷史資料基礎建設 ⬅️ **先做**

**目標**：讓 `data/news/YYYYMMDD.json` 可列舉、可區間讀取、可清理，作為後續 timeline / anomaly / RAG 的唯一歷史語料來源。

**後端變更**
- `src/config.py`：新增設定
  - `news_retention_days: int = 30`，可用 `NEWS_RETENTION_DAYS` override
  - `news_history_window_days: int = 7`，供 event timeline / anomaly 預設使用
- `src/storage/data_storage.py`：新增歷史檔 helper
  - `list_news_dates() -> List[str]`：只回傳符合 `^\d{8}\.json$` 的日期檔，排除 `latest.json`、`events.json`、暫存檔，結果升冪排序
  - `load_news_range(start_date: str, end_date: str) -> List[NewsDailyFile]`：逐日讀取，單檔 parse 失敗只記 warning 並跳過
  - `iter_news_articles(start_date, end_date, dedupe=True)` 或同等私有 helper：flatten `runs -> categories -> articles`，以 URL 去重；**dedupe 規則**：同 URL 多次出現時，保留**最後一次出現的 run 的 article 物件**（`related_stock_ids`、`summary` 取最後版本，因為通常累積最完整）。**歸日規則**：article 歸屬日期 = `published_at` 轉 Asia/Taipei 後的 `YYYYMMDD`，給 Phase 3b `daily_count` 共用，避免時區錯位
  - `cleanup_old_news(retention_days: int, now: Optional[date] = None) -> int`：實作採**白名單 match-then-delete**——只刪除符合 `^\d{8}\.json$` 且日期早於 cutoff 的檔案；任何不符合此 regex 的檔案（含 `latest.json`、`events.json`、`rag_*.json`、`rag_*.npz`、未來新增的 sidecar）一律保留
- `src/scheduler/scheduler.py`：新增 `add_news_cleanup_job(cleanup_callback)`，每日 23:55 Asia/Taipei 觸發
- `src/app/app_controller.py`：註冊 cleanup job，callback 呼叫 `storage.cleanup_old_news(config.news_retention_days)`

**測試**
- `cleanup_old_news`：用 `tmp_path` 建立日期檔、`latest.json`、`events.json`、非日期檔，驗證 cutoff 邊界與保留規則
- `list_news_dates`：驗證排序、格式過濾、空目錄
- `load_news_range`：驗證 start/end inclusive、缺檔跳過、單一損毀檔不影響其他日期
- article flatten/dedupe helper：同 URL 多 run 只留最新文章，跨分類重複 URL 不重複計數

**驗收標準**
- [ ] `data/news/` 只清掉超過 retention 的日期檔，`latest.json` / `events.json` / index 檔不被刪
- [ ] 可以從任意日期區間載入 `NewsDailyFile`，單檔損毀不會中斷整批
- [ ] flatten 後的歷史文章沒有同 URL 重複
- [ ] 單元測試 pass

---

### Phase 3b：事件 timeline（同議題跨日演進）

**目標**：把過去 N 日（預設 7）的去重新聞聚類成「事件」，產出可被 UI 直接渲染的 `events.json`，呈現同一議題跨日演進。

**資料模型**
- `src/news/news_models.py`：新增 `EventCluster`
  - `event_id: str`：穩定 ID。由 normalized title / keywords 做 hash，不能直接用 LLM 每次任意產生的流水號
  - `title: str`
  - `summary: str`
  - `keywords: List[str]`
  - `first_seen: str`、`last_seen: str`（YYYYMMDD）
  - `article_urls: List[str]`
  - `daily_count: Dict[str, int]`
  - `sectors: List[str]`
  - `related_stock_ids: List[str]`
  - anomaly 欄位先預留預設值：`is_anomaly=False`、`anomaly_score=0.0`、`anomaly_reason=""`，Phase 3c 再填值，避免下一階段再做 schema migration
- 新增 `NewsEventFile`
  - `generated_at: str`
  - `window_start: str`
  - `window_end: str`
  - `clusters: List[EventCluster]`
  - `source_article_count: int`

**後端變更**
- `src/news/news_summarizer.py`：新增 `cluster_events(articles, window_days=7) -> List[EventCluster]`
  - input 使用 Phase 3a flatten 後的文章：title、source、url、published_at、category、excerpt、related_stock_ids
  - **input 上限**：文章 ≤ 800 篇（超過則依 `published_at` 降序取最近 800 篇），LLM cluster 數輸出上限 50；超量在 prompt 內限制 + parser 端再做 truncate，避免 prompt / events.json 失控
  - 1 次 Gemini call，要求輸出事件 title / summary / keywords / article_urls / sectors / related_stock_ids
  - parser 必須只接受存在於 input 的 URL，未知 URL 丟棄；cluster 沒有有效 URL 則丟棄
  - `event_id` 由程式端產生，不信任 LLM 回傳
  - **event_id 跨 build 穩定性**：先讀既有 `events.json`，對每個新 cluster 依 keywords Jaccard ≥ 0.5（或 normalized title 相似度 ≥ 0.8）匹配既有 cluster，命中則沿用舊 `event_id`，避免「台積電財報」vs「台積電 Q1 財報」被切成兩個事件。未命中才用 `sha1(sorted(keywords) + normalized_title)[:12]` 產新 ID。文件中聲明：跨 build 盡力穩定但不保證 100%
- `src/news/news_processor.py`：新增 `build_event_timeline(window_days=None) -> NewsEventFile`
  - 從 `storage.load_news_range()` 取歷史資料
  - 呼叫 `cluster_events`
  - 依 article published date（Asia/Taipei）回填 `first_seen`、`last_seen`、`daily_count`；明白聲明 `first_seen/last_seen` 限定於當前 window，跨 window 不持久化（events.json 為每日完全覆蓋語義）
  - **失敗回復**：LLM call 拋例外或 parser 回空 cluster 時，**保留上次 events.json 不覆蓋**，僅記錄 warning，呼應 Phase 1 graceful fallback
  - 寫入 `storage.save_news_events(event_file)`，目標 `data/news/events.json`
- `src/storage/data_storage.py`：新增 `save_news_events(event_file)`、`load_news_events()`
- `src/scheduler/scheduler.py`：新增 `add_news_event_job(event_callback)`，每日 16:05 Asia/Taipei 觸發（避開 08:00-15:00 每小時新聞收集）
- `src/app/app_controller.py`：註冊 event job，callback 呼叫 `news_processor.build_event_timeline(config.news_history_window_days)`

**UI 變更**
- `src/app/layout.py`
  - `/news` 新增「議題演進」區塊，dom id：`event-timeline`
  - hidden components 新增 `dcc.Store(id="news-events-store")`
  - `dom_ids` 補 `news_events_store`、`event_timeline`
- `src/app/callbacks.py`
  - 新增 `refresh_news_events_store`：定期或手動從 `storage.load_news_events()` 載入
  - 新增 `render_event_timeline`：用 Plotly stacked bar 或 grouped bar，X 軸日期、Y 軸文章數、color 事件
  - 圖下方顯示事件清單：title、summary、first_seen~last_seen、文章連結前 3 筆

**測試**
- `EventCluster` / `NewsEventFile` round-trip、unknown field fallback、舊 schema fallback
- `cluster_events` parser：未知 URL 丟棄、空 URL cluster 丟棄、event_id 穩定（同批重跑 stable + 跨 build 對相似 cluster 沿用舊 ID）
- `cluster_events` 文章上限：> 800 篇 input 時 prompt 只送最近 800 篇
- `build_event_timeline`：mock 7 日 daily files，驗證 URL dedupe、daily_count（時區轉換正確）、events.json 寫入
- `build_event_timeline` 失敗回復：LLM 拋例外時既有 events.json 不被覆蓋
- UI helper：空 events、正常 events、文章連結 render

**驗收標準**
- [ ] `data/news/events.json` 產出且符合 `NewsEventFile`
- [ ] 同一批 input 重跑時 `event_id` 穩定
- [ ] 同 URL 多 run 不會讓 `daily_count` 膨脹
- [ ] `/news` 顯示議題演進圖與事件摘要
- [ ] event job 每日最多新增 1 次 Gemini call，不影響每小時新聞 run

---

### Phase 3c：異常偵測（議題爆量標記）

**目標**：在已產生的 `EventCluster.daily_count` 上做純統計異常標記，找出「今日或最近一日突然爆量」的事件，不增加 LLM 呼叫。

**後端變更**
- 新模組 `src/news/news_anomaly.py`
  - `mark_event_anomalies(clusters, min_history_days=3, z_threshold=2.0) -> List[EventCluster]`
  - latest day = cluster `daily_count` 中最新日期
  - baseline = latest day 前 N 日的平均與標準差
  - 若歷史天數不足，`is_anomaly=False`，`anomaly_reason="歷史資料不足"`
  - 若標準差為 0，使用保守 fallback：latest count >= max(3, mean * 2) 才標異常
  - 計算結果寫回 `is_anomaly`、`anomaly_score`、`anomaly_reason`
- `NewsProcessor.build_event_timeline()` 結尾呼叫 `mark_event_anomalies` 後再寫 `events.json`

**UI 變更**
- `event-timeline`：
  - 異常事件在圖例 / 清單顯示「爆量」badge
  - bar 顏色或 marker 增加異常提示，但不要只靠顏色，需有文字 badge
- 主頁 `favorite-signal-strip`：
  - 若異常事件的 `related_stock_ids` 命中目前 favorite，該股票訊號項目顯示小型異常提示
  - **callback inputs 變動**：原本只讀 `news-data-store`，現在須額外讀 `news-events-store`，render helper 簽章與 callback decorator 都要更新
  - 若沒有 event data 或 store 為空，維持現有 UI，不顯示錯誤

**測試**
- `news_anomaly`：z-score 正常命中、未命中、少於 min_history_days、stdev=0 fallback
- `EventCluster` anomaly 欄位 round-trip
- `build_event_timeline`：確認寫入 events 前已標 anomaly
- UI helper：有 anomaly badge / 無 anomaly / 無 events store 三種情境

**驗收標準**
- [ ] `events.json.clusters[*]` 可包含 `is_anomaly=true` 與可讀的 `anomaly_reason`
- [ ] 異常偵測不產生任何 Gemini / embedding call
- [ ] `/news` timeline 清楚標示爆量事件
- [ ] 主頁自選股訊號能在有命中時顯示異常提示，無資料時優雅降級

### Phase 3a/3b/3c e2e 整合驗收

各 sub-phase 均為 unit test，需另設一組整合測試確保串聯正確：
- 給定 7 日 mock `YYYYMMDD.json`（含同 URL 跨日重複、含一日突發爆量主題）
- 順序執行：`cleanup_old_news` → `iter_news_articles` → `build_event_timeline`（內含 `cluster_events` + `mark_event_anomalies`）
- 驗收：產出的 `events.json` 包含正確 `daily_count`（時區無誤）、爆量事件被標記 `is_anomaly=true`、retention 外的檔案已刪除、`latest.json` 與 `events.json` 自身保留

---

### Phase 3d：RAG 問答側欄（最後做、預設關閉）

**目標**：使用者在 `/news` 側欄用自然語言詢問歷史新聞，例如「台積電最近有什麼利多？」、「AI 板塊本週發生什麼事？」；回答必須基於檢索到的新聞並附引用來源。

**設定與儲存**
- `src/config.py`
  - `news_rag_enabled: bool = False`，由 `NEWS_RAG_ENABLED` 控制，預設關閉
  - `news_rag_window_days: int = 30`
  - `news_rag_top_k: int = 8`
  - `news_rag_max_new_embeddings_per_day: int = 100`
  - `news_rag_embedding_model: str = "text-embedding-004"`（Gemini embedding model）
  - `news_rag_max_chat_history_turns: int = 6`（送入 prompt 的最近 user+assistant 輪數上限，避免多輪 chat prompt 暴漲）
- 儲存檔
  - `data/news/rag_embeddings.npz`：embedding matrix
  - `data/news/rag_metadata.json`：每列 embedding 對應的 url、title、source、published_at、category、excerpt、content_hash

**後端變更**
- 新模組 `src/news/news_rag.py`
  - `build_or_update_index(historical_articles)`：只為 content hash 不存在的新文章建立 embedding；超過每日上限則跳過並記 warning
  - **index garbage collection**：build/update 同時剔除 metadata 中 `published_at < now - news_rag_window_days` 的 row，並對 `rag_embeddings.npz` 做對應的 row 重寫，避免 index 無限膨脹
  - `retrieve(query, top_k=8)`：query embedding × cosine similarity，回傳含 score 的 citation chunks
  - `answer(query, chat_history)`：retrieve → 組 grounded prompt → Gemini 回答，回傳 `NewsRagAnswer(answer, citations, failed=False)`
  - **chat_history 截斷**：傳入前先截到最近 `news_rag_max_chat_history_turns` 輪
  - **citation validation**：LLM 回答中提到的 URL 必須屬於 `retrieve()` 結果集合；非屬集合的 URL 從 citations 移除（防 LLM 幻覺 URL）
  - backend 不可用、index 不存在、RAG disabled 時，回 graceful response，不丟到 UI
- `src/news/news_models.py`：新增輕量模型
  - `NewsRagCitation(url, title, source, published_at, score)`
  - `NewsRagAnswer(answer, citations, failed=False, error_reason="")`
- `src/news/news_processor.py`：新增 `update_rag_index(window_days=None)`，由 scheduler 或手動維護觸發；不放進每小時 `run()`
- `src/scheduler/scheduler.py`：新增 `add_news_rag_index_job(index_callback)`，每日 16:20 觸發；只有 `news_rag_enabled=True` 才註冊

**UI 變更**
- `src/app/layout.py`
  - `/news` 新增 collapsible 側欄 `news-chat-sidebar`
  - 元件：`news-chat-input`、送出 icon button、`news-chat-history` store、`news-chat-messages`
  - RAG disabled 時顯示收合狀態或短訊息，不佔用主要新聞內容
- `src/app/callbacks.py`
  - `submit_chat_message`：append user message → 呼叫 `news_rag.answer` → append assistant response
  - 回答使用 `[1] [2]` citation 標記；下方列出可點擊來源，不依賴 hover 才能看到 URL
  - 失敗時顯示「目前無法回答」類訊息，不清空既有對話

**測試**
- `build_or_update_index`：content_hash 去重、每日上限、metadata 與 matrix row 對齊
- `build_or_update_index` GC：超出 `news_rag_window_days` 的 row 被剔除、剩餘 row 與 matrix index 仍對齊
- `retrieve`：mock embedding，驗證 cosine 排序與 top_k
- `answer` citation validation：LLM 回傳的 URL 不在 retrieve 集合時被剔除
- `answer` chat_history 截斷：超過 `news_rag_max_chat_history_turns` 時 prompt 只含最近 N 輪
- `answer`：mock retrieve + mock Gemini，驗證 citations、LLM 失敗 graceful response
- disabled path：`news_rag_enabled=False` 時不建立 index、不呼叫 Gemini、不破壞 UI
- UI callback：送出空字串、正常回答、失敗回答、多輪 history

**驗收標準**
- [ ] `news_rag_enabled=False` 時，沒有 embedding / answer call，側欄優雅停用
- [ ] `news_rag_enabled=True` 時，可建立或增量更新 index
- [ ] 側欄 chat 可問可答，回答至少附 1 個真實新聞 URL 引用
- [ ] embedding 每日新增量受 `news_rag_max_new_embeddings_per_day` 控制
- [ ] RAG backend 失敗不影響 `/news` 既有新聞、timeline、market dashboard

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
