"""暫時探測：合約負債資料來源（跑完就刪）"""
import sys, os
sys.stdout = open("probe/result.txt", "w", buffering=1)
import re, time, json, io, requests, pandas as pd
H = {"User-Agent": "Mozilla/5.0"}
strip = lambda t: re.sub(r"<[^>]+>|&nbsp;|\s", "", t)

print("### 1. MOPS 彙總 t163sb05 表頭")
r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t163sb05", headers=H, timeout=90,
    data={"encodeURIComponent":1,"step":1,"firstin":1,"off":1,"isQuery":"Y","TYPEK":"sii","year":"114","season":"02"})
heads = set()
for t in re.findall(r"<table[^>]*>(.*?)</table>", r.text, re.S):
    heads |= {strip(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", t, re.S)}
print(sorted(heads)); print("含合約:", [h for h in heads if "合約" in h or "預收" in h])

print("### 2. MOPS 個別 t164sb03 2330 2025Q2")
for host in ("mopsov.twse.com.tw",):
    try:
        r = requests.post(f"https://{host}/mops/web/ajax_t164sb03", headers=H, timeout=90,
            data={"encodeURIComponent":1,"step":1,"firstin":1,"off":1,"queryName":"co_id","inpuType":"co_id",
                  "TYPEK":"all","isnew":"false","co_id":"2330","year":"114","season":"02"})
        rows = [[strip(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)] for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S)]
        print(host, r.status_code, len(r.text), [x for x in rows if x and ("合約" in x[0] or "預收" in x[0])][:10])
    except Exception as e: print(host, "失敗", e)

print("### 3. TWSE openapi t187ap07_L_ci 欄位")
try:
    j = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci", headers=H, timeout=60).json()
    print(list(j[0].keys()))
except Exception as e: print("失敗", e)

print("### 4. XBRL 整包下載 HEAD")
for u in ["https://mopsov.twse.com.tw/server-java/FileDownLoad?step=9&fileName=tifrs-2025Q2.zip&filePath=/home/html/nas/ifrs/2025/",
          "https://mops.twse.com.tw/server-java/FileDownLoad?step=9&fileName=tifrs-2025Q2.zip&filePath=/home/html/nas/ifrs/2025/"]:
    try:
        r = requests.get(u, headers=H, timeout=60, stream=True)
        print(u[:40], r.status_code, r.headers.get("Content-Type"), r.headers.get("Content-Length")); r.close()
    except Exception as e: print("失敗", e)

print("### 5. FinMind 不帶代號（全市場）")
r = requests.get("https://api.finmindtrade.com/api/v4/data", params={"dataset":"TaiwanStockBalanceSheet","start_date":"2025-06-30","end_date":"2025-06-30"}, timeout=60)
print(r.status_code, r.text[:300])

print("### 6. FinMind 個股 合約負債")
codes = "2330 2454 2317 3131 3583 6187 2404 6139 5536 3680 2520 2542 5522 2545 1519 1503 1513 3017 3324 2059 3443 3661 6515 6640 2368 2383 8046 3711 2603 2912 9910 2207 4966 6669 3227 2049 1560 6223 6510 7769".split()
out = []
for i, c in enumerate(codes):
    try:
        r = requests.get("https://api.finmindtrade.com/api/v4/data", params={"dataset":"TaiwanStockBalanceSheet","data_id":c,"start_date":"2021-01-01"}, timeout=60)
        d = pd.DataFrame(r.json().get("data", []))
        if i == 0:
            print("2330 types 合約:", d[d["origin_name"].str.contains("合約|預收", na=False)][["type","origin_name"]].drop_duplicates().values.tolist())
            print("剩餘次數 header:", {k:v for k,v in r.headers.items() if "limit" in k.lower() or "remain" in k.lower()})
        if len(d):
            s = d[(d["type"].isin(["TotalAssets","CapitalStock"]) | d["origin_name"].str.contains("合約負債", na=False)) & ~d["type"].str.endswith("_per")]
            out.append(s.assign(code=c)[["code","date","type","origin_name","value"]])
        else:
            print(c, "空", r.text[:200])
    except Exception as e: print(c, "失敗", e)
    time.sleep(1.5)
t = pd.concat(out)
print("合約相關 type:", t[t["origin_name"].str.contains("合約")][["type","origin_name"]].drop_duplicates().values.tolist())
t["k"] = t["type"].where(~t["origin_name"].str.contains("合約"), "CL_" + t["origin_name"])
w = t.pivot_table(index=["code","date"], columns="k", values="value", aggfunc="first").reset_index()
w.to_csv("probe/result.csv", index=False)
