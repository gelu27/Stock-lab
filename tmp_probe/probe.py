import requests, datetime as dt, json
H = {"User-Agent": "Mozilla/5.0 (personal stock dashboard)"}
SEC = {"User-Agent": "stock-lab personal research gelu27@users.noreply.github.com"}
def show(name, r, n=600):
    print(f"\n===== {name} status={getattr(r,'status_code',r)}")
    try: print(r.text[:n])
    except Exception as e: print(e)
def tryit(name, f, n=600):
    try: show(name, f(), n)
    except Exception as e: print(f"\n===== {name} ERROR {e!r}")
for s in ["DX-Y.NYB", "CL=F", "HYG", "^TNX", "MSFT"]:
    tryit("yahoo " + s, lambda s=s: requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(s)}?range=5d&interval=1d", headers=H, timeout=30), 300)
tryit("fred CPI", lambda: requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL", headers=H, timeout=30), 200)
tryit("fred PAYEMS tail", lambda: requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=PAYEMS&cosd=2026-01-01", headers=H, timeout=30), 400)
def sec():
    r = requests.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json", headers=SEC, timeout=60)
    j = r.json(); u = j["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]["units"]["USD"]
    class R: status_code=r.status_code; text=json.dumps([x for x in u if "frame" in x][-6:])
    return R
tryit("sec MSFT capex", sec, 1500)
# MOPS 內部人持股轉讓事前申報
today = dt.date.today()
for page, data in [
    ("ajax_t56sb12_q1", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "year": str(today.year-1911), "month": f"{today.month:02d}"}),
    ("ajax_t56sb12_q1", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "all", "year": str(today.year-1911), "month": f"{today.month-1:02d}"}),
    ("ajax_t56sb12_q2", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "year": str(today.year-1911), "month": f"{today.month-1:02d}"}),
    ("ajax_t56sb12", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "year": str(today.year-1911), "month": f"{today.month-1:02d}"}),
    ("ajax_t05sr01_1", {"encodeURIComponent": 1, "step": 0}),
]:
    tryit("mops " + page + json.dumps(data, ensure_ascii=False), lambda page=page, data=data: requests.post(f"https://mopsov.twse.com.tw/mops/web/{page}", headers=H, data=data, timeout=60), 2500)
tryit("twse openapi insider transfer", lambda: requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap12_L", headers=H, timeout=60), 800)
tryit("tpex openapi insider transfer", lambda: requests.get("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap12_O", headers=H, timeout=60), 800)
tryit("tpex esb recommend broker", lambda: requests.get("https://www.tpex.org.tw/openapi/v1/tpex_esb_capitals_rank", headers=H, timeout=60), 400)
tryit("tpex openapi list", lambda: requests.get("https://www.tpex.org.tw/openapi/swagger.json", headers=H, timeout=60), 200)
def esbpaths():
    r = requests.get("https://www.tpex.org.tw/openapi/swagger.json", headers=H, timeout=60)
    class R: status_code=r.status_code; text="\n".join(p for p in r.json()["paths"] if "esb" in p.lower() or "emerging" in p.lower())
    return R
tryit("tpex esb paths", esbpaths, 3000)
def twsepaths():
    r = requests.get("https://openapi.twse.com.tw/v1/swagger.json", headers=H, timeout=60)
    j=r.json()
    class R: status_code=r.status_code; text="\n".join(f"{p} {v.get('get',{}).get('summary','')}" for p,v in j["paths"].items() if any(k in (v.get('get',{}).get('summary','')) for k in ("轉讓","董監","內部人")))
    return R
tryit("twse insider paths", twsepaths, 3000)
