import requests, json
H = {"User-Agent": "Mozilla/5.0"}
def show(name, r, n=1500):
    print("=====", name, r.status_code, r.headers.get("content-type"))
    print(r.text[:n])
show("MI_MARGN MS", requests.get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
     params={"date": "20261022", "selectType": "MS", "response": "json"}, headers=H, timeout=20), 2500)
for u in ("https://www.tpex.org.tw/www/zh-tw/margin/balance", "https://www.tpex.org.tw/www/zh-tw/margin/sumMargin"):
    try:
        show(u, requests.post(u, data={"date": "2026/10/22", "response": "json"}, headers=H, timeout=20), 2500)
    except Exception as e:
        print(u, e)
try:
    show("tpex openapi margin", requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance", headers=H, timeout=20), 800)
except Exception as e:
    print(e)
try:
    r = requests.post("https://www.taifex.com.tw/cht/3/futContractsDateDown", headers=H, timeout=30,
                      data={"queryStartDate": "2026/09/01", "queryEndDate": "2026/10/22", "commodityId": "TXF"})
    r.encoding = "big5"
    show("taifex down", r, 2500)
except Exception as e:
    print("taifex down", e)
try:
    show("taifex openapi", requests.get("https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate", headers=H, timeout=30), 1500)
except Exception as e:
    print("taifex openapi", e)
