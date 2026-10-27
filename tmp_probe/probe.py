import requests, json, datetime as dt
H = {"User-Agent": "Mozilla/5.0"}
def show(name, f):
    try:
        print("=====", name); f()
    except Exception as e:
        print("FAIL", name, e)
def yahoo(sym):
    def f():
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5y&interval=1d", headers=H, timeout=30)
        j = r.json()["chart"]["result"][0]; q = j["indicators"]["quote"][0]; off = j["meta"].get("gmtoffset", 0)
        rows = list(zip(j["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"]))
        print(len(rows), j["meta"].get("currentTradingPeriod", {}).get("regular"))
        for t, *x in rows[:2] + rows[-8:]:
            print(dt.datetime.utcfromtimestamp(t + off), x)
    return f
show("TWII", yahoo("%5ETWII"))
show("TWOII", yahoo("%5ETWOII"))
def twse():
    r = requests.get("https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date=20261001&response=json", headers=H, timeout=30)
    j = r.json(); print(j.get("fields")); print(j.get("data", [])[-5:])
show("TWSE MI_5MINS_HIST", twse)
def tpex():
    for u in ["https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?date=2026%2F10%2F01&response=json",
              "https://www.tpex.org.tw/www/zh-tw/indexInfo/sectinx?date=2026%2F10%2F01&response=json"]:
        r = requests.get(u, headers=H, timeout=30); print(u, r.status_code, r.text[:600])
show("TPEX", tpex)
def cnn():
    r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2025-10-01", headers=H, timeout=30)
    print(r.status_code); j = r.json(); print(j.keys()); print(j["fear_and_greed"]); h = j["fear_and_greed_historical"]["data"]; print(len(h), h[:2], h[-3:])
show("CNN", cnn)
def yq():
    r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5ESOX?range=5d&interval=1d", headers=H, timeout=30)
    j = r.json()["chart"]["result"][0]; print(j["meta"].get("currentTradingPeriod"), j["meta"].get("regularMarketTime"), j["timestamp"][-3:])
show("SOX meta", yq)
