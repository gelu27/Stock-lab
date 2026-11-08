# 自動檢查：順勢做多引擎（均線刻度、VCP 帶量突破、交易計畫的停損與目標、回測統計）
#   本機執行：python tests/test_momentum.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import momentum  # noqa: E402

錯誤 = []


def 檢查(條件, 說明):
    print(("✅ " if 條件 else "❌ ") + 說明)
    if not 條件:
        錯誤.append(說明)


# 造一檔 300 天穩定上漲、最後 15 天窄幅整理、最後一天帶 3 倍量突破的股票；還原價是收盤的一半（模擬配過息）
天 = pd.bdate_range("2025-01-01", periods=300)
價 = np.linspace(50, 100, 300)
價[-16:-1] = 100 + np.sin(np.arange(15)) * 0.3
價[-1] = 104
t = pd.DataFrame({"date": 天, "代號": "9999", "收盤": 價, "還原價": 價 / 2, "open": 價 * 0.995, "high": 價 * 1.01,
                  "low": 價 * 0.99, "volume": 1000.0, "外資連買": 0, "投信連買": 0})
t.loc[t.index[:-16], ["high", "low"]] = np.c_[價[:-16] * 1.03, 價[:-16] * 0.97]  # 前面波動大、最後收斂
t.loc[t.index[-1], "volume"] = 3000.0
x = momentum.加上動能欄位(t)
末 = x.iloc[-1]
檢查(abs(末["MA20"] - 價[-20:].mean()) < 0.5, "均線換回原始股價刻度（不是還原價）")
遮 = momentum.訊號遮罩(x)
檢查(bool(遮["多頭排列"].iloc[-1]), "穩定上漲 → 多頭排列")
檢查(bool(遮["VCP突破"].iloc[-1]), "波動收斂後帶 3 倍量突破 → VCP突破")
檢查(not bool(遮["VCP突破"].iloc[-5]), "整理期間不是突破")

計 = momentum.交易計畫(末, 壓力=130)
檢查(計["已突破"] and 計["買點"] == round(末["收盤"], 2), "已突破時買點＝收盤價")
R = 計["買點"] - 計["停損"]
檢查(R > 0 and abs(計["目標1"] - (計["買點"] + 2 * R)) < 0.02 and abs(計["目標2"] - (計["買點"] + 3 * R)) < 0.02, "目標 1／2＝買點＋2R／3R")
檢查(計["停損"] >= 計["買點"] - 1.5 * 末["ATR14"] - 0.01, "停損不會比 1.5 倍 ATR 更遠")
檢查(計.get("前波壓力") == 130, "列出前波壓力")

遠 = 末.copy()
遠["收盤"], 遠["前高20"] = 80.0, 100.0
檢查(momentum.交易計畫(遠)["買點"] is None, "離前高超過 10% 不給買點")

# 回測統計：之後 5 天都漲 → 勝率 100%
y = momentum.加上未來報酬(x.copy())
統 = momentum.訊號統計(y, {"多頭排列": 遮["多頭排列"] & y["f20"].notna()})[0]
檢查(統["次數"] > 0 and 統["20日勝率%"] is not None, "訊號統計算得出勝率")

if 錯誤:
    print(f"\n共 {len(錯誤)} 項失敗")
    sys.exit(1)
