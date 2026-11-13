"""LINE 推播省額度：合併送出、節省模式、查詢只用回覆。本機執行：python -m pytest tests/test_line_quota.py"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notify


def _假送(monkeypatch):
    送 = []
    monkeypatch.setattr(notify, "_直接送", lambda 訊, 類, 回覆="": 送.append((訊, 類, 回覆)))
    monkeypatch.setattr(notify, "記用量", lambda *a, **k: None)
    return 送


def test_節省模式門檻():
    日 = dt.date(2026, 11, 13)
    assert notify.節省模式({"上限": 200, "已用": 40}, 日) == ""
    assert notify.節省模式({"上限": 200, "已用": 121}, 日) == "省"     # 照速度月底約 279 則
    assert notify.節省模式({"上限": 200, "已用": 175}, dt.date(2026, 11, 28)) == "省"   # 85% 以上
    assert notify.節省模式({"上限": 200, "已用": 197}, dt.date(2026, 11, 28)) == "緊"   # 剩 3 則、剩 3 天
    assert notify.節省模式(None, 日) == ""
    assert notify.可以推播("新片提醒", "省") is False and notify.可以推播("大盤解讀", "省") is True
    assert notify.可以推播("大盤解讀", "緊") is False and notify.可以推播("收盤摘要", "緊") is True


def test_排程裡的通知合成一則(monkeypatch, tmp_path):
    送 = _假送(monkeypatch)
    monkeypatch.setenv("LINE_OUTBOX", str(tmp_path / "box.json"))
    monkeypatch.delenv("REPLY_TOKEN", raising=False)
    monkeypatch.setattr(notify, "節省模式", lambda 額=None, 今=None: "")
    notify.推播("📊 收盤摘要", "收盤摘要")
    notify.推播("🧠 收盤解讀", "大盤解讀")
    notify.推播("⚠️ 資料異常", "資料異常")
    notify.送出([{"type": "text", "text": "影片清單 1"}, {"type": "text", "text": "影片清單 2"}], "新片提醒")
    assert 送 == []   # 還沒送
    notify.送出待送()
    assert len(送) == 1, "全部只算 1 則推播"
    訊, 類, _ = 送[0]
    assert len(訊) <= 5 and 類 == ["收盤摘要", "大盤解讀", "資料異常", "新片提醒"]
    assert [m["text"] for m in 訊][-2:] == ["影片清單 1", "影片清單 2"], "影片清單要各自完整，不跟別的併"
    assert not (tmp_path / "box.json").exists()


def test_節省模式略過低優先(monkeypatch, tmp_path):
    送 = _假送(monkeypatch)
    monkeypatch.setenv("LINE_OUTBOX", str(tmp_path / "box.json"))
    monkeypatch.setattr(notify, "節省模式", lambda 額=None, 今=None: "省")
    notify.推播("🧠 夜盤解讀", "大盤解讀")
    notify.送出([{"type": "text", "text": "影片"}], "新片提醒")
    notify.送出待送()
    assert len(送) == 1 and 送[0][1] == ["大盤解讀"]
    assert "LINE_OUTBOX" not in os.environ   # 送出待送() 用完就清掉
    notify.推播("📍 大盤盤中關鍵價位", "盤中大盤價位")
    assert len(送) == 1, "沒有合併的低優先推播也要略過"


def test_回覆不受節省模式影響(monkeypatch):
    送 = _假送(monkeypatch)
    monkeypatch.setattr(notify, "節省模式", lambda 額=None, 今=None: "緊")
    monkeypatch.setenv("REPLY_TOKEN", "abc")
    monkeypatch.setenv("LINE_OUTBOX", "/tmp/不該用到.json")
    notify.送出([{"type": "text", "text": "新片"}], "新片提醒")
    assert 送 == [([{"type": "text", "text": "新片"}], ["新片提醒"], "abc")]


def test_併成五則():
    文 = lambda t: {"type": "text", "text": t}
    批們 = notify.併成五則([(文(str(i)), True) for i in range(8)])
    assert len(批們) == 1 and len(批們[0]) == 5
    批們 = notify.併成五則([(文(str(i)), False) for i in range(7)])
    assert [len(b) for b in 批們] == [5, 2], "不能併的超過 5 個就分兩次"
