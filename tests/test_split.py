# 自動檢查：面額分割後本益比、殖利率、淨值比、EPS 有換成新股數基準
#   本機執行：python tests/test_split.py
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402

假分割 = pd.DataFrame({"code": ["9999"], "date": [pd.Timestamp("2026-09-02")], "倍數": [3.0]})
engine.分割紀錄 = lambda: 假分割


def main():
    錯誤 = []

    def 檢查(名, 實際, 預期, 容許=0.01):
        if abs(實際 - 預期) > 容許:
            錯誤.append(f"{名}：得到 {實際}，應該是 {預期}")

    # 交易所沒調整：分割後本益比掉成 1/3 → 換算回來；交易所改好的那天起就不再換算
    日 = pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03"])
    表 = pd.DataFrame({"date": 日, "code": "9999", "close": [3000.0, 1000.0, 1000.0],
                       "pe": [30.0, 10.0, 30.0], "pb": [9.0, 3.0, 9.0], "dy": [2.0, 6.0, 2.0]})
    表 = engine.修正分割估值(表)
    for i, (pe, pb, dy) in enumerate([(30, 9, 2), (30, 9, 2), (30, 9, 2)]):
        檢查(f"第 {i} 天本益比", float(表["pe"][i]), pe)
        檢查(f"第 {i} 天淨值比", float(表["pb"][i]), pb)
        檢查(f"第 {i} 天殖利率", float(表["dy"][i]), dy)

    # 財報 EPS：分割前公布的季報除以 3，分割後公布的不動
    t = pd.DataFrame({"code": "9999", "quarter": ["2026Q1", "2026Q2", "2026Q3"], "eps": [30.0, 60.0, 30.0],
                      "netinc": [300.0, 600.0, 900.0]})
    t = engine.調整分割EPS(t)
    for q, 預期 in zip(t["quarter"], [10, 20, 30]):
        檢查(f"{q} EPS", float(t.loc[t["quarter"] == q, "eps"].iloc[0]), 預期)

    檢查("分割前的倍數", engine.分割倍數("9999", "2026-08-01"), 3)
    檢查("分割後的倍數", engine.分割倍數("9999", "2026-09-02"), 1)

    for e in 錯誤:
        print("❌", e)
    if 錯誤:
        sys.exit(1)
    print("✅ 面額分割換算正常")


if __name__ == "__main__":
    main()
