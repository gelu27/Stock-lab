# 主動式 ETF 每日持股追蹤：抓各投信公布的每日持股（申購買回清單 PCF），比對每天的加碼、減碼、新增、出清
# 由 GitHub Actions（etf.yml）每天收盤後執行，也可以手動執行：
#   python etf_data.py               （抓最新一天，並補最近 7 天缺的）
#   python etf_data.py --days 90     （有歷史查詢的投信，回補近 90 天）
#
# 資料來源（都是公開、免費的）
#   野村、統一、群益、復華：投信官網每日持股，可以查歷史日期
#   其他投信（摩根、富邦、中信、凱基、第一金、永豐、安聯、台新、聯博、國泰）：
#     公開的彙整資料 nctuwanglin.github.io/active-etf（逐家抓投信官網 PCF 後整理），只有最新一天，每天累積
#
# 資料夾結構
#   data/etf/holdings/2026-10/20261022.csv.gz   當天各主動式 ETF 的持股（etf, code, name, shares, weight, source）
#   data/etf/info.csv                           每天的基金規模、淨值、在外流通單位數

import argparse
import datetime as dt
import io
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
    "00982A": ("群益", "399"), "00992A": ("群益", "500"),
    "00991A": ("復華", "ETF23"),
}


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
    """群益的日期參數是「申購買回清單適用日」（持股日的下一個交易日），回傳的 date2 才是持股日。"""
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


# ---------- 存檔 ----------
def 持股檔(日期):
    return 持股資料夾 / f"{日期:%Y-%m}" / f"{日期:%Y%m%d}.csv.gz"


def 存持股(代號, 日期, 持股, 來源):
    """同一天同一檔 ETF 以最新抓到的為準（官網優先於彙整）。"""
    檔 = 持股檔(日期)
    舊 = pd.read_csv(檔, dtype={"etf": str, "code": str}) if 檔.exists() else pd.DataFrame()
    if len(舊) and 來源 == "彙整" and ((舊["etf"] == 代號) & (舊["source"] == "官網")).any():
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
    合 = pd.concat([舊, pd.DataFrame(列們)]).drop_duplicates(["etf", "date"], keep="last").sort_values(["date", "etf"])
    資料夾.mkdir(parents=True, exist_ok=True)
    合.to_csv(資訊檔, index=False)


def main():
    參數 = argparse.ArgumentParser()
    參數.add_argument("--days", type=int, default=7, help="官網有歷史的 ETF 回補幾天")
    天數 = 參數.parse_args().days
    今天 = dt.datetime.now(台北時區).date()
    日們 = [今天 - dt.timedelta(days=i) for i in range(天數 + 1)]
    日們 = [d for d in 日們 if d.weekday() < 5]
    資訊們, 筆數 = [], 0
    for 代號, (投信, 基金) in 官網.items():
        已有 = {d for d in 日們 if 持股檔(d).exists()
              and (pd.read_csv(持股檔(d), dtype={"etf": str}, usecols=["etf", "source"])
                   .query("etf == @代號 and source == '官網'").shape[0] > 0)}
        失敗 = 0
        for d in 日們:
            查詢日 = d + dt.timedelta(days=1) if 投信 == "群益" else d  # 群益要用下一天查
            if d in 已有 and d < 今天 - dt.timedelta(days=3):
                continue
            try:
                結果 = 抓官網[投信](基金, 查詢日)
            except Exception as e:
                失敗 += 1
                print(f"{代號} {投信} {d}：{type(e).__name__} {str(e)[:120]}")
                if 失敗 >= 3:
                    break
                continue
            time.sleep(0.3)
            if not 結果 or 結果[1].empty:
                continue
            資料日, 持股, 資訊 = 結果
            if 資料日 > 今天:
                continue
            存持股(代號, 資料日, 持股, "官網")
            資訊們.append({"etf": 代號, "date": 資料日.isoformat(), "issuer": 投信, "source": "官網", **資訊})
            已有.add(資料日)
            筆數 += 1
        print(f"{代號} {投信}：已有 {len(已有)} 天")
    try:
        for 代號, 投信, 資料日, 持股, 資訊 in 彙整來源():
            if 持股.empty:
                continue
            if 存持股(代號, 資料日, 持股, "彙整"):
                資訊們.append({"etf": 代號, "date": 資料日.isoformat(), "issuer": 投信, "source": "彙整", **資訊})
                筆數 += 1
        print("彙整來源 OK")
    except Exception as e:
        print(f"彙整來源失敗：{type(e).__name__} {str(e)[:200]}")
    存資訊(資訊們)
    print(f"共存 {筆數} 份持股")


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
    價格 = {d: 收盤價(d) for d in 變["date"].unique()}
    變["price"] = [價格[d].get(c, float("nan")) for d, c in zip(變["date"], 變["code"])]
    變["amount"] = 變["delta"] * 變["price"]
    return 變


if __name__ == "__main__":
    main()
