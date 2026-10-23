# 自動更新資料庫：從臺灣證券交易所下載每日收盤行情，存進 data/ 資料夾
# 由 GitHub Actions 每天收盤後自動執行，也可以手動執行：
#   python update_data.py            （補到最新）
#   python update_data.py --years 3  （第一次建立資料庫，抓近 3 年）

import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

資料夾 = Path(__file__).parent / "data"
行情資料夾 = 資料夾 / "prices"
日期紀錄 = 資料夾 / "dates.txt"
指數檔 = 資料夾 / "index.csv"
台北時區 = dt.timezone(dt.timedelta(hours=8))
標頭 = {"User-Agent": "Mozilla/5.0 (personal stock dashboard)"}


def 轉數字(值):
    文字 = re.sub(r"<[^>]+>", "", str(值)).replace(",", "").strip()
    try:
        return float(文字)
    except ValueError:
        return float("nan")


def 漲跌正負(值):
    文字 = re.sub(r"<[^>]+>", "", str(值)).strip()
    if "-" in 文字:
        return -1.0
    if "+" in 文字:
        return 1.0
    if 文字 == "X":
        return float("nan")
    return 0.0


def 取得表格(回應):
    """交易所的 JSON 有新舊兩種格式，統一整理成 [(標題, 欄位, 資料)]。"""
    表格們 = []
    for 表 in 回應.get("tables", []):
        if 表.get("fields") and 表.get("data"):
            表格們.append((表.get("title", ""), 表["fields"], 表["data"]))
    for 鍵 in 回應:
        if 鍵.startswith("fields"):
            編號 = 鍵[len("fields"):]
            資料 = 回應.get("data" + 編號)
            if 資料:
                表格們.append((回應.get("subtitle" + 編號, ""), 回應[鍵], 資料))
    return 表格們


def 下載(網址):
    for 第幾次 in range(4):
        try:
            r = requests.get(網址, headers=標頭, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, json.JSONDecodeError) as 錯誤:
            print(f"  下載失敗（第 {第幾次 + 1} 次）：{錯誤}")
            time.sleep(10 * (第幾次 + 1))
    return None


def 抓一天(日期):
    """回傳 (個股 DataFrame, 加權指數 dict)；休市回傳 (None, None)。"""
    字串 = 日期.strftime("%Y%m%d")
    行情 = 下載("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
             f"?date={字串}&type=ALLBUT0999&response=json")
    if 行情 is None:
        raise RuntimeError("交易所連線失敗")
    if 行情.get("stat") != "OK":
        return None, None

    個股 = None
    指數 = None
    for 標題, 欄位, 資料 in 取得表格(行情):
        if "證券代號" in 欄位 and "收盤價" in 欄位:
            表 = pd.DataFrame(資料, columns=欄位)
            個股 = pd.DataFrame({
                "date": 日期.strftime("%Y-%m-%d"),
                "code": 表["證券代號"].str.strip(),
                "name": 表["證券名稱"].str.strip(),
                "open": 表["開盤價"].map(轉數字),
                "high": 表["最高價"].map(轉數字),
                "low": 表["最低價"].map(轉數字),
                "close": 表["收盤價"].map(轉數字),
                "change": 表["漲跌(+/-)"].map(漲跌正負) * 表["漲跌價差"].map(轉數字),
                "volume": 表["成交股數"].map(轉數字),
                "value": 表["成交金額"].map(轉數字),
            })
        if "指數" in 欄位 and "收盤指數" in 欄位:
            for 列 in 資料:
                紀錄 = dict(zip(欄位, 列))
                if 紀錄["指數"].strip() == "發行量加權股價指數":
                    指數 = {
                        "date": 日期.strftime("%Y-%m-%d"),
                        "close": 轉數字(紀錄["收盤指數"]),
                        "change": 漲跌正負(紀錄["漲跌(+/-)"]) * 轉數字(紀錄["漲跌點數"]),
                    }
    if 個股 is None:
        return None, None
    # 只留 4 位數代號（一般股票與 0050、0056 等），資料庫比較小
    個股 = 個股[個股["code"].str.fullmatch(r"\d{4}")].copy()

    time.sleep(3)  # 交易所限制下載頻率，太快會被暫時封鎖
    估值 = 下載("https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
             f"?date={字串}&selectType=ALL&response=json")
    個股["pe"] = 個股["dy"] = 個股["pb"] = float("nan")
    if 估值 and 估值.get("stat") == "OK":
        for _, 欄位, 資料 in 取得表格(估值):
            if "證券代號" not in 欄位:
                continue
            表 = pd.DataFrame(資料, columns=欄位)
            表["code"] = 表["證券代號"].str.strip()
            對照 = {"本益比": "pe", "殖利率(%)": "dy", "股價淨值比": "pb"}
            for 中文, 英文 in 對照.items():
                if 中文 in 表.columns:
                    個股[英文] = 個股["code"].map(表.set_index("code")[中文].map(轉數字))
    return 個股, 指數


def 讀日期紀錄():
    if not 日期紀錄.exists():
        return {}
    紀錄 = {}
    for 行 in 日期紀錄.read_text().split():
        日, 狀態 = 行.split(",")
        紀錄[日] = 狀態
    return 紀錄


def 寫入一天(這天):
    """每天存成一個檔案：data/prices/2026-10/20261023.csv.gz
    （GitHub 會保留每次修改的舊版本，一天一檔可以讓歷史紀錄長得最慢）"""
    日 = 這天["date"].iloc[0]
    檔案 = 行情資料夾 / 日[:7] / f"{日.replace('-', '')}.csv.gz"
    檔案.parent.mkdir(parents=True, exist_ok=True)
    這天 = 這天.drop_duplicates("code", keep="last").sort_values("code").copy()
    這天[["volume", "value"]] = 這天[["volume", "value"]].round().astype("Int64")
    這天.round(2).to_csv(檔案, index=False, compression="gzip")


def 轉換舊格式():
    """舊版是一個月一個檔，拆成一天一檔。"""
    for 檔案 in 行情資料夾.glob("*.csv.gz"):
        表 = pd.read_csv(檔案, dtype={"code": str})
        for _, 這天 in 表.groupby("date"):
            寫入一天(這天)
        檔案.unlink()
        print(f"已轉換 {檔案.name}")


def 存檔(暫存, 指數們, 紀錄):
    行情資料夾.mkdir(parents=True, exist_ok=True)
    for 這天 in 暫存:
        寫入一天(這天)
    if 指數們:
        新指數 = pd.DataFrame(指數們)
        if 指數檔.exists():
            新指數 = pd.concat([pd.read_csv(指數檔), 新指數])
        新指數.drop_duplicates("date", keep="last").sort_values("date").to_csv(指數檔, index=False)
    日期紀錄.write_text("\n".join(f"{日},{狀態}" for 日, 狀態 in sorted(紀錄.items())) + "\n")


def main():
    參數 = argparse.ArgumentParser()
    參數.add_argument("--years", type=float, default=3, help="資料庫保留幾年")
    參數.add_argument("--max-minutes", type=float, default=300, help="最多執行幾分鐘")
    參數 = 參數.parse_args()

    現在 = dt.datetime.now(台北時區)
    今天 = 現在.date()
    # 交易所大約下午 3 點後才有當天資料
    最後一天 = 今天 if 現在.hour >= 15 else 今天 - dt.timedelta(days=1)
    第一天 = 今天 - dt.timedelta(days=int(參數.years * 365))
    紀錄 = 讀日期紀錄()
    轉換舊格式()
    開始時間 = time.time()

    待抓 = []
    日 = 最後一天
    while 日 >= 第一天:  # 從最新往回抓，先有近期資料可以用
        if 日.weekday() < 5 and 日.strftime("%Y%m%d") not in 紀錄:
            待抓.append(日)
        日 -= dt.timedelta(days=1)
    print(f"需要下載 {len(待抓)} 天")

    暫存, 指數們 = [], []
    for 序號, 日 in enumerate(待抓, 1):
        if time.time() - 開始時間 > 參數.max_minutes * 60:
            print("已達執行時間上限，下次會接著抓")
            break
        try:
            個股, 指數 = 抓一天(日)
        except RuntimeError as 錯誤:
            print(f"{日} 失敗：{錯誤}，先停止")
            break
        字串 = 日.strftime("%Y%m%d")
        if 個股 is None:
            # 今天、昨天沒資料可能只是還沒公布，不要記成休市
            if (今天 - 日).days > 1:
                紀錄[字串] = "closed"
            print(f"{日} 休市")
        else:
            暫存.append(個股)
            if 指數:
                指數們.append(指數)
            紀錄[字串] = "ok"
            print(f"{日} 完成，{len(個股)} 檔（{序號}/{len(待抓)}）")
        if 序號 % 20 == 0:
            存檔(暫存, 指數們, 紀錄)
            暫存, 指數們 = [], []
        time.sleep(3)
    存檔(暫存, 指數們, 紀錄)

    # 刪掉超過保留年限的舊資料
    for 檔案 in 行情資料夾.glob("*/*.csv.gz"):
        if 檔案.name[:8] < 第一天.strftime("%Y%m%d"):
            檔案.unlink()


if __name__ == "__main__":
    main()
