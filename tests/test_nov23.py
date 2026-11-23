# 2026-11-23 盤勢圖文查核：修復檢核表、等幅測量、向下缺口、前波低點：python tests/test_nov23.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def main():
    日 = pd.bdate_range("2026-09-01", periods=40)
    # 高點 100 → 第一段跌到 80 → 反彈 92 → 第二段跌到 75
    收 = list(np.linspace(95, 100, 5)) + list(np.linspace(98, 80, 10)) + list(np.linspace(82, 92, 8)) + list(np.linspace(90, 75, 17))
    K = pd.DataFrame({"date": 日, "close": 收})
    K["high"], K["low"] = K["close"] + 0.5, K["close"] - 0.5
    等 = engine.等幅測量(K)
    assert 等 and abs(等["H"] - 100.5) < 1e-9 and abs(等["L1"] - 79.5) < 1e-9 and abs(等["B"] - 92.5) < 1e-9, 等
    一倍 = [t for t in 等["目標"] if t["比例"] == 1.0][0]
    assert 一倍["點位"] == round(92.5 - 21) and 一倍["已到"] is False, 等
    # 向下缺口：第 3 天最高低於第 2 天最低，之後沒回補
    K2 = pd.DataFrame({"date": pd.bdate_range("2026-11-02", periods=5), "high": [110, 108, 100, 99, 98],
                       "low": [105, 104, 97, 96, 95], "close": [106, 105, 98, 97, 96]})
    缺 = engine.向下缺口(K2)
    assert len(缺) == 1 and 缺[0]["缺口上緣"] == 104 and 缺[0]["缺口下緣"] == 100, 缺
    # 回補後不列
    K3 = K2.copy(); K3.loc[4, "high"] = 105
    assert engine.向下缺口(K3) == []
    # 前波低點
    低們 = engine.前波低點(K, 窗=3, 天數=40)
    assert 低們 and abs(低們[0][1] - 79.5) < 1e-9, 低們
    # 修復檢核表：全部改善 → 7 綠；全部惡化 → 0 綠
    n = 12
    好 = pd.DataFrame({"融資變化%": [-1.0] * n, "外資": [-50] * 6 + [30] * 6, "外資期貨": np.linspace(-100000, -80000, n),
                       "匯率": np.linspace(33.0, 32.5, n), "上漲": [1200] * n, "下跌": [600] * n},
                      index=pd.bdate_range("2026-11-02", periods=n))
    低 = [100] * 6 + [105] * 6
    KK = pd.DataFrame({"date": 好.index, "low": 低, "close": [x + 1 for x in 低]})
    台 = pd.Series([x * 20 for x in 低], index=好.index)
    列, 總 = engine.修復檢核表(好, KK, KK, 台)
    assert len(列) == 7 and all(r["燈"] == "🟢" for r in 列), 列
    壞 = 好.assign(外資=[-30] * 6 + [-60] * 6, 外資期貨=np.linspace(-80000, -100000, n), 匯率=np.linspace(32.5, 33.0, n), 上漲=600, 下跌=1200)
    KB = KK.assign(low=[105] * 6 + [100] * 6)
    列, 總 = engine.修復檢核表(壞, KB, KB, pd.Series([x * 20 for x in KB["low"]], index=好.index))
    assert all(r["燈"] == "🔴" for r in 列), 列
    assert "去槓桿" in 總
    # 資料不足 → ⚪
    列, 總 = engine.修復檢核表(pd.DataFrame())
    assert all(r["燈"] == "⚪" for r in 列) and 總 == "資料不足"
    print("ok")


if __name__ == "__main__":
    main()
