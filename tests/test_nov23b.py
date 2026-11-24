# 2026-11-23 利多圖卡查核：V 轉反彈統計、停損雜訊檢查：python tests/test_nov23b.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def main():
    日 = pd.bdate_range("2020-01-01", periods=200)
    收 = np.full(200, 100.0)
    收[100:105] = [98, 95, 92, 90, 88]   # 前 5 日累計跌
    收[105] = 92                           # 單日 +4.5%
    收[106:] = 92 + np.arange(94) * 0.1
    K = pd.DataFrame({"date": 日, "close": 收})
    表, 摘 = engine.V轉反彈統計(K)
    assert 摘 and 摘["次數"] >= 1 and 表.iloc[0]["當日%"] > 4, 表
    t0, s0 = engine.V轉反彈統計(K.head(30))
    assert t0.empty and s0 == {}
    # 停損雜訊：日振幅 6%，停損距離 3% → 0.5 倍、太緊
    z = pd.DataFrame({"high": [103] * 25, "low": [97] * 25, "close": [100.0] * 25})
    r = engine.停損雜訊檢查(z, 100, 97)
    assert r and r["倍數"] == 0.5 and "太緊" in r["判讀"], r
    r2 = engine.停損雜訊檢查(z, 100, 88)
    assert "有緩衝" == r2["判讀"], r2
    assert engine.停損雜訊檢查(z, 100, 105) is None
    print("ok")


if __name__ == "__main__":
    main()
