# 暫時：測試中信、安聯 API 與群益基金代碼
import json, requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

print("===== 中信")
s = requests.Session(); s.headers.update({**UA, "Origin": "https://www.ctbcinvestments.com", "Referer": "https://www.ctbcinvestments.com/"})
t = s.post("https://www.ctbcinvestments.com.tw/API/home/AuthToken?token=www.ctbcinvestments.com", json={"token": "www.ctbcinvestments.com"}, timeout=30).json()["Data"]["token"]
清單 = s.post("https://www.ctbcinvestments.com.tw/API/etf/ETFList?token=www.ctbcinvestments.com", json={"token": "www.ctbcinvestments.com", "IsWithETF": "Y"}, timeout=30).json()
for x in 清單["Data"]["Data"]:
    if str(x.get("ETF_ID", "")).endswith("A"):
        print(x.get("ETF_ID"), x.get("FID"), x.get("CNO"), x.get("FID_BNAME"))
for 日 in ["2026-10-26T04:24:00.196Z", "2026-10-21T00:00:00.000Z"]:
    r = s.post("https://www.ctbcinvestments.com.tw/API/etf/ETFHoldingWeight", params={"token": t}, json={"token": t, "FID": "E0038", "StartDate": 日}, timeout=30)
    d = r.json().get("Data") or {}
    print(日, r.status_code, list(d))
    for k, v in d.items():
        print(" ", k, json.dumps(v, ensure_ascii=False)[:1200])

print("===== 安聯")
s = requests.Session(); s.headers.update({**UA, "Origin": "https://etf.allianzgi.com.tw", "Referer": "https://etf.allianzgi.com.tw/etf-info/E0001?tab=4"})
for body in [{"FundID": "E0001"}, {"FundID": "E0001", "SearchDate": "2026-10-21"}]:
    r = s.post("https://etf.allianzgi.com.tw/webapi/api/Fund/GetFundAssets", json=body, timeout=30)
    print(body, r.status_code, r.text[:2500])

print("===== 群益")
for f in ["195", "365", "399", "500", "501", "502", "503", "510"]:
    try:
        r = requests.post("https://www.capitalfund.com.tw/CFWeb/api/etf/buyback", json={"fundId": f}, headers={**UA, "Accept": "application/json", "Referer": f"https://www.capitalfund.com.tw/etf/product/detail/{f}/portfolio"}, timeout=30)
        p = (r.json().get("data") or {}).get("pcf") or {}
        print(f, p.get("fundName"), p.get("date2"), len((r.json().get("data") or {}).get("stocks") or []))
    except Exception as e:
        print(f, repr(e)[:100])
