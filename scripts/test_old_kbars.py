import sys
import os
import logging
from datetime import date

sys.path.append(os.getcwd())
from src.config import AppConfig, setup_logging
from src.fetcher.shioaji_fetcher import ShioajiFetcher

setup_logging(AppConfig(log_level="INFO"))

def test_old_kbars():
    from dotenv import load_dotenv
    load_dotenv("config.env")
    
    config = AppConfig(shioaji_simulation=False)
    fetcher = ShioajiFetcher(config)
    
    if fetcher.login():
        print("Testing old kbars (e.g., 2024-01)...")
        records = fetcher.fetch_daily_history("0050", 2024, 1)
        print(f"Fetched {len(records)} daily records for 0050 in 2024/01")
        
        print("Testing 1 year ago (e.g., 2025-02)...")
        records = fetcher.fetch_daily_history("0050", 2025, 2)
        print(f"Fetched {len(records)} daily records for 0050 in 2025/02")
        
        fetcher.logout()

if __name__ == "__main__":
    test_old_kbars()
