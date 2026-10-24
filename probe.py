import requests, json, io
H = {"User-Agent": "Mozilla/5.0"}
def show(name, r, n=600):
    try:
        print(f"===== {name} status={r.status_code} type={r.headers.get('content-type')} len={len(r.content)}")
        t = r.content[:n*3]
        try: print(t.decode("utf-8")[:n])
        except Exception: print(t.decode("big5", "replace")[:n])
    except Exception as e:
        print(name, "ERR", e)
def get(name, url, n=600, **kw):
    try: show(name, requests.get(url, headers=H, timeout=30, **kw), n)
    except Exception as e: print(f"===== {name} EXC {e}")
def post(name, url, n=600, **kw):
    try: show(name, requests.post(url, headers=H, timeout=30, **kw), n)
    except Exception as e: print(f"===== {name} EXC {e}")

get("TWT49U range", "https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20250101&endDate=20251231&response=json", n=1500)
get("TWT48U openapi", "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL", n=800)
get("TWT48U rwd", "https://www.twse.com.tw/rwd/zh/exRight/TWT48U?response=json", n=1200)
get("t187ap45_L dividend", "https://openapi.twse.com.tw/v1/opendata/t187ap45_L", n=1200)
get("tpex exright openapi", "https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost", n=800)
get("tpex t187ap45_O", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap45_O", n=800)
post("tpex exright result", "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ", data={"startDate":"2025/01/01","endDate":"2025/12/31","response":"json"}, n=1500)
get("tpex exright old", "https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php?l=zh-tw&d=114/01/01&ed=114/12/31&o=json", n=1500)
get("TDCC 1-5", "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5", n=800)
get("TDCC smart 1-5", "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5", n=400)
for s in ["%5EGSPC", "%5EDJI", "%5EIXIC", "%5ESOX", "TSM", "%5EN225", "%5EVIX", "USDTWD%3DX"]:
    get("yahoo " + s, f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1d&range=5d", n=300)
body = {"MarketType":"1","SymbolType":"F","KindID":"1","CID":"TXF","ExpireMonth":"","RowSize":"全部","PageNo":"","SortColumn":"","AscDesc":"A"}
post("taifex night", "https://mis.taifex.com.tw/futures/api/getQuoteList", json=body, n=1500)
body["MarketType"] = "0"
post("taifex day", "https://mis.taifex.com.tw/futures/api/getQuoteList", json=body, n=1500)
get("taifex futDataDown", "https://www.taifex.com.tw/cht/3/futDailyMarketReport", n=300)
