"""2026-11-18 網紅摘要補強（國安跟買、投信連賣散戶升、跌破 20 週線、底高、風險標記）。直接執行：python tests/test_nov18.py"""
import sys, pathlib
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import lab1118 as L


def main():
    日 = pd.bdate_range("2024-01-01", periods=300)
    價 = pd.DataFrame({"2330": np.linspace(100, 160, 300), "2308": np.linspace(100, 70, 300)}, index=日)
    大 = pd.Series(np.linspace(100, 130, 300), index=日)
    紀 = pd.DataFrame({"次": ["1", "2"], "決議日": [str(日[10].date()), "2000-03"], "退場日": ["", ""]})
    表 = L.護盤跟買(價, 大, 紀, 天數=(20, 60))
    assert list(表["期間"]) == ["20 日", "60 日", "至今 289 日"], 表
    assert abs(表.loc[0, "2330 台積電%"] - (價["2330"].iloc[30] / 價["2330"].iloc[10] - 1) * 100) < 0.06
    勝 = L.護盤跟買勝率(表)
    assert 勝.set_index("標的").loc["2330 台積電", "上漲比例%"] == 100 and 勝.set_index("標的").loc["2308 台達電", "上漲比例%"] == 0

    assert L.連賣天數([1, -1, -2, -3]) == 3 and L.連賣天數([-1, 2]) == 0
    assert L.是個股("2330") and not L.是個股("00632R") and not L.是個股("0050")

    # 投信連賣 6 天、散戶持股 20 → 23
    日2 = pd.bdate_range("2026-10-01", periods=30)
    指 = pd.concat([pd.DataFrame({"代號": c, "date": 日2, "投信買超": [5.0] * 24 + [-3.0] * 6 if c == "1111" else [5.0] * 30,
                                 "名稱": c, "收盤": 10.0, "漲跌幅": 0.0, "20日漲幅": 0.0}) for c in ("1111", "2222")])
    集 = pd.DataFrame({"code": ["1111"] * 5 + ["2222"] * 5, "date": list(pd.date_range("2026-10-01", periods=5, freq="7D")) * 2,
                     "retail": [20, 20, 21, 22, 23] + [20, 20, 20, 20, 19]})
    r = L.投信連賣散戶升(指, 集, 連賣下限=5)
    assert list(r["代號"]) == ["1111"] and r.loc[0, "散戶持股變化(個百分點)"] == 3.0 and r.loc[0, "投信連賣天"] == 6, r
    assert L.投信連賣散戶升(指, 集, 連賣下限=7).empty

    # 20 週線：一檔上漲後最後兩週暴跌
    日3 = pd.bdate_range("2025-06-02", periods=200)
    收 = np.r_[np.linspace(100, 200, 190), np.full(10, 120.0)]
    指3 = pd.DataFrame({"代號": "1234", "date": 日3, "收盤": 收, "value": 1e9, "外資買超": -5.0, "名稱": "測試"})
    r = L.跌破20週線(指3, 檔數=10)
    assert len(r) == 1 and r.loc[0, "距20週線%"] < 0, r

    # 底高：高點 200 → 低 100（−50%）→ 反彈 → 低 110（更高）
    n = 260
    收 = np.r_[np.full(100, 200.0), np.linspace(200, 100, 30), np.linspace(100, 140, 20), np.linspace(140, 110, 20), np.linspace(110, 150, 90)]
    s = pd.Series(收, index=pd.bdate_range("2024-01-01", periods=len(收)))
    日們 = L.底高訊號日(s, s)
    assert len(日們) >= 1 and all(d > s.index[129] for d in 日們), 日們
    assert L.底高訊號日(pd.Series(np.linspace(100, 200, n)), pd.Series(np.linspace(100, 200, n))) == []

    風 = pd.DataFrame({"code": ["2382"], "風險": ["估值"], "依據": ["x"], "更新日": ["2026-11-18"]})
    assert L.風險標記文字("2382", 風)[0].startswith("⚠️ 估值") and L.風險標記文字("2330", 風) == []
    print("ok")


if __name__ == "__main__":
    main()
