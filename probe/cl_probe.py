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
print("### XBRL 整包")
u = "https://mopsov.twse.com.tw/server-java/FileDownLoad?step=9&fileName=tifrs-2026Q2.zip&filePath=/home/html/nas/ifrs/2026/"
t0 = time.time()
try:
    r = requests.get(u, headers=H, timeout=600)
    print("大小 MB", round(len(r.content)/1e6,1), "秒", round(time.time()-t0), r.headers.get("Content-Type"))
    z = zipfile.ZipFile(io.BytesIO(r.content)); n = z.namelist(); print("檔數", len(n), n[:5])
    hit = 0
    for name in n:
        if "-2404-" in name or "_2404_" in name or "8046" in name:
            x = z.read(name).decode("utf-8", "ignore")
            print(name, len(x), sorted(set(re.findall(r"<([\w-]+:\w*ContractLiabilit\w*)[^>]*>([-\d.]+)<", x)))[:12])
            hit += 1
        if hit >= 3: break
    # 全市場有合約負債標籤的家數
    cnt = sum(1 for name in n if b"ContractLiabilit" in z.read(name))
    print("有合約負債標籤的檔案數", cnt, "/", len(n))
except Exception as e: print("失敗", e)
