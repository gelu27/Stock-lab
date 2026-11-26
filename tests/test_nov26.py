"""2026-11-26：看盤軟體「資券」頁（每日資券明細）、法人 1～60 日累計排行、三率三升徽章。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402
import glance  # noqa: E402


def test_三率三升():
    單季 = pd.DataFrame({
        "code": ["A"] * 5 + ["B"] * 5,
        "quarter": ["2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"] * 2,
        "年": ["2025", "2025", "2025", "2026", "2026"] * 2, "季": [2, 3, 4, 1, 2] * 2,
        "毛利率": [30, 31, 32, 33, 34, 30, 29, 28, 27, 26.0],
        "營益率": [10, 11, 12, 13, 14, 10, 9, 8, 7, 6.0],
        "淨利率": [8, 9, 10, 11, 12, 8, 7, 6, 5, 4.0]})
    m = engine.毛利率表(單季)
    assert bool(m.at["A", "三率三升"]) and not bool(m.at["A", "三率三降"])
    assert bool(m.at["B", "三率三降"]) and not bool(m.at["B", "三率三升"])
    assert m.at["A", "淨利率年增"] == 4


def test_三升徽章():
    今 = pd.DataFrame({"代號": ["A", "B"], "收盤": [10.0, 10.0], "本益比": [np.nan, np.nan], "三率三升": [True, False], "三率三降": [False, True]})
    b = glance.徽章表(["A", "B"], 今, 體檢={}, 期貨=set(), 位階表=pd.DataFrame())
    assert "三升" in b.at["A", "徽章"] and "三降" in b.at["B", "徽章"]


def test_資券明細與法人累計():
    t = engine.資券明細("2330", 30)
    assert t is not None and len(t) >= 20
    for 欄 in ("資增減", "融資餘額", "券增減", "融券餘額", "券資比", "當沖張數", "借券賣出", "借券餘額"):
        assert 欄 in t.columns
    d = t.dropna(subset=["融資餘額"])
    assert np.allclose(d["融資餘額"].diff().iloc[1:], d["資增減"].iloc[1:], equal_nan=True)
    累 = engine.法人累計表((1, 5, 60))
    assert {"外資_1_張", "投信_5_億", "合計_60_張"} <= set(累.columns)
    # 60 日累計包含 1 日
    x = 累.dropna(subset=["外資_1_張", "外資_60_張"])
    assert len(x) > 1000



def test_報告資券段落():
    t = engine.資券明細("2330", 120)
    標, 點 = engine.資券解讀(t)
    assert 標 and any("融資餘額" in x for x in 點) and any("回測提醒" in x for x in 點)
    文 = engine.資券摘要(t)
    assert 文.count("\n") >= 10 and "判讀" in 文
    assert engine.資券一行(t).startswith("🏦 資 ")
    assert engine.資券解讀(None) is None and engine.資券摘要(None) == "" and engine.資券一行(None) == ""
    import report
    assert report.資券圖(t) is not None


if __name__ == "__main__":
    for 名, f in list(globals().items()):
        if 名.startswith("test_"):
            f()
            print("OK", 名)
