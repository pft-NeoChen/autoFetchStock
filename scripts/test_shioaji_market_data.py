import os
import time
import shioaji as sj
from dotenv import load_dotenv
from datetime import datetime, timedelta

def test_market_data():
    load_dotenv("config.env")
    
    is_simulation = os.getenv("SHIOAJI_SIMULATION", "true").lower() == "true"
    
    if is_simulation:
        api_key = os.getenv("SHIOAJI_API_KEY_SIM")
        secret_key = os.getenv("SHIOAJI_SECRET_KEY_SIM")
        print("模式: 模擬環境 (Simulation)")
    else:
        api_key = os.getenv("SHIOAJI_API_KEY_PROD")
        secret_key = os.getenv("SHIOAJI_SECRET_KEY_PROD")
        print("模式: 正式環境 (Production)")

    api = sj.Shioaji(simulation=is_simulation)
    
    try:
        # 1. Login
        api.login(api_key, secret_key)
        print("[1/4] 登入成功")

        # 2. Contract Test (TSMC 2330)
        print("[2/4] 測試合約查詢 (2330)...")
        contract = api.Contracts.Stocks["2330"]
        if contract:
            print(f"      成功獲取台積電資訊: {contract.name} ({contract.code})")
        else:
            print("      錯誤: 找不到 2330 合約")
            return

        # 3. Real-time Streaming Test
        print("[3/4] 測試即時串流訂閱 (訂閱 5 秒)...")
        received_data = {"quote": False, "tick": False}

        def quote_callback(exchange, quote):
            received_data["quote"] = True
            print(f"      [Quote] {quote.code} 最新成交價: {quote.close}")

        def tick_callback(exchange, tick):
            received_data["tick"] = True
            print(f"      [Tick] {tick.code} 成交價: {tick.close} | 單筆量: {tick.volume}")

        # 使用賦值方式設定回調
        api.on_quote_stkv1_callback = quote_callback
        api.on_tick_stkv1_callback = tick_callback

        api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.Quote, version=sj.constant.QuoteVersion.v1)
        api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.Tick, version=sj.constant.QuoteVersion.v1)
        
        # Wait a few seconds for data
        time.sleep(5)
        
        if received_data["quote"] or received_data["tick"]:
            print("      即時資料接收正常")
        else:
            print("      提示: 目前可能非盤中時間，或該股暫無成交資料")

        # 4. Historical Kbars Test
        print("[4/4] 測試歷史 K 線回補 (最近 1 天)...")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        kbars = api.kbars(contract, start=yesterday)
        if hasattr(kbars, 'close') and len(kbars.close) > 0:
            print(f"      成功獲取 {len(kbars.close)} 根 K 線資料")
        else:
            print("      提示: 無法獲取 K 線資料")

        print("\n所有核心測試完成！")
    except Exception as e:
        print(f"\n測試過程中發生錯誤: {str(e)}")
    finally:
        api.logout()

if __name__ == "__main__":
    test_market_data()
