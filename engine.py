# 計算核心：讀資料庫、算技術指標、選股、回測
# 想調整選股或回測規則，主要改這個檔案

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

資料夾 = Path(__file__).parent / "data"

手續費率 = 0.001425  # 買賣各收一次（未算券商折扣）
證交稅率 = 0.003     # 賣出才收

排序方式 = {
    "殖利率 高→低": ("殖利率", False),
    "本益比 低→高": ("本益比", True),
    "股價淨值比 低→高": ("淨值比", True),
    "營收年增率 高→低": ("營收年增率", False),
    "20日漲幅 高→低": ("20日漲幅", False),
    "成交值 大→小": ("成交值億", False),
    "量比 高→低": ("量比", False),
    "法人5日買超 多→少": ("法人5日買超", False),
    "投信連買天數 多→少": ("投信連買", False),
    "週轉率 高→低": ("週轉率", False),
}


# ---------- 1. 讀資料 ----------
def _讀每日檔(子資料夾):
    檔案們 = sorted((資料夾 / 子資料夾).glob("**/*.csv.gz"))
    if not 檔案們:
        return None
    表們, 名稱們 = [], {}
    for f in 檔案們:
        t = pd.read_csv(f, dtype={"code": str})
        if "name" in t.columns:  # 名稱另外存一份對照表，不必每天每檔都存一個字串（很佔記憶體）
            名稱們.update(zip(t["code"], t["name"]))
            t = t.drop(columns="name")
        t["date"] = pd.Timestamp(f"{f.name[:4]}-{f.name[4:6]}-{f.name[6:8]}")  # 日期從檔名取
        數字 = t.select_dtypes("number").columns
        t[數字] = t[數字].astype("float32")
        表們.append(t)
    表 = pd.concat(表們, ignore_index=True)
    del 表們
    表 = 表.drop_duplicates(["date", "code"], keep="last")
    # 同樣的文字共用同一個物件，例如「2330」「上市」，省下幾百 MB 記憶體
    for 欄 in ("code", "market"):
        if 欄 in 表.columns:
            共用 = {v: v for v in 表[欄].dropna().unique()}
            表[欄] = 表[欄].map(共用)
    if 名稱們:
        表["name"] = 表["code"].map(名稱們)
    return 表


def 讀取資料庫():
    表 = _讀每日檔("prices")
    if 表 is None:
        return None
    if "market" not in 表.columns:
        表["market"] = "上市"
    表["market"] = 表["market"].fillna("上市")
    籌碼 = _讀每日檔("chips")
    if 籌碼 is not None:
        表 = 表.merge(籌碼, on=["date", "code"], how="left")
    數字 = 表.select_dtypes("float64").columns
    表[數字] = 表[數字].astype("float32")  # 省記憶體
    return 表.sort_values(["code", "date"], ignore_index=True)


def 讀取加權指數():
    檔案們 = sorted((資料夾 / "index").glob("*.csv"))
    if not 檔案們 and (資料夾 / "index.csv").exists():
        檔案們 = [資料夾 / "index.csv"]
    if not 檔案們:
        return None
    表 = pd.concat([pd.read_csv(f, parse_dates=["date"]) for f in 檔案們])
    return 表.drop_duplicates("date", keep="last").sort_values("date")


def 讀取分時():
    """回傳 {日期: DataFrame(time, taiex)}，最近 5 個交易日。"""
    結果 = {}
    for f in sorted((資料夾 / "intraday").glob("*.csv")):
        t = pd.read_csv(f)
        t["datetime"] = pd.to_datetime(f.stem + " " + t["time"])
        結果[f.stem] = t
    return 結果


def 讀取基本面():
    """最新月營收、EPS、股本，回傳以代號為索引的表。"""
    表 = None
    f = 資料夾 / "fundamental" / "revenue.csv"
    if f.exists():
        r = pd.read_csv(f, dtype={"code": str}).drop_duplicates("code", keep="last").set_index("code")
        表 = r.rename(columns={"month": "營收月份", "rev_yoy": "營收年增率", "rev_mom": "營收月增率",
                              "rev_cum_yoy": "累計營收年增率"})[["營收月份", "營收年增率", "營收月增率", "累計營收年增率"]]
        h = 資料夾 / "fundamental" / "revenue_history.csv"
        if h.exists():
            歷史 = pd.concat([pd.read_csv(h, dtype={"code": str}), r.reset_index()[["code", "month", "revenue"]]])
            歷史 = 歷史.drop_duplicates(["code", "month"], keep="last").sort_values(["code", "month"])
            最新 = 歷史.groupby("code").tail(1).set_index("code")
            以前最高 = 歷史.groupby("code")["revenue"].apply(lambda s: s.iloc[:-1].max() if len(s) >= 13 else np.nan)
            表["營收創新高"] = (最新["revenue"] >= 以前最高).reindex(表.index).fillna(False)
    f = 資料夾 / "fundamental" / "eps.csv"
    if f.exists():
        e = pd.read_csv(f, dtype={"code": str}).sort_values(["code", "quarter"])
        最新 = e.drop_duplicates("code", keep="last").set_index("code")
        最新 = 最新.rename(columns={"quarter": "EPS季度", "eps": "EPS"})[["EPS季度", "EPS"]]
        最新["近三季EPS"] = _近三季EPS(e).reindex(最新.index).fillna(最新["EPS"])
        表 = 最新 if 表 is None else 表.join(最新, how="outer")
    f = 資料夾 / "fundamental" / "capital.csv"
    if f.exists():
        c = pd.read_csv(f, dtype={"code": str}).drop_duplicates("code", keep="last").set_index("code")
        表 = _股本表() if 表 is None else 表.join(_股本表(), how="outer")
    f = 資料夾 / "fundamental" / "income.csv"
    if f.exists():
        m = 毛利率表()
        表 = m if 表 is None else 表.join(m, how="outer")
    return 表


def 單季損益(代號=None):
    """損益表是「今年累計」，換成單季的營收、毛利、營業利益與毛利率、營益率。"""
    f = 資料夾 / "fundamental" / "income.csv"
    if not f.exists():
        return pd.DataFrame()
    t = pd.read_csv(f, dtype={"code": str})
    if 代號 is not None:
        t = t[t["code"] == str(代號)]
    t = t.dropna(subset=["revenue", "gross"]).sort_values(["code", "quarter"]).copy()
    t["年"], t["季"] = t["quarter"].str[:4], t["quarter"].str[-1].astype(int)
    前季號 = t.groupby(["code", "年"])["季"].shift()
    for k in ("revenue", "gross", "opinc"):
        前 = t.groupby(["code", "年"])[k].shift()
        t[k + "_q"] = np.where(t["季"] == 1, t[k], np.where(前季號 == t["季"] - 1, t[k] - 前, np.nan))
    有效 = t["revenue_q"] > 0
    t["毛利率"] = np.where(有效, t["gross_q"] / t["revenue_q"] * 100, np.nan).round(2)
    t["營益率"] = np.where(有效, t["opinc_q"] / t["revenue_q"] * 100, np.nan).round(2)
    return t


def 毛利率表():
    """每檔最新一季的單季毛利率，和上一季、去年同季比較（百分點）。"""
    t = 單季損益().dropna(subset=["毛利率"])
    if t.empty:
        return pd.DataFrame(columns=["毛利率", "毛利率季度", "毛利率季增", "毛利率年增", "營益率"])
    t["序"] = t["年"].astype(int) * 4 + t["季"]
    鍵 = t.set_index(["code", "序"])["毛利率"]
    最新 = t.groupby("code").tail(1).set_index("code")
    上季 = 鍵.reindex(list(zip(最新.index, 最新["序"] - 1))).values
    去年 = 鍵.reindex(list(zip(最新.index, 最新["序"] - 4))).values
    return pd.DataFrame({"毛利率": 最新["毛利率"], "毛利率季度": 最新["quarter"],
                         "毛利率季增": (最新["毛利率"] - 上季).round(2), "毛利率年增": (最新["毛利率"] - 去年).round(2),
                         "營益率": 最新["營益率"]}, index=最新.index)


def _近三季EPS(e):
    """交易所公布的是「今年累計」EPS，先換成單季再加最近三季；資料不夠的股票回傳空值。"""
    e = e.copy()
    e["年"], e["季"] = e["quarter"].str[:4], e["quarter"].str[-1].astype(int)
    前一季 = e.groupby(["code", "年"])["eps"].shift()
    前一季號 = e.groupby(["code", "年"])["季"].shift()
    e["單季"] = np.where(e["季"] == 1, e["eps"], np.where(前一季號 == e["季"] - 1, e["eps"] - 前一季, np.nan))
    def 加總(g):
        g = g.tail(3)
        序 = g["年"].astype(int) * 4 + g["季"]
        連續 = len(g) == 3 and 序.iloc[-1] - 序.iloc[0] == 2
        return g["單季"].sum() if 連續 and g["單季"].notna().all() else np.nan
    return e.groupby("code").apply(加總)


def 讀取興櫃最新():
    檔案們 = sorted((資料夾 / "esb").glob("*.csv.gz"))
    if not 檔案們:
        return None
    表 = pd.read_csv(檔案們[-1], dtype={"code": str})
    表["date"] = pd.to_datetime(表["date"])
    return 表


# ---------- 2. 技術指標 ----------
def _滾動(群, 欄, n, 方法="mean", 最少=None):
    return getattr(群[欄].rolling(n, min_periods=最少 or n), 方法)().reset_index(level=0, drop=True)


def _連續天數(條件, 代號):
    """每檔股票「條件連續成立」的天數，例如外資連買幾天。"""
    斷點 = (條件 != 條件.groupby(代號).shift()).cumsum()
    return 條件.astype(int).groupby([代號, 斷點]).cumsum()


def 計算指標(原始):
    表 = 原始.rename(columns={
        "name": "名稱", "close": "收盤", "change": "漲跌", "pe": "本益比",
        "dy": "殖利率", "pb": "淨值比", "market": "市場",
    })
    表["代號"] = 表["code"]
    群 = 表.groupby("code", sort=False)

    # 日報酬：交易所的「漲跌」是跟參考價比，除權息當天不會誤算成大跌
    前一天 = 表["收盤"] - 表["漲跌"]
    表["日報酬"] = (表["漲跌"] / 前一天).where(前一天 > 0)
    # 沒有漲跌資料（例如減資、暫停交易後恢復）時才用收盤價推算；
    # 超過 10% 漲跌停限制的變動通常是減資等公司行動，不算成真正的漲跌
    推算 = 群["收盤"].pct_change()
    推算 = 推算.where(推算.abs() <= 0.105, 0)
    表["日報酬"] = 表["日報酬"].fillna(推算).fillna(0).clip(-0.105, 0.105)
    # 還原股價：把除權息的影響補回去，回測才準
    表["還原價"] = np.exp(np.log1p(表["日報酬"]).groupby(表["code"]).cumsum())

    群 = 表.groupby("code", sort=False)
    for 天數 in (5, 10, 20, 60):
        表[f"MA{天數}"] = _滾動(群, "還原價", 天數)
    for 天數 in (3, 5, 10, 20, 30, 40):
        表[f"{天數}日漲幅"] = ((表["還原價"] / 群["還原價"].shift(天數) - 1) * 100).round(2)
    表["成交張數"] = (表["volume"] / 1000).round()
    表["5日均量"] = _滾動(群, "成交張數", 5).round()
    # 今天的量是前 5 天平均的幾倍（不含今天，爆量才看得出來）
    表["量對5日均"] = (表["成交張數"] / 群["5日均量"].shift().replace(0, np.nan)).round(2)
    # 均線「剛勾起來」：今天 5 日線往上，昨天還沒往上
    MA5昨 = 群["MA5"].shift()
    上揚 = 表["MA5"] > MA5昨
    表["MA5勾起"] = 上揚 & ~上揚.groupby(表["code"]).shift(fill_value=True)
    # 盤整箱型：前 20 個交易日（不含今天）的最高、最低價
    前高 = 群["high"].shift()
    前低 = 群["low"].shift()
    表["箱頂"] = 前高.groupby(表["code"]).rolling(20, min_periods=20).max().reset_index(level=0, drop=True)
    箱底 = 前低.groupby(表["code"]).rolling(20, min_periods=20).min().reset_index(level=0, drop=True)
    表["箱底"] = 箱底
    表["箱寬"] = ((表["箱頂"] / 箱底 - 1) * 100).round(1)
    # 下降趨勢的轉折：今天收盤跌破 10 日線，昨天還在線上
    在線下 = 表["還原價"] < 表["MA10"]
    表["剛跌破MA10"] = 在線下 & ~在線下.groupby(表["code"]).shift(fill_value=True)
    表["昨高"] = 前高
    表["振幅"] = ((表["high"] - 表["low"]) / 前一天.where(前一天 > 0) * 100).round(2)
    表["成交值億"] = (表["value"] / 1e8).round(2)
    表["量比"] = (表["volume"] / _滾動(群, "volume", 20)).round(2)
    表["距52週高點"] = ((表["還原價"] / _滾動(群, "還原價", 240, "max", 20) - 1) * 100).round(1)

    漲 = 表["日報酬"].clip(lower=0)
    跌 = (-表["日報酬"]).clip(lower=0)
    平均漲 = 漲.groupby(表["code"]).transform(lambda s: s.ewm(alpha=1 / 14, adjust=False).mean())
    平均跌 = 跌.groupby(表["code"]).transform(lambda s: s.ewm(alpha=1 / 14, adjust=False).mean())
    表["RSI"] = (100 - 100 / (1 + 平均漲 / 平均跌.replace(0, np.nan))).round(1)
    表["漲跌幅"] = (表["日報酬"] * 100).round(2)

    # 籌碼面（股數換成張數）
    if "total" in 表.columns:
        for 英, 中 in (("foreign", "外資買超"), ("trust", "投信買超"), ("dealer", "自營買超"), ("total", "法人買超")):
            表[中] = (表[英] / 1000).round()
        群 = 表.groupby("code", sort=False)
        表["法人5日買超"] = _滾動(群, "法人買超", 5, "sum", 1).round()
        表["法人10日買超"] = _滾動(群, "法人買超", 10, "sum", 1).round()
        表["外資連買"] = _連續天數(表["外資買超"] > 0, 表["code"])
        表["投信連買"] = _連續天數(表["投信買超"] > 0, 表["code"])
        表["融資餘額"] = 表["margin"]
        表["融資5日增減"] = ((表["margin"] / 群["margin"].shift(5) - 1) * 100).round(1)
    數字 = 表.select_dtypes("float64").columns
    表[數字] = 表[數字].astype("float32")
    return 表


# ---------- 3. 選股 ----------
def 加基本面(當日, 基本面):
    if 基本面 is None:
        return 當日
    return 當日.join(基本面, on="代號")


def 選股(當日, 條件):
    """當日：某一天所有股票的指標；條件：dict，空白(None)代表不設限。"""
    c = 條件
    結果 = 當日[當日["收盤"] > 0]
    if c.get("市場"):
        結果 = 結果[結果["市場"].isin(c["市場"])]
    if c.get("本益比上限") is not None:
        結果 = 結果[(結果["本益比"] > 0) & (結果["本益比"] <= c["本益比上限"])]
    if c.get("殖利率下限") is not None:
        結果 = 結果[結果["殖利率"] >= c["殖利率下限"]]
    if c.get("淨值比上限") is not None:
        結果 = 結果[(結果["淨值比"] > 0) & (結果["淨值比"] <= c["淨值比上限"])]
    for 鍵, 欄 in (("營收年增率下限", "營收年增率"), ("營收月增率下限", "營收月增率"),
                 ("累計營收年增率下限", "累計營收年增率"), ("EPS下限", "EPS")):
        if c.get(鍵) is not None and 欄 in 結果.columns:
            結果 = 結果[結果[欄] >= c[鍵]]
    if c.get("成交張數下限") is not None:
        結果 = 結果[結果["成交張數"] >= c["成交張數下限"]]
    if c.get("股價區間"):
        結果 = 結果[結果["收盤"].between(*c["股價區間"])]
    if c.get("站上均線"):
        結果 = 結果[結果["還原價"] > 結果[f"MA{c['站上均線']}"]]
    if c.get("均線多頭排列"):
        結果 = 結果[(結果["MA5"] > 結果["MA20"]) & (結果["MA20"] > 結果["MA60"])]
    if c.get("20日漲幅下限") is not None:
        結果 = 結果[結果["20日漲幅"] >= c["20日漲幅下限"]]
    if c.get("RSI區間"):
        結果 = 結果[結果["RSI"].between(*c["RSI區間"])]
    if c.get("量比下限") is not None:
        結果 = 結果[結果["量比"] >= c["量比下限"]]
    for 鍵, 欄 in (("外資連買下限", "外資連買"), ("投信連買下限", "投信連買"), ("法人5日買超下限", "法人5日買超")):
        if c.get(鍵) is not None and 欄 in 結果.columns:
            結果 = 結果[結果[欄] >= c[鍵]]
    if c.get("融資5日增減上限") is not None and "融資5日增減" in 結果.columns:
        結果 = 結果[結果["融資5日增減"] <= c["融資5日增減上限"]]
    # ----- 烏賊課程用到的條件 -----
    if any(c.get(k) is not None for k in ("股本上限", "週轉率下限")) and "股本億" not in 結果.columns:
        結果 = 結果.join(_股本表(), on="代號")
    if "股本億" in 結果.columns and "發行股數" in 結果.columns:
        結果 = 結果.assign(週轉率=(結果["volume"] / 結果["發行股數"] * 100).round(2))
    for 天數, 下限, 上限 in c.get("區間漲跌幅") or []:  # 近 N 日漲跌幅介於下限與上限之間
        if 下限 is not None:
            結果 = 結果[結果[f"{天數}日漲幅"] > 下限]
        if 上限 is not None:
            結果 = 結果[結果[f"{天數}日漲幅"] < 上限]
    if c.get("週轉率下限") is not None and "週轉率" in 結果.columns:
        結果 = 結果[結果["週轉率"] > c["週轉率下限"]]
    if c.get("股本上限") is not None and "股本億" in 結果.columns:
        結果 = 結果[結果["股本億"] < c["股本上限"]]
    if c.get("量對5日均下限") is not None:
        結果 = 結果[結果["量對5日均"] > c["量對5日均下限"]]
    if c.get("收盤低於MA5"):
        結果 = 結果[結果["還原價"] < 結果["MA5"]]
    if c.get("法人10日賣超下限") is not None and "法人10日買超" in 結果.columns:
        結果 = 結果[結果["法人10日買超"] < -c["法人10日賣超下限"]]
    if c.get("近三季EPS下限") is not None and "近三季EPS" in 結果.columns:
        結果 = 結果[結果["近三季EPS"] > c["近三季EPS下限"]]
    if c.get("營收創新高") and "營收創新高" in 結果.columns:
        結果 = 結果[結果["營收創新高"] == True]  # noqa: E712
    if c.get("剛跌破MA10"):
        結果 = 結果[結果["剛跌破MA10"] == True]  # noqa: E712
    if c.get("跌破箱底"):
        結果 = 結果[(結果["收盤"] < 結果["箱底"]) & (結果["箱寬"] <= 25)]
    if c.get("空頭排列"):
        結果 = 結果[(結果["還原價"] < 結果["MA5"]) & (結果["MA5"] < 結果["MA10"])]
    if c.get("過濾低價低量"):  # 講義：過濾股價 5 元以下、五日均量 500 張以下
        結果 = 結果[(結果["收盤"] >= 5) & (結果["5日均量"] >= 500)]
    if c.get("排除ETF", True):
        結果 = 結果[~結果["代號"].str.startswith("00")]
    欄, 由小到大 = 排序方式[c.get("排序", "殖利率 高→低")]
    if 欄 not in 結果.columns:
        return 結果
    return 結果.sort_values(欄, ascending=由小到大, na_position="last")


def _股本表():
    f = 資料夾 / "fundamental" / "capital.csv"
    if not f.exists():
        return pd.DataFrame(columns=["股本億", "發行股數", "產業"])
    return _讀股本(f.stat().st_mtime)  # 檔案更新後自動重讀


@lru_cache(maxsize=1)
def _讀股本(_更新時間):
    c = pd.read_csv(資料夾 / "fundamental" / "capital.csv", dtype={"code": str, "industry": str})
    c = c.drop_duplicates("code", keep="last").set_index("code")
    return pd.DataFrame({"股本億": (c["capital"] / 1e8).round(2), "發行股數": c["shares"],
                         "產業": c["industry"].fillna("") if "industry" in c else ""})


# 烏賊 0530 課程「如何選股」的五組條件（原本在 MoneyDJ 選股大師設定）
烏賊條件 = {
    "烏賊條件（一）短線活躍小型股": {
        "方向": "多",
        "說明": "近 20 日漲跌幅 > 10%、今日週轉率 > 10%、股本 < 20 億；過濾股價 5 元以下、五日均量 500 張以下",
        "條件": {"區間漲跌幅": [(20, 10, None)], "週轉率下限": 10, "股本上限": 20, "過濾低價低量": True,
               "排序": "週轉率 高→低"},
    },
    "烏賊條件（二）量增、近月未漲": {
        "方向": "多",
        "說明": "今日量 > 五日均量 1.2 倍、近 30 日漲跌幅 < 1%；過濾低價低量；再看外資與投信動向",
        "條件": {"量對5日均下限": 1.2, "區間漲跌幅": [(30, None, 1)], "過濾低價低量": True,
               "排序": "法人5日買超 多→少"},
    },
    "烏賊條件（三）爆量起漲": {
        "方向": "多",
        "說明": "近 10 日漲跌幅 > 1%、今日量 > 五日均量 3 倍、今日量 > 100 張、股本 < 30 億；不過濾低價低量",
        "條件": {"區間漲跌幅": [(10, 1, None)], "量對5日均下限": 3, "成交張數下限": 100, "股本上限": 30,
               "排序": "量比 高→低"},
    },
    "烏賊條件（四）強勢股拉回": {
        "方向": "多",
        "說明": "收盤 < 5 日均線、近 40 日漲跌幅 > 30%、近 10 日三大法人賣超 > 10000 張；過濾低價低量",
        "條件": {"收盤低於MA5": True, "區間漲跌幅": [(40, 30, None)], "法人10日賣超下限": 10000,
               "過濾低價低量": True, "排序": "20日漲幅 高→低"},
    },
    "烏賊條件（五）低價成長股": {
        "方向": "多",
        "說明": "股價 < 50 元、近三季 EPS 合計 > 0.5 元、最新月營收創歷史新高、月營收年增率 > 20%；不過濾低價低量",
        "條件": {"股價區間": (0, 49.99), "近三季EPS下限": 0.5, "營收創新高": True, "營收年增率下限": 20,
               "排序": "營收年增率 高→低"},
    },
    "烏賊空方（一）跌破十日線": {
        "方向": "空",
        "說明": "講義「下降趨勢」：今天收盤剛跌破 10 日線（昨天還在線上），且 5 日線在 10 日線之下；過濾低價低量",
        "條件": {"剛跌破MA10": True, "空頭排列": True, "過濾低價低量": True, "排序": "量比 高→低"},
    },
    "烏賊空方（二）跌破盤整箱底": {
        "方向": "空",
        "說明": "講義「盤整格局」反向：前 20 日箱型盤整（高低差 25% 內），今天收盤跌破箱底且量大於前 5 日均量 1.5 倍",
        "條件": {"跌破箱底": True, "量對5日均下限": 1.5, "過濾低價低量": True, "排序": "量比 高→低"},
    },
    "烏賊空方（三）三&五日弱勢": {
        "方向": "空",
        "說明": "講義「每日功課」弱勢股：近 3 日、5 日都下跌超過 5%，收盤 < 5 日線 < 10 日線；過濾低價低量",
        "條件": {"區間漲跌幅": [(3, None, -5), (5, None, -5)], "空頭排列": True, "過濾低價低量": True,
               "排序": "20日漲幅 高→低"},
    },
}


def 烏賊總覽(今日):
    """每個烏賊策略今天符合幾檔，以及同時符合多個策略的股票。"""
    總表, 名單 = [], {}
    for 名, 設定 in 烏賊條件.items():
        結果 = 選股(今日, dict(設定["條件"], 排除ETF=True))
        名單[名] = 結果
        總表.append({"策略": 名, "多空": 設定["方向"], "符合檔數": len(結果), "說明": 設定["說明"]})
    總表 = pd.DataFrame(總表)
    出現 = pd.concat([pd.DataFrame({"代號": r["代號"], "策略": 名, "多空": 烏賊條件[名]["方向"]})
                    for 名, r in 名單.items() if len(r)] or [pd.DataFrame(columns=["代號", "策略", "多空"])])
    次數 = 出現.groupby("代號").agg(符合策略數=("策略", "size"),
                                  符合策略=("策略", lambda s: "、".join(x.replace("烏賊", "") for x in s)),
                                  多空=("多空", lambda s: "多空都有" if s.nunique() > 1 else s.iloc[0]))
    重複 = 次數[次數["符合策略數"] >= 2].join(今日.set_index("代號")[["名稱", "收盤", "漲跌幅"]])
    重複 = 重複.reset_index().sort_values("符合策略數", ascending=False)
    總表["重複檔數"] = [int(r["代號"].isin(重複["代號"]).sum()) for r in 名單.values()]
    return 總表, 名單, 重複[["代號", "名稱", "收盤", "漲跌幅", "多空", "符合策略數", "符合策略"]]


def 每日功課(今日, 檔數=20):
    """講義「每天的功課」六張榜單。"""
    表 = 今日[(今日["收盤"] > 0) & ~今日["代號"].str.startswith("00")].copy()
    表["3&5日"] = 表["3日漲幅"].fillna(0) + 表["5日漲幅"].fillna(0)
    # 三&五日強勢股的重點：貼近 5 日或 10 日線（±3% 內）且 5 日線往上，最好是剛勾起來
    貼近 = ((表["還原價"] / 表["MA5"] - 1).abs() <= 0.03) | ((表["還原價"] / 表["MA10"] - 1).abs() <= 0.03)
    表["重點"] = np.where(貼近 & 表["MA5勾起"], "★ 剛勾起", np.where(貼近 & (表["MA5"] > 0), "貼近均線", ""))
    強 = 表[(表["3日漲幅"] > 0) & (表["5日漲幅"] > 0)].nlargest(檔數, "3&5日")
    弱 = 表[(表["3日漲幅"] < 0) & (表["5日漲幅"] < 0)].nsmallest(檔數, "3&5日")
    return {
        "三&五日強勢股": 強, "三&五日弱勢股": 弱,
        "量大股": 表.nlargest(檔數, "成交張數"), "大幅震盪股": 表[表["成交張數"] >= 500].nlargest(檔數, "振幅"),
        "強勢股": 表.nlargest(檔數, "漲跌幅"), "弱勢股": 表.nsmallest(檔數, "漲跌幅"),
    }


# ---------- 4. 回測 ----------
def 回測(指標, 條件, 開始, 結束, 最多檔數=10, 調倉="每月", 停損=None, 停利=None,
       初始資金=1_000_000):
    """
    規則：每週或每月最後一個交易日收盤後選股，隔一個交易日以收盤價買進，
    每檔投入「總資產 ÷ 最多檔數」。沒入選的持股賣出；
    持有期間跌破停損或達到停利，當天收盤賣出，資金等下次調倉再投入。
    """
    區間 = 指標[(指標["date"] >= 開始) & (指標["date"] <= 結束)]
    if 區間.empty:
        return None
    報酬表 = 區間.pivot(index="date", columns="code", values="日報酬").fillna(0)
    收盤表 = 區間.pivot(index="date", columns="code", values="收盤")
    還原表 = 區間.pivot(index="date", columns="code", values="還原價")
    名稱 = 區間.drop_duplicates("code", keep="last").set_index("code")["名稱"]
    日期們 = 報酬表.index
    依日期 = {d: g for d, g in 區間.groupby("date")}

    if 調倉 == "每日":
        訊號日 = set(日期們)
    else:
        期別 = 日期們.to_period("W" if 調倉 == "每週" else "M")
        訊號日 = set(日期們[np.r_[期別[1:] != 期別[:-1], True]])
    訊號日.add(日期們[0])

    現金 = float(初始資金)
    持股 = {}   # 代號 -> {市值, 進場日, 進場價, 進場還原價}
    待買 = None
    資產曲線, 交易紀錄 = [], []

    def 賣出(代號, 日, 原因):
        nonlocal 現金
        部位 = 持股.pop(代號)
        現金 += 部位["市值"] * (1 - 手續費率 - 證交稅率)
        交易紀錄.append({
            "代號": 代號, "名稱": 名稱.get(代號, ""),
            "進場日": 部位["進場日"].date(), "進場價": 部位["進場價"],
            "出場日": 日.date(), "出場價": 收盤表.at[日, 代號],
            "報酬率(%)": round((還原表.at[日, 代號] / 部位["進場還原價"] * (1 - 手續費率) ** 2
                              * (1 - 證交稅率) - 1) * 100, 2),
            "出場原因": 原因,
        })

    for 日 in 日期們:
        今日報酬 = 報酬表.loc[日]
        for 部位 in 持股.values():
            部位["市值"] *= 1 + 今日報酬[部位["代號"]]

        if 待買 is not None:
            for 代號 in [k for k in 持股 if k not in 待買]:
                if pd.notna(收盤表.at[日, 代號]):
                    賣出(代號, 日, "調倉")
            總資產 = 現金 + sum(p["市值"] for p in 持股.values())
            每檔金額 = 總資產 / 最多檔數
            for 代號 in 待買:
                if 代號 in 持股 or pd.isna(收盤表.at[日, 代號]) or 現金 < 每檔金額 * 0.5:
                    continue
                投入 = min(每檔金額, 現金)
                現金 -= 投入
                持股[代號] = {"代號": 代號, "市值": 投入 * (1 - 手續費率), "進場日": 日,
                            "進場價": 收盤表.at[日, 代號], "進場還原價": 還原表.at[日, 代號]}
            待買 = None

        for 代號 in list(持股):
            部位 = 持股[代號]
            if pd.isna(收盤表.at[日, 代號]):
                continue
            漲跌 = 還原表.at[日, 代號] / 部位["進場還原價"] - 1
            if 停損 is not None and 漲跌 <= -停損 / 100:
                賣出(代號, 日, "停損")
            elif 停利 is not None and 漲跌 >= 停利 / 100:
                賣出(代號, 日, "停利")

        if 日 in 訊號日 and 日 != 日期們[-1]:
            待買 = list(選股(依日期[日], 條件)["代號"].head(最多檔數))

        資產曲線.append((日, 現金 + sum(p["市值"] for p in 持股.values())))

    最後一天 = 日期們[-1]
    for 代號, 部位 in 持股.items():
        交易紀錄.append({
            "代號": 代號, "名稱": 名稱.get(代號, ""), "進場日": 部位["進場日"].date(),
            "進場價": 部位["進場價"], "出場日": None, "出場價": 收盤表.at[最後一天, 代號],
            "報酬率(%)": round((還原表.at[最後一天, 代號] / 部位["進場還原價"] - 1) * 100, 2),
            "出場原因": "仍持有",
        })

    曲線 = pd.Series(dict(資產曲線)) / 初始資金
    基準 = None
    if "0050" in 報酬表.columns:
        基準 = (1 + 報酬表["0050"]).cumprod()
    交易表 = pd.DataFrame(交易紀錄)
    return {"曲線": 曲線, "基準": 基準, "交易": 交易表, "績效": 計算績效(曲線, 交易表, 基準)}


def 計算績效(曲線, 交易表, 基準):
    年數 = max((曲線.index[-1] - 曲線.index[0]).days / 365.25, 1 / 365)
    日報酬 = 曲線.pct_change().dropna()
    已出場 = 交易表[交易表["出場原因"] != "仍持有"] if not 交易表.empty else 交易表
    績效 = {
        "總報酬(%)": (曲線.iloc[-1] - 1) * 100,
        "年化報酬(%)": (曲線.iloc[-1] ** (1 / 年數) - 1) * 100,
        "最大回撤(%)": ((曲線 / 曲線.cummax()) - 1).min() * 100,
        "夏普值": 日報酬.mean() / 日報酬.std() * np.sqrt(252) if 日報酬.std() > 0 else 0.0,
        "勝率(%)": (已出場["報酬率(%)"] > 0).mean() * 100 if len(已出場) else 0.0,
        "交易次數": len(已出場),
    }
    if 基準 is not None:
        績效["0050 同期報酬(%)"] = (基準.iloc[-1] - 1) * 100
    return 績效


# ---------- 5. 我的庫存 ----------
def 讀取匯率():
    檔案 = 資料夾 / "fx.csv"
    if not 檔案.exists():
        return None
    return pd.read_csv(檔案, parse_dates=["date"]).sort_values("date")


def _升降單位(價):
    return 0.01 if 價 < 10 else 0.05 if 價 < 50 else 0.1 if 價 < 100 else 0.5 if 價 < 500 else 1 if 價 < 1000 else 5


def 漲跌停價(昨收):
    """台股漲跌幅 10%，依升降單位取到有效價位（漲停往下取、跌停往上取）。"""
    if not 昨收 or pd.isna(昨收) or 昨收 <= 0:
        return np.nan, np.nan
    上 = 昨收 * 1.1
    單位 = _升降單位(上)
    上 = np.floor(上 / 單位 + 1e-9) * 單位
    下 = 昨收 * 0.9
    單位 = _升降單位(下)
    下 = np.ceil(下 / 單位 - 1e-9) * 單位
    return round(上, 2), round(下, 2)


def 排行資料(今日):
    """今日所有上市櫃股票（不含 ETF），給排行榜用。"""
    表 = 今日.rename(columns={"名稱": "name", "收盤": "close", "漲跌": "change"})
    表 = 表[~表["code"].str.startswith("00") & (表["close"] > 0)].copy()
    表["昨收"] = 表["close"] - 表["change"]
    表["幅度"] = 表["change"] / 表["昨收"] * 100
    表["張數"] = 表["volume"] / 1000
    表["成交金額億"] = 表["value"] / 1e8
    停 = 表["昨收"].map(漲跌停價)
    表["漲停價"], 表["跌停價"] = 停.str[0], 停.str[1]
    表["漲停"] = (表["close"] >= 表["漲停價"] - 1e-6) & (表["幅度"] > 9)
    表["跌停"] = (表["close"] <= 表["跌停價"] + 1e-6) & (表["幅度"] < -9)
    if "發行股數" not in 表.columns:
        表 = 表.join(_股本表()[["發行股數"]], on="code")
    表["週轉率"] = 表["volume"] / 表["發行股數"] * 100
    return 表


def 鎖死分析(分K, 停價, 方向="漲"):
    """用 1 分鐘線找漲跌停的首次觸及時間、最後鎖死時間、中間打開次數。"""
    if 分K is None or 分K.empty or pd.isna(停價):
        return None
    if 方向 == "漲":
        碰 = 分K["high"] >= 停價 - 1e-6
        鎖 = 分K["low"] >= 停價 - 1e-6
    else:
        碰 = 分K["low"] <= 停價 + 1e-6
        鎖 = 分K["high"] <= 停價 + 1e-6
    if not 碰.any():
        return None
    首次 = 分K.loc[碰.idxmax(), "datetime"]
    鎖死 = None
    if 鎖.iloc[-1]:
        未鎖 = (~鎖).to_numpy().nonzero()[0]
        起 = 未鎖[-1] + 1 if len(未鎖) else 0
        鎖死 = 分K["datetime"].iloc[起]
    段 = 鎖.astype(int).diff().fillna(鎖.astype(int).iloc[0])
    打開 = int(max((段 == -1).sum(), 0))
    return {"首次": 首次.strftime("%H:%M"), "鎖死": 鎖死.strftime("%H:%M") if 鎖死 is not None else None, "打開": 打開}


def 讀取上櫃最新():
    檔案們 = sorted((資料夾 / "otc").glob("*.csv.gz"))
    if not 檔案們:
        return None
    表 = pd.read_csv(檔案們[-1], dtype={"code": str})
    表["date"] = pd.to_datetime(表["date"])
    return 表


def 計算庫存(持股, 最新行情, *其他報價):
    """持股：DataFrame（代號、股數、總成本）。其他報價：例如興櫃。回傳每檔明細與合計。"""
    最新行情 = 最新行情.rename(columns={"名稱": "name", "收盤": "close", "漲跌": "change"})
    報價 = 最新行情[["code", "name", "date", "close", "change"]]
    for 其他 in 其他報價:
        if 其他 is not None:
            報價 = pd.concat([其他[["code", "name", "date", "close", "change"]], 報價])
    報價 = 報價.dropna(subset=["close"]).sort_values("date", kind="stable").drop_duplicates("code", keep="last").set_index("code")

    表 = 持股.copy()
    表["代號"] = 表["代號"].astype(str).str.strip()
    表 = 表.join(報價, on="代號")
    表["名稱"] = 表["name"].fillna(表["代號"] + "（待報價）")
    表["股價"] = 表["close"]
    表["漲跌幅"] = (表["change"] / (表["close"] - 表["change"]) * 100).round(2)
    表["今日損益"] = (表["change"] * 表["股數"]).round()
    表["股票市值"] = (表["close"] * 表["股數"]).round()
    表["總損益"] = 表["股票市值"] - 表["總成本"]
    表["報酬率(%)"] = (表["總損益"] / 表["總成本"] * 100).round(2)
    表["均價"] = (表["總成本"] / 表["股數"]).round(2)
    表["報價日期"] = 表["date"].dt.strftime("%m/%d")

    有報價 = 表[表["股價"].notna()]
    昨日市值 = ((有報價["close"] - 有報價["change"]) * 有報價["股數"]).sum()
    合計 = {
        "今日損益": 有報價["今日損益"].sum(),
        "今日損益(%)": 有報價["今日損益"].sum() / 昨日市值 * 100 if 昨日市值 else 0.0,
        "累積損益": 有報價["總損益"].sum(),
        "累積損益(%)": 有報價["總損益"].sum() / 有報價["總成本"].sum() * 100 if len(有報價) else 0.0,
        "股票市值": 有報價["股票市值"].sum(),
        "總成本": 表["總成本"].sum(),
        "日期": 有報價["date"].max(),
        "缺報價": 表.loc[表["股價"].isna(), "代號"].tolist(),
    }
    欄 = ["名稱", "今日損益", "股價", "漲跌幅", "總損益", "報酬率(%)", "股數", "均價", "總成本", "代號", "報價日期"]
    return 表.sort_values("今日損益", ascending=False, na_position="last")[欄], 合計


# ---------- 6. 個股回測 ----------
個股策略 = {
    "買進持有": "第一天買進，一直持有到最後一天",
    "均線交叉": "短均線由下往上穿過長均線時買進，由上往下穿過時賣出",
    "站上均線": "收盤價站上均線時買進，跌破均線時賣出",
    "RSI 超賣反彈": "RSI 低於下限時買進，高於上限時賣出",
    "盤整突破（烏賊）": "前 20 日箱型盤整（高低差 25% 以內），收盤突破箱頂且量大於五日均量 1.5 倍時買進；跌破十日線賣出",
    "均線勾起（烏賊）": "股價貼近 5 日或 10 日線（3% 以內）且 5 日線剛勾起時買進；跌破十日線賣出",
}


def 個股回測(指標, 代號, 開始, 結束, 策略="均線交叉", 短=5, 長=20, RSI下限=30, RSI上限=70,
          停損=None, 停利=None, 初始資金=1_000_000):
    """訊號在收盤後產生，隔一個交易日收盤價成交。"""
    表 = 指標[(指標["代號"] == 代號) & (指標["date"] >= 開始) & (指標["date"] <= 結束)].copy()
    if len(表) < 2:
        return None
    全部 = 指標[指標["代號"] == 代號]
    均 = lambda n: 全部["還原價"].rolling(n).mean().reindex(表.index)
    if 策略 == "買進持有":
        想持有 = pd.Series(True, index=表.index)
    elif 策略 == "均線交叉":
        想持有 = 均(短) > 均(長)
    elif 策略 == "站上均線":
        想持有 = 表["還原價"] > 均(長)
    elif 策略 == "RSI 超賣反彈":  # 低於下限進場，高於上限出場，中間維持原狀
        想持有 = _進出狀態(表["RSI"] < RSI下限, 表["RSI"] > RSI上限)
    else:  # 烏賊課程：進場條件各自不同，出場都是跌破十日線
        if 策略 == "盤整突破（烏賊）":
            進 = (表["收盤"] > 表["箱頂"]) & (表["箱寬"] <= 25) & (表["量對5日均"] >= 1.5)
        else:
            貼近 = ((表["還原價"] / 表["MA5"] - 1).abs() <= 0.03) | ((表["還原價"] / 表["MA10"] - 1).abs() <= 0.03)
            進 = 貼近 & 表["MA5勾起"].astype(bool)
        想持有 = _進出狀態(進, 表["還原價"] < 表["MA10"])

    現金, 股數價值, 持有中 = float(初始資金), 0.0, False
    進場 = None
    待執行, 等重設 = None, False
    曲線, 交易 = [], []
    for i, (索引, r) in enumerate(表.iterrows()):
        if 持有中:
            股數價值 *= 1 + r["日報酬"]
        if 待執行 == "買" and not 持有中:
            股數價值, 現金, 持有中 = 現金 * (1 - 手續費率), 0.0, True
            進場 = (r["date"], r["收盤"], r["還原價"])
        elif 待執行 == "賣" and 持有中:
            現金, 股數價值, 持有中 = 股數價值 * (1 - 手續費率 - 證交稅率), 0.0, False
            交易.append(_紀錄(進場, r, "訊號出場"))
        待執行 = None
        if 持有中:
            漲跌 = r["還原價"] / 進場[2] - 1
            原因 = "停損" if 停損 and 漲跌 <= -停損 / 100 else ("停利" if 停利 and 漲跌 >= 停利 / 100 else None)
            if 原因:
                現金, 股數價值, 持有中 = 股數價值 * (1 - 手續費率 - 證交稅率), 0.0, False
                交易.append(_紀錄(進場, r, 原因))
                等重設 = True
        if not 想持有.loc[索引]:
            等重設 = False  # 停損停利出場後，要等訊號先消失再出現才再進場
        if i < len(表) - 1:
            if 想持有.loc[索引] and not 持有中 and not 等重設:
                待執行 = "買"
            elif not 想持有.loc[索引] and 持有中:
                待執行 = "賣"
        曲線.append((r["date"], 現金 + 股數價值))
    if 持有中:
        交易.append(_紀錄(進場, 表.iloc[-1], "仍持有"))

    曲線 = pd.Series(dict(曲線)) / 初始資金
    基準 = 表.set_index("date")["還原價"] / 表["還原價"].iloc[0]
    交易表 = pd.DataFrame(交易)
    績效 = 計算績效(曲線, 交易表, None)
    績效["買進持有(%)"] = (基準.iloc[-1] - 1) * 100
    return {"曲線": 曲線, "基準": 基準, "交易": 交易表, "績效": 績效, "價格": 表}


def _進出狀態(進場, 出場):
    狀態, 序列 = False, []
    for 進, 出 in zip(進場.fillna(False), 出場.fillna(False)):
        if 進 and not 狀態:
            狀態 = True
        elif 出:
            狀態 = False
        序列.append(狀態)
    return pd.Series(序列, index=進場.index)


def _紀錄(進場, r, 原因):
    return {"進場日": 進場[0].date(), "進場價": 進場[1], "出場日": r["date"].date(), "出場價": r["收盤"],
            "報酬率(%)": round((r["還原價"] / 進場[2] * (1 - 手續費率) ** 2 * (1 - 證交稅率) - 1) * 100, 2),
            "出場原因": 原因}


# ---------- 7. 盤中即時報價 ----------
def 盤中時間():
    現在 = pd.Timestamp.now(tz="Asia/Taipei")
    return 現在.weekday() < 5 and (9, 0) <= (現在.hour, 現在.minute) <= (13, 35)


def 即時報價(代號們, 市場對照):
    """證交所基本市況報導（延遲約 5 到 20 秒）。回傳 DataFrame：code, name, close, change, time。
    代號 t00 是加權指數。"""
    import requests

    頻道 = []
    for 代號 in 代號們:
        前綴 = "otc" if 市場對照.get(代號) == "上櫃" else "tse"
        頻道.append(f"{前綴}_{代號}.tw")
    結果 = []
    for i in range(0, len(頻道), 40):
        網址 = ("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?json=1&delay=0&ex_ch="
              + "|".join(頻道[i:i + 40]))
        r = requests.get(網址, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        for m in r.json().get("msgArray", []):
            昨收 = _數(m.get("y"))
            現價 = _數(m.get("z"))
            if pd.isna(現價):  # 這段時間沒成交，用最佳買價
                現價 = _數(str(m.get("b", "")).split("_")[0])
            結果.append({"code": m.get("c"), "name": m.get("n"), "close": 現價,
                       "change": 現價 - 昨收, "time": m.get("t"),
                       "date": pd.Timestamp(m.get("d", "")) if m.get("d") else pd.NaT})
    return pd.DataFrame(結果)


def _數(值):
    try:
        return float(值)
    except (TypeError, ValueError):
        return float("nan")


# ---------- 8. 個股查詢用：盤中 K 線、週月季 K、MACD、內部人 ----------
def 盤中K線(代號, 市場="上市", 間隔="1m", 範圍="5d"):
    """Yahoo 奇摩股市的分鐘線（盤中約延遲數分鐘）。代號 t00 代表加權指數。
    回傳 DataFrame：datetime（台北時間）、open、high、low、close、volume（股）。"""
    import requests

    符號 = "%5ETWII" if 代號 == "t00" else f"{代號}.{'TWO' if 市場 == '上櫃' else 'TW'}"
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{符號}?interval={間隔}&range={範圍}",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    結果 = r.json()["chart"]["result"][0]
    if not 結果.get("timestamp"):
        return None
    報價 = 結果["indicators"]["quote"][0]
    表 = pd.DataFrame({"datetime": pd.to_datetime(結果["timestamp"], unit="s", utc=True)
                       .tz_convert("Asia/Taipei").tz_localize(None),
                       **{k: 報價.get(k) for k in ("open", "high", "low", "close", "volume")}})
    表 = 表.dropna(subset=["close"])
    表 = 表[表["datetime"].dt.time <= pd.Timestamp("13:30").time()]  # 去掉收盤後的試撮
    昨收 = 結果["meta"].get("chartPreviousClose")
    表.attrs["昨收"] = 昨收
    return 表


def 週期K線(歷史, 週期):
    """把日 K 合併成週 K、月 K、季 K（籌碼加總、價格用原始股價）。"""
    規則 = {"週": "W-FRI", "月": "ME", "季": "QE"}[週期]
    加總 = {c: "sum" for c in ("成交張數", "法人買超", "外資買超", "投信買超", "自營買超") if c in 歷史.columns}
    其他 = {"open": "first", "high": "max", "low": "min", "收盤": "last", "還原價": "last"}
    if "融資餘額" in 歷史.columns:
        其他["融資餘額"] = "last"
    表 = 歷史.set_index("date").resample(規則).agg({**其他, **加總}).dropna(subset=["收盤"]).reset_index()
    return 表


def MACD(收盤, 快=12, 慢=26, 訊號=9):
    快線 = 收盤.ewm(span=快, adjust=False).mean()
    慢線 = 收盤.ewm(span=慢, adjust=False).mean()
    DIF = 快線 - 慢線
    DEA = DIF.ewm(span=訊號, adjust=False).mean()
    return DIF, DEA, DIF - DEA


def RSI(收盤, n=14):
    變動 = 收盤.diff()
    漲 = 變動.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    跌 = (-變動).clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + 漲 / 跌.replace(0, np.nan))


def 讀取內部人(代號):
    """每月董監、經理人、大股東持股合計；回傳這檔的歷史（月份、內部人持股、董監持股、設質）。"""
    f = 資料夾 / "fundamental" / "insider.csv"
    if not f.exists():
        return None
    表 = pd.read_csv(f, dtype={"code": str})
    表 = 表[表["code"] == str(代號)].sort_values("month")
    return 表 if len(表) else None


# ========== 9. AI 新聞彙整與投資觀點 ==========
AI系統提示 = """你是台灣股市的研究助理，替一位個人投資者整理單一個股的市場資訊。
請一律使用繁體中文（台灣用語）。

工作方式：
1. 用網路搜尋找這家公司近六個月的資訊：新聞、月營收與財報、法說會重點、
   券商或投顧的研究報告與目標價（多半只能看到新聞引述的摘要）、產業動態、重大訊息。
   優先採用鉅亨網、經濟日報、工商時報、MoneyDJ、公開資訊觀測站等可靠來源，並注意日期，舊聞不要當新聞。
2. 結合使用者提供的最新股價、基本面、籌碼與技術面數據（這些數據是正確的，以它為準）。
3. 輸出 Markdown，依序包含以下段落（用 ### 標題）：
   ### 一句話結論
   ### 近半年重要消息（依時間由新到舊，條列，每條註明月份）
   ### 法人與券商觀點（目標價、評等；找不到就說找不到，不要編造）
   ### 目標價與預估本益比
       用表格列出：法人／券商目標價（註明券商與日期，找不到就寫「未找到」）、
       今年與明年預估 EPS（優先用券商或法說會預估；沒有就依近幾季 EPS 與營收成長自行估算並註明「自行估算」）、
       以目前股價換算的預估本益比，以及用「預估 EPS × 合理本益比區間」（參考使用者提供的歷史本益比區間）
       推算的目標價區間（保守／合理／樂觀三檔），並說明假設。
   ### 利多因素
   ### 利空與風險
   ### 數據面解讀（基本面、籌碼、技術面）
   ### 投資建議（短線 1 個月內、中期 3–6 個月各一段，給出偏多/中性/偏空的看法，
       以及可參考的支撐、壓力或停損價位，說明理由）
4. 不確定的事要說不確定；沒有來源支持的數字不要寫。
5. 報告最後寫：「以上為 AI 彙整的公開資訊，僅供參考，不構成投資建議。」
6. 在最後面另外附上一個 ```json 程式碼區塊，整理成網站卡片用的資料（數字填純數字，不知道填 null）：
   {"看法": "偏多/中性/偏空", "一句話": "30 字內結論", "短線": "偏多/中性/偏空", "中期": "偏多/中性/偏空",
    "券商目標價": 數字, "目標價保守": 數字, "目標價合理": 數字, "目標價樂觀": 數字,
    "今年EPS": 數字, "明年EPS": 數字, "預估本益比": 數字, "支撐": 數字, "壓力": 數字, "停損": 數字}"""


def AI分析(代號, 名稱, 數據摘要, api_key, 模型="claude-opus-5-5", 搜尋次數=8):
    """請 Claude 上網搜尋近半年新聞與法人報告，彙整後給出觀點。回傳 (Markdown 內文, 來源清單)。"""
    import anthropic

    客戶端 = anthropic.Anthropic(api_key=api_key)
    今天 = (pd.Timestamp.now(tz="Asia/Taipei")).strftime("%Y-%m-%d")
    訊息們 = [{"role": "user", "content": (
        f"今天是 {今天}。請分析台股 {代號} {名稱}。\n\n"
        f"以下是我資料庫裡的最新數據：\n{數據摘要}\n\n"
        "請搜尋近六個月的新聞與法人報告後，依照指定格式彙整並給出投資建議。")}]
    參數 = dict(
        model=模型, max_tokens=16000, system=AI系統提示,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        thinking={"type": "adaptive"}, output_config={"effort": "medium"},
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 搜尋次數,
                "user_location": {"type": "approximate", "country": "TW", "timezone": "Asia/Taipei"}}],
    )
    for _ in range(5):
        回應 = 客戶端.beta.messages.create(messages=訊息們, **參數)
        if 回應.stop_reason != "pause_turn":  # 搜尋太久會暫停，接著送回去讓它繼續
            break
        訊息們 = 訊息們 + [{"role": "assistant", "content": 回應.content}]
    if 回應.stop_reason == "refusal":
        raise RuntimeError("AI 拒絕回答這個請求，請換一檔或稍後再試。")

    內文, 來源 = [], {}
    for 區塊 in 回應.content:
        if 區塊.type == "text":
            內文.append(區塊.text)
            for 引用 in getattr(區塊, "citations", None) or []:
                網址 = getattr(引用, "url", None)
                if 網址 and 網址 not in 來源:
                    來源[網址] = getattr(引用, "title", None) or 網址
    文字 = "".join(內文).strip()
    if not 文字:
        raise RuntimeError("AI 沒有產生內容，請稍後再試。")
    return 文字, list(來源.items())


def 拆解AI建議(文字):
    """把報告最後的 json 區塊拆出來做卡片；回傳 (給人看的內文, 建議 dict 或 None)。舊報告沒有 json 就只抓一句話結論。"""
    import json, re
    建議 = None
    配 = re.search(r"```json\s*(\{.*?\})\s*```", 文字, re.S)
    if 配:
        try:
            建議 = json.loads(配.group(1))
        except Exception:
            建議 = None
        文字 = (文字[: 配.start()] + 文字[配.end():]).strip()
    if 建議 is None and isinstance(文字, str):
        結 = re.search(r"###\s*一句話結論\s*\n+(.+?)(?:\n\s*\n|\n#|$)", 文字, re.S)
        if 結:
            一句 = 結.group(1).strip()
            看法 = next((k for k in ("偏多", "偏空", "中性") if k in 一句), None)
            建議 = {"一句話": 一句, "看法": 看法}
    return 文字, 建議


def AI補卡片(報告, 引擎, 金鑰, 模型):
    """舊報告沒有卡片資料：請 AI 只從報告內容整理出卡片用的 json（不上網，很快）。"""
    import json, re
    提示 = ("以下是一份台股 AI 分析報告。請只根據報告內容，輸出一個 ```json 程式碼區塊，欄位如下"
           "（數字填純數字，報告沒提到填 null，不要編造）：\n"
           '{"看法": "偏多/中性/偏空", "一句話": "30 字內結論", "短線": "偏多/中性/偏空", "中期": "偏多/中性/偏空", '
           '"券商目標價": 數字, "目標價保守": 數字, "目標價合理": 數字, "目標價樂觀": 數字, '
           '"今年EPS": 數字, "明年EPS": 數字, "預估本益比": 數字, "支撐": 數字, "壓力": 數字, "停損": 數字}\n\n報告：\n' + 報告)
    if 引擎 == "Gemini":
        import requests
        回應 = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{模型}:generateContent",
                             headers={"x-goog-api-key": 金鑰}, timeout=120,
                             json={"contents": [{"role": "user", "parts": [{"text": 提示}]}]})
        回應.raise_for_status()
        文字 = "".join(p.get("text", "") for p in 回應.json()["candidates"][0]["content"]["parts"])
    else:
        import anthropic
        回應 = anthropic.Anthropic(api_key=金鑰).messages.create(
            model=模型, max_tokens=2000, messages=[{"role": "user", "content": 提示}])
        文字 = "".join(b.text for b in 回應.content if b.type == "text")
    配 = re.search(r"\{.*\}", 文字, re.S)
    return json.loads(配.group(0)) if 配 else None


# ========== 9-1. AI 報告紀錄（存到 GitHub 的 ai-reports 分支，網站重啟也不會消失） ==========
def _AI紀錄網址(設定, 代號):
    倉庫 = 設定.get("AI_REPO", "gelu27/Stock-lab")
    return f"https://api.github.com/repos/{倉庫}/contents/reports/{代號}.json"


def 清理金鑰(值):
    """手機複製貼上常夾帶全形字或看不見的字元，轉成半形並只留英數符號。"""
    import unicodedata
    值 = unicodedata.normalize("NFKC", str(值 or ""))
    return "".join(c for c in 值 if 33 <= ord(c) <= 126).strip('"\'')


def _本機紀錄(代號):
    return 資料夾.parent / "ai_reports" / f"{代號}.json"


def 讀取AI紀錄(代號, 設定):
    """回傳這檔的歷史報告（新到舊）。有 GITHUB_TOKEN 就從 GitHub 讀，否則讀網站暫存（重啟會消失）。"""
    import base64, json, requests

    權杖 = 清理金鑰(設定.get("GITHUB_TOKEN"))
    if 權杖:
        回應 = requests.get(_AI紀錄網址(設定, 代號), timeout=15,
                            params={"ref": 設定.get("AI_BRANCH", "ai-reports")},
                            headers={"Authorization": f"Bearer {權杖}", "Accept": "application/vnd.github+json"})
        if 回應.status_code == 404:
            return []
        回應.raise_for_status()
        return json.loads(base64.b64decode(回應.json()["content"]).decode("utf-8"))
    f = _本機紀錄(代號)
    return json.loads(f.read_text("utf-8")) if f.exists() else []


def 儲存AI紀錄(代號, 紀錄, 設定, 保留=20, 取代=False):
    """把新報告加到最前面並存檔（取代=True 則換掉最新一筆）。回傳是否已永久保存（存到 GitHub）。"""
    略 = 1 if 取代 else 0
    import base64, json, requests

    權杖 = 清理金鑰(設定.get("GITHUB_TOKEN"))
    f = _本機紀錄(代號)
    f.parent.mkdir(exist_ok=True)
    if not 權杖:
        舊 = json.loads(f.read_text("utf-8")) if f.exists() else []
        f.write_text(json.dumps([紀錄] + 舊[略: 保留 - 1 + 略], ensure_ascii=False), "utf-8")
        return False
    分支 = 設定.get("AI_BRANCH", "ai-reports")
    標頭 = {"Authorization": f"Bearer {權杖}", "Accept": "application/vnd.github+json"}
    倉庫 = 設定.get("AI_REPO", "gelu27/Stock-lab")
    # 第一次使用：從 main 開一個 ai-reports 分支（不動到網站程式，所以存檔不會讓網站重新部署）
    if requests.get(f"https://api.github.com/repos/{倉庫}/branches/{分支}", headers=標頭, timeout=15).status_code == 404:
        主 = requests.get(f"https://api.github.com/repos/{倉庫}/git/ref/heads/main", headers=標頭, timeout=15)
        主.raise_for_status()
        requests.post(f"https://api.github.com/repos/{倉庫}/git/refs", headers=標頭, timeout=15,
                      json={"ref": f"refs/heads/{分支}", "sha": 主.json()["object"]["sha"]}).raise_for_status()
    網址 = _AI紀錄網址(設定, 代號)
    現有 = requests.get(網址, params={"ref": 分支}, headers=標頭, timeout=15)
    舊, sha = [], None
    if 現有.status_code == 200:
        舊 = json.loads(base64.b64decode(現有.json()["content"]).decode("utf-8"))
        sha = 現有.json()["sha"]
    內容 = json.dumps([紀錄] + 舊[略: 保留 - 1 + 略], ensure_ascii=False, indent=1)
    資料 = {"message": f"AI 報告 {代號} {紀錄['時間']}", "branch": 分支,
            "content": base64.b64encode(內容.encode("utf-8")).decode()}
    if sha:
        資料["sha"] = sha
    requests.put(網址, headers=標頭, json=資料, timeout=30).raise_for_status()
    return True


# ========== 10. 免費版：新聞清單與規則判讀 ==========
def 個股新聞(代號, 名稱, 天數=180, 筆數=60):
    """從 Google 新聞 RSS 抓近半年新聞（標題、來源、日期、連結），新到舊排序。"""
    import requests
    import xml.etree.ElementTree as ET

    回應 = requests.get("https://news.google.com/rss/search", timeout=20, headers={"User-Agent": "Mozilla/5.0"},
                        params={"q": f"{名稱} {代號} when:{天數}d", "hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant"})
    回應.raise_for_status()
    列們 = []
    for 項 in ET.fromstring(回應.content).iter("item"):
        標題 = 項.findtext("title") or ""
        來源 = 項.findtext("source") or ""
        if 來源 and 標題.endswith(" - " + 來源):
            標題 = 標題[: -len(來源) - 3]
        列們.append({"日期": pd.to_datetime(項.findtext("pubDate"), errors="coerce", utc=True),
                    "標題": 標題, "來源": 來源, "連結": 項.findtext("link") or ""})
    表 = pd.DataFrame(列們, columns=["日期", "標題", "來源", "連結"])
    if 表.empty:
        return 表
    表["日期"] = 表["日期"].dt.tz_convert("Asia/Taipei").dt.tz_localize(None)
    return 表.drop_duplicates("標題").sort_values("日期", ascending=False).head(筆數).reset_index(drop=True)


新聞關鍵字 = {
    "利多": ["創新高", "新高", "成長", "大增", "看好", "調升", "上修", "買進", "優於預期", "超預期", "接單", "擴產",
            "漲停", "轉盈", "獲利", "加碼", "目標價上調", "強勁", "旺"],
    "利空": ["衰退", "下滑", "大減", "看淡", "調降", "下修", "賣出", "低於預期", "虧損", "轉虧", "跌停", "減碼",
            "目標價下調", "疲弱", "砍單", "利空", "裁員", "違約", "淡"],
}


def 新聞情緒(標題):
    多 = sum(k in 標題 for k in 新聞關鍵字["利多"])
    空 = sum(k in 標題 for k in 新聞關鍵字["利空"])
    return "利多" if 多 > 空 else ("利空" if 空 > 多 else "中性")


def 規則判讀(r):
    """用資料庫數據列出利多、利空因素與綜合分數（-100 ~ +100）。r 是今日表的一列。"""
    多, 空 = [], []

    def 看(條件, 分, 文字, 清單):
        if 條件:
            清單.append((分, 文字))

    def g(k):
        v = r.get(k, np.nan)
        return np.nan if v is None or isinstance(v, str) else v
    有 = lambda v: pd.notna(v)
    收 = g("收盤")
    比 = 收 / g("還原價") if g("還原價") else 1
    # 技術面
    for n, 分 in ((20, 10), (60, 10)):
        線 = g(f"MA{n}") * 比
        if 有(線):
            看(收 >= 線, 分, f"站上 {n} 日線（{線:.2f}）", 多)
            看(收 < 線, 分, f"跌破 {n} 日線（{線:.2f}）", 空)
    看(有(g("MA5")) and 有(g("MA20")) and 有(g("MA60")) and g("MA5") > g("MA20") > g("MA60"), 10, "均線多頭排列", 多)
    看(有(g("MA5")) and 有(g("MA20")) and 有(g("MA60")) and g("MA5") < g("MA20") < g("MA60"), 10, "均線空頭排列", 空)
    看(g("RSI") > 80, 5, f"RSI {g('RSI'):.0f} 過熱，留意拉回", 空)
    看(g("RSI") < 25, 5, f"RSI {g('RSI'):.0f} 超賣，可能反彈", 多)
    看(g("距52週高點") > -5, 5, "接近 52 週高點，股價強勢", 多)
    看(g("距52週高點") < -35, 5, f"距 52 週高點 {g('距52週高點'):.0f}%，仍在弱勢區", 空)
    看(g("量比") >= 2 and g("漲跌幅") > 0, 5, f"價漲量增（量為 20 日均量 {g('量比'):.1f} 倍）", 多)
    看(g("量比") >= 2 and g("漲跌幅") < 0, 5, f"價跌量增（量為 20 日均量 {g('量比'):.1f} 倍）", 空)
    # 基本面
    營 = g("營收年增率")
    看(營 >= 20, 10, f"月營收年增 {營:.1f}%", 多)
    看(營 <= -10, 10, f"月營收年減 {abs(營):.1f}%", 空)
    看(g("累計營收年增率") >= 10, 5, f"今年累計營收年增 {g('累計營收年增率'):.1f}%", 多)
    看(g("累計營收年增率") <= -10, 5, f"今年累計營收年減 {abs(g('累計營收年增率')):.1f}%", 空)
    看(r.get("營收創新高") == True, 10, "月營收創歷史新高", 多)
    看(g("近三季EPS") < 0, 10, "近三季 EPS 合計虧損", 空)
    看(0 < g("本益比") <= 12, 5, f"本益比 {g('本益比'):.1f} 偏低", 多)
    看(g("本益比") >= 40, 5, f"本益比 {g('本益比'):.1f} 偏高", 空)
    看(g("殖利率") >= 5, 5, f"殖利率 {g('殖利率'):.1f}%", 多)
    # 籌碼面
    看(g("外資連買") >= 3, 10, f"外資連買 {g('外資連買'):.0f} 天", 多)
    看(g("投信連買") >= 3, 10, f"投信連買 {g('投信連買'):.0f} 天", 多)
    法 = g("法人10日買超")
    if 有(法) and 有(g("5日均量")) and g("5日均量") > 0:
        佔 = 法 / g("5日均量")  # 法人 10 日買超相當於幾天的成交量
        看(佔 >= 1, 10, f"法人 10 日買超 {法:,.0f} 張", 多)
        看(佔 <= -1, 10, f"法人 10 日賣超 {abs(法):,.0f} 張", 空)
    看(g("融資5日增減") >= 10 and g("20日漲幅") < 0, 5, f"股價跌但融資 5 日增 {g('融資5日增減'):.0f}%，籌碼凌亂", 空)

    分數 = sum(s for s, _ in 多) - sum(s for s, _ in 空)
    總 = sum(s for s, _ in 多) + sum(s for s, _ in 空)
    分數 = round(分數 / 總 * 100) if 總 else 0
    看法 = "偏多" if 分數 >= 30 else ("偏空" if 分數 <= -30 else "中性")
    return {"分數": 分數, "看法": 看法, "利多": [t for _, t in 多], "利空": [t for _, t in 空]}


def AI分析Gemini(代號, 名稱, 數據摘要, api_key, 模型="gemini-flash-latest"):
    """改用 Google Gemini（Google 搜尋）做同樣的彙整。回傳 (Markdown 內文, 來源清單)。"""
    import requests

    今天 = pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m-%d")
    內容 = {
        "systemInstruction": {"parts": [{"text": AI系統提示}]},
        "contents": [{"role": "user", "parts": [{"text": (
            f"今天是 {今天}。請分析台股 {代號} {名稱}。\n\n以下是我資料庫裡的最新數據：\n{數據摘要}\n\n"
            "請用 Google 搜尋近六個月的新聞與法人報告後，依照指定格式彙整並給出投資建議。")}]}],
        "tools": [{"google_search": {}}],
    }
    網址 = f"https://generativelanguage.googleapis.com/v1beta/models/{模型}:generateContent"
    回應 = requests.post(網址, headers={"x-goog-api-key": api_key}, json=內容, timeout=300)
    if 回應.status_code == 429:
        # 免費額度不含 Google 搜尋：改成只根據我們抓到的新聞標題彙整
        內容.pop("tools")
        內容["contents"][0]["parts"][0]["text"] += "\n\n（這次無法上網搜尋，請只根據上面提供的新聞標題與數據分析，並在結論註明。）"
        回應 = requests.post(網址, headers={"x-goog-api-key": api_key}, json=內容, timeout=300)
    if 回應.status_code != 200:
        try:
            訊息 = 回應.json()["error"]["message"]
        except Exception:
            訊息 = 回應.text[:200]
        if 回應.status_code == 429:
            訊息 = "今天的 Gemini 免費額度用完了，明天再試。"
        raise RuntimeError(f"Gemini 回應錯誤（{回應.status_code}）：{訊息}")
    候選 = (回應.json().get("candidates") or [{}])[0]
    文字 = "".join(p.get("text", "") for p in (候選.get("content") or {}).get("parts", [])).strip()
    if not 文字:
        raise RuntimeError(f"Gemini 沒有產生內容（{候選.get('finishReason', '未知原因')}），請稍後再試。")
    來源 = {}
    for 塊 in (候選.get("groundingMetadata") or {}).get("groundingChunks", []):
        網 = 塊.get("web") or {}
        if 網.get("uri") and 網["uri"] not in 來源:
            來源[網["uri"]] = 網.get("title") or 網["uri"]
    return 文字, list(來源.items())
