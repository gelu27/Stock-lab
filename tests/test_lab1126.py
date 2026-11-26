# 網紅摘要 11/23 建議 N1～N6（流動性四燈、鎖死跌停、循環股本淨比、標普門檻）
#   本機執行：python tests/test_lab1126.py
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lab1126  # noqa: E402


def main():
    日 = pd.bdate_range("2026-01-05", periods=3)
    列 = []
    for c, 收, 高, 低 in [("1111", [100, 90, 81], [100, 90, 81], [100, 90, 81]),   # 連續兩天鎖死跌停
                        ("2222", [100, 100, 110], [100, 100, 110], [100, 100, 100]),  # 收漲停
                        ("3037", [100, 95, 96], [100, 96, 97], [100, 90, 91])]:    # 盤中跌停(90)後打開
        for i, d in enumerate(日):
            列.append({"date": d, "code": c, "name": c, "open": 收[i], "high": 高[i], "low": 低[i], "close": 收[i], "value": 1e8, "pe": 10.0})
    價 = pd.DataFrame(列)
    t = lab1126.鎖死跌停表(價)
    今 = t.iloc[0]
    assert 今["收跌停"] == 1 and 今["全日鎖死"] == 1 and 今["收漲停"] == 1, 今
    連 = lab1126.連續鎖死(價)
    assert list(連["代號"]) == ["1111"] and 連.iloc[0]["連續跌停天數"] == 2, 連
    燈 = lab1126.流動性四燈(價)
    assert 燈[0][2].startswith("3037") and 燈[0][0] == "🟢", 燈
    美 = pd.DataFrame({"S&P 500": [7000.0, 6800.0], "高收益債 HYG": [78.0, 77.0]}, index=pd.to_datetime(["2026-11-19", "2026-11-20"]))
    r = lab1126.標普條件(美)
    assert r["破門檻"] and round(r["距門檻%"], 2) == -0.66, r
    pb = pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=200), "code": "2603", "pb": list(range(1, 201)), "pe": 5.0})
    表 = lab1126.循環股本淨比(pb)
    assert 表.iloc[0]["本淨比"] == 200 and 表.iloc[0]["位階%"] == 100, 表
    print("✅ lab1126 氣氛工具")


if __name__ == "__main__":
    main()
