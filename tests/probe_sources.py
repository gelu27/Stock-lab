# 暫時：測試新資料來源能不能連（只在分支的暫時 workflow 執行）
import requests
H = {"User-Agent": "Mozilla/5.0"}
def show(名, r):
    print(f"\n===== {名} {r.status_code} {r.headers.get('content-type','')} len={len(r.content)}")
    print(r.text[:700].replace("\n", " "))
def get(名, url, **kw):
    try:
        show(名, requests.get(url, headers=H, timeout=30, **kw))
    except Exception as e:
        print(f"\n===== {名} 失敗 {e}")
def post(名, url, data):
    try:
        show(名, requests.post(url, data=data, headers=H, timeout=30))
    except Exception as e:
        print(f"\n===== {名} 失敗 {e}")
get("上市處置", "https://openapi.twse.com.tw/v1/announcement/punish")
get("上市注意", "https://openapi.twse.com.tw/v1/announcement/notice")
get("上櫃處置", "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information")
get("上櫃注意", "https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_information")
get("上市借券TWT93U", "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date=20261022&response=json")
get("上市借券openapi", "https://openapi.twse.com.tw/v1/exchangeReport/TWT93U")
get("上櫃借券sbl", "https://www.tpex.org.tw/www/zh-tw/margin/sbl?date=2026%2F10%2F22&response=json")
get("上櫃借券openapi", "https://www.tpex.org.tw/openapi/v1/tpex_margin_sbl")
post("法說會MOPS", "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1",
     {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "year": "115", "month": "11", "co_id": ""})
get("法說會openapi", "https://openapi.twse.com.tw/v1/opendata/t187ap46_L_6")
get("ETF持股MoneyDJ", "https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid=0050.TW")
get("ETF持股元大", "https://www.yuantaetfs.com/api/StkWeights?date=&fundid=1066")
get("ETF持股PCF證交所", "https://www.twse.com.tw/rwd/zh/ETF/etfPcf?response=json")
