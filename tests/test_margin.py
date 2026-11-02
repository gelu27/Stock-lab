# 個股融資成本／維持率估算的小測試：python tests/test_margin.py
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def main():
    # 第 1 天 100 張@100；第 2 天加 100 張@110 → 成本 105；第 3 天減少 → 成本不變
    代 = np.array(["A"] * 3 + ["B"] * 2)
    價 = np.array([100.0, 110, 120, 50, 50])
    報 = np.array([0, 0.1, 0.0909, 0, 0])
    融 = np.array([100.0, 200, 150, 10, np.nan])
    c = engine.融資成本估算(代, 價, 報, 融)
    assert abs(c[1] - 105) < 1e-9 and abs(c[2] - 105) < 1e-9, c
    assert c[3] == 50 and c[4] == 50, c          # 換股票重算、融資沒公布沿用
    # 面額分割 1 拆 4：收盤 400 → 100、交易所漲跌 0，成本跟著 ÷4，張數 ×4 不算新買進
    c = engine.融資成本估算(np.array(["C"] * 3), np.array([400.0, 100, 100]), np.array([0, 0, 0.0]),
                         np.array([100.0, 400, 500]))
    assert abs(c[1] - 100) < 1e-9, c
    assert abs(c[2] - 100) < 1e-9, c
    print("✅ 融資成本估算正常")

    # 大盤融資變化：A 100→90 張@10、B 50→50 張@20 → (−10×10) ÷ (100×10 + 50×20) = −5%；分割暴增的 C 不算
    import pandas as pd
    d1, d2 = pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")
    t = pd.DataFrame({"code": ["1111", "1111", "2222", "2222", "3333", "3333"], "date": [d1, d2] * 3,
                      "close": [10.0, 10, 20, 20, 100, 25], "margin": [100.0, 90, 50, 50, 10, 40]})
    v = engine.大盤融資變化(t)
    assert list(v.index) == [d2] and abs(v.iloc[0] + 5) < 1e-9, v
    # 維持率到警戒線：180% → 165% 要跌 8.3%
    點 = engine.維持率警戒點位(180, 10000)
    assert 點[0][0] == 165 and 點[0][1] == 9167 and 點[0][2] == -8.3, 點
    assert engine.維持率警戒點位(160, 10000, 官方=170)[0][1] == 9706
    # 月線連跌：只用收完的月份
    日 = pd.bdate_range("2025-01-01", "2025-06-10")
    值 = [100 + (i % 40) - (20 if 日[i].month in (3, 4) else 0) for i in range(len(日))]
    目, 歷, 彙 = engine.月線連跌統計(pd.DataFrame({"date": 日, "close": 值}))
    assert 目["本月完整"] is False and 目["月份"].month == 6, 目
    print("✅ 大盤融資變化、維持率警戒點位、月線連跌正常")


if __name__ == "__main__":
    main()
