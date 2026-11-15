# 一眼判斷（glance.py）：表情、估值位階、三格判斷、風險、檢查表、注意分數、籌碼快訊
#   本機執行：python tests/test_glance.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import glance  # noqa: E402

列 = {"pe_p10": 10, "pe_p25": 12, "pe_p50": 15, "pe_p75": 20, "pe_p90": 25}
assert glance.位階百分位(15, 列) == 50
assert glance.位階百分位(10, 列) == 10 and glance.位階百分位(25, 列) == 90
assert glance.位階百分位(1, 列) == 0 and glance.位階百分位(100, 列) == 100
assert np.isnan(glance.位階百分位(-3, 列))
assert [glance.估值標籤(x) for x in (5, 20, 50, 80, 95)] == ["特價", "便宜", "合理", "偏貴", "昂貴"]
assert [n for n, _, _ in glance.估值價位(2, 列)] == ["特價", "便宜", "合理", "偏貴", "昂貴"]
assert glance.估值價位(2, 列)[2][1] == 30

assert glance.表情(70) == "😀" and glance.表情(50) == "😐" and glance.表情(30) == "😟" and glance.表情(np.nan) == "·"

今年 = pd.Timestamp.now().year
股利 = pd.DataFrame({"code": ["A"] * 4 + ["B"] * 2, "date": [f"{今年 - k}-07-01" for k in (1, 2, 3, 4)] + [f"{今年}-07-01", f"{今年 - 2}-07-01"],
                   "type": ["息"] * 6, "cash": [1] * 6})
assert glance.連續配息年數(股利) == {"A": 4, "B": 1}
損 = pd.DataFrame({"code": ["A"] * 9, "quarter": [f"2024Q{q}" for q in (1, 2, 3, 4)] + [f"2025Q{q}" for q in (1, 2, 3, 4)] + ["2026Q1"],
                  "eps": [-1, 1, 1, 1, 1, 1, 1, 1, 1]})
assert glance.連續獲利季數(損) == {"A": 8}

r = {"收盤": 110, "還原價": 110, "MA5": 105, "MA10": 102, "MA20": 100, "MA60": 95, "5日漲幅": 6, "法人5日買超": 3000,
     "RSI": 65, "營收年增率": 35, "距52週高點": -2, "EPS": 2, "融資維持率": 130, "當沖比率": 45}
三 = glance.三格判斷(r, 位階=20, 分數列={"基本": 70}, 體檢={})
assert [x["看法"] for x in 三] == ["偏多", "偏多", "偏多"], 三
險 = glance.風險清單(r, "處置 第一次處置", 95, {"建議": "出清"})
assert 險[0][0] == "高" and any("融資維持率" in t for _, t in 險) and any("停損" in t for _, t in 險)
assert "短線偏多" in glance.重點摘要(三, "合理", 險)
最壞 = glance.最壞情境(pd.Series(np.linspace(100, 50, 200)))
assert 最壞["中位數"] < 0 and 最壞["差的1/4"] <= 最壞["中位數"]

方們, 總 = glance.三方意見("偏多", {"家數": 3, "看多": 1, "中性": 0, "看空": 2, "中位數空間%": -5}, {"看多": 2, "看空": 0}, "偏多", {}, 70)
assert "分歧" in 總 and len(方們) == 4
assert "一致偏多" == glance.三方意見("偏多", None, {"看多": 3, "看空": 0})[1]

表 = glance.檢查表({**r, "本益比": 10, "殖利率": 6, "淨值比": 1, "營收創新高": True}, 6, 10, 20)
assert {x[1]: x[3] for x in 表}["月營收年增率"] == "優" and {x[1]: x[3] for x in 表}["本益比"] == "優"

分, 理 = glance.注意分數({"報酬率(%)": -20, "漲跌幅": -6, "融資維持率": 130}, {"較昨日": -6, "基本": 40}, {"建議": "出清"}, "處置", 95)
assert 分 >= 10 and "處置" in 理 and "破 10 日線" in 理

集, 項 = glance.籌碼集中度({"外資持股20日變化": 2, "融資20日增減": -10, "當沖比率": 20}, 0.5)
assert 集 > 60 and len(項) == 4

assert "漲停" in glance.漲跌原因({"代號": "1", "漲停": True, "成交張數": 1000, "法人買超": 400}, {"1": "董事會決議"})
assert glance.PEG(20, 40) == 0.5 and np.isnan(glance.PEG(20, -5))

位 = pd.DataFrame([列], index=pd.Index(["X"], name="code"))
今 = pd.DataFrame({"代號": ["X"], "收盤": [30.0], "本益比": [15.0], "預估本益比": [11.0], "明年預估本益比": [np.nan], "預估年度": [今年],
                  "融資維持率": [200.0], "營收創新高": [True]})
b = glance.徽章表(["X"], 今, 配息={"X": 5}, 獲利={"X": 9}, 期貨={"X"}, 位階表=位, 體檢={}, 配息上限=5)
assert b.at["X", "徽章"] == "連配5+ 賺 期 營收高", b
assert b.at["X", "估值"] == "合理" and b.at["X", "預估估值"] == "便宜"
print("✅ glance 測試通過")
