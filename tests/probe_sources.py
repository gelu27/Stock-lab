# 暫時：測試法說會資料格式
import re, requests
H = {"User-Agent": "Mozilla/5.0"}
for typek in ("sii", "otc"):
    r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1", headers=H, timeout=30,
                      data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": typek, "year": "115", "month": "11", "co_id": ""})
    t = r.text
    i = t.find("<table")
    print("=====", typek, len(t), "tables", t.count("<table"), "tr", t.count("<tr"))
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S | re.I)
    for row in rows[:6]:
        print(" | ".join(re.sub(r"<[^>]+>|\s+", " ", c).strip()[:40] for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)))
    fn = re.search(r"name='filename' value='([^']+)'", t)
    if fn:
        c = requests.post("https://mopsov.twse.com.tw/server-java/t105sb02", headers=H, timeout=30,
                          data={"firstin": "true", "step": "10", "filename": fn.group(1)})
        print("CSV", c.status_code, c.headers.get("content-type"), len(c.content))
        print(c.content[:800].decode("big5", "replace") if c.content else "")
