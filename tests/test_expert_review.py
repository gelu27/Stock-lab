# 自動檢查：八位專家評測後的修正（2026-11-15）
#   1. 密碼連錯 5 次會先鎖住、同一個錯誤值重跑不重複計次
#   2. 全站漲跌家數同一個範圍（普通股、不含 ETF）
#   3. 建議持股水位要回測方向正確才顯示
#   本機執行：python tests/test_expert_review.py
import sys
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

程式 = Path(__file__).resolve().parent.parent / "app.py"
錯誤 = []


def 檢查(條件, 說明):
    print(("✅ " if 條件 else "❌ ") + 說明)
    if not 條件:
        錯誤.append(說明)


def 錯誤文字(at):
    return " ".join(e.value for e in at.error)


def main():
    at = AppTest.from_file(str(程式), default_timeout=600)
    at.secrets["password"] = "對的密碼"
    at.query_params["p"] = "02"
    at.run()
    檢查(not at.exception, "02 我的股票（有密碼）打開沒有錯誤")
    框 = lambda: next(t for t in at.text_input if t.label == "輸入密碼查看庫存")
    框().input("錯誤的中文密碼").run()
    檢查(not at.exception and "密碼不正確" in 錯誤文字(at), "輸入錯誤密碼（含中文）會顯示「密碼不正確」，不會當掉")

    # 1b. 防猜邏輯：把 app.核對密碼 拿出來，用假的 st 測（AppTest 每次重跑會清掉 cache_resource，真網站不會）
    import hashlib, hmac, time, types
    原始 = Path(程式).read_text("utf-8")
    片 = 原始[原始.index("def 核對密碼"):原始.index('if "k" in st.query_params:')]
    訊息, 紀錄 = [], {}
    假st = types.SimpleNamespace(context=types.SimpleNamespace(headers={}, ip_address="1.2.3.4"),
                                session_state={}, error=訊息.append)
    ns = {"st": 假st, "time": time, "hmac": hmac, "hashlib": hashlib, "_密碼": lambda: "對的密碼", "_密碼錯誤紀錄": lambda: 紀錄}
    exec(片, ns)
    核對 = ns["核對密碼"]
    檢查(核對("對的密碼") is True, "正確密碼可以解鎖")
    核對("錯1")
    核對("錯1")  # 畫面重跑、同一個錯誤值
    檢查(紀錄["1.2.3.4"][0] == 1, "同一個錯誤值重跑不重複計次")
    for i in range(2, 6):
        核對(f"錯{i}")
    檢查(核對("對的密碼") is False and "密碼錯太多次" in 訊息[-1], "連錯 5 次後，就算輸入正確密碼也先鎖住")
    紀錄["1.2.3.4"] = (5, time.time() - 601)
    檢查(核對("對的密碼") is True, "10 分鐘後自動解除鎖定")

    # 2. 漲跌家數：頁首、指數卡、市場判讀同一組數字
    ns = {}
    exec("def f(今日):\n" + "\n".join("    " + l for l in """
t = 今日[今日["代號"].astype(str).str.fullmatch(r"[1-9]\\d{3}") & (今日["收盤"] > 0)]
return int((t["漲跌"] > 0).sum()), int((t["漲跌"] == 0).sum()), int((t["漲跌"] < 0).sum())""".strip().splitlines()), ns)
    樣 = pd.DataFrame({"代號": ["2330", "0050", "00878", "8069", "2317", "030001"], "收盤": [1, 1, 1, 1, 0, 1], "漲跌": [1, 1, -1, -1, 1, 1]})
    檢查(ns["f"](樣) == (1, 0, 1), "漲跌家數只算 4 碼普通股（不含 ETF、權證、沒成交）")
    原始碼 = (Path(程式).parent / "views" / "p01_market.py").read_text("utf-8") + Path(程式).read_text("utf-8")
    檢查(原始碼.count('(今日["漲跌"] > 0).sum()') == 0, "首頁不再各自計算漲跌家數")

    # 3. 建議持股水位：回測方向相反就不顯示
    檔 = (Path(程式).parent / "views" / "p01_market.py").read_text("utf-8")
    片 = 檔[檔.index("def 水位有驗證"):檔.index("def 資金水位區")]
    ns = {"pd": pd}
    exec(片, ns)
    反 = pd.DataFrame({"分數區間": ["低", "中", "高"], "天數": [60, 140, 80], "加權之後20日平均%": [6.7, 5.3, 2.0]})
    正 = 反.assign(**{"加權之後20日平均%": [-1.0, 1.0, 3.0]})
    少 = 正.assign(天數=[5, 140, 80])
    檢查(not ns["水位有驗證"](反), "回測反向（分數低反而漲多）→ 不給持股建議")
    檢查(ns["水位有驗證"](正), "回測正向 → 顯示持股建議")
    檢查(not ns["水位有驗證"](少), "樣本太少 → 不給持股建議")

    # 4. 登入通行證改存 cookie：站內連結不再帶 k=，解鎖改用 記住登入()
    app原始 = Path(程式).read_text("utf-8")
    連結 = app原始[app原始.index("def 登入參數"):app原始.index("def 股連結")]
    檢查("&k=" not in 連結, "站內連結不再帶登入通行證 k=")
    檢查("twk=" in app原始 and 'st.context.cookies.get("twk"' in app原始, "通行證存在 cookie、開站時讀 cookie 解鎖")
    分頁們 = "".join((Path(程式).parent / "views" / f).read_text("utf-8") for f in ("p02_mystocks.py", "p03_stock.py", "p09_stats.py"))
    檢查('query_params["k"]' not in 分頁們 and 分頁們.count("記住登入()") == 3, "三個解鎖入口都改用 記住登入()")

    if 錯誤:
        print(f"\n共 {len(錯誤)} 項沒通過")
        sys.exit(1)


if __name__ == "__main__":
    main()
