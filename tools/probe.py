import sys; sys.path.insert(0, ".")
import update_data as u, requests
for 類 in ("sii", "otc"):
    r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t163sb04", headers=u.標頭, timeout=60,
                      data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y",
                            "TYPEK": 類, "year": "115", "season": "02"})
    import re
    print([re.sub(r"<[^>]+>|\s", "", t) for t in re.findall(r"<th[^>]*>(.*?)</th>", r.text, re.S)][:40])
    t = u._解析損益(r.text); print(類, len(t)); print(t[t["code"].isin(["2330", "2801", "3264", "2881"])])
r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t163sb04", headers=u.標頭, timeout=60,
                  data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y", "TYPEK": "sii", "year": "115", "season": "03"})
print("115Q3", len(u._解析損益(r.text)), r.text[-300:])
