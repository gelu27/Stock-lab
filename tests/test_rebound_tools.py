# 反彈力道、KD 止跌條件、反彈兩階段、國安平均、標普大跌後波動（網紅摘要 11/09）
#   本機執行：python tests/test_rebound_tools.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def main():
    日 = pd.bdate_range("2026-01-01", periods=40)
    收 = [100] * 20 + [96, 98.5, 99, 100, 101, 102, 103, 104, 105, 106] + [107] * 10
    K = pd.DataFrame({"date": 日, "close": 收, "high": [x + 0.5 for x in 收]})
    事, 統, 今 = engine.反彈首日(K, 天數=(2,))
    assert len(事) == 1 and 事.iloc[0]["大跌日"] == 日[20] and 事.iloc[0]["反彈日%"] == 2.6, 事
    assert 事.iloc[0]["類型"] in ("站上 5 日線", "碰線被壓", "沒碰到 5 日線")
    assert list(統["類型"])[0] == "全部" and 統.iloc[-1]["類型"] == "任何一天買進"

    c2 = [100 - i * 0.8 for i in range(30)] + [76 + i for i in range(10)]
    K2 = pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=40), "close": c2})
    事2, 統2, 今2 = engine.止跌KD條件(K2, 天數=(2,))
    assert 今2 and set(("KD 黃金交叉", "站上 5、10 日線", "離 20 日高%")) <= set(今2) and len(統2) == 2

    d = pd.bdate_range("2026-10-01", periods=8)
    列 = []
    for 碼, 起, 終, pe in (("1101", 100, 60, 10), ("2330", 100, 99, 30), ("3008", 100, 105, 5)):
        for i, t in enumerate(d):
            列.append({"code": 碼, "date": t, "close": 起 if i < 6 else (終 if i == 6 else 終 * (1.1 if 碼 == "1101" else 1.02)), "pe": pe})
    輪 = engine.反彈輪動(pd.DataFrame(列))
    assert 輪 and 輪["組別"].iloc[0]["檔數"] == 1 and 輪["組別"].iloc[1]["檔數"] == 1, 輪
    assert 輪["階段"].startswith("第一階段"), 輪["階段"]

    表 = pd.DataFrame({"20日%": [4.0, -2.0, np.nan], "60日%": [10.0, 5.0, 8.0]})
    均 = engine.國安基金平均(表, (20, 60))
    assert 均.iloc[0]["次數"] == 2 and 均.iloc[0]["平均%"] == 1.0 and 均.iloc[1]["上漲機率%"] == 100

    rng = np.random.default_rng(1)
    s = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.005, 600)), index=pd.bdate_range("2020-01-01", periods=600))
    s.iloc[300] = s.iloc[299] * 0.94
    波 = engine.單日大跌後波動(s)
    assert 波 and 波["次數"] >= 1
    print("✅ 反彈力道、KD 止跌、反彈兩階段、國安平均、標普大跌後波動")


if __name__ == "__main__":
    main()
