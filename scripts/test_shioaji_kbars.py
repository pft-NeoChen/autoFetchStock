
import sys
import os
import logging
from datetime import datetime, timedelta

sys.path.append(os.getcwd())
from src.config import AppConfig, setup_logging
from src.fetcher.shioaji_fetcher import ShioajiFetcher

setup_logging(AppConfig(log_level="DEBUG"))

def test_kbars():
    from dotenv import load_dotenv
    load_dotenv("config.env")
    config = AppConfig(shioaji_simulation=False)
    fetcher = ShioajiFetcher(config)
    
    if not fetcher.login():
        print("Login failed")
        return
        
    contract = fetcher.api.Contracts.Stocks["3363"]
    if not contract:
        print("Contract not found")
        return
        
    print(f"Contract: {contract}")
    
    # Try fetching kbars for the last 180 days
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    
    print(f"Fetching kbars from {start_date} to {end_date}")
    
    try:
        kbars = fetcher.api.kbars(contract, start=start_date, end=end_date)
        import pandas as pd
        df = pd.DataFrame({**kbars})
        df.ts = pd.to_datetime(df.ts)
        print(f"Total minute rows: {len(df)}")
        
        # Resample to daily OHLC
        df.set_index('ts', inplace=True)
        daily_df = df.resample('D').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum',
            'Amount': 'sum'
        }).dropna()
        
        print("Daily Kbars DataFrame:")
        print(daily_df.head())
        print(f"Total daily rows: {len(daily_df)}")
        
    except Exception as e:
        print(f"Error fetching kbars: {e}")
        
    fetcher.logout()

if __name__ == "__main__":
    test_kbars()
