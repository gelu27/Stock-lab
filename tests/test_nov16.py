"""2026-11-16 網紅摘要建議：現增試算、投信作帳、財報壓力測試、ETF 破發、大跌日後回測、ETF 分割提示。直接執行：python tests/test_nov16.py"""
import sys, pathlib
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import engine


def main():
    # 現增：收盤 211、舊股 1 億、認購價 140、新股 1000 萬 → 參考價約 204.5、跌停約 184
    r = engine.現增試算(211, 1e8, 140, 1e7)
    assert abs(r["參考價"] - 204.55) < 0.01 and abs(r["跌停價"] - 184.09) < 0.01 and r["除權跌幅%"] < 0, r
    assert engine.現增試算(None, 1, 1, 1) is None and engine.現增試算(10, 0, 5, 1) is None
    申 = pd.DataFrame({"draw_date": [pd.Timestamp("2026-11-17"), pd.Timestamp("2026-09-01")], "code": ["6834", "1111"],
                       "name": ["天二", "舊"], "market": ["上市增資", "上市增資"], "list_date": [pd.Timestamp("2026-11-25")] * 2,
                       "price": [80.0, 10.0], "shares": [850000.0, 1000.0]})
    近 = engine.近期現增(申, {"6834": 100.0}, {"6834": 1e8}, 今日="2026-11-16")
    assert list(近["代號"]) == ["6834"] and 近.loc[0, "估參考價"] < 100, 近

    # 投信作帳：A 天天買、B 只買 5 天、C 漲太多
    日 = pd.bdate_range("2026-10-01", periods=30)
    列 = []
    for 碼, 買, 張, 末價 in (("A", 20, 8000, 110), ("B", 5, 8000, 110), ("C", 20, 8000, 200)):
        for i, d in enumerate(日):
            列.append({"date": d, "code": 碼, "name": 碼, "close": 100 + (末價 - 100) * i / 29, "trust": (張 * 1000 / 20 if i < 買 else -1000)})
    名 = engine.投信作帳名單(pd.DataFrame(列), {"A": 1e8, "B": 1e8, "C": 1e8})
    assert list(名["代號"]) == ["A"], 名
    assert engine.投信作帳名單(pd.DataFrame(列), {"A": 5e9, "B": 1e8, "C": 1e8}).empty  # 股本 > 100 億
    assert engine.投信作帳名單(None).empty

    # 財報壓力測試
    資 = pd.DataFrame({"date": list(日[-2:]) * 2, "code": ["3231"] * 2 + ["2317"] * 2, "close": [100.0, 90.0, 200.0, 220.0]})
    壓 = engine.財報壓力測試(資, 日[-2])
    assert list(壓["漲跌%"]) == [-10.0, 10.0], 壓

    # ETF 破發
    表 = engine.ETF破發表({"00400A": 9.5, "00401A": 10.8, "0050": 50.0}, {"00400A": "某"})
    assert list(表["代號"]) == ["00400A", "00401A"] and bool(表.loc[0, "破發"]) and not bool(表.loc[1, "破發"])
    assert engine.ETF破發表({}).empty

    # 大跌日後
    c = np.r_[np.full(5, 100.0), 90.0, np.linspace(91, 100, 25)]
    K = pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=len(c)), "close": c})
    驗 = engine.大跌日後回測(K)
    assert len(驗["事件"]) == 1 and 驗["事件"].loc[0, "當天%"] == -10.0 and 驗["彙總"].loc[0, "上漲機率%"] == 100, 驗
    assert 驗["再破低%"] == 0

    # ETF 分割
    分 = pd.DataFrame({"code": ["00662"], "date": [pd.Timestamp("2026-11-17")], "倍數": [5], "備註": [""]})
    assert len(engine.ETF分割提示("2026-11-16", 表=分)) == 1 and not engine.ETF分割提示("2026-12-30", 表=分)
    print("test_nov16 OK")


if __name__ == "__main__":
    main()
