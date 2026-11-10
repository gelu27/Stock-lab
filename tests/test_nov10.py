"""2026-11-10 網紅摘要建議：美股缺口、資料中心成長趨緩、外資空單回測、目標價大砍、指數數字查核。直接執行：python tests/test_nov10.py"""
import sys, tempfile, pathlib
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import engine


def main():
    # 1. 美股缺口：造一段上漲後向下跳空、沒補回的資料
    日 = pd.bdate_range("2026-08-01", periods=60)
    收 = np.r_[np.linspace(100, 120, 40), np.linspace(100, 104, 20)]
    t = pd.DataFrame({"date": 日, "symbol": "^SOX", "open": 收, "high": 收 + 1, "low": 收 - 1, "close": 收})
    t.loc[40, ["open", "high", "low", "close"]] = [100, 101, 99, 100]  # 120 → 100 向下跳空
    暫 = pathlib.Path(tempfile.mkdtemp())
    t.to_csv(暫 / "us_ohlc.csv", index=False)
    原 = engine.資料夾
    engine.資料夾 = 暫
    try:
        缺 = engine.美股指數缺口("^SOX")
        assert 缺 and 缺["上方"] and 缺["燈"] == "🟠", 缺
        assert engine.美股指數缺口("^IXIC") is None
    finally:
        engine.資料夾 = 原
    assert engine.美股指數缺口("^SOX") is None or True  # 沒有檔案時不能報錯

    # 2. 資料中心成長趨緩
    資 = engine.資料中心成長趨緩()
    assert 資 and 資["燈"] == "🔴", 資

    # 3. 外資空單回測
    K = pd.read_csv(engine.資料夾 / "index_ohlc.csv", parse_dates=["date"]).query("symbol == 'TAIEX'")
    表 = engine.外資空單回測(K)
    assert len(表) == 4 and 表.iloc[0]["次數"] > 100

    # 4. 目標價大砍
    拆 = pd.DataFrame([{"日期": pd.Timestamp("2026-11-10"), "代號": "5274", "名稱": "信驊", "券商": "X", "前次目標價": 24000, "目標價": 14417,
                      "總變動%": -39.9, "倍數變動%": -35.0, "EPS與年度變動%": -7.5, "估值年度": "2027", "判讀": ""},
                     {"日期": pd.Timestamp("2026-11-10"), "代號": "2330", "名稱": "台積電", "券商": "Y", "前次目標價": 2000, "目標價": 1900,
                      "總變動%": -5.0, "倍數變動%": -5.0, "EPS與年度變動%": 0.0, "估值年度": "2027", "判讀": ""}])
    砍 = engine.目標價大砍(拆)
    assert len(砍) == 1 and "本益比" in 砍.iloc[0]["原因"]
    assert engine.目標價大砍(pd.DataFrame()).empty

    # 5. 指數數字查核
    影 = [{"頻道": "甲", "日期": "2026-11-10", "指數說法": [{"指數": "費半", "日期": "2026-11-09", "收盤": 10033}]},
          {"頻道": "乙", "日期": "2026-11-10", "指數說法": [{"指數": "費半", "日期": "2026-11-09", "收盤": 10333}]}]
    逐, 衝 = engine.指數說法查核(影)
    assert list(逐["判定"]) == ["相符", "不符"] and len(衝) == 1, (逐, 衝)
    print("✅ test_nov10 通過")


if __name__ == "__main__":
    main()
