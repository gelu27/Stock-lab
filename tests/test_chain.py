# 題材產業鏈（人形機器人，2026-11-15）的小測試：python tests/test_chain.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def main():
    鏈 = engine.讀取產業鏈()
    人 = 鏈[鏈["chain"] == "人形機器人"]
    註 = engine.讀取產業鏈註記()
    assert len(人) >= 20 and 人["code"].is_unique, "人形機器人鏈每檔只放一個主要部位"
    assert set(人["code"]) == set(註[註["chain"] == "人形機器人"]["code"]), "產業鏈與受惠等級名單要一致"
    assert set(註["等級"]) <= {"A 已出貨", "B 送樣驗證", "C 間接題材"}, 註["等級"].unique()
    概 = engine.讀取概念()
    assert set(人["code"]) <= set(概[概["concept"] == "人形機器人"]["code"]), "概念股也要有人形機器人"
    文 = engine.產業鏈位置("2049", {"2049": "上銀"})
    assert "人形機器人 供應鏈" in 文 and "受惠等級：A 已出貨" in 文 and "上游環節" not in 文.split("人形機器人")[1], 文
    print("✅ 人形機器人名單、受惠等級、個股產業鏈文字正常")

    衛 = 鏈[鏈["chain"] == "低軌衛星"]
    assert len(衛) >= 20 and 衛["code"].is_unique, "低軌衛星鏈每檔只放一個主要環節"
    assert set(衛["code"]) == set(註[註["chain"] == "低軌衛星"]["code"]), "低軌衛星產業鏈與受惠等級名單要一致"
    assert set(衛["code"]) == set(概[概["concept"] == "低軌衛星"]["code"]), "概念股低軌衛星要跟產業鏈同一份名單"
    assert "2314" not in set(衛["code"]), "台揚 12/21 終止上市，不列入"
    文 = engine.產業鏈位置("3491", {"3491": "昇達科"})
    assert "低軌衛星 產業鏈" in 文 and "受惠等級：A 已出貨" in 文 and "下游環節" not in 文 and "並行" in 文, 文
    文 = engine.產業鏈位置("2412", {"2412": "中華電"})
    assert "受惠等級：C 間接題材" in 文, 文
    print("✅ 低軌衛星名單、受惠等級、個股產業鏈文字正常")

    # 指數：兩檔每天各漲 1%、加權每天漲 0.5% → 全部指數每天 ×1.01
    日 = pd.bdate_range("2024-01-01", periods=300)
    碼們 = 人["code"].tolist()[:2]
    指標 = pd.concat([pd.DataFrame({"date": 日, "代號": c, "還原價": 100 * 1.01 ** np.arange(300)}) for c in 碼們])
    加權 = pd.DataFrame({"date": 日, "close": 1000 * 1.005 ** np.arange(300)})
    指數 = engine.產業鏈指數(指標, 加權, "人形機器人")
    assert abs(指數["全部"].iloc[-1] - 1.01 ** 299) < 1e-6, 指數.tail()
    assert abs(指數["加權指數"].iloc[-1] - 1.005 ** 299) < 1e-6, 指數.tail()
    表, 現 = engine.族群熱度回測(指數)
    assert len(表) == 1 and 表.iloc[0, 0] == "領先 10% 以上" and 現 > 10, (表, 現)
    print("✅ 產業鏈等權指數與熱度回測正常")

    今日 = pd.DataFrame({"代號": ["2049", "1536"], "名稱": ["上銀", "和大"], "收盤": [300.0, 40.0], "本益比": [30.0, -1.0],
                       "漲跌幅": [1.0, -1.0], "20日漲幅": [5.0, -5.0], "距52週高點": [-10.0, -20.0]})
    評分 = pd.DataFrame({"總分": [70.0]}, index=["2049"])
    t = engine.產業鏈族群表(今日, 評分)
    assert list(t["代號"]) == ["2049", "1536"] or set(t["代號"]) == {"2049", "1536"}, t
    r = t.set_index("代號")
    assert r.loc["2049", "總分"] == 70 and pd.isna(r.loc["1536", "本益比"]) and r.loc["1536", "等級"] == "A 已出貨"
    assert "合約負債億" in t.columns and "能見度月" in t.columns, t.columns
    t2 = engine.產業鏈族群表(pd.DataFrame({"代號": ["6285", "3491"], "名稱": ["啟碁", "昇達科"], "收盤": [1.0, 1.0]}), None, "低軌衛星").set_index("代號")
    if len(engine.讀取合約負債()):
        assert pd.notna(t2.loc["6285", "合約負債億"]) and t2.loc["3491", "合約負債季"].endswith("未列報"), t2
    報 = [{"代號": "6285", "名稱": "啟碁", "券商": "甲", "日期": f"{pd.Timestamp.now():%Y-%m-%d}", "看法": "看多", "目標價": 250},
         {"代號": "6285", "名稱": "啟碁", "券商": "乙", "日期": f"{pd.Timestamp.now():%Y-%m-%d}", "看法": "中性", "目標價": 200}]
    t3 = engine.產業鏈族群表(pd.DataFrame({"代號": ["6285"], "名稱": ["啟碁"], "收盤": [200.0]}),
                        pd.DataFrame({"總分": [53.0], "較昨日": [1.5]}, index=["6285"]), "低軌衛星", 報).iloc[0]
    assert t3["券商評等"] == "2 家：多 1／中 1／空 0" and t3["目標價中位數"] == 225 and abs(t3["目標價空間%"] - 12.5) < 0.01, t3
    assert t3["較昨日"] == 1.5 and "庫藏股" in t3.index
    庫 = pd.DataFrame({"code": ["9999"], "start": [pd.Timestamp("2026-11-01")], "end": [pd.Timestamp("2026-12-31")],
                      "done": ["N"], "pct_done": [30.0]})
    assert engine.庫藏股狀態(庫, "9999", "2026-11-16") == "執行中 11/01～12/31，已買 30%"
    assert engine.庫藏股狀態(庫, "9999", "2026-10-16") == "將於 11/01 開始" and engine.庫藏股狀態(庫, "1111") == ""
    print("✅ 產業鏈現況表正常（含合約負債、庫藏股、券商評等、較昨日）")


if __name__ == "__main__":
    main()
