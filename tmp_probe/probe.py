# 暫時：測試公司基本資料來源（測完會刪掉）
import re, time, requests
H = {"User-Agent": "Mozilla/5.0"}
def 文字(html):
    t = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", "", html)
    t = re.sub(r"<[^>]+>", "|", t)
    t = re.sub(r"&nbsp;?", " ", t)
    return re.sub(r"\s*\|[\s|]*", "|", t)
for 代 in ("2330", "8069"):
    r = requests.get(f"https://concords.moneydj.com/z/zc/zca/zca_{代}.djhtm", headers=H, timeout=30)
    r.encoding = "big5"
    t = 文字(r.text)
    i = t.find("最近交易日")
    print(代, r.status_code, t[i:i + 2500] if i >= 0 else t[:2500])
    print("=" * 40)
t0 = time.time(); 好 = 0
for 代 in ["1101", "1216", "2317", "2454", "2881", "3008", "6488", "5483", "3105", "6274"]:
    try:
        r = requests.get(f"https://concords.moneydj.com/z/zc/zca/zca_{代}.djhtm", headers=H, timeout=20)
        r.encoding = "big5"; 好 += "營收比重" in r.text
    except Exception as e:
        print(代, e)
print("10 檔", round(time.time() - t0, 1), "秒，有營收比重", 好)
t0 = time.time(); 好 = 0
for 代 in ["1101", "1216", "2317", "2454", "2881", "3008", "6488", "5483", "3105", "6274"]:
    r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t05st03", headers=H, timeout=30, data={
        "encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "keyword4": "", "code1": "", "TYPEK2": "",
        "checkbtn": "", "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "co_id": 代})
    好 += "主要經營業務" in r.text
    if "主要經營業務" not in r.text: print(代, r.text[:200])
print("MOPS 10 檔", round(time.time() - t0, 1), "秒，有業務", 好)
