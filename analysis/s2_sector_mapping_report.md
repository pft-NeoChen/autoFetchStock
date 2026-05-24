# TASK-S2-SECTOR — Real TWSE Sector Mapping

- **Task spec**: `STRATEGY_REVIEW.md §E.2`
- **Source endpoints**: TWSE C_public.jsp ISIN
  - TSE (上市): `strMode=2`
  - TPEX (上櫃): `strMode=4`
- **Cache artifact**: `analysis/sector_map.json`（亦作為 sprint 2 後續 task 的 mapping 來源）
- **Implementation**: `src/universe/sector_mapping.py`

---

## 1. Mapping 統計

| 來源 | 條目數 |
|---|---:|
| TSE (strMode=2) | 1,079 |
| TPEX (strMode=4) | 888 |
| **合併** | **1,967** |

### 1.1 139 universe coverage

- **137 / 139 = 98.6%** lookup 成功
- **2 個 miss**：
  - `0050` — ETF（元大台灣50），不屬於上市/上櫃 industry 分類
  - `9110` — TDR 或股票存託憑證（同樣不屬於 industry）

兩個 miss 都是非個股工具，預期可從後續 momentum universe 排除。

### 1.2 139 universe 真實產業分布（27 unique）

| 產業 | 檔數 |
|---|---:|
| 電子零組件業 | 22 |
| 半導體業 | 21 |
| 光電業 | 12 |
| 通信網路業 | 12 |
| 生技醫療業 | 7 |
| 紡織纖維 | 6 |
| 其他業 | 6 |
| 電腦及週邊設備業 | 6 |
| 建材營造業 | 6 |
| 航運業 | 5 |
| 汽車工業 | 4 |
| 電機機械 | 3 |
| 化學工業 | 3 |
| 其他電子業 | 3 |
| 食品工業、電器電纜、金融保險業、居家生活、電子通路業、數位雲端、資訊服務業、文化創意業 | 各 2 |
| 塑膠工業、造紙工業、觀光餐旅、貿易百貨業、運動休閒 | 各 1 |

**平均 5.1 檔 / industry**（vs sprint 1 4-digit prefix heuristic 50 buckets / 平均 2.78 檔 / bucket）。

---

## 2. Sprint 1 E3 重評（in-sample only sanity check）

把 sprint 1 E3 momentum IC 改用真實 mapping 重算（同 139 universe / 同 4yr / 同 12-1m feature / 同 21d forward）：

| Variant | ic_mean | decile_spread | cost_adj decile_spread |
|---|---:|---:|---:|
| Raw | 0.0996 | 0.0453 | 0.0393 |
| **Heuristic** (sprint 1, 50 buckets) | 0.0834 | 0.0529 | 0.0469 |
| **Real** (27 industries) | **0.0333** | **0.0270** | **0.0210** |

### 觀察

1. **Sprint 1 heuristic 沒做有效中性化** — 50 buckets 中多為 singleton（單檔自成 bucket），sector-neutralize 等於 0；結果與 raw 接近甚至更高（4.69% > 3.93%）只是噪音浮動。
2. **真實 sector 神經化後 ic_mean 縮水 60%**（0.0834 → 0.0333），cost-adj spread 縮水 55%（4.69% → 2.10%）。
3. **Sprint 1 「alpha 非純 sector beta」結論破功**：把同產業（特別是半導體 21 檔、電子零組件 22 檔、光電 12 檔）放同 bucket 後，cross-sectional alpha 大部分被吸收 → momentum 主要在「半導體 vs 其他產業」等 sector beta，不是個股級 stock-picking。
4. **0.0333 in-sample 落在 §E.3 UNCERTAIN 區**（0.02 ~ 0.04）。Walk-forward OOS 通常進一步衰減 → 高機率落到 < 0.02 DEAD 區。

### 對 sprint 2 的影響

- TASK-S2-WALKFWD 仍要跑，得到正式 OOS verdict 才能套 §E.3 gate
- **預期 verdict 偏 UNCERTAIN / 偏 DEAD**：若 walk-forward 縮減比 in-sample 嚴重，E3 列 in-sample artifact，sprint 2 結束
- 若 OOS sector-neutral ic_mean 仍 ≥ 0.04（極不可能但有可能），才解鎖 PORTFOLIO + RANK-SE + UNIVERSE + BACKTEST

---

## 3. API 摘要

```python
from src.universe.sector_mapping import (
    fetch_twse_sectors,      # HTTP + persist
    load_sector_mapping,     # cache-first
    get_sector,              # lookup w/ "unknown" fallback
    parse_twse_sectors_html, # offline parser
)
```

- `load_sector_mapping(Path("analysis/sector_map.json"))` — 預設路徑，cache miss 自動 fetch 雙 endpoint
- `load_sector_mapping(cache, refresh=True)` — 強制重抓
- `load_sector_mapping(cache, sources=(URL,))` — 限定單一 URL（測試用）

---

## 4. 結論

- **DoD 達成**：mapping 持久化 + sector_neutral 接得起；7 個 unit tests 全綠（pytest 758/758）
- **意外收穫**：用真實 sector 重評 E3 in-sample IC，發現 sprint 1 的 sector-neutral PASS 大部分是 heuristic singleton bucket artifact；alpha 的「非 sector beta」性質被嚴重高估
- **下一 task**：TASK-S2-WALKFWD（用真實 mapping 跑 walk-forward IC + §E.3 gate verdict）
