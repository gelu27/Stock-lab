# 自動檢查：新聞舊聞標記、事件反應表、消息先走統計、投資金額換算、損益表業外欄、重大訊息解析
#   本機執行：python tests/test_news_tools.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402
import update_data  # noqa: E402


def main():
    錯誤 = []

    def 檢查(名, 實際, 預期, 容許=0.01):
        if 預期 is None or isinstance(預期, (bool, str, list)):
            if 實際 != 預期:
                錯誤.append(f"{名}：得到 {實際}，應該是 {預期}")
        elif 實際 is None or pd.isna(實際) or abs(實際 - 預期) > 容許:
            錯誤.append(f"{名}：得到 {實際}，應該是 {預期}")

    # 舊聞：超過 30 天標舊聞；標題很像 30 天以前的新聞要標「舊聞重提」
    新聞 = pd.DataFrame({"日期": pd.to_datetime(["2026-11-02", "2026-10-20", "2026-08-11", "2026-08-12"]),
                       "標題": ["台積電與Sony合資熊本影像感測器廠 2029年量產", "法說會資本支出維持不變",
                              "台積電Sony合資熊本影像感測器廠", "完全不同的另一則消息"],
                       "來源": "x", "連結": ""})
    t = engine.新聞舊聞標記(新聞, 今天="2026-11-04")
    檢查("近期不算舊聞", bool(t["舊聞"][0]), False)
    檢查("三個月前算舊聞", bool(t["舊聞"][2]), True)
    檢查("舊聞重提", str(t["首見日"][0].date()), "2026-08-11")
    檢查("不相關的不算重提", bool(pd.isna(t["首見日"][1])), True)
    檢查("標籤", "舊聞重提" in engine.新聞日期標籤(t.iloc[0]), True)

    # 事件反應：前置日、反應日、後 N 日與超額
    日 = pd.bdate_range("2026-08-03", periods=30)
    收 = np.linspace(100, 129, 30)
    價 = pd.DataFrame({"date": 日, "code": "9999", "name": "測試", "close": 收, "change": np.r_[0, np.diff(收)]})
    指 = pd.DataFrame({"date": 日, "close": 1000.0})
    r = engine.事件反應(價, 指, ("9999",), 日[5], 日[3]).iloc[0]
    檢查("事件日漲跌", r["事件日漲跌%"], (收[5] / 收[4] - 1) * 100)
    檢查("前置日超額（大盤不動＝漲跌）", r["前置日超額%"], (收[3] / 收[2] - 1) * 100)
    檢查("後 5 日", r["後5日漲跌%"], (收[10] / 收[5] - 1) * 100)
    檢查("後 20 日", r["後20日漲跌%"], (收[25] / 收[5] - 1) * 100)
    _, 總 = engine.消息先走統計([("a", pd.DataFrame([r]))])
    檢查("利多出盡比例（一路漲＝0%）", 總["利多出盡比例%"], 0)

    # 投資金額換算：2820 億日圓 × 0.21 ＝ 592.2 億台幣
    台幣, 表 = engine.投資金額換算(2820, 0.21, {"近四季營收": 5922.0}, 59220)
    檢查("台幣", 台幣, 592.2)
    檢查("占營收", float(表.loc[表["比較對象"] == "近四季營收", "占比%"].iloc[0]), 10)
    檢查("占市值", float(表.loc[表["比較對象"] == "市值", "占比%"].iloc[0]), 1)

    # 損益表彙總：抓得到業外與稅前
    html = ("<table><tr><th>公司代號</th><th>公司名稱</th><th>營業收入</th><th>營業毛利（毛損）淨額</th><th>營業利益（損失）</th>"
            "<th>營業外收入及支出</th><th>稅前淨利（淨損）</th><th>淨利（淨損）歸屬於母公司業主</th><th>基本每股盈餘（元）</th></tr>"
            "<tr><td>2330</td><td>台積電</td><td>1,000</td><td>600</td><td>500</td><td>-20</td><td>480</td><td>400</td><td>15.5</td></tr></table>")
    p = update_data._解析損益(html).iloc[0]
    檢查("業外", p["nonop"], -20)
    檢查("稅前", p["pretax"], 480)

    # 重大訊息：全部存到月檔、關鍵字的另存 material_news.csv（用假網頁、暫存資料夾，不連網）
    import tempfile

    今 = pd.Timestamp.now()
    民國 = f"{今.year - 1911}/{今:%m/%d}"

    class 假回應:
        encoding = "utf-8"
        text = (f"<tr class='even'><td>2330</td><td>台積電</td><td>{民國}</td><td>16:01:02</td><td>公告本公司董事會決議 合資</td></tr>"
                f"<tr class='odd'><td>6723</td><td>傑智環境</td><td>{民國}</td><td>17:00:00</td><td>更換推薦證券商</td></tr>")
    原 = update_data.requests.post, update_data.資料夾
    with tempfile.TemporaryDirectory() as 夾:
        update_data.requests.post = lambda *a, **k: 假回應()
        update_data.資料夾 = Path(夾)
        try:
            update_data.抓重大訊息()
            全 = pd.read_csv(Path(夾) / "material_news" / f"{今:%Y-%m}.csv.gz", dtype={"code": str})
            關 = pd.read_csv(Path(夾) / "material_news.csv", dtype={"code": str})
            檢查("全部重訊筆數", len(全), 2)
            檢查("主旨去空白", 全.loc[全["code"] == "2330", "subject"].iloc[0], "公告本公司董事會決議合資")
            檢查("關鍵字重訊只留推薦券商", list(關["code"]), ["6723"])
        finally:
            update_data.requests.post, update_data.資料夾 = 原

    if 錯誤:
        print("❌ 有問題：\n" + "\n".join(錯誤))
        sys.exit(1)
    print("✅ 新聞事件工具檢查通過")


if __name__ == "__main__":
    main()
