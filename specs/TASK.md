# 專案任務分解文件 (Task Breakdown Document)
## 新聞收集與摘要子模組 (News Collection & Summarization Submodule)

## 元資料
- **專案名稱**：autoFetchStock - 新聞收集與摘要子模組
- **最後更新**：2026-04-06
- **總任務數**：30
- **已完成**：0 (0%)

---

## P0：基礎建設

- [x] [TASK-100] 新增依賴套件
  - **複雜度**：S
  - **依賴**：無
  - **需求對應**：REQ-200
  - **檔案**：`requirements.txt`
  - **接受標準**：
    - 新增 `google-genai>=1.0` 至 requirements.txt（取代已棄用的 google-generativeai）
    - 新增 `atoma>=0.0.17` 至 requirements.txt（feedparser 在 Python 3.11 有 sgmllib 相依性問題）
    - 新增 `beautifulsoup4>=4.12` 至 requirements.txt
    - 新增 `lxml>=4.9` 至 requirements.txt
    - `python3 -c "import google.genai, atoma, bs4, lxml"` 可正常執行

- [ ] [TASK-101] 建立 src/news/ 模組目錄結構
  - **複雜度**：S
  - **依賴**：TASK-100
  - **需求對應**：REQ-200, REQ-272
  - **檔案**：`src/news/__init__.py`, `src/news/news_fetcher.py`, `src/news/news_summarizer.py`, `src/news/news_processor.py`, `src/news/news_models.py`
  - **接受標準**：
    - 建立 `src/news/` 目錄與所有 4 個模組檔案
    - 各模組檔案包含模組說明 docstring
    - `src/news/__init__.py` 匯出主要類別
    - 建立 `data/news/` 資料目錄
    - `from src.news import NewsProcessor` 可正常執行

- [ ] [TASK-102] 實作 news_models.py
  - **複雜度**：M
  - **依賴**：TASK-101
  - **需求對應**：REQ-202, REQ-203
  - **檔案**：`src/news/news_models.py`
  - **接受標準**：
    - 定義 `NewsCategory` Enum（INTERNATIONAL, FINANCIAL, TECH, STOCK_TW, STOCK_US）
    - 定義 `NewsArticle` dataclass（含 title, source, url, published_at, summary, category, related_stock_ids, full_text_fetched, summary_failed 欄位）
    - 定義 `NewsCategoryResult` dataclass（含 category, articles, category_summary, collected_at）
    - 定義 `NewsRunResult` dataclass（含 run_at, categories, run_stats）
    - 定義 `NewsDailyFile` dataclass（含 date, runs）
    - 所有 dataclass 實作 `to_dict()` 與 `from_dict()` 方法

- [ ] [TASK-103] 擴充 AppConfig 新聞設定欄位
  - **複雜度**：S
  - **依賴**：TASK-101
  - **需求對應**：REQ-214, REQ-243, REQ-273
  - **檔案**：`src/config.py`
  - **接受標準**：
    - 新增 `gemini_api_key` 欄位（從 `GEMINI_API_KEY` 環境變數讀取）
    - 新增 `news_start_hour: int = 8`、`news_end_hour: int = 15`、`news_interval_minutes: int = 60`
    - 新增 `news_max_articles_per_category: int = 20`
    - 新增 `news_request_timeout: int = 15`、`news_summarizer_timeout: int = 30`
    - 新增 `news_summarizer_backend: str = "gemini"`（備案值：`"gemini-cli"`，使用 subprocess 呼叫 gemini CLI）
    - `config.env.example` 新增 `GEMINI_API_KEY=YOUR_KEY_HERE`

- [ ] [TASK-104] 新增新聞相關例外類別
  - **複雜度**：S
  - **依賴**：TASK-101
  - **需求對應**：REQ-290, REQ-291, REQ-293
  - **檔案**：`src/exceptions.py`
  - **接受標準**：
    - 新增 `NewsFetchError(AutoFetchStockError)`（含 source_url, status_code 欄位）
    - 新增 `SummarizationError(AutoFetchStockError)`（含 article_url, reason 欄位）
    - 所有新例外繼承自 `AutoFetchStockError`
    - 各例外包含繁體中文預設訊息

---

## P1：資料抓取層

- [ ] [TASK-110] 實作 NewsFetcher RSS 抓取
  - **複雜度**：M
  - **依賴**：TASK-102, TASK-103
  - **需求對應**：REQ-220, REQ-221, REQ-222, REQ-223
  - **檔案**：`src/news/news_fetcher.py`
  - **接受標準**：
    - 實作 `fetch_rss(url: str) -> List[RawArticle]`，使用 feedparser 解析
    - 定義各分類 RSS 來源 URL 常數（Google News RSS + Yahoo Finance RSS）
    - 每個分類至少設定 2 個 RSS 來源
    - 解析結果包含 title, url, published_at, excerpt 欄位
    - RSS 請求逾時上限 15 秒

- [ ] [TASK-111] 實作 NewsFetcher 全文抓取
  - **複雜度**：M
  - **依賴**：TASK-110
  - **需求對應**：REQ-226
  - **檔案**：`src/news/news_fetcher.py`
  - **接受標準**：
    - 實作 `fetch_full_text(url: str) -> tuple[str, bool]`，回傳 (內容, full_text_fetched)
    - 使用 BeautifulSoup + lxml 解析 HTML，提取 `<p>` 標籤正文
    - HTTP GET 逾時上限 15 秒
    - 抓取失敗時 fallback 回傳 RSS excerpt，full_text_fetched=False
    - 過濾導覽列、廣告等非正文內容

- [ ] [TASK-112] 實作 NewsFetcher 分類抓取整合
  - **複雜度**：M
  - **依賴**：TASK-111
  - **需求對應**：REQ-220, REQ-224, REQ-225
  - **檔案**：`src/news/news_fetcher.py`
  - **接受標準**：
    - 實作 `fetch_category(category: NewsCategory, max_articles: int) -> List[RawArticle]`
    - 每篇文章呼叫 `fetch_full_text()` 取得全文
    - 回傳結果數量不超過 max_articles 上限
    - 各分類來源依序嘗試，合併結果後去重（依 URL）
    - 記錄每篇文章的抓取狀態至日誌

- [ ] [TASK-113] 實作個股新聞抓取與 TW/US 自動判斷
  - **複雜度**：M
  - **依賴**：TASK-112
  - **需求對應**：REQ-224, REQ-231
  - **檔案**：`src/news/news_fetcher.py`
  - **接受標準**：
    - 實作 `fetch_stock_news(stock_info: StockInfo) -> tuple[List[RawArticle], NewsCategory]`
    - stock_id 全數字 → 回傳 STOCK_TW，查詢台灣相關新聞
    - stock_id 含英文字母 → 回傳 STOCK_US，查詢美國相關新聞
    - 查詢關鍵字使用 stock_id + stock_name 組合
    - Google News RSS 查詢 URL 格式：`?q={stock_id}+{stock_name}&hl=zh-TW`（TW）/ `&hl=en-US`（US）

- [ ] [TASK-114] 實作速率限制與來源停用機制
  - **複雜度**：S
  - **依賴**：TASK-112
  - **需求對應**：REQ-261, REQ-292
  - **檔案**：`src/news/news_fetcher.py`
  - **接受標準**：
    - 同一 domain 請求間隔至少 2 秒
    - 追蹤各來源連續失敗次數
    - 連續失敗 3 次將來源標記為停用（disabled），記錄停用時間
    - 停用來源 24 小時後自動重新啟用
    - 停用狀態記錄至日誌

---

## P2：摘要層

- [ ] [TASK-120] 實作 NewsSummarizer Gemini API 整合
  - **複雜度**：M
  - **依賴**：TASK-103
  - **需求對應**：REQ-243, REQ-244
  - **檔案**：`src/news/news_summarizer.py`
  - **接受標準**：
    - 使用 `google-generativeai` SDK 初始化 `genai.GenerativeModel("gemini-2.0-flash")`
    - API key 從 `AppConfig.gemini_api_key` 讀取
    - 每次 API 請求設定 30 秒逾時
    - 實作 `_call_gemini(prompt: str) -> str` 基礎呼叫方法
    - 初始化失敗時拋出 `SummarizationError`
    - **備案**：`news_summarizer_backend="gemini-cli"` 時改用 `subprocess` 呼叫 `gemini -p`，透過暫存檔傳入 prompt 以規避 shell argument 長度與特殊字元問題

- [ ] [TASK-121] 實作單篇文章摘要與股票標記
  - **複雜度**：L
  - **依賴**：TASK-120
  - **需求對應**：REQ-240, REQ-227
  - **檔案**：`src/news/news_summarizer.py`
  - **接受標準**：
    - 實作 `summarize_article(article: RawArticle, favorites: List[StockInfo]) -> tuple[str, List[str]]`
    - 單一 Gemini prompt 同時完成：翻譯為繁體中文 + 摘要（≤200 字）+ 標記 related_stock_ids
    - prompt 明確要求輸出 JSON 格式：`{"summary": "...", "related_stocks": ["2330", ...]}`
    - 摘要長度超過 200 字時截斷並記錄警告
    - related_stock_ids 只包含 favorites 清單中存在的股票代號

- [ ] [TASK-122] 實作分類整體摘要
  - **複雜度**：M
  - **依賴**：TASK-121
  - **需求對應**：REQ-241, REQ-242
  - **檔案**：`src/news/news_summarizer.py`
  - **接受標準**：
    - 實作 `summarize_category(articles: List[NewsArticle], category: NewsCategory) -> str`
    - 整合該分類所有文章摘要，產生不超過 500 字的繁體中文整體摘要
    - 單一分類所有文章摘要完成後立即呼叫，不等待其他分類
    - 輸入文章列表為空時回傳空字串，不呼叫 Gemini API
    - 分類摘要包含該分類的主要趨勢與重點

- [ ] [TASK-123] 實作摘要錯誤處理
  - **複雜度**：S
  - **依賴**：TASK-121
  - **需求對應**：REQ-293, REQ-294
  - **檔案**：`src/news/news_summarizer.py`
  - **接受標準**：
    - API 呼叫逾時（30 秒）時設定 `summary_failed=True`，summary 設為空字串
    - API 回傳格式錯誤時嘗試解析純文字，失敗則設定 summary_failed=True
    - 單篇失敗不影響其他文章處理
    - 分類內所有文章 summary_failed 時略過分類整體摘要
    - 所有失敗均記錄至 `autofetchstock.news` logger

---

## P3：處理層

- [ ] [TASK-130] 實作 NewsProcessor 主流程
  - **複雜度**：L
  - **依賴**：TASK-113, TASK-123
  - **需求對應**：REQ-220, REQ-270
  - **檔案**：`src/news/news_processor.py`
  - **接受標準**：
    - 實作 `run() -> NewsRunResult` 執行完整新聞收集與摘要流程
    - 依序處理 5 個分類（INTERNATIONAL, FINANCIAL, TECH, STOCK_TW, STOCK_US）
    - 各分類獨立 try/except，單一分類失敗不中斷其他分類
    - 回傳包含所有分類結果的 NewsRunResult
    - 記錄 run_at, 各分類成功/失敗文章數至 run_stats

- [ ] [TASK-131] 實作 NewsProcessor 我的最愛整合
  - **複雜度**：M
  - **依賴**：TASK-130
  - **需求對應**：REQ-230, REQ-231, REQ-232, REQ-295
  - **檔案**：`src/news/news_processor.py`
  - **接受標準**：
    - 實作 `_load_favorites() -> List[StockInfo]`，從 DataStorage 讀取我的最愛
    - favorites 為空時略過 STOCK_TW/STOCK_US 並記錄警告日誌
    - favorites 讀取失敗（JSON 損毀等）時略過個股分類，繼續執行其他三類
    - 對每支股票呼叫 NewsFetcher.fetch_stock_news()，結果依 TW/US 分流

- [ ] [TASK-132] 實作錯誤隔離與執行統計
  - **複雜度**：M
  - **依賴**：TASK-130
  - **需求對應**：REQ-270, REQ-271, REQ-297
  - **檔案**：`src/news/news_processor.py`
  - **接受標準**：
    - 每個分類的例外被捕捉並記錄完整 stack trace
    - run_stats 包含：start_time, end_time, total_articles, success_count, failure_count, summary_success_count
    - 未預期例外透過 SchedulerTaskError 通知排程器
    - 單次執行總時間超過 30 分鐘時記錄警告
    - 執行結果保留於記憶體供查詢

- [ ] [TASK-133] 擴充 DataStorage 新聞儲存
  - **複雜度**：M
  - **依賴**：TASK-102
  - **需求對應**：REQ-250, REQ-251, REQ-252, REQ-253, REQ-254, REQ-255
  - **檔案**：`src/storage/data_storage.py`
  - **接受標準**：
    - 實作 `save_news(result: NewsRunResult, date: date) -> None`，追加至當日 JSON
    - 實作 `load_news(date: date) -> Optional[NewsDailyFile]`
    - 實作 `load_latest_news() -> Optional[NewsRunResult]`，讀取 latest.json
    - 每次 save 後同步更新 `data/news/latest.json`
    - 所有寫入使用原子性操作（os.replace()）

---

## P4：排程整合

- [ ] [TASK-140] 擴充 Scheduler 新增新聞排程
  - **複雜度**：M
  - **依賴**：TASK-130, TASK-103
  - **需求對應**：REQ-210, REQ-211, REQ-212, REQ-213, REQ-214
  - **檔案**：`src/scheduler/scheduler.py`
  - **接受標準**：
    - 實作 `add_news_job(news_callback: Callable) -> None`
    - 使用 APScheduler CronTrigger，hour=`8-14`，minute=`0`，timezone=Asia/Taipei
    - 15:00 後不觸發（hour 最大為 14，即最後一次為 14:00）
    - 跨午夜自動重設，次日 08:00 正確觸發
    - 新聞排程任務 job_id 為 `news_collection`

- [ ] [TASK-141] 擴充 AppController 初始化新聞模組
  - **複雜度**：S
  - **依賴**：TASK-140
  - **需求對應**：REQ-210
  - **檔案**：`src/app/app_controller.py`
  - **接受標準**：
    - 初始化 `NewsProcessor` 實例並持有引用
    - 呼叫 `scheduler.add_news_job(news_processor.run)` 注冊排程
    - 應用啟動日誌記錄新聞模組初始化成功
    - 新聞模組初始化失敗時記錄錯誤但不中斷主程式啟動

---

## P5：UI 層

- [ ] [TASK-150] 擴充 layout.py（路由與跑馬燈）
  - **複雜度**：M
  - **依賴**：TASK-102
  - **需求對應**：REQ-301, REQ-320
  - **檔案**：`src/app/layout.py`
  - **接受標準**：
    - 新增 `dcc.Location(id="url", refresh=False)` 至 hidden components
    - 新增頂部導航列，含「股票」（href="/"）和「新聞」（href="/news"）連結
    - 新增跑馬燈容器 `id="news-ticker-bar"`（預設隱藏）
    - 新增跑馬燈 Interval `id="news-ticker-interval", interval=5000`
    - 新增主頁面容器 `id="page-content"` 用於路由渲染

- [ ] [TASK-151] 實作 /news 頁面佈局
  - **複雜度**：M
  - **依賴**：TASK-150
  - **需求對應**：REQ-300, REQ-302, REQ-303
  - **檔案**：`src/app/layout.py`
  - **接受標準**：
    - 實作 `create_news_page_layout() -> html.Div`
    - 包含 5 個分類頁籤（id="news-category-tabs"）
    - 每個頁籤內容容器 id 格式：`news-{category.value}-content`
    - 顯示最後更新時間（id="news-last-updated"）
    - 包含手動重新整理按鈕（id="news-refresh-button"）

- [ ] [TASK-152] 實作主畫面第三個新聞 Tab
  - **複雜度**：M
  - **依賴**：TASK-150
  - **需求對應**：REQ-310, REQ-311, REQ-312
  - **檔案**：`src/app/layout.py`
  - **接受標準**：
    - 在現有 `dcc.Tabs` 新增第三個 Tab（label="新聞", value="news"）
    - 新聞 Tab 內含 5 個分類子頁籤（id="stock-news-category-tabs"）
    - 子頁籤內容容器 id 格式：`stock-news-{category.value}-content`
    - 無相關新聞時顯示「目前無相關新聞」提示（id="stock-news-empty-hint"）

- [ ] [TASK-153] 實作路由 callback
  - **複雜度**：S
  - **依賴**：TASK-151, TASK-152
  - **需求對應**：REQ-300, REQ-301
  - **檔案**：`src/app/callbacks.py`
  - **接受標準**：
    - 實作 callback：Input("url", "pathname") → Output("page-content", "children")
    - pathname="/news" 渲染 create_news_page_layout()
    - pathname="/" 渲染原有股票主畫面內容
    - 未知 pathname 重定向至 "/"

- [ ] [TASK-154] 實作主畫面新聞 Tab callback
  - **複雜度**：M
  - **依賴**：TASK-133, TASK-152
  - **需求對應**：REQ-310, REQ-311
  - **檔案**：`src/app/callbacks.py`
  - **接受標準**：
    - 當主畫面新聞 Tab 選中時讀取 latest.json
    - 依 current_stock 的 stock_id 過濾各分類 related_stock_ids
    - 各分類無相關文章時顯示空狀態提示
    - 文章顯示：標題、來源、發布時間、繁體中文摘要、原文連結

- [ ] [TASK-155] 實作 /news 頁面 callback
  - **複雜度**：M
  - **依賴**：TASK-133, TASK-151
  - **需求對應**：REQ-302, REQ-303
  - **檔案**：`src/app/callbacks.py`
  - **接受標準**：
    - 頁面載入時自動讀取 latest.json 並填入各分類頁籤
    - 手動重新整理按鈕觸發重新讀取 latest.json
    - 最後更新時間顯示 latest.json 的 run_at
    - latest.json 不存在時顯示「尚無新聞資料，請等待排程執行」

- [ ] [TASK-156] 實作跑馬燈 callback
  - **複雜度**：M
  - **依賴**：TASK-133, TASK-150
  - **需求對應**：REQ-320, REQ-321, REQ-322
  - **檔案**：`src/app/callbacks.py`
  - **接受標準**：
    - 每 5 秒輪播一則標題（5 個分類各取 1 則，最多 5 則）
    - 僅顯示 related_stock_ids 包含 current_stock 的文章
    - 無相關新聞時隱藏跑馬燈區塊（display: none）
    - 點擊標題切換主畫面至新聞 Tab 並捲動至對應文章
    - 使用 dcc.Store(id="news-ticker-store") 暫存輪播索引

---

## P6：測試

- [ ] [TASK-160] 建立 tests/test_news/ 目錄結構
  - **複雜度**：S
  - **依賴**：TASK-101
  - **需求對應**：REQ-200
  - **檔案**：`tests/test_news/__init__.py`, `tests/test_news/conftest.py`
  - **接受標準**：
    - 建立 tests/test_news/ 目錄與 __init__.py
    - conftest.py 定義共用 fixtures（mock_config, sample_favorites, sample_article）
    - pytest 可正確發現 test_news/ 目錄下的測試

- [ ] [TASK-161] 實作 test_news_models.py
  - **複雜度**：S
  - **依賴**：TASK-102, TASK-160
  - **需求對應**：REQ-202, REQ-203
  - **檔案**：`tests/test_news/test_news_models.py`
  - **接受標準**：
    - 測試 NewsCategory 所有 5 個值
    - 測試 NewsArticle.to_dict() / from_dict() 往返序列化
    - 測試 NewsDailyFile.to_dict() / from_dict() 往返序列化
    - 測試 summary_failed=True 時的序列化行為
    - 測試覆蓋率 >= 95%

- [ ] [TASK-162] 實作 test_news_fetcher.py
  - **複雜度**：M
  - **依賴**：TASK-114, TASK-160
  - **需求對應**：REQ-220~226, REQ-261, REQ-292
  - **檔案**：`tests/test_news/test_news_fetcher.py`
  - **接受標準**：
    - 使用 unittest.mock 模擬 feedparser 與 HTTP 請求
    - 測試全文抓取成功（full_text_fetched=True）
    - 測試全文抓取失敗 fallback 至 RSS 摘錄（full_text_fetched=False）
    - 測試速率限制（2 秒間隔）
    - 測試來源停用機制（連續 3 次失敗）

- [ ] [TASK-163] 實作 test_news_summarizer.py
  - **複雜度**：M
  - **依賴**：TASK-123, TASK-160
  - **需求對應**：REQ-240~244, REQ-293, REQ-294
  - **檔案**：`tests/test_news/test_news_summarizer.py`
  - **接受標準**：
    - 使用 unittest.mock 模擬 google.generativeai
    - 測試摘要長度 ≤ 200 字
    - 測試 related_stock_ids 只包含 favorites 中的股票
    - 測試 API 逾時時 summary_failed=True
    - 測試分類所有文章失敗時略過整體摘要

- [ ] [TASK-164] 實作 test_news_processor.py
  - **複雜度**：L
  - **依賴**：TASK-132, TASK-160
  - **需求對應**：REQ-270, REQ-271, REQ-230~232
  - **檔案**：`tests/test_news/test_news_processor.py`
  - **接受標準**：
    - 使用 tmp_path fixture 模擬 data/news/ 目錄
    - 測試 favorites 為空時略過 STOCK_TW/STOCK_US
    - 測試單一分類失敗不中斷其他分類
    - 測試 run_stats 欄位正確計算
    - 測試執行結果正確寫入 data/news/{date}.json

---

## 需求覆蓋矩陣

| 需求範圍 | 覆蓋任務 |
|---------|---------|
| REQ-200~203（核心系統） | TASK-100, TASK-101, TASK-102 |
| REQ-210~214（排程） | TASK-140, TASK-141 |
| REQ-220~227（新聞分類/全文） | TASK-110~114 |
| REQ-230~232（我的最愛） | TASK-131 |
| REQ-240~244（摘要） | TASK-120~123 |
| REQ-250~255（資料儲存） | TASK-133 |
| REQ-260~263（效能） | TASK-114, TASK-132 |
| REQ-270~273（可靠性/可維護性） | TASK-130, TASK-132 |
| REQ-290~297（錯誤處理） | TASK-104, TASK-114, TASK-123, TASK-131, TASK-132 |
| REQ-300~303（/news 頁面） | TASK-151, TASK-153, TASK-155 |
| REQ-310~312（個股新聞 Tab） | TASK-152, TASK-154 |
| REQ-320~322（跑馬燈） | TASK-150, TASK-156 |

---

## 品質門檻狀態

- ✓ 所有 61 項需求（REQ-200~REQ-322）均有對應任務
- ✓ 依賴關係無循環（DAG 驗證通過）
- ✓ 各任務均有可量化接受標準
- ✓ 總計 30 個任務，分 6 個階段，0 個孤立任務
- ✓ 測試任務（TASK-160~164）覆蓋所有核心層

**可進入實作階段**：是
