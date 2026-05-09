# Handoff: autoFetchStock UX Redesign

## Overview
This package contains a complete UX redesign for **pft-NeoChen/autoFetchStock**, a Dash-based Taiwan stock real-time dashboard. It addresses 4 pain points identified in the original product:

| # | Pain | Solution |
|---|------|----------|
| 1 | 整體佈局過於擁擠、1400px 寬度限制 | 升級為 1920×1080 彈性 grid，提供 3 個 layout 變體（4-Pane / Chart-First / Dual-Stock） |
| 2 | 新聞列表純時間排序、無法快速定位重要資訊 | 提供 2 個變體：N1 事件時間軸、N2 影響力排序 Feed |
| 3 | AI 訊號燈 (利多/利空/中性) 視覺位置不明確 | 提供 3 個位置變體：a 側欄整合 / b 內嵌標題 / c 獨立分頁 |
| 4 | 缺少統合的 AI 顧問入口 | 新增 4 維度 AI 顧問（新聞 / 籌碼 / 基本面 / 技術面），2 個變體：右欄常駐 / 全頁畫布 |

## About the Design Files

The HTML files in this bundle (under `design/`) are **design references created in HTML/React** — high-fidelity interactive prototypes showing the intended look, density, and interaction model. They are **NOT production code to copy directly**.

Your task is to **recreate these designs in the existing autoFetchStock Dash codebase**, using:
- The current **Dash + Plotly** framework (`dash`, `dash.html`, `dcc`, `plotly.graph_objects`)
- The existing CSS architecture in `src/app/assets/style.css`
- The existing callback patterns in `src/app/callbacks/`
- The existing models in `src/models.py`

This is **incremental refactor**, not a rewrite. Preserve:
- The Taiwan stock color convention (紅漲綠跌 — Red=up, Green=down — DO NOT swap)
- The 4 MA line colors (MA5 orange / MA10 blue / MA20 pink / MA60 purple)
- The existing data fetching layer (`src/data/`)
- The existing chart rendering layer (`src/renderer/`)

## Fidelity

**High-fidelity (hifi)** — pixel-perfect with final colors, typography, spacing, density, and component states. Implement to match within ~4px tolerance.

## Recommended Implementation Combo

After reviewing all 10 variants, the recommended production combo is:

| Pain | Variant | Reason |
|---|---|---|
| #1 Layout | **A · 4-Pane (Bloomberg)** as default + **B · Chart-First** as a "當沖模式" toggle | A maximizes density for power users; B reduces cognitive load for casual viewing. Toggle in header. |
| #3 Signal | **a · Sidebar** (always-on) + **b · Inline** (selected stock) | Persistent watchlist context + immediate visual reinforcement. **c** is overkill. |
| #2 News | **N2 · Impact-ranked Feed** first, **N1 · Timeline** as a Phase 6 enhancement | N2 is shippable today with the existing news data + an `impact_score` field. N1 needs event clustering ML. |
| #4 AI | **AI-1 · Right Rail** as primary + **AI-2 · /advisor route** for deep dive | AI-1 is always visible during trading; AI-2 is a "research mode" page. |

## Document Index

| File | Purpose | Read When |
|---|---|---|
| **README.md** (this file) | Entry prompt for AI agent | First |
| **DESIGN_SPEC.md** | Full design spec — tokens, layout grids, component anatomy, every variant detailed | Before any implementation |
| **COMPONENT_MAP.md** | Maps each design variant to existing Dash components, CSS classes, callbacks, model fields | When starting a Phase |
| **IMPLEMENTATION_PLAN.md** | 6-phase roadmap with file-level checklists | To plan PRs |
| **PHASE_3_5_INFO_DENSITY.md** | ⚠️ Field-level component spec — must-have data for every panel | Phase 3.5 (✅ done) |
| **PHASE_3_6_VISUAL_REFINEMENT.md** | ⚠️ 11 visual / structural defects to fix after Phase 3.5 | Phase 3.6 (✅ done) |
| **PHASE_4_5_LAYOUT_B_SYNC.md** | ⚠️ Layout-B sync 計畫（即時看板 chart-first + 右欄 5-tab） | Phase 4.5 (✅ done) |
| **PHASE_4_6_BATCH_AI_SUMMARY.md** | ⚠️ Batch per-article AI summary（解決「AI 解讀」與標題重複） | Phase 4.6 (✅ done) |
| **tokens.css** | Drop-in CSS variables — append to or replace top of `src/app/assets/style.css` | Phase 1 |
| **design/** | HTML/JSX source of all variants | When confused about a detail |
| **reference/** | PNG screenshots of each artboard | Visual ground truth |

## Phase Progress Tracker (updated 2026-05-09)

| Phase | Status | Doc |
|---|---|---|
| 1 — Design Tokens Migration | ✅ DONE | `IMPLEMENTATION_PLAN.md` §Phase 1 |
| 2 — Layout Grid Upgrade | ✅ DONE | `IMPLEMENTATION_PLAN.md` §Phase 2 |
| 3 — Signal Strip | ✅ DONE | `IMPLEMENTATION_PLAN.md` §Phase 3 |
| 3.5 — Information Density | ✅ DONE | `PHASE_3_5_INFO_DENSITY.md` |
| 3.6 — Visual Refinement | ✅ DONE | `PHASE_3_6_VISUAL_REFINEMENT.md` |
| 4 — News Feed (N2) | ✅ DONE | `IMPLEMENTATION_PLAN.md` §Phase 4 |
| 4.5 — Layout-B Sync | ✅ DONE | `PHASE_4_5_LAYOUT_B_SYNC.md` |
| 4.6 — Batch AI Summary | ✅ DONE | `PHASE_4_6_BATCH_AI_SUMMARY.md` |
| 5 — AI Right Rail | ✅ DONE | `IMPLEMENTATION_PLAN.md` §Phase 5 |
| **6 — Polish + multi-page route (incl. LLM impact swap)** | ⬜ pending | `IMPLEMENTATION_PLAN.md` §Phase 6 |

> **Current task: Phase 6 is pending.** Do not start Phase 6 until explicitly requested; Phase 5 AI Right Rail is complete.

## Execution Order for Claude Code

When implementing, run these in order:

1. **Read** `DESIGN_SPEC.md` end-to-end (~25 min). Understand the 4 pains and the variant decisions.
2. **Read** `COMPONENT_MAP.md`. Understand which `src/app/layout.py` builders change and which CSS classes are touched.
3. **Read** `IMPLEMENTATION_PLAN.md`. Each Phase = 1 PR.
4. **Phase 1 (Tokens):** ✅ DONE.
5. **Phase 2 (Layout grid):** ✅ DONE.
6. **Phase 3 (Signal sidebar):** ✅ DONE.
7. **Phase 3.5 (Information Density):** ✅ DONE — see `PHASE_3_5_INFO_DENSITY.md`.
8. **Phase 3.6 (Visual Refinement):** ✅ DONE — see `PHASE_3_6_VISUAL_REFINEMENT.md`.
9. **Phase 4 (News feed):** ✅ DONE — N2 impact feed, filter buttons, sort toggle (asc/desc), right rail (今日重點/情緒分佈/熱門關鍵字), per-row stock card with click-through to dashboard.
10. **Phase 4.5 (Layout-B Sync):** ✅ DONE — 即時看板 sync layout-B：grid 改 `180/1fr/300`、移除底部列、右欄 5-tab（五檔/大戶｜AI｜訊號｜籌碼面｜新聞）、中央『新聞』tab 移除。see `PHASE_4_5_LAYOUT_B_SYNC.md`.
10.5 **Phase 4.6 (Batch AI Summary):** ✅ DONE — `summarize_articles_batch` chunked LLM call（30 篇/批）+ URL-level cache + `summarize_global` 改吃 summary 省 token。修復「AI 解讀」展開與標題重複問題。see `PHASE_4_6_BATCH_AI_SUMMARY.md`.
11. **Phase 5 (AI Right Rail):** ✅ DONE — 填右欄 `AI` tab 內容。`_create_ai_panel()` builder + advisor data layer.
12. **Phase 6 (Polish + AI-2 route):** ⬜ pending — Add `/advisor` Dash multi-page route. Add news timeline (N1) as a tab.

After each Phase, run the app and visually compare to the corresponding `reference/*.png`.

## Constraints (DO NOT VIOLATE)

- **紅漲綠跌**: Up = `#EF5350` (red), Down = `#26A69A` (green-teal). Never invert. Taiwan convention is the opposite of US/Western markets.
- **MA Colors**: MA5=`#FF6F00` MA10=`#2196F3` MA20=`#E91E63` MA60=`#9C27B0` — locked.
- **Background scale**: `#1E1E1E` → `#2A2A2A` → `#333333` (3 levels, no more).
- **Number font**: Always `JetBrains Mono` with `font-variant-numeric: tabular-nums`. Prices, volumes, percentages must NOT shift width when updating.
- **Density**: Base font-size = 13px. Pills = 10px. Stock-row line-height = 28px. Don't inflate to 16px web-app defaults.
- **Update animation**: Price changes flash for 600ms with `--up-soft`/`--down-soft` background, never sliding/bouncing.

## What is NOT in this handoff

- Backend data fetching changes (out of scope — existing `src/data/` is fine)
- Authentication / user accounts
- Mobile responsive design (1920 desktop only per user spec)
- WebSocket migration (existing 1-second polling is acceptable)

## Questions / Ambiguity

If the spec is unclear on a detail, **defer to the HTML reference in `design/afs/*.jsx`** — that is the source of truth. Anything not specified there should match existing autoFetchStock styling.

---

**Ready? Open `DESIGN_SPEC.md` next.**
