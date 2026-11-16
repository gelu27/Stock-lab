# 券商報告寫法借鏡（2026-11-16）：評價基礎、前次倍數、四象限拆解、財報對答案、升降評、估值風向。python tests/test_broker_logic.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def 報(**k):
    基 = {"代號": "2345", "名稱": "智邦", "券商": "富邦", "日期": "2026-11-16", "評等": "買進", "看法": "看多",
          "目標價": None, "前次目標價": None, "EPS今年": None, "EPS明年": None, "前次EPS今年": None, "前次EPS明年": None,
          "報告收盤價": None, "評價方法": "", "理由": [], "風險": "", "白話": []}
    基.update(k)
    return 基


def test_前次倍數與營收比():
    析 = engine.解析評價("20 倍 × 2027 EPS 114.52 元（前次 30 倍）")
    assert (析["倍數"], 析["前次倍數"], 析["基礎"]) == (20, 30, "本益比")
    assert engine.解析評價("10 倍 × 2027 EPS 42.26（原 13 倍，調降倍數）")["前次倍數"] == 13
    ps = engine.解析評價("9 倍 × 2027 年預估每股營收 40.14 元（約當 51 倍 2027 EPS 6.97 元）；採 PS 而非 PE")
    assert ps["基礎"] == "營收比" and ps["倍數"] == 9
    assert engine.解析評價("1.6 倍 × 2027 年 BVPS 36.5 元(股價淨值比)")["基礎"] == "淨值比"
    assert engine.解析評價("約 38.2 倍 × 2027 EPS 0.79 元，約 1 倍股價淨值比")["基礎"] == "本益比"
    assert engine.解析評價("15 倍 PER × 未來 12 個月（4Q26-3Q27）EPS 約 35.95 元")["滾動"]


def test_四象限判讀():
    assert "雙殺" in engine.拆解判讀(-0.36, -0.22, -0.17)
    assert "雙擊" in engine.拆解判讀(0.3, 0.1, 0.18)
    assert "降倍數" in engine.拆解判讀(-0.16, -0.23, 0.09)
    assert "倍數拉高" in engine.拆解判讀(-0.28, 1.13, -0.66)   # 舊版會誤寫成「降倍數」


def test_拆解用前次倍數():
    x = 報(目標價=2290, 前次目標價=3500, EPS明年=114.52, 前次EPS明年=116.08, 評價方法="20 倍 × 2027 EPS 114.52 元（前次 30 倍）",
          理由=["3Q26 EPS 23.39 元低於預期", "因 AI 投資疑慮、類股評價下修，目標價由 3500 降至 2290 元"])
    t = engine.目標價拆解([x])
    assert round(t.loc[0, "倍數變動%"]) == -33 and "降倍數" in t.loc[0, "判讀"]
    assert "AI 投資疑慮" in t.loc[0, "券商說法"]
    標 = engine.報告標籤(x)
    assert "財報低於預期" in 標


def test_營收比不拿EPS反推():
    x = 報(代號="6533", 名稱="晶心科", 目標價=360, 前次目標價=250, EPS明年=6.97, 前次EPS明年=4.68,
          評價方法="9 倍 × 2027 年預估每股營收 40.14 元；採 PS 而非 PE", 理由=["評等由中立升至買進"])
    t = engine.目標價拆解([x])
    assert "營收比" in t.loc[0, "判讀"]
    標 = engine.報告標籤(x)
    assert "營收比評價" in 標 and "升評" in 標


def test_升降評不誤判毛利率():
    assert engine.評等變動(報(評等="中立（由買進調降）")) == "降評"
    assert engine.評等變動(報(理由=["毛利率由 17.6% 升至 19.5%"])) is None
    assert engine.財報對答案(報(理由=["3Q26 EPS 2.34 元，優於元大預期 7%、低於市場預期 17%"])) == "好壞參半"
    assert engine.財報對答案(報(風險="新製程不如預期")) is None   # 風險段是假設，不算


def test_一次性新字():
    assert "一次性" in engine.報告標籤(報(理由=["提列存貨跌價損失約影響毛利率 2 個百分點"]))


def test_估值風向():
    報們 = [報(代號=str(i), 名稱=f"股{i}", 目標價=80, 前次目標價=100, 評價方法="16 倍 × 2027 EPS 5（前次 20 倍）") for i in range(4)]
    報們.append(報(代號="9", 名稱="股9", 目標價=120, 前次目標價=100, 評價方法="24 倍 × 2027 EPS 5（前次 20 倍）"))
    風 = engine.估值風向(報們, 今天="2026-11-16")
    assert 風["降倍數"] == 4 and 風["升倍數"] == 1 and "調降評價倍數" in 風["文字"]
    週 = engine.估值風向週表(報們)
    assert int(週.loc[0, "降倍數"]) == 4
    assert "倍數 -20.0%" in engine.拆解文字(報們)


def test_虧損IP建議營收比():
    assert "P/S" in engine.評價方法建議("半導體業", -1.0)
    assert "P/B" in engine.評價方法建議("建材營造", -1.0)


if __name__ == "__main__":
    for 名, f in list(globals().items()):
        if 名.startswith("test_") and callable(f):
            f()
    print("✅ 券商報告寫法（評價基礎、四象限拆解、財報對答案、估值風向）正常")
