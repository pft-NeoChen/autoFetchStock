# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

**autoFetchStock** 是一套台股即時資料抓取與視覺化系統（Taiwan Stock Real-time Data Fetcher & Visualizer）。

- **雙資料來源**：TWSE API（台灣證交所公開資料）與永豐金 Shioaji API（即時串流）
- **Web 介面**：Dash + Plotly，提供分時走勢圖與 K 線圖（含 MA/成交量均線）
- **雙環境支援**：Shioaji API 支援模擬/正式環境切換
- **版本**：0.1.0 (Alpha)，Python >= 3.10
- **專案狀態**：44.2% 完成（23/52 tasks），測試套件尚未實作

---

## 環境設定

```bash
# 複製環境變數範本並填入 Shioaji API 金鑰
cp config.env.example config.env

# Shioaji 憑證放置於 cert/ 目錄（已在 .gitignore 中排除）
# cert/Sinopac.pfx
```

**環境變數**（`config.env`）：

| 變數名稱 | 說明 |
|---------|------|
| `SHIOAJI_API_KEY_SIM` / `SHIOAJI_SECRET_KEY_SIM` | 模擬環境金鑰 |
| `SHIOAJI_API_KEY_PROD` / `SHIOAJI_SECRET_KEY_PROD` | 正式環境金鑰 |
| `SHIOAJI_CERT_PATH` | 憑證路徑（預設 `./cert/Sinopac.pfx`） |
| `SHIOAJI_CERT_PASSWORD` | 憑證密碼 |
| `SHIOAJI_PERSON_ID` | 身分證/統編 |
| `SHIOAJI_SIMULATION=true` | 預設使用模擬環境 |

---

## 常用指令

```bash
# 安裝依賴
pip install -r requirements.txt

# 啟動應用（預設 http://127.0.0.1:8050）
python -m src.main
python -m src.main --host 0.0.0.0 --port 8080 --debug
python -m src.main --production    # 正式環境（Shioaji 切換為 prod）

# 執行測試（測試套件目前為空）
pytest
pytest --cov=src                    # 含覆蓋率
pytest tests/test_fetcher/ -v       # 單一模組
pytest tests/test_processor/test_data_processor.py::TestClassName::test_method  # 單一測試

# Shioaji 連線測試（scripts/ 目錄）
python scripts/test_shioaji_login.py
python scripts/test_shioaji_market_data.py
```

---

## 架構

七大核心模組，分層架構（Layered Architecture），各模組職責獨立：

```
src/
├── main.py                    # 入口點（CLI 參數解析、signal handler、啟動伺服器）
├── config.py                  # AppConfig dataclass + 日誌設定 + API 端點常數
├── models.py                  # 所有 dataclass/enum（10 個 dataclass，2 個 enum）
├── exceptions.py              # 自定義例外（9 個，對應 REQ-100~106）
├── fetcher/
│   ├── data_fetcher.py        # DataFetcher：TWSE API 請求、頻率限制、重試、失敗計數
│   ├── shioaji_fetcher.py     # ShioajiFetcher：永豐金 Shioaji API 即時串流（Singleton）
│   └── twse_parser.py         # TWSEParser：解析 TWSE 回應 JSON/HTML 為 dataclass
├── storage/
│   └── data_storage.py        # DataStorage：JSON 檔案讀寫、原子性寫入、損毀備份
├── processor/
│   └── data_processor.py      # DataProcessor：MA 計算、K 線重取樣、漲跌計算、OHLC 驗證
├── renderer/
│   ├── chart_renderer.py      # ChartRenderer：Plotly K 線圖/分時圖渲染
│   └── chart_colors.py        # ChartColors：顏色常數（紅漲綠跌台灣慣例）
├── scheduler/
│   └── scheduler.py           # Scheduler：APScheduler 定時抓取、交易時段判斷
└── app/
    ├── app_controller.py      # AppController：初始化所有元件、管理生命週期
    ├── layout.py              # Dash 版面配置（元件 ID 定義）
    ├── callbacks.py           # CallbackManager：所有 Dash callback 函式
    └── assets/style.css       # 深色主題 CSS

scripts/                        # 獨立測試腳本（不依賴應用程式模組）
├── test_shioaji_login.py      # Shioaji 登入連線測試（sim/prod 雙模式）
└── test_shioaji_market_data.py # Shioaji 市場資料取得測試（4 步驟整合測試）

specs/history/                  # 規格文件（cc-sdd 工作流歸檔）
├── REQUIREMENTS.md            # EARS 格式需求（48 項，REQ-001~REQ-106）
├── DESIGN.md                  # 技術設計（元件介面、資料模型、測試策略）
├── TASK.md                    # 任務分解（52 項，23 項已完成）
└── SHIOAJI_PLAN.md            # Shioaji API 整合計畫
```

**資料流**：
- **TWSE 模式**：使用者搜尋 → DataFetcher (TWSE API) → DataStorage (JSON) → DataProcessor (pandas) → ChartRenderer (Plotly) → Dash callback 更新前端
- **Shioaji 模式**：ShioajiFetcher (即時串流) → callback 轉換 → DataStorage → 同上流程

**資料儲存**：
- `data/stocks/{stock_id}.json` — 歷史日成交資料（`StockDailyFile` 格式）
- `data/intraday/{stock_id}_{yyyymmdd}.json` — 分時資料（`StockIntradayFile` 格式）
- `data/cache/` — 快取（股票清單、我的最愛）
- `data/backup/` — 損毀檔案自動備份

---

## 資料模型（`src/models.py`）

### Enum

| 名稱 | 值 | 說明 |
|------|----|------|
| `PriceDirection` | `UP`, `DOWN`, `FLAT` | 漲跌方向 |
| `KlinePeriod` | `DAILY`, `WEEKLY`, `MONTHLY`, `MIN_1`, `MIN_5`, `MIN_15`, `MIN_30`, `MIN_60` | K 線週期，含 `display_name`、`minutes`、`pandas_resample_rule` 屬性 |

### Dataclass

| 名稱 | 說明 |
|------|------|
| `StockInfo` | 股票基本資訊（stock_id 1~6 碼英數字、stock_name、market） |
| `RealtimeQuote` | 即時報價（含 current_price、OHLC、change、volume、bid/ask、timestamp） |
| `DailyOHLC` | 日線 OHLC 資料（含 OHLC 驗證：high ≥ max(open,close)，low ≤ min(open,close)） |
| `IntradayTick` | 分時明細（price、volume、buy_volume、sell_volume、accumulated_volume、is_odd） |
| `PriceChange` | 漲跌計算結果（amount、percentage、direction），有 `calculate()` class method |
| `SchedulerStatus` | 排程器狀態（is_running、is_market_open、is_paused、active_jobs、consecutive_failures） |
| `StockDailyFile` | JSON 檔案根結構（股票代號、名稱、最後更新時間、`DailyOHLC` 列表） |
| `StockIntradayFile` | JSON 檔案根結構（股票代號、名稱、日期、前收盤、`IntradayTick` 列表） |
| `PriceExtremes` | 可視範圍內最高/最低價及日期（用於 K 線圖標注） |

所有 Dataclass 均有 `to_dict()` 和 `from_dict()` 方法（用於 JSON 序列化）。

---

## 自定義例外（`src/exceptions.py`）

共 9 個，全繼承自 `AutoFetchStockError`：

| 例外類別 | REQ | 觸發條件 | 處理方式 |
|---------|-----|---------|---------|
| `ConnectionTimeoutError` | REQ-100 | TWSE API 逾時（預設 10 秒） | 顯示錯誤、30 秒後自動重試 |
| `InvalidDataError` | REQ-101 | 回應格式異常、欄位缺失、OHLC 驗證失敗 | 略過本次更新、記錄日誌 |
| `StockNotFoundError` | REQ-102 | 股票代號/名稱不存在 | 顯示「查無此股票」 |
| `DataCorruptedError` | REQ-103 | JSON 解析失敗、結構異常 | 備份損毀檔、建立新空檔 |
| `ServiceUnavailableError` | REQ-104 | 連續失敗 3 次 | 暫停自動排程、允許手動重試 |
| `DiskSpaceError` | REQ-105 | 可用空間 < 100MB | 停止所有寫入操作 |
| `SchedulerTaskError` | REQ-106 | 排程任務執行異常 | 記錄完整 stack trace、繼續執行其他任務 |
| `RateLimitError` | — | 請求頻率過高 | 等待指定秒數後重試 |

---

## 關鍵開發慣例

### 語言與型別
- **Python >= 3.10**，使用完整 type hints
- **import 路徑**：使用絕對路徑 `from src.xxx import yyy`
- **日誌模組**：使用 `logging.getLogger("autofetchstock.{module}")` 取得 logger

### 顏色慣例
- **紅漲**：`#EF5350`，**綠跌**：`#26A69A`，**持平**：`#FFFFFF`
- MA 線顏色：MA5 橘（`#FF9800`）、MA10 藍（`#2196F3`）、MA20 粉（`#E91E63`）、MA60 紫（`#9C27B0`）
- 深色主題背景：`#1E1E1E`
- 定義於 `src/renderer/chart_colors.py`

### API 規則
- **TWSE API 頻率限制**：每次請求間隔至少 3 秒（`RateLimitError`）
- **逾時設定**：10 秒（`ConnectionTimeoutError`）
- **重試機制**：連續失敗計數，達 3 次觸發 `ServiceUnavailableError` 並暫停排程

### 檔案操作
- **JSON 寫入必須使用原子性操作**：先寫暫存檔再 `os.replace()`，確保資料完整性
- **損毀檔案**：自動備份至 `data/backup/`，再建立空白檔案
- **磁碟空間**：寫入前檢查，可用空間 < 100MB 拋出 `DiskSpaceError`

### Dash 元件 ID 命名規範
- 使用 kebab-case：`stock-search-input`、`kline-chart`、`main-tabs`
- 詳見 `specs/history/DESIGN.md` 2.7 節

### 設計模式
- **Singleton**：`ShioajiFetcher`（thread-safe with lock）
- **Layered Architecture**：Fetcher → Storage → Processor → Renderer → UI
- **Dataclass + Enum**：所有資料模型

### 市場時段
- 台灣股市交易時間：**09:00 - 13:30（Asia/Taipei）**，週一至週五
- `Scheduler` 自動判斷是否在交易時段，非交易時段停止自動抓取

---

## 測試

### 設定（`pyproject.toml`）
- 框架：pytest
- 測試標記：`@pytest.mark.unit`、`@pytest.mark.integration`、`@pytest.mark.e2e`、`@pytest.mark.slow`
- 覆蓋率目標：整體 >= 80%，DataFetcher/DataStorage >= 90%，DataProcessor >= 95%

### 現狀
- **目前測試套件為空**（tests/ 目錄下只有 `__init__.py`）
- 需使用 `unittest.mock` 模擬 HTTP 回應，`tmp_path` fixture 處理檔案測試

### 目錄結構
```
tests/
├── test_fetcher/      # DataFetcher & TWSEParser 測試（待實作）
├── test_storage/      # DataStorage 測試（待實作）
├── test_processor/    # DataProcessor 測試（待實作）
├── test_renderer/     # ChartRenderer 測試（待實作）
├── test_scheduler/    # Scheduler 測試（待實作）
└── test_integration/  # 端對端測試（待實作）
```

---

## Spec-Driven Development 工作流

本專案使用 cc-sdd 工作流管理。規格文件已歸檔至 `specs/history/` 目錄：

| 文件 | 說明 |
|------|------|
| `specs/history/REQUIREMENTS.md` | EARS 格式需求（48 項，REQ-001~REQ-106） |
| `specs/history/DESIGN.md` | 技術設計（元件介面、資料模型、API 封裝、測試策略） |
| `specs/history/TASK.md` | 任務分解（52 項，23 項已完成，44.2%） |
| `specs/history/SHIOAJI_PLAN.md` | Shioaji API 整合計畫（已實作） |

### 任務進度（`specs/history/TASK.md`）
- **P0 基礎建設**：TASK-001~005（完成）
- **P1 資料層**：TASK-010~020（大部分完成）
- **P2 處理/渲染層**：TASK-021~030（完成）
- **P3 Dash UI 層**：TASK-031~045（部分完成）
- **P4 選配功能**：TASK-046~052（未開始）

---

## 依賴套件

| 套件 | 版本 | 用途 |
|------|------|------|
| `dash` | >=2.14 | Web 框架 |
| `plotly` | >=5.18 | 圖表渲染 |
| `requests` | >=2.31 | HTTP 客戶端（TWSE API） |
| `APScheduler` | >=3.10 | 排程背景任務 |
| `pandas` | >=2.1 | 資料處理（MA、重取樣） |
| `numpy` | >=1.26 | 數值計算 |
| `shioaji` | ==1.3.2 | 永豐金 API（固定版本） |
| `python-dotenv` | ==1.2.1 | 讀取 .env 檔案 |
| `msgpack` | latest | 序列化 |
| `orjson` | latest | 高效能 JSON |
| `pytest` | >=7.4 | 測試框架 |
| `pytest-cov` | >=4.1 | 覆蓋率報告 |
