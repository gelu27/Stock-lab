import requests, time
H = {"User-Agent": "Mozilla/5.0 (personal stock dashboard)"}
SEC = {"User-Agent": "stock-lab personal research gelu27@gmail.com"}
def tryit(name, f, n=500):
    try:
        r = f(); print(f"\n===== {name} status={r.status_code}\n{r.text[:n]}")
    except Exception as e: print(f"\n===== {name} ERROR {e!r}")
tryit("fred long timeout", lambda: requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL&cosd=2025-01-01", headers=H, timeout=120))
tryit("bls v2 post", lambda: requests.post("https://api.bls.gov/publicAPI/v2/timeseries/data/", json={"seriesid": ["CUSR0000SA0", "CES0000000001"], "startyear": "2025", "endyear": "2026"}, headers=H, timeout=60), 800)
tryit("sec companyconcept", lambda: requests.get("https://data.sec.gov/api/xbrl/companyconcept/CIK0000789019/us-gaap/PaymentsToAcquirePropertyPlantAndEquipment.json", headers=SEC, timeout=60), 300)
p2 = int(time.time()); p1 = p2 - 3 * 365 * 86400
tryit("yahoo timeseries", lambda: requests.get(f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/MSFT?type=quarterlyCapitalExpenditure,quarterlyOperatingCashFlow&period1={p1}&period2={p2}", headers=H, timeout=60), 1500)
