# 烏賊多方 × 高分／分數大增 提醒：門檻與欄位
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
import engine


def test_重疊(monkeypatch):
    今 = pd.DataFrame({"代號": ["1111", "2222", "3333"], "名稱": ["甲", "乙", "丙"], "收盤": [10, 20, 30], "漲跌幅": [1, 2, 3]})
    monkeypatch.setattr(engine, "選股", lambda d, c: d)
    monkeypatch.setattr(engine, "烏賊條件", {"烏賊多": {"方向": "多", "條件": {}}, "烏賊空": {"方向": "空", "條件": {}}})
    分 = pd.DataFrame({"總分": [85, 60, 70], "較昨日": [0, 11, 5], "名稱": ["甲", "乙", "丙"]}, index=["1111", "2222", "3333"])
    表 = engine.烏賊多方高分重疊(今, 分)
    assert list(表["代號"]) == ["1111", "2222"]
    assert "高分" in 表.iloc[0]["原因"] and "大增" in 表.iloc[1]["原因"]
