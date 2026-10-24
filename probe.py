import pandas as pd, update_data as u
u.抓除權息()
d = pd.read_csv("data/fundamental/dividend.csv", dtype={"code": str})
print(d.groupby(d.date.str[:4]).size())
print(d[d.code.isin(["2330", "2454", "8299", "0056"])].tail(12).to_string())
print(pd.read_csv("data/fundamental/dividend_upcoming.csv").head(10).to_string())
u.抓集保()
import glob
f = sorted(glob.glob("data/tdcc/*.csv.gz"))[-1]
t = pd.read_csv(f, dtype={"code": str})
print(f, len(t)); print(t[t.code.isin(["2330", "2317", "8299", "0050"])].to_string())
