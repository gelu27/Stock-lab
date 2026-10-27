import sys, pandas as pd
sys.path.insert(0, ".")
import update_data as u
u.抓指數K線()
u.抓美股日線()
t = pd.read_csv("data/index_ohlc.csv")
print(t.groupby("symbol").agg(n=("date", "size"), first=("date", "min"), last=("date", "max")))
print(t.tail(4)); print(t[t.symbol == "TPEX"].tail(4))
u2 = pd.read_csv("data/us_daily.csv"); print(u2[u2.symbol == "^SOX"].tail(3))
