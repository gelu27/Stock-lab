# 自動更新資料庫：從臺灣證券交易所（上市）與櫃買中心（上櫃、興櫃）下載資料，存進 data/ 資料夾
# 由 GitHub Actions 每天收盤後自動執行，也可以手動執行：
#   python update_data.py                              （補到最新，近 5 年內缺的都會補）
#   python update_data.py --start 2022-01-01 --end 2022-12-31   （只抓某段期間，給分段下載用）
#
# 資料夾結構
#   data/prices/2026-10/20261022.csv.gz   每日行情（上市＋上櫃，含 ETF）、本益比、殖利率、淨值比
#   data/chips/2026-10/20261022.csv.gz    每日籌碼：外資、投信、自營商買賣超，融資融券餘額
#   data/index/2026-10.csv                加權指數每日收盤
#   data/status/2026-10.txt               哪些日期已經抓過（ok / closed）
#   data/intraday/20261022.csv            加權指數當日分時（保留最近 5 天）
#   data/esb/20261022.csv.gz              興櫃行情（櫃買只提供最新一天，每天累積）
#   data/fundamental/revenue.csv, eps.csv 最新月營收、最新一季 EPS（eps.csv 每季累積保留）
#   data/fundamental/revenue_history.csv   近 5 年每月營收（公開資訊觀測站），算「營收創新高」
#   data/fundamental/capital.csv           股本、發行股數、產業，算「週轉率」
#   data/fundamental/insider.csv           每月內部人（董監經理人、大股東）持股與質押合計，逐月累積
#   data/fundamental/dividend.csv          近 6 年除權息紀錄；dividend_upcoming.csv 除權息預告
#   data/tdcc/20261022.csv.gz             集保每週股權分散（千張大戶、400 張大戶、散戶比例），每週累積
#   data/fx.csv                           美元兌台幣匯率
#   data/warning.csv                      處置股、注意股（交易所每日公告）
#   data/sbl/20261022.csv.gz              借券賣出餘額（上市＋上櫃，單位：張，保留約一年）
#   data/calendar.csv                     法說會日程（公開資訊觀測站，本月與下月）

import argparse
import datetime as dt
import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

資料夾 = Path(__file__).parent / "data"
台北時區 = dt.timezone(dt.timedelta(hours=8))
標頭 = {"User-Agent": "Mozilla/5.0 (personal stock dashboard)"}
代號格式 = r"\d{4}|00\d{2,4}[A-Z]?"  # 一般股票與 ETF，不含權證


# ---------- 共用工具 ----------
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
    for 表 in 回應.get("tables", []) or []:
        if 表.get("fields") and 表.get("data"):
            表格們.append((表.get("title", ""), [str(f).strip() for f in 表["fields"]], 表["data"]))
    for 鍵 in 回應:
        if 鍵.startswith("fields"):
            編號 = 鍵[len("fields"):]
            資料 = 回應.get("data" + 編號)
            if 資料:
                表格們.append((回應.get("subtitle" + 編號, ""), [str(f).strip() for f in 回應[鍵]], 資料))
    return 表格們


class 下載器:
    """同一個網站的下載間隔至少 3 秒，避免被暫時封鎖。"""

    def __init__(self, 間隔=3.0):
        self.間隔, self.上次 = 間隔, 0.0

    def __call__(self, 網址):
        for 第幾次 in range(4):
            等待 = self.間隔 - (time.time() - self.上次)
            if 等待 > 0:
                time.sleep(等待)
            self.上次 = time.time()
            try:
                r = requests.get(網址, headers=標頭, timeout=30)
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, json.JSONDecodeError) as 錯誤:
                print(f"  下載失敗（第 {第幾次 + 1} 次）：{網址[:80]} {錯誤}")
                time.sleep(15 * (第幾次 + 1))
        return None


證交所 = 下載器()
櫃買 = 下載器()


def 存壓縮檔(表, 檔案):
    檔案.parent.mkdir(parents=True, exist_ok=True)
    表 = 表.copy()
    for 欄 in 表.columns:
        if 欄 in ("volume", "value", "foreign", "trust", "dealer", "total", "margin", "short"):
            表[欄] = 表[欄].round().astype("Int64")
    表.round(2).to_csv(檔案, index=False, compression="gzip")


def 民國轉西元(文字):
    文字 = str(文字).strip()
    return f"{int(文字[:-4]) + 1911}-{文字[-4:-2]}-{文字[-2:]}"


# ---------- 上市（證交所） ----------
def 上市一天(日期):
    字串 = 日期.strftime("%Y%m%d")
    行情 = 證交所(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={字串}&type=ALLBUT0999&response=json")
    if 行情 is None:
        raise RuntimeError("證交所連線失敗")
    if 行情.get("stat") != "OK":
        return None, None, None
    個股, 指數 = None, None
    for _, 欄位, 資料 in 取得表格(行情):
        if "證券代號" in 欄位 and "收盤價" in 欄位:
            表 = pd.DataFrame(資料, columns=欄位)
            個股 = pd.DataFrame({
                "market": "上市",
                "code": 表["證券代號"].str.strip(), "name": 表["證券名稱"].str.strip(),
                "open": 表["開盤價"].map(轉數字), "high": 表["最高價"].map(轉數字),
                "low": 表["最低價"].map(轉數字), "close": 表["收盤價"].map(轉數字),
                "change": 表["漲跌(+/-)"].map(漲跌正負) * 表["漲跌價差"].map(轉數字),
                "volume": 表["成交股數"].map(轉數字), "value": 表["成交金額"].map(轉數字),
            })
        if "指數" in 欄位 and "收盤指數" in 欄位:
            for 列 in 資料:
                紀錄 = dict(zip(欄位, 列))
                if 紀錄["指數"].strip() == "發行量加權股價指數":
                    指數 = {"date": 日期.isoformat(), "close": 轉數字(紀錄["收盤指數"]),
                          "change": 漲跌正負(紀錄["漲跌(+/-)"]) * 轉數字(紀錄["漲跌點數"])}
    if 個股 is None:
        return None, None, None
    個股 = 個股[個股["code"].str.fullmatch(代號格式)].copy()

    估值 = 證交所(f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={字串}&selectType=ALL&response=json")
    個股 = 加估值(個股, 估值, "證券代號", {"本益比": "pe", "殖利率(%)": "dy", "股價淨值比": "pb"})

    籌碼 = []
    法人 = 證交所(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={字串}&selectType=ALLBUT0999&response=json")
    for _, 欄位, 資料 in 取得表格(法人 or {}):
        if "證券代號" in 欄位 and "投信買賣超股數" in 欄位:
            表 = pd.DataFrame(資料, columns=欄位)
            外資 = 表["外陸資買賣超股數(不含外資自營商)"].map(轉數字)
            if "外資自營商買賣超股數" in 表.columns:
                外資 = 外資 + 表["外資自營商買賣超股數"].map(轉數字).fillna(0)
            籌碼.append(pd.DataFrame({
                "code": 表["證券代號"].str.strip(), "foreign": 外資,
                "trust": 表["投信買賣超股數"].map(轉數字), "dealer": 表["自營商買賣超股數"].map(轉數字),
                "total": 表["三大法人買賣超股數"].map(轉數字),
            }))
    融資 = 證交所(f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={字串}&selectType=ALL&response=json")
    融資表 = None
    for _, 欄位, 資料 in 取得表格(融資 or {}):
        if 欄位[:2] == ["代號", "名稱"] and len(欄位) >= 13:
            # 欄位名稱重複（融資、融券都叫「今日餘額」），用位置取：第 7 欄融資餘額、第 13 欄融券餘額
            融資表 = pd.DataFrame({"code": [str(r[0]).strip() for r in 資料],
                                "margin": [轉數字(r[6]) for r in 資料],
                                "short": [轉數字(r[12]) for r in 資料]})
    return 個股, 指數, 合併籌碼(籌碼, 融資表)


def 加估值(個股, 估值, 代號欄, 對照):
    for 英文 in 對照.values():
        個股[英文] = float("nan")
    if 估值 and str(估值.get("stat", "")).upper() == "OK":
        for _, 欄位, 資料 in 取得表格(估值):
            if 代號欄 not in 欄位:
                continue
            表 = pd.DataFrame(資料, columns=欄位)
            表["code"] = 表[代號欄].astype(str).str.strip()
            表 = 表.drop_duplicates("code").set_index("code")
            for 中文, 英文 in 對照.items():
                if 中文 in 表.columns:
                    個股[英文] = 個股["code"].map(表[中文].map(轉數字))
    return 個股


def 合併籌碼(籌碼們, 融資表):
    if not 籌碼們 and 融資表 is None:
        return None
    表 = pd.concat(籌碼們) if 籌碼們 else pd.DataFrame(columns=["code"])
    if 融資表 is not None:
        表 = 表.merge(融資表, on="code", how="outer")
    return 表[表["code"].str.fullmatch(代號格式)]


# ---------- 上櫃（櫃買中心） ----------
def 上櫃一天(日期):
    斜線 = 日期.strftime("%Y/%m/%d")
    行情 = 櫃買(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={斜線}&type=EW&id=&response=json")
    if 行情 is None:
        raise RuntimeError("櫃買中心連線失敗")
    if str(行情.get("stat", "")).lower() != "ok" or str(行情.get("date")) != 日期.strftime("%Y%m%d"):
        return None, None
    個股 = None
    for _, 欄位, 資料 in 取得表格(行情):
        if "代號" in 欄位 and "收盤" in 欄位:
            表 = pd.DataFrame(資料, columns=欄位)
            個股 = pd.DataFrame({
                "market": "上櫃",
                "code": 表["代號"].str.strip(), "name": 表["名稱"].str.strip(),
                "open": 表["開盤"].map(轉數字), "high": 表["最高"].map(轉數字),
                "low": 表["最低"].map(轉數字), "close": 表["收盤"].map(轉數字),
                "change": 表["漲跌"].map(轉數字),
                "volume": 表["成交股數"].map(轉數字), "value": 表["成交金額(元)"].map(轉數字),
            })
            break
    if 個股 is None or 個股.empty:
        return None, None
    個股 = 個股[個股["code"].str.fullmatch(代號格式)].copy()

    估值 = 櫃買(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date={斜線}&id=&response=json")
    個股 = 加估值(個股, 估值, "股票代號", {"本益比": "pe", "殖利率(%)": "dy", "股價淨值比": "pb"})

    籌碼 = []
    法人 = 櫃買(f"https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date={斜線}&id=&response=json")
    for _, 欄位, 資料 in 取得表格(法人 or {}):
        if 欄位[:1] == ["代號"] and len(欄位) >= 24:
            # 欄位名稱重複，用位置取：外資合計、投信、自營商合計、三大法人合計
            籌碼.append(pd.DataFrame({
                "code": [str(r[0]).strip() for r in 資料],
                "foreign": [轉數字(r[10]) for r in 資料], "trust": [轉數字(r[13]) for r in 資料],
                "dealer": [轉數字(r[22]) for r in 資料], "total": [轉數字(r[23]) for r in 資料],
            }))
    融資 = 櫃買(f"https://www.tpex.org.tw/www/zh-tw/margin/balance?date={斜線}&id=&response=json")
    融資表 = None
    for _, 欄位, 資料 in 取得表格(融資 or {}):
        if "資餘額" in 欄位 and "券餘額" in 欄位:
            表 = pd.DataFrame(資料, columns=欄位)
            融資表 = pd.DataFrame({"code": 表["代號"].str.strip(), "margin": 表["資餘額"].map(轉數字),
                                "short": 表["券餘額"].map(轉數字)})
    return 個股, 合併籌碼(籌碼, 融資表)


# ---------- 紀錄 ----------
def 讀狀態():
    紀錄 = {}
    for 檔案 in (資料夾 / "status").glob("*.txt"):
        for 行 in 檔案.read_text().split():
            日, 狀態 = 行.split(",")
            紀錄[日] = 狀態
    return 紀錄


def 寫狀態(日期, 狀態):
    檔案 = 資料夾 / "status" / f"{日期:%Y-%m}.txt"
    檔案.parent.mkdir(parents=True, exist_ok=True)
    舊 = dict(行.split(",") for 行 in 檔案.read_text().split()) if 檔案.exists() else {}
    舊[日期.strftime("%Y%m%d")] = 狀態
    檔案.write_text("\n".join(f"{k},{v}" for k, v in sorted(舊.items())) + "\n")


def 寫指數(指數):
    檔案 = 資料夾 / "index" / f"{指數['date'][:7]}.csv"
    檔案.parent.mkdir(parents=True, exist_ok=True)
    表 = pd.DataFrame([指數])
    if 檔案.exists():
        表 = pd.concat([pd.read_csv(檔案), 表])
    表.drop_duplicates("date", keep="last").sort_values("date").to_csv(檔案, index=False)


def 抓一天(日期):
    with ThreadPoolExecutor(2) as 池:  # 證交所與櫃買是不同網站，可以同時抓
        上市工作 = 池.submit(上市一天, 日期)
        上櫃工作 = 池.submit(上櫃一天, 日期)
        上市, 指數, 上市籌碼 = 上市工作.result()
        上櫃, 上櫃籌碼 = 上櫃工作.result()
    if 上市 is None:
        return False
    月 = f"{日期:%Y-%m}"
    名 = f"{日期:%Y%m%d}.csv.gz"
    行情 = pd.concat([上市, 上櫃]) if 上櫃 is not None else 上市
    存壓縮檔(行情.drop_duplicates("code").sort_values("code"), 資料夾 / "prices" / 月 / 名)
    籌碼 = [t for t in (上市籌碼, 上櫃籌碼) if t is not None]
    if 籌碼:
        存壓縮檔(pd.concat(籌碼).drop_duplicates("code").sort_values("code"), 資料夾 / "chips" / 月 / 名)
    if 指數:
        寫指數(指數)
    return True


# ---------- 只有最新一天的資料 ----------
def 抓分時():
    """加權指數當日走勢（證交所每 5 秒一筆，存成每分鐘一筆），保留最近 5 個交易日。"""
    今天 = dt.datetime.now(台北時區).date()
    資料夾.joinpath("intraday").mkdir(parents=True, exist_ok=True)
    已有 = {f.stem for f in (資料夾 / "intraday").glob("*.csv")}
    日 = 今天
    for _ in range(10):
        字串 = 日.strftime("%Y%m%d")
        if 日.weekday() < 5 and 字串 not in 已有:
            資料 = 證交所(f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_INDEX?date={字串}&response=json")
            if 資料 and 資料.get("stat") == "OK" and 資料.get("data"):
                表 = pd.DataFrame([[r[0], 轉數字(r[1])] for r in 資料["data"]], columns=["time", "taiex"])
                表 = 表[表["time"].str.endswith(":00")]
                表.to_csv(資料夾 / "intraday" / f"{字串}.csv", index=False)
                print(f"分時 {字串} 完成，{len(表)} 筆")
        日 -= dt.timedelta(days=1)
    for 檔案 in sorted((資料夾 / "intraday").glob("*.csv"))[:-5]:
        檔案.unlink()


def 抓興櫃():
    資料 = 櫃買("https://www.tpex.org.tw/openapi/v1/tpex_esb_latest_statistics")
    if not 資料:
        return
    表 = pd.DataFrame(資料)
    興櫃 = pd.DataFrame({
        "date": 表["Date"].map(民國轉西元), "market": "興櫃",
        "code": 表["SecuritiesCompanyCode"].str.strip(), "name": 表["CompanyName"].str.strip(),
        "high": 表["Highest"].map(轉數字), "low": 表["Lowest"].map(轉數字),
        "close": 表["LatestPrice"].map(轉數字), "average": 表["Average"].map(轉數字),
        "prev_average": 表["PreviousAveragePrice"].map(轉數字),
        "volume": 表["TransactionVolume"].map(轉數字),
    })
    # 興櫃沒有漲跌幅限制，漲跌以「最後成交價 − 前一日均價」計算
    興櫃["change"] = 興櫃["close"] - 興櫃["prev_average"]
    for 日, 這天 in 興櫃.groupby("date"):
        存壓縮檔(這天, 資料夾 / "esb" / f"{日.replace('-', '')}.csv.gz")
        print(f"興櫃 {日} 完成，{len(這天)} 檔")


def 抓基本面():
    資料夾.joinpath("fundamental").mkdir(parents=True, exist_ok=True)
    營收們 = []
    for 網址, 市場 in (("https://openapi.twse.com.tw/v1/opendata/t187ap05_L", "上市"),
                     ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O", "上櫃")):
        資料 = (證交所 if 市場 == "上市" else 櫃買)(網址)
        if not 資料:
            continue
        表 = pd.DataFrame(資料)
        營收們.append(pd.DataFrame({
            "code": 表["公司代號"].str.strip(), "month": 表["資料年月"].map(lambda s: f"{int(s[:-2]) + 1911}-{s[-2:]}"),
            "revenue": 表["營業收入-當月營收"].map(轉數字),
            "rev_yoy": 表["營業收入-去年同月增減(%)"].map(轉數字),
            "rev_mom": 表["營業收入-上月比較增減(%)"].map(轉數字),
            "rev_cum_yoy": 表["累計營業收入-前期比較增減(%)"].map(轉數字),
        }))
    if 營收們:
        pd.concat(營收們).round(2).to_csv(資料夾 / "fundamental" / "revenue.csv", index=False)
        print("月營收完成")
    EPS們 = []
    for 網址, 市場 in (("https://openapi.twse.com.tw/v1/opendata/t187ap14_L", "上市"),
                     ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap14_O", "上櫃")):
        資料 = (證交所 if 市場 == "上市" else 櫃買)(網址)
        if not 資料:
            continue
        表 = pd.DataFrame(資料)
        代號 = 表.get("公司代號", 表.get("SecuritiesCompanyCode"))
        年度 = 表.get("年度", 表.get("Year"))
        EPS = 表.get("基本每股盈餘(元)", 表.get("基本每股盈餘"))
        EPS們.append(pd.DataFrame({
            "code": 代號.str.strip(), "quarter": (年度.astype(int) + 1911).astype(str) + "Q" + 表["季別"].astype(str),
            "eps": EPS.map(轉數字),
        }))
    if EPS們:
        檔案 = 資料夾 / "fundamental" / "eps.csv"
        表 = pd.concat(EPS們)
        if 檔案.exists():  # 保留以前各季，才能算「近三季 EPS 合計」
            表 = pd.concat([pd.read_csv(檔案, dtype={"code": str}), 表])
        表.drop_duplicates(["code", "quarter"], keep="last").sort_values(["code", "quarter"]).to_csv(檔案, index=False)
        print("EPS 完成")
    抓股本()
    抓內部人()
    抓歷史營收()
    抓損益表()
    抓除權息()
    抓集保()


def 抓處置注意():
    """處置股（還在處置期間的）與今天的注意股 → data/warning.csv。"""
    今天 = dt.datetime.now(台北時區).date()
    列們 = []

    def 迄日(文字):
        日們 = re.findall(r"(\d{2,3})/?(\d{2})/?(\d{2})", str(文字).replace("～", "~"))
        return dt.date(int(日們[-1][0]) + 1911, int(日們[-1][1]), int(日們[-1][2])) if 日們 else None

    for r in 證交所("https://openapi.twse.com.tw/v1/announcement/punish") or []:
        if r.get("Code"):
            列們.append({"code": r["Code"].strip(), "type": "處置", "market": "上市", "date": 民國轉西元(r["Date"]),
                       "end": 迄日(r.get("DispositionPeriod")), "reason": f"{r.get('DispositionMeasures', '')}（{r.get('ReasonsOfDisposition', '')}）"})
    for r in 櫃買("https://www.tpex.org.tw/openapi/v1/tpex_disposal_information") or []:
        if r.get("SecuritiesCompanyCode"):
            列們.append({"code": r["SecuritiesCompanyCode"].strip(), "type": "處置", "market": "上櫃",
                       "date": 民國轉西元(r["Date"]), "end": 迄日(r.get("DispositionPeriod")),
                       "reason": r.get("DispositionReasons", "")})
    for r in 證交所("https://openapi.twse.com.tw/v1/announcement/notice") or []:
        if r.get("Code"):
            列們.append({"code": r["Code"].strip(), "type": "注意", "market": "上市", "date": 民國轉西元(r["Date"]),
                       "end": None, "reason": r.get("TradingInfoForAttention", "")})
    for r in 櫃買("https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_information") or []:
        if r.get("SecuritiesCompanyCode"):
            列們.append({"code": r["SecuritiesCompanyCode"].strip(), "type": "注意", "market": "上櫃",
                       "date": 民國轉西元(r["Date"]), "end": None, "reason": r.get("TradingInformation", "")})
    表 = pd.DataFrame(列們, columns=["code", "type", "market", "date", "end", "reason"])
    表["end"] = pd.to_datetime(表["end"])
    表 = 表[表["code"].astype(str).str.fullmatch(代號格式) & (表["end"].isna() | (表["end"] >= pd.Timestamp(今天)))]
    表["reason"] = 表["reason"].astype(str).str.replace(r"\s+", " ", regex=True).str.slice(0, 120)
    表.to_csv(資料夾 / "warning.csv", index=False)
    print(f"處置／注意股完成：處置 {(表['type'] == '處置').sum()} 檔、注意 {(表['type'] == '注意').sum()} 檔")


def 抓借券(天數=60):
    """借券賣出餘額（信用額度總量管制餘額表的右半部）→ data/sbl/YYYYMMDD.csv.gz，缺的日子往回補到近 天數 個交易日。"""
    資料 = 資料夾 / "sbl"
    資料.mkdir(exist_ok=True)
    日們 = sorted({f.name[:8] for f in (資料夾 / "prices").glob("*/*.csv.gz")})[-天數:]
    for 日 in reversed(日們):
        if (資料 / f"{日}.csv.gz").exists():
            continue
        表們 = []
        for 網址, 下載 in ((f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={日}&response=json", 證交所),
                         (f"https://www.tpex.org.tw/www/zh-tw/margin/sbl?date={日[:4]}%2F{日[4:6]}%2F{日[6:]}&response=json", 櫃買)):
            回應 = 下載(網址)
            for _, 欄, 列 in 取得表格(回應 or {}):
                if len(欄) >= 14:
                    t = pd.DataFrame([x[:15] for x in 列])
                    表們.append(pd.DataFrame({"code": t[0].astype(str).str.strip(),
                                            "sbl_sell": t[9].map(轉數字) / 1000, "sbl_return": t[10].map(轉數字) / 1000,
                                            "sbl_balance": t[12].map(轉數字) / 1000, "sbl_limit": t[13].map(轉數字) / 1000}))
                    break
        if not 表們:
            print(f"借券 {日} 沒有資料")
            continue
        表 = pd.concat(表們)
        表 = 表[表["code"].str.fullmatch(代號格式)].round(1)
        存壓縮檔(表, 資料 / f"{日}.csv.gz")
        print(f"借券 {日} 完成（{len(表)} 檔）")
    for f in sorted(資料.glob("*.csv.gz"))[:-260]:  # 保留約一年
        f.unlink()


def 抓法說會():
    """公開資訊觀測站「法人說明會一覽表」本月與下月 → data/calendar.csv。"""
    今天 = dt.datetime.now(台北時區).date()
    月們 = [(今天.year, 今天.month), (今天.year + 今天.month // 12, 今天.month % 12 + 1)]
    列們 = []
    for 年, 月 in 月們:
        for 類 in ("sii", "otc"):
            try:
                r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1", headers=標頭, timeout=30,
                                  data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": 類,
                                        "year": str(年 - 1911), "month": f"{月:02d}", "co_id": ""})
            except requests.RequestException as 錯誤:
                print(f"法說會 {年}-{月} {類} 失敗：{錯誤}")
                continue
            for 列 in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S | re.I):
                格 = [re.sub(r"<[^>]+>|&nbsp;|\s+", " ", c).strip()
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", 列, re.S | re.I)]
                if len(格) >= 6 and re.fullmatch(r"\d{4}", 格[0]) and re.fullmatch(r"\d{2,3}/\d{2}/\d{2}", 格[2]):
                    列們.append({"code": 格[0], "name": 格[1], "date": 民國轉西元(格[2].replace("/", "")),
                               "time": 格[3], "place": 格[4][:60], "summary": 格[5][:120]})
            time.sleep(3)
    if 列們:
        表 = pd.DataFrame(列們).drop_duplicates(["code", "date", "time"]).sort_values(["date", "time", "code"])
        表.to_csv(資料夾 / "calendar.csv", index=False)
        print(f"法說會完成，共 {len(表)} 場")


def _民國日期(文字):
    """「114年01月02日」「114/01/02」「1140102」都轉成 2025-01-02，看不懂就回傳 None。"""
    數字 = re.sub(r"\D", "", str(文字))
    return 民國轉西元(數字) if len(數字) in (6, 7) else None


def 抓除權息(年數=6):
    """除權息歷史（交易所 TWT49U、櫃買 exDailyQ，一年抓一次）→ dividend.csv；
    之後的除權息預告 → dividend_upcoming.csv。今年和去年每次重抓，更早的已經有就不重抓。"""
    檔案 = 資料夾 / "fundamental" / "dividend.csv"
    舊 = pd.read_csv(檔案, dtype={"code": str}) if 檔案.exists() else pd.DataFrame()
    已有年 = set(舊["date"].str[:4]) if len(舊) else set()
    今年 = dt.date.today().year
    新們 = []
    for 年 in range(今年 - 年數 + 1, 今年 + 1):
        if str(年) in 已有年 and 年 < 今年 - 1:
            continue
        上市 = 證交所(f"https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={年}0101&endDate={年}1231&response=json")
        for 標題, 欄, 資料 in 取得表格(上市 or {}):
            t = pd.DataFrame(資料, columns=欄)
            新們.append(pd.DataFrame({
                "code": t["股票代號"].str.strip(), "date": t["資料日期"].map(_民國日期),
                "type": t["權/息"].str.strip(), "value": t["權值+息值"].map(轉數字), "cash": float("nan"),
                "pre_close": t["除權息前收盤價"].map(轉數字), "ref": t["除權息參考價"].map(轉數字)}))
        try:
            time.sleep(3)
            r = requests.post("https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ", headers=標頭, timeout=30,
                              data={"startDate": f"{年}/01/01", "endDate": f"{年}/12/31", "response": "json"})
            for 標題, 欄, 資料 in 取得表格(r.json()):
                t = pd.DataFrame(資料, columns=欄)
                新們.append(pd.DataFrame({
                    "code": t["代號"].str.strip(), "date": t["除權息日期"].map(_民國日期),
                    "type": t["權/息"].str.replace("除", "").str.strip(), "value": t["權值+息值"].map(轉數字),
                    "cash": t["現金股利"].map(轉數字),
                    "pre_close": t["除權息前收盤價"].map(轉數字), "ref": t["除權息參考價"].map(轉數字)}))
        except Exception as 錯誤:
            print(f"  櫃買除權息 {年} 失敗：{錯誤}")
    if 新們:
        新 = pd.concat(新們)
        新 = 新[新["code"].str.fullmatch(代號格式) & 新["date"].notna()]
        新["date"] = pd.to_datetime(新["date"]).dt.strftime("%Y-%m-%d")
        表 = pd.concat([舊, 新]).drop_duplicates(["code", "date"], keep="last").sort_values(["code", "date"])
        表.round(4).to_csv(檔案, index=False)
        print(f"除權息歷史完成，共 {len(表)} 筆")
    預告 = []
    for 列 in 證交所("https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL") or []:
        預告.append({"code": 列.get("Code", "").strip(), "date": _民國日期(列.get("Date", "")),
                   "type": 列.get("Exdividend", "").strip(), "cash": 轉數字(列.get("CashDividend")),
                   "stock_ratio": 轉數字(列.get("StockDividendRatio"))})
    for 列 in 櫃買("https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost") or []:
        預告.append({"code": 列.get("SecuritiesCompanyCode", "").strip(),
                   "date": _民國日期(列.get("ExRrightsExDividendDate", "")),
                   "type": 列.get("ExRrightsExDividend", "").replace("除", "").strip(),
                   "cash": 轉數字(列.get("CashDividend")), "stock_ratio": 轉數字(列.get("StockDividendRatio"))})
    if 預告:
        表 = pd.DataFrame(預告).dropna(subset=["date"])
        表["date"] = pd.to_datetime(表["date"]).dt.strftime("%Y-%m-%d")
        表.to_csv(資料夾 / "fundamental" / "dividend_upcoming.csv", index=False)
        print(f"除權息預告完成，共 {len(表)} 筆")


def 抓集保():
    """集保結算所每週股權分散表（只有最新一週，每週累積一份）→ data/tdcc/YYYYMMDD.csv.gz。
    分級 1~15：1 張以下 … 15 為 1000 張以上；17 為合計。"""
    r = requests.get("https://opendata.tdcc.com.tw/getOD.ashx?id=1-5", headers=標頭, timeout=60)
    r.raise_for_status()
    t = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")), dtype={"證券代號": str})
    t.columns = ["date", "code", "level", "people", "shares", "pct"]
    t["code"] = t["code"].str.strip()
    t = t[t["code"].str.fullmatch(代號格式)]
    日期 = str(t["date"].iloc[0])
    樞 = t.pivot_table(index="code", columns="level", values="pct", aggfunc="sum").fillna(0)
    人 = t.pivot_table(index="code", columns="level", values="people", aggfunc="sum").fillna(0)
    結果 = pd.DataFrame({
        "big1000": 樞.get(15, 0),
        "big400": 樞[[c for c in (12, 13, 14, 15) if c in 樞]].sum(axis=1),
        "retail": 樞[[c for c in range(1, 9) if c in 樞]].sum(axis=1),   # 50 張以下
        "holders": 人.get(17, 0),
        "big1000_people": 人.get(15, 0),
    }).round(2).reset_index()
    (資料夾 / "tdcc").mkdir(exist_ok=True)
    存壓縮檔(結果, 資料夾 / "tdcc" / f"{日期}.csv.gz")
    print(f"集保股權分散完成（{日期}，{len(結果)} 檔）")


def 抓內部人():
    列們 = []
    for 網址, 市場 in (("https://openapi.twse.com.tw/v1/opendata/t187ap11_L", "上市"),
                     ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O", "上櫃")):
        資料 = (證交所 if 市場 == "上市" else 櫃買)(網址)
        if 資料:
            列們.append(pd.DataFrame(資料))
    if not 列們:
        return
    表 = pd.concat(列們)
    表 = pd.DataFrame({
        "code": 表["公司代號"].str.strip(),
        "month": 表["資料年月"].map(lambda s: f"{int(s[:-2]) + 1911}-{s[-2:]}"),
        "董監": 表["職稱"].str.contains("董事|監察人"),
        "持股": 表["目前持股"].map(轉數字), "設質": 表["設質股數"].map(轉數字),
    })
    合計 = 表.groupby(["code", "month"]).agg(insider=("持股", "sum"), pledged=("設質", "sum"))
    合計["directors"] = 表[表["董監"]].groupby(["code", "month"])["持股"].sum()
    合計 = 合計.fillna(0).reset_index()
    檔案 = 資料夾 / "fundamental" / "insider.csv"
    if 檔案.exists():
        合計 = pd.concat([pd.read_csv(檔案, dtype={"code": str}), 合計])
    合計.drop_duplicates(["code", "month"], keep="last").sort_values(["code", "month"]).to_csv(檔案, index=False)
    print("內部人持股完成")


產業別名稱 = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維", "05": "電機機械", "06": "電器電纜",
    "08": "玻璃陶瓷", "09": "造紙工業", "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業", "14": "建材營造",
    "15": "航運業", "16": "觀光餐旅", "17": "金融保險", "18": "貿易百貨", "19": "綜合", "20": "其他",
    "21": "化學工業", "22": "生技醫療", "23": "油電燃氣", "24": "半導體", "25": "電腦及週邊設備",
    "26": "光電", "27": "通信網路", "28": "電子零組件", "29": "電子通路", "30": "資訊服務",
    "31": "其他電子", "32": "文化創意", "33": "農業科技", "34": "電子商務", "35": "綠能環保",
    "36": "數位雲端", "37": "運動休閒", "38": "居家生活", "80": "管理股票", "91": "存託憑證",
}


def 抓股本():
    列們 = []
    for 網址, 市場 in (("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "上市"),
                     ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "上櫃")):
        資料 = (證交所 if 市場 == "上市" else 櫃買)(網址)
        for 列 in 資料 or []:
            代號 = 列.get("公司代號", 列.get("SecuritiesCompanyCode", "")).strip()
            股本 = 轉數字(列.get("實收資本額", 列.get("Paidin.Capital.NTDollars")))
            面額 = 轉數字(re.sub(r"[^\d.]", "", str(列.get("普通股每股面額", 列.get("ParValueOfCommonStock", "")))))
            if not 面額 or 面額 != 面額:
                面額 = 10.0
            產業 = str(列.get("產業別", 列.get("SecuritiesIndustryCode", ""))).strip()
            列們.append({"code": 代號, "capital": 股本, "shares": 股本 / 面額, "industry": 產業別名稱.get(產業, 產業)})
    if 列們:
        pd.DataFrame(列們).round(0).to_csv(資料夾 / "fundamental" / "capital.csv", index=False)
        print("股本完成")


def 抓歷史營收(月數=60):
    """公開資訊觀測站每月營收彙總 CSV；已經有的月份不重抓（最近 2 個月會重抓，因為有公司晚公布）。"""
    檔案 = 資料夾 / "fundamental" / "revenue_history.csv"
    舊 = pd.read_csv(檔案, dtype={"code": str}) if 檔案.exists() else pd.DataFrame(columns=["code", "month", "revenue"])
    已有 = set(舊["month"])
    今天 = dt.date.today()
    年, 月 = 今天.year, 今天.month
    新們 = []
    for i in range(月數):
        月 -= 1
        if 月 == 0:
            年, 月 = 年 - 1, 12
        月份 = f"{年}-{月:02d}"
        if 月份 in 已有 and i >= 2:
            continue
        for 類 in ("sii", "otc"):
            time.sleep(3)
            try:
                r = requests.get(f"https://mopsov.twse.com.tw/nas/t21/{類}/t21sc03_{年 - 1911}_{月}.csv",
                                 headers=標頭, timeout=30)
                if r.status_code != 200 or "公司代號" not in r.content[:600].decode("utf-8-sig", "ignore"):
                    continue
                表 = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")), dtype=str)
                新們.append(pd.DataFrame({"code": 表["公司代號"].str.strip(), "month": 月份,
                                         "revenue": 表["營業收入-當月營收"].map(轉數字)}))
            except Exception as 錯誤:
                print(f"  歷史營收 {月份} {類} 失敗：{錯誤}")
    if 新們:
        表 = pd.concat([舊] + 新們).dropna(subset=["revenue"])
        表 = 表.drop_duplicates(["code", "month"], keep="last").sort_values(["code", "month"])
        表.to_csv(檔案, index=False)
        print(f"歷史營收完成，共 {表['month'].nunique()} 個月")


def _解析損益(html):
    """公開資訊觀測站「綜合損益表彙總」HTML → 代號、營收、毛利、營業利益（今年累計，千元）。"""
    import re
    去標籤 = lambda t: re.sub(r"<[^>]+>|&nbsp;|\s", "", t)
    列們 = []
    for 表 in re.findall(r"<table[^>]*>(.*?)</table>", html, re.S):
        標題 = [去標籤(t) for t in re.findall(r"<th[^>]*>(.*?)</th>", 表, re.S)]
        if "公司代號" not in 標題 or "基本每股盈餘（元）" not in 標題:
            continue
        # 金融業的表沒有營收、毛利，但有 EPS 和歸屬母公司淨利（ROE 會用到）
        淨利欄 = next((k for k in 標題 if k.startswith("淨利") and "母公司業主" in k), None)
        位 = {k: 標題.index(k) for k in ("公司代號", "營業收入", "營業毛利（毛損）淨額", "營業利益（損失）",
                                        "基本每股盈餘（元）") if k in 標題}
        if 淨利欄:
            位["淨利"] = 標題.index(淨利欄)
        for 列 in re.findall(r"<tr[^>]*>(.*?)</tr>", 表, re.S):
            格 = [去標籤(t) for t in re.findall(r"<td[^>]*>(.*?)</td>", 列, re.S)]
            if len(格) != len(標題):
                continue
            取 = lambda k: 轉數字(格[位[k]]) if k in 位 else None
            列們.append({"code": 格[位["公司代號"]], "revenue": 取("營業收入"),
                        "gross": 取("營業毛利（毛損）淨額"), "opinc": 取("營業利益（損失）"),
                        "netinc": 取("淨利"), "eps": 取("基本每股盈餘（元）")})
    return pd.DataFrame(列們)


def 抓損益表(季數=12):
    """各季綜合損益表（今年累計數），用來算毛利率；已經有的季度不重抓（最近 2 季會重抓）。"""
    檔案 = 資料夾 / "fundamental" / "income.csv"
    舊 = pd.read_csv(檔案, dtype={"code": str}) if 檔案.exists() else pd.DataFrame(
        columns=["code", "quarter", "revenue", "gross", "opinc", "netinc", "eps"])
    已有 = set(舊["quarter"]) if "eps" in 舊.columns else set()  # 舊檔沒有 EPS 欄位就全部重抓
    今天 = dt.date.today()
    年, 季 = 今天.year, (今天.month - 1) // 3 + 1
    新們 = []
    for i in range(季數):
        季 -= 1
        if 季 == 0:
            年, 季 = 年 - 1, 4
        季度 = f"{年}Q{季}"
        if 季度 in 已有 and i >= 2:
            continue
        for 類 in ("sii", "otc"):
            time.sleep(3)
            try:
                r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t163sb04", headers=標頭, timeout=60,
                                  data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y",
                                        "TYPEK": 類, "year": str(年 - 1911), "season": f"{季:02d}"})
                表 = _解析損益(r.text)
                if len(表):
                    表["quarter"] = 季度
                    新們.append(表)
                    print(f"  損益表 {季度} {類}：{len(表)} 家")
            except Exception as 錯誤:
                print(f"  損益表 {季度} {類} 失敗：{錯誤}")
    if 新們:
        表 = pd.concat([舊] + 新們).dropna(subset=["revenue", "eps"], how="all")
        表 = 表.drop_duplicates(["code", "quarter"], keep="last").sort_values(["code", "quarter"])
        表.to_csv(檔案, index=False)
        print(f"損益表完成，共 {表['quarter'].nunique()} 季")


def 抓匯率():
    """美元兌台幣每日收盤匯率（數字變小代表台幣升值）。"""
    新資料 = []
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/TWD=X?range=3mo&interval=1d",
                         headers=標頭, timeout=30)
        結果 = r.json()["chart"]["result"][0]
        for 時間, 收盤 in zip(結果["timestamp"], 結果["indicators"]["quote"][0]["close"]):
            if 收盤:
                日 = dt.datetime.fromtimestamp(時間, 台北時區).strftime("%Y-%m-%d")
                新資料.append({"date": 日, "usdtwd": round(收盤, 4)})
    except Exception as 錯誤:
        print(f"Yahoo 匯率失敗（{錯誤}），改用臺灣銀行")
    if not 新資料:
        r = requests.get("https://rate.bot.com.tw/xrt/flcsv/0/L3M/USD", headers=標頭, timeout=30)
        r.encoding = "utf-8-sig"
        for 行 in r.text.splitlines()[1:]:
            欄 = 行.split(",")
            try:
                新資料.append({"date": f"{欄[0][:4]}-{欄[0][4:6]}-{欄[0][6:8]}",
                            "usdtwd": round((float(欄[4]) + float(欄[14])) / 2, 4)})
            except (ValueError, IndexError):
                continue
    if not 新資料:
        print("匯率下載失敗，略過")
        return
    檔案 = 資料夾 / "fx.csv"
    表 = pd.DataFrame(新資料)
    if 檔案.exists():
        表 = pd.concat([pd.read_csv(檔案), 表])
    表.drop_duplicates("date", keep="last").sort_values("date").to_csv(檔案, index=False)
    print("匯率完成")


# ---------- 主程式 ----------
def main():
    參數 = argparse.ArgumentParser()
    參數.add_argument("--years", type=float, default=5, help="資料庫保留幾年")
    參數.add_argument("--start", help="只抓這天之後（YYYY-MM-DD）")
    參數.add_argument("--end", help="只抓這天之前（YYYY-MM-DD）")
    參數.add_argument("--max-minutes", type=float, default=320, help="最多執行幾分鐘")
    參數.add_argument("--skip-latest", action="store_true", help="不抓只有最新一天的資料（分段下載用）")
    參數 = 參數.parse_args()

    現在 = dt.datetime.now(台北時區)
    今天 = 現在.date()
    最後一天 = 今天 if 現在.hour >= 15 else 今天 - dt.timedelta(days=1)
    第一天 = 今天 - dt.timedelta(days=int(參數.years * 365))
    if 參數.start:
        第一天 = max(第一天, dt.date.fromisoformat(參數.start))
    if 參數.end:
        最後一天 = min(最後一天, dt.date.fromisoformat(參數.end))

    紀錄 = 讀狀態()
    待抓 = []
    日 = 最後一天
    while 日 >= 第一天:  # 從最新往回抓，先有近期資料可以用
        if 日.weekday() < 5 and 日.strftime("%Y%m%d") not in 紀錄:
            待抓.append(日)
        日 -= dt.timedelta(days=1)
    print(f"需要下載 {len(待抓)} 天（{第一天} ~ {最後一天}）")

    開始時間 = time.time()
    for 序號, 日 in enumerate(待抓, 1):
        if time.time() - 開始時間 > 參數.max_minutes * 60:
            print("已達執行時間上限，下次會接著抓")
            break
        try:
            有資料 = 抓一天(日)
        except RuntimeError as 錯誤:
            print(f"{日} 失敗：{錯誤}，先停止")
            break
        if 有資料:
            寫狀態(日, "ok")
            print(f"{日} 完成（{序號}/{len(待抓)}）")
        else:
            if (今天 - 日).days > 1:  # 今天、昨天沒資料可能只是還沒公布
                寫狀態(日, "closed")
            print(f"{日} 休市")

    if not 參數.skip_latest:
        for 工作 in (抓分時, 抓興櫃, 抓基本面, 抓匯率, 抓處置注意, 抓借券, 抓法說會):  # 這些出問題不影響主資料庫
            try:
                工作()
            except Exception as 錯誤:
                print(f"{工作.__name__} 失敗：{錯誤}")

    # 刪掉超過保留年限的舊資料
    for 子 in ("prices", "chips"):
        for 檔案 in (資料夾 / 子).glob("*/*.csv.gz"):
            if 檔案.name[:8] < 第一天.strftime("%Y%m%d") and not 參數.start:
                檔案.unlink()


if __name__ == "__main__":
    main()
