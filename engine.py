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
    "20日漲幅 高→低": ("20日漲幅", False),
    "成交值 大→小": ("成交值億", False),
    "量比 高→低": ("量比", False),
}


# ---------- 1. 讀資料 ----------
def 讀取資料庫():
    檔案們 = sorted((資料夾 / "prices").glob("**/*.csv.gz"))
    if not 檔案們:
        return None
    表 = pd.concat([pd.read_csv(f, dtype={"code": str}) for f in 檔案們], ignore_index=True)
    表 = 表.drop_duplicates(["date", "code"], keep="last")
    表["date"] = pd.to_datetime(表["date"])
    return 表.sort_values(["code", "date"]).reset_index(drop=True)


def 讀取加權指數():
    檔案 = 資料夾 / "index.csv"
    if not 檔案.exists():
        return None
    表 = pd.read_csv(檔案, parse_dates=["date"])
    return 表.sort_values("date")


# ---------- 2. 技術指標 ----------
def 計算指標(原始):
    表 = 原始.rename(columns={
        "name": "名稱", "close": "收盤", "change": "漲跌", "pe": "本益比",
        "dy": "殖利率", "pb": "淨值比",
    }).copy()
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
    表["還原價"] = 群["日報酬"].transform(lambda r: (1 + r).cumprod())

    群 = 表.groupby("code", sort=False)
    for 天數 in (5, 20, 60):
        表[f"MA{天數}"] = 群["還原價"].transform(lambda s, n=天數: s.rolling(n).mean())
    表["20日漲幅"] = (群["還原價"].transform(lambda s: s / s.shift(20) - 1) * 100).round(2)
    表["成交張數"] = (表["volume"] / 1000).round()
    表["成交值億"] = (表["value"] / 1e8).round(2)
    表["量比"] = (表["volume"] / 群["volume"].transform(lambda s: s.rolling(20).mean())).round(2)
    表["距52週高點"] = ((表["還原價"] / 群["還原價"].transform(lambda s: s.rolling(240, min_periods=20).max()) - 1) * 100).round(1)

    漲 = 表["日報酬"].clip(lower=0)
    跌 = (-表["日報酬"]).clip(lower=0)
    平均漲 = 漲.groupby(表["code"]).transform(lambda s: s.ewm(alpha=1 / 14, adjust=False).mean())
    平均跌 = 跌.groupby(表["code"]).transform(lambda s: s.ewm(alpha=1 / 14, adjust=False).mean())
    表["RSI"] = (100 - 100 / (1 + 平均漲 / 平均跌.replace(0, np.nan))).round(1)

    表["漲跌幅"] = (表["日報酬"] * 100).round(2)
    return 表


# ---------- 3. 選股 ----------
def 選股(當日, 條件):
    """當日：某一天所有股票的指標；條件：dict，空白(None)代表不設限。"""
    c = 條件
    結果 = 當日[當日["收盤"] > 0]
    if c.get("本益比上限") is not None:
        結果 = 結果[(結果["本益比"] > 0) & (結果["本益比"] <= c["本益比上限"])]
    if c.get("殖利率下限") is not None:
        結果 = 結果[結果["殖利率"] >= c["殖利率下限"]]
    if c.get("淨值比上限") is not None:
        結果 = 結果[(結果["淨值比"] > 0) & (結果["淨值比"] <= c["淨值比上限"])]
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
    if c.get("排除ETF", True):
        結果 = 結果[~結果["代號"].str.startswith("00")]
    欄, 由小到大 = 排序方式[c.get("排序", "殖利率 高→低")]
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


def 排行資料(上市今日, 上櫃最新=None):
    """合併上市與同一天的上櫃股票（不含 ETF），給排行榜用。"""
    表 = 上市今日.rename(columns={"名稱": "name", "收盤": "close", "漲跌": "change"})
    表 = 表[["date", "code", "name", "close", "change", "volume", "value"]].assign(市場="上市")
    if 上櫃最新 is not None and 上櫃最新["date"].max() == 表["date"].max():
        表 = pd.concat([表, 上櫃最新[表.columns.drop("市場")].assign(市場="上櫃")])
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


def 計算庫存(持股, 上市最新, 上櫃最新=None):
    """持股：DataFrame（代號、股數、總成本）。回傳每檔明細與合計。"""
    上市最新 = 上市最新.rename(columns={"名稱": "name", "收盤": "close", "漲跌": "change"})
    報價 = 上市最新[["code", "name", "date", "close", "change"]]
    if 上櫃最新 is not None:
        報價 = pd.concat([報價, 上櫃最新[["code", "name", "date", "close", "change"]]])
    報價 = 報價.sort_values("date").drop_duplicates("code", keep="last").set_index("code")

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
