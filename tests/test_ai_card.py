"""AI 報告 json 拆解與目標價合理性檢查。本機執行：python tests/test_ai_card.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402

裸 = '{\n  "看法": "偏多",\n  "目標價保守": 26.4,\n  "目標價合理": 33.0,\n  "目標價樂觀": 44.0,\n  "券商目標價": null,\n' \
     '  "預估本益比": 15,\n  "評價方法": "15 倍 × 2027 EPS 2.20",\n  "支撐": 16.76,\n  "壓力": 16.95,\n  "停損": 16.45\n}'


def test_只貼裸json():
    內文, 建議 = engine.拆解AI建議(裸)
    assert 內文 == ""
    assert 建議["目標價合理"] == 33.0 and 建議["券商目標價"] is None


def test_報告後面接裸json():
    內文, 建議 = engine.拆解AI建議("### 一句話結論\n偏多\n\n" + 裸)
    assert "{" not in 內文 and 建議["看法"] == "偏多"


def test_沒標語言的程式碼區塊():
    內文, 建議 = engine.拆解AI建議("# 報告\n內文\n```\n" + 裸 + "\n```")
    assert 內文 == "# 報告\n內文" and 建議["支撐"] == 16.76


def test_目標價檢查():
    _, 建議 = engine.拆解AI建議(裸)
    提醒 = engine.檢查AI目標價(建議, 16.8, 9.77, 27.55)
    文 = "\n".join(提醒)
    assert "高 96%" in 文 and "倍數拉高" in 文 and "近三年最高" in 文 and "時間尺度" in 文
    assert not any("不一致" in 句 for 句 in 提醒)  # 15 × 2.20 = 33 對得上
    assert engine.檢查AI目標價(dict(建議, 目標價合理=40.0), 16.8)[0].startswith("評價方法")
    assert engine.檢查AI目標價({"目標價合理": 18, "支撐": 15, "壓力": 19, "停損": 14.5}, 16.8, 10) == []


if __name__ == "__main__":
    for 名, 函 in list(globals().items()):
        if 名.startswith("test_"):
            函()
            print(f"✅ {名}")
