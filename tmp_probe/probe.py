import sys, os; sys.path.insert(0, os.getcwd())
import update_data as u, pandas as pd
for f in (u.抓美國數據, u.抓美股資本支出, u.抓內部人轉讓, u.抓興櫃推薦券商, u.抓重大訊息):
    try:
        f()
    except Exception as e:
        print(f.__name__, "ERROR", repr(e))
for n in ("us_macro.csv", "us_capex.csv", "insider_transfer.csv", "esb_dealers.csv", "material_news.csv"):
    p = u.資料夾 / n
    if p.exists():
        t = pd.read_csv(p); print("\n==", n, len(t)); print(t.tail(6).to_string()[:1500])
r = u.櫃買("https://www.tpex.org.tw/openapi/v1/tpex_esb_recommended_dealer") or []
print("\n== dealer raw", r[:2])
