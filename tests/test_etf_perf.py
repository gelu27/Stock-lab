# 自動檢查：主動式 ETF 績效體檢（etf_perf）與除權息日報酬
#   本機執行：python tests/test_etf_perf.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402
import etf_perf  # noqa: E402


def main():
    錯誤 = []

    def 檢查(名, 實際, 預期, 容許=0.01):
        if not abs(實際 - 預期) <= 容許:
            錯誤.append(f"{名}：得到 {實際}，應該是 {預期}")

    rng = np.random.default_rng(1)
    日 = pd.bdate_range("2026-01-02", periods=200)
    m = pd.Series(rng.normal(0.001, 0.015, len(日)), index=日)
    l2 = 2 * m
    寬 = pd.DataFrame({"0050": m, "00631L": l2,
                      "00001A": 0.5 * m + 0.5 * l2,             # 就是 beta 1.5 的組合，超額應該 0
                      "00002A": 1.3 * m + 0.0004,               # 每天多賺 0.04%，超額要是正的
                      "00003A": 0.6 * m + 0.4 * 0.017 / 252})   # beta 0.6 配現金，超額 0
    寬.loc[日[:30], "00002A"] = np.nan                          # 晚上市，從上市後算
    t = etf_perf.體檢表(寬, ["00001A", "00002A", "00003A"], "2026-01-01").set_index("代號")
    檢查("組合本身 beta", t.at["00001A", "beta"], 1.5)
    檢查("組合本身超額", t.at["00001A", "超額vs組合%"], 0, 0.05)
    檢查("配現金超額", t.at["00003A", "超額vs組合%"], 0, 0.05)
    if not t.at["00002A", "超額vs組合%"] > 3:
        錯誤.append(f"每天多賺的超額應該明顯為正：{t.at['00002A', '超額vs組合%']}")
    檢查("晚上市天數", t.at["00002A", "天數"], 170, 0)
    檢查("0050 對自己 beta", t.at["0050", "beta"], 1)
    if not pd.isna(t.at["00631L", "超額vs組合%"]):
        錯誤.append("正 2 本身不該算同 beta 超額")

    # 純槓桿攻守比：上漲段、下跌段都單邊時，2 倍不會等於 1
    上 = pd.Series([0.01] * 20 + [-0.01] * 20, index=pd.bdate_range("2026-01-01", periods=40))
    比 = etf_perf.純槓桿攻守比(上, 2, (上.index[0], 上.index[19]), (上.index[20], 上.index[39]))
    if not 比 > 1.1:
        錯誤.append(f"純 2 倍攻守比應明顯大於 1：{比}")

    # 滾動超額：組合本身一直是 0
    s = etf_perf.滾動超額(寬, "00001A", 窗=60)
    檢查("滾動超額筆數", len(s), 141, 0)
    檢查("滾動超額最大絕對值", float(s.abs().max()), 0, 0.05)

    # 台積電因素
    台權 = pd.DataFrame({"etf": ["00001A"] * 2, "date": 日[:2], "weight": [9.0, 11.0]})
    台報 = pd.Series([0.0, 0.2], index=日[:2])
    f = etf_perf.台積電因素(台權, 50.0, 台報).set_index("代號")
    檢查("台積電影響", f.at["00001A", "台積電影響(百分點)"], -8.0)
    檢查("0050 權重估算", etf_perf.估計0050台積電權重(["2330", "2317"], {"2330": 60, "2317": 40}), 60)

    # 除權息當天交易所漲跌是空值 → 用參考價補回股利
    engine.除權息參考價 = lambda: pd.DataFrame({"code": ["9999"], "date": [pd.Timestamp("2026-01-03")], "ref": [9.0]})
    原 = engine.讀取資料庫(最近天數=5, 代號=["2330"]).tail(2).reset_index(drop=True)   # 用真的欄位，改成假股票
    原["code"], 原["date"] = "9999", pd.to_datetime(["2026-01-02", "2026-01-03"])
    原["close"], 原["change"] = [10.0, 9.18], [0.0, np.nan]
    檢查("除息日報酬", float(engine.計算指標(原)["日報酬"].iloc[1]), 0.02, 0.0005)
    # 槓桿型 ETF 單日 18% 不能被截在 10.5%
    原2 = 原.assign(code="00999L", change=[0.0, 1.8], close=[10.0, 11.8])
    檢查("正 2 單日大漲", float(engine.計算指標(原2)["日報酬"].iloc[1]), 0.18, 0.001)

    # 費用：網頁文字解析、只補空白與自動列，手動填的不動
    import tempfile
    import etf_data
    經, 保, _ = etf_data.解析費用("<tr><td>管理費(%)</td><td>1.20%（200億以下）、1.00%</td></tr><td>保管費</td><td>0.035 %</td>")
    檢查("解析經理費", 經, 1.2)
    檢查("解析保管費", 保, 0.035)
    頁 = "保管機構 彰化商業銀行&nbsp; 投資風格 配息頻率 季配 經理費(%) 1 殖利率(%) 6.59（11/11） 總管理費用(%) 1.67 (含 0.67 非管理費用) 經銷商"
    經, 保, 總 = etf_data.解析費用(頁)
    檢查("MoneyDJ 經理費", 經, 1.0)
    檢查("MoneyDJ 總費用率", 總, 1.67)
    檢查("MoneyDJ 保管及其他", 保, 0.67)
    if etf_data.解析費用("沒有費用資料")[0] is not None:
        錯誤.append("找不到費用時應回 None")
    with tempfile.TemporaryDirectory() as 暫:
        etf_data.費用檔 = Path(暫) / "fees.csv"
        pd.DataFrame({"etf": ["00981A", "00985A"], "經理費": [9.9, None], "保管費": [0.1, None],
                      "總費用率": [None, None], "來源": ["公開說明書", "待填"], "更新日": ["2026-11-01", None]}).to_csv(etf_data.費用檔, index=False)
        etf_data.更新費用(["00981A", "00985A", "00999A"], 抓=lambda c: (0.45, 0.03, 0.88) if c == "00985A" else (None, None, None))
        f = pd.read_csv(etf_data.費用檔, dtype={"etf": str}).set_index("etf")
        檢查("手動填的不動", f.at["00981A", "經理費"], 9.9)
        檢查("空白自動補", f.at["00985A", "經理費"], 0.45)
        if "00999A" not in f.index:
            錯誤.append("清單裡沒有的 ETF 要補一列")

    # 全空白的 fees.csv（更新日整欄 NaN）也要能寫入
    with tempfile.TemporaryDirectory() as 暫:
        etf_data.費用檔 = Path(暫) / "fees.csv"
        pd.DataFrame({"etf": ["0050"], "經理費": [None], "保管費": [None], "總費用率": [None],
                      "來源": ["待填"], "更新日": [None]}).to_csv(etf_data.費用檔, index=False)
        etf_data.更新費用(["0050"], 抓=lambda c: (0.15, 0.07, 0.22))
        f = pd.read_csv(etf_data.費用檔, dtype={"etf": str}).set_index("etf")
        檢查("全空白檔可寫入經理費", f.at["0050", "經理費"], 0.15)
        檢查("全空白檔可寫入總費用率", f.at["0050", "總費用率"], 0.22)

    for e in 錯誤:
        print("❌", e)
    if 錯誤:
        sys.exit(1)
    print("✅ 主動式 ETF 績效體檢計算正常")


if __name__ == "__main__":
    main()
