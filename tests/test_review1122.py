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
    print("綜合評估 11/22 修正：全部通過")


if __name__ == "__main__":
    main()
