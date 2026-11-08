# 正2 融資追蹤、維持率估算、期貨多空對手、背離回測的小測試：python tests/test_lev_margin.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def main():
    日 = pd.bdate_range("2026-01-01", periods=8)
    # 00685L：每天融資增加、第 5 天一拆 25（收盤 /25、張數 ×25），之後再跌
    價 = [20, 20, 20, 20, 0.8, 0.8, 0.72, 0.64]
    張 = [100, 110, 120, 130, 3300, 3400, 3500, 3600]
    表 = pd.DataFrame({"code": "00685L", "date": 日, "close": 價, "margin": 張})
    天, 檔 = engine.正2融資明細(表)
    x = 檔[0]
    assert x["代號"] == "00685L" and x["連增天數"] == 6, x       # 分割那天不算增減，也不打斷連增
    assert abs(x["估成本"] - 0.8) < 0.05, x                       # 成本跟著分割換算
    assert 120 < x["估維持率"] < 135, x                           # 0.64 ÷ (≈0.79 × 60%)
    assert pd.isna(天["單日增減億"].iloc[4]) or 天["單日增減億"].iloc[4] == 0
    # 期貨多空對手：外資空單 ≈ 投信多單 × 1.1
    期 = pd.DataFrame({"foreign_oi": -np.linspace(20000, 99000, 60) * 1.1, "trust_oi": np.linspace(20000, 99000, 60)},
                      index=pd.bdate_range("2025-09-01", periods=60))
    對 = engine.期貨多空對手(期)
    assert 對["燈"] == "⚪" and abs(對["最新"] - 1.1) < 0.01, 對
    期.iloc[-1, 0] = -99000 * 1.6
    assert engine.期貨多空對手(期)["燈"] == "🟡"
    # 背離回測：第 3 天大盤融資 −2%、正2 +10%
    K = pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=80), "close": np.linspace(100, 180, 80)})
    變 = pd.Series(0.0, index=K["date"]); 變.iloc[2] = -2.0
    正 = pd.DataFrame({"融資市值億": 100.0, "單日增減億": 0.0}, index=K["date"]); 正.iloc[2, 1] = 10.0
    回 = engine.正2背離統計(變, 正, K)
    assert 回["次數"] == 1 and 回["事件"][0]["date"] == f"{K['date'][2]:%Y-%m-%d}", 回
    是, 大, 正2 = engine.今日正2背離(變.iloc[:3], 正.iloc[:3])
    assert 是 and 大 == -2.0 and 正2 == 10.0
    print("ok")


if __name__ == "__main__":
    main()
