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
    assert list(表["代號"]) == ["1111"]   # 乙 60 分雖然大增 +11，但總分不到 70 不提醒
    分.loc["2222", "總分"] = 72
    表 = engine.烏賊多方高分重疊(今, 分)
    assert list(表["代號"]) == ["1111", "2222"]
    assert "高分" in 表.iloc[0]["原因"] and "大增" in 表.iloc[1]["原因"]
    分.loc["2222", "總分"] = 60
    累 = pd.DataFrame({"較3日": [0, 0, 16], "較5日": [0, 0, 0]}, index=["1111", "2222", "3333"])
    表 = engine.烏賊多方高分重疊(今, 分, 累)
    assert set(表["代號"]) == {"1111", "3333"}   # 丙 70 分、3 日 +16 達標；乙 60 分不到 70
    assert "3 日" in 表[表["代號"] == "3333"].iloc[0]["原因"]


def test_彙總():
    事 = pd.DataFrame({"5日報酬%": [2.0, -1.0], "5日超額%": [1.0, -2.0]})
    _, 彙 = engine.彙總訊號績效(事)
    assert 彙.iloc[0]["次數"] == 2 and 彙.iloc[0]["勝率%"] == 50 and 彙.iloc[0]["贏大盤%"] == 50


def test_黃金實際追蹤():
    日們 = pd.to_datetime(["2026-11-02", "2026-11-03", "2026-11-04"])
    指標 = pd.DataFrame({"date": 日們.tolist() * 1, "代號": ["1111"] * 3, "還原價": [10.0, 12.0, 9.0]})
    記錄 = {"2026-11-02": {"1111": ["甲", 10.0, 82.0, "強勢股"]}, "2026-11-03": {"1111": ["甲", 12.0, 83.0, "強勢股"]}}
    明, 摘 = engine.黃金實際追蹤(記錄, 指標)
    assert len(明) == 1 and 摘["檔數"] == 1        # 同一檔只算第一次
    r = 明.iloc[0]
    assert round(r["最高漲幅%"]) == 20 and round(r["最大回檔%"]) == -10 and round(r["目前報酬%"]) == -10


def test_黃金組合(monkeypatch):
    今 = pd.DataFrame({"代號": ["1111", "2222"], "名稱": ["甲", "乙"], "收盤": [100.0, 50.0], "漲跌幅": [1, 2]})
    monkeypatch.setattr(engine, "選股", lambda d, c: d)
    monkeypatch.setattr(engine, "每日功課", lambda d: {"強勢股": d, "三&五日強勢股": d.iloc[0:0], "量大股": d.iloc[0:0]})
    分 = pd.DataFrame({"總分": [85, 70], "較昨日": [1, 1]}, index=["1111", "2222"])
    表 = engine.黃金組合(今, 分)
    assert list(表["代號"]) == ["1111"] and 表.iloc[0]["停損價"] == 92.0 and 表.iloc[0]["停利價1"] == 115.0
