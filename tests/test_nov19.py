"""2026-11-19 網紅摘要建議：打折本益比、落底五訊號、融資減未破低、主動式 ETF 相對大盤、分批買試算。直接執行：python tests/test_nov19.py"""
import sys, pathlib
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import engine


def main():
    # 打折本益比：用真實預估檔，2330 收 2100 → 打 8 折本益比 ≈ 17.5
    今 = pd.DataFrame({"代號": ["2330", "9999"], "名稱": ["台積電", "無預估"], "收盤": [2100.0, 10.0]})
    t = engine.打折本益比(今, 折=0.8)
    if len(t):
        r = t[t["代號"] == "2330"].iloc[0]
        assert abs(r["打折後本益比"] - r["原本益比"] / 0.8) < 0.2 and 9999 not in t["代號"].tolist()
    assert engine.打折本益比(None).empty

    # 落底五訊號
    日 = pd.bdate_range("2026-09-01", periods=40)
    c = np.r_[np.linspace(100, 120, 30), 118, 112, 108, 106, 106, 107, 108, 109, 109.5, 110]
    K = pd.DataFrame({"date": 日, "open": c + 1, "high": c + 2, "low": c - 1, "close": c})
    量 = pd.Series(np.r_[np.full(30, 1000.0), 2000, 2000, 1800, 1500, 600, 500, 500, 550, 520, 500], index=日)
    融 = pd.Series(np.r_[np.full(34, 1e9), 9.9e8, 9.8e8, 9.7e8, 9.6e8, 9.5e8, 9.4e8], index=日)
    台 = pd.Series(c * 10, index=日)
    台.iloc[-10:-5] = [1000, 990, 980, 970, 975]
    台.iloc[-5:] = [1000, 1010, 1020, 1030, 1040]
    s = engine.落底五訊號(K, 量, 融, 台)
    assert len(s) == 5 and s[0]["亮"] is True and s[2]["亮"] is True and s[3]["亮"] is True, s
    assert engine.落底五訊號(K, None, None, None)[0]["亮"] is None

    # 融資減未破低：A 融資 5000→3500 且沒破低；B 融資減但破前低；C 融資沒減
    日 = pd.bdate_range("2026-06-01", periods=80)
    列 = []
    for 碼, 融1, 融2, 末 in (("1111", 5000, 3500, 100), ("2222", 5000, 3500, 50), ("3333", 5000, 4900, 100)):
        for i, d in enumerate(日):
            收 = 100.0 if i < 70 else 末
            列.append({"date": d, "代號": 碼, "名稱": 碼, "收盤": 收, "融資餘額": 融1 if i < 70 else 融2, "成交張數": 5000})
    名 = engine.融資減未破低名單(pd.DataFrame(列))
    assert list(名["代號"]) == ["1111"], 名

    # 主動式 ETF 相對大盤
    日 = pd.bdate_range("2026-08-01", periods=40)
    K2 = pd.DataFrame({"date": 日, "close": np.linspace(100, 90, 40)})
    列 = [{"date": d, "代號": "00999A", "名稱": "測試A", "收盤": v} for d, v in zip(日, np.linspace(20, 14, 40))]
    相 = engine.主動式ETF相對大盤(pd.DataFrame(列), K2)
    assert len(相) == 1 and 相.loc[0, "20日相對%"] < 0, 相

    # 分批買：120 萬、100/110/120 → 平均成本約 112.8
    明, 摘 = engine.分批買試算(1_200_000, [100, 110, 120], 95)
    assert 摘["每份"] == 200000 and 摘["已投入"] == 1200000 and abs(摘["平均成本"] - 112.82) < 0.01 and 摘["停損虧損"] < 0, 摘
    assert engine.分批買試算(0, [1, 2, 3])[0].empty
    print("✅ 11/19 建議 6 項正常")


if __name__ == "__main__":
    main()
