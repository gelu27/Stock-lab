"""2026-11-11 網紅摘要建議：降評利空測試、連板統計、無量上漲回測、族群連續流入、台幣×外資警示。直接執行：python tests/test_nov11.py"""
import sys, pathlib
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import engine


def 假指標():
    日 = pd.bdate_range("2026-09-01", periods=40)
    列們 = []
    for 碼, 收 in (("1111", np.r_[np.full(30, 100.0), 110, 121, 133.1, np.full(7, 133.1)]), ("2222", np.full(40, 50.0))):
        前 = np.r_[收[0], 收[:-1]]
        開 = np.where(碼 == "2222", 49.0, 前)
        列們.append(pd.DataFrame({"date": 日, "代號": 碼, "名稱": 碼, "open": 開, "high": 收, "low": 收 - 1, "收盤": 收,
                               "日報酬": (收 / 前 - 1), "還原價": 收, "漲跌幅": (收 / 前 - 1) * 100, "value": 1e8,
                               "外資買超": -100.0}))
    return pd.concat(列們, ignore_index=True)


def main():
    p = 假指標()
    # 連板：1111 在第 31～33 天連三個漲停
    今, 統 = engine.連板統計(p)
    assert len(統) == 3 and 統.iloc[1]["條件"] == "連板第 2 天收盤"
    # 降評利空測試：2222 開 49（低於昨收 50）收 50 → 過關；1111 沒有降評
    報 = [{"日期": "2026-09-30", "代號": "2222", "名稱": "乙", "券商": "甲", "目標價": 60, "前次目標價": 80}]
    表, 摘 = engine.降評利空測試(報, p)
    assert len(表) == 1 and 表.iloc[0]["利空測試"] == "過關", 表
    assert engine.降評利空測試([], p)[0].empty
    # 無量上漲：不能報錯
    K = pd.DataFrame({"date": 假指標()["date"].unique(), "close": np.linspace(100, 120, 40)})
    assert len(engine.無量上漲回測(K, p)) == 4
    # 台幣×外資警示：匯率連兩天上升、外資賣超 → 🟠
    匯 = pd.DataFrame({"date": pd.bdate_range("2026-11-05", periods=3), "usdtwd": [32.7, 32.8, 32.9]})
    警 = engine.台幣外資警示(匯, p)
    assert 警 and 警["燈"] == "🟠", 警
    assert engine.台幣外資警示(None, p) is None
    print("✅ test_nov11 通過")


if __name__ == "__main__":
    main()
