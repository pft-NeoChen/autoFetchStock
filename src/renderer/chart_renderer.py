"""
Chart renderer for autoFetchStock.

This module handles all Plotly chart rendering:
- K-line candlestick chart with volume subplot
- Moving average lines (MA5/MA10/MA20/MA60)
- Volume bar chart with volume MAs
- Intraday price line chart
- Buy/sell volume visualization
- Price extremes annotation
"""

import logging
from datetime import date, datetime, time
from typing import List, Optional, Dict, Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.renderer.chart_colors import (
    ChartColors,
    DEFAULT_COLORS,
    get_direction_color,
    get_ma_color,
    get_volume_ma_color,
)
from src.models import PriceExtremes, KlinePeriod

logger = logging.getLogger("autofetchstock.renderer")


class ChartRenderer:
    """Plotly chart rendering engine."""

    def __init__(self, colors: ChartColors = None):
        """
        Initialize chart renderer.

        Args:
            colors: Optional custom color configuration
        """
        self.colors = colors or DEFAULT_COLORS
        logger.info("ChartRenderer initialized")

    def render_kline_chart(
        self,
        df: pd.DataFrame,
        stock_name: str = "",
        period_label: str = "日K",
        uirevision: Optional[str] = None
    ) -> go.Figure:
        """
        Render complete K-line chart with volume subplot.

        Layout:
        - Upper subplot (70%): Candlestick + Moving averages + Price extremes
        - Lower subplot (30%): Volume bars + Volume MAs

        Args:
            df: DataFrame with OHLC data and MA columns
            stock_name: Stock name for chart title
            period_label: Period label (e.g., "日K", "週K")
            uirevision: Unique ID to preserve UI state

        Returns:
            Plotly Figure object
        """
        if df.empty:
            return self._create_empty_chart(f"{stock_name} {period_label}")
            
        if len(df) < 2:
            return self.render_empty_chart("歷史資料不足，無法繪製完整 K 線")

        # Create subplots
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.12,
            row_heights=[0.7, 0.3],
            subplot_titles=("", "成交量")
        )

        # Render candlestick
        self._render_candlestick(fig, df, row=1, col=1)

        # Render moving averages
        self._render_moving_averages(fig, df, row=1, col=1)

        # Render price extremes annotation
        self._render_price_extremes(fig, df, row=1, col=1)

        # Render volume bars
        self._render_volume_bars(fig, df, row=2, col=1)

        # Render volume moving averages
        self._render_volume_moving_averages(fig, df, row=2, col=1)

        # Apply unified layout
        title = f"{stock_name} {period_label}" if stock_name else period_label
        self._apply_chart_layout(fig, title, uirevision=uirevision)

        # Configure axes
        fig.update_xaxes(
            rangeslider_visible=False,
            type="category",
            categoryorder="category ascending",
            tickformat="%m/%d",
            row=1, col=1
        )
        
        # Also ensure the shared x-axis on the volume subplot skips empty dates
        fig.update_xaxes(
            type="category",
            categoryorder="category ascending",
            tickformat="%m/%d",
            row=2, col=1
        )

        fig.update_yaxes(
            title_text="價格",
            row=1, col=1
        )

        fig.update_yaxes(
            title_text="成交量",
            row=2, col=1
        )

        logger.info(f"Rendered K-line chart for {stock_name} with {len(df)} data points")

        return fig

    def _render_candlestick(
        self,
        fig: go.Figure,
        df: pd.DataFrame,
        row: int,
        col: int
    ) -> None:
        """
        Render K-line candlesticks (Taiwan convention: red up, green down).

        Args:
            fig: Plotly Figure
            df: DataFrame with OHLC data
            row: Subplot row
            col: Subplot column
        """
        # Determine colors based on open/close
        colors = []
        for _, r in df.iterrows():
            if r["close"] > r["open"]:
                colors.append(self.colors.UP_COLOR)
            elif r["close"] < r["open"]:
                colors.append(self.colors.DOWN_COLOR)
            else:
                colors.append(self.colors.FLAT_COLOR)

        # Get x-axis values (dates)
        x_values = df["date"] if "date" in df.columns else df.index

        candlestick = go.Candlestick(
            x=x_values,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            increasing_line_color=self.colors.UP_COLOR,
            decreasing_line_color=self.colors.DOWN_COLOR,
            increasing_fillcolor=self.colors.UP_COLOR,
            decreasing_fillcolor=self.colors.DOWN_COLOR,
            name="K線",
            showlegend=False,
        )

        fig.add_trace(candlestick, row=row, col=col)

    def _render_moving_averages(
        self,
        fig: go.Figure,
        df: pd.DataFrame,
        row: int,
        col: int
    ) -> None:
        """
        Render moving average lines (MA5/MA10/MA20/MA60).

        Args:
            fig: Plotly Figure
            df: DataFrame with MA columns
            row: Subplot row
            col: Subplot column
        """
        x_values = df["date"] if "date" in df.columns else df.index

        ma_configs = [
            ("ma5", 5, "MA5"),
            ("ma10", 10, "MA10"),
            ("ma20", 20, "MA20"),
            ("ma60", 60, "MA60"),
        ]

        for col_name, period, display_name in ma_configs:
            if col_name in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=x_values,
                        y=df[col_name],
                        mode="lines",
                        name=display_name,
                        line=dict(
                            color=get_ma_color(period, self.colors),
                            width=1
                        ),
                        hovertemplate=f"{display_name}: %{{y:.2f}}<extra></extra>",
                    ),
                    row=row,
                    col=col
                )

    def _render_price_extremes(
        self,
        fig: go.Figure,
        df: pd.DataFrame,
        row: int,
        col: int
    ) -> None:
        """
        Annotate highest and lowest prices in visible range (REQ-057).

        Args:
            fig: Plotly Figure
            df: DataFrame with OHLC data
            row: Subplot row
            col: Subplot column
        """
        if df.empty:
            return

        x_values = df["date"] if "date" in df.columns else df.index

        # Find highest price
        highest_idx = df["high"].idxmax()
        highest_price = df.loc[highest_idx, "high"]
        highest_x = x_values.iloc[df.index.get_loc(highest_idx)] if hasattr(x_values, 'iloc') else x_values[highest_idx]

        # Find lowest price
        lowest_idx = df["low"].idxmin()
        lowest_price = df.loc[lowest_idx, "low"]
        lowest_x = x_values.iloc[df.index.get_loc(lowest_idx)] if hasattr(x_values, 'iloc') else x_values[lowest_idx]

        # Add highest price annotation
        fig.add_annotation(
            x=highest_x,
            y=highest_price,
            text=f"▲ {highest_price:.2f}",
            showarrow=True,
            arrowhead=0,
            arrowsize=1,
            arrowwidth=1,
            arrowcolor=self.colors.HIGHLIGHT_COLOR,
            font=dict(color=self.colors.HIGHLIGHT_COLOR, size=10),
            ax=20,
            ay=-20,
            row=row,
            col=col
        )

        # Add lowest price annotation
        fig.add_annotation(
            x=lowest_x,
            y=lowest_price,
            text=f"▼ {lowest_price:.2f}",
            showarrow=True,
            arrowhead=0,
            arrowsize=1,
            arrowwidth=1,
            arrowcolor=self.colors.HIGHLIGHT_COLOR,
            font=dict(color=self.colors.HIGHLIGHT_COLOR, size=10),
            ax=20,
            ay=20,
            row=row,
            col=col
        )

    def _render_volume_bars(
        self,
        fig: go.Figure,
        df: pd.DataFrame,
        row: int,
        col: int
    ) -> None:
        """
        Render volume bar chart (colors match K-line candles).

        Args:
            fig: Plotly Figure
            df: DataFrame with OHLC and volume data
            row: Subplot row
            col: Subplot column
        """
        x_values = df["date"] if "date" in df.columns else df.index

        # Determine colors based on price change
        colors = []
        for _, r in df.iterrows():
            if r["close"] > r["open"]:
                colors.append(self.colors.UP_COLOR)
            elif r["close"] < r["open"]:
                colors.append(self.colors.DOWN_COLOR)
            else:
                colors.append(self.colors.FLAT_COLOR)

        fig.add_trace(
            go.Bar(
                x=x_values,
                y=df["volume"],
                marker_color=colors,
                name="成交量",
                showlegend=False,
                hovertemplate="成交量: %{y:,.0f}<extra></extra>",
            ),
            row=row,
            col=col
        )

    def _render_volume_moving_averages(
        self,
        fig: go.Figure,
        df: pd.DataFrame,
        row: int,
        col: int
    ) -> None:
        """
        Render volume moving average lines.

        Args:
            fig: Plotly Figure
            df: DataFrame with volume MA columns
            row: Subplot row
            col: Subplot column
        """
        x_values = df["date"] if "date" in df.columns else df.index

        vol_ma_configs = [
            ("vol_ma5", 5, "均量5"),
            ("vol_ma20", 20, "均量20"),
            ("vol_ma60", 60, "均量60"),
        ]

        for col_name, period, display_name in vol_ma_configs:
            if col_name in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=x_values,
                        y=df[col_name],
                        mode="lines",
                        name=display_name,
                        line=dict(
                            color=get_volume_ma_color(period, self.colors),
                            width=1
                        ),
                        hovertemplate=f"{display_name}: %{{y:,.0f}}<extra></extra>",
                    ),
                    row=row,
                    col=col
                )

    def render_intraday_chart(
        self,
        ticks_df: pd.DataFrame,
        stock_name: str = "",
        previous_close: float = None,
        uirevision: Optional[str] = None
    ) -> go.Figure:
        """
        Render intraday chart with total volume and market strength subplots.

        Layout:
        - Upper subplot: Total Accumulated Volume line chart
        - Lower subplot: Net buy/sell strength (cumulative)

        Args:
            ticks_df: DataFrame with intraday tick data
            stock_name: Stock name for chart title
            previous_close: Previous day's closing price
            uirevision: Unique ID to preserve UI state

        Returns:
            Plotly Figure object
        """
        if ticks_df.empty:
            return self._create_empty_chart(f"{stock_name} 分時走勢")

        # Create subplots
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.12,
            row_heights=[0.6, 0.4],
            subplot_titles=("累計成交量", "買賣力道 (累計差額)")
        )

        # Render total volume line
        self._render_intraday_volume_line(fig, ticks_df, row=1, col=1)

        # Render buy/sell strength
        self._render_buy_sell_volume(fig, ticks_df, row=2, col=1)

        # Apply unified layout
        title = f"{stock_name} 分時走勢" if stock_name else "分時走勢"
        self._apply_chart_layout(fig, title, uirevision=uirevision)
        
        # Set barmode to relative
        fig.update_layout(barmode="relative")

        # Configure y-axis titles
        fig.update_yaxes(title_text="張數", row=1, col=1)
        fig.update_yaxes(
            title_text="淨張數",
            zeroline=True,
            zerolinecolor=self.colors.TEXT_SECONDARY,
            zerolinewidth=2,
            row=2, col=1
        )

        logger.info(f"Rendered intraday chart for {stock_name} with {len(ticks_df)} data points")

        return fig

    def _render_intraday_volume_line(
        self,
        fig: go.Figure,
        ticks_df: pd.DataFrame,
        row: int,
        col: int
    ) -> None:
        """
        Render intraday total accumulated volume line.

        Args:
            fig: Plotly Figure
            ticks_df: DataFrame with tick data
            row: Subplot row
            col: Subplot column
        """
        x_values = ticks_df["time"] if "time" in ticks_df.columns else ticks_df.index
        
        # Add volume line
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=ticks_df["accumulated_volume"],
                mode="lines+markers" if len(ticks_df) < 5 else "lines",
                name="累計成交量",
                line=dict(color=self.colors.MA10_COLOR, width=2), # Use blue for volume
                fill="tozeroy",
                fillcolor="rgba(33, 150, 243, 0.1)",
                hovertemplate="時間: %{x|%H:%M:%S}<br>總量: %{y:,.0f} 張<extra></extra>",
            ),
            row=row,
            col=col
        )

        # Add Big Order Markers (Big Buy)
        if "is_big_buy" in ticks_df.columns:
            big_buy_df = ticks_df[ticks_df["is_big_buy"]]
            if not big_buy_df.empty:
                big_buy_x = big_buy_df["time"] if "time" in big_buy_df.columns else big_buy_df.index
                fig.add_trace(
                    go.Scatter(
                        x=big_buy_x,
                        y=big_buy_df["accumulated_volume"],
                        mode="markers",
                        name="大戶買進",
                        marker=dict(
                            symbol="triangle-up",
                            size=12,
                            color="#D32F2F", # Darker Red
                            line=dict(width=1, color="white")
                        ),
                        hovertemplate="時間: %{x|%H:%M:%S}<br>大戶買進: %{customdata[1]:.2f}<br>單筆: %{customdata[0]:,.0f}張<extra></extra>",
                        customdata=big_buy_df[["tick_vol_calc", "price"]],
                    ),
                    row=row,
                    col=col
                )

        # Add Big Order Markers (Big Sell)
        if "is_big_sell" in ticks_df.columns:
            big_sell_df = ticks_df[ticks_df["is_big_sell"]]
            if not big_sell_df.empty:
                big_sell_x = big_sell_df["time"] if "time" in big_sell_df.columns else big_sell_df.index
                fig.add_trace(
                    go.Scatter(
                        x=big_sell_x,
                        y=big_sell_df["accumulated_volume"],
                        mode="markers",
                        name="大戶賣出",
                        marker=dict(
                            symbol="triangle-down",
                            size=12,
                            color="#00796B", # Darker Green
                            line=dict(width=1, color="white")
                        ),
                        hovertemplate="時間: %{x|%H:%M:%S}<br>大戶賣出: %{customdata[1]:.2f}<br>單筆: %{customdata[0]:,.0f}張<extra></extra>",
                        customdata=big_sell_df[["tick_vol_calc", "price"]],
                    ),
                    row=row,
                    col=col
                )

        # Set Y-axis to auto-range
        fig.update_yaxes(autorange=True, row=row, col=col)

        # Ensure X-axis is treated as date/time
        fig.update_xaxes(
            type="date",
            tickformat="%H:%M",
            row=row, col=col
        )

    def _render_buy_sell_volume(
        self,
        fig: go.Figure,
        ticks_df: pd.DataFrame,
        row: int,
        col: int
    ) -> None:
        """
        Render net cumulative buy/sell volume as a single line (REQ-042).

        Args:
            fig: Plotly Figure
            ticks_df: DataFrame with net_cum_volume data
            row: Subplot row
            col: Subplot column
        """
        x_values = ticks_df["time"] if "time" in ticks_df.columns else ticks_df.index

        if "net_cum_volume" in ticks_df.columns:
            fig.add_trace(
                go.Scatter(
                    x=x_values,
                    y=ticks_df["net_cum_volume"],
                    mode="lines",
                    line=dict(color=self.colors.HIGHLIGHT_COLOR, width=2),
                    fill="tozeroy",
                    fillcolor="rgba(255, 193, 7, 0.2)", # Amber highlight
                    name="買賣力道",
                    hovertemplate="時間: %{x|%H:%M:%S}<br>買賣力道: %{y:,.0f} 張<extra></extra>",
                ),
                row=row,
                col=col
            )

    def _apply_chart_layout(
        self, 
        fig: go.Figure, 
        title: str,
        uirevision: Optional[str] = None
    ) -> None:
        """
        Apply unified chart layout settings (REQ-085).

        Settings:
        - Dark background theme
        - Consistent fonts and colors
        - Scroll zoom enabled
        - Drag mode for panning

        Args:
            fig: Plotly Figure
            title: Chart title
            uirevision: Unique ID to preserve UI state
        """
        layout_updates = dict(
            title=dict(
                text=title,
                font=dict(color=self.colors.TEXT_COLOR, size=16),
                x=0.5,
            ),
            paper_bgcolor=self.colors.PAPER_BG_COLOR,
            plot_bgcolor=self.colors.BG_COLOR,
            font=dict(color=self.colors.TEXT_COLOR),
            legend=dict(
                bgcolor="rgba(0,0,0,0)",
                font=dict(color=self.colors.TEXT_COLOR),
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            hovermode="x unified",
            dragmode="pan",
            margin=dict(l=50, r=50, t=80, b=50),
        )

        if uirevision:
            layout_updates["uirevision"] = uirevision

        fig.update_layout(**layout_updates)

        # Update all axes
        fig.update_xaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor=self.colors.GRID_COLOR,
            showline=True,
            linewidth=1,
            linecolor=self.colors.GRID_COLOR,
            tickfont=dict(color=self.colors.AXIS_COLOR),
        )

        fig.update_yaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor=self.colors.GRID_COLOR,
            showline=True,
            linewidth=1,
            linecolor=self.colors.GRID_COLOR,
            tickfont=dict(color=self.colors.AXIS_COLOR),
        )

        # Enable scroll zoom (REQ-086)
        fig.update_layout(
            xaxis=dict(fixedrange=False),
            yaxis=dict(fixedrange=False),
        )

    def _create_empty_chart(self, title: str) -> go.Figure:
        """
        Create an empty chart with placeholder message.

        Args:
            title: Chart title

        Returns:
            Empty Plotly Figure
        """
        fig = go.Figure()

        fig.add_annotation(
            text="尚無資料",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(color=self.colors.TEXT_SECONDARY, size=20),
        )

        self._apply_chart_layout(fig, title)

        return fig

    def render_empty_chart(self, message: str = "尚無資料") -> go.Figure:
        """
        Render an empty chart with a message.

        Public method for creating placeholder charts.

        Args:
            message: Message to display in the chart

        Returns:
            Plotly Figure with the message
        """
        fig = go.Figure()

        fig.add_annotation(
            text=message,
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(color=self.colors.TEXT_SECONDARY, size=20),
        )

        self._apply_chart_layout(fig, "")

        return fig

    def get_ohlc_display_text(self, df: pd.DataFrame, idx: int = -1) -> Dict[str, str]:
        """
        Get OHLC information for display (REQ-052, REQ-058).

        Args:
            df: DataFrame with OHLC data
            idx: Index of the data point (-1 for latest)

        Returns:
            Dictionary with formatted OHLC strings
        """
        if df.empty:
            return {
                "date": "",
                "open": "-",
                "high": "-",
                "low": "-",
                "close": "-",
                "volume": "-",
            }

        row = df.iloc[idx]

        return {
            "date": str(row.get("date", "")),
            "open": f"{row['open']:.2f}" if pd.notna(row.get("open")) else "-",
            "high": f"{row['high']:.2f}" if pd.notna(row.get("high")) else "-",
            "low": f"{row['low']:.2f}" if pd.notna(row.get("low")) else "-",
            "close": f"{row['close']:.2f}" if pd.notna(row.get("close")) else "-",
            "volume": f"{row['volume']:,.0f}" if pd.notna(row.get("volume")) else "-",
        }
