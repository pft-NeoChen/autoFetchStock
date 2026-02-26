
import sys
import os
import logging
from datetime import date

# Add project root to path
sys.path.append(os.getcwd())

from src.config import setup_logging, AppConfig
from src.fetcher.data_fetcher import DataFetcher

# Setup logging
setup_logging(AppConfig(log_level="DEBUG"))
logger = logging.getLogger("test_otc")

def test_fetch_3363():
    print("Testing fetch for 3363 (OTC)...")
    fetcher = DataFetcher()
    
    # Check market detection
    market = fetcher._get_market("3363")
    print(f"Market for 3363: {market}")
    
    if market != "otc":
        print("ERROR: 3363 should be OTC!")
    
    # Try fetching history for current month
    today = date.today()
    print(f"Fetching history for {today.year}/{today.month}...")
    
    try:
        data = fetcher.fetch_daily_history("3363", today.year, today.month)
        print(f"Fetched {len(data)} records.")
        if data:
            print(f"First record: {data[0]}")
            print(f"Last record: {data[-1]}")
    except Exception as e:
        print(f"Fetch failed: {e}")
        import traceback
        traceback.print_exc()
        
    fetcher.close()

if __name__ == "__main__":
    test_fetch_3363()
