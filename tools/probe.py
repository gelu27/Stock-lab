# 暫時用：測試各資料來源的格式（跑完會刪掉）
import json, sys, time
import requests
H = {"User-Agent": "Mozilla/5.0"}
D, RD, SD = "20261022", "115/10/22", "2026/10/22"
URLS = {
 "tpex_new_quotes": f"https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={SD}&id=&response=json",
 "tpex_new_otc": f"https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={SD}&type=EW&id=&response=json",
 "tpex_legacy_quotes": f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={RD}&o=json",
 "tpex_new_insti": f"https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date={SD}&id=&response=json",
 "tpex_legacy_insti": f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d={RD}&o=json",
 "tpex_new_margin": f"https://www.tpex.org.tw/www/zh-tw/margin/balance?date={SD}&id=&response=json",
 "tpex_legacy_margin": f"https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&o=json&d={RD}",
 "tpex_new_pe": f"https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date={SD}&id=&response=json",
 "tpex_legacy_pe": f"https://www.tpex.org.tw/web/stock/aftertrading/peratio_analysis/pera_result.php?l=zh-tw&o=json&d={RD}",
 "tpex_esb_latest": "https://www.tpex.org.tw/openapi/v1/tpex_esb_latest_statistics",
 "tpex_esb_new": f"https://www.tpex.org.tw/www/zh-tw/emerging/historical?date={SD}&response=json",
 "twse_t86": f"https://www.twse.com.tw/rwd/zh/fund/T86?date={D}&selectType=ALLBUT0999&response=json",
 "twse_margin": f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={D}&selectType=ALL&response=json",
 "twse_5min_index": f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_INDEX?date={D}&response=json",
 "twse_rev_L": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
 "twse_eps_L": "https://openapi.twse.com.tw/v1/opendata/t187ap14_L",
 "tpex_rev_O": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
 "tpex_eps_O": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap14_O",
 "mis_realtime": "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw|tse_2330.tw|otc_3264.tw&json=1&delay=0",
 "yahoo_intraday": "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?range=5d&interval=5m",
}
def short(v, n=300):
    return json.dumps(v, ensure_ascii=False)[:n]
for k, u in URLS.items():
    try:
        r = requests.get(u, headers=H, timeout=30)
        print(f"\n=== {k} HTTP {r.status_code} len={len(r.content)}")
        try:
            j = r.json()
        except Exception:
            print("  not json:", r.text[:200].replace("\n", " ")); continue
        if isinstance(j, list):
            print("  list", len(j), "keys:", list(j[0].keys()) if j else None); print("  row0:", short(j[0] if j else None, 600))
        else:
            print("  keys:", list(j.keys())[:20])
            for kk in ("stat", "date", "reportDate", "iTotalRecords"):
                if kk in j: print(f"  {kk}:", short(j[kk], 80))
            for t in j.get("tables", [])[:6]:
                print("  table:", t.get("title"), "| fields:", short(t.get("fields"), 700), "| n=", len(t.get("data") or []), "| row0:", short((t.get("data") or [None])[0], 500))
            for kk in j:
                if kk.startswith("fields") or kk in ("aaData",):
                    print(f"  {kk}:", short(j[kk], 700))
                if kk.startswith("data") or kk == "aaData":
                    print(f"  {kk} n=", len(j[kk]) if isinstance(j[kk], list) else "-", "row0:", short(j[kk][0] if isinstance(j[kk], list) and j[kk] else j[kk], 500))
            if "msgArray" in j: print("  msgArray0:", short(j["msgArray"][:1], 900))
            if "chart" in j: print("  chart:", short(j["chart"], 400))
    except Exception as e:
        print(f"\n=== {k} ERROR {e}")
    time.sleep(2)
