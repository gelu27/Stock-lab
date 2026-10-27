# 暫時用：在 GitHub Actions 實際跑新的下載函式，看結果（測完就刪）
import sys
import time
sys.path.insert(0, ".")
import pandas as pd
import update_data as u

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
for 名, 工作, 檔 in (("選擇權", u.抓選擇權, ["options_pc.csv", "options_inst.csv", "options_oi.csv"]),
                    ("新股申購", u.抓新股申購, ["ipo.csv"]),
                    ("外資持股", lambda: u.抓外資持股(3), ["qfii.csv.gz"]),
                    ("當沖", lambda: u.抓當沖(3), ["daytrade.csv.gz", "daytrade_market.csv"]),
                    ("庫藏股", u.抓庫藏股, ["buyback.csv"]),
                    ("可轉債", u.抓可轉債, ["cb.csv"]),
                    ("財報", lambda: u.抓財報(2), ["fundamental/balance.csv", "fundamental/cashflow.csv"])):
    t0 = time.time()
    try:
        工作()
    except Exception as e:
        import traceback
        traceback.print_exc()
    print(f"##### {名} 花 {time.time() - t0:.0f} 秒")
    for f in 檔:
        p = u.資料夾 / f
        if p.exists():
            t = pd.read_csv(p, dtype=str)
            print(f"--- {f} {len(t)} 列 {p.stat().st_size // 1024} KB\n{t.head(4)}\n{t.tail(3)}")
            if f in ("fundamental/balance.csv", "fundamental/cashflow.csv", "qfii.csv.gz", "daytrade.csv.gz"):
                print(t[t["code"].isin(["2330", "2881", "6488", "5274"])].tail(8))
        else:
            print(f"--- {f} 沒有產生")
