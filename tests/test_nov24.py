"""2026-11-24：連板 × 翻綠（今日名單、5 年回測）、前瞻本益比 vs 歷史區間。"""
import numpy as np
import pandas as pd

import engine


def _指標():
    日 = pd.bdate_range("2026-10-01", periods=30)
    列 = []
    for c, 收們, 高們 in [
        ("1111", [10.0] * 29 + [9.0], [10.0] * 29 + [11.0]),     # 天地板：碰漲停 11、收跌停 9
        ("2222", [10.0] * 29 + [9.8], [10.0] * 29 + [10.5]),     # 開高走低翻綠
        ("3333", [10.0] * 29 + [10.3], [10.0] * 29 + [10.5]),    # 收漲，不算
    ]:
        for i, d in enumerate(日):
            前 = 收們[i - 1] if i else 收們[0]
            列.append({"date": d, "代號": c, "名稱": f"股{c}", "open": 前, "high": 高們[i], "收盤": 收們[i],
                       "日報酬": 收們[i] / 前 - 1, "value": 1e9})
    return pd.DataFrame(列)


def test_今日翻綠分類():
    t = engine.今日翻綠(_指標())
    assert list(t["代號"]) == ["1111", "2222"]
    assert list(t["翻綠類型"]) == ["天地板", "開高走低翻綠"]
    assert t.loc[0, "盤中最高%"] == 10.0


def test_今日翻綠空資料():
    assert engine.今日翻綠(None).empty


def test_回測檔格式():
    結 = engine.讀取強弱轉折回測()
    assert 結 is not None
    assert {r["條件"] for r in 結["翻綠"]} >= {"天地板（碰漲停收跌停）"}
    assert any(r["條件"] == "連板＋大盤大漲日" for r in 結["連板"])
    for r in 結["連板"] + 結["翻綠"]:
        assert "隔天開盤買20日超額%" in r
