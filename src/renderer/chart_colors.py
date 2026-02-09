"""
Chart color configuration for autoFetchStock.

This module defines all color constants used in charts,
following Taiwan stock market convention (red for up, green for down).

Color palette is designed for dark theme backgrounds with good contrast
and accessibility considerations.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChartColors:
    """
    Chart color configuration constants.

    All colors follow Taiwan stock market convention:
    - Red (#EF5350): Price up / bullish
    - Green (#26A69A): Price down / bearish
    - White (#FFFFFF): Flat / unchanged
    """

    # Price direction colors (Taiwan convention: red up, green down)
    UP_COLOR: str = "#EF5350"        # Red - price increase
    DOWN_COLOR: str = "#26A69A"      # Green - price decrease
    FLAT_COLOR: str = "#FFFFFF"      # White - unchanged

    # Moving average line colors
    MA5_COLOR: str = "#FF6F00"       # Orange - MA5
    MA10_COLOR: str = "#2196F3"      # Blue - MA10
    MA20_COLOR: str = "#E91E63"      # Pink - MA20
    MA60_COLOR: str = "#9C27B0"      # Purple - MA60

    # Volume moving average colors (matching corresponding MA)
    VOL_MA5_COLOR: str = "#FF6F00"   # Orange - Volume MA5
    VOL_MA20_COLOR: str = "#2196F3"  # Blue - Volume MA20
    VOL_MA60_COLOR: str = "#9C27B0"  # Purple - Volume MA60

    # Special indicator colors
    BASELINE_COLOR: str = "#FFEB3B"  # Yellow - previous close baseline
    HIGHLIGHT_COLOR: str = "#FFC107" # Amber - price extremes annotation

    # Chart background and grid
    BG_COLOR: str = "#1E1E1E"        # Dark background
    PAPER_BG_COLOR: str = "#1E1E1E"  # Chart paper background
    GRID_COLOR: str = "#333333"      # Grid lines
    ZERO_LINE_COLOR: str = "#555555" # Zero axis line

    # Text colors
    TEXT_COLOR: str = "#FFFFFF"      # Primary text
    TEXT_SECONDARY: str = "#AAAAAA"  # Secondary text
    AXIS_COLOR: str = "#888888"      # Axis labels

    # Buy/Sell volume colors (for intraday chart)
    BUY_VOLUME_COLOR: str = "#EF5350"   # Red - buy volume (upward)
    SELL_VOLUME_COLOR: str = "#26A69A"  # Green - sell volume (downward)

    # Error/Warning message colors
    ERROR_BG_COLOR: str = "#B71C1C"     # Dark red - critical error
    WARNING_BG_COLOR: str = "#F57F17"   # Dark yellow - warning
    INFO_BG_COLOR: str = "#1565C0"      # Dark blue - info


# Default color instance for easy import
DEFAULT_COLORS = ChartColors()


def get_direction_color(direction: str, colors: ChartColors = None) -> str:
    """
    Get color based on price direction.

    Args:
        direction: "up", "down", or "flat"
        colors: Optional ChartColors instance (uses DEFAULT_COLORS if None)

    Returns:
        Hex color string
    """
    if colors is None:
        colors = DEFAULT_COLORS

    direction_map = {
        "up": colors.UP_COLOR,
        "down": colors.DOWN_COLOR,
        "flat": colors.FLAT_COLOR,
    }
    return direction_map.get(direction.lower(), colors.FLAT_COLOR)


def get_ma_color(period: int, colors: ChartColors = None) -> str:
    """
    Get moving average line color based on period.

    Args:
        period: MA period (5, 10, 20, or 60)
        colors: Optional ChartColors instance (uses DEFAULT_COLORS if None)

    Returns:
        Hex color string
    """
    if colors is None:
        colors = DEFAULT_COLORS

    ma_colors = {
        5: colors.MA5_COLOR,
        10: colors.MA10_COLOR,
        20: colors.MA20_COLOR,
        60: colors.MA60_COLOR,
    }
    return ma_colors.get(period, colors.TEXT_SECONDARY)


def get_volume_ma_color(period: int, colors: ChartColors = None) -> str:
    """
    Get volume moving average line color based on period.

    Args:
        period: Volume MA period (5, 20, or 60)
        colors: Optional ChartColors instance (uses DEFAULT_COLORS if None)

    Returns:
        Hex color string
    """
    if colors is None:
        colors = DEFAULT_COLORS

    vol_ma_colors = {
        5: colors.VOL_MA5_COLOR,
        20: colors.VOL_MA20_COLOR,
        60: colors.VOL_MA60_COLOR,
    }
    return vol_ma_colors.get(period, colors.TEXT_SECONDARY)


def get_candlestick_colors(open_price: float, close_price: float, colors: ChartColors = None) -> tuple:
    """
    Get candlestick colors based on open/close prices.

    Args:
        open_price: Opening price
        close_price: Closing price
        colors: Optional ChartColors instance (uses DEFAULT_COLORS if None)

    Returns:
        Tuple of (fill_color, line_color) for the candlestick
    """
    if colors is None:
        colors = DEFAULT_COLORS

    if close_price > open_price:
        return (colors.UP_COLOR, colors.UP_COLOR)
    elif close_price < open_price:
        return (colors.DOWN_COLOR, colors.DOWN_COLOR)
    else:
        return (colors.FLAT_COLOR, colors.FLAT_COLOR)


# CSS class names for dynamic styling in Dash
CSS_CLASSES = {
    "price_up": "price-up",
    "price_down": "price-down",
    "price_flat": "price-flat",
    "error": "error-message",
    "warning": "warning-message",
    "info": "info-message",
}
