# 計算核心：讀資料庫、算技術指標、選股、回測
# 想調整選股或回測規則，主要改這個檔案

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
}


# ---------- 1. 讀資料 ----------
def _讀每日檔(子資料夾):
    檔案們 = sorted((資料夾 / 子資料夾).glob("**/*.csv.gz"))
    if not 檔案們:
        return None
    表們 = []
    for f in 檔案們:
        t = pd.read_csv(f, dtype={"code": str})
        if "date" not in t.columns:  # 籌碼檔沒有日期欄，從檔名取
            t["date"] = f"{f.name[:4]}-{f.name[4:6]}-{f.name[6:8]}"
        表們.append(t)
    表 = pd.concat(表們, ignore_index=True)
    表["date"] = pd.to_datetime(表["date"])
    return 表.drop_duplicates(["date", "code"], keep="last")


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
    return 表.sort_values(["code", "date"]).reset_index(drop=True)


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
    """最新月營收與最新一季 EPS，回傳以代號為索引的表。"""
    表 = None
    f = 資料夾 / "fundamental" / "revenue.csv"
    if f.exists():
        r = pd.read_csv(f, dtype={"code": str}).drop_duplicates("code", keep="last").set_index("code")
        表 = r.rename(columns={"month": "營收月份", "rev_yoy": "營收年增率", "rev_mom": "營收月增率",
                              "rev_cum_yoy": "累計營收年增率"})[["營收月份", "營收年增率", "營收月增率", "累計營收年增率"]]
    f = 資料夾 / "fundamental" / "eps.csv"
    if f.exists():
        e = pd.read_csv(f, dtype={"code": str}).drop_duplicates("code", keep="last").set_index("code")
        e = e.rename(columns={"quarter": "EPS季度", "eps": "EPS"})[["EPS季度", "EPS"]]
        表 = e if 表 is None else 表.join(e, how="outer")
    return 表


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
    for 天數 in (5, 20, 60):
        表[f"MA{天數}"] = _滾動(群, "還原價", 天數)
    表["20日漲幅"] = ((表["還原價"] / 群["還原價"].shift(20) - 1) * 100).round(2)
    表["成交張數"] = (表["volume"] / 1000).round()
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
    if c.get("排除ETF", True):
        結果 = 結果[~結果["代號"].str.startswith("00")]
    欄, 由小到大 = 排序方式[c.get("排序", "殖利率 高→低")]
    if 欄 not in 結果.columns:
        return 結果
    return 結果.sort_values(欄, ascending=由小到大, na_position="last")


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


def 排行資料(今日):
    """今日所有上市櫃股票（不含 ETF），給排行榜用。"""
    表 = 今日.rename(columns={"名稱": "name", "收盤": "close", "漲跌": "change"})
    表 = 表[~表["code"].str.startswith("00") & (表["close"] > 0)].copy()
    表["幅度"] = 表["change"] / (表["close"] - 表["change"]) * 100
    表["張數"] = 表["volume"] / 1000
    return 表


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
    else:  # RSI 超賣反彈：低於下限進場，高於上限出場，中間維持原狀
        狀態, 序列 = False, []
        for v in 表["RSI"]:
            if pd.notna(v) and v < RSI下限:
                狀態 = True
            elif pd.notna(v) and v > RSI上限:
                狀態 = False
            序列.append(狀態)
        想持有 = pd.Series(序列, index=表.index)

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
