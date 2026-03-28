# 軟體需求規格書 (Software Requirements Specification)
## 新聞收集與摘要子模組 (News Collection & Summarization Submodule)

## 專案概述

**專案名稱**：autoFetchStock - 新聞收集與摘要子模組

**專案描述**：作為 autoFetchStock 系統的新增子模組，本模組負責每日定時收集國際、財經、科技及台美股票相關新聞，並對所有收集到的新聞文章進行自動摘要。模組依附於現有 APScheduler 排程架構，整合我的最愛清單（`data/cache/`）進行個股相關新聞過濾，並以 JSON 格式透過 DataStorage 的原子性寫入機制儲存摘要結果。

**相關現有基礎設施**：
- **排程器**：`src/scheduler/scheduler.py`（APScheduler）
- **資料儲存**：`src/storage/data_storage.py`（JSON 原子性寫入）
- **資料模型**：`src/models.py`（Dataclass + Enum）
- **設定**：`src/config.py`（AppConfig）
- **例外**：`src/exceptions.py`（AutoFetchStockError 繼承體系）
- **我的最愛清單**：`data/cache/` 中的 `StockInfo` 清單

**新增模組位置**：
```
src/news/
├── news_fetcher.py       # NewsFetcher：從各新聞來源抓取原始新聞
├── news_summarizer.py    # NewsSummarizer：呼叫摘要 API 對新聞進行摘要
├── news_processor.py     # NewsProcessor：整合抓取與摘要流程、管理分類
└── news_models.py        # 新聞相關 Dataclass / Enum 定義
```

**資料儲存路徑**：
- `data/news/{yyyymmdd}.json` — 當日所有分類新聞與摘要
- `data/news/latest.json` — 最新一次執行的新聞摘要（符號連結或複本）

---

## 功能性需求

### 核心系統需求

#### REQ-200 (基礎型 / Ubiquitous)
新聞子模組（news submodule）應以 Python >= 3.10 實作，並完整整合至現有 autoFetchStock 分層架構（Layered Architecture）。

#### REQ-201 (基礎型 / Ubiquitous)
新聞子模組應使用 `logging.getLogger("autofetchstock.news")` 記錄所有運作狀態、警告及錯誤資訊。

#### REQ-202 (基礎型 / Ubiquitous)
新聞子模組應定義以下新聞資料 Dataclass，且每個 Dataclass 均須實作 `to_dict()` 及 `from_dict()` 方法：
- `NewsArticle`：單篇新聞（標題、來源、URL、發布時間、原文摘錄、摘要文字、新聞分類）
- `NewsCategoryResult`：單一分類的新聞集合（分類名稱、文章列表、分類整體摘要、收集時間戳記）
- `NewsDailyFile`：當日 JSON 檔案根結構（日期、執行紀錄列表，每次執行包含所有分類結果）

#### REQ-203 (基礎型 / Ubiquitous)
新聞子模組應定義 `NewsCategory` Enum，包含以下值：
- `INTERNATIONAL`（國際新聞）
- `FINANCIAL`（財經/經濟新聞）
- `TECH`（科技產業新聞）
- `STOCK_TW`（台灣個股相關新聞）
- `STOCK_US`（美國個股相關新聞）

---

### 排程需求

#### REQ-210 (事件驅動型 / Event-Driven)
當系統啟動時，新聞子模組應向現有 APScheduler 排程器（`src/scheduler/scheduler.py`）註冊新聞收集任務，首次執行時間為當日 Asia/Taipei 時區 08:00。

#### REQ-211 (狀態驅動型 / State-Driven)
當新聞收集任務處於執行排程中且當前 Asia/Taipei 時間介於 08:00 至 15:00 之間時，新聞子模組應每隔 60 分鐘觸發一次完整的新聞收集與摘要流程。

#### REQ-212 (狀態驅動型 / State-Driven)
當 Asia/Taipei 時間超過 15:00 時，新聞子模組應停止當日剩餘的排程觸發，不再執行新的新聞收集任務，直至次日 08:00。

#### REQ-213 (事件驅動型 / Event-Driven)
當跨越午夜（00:00 Asia/Taipei）時，新聞子模組應重設當日執行計數器，並確保次日 08:00 能正確觸發新的排程週期。

#### REQ-214 (基礎型 / Ubiquitous)
新聞子模組的排程設定（起始時間 08:00、結束時間 15:00、執行間隔 60 分鐘）應透過 `AppConfig` 集中管理，允許從設定檔或環境變數覆寫預設值。

---

### 新聞來源分類需求

#### REQ-220 (基礎型 / Ubiquitous)
每次新聞收集執行時，新聞子模組應依序收集以下四個固定分類的新聞，每個分類收集的文章數量上限為 20 篇：
1. 國際新聞（`INTERNATIONAL`）
2. 財經/經濟新聞（`FINANCIAL`）
3. 科技產業新聞（`TECH`）
4. 台灣及美國個股新聞（`STOCK_TW` 及 `STOCK_US`）

#### REQ-221 (基礎型 / Ubiquitous)
新聞子模組在收集國際新聞（`INTERNATIONAL`）時，應涵蓋全球政治、地緣政治、總體經濟政策及國際貿易等主題。

#### REQ-222 (基礎型 / Ubiquitous)
新聞子模組在收集財經/經濟新聞（`FINANCIAL`）時，應涵蓋股市大盤動態、央行政策、匯率、大宗商品及 IPO 等財經主題。

#### REQ-223 (基礎型 / Ubiquitous)
新聞子模組在收集科技產業新聞（`TECH`）時，應涵蓋半導體、AI、雲端運算、消費性電子及科技公司財報等科技主題。

#### REQ-224 (事件驅動型 / Event-Driven)
當新聞子模組執行我的最愛個股新聞收集時，應從 `data/cache/` 讀取使用者我的最愛清單（`StockInfo` 列表），並以每支股票的股票代號（`stock_id`）及股票名稱（`stock_name`）作為查詢關鍵字，分別收集台灣（`STOCK_TW`）及美國（`STOCK_US`）相關新聞。

#### REQ-225 (事件驅動型 / Event-Driven)
當新聞子模組完成個股新聞查詢時，每篇 `NewsArticle` 應記錄其關聯的股票代號（`related_stock_ids` 欄位），以便後續過濾與追溯。

---

### 我的最愛整合需求

#### REQ-230 (事件驅動型 / Event-Driven)
當新聞收集任務啟動時，新聞子模組應讀取 `data/cache/` 中的我的最愛清單檔案，並以該次讀取的結果作為本輪個股新聞查詢的依據。

#### REQ-231 (狀態驅動型 / State-Driven)
當我的最愛清單中包含一或多支股票時，新聞子模組應對清單中的每支股票各自執行台灣及美國新聞查詢，並將結果分別歸入 `STOCK_TW` 及 `STOCK_US` 分類。

#### REQ-232 (狀態驅動型 / State-Driven)
當我的最愛清單為空或無法讀取時，新聞子模組應略過 `STOCK_TW` 及 `STOCK_US` 分類的收集，仍完整執行其他三個固定分類（`INTERNATIONAL`、`FINANCIAL`、`TECH`）的收集與摘要，並於日誌中記錄略過原因。

---

### 新聞摘要需求

#### REQ-240 (基礎型 / Ubiquitous)
新聞子模組應對每篇收集到的 `NewsArticle` 進行單篇摘要，摘要結果應儲存於 `NewsArticle.summary` 欄位，長度不超過 200 個中文字元（或等效英文字元數）。

#### REQ-241 (基礎型 / Ubiquitous)
新聞子模組應對每個 `NewsCategoryResult` 產生分類整體摘要（`category_summary` 欄位），整合該分類所有文章的重點，長度不超過 500 個中文字元（或等效英文字元數）。

#### REQ-242 (事件驅動型 / Event-Driven)
當某一分類下所有文章的單篇摘要均完成後，新聞子模組應立即生成該分類的整體摘要，不等待其他分類完成。

#### REQ-243 (基礎型 / Ubiquitous)
新聞子模組的摘要功能（`NewsSummarizer`）應支援透過設定檔切換摘要後端（例如：OpenAI API、本地 LLM 或規則式摘要），摘要後端的選擇應透過 `AppConfig` 中的 `NEWS_SUMMARIZER_BACKEND` 設定項目控制。

#### REQ-244 (基礎型 / Ubiquitous)
新聞子模組對摘要 API 的每次請求逾時上限應設為 30 秒，若超過逾時時間則視為單次請求失敗。

---

### 資料儲存需求

#### REQ-250 (基礎型 / Ubiquitous)
新聞子模組應將每日所有執行結果儲存於 `data/news/{yyyymmdd}.json`，檔名中的日期應為 Asia/Taipei 時區的當日日期（格式：`YYYYMMDD`）。

#### REQ-251 (事件驅動型 / Event-Driven)
當每次新聞收集與摘要流程完成後，新聞子模組應以追加（append）方式將本次執行的 `NewsCategoryResult` 列表寫入當日 `data/news/{yyyymmdd}.json`，不覆蓋同日先前的執行結果。

#### REQ-252 (基礎型 / Ubiquitous)
新聞子模組對 `data/news/` 目錄下所有 JSON 檔案的寫入操作應使用原子性寫入機制（先寫暫存檔再執行 `os.replace()`），確保寫入中斷時不產生損毀檔案。

#### REQ-253 (基礎型 / Ubiquitous)
新聞子模組在執行任何寫入操作前，應透過 `DataStorage` 的磁碟空間檢查機制確認可用空間，若可用空間低於 100 MB 則拋出 `DiskSpaceError` 並中止寫入。

#### REQ-254 (事件驅動型 / Event-Driven)
當每次執行完成後，新聞子模組應同步更新 `data/news/latest.json`，內容為本次執行的完整結果，以便 Dash 前端能快速讀取最新新聞摘要而無需解析日期。

#### REQ-255 (基礎型 / Ubiquitous)
`data/news/{yyyymmdd}.json` 的根結構應符合 `NewsDailyFile` Dataclass 定義，包含以下必要欄位：
- `date`（字串，格式 `YYYYMMDD`，Asia/Taipei 日期）
- `runs`（列表，每個元素包含 `run_at` 時間戳記及 `categories` 分類結果列表）

---

### 效能需求

#### REQ-260 (基礎型 / Ubiquitous)
新聞子模組對單一新聞來源的 HTTP 請求逾時上限應設為 15 秒；若超過此上限，視為該來源本次請求失敗。

#### REQ-261 (基礎型 / Ubiquitous)
新聞子模組對同一新聞來源的連續請求間隔應至少 2 秒，以避免觸發來源網站的速率限制（rate limiting）。

#### REQ-262 (基礎型 / Ubiquitous)
單次完整新聞收集與摘要流程（含所有分類）的總執行時間上限應不超過 30 分鐘，確保在下一個 60 分鐘排程觸發前能完成執行。

#### REQ-263 (基礎型 / Ubiquitous)
新聞子模組的記憶體佔用量（不含已有 autoFetchStock 進程的基礎記憶體）在單次執行過程中應不超過 256 MB。

---

## 非功能性需求

### 可靠性需求

#### REQ-270 (基礎型 / Ubiquitous)
新聞子模組應確保單一分類或單篇文章的收集/摘要失敗不影響其他分類或文章的處理，各分類的執行結果相互獨立。

#### REQ-271 (基礎型 / Ubiquitous)
新聞子模組應記錄每次執行的開始時間、結束時間、成功收集文章數、失敗數及摘要完成數，並儲存於 `NewsDailyFile` 中的執行統計欄位（`run_stats`）。

### 可維護性需求

#### REQ-272 (基礎型 / Ubiquitous)
`NewsFetcher`、`NewsSummarizer` 及 `NewsProcessor` 應分別為獨立模組，各自職責單一，遵循現有分層架構慣例。

#### REQ-273 (基礎型 / Ubiquitous)
新聞來源的設定（來源 URL、API 金鑰、查詢參數）應集中定義於 `AppConfig` 或對應的設定常數，不得硬編碼（hardcode）於業務邏輯程式碼中。

---

## 選配功能

#### REQ-280 (選配型 / Optional)
若系統包含新聞頁面功能，則新聞子模組應提供 Dash callback 接口，使前端能讀取 `data/news/latest.json` 並以分類頁籤方式顯示各類新聞摘要。

#### REQ-281 (選配型 / Optional)
若系統包含新聞通知功能，則當與我的最愛股票相關的負面新聞出現時，新聞子模組應於系統介面顯示高亮警示訊息。

#### REQ-282 (選配型 / Optional)
若系統包含新聞歷史查詢功能，則新聞子模組應支援依日期範圍讀取 `data/news/{yyyymmdd}.json` 並返回對應日期的新聞摘要列表。

#### REQ-283 (選配型 / Optional)
若系統包含多語言摘要功能，則新聞子模組應支援透過設定指定摘要輸出語言（繁體中文或英文），預設輸出語言為繁體中文。

---

## 錯誤處理

#### REQ-290 (異常行為型 / Unwanted Behavior)
若新聞來源 HTTP 請求連線逾時（超過 15 秒無回應），則新聞子模組應中斷該次請求，記錄逾時錯誤至日誌，並繼續處理下一個新聞來源，不中斷整體執行流程。

#### REQ-291 (異常行為型 / Unwanted Behavior)
若單一新聞來源回傳 HTTP 4xx 或 5xx 錯誤狀態碼，則新聞子模組應記錄錯誤狀態碼及來源 URL 至日誌，並跳過該來源，繼續執行其他來源的收集。

#### REQ-292 (異常行為型 / Unwanted Behavior)
若同一新聞來源連續失敗達 3 次（跨執行週期累計），則新聞子模組應將該來源標記為暫時停用，並於 24 小時後自動重新啟用，標記狀態應記錄於 `AppConfig` 的執行期狀態中。

#### REQ-293 (異常行為型 / Unwanted Behavior)
若摘要 API（`NewsSummarizer`）對單篇文章的摘要請求失敗（含逾時、API 錯誤或網路中斷），則新聞子模組應將該篇 `NewsArticle.summary` 欄位設為空字串，並在 `NewsArticle` 中記錄 `summary_failed: true` 旗標，繼續處理其他文章。

#### REQ-294 (異常行為型 / Unwanted Behavior)
若某一分類下所有文章的摘要均失敗，則新聞子模組應略過該分類的整體摘要生成（`category_summary` 設為空字串），並於日誌記錄該分類摘要完全失敗的警告，不拋出例外至上層排程。

#### REQ-295 (異常行為型 / Unwanted Behavior)
若 `data/cache/` 中的我的最愛清單檔案讀取失敗（檔案不存在、JSON 損毀或格式錯誤），則新聞子模組應略過 `STOCK_TW` 及 `STOCK_US` 分類，記錄警告日誌，並繼續執行其他三個固定分類，不拋出例外至上層排程。

#### REQ-296 (異常行為型 / Unwanted Behavior)
若 `data/news/{yyyymmdd}.json` 寫入操作失敗（磁碟空間不足除外），則新聞子模組應重試寫入最多 2 次（間隔 5 秒），若仍失敗則記錄完整錯誤堆疊至日誌並拋出 `DataCorruptedError`，同時保留當次執行結果於記憶體以供手動查詢。

#### REQ-297 (異常行為型 / Unwanted Behavior)
若新聞收集任務執行過程中發生未預期的例外錯誤，則新聞子模組應捕捉該例外，記錄完整錯誤堆疊（stack trace）至日誌，並透過現有 `SchedulerTaskError` 機制通知排程器，確保下一次排程觸發不受影響。

---

## 需求追溯矩陣

| 需求編號 | 功能領域 | EARS 類型 | 優先級 |
|---------|---------|----------|--------|
| REQ-200 | 核心系統 | 基礎型 | 必要 |
| REQ-201 | 核心系統 | 基礎型 | 必要 |
| REQ-202 | 核心系統 | 基礎型 | 必要 |
| REQ-203 | 核心系統 | 基礎型 | 必要 |
| REQ-210 | 排程 | 事件驅動型 | 必要 |
| REQ-211 | 排程 | 狀態驅動型 | 必要 |
| REQ-212 | 排程 | 狀態驅動型 | 必要 |
| REQ-213 | 排程 | 事件驅動型 | 必要 |
| REQ-214 | 排程 | 基礎型 | 必要 |
| REQ-220 | 新聞來源分類 | 基礎型 | 必要 |
| REQ-221 | 新聞來源分類 | 基礎型 | 必要 |
| REQ-222 | 新聞來源分類 | 基礎型 | 必要 |
| REQ-223 | 新聞來源分類 | 基礎型 | 必要 |
| REQ-224 | 新聞來源分類 | 事件驅動型 | 必要 |
| REQ-225 | 新聞來源分類 | 事件驅動型 | 建議 |
| REQ-230 | 我的最愛整合 | 事件驅動型 | 必要 |
| REQ-231 | 我的最愛整合 | 狀態驅動型 | 必要 |
| REQ-232 | 我的最愛整合 | 狀態驅動型 | 必要 |
| REQ-240 | 新聞摘要 | 基礎型 | 必要 |
| REQ-241 | 新聞摘要 | 基礎型 | 必要 |
| REQ-242 | 新聞摘要 | 事件驅動型 | 建議 |
| REQ-243 | 新聞摘要 | 基礎型 | 必要 |
| REQ-244 | 新聞摘要 | 基礎型 | 必要 |
| REQ-250 | 資料儲存 | 基礎型 | 必要 |
| REQ-251 | 資料儲存 | 事件驅動型 | 必要 |
| REQ-252 | 資料儲存 | 基礎型 | 必要 |
| REQ-253 | 資料儲存 | 基礎型 | 必要 |
| REQ-254 | 資料儲存 | 事件驅動型 | 建議 |
| REQ-255 | 資料儲存 | 基礎型 | 必要 |
| REQ-260 | 效能 | 基礎型 | 必要 |
| REQ-261 | 效能 | 基礎型 | 必要 |
| REQ-262 | 效能 | 基礎型 | 必要 |
| REQ-263 | 效能 | 基礎型 | 建議 |
| REQ-270 | 可靠性 | 基礎型 | 必要 |
| REQ-271 | 可靠性 | 基礎型 | 必要 |
| REQ-272 | 可維護性 | 基礎型 | 必要 |
| REQ-273 | 可維護性 | 基礎型 | 必要 |
| REQ-280 | 選配功能 | 選配型 | 選配 |
| REQ-281 | 選配功能 | 選配型 | 選配 |
| REQ-282 | 選配功能 | 選配型 | 選配 |
| REQ-283 | 選配功能 | 選配型 | 選配 |
| REQ-290 | 錯誤處理 | 異常行為型 | 必要 |
| REQ-291 | 錯誤處理 | 異常行為型 | 必要 |
| REQ-292 | 錯誤處理 | 異常行為型 | 建議 |
| REQ-293 | 錯誤處理 | 異常行為型 | 必要 |
| REQ-294 | 錯誤處理 | 異常行為型 | 必要 |
| REQ-295 | 錯誤處理 | 異常行為型 | 必要 |
| REQ-296 | 錯誤處理 | 異常行為型 | 必要 |
| REQ-297 | 錯誤處理 | 異常行為型 | 必要 |

---

## 品質門檻狀態

**需求 -> 設計 品質門檻**：
- ✓ 所有需求均具有唯一識別碼（REQ-XXX 格式），共計 49 項需求（REQ-200 至 REQ-297），無與現有 REQ-001~REQ-106 衝突
- ✓ 每項需求均遵循 EARS 語法模式（基礎型 / 事件驅動型 / 狀態驅動型 / 選配型 / 異常行為型）
- ✓ 所有需求均可測試（包含可量化的結果，如逾時秒數、文章數上限、摘要字元上限、執行間隔等）
- ✓ 未使用模糊用語（已排除「應該」、「可能」、「或許」、「大概」等不確定用語，所有行為以「應」明確規範）
- ✓ 涵蓋所有功能領域（排程、新聞分類收集、我的最愛整合、摘要、資料儲存、效能、可靠性、可維護性）
- ✓ 已定義錯誤場景（8 項異常行為處理需求，REQ-290~REQ-297）
- ✓ 已定義非功能性需求（效能、可靠性、可維護性）

**可進入設計階段**：是
