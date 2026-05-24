# Handoff: 策略回測結果頁 (`/strategy`)

> 重新設計 autoFetchStock 量化交易研究平台的「策略回測結果」頁面。
> 這份資料夾是給 **Claude Code** 用來把設計實作到既有 codebase 的。

---

## 1. 這份檔案是什麼？（重要）

`Strategy Backtest.html` 是**設計參考稿**，不是要直接搬進 production。
它是一份用純 HTML/CSS/JS 做的「視覺與互動原型」，用來說明：

- 頁面長什麼樣（顏色、字體、間距、卡片佈局）
- 每個區塊裝什麼資訊、用什麼語氣
- 互動行為（hover、collapse、響應式）

**你的工作**是把這份設計**用既有 codebase 的元件庫重新實作一次**，而不是把 HTML 抄進去。
這個專案是 **Dash (Python)**，所以最終會是 `dash.html` / `dash.dcc` 元件 + CSS class，不是純 HTML。

## 2. 設計 Fidelity

**Hi-fi**。顏色、字體、間距、文案、互動都是最終版，請對齊到像素級。
所有 hex 色碼、字級、border-radius 等請參照 `Strategy Backtest.html` 的 `:root` CSS 變數區塊。

## 3. 目標檔案

實作目標：**`src/app/pages/strategy.py`** （Dash page）。
- 既有實作使用 `Dash + dash_table + dcc.Markdown`，已有 dark style。
- 全域 CSS 在 `src/app/assets/style.css`，新增 class 可以放這裡，命名前綴用 `strategy-`。

## 4. 元件 ID（必須保留，給測試用）

```
strategy-page              （root 容器）
strategy-page-verdict      （結論卡）
strategy-page-explainer    （頁面用途說明）
strategy-page-what-we-tested （回測設定卡）
strategy-page-metrics      （主要結果區）
strategy-page-recommendation （行動建議區）
strategy-page-details      （進階詳情 details）
strategy-page-empty        （無資料時的空狀態）
```

## 5. 頁面結構（由上而下）

| 順序 | 區塊                  | id                              | 內容重點                                                 |
|----|---------------------|----------------------------------|------------------------------------------------------|
| 1  | Page heading        | (在 `strategy-page` 內)            | eyebrow + 大標 + 副標                                    |
| 2  | **結論卡（hero）**       | `strategy-page-verdict`          | 一句 verdict + 為什麼 + 建議下一步；**5px 藍色左邊框**               |
| 3  | 這個頁面在做什麼            | `strategy-page-explainer`        | 2 段白話文                                              |
| 4  | 我們測試了什麼             | `strategy-page-what-we-tested`   | 策略類型 / 股票池 / 進出場規則 / 時間範圍 / 測試方式 + walk-forward 圖解 |
| 5  | 主要結果                | `strategy-page-metrics`          | 8 列 metric，每列：狀態點 + 中文名 + 數字 + 白話解讀 + PASS/警告/FAIL pill |
| 6  | 接下來該怎麼做             | `strategy-page-recommendation`   | 5 個 numbered 行動建議                                   |
| 7  | 進階詳情                | `strategy-page-details`          | `<details>` collapsed；內含 manifest table + markdown 完整報告 |
| 8  | 空狀態                 | `strategy-page-empty`            | 預設 `display:none`，無資料時顯示                              |

## 6. Design Tokens

直接從 `Strategy Backtest.html` `:root` 取，不要改：

### Colors
```
--bg:           #1a1a1a      頁面背景
--bg-2:         #1f1f1f      卡片背景（比頁面亮一階）
--surface:      #222222      內層卡片
--surface-2:    #2a2a2a      hover / 強調
--line:         #2e2e2e      邊框
--line-2:       #3a3a3a      hover 邊框

--ink:          #f5f5f5      主要文字
--ink-2:        #c8c8c8      次要文字
--ink-3:        #8a8a8a      說明文字
--ink-4:        #5a5a5a      微弱文字

--accent:       #6c8eff      藍：連結、強調、結論左邊框
--pass:         #4ade80      綠：PASS
--fail:         #f87171      紅：FAIL
--warn:         #facc15      黃：注意
```

### Typography
- 字族：`"Noto Sans TC", "Microsoft JhengHei", system-ui, -apple-system, sans-serif`
- 數字字族：`"IBM Plex Mono", ui-monospace, monospace`（class 名為 `.num`）
- 字級：page-title `26px/700`、verdict-headline `30px/700`、metric-value `20px/600`、body `14px/1.65`

### Spacing
- 區塊間距：`20px`（CSS var `--gap`）
- 卡片 padding：`22px 24px`
- max-width：`1100px` 置中

### Radius
- 大卡片 `10px`、內層 `6px`

## 7. 互動 / 行為

- `.card:hover { border-color: var(--line-2); }`（微亮）
- `#strategy-page-details`：用原生 `<details><summary>`，預設**摺疊**，summary 上的 ▶ 箭頭 open 時旋轉 90°
- 結論卡 hover **不改變**左邊框顏色（保持藍色）
- 不要 modal、不要 sidebar、不要內層 scroll 容器

## 8. 響應式

- ≥ 760px：兩欄 grid（verdict 兩個區塊並排、what-we-tested 兩欄）
- < 760px：全部改成單欄 stack；metric 改成 `dot / name → value → meaning` 三層
- 詳細 media query 在 HTML 檔尾

## 9. 資料來源（給 Claude Code 參考）

設計稿中的數字是**範例資料**。實作時請把這些位置改成從現有回測結果 dict / dataclass 讀進來。建議的資料介面（命名只是建議）：

```python
@dataclass
class BacktestResult:
    verdict: Literal["pass", "warn", "fail"]
    verdict_headline: str          # "❌ 策略目前沒有穩定獲利能力"
    verdict_reason: str            # 白話原因（含 markdown）
    verdict_action: str            # 白話建議下一步

    strategy_type: str             # "趨勢追蹤"
    universe_size: int             # 487
    universe_desc: str             # "市值前 500 大、近一年..."
    entry_rule: str                # 白話進場規則
    exit_rule: str                 # 白話出場規則
    test_range: tuple[date, date]
    walk_forward_windows: int      # 11

    metrics: list[Metric]          # 見下方
    recommendations: list[Reco]    # 見下方
    manifest: dict[str, str]       # 進階詳情的 key/value
    full_report_md: str            # markdown 字串，給 dcc.Markdown
    run_id: str
    finished_at: datetime

@dataclass
class Metric:
    name: str                      # "驗證期成交筆數"
    hint: str                      # "策略在『沒看過』的時段裡實際成交了幾次"
    value: str                     # "59"
    unit: str                      # "筆"
    status: Literal["pass", "warn", "fail"]
    status_label: str              # "PASS" / "注意" / "FAIL"
    meaning: str                   # 白話解讀
    sign: Literal["pos", "neg", "neutral"] = "neutral"  # 影響數字顏色

@dataclass
class Reco:
    title: str
    desc: str                      # 可含內嵌 <code>
```

## 10. ⚠️ 不要做的事

- ❌ 不要顯示內部 spec reference（V2 §X / `experiment_id` raw / 內部檔案路徑）
- ❌ 不要直接列原始 JSON / code-style 欄位名（如 `trade_count`、`oos_is_ratio`）
- ❌ 不要把整個頁面塞進固定高度 div 造成內層 scroll
- ❌ 不要用 modal / pop-up / sidebar
- ❌ 不要保留 HTML 原型裡的 topbar / breadcrumb（那只是讓設計檔自己可看，實際應用會由 layout shell 提供）

## 11. Walk-forward 視覺圖

`#strategy-page-what-we-tested` 內有一塊 walk-forward 滾動視窗的視覺化（11 條橫向 bar，每條都是「藍色學習段 + 綠色驗證段」沿時間軸向右滑）。
在 HTML 裡是用 vanilla JS 動態生成的（搜尋 `renderWF`）。
實作上可以用 Dash 端先計算每段的 offset/width，渲染成 `html.Div` 加 style，或乾脆用 `dash.dcc.Graph` 畫 plotly horizontal bar。

## 12. 檔案

- `Strategy Backtest.html` — 完整設計原型（含所有 CSS、互動）
- `preview.png` — 全頁截圖（進階詳情已展開）
- `README.md` — 本檔

---

## 13. 給 Claude Code 的 prompt 範本

把下面這段貼進 Claude Code：

```
請依照 design_handoff_strategy_backtest/ 裡的設計稿，
重寫 src/app/pages/strategy.py。

具體要求：
1. 讀 design_handoff_strategy_backtest/README.md 了解全貌、
   讀 Strategy Backtest.html 對照像素細節
2. 用 Dash 元件（html.Div / dcc.Markdown / html.Details / html.Summary）實作，
   不要直接把 HTML 當字串塞進 dangerously_set_inner_html
3. CSS 新增到 src/app/assets/style.css，class 全部加 strategy- 前綴
4. 必須保留 README.md §4 列的 8 個元件 ID
5. 設計稿中的範例資料改成從 BacktestResult dataclass 讀
   （介面定義在 README §9）；先寫一個 mock loader 回傳寫死的範例資料即可
6. 完成後跑一次 dash 啟動指令，確認沒有 callback 錯誤、空狀態能正確切換
```
