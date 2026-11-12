import sys
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402
import auto_intake  # noqa: E402

整理 = """一、基本資料
頻道：測試頻道
日期：2026-11-07
長度：10 分
二、逐段內容：略
三、提到的股票：
2330 台積電：看多。理由：本益比低
2454 聯電：看空。理由：測試
四、判斷條件：
如果台積電站回 20 週均線就買回
五、資料來源：無
"""


def test_解析與初步查核():
    v = engine.解析影片整理(整理, {"台積電": "2330"})
    assert v and v["頻道"] == "測試頻道"
    旗 = engine.初步查核網紅(v, {"2330": "台積電", "2454": "聯發科"})
    assert any("2454" in x for x in 旗)       # 聯電≠聯發科
    assert not any("2330" in x for x in 旗)


def test_用量計數與小卡(tmp_path, monkeypatch):
    存 = {}
    monkeypatch.setattr(engine, "讀取設定檔", lambda s, f: dict(存.get(f, {})))
    monkeypatch.setattr(engine, "儲存設定檔", lambda s, f, c, m="": 存.__setitem__(f, c))
    engine.Gemini本次呼叫.update({"成功": 3, "失敗": 1})
    engine.AI用量紀錄({}, "測試")
    assert engine.Gemini本次呼叫 == {"成功": 0, "失敗": 0}
    assert engine.AI今日呼叫數({}, "測試") == 4
    assert "測試：3 次（失敗 1）" in engine.AI用量小卡({})


def test_影片收件流程(monkeypatch):
    存 = {"video_sources.json": {"網址": ["https://youtu.be/abcdefghijk"]}}
    monkeypatch.setattr(engine, "讀取設定檔", lambda s, f: dict(存.get(f, {})))
    monkeypatch.setattr(engine, "儲存設定檔", lambda s, f, c, m="": 存.__setitem__(f, c))
    今 = pd.DataFrame({"date": [pd.Timestamp("2026-11-06")] * 2, "code": ["2330", "2454"], "name": ["台積電", "聯發科"]})
    monkeypatch.setattr(engine, "讀取資料庫", lambda **k: 今)
    回 = mock.Mock()
    回.json.return_value = {"candidates": [{"content": {"parts": [{"text": 整理}]}}]}
    monkeypatch.setattr(engine, "Gemini呼叫", lambda *a, **k: (回, "m"))
    monkeypatch.setattr(auto_intake, "_通知", lambda t: None)
    monkeypatch.setattr(auto_intake, "取字幕", lambda v: None)
    monkeypatch.setattr(auto_intake, "_額度夠", lambda s, f: True)
    新, 敗 = auto_intake.收影片({"GEMINI_API_KEY": "k"})
    assert (新, 敗) == (1, 0)
    assert "abcdefghijk" in 存["intake_seen.json"]["影片"]
    assert 存["influencer_notes.json"]["影片"][0]["頻道"] == "測試頻道"
    assert auto_intake.收影片({"GEMINI_API_KEY": "k"}) == (0, 0)   # 第二次不重複處理


def test_新片提醒只提醒一次(monkeypatch):
    import datetime as dt
    import notify
    存 = {"video_sources.json": {"頻道": [{"名稱": "測試台", "channel_id": "UCx"}]}}
    monkeypatch.setattr(engine, "讀取設定檔", lambda s, f: dict(存.get(f, {})))
    monkeypatch.setattr(engine, "儲存設定檔", lambda s, f, c, m="": 存.__setitem__(f, c))
    現在 = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    rss = mock.Mock(text=f"<entry><yt:videoId>abcdefghijk</yt:videoId><title>【直播】測試</title><published>{現在}</published></entry>")
    monkeypatch.setattr(auto_intake.requests, "get", lambda *a, **k: rss)
    送 = []
    monkeypatch.setattr(notify, "送出", lambda m: 送.append(m))
    assert auto_intake.新片提醒({}) == 1
    文 = 送[0][0]["text"]
    assert len(送[0]) == 1 and "整理以下所有影片" in 文 and "影片連結如下" in 文 and "測試台｜" in 文 and "folders/" in 文
    assert "abcdefghijk" in 存["intake_seen.json"]["已通知"]
    assert auto_intake.新片提醒({}) == 0   # 第二次不重複提醒


def test_提醒訊息太長會分則():
    新 = [(f"id{i:09d}", f"https://www.youtube.com/watch?v=id{i:09d}", "標題" * 20, "2026-11-12") for i in range(40)]
    訊息們 = auto_intake.提醒訊息(新, 上限=1500)
    assert len(訊息們) > 1 and all(len(t) <= 1500 for t in 訊息們)
    assert sum(t.count("watch?v=") for t in 訊息們) == 40
