import requests
import re

headers = {"User-Agent": "Mozilla/5.0"}
url = "https://www.tpex.org.tw/www/zh-tw/afterTrading/stockQuote"

try:
    r = requests.get(url, headers=headers)
    js_files = re.findall(r'src="([^"]+\.js[^"]*)"', r.text)
    
    found_endpoints = set()
    for js_file in js_files:
        if js_file.startswith('/'):
            js_url = f"https://www.tpex.org.tw{js_file}"
        elif not js_file.startswith('http'):
            js_url = f"https://www.tpex.org.tw/www/zh-tw/afterTrading/{js_file}"
        else:
            js_url = js_file
            
        print(f"Checking JS: {js_url}")
        js_r = requests.get(js_url, headers=headers)
        
        # Look for API endpoint patterns in the minified JS
        endpoints = re.findall(r'"/(?:www/)?zh-tw/afterTrading/[^"]+/result"', js_r.text)
        found_endpoints.update(endpoints)
        
    print("Found Potential Endpoints:")
    for ep in found_endpoints:
        print(ep)
except Exception as e:
    print(f"Error: {e}")
