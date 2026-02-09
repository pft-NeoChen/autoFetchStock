# autoFetchStock

**autoFetchStock** 是一個台股即時資料抓取與視覺化系統，旨在提供台灣證券交易所 (TWSE) 股票的即時成交資訊與歷史 K 線分析。

## 目前功能概要

- **即時資料抓取**: 對接 TWSE API，支援台股個股即時成交資訊與基本面資料抓取。
- **自動排程更新**: 內建 APScheduler，於台股交易時段 (09:00-13:30) 自動執行資料同步。
- **多週期 K 線分析**: 支援日/週/月及 1/5/15/30/60 分 K 線切換，並自動計算 MA 均線 (MA5, 10, 20, 60)。
- **互動式視覺化**: 基於 Dash 與 Plotly 構建，提供縮放、平移及游標追蹤功能的 K 線圖與分時走勢圖。
- **本地資料管理**: 使用 JSON 格式持久化儲存，具備原子性寫入機制以防資料損毀。
- **現代化 UI 介面**: 支援股票搜尋、即時漲跌幅統計與符合台股慣例的紅漲綠跌視覺呈現。

## 快速啟動

### 環境安裝
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 啟動應用
```bash
python -m src.main
```

### 執行測試
```bash
pytest
```