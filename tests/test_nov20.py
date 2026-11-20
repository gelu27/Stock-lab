"""2026-11-20 網紅摘要補強（台指 VIX、四象限、ODM 存貨銷售比、限空令追蹤、落底訊號、新片去重）。直接執行：python tests/test_nov20.py"""
import sys, pathlib
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import lab1120 as L
import auto_intake as A


def main():
    # VIX 解析
    t = L.解析台指VIX("日期,臺指選擇權波動率指數\n2026/11/19,45.1\n2026/11/20,50.3\n")
    assert list(t["close"]) == [45.1, 50.3] and t.loc[0, "date"] == "2026-11-19", t
    assert L.解析台指VIX("<html>查無資料</html>") is None

    # VIX 回測：第 10 天站上 40，之後大盤每天 +1
    日 = pd.bdate_range("2025-01-01", periods=200)
    vix = pd.Series(20.0, index=日); vix.iloc[100:105] = 45
    大 = pd.Series(np.arange(100, 300, dtype=float), index=日)
    r = L.VIX回測(vix, 大, 門檻=(40,), 天數=(5,))
    assert r.loc[0, "次數"] == 1 and r.loc[0, "5 日上漲%"] == 100 and r.iloc[-1]["VIX 門檻"] == "全部日子", r
    assert L.VIX現況(vix)["VIX"] == 20.0

    # 單季與四象限：2026Q3 營益 120（去年 100，年增 20，上季年增 10 → 成長加速）
    def 列(c, q, rev, op): return {"code": c, "quarter": q, "revenue": rev, "gross": rev / 2, "opinc": op}
    inc = pd.DataFrame([
        列("1111", "2025Q1", 100, 100), 列("1111", "2025Q2", 200, 200), 列("1111", "2025Q3", 300, 300),
        列("1111", "2026Q1", 100, 110), 列("1111", "2026Q2", 220, 220), 列("1111", "2026Q3", 340, 340),
        列("2222", "2025Q1", 100, 100), 列("2222", "2025Q2", 200, 200), 列("2222", "2025Q3", 300, 300),
        列("2222", "2026Q1", 100, 150), 列("2222", "2026Q2", 200, 290), 列("2222", "2026Q3", 300, 410)])
    s = L.單季(inc)
    assert list(s[s.code == "1111"]["單季營益"]) == [100, 100, 100, 110, 110, 120], s[s.code == "1111"]["單季營益"].tolist()
    象, 季 = L.營益四象限(inc)
    m = 象.set_index("code")["象限"]
    assert 季 == "2026Q3" and m["1111"] == "成長加速" and m["2222"] == "成長放緩", 象

    # ODM 存貨銷售比
    存 = pd.DataFrame({"code": ["1111"] * 3, "quarter": ["2026Q1", "2026Q2", "2026Q3"], "inventory": [50, 80, 130]})
    o = L.ODM存貨銷售比(inc, 存, {"1111": "甲"})
    assert list(o["存貨銷售比"]) == [0.5, 0.667, 1.083] and len(L.ODM警訊(o)) == 1, o
    assert L.ODM存貨銷售比(inc, None).empty

    # 限空令事件追蹤
    追 = L.限空事件追蹤(大, [(str(日[10].date()), "事件甲"), (str(日[-3].date()), "事件乙")], 天數=(5,))
    assert 追.loc[0, "5 日%"] is not None and pd.isna(追.loc[1, "5 日%"]) and 追.loc[1, "至今天數"] == 2, 追

    # 谷底量：量縮到 40% 且沒破低
    量 = pd.Series(1000.0, index=日); 量.iloc[-1] = 400
    谷 = L.谷底量(量, 大)
    assert bool(谷["量縮不破底"].iloc[-1]) and not bool(谷["量縮不破底"].iloc[-2])
    領 = pd.Series(np.r_[np.linspace(100, 80, 100), np.linspace(81, 95, 100)], index=日)
    大2 = pd.Series(np.r_[np.linspace(100, 70, 100), np.linspace(70, 60, 100)], index=日)
    assert bool(L.領頭羊墊高(領, 大2).iloc[-1])

    # 新片去重：雲端標題 vs YouTube 標題
    清單 = [(pd.Timestamp("2026-11-19"), A._標題鍵("[理財達人秀 EBCmoneyshow] 2026-11-19 【理財達人秀】限空令加嚴！5落底訊號！CPO殺過頭 全_詳細整理"))]
    assert A.已整理過("【理財達人秀】限空令加嚴！5落底訊號！CPO殺過頭 PCB鎖資減大戶買！", "2026-11-20", 清單)
    assert not A.已整理過("【理財達人秀】限空令加嚴！5落底訊號！CPO殺過頭", "2026-11-25", 清單)
    assert not A.已整理過("完全不同的影片標題在這裡", "2026-11-19", 清單)
    print("test_nov20 OK")


if __name__ == "__main__":
    main()
