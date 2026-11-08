# 止跌三階段、融資減幅比、長均線距離、三條件抄底、摘要混稿偵測的小測試：python tests/test_dip_tools.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def main():
    日 = pd.bdate_range("2026-01-01", periods=30)
    # 先跌到第 24 天的低點，之後 5 天反彈
    c = np.r_[np.linspace(100, 80, 24), [82, 84, 86, 88, 90, 92]]
    K = pd.DataFrame({"date": 日, "low": c - 1, "close": c})
    r = engine.止跌三階段(K)
    assert r["已到"] >= 2, r
    s4 = c[-4:].sum()
    assert abs(r["站回5日需"] - s4 / 4) < 0.01, r
    # 收盤正好等於「站回5日需」時，5 日線＝收盤
    x = r["站回5日需"]
    assert abs((s4 + x) / 5 - x) < 0.01
    y = r["金叉需"]
    s9 = c[-9:].sum()
    assert abs((s4 + y) / 5 - (s9 + y) / 10) < 0.01
    print("✅ 止跌三階段正常")

    # 指數從 100 跌到 90（−10%），融資同期減 8% → 比例 0.8 亮綠燈
    日 = pd.bdate_range("2026-01-01", periods=20)
    指 = pd.DataFrame({"date": 日, "close": np.r_[np.full(10, 100.0), np.linspace(99, 90, 10)]})
    變 = pd.Series(np.r_[np.zeros(10), np.full(10, (0.92 ** 0.1 - 1) * 100)], index=日)
    序 = engine.融資減幅比序列(變, 指)
    末 = 序.iloc[-1]
    assert abs(末["指數跌幅"] + 10) < 0.01 and abs(末["融資減幅"] + 8) < 0.05, 末
    assert engine.融資減幅燈(末)[0] == "🟢"
    print("✅ 融資減幅比正常")

    日 = pd.bdate_range("2025-01-01", "2026-06-30")
    歷 = pd.DataFrame({"code": "1234", "date": 日, "close": 100.0})
    距 = engine.長均線距離(歷)
    assert 距.loc["1234", "距年線%"] == 0 and 距.loc["1234", "距72週線%"] == 0, 距
    今日 = pd.DataFrame({"代號": ["1234"], "名稱": ["測試"], "收盤": [100.0], "融資洗完": [False],
                       "融資20日增減": [-12.0], "融資餘額": [500]})
    表 = engine.抄底三條件(今日, 距, {"1234": 5.0})
    assert len(表) == 1 and "年線" in 表.loc[0, "靠近支撐"], 表
    assert engine.抄底三條件(今日, 距, {"1234": -1.0}).empty   # 營收衰退不列
    print("✅ 三條件抄底正常")

    理 = ["記憶體剛性需求，前三季約 5 個資本額，近 400 元佈局", "光通訊量產未明、折舊壓毛利，百元保衛戰", "碳氫樹脂切入先進封裝，毛利率升到 32%"]
    a = {"頻道": "甲", "日期": "2026-11-03", "股票": [{"代號": c, "名稱": c, "理由": t} for c, t in zip(["1", "2", "3"], 理)]}
    b = {"頻道": "乙", "日期": "2026-11-04", "股票": [{"代號": c, "名稱": c, "理由": t + "。"} for c, t in zip(["1", "2", "3"], 理)]}
    丙 = {"頻道": "丙", "日期": "2026-11-04", "股票": [{"代號": c, "名稱": c, "理由": "完全不同的說法" + c} for c in ["1", "2", "3"]]}
    混 = engine.摘要混稿偵測([a, b, 丙])
    assert len(混) == 1 and {混[0]["頻道A"], 混[0]["頻道B"]} == {"甲", "乙"}, 混
    print("✅ 摘要混稿偵測正常")


if __name__ == "__main__":
    main()
