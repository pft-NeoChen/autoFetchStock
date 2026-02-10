# 技術設計文件 (Technical Design Document)

## 執行摘要

autoFetchStock 是一套以 Python 開發的台灣股票即時資料抓取與視覺化系統。系統採用模組化分層架構，分為四大核心模組：資料抓取層 (Fetcher)、資料儲存層 (Storage)、資料處理層 (Processor)、圖表渲染層 (Renderer)。前端介面採用 Dash + Plotly 框架建構 Web 應用，透過 APScheduler 實現定時排程抓取，並以本地 JSON 檔案作為持久化儲存方案。

系統遵循台灣股市慣例（紅漲綠跌），提供分時走勢圖與 K 線圖雙頁籤介面，支援 8 種時間週期切換、4 條移動平均線、3 條成交量均線，以及即時資料自動更新機制。

---

## 1. 架構概覽

### 1.1 系統架構圖

```
+------------------------------------------------------------------+
|                         Web Browser (使用者端)                     |
|  +------------------------------------------------------------+  |
|  |                  Dash Web Application                       |  |
|  |  +------------------+  +------------------+                 |  |
|  |  | 股票搜尋輸入框    |  | 股票資訊顯示區   |                 |  |
|  |  +------------------+  +------------------+                 |  |
|  |  +--------------------------------------------------+      |  |
|  |  |              頁籤切換區域 (Tabs)                   |      |  |
|  |  |  +--------------------+ +---------------------+  |      |  |
|  |  |  | Tab 1: 分時資料     | | Tab 2: K 線圖       |  |      |  |
|  |  |  | - 分時走勢折線圖   | | - K 線蠟燭圖        |  |      |  |
|  |  |  | - 買賣量視覺化     | | - 移動平均線        |  |      |  |
|  |  |  |                    | | - 成交量柱狀圖      |  |      |  |
|  |  |  |                    | | - 成交量均線        |  |      |  |
|  |  |  |                    | | - 時間週期選擇器    |  |      |  |
|  |  |  +--------------------+ +---------------------+  |      |  |
|  |  +--------------------------------------------------+      |  |
|  +------------------------------------------------------------+  |
+------------------------------------------------------------------+
        |  Dash Callbacks (事件驅動)           ^  圖表更新
        v                                      |
+------------------------------------------------------------------+
|                     Python Backend (伺服器端)                      |
|                                                                    |
|  +------------------+    +------------------+    +---------------+ |
|  |  AppController   |--->|  DataProcessor   |--->|  ChartRenderer| |
|  |  (應用控制器)     |    |  (資料處理器)     |    |  (圖表渲染器) | |
|  +------------------+    +------------------+    +---------------+ |
|        |                        ^                                  |
|        v                        |                                  |
|  +------------------+    +------------------+                      |
|  |  DataFetcher     |--->|  DataStorage     |                      |
|  |  (資料抓取器)     |    |  (資料儲存器)     |                      |
|  +------------------+    +------------------+                      |
|        |                        |                                  |
|  +------------------+           v                                  |
|  |  Scheduler       |    +------------------+                      |
|  |  (排程管理器)     |    |  JSON 檔案系統    |                      |
|  +------------------+    +------------------+                      |
+------------------------------------------------------------------+
        |
        v
+------------------------------------------------------------------+
|                   TWSE API (台灣證券交易所)                        |
|  - 個股即時成交資訊                                                |
|  - 個股歷史日成交資訊                                              |
|  - 大盤統計資訊                                                    |
+------------------------------------------------------------------+
```

### 1.2 技術堆疊

| 層級 | 技術選型 | 版本需求 | 用途說明 |
|------|---------|---------|---------|
| 程式語言 | Python | >= 3.10 | 主要開發語言 (REQ-001) |
| Web 框架 | Dash | >= 2.14 | Web 應用框架，提供 GUI 介面 |
| 圖表引擎 | Plotly | >= 5.18 | 互動式圖表渲染（K 線圖、折線圖） |
| HTTP 用戶端 | requests | >= 2.31 | TWSE API 請求 |
| 排程引擎 | APScheduler | >= 3.10 | 定時排程資料抓取 |
| 資料處理 | pandas | >= 2.1 | 股票資料整理、均線計算 |
| 數值運算 | numpy | >= 1.26 | 數值計算輔助 |
| 日誌管理 | logging (stdlib) | - | 系統日誌記錄 (REQ-088) |
| 測試框架 | pytest | >= 7.4 | 單元測試與整合測試 |
| 測試覆蓋 | pytest-cov | >= 4.1 | 測試覆蓋率統計 |

### 1.3 架構決策紀錄

| 編號 | 決策 | 理由 |
|------|------|------|
| AD-01 | 選用 Dash + Plotly 而非 Streamlit | Dash 提供更精細的 callback 控制、支援原生 Plotly 圖表（包含 Candlestick）、頁籤元件完善、且支援 Interval 元件實現即時更新，更適合複雜的金融圖表需求 |
| AD-02 | 選用 APScheduler 而非 Celery | 本系統為單機應用，不需要分散式任務佇列，APScheduler 輕量且支援 cron 與 interval 排程，足以滿足需求 |
| AD-03 | 選用本地 JSON 儲存而非資料庫 | 依照需求規格 (REQ-003)，使用本地 JSON 檔案儲存，降低部署複雜度 |
| AD-04 | 選用 pandas 進行資料處理 | pandas 提供完善的時間序列處理、移動平均線計算、資料重取樣（用於週 K、月 K 轉換）等金融資料分析功能 |
| AD-05 | 選用 requests 而非 aiohttp | 系統為單一使用者應用，同步 HTTP 請求已足夠，且 requests 更為穩定成熟 |

---

## 2. 元件設計

### 2.1 元件：AppController（應用控制器）

**目的**：系統入口點與 Dash 應用的核心控制器，負責初始化所有元件、註冊 Dash callback、協調各模組之間的互動。

**職責**：
- 初始化 Dash 應用實例與版面配置 (Layout)
- 註冊所有 Dash callback（使用者輸入、頁籤切換、圖表更新、週期選擇）
- 管理各模組的生命週期（啟動、停止排程器等）
- 統一錯誤處理與日誌記錄入口
- 管理應用狀態（當前選取的股票、當前頁籤、當前 K 線週期）

**介面**：
- 輸入：使用者操作事件（Dash callback 觸發）
- 輸出：更新的介面元件（圖表、文字、樣式）

**依賴**：
- DataFetcher（資料抓取）
- DataProcessor（資料處理）
- ChartRenderer（圖表渲染）
- DataStorage（資料儲存）
- Scheduler（排程管理）

**關鍵方法**：

```python
class AppController:
    def __init__(self, config: AppConfig) -> None:
        """初始化所有子元件與 Dash 應用"""

    def create_layout(self) -> html.Div:
        """建構 Dash 應用版面配置"""

    def register_callbacks(self) -> None:
        """註冊所有 Dash callback"""

    def run(self, host: str = "127.0.0.1", port: int = 8050, debug: bool = False) -> None:
        """啟動應用伺服器"""

    # === Dash Callbacks ===
    def _on_stock_search(self, search_value: str) -> tuple:
        """使用者輸入股票代號/名稱時觸發"""

    def _on_tab_switch(self, active_tab: str) -> html.Div:
        """頁籤切換時觸發"""

    def _on_period_change(self, period: str) -> go.Figure:
        """K 線圖時間週期變更時觸發"""

    def _on_interval_update(self, n_intervals: int) -> tuple:
        """定時更新觸發（分時資料即時更新）"""
```

---

### 2.2 元件：DataFetcher（資料抓取器）

**目的**：封裝所有與 TWSE API 的互動邏輯，負責發送 HTTP 請求、解析回應、處理 API 錯誤。

**職責**：
- 發送 HTTP GET 請求至 TWSE API 端點
- 解析 TWSE API 回傳的 JSON 資料
- 處理 API 連線逾時、非預期格式、空資料等異常情況
- 追蹤連續失敗次數，達 3 次時觸發暫停機制
- 支援查詢個股即時成交資訊與歷史日成交資訊
- 支援股票代號/名稱查詢與模糊匹配
- 遵守 TWSE API 請求頻率限制（每次請求間隔至少 3 秒）

**介面**：
- 輸入：股票代號 (str)、查詢日期範圍 (date)、查詢類型 (enum)
- 輸出：StockData (dataclass) 或 List[StockData]，失敗時拋出自定義例外

**依賴**：
- requests（HTTP 用戶端）
- logging（日誌記錄）

**TWSE API 端點設計**：

| 端點 | URL 模式 | 用途 |
|------|---------|------|
| 即時成交資訊 | `https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_id}.tw` | 取得個股即時報價 |
| 個股日成交資訊 | `https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={yyyymmdd}&stockNo={stock_id}` | 取得個股歷史日成交資訊 |
| 當日成交資訊 | `https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=json` | 取得全部上市股票當日資訊 |
| 股票清單 | `https://isin.twse.com.tw/isin/C_public.jsp?strMode=2` | 取得上市股票清單（用於名稱查詢） |

**關鍵方法**：

```python
class DataFetcher:
    # API 請求間隔（秒），遵守 TWSE 限制
    REQUEST_INTERVAL: float = 3.0
    # 連線逾時（秒）
    CONNECTION_TIMEOUT: int = 10
    # 連續失敗閾值
    MAX_CONSECUTIVE_FAILURES: int = 3

    def __init__(self) -> None:
        """初始化 HTTP session 與失敗計數器"""

    def fetch_realtime_quote(self, stock_id: str) -> RealtimeQuote:
        """
        取得個股即時報價（最新成交價、漲跌、成交量）
        Raises: ConnectionTimeoutError, InvalidDataError, StockNotFoundError
        """

    def fetch_daily_history(self, stock_id: str, year: int, month: int) -> List[DailyOHLC]:
        """
        取得個股指定月份的歷史日成交資訊
        Raises: ConnectionTimeoutError, InvalidDataError
        """

    def fetch_intraday_ticks(self, stock_id: str) -> List[IntradayTick]:
        """
        取得個股當日分時明細（用於分時走勢圖）
        Raises: ConnectionTimeoutError, InvalidDataError
        """

    def search_stock(self, keyword: str) -> List[StockInfo]:
        """
        依股票代號或名稱搜尋匹配的股票清單
        Raises: ConnectionTimeoutError
        """

    def _make_request(self, url: str, params: dict = None) -> dict:
        """
        底層 HTTP 請求方法，包含重試、頻率限制、逾時處理
        """

    def _check_consecutive_failures(self) -> None:
        """檢查連續失敗次數，達閾值時拋出 ServiceUnavailableError"""

    def reset_failure_count(self) -> None:
        """重置連續失敗計數器"""
```

**錯誤處理流程**：

```
HTTP 請求
    |
    +---> 連線逾時 (>10秒) ---> 記錄日誌 ---> 30秒後自動重試一次 (REQ-100)
    |                                              |
    |                                              +---> 重試成功 ---> 返回資料
    |                                              +---> 重試失敗 ---> 累加失敗次數 ---> 拋出例外
    |
    +---> 回應成功 ---> 驗證資料格式
                            |
                            +---> 格式正確 ---> 重置失敗計數 ---> 返回解析後資料
                            +---> 格式異常/空資料 ---> 記錄日誌 ---> 拋出 InvalidDataError (REQ-101)
                            +---> 查無股票 ---> 拋出 StockNotFoundError (REQ-102)

連續失敗次數 >= 3 ---> 拋出 ServiceUnavailableError (REQ-104)
```

---

### 2.3 元件：DataStorage（資料儲存器）

**目的**：管理本地 JSON 檔案的讀寫操作，確保資料持久化的可靠性與完整性。

**職責**：
- 以股票代號為單位建立獨立 JSON 檔案
- 以追加模式寫入新資料，不覆蓋歷史資料
- 實作原子性寫入（先寫暫存檔再 rename）
- 系統啟動時自動載入既有歷史資料
- 處理檔案損毀情況（備份損毀檔案、建立新檔）
- 監測磁碟空間使用狀況
- 記錄每次寫入的時間戳記

**介面**：
- 輸入：StockData 物件或 List[StockData]、股票代號
- 輸出：讀取時返回 List[StockData]，寫入時返回 bool（成功/失敗）

**依賴**：
- json (stdlib)
- os / pathlib (stdlib)
- shutil (stdlib)
- logging (stdlib)
- tempfile (stdlib)

**檔案結構設計**：

```
data/
├── stocks/
│   ├── 2330.json          # 台積電歷史資料
│   ├── 2317.json          # 鴻海歷史資料
│   └── ...
├── intraday/
│   ├── 2330_20260202.json # 台積電當日分時資料
│   └── ...
├── cache/
│   └── stock_list.json    # 上市股票清單快取
└── backup/
    └── 2330_20260202_corrupted.json  # 損毀檔案備份
```

**JSON 檔案格式設計**：

股票歷史日成交資料 (`stocks/{stock_id}.json`)：

```json
{
  "stock_id": "2330",
  "stock_name": "台積電",
  "last_updated": "2026-02-02T13:30:00+08:00",
  "daily_data": [
    {
      "date": "2026-02-02",
      "open": 985.0,
      "high": 990.0,
      "low": 980.0,
      "close": 988.0,
      "volume": 25630,
      "turnover": 25322140000,
      "timestamp": "2026-02-02T13:30:00+08:00"
    }
  ]
}
```

分時資料 (`intraday/{stock_id}_{yyyymmdd}.json`)：

```json
{
  "stock_id": "2330",
  "stock_name": "台積電",
  "date": "2026-02-02",
  "previous_close": 980.0,
  "ticks": [
    {
      "time": "09:00:05",
      "price": 985.0,
      "volume": 150,
      "buy_volume": 100,
      "sell_volume": 50,
      "accumulated_volume": 150,
      "timestamp": "2026-02-02T09:00:05+08:00"
    }
  ]
}
```

**關鍵方法**：

```python
class DataStorage:
    DEFAULT_DATA_DIR: str = "data"
    MIN_DISK_SPACE_MB: int = 100

    def __init__(self, data_dir: str = DEFAULT_DATA_DIR) -> None:
        """初始化儲存目錄結構"""

    def save_daily_data(self, stock_id: str, stock_name: str, records: List[DailyOHLC]) -> bool:
        """
        追加寫入日成交資料（原子性寫入）
        Raises: DiskSpaceError
        """

    def load_daily_data(self, stock_id: str) -> Optional[StockDailyFile]:
        """
        載入指定股票的歷史日成交資料
        Raises: DataCorruptedError（損毀時自動備份並建新檔）
        """

    def save_intraday_data(self, stock_id: str, stock_name: str, date: str, previous_close: float, ticks: List[IntradayTick]) -> bool:
        """
        追加寫入分時資料（原子性寫入）
        Raises: DiskSpaceError
        """

    def load_intraday_data(self, stock_id: str, date: str) -> Optional[StockIntradayFile]:
        """載入指定股票指定日期的分時資料"""

    def _atomic_write(self, file_path: str, data: dict) -> None:
        """原子性寫入：寫入暫存檔後 rename"""

    def _check_disk_space(self) -> None:
        """檢查磁碟剩餘空間，低於 100MB 時拋出 DiskSpaceError"""

    def _backup_corrupted_file(self, file_path: str) -> str:
        """備份損毀檔案至 backup 目錄，返回備份路徑"""

    def _validate_json_integrity(self, data: dict) -> bool:
        """驗證 JSON 資料結構完整性"""
```

**原子性寫入流程**：

```
1. 讀取現有 JSON 檔案內容
2. 將新資料追加至記錄列表
3. 序列化為 JSON 字串
4. 寫入暫存檔 (同一目錄下的 .tmp 檔)
5. 使用 os.replace() 將暫存檔 rename 為目標檔案（原子操作）
6. 記錄時間戳記至日誌
```

---

### 2.4 元件：DataProcessor（資料處理器）

**目的**：負責所有資料轉換、計算與聚合邏輯，將原始資料處理為圖表所需的格式。

**職責**：
- 計算移動平均線（MA5、MA10、MA20、MA60）
- 計算成交量均線（均量 5、均量 20、均量 60）
- 將日 K 資料重取樣為週 K、月 K
- 處理分鐘 K 資料（1 分 K、5 分 K、15 分 K、30 分 K、60 分 K）
- 計算漲跌幅、漲跌金額
- 計算可視範圍內最高價/最低價
- 分離買入量與賣出量（分時資料）
- 驗證 OHLC 資料的有效性

**介面**：
- 輸入：原始 StockData 列表、時間週期參數
- 輸出：處理後的 pandas DataFrame（含計算欄位）

**依賴**：
- pandas
- numpy

**關鍵方法**：

```python
class DataProcessor:
    # 移動平均線週期
    MA_PERIODS: List[int] = [5, 10, 20, 60]
    # 成交量均線週期
    VOLUME_MA_PERIODS: List[int] = [5, 20, 60]

    def calculate_moving_averages(self, df: pd.DataFrame, periods: List[int] = None) -> pd.DataFrame:
        """
        計算收盤價移動平均線 (MA5/MA10/MA20/MA60)
        在 DataFrame 中新增 ma5, ma10, ma20, ma60 欄位
        """

    def calculate_volume_moving_averages(self, df: pd.DataFrame, periods: List[int] = None) -> pd.DataFrame:
        """
        計算成交量移動平均線 (均量5/均量20/均量60)
        在 DataFrame 中新增 vol_ma5, vol_ma20, vol_ma60 欄位
        """

    def resample_to_period(self, df: pd.DataFrame, period: str) -> pd.DataFrame:
        """
        將日 K 資料重取樣為指定週期
        period: 'W' (週K), 'M' (月K)
        使用 pandas resample，open 取 first, high 取 max, low 取 min, close 取 last, volume 取 sum
        """

    def resample_intraday_to_minutes(self, ticks_df: pd.DataFrame, minutes: int) -> pd.DataFrame:
        """
        將分時 tick 資料聚合為分鐘 K 線
        minutes: 1, 5, 15, 30, 60
        """

    def calculate_price_change(self, current_price: float, previous_close: float) -> PriceChange:
        """
        計算漲跌金額與百分比
        返回 PriceChange(amount, percentage, direction)
        direction: 'up' | 'down' | 'flat'
        """

    def find_visible_range_extremes(self, df: pd.DataFrame, start_idx: int, end_idx: int) -> dict:
        """
        找出可視範圍內的最高價與最低價及其對應日期
        返回 {'highest': {'price': float, 'date': str}, 'lowest': {'price': float, 'date': str}}
        """

    def separate_buy_sell_volume(self, ticks_df: pd.DataFrame) -> pd.DataFrame:
        """
        分離買入量（正值，向上）與賣出量（負值，向下）
        以零軸為基準線
        """

    def validate_ohlc_data(self, record: dict) -> bool:
        """
        驗證 OHLC 資料完整性
        - 所有欄位為有效數值
        - high >= max(open, close)
        - low <= min(open, close)
        - volume >= 0
        """

    def prepare_kline_data(self, stock_id: str, period: str, storage: DataStorage) -> pd.DataFrame:
        """
        完整的 K 線資料準備流程：
        1. 從 storage 載入原始資料
        2. 轉換為 DataFrame
        3. 根據 period 重取樣
        4. 計算所有均線
        5. 返回完整 DataFrame
        """
```

---

### 2.5 元件：ChartRenderer（圖表渲染器）

**目的**：使用 Plotly 產生所有圖表的 Figure 物件，供 Dash 前端顯示。

**職責**：
- 渲染 K 線蠟燭圖（紅漲綠跌）
- 渲染移動平均線（MA5/MA10/MA20/MA60，各用不同顏色）
- 渲染成交量柱狀圖（顏色與 K 線一致）
- 渲染成交量均線
- 渲染分時走勢折線圖（含前日收盤價基準線）
- 渲染買賣量視覺化圖（零軸分離）
- 標註可視範圍內最高價/最低價
- 顯示 OHLC 資訊（十字游標 hover）
- 支援滑鼠滾輪縮放與拖曳平移

**介面**：
- 輸入：處理後的 pandas DataFrame、圖表配置參數
- 輸出：plotly.graph_objects.Figure

**依賴**：
- plotly.graph_objects
- plotly.subplots (make_subplots)

**顏色配置**：

```python
class ChartColors:
    """圖表顏色配置（台灣慣例：紅漲綠跌）"""
    UP_COLOR: str = "#EF5350"        # 紅色（上漲）
    DOWN_COLOR: str = "#26A69A"      # 綠色（下跌）
    FLAT_COLOR: str = "#FFFFFF"      # 白色（平盤）
    MA5_COLOR: str = "#FF6F00"       # 橘色
    MA10_COLOR: str = "#2196F3"      # 藍色
    MA20_COLOR: str = "#E91E63"      # 粉紅色
    MA60_COLOR: str = "#9C27B0"      # 紫色
    VOL_MA5_COLOR: str = "#FF6F00"   # 橘色
    VOL_MA20_COLOR: str = "#2196F3"  # 藍色
    VOL_MA60_COLOR: str = "#9C27B0"  # 紫色
    BASELINE_COLOR: str = "#FFEB3B"  # 黃色（前日收盤價基準線）
    BG_COLOR: str = "#1E1E1E"        # 深色背景
    GRID_COLOR: str = "#333333"      # 網格線色
    TEXT_COLOR: str = "#FFFFFF"      # 文字色
```

**關鍵方法**：

```python
class ChartRenderer:
    def __init__(self, colors: ChartColors = None) -> None:
        """初始化顏色配置"""

    def render_kline_chart(self, df: pd.DataFrame, stock_name: str, period_label: str) -> go.Figure:
        """
        渲染完整 K 線圖（含成交量子圖）
        使用 make_subplots 建立上下兩個子圖：
        - 上方：K 線蠟燭圖 + 移動平均線 + 最高最低價標註
        - 下方：成交量柱狀圖 + 成交量均線
        圖表配置：
        - rangeslider 隱藏（使用自訂縮放）
        - xaxis 設定 rangeslider=False
        - 支援滑鼠滾輪縮放 (scrollZoom=True)
        - 支援拖曳平移
        """

    def render_candlestick(self, fig: go.Figure, df: pd.DataFrame, row: int, col: int) -> None:
        """在指定子圖位置渲染 K 線蠟燭"""

    def render_moving_averages(self, fig: go.Figure, df: pd.DataFrame, row: int, col: int) -> None:
        """在指定子圖位置渲染所有移動平均線"""

    def render_volume_bars(self, fig: go.Figure, df: pd.DataFrame, row: int, col: int) -> None:
        """渲染成交量柱狀圖，顏色與對應 K 線一致"""

    def render_volume_moving_averages(self, fig: go.Figure, df: pd.DataFrame, row: int, col: int) -> None:
        """渲染成交量均線"""

    def render_price_extremes(self, fig: go.Figure, df: pd.DataFrame, row: int, col: int) -> None:
        """標註可視範圍內最高價與最低價"""

    def render_intraday_chart(self, ticks_df: pd.DataFrame, stock_name: str, previous_close: float) -> go.Figure:
        """
        渲染分時走勢圖（含買賣量子圖）
        使用 make_subplots 建立上下兩個子圖：
        - 上方：分時走勢折線圖 + 前日收盤價基準線
        - 下方：買賣量視覺化（零軸分離，上方買入、下方賣出）
        """

    def render_intraday_price_line(self, fig: go.Figure, ticks_df: pd.DataFrame, previous_close: float, row: int, col: int) -> None:
        """渲染分時走勢折線與前日收盤價基準線"""

    def render_buy_sell_volume(self, fig: go.Figure, ticks_df: pd.DataFrame, row: int, col: int) -> None:
        """渲染買賣量視覺化（零軸分離）"""

    def _apply_chart_layout(self, fig: go.Figure, title: str) -> None:
        """統一套用圖表版面設定（背景色、網格、字型等）"""
```

**K 線圖子圖配置**：

```
+------------------------------------------+
|  K 線蠟燭圖 (row=1)                       |
|  - Candlestick trace (紅漲綠跌)           |
|  - MA5 線 (橘色)                          |
|  - MA10 線 (藍色)                         |
|  - MA20 線 (粉紅色)                       |
|  - MA60 線 (紫色)                         |
|  - 最高價/最低價標註                       |
|  佔比：70%                                |
+------------------------------------------+
|  成交量圖 (row=2)                          |
|  - 成交量柱狀圖 (紅漲綠跌)                 |
|  - 均量5 (橘色)                            |
|  - 均量20 (藍色)                           |
|  - 均量60 (紫色)                           |
|  佔比：30%                                |
+------------------------------------------+
```

---

### 2.6 元件：Scheduler（排程管理器）

**目的**：管理定時資料抓取任務，根據台灣股市交易時段自動啟停排程。

**職責**：
- 管理 APScheduler 排程器實例
- 在交易時段（09:00-13:30）啟動定時抓取
- 在非交易時段停止自動抓取
- 處理排程任務執行中的例外錯誤
- 支援動態調整抓取間隔
- 提供手動觸發抓取的介面

**介面**：
- 輸入：排程配置（間隔時間、股票代號）
- 輸出：排程狀態（執行中/暫停/停止）

**依賴**：
- APScheduler
- datetime (stdlib)
- logging (stdlib)

**關鍵方法**：

```python
class Scheduler:
    # 交易時段
    MARKET_OPEN: time = time(9, 0)
    MARKET_CLOSE: time = time(13, 30)
    # 預設抓取間隔（秒）
    DEFAULT_FETCH_INTERVAL: int = 5
    # 時區
    TIMEZONE: str = "Asia/Taipei"

    def __init__(self, fetcher: DataFetcher, storage: DataStorage) -> None:
        """初始化 APScheduler 與依賴元件"""

    def start(self) -> None:
        """啟動排程器"""

    def stop(self) -> None:
        """停止排程器"""

    def add_stock_job(self, stock_id: str) -> None:
        """為指定股票新增定時抓取任務"""

    def remove_stock_job(self, stock_id: str) -> None:
        """移除指定股票的抓取任務"""

    def is_market_open(self) -> bool:
        """判斷當前是否在台灣股市交易時段"""

    def _fetch_job(self, stock_id: str) -> None:
        """
        排程任務的執行函式
        包含完整的 try-except 處理，確保例外不會中斷排程器
        """

    def get_status(self) -> SchedulerStatus:
        """返回排程器當前狀態"""

    def pause_auto_fetch(self) -> None:
        """暫停自動抓取（API 連續失敗時呼叫）"""

    def resume_auto_fetch(self) -> None:
        """恢復自動抓取"""
```

**排程邏輯流程**：

```
系統啟動
    |
    v
排程器初始化
    |
    v
檢查當前時間 ---> 交易時段 (09:00-13:30)
    |                    |
    |                    v
    |              啟動定時抓取任務
    |              (interval = TWSE 允許最短間隔)
    |                    |
    |                    v
    |              每次抓取 ---> 成功 ---> 儲存資料 ---> 通知更新
    |                    |
    |                    +---> 失敗 ---> 記錄日誌 ---> 檢查連續失敗次數
    |                                                       |
    |                                                  >= 3次 ---> 暫停自動抓取
    |
    +---> 非交易時段
              |
              v
         停止自動抓取，等待下一個交易日
```

---

### 2.7 元件：DashLayout（Dash 版面配置）

**目的**：定義 Dash 應用的完整 HTML 版面結構，分離 UI 定義與業務邏輯。

**職責**：
- 定義頁面整體版面結構
- 建構股票搜尋輸入框元件
- 建構股票資訊顯示區域
- 建構頁籤切換元件（分時資料 / K 線圖）
- 建構時間週期選擇器
- 設定 dcc.Interval 元件（即時更新用）
- 定義 CSS 樣式

**版面結構**：

```
+----------------------------------------------------------+
|  [autoFetchStock]  台股即時資料抓取與視覺化系統              |
+----------------------------------------------------------+
|                                                            |
|  搜尋股票: [________________] [搜尋]                       |
|                                                            |
|  匹配清單 (若有多筆結果):                                    |
|  +------------------------------------------------------+ |
|  | 2330 台積電  |  2331 精英  |  ...                      | |
|  +------------------------------------------------------+ |
|                                                            |
+----------------------------------------------------------+
|  台積電 (2330)                                             |
|  988.00  +8.00 (+0.82%)  成交量: 25,630 張                 |
|  (紅色/綠色/白色 依漲跌狀態)                                 |
+----------------------------------------------------------+
|  [ 分時資料 ]  [ K 線圖 ]                                   |
+----------------------------------------------------------+
|                                                            |
|  (Tab 1: 分時資料)                                         |
|  +------------------------------------------------------+ |
|  |  分時走勢折線圖                                        | |
|  |  (含前日收盤價基準線)                                   | |
|  +------------------------------------------------------+ |
|  +------------------------------------------------------+ |
|  |  買賣量視覺化                                          | |
|  |  (零軸分離：上方買入 / 下方賣出)                        | |
|  +------------------------------------------------------+ |
|                                                            |
|  --- 或 ---                                                |
|                                                            |
|  (Tab 2: K 線圖)                                           |
|  週期: [日K] [週K] [月K] [1分K] [5分K] [15分K] [30分K] [60分K]|
|  OHLC: 開:985 高:990 低:980 收:988                         |
|  +------------------------------------------------------+ |
|  |  K 線蠟燭圖                                            | |
|  |  (含 MA5/MA10/MA20/MA60 移動平均線)                    | |
|  |  (含最高價/最低價標註)                                   | |
|  +------------------------------------------------------+ |
|  +------------------------------------------------------+ |
|  |  成交量柱狀圖                                          | |
|  |  (含 均量5/均量20/均量60)                               | |
|  +------------------------------------------------------+ |
|                                                            |
+----------------------------------------------------------+
|  dcc.Interval (隱藏元件，控制即時更新頻率)                   |
|  dcc.Store (隱藏元件，儲存應用狀態)                          |
+----------------------------------------------------------+
```

**Dash 元件 ID 命名規範**：

| 元件 | ID | 類型 |
|------|-----|------|
| 搜尋輸入框 | `stock-search-input` | dcc.Input |
| 搜尋按鈕 | `stock-search-button` | html.Button |
| 匹配清單 | `stock-match-list` | html.Div |
| 股票名稱顯示 | `stock-name-display` | html.H2 |
| 股價顯示 | `stock-price-display` | html.Span |
| 漲跌顯示 | `stock-change-display` | html.Span |
| 成交量顯示 | `stock-volume-display` | html.Span |
| 頁籤元件 | `main-tabs` | dcc.Tabs |
| 分時資料頁籤內容 | `tab-intraday-content` | html.Div |
| K 線圖頁籤內容 | `tab-kline-content` | html.Div |
| 分時走勢圖 | `intraday-price-chart` | dcc.Graph |
| 買賣量圖 | `intraday-volume-chart` | dcc.Graph |
| K 線圖 | `kline-chart` | dcc.Graph |
| 時間週期選擇器 | `period-selector` | dcc.RadioItems |
| OHLC 資訊區 | `ohlc-display` | html.Div |
| 即時更新計時器 | `auto-update-interval` | dcc.Interval |
| 應用狀態儲存 | `app-state-store` | dcc.Store |
| 錯誤訊息區 | `error-message-display` | html.Div |
| 系統狀態列 | `system-status-bar` | html.Div |

---

## 3. 資料設計

### 3.1 資料模型

```python
from dataclasses import dataclass, field
from datetime import datetime, date, time
from enum import Enum
from typing import List, Optional

class PriceDirection(Enum):
    """股價漲跌方向"""
    UP = "up"
    DOWN = "down"
    FLAT = "flat"

class KlinePeriod(Enum):
    """K 線時間週期"""
    DAILY = "daily"          # 日 K
    WEEKLY = "weekly"        # 週 K
    MONTHLY = "monthly"      # 月 K
    MIN_1 = "1min"           # 1 分 K
    MIN_5 = "5min"           # 5 分 K
    MIN_15 = "15min"         # 15 分 K
    MIN_30 = "30min"         # 30 分 K
    MIN_60 = "60min"         # 60 分 K

@dataclass
class StockInfo:
    """股票基本資訊"""
    stock_id: str            # 股票代號 (e.g., "2330")
    stock_name: str          # 股票名稱 (e.g., "台積電")
    market: str = "tse"      # 市場 (tse: 上市, otc: 上櫃)

@dataclass
class RealtimeQuote:
    """即時報價資料"""
    stock_id: str
    stock_name: str
    current_price: float     # 最新成交價
    open_price: float        # 開盤價
    high_price: float        # 最高價
    low_price: float         # 最低價
    previous_close: float    # 前日收盤價
    change_amount: float     # 漲跌金額
    change_percent: float    # 漲跌百分比
    direction: PriceDirection # 漲跌方向
    total_volume: int        # 總成交量（張）
    timestamp: datetime      # 資料時間戳記

@dataclass
class DailyOHLC:
    """日成交資料（OHLC）"""
    date: date               # 日期
    open: float              # 開盤價
    high: float              # 最高價
    low: float               # 最低價
    close: float             # 收盤價
    volume: int              # 成交量（張）
    turnover: int            # 成交金額
    timestamp: datetime      # 資料寫入時間戳記

@dataclass
class IntradayTick:
    """分時成交明細"""
    time: time               # 成交時間
    price: float             # 成交價
    volume: int              # 成交量（張）
    buy_volume: int          # 買入量
    sell_volume: int         # 賣出量
    accumulated_volume: int  # 累積成交量
    timestamp: datetime      # 資料時間戳記

@dataclass
class PriceChange:
    """漲跌計算結果"""
    amount: float            # 漲跌金額
    percentage: float        # 漲跌百分比
    direction: PriceDirection # 漲跌方向

@dataclass
class SchedulerStatus:
    """排程器狀態"""
    is_running: bool         # 排程器是否運行中
    is_market_open: bool     # 是否在交易時段
    is_paused: bool          # 是否因錯誤暫停
    active_jobs: List[str]   # 正在排程的股票代號列表
    last_fetch_time: Optional[datetime]  # 上次抓取時間
    consecutive_failures: int # 連續失敗次數

@dataclass
class AppConfig:
    """應用設定"""
    host: str = "127.0.0.1"
    port: int = 8050
    debug: bool = False
    data_dir: str = "data"
    fetch_interval: int = 5  # 抓取間隔（秒）
    log_level: str = "INFO"
    log_file: str = "logs/app.log"
```

### 3.2 資料驗證規則

| 欄位 | 類型 | 驗證規則 |
|------|------|---------|
| stock_id | str | 非空、1-6 位數字或英文字母 |
| date | date | 有效日期，不超過今日 |
| open / high / low / close | float | > 0，且 high >= max(open, close)，low <= min(open, close) |
| volume | int | >= 0 |
| turnover | int | >= 0 |
| change_percent | float | 合理範圍 -10% ~ +10%（台股漲跌幅限制） |
| price | float | > 0 |
| buy_volume / sell_volume | int | >= 0，且 buy_volume + sell_volume == volume |

### 3.3 資料流設計

```
使用者輸入股票代號
        |
        v
DataFetcher.search_stock()
        |
        v
DataFetcher.fetch_realtime_quote() --------+
        |                                   |
        v                                   v
DataFetcher.fetch_daily_history() ---> DataStorage.save_daily_data()
        |                                   |
        v                                   v
DataFetcher.fetch_intraday_ticks() --> DataStorage.save_intraday_data()
        |
        v
DataStorage.load_daily_data() / load_intraday_data()
        |
        v
DataProcessor (計算均線、重取樣、分離買賣量)
        |
        v
ChartRenderer (渲染圖表)
        |
        v
Dash Callback 更新前端 dcc.Graph 元件
```

---

## 4. API 設計

### 4.1 TWSE API 封裝

本系統不對外提供 API，但對 TWSE API 進行封裝。以下為 TWSE API 呼叫規格。

#### 4.1.1 即時成交資訊

```
GET https://mis.twse.com.tw/stock/api/getStockInfo.jsp
Parameters:
  - ex_ch: tse_{stock_id}.tw (上市) / otc_{stock_id}.tw (上櫃)
  - json: 1
  - delay: 0

Response 關鍵欄位：
  - n: 股票名稱
  - z: 最新成交價
  - o: 開盤價
  - h: 最高價
  - l: 最低價
  - y: 昨收價
  - v: 成交量
  - t: 最新成交時間
```

#### 4.1.2 個股日成交資訊

```
GET https://www.twse.com.tw/exchangeReport/STOCK_DAY
Parameters:
  - response: json
  - date: yyyymmdd
  - stockNo: 股票代號

Response 關鍵欄位：
  - stat: 狀態 ("OK" 表示成功)
  - title: 標題（含股票名稱）
  - data: 二維陣列，每列為 [日期, 成交股數, 成交金額, 開盤價, 最高價, 最低價, 收盤價, 漲跌價差, 成交筆數]
```

#### 4.1.3 當日收盤行情

```
GET https://www.twse.com.tw/exchangeReport/MI_INDEX
Parameters:
  - response: json
  - date: yyyymmdd
  - type: ALLBUT0999

Response: 包含所有上市股票當日行情資料
```

### 4.2 內部 Dash Callback 設計

| Callback | Input | Output | 說明 |
|----------|-------|--------|------|
| 股票搜尋 | `stock-search-input.value`, `stock-search-button.n_clicks` | `stock-match-list.children`, `stock-name-display.children`, `stock-price-display.children`, `stock-change-display.children`, `stock-change-display.style`, `stock-volume-display.children` | 使用者輸入時觸發搜尋與資訊更新 |
| 頁籤切換 | `main-tabs.value` | `tab-intraday-content.style`, `tab-kline-content.style` | 切換分時/K線頁籤 |
| K 線週期切換 | `period-selector.value` | `kline-chart.figure`, `ohlc-display.children` | 切換 K 線時間週期 |
| 即時更新 | `auto-update-interval.n_intervals` | `intraday-price-chart.figure`, `intraday-volume-chart.figure`, `stock-price-display.children`, `stock-change-display.children`, `stock-change-display.style`, `stock-volume-display.children` | 定時更新分時資料與即時報價 |
| K 線 Hover | `kline-chart.hoverData` | `ohlc-display.children` | 滑鼠移至 K 線上方時顯示 OHLC |

---

## 5. 安全設計

### 5.1 網路安全

| 項目 | 措施 |
|------|------|
| API 請求 | 使用 HTTPS 連線至 TWSE API |
| 請求頻率 | 遵守 TWSE API 頻率限制，每次請求間隔 >= 3 秒，避免被封鎖 |
| User-Agent | 設定合理的 User-Agent 標頭，避免被辨識為爬蟲 |
| 逾時控制 | 所有 HTTP 請求設定 10 秒逾時 |

### 5.2 資料安全

| 項目 | 措施 |
|------|------|
| 輸入驗證 | 股票代號/名稱輸入進行嚴格驗證，防止注入攻擊 |
| 檔案路徑 | 使用 pathlib 處理檔案路徑，防止路徑穿越攻擊 |
| 原子性寫入 | JSON 檔案使用暫存檔 + rename 模式，防止寫入中斷導致資料損毀 |
| 備份機制 | 損毀檔案自動備份至 backup 目錄 |

### 5.3 應用安全

| 項目 | 措施 |
|------|------|
| 本地存取 | 預設綁定 127.0.0.1，僅限本地存取 |
| Debug 模式 | 正式運作時關閉 Dash debug 模式 |
| 例外處理 | 所有排程任務包裹 try-except，防止未預期例外中斷系統 |

---

## 6. 實作指引

### 6.1 程式碼組織

```
autoFetchStock/
├── src/
│   ├── __init__.py
│   ├── main.py                    # 應用入口點
│   ├── config.py                  # 應用設定與常數定義
│   ├── models.py                  # 資料模型 (dataclass)
│   ├── exceptions.py              # 自定義例外類別
│   ├── fetcher/
│   │   ├── __init__.py
│   │   ├── data_fetcher.py        # DataFetcher 主類別
│   │   └── twse_parser.py         # TWSE API 回應解析器
│   ├── storage/
│   │   ├── __init__.py
│   │   └── data_storage.py        # DataStorage 主類別
│   ├── processor/
│   │   ├── __init__.py
│   │   └── data_processor.py      # DataProcessor 主類別
│   ├── renderer/
│   │   ├── __init__.py
│   │   ├── chart_renderer.py      # ChartRenderer 主類別
│   │   └── chart_colors.py        # 顏色配置
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── scheduler.py           # Scheduler 主類別
│   └── app/
│       ├── __init__.py
│       ├── app_controller.py      # AppController 主類別
│       ├── layout.py              # DashLayout 版面定義
│       ├── callbacks.py           # Dash callback 函式
│       └── assets/
│           └── style.css          # 自訂 CSS 樣式
├── data/
│   ├── stocks/                    # 歷史日成交資料
│   ├── intraday/                  # 分時資料
│   ├── cache/                     # 快取資料
│   └── backup/                    # 損毀檔案備份
├── logs/                          # 日誌檔案
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # pytest 共用 fixture
│   ├── test_fetcher/
│   │   ├── __init__.py
│   │   ├── test_data_fetcher.py
│   │   └── test_twse_parser.py
│   ├── test_storage/
│   │   ├── __init__.py
│   │   └── test_data_storage.py
│   ├── test_processor/
│   │   ├── __init__.py
│   │   └── test_data_processor.py
│   ├── test_renderer/
│   │   ├── __init__.py
│   │   └── test_chart_renderer.py
│   ├── test_scheduler/
│   │   ├── __init__.py
│   │   └── test_scheduler.py
│   └── test_integration/
│       ├── __init__.py
│       └── test_app_flow.py
├── specs/
│   ├── REQUIREMENTS.md
│   └── DESIGN.md
├── requirements.txt
├── pyproject.toml
├── README.md
└── .gitignore
```

### 6.2 自定義例外類別

```python
# src/exceptions.py

class AutoFetchStockError(Exception):
    """基礎例外類別"""
    pass

class ConnectionTimeoutError(AutoFetchStockError):
    """TWSE API 連線逾時 (REQ-100)"""
    pass

class InvalidDataError(AutoFetchStockError):
    """API 回傳資料格式異常 (REQ-101)"""
    pass

class StockNotFoundError(AutoFetchStockError):
    """查無此股票 (REQ-102)"""
    pass

class DataCorruptedError(AutoFetchStockError):
    """本地 JSON 檔案損毀 (REQ-103)"""
    pass

class ServiceUnavailableError(AutoFetchStockError):
    """TWSE API 連續失敗，服務暫時不可用 (REQ-104)"""
    pass

class DiskSpaceError(AutoFetchStockError):
    """磁碟空間不足 (REQ-105)"""
    pass

class SchedulerTaskError(AutoFetchStockError):
    """排程任務執行錯誤 (REQ-106)"""
    pass
```

### 6.3 設計模式

| 模式 | 應用場景 | 說明 |
|------|---------|------|
| 觀察者模式 (Observer) | Dash Callback 機制 | Dash 內建的 callback 機制本質上就是觀察者模式，當 Input 元件狀態改變時自動觸發對應的 callback 函式 |
| 單例模式 (Singleton) | DataFetcher / Scheduler | 確保全域只有一個 HTTP session 與一個排程器實例，避免資源競爭 |
| 策略模式 (Strategy) | K 線週期切換 | 不同時間週期使用不同的資料重取樣策略（日/週/月/分鐘） |
| 模板方法模式 (Template Method) | ChartRenderer 渲染流程 | 所有圖表共用相同的渲染流程框架（初始化 figure -> 添加 trace -> 套用 layout），但各類圖表的具體 trace 不同 |
| 建造者模式 (Builder) | DashLayout 版面建構 | 逐步建構複雜的 Dash 版面配置 |

### 6.4 日誌設計

```python
# src/config.py 中的日誌配置

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S"
        },
        "detailed": {
            "format": "%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "standard",
            "stream": "ext://sys.stdout"
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "detailed",
            "filename": "logs/app.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "encoding": "utf-8"
        }
    },
    "loggers": {
        "autofetchstock": {
            "level": "DEBUG",
            "handlers": ["console", "file"],
            "propagate": False
        },
        "autofetchstock.fetcher": {
            "level": "DEBUG",
            "handlers": ["console", "file"],
            "propagate": False
        },
        "autofetchstock.scheduler": {
            "level": "INFO",
            "handlers": ["console", "file"],
            "propagate": False
        }
    }
}
```

### 6.5 錯誤處理設計

以下為各錯誤場景的處理流程與對應使用者介面訊息。

| 錯誤場景 | 對應需求 | 處理方式 | 使用者介面訊息 |
|----------|---------|---------|--------------|
| TWSE API 連線逾時 | REQ-100 | 中斷請求、30 秒後重試一次 | "網路連線逾時，請稍後再試" |
| API 回傳格式異常 | REQ-101 | 捨棄本次資料、記錄錯誤日誌 | "資料格式異常，已略過本次更新" |
| 查無股票 | REQ-102 | 返回空結果 | "查無此股票，請確認輸入內容" |
| JSON 檔案損毀 | REQ-103 | 備份損毀檔、建新檔 | "歷史資料載入失敗，已重新建立資料檔" |
| API 連續 3 次失敗 | REQ-104 | 暫停自動排程 | "資料來源暫時無法存取，自動更新已暫停" |
| 磁碟空間不足 | REQ-105 | 停止資料寫入 | "磁碟空間不足，請清理磁碟後重試" |
| 排程任務例外 | REQ-106 | 捕捉例外、記錄堆疊、繼續排程 | （僅記錄日誌，不中斷系統） |

**錯誤訊息顯示方式**：在介面底部設置一個 `error-message-display` 區域，使用不同顏色區分錯誤等級：
- 紅色背景：嚴重錯誤（系統無法繼續該操作）
- 黃色背景：警告（系統自動處理，但通知使用者）
- 藍色背景：資訊（系統狀態通知）

---

## 7. 效能設計

### 7.1 效能目標與策略

| 需求 | 目標 | 策略 |
|------|------|------|
| REQ-080 | 查詢回應 < 3 秒 | 非同步 callback 處理、API 回應快取、先顯示快取資料再更新 |
| REQ-081 | 1 年 K 線資料流暢渲染，互動 < 500ms | Plotly 原生支援 WebGL 渲染大量資料點、限制初始載入資料量、使用 rangeslider 控制可視範圍 |
| REQ-082 | 記憶體 < 512MB | 使用 pandas 的記憶體最佳化（適當的 dtype）、限制分時資料快取大小、定期清理不再使用的 DataFrame |
| REQ-056 | K 線週期切換 < 2 秒 | 預先計算各週期的 DataFrame 並快取、只在切換時重新渲染圖表 |

### 7.2 快取策略

```python
class DataCache:
    """資料快取管理"""

    def __init__(self, max_size: int = 20):
        """
        max_size: 最多快取幾支股票的資料
        使用 LRU (Least Recently Used) 策略淘汰
        """

    # 快取項目：
    # - 股票清單（24 小時有效期）
    # - 各股票的日 K DataFrame（直到有新資料寫入時失效）
    # - 各週期重取樣後的 DataFrame（依賴日 K 快取）
    # - 即時報價（每次排程更新時刷新）
```

---

## 8. 測試策略

### 8.1 單元測試

| 模組 | 測試重點 | 測試方法 |
|------|---------|---------|
| DataFetcher | API 請求構建、回應解析、錯誤處理、重試邏輯、頻率限制 | 使用 unittest.mock 模擬 HTTP 回應 |
| DataStorage | JSON 讀寫、原子性寫入、追加模式、損毀處理、磁碟空間檢查 | 使用 tmp_path fixture 建立臨時檔案 |
| DataProcessor | 移動平均線計算、資料重取樣、OHLC 驗證、漲跌計算、買賣量分離 | 使用預建立的測試 DataFrame |
| ChartRenderer | 圖表 Figure 結構驗證、顏色正確性、trace 數量與類型 | 檢查返回的 go.Figure 物件屬性 |
| Scheduler | 交易時段判斷、任務新增/移除、暫停/恢復、例外處理 | 使用 freezegun 模擬時間 |

### 8.2 整合測試

| 場景 | 測試內容 |
|------|---------|
| 完整查詢流程 | 搜尋股票 -> 抓取資料 -> 儲存 -> 處理 -> 渲染圖表 |
| 即時更新流程 | 排程觸發 -> 抓取 -> 儲存 -> 更新分時圖 |
| 錯誤恢復流程 | API 失敗 -> 重試 -> 連續失敗 -> 暫停排程 -> 恢復 |
| 資料持久化 | 寫入 JSON -> 系統重啟 -> 載入歷史資料 -> 驗證完整性 |

### 8.3 端對端測試

| 場景 | 測試內容 |
|------|---------|
| 使用者搜尋股票 | 輸入 "2330" -> 顯示台積電資訊 -> 顯示分時圖 |
| 頁籤切換 | 點選 K 線圖頁籤 -> 顯示 K 線蠟燭圖 |
| K 線週期切換 | 選擇週 K -> 圖表更新為週 K 資料 |
| 錯誤場景 | 輸入不存在的代號 -> 顯示錯誤訊息 |

### 8.4 測試覆蓋率目標

| 層級 | 目標覆蓋率 |
|------|-----------|
| 整體 | >= 80% |
| DataFetcher | >= 90%（含所有錯誤路徑） |
| DataStorage | >= 90%（含損毀恢復路徑） |
| DataProcessor | >= 95%（核心計算邏輯） |
| ChartRenderer | >= 70%（圖表渲染較難完整測試） |

---

## 9. 需求追溯矩陣

| 需求編號 | 設計元件 | 章節參考 | 驗證方式 |
|---------|---------|---------|---------|
| REQ-001 | 全系統 | 1.2 技術堆疊 | 所有模組以 Python 實作 |
| REQ-002 | DataFetcher | 2.2 DataFetcher / 4.1 TWSE API | 單元測試驗證 API 呼叫 |
| REQ-003 | DataStorage | 2.3 DataStorage | 單元測試驗證 JSON 讀寫 |
| REQ-004 | AppController + DashLayout | 2.1 AppController / 2.7 DashLayout | 端對端測試驗證介面元素 |
| REQ-005 | ChartRenderer (ChartColors) | 2.5 ChartRenderer 顏色配置 | 單元測試驗證顏色值 |
| REQ-010 | AppController._on_stock_search + DataFetcher.search_stock | 2.1 / 2.2 | 整合測試 |
| REQ-011 | AppController + DataFetcher | 2.1 / 2.2 / 7.1 效能目標 | 效能測試 (< 3 秒) |
| REQ-012 | AppController._on_stock_search + DashLayout (match-list) | 2.1 / 2.7 | 端對端測試 |
| REQ-020 | DashLayout (stock-name-display) | 2.7 版面結構 | 端對端測試 |
| REQ-021 | DashLayout (price/change/volume-display) | 2.7 版面結構 | 端對端測試 |
| REQ-022 | AppController (style callback) + ChartColors.UP_COLOR | 2.1 / 2.5 | 單元測試驗證紅色樣式 |
| REQ-023 | AppController (style callback) + ChartColors.DOWN_COLOR | 2.1 / 2.5 | 單元測試驗證綠色樣式 |
| REQ-024 | AppController (style callback) + ChartColors.FLAT_COLOR | 2.1 / 2.5 | 單元測試驗證白色樣式 |
| REQ-030 | DashLayout (main-tabs) | 2.7 版面結構 | 端對端測試 |
| REQ-031 | AppController._on_tab_switch | 2.1 callback 設計 | 端對端測試 |
| REQ-032 | AppController._on_tab_switch | 2.1 callback 設計 | 端對端測試 |
| REQ-040 | ChartRenderer.render_intraday_chart | 2.5 ChartRenderer | 單元測試 |
| REQ-041 | ChartRenderer.render_intraday_chart | 2.5 ChartRenderer | 單元測試 |
| REQ-042 | ChartRenderer.render_buy_sell_volume + DataProcessor.separate_buy_sell_volume | 2.4 / 2.5 | 單元測試 |
| REQ-043 | Scheduler.is_market_open + auto-update-interval | 2.6 排程邏輯 | 整合測試 |
| REQ-044 | AppController._on_interval_update | 2.1 callback / 4.2 Dash Callback | 整合測試 |
| REQ-045 | ChartRenderer.render_intraday_price_line (baseline) | 2.5 ChartRenderer | 單元測試 |
| REQ-050 | ChartRenderer.render_candlestick + ChartColors | 2.5 ChartRenderer | 單元測試 |
| REQ-051 | ChartRenderer.render_moving_averages + DataProcessor.calculate_moving_averages | 2.4 / 2.5 | 單元測試 |
| REQ-052 | DashLayout (ohlc-display) + AppController | 2.7 / 4.2 Dash Callback | 端對端測試 |
| REQ-053 | ChartRenderer.render_volume_bars | 2.5 ChartRenderer | 單元測試 |
| REQ-054 | ChartRenderer.render_volume_moving_averages + DataProcessor.calculate_volume_moving_averages | 2.4 / 2.5 | 單元測試 |
| REQ-055 | DashLayout (period-selector) + AppController._on_period_change | 2.7 / 2.1 | 端對端測試 |
| REQ-056 | AppController._on_period_change + DataProcessor.resample_to_period | 2.1 / 2.4 / 7.1 | 效能測試 (< 2 秒) |
| REQ-057 | ChartRenderer.render_price_extremes + DataProcessor.find_visible_range_extremes | 2.4 / 2.5 | 單元測試 |
| REQ-058 | K 線圖 hoverData callback + DashLayout (ohlc-display) | 4.2 Dash Callback | 端對端測試 |
| REQ-060 | Scheduler | 2.6 Scheduler | 整合測試 |
| REQ-061 | Scheduler.is_market_open + Scheduler.start | 2.6 排程邏輯 | 單元測試 (freezegun) |
| REQ-062 | Scheduler.is_market_open (非交易時段停止) | 2.6 排程邏輯 | 單元測試 (freezegun) |
| REQ-063 | Scheduler._fetch_job + DataFetcher + DataStorage | 2.2 / 2.3 / 2.6 | 整合測試 |
| REQ-064 | DataStorage (timestamp 欄位) | 2.3 / 3.1 DailyOHLC.timestamp | 單元測試 |
| REQ-070 | DataStorage (檔案結構設計) | 2.3 檔案結構 | 單元測試 |
| REQ-071 | DataStorage + DailyOHLC 資料模型 | 2.3 JSON 格式 / 3.1 | 單元測試 |
| REQ-072 | DataStorage.save_daily_data (追加模式) | 2.3 DataStorage | 單元測試 |
| REQ-073 | DataStorage.load_daily_data (系統啟動時載入) | 2.3 DataStorage | 整合測試 |
| REQ-080 | 效能策略：快取 + 非同步 callback | 7.1 效能目標 | 效能測試 |
| REQ-081 | ChartRenderer (WebGL) + 資料量限制 | 7.1 效能目標 | 效能測試 |
| REQ-082 | DataCache (LRU) + dtype 最佳化 | 7.1 / 7.2 快取策略 | 效能測試 |
| REQ-083 | DataProcessor.validate_ohlc_data | 2.4 DataProcessor / 3.2 驗證規則 | 單元測試 |
| REQ-084 | DataStorage._atomic_write | 2.3 原子性寫入流程 | 單元測試 |
| REQ-085 | ChartRenderer._apply_chart_layout (標題/軸標籤/圖例) | 2.5 ChartRenderer | 單元測試 |
| REQ-086 | ChartRenderer.render_kline_chart (scrollZoom/dragmode) | 2.5 ChartRenderer | 手動測試 |
| REQ-087 | 模組化程式碼組織 | 6.1 程式碼組織 | 程式碼審查 |
| REQ-088 | logging 模組 + LOGGING_CONFIG | 6.4 日誌設計 | 單元測試 |
| REQ-090 | ChartRenderer (圖表匯出 PNG) | 2.5 ChartRenderer (選配) | 單元測試 |
| REQ-091 | AppController 多股監控模式 (選配) | 2.1 AppController (選配) | 整合測試 |
| REQ-092 | DataProcessor 技術指標擴充 (選配) | 2.4 DataProcessor (選配) | 單元測試 |
| REQ-093 | DataStorage CSV 匯出 (選配) | 2.3 DataStorage (選配) | 單元測試 |
| REQ-100 | DataFetcher._make_request (逾時+重試) | 2.2 錯誤處理流程 / 6.5 | 單元測試 |
| REQ-101 | DataFetcher._make_request (格式驗證) | 2.2 錯誤處理流程 / 6.5 | 單元測試 |
| REQ-102 | DataFetcher.search_stock + StockNotFoundError | 2.2 / 6.2 例外類別 | 單元測試 |
| REQ-103 | DataStorage.load_daily_data + _backup_corrupted_file | 2.3 DataStorage / 6.5 | 單元測試 |
| REQ-104 | DataFetcher._check_consecutive_failures + Scheduler.pause_auto_fetch | 2.2 / 2.6 / 6.5 | 整合測試 |
| REQ-105 | DataStorage._check_disk_space | 2.3 DataStorage / 6.5 | 單元測試 |
| REQ-106 | Scheduler._fetch_job (try-except) | 2.6 排程邏輯 / 6.5 | 單元測試 |

---

## 10. 品質門檻狀態

**設計 -> 任務規劃 品質門檻**：

- [x] 所有需求已對應到設計元件（48/48 項需求已涵蓋）
- [x] 元件介面已完整定義（輸入/輸出/方法簽名）
- [x] 資料模型完整且包含驗證規則
- [x] 錯誤處理涵蓋所有失敗場景（7 項異常行為需求全數對應）
- [x] 安全措施已文件化（網路安全/資料安全/應用安全）
- [x] 測試策略已針對各元件定義
- [x] 效能考量已文件化並提供具體策略
- [x] 模組化架構設計（6 個核心元件、獨立職責）

**需求涵蓋率**：100%（48/48 項需求已對應設計元件）

**可進入任務規劃階段**：是

### 設計決策紀錄

| 編號 | 決策 | 理由 |
|------|------|------|
| DD-01 | 選用 Dash + Plotly 作為 Web 框架 | Plotly 原生支援 Candlestick 圖表類型、make_subplots 支援 K 線圖+成交量圖的子圖佈局、dcc.Interval 支援即時更新、dcc.Tabs 支援頁籤切換，完美對應需求中的所有圖表與互動需求 |
| DD-02 | 選用 APScheduler 作為排程引擎 | 輕量級、支援 interval/cron 排程、可內嵌於 Python 應用中、不需額外的訊息佇列或 worker 程序 |
| DD-03 | 選用 pandas 進行資料處理 | 提供 resample() 方法直接支援 K 線週期轉換、rolling() 方法支援移動平均線計算、DataFrame 結構便於與 Plotly 整合 |
| DD-04 | JSON 檔案按股票代號分檔儲存 | 符合 REQ-070 要求、避免單一大檔案的讀寫效能問題、便於管理與備份 |
| DD-05 | 分時資料按日期分檔 | 分時資料量較大，按日期分檔可限制單一檔案大小、歷史分時資料可依需求清理 |
| DD-06 | 使用原子性寫入（暫存檔 + rename） | 確保 REQ-084 要求的寫入原子性，os.replace() 在 POSIX 系統上是原子操作 |
| DD-07 | 預設綁定 127.0.0.1 | 本系統為個人使用工具，預設僅允許本地存取，減少安全風險 |
| DD-08 | 使用 LRU 快取策略 | 限制記憶體使用量 (REQ-082)，自動淘汰最久未使用的股票資料 |
