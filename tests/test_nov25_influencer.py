"""2026-11-25 網紅摘要建議：追繳線 120%、法人拆 ETF、大盤判斷卡、目標價異常旗、暴漲後破前低。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402


def test_追繳線改120():
    assert engine.融資追繳線 == 120 and engine.融資舊追繳線 == 130
    assert engine.融資訊號({"融資維持率": 125, "融資餘額": 500}) != "🚨 低於追繳線"
    assert engine.融資訊號({"融資維持率": 118, "融資餘額": 500}) == "🚨 低於追繳線"
    線們 = [x[0] for x in engine.維持率警戒點位(170, 40000)]
    assert 120 in 線們 and 130 not in 線們


def test_法人拆ETF():
    表 = pd.DataFrame({"代號": ["2330", "00981A", "2330", "00981A"], "date": pd.to_datetime(["2026-11-24"] * 2 + ["2026-11-25"] * 2),
                     "收盤": [100.0, 20.0, 100.0, 20.0], "外資買超": [-1000, 0, 0, 0], "投信買超": [0, 0, 0, 0],
                     "自營買超": [0, -5000, 0, 0], "法人買超": [-1000, -5000, 0, 0]})
    r = engine.法人拆ETF(表)
    d = pd.Timestamp("2026-11-24")
    assert r.loc[d, "法人個股"] == -1.0 and r.loc[d, "法人ETF"] == -1.0
    assert r.loc[d, "ETF最大自營賣超"] == "00981A"


def _K(收, 高=None, 低=None):
    n = len(收)
    return pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=n), "close": 收,
                         "high": 高 if 高 is not None else 收, "low": 低 if 低 is not None else 收})


def test_大盤判斷卡_島狀反轉失敗():
    收 = [100.0] * 25
    高, 低 = list(收), list(收)
    # 向下缺口（第 25 天高 < 前日低），島 2 天，再向上缺口，之後回補
    收 += [90, 89, 105, 99]
    高 += [91, 90, 106, 100]
    低 += [88, 88, 104, 85]
    卡 = engine.大盤判斷卡(_K(收, 高, 低))
    assert 卡["島狀"] and 卡["島狀"]["成立"] and 卡["島狀"]["失敗"]
    assert 卡["上缺口"]["狀態"] == "已完全回補"


def test_目標價異常():
    共 = {"目標價數": 2, "最高": 1050, "最低": 318, "最樂觀": "A"}
    assert len(engine.目標價異常(共, 309)) == 2
    assert engine.目標價異常({"目標價數": 2, "最高": 350, "最低": 300, "最樂觀": "A"}, 309) == []


def test_暴漲後破前低():
    收 = [100.0] * 15 + [106.0] + [101.0] * 3 + [90.0] + [100.0] * 60
    r = engine.暴漲後破前低(_K(收), 5.0)
    assert len(r) == 1 and bool(r.loc[0, "再破前低"]) and r.loc[0, "幾天後"] == 4


def test_記憶體時鐘檔():
    t = engine.讀取記憶體時鐘()
    assert len(t) >= 3 and "預估轉折" in t.columns
