"""2026-11-13 網紅摘要建議：輝達事件週、反彈延續燈、國安隔日／一季、營收動能、價位量級提示。直接執行：python tests/test_nov13.py"""
import sys, pathlib
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import engine


def main():
    # 反彈延續燈：美股、加權都在上升、匯率持平 → 🟢；加權急跌 + 台幣重貶 → 🔴
    日 = pd.bdate_range("2026-09-01", periods=40)
    美 = pd.DataFrame({"費城半導體": np.linspace(100, 140, 40), "那斯達克": np.linspace(100, 130, 40)}, index=日)
    匯 = pd.DataFrame({"date": 日, "usdtwd": np.full(40, 32.0)})
    K = pd.DataFrame({"date": 日, "close": np.linspace(100, 140, 40)})
    燈 = engine.反彈延續燈(美, 匯, K)
    assert 燈["燈"] == "🟢" and all(v for _, v in 燈["條件"]), 燈
    K2 = K.assign(close=np.r_[np.linspace(100, 140, 35), 130, 125, 120, 118, 115])
    匯2 = 匯.assign(usdtwd=np.r_[np.full(34, 32.0), 32.2, 32.4, 32.6, 32.8, 33.0, 33.2])
    燈2 = engine.反彈延續燈(美, 匯2, K2)
    assert 燈2["燈"] == "🔴", 燈2
    assert engine.反彈延續燈(None, None, None) is None
    engine.反彈延續回測(美, 匯, K)  # 不能報錯

    # 國安隔日／一季
    表 = pd.DataFrame({"1日%": [np.nan, 4.0, -1.0, 3.5], "60日%": [np.nan, 10.0, -5.0, np.nan]})
    驗 = engine.國安隔日一季(表)
    assert 驗["隔日次數"] == 3 and 驗["隔日噴出"] == 2 and 驗["一季次數"] == 2 and 驗["一季上漲"] == 1, 驗
    assert engine.國安隔日一季(pd.DataFrame()) is None

    # 營收動能：A 近 3 月年增 > 近 12 月年增；B 相反；C 基期太小
    月 = [f"{y}-{m:02d}" for y in (2024, 2025, 2026) for m in range(1, 13)][:34]
    列們 = []
    for 碼, 前, 後 in (("1111", 1.0, 1.6), ("2222", 1.5, 1.0), ("3333", 0.001, 1.0)):
        for i, m in enumerate(月):
            列們.append({"code": 碼, "month": m, "revenue": 1e6 * (1 if i < 12 else (前 if i < 31 else 後))})
    for 碼 in ["x%02d" % i for i in range(60)]:  # 讓每個月家數 >= 50
        for m in 月:
            列們.append({"code": 碼, "month": m, "revenue": 1e6})
    t = engine.營收動能名單(營收=pd.DataFrame(列們))
    assert list(t["代號"][:1]) == ["1111"] and "2222" not in set(t["代號"]) and "3333" not in set(t["代號"]), t.head()

    # 價位量級提示：說 66 元、現價 667 → 提示；說 650 元、現價 667 → 不提示
    影片 = [{"頻道": "甲", "日期": "2026-11-12", "股票": [
        {"代號": "3189", "名稱": "景碩", "理由": "殺至66元跌停", "原文看法": "看空"},
        {"代號": "1111", "名稱": "乙", "理由": "目標價650元", "原文看法": "看多"}]}]
    提 = engine.價位量級提示(影片, {"3189": 667.0, "1111": 667.0}, 今天="2026-11-13")
    assert len(提) == 1 and 提.iloc[0]["股票"].startswith("3189"), 提
    print("✅ test_nov13 通過")


if __name__ == "__main__":
    main()
