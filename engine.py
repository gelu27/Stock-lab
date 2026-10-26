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
def 釋放記憶體():
    """把 pandas 用完的暫存記憶體真正還給系統（Linux 預設會一直佔著，雲端容易超過上限而當機）"""
    import gc
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def _讀一天(f):
    """讀一個每日 csv.gz，數字一律轉 float32 省記憶體，日期從檔名取。"""
    import pyarrow as pa
    import pyarrow.csv as pc

    選項 = pc.ConvertOptions(column_types={"code": pa.string(), "market": pa.string(), "name": pa.string()})
    t = pc.read_csv(f, convert_options=選項)
    欄們 = {}
    for 名 in t.column_names:
        c = t[名]
        if pa.types.is_integer(c.type) or pa.types.is_floating(c.type) or pa.types.is_null(c.type):
            c = c.cast(pa.float32(), safe=False)
        欄們[名] = c
    日 = np.datetime64(f"{f.name[:4]}-{f.name[4:6]}-{f.name[6:8]}", "us")
    欄們["date"] = pa.array(np.full(t.num_rows, 日))
    return pa.table(欄們)


def _月檔(子資料夾, 月):
    return 資料夾 / "monthly" / f"{子資料夾}_{月}.parquet"


def 整併月檔(子資料夾們=("prices", "chips")):
    """把已經過完的月份（每天一檔的 csv.gz）合併成一個依代號排序的 parquet，
    網站要查單一股票或讀很多天時快很多、也省記憶體。由 GitHub Actions 每天更新資料後執行。"""
    import pyarrow as pa
    import pyarrow.parquet as pq

    本月 = pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m")
    (資料夾 / "monthly").mkdir(exist_ok=True)
    for 子 in 子資料夾們:
        for 夾 in sorted(p for p in (資料夾 / 子).glob("*") if p.is_dir()):
            月 = 夾.name
            檔們 = sorted(夾.glob("*.csv.gz"))
            目標 = _月檔(子, 月)
            if 月 >= 本月 or not 檔們:
                continue
            # 記下來源檔名與大小，來源沒變就不重做（git 下載後檔案時間不可靠）
            指紋 = ",".join(f"{f.name}:{f.stat().st_size}" for f in 檔們).encode()
            if 目標.exists() and (pq.read_schema(目標).metadata or {}).get(b"sources") == 指紋:
                continue
            t = pa.concat_tables([_讀一天(f) for f in 檔們], promote_options="permissive")
            t = t.sort_by([("code", "ascending"), ("date", "ascending")])
            t = t.replace_schema_metadata({"sources": 指紋})
            pq.write_table(t, 目標, compression="zstd", row_group_size=8000)
            print(f"整併 {子} {月}：{t.num_rows} 列")


def _交易日(子資料夾):
    return sorted(pd.Timestamp(f.name[:8]) for f in (資料夾 / 子資料夾).glob("*/*.csv.gz"))


def _讀每日檔(子資料夾, 最近天數=None, 代號=None, 起日=None):
    """讀資料庫：過完的月份讀整併好的 parquet，其他讀每天的 csv.gz。
    最近天數：只讀最後幾個交易日；代號：只讀這一檔；起日：只讀這天以後。"""
    from concurrent.futures import ThreadPoolExecutor
    import pyarrow as pa
    import pyarrow.compute as pcm
    import pyarrow.parquet as pq

    夾們 = sorted(p for p in (資料夾 / 子資料夾).glob("*") if p.is_dir())
    if not 夾們:
        return None
    if 最近天數:
        日們 = _交易日(子資料夾)
        if 日們:
            起日 = max(起日 or 日們[0], 日們[-最近天數:][0])
    起月 = 起日.strftime("%Y-%m") if 起日 is not None else ""
    過濾 = []
    代號們 = None if 代號 is None else ([str(代號)] if isinstance(代號, str) else [str(c) for c in 代號])
    if 代號們 is not None:
        過濾.append(("code", "in", 代號們))
    if 起日 is not None:
        過濾.append(("date", ">=", pd.Timestamp(起日).to_datetime64().astype("datetime64[us]")))

    工作 = []
    for 夾 in 夾們:
        if 夾.name < 起月:
            continue
        月檔 = _月檔(子資料夾, 夾.name)
        if 月檔.exists():
            工作.append(("pq", 月檔))
        else:
            工作.extend(("csv", f) for f in sorted(夾.glob("*.csv.gz"))
                      if 起日 is None or pd.Timestamp(f.name[:8]) >= 起日)

    def 讀(項):
        種類, f = 項
        if 種類 == "pq":
            return pq.read_table(f, filters=過濾 or None)
        t = _讀一天(f)
        if 代號們 is not None:
            t = t.filter(pcm.is_in(t["code"], value_set=pa.array(代號們)))
        return t

    with ThreadPoolExecutor(4) as 工人:
        表們 = [t for t in 工人.map(讀, 工作) if t.num_rows]
    if not 表們:
        return None
    合併 = pa.concat_tables(表們, promote_options="permissive")
    del 表們
    名稱們 = {}
    if "name" in 合併.column_names:  # 名稱另外存一份對照表，不必每天每檔都存一個字串（很佔記憶體）
        名 = 合併.select(["code", "name"]).to_pandas()
        名稱們 = dict(zip(名["code"], 名["name"]))  # 後面（較新）的名稱蓋過前面的
        del 名
        合併 = 合併.drop_columns(["name"])
    表 = 合併.to_pandas(self_destruct=True)
    del 合併
    表 = 表.drop_duplicates(["date", "code"], keep="last")
    # 同樣的文字共用同一個物件，例如「2330」「上市」，省下幾百 MB 記憶體
    for 欄 in ("code", "market"):
        if 欄 in 表.columns:
            共用 = {v: v for v in 表[欄].dropna().unique()}
            表[欄] = 表[欄].map(共用)
    if 名稱們:
        表["name"] = 表["code"].map(名稱們)
    return 表


def 讀取資料庫(最近天數=None, 代號=None, 起日=None):
    """上市櫃每日行情＋籌碼。最近天數／代號／起日可以只讀一部分，省記憶體。"""
    表 = _讀每日檔("prices", 最近天數, 代號, 起日)
    if 表 is None:
        return None
    if "market" not in 表.columns:
        表["market"] = "上市"
    表["market"] = 表["market"].fillna("上市")
    釋放記憶體()
    籌碼 = _讀每日檔("chips", 最近天數, 代號, 起日)
    if 籌碼 is not None:
        表 = 表.merge(籌碼, on=["date", "code"], how="left")
        del 籌碼
        釋放記憶體()
    數字 = 表.select_dtypes("float64").columns
    表[數字] = 表[數字].astype("float32")  # 省記憶體
    return 表.sort_values(["code", "date"], ignore_index=True)


def 資料起訖():
    """資料庫第一天、最後一天（看檔名，不必讀資料）。"""
    日們 = _交易日("prices")
    return (日們[0], 日們[-1]) if 日們 else (None, None)


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


def 讀取營收歷史(代號):
    """這檔的月營收歷史（month、revenue 千元）。"""
    表們 = []
    for 名 in ("revenue_history.csv", "revenue.csv"):
        f = 資料夾 / "fundamental" / 名
        if f.exists():
            t = pd.read_csv(f, dtype={"code": str})
            if {"month", "revenue"} <= set(t.columns):
                表們.append(t.loc[t["code"] == str(代號), ["month", "revenue"]])
    if not 表們:
        return None
    return pd.concat(表們).dropna().drop_duplicates("month", keep="last").sort_values("month")


def 單季損益(代號=None):
    """損益表是「今年累計」，換成單季的營收、毛利、營業利益與毛利率、營益率。"""
    f = 資料夾 / "fundamental" / "income.csv"
    if not f.exists():
        return pd.DataFrame()
    t = pd.read_csv(f, dtype={"code": str})
    if 代號 is not None:
        t = t[t["code"] == str(代號)]
    t = t.dropna(subset=["revenue", "gross"]).sort_values(["code", "quarter"]).copy()
    if "opinc" not in t.columns:
        t["opinc"] = np.nan
    t["年"], t["季"] = t["quarter"].str[:4], t["quarter"].str[-1].astype(int)
    前季號 = t.groupby(["code", "年"])["季"].shift()
    for k in ("revenue", "gross", "opinc"):
        前 = t.groupby(["code", "年"])[k].shift()
        t[k + "_q"] = np.where(t["季"] == 1, t[k], np.where(前季號 == t["季"] - 1, t[k] - 前, np.nan))
    有效 = t["revenue_q"] > 0
    t["毛利率"] = np.where(有效, t["gross_q"] / t["revenue_q"] * 100, np.nan).round(2)
    t["營益率"] = np.where(有效, t["opinc_q"] / t["revenue_q"] * 100, np.nan).round(2)
    return t


def 近四季EPS(代號):
    """用各季累計 EPS 換成單季，加總最近連續四季；也算去年同期的近四季。回傳 (近四季, 截至季度, 去年同期近四季)。"""
    f = 資料夾 / "fundamental" / "income.csv"
    if not f.exists():
        return np.nan, None, np.nan
    t = pd.read_csv(f, dtype={"code": str})
    if "eps" not in t.columns:
        return np.nan, None, np.nan
    t = t[t["code"] == str(代號)].dropna(subset=["eps"]).sort_values("quarter")
    if t.empty:
        return np.nan, None, np.nan
    t["年"], t["季"] = t["quarter"].str[:4].astype(int), t["quarter"].str[-1].astype(int)
    t["序"] = t["年"] * 4 + t["季"]
    累計 = t.set_index("序")["eps"]
    單季 = {序: (累計[序] if 季 == 1 else 累計[序] - 累計[序 - 1] if 序 - 1 in 累計.index else np.nan)
            for 序, 季 in zip(t["序"], t["季"])}
    def 四季(末):
        值 = [單季.get(末 - i, np.nan) for i in range(4)]
        return float(np.sum(值)) if not np.isnan(值).any() else np.nan
    末 = int(t["序"].iloc[-1])
    return 四季(末), t["quarter"].iloc[-1], 四季(末 - 4)


def 毛利率表():
    """每檔最新一季的單季毛利率，和上一季、去年同季比較（百分點）。"""
    t = 單季損益().dropna(subset=["毛利率"])
    if t.empty:
        return pd.DataFrame(columns=["毛利率", "毛利率季度", "毛利率季增", "毛利率年增", "營益率", "營益率季增", "營益率年增"])
    t["序"] = t["年"].astype(int) * 4 + t["季"]
    最新 = t.groupby("code").tail(1).set_index("code")
    結果 = {"毛利率": 最新["毛利率"], "毛利率季度": 最新["quarter"], "營益率": 最新["營益率"]}
    for 欄 in ("毛利率", "營益率"):
        鍵 = t.set_index(["code", "序"])[欄]
        上季 = 鍵.reindex(list(zip(最新.index, 最新["序"] - 1))).values
        去年 = 鍵.reindex(list(zip(最新.index, 最新["序"] - 4))).values
        結果[欄 + "季增"] = (最新[欄] - 上季).round(2)
        結果[欄 + "年增"] = (最新[欄] - 去年).round(2)
    return pd.DataFrame(結果, index=最新.index)


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
       初始資金=1_000_000, 選股資料=None):
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
    # 選股資料：只有調倉日的完整指標（省記憶體版，見 回測資料()）；沒給就用 指標 本身
    依日期 = {d: g for d, g in (區間 if 選股資料 is None else 選股資料).groupby("date")}

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


def 調倉日(日期們, 調倉):
    日期們 = pd.DatetimeIndex(日期們)
    if 調倉 == "每日":
        return set(日期們)
    期別 = 日期們.to_period("W" if 調倉 == "每週" else "M")
    return set(日期們[np.r_[期別[1:] != 期別[:-1], True]]) | {日期們[0]}


def 回測資料(開始, 結束, 調倉="每月", 批數=6):
    """組合回測用的資料，分批計算省記憶體：每天只留報酬、收盤、還原價、名稱（算績效用），
    調倉日才留完整指標（選股用）。回傳 (每日窄表, 調倉日完整表)。"""
    import pyarrow.parquet as pq

    開始, 結束 = pd.Timestamp(開始), pd.Timestamp(結束)
    日們 = [d for d in _交易日("prices") if 開始 <= d <= 結束]
    if not 日們:
        return None, None
    訊號 = 調倉日(日們, 調倉)
    # 期間內出現過的所有代號（含已下市），只讀 code 欄很快
    代號們 = set()
    for f in (資料夾 / "monthly").glob("prices_*.parquet"):
        if 開始.strftime("%Y-%m") <= f.stem[-7:] <= 結束.strftime("%Y-%m"):
            代號們 |= set(pq.read_table(f, columns=["code"])["code"].to_pylist())
    for f in (資料夾 / "prices").glob("*/*.csv.gz"):
        if 開始 <= pd.Timestamp(f.name[:8]) <= 結束 and not _月檔("prices", f.parent.name).exists():
            代號們 |= set(pd.read_csv(f, usecols=["code"], dtype=str)["code"])
    代號們 = sorted(代號們)
    窄們, 全們 = [], []
    for i in range(批數):
        批 = 代號們[i::批數]
        原始 = 讀取資料庫(代號=批, 起日=開始 - pd.Timedelta(days=400))  # 多讀一年多算均線、52 週高點
        if 原始 is None:
            continue
        指 = 計算指標(原始)
        del 原始
        指 = 指[(指["date"] >= 開始) & (指["date"] <= 結束)]
        窄們.append(指[["date", "code", "代號", "名稱", "日報酬", "收盤", "還原價"]].copy())
        全們.append(指[指["date"].isin(訊號)].copy())
        del 指
        釋放記憶體()
    排 = lambda 們: pd.concat(們, ignore_index=True).sort_values(["code", "date"], ignore_index=True)  # 同分時順序跟以前一樣
    return 排(窄們), 排(全們)


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
        回應, _ = Gemini呼叫({"contents": [{"role": "user", "parts": [{"text": 提示}]}]}, 金鑰, 模型)
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


Gemini備用模型 = ["gemini-flash-latest", "gemini-3.5-flash", "gemini-flash-lite-latest"]


def Gemini呼叫(內容, api_key, 模型="gemini-flash-latest", 每個試幾次=2):
    """呼叫 Gemini；遇到「忙線」(500/503/504) 或逾時會稍等重試，還是不行就換備用模型。回傳 (回應, 實際模型)。"""
    import time
    import requests

    最後錯誤 = None
    for m in dict.fromkeys([模型] + Gemini備用模型):
        網址 = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
        for 次 in range(每個試幾次):
            try:
                回應 = requests.post(網址, headers={"x-goog-api-key": api_key}, json=內容, timeout=180)
            except requests.RequestException as 錯:
                最後錯誤 = f"連線逾時或中斷（{type(錯).__name__}）"
                time.sleep(3)
                continue
            if 回應.status_code == 200:
                return 回應, m
            try:
                訊息 = 回應.json()["error"]["message"]
            except Exception:
                訊息 = 回應.text[:200]
            if 回應.status_code == 429:
                最後錯誤 = "今天的 Gemini 免費額度用完了，明天再試。"
                break  # 這個模型額度用完，換下一個
            if 回應.status_code in (500, 503, 504):
                最後錯誤 = "Gemini 目前使用的人太多（忙線），已自動重試和換模型仍失敗，請過幾分鐘再按一次。"
                time.sleep(4 * (次 + 1))
                continue
            if 回應.status_code == 404:
                最後錯誤 = f"模型 {m} 不存在"
                break
            raise RuntimeError(f"Gemini 回應錯誤（{回應.status_code}）：{訊息}")
    raise RuntimeError(最後錯誤 or "Gemini 沒有回應")


def AI分析Gemini(代號, 名稱, 數據摘要, api_key, 模型="gemini-flash-latest", 搜尋=False):
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
    if not 搜尋:
        # 免費額度不含 Google 搜尋：只根據我們抓到的新聞標題與數據彙整（省一次呼叫）
        內容.pop("tools")
        內容["contents"][0]["parts"][0]["text"] += "\n\n（這次無法上網搜尋，請只根據上面提供的新聞標題與數據分析，並在結論註明。）"
    回應, 模型 = Gemini呼叫(內容, api_key, 模型)
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


# ========== 11. 族群熱力圖 ==========
族群期間 = {"今日": "漲跌幅", "5 日": "5日漲幅", "20 日": "20日漲幅"}


def 族群資料(今日, 期間="今日", 大小="市值", 每族群=15):
    """回傳 (族群表, 個股表)。族群漲跌幅用市值（或成交值）加權平均，大型股影響較大。
    個股表只留每個族群最大的幾檔，熱力圖在手機上才看得清楚。"""
    欄 = 族群期間[期間]
    表 = 今日[(今日["收盤"] > 0) & ~今日["代號"].str.startswith("00")
            & (今日["產業"].fillna("") != "") & 今日[欄].notna()].copy()
    表["市值億"] = 表["收盤"] * 表["發行股數"] / 1e8
    表["權重"] = 表["市值億"] if 大小 == "市值" else 表["成交值億"]
    表 = 表[表["權重"] > 0]
    表["幅度"] = 表[欄]
    表["加權"] = 表["幅度"] * 表["權重"]
    群 = 表.groupby("產業")
    族群 = pd.DataFrame({
        "漲跌幅": 群["加權"].sum() / 群["權重"].sum(),
        "上漲": 群["幅度"].apply(lambda s: int((s > 0).sum())),
        "下跌": 群["幅度"].apply(lambda s: int((s < 0).sum())),
        "家數": 群.size(),
        "成交值億": 群["成交值億"].sum(),
        "市值億": 群["市值億"].sum(),
        "權重": 群["權重"].sum(),
    })
    領 = 表.loc[群["幅度"].idxmax()].set_index("產業")
    族群["領漲股"] = 領["名稱"] + " " + 領["幅度"].map("{:+.1f}%".format)
    族群 = 族群.astype({"漲跌幅": float, "成交值億": float, "市值億": float}).round({"漲跌幅": 2, "成交值億": 1, "市值億": 0}).sort_values("漲跌幅", ascending=False)
    表 = 表.sort_values("權重", ascending=False)
    前段 = 表.groupby("產業").head(每族群)
    其餘 = 表.drop(前段.index).groupby("產業")
    其他 = pd.DataFrame({"代號": "", "權重": 其餘["權重"].sum(), "加權": 其餘["加權"].sum(),
                       "名稱": 其餘.size().map("其他 {} 檔".format)}).reset_index()
    其他["幅度"] = 其他["加權"] / 其他["權重"]
    個股 = pd.concat([前段, 其他], ignore_index=True)
    return 族群, 個股[["產業", "代號", "名稱", "幅度", "權重"]]


# ========== 12. 自選股、到價提醒（存到 GitHub 的 ai-reports 分支，跟 AI 報告放一起） ==========
def _GitHub設定(設定, 檔名):
    權杖 = 清理金鑰(設定.get("GITHUB_TOKEN"))
    倉庫 = 設定.get("AI_REPO", "gelu27/Stock-lab")
    分支 = 設定.get("AI_BRANCH", "ai-reports")
    標頭 = {"Authorization": f"Bearer {權杖}", "Accept": "application/vnd.github+json"}
    return 權杖, f"https://api.github.com/repos/{倉庫}/contents/{檔名}", 分支, 標頭


def 觸發更新(設定):
    """請 GitHub Actions 立刻跑一次「更新資料庫」。回傳 (成功, 說明)。
    GITHUB_TOKEN 需要 Actions 的 Read and write 權限。"""
    import requests
    權杖, _, _, 標頭 = _GitHub設定(設定, "")
    if not 權杖:
        return False, "Secrets 沒有設定 GITHUB_TOKEN"
    倉庫 = 設定.get("AI_REPO", "gelu27/Stock-lab")
    r = requests.post(f"https://api.github.com/repos/{倉庫}/actions/workflows/update.yml/dispatches",
                      headers=標頭, json={"ref": "main"}, timeout=15)
    if r.status_code == 204:
        return True, "已開始更新"
    if r.status_code in (401, 403, 404):
        return False, ("GITHUB_TOKEN 沒有執行 Actions 的權限：到 GitHub → Settings → Developer settings → "
                       "Fine-grained tokens，編輯這把金鑰，在 Repository permissions 把「Actions」改成 Read and write。")
    return False, f"GitHub 回應 {r.status_code}：{r.text[:120]}"


def 讀取設定檔(設定, 檔名):
    """讀 ai-reports 分支上的 JSON 檔（watchlist.json、alerts.json）。沒有 GITHUB_TOKEN 時讀網站暫存（重啟會消失）。"""
    import base64, json, requests

    權杖, 網址, 分支, 標頭 = _GitHub設定(設定, 檔名)
    if 權杖:
        回應 = requests.get(網址, params={"ref": 分支}, headers=標頭, timeout=15)
        if 回應.status_code == 404:
            return {}
        回應.raise_for_status()
        return json.loads(base64.b64decode(回應.json()["content"]).decode("utf-8"))
    f = 資料夾.parent / "ai_reports" / 檔名
    return json.loads(f.read_text("utf-8")) if f.exists() else {}


def 儲存設定檔(設定, 檔名, 內容物, 訊息="更新設定"):
    """回傳是否已永久保存（存到 GitHub）。"""
    import base64, json, requests

    內容 = json.dumps(內容物, ensure_ascii=False, indent=1)
    權杖, 網址, 分支, 標頭 = _GitHub設定(設定, 檔名)
    if not 權杖:
        f = 資料夾.parent / "ai_reports" / 檔名
        f.parent.mkdir(exist_ok=True)
        f.write_text(內容, "utf-8")
        return False
    倉庫網址 = 網址.split("/contents/")[0]
    if requests.get(f"{倉庫網址}/branches/{分支}", headers=標頭, timeout=15).status_code == 404:
        主 = requests.get(f"{倉庫網址}/git/ref/heads/main", headers=標頭, timeout=15)
        主.raise_for_status()
        requests.post(f"{倉庫網址}/git/refs", headers=標頭, timeout=15,
                      json={"ref": f"refs/heads/{分支}", "sha": 主.json()["object"]["sha"]}).raise_for_status()
    現有 = requests.get(網址, params={"ref": 分支}, headers=標頭, timeout=15)
    資料 = {"message": 訊息, "branch": 分支, "content": base64.b64encode(內容.encode("utf-8")).decode()}
    if 現有.status_code == 200:
        資料["sha"] = 現有.json()["sha"]
    requests.put(網址, headers=標頭, json=資料, timeout=30).raise_for_status()
    return True


def 讀取自選股(設定):
    """回傳 {群組名: [代號, ...]}。"""
    return 讀取設定檔(設定, "watchlist.json")


def 儲存自選股(自選, 設定):
    return 儲存設定檔(設定, "watchlist.json", 自選, "更新自選股")


def 讀取提醒(設定):
    """回傳 {代號: {"上": 價格或 None, "下": 價格或 None}}。"""
    return 讀取設定檔(設定, "alerts.json")


def 儲存提醒(提醒, 設定):
    return 儲存設定檔(設定, "alerts.json", 提醒, "更新到價提醒")


# ========== 13. 本益比河流圖、同族群比較 ==========
def 本益比河流(歷史, 倍數個數=5):
    """歷史：某檔的每日資料（date、收盤、本益比）。交易所的本益比 = 收盤 ÷ 近四季 EPS，
    反推每天的近四季 EPS，再乘上幾個本益比倍數畫成河流。回傳 (表, 倍數們, 目前百分位) 或 None。"""
    h = 歷史[(歷史["本益比"] > 0) & (歷史["收盤"] > 0)][["date", "收盤", "本益比"]].copy()
    if len(h) < 60:
        return None
    h["EPS"] = h["收盤"] / h["本益比"]
    低, 高 = h["本益比"].quantile([0.1, 0.9])
    倍數們 = sorted({round(x) for x in np.linspace(低, 高, 倍數個數)})
    if len(倍數們) < 3:
        倍數們 = [round(低 * 0.8), round(低), round((低 + 高) / 2), round(高), round(高 * 1.2)]
    for 倍 in 倍數們:
        h[f"{倍}倍"] = h["EPS"] * 倍
    目前 = h["本益比"].iloc[-1]
    百分位 = (h["本益比"] < 目前).mean() * 100
    return h, 倍數們, 百分位


def 同族群(今日, 代號, 檔數=10):
    """同產業市值最大的幾檔（一定包含自己），用來比較估值與成長。"""
    產業 = 今日.loc[今日["代號"] == 代號, "產業"]
    if 產業.empty or not 產業.iloc[0]:
        return None
    群 = 今日[(今日["產業"] == 產業.iloc[0]) & (今日["收盤"] > 0) & ~今日["代號"].str.startswith("00")].copy()
    群["市值億"] = (群["收盤"] * 群["發行股數"] / 1e8).round(0)
    前段 = 群.nlargest(檔數, "市值億")
    if 代號 not in 前段["代號"].values:
        前段 = pd.concat([前段.head(檔數 - 1), 群[群["代號"] == 代號]])
    return 前段.sort_values("市值億", ascending=False)


# ========== 14. 除權息、集保大戶、國際行情 ==========
def 讀取除權息(代號):
    """回傳 (歷史, 預告)。歷史：date、type（權/息/權息）、value（權值+息值）、cash、pre_close、ref。"""
    歷史 = 預告 = None
    f = 資料夾 / "fundamental" / "dividend.csv"
    if f.exists():
        t = pd.read_csv(f, dtype={"code": str}, parse_dates=["date"])
        歷史 = t[t["code"] == 代號].sort_values("date")
    f = 資料夾 / "fundamental" / "dividend_upcoming.csv"
    if f.exists():
        t = pd.read_csv(f, dtype={"code": str}, parse_dates=["date"])
        預告 = t[(t["code"] == 代號) & (t["date"] >= pd.Timestamp.now().normalize())]
    return 歷史, 預告


def 讀取全部除權息(預告=False):
    f = 資料夾 / "fundamental" / ("dividend_upcoming.csv" if 預告 else "dividend.csv")
    return pd.read_csv(f, dtype={"code": str}, parse_dates=["date"]) if f.exists() else pd.DataFrame(
        columns=["code", "date", "type", "value", "cash"])


def 填息(除權息, 價格):
    """價格：該檔每日 date、收盤（原始價）。每次除權息後，收盤回到除權息前收盤價要幾個交易日。"""
    結果 = []
    for _, e in 除權息.iterrows():
        之後 = 價格[價格["date"] >= e["date"]]
        回到 = 之後[之後["收盤"] >= e["pre_close"]]
        if len(之後) == 0:
            狀態 = "—"
        elif len(回到):
            狀態 = f"{len(之後[之後['date'] <= 回到['date'].iloc[0]]) - 1} 天"
        else:
            狀態 = "尚未填息" if 之後["date"].min() > 價格["date"].min() else "—"
        結果.append(狀態)
    return 結果


def 讀取集保(代號):
    """每週千張大戶、400 張以上大戶、50 張以下散戶持股比例與總股東人數。"""
    表們 = []
    for f in sorted((資料夾 / "tdcc").glob("*.csv.gz")):
        t = pd.read_csv(f, dtype={"code": str})
        t = t[t["code"] == 代號]
        if len(t):
            表們.append(t.assign(date=pd.Timestamp(f.name[:8])))
    return pd.concat(表們, ignore_index=True) if 表們 else None


國際代號 = {"道瓊": "^DJI", "那斯達克": "^IXIC", "S&P 500": "^GSPC", "費城半導體": "^SOX",
          "台積電 ADR": "TSM", "日經 225": "^N225", "美元/台幣": "USDTWD=X"}


def 國際行情():
    """Yahoo 財經的國際指數（最新價與漲跌）。回傳 {名稱: dict(價, 漲跌, 幅度, 時間)}。"""
    import requests
    from concurrent.futures import ThreadPoolExecutor

    def 抓(項):
        名, 符號 = 項
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(符號)}"
                             "?interval=1d&range=5d", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            結果 = r.json()["chart"]["result"][0]
            收們 = [c for c in 結果["indicators"]["quote"][0]["close"] if c is not None]
            價 = 結果["meta"].get("regularMarketPrice") or 收們[-1]
            # 日線最後一根通常就是現價，昨收取前一根
            昨 = 收們[-2] if len(收們) >= 2 and abs(收們[-1] - 價) <= abs(價) * 1e-6 else 收們[-1]
            時間 = pd.Timestamp(結果["meta"]["regularMarketTime"], unit="s", tz="UTC").tz_convert("Asia/Taipei")
            return 名, {"價": 價, "漲跌": 價 - 昨, "幅度": (價 / 昨 - 1) * 100, "時間": 時間}
        except Exception:
            return 名, None

    with ThreadPoolExecutor(8) as 工人:
        return {名: v for 名, v in 工人.map(抓, 國際代號.items()) if v}


def 台指期():
    """期交所行情：台指期近月日盤與夜盤。回傳 {"日盤": dict, "夜盤": dict}（抓不到的不放）。"""
    import requests

    結果 = {}
    for 盤, 代碼, 尾 in (("日盤", "0", "-F"), ("夜盤", "1", "-M")):
        try:
            r = requests.post("https://mis.taifex.com.tw/futures/api/getQuoteList", timeout=10,
                              headers={"User-Agent": "Mozilla/5.0"},
                              json={"MarketType": 代碼, "SymbolType": "F", "KindID": "1", "CID": "TXF",
                                    "ExpireMonth": "", "RowSize": "全部", "PageNo": "", "SortColumn": "",
                                    "AscDesc": "A"})
            for q in r.json()["RtData"]["QuoteList"]:
                if q["SymbolID"].startswith("TXF") and q["SymbolID"].endswith(尾) and q.get("CLastPrice"):
                    結果[盤] = {"名稱": q["DispCName"], "價": float(q["CLastPrice"]), "漲跌": float(q["CDiff"]),
                              "幅度": float(q["CDiffRate"]), "時間": f"{q['CDate'][4:6]}/{q['CDate'][6:]} "
                              f"{q['CTime'][:2]}:{q['CTime'][2:4]}" if q.get("CTime") else q["CDate"]}
                    break
        except Exception:
            pass
    return 結果


# ========== 13. 每日評分（大盤、技術面、籌碼面、基本面、市場面，規則打分數，僅供參考） ==========
# 每一面從 50 分（中性）開始，符合條件就加分或扣分，最後限制在 0～100。
# 想調整規則就改下面的表：(面向, 分數, 條件, 說明文字)；分數是正的就是利多、負的就是利空。
def _有(d, 欄):
    return d[欄] if 欄 in d.columns else pd.Series(np.nan, index=d.index)


評分規則 = [
    # ----- 技術面 -----
    ("技術", 10, lambda d: d["還原價"] >= d["MA20"], lambda r: "站上 20 日線"),
    ("技術", -10, lambda d: d["還原價"] < d["MA20"], lambda r: "跌破 20 日線"),
    ("技術", 10, lambda d: d["還原價"] >= d["MA60"], lambda r: "站上 60 日線（季線）"),
    ("技術", -10, lambda d: d["還原價"] < d["MA60"], lambda r: "跌破 60 日線（季線）"),
    ("技術", 10, lambda d: (d["MA5"] > d["MA20"]) & (d["MA20"] > d["MA60"]), lambda r: "均線多頭排列"),
    ("技術", -10, lambda d: (d["MA5"] < d["MA20"]) & (d["MA20"] < d["MA60"]), lambda r: "均線空頭排列"),
    # 2026-10 依歷史驗證調整：RSI 過熱／超賣、價漲量增、跌深、遠離高點這幾條實際效果跟直覺相反或不穩，拿掉；
    # 「5 日急跌 10% 以上」之後反彈的機率高（前後兩段期間都成立），改成加分
    ("技術", 5, lambda d: d["20日漲幅"] >= 10, lambda r: f"近 20 日漲 {r['20日漲幅']:.1f}%"),
    ("技術", 5, lambda d: d["距52週高點"] > -5, lambda r: "接近 52 週高點"),
    ("技術", 10, lambda d: d["5日漲幅"] <= -10, lambda r: f"近 5 日急跌 {abs(r['5日漲幅']):.1f}%，短線超跌易反彈"),
    ("技術", -5, lambda d: (d["量比"] >= 2) & (d["漲跌幅"] < 0), lambda r: f"價跌量增（{r['量比']:.1f} 倍均量）"),
    # ----- 籌碼面（買賣超張數跟成交量比，大型股小型股才比得起來） -----
    ("籌碼", 15, lambda d: _有(d, "法人5日買超") / d["5日均量"].replace(0, np.nan) >= 0.5,
     lambda r: f"法人 5 日買超 {r['法人5日買超']:,.0f} 張（量大）"),
    ("籌碼", 7, lambda d: (_有(d, "法人5日買超") / d["5日均量"].replace(0, np.nan)).between(0.15, 0.5, "left"),
     lambda r: f"法人 5 日買超 {r['法人5日買超']:,.0f} 張"),
    ("籌碼", -7, lambda d: (_有(d, "法人5日買超") / d["5日均量"].replace(0, np.nan)).between(-0.5, -0.15, "right"),
     lambda r: f"法人 5 日賣超 {abs(r['法人5日買超']):,.0f} 張"),
    ("籌碼", -15, lambda d: _有(d, "法人5日買超") / d["5日均量"].replace(0, np.nan) <= -0.5,
     lambda r: f"法人 5 日賣超 {abs(r['法人5日買超']):,.0f} 張（量大）"),
    ("籌碼", 10, lambda d: _有(d, "外資連買") >= 3, lambda r: f"外資連買 {r['外資連買']:.0f} 天"),
    ("籌碼", 10, lambda d: _有(d, "投信連買") >= 3, lambda r: f"投信連買 {r['投信連買']:.0f} 天"),
    ("籌碼", 5, lambda d: _有(d, "外資買超") > 0, lambda r: "外資今日買超"),
    ("籌碼", -5, lambda d: _有(d, "外資買超") < 0, lambda r: "外資今日賣超"),
    ("籌碼", -10, lambda d: (_有(d, "融資5日增減") >= 10) & (d["20日漲幅"] < 0),
     lambda r: f"股價跌、融資 5 日卻增 {r['融資5日增減']:.0f}%（散戶接刀）"),
    ("籌碼", 5, lambda d: (_有(d, "融資5日增減") <= -5) & (d["5日漲幅"] > 0),
     lambda r: f"股價漲、融資 5 日減 {abs(r['融資5日增減']):.0f}%（籌碼安定）"),
    # ----- 基本面 -----
    ("基本", 15, lambda d: _有(d, "營收年增率") >= 20, lambda r: f"月營收年增 {r['營收年增率']:.1f}%"),
    ("基本", 5, lambda d: _有(d, "營收年增率").between(0, 20, "left"), lambda r: f"月營收年增 {r['營收年增率']:.1f}%"),
    ("基本", -15, lambda d: _有(d, "營收年增率") <= -10, lambda r: f"月營收年減 {abs(r['營收年增率']):.1f}%"),
    ("基本", 5, lambda d: _有(d, "累計營收年增率") >= 10, lambda r: f"今年累計營收年增 {r['累計營收年增率']:.1f}%"),
    ("基本", -5, lambda d: _有(d, "累計營收年增率") <= -10, lambda r: f"今年累計營收年減 {abs(r['累計營收年增率']):.1f}%"),
    ("基本", 10, lambda d: _有(d, "營收創新高") == True, lambda r: "月營收創新高"),  # noqa: E712
    ("基本", 5, lambda d: _有(d, "近三季EPS") > 0, lambda r: f"近三季 EPS {r['近三季EPS']:.2f} 元"),
    ("基本", -20, lambda d: _有(d, "近三季EPS") < 0, lambda r: f"近三季 EPS 虧損 {r['近三季EPS']:.2f} 元"),
    ("基本", 5, lambda d: _有(d, "毛利率年增") >= 1, lambda r: f"毛利率較去年同季增 {r['毛利率年增']:.1f} 個百分點"),
    ("基本", -5, lambda d: _有(d, "毛利率年增") <= -1, lambda r: f"毛利率較去年同季減 {abs(r['毛利率年增']):.1f} 個百分點"),
    ("基本", 5, lambda d: (d["本益比"] > 0) & (d["本益比"] <= 15), lambda r: f"本益比 {r['本益比']:.1f} 偏低"),
    ("基本", -5, lambda d: d["本益比"] >= 40, lambda r: f"本益比 {r['本益比']:.1f} 偏高"),
    ("基本", 5, lambda d: d["殖利率"] >= 5, lambda r: f"殖利率 {r['殖利率']:.1f}%"),
    # ----- 市場面（大盤氣氛、所屬族群強弱、跟大盤比的相對強弱） -----
    ("市場", 10, lambda d: d["大盤分數"] >= 60, lambda r: f"大盤偏多（{r['大盤分數']:.0f} 分）"),
    ("市場", -10, lambda d: d["大盤分數"] <= 40, lambda r: f"大盤偏空（{r['大盤分數']:.0f} 分）"),
    ("市場", 5, lambda d: d["族群排名"] >= 0.75, lambda r: f"{r['產業']}族群近 20 日強勢（{r['族群20日']:+.1f}%）"),
    ("市場", -5, lambda d: d["族群排名"] <= 0.25, lambda r: f"{r['產業']}族群近 20 日弱勢（{r['族群20日']:+.1f}%）"),
    ("市場", 15, lambda d: d["贏大盤20日"] >= 5, lambda r: f"近 20 日贏大盤 {r['贏大盤20日']:.1f}%"),
    ("市場", -15, lambda d: d["贏大盤20日"] <= -5, lambda r: f"近 20 日輸大盤 {abs(r['贏大盤20日']):.1f}%"),
    ("市場", 5, lambda d: d["贏大盤5日"] >= 3, lambda r: f"近 5 日贏大盤 {r['贏大盤5日']:.1f}%"),
    ("市場", -5, lambda d: d["贏大盤5日"] <= -3, lambda r: f"近 5 日輸大盤 {abs(r['贏大盤5日']):.1f}%"),
]
# 權重依 data/score_backtest.json 的歷史驗證調整（2026-10：基本面最有效，技術、市場面平均效果偏負）
評分權重 = {"技術": 0.15, "籌碼": 0.25, "基本": 0.50, "市場": 0.10}


def 評分看法(分):
    if pd.isna(分):
        return "—"
    return "強勢" if 分 >= 70 else "偏多" if 分 >= 58 else "中性" if 分 > 42 else "偏空" if 分 > 30 else "弱勢"


def 大盤評分(加權, 今日):
    """大盤氣氛 0～100 分：指數均線、上漲家數、外資買賣超金額。回傳 dict（分數、看法、利多、利空、數字）。"""
    多, 空, 數 = [], [], {}

    def 看(條件, 分, 文字):
        if 條件:
            (多 if 分 > 0 else 空).append((abs(分), 文字))
    if 加權 is not None and len(加權) >= 60:
        收 = 加權["close"].astype(float).reset_index(drop=True)
        現, 月, 季 = 收.iloc[-1], 收.tail(20).mean(), 收.tail(60).mean()
        數.update(加權=現, MA20=月, MA60=季, 漲5日=(現 / 收.iloc[-6] - 1) * 100, 漲20日=(現 / 收.iloc[-21] - 1) * 100)
        看(現 >= 月, 10, f"加權指數站上月線（{月:,.0f}）")
        看(現 < 月, -10, f"加權指數跌破月線（{月:,.0f}）")
        看(現 >= 季, 10, f"加權指數站上季線（{季:,.0f}）")
        看(現 < 季, -10, f"加權指數跌破季線（{季:,.0f}）")
        看(月 > 季, 5, "月線在季線之上，中期趨勢向上")
        看(月 <= 季, -5, "月線在季線之下，中期趨勢向下")
        看(數["漲20日"] >= 5, 5, f"指數近 20 日漲 {數['漲20日']:.1f}%")
        看(數["漲20日"] <= -5, -5, f"指數近 20 日跌 {abs(數['漲20日']):.1f}%")
    股 = 今日[今日["代號"].str.fullmatch(r"\d{4}") & (今日["收盤"] > 0)]
    漲, 跌 = int((股["漲跌幅"] > 0).sum()), int((股["漲跌幅"] < 0).sum())
    數.update(上漲=漲, 下跌=跌)
    if 漲 + 跌:
        比 = 漲 / (漲 + 跌)
        看(比 >= 0.6, 10, f"上漲家數多（{漲} 漲／{跌} 跌）")
        看(比 <= 0.4, -10, f"下跌家數多（{漲} 漲／{跌} 跌）")
    if "外資買超" in 今日.columns and 今日["外資買超"].notna().any():
        金額 = float((今日["外資買超"] * 1000 * 今日["收盤"]).sum() / 1e8)
        數["外資億"] = 金額
        看(金額 >= 50, 10, f"外資買超約 {金額:,.0f} 億")
        看(0 < 金額 < 50, 5, f"外資小買約 {金額:,.0f} 億")
        看(-50 < 金額 < 0, -5, f"外資小賣約 {abs(金額):,.0f} 億")
        看(金額 <= -50, -10, f"外資賣超約 {abs(金額):,.0f} 億")
    分數 = int(np.clip(50 + sum(s for s, _ in 多) - sum(s for s, _ in 空), 0, 100))
    return {"分數": 分數, "看法": 評分看法(分數), "利多": [t for _, t in 多], "利空": [t for _, t in 空], "數字": 數}


def 每日評分(今日, 加權=None, 大盤=None):
    """全部股票（含上櫃、ETF）打分數。回傳以代號為索引的表：總分、技術、籌碼、基本、市場、看法。"""
    大盤 = 大盤 or 大盤評分(加權, 今日)
    d = 今日[今日["收盤"] > 0].set_index("代號", drop=False).copy()
    if "產業" not in d.columns:
        d = d.join(_股本表(), on="代號")
    d["大盤分數"] = 大盤["分數"]
    # 族群強弱：族群內市值加權的 20 日漲幅，在所有族群裡排第幾（0 最弱、1 最強）
    g = d[~d["代號"].str.startswith("00") & d["產業"].fillna("").ne("") & d["20日漲幅"].notna()]
    權 = (g["收盤"] * g["發行股數"]).fillna(0)
    族 = (g["20日漲幅"] * 權).groupby(g["產業"]).sum() / 權.groupby(g["產業"]).sum().replace(0, np.nan)
    族 = 族.dropna()
    d["族群20日"] = d["產業"].map(族)
    d["族群排名"] = d["產業"].map(族.rank(pct=True))
    數 = 大盤["數字"]
    d["贏大盤20日"] = d["20日漲幅"] - 數.get("漲20日", np.nan)
    d["贏大盤5日"] = d["5日漲幅"] - 數.get("漲5日", np.nan)
    分 = {面: pd.Series(50.0, index=d.index) for 面 in 評分權重}
    for 面, 點, 條件, _ in 評分規則:
        分[面] += 點 * 條件(d).fillna(False).astype(bool)
    結果 = pd.DataFrame({面: s.clip(0, 100) for 面, s in 分.items()})
    # 沒有資料的面向不算（例如 ETF 沒有營收、EPS）
    結果.loc[_有(d, "外資買超").isna(), "籌碼"] = np.nan
    沒基本 = _有(d, "營收年增率").isna() & _有(d, "近三季EPS").isna() & (d["本益比"].fillna(0) <= 0)
    結果.loc[沒基本, "基本"] = np.nan
    權重 = pd.DataFrame({面: 結果[面].notna() * w for 面, w in 評分權重.items()})
    結果["總分"] = ((結果.fillna(0) * 權重).sum(axis=1) / 權重.sum(axis=1)).round()
    結果["看法"] = 結果["總分"].map(評分看法)
    for 欄 in ("名稱", "產業", "收盤", "漲跌幅", "5日均量"):
        結果[欄] = d[欄] if 欄 in d.columns else np.nan
    結果["上市櫃"] = d["市場"]  # 「市場」已經是評分面向的名字
    return 結果[["名稱", "總分", "看法", "技術", "籌碼", "基本", "市場", "收盤", "漲跌幅", "產業", "上市櫃", "5日均量"]], d


def 評分明細(d, 代號):
    """某一檔各面向的加分、扣分理由。d 是 每日評分() 回傳的第二個表。"""
    if 代號 not in d.index:
        return {}
    列 = d.loc[[代號]]
    r = 列.iloc[0]
    明細 = {面: {"利多": [], "利空": []} for 面 in 評分權重}
    for 面, 點, 條件, 文字 in 評分規則:
        try:
            if bool(條件(列).fillna(False).iloc[0]):
                明細[面]["利多" if 點 > 0 else "利空"].append(f"{文字(r)}（{點:+d}）")
        except (KeyError, TypeError, ValueError):
            continue
    return 明細


def 今昨評分(指標, 基本面, 加權):
    """最新一天的評分，加上「較前一交易日」的分數變化（前一天的基本面用同一份最新資料）。"""
    日們 = sorted(指標["date"].unique())
    def 那天(日):
        當日 = 加基本面(指標[指標["date"] == 日], 基本面)
        權 = None if 加權 is None else 加權[加權["date"] <= 日]
        大 = 大盤評分(權, 當日)
        分, d = 每日評分(當日, 權, 大)
        return 分, d, 大
    分, d, 大 = 那天(日們[-1])
    分["較昨日"] = np.nan
    if len(日們) > 1:
        昨, _, 昨大 = 那天(日們[-2])
        分["較昨日"] = 分["總分"] - 昨["總分"].reindex(分.index)
        大["較昨日"] = 大["分數"] - 昨大["分數"]
    大["日期"] = pd.Timestamp(日們[-1])
    return 分, d, 大


def 集保歷史(代號, 週數=26):
    """從集保結算所網站查這檔過去幾週的股權分散表（官方開放資料只有最新一週）。
    回傳 date、big1000（千張大戶 %）、big400（400 張以上 %）、retail（50 張以下 %）、holders（股東人數）。"""
    import re
    from concurrent.futures import ThreadPoolExecutor
    import requests

    網址 = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
    標頭 = {"User-Agent": "Mozilla/5.0"}
    with requests.Session() as s:
        頁 = s.get(網址, headers=標頭, timeout=20).text
        日期們 = re.findall(r'<option[^>]*value="(\d{8})"', 頁)[:週數]
        權杖 = re.search(r'name="SYNCHRONIZER_TOKEN"[^>]*value="([^"]+)"', 頁)
        if not 日期們 or not 權杖:
            return None
        cookie = s.cookies.get_dict()

    def 查(日):
        with requests.Session() as s2:
            s2.cookies.update(cookie)
            # 每次查詢都要新的權杖，所以先重新開一次查詢頁
            頁2 = s2.get(網址, headers=標頭, timeout=20).text
            t = re.search(r'name="SYNCHRONIZER_TOKEN"[^>]*value="([^"]+)"', 頁2)
            r = s2.post(網址, headers=標頭, timeout=20, data={
                "SYNCHRONIZER_TOKEN": t.group(1) if t else "", "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
                "method": "submit", "firDate": 日期們[0], "scaDate": 日, "sqlMethod": "StockNo",
                "stockNo": 代號, "stockName": ""})
        列們 = re.findall(r"<tr>\s*<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*>\s*([\d,]+)\s*</td>"
                        r"\s*<td[^>]*>\s*([\d,]+)\s*</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>", r.text)
        級 = {int(a): (int(b.replace(",", "")), float(d)) for a, b, _, d in 列們}
        if 15 not in 級:
            return None
        return {"date": pd.Timestamp(日), "big1000": 級[15][1], "big400": sum(級[k][1] for k in range(12, 16) if k in 級),
                "retail": sum(級[k][1] for k in range(1, 9) if k in 級),
                "holders": sum(級[k][0] for k in range(1, 16) if k in 級)}

    with ThreadPoolExecutor(6) as 工人:
        結果 = [x for x in 工人.map(查, 日期們) if x]
    return pd.DataFrame(結果).sort_values("date", ignore_index=True) if 結果 else None


def 內部人歷史(代號, 月數=7):
    """從公開資訊觀測站查這檔近幾個月的董監經理人、大股東持股（同一人有多個職稱只算一次）。
    回傳 month、insider（內部人持股）、directors（董監持股）、pledged（設質）股數；查不到回傳 None。"""
    import re
    from concurrent.futures import ThreadPoolExecutor
    import requests

    今 = pd.Timestamp.now(tz="Asia/Taipei")
    月們 = [(今 - pd.DateOffset(months=i)) for i in range(1, 月數 + 2)]

    def 查(月):
        try:
            r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_stapap1", headers={"User-Agent": "Mozilla/5.0"},
                              timeout=20, data={"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
                                                "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "isnew": "false",
                                                "co_id": 代號, "year": str(月.year - 1911), "month": f"{月.month:02d}"})
        except requests.RequestException:
            return None
        人們 = {}
        for 列 in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S | re.I):
            格 = [re.sub(r"<[^>]+>|&nbsp;|\s", "", c) for c in re.findall(r"<td[^>]*>(.*?)</td>", 列, re.S | re.I)]
            if len(格) < 5 or not re.fullmatch(r"[\d,]+", 格[3] or "x"):
                continue
            職稱, 姓名 = 格[0], 格[1]
            持股, 設質 = float(格[3].replace(",", "")), float((格[4] or "0").replace(",", ""))
            舊 = 人們.get(姓名, {"持股": 0, "設質": 0, "董監": False})
            人們[姓名] = {"持股": max(舊["持股"], 持股), "設質": max(舊["設質"], 設質),
                        "董監": 舊["董監"] or bool(re.search("董事|監察人", 職稱))}
        if not 人們:
            return None
        return {"month": f"{月.year}-{月.month:02d}", "insider": sum(p["持股"] for p in 人們.values()),
                "directors": sum(p["持股"] for p in 人們.values() if p["董監"]),
                "pledged": sum(p["設質"] for p in 人們.values())}

    with ThreadPoolExecutor(4) as 工人:
        結果 = [x for x in 工人.map(查, 月們) if x]
    return pd.DataFrame(結果).sort_values("month", ignore_index=True) if 結果 else None


# ========== 15. FLOW：股價、週轉率、千張大戶、三大法人變化（網站、AI 分析、PDF 共用） ==========
def 變化解讀(歷史, 週轉, 大):
    """白話解讀（Markdown 條列文字）。歷史：這檔近 N 日的指標表；週轉：每日週轉率 %；大：每週千張大戶表。"""
    說明 = []
    漲 = (歷史["還原價"].iloc[-1] / 歷史["還原價"].iloc[0] - 1) * 100
    說明.append(f"**股價**：這段期間 {'上漲' if 漲 >= 0 else '下跌'} {abs(漲):.1f}%"
              f"（{歷史['收盤'].iloc[0]:,.2f} → {歷史['收盤'].iloc[-1]:,.2f}）。")
    if 週轉.notna().any():
        近, 平 = 週轉.tail(5).mean(), 週轉.mean()
        倍 = 近 / 平 if 平 else np.nan
        狀態 = "明顯變熱" if 倍 >= 1.5 else ("變冷清" if 倍 <= 0.6 else "跟平常差不多")
        說明.append(f"**週轉率**：近 5 日平均 {近:.2f}%，期間平均 {平:.2f}%，交易{狀態}。")
    if 大 is not None and len(大) >= 2:
        差 = 大["big1000"].iloc[-1] - 大["big1000"].iloc[0]
        說明.append(f"**千張大戶**：{大['date'].iloc[0]:%m/%d} {大['big1000'].iloc[0]:.2f}% → {大['date'].iloc[-1]:%m/%d} "
                  f"{大['big1000'].iloc[-1]:.2f}%（{差:+.2f} 個百分點），"
                  + ("籌碼往大戶集中。" if 差 >= 0.5 else "大戶在減碼。" if 差 <= -0.5 else "變化不大。"))
    elif 大 is not None and len(大) == 1:
        說明.append(f"**千張大戶**：目前只有 {大['date'].iloc[0]:%m/%d} 一週的資料（{大['big1000'].iloc[0]:.2f}%）。")
    else:
        說明.append("**千張大戶**：集保資料暫時查不到。")
    if "外資買超" in 歷史.columns:
        合 = {名: 歷史[欄].sum() for 欄, 名 in (("外資買超", "外資"), ("投信買超", "投信"), ("自營買超", "自營商"))}
        說明.append("**三大法人**：期間累計 " + "、".join(f"{k}{'買超' if v >= 0 else '賣超'} {abs(v):,.0f} 張"
                                               for k, v in 合.items()) + "。")
    return 說明


def 變化摘要(歷史, 週轉, 大):
    """給 AI 分析的文字：白話解讀＋每 20 個交易日一段的數字表。"""
    行們 = [f"- {x.replace('**', '')}" for x in 變化解讀(歷史, 週轉, 大)]
    h = 歷史.assign(週轉率=週轉.values).reset_index(drop=True)
    段落們 = [h.iloc[i:i + 20] for i in range(max(len(h) - 20 * (len(h) // 20), 0), len(h), 20)]
    行們.append("| 期間 | 收盤 | 期間漲跌 | 平均週轉率 | 千張大戶 | 外資 | 投信 | 自營商 |")
    行們.append("|---|---|---|---|---|---|---|---|")
    for 段 in 段落們:
        if 段.empty:
            continue
        末 = 段["date"].iloc[-1]
        大值 = "—"
        if 大 is not None and len(大):
            前 = 大[大["date"] <= 末 + pd.Timedelta(days=3)]
            大值 = f"{前['big1000'].iloc[-1]:.2f}%" if len(前) else "—"
        起 = 段.index[0]
        基 = h["還原價"].iloc[起 - 1] if 起 > 0 else 段["還原價"].iloc[0]  # 跟上一段最後一天比
        漲 = (段["還原價"].iloc[-1] / 基 - 1) * 100
        法 = ([f"{段[c].sum():+,.0f}" for c in ("外資買超", "投信買超", "自營買超")]
             if "外資買超" in 段.columns else ["—"] * 3)
        行們.append(f"| {段['date'].iloc[0]:%m/%d}~{末:%m/%d} | {段['收盤'].iloc[-1]:,.2f} | {漲:+.1f}% | "
                  f"{段['週轉率'].mean():.2f}% | {大值} | " + " | ".join(法) + " |")
    return "\n".join(行們)


# ========== 14. 評分回測：分數高的股票之後真的比較會漲嗎？ ==========
def 評分回測(持有天數=20, 最少量=500):
    """每月最後一個交易日用「當時看得到的資料」打分數，比較之後 N 個交易日的報酬。
    營收用當時已公布的月份（假設次月 10 日前公布）；EPS、毛利率沒有歷史資料，所以不算。
    很吃記憶體，在 GitHub Actions 算好存成 data/score_backtest.json，網站只讀結果。"""
    指 = 計算指標(讀取資料庫())
    加 = 讀取加權指數()
    股 = _股本表()
    營收 = pd.read_csv(資料夾 / "fundamental" / "revenue_history.csv", dtype={"code": str})
    營收["m"] = pd.PeriodIndex(營收["month"], freq="M")
    營收 = 營收.set_index(["code", "m"])["revenue"]
    有的月 = set(營收.index.get_level_values("m"))
    日們 = pd.DatetimeIndex(sorted(指["date"].unique()))
    期 = 日們.to_period("M")
    月底 = 日們[np.r_[期[1:] != 期[:-1], True]]
    還原 = 指.pivot_table(index="date", columns="代號", values="還原價")
    未來 = (還原.shift(-持有天數) / 還原 - 1) * 100
    結果 = []
    for 日 in 月底[12:]:  # 前 12 個月要拿來算均線、52 週高點
        if pd.isna(未來.loc[日]).all():
            continue
        當 = 指[指["date"] == 日].join(股, on="代號")
        月 = (日 - pd.Timedelta(days=10)).to_period("M") - 1
        if 月 in 有的月 and 月 - 12 in 有的月:
            當["營收年增率"] = 當["代號"].map((營收.xs(月, level="m") / 營收.xs(月 - 12, level="m") - 1) * 100)
        分, _ = 每日評分(當, 加[加["date"] <= 日])
        分["報酬"] = 未來.loc[日].reindex(分.index)
        分 = 分[(分["5日均量"] >= 最少量) & ~分.index.str.startswith("00")].dropna(subset=["報酬", "總分"])
        分["date"] = 日
        結果.append(分[["date", "總分", "看法", "技術", "籌碼", "基本", "市場", "報酬"]])
    return pd.concat(結果) if 結果 else None


def 評分回測摘要(表, 持有天數=20):
    """把 評分回測() 的結果整理成網站要顯示的數字（超額報酬＝減掉同一天所有股票的平均）。"""
    表 = 表.copy()
    表["超額"] = 表["報酬"] - 表.groupby("date")["報酬"].transform("mean")
    def 相關(欄):
        s = 表.groupby("date")[[欄, "報酬"]].apply(lambda g: g[欄].rank().corr(g["報酬"].rank())).dropna()
        return {"IC": round(float(s.mean()), 4), "t": round(float(s.mean() / s.std() * np.sqrt(len(s))), 2),
                "勝率": round(float((s > 0).mean()), 3)}
    def 分組(欄, 資料=表):
        組 = 資料.groupby("date")[欄].transform(lambda x: pd.qcut(x.rank(method="first"), 5, labels=False))
        g = 資料.groupby(組)
        return [{"組": int(k) + 1, "超額": round(float(v["超額"].mean()), 3), "報酬": round(float(v["報酬"].mean()), 3),
                 "贏過平均": round(float((v["超額"] > 0).mean()), 3)} for k, v in g]
    日們 = sorted(表["date"].unique())
    中 = 日們[len(日們) // 2]
    看法 = 表.groupby("看法").agg(檔次=("超額", "size"), 超額=("超額", "mean"), 報酬=("報酬", "mean"))
    看法 = 看法.reindex([k for k in ("強勢", "偏多", "中性", "偏空", "弱勢") if k in 看法.index])
    return {
        "計算時間": pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y/%m/%d %H:%M"),
        "起": f"{pd.Timestamp(日們[0]):%Y/%m/%d}", "迄": f"{pd.Timestamp(日們[-1]):%Y/%m/%d}",
        "期數": len(日們), "平均檔數": int(表.groupby("date").size().mean()), "持有天數": 持有天數,
        "權重": 評分權重,
        "相關": {欄: 相關(欄) for 欄 in ("總分", "技術", "籌碼", "基本", "市場")},
        "五分組": {欄: 分組(欄) for 欄 in ("總分", "技術", "籌碼", "基本", "市場")},
        "前後半": {"前半": 分組("總分", 表[表["date"] < 中]), "後半": 分組("總分", 表[表["date"] >= 中])},
        "看法": [{"看法": k, "檔次": int(r["檔次"]), "超額": round(float(r["超額"]), 3), "報酬": round(float(r["報酬"]), 3)}
               for k, r in 看法.iterrows()],
    }


def 更新評分回測(強制=False, 間隔天數=25):
    """GitHub Actions 每天呼叫；距離上次超過 間隔天數 才重算（約幾分鐘）。"""
    import json
    檔 = 資料夾 / "score_backtest.json"
    if 檔.exists() and not 強制:
        舊 = json.loads(檔.read_text())
        if 舊.get("權重") == 評分權重 and (pd.Timestamp.now() - pd.Timestamp(舊.get("計算日", "2000-01-01"))).days < 間隔天數:
            print("評分回測：還不用重算")
            return
    表 = 評分回測()
    if 表 is None:
        return
    摘要 = 評分回測摘要(表)
    摘要["計算日"] = f"{pd.Timestamp.now():%Y-%m-%d}"
    檔.write_text(json.dumps(摘要, ensure_ascii=False, indent=1))
    print("評分回測：已更新", 摘要["相關"]["總分"])


def 讀取評分回測():
    import json
    檔 = 資料夾 / "score_backtest.json"
    return json.loads(檔.read_text()) if 檔.exists() else None


# ========== 16. 使用統計：來客數、產生過 AI 報告的個股 ==========
def 列出AI報告(設定):
    """回傳 {代號: 紀錄們（新到舊）}，讀 ai-reports 分支 reports/ 底下的全部報告。"""
    import json, requests

    權杖 = 清理金鑰(設定.get("GITHUB_TOKEN"))
    if not 權杖:
        資料 = 資料夾.parent / "ai_reports"
        return {f.stem: json.loads(f.read_text("utf-8")) for f in sorted(資料.glob("*.json"))
                if f.stem[:1].isdigit()} if 資料.exists() else {}
    倉庫 = 設定.get("AI_REPO", "gelu27/Stock-lab")
    回應 = requests.get(f"https://api.github.com/repos/{倉庫}/contents/reports", timeout=15,
                        params={"ref": 設定.get("AI_BRANCH", "ai-reports")},
                        headers={"Authorization": f"Bearer {權杖}", "Accept": "application/vnd.github+json"})
    if 回應.status_code == 404:
        return {}
    回應.raise_for_status()
    代號們 = [x["name"][:-5] for x in 回應.json() if x["name"].endswith(".json")]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(6) as 工人:
        return dict(zip(代號們, 工人.map(lambda c: 讀取AI紀錄(c, 設定), 代號們)))


def 記錄來訪(設定, 自己=False, 訪客碼=""):
    """每個瀏覽階段記一次：stats.json 的 {日期: {"次數", "自己", "訪客": [代碼]}}（訪客碼是 IP 加密後的前 8 碼）。"""
    import datetime as dt

    今天 = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    for _ in range(3):  # 同時有人存檔會衝突，重試
        try:
            統計 = 讀取設定檔(設定, "stats.json") or {}
            日 = 統計.setdefault(今天, {"次數": 0, "自己": 0, "訪客": []})
            日["次數"] += 1
            日["自己"] += int(bool(自己))
            if 訪客碼 and not 自己 and 訪客碼 not in 日["訪客"]:
                日["訪客"].append(訪客碼)
            儲存設定檔(設定, "stats.json", 統計, f"來訪 {今天}")
            return
        except Exception:
            continue


def 讀取來訪(設定):
    return 讀取設定檔(設定, "stats.json") or {}


# ========== 17. 處置／注意股、借券賣出、重要日程 ==========
def 讀取警示():
    """{代號: "⚠️ 處置中（至 10/27）：第二次處置…"}，處置優先於注意。"""
    f = 資料夾 / "warning.csv"
    if not f.exists():
        return {}
    t = pd.read_csv(f, dtype={"code": str}, parse_dates=["date", "end"])
    結果 = {}
    for _, r in t.sort_values("type", key=lambda s: s.map({"處置": 0, "注意": 1})).iterrows():
        if r["code"] in 結果:
            continue
        if r["type"] == "處置":
            結果[r["code"]] = f"處置中（至 {r['end']:%m/%d}）：{r['reason']}" if pd.notna(r["end"]) else f"處置中：{r['reason']}"
        else:
            結果[r["code"]] = f"注意股（{r['date']:%m/%d} 公告）：{r['reason']}"
    return 結果


def 讀取借券(代號, 天數=120):
    """這檔每天的借券賣出（張）：date、sbl_sell 當日借券賣出、sbl_return 當日還券、sbl_balance 餘額、sbl_limit 可借券賣出限額。"""
    表們 = []
    for f in sorted((資料夾 / "sbl").glob("*.csv.gz"))[-天數:]:
        t = pd.read_csv(f, dtype={"code": str})
        t = t[t["code"] == 代號]
        if len(t):
            表們.append(t.assign(date=pd.Timestamp(f.name[:8])))
    return pd.concat(表們, ignore_index=True) if 表們 else None


def 重要日程(代號們=None, 天數=30, 今天=None):
    """近 天數 天的法說會（代號們給了就只看這些）＋月營收、財報公布期限。回傳 DataFrame（日期、類型、股票、說明）。"""
    import datetime as dt
    今天 = pd.Timestamp(今天 or dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date())
    迄 = 今天 + pd.Timedelta(days=天數)
    列們 = []
    f = 資料夾 / "calendar.csv"
    if f.exists():
        t = pd.read_csv(f, dtype={"code": str}, parse_dates=["date"])
        t = t[(t["date"] >= 今天) & (t["date"] <= 迄)]
        if 代號們 is not None:
            t = t[t["code"].isin(list(代號們))]
        for _, r in t.iterrows():
            列們.append({"日期": r["date"], "類型": "法說會", "股票": f"{r['code']} {r['name']}", "代號": r["code"],
                       "說明": f"{r['time']} {r['place']}｜{r['summary']}"})
    # 固定期限：每月 10 日前公布上月營收；財報 Q1 5/15、Q2 8/14、Q3 11/14、年報 3/31
    for 月 in pd.period_range(今天, 迄, freq="M"):
        日 = pd.Timestamp(月.year, 月.month, 10)
        if 今天 <= 日 <= 迄:
            列們.append({"日期": 日, "類型": "月營收", "股票": "全部上市櫃", "代號": "",
                       "說明": f"{(月 - 1).month} 月營收公布期限（多數公司在這之前陸續公布）"})
    for 年 in {今天.year, 迄.year}:
        for 月, 日, 名 in ((3, 31, f"{年 - 1} 年報"), (5, 15, "第一季財報"), (8, 14, "第二季財報"), (11, 14, "第三季財報")):
            d = pd.Timestamp(年, 月, 日)
            if 今天 <= d <= 迄:
                列們.append({"日期": d, "類型": "財報", "股票": "全部上市櫃", "代號": "", "說明": f"{名}公布期限"})
    return pd.DataFrame(列們, columns=["日期", "類型", "股票", "代號", "說明"]).sort_values("日期", ignore_index=True)


def 驗收AI報告(紀錄, 價格):
    """看報告之後股價先碰到目標價還是停損價。價格：這檔每日 date、high、low、收盤。
    回傳 {"結果": 達標／停損／進行中／無目標價, "日期", "天數"}。"""
    建議 = 紀錄.get("建議") or 拆解AI建議(紀錄.get("內容", ""))[1] or {}
    def 數(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return np.nan
    目標, 停損, 當時 = 數(建議.get("目標價合理")), 數(建議.get("停損")), 數(紀錄.get("收盤"))
    起 = pd.Timestamp(紀錄.get("資料日期") or str(紀錄.get("時間", ""))[:10])
    之後 = 價格[價格["date"] > 起].sort_values("date")
    結果 = {"結果": "無目標價", "日期": pd.NaT, "天數": len(之後), "目標": 目標, "停損": 停損}
    if pd.isna(目標) or pd.isna(當時):
        return 結果
    向上 = 目標 >= 當時
    for _, r in 之後.iterrows():
        碰目標 = r["high"] >= 目標 if 向上 else r["low"] <= 目標
        碰停損 = pd.notna(停損) and (r["low"] <= 停損 if 向上 else r["high"] >= 停損)
        if 碰停損:  # 同一天兩個都碰到，保守算停損
            return dict(結果, 結果="停損", 日期=r["date"])
        if 碰目標:
            return dict(結果, 結果="達標", 日期=r["date"])
    return dict(結果, 結果="進行中")
