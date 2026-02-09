# Shioaji API (永豐金) 整合計畫

**文件狀態**: 待執行 (Pending Account Approval)  
**最後更新**: 2026-02-05  
**目標**: 整合永豐金 Shioaji API，解決 TWSE 爬蟲資料延遲與漏單問題，實現毫秒級即時監控與大戶追蹤。

---

## 1. 核心優勢與互補策略

目前的系統依賴 TWSE 網站爬蟲 (Polling)，存在 3-5 秒延遲且容易漏掉盤中瞬間大單。引入 Shioaji (Streaming) 可實現以下升級：

| 功能 | 目前 (TWSE) | 未來 (TWSE + Shioaji) | 優勢 |
| :--- | :--- | :--- | :--- |
| **報價機制** | 每 5 秒輪詢 | **WebSocket 推播** | 真正的即時跳動，無須手動刷新。 |
| **成交明細** | 僅快照 (Snapshot) | **逐筆成交 (Tick)** | 完整捕捉每一筆交易，**大戶監控零漏單**。 |
| **買賣力道** | 演算法推估 | **精準內外盤** | API 直接提供 Bid/Ask flag，無需猜測。 |
| **歷史 K 線** | 爬蟲 (慢) | **Kbars API (快)** | 秒速回補數月歷史資料。 |

### 雙軌並行架構 (Hybrid Architecture)

我們不廢除 TWSE 模組，而是採**混合模式**：

1.  **Shioaji (主軌)**：
    *   負責 **「當前查看股票」** 與 **「我的最愛」**。
    *   提供即時走勢、大戶監控、買賣力道分析。
    *   使用 WebSocket 串流技術。

2.  **TWSE (副軌/備援)**：
    *   負責 **「臨時搜尋」** (使用者尚未關注的股票)。
    *   負責 **「全市場代碼清單更新」**。
    *   當 Shioaji 連線中斷或達到訂閱上限時的自動備援。

---

## 2. 系統架構設計

### 新增模組
*   `src/fetcher/shioaji_fetcher.py`: 封裝 Shioaji API 的單例類別 (Singleton)。
*   `src/config.py`: 新增 API Key, Secret Key, 憑證路徑等設定欄位。

### 數據流 (Data Flow)

1.  **初始化**:
    *   App 啟動 -> `ShioajiFetcher` 嘗試登入 (載入憑證)。
    *   若登入成功，開啟 WebSocket 連線。

2.  **使用者搜尋/切換股票**:
    *   **Step 1**: `AppController` 檢查 Shioaji 是否可用。
    *   **Step 2 (可用)**: 呼叫 `shioaji_fetcher.subscribe(stock_id)`。
        *   接收 `quote` 與 `tick` 回調 (Callback)。
        *   將回調數據轉換為 `RealtimeQuote` 與 `IntradayTick` 物件。
        *   直接寫入 `DataStorage` 或更新記憶體快取。
    *   **Step 3 (不可用)**: 降級使用 `DataFetcher` (TWSE Polling)。

3.  **前端更新**:
    *   Dash 前端維持 `Interval` 輪詢 (例如每 1 秒)，但後端數據源已經是由 Shioaji 毫秒級寫入的最新數據，因此前端會感覺到圖表更新非常平滑。

---

## 3. 實作階段規劃

### Phase 0: 帳號與環境準備 (User Action)
*   [ ] 申請永豐金證券帳號 & API 權限。
*   [ ] 下載並備份憑證檔案 (`.pfx`)。
*   [ ] 準備 API Key 與 Secret Key。

### Phase 1: 基礎建設 (Developer)
1.  **依賴安裝**: `pip install shioaji`
2.  **設定檔擴充**: 更新 `.env` 或 `config.py` 支援帳號資訊讀取。
3.  **連線測試腳本**: 撰寫 `scripts/test_shioaji_login.py`，驗證憑證簽署與登入流程 (特別是 macOS 環境的 CA 設定)。

### Phase 2: 數據適配器 (Adapter)
1.  建立 `ShioajiFetcher` 類別。
2.  **Tick 轉換器**: 將 Shioaji 的 `Tick` 物件 (包含 `volume`, `price`, `ask`, `bid`, `simtrade`) 轉換為系統通用的 `IntradayTick`。
    *   *重點*: 直接使用 API 提供的 `simtrade` 過濾試撮，無需時間過濾。
    *   *重點*: 直接使用 API 提供的 `volume` 作為單筆量，無需差額計算。

### Phase 3: 整合與切換
1.  修改 `AppController`，加入雙 fetcher 管理邏輯。
2.  實作訂閱/退訂管理 (避免超過 200 檔限制)。
3.  優化前端 `Interval`，在 Shioaji 模式下可縮短至 1 秒甚至更短。

---

## 4. 關鍵技術筆記

### macOS 憑證簽署
Shioaji 在 macOS 上使用 `openssl` 進行憑證簽署。需確保環境變數設定正確：
```bash
# 範例
export CA_CERT_PATH=/path/to/sinopac.pfx
```

### 模擬交易 (Simulation Mode)
在開發階段，應優先使用 Shioaji 的模擬環境 (Simulation)，以免誤下單或影響正式帳號額度。

### 大戶邏輯遷移
一旦切換到 Shioaji，現有的 `DataProcessor` 中的「大戶推算邏輯」與「買賣力道推算邏輯」將不再需要（或作為備援），因為 Shioaji 直接提供：
*   `Tick.volume`: 真實單筆量 (直接篩選 > 499)。
*   `Tick.ask_side` / `Tick.bid_side`: 真實內外盤成交標記。

---

**下一步**: 待使用者帳號申請完成後，從 **Phase 1** 開始執行。
