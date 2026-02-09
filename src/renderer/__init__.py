"""
Chart renderer package for autoFetchStock.

Provides Plotly chart rendering capabilities.
"""

from src.renderer.chart_renderer import ChartRenderer
from src.renderer.chart_colors import ChartColors, DEFAULT_COLORS

__all__ = [
    "ChartRenderer",
    "ChartColors",
    "DEFAULT_COLORS",
]
