# 爆量偵測（Volume Spike Detection）實作計畫

> **目標**：基於 1 分 K 偵測單檔股票成交量異常放大，於右側面板顯示爆量列表、K 線圖標記、瀏覽器原生推播。

---

## 1. 規格定案（Frozen Spec）

### 1.1 核心定義

- **爆量單位**：1 分鐘 K 棒（不用逐筆 tick；雜訊過多）
- **判定公式**：`volume_ratio = current_bar_volume / baseline_volume`
- **Baseline 演算法**：混合法（法 B 優先 → 法 A 退回）
  - **法 B（同時段歷史均量）**：取過去 5 個交易日同一分鐘 K 棒（如 10:35）的成交量，去極值後求均值
    - `sorted_vols = sorted([b.volume for b in historical_bars])`
    - `trimmed = sorted_vols[1:-1] if len(sorted_vols) >= 5 else sorted_vols`
    - `baseline = mean(trimmed)`
    - 需要至少 **3 個交易日**歷史資料
  - **法 A（當日近 N 根均量）退回**：歷史不足時，取當日近 20 根 1 分 K 均量（排除前 5 根開盤）
    - `baseline = mean(recent_bars_excluding_opening_5)`
    - 同時標記 `baseline_low_confidence = True`

### 1.2 Threshold（寫死於 `src/config.py`）

| 常數 | 值 | 用途 |
|------|----|----|
| `SPIKE_THRESHOLD_LOW` | 2.0 | 進入列表最低門檻（≥ 2× 即進列表）|
| `SPIKE_THRESHOLD_MID` | 3.0 | MID severity |
| `SPIKE_THRESHOLD_HIGH` | 5.0 | HIGH severity（觸發推播）|
| `SPIKE_THRESHOLD_EXTREME` | 10.0 | EXTREME severity |
| `SPIKE_MIN_ABS_VOLUME` | 100 | 絕對量下限（張），低於不判定 |
| `SPIKE_BASELINE_DAYS` | 5 | 法 B 取近幾日 |
| `SPIKE_BASELINE_MIN_DAYS` | 3 | 法 B 最少需要幾日 |
| `SPIKE_FALLBACK_WINDOW` | 20 | 法 A 取近幾根 |
| `SPIKE_FALLBACK_SKIP_OPENING` | 5 | 法 A 跳過開盤前幾根 |

### 1.3 Severity 配色

| Severity | Ratio 範圍 | 顏色 | 色碼 |
|----------|-----------|------|------|
| NORMAL | < 2.0 | — | — |
| LOW | 2.0 ~ 3.0 | 淡黃 | `#FFEB3B` |
| MID | 3.0 ~ 5.0 | 橘 | `#FF9800` |
| HIGH | 5.0 ~ 10.0 | 紅 | `#EF5350` |
| EXTREME | ≥ 10.0 | 紫 | `#9C27B0` |

### 1.4 實務坑對應

| 坑 | 處理方式 |
|---|---|
| 開盤首根（09:00）量天生大 | 法 B 同時段比較自然處理；法 A 跳過前 5 根 |
| 尾盤集合競價（13:25~13:30）| 同上，法 B 處理 |
| 冷門股 baseline 太小 | `volume >= 100 張 AND ratio >= 2.0` 才判 spike |
| 跳空後幾分鐘量大 | 法 B 5 日同時段均量自然吸收 |
| 除權息日 | 整合 `src/data/events.py`，當日跳過偵測 |
| 1 分 K 0 量 | `volume == 0` 直接跳過 |
| 歷史不足 | 退法 A + 標記 `baseline_low_confidence` |

### 1.5 UI 規格

**位置**：右側面板，`大戶逐筆` 下方新增 `爆量 1 分 K` 區塊（共用 sidebar 樣式）。

**列表預設顯示 4 欄**：

| 時間 | K | 價格 | 量（倍數）|
|------|---|------|----------|
| `10:35` | `▲` 紅 K（量增價漲）/ `▼` 綠 K（量增價跌）/ `─` 灰（十字星）| close 價格 + 漲跌色 | `2.3K張 (5.2×)` 倍數依 severity 上色 |

**Hover Tooltip 完整資訊**：
```
10:35:00 ~ 10:35:59
─────────────────────
開 611.0  →  收 612.0  (+0.16%)
高 612.5     低 610.5
─────────────────────
成交量    2,341 張
成交額    143.2M
VWAP      611.8
筆數      87 筆
─────────────────────
基準量    450 張
倍數      5.2×  HIGH 🔥
─────────────────────
```

**列表上限**：20 筆（最新 20 根爆量 K 棒）

**空狀態**：顯示「尚無爆量」

### 1.6 K 線圖標記

- 僅 1 分 K 週期（`KlinePeriod.MIN_1`）時啟用
- 量柱色：依 severity 變色 + 加深邊框
- 價格區：plotly annotation 小三角 + 倍數文字（如 `5.2×`）

### 1.7 通知機制

- 瀏覽器原生 `Notification API`
- 觸發條件：`severity >= HIGH`（≥ 5× 才推播，避免太吵）
- 標題：`⚡ 2330 爆量 5.2×`
- 內文：`10:35 612.0 +0.16% 2,341張`
- `tag = stock_id + timestamp_iso`（avoid duplicate）
- 盤後不推送（交易時段判斷沿用 `Scheduler.is_market_open`）
- 首次載入要求權限：`Notification.requestPermission()`

---

## 2. 資料模型

### 2.1 新增 Enum

```python
# src/models.py
class SpikeSeverity(Enum):
    NORMAL = "normal"
    LOW = "low"
    MID = "mid"
    HIGH = "high"
    EXTREME = "extreme"

    @property
    def display_name(self) -> str:
        names = {
            SpikeSeverity.LOW: "LOW",
            SpikeSeverity.MID: "MID",
            SpikeSeverity.HIGH: "HIGH 🔥",
            SpikeSeverity.EXTREME: "EXTREME 💥",
        }
        return names.get(self, "")
```

### 2.2 新增 Dataclass

```python
# src/models.py
@dataclass
class MinuteKBar:
    stock_id: str
    timestamp: datetime          # K 棒起始時間 (09:00, 09:01...)
    open: float
    high: float
    low: float
    close: float
    volume: int                  # 該分鐘成交張數
    amount: float                # 該分鐘成交金額（TWD）
    tick_count: int              # 該分鐘內成交筆數
    vwap: float                  # amount / (volume * 1000)

    # 偵測結果（由 detector 填入）
    baseline_volume: Optional[float] = None
    volume_ratio: Optional[float] = None
    is_volume_spike: bool = False
    spike_severity: SpikeSeverity = SpikeSeverity.NORMAL
    baseline_low_confidence: bool = False
    price_direction: PriceDirection = PriceDirection.FLAT

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "MinuteKBar": ...

@dataclass
class StockMinuteKFile:
    stock_id: str
    stock_name: str
    date: date
    bars: List[MinuteKBar] = field(default_factory=list)

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "StockMinuteKFile": ...
```

### 2.3 檔案儲存

```
data/minute_kbars/{stock_id}_{yyyymmdd}.json
```

格式：
```json
{
  "stock_id": "2330",
  "stock_name": "台積電",
  "date": "2026-05-16",
  "bars": [MinuteKBar.to_dict(), ...]
}
```

---

## 3. Task 列表與進度

> **規則**：每完成一個 task → 更新本表狀態 → 透過 `git-branch-commit-manager` agent 提交並推送 → 才執行下一個 task。

| # | Task | 狀態 | 預估 |
|---|------|------|------|
| 1 | 新增 MinuteKBar / SpikeSeverity / StockMinuteKFile 資料模型 | ✅ completed | 30m |
| 2 | minute_kbar_storage 模組（原子寫入 + 同時段查詢）| ✅ completed | 1h |
| 3 | Shioaji kbars 整合 + IntradayTick 聚合 fallback | ✅ completed | 2h |
| 4 | 爆量偵測核心（混合 baseline + severity 分級）| ✅ completed | 2h |
| 5 | Warmup 機制：首次載入股票 backfill 5 日 1 分 K | ✅ completed | 1h |
| 6 | Scheduler 每分鐘排程偵測 | ✅ completed | 1h |
| 7 | UI: 大戶逐筆下方新增爆量 K 棒面板 | ✅ completed | 1h |
| 8 | UI: hover tooltip + severity 配色 CSS | ✅ completed | 1.5h |
| 9 | Callback: 爆量面板資料更新 | ✅ completed | 1h |
| 10 | K 線圖（1 分 K）爆量根標記 | ✅ completed | 2h |
| 11 | 瀏覽器 Notification API 推播 | ✅ completed | 2h |
| 12 | 單元測試：detector + storage + parser | ⬜ pending | 2h |

**狀態圖示**：⬜ pending / 🟡 in_progress / ✅ completed / ❌ blocked

**進度**：11 / 12（92%）

---

## 4. Task 詳細規格

> 每個 task 都包含：**目標 / 檔案 / 介面 / 實作步驟 / 完成條件 / 注意事項**

---

### Task 1 — 新增資料模型

**目標**：在 `src/models.py` 加入 `SpikeSeverity` enum、`MinuteKBar` dataclass、`StockMinuteKFile` dataclass，含 `to_dict()` / `from_dict()` 方法。

**檔案**：
- `src/models.py`（修改）

**介面**：
```python
class SpikeSeverity(Enum):
    NORMAL = "normal"; LOW = "low"; MID = "mid"; HIGH = "high"; EXTREME = "extreme"

    @property
    def display_name(self) -> str: ...

@dataclass
class MinuteKBar:
    # 詳見 §2.2
    ...

@dataclass
class StockMinuteKFile:
    # 詳見 §2.2
    ...
```

**實作步驟**：
1. 在 `src/models.py` 檔案結尾加 `# ─── Volume Spike Detection ─────`分隔線
2. 新增 `SpikeSeverity` enum，含 `display_name` property
3. 新增 `MinuteKBar` dataclass：
   - 含 `__post_init__` 驗證 `high >= max(open, close)`、`low <= min(open, close)`、`volume >= 0`
   - `to_dict()`：`timestamp.isoformat()`、enum 用 `.value`
   - `from_dict()`：反向解析；`spike_severity` 用 `SpikeSeverity(data.get("spike_severity", "normal"))`
4. 新增 `StockMinuteKFile` dataclass：仿 `StockIntradayFile` 結構

**完成條件**：
- `python -c "from src.models import MinuteKBar, SpikeSeverity, StockMinuteKFile"` 無錯
- 寫一個 mini smoke test：建 `MinuteKBar` 物件 → `to_dict()` → `from_dict()` round-trip 一致

**注意事項**：
- OHLC 驗證邏輯參考 `DailyOHLC.__post_init__`
- 時區處理：`timestamp` 必須帶 tzinfo（Asia/Taipei）
- 不在此 task 寫測試，留到 Task 12

**Commit message**：`feat(models): add MinuteKBar + SpikeSeverity for volume spike detection`

---

### Task 2 — minute_kbar_storage 模組

**目標**：建立 1 分 K 檔案 I/O 模組，提供原子寫入、讀取、同時段歷史查詢。

**檔案**：
- `src/storage/minute_kbar_storage.py`（新建）

**介面**：
```python
class MinuteKBarStorage:
    def __init__(self, data_dir: Path = Path("data/minute_kbars")): ...

    def save(self, file: StockMinuteKFile) -> None:
        """原子寫入：先寫 .tmp 再 os.replace。"""

    def load(self, stock_id: str, target_date: date) -> Optional[StockMinuteKFile]:
        """讀取某日所有 1 分 K。找不到回傳 None。"""

    def append_bar(self, stock_id: str, stock_name: str, bar: MinuteKBar) -> None:
        """追加單根 K 棒到當日檔案。需 locking 避免並發寫入。"""

    def load_same_time_bars(
        self, stock_id: str, target_time: time, days: int = 5,
        end_date: Optional[date] = None
    ) -> List[MinuteKBar]:
        """讀取過去 N 個交易日同一分鐘的 K 棒。end_date 預設今天。
        跳過週末、不存在的檔案。回傳依日期由近至遠排序。"""

    def load_recent_bars(
        self, stock_id: str, target_date: date,
        before_timestamp: datetime, n: int = 20
    ) -> List[MinuteKBar]:
        """讀取當日 before_timestamp 之前最近 N 根 K 棒。"""
```

**實作步驟**：
1. 仿 `src/storage/data_storage.py` 的原子寫入模式
2. `save()`：寫入 `{data_dir}/{stock_id}_{date:YYYYMMDD}.json.tmp` → `os.replace()`
3. `load()`：`json.load()` → `StockMinuteKFile.from_dict()`；損毀時備份到 `data/backup/` 並回傳 `None`
4. `append_bar()`：load → append → save；用 `threading.Lock` 保護（key by `stock_id+date`）
5. `load_same_time_bars()`：迭代日期回推，跳週末（`weekday() < 5`），逐檔案讀取找 `bar.timestamp.time() == target_time`
6. `load_recent_bars()`：load 當日 → filter `bar.timestamp < before_timestamp` → sort → 取最後 N 根
7. 磁碟空間檢查：寫入前用 `shutil.disk_usage()` 確認，< 100MB 拋 `DiskSpaceError`

**完成條件**：
- 模組可 import
- 手動 smoke test：建立 `MinuteKBar` → `save()` → `load()` round-trip
- 模擬連 7 日資料，`load_same_time_bars(stock_id, time(10,35), days=5)` 應回傳 5 筆

**注意事項**：
- 並發安全：用 `threading.Lock`（dict by stock_id_date），避免 scheduler 與 backfill 同時寫入
- 損毀處理：JSON parse 失敗 → 備份原檔到 `data/backup/{stock_id}_{date}_{ts}.json.corrupted` → 回傳 `None`
- 不在此 task 寫測試

**Commit message**：`feat(storage): add MinuteKBarStorage with atomic writes + same-time-slot query`

---

### Task 3 — Shioaji kbars 整合 + tick 聚合 fallback

**目標**：擴充 `ShioajiFetcher` 取得 1 分 K 棒，失敗時退回 `IntradayTick` 累計量差分聚合。

**檔案**：
- `src/fetcher/shioaji_fetcher.py`（修改）

**介面**：
```python
class ShioajiFetcher:
    def fetch_minute_kbars(
        self, stock_id: str, target_date: date,
        start_time: Optional[time] = None,
        end_time: Optional[time] = None
    ) -> List[MinuteKBar]:
        """從 Shioaji kbars API 取得 1 分 K。
        若 API 失敗，退回 _aggregate_from_ticks。"""

    def _aggregate_from_ticks(
        self, stock_id: str, target_date: date,
        ticks: List[IntradayTick]
    ) -> List[MinuteKBar]:
        """從逐筆 tick 聚合為 1 分 K。
        - 以 tick.time 的分鐘為 key 分桶
        - OHLC: open=第一筆 price, high=max, low=min, close=最後一筆
        - volume: sum
        - amount: sum(price * volume * 1000)
        - tick_count: len
        - vwap: amount / (volume * 1000)
        """
```

**實作步驟**：
1. Shioaji API 呼叫：`self.api.kbars(contract, start=date, end=date)`
2. 回傳結構是 `pandas.DataFrame` 風格，欄位含 `ts, Open, High, Low, Close, Volume, Amount`
3. 將 DataFrame 轉為 `List[MinuteKBar]`，timestamp 帶 `Asia/Taipei` tz（現有檔案有 `_TZ_TAIPEI` 可用）
4. 計算 `vwap = amount / (volume * 1000)`，`volume == 0` 時 vwap = close
5. `tick_count` 在 Shioaji kbars 沒提供 → 設 0（標記 from_kbars），或從同日 ticks 補
6. fallback：try/except `Exception`（包含 `ShioajiError`、network），失敗時呼叫 `_aggregate_from_ticks`
7. `_aggregate_from_ticks`：用 `itertools.groupby` 或 dict 分桶，key = `(time.hour, time.minute)`
8. 過濾交易時段：只保留 09:00 ≤ time ≤ 13:30 的 K 棒

**完成條件**：
- `fetch_minute_kbars("2330", date.today())` 在交易日回傳 ≥ 1 根 K 棒
- 模擬 Shioaji API 失敗（mock），驗證 fallback 走 `_aggregate_from_ticks`

**注意事項**：
- Shioaji API 有 quota 限制，warmup 用（Task 5）
- 時區：Shioaji 回傳 `ts` 可能是 epoch 毫秒或 datetime，沿用現有 `_normalize_timestamp` 邏輯
- 模擬環境（sim）可能無 kbars 資料，需用 prod 或本地 fixture 測試
- `tick_count` 缺失時用 0；UI 顯示「-」即可

**Commit message**：`feat(shioaji): add minute kbars fetch + tick aggregation fallback`

---

### Task 4 — 爆量偵測核心演算法

**目標**：實作混合 baseline 計算與 spike severity 分級，輸入 `MinuteKBar` 輸出填入偵測結果。

**檔案**：
- `src/processor/volume_spike_detector.py`（新建）
- `src/config.py`（修改：加 SPIKE_* 常數）

**介面**：
```python
class VolumeSpikeDetector:
    def __init__(self, storage: MinuteKBarStorage, events_provider: Optional[Callable] = None):
        """events_provider: 給 stock_id, date 回傳當日是否為除權息日。"""

    def detect(self, bar: MinuteKBar) -> MinuteKBar:
        """對單根 K 棒執行偵測，回傳填入偵測結果的新 MinuteKBar。
        - 0 量 / 除權息日 → 直接回傳 (NORMAL)
        - 計算 baseline (混合法)
        - 計算 ratio, severity
        - 套用絕對量門檻
        """

    def _compute_baseline(self, bar: MinuteKBar) -> Tuple[Optional[float], bool]:
        """回傳 (baseline, low_confidence)。
        法 B 優先，失敗退法 A。皆失敗回 (None, True)。"""

    def _classify_severity(self, ratio: float, volume: int) -> SpikeSeverity:
        """依 threshold 分級。volume < MIN_ABS_VOLUME 強制 NORMAL。"""
```

**實作步驟**：
1. `src/config.py` 加入 SPIKE_* 常數（見 §1.2）
2. `_compute_baseline`：
   - 法 B：`storage.load_same_time_bars(bar.stock_id, bar.timestamp.time(), days=SPIKE_BASELINE_DAYS)`
   - 若 `len(historical) >= SPIKE_BASELINE_MIN_DAYS`：去極值（≥ 5 筆才掐頭去尾，否則直接均值）→ 回 `(mean, False)`
   - 否則法 A：`storage.load_recent_bars(stock_id, date, bar.timestamp, n=SPIKE_FALLBACK_WINDOW)`
   - 排除前 `SPIKE_FALLBACK_SKIP_OPENING` 根（依 timestamp 排序後跳過）
   - 過濾 `volume > 0`
   - 若有資料 → 回 `(mean, True)`；否則 `(None, True)`
3. `_classify_severity`：
   - `volume < SPIKE_MIN_ABS_VOLUME` → NORMAL
   - `ratio >= EXTREME (10.0)` → EXTREME
   - `>= HIGH (5.0)` → HIGH
   - `>= MID (3.0)` → MID
   - `>= LOW (2.0)` → LOW
   - else NORMAL
4. `detect`：
   - `volume == 0` → 回原物件
   - 除權息日（透過 `events_provider`）→ 回原物件
   - 計算 baseline；`baseline is None or baseline == 0` → NORMAL
   - `ratio = volume / baseline`
   - 填入 `baseline_volume, volume_ratio, is_volume_spike, spike_severity, baseline_low_confidence`
   - `is_volume_spike = (severity != NORMAL)`
   - 同時設 `price_direction`：close vs open
5. 除權息整合：從 `src/data/events.py` 提供函式（若無則先傳 `None`，後續再接）

**完成條件**：
- 模組可 import
- Smoke test：mock storage，模擬 5 日同時段量 [100, 110, 120, 90, 105]，新 bar volume=600 → ratio≈5.4 → HIGH
- volume=50 (< 100) → NORMAL（被絕對量門檻擋）

**注意事項**：
- baseline 可能為 0（連 5 日都 0 量）→ 視為無法判定，回 NORMAL + low_confidence
- 去極值前要排序，且須 `volume > 0` 才納入
- detector 不該有副作用（不寫檔），純函式風格

**Commit message**：`feat(processor): add VolumeSpikeDetector with hybrid baseline algorithm`

---

### Task 5 — Warmup 機制：歷史 backfill

**目標**：首次追蹤新股票時，背景抓取過去 5 個交易日 1 分 K 棒，建立 baseline 基礎。

**檔案**：
- `src/app/app_controller.py`（修改）
- `src/fetcher/minute_kbar_warmup.py`（新建，可選獨立模組）

**介面**：
```python
class MinuteKBarWarmup:
    def __init__(self, fetcher: ShioajiFetcher, storage: MinuteKBarStorage): ...

    def needs_warmup(self, stock_id: str) -> bool:
        """檢查近 5 個交易日資料是否齊全（>= 3 日即視為夠）。"""

    def warmup_async(self, stock_id: str) -> threading.Thread:
        """背景 thread 抓取近 5 個交易日 1 分 K 並存檔。
        返回 thread object（caller 不必 join）。"""

    def _backfill_day(self, stock_id: str, target_date: date) -> int:
        """抓單日並存檔，回傳存入的 bar 數。"""
```

**實作步驟**：
1. `needs_warmup`：迭代過去 7 個日曆日（避開週末），呼叫 `storage.load()`，計數有資料的天數，< `SPIKE_BASELINE_MIN_DAYS` 時回 `True`
2. `warmup_async`：建 daemon thread 跑 `_warmup_sync`
3. `_warmup_sync`：迭代過去 5 個交易日，逐日呼叫 `_backfill_day`
4. `_backfill_day`：`fetcher.fetch_minute_kbars(stock_id, day)` → 包成 `StockMinuteKFile` → `storage.save()`
5. 已有資料的日子跳過（`storage.load() is not None`）
6. AppController 偵測新追蹤股票時呼叫 `warmup.warmup_async(stock_id)`
7. 整合點：使用者搜尋股票時、加入我的最愛時觸發

**完成條件**：
- 對 `2330` 呼叫 `warmup_async()`，2 分鐘內 `data/minute_kbars/` 出現 5 個檔案
- 第二次呼叫 `needs_warmup("2330")` 應回 `False`

**注意事項**：
- Shioaji API quota：一次 warmup 5 個 API call，多檔股票同時 warmup 要 rate limit（每秒 ≤ 2 call）
- 失敗的日子不要 retry 死循環，最多 retry 1 次
- daemon thread：應用結束時不卡住
- log 標記為 `[warmup]` 方便除錯

**Commit message**：`feat(warmup): backfill 5-day minute kbars on stock first-load`

---

### Task 6 — Scheduler 每分鐘排程

**目標**：在交易時段內每分鐘執行爆量偵測，將結果寫入記憶體 store 供 UI 取用。

**檔案**：
- `src/scheduler/scheduler.py`（修改）
- `src/app/app_controller.py`（修改：建立 detection_store）

**介面**：
```python
class VolumeSpikeJob:
    def __init__(
        self,
        fetcher: ShioajiFetcher,
        storage: MinuteKBarStorage,
        detector: VolumeSpikeDetector,
        detection_store: "SpikeDetectionStore",
        tracked_stocks_provider: Callable[[], List[str]],
    ): ...

    def run_once(self) -> None:
        """對每個追蹤股票，抓上一分鐘 K → 偵測 → 寫 store。"""

class SpikeDetectionStore:
    """執行緒安全的 in-memory store：{stock_id: deque[MinuteKBar(spike)]}, max=20。"""

    def add_spike(self, stock_id: str, bar: MinuteKBar) -> None: ...
    def get_recent(self, stock_id: str, n: int = 20) -> List[MinuteKBar]: ...
    def clear(self, stock_id: str) -> None: ...
```

**實作步驟**：
1. 新增 `SpikeDetectionStore` 在 `src/app/app_controller.py` 或新檔 `src/data/spike_store.py`
   - 使用 `collections.deque(maxlen=20)`
   - `threading.Lock` 保護
2. `VolumeSpikeJob.run_once`：
   - 取 `tracked_stocks_provider()` 列表
   - 對每檔：
     - `target_minute = now().replace(second=0, microsecond=0) - timedelta(minutes=1)`
     - 抓上一分鐘 K：`fetcher.fetch_minute_kbars(stock_id, today, target_minute, target_minute)`
     - 若有結果：`storage.append_bar()` → `detector.detect()` → 若 `is_volume_spike`，`detection_store.add_spike()`
3. APScheduler 加 `cron` job：`minute='*', second=5`（每分鐘第 5 秒，讓券商資料先到位）
4. 交易時段判斷：`scheduler.is_market_open()` False → 跳過
5. 失敗計數整合（沿用現有機制）

**完成條件**：
- 啟動應用、進入交易時段、追蹤某檔股票
- 1 分鐘後 log 出現 `[spike_job] checked 2330`
- 模擬爆量資料 → `detection_store.get_recent("2330")` 回傳 spike list

**注意事項**：
- `second=5` 避開券商資料延遲；若仍取不到，30 秒後 retry
- tracked_stocks：目前應用追蹤股票來源可能是「我的最愛」+「當前查看股票」
- 此 job 不該擋住其他 scheduler job，例外要 catch

**Commit message**：`feat(scheduler): add per-minute volume spike detection job`

---

### Task 7 — UI: 爆量面板 layout

**目標**：在 `src/app/layout.py` 大戶逐筆下方新增爆量 1 分 K 面板。

**檔案**：
- `src/app/layout.py`（修改）

**介面**：
```python
def _create_volume_spike_panel() -> html.Div:
    """爆量 1 分 K 面板。
    結構：title row + 4-col header + 列表 + interval.
    """
```

**實作步驟**：
1. 在 `_create_big_orders_tape` 函式定義下方新增 `_create_volume_spike_panel`
2. 結構：
   ```python
   html.Div(
       id="volume-spike-panel",
       className="volume-spike-panel",
       children=[
           html.Div(
               className="sidebar-section-title-row",
               children=[
                   html.H3("爆量 1 分 K", className="sidebar-title"),
                   html.Span("≥2×", className="pill pill-neu sidebar-title-pill"),
               ],
           ),
           html.Div(
               className="volume-spike-header",
               children=[
                   html.Span("時間", className="vs-col-time"),
                   html.Span("K", className="vs-col-kbar"),
                   html.Span("價格", className="vs-col-price"),
                   html.Span("量(倍)", className="vs-col-vol"),
               ],
           ),
           html.Div(
               id="volume-spike-list",
               className="volume-spike-list",
               children=[html.Div("尚無爆量", className="no-data")],
           ),
           dcc.Interval(
               id="volume-spike-interval",
               interval=60_000,  # 60s
               n_intervals=0,
           ),
       ],
   )
   ```
3. 在 sidebar 主容器內插入 `_create_volume_spike_panel()`，位於 `_create_big_orders_tape()` 之後
4. 將 `volume_spike_panel`、`volume_spike_list`、`volume_spike_interval` 加入檔案結尾的 `ELEMENT_IDS` 對應 dict

**完成條件**：
- 應用啟動，右側面板大戶逐筆下方可見「爆量 1 分 K」標題與「尚無爆量」占位
- 瀏覽器 DevTools 找得到 `#volume-spike-panel`、`#volume-spike-list`、`#volume-spike-interval`

**注意事項**：
- 不在此 task 做樣式（CSS 在 Task 8）
- 不接 callback（在 Task 9）
- 注意現有 sidebar 結構順序

**Commit message**：`feat(layout): add volume spike panel below big orders tape`

---

### Task 8 — UI: hover tooltip + 配色 CSS

**目標**：實作每列 hover 顯示完整 K 棒資訊；severity 配色。

**檔案**：
- `src/app/assets/style.css`（修改）
- `src/app/layout.py`（可能需調整列結構支援 tooltip）

**實作步驟**：
1. CSS 新增（建議獨立區塊 `/* ─── Volume Spike Panel ─── */`）：
   ```css
   .volume-spike-panel { /* 仿 .big-orders-tape padding/border */ }
   .volume-spike-header { display: grid; grid-template-columns: 56px 32px 1fr 1fr; ... }
   .volume-spike-row { display: grid; ...; position: relative; cursor: help; }
   .volume-spike-row:hover .vs-tooltip { display: block; }

   .vs-severity-low    { color: #FFEB3B; }
   .vs-severity-mid    { color: #FF9800; }
   .vs-severity-high   { color: #EF5350; }
   .vs-severity-extreme { color: #9C27B0; font-weight: bold; }

   .vs-kbar-up   { color: #EF5350; }   /* 紅 K 量增價漲 */
   .vs-kbar-down { color: #26A69A; }   /* 綠 K 量增價跌 */
   .vs-kbar-flat { color: #999; }

   .vs-tooltip {
     display: none;
     position: absolute;
     right: 100%;
     top: 0;
     background: #2A2A2A;
     border: 1px solid #444;
     padding: 8px 12px;
     z-index: 100;
     min-width: 240px;
     white-space: pre-line;
     font-family: monospace;
   }
   ```
2. Tooltip 內容由 callback 生成（Task 9），CSS 只負責顯示/隱藏
3. 列結構（callback 會產出）：
   ```html
   <div class="volume-spike-row">
     <span class="vs-col-time">10:35</span>
     <span class="vs-col-kbar vs-kbar-up">▲</span>
     <span class="vs-col-price vs-kbar-up">612.0</span>
     <span class="vs-col-vol vs-severity-high">2.3K (5.2×)</span>
     <div class="vs-tooltip">...full info...</div>
   </div>
   ```

**完成條件**：
- 滑鼠移到列上 tooltip 顯示，移開消失
- 不同 severity 顏色正確

**注意事項**：
- 用純 CSS hover，不依賴 JS
- tooltip 不要遮到大戶逐筆面板（位置可改 `left: -260px`）
- 黑底白字確保深色主題易讀

**Commit message**：`style(spike): hover tooltip + severity color palette`

---

### Task 9 — Callback: 爆量面板資料更新

**目標**：實作 callback，將 `SpikeDetectionStore` 的資料渲染為列表。

**檔案**：
- `src/app/callbacks.py`（修改）

**介面**：
```python
@callback(
    Output("volume-spike-list", "children"),
    Input("volume-spike-interval", "n_intervals"),
    Input("current-stock-store", "data"),  # 現有 store
)
def update_volume_spike_panel(n, stock_data):
    """讀 detection_store → 渲染 20 筆爆量 K 棒列表。"""
```

**實作步驟**：
1. 在 `CallbackManager.register_all()` 加入
2. 從 `stock_data` 取 `stock_id`，若無則回傳「請選擇股票」
3. `bars = self.detection_store.get_recent(stock_id, n=20)`
4. 空時回傳 `html.Div("尚無爆量", className="no-data")`
5. 否則迭代產出列表：
   ```python
   rows = []
   for bar in bars:
       severity_cls = f"vs-severity-{bar.spike_severity.value}"
       kbar_cls = (
           "vs-kbar-up" if bar.close > bar.open
           else "vs-kbar-down" if bar.close < bar.open
           else "vs-kbar-flat"
       )
       kbar_icon = "▲" if bar.close > bar.open else "▼" if bar.close < bar.open else "─"
       tooltip = build_tooltip_text(bar)  # 見下
       rows.append(html.Div(
           className="volume-spike-row",
           children=[
               html.Span(bar.timestamp.strftime("%H:%M"), className="vs-col-time"),
               html.Span(kbar_icon, className=f"vs-col-kbar {kbar_cls}"),
               html.Span(f"{bar.close:.2f}", className=f"vs-col-price {kbar_cls}"),
               html.Span(f"{format_volume(bar.volume)} ({bar.volume_ratio:.1f}×)", className=f"vs-col-vol {severity_cls}"),
               html.Div(tooltip, className="vs-tooltip"),
           ],
       ))
   ```
6. `build_tooltip_text(bar)` 回傳多行字串（CSS `white-space: pre-line`）：
   ```
   10:35:00 ~ 10:35:59
   ─────────────────────
   開 611.0  →  收 612.0  (+0.16%)
   高 612.5     低 610.5
   ─────────────────────
   成交量    2,341 張
   成交額    143.2M
   VWAP      611.8
   筆數      87 筆
   ─────────────────────
   基準量    450 張
   倍數      5.2×  HIGH 🔥
   ─────────────────────
   ```
7. `format_volume`：≥ 1000 顯示 `2.3K`，否則 `234`
8. CallbackManager 建構子需接收 `detection_store`（修改 AppController 注入）

**完成條件**：
- 模擬塞入 spike → UI 列表顯示對應筆數
- 換股票 → 列表更新
- 60 秒間隔自動 refresh

**注意事項**：
- `dash.no_update`：未變更時不必更新
- callback exception 要 log，不要讓整頁壞掉
- volume_ratio 若 None（baseline 不可用）顯示 `—×`

**Commit message**：`feat(callback): wire volume spike panel with detection store`

---

### Task 10 — K 線圖爆量根標記

**目標**：在 1 分 K 線圖上將爆量 K 棒量柱改色 + 加倍數 annotation。

**檔案**：
- `src/renderer/chart_renderer.py`（修改）
- `src/renderer/chart_colors.py`（修改：加 SPIKE_* 色碼）

**實作步驟**：
1. `chart_colors.py` 加入：
   ```python
   SPIKE_LOW = "#FFEB3B"
   SPIKE_MID = "#FF9800"
   SPIKE_HIGH = "#EF5350"
   SPIKE_EXTREME = "#9C27B0"
   ```
2. `chart_renderer.py` `render_kline_chart()` 函式（或對應名稱）：
   - 接收 `bars: List[MinuteKBar]` 參數（或從 daily OHLC 轉，需 caller 端配合提供）
   - 僅 `period == KlinePeriod.MIN_1` 時啟用
   - 計算量柱顏色 list：
     ```python
     volume_colors = [
         SPIKE_EXTREME if b.spike_severity == SpikeSeverity.EXTREME
         else SPIKE_HIGH if b.spike_severity == SpikeSeverity.HIGH
         else SPIKE_MID if b.spike_severity == SpikeSeverity.MID
         else SPIKE_LOW if b.spike_severity == SpikeSeverity.LOW
         else (UP_COLOR if b.close > b.open else DOWN_COLOR)
         for b in bars
     ]
     ```
   - 量柱 trace 用 `marker.color = volume_colors`，spike 量柱加 `marker.line.width=1.5`
3. Annotation：對每個 `is_volume_spike` 的 bar，於價格 subplot 加 annotation：
   ```python
   fig.add_annotation(
       x=bar.timestamp,
       y=bar.high * 1.005,
       text=f"{bar.volume_ratio:.1f}×",
       showarrow=True,
       arrowhead=2,
       arrowsize=0.8,
       font={"color": severity_color, "size": 10},
       row=1, col=1,
   )
   ```
4. 上限：annotation 太多會擠，>20 個 spike 時只標 severity >= MID

**完成條件**：
- 1 分 K 圖載入含爆量資料時，量柱有對應 severity 色
- 對應 K 棒上方出現小三角 + 倍數文字
- 切到 5 分 K / 日 K → 標記消失

**注意事項**：
- 1 分 K 圖目前資料源若是 IntradayTick → 需改用 MinuteKBar，或在 renderer 內呼叫 detector 重算
- 為避免重算，建議 callback 傳已偵測過的 `List[MinuteKBar]` 進來
- annotation 不要遮到 MA 線

**Commit message**：`feat(chart): mark volume spike bars on 1min kline`

---

### Task 11 — 瀏覽器 Notification 推播

**目標**：偵測到 severity ≥ HIGH 時，透過 Notification API 推播桌面通知。

**檔案**：
- `src/app/assets/spike_notification.js`（新建）
- `src/app/layout.py`（修改：加 dcc.Store）
- `src/app/callbacks.py`（修改：加 clientside callback）

**實作步驟**：
1. layout 加 `dcc.Store(id="spike-notification-store", data=None)`
2. clientside callback：
   ```python
   app.clientside_callback(
       """
       function(data) {
           if (!data || !data.title) return window.dash_clientside.no_update;
           if (!('Notification' in window)) return window.dash_clientside.no_update;
           if (Notification.permission === 'default') {
               Notification.requestPermission();
               return window.dash_clientside.no_update;
           }
           if (Notification.permission !== 'granted') return window.dash_clientside.no_update;
           new Notification(data.title, {
               body: data.body,
               icon: data.icon || '/assets/favicon.ico',
               tag: data.tag,
               requireInteraction: false,
           });
           return window.dash_clientside.no_update;
       }
       """,
       Output("spike-notification-store", "data", allow_duplicate=True),
       Input("spike-notification-store", "data"),
       prevent_initial_call=True,
   )
   ```
3. server-side callback：每分鐘從 `detection_store` 取最新 spike，若 severity ≥ HIGH 且 timestamp 為「最近 90 秒內」（避免歷史誤觸發）→ 寫入 `spike-notification-store`
4. 通知內容：
   ```python
   {
       "title": f"⚡ {stock_id} 爆量 {ratio:.1f}×",
       "body": f"{time_str} {close:.2f} {pct:+.2%} {volume:,}張",
       "tag": f"{stock_id}_{timestamp.isoformat()}",
   }
   ```
5. 盤後判斷：`scheduler.is_market_open()` False → 不推
6. 首次載入：另一個 clientside callback 觸發 `Notification.requestPermission()`（onLoad）

**完成條件**：
- 模擬 HIGH spike → 桌面出現通知
- 同一筆 spike 不重複推（`tag` 機制）
- 拒絕權限後不再嘗試
- 盤後不推

**注意事項**：
- 瀏覽器需 HTTPS 或 localhost 才能用 Notification（dev 環境 localhost OK）
- iOS Safari 不支援，需 graceful degradation
- 太頻繁的推送會被瀏覽器靜音，HIGH+ 已是合理過濾

**Commit message**：`feat(notification): browser push for HIGH+ volume spikes`

---

### Task 12 — 單元測試

**目標**：覆蓋 detector + storage + parser 核心邏輯。

**檔案**：
- `tests/test_processor/test_volume_spike_detector.py`（新建）
- `tests/test_storage/test_minute_kbar_storage.py`（新建）
- `tests/test_fetcher/test_minute_kbar_aggregation.py`（新建）

**測試案例**：

**detector**:
- 法 B 5 日齊全 → 用法 B
- 法 B 僅 2 日（< MIN_DAYS）→ 退法 A
- 法 A 也無資料 → baseline=None → NORMAL
- volume=0 → NORMAL（直接跳過）
- volume < 100 → NORMAL（絕對量擋）
- ratio=2.5 → LOW
- ratio=4.0 → MID
- ratio=6.0 → HIGH
- ratio=15.0 → EXTREME
- 除權息日 → NORMAL（mock events_provider 回 True）
- 去極值：[100, 110, 1000, 90, 105] → trimmed [100, 105, 110] mean=105

**storage**:
- save → load round-trip
- 損毀檔備份到 data/backup/
- load_same_time_bars 跳過週末
- load_recent_bars 過濾 before_timestamp
- 並發 append_bar（執行緒安全）

**aggregation**:
- 從 ticks 聚合：3 筆 tick 在 10:35 → 1 根 MinuteKBar，OHLC 正確
- 跨分鐘 tick：5 筆橫跨 10:35 / 10:36 → 2 根
- 空 ticks → 空 list

**完成條件**：
- `pytest tests/test_processor/test_volume_spike_detector.py -v` 全綠
- `pytest --cov=src.processor.volume_spike_detector --cov-fail-under=90`

**Commit message**：`test: unit tests for volume spike detection + storage`

---

## 5. 執行流程約定

1. **開始 task**：本檔對應 task 狀態改 `🟡 in_progress`
2. **task 完成**：
   - 本檔狀態改 `✅ completed`
   - 更新進度數字（如 `3 / 12 (25%)`）
   - 透過 `git-branch-commit-manager` agent 執行 commit + push
   - **commit 必須包含本檔的進度更新**
3. **遇到 blocker**：狀態改 `❌ blocked`，並於本檔該 task 下方加 `> **Blocker**: ...` 區塊
4. **跨 task 依賴**：嚴格依序執行 1 → 12，不跳號（除非明確說明可平行）

---

## 6. 開放問題（後續討論）

- [ ] Threshold 是否要做 UI 可調？（目前寫死）
- [ ] 多檔股票同時追蹤時的推播頻率限制（rate limit）
- [ ] 是否需要記錄爆量歷史供回測使用？
- [ ] 5 分 K / 15 分 K 是否也要做爆量偵測？（目前只 1 分 K）
