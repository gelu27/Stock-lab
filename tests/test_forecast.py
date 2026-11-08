# 自動檢查：預估 EPS（三源）共識、預估本益比、隱含剩餘 EPS、選股條件
#   本機執行：python tests/test_forecast.py
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def main():
    錯誤 = []

    def 檢查(名, 實際, 預期, 容許=0.01):
        if not (abs(float(實際) - 預期) <= 容許):
            錯誤.append(f"{名}：得到 {實際}，應該是 {預期}")

    暫 = Path(tempfile.mkdtemp())
    (暫 / "forecast").mkdir()
    pd.DataFrame({"code": ["9991", "9992", "9993"], "A_2026": [10.0, 2.0, -1.0], "B_2026": [12.0, np.nan, np.nan],
                  "Vera_2026": [5.0, 2.1, np.nan], "A_2027": [15.0, np.nan, np.nan], "B_2027": [13.0, np.nan, np.nan]}
                 ).to_csv(暫 / "forecast" / "eps_forecast_20261107.csv", index=False)
    pd.DataFrame({"code": ["9991"], "A_2026": [1.0]}).to_csv(暫 / "forecast" / "eps_forecast_20260901.csv", index=False)
    原資料夾, 原四季 = engine.資料夾, engine.近四季EPS表
    engine.資料夾 = 暫
    engine.近四季EPS表 = lambda: pd.DataFrame({"近四季EPS": [9.0, 3.0], "EPS季度": ["2026Q2", "2025Q4"], "單季EPS": [3.0, 1.0],
                                              "累計EPS": [5.0, 3.0]}, index=pd.Index(["9991", "9992"], name="code"))
    try:
        t = engine.預估EPS表()
    finally:
        engine.資料夾, engine.近四季EPS表 = 原資料夾, 原四季
    檢查("取最新一份、A B 中位數", t.loc["9991", "預估EPS今年"], 11.0)
    檢查("明年中位數", t.loc["9991", "預估EPS明年"], 14.0)
    檢查("明年成長", t.loc["9991", "明年EPS成長%"], 27.3, 0.05)
    檢查("兩源差", t.loc["9991", "預估分歧%"], 18.0, 0.5)
    檢查("只有 A", t.loc["9992", "預估EPS今年"], 2.0)
    檢查("Vera 不納入", t.loc["9992", "預估來源數"], 1)
    檢查("隱含剩餘", t.loc["9991", "隱含剩餘EPS"], 6.0)
    檢查("隱含季成長（剩 2 季每季 3 元 vs 最新一季 3 元）", t.loc["9991", "隱含季成長%"], 0.0)
    if not pd.isna(t.loc["9992", "已公布累計EPS"]):
        錯誤.append("去年的累計 EPS 不該拿來跟今年預估比")
    if t["預估資料日"].iloc[0] != pd.Timestamp("2026-11-07"):
        錯誤.append(f"資料日應為 2026-11-07，得到 {t['預估資料日'].iloc[0]}")

    今 = pd.DataFrame({"代號": ["9991", "9992", "9993"], "收盤": [110.0, 30.0, 50.0]}).join(t, on="代號")
    今 = engine.加預估本益比(今)
    檢查("預估本益比", 今.loc[0, "預估本益比"], 10.0)
    檢查("明年預估本益比", 今.loc[0, "明年預估本益比"], 7.9, 0.05)
    if not pd.isna(今.loc[2, "預估本益比"]):
        錯誤.append("預估虧損不該有本益比")
    for c in ("市場",):
        今[c] = "上市"
    文 = engine.預估EPS文字(今.iloc[0].to_dict())
    if "11.00" not in 文 or "後面還要賺 6.00" not in 文:
        錯誤.append(f"AI 文字缺數字：{文}")
    if engine.預估EPS文字({"預估EPS今年": np.nan}):
        錯誤.append("沒有預估時 AI 文字要是空的")

    if 錯誤:
        print("\n".join("❌ " + e for e in 錯誤))
        sys.exit(1)
    print("✅ 預估 EPS 檢查通過")


if __name__ == "__main__":
    main()
