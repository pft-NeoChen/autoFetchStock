# 技術設計文件 (Technical Design Document)
## 新聞收集與摘要子模組 (News Collection & Summarization Submodule)

**版本**：1.0.0
**最後更新**：2026-03-29
**對應需求**：REQ-200~REQ-322（`specs/REQUIREMENTS.md`）

---

## 1. 模組架構

### 1.1 新增模組位置

```
src/news/
├── __init__.py
├── news_models.py       # NewsCategory enum + 所有 dataclass
├── news_fetcher.py      # NewsFetcher：RSS 抓取 + 全文解析
├── news_summarizer.py   # NewsSummarizer：Gemini API 摘要 + 標記
└── news_processor.py    # NewsProcessor：整合流程、分類管理
```

### 1.2 整合點

```
AppController
    └── NewsProcessor            ← 初始化並持有實例
            ├── NewsFetcher      ← 負責 RSS + 全文抓取
            ├── NewsSummarizer   ← 負責 Gemini 摘要/標記
            └── DataStorage      ← 共用現有儲存模組

Scheduler
    └── add_news_job()           ← 新增新聞排程任務（每小時觸發）

src/app/layout.py
    └── 新增：/news 路由、新聞 Tab、跑馬燈元件

src/app/callbacks.py
    └── 新增：新聞相關 callback（NewsCallbackManager）
```

### 1.3 資料流

```
[APScheduler 08:00~15:00 每小時]
         │
         ▼
  NewsProcessor.run()
    ├── DataStorage.load_favorites()      → List[StockInfo]
    ├── NewsFetcher.fetch_category(INTERNATIONAL)
    │     ├── fetch_rss(url)              → List[RawArticle]
    │     └── fetch_full_text(url)        → str (BeautifulSoup)
    ├── NewsSummarizer.summarize_article(text, favorites)
    │     └── Gemini API                 → summary + related_stock_ids
    ├── NewsSummarizer.summarize_category(articles)
    │     └── Gemini API                 → category_summary
    └── DataStorage.save_news(NewsDailyFile)
              └── data/news/{yyyymmdd}.json (atomic write)
              └── data/news/latest.json
```

---

## 2. 資料模型（`src/news/news_models.py`）

### 2.1 NewsCategory Enum

```python
class NewsCategory(Enum):
    INTERNATIONAL = "international"   # 國際新聞
    FINANCIAL     = "financial"       # 財經/經濟新聞
    TECH          = "tech"            # 科技產業新聞
    STOCK_TW      = "stock_tw"        # 台灣個股相關新聞
    STOCK_US      = "stock_us"        # 美國個股相關新聞

    @property
    def display_name(self) -> str:
        names = {
            NewsCategory.INTERNATIONAL: "國際",
            NewsCategory.FINANCIAL:     "財經",
            NewsCategory.TECH:          "科技",
            NewsCategory.STOCK_TW:      "台股個股",
            NewsCategory.STOCK_US:      "美股個股",
        }
        return names[self]
```

### 2.2 NewsArticle Dataclass

```python
@dataclass
class NewsArticle:
    title: str                          # 文章標題（原文）
    source: str                         # 新聞來源（如 "Reuters"）
    url: str                            # 原始文章 URL
    published_at: datetime              # 發布時間（UTC）
    category: NewsCategory              # 所屬分類
    excerpt: str                        # RSS 提供的短摘錄（原文）
    full_text: str                      # 全文內容（BeautifulSoup 解析）
    summary: str                        # 繁體中文摘要（Gemini 生成，≤200 字）
    related_stock_ids: List[str]        # 關聯股票代號列表（Gemini 標記）
    full_text_fetched: bool = True      # 是否成功取得全文（False = 使用 RSS 摘錄）
    summary_failed: bool = False        # 摘要是否失敗

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "NewsArticle": ...
```

### 2.3 NewsCategoryResult Dataclass

```python
@dataclass
class NewsCategoryResult:
    category: NewsCategory
    articles: List[NewsArticle]
    category_summary: str               # 分類整體摘要（≤500 字）
    fetched_at: datetime                # 本次收集時間戳記
    article_count: int                  # 成功收集篇數
    failed_count: int                   # 失敗篇數
    summary_failed: bool = False        # 整體摘要是否失敗

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "NewsCategoryResult": ...
```

### 2.4 NewsRunResult Dataclass

```python
@dataclass
class NewsRunResult:
    run_at: datetime                    # 本次執行觸發時間（Asia/Taipei）
    finished_at: datetime               # 完成時間
    categories: List[NewsCategoryResult]
    run_stats: NewsRunStats             # 執行統計

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "NewsRunResult": ...

@dataclass
class NewsRunStats:
    total_articles: int
    successful_articles: int
    failed_articles: int
    total_summaries: int
    failed_summaries: int
    duration_seconds: float
```

### 2.5 NewsDailyFile Dataclass（JSON 根結構）

```python
@dataclass
class NewsDailyFile:
    date: str                           # 格式 "YYYYMMDD"（Asia/Taipei）
    runs: List[NewsRunResult]           # 當日所有執行結果

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "NewsDailyFile": ...
```

### 2.6 JSON 檔案範例（`data/news/20260329.json`）

```json
{
  "date": "20260329",
  "runs": [
    {
      "run_at": "2026-03-29T08:00:00+08:00",
      "finished_at": "2026-03-29T08:12:34+08:00",
      "categories": [
        {
          "category": "international",
          "fetched_at": "2026-03-29T08:01:00+08:00",
          "article_count": 18,
          "failed_count": 2,
          "category_summary": "今日國際局勢...",
          "articles": [
            {
              "title": "US Fed holds rates steady",
              "source": "Reuters",
              "url": "https://...",
              "published_at": "2026-03-29T01:30:00Z",
              "category": "international",
              "excerpt": "The Federal Reserve...",
              "full_text": "...",
              "summary": "聯準會維持利率不變，暗示年內可能降息...",
              "related_stock_ids": ["2330", "TSMC"],
              "full_text_fetched": true,
              "summary_failed": false
            }
          ]
        }
      ],
      "run_stats": {
        "total_articles": 95,
        "successful_articles": 91,
        "failed_articles": 4,
        "total_summaries": 91,
        "failed_summaries": 2,
        "duration_seconds": 754.2
      }
    }
  ]
}
```

---

## 3. NewsFetcher 設計（`src/news/news_fetcher.py`）

### 3.1 RSS 來源設定

```python
# 固定分類 RSS 來源
RSS_SOURCES: Dict[NewsCategory, List[str]] = {
    NewsCategory.INTERNATIONAL: [
        "https://feeds.reuters.com/reuters/worldNews",
        "https://news.google.com/rss/headlines/section/topic/WORLD?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    ],
    NewsCategory.FINANCIAL: [
        "https://finance.yahoo.com/news/rssindex",
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    ],
    NewsCategory.TECH: [
        "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
        "https://feeds.feedburner.com/techcrunch/startups",
    ],
}

# 個股新聞 URL 模板（動態查詢）
GOOGLE_NEWS_STOCK_URL = (
    "https://news.google.com/rss/search"
    "?q={keyword}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
)
YAHOO_FINANCE_STOCK_URL = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline"
    "?s={symbol}&region=US&lang=en-US"
)
```

### 3.2 介面定義

```python
class NewsFetcher:
    def __init__(self, config: AppConfig): ...

    def fetch_category(
        self,
        category: NewsCategory,
        max_articles: int = 20
    ) -> List[RawArticle]:
        """抓取指定分類的 RSS 文章列表（含全文）。"""

    def fetch_stock_news(
        self,
        stock_info: StockInfo,
        max_articles: int = 20
    ) -> Tuple[List[RawArticle], List[RawArticle]]:
        """
        抓取個股相關新聞。
        返回 (tw_articles, us_articles)。
        台股（純數字 stock_id）查詢中文關鍵字 + Google News TW。
        美股（含英文字母 stock_id）查詢英文 symbol + Yahoo Finance。
        """

    def fetch_rss(self, url: str) -> List[RawArticle]:
        """解析 RSS Feed，返回原始文章列表（標題、URL、發布時間、摘錄）。"""

    def fetch_full_text(self, url: str) -> Tuple[str, bool]:
        """
        抓取文章全文。
        返回 (text, success)。
        失敗時返回 ("", False)，呼叫方應 fallback 至 RSS 摘錄。
        """

    def _is_taiwan_stock(self, stock_id: str) -> bool:
        """純數字代碼 → 台股；含英文字母 → 美股。"""
        return stock_id.isdigit()

    def _extract_text_from_html(self, html: str) -> str:
        """BeautifulSoup 解析 HTML，提取 <p> 正文段落。"""
```

### 3.3 速率限制

- 同一網域請求間隔：最少 2 秒（`_domain_last_request: Dict[str, float]`）
- HTTP 請求逾時：15 秒（REQ-260）
- RSS 解析使用 `feedparser` 函式庫

---

## 4. NewsSummarizer 設計（`src/news/news_summarizer.py`）

### 4.1 Gemini API 整合

```python
import google.generativeai as genai

class NewsSummarizer:
    MODEL_NAME = "gemini-2.0-flash"
    REQUEST_TIMEOUT = 30  # 秒

    def __init__(self, config: AppConfig):
        genai.configure(api_key=config.gemini_api_key)
        self._model = genai.GenerativeModel(self.MODEL_NAME)
        self._favorites: List[StockInfo] = []  # 用於 related_stock_ids 標記

    def set_favorites(self, favorites: List[StockInfo]) -> None:
        """每次執行前設定我的最愛列表，供標記使用。"""

    def summarize_article(self, article: RawArticle) -> Tuple[str, List[str], bool]:
        """
        翻譯 + 摘要 + 標記一次完成。
        返回 (summary, related_stock_ids, success)。
        summary：繁體中文，≤200 字。
        related_stock_ids：self._favorites 中關聯的 stock_id 列表。
        """

    def summarize_category(self, articles: List[NewsArticle]) -> Tuple[str, bool]:
        """
        生成分類整體摘要。
        返回 (category_summary, success)。
        category_summary：繁體中文，≤500 字。
        """
```

### 4.2 單篇摘要 Prompt 設計

```python
ARTICLE_PROMPT_TEMPLATE = """\
你是一位專業財經新聞編輯。請根據以下新聞內容完成兩件事：

1. 將新聞摘要成繁體中文，字數不超過 200 字，重點包含：事件、影響、數據。
2. 從以下股票清單中，判斷哪些股票與此新聞有直接或間接關聯，列出股票代號（無關聯則回傳空列表）。

股票清單（代號: 名稱）：
{stock_list}

新聞標題：{title}
新聞內容：
{content}

請以下列 JSON 格式回應，不要包含其他文字：
{{
  "summary": "繁體中文摘要...",
  "related_stock_ids": ["2330", "NVDA"]
}}
"""
```

### 4.3 分類整體摘要 Prompt

```python
CATEGORY_PROMPT_TEMPLATE = """\
你是一位專業財經新聞編輯。以下是今日「{category_name}」類別的新聞摘要列表，
請整合重點，撰寫一段不超過 500 字的繁體中文總結，涵蓋最重要的趨勢與事件。

各篇摘要：
{summaries}

請直接回應繁體中文總結內容，不需要加標題或格式標記。
"""
```

---

## 5. NewsProcessor 設計（`src/news/news_processor.py`）

### 5.1 介面定義

```python
class NewsProcessor:
    def __init__(
        self,
        fetcher: NewsFetcher,
        summarizer: NewsSummarizer,
        storage: DataStorage,
        config: AppConfig,
    ): ...

    def run(self) -> NewsRunResult:
        """
        完整執行一次新聞收集與摘要流程。
        由 APScheduler 觸發。
        1. 載入我的最愛列表
        2. 依序處理 5 個分類（各自獨立，互不影響）
        3. 儲存結果至 data/news/{yyyymmdd}.json + latest.json
        """

    def _process_category(
        self,
        category: NewsCategory,
        favorites: List[StockInfo],
    ) -> NewsCategoryResult:
        """處理單一分類（抓取 → 逐篇摘要 → 分類整體摘要）。"""

    def _load_favorites(self) -> List[StockInfo]:
        """
        從 DataStorage 載入我的最愛列表。
        失敗時返回空列表，不拋出例外（REQ-295）。
        """
```

### 5.2 執行流程（每小時觸發）

```
run()
 ├── 1. load_favorites() → List[StockInfo]
 ├── 2. summarizer.set_favorites(favorites)
 ├── 3. 依序處理各分類（try/except 各自隔離）：
 │      INTERNATIONAL → _process_category()
 │      FINANCIAL     → _process_category()
 │      TECH          → _process_category()
 │      STOCK_TW      → _process_category()（favorites 為空時跳過）
 │      STOCK_US      → _process_category()（favorites 為空時跳過）
 ├── 4. 建立 NewsRunResult
 └── 5. storage.save_news(result) → data/news/{yyyymmdd}.json
                                 → data/news/latest.json
```

---

## 6. 排程整合（`src/scheduler/scheduler.py` 擴充）

### 6.1 新增 Scheduler 方法

```python
def add_news_job(self, news_callback: Callable[[], None]) -> None:
    """
    註冊新聞收集排程任務。
    使用 CronTrigger：每天 08:00~15:00，每小時一次（Asia/Taipei）。
    """
    from apscheduler.triggers.cron import CronTrigger
    self._scheduler.add_job(
        func=news_callback,
        trigger=CronTrigger(
            hour="8-15",
            minute=0,
            timezone=TW_TIMEZONE,
        ),
        id="news-hourly",
        name="新聞收集與摘要",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,  # 允許 5 分鐘遲發
    )

def remove_news_job(self) -> None:
    """移除新聞排程任務。"""
    if self._scheduler.get_job("news-hourly"):
        self._scheduler.remove_job("news-hourly")
```

### 6.2 AppController 整合

```python
# src/app/app_controller.py 新增
from src.news.news_models import *
from src.news.news_fetcher import NewsFetcher
from src.news.news_summarizer import NewsSummarizer
from src.news.news_processor import NewsProcessor

class AppController:
    def _init_news_module(self) -> None:
        self._news_fetcher = NewsFetcher(self._config)
        self._news_summarizer = NewsSummarizer(self._config)
        self._news_processor = NewsProcessor(
            fetcher=self._news_fetcher,
            summarizer=self._news_summarizer,
            storage=self._storage,
            config=self._config,
        )
        self._scheduler.add_news_job(self._news_processor.run)
```

---

## 7. DataStorage 擴充（`src/storage/data_storage.py`）

### 7.1 新增方法

```python
def save_news(self, run_result: "NewsRunResult") -> None:
    """
    將本次執行結果追加寫入當日 JSON 檔。
    流程：
    1. 讀取 data/news/{yyyymmdd}.json（不存在則建立空 NewsDailyFile）
    2. 追加 run_result 至 runs 列表
    3. 原子性寫入（tempfile + os.replace）
    4. 同步更新 data/news/latest.json
    """

def load_news(self, date_str: str) -> Optional["NewsDailyFile"]:
    """讀取指定日期的新聞檔案，返回 NewsDailyFile 或 None。"""

def load_latest_news(self) -> Optional["NewsRunResult"]:
    """讀取 data/news/latest.json，返回最新一次執行結果。"""
```

---

## 8. AppConfig 擴充（`src/config.py`）

```python
@dataclass
class AppConfig:
    # ... 現有欄位 ...

    # Gemini API
    gemini_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "")
    )
    news_summarizer_backend: str = field(
        default_factory=lambda: os.getenv("NEWS_SUMMARIZER_BACKEND", "gemini")
    )

    # 新聞排程設定
    news_start_hour: int = 8     # 排程開始（Asia/Taipei）
    news_end_hour: int = 15      # 排程結束（Asia/Taipei，最後一次在 15:00）
    news_interval_minutes: int = 60

    # 新聞抓取設定
    news_max_articles_per_category: int = 20
    news_request_timeout: int = 15       # 全文抓取逾時（秒）
    news_request_interval: float = 2.0  # 同網域請求間隔（秒）
    news_max_run_minutes: int = 30       # 單次執行時間上限（分鐘）
```

**`config.env.example` 新增**：

```bash
# Gemini API（新聞摘要）
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
NEWS_SUMMARIZER_BACKEND=gemini
```

---

## 9. 新例外類別（`src/exceptions.py` 擴充）

```python
class NewsFetchError(AutoFetchStockError):
    """
    新聞來源抓取失敗。
    適用：RSS 解析失敗、全文 HTTP 錯誤（非 fallback 情境）。
    """
    def __init__(self, message="新聞來源抓取失敗", source_url=None, reason=None):
        self.source_url = source_url
        self.reason = reason
        detail = f" (url: {source_url})" if source_url else ""
        super().__init__(f"{message}{detail}")


class SummarizationError(AutoFetchStockError):
    """
    新聞摘要 API 呼叫失敗。
    適用：Gemini API 逾時、回應格式錯誤、配額超限。
    """
    def __init__(self, message="新聞摘要失敗", article_title=None, reason=None):
        self.article_title = article_title
        self.reason = reason
        super().__init__(f"{message}: {reason or ''}")
```

---

## 10. UI 設計

### 10.1 路由架構

```python
# src/app/layout.py 擴充
# 使用 dcc.Location 支援多路由

def create_layout() -> html.Div:
    return html.Div(children=[
        dcc.Location(id="url", refresh=False),
        html.Div(id="page-content"),  # 由 callback 根據 pathname 渲染
        _create_top_nav(),            # 新增頂部導航
    ])

# 頂部導航（新增）
def _create_top_nav() -> html.Div:
    return html.Div(
        id="top-nav",
        children=[
            dcc.Link("股票", href="/", className="nav-link"),
            dcc.Link("新聞", href="/news", className="nav-link"),
        ]
    )
```

### 10.2 主畫面新聞頁籤（`/`）

現有 `_create_tabs_section()` 新增第三個 Tab：

```python
dcc.Tab(
    label="新聞",
    value="news",
    className="tab",
    selected_className="tab-selected",
    children=_create_news_tab_content(),
)
```

```python
def _create_news_tab_content() -> html.Div:
    return html.Div(
        id="news-tab-content",
        className="tab-content",
        children=[
            dcc.Tabs(
                id="news-category-tabs",
                value="international",
                children=[
                    dcc.Tab(label="國際",    value="international"),
                    dcc.Tab(label="財經",    value="financial"),
                    dcc.Tab(label="科技",    value="tech"),
                    dcc.Tab(label="台股個股", value="stock_tw"),
                    dcc.Tab(label="美股個股", value="stock_us"),
                ]
            ),
            html.Div(id="news-articles-list"),  # callback 渲染文章列表
        ]
    )
```

### 10.3 新聞頁面（`/news`）

```python
def create_news_page_layout() -> html.Div:
    return html.Div(
        id="news-page",
        children=[
            html.Div(
                className="news-page-header",
                children=[
                    html.H2("新聞總覽"),
                    html.Span(id="news-last-updated", children=""),
                    html.Button("重新整理", id="news-refresh-button"),
                ]
            ),
            dcc.Tabs(
                id="news-page-tabs",
                value="international",
                children=[
                    dcc.Tab(label="國際",    value="international"),
                    dcc.Tab(label="財經",    value="financial"),
                    dcc.Tab(label="科技",    value="tech"),
                    dcc.Tab(label="台股個股", value="stock_tw"),
                    dcc.Tab(label="美股個股", value="stock_us"),
                ]
            ),
            html.Div(id="news-page-articles"),
        ]
    )
```

### 10.4 底部跑馬燈

```python
def _create_news_ticker() -> html.Div:
    return html.Div(
        id="news-ticker",
        style={"display": "none"},   # 無新聞時隱藏
        children=[
            html.Span("📰", className="ticker-icon"),
            html.Div(id="news-ticker-text", className="ticker-text"),
            dcc.Interval(
                id="news-ticker-interval",
                interval=5 * 1000,  # 5 秒切換
                n_intervals=0,
            ),
        ]
    )
```

### 10.5 新增 Dash 元件 ID

| 元件 ID | 用途 |
|---------|------|
| `url` | dcc.Location 路由 |
| `page-content` | 路由對應頁面容器 |
| `top-nav` | 頂部導航列 |
| `news-category-tabs` | 主畫面新聞分類子頁籤 |
| `news-articles-list` | 主畫面新聞文章列表容器 |
| `news-page-tabs` | /news 頁面分類頁籤 |
| `news-page-articles` | /news 頁面文章列表容器 |
| `news-last-updated` | /news 頁面最後更新時間 |
| `news-refresh-button` | /news 頁面手動重新整理按鈕 |
| `news-ticker` | 底部跑馬燈容器 |
| `news-ticker-text` | 跑馬燈文字 |
| `news-ticker-interval` | 跑馬燈切換計時器（5 秒） |
| `news-data-store` | dcc.Store，儲存 latest.json 內容 |
| `news-update-interval` | 定期重新整理新聞資料（60 秒） |

### 10.6 Callback 設計（新增 NewsCallbackManager）

```python
class NewsCallbackManager:

    def _register_routing_callback(self):
        """根據 url.pathname 渲染對應頁面（/ 或 /news）。"""
        # Input:  url.pathname
        # Output: page-content.children

    def _register_news_tab_callback(self):
        """主畫面新聞頁籤：依當前股票 + 選定分類過濾文章。"""
        # Input:  news-category-tabs.value, app-state-store.data
        # Output: news-articles-list.children

    def _register_news_page_callback(self):
        """/news 頁面：顯示全部文章（不過濾股票）。"""
        # Input:  news-page-tabs.value, news-refresh-button.n_clicks
        # Output: news-page-articles.children, news-last-updated.children

    def _register_ticker_callback(self):
        """跑馬燈：依當前股票從各分類各取最新一則相關標題輪播。"""
        # Input:  news-ticker-interval.n_intervals, app-state-store.data
        # Output: news-ticker-text.children, news-ticker.style

    def _register_news_data_store_callback(self):
        """每 60 秒從 latest.json 更新 news-data-store。"""
        # Input:  news-update-interval.n_intervals
        # Output: news-data-store.data
```

---

## 11. 依賴套件（新增）

| 套件 | 版本 | 用途 |
|------|------|------|
| `google-generativeai` | >=0.8 | Gemini API SDK |
| `feedparser` | >=6.0 | RSS Feed 解析 |
| `beautifulsoup4` | >=4.12 | HTML 全文解析 |
| `lxml` | >=4.9 | BeautifulSoup HTML 解析器（速度快） |

更新 `requirements.txt` 新增以上 4 個套件。

---

## 12. 測試策略

### 12.1 Unit Tests

```
tests/test_news/
├── test_news_models.py      # dataclass to_dict/from_dict 序列化驗證
├── test_news_fetcher.py     # mock HTTP + mock feedparser
├── test_news_summarizer.py  # mock Gemini API 回應
└── test_news_processor.py   # mock fetcher + summarizer，驗證流程
```

### 12.2 Mock 策略

| 對象 | Mock 方式 |
|------|----------|
| Gemini API | `unittest.mock.patch("google.generativeai.GenerativeModel.generate_content")` |
| RSS Fetch | `unittest.mock.patch("feedparser.parse")` |
| 全文 HTTP | `unittest.mock.patch("requests.get")` |
| DataStorage | `tmp_path` fixture |
| APScheduler | `unittest.mock.MagicMock()` |

### 12.3 覆蓋率目標

| 模組 | 目標覆蓋率 |
|------|-----------|
| `news_models.py` | 95% |
| `news_fetcher.py` | 85% |
| `news_summarizer.py` | 85% |
| `news_processor.py` | 90% |

---

## 13. 品質門檻狀態

**設計 -> 任務分解 品質門檻**：
- ✓ 所有需求（REQ-200~REQ-322）均有對應設計元素
- ✓ 所有模組介面均已定義（類別名稱、方法簽名、回傳型別）
- ✓ 資料模型完整（所有欄位、to_dict/from_dict、JSON 範例）
- ✓ 整合點明確（AppController、Scheduler、DataStorage、AppConfig）
- ✓ 新增套件已列出（4 個），版本需求已指定
- ✓ UI 元件 ID 遵循 kebab-case 慣例
- ✓ Prompt 設計已具體化（可直接實作）
- ✓ 測試策略已定義（mock 方式、目錄結構、覆蓋率目標）

**可進入任務分解（Task Breakdown）階段**：是
