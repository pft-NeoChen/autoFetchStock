"""
Chips KPI cards (bottom data row, Phase 3.5).

Real data source is TWSE 三大法人買賣超 (T86), pulled by
`src.fetcher.chips_fetcher.ChipsFetcher` and persisted via
`src.storage.chips_storage.ChipsStorage`. This module computes the
display-ready `ChipKpiCard` shapes consumed by the layout.

When no on-disk history is available for the current stock, falls
back to a deterministic STUB matching the reference PNG so the UI
never blank-screens during first-run / non-trading-day conditions.

Margin (融資) is NOT yet wired to a real source; the card stays a
placeholder until `MI_MARGN` integration lands.
"""

from __future__ import annotations

from typing import List, Optional

from src.models import ChipKpiCard
from src.storage.chips_storage import ChipsStorage


# ── STUB fallback (matches reference/04-layout-A.png) ───────────────
_STUB_CARDS: List[ChipKpiCard] = [
    ChipKpiCard(
        key="foreign", label="外資",
        value_text="+12,485", direction="up",
        caption="連3買 · 5日 +18,420",
    ),
    ChipKpiCard(
        key="trust", label="投信",
        value_text="+822", direction="up",
        caption="連2買",
    ),
    ChipKpiCard(
        key="dealer", label="自營",
        value_text="-412", direction="down",
        caption="5日 -1,820",
    ),
    ChipKpiCard(
        key="margin", label="融資",
        value_text="-4.2%", direction="up",
        caption="月減 · 籌碼改善",
    ),
]


def build_chips_kpi(
    stock_id: Optional[str] = None,
    storage: Optional[ChipsStorage] = None,
) -> List[ChipKpiCard]:
    """Return the 4 KPI cards for `stock_id`.

    Three paths:
      1. No `storage` and no `stock_id` (boot, homepage) → STUB fixture.
      2. `storage` + `stock_id` with on-disk history → real data.
      3. `storage` + `stock_id` but no history (e.g. small caps that
         don't appear in 三大法人買賣超 today) → empty cards with `--`,
         **never** the STUB — that would surface fake numbers.
    """
    if storage is None and not stock_id:
        return list(_STUB_CARDS)
    if storage and stock_id:
        recent = storage.load_recent_for_stock(stock_id, n_days=5)
        if recent:
            margin_recent = storage.load_recent_margin_for_stock(stock_id, n_days=20)
            return _build_from_history(recent, margin_recent)
        return _empty_cards()
    # storage present but stock_id missing (no stock selected yet)
    return _empty_cards()


def _empty_cards() -> List[ChipKpiCard]:
    """Cards displayed when there is no real data for the current stock.

    Used for small caps with no 三大法人買賣超 activity and for the
    pre-selection state. Captions explain *why* the value is missing
    so the UI doesn't read as broken.
    """
    return [
        ChipKpiCard(key="foreign", label="外資",
                    value_text="--", direction="flat", caption="本日無進出"),
        ChipKpiCard(key="trust",   label="投信",
                    value_text="--", direction="flat", caption="本日無進出"),
        ChipKpiCard(key="dealer",  label="自營",
                    value_text="--", direction="flat", caption="本日無進出"),
        ChipKpiCard(key="margin",  label="融資",
                    value_text="--", direction="flat", caption="無融資資料"),
    ]


# ── Real-data builder ───────────────────────────────────────────────

def _build_from_history(
    recent: List[dict],
    margin_recent: Optional[List[dict]] = None,
) -> List[ChipKpiCard]:
    """`recent` is newest-first; rows have foreign_net/trust_net/dealer_net
    in **股** (TWSE native unit). Display unit is 張 (= 1000 股).

    `margin_recent` is newest-first MI_MARGN rows; `margin_balance` /
    `margin_prev` are already in 張 (TWSE MI_MARGN native unit).
    """
    today = recent[0]
    foreign_lots = _to_lots(today.get("foreign_net", 0))
    trust_lots   = _to_lots(today.get("trust_net", 0))
    dealer_lots  = _to_lots(today.get("dealer_net", 0))

    f_streak = _streak(recent, "foreign_net")
    t_streak = _streak(recent, "trust_net")

    f_sum5 = _to_lots(sum(r.get("foreign_net", 0) for r in recent[:5]))
    d_sum5 = _to_lots(sum(r.get("dealer_net",  0) for r in recent[:5]))

    return [
        ChipKpiCard(
            key="foreign", label="外資",
            value_text=_signed_lots(foreign_lots),
            direction=_direction(foreign_lots),
            caption=_caption_with_streak(f_streak, f_sum5_label=f"5日 {_signed_lots(f_sum5)}"),
        ),
        ChipKpiCard(
            key="trust", label="投信",
            value_text=_signed_lots(trust_lots),
            direction=_direction(trust_lots),
            caption=_caption_with_streak(t_streak),
        ),
        ChipKpiCard(
            key="dealer", label="自營",
            value_text=_signed_lots(dealer_lots),
            direction=_direction(dealer_lots),
            caption=f"5日 {_signed_lots(d_sum5)}",
        ),
        _build_margin_card(margin_recent),
    ]


def _build_margin_card(margin_recent: Optional[List[dict]]) -> ChipKpiCard:
    """Build the 融資 KPI card from MI_MARGN history.

    Display: pct change of margin balance over the rolling window
    (today vs oldest available, up to ~20 trading days). Direction is
    inverted vs raw delta because **falling 融資 = 籌碼改善** under the
    Taiwan retail-leverage convention used in the spec STUB.
    """
    if not margin_recent:
        return ChipKpiCard(
            key="margin", label="融資",
            value_text="--", direction="flat",
            caption="資料整合中",
        )

    today_bal = int(margin_recent[0].get("margin_balance", 0) or 0)
    # Prefer oldest within window; fall back to today's `margin_prev`
    # (D-1 balance) when only one snapshot exists.
    if len(margin_recent) >= 2:
        base_bal = int(margin_recent[-1].get("margin_balance", 0) or 0)
        days = len(margin_recent) - 1
    else:
        base_bal = int(margin_recent[0].get("margin_prev", 0) or 0)
        days = 1

    if base_bal <= 0 or today_bal <= 0:
        return ChipKpiCard(
            key="margin", label="融資",
            value_text="--", direction="flat",
            caption="資料整合中",
        )

    pct = (today_bal - base_bal) / base_bal * 100.0
    sign = "+" if pct > 0 else ""
    value_text = f"{sign}{pct:.1f}%"
    # Falling margin = chip improvement → green/up signal under spec.
    direction = "down" if pct > 0 else ("up" if pct < 0 else "flat")
    if pct < -1.0:
        caption_head = "月減" if days >= 15 else f"{days}日減"
        caption_tail = "籌碼改善"
    elif pct > 1.0:
        caption_head = "月增" if days >= 15 else f"{days}日增"
        caption_tail = "槓桿升溫"
    else:
        caption_head = "持平"
        caption_tail = "籌碼穩定"
    caption = f"{caption_head} · {caption_tail}"

    return ChipKpiCard(
        key="margin", label="融資",
        value_text=value_text, direction=direction, caption=caption,
    )


# ── Helpers ─────────────────────────────────────────────────────────

def _to_lots(shares: int) -> int:
    """Convert TWSE 股 to 張 (1 張 = 1000 股)."""
    try:
        return int(round(shares / 1000))
    except (TypeError, ValueError):
        return 0


def _direction(lots: int) -> str:
    if lots > 0:
        return "up"
    if lots < 0:
        return "down"
    return "flat"


def _signed_lots(lots: int) -> str:
    sign = "+" if lots > 0 else ("" if lots < 0 else "")
    return f"{sign}{lots:,}"


def _streak(rows: List[dict], field: str) -> int:
    """Signed streak length in days. +N = N consecutive net-buy days,
    -N = N consecutive net-sell days. 0 if today is flat."""
    if not rows:
        return 0
    first = rows[0].get(field, 0) or 0
    if first == 0:
        return 0
    sign = 1 if first > 0 else -1
    count = 0
    for r in rows:
        v = r.get(field, 0) or 0
        if v == 0:
            break
        if (v > 0) != (sign > 0):
            break
        count += 1
    return count * sign


def _caption_with_streak(streak: int, f_sum5_label: Optional[str] = None) -> str:
    if streak >= 2:
        head = f"連{streak}買"
    elif streak <= -2:
        head = f"連{-streak}賣"
    else:
        head = ""
    parts = [p for p in (head, f_sum5_label) if p]
    return " · ".join(parts) or "今日進場"
