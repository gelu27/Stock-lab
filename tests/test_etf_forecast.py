# 自動檢查：主動式 ETF 明日續買預測（etf_analysis.個股買賣面板／續買預測／續買回測）
#   本機執行：python tests/test_etf_forecast.py
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import etf_analysis  # noqa: E402


def main():
    錯誤 = []
    日 = pd.bdate_range("2026-11-02", periods=4)
    列 = []
    for i, d in enumerate(日):
        for e in ["00001A", "00002A", "00003A"]:
            # 1111 每天被三檔加碼；2222 只有第 2 天被一檔加碼；3333 每天被減碼
            列.append(dict(etf=e, date=d, code="1111", shares=1e6 + i, type="加碼", adj_amount=1e8, amount=1e8))
            列.append(dict(etf=e, date=d, code="2222", shares=1e6, type="加碼" if (i == 1 and e == "00001A") else "持平",
                           adj_amount=0.0, amount=0.0))
            列.append(dict(etf=e, date=d, code="3333", shares=1e6, type="減碼", adj_amount=-1e8, amount=-1e8))
    面板 = etf_analysis.個股買賣面板(pd.DataFrame(列))
    最後 = 面板[面板["date"] == 日[-1]].set_index("code")
    if 最後.at["1111", "連買天數"] != 4 or 最後.at["1111", "前日買檔"] != 3:
        錯誤.append(f"連買天數／前日買檔算錯：{最後.loc['1111'].to_dict()}")
    if 最後.at["2222", "前前日買檔"] != 1 or 最後.at["2222", "連買天數"] != 0:
        錯誤.append(f"2222 前前日買檔應為 1、連買 0：{最後.loc['2222'].to_dict()}")
    預, 預日 = etf_analysis.續買預測(面板)
    if 預日 != 日[-1] or 預["code"].iloc[0] != "1111" or "3333" in set(預["code"]):
        錯誤.append(f"預測排序錯：{預[['code', '續買分數']].to_dict('records')}")
    行情 = pd.DataFrame([dict(code=c, date=d, high=110.0 if c == "1111" else 101.0, 收盤=100.0, 日報酬=0.0)
                       for d in 日 for c in ["1111", "2222", "3333"]])
    彙, 每天, _ = etf_analysis.續買回測(面板, 行情, 前幾名=1)
    if not 彙 or 彙["名單"]["續買1"] != 100 or 彙["天數"] != 3:
        錯誤.append(f"回測命中率應 100%、3 天：{彙}")
    if 彙 and 彙["名單"]["碰漲停%"] != 100:
        錯誤.append(f"1111 每天碰漲停（最高 110＝前收 100 的漲停價）：{彙['名單']}")
    if 錯誤:
        print("\n".join("❌ " + e for e in 錯誤))
        sys.exit(1)
    print("✅ 明日續買預測檢查通過")


if __name__ == "__main__":
    main()
