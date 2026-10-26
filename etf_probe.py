# 暫時：測試主動式 ETF 持股資料來源（GitHub Actions 上跑）
import datetime as dt, json, re, io, traceback
import requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      "Accept-Language": "zh-TW,zh;q=0.9"}
今天 = dt.date(2026, 10, 22)

def 試(名, 函式):
    print("=" * 20, 名)
    try:
        函式()
    except Exception as e:
        print("錯誤", repr(e)[:300])

def 統一():
    s = requests.Session(); s.headers.update(UA)
    r = s.get("https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode=49YTW", timeout=30)
    print("info", r.status_code, len(r.text), r.text[:200].replace("\n", " "))
    for 日 in ["115/10/22", ""]:
        r = s.post("https://www.ezmoney.com.tw/ETF/Transaction/GetPCF", json={"fundCode": "49YTW", "date": 日, "specificDate": bool(日)},
                   headers={"Referer": "https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode=49YTW", "X-Requested-With": "XMLHttpRequest",
                            "Origin": "https://www.ezmoney.com.tw", "Content-Type": "application/json; charset=UTF-8"}, timeout=30)
        print("pcf", 日, r.status_code, r.text[:1500])
    r = s.get("https://www.ezmoney.com.tw/ETF/Fund/AssetExcelNPOI?fundCode=49YTW", timeout=30)
    print("excel", r.status_code, r.headers.get("content-type"), len(r.content), r.content[:100])

def 野村():
    for 日 in ["2026-10-22", "2026-10-21"]:
        r = requests.post("https://www.nomurafunds.com.tw/API/ETFAPI/api/Fund/GetFundAssets", json={"FundID": "00980A", "SearchDate": 日},
                          headers={**UA, "Origin": "https://www.nomurafunds.com.tw", "Referer": "https://www.nomurafunds.com.tw/ETFWEB/product-description",
                                   "Accept": "application/json, text/plain, */*"}, timeout=30)
        print(日, r.status_code, r.text[:1500])

def 群益():
    r = requests.post("https://www.capitalfund.com.tw/CFWeb/api/etf/buyback", json={"fundId": "399"},
                      headers={**UA, "Referer": "https://www.capitalfund.com.tw/etf/product/detail/399/portfolio", "Accept": "application/json"}, timeout=30)
    print(r.status_code, r.text[:1500])
    r = requests.post("https://www.capitalfund.com.tw/CFWeb/api/etf/buyback", json={"fundId": "399", "date": "2026-10-21"},
                      headers={**UA, "Referer": "https://www.capitalfund.com.tw/etf/product/detail/399/portfolio", "Accept": "application/json"}, timeout=30)
    print("帶日期", r.status_code, r.text[:600])

def 復華():
    r = requests.get("https://www.fhtrust.com.tw/api/assetsExcel/ETF23/20261022", headers=UA, timeout=30)
    print(r.status_code, r.headers.get("content-type"), len(r.content), r.content[:80])
    if r.content[:2] == b"PK":
        import pandas as pd
        t = pd.read_excel(io.BytesIO(r.content), header=None)
        print(t.head(20).to_string())

def 國泰():
    r = requests.get("https://cwapi.cathaysite.com.tw/api/ETF/GetETFDetailStockList", params={"FundCode": "EA", "SearchDate": "2026-10-22"},
                     headers={**UA, "Origin": "https://www.cathaysite.com.tw", "Referer": "https://www.cathaysite.com.tw/"}, timeout=30)
    print(r.status_code, r.text[:800])
    r = requests.get("https://cwapi.cathaysite.com.tw/api/ETF/GetETFList", headers={**UA, "Origin": "https://www.cathaysite.com.tw", "Referer": "https://www.cathaysite.com.tw/"}, timeout=30)
    print("list", r.status_code, r.text[:1500])

def 彙整():
    r = requests.get("https://nctuwanglin.github.io/active-etf/active.json", headers=UA, timeout=60)
    print(r.status_code, len(r.content))
    d = r.json()
    print("頂層", list(d))
    for k, v in d["etfs"].items():
        print(k, v.get("name"), v.get("issuer"), v.get("data_date"), v.get("status"), len(v.get("holdings") or []), (v.get("holdings") or [None])[0], v.get("scale"))
    k = next(iter(d["etfs"]))
    v = d["etfs"][k]
    print(json.dumps({kk: vv for kk, vv in v.items() if kk not in ("holdings", "events", "holders")}, ensure_ascii=False)[:800])
    print("events", json.dumps((v.get("events") or [])[:2], ensure_ascii=False))
    print("holders", json.dumps(v.get("holders"), ensure_ascii=False)[:300])
    print("consensus", json.dumps(d.get("consensus"), ensure_ascii=False)[:600])

def 元大():
    for u in ["https://www.yuantaetfs.com/api/StkWeights?date=&fundid=1066",
              "https://www.yuantaetfs.com/product/detail/0050/ratio"]:
        r = requests.get(u, headers=UA, timeout=30)
        print(u, r.status_code, r.headers.get("content-type"), r.text[:600].replace("\n", " "))
        m = re.findall(r"/api/[A-Za-z/]+", r.text)
        print("api", sorted(set(m))[:40])

def moneydj():
    for e in ["0050.tw", "00981A.tw"]:
        r = requests.get(f"https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={e}", headers=UA, timeout=30)
        r.encoding = "utf-8"
        t = re.sub(r"<[^>]+>", " ", r.text); t = re.sub(r"\s+", " ", t)
        i = t.find("持股")
        print(e, r.status_code, len(r.text), t[i:i+800])

def 證交所清單():
    r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", headers=UA, timeout=30)
    print([ (x["Code"], x["Name"]) for x in r.json() if re.fullmatch(r"00\d{3}A", x["Code"]) ])

for 名, f in [("統一", 統一), ("野村", 野村), ("群益", 群益), ("復華", 復華), ("國泰", 國泰), ("彙整 active.json", 彙整), ("元大", 元大), ("moneydj", moneydj), ("證交所清單", 證交所清單)]:
    試(名, f)
