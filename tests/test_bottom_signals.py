# 止跌訊號（指數 vs 融資、全市場借券、賣壓消散三燈號、破低不破榜）的小測試：python tests/test_bottom_signals.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def main():
    日 = pd.bdate_range("2026-01-01", periods=30)
    # 指數 100 → 80（−20%），融資 1,000 → 900（−10%）
    c = np.r_[np.linspace(90, 100, 10), np.linspace(99, 80, 20)]
    K = pd.DataFrame({"date": 日, "open": c, "high": c + 1, "low": c - 1, "close": c})
    融 = pd.Series(np.r_[np.full(10, 1e6), np.linspace(1e6, 9e5, 20)], index=日)
    r = engine.指數融資對照(K, 融)
    assert r["起日"] == 日[9] and abs(r["指數跌幅%"] + 20) < 0.01 and abs(r["融資減幅%"] + 10) < 0.01, r
    assert r["同步還要減億"] == 1, r          # 起點 1,000 億（千元單位 1e6 = 10 億）× 0.8 = 8 億，現在 9 億 → 還要 1 億
    print("✅ 指數 vs 融資正常")

    # 借券：一檔股票餘額 100 → 110 → 105 張，股價變動不影響變化%
    借 = pd.DataFrame({"date": 日[:3], "code": "1234", "sbl_sell": [0, 10, 0], "sbl_return": [0, 0, 5],
                      "sbl_balance": [100.0, 110.0, 105.0]})
    價 = pd.DataFrame({"date": 日[:3], "code": "1234", "close": [10.0, 20.0, 30.0]})
    t = engine.大盤借券趨勢(借, 價)
    assert abs(t["變化%"].iloc[0] - 10) < 0.01 and abs(t["變化%"].iloc[1] + 100 * 5 / 110) < 0.01, t
    長 = pd.DataFrame({"指數": np.r_[np.linspace(100, 110, 12), [109, 108, 107]]})
    assert engine.借券轉向燈(長)[0] == "🟢"
    assert engine.借券轉向燈(pd.DataFrame({"指數": np.linspace(100, 120, 15)}))[0] == "🔴"
    print("✅ 全市場借券正常")

    匯 = pd.DataFrame({"date": 日[:4], "usdtwd": [32.9, 33.0, 32.9, 32.8]})
    期 = pd.DataFrame({"foreign_oi": [-100, -110, -100, -90]}, index=日[:4])
    k = pd.DataFrame({"date": 日[:4], "open": [100, 100, 100, 100], "low": [98, 98, 97, 97],
                      "close": [99, 99, 99.5, 99.5], "high": 101})
    燈 = engine.賣壓消散燈號(匯, 期, k)
    assert 燈["亮幾個"] == 3, 燈
    燈 = engine.賣壓消散燈號(匯.assign(usdtwd=[32.9, 33.0, 33.1, 32.8]), 期, k)
    assert 燈["亮幾個"] == 2, 燈
    print("✅ 賣壓消散三燈號正常")

    # 大盤：先跌到 50（前波低）、漲到 120（高點）、再跌到 40（破前低）；甲股前波低 10、近期低 12（不破），乙股近期低 8（破）
    n = 150
    指 = np.r_[np.linspace(100, 50, 40), np.linspace(51, 120, 70), np.linspace(119, 40, 40)]
    日 = pd.bdate_range("2026-01-01", periods=n)
    K = pd.DataFrame({"date": 日, "open": 指, "high": 指, "low": 指, "close": 指})
    前 = 日[39]
    列們 = []
    for code, 前低, 近低 in (("1111", 10.0, 12.0), ("2222", 10.0, 8.0)):
        for i, d in enumerate(日):
            低 = 前低 if d == 前 else (近低 if i == n - 1 else 20.0)
            列們.append({"代號": code, "名稱": code, "date": d, "low": 低, "收盤": 低 + 1, "成交值億": 5.0})
    表, 資 = engine.破低不破榜(pd.DataFrame(列們), K, 前波窗=80)
    assert 資["大盤破了"] and 資["前波日"] == 前, 資
    assert 表["代號"].tolist() == ["1111"] and abs(表.loc[0, "高於前低%"] - 20) < 0.01, 表
    print("✅ 破低不破榜正常")


if __name__ == "__main__":
    main()
