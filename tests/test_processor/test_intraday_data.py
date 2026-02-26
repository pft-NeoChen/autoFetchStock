
import pytest
import pandas as pd
from datetime import datetime, time
from src.processor.data_processor import DataProcessor
from src.models import IntradayTick

class TestIntradayData:
    def test_accumulated_volume_monotonicity(self):
        """Test that accumulated_volume is monotonically increasing even with dips in input."""
        processor = DataProcessor()
        
        # Simulate ticks with non-monotonic accumulated volume
        # This simulates Stream (Sum) lagging behind Poll (Quote)
        ticks = [
            IntradayTick(time=time(9, 0, 0), price=100, volume=10, buy_volume=10, sell_volume=0, accumulated_volume=100),
            IntradayTick(time=time(9, 0, 1), price=101, volume=5, buy_volume=5, sell_volume=0, accumulated_volume=105), # Quote (High)
            IntradayTick(time=time(9, 0, 2), price=102, volume=2, buy_volume=2, sell_volume=0, accumulated_volume=102), # Stream (Low - missing packets?)
            IntradayTick(time=time(9, 0, 3), price=103, volume=8, buy_volume=8, sell_volume=0, accumulated_volume=110), # Quote (New High)
        ]
        
        df = processor.prepare_intraday_data(ticks)
        
        # Verify accumulated_volume is monotonically increasing
        assert df["accumulated_volume"].is_monotonic_increasing
        
        # Verify values are corrected (cummax)
        expected_volumes = [100, 105, 105, 110]
        assert df["accumulated_volume"].tolist() == expected_volumes

