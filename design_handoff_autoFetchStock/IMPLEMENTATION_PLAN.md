# IMPLEMENTATION_PLAN.md — 7 Phases

Each Phase = 1 PR. Don't skip ahead. Run the app and visually compare to `reference/*.png` after each Phase.

---

## Phase 4 — News Impact Feed (Variant N2)

**Goal:** News sorted by impact, not time. Match `reference/11-news-impact.png`.

**Tasks:**
- [ ] Add `impact_score: float = 0.0` to `NewsItem` model
- [ ] Stub `src/data/news_impact.py` — `score_news(news_item) -> float`
  - Heuristic: keyword presence (`目標價`, `法說`, `管制`, `下修` etc.) → base score; recency multiplier; sentiment magnitude
- [ ] Update news fetching to compute and persist `impact_score` on each item
- [ ] Replace existing news rendering with `.news-row` template
- [ ] Add filter chip row at top: `[全部] [我的最愛] [利多] [利空] [Impact ≥ 7]`
- [ ] New callback `callbacks/news_filter.py`
- [ ] Click row → expand summary inline (no modal)

**Done when:** News list is sorted by impact, filter chips work, expand/collapse works.

---

## Phase 5 — AI Advisor Right Rail (Variant AI-1)

**Goal:** 4-dimension AI panel always visible on stock detail. Match `reference/12-ai-rightrail.png`.

**Tasks:**
- [ ] Add `Advisor`, `AdvisorDimension`, `AdvisorBullet` to `src/models.py`
- [ ] Stub `src/data/advisor.py` — `build_advisor(stock_id) -> Advisor` from existing news/chip/fund/tech data
- [ ] New builder `_create_ai_panel(stock_id)` in `layout.py`
- [ ] Mount in right rail above Big Orders (or replace if space-constrained)
- [ ] Header: overall score + stance pill + delta arrow
- [ ] 4 dimension cards stacked, click to expand bullets
- [ ] Recommendation footer in bg-1 italic
- [ ] New callback `callbacks/advisor.py` — re-render on stock change

**Done when:** AI panel renders for selected stock, shows 4 dims, clicking expands bullets, recommendation visible.

---

## Phase 6 — Polish + Multi-page (B + N1 + AI-2)

**Goal:** Add layout toggle, news timeline, full advisor canvas.

**Tasks:**
- [ ] Migrate to Dash multi-page (`use_pages=True`)
- [ ] `pages/_dashboard.py` = current main (Variant A)
- [ ] `pages/_advisor.py` = Variant AI-2 full canvas with radar chart
- [ ] Add layout toggle to header: `[標準] [當沖]` — `當沖` mode = Variant B
- [ ] Add `EVENTS` model + `EVENTS` data layer (event clustering by date)
- [ ] Add news timeline (N1) as a tab inside stock detail page
- [ ] Update status bar with stale-data + connection-lost states (DESIGN_SPEC §7)
- [ ] Add focus rings, finalize a11y (DESIGN_SPEC §8)

**Done when:** All variants accessible, layout toggle works, /advisor route renders, a11y audit passes.

---

## Out of Scope (Future Stories)

- Real LLM-driven sentiment scoring (currently heuristic stubs)
- Variant C — Dual-Stock Compare route (`/compare`)
- Variant 3c — Standalone Signal Wall (`/signals`)
- Mobile responsive
- WebSocket migration
- User auth / saved layouts per user

---

## Verification Checklist (run before each PR)

- [ ] No new console errors in browser devtools
- [ ] No new mypy/ruff/pyright errors
- [ ] Existing tests still pass
- [ ] Screenshot diff against the matching `reference/*.png` is within ~4px tolerance
- [ ] Taiwan color convention preserved (red=up, teal=down)
- [ ] Numbers don't shift width on update (tabular-nums verified)
- [ ] Tested at 1920×1080 viewport


## Phase 7 — Data Quality & Tech Debt

### 7.1 Shioaji Timestamp Timezone Shift Root-Cause Fix

**Status**: Deferred (stop-gap heuristic in place as of Phase 3.5)

#### Background

Shioaji tick callbacks deliver timestamps that are consistently shifted by +8 hours
relative to Asia/Taipei local time. Symptom: after-hours 大戶進出 ticks land at
22:30 or 06:30 instead of the correct 14:30.

The current mitigation in `ShioajiFetcher._normalize_datetime` applies an **hour-band
heuristic**:

- `hour >= 15` → subtract 8 hours
- `hour < 8` → add 8 hours

This is a symptom-level fix. It will **misfire** on legitimate edge sessions:

- 盤後定盤 (after-hours fixed-price session): ticks near 14:30+ may be incorrectly
  shifted if the session runs past 15:00.
- 早盤試撮 (pre-open matching): ticks in 08:00–09:00 window are within the safe band
  but could be affected in corner cases.

#### Follow-up Tasks

1. **Diagnostic log**: Add structured logging in `_normalize_datetime` to capture raw
   vs corrected timestamps for 50 consecutive ticks. Dump to `logs/ts_debug.jsonl`.

2. **Identify offending code path**: Determine whether the shift originates from:
   - Shioaji SDK internal UTC assumption with no local conversion
   - `tick.datetime` attribute already being UTC naive
   - System locale mismatch at API login time

3. **Proper fix**: Replace the heuristic with `zoneinfo.ZoneInfo("Asia/Taipei")`
   applied at the correct point in the data pipeline:
   ```python
   from zoneinfo import ZoneInfo
   _TZ_TAIPEI = ZoneInfo("Asia/Taipei")
   # attach tz-info at source, then convert to naive local
   ts_local = tick.datetime.replace(tzinfo=ZoneInfo("UTC")).astimezone(_TZ_TAIPEI).replace(tzinfo=None)
   ```

4. **Unit tests**: Add tests in `tests/test_fetcher/` covering hour boundaries:
   - 07:59 UTC → should resolve to 15:59 Taipei (no heuristic trigger)
   - 08:00 UTC → should resolve to 16:00 Taipei
   - 14:59 UTC → should resolve to 22:59 Taipei
   - 15:00 UTC → should resolve to 23:00 Taipei
   - Pre-open (00:00–01:00 UTC → 08:00–09:00 Taipei)

5. **Remove heuristic**: Once root cause is confirmed and proper fix passes all
   boundary tests, delete the `if parsed.hour >= 15 / elif parsed.hour < 8` block
   and the `TODO(phase 7.1)` comment.

6. **Metric counter**: Increment a `prometheus` (or simple in-memory) counter each
   time a correction is applied, so ops can monitor ongoing correctness after deploy.

#### Acceptance Criteria

- All intraday ticks for regular session (09:00–13:30) and after-hours (14:00–14:30)
  display correct Asia/Taipei wall-clock time with zero heuristic corrections.
- Unit tests for all boundary cases pass.
- `TODO(phase 7.1)` comment removed from `shioaji_fetcher.py`.
