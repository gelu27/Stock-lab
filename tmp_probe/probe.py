# 暫時用：在 GitHub Actions 測新資料來源能不能連（測完就刪）
import json
import re
import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
去 = lambda t: re.sub(r"<[^>]+>|&nbsp;|\s", "", t)


def 看(名, 方法, url, n=900, **kw):
    try:
        r = requests.request(方法, url, headers=H, timeout=60, **kw)
        r.encoding = r.encoding or "utf-8"
        print(f"\n===== {名} {r.status_code} {len(r.text)} {r.headers.get('content-type')}\n{r.text[:n]}")
        return r
    except Exception as e:
        print(f"\n===== {名} 失敗 {e!r}")


def 表頭(名, r, 列數=3):
    if r is None:
        return
    for i, 表 in enumerate(re.findall(r"<table[^>]*>(.*?)</table>", r.text, re.S)[:6]):
        th = [去(t) for t in re.findall(r"<th[^>]*>(.*?)</th>", 表, re.S)]
        trs = re.findall(r"<tr[^>]*>(.*?)</tr>", 表, re.S)
        print(f"--- {名} 表{i} th={th[:40]}")
        k = 0
        for tr in trs:
            td = [去(t) for t in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(td) > 3:
                print("   ", td[:30])
                k += 1
                if k >= 列數:
                    break


j = requests.get("https://www.tpex.org.tw/openapi/swagger.json", headers=H, timeout=40).json()
for p, v in j["paths"].items():
    s = json.dumps(v, ensure_ascii=False)
    if re.search(r"bond|cb|CB|債|增資|庫藏|私募", p + s):
        print("TPEx", p, v.get("get", {}).get("summary", "")[:50])
j = requests.get("https://openapi.twse.com.tw/v1/swagger.json", headers=H, timeout=40).json()
for p, v in j["paths"].items():
    s = json.dumps(v, ensure_ascii=False)
    if re.search(r"債|增資|庫藏|私募|買回", s):
        print("TWSE", p, v.get("get", {}).get("summary", "")[:50])

看("TWSE openapi TWTB4U", "GET", "https://openapi.twse.com.tw/v1/exchangeReport/TWTB4U", 1200)
看("TWSE rwd dayTrading", "GET", "https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U?date=20261027&selectType=All&response=json", 1500)
看("TWSE old TWTB4U", "GET", "https://www.twse.com.tw/exchangeReport/TWTB4U?response=json&date=20261027&selectType=All", 1500)
看("TPEx openapi 當沖統計", "GET", "https://www.tpex.org.tw/openapi/v1/tpex_intraday_trading_statistics", 1200)
看("TPEx openapi 當沖標的", "GET", "https://www.tpex.org.tw/openapi/v1/tpex_securities", 600)
看("TPEx openapi qfii", "GET", "https://www.tpex.org.tw/openapi/v1/tpex_3insti_qfii", 600)
看("TPEx rwd 當沖", "POST", "https://www.tpex.org.tw/www/zh-tw/intraday/trading", 800, data={"date": "2026/10/27", "response": "json"})
看("TWSE openapi 資產負債", "GET", "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci", 1200)
for 頁 in ("ajax_t163sb05", "ajax_t163sb20"):
    r = 看(f"MOPS {頁}", "POST", f"https://mopsov.twse.com.tw/mops/web/{頁}", 100,
          data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y", "TYPEK": "sii", "year": "115", "season": "02"})
    表頭(頁, r)
r = 看("MOPS 庫藏股 t35sc09", "POST", "https://mopsov.twse.com.tw/mops/web/ajax_t35sc09", 100,
      data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "d1": "1150701", "d2": "1151027", "RD": "1"})
表頭("t35sc09", r, 5)
print(r.text[-3000:] if r is not None else "")
r = 看("MOPS 現金流 個股", "POST", "https://mopsov.twse.com.tw/mops/web/ajax_t164sb05", 100,
      data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
            "isnew": "false", "co_id": "2330", "year": "115", "season": "02"})
表頭("t164sb05", r, 40)
