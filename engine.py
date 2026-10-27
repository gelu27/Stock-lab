# 計算核心：讀資料庫、算技術指標、選股、回測
# 想調整選股或回測規則，主要改這個檔案

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

資料夾 = Path(__file__).parent / "data"

手續費率 = 0.001425  # 買賣各收一次（未算券商折扣）
證交稅率 = 0.003     # 賣出才收
ETF證交稅率 = 0.001  # 股票型 ETF（00 開頭）賣出稅率


def 稅率(代號):
    return ETF證交稅率 if str(代號).startswith("00") else 證交稅率

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


def 近四季EPS表():
    """每檔最新一季往回連續四季的 EPS 合計（income.csv 是今年累計，先換成單季）。回傳 DataFrame（近四季EPS、EPS季度、單季EPS）。"""
    f = 資料夾 / "fundamental" / "income.csv"
    if not f.exists():
        return pd.DataFrame(columns=["近四季EPS", "EPS季度", "單季EPS"])
    t = pd.read_csv(f, dtype={"code": str})
    t = t.dropna(subset=["eps"]).sort_values(["code", "quarter"]).copy()
    t["序"] = t["quarter"].str[:4].astype(int) * 4 + t["quarter"].str[-1].astype(int)
    前 = t.groupby("code")[["序", "eps", "revenue"]].shift()
    第一季 = t["quarter"].str[-1] == "1"
    連續 = 前["序"] == t["序"] - 1
    t["單季"] = np.where(第一季, t["eps"], np.where(連續, t["eps"] - 前["eps"], np.nan))
    t["單季營收"] = np.where(第一季, t["revenue"], np.where(連續, t["revenue"] - 前["revenue"], np.nan))
    # 連續四季才加總：往回第 3 筆的季序要剛好差 3
    斷 = t.groupby("code")["序"].shift(3) != t["序"] - 3
    for 欄, 新欄 in (("單季", "近四季"), ("單季營收", "近四季營收")):
        t[新欄] = t.groupby("code")[欄].transform(lambda s: s.rolling(4).sum())
        t.loc[斷, 新欄] = np.nan
    最新 = t.groupby("code").tail(1).set_index("code")
    return pd.DataFrame({"近四季EPS": 最新["近四季"].round(2), "EPS季度": 最新["quarter"],
                         "單季EPS": 最新["單季"].round(2), "累計EPS": 最新["eps"],
                         "近四季營收": 最新["近四季營收"]})


def EPS試算(營收表, EPS表, 月份):
    """用月營收試算還沒出財報月份的 EPS：每 1 元營收賺多少 EPS 用近四季（近四季 EPS ÷ 近四季營收），
    乘上當月營收得「單月 EPS 試算」；今年已公布的累計 EPS 加上之後各月試算得「今年累計 EPS 試算」。
    金融股沒有營收資料，不試算。2025Q4～2026Q2 回測：和實際單季 EPS 相關 0.74～0.91，EPS ≥ 1 元的股票誤差中位數約 2～4 成。"""
    寬 = 營收表
    年, 月 = int(月份[:4]), int(月份[5:])
    e = EPS表.reindex(寬.index)
    每元 = (e["近四季EPS"] / e["近四季營收"]).where(e["近四季營收"] > 0)
    單月 = (寬[月份] * 每元).round(2) if 月份 in 寬 else pd.Series(np.nan, index=寬.index)
    季年 = e["EPS季度"].str[:4].astype(float)
    季末月 = e["EPS季度"].str[-1].astype(float) * 3
    同年 = (季年 == 年) & (季末月 < 月)
    去年底 = (季年 == 年 - 1) & (季末月 == 12)
    起 = np.where(同年, 季末月 + 1, 1)
    底 = np.where(同年, e["累計EPS"], 0.0)
    今年 = pd.DataFrame({m: 寬[f"{年}-{m:02d}"] if f"{年}-{m:02d}" in 寬 else np.nan for m in range(1, 月 + 1)})
    月號 = np.arange(1, 月 + 1)
    範圍 = 月號[None, :] >= 起[:, None]
    營收和 = np.where(範圍, 今年.fillna(0).values, 0).sum(axis=1)
    缺 = (範圍 & 今年.isna().values).any(axis=1)
    累計 = pd.Series(np.where((同年 | 去年底) & ~缺, 底 + 營收和 * 每元, np.nan), index=寬.index).round(2)
    return pd.DataFrame({"單月EPS試算": 單月, "累計EPS試算": 累計})


def 月營收總表(月份=None, 基期下限=10000):
    """月營收分頁用：每檔某個月（預設最新）的營收、月增、年增、累計年增、近 5 年新高、公告日。
    營收單位千元；上月或去年同期營收低於 基期下限（千元，預設 1,000 萬）時另外標記，避免基期近零的爆量百分比。
    回傳 (表, 可選月份們)。"""
    來源 = 資料夾 / "fundamental"
    表們 = [pd.read_csv(來源 / 名, dtype={"code": str}) for 名 in ("revenue_history.csv", "revenue.csv")
          if (來源 / 名).exists()]
    if not 表們:
        return pd.DataFrame(), []
    最新 = 表們[-1] if len(表們) == 2 else pd.DataFrame(columns=["code", "month"])
    歷史 = pd.concat([t[["code", "month", "revenue"]] for t in 表們]).dropna()
    歷史 = 歷史.drop_duplicates(["code", "month"], keep="last")
    家數 = 歷史.groupby("month")["code"].nunique()
    月份們 = sorted(家數[家數 >= 50].index, reverse=True)[:13]  # 新月份剛開始公布、家數很少也要能選
    月份 = 月份 or (月份們[0] if 月份們 else None)
    if 月份 is None:
        return pd.DataFrame(), 月份們
    年, 月 = int(月份[:4]), int(月份[5:])
    上月 = f"{年 - (月 == 1)}-{12 if 月 == 1 else 月 - 1:02d}"
    去年 = f"{年 - 1}-{月:02d}"
    寬 = 歷史.pivot(index="code", columns="month", values="revenue")
    本 = 寬[月份].dropna()
    表 = pd.DataFrame({"營收": 本})
    前值 = 寬[上月].reindex(本.index) if 上月 in 寬 else pd.Series(np.nan, index=本.index)
    去值 = 寬[去年].reindex(本.index) if 去年 in 寬 else pd.Series(np.nan, index=本.index)
    表["月增"] = np.where(前值 > 0, (本 / 前值 - 1) * 100, np.nan)
    表["年增"] = np.where(去值 > 0, (本 / 去值 - 1) * 100, np.nan)
    今年月 = [f"{年}-{m:02d}" for m in range(1, 月 + 1)]
    去年月 = [f"{年 - 1}-{m:02d}" for m in range(1, 月 + 1)]
    if all(m in 寬 for m in 今年月 + 去年月):
        今累 = 寬[今年月].reindex(本.index)
        去累 = 寬[去年月].reindex(本.index)
        完整 = 今累.notna().all(axis=1) & 去累.notna().all(axis=1)
        表["今年累計"] = 今累.sum(axis=1).where(完整)
        表["去年累計"] = 去累.sum(axis=1).where(完整)
        表["累計年增"] = np.where(表["去年累計"] > 0, (表["今年累計"] / 表["去年累計"] - 1) * 100, np.nan)
    else:
        表["今年累計"] = 表["去年累計"] = 表["累計年增"] = np.nan
    # 最新月份優先用交易所公布的百分比（歷史有缺月時自己算不出來）
    if "rev_yoy" in 最新.columns:
        官 = 最新[最新["month"] == 月份].drop_duplicates("code", keep="last").set_index("code")
        for 欄, 官欄 in (("月增", "rev_mom"), ("年增", "rev_yoy"), ("累計年增", "rev_cum_yoy")):
            表[欄] = 官[官欄].reindex(表.index).combine_first(表[欄])
    表["上月營收"], 表["去年同月營收"] = 前值, 去值
    表["月增基期低"] = 前值.fillna(0) < 基期下限
    表["年增基期低"] = 去值.fillna(0) < 基期下限
    表["累計基期低"] = 表["去年累計"].notna() & (表["去年累計"] < 基期下限 * 月)
    # 近 5 年新高：比這個月之前 60 個月的最高還高（至少要有 12 個月可比）
    以前 = [m for m in 寬.columns if m < 月份][-60:]
    # 連續年增月數（到這個月為止，年增 > 0 連續幾個月）、近 3 月合計年增（比單月穩，不受春節等月份錯開影響）
    近月 = [m for m in 寬.columns if m <= 月份][-24:]
    年增們 = pd.DataFrame({m: 寬[m] / 寬[f"{int(m[:4]) - 1}{m[4:]}"] - 1 for m in 近月
                        if f"{int(m[:4]) - 1}{m[4:]}" in 寬}).reindex(本.index)
    倒 = 年增們.iloc[:, ::-1]
    未斷 = (倒 <= 0).cumsum(axis=1) == 0  # 缺資料的月份（NaN）跳過，不算中斷也不計入
    表["連增月數"] = ((倒 > 0) & 未斷).sum(axis=1).astype(int)
    三月 = 近月[-3:]
    三月去年 = [f"{int(m[:4]) - 1}{m[4:]}" for m in 三月]
    if all(m in 寬 for m in 三月 + 三月去年):
        今3, 去3 = 寬[三月].reindex(本.index), 寬[三月去年].reindex(本.index)
        有 = 今3.notna().all(axis=1) & 去3.notna().all(axis=1) & (去3.sum(axis=1) >= 基期下限 * 3)
        表["近3月年增"] = ((今3.sum(axis=1) / 去3.sum(axis=1) - 1) * 100).where(有).round(2)
    else:
        表["近3月年增"] = np.nan
    以前最高 = 寬[以前].reindex(本.index).max(axis=1)
    可比 = 寬[以前].reindex(本.index).notna().sum(axis=1) >= 12
    表["五年新高"] = 可比 & (本 > 以前最高)
    f = 來源 / "revenue_announce.csv"
    if f.exists():
        公 = pd.read_csv(f, dtype={"code": str})
        公 = 公[公["month"] == 月份].drop_duplicates("code").set_index("code")["date"]
        表["公告日"] = 公.reindex(表.index)
    else:
        表["公告日"] = np.nan
    if 月份 >= max(寬.columns):  # 只有最新月份才試算（之前的月份財報多半已經出了）
        表 = 表.join(EPS試算(寬.reindex(本.index), 近四季EPS表(), 月份))
    else:
        表["單月EPS試算"] = 表["累計EPS試算"] = np.nan
    表.index.name = "code"
    return 表, 月份們


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
       初始資金=1_000_000, 選股資料=None, 手續費折扣=1.0):
    """
    規則：每週或每月最後一個交易日收盤後選股，隔一個交易日以收盤價買進，
    每檔投入「總資產 ÷ 最多檔數」。沒入選的持股賣出；
    持有期間跌破停損或達到停利，當天收盤賣出，資金等下次調倉再投入。
    手續費折扣：例如 0.28 代表 2.8 折；ETF 證交稅 0.1%、股票 0.3%。
    """
    費 = 手續費率 * 手續費折扣
    成本 = 0.0
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
        nonlocal 現金, 成本
        部位 = 持股.pop(代號)
        現金 += 部位["市值"] * (1 - 費 - 稅率(代號))
        成本 += 部位["市值"] * (費 + 稅率(代號))
        交易紀錄.append({
            "代號": 代號, "名稱": 名稱.get(代號, ""),
            "進場日": 部位["進場日"].date(), "進場價": 部位["進場價"],
            "出場日": 日.date(), "出場價": 收盤表.at[日, 代號],
            "報酬率(%)": round((還原表.at[日, 代號] / 部位["進場還原價"] * (1 - 費) ** 2
                              * (1 - 稅率(代號)) - 1) * 100, 2),
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
                成本 += 投入 * 費
                持股[代號] = {"代號": 代號, "市值": 投入 * (1 - 費), "進場日": 日,
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
    績效 = 計算績效(曲線, 交易表, 基準)
    績效["交易成本(元)"] = 成本
    return {"曲線": 曲線, "基準": 基準, "交易": 交易表, "績效": 績效}


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
          停損=None, 停利=None, 初始資金=1_000_000, 手續費折扣=1.0, 大盤=None):
    """訊號在收盤後產生，隔一個交易日收盤價成交。大盤：0050 的指標（給了就多算 0050 同期報酬）。"""
    費, 稅 = 手續費率 * 手續費折扣, 稅率(代號)
    成本 = 0.0
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
            成本 += 現金 * 費
            股數價值, 現金, 持有中 = 現金 * (1 - 費), 0.0, True
            進場 = (r["date"], r["收盤"], r["還原價"])
        elif 待執行 == "賣" and 持有中:
            成本 += 股數價值 * (費 + 稅)
            現金, 股數價值, 持有中 = 股數價值 * (1 - 費 - 稅), 0.0, False
            交易.append(_紀錄(進場, r, "訊號出場", 費, 稅))
        待執行 = None
        if 持有中:
            漲跌 = r["還原價"] / 進場[2] - 1
            原因 = "停損" if 停損 and 漲跌 <= -停損 / 100 else ("停利" if 停利 and 漲跌 >= 停利 / 100 else None)
            if 原因:
                成本 += 股數價值 * (費 + 稅)
                現金, 股數價值, 持有中 = 股數價值 * (1 - 費 - 稅), 0.0, False
                交易.append(_紀錄(進場, r, 原因, 費, 稅))
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
        交易.append(_紀錄(進場, 表.iloc[-1], "仍持有", 費, 稅))

    曲線 = pd.Series(dict(曲線)) / 初始資金
    基準 = 表.set_index("date")["還原價"] / 表["還原價"].iloc[0]
    交易表 = pd.DataFrame(交易)
    大盤線 = None
    if 大盤 is not None and 代號 != "0050":
        大 = 大盤[(大盤["date"] >= 表["date"].iloc[0]) & (大盤["date"] <= 表["date"].iloc[-1])].set_index("date")["還原價"]
        if len(大) >= 2:
            大盤線 = 大 / 大.iloc[0]
    績效 = 計算績效(曲線, 交易表, 大盤線)
    績效["買進持有(%)"] = (基準.iloc[-1] - 1) * 100
    績效["交易成本(元)"] = 成本
    return {"曲線": 曲線, "基準": 基準, "交易": 交易表, "績效": 績效, "價格": 表, "大盤": 大盤線}


def _進出狀態(進場, 出場):
    狀態, 序列 = False, []
    for 進, 出 in zip(進場.fillna(False), 出場.fillna(False)):
        if 進 and not 狀態:
            狀態 = True
        elif 出:
            狀態 = False
        序列.append(狀態)
    return pd.Series(序列, index=進場.index)


def _紀錄(進場, r, 原因, 費=手續費率, 稅=證交稅率):
    return {"進場日": 進場[0].date(), "進場價": 進場[1], "出場日": r["date"].date(), "出場價": r["收盤"],
            "報酬率(%)": round((r["還原價"] / 進場[2] * (1 - 費) ** 2 * (1 - 稅) - 1) * 100, 2),
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


def 權值貢獻(今日, 加權, 期間="今日"):
    """上市股票對加權指數的貢獻點數（估算）。
    權重＝期初市值 ÷ 上市總市值（期初市值用 今天市值 ÷ (1＋期間漲幅) 推回去），貢獻點數＝權重 × 期間漲幅 × 期初指數。
    回傳 (表, 摘要)：表有 代號、名稱、產業、收盤、幅度、權重、貢獻點數；摘要有 估算合計、實際漲跌、期初指數。"""
    欄 = 族群期間[期間]
    天 = {"今日": 1, "5 日": 5, "20 日": 20}[期間]
    表 = 今日[(今日["市場"] == "上市") & ~今日["代號"].str.startswith("0") & (今日["收盤"] > 0)
            & 今日["發行股數"].notna()].copy()
    表["幅度"] = 表[欄].fillna(0).astype(float)
    表["市值億"] = 表["收盤"].astype(float) * 表["發行股數"] / 1e8
    表["期初市值"] = 表["市值億"] / (1 + 表["幅度"] / 100)
    表["權重"] = 表["期初市值"] / 表["期初市值"].sum() * 100
    摘要 = {"估算合計": np.nan, "實際漲跌": np.nan, "期初指數": np.nan}
    if 加權 is not None and len(加權) > 天:
        期初 = float(加權["close"].iloc[-1 - 天])
        摘要 = {"期初指數": 期初, "實際漲跌": float(加權["close"].iloc[-1]) - 期初}
        表["貢獻點數"] = 表["權重"] / 100 * 表["幅度"] / 100 * 期初
        摘要["估算合計"] = float(表["貢獻點數"].sum())
    else:
        表["貢獻點數"] = np.nan
    表 = 表.sort_values("貢獻點數", ascending=False)
    return 表[["代號", "名稱", "產業", "收盤", "幅度", "權重", "市值億", "貢獻點數"]].round(
        {"權重": 3, "市值億": 0, "貢獻點數": 2}), 摘要


def 投信拆解(指標, 變化):
    """把投信買賣超拆成「主動式 ETF」與「其他投信（一般基金、被動式 ETF）」。
    用 ETF 持股資料和法人資料都有的最新一天；主動式 ETF 用持股張數變化（含申贖，因為申贖造成的買賣也算在投信裡）。
    回傳 (日期, 表)，表欄位：代號、名稱、收盤、投信、主動ETF、主動ETF扣申贖、其他投信（張）與金額（億）。"""
    if 變化 is None or len(變化) == 0 or "投信買超" not in 指標.columns:
        return None, pd.DataFrame()
    共同 = sorted(set(pd.to_datetime(變化["date"]).unique()) & set(指標["date"].unique()))
    if not 共同:
        return None, pd.DataFrame()
    日 = pd.Timestamp(共同[-1])
    當日 = 指標[指標["date"] == 日].set_index("代號")
    變 = 變化[pd.to_datetime(變化["date"]) == 日]
    彙 = 變.groupby("code").agg(主動ETF=("delta", "sum"), 主動ETF扣申贖=("adj_delta", "sum")) / 1000
    表 = pd.DataFrame({"名稱": 當日["名稱"], "收盤": 當日["收盤"].astype(float), "投信": 當日["投信買超"].astype(float)})
    表 = 表.join(彙, how="left").fillna({"主動ETF": 0, "主動ETF扣申贖": 0})
    表 = 表[(表["投信"].fillna(0) != 0) | (表["主動ETF"] != 0)]
    表["其他投信"] = 表["投信"] - 表["主動ETF"]
    for 欄 in ("投信", "主動ETF", "其他投信"):
        表[f"{欄}金額"] = 表[欄] * 1000 * 表["收盤"] / 1e8
    return 日, 表.reset_index(names="代號").round(2)


def 焦點清單(今日, 評分=None, ETF變化=None, 警示=None, 我的=(), 檔數=15, 最少張數=500):
    """首頁「值得研究」與「需要防守」兩張清單（規則篩選，僅供研究）。
    回傳 (機會, 風險)，欄位：代號、股票、理由、收盤、漲跌幅、總分。我的＝庫存＋自選股代號，風險清單會排前面。"""
    表 = 今日[(今日["收盤"] > 0) & ~今日["代號"].str.startswith("00")].set_index("代號")
    量夠 = 表["成交張數"].fillna(0) >= 最少張數
    機會, 風險 = {}, {}

    def 記(字典, 條件, 理由):
        for c in 條件[條件.fillna(False).astype(bool)].index:
            字典.setdefault(c, []).append(理由)

    分 = 評分.reindex(表.index) if 評分 is not None else pd.DataFrame(index=表.index, columns=["總分", "較昨日"])
    記(機會, 量夠 & (分["總分"] >= 70) & (分["較昨日"] >= 10), "評分大升進入強勢")
    if "營收創新高" in 表:
        記(機會, 量夠 & (表["營收創新高"] == True) & (表.get("營收年增率", 0) >= 20), "月營收創新高、年增>20%")  # noqa: E712
    if "箱頂" in 表:
        記(機會, 量夠 & (表["收盤"] > 表["箱頂"]) & (表["量比"] >= 1.5) & (表["漲跌幅"] > 0),
           "帶量突破 20 日盤整")
    if "外資連買" in 表:
        記(機會, 量夠 & (表["外資連買"] >= 5) & (表["投信連買"] >= 3), "外資、投信連續買超")
    if ETF變化 is not None and len(ETF變化):
        最新 = ETF變化[ETF變化["date"] == ETF變化["date"].max()]
        買 = 最新[最新["adj_delta"] > 0].groupby("code")["etf"].nunique()
        記(機會, pd.Series(表.index.isin(買[買 >= 3].index), index=表.index), "3 檔以上主動式 ETF 同時加碼")

    if 警示:
        記(風險, pd.Series(表.index.isin(list(警示)), index=表.index) & 量夠, "注意股／處置股")
    記(風險, 量夠 & (分["較昨日"] <= -10) & (分["總分"] <= 42), "評分大跌轉弱")
    if "剛跌破MA10" in 表:
        記(風險, 量夠 & 表["剛跌破MA10"].astype(bool) & (表.get("法人5日買超", 0) < 0), "跌破十日線、法人 5 日賣超")
    if "融資5日增減" in 表:
        記(風險, 量夠 & (表["融資5日增減"] >= 15) & (表["5日漲幅"] < 0), "融資 5 日暴增但股價下跌")
    if "法人5日買超" in 表:
        記(風險, 量夠 & (表.get("法人5日買超", 0) <= -5000) & (表["5日漲幅"] < -5), "法人 5 日大賣、股價重挫")

    def 成表(字典, 優先=()):
        if not 字典:
            return pd.DataFrame(columns=["代號", "股票", "理由", "收盤", "漲跌幅", "總分"])
        t = pd.DataFrame({"代號": list(字典), "理由數": [len(v) for v in 字典.values()],
                          "理由": ["、".join(v) for v in 字典.values()]})
        t["我的"] = t["代號"].isin(list(優先))
        t["股票"] = np.where(t["我的"], "⭐", "") + t["代號"] + " " + t["代號"].map(表["名稱"])
        t["收盤"] = t["代號"].map(表["收盤"]).astype(float)
        t["漲跌幅"] = t["代號"].map(表["漲跌幅"]).astype(float)
        t["總分"] = t["代號"].map(分["總分"]).astype(float)
        t["成交值"] = t["代號"].map(表["成交值億"]).astype(float)
        t = t.sort_values(["我的", "理由數", "成交值"], ascending=False).head(檔數)
        return t[["代號", "股票", "理由", "收盤", "漲跌幅", "總分"]].reset_index(drop=True)

    return 成表(機會), 成表(風險, 我的)


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


# ========== 18. 資料新鮮度：每個資料來源最後更新到哪一天 ==========
def _最新檔日(子):
    檔們 = [f.name[:8] for f in (資料夾 / 子).glob("**/*.csv.gz") if f.name[:8].isdigit()]
    return pd.Timestamp(max(檔們)) if 檔們 else None


def 資料新鮮度():
    """回傳 DataFrame：資料、最新、更新頻率、狀態（✅ 正常／⚠️ 落後）。
    每日資料跟股價最新交易日比；每週、每月、每季資料看距今天數。"""
    import datetime as dt
    今天 = pd.Timestamp(dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date())
    價 = _最新檔日("prices")

    def 欄最大(檔, 欄):
        f = 資料夾 / 檔
        try:
            return pd.read_csv(f, usecols=[欄])[欄].astype(str).max() if f.exists() else None
        except Exception:
            return None

    def 期末(值, 頻):
        return (pd.Period(值, 頻) + 1).to_timestamp() if 值 else None  # 這一期資料最晚該在下一期初公布

    指數 = sorted((資料夾 / "index").glob("*.csv"))
    指數日 = pd.Timestamp(pd.read_csv(指數[-1], usecols=["date"])["date"].max()) if 指數 else None
    fx = 欄最大("fx.csv", "date")
    營 = 欄最大("fundamental/revenue.csv", "month")
    季 = 欄最大("fundamental/eps.csv", "quarter")
    內 = 欄最大("fundamental/insider.csv", "month")
    列們 = [  # (名稱, 最新, 頻率, 判斷方式, 容許)
        ("股價、成交量", 價, "每個交易日", "平日", 1),
        ("指數開高低（支撐壓力）", (lambda v: v and pd.Timestamp(v))(欄最大("index_ohlc.csv", "date")), "每個交易日", "交易日", 0),
        ("三大法人、融資券", _最新檔日("chips"), "每個交易日", "交易日", 0),
        ("加權指數", 指數日, "每個交易日", "交易日", 0),
        ("借券賣出", _最新檔日("sbl"), "每個交易日", "交易日", 0),
        ("興櫃行情", _最新檔日("esb"), "每個交易日", "交易日", 1),
        ("主動式 ETF 持股", _最新檔日("etf/holdings"), "每個交易日晚上", "交易日", 1),
        ("上市融資金額（維持率）", (lambda v: v and pd.Timestamp(v))(欄最大("margin_total.csv", "date")), "每個交易日", "交易日", 1),
        ("外資台指期未平倉", (lambda v: v and pd.Timestamp(v))(欄最大("futures_oi.csv", "date")), "每個交易日", "交易日", 1),
        ("集保大戶（千張）", _最新檔日("tdcc"), "每週", "天", 10),
        ("美元匯率", fx and pd.Timestamp(fx), "每天", "天", 5),
        ("月營收", 營 and pd.Period(營, "M").to_timestamp(), "每月 10 日前", "期末", (期末(營, "M"), 45)),
        ("內部人持股", 內 and pd.Period(內, "M").to_timestamp(), "每月 15 日前", "期末", (期末(內, "M"), 50)),
        ("季報 EPS", 季 and pd.Period(季, "Q").to_timestamp(), "每季", "期末", (期末(季, "Q"), 140)),
    ]
    交易日們 = sorted({f.name[:8] for f in (資料夾 / "prices").glob("*/*.csv.gz")})[-5:]
    結果 = []
    for 名稱, 最新, 頻率, 方式, 容許 in 列們:
        if 最新 is None or pd.isna(最新):
            結果.append({"資料": 名稱, "最新": "—", "更新頻率": 頻率, "狀態": "⚠️ 沒有資料"})
            continue
        if 方式 == "交易日":  # 跟股價比：落後超過 容許 個交易日
            落後 = sum(1 for d in 交易日們 if pd.Timestamp(d) > 最新)
            正常 = 落後 <= 容許
            說 = f"落後 {落後} 個交易日"
        elif 方式 == "平日":  # 數股價最新日之後到昨天（今天 18:30 後也算）有幾個平日沒資料，已確認休市的不算
            休市 = set()
            for f in (資料夾 / "status").glob("*.txt"):
                休市 |= {行.split(",")[0] for 行 in f.read_text().split() if 行.endswith(",closed")}
            現在 = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
            截止 = 今天 if 現在.hour * 60 + 現在.minute >= 18 * 60 + 30 else 今天 - pd.Timedelta(days=1)
            缺 = [d for d in pd.bdate_range(最新 + pd.Timedelta(days=1), 截止) if f"{d:%Y%m%d}" not in 休市]
            正常, 說 = len(缺) <= 容許, f"有 {len(缺)} 個平日沒有資料（可能是休市還沒確認）"
        elif 方式 == "期末":
            起, 天 = 容許
            差 = (今天 - 起).days
            正常, 說 = 差 <= 天, f"已 {差} 天沒有新的一期"
        else:
            差 = (今天 - 最新).days
            正常, 說 = 差 <= 容許, f"已 {差} 天沒更新"
        顯示 = f"{最新:%Y/%m}" if 方式 == "期末" and 頻率 != "每季" else (
            f"{最新.year} Q{最新.quarter}" if 頻率 == "每季" else f"{最新:%Y/%m/%d}")
        結果.append({"資料": 名稱, "最新": 顯示, "更新頻率": 頻率, "狀態": "✅ 正常" if 正常 else f"⚠️ {說}"})
    return pd.DataFrame(結果)


# ========== 19. 大盤資金面：融資維持率、期貨未平倉 ==========
def 讀取融資金額():
    f = 資料夾 / "margin_total.csv"
    if not f.exists():
        return None
    t = pd.read_csv(f, parse_dates=["date"])
    return t.set_index("date")["margin_amount"] if len(t) else None


def 融資維持率(指標):
    """上市融資維持率（估算）＝ Σ(各股融資餘額 × 收盤) ÷ 融資金額。指標要有 市場、融資餘額、收盤。回傳 Series（%）。"""
    金額 = 讀取融資金額()
    if 金額 is None or "融資餘額" not in 指標.columns:
        return None
    上市 = 指標[(指標["市場"] == "上市") & 指標["date"].isin(金額.index)]
    市值 = (上市["融資餘額"].astype("float64") * 1000 * 上市["收盤"]).groupby(上市["date"]).sum()
    return (市值 / (金額.reindex(市值.index) * 1000) * 100).dropna().round(1)


def 讀取期貨未平倉():
    """三大法人台指期（大台）多空未平倉口數淨額：date、foreign_oi、trust_oi、dealer_oi。"""
    f = 資料夾 / "futures_oi.csv"
    if not f.exists():
        return None
    return pd.read_csv(f, parse_dates=["date"]).set_index("date")


# ========== 20. 概念股、國際行事曆、市場情緒、市場狀態 ==========
def 讀取概念():
    """data/concepts.csv（concept, code）：自己整理的題材分類，一檔可以屬於好幾個概念，可直接在 GitHub 上增刪。"""
    f = 資料夾 / "concepts.csv"
    if not f.exists():
        return pd.DataFrame(columns=["concept", "code"])
    return pd.read_csv(f, dtype=str).dropna().drop_duplicates()


def 概念展開(今日):
    """把 今日 依概念展開（一檔屬於幾個概念就出現幾次），產業 欄換成概念名稱，族群資料() 可以直接用。"""
    概 = 讀取概念()
    t = 今日.merge(概.rename(columns={"code": "代號", "concept": "_概念"}), on="代號")
    return t.assign(產業=t["_概念"]).drop(columns="_概念")


def 個股概念(代號):
    概 = 讀取概念()
    return 概.loc[概["code"] == str(代號), "concept"].tolist()


def 讀取美股():
    """data/us_daily.csv 轉成 日期 × 名稱 的收盤價表（美股交易日）。"""
    f = 資料夾 / "us_daily.csv"
    if not f.exists():
        return None
    t = pd.read_csv(f, parse_dates=["date"])
    return t.pivot_table(index="date", columns="name", values="close").sort_index() if len(t) else None


經濟中文 = {
    "CPI m/m": "CPI 月增率", "CPI y/y": "CPI 年增率", "Core CPI m/m": "核心 CPI 月增率", "PPI m/m": "PPI 月增率",
    "Core PPI m/m": "核心 PPI 月增率", "Non-Farm Employment Change": "非農就業人數", "Unemployment Rate": "失業率",
    "Average Hourly Earnings m/m": "平均時薪月增率", "FOMC Statement": "FOMC 利率決策聲明", "Federal Funds Rate": "聯準會利率決策",
    "FOMC Press Conference": "聯準會主席記者會", "FOMC Meeting Minutes": "FOMC 會議紀錄", "Fed Chair Powell Speaks": "聯準會主席談話",
    "Advance GDP q/q": "GDP 初值", "Prelim GDP q/q": "GDP 修正值", "Final GDP q/q": "GDP 終值",
    "Core PCE Price Index m/m": "核心 PCE 物價月增率", "ISM Manufacturing PMI": "ISM 製造業 PMI",
    "ISM Services PMI": "ISM 服務業 PMI", "Retail Sales m/m": "零售銷售月增率", "Core Retail Sales m/m": "核心零售銷售月增率",
    "Unemployment Claims": "初領失業救濟金", "JOLTS Job Openings": "JOLTS 職缺", "ADP Non-Farm Employment Change": "ADP 就業人數",
    "CB Consumer Confidence": "諮商會消費者信心", "Prelim UoM Consumer Sentiment": "密大消費者信心初值",
    "BOJ Policy Rate": "日本央行利率決策", "Monetary Policy Statement": "央行貨幣政策聲明", "Main Refinancing Rate": "歐洲央行利率決策",
    "Official Bank Rate": "英國央行利率決策", "Manufacturing PMI": "製造業 PMI", "Caixin Manufacturing PMI": "財新製造業 PMI",
    "Caixin Services PMI": "財新服務業 PMI", "Non-Manufacturing PMI": "非製造業 PMI", "Trade Balance": "貿易收支",
    "Industrial Production y/y": "工業生產年增率", "Retail Sales y/y": "零售銷售年增率", "GDP q/y": "GDP 年增率",
    "Flash Manufacturing PMI": "製造業 PMI 初值", "Flash Services PMI": "服務業 PMI 初值", "BOJ Press Conference": "日銀總裁記者會",
    "ECB Press Conference": "歐洲央行記者會", "Durable Goods Orders m/m": "耐久財訂單月增率",
    "Employment Cost Index q/q": "就業成本指數季增率", "Tokyo Core CPI y/y": "東京核心 CPI 年增率",
    "German Prelim CPI m/m": "德國 CPI 初值月增率", "German Prelim GDP q/q": "德國 GDP 初值", "BOJ Outlook Report": "日銀經濟展望報告",
    "Advance GDP Price Index q/q": "GDP 物價指數初值", "Pending Home Sales m/m": "成屋待完成銷售", "New Home Sales": "新屋銷售",
    "Existing Home Sales": "成屋銷售", "Empire State Manufacturing Index": "紐約州製造業指數",
    "Philly Fed Manufacturing Index": "費城聯儲製造業指數", "Core PCE Price Index y/y": "核心 PCE 物價年增率",
    "CPI Flash Estimate y/y": "CPI 初值年增率", "Final Manufacturing PMI": "製造業 PMI 終值", "Final Services PMI": "服務業 PMI 終值",
}
國別 = {"USD": "美國", "JPY": "日本", "EUR": "歐元區", "GBP": "英國", "CNY": "中國"}


def 結算日(年, 月):
    """台指期月結算：每月第三個週三。"""
    d = pd.Timestamp(年, 月, 1)
    第一個週三 = d + pd.Timedelta(days=(2 - d.weekday()) % 7)
    return 第一個週三 + pd.Timedelta(days=14)


def 經濟日程(今天=None, 天數=14, 往前=0, 大型股=None):
    """國內外重要事件：國際經濟數據與央行會議、美股龍頭財報、台指期結算、月營收與財報期限、大型股法說會與除權息。
    回傳 DataFrame（日期、時間、類別、市場、事件、重要性、說明）。大型股＝要列入法說會、除權息的代號（例如市值前 50）。"""
    import datetime as dt
    import html
    今天 = pd.Timestamp(今天 or dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date())
    起, 迄 = 今天 - pd.Timedelta(days=往前), 今天 + pd.Timedelta(days=天數)
    列們 = []
    f = 資料夾 / "econ_calendar.csv"
    if f.exists():
        t = pd.read_csv(f, dtype=str).fillna("")
        t["date"] = pd.to_datetime(t["date"])
        t = t[(t["date"] >= 起) & (t["date"] <= 迄)]
        for _, r in t.iterrows():
            名 = 經濟中文.get(r["title"], r["title"])
            央行 = any(k in r["title"] for k in ("FOMC", "Federal Funds", "Policy Rate", "Refinancing", "Bank Rate", "Monetary Policy"))
            說 = "　".join(x for x in (f"預估 {r['forecast']}" if r["forecast"] else "", f"前值 {r['previous']}" if r["previous"] else "",
                                      f"公布 {r['actual']}" if r["actual"] else "") if x)
            列們.append({"日期": r["date"], "時間": r["time"], "類別": "央行會議" if 央行 else "經濟數據",
                       "市場": 國別.get(r["country"], r["country"]), "事件": f"{國別.get(r['country'], '')} {名}".strip(),
                       "重要性": "高" if r["impact"] == "High" else "中", "說明": 說})
    f = 資料夾 / "us_earnings.csv"
    if f.exists():
        t = pd.read_csv(f, dtype=str).fillna("")
        t["date"] = pd.to_datetime(t["date"])
        for _, r in t[(t["date"] >= 起) & (t["date"] <= 迄)].iterrows():
            列們.append({"日期": r["date"], "時間": r["time"], "類別": "美股財報", "市場": "美國",
                       "事件": f"{r['name']}（{r['symbol']}）財報", "重要性": "高" if r["symbol"] in ("NVDA", "TSM", "AAPL", "AVGO", "MU", "AMD") else "中",
                       "說明": "美股時間，台灣隔天早上看結果" if r["time"] == "盤後" else ""})
    for 月 in pd.period_range(起, 迄, freq="M"):
        d = 結算日(月.year, 月.month)
        if 起 <= d <= 迄:
            列們.append({"日期": d, "時間": "13:30", "類別": "期貨結算", "市場": "台灣", "事件": "台指期月結算",
                       "重要性": "高", "說明": "結算日前後大盤波動常較大"})
    for _, r in 重要日程(大型股, 天數 + 往前, 起).iterrows():
        if r["類型"] == "法說會" and 大型股 is None:
            continue
        說 = html.unescape(str(r["說明"])).replace("\u200e", "").replace("\u200f", "")
        列們.append({"日期": r["日期"], "時間": "", "類別": r["類型"], "市場": "台灣",
                   "事件": r["股票"] if r["代號"] else 說, "重要性": "中", "說明": 說 if r["代號"] else ""})
    if 大型股 is not None:
        f = 資料夾 / "fundamental" / "dividend_upcoming.csv"
        if f.exists():
            t = pd.read_csv(f, dtype={"code": str})
            日欄 = next((c for c in ("date", "ex_date") if c in t.columns), None)
            if 日欄:
                t[日欄] = pd.to_datetime(t[日欄], errors="coerce")
                t = t[(t[日欄] >= 起) & (t[日欄] <= 迄) & t["code"].isin(list(大型股))]
                for _, r in t.iterrows():
                    列們.append({"日期": r[日欄], "時間": "", "類別": "除權息", "市場": "台灣",
                               "事件": f"{r['code']} {r.get('name', '')} 除權息".replace("  ", " "), "重要性": "中", "說明": ""})
    表 = pd.DataFrame(列們, columns=["日期", "時間", "類別", "市場", "事件", "重要性", "說明"])
    return 表.sort_values(["日期", "時間"], ignore_index=True)


def _百分位(s, 窗=250, 最少=40):
    """每天的值在過去 窗 天裡排第幾（0～100），缺值保持空白、不補 0。"""
    s = s.astype(float)
    return s.rolling(窗, min_periods=最少).apply(lambda x: (x[~np.isnan(x)] <= x[-1]).mean() * 100 if not np.isnan(x[-1]) else np.nan,
                                              raw=True)


def 情緒指數(指標, 加權=None):
    """四個 0～100 的情緒分數（越高越樂觀／越熱）：
    散戶＝融資 20 日增減與融資維持率；法人＝三大法人 5 日買賣超金額與外資台指期淨部位；
    資金溫度＝成交金額相對 60 日均量與上漲家數比例；全球＝VIX（反向）與費城半導體 20 日漲跌。
    每項先換成「在過去一年排第幾」，資料不夠的項目不算，不補 0。回傳 DataFrame（index＝日期）。"""
    群 = 指標.groupby("date")
    日 = pd.DataFrame({"成交值": 群["成交值億"].sum(), "上漲": 群["漲跌"].apply(lambda s: (s > 0).sum()),
                       "下跌": 群["漲跌"].apply(lambda s: (s < 0).sum())}).astype(float)
    項 = {}
    if "融資餘額" in 指標.columns:
        融 = 群["融資餘額"].sum().astype(float)
        融 = 融.where(融 > 0)
        項["融資增減"] = _百分位(融.pct_change(20))
        維 = 融資維持率(指標)
        if 維 is not None and len(維):
            項["維持率"] = _百分位(維.reindex(日.index))
    if "法人買超" in 指標.columns:
        金 = (指標["法人買超"].astype(float) * 1000 * 指標["收盤"].astype(float)).groupby(指標["date"]).sum() / 1e8
        項["法人5日"] = _百分位(金.rolling(5).sum())
    期 = 讀取期貨未平倉()
    if 期 is not None and "foreign_oi" in 期:
        項["外資期貨"] = _百分位(期["foreign_oi"].reindex(日.index))
    項["量能"] = _百分位(日["成交值"] / 日["成交值"].rolling(60, min_periods=20).mean())
    項["廣度"] = _百分位((日["上漲"] / (日["上漲"] + 日["下跌"]).replace(0, np.nan)).rolling(5).mean())
    美 = 讀取美股()
    if 美 is not None:
        前一美股日 = lambda s: s.reindex(s.index.union(日.index)).ffill().shift(1).reindex(日.index)  # 台股當天看前一晚美股
        if "VIX" in 美:
            項["VIX"] = 100 - _百分位(前一美股日(美["VIX"].dropna()))
        if "費城半導體" in 美:
            項["費半"] = _百分位(前一美股日(美["費城半導體"].dropna().pct_change(20)))
    結果 = pd.DataFrame(index=日.index)
    for 名, 欄們 in (("散戶", ["融資增減", "維持率"]), ("法人", ["法人5日", "外資期貨"]),
                    ("資金溫度", ["量能", "廣度"]), ("全球", ["VIX", "費半"])):
        有 = [項[c] for c in 欄們 if c in 項]
        結果[名] = pd.concat(有, axis=1).mean(axis=1, skipna=True).rolling(3, min_periods=1).mean().round(0) if 有 else np.nan  # 3 日平滑
    if 加權 is not None and len(加權):
        結果["加權"] = 加權.set_index("date")["close"].reindex(結果.index)
    return 結果


def 情緒說明(分):
    if pd.isna(分):
        return "資料不足"
    return "極度樂觀" if 分 >= 80 else "樂觀" if 分 >= 60 else "中性" if 分 > 40 else "悲觀" if 分 > 20 else "極度悲觀"


def 情緒象限(散戶, 法人):
    if pd.isna(散戶) or pd.isna(法人):
        return "資料不足"
    if 法人 >= 50:
        return "全市場過熱" if 散戶 >= 50 else "法人吸籌"
    return "法人出貨" if 散戶 >= 50 else "系統恐慌"


def 市場狀態(加權, 今日, 每日, 情緒=None, 日程=None):
    """市場狀態判讀卡（規則，不用 AI）：回傳 dict(狀態, 分數, 支持, 反向, 待觀察, 下一步)。
    每日＝每天的大盤數字（外資、融資、外資期貨、維持率…），情緒＝情緒指數()，日程＝經濟日程()。"""
    大 = 大盤評分(加權, 今日)
    支持, 反向, 待觀察 = list(大["利多"]), list(大["利空"]), []
    def 近(欄, n):
        s = 每日[欄].dropna() if 欄 in 每日 else pd.Series(dtype=float)
        return (s.iloc[-1], s.iloc[-1 - n]) if len(s) > n else (None, None)
    if "外資" in 每日:
        五 = 每日["外資"].tail(5).sum()
        (支持 if 五 > 0 else 反向).append(f"外資近 5 日{'買' if 五 > 0 else '賣'}超約 {abs(五):,.0f} 億")
    現, 前 = 近("外資期貨", 5)
    if 現 is not None:
        差 = 現 - 前
        if abs(差) >= 3000:
            (支持 if 差 > 0 else 反向).append(f"外資台指期淨部位 5 日{'增加' if 差 > 0 else '減少'} {abs(差):,.0f} 口（{'回補空單' if 差 > 0 else '加碼空單'}）")
    現, 前 = 近("融資", 5)
    if 現 is not None and 前:
        變 = (現 / 前 - 1) * 100
        if 變 >= 2:
            反向.append(f"融資 5 日增加 {變:.1f}%，散戶追價、籌碼變亂")
        elif 變 <= -2:
            支持.append(f"融資 5 日減少 {abs(變):.1f}%，籌碼沉澱")
    現, _ = 近("維持率", 1)
    if 現 is not None:
        if 現 < 150:
            反向.append(f"融資維持率 {現:.0f}% 偏低，留意追繳賣壓")
        elif 現 >= 175:
            待觀察.append(f"融資維持率 {現:.0f}% 偏高，市場偏熱")
    if 情緒 is not None and len(情緒):
        r = 情緒.iloc[-1]
        if pd.notna(r.get("散戶")) and r["散戶"] >= 80:
            反向.append(f"散戶情緒 {r['散戶']:.0f} 分過熱（反向指標）")
        elif pd.notna(r.get("散戶")) and r["散戶"] <= 20:
            支持.append(f"散戶情緒 {r['散戶']:.0f} 分極度悲觀（反向指標，常接近低點）")
        if pd.notna(r.get("全球")):
            if r["全球"] >= 65:
                支持.append(f"國際風險情緒 {r['全球']:.0f} 分偏樂觀（VIX 低、費半強）")
            elif r["全球"] <= 35:
                反向.append(f"國際風險情緒 {r['全球']:.0f} 分偏悲觀（VIX 高或費半弱）")
    if 日程 is not None and len(日程):
        近期 = 日程[(日程["重要性"] == "高")].head(6)
        for _, r in 近期.iterrows():
            待觀察.append(f"{r['日期']:%m/%d}（{'一二三四五六日'[r['日期'].weekday()]}）{r['事件']}")
    分數 = len(支持) - len(反向)
    狀態 = "偏多" if 分數 >= 3 else ("偏空" if 分數 <= -3 else ("中性偏多" if 分數 > 0 else ("中性偏空" if 分數 < 0 else "中性盤整")))
    數 = 大["數字"]
    下一步 = []
    if "MA20" in 數:
        下一步.append(f"加權能否守住月線 {數['MA20']:,.0f}" if 數["加權"] >= 數["MA20"] else f"加權能否站回月線 {數['MA20']:,.0f}")
    if "MA60" in 數:
        下一步.append(f"季線 {數['MA60']:,.0f} 是中期多空分界")
    下一步.append("外資現貨與期貨方向是否一致（同買＝偏多確認、同賣＝偏空確認）")
    return {"狀態": 狀態, "分數": 分數, "支持": 支持, "反向": 反向, "待觀察": 待觀察, "下一步": 下一步, "大盤": 大}


# ========== 21. 美股 → 台股族群連動、AI 大盤解讀 ==========
連動美股 = ["費城半導體", "那斯達克", "輝達", "蘋果", "台積電 ADR"]


def 族群日報酬(指標, 分類="產業"):
    """每個族群每天的市值加權報酬（%）。分類＝產業 或 概念股。回傳 DataFrame（日期 × 族群）。"""
    t = 指標[["date", "代號", "收盤", "日報酬"]].copy()
    股 = _股本表()
    t["權重"] = t["收盤"].astype(float) * t["代號"].map(股["發行股數"]).astype(float)
    if 分類 == "概念股":
        t = t.merge(讀取概念().rename(columns={"code": "代號", "concept": "族群"}), on="代號")
    else:
        t["族群"] = t["代號"].map(股["產業"])
        t = t[~t["代號"].str.startswith("0") & (t["族群"].fillna("") != "")]
    t = t[t["權重"] > 0]
    t["加權"] = t["日報酬"].astype(float) * t["權重"]
    群 = t.groupby(["date", "族群"])
    return (群["加權"].sum() / 群["權重"].sum() * 100).unstack()


def 美股連動(指標, 分類="產業", 天數=120, 最少檔數=5):
    """台股各族群跟「前一晚美股」的連動程度。
    回傳 (表, 美股最新)：表的 index＝族群，欄位有 各美股的相關係數、對費半的敏感度（費半漲 1% 族群平均漲幾 %）、
    今天實際漲跌、依昨晚費半推估的漲跌、落差（實際 − 推估）、明天推估（用最新一晚的費半，若美股比台股新）。"""
    美 = 讀取美股()
    if 美 is None:
        return pd.DataFrame(), {}
    族 = 族群日報酬(指標, 分類)
    if 分類 == "產業":
        家數 = 指標[指標["date"] == 指標["date"].max()]["代號"].map(_股本表()["產業"]).value_counts()
        族 = 族[[c for c in 族.columns if 家數.get(c, 0) >= 最少檔數]]
    美報酬 = 美[[c for c in 連動美股 if c in 美]].pct_change(fill_method=None) * 100
    # 台股 t 日對應「t 日之前最後一個美股交易日」（台股收盤時美股還沒開，所以用前一晚）
    美報酬 = 美報酬.dropna(how="all")
    前晚 = pd.merge_asof(pd.DataFrame({"date": 族.index}), 美報酬.rename_axis("date").reset_index(), on="date",
                         direction="backward", allow_exact_matches=False).set_index("date")
    近 = 族.tail(天數)
    前 = 前晚.reindex(近.index)
    表 = pd.DataFrame(index=近.columns)
    for c in 前.columns:
        表[c] = 近.corrwith(前[c]).round(2)
    if "費城半導體" in 前:
        x = 前["費城半導體"]
        表["費半敏感度"] = (近.apply(lambda y: y.cov(x)) / x.var()).round(2)
        今 = 族.index[-1]
        表["今天實際%"] = 族.loc[今].round(2)
        表["依昨晚費半推估%"] = (表["費半敏感度"] * 前晚.loc[今, "費城半導體"]).round(2)
        表["落差%"] = (表["今天實際%"] - 表["依昨晚費半推估%"]).round(2)
        最新美 = 美報酬["費城半導體"].dropna()
        if len(最新美) and 最新美.index[-1] >= 今:
            表["明天推估%"] = (表["費半敏感度"] * 最新美.iloc[-1]).round(2)
    最新 = {c: (美報酬[c].dropna().index[-1], 美報酬[c].dropna().iloc[-1]) for c in 美報酬.columns if 美報酬[c].notna().any()}
    return 表.sort_values(表.columns[0], ascending=False), 最新


解讀模式 = {
    "盤前": "台股開盤前（08:30）的盤前解讀：昨晚美股與台指期夜盤怎麼走、今天可能受影響的族群、今天要注意的事件與風險、開盤觀察重點。",
    "收盤": "台股收盤後的收盤分析：今天盤勢結構（指數、權值股撐盤或拖盤、漲跌家數）、強勢與弱勢族群、資金流向（外資、投信、融資、期貨）、領頭羊、明天觀察重點。",
    "夜盤": "晚上 22:00 的夜盤與美股解讀：美股開盤表現、台指期夜盤、國際事件，提出隔天的族群觀察、偏多或偏空的條件與風險控管。",
}
大盤解讀提示 = """你是台灣股市的研究助理，替一位剛開始學投資、可能用手機看的個人投資者寫大盤解讀。
規則：
- 全部用繁體中文、白話，專有名詞第一次出現要用一句話解釋。
- 只根據提供的數據寫，不要編造沒有給的數字；資料缺的就說「資料不足」。關聯不要寫成因果。
- 用 Markdown，600 字以內，分成：## 一句話結論、## 盤勢重點（3～5 點）、## 族群與資金、## 接下來觀察（含偏多與偏空的條件）、## 風險提醒。
- 最後一行固定寫「（AI 依規則數據整理，僅供研究參考，不是買賣建議）」。"""


def 大盤摘要(指標, 加權, 國際=None, 期貨=None):
    """把網站上的大盤數據整理成一段文字，給 AI 寫大盤解讀用。"""
    最新 = 指標["date"].max()
    今日 = 加基本面(指標[指標["date"] == 最新], 讀取基本面())
    行 = [f"資料日期：{最新:%Y-%m-%d}（台股最新收盤）"]
    if 加權 is not None and len(加權):
        r = 加權.iloc[-1]
        行.append(f"加權指數 {r['close']:,.0f}，漲跌 {r['change']:+,.0f} 點（{r['change'] / (r['close'] - r['change']) * 100:+.2f}%）")
    股 = 今日[今日["代號"].str.fullmatch(r"\d{4}")]
    行.append(f"上漲 {(股['漲跌'] > 0).sum()} 家、下跌 {(股['漲跌'] < 0).sum()} 家，成交 {今日['成交值億'].sum():,.0f} 億")
    try:
        權, 摘 = 權值貢獻(今日, 加權)
        行.append("撐盤：" + "、".join(f"{r['名稱']} {r['貢獻點數']:+.0f} 點" for _, r in 權.head(5).iterrows()))
        行.append("拖盤：" + "、".join(f"{r['名稱']} {r['貢獻點數']:+.0f} 點" for _, r in 權.tail(5).iloc[::-1].iterrows()))
    except Exception:
        pass
    for 名, 來源 in (("產業", 今日), ("概念股", 概念展開(今日))):
        try:
            族, _ = 族群資料(來源)
            行.append(f"強勢{名}：" + "、".join(f"{k} {v:+.1f}%（{r['上漲']}/{r['家數']} 檔漲）" for k, r in 族.head(4).iterrows() for v in [r["漲跌幅"]]))
            行.append(f"弱勢{名}：" + "、".join(f"{k} {v:+.1f}%" for k, r in 族.tail(4).iloc[::-1].iterrows() for v in [r["漲跌幅"]]))
        except Exception:
            pass
    if "外資買超" in 今日:
        金 = lambda 欄: (今日[欄] * 1000 * 今日["收盤"]).sum() / 1e8
        行.append(f"法人買賣超：外資 {金('外資買超'):+,.0f} 億、投信 {金('投信買超'):+,.0f} 億、自營商 {金('自營買超'):+,.0f} 億")
        融 = 指標.groupby("date")["融資餘額"].sum()
        if len(融) > 5:
            行.append(f"融資餘額 {融.iloc[-1]:,.0f} 張，5 日 {(融.iloc[-1] / 融.iloc[-6] - 1) * 100:+.1f}%")
    維 = 融資維持率(指標[指標["date"] >= 最新 - pd.Timedelta(days=10)])
    if 維 is not None and len(維):
        行.append(f"上市融資維持率約 {維.iloc[-1]:.0f}%")
    期 = 讀取期貨未平倉()
    if 期 is not None and len(期) > 5:
        行.append(f"外資台指期淨部位 {期['foreign_oi'].iloc[-1]:+,.0f} 口（5 日變化 {期['foreign_oi'].iloc[-1] - 期['foreign_oi'].iloc[-6]:+,.0f}）")
    try:
        情 = 情緒指數(指標, 加權).dropna(how="all", subset=["散戶", "法人"]).iloc[-1]
        行.append("情緒分數（0～100）：" + "、".join(f"{k} {情[k]:.0f}" for k in ("法人", "散戶", "資金溫度", "全球") if pd.notna(情[k]))
                 + f"；法人×散戶象限：{情緒象限(情['散戶'], 情['法人'])}")
    except Exception:
        pass
    if 國際:
        行.append("國際行情（最新）：" + "、".join(f"{k} {v['價']:,.2f}（{v['幅度']:+.2f}%，{v['時間']:%m/%d %H:%M}）" for k, v in 國際.items()))
    if 期貨:
        行.append("台指期：" + "、".join(f"{k} {v['價']:,.0f}（{v['漲跌']:+,.0f}，{v['時間']}）" for k, v in 期貨.items()))
    try:
        日程 = 經濟日程(天數=5)
        日程 = 日程[日程["重要性"] == "高"].head(8)
        if len(日程):
            行.append("未來 5 天重要事件：" + "；".join(f"{r['日期']:%m/%d} {r['時間']} {r['事件']}" for _, r in 日程.iterrows()))
    except Exception:
        pass
    return "\n".join(行)


def AI大盤解讀(摘要, 模式, 設定):
    """用 Gemini（有 GEMINI_API_KEY）或 Claude 寫大盤解讀。回傳 (Markdown, 模型名稱)。"""
    import datetime as dt
    現在 = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    問題 = f"現在是台灣時間 {現在}。請寫「{模式}」解讀：{解讀模式[模式]}\n\n以下是最新數據：\n{摘要}"
    if str(設定.get("GEMINI_API_KEY", "")).strip():
        內容 = {"systemInstruction": {"parts": [{"text": 大盤解讀提示}]},
                "contents": [{"role": "user", "parts": [{"text": 問題}]}]}
        回應, 模型 = Gemini呼叫(內容, 清理金鑰(設定["GEMINI_API_KEY"]), str(設定.get("GEMINI_MODEL", "gemini-flash-latest")))
        候選 = (回應.json().get("candidates") or [{}])[0]
        文字 = "".join(p.get("text", "") for p in (候選.get("content") or {}).get("parts", [])).strip()
    elif str(設定.get("ANTHROPIC_API_KEY", "")).strip():
        import anthropic
        模型 = str(設定.get("AI_MODEL", "claude-opus-5-5"))
        回應 = anthropic.Anthropic(api_key=清理金鑰(設定["ANTHROPIC_API_KEY"])).messages.create(
            model=模型, max_tokens=4000, system=大盤解讀提示, messages=[{"role": "user", "content": 問題}])
        文字 = "".join(b.text for b in 回應.content if b.type == "text").strip()
    else:
        raise RuntimeError("沒有設定 GEMINI_API_KEY 或 ANTHROPIC_API_KEY。")
    if not 文字:
        raise RuntimeError("AI 沒有產生內容，請稍後再試。")
    return 文字, 模型


def 讀取大盤解讀(設定):
    """ai-reports 分支的 briefs.json：{"YYYY-MM-DD_模式": {時間, 模式, 內容, 模型}}。"""
    try:
        return 讀取設定檔(設定, "briefs.json") or {}
    except Exception:
        return {}


def 儲存大盤解讀(設定, 模式, 內容, 模型, 保留=60):
    import datetime as dt
    現在 = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    全部 = 讀取大盤解讀(設定)
    全部[f"{現在:%Y-%m-%d}_{模式}"] = {"時間": f"{現在:%Y-%m-%d %H:%M}", "模式": 模式, "內容": 內容, "模型": 模型}
    全部 = dict(sorted(全部.items())[-保留:])
    return 儲存設定檔(設定, "briefs.json", 全部, f"{模式}大盤解讀 {現在:%m/%d}")


# ========== 22. 支撐壓力、共振區、三條件燈號、黑 K 一半 ==========
指數名稱 = {"TAIEX": "加權指數", "TPEX": "櫃買指數"}
回檔比例 = (0.236, 0.382, 0.5, 0.618, 0.786)
均線名稱 = {20: "月線", 60: "季線", 120: "半年線", 240: "年線"}


def 讀取指數K線(代號="TAIEX"):
    """data/index_ohlc.csv 的加權（TAIEX）或櫃買（TPEX）日 K（date, open, high, low, close）。
    加權還沒有開高低資料時，退回只有收盤的 data/index（開高低都用收盤代替）。"""
    f = 資料夾 / "index_ohlc.csv"
    if f.exists():
        t = pd.read_csv(f, parse_dates=["date"])
        t = t[t["symbol"] == 代號].drop(columns="symbol").sort_values("date").reset_index(drop=True)
        if len(t) >= 60:
            return t
    if 代號 == "TAIEX":
        t = 讀取加權指數()
        if t is not None and len(t):
            t = t[["date", "close"]].reset_index(drop=True)
            return t.assign(open=t["close"], high=t["close"], low=t["close"])
    return None


def 有開高低(K):
    return K is not None and len(K) and not (K["high"] == K["low"]).all()


def 整數級距(價):
    """整數關卡的間隔：4 萬多點→1000、2 千多元→100、300 多元→10、20 多元→1。"""
    return 10 ** max(int(np.floor(np.log10(max(價, 1)))) - 1, 0)


def 找缺口(K, 天數=250, 最小=0.001):
    """還沒回補的跳空缺口：向上缺口（今天最低 > 昨天最高）是支撐，向下缺口是壓力。
    後來的 K 線碰到一部分就把缺口縮小，整個碰到就算回補。回傳 [(下緣, 上緣, 日期, "向上"/"向下")]。"""
    if not 有開高低(K):
        return []
    k = K.tail(天數).reset_index(drop=True)
    高, 低, 日 = k["high"].values, k["low"].values, k["date"].values
    結果 = []
    for i in range(1, len(k)):
        if 低[i] > 高[i - 1] * (1 + 最小):
            下, 上 = 高[i - 1], 低[i]
            後低 = 低[i + 1:].min() if i + 1 < len(k) else np.inf
            上 = min(上, 後低)
            if 上 > 下 * (1 + 最小):
                結果.append((float(下), float(上), pd.Timestamp(日[i]), "向上"))
        elif 高[i] < 低[i - 1] * (1 - 最小):
            下, 上 = 高[i], 低[i - 1]
            後高 = 高[i + 1:].max() if i + 1 < len(k) else -np.inf
            下 = max(下, 後高)
            if 上 > 下 * (1 + 最小):
                結果.append((float(下), float(上), pd.Timestamp(日[i]), "向上" if False else "向下"))
    return 結果


def 最近波段(K, 門檻=None):
    """用「轉折幅度超過門檻才算一個波段」的方法（ZigZag）找最近一段完整的漲勢或跌勢，算費波那契回檔用。
    門檻依波動度自動調整（指數約 8～10%、個股較大）。回傳 dict(高, 高日, 低, 低日, 方向)。"""
    k = K.reset_index(drop=True)
    if 門檻 is None:
        波動 = k["close"].pct_change().tail(120).std()
        門檻 = float(np.clip(2.0 * 波動 * np.sqrt(10), 0.05, 0.2)) if pd.notna(波動) else 0.1
    高, 低 = k["high"].values, k["low"].values
    轉折 = []                       # [(位置, 種類)]，種類 "高"／"低"
    方向, 極 = 0, 0                 # 方向 1＝往上找高點、-1＝往下找低點
    for i in range(1, len(k)):
        if 方向 == 0:
            if 高[i] >= 低[:i + 1].min() * (1 + 門檻):
                轉折.append((int(np.argmin(低[:i + 1])), "低"))
                方向, 極 = 1, i
            elif 低[i] <= 高[:i + 1].max() * (1 - 門檻):
                轉折.append((int(np.argmax(高[:i + 1])), "高"))
                方向, 極 = -1, i
        elif 方向 == 1:
            if 高[i] >= 高[極]:
                極 = i
            elif 低[i] <= 高[極] * (1 - 門檻):
                轉折.append((極, "高"))
                方向, 極 = -1, i
        else:
            if 低[i] <= 低[極]:
                極 = i
            elif 高[i] >= 低[極] * (1 + 門檻):
                轉折.append((極, "低"))
                方向, 極 = 1, i
    if 方向 == 0:               # 整段都沒有大波動：用區間高低
        i高, i低 = int(np.argmax(高)), int(np.argmin(低))
    elif 方向 == 1:             # 目前在上漲段（高點還沒確認）：上一個確認的低點 → 目前最高
        i低, i高 = 轉折[-1][0], 極
    else:                       # 目前在下跌段：上一個確認的高點 → 目前最低
        i高, i低 = 轉折[-1][0], 極
    return {"高": float(高[i高]), "高日": k["date"].iat[i高], "低": float(低[i低]), "低日": k["date"].iat[i低],
            "方向": "上漲" if i低 < i高 else "下跌", "門檻": 門檻}


def 支撐壓力(K, 波段天數=120, 量=None):
    """把均線、波段費波那契回檔、未回補缺口、前高前低、整數關卡（有成交量時再加分價量密集區）整理成一張價位表。
    K＝date, open, high, low, close（由舊到新）；量＝以日期為 index 的成交金額。
    回傳 dict(收盤, 日期, 均線, 波段, 缺口, 分價量, 價位 DataFrame)。"""
    K = K.dropna(subset=["close"]).reset_index(drop=True)
    收 = float(K["close"].iloc[-1])
    列們 = []
    均線 = {}
    for n, 名 in 均線名稱.items():
        if len(K) >= n:
            均線[名] = float(K["close"].tail(n).mean())
            列們.append((名, 均線[名], "均線", f"{n} 日均線"))
    波段 = 最近波段(K.tail(波段天數 * 2))
    高, 低 = 波段["高"], 波段["低"]
    if 高 > 低:
        段 = f"{波段['低日']:%m/%d} 低點 → {波段['高日']:%m/%d} 高點" if 波段["方向"] == "上漲" else \
            f"{波段['高日']:%m/%d} 高點 → {波段['低日']:%m/%d} 低點"
        for r in 回檔比例:
            if 波段["方向"] == "上漲":   # 漲一段後回檔：從高點往下算
                列們.append((f"回檔 {r:g}", 高 - r * (高 - 低), "回檔", f"費波那契，{段}"))
            else:                          # 跌一段後反彈：從低點往上算
                列們.append((f"反彈 {r:g}", 低 + r * (高 - 低), "回檔", f"費波那契，{段}"))
        列們.append(("波段高點", 高, "前高低", f"{波段['高日']:%Y/%m/%d}"))
        列們.append(("波段低點", 低, "前高低", f"{波段['低日']:%Y/%m/%d}"))
    缺口 = 找缺口(K)
    小數 = 0 if 收 > 1000 else 2
    下方缺口 = sorted([g for g in 缺口 if g[1] < 收], key=lambda g: -g[1])[:2]   # 只列最近的兩個
    上方缺口 = sorted([g for g in 缺口 if g[0] > 收], key=lambda g: g[0])[:2]
    for 下, 上, 日, 向 in 下方缺口 + 上方缺口:
        列們.append((f"{日:%m/%d} 缺口", 上 if 上 < 收 else 下, "缺口", f"{下:,.{小數}f}～{上:,.{小數}f} 還沒回補"))  # 先碰到的那一邊
    近 = K.iloc[-61:-1]
    if len(近):
        for 名, v in (("近 60 日高點", float(近["high"].max())), ("近 60 日低點", float(近["low"].min()))):
            if min(abs(v / 高 - 1), abs(v / 低 - 1)) > 0.002:  # 跟波段高低點一樣就不重複列
                列們.append((名, v, "前高低", ""))
    步 = 整數級距(收)
    下關, 上關 = np.floor(收 / 步) * 步, np.ceil(收 / 步) * 步
    if 收 - 下關 < 收 * 0.003:   # 收盤剛好在關卡上，往外再找一格
        下關 -= 步
    if 上關 - 收 < 收 * 0.003:
        上關 += 步
    列們 += [("整數關卡", float(下關), "整數", "心理關卡"), ("整數關卡", float(上關), "整數", "心理關卡")]
    分量 = 分價量(K, 量) if 量 is not None else None
    if 分量:
        n = 分量["天數"]
        列們 += [("成交最密集", 分量["POC"], "分價量", f"近 {n} 日成交金額最多的價位"),
                ("密集區上緣", 分量["VAH"], "分價量", f"近 {n} 日 7 成成交金額落在上下緣之間"),
                ("密集區下緣", 分量["VAL"], "分價量", f"近 {n} 日 7 成成交金額落在上下緣之間")]
    價位 = pd.DataFrame(列們, columns=["名稱", "價位", "類別", "說明"])
    價位 = 價位[(價位["價位"] > 收 * 0.75) & (價位["價位"] < 收 * 1.25)]  # 太遠的價位短期用不到
    價位["距離%"] = (價位["價位"] / 收 - 1) * 100
    價位["角色"] = np.where(價位["價位"] < 收, "支撐", "壓力")
    價位 = 價位.drop_duplicates(["名稱", "價位"]).sort_values("價位", ascending=False).reset_index(drop=True)
    return {"收盤": 收, "日期": K["date"].iloc[-1], "均線": 均線, "波段": 波段, "缺口": 缺口, "分價量": 分量, "價位": 價位}


def 共振區(價位, 容忍=0.012):
    """價位彼此在 ±容忍 以內、而且來自 2 種以上方法（或 3 個以上價位）就算共振區：多種方法都指向這裡，比較有參考價值。"""
    t = 價位.sort_values("價位").reset_index(drop=True)
    區們, 目前 = [], []
    for _, r in t.iterrows():
        if 目前 and r["價位"] > 目前[0]["價位"] * (1 + 容忍):
            區們.append(目前)
            目前 = []
        目前.append(r)
    if 目前:
        區們.append(目前)
    結果 = []
    for 區 in 區們:
        類 = {r["類別"] for r in 區}
        if len(類) >= 2 or len(區) >= 3:
            價 = [r["價位"] for r in 區]
            結果.append({"下": min(價), "上": max(價), "中": float(np.mean(價)), "成員": [r["名稱"] for r in 區],
                       "強度": len(區), "角色": 區[0]["角色"] if len({r["角色"] for r in 區}) == 1 else "目前位置"})
    return 結果


def 位置解讀(sr, 區們=None):
    """一段白話：目前站上／跌破哪些均線，下方最近的支撐、上方最近的壓力，以及最重要的共振區。"""
    收, 均線, 價位 = sr["收盤"], sr["均線"], sr["價位"]
    區們 = 共振區(價位) if 區們 is None else 區們
    小數 = 0 if 收 > 1000 else 2
    f = lambda v: f"{v:,.{小數}f}"
    距 = lambda v: "就在目前價位" if abs(v) < 0.15 else f"{v:+.1f}%"
    區間 = lambda z: f(z["下"]) if z["上"] - z["下"] < 收 * 0.001 else f"{f(z['下'])}～{f(z['上'])}"
    站上 = [k for k, v in 均線.items() if 收 >= v]
    跌破 = [k for k, v in 均線.items() if 收 < v]
    if 站上 and 跌破:
        均線句 = f"站在{'、'.join(站上)}之上、{'、'.join(跌破)}之下"
    elif 站上:
        均線句 = "站上所有主要均線（多頭排列中）" if len(站上) == len(均線) else f"站上{'、'.join(站上)}"
    else:
        均線句 = "跌破所有主要均線（偏弱）"
    支 = 價位[價位["角色"] == "支撐"].sort_values("價位", ascending=False)
    壓 = 價位[價位["角色"] == "壓力"].sort_values("價位")
    句們 = [f"收盤 {f(收)}，{均線句}。"]
    if len(支):
        a = 支.iloc[0]
        句 = f"下方最近支撐是{a['名稱']} {f(a['價位'])}（{距(a['距離%'])}）"
        if len(支) > 1:
            b = 支.iloc[1]
            句 += f"，再下來是{b['名稱']} {f(b['價位'])}（{距(b['距離%'])}）"
        句們.append(句 + "。")
    if len(壓):
        a = 壓.iloc[0]
        句們.append(f"上方最近壓力是{a['名稱']} {f(a['價位'])}（{距(a['距離%'])}）。")
    下區 = [z for z in 區們 if z["上"] < 收]
    上區 = [z for z in 區們 if z["下"] > 收]
    if 下區:
        z = max(下區, key=lambda z: z["中"])
        句們.append(f"{區間(z)} 有{'、'.join(z['成員'][:4])} 重疊，是比較重要的支撐區（{距((z['中'] / 收 - 1) * 100)}）。")
    if 上區:
        z = min(上區, key=lambda z: z["中"])
        句們.append(f"上方 {區間(z)} 有{'、'.join(z['成員'][:4])} 重疊，是比較重要的壓力區（{距((z['中'] / 收 - 1) * 100)}）。")
    最近支 = 支.iloc[0] if len(支) else None
    最近壓 = 壓.iloc[0] if len(壓) else None
    return {"文字": "".join(句們), "站上": 站上, "跌破": 跌破, "最近支撐": 最近支, "最近壓力": 最近壓}


def 黑K一半(K, 回看=10, 跌幅門檻=1.0):
    """找最近一根「大黑 K」（收比開低 1% 以上、實體比近 20 日一般 K 線大），看之後的反彈收盤有沒有站上黑 K 實體的一半。
    站上＝反彈有力；沒站上就要小心二次回落。資料沒有開高低時回傳 None。"""
    if not 有開高低(K) or len(K) < 25:
        return None
    k = K.reset_index(drop=True)
    實體 = (k["open"] - k["close"]).abs()
    一般 = 實體.rolling(20).median()
    for i in range(len(k) - 1, max(len(k) - 1 - 回看, 20), -1):
        開, 收 = k.at[i, "open"], k.at[i, "close"]
        if 收 < 開 and (開 - 收) / 開 * 100 >= 跌幅門檻 and (開 - 收) >= 1.2 * 一般.iat[i - 1]:
            中 = (開 + 收) / 2
            之後 = k.iloc[i + 1:]
            基本 = {"日期": k.at[i, "date"], "開": float(開), "收": float(收), "中點": float(中), "高": float(k.at[i, "high"])}
            if 之後.empty:
                return {**基本, "燈": "🟡", "狀態": f"剛出現大黑 K，接下來反彈收盤要站上一半 {中:,.2f} 才算有力"}
            最高收 = float(之後["close"].max())
            if 之後["close"].iloc[-1] > 基本["高"]:
                return {**基本, "燈": "🟢", "狀態": f"已收復整根黑 K（高點 {基本['高']:,.2f}），賣壓消化"}
            if 最高收 > 中:
                現在 = "目前仍在一半之上" if 之後["close"].iloc[-1] > 中 else "但目前又跌回一半之下，要小心"
                return {**基本, "燈": "🟢" if 之後["close"].iloc[-1] > 中 else "🟡",
                        "狀態": f"反彈收盤曾站上黑 K 一半 {中:,.2f}，{現在}"}
            return {**基本, "燈": "🔴", "狀態": f"反彈收盤還沒站上黑 K 一半 {中:,.2f}（最高只到 {最高收:,.2f}），小心二次回落"}
    return None


def 三條件燈號(加權K, 櫃買K=None, 美股=None):
    """參考週報分析者的三個觀察條件：費半守住前低與年線、加權守住半年線並收復季線、櫃買低點不再下移。
    回傳 [(名稱, 燈, 說明)] 與一句總結。🟢＝改善、🟡＝觀察中、🔴＝轉弱。"""
    結果 = []
    if 美股 is not None and "費城半導體" in 美股:
        s = 美股["費城半導體"].dropna()
        if len(s) >= 60:
            收 = float(s.iloc[-1])
            前低 = float(s.iloc[-120:-10].min())
            年線 = float(s.tail(240).mean()) if len(s) >= 240 else None
            守低, 守年 = 收 > 前低, (年線 is None or 收 > 年線)
            燈 = "🟢" if 守低 and 守年 and 收 > 前低 * 1.03 else ("🔴" if not 守低 or not 守年 else "🟡")
            說 = f"費半 {收:,.0f}，前波低點 {前低:,.0f}（{(收 / 前低 - 1) * 100:+.1f}%）" + (
                f"、年線 {年線:,.0f}（{(收 / 年線 - 1) * 100:+.1f}%）" if 年線 else "")
            結果.append(("費半守住前低與年線", 燈, 說))
    if 加權K is not None and len(加權K) >= 120:
        c = 加權K["close"]
        收, 季, 半年 = float(c.iloc[-1]), float(c.tail(60).mean()), float(c.tail(120).mean())
        燈 = "🟢" if 收 >= 季 else ("🟡" if 收 >= 半年 else "🔴")
        說 = f"加權 {收:,.0f}，季線 {季:,.0f}（{(收 / 季 - 1) * 100:+.1f}%）、半年線 {半年:,.0f}（{(收 / 半年 - 1) * 100:+.1f}%）"
        結果.append(("加權守半年線、收復季線", 燈, 說))
    if 櫃買K is not None and len(櫃買K) >= 30:
        低 = 櫃買K["low"] if 有開高低(櫃買K) else 櫃買K["close"]
        近, 前 = float(低.tail(5).min()), float(低.iloc[-10:-5].min())
        收, 月 = float(櫃買K["close"].iloc[-1]), float(櫃買K["close"].tail(20).mean())
        燈 = "🟢" if 近 > 前 and 收 >= 月 else ("🔴" if 近 < 前 else "🟡")
        說 = f"櫃買 {收:,.2f}，近 5 日低點 {近:,.2f} {'高於' if 近 > 前 else ('低於' if 近 < 前 else '等於')}前 5 日 {前:,.2f}，月線 {月:,.2f}"
        結果.append(("櫃買低點不再下移", 燈, 說))
    綠 = sum(1 for _, 燈, _ in 結果 if 燈 == "🟢")
    紅 = sum(1 for _, 燈, _ in 結果 if 燈 == "🔴")
    if not 結果:
        總結 = "資料不足"
    elif 綠 == len(結果):
        總結 = "條件都改善，反彈比較有品質"
    elif 紅 >= 2:
        總結 = "多數條件仍轉弱，反彈先當作短線，提防上方賣壓"
    else:
        總結 = "條件好壞參半，等更多條件轉綠再加碼"
    return 結果, 總結


# ========== 23. 分價量、量價標籤、櫃買／加權強弱、誰在撐盤、避風港與提款機、恐慌溫度計 ==========
def 分價量(K, 量, 天數=120, 格數=40):
    """近 N 日每個價格區間累積了多少成交金額（每天的成交金額平均分到當天最高～最低之間）。
    成交最多的價位（POC）和 7 成成交集中的區間（上下緣）常是套牢或防守的位置。量＝以日期為 index 的成交金額。"""
    k = K.tail(天數).merge(量.rename("量"), left_on="date", right_index=True, how="inner")
    k = k[k["量"] > 0]
    if len(k) < 20:
        return None
    邊 = np.linspace(float(k["low"].min()), float(k["high"].max()), 格數 + 1)
    量格 = np.zeros(格數)
    for 低, 高, v in zip(k["low"].values, k["high"].values, k["量"].values):
        if 高 <= 低:
            量格[min(max(np.searchsorted(邊, 低, side="right") - 1, 0), 格數 - 1)] += v
            continue
        量格 += v * np.clip(np.minimum(邊[1:], 高) - np.maximum(邊[:-1], 低), 0, None) / (高 - 低)
    i = int(np.argmax(量格))
    下i = 上i = i
    累計, 全部 = 量格[i], 量格.sum()
    while 累計 < 全部 * 0.7 and (下i > 0 or 上i < 格數 - 1):   # 從最多的那格往兩邊擴，直到包住 7 成
        往下 = 量格[下i - 1] if 下i > 0 else -1
        往上 = 量格[上i + 1] if 上i < 格數 - 1 else -1
        if 往上 >= 往下:
            上i += 1
            累計 += 量格[上i]
        else:
            下i -= 1
            累計 += 量格[下i]
    表 = pd.DataFrame({"下": 邊[:-1], "上": 邊[1:], "量": 量格})
    表["中"] = (表["下"] + 表["上"]) / 2
    return {"表": 表, "POC": float(表["中"].iat[i]), "VAH": float(邊[上i + 1]), "VAL": float(邊[下i]), "天數": len(k)}


量價說明 = {
    "價漲量增": "買盤積極，上漲有量，比較健康", "價漲量平": "上漲但追價力道普通", "價漲量縮": "上漲但追價意願不足，小心反彈無力",
    "價跌量增": "賣壓沉重，有人急著出場", "價跌量平": "下跌但賣壓沒有擴大", "價跌量縮": "下跌但賣壓減輕，有惜售跡象",
    "價平量增": "多空交戰激烈，留意變盤", "價平量平": "觀望", "價平量縮": "觀望、量能退潮",
}


def 量價標籤(K, 量, 天數=5):
    """最近幾天的量價關係：漲跌看收盤、量看成交金額比前 5 日平均（多 15% 算量增、少 15% 算量縮）。
    回傳 [(日期, 標籤, 量比)]（由舊到新），最後一筆是今天。"""
    k = K.merge(量.rename("量"), left_on="date", right_index=True, how="inner").reset_index(drop=True)
    if len(k) < 7:
        return []
    k["均量"] = k["量"].shift(1).rolling(5).mean()
    k["幅"] = k["close"].pct_change() * 100
    結果 = []
    for _, r in k.tail(天數).iterrows():
        if pd.isna(r["均量"]) or r["均量"] <= 0:
            continue
        比 = r["量"] / r["均量"]
        價 = "價漲" if r["幅"] > 0.2 else ("價跌" if r["幅"] < -0.2 else "價平")
        量字 = "量增" if 比 >= 1.15 else ("量縮" if 比 <= 0.85 else "量平")
        結果.append((r["date"], 價 + 量字, float(比)))
    return 結果


def 櫃買加權比(加權K, 櫃買K, 天數=250):
    """櫃買指數 ÷ 加權指數（起點＝100）：往上＝中小型股比大型權值股強。回傳 (比值 Series, 20 日均線, 白話)。"""
    if 加權K is None or 櫃買K is None:
        return None, None, ""
    r = (櫃買K.set_index("date")["close"] / 加權K.set_index("date")["close"]).dropna()
    if len(r) < 40:
        return None, None, ""
    均 = r.rolling(20).mean()
    r, 均 = r.tail(天數), 均.tail(天數)
    基 = r.iloc[0]
    r, 均 = r / 基 * 100, 均 / 基 * 100
    變5, 變20 = (r.iloc[-1] / r.iloc[-6] - 1) * 100, (r.iloc[-1] / r.iloc[-21] - 1) * 100
    強 = lambda v: f"櫃買比加權{'強' if v > 0 else '弱'} {abs(v):.1f}%"
    文字 = f"近 20 日{強(變20)}、近 5 日{強(變5)}；比值{'在' if r.iloc[-1] >= 均.iloc[-1] else '跌破'} 20 日均線{'之上' if r.iloc[-1] >= 均.iloc[-1] else ''}，"
    if 變20 > 0 and r.iloc[-1] >= 均.iloc[-1]:
        文字 += "資金偏向中小型股。"
    elif 變20 < 0 and r.iloc[-1] < 均.iloc[-1]:
        文字 += "資金集中在大型權值股，中小型股相對弱。"
    else:
        文字 += "強弱正在轉換，還沒有明確方向。"
    return r, 均, 文字


電子產業 = {"半導體", "電子零組件", "電腦及週邊設備", "光電", "通信網路", "電子通路", "資訊服務", "其他電子", "數位雲端"}
電信代號 = {"2412", "3045", "4904"}


def 撐盤分組(表):
    """把權值貢獻表分成 電子／金融／電信／傳產 四組合計點數，判斷是誰在撐盤。回傳 (Series, 白話)。"""
    組 = np.where(表["代號"].isin(電信代號), "電信", np.where(表["產業"].isin(電子產業), "電子",
                 np.where(表["產業"] == "金融保險", "金融", "傳產")))
    s = 表.groupby(組)["貢獻點數"].sum().reindex(["電子", "金融", "電信", "傳產"]).fillna(0)
    撐 = s[s > 0.5].sort_values(ascending=False)
    拖 = s[s < -0.5].sort_values()
    句 = []
    if len(撐):
        句.append("撐盤：" + "、".join(f"{k} {v:+.0f} 點" for k, v in 撐.items()))
    if len(拖):
        句.append("拖盤：" + "、".join(f"{k} {v:+.0f} 點" for k, v in 拖.items()))
    文字 = "；".join(句) + "。" if 句 else "各組貢獻都很小。"
    防禦 = s["金融"] + s["電信"]
    if s["電子"] < -0.5 and 防禦 > 0.5:
        文字 += "電子弱、金融電信逆勢撐盤，屬於防禦型撐盤，資金偏保守。"
    elif s["電子"] > 0.5 and 防禦 < -0.5:
        文字 += "電子帶頭、防禦股被賣，資金偏積極。"
    elif s["電子"] > 0.5 and abs(s["電子"]) > abs(s.drop("電子")).sum():
        文字 += "主要靠電子權值股撐盤。"
    return s, 文字


def 避風港與提款機(今日, 大盤5日=None, 最少家數=5):
    """避風港＝近 5 日比大盤抗跌（或逆勢上漲）的族群；提款機＝前 20 日漲多、這 5 天被賣最多的族群（獲利了結）。
    回傳 (避風港表, 提款機表)，欄位 5日、20日、家數。"""
    五 = 族群資料(今日, "5 日")[0]
    二十 = 族群資料(今日, "20 日")[0]
    t = pd.DataFrame({"5日": 五["漲跌幅"], "家數": 五["家數"]}).join(二十["漲跌幅"].rename("20日"))
    t = t[t["家數"] >= 最少家數].dropna()
    if t.empty:
        return t, t
    基 = 大盤5日 if 大盤5日 is not None else float(t["5日"].median())
    港 = t[(t["5日"] > 基 + 1.5) & (t["5日"] > 0)].nlargest(3, "5日")
    提 = t[(t["20日"] >= t["20日"].quantile(0.7)) & (t["5日"] < 基 - 1.5)].nsmallest(3, "5日")
    return 港, 提


def 恐慌溫度計(美股=None, 匯率=None):
    """反向思考用：VIX 在過去一年的位置、美元兌台幣在一年區間的位置（台幣越貶＝外資匯出壓力越大）。
    每項換成 0～100 的「恐慌分數」再平均。回傳 (項目 [(名稱, 數值字, 說明, 分數)], 溫度, 等級, 白話)。"""
    項們 = []
    if 美股 is not None and "VIX" in 美股:
        v = 美股["VIX"].dropna().tail(252)
        if len(v) >= 60:
            現 = float(v.iloc[-1])
            分 = float((v < 現).mean() * 100)
            級 = "平靜" if 現 < 15 else "正常" if 現 < 20 else "緊張" if 現 < 30 else "恐慌"
            項們.append(("VIX 恐慌指數", f"{現:.1f}", f"{級}・比過去一年 {分:.0f}% 的日子高", 分))
    if 匯率 is not None and len(匯率) >= 60:
        x = 匯率.set_index("date")["usdtwd"].dropna().tail(252)
        現, 低, 高 = float(x.iloc[-1]), float(x.min()), float(x.max())
        分 = (現 - 低) / (高 - 低) * 100 if 高 > 低 else 50.0
        變 = (現 / float(x.iloc[-21]) - 1) * 100 if len(x) > 21 else 0.0
        說 = f"{'一年' if len(x) >= 240 else f'近 {len(x)} 日'}區間 {低:.2f}～{高:.2f}，20 日台幣{'貶' if 變 > 0 else '升'} {abs(變):.1f}%"
        項們.append(("美元兌台幣", f"{現:.2f}", 說, 分))
    if not 項們:
        return [], None, "", ""
    溫 = float(np.mean([p[3] for p in 項們]))
    if 溫 >= 75:
        級, 話 = "恐慌", "市場很怕，反向思考常是分批研究布局的時機，但要等止跌訊號。"
    elif 溫 >= 55:
        級, 話 = "偏緊張", "情緒偏保守，留意是否繼續升溫。"
    elif 溫 >= 30:
        級, 話 = "中性", "情緒還算平穩。"
    else:
        級, 話 = "樂觀", "市場很放心，反向思考要小心追高。"
    return 項們, 溫, 級, 話


# ========== 24. 支撐壓力回測、缺口清單、跌破／站回、金融股看獲利、美股龍頭超賣 ==========
def 支撐壓力回測(K, 間隔=5, 往後=20, 守住天數=3, 碰到=0.003, 跌破=0.01, 範圍=0.05, 起=250):
    """這些自動價位過去準不準：每隔幾天站在「當時」只用當時以前的資料畫價位，看之後 20 天有沒有碰到、碰到後有沒有守住。
    支撐守住＝碰到那天起 守住天數 內收盤都沒跌破價位 1% 以上；壓力守住＝收盤都沒突破 1% 以上。
    另外放「隨機對照」：距離收盤 1～4% 的任意價位，用來比較自動價位是不是真的比較有用。
    回傳每次測試的明細 DataFrame（類別, 角色, 共振, 守住）。"""
    k = K.dropna(subset=["close"]).reset_index(drop=True)
    低, 高, 收們 = k["low"].values, k["high"].values, k["close"].values
    列們 = []
    for t in range(起, len(k) - 往後, 間隔):
        sr = 支撐壓力(k.iloc[:t + 1])
        收 = sr["收盤"]
        價位 = sr["價位"]
        共 = {n for z in 共振區(價位) for n in z["成員"]}
        候選 = [(r["類別"], r["價位"], r["角色"], r["名稱"] in 共) for _, r in 價位.iterrows()
                if 0.005 <= abs(r["距離%"]) / 100 <= 範圍]
        候選 += [("隨機對照", 收 * (1 - d), "支撐", False) for d in (0.01, 0.02, 0.03, 0.04)]
        候選 += [("隨機對照", 收 * (1 + d), "壓力", False) for d in (0.01, 0.02, 0.03, 0.04)]
        for 類, 價, 角, 共振 in 候選:
            段 = slice(t + 1, t + 1 + 往後)
            碰 = np.where(低[段] <= 價 * (1 + 碰到))[0] if 角 == "支撐" else np.where(高[段] >= 價 * (1 - 碰到))[0]
            if not len(碰):
                continue
            i = t + 1 + int(碰[0])
            之後 = 收們[i:i + 守住天數 + 1]
            守 = bool((之後 >= 價 * (1 - 跌破)).all()) if 角 == "支撐" else bool((之後 <= 價 * (1 + 跌破)).all())
            列們.append((類, 角, 共振, 守))
    return pd.DataFrame(列們, columns=["類別", "角色", "共振", "守住"])


def 回測摘要(明細):
    """依方法彙總守住率，另外列「共振區裡的價位」與「全部自動價位」。"""
    if 明細.empty:
        return pd.DataFrame()
    自動 = 明細[明細["類別"] != "隨機對照"]
    組們 = [(c, 明細[明細["類別"] == c]) for c in ("均線", "回檔", "缺口", "前高低", "整數", "分價量")]
    組們 += [("共振區", 自動[自動["共振"]]), ("全部自動價位", 自動), ("隨機對照", 明細[明細["類別"] == "隨機對照"])]
    列們 = []
    for 名, g in 組們:
        if len(g) < 5:
            continue
        支, 壓 = g[g["角色"] == "支撐"], g[g["角色"] == "壓力"]
        列們.append({"方法": 名, "測試次數": len(g), "守住率%": g["守住"].mean() * 100,
                   "支撐守住%": 支["守住"].mean() * 100 if len(支) else np.nan,
                   "壓力守住%": 壓["守住"].mean() * 100 if len(壓) else np.nan})
    return pd.DataFrame(列們).round(1)


def 缺口清單(K):
    """全部還沒回補的缺口（資料有幾年就看幾年），由近到遠。"""
    if not 有開高低(K):
        return pd.DataFrame()
    收 = float(K["close"].iloc[-1])
    最後 = K["date"].iloc[-1]
    列們 = []
    for 下, 上, 日, 向 in 找缺口(K, 天數=len(K)):
        邊 = 上 if 上 < 收 else 下
        列們.append({"日期": 日, "方向": "向上跳空（支撐）" if 向 == "向上" else "向下跳空（壓力）", "下緣": 下, "上緣": 上,
                   "缺口大小%": (上 / 下 - 1) * 100, "距離%": (邊 / 收 - 1) * 100,
                   "已過交易日": int((K["date"] > 日).sum()) if 日 < 最後 else 0})
    if not 列們:
        return pd.DataFrame()
    return pd.DataFrame(列們).sort_values("距離%", key=abs).reset_index(drop=True)


def 還原K線(歷史):
    """一檔股票的指標表（date, open, high, low, 收盤, 還原價）換成還原後的開高低收，最新一天等於實際股價，
    除權息才不會被當成跳空缺口。"""
    if 歷史 is None or len(歷史) < 60:
        return None
    h = 歷史[["date", "open", "high", "low", "收盤", "還原價"]].dropna(subset=["收盤"]).sort_values("date").reset_index(drop=True)
    比 = (h["還原價"] / h["收盤"]).where(h["收盤"] > 0).ffill().fillna(1)
    比 = 比 / 比.iloc[-1]
    K = pd.DataFrame({"date": h["date"], "open": h["open"] * 比, "high": h["high"] * 比, "low": h["low"] * 比,
                      "close": h["收盤"] * 比})
    return K.dropna().reset_index(drop=True)


def 跌破站回(K, 量=None):
    """今天收盤跟昨天比，有沒有跌破或站回重要價位（月線、季線、半年線、年線、共振區、黑 K 一半）。
    回傳 [(「跌破」/「站回」, 名稱, 價位)]。"""
    if K is None or len(K) < 130:
        return []
    今, 昨 = float(K["close"].iloc[-1]), float(K["close"].iloc[-2])
    結果 = []
    昨K = K.iloc[:-1]
    for n, 名 in 均線名稱.items():   # 均線用各自那天的值比較
        if len(K) > n:
            今均, 昨均 = float(K["close"].tail(n).mean()), float(昨K["close"].tail(n).mean())
            if 昨 >= 昨均 and 今 < 今均:
                結果.append(("跌破", 名, 今均))
            elif 昨 <= 昨均 and 今 > 今均:
                結果.append(("站回", 名, 今均))
    sr = 支撐壓力(昨K, 量=量)
    for z in 共振區(sr["價位"]):
        區 = f"{z['下']:,.0f}～{z['上']:,.0f} 共振區" if z["上"] > 1000 else f"{z['下']:,.2f}～{z['上']:,.2f} 共振區"
        if 昨 >= z["下"] and 今 < z["下"]:
            結果.append(("跌破", 區, z["下"]))
        elif 昨 <= z["上"] and 今 > z["上"]:
            結果.append(("站回", 區, z["上"]))
    黑 = 黑K一半(昨K)
    if 黑 and 昨 <= 黑["中點"] < 今:
        結果.append(("站回", f"{黑['日期']:%m/%d} 黑 K 一半", 黑["中點"]))
    return 結果


def 金融股獲利表():
    """金融保險股的單季、今年累計 EPS 與稅後淨利，跟去年同期比（金融股月營收含投資損益，波動大，看獲利比較準）。"""
    f = 資料夾 / "fundamental" / "income.csv"
    if not f.exists():
        return pd.DataFrame()
    t = pd.read_csv(f, dtype={"code": str})
    金 = _股本表().index[_股本表()["產業"] == "金融保險"]
    t = t[t["code"].isin(金)].dropna(subset=["eps"]).sort_values(["code", "quarter"]).copy()
    if t.empty:
        return pd.DataFrame()
    t["序"] = t["quarter"].str[:4].astype(int) * 4 + t["quarter"].str[-1].astype(int)
    前 = t.groupby("code")[["序", "eps", "netinc"]].shift()
    第一季 = t["quarter"].str[-1] == "1"
    連續 = 前["序"] == t["序"] - 1
    t["單季EPS"] = np.where(第一季, t["eps"], np.where(連續, t["eps"] - 前["eps"], np.nan))
    t["單季淨利"] = np.where(第一季, t["netinc"], np.where(連續, t["netinc"] - 前["netinc"], np.nan))
    鍵 = t.set_index(["code", "序"])
    最新 = t.groupby("code").tail(1).set_index("code")
    去年 = list(zip(最新.index, 最新["序"] - 4))
    def 年增(今, 去):
        return np.where(np.asarray(去) > 0, (np.asarray(今) / np.asarray(去) - 1) * 100, np.nan)
    表 = pd.DataFrame({"季度": 最新["quarter"], "單季EPS": 最新["單季EPS"],
                       "去年同季EPS": 鍵["單季EPS"].reindex(去年).values,
                       "累計EPS": 最新["eps"], "去年同期累計EPS": 鍵["eps"].reindex(去年).values,
                       "單季淨利(億)": 最新["單季淨利"] / 1e5}, index=最新.index)
    表["單季EPS年增%"] = 年增(表["單季EPS"], 表["去年同季EPS"])
    表["累計EPS年增%"] = 年增(表["累計EPS"], 表["去年同期累計EPS"])
    四季 = 近四季EPS表()
    表["近四季EPS"] = 四季["近四季EPS"].reindex(表.index)
    return 表.round(2)


美股龍頭 = ("輝達", "台積電 ADR", "博通", "超微", "美光", "蘋果", "特斯拉", "費城半導體", "那斯達克")


def 美股超賣(美股, 名單=美股龍頭):
    """美股龍頭的 RSI(14)、距 20 日均線、距 60 日高點、連跌天數。RSI < 30 或跌破月線 8% 以上＝超賣，RSI < 35＝接近超賣。
    回傳 DataFrame（index＝名稱），依 RSI 由低到高。"""
    if 美股 is None:
        return pd.DataFrame()
    列們 = {}
    for 名 in 名單:
        if 名 not in 美股:
            continue
        s = 美股[名].dropna()
        if len(s) < 70:
            continue
        變 = s.diff()
        漲 = 變.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        跌 = (-變.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rsi = float(100 - 100 / (1 + 漲.iloc[-1] / 跌.iloc[-1])) if 跌.iloc[-1] > 0 else 100.0
        乖離 = float((s.iloc[-1] / s.tail(20).mean() - 1) * 100)
        回落 = float((s.iloc[-1] / s.tail(60).max() - 1) * 100)
        連跌 = 0
        for v in 變.iloc[::-1]:
            if v < 0:
                連跌 += 1
            else:
                break
        狀態 = "超賣" if rsi < 30 or 乖離 < -8 else ("接近超賣" if rsi < 35 or 乖離 < -5 else ("過熱" if rsi > 70 else ""))
        列們[名] = {"日期": s.index[-1], "收盤": float(s.iloc[-1]), "RSI": round(rsi, 1), "距月線%": round(乖離, 1),
                  "距60日高%": round(回落, 1), "連跌天數": 連跌, "狀態": 狀態}
    return pd.DataFrame(列們).T.sort_values("RSI") if 列們 else pd.DataFrame()
