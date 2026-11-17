"""2026-11-17 長中短分倉：加碼階梯、波段新倉燈、分倉配置、分倉紀律。直接執行：python tests/test_buckets.py"""
import sys, pathlib
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import engine, portfolio


def main():
    日 = pd.bdate_range("2020-01-01", periods=600)
    價 = np.r_[np.linspace(100, 200, 400), np.linspace(200, 150, 200)]   # 最後離高點 −25%
    K = pd.DataFrame({"date": 日, "close": 價})
    階 = engine.分倉加碼階梯(K)
    assert 階["距高%"] == -25.0 and 階["階"] == 2 and 階["下一階"] == -30 and 階["下一階點位"] == 140, 階
    assert engine.分倉加碼階梯(K.head(100)) is None
    燈 = engine.波段新倉燈(K)
    assert 燈["燈"] == "🔴" and not 燈["季線上彎"], 燈
    assert engine.波段新倉燈(K.head(400))["燈"] == "🟢"

    持股 = pd.DataFrame({"代號": ["0050", "2330", "3105", "6182"], "股數": [1000, 100, 1000, 2000], "總成本": [50000, 100000, 40000, 30000]})
    現價 = {"0050": 60.0, "2330": 1000.0, "3105": 30.0, "6182": 20.0}
    明, 倉, 總 = portfolio.分倉配置(持股, 現價, {"6182": "短線"}, 現金=40000, 已實現獲利=10000, 大型股=["2330"])
    assert dict(zip(明["代號"], 明["分倉"])) == {"0050": "長線", "2330": "長線", "3105": "波段", "6182": "短線"}
    assert 總["總資產"] == 60000 + 100000 + 30000 + 40000 + 40000 and 總["短線超出"] == 30000, 總
    assert abs(倉.set_index("分倉").loc["長線", "目前%"] - 160000 / 270000 * 100) < 1e-9

    線們 = {"0050": pd.Series(np.r_[np.full(100, 80.0), np.full(20, 60.0)]),   # −25% → 🟢
            "3105": pd.Series(np.full(30, 30.0)), "6182": pd.Series(np.r_[np.full(25, 22.0), [20.0]])}
    紀 = dict(zip(*portfolio.分倉紀律(明, 線們, {"燈": "🟢"}).T.values))
    assert 紀["0050"].startswith("🟢") and 紀["6182"].startswith("🔴") and 紀["3105"].startswith("🔴"), 紀  # 3105 虧 25%
    assert 紀["2330"].startswith("⚪")
    print("ok")


if __name__ == "__main__":
    main()
