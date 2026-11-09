# 加權大跌日收復表、跌停打開回測（網紅摘要 11/07 建議 5、6）
#   本機執行：python tests/test_crash_tools.py
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def main():
    日 = pd.bdate_range("2026-01-01", periods=10)
    K = pd.DataFrame({"date": 日, "close": [100, 100, 95, 96, 99, 101, 102, 90, 91, 92]})
    t = engine.大跌日收復表(K, 天數=(2,))
    assert list(t["跌幅%"]) == [-11.76, -5.0], t
    舊 = t.iloc[1]
    assert 舊["收復天數"] == 3 and 舊["之後最深%"] == 0.0 and 舊["2日後%"] == 4.21, 舊
    assert pd.isna(t.iloc[0]["收復天數"])
    統 = engine.大跌日統計(t, 天數=(2,))
    assert 統["次數"] == 2 and 統["已收復"] == 1

    價 = pd.DataFrame({"code": ["A"] * 5 + ["B"] * 5, "date": list(日[:5]) * 2,
                      "low": [100, 90, 95, 96, 97, 50, 45, 50, 51, 52],
                      "close": [100, 95, 96, 97, 98, 50, 45, 51, 52, 53]})
    事, 基 = engine.跌停打開事件(價, 天數=(2,))
    assert sorted(zip(事["代號"], 事["類型"])) == [("A", "打開"), ("B", "沒打開")], 事
    assert 事.set_index("代號").at["A", "2日後%"] == 2.11
    統 = engine.跌停打開統計(事, 基, 天數=(2,))
    assert list(統["類型"]) == ["全部", "打開", "沒打開", "任何一天買進"]
    print("✅ 大跌日收復表、跌停打開回測")


if __name__ == "__main__":
    main()
