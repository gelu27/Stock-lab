import requests, json
H = {"User-Agent": "Mozilla/5.0"}
for u in ["https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci", "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_basi",
          "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci"]:
    try:
        r = requests.get(u, headers=H, timeout=30); d = r.json()
        print(u, r.status_code, len(d)); print(json.dumps(d[0], ensure_ascii=False)[:900])
        x = [v for v in d if v.get("公司代號", v.get("SecuritiesCompanyCode")) in ("2330", "3264")]
        print(json.dumps(x[:1], ensure_ascii=False)[:600])
    except Exception as e: print(u, "ERR", e)
for typek in ("sii", "otc"):
    try:
        r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t163sb04", headers=H, timeout=60,
                          data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y",
                                "TYPEK": typek, "year": "114", "season": "04"})
        print("t163sb04", typek, r.status_code, len(r.text)); t = r.text
        i = t.find("2330"); print(t[:300].replace("\n", " ")); print(t[i-200:i+800].replace("\n", " ") if i > 0 else "no 2330")
    except Exception as e: print("t163sb04 ERR", e)
