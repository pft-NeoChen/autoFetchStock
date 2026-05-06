# Implementation Plan — autoFetchStock

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
