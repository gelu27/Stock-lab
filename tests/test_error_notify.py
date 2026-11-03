# 自動檢查：網站錯誤通知不重複推播（已通知過、或很久沒再發生的錯誤不再通知）
#   本機執行：python tests/test_error_notify.py
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notify

現在 = dt.datetime.now(notify.台北)
近 = (現在 - dt.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
舊 = (現在 - dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
錯誤 = {
    "a": {"頁面": "01 首頁", "類型": "KeyError", "訊息": "x", "次數": 2, "最近": 近},
    "b": {"頁面": "02 自選", "類型": "KeyError", "訊息": "y", "次數": 1, "最近": 舊},
    "c": {"頁面": "03 個股", "類型": "KeyError", "訊息": "z", "次數": 3, "最近": 近},
}
存檔 = {"alert_state.json": {"網站錯誤已通知": {"c": 3}}}


def 讀(檔名):
    return (錯誤 if 檔名 == "errors.json" else 存檔.get(檔名, {})), "sha"


def 寫(檔名, 內容物, sha):
    存檔[檔名] = 內容物


notify.讀設定, notify.寫設定 = 讀, 寫
第一次 = notify.網站錯誤()
assert len(第一次) == 1 and 第一次[0].startswith("01 首頁"), 第一次  # b 太舊、c 已通知過
assert notify.網站錯誤() == [], "同一批錯誤不應該再通知"
錯誤["a"]["次數"] = 3
assert len(notify.網站錯誤()) == 1, "同一個錯誤又發生要再通知"


def 壞掉(檔名, 內容物, sha):
    raise RuntimeError("401")


notify.寫設定 = 壞掉
存檔["alert_state.json"] = {}
for k in 錯誤:
    錯誤[k]["最近"] = 舊
assert notify.網站錯誤() == [], "存檔失敗時，很久沒再發生的錯誤也不應該重複通知"
print("✅ 網站錯誤通知不會重複推播")
