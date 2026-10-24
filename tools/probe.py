import requests
H = {"User-Agent": "Mozilla/5.0"}
def show(u, n=700):
    try:
        r = requests.get(u, headers=H, timeout=30)
        print("==", u, r.status_code, len(r.content)); print(r.text[:n].replace("\n", " | "))
    except Exception as e:
        print("==", u, "ERR", e)
show("https://openapi.twse.com.tw/v1/opendata/t187ap11_L", 1200)
show("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O", 1200)
show("https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1m&range=1d", 500)
show("https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?interval=5m&range=5d", 500)
show("https://query1.finance.yahoo.com/v8/finance/chart/3264.TWO?interval=1m&range=1d", 300)
