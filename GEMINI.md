# GEMINI.md - autoFetchStock 專案指南

## 專案概覽 (Project Overview)

**autoFetchStock** 是一個台股即時資料抓取與視覺化系統，旨在提供台灣證券交易所 (TWSE) 股票的即時成交資訊與歷史 K 線分析。

### 核心技術棧 (Tech Stack)
- **語言**: Python 3.10+
- **前端/Web**: [Dash](https://dash.plotly.com/) (>= 2.14), [Plotly](https://plotly.com/python/) (>= 5.18)
- **資料處理**: [pandas](https://pandas.pydata.org/) (>= 2.1), [numpy](https://numpy.org/) (>= 1.26)
- **排程管理**: [APScheduler](https://apscheduler.readthedocs.io/) (>= 3.10)
- **HTTP 請求**: [requests](https://requests.readthedocs.io/) (>= 2.31)
- **測試框架**: [pytest](https://docs.pytest.org/) (>= 7.4)

### 系統架構 (Architecture)
系統採用模組化分層設計：
- **`src/app/`**: 應用入口與 UI 控制，包含 `AppController` (處理 Callback) 與 `layout.py` (介面配置)。
- **`src/fetcher/`**: 資料抓取層，負責與 TWSE API 溝通。
- **`src/storage/`**: 資料儲存層，使用本地 JSON 檔案進行持久化。
- **`src/processor/`**: 資料處理層，計算均線 (MA)、週/月 K 重取樣等。
- **`src/renderer/`**: 圖表渲染層，產生 K 線圖與分時走勢圖。
- **`src/scheduler/`**: 排程管理器，在台股交易時段 (09:00-13:30) 自動觸發抓取任務。

---

## 建立與運行 (Building and Running)

### 1. 環境安裝
建議使用虛擬環境 (Virtual Environment)：
```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
# 或 venv\Scripts\activate # Windows
pip install -r requirements.txt
```

### 2. 啟動應用
執行以下指令啟動 Dash 伺服器：
```bash
python -m src.main
```
常用參數：
- `--host`: 伺服器位址 (預設: 127.0.0.1)
- `--port`: 埠號 (預設: 8050)
- `--debug`: 開啟除錯模式
- `--data-dir`: 資料儲存目錄 (預設: data)

### 3. 執行測試
```bash
pytest
```
產生測試覆蓋率報告：
```bash
pytest --cov=src
```

---

## 開發慣例 (Development Conventions)

### 程式碼風格
- 遵循 **PEP 8** 規範。
- 使用 **Type Hinting** (Python 3.10+ 語法)。
- 變數與函式命名採用 `snake_case`，類別命名採用 `PascalCase`。

### 錯誤處理
- 自定義例外定義於 `src/exceptions.py`。
- 網路請求需考慮 TWSE API 的頻率限制 (至少間隔 3 秒)。
- 寫入 JSON 應使用原子性寫入 (先寫暫存檔再更名)，防止資料損毀。

### 資料儲存
- 歷史日成交資料存於 `data/stocks/{stock_id}.json`。
- 分時資料按日期存於 `data/intraday/{stock_id}_{date}.json`。
- 顏色規範：台灣股市慣例——**紅漲綠跌**。

### 文件規範
- 詳細的需求與設計規格位於 `specs/` 目錄。
- `specs/REQUIREMENTS.md`: 功能與非功能性需求。
- `specs/DESIGN.md`: 詳細的架構設計與元件介面。
