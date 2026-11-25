# 2026-11-22 盤勢文查核：斷頭處分日曆、處分日回測、跌破年線統計、融資金額減幅、歷史底部維持率：python tests/test_nov22.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def main():
    # 加交易日：週五 +1 → 週一；遇假日再往後
    assert engine.加交易日("2026-11-20", 1) == pd.Timestamp("2026-11-23")
    assert engine.加交易日("2026-11-25", 1, 休市=["2026-11-26"]) == pd.Timestamp("2026-11-27")
    # 斷頭處分日曆：週一大跌 → 週四處分；最後一天（週五）大跌 → 下週三
    日 = pd.bdate_range("2026-11-09", "2026-11-20")
    收 = [100, 101, 102, 103, 104, 97, 97.5, 98, 94, 88]
    K = pd.DataFrame({"date": 日, "close": 收})
    曆 = engine.斷頭處分日曆(K)
    assert list(曆["大跌日"]) == [pd.Timestamp("2026-11-16"), pd.Timestamp("2026-11-19"), pd.Timestamp("2026-11-20")], 曆
    assert 曆["最快處分日"].iloc[0] == pd.Timestamp("2026-11-19") and 曆["狀態"].iloc[0] == "已過"
    assert 曆["最快處分日"].iloc[1] == pd.Timestamp("2026-11-24") and 曆["最快處分日"].iloc[2] == pd.Timestamp("2026-11-25")
    assert 曆["追繳通知"].iloc[2] == pd.Timestamp("2026-11-23")
    # 處分日回測：T+3 標成處分日
    rng = np.random.default_rng(1)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.02, 600))
    K2 = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=600), "close": c})
    回, 次, 均, 漲 = engine.處分日回測(K2, 跌幅門檻=-3)
    assert 次 > 0 and "T+3（處分日）" in list(回["第幾天"]), 回
    # 跌破年線統計：一路漲 300 天 → 跌到年線下 30 天 → 再漲回
    上 = list(np.linspace(100, 200, 300))
    下 = list(np.linspace(150, 140, 30))
    回升 = list(np.linspace(150, 230, 60))
    K3 = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=390), "close": 上 + 下 + 回升})
    事, 今 = engine.跌破年線統計(K3, 最少站回天數=0)
    assert len(事) == 1 and 事["站回日"].notna().iloc[0] and 事["站回前最多再跌%"].iloc[0] < 0, 事
    assert 今["距年線%"] > 0 and "回檔級別" in 事.columns and 事["自年線最多再跌%"].iloc[0] < 0
    點 = engine.年線回檔滿足點(39368.24)
    assert 點[0][3] == 35577 and 點[2][0] == "大回檔", 點
    # 只留真跌破：站回少於 100 天的不列
    事2, _ = engine.跌破年線統計(K3, 最少站回天數=100)
    assert len(事2) == 0
    # 融資金額減幅：金額 100 → 60（−40%），指數高 1000 → 收 800（−20%）
    金 = pd.Series([90, 100, 80, 70, 60, 60], index=pd.bdate_range("2026-01-05", periods=6), dtype=float) * 1e5
    K4 = pd.DataFrame({"date": 金.index, "high": [950, 1000, 900, 850, 820, 810], "close": [940, 990, 880, 840, 810, 800]})
    減 = engine.融資金額減幅(金, K4)
    assert 減["融資減幅%"] == -40.0 and 減["指數跌幅%"] == -20.0 and 減["比例"] == 2.0, 減
    # 維持率警戒點位加了 135%
    assert [x[0] for x in engine.維持率警戒點位(140, 10000)] == [135, engine.融資追繳線]
    底 = engine.讀取歷史底部維持率()
    assert len(底) == 3 and 底["維持率%"].between(129, 136).all()
    # 槓桿追繳機率：一路跌 30% 的資料 → 融資一定碰到追繳線、現股沒有追繳欄
    K5 = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=600), "close": np.linspace(100, 60, 600)})
    槓 = engine.槓桿追繳機率(K5, 窗=250)
    assert pd.isna(槓["一年內碰到追繳線%"].iloc[0]) and 槓["一年內碰到追繳線%"].iloc[2] > 槓["一年內碰到追繳線%"].iloc[1], 槓
    回本 = engine.高點回本時間(K3, 高點們=[("2021-01", "2021-03")])
    assert len(回本) == 1 and 回本["期間最大跌%"].iloc[0] < 0
    # 補上市法人：上市法人欄大多是空的 → 重抓補回，上櫃不動
    import tempfile
    import update_data
    with tempfile.TemporaryDirectory() as 暫:
        根 = Path(暫)
        (根 / "chips" / "2026-11").mkdir(parents=True)
        (根 / "prices" / "2026-11").mkdir(parents=True)
        pd.DataFrame({"code": ["1101", "1102", "6488"], "foreign": [np.nan, np.nan, 5.0], "trust": [np.nan, np.nan, 1.0],
                      "dealer": [np.nan] * 3, "total": [np.nan] * 3, "margin": [1.0, 2.0, 3.0]}).to_csv(
            根 / "chips" / "2026-11" / "20261117.csv.gz", index=False)
        pd.DataFrame({"code": ["1101", "1102", "6488"], "market": ["上市", "上市", "上櫃"]}).to_csv(
            根 / "prices" / "2026-11" / "20261117.csv.gz", index=False)
        舊資料夾, 舊法人 = update_data.資料夾, update_data.上市法人
        try:
            update_data.資料夾 = 根
            update_data.上市法人 = lambda d: pd.DataFrame({"code": ["1101", "1102"], "foreign": [100.0, -50.0],
                                                     "trust": [0.0, 1.0], "dealer": [0.0, 0.0], "total": [100.0, -49.0]})
            update_data.補上市法人()
        finally:
            update_data.資料夾, update_data.上市法人 = 舊資料夾, 舊法人
        補 = pd.read_csv(根 / "chips" / "2026-11" / "20261117.csv.gz", dtype={"code": str}).set_index("code")
        assert 補.at["1101", "foreign"] == 100 and 補.at["6488", "foreign"] == 5 and 補.at["1102", "margin"] == 2, 補
    # 斷頭年線摘要：年線下、維持率 140、20 日跌 8% 以上 → 都要有
    c6 = list(np.linspace(100, 200, 300)) + list(np.linspace(190, 150, 25))
    K6 = pd.DataFrame({"date": pd.bdate_range("2025-01-01", periods=len(c6)), "close": c6})
    摘 = engine.斷頭年線摘要(K6, 140)
    assert any("年線下" in x for x in 摘) and any("130～135%" in x for x in 摘) and any("外資連買" in x for x in 摘), 摘
    assert engine.斷頭年線摘要(K6.head(300), 170) == []
    print("test_nov22 OK")

def 測崩跌模式():
    import engine
    d = pd.DataFrame({"外資連買": [5, 5, 1], "崩跌模式": [False, True, True]})
    加 = [0, 0, 0]
    for 面, 點, 條件, 文字 in engine.評分規則:
        try:
            是 = 面 == "籌碼" and "外資連買" in 文字(d.iloc[0])
        except (KeyError, TypeError, ValueError):
            是 = False
        if 是:
            for i, 中 in enumerate(條件(d).fillna(False).astype(bool)):
                加[i] += 點 * 中
    assert 加 == [10, 5, 0], 加
    assert engine.崩跌模式說明({"崩跌模式": False}) == ""
    說 = engine.崩跌模式說明({"崩跌模式": True, "數字": {"漲20日": -12.3}})
    assert "12.3%" in 說 and "+5" in 說
    大 = engine.大盤評分(None, pd.DataFrame({"代號": ["2330"], "收盤": [1.0], "漲跌幅": [1.0]}))
    assert 大["崩跌模式"] is False
    print("崩跌模式 OK")


if __name__ == "__main__":
    main()
    測崩跌模式()
