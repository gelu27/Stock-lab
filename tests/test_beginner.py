# 自動檢查：新手白話模式、AI 數據包與數字查核、族群輪動階段、市場健康分數
#   本機執行：python tests/test_beginner.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ai_debate  # noqa: E402
import beginner  # noqa: E402
import momentum  # noqa: E402

錯誤 = []


def 檢查(條件, 說明):
    print(("✅ " if 條件 else "❌ ") + 說明)
    if not 條件:
        錯誤.append(說明)


# ---- 名詞小卡 ----
for k, v in beginner.名詞卡.items():
    檢查(len(v) == 3 and all(v), f"名詞卡 {k} 有白話／怎麼用／陷阱三欄")
檢查(beginner.找名詞("RSI(14)") == "RSI", "找名詞：RSI(14) → RSI")
檢查(beginner.找名詞("外資買超") == "三大法人", "找名詞：別名 外資 → 三大法人")
檢查(beginner.找名詞("收盤價") is None, "找名詞：沒有對應名詞時回傳 None")
檢查("<script" not in beginner.小卡HTML("RSI") and "tipbox" in beginner.小卡HTML("RSI"), "小卡 HTML 有跳脫、有說明框")

# ---- 白話燈號 ----
熱 = beginner.白話燈號({"收盤": 120, "RSI": 82}, {5: 115, 20: 100, 60: 90})
檢查(熱[0][0] == "🔥" and "過熱" in 熱[0][1], "RSI 82、離月線 +20% → 第一個燈是過熱")
檢查(any("多頭排列" in x[1] for x in 熱), "收盤 > 5 > 20 > 60 日線 → 多頭排列")
檢查(beginner.一句話結論(熱).startswith("🔥"), "又熱又多頭 → 一句話是「好股票但太熱」")
空 = beginner.白話燈號({"收盤": 80, "RSI": 40, "法人5日買超": -5000, "外資連賣": 4}, {5: 85, 20: 90, 60: 100})
檢查(beginner.一句話結論(空).startswith("🔴"), "空頭排列＋外資連賣 → 先跑")
檢查(beginner.一句話結論([]).startswith("🟡"), "沒有燈號 → 資料不足")

# ---- AI 數據包與數字查核 ----
r = pd.Series({"收盤": 1000.0, "漲跌幅": 1.5, "RSI": 63.2, "本益比": 22.5, "毛利率": 58.1, "營收年增率": 35.0, "EPS": np.nan})
包 = ai_debate.數據包("2330", "台積電", r, 支撐=950, 壓力=1080)
檢查(包["價格"]["收盤"] == 1000.0 and 包["基本面"]["今年累計EPS"] is None, "數據包：數字照抄，NaN 變 None")
核, 錯 = ai_debate.數字查核("- 收盤 1,000 元，RSI 63，本益比 22.5 倍，毛利率 58%，支撐 950", 包)
檢查(核 >= 5 and not 錯, f"數字都對 → 沒有錯（核對 {核} 個）")
核, 錯 = ai_debate.數字查核("股價收在 1200 元，本益比 15 倍", 包)
檢查(len(錯) == 2, f"編造股價與本益比 → 抓到 2 個錯：{錯}")
核, 錯 = ai_debate.數字查核("EPS 30 元", 包)
檢查(核 == 0, "數據包沒有的數字（EPS 是空的）→ 不核對，不誤判")

# ---- 族群輪動階段 ----
列們 = []
for 群, 龍20, 二20, 龍5, 二5 in (("甲", 20, 3, 5, 1), ("乙", 10, 6, 0, 4), ("丙", -6, -5, -2, -2), ("丁", 12, 11, 2, 2)):
    for i in range(8):
        龍 = i < 3
        列們.append({"代號": f"{群}{i}", "名稱": f"{群}{i}", "產業": 群, "收盤": 100.0, "發行股數": 1e9 if 龍 else 1e7 * (i + 1),
                   "20日漲幅": 龍20 if 龍 else 二20, "5日漲幅": 龍5 if 龍 else 二5})
階 = momentum.族群輪動階段(pd.DataFrame(列們)).set_index("族群")["階段"]
檢查(階.get("甲") == "龍頭領漲期", "龍頭大漲、二線沒跟 → 龍頭領漲期")
檢查(階.get("乙") == "二線補漲期", "龍頭漲過、近 5 日二線較強 → 二線補漲期")
檢查(階.get("丙") == "退潮", "兩邊都跌 → 退潮")
檢查(階.get("丁") == "全面上攻", "兩邊都大漲且接近 → 全面上攻")

# ---- 市場健康分數 ----
天 = pd.bdate_range("2025-01-01", periods=160)
rng = np.random.default_rng(1)
指 = []
for c in range(30):
    p = 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, len(天)))
    s = pd.Series(p)
    指.append(pd.DataFrame({"date": 天, "代號": f"{1000 + c}", "還原價": p, "MA20": s.rolling(20).mean(), "漲跌": s.diff()}))
指 = pd.concat(指)
加 = pd.DataFrame({"date": 天, "close": 20000 * np.cumprod(1 + rng.normal(0.0005, 0.01, len(天)))})
vix = pd.DataFrame({"date": 天, "close": 15 + rng.normal(0, 2, len(天))})
日, 回 = momentum.資金水位(指, 加, vix)
檢查(len(日) > 100 and 日["分數"].between(0, 100).all(), "分數都在 0～100")
檢查(日["建議持股%"].between(20, 90).all(), "建議持股在 20%～90%")
檢查(len(回) == 3 and int(回["天數"].sum()) == int(日["之後20日%"].notna().sum()), "回測三組天數加起來＝有未來報酬的天數")

print()
if 錯誤:
    print(f"❌ {len(錯誤)} 項沒通過")
    sys.exit(1)
print("✅ 全部通過")
