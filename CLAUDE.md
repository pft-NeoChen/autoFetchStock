# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

autoFetchStock 是一套台股即時資料抓取與視覺化系統。支援雙資料來源：TWSE API（台灣證交所公開資料）與永豐金 Shioaji API（即時串流），以 Dash + Plotly 建構 Web 介面，提供分時走勢圖與 K 線圖（含 MA/成交量均線）。Shioaji API 支援模擬/正式雙環境切換。

## 環境設定

```bash
# 複製環境變數範本並填入 Shioaji API 金鑰
cp config.env.example config.env

# Shioaji 憑證放置於 cert/ 目錄
# cert/Sinopac.pfx
```

**環境變數**（`config.env`）：
- `SHIOAJI_API_KEY_SIM` / `SHIOAJI_SECRET_KEY_SIM` — 模擬環境金鑰
- `SHIOAJI_API_KEY_PROD` / `SHIOAJI_SECRET_KEY_PROD` — 正式環境金鑰
- `SHIOAJI_CERT_PATH` / `SHIOAJI_CERT_PASSWORD` / `SHIOAJI_PERSON_ID` — 憑證設定
- `SHIOAJI_SIMULATION=true` — 預設使用模擬環境

## 常用指令

```bash
# 安裝依賴
pip install -r requirements.txt

# 啟動應用（預設 http://127.0.0.1:8050）
python -m src.main
python -m src.main --host 0.0.0.0 --port 8080 --debug

# 執行測試
pytest
pytest --cov=src                    # 含覆蓋率
pytest tests/test_fetcher/ -v       # 單一模組
pytest tests/test_processor/test_data_processor.py::TestClassName::test_method  # 單一測試

# Shioaji 連線測試（scripts/ 目錄）
python scripts/test_shioaji_login.py
python scripts/test_shioaji_market_data.py
```

## 架構

七大核心模組，分層架構，各模組職責獨立：

```
src/
├── main.py                    # 入口點（CLI 參數解析、啟動伺服器）
├── config.py                  # AppConfig dataclass + 日誌設定 + API 端點常數
├── models.py                  # 所有 dataclass/enum（StockInfo, DailyOHLC, IntradayTick, RealtimeQuote 等）
├── exceptions.py              # 自定義例外（對應 REQ-100~106）
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

scripts/                        # 獨立測試腳本
├── test_shioaji_login.py      # Shioaji 登入連線測試
└── test_shioaji_market_data.py # Shioaji 市場資料取得測試
```

**資料流**：
- **TWSE 模式**：使用者搜尋 → DataFetcher (TWSE API) → DataStorage (JSON) → DataProcessor (pandas) → ChartRenderer (Plotly) → Dash callback 更新前端
- **Shioaji 模式**：ShioajiFetcher (即時串流) → callback 轉換 → DataStorage → 同上流程

**資料儲存**：
- `data/stocks/{stock_id}.json` — 歷史日成交資料
- `data/intraday/{stock_id}_{yyyymmdd}.json` — 分時資料
- `data/cache/` — 快取（股票清單、我的最愛）
- `data/backup/` — 損毀檔案自動備份

## 關鍵開發慣例

- **Python >= 3.10**，使用 type hints
- **顏色慣例**：紅漲（#EF5350）綠跌（#26A69A），定義於 `src/renderer/chart_colors.py`
- **TWSE API 頻率限制**：每次請求間隔至少 3 秒，逾時 10 秒
- **JSON 寫入必須使用原子性操作**：先寫暫存檔再 `os.replace()`
- **Dash 元件 ID 命名規範**：見 `specs/history/DESIGN.md` 2.7 節（如 `stock-search-input`, `kline-chart`, `main-tabs`）
- **日誌模組**：使用 `logging.getLogger("autofetchstock.{module}")` 取得 logger
- **import 路徑**：使用絕對路徑 `from src.xxx import yyy`

## Spec-Driven Development 工作流

本專案使用 cc-sdd 工作流管理。規格文件已歸檔至 `specs/history/` 目錄：
- `specs/history/REQUIREMENTS.md` — EARS 格式需求（48 項，REQ-001~REQ-106）
- `specs/history/DESIGN.md` — 技術設計（元件介面、資料模型、API 封裝、測試策略）
- `specs/history/TASK.md` — 任務分解（52 項任務，23 項已完成）
- `specs/history/SHIOAJI_PLAN.md` — Shioaji API 整合計畫（已實作）

## 測試

- 使用 pytest，設定於 `pyproject.toml`
- 測試標記：`@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`, `@pytest.mark.slow`
- 覆蓋率目標：整體 >= 80%，DataFetcher/DataStorage >= 90%，DataProcessor >= 95%
- 使用 `unittest.mock` 模擬 HTTP 回應，`tmp_path` fixture 處理檔案測試
