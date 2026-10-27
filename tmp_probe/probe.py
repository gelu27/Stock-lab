# 暫時用：在 GitHub Actions 測新資料來源能不能連（測完就刪）
import datetime as dt
import json
import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
日 = "20261027"


def 看(名, 方法, url, **kw):
    try:
        r = requests.request(方法, url, headers=H, timeout=40, **kw)
        r.encoding = r.encoding or "utf-8"
        t = r.text
        print(f"\n===== {名} {r.status_code} {len(t)} {r.headers.get('content-type')}\n{t[:700]}")
        return r
    except Exception as e:
        print(f"\n===== {名} 失敗 {e!r}")


for 名, url in (("TWSE swagger", "https://openapi.twse.com.tw/v1/swagger.json"),
               ("TPEx swagger", "https://www.tpex.org.tw/openapi/swagger.json")):
    try:
        j = requests.get(url, headers=H, timeout=40).json()
        for p, v in j.get("paths", {}).items():
            s = json.dumps(v, ensure_ascii=False)
            if any(k in s for k in ("庫藏", "轉換", "可轉", "申購", "抽籤", "增資", "私募", "現金流", "資產負債", "外資", "僑外", "當沖", "當日沖")):
                摘 = v.get("get", v.get("post", {}))
                print(名, p, 摘.get("summary", "")[:60], 摘.get("description", "")[:40])
    except Exception as e:
        print(名, "失敗", repr(e))

看("外資持股 MI_QFIIS", "GET", f"https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date={日}&selectType=ALLBUT0999&response=json")
看("當沖 TWTB4U", "GET", f"https://www.twse.com.tw/rwd/zh/afterTrading/TWTB4U?date={日}&selectType=All&response=json")
看("櫃買當沖", "POST", "https://www.tpex.org.tw/www/zh-tw/intraday/statistics", data={"date": "2026/10/27", "response": "json"})
看("櫃買外資持股", "POST", "https://www.tpex.org.tw/www/zh-tw/insti/qfii", data={"date": "2026/10/27", "response": "json"})
看("PC ratio", "POST", "https://www.taifex.com.tw/cht/3/pcRatioDown", data={"queryStartDate": "2026/10/01", "queryEndDate": "2026/10/27"})
看("選擇權三大法人", "POST", "https://www.taifex.com.tw/cht/3/callsAndPutsDateDown",
   data={"queryStartDate": "2026/10/20", "queryEndDate": "2026/10/27", "commodityId": "TXO"})
看("選擇權每日行情", "POST", "https://www.taifex.com.tw/cht/3/dlOptDataDown",
   data={"down_type": "1", "commodity_id": "TXO", "commodity_id2": "", "queryStartDate": "2026/10/27", "queryEndDate": "2026/10/27"})
看("公開申購", "GET", "https://www.twse.com.tw/rwd/zh/announcement/publicForm?response=json")
for 頁 in ("ajax_t163sb05", "ajax_t163sb20", "ajax_t163sb06"):
    看(f"MOPS {頁}", "POST", f"https://mopsov.twse.com.tw/mops/web/{頁}",
       data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y", "TYPEK": "sii", "year": "115", "season": "02"})
看("MOPS 現金流 個股 t164sb05", "POST", "https://mopsov.twse.com.tw/mops/web/ajax_t164sb05",
   data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
         "isnew": "false", "co_id": "2330", "year": "115", "season": "02"})
看("MOPS 庫藏股 t35sc09", "POST", "https://mopsov.twse.com.tw/mops/web/ajax_t35sc09",
   data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "d1": "1151001", "d2": "1151027", "RD": "1"})
