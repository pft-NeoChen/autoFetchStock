
import requests
import time

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

endpoints = [
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/trading/stockDay/result?l=zh-tw&d=115/02&code=3363",
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/trading/stockDay?l=zh-tw&d=115/02&code=3363",
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/stockQuote/result?l=zh-tw&d=115/02&code=3363",
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/stockQuote?l=zh-tw&d=115/02&code=3363",
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyTradingInfo/result?l=zh-tw&d=115/02&code=3363",
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyTradingInfo?l=zh-tw&d=115/02&code=3363",
]

for url in endpoints:
    print(f"Testing: {url}")
    try:
        r = requests.get(url, headers=headers, timeout=5)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            content_type = r.headers.get('content-type', '')
            print(f"Content-Type: {content_type}")
            if 'application/json' in content_type:
                print(f"Success! Found JSON API: {url}")
                print(r.text[:200])
                break
            else:
                print("Returned HTML, not JSON.")
    except Exception as e:
        print(f"Error: {e}")
    time.sleep(1)
