# 主動式 ETF 每日持股追蹤：抓各投信公布的每日持股（申購買回清單 PCF），比對每天的加碼、減碼、新增、出清
# 由 GitHub Actions（etf.yml）每天收盤後執行，也可以手動執行：
#   python etf_data.py               （抓最新一天，並補最近 7 天缺的）
#   python etf_data.py --days 90     （有歷史查詢的投信，回補近 90 天）
#
# 資料來源（都是公開、免費的），同一天同一檔依序取第一個抓得到的：
#   1. 投信官網：野村、統一、群益、復華、第一金可以查歷史日期；富邦、凱基、摩根、台新、永豐、聯博只有最新一天
#   2. 公開彙整 nctuwanglin.github.io/active-etf（逐家抓投信官網 PCF 後整理），只有最新一天
#   3. 第二彙整 github.com/janeytu/tw-etf-pages 的每日快照（第一個彙整停掉、或國泰、兆豐這種擋 GitHub 的才用）
#
# 資料夾結構
#   data/etf/holdings/2026-10/20261022.csv.gz   當天各主動式 ETF 的持股（etf, code, name, shares, weight, source）
#   data/etf/info.csv                           每天的基金規模、淨值、在外流通單位數

import argparse
import datetime as dt
import io
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

資料夾 = Path(__file__).parent / "data" / "etf"
持股資料夾 = 資料夾 / "holdings"
資訊檔 = 資料夾 / "info.csv"
價格資料夾 = Path(__file__).parent / "data" / "prices"
台北時區 = dt.timezone(dt.timedelta(hours=8))
標頭 = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
       "Accept-Language": "zh-TW,zh;q=0.9"}
彙整網址 = "https://nctuwanglin.github.io/active-etf/active.json"

# 官網有歷史查詢的 ETF：代號 → (投信, 官網基金代碼)
官網 = {
    "00980A": ("野村", "00980A"), "00985A": ("野村", "00985A"), "00999A": ("野村", "00999A"),
    "00981A": ("統一", "49YTW"), "00403A": ("統一", "63YTW"), "00988A": ("統一", "61YTW"),
    "00982A": ("群益", "399"), "00992A": ("群益", "500"), "00415A": ("群益", "504"),
    "00406A": ("中信", "E0038"), "00995A": ("中信", "E0036"),
    "00991A": ("復華", "ETF23"),
    "00994A": ("第一金", "182"), "00408A": ("第一金", "183"),
}
# 官網只有最新一天的 ETF：代號 → (投信, 官網基金代碼)
官網最新 = {
    "00405A": ("富邦", "00405A"), "00407A": ("凱基", "J024"), "00401A": ("摩根", "TW00000401A1"),
    "00987A": ("台新", "00987A"), "00410A": ("永豐", "00410A"),
    "00404A": ("聯博", "TW00000404A5"), "00984A": ("安聯", "E0001"), "00993A": ("安聯", "E0002"),
}
第二彙整網址 = "https://raw.githubusercontent.com/janeytu/tw-etf-pages/main/data/snapshots/{}/{}.json"


def 數字(值):
    try:
        return float(str(值).replace(",", "").replace("%", "").strip())
    except ValueError:
        return float("nan")


def 是代號(代號):
    """台股代號（4 碼數字、ETF）或海外股票（例如 NVDA US）。"""
    代號 = str(代號).strip()
    return bool(re.fullmatch(r"\d{4,6}[A-Z]?|[A-Z0-9.]{1,12} [A-Z]{2}", 代號))


def 整理持股(列們):
    表 = pd.DataFrame(列們, columns=["code", "name", "shares", "weight"])
    表["code"] = 表["code"].astype(str).str.strip()
    表 = 表[表["code"].map(是代號) & (表["shares"] > 0)]
    return 表.drop_duplicates("code")


# ---------- 各投信官網 ----------
def 野村(基金, 日期):
    r = requests.post("https://www.nomurafunds.com.tw/API/ETFAPI/api/Fund/GetFundAssets",
                      json={"FundID": 基金, "SearchDate": 日期.isoformat()}, timeout=30,
                      headers={**標頭, "Origin": "https://www.nomurafunds.com.tw", "Accept": "application/json, text/plain, */*",
                               "Referer": "https://www.nomurafunds.com.tw/ETFWEB/product-description"})
    r.raise_for_status()
    資料 = ((r.json() or {}).get("Entries") or {}).get("Data") or {}
    資產 = 資料.get("FundAsset") or {}
    if not 資產.get("NavDate"):
        return None
    資料日 = dt.datetime.strptime(資產["NavDate"], "%Y/%m/%d").date()
    列們 = [(x[0], x[1], 數字(x[2]), 數字(x[3])) for t in 資料.get("Table") or [] if t.get("TableTitle") == "股票"
           for x in t.get("Rows") or [] if len(x) >= 4]
    return 資料日, 整理持股(列們), {"nav": 數字(資產.get("Nav")), "aum": 數字(資產.get("Aum")), "units": 數字(資產.get("Units"))}


_統一連線 = None


def 統一(基金, 日期):
    """日期是申購買回清單日（PostDate），TranDate 才是持股日（前一個交易日）。"""
    global _統一連線
    if _統一連線 is None:  # 先開一次網頁拿 cookie
        _統一連線 = requests.Session()
        _統一連線.headers.update(標頭)
        _統一連線.get(f"https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode={基金}", timeout=30)
    民國 = f"{日期.year - 1911}/{日期:%m/%d}"
    r = _統一連線.post("https://www.ezmoney.com.tw/ETF/Transaction/GetPCF", timeout=30,
                    json={"fundCode": 基金, "date": 民國, "specificDate": True},
                    headers={"Referer": f"https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode={基金}",
                             "X-Requested-With": "XMLHttpRequest", "Origin": "https://www.ezmoney.com.tw",
                             "Content-Type": "application/json; charset=UTF-8"})
    r.raise_for_status()
    if not r.text.lstrip().startswith("{"):
        return None
    資料 = r.json()
    pcf = 資料.get("pcf") or []
    m = re.search(r"Date\((-?\d+)\)", str(pcf[0].get("TranDate"))) if pcf else None
    if not m or int(m.group(1)) < 0:
        return None
    資料日 = dt.datetime.fromtimestamp(int(m.group(1)) / 1000, 台北時區).date()
    項 = {x.get("PCFCode"): x.get("Amount") for x in pcf}
    列們 = []
    for 類 in 資料.get("asset") or []:
        if 類.get("AssetCode") != "ST":
            continue
        for x in 類.get("Details") or []:
            列們.append((x.get("DetailCode"), x.get("DetailName"), 數字(x.get("Share")), 數字(x.get("NavRate"))))
    return 資料日, 整理持股(列們), {"nav": 數字(項.get("P_UNIT")), "aum": 數字(項.get("NAV")), "units": 數字(項.get("OUT_UNIT"))}


def 群益(基金, 日期):
    """群益的日期參數是「申購買回清單日」（持股日的下一個交易日），回傳的 date2 才是持股日。"""
    r = requests.post("https://www.capitalfund.com.tw/CFWeb/api/etf/buyback", json={"fundId": 基金, "date": 日期.isoformat()},
                      headers={**標頭, "Accept": "application/json",
                               "Referer": f"https://www.capitalfund.com.tw/etf/product/detail/{基金}/portfolio"}, timeout=30)
    r.raise_for_status()
    資料 = (r.json() or {}).get("data") or {}
    pcf = 資料.get("pcf") or {}
    if not re.fullmatch(r"20\d\d-\d\d-\d\d", str(pcf.get("date2"))):
        return None
    資料日 = dt.date.fromisoformat(pcf["date2"])
    列們 = [(x.get("stocNo"), x.get("stocName"), 數字(x.get("share")), 數字(x.get("weight"))) for x in 資料.get("stocks") or []]
    return 資料日, 整理持股(列們), {"nav": 數字(pcf.get("pUnit")), "aum": 數字(pcf.get("nav")), "units": 數字(pcf.get("totUnit"))}


def 復華(基金, 日期):
    r = requests.get(f"https://www.fhtrust.com.tw/api/assetsExcel/{基金}/{日期:%Y%m%d}", headers=標頭, timeout=30)
    if r.status_code != 200 or r.content[:2] != b"PK":
        return None
    表 = pd.read_excel(io.BytesIO(r.content), header=None, dtype=str)
    文字 = 表[0].fillna("").tolist()
    m = next((re.search(r"(\d{4})/(\d\d)/(\d\d)", t) for t in 文字 if "日期" in t), None)
    if not m:
        return None
    資料日 = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    def 下一格(關鍵字):
        i = next((i for i, t in enumerate(文字) if t.strip() == 關鍵字), None)
        return 數字(文字[i + 1]) if i is not None and i + 1 < len(文字) else float("nan")
    表頭 = next((i for i, t in enumerate(文字) if t.strip() == "證券代號"), None)
    列們 = []
    if 表頭 is not None:
        欄 = [str(x).strip() for x in 表.iloc[表頭]]
        內容 = 表.iloc[表頭 + 1:]
        內容.columns = 欄
        for _, x in 內容.iterrows():
            if "股數" in 欄 and "權重(%)" in 欄:
                列們.append((x["證券代號"], x["證券名稱"], 數字(x["股數"]), 數字(x["權重(%)"])))
    return 資料日, 整理持股(列們), {"nav": 下一格("基金每單位淨值"), "aum": 下一格("基金資產淨值"), "units": 下一格("基金在外流通單位數")}


抓官網 = {"野村": 野村, "統一": 統一, "群益": 群益, "復華": 復華}


def 第一金(基金, 日期):
    """日期是申購買回清單日，sdate 才是持股日（前一個交易日）。"""
    r = requests.post("https://www.fsitc.com.tw/WebAPI.aspx/Get_hd", json={"pStrFundID": 基金, "pStrDate": 日期.isoformat()},
                      headers={**標頭, "Content-Type": "application/json; charset=utf-8", "X-Requested-With": "XMLHttpRequest",
                               "Origin": "https://www.fsitc.com.tw", "Referer": "https://www.fsitc.com.tw/FundDetail.aspx"},
                      timeout=30)
    r.raise_for_status()
    try:
        資料 = r.json().get("d")
    except ValueError:  # 假日、還沒公布時回的是網頁
        return None
    if isinstance(資料, str):
        if 資料.lstrip().startswith("<"):
            return None
        資料 = json.loads(資料)
    if isinstance(資料, dict):
        資料 = next((v for v in 資料.values() if isinstance(v, list)), [])
    if not 資料 or not re.fullmatch(r"20\d\d-\d\d-\d\d", str(資料[0].get("sdate", ""))[:10]):
        return None
    資料日 = dt.date.fromisoformat(str(資料[0]["sdate"])[:10])
    列們 = [(x.get("A"), x.get("B"), 數字(x.get("D")), 數字(x.get("C"))) for x in 資料]
    return 資料日, 整理持股(列們), {}


抓官網["第一金"] = 第一金
_中信連線 = None


def 中信(基金, 日期):
    global _中信連線
    if _中信連線 is None:
        s = requests.Session()
        s.headers.update({**標頭, "Origin": "https://www.ctbcinvestments.com", "Referer": "https://www.ctbcinvestments.com/"})
        權杖 = s.post("https://www.ctbcinvestments.com.tw/API/home/AuthToken?token=www.ctbcinvestments.com",
                    json={"token": "www.ctbcinvestments.com"}, timeout=30).json()["Data"]["token"]
        _中信連線 = (s, 權杖)
    s, 權杖 = _中信連線
    r = s.post("https://www.ctbcinvestments.com.tw/API/etf/ETFHoldingWeight", params={"token": 權杖}, timeout=30,
               json={"token": 權杖, "FID": 基金, "StartDate": f"{日期.isoformat()}T00:00:00.000Z"})
    r.raise_for_status()
    資料 = r.json().get("Data") or {}
    資產 = (資料.get("FundAssets") or [{}])[0]
    m = re.fullmatch(r"(\d{4})/(\d\d)/(\d\d)", str(資產.get("資料日期", "")))
    if not m:
        return None
    資料日 = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    列們 = [(x.get("code_"), x.get("name_"), 數字(x.get("qty_")), 數字(x.get("weights_")))
           for 類 in 資料.get("FundAssetsDetail") or [] if 類.get("Code") == "STOCK" for x in 類.get("Data") or []]
    return 資料日, 整理持股(列們), {"nav": 數字(資產.get("基金每單位淨值")), "aum": 數字(資產.get("基金淨資產")),
                               "units": 數字(資產.get("基金在外流通單位數"))}


抓官網["中信"] = 中信


# ---------- 官網只有最新一天的（網頁表格或 Excel） ----------
def _網頁(網址, **參數):
    from bs4 import BeautifulSoup
    r = requests.request(參數.pop("method", "GET"), 網址, headers={**標頭, **參數.pop("headers", {})}, timeout=30, **參數)
    r.raise_for_status()
    r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
    網 = BeautifulSoup(r.text, "html.parser")
    return 網, re.sub(r"\s+", " ", 網.get_text(" ", strip=True))


def _日期(文字, 樣式):
    日們 = {dt.date(int(a), int(b), int(c)) for a, b, c in re.findall(樣式, 文字)}
    return 日們.pop() if len(日們) == 1 else None


def _基金資訊(文字):
    """網頁上常見的基金規模、單位數、淨值（找不到就留空）。"""
    def 找(*關鍵字):
        for k in 關鍵字:
            m = re.search(k + r"[^\d\-]{0,30}?([\d,]+(?:\.\d+)?)", 文字)
            if m:
                return 數字(m.group(1))
        return float("nan")
    return {"nav": 找("每受益權單位淨資產價值", "每單位淨值", "單位淨值"),
            "aum": 找("基金淨資產價值", "基金資產淨值", "淨資產價值\\(元\\)"),
            "units": 找("已發行受益權單位總數", "在外流通單位數", "流通在外單位數", "已發行單位數")}


def _表格列(網, 必要, 排除="口數"):
    """找第一個表頭含有「必要」所有文字的表格，回傳資料列（每列是各格文字）。"""
    for 表 in 網.find_all("table"):
        列們 = 表.find_all("tr")
        if len(列們) < 2:
            continue
        頭 = " ".join(c.get_text(" ", strip=True) for c in 列們[0].find_all(["th", "td"]))
        if not 頭.strip():
            頭 = " ".join(c.get_text(" ", strip=True) for c in 表.find_all("th"))
        if all(k in 頭 for k in 必要) and 排除 not in 頭:
            return [[c.get_text(" ", strip=True) for c in tr.find_all("td")] for tr in 列們 if tr.find_all("td")]
    return []


def 富邦(基金):
    網, 文字 = _網頁(f"https://websys.fsit.com.tw/FubonETF/Fund/Assets.aspx?stkId={基金}")
    資料日 = _日期(文字, r"資料日期[：:\s]*(20\d{2})[/\-年](\d{1,2})[/\-月](\d{1,2})")
    列們 = [(x[0], x[1], 數字(x[2]), 數字(x[4])) for x in _表格列(網, ["股數", "權重"]) if len(x) >= 5]
    return 資料日, 整理持股(列們), _基金資訊(文字)


def 凱基(基金):
    s = requests.Session()
    s.headers.update(標頭)
    s.get("https://www.kgifund.com.tw/Fund/RedemptionList", timeout=30)
    r = s.post("https://www.kgifund.com.tw/Fund/RedemptionVC", data={"fundID": 基金, "queryDate": ""}, timeout=30,
               headers={"X-Requested-With": "XMLHttpRequest", "Referer": "https://www.kgifund.com.tw/Fund/RedemptionList"})
    r.raise_for_status()
    from bs4 import BeautifulSoup
    網 = BeautifulSoup(r.text, "html.parser")
    文字 = re.sub(r"\s+", " ", 網.get_text(" ", strip=True))
    資料日 = _日期(文字, r"\((20\d{2})/(\d{1,2})/(\d{1,2})\)\s*每受益權單位淨資產價值")
    列們 = [(x[0], x[1], 數字(x[2]), 數字(x[3])) for x in _表格列(網, ["股票代號", "股票名稱"]) if len(x) >= 4]
    return 資料日, 整理持股(列們), _基金資訊(文字)


def 摩根(基金):
    import openpyxl
    代號 = next(k for k, v in 官網最新.items() if v[1] == 基金)
    r = requests.get(f"https://am.jpmorgan.com/content/dam/jpm-am-aem/asiapacific/tw/zh/regulatory/etf-supplement/"
                     f"jpm_apac_tw_etf_pcf_updates_{代號}_{基金}.xlsx", timeout=30,
                     headers={**標頭, "Referer": "https://am.jpmorgan.com/tw/zh/asset-management/twetf/"})
    if r.status_code != 200 or r.content[:2] != b"PK":
        print(f"摩根 {r.status_code}")
        return None
    列們 = list(openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True))
    基金頭, 基金值, 股頭 = [str(x).strip() for x in 列們[0]], 列們[1], [str(x).strip() for x in 列們[2]]
    基 = dict(zip(基金頭, 基金值))
    估值日 = dt.datetime.strptime(str(基.get("Valuation Date"))[:8], "%Y%m%d").date()
    資料日 = 前一交易日(估值日)  # 估值日是下一個交易日
    總值 = 數字(基.get("Estimated Total Market Value"))
    i = {k: 股頭.index(k) for k in ("Constituent Ticker", "Constituent Description", "Shares or PAR Amount",
                                     "Market Value Base", "Record Type")}
    持股 = [(str(x[i["Constituent Ticker"]]).split()[0], x[i["Constituent Description"]], 數字(x[i["Shares or PAR Amount"]]),
            數字(x[i["Market Value Base"]]) / 總值 * 100 if 總值 else float("nan"))
           for x in 列們[3:] if x and x[i["Record Type"]] == "D"]
    return 資料日, 整理持股(持股), {"aum": 總值}


def 台新(基金):
    網, 文字 = _網頁(f"https://www.tsit.com.tw/ETF/Home/Pcf/{基金}")
    資料日 = _日期(文字, r"(20\d{2})/(\d{1,2})/(\d{1,2})\s*每基數")
    def 代號(文字):
        段 = 文字.split()
        return 段[0] if len(段) == 1 or 段[1] == "TT" else " ".join(段[:2])
    列們 = [(代號(x[0]), x[1], 數字(x[2]), 數字(x[3])) for x in _表格列(網, ["股數", "權重"]) if len(x) >= 4]
    return 資料日, 整理持股(列們), _基金資訊(文字)


def 永豐(基金):
    網, 文字 = _網頁(f"https://sitc.sinopac.com/SinopacEtfs/Etfs/Pcf/{基金}")
    資料日 = _日期(文字, r"資料日期[：:\s]*(20\d{2})[/\-](\d{1,2})[/\-](\d{1,2})")
    列們 = [(x[0], x[1], 數字(x[2]), 數字(x[3])) for x in _表格列(網, ["證券代碼", "證券名稱"]) if len(x) >= 4]
    return 資料日, 整理持股(列們), _基金資訊(文字)


def 聯博(基金):
    import openpyxl
    r = requests.get(f"https://webapi.alliancebernstein.com/v2/funds/tw/zh-tw/investor/{基金}/xls?type=holdings&prec=2",
                     headers={**標頭, "Referer": f"https://www.abfunds.com.tw/zh-tw/etfs/pcf.{基金}.html"}, timeout=30)
    if r.status_code != 200 or r.content[:2] != b"PK":
        print(f"聯博 {r.status_code}")
        return None
    m = re.search(r"(\d{4})-(\d\d)-(\d\d)", r.headers.get("content-disposition", ""))
    資料日 = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    列們, 開始 = [], False
    for x in openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True):
        頭 = " ".join(str(c) for c in x[:5] if c is not None)
        if not 開始:
            開始 = all(k in 頭 for k in ("代碼", "名稱", "股數", "權重"))
            continue
        if not x or x[0] is None:
            break
        isin = str(x[0]).strip()
        代號 = isin[5:9] if isin.startswith("TW") and isin[5:9].isdigit() else isin
        列們.append((代號, x[1], 數字(x[2]), 數字(x[4])))
    return 資料日, 整理持股(列們), {}


def 安聯(基金):
    s = requests.Session()
    s.headers.update({**標頭, "Origin": "https://etf.allianzgi.com.tw", "Accept": "application/json, text/plain, */*",
                      "Referer": f"https://etf.allianzgi.com.tw/etf-info/{基金}?tab=4"})
    權杖 = s.get("https://etf.allianzgi.com.tw/webapi/api/AntiForgery/GetAntiForgeryToken", timeout=30).json()["token"]
    r = s.post("https://etf.allianzgi.com.tw/webapi/api/Fund/GetFundAssets", json={"FundID": 基金},
               headers={"X-XSRF-TOKEN": 權杖}, timeout=30)
    r.raise_for_status()
    資料 = ((r.json() or {}).get("Entries") or {}).get("Data") or {}
    資產 = 資料.get("FundAsset") or {}
    if not 資產.get("NavDate"):
        return None
    資料日 = dt.datetime.strptime(資產["NavDate"], "%Y/%m/%d").date()
    列們 = []
    for t in 資料.get("Table") or []:
        欄 = [c.get("Name") for c in t.get("Columns") or []]
        if not str(t.get("TableTitle", "")).startswith("股票") or "股票代號" not in 欄:
            continue
        i = {k: 欄.index(k) for k in ("股票代號", "股票名稱", "股數", "權重(%)") if k in 欄}
        列們 += [(x[i["股票代號"]], x[i["股票名稱"]], 數字(x[i["股數"]]), 數字(x[i["權重(%)"]])) for x in t.get("Rows") or []]
    return 資料日, 整理持股(列們), {"nav": 數字(資產.get("Nav")), "aum": 數字(資產.get("Aum")), "units": 數字(資產.get("Units"))}


抓最新 = {"安聯": 安聯, "富邦": 富邦, "凱基": 凱基, "摩根": 摩根, "台新": 台新, "永豐": 永豐, "聯博": 聯博}


def 彙整來源():
    """公開彙整（各投信官網 PCF 整理成一份 JSON）：只有最新一天。回傳 [(ETF, 投信, 資料日, 持股, 資訊)]。"""
    r = requests.get(彙整網址, headers=標頭, timeout=60)
    r.raise_for_status()
    結果 = []
    for 代號, v in (r.json().get("etfs") or {}).items():
        if v.get("status") != "ok" or not v.get("data_date"):
            continue  # stale＝那家投信當天沒抓到，沿用舊資料，不存
        持股 = 整理持股([(x.get("code"), x.get("name"), 數字(x.get("shares")), 數字(x.get("weight")))
                     for x in v.get("holdings") or []])
        淨值, 規模 = 數字(v.get("nav")), 數字(v.get("scale"))
        結果.append((代號, v.get("issuer", ""), dt.date.fromisoformat(v["data_date"]), 持股,
                   {"nav": 淨值, "aum": 規模, "units": 規模 / 淨值 if 淨值 else float("nan")}))
    return 結果


def 第二彙整(代號, 今天):
    """janeytu/tw-etf-pages 每天存的快照（檔名日期各投信意義不同，所以用抓取時間推算持股日）。"""
    for i in range(-2, 6):
        日 = 今天 - dt.timedelta(days=i)
        r = requests.get(第二彙整網址.format(代號, 日.isoformat()), headers=標頭, timeout=30)
        if r.status_code != 200:
            continue
        v = r.json()
        抓取 = dt.datetime.fromisoformat(str(v.get("fetched_at"))).astimezone(台北時區)
        # 下午 3 點前抓的是前一個交易日的持股，之後抓的可能是當天的；保守取前一個交易日
        資料日 = 前一交易日(抓取.date() + dt.timedelta(days=1)) if 抓取.hour >= 18 else 前一交易日(抓取.date())
        持股 = 整理持股([(x.get("stock_code"), x.get("stock_name"), 數字(x.get("shares")), 數字(x.get("weight_pct")))
                       for x in v.get("holdings") or [] if not x.get("is_placeholder")])
        return 資料日, 持股, {}
    return None


# ---------- 存檔 ----------
來源順位 = {"官網": 0, "彙整": 1, "彙整2": 2}


def 持股檔(日期):
    return 持股資料夾 / f"{日期:%Y-%m}" / f"{日期:%Y%m%d}.csv.gz"


def 存持股(代號, 日期, 持股, 來源):
    """同一天同一檔 ETF：官網 > 彙整 > 彙整2，同等級以最新抓到的為準。"""
    檔 = 持股檔(日期)
    舊 = pd.read_csv(檔, dtype={"etf": str, "code": str}) if 檔.exists() else pd.DataFrame()
    if len(舊):
        已有 = 舊.loc[舊["etf"] == 代號, "source"]
        if len(已有) and 來源順位.get(已有.iloc[0], 9) < 來源順位[來源]:
            return False
    新 = 持股.assign(etf=代號, source=來源)[["etf", "code", "name", "shares", "weight", "source"]]
    合 = pd.concat([舊[舊["etf"] != 代號] if len(舊) else 舊, 新]).sort_values(["etf", "weight"], ascending=[True, False])
    檔.parent.mkdir(parents=True, exist_ok=True)
    合.to_csv(檔, index=False, compression="gzip")
    return True


def 存資訊(列們):
    if not 列們:
        return
    舊 = pd.read_csv(資訊檔, dtype={"etf": str}) if 資訊檔.exists() else pd.DataFrame()
    合 = pd.concat([pd.DataFrame(列們), 舊], ignore_index=True)  # 新抓的排前面
    合["_順位"] = 合["source"].map(來源順位).fillna(9)
    合 = (合.sort_values("_順位", kind="stable").groupby(["etf", "date"], as_index=False).first()
          .drop(columns="_順位").sort_values(["date", "etf"]))
    資料夾.mkdir(parents=True, exist_ok=True)
    合.to_csv(資訊檔, index=False)


def main():
    參數 = argparse.ArgumentParser()
    參數.add_argument("--days", type=int, default=7, help="官網有歷史的 ETF 回補幾天")
    參數.add_argument("--health", action="store_true", help="只做健康檢查：超過 2 個交易日沒更新就 LINE 通知")
    選項 = 參數.parse_args()
    if 選項.health:
        return 通知斷線()
    天數 = 選項.days
    今天 = dt.datetime.now(台北時區).date()
    日們 = [今天 + dt.timedelta(days=1 - i) for i in range(天數 + 2)]
    日們 = [d for d in 日們 if d.weekday() < 5]
    資訊們, 筆數 = [], 0
    for 代號, (投信, 基金) in 官網.items():
        已有 = {d for d in 日們 if 持股檔(d).exists()
              and (pd.read_csv(持股檔(d), dtype={"etf": str}, usecols=["etf", "source"])
                   .query("etf == @代號 and source == '官網'").shape[0] > 0)}
        失敗, 抓到 = 0, set()
        for d in 日們:
            # 統一、群益、第一金查的是「申購買回清單日」，拿到的是前一個交易日的持股；野村、復華查的就是持股日
            清單日 = 投信 in ("統一", "群益", "第一金")
            對應日 = 前一交易日(d) if 清單日 else d
            if 對應日 in 已有 and d < 今天 - dt.timedelta(days=3):
                continue
            if d > 今天 and not 清單日:
                continue
            try:
                結果 = 抓官網[投信](基金, d)
                失敗 = 0
            except Exception as e:
                失敗 += 1
                print(f"{代號} {投信} {d}：{type(e).__name__} {str(e)[:120]}")
                if 失敗 >= 5:
                    break
                time.sleep(2)
                continue
            time.sleep(0.3)
            if not 結果 or 結果[1].empty:
                continue
            資料日, 持股, 資訊 = 結果
            if 資料日 > 今天 or 資料日 in 抓到:
                continue
            存持股(代號, 資料日, 持股, "官網")
            資訊們.append({"etf": 代號, "date": 資料日.isoformat(), "issuer": 投信, "source": "官網", **資訊})
            抓到.add(資料日)
            筆數 += 1
        已有 |= 抓到
        print(f"{代號} {投信}：已有 {len(已有)} 天")
    for 代號, (投信, 基金) in 官網最新.items():
        try:
            結果 = 抓最新[投信](基金)
        except Exception as e:
            print(f"{代號} {投信}：{type(e).__name__} {str(e)[:120]}")
            continue
        if not 結果 or not 結果[0] or 結果[1].empty or 結果[0] > 今天:
            print(f"{代號} {投信}：沒抓到（{'沒有日期' if 結果 and not 結果[0] else '沒有持股'}）")
            continue
        資料日, 持股, 資訊 = 結果
        if not 日期可信(代號, 資料日, 持股):
            print(f"{代號} {投信}：{資料日} 不是交易日或和上一份相同，略過")
            continue
        存持股(代號, 資料日, 持股, "官網")
        資訊們.append({"etf": 代號, "date": 資料日.isoformat(), "issuer": 投信, "source": "官網", **資訊})
        筆數 += 1
        print(f"{代號} {投信}：{資料日} {len(持股)} 檔")
    最新日 = {}
    try:
        for 代號, 投信, 資料日, 持股, 資訊 in 彙整來源():
            if 持股.empty:
                continue
            最新日[代號] = 資料日
            資訊們.append({"etf": 代號, "date": 資料日.isoformat(), "issuer": 投信, "source": "彙整", **資訊})
            if 存持股(代號, 資料日, 持股, "彙整"):
                筆數 += 1
        print(f"彙整來源 OK：{len(最新日)} 檔")
    except Exception as e:
        print(f"彙整來源失敗：{type(e).__name__} {str(e)[:200]}")
    # 第二彙整：第一個彙整沒有、或日期比較舊的，才去補
    最近交易日 = max(最新日.values(), default=None)
    for 代號 in 主動式清單():
        if 最近交易日 and 最新日.get(代號) == 最近交易日:
            continue
        try:
            結果 = 第二彙整(代號, 今天)
        except Exception as e:
            print(f"{代號} 第二彙整：{type(e).__name__} {str(e)[:120]}")
            continue
        time.sleep(0.3)
        if not 結果 or 結果[1].empty or 結果[0] > 今天 or not 日期可信(代號, 結果[0], 結果[1]):
            continue
        資料日, 持股, 資訊 = 結果
        資訊們.append({"etf": 代號, "date": 資料日.isoformat(), "issuer": "", "source": "彙整2", **資訊})
        if 存持股(代號, 資料日, 持股, "彙整2"):
            筆數 += 1
            print(f"{代號} 第二彙整：{資料日} {len(持股)} 檔")
    存資訊(資訊們)
    print(f"共存 {筆數} 份持股")


def 通知斷線():
    斷 = 健康檢查()
    if not 斷:
        print("主動式 ETF 持股都有更新")
        return
    文字 = "⚠️ 主動式 ETF 持股超過 2 個交易日沒更新：\n" + "\n".join(
        f"・{e}（最後 {d:%m/%d}）" if d else f"・{e}（還沒有資料）" for e, d in 斷) + \
        "\n可能是投信官網改版或彙整資料停止更新，網站上這幾檔會停在舊資料。"
    print(文字)
    import notify
    notify.推播(文字)


def 前一交易日(日期):
    """日期之前最近的交易日：跳過週末和 data/status 記為休市（closed）的日子。"""
    休市 = set()
    for f in (價格資料夾.parent / "status").glob("*.txt"):
        休市 |= {x.split(",")[0] for x in f.read_text().split() if x.endswith(",closed")}
    d = 日期 - dt.timedelta(days=1)
    while d.weekday() >= 5 or f"{d:%Y%m%d}" in 休市:
        d -= dt.timedelta(days=1)
    return d


def 日期可信(代號, 日期, 持股):
    """只有最新一天的來源，日期是推算的：休市日不收；還不知道是不是交易日時，持股和上一份一模一樣就不收（多半是假日重複）。"""
    狀態 = {}
    for f in (價格資料夾.parent / "status").glob("*.txt"):
        狀態.update(x.split(",", 1) for x in f.read_text().split() if "," in x)
    if 狀態.get(f"{日期:%Y%m%d}") == "closed":
        return False
    if 狀態.get(f"{日期:%Y%m%d}") == "ok":
        return True
    for f in sorted(持股資料夾.glob("*/*.csv.gz"), reverse=True)[:10]:
        if f.name[:8] >= f"{日期:%Y%m%d}":
            continue
        舊 = pd.read_csv(f, dtype={"etf": str, "code": str})
        舊 = 舊[舊["etf"] == 代號]
        if len(舊):
            return not 舊.set_index("code")["shares"].sort_index().equals(持股.set_index("code")["shares"].sort_index().astype(float))
    return True


def 主動式清單():
    """最新一天行情裡所有主動式 ETF（代號 00xxxA）。"""
    檔們 = sorted(價格資料夾.glob("*/*.csv.gz"))
    if not 檔們:
        return sorted(set(官網) | set(官網最新))
    t = pd.read_csv(檔們[-1], dtype={"code": str}, usecols=["code"])
    return sorted(t.loc[t["code"].str.fullmatch(r"00\d{3}A"), "code"])


def 健康檢查(今天=None, 容忍天數=2):
    """哪些主動式 ETF 的持股超過 容忍天數 個交易日沒更新。回傳 [(代號, 最後日期或 None)]。"""
    今天 = 今天 or dt.datetime.now(台北時區).date()
    檔們 = sorted(持股資料夾.glob("*/*.csv.gz"))[-30:]
    最後 = {}
    for f in 檔們:
        for e in pd.read_csv(f, dtype={"etf": str}, usecols=["etf"])["etf"].unique():
            最後[e] = dt.date(int(f.name[:4]), int(f.name[4:6]), int(f.name[6:8]))
    # 交易日以股價資料為準（ETF 資料全部斷掉時也看得出來）
    交易日們 = sorted(dt.date(int(f.name[:4]), int(f.name[4:6]), int(f.name[6:8]))
                  for f in sorted(價格資料夾.glob("*/*.csv.gz"))[-10:])
    交易日們 = [d for d in 交易日們 if d <= 今天]
    if len(交易日們) <= 容忍天數 or not 最後:
        return []
    門檻 = 交易日們[-1 - 容忍天數]
    追蹤 = set(最後) | set(官網) | set(官網最新)
    return sorted((e, 最後.get(e)) for e in 追蹤 if 最後.get(e) is None or 最後[e] <= 門檻)


# ---------- 網站用：讀資料與分析 ----------
def 讀持股(天數=70):
    """最近 天數 個有資料的日子，合成一張表（date 欄是 Timestamp）。"""
    檔們 = sorted(持股資料夾.glob("*/*.csv.gz"))[-天數:]
    if not 檔們:
        return pd.DataFrame(columns=["date", "etf", "code", "name", "shares", "weight", "source"])
    表們 = [pd.read_csv(f, dtype={"etf": str, "code": str}).assign(date=pd.Timestamp(f.name[:8])) for f in 檔們]
    return pd.concat(表們, ignore_index=True)


def 讀資訊():
    if not 資訊檔.exists():
        return pd.DataFrame(columns=["etf", "date", "issuer", "source", "nav", "aum", "units"])
    表 = pd.read_csv(資訊檔, dtype={"etf": str})
    表["date"] = pd.to_datetime(表["date"])
    return 表


def 收盤價(日期):
    """那天（或之前最近一天）的收盤價：{代號: 收盤}。"""
    for i in range(8):
        d = pd.Timestamp(日期) - pd.Timedelta(days=i)
        f = 價格資料夾 / f"{d:%Y-%m}" / f"{d:%Y%m%d}.csv.gz"
        if f.exists():
            t = pd.read_csv(f, dtype={"code": str}, usecols=["code", "close"])
            return t.dropna().set_index("code")["close"].to_dict()
    return {}


def 每日變化(持股, 資訊):
    """每檔 ETF 每一天和自己的前一份持股比對。
    扣除申贖：基金被申購（單位數變多）時經理人會等比例買進，那不是看好，所以用「今天股數 − 昨天股數 × 單位數變化」判斷加減碼。"""
    if 持股.empty:
        return pd.DataFrame()
    單位 = 資訊.set_index(["etf", "date"])["units"].to_dict() if len(資訊) else {}
    結果 = []
    for 代號, 表 in 持股.groupby("etf"):
        日們 = sorted(表["date"].unique())
        前 = None
        for d in 日們:
            今 = 表[表["date"] == d].set_index("code")
            if 前 is not None:
                昨日, 昨 = 前
                比 = 單位.get((代號, d), float("nan")) / 單位.get((代號, 昨日), float("nan"))
                比 = 比 if pd.notna(比) and 0.5 < 比 < 2 else 1.0
                代號們 = 今.index.union(昨.index)
                合 = pd.DataFrame({"etf": 代號, "date": d, "prev_date": 昨日, "code": 代號們,
                                  "name": 今["name"].reindex(代號們).fillna(昨["name"].reindex(代號們)).values,
                                  "shares": 今["shares"].reindex(代號們).fillna(0).values,
                                  "prev_shares": 昨["shares"].reindex(代號們).fillna(0).values,
                                  "weight": 今["weight"].reindex(代號們).fillna(0).values,
                                  "prev_weight": 昨["weight"].reindex(代號們).fillna(0).values})
                合["delta"] = 合["shares"] - 合["prev_shares"]
                合["adj_delta"] = 合["shares"] - 合["prev_shares"] * 比
                結果.append(合)
            前 = (d, 今)
    if not 結果:
        return pd.DataFrame()
    變 = pd.concat(結果, ignore_index=True)
    def 類型(x):
        if x.prev_shares == 0 and x.shares > 0:
            return "新增"
        if x.shares == 0 and x.prev_shares > 0:
            return "出清"
        門檻 = max(1000, x.prev_shares * 0.005)  # 至少 1 張、且超過 0.5% 才算經理人主動調整
        if x.adj_delta >= 門檻 and x.delta > 0:
            return "加碼"
        if x.adj_delta <= -門檻 and x.delta < 0:
            return "減碼"
        return "持平"
    變["type"] = [類型(x) for x in 變.itertuples()]
    全進出 = 變["type"].isin(["新增", "出清"])
    變.loc[全進出, "adj_delta"] = 變.loc[全進出, "delta"]
    價格 = {d: 收盤價(d) for d in 變["date"].unique()}
    變["price"] = [價格[d].get(c, float("nan")) for d, c in zip(變["date"], 變["code"])]
    變["amount"] = 變["delta"] * 變["price"]
    變["adj_amount"] = 變["adj_delta"] * 變["price"]
    return 變


if __name__ == "__main__":
    main()
