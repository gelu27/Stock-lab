# 計算核心：讀資料庫、算技術指標、選股、回測
# 想調整選股或回測規則，主要改這個檔案

import re
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
    "預估本益比 低→高": ("預估本益比", True),
    "明年預估本益比 低→高": ("明年預估本益比", True),
    "明年 EPS 成長 高→低": ("明年EPS成長%", False),
    "預估 EPS 上修 多→少": ("預估修正%", False),
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
    return 修正分割估值(表.sort_values(["code", "date"], ignore_index=True))


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
        e = 調整分割EPS(pd.read_csv(f, dtype={"code": str})).sort_values(["code", "quarter"])
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
    t = 調整分割EPS(t[t["code"] == str(代號)])
    t = t.dropna(subset=["eps"]).sort_values("quarter")
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


def 毛利率表(單季=None):
    """每檔最新一季的單季毛利率，和上一季、去年同季比較（百分點）。單季＝單季損益() 的結果（回測時只給當時已公布的季）。"""
    t = (單季損益() if 單季 is None else 單季).dropna(subset=["毛利率"])
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
    t = 調整分割EPS(pd.read_csv(f, dtype={"code": str}))
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


@lru_cache(maxsize=2)
def _讀參考價(_更新時間):
    t = pd.read_csv(資料夾 / "fundamental" / "dividend.csv", dtype={"code": str}, usecols=["code", "date", "ref"])
    t["date"] = pd.to_datetime(t["date"])
    t["ref"] = pd.to_numeric(t["ref"], errors="coerce")
    return t.dropna().drop_duplicates(["code", "date"], keep="last")


def 除權息參考價():
    """除權息（含面額分割）當天的參考價：code、date、ref。"""
    f = 資料夾 / "fundamental" / "dividend.csv"
    if not f.exists():
        return pd.DataFrame(columns=["code", "date", "ref"])
    return _讀參考價(f.stat().st_mtime)


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
    # 除權息當天交易所的漲跌欄是「X」（讀進來是空值），以前會改用收盤價推算，股利就沒補回去；
    # 改用除權息表的參考價：日報酬 ＝ 收盤 ÷ 參考價 − 1（2026-11-08 修正，0050 今年少算約 3 個百分點）
    參考 = 除權息參考價()
    if len(參考):
        參考價 = 表[["code", "date"]].merge(參考, on=["code", "date"], how="left")["ref"].to_numpy()
        補 = 表["日報酬"].isna() & (參考價 > 0)
        表.loc[補, "日報酬"] = (表.loc[補, "收盤"].to_numpy() / 參考價[補.to_numpy()] - 1).astype(表["日報酬"].dtype)
    # 沒有漲跌資料（例如減資、暫停交易後恢復）時才用收盤價推算；
    # 超過 10% 漲跌停限制的變動通常是減資等公司行動，不算成真正的漲跌
    # 槓桿型 ETF（代號結尾 L，例如 00631L 正2）漲跌幅限制是倍數 × 10%，不能截在 10.5%，否則還原價會失真
    上限 = pd.Series(np.where(表["code"].astype(str).str.fullmatch(r"00\d{3,4}L"), 0.21, 0.105), index=表.index)
    推算 = 群["收盤"].pct_change()
    推算 = 推算.where(推算.abs() <= 上限, 0)
    表["日報酬"] = 表["日報酬"].fillna(推算).fillna(0).clip(-上限, 上限)
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
    # MACD 柱（DIF − 訊號線，用還原價）與今天是否剛翻紅；講義實測：單獨翻紅沒優勢，搭配多頭排列 20 日超額 +1.03%
    表["MACD柱"] = 表.groupby("code", sort=False)["還原價"].transform(lambda s: MACD(s)[2])
    表["MACD翻紅"] = (表["MACD柱"] > 0) & (表.groupby("code", sort=False)["MACD柱"].shift() <= 0)
    # 均線糾結：5、10、20、60 日線最高與最低差距 < 2%（講義的「盤整走勢」；實測之後 20 日超額 −0.79%，偏弱）
    均 = 表[["MA5", "MA10", "MA20", "MA60"]]
    表["均線糾結"] = (均.max(axis=1) / 均.min(axis=1) - 1) < 0.02
    del 均

    # 籌碼面（股數換成張數）
    if "total" in 表.columns:
        for 英, 中 in (("foreign", "外資買超"), ("trust", "投信買超"), ("dealer", "自營買超"), ("total", "法人買超")):
            表[中] = (表[英] / 1000).round()
        群 = 表.groupby("code", sort=False)
        表["法人5日買超"] = _滾動(群, "法人買超", 5, "sum", 1).round()
        表["法人10日買超"] = _滾動(群, "法人買超", 10, "sum", 1).round()
        表["外資連買"] = _連續天數(表["外資買超"] > 0, 表["code"])
        表["投信連買"] = _連續天數(表["投信買超"] > 0, 表["code"])
        表["外資連賣"] = _連續天數(表["外資買超"] < 0, 表["code"])
        # 土洋對作：外資賣、投信買（理財達人秀：要看急殺時誰接手）
        表["土洋對作"] = _連續天數((表["外資買超"] < 0) & (表["投信買超"] > 0), 表["code"])
        表["融資餘額"] = 表["margin"]
        表["融資5日增減"] = ((表["margin"] / 群["margin"].shift(5) - 1) * 100).round(1)
        加融資維持率(表)
    數字 = 表.select_dtypes("float64").columns
    表[數字] = 表[數字].astype("float32")
    return 表


def 融資成本估算(代號, 收盤, 日報酬, 融資):
    """個股融資平均成本（估算）。交易所不公布個股維持率，只能從每天融資餘額推：
    融資增加的張數用當天收盤價計入加權平均成本，減少（賣出或還款）時成本不變；
    遇到面額分割／減資（收盤跳動跟交易所漲跌對不起來超過 15%），成本與餘額一起換算。
    四個參數都是同樣長度、依 代號、日期 排好的 numpy 陣列。一次跑完全部股票（約 75 萬筆 1 秒內）。"""
    n = len(收盤)
    成本 = [np.nan] * n
    代號, 收盤, 日報酬, 融資 = list(代號), np.asarray(收盤, float).tolist(), np.asarray(日報酬, float).tolist(), \
        np.asarray(融資, float).tolist()   # 純 Python 數字比 numpy 單一元素快好幾倍
    c = 前餘 = 前價 = np.nan
    前代號 = None
    for i in range(n):
        if 代號[i] != 前代號:
            c = 前餘 = 前價 = np.nan
            前代號 = 代號[i]
        b, p = 融資[i], 收盤[i]
        if not (p > 0):
            成本[i] = c
            continue
        if 前價 > 0:
            f = (p / 前價) / (1 + 日報酬[i])
            if f < 0.85 or f > 1.15:   # 分割、減資
                c *= f
                前餘 /= f
        前價 = p
        if b != b:                     # 融資還沒公布：沿用
            成本[i] = c
            continue
        if c != c or not (前餘 > 0):
            c = p
        elif b > 前餘:
            c = (c * 前餘 + p * (b - 前餘)) / b
        前餘 = b
        成本[i] = c if b > 0 else np.nan
    return np.array(成本, dtype=float)


def 加融資維持率(表):
    """在 計算指標 的表上加：融資成本、融資維持率（個股估算，上市融資成數 60%、上櫃 50%）、融資20日增減、
    維持率20日低、距今年高點、融資洗完、接刀風險。表要依 code、date 排好。
    2026-11 回測（2022-11～2026-10）：0050 成分股挑跌最深 5 檔、維持率越低越好，120 日反而輸 0050 約 10～17 個百分點；
    跌超過 30% 之後「融資 20 日減少 > 15%」或「維持率曾跌破 130%」（融資已洗掉）才有小幅正超額。"""
    成本 = 融資成本估算(表["code"].to_numpy(), 表["收盤"].to_numpy("float64"), 表["日報酬"].to_numpy("float64"),
                     表["margin"].to_numpy("float64"))
    成數 = np.where(表["市場"].to_numpy() == "上櫃", 0.5, 0.6)
    表["融資成本"] = np.round(成本, 2)
    表["融資維持率"] = np.round(表["收盤"].to_numpy("float64") / (成本 * 成數) * 100, 1)
    群 = 表.groupby("code", sort=False)
    前 = 群["margin"].shift(20)
    表["融資20日增減"] = ((表["margin"] / 前.where(前 > 0) - 1) * 100).round(1)
    表["維持率20日低"] = _滾動(群, "融資維持率", 20, "min", 1)
    年 = 表["date"].dt.year
    表["距今年高點"] = ((表["還原價"] / 表.groupby([表["code"], 年], sort=False)["還原價"].cummax() - 1) * 100).round(1)
    深 = 表["距52週高點"] <= -30
    有量 = 表["margin"] >= 200        # 融資太少的股票維持率沒意義
    表["融資洗完"] = 深 & 有量 & ((表["融資20日增減"] <= -15) | (表["維持率20日低"] < 130))
    表["接刀風險"] = 深 & 有量 & (表["融資20日增減"] >= 15)


def 融資訊號(列):
    """跌深榜、個股頁用的一句話標籤。"""
    if bool(列.get("融資洗完", False)):
        return "🧹 融資洗完"
    if bool(列.get("接刀風險", False)):
        return "🔪 接刀風險"
    v = 列.get("融資維持率")
    if v is not None and v == v and 列.get("融資餘額", 0) >= 200:
        if v < 130:
            return "🚨 低於追繳線"
        if v < 145:
            return "⚠️ 接近追繳"
    return ""


def 讀取0050成分():
    """data/etf0050.csv（update_data.抓0050成分 每天抓元大或 MoneyDJ）→ 代號 list；沒有就回 None。"""
    f = 資料夾 / "etf0050.csv"
    if not f.exists():
        return None
    t = pd.read_csv(f, dtype={"code": str})
    return t["code"].tolist() if len(t) >= 40 else None


def 跌深榜(今日, 名單=None, 檔數=50):
    """0050 成分股從今年高點跌到最新收盤的跌幅排行。名單 None → data/etf0050.csv，再沒有就用上市市值前 50 大近似。
    回傳 (表, 來源說明)。"""
    t = 今日[(今日["收盤"] > 0) & 今日["代號"].str.fullmatch(r"\d{4}")].copy()
    來源 = "元大 0050 持股"
    if 名單 is None:
        名單 = 讀取0050成分()
    if 名單 is None:
        市 = t[t["市場"] == "上市"]
        市值 = 市["收盤"].astype(float) * 市.get("發行股數", pd.Series(np.nan, index=市.index))
        名單 = 市.loc[市值.nlargest(50).index, "代號"].tolist()
        來源 = "上市市值前 50 大（近似，還沒抓到元大官方持股）"
    t = t[t["代號"].isin(名單)]
    if "發行股數" in t.columns:
        t["市值億"] = (t["收盤"].astype(float) * t["發行股數"] / 1e8).round(0)
    t["訊號"] = t.apply(融資訊號, axis=1) if len(t) else ""
    return t.sort_values("距今年高點").head(檔數), 來源


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
    if c.get("MACD翻紅多頭") and "MACD翻紅" in 結果.columns:
        結果 = 結果[結果["MACD翻紅"].astype(bool) & (結果["MA5"] > 結果["MA10"]) & (結果["MA10"] > 結果["MA20"])
                  & (結果["MA20"] > 結果["MA60"])]
    if c.get("排除均線糾結") and "均線糾結" in 結果.columns:
        結果 = 結果[~結果["均線糾結"].astype(bool)]
    if c.get("20日漲幅下限") is not None:
        結果 = 結果[結果["20日漲幅"] >= c["20日漲幅下限"]]
    if c.get("RSI區間"):
        結果 = 結果[結果["RSI"].between(*c["RSI區間"])]
    if c.get("量比下限") is not None:
        結果 = 結果[結果["量比"] >= c["量比下限"]]
    for 鍵, 欄 in (("外資持股比下限", "外資持股比"), ("外資持股20日變化下限", "外資持股20日變化")):
        if c.get(鍵) is not None and 欄 in 結果.columns:
            結果 = 結果[結果[欄] >= c[鍵]]
    for 鍵, 欄 in (("當沖比率上限", "當沖比率"), ("負債比上限", "負債比")):
        if c.get(鍵) is not None and 欄 in 結果.columns:
            結果 = 結果[結果[欄] <= c[鍵]]
    for 鍵, 欄 in (("合約負債年增下限", "合約負債年增"), ("能見度月下限", "能見度月")):
        if c.get(鍵) is not None and 欄 in 結果.columns:
            結果 = 結果[結果[欄] >= c[鍵]]
    for 鍵, 欄 in (("預估本益比上限", "預估本益比"), ("明年預估本益比上限", "明年預估本益比")):
        if c.get(鍵) is not None and 欄 in 結果.columns:
            結果 = 結果[結果[欄] <= c[鍵]]
    if c.get("預估修正下限") is not None:
        結果 = 結果[結果["預估修正%"] >= c["預估修正下限"]] if "預估修正%" in 結果.columns else 結果.iloc[0:0]
    if c.get("明年EPS成長下限") is not None and "明年EPS成長%" in 結果.columns:
        結果 = 結果[結果["明年EPS成長%"] >= c["明年EPS成長下限"]]
    if c.get("預估業外占比上限") is not None and "預估業外占比%" in 結果.columns:
        結果 = 結果[結果["預估業外占比%"] <= c["預估業外占比上限"]]
    if c.get("排除預估分歧") and "預估分歧%" in 結果.columns:
        結果 = 結果[~(結果["預估分歧%"] > 預估分歧門檻)]
    if c.get("自由現金流為正") and "近四季自由現金流億" in 結果.columns:
        結果 = 結果[結果["近四季自由現金流億"] > 0]
    for 鍵, 欄 in (("外資連買下限", "外資連買"), ("投信連買下限", "投信連買"), ("法人5日買超下限", "法人5日買超"),
                 ("外資連賣下限", "外資連賣"), ("土洋對作下限", "土洋對作")):
        if c.get(鍵) is not None and 欄 in 結果.columns:
            結果 = 結果[結果[欄] >= c[鍵]]
    if c.get("融資洗完") and "融資洗完" in 結果.columns:
        結果 = 結果[結果["融資洗完"].astype(bool)]
    if c.get("融資維持率上限") is not None and "融資維持率" in 結果.columns:
        結果 = 結果[結果["融資維持率"] <= c["融資維持率上限"]]
    if c.get("融資佔股本排名上限") is not None and "融資佔股本排名%" in 結果.columns:
        結果 = 結果[結果["融資佔股本排名%"].fillna(0) <= c["融資佔股本排名上限"]]
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
    股數 = c["shares"].astype(float)
    # 面額分割後，公司基本資料的面額常常還沒改（股數＝股本÷10 元），發行股數要乘上分割倍數，市值、週轉率才不會少算
    for (代號, _, 倍) in 分割紀錄().itertuples(index=False):
        if 代號 in 股數.index and abs(c.at[代號, "capital"] / 10 - 股數[代號]) < 1:
            股數[代號] = round(股數[代號] * 倍)
    return pd.DataFrame({"股本億": (c["capital"] / 1e8).round(2), "發行股數": 股數,
                         "產業": c["industry"].fillna("") if "industry" in c else ""})


# ---------- 面額分割（與大比例配股）：每股數字換成分割後的基準 ----------
分割門檻 = 1.5  # 除權前收盤 ÷ 參考價 ≥ 1.5 才算（面額分割、大比例配股）；一般配股幾%影響小，不處理


@lru_cache(maxsize=2)
def _讀分割(_更新時間):
    t = pd.read_csv(資料夾 / "fundamental" / "dividend.csv", dtype={"code": str})
    t = t[t["type"].astype(str).str.strip() == "權"].copy()  # 只有「權」才能用參考價精準算出股數倍數（權息合併的會混到現金股利）
    t["倍數"] = pd.to_numeric(t["pre_close"], errors="coerce") / pd.to_numeric(t["ref"], errors="coerce")
    t = t[t["倍數"] >= 分割門檻]
    t["date"] = pd.to_datetime(t["date"])
    return t[["code", "date", "倍數"]].sort_values(["code", "date"], ignore_index=True)


def 分割紀錄():
    """面額分割與大比例配股：code、date（分割後第一個交易日）、倍數（1 股變幾股）。來源是交易所除權表的「權」。"""
    f = 資料夾 / "fundamental" / "dividend.csv"
    if not f.exists():
        return pd.DataFrame(columns=["code", "date", "倍數"])
    return _讀分割(f.stat().st_mtime)


def 分割倍數(代號, 日期):
    """這天的每股數字（EPS、每股淨值、股利）要除以多少，才會跟現在的股數基準一致。"""
    s = 分割紀錄()
    s = s[(s["code"] == str(代號)) & (s["date"] > pd.Timestamp(日期))]
    return float(s["倍數"].prod()) if len(s) else 1.0


def 分割倍數序列(代號, 日期們):
    """每個日期各自的分割倍數（例如換算週轉率：分割前的成交股數要乘上倍數，才能跟現在的發行股數比）。"""
    日期們 = pd.to_datetime(pd.Series(日期們))
    倍 = pd.Series(1.0, index=日期們.index)
    s = 分割紀錄()
    for 日, 數 in s.loc[s["code"] == str(代號), ["date", "倍數"]].itertuples(index=False):
        倍[日期們 < 日] *= 數
    return 倍.to_numpy()


_季報期限 = {1: (0, "05-15"), 2: (0, "08-14"), 3: (0, "11-14"), 4: (1, "03-31")}


def _季報期限日(季度):
    年, 季 = int(str(季度)[:4]), int(str(季度)[-1])
    加年, 月日 = _季報期限[季]
    return pd.Timestamp(f"{年 + 加年}-{月日}")


def 調整分割EPS(t):
    """財報 EPS 是公布當時的股數算的：分割前公布的季報，EPS 除以分割倍數，才能跟分割後的季報相加、跟現在股價比。
    t 要有 code、quarter、eps（有 netinc 更準）。季報期限在分割日之前 → 舊股數；
    季底在分割前、期限在分割後（可能分割前就公布了）→ 用「淨利 ÷ EPS」推算股數，跟上一季比有沒有放大來判斷。"""
    s = 分割紀錄()
    if not len(s) or "eps" not in t.columns or not len(t):
        return t
    s = s[s["code"].isin(set(t["code"]))]
    if not len(s):
        return t
    t = t.copy()
    t["eps"] = t["eps"].astype(float)
    for (代號, 日, 倍) in s.itertuples(index=False):
        列 = t.index[t["code"] == 代號]
        if not len(列):
            continue
        季們 = t.loc[列, "quarter"]
        期限 = 季們.map(_季報期限日)
        季底 = 季們.map(lambda q: pd.Timestamp(f"{str(q)[:4]}-{int(str(q)[-1]) * 3:02d}-01") + pd.offsets.MonthEnd(0))
        舊 = 期限 < 日
        模糊 = (季底 < 日) & ~舊
        if 模糊.any() and "netinc" in t.columns:
            股數 = (t.loc[列, "netinc"] / t.loc[列, "eps"]).where(t.loc[列, "eps"].abs() > 0)
            for i in 季們.index[模糊]:
                前 = 股數[舊 & 股數.notna()]
                if len(前) and pd.notna(股數[i]):
                    舊[i] = 股數[i] / 前.iloc[-1] < 倍 ** 0.5  # 股數沒放大 → 還是分割前公布的
        t.loc[舊[舊].index, "eps"] = t.loc[舊[舊].index, "eps"] / 倍
    return t


@lru_cache(maxsize=64)
def _分割前估值(代號, 日):
    """分割前最後一天的每股數字：(收盤÷本益比＝EPS, 收盤÷淨值比＝每股淨值, 收盤×殖利率＝股利)。"""
    t = _讀每日檔("prices", 代號=[代號], 起日=pd.Timestamp(日) - pd.Timedelta(days=20))
    if t is None:
        return None
    t = t[t["date"] < pd.Timestamp(日)].sort_values("date")
    return None if t.empty else _每股數字(t.iloc[-1])


def _每股數字(r):
    def 除(a, b):
        return float(a) / float(b) if pd.notna(a) and pd.notna(b) and float(b) > 0 else np.nan
    return 除(r["close"], r.get("pe")), 除(r["close"], r.get("pb")), float(r["close"]) * float(r["dy"]) if pd.notna(r.get("dy")) else np.nan


def 修正分割估值(表):
    """交易所的本益比、殖利率、淨值比在分割後一段時間還用舊股數的 EPS、股利、淨值（例如緯穎分割後本益比 25 → 8，實際沒變）。
    分割日以後，每天的「隱含每股數字」若還跟分割前差不多（沒有縮成 1/倍數），就換算回來；交易所改好後自動停止換算。
    只看最近 15 個月內的分割（再早的，近四季財報都已是新股數）。"""
    if 表 is None or not len(表) or not {"pe", "pb", "dy", "close", "date", "code"} <= set(表.columns):
        return 表
    s = 分割紀錄()
    最新 = 表["date"].max()
    s = s[(s["date"] > 最新 - pd.Timedelta(days=460)) & (s["date"] <= 最新) & s["code"].isin(set(表["code"].unique()))]
    if not len(s):
        return 表
    for 欄 in ("pe", "pb", "dy"):
        表[欄] = 表[欄].astype("float64")
    for (代號, 日, 倍) in s.itertuples(index=False):
        本檔 = 表["code"] == 代號
        前 = 表[本檔 & (表["date"] < 日)]
        基 = _每股數字(前.loc[前["date"].idxmax()]) if len(前) else _分割前估值(代號, 日)
        if 基 is None:
            continue
        後 = 表.index[本檔 & (表["date"] >= 日)]
        收 = 表.loc[後, "close"].astype("float64")
        門檻 = 倍 ** -0.5  # 介於「沒調整（1）」和「已調整（1/倍數）」的中間
        for 欄, 基值, 現 in (("pe", 基[0], 收 / 表.loc[後, "pe"]), ("pb", 基[1], 收 / 表.loc[後, "pb"]),
                            ("dy", 基[2], 收 * 表.loc[後, "dy"])):
            if not (pd.notna(基值) and 基值 > 0):
                continue
            沒調 = 後[((現 / 基值) > 門檻).to_numpy() & (表.loc[後, 欄] > 0).to_numpy()]
            表.loc[沒調, 欄] = 表.loc[沒調, 欄] * (1 / 倍 if 欄 == "dy" else 倍)
    for 欄 in ("pe", "pb", "dy"):
        表[欄] = 表[欄].round(2).astype("float32")
    return 表


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


def 讀取匯率K線():
    """data/fx.csv 的美元兌台幣日 K（date, open, high, low, close）；還沒有開高低的日子用收盤代替。"""
    t = 讀取匯率()
    if t is None or t.empty:
        return None
    t = t.rename(columns={"usdtwd": "close"})
    for k in ("open", "high", "low"):
        t[k] = t[k].fillna(t["close"]) if k in t.columns else t["close"]
    return t[["date", "open", "high", "low", "close"]].reset_index(drop=True)


def 讀取台指期K線():
    """data/futures_basis.csv 的台指期近月日 K（date, open, high, low, close, month）；換月那天價格會跳一下。"""
    f = 資料夾 / "futures_basis.csv"
    if not f.exists():
        return None
    t = pd.read_csv(f, parse_dates=["date"], dtype={"month": str}).sort_values("date")
    t = t.rename(columns={"fut_close": "close", "fut_open": "open", "fut_high": "high", "fut_low": "low"})
    for k in ("open", "high", "low"):
        t[k] = t[k].fillna(t["close"]) if k in t.columns else t["close"]
    return t[["date", "open", "high", "low", "close", "month"]].reset_index(drop=True)


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
    "MACD 翻紅＋多頭排列": "MACD 柱由負翻正、且 5 > 10 > 20 > 60 日線多頭排列時買進；MACD 柱翻負時賣出（講義實測最有效的組合）",
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
    elif 策略 == "MACD 翻紅＋多頭排列":
        柱 = MACD(全部["還原價"])[2].reindex(表.index)
        多頭 = (均(5) > 均(10)) & (均(10) > 均(20)) & (均(20) > 均(60))
        想持有 = _進出狀態((柱 > 0) & (柱.shift() <= 0) & 多頭, 柱 < 0)
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
    """證交所基本市況報導（延遲約 5 到 20 秒）。回傳 DataFrame：code, name, close, change, high, low, time。
    代號 t00 是加權指數、o00 是櫃買指數（市場對照要給 {"o00": "上櫃"}）。"""
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
                       "change": 現價 - 昨收, "high": _數(m.get("h")), "low": _數(m.get("l")), "time": m.get("t"),
                       "volume": _數(m.get("v")),
                       "date": pd.Timestamp(m.get("d", "")) if m.get("d") else pd.NaT})
    return pd.DataFrame(結果)


def 套用即時價(r, 代號, 資料日, 現在=None, 抓報價=None):
    """個股報告用：資料庫最新一天之後有成交（盤中，或收盤後到晚上更新資料庫前），就用證交所即時價
    更新現價、漲跌、本益比、殖利率、淨值比、成交量；法人、融資、營收、均線等還是資料庫最近一天的。
    r 是個股那一列（pd.Series，要有 收盤、市場），資料日是資料庫最新日期。
    回傳 (新的 r, 說明文字)；不需要或抓不到回傳 (原本的 r, None)。說明例如「盤中 11/09 10:35 即時價」。
    抓報價：函式 (代號, 市場) → 即時報價() 格式的 DataFrame（網站用來加快取、測試用來不上網），預設直接抓證交所。"""
    現在 = 現在 or pd.Timestamp.now(tz="Asia/Taipei").tz_localize(None)
    資料日 = pd.Timestamp(資料日).normalize()
    if 現在.weekday() >= 5 or 現在.hour < 9 or 現在.normalize() <= 資料日 or str(r.get("市場")) not in ("上市", "上櫃"):
        return r, None
    try:
        市場 = str(r.get("市場"))
        t = 抓報價(代號, 市場) if 抓報價 else 即時報價([代號], {代號: 市場})
        x = t[t["code"] == 代號].iloc[0]
    except Exception:
        return r, None
    新, 舊 = float(x["close"]), float(r["收盤"])
    if pd.isna(新) or 新 <= 0 or not 舊 or pd.isna(x["date"]) or pd.Timestamp(x["date"]).normalize() <= 資料日:
        return r, None
    倍 = 新 / 舊
    r = r.copy()
    昨收 = 新 - float(x["change"])
    r["收盤"], r["漲跌"] = 新, float(x["change"])
    r["漲跌幅"] = r["漲跌"] / 昨收 * 100 if 昨收 > 0 else np.nan
    for 欄 in ("本益比", "淨值比", "還原價"):   # 還原價跟著調，均線換回原始股價的比例才不會變
        if 欄 in r and pd.notna(r[欄]):
            r[欄] = r[欄] * 倍
    if "殖利率" in r and pd.notna(r["殖利率"]):
        r["殖利率"] = r["殖利率"] / 倍
    if pd.notna(x.get("volume")) and "成交張數" in r:
        r["成交張數"] = float(x["volume"])
        if "volume" in r:
            r["volume"] = float(x["volume"]) * 1000
    時 = str(x.get("time") or "")[:5]
    盤中 = 現在.strftime("%H:%M") < "13:30" and (not 時 or 時 < "13:30")
    說明 = f"{'盤中' if 盤中 else '今日收盤'} {pd.Timestamp(x['date']):%m/%d} {時} 即時價".replace("  ", " ")
    r["即時說明"] = 說明
    return r, 說明


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

    符號 = {"t00": "%5ETWII", "o00": "%5ETWOII"}.get(代號) or f"{代號}.{'TWO' if 市場 == '上櫃' else 'TW'}"
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
請一律使用繁體中文（台灣用語），白話、專有名詞第一次出現用一句話解釋。

思考方式（參考券商研究報告的骨架，再加上技術面的出場紀律）：
A. 目標價是「算」出來的：一定寫清楚「幾倍 × 哪一年的 EPS（或每股淨值）」。
B. 評價方法跟著產業與獲利狀態走：
   - 一般獲利穩定的公司用本益比（P/E）；
   - 營建、金融保險、景氣循環股在谷底、或 EPS ≤ 0 的公司，改用股價淨值比（P/B），營建與金融再搭配殖利率；
   - 數據摘要裡的「建議評價方法」是網站依產業與 EPS 判斷的，除非有充分理由，照它的方法算；
   - 參考使用者提供的「近三年本益比／股價淨值比區間」判斷現在在歷史的哪個位階。
C. 先對上一季的答案：上一季（或最近月營收）有沒有照公司或市場預期走，再談下一季。
D. 成長來源要量化：稼動率、訂單能見度（B/B ratio、交期）、漲價幅度、新產能哪一季開始貢獻；說不出數字就寫「未找到」。
E. 預估要比較「前次 vs 本次」與「市場共識」：券商有上修或下修 EPS／目標價要寫出方向；找得到共識就比較，找不到就說找不到。
F. 好公司不等於好價格：判斷利多是否「已反應在股價」（本益比位階、距 52 週高點、近期漲幅），已反應就寫「等回落」而不是追價。
G. 先判斷格局再給做法（數據摘要有「格局」）：盤整看區間上下緣、上升趨勢買拉回、下降趨勢（跌破 10 日線）先不接刀。
H. 一定要寫「看錯了怎麼辦」：停損價要用網站算好的支撐（共振區、均線、缺口）或黑 K 一半，不要憑感覺給整數。
I. 不預測哪一天漲跌；只寫「站上／跌破哪個價位就怎樣」。
J. 一次性項目（訴訟和解、處分利益、匯兌、存貨回沖、賣資產、稅率變動）要排除後再看本業 EPS。
K. 先寫「這次跟上次差在哪」：數據摘要有「上次網站 AI 報告」就列本次 vs 前次（看法、合理價、今年／明年 EPS 與變動 %），沒有就寫「首次」；沒有變化就明說「維持」。
L. 合理價變動超過 10%，拆成 EPS／倍數／估值年度三塊；主要是倍數變的話要提醒「這是估值變化，不是獲利變好」。
M. 引用券商用中位數與區間（數據摘要的「券商共識」），寫出上修／下修家數與最樂觀、最悲觀是哪家；網站合理價跟共識中位數差超過 20% 要解釋原因。
N. 券商前次目標價低於報告前收盤價的上修，標「追價上修」，不當成新的看多訊號；近 3 天 3 家以上同方向改目標價要寫在結論。
O. 循環股（記憶體、面板、航運、鋼鐵、塑化等）說明現在是景氣高峰還是谷底，低本益比要提醒「可能是獲利高峰」，改用股價淨值比或全周期平均 EPS。
P. 「看錯條件」要用網站能自動對答案的數字（月營收年增率、收盤價位、毛利率）；資料不足就說不足，不自己推測數字；不複製券商原文。
Q. 目標價要跟現價對得上：合理價比現價高 50% 以上、或高於近三年最高價、或預估本益比是目前本益比的 1.4 倍以上時，要在「目標價與評價」說清楚為什麼市場會給這個倍數（例如獲利翻倍、產業重新評價），說不出理由就把倍數降到近三年本益比中位數附近；json 的「支撐」「壓力」填波段價位（數據摘要的月線、季線、共振區、箱頂箱底），不要只填離現價 1% 內的當日價位。

資料紀律：
- 使用者提供的股價、基本面、籌碼、技術面、支撐壓力數據是正確的，以它為準；價位名稱（月線、季線、共振區等）只用數據摘要裡的。
- 用網路搜尋近六個月的新聞、月營收與財報、法說會、券商或投顧報告與目標價（多半只能看到新聞摘要）、產業動態。
  優先採用鉅亨網、經濟日報、工商時報、MoneyDJ、公開資訊觀測站，並注意日期，舊聞不要當新聞。
- 新聞標題標「舊聞」或「舊聞重提」的，要寫出第一次公告的日期，並判斷是否已反映在股價；不要把舊事重提當成新的利多或利空。
- 沒有來源支持的數字不要寫；傳聞要標「傳聞／待證實」；關聯不要寫成因果。
- 券商報告幾乎都是買進評等，目標價也常在大漲後才上修：引用時要說明是哪家、哪天，並提醒分歧（最高與最低目標價）。

輸出 Markdown，依序包含以下段落（用 ### 標題）：
   ### 一句話結論（看法＋目標價＋怎麼算的＋現在貴不貴）
   ### 本次 vs 前次（K；第一次就寫「首次」）
   ### 公司介紹（做什麼、主要產品與營收比重、主要客戶與下游應用、產業地位／是否龍頭、主要競爭對手；
       營收比重與主要業務以使用者提供的「公司資料」為準，客戶查不到就寫未找到）
   ### 近半年重要消息（由新到舊條列，每條註明月份）
   ### 上一季對答案與成長來源（C、D）
   ### 法人與券商觀點（M、N：區間、中位數、上修下修家數、最樂觀與最悲觀；找不到就說找不到，不要編造）
   ### 一次性檢查與景氣位置（J、O）
   ### 目標價與評價
       表格列出：評價方法（P/E 或 P/B）、今年與明年預估 EPS（或每股淨值；優先用券商或法說會預估，沒有就自行估算並註明「自行估算」）、
       以目前股價換算的倍數與歷史位階、保守／合理／樂觀三檔目標價（倍數 × EPS），並說明假設。
   ### 利多因素
   ### 利空與風險（含要追蹤的指標，例如需求、庫存、擴產時點）
   ### 數據面解讀（基本面、籌碼、技術面各一段；技術面用網站的格局、支撐壓力、量價）
   ### 投資建議與劇本
       短線（1 個月內）與中期（3–6 個月）各一段，給偏多／中性／偏空，並寫：
       - 偏多劇本：站上哪個價位、看到什麼條件
       - 偏空劇本：跌破哪個價位、要怎麼做
       - 看錯的條件與停損價（H）
報告最後寫：「以上為 AI 彙整的公開資訊，僅供參考，不構成投資建議。」
最後面另外附上一個 ```json 程式碼區塊，整理成網站卡片用的資料（數字填純數字，不知道填 null）：
   {"看法": "偏多/中性/偏空", "一句話": "30 字內結論", "短線": "偏多/中性/偏空", "中期": "偏多/中性/偏空",
    "評價方法": "例如 25 倍 × 2027 EPS 32.5", "券商目標價": 數字, "目標價保守": 數字, "目標價合理": 數字, "目標價樂觀": 數字,
    "今年EPS": 數字, "明年EPS": 數字, "預估本益比": 數字, "支撐": 數字, "壓力": 數字, "停損": 數字,
    "看錯條件": "20 字內，例如 收盤跌破季線 480"}"""


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
    """把報告裡的 json 區塊拆出來做卡片；回傳 (給人看的內文, 建議 dict 或 None)。舊報告沒有 json 就只抓一句話結論。
    支援 ```json、``` 沒標語言、以及手動貼上時只貼了一段裸 json（整份或在最後）的情況，內文就不會印出原始 json。"""
    import json, re
    建議 = None
    文字 = 文字 if isinstance(文字, str) else ""

    def 讀(片段):
        try:
            值 = json.loads(片段)
        except Exception:
            return None
        return 值 if isinstance(值, dict) else None

    for 樣式 in (r"```\s*json\s*(\{.*?\})\s*```", r"```\s*(\{.*?\})\s*```"):
        配 = re.search(樣式, 文字, re.S | re.I)
        if 配:
            建議 = 讀(配.group(1))
            文字 = (文字[: 配.start()] + 文字[配.end():]).strip()
            break
    if 建議 is None:
        # 裸 json：整份就是 json，或報告最後接一段 { ... }（沒有包 ```）
        乾 = 文字.strip()
        if 乾.startswith("{") and 讀(乾) is not None:
            建議, 文字 = 讀(乾), ""
        else:
            配 = re.search(r"(?:^|\n)\s*(\{[^{}]*\"看法\"[^{}]*\})\s*$", 文字, re.S)
            if 配 and 讀(配.group(1)) is not None:
                建議 = 讀(配.group(1))
                文字 = 文字[: 配.start()].strip()
    if 建議 is None and 文字:
        結 = re.search(r"###\s*一句話結論\s*\n+(.+?)(?:\n\s*\n|\n#|$)", 文字, re.S)
        if 結:
            一句 = 結.group(1).strip()
            看法 = next((k for k in ("偏多", "偏空", "中性") if k in 一句), None)
            建議 = {"一句話": 一句, "看法": 看法}
    return 文字, 建議


def 檢查AI目標價(建議, 收盤, 本益比=None, 三年高=None, 三年低=None, 共識=None):
    """AI 給的目標價、支撐壓力有沒有自相矛盾或離現價太遠。不改 AI 的數字，只回傳提醒清單（繁體中文）。
    收盤：現價；本益比：目前本益比；三年高／三年低：近三年收盤最高／最低（可省略）。
    共識：預估EPS表() 的一列（dict，有 預估EPS今年、預估EPS明年、預估年度），用來比 AI 的 EPS 和隱含本益比。"""
    import re
    def 數(k):
        v = (建議 or {}).get(k)
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if v == v else None
    提醒 = []
    try:
        收盤 = float(收盤)
    except (TypeError, ValueError):
        return 提醒
    if not 收盤 or 收盤 != 收盤:
        return 提醒
    保守, 合理, 樂觀 = 數("目標價保守"), 數("目標價合理"), 數("目標價樂觀")
    支撐, 壓力, 停損 = 數("支撐"), 數("壓力"), 數("停損")
    倍數 = 數("預估本益比")
    # 1. 評價方法寫的「N 倍 × EPS X」要等於合理價
    方法 = str((建議 or {}).get("評價方法") or "")
    配 = re.search(r"([\d.]+)\s*倍.*?([\d]+\.\d+|\d+)\s*(?:元)?\s*$", 方法)
    if 配 and 合理:
        try:
            算 = float(配.group(1)) * float(配.group(2))
            if 算 > 0 and abs(算 / 合理 - 1) > 0.05:
                提醒.append(f"評價方法「{方法}」算出 {算:,.1f}，與合理價 {合理:,.1f} 不一致")
        except ValueError:
            pass
    if 保守 and 合理 and 樂觀 and not (保守 <= 合理 <= 樂觀):
        提醒.append("保守／合理／樂觀三檔目標價順序不對")
    # 2. 合理價離現價太遠
    if 合理:
        空間 = (合理 / 收盤 - 1) * 100
        if 空間 >= 50:
            提醒.append(f"合理價 {合理:,.1f} 比現價 {收盤:,.2f} 高 {空間:.0f}%，假設偏樂觀，請看清楚依據再參考")
        elif 空間 <= -40:
            提醒.append(f"合理價 {合理:,.1f} 比現價低 {-空間:.0f}%，與現價落差很大")
    if 保守 and 保守 / 收盤 - 1 >= 0.3:
        提醒.append(f"連保守價 {保守:,.1f} 都比現價高 {(保守 / 收盤 - 1) * 100:.0f}%")
    # 3. 漲幅主要來自本益比拉高（不是獲利成長）
    try:
        本益比 = float(本益比) if 本益比 is not None else None
    except (TypeError, ValueError):
        本益比 = None
    if 倍數 and 本益比 and 本益比 > 0 and 倍數 / 本益比 >= 1.4:
        提醒.append(f"預估本益比 {倍數:.1f} 倍遠高於目前 {本益比:.1f} 倍，大部分上漲空間來自「倍數拉高」而不是獲利成長")
    if 合理 and 三年高 and 合理 > float(三年高) * 1.1:
        提醒.append(f"合理價高於近三年最高收盤 {float(三年高):,.2f}")
    提醒 += _對照共識EPS(建議, 合理, 共識)
    # 4. 支撐壓力停損
    if 支撐 and 壓力 and 支撐 > 壓力:
        提醒.append(f"支撐 {支撐:,.2f} 高於壓力 {壓力:,.2f}，數字可能填反")
    if 停損 and 停損 >= 收盤:
        提醒.append(f"停損 {停損:,.2f} 不低於現價，請確認")
    if 支撐 and 壓力 and 合理 and (壓力 - 支撐) / 收盤 < 0.05 and (合理 / 收盤 - 1) >= 0.3:
        提醒.append("支撐／壓力只是短線幾天的區間，跟中長期目標價不是同一個時間尺度，不能直接當成「會漲到目標價」")
    return 提醒



def _對照共識EPS(建議, 合理, 共識, 門檻=20):
    """AI 的今年／明年 EPS 跟全市場預估共識（A、B 中位數）差超過 門檻% 就提醒；合理價換算成共識明年 EPS 的本益比也列出。"""
    if not 共識:
        return []
    def 數(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if v == v else None
    提醒 = []
    年 = 共識.get("預估年度")
    年 = int(年) if 數(年) else None
    for 鍵, 共鍵, 名 in (("今年EPS", "預估EPS今年", f"{年} 年" if 年 else "今年"), ("明年EPS", "預估EPS明年", f"{年 + 1} 年" if 年 else "明年")):
        ai, 共 = 數((建議 or {}).get(鍵)), 數(共識.get(共鍵))
        if ai is None or 共 is None or abs(共) < 0.3:
            continue
        差 = (ai / 共 - 1) * 100
        if abs(差) > 門檻:
            提醒.append(f"AI 的{名} EPS {ai:,.2f} 比市場預估共識 {共:,.2f} {'高' if 差 > 0 else '低'} {abs(差):.0f}%，"
                       f"{'偏樂觀' if 差 > 0 else '偏保守'}，請看 AI 的理由")
    明 = 數(共識.get("預估EPS明年")) or 數(共識.get("預估EPS今年"))
    if 合理 and 明 and 明 > 0:
        倍 = 合理 / 明
        if 倍 >= 40:
            提醒.append(f"合理價 {合理:,.1f} 換算成市場預估 EPS {明:,.2f} 是 {倍:.0f} 倍本益比，偏高")
    return 提醒

def AI補卡片(報告, 引擎, 金鑰, 模型):
    """舊報告沒有卡片資料：請 AI 只從報告內容整理出卡片用的 json（不上網，很快）。"""
    import json, re
    提示 = ("以下是一份台股 AI 分析報告。請只根據報告內容，輸出一個 ```json 程式碼區塊，欄位如下"
           "（數字填純數字，報告沒提到填 null，不要編造）：\n"
           '{"看法": "偏多/中性/偏空", "一句話": "30 字內結論", "短線": "偏多/中性/偏空", "中期": "偏多/中性/偏空", '
           '"券商目標價": 數字, "目標價保守": 數字, "目標價合理": 數字, "目標價樂觀": 數字, '
           '"今年EPS": 數字, "明年EPS": 數字, "預估本益比": 數字, "支撐": 數字, "壓力": 數字, "停損": 數字, '
           '"評價方法": "文字", "看錯條件": "文字"}\n\n報告：\n' + 報告)
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
Gemini本次呼叫 = {"成功": 0, "失敗": 0}   # 這個程序裡呼叫 Gemini 的次數，排程結束時寫進 ai_usage.json


def Gemini呼叫(內容, api_key, 模型="gemini-flash-latest", 每個試幾次=2, 逾時=180, 換模型=True, 等429秒=0):
    """呼叫 Gemini；遇到「忙線」(500/503/504) 或逾時會稍等重試，還是不行就換備用模型。回傳 (回應, 實際模型)。"""
    import time
    import requests

    最後錯誤 = None
    for m in dict.fromkeys([模型] + (Gemini備用模型 if 換模型 else [])):
        網址 = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
        for 次 in range(每個試幾次):
            try:
                回應 = requests.post(網址, headers={"x-goog-api-key": api_key}, json=內容, timeout=逾時)
            except requests.RequestException as 錯:
                最後錯誤 = f"連線逾時或中斷（{type(錯).__name__}）"
                time.sleep(3)
                continue
            if 回應.status_code == 200:
                Gemini本次呼叫["成功"] += 1
                return 回應, m
            Gemini本次呼叫["失敗"] += 1
            try:
                訊息 = 回應.json()["error"]["message"]
            except Exception:
                訊息 = 回應.text[:200]
            if 回應.status_code == 429:
                最後錯誤 = "Gemini 額度或每分鐘字數上限用完了（免費額度對長影片很容易超過，可到 Google AI Studio 開啟付費）。"
                if 等429秒 and 次 + 1 < 每個試幾次:
                    time.sleep(等429秒)   # 可能只是「每分鐘」上限，等一下再試
                    continue
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


會診角色 = {"技術面": "只看 K 線、均線、支撐壓力、量價", "籌碼面": "只看三大法人、融資券、大戶與主動式 ETF",
          "基本面": "只看營收、毛利率、EPS、評價", "唱反調": "專門找這檔的空方理由與最可能看錯的地方"}


def AI用量紀錄(設定, 流程, 保留天數=60):
    """把這個程序呼叫 Gemini 的次數累加進 ai-reports 的 ai_usage.json（{日期: {流程: {成功, 失敗}}}）。"""
    n = dict(Gemini本次呼叫)
    if not (n["成功"] or n["失敗"]):
        return
    日 = pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m-%d")
    表 = 讀取設定檔(設定, "ai_usage.json") or {}
    格 = 表.setdefault(日, {}).setdefault(流程, {"成功": 0, "失敗": 0})
    格["成功"] += n["成功"]
    格["失敗"] += n["失敗"]
    截止 = (pd.Timestamp.now(tz="Asia/Taipei") - pd.Timedelta(days=保留天數)).strftime("%Y-%m-%d")
    儲存設定檔(設定, "ai_usage.json", {k: v for k, v in sorted(表.items()) if k >= 截止}, f"AI 用量 {日} {流程}")
    Gemini本次呼叫.update({"成功": 0, "失敗": 0})


def AI今日呼叫數(設定, 流程=None):
    日 = pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m-%d")
    今 = (讀取設定檔(設定, "ai_usage.json") or {}).get(日, {})
    return sum(v["成功"] + v["失敗"] for k, v in 今.items() if 流程 in (None, k))


def AI用量小卡(設定, 天數=7):
    """近 N 天各流程 Gemini 呼叫次數的 LINE 文字（失敗次數另列）。"""
    表 = 讀取設定檔(設定, "ai_usage.json") or {}
    起 = (pd.Timestamp.now(tz="Asia/Taipei") - pd.Timedelta(days=天數)).strftime("%Y-%m-%d")
    合 = {}
    for 日, 流們 in 表.items():
        if 日 >= 起:
            for 流, v in 流們.items():
                格 = 合.setdefault(流, [0, 0])
                格[0] += v["成功"]
                格[1] += v["失敗"]
    if not 合:
        return f"📊 近 {天數} 天沒有 Gemini 呼叫紀錄。"
    行們 = [f"　{k}：{a} 次" + (f"（失敗 {b}）" if b else "") for k, (a, b) in sorted(合.items(), key=lambda x: -x[1][0])]
    總 = sum(a for a, _ in 合.values())
    return f"📊 近 {天數} 天 Gemini 呼叫 {總} 次\n" + "\n".join(行們) + "\n（免費額度內不用錢；超過才依 Google 計價）"


def 初步查核網紅(影片, 名表):
    """程式化初步查核（不用 AI）：代號存在嗎？名稱和代號對得上嗎？回傳紅旗文字清單，空＝沒發現問題。
    名表＝{代號: 名稱}。有紅旗的才需要人（或 Claude）再看。"""
    旗 = []
    for x in 影片.get("股票", []):
        代, 名 = str(x.get("代號") or ""), str(x.get("名稱") or "")
        if 代 and 代 in 名表 and 名 and 名 not in 名表[代] and 名表[代] not in 名:
            旗.append(f"{代} 影片寫「{名}」，資料庫是「{名表[代]}」")
        elif 代 and 名表 and 代 not in 名表 and not 代.isalpha():
            旗.append(f"{代}{名} 在資料庫找不到")
    return 旗


def AI多角色會診(代號, 名稱, 數據摘要, api_key, 模型="gemini-flash-latest"):
    """Gemini 一次扮 4 位分析師各寫 3 句，再給總結與分歧點（只用網站數據，不上網，省用量）。"""
    角色 = "\n".join(f"### {k}（{v}）" for k, v in 會診角色.items())
    提示 = (f"以下是台股 {代號} {名稱} 的網站數據（以此為準，不要自己編數字）：\n{數據摘要}\n\n"
          f"請用繁體中文，分別扮演 4 位分析師，每位只用自己負責的數據寫 3 句（每句帶一個數字），依序用這些標題：\n{角色}\n"
          "### 總結（2 句：多數人怎麼看、整體偏多／中性／偏空）\n### 分歧點（大家意見不同的地方，以及要看哪個數字來判斷誰對）\n"
          "最後一行寫「以上為 AI 依網站數據的多角度整理，不構成投資建議。」")
    回應, _ = Gemini呼叫({"contents": [{"role": "user", "parts": [{"text": 提示}]}],
                        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 3000}}, api_key, 模型)
    j = 回應.json()
    return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])


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
    # 族群預估本益比＝有正的預估 EPS 那些股票的合計市值 ÷ 合計預估獲利（大型股影響較大，虧損股不算）
    for 欄, 新 in (("預估EPS今年", "預估本益比"), ("預估EPS明年", "明年預估本益比")):
        if 欄 in 表.columns:
            e = pd.to_numeric(表[欄], errors="coerce")
            有 = e > 0
            獲利 = (e * 表["發行股數"]).where(有).groupby(表["產業"]).sum(min_count=1)
            市值 = (表["收盤"] * 表["發行股數"]).where(有).groupby(表["產業"]).sum(min_count=1)
            族群[新] = (市值 / 獲利).round(1)
            if 新 == "預估本益比":
                族群["預估涵蓋"] = 有.groupby(表["產業"]).sum().astype(int)
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


def 預估河流位置(h, 收盤, 預估們):
    """本益比河流（h＝本益比河流() 的表）＋預估 EPS：用預估 EPS 換算的本益比落在過去 5 年本益比的哪裡，
    以及「預估 EPS × 過去本益比低標／中位數／高標」的價格。預估們＝{"2026": EPS, "2027": EPS}（≤ 0 或缺值略過）。
    回傳 list of dict（年度、EPS、預估本益比、歷史百分位、低標價、中位價、高標價）。"""
    倍 = h["本益比"]
    低, 中, 高 = 倍.quantile([0.1, 0.5, 0.9])
    結果 = []
    for 年, e in 預估們.items():
        try:
            e = float(e)
        except (TypeError, ValueError):
            continue
        if not e > 0:
            continue
        pe = float(收盤) / e
        結果.append({"年度": 年, "EPS": e, "預估本益比": round(pe, 1), "歷史百分位": round((倍 < pe).mean() * 100),
                   "低標價": round(e * 低, 1), "中位價": round(e * 中, 1), "高標價": round(e * 高, 1),
                   "低標倍": round(低, 1), "中位倍": round(中, 1), "高標倍": round(高, 1)})
    return 結果


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
    # 2026-11 加：合約負債（預收款）年增，全市場驗證財報後 60 日高組贏低組 6.3%（t≈2.4），只看預收款夠大的公司
    ("基本", 10, lambda d: (_有(d, "合約負債年增") >= 30) & (_有(d, "合約負債營收比") >= 5),
     lambda r: f"合約負債（預收款）年增 {r['合約負債年增']:.0f}%"),
    ("基本", -5, lambda d: (_有(d, "合約負債年增") <= -20) & (_有(d, "合約負債營收比") >= 5),
     lambda r: f"合約負債（預收款）年減 {abs(r['合約負債年增']):.0f}%"),
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
# 網站「評分依據」表用的白話說明（改上面的規則時，這裡也要一起改）
評分規則說明 = [
    ("技術", "+10／−10", "收盤（還原股價）站上／跌破 20 日線"),
    ("技術", "+10／−10", "站上／跌破 60 日線（季線）"),
    ("技術", "+10／−10", "均線多頭排列（5 日 > 20 日 > 60 日）／空頭排列"),
    ("技術", "+5", "近 20 日漲 10% 以上"),
    ("技術", "+5", "離 52 週高點不到 5%"),
    ("技術", "+10", "近 5 日急跌 10% 以上（短線超跌，歷史上之後常反彈）"),
    ("技術", "−5", "價跌量增：今天下跌、成交量是 20 日均量 2 倍以上"),
    ("籌碼", "+15／+7", "三大法人 5 日買超 ≥ 5 日均量的 50%／15～50%"),
    ("籌碼", "−7／−15", "三大法人 5 日賣超 15～50%／≥ 50%（跟成交量比，大小型股才比得起來）"),
    ("籌碼", "+10", "外資連買 3 天以上"),
    ("籌碼", "+10", "投信連買 3 天以上"),
    ("籌碼", "+5／−5", "外資今天買超／賣超"),
    ("籌碼", "−10", "近 20 日股價跌、融資 5 日卻增加 10% 以上（散戶接刀）"),
    ("籌碼", "+5", "近 5 日股價漲、融資減少 5% 以上（籌碼安定）"),
    ("基本", "+15／+5／−15", "月營收年增 ≥ 20%／0～20%／≤ −10%"),
    ("基本", "+5／−5", "今年累計營收年增 ≥ 10%／≤ −10%"),
    ("基本", "+10", "月營收創歷史新高（要有 13 個月以上資料）"),
    ("基本", "+5／−20", "近三季 EPS 合計為正／虧損"),
    ("基本", "+5／−5", "單季毛利率比去年同季增加／減少 1 個百分點以上"),
    ("基本", "+10／−5", "合約負債（預收款）年增 ≥ 30%／≤ −20%（只算合約負債至少是近四季營收 5% 的公司）"),
    ("基本", "+5／−5", "本益比 15 倍以下／40 倍以上"),
    ("基本", "+5", "殖利率 5% 以上"),
    ("市場", "+10／−10", "大盤分數 ≥ 60／≤ 40（指數均線、漲跌家數、外資買賣超）"),
    ("市場", "+5／−5", "所屬產業近 20 日漲幅排在前 25%／後 25%"),
    ("市場", "+15／−15", "近 20 日贏大盤／輸大盤 5% 以上"),
    ("市場", "+5／−5", "近 5 日贏大盤／輸大盤 3% 以上"),
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
    結果["總分"] = ((結果.fillna(0) * 權重).sum(axis=1) / 權重.sum(axis=1)).round(1)
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
    起價, 註 = 歷史["收盤"].iloc[0], ""
    if "代號" in 歷史.columns:
        倍 = 分割倍數(歷史["代號"].iloc[-1], 歷史["date"].iloc[0])
        if 倍 != 1:  # 期間有面額分割，起點價格換成分割後的基準才看得懂
            起價, 註 = 起價 / 倍, "，起點已換算面額分割"
    說明.append(f"**股價**：這段期間 {'上漲' if 漲 >= 0 else '下跌'} {abs(漲):.1f}%"
              f"（{起價:,.2f} → {歷史['收盤'].iloc[-1]:,.2f}{註}）。")
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
def 評分回測(持有天數=20, 最少量=500, 含合約負債=True):
    """每月最後一個交易日用「當時看得到的資料」打分數，比較之後 N 個交易日的報酬。
    營收用當時已公布的月份（假設次月 10 日前公布）；EPS、毛利率用當時已過公布期限的季報
    （Q1 5/15、Q2 8/14、Q3 11/14、Q4 隔年 3/31），損益表歷史約 5 年。
    很吃記憶體，在 GitHub Actions 算好存成 data/score_backtest.json，網站只讀結果。"""
    指 = 計算指標(讀取資料庫())
    加 = 讀取加權指數()
    股 = _股本表()
    營收 = pd.read_csv(資料夾 / "fundamental" / "revenue_history.csv", dtype={"code": str})
    營收["m"] = pd.PeriodIndex(營收["month"], freq="M")
    營收 = 營收.set_index(["code", "m"])["revenue"]
    有的月 = set(營收.index.get_level_values("m"))
    單季 = 單季損益()
    損益檔 = 資料夾 / "fundamental" / "income.csv"
    累計EPS = pd.read_csv(損益檔, dtype={"code": str}) if 損益檔.exists() else pd.DataFrame(columns=["code", "quarter", "eps"])
    累計EPS = 累計EPS.dropna(subset=["eps"])[["code", "quarter", "eps"]] if "eps" in 累計EPS else 累計EPS.iloc[0:0]

    def 公布期限(季度):
        年, 季 = int(季度[:4]), int(季度[-1])
        return pd.Timestamp(f"{年 + 1}-03-31") if 季 == 4 else pd.Timestamp(f"{年}-{(5, 8, 11)[季 - 1]:02d}-{(15, 14, 14)[季 - 1]}")
    季期限 = {q: 公布期限(q) for q in set(累計EPS["quarter"]) | set(單季.get("quarter", []))}
    合約 = 讀取合約負債() if 含合約負債 else None

    def 當時財報(日):
        可 = {q for q, d in 季期限.items() if d <= 日}
        if not 可:
            return None
        e = 累計EPS[累計EPS["quarter"].isin(可)].sort_values(["code", "quarter"])
        最新 = e.drop_duplicates("code", keep="last").set_index("code").rename(columns={"quarter": "EPS季度", "eps": "EPS"})
        最新["近三季EPS"] = _近三季EPS(e).reindex(最新.index).fillna(最新["EPS"]) if len(e) else np.nan
        if len(單季):
            最新 = 最新.join(毛利率表(單季[單季["quarter"].isin(可)]), how="outer")
        if 合約 is not None:
            c = 合約[合約["quarter"].map(lambda q: 公布期限(q) <= 日)].dropna(subset=["合約負債"])
            if len(c):
                最新 = 最新.join(c.groupby("code").tail(1).set_index("code")[["合約負債年增", "合約負債營收比"]], how="outer")
        return 最新
    日們 = pd.DatetimeIndex(sorted(指["date"].unique()))
    期 = 日們.to_period("M")
    月底 = 日們[np.r_[期[1:] != 期[:-1], True]]
    還原 = 指.pivot_table(index="date", columns="代號", values="還原價")
    未來 = (還原.shift(-持有天數) / 還原 - 1) * 100
    長 = {n: (還原.shift(-n) / 還原 - 1) * 100 for n in (60, 120)}  # 網站「高分股回測」看比較久的報酬
    結果 = []
    for 日 in 月底[12:]:  # 前 12 個月要拿來算均線、52 週高點
        if pd.isna(未來.loc[日]).all():
            continue
        當 = 指[指["date"] == 日].join(股, on="代號")
        月 = (日 - pd.Timedelta(days=10)).to_period("M") - 1
        if 月 in 有的月 and 月 - 12 in 有的月:
            當["營收年增率"] = 當["代號"].map((營收.xs(月, level="m") / 營收.xs(月 - 12, level="m") - 1) * 100)
        財 = 當時財報(日)
        if 財 is not None and len(財):
            當 = 當.drop(columns=[c for c in 財.columns if c in 當.columns]).join(財, on="代號")
        分, _ = 每日評分(當, 加[加["date"] <= 日])
        分["報酬"] = 未來.loc[日].reindex(分.index)
        for n, t in 長.items():
            分[f"報酬{n}"] = t.loc[日].reindex(分.index)
        分 = 分[(分["5日均量"] >= 最少量) & ~分.index.str.startswith("00")].dropna(subset=["報酬", "總分"])
        分["date"] = 日
        結果.append(分[["date", "總分", "看法", "技術", "籌碼", "基本", "市場", "報酬", "報酬60", "報酬120"]])
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
    明細檔 = 資料夾 / "score_backtest_detail.csv.gz"
    if 檔.exists() and 明細檔.exists() and not 強制:
        舊 = json.loads(檔.read_text())
        if 舊.get("權重") == 評分權重 and 舊.get("版本") == 2 and (pd.Timestamp.now() - pd.Timestamp(舊.get("計算日", "2000-01-01"))).days < 間隔天數:
            print("評分回測：還不用重算")
            return
    表 = 評分回測()
    if 表 is None:
        return
    摘要 = 評分回測摘要(表)
    摘要["計算日"] = f"{pd.Timestamp.now():%Y-%m-%d}"
    摘要["版本"] = 2  # 2：基本面加入當時已公布的 EPS、毛利率
    # 每期每檔的四個面向分數與之後報酬，網站「自訂權重」用來即時重算驗證
    欄 = ["技術", "籌碼", "基本", "市場", "報酬", "報酬60", "報酬120"]
    明細 = 表[["date"] + 欄].rename_axis("代號").reset_index()
    明細[欄] = 明細[欄].round(2)
    明細.to_csv(明細檔, index=False, compression="gzip")
    檔.write_text(json.dumps(摘要, ensure_ascii=False, indent=1))
    print("評分回測：已更新", 摘要["相關"]["總分"])


def 高分股回測(明細, 權重, 門檻=85, 前幾名=None):
    """歷史每月底分數夠高（總分 ≥ 門檻，或每月前幾名）的股票，之後 20／60／120 個交易日的報酬，
    跟同一天全部股票的平均比。回傳 (選到的表, 每月統計)。"""
    t = 明細.assign(總分=加權總分(明細, 權重))
    報欄 = [c for c in ("報酬", "報酬60", "報酬120") if c in t.columns]
    平均 = t.groupby("date")[報欄].mean().add_prefix("全體")
    if 前幾名:
        選 = t[t.groupby("date")["總分"].rank(ascending=False, method="first") <= 前幾名]
    else:
        選 = t[t["總分"] >= 門檻]
    選 = 選.join(平均, on="date")
    for c in 報欄:
        選[f"超額{c[2:] or '20'}"] = 選[c] - 選[f"全體{c}"]
    每月 = 選.groupby("date").agg(檔數=("代號", "size"), 平均報酬=("報酬", "mean")).join(平均["全體報酬"])
    return 選.sort_values(["date", "總分"], ascending=[False, False]), 每月


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

# ---------- 網紅摘要 11/07 建議 W1～W4：止跌訊號（指數 vs 融資、全市場借券、賣壓消散、破低不破） ----------
def 讀取全部借券(天數=120):
    """全市場每天每檔的借券賣出餘額（張）：date、code、sbl_sell、sbl_return、sbl_balance。"""
    表們 = []
    for f in sorted((資料夾 / "sbl").glob("*.csv.gz"))[-天數:]:
        t = pd.read_csv(f, dtype={"code": str}, usecols=["code", "sbl_sell", "sbl_return", "sbl_balance"])
        表們.append(t.assign(date=pd.Timestamp(f.name[:8])))
    return pd.concat(表們, ignore_index=True) if 表們 else None


def 指數融資對照(K, 融資, 起日=None, 窗=60):
    """W1（雪寶學院）：把加權收盤和上市融資金額都從同一天＝100 畫在一起，看融資有沒有跟上指數跌幅。
    K：加權日 K（date、close）；融資：讀取融資金額()（index＝date，單位千元）。起日沒給就用近 窗 日收盤最高那天。
    回傳 dict(表＝DataFrame(index＝date；指數、融資 兩欄都是 100 基期), 起日, 指數跌幅%, 融資減幅%, 同步還要減億)；資料不夠回 None。"""
    if K is None or 融資 is None or not len(K) or not len(融資):
        return None
    c = K.set_index("date")["close"].astype(float)
    m = 融資.astype(float)
    共 = c.index.intersection(m.index)
    if len(共) < 5:
        return None
    c, m = c.loc[共], m.loc[共]
    if 起日 is None:
        近 = c.tail(窗)
        起日 = 近.idxmax()
    起日 = pd.Timestamp(起日)
    c, m = c[c.index >= 起日], m[m.index >= 起日]
    if len(c) < 2:
        return None
    表 = pd.DataFrame({"指數": c / c.iloc[0] * 100, "融資": m / m.iloc[0] * 100}).round(2)
    跌, 減 = 表["指數"].iloc[-1] - 100, 表["融資"].iloc[-1] - 100
    # 融資要減到跟指數同比例：起點金額 ×（1＋指數跌幅），和現在差多少（千元 → 億）
    還要 = (m.iloc[-1] - m.iloc[0] * (1 + 跌 / 100)) / 1e5 if 跌 < 減 else 0.0
    return {"表": 表, "起日": 表.index[0], "指數跌幅%": round(float(跌), 2), "融資減幅%": round(float(減), 2),
            "同步還要減億": round(float(還要))}


def 大盤借券趨勢(借, 價):
    """W3（關我什麼事）：全市場借券賣出餘額走勢與「由增轉減」燈號。
    借：讀取全部借券()；價：date、code、close（用來把張數換成金額）。
    每天的變化用「餘額張數變化 × 當天收盤」÷ 前一天餘額市值，跟大盤融資變化同一種算法，不受股價漲跌影響。
    回傳 DataFrame(index＝date；餘額億、借券賣出張、還券張、變化%、指數＝前一天累積 100 基期)。"""
    if 借 is None or 價 is None or not len(借):
        return pd.DataFrame()
    t = 借.merge(價[["date", "code", "close"]], on=["date", "code"], how="inner")
    t = t[t["close"] > 0].sort_values(["code", "date"])
    t["前餘額"] = t.groupby("code")["sbl_balance"].shift()
    t["市值"] = t["sbl_balance"] * t["close"] * 1000
    t["前市值"] = t["前餘額"] * t["close"] * 1000
    t["變化值"] = (t["sbl_balance"] - t["前餘額"]) * t["close"] * 1000
    群 = t.groupby("date")
    表 = pd.DataFrame({"餘額億": 群["市值"].sum() / 1e8, "借券賣出張": 群["sbl_sell"].sum(), "還券張": 群["sbl_return"].sum(),
                       "變化%": 群["變化值"].sum() / 群["前市值"].sum() * 100})
    表 = 表.iloc[1:] if len(表) > 1 else 表   # 第一天沒有前一天可比
    表["指數"] = (1 + 表["變化%"].fillna(0) / 100).cumprod() * 100
    return 表.round(2)


def 借券轉向燈(表, 短=3, 長=10):
    """近 短 天餘額指數都在減少、而且再往前 長 天是增加的 → 🟢 由增轉減；還在增加 → 🔴；其他 🟡。回傳 (燈, 說)。"""
    if 表 is None or len(表) < 短 + 長:
        return "🟡", "資料還不夠"
    s = 表["指數"]
    近 = s.diff().tail(短)
    前段 = s.iloc[-短 - 1] / s.iloc[-短 - 1 - 長] - 1
    五日 = (s.iloc[-1] / s.iloc[-6] - 1) * 100 if len(s) > 5 else np.nan
    if (近 < 0).all() and 前段 > 0:
        return "🟢", f"連 {短} 天減少、之前 {長} 天是增加的：由增轉減（近 5 日 {五日:+.1f}%）"
    if (近 < 0).all():
        return "🟡", f"連 {短} 天減少，但之前就在減，不算轉向（近 5 日 {五日:+.1f}%）"
    if 五日 > 0:
        return "🔴", f"空方還在加碼：近 5 日餘額 {五日:+.1f}%"
    return "🟡", f"增減互見（近 5 日 {五日:+.1f}%）"


def 賣壓消散燈號(匯率, 期貨, K, 天數=2, 影線門檻=0.6):
    """W4（宏爺）：① 台幣連 天數 天沒有再貶（USD/TWD 沒有比前一天高）② 外資台指期淨空單連 天數 天減少
    ③ 加權連 天數 天收下影線（下影線 ≥ 收盤 影線門檻%，而且比實體長）。
    匯率：讀取匯率()（date、usdtwd）；期貨：讀取期貨未平倉()（index＝date、foreign_oi）；K：加權日 K。
    回傳 dict(燈們=[(名, 燈, 說)], 亮幾個)；資料不夠的項目給 🟡。"""
    燈們 = []
    if 匯率 is not None and len(匯率) > 天數:
        s = 匯率.set_index("date")["usdtwd"].astype(float).dropna()
        差 = s.diff().tail(天數)
        亮 = bool((差 <= 0).all())
        燈們.append(("① 台幣不再貶", "🟢" if 亮 else "🔴",
                     f"USD/TWD {s.iloc[-1]:.3f}，近 {天數} 天" + ("都沒有比前一天高" if 亮 else f"還有貶值（{'、'.join(f'{v:+.3f}' for v in 差)}）")))
    else:
        燈們.append(("① 台幣不再貶", "🟡", "沒有匯率資料"))
    if 期貨 is not None and "foreign_oi" in 期貨 and len(期貨) > 天數:
        s = 期貨["foreign_oi"].astype(float).dropna()
        差 = s.diff().tail(天數)
        亮 = bool((差 > 0).all()) and s.iloc[-1] < 0
        燈們.append(("② 外資期貨空單減少", "🟢" if 亮 else "🔴",
                     f"淨未平倉 {s.iloc[-1]:+,.0f} 口，近 {天數} 天變化 " + "、".join(f"{v:+,.0f}" for v in 差)
                     + ("：空單在回補" if 亮 else "：還沒連續回補")))
    else:
        燈們.append(("② 外資期貨空單減少", "🟡", "沒有期貨資料"))
    if K is not None and len(K) > 天數 and {"open", "low", "close"} <= set(K.columns):
        k = K.tail(天數).astype({"open": float, "low": float, "close": float})
        下影 = (k[["open", "close"]].min(axis=1) - k["low"])
        實體 = (k["close"] - k["open"]).abs()
        條 = (下影 >= k["close"] * 影線門檻 / 100) & (下影 > 實體)
        亮 = bool(條.all())
        燈們.append(("③ 大盤連續下影線", "🟢" if 亮 else "🔴",
                     "近 {} 天下影線 {}".format(天數, "、".join(f"{v:,.0f} 點" for v in 下影))
                     + ("：低檔有買盤承接" if 亮 else f"：要連 {天數} 天下影線 ≥ {影線門檻:g}% 且比實體長")))
    else:
        燈們.append(("③ 大盤連續下影線", "🟡", "沒有開高低資料"))
    return {"燈們": 燈們, "亮幾個": sum(1 for _, 燈, _ in 燈們 if 燈 == "🟢")}


def 賣壓消散回測(匯率, 期貨, K, 天數=2, 影線門檻=0.6, 後=(5, 20), 間隔=10):
    """過去三個燈同時亮（只看有期貨資料的期間）之後加權 N 日漲跌，對照任何一天。回傳 dict(次數, 起, 統計, 事件)。"""
    if 匯率 is None or 期貨 is None or K is None or "foreign_oi" not in 期貨:
        return None
    k = K.set_index("date")[["open", "low", "close"]].astype(float)
    fx = 匯率.set_index("date")["usdtwd"].astype(float).reindex(k.index).ffill()
    oi = 期貨["foreign_oi"].astype(float).reindex(k.index)
    k = k[oi.notna()]
    fx, oi = fx.reindex(k.index), oi.reindex(k.index)
    if len(k) < 60:
        return None
    下影 = k[["open", "close"]].min(axis=1) - k["low"]
    影 = ((下影 >= k["close"] * 影線門檻 / 100) & (下影 > (k["close"] - k["open"]).abs())).astype(int)
    台 = (fx.diff() <= 0).astype(int)
    期 = ((oi.diff() > 0) & (oi < 0)).astype(int)
    全 = (影.rolling(天數).sum() == 天數) & (台.rolling(天數).sum() == 天數) & (期.rolling(天數).sum() == 天數)
    位們, 上次 = [], -10 ** 9
    for i in np.flatnonzero(全.to_numpy()):
        if i - 上次 > 間隔:
            位們.append(i)
            上次 = i
    c = k["close"]
    統計 = []
    for n in 後:
        報 = (c.shift(-n) / c - 1) * 100
        x = 報.iloc[位們].dropna()
        統計.append({"天數": n, "次數": int(len(x)), "平均%": round(float(x.mean()), 2) if len(x) else None,
                   "上漲機率%": round(float((x > 0).mean() * 100)) if len(x) else None,
                   "基準平均%": round(float(報.mean()), 2), "基準上漲機率%": round(float((報.dropna() > 0).mean() * 100))})
    事件 = [{"日期": f"{k.index[i]:%Y-%m-%d}", "收盤": round(float(c.iloc[i])),
             **{f"{n}日後%": (round(float(c.iloc[i + n] / c.iloc[i] * 100 - 100), 1) if i + n < len(c) else None) for n in 後}}
            for i in 位們]
    return {"次數": len(位們), "起": f"{k.index[0]:%Y-%m-%d}", "統計": 統計, "事件": 事件}


def 破低不破榜(價, K, 高點窗=60, 前波窗=60, 近期=20, 前後=3, 最低成交值億=2.0):
    """W2（關我什麼事）：大盤近 近期 日低點跌破前波低點時，
    列出自己近 近期 日低點還高於「大盤前波低點那幾天（±前後 日）自己的低點」的股票。
    價：指標表（代號、名稱、date、low、收盤、成交值億 可有可無）；K：加權日 K。
    前波低點＝這一段下跌的起點（近 高點窗 日收盤最高那天）之前 前波窗 日內的最低點，例如 10/06 高點之前的 7/29 低點。
    回傳 (表, 資訊 dict(前波日, 前波低, 近期低, 大盤破了, 大盤距前低%))；資料不夠回 (空表, None)。"""
    if K is None or len(K) < 高點窗 + 前波窗 or 價 is None or not len(價):
        return pd.DataFrame(), None
    K = K.reset_index(drop=True)
    低 = K["low"].astype(float)
    高位 = len(K) - 高點窗 + int(np.argmax(K["close"].astype(float).tail(高點窗).to_numpy()))
    段 = K.iloc[max(0, 高位 - 前波窗):高位]
    if not len(段):
        return pd.DataFrame(), None
    前位 = int(段["low"].astype(float).idxmin())
    前日, 前低 = K["date"].iloc[前位], float(低.iloc[前位])
    近低 = float(低.tail(近期).min())
    資訊 = {"前波日": 前日, "前波低": 前低, "近期低": 近低, "大盤破了": 近低 < 前低,
            "大盤距前低%": round((近低 / 前低 - 1) * 100, 2)}
    日們 = K["date"].iloc[max(0, 前位 - 前後):前位 + 前後 + 1]
    低欄 = "low" if "low" in 價.columns else "收盤"
    p = 價[價["代號"].astype(str).str.fullmatch(r"\d{4}")]
    舊 = p[p["date"].isin(日們)].groupby("代號")[低欄].min()
    近日 = K["date"].tail(近期)
    近 = p[p["date"].isin(近日)]
    最新日 = p["date"].max()
    今 = p[p["date"] == 最新日].set_index("代號")
    t = pd.DataFrame({"前波時低點": 舊, "近期低點": 近.groupby("代號")[低欄].min()}).dropna()
    t = t[t["前波時低點"] > 0]
    t["高於前低%"] = ((t["近期低點"] / t["前波時低點"] - 1) * 100).round(1)
    t = t[t["高於前低%"] > 0]
    if "成交值億" in 近.columns:
        量 = 近.groupby("代號")["成交值億"].mean()
        t = t[量.reindex(t.index).fillna(0) >= 最低成交值億]
    for 欄 in ("名稱", "收盤", "產業"):
        if 欄 in 今.columns:
            t[欄] = 今[欄].reindex(t.index)
    if "收盤" in t:
        t["收盤距近期低%"] = ((t["收盤"] / t["近期低點"] - 1) * 100).round(1)
    t = t.reset_index().rename(columns={"index": "代號"})
    欄 = [c for c in ["代號", "名稱", "產業", "收盤", "前波時低點", "近期低點", "高於前低%", "收盤距近期低%"] if c in t.columns]
    return t[欄].sort_values("高於前低%", ascending=False).reset_index(drop=True), 資訊


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
    財 = 欄最大("fundamental/cashflow.csv", "quarter")
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
        ("台指期正逆價差", (lambda v: v and pd.Timestamp(v))(欄最大("futures_basis.csv", "date")), "每個交易日", "交易日", 1),
        ("外資持股比", (lambda v: v and pd.Timestamp(v))(欄最大("qfii.csv.gz", "date")), "每個交易日", "交易日", 1),
        ("上市個股當沖", (lambda v: v and pd.Timestamp(v))(欄最大("daytrade.csv.gz", "date")), "每個交易日", "交易日", 1),
        ("選擇權籌碼", (lambda v: v and pd.Timestamp(v))(欄最大("options_pc.csv", "date")), "每個交易日", "交易日", 1),
        ("集保大戶（千張）", _最新檔日("tdcc"), "每週", "天", 10),
        ("美元匯率", fx and pd.Timestamp(fx), "每天", "天", 5),
        ("月營收", 營 and pd.Period(營, "M").to_timestamp(), "每月 10 日前", "期末", (期末(營, "M"), 45)),
        ("內部人持股", 內 and pd.Period(內, "M").to_timestamp(), "每月 15 日前", "期末", (期末(內, "M"), 50)),
        ("季報 EPS", 季 and pd.Period(季, "Q").to_timestamp(), "每季", "期末", (期末(季, "Q"), 140)),
        ("資產負債、現金流量", 財 and pd.Period(財, "Q").to_timestamp(), "每季", "期末", (期末(財, "Q"), 140)),
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
    市值 = (上市["融資餘額"].astype("float64") * 1000 * 上市["收盤"]).groupby(上市["date"]).sum(min_count=1)
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
        融 = 群["融資餘額"].sum(min_count=1).astype(float)
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
    "盤前": "台股開盤前（08:30）的盤前解讀：昨晚美股、費半、台積電 ADR 與台指期夜盤怎麼走，今天開盤可能在哪個位置、受影響的族群、"
            "今天要注意的事件，以及今天盤中要看的 2～3 個價位或條件。",
    "收盤": "台股收盤後的收盤分析：如果數據裡有「收盤對答案」，第一段先用 2～3 句說早上與前一晚提出的條件哪些成立、哪些沒有，"
            "沒成立的要說代表什麼；接著是今天盤勢結構（指數位置、誰在撐盤、漲跌家數、量價）、強弱族群與避風港、資金流向（外資、投信、融資、期貨）、"
            "今天有沒有跌破或站回重要價位、明天要看的 2～3 個價位或條件。",
    "夜盤": "晚上 22:00 的夜盤與美股解讀：美股開盤、費半與台指期夜盤表現、國際事件，對照台股的關鍵價位，提出明天的劇本。",
}
大盤解讀提示 = """你是台灣股市的研究助理，替剛開始學投資、多半用手機看的投資人寫大盤解讀。讀者看完要知道「現在在哪裡、接下來看什麼、看到什麼要怎麼做」。

思考順序（照做，但不用把步驟名稱寫出來）：
1. 由外而內：美股與費半 → 台積電 ADR、台指期夜盤 → 加權 → 櫃買 → 族群。
2. 先判斷格局（數據裡的「格局」：盤整／上升／下降），同一個訊號在不同格局意思不同。
3. 再找價位：只用數據裡算好的均線、共振區、缺口、回檔、整數關卡、分價量密集區，名稱和數字照抄，不要自己發明價位。
4. 看結構不只看漲跌：誰在撐盤（電子或金融電信）、櫃買比加權強或弱、量價關係、漲跌家數、避風港與提款機族群。
5. 三條件燈號、黑 K 一半、恐慌溫度計、分析師常用條件（週線位置、KD、5 日線扣抵值、爆量 K 棒）是現成的判斷，要引用並說明意思；恐慌是線索不是訊號，要等價格確認。
6. 結論寫成條件劇本，每個劇本都要有具體價位，並寫出「看錯了怎麼辦」。

寫法規則：
- 繁體中文、白話，專有名詞第一次出現用一句話解釋；每段 2～4 句，手機好讀。
- 只根據提供的數據寫，不要編造沒有給的數字；資料缺的就說「資料不足」。關聯不要寫成因果。
- 不預測哪一天轉折、不說「明天會漲／會跌 X%」；只寫「站上／跌破哪個價位就怎樣」。
- 不點名叫人買賣個股；個股只能當族群或撐盤的例子。
- 數字門檻常識（判斷高低時照這個，不要說反）：
  · 融資維持率：低於 130% 才會被追繳（斷頭壓力），150% 以下偏緊，160% 以上屬正常偏安全。
  · VIX：15 以下平靜、20 以上緊張、30 以上恐慌。
  · 法人買賣超看「金額」，不要用張數排名（低價股張數多但金額小）。
  · 外資台指期淨空單變多＝避險或看空增加，變少＝空單回補。
  · 量價：價漲量增健康、價跌量增賣壓重、價跌量縮賣壓減輕。
  · KD：低於 20 是超賣、高於 80 是過熱，但沒有黃金交叉（K 由下往上穿過 D）不算反轉，超賣不等於可以買。
  · 扣抵值：明天收盤高於扣抵值，5 日線才會往上彎；接下來幾天「扣高」代表均線短期不容易翻揚。
  · 週線：跌破 5 週線是短線回檔，跌破 20 週線才是中期轉弱。
  · 爆量 K 棒：跌破爆量那天的低點＝那天買的人都被套，賣壓重；站上高點＝賣壓消化完。
- 用 Markdown，800 字以內，依序分成：
  ## 一句話結論（含燈號 🟢🟡🔴 與格局）
  ## 現在在哪裡（指數位置、最近的支撐與壓力、共振區）
  ## 盤勢結構（誰在撐盤、量價、櫃買強弱、族群與資金，3～5 點）
  ## 劇本（偏多：站上／守住哪裡＋要看到什麼；偏空：跌破哪裡＋怎麼因應；看錯了怎麼辦）
  ## 今天要看的條件（2～3 條，每條都要有價位或可以驗證的數字，例如「加權收盤守住 45,000」）
  ## 今天學一個觀念（挑一個跟今天數據直接相關的觀念，例如黑 K 一半、共振區、量價背離、融資維持率、櫃買÷加權，
     用 2～3 句白話解釋「它是什麼、今天的數字代表什麼」；盡量不要跟前幾天重複）
  ## 風險提醒（含未來幾天的重要事件）
- 最後一行固定寫「（AI 依規則數據整理，僅供研究參考，不是買賣建議）」。"""


def 大盤摘要(指標, 加權, 國際=None, 期貨=None, 設定=None):
    """把網站上的大盤數據整理成一段文字，給 AI 寫大盤解讀用。有 設定 就加上網紅與券商的外部觀點。"""
    最新 = 指標["date"].max()
    今日 = 加基本面(指標[指標["date"] == 最新], 讀取基本面())
    行 = [f"資料日期：{最新:%Y-%m-%d}（台股最新收盤）"]
    if 加權 is not None and len(加權):
        r = 加權.iloc[-1]
        行.append(f"加權指數 {r['close']:,.0f}，漲跌 {r['change']:+,.0f} 點（{r['change'] / (r['close'] - r['change']) * 100:+.2f}%）")
    股 = 今日[今日["代號"].str.fullmatch(r"\d{4}")]
    行.append(f"上漲 {(股['漲跌'] > 0).sum()} 家、下跌 {(股['漲跌'] < 0).sum()} 家，成交 {今日['成交值億'].sum():,.0f} 億")
    權 = None
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
        融 = 指標.groupby("date")["融資餘額"].sum(min_count=1).dropna()
        if len(融) > 5:
            行.append(f"融資餘額 {融.iloc[-1]:,.0f} 張，5 日 {(融.iloc[-1] / 融.iloc[-6] - 1) * 100:+.1f}%")
        外 = 今日.assign(金額=今日["外資買超"] * 1000 * 今日["收盤"] / 1e8).dropna(subset=["金額"])
        行.append("外資買超金額前 5：" + "、".join(f"{r['名稱']} {r['金額']:+.1f} 億" for _, r in 外.nlargest(5, "金額").iterrows())
                 + "；賣超前 5：" + "、".join(f"{r['名稱']} {r['金額']:+.1f} 億" for _, r in 外.nsmallest(5, "金額").iterrows()))
    維 = 融資維持率(指標[指標["date"] >= 最新 - pd.Timedelta(days=10)])
    if 維 is not None and len(維):
        v = 維.iloc[-1]
        行.append(f"上市融資維持率約 {v:.0f}%（低於 130% 才會追繳；"
                 + ("目前偏緊，留意斷頭賣壓）" if v < 150 else "目前在安全範圍）"))
    期 = 讀取期貨未平倉()
    if 期 is not None and len(期) > 5:
        行.append(f"外資台指期淨部位 {期['foreign_oi'].iloc[-1]:+,.0f} 口（5 日變化 {期['foreign_oi'].iloc[-1] - 期['foreign_oi'].iloc[-6]:+,.0f}）")
    try:
        情 = 情緒指數(指標, 加權).dropna(how="all", subset=["散戶", "法人"]).iloc[-1]
        行.append("情緒分數（0～100）：" + "、".join(f"{k} {情[k]:.0f}" for k in ("法人", "散戶", "資金溫度", "全球") if pd.notna(情[k]))
                 + f"；法人×散戶象限：{情緒象限(情['散戶'], 情['法人'])}")
    except Exception:
        pass
    行 += 大盤價位摘要(指標, 今日, 權)
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
    try:
        本 = 大盤本益比()
        if len(本) >= 12:
            v, 近 = 本["本益比"].iloc[-1], 本[本["date"] >= 本["date"].max() - pd.Timedelta(days=365 * 5)]["本益比"]
            行.append(f"上市加權本益比（近四季，網站估算）{v:.1f} 倍，5 年區間 {近.min():.1f}～{近.max():.1f} 倍、中位數 {近.median():.1f} 倍")
    except Exception:
        pass
    try:
        目, _, 彙 = 週線連跌統計(讀取指數K線("TAIEX"))
        if 目["連跌週數"] >= 2 or 目["乖離%"] <= -3:
            t = f"加權週線連跌 {目['連跌週數']} 週，週收盤比 5 週線 {目['乖離%']:+.1f}%"
            if len(彙):
                r = 彙.iloc[-1]
                t += f"；過去 5 年連跌 3 週且乖離 −5% 以下共 {r['次數']} 次，{r['期間']}上漲機率 {r['上漲機率%']:.0f}%、平均 {r['平均%']:+.1f}%"
            行.append(t)
    except Exception:
        pass
    if 設定 is not None:
        外 = 外部觀點摘要(設定, 指標, dict(zip(今日["名稱"], 今日["代號"])))
        if 外:
            行.append(外)
    return "\n".join(行)


def 大盤價位摘要(指標, 今日, 權=None):
    """大盤解讀用：加權、櫃買的格局與關鍵價位，三條件燈號、櫃買強弱、誰在撐盤、避風港、恐慌溫度計。每項失敗就略過。"""
    行 = [""]
    美股 = None
    try:
        美股 = 讀取美股()
    except Exception:
        pass
    K們 = {}
    for 代, 市, 名 in (("TAIEX", "上市", "加權"), ("TPEX", "上櫃", "櫃買")):
        try:
            K = 讀取指數K線(代)
            K們[代] = K
            量 = 指標[指標["市場"] == 市].groupby("date")["成交值億"].sum() if "市場" in 指標 else None
            文 = 價位摘要(K, 量, 名)
            if 文:
                行 += [f"【{名}指數價位】", 文]
        except Exception as e:
            print(f"{名}價位摘要失敗：", repr(e))
    try:
        項們, 總結 = 三條件燈號(K們.get("TAIEX"), K們.get("TPEX"), 美股)
        if 項們:
            行.append("【三條件燈號】" + "；".join(f"{燈}{名}：{說}" for 名, 燈, 說 in 項們) + f"。總結：{總結}")
    except Exception:
        pass
    try:
        _, _, 文 = 櫃買加權比(K們.get("TAIEX"), K們.get("TPEX"))
        if 文:
            行.append("【櫃買÷加權】" + 文)
    except Exception:
        pass
    if 權 is not None:
        try:
            行.append("【誰在撐盤】" + 撐盤分組(權)[1])
        except Exception:
            pass
    try:
        加 = K們.get("TAIEX")
        大5 = (float(加["close"].iloc[-1]) / float(加["close"].iloc[-6]) - 1) * 100 if 加 is not None and len(加) > 5 else None
        港, 提 = 避風港與提款機(今日, 大5)
        if len(港):
            行.append("【避風港（近 5 日抗跌族群）】" + "、".join(f"{k} 5 日 {r['5日']:+.1f}%" for k, r in 港.iterrows()))
        if len(提):
            行.append("【提款機（前段漲多、近 5 日被賣）】" + "、".join(f"{k} 5 日 {r['5日']:+.1f}%、20 日 {r['20日']:+.1f}%" for k, r in 提.iterrows()))
    except Exception as e:
        print("避風港失敗：", repr(e))
    try:
        文 = 殺估值摘要(指標, 美股)
        if 文:
            行.append(文)
    except Exception as e:
        print("殺估值觀察失敗：", repr(e))
    try:
        項們, 溫, 級, 話 = 恐慌溫度計(美股, 讀取匯率(), 讀取小台散戶())
        if 項們:
            行.append(f"【恐慌溫度計】{溫:.0f} 分（{級}）：" + "；".join(f"{n} {v}（{說}）" for n, v, 說, _ in 項們) + f"。{話}")
    except Exception:
        pass
    return 行 if len(行) > 1 else []


def AI大盤解讀(摘要, 模式, 設定):
    """用 Gemini（有 GEMINI_API_KEY）或 Claude 寫大盤解讀。回傳 (Markdown, 模型名稱)。"""
    import datetime as dt
    現在 = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    try:
        驗 = 驗收大盤解讀(讀取大盤解讀(設定), {"加權": 讀取指數K線("TAIEX"), "櫃買": 讀取指數K線("TPEX")})
    except Exception as e:
        print("解讀驗收失敗：", repr(e))
        驗 = []
    if 模式 == "收盤" and 驗:
        try:
            回顧 = 條件回顧文字(驗, 讀取指數K線("TAIEX")["date"].iloc[-1])
            if 回顧:
                摘要 = f"{摘要}\n\n{回顧}"
        except Exception as e:
            print("條件回顧失敗：", repr(e))
    try:  # 回饋循環：錯誤本＋規則體檢
        import feedback
        錯 = feedback.大盤錯誤本(驗)
        體 = feedback.規則體檢文字(給AI=True)
        回 = "\n".join([x for x in [錯, *體] if x])
        if 回:
            摘要 = f"{摘要}\n\n{回}"
    except Exception as e:
        print("錯誤本失敗：", repr(e))
    問題 = f"現在是台灣時間 {現在}。請寫「{模式}」解讀：{解讀模式[模式]}\n\n以下是最新數據：\n{摘要}"
    系統 = 大盤解讀提示 + 解讀條件說明
    if str(設定.get("GEMINI_API_KEY", "")).strip():
        內容 = {"systemInstruction": {"parts": [{"text": 系統}]},
                "contents": [{"role": "user", "parts": [{"text": 問題}]}]}
        回應, 模型 = Gemini呼叫(內容, 清理金鑰(設定["GEMINI_API_KEY"]), str(設定.get("GEMINI_MODEL", "gemini-flash-latest")))
        候選 = (回應.json().get("candidates") or [{}])[0]
        文字 = "".join(p.get("text", "") for p in (候選.get("content") or {}).get("parts", [])).strip()
    elif str(設定.get("ANTHROPIC_API_KEY", "")).strip():
        import anthropic
        模型 = str(設定.get("AI_MODEL", "claude-opus-5-5"))
        回應 = anthropic.Anthropic(api_key=清理金鑰(設定["ANTHROPIC_API_KEY"])).messages.create(
            model=模型, max_tokens=4000, system=系統, messages=[{"role": "user", "content": 問題}])
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
    內容, 條 = 拆解解讀條件(內容)
    全部[f"{現在:%Y-%m-%d}_{模式}"] = {"時間": f"{現在:%Y-%m-%d %H:%M}", "模式": 模式, "內容": 內容, "模型": 模型, **條,
                                    "提示版本": 大盤提示版本()}
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


def 讀取小台散戶():
    """data/mtx_retail.csv：小台散戶多空比（%，正＝散戶淨多單）。沒有資料回傳 None。"""
    f = 資料夾 / "mtx_retail.csv"
    if not f.exists():
        return None
    t = pd.read_csv(f, parse_dates=["date"]).sort_values("date")
    if not len(t) or t["date"].max() < pd.Timestamp.today().normalize() - pd.Timedelta(days=10):
        return None   # 太久沒更新（還在回補）就先不顯示，免得拿舊數字當今天
    return t


def 恐慌溫度計(美股=None, 匯率=None, 散戶=None):
    """反向思考用：VIX 在過去一年的位置、美元兌台幣在一年區間的位置（台幣越貶＝外資匯出壓力越大）、
    小台散戶多空比（散戶越看空＝越絕望）。每項換成 0～100 的「恐慌分數」再平均。
    回傳 (項目 [(名稱, 數值字, 說明, 分數)], 溫度, 等級, 白話)。"""
    項們 = []
    if 散戶 is not None and len(散戶) >= 20:
        x = 散戶.set_index("date")["ratio"].dropna().tail(252)
        現 = float(x.iloc[-1])
        分 = float((x > 現).mean() * 100)   # 散戶越看空，恐慌分數越高
        級 = "散戶大舉做多" if 現 >= 20 else "散戶偏多" if 現 >= 5 else "散戶大舉做空" if 現 <= -20 else "散戶偏空" if 現 <= -5 else "中性"
        項們.append(("韭菜指數（小台散戶多空比）", f"{現:+.1f}%", f"{級}・比過去一年 {100 - 分:.0f}% 的日子看多；"
                    "散戶通常是反向指標，大舉做多時要小心", 分))
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
def 支撐壓力回測(K, 量=None, 間隔=5, 往後=20, 守住天數=3, 碰到=0.003, 跌破=0.01, 範圍=0.05, 起=250):
    """這些自動價位過去準不準：每隔幾天站在「當時」只用當時以前的資料畫價位，看之後 20 天有沒有碰到、碰到後有沒有守住。
    支撐守住＝碰到那天起 守住天數 內收盤都沒跌破價位 1% 以上；壓力守住＝收盤都沒突破 1% 以上。
    另外放「隨機對照」：距離收盤 1～4% 的任意價位，用來比較自動價位是不是真的比較有用。
    回傳每次測試的明細 DataFrame（類別, 角色, 共振, 守住）。"""
    k = K.dropna(subset=["close"]).reset_index(drop=True)
    低, 高, 收們 = k["low"].values, k["high"].values, k["close"].values
    列們 = []
    for t in range(起, len(k) - 往後, 間隔):
        sr = 支撐壓力(k.iloc[:t + 1], 量=量)
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
    t = 調整分割EPS(t[t["code"].isin(金)])
    t = t.dropna(subset=["eps"]).sort_values(["code", "quarter"]).copy()
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


# ========== 25. 給 AI 的價位與格局摘要、評價方法建議 ==========
def 格局判斷(K):
    """烏賊課程的三種格局：盤整（在前 20 日高低區間內）、上升（突破區間，或站上上彎的 10 日線）、下降（跌破區間，或跌破下彎的 10 日線）。
    回傳 dict(格局, 說明, 十日線, 區間上, 區間下)。"""
    if K is None or len(K) < 25:
        return None
    k = K.reset_index(drop=True)
    c = k["close"]
    高 = k["high"] if 有開高低(k) else c
    低 = k["low"] if 有開高低(k) else c
    收, 十 = float(c.iloc[-1]), float(c.tail(10).mean())
    十彎 = 十 - float(c.iloc[-13:-3].mean())
    上, 下 = float(高.iloc[-21:-1].max()), float(低.iloc[-21:-1].min())
    小數 = 0 if 收 > 1000 else 2
    f = lambda v: f"{v:,.{小數}f}"
    if 收 > 上:
        格, 說 = "上升", f"收盤 {f(收)} 突破前 20 日區間上緣 {f(上)}"
    elif 收 < 下:
        格, 說 = "下降", f"收盤 {f(收)} 跌破前 20 日區間下緣 {f(下)}"
    elif 收 >= 十 and 十彎 > 0:
        格, 說 = "上升", f"站上往上彎的 10 日線 {f(十)}，區間 {f(下)}～{f(上)}"
    elif 收 < 十 and 十彎 < 0:
        格, 說 = "下降", f"跌破往下彎的 10 日線 {f(十)}，區間 {f(下)}～{f(上)}"
    else:
        格, 說 = "盤整", f"在前 20 日區間 {f(下)}～{f(上)} 內，10 日線 {f(十)}"
    return {"格局": 格, "說明": 說, "十日線": 十, "區間上": 上, "區間下": 下}


def 價位摘要(K, 量=None, 名稱=""):
    """把支撐壓力、共振區、格局、黑 K 一半、量價、今天跌破站回整理成幾行文字，給 AI 當寫解讀的價位依據。"""
    if K is None or len(K) < 60:
        return ""
    行 = []
    格 = 格局判斷(K)
    if 格:
        行.append(f"{名稱}格局：{格['格局']}（{格['說明']}）")
    sr = 支撐壓力(K, 量=量)
    區們 = 共振區(sr["價位"])
    行.append(f"{名稱}位置：" + 位置解讀(sr, 區們)["文字"])
    收 = sr["收盤"]
    小數 = 0 if 收 > 1000 else 2
    價 = sr["價位"]
    if len(價):
        行.append(f"{名稱}價位表：" + "；".join(
            f"{r['名稱']} {r['價位']:,.{小數}f}（{r['角色']} {r['距離%']:+.1f}%）" for _, r in 價.iterrows()
            if abs(r["距離%"]) <= 8))
    if 區們:
        行.append(f"{名稱}共振區：" + "；".join(
            f"{z['下']:,.{小數}f}～{z['上']:,.{小數}f}（{z['角色']}，{'、'.join(z['成員'][:4])}）" for z in 區們
            if abs(z["中"] / 收 - 1) <= 0.08))
    黑 = 黑K一半(K)
    if 黑:
        行.append(f"{名稱}黑 K 一半：{黑['日期']:%m/%d} 黑 K 中點 {黑['中點']:,.{小數}f}，{黑['狀態']}（{黑['燈']}）")
    if 量 is not None:
        標 = 量價標籤(K, 量, 3)
        if 標:
            行.append(f"{名稱}量價：" + "、".join(f"{d:%m/%d} {t}（量為 5 日均量 {比:.2f} 倍）" for d, t, 比 in 標))
    try:
        變 = 跌破站回(K, 量) + 技術訊號(K, 量)
        if 變:
            行.append(f"{名稱}今天：" + "、".join(f"{a}{n}" + ("" if v is None else f" {v:,.{小數}f}") for a, n, v in 變))
    except Exception:
        pass
    try:
        文 = 技術觀察摘要(K, 量, 名稱)
        if 文:
            行.append(文)
    except Exception:
        pass
    return "\n".join(行)


def 評價方法建議(產業, EPS=None):
    """依產業與獲利狀態建議評價方法（參考券商：營建、金融用股價淨值比與殖利率，虧損公司只能用股價淨值比）。"""
    if pd.notna(EPS) and EPS <= 0:
        return "股價淨值比（P/B）：目前 EPS ≤ 0，本益比沒有意義"
    if 產業 in ("建材營造", "營建", "金融保險"):
        return "股價淨值比（P/B）＋殖利率：營建、金融獲利認列不平均，看淨值與配息較準"
    if 產業 in ("航運業", "鋼鐵工業", "塑膠工業", "水泥工業", "造紙工業"):
        return "景氣循環股：獲利高峰時本益比會偏低，建議同時看股價淨值比（P/B）與本益比"
    return "本益比（P/E）：未來 4 季或明年 EPS × 合理倍數"


# ========== 26. 大盤解讀的觀察條件：對答案與記分板 ==========
解讀條件說明 = """
最後面另外附上一個 ```json 程式碼區塊（給網站對答案用，讀者看不到），最多 3 條條件，價位只能用數據裡的數字：
{"看法": "偏多/中性/偏空", "條件": [{"說明": "加權收盤守住 45,000", "指數": "加權/櫃買", "方向": "站上/守住/跌破", "價位": 45000}]}"""


def 拆解解讀條件(文字):
    """把解讀最後的 json 區塊拆出來；回傳 (給人看的內文, {"看法", "條件"} 或 {})。"""
    import json, re
    配 = re.search(r"```json\s*(\{.*?\})\s*```", 文字, re.S)
    if not 配:
        return 文字, {}
    try:
        資料 = json.loads(配.group(1))
    except Exception:
        資料 = {}
    條件 = []
    for c in 資料.get("條件") or []:
        try:
            if c.get("指數") in ("加權", "櫃買") and c.get("方向") in ("站上", "守住", "跌破"):
                條件.append({"說明": str(c.get("說明", ""))[:60], "指數": c["指數"], "方向": c["方向"], "價位": float(c["價位"])})
        except (TypeError, ValueError):
            continue
    看法 = 資料.get("看法") if 資料.get("看法") in ("偏多", "中性", "偏空") else None
    return (文字[: 配.start()] + 文字[配.end():]).strip(), {"看法": 看法, "條件": 條件[:3]}


def 解讀驗收日(時間, 交易日):
    """解讀寫完後第一個收盤（13:30）的交易日：盤前驗當天、收盤與夜盤驗下一個交易日。交易日＝由舊到新的日期。"""
    t = pd.Timestamp(str(時間)[:16])
    for d in 交易日:
        if pd.Timestamp(d) + pd.Timedelta(hours=13, minutes=30) > t:
            return pd.Timestamp(d)
    return None


def 驗收大盤解讀(紀錄, K們):
    """K們＝{"加權": K, "櫃買": K}。回傳每篇解讀的對答案結果（由新到舊），還沒到驗收日的不列。
    看法：偏多＋加權收紅、偏空＋加權收黑＝對；中性不計分。條件：站上／守住＝收盤 ≥ 價位，跌破＝收盤 < 價位。"""
    加 = K們.get("加權")
    if 加 is None or len(加) < 2:
        return []
    交易日 = list(加["date"])
    收們 = {名: K.set_index("date")["close"] for 名, K in K們.items() if K is not None}
    結果 = []
    for 鍵, v in sorted(紀錄.items(), reverse=True):
        條 = v.get("條件") or []
        if not 條 and not v.get("看法"):
            continue
        日 = 解讀驗收日(v.get("時間", ""), 交易日)
        if 日 is None or 日 not in 收們["加權"].index:
            continue
        i = 交易日.index(日)
        if i == 0:
            continue
        幅 = (收們["加權"][日] / 收們["加權"][交易日[i - 1]] - 1) * 100
        看 = v.get("看法")
        對 = None if 看 in (None, "中性") else bool((看 == "偏多") == (幅 > 0))
        明細 = []
        for c in 條:
            s = 收們.get(c["指數"])
            if s is None or 日 not in s.index:
                continue
            收 = float(s[日])
            成立 = 收 < c["價位"] if c["方向"] == "跌破" else 收 >= c["價位"]
            明細.append({**c, "收盤": 收, "成立": bool(成立)})
        結果.append({"鍵": 鍵, "時間": v.get("時間"), "模式": v.get("模式"), "看法": 看, "驗收日": 日,
                   "加權漲跌%": float(幅), "看法對": 對, "條件": 明細})
    return 結果


def 條件回顧文字(驗收, 日期):
    """收盤解讀用：今天（日期）要驗收的盤前與前一晚條件，整理成給 AI 的文字。"""
    今 = [x for x in 驗收 if x["驗收日"] == pd.Timestamp(日期)]
    if not 今:
        return ""
    行 = ["【今天早上與前一晚解讀提出的條件，收盤對答案】"]
    for x in 今:
        行.append(f"{x['時間']} {x['模式']}解讀（看法 {x['看法'] or '未標'}，加權今天 {x['加權漲跌%']:+.2f}%）：" + "；".join(
            f"{c['說明']} → {'成立' if c['成立'] else '沒有成立'}（{c['指數']}收 {c['收盤']:,.2f}）" for c in x["條件"]))
    return "\n".join(行)


def 解讀記分(驗收, 篇數=20):
    """最近 N 篇的看法命中率與條件成立率。"""
    近 = 驗收[:篇數]
    看 = [x["看法對"] for x in 近 if x["看法對"] is not None]
    條 = [c["成立"] for x in 近 for c in x["條件"]]
    return {"篇數": len(近), "看法篇數": len(看), "看法命中": sum(看), "條件數": len(條), "條件成立": sum(條)}


# ========== 27. 券商報告收件匣：讀 PDF／截圖、修正追蹤、驗收、交叉驗證 ==========
券商報告提示 = """你是台股研究助理。使用者上傳一份券商或投顧研究報告（PDF），或一張整理多檔目標價的截圖。
請把裡面「每一檔股票」的評等資訊抽出來，只輸出一個 JSON 陣列（不要其他文字），每個元素：
{"代號": "4 碼台股代號，美股用英文代號", "名稱": "", "券商": "券商或投顧名稱", "日期": "YYYY-MM-DD 報告日期",
 "評等": "原文評等，例如 買進、Buy、增加持股、中立", "看法": "看多/中性/看空",
 "目標價": 數字或 null, "前次目標價": 數字或 null, "報告收盤價": 數字或 null,
 "EPS今年": 數字或 null, "EPS明年": 數字或 null, "前次EPS今年": 數字或 null, "前次EPS明年": 數字或 null,
 "評價方法": "例如 25 倍 × 2027 EPS 32.5；沒寫就 null", "評等定義": "例如 買進＝6 個月絕對報酬 15～30%；沒寫就 null",
 "理由": "用自己的話寫 60 字內的核心理由，不要照抄原文",
 "風險": "30 字內", "追蹤指標": "30 字內，報告提到要觀察的事",
 "白話": ["用 5 句白話向新手解釋：1 這份報告在說什麼 2 為什麼看好或看壞 3 目標價怎麼算出來 4 什麼情況代表看錯 5 現在價格貴不貴（用報告數字判斷）"],
 "可核對": [{"項目": "月營收/季營收/收盤價/毛利率", "期間": "例如 2026-09 或 3Q26 或 2026-10-21", "數值": 數字, "單位": "億元/元/%", "年增%": 數字或 null, "月增%": 數字或 null}]}
規則：數字填純數字；報告沒寫的填 null，不要猜；截圖裡每一列都是一筆（同一檔不同券商分開）；箭頭 ▲▼ 旁的「原 X」是前次數值；
EPS 欄若有兩個數字，上面是今年、下面是明年；「可核對」只放報告裡明確寫出的實績數字（不要放預估）。
截圖沒有理由、白話等資訊時，那些欄位填 null 或空陣列。"""


def AI讀券商報告(檔案, 檔名, 引擎, 金鑰, 模型):
    """把 PDF 或圖片交給 AI 抽出評等資料。回傳 list[dict]。"""
    import base64, json, re
    小 = 檔名.lower()
    類 = "application/pdf" if 小.endswith(".pdf") else ("image/png" if 小.endswith(".png") else "image/jpeg")
    if 引擎 == "Gemini":
        內容 = {"contents": [{"role": "user", "parts": [
                    {"inline_data": {"mime_type": 類, "data": base64.b64encode(檔案).decode()}},
                    {"text": 券商報告提示}]}],
                "generationConfig": {"responseMimeType": "application/json"}}
        回應, _ = Gemini呼叫(內容, 金鑰, 模型)
        候選 = (回應.json().get("candidates") or [{}])[0]
        文字 = "".join(p.get("text", "") for p in (候選.get("content") or {}).get("parts", []))
    else:
        import anthropic
        區 = ({"type": "document", "source": {"type": "base64", "media_type": 類, "data": base64.b64encode(檔案).decode()}}
             if 類 == "application/pdf" else
             {"type": "image", "source": {"type": "base64", "media_type": 類, "data": base64.b64encode(檔案).decode()}})
        回應 = anthropic.Anthropic(api_key=金鑰).messages.create(
            model=模型, max_tokens=8000, system=券商報告提示,
            messages=[{"role": "user", "content": [區, {"type": "text", "text": "請抽出這份報告的資料。"}]}])
        文字 = "".join(b.text for b in 回應.content if b.type == "text")
    配 = re.search(r"\[.*\]", 文字, re.S)
    if not 配:
        raise RuntimeError("AI 沒有讀出任何報告資料，請確認檔案是券商報告或目標價截圖。")
    資料 = json.loads(配.group(0))
    結果 = []
    for x in 資料 if isinstance(資料, list) else []:
        if not isinstance(x, dict) or not x.get("代號"):
            continue
        x["代號"] = str(x["代號"]).strip().upper()
        x["來源檔"] = 檔名
        結果.append(x)
    return 結果


def 讀取券商報告(設定):
    try:
        return (讀取設定檔(設定, "broker_reports.json") or {}).get("報告", [])
    except Exception:
        return []


def 合併券商報告(舊, 新):
    """同一檔、同券商、同日期視為同一份，新的覆蓋舊的。回傳依日期由新到舊的清單。"""
    鍵 = lambda x: (x.get("代號"), x.get("券商"), x.get("日期"))
    表 = {鍵(x): x for x in 舊}
    for x in 新:
        表[鍵(x)] = {**表.get(鍵(x), {}), **x}
    return sorted(表.values(), key=lambda x: str(x.get("日期") or ""), reverse=True)


def 儲存券商報告(設定, 報告們):
    return 儲存設定檔(設定, "broker_reports.json", {"報告": 報告們}, f"券商報告 {len(報告們)} 筆")


def _數(v):
    try:
        f = float(v)
        return f if np.isfinite(f) else np.nan
    except (TypeError, ValueError):
        return np.nan


def 修正方向(x):
    """目標價與 EPS 跟前次比：上修／下修／持平／首次。"""
    方向 = {}
    for 名, 今, 前 in (("目標價", "目標價", "前次目標價"), ("EPS今年", "EPS今年", "前次EPS今年"), ("EPS明年", "EPS明年", "前次EPS明年")):
        a, b = _數(x.get(今)), _數(x.get(前))
        方向[名] = "—" if np.isnan(a) or np.isnan(b) else ("上修" if a > b * 1.001 else ("下修" if a < b * 0.999 else "持平"))
    return 方向


def 券商報告表(報告們):
    """整理成 DataFrame：一列一份報告，含修正方向。"""
    if not 報告們:
        return pd.DataFrame()
    列們 = []
    for x in 報告們:
        方 = 修正方向(x)
        列們.append({"日期": pd.to_datetime(x.get("日期"), errors="coerce"), "代號": x.get("代號"), "名稱": x.get("名稱"),
                   "券商": x.get("券商"), "評等": x.get("評等"), "看法": x.get("看法"),
                   "目標價": _數(x.get("目標價")), "前次目標價": _數(x.get("前次目標價")),
                   "EPS今年": _數(x.get("EPS今年")), "EPS明年": _數(x.get("EPS明年")),
                   "目標價修正": 方["目標價"], "EPS修正": "上修" if "上修" in (方["EPS今年"], 方["EPS明年"]) else
                   ("下修" if "下修" in (方["EPS今年"], 方["EPS明年"]) else ("持平" if "持平" in (方["EPS今年"], 方["EPS明年"]) else "—")),
                   "評價方法": x.get("評價方法"), "標籤": 報告標籤(x), "報告收盤價": _數(x.get("報告收盤價"))})
    return pd.DataFrame(列們).sort_values("日期", ascending=False).reset_index(drop=True)


外資券商字 = ("大和", "高盛", "摩根", "大摩", "小摩", "美林", "美銀", "花旗", "瑞銀", "麥格理", "野村", "滙豐", "匯豐", "里昂",
           "巴克萊", "德意志", "傑富瑞", "伯恩斯坦", "瑞穗", "Morgan", "Goldman", "Citi", "UBS", "Macquarie", "Nomura",
           "HSBC", "CLSA", "Jefferies", "BofA", "Bernstein", "Daiwa", "Mizuho", "Barclays")
一次性字 = ("一次性", "處分", "業外", "退稅", "回沖", "賣廠", "出售", "評價利益", "稅率", "匯兌", "和解", "認列", "非經常")


def 解析評價(文字):
    """從「35 倍 × FY28 EPS 3.00」這種評價方法文字拆出：倍數、估值年度、用的 EPS、前次倍數、是否用淨值比。"""
    import re
    t = str(文字 or "")
    數字 = lambda m: float(m.group(1)) if m else np.nan
    倍 = 數字(re.search(r"([\d.]+)\s*倍", t))
    前 = 數字(re.search(r"由\s*([\d.]+)\s*倍", t))
    if not np.isnan(前):  # 「本益比由 50.5 倍降到 35 倍」：本次倍數是後面那個
        後 = re.search(r"(?:降|升|調|上修|下修)[到至為]\s*([\d.]+)\s*倍", t)
        倍 = 數字(後) if 後 else 倍
    年 = re.search(r"(?<!\d)20(\d{2})(?!\d)|FY\s*(\d{2})(?!\d)", t)  # 2027、FY2027、FY27 都要認得
    年 = (年.group(1) or 年.group(2)) if 年 else None
    return {"倍數": 倍, "前次倍數": 前, "估值年度": f"20{年}" if 年 else None,
            "EPS": 數字(re.search(r"EPS\s*([\d.]+)", t)), "淨值比": bool(re.search(r"淨值|P/?B|BVPS", t, re.I))}


def 報告標籤(x):
    """一次性項目、估值年度、追價上修。"""
    標 = []
    文 = " ".join(str(x.get(k) or "") for k in ("理由", "風險", "評價方法")) + " ".join(x.get("白話") or [])
    if any(k in 文 for k in 一次性字):
        標.append("一次性")
    年 = 解析評價(x.get("評價方法"))["估值年度"]
    if 年:
        標.append(f"估 {年}")
    前, 收, 目 = _數(x.get("前次目標價")), _數(x.get("報告收盤價")), _數(x.get("目標價"))
    if not np.isnan(前) and not np.isnan(收) and not np.isnan(目) and 目 > 前 and 前 < 收:
        標.append("追價上修")
    return "、".join(標)


def 目標價拆解(報告們):
    """目標價變動拆成「倍數變動」與「EPS／年度變動」：TP＝倍數 × EPS，所以 (1+總變動)＝(1+倍數變動)×(1+EPS變動)。
    前次倍數優先用同券商上一份報告，沒有就用評價方法文字裡的「由 X 倍」。回傳 DataFrame（新到舊）。"""
    列們 = []
    依序 = sorted(報告們, key=lambda x: str(x.get("日期")))
    for i, x in enumerate(依序):
        目, 前 = _數(x.get("目標價")), _數(x.get("前次目標價"))
        if np.isnan(目) or np.isnan(前) or 前 <= 0 or abs(目 / 前 - 1) < 0.001:
            continue
        本 = 解析評價(x.get("評價方法"))
        舊 = next((y for y in reversed(依序[:i]) if y.get("券商") == x.get("券商") and str(y.get("代號")) == str(x.get("代號"))), None)
        舊析 = 解析評價(舊.get("評價方法")) if 舊 else {}
        前倍 = 本["前次倍數"] if not np.isnan(本["前次倍數"]) else 舊析.get("倍數", np.nan)
        總 = 目 / 前 - 1
        倍變 = 本["倍數"] / 前倍 - 1 if not np.isnan(本["倍數"]) and not np.isnan(前倍) and 前倍 > 0 else np.nan
        獲變 = (1 + 總) / (1 + 倍變) - 1 if not np.isnan(倍變) else np.nan
        if np.isnan(倍變):  # 沒有倍數，改用同一年度 EPS 的上下修推回倍數變動
            for 今欄, 前欄 in (("EPS明年", "前次EPS明年"), ("EPS今年", "前次EPS今年")):
                e1, e0 = _數(x.get(今欄)), _數(x.get(前欄))
                if not np.isnan(e1) and not np.isnan(e0) and e0 > 0:
                    獲變 = e1 / e0 - 1
                    倍變 = (1 + 總) / (1 + 獲變) - 1
                    break
        年推 = bool(舊析.get("估值年度") and 本["估值年度"] and 舊析["估值年度"] != 本["估值年度"])
        if np.isnan(倍變):
            判 = "倍數資料不足，看不出是獲利還是估值變"
        elif abs(倍變) >= abs(獲變):
            判 = "主要是券商改倍數（估值變化，不是獲利變好）" if 總 > 0 else "主要是券商降倍數（估值變保守）"
        else:
            判 = ("主要是獲利預估上修" if 總 > 0 else "主要是獲利預估下修") + ("，且估值年度往後推" if 年推 else "")
        列們.append({"日期": pd.to_datetime(x.get("日期"), errors="coerce"), "代號": x.get("代號"), "名稱": x.get("名稱"),
                   "券商": x.get("券商"), "前次目標價": 前, "目標價": 目, "總變動%": round(總 * 100, 1),
                   "倍數變動%": round(倍變 * 100, 1) if not np.isnan(倍變) else np.nan,
                   "EPS與年度變動%": round(獲變 * 100, 1) if not np.isnan(獲變) else np.nan,
                   "估值年度": 本["估值年度"] or "—", "判讀": 判})
    t = pd.DataFrame(列們)
    return t.sort_values("日期", ascending=False).reset_index(drop=True) if len(t) else t


def 券商共識(報告們, 現價=None, 天數=180):
    """每家券商只取最新一份（近 天數 天），算目標價區間、中位數、上修下修家數、多中空家數、外資與本土各自中位數。"""
    if not 報告們:
        return None
    表 = 券商報告表(報告們)
    表 = 表[表["日期"] >= pd.Timestamp.now().normalize() - pd.Timedelta(days=天數)]
    if 表.empty:
        return None
    最新 = 表.sort_values("日期").groupby("券商").tail(1)
    目 = 最新["目標價"].dropna()
    外 = 最新["券商"].astype(str).apply(lambda b: any(k in b for k in 外資券商字))
    結果 = {"家數": len(最新), "目標價數": len(目), "最低": 目.min() if len(目) else np.nan, "中位數": 目.median() if len(目) else np.nan,
          "最高": 目.max() if len(目) else np.nan,
          "最樂觀": 最新.loc[目.idxmax(), "券商"] if len(目) else None, "最悲觀": 最新.loc[目.idxmin(), "券商"] if len(目) else None,
          "上修": int((最新["目標價修正"] == "上修").sum()), "下修": int((最新["目標價修正"] == "下修").sum()),
          "看多": int((最新["看法"] == "看多").sum()), "中性": int((最新["看法"] == "中性").sum()), "看空": int((最新["看法"] == "看空").sum()),
          "外資中位數": 最新.loc[外, "目標價"].median() if 外.any() else np.nan, "外資家數": int(外.sum()),
          "本土中位數": 最新.loc[~外, "目標價"].median() if (~外).any() else np.nan, "本土家數": int((~外).sum())}
    if 現價 and len(目):
        結果["現價位置%"] = round((現價 - 目.min()) / (目.max() - 目.min()) * 100, 0) if 目.max() > 目.min() else np.nan
        結果["中位數空間%"] = round((目.median() / 現價 - 1) * 100, 1)
    return 結果


def 共識文字(c):
    if not c:
        return ""
    t = (f"近半年 {c['家數']} 家券商：目標價 {c['最低']:,.0f}～{c['最高']:,.0f}，中位數 {c['中位數']:,.0f}"
         f"（最樂觀 {c['最樂觀']}、最悲觀 {c['最悲觀']}）；看多 {c['看多']}／中性 {c['中性']}／看空 {c['看空']}；"
         f"最新一份比前次上修 {c['上修']} 家、下修 {c['下修']} 家") if c["目標價數"] else f"近半年 {c['家數']} 家券商，沒有目標價"
    if c["外資家數"] and c["本土家數"] and not np.isnan(c["外資中位數"]) and not np.isnan(c["本土中位數"]):
        t += f"；外資中位數 {c['外資中位數']:,.0f} vs 本土 {c['本土中位數']:,.0f}"
    return t


def 集體升降評(報告們, 天數=3, 門檻=3, 今天=None):
    """近 天數 天內，同一檔有 門檻 家以上券商同方向調整目標價（或首次給評等時同看法）。回傳 [(代號, 名稱, 方向, 家數, 券商們)]。"""
    表 = 券商報告表(報告們)
    if 表.empty:
        return []
    今天 = pd.Timestamp(今天 or pd.Timestamp.now().normalize())
    近 = 表[表["日期"] >= 今天 - pd.Timedelta(days=天數 + 2)]  # 多抓兩天：週末與報告隔天才上傳
    結果 = []
    for (代, 名), g in 近.groupby(["代號", "名稱"]):
        for 方向 in ("上修", "下修"):
            家 = g.loc[g["目標價修正"] == 方向, "券商"].unique()
            if len(家) >= 門檻:
                結果.append((str(代), 名, 方向, len(家), "、".join(map(str, 家))))
    return sorted(結果, key=lambda x: -x[3])


def EPS共識走勢(報告們):
    """每個報告日，用各券商「截至那天的最新一份」算今年、明年 EPS 中位數。年度以報告日期的年份為準。"""
    列們 = []
    依序 = sorted(報告們, key=lambda x: str(x.get("日期")))
    for 日 in sorted({str(x.get("日期")) for x in 依序}):
        最新 = {}
        for x in 依序:
            if str(x.get("日期")) <= 日:
                最新[x.get("券商")] = x
        for 欄, 加 in (("EPS今年", 0), ("EPS明年", 1)):
            值們 = {}
            for x in 最新.values():
                v = _數(x.get(欄))
                if not np.isnan(v):
                    值們.setdefault(int(str(x.get("日期"))[:4]) + 加, []).append(v)
            for 年, v in 值們.items():
                列們.append({"日期": pd.Timestamp(日), "年度": f"{年} EPS", "中位數": float(np.median(v)), "家數": len(v)})
    return pd.DataFrame(列們)


def 覆蓋熱度(報告們, 天數=7):
    表 = 券商報告表(報告們)
    if 表.empty:
        return 表
    近 = 表[表["日期"] >= 表["日期"].max() - pd.Timedelta(days=天數)]
    g = 近.groupby(["代號", "名稱"])
    return pd.DataFrame({"報告數": g.size(), "券商數": g["券商"].nunique(), "上修": g["目標價修正"].apply(lambda s: (s == "上修").sum()),
                         "下修": g["目標價修正"].apply(lambda s: (s == "下修").sum()),
                         "目標價中位數": g["目標價"].median()}).reset_index().sort_values(["報告數", "券商數"], ascending=False)


循環產業 = {"航運業", "鋼鐵工業", "塑膠工業", "水泥工業", "造紙工業", "玻璃陶瓷", "橡膠工業", "化學工業", "油電燃氣業"}
循環概念字 = ("記憶體", "DRAM", "NAND", "面板")


def 加潛在空間(表, 現價):
    """現價＝{代號: 今天收盤}。加上「現價」與「潛在空間%」（目標價 ÷ 現價 − 1），每天跟著收盤更新。"""
    if 表.empty:
        return 表
    表 = 表.copy()
    表["現價"] = 表["代號"].astype(str).map(現價).astype(float)
    表["潛在空間%"] = ((表["目標價"] / 表["現價"] - 1) * 100).round(1)
    return 表


def 上修名單(報告們, 天數=30):
    """近 N 天有券商上修 EPS 或目標價的台股代號。"""
    表 = 券商報告表(報告們)
    if 表.empty:
        return set()
    近 = 表[表["日期"] >= pd.Timestamp.now().normalize() - pd.Timedelta(days=天數)]
    return set(近.loc[(近["EPS修正"] == "上修") | (近["目標價修正"] == "上修"), "代號"].astype(str))


def 驗收券商報告(x, 價格, 期限=126):
    """價格＝這檔每日 date、high、low、收盤。看報告後 6 個月（約 126 個交易日）內有沒有碰到目標價。
    回傳 {結果: 達標／進行中／到期未達標／無目標價, 天數, 報酬%, 基準價, 日期}。"""
    目標 = _數(x.get("目標價"))
    起 = pd.to_datetime(x.get("日期"), errors="coerce")
    結果 = {"結果": "無目標價", "天數": 0, "報酬%": np.nan, "基準價": np.nan, "日期": pd.NaT}
    if 價格 is None or len(價格) == 0 or pd.isna(起):
        return 結果
    p = 價格.sort_values("date")
    前 = p[p["date"] <= 起]
    基 = _數(x.get("報告收盤價"))
    if np.isnan(基) and len(前):
        基 = float(前["收盤"].iloc[-1])
    之後 = p[p["date"] > 起].head(期限)
    結果.update(基準價=基, 天數=len(之後))
    if len(之後) and not np.isnan(基):
        結果["報酬%"] = (float(之後["收盤"].iloc[-1]) / 基 - 1) * 100
    if np.isnan(目標) or np.isnan(基):
        return 結果
    向上 = 目標 >= 基
    碰 = 之後[之後["high"] >= 目標] if 向上 else 之後[之後["low"] <= 目標]
    if len(碰):
        return dict(結果, 結果="達標", 日期=碰["date"].iloc[0])
    return dict(結果, 結果="到期未達標" if len(之後) >= 期限 else "進行中")


def 交叉驗證(x, 營收表=None, 價格=None):
    """報告裡寫的實績數字（月營收、收盤價）跟網站資料比對。營收表＝這檔的 month、revenue（千元）。回傳 [(說明, ✅／⚠️, 網站數字)]。"""
    結果 = []
    代號 = str(x.get("代號"))
    for c in x.get("可核對") or []:
        項, 期, 值 = str(c.get("項目", "")), str(c.get("期間", "")), _數(c.get("數值"))
        if np.isnan(值):
            continue
        if 項 == "月營收" and 營收表 is not None:
            r = 營收表[營收表["month"] == 期[:7]]
            去 = 營收表[營收表["month"] == f"{int(期[:4]) - 1}{期[4:7]}"] if 期[:4].isdigit() else 營收表.iloc[:0]
            if len(r):
                網年 = (float(r["revenue"].iloc[0]) / float(去["revenue"].iloc[0]) - 1) * 100 if len(去) else np.nan
                網 = float(r["revenue"].iloc[0]) / 1e5   # 千元 → 億元
                單 = str(c.get("單位", ""))
                換 = 1 / 100 if 單.startswith("百萬") else 1 / 1e5 if 單.startswith("千") else 1 / 1e4 if 單.startswith("萬") else 1
                ok = bool(網) and abs(值 * 換 / 網 - 1) < 0.03
                年 = _數(c.get("年增%"))
                if ok and not np.isnan(年) and not np.isnan(網年):
                    ok = abs(年 - 網年) < 1.5
                結果.append((f"{期[:7]} 月營收 {值:g}{c.get('單位', '')}" + (f"、年增 {年:+.1f}%" if not np.isnan(年) else ""),
                           "✅" if ok else "⚠️", f"網站 {網:.2f} 億" + (f"、年增 {網年:+.1f}%" if not np.isnan(網年) else "")))
        elif 項 == "收盤價" and 價格 is not None:
            d = pd.to_datetime(期, errors="coerce")
            r = 價格[價格["date"] == d] if pd.notna(d) else pd.DataFrame()
            if len(r):
                網 = float(r["收盤"].iloc[0])
                結果.append((f"{期} 收盤 {值:g}", "✅" if abs(值 / 網 - 1) < 0.005 else "⚠️", f"網站 {網:g}"))
    收 = _數(x.get("報告收盤價"))
    d = pd.to_datetime(x.get("日期"), errors="coerce")
    if not np.isnan(收) and 價格 is not None and pd.notna(d):
        前 = 價格[(價格["date"] <= d) & (價格["date"] >= d - pd.Timedelta(days=7))].sort_values("date")
        if len(前):
            近 = 前["收盤"].tail(2).tolist()
            ok = any(abs(收 / v - 1) < 0.005 for v in 近)
            結果.append((f"報告收盤價 {收:g}", "✅" if ok else "⚠️", f"網站報告日前後 {' / '.join(f'{v:g}' for v in 近)}"))
    return 結果


def 券商命中率(報告們, 價格們):
    """價格們＝{代號: 價格表}。依券商彙總：報告數、已達標、到期未達標、進行中、平均報酬%。"""
    列們 = []
    for x in 報告們:
        p = 價格們.get(str(x.get("代號")))
        if p is None:
            continue
        v = 驗收券商報告(x, p)
        if v["結果"] == "無目標價":
            continue
        列們.append({"券商": x.get("券商"), "結果": v["結果"], "報酬%": v["報酬%"], "看法": x.get("看法")})
    if not 列們:
        return pd.DataFrame()
    t = pd.DataFrame(列們)
    g = t.groupby("券商")
    表 = pd.DataFrame({"報告數": g.size(), "已達標": g["結果"].apply(lambda s: (s == "達標").sum()),
                      "到期未達標": g["結果"].apply(lambda s: (s == "到期未達標").sum()),
                      "進行中": g["結果"].apply(lambda s: (s == "進行中").sum()), "平均報酬%": g["報酬%"].mean().round(1)})
    已結 = 表["已達標"] + 表["到期未達標"]
    表["達標率%"] = (表["已達標"] / 已結.replace(0, np.nan) * 100).round(0)
    表["看多後平均%"] = t[t["看法"] == "看多"].groupby("券商")["報酬%"].mean().round(1).reindex(表.index)
    return 表.sort_values("報告數", ascending=False)


# ========== 28. 產業鏈位置（data/supply_chain.csv，手動維護） ==========
def 讀取產業鏈():
    f = 資料夾 / "supply_chain.csv"
    return pd.read_csv(f, dtype=str) if f.exists() else pd.DataFrame(columns=["chain", "stage", "group", "code"])


賺錢順序鏈 = {"玻璃基板"}   # Vic：設備與檢測 → 代工與材料 → 基板廠


def 產業鏈位置(代號, 名稱表=None):
    """回傳一段文字：這檔在哪條產業鏈的哪一段、同組有誰、上下游是哪些環節。名稱表＝{代號: 名稱}。"""
    t = 讀取產業鏈()
    我 = t[t["code"] == str(代號)]
    if 我.empty:
        return ""
    名 = lambda c: f"{(名稱表 or {}).get(c, '')}{c}"
    行 = []
    for _, r in 我.iterrows():
        鏈 = t[t["chain"] == r["chain"]]
        同 = 鏈[(鏈["group"] == r["group"]) & (鏈["code"] != r["code"])]["code"]
        段們 = sorted(x for x in 鏈["stage"].unique() if "支援" not in x)   # 製程支援（設備、耗材）服務各段，不算上下游
        if r["chain"] in 賺錢順序鏈:   # 新技術的鏈依建廠順序排，不是上下游
            行.append(f"{r['chain']} 產業鏈：{r['stage']}／{r['group']}"
                     + (f"；同組：{'、'.join(名(c) for c in 同)}" if len(同) else "")
                     + f"；賺錢順序：{' → '.join(段們)}（設備先收錢，基板廠要等量產）")
            continue
        if r["stage"] in 段們:
            i = 段們.index(r["stage"])
            上 = 段們[i - 1] if i > 0 else None
            下 = 段們[i + 1] if i + 1 < len(段們) else "終端應用"
        else:
            上, 下 = None, None
        行.append(f"{r['chain']} 產業鏈：{r['stage']}／{r['group']}"
                 + (f"；同組：{'、'.join(名(c) for c in 同)}" if len(同) else "")
                 + (f"；上游環節：{上}" if 上 else "") + (f"；下游環節：{下}" if 下 else ""))
    return "\n".join(行)


# ========== 29. 影片分析師的技術觀察：週線位置、KD、扣抵值、爆量 K 棒、買貴檢查、守週線強勢股 ==========
def 週收盤(K):
    """日 K 換成每週最後一個收盤（這週還沒結束就用最新收盤，跟看盤軟體一樣）。"""
    return K.set_index("date")["close"].resample("W-FRI").last().dropna()


def 關鍵均線(K):
    """影片裡常用的幾條線：5 日、10 日、72 日線，5 週、20 週、24 週線。回傳 [(名稱, 價位, 收盤距離%)]，資料不夠的略過。"""
    if K is None or len(K) < 20:
        return []
    c = K["close"]
    收 = float(c.iloc[-1])
    週 = 週收盤(K)
    線們 = [(f"{n} 日線", c, n) for n in (5, 10, 72)] + [(f"{n} 週線", 週, n) for n in (5, 20, 24)]
    return [(名, v, (收 / v - 1) * 100) for 名, s, n in 線們 if len(s) >= n for v in [float(s.tail(n).mean())]]


def KD(K, n=9):
    """台灣看盤軟體的 KD：9 日 RSV，K、D 各用 1/3 平滑（起始 50）。回傳 DataFrame[K, D]，index 跟 K 一樣。"""
    c = K["close"]
    高 = K["high"] if 有開高低(K) else c
    低 = K["low"] if 有開高低(K) else c
    區 = 高.rolling(n).max() - 低.rolling(n).min()
    rsv = ((c - 低.rolling(n).min()) / 區.replace(0, np.nan) * 100).fillna(50)
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    return pd.DataFrame({"K": k, "D": k.ewm(alpha=1 / 3, adjust=False).mean()})


def KD狀態(K):
    """KD 白話判讀（老王：低於 20 是超賣，但沒有黃金交叉就不算反轉）。回傳 dict(K, D, 燈, 狀態, 金叉, 死叉) 或 None。"""
    if K is None or len(K) < 30:
        return None
    t = KD(K)
    k, d, 昨k, 昨d = (float(v) for v in (t["K"].iloc[-1], t["D"].iloc[-1], t["K"].iloc[-2], t["D"].iloc[-2]))
    金叉, 死叉 = 昨k <= 昨d and k > d, 昨k >= 昨d and k < d
    if 金叉 and d < 30:
        燈, 話 = "🟢", "低檔黃金交叉：K 從超賣區往上穿過 D，是止跌的第一個訊號，還要價格站回 5 日線確認"
    elif 金叉:
        燈, 話 = "🟢", "黃金交叉：K 往上穿過 D，短線轉強"
    elif 死叉 and d > 70:
        燈, 話 = "🔴", "高檔死亡交叉：K 從過熱區往下穿過 D，短線漲多要休息"
    elif 死叉:
        燈, 話 = "🔴", "死亡交叉：K 往下穿過 D，短線轉弱"
    elif k < 20 and k < d:
        燈, 話 = "🟡", "超賣（低於 20）但還沒黃金交叉，跌勢還沒停，不要急著接"
    elif k < d:
        燈, 話 = "🔴", "K 在 D 下面，短線動能向下"
    elif k > 80:
        燈, 話 = "🟡", "過熱（高於 80）但還沒死亡交叉，強勢股常在這裡鈍化，不代表馬上會跌"
    else:
        燈, 話 = "🟢", "K 在 D 上面，短線動能向上"
    return {"K": k, "D": d, "燈": 燈, "狀態": 話, "金叉": 金叉, "死叉": 死叉}


def 扣抵(K, n=5):
    """均線扣抵值：明天要被扣掉的是 n 天前的收盤，明天收在它上面，n 日線就會往上彎。
    回傳 dict(扣抵, 接下來, 均線, 收盤, 上彎, 燈, 說明)；接下來＝往後 3 天要扣的收盤。"""
    if K is None or len(K) < n + 3:
        return None
    c = K["close"].reset_index(drop=True)
    收, 均 = float(c.iloc[-1]), float(c.tail(n).mean())
    扣 = float(c.iloc[-n])
    接 = [float(v) for v in c.iloc[-n:-n + 3]]
    上彎 = 均 > float(c.iloc[-n - 1:-1].mean())
    小數 = 0 if 收 > 1000 else 2
    f = lambda v: f"{v:,.{小數}f}"
    高扣 = sum(v > 收 for v in 接)
    話 = (f"明天收在 {f(扣)} 以上，{n} 日線（{f(均)}）就會往上彎；接下來 3 天要扣 {'、'.join(f(v) for v in 接)}，"
         + ("都比現在高（扣高），均線不容易翻揚，要漲上去才行" if 高扣 == 3 else
            "都比現在低（扣低），只要不再大跌，均線很快會翻揚" if 高扣 == 0 else "有高有低"))
    燈 = "🟢" if 上彎 and 收 >= 均 else ("🔴" if not 上彎 and 收 < 均 else "🟡")
    return {"扣抵": 扣, "接下來": 接, "均線": 均, "收盤": 收, "上彎": 上彎, "燈": 燈, "說明": 話}


def 爆量K棒(K, 量, 天數=60, 倍數=1.5):
    """近 天數 內成交最大的那根 K 棒（量要是前 20 日平均的 倍數 以上才算爆量）。
    老王：跌破爆量那天的低點＝那天買的人全被套，凶多吉少；站上高點＝套牢賣壓消化完。回傳 dict 或 None。"""
    if K is None or 量 is None or len(K) < 30:
        return None
    k = K.set_index("date")
    v = pd.Series(量).reindex(k.index).astype(float)
    if v.tail(天數).isna().all():
        return None
    均 = v.rolling(20, min_periods=10).mean().shift()
    d = v.tail(天數).idxmax()
    比 = float(v[d] / 均[d]) if pd.notna(均[d]) and 均[d] > 0 else np.nan
    if not (比 >= 倍數):
        return None
    高, 低 = (float(k.at[d, "high"]), float(k.at[d, "low"])) if 有開高低(K) else (float(k.at[d, "close"]),) * 2
    收 = float(k["close"].iloc[-1])
    if 收 < 低:
        燈, 話 = "🔴", "跌破爆量那天的低點，那天買的人全部套牢，凶多吉少；要重新站回低點才止跌"
    elif 收 > 高:
        燈, 話 = "🟢", "站上爆量那天的高點，套牢賣壓已經消化，換手成功"
    else:
        燈, 話 = "🟡", "在爆量 K 棒的高低點之間，跌破低點轉弱、站上高點轉強"
    return {"日期": d, "高": 高, "低": 低, "量": float(v[d]), "倍數": 比, "收盤": 收, "燈": 燈, "狀態": 話}


def 週線位置(K):
    """5 週、20 週、24 週線的位置燈號：站上 5 週線🟢；跌破 5 週線但守住 20 週線🟡；跌破 20 週線🔴（宏爺：容易轉成空方）。"""
    線 = {名: (v, 距) for 名, v, 距 in 關鍵均線(K)}
    if "20 週線" not in 線:
        return None
    收 = float(K["close"].iloc[-1])
    小數 = 0 if 收 > 1000 else 2
    在5 = 線.get("5 週線", (0, 1))[1] >= 0
    在20 = 線["20 週線"][1] >= 0
    燈 = "🟢" if 在5 and 在20 else ("🟡" if 在20 else "🔴")
    結論 = ("站上 5 週線，中短線都偏多" if 燈 == "🟢" else
           "跌破 5 週線但守住 20 週線，屬於中期多頭裡的回檔" if 燈 == "🟡" else
           "跌破 20 週線，中期轉弱，容易變成空方格局")
    說 = "、".join(f"{名} {v:,.{小數}f}（{距:+.1f}%）" for 名, (v, 距) in 線.items()) + f"。{結論}"
    return {"燈": 燈, "說明": 說, "結論": 結論}


def 技術觀察(K, 量=None):
    """首頁與個股頁的「分析師常用條件」燈號：週線位置、KD、5 日線扣抵、爆量 K 棒。回傳 [(名稱, 燈, 說明)]。"""
    if K is None or len(K) < 30:
        return []
    收 = float(K["close"].iloc[-1])
    小數 = 0 if 收 > 1000 else 2
    結果 = []
    週 = 週線位置(K)
    if 週:
        結果.append(("週線與 72 日線", 週["燈"], 週["說明"]))
    kd = KD狀態(K)
    if kd:
        結果.append(("KD 指標", kd["燈"], f"K {kd['K']:.0f}、D {kd['D']:.0f}：{kd['狀態']}"))
    扣 = 扣抵(K)
    if 扣:
        結果.append(("5 日線扣抵值", 扣["燈"], 扣["說明"]))
    爆 = 爆量K棒(K, 量)
    if 爆:
        結果.append(("爆量 K 棒", 爆["燈"], f"{爆['日期']:%m/%d} 量是前 20 日平均的 {爆['倍數']:.1f} 倍，"
                                        f"高 {爆['高']:,.{小數}f}／低 {爆['低']:,.{小數}f}：{爆['狀態']}"))
    return 結果


def 技術訊號(K, 量=None):
    """今天才發生的技術事件，給跌破站回條與 LINE：KD 低檔黃金交叉、跌破或站回爆量 K 棒低點。回傳 [(動作, 名稱, 價位或 None)]。"""
    結果 = []
    if K is None or len(K) < 31:
        return 結果
    kd = KD狀態(K)
    if kd and kd["金叉"] and kd["D"] < 30:
        結果.append(("出現", "KD 低檔黃金交叉", None))
    爆 = 爆量K棒(K.iloc[:-1], 量)   # 用昨天以前找爆量棒，今天才知道是不是剛跌破
    if 爆:
        今, 昨 = float(K["close"].iloc[-1]), float(K["close"].iloc[-2])
        名 = f"{爆['日期']:%m/%d} 爆量 K 低點"
        if 昨 >= 爆["低"] > 今:
            結果.append(("跌破", 名, 爆["低"]))
        elif 昨 < 爆["低"] <= 今:
            結果.append(("站回", 名, 爆["低"]))
    return 結果


def 買貴檢查(歷史, 天數=250):
    """宏爺「買貴欲哭無淚」：離一年內高點跌了多少、要漲多少才回得去、高點那天的本益比 vs 現在。
    歷史＝計算指標後的單一個股表（用實際股價，不還原）。回傳 dict 或 None。"""
    if 歷史 is None or len(歷史) < 60:
        return None
    h = 歷史.sort_values("date").tail(天數)
    高欄 = "high" if "high" in h and h["high"].notna().any() else "收盤"
    i = h[高欄].idxmax()
    高, 收 = float(h.at[i, 高欄]), float(h["收盤"].iloc[-1])
    if not (高 > 0 and 收 > 0):
        return None
    結果 = {"高點": 高, "高點日": h.at[i, "date"], "收盤": 收, "跌幅%": (收 / 高 - 1) * 100, "回前高%": (高 / 收 - 1) * 100,
            "高點本益比": None, "本益比": None}
    if "本益比" in h:
        前後 = h.loc[i:, "本益比"].dropna()
        if len(前後) and 前後.iloc[0] > 0:
            結果["高點本益比"] = float(前後.iloc[0])
        現 = h["本益比"].dropna()
        if len(現) and 現.iloc[-1] > 0:
            結果["本益比"] = float(現.iloc[-1])
    小數 = 0 if 收 > 1000 else 2
    話 = (f"一年內高點 {高:,.{小數}f}（{結果['高點日']:%Y/%m/%d}），現在 {收:,.{小數}f}，"
         f"跌了 {-結果['跌幅%']:.1f}%，要再漲 {結果['回前高%']:.1f}% 才回得去")
    if 結果["高點本益比"] and 結果["本益比"]:
        話 += f"。高點那天本益比 {結果['高點本益比']:.1f} 倍，現在 {結果['本益比']:.1f} 倍"
        if 結果["高點本益比"] > 200:
            話 += "（高點時獲利很少，本益比失真，改看股價淨值比比較準）"
        elif 結果["高點本益比"] >= 40:
            話 += "：高點時買的是很高的成長期待，期待降溫就算公司照樣賺錢，股價也可能好幾年回不去"
    結果["說明"] = 話
    return 結果


def 守週線強勢股(指標, 最少張數=1000, 檔數=30):
    """通勤族：大盤被壓在 5 週線下時，先找還守在自己 5 週線上的股票（相對大盤強）。
    用近 40 個交易日算每檔的 5 週線，回傳 DataFrame（距5週線%、20 日漲幅、產業），依 20 日漲幅排序。"""
    最近 = 指標[指標["date"] >= 指標["date"].drop_duplicates().nlargest(40).min()]
    最近 = 最近[最近["代號"].str.fullmatch(r"\d{4}")]
    週 = (最近.set_index("date").groupby("代號")["還原價"].resample("W-FRI").last().dropna())
    五週 = 週.groupby(level=0).apply(lambda s: s.tail(5).mean() if len(s) >= 5 else np.nan)
    今 = 最近[最近["date"] == 最近["date"].max()].set_index("代號")
    今 = 今[今["5日均量"] >= 最少張數]
    t = pd.DataFrame({"名稱": 今["名稱"], "收盤": 今["收盤"], "還原價": 今["還原價"], "5週線": 五週.reindex(今.index),
                      "20日漲幅": 今.get("20日漲幅"), "外資連買": 今.get("外資連買")})
    t["距5週線%"] = ((t["還原價"] / t["5週線"] - 1) * 100).round(1)
    t = t[t["距5週線%"] >= 0].dropna(subset=["5週線"])
    比 = (t["收盤"] / t["還原價"])   # 5 週線換回實際股價
    t["5週線"] = (t["5週線"] * 比).round(2)
    產 = _股本表()
    if "產業" in 產:
        t["產業"] = 產["產業"].reindex(t.index)
    return t.drop(columns="還原價").sort_values("20日漲幅", ascending=False).head(檔數)


def 技術觀察摘要(K, 量=None, 名稱=""):
    """給 AI 大盤解讀用的一行：週線位置、KD、扣抵值、爆量 K 棒。"""
    項們 = 技術觀察(K, 量)
    return f"{名稱}分析師常用條件：" + "；".join(f"{燈}{名}：{說}" for 名, 燈, 說 in 項們) if 項們 else ""


# ========== 30. 老王的停損紀律：破 5 日線減半、破 10 日線出清 ==========
def 停損紀律狀態(K):
    """老王的 SOP：收盤跌破 5 日線先賣一半，跌破 10 日線全部出清；站上 5、10、20 日線才算重新轉強。
    回傳 dict(燈, 建議, 說明, 今天) ；今天＝今天剛跌破／站回的那條線（給 LINE），沒有就是 None。"""
    if K is None or len(K) < 25:
        return None
    c = K["close"].reset_index(drop=True)
    均 = {n: c.rolling(n).mean() for n in (5, 10, 20)}
    收 = float(c.iloc[-1])
    在 = {n: 收 >= float(均[n].iloc[-1]) for n in 均}
    昨在 = {n: float(c.iloc[-2]) >= float(均[n].iloc[-2]) for n in 均}
    小數 = 0 if 收 > 1000 else 2
    f = lambda n: f"{float(均[n].iloc[-1]):,.{小數}f}"
    if not 在[10]:
        燈, 建議 = "🔴", "出清"
        說 = f"收盤在 10 日線 {f(10)} 下面：照老王的紀律，持股應該已經全部出清，等重新站上 5、10、20 日線再說"
    elif not 在[5]:
        燈, 建議 = "🟡", "減碼一半"
        說 = f"跌破 5 日線 {f(5)}、還守著 10 日線 {f(10)}：先賣一半，跌破 10 日線再全出"
    elif 在[20]:
        燈, 建議 = "🟢", "續抱"
        說 = f"站在 5 日 {f(5)}、10 日 {f(10)}、20 日線 {f(20)} 上面，紀律上可以續抱；停損看 5 日線 {f(5)}"
    else:
        燈, 建議 = "🟡", "觀察"
        說 = f"站回 5、10 日線但還在 20 日線 {f(20)} 下面，反彈還沒確認"
    今天 = None
    if 昨在[10] and not 在[10]:
        今天 = ("跌破", "10 日線（老王紀律：出清）", float(均[10].iloc[-1]))
    elif 昨在[5] and not 在[5]:
        今天 = ("跌破", "5 日線（老王紀律：減碼一半）", float(均[5].iloc[-1]))
    elif all(在.values()) and not all(昨在.values()):
        今天 = ("站回", "5、10、20 日線（老王紀律：重新轉強）", None)
    return {"燈": 燈, "建議": 建議, "說明": 說, "今天": 今天}


def 停損紀律回測(歷史, 年數=5):
    """這檔股票過去幾年用三種方式抱股的結果：一直抱著、只看 10 日線（全進全出）、老王紀律（破 5 日線減半、破 10 日線出清）。
    進場都是收盤站上 5、10、20 日線；訊號收盤產生，隔天收盤成交，已扣手續費與證交稅。回傳 DataFrame 或空表。"""
    if 歷史 is None or len(歷史) < 120:
        return pd.DataFrame()
    h = 歷史.sort_values("date").reset_index(drop=True)
    h = h[h["date"] >= h["date"].iloc[-1] - pd.DateOffset(years=年數)].reset_index(drop=True)
    p, r = h["還原價"], h["日報酬"].fillna(0).values
    m5, m10, m20 = (p.rolling(n).mean() for n in (5, 10, 20))
    強 = ((p > m5) & (p > m10) & (p > m20)).values
    破5, 破10 = (p < m5).values, (p < m10).values
    費, 稅 = 手續費率, 稅率(str(h["代號"].iloc[-1]) if "代號" in h else "")

    def 跑(規則):
        倉, 資產, 高, 回撤, 次 = 0.0, 1.0, 1.0, 0.0, 0
        目標 = 0.0
        for i in range(len(h)):
            資產 *= 1 + 倉 * r[i]
            if 目標 != 倉:   # 昨天收盤的訊號，今天收盤成交
                變 = 目標 - 倉
                資產 -= 資產 * abs(變) * (費 + (稅 if 變 < 0 else 0))
                次 += 變 > 0
                倉 = 目標
            高 = max(高, 資產)
            回撤 = min(回撤, 資產 / 高 - 1)
            目標 = 規則(i, 倉)
        return 資產, 回撤, 次

    def 只看十日(i, 倉):
        return 0.0 if 破10[i] else (1.0 if 強[i] else 倉)

    def 老王(i, 倉):
        if 破10[i]:
            return 0.0
        if 破5[i]:
            return min(倉, 0.5)
        return 1.0 if 強[i] or (倉 > 0 and not 破5[i]) else 倉

    列們 = []
    for 名, 規則 in (("一直抱著", lambda i, 倉: 1.0), ("只看 10 日線（全進全出）", 只看十日), ("老王紀律（破 5 日減半、破 10 日出清）", 老王)):
        資產, 回撤, 次 = 跑(規則)
        列們.append({"方法": 名, "總報酬%": round((資產 - 1) * 100, 1), "最大回檔%": round(回撤 * 100, 1), "進場次數": 次})
    t = pd.DataFrame(列們)
    t.attrs["起"] = h["date"].iloc[0]
    return t


# ========== 31. 網紅說法收件匣：貼上 Gemini 整理的影片重點，抓出股票與看法、紅旗、到期對答案 ==========
看法詞 = (("看空", "看空"), ("偏空", "看空"), ("看多", "看多"), ("偏多", "看多"))
紅旗規則 = (
    (r"賺了?\s*\d|帳上|大賺|會員.{0,6}賺|獲利\s*\d+\s*%", "用自己或會員的績效建立可信度"),
    (r"保證|穩賺|必漲|一定會漲|閉眼買", "保證獲利的用語"),
    (r"開戶|手續費|下載|定期定額|基金平台|業配|贊助|課程|訂閱", "可能有業配或推銷"),
)


def _段落(文字, 開頭, 結尾):
    m = re.search(開頭 + r"(.*?)(?=" + 結尾 + r"|\Z)", 文字, re.S)
    return m.group(1) if m else ""


def 解析影片整理(文字, 名稱表=None):
    """把照網站指令請 Gemini 整理的影片重點（一、基本資料 … 七、矛盾處）拆成結構化資料。
    名稱表＝{名稱: 代號}，影片沒講代號時用名稱找。回傳 dict(頻道, 日期, 股票, 條件數, 紅旗)；看不懂回傳 None。"""
    文字 = str(文字 or "")
    if "三、" not in 文字:
        return None
    頻道 = re.search(r"頻道[：:]\s*([^\n]+)", 文字)
    日 = re.search(r"日期[：:][^\n]*?(\d{4})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})", 文字)
    名稱表 = 名稱表 or {}
    股票 = []
    for 行 in _段落(文字, r"三、[^\n]*\n", r"\n\s*四、").splitlines():
        行 = 行.strip(" \t•*-·")
        前段 = re.split(r"[：:]", 行, maxsplit=1)
        if len(前段) == 2 and "、" in 前段[0]:   # 「8027 鈦昇、8064 東捷：中性偏多」一行好幾檔，拆開
            行們 = [f"{x.strip()}：{前段[1]}" for x in 前段[0].split("、") if x.strip()]
        else:
            行們 = [行]
        for 行 in 行們:
            股票 += _解析一行(行, 名稱表)
    return _整理影片(文字, 頻道, 日, 股票)


def _解析一行(行, 名稱表):
    """一行「代號 名稱（括號）：看法。理由：…」拆成一筆；沒有代號時用名稱表找。"""
    m = re.match(r"(?:\d+\.\s*)?(?:(\d{4,6}[A-Z]?)\s*)?([^：:（(]{1,20}?)\s*(?:[（(]([^）)]*)[）)])?\s*[：:]\s*(.+)", 行)
    if not m:
        return []
    代, 名, 括, 後 = m.groups()
    if not 代 and 括:
        找 = re.search(r"(?<!\d)(\d{4,6}[A-Z]?)(?!\d)", 括)
        代 = 找.group(1) if 找 else None
    名 = 名.strip()
    if not 代 and re.fullmatch(r"[A-Z]{1,5}", 括 or ""):
        代 = 括
    if not 代:
        代 = 名稱表.get(名) or 名稱表.get(名.replace("-KY", ""))
    看段 = 後.split("。")[0]
    看 = next((v for k, v in 看法詞 if k in 看段), "中立")
    理 = re.search(r"理由[：:]\s*(.+)", 後)
    return [{"代號": 代 or "", "名稱": 名, "看法": 看, "原文看法": 看段[:20], "理由": (理.group(1) if 理 else 後)[:120]}]


def _整理影片(文字, 頻道, 日, 股票):
    """算「如果…就…」條件數與紅旗，組成一支影片的紀錄。"""
    四 = _段落(文字, r"四、[^\n]*\n", r"\n\s*五、")
    條件數 = 0 if re.search(r"未出現|沒有出現", 四) else len(re.findall(r"如果", 四))
    正文 = 文字.split("七、")[0]   # 第七段是整理者自己的評論，不算影片內容
    紅旗 = [說 for 式, 說 in 紅旗規則 if re.search(式, 正文)]
    if 條件數 == 0:
        紅旗.append("沒有任何「如果…就…」條件，說錯了無法驗證")
    if len(股票) >= 5 and sum(x["看法"] == "看多" for x in 股票) / len(股票) >= 0.9:
        紅旗.append(f"點名 {len(股票)} 檔幾乎全部看多")
    if len(股票) >= 12:
        紅旗.append(f"一支影片點名 {len(股票)} 檔，每檔分析很淺")
    if 股票 and not re.search(r"支撐|壓力|停損|均線|目標價|\d+\s*元", _段落(文字, r"三、", r"\n\s*四、")):
        紅旗.append("沒有給任何價位或停損")
    return {"頻道": 頻道.group(1).strip() if 頻道 else "未知頻道",
            "日期": f"{日.group(1)}-{int(日.group(2)):02d}-{int(日.group(3)):02d}" if 日 else None,
            "股票": 股票, "條件數": 條件數, "紅旗": 紅旗}


def 拆開多支影片(文字):
    """一次貼好幾支時，用「一、」開頭切開。"""
    片們 = re.split(r"\n(?=[^\n]*\n?\s*一、[^\n]*頻道)", "\n" + str(文字))
    return [p for p in (x.strip() for x in 片們) if "三、" in p]


def 讀取網紅說法(設定):
    try:
        return (讀取設定檔(設定, "influencer_notes.json") or {}).get("影片", [])
    except Exception:
        return []


def 儲存網紅說法(設定, 影片們):
    return 儲存設定檔(設定, "influencer_notes.json", {"影片": 影片們}, f"網紅說法 {len(影片們)} 支")


def 合併網紅說法(舊, 新):
    鍵 = lambda x: (x.get("頻道"), x.get("日期"))
    表 = {鍵(x): x for x in 舊}
    for x in 新:
        表[鍵(x)] = x
    return sorted(表.values(), key=lambda x: str(x.get("日期") or ""), reverse=True)


def 網紅對答案(影片們, 價格們, 加權=None, 天數=20):
    """每一則看多／看空，影片日之後 天數 個交易日的報酬（不到期用最新），扣掉同期加權算超額報酬。
    看多且超額報酬 > 0、看空且 < 0 算說對。回傳 (明細 DataFrame, 依頻道彙總 DataFrame)。"""
    列們 = []
    加 = None
    if 加權 is not None and len(加權):
        加 = 加權.set_index("date")["close"]
    for v in 影片們:
        起 = pd.to_datetime(v.get("日期"), errors="coerce")
        if pd.isna(起):
            continue
        for x in v.get("股票", []):
            p = 價格們.get(str(x.get("代號")))
            if p is None or x.get("看法") not in ("看多", "看空"):
                continue
            p = p.sort_values("date")
            前, 後 = p[p["date"] <= 起], p[p["date"] > 起].head(天數)
            if not len(前):
                continue
            基 = float(前["收盤"].iloc[-1])
            if not len(後):
                列們.append({"頻道": v["頻道"], "日期": 起, "代號": x["代號"], "名稱": x["名稱"], "看法": x["看法"],
                           "天數": 0, "報酬%": np.nan, "超額%": np.nan, "結果": "等資料"})
                continue
            報 = (float(後["收盤"].iloc[-1]) / 基 - 1) * 100
            超 = 報
            if 加 is not None:
                a, b = 加[加.index <= 起], 加[加.index <= 後["date"].iloc[-1]]
                if len(a) and len(b):
                    超 = 報 - (float(b.iloc[-1]) / float(a.iloc[-1]) - 1) * 100
            對 = 超 > 0 if x["看法"] == "看多" else 超 < 0
            列們.append({"頻道": v["頻道"], "日期": 起, "代號": x["代號"], "名稱": x["名稱"], "看法": x["看法"],
                       "天數": len(後), "報酬%": round(報, 1), "超額%": round(超, 1),
                       "結果": ("說對" if 對 else "說錯") if len(後) >= 天數 else ("暫時對" if 對 else "暫時錯")})
    明細 = pd.DataFrame(列們)
    if 明細.empty:
        return 明細, pd.DataFrame()
    g = 明細.groupby("頻道")
    彙 = pd.DataFrame({"則數": g.size(), "到期": g["結果"].apply(lambda s: s.isin(["說對", "說錯"]).sum()),
                      "說對": g["結果"].apply(lambda s: (s == "說對").sum()),
                      "看多比例%": g["看法"].apply(lambda s: round((s == "看多").mean() * 100)),
                      "平均超額%": g["超額%"].mean().round(1)})
    彙["命中率%"] = (彙["說對"] / 彙["到期"].replace(0, np.nan) * 100).round(0)
    return 明細, 彙.sort_values("則數", ascending=False)


# ========== 32. 殺估值觀察組：高本益比領頭股還有沒有在破底 ==========
殺估值觀察 = {"2383": "台光電", "6274": "台燿", "6213": "聯茂", "2308": "台達電", "2327": "國巨", "LITE": "Lumentum"}


def 殺估值觀察組(指標, 美股=None, 名單=殺估值觀察):
    """通勤族：高本益比的領頭股「不再創新低」，殺估值才可能告一段落。
    每檔看近 5 日低點有沒有低於前 20 日低點（還在破底）、距 60 日高點跌多少、本益比從 60 日內最高降了多少。
    回傳 (DataFrame, 燈, 白話)。"""
    列們 = []
    for 代, 名 in 名單.items():
        if 代.isdigit():
            h = 指標[指標["代號"] == 代].sort_values("date").tail(60)
            if len(h) < 30:
                continue
            價 = h["還原價"]
            低 = h["low"] * h["還原價"] / h["收盤"] if "low" in h else 價
            本 = h["本益比"].where(h["本益比"] > 0)
            本降 = (float(本.iloc[-1]) / float(本.max()) - 1) * 100 if 本.notna().any() and pd.notna(本.iloc[-1]) else np.nan
        else:
            if 美股 is None or 名 not in 美股:
                continue
            價 = 美股[名].dropna().tail(60)
            if len(價) < 30:
                continue
            低, 本降 = 價, np.nan
        破底 = float(低.tail(5).min()) < float(低.iloc[-25:-5].min())
        列們.append({"代號": 代, "名稱": 名, "還在破底": "是" if 破底 else "否",
                   "距60日高%": round((float(價.iloc[-1]) / float(價.max()) - 1) * 100, 1),
                   "本益比降幅%": round(本降, 1) if pd.notna(本降) else np.nan})
    t = pd.DataFrame(列們)
    if t.empty:
        return t, "", ""
    停 = int((t["還在破底"] == "否").sum())
    燈 = "🟢" if 停 >= len(t) * 2 / 3 else ("🔴" if 停 <= len(t) / 3 else "🟡")
    話 = (f"{len(t)} 檔高本益比領頭股有 {停} 檔不再破底"
         + ("，殺估值可能告一段落" if 燈 == "🟢" else "，殺估值還在進行" if 燈 == "🔴" else "，有止跌跡象但還沒全面"))
    return t, 燈, 話


def 殺估值摘要(指標, 美股=None):
    t, 燈, 話 = 殺估值觀察組(指標, 美股)
    if t.empty:
        return ""
    return (f"【殺估值觀察組】{燈}{話}：" + "、".join(
        f"{r['名稱']} {'破底中' if r['還在破底'] == '是' else '止跌'}（距 60 日高 {r['距60日高%']:+.0f}%"
        + (f"、本益比降 {-r['本益比降幅%']:.0f}%" if pd.notna(r["本益比降幅%"]) else "") + "）" for _, r in t.iterrows()))


def 價位可靠度(價位, 摘要, 區們=None):
    """把回測的守住率貼到每一條價位上：支撐看「支撐守住%」、壓力看「壓力守住%」，用這條線自己的方法（均線、缺口…）。
    回傳 (守住% Series, 比隨機 Series)，index 跟 價位 一樣；比隨機＝守住% − 隨機對照同角色的守住%。"""
    if 摘要 is None or len(摘要) == 0:
        空 = pd.Series(np.nan, index=價位.index)
        return 空, 空
    基 = 摘要.set_index("方法")
    守們, 比們 = [], []
    for _, r in 價位.iterrows():
        欄 = "支撐守住%" if r["角色"] == "支撐" else "壓力守住%"
        守 = 基.at[r["類別"], 欄] if r["類別"] in 基.index and 基.at[r["類別"], "測試次數"] >= 20 else np.nan
        隨 = 基.at["隨機對照", 欄] if "隨機對照" in 基.index else np.nan
        守們.append(守)
        比們.append(守 - 隨 if pd.notna(守) and pd.notna(隨) else np.nan)
    return pd.Series(守們, index=價位.index), pd.Series(比們, index=價位.index)


# ========== 交易日記（加密後存 ai-reports 分支 journal.json） ==========
日記檔 = "journal.json"


def _日記金鑰(密碼, 鹽):
    import hashlib
    k = hashlib.pbkdf2_hmac("sha256", str(密碼).encode("utf-8"), 鹽, 200_000, dklen=64)
    return k[:32], k[32:]


def _金鑰流(金鑰, 隨機, 長度):
    import hashlib, hmac
    流 = bytearray()
    i = 0
    while len(流) < 長度:
        流 += hmac.new(金鑰, 隨機 + i.to_bytes(8, "big"), hashlib.sha256).digest()
        i += 1
    return bytes(流[:長度])


def 加密(內容物, 密碼):
    """HMAC-SHA256 計數器模式加密＋驗證碼（公開分支上的人只看得到亂碼）。"""
    import base64, hashlib, hmac, json, os
    鹽, 隨機 = os.urandom(16), os.urandom(16)
    加, 驗 = _日記金鑰(密碼, 鹽)
    明 = json.dumps(內容物, ensure_ascii=False).encode("utf-8")
    密 = bytes(a ^ b for a, b in zip(明, _金鑰流(加, 隨機, len(明))))
    碼 = hmac.new(驗, 鹽 + 隨機 + 密, hashlib.sha256).digest()
    b = lambda x: base64.b64encode(x).decode()
    return {"加密": 1, "鹽": b(鹽), "隨機": b(隨機), "內容": b(密), "驗證": b(碼)}


def 解密(包, 密碼):
    import base64, hashlib, hmac, json
    if not 包.get("加密"):
        return 包
    鹽, 隨機, 密, 碼 = (base64.b64decode(包[k]) for k in ("鹽", "隨機", "內容", "驗證"))
    加, 驗 = _日記金鑰(密碼, 鹽)
    if not hmac.compare_digest(碼, hmac.new(驗, 鹽 + 隨機 + 密, hashlib.sha256).digest()):
        raise ValueError("密碼不對，交易日記解不開")
    return json.loads(bytes(a ^ b for a, b in zip(密, _金鑰流(加, 隨機, len(密)))).decode("utf-8"))


def 讀取日記(設定):
    包 = 讀取設定檔(設定, 日記檔)
    if not 包:
        return {"交易": [], "當作庫存": False}
    return 解密(包, 設定.get("password", "")) if 包.get("加密") else 包


def 儲存日記(日記, 設定):
    密碼 = str(設定.get("password", ""))
    return 儲存設定檔(設定, 日記檔, 加密(日記, 密碼) if 密碼 else 日記, "更新交易日記")


def 交易費用(代號, 買賣, 股數, 價格, 折扣=1.0):
    """回傳 (手續費, 證交稅)；手續費最低 20 元（零股 1 元）。"""
    金額 = 股數 * 價格
    費 = max(round(金額 * 手續費率 * 折扣), 20 if 股數 >= 1000 else 1)
    稅 = round(金額 * 稅率(代號)) if 買賣 == "賣" else 0
    return 費, 稅


def 交易日記統計(交易們, 現價=None):
    """先進先出配對。回傳 (已實現表, 庫存表[代號,股數,總成本], 摘要 dict)。"""
    現價 = 現價 or {}
    批 = {}  # 代號 → [[剩餘股數, 每股成本(含手續費), 買進日]]
    已實現 = []
    for t in sorted(交易們, key=lambda x: (x["日期"], 0 if x["買賣"] == "買" else 1)):
        代, 股, 價 = str(t["代號"]), float(t["股數"]), float(t["價格"])
        費, 稅 = float(t.get("手續費") or 0), float(t.get("稅") or 0)
        if t["買賣"] == "買":
            批.setdefault(代, []).append([股, (股 * 價 + 費) / 股, pd.Timestamp(t["日期"])])
            continue
        剩, 成本, 天數 = 股, 0.0, 0.0
        for b in 批.get(代, []):
            if 剩 <= 0:
                break
            用 = min(b[0], 剩)
            成本 += 用 * b[1]
            天數 += 用 * (pd.Timestamp(t["日期"]) - b[2]).days
            b[0] -= 用
            剩 -= 用
        批[代] = [b for b in 批.get(代, []) if b[0] > 0]
        配到 = 股 - 剩
        if 配到 <= 0:
            continue
        收入 = 配到 * 價 - (費 + 稅) * 配到 / 股
        已實現.append({"賣出日": t["日期"], "代號": 代, "股數": 配到, "買進均價": round(成本 / 配到, 2), "賣出價": 價,
                    "損益": round(收入 - 成本), "報酬率(%)": round((收入 / 成本 - 1) * 100, 2) if 成本 else np.nan,
                    "持有天數": round(天數 / 配到), "理由": t.get("理由", "")})
    庫存 = pd.DataFrame([{"代號": c, "股數": sum(b[0] for b in v), "總成本": round(sum(b[0] * b[1] for b in v))}
                       for c, v in 批.items() if sum(b[0] for b in v) > 0], columns=["代號", "股數", "總成本"])
    實 = pd.DataFrame(已實現, columns=["賣出日", "代號", "股數", "買進均價", "賣出價", "損益", "報酬率(%)", "持有天數", "理由"])
    賺 = 實[實["損益"] > 0]
    賠 = 實[實["損益"] <= 0]
    摘要 = {
        "已實現損益": float(實["損益"].sum()), "賣出筆數": len(實),
        "勝率": len(賺) / len(實) * 100 if len(實) else np.nan,
        "平均持有天數": float(實["持有天數"].mean()) if len(實) else np.nan,
        "平均賺": float(賺["損益"].mean()) if len(賺) else np.nan,
        "平均賠": float(賠["損益"].mean()) if len(賠) else np.nan,
        "未實現損益": float(sum(r["股數"] * 現價[r["代號"]] - r["總成本"] for _, r in 庫存.iterrows() if r["代號"] in 現價)),
    }
    摘要["賺賠比"] = (摘要["平均賺"] / -摘要["平均賠"]) if 摘要["平均賠"] and 摘要["平均賠"] < 0 and pd.notna(摘要["平均賺"]) else np.nan
    return 實, 庫存, 摘要


def 停損目標檢查(交易們, 庫存, 現價):
    """還持有的股票，最近一筆買進記下的停損價、目標價，跟現價比。"""
    列們 = []
    for 代 in 庫存["代號"]:
        買們 = [t for t in 交易們 if str(t["代號"]) == 代 and t["買賣"] == "買"]
        if not 買們 or 代 not in 現價:
            continue
        有設 = [t for t in 買們 if t.get("停損") or t.get("目標")]
        t = max(有設 or 買們, key=lambda x: x["日期"])
        價 = 現價[代]
        停, 目 = t.get("停損"), t.get("目標")
        狀態 = ("⚠️ 已跌破停損" if 停 and 價 <= 停 else "🎯 已到目標" if 目 and 價 >= 目 else "持有中")
        列們.append({"代號": 代, "現價": 價, "停損": 停 or np.nan, "距停損%": round((價 / 停 - 1) * 100, 1) if 停 else np.nan,
                   "目標": 目 or np.nan, "距目標%": round((目 / 價 - 1) * 100, 1) if 目 else np.nan,
                   "狀態": 狀態, "買進理由": t.get("理由", "")})
    return pd.DataFrame(列們)


# ========== 庫存風險體檢 ==========
def 庫存風險(持股, 指標, 指數收盤, 產業表=None, 天數=250, 名稱表=None):
    """持股：代號、股數。回傳 dict：占比表、產業表、Beta、大盤跌 10% 估計、最大單日跌幅、相關最高的組合、提醒。"""
    股數 = 持股.assign(代號=持股["代號"].astype(str).str.strip()).groupby("代號")["股數"].sum()
    寬 = 指標[指標["代號"].isin(股數.index)].pivot_table(index="date", columns="代號", values="還原價").sort_index()
    收 = 指標[指標["代號"].isin(股數.index)].pivot_table(index="date", columns="代號", values="收盤").sort_index()
    if 寬.empty:
        return None
    最新 = 收.ffill().iloc[-1]
    市值 = (最新 * 股數.reindex(最新.index)).dropna()
    市值 = 市值[市值 > 0]
    權 = 市值 / 市值.sum()
    報 = 寬[權.index].pct_change().tail(天數)
    大 = 指數收盤.sort_index().pct_change().reindex(報.index)
    beta = {}
    for c in 權.index:
        x = pd.concat([報[c], 大], axis=1).dropna()
        beta[c] = float(x.iloc[:, 0].cov(x.iloc[:, 1]) / x.iloc[:, 1].var()) if len(x) >= 60 and x.iloc[:, 1].var() > 0 else np.nan
    beta = pd.Series(beta)
    組合 = (報.fillna(0) * 權).sum(axis=1)
    淨值 = (1 + 組合).cumprod()
    產 = pd.Series({c: ("ETF" if c.startswith("00") else ((產業表 or {}).get(c) or "其他")) for c in 權.index})
    產業 = 權.groupby(產).sum().sort_values(ascending=False)
    占比 = pd.DataFrame({"市值": 市值.round(), "占比%": (權 * 100).round(1), "Beta": beta.round(2), "產業": 產})
    占比 = 占比.sort_values("占比%", ascending=False)
    組Beta = float((beta.fillna(1) * 權).sum())
    相關 = 報.corr()
    對們 = [(a, b, 相關.at[a, b]) for i, a in enumerate(相關.columns) for b in 相關.columns[i + 1:] if pd.notna(相關.at[a, b])]
    對們 = sorted(對們, key=lambda x: -x[2])[:3]
    提醒 = []
    名 = lambda c: f"{c} {(名稱表 or {}).get(c, '')}".strip()
    if len(占比) and 占比["占比%"].iloc[0] > 30:
        提醒.append(f"單一股票 {名(占比.index[0])} 占 {占比['占比%'].iloc[0]:.0f}%，超過 3 成，這檔一跌整體就跟著大跌。")
    if len(產業) and 產業.iloc[0] > 0.5 and 產業.index[0] != "ETF":
        提醒.append(f"「{產業.index[0]}」占 {產業.iloc[0] * 100:.0f}%，超過一半集中在同一個產業。")
    if 組Beta > 1.2:
        提醒.append(f"整體 Beta {組Beta:.2f}，大盤跌 1% 你的庫存平均跌 {組Beta:.1f}%，比大盤更敏感。")
    if 對們 and 對們[0][2] > 0.8:
        提醒.append(f"{名(對們[0][0])} 和 {名(對們[0][1])} 走勢高度同步（相關 {對們[0][2]:.2f}），分散效果有限。")
    return {"占比": 占比, "產業": 產業, "Beta": 組Beta, "跌10%": 市值.sum() * 組Beta * -0.10,
            "最大單日": float(組合.min()) if len(組合) else np.nan, "最大單日日": 組合.idxmin() if len(組合) else None,
            "最大回撤": float((淨值 / 淨值.cummax() - 1).min()) if len(淨值) else np.nan,
            "大盤最大回撤": float(((1 + 大.fillna(0)).cumprod() / (1 + 大.fillna(0)).cumprod().cummax() - 1).min()),
            "相關": 對們, "提醒": 提醒, "市值": float(市值.sum()), "天數": len(報)}


# ========== 策略總排行榜：所有內建策略用同一套方法比 ==========
def 策略排行(指標, 往後們=(5, 20), 間隔=5, 起=60):
    """每隔 N 個交易日，看各策略當天選出的股票，之後 5、20 日的平均報酬，跟同期全部股票平均比。
    只用股價與籌碼條件（基本面只有最新一期，會偷看未來，所以「低價成長股」不列）。"""
    日們 = sorted(指標["date"].unique())
    最長 = max(往後們)
    取樣 = 日們[起:len(日們) - 最長:間隔]
    寬 = 指標.pivot_table(index="date", columns="代號", values="還原價").sort_index()
    位置 = {d: i for i, d in enumerate(寬.index)}
    策略們 = {名: (設["方向"], 設["條件"]) for 名, 設 in 烏賊條件.items() if "營收創新高" not in 設["條件"]}
    功課 = {"三&五日強勢股": "多", "三&五日弱勢股": "空", "量大股": "多", "大幅震盪股": "多", "強勢股": "多", "弱勢股": "空"}
    列們 = []
    for d in 取樣:
        當日 = 指標[指標["date"] == d]
        i = 位置[d]
        if i + 最長 >= len(寬):
            continue
        今 = 寬.iloc[i]
        後 = {n: 寬.iloc[i + n] / 今 - 1 for n in 往後們}
        全 = {n: 後[n][~後[n].index.str.startswith("00")].clip(-0.9, 3).mean() for n in 往後們}
        名單們 = {名: (方向, 選股(當日, dict(條件, 排除ETF=True))["代號"]) for 名, (方向, 條件) in 策略們.items()}
        for 名, 表 in 每日功課(當日).items():
            名單們["功課：" + 名] = (功課[名], 表["代號"])
        for 名, (方向, 代號們) in 名單們.items():
            代號們 = [c for c in 代號們 if c in 今.index]
            if not 代號們:
                continue
            列 = {"策略": 名, "多空": 方向, "日期": d, "檔數": len(代號們)}
            for n in 往後們:
                r = 後[n].reindex(代號們).clip(-0.9, 3).dropna()
                列[f"{n}日報酬"] = r.mean() * 100
                列[f"{n}日超額"] = (r.mean() - 全[n]) * 100
                列[f"{n}日對的比例"] = ((r > 0) if 方向 == "多" else (r < 0)).mean() * 100
                列[f"{n}日有用"] = 列[f"{n}日超額"] if 方向 == "多" else -列[f"{n}日超額"]
            列們.append(列)
    明細 = pd.DataFrame(列們)
    if 明細.empty:
        return 明細, 明細
    n = 最長
    總 = 明細.groupby(["策略", "多空"]).agg(
        出現次數=("日期", "size"), 平均檔數=("檔數", "mean"),
        **{f"{k}日平均報酬%": (f"{k}日報酬", "mean") for k in 往後們},
        **{f"{k}日超額%": (f"{k}日超額", "mean") for k in 往後們},
        **{f"{n}日方向對%": (f"{n}日對的比例", "mean")},
        **{f"{n}日贏過大盤次數%": (f"{n}日有用", lambda s: (s > 0).mean() * 100)},
        有用程度=(f"{n}日有用", "mean")).reset_index()
    # 空方策略：選出來的股票越弱越好，所以「有用程度」＝多方看超額、空方看超額的相反數
    總 = 總.sort_values("有用程度", ascending=False).round(2)
    總["平均檔數"] = 總["平均檔數"].round(1)
    return 總, 明細


# ========== 自訂評分權重 ==========
def 加權總分(分, 權重):
    """分：含 技術、籌碼、基本、市場 欄；沒資料的面向不算，權重按比例重分。"""
    權 = pd.DataFrame({面: 分[面].notna() * w for 面, w in 權重.items()})
    return ((分[list(權重)].fillna(0) * 權).sum(axis=1) / 權.sum(axis=1).replace(0, np.nan)).round(1)


def 讀取評分回測明細():
    f = 資料夾 / "score_backtest_detail.csv.gz"
    return pd.read_csv(f, dtype={"代號": str}, parse_dates=["date"]) if f.exists() else None


def 權重驗證(明細, 權重):
    """用歷史每月分數，算這組權重的 IC（分數排名和之後 20 日報酬排名的相關）與五分組超額報酬。"""
    t = 明細.assign(總分=加權總分(明細, 權重)).dropna(subset=["總分", "報酬"])
    t["超額"] = t["報酬"] - t.groupby("date")["報酬"].transform("mean")
    ic = t.groupby("date")[["總分", "報酬"]].apply(lambda g: g["總分"].rank().corr(g["報酬"].rank())).dropna()
    組 = t.groupby("date")["總分"].transform(lambda x: pd.qcut(x.rank(method="first"), 5, labels=False)) + 1
    五 = t.groupby(組)["超額"].mean().round(2)
    return {"IC": float(ic.mean()), "t": float(ic.mean() / ic.std() * np.sqrt(len(ic))) if ic.std() > 0 else np.nan,
            "IC為正": float((ic > 0).mean()), "五分組": 五, "期數": len(ic), "高減低": float(五.iloc[-1] - 五.iloc[0])}


# ========== 股利收入預估 ==========
def 股利預估(持股, 年=None):
    """今年每檔已除息、即將除息（已公告）的現金股利；去年同期有配、今年還沒公告的，用最近一次的金額估。
    單次入帳超過 2 萬元要扣 2.11% 二代健保補充保費。"""
    年 = 年 or pd.Timestamp.now().year
    股數 = 持股.assign(代號=持股["代號"].astype(str).str.strip()).groupby("代號")["股數"].sum()
    已 = 讀取全部除權息()
    已 = 已[已["code"].isin(股數.index) & (已["type"] != "權")].copy()
    # 交易所的「權值＋息值」：只有息時就是現金股利；權息合併的用合計值估（含配股價值）
    已["cash"] = 已["cash"].fillna(已["value"])
    預 = 讀取全部除權息(預告=True)
    預 = 預[預["code"].isin(股數.index) & (預["date"].dt.year == 年)]
    列們 = []
    今 = pd.Timestamp.now().normalize()
    for c, n in 股數.items():
        今年 = 已[(已["code"] == c) & (已["date"].dt.year == 年)]
        去年 = 已[(已["code"] == c) & (已["date"].dt.year == 年 - 1)]
        即將 = 預[(預["code"] == c) & (預["date"] >= 今) & ~預["date"].isin(今年["date"])]
        for _, r in 今年.iterrows():
            列們.append({"代號": c, "除息日": r["date"], "每股": r["cash"], "狀態": "已除息"})
        for _, r in 即將.iterrows():
            列們.append({"代號": c, "除息日": r["date"], "每股": r["cash"], "狀態": "已公告"})
        # 去年同一季以後、今年還沒出現的配息次數，用去年金額估（季配、半年配也適用）
        已有月 = set(今年["date"].dt.month) | set(即將["date"].dt.month)
        for _, r in 去年.iterrows():
            if r["date"].replace(year=年) < 今 or any(abs(m - r["date"].month) <= 1 for m in 已有月):
                continue
            最近 = 已[已["code"] == c].sort_values("date")["cash"].dropna()
            列們.append({"代號": c, "除息日": r["date"].replace(year=年), "每股": 最近.iloc[-1] if len(最近) else r["cash"],
                       "狀態": "估計（照最近一次金額）"})
    t = pd.DataFrame(列們, columns=["代號", "除息日", "每股", "狀態"])
    if t.empty:
        return t
    t["股數"] = t["代號"].map(股數)
    t["金額"] = (t["每股"].fillna(0) * t["股數"]).round()
    t["補充保費"] = np.where(t["金額"] >= 20000, (t["金額"] * 0.0211).round(), 0)
    return t.sort_values("除息日")


# ========== 部位大小 ==========
def 部位建議(資金, 風險比例, 進場, 停損, 代號="", 折扣=1.0):
    """停損出場時最多只賠 資金 × 風險比例：股數 ＝ 可賠金額 ÷ 每股風險（含買賣手續費與證交稅）。"""
    if 進場 <= 0 or 停損 <= 0 or 停損 >= 進場:
        return None
    每股風險 = 進場 - 停損 + 進場 * 手續費率 * 折扣 + 停損 * (手續費率 * 折扣 + 稅率(代號))
    可賠 = 資金 * 風險比例
    股數 = int(可賠 // 每股風險)
    股數 = min(股數, int(資金 // (進場 * (1 + 手續費率 * 折扣))))  # 錢不夠就以全部資金為上限
    return {"股數": 股數, "張": 股數 // 1000, "零股": 股數 % 1000, "金額": 股數 * 進場,
            "占資金%": 股數 * 進場 / 資金 * 100 if 資金 else np.nan, "最多虧損": 股數 * 每股風險,
            "可賠": 可賠, "每股風險": 每股風險, "停損幅度%": (停損 / 進場 - 1) * 100}


# ========== 定期定額 ==========
def 定期定額(歷史, 每月, 扣款日=6, 開始=None, 結束=None, 折扣=1.0):
    """每月扣款日（遇假日順延）買進（可買零股），現金股利自動再投入（用還原價計算，分割、減資也不會算錯）。
    回傳 (每日曲線, 摘要)；另算「第一天就把總投入一次買進」做比較。"""
    h = 歷史.sort_values("date").set_index("date")
    if 開始 is not None:
        h = h[h.index >= pd.Timestamp(開始)]
    if 結束 is not None:
        h = h[h.index <= pd.Timestamp(結束)]
    還 = h["還原價"].dropna()
    if len(還) < 2:
        return None, None
    扣款日們 = []
    for _, g in pd.Series(還.index, index=還.index).groupby(還.index.to_period("M")):
        候 = g[g.dt.day >= 扣款日]
        if len(候):
            扣款日們.append(候.iloc[0])
    費率 = 手續費率 * 折扣
    買 = pd.Series(0.0, index=還.index)
    for d in 扣款日們:
        買[d] = (每月 - max(每月 * 費率, 1)) / 還[d]
    單位 = 買.cumsum()
    投入 = pd.Series(0.0, index=還.index)
    投入[扣款日們] = 每月
    曲 = pd.DataFrame({"投入": 投入.cumsum(), "市值": 單位 * 還})
    總 = float(曲["投入"].iloc[-1])
    曲["一次投入"] = 總 * (1 - 費率) / 還.iloc[0] * 還  # 同樣的總金額第一天全買
    流 = [(d, -每月) for d in 扣款日們] + [(曲.index[-1], float(曲["市值"].iloc[-1]))]
    def npv(r):
        return sum(v / (1 + r) ** ((d - 流[0][0]).days / 365) for d, v in 流)
    低, 高 = -0.99, 10.0
    for _ in range(100):  # 二分法求 XIRR（考慮每筆錢投入的時間）
        中 = (低 + 高) / 2
        低, 高 = (中, 高) if npv(中) > 0 else (低, 中)
    年數 = (曲.index[-1] - 曲.index[0]).days / 365
    市值 = float(曲["市值"].iloc[-1])
    一次 = float(曲["一次投入"].iloc[-1])
    return 曲, {"扣款次數": len(扣款日們), "總投入": 總, "市值": 市值,
               "報酬率%": (市值 / 總 - 1) * 100 if 總 else np.nan, "年化%": 中 * 100,
               "一次投入市值": 一次, "一次投入報酬率%": (一次 / 總 - 1) * 100 if 總 else np.nan,
               "一次投入年化%": ((一次 / 總) ** (1 / 年數) - 1) * 100 if 總 and 年數 > 0 else np.nan,
               "最大回檔%": float((曲["市值"] / 曲["市值"].cummax() - 1).min() * 100),
               "一次投入最大回檔%": float((曲["一次投入"] / 曲["一次投入"].cummax() - 1).min() * 100)}


# ========== 名詞小辭典（網站上方「📖 名詞」） ==========
名詞表 = {
    "P/C ratio": "選擇權賣權未平倉量 ÷ 買權未平倉量。台灣常見解讀：超過 100% 偏多（有人大量賣出賣權當支撐）、低於 80% 偏空。",
    "選擇權最大未平倉": "買權未平倉最多的履約價常被當成壓力、賣權最多的當成支撐，越接近結算日越有參考性。",
    "外資持股比": "外資持有的股數 ÷ 公司發行股數。持續上升代表外資長線布局，比單日買賣超更能看出趨勢。",
    "當沖比率": "當天買進又賣出（當日沖銷）的成交量 ÷ 總成交量。比率很高代表短線客多，股價容易暴漲暴跌。",
    "自由現金流": "公司本業賺進的現金（營業現金流）扣掉投資支出後剩下的錢，可以拿來配息、還債。網站用「營業＋投資現金流」簡單估算。",
    "合約負債": "公司已經收款、還沒交貨的預收款（舊稱預收款項），交貨後才轉成營收，常當成未來一兩季營收的領先指標。網站看年增率與「能見度」（合約負債 ÷ 近四季營收 × 12，約等於幾個月營收）。台積電、鴻海等很多公司沒有單獨列這行。",
    "負債比": "總負債 ÷ 總資產。一般產業超過 60～70% 要留意；銀行、保險本來就很高，不能直接比。",
    "庫藏股": "公司拿錢從市場買回自家股票，通常代表公司認為股價偏低，也有護盤效果。",
    "可轉債": "可以轉換成股票的公司債。股價高於轉換價時債券持有人會轉成股票，股本會被稀釋。",
    "支撐／壓力": "股價跌到某個價位常會止跌（支撐）、漲到某個價位常會賣壓出現（壓力）。網站用前波高低點、缺口、成交密集區、整數關卡自動找。",
    "共振區": "兩種以上方法算出的支撐或壓力剛好重疊在附近，通常比單一條線更有參考價值。",
    "缺口": "今天最低價比昨天最高價還高（向上缺口），或今天最高價比昨天最低價還低（向下缺口）。沒被回補的缺口常變成支撐或壓力。",
    "黑 K 一半": "一根大黑 K 的一半價位。之後反彈站不回這一半，代表賣壓還重。",
    "分價量": "過去一段時間，每個價位累積成交了多少量。量最大的價位（成交密集區）常是支撐或壓力。",
    "均線": "最近 N 天收盤價的平均。5 日（週線）、20 日（月線）、60 日（季線）、240 日（年線）。股價在均線上方表示短期偏強。",
    "扣抵值": "均線明天要拿掉的那一天的價格。今天股價高於扣抵值，均線就會往上彎。",
    "KD": "隨機指標，0～100。K 由下往上穿過 D 叫黃金交叉（轉強），反過來叫死亡交叉；80 以上偏熱、20 以下偏冷。",
    "RSI": "相對強弱指標，0～100，看一段時間內上漲力道占多少。70 以上常被認為過熱，30 以下超賣。",
    "量比": "今天成交量 ÷ 過去幾天的平均量。大於 1.5 代表明顯放量。",
    "週轉率": "今天成交股數 ÷ 發行股數。越高代表換手越熱絡，小型股常見 10% 以上。",
    "三大法人": "外資、投信、自營商。網站的「法人買超」是三者合計買進減賣出的張數。",
    "土洋對作": "外資和投信方向相反（一個買、一個賣），而且連續好幾天。",
    "融資": "跟券商借錢買股票，通常代表散戶加槓桿。融資大增但股價不漲，常被視為籌碼變亂。",
    "個股融資維持率": "網站估算值：用每天融資餘額變化推融資平均成本，維持率 ≈ 收盤 ÷（成本 × 60%，上櫃 50%）。交易所不公布個股數字，跟大盤實際值比對，估算可能偏高 2～15 個百分點，看高低級距就好。",
    "融資洗完": "股價距 52 週高點跌超過 30%，而且融資 20 日減少超過 15% 或維持率 20 日內跌破過 130%（融資被追繳、斷頭過）。實測之後 60 日比大家略好；跌深但融資還在增加（接刀風險）最差。",
    "融資維持率": "融資戶擔保品市值 ÷ 借款。低於 130% 會被追繳，大盤維持率低於 140% 常代表散戶被洗得差不多了；170% 以上算安全。",
    "借券賣出": "借別人的股票來賣，等跌了再買回還。餘額增加代表看空的人變多。",
    "千張大戶": "持有 1,000 張以上的股東合計持股比例（集保每週公布）。比例上升通常代表籌碼往大戶集中。",
    "本益比": "股價 ÷ 每股盈餘（EPS）。代表用幾年的獲利回本，數字越低越便宜，但要跟同產業、自己的歷史比。",
    "股價淨值比": "股價 ÷ 每股淨值。金融、營建、景氣循環股常用這個看貴不貴。",
    "殖利率": "一年現金股利 ÷ 股價。存股族常看 4%～5% 以上。",
    "EPS": "每股盈餘：公司賺的錢 ÷ 股數。網站的近四季 EPS 是最近四季加總。",
    "ROE": "股東權益報酬率：近四季 EPS ÷ 每股淨值，代表公司用股東的錢一年賺多少 %。15% 以上算好公司。",
    "月營收年增率": "這個月營收跟去年同月比。去年同月太小時會標「基期低」，百分比容易誇大。",
    "毛利率": "（營收 − 成本）÷ 營收。代表產品賺錢的能力，比上一季、去年同季提升是好事。",
    "Beta": "股票跟大盤一起動的程度。1＝跟大盤一樣，1.5＝大盤跌 1% 它平均跌 1.5%，0.5 比較抗跌。",
    "IC": "分數排名和之後報酬排名的相關係數。0＝沒關係；股票裡 0.03～0.05 就算有用，t 值超過 2 才比較不像巧合。",
    "超額報酬": "某檔股票（或策略）的報酬減掉同期全部股票的平均報酬。正的代表跑贏大盤。",
    "最大回撤": "從最高點跌到之後最低點的最大跌幅，代表最壞情況下帳面會縮水多少。",
    "停損": "事先設定好「跌到這裡就賣」的價格，避免小賠變大賠。",
    "除權息": "公司發股利的那天，股價會扣掉股利（除息）或配股價值（除權）。漲回除權息前的價格叫填息。",
    "二代健保補充保費": "單次領到的股利超過 2 萬元，會先扣 2.11% 的補充保費。",
    "主動式 ETF": "由經理人主動挑股票的 ETF，每天公布持股，可以看經理人加碼、減碼了什麼。",
    "處置股／注意股": "交易所認為交易異常的股票。處置股要分盤撮合（例如 5 或 20 分鐘撮合一次），流動性變差。",
    "台指期": "以加權指數為標的的期貨。外資台指期淨未平倉是空單多時，代表外資在期貨端偏空或避險。",
    "Put/Call 比": "選擇權賣權和買權的比例，常被拿來看市場情緒；數值高代表避險的人多。",
    "XIRR 年化報酬": "考慮每一筆錢投入時間的年化報酬，定期定額要用這個看才公平。",
}


# ========== 研究筆記：自己的筆記＋券商報告＋網紅說法放在同一條時間軸 ==========
筆記檔 = "notes.json"


def 讀取筆記(設定):
    包 = 讀取設定檔(設定, 筆記檔)
    if not 包:
        return []
    return (解密(包, 設定.get("password", "")) if 包.get("加密") else 包).get("筆記", [])


def 儲存筆記(筆記們, 設定):
    密碼 = str(設定.get("password", ""))
    內容 = {"筆記": 筆記們}
    return 儲存設定檔(設定, 筆記檔, 加密(內容, 密碼) if 密碼 else 內容, "更新研究筆記")


def 研究時間軸(筆記們=(), 券商們=(), 影片們=(), 代號=None):
    """一列一則：日期、來源、代號、出處、看法、內容。代號給了就只留那檔。"""
    列們 = []
    for x in 筆記們:
        列們.append({"日期": x.get("日期"), "來源": "📝 我的筆記", "代號": str(x.get("代號") or ""), "出處": "自己",
                   "看法": x.get("看法", ""), "內容": x.get("內容", "")})
    for x in 券商們:
        目 = _數(x.get("目標價"))
        列們.append({"日期": x.get("日期"), "來源": "🏦 券商報告", "代號": str(x.get("代號") or ""), "出處": x.get("券商", ""),
                   "看法": x.get("看法") or x.get("評等") or "",
                   "內容": "　".join(s for s in (f"評等 {x['評等']}" if x.get("評等") else "", f"目標價 {目:,.0f}" if pd.notna(目) else "",
                                                str(x.get("摘要") or x.get("重點") or "")[:120]) if s)})
    for v in 影片們:
        for s in v.get("股票", []):
            列們.append({"日期": v.get("日期"), "來源": "🎬 網紅說法", "代號": str(s.get("代號") or ""), "出處": v.get("頻道", ""),
                       "看法": s.get("看法", ""), "內容": str(s.get("理由") or s.get("原文看法") or "")[:120]})
    t = pd.DataFrame(列們, columns=["日期", "來源", "代號", "出處", "看法", "內容"])
    if 代號:
        t = t[t["代號"] == str(代號)]
    t["日期"] = pd.to_datetime(t["日期"], errors="coerce")
    return t.sort_values("日期", ascending=False, na_position="last").reset_index(drop=True)


# ========== 網站錯誤紀錄（ai-reports 分支 errors.json；每天資料健康檢查時 LINE 通知新錯誤） ==========
def 記錄錯誤(設定, 頁面, 錯誤, 追蹤=""):
    """同一個錯誤（同頁、同類型、同一行）只記一筆，累加次數。"""
    import datetime as dt
    import hashlib
    import re as _re
    位置 = _re.findall(r'File "([^"]+)", line (\d+)', 追蹤)
    位置 = f"{Path(位置[-1][0]).name}:{位置[-1][1]}" if 位置 else ""
    鍵 = hashlib.sha1(f"{頁面}|{type(錯誤).__name__}|{位置}".encode()).hexdigest()[:10]
    現在 = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    for _ in range(3):
        try:
            紀錄 = 讀取設定檔(設定, "errors.json") or {}
            舊 = 紀錄.get(鍵, {"首次": 現在, "次數": 0})
            紀錄[鍵] = {**舊, "最近": 現在, "次數": 舊["次數"] + 1, "頁面": 頁面, "類型": type(錯誤).__name__,
                       "訊息": str(錯誤)[:300], "位置": 位置, "追蹤": 追蹤[-1500:]}
            if len(紀錄) > 50:  # 只留最近 50 種
                紀錄 = dict(sorted(紀錄.items(), key=lambda kv: kv[1]["最近"])[-50:])
            儲存設定檔(設定, "errors.json", 紀錄, f"網站錯誤 {頁面}")
            return
        except Exception:
            continue


# ========== 第三批新資料：外資持股比、當沖、選擇權籌碼、財報體質、公司事件、新股申購 ==========
def _讀(檔, **kw):
    f = 資料夾 / 檔
    if not f.exists():
        return None
    t = pd.read_csv(f, **kw)
    return t if len(t) else None


def 讀取外資持股():
    """data/qfii.csv.gz：date、code、ratio（外資及陸資持股比率 %）。"""
    return _讀("qfii.csv.gz", dtype={"code": str}, parse_dates=["date"])


def 讀取當沖():
    """data/daytrade.csv.gz：上市個股每日當沖成交股數 shares、買進金額 buy、賣出金額 sell。"""
    return _讀("daytrade.csv.gz", dtype={"code": str}, parse_dates=["date"])


def 讀取當沖大盤():
    """上市、上櫃整體當沖成交股數佔比（%），date × market。"""
    t = _讀("daytrade_market.csv", parse_dates=["date"])
    return None if t is None else t.pivot_table(index="date", columns="market", values="vol_pct").sort_index()


def 籌碼補充表(指標):
    """每檔：外資持股比、外資持股比 20 日變化（百分點）、當沖比率（近 5 日當沖股數 ÷ 成交股數，%）、
    投信 60 日買超佔股本（%，投信沒有公布持股，用累計買超估算）。以代號為索引。"""
    表 = pd.DataFrame(index=pd.Index([], name="代號"))
    q = 讀取外資持股()
    if q is not None:
        日們 = sorted(q["date"].unique())
        今 = q[q["date"] == 日們[-1]].set_index("code")["ratio"]
        表 = pd.DataFrame({"外資持股比": 今})
        if len(日們) > 20:
            前 = q[q["date"] == 日們[-21]].set_index("code")["ratio"]
            表["外資持股20日變化"] = (今 - 前.reindex(今.index)).round(2)
    d = 讀取當沖()
    if d is not None and "成交張數" in 指標.columns:
        近日 = sorted(d["date"].unique())[-5:]
        d = d[d["date"].isin(近日)].groupby("code")["shares"].sum() / 1000
        量 = 指標[指標["date"].isin(近日)].groupby("代號")["成交張數"].sum()
        比 = (d / 量.reindex(d.index) * 100).where(lambda s: s.between(0, 100)).round(1)
        表 = 表.join(比.rename("當沖比率"), how="outer")
    if "投信買超" in 指標.columns:
        近 = 指標[指標["date"] >= sorted(指標["date"].unique())[-60]]
        累 = 近.groupby("代號")["投信買超"].sum() * 1000
        股數 = _股本表()["發行股數"]
        表 = 表.join((累 / 股數.reindex(累.index) * 100).round(2).rename("投信60日買超佔股本"), how="outer")
    表.index.name = "代號"
    return 表


def 讀取財報(代號=None):
    """各季資產負債（季底，千元）與現金流量（換成單季，千元）：code、quarter、assets、liabilities、cur_assets、
    cur_liab、equity、cash_end、cfo、cfi、cff、fcf（營業＋投資現金流，自由現金流的簡易算法）。"""
    b = _讀("fundamental/balance.csv", dtype={"code": str})
    c = _讀("fundamental/cashflow.csv", dtype={"code": str})
    if b is None and c is None:
        return None
    if 代號 is not None:
        b = None if b is None else b[b["code"] == str(代號)]
        c = None if c is None else c[c["code"] == str(代號)]
    if c is not None and len(c):
        c = c.sort_values(["code", "quarter"]).copy()
        年, 季 = c["quarter"].str[:4], c["quarter"].str[-1].astype(int)
        前季 = 季.groupby([c["code"], 年]).shift()
        for 欄 in ("cfo", "cfi", "cff"):
            前 = c[欄].groupby([c["code"], 年]).shift()
            c[欄] = np.where(季 == 1, c[欄], np.where(前季 == 季 - 1, c[欄] - 前, np.nan))
        c["fcf"] = c["cfo"] + c["cfi"]
    if b is None or not len(b):
        return c
    return b.merge(c, on=["code", "quarter"], how="outer") if c is not None else b


def 財報體質表():
    """每檔最新一季：負債比、流動比（%）、近四季營業現金流、近四季自由現金流（億）。以代號為索引。"""
    t = 讀取財報()
    if t is None:
        return None
    t = t.sort_values(["code", "quarter"])
    結果 = pd.DataFrame(index=pd.Index(t["code"].unique(), name="代號"))
    if "liabilities" in t:
        最新 = t.dropna(subset=["assets"]).groupby("code").tail(1).set_index("code")
        結果["負債比"] = (最新["liabilities"] / 最新["assets"] * 100).round(1)
        結果["流動比"] = (最新["cur_assets"] / 最新["cur_liab"] * 100).where(最新["cur_liab"] > 0).round(0)
    if "cfo" in t:
        c = t.dropna(subset=["cfo"]).groupby("code").tail(4)
        季 = c.groupby("code")["quarter"].agg(["first", "last", "count"])
        連續 = 季[(季["count"] == 4) &季.apply(lambda r: (pd.Period(r["last"], "Q") - pd.Period(r["first"], "Q")).n == 3, axis=1)].index
        和 = c[c["code"].isin(連續)].groupby("code")[["cfo", "fcf"]].sum() / 1e5
        結果["近四季營業現金流億"] = 和["cfo"].round(1)
        結果["近四季自由現金流億"] = 和["fcf"].round(1)
    return 結果


def 讀取合約負債(代號=None):
    """各季合約負債（預收款，千元）＋同季營收：code、quarter、cl_cur、cl_noncur、src、合約負債、近四季營收、
    合約負債年增（%）、合約負債營收比（÷近四季營收，%）、能見度月（約等於幾個月營收）。
    年增：兩季都是觀測站資料就用流動＋非流動，否則只比流動（FinMind 歷史只有流動）；兩季都不到 1 億不算，避免小金額亂跳。"""
    t = _讀("fundamental/contract.csv", dtype={"code": str})
    if t is None or not len(t):
        return None
    if 代號 is not None:
        t = t[t["code"] == str(代號)]
        if not len(t):
            return None
    t = t.sort_values(["code", "quarter"]).copy()
    t["合約負債"] = t[["cl_cur", "cl_noncur"]].sum(axis=1, min_count=1)
    t["序"] = t["quarter"].str[:4].astype(int) * 4 + t["quarter"].str[-1].astype(int)
    去年 = t.set_index(["code", "序"])
    鍵 = list(zip(t["code"], t["序"] - 4))
    前總, 前流, 前源 = (去年[k].reindex(鍵).values for k in ("合約負債", "cl_cur", "src"))
    同源 = (t["src"].values == "mops") & (前源 == "mops")
    今 = np.where(同源, t["合約負債"], t["cl_cur"])
    前 = np.where(同源, 前總, 前流)
    with np.errstate(divide="ignore", invalid="ignore"):
        年增 = (今 / 前 - 1) * 100
    t["合約負債年增"] = np.where((前 > 0) & (np.fmax(今, 前) >= 1e5), 年增, np.nan).round(1)
    單 = 單季損益(代號)
    if len(單):
        單 = 單[["code", "quarter", "revenue_q"]].copy()
        單["近四季營收"] = 單.groupby("code")["revenue_q"].transform(lambda s: s.rolling(4).sum())
        t = t.merge(單[["code", "quarter", "revenue_q", "近四季營收"]].rename(columns={"revenue_q": "單季營收"}),
                    on=["code", "quarter"], how="left")
    else:
        t["單季營收"] = t["近四季營收"] = np.nan
    有營收 = t["近四季營收"] > 0
    t["合約負債營收比"] = (t["合約負債"] / t["近四季營收"] * 100).where(有營收).round(1)
    t["能見度月"] = (t["合約負債"] / t["近四季營收"] * 12).where(有營收).round(1)
    return t.drop(columns="序").reset_index(drop=True)


def 合約負債摘要(代號, 季數=6):
    """給 AI 分析用的一段文字：近幾季合約負債、年增率、能見度。沒資料回傳空字串。"""
    t = 讀取合約負債(代號)
    if t is None:
        return ""
    if t["src"].eq("mops").any() and t["合約負債"].isna().all():
        return "- 合約負債：財報沒有單獨列報（無法用預收款判斷營收能見度）"
    t = t.dropna(subset=["合約負債"]).tail(季數)
    if not len(t):
        return ""
    fmt = lambda v, f, 尾="": "—" if pd.isna(v) else f.format(v) + 尾
    各季 = "、".join(f"{x['quarter']} {x['合約負債'] / 1e5:,.1f} 億（年增 {fmt(x['合約負債年增'], '{:+.0f}', '%')}）"
                    for _, x in t.iterrows())
    最 = t.iloc[-1]
    return (f"- 合約負債（預收款，未來營收領先指標）近 {len(t)} 季：{各季}；最新能見度約 {fmt(最['能見度月'], '{:.1f}')} 個月營收"
            f"（合約負債 ÷ 近四季營收 {fmt(最['合約負債營收比'], '{:.0f}', '%')}）")


def 合約負債表():
    """每檔最新一季合約負債：合約負債億、合約負債季度、合約負債年增、合約負債營收比、能見度月、合約負債佔股本（%）。以代號為索引。"""
    t = 讀取合約負債()
    if t is None:
        return None
    最新 = t.dropna(subset=["合約負債"]).groupby("code").tail(1).set_index("code")
    結果 = pd.DataFrame({"合約負債億": (最新["合約負債"] / 1e5).round(2), "合約負債季度": 最新["quarter"],
                         "合約負債年增": 最新["合約負債年增"], "合約負債營收比": 最新["合約負債營收比"],
                         "能見度月": 最新["能見度月"]})
    股本 = _讀("fundamental/capital.csv", dtype={"code": str})
    if 股本 is not None:
        股 = 股本.drop_duplicates("code", keep="last").set_index("code")["capital"]
        結果["合約負債佔股本"] = (最新["合約負債"] * 1000 / 股.reindex(最新.index) * 100).round(1)
    結果.index.name = "代號"
    return 結果


def 預估檔們():
    """data/forecast/ 底下所有預估 EPS 快照，依資料日由舊到新：[(日期, 檔案), ...]。"""
    結果 = []
    for f in (資料夾 / "forecast").glob("eps_forecast_*.csv"):
        try:
            結果.append((pd.Timestamp(f.stem.split("_")[-1]), f))
        except ValueError:
            continue
    return sorted(結果)


def 讀取預估EPS(第幾份=-1):
    """取一份預估 EPS 快照（預設最新；-2＝前一份）。使用者匯出的全市場預估 EPS，三個來源。
    欄位：code、A_年、B_年、Vera_年（今年）、A_年+1、B_年+1（明年）。回傳 (DataFrame, 資料日 Timestamp) 或 (None, None)。"""
    檔們 = 預估檔們()
    if not 檔們 or -len(檔們) > 第幾份 or 第幾份 >= len(檔們):
        return None, None
    日, f = 檔們[第幾份]
    t = pd.read_csv(f, dtype={"code": str})
    return (t if len(t) else None), 日


def 轉換預估檔(原始):
    """使用者匯出的原始 CSV（股號、A_2026E_EPS、B_2027E_EPS、Vera_2026E_EPS…）→ 網站格式（code、A_2026…）。
    也接受已經是網站格式的檔。代號欄可叫 股號／代號／code。回傳 DataFrame；認不出欄位就丟 ValueError。"""
    代號欄 = next((c for c in ("code", "股號", "代號", "證券代號") if c in 原始.columns), None)
    if 代號欄 is None:
        raise ValueError("找不到代號欄（股號／代號／code）")
    欄們 = {}
    for c in 原始.columns:
        m = re.fullmatch(r"\s*(A|B|Vera)_(\d{4})E?(?:_EPS)?\s*", str(c), flags=re.I)
        if m:
            來源 = {"a": "A", "b": "B", "vera": "Vera"}[m.group(1).lower()]
            欄們[c] = f"{來源}_{m.group(2)}"
    if not 欄們:
        raise ValueError("找不到預估 EPS 欄（例如 A_2026E_EPS、B_2027E_EPS、Vera_2026E_EPS）")
    t = 原始[[代號欄] + list(欄們)].rename(columns={代號欄: "code", **欄們})
    t["code"] = t["code"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    for c in 欄們.values():
        t[c] = pd.to_numeric(t[c], errors="coerce").round(2)
    return t.dropna(how="all", subset=list(欄們.values())).drop_duplicates("code", keep="last")


def 存預估檔(t, 日期, 設定=None):
    """存成 data/forecast/eps_forecast_YYYYMMDD.csv。有 GITHUB_TOKEN 就直接寫到 main 分支（網站會自動重新部署），
    否則只存在網站本機（重啟會消失）。回傳是否已永久保存。"""
    import base64, requests
    檔名 = f"eps_forecast_{pd.Timestamp(日期):%Y%m%d}.csv"
    內容 = t.to_csv(index=False)
    f = 資料夾 / "forecast" / 檔名
    f.parent.mkdir(exist_ok=True)
    f.write_text(內容, "utf-8")
    權杖, 網址, _, 標頭 = _GitHub設定(設定 or {}, "x")
    if not 權杖:
        return False
    網址 = 網址.split("/contents/")[0] + f"/contents/data/forecast/{檔名}"
    現有 = requests.get(網址, params={"ref": "main"}, headers=標頭, timeout=15)
    資料 = {"message": f"更新預估 EPS {pd.Timestamp(日期):%Y-%m-%d}", "branch": "main",
            "content": base64.b64encode(內容.encode("utf-8")).decode()}
    if 現有.status_code == 200:
        資料["sha"] = 現有.json()["sha"]
    requests.put(網址, headers=標頭, json=資料, timeout=30).raise_for_status()
    return True


def _預估共識(t):
    """一份快照 → 以代號為索引的 A、B、Vera 今年／明年，與 A、B 中位數（預估EPS今年、預估EPS明年）、預估年度。"""
    年們 = sorted({int(c.split("_")[1]) for c in t.columns if "_" in c and c.split("_")[1].isdigit()})
    if not 年們:
        return None
    今年 = 年們[0]
    t = t.drop_duplicates("code", keep="last").set_index("code")
    g = lambda c: pd.to_numeric(t[c], errors="coerce") if c in t.columns else pd.Series(np.nan, index=t.index)
    A, B, V = g(f"A_{今年}"), g(f"B_{今年}"), g(f"Vera_{今年}")
    A2, B2 = g(f"A_{今年 + 1}"), g(f"B_{今年 + 1}")
    結果 = pd.DataFrame(index=t.index)
    結果["預估EPS今年"] = pd.concat([A, B], axis=1).median(axis=1).round(2)
    結果["預估EPS明年"] = pd.concat([A2, B2], axis=1).median(axis=1).round(2)
    結果["預估A今年"], 結果["預估B今年"], 結果["預估Vera今年"] = A, B, V
    結果["預估A明年"], 結果["預估B明年"] = A2, B2
    結果["預估年度"] = 今年
    return 結果


def _修正幅度(新, 舊):
    """預估 EPS 修正 %：分母用 |舊|，舊值太小（< 0.3 元）不算，避免 0.05 → 0.2 變成 +300%。"""
    with np.errstate(divide="ignore", invalid="ignore"):
        return ((新 - 舊) / 舊.abs() * 100).where(舊.abs() >= 0.3).round(1)


預估分歧門檻 = 30  # A、B 兩源差超過 30% 視為分歧


def 預估EPS表():
    """每檔的預估 EPS 整理（以代號為索引）：
    預估EPS今年／預估EPS明年＝A、B 兩源中位數（含業外的完整 EPS，跟財報 EPS 同口徑）。
    Vera 是使用者說的 AI 角色，只預估本業（業內），不含業外，所以口徑不同、不納入共識、不能拿去跟已公布 EPS 比；
    另列 預估本業EPS（＝Vera）、預估業外占比%（＝（共識 − 本業）÷ 共識，估計業外占今年預估多少）。
    另算 預估分歧%（A、B 差）、明年EPS成長%、隱含剩餘EPS（今年預估 − 已公布累計）、隱含季成長%（剩下幾季平均 vs 最新單季）、
    預估低於累計（今年預估比已公布累計還低，可能是舊預估或預期後面虧損）。
    有前一份快照時，再加 前期預估EPS今年、預估修正%、明年預估修正%、前期資料日（同一年度才比今年；跨年時拿舊的明年比新的今年）。"""
    t, 日 = 讀取預估EPS()
    if t is None:
        return None
    結果 = _預估共識(t)
    if 結果 is None:
        return None
    今年 = int(結果["預估年度"].iloc[0])
    A, B = 結果["預估A今年"], 結果["預估B今年"]
    結果["預估來源數"] = A.notna().astype(int) + B.notna().astype(int)
    結果["預估本業EPS"] = 結果["預估Vera今年"]
    with np.errstate(divide="ignore", invalid="ignore"):
        分母 = ((A.abs() + B.abs()) / 2).where(lambda s: s >= 0.3)
        結果["預估分歧%"] = ((A - B).abs() / 分母 * 100).round(0)
        今 = 結果["預估EPS今年"]
        結果["明年EPS成長%"] = ((結果["預估EPS明年"] / 今 - 1) * 100).where(今 >= 0.3).round(1)
        結果["預估業外占比%"] = ((今 - 結果["預估本業EPS"]) / 今.abs() * 100).where(今 >= 0.3).round(0)
    結果["預估資料日"] = 日
    # 跟前一份快照比：上修／下修
    舊表, 舊日 = 讀取預估EPS(-2)
    舊 = _預估共識(舊表) if 舊表 is not None else None
    if 舊 is not None:
        舊 = 舊.reindex(結果.index)
        舊年 = int(舊["預估年度"].dropna().iloc[0]) if 舊["預估年度"].notna().any() else 今年
        if 舊年 == 今年:
            結果["前期預估EPS今年"] = 舊["預估EPS今年"]
            結果["預估修正%"] = _修正幅度(結果["預估EPS今年"], 舊["預估EPS今年"])
            結果["明年預估修正%"] = _修正幅度(結果["預估EPS明年"], 舊["預估EPS明年"])
        elif 舊年 == 今年 - 1:
            結果["前期預估EPS今年"] = 舊["預估EPS明年"]
            結果["預估修正%"] = _修正幅度(結果["預估EPS今年"], 舊["預估EPS明年"])
        結果["前期資料日"] = 舊日
    # 跟已公布的今年累計 EPS 對照
    e = 近四季EPS表()
    if len(e):
        e = e.reindex(結果.index)
        同年 = e["EPS季度"].astype(str).str[:4] == str(今年)
        季 = pd.to_numeric(e["EPS季度"].astype(str).str[-1], errors="coerce")
        累計 = e["累計EPS"].where(同年)
        結果["已公布累計EPS"] = 累計
        結果["累計至"] = e["EPS季度"].where(同年)
        結果["隱含剩餘EPS"] = (今 - 累計).round(2)
        剩 = (4 - 季).where(同年 & (季 < 4))
        with np.errstate(divide="ignore", invalid="ignore"):
            季均 = 結果["隱含剩餘EPS"] / 剩
            單 = e["單季EPS"].where(同年)
            結果["隱含季成長%"] = ((季均 / 單 - 1) * 100).where(單 >= 0.2).round(0)
        結果["預估低於累計"] = (今 < 累計 * 0.95) & (累計 > 0.5)
    結果.index.name = "代號"
    return 結果


def 預估EPS查詢(代號):
    """單檔的預估 EPS 那一列（dict）；沒有回傳 {}。給 LINE／PDF 報告這類不經過網站今日表的地方用。"""
    try:
        t = 預估EPS表()
    except Exception:
        return {}
    if t is None or str(代號) not in t.index:
        return {}
    return t.loc[str(代號)].to_dict()


def 預估修正驗證(價=None, 天數=20, 門檻=2.0, 最少檔數=10):
    """每兩份相鄰快照：預估上修（≥ 門檻%）和下修（≤ −門檻%）的股票，之後 天數 個交易日的平均報酬減全體平均。
    價＝寬表（日期 × 代號，還原價），測試用；不給就從資料庫算。快照不到兩份、或後面還不夠 天數 天時回傳 None 和原因。
    回傳 (DataFrame 每一期一列, 說明文字)。"""
    檔們 = 預估檔們()
    if len(檔們) < 2:
        return None, f"目前只有 {len(檔們)} 份預估快照，至少要兩份才能比上修下修，再過 {天數} 個交易日才能驗證。"
    if 價 is None:
        指 = 計算指標(讀取資料庫(最近天數=400))
        價 = 指.pivot(index="date", columns="代號", values="還原價").sort_index()
        del 指
        釋放記憶體()
    列們 = []
    for (舊日, 舊檔), (新日, 新檔) in zip(檔們[:-1], 檔們[1:]):
        舊 = _預估共識(pd.read_csv(舊檔, dtype={"code": str}))
        新 = _預估共識(pd.read_csv(新檔, dtype={"code": str}))
        if 舊 is None or 新 is None:
            continue
        同年 = 新["預估年度"].iloc[0] == 舊["預估年度"].iloc[0]
        修 = _修正幅度(新["預估EPS今年"], 舊.reindex(新.index)["預估EPS今年" if 同年 else "預估EPS明年"]).dropna()
        進 = 價.index.searchsorted(新日, side="right")
        if 進 + 天數 >= len(價.index):
            continue
        碼 = [c for c in 修.index if c in 價.columns]
        報 = (價.iloc[進 + 天數][碼] / 價.iloc[進][碼] - 1).dropna() * 100
        修 = 修.reindex(報.index)
        上, 下 = 報[修 >= 門檻], 報[修 <= -門檻]
        if len(上) < 最少檔數 or len(下) < 最少檔數:
            continue
        列們.append({"前期": 舊日, "本期": 新日, "上修檔數": len(上), "下修檔數": len(下),
                   "上修超額%": round(上.mean() - 報.mean(), 2), "下修超額%": round(下.mean() - 報.mean(), 2),
                   "上修減下修%": round(上.mean() - 下.mean(), 2)})
    if not 列們:
        return None, (f"已有 {len(檔們)} 份快照，但最新一期之後還不到 {天數} 個交易日（或上修、下修檔數太少），還不能驗證。")
    t = pd.DataFrame(列們)
    return t, f"{len(t)} 期平均：上修減下修 {t['上修減下修%'].mean():+.2f}%（{天數} 個交易日），勝率 {(t['上修減下修%'] > 0).mean() * 100:.0f}%。"


def 加預估本益比(t):
    """t 要有 收盤、預估EPS今年、預估EPS明年 → 加 預估本益比、明年預估本益比（EPS ≤ 0 不算；每天用最新收盤重算）。"""
    if "預估EPS今年" not in t.columns:
        return t
    t = t.copy()
    for 欄, 新 in (("預估EPS今年", "預估本益比"), ("預估EPS明年", "明年預估本益比")):
        e = pd.to_numeric(t[欄], errors="coerce")
        t[新] = (t["收盤"] / e).where(e > 0).round(1)
    if "預估本業EPS" in t.columns:
        e = pd.to_numeric(t["預估本業EPS"], errors="coerce")
        t["本業預估本益比"] = (t["收盤"] / e).where(e > 0).round(1)
    return t


def 預估EPS文字(r):
    """給 AI 用的一行文字；r 是今日表的一列（dict 或 Series）。沒有資料回傳空字串。"""
    g = lambda k: r.get(k, np.nan)
    今 = g("預估EPS今年")
    if not isinstance(今, (int, float)) or pd.isna(今):
        return ""
    年 = int(g("預估年度")) if pd.notna(g("預估年度")) else ""
    日 = g("預估資料日")
    說 = [f"市場預估 EPS（使用者匯出的全市場預估，A、B 兩源中位數，資料日 {pd.Timestamp(日):%Y-%m-%d}）：{年} 年 {今:.2f}"]
    if pd.notna(g("預估EPS明年")):
        說.append(f"{年 + 1 if 年 else '明'} 年 {g('預估EPS明年'):.2f}")
    if pd.notna(g("預估本益比")):
        說.append(f"預估本益比 {g('預估本益比'):.1f} 倍" + (f"／明年 {g('明年預估本益比'):.1f} 倍" if pd.notna(g("明年預估本益比")) else ""))
    if pd.notna(g("預估本業EPS")):
        說.append(f"本業（業內）預估 EPS {g('預估本業EPS'):.2f}"
                  + (f"，預估業外約占 {g('預估業外占比%'):.0f}%" if pd.notna(g("預估業外占比%")) else ""))
    if pd.notna(g("預估分歧%")) and g("預估分歧%") > 預估分歧門檻:
        說.append(f"兩源差 {g('預估分歧%'):.0f}%（分歧大）")
    if pd.notna(g("隱含剩餘EPS")):
        說.append(f"已公布累計 {g('已公布累計EPS'):.2f}（至 {g('累計至')}），全年預估隱含後面還要賺 {g('隱含剩餘EPS'):.2f}"
                  + (f"，平均每季比最新一季 {g('隱含季成長%'):+.0f}%" if pd.notna(g("隱含季成長%")) else ""))
    return "，".join(說)


def 合約負債驗證(價=None, 天數=60, 最少成交值=2e7):
    """全市場驗證合約負債：每季財報公告後（季底＋45 天，第四季＋90 天）持有 天數 個交易日的超額報酬，
    依合約負債年增率／能見度／近兩季營收年增各分三組，比較高組減低組；也看合約負債年增能不能預告未來兩季營收。
    價＝寬表（日期 × 代號，還原價），測試用；不給就從資料庫算。結果存 data/contract_backtest.json（Actions 算）。"""
    t = 讀取合約負債()
    if t is None:
        return None
    t = t[t["code"].str.fullmatch(r"[1-9]\d{3}")].copy()
    均額 = None
    if 價 is None:
        指 = 計算指標(讀取資料庫())
        指 = 指[指["代號"].isin(set(t["code"]))]
        價 = 指.pivot(index="date", columns="代號", values="還原價").sort_index()
        均額 = 指.pivot(index="date", columns="代號", values="value").sort_index().rolling(20).mean()
        del 指
        釋放記憶體()
    日 = 價.index
    季底 = pd.PeriodIndex(t["quarter"].str.replace("Q", "-Q"), freq="Q").end_time.normalize()
    公告 = 季底 + pd.to_timedelta(np.where(季底.month == 12, 90, 45), "D")
    t["進"] = 日.searchsorted(公告.values, side="right")
    可 = (t["進"] + 天數 < len(日)) & t["code"].isin(價.columns)
    t = t[可].copy()
    欄位 = 價.columns.get_indexer(t["code"])
    進價, 出價 = 價.values[t["進"], 欄位], 價.values[t["進"] + 天數, 欄位]
    t["報酬"] = 出價 / 進價 - 1
    if 均額 is not None:
        t = t[均額.values[t["進"] - 1, 均額.columns.get_indexer(t["code"])] >= 最少成交值]
    # 近兩季營收年增（已公布）與未來兩季營收年增
    單 = 單季損益()[["code", "quarter", "revenue_q"]]
    單["序"] = 單["quarter"].str[:4].astype(int) * 4 + 單["quarter"].str[-1].astype(int)
    營 = 單.set_index(["code", "序"])["revenue_q"]
    t["序"] = t["quarter"].str[:4].astype(int) * 4 + t["quarter"].str[-1].astype(int)
    取 = lambda d: 營.reindex(list(zip(t["code"], t["序"] + d))).values
    with np.errstate(divide="ignore", invalid="ignore"):
        t["近兩季營收年增"] = ((取(0) + 取(-1)) / (取(-4) + 取(-5)) - 1) * 100
        t["未來兩季營收年增"] = ((取(1) + 取(2)) / (取(-3) + 取(-2)) - 1) * 100
    t = t.replace([np.inf, -np.inf], np.nan).dropna(subset=["報酬"])
    t["超額"] = t["報酬"] - t.groupby("quarter")["報酬"].transform("mean")
    有意義 = t["合約負債營收比"] >= 5  # 合約負債至少是近四季營收的 5%，太小的公司不看

    def 分組(欄, 遮=None):
        d = t[有意義 if 遮 is None else 遮].dropna(subset=[欄])
        d = d[d.groupby("quarter")[欄].transform("count") >= 15]
        if not len(d):
            return None
        秩 = d.groupby("quarter")[欄].rank(pct=True)
        差 = (d[秩 > 2 / 3].groupby("quarter")["超額"].mean() - d[秩 <= 1 / 3].groupby("quarter")["超額"].mean()).dropna()
        if len(差) < 4:
            return None
        return {"高減低%": round(差.mean() * 100, 2), "t值": round(差.mean() / 差.std() * np.sqrt(len(差)), 2),
                "勝率%": round((差 > 0).mean() * 100), "季數": int(len(差)), "筆數": int(len(d)),
                "高組平均%": round(d[秩 > 2 / 3]["超額"].mean() * 100, 2), "低組平均%": round(d[秩 <= 1 / 3]["超額"].mean() * 100, 2),
                "每季": {k: round(v * 100, 2) for k, v in 差.items()}}

    列們 = []
    for 名, 欄, 遮 in (("合約負債年增率", "合約負債年增", None), ("能見度（合約負債 ÷ 營收）", "能見度月", None),
                    ("對照：近兩季營收年增", "近兩季營收年增", None),
                    ("合約負債年增率（只看能見度 ≥ 3 個月的公司）", "合約負債年增", t["能見度月"] >= 3)):
        r = 分組(欄, 遮)
        if r:
            列們.append({"指標": 名, **r})
    d = t[有意義].dropna(subset=["合約負債年增", "近兩季營收年增", "未來兩季營收年增"])
    d = d[d[["合約負債年增", "近兩季營收年增", "未來兩季營收年增"]].abs().lt(1000).all(axis=1)]
    預告 = {}
    if len(d) >= 100:
        c = d[["合約負債年增", "近兩季營收年增", "未來兩季營收年增"]].rank().corr()
        a, b, r_ = c.loc["未來兩季營收年增", "合約負債年增"], c.loc["未來兩季營收年增", "近兩季營收年增"], c.loc["合約負債年增", "近兩季營收年增"]
        組 = pd.qcut(d["合約負債年增"].rank(method="first"), 3, labels=["低", "中", "高"])
        預告 = {"筆數": int(len(d)), "相關": round(a, 3),
                "偏相關": round((a - b * r_) / np.sqrt((1 - b ** 2) * (1 - r_ ** 2)), 3),
                "各組未來兩季營收年增中位數%": d.groupby(組, observed=True)["未來兩季營收年增"].median().round(1).to_dict()}
    主 = next((r for r in 列們 if r["指標"] == "合約負債年增率"), None)
    結論 = "資料不足"
    if 主:
        結論 = ("成立" if 主["t值"] >= 2 and 主["高減低%"] > 0 else "偏弱" if 主["高減低%"] > 0 else "不成立")
    return {"計算日": pd.Timestamp.now().strftime("%Y-%m-%d"), "天數": 天數, "家數": int(t[有意義]["code"].nunique()),
            "起": t["quarter"].min(), "迄": t["quarter"].max(), "結果": 列們, "營收預告": 預告, "結論": 結論}


def 更新合約負債驗證(強制=False, 間隔天數=25):
    """GitHub Actions 每天呼叫；距離上次超過 間隔天數 才重算。"""
    import json
    檔 = 資料夾 / "contract_backtest.json"
    if 檔.exists() and not 強制:
        舊 = json.loads(檔.read_text())
        if (pd.Timestamp.now() - pd.Timestamp(舊.get("計算日", "2000-01-01"))).days < 間隔天數:
            print("合約負債驗證：還不用重算")
            return
    結果 = 合約負債驗證()
    if 結果:
        檔.write_text(json.dumps(結果, ensure_ascii=False, indent=1, default=float))
        print(f"合約負債驗證：{結果['結論']}，{結果['家數']} 家")


def 讀取合約負債驗證():
    import json
    檔 = 資料夾 / "contract_backtest.json"
    return json.loads(檔.read_text()) if 檔.exists() else None


def 讀取選擇權():
    """回傳 (P/C ratio 表, 三大法人買賣權未平倉表, 各履約價未平倉分布)，沒有的回傳 None。"""
    pc = _讀("options_pc.csv", parse_dates=["date"])
    法 = _讀("options_inst.csv", parse_dates=["date"])
    分布 = _讀("options_oi.csv", parse_dates=["date"], dtype={"expiry": str})
    return (None if pc is None else pc.set_index("date").sort_index(),
            None if 法 is None else 法.set_index("date").sort_index(), 分布)


def 選擇權壓力支撐(分布, 種類="month", 檔數=3):
    """最新一天、最近月份（month）或最近一週（week）合約：買權未平倉最多的履約價＝壓力、賣權最多＝支撐。
    回傳 dict（日期、合約、壓力 [(履約價, 口數)…]、支撐、表）或 None。"""
    if 分布 is None or not len(分布):
        return None
    t = 分布[(分布["date"] == 分布["date"].max()) & (分布["kind"] == 種類)]
    if not len(t):
        return None
    買 = t[t["cp"] == "call"].nlargest(檔數, "oi")
    賣 = t[t["cp"] == "put"].nlargest(檔數, "oi")
    return {"日期": t["date"].iloc[0], "合約": t["expiry"].iloc[0],
            "壓力": list(zip(買["strike"], 買["oi"])), "支撐": list(zip(賣["strike"], 賣["oi"])), "表": t}


def 讀取新股申購():
    t = _讀("ipo.csv", dtype={"code": str}, parse_dates=["draw_date", "start", "end", "list_date"])
    return t


def 申購試算(申購, 現價):
    """申購表加上：現價、價差、每簽獲利（1 張）、報酬%。現價＝今日收盤（初上市櫃還沒有就是 NaN）。"""
    t = 申購.copy()
    t["現價"] = t["code"].map(現價)
    t["價差"] = t["現價"] - t["price"]
    t["每簽獲利"] = (t["價差"] * 1000).round(0)
    t["報酬%"] = (t["價差"] / t["price"] * 100).round(1)
    return t


def 讀取庫藏股():
    return _讀("buyback.csv", dtype={"code": str}, parse_dates=["board_date", "start", "end"])


def 讀取可轉債():
    """data/cb.csv：code、name、issue_date、maturity、amount、outstanding（元）、conv_price（發行時轉換價）。"""
    return _讀("cb.csv", dtype={"code": str}, parse_dates=["issue_date", "maturity"])


# ========== 公司簡介：主要業務、營收比重、董事長、成立／上市日期（公開資訊觀測站＋MoneyDJ） ==========
公司簡介欄 = ["code", "業務", "營收比重", "董事長", "總經理", "成立日期", "上市日期", "網址", "員工人數", "同業本益比", "更新日"]


def _表頭對值(html):
    """把 <th>名稱</th><td>值</td> 這種表格轉成 {名稱: 值}（去掉標籤與空白）。"""
    import re
    清 = lambda x: re.sub(r"\s+", " ", re.sub(r"<[^>]+>|&nbsp;?", " ", re.sub(r"(?i)<br\s*/?>\s*", "", x))).strip()
    return {清(k): 清(v) for k, v in re.findall(r"(?is)<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", html)}


def 抓公司簡介(代號):
    """一檔公司的簡介：公開資訊觀測站「公司基本資料」（主要經營業務等）＋ MoneyDJ 基本資料（營收比重）。
    兩邊各約 1 秒；任一邊失敗就留空。回傳 dict（欄位見 公司簡介欄）。"""
    import re
    import requests

    H = {"User-Agent": "Mozilla/5.0"}
    結果 = {"code": str(代號), "更新日": f"{pd.Timestamp.now(tz='Asia/Taipei'):%Y-%m-%d}"}
    try:
        r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t05st03", headers=H, timeout=20, data={
            "encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "keyword4": "", "code1": "", "TYPEK2": "",
            "checkbtn": "", "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "co_id": str(代號)})
        表 = _表頭對值(r.text)
        結果.update({"業務": 表.get("主要經營業務", ""), "董事長": 表.get("董事長", ""), "總經理": 表.get("總經理", ""),
                   "成立日期": 表.get("公司成立日期", ""), "網址": 表.get("公司網址", "") or 表.get("網址", ""),
                   "上市日期": next((表[k] for k in ("上市日期", "上櫃日期", "興櫃日期") if 表.get(k, "").strip("& ")), "")})
        員工 = next((v for k, v in 表.items() if "員工" in k), "")
        結果["員工人數"] = 員工
    except Exception:
        pass
    try:
        r = requests.get(f"https://concords.moneydj.com/z/zc/zca/zca_{代號}.djhtm", headers=H, timeout=20)
        r.encoding = "big5"
        t = re.sub(r"<[^>]+>", "|", re.sub(r"(?is)<script.*?</script>|<style.*?</style>", "", r.text))
        t = re.sub(r"\s*\|[\s|]*", "|", re.sub(r"&nbsp;?", " ", t))
        找 = lambda 名: (re.search(rf"\|{名}\|([^|]+)\|", t) or [None, ""])[1].strip()
        結果["營收比重"] = 找("營收比重")
        結果["同業本益比"] = 找("同業平均本益比")
        for 名, 欄 in (("董事長", "董事長"), ("總經理", "總經理"), ("網址", "網址")):
            if not 結果.get(欄):
                結果[欄] = 找(名)
    except Exception:
        pass
    return 結果


def 讀取公司簡介():
    f = 資料夾 / "company_profile.csv"
    return pd.read_csv(f, dtype=str).fillna("").set_index("code") if f.exists() else pd.DataFrame(columns=公司簡介欄[1:])


def 營收比重解析(文字):
    """「晶圓-5奈米30.98%、其他14.08% (2025年)」→ (DataFrame[項目, 比重], 年度)。"""
    import re
    if not 文字:
        return pd.DataFrame(columns=["項目", "比重"]), ""
    年 = (re.search(r"\((\d{4})年\)", 文字) or [None, ""])[1]
    項們 = re.findall(r"([^、()%]+?)\s*(-?[\d.]+)%", re.sub(r"\(\d{4}年\)", "", 文字))
    t = pd.DataFrame([(a.strip(), float(b)) for a, b in 項們], columns=["項目", "比重"])
    return t.sort_values("比重", ascending=False, ignore_index=True), 年


def 公司規模(今日, 代號):
    """市值、近 12 個月營收在全市場與同產業的排名（同產業市值第一＝產業龍頭的參考）。"""
    t = 今日[~今日["代號"].str.startswith("0") & 今日["發行股數"].notna()].copy()
    t["市值億"] = t["收盤"] * t["發行股數"] / 1e8
    營收 = None
    f = 資料夾 / "fundamental" / "revenue_history.csv"
    if f.exists():
        h = pd.read_csv(f, dtype={"code": str}).sort_values("month")
        近 = h[h["month"] > sorted(h["month"].unique())[-13]] if h["month"].nunique() >= 13 else h
        營收 = 近.groupby("code")["revenue"].sum() / 1e5   # 千元 → 億元
        t["近12月營收億"] = t["代號"].map(營收)
    if 代號 not in set(t["代號"]):
        return None
    r = t.set_index("代號").loc[代號]
    同 = t[t["產業"] == r["產業"]] if pd.notna(r.get("產業")) and r.get("產業") else t.iloc[0:0]
    結果 = {"市值億": r["市值億"], "市值排名": int((t["市值億"] > r["市值億"]).sum()) + 1, "全部": len(t),
          "產業": r.get("產業") or "", "同業家數": len(同),
          "同業市值排名": int((同["市值億"] > r["市值億"]).sum()) + 1 if len(同) else None,
          "同業市值前三": 同.nlargest(3, "市值億")[["代號", "名稱", "市值億"]].values.tolist() if len(同) else []}
    if 營收 is not None and pd.notna(r.get("近12月營收億")):
        結果["近12月營收億"] = r["近12月營收億"]
        結果["同業營收排名"] = int((同["近12月營收億"] > r["近12月營收億"]).sum()) + 1 if len(同) else None
    return 結果


公司介紹提示 = """你是台股產業研究員。請用繁體中文（台灣用語）、白話，替一般投資人整理這家公司的介紹。
使用者提供的官方資料（主要經營業務、營收比重、市值與營收排名）是正確的，以它為準；其他內容依你所知或上網搜尋補充，
不確定的寫「未找到」或「待確認」，不要編造客戶名稱與數字。輸出 Markdown，依序用 ### 標題：
### 一句話介紹（這家公司靠什麼賺錢，30 字內）
### 主要產品與營收比重（條列，比重以使用者提供的為準，並用一句話解釋每項產品是什麼、用在哪裡）
### 主要客戶與下游應用（知名客戶、客戶集中度；查不到就寫未找到）
### 產業地位（是不是龍頭、全球／台灣市占率大約多少、主要競爭對手）
### 公司規模（市值、營收規模在同業的排名、員工、海外據點或產能）
### 投資人要注意的地方（景氣循環、客戶集中、匯率等 2～4 點）"""


def AI公司介紹(代號, 名稱, 資料文字, 引擎, 金鑰, 模型, 搜尋=False):
    """請 AI 寫公司介紹（產品、客戶、產業地位、規模）。回傳 Markdown。"""
    提問 = f"請介紹台股 {代號} {名稱}。\n\n官方與網站資料：\n{資料文字}"
    if 引擎 == "Gemini":
        內容 = {"systemInstruction": {"parts": [{"text": 公司介紹提示}]},
              "contents": [{"role": "user", "parts": [{"text": 提問}]}]}
        if 搜尋:
            內容["tools"] = [{"google_search": {}}]
        回應, _ = Gemini呼叫(內容, 金鑰, 模型)
        候選 = (回應.json().get("candidates") or [{}])[0]
        return "".join(p.get("text", "") for p in (候選.get("content") or {}).get("parts", [])).strip()
    import anthropic
    回應 = anthropic.Anthropic(api_key=金鑰).messages.create(
        model=模型, max_tokens=3000, system=公司介紹提示, messages=[{"role": "user", "content": 提問}])
    return "".join(b.text for b in 回應.content if b.type == "text").strip()


def 讀取公司介紹(代號, 設定):
    return 讀取設定檔(設定, f"company/{代號}.json") or {}


def 儲存公司介紹(代號, 紀錄, 設定):
    return 儲存設定檔(設定, f"company/{代號}.json", 紀錄, f"公司介紹 {代號}")


# ========== 第四批：董監轉讓、經理人記分板、網紅條件與價位 ==========
def 讀取內部人轉讓():
    """data/insider_transfer.csv：董監大股東轉讓事前申報（每天抓當天的，慢慢累積）。"""
    return _讀("insider_transfer.csv", dtype={"code": str}, parse_dates=["date"])


def 價格寬表(指標, 欄="還原價"):
    """指標（代號, date, 還原價）→ 以日期為 index、代號為欄位的寬表，算事件後報酬用。"""
    if 指標 is None or not len(指標):
        return pd.DataFrame()
    return 指標.pivot_table(index="date", columns="代號", values=欄, aggfunc="last").sort_index()


def 事件後報酬(事件, 寬表, 加權=None, 天數=20, 代欄="code", 日欄="date"):
    """每個事件（代號＋日期）之後 天數 個交易日的報酬，扣掉同期加權＝超額報酬。
    以事件日收盤為基準（申報、ETF 公布持股都是收盤後才知道）。不到期的用最新價，標「到期」=False。"""
    t = 事件.copy()
    t["報酬%"], t["超額%"], t["到期"] = np.nan, np.nan, False
    if 寬表.empty or not len(t):
        return t
    日們 = 寬表.index
    加 = None
    if 加權 is not None and len(加權):
        加 = 加權.set_index("date")["close"].reindex(日們).ffill()
    起位 = 日們.searchsorted(pd.to_datetime(t[日欄]).values, side="right") - 1
    報, 超, 到 = [], [], []
    for 位, c in zip(起位, t[代欄].astype(str)):
        if 位 < 0 or c not in 寬表.columns or 位 >= len(日們) - 1:
            報.append(np.nan); 超.append(np.nan); 到.append(False)
            continue
        終 = min(位 + 天數, len(日們) - 1)
        a, b = 寬表[c].iloc[位], 寬表[c].iloc[終]
        r = (b / a - 1) * 100 if pd.notna(a) and pd.notna(b) and a > 0 else np.nan
        報.append(r)
        超.append(r - (加.iloc[終] / 加.iloc[位] - 1) * 100 if 加 is not None and pd.notna(r) else r)
        到.append(位 + 天數 <= len(日們) - 1)
    t["報酬%"], t["超額%"], t["到期"] = np.round(報, 1), np.round(超, 1), 到
    return t


def 內部人記分板(轉讓, 寬表, 加權=None):
    """董監申報轉讓之後 20／60 天，股價有沒有比大盤差。依申報方式分組（一般交易＝在市場上賣，最值得注意）。"""
    if 轉讓 is None or not len(轉讓):
        return pd.DataFrame(), pd.DataFrame()
    t = 事件後報酬(轉讓, 寬表, 加權, 20)
    t60 = 事件後報酬(轉讓, 寬表, 加權, 60)
    t["超額60%"], t["到期60"] = t60["超額%"].values, t60["到期"].values
    t["方式"] = t["方式"].fillna("").str.replace(r"\(.*\)", "", regex=True).str.strip()
    g = t.groupby("方式")
    彙 = pd.DataFrame({"筆數": g.size(), "20天到期": g["到期"].sum(),
                      "20天平均超額%": g.apply(lambda x: x.loc[x["到期"], "超額%"].mean()).round(1),
                      "20天輸大盤%": g.apply(lambda x: (x.loc[x["到期"], "超額%"] < 0).mean() * 100).round(0),
                      "60天平均超額%": g.apply(lambda x: x.loc[x["到期60"], "超額60%"].mean()).round(1)})
    return t, 彙.sort_values("筆數", ascending=False)


def 經理人記分板(變化, 寬表, 加權=None, 天數=20, 爛盤=-1.0):
    """主動式 ETF 每次「新增／加碼」之後 天數 個交易日的超額報酬，看哪位經理人的加碼最準。
    另外單獨看「爛盤逆勢加碼」：加權當天跌 1% 以上還在加碼。回傳 (明細, 依 ETF 彙總, 爛盤彙總)。"""
    if 變化 is None or not len(變化):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    e = 變化[變化["type"].isin(["新增", "加碼"])].copy()
    if "adj_amount" in e:
        e = e[e["adj_amount"].fillna(0) > 0]
    e = 事件後報酬(e, 寬表, 加權, 天數)
    if 加權 is not None and len(加權):
        漲 = 加權.set_index("date")["close"].pct_change() * 100
        e["大盤%"] = pd.to_datetime(e["date"]).map(漲).round(2)
    else:
        e["大盤%"] = np.nan
    e["爛盤"] = e["大盤%"] <= 爛盤

    def 彙(t):
        到 = t[t["到期"]]
        if not len(t):
            return pd.DataFrame()
        g, gd = t.groupby("etf"), 到.groupby("etf")
        r = pd.DataFrame({"加碼次數": g.size(), "已到期": gd.size(), "平均超額%": gd["超額%"].mean().round(1),
                          "贏大盤%": gd["超額%"].apply(lambda s: (s > 0).mean() * 100).round(0)}).fillna({"已到期": 0})
        return r.sort_values(["平均超額%"], ascending=False)
    return e, 彙(e), 彙(e[e["爛盤"]])


AI工具字 = re.compile(r"ChatGPT|Gemini|Claude|NotebookLM|Copilot|Perplexity|提示詞|[Pp]rompt|AI\s*工具|AI\s*教學|GPTs")


def 是AI工具影片(v):
    """在講怎麼用 AI 工具的影片（不是在講股票），不計入對答案與熱度。"""
    文 = f"{v.get('標題') or ''} {v.get('頻道') or ''}"
    return bool(AI工具字.search(文)) and len(v.get("股票") or []) <= 1


def 網紅共識熱度(影片們, 天數=14, 今天=None, 最少頻道=2):
    """最近 天數 天被 2 個以上頻道點名的股票，看多／看空各幾個頻道。"""
    今天 = pd.Timestamp(今天 or pd.Timestamp.today().normalize())
    列們 = [{"代號": str(x.get("代號")), "名稱": x.get("名稱"), "看法": x.get("看法"), "頻道": v.get("頻道")}
           for v in 影片們 if not 是AI工具影片(v)
           and pd.notna(d := pd.to_datetime(v.get("日期"), errors="coerce")) and d >= 今天 - pd.Timedelta(days=天數)
           for x in v.get("股票", [])]
    t = pd.DataFrame(列們)
    if t.empty:
        return t
    g = t.groupby("代號")
    彙 = pd.DataFrame({"名稱": g["名稱"].first(), "頻道數": g["頻道"].nunique(),
                      "看多": g.apply(lambda x: x.loc[x["看法"] == "看多", "頻道"].nunique()),
                      "看空": g.apply(lambda x: x.loc[x["看法"] == "看空", "頻道"].nunique()),
                      "頻道": g["頻道"].apply(lambda s: "、".join(dict.fromkeys(s))[:60])}).reset_index()
    return 彙[彙["頻道數"] >= 最少頻道].sort_values(["頻道數", "看多"], ascending=False)


價位字 = re.compile(r"(支撐|壓力|停損|目標價?|上看|跌破|站上|站回|守住?|突破|買點|賣點|回測|低接|加碼|減碼)"
                 r"[^\d，。；]{0,6}?(\d{2,5}(?:\.\d+)?)\s*(?:元|塊)")


def 網紅價位(影片們, 現價=None, 天數=60, 今天=None):
    """從理由裡挑出「支撐 / 停損 / 目標價 … N 元」這種價位計畫，和現價比距離。"""
    今天 = pd.Timestamp(今天 or pd.Timestamp.today().normalize())
    列們 = []
    for v in 影片們:
        d = pd.to_datetime(v.get("日期"), errors="coerce")
        if pd.isna(d) or d < 今天 - pd.Timedelta(days=天數) or 是AI工具影片(v):
            continue
        for x in v.get("股票", []):
            for 類, 價 in 價位字.findall(str(x.get("理由") or "")):
                價 = float(價)
                現 = (現價 or {}).get(str(x.get("代號")))
                if 現 and not (現 * 0.3 < 價 < 現 * 3):
                    continue  # 像「2028 年」「EPS 200 元」這種不是股價
                列們.append({"日期": d, "頻道": v.get("頻道"), "代號": str(x.get("代號")), "名稱": x.get("名稱"),
                           "類型": 類, "價位": 價, "現價": 現,
                           "距離%": round((價 / 現 - 1) * 100, 1) if 現 else np.nan})
    return pd.DataFrame(列們)


def 數字查核(理由, 本益比=None, EPS=None):
    """影片說的「EPS × 倍數」和網站目前數字並列，不幫影片判對錯，只提醒差多少。"""
    文 = str(理由 or "")
    說 = []
    m倍 = re.search(r"(\d{1,3}(?:\.\d+)?)\s*倍", 文)
    mE = re.search(r"EPS[^\d]{0,6}(\d{1,4}(?:\.\d+)?)", 文)
    if m倍:
        說.append(f"影片用 {m倍.group(1)} 倍" + (f"，網站目前本益比 {本益比:.1f} 倍" if 本益比 and 本益比 > 0 else ""))
    if mE:
        說.append(f"影片用 EPS {mE.group(1)}" + (f"，網站近四季 EPS {EPS:.2f}" if EPS is not None and EPS == EPS else ""))
    return "；".join(說)


_週期 = {"日": 1, "週": 5, "周": 5, "月": 20}


def 條件目標(文字, 股票們, 名表=None):
    """條件講的是哪一個標的：先找影片點名的股票名稱，再看有沒有講大盤。回傳 (代號, 名稱) 或 None。"""
    for x in 股票們 or []:
        if x.get("名稱") and x["名稱"] in 文字 and str(x.get("代號", "")).isdigit():
            return str(x["代號"]), x["名稱"]
    for 名, 代 in (名表 or {}).items():
        if len(名) >= 2 and 名 in 文字:
            return str(代), 名
    if re.search(r"台股|大盤|加權|指數", 文字):
        return "TAIEX", "加權指數"
    return None


def 檢查條件(文字, 標的, K=None, 匯率=None, 外資億=None):
    """把一句「如果…就…」的前半段拿來跟現在的資料比。K＝標的日 K（date, close 由舊到新）。
    回傳 (狀態, 說明)；狀態：成立／未成立／None（看不懂或沒資料）。只判斷看得懂的幾種：均線、價位、KD 交叉、台幣、外資。"""
    文 = str(文字)
    if K is not None and len(K) >= 20:
        收 = K["close"].astype(float).reset_index(drop=True)
        現 = float(收.iloc[-1])
        m = re.search(r"(站上|站回|突破|守住|跌破|失守|跌到)\s*(\d{1,3})\s*(日|週|周|月)\s*(?:均線|線|均)", 文)
        if m:
            n = int(m.group(2)) * _週期[m.group(3)]
            if len(收) >= n:
                線 = float(收.tail(n).mean())
                上 = 現 > 線
                要上 = m.group(1) in ("站上", "站回", "突破", "守住")
                return ("成立" if 上 == 要上 else "未成立",
                        f"{標的} 收盤 {現:,.2f}，{m.group(2)}{m.group(3)}線 {線:,.2f}（{'在上面' if 上 else '在下面'}）")
        m = re.search(r"(站上|站回|突破|守住|跌破|失守|跌到|回到)\s*(\d{2,6}(?:\.\d+)?)\s*(點|元)?", 文)
        if m and not re.match(r"\d+\s*(日|週|周|月)", 文[m.end(2):m.end(2) + 2]):
            價 = float(m.group(2))
            if 現 * 0.5 < 價 < 現 * 2:
                要上 = m.group(1) in ("站上", "站回", "突破", "守住", "回到")
                上 = 現 >= 價
                return ("成立" if 上 == 要上 else "未成立", f"{標的} 收盤 {現:,.2f}，條件價 {價:,.0f}")
        if re.search(r"KD", 文) and re.search(r"黃金交叉|死亡交叉", 文) and "high" in K and "low" in K:
            高, 低 = K["high"].astype(float).reset_index(drop=True), K["low"].astype(float).reset_index(drop=True)
            rsv = (收 - 低.rolling(9).min()) / (高.rolling(9).max() - 低.rolling(9).min()) * 100
            k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
            d = k.ewm(alpha=1 / 3, adjust=False).mean()
            近 = (k > d).tail(4).tolist()
            金 = 近[-1] and not all(近)
            死 = (not 近[-1]) and any(近)
            要金 = "黃金交叉" in 文
            return ("成立" if (金 if 要金 else 死) else "未成立",
                    f"{標的} K {k.iloc[-1]:.0f}、D {d.iloc[-1]:.0f}" + ("，近 3 天黃金交叉" if 金 else "，近 3 天死亡交叉" if 死 else ""))
    if "台幣" in 文 and 匯率 is not None and len(匯率) >= 6 and re.search(r"貶|升", 文):
        x = 匯率["usdtwd"].dropna()
        變 = (float(x.iloc[-1]) / float(x.iloc[-6]) - 1) * 100
        貶 = 變 > 0
        要貶 = bool(re.search(r"續貶|貶值|做頭續貶|再貶", 文)) or ("貶" in 文 and "止貶" not in 文)
        if "止貶" in 文 or "升值" in 文:
            要貶 = False
        return ("成立" if 貶 == 要貶 else "未成立", f"近 5 日美元兌台幣 {變:+.2f}%（{'台幣貶' if 貶 else '台幣升'}）")
    if "外資" in 文 and 外資億 is not None and len(外資億) >= 5 and re.search(r"買|賣", 文):
        五 = float(外資億.tail(5).sum())
        要賣 = bool(re.search(r"賣", 文)) and not re.search(r"回補|轉買|買超", 文)
        return ("成立" if (五 < 0) == 要賣 else "未成立", f"外資近 5 日{'賣超' if 五 < 0 else '買超'} {abs(五):,.0f} 億")
    return None, ""


def 網紅條件清單(影片們, 天數=30, 今天=None, 名表=None):
    """最近 天數 天影片的「如果…就…」條件，附上要拿哪個標的去檢查。"""
    今天 = pd.Timestamp(今天 or pd.Timestamp.today().normalize())
    列們 = []
    for v in 影片們:
        d = pd.to_datetime(v.get("日期"), errors="coerce")
        if pd.isna(d) or d < 今天 - pd.Timedelta(days=天數) or 是AI工具影片(v):
            continue
        for 條 in v.get("條件") or []:
            目 = 條件目標(條, v.get("股票"), 名表)
            列們.append({"日期": d, "頻道": v.get("頻道"), "條件": 條, "代號": 目[0] if 目 else None,
                       "標的": 目[1] if 目 else None})
    return 列們


# ========== 第五批：興櫃觀察、推薦券商、承銷重訊 ==========
def 讀取興櫃歷史(天數=60):
    檔們 = sorted((資料夾 / "esb").glob("*.csv.gz"))[-天數:]
    if not 檔們:
        return None
    t = pd.concat([pd.read_csv(f, dtype={"code": str}) for f in 檔們], ignore_index=True)
    t["date"] = pd.to_datetime(t["date"])
    return t


def 讀取推薦券商():
    return _讀("esb_dealers.csv", dtype={"code": str})


def 讀取推薦變動():
    return _讀("esb_dealer_changes.csv", dtype={"code": str}, parse_dates=["date"])


def 讀取重大訊息():
    return _讀("material_news.csv", dtype={"code": str}, parse_dates=["date"])


掛牌字 = re.compile(r"申請(股票)?(上市|上櫃)|上(市|櫃)審議|轉(上市|上櫃)|掛牌")


def 興櫃總覽(歷史, 券商=None, 變動=None, 重訊=None, 今天=None):
    """每檔興櫃股：最新價、20 日漲幅、成交張數、推薦券商家數、近 30 天推薦變動、近 90 天掛牌相關重訊，
    以及「估計承銷價」＝近 20 日均價 × 0.7～0.85（經驗法則：承銷價通常比興櫃均價打折）。"""
    if 歷史 is None or not len(歷史):
        return pd.DataFrame()
    今天 = pd.Timestamp(今天 or 歷史["date"].max())
    歷史 = 歷史.sort_values("date")
    g = 歷史.groupby("code")
    最新 = g.tail(1).set_index("code")
    均20 = g["average"].apply(lambda s: s.tail(20).mean())
    首 = g["close"].apply(lambda s: s.iloc[-21] if len(s) > 20 else s.iloc[0])
    t = pd.DataFrame({"名稱": 最新["name"], "收盤": 最新["close"], "均價": 最新["average"],
                      "漲幅%": ((最新["close"] / 首 - 1) * 100).round(1),
                      "成交張數": (最新["volume"] / 1000).round(0), "20日均價": 均20.round(2)})
    t["推薦家數"] = 券商.groupby("code").size().reindex(t.index).fillna(0).astype(int) if 券商 is not None and len(券商) else np.nan
    t["推薦變動"] = ""
    if 變動 is not None and len(變動):
        近 = 變動[變動["date"] >= 今天 - pd.Timedelta(days=30)]
        字 = 近.groupby("code").apply(lambda x: "、".join(f"{a}{b}" for a, b in zip(x["change"].str[:2], x["dealer"])))
        t["推薦變動"] = 字.reindex(t.index).fillna("")
    t["掛牌進度"] = ""
    if 重訊 is not None and len(重訊):
        近 = 重訊[(重訊["date"] >= 今天 - pd.Timedelta(days=90)) & 重訊["subject"].str.contains(掛牌字, na=False)]
        t["掛牌進度"] = 近.sort_values("date").groupby("code")["subject"].last().str[:40].reindex(t.index).fillna("")
    t["估計承銷價"] = [f"{a * 0.7:,.1f}～{a * 0.85:,.1f}" if pd.notna(a) else "—" for a in t["20日均價"]]
    return t.reset_index().rename(columns={"code": "代號"})


技術替代風險 = {
    "高速傳輸連接器": "光進銅退：機櫃內的高速銅纜、連接器，之後可能被 CPO／光學互連取代一部分。要看公司有沒有光通訊、NPO 的產品或認證。",
    "PCB載板銅箔基板": "玻璃基板：大尺寸 AI 晶片的封裝載板，之後可能從有機（ABF）材料換成玻璃核心，時間點大約 2027 年以後。要看公司有沒有參與玻璃基板送樣。",
    "散熱": "液冷取代氣冷：AI 機櫃功耗越來越高，只做風扇、熱導管、散熱片的公司要看有沒有水冷板、CDU、快接頭的產品。",
    "面板": "OLED、Micro LED 取代 LCD：手機、筆電、車用面板慢慢換成新技術，要看公司新技術的營收比重。",
    "PCB製板": "CoWoP／玻璃基板：封裝直接上 PCB 或改用玻璃核心，會改變載板與主機板的分工，要看公司技術能不能跟上。",
    "先進封裝抗翹曲": "上蓋結構與翹曲抑制設備：新一代 GPU 的上蓋、加強框設計，或印能 WSAS 這類設備，可能減少平衡膜／抗翹曲材料的單顆用量。要看 Rubin Ultra 之後的封裝架構定案，以及客戶是混用還是改用設備。",
}


def 掛牌估值試算(現價, EPS們, 同業本益比):
    """同業本益比（三檔以上取低四分位、中位數、高四分位，否則取平均）× 自己估的 EPS ＝ 參考價，再算現價等於幾倍。
    EPS們：{"今年": 7.5, "明年": 13}；同業本益比：同業的本益比清單（負的、空的會被拿掉）。"""
    倍 = pd.Series(同業本益比, dtype=float)
    倍 = 倍[倍 > 0].dropna()
    EPS們 = {k: float(v) for k, v in (EPS們 or {}).items() if v is not None and pd.notna(v) and float(v) > 0}
    if not len(倍) or not EPS們:
        return pd.DataFrame()
    層 = ({"同業偏低（25%）": 倍.quantile(0.25), "同業中位數": 倍.median(), "同業偏高（75%）": 倍.quantile(0.75)}
         if len(倍) >= 3 else {"同業平均": 倍.mean()})
    列們 = [{"情境": k, "本益比": f"{v:.1f} 倍", **{f"{名}EPS {e:g} 元": f"{v * e:,.1f}" for 名, e in EPS們.items()}}
           for k, v in 層.items()]
    if 現價 and pd.notna(現價) and 現價 > 0:
        列們.append({"情境": f"現價 {現價:,.1f} 等於", "本益比": "—",
                   **{f"{名}EPS {e:g} 元": f"{現價 / e:.1f} 倍" for 名, e in EPS們.items()}})
    return pd.DataFrame(列們)


def 新股掛牌表現(申購試算表):
    """過去公開申購（初上市櫃）掛牌後的報酬%：給興櫃估值當參考。"""
    if 申購試算表 is None or not len(申購試算表) or "報酬%" not in 申購試算表:
        return None
    t = 申購試算表[申購試算表["market"].astype(str).str.contains("初上")].dropna(subset=["報酬%"])
    if not len(t):
        return None
    return {"檔數": len(t), "中位數%": float(t["報酬%"].median()), "上漲比例%": float((t["報酬%"] > 0).mean() * 100)}


# ========== 基礎撐壓講義：正逆價差、教科書規則實測、K 棒白話、均線三態、期貨試算、布林、成交均價 ==========
def 均線狀態(ma5, ma10, ma20, ma60):
    """講義的均線三態：多頭排列（5>10>20>60）、空頭排列、均線糾結（四線差 < 2%），其他算均線交錯。回傳 (狀態, 燈, 說明)。"""
    值 = [ma5, ma10, ma20, ma60]
    if any(v is None or pd.isna(v) or v <= 0 for v in 值):
        return None, "⚪", "資料不足 60 天"
    if ma5 > ma10 > ma20 > ma60:
        return "多頭排列", "🔴", "5 > 10 > 20 > 60 日線，短中長期買的人都賺錢，均線在下方當支撐"
    if ma5 < ma10 < ma20 < ma60:
        return "空頭排列", "🟢", "5 < 10 < 20 < 60 日線，各期間買的人都套牢，均線在上方變壓力"
    if max(值) / min(值) - 1 < 0.02:
        return "均線糾結", "🟡", f"四條均線只差 {(max(值) / min(值) - 1) * 100:.1f}%，盤整中、方向未定（實測之後偏弱）"
    return "均線交錯", "⚪", "均線順序交錯，趨勢不明，看站上或跌破哪幾條"


def K棒解讀(今, 昨, 前20高=None, 前20低=None, 量比=None):
    """講義的 K 棒四價解讀：開盤（跳空）、收盤位置、上下影線、有沒有過昨高／破昨低。
    今、昨：dict 或 Series，要有 open、high、low、close。量比：今天量 ÷ 20 日均量（大盤沒有就 None）。
    回傳 (句子們, 規則鍵們)：規則鍵對應 讀取規則實測() 的列，用來附上「過去這種 K 棒之後的實際結果」。"""
    o, h, l, c = (float(今[k]) for k in ("open", "high", "low", "close"))
    yo, yh, yl, yc = (float(昨[k]) for k in ("open", "high", "low", "close"))
    句, 鍵 = [], []
    幅 = h - l
    if 幅 <= 0 or c <= 0:
        return ["今天幾乎沒有波動（一字線）。"], 鍵
    if o > yh:
        句.append(f"開盤 {o:,.2f} 跳空開在昨天最高 {yh:,.2f} 之上，開盤就很強。")
        鍵.append("跳空開高")
    elif o < yl:
        句.append(f"開盤 {o:,.2f} 跳空開在昨天最低 {yl:,.2f} 之下，開盤就偏弱。")
    elif yc > yo and abs(o / yc - 1) < 0.003:
        句.append("昨天收紅、今天開平盤附近，講義認為多方企圖不強。")
    位 = (c - l) / 幅
    實體 = abs(c - o)
    上影, 下影 = h - max(o, c), min(o, c) - l
    if 位 >= 0.8:
        句.append(f"收在當天高檔（全天區間的 {位 * 100:.0f}% 位置），多方收盤占上風。")
        鍵.append("收在高檔")
    elif 位 <= 0.2:
        句.append(f"收在當天低檔（全天區間的 {位 * 100:.0f}% 位置），空方收盤占上風。")
        鍵.append("收在低檔")
    else:
        句.append(f"收在當天中段（{位 * 100:.0f}% 位置），多空大致打平。")
    if 上影 > 2 * 實體 and 上影 / c > 0.015:
        創高 = 前20高 is not None and pd.notna(前20高) and h >= 前20高
        句.append(f"留下 {上影 / c * 100:.1f}% 的長上影線，" + ("而且是在創 20 日新高時，講義說這是遇到壓力。" if 創高 else "上方有賣壓。"))
        if 創高:
            鍵.append("創高長上影線")
    if 下影 > 2 * 實體 and 下影 / c > 0.015:
        破低 = 前20低 is not None and pd.notna(前20低) and l <= 前20低
        句.append(f"留下 {下影 / c * 100:.1f}% 的長下影線，" + ("而且是在破 20 日新低時，講義說這是有支撐。" if 破低 else "下方有買盤承接。"))
        if 破低:
            鍵.append("破低長下影線")
    if 前20高 is not None and pd.notna(前20高):
        if c > 前20高:
            帶量 = 量比 is not None and pd.notna(量比) and 量比 >= 1.5
            句.append(f"收盤突破前 20 日最高 {前20高:,.2f}" + ("，而且量放大到 20 日均量的 1.5 倍以上。" if 帶量 else
                                                  "，但量沒有特別放大。" if 量比 is not None and pd.notna(量比) else "。"))
            if 量比 is not None and pd.notna(量比):
                鍵.append("突破帶量" if 帶量 else "突破量不足")
        elif h > 前20高:
            句.append(f"盤中衝過前 20 日最高 {前20高:,.2f}，收盤卻沒守住，講義說收盤突破才算數。")
            鍵.append("假突破")
    elif h > yh and c <= yh:
        句.append("盤中過昨高但收盤沒站上，上方仍有壓力。")
    return 句, 鍵


規則清單 = [  # 鍵, 名稱, 講義說法, 預期方向（+1 偏多、−1 偏空）, 看幾天
    ("多頭排列", "均線多頭排列（5>10>20>60）", "多頭走勢，偏多", 1, 20),
    ("空頭排列", "均線空頭排列", "空頭走勢，偏空", -1, 20),
    ("均線糾結", "均線糾結（四線差 < 2%）", "盤整，等方向", 0, 20),
    ("糾結後突破", "均線糾結後收盤突破 20 日高", "盤整突破，有一波行情", 1, 20),
    ("MACD翻紅", "MACD 柱翻紅（單獨）", "買進訊號", 1, 20),
    ("MACD翻黑", "MACD 柱翻黑（單獨）", "賣出訊號", -1, 20),
    ("MACD翻紅多頭", "MACD 柱翻紅＋多頭排列", "買進訊號＋趨勢向上", 1, 20),
    ("跳空開高", "開盤跳空開在昨高之上", "主力拉抬，強勢續多", 1, 5),
    ("收在高檔", "收在當天高檔（區間 80% 以上）", "多方強勢", 1, 5),
    ("收在低檔", "收在當天低檔（區間 20% 以下）", "空方強勢", -1, 5),
    ("創高長上影線", "創 20 日高留長上影線", "遇到壓力，注意拉回", -1, 5),
    ("破低長下影線", "破 20 日低留長下影線", "出現支撐，注意反彈", 1, 5),
    ("突破帶量", "收盤突破 20 日高＋量 ≥ 1.5 倍", "突破要帶量才可靠", 1, 20),
    ("突破量不足", "收盤突破 20 日高、量不足", "沒量的突破不可靠", -1, 20),
    ("假突破", "盤中過 20 日高、收盤沒過", "收盤沒突破不算數", -1, 20),
    # 「0050 跌深前 5＋融資維持率 140% 越低越好」說法（2026-11 查核）
    ("跌深", "距 52 週高點跌 > 30%", "跌深就會反彈", 1, 60),
    ("跌深低維持", "跌深＋融資維持率 < 150%", "維持率越低越好、反彈首選", 1, 60),
    ("跌深已追繳", "跌深＋融資維持率 < 130%", "融資斷頭後籌碼乾淨", 1, 60),
    ("跌深融資洗完", "跌深＋融資洗完（20 日減 > 15% 或曾破 130%）", "融資退場後反彈", 1, 60),
    ("跌深融資增加", "跌深＋融資 20 日增 > 15%", "融資接刀，還沒洗完", -1, 60),
]


def 規則實測(最少成交值=5e7):
    """用資料庫全部個股驗證 規則清單：每條規則出現後 N 日的平均報酬、勝率、超額（扣掉同一天所有樣本平均）。
    很吃記憶體，跟評分回測一樣在 GitHub Actions 算好存 data/rule_backtest.json。"""
    指 = 計算指標(讀取資料庫())
    指 = 指[指["代號"].str.fullmatch(r"\d{4}") & (指["收盤"] > 0)]
    t = 指[["date", "代號", "open", "high", "low", "收盤", "還原價", "volume", "value", "MA5", "MA10", "MA20", "MA60",
           "MACD柱", "MACD翻紅", "均線糾結"] + [c for c in ("距52週高點", "margin", "融資維持率", "融資20日增減", "融資洗完",
                                                    "接刀風險") if c in 指.columns]].rename(columns={"收盤": "close"}).copy()
    del 指
    釋放記憶體()
    群 = t.groupby("代號", sort=False)
    t["均額"] = 群["value"].transform(lambda s: s.rolling(20).mean())
    t["均量"] = 群["volume"].transform(lambda s: s.rolling(20).mean().shift())
    t["前高"] = 群["high"].transform(lambda s: s.rolling(20).max().shift())
    t["前低"] = 群["low"].transform(lambda s: s.rolling(20).min().shift())
    t["昨高"] = 群["high"].shift()
    t["前柱"] = 群["MACD柱"].shift()
    for n in (5, 20, 60):
        t[f"f{n}"] = 群["還原價"].shift(-n) / t["還原價"] - 1
    t = t[(t["均額"] > 最少成交值)].dropna(subset=["MA60", "f20", "前高"])
    for n in (5, 20, 60):
        t[f"x{n}"] = t[f"f{n}"] - t.groupby("date")[f"f{n}"].transform("mean")
    多 = (t["MA5"] > t["MA10"]) & (t["MA10"] > t["MA20"]) & (t["MA20"] > t["MA60"])
    空 = (t["MA5"] < t["MA10"]) & (t["MA10"] < t["MA20"]) & (t["MA20"] < t["MA60"])
    糾 = t["均線糾結"].astype(bool)
    實體 = (t["close"] - t["open"]).abs()
    上影 = t["high"] - t[["open", "close"]].max(axis=1)
    下影 = t[["open", "close"]].min(axis=1) - t["low"]
    位 = (t["close"] - t["low"]) / (t["high"] - t["low"]).replace(0, np.nan)
    突 = t["close"] > t["前高"]
    帶量 = t["volume"] >= 1.5 * t["均量"]
    遮罩 = {
        "多頭排列": 多, "空頭排列": 空, "均線糾結": 糾, "糾結後突破": 糾 & 突,
        "MACD翻紅": t["MACD翻紅"].astype(bool), "MACD翻黑": (t["MACD柱"] < 0) & (t["前柱"] >= 0),
        "MACD翻紅多頭": t["MACD翻紅"].astype(bool) & 多,
        "跳空開高": t["open"] > t["昨高"], "收在高檔": 位 >= 0.8, "收在低檔": 位 <= 0.2,
        "創高長上影線": (上影 > 2 * 實體) & (上影 > 0.015 * t["close"]) & (t["high"] >= t["前高"]),
        "破低長下影線": (下影 > 2 * 實體) & (下影 > 0.015 * t["close"]) & (t["low"] <= t["前低"]),
        "突破帶量": 突 & 帶量, "突破量不足": 突 & ~帶量, "假突破": (t["high"] > t["前高"]) & ~突,
    }
    if "融資洗完" in t.columns:
        深 = (t["距52週高點"] <= -30) & (t["margin"] >= 200)
        遮罩.update({"跌深": 深, "跌深低維持": 深 & (t["融資維持率"] < 150), "跌深已追繳": 深 & (t["融資維持率"] < 130),
                   "跌深融資洗完": t["融資洗完"].astype(bool), "跌深融資增加": t["接刀風險"].astype(bool)})
    列們 = []
    for 鍵, 名, 說法, 向, n in 規則清單:
        if 鍵 not in 遮罩:
            continue
        m = 遮罩[鍵].fillna(False)
        r, x = t.loc[m, f"f{n}"], t.loc[m, f"x{n}"]
        if len(r) < 30:
            continue
        超 = float(x.mean() * 100)
        if 向 == 0:
            結論 = "偏弱" if 超 <= -0.3 else "偏強" if 超 >= 0.3 else "沒差"
        else:
            結論 = "成立" if 超 * 向 >= 0.3 else "相反" if 超 * 向 <= -0.3 else "沒差"
        列們.append({"鍵": 鍵, "規則": 名, "講義說法": 說法, "天數": n, "筆數": int(len(r)),
                    "平均報酬%": round(float(r.mean() * 100), 2), "勝率%": round(float((r > 0).mean() * 100), 1),
                    "超額%": round(超, 2), "結論": 結論})
    return {"計算日": f"{pd.Timestamp.now():%Y-%m-%d}", "起": f"{t['date'].min():%Y-%m-%d}",
            "迄": f"{t['date'].max():%Y-%m-%d}", "樣本": int(len(t)), "規則": 列們}


def 更新規則實測(強制=False, 間隔天數=25):
    """GitHub Actions 每天呼叫；距離上次超過 間隔天數 才重算。"""
    import json
    檔 = 資料夾 / "rule_backtest.json"
    if 檔.exists() and not 強制:
        舊 = json.loads(檔.read_text())
        if (pd.Timestamp.now() - pd.Timestamp(舊.get("計算日", "2000-01-01"))).days < 間隔天數:
            print("規則實測：還不用重算")
            return
    結果 = 規則實測()
    檔.write_text(json.dumps(結果, ensure_ascii=False, indent=1))
    print(f"規則實測：已更新 {len(結果['規則'])} 條")


def 讀取規則實測():
    import json
    檔 = 資料夾 / "rule_backtest.json"
    return json.loads(檔.read_text()) if 檔.exists() else None


def 規則實測句(實測, 鍵們):
    """K 棒解讀用：把對到的規則接上一句「過去這種情況之後 N 日…」。"""
    if not 實測 or not 鍵們:
        return []
    表 = {r["鍵"]: r for r in 實測.get("規則", [])}
    句 = []
    for k in 鍵們:
        r = 表.get(k)
        if r:
            句.append(f"過去「{r['規則']}」{r['筆數']:,} 次，之後 {r['天數']} 日平均 {r['平均報酬%']:+.2f}%、"
                     f"勝率 {r['勝率%']:.0f}%、比同期大家 {r['超額%']:+.2f}%（常見說法：{r['講義說法']} → {r['結論']}）")
    return 句


# ----- 台指期正逆價差＋未平倉四象限 -----
def 讀取台指期價差():
    """data/futures_basis.csv（期交所近月收盤、全市場未平倉）對上 index_ohlc.csv 的加權收盤。
    回傳 DataFrame(index=date)：期貨、加權、價差、未平倉、價差變化、未平倉變化、象限、之後5日%。"""
    f = 資料夾 / "futures_basis.csv"
    指 = 資料夾 / "index_ohlc.csv"
    if not f.exists() or not 指.exists():
        return None
    期 = pd.read_csv(f, parse_dates=["date"], dtype={"month": str}).set_index("date")
    加 = pd.read_csv(指, parse_dates=["date"])
    加 = 加[加["symbol"] == "TAIEX"].set_index("date")["close"]
    t = 期.join(加.rename("加權"), how="inner").rename(columns={"fut_close": "期貨", "total_oi": "未平倉", "month": "月份"})
    if t.empty:
        return None
    t["價差"] = (t["期貨"] - t["加權"]).round(2)
    t["價差變化"] = t["價差"].diff().round(2)
    t["未平倉變化"] = t["未平倉"].diff()
    換月 = t["月份"] != t["月份"].shift()   # 換月那天價差跳動是合約換了，不算擴大縮小
    t.loc[換月, "價差變化"] = np.nan
    t["象限"] = [價差象限(b, db, doi) for b, db, doi in zip(t["價差"], t["價差變化"], t["未平倉變化"])]
    t["之後5日%"] = ((t["加權"].shift(-5) / t["加權"] - 1) * 100).round(2)
    return t


def 價差象限(價差, 價差變化, 未平倉變化):
    """講義四象限：正價差擴大＋未平倉增＝多方攻；正價差擴大＋未平倉減＝行情近尾聲；
    逆價差擴大＋未平倉增＝空方強；逆價差擴大＋未平倉減＝空單回補、反彈機會。價差收斂＝中性。"""
    if any(pd.isna(v) for v in (價差, 價差變化, 未平倉變化)):
        return "—"
    擴大 = (價差 > 0 and 價差變化 > 0) or (價差 < 0 and 價差變化 < 0)
    if not 擴大:
        return "價差收斂"
    if 價差 > 0:
        return "正價差擴大＋未平倉增" if 未平倉變化 > 0 else "正價差擴大＋未平倉減"
    return "逆價差擴大＋未平倉增" if 未平倉變化 > 0 else "逆價差擴大＋未平倉減"


象限解讀 = {
    "正價差擴大＋未平倉增": ("🔴", "多方上攻力道強，講義：可看多"),
    "正價差擴大＋未平倉減": ("🟡", "多單在獲利了結，講義：行情可能接近尾聲"),
    "逆價差擴大＋未平倉增": ("🟢", "空方放空力道強，講義：可看空"),
    "逆價差擴大＋未平倉減": ("🟡", "空單在回補，講義：反彈機會大"),
    "價差收斂": ("⚪", "價差往 0 靠近，期現貨看法趨於一致"),
}


def 象限統計(t):
    """四象限出現後加權指數 5 日報酬：次數、平均、上漲機率，對照全部日子。"""
    if t is None or t["之後5日%"].notna().sum() < 20:
        return None
    s = t.dropna(subset=["之後5日%"])
    s = s[s["象限"] != "—"]
    g = s.groupby("象限")["之後5日%"].agg(次數="size", 平均報酬="mean", 上漲機率=lambda x: (x > 0).mean() * 100)
    g.loc["全部日子"] = [len(s), s["之後5日%"].mean(), (s["之後5日%"] > 0).mean() * 100]
    g = g.round(2)
    g["次數"] = g["次數"].astype(int)
    return g


# ----- 期貨部位試算 -----
期貨規格 = {"大台（TX）": 200, "小台（MTX）": 50, "微台（TMF）": 10}
期貨保證金預設 = {  # 2026-08-12 期交所公告（一般交易時段結束後生效）；data/futures_margin.csv 有新資料會優先用
    "大台（TX）": {"原始": 701_000, "維持": 538_000},
    "小台（MTX）": {"原始": 175_250, "維持": 134_500},
    "微台（TMF）": {"原始": 35_050, "維持": 26_900},
}


def 讀取期貨保證金():
    """回傳 (保證金 dict, 來源說明)。data/futures_margin.csv（product, initial, maintenance, date）由 update_data 抓期交所。"""
    f = 資料夾 / "futures_margin.csv"
    保 = {k: dict(v) for k, v in 期貨保證金預設.items()}
    來源 = "2026-08-12 期交所公告"
    if f.exists():
        try:
            t = pd.read_csv(f)
            for _, r in t.iterrows():
                if r["product"] in 保 and r["initial"] > 0:
                    保[r["product"]] = {"原始": int(r["initial"]), "維持": int(r["maintenance"])}
            來源 = f"期交所保證金一覽（{t['date'].max()} 抓取）"
        except Exception:
            pass
    return 保, 來源


def 期貨試算(商品, 點位, 口數, 帳戶資金, 方向="多", 手續費=50, 保證金=None):
    """回傳 dict：契約價值、原始／維持保證金、實際槓桿、每點損益、來回期交稅＋手續費、追繳點位、幾口錢做一口。
    期交稅 = 契約價值 × 10 萬分之 2（單邊），手續費是單邊每口。"""
    每點 = 期貨規格[商品]
    保 = (保證金 or 讀取期貨保證金()[0])[商品]
    契約 = 點位 * 每點 * 口數
    原始, 維持 = 保["原始"] * 口數, 保["維持"] * 口數
    稅 = round(點位 * 每點 * 2e-5) * 口數 * 2
    費 = 手續費 * 口數 * 2
    可虧 = 帳戶資金 - 維持
    追繳距離 = 可虧 / (每點 * 口數) if 口數 else np.nan
    return {
        "契約價值": 契約, "原始保證金": 原始, "維持保證金": 維持,
        "資金夠不夠": 帳戶資金 >= 原始,
        "槓桿（對保證金）": 契約 / 原始 if 原始 else np.nan,
        "槓桿（對帳戶資金）": 契約 / 帳戶資金 if 帳戶資金 else np.nan,
        "幾口錢做一口": 帳戶資金 / (保["原始"] * 口數) if 口數 else np.nan,
        "每點損益": 每點 * 口數, "來回交易成本": 稅 + 費, "期交稅（來回）": 稅,
        "成本折合點數": (稅 + 費) / (每點 * 口數) if 口數 else np.nan,
        "追繳距離（點）": 追繳距離,
        "追繳點位": 點位 - 追繳距離 if 方向 == "多" else 點位 + 追繳距離,
        "指數跌 10% 損益": -點位 * 0.1 * 每點 * 口數 * (1 if 方向 == "多" else -1),
    }


# ----- 布林通道、成交均價 -----
def 布林通道(收盤, n=20, k=2):
    """回傳 (中線, 上軌, 下軌)。"""
    中 = 收盤.rolling(n).mean()
    標 = 收盤.rolling(n).std()
    return 中, 中 + k * 標, 中 - k * 標


def 成交均價線(成交金額, 成交股數, n=20):
    """近 n 日成交量加權均價＝Σ成交金額 ÷ Σ成交股數，比一般均線更接近這段期間買進者的平均成本（原始股價，不還原）。"""
    return 成交金額.rolling(n).sum() / 成交股數.rolling(n).sum().replace(0, np.nan)


# ========== 第六批：網紅與券商觀點餵給 AI、大盤本益比、週線連跌統計、法說會後反應 ==========
外部觀點規則 = """
- 外部觀點（網紅影片、券商報告）是別人的看法，不是事實：
  · 只能當「市場在討論什麼」的線索，數字以網站數據為準；兩者不一致時寫出差異，不要替外部說法圓。
  · 記分板命中率較高（到期 3 則以上、命中率 60% 以上）的頻道可以多參考，但要寫出命中率與樣本數；沒到期的不算準。
  · 多個頻道或多家券商同方向，是「熱度」不是「保證」；全部看多時提醒可能已反應。
  · 網紅的「如果…就…」條件若能用網站數據檢查，就寫出目前成立或還沒成立。
  · 引用時寫出處（頻道名或券商名＋日期），不要照抄原文。"""
大盤解讀提示 += 外部觀點規則
AI系統提示 += 外部觀點規則
回饋規則 = """
- 回饋紀錄（網站自己對答案的結果）：
  · 數據摘要有「AI 錯誤本」或「網站 AI 過去對這檔的報告」時，先看過去哪裡說錯，這次避免同樣的判斷；上次看錯要寫出這次有什麼不同。
  · 有「券商過去紀錄」時，紀錄好的券商可以多參考，紀錄差或樣本少的要打折，並寫出依據（說對幾 %、幾份）。
  · 有「規則體檢」列出沒有優勢的燈號時，不要拿那些燈號當主要理由。"""
大盤解讀提示 += 回饋規則
AI系統提示 += 回饋規則


def 提示版本(*文字們):
    """提示文字的指紋（8 碼）。提示一改，版本碼就變，命中率可以按版本比較（feedback.提示修改紀錄 寫改了什麼）。"""
    import hashlib
    return hashlib.sha1("".join(文字們).encode("utf-8")).hexdigest()[:8]


def 大盤提示版本():
    return 提示版本(大盤解讀提示, 解讀條件說明)


def 個股提示版本():
    return 提示版本(AI系統提示)


def 網紅記分板(影片們, 價格們, 加權=None):
    """依頻道彙總的命中率（網紅對答案），排除 AI 工具影片。回傳 DataFrame（index＝頻道）。"""
    影片們 = [v for v in 影片們 or [] if not 是AI工具影片(v)]
    if not 影片們 or not 價格們:
        return pd.DataFrame()
    _, 彙 = 網紅對答案(影片們, 價格們, 加權)
    return 彙


def _頻道標記(彙, 頻道):
    if 彙 is None or 彙.empty or 頻道 not in 彙.index:
        return ""
    r = 彙.loc[頻道]
    if not r["到期"]:
        return "（還沒有到期的看法）"
    return f"（記分板：到期 {r['到期']:.0f} 則、命中率 {r['命中率%']:.0f}%）"


def 指標價格表(指標, 代號們):
    """從 指標 拿出網紅對答案要的 {代號: DataFrame(date, 收盤)}。"""
    t = 指標[指標["代號"].isin(set(代號們))][["代號", "date", "收盤"]]
    return {c: g[["date", "收盤"]] for c, g in t.groupby("代號")}


def 網紅觀點摘要(影片們, 指標=None, 代號=None, 今天=None, 名表=None, 記分板=None):
    """給 AI 用的網紅觀點文字（list of str）。代號＝None 是大盤用：近 7 天條件、共識熱度、準的頻道；有代號則是該股近 60 天說法。"""
    影片們 = [v for v in 影片們 or [] if not 是AI工具影片(v)]
    if not 影片們:
        return []
    今天 = pd.Timestamp(今天 or pd.Timestamp.today().normalize())
    彙 = 記分板 if 記分板 is not None else pd.DataFrame()
    if 指標 is not None and 記分板 is None:
        try:
            代們 = {str(x.get("代號")) for v in 影片們 for x in v.get("股票", [])}
            彙 = 網紅記分板(影片們, 指標價格表(指標, 代們), 讀取指數K線("TAIEX"))
        except Exception as e:
            print("網紅記分板失敗：", repr(e))
    行 = []
    if 代號:
        for v in sorted(影片們, key=lambda v: str(v.get("日期")), reverse=True):
            d = pd.to_datetime(v.get("日期"), errors="coerce")
            if pd.isna(d) or d < 今天 - pd.Timedelta(days=60):
                continue
            for x in v.get("股票", []):
                if str(x.get("代號")) == str(代號):
                    行.append(f"- {d:%m/%d} {v['頻道']}{_頻道標記(彙, v['頻道'])}：{x.get('原文看法') or x.get('看法')}；{str(x.get('理由') or '')[:80]}")
        return (["網紅影片說法（近 60 天，是觀點不是事實）："] + 行[:6]) if 行 else []
    條們 = 網紅條件清單(影片們, 天數=7, 今天=今天, 名表=名表)
    if 條們:
        行.append("近 7 天網紅的「如果…就…」條件（可用數據檢查的請檢查）：")
        行 += [f"- {r['日期']:%m/%d} {r['頻道']}{_頻道標記(彙, r['頻道'])}：{r['條件'][:60]}"
              for r in sorted(條們, key=lambda r: r["日期"], reverse=True)[:10]]
    熱 = 網紅共識熱度(影片們, 天數=14, 今天=今天)
    if len(熱):
        行.append("近 14 天被多個頻道點名：" + "、".join(f"{r['名稱']}（{r['頻道數']} 個頻道，看多 {r['看多']}／看空 {r['看空']}）"
                                              for _, r in 熱.head(6).iterrows()))
    if not 彙.empty:
        準 = 彙[(彙["到期"] >= 3) & (彙["命中率%"] >= 60)].sort_values("命中率%", ascending=False)
        if len(準):
            行.append("記分板較準的頻道：" + "、".join(f"{k} {r['命中率%']:.0f}%（{r['到期']:.0f} 則）" for k, r in 準.head(5).iterrows()))
            for v in sorted(影片們, key=lambda v: str(v.get("日期")), reverse=True):
                d = pd.to_datetime(v.get("日期"), errors="coerce")
                if v.get("頻道") in 準.index and pd.notna(d) and d >= 今天 - pd.Timedelta(days=7):
                    行.append(f"- {d:%m/%d} {v['頻道']} 最近說：" + "；".join(
                        f"{x.get('名稱')} {x.get('看法')}" for x in v.get("股票", [])[:4]))
    return (["", "外部觀點：網紅影片（觀點不是事實）"] + 行) if 行 else []


def 券商觀點摘要(報告們, 今天=None, 天數=7):
    """給大盤 AI 用：近 天數 天券商報告的看法與目標價修正家數、集體升降評。"""
    if not 報告們:
        return []
    今天 = pd.Timestamp(今天 or pd.Timestamp.now().normalize())
    表 = 券商報告表(報告們)
    近 = 表[表["日期"] >= 今天 - pd.Timedelta(days=天數)]
    if 近.empty:
        return []
    行 = ["", f"外部觀點：券商報告（近 {天數} 天 {len(近)} 份）",
         f"看多 {(近['看法'] == '看多').sum()}／中性 {(近['看法'] == '中性').sum()}／看空 {(近['看法'] == '看空').sum()} 份；"
         f"目標價上修 {(近['目標價修正'] == '上修').sum()}、下修 {(近['目標價修正'] == '下修').sum()} 份"]
    集 = 集體升降評(報告們, 今天=今天)
    if 集:
        行.append("近 3 天 3 家以上同方向調整：" + "；".join(f"{名} {家} 家{方}" for _, 名, 方, 家, _ in 集[:5]))
    for 方 in ("上修", "下修"):
        t = 近[近["目標價修正"] == 方]
        if len(t):
            行.append(f"{方}目標價的股票：" + "、".join(dict.fromkeys(t["名稱"].astype(str)))[:120])
    return 行


def 外部觀點摘要(設定, 指標=None, 名表=None):
    """大盤 AI 用的網紅＋券商觀點。讀不到就回傳空字串。"""
    行 = []
    try:
        行 += 網紅觀點摘要(讀取網紅說法(設定), 指標, 名表=名表)
    except Exception as e:
        print("網紅觀點失敗：", repr(e))
    try:
        行 += 券商觀點摘要(讀取券商報告(設定))
    except Exception as e:
        print("券商觀點失敗：", repr(e))
    return "\n".join(行)


_本益比快取 = {}


def 大盤本益比(天數=None):
    """同一天的資料只算一次（讀 5 年月檔約 7 秒）。"""
    最新 = max((f.name for f in (資料夾 / "prices").glob("*/*.csv.gz")), default="")
    鍵 = (最新, 天數)
    if 鍵 not in _本益比快取:
        _本益比快取.clear()
        _本益比快取[鍵] = _大盤本益比(天數)
    return _本益比快取[鍵].copy()


def _大盤本益比(天數=None):
    """上市加權本益比＝Σ市值 ÷ Σ(市值 ÷ 本益比)，只算本益比 > 0 的（虧損股證交所不給本益比）。
    股數用 fundamental/capital.csv 目前的股數（歷史會有一點誤差）。每月取最後一個交易日，加上最近 天數 個交易日。
    另算 半導體（capital.csv 產業＝半導體）與 半導體不含台積電 的本益比，以及兩者對大盤的比值。
    回傳 DataFrame(date, 本益比, 半導體, 半導體不含台積電, 半導體相對, 不含台積電相對)。"""
    股 = _讀("fundamental/capital.csv", dtype={"code": str})
    欄們 = ["date", "本益比", "半導體", "半導體不含台積電", "半導體相對", "不含台積電相對"]
    if 股 is None or not len(股):
        return pd.DataFrame(columns=欄們)
    產業 = 股.set_index("code")["industry"] if "industry" in 股.columns else pd.Series(dtype=str)
    股 = 股.set_index("code")["shares"]

    def 算(t):
        t = t[(t["market"] == "上市") & t["code"].isin(股.index) & (t["pe"] > 0)]
        市 = t["close"] * t["code"].map(股)
        if len(t) <= 100:
            return {"本益比": np.nan}
        大 = float(市.sum() / (市 / t["pe"]).sum())
        半 = t["code"].map(產業).eq("半導體")
        結果 = {"本益比": 大}
        if 半.sum() >= 20:
            a = float(市[半].sum() / (市[半] / t["pe"][半]).sum())
            非 = 半 & (t["code"] != "2330")
            b = float(市[非].sum() / (市[非] / t["pe"][非]).sum())
            結果.update({"半導體": a, "半導體不含台積電": b, "半導體相對": a / 大, "不含台積電相對": b / 大})
        return 結果

    列們 = []
    for f in sorted((資料夾 / "monthly").glob("prices_*.parquet")):
        try:
            t = pd.read_parquet(f, columns=["market", "code", "close", "pe", "date"])
        except Exception:
            continue
        t["date"] = pd.to_datetime(t["date"])
        末 = t["date"].max()
        列們.append({"date": 末, **算(t[t["date"] == 末])})
    for f in sorted((資料夾 / "prices").glob("*/*.csv.gz"))[-(天數 or 1):]:
        t = pd.read_csv(f, dtype={"code": str})
        列們.append({"date": pd.to_datetime(f.name[:8]), **算(t)})
    結果 = pd.DataFrame(列們).reindex(columns=欄們)
    return 結果.dropna(subset=["本益比"]).drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def 週線連跌統計(K, 連跌=3, 乖離門檻=-5.0, 週數=(1, 2, 4)):
    """日 K 轉週 K，找「連跌 連跌 週以上、週收盤比 5 週線低 乖離門檻% 以上」的週，看之後 週數 週的漲跌。
    回傳 (目前狀態 dict, 歷次 DataFrame, 彙總 DataFrame)。"""
    週 = K.set_index("date")["close"].resample("W-FRI").last().dropna()
    週 = 週[週.index <= K["date"].max() + pd.Timedelta(days=6)]
    跌 = 週.diff() < 0
    連 = 跌.groupby((~跌).cumsum()).cumsum()
    乖 = (週 / 週.rolling(5).mean() - 1) * 100
    目前 = {"連跌週數": int(連.iloc[-1]), "乖離%": round(float(乖.iloc[-1]), 1), "週收盤": float(週.iloc[-1])}
    訊 = (連 >= 連跌) & (乖 <= 乖離門檻)
    訊 = 訊 & ~訊.shift(1, fill_value=False)  # 同一段只算第一次
    列們 = []
    位置 = list(週.index)
    for d in 週.index[訊]:
        i = 位置.index(d)
        列 = {"週": d, "連跌週數": int(連[d]), "乖離%": round(float(乖[d]), 1)}
        for n in 週數:
            列[f"{n}週後%"] = round((週.iloc[i + n] / 週.iloc[i] - 1) * 100, 1) if i + n < len(週) else np.nan
        列們.append(列)
    歷 = pd.DataFrame(列們)
    if 歷.empty:
        return 目前, 歷, pd.DataFrame()
    彙 = pd.DataFrame([{"期間": f"{n} 週後", "次數": int(歷[f"{n}週後%"].notna().sum()),
                       "上漲機率%": round(float((歷[f"{n}週後%"] > 0).mean() * 100), 0) if 歷[f"{n}週後%"].notna().any() else np.nan,
                       "平均%": round(float(歷[f"{n}週後%"].mean()), 1), "最差%": 歷[f"{n}週後%"].min(), "最好%": 歷[f"{n}週後%"].max()}
                      for n in 週數])
    return 目前, 歷, 彙


def 法說後反應(法說, 價格, 加權=None, 天數=3):
    """法說會（data/calendar.csv）之後隔天與 天數 天的漲跌，扣掉同期加權。
    法說多在盤後或盤中，所以「隔天」＝法說日之後第一個交易日收盤 vs 法說日收盤。價格＝DataFrame(代號, date, 收盤)。"""
    if 法說 is None or not len(法說) or 價格 is None or not len(價格):
        return pd.DataFrame()
    加 = 加權.set_index("date")["close"] if 加權 is not None and len(加權) else None
    群 = dict(tuple(價格.sort_values("date").groupby("代號")))
    列們 = []
    for _, r in 法說.iterrows():
        p = 群.get(str(r["code"]))
        if p is None:
            continue
        前, 後 = p[p["date"] <= r["date"]], p[p["date"] > r["date"]]
        if not len(前) or not len(後):
            continue
        基 = float(前["收盤"].iloc[-1])
        列 = {"法說日": r["date"], "代號": str(r["code"]), "名稱": r["name"]}
        for n, 名 in ((1, "隔天%"), (天數, f"{天數}天%")):
            if len(後) < n:
                列[名] = 列[名.replace("%", "超額%")] = np.nan
                continue
            報 = (float(後["收盤"].iloc[n - 1]) / 基 - 1) * 100
            超 = 報
            if 加 is not None:
                a, b = 加[加.index <= r["date"]], 加[加.index <= 後["date"].iloc[n - 1]]
                if len(a) and len(b):
                    超 = 報 - (float(b.iloc[-1]) / float(a.iloc[-1]) - 1) * 100
            列[名], 列[名.replace("%", "超額%")] = round(報, 1), round(超, 1)
        列們.append(列)
    return pd.DataFrame(列們).sort_values("法說日", ascending=False).reset_index(drop=True)


def 讀取法說會():
    return _讀("calendar.csv", dtype={"code": str}, parse_dates=["date"])


# ========== 網友 juju 盤勢筆記（2026-11）：月 K 連跌、大盤融資維持率距警戒線、大盤融資洗盤日 ==========
def 月線連跌統計(K):
    """日 K 轉月 K：目前連跌幾個月、今年跌了幾個月，以及過去「前兩個月漲、這個月跌」之後下個月怎麼走。
    網紅說「月 K 今年沒有連跌兩個月」，這裡把它變成看得到的數字。回傳 (目前 dict, 歷次 DataFrame, 彙總 dict)。"""
    k = K.set_index("date")["close"].astype(float)
    月 = k.resample("ME").last().dropna()
    報 = (月.pct_change() * 100).dropna()
    最後日 = k.index.max()
    完整 = 最後日 >= (最後日 + pd.offsets.MonthEnd(0) - pd.offsets.BDay(1))  # 月底前最後一兩個交易日才算收完
    已收 = 報 if 完整 else 報.iloc[:-1]          # 只用收完的月份算連跌，本月另外顯示
    已跌 = 已收 < 0
    連 = 已跌.groupby((~已跌).cumsum()).cumsum()
    今年 = 已收[已收.index.year == 報.index[-1].year]
    今年跌 = 今年 < 0
    今年最長 = int(今年跌.groupby((~今年跌).cumsum()).cumsum().max()) if len(今年) else 0
    目前 = {"月份": 報.index[-1], "本月%": round(float(報.iloc[-1]), 1), "本月完整": bool(完整),
            "連跌月數": int(連.iloc[-1]) if len(連) else 0, "今年跌月數": int(今年跌.sum()), "今年月數": int(len(今年)),
            "今年最長連跌": 今年最長, "連跌兩月次數": int((已跌 & 已跌.shift(1, fill_value=False)).sum()),
            "總月數": int(len(已收))}
    條件 = (已收 < 0) & (已收.shift(1) > 0) & (已收.shift(2) > 0)
    列們 = []
    for d in 已收.index[條件]:
        i = 報.index.get_loc(d)
        下 = 報.iloc[i + 1] if i + 1 < len(報) and (i + 1 < len(已收)) else np.nan
        列們.append({"月份": d, "前兩月%": round(float(已收.iloc[i - 2] / 100 + 1) * (已收.iloc[i - 1] / 100 + 1) * 100 - 100, 1),
                    "當月%": round(float(已收.iloc[i]), 1), "下月%": round(float(下), 1) if pd.notna(下) else np.nan})
    歷 = pd.DataFrame(列們)
    彙 = {}
    if len(歷) and 歷["下月%"].notna().any():
        x = 歷["下月%"].dropna()
        彙 = {"次數": int(len(x)), "上漲次數": int((x > 0).sum()), "上漲機率%": round(float((x > 0).mean() * 100)),
             "平均%": round(float(x.mean()), 1), "中位數%": round(float(x.median()), 1), "最差%": float(x.min()), "最好%": float(x.max())}
    return 目前, 歷, 彙


def 維持率警戒點位(維持率, 加權收盤, 官方=None, 警戒=(165, 150, 130)):
    """融資股票大致跟著大盤跌時，維持率要降到 165%／150%／130%，加權約要跌到幾點。
    官方＝證交所／金管會公布的整戶維持率（有填就用它當基準，網站估算只用來算比例）。
    回傳 [(警戒線, 加權約略點位, 還要跌%)]；已經低於的線不列。融資股通常跌得比大盤重，實際會更早到。"""
    基 = float(官方) if 官方 else float(維持率)
    if not 基 or not 加權收盤:
        return []
    return [(線, round(加權收盤 * 線 / 基), round((線 / 基 - 1) * 100, 1)) for 線 in 警戒 if 線 < 基]


def 大盤融資變化(表, 代號欄="code", 價欄="close", 融資欄="margin"):
    """全市場（四碼普通股）融資餘額每天增減的百分比，用「張數變化 × 當天收盤」加權，不受股價漲跌影響：
    Σ(今天張數 − 昨天張數) × 收盤 ÷ Σ 昨天張數 × 收盤。面額分割當天張數暴增的股票不算。回傳 Series（%，index＝date）。"""
    if 表 is None or 融資欄 not in 表.columns:
        return pd.Series(dtype=float)
    t = 表[[代號欄, "date", 價欄, 融資欄]].copy()
    t = t[t[代號欄].astype(str).str.fullmatch(r"\d{4}")].sort_values([代號欄, "date"])
    t[融資欄] = t[融資欄].astype("float64")
    前 = t.groupby(代號欄, sort=False)[融資欄].shift()
    有 = 前.notna() & t[融資欄].notna() & (前 > 0) & (t[融資欄] < 前 * 2.5)
    價 = t[價欄].astype("float64")
    分子 = ((t[融資欄] - 前) * 價)[有].groupby(t.loc[有, "date"]).sum()
    分母 = (前 * 價)[有].groupby(t.loc[有, "date"]).sum()
    return (分子 / 分母.where(分母 > 0) * 100).dropna().round(2)


def 融資洗盤統計(變化, K, 門檻=-1.5, 間隔天數=14, 天數=(5, 20, 60)):
    """大盤融資單日減少超過 門檻%（融資洗盤日）之後，加權 5／20／60 個交易日的漲跌，對照「任何一天買進」的平均。
    同一段（間隔天數內）只算第一次。回傳 dict(門檻, 次數, 每期統計, 事件)。"""
    c = K.set_index("date")["close"].astype(float)
    事件, 上次 = [], None
    for d, v in 變化[變化 <= 門檻].items():
        if d not in c.index:
            continue
        if 上次 is None or (d - 上次).days > 間隔天數:
            事件.append((d, float(v)))
            上次 = d
    統計 = []
    for n in 天數:
        後 = (c.shift(-n) / c - 1) * 100
        x = 後.reindex([d for d, _ in 事件]).dropna()
        基 = 後.dropna()
        統計.append({"天數": n, "次數": int(len(x)), "平均%": round(float(x.mean()), 2) if len(x) else None,
                   "上漲機率%": round(float((x > 0).mean() * 100)) if len(x) else None,
                   "基準平均%": round(float(基.mean()), 2), "基準上漲機率%": round(float((基 > 0).mean() * 100))})
    明細 = [{"date": f"{d:%Y-%m-%d}", "融資%": round(v, 2),
             **{f"{n}日後%": (round(float(c.shift(-n).get(d) / c[d] * 100 - 100), 1) if pd.notna(c.shift(-n).get(d)) else None)
                for n in 天數}} for d, v in 事件]
    return {"門檻": 門檻, "次數": len(事件), "統計": 統計, "事件": 明細}


def 更新大盤融資洗盤(強制=False, 間隔天數=25):
    """GitHub Actions 呼叫：用全部歷史算大盤融資每日增減與洗盤日回測 → data/margin_flush.json（約每月重算）。"""
    import json
    檔 = 資料夾 / "margin_flush.json"
    if 檔.exists() and not 強制:
        舊 = json.loads(檔.read_text())
        if (pd.Timestamp.now() - pd.Timestamp(舊.get("計算日", "2000-01-01"))).days < 間隔天數 and "恐慌日" in 舊 \
                and "正2背離" in 舊:
            print("大盤融資洗盤：還不用重算")
            return
    表 = 讀取資料庫()
    變 = 大盤融資變化(表)
    del 表
    釋放記憶體()
    K = 讀取指數K線("TAIEX")
    結果 = {"計算日": f"{pd.Timestamp.now():%Y-%m-%d}", "起": f"{變.index.min():%Y-%m-%d}", "迄": f"{變.index.max():%Y-%m-%d}",
            "最大單日減%": round(float(變.min()), 2),
            "分位": {f"{q:g}": round(float(變.quantile(q)), 2) for q in (0.01, 0.05, 0.1)},
            "洗盤": 融資洗盤統計(變, K, -1.5), "大洗盤": 融資洗盤統計(變, K, -2.5),
            "減幅比": 融資減幅比回測(融資減幅比序列(變, K), K),
            "恐慌日": 恐慌日統計(K, 變)}
    正2每日, _ = 正2融資明細(讀取資料庫(代號=list(台股正2)))
    結果["正2背離"] = 正2背離統計(變, 正2每日, K)
    檔.write_text(json.dumps(結果, ensure_ascii=False, indent=1))
    print(f"大盤融資洗盤：{結果['洗盤']['次數']} 次（≤ −1.5%）")


def 讀取大盤融資洗盤():
    import json
    檔 = 資料夾 / "margin_flush.json"
    return json.loads(檔.read_text()) if 檔.exists() else None


# ========== 21. 新聞事件工具：舊聞提醒、全部重訊、事件反應、消息先走、金額換算、海外布局、業外損益 ==========
def _字組(文字):
    """標題的「兩字一組」集合，用來比對兩則新聞是不是講同一件事。"""
    字 = re.sub(r"[\s\W_]+", "", str(文字))
    return {字[i:i + 2] for i in range(len(字) - 1)}


def 新聞舊聞標記(新聞, 今天=None, 門檻天數=30, 相似度=0.5):
    """新聞表加三欄：天數（發布至今幾天）、舊聞（超過 門檻天數）、首見日（同一件事最早出現的日期，
    比 門檻天數 更早才填，代表這則是「舊聞重提」）。"""
    if 新聞 is None or not len(新聞):
        return 新聞
    t = 新聞.copy()
    今天 = pd.Timestamp(今天 or pd.Timestamp.now(tz="Asia/Taipei").tz_localize(None)).normalize()
    t["天數"] = (今天 - t["日期"].dt.normalize()).dt.days.clip(lower=0)
    t["舊聞"] = t["天數"] > 門檻天數
    組 = [_字組(x) for x in t["標題"]]
    首見 = []
    for i, (日, a) in enumerate(zip(t["日期"], 組)):
        最早 = pd.NaT
        for j, (日2, b) in enumerate(zip(t["日期"], 組)):
            if j == i or not a or not b or 日2 >= 日 - pd.Timedelta(days=門檻天數):
                continue
            if len(a & b) / min(len(a), len(b)) >= 相似度 and (pd.isna(最早) or 日2 < 最早):
                最早 = 日2
        首見.append(最早)
    t["首見日"] = 首見
    return t


def 新聞日期標籤(x, 格式="%m/%d"):
    """新聞清單、AI 提示用的日期標籤：近 30 天只寫日期；更早的加「N 天前」；舊聞重提註明首見日。"""
    字 = x["日期"].strftime(格式)
    if x.get("舊聞"):
        字 += f"（{x['天數']} 天前・舊聞）"
    if pd.notna(x.get("首見日")):
        字 += f"（舊聞重提，{x['首見日']:%Y/%m/%d} 已報導過）"
    return 字


def 讀取全部重訊(代號=None, 天數=120):
    """data/material_news/YYYY-MM.csv.gz：公開資訊觀測站每天全部重大訊息（date, time, code, name, subject）；
    另外合併舊的 material_news.csv（只有承銷、掛牌等關鍵字的）。新到舊排序。"""
    起 = pd.Timestamp.now().normalize() - pd.Timedelta(days=天數)
    檔們 = [f for f in sorted((資料夾 / "material_news").glob("*.csv.gz")) if f.name[:7] >= f"{起:%Y-%m}"]
    表們 = [pd.read_csv(f, dtype={"code": str}, parse_dates=["date"]) for f in 檔們]
    舊 = 讀取重大訊息()
    if 舊 is not None:
        表們.append(舊)
    if not 表們:
        return None
    t = pd.concat(表們, ignore_index=True)
    t = t[t["date"] >= 起]
    if 代號 is not None:
        t = t[t["code"] == str(代號)]
    t = t.drop_duplicates(["date", "code", "subject"])
    return t.sort_values(["date", "time"], ascending=False).reset_index(drop=True) if len(t) else None


def 事件反應(價, 指數, 代號們, 事件日, 前置日=None, 天數們=(1, 5, 20)):
    """事件前後的漲跌幅（%）與減掉大盤後的超額（%）。
    價：讀取資料庫() 的表（date, code, name, close, change）；指數：讀取指數K線() 的表（date, close）。
    事件日＝正式公告「之後第一個能反應的交易日」（盤後公告就填隔天）；前置日＝媒體先報導的那天（可省略）。
    回傳 DataFrame：代號、名稱、前置日漲跌、事件日漲跌、事件後 N 日漲跌（從事件日收盤起算）、各自的超額。"""
    事件日 = pd.Timestamp(事件日)
    前置日 = pd.Timestamp(前置日) if 前置日 is not None and pd.notna(前置日) else None
    指 = 指數.set_index("date")["close"].sort_index()
    指報酬 = 指.pct_change()

    def 第一個交易日(序列索引, 日):
        後 = 序列索引[序列索引 >= 日]
        return 後[0] if len(後) else None

    列們 = []
    for c in 代號們:
        p = 價[價["code"] == str(c)].sort_values("date").set_index("date")
        if p.empty:
            continue
        前收 = p["close"] - p["change"]
        日報 = (p["change"] / 前收).where(前收 > 0).fillna(p["close"].pct_change()).clip(-0.105, 0.105)
        還原 = (1 + 日報.fillna(0)).cumprod()
        列 = {"代號": str(c), "名稱": p["name"].iloc[-1]}
        d0 = 第一個交易日(p.index, 事件日)
        if d0 is None:
            continue
        列["事件日"] = d0
        if 前置日 is not None:
            d = 第一個交易日(p.index, 前置日)
            if d is not None and d < d0:
                列["前置日漲跌%"] = 日報.get(d, np.nan) * 100
                列["前置日超額%"] = 列["前置日漲跌%"] - 指報酬.get(d, np.nan) * 100
        列["事件日漲跌%"] = 日報.get(d0, np.nan) * 100
        列["事件日超額%"] = 列["事件日漲跌%"] - 指報酬.get(d0, np.nan) * 100
        位 = p.index.get_loc(d0)
        for n in 天數們:
            if 位 + n < len(p):
                d = p.index[位 + n]
                漲 = (還原.iloc[位 + n] / 還原.iloc[位] - 1) * 100
                列[f"後{n}日漲跌%"] = 漲
                if d0 in 指.index and d in 指.index:
                    列[f"後{n}日超額%"] = 漲 - (指[d] / 指[d0] - 1) * 100
        列們.append(列)
    return pd.DataFrame(列們)


事件範本 = [
    {"名稱": "台積電、Sony 熊本合資影像感測器廠", "代號": "2330,3374,6789,6271,3530",
     "前置日": "2026-08-10", "事件日": "2026-08-12",
     "說明": "8/10 媒體先報導，8/11 盤後董事會通過並發新聞稿（台積電新聞 3333），所以反應日是 8/12。"},
]


def 消息先走統計(結果們):
    """多個事件的 事件反應() 結果合併後，看「媒體先報那天」跟「正式公告之後」哪個反應大。
    結果們：[(事件名稱, DataFrame), …]。回傳 (每個事件的平均表, 總結 dict)。"""
    列們 = []
    for 名, t in 結果們:
        if t is None or not len(t):
            continue
        列 = {"事件": 名, "檔數": len(t)}
        for 欄 in ("前置日超額%", "事件日超額%", "後5日超額%", "後20日超額%"):
            if 欄 in t.columns and t[欄].notna().any():
                列[欄] = float(t[欄].mean())
        列們.append(列)
    表 = pd.DataFrame(列們)
    if 表.empty:
        return 表, {}
    總 = {"事件數": len(表)}
    for 欄 in ("前置日超額%", "事件日超額%", "後5日超額%", "後20日超額%"):
        if 欄 in 表.columns and 表[欄].notna().any():
            總[欄] = float(表[欄].mean())
    if "後20日超額%" in 表.columns and 表["後20日超額%"].notna().any():
        總["利多出盡比例%"] = float((表["後20日超額%"].dropna() < 0).mean() * 100)
    if "前置日超額%" in 表.columns and 表["前置日超額%"].notna().any():
        有 = 表.dropna(subset=["前置日超額%", "事件日超額%"])
        總["先走事件數"] = int((有["前置日超額%"].abs() > 有["事件日超額%"].abs()).sum())
        總["有前置日事件數"] = len(有)
    return 表, 總


def 財務規模(代號):
    """換算投資金額用的分母（台幣億元）：近四季營收、近四季投資現金流（資本支出的近似）、淨值、期末現金。"""
    結果 = {}
    營 = _讀("fundamental/revenue_history.csv", dtype={"code": str})
    if 營 is not None:
        近 = 營[營["code"] == str(代號)].sort_values("month").tail(12)
        if len(近) == 12:
            結果["近四季營收"] = float(近["revenue"].sum()) / 1e5
    財 = 讀取財報(代號)
    if 財 is not None and len(財):
        財 = 財.sort_values("quarter")
        if "cfi" in 財 and 財["cfi"].tail(4).notna().sum() == 4:
            結果["近四季投資支出"] = float(-財["cfi"].tail(4).sum()) / 1e5
        if "equity" in 財 and 財["equity"].notna().any():
            結果["淨值"] = float(財["equity"].dropna().iloc[-1]) / 1e5
        if "cash_end" in 財 and 財["cash_end"].notna().any():
            結果["期末現金"] = float(財["cash_end"].dropna().iloc[-1]) / 1e5
    return 結果


def 投資金額換算(金額, 匯率, 規模, 市值億=None):
    """金額（外幣，單位：億）× 匯率 → 台幣億元，再換算成占公司各項規模的比例。回傳 (台幣億, DataFrame)。"""
    台幣 = float(金額) * float(匯率)
    分母 = dict(規模)
    if 市值億:
        分母["市值"] = float(市值億)
    名稱 = {"近四季營收": "近四季營收", "近四季投資支出": "近四季投資支出（資本支出近似）", "淨值": "淨值（股東權益）",
          "期末現金": "期末現金", "市值": "市值"}
    列們 = [{"比較對象": 名稱[k], "金額(億)": v, "占比%": 台幣 / v * 100 if v and v > 0 else np.nan}
           for k, v in 分母.items() if k in 名稱]
    return 台幣, pd.DataFrame(列們)


def 讀取海外布局(代號=None):
    """data/overseas.csv：自己整理的海外廠、合資與轉投資（code, item, region, kind, stake, invest, timeline, status, note, source）。"""
    t = _讀("overseas.csv", dtype={"code": str})
    if t is None:
        return None
    if 代號 is not None:
        t = t[t["code"] == str(代號)]
    return t.reset_index(drop=True) if len(t) else None


def 業外損益(代號):
    """各季單季的營業利益、業外收支、稅前淨利（億元）與業外占稅前比例；採權益法的投資損益（合資、轉投資）就在業外裡。
    income.csv 是今年累計數，這裡相減成單季。沒有 nonop 欄（舊資料）就回傳 None。"""
    t = _讀("fundamental/income.csv", dtype={"code": str})
    if t is None or "nonop" not in t.columns:
        return None
    t = t[t["code"] == str(代號)].sort_values("quarter").copy()
    if t["nonop"].notna().sum() == 0:
        return None
    年, 季 = t["quarter"].str[:4], t["quarter"].str[-1].astype(int)
    前季 = 季.groupby(年).shift()
    for 欄 in ("opinc", "nonop", "pretax", "netinc"):
        if 欄 not in t.columns:
            t[欄] = np.nan
        前 = t[欄].groupby(年).shift()
        t[欄] = np.where(季 == 1, t[欄], np.where(前季 == 季 - 1, t[欄] - 前, np.nan))
    結果 = pd.DataFrame({"季度": t["quarter"], "營業利益(億)": t["opinc"] / 1e5, "業外收支(億)": t["nonop"] / 1e5,
                       "稅前淨利(億)": t["pretax"] / 1e5, "稅後淨利(億)": t["netinc"] / 1e5})
    結果["業外占稅前%"] = (結果["業外收支(億)"] / 結果["稅前淨利(億)"] * 100).where(結果["稅前淨利(億)"] > 0)
    return 結果.dropna(subset=["業外收支(億)"]).reset_index(drop=True)


# ========== 33. 網紅摘要 11/07 建議 5、6：加權大跌日收復表、權值股跌停打開回測 ==========
def 大跌日收復表(K, 跌幅門檻=-3.0, 天數=(5, 20, 60)):
    """加權單日跌幅 ≤ 跌幅門檻% 的日子：之後 N 日漲跌、幾個交易日收復大跌前一天收盤、之後最深再跌多少。
    K：讀取指數K線() 的 DataFrame（date, close…）。回傳 DataFrame，新的在上面。"""
    if K is None or len(K) < 2:
        return pd.DataFrame()
    k = K[["date", "close"]].dropna().reset_index(drop=True)
    收 = k["close"].to_numpy(dtype="float64")
    列們 = []
    for i in range(1, len(k)):
        前, 今 = 收[i - 1], 收[i]
        跌點, 跌幅 = 今 - 前, (今 / 前 - 1) * 100
        if 跌幅 > 跌幅門檻:
            continue
        後 = 收[i + 1:]
        回 = np.nonzero(後 >= 前)[0]
        列 = {"日期": k.at[i, "date"], "收盤": round(今, 2), "跌點": round(跌點, 2), "跌幅%": round(跌幅, 2),
              "收復天數": int(回[0]) + 1 if len(回) else None,
              "之後最深%": round(min(0.0, (後[: 回[0] + 1 if len(回) else len(後)].min() / 今 - 1) * 100), 2) if len(後) else None}
        for n in 天數:
            列[f"{n}日後%"] = round((收[i + n] / 今 - 1) * 100, 2) if i + n < len(收) else None
        列們.append(列)
    return pd.DataFrame(列們).iloc[::-1].reset_index(drop=True)


def 大跌日統計(表, 天數=(5, 20, 60)):
    """大跌日收復表() 的平均：次數、已收復次數、收復天數中位數、N 日後平均與上漲機率。"""
    if 表 is None or not len(表):
        return {}
    統 = {"次數": len(表), "已收復": int(表["收復天數"].notna().sum()),
          "收復天數中位數": float(表["收復天數"].median()) if 表["收復天數"].notna().any() else None}
    for n in 天數:
        s = 表[f"{n}日後%"].dropna()
        統[f"{n}日"] = {"次數": len(s), "平均%": round(float(s.mean()), 2) if len(s) else None,
                        "上漲機率%": round(float((s > 0).mean() * 100)) if len(s) else None}
    return 統


def 跌停打開事件(價, 拉回門檻=5.0, 天數=(5, 20, 60)):
    """個股當天最低價碰到跌停（≤ 前收 × 0.905）的日子，分成「打開」（收盤從最低拉回 ≥ 拉回門檻%）與「沒打開」，之後 N 日報酬。
    同時算這些股票「任何一天買進」的 N 日平均當基準。價：code、date、low、close（可多檔）。
    回傳 (事件 DataFrame, 基準 dict{n: 平均%})。"""
    if 價 is None or not len(價):
        return pd.DataFrame(), {}
    t = 價[["code", "date", "low", "close"]].dropna().sort_values(["code", "date"]).reset_index(drop=True)
    t[["low", "close"]] = t[["low", "close"]].astype("float64")
    g = t.groupby("code")["close"]
    t["前收"] = g.shift(1)
    for n in 天數:
        t[f"{n}日後%"] = (g.shift(-n) / t["close"] - 1) * 100
    事 = t[t["low"] <= t["前收"] * 0.905].copy()
    事["當天%"] = (事["close"] / 事["前收"] - 1) * 100
    事["從低點拉回%"] = (事["close"] / 事["low"] - 1) * 100
    事["類型"] = np.where(事["從低點拉回%"] >= 拉回門檻, "打開", "沒打開")
    基準 = {n: round(float(t[f"{n}日後%"].mean()), 2) for n in 天數}
    數欄 = ["前收", "low", "close", "當天%", "從低點拉回%"] + [f"{n}日後%" for n in 天數]
    事[數欄] = 事[數欄].round(2)
    事 = 事[["date", "code", "類型"] + 數欄].rename(columns={"date": "日期", "code": "代號", "low": "最低", "close": "收盤"})
    return 事.sort_values("日期", ascending=False).reset_index(drop=True), 基準


def 跌停打開統計(事, 基準, 天數=(5, 20, 60)):
    """跌停打開事件() 依「打開／沒打開」分組：次數、N 日後平均與上漲機率，和任何一天買進比。"""
    列們 = []
    for 類, g in ([("全部", 事)] + list(事.groupby("類型"))) if len(事) else []:
        列 = {"類型": 類, "次數": len(g), "不同日期": g["日期"].nunique()}
        for n in 天數:
            s = g[f"{n}日後%"].dropna()
            列[f"{n}日後平均%"] = round(float(s.mean()), 2) if len(s) else None
            列[f"{n}日上漲機率%"] = round(float((s > 0).mean() * 100)) if len(s) else None
        列們.append(列)
    if 列們:
        列們.append({"類型": "任何一天買進", "次數": None, "不同日期": None, **{f"{n}日後平均%": 基準.get(n) for n in 天數}})
    return pd.DataFrame(列們)


def 讀取跌停打開事件(代號們=None, 拉回門檻=5.0):
    """0050 成分股（沒有名單就只看台積電）近 5 年的跌停打開事件，名稱一起帶上。"""
    代號們 = 代號們 or 讀取0050成分() or ["2330"]
    價 = _讀每日檔("prices", 代號=代號們, 起日=pd.Timestamp.today() - pd.Timedelta(days=365 * 5 + 30))
    if 價 is None or not len(價):
        return pd.DataFrame(), {}
    事, 基準 = 跌停打開事件(價, 拉回門檻)
    名 = 價.drop_duplicates("code", keep="last").set_index("code")["name"] if "name" in 價 else None
    if 名 is not None and len(事):
        事.insert(2, "名稱", 事["代號"].map(名))
    return 事, 基準


# ========== 31. 網紅摘要 11/04 建議：止跌三階段、融資減幅比、三條件抄底、摘要混稿偵測 ==========
def 止跌三階段(K, 低點天數=20, 確認天數=3):
    """通勤族（阿信）的大盤止跌三階段：① 不再創新低 → ② 收盤站回 5 日線 → ③ 5 日線往上穿過 10 日線。
    K：date、low、close（原始價，依日期排）。回傳 dict(階段們=[(名, 燈, 說)], 已到第幾階段, 站回5日需, 金叉需, 低點, 低點日)；資料不夠回 None。
    「站回5日需」＝下一個交易日收盤要高於多少，收盤才會在 5 日線之上；「金叉需」＝收多少 5 日線才會高過 10 日線。"""
    if K is None or len(K) < max(低點天數, 10) + 1:
        return None
    K = K.reset_index(drop=True)
    c = K["close"].astype(float)
    低 = (K["low"] if "low" in K.columns else K["close"]).astype(float)
    近 = 低.tail(低點天數)
    低點, 低點位 = float(近.min()), int(近.idxmin())
    沒破天數 = len(K) - 1 - 低點位
    ma5, ma10 = float(c.tail(5).mean()), float(c.tail(10).mean())
    收 = float(c.iloc[-1])
    S4, S9 = float(c.tail(4).sum()), float(c.tail(9).sum())
    站回需 = S4 / 4                 # 明天收 X：X > (S4+X)/5 ⇔ X > S4/4
    金叉需 = S9 - 2 * S4            # (S4+X)/5 > (S9+X)/10 ⇔ X > S9 − 2·S4
    一 = 沒破天數 >= 確認天數
    二 = 收 > ma5
    三 = ma5 > ma10
    日 = K["date"].iloc[低點位]
    階段們 = [
        ("① 不再創新低", "🟢" if 一 else ("🟡" if 沒破天數 >= 1 else "🔴"),
         f"近 {低點天數} 日低點 {低點:,.0f}（{日:%m/%d}），" + (f"已經 {沒破天數} 天沒跌破" if 沒破天數 else "今天剛創新低")
         + ("" if 一 else f"，要連 {確認天數} 天不破才算")),
        ("② 站回 5 日線", "🟢" if 二 else "🔴",
         f"收盤 {收:,.0f}、5 日線 {ma5:,.0f}" + ("，已站上" if 二 else f"；下個交易日收 {站回需:,.0f} 以上才站回（差 {(站回需 / 收 - 1) * 100:+.1f}%）")),
        ("③ 5 日線穿過 10 日線", "🟢" if 三 else "🔴",
         f"5 日線 {ma5:,.0f}、10 日線 {ma10:,.0f}" + ("，已在上方" if 三 else (
             f"；下個交易日收 {金叉需:,.0f} 以上才會交叉" if 金叉需 <= 收 * 1.1 else "；差距還大，一天內不可能交叉，要等幾天均線扣抵下來"))),
    ]
    已到 = 3 if (一 and 二 and 三) else (2 if (一 and 二) else (1 if 一 else 0))
    return {"階段們": 階段們, "已到": 已到, "站回5日需": round(站回需, 2), "金叉需": round(金叉需, 2),
            "低點": 低點, "低點日": 日}


def 止跌三階段回測(K, 跌深=-8.0, 窗=60, 天數=(5, 20, 60), 間隔=20):
    """過去「指數距 60 日高點跌超過 跌深%」之後，第一次三階段全部成立那天買進，之後 N 日加權漲跌，對照任何一天。
    回傳 dict(次數, 統計=[{天數, 次數, 平均%, 上漲機率%, 基準平均%, 基準上漲機率%}], 事件=[...])。"""
    if K is None or len(K) < 120:
        return None
    K = K.reset_index(drop=True)
    c = K["close"].astype(float)
    低 = (K["low"] if "low" in K.columns else K["close"]).astype(float)
    跌幅 = (c / c.rolling(窗, min_periods=20).max() - 1) * 100
    低點位 = 低.rolling(20).apply(lambda s: len(s) - 1 - int(np.argmin(s)), raw=True)
    ma5, ma10 = c.rolling(5).mean(), c.rolling(10).mean()
    全 = (低點位 >= 3) & (c > ma5) & (ma5 > ma10)
    # 跌深條件看「最近 20 天內曾經跌深」，止跌當天通常已經反彈一點
    曾深 = (跌幅.rolling(20, min_periods=1).min() <= 跌深)
    事件, 上次 = [], -10 ** 9
    for i in np.flatnonzero((全 & 曾深).to_numpy()):
        if i - 上次 > 間隔:
            事件.append(i)
            上次 = i
    統計 = []
    for n in 天數:
        後 = (c.shift(-n) / c - 1) * 100
        x = 後.iloc[事件].dropna()
        統計.append({"天數": n, "次數": int(len(x)), "平均%": round(float(x.mean()), 2) if len(x) else None,
                   "上漲機率%": round(float((x > 0).mean() * 100)) if len(x) else None,
                   "基準平均%": round(float(後.mean()), 2), "基準上漲機率%": round(float((後.dropna() > 0).mean() * 100))})
    明細 = [{"date": f"{K['date'].iloc[i]:%Y-%m-%d}", "收盤": round(float(c.iloc[i])),
             **{f"{n}日後%": (round(float(c.iloc[i + n] / c.iloc[i] * 100 - 100), 1) if i + n < len(c) else None) for n in 天數}}
            for i in 事件]
    return {"次數": len(事件), "跌深": 跌深, "統計": 統計, "事件": 明細}


def 融資減幅比序列(變化, K, 窗=60, 前置=5):
    """鄭廳宜／吳嘉隆：「大盤跌 10%，融資餘額要減 7～8% 才算洗乾淨」。
    變化：大盤融資變化()（每天 %，張數 × 收盤加權，不受股價漲跌影響）；K：加權日 K。
    每天算：指數距近 窗 日收盤高點跌幅%、融資（從那個高點前 前置 天起算的最高）減幅%、比例＝融資減幅 ÷ 指數跌幅。
    回傳 DataFrame(index＝date；指數跌幅、融資減幅、比例、高點日)。"""
    if 變化 is None or K is None or not len(變化):
        return pd.DataFrame()
    c = K.set_index("date")["close"].astype(float)
    c = c[c.index >= 變化.index.min() - pd.Timedelta(days=1)]
    L = (1 + 變化.reindex(c.index).fillna(0) / 100).cumprod()
    列們 = []
    值c, 值L, 日們 = c.to_numpy(), L.to_numpy(), c.index
    for i in range(len(c)):
        a = max(0, i - 窗 + 1)
        p = a + int(np.argmax(值c[a:i + 1]))
        跌 = (值c[i] / 值c[p] - 1) * 100
        b = max(0, p - 前置)
        減 = (值L[i] / 值L[b:i + 1].max() - 1) * 100
        列們.append((日們[i], round(跌, 2), round(減, 2), round(減 / 跌, 2) if 跌 < -0.5 else np.nan, 日們[p]))
    return pd.DataFrame(列們, columns=["date", "指數跌幅", "融資減幅", "比例", "高點日"]).set_index("date")


def 融資減幅燈(列, 跌深=-8.0, 門檻=0.7):
    """融資減幅比的燈號與白話。列：融資減幅比序列() 的一列。"""
    跌, 減, 比 = 列["指數跌幅"], 列["融資減幅"], 列["比例"]
    if 跌 > 跌深:
        return "🟡", f"加權距高點只跌 {跌:+.1f}%（還沒到 {跌深:.0f}%），這個指標先不看"
    if 比 >= 門檻:
        return "🟢", f"加權跌 {跌:+.1f}%、融資減 {減:+.1f}%，比例 {比:.0%}，融資已經跟上跌幅（≥ {門檻:.0%}）"
    return "🔴", f"加權跌 {跌:+.1f}%、融資只減 {減:+.1f}%，比例 {比:.0%}，還沒到 {門檻:.0%}（融資約還要再減 {跌 * 門檻 - 減:+.1f} 個百分點）"


def 融資減幅比回測(序列, K, 跌深=-8.0, 門檻=0.7, 天數=(5, 20, 60), 間隔=20):
    """融資減幅比第一次亮綠燈（指數跌超過 跌深%、比例 ≥ 門檻）那天買進加權，之後 N 日漲跌，對照任何一天。"""
    if 序列 is None or not len(序列):
        return None
    c = K.set_index("date")["close"].astype(float)
    綠 = (序列["指數跌幅"] <= 跌深) & (序列["比例"] >= 門檻)
    事件, 上次 = [], None
    位 = {d: i for i, d in enumerate(c.index)}
    for d in 綠[綠].index:
        if d not in 位:
            continue
        if 上次 is None or 位[d] - 上次 > 間隔:
            事件.append(d)
            上次 = 位[d]
    統計 = []
    for n in 天數:
        後 = (c.shift(-n) / c - 1) * 100
        後 = 後[後.index >= 序列.index.min()]
        x = 後.reindex(事件).dropna()
        統計.append({"天數": n, "次數": int(len(x)), "平均%": round(float(x.mean()), 2) if len(x) else None,
                   "上漲機率%": round(float((x > 0).mean() * 100)) if len(x) else None,
                   "基準平均%": round(float(後.mean()), 2), "基準上漲機率%": round(float((後.dropna() > 0).mean() * 100))})
    明細 = [{"date": f"{d:%Y-%m-%d}", "指數跌幅%": float(序列.at[d, "指數跌幅"]), "融資減幅%": float(序列.at[d, "融資減幅"]),
             **{f"{n}日後%": (round(float(c.shift(-n).get(d) / c[d] * 100 - 100), 1) if pd.notna(c.shift(-n).get(d)) else None)
                for n in 天數}} for d in 事件]
    return {"門檻": 門檻, "跌深": 跌深, "次數": len(事件), "統計": 統計, "事件": 明細}


def 長均線距離(歷史):
    """每檔最新一天距 年線（240 日）、月線 10MA（10 個月底收盤平均，含本月）、72 週線（72 個週收盤平均，含本週）的 %。
    歷史：讀取資料庫() 的原始表（code、date、close），要有 1 年半以上。回傳 DataFrame(index＝代號)。"""
    t = 歷史[["code", "date", "close"]].dropna()
    t = t[t["close"] > 0].sort_values(["code", "date"])
    列們 = {}
    for code, g in t.groupby("code", sort=False):
        s = g.set_index("date")["close"].astype(float)
        if len(s) < 240:
            continue
        收 = float(s.iloc[-1])
        年 = float(s.tail(240).mean())
        月 = s.resample("ME").last().dropna()
        週 = s.resample("W").last().dropna()
        列們[code] = {"收盤": 收, "年線": round(年, 2),
                    "月10MA": round(float(月.tail(10).mean()), 2) if len(月) >= 10 else np.nan,
                    "72週線": round(float(週.tail(72).mean()), 2) if len(週) >= 72 else np.nan}
    表 = pd.DataFrame.from_dict(列們, orient="index")
    for 欄 in ("年線", "月10MA", "72週線"):
        if 欄 in 表:
            表[f"距{欄}%"] = ((表["收盤"] / 表[欄] - 1) * 100).round(1)
    return 表


def 抄底三條件(今日, 距離, 營收年增, 距離上限=3.0, 融資減門檻=-10.0):
    """通勤族（阿信）選股法：① 技術面跌到長均線支撐（距 年線／月 10MA／72 週線 ±距離上限% 內，任一條）、
    ② 基本面沒壞（近 3 個月營收年增 > 0）、③ 籌碼面融資已洗（🧹 融資洗完，或融資 20 日減少 ≥ 10%）。
    今日：最新一天指標（代號、名稱、收盤、融資20日增減、融資洗完…）；距離：長均線距離()；營收年增：{代號: 近3月年增%}。"""
    if 今日 is None or 距離 is None or not len(距離):
        return pd.DataFrame()
    t = 今日[今日["代號"].isin(距離.index)].copy()
    t = t.join(距離.drop(columns=["收盤"], errors="ignore"), on="代號")
    t["近3月營收年增"] = t["代號"].map(營收年增)
    支撐們 = []
    for _, r in t.iterrows():
        近 = [名 for 名 in ("年線", "月10MA", "72週線") if pd.notna(r.get(f"距{名}%")) and abs(r[f"距{名}%"]) <= 距離上限]
        支撐們.append("、".join(近))
    t["靠近支撐"] = 支撐們
    洗 = t["融資洗完"].astype(bool) if "融資洗完" in t.columns else False
    減 = t["融資20日增減"] <= 融資減門檻 if "融資20日增減" in t.columns else False
    量 = t["融資餘額"] >= 200 if "融資餘額" in t.columns else True
    t["融資"] = np.where(洗, "🧹 融資洗完", np.where(減, "融資 20 日減 10% 以上", ""))
    t = t[(t["靠近支撐"] != "") & (t["近3月營收年增"] > 0) & (洗 | 減) & 量]
    欄 = [c for c in ["代號", "名稱", "產業", "收盤", "靠近支撐", "距年線%", "距月10MA%", "距72週線%", "近3月營收年增",
                     "融資", "融資20日增減", "融資維持率", "本益比"] if c in t.columns]
    return t[欄].sort_values("近3月營收年增", ascending=False).reset_index(drop=True)


def 摘要混稿偵測(影片們, 天數差=1, 最少共同=3, 相似門檻=0.55):
    """同一天（前後 天數差 天）不同頻道的摘要，點名的股票重疊很多、理由句子又很像，可能是同一支影片被重複整理，
    或 Gemini 把兩支影片混在一起（2026-11-04 優分析 × 賺錢放大術）。這種要只算一次，否則「網紅共識」會灌水。
    回傳 [{日期, 頻道A, 頻道B, 共同檔數, 共同股票, 理由相似度}]，相似度 0～1（兩字一組的重疊比例）。"""
    結果 = []
    影們 = [v for v in 影片們 if v.get("股票")]
    for i, a in enumerate(影們):
        for b in 影們[i + 1:]:
            if a.get("頻道") == b.get("頻道"):
                continue
            try:
                差 = abs((pd.Timestamp(a.get("日期")) - pd.Timestamp(b.get("日期"))).days)
            except (TypeError, ValueError):
                continue
            if 差 > 天數差:
                continue
            A = {str(x.get("代號")): str(x.get("理由") or "") for x in a["股票"]}
            B = {str(x.get("代號")): str(x.get("理由") or "") for x in b["股票"]}
            共 = [k for k in A if k in B]
            if len(共) < 最少共同:
                continue
            分們 = []
            for k in 共:
                x, y = _字組(A[k]), _字組(B[k])
                if x and y:
                    分們.append(len(x & y) / min(len(x), len(y)))
            分 = float(np.mean(分們)) if 分們 else 0.0
            if 分 >= 相似門檻:
                名 = {str(x.get("代號")): x.get("名稱") or "" for x in a["股票"]}
                結果.append({"日期": max(str(a.get("日期")), str(b.get("日期"))), "頻道A": a.get("頻道"), "頻道B": b.get("頻道"),
                           "共同檔數": len(共), "共同股票": "、".join(名.get(k) or k for k in 共[:6]),
                           "理由相似度": round(分, 2)})
    return sorted(結果, key=lambda r: r["日期"], reverse=True)


# ========== 網紅摘要 2026-11-03：光通訊美台對照、全年 EPS 反推第四季、大盤恐慌日回測、漲跌停說法查核 ==========
光通訊美股 = ["Lumentum", "Coherent", "邁威爾"]
光通訊台股 = {"3081": "聯亞", "2455": "全新", "3105": "穩懋", "4979": "華星光", "3363": "上詮", "3450": "聯鈞",
          "4977": "眾達-KY", "6442": "光聖"}


def 光通訊美台對照(指標, 美股=None, 天數=120, 名單=光通訊台股):
    """通勤族 11/03：Lumentum 前一晚跌 18.6%，隔天聯亞、全新、穩懋全部跌停。
    每檔台股光通訊：今天漲跌、近 天數 天跟「前一晚」各美股光通訊的相關係數、Lumentum 漲 1% 隔天平均跟漲幾 %。
    回傳 (表, 美股最新 {名稱: (日期, 漲跌%)})。"""
    if 美股 is None:
        美股 = 讀取美股()
    if 美股 is None:
        return pd.DataFrame(), {}
    美報 = (美股[[c for c in 光通訊美股 if c in 美股]].pct_change(fill_method=None) * 100).dropna(how="all")
    if 美報.empty:
        return pd.DataFrame(), {}
    t = 指標[指標["代號"].isin(list(名單))][["date", "代號", "日報酬"]]
    台 = t.pivot_table(index="date", columns="代號", values="日報酬").sort_index() * 100
    if 台.empty:
        return pd.DataFrame(), {}
    前晚 = pd.merge_asof(pd.DataFrame({"date": 台.index}), 美報.rename_axis("date").reset_index(), on="date",
                       direction="backward", allow_exact_matches=False).set_index("date")
    近, 前 = 台.tail(天數), 前晚.reindex(台.tail(天數).index)
    列們 = []
    for 代 in 近.columns:
        y = 近[代]
        列 = {"代號": 代, "名稱": 名單.get(代, 代), "今天%": round(float(y.iloc[-1]), 2) if pd.notna(y.iloc[-1]) else np.nan}
        for c in 前.columns:
            列[f"對{c}相關"] = round(float(y.corr(前[c])), 2) if 前[c].notna().sum() > 20 else np.nan
        if "Lumentum" in 前 and 前["Lumentum"].var() > 0:
            x = 前["Lumentum"]
            列["Lumentum漲1%跟漲%"] = round(float(y.cov(x) / x.var()), 2)
        列們.append(列)
    表 = pd.DataFrame(列們)
    最新 = {c: (美報[c].dropna().index[-1], round(float(美報[c].dropna().iloc[-1]), 2)) for c in 美報.columns if 美報[c].notna().any()}
    if "Lumentum漲1%跟漲%" in 表 and "Lumentum" in 最新 and 最新["Lumentum"][0] >= 台.index[-1]:
        表["依今晚Lumentum推估%"] = (表["Lumentum漲1%跟漲%"] * 最新["Lumentum"][1]).clip(-10, 10).round(1)
    return 表.sort_values(表.columns[3] if len(表.columns) > 3 else "代號", ascending=False), 最新


def 全年EPS反推(代號, 全年EPS):
    """影片或券商說「今年 EPS 約 X 元」→ 用已公布的累計 EPS 算剩下的季度每季要賺多少（鈔錢部署 11/03：台達電 40.7 元）。
    回傳 dict 或 None：年度、已公布季數、累計EPS、剩下季數、剩下每季要賺、今年平均每季、倍數（要賺 ÷ 平均）、
    最近一季單季、去年全年、全年年增%。"""
    f = 資料夾 / "fundamental" / "income.csv"
    if not f.exists() or 全年EPS is None:
        return None
    t = pd.read_csv(f, dtype={"code": str})
    t = 調整分割EPS(t[t["code"] == str(代號)]).dropna(subset=["eps"]).sort_values("quarter")
    if t.empty:
        return None
    末 = t.iloc[-1]
    年, 季 = int(末["quarter"][:4]), int(末["quarter"][-1])
    if 季 >= 4:
        return {"年度": 年, "已公布季數": 4, "累計EPS": float(末["eps"]), "說明": f"{年} 年四季都已公布，全年 EPS {末['eps']:.2f} 元"}
    今年 = t[t["quarter"].str[:4] == str(年)].set_index("quarter")["eps"]
    前季 = 今年.get(f"{年}Q{季 - 1}") if 季 > 1 else 0.0
    單季 = float(末["eps"]) - float(前季) if 前季 is not None and pd.notna(前季) else np.nan
    去年 = t[t["quarter"] == f"{年 - 1}Q4"]["eps"]
    去年值 = float(去年.iloc[0]) if len(去年) else np.nan
    累計, 剩 = float(末["eps"]), 4 - 季
    要 = (float(全年EPS) - 累計) / 剩
    平均 = 累計 / 季
    return {"年度": 年, "已公布季數": 季, "累計EPS": round(累計, 2), "剩下季數": 剩, "剩下每季要賺": round(要, 2),
            "今年平均每季": round(平均, 2), "倍數": round(要 / 平均, 2) if 平均 > 0 else np.nan,
            "最近一季單季": round(單季, 2) if pd.notna(單季) else np.nan, "去年全年": 去年值,
            "全年年增%": round((float(全年EPS) / 去年值 - 1) * 100, 1) if 去年值 and 去年值 > 0 else np.nan}


def 恐慌日判斷(K, 跌幅=-2.0, 下影=0.3):
    """大盤「恐慌日」：跌超過 跌幅%，而且收在當天最低點附近（下影線 ≤ 下影%，收盤離最低點很近）。
    通勤族 11/03：前幾天開低會拉出下影線，今天一路殺到底、幾乎沒有下影線，才是真正的恐慌。回傳 DataFrame。"""
    k = K.sort_values("date").reset_index(drop=True)
    c, 低 = k["close"].astype(float), k["low"].astype(float)
    開 = k["open"].astype(float) if "open" in k else c
    k["漲跌%"] = ((c / c.shift() - 1) * 100).round(2)
    k["下影線%"] = ((np.minimum(開, c) - 低) / c * 100).round(2)
    k["恐慌日"] = (k["漲跌%"] <= 跌幅) & (k["下影線%"] <= 下影)
    return k


def 恐慌日統計(K, 融資變化=None, 跌幅=-2.0, 下影=0.3, 洗=-1.5, 天數=(5, 20, 60), 間隔天數=10):
    """恐慌日之後大盤怎麼走，再分「當天＋隔天融資合計減超過 洗%」與「融資沒洗」兩組。
    融資要等隔天晚上才知道，所以報酬一律從恐慌日「隔天收盤」算起，避免偷看。"""
    k = 恐慌日判斷(K, 跌幅, 下影).set_index("date")
    c = k["close"].astype(float)
    日們 = list(c.index)
    事件, 上次 = [], None
    for d in k.index[k["恐慌日"]]:
        if 上次 is not None and (d - 上次).days <= 間隔天數:
            continue
        上次 = d
        i = 日們.index(d)
        if i + 1 >= len(日們):
            事件.append({"date": d, "漲跌%": float(k.at[d, "漲跌%"]), "融資兩日%": np.nan, "起算": None})
            continue
        隔 = 日們[i + 1]
        融 = np.nan
        if 融資變化 is not None and len(融資變化):
            v = [融資變化.get(d), 融資變化.get(隔)]
            融 = round(float(np.nansum([x for x in v if x is not None])), 2) if any(x is not None for x in v) else np.nan
        事件.append({"date": d, "漲跌%": float(k.at[d, "漲跌%"]), "融資兩日%": 融, "起算": 隔})
    def 統(組):
        列們 = []
        for n in 天數:
            後 = (c.shift(-n) / c - 1) * 100
            x = 後.reindex([e["起算"] for e in 組 if e["起算"] is not None]).dropna()
            列們.append({"天數": n, "次數": int(len(x)), "平均%": round(float(x.mean()), 2) if len(x) else None,
                       "上漲機率%": round(float((x > 0).mean() * 100)) if len(x) else None})
        return 列們
    基準 = []
    for n in 天數:
        後 = ((c.shift(-n) / c - 1) * 100).dropna()
        基準.append({"天數": n, "平均%": round(float(後.mean()), 2), "上漲機率%": round(float((後 > 0).mean() * 100))})
    已洗 = [e for e in 事件 if pd.notna(e["融資兩日%"]) and e["融資兩日%"] <= 洗]
    沒洗 = [e for e in 事件 if pd.notna(e["融資兩日%"]) and e["融資兩日%"] > 洗]
    明細 = [{"date": f"{e['date']:%Y-%m-%d}", "漲跌%": e["漲跌%"], "融資兩日%": None if pd.isna(e["融資兩日%"]) else e["融資兩日%"],
             **{f"{n}日後%": (round(float(c.shift(-n).get(e["起算"]) / c[e["起算"]] * 100 - 100), 1)
                            if e["起算"] is not None and pd.notna(c.shift(-n).get(e["起算"])) else None) for n in 天數}}
            for e in 事件]
    return {"條件": {"跌幅": 跌幅, "下影線": 下影, "融資洗": 洗}, "次數": len(事件), "全部": 統(事件), "融資有洗": 統(已洗),
            "融資沒洗": 統(沒洗), "基準": 基準, "事件": 明細}


漲跌停門檻 = 0.095


def _拼音(字):
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return list(字)
    return [re.sub(r"ng$", "n", p) for p in lazy_pinyin(re.sub(r"[^一-鿿]", "", 字))]


def 同音分數(甲, 乙):
    """兩個名字念起來有多像（0～1）：逐字比拼音（不管聲調、ng／n 視為相同），取前面對齊的比例。
    用來抓「字幕把旺玖聽成忘久、Gemini 又對成萬泰科」這種同音錯字。"""
    a, b = _拼音(甲), _拼音(乙)
    if not a or not b:
        return 0.0
    中 = sum(1 for x, y in zip(a, b) if x == y)
    return round(中 / max(len(a), len(b)), 2)


def _候選字詞(x):
    """一則股票說法裡可能是「聽到的名字」的字詞：名稱本身＋括號裡「誤植為／口述為／字幕為」後面的字。"""
    文 = " ".join(str(x.get(k) or "") for k in ("名稱", "理由", "原文看法"))
    詞們 = [re.sub(r"[（(].*", "", str(x.get("名稱") or "")).strip()]
    for m in re.finditer(r"(?:誤植為|口述為|字幕為|逐字稿為|辨識為|聽成)[「『]?([一-鿿]{2,4}(?:[／/、][一-鿿]{2,4})*)", 文):
        詞們 += re.split(r"[／/、]", m.group(1))
    詞們 += re.findall(r"[「『]([一-鿿]{2,4})[」』]", 文)
    return [w for w in dict.fromkeys(詞們) if w]


def 漲跌停查核(影片們, 日表, 天數=30, 今天=None):
    """網紅說某檔「漲停／跌停」，拿影片日（或之前最近一個交易日）的實際漲跌對照；不符時，
    從當天真的漲停（跌停）的股票裡找名字念起來最像的，當作「可能是」。
    日表＝DataFrame（date, 代號, 名稱, 日報酬[小數]）。回傳 DataFrame。"""
    if 日表 is None or 日表.empty:
        return pd.DataFrame()
    今天 = pd.Timestamp(今天 or pd.Timestamp.now().normalize())
    交易日 = pd.DatetimeIndex(sorted(日表["date"].unique()))
    列們 = []
    for v in 影片們:
        日 = pd.to_datetime(v.get("日期"), errors="coerce")
        if pd.isna(日) or (今天 - 日).days > 天數:
            continue
        前 = 交易日[交易日 <= 日]
        if not len(前):
            continue
        d = 前[-1]
        當天 = 日表[日表["date"] == d]
        for x in v.get("股票", []):
            文 = f"{x.get('理由') or ''} {x.get('原文看法') or ''}"
            if re.search(r"(沒有|沒|未|不)(?:漲停|跌停)", 文):
                continue
            說 = "漲停" if "漲停" in 文 else ("跌停" if "跌停" in 文 else None)
            if not 說:
                continue
            代 = str(x.get("代號") or "")
            實 = 當天[當天["代號"] == 代]["日報酬"]
            實值 = float(實.iloc[0]) if len(實) else np.nan
            對 = pd.notna(實值) and (實值 >= 漲跌停門檻 if 說 == "漲停" else 實值 <= -漲跌停門檻)
            可能 = ""
            if not 對:
                池 = 當天[當天["日報酬"] >= 漲跌停門檻] if 說 == "漲停" else 當天[當天["日報酬"] <= -漲跌停門檻]
                詞們 = _候選字詞(x)
                最佳 = max(((max(同音分數(w, 名) for w in 詞們), 代2, 名) for 代2, 名 in zip(池["代號"], 池["名稱"])),
                         default=(0, "", ""))
                if 最佳[0] >= 0.5:
                    可能 = f"{最佳[1]} {最佳[2]}（念起來像）"
            列們.append({"影片日": 日, "頻道": v.get("頻道", ""), "股票": f"{代} {x.get('名稱', '')}".strip(), "說": 說,
                       "交易日": d, "實際漲跌%": round(實值 * 100, 2) if pd.notna(實值) else np.nan,
                       "結果": "✅ 相符" if 對 else "❌ 不符", "可能是": 可能})
    return pd.DataFrame(列們)


# ========== 股癌 EP712（2026-11-08）：國安基金、季線保衛戰、VIX 跳升、融資佔股本、Permit、砍單長鞭、說法查核 ==========
def 讀取國安基金():
    """data/stabilization_fund.csv：歷次國安基金進場（次, 決議日, 退場日, 事件, 投入億, 獲利億, 備註）。
    決議日只寫到月份（例如 2000-03）的是網站資料以前的護盤，只列事件不算報酬。新的一次直接在 GitHub 加一列。"""
    f = 資料夾 / "stabilization_fund.csv"
    if not f.exists():
        return pd.DataFrame(columns=["次", "決議日", "退場日", "事件", "投入億", "獲利億", "備註"])
    return pd.read_csv(f, dtype=str).fillna("")


def 國安基金統計(K, 紀錄=None, 天數=(1, 5, 20, 60, 120)):
    """每次國安基金決議日（盤後決議，從當天收盤算）之後加權的表現，以及這次護盤到今天跟前幾次「同一天數」的比較。
    回傳 (表, 本次)。表每列：次、決議日、事件、收盤、距一年高點%、季線乖離%、N日%、之後最低再跌%、最低日。"""
    紀錄 = 讀取國安基金() if 紀錄 is None else 紀錄
    if K is None or not len(K) or 紀錄.empty:
        return pd.DataFrame(), None
    k = K.set_index("date").sort_index()
    c, 低 = k["close"], k["low"] if "low" in k else k["close"]
    ma = c.rolling(60).mean()
    高 = c.rolling(250, min_periods=120).max()
    列們 = []
    for _, r in 紀錄.iterrows():
        日 = pd.to_datetime(r["決議日"], format="%Y-%m-%d", errors="coerce")
        列 = {"次": r["次"], "決議日": r["決議日"], "事件": r["事件"], "退場日": r.get("退場日", ""),
              "投入億": r.get("投入億", ""), "獲利億": r.get("獲利億", "")}
        if pd.notna(日) and 日 >= c.index[0]:
            前 = c.index[c.index <= 日]
            if len(前):
                i = c.index.get_loc(前[-1])
                p = float(c.iloc[i])
                列.update({"收盤": p, "距一年高點%": round((p / 高.iloc[i] - 1) * 100, 1) if pd.notna(高.iloc[i]) else np.nan,
                          "季線乖離%": round((p / ma.iloc[i] - 1) * 100, 1) if pd.notna(ma.iloc[i]) else np.nan,
                          "已過交易日": len(c) - 1 - i})
                for n in 天數:
                    列[f"{n}日%"] = round((c.iloc[i + n] / p - 1) * 100, 1) if i + n < len(c) else np.nan
                後 = 低.iloc[i + 1:i + 121]
                if len(後):
                    列["之後最低再跌%"] = round((後.min() / p - 1) * 100, 1)
                    列["最低日"] = 後.idxmin()
        列們.append(列)
    表 = pd.DataFrame(列們)
    本次 = None
    有 = 表[表.get("收盤", pd.Series(dtype=float)).notna()] if "收盤" in 表 else pd.DataFrame()
    if len(有):
        最後 = 有.iloc[-1]
        if not str(最後.get("退場日") or "").strip():
            n = int(最後["已過交易日"])
            i0 = c.index.get_loc(c.index[c.index <= pd.Timestamp(最後["決議日"])][-1])
            前幾次 = []
            for _, r in 有.iloc[:-1].iterrows():
                j = c.index.get_loc(c.index[c.index <= pd.Timestamp(r["決議日"])][-1])
                if j + n < len(c):
                    前幾次.append({"次": r["次"], "決議日": r["決議日"], "同天數%": round((c.iloc[j + n] / c.iloc[j] - 1) * 100, 1)})
            本次 = {"次": 最後["次"], "決議日": 最後["決議日"], "已過交易日": n,
                    "目前%": round((c.iloc[-1] / c.iloc[i0] - 1) * 100, 1), "最新日": c.index[-1], "前幾次": 前幾次}
    return 表, 本次


def 季線站上事件(收盤, 跌深=-10.0, 觀察=10):
    """指數離一年高點跌超過 跌深% 之後，第一次收盤站上 60 日線；之後 觀察 個交易日內只要收盤跌回季線就算「又跌破」。
    報酬從第 觀察 天收盤（已經知道站穩或跌破時）算起，避免偷看。回傳每次事件的表。"""
    c = 收盤.dropna().astype(float)
    ma = c.rolling(60).mean()
    高 = c.rolling(250, min_periods=120).max()
    列們, i, n, 待 = [], 61, len(c), False
    while i < n - 1:
        if c.iloc[i] / 高.iloc[i] - 1 <= 跌深 / 100 and c.iloc[i] < ma.iloc[i]:
            待 = True
        if 待 and c.iloc[i] > ma.iloc[i] and c.iloc[i - 1] <= ma.iloc[i - 1]:
            j = i + 觀察
            if j >= n:
                break
            破 = bool((c.iloc[i + 1:j + 1] < ma.iloc[i + 1:j + 1]).any())
            後 = c.iloc[j + 1:j + 121]
            f = lambda m: (c.iloc[j + m] / c.iloc[j] - 1) * 100 if j + m < n else np.nan
            列們.append({"站上日": c.index[i], "又跌破": 破, "60日%": f(60), "120日%": f(120), "250日%": f(250),
                       "再跌10%": (後.min() / c.iloc[j] - 1 <= -0.10) if len(後) >= 60 else np.nan})
            待, i = False, j
            continue
        i += 1
    return pd.DataFrame(列們, columns=["站上日", "又跌破", "60日%", "120日%", "250日%", "再跌10%"])


def 季線站上統計(事件):
    """季線站上事件 → 依「站穩／又跌破」分組的次數、平均報酬、上漲機率、之後 120 日內再跌 10% 的機率。"""
    if 事件 is None or 事件.empty:
        return pd.DataFrame()
    列們 = []
    for 破, g in 事件.groupby("又跌破"):
        x = g["再跌10%"].dropna().astype(float)
        六十 = g["60日%"].dropna()
        列們.append({"分組": "又跌破" if 破 else "站穩", "次數": len(g),
                   "60日平均%": round(六十.mean(), 1) if len(六十) else np.nan,
                   "60日上漲機率%": round((六十 > 0).mean() * 100) if len(六十) else np.nan,
                   "120日平均%": round(g["120日%"].mean(), 1), "250日平均%": round(g["250日%"].mean(), 1),
                   "再跌10%機率": round(x.mean() * 100) if len(x) else np.nan})
    return pd.DataFrame(列們).sort_values("分組", ascending=False).reset_index(drop=True)


def 季線狀態(K, 跌深=-10.0, 觀察=10):
    """加權現在在「季線保衛戰」的哪一段：
    正常（離高點不到 跌深%）→ 等站上季線（跌深且在季線下）→ 站上第 N 天（觀察期）→ 站穩／又跌破。
    回傳 dict：狀態、燈、說明、季線、收盤、乖離%、站上日、第幾天。"""
    if K is None or len(K) < 80:
        return None
    k = K.set_index("date").sort_index()
    c = k["close"].astype(float)
    ma = c.rolling(60).mean()
    高 = c.rolling(250, min_periods=120).max()
    n = len(c)
    深 = ((c / 高 - 1 <= 跌深 / 100) & (c < ma)).to_numpy()
    基本 = {"季線": float(ma.iloc[-1]), "收盤": float(c.iloc[-1]), "乖離%": round((c.iloc[-1] / ma.iloc[-1] - 1) * 100, 1),
            "距一年高點%": round((c.iloc[-1] / 高.iloc[-1] - 1) * 100, 1), "日期": c.index[-1]}
    等 = {**基本, "狀態": "等站上季線", "燈": "🔴",
          "說明": f"加權在季線（{ma.iloc[-1]:,.0f}）之下 {abs(基本['乖離%']):.1f}%，還沒彈回季線；別在還沒彈的時候急著加碼。"}
    # 最近一次「跌深之後第一次站上季線」：跟 季線站上事件 同一套規則（跌深＋在季線下才「上膛」，站上一次就用掉）
    上們, 待 = [], False
    for j in range(61, n):
        if 深[j]:
            待 = True
        elif 待 and c.iloc[j] > ma.iloc[j] and c.iloc[j - 1] <= ma.iloc[j - 1]:
            上們.append(j)
            待 = False
    上們 = [j for j in 上們 if j >= n - 250]
    if not 上們:
        return 等 if 深[-1] else {**基本, "狀態": "正常", "燈": "⚪",
                                  "說明": f"過去一年沒有跌離高點 {abs(跌深):.0f}% 以上又跌破季線，不在保衛戰。"}
    j = 上們[-1]
    第 = n - 1 - j
    基本.update({"站上日": c.index[j], "第幾天": 第})
    破們 = [k for k in range(j + 1, min(j + 1 + 觀察, n)) if c.iloc[k] < ma.iloc[k]]
    if 破們:
        k = 破們[0]
        if c.iloc[-1] > ma.iloc[-1]:
            return {**基本, "狀態": "重新站上季線", "燈": "🟡",
                    "說明": f"{c.index[j]:%m/%d} 站上後 {c.index[k]:%m/%d} 跌回，現在又回到季線上，再觀察能不能守住。"}
        if n - 1 - k > 20:
            if 深[-1]:
                return {**等, "說明": 等["說明"] + f"（上一次 {c.index[j]:%m/%d} 站上、{c.index[k]:%m/%d} 又跌破）"}
            return {**基本, "狀態": "正常", "燈": "⚪", "說明": f"在季線下，但離一年高點不到 {abs(跌深):.0f}%，不在保衛戰。"}
        return {**基本, "狀態": "又跌破", "燈": "🟠",
                "說明": f"{c.index[j]:%m/%d} 站上季線，{c.index[k]:%m/%d} 又跌回去：風險偏高、先別加碼，"
                        "但美股 30 年回測顯示這不等於大頭部。"}
    if 第 < 觀察:
        return {**基本, "狀態": f"站上第 {第} 天", "燈": "🟡",
                "說明": f"{c.index[j]:%m/%d} 站上季線，觀察到第 {觀察} 天都沒跌回去才算站穩（還差 {觀察 - 第} 天）。"}
    if 深[-1]:   # 站穩之後又跌深到季線下：新的一輪
        return 等
    if c.iloc[-1] < ma.iloc[-1]:
        return {**基本, "狀態": "正常", "燈": "⚪", "說明": f"{c.index[j]:%m/%d} 那次站穩後，現在回到季線下但離高點不到 {abs(跌深):.0f}%。"}
    return {**基本, "狀態": "站穩", "燈": "🟢",
            "說明": f"{c.index[j]:%m/%d} 站上季線後 {觀察} 天都守住，主委說的「站穩再加碼」條件成立。"}


def 季線乖離位置(K, 門檻=-10.0, 天數=(5, 20, 60)):
    """目前季線乖離在資料期間排第幾（越低越超跌），以及過去乖離 ≤ 門檻% 每一段（間隔 40 天以上算新的一段）
    第一次碰到門檻那天之後 N 日的加權表現。回傳 dict：乖離%、百分位、段落表。"""
    if K is None or len(K) < 80:
        return None
    c = K.set_index("date").sort_index()["close"].astype(float)
    乖 = (c / c.rolling(60).mean() - 1) * 100
    x = 乖.dropna()
    現 = float(x.iloc[-1])
    列們, 上次 = [], None
    for d in x[x <= 門檻].index:
        if 上次 is not None and (d - 上次).days <= 40:
            上次 = d
            continue
        上次 = d
        i = c.index.get_loc(d)
        段 = x.loc[d:d + pd.Timedelta(days=40)]
        列 = {"開始日": d, "當天乖離%": round(float(x[d]), 1), "最低乖離%": round(float(段.min()), 1)}
        for n in 天數:
            列[f"{n}日%"] = round((c.iloc[i + n] / c.iloc[i] - 1) * 100, 1) if i + n < len(c) else np.nan
        列們.append(列)
    return {"乖離%": round(現, 1), "百分位": round(float((x < 現).mean() * 100), 1), "起": x.index[0],
            "段落": pd.DataFrame(列們)}


def 讀取VIX長線():
    """data/vix_long.csv（date, close）：VIX 從 1990 年起的每日收盤。沒有這個檔時退回 us_daily.csv 的近兩年。"""
    f = 資料夾 / "vix_long.csv"
    if f.exists():
        t = pd.read_csv(f, parse_dates=["date"])
        s = t.set_index("date")["close"].sort_index()
    else:
        s = pd.Series(dtype=float)
    美 = 讀取美股()
    if 美 is not None and "VIX" in 美:
        近 = 美["VIX"].dropna()
        s = pd.concat([s, 近[近.index > (s.index.max() if len(s) else pd.Timestamp("1900-01-01"))]]).sort_index()
    return s if len(s) else None


VIX條件 = [  # 名稱, 函式(vix) → 布林序列
    ("VIX 單日跳升 ≥ 50%", lambda v: v / v.shift(1) - 1 >= 0.5),
    ("VIX 單日跳升 ≥ 30%", lambda v: v / v.shift(1) - 1 >= 0.3),
    ("VIX 首次站上 30", lambda v: (v >= 30) & (v.shift(1) < 30)),
    ("VIX 首次站上 40", lambda v: (v >= 40) & (v.shift(1) < 40)),
]


def VIX跳升統計(vix, 指數, 天數=(5, 20, 60, 250), 間隔=20, 隔天=False):
    """VIX 條件出現之後 指數（S&P 500 或加權）N 日的平均報酬與上漲機率；同一個條件 間隔 個交易日內只算第一次。
    S&P 500 用當天收盤進場；加權傳 隔天=True，用「美國那天之後的第一個台股交易日」收盤進場（美股收盤時台股已收盤）。
    回傳 (表, 事件日 dict)。"""
    if vix is None or 指數 is None or not len(vix) or not len(指數):
        return pd.DataFrame(), {}
    v = vix.dropna().astype(float)
    p = 指數.dropna().astype(float).sort_index()
    v = v[v.index >= p.index[0] - pd.Timedelta(days=5)]
    fw = {n: p.shift(-n) / p - 1 for n in 天數}
    列們 = [{"條件": "任意一天（基準）", "次數": len(p),
            **{k: v2 for n in 天數 for k, v2 in ((f"{n}日平均%", round(fw[n].mean() * 100, 1)),
                                                  (f"{n}日上漲%", round((fw[n].dropna() > 0).mean() * 100)))}}]
    事件們 = {}
    for 名, 規則 in VIX條件:
        日們 = v.index[規則(v).fillna(False).to_numpy()]
        進場 = []
        for d in 日們:
            後 = p.index[p.index > d] if 隔天 else p.index[p.index >= d]
            if len(後) == 0:
                continue
            e = 後[0]
            if 進場 and p.index.get_loc(e) - p.index.get_loc(進場[-1]) <= 間隔:
                continue
            進場.append(e)
        事件們[名] = 日們
        idx = pd.DatetimeIndex(進場)
        列 = {"條件": 名, "次數": len(idx)}
        for n in 天數:
            x = fw[n].reindex(idx).dropna()
            列[f"{n}日平均%"] = round(x.mean() * 100, 1) if len(x) else np.nan
            列[f"{n}日上漲%"] = round((x > 0).mean() * 100) if len(x) else np.nan
        列們.append(列)
    return pd.DataFrame(列們), 事件們


def VIX今日觸發(vix, 最近天數=3):
    """最近 最近天數 個美股交易日有沒有符合任何 VIX 條件；回傳 [(日期, 條件, VIX, 單日變化%)]。"""
    if vix is None or len(vix) < 3:
        return []
    v = vix.dropna().astype(float)
    結果 = []
    for 名, 規則 in VIX條件:
        m = 規則(v).fillna(False)
        for d in m.index[-最近天數:][m.iloc[-最近天數:].to_numpy()]:
            結果.append((d, 名, float(v[d]), round((v[d] / v.shift(1)[d] - 1) * 100, 1)))
    return 結果


def 加融資佔股本(今日):
    """今日表加「融資佔股本%」（融資餘額張數 × 1000 ÷ 發行股數）與「融資佔股本排名%」（全市場第幾 %，100＝最高）。"""
    t = 今日
    if "融資餘額" not in t.columns or "發行股數" not in t.columns:
        return t
    t = t.copy()
    股 = pd.to_numeric(t["發行股數"], errors="coerce")
    t["融資佔股本%"] = (pd.to_numeric(t["融資餘額"], errors="coerce") * 1000 / 股.where(股 > 0) * 100).round(2)
    t["融資佔股本排名%"] = (t["融資佔股本%"].rank(pct=True) * 100).round(0)
    return t


def 個股beta(指標, K, 天數=120):
    """近 天數 個交易日每檔股票對加權的 beta。指標要有 date、代號、日報酬。回傳 Series（代號 → beta）。"""
    if K is None or 指標 is None or "日報酬" not in 指標.columns:
        return pd.Series(dtype=float)
    日們 = np.sort(指標["date"].unique())[-天數:]
    r = 指標[指標["date"].isin(日們)].pivot_table(index="date", columns="代號", values="日報酬")
    m = K.set_index("date")["close"].astype(float).pct_change().reindex(r.index)
    ok = m.notna()
    r, m = r[ok], m[ok]
    if len(m) < 40:
        return pd.Series(dtype=float)
    rm = r.sub(r.mean())
    mm = m - m.mean()
    cov = rm.mul(mm, axis=0).sum() / (r.notna().mul(1).sum() - 1)
    beta = cov / mm.var()
    return beta.where(r.notna().sum() >= 40).round(2)


def 籌碼不安定榜(今日, 指標=None, K=None, 檔數=50, 最少成交值億=0.5, 最少融資張=500):
    """融資佔股本最高的股票（股癌 EP712：融資高的標的籌碼不安定，殺盤時是重災區）。附 beta 與近 5 日漲跌，
    因為 2026-11 回測：融資高的股票 9 次急跌都跌更深，但同 beta 比只多跌 1～4 個百分點，主要是高波動股的另一面。"""
    t = 加融資佔股本(今日) if "融資佔股本%" not in 今日.columns else 今日
    if "融資佔股本%" not in t.columns:
        return pd.DataFrame()
    t = t[t["代號"].astype(str).str.fullmatch(r"\d{4}") & (t["融資餘額"] >= 最少融資張)]
    if "成交值億" in t.columns:
        t = t[t["成交值億"] >= 最少成交值億]
    t = t.sort_values("融資佔股本%", ascending=False).head(檔數).copy()
    if 指標 is not None and K is not None and len(t):
        b = 個股beta(指標[指標["代號"].isin(t["代號"])], K)
        t["beta"] = t["代號"].map(b)
    return t.reset_index(drop=True)


def 讀取Permit追蹤():
    """data/permit_watch.csv（日期, 地區, 事件, 燈, 來源）：美國資料中心許可（建照、環保、電網併接）被卡住的紀錄。
    燈：🔴 卡住擴大、🟡 部分暫停或審查中、🟢 恢復發放。最新一列的燈就是目前燈號，可以在 GitHub 直接加列。"""
    f = 資料夾 / "permit_watch.csv"
    if not f.exists():
        return pd.DataFrame(columns=["日期", "地區", "事件", "燈", "來源"])
    t = pd.read_csv(f, dtype=str).fillna("")
    t["日期"] = pd.to_datetime(t["日期"], errors="coerce")
    return t.iloc[::-1].sort_values("日期", ascending=False, kind="stable").reset_index(drop=True)  # 同一天：檔案後面的排前面


Permit關鍵字 = '"data center" (permit OR moratorium OR pause OR "interconnection" OR ERCOT)'


def Permit新聞(天數=14, 筆數=20):
    """Google 新聞（英文）搜尋資料中心許可、暫停、併網審查的新聞。"""
    import requests
    import xml.etree.ElementTree as ET

    回應 = requests.get("https://news.google.com/rss/search", timeout=20, headers={"User-Agent": "Mozilla/5.0"},
                        params={"q": f"{Permit關鍵字} when:{天數}d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    回應.raise_for_status()
    列們 = []
    for 項 in ET.fromstring(回應.content).iter("item"):
        標題, 來源 = 項.findtext("title") or "", 項.findtext("source") or ""
        if 來源 and 標題.endswith(" - " + 來源):
            標題 = 標題[: -len(來源) - 3]
        列們.append({"日期": pd.to_datetime(項.findtext("pubDate"), errors="coerce", utc=True), "標題": 標題,
                   "來源": 來源, "連結": 項.findtext("link") or ""})
    表 = pd.DataFrame(列們, columns=["日期", "標題", "來源", "連結"])
    if 表.empty:
        return 表
    表["日期"] = 表["日期"].dt.tz_convert("Asia/Taipei").dt.tz_localize(None)
    緊 = 表["標題"].str.contains(r"(?i)moratorium|pause|halt|block|ban|reject|deny|freeze", regex=True)
    表["訊號"] = np.where(緊, "⚠️ 限制", "")
    return 表.drop_duplicates("標題").sort_values("日期", ascending=False).head(筆數).reset_index(drop=True)


長鞭族群 = [  # 名稱, 位置, 來源（概念 or 產業）, 值
    ("被動元件", "小料件", "概念", "被動元件"),
    ("電子零組件", "小料件", "產業", "電子零組件"),
    ("電腦及週邊（組裝）", "中游", "產業", "電腦及週邊設備"),
    ("半導體", "上游", "產業", "半導體"),
    ("晶圓代工", "上游", "概念", "晶圓代工"),
]


def 砍單長鞭(營收=None, 月數=3):
    """股癌 EP712：砍單通常先從違約代價低的小料件開始，再像甩長鞭往上傳。
    各族群「近 月數 個月營收合計年增 < 0」的公司比例（%），月 × 族群。回傳 (表, 燈 dict)。
    2022～2023 那次：被動元件 2023-02 衰退比例到 100%，晶圓代工晚約 2 個月（2023-04）才到 100%。"""
    if 營收 is None:
        f = 資料夾 / "fundamental" / "revenue_history.csv"
        if not f.exists():
            return pd.DataFrame(), None
        營收 = pd.read_csv(f, dtype={"code": str})
    p = 營收.pivot_table(index="month", columns="code", values="revenue").sort_index()
    s = p.rolling(月數).sum()
    yoy = s / s.shift(12) - 1
    概 = 讀取概念()
    產 = _股本表()["產業"]
    欄們 = {}
    for 名, _, 來源, 值 in 長鞭族群:
        碼 = 概.loc[概["concept"] == 值, "code"].tolist() if 來源 == "概念" else 產[產 == 值].index.tolist()
        碼 = [c for c in 碼 if c in yoy.columns]
        if not 碼:
            continue
        y = yoy[碼]
        欄們[名] = ((y < 0).sum(axis=1) / y.notna().sum(axis=1).replace(0, np.nan) * 100).round(0)
    表 = pd.DataFrame(欄們).dropna(how="all")
    if 表.empty:
        return 表, None
    表.index = pd.to_datetime(表.index)
    最新 = 表.iloc[-1]
    三月前 = 表.iloc[-4] if len(表) >= 4 else 表.iloc[0]
    小 = [n for n, 位, *_ in 長鞭族群 if 位 == "小料件" and n in 表]
    上 = [n for n, 位, *_ in 長鞭族群 if 位 == "上游" and n in 表]
    小現 = float(最新[小].mean()) if 小 else np.nan
    小升 = float((最新[小] - 三月前[小]).mean()) if 小 else np.nan
    上現 = float(最新[上].mean()) if 上 else np.nan
    if 小現 >= 50 and 上現 >= 50:
        燈, 話 = "🔴", "小料件和上游都有一半以上公司營收年衰退，修正已經往上傳"
    elif 小現 >= 50 or (小升 >= 15 and 小現 >= 35):
        燈, 話 = "🟡", "小料件營收衰退比例升高，先觀察會不會往上游傳"
    else:
        燈, 話 = "🟢", "小料件營收大多還在成長，沒看到砍單從小東西開始"
    return 表, {"燈": 燈, "說明": 話, "月份": 表.index[-1], "小料件%": round(小現), "小料件3月變化": round(小升),
               "上游%": round(上現) if 上現 == 上現 else np.nan}


def 讀取說法查核():
    """data/claims.csv（來源, 日期, 編號, 說法, 查到的事實, 判定）：網紅、Podcast、講義說法的查核紀錄。"""
    f = 資料夾 / "claims.csv"
    if not f.exists():
        return pd.DataFrame(columns=["來源", "日期", "編號", "說法", "查到的事實", "判定"])
    return pd.read_csv(f, dtype=str).fillna("")


# ========== 正2 融資斷頭論述（2026-11-08）：槓桿 ETF 融資追蹤、正2 融資維持率估算、期貨多空對手方、背離回測 ==========
台股正2 = {"00631L": "元大台灣50正2", "00685L": "群益臺灣加權正2", "00663L": "國泰臺灣加權正2", "00675L": "富邦臺灣加權正2"}


def 正2融資明細(表):
    """台股 4 檔正2 每天的融資：表要有 code、date、close、margin（讀取資料庫(代號=台股正2) 即可）。
    回傳 (每日, 每檔最新)：
    每日（index＝date）：融資市值億、估借款億、單日增減億（張數變化 × 收盤）、估維持率；
    每檔最新（list of dict）：代號、名稱、日期、融資張數、單日增減張、連增天數、收盤、融資市值億、估成本、估維持率、到130%大盤再跌%。
    估成本：融資增加的張數以當天收盤計入加權平均成本（同 融資成本估算），面額分割（00631L 2026-03-31、00685L 2026-07-07）
    從收盤跳動自動換算。融資成數 60%。維持率 ＝ 收盤 ÷（成本 × 60%）。"""
    if 表 is None or not len(表) or "margin" not in 表:
        return pd.DataFrame(), []
    t = 表[表["code"].isin(list(台股正2))][["code", "date", "close", "margin"]].copy()
    t = t.dropna(subset=["close"]).sort_values(["code", "date"], ignore_index=True)
    if t.empty:
        return pd.DataFrame(), []
    t["close"] = t["close"].astype("float64")
    t["margin"] = t["margin"].astype("float64")
    比 = t["close"] / t.groupby("code")["close"].shift()
    報 = (比 - 1).where((比 > 0.6) & (比 < 1.4), 0.0).fillna(0.0)   # 跳太多＝分割，報酬設 0 讓成本跟著換算
    t["成本"] = 融資成本估算(t["code"].to_numpy(), t["close"].to_numpy(), 報.to_numpy(), t["margin"].to_numpy())
    前 = t.groupby("code")["margin"].shift()
    分割 = (比 <= 0.6) | (比 >= 1.4)
    t["增減張"] = (t["margin"] - 前).where(~分割)
    t["市值"] = t["margin"] * 1000 * t["close"] / 1e8
    t["借款"] = t["margin"] * 1000 * t["成本"] * 0.6 / 1e8
    t["增減億"] = t["增減張"] * 1000 * t["close"] / 1e8
    群 = t.groupby("date")
    每日 = pd.DataFrame({"融資市值億": 群["市值"].sum(min_count=1), "估借款億": 群["借款"].sum(min_count=1),
                         "單日增減億": 群["增減億"].sum(min_count=1)})
    每日["估維持率"] = (每日["融資市值億"] / 每日["估借款億"] * 100).round(1)
    每檔 = []
    for c, g in t.groupby("code"):
        g = g.dropna(subset=["margin"])
        if g.empty:
            continue
        x = g.iloc[-1]
        連 = 0
        for v in g["增減張"].iloc[1:][::-1]:
            if pd.isna(v):          # 分割那天不算增減，也不打斷連增
                continue
            if v > 0:
                連 += 1
            else:
                break
        維 = x["close"] / (x["成本"] * 0.6) * 100 if x["成本"] > 0 else np.nan
        每檔.append({"代號": c, "名稱": 台股正2[c], "日期": x["date"], "融資張數": int(x["margin"]),
                     "單日增減張": None if pd.isna(x["增減張"]) else int(x["增減張"]), "連增天數": 連,
                     "收盤": float(x["close"]), "融資市值億": round(float(x["市值"]), 1),
                     "估成本": round(float(x["成本"]), 2), "估維持率": round(float(維), 1),
                     "到130%大盤再跌%": round(float(min(0.0, 130 / 維 - 1) * 50), 1) if 維 == 維 else np.nan})
    return 每日.round(2), sorted(每檔, key=lambda r: -r["融資市值億"])


def 期貨多空對手(期):
    """外資台指期淨空單 ÷ 投信淨多單。投信多單主要是正2 ETF 的期貨部位，外資空單有一大塊是它的對手方或現貨避險；
    比值在平常水準時，外資空單創新高多半只是正2 規模變大。期：讀取期貨未平倉()。
    回傳 dict(序列, 最新, 中位, 低, 高, 燈, 說明) 或 None。"""
    if 期 is None or "foreign_oi" not in 期 or "trust_oi" not in 期:
        return None
    d = 期[["foreign_oi", "trust_oi"]].dropna()
    d = d[d["trust_oi"] > 1000]
    if len(d) < 20:
        return None
    s = (-d["foreign_oi"] / d["trust_oi"]).round(2)
    中, 低, 高 = float(s.median()), float(s.quantile(0.1)), float(s.quantile(0.9))
    v = float(s.iloc[-1])
    if v > 高:
        燈, 話 = "🟡", "外資空單明顯多於投信多單，超出正2 對手方的部分偏多，外資比平常更偏空"
    elif v < 低:
        燈, 話 = "🟢", "外資空單少於平常比例，偏空力道比數字看起來小"
    else:
        燈, 話 = "⚪", "比例在平常範圍：外資空單變大主要是跟著正2 期貨多單一起變大，不能單看口數說外資大舉作空"
    return {"序列": s, "最新": v, "中位": round(中, 2), "低": round(低, 2), "高": round(高, 2), "燈": 燈, "說明": 話,
            "外資": int(d["foreign_oi"].iloc[-1]), "投信": int(d["trust_oi"].iloc[-1]), "日期": d.index[-1]}


def 正2背離統計(變, 正2每日, K, 大盤門檻=-1.5, 正2門檻=3.0, 間隔天數=14, 天數=(5, 20, 60)):
    """「大盤融資單日減 ≥ 1.5%，正2 融資同日增 ≥ 3%」（散戶在大盤洗融資時用融資接正2）之後加權的漲跌，
    對照任何一天買進。變：大盤融資變化()（%）；正2每日：正2融資明細() 的每日（要有 單日增減億、融資市值億）。
    2026-11 實測（2021-11～2026-11）：18 次，20 日 +2.8%、60 日 +9.8%，都不比一般日子差，不是崩盤前兆。"""
    if 正2每日 is None or not len(正2每日) or K is None:
        return None
    前市值 = 正2每日["融資市值億"].shift()
    正2變 = (正2每日["單日增減億"] / 前市值.where(前市值 > 0) * 100)
    d = pd.DataFrame({"大盤": 變, "正2": 正2變}).dropna()
    條件 = d[(d["大盤"] <= 大盤門檻) & (d["正2"] >= 正2門檻)]
    c = K.set_index("date")["close"].astype(float)
    事件, 上次 = [], None
    for 日, r in 條件.iterrows():
        if 日 not in c.index:
            continue
        if 上次 is None or (日 - 上次).days > 間隔天數:
            事件.append((日, r))
            上次 = 日
    統計 = []
    for n in 天數:
        後 = (c.shift(-n) / c - 1) * 100
        x = 後.reindex([e[0] for e in 事件]).dropna()
        基 = 後.loc[c.index >= d.index.min()].dropna()
        統計.append({"天數": n, "次數": int(len(x)), "平均%": round(float(x.mean()), 2) if len(x) else None,
                     "上漲機率%": round(float((x > 0).mean() * 100)) if len(x) else None,
                     "基準平均%": round(float(基.mean()), 2), "基準上漲機率%": round(float((基 > 0).mean() * 100))})
    列 = []
    for 日, r in 事件:
        項 = {"date": f"{日:%Y-%m-%d}", "大盤融資%": round(float(r["大盤"]), 2), "正2融資%": round(float(r["正2"]), 2)}
        for n in 天數:
            i = c.index.get_loc(日)
            項[f"{n}日後%"] = round(float((c.iloc[i + n] / c.iloc[i] - 1) * 100), 1) if i + n < len(c) else None
        列.append(項)
    return {"大盤門檻": 大盤門檻, "正2門檻": 正2門檻, "次數": len(事件), "統計": 統計, "事件": 列}


def 今日正2背離(大盤變化, 正2每日, 大盤門檻=-1.5, 正2門檻=3.0):
    """最新一天是不是「大盤洗融資、正2 融資逆勢增」。回傳 (是否, 大盤%, 正2%) 或 None。"""
    if 正2每日 is None or len(正2每日) < 2 or 大盤變化 is None or not len(大盤變化):
        return None
    日 = 正2每日.index[-1]
    if 日 not in 大盤變化.index:
        return None
    前 = 正2每日["融資市值億"].iloc[-2]
    正 = float(正2每日["單日增減億"].iloc[-1] / 前 * 100) if 前 > 0 and pd.notna(正2每日["單日增減億"].iloc[-1]) else np.nan
    大 = float(大盤變化.loc[日])
    return (大 <= 大盤門檻 and 正 >= 正2門檻), round(大, 2), round(正, 2)


# ========== 市場評論查核（2026-11-09）：預估本益比情境、季節（做帳）統計、年線測試、反彈尺達成率、關注清單、領頭連動、AI 資本支出警示 ==========
def 大盤預估本益比(今日, 龍頭="2330", 下修們=(0.9, 0.8)):
    """上市（不含 ETF）用共識預估 EPS（A、B 中位數）算的大盤預估本益比＝Σ市值 ÷ Σ(預估EPS × 股數)，只算預估 EPS > 0 的。
    回傳 dict：今年／明年 各有 本益比、不含龍頭、龍頭本益比、涵蓋%，以及 龍頭權重%、情境（龍頭或全部 EPS 下修）。"""
    if 今日 is None or not len(今日) or "預估EPS明年" not in 今日.columns:
        return None
    t = 今日[(今日.get("市場", "上市") == "上市") & ~今日["代號"].str.startswith("00") & (今日["收盤"] > 0)
            & (今日["發行股數"] > 0)].copy()
    if t.empty:
        return None
    t["市值"] = t["收盤"] * t["發行股數"]
    總市值 = t["市值"].sum()
    結果 = {"龍頭": 龍頭, "龍頭權重%": round(float(t.loc[t["代號"] == 龍頭, "市值"].sum() / 總市值 * 100), 1)}
    for 欄, 名 in (("預估EPS今年", "今年"), ("預估EPS明年", "明年")):
        e = pd.to_numeric(t[欄], errors="coerce")
        有 = e > 0
        if 有.sum() < 100:
            continue
        獲 = (e * t["發行股數"]).where(有)
        市 = t["市值"].where(有)
        非 = t["代號"] != 龍頭
        項 = {"本益比": float(市.sum() / 獲.sum()), "不含龍頭": float(市[非].sum() / 獲[非].sum()),
             "涵蓋%": round(float(市.sum() / 總市值 * 100), 1)}
        頭獲 = float(獲[~非].sum())
        項["龍頭本益比"] = float(市[~非].sum() / 頭獲) if 頭獲 > 0 else np.nan
        項["情境"] = []
        for k in 下修們:
            項["情境"].append({"情境": f"{t.loc[~非, '名稱'].iloc[0] if (~非).any() else 龍頭} EPS 下修 {round((1 - k) * 100)}%",
                             "大盤預估本益比": round(float(市.sum() / (獲[非].sum() + 頭獲 * k)), 2)})
        for k in 下修們:
            項["情境"].append({"情境": f"全部 EPS 下修 {round((1 - k) * 100)}%", "大盤預估本益比": round(項["本益比"] / k, 2)})
        結果[名] = 項
    return 結果 if ("今年" in 結果 or "明年" in 結果) else None


def 點位本益比換算(目前點位, 目前本益比, 目標點位=None, 目標本益比=None):
    """指數跟本益比同比例：給目標點位回傳對應本益比，給目標本益比回傳對應點位（假設 EPS 不變）。"""
    if not 目前點位 or not 目前本益比:
        return None
    if 目標點位:
        return 目前本益比 * 目標點位 / 目前點位
    if 目標本益比:
        return 目前點位 * 目標本益比 / 目前本益比
    return None


def 季節統計(K, 起=(11, 30), 迄=(2, 5), 今天=None):
    """每年 起（月, 日）收盤 → 隔年 迄 收盤的漲跌、12 月漲跌、期間最大回檔；跟「任意同樣長度期間」比。
    回傳 (表, 基準 dict, 今年 dict 或 None)。K：date, close（指數日 K）。"""
    if K is None or len(K) < 250:
        return pd.DataFrame(), {}, None
    c = K.set_index("date")["close"].sort_index()
    最後 = c.index.max()
    列們, 長度們 = [], []
    for y in range(c.index.min().year, 最後.year + 1):
        開 = pd.Timestamp(y, *起)
        收 = pd.Timestamp(y + 1, *迄)
        a = c[:開]
        if len(a) == 0 or a.index[-1] < 開 - pd.Timedelta(days=10) or 開 > 最後:
            continue
        a0 = float(a.iloc[-1])
        十二 = c[:pd.Timestamp(y, 12, 31)]
        段 = c[開 + pd.Timedelta(days=1):收]
        完整 = 最後 >= 收
        列 = {"年度": f"{y}～{str(y + 1)[2:]}", "起點": round(a0, 2),
             "區間%": round(float((段.iloc[-1] / a0 - 1) * 100), 1) if len(段) else np.nan,
             "12月%": round(float((十二.iloc[-1] / a0 - 1) * 100), 1) if 最後 >= pd.Timestamp(y, 12, 31) else np.nan,
             "最大回檔%": round(float(((段 / 段.cummax()).min() - 1) * 100), 1) if len(段) else np.nan,
             "完整": 完整}
        if 完整:
            長度們.append(len(段))
        列們.append(列)
    表 = pd.DataFrame(列們)
    基準 = {}
    if 長度們:
        n = int(np.median(長度們))
        r = (c.pct_change(n).dropna() * 100)
        完 = 表[表["完整"]]
        基準 = {"天數": n, "平均%": round(float(r.mean()), 1), "上漲%": round(float((r > 0).mean() * 100)),
              "區間平均%": round(float(完["區間%"].mean()), 1), "區間上漲次數": int((完["區間%"] > 0).sum()), "區間次數": int(len(完))}
    今年 = None
    if len(表) and not bool(表["完整"].iloc[-1]):
        今年 = 表.iloc[-1].to_dict()
    else:
        y = 最後.year
        開 = pd.Timestamp(y, *起)
        if 最後 < 開:
            今年 = {"年度": f"{y}～{str(y + 1)[2:]}", "還沒開始": True, "距開始天數": int((開 - 最後).days)}
    return 表, 基準, 今年


def 年線事件(K, 前置天數=60, 容忍=0.01, 年線天數=240):
    """指數（或個股）前 前置天數 天收盤都在年線上，第一次盤中碰到年線（容忍 1% 內）的日子，之後 5／20／60／120 日漲跌。
    回傳 (目前 dict, 事件表)。"""
    if K is None or len(K) < 年線天數 + 前置天數:
        return None, pd.DataFrame()
    d = K.set_index("date").sort_index()
    c, lo = d["close"], d["low"]
    ma = c.rolling(年線天數).mean()
    上 = (c > ma).astype(float).where(ma.notna())
    前 = 上.rolling(前置天數).min().shift(1) == 1
    碰 = (lo <= ma * (1 + 容忍)) & 前
    碰 = 碰 & ~碰.shift(1, fill_value=False).rolling(20, min_periods=1).max().astype(bool)
    列們 = []
    for 日 in c.index[碰]:
        i = c.index.get_loc(日)
        列 = {"日期": 日, "收盤": round(float(c.iloc[i]), 2), "年線": round(float(ma.iloc[i]), 2),
             "當天收破": bool(c.iloc[i] < ma.iloc[i])}
        for n in (5, 20, 60, 120):
            列[f"{n}日後%"] = round(float((c.iloc[i + n] / c.iloc[i] - 1) * 100), 1) if i + n < len(c) else np.nan
        段 = lo.iloc[i:i + 60]
        列["60日內最低距年線%"] = round(float((段.min() / ma.iloc[i] - 1) * 100), 1)
        列們.append(列)
    目前 = {"年線": float(ma.iloc[-1]), "收盤": float(c.iloc[-1]), "距年線%": float((c.iloc[-1] / ma.iloc[-1] - 1) * 100),
          "低點距年線%": float((lo.iloc[-1] / ma.iloc[-1] - 1) * 100),
          "年線方向": "上彎" if ma.iloc[-1] > ma.iloc[-21] else "下彎", "在年線上天數": int((上[::-1].cumprod()).sum())}
    return 目前, pd.DataFrame(列們)


def 反彈尺(K, 大段天數=120, 最近低點天數=30, 最小跌幅=0.10):
    """下跌後的反彈目標：低點＝最近 60 日最低（要在最近 最近低點天數 天內），
    大段高點＝低點前 大段天數 天內最高；小段高點＝低點前最後一個 2% 轉折高點（跟大段不同才列）。
    回傳 dict（低、大段、小段：各有 高、0.382／0.5／0.618 價位、目前反彈%）或 None（不是跌深後的反彈）。"""
    import macro
    if K is None or len(K) < 大段天數 + 10:
        return None
    d = K.reset_index(drop=True)
    近 = d.tail(60)
    i低 = int(近["low"].idxmin())
    低 = float(d.loc[i低, "low"])
    if len(d) - 1 - i低 > 最近低點天數:
        return None
    前段 = d.iloc[max(0, i低 - 大段天數):i低]
    i高 = int(前段["high"].idxmax())
    高 = float(d.loc[i高, "high"])
    if 高 < 低 * (1 + 最小跌幅):
        return None
    現 = float(d["close"].iloc[-1])

    def 尺(h, 日):
        幅 = h - 低
        return {"高": h, "高日": 日, "價位": {f"{r:g}": 低 + 幅 * r for r in (0.382, 0.5, 0.618)},
                "已反彈%": round((現 - 低) / 幅 * 100, 1)}
    結果 = {"低": 低, "低日": d.loc[i低, "date"], "現價": 現, "大段": 尺(高, d.loc[i高, "date"])}
    點 = [p for p in macro.轉折點(d.iloc[:i低 + 1].tail(大段天數 + 1).reset_index(drop=True), 0.02) if p[2] == "高" and p[0] < d.loc[i低, "date"]]
    if 點 and 點[-1][1] < 高 * 0.995 and 點[-1][1] > 低 * 1.03:
        結果["小段"] = 尺(float(點[-1][1]), 點[-1][0])
    return 結果


def 價位統計(表=None, 成交門檻=5e7):
    """個股（4 碼、近 20 日均成交額 > 成交門檻）5 年資料：
    ① 年線：前 60 天都在年線上、第一次盤中碰年線 1% 內 → 之後 20／60 日超額報酬（扣加權）vs 一般日子、20 天內收盤跌破年線 5% 的比率；
    ② 反彈尺：60 日高點跌 ≥ 20% 的波段低點（前後 20 日最低）→ 40 日內最高反彈到 0.382／0.5／0.618／1 的比率與落點分布。"""
    if 表 is None:
        表 = _讀每日檔("prices")
    t = 表[表["code"].astype(str).str.len() == 4][["code", "date", "close", "high", "low", "value"]].copy()
    t = t[t["close"] > 0]
    t["date"] = pd.to_datetime(t["date"])
    C = t.pivot_table(index="date", columns="code", values="close")
    H = t.pivot_table(index="date", columns="code", values="high").reindex_like(C)
    L = t.pivot_table(index="date", columns="code", values="low").reindex_like(C)
    V = t.pivot_table(index="date", columns="code", values="value").reindex_like(C)
    del t
    流 = V.rolling(20).mean() > 成交門檻
    K = 讀取指數K線("TAIEX")
    加 = K.set_index("date")["close"].reindex(C.index).ffill()
    ma = C.rolling(240, min_periods=230).mean()
    上 = (C > ma).astype(float).where(ma.notna())
    前 = 上.rolling(60).min().shift(1) == 1
    碰 = (L <= ma * 1.01) & 前 & 流
    碰 = 碰 & ~碰.shift(1).rolling(20, min_periods=1).max().fillna(0).astype(bool)
    年線 = {}
    for n in (20, 60):
        超 = (C.shift(-n) / C - 1) * 100 - ((加.shift(-n) / 加 - 1) * 100).to_numpy()[:, None]
        絕 = (C.shift(-n) / C - 1) * 100
        e = 超.where(碰).stack().dropna()
        b = 超.where(流 & ma.notna()).stack().dropna()
        年線[f"{n}日"] = {"次數": int(len(e)), "超額%": round(float(e.mean()), 2), "一般日超額%": round(float(b.mean()), 2),
                        "上漲%": round(float((絕.where(碰).stack().dropna() > 0).mean() * 100), 1)}
    破 = ((C / ma).rolling(20).min().shift(-19) < 0.95).where(碰).stack().dropna()
    年線["20日內跌破5%比率"] = round(float(破.astype(float).mean() * 100), 1)
    比們 = []
    for c in [c for c in C.columns if 流[c].mean() > 0.3]:
        s = C[c].dropna()
        h, l = H[c].reindex(s.index).to_numpy(), L[c].reindex(s.index).to_numpy()
        i = 60
        while i < len(s) - 40:
            hi = np.nanmax(h[i - 60:i])
            if l[i] <= hi * 0.8 and l[i] == np.nanmin(l[i - 20:i + 21]):
                比們.append((np.nanmax(h[i + 1:i + 41]) - l[i]) / (hi - l[i]))
                i += 40
            else:
                i += 1
    r = pd.Series(比們).dropna()
    邊 = [0, 0.25, 0.35, 0.41, 0.47, 0.53, 0.59, 0.65, 0.8, 1, 99]
    分 = pd.cut(r, 邊).value_counts(sort=False)
    反彈 = {"次數": int(len(r)), "達成%": {f"{lv:g}": round(float((r >= lv).mean() * 100), 1) for lv in (0.382, 0.5, 0.618, 1.0)},
          "分布": [{"區間": f"{a:g}～{b:g}" if b < 99 else f"{a:g} 以上", "次數": int(v)} for (a, b), v in zip(zip(邊[:-1], 邊[1:]), 分.to_numpy())]}
    return {"計算日": f"{pd.Timestamp.now():%Y-%m-%d}", "起": f"{C.index.min():%Y-%m-%d}", "迄": f"{C.index.max():%Y-%m-%d}",
            "年線": 年線, "反彈": 反彈}


def 更新價位統計(強制=False, 間隔天數=25):
    """GitHub Actions 每天呼叫；距離上次超過 間隔天數 才重算，結果存 data/level_stats.json。"""
    import json
    檔 = 資料夾 / "level_stats.json"
    if 檔.exists() and not 強制:
        舊 = json.loads(檔.read_text())
        if (pd.Timestamp.now() - pd.Timestamp(舊.get("計算日", "2000-01-01"))).days < 間隔天數:
            print("價位統計：還不用重算")
            return
    結果 = 價位統計()
    檔.write_text(json.dumps(結果, ensure_ascii=False, indent=1))
    print(f"價位統計：年線 {結果['年線']['20日']['次數']} 次、反彈 {結果['反彈']['次數']} 次")


def 讀取價位統計():
    import json
    檔 = 資料夾 / "level_stats.json"
    return json.loads(檔.read_text()) if 檔.exists() else None


def 讀取關注清單():
    """data/watchlists.csv（清單, 代號, 新, 增, 大, 角色, 加入日）：市場評論提到的股票清單（不記人名）。"""
    f = 資料夾 / "watchlists.csv"
    if not f.exists():
        return pd.DataFrame(columns=["清單", "代號", "新", "增", "大", "角色", "加入日"])
    return pd.read_csv(f, dtype=str).fillna("")


def 關注清單表(清單, 今日, 指標):
    """每檔：目前股價、加入日收盤、加入後%、同期加權%、超額%、距 60 日高%、預估 EPS、明年成長、明年預估本益比。
    回傳 (明細, 各清單彙總)。指標要有 代號、date、收盤（含加入日當天）。"""
    if 清單 is None or 清單.empty or 今日 is None:
        return pd.DataFrame(), pd.DataFrame()
    K = 讀取指數K線("TAIEX")
    加 = K.set_index("date")["close"] if K is not None else pd.Series(dtype=float)
    今 = 今日.set_index("代號")
    收 = 指標.pivot_table(index="date", columns="代號", values="收盤") if 指標 is not None else pd.DataFrame()
    高60 = 收.tail(60).max() if len(收) else pd.Series(dtype=float)
    列們 = []
    for _, r in 清單.iterrows():
        c = r["代號"]
        if c not in 今.index:
            continue
        x = 今.loc[c]
        現 = float(x["收盤"])
        日 = pd.Timestamp(r["加入日"]) if r.get("加入日") else None
        基 = np.nan
        if 日 is not None and c in 收.columns:
            s = 收[c][:日].dropna()
            基 = float(s.iloc[-1]) if len(s) else np.nan
        加基 = float(加[:日].iloc[-1]) if 日 is not None and len(加[:日]) else np.nan
        加後 = (float(加.iloc[-1]) / 加基 - 1) * 100 if pd.notna(加基) and len(加) else np.nan
        後 = (現 / 基 - 1) * 100 if pd.notna(基) and 基 > 0 else np.nan
        標 = "".join(k for k in ("新", "增", "大") if str(r.get(k, "")).strip() in ("1", "Y", "y", "✓", "是"))
        列們.append({"清單": r["清單"], "代號": c, "名稱": x.get("名稱", ""), "角色": r.get("角色", ""), "標記": 標,
                    "收盤": 現, "加入日": r.get("加入日", ""), "加入後%": round(後, 1) if pd.notna(後) else np.nan,
                    "超額%": round(後 - 加後, 1) if pd.notna(後) and pd.notna(加後) else np.nan,
                    "距60日高%": round((現 / float(高60[c]) - 1) * 100, 1) if c in 高60.index and pd.notna(高60[c]) else np.nan,
                    "預估EPS今年": x.get("預估EPS今年", np.nan), "預估EPS明年": x.get("預估EPS明年", np.nan),
                    "明年EPS成長%": x.get("明年EPS成長%", np.nan), "明年預估本益比": x.get("明年預估本益比", np.nan),
                    "_市值": 現 * float(x.get("發行股數", np.nan) or np.nan)})
    明 = pd.DataFrame(列們)
    if 明.empty:
        return 明, pd.DataFrame()
    彙們 = []
    for 名, g in 明.groupby("清單", sort=False):
        e = pd.to_numeric(g["預估EPS明年"], errors="coerce")
        有 = (e > 0) & g["_市值"].notna()
        股數 = g["_市值"] / g["收盤"]
        彙們.append({"清單": 名, "檔數": len(g), "加入後平均%": round(float(g["加入後%"].mean()), 1),
                    "超額平均%": round(float(g["超額%"].mean()), 1),
                    "明年EPS成長中位數%": round(float(pd.to_numeric(g["明年EPS成長%"], errors="coerce").median()), 1),
                    "明年預估本益比(合計)": round(float(g["_市值"][有].sum() / (e[有] * 股數[有]).sum()), 1) if 有.any() else np.nan,
                    "距60日高平均%": round(float(g["距60日高%"].mean()), 1)})
    return 明.drop(columns="_市值"), pd.DataFrame(彙們)


def 讀取領頭連動():
    """data/leader_groups.csv（組, 領頭, 跟隨, 說明）：跟隨＝空白分隔的代號。"""
    f = 資料夾 / "leader_groups.csv"
    if not f.exists():
        return pd.DataFrame(columns=["組", "領頭", "跟隨", "說明"])
    return pd.read_csv(f, dtype=str).fillna("")


def 領頭連動(組表, 指標, 均線=20, 跌破天數=10, 之後=20):
    """領頭股站回月線（前 跌破天數 天都在月線下，今天收盤站上）時，同組跟隨股之後 之後 日平均漲跌 vs 跟隨股一般日子。
    回傳 (目前狀態表, 回測表)。指標要有 代號、date、收盤（建議用還原價：有 還原價 欄就用）。"""
    if 組表 is None or 組表.empty or 指標 is None:
        return pd.DataFrame(), pd.DataFrame()
    欄 = "還原價" if "還原價" in 指標.columns else "收盤"
    收 = 指標.pivot_table(index="date", columns="代號", values=欄).sort_index()
    狀們, 測們 = [], []
    for _, r in 組表.iterrows():
        頭 = r["領頭"]
        跟 = [c for c in r["跟隨"].split() if c in 收.columns]
        if 頭 not in 收.columns or not 跟:
            continue
        s = 收[頭].dropna()
        ma = s.rolling(均線).mean()
        下 = s < ma
        站回 = (~下) & 下.shift(1).rolling(跌破天數).min().fillna(0).astype(bool)
        跟後 = (收[跟].shift(-之後) / 收[跟] - 1) * 100
        事件 = 跟後.loc[站回[站回].index].mean(axis=1).dropna()
        基 = 跟後.stack().dropna()
        跟20 = (收[跟].iloc[-1] / 收[跟].iloc[-21] - 1) * 100 if len(收) > 21 else pd.Series(np.nan, index=跟)
        狀們.append({"組": r["組"], "領頭": 頭, "領頭距月線%": round(float((s.iloc[-1] / ma.iloc[-1] - 1) * 100), 1),
                    "領頭狀態": "今天站回月線" if bool(站回.iloc[-1]) else ("月線上" if not bool(下.iloc[-1]) else "月線下"),
                    "連續月線下天數": int(下[::-1].cumprod().sum()),
                    "跟隨股20日平均%": round(float(跟20.mean()), 1), "跟隨": " ".join(跟), "說明": r.get("說明", "")})
        測們.append({"組": r["組"], "站回次數": int(len(事件)), f"跟隨股之後{之後}日平均%": round(float(事件.mean()), 2) if len(事件) else np.nan,
                    "跟隨股一般日子%": round(float(基.mean()), 2) if len(基) else np.nan,
                    "上漲比率%": round(float((事件 > 0).mean() * 100)) if len(事件) else np.nan})
    return pd.DataFrame(狀們), pd.DataFrame(測們)


def 今日領頭站回(組表, 指標):
    """LINE 用：今天剛站回月線的領頭股。回傳 list of (組, 領頭, 跟隨)。"""
    狀, _ = 領頭連動(組表, 指標)
    if 狀.empty:
        return []
    return [(r["組"], r["領頭"], r["跟隨"]) for _, r in 狀[狀["領頭狀態"] == "今天站回月線"].iterrows()]


def 資本支出警示(表, 季減門檻=-10.0):
    """AI 巨頭資本支出：最新一季比上一季、比去年同季。任兩家季減超過 季減門檻%，或合計年增率連兩季下滑 → 🟠／🔴。
    回傳 (燈, 說明, 明細表)。表：macro.讀取資本支出()。"""
    if 表 is None or 表.empty:
        return "⚪", "沒有資本支出資料", pd.DataFrame()
    t = 表.copy().sort_values("quarter")
    列們 = []
    for 代, g in t.groupby("symbol"):
        g = g.set_index("quarter")["capex"].dropna()
        if len(g) < 2:
            continue
        q = g.index[-1]
        去 = f"{int(q[:4]) - 1}{q[4:]}"
        列們.append({"公司": t.loc[t["symbol"] == 代, "name"].iloc[-1], "季度": q, "資本支出(億美元)": round(float(g.iloc[-1]) / 1e8, 0),
                    "季增%": round(float((g.iloc[-1] / g.iloc[-2] - 1) * 100), 1),
                    "年增%": round(float((g.iloc[-1] / g[去] - 1) * 100), 1) if 去 in g.index and g[去] else np.nan})
    明 = pd.DataFrame(列們)
    樞 = t.pivot_table(index="quarter", columns="symbol", values="capex").sort_index()
    年增 = {}
    for q in 樞.index:  # 只用「今年這季和去年同季都有資料」的公司加總，缺資料的公司不會讓年增率失真
        去 = f"{int(q[:4]) - 1}{q[4:]}"
        if 去 not in 樞.index:
            continue
        有 = 樞.loc[q].notna() & 樞.loc[去].notna()
        if 有.sum() >= 3:
            年增[q] = float((樞.loc[q, 有].sum() / 樞.loc[去, 有].sum() - 1) * 100)
    年增 = pd.Series(年增, dtype=float)
    季減家 = 明[明["季增%"] <= 季減門檻]["公司"].tolist() if len(明) else []
    放緩 = len(年增) >= 3 and 年增.iloc[-1] < 年增.iloc[-2] < 年增.iloc[-3]
    if len(季減家) >= 2 or (len(年增) and 年增.iloc[-1] < 0):
        燈 = "🔴"
    elif 季減家 or 放緩:
        燈 = "🟠"
    else:
        燈 = "🟢"
    話 = (f"合計年增 {年增.iloc[-1]:+.0f}%（{年增.index[-1]}）" if len(年增) else "合計年增：資料不足")
    if 放緩:
        話 += f"，已連兩季放緩（{年增.iloc[-3]:+.0f}% → {年增.iloc[-2]:+.0f}% → {年增.iloc[-1]:+.0f}%）"
    if 季減家:
        話 += f"；最新一季比上一季減少超過 {abs(季減門檻):.0f}%：{'、'.join(季減家)}"
    if 燈 == "🟢":
        話 += "；沒有大廠縮手的跡象"
    return 燈, 話, 明


# ========== 34. 網紅摘要 11/09 建議：反彈力道、KD＋站上短均、反彈兩階段、ETF 事件、國安長期歷史、標普大跌後波動 ==========
def 反彈首日(K, 跌幅門檻=-3.0, 等待=5, 反彈門檻=1.5, 天數=(5, 10, 20)):
    """大跌（單日 ≤ 跌幅門檻%）之後 等待 天內，第一個單日漲 ≥ 反彈門檻% 的日子＝「反彈首日」。
    站上＝收盤在 5 日線上（強反彈）；碰線被壓＝最高碰到 5 日線但收盤在下面（弱反彈）；沒碰到＝最高都沒到 5 日線。
    K：date、high、close。回傳 (事件 DataFrame 新的在上面, 統計 DataFrame, 最新 dict 或 None)。"""
    if K is None or len(K) < 30:
        return pd.DataFrame(), pd.DataFrame(), None
    k = K[["date", "high", "close"]].dropna().reset_index(drop=True) if "high" in K else \
        K[["date", "close"]].dropna().assign(high=lambda d: d["close"]).reset_index(drop=True)
    收, 高 = k["close"].to_numpy("float64"), k["high"].to_numpy("float64")
    報 = np.r_[np.nan, (收[1:] / 收[:-1] - 1) * 100]
    線 = k["close"].rolling(5).mean().to_numpy("float64")
    列們, 已 = [], set()
    for i in np.flatnonzero(報 <= 跌幅門檻):
        for j in range(i + 1, min(i + 等待, len(k) - 1) + 1):
            if 報[j] >= 反彈門檻:
                if j not in 已 and not np.isnan(線[j]):
                    已.add(j)
                    類 = "站上 5 日線" if 收[j] >= 線[j] else ("碰線被壓" if 高[j] >= 線[j] else "沒碰到 5 日線")
                    列 = {"日期": k.at[j, "date"], "大跌日": k.at[i, "date"], "大跌%": round(報[i], 2), "反彈日%": round(報[j], 2),
                          "5日線": round(線[j], 1), "收盤": round(收[j], 1), "類型": 類}
                    for n in 天數:
                        列[f"{n}日後%"] = round((收[j + n] / 收[j] - 1) * 100, 2) if j + n < len(k) else np.nan
                    列們.append(列)
                break
    事 = pd.DataFrame(列們)
    if not len(事):
        return 事, pd.DataFrame(), None
    統 = []
    for 類, g in [("全部", 事)] + list(事.groupby("類型")):
        列 = {"類型": 類, "次數": len(g)}
        for n in 天數:
            s = g[f"{n}日後%"].dropna()
            列[f"{n}日平均%"] = round(float(s.mean()), 2) if len(s) else None
            列[f"{n}日上漲%"] = round(float((s > 0).mean() * 100)) if len(s) else None
        統.append(列)
    基 = {"類型": "任何一天買進", "次數": None}
    for n in 天數:
        r = (k["close"].shift(-n) / k["close"] - 1) * 100
        基[f"{n}日平均%"], 基[f"{n}日上漲%"] = round(float(r.mean()), 2), round(float((r.dropna() > 0).mean() * 100))
    統.append(基)
    最新 = None
    if len(k) - 1 in 已 or any(len(k) - 1 - j <= 2 for j in 已):
        最新 = 事.iloc[-1].to_dict()
    return 事.iloc[::-1].reset_index(drop=True), pd.DataFrame(統), 最新


def _kd(K, 期=9):
    h = K["high"].astype(float) if "high" in K else K["close"].astype(float)
    l = K["low"].astype(float) if "low" in K else K["close"].astype(float)
    c = K["close"].astype(float)
    rsv = ((c - l.rolling(期).min()) / (h.rolling(期).max() - l.rolling(期).min()).replace(0, np.nan) * 100).fillna(50)
    k, d, kk, dd = [], [], 50.0, 50.0
    for v in rsv:
        kk, dd = kk * 2 / 3 + v / 3, dd * 2 / 3 + kk / 3
        k.append(kk)
        d.append(dd)
    return pd.Series(k, index=K.index), pd.Series(d, index=K.index)


def 止跌KD條件(K, 回落門檻=-8.0, 天數=(5, 10, 20), 間隔=10):
    """王老先聲「量縮時止跌」：KD 黃金交叉＋收盤站上 5 日與 10 日線。只看「離 20 日高點已跌 ≥ 回落門檻%」的日子。
    回傳 (事件 DataFrame, 統計 DataFrame, 今天 dict(三條件亮不亮))。"""
    if K is None or len(K) < 40:
        return pd.DataFrame(), pd.DataFrame(), None
    t = K.reset_index(drop=True)
    c = t["close"].astype(float)
    kv, dv = _kd(t)
    金叉 = (kv > dv) & (kv.shift(1) <= dv.shift(1))
    站 = (c > c.rolling(5).mean()) & (c > c.rolling(10).mean())
    回 = (c / c.rolling(20).max() - 1) * 100
    今 = {"KD 黃金交叉": bool(金叉.iloc[-1]), "站上 5、10 日線": bool(站.iloc[-1]), "K": round(float(kv.iloc[-1]), 1),
          "D": round(float(dv.iloc[-1]), 1), "離 20 日高%": round(float(回.iloc[-1]), 1), "日期": t["date"].iloc[-1]}
    位們, 上 = [], -10 ** 9
    for i in np.flatnonzero((金叉 & 站 & (回 <= 回落門檻)).to_numpy()):
        if i - 上 > 間隔:
            位們.append(i)
            上 = i
    列們 = []
    for i in 位們:
        列 = {"日期": t["date"].iloc[i], "收盤": round(float(c.iloc[i]), 1), "離20日高%": round(float(回.iloc[i]), 1)}
        for n in 天數:
            列[f"{n}日後%"] = round((c.iloc[i + n] / c.iloc[i] - 1) * 100, 2) if i + n < len(c) else np.nan
        列們.append(列)
    事 = pd.DataFrame(列們)
    統 = []
    基碼 = (回 <= 回落門檻)
    for 名, 遮罩位 in (("KD 金叉＋站上 5、10 日線", 位們), ("同樣回落、任何一天", list(np.flatnonzero(基碼.to_numpy())))):
        列 = {"類型": 名, "次數": len(遮罩位)}
        for n in 天數:
            r = ((c.shift(-n) / c - 1) * 100).iloc[遮罩位].dropna()
            列[f"{n}日平均%"] = round(float(r.mean()), 2) if len(r) else None
            列[f"{n}日上漲%"] = round(float((r > 0).mean() * 100)) if len(r) else None
        統.append(列)
    return (事.iloc[::-1].reset_index(drop=True) if len(事) else 事), pd.DataFrame(統), 今


def 反彈輪動(價, 深跌=-25.0, 高位=-10.0, 回看=60):
    """阿信「天秤兩端」：第一階段資金先回跌深股、第二階段輪到高位階高本益比的成長股。
    價：code、date、close、pe（至少最近 回看+1 天）。跌深＝收盤離 回看 日高 ≤ 深跌%；高位階＝離高點不到 -高位% 且本益比高於全市場中位數。
    （網站沒有每檔融資維持率，所以用「跌深＋本益比」代替「融資維持率爆掉」。）
    回傳 dict(日期, 組別 DataFrame（每組：檔數、近 N 日平均%、今日漲停數）, 階段, 說明) 或 None。"""
    if 價 is None or not len(價):
        return None
    p = 價[價["code"].astype(str).str.fullmatch(r"\d{4}")][["code", "date", "close", "pe"]].copy()
    p["close"] = p["close"].astype("float64")
    寬 = p.pivot_table(index="date", columns="code", values="close").sort_index()
    if len(寬) < 6:
        return None
    寬 = 寬.tail(回看 + 1)
    今 = 寬.iloc[-1]
    離高 = (今 / 寬.max() - 1) * 100
    pe = p[p["date"] == 寬.index[-1]].set_index("code")["pe"].astype("float64")
    中位 = float(pe[pe > 0].median())
    報 = {1: (今 / 寬.iloc[-2] - 1) * 100, 3: (今 / 寬.iloc[-4] - 1) * 100}
    組 = {"① 跌深（離高點 ≥ 25%）": 離高 <= 深跌,
          "② 高位階高本益比": (離高 >= 高位) & (pe.reindex(今.index) > 中位),
          "其他": ~((離高 <= 深跌) | ((離高 >= 高位) & (pe.reindex(今.index) > 中位)))}
    列們 = []
    for 名, m in 組.items():
        m = m.fillna(False)
        列們.append({"組別": 名, "檔數": int(m.sum()), "今日平均%": round(float(報[1][m].mean()), 2) if m.any() else None,
                   "近 3 日平均%": round(float(報[3][m].mean()), 2) if m.any() else None,
                   "今日漲停(≥9.5%)": int((報[1][m] >= 9.5).sum())})
    表 = pd.DataFrame(列們)
    甲, 乙 = 表.iloc[0], 表.iloc[1]
    if pd.notna(甲["今日平均%"]) and pd.notna(乙["今日平均%"]):
        差 = 甲["今日平均%"] - 乙["今日平均%"]
        階段 = "第一階段：資金先回跌深股" if 差 >= 1 else ("第二階段：資金轉向高位階高成長股" if 差 <= -1 else "兩端差不多，還在同步反彈")
    else:
        階段 = "資料不足"
    return {"日期": 寬.index[-1], "組別": 表, "階段": 階段, "本益比中位": round(中位, 1),
            "說明": f"今日跌深組平均 {甲['今日平均%']:+.2f}%、高位階組 {乙['今日平均%']:+.2f}%" if 階段 != "資料不足" else ""}


def 讀取反彈輪動():
    價 = _讀每日檔("prices", 最近天數=65)
    return 反彈輪動(價)


def 讀取ETF事件():
    """data/etf_events.csv：日期、代號、名稱、事件、備註（人工整理自投信公告／媒體，以公告為準）。"""
    f = 資料夾 / "etf_events.csv"
    if not f.exists():
        return pd.DataFrame()
    t = pd.read_csv(f, dtype=str).fillna("")
    t["日期"] = pd.to_datetime(t["日期"], errors="coerce")
    return t.dropna(subset=["日期"]).sort_values("日期").reset_index(drop=True)


def 讀取長期指數(K):
    """data/index_long.csv（每天補一段 2000 年以來的加權收盤）接在 K 前面，給國安基金歷史回測用。"""
    f = 資料夾 / "index_long.csv"
    if K is None or not f.exists():
        return K
    t = pd.read_csv(f, parse_dates=["date"])
    t = t[t["date"] < K["date"].min()]
    if not len(t):
        return K
    t = t.assign(open=t["close"], high=t["close"], low=t["close"])
    return pd.concat([t[["date", "open", "high", "low", "close"]], K[["date", "open", "high", "low", "close"]]], ignore_index=True)


def 國安基金平均(表, 天數=(20, 60, 120)):
    """國安基金統計() 的歷次平均：N 日後平均、上漲機率、有資料的次數。"""
    if 表 is None or not len(表):
        return pd.DataFrame()
    列們 = []
    for n in 天數:
        if f"{n}日%" not in 表:
            continue
        s = 表[f"{n}日%"].dropna()
        列們.append({"天數": n, "次數": len(s), "平均%": round(float(s.mean()), 1) if len(s) else None,
                   "上漲機率%": round(float((s > 0).mean() * 100)) if len(s) else None})
    return pd.DataFrame(列們)


def 單日大跌後波動(美, 跌幅門檻=-4.0, 窗=20, 基準窗=None):
    """S&P 500 單日跌幅 ≤ 跌幅門檻% 之後 窗 日的年化波動率，對照全期間平均的 窗 日年化波動率。
    美：Series（index＝日期、值＝收盤）。回傳 dict(次數, 之後波動%, 全期間波動%, 放大次數) 或 None。"""
    if 美 is None or len(美) < 300:
        return None
    s = 美.astype("float64").dropna().sort_index()
    r = s.pct_change() * 100
    後 = r[::-1].rolling(窗).std()[::-1].shift(-1) * np.sqrt(252)   # 事件隔天起算 窗 日
    全 = float((r.rolling(窗).std() * np.sqrt(252)).mean())
    位 = np.flatnonzero((r <= 跌幅門檻).to_numpy())
    vals = 後.iloc[位].dropna()
    if not len(vals):
        return None
    return {"次數": int(len(vals)), "之後波動%": round(float(vals.mean()), 1), "全期間波動%": round(全, 1),
            "放大次數": int((vals > 全).sum()), "起": f"{s.index[0]:%Y-%m-%d}"}


# ========== 網紅摘要 2026-11-10 建議：美股指數缺口、資料中心成長趨緩、外資空單回測、目標價大砍、指數數字查核 ==========
def 美股指數缺口(符號="^SOX"):
    """費半、那斯達克的未回補缺口（data/us_ohlc.csv，每日更新）。回傳 dict(收盤, 日期, 上方, 下方, 燈, 說明)，沒資料回 None。
    上方缺口＝向下跳空留下的壓力（還沒補到），下方缺口＝向上跳空留下的支撐。"""
    f = 資料夾 / "us_ohlc.csv"
    if not f.exists():
        return None
    t = pd.read_csv(f, parse_dates=["date"])
    K = t[t["symbol"] == 符號].sort_values("date").reset_index(drop=True)
    if len(K) < 30 or not 有開高低(K):
        return None
    收 = float(K["close"].iloc[-1])
    缺 = 找缺口(K, 天數=120)
    上 = sorted([g for g in 缺 if g[0] > 收], key=lambda g: g[0])
    下 = sorted([g for g in 缺 if g[1] < 收], key=lambda g: -g[1])
    if 上:
        g = 上[0]
        燈 = "🟠"
        話 = f"收盤 {收:,.0f}，上方 {g[2]:%m/%d} 向下跳空缺口 {g[0]:,.0f}～{g[1]:,.0f} 還沒補（距下緣 {(g[0] / 收 - 1) * 100:+.1f}%）"
    else:
        燈 = "🟢"
        話 = f"收盤 {收:,.0f}，上方近 120 天沒有未回補的向下缺口"
    if 下:
        g = 下[0]
        話 += f"；下方 {g[2]:%m/%d} 向上缺口 {g[0]:,.0f}～{g[1]:,.0f} 是支撐"
    return {"收盤": 收, "日期": K["date"].iloc[-1], "上方": 上, "下方": 下, "燈": 燈, "說明": 話}


def 資料中心成長趨緩():
    """data/dc_capex_growth.csv（手動從外資報告整理：項目, 年度, 數值, 來源日期）。
    判斷：年增率是否逐年下滑（成長趨緩 → 市場先下修本益比）、新增電力容量是否首度比前一年少。回傳 dict 或 None。"""
    f = 資料夾 / "dc_capex_growth.csv"
    if not f.exists():
        return None
    t = pd.read_csv(f)
    資 = t[t["項目"] == "四大CSP資本支出年增%"].sort_values("年度")
    電 = t[t["項目"] == "美國資料中心新增電力GW"].sort_values("年度")
    if len(資) < 2:
        return None
    趨緩 = bool((資["數值"].diff().dropna() < 0).all())
    電減 = [int(r.年度) for a, r in zip(電["數值"].values[:-1], 電.iloc[1:].itertuples()) if r.數值 < a]
    燈 = "🔴" if 趨緩 and 電減 else ("🟠" if 趨緩 or 電減 else "🟢")
    話 = "、".join(f"{int(r.年度)} 年 {r.數值:+.0f}%" for r in 資.itertuples()) + ("（逐年下滑，成長趨緩）" if 趨緩 else "")
    if len(電):
        話 += "；新增電力 " + "、".join(f"{int(r.年度)} 年 {r.數值:g}GW" for r in 電.itertuples())
        if 電減:
            話 += f"（{'、'.join(map(str, 電減))} 年首度比前一年少）"
    return {"燈": 燈, "說明": 話, "表": t, "來源日期": str(t["來源日期"].max())}


def 外資空單回測(K, 門檻們=(-50000, -80000, -100000), 天們=(5, 20)):
    """外資台指期淨未平倉很空（≤ 門檻口）的日子，之後 5／20 日大盤報酬，對照所有日子。
    K：大盤 K 線（date, close）。資料從 2025-09 起，樣本很少，次數不到 10 次只能當參考。回傳 DataFrame。"""
    oi = 讀取期貨未平倉()
    if oi is None or K is None or not len(K):
        return pd.DataFrame()
    收 = K.set_index("date")["close"].sort_index()
    外 = oi["foreign_oi"].reindex(收.index)
    列們 = []
    for 名, 遮 in [("全部日子", 外.notna())] + [(f"外資淨空 ≥ {-m // 10000} 萬口", 外 <= m) for m in 門檻們]:
        列 = {"條件": 名, "次數": int(遮.sum())}
        for n in 天們:
            後 = (收.shift(-n) / 收 - 1) * 100
            v = 後[遮].dropna()
            列[f"{n}日後平均%"] = round(float(v.mean()), 2) if len(v) else np.nan
            列[f"{n}日後上漲%"] = round(float((v > 0).mean() * 100), 0) if len(v) else np.nan
            列[f"{n}日樣本"] = int(len(v))
        列們.append(列)
    return pd.DataFrame(列們)


def 目標價大砍(拆, 門檻=-30.0):
    """從 目標價拆解 的結果挑出目標價下修 門檻% 以上的，並說明是砍估值還是砍獲利（大砍多半是估值調整，不是獲利衰退）。"""
    if 拆 is None or not len(拆):
        return pd.DataFrame()
    t = 拆[拆["總變動%"] <= 門檻].copy()
    if not len(t):
        return t
    def 說(r):
        倍, 獲 = r["倍數變動%"], r["EPS與年度變動%"]
        if pd.isna(倍):
            return "倍數資料不足"
        return "主要是砍本益比（估值下修，獲利預估沒大變）" if abs(倍) >= abs(獲) else "主要是獲利預估下修"
    t["原因"] = t.apply(說, axis=1)
    return t[["日期", "代號", "名稱", "券商", "前次目標價", "目標價", "總變動%", "倍數變動%", "EPS與年度變動%", "原因"]].reset_index(drop=True)


_指數對照 = {"費半": "^SOX", "那斯達克": "^IXIC", "標普": "^GSPC", "標普500": "^GSPC", "道瓊": "^DJI", "加權": "TAIEX", "大盤": "TAIEX"}


def 指數說法查核(影片們, 容許=0.3):
    """影片紀錄裡的「指數說法」（[{指數, 日期, 收盤}]，日期是該收盤價的交易日）對 data 查核：差距超過 容許% 標「不符」；
    不同頻道對同一指數同一天的數字互相不一致，也列出來。回傳 (逐筆表, 衝突表)。"""
    美 = pd.read_csv(資料夾 / "us_daily.csv") if (資料夾 / "us_daily.csv").exists() else pd.DataFrame(columns=["date", "symbol", "close"])
    台 = pd.read_csv(資料夾 / "index_ohlc.csv") if (資料夾 / "index_ohlc.csv").exists() else pd.DataFrame(columns=["date", "symbol", "close"])
    價 = pd.concat([美[["date", "symbol", "close"]], 台[台["symbol"] == "TAIEX"][["date", "symbol", "close"]]])
    字典 = {(str(r.date), r.symbol): float(r.close) for r in 價.itertuples()}
    列們 = []
    for v in 影片們:
        for s in v.get("指數說法") or []:
            符 = _指數對照.get(str(s.get("指數")))
            實 = 字典.get((str(s.get("日期")), 符))
            說 = _數(s.get("收盤"))
            if 符 is None or 實 is None or np.isnan(說):
                continue
            差 = (說 / 實 - 1) * 100
            列們.append({"頻道": v.get("頻道"), "影片日期": v.get("日期"), "指數": s.get("指數"), "交易日": s.get("日期"),
                       "說的收盤": 說, "資料收盤": round(實, 2), "差距%": round(差, 2), "判定": "相符" if abs(差) <= 容許 else "不符"})
    表 = pd.DataFrame(列們)
    衝 = []
    if len(表):
        for (指, 日), g in 表.groupby(["指數", "交易日"]):
            if g["頻道"].nunique() >= 2 and (g["說的收盤"].max() / g["說的收盤"].min() - 1) * 100 > 容許:
                衝.append({"指數": 指, "交易日": 日, "資料收盤": g["資料收盤"].iloc[0],
                         "各頻道說法": "；".join(f"{r.頻道} {r.說的收盤:,.0f}" for r in g.itertuples())})
    return 表, pd.DataFrame(衝)


# ========== 2026-11-11 網紅摘要建議：降評利空測試、連板統計、無量上漲、族群連續流入、台幣×外資警示 ==========
def _交易日位置(日們, 日):
    """事件日對到交易日（非交易日用下一個交易日），沒有就回傳 None。"""
    位 = 日們.searchsorted(pd.Timestamp(日), side="left")
    return None if 位 >= len(日們) else int(位)


def 降評利空測試(報告們, 指標, 下修門檻=-5.0):
    """外資／券商下修目標價（比前次低 門檻% 以上）當天，股價有沒有「利空不跌」。
    過關＝開低走高（開盤低於昨收、收盤高於開盤）或收盤不低於昨收；不過關＝收盤比昨收低。
    回傳 (事件表, 摘要表)：摘要比較過關與不過關事件之後 5／20 日報酬。指標需含 open、收盤、還原價、date、代號。"""
    if not len(報告們) or 指標 is None or not len(指標):
        return pd.DataFrame(), pd.DataFrame()
    價 = 指標[["date", "代號", "open", "收盤", "還原價"]]
    列們 = []
    for x in 報告們:
        目, 前 = _數(x.get("目標價")), _數(x.get("前次目標價"))
        if np.isnan(目) or np.isnan(前) or 前 <= 0 or (目 / 前 - 1) * 100 > 下修門檻:
            continue
        列們.append({"日期": pd.Timestamp(x.get("日期")), "代號": str(x.get("代號")), "名稱": x.get("名稱"), "券商": x.get("券商"),
                    "目標價變動%": round((目 / 前 - 1) * 100, 1)})
    if not 列們:
        return pd.DataFrame(), pd.DataFrame()
    事 = pd.DataFrame(列們).drop_duplicates(["日期", "代號", "券商"])
    分 = {c: g.sort_values("date").reset_index(drop=True) for c, g in 價.groupby("代號")}
    結 = []
    for r in 事.itertuples():
        g = 分.get(r.代號)
        if g is None or len(g) < 3:
            continue
        位 = _交易日位置(pd.DatetimeIndex(g["date"]), r.日期)
        if 位 is None or 位 < 1:
            continue
        昨, 開, 收 = float(g.loc[位 - 1, "收盤"]), float(g.loc[位, "open"]), float(g.loc[位, "收盤"])
        過 = (開 < 昨 and 收 > 開) or 收 >= 昨
        列 = r._asdict()
        列.pop("Index", None)
        列.update({"交易日": g.loc[位, "date"], "開盤%": round((開 / 昨 - 1) * 100, 2), "收盤%": round((收 / 昨 - 1) * 100, 2),
                  "利空測試": "過關" if 過 else "沒過"})
        基 = float(g.loc[位, "還原價"])
        for n in (5, 20):
            列[f"{n}日後%"] = round((float(g.loc[位 + n, "還原價"]) / 基 - 1) * 100, 2) if 位 + n < len(g) else np.nan
        結.append(列)
    if not 結:
        return pd.DataFrame(), pd.DataFrame()
    表 = pd.DataFrame(結).sort_values("交易日", ascending=False).reset_index(drop=True)
    摘 = []
    for 名, 遮 in [("全部降評", 表["利空測試"].notna())] + [(f"利空測試{k}", 表["利空測試"] == k) for k in ("過關", "沒過")]:
        g = 表[遮]
        摘.append({"條件": 名, "件數": int(len(g)), "5日後平均%": round(float(g["5日後%"].mean()), 2) if g["5日後%"].notna().any() else np.nan,
                  "20日後平均%": round(float(g["20日後%"].mean()), 2) if g["20日後%"].notna().any() else np.nan,
                  "20日樣本": int(g["20日後%"].notna().sum())})
    return 表, pd.DataFrame(摘)


def 連板統計(指標, 連板們=(2, 3), 漲停門檻=0.095):
    """連續漲停（收盤接近漲停：日報酬 ≥ 9.5% 且收在當天最高）的股票。
    回傳 (今日連板, 統計)：今日連板有代號、名稱、連板天數、產業；統計是歷史上連板 N 天之後隔天、5 天的報酬，對照所有一般日子。"""
    if 指標 is None or not len(指標):
        return pd.DataFrame(), pd.DataFrame()
    t = 指標[指標["代號"].str.fullmatch(r"[1-9]\d{3}")].sort_values(["代號", "date"]).copy()
    t["板"] = (t["日報酬"] >= 漲停門檻) & (t["收盤"] >= t["high"] - 1e-9)
    群 = t.groupby("代號", sort=False)
    t["連板"] = _連續天數(t["板"], t["代號"])
    t["隔日%"] = (群["還原價"].shift(-1) / t["還原價"] - 1) * 100
    t["五日%"] = (群["還原價"].shift(-5) / t["還原價"] - 1) * 100
    最新 = t["date"].max()
    今 = t[(t["date"] == 最新) & (t["連板"] >= 2)].copy()
    股 = _股本表()
    今["產業"] = 今["代號"].map(股["產業"])
    今 = 今.sort_values("連板", ascending=False)[["代號", "名稱", "連板", "產業", "收盤", "漲跌幅"]].reset_index(drop=True)
    列們 = [{"條件": "全部日子", "次數": int(t["隔日%"].notna().sum()), "隔日平均%": round(float(t["隔日%"].mean()), 2),
            "隔日上漲%": round(float((t["隔日%"].dropna() > 0).mean() * 100)), "5日平均%": round(float(t["五日%"].mean()), 2)}]
    for n in 連板們:
        g = t[t["連板"] == n]
        列們.append({"條件": f"連板第 {n} 天收盤", "次數": int(g["隔日%"].notna().sum()),
                    "隔日平均%": round(float(g["隔日%"].mean()), 2) if g["隔日%"].notna().any() else np.nan,
                    "隔日上漲%": round(float((g["隔日%"].dropna() > 0).mean() * 100)) if g["隔日%"].notna().any() else np.nan,
                    "5日平均%": round(float(g["五日%"].mean()), 2) if g["五日%"].notna().any() else np.nan})
    return 今, pd.DataFrame(列們)


def 無量上漲回測(K, 指標, 漲幅門檻=2.0, 天們=(5, 20)):
    """大盤單日大漲 漲幅門檻% 以上時，成交值比 20 日均量小（無量）或大（有量），之後 5／20 日報酬。
    成交值用 指標 全市場加總（只有近一年多，樣本少）。K：大盤 K 線（date, close）。回傳 DataFrame。"""
    if K is None or 指標 is None or not len(K) or not len(指標):
        return pd.DataFrame()
    量 = 指標.groupby("date")["value"].sum().sort_index()
    比 = 量 / 量.rolling(20, min_periods=10).mean().shift(1)
    收 = K.set_index("date")["close"].sort_index()
    漲 = (收.pct_change() * 100).reindex(比.index)
    列們 = []
    大 = 漲 >= 漲幅門檻
    for 名, 遮 in [("全部日子", 漲.notna() & 比.notna()), (f"大漲 {漲幅門檻:g}% 以上（全部）", 大 & 比.notna()),
                  (f"大漲且無量（量比 < 1）", 大 & (比 < 1)), (f"大漲且有量（量比 ≥ 1）", 大 & (比 >= 1))]:
        列 = {"條件": 名, "次數": int(遮.sum())}
        for n in 天們:
            後 = ((收.shift(-n) / 收 - 1) * 100).reindex(比.index)
            v = 後[遮].dropna()
            列[f"{n}日後平均%"] = round(float(v.mean()), 2) if len(v) else np.nan
            列[f"{n}日後上漲%"] = round(float((v > 0).mean() * 100)) if len(v) else np.nan
            列[f"{n}日樣本"] = int(len(v))
        列們.append(列)
    return pd.DataFrame(列們)


def 族群連續流入(指標, 分類="產業", 最少=3):
    """族群「資金流入日」＝當天族群上漲，且成交值占全市場比例高於前 20 日平均；回傳連續流入 最少 天以上的族群（含連續天數）。
    對照網紅「連三天資金流入可抱小波段、熱度退了就走」。"""
    if 指標 is None or not len(指標):
        return pd.DataFrame()
    報 = 族群日報酬(指標, 分類)
    t = 指標[["date", "代號", "value"]].copy()
    if 分類 == "概念股":
        t = t.merge(讀取概念().rename(columns={"code": "代號", "concept": "族群"}), on="代號")
    else:
        股 = _股本表()
        t["族群"] = t["代號"].map(股["產業"])
        t = t[~t["代號"].str.startswith("0") & (t["族群"].fillna("") != "")]
    總 = 指標.groupby("date")["value"].sum()
    占 = (t.groupby(["date", "族群"])["value"].sum().unstack().div(總, axis=0))
    占 = 占.reindex(報.index)
    流入 = (報 > 0) & (占 > 占.rolling(20, min_periods=10).mean().shift(1))
    列們 = []
    for 族 in 流入.columns:
        s = 流入[族].to_numpy()
        n = 0
        for v in s[::-1]:
            if not v:
                break
            n += 1
        if n >= 最少:
            列們.append({"族群": 族, "連續流入天數": n, "今日漲跌%": round(float(報[族].iloc[-1]), 2),
                        "成交值占比%": round(float(占[族].iloc[-1] * 100), 1)})
    return pd.DataFrame(列們).sort_values("連續流入天數", ascending=False).reset_index(drop=True) if 列們 else pd.DataFrame()


def 台幣外資警示(匯率, 指標, 連續=2):
    """新台幣連 連續 天貶值（美元兌台幣上升）且外資賣超 → 🟠；連續升值且外資買超 → 🟢；其餘 ⚪。
    回傳 dict（燈、說明、匯率、外資億）；資料不足回傳 None。匯率：data/fx.csv（date, usdtwd）。"""
    if 匯率 is None or len(匯率) < 連續 + 1 or 指標 is None or "外資買超" not in 指標.columns:
        return None
    匯 = 匯率.sort_values("date")["usdtwd"].astype(float).tail(連續 + 1).to_numpy()
    差 = np.diff(匯)
    貶, 升 = bool((差 > 0).all()), bool((差 < 0).all())
    最新 = 指標["date"].max()
    今 = 指標[指標["date"] == 最新]
    外 = float((今["外資買超"] * 1000 * 今["收盤"]).sum() / 1e8)
    if 貶 and 外 < 0:
        燈, 說 = "🟠", f"新台幣連 {連續} 天貶值，外資同日賣超約 {abs(外):,.0f} 億：資金外流跡象，反彈延續性要打折。"
    elif 升 and 外 > 0:
        燈, 說 = "🟢", f"新台幣連 {連續} 天升值，外資同日買超約 {外:,.0f} 億：外資沒有大舉匯出。"
    else:
        燈, 說 = "⚪", f"匯率與外資沒有同向（近 {連續} 天匯率變動 {匯[-1] - 匯[0]:+.2f}，外資{'買' if 外 >= 0 else '賣'}超約 {abs(外):,.0f} 億）。"
    return {"燈": 燈, "說明": 說, "匯率": float(匯[-1]), "外資億": 外, "日期": 最新}


# ========== 2026-11-13 網紅摘要建議：輝達事件週、反彈延續燈、國安隔日／一季、營收動能、價位量級提示 ==========
輝達連動股 = ("2330", "2317", "2382", "3231", "2454", "2308", "3443", "3661", "6669", "2345")


def 輝達事件(美股, 指標, 天數=60, 筆數=12):
    """輝達換帥／財報週：財報倒數、輝達最新收盤、離一年高點，以及台股（含供應鏈名單）近 天數 個交易日
    「輝達前一個美股交易日報酬 → 台股隔天報酬」的相關係數。回傳 dict：財報日、倒數天、時段、收盤、單日%、距高%、表。
    相關係數只代表過去一陣子「一起動」的程度，不是營收占比，也不代表因果。"""
    if 美股 is None or "輝達" not in 美股 or 指標 is None or 指標.empty:
        return None
    n = 美股["輝達"].dropna()
    if len(n) < 30:
        return None
    今 = pd.Timestamp(指標["date"].max())
    財報日, 時段 = None, ""
    f = 資料夾 / "us_earnings.csv"
    if f.exists():
        e = pd.read_csv(f, parse_dates=["date"])
        e = e[(e["symbol"] == "NVDA") & (e["date"] >= 今.normalize())].sort_values("date")
        if len(e):
            財報日, 時段 = e.iloc[0]["date"], str(e.iloc[0].get("time", ""))
    碼們 = set(輝達連動股)
    g = 資料夾 / "supply_chain.csv"
    if g.exists():
        碼們 |= set(pd.read_csv(g, dtype=str)["code"].dropna())
    r = n.pct_change().dropna()
    寬 = 指標[指標["代號"].isin(碼們) & (指標["date"] >= 今 - pd.Timedelta(days=int(天數 * 1.8)))].pivot_table(
        index="date", columns="代號", values="日報酬")
    位 = r.index.searchsorted(寬.index, side="left") - 1  # 台股日 d 對應「d 以前最近一個美股日」
    有 = 位 >= 0
    x = pd.Series(r.to_numpy()[位[有]], index=寬.index[有]).tail(天數)
    寬 = 寬.loc[x.index]
    列們 = []
    名 = 指標.drop_duplicates("代號", keep="last").set_index("代號")["名稱"]
    for c in 寬.columns:
        s = 寬[c]
        if s.notna().sum() < 40:
            continue
        列們.append({"代號": c, "名稱": 名.get(c, ""), "相關": round(float(s.corr(x)), 2),
                   "最近一日%": round(float(s.dropna().iloc[-1]) * 100, 1)})
    表 = pd.DataFrame(列們).sort_values("相關", ascending=False).head(筆數) if 列們 else pd.DataFrame()
    return {"財報日": 財報日, "倒數天": (財報日 - 今.normalize()).days if 財報日 is not None else None, "時段": 時段,
            "日期": n.index[-1], "收盤": float(n.iloc[-1]), "單日%": round(float(n.iloc[-1] / n.iloc[-2] - 1) * 100, 1),
            "距高%": round(float(n.iloc[-1] / n.tail(250).max() - 1) * 100, 1), "表": 表}


def _站上均線(s, n):
    s = s.dropna()
    return bool(len(s) > n and s.iloc[-1] > s.tail(n).mean())


def 反彈延續燈(美股, 匯率, K, 重貶=1.0):
    """老王的反彈延續條件：費半、那斯達克守住 5 日線；台幣沒有重貶（5 個交易日升值幅度，美元兌台幣上升超過 重貶% 算重貶）；
    加權守住 5、10 日線。回傳 dict（燈、條件清單[(文字, 是否成立)]、說明）。全成立 🟢；加權跌破 5、10 日線或台幣重貶 🔴；其餘 🟡。"""
    條件 = []
    if 美股 is not None:
        for 名 in ("費城半導體", "那斯達克"):
            if 名 in 美股:
                條件.append((f"{名}站上 5 日線", _站上均線(美股[名], 5)))
    重 = False
    if 匯率 is not None and len(匯率) > 6:
        m = 匯率.sort_values("date")["usdtwd"].astype(float).to_numpy()
        變 = (m[-1] / m[-6] - 1) * 100
        重 = 變 >= 重貶
        條件.append((f"台幣沒有重貶（近 5 日美元兌台幣 {變:+.2f}%，重貶門檻 +{重貶:.1f}%）", not 重))
    破 = False
    if K is not None and len(K) > 12:
        c = K.sort_values("date")["close"].astype(float)
        a, b = _站上均線(c, 5), _站上均線(c, 10)
        條件.append(("加權站上 5 日線", a))
        條件.append(("加權站上 10 日線", b))
        破 = (not a) and (not b)
    if not 條件:
        return None
    全 = all(v for _, v in 條件)
    燈 = "🟢" if 全 else ("🔴" if (破 or 重) else "🟡")
    話 = {"🟢": "條件都成立，反彈有機會延續（老王的說法）。", "🟡": "有條件沒過，反彈延續性要打折，留意是哪一項轉弱。",
         "🔴": "加權跌破 5、10 日線或台幣重貶：照老王的說法，反彈暫時告一段落。"}[燈]
    return {"燈": 燈, "條件": 條件, "說明": 話}


def 反彈延續回測(美股, 匯率, K, 重貶=1.0):
    """把 反彈延續燈 的條件放到歷史：每天收盤後條件全成立 vs 沒有全成立，之後 5、20 個交易日加權報酬。
    美股用「台股日以前最近一個美股交易日」，避免偷看。回傳 DataFrame（組別、天數、次數、平均%、上漲機率%）。"""
    if 美股 is None or K is None or 匯率 is None or "費城半導體" not in 美股 or "那斯達克" not in 美股:
        return pd.DataFrame()
    k = K.sort_values("date").set_index("date")["close"].astype(float)
    ok = (k > k.rolling(5).mean()) & (k > k.rolling(10).mean())
    u = ((美股["費城半導體"] > 美股["費城半導體"].rolling(5).mean()) & (美股["那斯達克"] > 美股["那斯達克"].rolling(5).mean())).dropna()
    位 = u.index.searchsorted(k.index, side="left") - 1
    美 = pd.Series(np.where(位 >= 0, u.to_numpy()[np.clip(位, 0, None)], False), index=k.index)
    m = 匯率.sort_values("date").set_index("date")["usdtwd"].astype(float)
    變 = (m / m.shift(5) - 1) * 100
    台 = (變.reindex(k.index, method="ffill") < 重貶).fillna(False)
    全 = ok & 美 & 台
    起 = u.index.min() + pd.Timedelta(days=10)
    列們 = []
    for n in (5, 20):
        fwd = (k.shift(-n) / k - 1) * 100
        for 名, 遮 in (("條件全成立", 全), ("沒有全成立", ~全)):
            v = fwd[遮 & (k.index >= 起)].dropna()
            if len(v):
                列們.append({"組別": 名, "天數": n, "次數": len(v), "平均%": round(float(v.mean()), 2),
                           "上漲機率%": round(float((v > 0).mean() * 100), 0)})
    return pd.DataFrame(列們)


def 國安隔日一季(表, 門檻=3.0):
    """兆華艾綸說：國安進場後隔天多半噴出 3% 以上，但一季後 4 勝 5 敗。用 國安基金統計 的表對答案
    （一季＝60 個交易日，從決議日收盤起算）。回傳 dict；沒有任何一次可算回傳 None。"""
    if 表 is None or 表.empty or "1日%" not in 表 or "60日%" not in 表:
        return None
    a = 表["1日%"].dropna()
    b = 表["60日%"].dropna()
    if not len(a):
        return None
    return {"隔日次數": len(a), "隔日噴出": int((a >= 門檻).sum()), "隔日上漲": int((a > 0).sum()), "門檻": 門檻,
            "一季次數": len(b), "一季上漲": int((b > 0).sum()), "一季平均%": round(float(b.mean()), 1) if len(b) else np.nan}


def 營收動能名單(今日=None, 營收=None, 下限千元=300000, 筆數=80):
    """股魚：優先選「短期營收動能優於長期、而且營收還在成長」的公司。
    近 3 個月營收合計年增（短期）> 近 12 個月合計年增（長期）> -∞，且短期年增 > 0；
    近 3 個月營收合計（今年與去年同期都要）低於 下限千元（預設 3 億）不列，避免基期很小、年增上萬 % 的公司。回傳 DataFrame（依動能差由大到小）。"""
    if 營收 is None:
        來源 = 資料夾 / "fundamental"
        表們 = [pd.read_csv(來源 / 名, dtype={"code": str}) for 名 in ("revenue_history.csv", "revenue.csv") if (來源 / 名).exists()]
        if not 表們:
            return pd.DataFrame()
        營收 = pd.concat([t[["code", "month", "revenue"]] for t in 表們]).dropna().drop_duplicates(["code", "month"], keep="last")
    p = 營收.pivot_table(index="month", columns="code", values="revenue").sort_index()
    家 = p.notna().sum(axis=1)
    p = p[家 >= 50] if (家 >= 50).any() else p
    if len(p) < 25:
        return pd.DataFrame()
    s3, s12 = p.rolling(3).sum(), p.rolling(12).sum()
    y3 = (s3.iloc[-1] / s3.iloc[-13] - 1) * 100
    y12 = (s12.iloc[-1] / s12.iloc[-13] - 1) * 100
    t = pd.DataFrame({"近3月年增": y3, "近12月年增": y12, "近3月營收": s3.iloc[-1], "去年同期": s3.iloc[-13]}).dropna()
    t = t[(t["近3月營收"] >= 下限千元) & (t["去年同期"] >= 下限千元) & (t["近3月年增"] > 0) & (t["近3月年增"] > t["近12月年增"])]
    t = t.drop(columns="去年同期")
    t["動能差"] = t["近3月年增"] - t["近12月年增"]
    t = t.round(1).sort_values("動能差", ascending=False).head(筆數)
    t.index.name = "代號"
    t = t.reset_index()
    t["月份"] = p.index[-1]
    if 今日 is not None and len(t):
        d = 今日.drop_duplicates("代號").set_index("代號")
        for 欄 in ("名稱", "收盤", "投信連買", "融資20日增減"):
            if 欄 in d:
                t[欄] = t["代號"].map(d[欄])
        t = t[t["名稱"].notna()] if "名稱" in t else t
    return t.reset_index(drop=True)


def 價位量級提示(影片們, 現價, 天數=14, 今天=None):
    """網紅說的價位（「…元」）跟現價差約 10 倍時，多半是字幕漏了一位數（例如 667 元念成 66 元）。
    現價＝{代號: 收盤}。只看 理由／原文看法 裡的「數字＋元」，倍數 8～12 倍才提示。回傳 DataFrame。"""
    今天 = pd.Timestamp(今天 or pd.Timestamp.now().normalize())
    列們 = []
    for v in 影片們:
        日 = pd.to_datetime(v.get("日期"), errors="coerce")
        if pd.isna(日) or (今天 - 日).days > 天數:
            continue
        for x in v.get("股票", []):
            價 = 現價.get(str(x.get("代號") or ""))
            if not 價 or 價 <= 0:
                continue
            文 = f"{x.get('理由') or ''} {x.get('原文看法') or ''}"
            for m in re.findall(r"(\d+(?:\.\d+)?)\s*元", 文):
                n = float(m)
                if n > 0 and 8 <= 價 / n <= 12:
                    列們.append({"影片日": 日, "頻道": v.get("頻道", ""), "股票": f"{x.get('代號')} {x.get('名稱', '')}".strip(),
                               "影片說": f"{m} 元", "現價": 價, "倍數": round(價 / n, 1)})
    return pd.DataFrame(列們).drop_duplicates() if 列們 else pd.DataFrame()


def 代號名稱核對(影片們, 名稱表, 天數=14, 今天=None):
    """說法裡的「代號」和「名稱」對不上時提示（Gemini 常把同音股名配到別檔的代號，例如光罩 2338 寫成旺玖 6233）。
    名稱表＝{代號: 名稱}。名稱互相包含、或念起來像（同音分數 ≥ 0.5）算對得上。
    「可能是」：先找名稱完全一樣的另一個代號，再找念起來最像的。回傳 DataFrame。"""
    今天 = pd.Timestamp(今天 or pd.Timestamp.now().normalize())
    反查 = {}
    for c, n in 名稱表.items():
        反查.setdefault(re.sub(r"[*＊\s]|-?KY", "", str(n)), c)
    列們 = []
    for v in 影片們:
        日 = pd.to_datetime(v.get("日期"), errors="coerce")
        if pd.isna(日) or (今天 - 日).days > 天數:
            continue
        for x in v.get("股票", []):
            代 = str(x.get("代號") or "")
            說 = re.sub(r"[（(].*", "", str(x.get("名稱") or "")).strip()
            實 = 名稱表.get(代)
            if not 說 or not 實 or not 代.isdigit():
                continue
            a, b = re.sub(r"[*＊\s]|-?KY", "", 說), re.sub(r"[*＊\s]|-?KY", "", str(實))
            if not a or not b or a in b or b in a or 同音分數(a, b) >= 0.5:
                continue
            可能 = 反查.get(a, "")
            if not 可能:
                最佳 = max(((同音分數(a, re.sub(r"[*＊\s]|-?KY", "", str(n))), c) for c, n in 名稱表.items()), default=(0, ""))
                可能 = 最佳[1] if 最佳[0] >= 0.7 else ""
            列們.append({"影片日": 日, "頻道": v.get("頻道", ""), "說法裡的": f"{代} {說}", "代號實際是": f"{代} {實}",
                       "名稱可能是": f"{可能} {名稱表.get(可能, '')}".strip() if 可能 else ""})
    return pd.DataFrame(列們).drop_duplicates() if 列們 else pd.DataFrame()
