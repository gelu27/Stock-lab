import sys, pandas as pd
sys.path.insert(0, ".")
import update_data as u
u.抓期貨未平倉(天數=70)
print(pd.read_csv("data/futures_oi.csv").tail(5).to_string())
print(len(pd.read_csv("data/futures_oi.csv")))
# 3
