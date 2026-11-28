# 2026-11-26 網紅摘要建議：外資止賣補燈、ETF 單日異動、前低守住、大反彈日：python tests/test_nov26.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lab1126  # noqa: E402


def main():
    日 = pd.bdate_range("2026-11-02", periods=6)
    # 補燈：外資連賣 → 紅；連 2 天買超 → 綠；美債連 2 天不升 → 綠
    賣 = pd.Series([-5, -3, -2.0], index=日[:3])
    assert lab1126.止賣補燈(賣, pd.Series([4.9, 4.8, 4.7]))[0][1] == "🔴"
    買 = pd.Series([-5, 3, 2.0], index=日[:3])
    燈 = lab1126.止賣補燈(買, pd.Series([4.7, 4.8, 4.7, 4.6]))
    assert 燈[0][1] == "🟢" and 燈[1][1] == "🟢", 燈
    assert lab1126.止賣補燈(None, None)[0][1] == "🟡"
    print("✅ 止賣補燈正常")

    # ETF 單日異動：00 開頭、±8% 以上才列
    列 = []
    for c, 收 in {"00999": [10, 12.8, 10], "0050": [100, 101, 102], "2330": [100, 130, 100]}.items():
        for d, v in zip(日[:3], 收):
            列.append({"date": d, "代號": c, "名稱": c, "收盤": v})
    異 = lab1126.ETF單日異動(pd.DataFrame(列), 門檻=8, 天數=5)
    assert set(異["代號"]) == {"00999"} and len(異) == 2, 異
    print("✅ ETF 單日異動正常")

    # 前低守住：基準日 low=100；A 一路在上、B 破到 90 後收 105、C 破後收 95
    d0 = pd.Timestamp("2026-11-02")
    列 = []
    資 = {"1111": [(100, 105), (101, 106), (102, 107)], "2222": [(100, 105), (90, 100), (95, 105)], "3333": [(100, 105), (90, 92), (90, 95)]}
    for c, 序 in 資.items():
        for i, (低, 收) in enumerate(序):
            列.append({"date": d0 + pd.Timedelta(days=i), "代號": c, "名稱": c, "low": 低, "收盤": 收, "成交值億": 5.0})
    表 = lab1126.前低守住表(pd.DataFrame(列), d0).set_index("代號")
    assert 表.loc["1111", "狀態"] == "沒破" and 表.loc["2222", "狀態"] == "破後收復" and 表.loc["3333", "狀態"] == "仍在前低下", 表
    print("✅ 前低守住分類正常")

    # 大反彈日：先單日 −3%，之後 +3% 觸發
    c = [100, 100, 97, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121]
    K = pd.DataFrame({"date": pd.bdate_range("2026-01-02", periods=len(c)), "close": c})
    r = lab1126.大反彈日回測(K)
    assert len(r["事件表"]) == 1 and r["事件表"]["當日%"].iloc[0] > 3, r["事件表"]
    print("✅ 大反彈日回測正常")


if __name__ == "__main__":
    main()
