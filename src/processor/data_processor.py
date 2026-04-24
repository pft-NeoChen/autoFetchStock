"""
Data processor for autoFetchStock.

This module handles all data transformation and calculation logic:
- Moving average calculation (MA5, MA10, MA20, MA60)
- Volume moving average calculation (Vol MA5, MA20, MA60)
- K-line period resampling (daily -> weekly/monthly, tick -> minute K)
- Price change calculation
- OHLC data validation
- Visible range extremes detection
- Buy/sell volume separation
"""

import logging
from datetime import date, datetime, time
from typing import List, Optional, Dict, Any, Tuple

import pandas as pd
import numpy as np

from src.models import (
    DailyOHLC,
    IntradayTick,
    RealtimeQuote,
    PriceChange,
    PriceDirection,
    PriceExtremes,
    KlinePeriod,
)

logger = logging.getLogger("autofetchstock.processor")


class DataProcessor:
    """Data processing and calculation engine."""

    # Moving average periods
    MA_PERIODS: List[int] = [5, 10, 20, 60]
    # Volume moving average periods
    VOLUME_MA_PERIODS: List[int] = [5, 20, 60]

    def __init__(self):
        """Initialize data processor."""
        logger.info("DataProcessor initialized")

    def calculate_moving_averages(
        self,
        df: pd.DataFrame,
        periods: List[int] = None,
        price_column: str = "close"
    ) -> pd.DataFrame:
        """
        Calculate closing price moving averages (MA5/MA10/MA20/MA60).

        Adds ma5, ma10, ma20, ma60 columns to the DataFrame.
        Values are NaN for periods with insufficient data.

        Args:
            df: DataFrame with OHLC data
            periods: List of MA periods (default: [5, 10, 20, 60])
            price_column: Column name to calculate MA from (default: "close")

        Returns:
            DataFrame with added MA columns
        """
        if periods is None:
            periods = self.MA_PERIODS

        result_df = df.copy()

        for period in periods:
            col_name = f"ma{period}"
            result_df[col_name] = result_df[price_column].rolling(
                window=period,
                min_periods=period
            ).mean()
            logger.debug(f"Calculated {col_name} with {period} periods")

        return result_df

    def calculate_volume_moving_averages(
        self,
        df: pd.DataFrame,
        periods: List[int] = None,
        volume_column: str = "volume"
    ) -> pd.DataFrame:
        """
        Calculate volume moving averages (均量5/均量20/均量60).

        Adds vol_ma5, vol_ma20, vol_ma60 columns to the DataFrame.

        Args:
            df: DataFrame with volume data
            periods: List of volume MA periods (default: [5, 20, 60])
            volume_column: Column name for volume (default: "volume")

        Returns:
            DataFrame with added volume MA columns
        """
        if periods is None:
            periods = self.VOLUME_MA_PERIODS

        result_df = df.copy()

        for period in periods:
            col_name = f"vol_ma{period}"
            result_df[col_name] = result_df[volume_column].rolling(
                window=period,
                min_periods=period
            ).mean()
            logger.debug(f"Calculated {col_name} with {period} periods")

        return result_df

    def resample_to_period(
        self,
        df: pd.DataFrame,
        period: KlinePeriod
    ) -> pd.DataFrame:
        """
        Resample daily K-line data to weekly or monthly K-line.

        Resampling rules:
        - open: first value
        - high: maximum value
        - low: minimum value
        - close: last value
        - volume: sum of values

        Args:
            df: DataFrame with daily OHLC data (must have 'date' column or DatetimeIndex)
            period: Target period (WEEKLY or MONTHLY)

        Returns:
            Resampled DataFrame
        """
        if period == KlinePeriod.DAILY:
            return df.copy()

        resample_rule = period.pandas_resample_rule
        if resample_rule is None:
            logger.warning(f"Period {period} is not a resample period, returning original data")
            return df.copy()

        result_df = df.copy()

        # Ensure we have a datetime index
        if "date" in result_df.columns:
            result_df["date"] = pd.to_datetime(result_df["date"])
            result_df.set_index("date", inplace=True)

        # Define aggregation rules
        agg_rules = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }

        # Add turnover if present
        if "turnover" in result_df.columns:
            agg_rules["turnover"] = "sum"

        # Resample
        resampled = result_df.resample(resample_rule).agg(agg_rules)

        # Drop rows with NaN values (incomplete periods)
        resampled = resampled.dropna()

        # Reset index to have date as column
        resampled = resampled.reset_index()
        resampled.rename(columns={"index": "date"}, inplace=True)

        logger.info(f"Resampled {len(df)} daily records to {len(resampled)} {period.value} records")

        return resampled

    def resample_intraday_to_minutes(
        self,
        ticks_df: pd.DataFrame,
        minutes: int
    ) -> pd.DataFrame:
        """
        Aggregate tick data to minute K-line.

        Args:
            ticks_df: DataFrame with tick data (must have 'time' and 'price' columns)
            minutes: Aggregation interval (1, 5, 15, 30, or 60)

        Returns:
            DataFrame with minute K-line data
        """
        if ticks_df.empty:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        result_df = ticks_df.copy()

        # Ensure datetime index
        if "time" in result_df.columns:
            # Combine with today's date for proper datetime handling
            today = date.today()
            result_df["datetime"] = result_df["time"].apply(
                lambda t: datetime.combine(today, t) if isinstance(t, time) else t
            )
            result_df.set_index("datetime", inplace=True)

        # Define aggregation rules
        agg_rules = {
            "price": ["first", "max", "min", "last"],
            "volume": "sum",
        }

        # Resample to minute intervals
        resampled = result_df.resample(f"{minutes}min").agg(agg_rules)

        # Flatten column names
        resampled.columns = ["open", "high", "low", "close", "volume"]

        # Drop rows with NaN
        resampled = resampled.dropna()

        # Reset index
        resampled = resampled.reset_index()
        resampled.rename(columns={"datetime": "time"}, inplace=True)

        logger.info(f"Resampled {len(ticks_df)} ticks to {len(resampled)} {minutes}-minute bars")

        return resampled

    def calculate_price_change(
        self,
        current_price: float,
        previous_close: float
    ) -> PriceChange:
        """
        Calculate price change amount and percentage.

        Args:
            current_price: Current/latest price
            previous_close: Previous day's closing price

        Returns:
            PriceChange object with amount, percentage, and direction
        """
        return PriceChange.calculate(current_price, previous_close)

    def validate_ohlc_data(self, record: Dict[str, Any]) -> bool:
        """
        Validate OHLC data integrity (REQ-083).

        Validation rules:
        - All price fields are valid numbers
        - high >= max(open, close)
        - low <= min(open, close)
        - volume >= 0

        Args:
            record: Dictionary with OHLC data

        Returns:
            True if valid, False otherwise
        """
        try:
            open_price = float(record.get("open", 0))
            high = float(record.get("high", 0))
            low = float(record.get("low", 0))
            close = float(record.get("close", 0))
            volume = int(record.get("volume", 0))

            # Check all prices are positive
            if any(p <= 0 for p in [open_price, high, low, close]):
                logger.warning(f"Invalid price values: O={open_price}, H={high}, L={low}, C={close}")
                return False

            # Check high >= max(open, close)
            if high < max(open_price, close):
                logger.warning(f"High ({high}) < max(open, close) ({max(open_price, close)})")
                return False

            # Check low <= min(open, close)
            if low > min(open_price, close):
                logger.warning(f"Low ({low}) > min(open, close) ({min(open_price, close)})")
                return False

            # Check volume is non-negative
            if volume < 0:
                logger.warning(f"Negative volume: {volume}")
                return False

            return True

        except (ValueError, TypeError) as e:
            logger.warning(f"OHLC validation error: {e}")
            return False

    def find_visible_range_extremes(
        self,
        df: pd.DataFrame,
        start_idx: int = None,
        end_idx: int = None
    ) -> PriceExtremes:
        """
        Find highest and lowest prices within a visible range (REQ-057).

        Args:
            df: DataFrame with OHLC data
            start_idx: Start index of visible range (default: 0)
            end_idx: End index of visible range (default: len(df))

        Returns:
            PriceExtremes object with highest/lowest prices and dates
        """
        if df.empty:
            raise ValueError("Cannot find extremes in empty DataFrame")

        if start_idx is None:
            start_idx = 0
        if end_idx is None:
            end_idx = len(df)

        # Get visible range
        visible_df = df.iloc[start_idx:end_idx]

        # Find highest
        highest_idx = visible_df["high"].idxmax()
        highest_row = df.loc[highest_idx]
        highest_price = highest_row["high"]
        highest_date = highest_row["date"] if "date" in df.columns else date.today()

        # Find lowest
        lowest_idx = visible_df["low"].idxmin()
        lowest_row = df.loc[lowest_idx]
        lowest_price = lowest_row["low"]
        lowest_date = lowest_row["date"] if "date" in df.columns else date.today()

        # Convert to date if needed
        if isinstance(highest_date, (datetime, pd.Timestamp)):
            highest_date = highest_date.date()
        if isinstance(lowest_date, (datetime, pd.Timestamp)):
            lowest_date = lowest_date.date()

        return PriceExtremes(
            highest_price=highest_price,
            highest_date=highest_date,
            lowest_price=lowest_price,
            lowest_date=lowest_date,
        )

    def separate_buy_sell_volume(self, ticks_df: pd.DataFrame) -> pd.DataFrame:
        """
        Separate and accumulate buy/sell volume for visualization (REQ-042).

        Args:
            ticks_df: DataFrame with tick data including buy_volume and sell_volume

        Returns:
            DataFrame with 'buy_volume_display', 'sell_volume_display',
            and 'net_cum_volume' columns.
        """
        result_df = ticks_df.copy()

        if "buy_volume" not in result_df.columns:
            result_df["buy_volume"] = 0
        if "sell_volume" not in result_df.columns:
            result_df["sell_volume"] = 0

        # Net cumulative volume (Buy - Sell)
        # Represents the overall buying/selling strength
        result_df["net_cum_volume"] = (result_df["buy_volume"] - result_df["sell_volume"]).cumsum()

        return result_df

    def prepare_kline_data(
        self,
        daily_data: List[DailyOHLC],
        period: KlinePeriod = KlinePeriod.DAILY,
        realtime_quote: Optional[RealtimeQuote] = None
    ) -> pd.DataFrame:
        """
        Prepare complete K-line data for chart rendering.

        Flow:
        1. Convert DailyOHLC list to DataFrame
        2. Merge realtime quote if provided (REQ-044)
        3. Resample to target period (if needed)
        4. Calculate all moving averages
        5. Return complete DataFrame

        Args:
            daily_data: List of DailyOHLC records
            period: Target K-line period
            realtime_quote: Optional live quote to include

        Returns:
            DataFrame with OHLC + all MA columns
        """
        if not daily_data and not realtime_quote:
            logger.warning("No data provided for K-line")
            return pd.DataFrame()

        # Convert to DataFrame
        records = [
            {
                "date": record.date,
                "open": record.open,
                "high": record.high,
                "low": record.low,
                "close": record.close,
                "volume": record.volume,
                "turnover": record.turnover,
            }
            for record in daily_data
        ]
        
        df = pd.DataFrame(records)

        # Merge realtime quote if provided and market has opened (volume > 0)
        # Check if prices are valid to prevent zero-price spikes
        if realtime_quote and realtime_quote.total_volume > 0 and realtime_quote.open_price > 0:
            quote_date = realtime_quote.timestamp.date() if realtime_quote.timestamp else date.today()
            
            # Create quote record
            quote_record = {
                "date": quote_date,
                "open": realtime_quote.open_price,
                "high": realtime_quote.high_price,
                "low": realtime_quote.low_price,
                "close": realtime_quote.current_price,
                "volume": realtime_quote.total_volume,
                "turnover": 0, # Not easily available from realtime API
            }

            if not df.empty:
                # Check if we already have this date
                date_mask = df["date"] == quote_date
                if date_mask.any():
                    # Date already exists in historical data (from TWSE STOCK_DAY).
                    # Historical open/high/low are authoritative — do NOT overwrite them.
                    # Only refresh close price and volume from the realtime feed.
                    idx = df.index[date_mask][0]
                    df.at[idx, "close"] = quote_record["close"]
                    df.at[idx, "volume"] = quote_record["volume"]
                    # Extend high/low only when realtime values are valid and exceed history
                    rt_high = quote_record["high"]
                    rt_low = quote_record["low"]
                    if rt_high is not None and rt_high > df.at[idx, "high"]:
                        df.at[idx, "high"] = rt_high
                    if rt_low is not None and rt_low < df.at[idx, "low"]:
                        df.at[idx, "low"] = rt_low
                else:
                    # New date not yet in history (today's intraday bar).
                    # Fall back to current_price for any unavailable OHLC fields.
                    current = quote_record["close"]
                    new_record = {
                        "date": quote_record["date"],
                        "open": quote_record["open"] if quote_record["open"] is not None else current,
                        "high": quote_record["high"] if quote_record["high"] is not None else current,
                        "low": quote_record["low"] if quote_record["low"] is not None else current,
                        "close": current,
                        "volume": quote_record["volume"],
                        "turnover": quote_record["turnover"],
                    }
                    df = pd.concat([df, pd.DataFrame([new_record])], ignore_index=True)
            else:
                current = quote_record["close"]
                df = pd.DataFrame([{
                    "date": quote_record["date"],
                    "open": quote_record["open"] if quote_record["open"] is not None else current,
                    "high": quote_record["high"] if quote_record["high"] is not None else current,
                    "low": quote_record["low"] if quote_record["low"] is not None else current,
                    "close": current,
                    "volume": quote_record["volume"],
                    "turnover": quote_record["turnover"],
                }])

        # Sort by date
        df = df.sort_values("date").reset_index(drop=True)

        # Resample if needed
        if period in [KlinePeriod.WEEKLY, KlinePeriod.MONTHLY]:
            df = self.resample_to_period(df, period)

        # Calculate moving averages
        df = self.calculate_moving_averages(df)

        # Calculate volume moving averages
        df = self.calculate_volume_moving_averages(df)

        logger.info(f"Prepared {len(df)} {period.value} K-line records with MA columns")

        return df

    def prepare_intraday_data(
        self,
        ticks: List[IntradayTick],
        period: KlinePeriod = None
    ) -> pd.DataFrame:
        """
        Prepare intraday data for chart rendering.

        Args:
            ticks: List of IntradayTick records
            period: Optional minute period for aggregation

        Returns:
            DataFrame with time-series data
        """
        if not ticks:
            logger.warning("Empty tick data provided")
            return pd.DataFrame()

        # Convert to DataFrame
        df = pd.DataFrame([
            {
                "time": tick.time,
                "price": tick.price,
                "volume": tick.volume,
                "buy_volume": tick.buy_volume,
                "sell_volume": tick.sell_volume,
                "accumulated_volume": tick.accumulated_volume,
                "is_odd": getattr(tick, "is_odd", False),
            }
            for tick in ticks
        ])

        # Ensure datetime for Plotly compatibility (REQ-045)
        if not df.empty and "time" in df.columns:
            today = date.today()
            df["time"] = df["time"].apply(
                lambda t: datetime.combine(today, t) if isinstance(t, time) and not isinstance(t, datetime) else t
            )

        # Sort by time
        df = df.sort_values("time").reset_index(drop=True)

        if df.empty:
            return df

        # Keep source accumulated volume before deriving display totals. Shioaji
        # tick callbacks do not provide accumulated volume, so zero means
        # "derive from per-tick volume" rather than an actual zero total.
        if "accumulated_volume" in df.columns:
            source_accumulated = pd.to_numeric(
                df["accumulated_volume"],
                errors="coerce",
            ).fillna(0.0).astype(float)
            df["accumulated_volume"] = source_accumulated
        else:
            source_accumulated = pd.Series(0.0, index=df.index)

        # Calculate actual tick volume from accumulated volume or use provided volume
        # Primary source: 'volume' column (should be per-tick volume)
        df["tick_vol_calc"] = pd.to_numeric(
            df["volume"],
            errors="coerce",
        ).fillna(0.0).astype(float)
        
        # If volume is 0 but accumulated volume exists, try to recover from diff
        # (This handles legacy data or potential sync issues)
        if (df["tick_vol_calc"] == 0).all() and "accumulated_volume" in df.columns:
            filled_accumulated = source_accumulated.replace(0, np.nan).ffill().fillna(0)
            df["tick_vol_calc"] = filled_accumulated.diff().fillna(0)
            if not df.empty:
                df.loc[0, "tick_vol_calc"] = filled_accumulated.iloc[0]

        # Heuristic for buy/sell volume attribution
        df["price_diff"] = df["price"].diff().fillna(0)
        
        # Cast to float to avoid FutureWarning
        if "buy_volume" not in df.columns:
            df["buy_volume"] = 0.0
        if "sell_volume" not in df.columns:
            df["sell_volume"] = 0.0
            
        df["buy_volume"] = df["buy_volume"].astype(float)
        df["sell_volume"] = df["sell_volume"].astype(float)
        
        # Normalize Odd Lots (Shares) to Board Lots (1 Lot = 1000 Shares)
        # This ensures all volume units are consistent (Lots) for charts and calculations
        if "is_odd" in df.columns:
            odd_mask = df["is_odd"] == True
            if odd_mask.any():
                source_accumulated.loc[odd_mask] = source_accumulated.loc[odd_mask] / 1000.0
                df.loc[odd_mask, "tick_vol_calc"] = df.loc[odd_mask, "tick_vol_calc"] / 1000.0
                df.loc[odd_mask, "buy_volume"] = df.loc[odd_mask, "buy_volume"] / 1000.0
                df.loc[odd_mask, "sell_volume"] = df.loc[odd_mask, "sell_volume"] / 1000.0

        # Build chart cumulative volume. Source accumulated values are anchors;
        # rows without an anchor, such as Shioaji ticks, advance by tick volume.
        running_total = 0.0
        accumulated_display = []
        for source_total, tick_volume in zip(source_accumulated, df["tick_vol_calc"]):
            if source_total > 0:
                running_total = max(running_total, float(source_total))
            else:
                running_total += float(tick_volume)
            accumulated_display.append(running_total)
        df["accumulated_volume"] = accumulated_display
        
        # Attribute the calculated tick volume based on price movement
        # ONLY if explicit buy/sell volume is missing (e.g. from TWSE fallback)
        for idx, row in df.iterrows():
            # If explicit data exists (from Shioaji), skip heuristic
            if row["buy_volume"] > 0 or row["sell_volume"] > 0:
                continue
                
            vol = row["tick_vol_calc"]
            if row["price_diff"] > 0:
                df.at[idx, "buy_volume"] = vol
            elif row["price_diff"] < 0:
                df.at[idx, "sell_volume"] = vol
            else:
                # Neutral/Same price: split it
                df.at[idx, "buy_volume"] = vol / 2
                df.at[idx, "sell_volume"] = vol / 2

        # Identify Big Orders (REQ-BigPlayer)
        # Criteria: Volume >= 499 OR Amount >= 10,000,000
        # Amount = Price * Volume (Lots) * 1000 (Shares/Lot)
        # Since we normalized tick_vol_calc to Lots, this formula works for both Board and Odd lots
        tick_amount = df["price"] * df["tick_vol_calc"] * 1000
        
        is_big_volume = df["tick_vol_calc"] >= 499
        # Filter out odd lots from big volume check (redundant if normalized, 499 shares = 0.499 lots < 499)
        # But kept for safety
        if "is_odd" in df.columns:
            is_big_volume = is_big_volume & (~df["is_odd"])
        
        is_big_amount = tick_amount >= 10000000
        
        is_big_order = is_big_volume | is_big_amount
        
        # Mark Big Buy/Sell
        # We check if it was attributed primarily to buy (>0) or sell (>0)
        # If split (neutral), we don't mark it as a directional big order to avoid confusion
        df["is_big_buy"] = is_big_order & (df["buy_volume"] > df["sell_volume"])
        df["is_big_sell"] = is_big_order & (df["sell_volume"] > df["buy_volume"])

        # Separate buy/sell volume for visualization (calculates net_cum_volume)
        df = self.separate_buy_sell_volume(df)
        
        # Debug logging for volume investigation
        # if not df.empty:
        #     logger.info(f"Intraday Volume Sample (Tail):\\n{df[['time', 'tick_vol_calc', 'buy_volume', 'sell_volume', 'net_cum_volume']].tail()}")

        # Resample to minute bars if period specified
        if period and period.minutes:
            df = self.resample_intraday_to_minutes(df, period.minutes)

        logger.info(f"Prepared {len(df)} intraday records")

        return df

    def get_latest_price_info(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Get latest price information from DataFrame.

        Args:
            df: DataFrame with OHLC data

        Returns:
            Dictionary with latest price info
        """
        if df.empty:
            return {}

        latest = df.iloc[-1]

        return {
            "date": latest.get("date"),
            "open": latest.get("open"),
            "high": latest.get("high"),
            "low": latest.get("low"),
            "close": latest.get("close"),
            "volume": latest.get("volume"),
            "ma5": latest.get("ma5"),
            "ma10": latest.get("ma10"),
            "ma20": latest.get("ma20"),
            "ma60": latest.get("ma60"),
        }
