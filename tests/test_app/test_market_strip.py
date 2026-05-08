from src.app.callbacks import _render_market_strip
from src.models import MarketIndexEntry


def test_market_strip_value_uses_direction_class():
    children = _render_market_strip(
        [
            MarketIndexEntry(
                label="加權",
                symbol="001",
                value=21500.0,
                change=123.45,
                pct=0.58,
                direction="up",
            )
        ]
    )

    item = children[0]
    value = item.children[1]
    change = item.children[2]

    assert value.className == "num market-strip-value up"
    assert change.className == "num market-strip-chg up"
