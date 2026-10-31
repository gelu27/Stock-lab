# 暫時：測試公司基本資料來源（測完會刪掉）
import re, json, requests
H = {"User-Agent": "Mozilla/5.0"}
def 試(名, f):
    try:
        f()
    except Exception as e:
        print(名, "失敗", type(e).__name__, str(e)[:200])
def a():
    r = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", headers=H, timeout=30)
    j = r.json(); print("TWSE t187ap03_L", len(j)); print(json.dumps(j[0], ensure_ascii=False)[:1500])
    print([x for x in j if x.get("公司代號") == "2330"][:1])
def b():
    r = requests.get("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", headers=H, timeout=30)
    j = r.json(); print("TPEx t187ap03_O", len(j)); print(json.dumps(j[0], ensure_ascii=False)[:1500])
def c():
    r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t05st03", headers=H, timeout=30, data={
        "encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "keyword4": "", "code1": "", "TYPEK2": "",
        "checkbtn": "", "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "co_id": "2330"})
    t = r.text; print("MOPS t05st03", r.status_code, len(t))
    i = t.find("主要經營業務"); print(re.sub(r"\s+", " ", t[max(i - 300, 0):i + 1500]))
def d():
    r = requests.get("https://tw.stock.yahoo.com/quote/2330.TW/profile", headers=H, timeout=30)
    t = r.text; print("Yahoo profile", r.status_code, len(t))
    for 詞 in ("營收比重", "主要經營業務", "經營業務"):
        i = t.find(詞); print(詞, i, re.sub(r"<[^>]+>", " | ", t[i:i + 1500])[:1200] if i >= 0 else "")
def e():
    r = requests.get("https://mopsov.twse.com.tw/mops/web/t05st03", headers=H, timeout=30)
    print("MOPS page", r.status_code, len(r.text))
def f():
    r = requests.get("https://concords.moneydj.com/z/zc/zca/zca_2330.djhtm", headers=H, timeout=30)
    r.encoding = "big5"; t = r.text; print("MoneyDJ zca", r.status_code, len(t))
    for 詞 in ("營收比重", "主要業務", "經營業務"):
        i = t.find(詞); print(詞, i, re.sub(r"<[^>]+>", " | ", t[i:i + 800])[:700] if i >= 0 else "")
for 名, 函 in [("a", a), ("b", b), ("c", c), ("d", d), ("e", e), ("f", f)]:
    試(名, 函); print("-" * 60)
