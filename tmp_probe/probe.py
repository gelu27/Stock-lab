import sys; sys.path.insert(0, ".")
import update_data as u, pandas as pd
u.抓美股日線(); u.抓經濟行事曆(); u.抓美股財報()
for f in ("us_daily.csv", "econ_calendar.csv", "us_earnings.csv"):
    t = pd.read_csv(u.資料夾 / f); print(f, len(t)); print(t.tail(15).to_string())
t = pd.read_csv(u.資料夾 / "us_daily.csv"); print(t.groupby("symbol")["date"].agg(["min", "max", "count"]))
