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
    檢查("本業 EPS＝Vera", t.loc["9991", "預估本業EPS"], 5.0)
    檢查("預估業外占比", t.loc["9991", "預估業外占比%"], 55.0, 0.5)
    檢查("隱含剩餘", t.loc["9991", "隱含剩餘EPS"], 6.0)
    檢查("隱含季成長（剩 2 季每季 3 元 vs 最新一季 3 元）", t.loc["9991", "隱含季成長%"], 0.0)
    if not pd.isna(t.loc["9992", "已公布累計EPS"]):
        錯誤.append("去年的累計 EPS 不該拿來跟今年預估比")
    if t["預估資料日"].iloc[0] != pd.Timestamp("2026-11-07"):
        錯誤.append(f"資料日應為 2026-11-07，得到 {t['預估資料日'].iloc[0]}")
    檢查("跟上一份比的修正%", t.loc["9991", "預估修正%"], 1000.0)
    if t.loc["9991", "前期資料日"] != pd.Timestamp("2026-09-01"):
        錯誤.append("前期資料日應為 2026-09-01")

    # 原始匯出檔轉換
    原始 = pd.DataFrame({"股號": ["2330", "1101"], "公司": ["台積電", "台泥"], "收盤價": [2135, 26.75],
                         "A_2026E_EPS": [111.2, 0.87], "B_2027E_EPS": [149.96, np.nan], "Vera_2026E_EPS": [108.5, 1.05],
                         "A_2026PE": [19.2, 30.75]})
    轉 = engine.轉換預估檔(原始)
    if sorted(轉.columns) != sorted(["code", "A_2026", "B_2027", "Vera_2026"]):
        錯誤.append(f"轉換欄位不對：{list(轉.columns)}")

    # 驗證：兩份快照，上修股之後漲 10%、下修股跌 10%
    暫2 = Path(tempfile.mkdtemp())
    (暫2 / "forecast").mkdir()
    碼 = [f"8{i:03d}" for i in range(30)]
    pd.DataFrame({"code": 碼, "A_2026": 1.0}).to_csv(暫2 / "forecast" / "eps_forecast_20260105.csv", index=False)
    pd.DataFrame({"code": 碼, "A_2026": [1.2] * 10 + [0.8] * 10 + [1.0] * 10}).to_csv(
        暫2 / "forecast" / "eps_forecast_20260202.csv", index=False)
    日 = pd.bdate_range("2026-01-01", periods=60)
    價 = pd.DataFrame(100.0, index=日, columns=碼)
    進 = 日.searchsorted(pd.Timestamp("2026-02-02"), side="right")
    價.iloc[進 + 1:, :10] = 110.0
    價.iloc[進 + 1:, 10:20] = 90.0
    engine.資料夾 = 暫2
    try:
        驗, 說 = engine.預估修正驗證(價)
    finally:
        engine.資料夾 = 原資料夾
    if 驗 is None:
        錯誤.append(f"驗證沒有結果：{說}")
    else:
        檢查("上修減下修", 驗["上修減下修%"].iloc[0], 20.0)

    # 河流位置
    h = pd.DataFrame({"本益比": np.linspace(10, 20, 101)})
    位 = engine.預估河流位置(h, 150.0, {"2026": 10.0, "2027": -1})
    if len(位) != 1:
        錯誤.append("虧損的預估不該算河流位置")
    else:
        檢查("預估本益比", 位[0]["預估本益比"], 15.0)
        檢查("歷史百分位", 位[0]["歷史百分位"], 50, 1)
        檢查("中位價", 位[0]["中位價"], 150.0)

    # AI 目標價對照共識
    提醒 = engine.檢查AI目標價({"今年EPS": 15.0, "明年EPS": 10.0, "目標價合理": 120.0}, 100.0,
                             共識={"預估EPS今年": 10.0, "預估EPS明年": 10.0, "預估年度": 2026})
    if not any("2026 年 EPS 15.00" in x and "高 50%" in x for x in 提醒):
        錯誤.append(f"AI EPS 高於共識沒有提醒：{提醒}")
    if any("2027 年" in x for x in 提醒):
        錯誤.append("明年 EPS 跟共識一樣，不該提醒")

    # 族群預估本益比：合計市值 ÷ 合計預估獲利
    族 = pd.DataFrame({"代號": ["1", "2", "3"], "名稱": list("甲乙丙"), "收盤": [100.0, 50.0, 10.0], "發行股數": [1e6, 2e6, 1e6],
                      "成交值億": 1.0, "產業": "測試", "漲跌幅": 1.0, "預估EPS今年": [10.0, 2.5, -1.0], "預估EPS明年": np.nan})
    群, _ = engine.族群資料(族)
    檢查("族群預估本益比", 群.loc["測試", "預估本益比"], 200e6 / 15e6, 0.05)

    今 = pd.DataFrame({"代號": ["9991", "9992", "9993"], "收盤": [110.0, 30.0, 50.0]}).join(t, on="代號")
    今 = engine.加預估本益比(今)
    檢查("預估本益比", 今.loc[0, "預估本益比"], 10.0)
    檢查("本業預估本益比", 今.loc[0, "本業預估本益比"], 22.0)
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
