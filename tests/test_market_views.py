# 市場評論查核（2026-11-09）功能的小測試：python tests/test_market_views.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def K線(c, 起="2021-01-04"):
    日 = pd.bdate_range(起, periods=len(c))
    c = np.asarray(c, float)
    return pd.DataFrame({"date": 日, "open": c, "high": c * 1.005, "low": c * 0.995, "close": c})


def main():
    # 大盤預估本益比：200 檔各市值 100、明年獲利 10（PE 10）；龍頭市值 100、獲利 5（PE 20）
    n = 200
    今日 = pd.DataFrame({"代號": [f"{1000 + i}" for i in range(n)] + ["2330", "0050"], "名稱": ["x"] * n + ["台積電", "ETF"],
                       "市場": "上市", "收盤": 100.0, "發行股數": 1.0,
                       "預估EPS今年": [8.0] * n + [4.0, 1.0], "預估EPS明年": [10.0] * n + [5.0, 1.0]})
    估 = engine.大盤預估本益比(今日)
    總市 = 100 * (n + 1)
    assert abs(估["明年"]["本益比"] - 總市 / (10 * n + 5)) < 1e-9, 估
    assert abs(估["明年"]["不含龍頭"] - 10) < 1e-9 and abs(估["明年"]["龍頭本益比"] - 20) < 1e-9
    assert abs(估["明年"]["情境"][-1]["大盤預估本益比"] - round(估["明年"]["本益比"] / 0.8, 2)) < 1e-9
    assert abs(engine.點位本益比換算(40000, 13, 目標點位=80000) - 26) < 1e-9
    assert abs(engine.點位本益比換算(40000, 13, 目標本益比=12) - 40000 * 12 / 13) < 1e-9
    print("✅ 大盤預估本益比正常")

    # 季節統計：每天漲 0.1%，區間一定上漲
    K = K線(100 * 1.001 ** np.arange(1300))
    表, 基, 今 = engine.季節統計(K)
    assert len(表) >= 4 and (表.loc[表["完整"], "區間%"] > 0).all() and 基["區間上漲次數"] == 基["區間次數"], 表
    print("✅ 季節統計正常")

    # 年線：漲 400 天 → 跌到年線附近
    c = np.r_[np.linspace(100, 200, 400), np.linspace(200, 160, 40), np.linspace(160, 175, 30)]
    目, 事 = engine.年線事件(K線(c))
    assert len(事) >= 1 and 目["年線"] > 0, 事
    print("✅ 年線事件正常")

    # 反彈尺：120 → 100（跌 17%）→ 反彈到 108
    c = np.r_[np.linspace(80, 120, 150), np.linspace(120, 110, 10), np.linspace(110, 114, 5), np.linspace(114, 100, 10), np.linspace(100, 108, 5)]
    尺 = engine.反彈尺(K線(c))
    assert 尺 and abs(尺["大段"]["高"] - 120 * 1.005) < 1e-6 and abs(尺["低"] - 100 * 0.995) < 1e-6, 尺
    assert 尺["大段"]["價位"]["0.5"] == (尺["大段"]["高"] + 尺["低"]) / 2
    print("✅ 反彈尺正常")

    # 資本支出警示：兩家季減 → 🔴
    t = pd.DataFrame({"symbol": ["A", "A", "B", "B", "C", "C"], "name": ["A", "A", "B", "B", "C", "C"],
                      "quarter": ["2026Q2", "2026Q3"] * 3, "capex": [100, 80, 100, 85, 100, 110], "ocf": 1})
    燈, 話, 明 = engine.資本支出警示(t)
    assert 燈 == "🔴" and len(明) == 3, (燈, 話)
    print("✅ 資本支出警示正常")

    # 關注清單、領頭連動：檔案格式正確
    清 = engine.讀取關注清單()
    assert {"清單", "代號", "加入日"} <= set(清.columns) and len(清) > 0
    組 = engine.讀取領頭連動()
    assert len(組) and all(len(x.split()) >= 1 for x in 組["跟隨"])
    日 = pd.bdate_range("2026-01-01", periods=80)
    頭 = np.r_[np.linspace(100, 80, 40), np.linspace(80, 95, 10), np.full(30, 95.0)]
    指 = pd.concat([pd.DataFrame({"代號": 組["領頭"].iloc[0], "date": 日, "收盤": 頭}),
                   *[pd.DataFrame({"代號": c, "date": 日, "收盤": np.linspace(50, 60, 80)}) for c in 組["跟隨"].iloc[0].split()]])
    狀, 測 = engine.領頭連動(組.head(1), 指)
    assert len(狀) == 1 and 測["站回次數"].iloc[0] >= 1, (狀, 測)
    for 欄 in ("角色",):
        assert 欄 in 清.columns
    assert not 清["清單"].str.contains("廖|杜").any()
    查 = engine.讀取說法查核()
    assert not 查["來源"].str.contains("廖|杜").any()
    print("✅ 關注清單、領頭連動正常")


if __name__ == "__main__":
    main()
