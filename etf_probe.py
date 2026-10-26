# 暫時：安聯 token、群益 00415A 代碼、第二備援來源
import json, requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
print("===== 安聯")
s = requests.Session(); s.headers.update({**UA, "Origin": "https://etf.allianzgi.com.tw", "Referer": "https://etf.allianzgi.com.tw/etf-info/E0001?tab=4", "Accept": "application/json, text/plain, */*"})
s.get("https://etf.allianzgi.com.tw/etf-info/E0001?tab=4", timeout=30)
t = s.get("https://etf.allianzgi.com.tw/webapi/api/AntiForgery/GetAntiForgeryToken", timeout=30)
print("token", t.status_code, t.text[:200], dict(s.cookies))
tok = t.json().get("token", "")
for h in ["RequestVerificationToken", "X-XSRF-TOKEN", "X-CSRF-TOKEN", "X-AntiForgery-Token"]:
    r = s.post("https://etf.allianzgi.com.tw/webapi/api/Fund/GetFundAssets", json={"FundID": "E0001"}, headers={h: tok}, timeout=30)
    print(h, r.status_code, r.text[:300])
    if r.status_code == 200:
        r2 = s.post("https://etf.allianzgi.com.tw/webapi/api/Fund/GetFundAssets", json={"FundID": "E0001", "SearchDate": "2026-10-21"}, headers={h: tok}, timeout=30)
        print("帶日期", r2.status_code, r2.text[:3000])
        break
print("===== 群益")
for f in range(504, 531):
    try:
        r = requests.post("https://www.capitalfund.com.tw/CFWeb/api/etf/buyback", json={"fundId": str(f)}, headers={**UA, "Accept": "application/json"}, timeout=20)
        p = (r.json().get("data") or {}).get("pcf") or {}
        if p.get("fundName"):
            print(f, p.get("fundName"), p.get("date2"))
    except Exception as e:
        pass
print("===== 復華清單")
r = requests.get("https://www.fhtrust.com.tw/api/assetsExcel/ETF24/20261022", headers=UA, timeout=30)
print("ETF24", r.status_code, r.content[:4])
for k in ["ETF20", "ETF21", "ETF22", "ETF24", "ETF25", "ETF26"]:
    r = requests.get(f"https://www.fhtrust.com.tw/api/assetsExcel/{k}/20261022", headers=UA, timeout=30)
    if r.content[:2] == b"PK":
        import pandas as pd, io
        print(k, pd.read_excel(io.BytesIO(r.content), header=None).iloc[0, 0])
print("===== janeytu 快照")
r = requests.get("https://api.github.com/repos/janeytu/tw-etf-pages/contents/data/snapshots", timeout=30)
print(r.status_code, [x["name"] for x in r.json()][:50] if r.status_code == 200 else r.text[:200])
r = requests.get("https://api.github.com/repos/janeytu/tw-etf-pages/contents/data/snapshots/00406A", timeout=30)
if r.status_code == 200:
    names = [x["name"] for x in r.json()]
    print(names[-5:])
    raw = requests.get(f"https://raw.githubusercontent.com/janeytu/tw-etf-pages/main/data/snapshots/00406A/{names[-1]}", timeout=30)
    print(raw.status_code, raw.text[:800])
print("===== 中信 00995A")
s = requests.Session(); s.headers.update({**UA, "Origin": "https://www.ctbcinvestments.com", "Referer": "https://www.ctbcinvestments.com/"})
t = s.post("https://www.ctbcinvestments.com.tw/API/home/AuthToken?token=www.ctbcinvestments.com", json={"token": "www.ctbcinvestments.com"}, timeout=30).json()["Data"]["token"]
r = s.post("https://www.ctbcinvestments.com.tw/API/etf/ETFHoldingWeight", params={"token": t}, json={"token": t, "FID": "E0036", "StartDate": "2026-10-23T00:00:00.000Z"}, timeout=30)
d = r.json()["Data"]
print(d["FundAssets"], [(x["Code"], len(x["Data"])) for x in d["FundAssetsDetail"]])
print("===== 第一金")
r = requests.post("https://www.fsitc.com.tw/WebAPI.aspx/Get_hd", json={"pStrFundID": "182", "pStrDate": "2026-10-22"}, headers={**UA, "Content-Type": "application/json; charset=utf-8", "X-Requested-With": "XMLHttpRequest", "Origin": "https://www.fsitc.com.tw", "Referer": "https://www.fsitc.com.tw/FundDetail.aspx"}, timeout=30)
print(r.status_code, r.headers.get("content-type"), r.text[:600])
