# 專案任務分解文件 (Task Breakdown Document)

## 元資料
- **專案名稱**：autoFetchStock - 台股即時資料抓取與視覺化系統
- **最後更新**：2026-02-04
- **總任務數**：52
- **已完成**：23 (44.2%)

---

## 第一階段：基礎建設 (P0)

### 專案設定與環境建構

- [x] [TASK-001] 初始化專案目錄結構
  - **複雜度**：S
  - **需求對應**：REQ-001, REQ-087
  - **檔案**：整體目錄結構（依 DESIGN.md 6.1 節）
  - **接受標準**：
    - 建立 `src/`, `src/fetcher/`, `src/storage/`, `src/processor/`, `src/renderer/`, `src/scheduler/`, `src/app/` 等模組目錄
    - 建立 `data/stocks/`, `data/intraday/`, `data/cache/`, `data/backup/` 資料目錄
    - 建立 `logs/`, `tests/` 等輔助目錄
    - 所有 Python 套件目錄包含 `__init__.py`

- [x] [TASK-002] 建立專案設定檔與依賴管理
  - **複雜度**：S
  - **依賴**：TASK-001
  - **需求對應**：REQ-001
  - **檔案**：`requirements.txt`, `pyproject.toml`, `.gitignore`
  - **接受標準**：
    - `requirements.txt` 包含所有依賴套件及版本（Dash>=2.14, Plotly>=5.18, requests>=2.31, APScheduler>=3.10, pandas>=2.1, numpy>=1.26）
    - `pyproject.toml` 包含專案元資料與工具設定（pytest, coverage）
    - `.gitignore` 排除 `data/`, `logs/`, `__pycache__/`, `.env` 等
    - 執行 `pip install -r requirements.txt` 可成功安裝所有依賴

- [x] [TASK-003] 實作應用設定模組
  - **複雜度**：M
  - **依賴**：TASK-001
  - **需求對應**：REQ-088
  - **檔案**：`src/config.py`
  - **接受標準**：
    - 定義 `AppConfig` dataclass（host, port, debug, data_dir, fetch_interval, log_level, log_file）
    - 定義 `LOGGING_CONFIG` 日誌設定字典（console + file handler, RotatingFileHandler 10MB/5 份）
    - 日誌格式包含時間戳記、等級、模組名稱、訊息
    - 提供 `setup_logging()` 函式初始化日誌系統

- [x] [TASK-004] 實作資料模型模組
  - **複雜度**：M
  - **依賴**：TASK-001
  - **需求對應**：REQ-071
  - **檔案**：`src/models.py`
  - **接受標準**：
    - 定義 `PriceDirection` 列舉（UP, DOWN, FLAT）
    - 定義 `KlinePeriod` 列舉（DAILY, WEEKLY, MONTHLY, MIN_1, MIN_5, MIN_15, MIN_30, MIN_60）
    - 定義 `StockInfo`, `RealtimeQuote`, `DailyOHLC`, `IntradayTick`, `PriceChange`, `SchedulerStatus`, `AppConfig` 等 dataclass
    - 所有欄位均有型別標注
    - 資料驗證規則符合 DESIGN.md 3.2 節

- [x] [TASK-005] 實作自定義例外類別模組
  - **複雜度**：S
  - **依賴**：TASK-001
  - **需求對應**：REQ-100 ~ REQ-106
  - **檔案**：`src/exceptions.py`
  - **接受標準**：
    - 定義基礎例外 `AutoFetchStockError`
    - 定義 `ConnectionTimeoutError`（REQ-100）
    - 定義 `InvalidDataError`（REQ-101）
    - 定義 `StockNotFoundError`（REQ-102）
    - 定義 `DataCorruptedError`（REQ-103）
    - 定義 `ServiceUnavailableError`（REQ-104）
    - 定義 `DiskSpaceError`（REQ-105）
    - 定義 `SchedulerTaskError`（REQ-106）
    - 所有例外類別繼承自 `AutoFetchStockError`

---

### 資料抓取層 (DataFetcher)

- [x] [TASK-010] 實作 TWSE API 回應解析器
  - **複雜度**：L
  - **依賴**：TASK-004, TASK-005
  - **需求對應**：REQ-002, REQ-083
  - **檔案**：`src/fetcher/twse_parser.py`
  - **接受標準**：
    - 實作即時成交資訊回應解析（從 TWSE JSON 回應提取 n, z, o, h, l, y, v, t 欄位）
    - 實作個股日成交資訊回應解析（解析 data 二維陣列為 DailyOHLC 列表）
    - 實作股票清單回應解析（從 HTML 表格提取股票代號與名稱）
    - 每筆解析結果均驗證 OHLC 資料完整性（high >= max(open,close), low <= min(open,close), volume >= 0）
    - 遇到無效資料時拋出 `InvalidDataError`
    - 包含完整的日誌記錄

- [x] [TASK-011] 實作 DataFetcher 核心類別
  - **複雜度**：XL
  - **依賴**：TASK-010, TASK-003
  - **需求對應**：REQ-002, REQ-010, REQ-011, REQ-060, REQ-064, REQ-100, REQ-101, REQ-102, REQ-104
  - **檔案**：`src/fetcher/data_fetcher.py`
  - **接受標準**：
    - 實作 `fetch_realtime_quote()` 取得個股即時報價
    - 實作 `fetch_daily_history()` 取得個股指定月份歷史日成交資訊
    - 實作 `fetch_intraday_ticks()` 取得當日分時明細
    - 實作 `search_stock()` 依股票代號或名稱搜尋匹配清單
    - 底層 `_make_request()` 方法包含：
      - HTTPS 連線（REQ-002）
      - 10 秒逾時控制（REQ-100）
      - 每次請求間隔 >= 3 秒頻率限制
      - 連線逾時時 30 秒後自動重試一次（REQ-100）
      - 非預期格式時拋出 InvalidDataError（REQ-101）
      - 查無股票時拋出 StockNotFoundError（REQ-102）
    - 追蹤連續失敗次數，達 3 次時拋出 ServiceUnavailableError（REQ-104）
    - 成功時重置失敗計數器
    - 設定合理 User-Agent 標頭
    - 每次抓取記錄時間戳記（REQ-064）

---

### 資料儲存層 (DataStorage)

- [x] [TASK-020] 實作 DataStorage 核心類別
  - **複雜度**：XL
  - **依賴**：TASK-004, TASK-005, TASK-003
  - **需求對應**：REQ-003, REQ-070, REQ-071, REQ-072, REQ-073, REQ-084, REQ-103, REQ-105
  - **檔案**：`src/storage/data_storage.py`
  - **接受標準**：
    - 初始化時自動建立 `data/stocks/`, `data/intraday/`, `data/cache/`, `data/backup/` 目錄結構
    - 實作 `save_daily_data()` 以追加模式寫入日成交資料（REQ-072），不覆蓋既有歷史資料
    - 實作 `load_daily_data()` 載入指定股票歷史日成交資料（REQ-073）
    - 實作 `save_intraday_data()` 以追加模式寫入分時資料
    - 實作 `load_intraday_data()` 載入指定日期分時資料
    - 每支股票獨立 JSON 檔案，檔名包含股票代號（REQ-070）
    - JSON 欄位包含日期、時間、OHLC、成交量、成交金額（REQ-071）
    - 原子性寫入：先寫暫存檔再 `os.replace()`（REQ-084）
    - 檔案損毀時自動備份至 `data/backup/` 並建立新檔（REQ-103）
    - 寫入前檢查磁碟空間，低於 100MB 時拋出 DiskSpaceError（REQ-105）
    - 使用 pathlib 處理所有檔案路徑，防止路徑穿越
    - 實作 `_validate_json_integrity()` 驗證 JSON 資料結構完整性

---

### 資料處理層 (DataProcessor)

- [x] [TASK-030] 實作移動平均線與成交量均線計算
  - **複雜度**：M
  - **依賴**：TASK-004
  - **需求對應**：REQ-051, REQ-054
  - **檔案**：`src/processor/data_processor.py`
  - **接受標準**：
    - 實作 `calculate_moving_averages()` 計算 MA5, MA10, MA20, MA60
    - 實作 `calculate_volume_moving_averages()` 計算均量 5, 均量 20, 均量 60
    - 使用 pandas rolling() 方法計算
    - 資料不足時（如不足 60 日）對應均線欄位為 NaN
    - 返回的 DataFrame 包含新增的 ma5/ma10/ma20/ma60 及 vol_ma5/vol_ma20/vol_ma60 欄位

- [x] [TASK-031] 實作 K 線資料重取樣
  - **複雜度**：L
  - **依賴**：TASK-030
  - **需求對應**：REQ-055, REQ-056
  - **檔案**：`src/processor/data_processor.py`
  - **接受標準**：
    - 實作 `resample_to_period()` 將日 K 轉換為週 K、月 K
    - 重取樣規則：open 取 first, high 取 max, low 取 min, close 取 last, volume 取 sum
    - 實作 `resample_intraday_to_minutes()` 將 tick 資料聚合為 1/5/15/30/60 分鐘 K 線
    - 支援所有 8 種 KlinePeriod 週期
    - 轉換後的 DataFrame 結構與日 K 一致（date, open, high, low, close, volume）

- [x] [TASK-032] 實作漲跌計算與資料驗證
  - **複雜度**：M
  - **依賴**：TASK-004
  - **需求對應**：REQ-021, REQ-022, REQ-023, REQ-024, REQ-083
  - **檔案**：`src/processor/data_processor.py`
  - **接受標準**：
    - 實作 `calculate_price_change()` 計算漲跌金額與百分比
    - 返回 PriceChange 物件，包含 amount, percentage, direction (UP/DOWN/FLAT)
    - 實作 `validate_ohlc_data()` 驗證 OHLC 資料完整性
    - 驗證規則：所有欄位為有效數值、high >= max(open,close)、low <= min(open,close)、volume >= 0
    - 漲跌百分比計算精度至小數點後兩位

- [x] [TASK-033] 實作可視範圍極值與買賣量分離
  - **複雜度**：M
  - **依賴**：TASK-004
  - **需求對應**：REQ-042, REQ-057
  - **檔案**：`src/processor/data_processor.py`
  - **接受標準**：
    - 實作 `find_visible_range_extremes()` 找出指定範圍內最高價與最低價及對應日期
    - 實作 `separate_buy_sell_volume()` 分離買入量（正值）與賣出量（負值），以零軸為基準
    - 返回結構化的極值資訊（{highest: {price, date}, lowest: {price, date}}）

- [x] [TASK-034] 實作完整 K 線資料準備流程
  - **複雜度**：M
  - **依賴**：TASK-030, TASK-031, TASK-032, TASK-020
  - **需求對應**：REQ-050 ~ REQ-057
  - **檔案**：`src/processor/data_processor.py`
  - **接受標準**：
    - 實作 `prepare_kline_data()` 整合完整 K 線資料準備流程
    - 流程：從 DataStorage 載入原始資料 -> 轉換為 DataFrame -> 根據 period 重取樣 -> 計算所有均線 -> 返回完整 DataFrame
    - 支援所有 8 種時間週期
    - 返回的 DataFrame 包含 OHLC + 所有均線欄位

---

### 圖表渲染層 (ChartRenderer)

- [x] [TASK-040] 實作圖表顏色配置
  - **複雜度**：S
  - **依賴**：TASK-001
  - **需求對應**：REQ-005
  - **檔案**：`src/renderer/chart_colors.py`
  - **接受標準**：
    - 定義 `ChartColors` 類別，包含所有顏色常數
    - 紅色上漲（#EF5350）、綠色下跌（#26A69A）、白色平盤（#FFFFFF）
    - MA5 橘色、MA10 藍色、MA20 粉紅色、MA60 紫色
    - 成交量均線顏色與對應 MA 一致
    - 前日收盤價基準線黃色（#FFEB3B）
    - 深色背景（#1E1E1E）、網格線色（#333333）

- [x] [TASK-041] 實作 K 線蠟燭圖與成交量柱狀圖渲染
  - **複雜度**：XL
  - **依賴**：TASK-040, TASK-004
  - **需求對應**：REQ-050, REQ-051, REQ-052, REQ-053, REQ-054, REQ-057, REQ-058, REQ-085, REQ-086
  - **檔案**：`src/renderer/chart_renderer.py`
  - **接受標準**：
    - 實作 `render_kline_chart()` 使用 make_subplots 建立上下子圖（K 線 70% + 成交量 30%）
    - 實作 `render_candlestick()` 渲染 K 線蠟燭（紅漲綠跌）
    - 實作 `render_moving_averages()` 渲染 MA5/MA10/MA20/MA60 四條均線（各不同顏色）
    - 實作 `render_volume_bars()` 渲染成交量柱狀圖（顏色與對應 K 線一致）
    - 實作 `render_volume_moving_averages()` 渲染均量 5/20/60 三條均線
    - 實作 `render_price_extremes()` 標註可視範圍最高價與最低價數值
    - 支援滑鼠滾輪縮放（scrollZoom=True）與拖曳平移（REQ-086）
    - 隱藏 rangeslider
    - hover 時顯示 OHLC 完整資訊（REQ-058）
    - 圖表包含清晰的標題、軸標籤、圖例（REQ-085）

- [x] [TASK-042] 實作分時走勢圖與買賣量圖渲染
  - **複雜度**：L
  - **依賴**：TASK-040, TASK-004
  - **需求對應**：REQ-040, REQ-041, REQ-042, REQ-045, REQ-085
  - **檔案**：`src/renderer/chart_renderer.py`
  - **接受標準**：
    - 實作 `render_intraday_chart()` 使用 make_subplots 建立上下子圖（走勢 + 買賣量）
    - 實作 `render_intraday_price_line()` 渲染分時走勢折線圖
    - 包含前日收盤價基準線（黃色水平線）（REQ-045）
    - 實作 `render_buy_sell_volume()` 渲染買賣量視覺化（零軸分離，上方買入紅色、下方賣出綠色）（REQ-042）
    - 圖表包含清晰的標題、軸標籤、圖例（REQ-085）

- [x] [TASK-043] 實作圖表統一版面設定
  - **複雜度**：M
  - **依賴**：TASK-040
  - **需求對應**：REQ-085
  - **檔案**：`src/renderer/chart_renderer.py`
  - **接受標準**：
    - 實作 `_apply_chart_layout()` 統一套用深色背景、網格線色、字型
    - 所有圖表使用一致的視覺風格
    - 圖表響應式寬度設定
    - 互動操作回應延遲目標 < 500ms（REQ-081）

---

### 排程管理層 (Scheduler)

- [x] [TASK-050] 實作 Scheduler 核心類別
  - **複雜度**：L
  - **依賴**：TASK-011, TASK-020, TASK-005
  - **需求對應**：REQ-060, REQ-061, REQ-062, REQ-063, REQ-064, REQ-104, REQ-106
  - **檔案**：`src/scheduler/scheduler.py`
  - **接受標準**：
    - 使用 APScheduler 建立排程器實例
    - 實作 `start()` / `stop()` 排程器啟停控制
    - 實作 `is_market_open()` 判斷是否在台灣股市交易時段（09:00-13:30, Asia/Taipei）
    - 實作 `add_stock_job()` / `remove_stock_job()` 動態管理股票抓取任務
    - 實作 `_fetch_job()` 排程任務執行函式，包含完整 try-except 處理（REQ-106）
    - 交易時段自動啟動定時抓取（REQ-061），間隔遵守 TWSE API 限制
    - 非交易時段停止自動抓取（REQ-062）
    - 排程觸發時發送 API 請求並將回傳資料儲存至 JSON（REQ-063）
    - 收到 ServiceUnavailableError 時暫停自動抓取（REQ-104）
    - 實作 `pause_auto_fetch()` / `resume_auto_fetch()` 暫停/恢復機制
    - 排程任務例外不中斷排程器運作（REQ-106），記錄完整錯誤堆疊

---

## 第二階段：應用整合與前端介面 (P1)

### Dash 版面配置 (DashLayout)

- [x] [TASK-060] 實作 Dash 版面配置模組
  - **複雜度**：L
  - **依賴**：TASK-040
  - **需求對應**：REQ-004, REQ-030
  - **檔案**：`src/app/layout.py`
  - **接受標準**：
    - 建構股票搜尋輸入框（dcc.Input `stock-search-input` + html.Button `stock-search-button`）
    - 建構匹配清單區域（html.Div `stock-match-list`）
    - 建構股票資訊顯示區域（名稱 `stock-name-display`、股價 `stock-price-display`、漲跌 `stock-change-display`、成交量 `stock-volume-display`）
    - 建構雙頁籤切換元件（dcc.Tabs `main-tabs`：分時資料 + K 線圖）（REQ-030）
    - 建構時間週期選擇器（dcc.RadioItems `period-selector`，8 種週期選項）
    - 建構 OHLC 資訊顯示區（html.Div `ohlc-display`）
    - 建構圖表容器（dcc.Graph `intraday-price-chart`, `intraday-volume-chart`, `kline-chart`）
    - 建構隱藏元件：dcc.Interval `auto-update-interval`、dcc.Store `app-state-store`
    - 建構錯誤訊息區（html.Div `error-message-display`）
    - 建構系統狀態列（html.Div `system-status-bar`）
    - 所有元件 ID 命名符合 DESIGN.md 2.7 節規範

- [x] [TASK-061] 實作自訂 CSS 樣式
  - **複雜度**：M
  - **依賴**：TASK-060
  - **需求對應**：REQ-004, REQ-005, REQ-022, REQ-023, REQ-024
  - **檔案**：`src/app/assets/style.css`
  - **接受標準**：
    - 深色主題背景樣式
    - 股票搜尋區域樣式
    - 股價上漲紅色（.price-up）、下跌綠色（.price-down）、平盤白色（.price-flat）樣式類別
    - 頁籤切換樣式
    - 錯誤訊息樣式（紅色背景-嚴重錯誤、黃色背景-警告、藍色背景-資訊）
    - 響應式版面設計
    - 整體風格與圖表深色背景一致

### 應用控制器 (AppController)

- [x] [TASK-070] 實作 Dash Callback 函式
  - **複雜度**：XL
  - **依賴**：TASK-060, TASK-011, TASK-034, TASK-041, TASK-042, TASK-050
  - **需求對應**：REQ-010 ~ REQ-012, REQ-020 ~ REQ-024, REQ-031, REQ-032, REQ-044, REQ-055, REQ-056, REQ-058
  - **檔案**：`src/app/callbacks.py`
  - **接受標準**：
    - 實作股票搜尋 callback：輸入觸發搜尋、顯示匹配清單（REQ-012）、更新股票名稱與代號（REQ-020）、更新即時資訊（REQ-021）、依漲跌設定顏色樣式（REQ-022/023/024）
    - 實作頁籤切換 callback：切換分時資料/K 線圖頁籤內容（REQ-031/032）
    - 實作 K 線週期切換 callback：切換時間週期時 2 秒內重繪圖表（REQ-056）、支援 8 種週期（REQ-055）
    - 實作即時更新 callback：定時更新分時走勢圖與即時報價（REQ-044）
    - 實作 K 線 hover callback：滑鼠移至 K 線上方時顯示 OHLC 資訊（REQ-058）
    - 所有 callback 包含錯誤處理，錯誤訊息顯示至 `error-message-display`

- [x] [TASK-071] 實作 AppController 核心類別
  - **複雜度**：L
  - **依賴**：TASK-070, TASK-003
  - **需求對應**：REQ-004, REQ-011, REQ-080
  - **檔案**：`src/app/app_controller.py`
  - **接受標準**：
    - 初始化 Dash 應用實例與所有子元件（DataFetcher, DataStorage, DataProcessor, ChartRenderer, Scheduler）
    - 呼叫 DashLayout 建構版面配置
    - 註冊所有 Dash callback
    - 系統啟動時自動載入既有歷史資料（REQ-073）
    - 管理應用狀態（當前股票、當前頁籤、當前 K 線週期）
    - 查詢回應時間 < 3 秒（REQ-011, REQ-080）
    - 實作 `run()` 啟動應用伺服器（預設 127.0.0.1:8050）

- [x] [TASK-072] 實作應用入口點
  - **複雜度**：S
  - **依賴**：TASK-071
  - **需求對應**：REQ-001
  - **檔案**：`src/main.py`
  - **接受標準**：
    - 初始化日誌系統
    - 建立 AppConfig 實例
    - 建立 AppController 實例並啟動
    - 支援命令列參數（host, port, debug）
    - 正確處理 KeyboardInterrupt 優雅關閉

---

### 效能最佳化

- [ ] [TASK-080] 實作資料快取機制
  - **複雜度**：M
  - **依賴**：TASK-020, TASK-034
  - **需求對應**：REQ-080, REQ-081, REQ-082
  - **檔案**：`src/processor/data_processor.py` (或新增 `src/cache.py`)
  - **接受標準**：
    - 實作 LRU 快取策略，最多快取 20 支股票資料
    - 股票清單快取（24 小時有效期）
    - 日 K DataFrame 快取（新資料寫入時失效）
    - 各週期重取樣後的 DataFrame 快取
    - 即時報價快取（每次排程更新時刷新）
    - 記憶體使用量控制在 512MB 以下（REQ-082）
    - 查詢回應時間 < 3 秒（REQ-080）
    - 1 年 K 線資料流暢渲染，互動 < 500ms（REQ-081）

---

## 第三階段：測試與品質保證 (P1)

### 單元測試

- [ ] [TASK-100] 建立測試基礎設施
  - **複雜度**：M
  - **依賴**：TASK-002
  - **需求對應**：REQ-087
  - **檔案**：`tests/conftest.py`
  - **接受標準**：
    - 定義共用 pytest fixture（測試用 DataFrame、模擬 API 回應、臨時檔案目錄）
    - 定義測試用常數（測試股票代號、模擬 OHLC 資料）
    - 設定 pytest 標記（unit, integration, e2e）
    - 設定測試覆蓋率排除規則

- [ ] [TASK-101] DataFetcher 單元測試
  - **複雜度**：L
  - **依賴**：TASK-011, TASK-100
  - **需求對應**：REQ-100, REQ-101, REQ-102, REQ-104
  - **檔案**：`tests/test_fetcher/test_data_fetcher.py`
  - **目標覆蓋率**：>= 90%
  - **接受標準**：
    - 測試正常 API 請求構建與回應解析
    - 測試連線逾時處理與 30 秒後自動重試（REQ-100）
    - 測試非預期格式處理（REQ-101）
    - 測試查無股票處理（REQ-102）
    - 測試連續 3 次失敗暫停機制（REQ-104）
    - 測試請求頻率限制（間隔 >= 3 秒）
    - 測試失敗計數器重置
    - 使用 unittest.mock 模擬所有 HTTP 回應

- [ ] [TASK-102] TWSE API 解析器單元測試
  - **複雜度**：M
  - **依賴**：TASK-010, TASK-100
  - **需求對應**：REQ-002, REQ-083
  - **檔案**：`tests/test_fetcher/test_twse_parser.py`
  - **接受標準**：
    - 測試即時成交資訊解析正確性
    - 測試日成交資訊解析正確性
    - 測試股票清單解析正確性
    - 測試無效資料格式處理
    - 測試空資料處理
    - 測試 OHLC 驗證邏輯

- [ ] [TASK-103] DataStorage 單元測試
  - **複雜度**：L
  - **依賴**：TASK-020, TASK-100
  - **需求對應**：REQ-070, REQ-071, REQ-072, REQ-073, REQ-084, REQ-103, REQ-105
  - **檔案**：`tests/test_storage/test_data_storage.py`
  - **目標覆蓋率**：>= 90%
  - **接受標準**：
    - 測試 JSON 檔案建立與命名規則（REQ-070）
    - 測試 JSON 欄位完整性（REQ-071）
    - 測試追加寫入不覆蓋歷史資料（REQ-072）
    - 測試系統啟動載入歷史資料（REQ-073）
    - 測試原子性寫入（暫存檔 + rename）（REQ-084）
    - 測試檔案損毀處理（備份 + 建新檔）（REQ-103）
    - 測試磁碟空間不足處理（REQ-105）
    - 測試 JSON 結構完整性驗證
    - 使用 tmp_path fixture 建立臨時檔案

- [ ] [TASK-104] DataProcessor 單元測試
  - **複雜度**：L
  - **依賴**：TASK-030, TASK-031, TASK-032, TASK-033, TASK-100
  - **需求對應**：REQ-051, REQ-054, REQ-055, REQ-057, REQ-083
  - **檔案**：`tests/test_processor/test_data_processor.py`
  - **目標覆蓋率**：>= 95%
  - **接受標準**：
    - 測試 MA5/MA10/MA20/MA60 計算正確性（與手動計算結果比對）
    - 測試均量 5/20/60 計算正確性
    - 測試日 K 轉週 K、月 K 重取樣正確性
    - 測試分鐘 K 線聚合正確性（1/5/15/30/60 分鐘）
    - 測試漲跌金額與百分比計算
    - 測試 OHLC 資料驗證（有效/無效情境）
    - 測試可視範圍最高價/最低價計算
    - 測試買賣量分離邏輯
    - 測試資料不足時均線為 NaN 的情境

- [ ] [TASK-105] ChartRenderer 單元測試
  - **複雜度**：M
  - **依賴**：TASK-041, TASK-042, TASK-100
  - **需求對應**：REQ-005, REQ-050, REQ-085
  - **檔案**：`tests/test_renderer/test_chart_renderer.py`
  - **目標覆蓋率**：>= 70%
  - **接受標準**：
    - 測試 K 線圖 Figure 結構（子圖數量、trace 類型）
    - 測試顏色配置正確性（紅漲綠跌）
    - 測試移動平均線 trace 數量與顏色
    - 測試成交量柱狀圖 trace
    - 測試分時走勢圖結構
    - 測試前日收盤價基準線存在
    - 測試買賣量圖零軸分離
    - 測試圖表標題、軸標籤存在

- [ ] [TASK-106] Scheduler 單元測試
  - **複雜度**：M
  - **依賴**：TASK-050, TASK-100
  - **需求對應**：REQ-061, REQ-062, REQ-104, REQ-106
  - **檔案**：`tests/test_scheduler/test_scheduler.py`
  - **接受標準**：
    - 測試交易時段判斷（09:00-13:30 Asia/Taipei）
    - 測試非交易時段停止抓取
    - 測試任務新增與移除
    - 測試暫停與恢復機制
    - 測試排程任務例外不中斷排程器（REQ-106）
    - 使用 freezegun 模擬不同時間場景

### 整合測試

- [ ] [TASK-110] 完整查詢流程整合測試
  - **複雜度**：L
  - **依賴**：TASK-071, TASK-100
  - **需求對應**：REQ-010, REQ-011, REQ-020, REQ-021
  - **檔案**：`tests/test_integration/test_app_flow.py`
  - **接受標準**：
    - 測試搜尋股票 -> 抓取資料 -> 儲存 -> 處理 -> 渲染圖表完整流程
    - 測試即時更新流程：排程觸發 -> 抓取 -> 儲存 -> 更新分時圖
    - 測試錯誤恢復流程：API 失敗 -> 重試 -> 連續失敗 -> 暫停排程 -> 恢復
    - 測試資料持久化：寫入 JSON -> 重新載入 -> 驗證完整性
    - 使用 mock 模擬 TWSE API 回應

---

## 第四階段：文件與部署 (P2)

### 文件撰寫

- [ ] [TASK-120] 撰寫 README.md
  - **複雜度**：M
  - **依賴**：TASK-072
  - **檔案**：`README.md`
  - **接受標準**：
    - 專案簡介與功能說明
    - 系統需求與環境設定說明
    - 安裝步驟與依賴安裝指引
    - 使用方法（啟動、搜尋股票、切換圖表）
    - 目錄結構說明
    - 設定參數說明
    - 常見問題排解

- [ ] [TASK-121] 撰寫程式碼內文件
  - **複雜度**：M
  - **依賴**：TASK-071
  - **檔案**：所有 `src/` 下的 Python 檔案
  - **接受標準**：
    - 所有類別與公開方法包含 docstring
    - docstring 格式統一（Google style 或 NumPy style）
    - 複雜邏輯包含行內註解
    - 模組層級 docstring 說明模組用途

### 選配功能

- [ ] [TASK-130] 實作圖表匯出 PNG 功能
  - **複雜度**：M
  - **依賴**：TASK-041, TASK-042
  - **需求對應**：REQ-090
  - **檔案**：`src/renderer/chart_renderer.py`, `src/app/callbacks.py`
  - **接受標準**：
    - K 線圖與分時走勢圖支援匯出為 PNG 圖片
    - 在介面中提供匯出按鈕
    - 匯出圖片解析度適合閱讀

- [ ] [TASK-131] 實作資料匯出 CSV 功能
  - **複雜度**：M
  - **依賴**：TASK-020
  - **需求對應**：REQ-093
  - **檔案**：`src/storage/data_storage.py`, `src/app/callbacks.py`
  - **接受標準**：
    - 支援將股票歷史資料匯出為 CSV 格式
    - CSV 欄位包含日期、OHLC、成交量、成交金額
    - 在介面中提供匯出按鈕

- [ ] [TASK-132] 實作技術指標擴充功能
  - **複雜度**：XL
  - **依賴**：TASK-034, TASK-041
  - **需求對應**：REQ-092
  - **檔案**：`src/processor/data_processor.py`, `src/renderer/chart_renderer.py`
  - **接受標準**：
    - 支援 RSI 指標計算與渲染
    - 支援 MACD 指標計算與渲染
    - 支援 KD 指標計算與渲染
    - 各指標以獨立子圖或疊加方式呈現
    - 提供指標選擇器供使用者開關

- [ ] [TASK-133] 實作多股監控功能
  - **複雜度**：XL
  - **依賴**：TASK-071
  - **需求對應**：REQ-091
  - **檔案**：`src/app/app_controller.py`, `src/app/layout.py`, `src/app/callbacks.py`
  - **接受標準**：
    - 支援同時追蹤多支股票
    - 以分頁或分割畫面方式呈現
    - 排程器同時管理多支股票的抓取任務

---

## 已完成任務

- [x] [TASK-001] 初始化專案目錄結構
  - **完成日期**：2026-02-02
  - **說明**：建立 src/（含 6 個子模組）、data/（4 個子目錄）、tests/（6 個測試子目錄）、logs/ 完整目錄結構

- [x] [TASK-002] 建立專案設定檔與依賴管理
  - **完成日期**：2026-02-04
  - **說明**：建立 requirements.txt（11 個依賴套件）、pyproject.toml（含 pytest/coverage 設定）、.gitignore

- [x] [TASK-003] 實作應用設定模組
  - **完成日期**：2026-02-04
  - **說明**：建立 src/config.py，含 AppConfig dataclass、LOGGING_CONFIG、setup_logging()

- [x] [TASK-004] 實作資料模型模組
  - **完成日期**：2026-02-04
  - **說明**：建立 src/models.py，含 PriceDirection、KlinePeriod 列舉及 9 個 dataclass

- [x] [TASK-005] 實作自定義例外類別模組
  - **完成日期**：2026-02-04
  - **說明**：建立 src/exceptions.py，含 8 個自定義例外類別（REQ-100~106）

- [x] [TASK-040] 實作圖表顏色配置
  - **完成日期**：2026-02-04
  - **說明**：建立 src/renderer/chart_colors.py，含 ChartColors dataclass（紅漲綠跌台灣慣例）

---

## 任務依賴圖

```
TASK-001 (專案目錄結構)
    |
    +---> TASK-002 (設定檔與依賴管理)
    |       |
    |       +---> TASK-100 (測試基礎設施)
    |
    +---> TASK-003 (應用設定模組)
    |       |
    |       +---> TASK-011 (DataFetcher)
    |       +---> TASK-020 (DataStorage)
    |       +---> TASK-071 (AppController)
    |
    +---> TASK-004 (資料模型)
    |       |
    |       +---> TASK-010 (TWSE 解析器) ---> TASK-011 (DataFetcher)
    |       +---> TASK-030 (均線計算) ---> TASK-031 (K 線重取樣) ---> TASK-034 (K 線資料準備)
    |       +---> TASK-032 (漲跌計算)                                      |
    |       +---> TASK-033 (極值/買賣量) ----------------------------------|
    |       +---> TASK-041 (K 線圖渲染)
    |       +---> TASK-042 (分時走勢圖渲染)
    |
    +---> TASK-005 (例外類別)
    |       |
    |       +---> TASK-010, TASK-011, TASK-020, TASK-050
    |
    +---> TASK-040 (顏色配置)
            |
            +---> TASK-041, TASK-042, TASK-043, TASK-060

TASK-011 (DataFetcher) + TASK-020 (DataStorage) ---> TASK-050 (Scheduler)

TASK-060 (版面配置) + 所有核心元件 ---> TASK-070 (Callbacks) ---> TASK-071 (AppController) ---> TASK-072 (入口點)

TASK-020 + TASK-034 ---> TASK-080 (快取機制)

各核心元件 + TASK-100 ---> TASK-101 ~ TASK-106 (單元測試)

TASK-071 + TASK-100 ---> TASK-110 (整合測試)
```

---

## 設計元件覆蓋驗證

| 設計元件 | 任務編號 | 覆蓋狀態 |
|---------|---------|---------|
| AppController (2.1) | TASK-071, TASK-072, TASK-070 | 完整 |
| DataFetcher (2.2) | TASK-010, TASK-011 | 完整 |
| DataStorage (2.3) | TASK-020 | 完整 |
| DataProcessor (2.4) | TASK-030, TASK-031, TASK-032, TASK-033, TASK-034 | 完整 |
| ChartRenderer (2.5) | TASK-040, TASK-041, TASK-042, TASK-043 | 完整 |
| Scheduler (2.6) | TASK-050 | 完整 |
| DashLayout (2.7) | TASK-060, TASK-061 | 完整 |
| 資料模型 (3.1) | TASK-004 | 完整 |
| 例外類別 (6.2) | TASK-005 | 完整 |
| 應用設定 (6.4) | TASK-003 | 完整 |
| 快取策略 (7.2) | TASK-080 | 完整 |
| 測試策略 (8) | TASK-100 ~ TASK-110 | 完整 |

---

## 需求覆蓋驗證

| 需求編號 | 功能領域 | 對應任務 | 覆蓋狀態 |
|---------|---------|---------|---------|
| REQ-001 | 核心系統 | TASK-001, TASK-002, TASK-072 | 完整 |
| REQ-002 | 核心系統 | TASK-010, TASK-011 | 完整 |
| REQ-003 | 核心系統 | TASK-020 | 完整 |
| REQ-004 | 核心系統 | TASK-060, TASK-071 | 完整 |
| REQ-005 | 核心系統 | TASK-040, TASK-061 | 完整 |
| REQ-010 | 使用者輸入 | TASK-011, TASK-070 | 完整 |
| REQ-011 | 使用者輸入 | TASK-071, TASK-080 | 完整 |
| REQ-012 | 使用者輸入 | TASK-070 | 完整 |
| REQ-020 | 資訊顯示 | TASK-060, TASK-070 | 完整 |
| REQ-021 | 資訊顯示 | TASK-032, TASK-060, TASK-070 | 完整 |
| REQ-022 | 資訊顯示 | TASK-040, TASK-061, TASK-070 | 完整 |
| REQ-023 | 資訊顯示 | TASK-040, TASK-061, TASK-070 | 完整 |
| REQ-024 | 資訊顯示 | TASK-040, TASK-061, TASK-070 | 完整 |
| REQ-030 | 頁籤切換 | TASK-060 | 完整 |
| REQ-031 | 頁籤切換 | TASK-070 | 完整 |
| REQ-032 | 頁籤切換 | TASK-070 | 完整 |
| REQ-040 | 分時資料 | TASK-042 | 完整 |
| REQ-041 | 分時資料 | TASK-042 | 完整 |
| REQ-042 | 分時資料 | TASK-033, TASK-042 | 完整 |
| REQ-043 | 分時資料 | TASK-050 | 完整 |
| REQ-044 | 分時資料 | TASK-070 | 完整 |
| REQ-045 | 分時資料 | TASK-042 | 完整 |
| REQ-050 | K 線圖 | TASK-041 | 完整 |
| REQ-051 | K 線圖 | TASK-030, TASK-041 | 完整 |
| REQ-052 | K 線圖 | TASK-041, TASK-070 | 完整 |
| REQ-053 | K 線圖 | TASK-041 | 完整 |
| REQ-054 | K 線圖 | TASK-030, TASK-041 | 完整 |
| REQ-055 | K 線圖 | TASK-031, TASK-060, TASK-070 | 完整 |
| REQ-056 | K 線圖 | TASK-031, TASK-070 | 完整 |
| REQ-057 | K 線圖 | TASK-033, TASK-041 | 完整 |
| REQ-058 | K 線圖 | TASK-041, TASK-070 | 完整 |
| REQ-060 | 資料排程 | TASK-050 | 完整 |
| REQ-061 | 資料排程 | TASK-050 | 完整 |
| REQ-062 | 資料排程 | TASK-050 | 完整 |
| REQ-063 | 資料排程 | TASK-050 | 完整 |
| REQ-064 | 資料排程 | TASK-011, TASK-050 | 完整 |
| REQ-070 | 資料儲存 | TASK-020 | 完整 |
| REQ-071 | 資料儲存 | TASK-004, TASK-020 | 完整 |
| REQ-072 | 資料儲存 | TASK-020 | 完整 |
| REQ-073 | 資料儲存 | TASK-020, TASK-071 | 完整 |
| REQ-080 | 效能 | TASK-080, TASK-071 | 完整 |
| REQ-081 | 效能 | TASK-041, TASK-080 | 完整 |
| REQ-082 | 效能 | TASK-080 | 完整 |
| REQ-083 | 可靠性 | TASK-010, TASK-032 | 完整 |
| REQ-084 | 可靠性 | TASK-020 | 完整 |
| REQ-085 | 可用性 | TASK-041, TASK-042, TASK-043 | 完整 |
| REQ-086 | 可用性 | TASK-041 | 完整 |
| REQ-087 | 可維護性 | TASK-001, TASK-100 | 完整 |
| REQ-088 | 可維護性 | TASK-003 | 完整 |
| REQ-090 | 選配功能 | TASK-130 | 完整 |
| REQ-091 | 選配功能 | TASK-133 | 完整 |
| REQ-092 | 選配功能 | TASK-132 | 完整 |
| REQ-093 | 選配功能 | TASK-131 | 完整 |
| REQ-100 | 錯誤處理 | TASK-005, TASK-011 | 完整 |
| REQ-101 | 錯誤處理 | TASK-005, TASK-010, TASK-011 | 完整 |
| REQ-102 | 錯誤處理 | TASK-005, TASK-011 | 完整 |
| REQ-103 | 錯誤處理 | TASK-005, TASK-020 | 完整 |
| REQ-104 | 錯誤處理 | TASK-005, TASK-011, TASK-050 | 完整 |
| REQ-105 | 錯誤處理 | TASK-005, TASK-020 | 完整 |
| REQ-106 | 錯誤處理 | TASK-005, TASK-050 | 完整 |

---

## 品質門檻狀態

**任務規劃驗證**：
- OK 所有設計元件均有對應實作任務（12/12 元件已覆蓋）
- OK 所有 API 端點（TWSE API 封裝）均有對應任務（TASK-010, TASK-011）
- OK 資料儲存模式均有對應任務（TASK-020）
- OK 每個任務均有明確的接受標準
- OK 依賴關係形成有效 DAG（無循環依賴）
- OK 任務估算遵循一致的 S/M/L/XL 量表
- OK 測試任務涵蓋所有核心元件（6 組單元測試 + 1 組整合測試）
- OK 文件任務已包含（TASK-120, TASK-121）
- OK 無孤立任務（所有任務均有明確的目的與依賴路徑）

**需求覆蓋率**：100%（48/48 項需求已對應實作任務）

**設計元件覆蓋率**：100%（12/12 元件已對應實作任務）

**任務統計**：
| 複雜度 | 數量 |
|-------|------|
| S | 5 |
| M | 21 |
| L | 14 |
| XL | 7 |

**階段分佈**：
| 階段 | 優先級 | 任務數 | 說明 |
|------|-------|-------|------|
| 第一階段：基礎建設 | P0 | 18 | 目錄結構、核心元件實作 |
| 第二階段：應用整合 | P1 | 7 | Dash 前端、Callback、效能最佳化 |
| 第三階段：測試與品質 | P1 | 8 | 單元測試、整合測試 |
| 第四階段：文件與選配 | P2 | 6 | README、選配功能 |

**關鍵路徑**：
```
TASK-001 -> TASK-004 -> TASK-010 -> TASK-011 -> TASK-050 -> TASK-070 -> TASK-071 -> TASK-072
                                                    ^
TASK-001 -> TASK-004 -> TASK-030 -> TASK-031 -> TASK-034 ---+
                                                             |
TASK-001 -> TASK-040 -> TASK-041 ----------------------------+---> TASK-070
                                                             |
TASK-001 -> TASK-005 -> TASK-020 ----------------------------+
                                                             |
TASK-001 -> TASK-040 -> TASK-060 ----------------------------+
```

**風險評估**：
- **高複雜度任務**：TASK-011 (DataFetcher), TASK-020 (DataStorage), TASK-041 (K 線圖渲染), TASK-070 (Dash Callback), TASK-132 (技術指標), TASK-133 (多股監控) 均為 XL 複雜度，建議優先審查設計細節
- **關鍵阻塞點**：TASK-011 (DataFetcher) 被 TASK-050 (Scheduler) 與 TASK-070 (Callback) 依賴；TASK-020 (DataStorage) 被 TASK-034、TASK-050、TASK-080 依賴
- **外部依賴風險**：TWSE API 的穩定性與格式變更可能影響 TASK-010, TASK-011 的實作
- **技術專業需求**：金融圖表渲染（TASK-041, TASK-042）需要 Plotly 金融圖表經驗；pandas 時間序列處理（TASK-031）需要資料分析經驗

**可進入實作階段**：是
