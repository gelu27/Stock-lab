"""暫時探測第二輪：MOPS 個別資產負債表核對、XBRL 整包大小（跑完就刪）"""
import sys
sys.stdout = open("probe/result.txt", "w", buffering=1)
import re, time, io, zipfile, requests
H = {"User-Agent": "Mozilla/5.0"}
strip = lambda t: re.sub(r"<[^>]+>|&nbsp;|\s", "", t)
print("### MOPS t164sb03 合約相關列（2026Q2）")
for c in "8046 6669 3227 2404 2330 2317 2383 3711 1560".split():
    time.sleep(3)
    try:
        r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t164sb03", headers=H, timeout=90,
            data={"encodeURIComponent":1,"step":1,"firstin":1,"off":1,"queryName":"co_id","inpuType":"co_id",
                  "TYPEK":"all","isnew":"false","co_id":c,"year":"115","season":"02"})
        rows = [[strip(x) for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)] for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S)]
        print(c, r.status_code, len(rows), [x[:3] for x in rows if x and ("合約負債" in x[0] or "預收" in x[0])])
    except Exception as e: print(c, "失敗", e)
print("### XBRL 整包（只量 90 秒下載速度與開頭）")
u = "https://mopsov.twse.com.tw/server-java/FileDownLoad?step=9&fileName=tifrs-2026Q2.zip&filePath=/home/html/nas/ifrs/2026/"
t0 = time.time(); n = 0
try:
    r = requests.get(u, headers=H, timeout=60, stream=True)
    print(r.status_code, dict(r.headers))
    for ch in r.iter_content(1 << 16):
        n += len(ch)
        if n < 70000: first = (first if n > 65536 else b"") + ch if False else None
        if time.time() - t0 > 90: break
    print("90 秒下載 MB", round(n/1e6, 2))
except Exception as e: print("失敗", e, "已下載", n)
