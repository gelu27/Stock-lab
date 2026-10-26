import sys, pandas as pd
sys.path.insert(0, ".")
import update_data as u
u.抓融資金額(天數=5)
print(open("data/margin_total.csv").read())
u.抓期貨未平倉(天數=70)
print(pd.read_csv("data/futures_oi.csv").tail(8).to_string())
print(len(pd.read_csv("data/futures_oi.csv")))
