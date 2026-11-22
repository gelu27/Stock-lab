# 2026-11-22 全站綜合評估修正：大檔案讀取（券商報告超過 1MB）、法人缺漏警示、本益比型別防護：python tests/test_review1122.py
import gzip
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402
import notify  # noqa: E402


class 假回應:
    def __init__(self, 狀態, 內容=b"", j=None, url="https://api.github.com/x"):
        self.status_code, self.content, self._j, self.url = 狀態, 內容, j, url

    def json(self):
        return self._j

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def main():
    大 = {"報告": [{"代號": "2330", "券商": "某券商", "日期": "2026-11-20", "理由": ["x" * 2000]}] * 600}
    原文 = json.dumps(大, ensure_ascii=False).encode("utf-8")
    assert len(原文) > 1024 * 1024
    設 = {"GITHUB_TOKEN": "t" * 40, "AI_REPO": "o/r"}
    看到 = {}

    def 假get(url, params=None, headers=None, timeout=None):
        看到["accept"] = headers.get("Accept")
        # raw 格式才給內容；一般格式超過 1MB 時 content 是空字串
        if headers.get("Accept", "").endswith("raw+json"):
            return 假回應(200, 原文)
        return 假回應(200, j={"content": "", "encoding": "none", "sha": "abc"})

    with mock.patch("requests.get", 假get):
        r = engine.讀取券商報告(設)
    assert len(r) == 600 and 看到["accept"].endswith("raw+json"), (len(r), 看到)

    # 嚴格模式：讀失敗要丟錯（不能用空清單把舊報告蓋掉）
    def 壞get(*a, **k):
        return 假回應(500)
    with mock.patch("requests.get", 壞get):
        assert engine.讀取券商報告(設) == []
        try:
            engine.讀取券商報告(設, 嚴格=True)
            raise AssertionError("應該丟錯")
        except RuntimeError:
            pass

    # notify.讀設定：一般格式 content 空 → 改用 raw
    def 假get2(url, params=None, headers=None, timeout=None):
        if headers.get("Accept", "").endswith("raw+json"):
            return 假回應(200, 原文)
        return 假回應(200, j={"content": "", "encoding": "none", "sha": "abc", "download_url": "https://raw/x"})
    with mock.patch.object(notify.requests, "get", 假get2):
        內, sha = notify.讀設定("broker_reports.json")
    assert len(內["報告"]) == 600 and sha == "abc"

    # 法人缺漏：某天外資只有一部分
    with tempfile.TemporaryDirectory() as d:
        夾 = Path(d) / "chips" / "2026-11"
        夾.mkdir(parents=True)
        for i, 日 in enumerate(["20261113", "20261116", "20261117", "20261118", "20261119"]):
            n = 400 if 日 == "20261117" else 1000
            t = pd.DataFrame({"code": [str(1000 + k) for k in range(1000)],
                              "foreign": [1.0] * n + [None] * (1000 - n)})
            with gzip.open(夾 / f"{日}.csv.gz", "wt", encoding="utf-8") as f:
                t.to_csv(f, index=False)
        with mock.patch.object(notify, "資料夾", Path(d)):
            缺 = notify._法人缺漏()
    assert 缺 == ["11/17（400/1000 檔）"], 缺

    # 大盤本益比：收盤、本益比是字串也要能算
    t = pd.DataFrame({"market": ["上市"] * 150, "code": [str(2000 + i) for i in range(150)],
                      "close": ["100"] * 150, "pe": ["20"] * 150})
    股 = pd.DataFrame({"code": [str(2000 + i) for i in range(150)], "shares": ["1000"] * 150, "industry": ["其他"] * 150})
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "fundamental").mkdir()
        股.to_csv(Path(d) / "fundamental" / "capital.csv", index=False)
        (Path(d) / "prices" / "2026-11").mkdir(parents=True)
        with gzip.open(Path(d) / "prices" / "2026-11" / "20261120.csv.gz", "wt", encoding="utf-8") as f:
            t.to_csv(f, index=False)
        with mock.patch.object(engine, "資料夾", Path(d)):
            r = engine._大盤本益比(1)
    assert abs(float(r["本益比"].iloc[-1]) - 20) < 1e-6, r
    # 依盤勢切換權重（2026-11-22 TAi 決定）
    import numpy as np
    漲 = np.linspace(100, 200, 300)            # 一路漲：年線上、60 日漲 > 10%
    assert engine.判斷盤勢(漲)[0] == "強多頭"
    緩 = np.linspace(100, 104, 300)            # 年線上但 60 日漲不到 10%
    assert engine.判斷盤勢(緩)[0] == "多頭"
    跌 = np.r_[np.linspace(100, 120, 260), np.linspace(120, 100, 40)]   # 20 日跌 > 8%
    assert engine.判斷盤勢(跌)[0] == "崩跌"
    空 = np.r_[np.full(240, 120.0), np.linspace(119, 110, 60)]          # 年線下、20 日跌不到 8%
    assert engine.判斷盤勢(空)[0] == "空頭", engine.判斷盤勢(空)
    assert engine.判斷盤勢([100] * 30)[0] == "不明"
    assert engine.盤勢權重({"盤勢": "強多頭"})["市場"] == 0.2 and engine.盤勢權重({"盤勢": "崩跌"})["市場"] == 0
    assert abs(sum(engine.評分權重.values()) - 1) < 1e-9 and abs(sum(engine.強多頭權重.values()) - 1) < 1e-9
    assert "強多頭" in engine.盤勢權重說明({"盤勢": "強多頭", "數字": {"漲60日": 12.0}})
    assert engine.盤勢權重說明({"盤勢": "不明"}) == ""
    明 = pd.DataFrame({"技術": [50, 50], "籌碼": [50, 50], "基本": [50, 50], "市場": [100, 100], "盤勢": ["強多頭", "空頭"]})
    總 = engine.加權總分(明)
    assert 總.iloc[0] == 60 and 總.iloc[1] == 50, 總   # 強多頭市場面佔 20%：50×0.8＋100×0.2
    K = pd.DataFrame({"date": pd.bdate_range("2025-01-01", periods=300), "close": 漲})
    勢 = engine.盤勢序列(K)
    assert 勢.iloc[-1] == "強多頭" and 勢.iloc[0] == "不明"
    大 = engine.大盤評分(K, pd.DataFrame({"代號": ["2330"], "收盤": [1.0], "漲跌幅": [1.0]}))
    assert 大["盤勢"] == "強多頭" and "漲60日" in 大["數字"]
    # 80 分名單太長只列前 20 檔（庫存一定列）
    分 = pd.DataFrame({"名稱": [f"股{i}" for i in range(30)], "總分": [90 - i * 0.1 for i in range(30)],
                      "較昨日": [0.0] * 30, "收盤": [10.0] * 30, "漲跌幅": [1.0] * 30},
                     index=[str(1100 + i) for i in range(30)])
    行, _ = notify.高分名單變化(分, "2026-11-23", {}, 庫存們={"1129"})
    assert sum(1 for x in 行 if x.startswith(("11", "💼"))) == 21 and any("其餘 9 檔" in x for x in 行), 行
    # 三步篩選：量太小、ETF、分數不夠、跌破 20 日線的都排除，依總分排序
    分 = pd.DataFrame({"總分": [80, 90, 76, 60, 85], "5日均量": [1000, 1000, 1000, 1000, 100]},
                      index=["1101", "2330", "0050", "2317", "3008"])
    d = pd.DataFrame({"還原價": [10, 10, 10, 10, 10], "MA20": [9, 9, 9, 9, 9]}, index=分.index)
    d.loc["1101", "MA20"] = 11
    表, 數 = engine.三步篩選(分, d)
    assert list(表.index) == ["2330"] and 數 == {"全部": 3, "第二步": 2, "第三步": 1}, (表, 數)
    print("綜合評估 11/22 修正：全部通過")


if __name__ == "__main__":
    main()
