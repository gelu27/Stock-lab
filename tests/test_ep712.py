# 股癌 EP712 功能（國安基金、季線保衛戰、季線乖離、VIX 跳升、融資佔股本、砍單長鞭）的小測試：python tests/test_ep712.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def K線(c, 起="2024-01-01"):
    日 = pd.bdate_range(起, periods=len(c))
    return pd.DataFrame({"date": 日, "open": c, "high": c, "low": c, "close": c})


def main():
    # 季線狀態：漲到 200 → 跌到 150（−25%）→ 彈上季線並守住
    c = np.r_[np.linspace(100, 200, 200), np.linspace(199, 150, 40)]
    K = K線(c)
    狀 = engine.季線狀態(K)
    assert 狀["燈"] == "🔴" and 狀["狀態"] == "等站上季線", 狀
    c2 = np.r_[c, np.linspace(152, 215, 30)]
    狀 = engine.季線狀態(K線(c2))
    assert 狀["燈"] == "🟢", 狀
    # 站上後跌回
    ma60 = pd.Series(c).rolling(60).mean().iloc[-1]
    c3 = np.r_[c, np.linspace(152, ma60 + 25, 12), np.linspace(ma60 + 20, 140, 8)]
    狀 = engine.季線狀態(K線(c3))
    assert 狀["燈"] == "🟠", 狀
    # 只觀察了 3 天
    c4 = np.r_[c, np.linspace(152, ma60 + 20, 10)]
    k4 = K線(c4)
    s = k4["close"]; m = s.rolling(60).mean()
    上 = int(np.argmax((s > m).to_numpy() & (s.shift() <= m.shift()).to_numpy() & (np.arange(len(s)) > 200)))
    狀 = engine.季線狀態(k4)
    assert 狀["燈"] == "🟡" and 狀["第幾天"] == len(s) - 1 - 上, 狀
    print("✅ 季線狀態正常")

    事 = engine.季線站上事件(pd.Series(c2, index=pd.bdate_range("2024-01-01", periods=len(c2))))
    assert len(事) == 1 and not 事["又跌破"].iloc[0], 事
    統 = engine.季線站上統計(pd.concat([事, 事.assign(又跌破=True)]))
    assert set(統["分組"]) == {"站穩", "又跌破"}, 統
    print("✅ 季線站上統計正常")

    乖 = engine.季線乖離位置(K)
    assert 乖["乖離%"] < -10 and len(乖["段落"]) == 1 and 乖["百分位"] == 0, 乖
    print("✅ 季線乖離位置正常")

    # 國安基金：決議日收盤 150，之後 +10%
    c5 = np.r_[c, np.full(5, 165.0)]
    K5 = K線(c5)
    d = K5["date"].iloc[239]
    紀 = pd.DataFrame([{"次": "1", "決議日": "2000-03", "退場日": "", "事件": "舊", "投入億": "", "獲利億": "", "備註": ""},
                      {"次": "2", "決議日": f"{d:%Y-%m-%d}", "退場日": "", "事件": "新", "投入億": "", "獲利億": "", "備註": ""}])
    表, 本 = engine.國安基金統計(K5, 紀)
    assert pd.isna(表.loc[0].get("收盤")) and 表.loc[1, "收盤"] == 150 and 表.loc[1, "1日%"] == 10.0, 表
    assert 本["已過交易日"] == 5 and 本["目前%"] == 10.0, 本
    print("✅ 國安基金統計正常")

    # VIX：第 10 天跳升 60%，指數之後每天 +1%
    日 = pd.bdate_range("2020-01-01", periods=300)
    v = pd.Series(15.0, index=日); v.iloc[10] = 24.0
    p = pd.Series(100 * 1.01 ** np.arange(300), index=日)
    表, _ = engine.VIX跳升統計(v, p, 天數=(5, 20))
    r = 表[表["條件"] == "VIX 單日跳升 ≥ 50%"].iloc[0]
    assert r["次數"] == 1 and abs(r["5日平均%"] - 5.1) < 0.05, 表
    表2, _ = engine.VIX跳升統計(v, p, 天數=(5,), 隔天=True)
    assert 表2.iloc[1]["次數"] == 1
    assert engine.VIX今日觸發(v) == []
    v2 = v.copy(); v2.iloc[-1] = 30.0
    觸 = engine.VIX今日觸發(v2)
    assert 觸 and 觸[0][1] == "VIX 單日跳升 ≥ 50%", 觸
    print("✅ VIX 跳升統計正常")

    今 = pd.DataFrame({"代號": ["1111", "2222", "3333"], "融資餘額": [1000, 500, 0], "發行股數": [1e7, 1e8, 1e8],
                      "成交值億": [1, 1, 1]})
    t = engine.加融資佔股本(今)
    assert t["融資佔股本%"].tolist() == [10.0, 0.5, 0.0] and t["融資佔股本排名%"].iloc[0] == 100, t
    榜 = engine.籌碼不安定榜(t)
    assert 榜["代號"].tolist() == ["1111", "2222"], 榜
    print("✅ 融資佔股本正常")

    # 砍單長鞭：小料件先衰退
    月 = pd.date_range("2022-01-01", periods=30, freq="MS").strftime("%Y-%m")
    列 = []
    for code in ["2327", "2492"]:   # 被動元件概念股
        for i, m in enumerate(月):
            列.append({"code": code, "month": m, "revenue": 100 if i < 18 else 50})
    for code in ["2330"]:
        for i, m in enumerate(月):
            列.append({"code": code, "month": m, "revenue": 100 + i})
    表, 燈 = engine.砍單長鞭(pd.DataFrame(列))
    assert 表["被動元件"].iloc[-1] == 100 and 燈["燈"] in ("🟡", "🔴"), (表.tail(), 燈)
    print("✅ 砍單長鞭正常")
    assert len(engine.讀取說法查核()) >= 15 and len(engine.讀取Permit追蹤()) >= 1 and len(engine.讀取國安基金()) >= 10
    print("✅ 資料檔正常")


if __name__ == "__main__":
    main()
