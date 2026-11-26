"""2026-11-26 網紅摘要建議的純計算函式（不碰 streamlit，方便測試）。
外資止賣補燈、ETF 暴漲暴跌預警、前低守住分類、大反彈日回測。"""
import numpy as np
import pandas as pd


def 外資現貨估算(指標):
    """每天外資買賣超估算（億元）＝ Σ 外資張數(股) × 收盤 ÷ 1e8；含 ETF，誤差約 5%。回傳 Series（index＝date）。"""
    d = 指標[["date", "foreign", "收盤"]].dropna()
    return (d["foreign"] * d["收盤"]).groupby(d["date"]).sum().sort_index() / 1e8


def 止賣補燈(外資估, 美債10年=None, 天數=2):
    """宏爺『外資止賣三部曲』網站原本只有台幣、期貨兩燈；這裡補『外資現貨轉買超』『美債殖利率止升』。
    網站沒有 2 年期殖利率，改用 10 年期（^TNX）代替，燈上會寫明。回傳 [(名, 燈, 說)]。"""
    燈們 = []
    if 外資估 is not None and len(外資估) >= 天數:
        s = 外資估.dropna()
        連賣 = 0
        for v in s.values[::-1]:
            if v < 0:
                連賣 += 1
            else:
                break
        亮 = bool((s.tail(天數) > 0).all())
        燈們.append(("④ 外資現貨轉買超", "🟢" if 亮 else "🔴",
                     f"外資估算買賣超最新 {s.iloc[-1]:+,.0f} 億" + (f"，已連賣 {連賣} 天" if 連賣 else "")
                     + ("：連續買超" if 亮 else f"：要連 {天數} 天買超才亮（用個股張數×收盤估算，誤差約 5%）")))
    else:
        燈們.append(("④ 外資現貨轉買超", "🟡", "沒有外資資料"))
    if 美債10年 is not None and len(美債10年) > 天數:
        s = 美債10年.astype(float).dropna()
        差 = s.diff().tail(天數)
        亮 = bool((差 <= 0).all())
        燈們.append(("⑤ 美債殖利率止升", "🟢" if 亮 else "🔴",
                     f"美債 10 年期 {s.iloc[-1]:.2f}%，近 {天數} 天變化 " + "、".join(f"{v:+.2f}" for v in 差)
                     + "（影片說的是 2 年期，網站沒有，用 10 年期代替）"))
    else:
        燈們.append(("⑤ 美債殖利率止升", "🟡", "沒有美債資料"))
    return 燈們


def ETF單日異動(指標, 門檻=8.0, 天數=5):
    """代號 00 開頭的 ETF，最近 天數 個交易日內單日漲跌幅超過 ±門檻%。沒有淨值資料，只標單日振幅，
    折溢價另看主動式 ETF 區。回傳 DataFrame（日期、代號、名稱、收盤、單日%、次日%）。"""
    d = 指標[指標["代號"].astype(str).str.startswith("00")][["date", "代號", "名稱", "收盤"]].sort_values(["代號", "date"]).copy()
    d["單日%"] = d.groupby("代號")["收盤"].pct_change() * 100
    d["次日%"] = d.groupby("代號")["單日%"].shift(-1)
    日們 = sorted(d["date"].unique())[-天數:]
    r = d[d["date"].isin(日們) & (d["單日%"].abs() >= 門檻)]
    return r.sort_values("單日%", key=lambda s: -s.abs()).rename(columns={"date": "日期"}).reset_index(drop=True)


def 前低守住表(指標, 基準日, 最低成交值億=1.0):
    """以 基準日 當天的最低價為『前低』。之後有沒有跌破？現在收在前低上還是下？
    狀態：沒破（之後最低價都≥前低）／破後收復（破過但現在收盤≥前低）／仍在前低下。只看 4 碼股票、基準日成交值≥最低成交值億。"""
    基準日 = pd.Timestamp(基準日)
    d = 指標[指標["代號"].astype(str).str.fullmatch(r"\d{4}")]
    起 = d[d["date"] == 基準日].set_index("代號")
    if 起.empty:
        return pd.DataFrame()
    後 = d[d["date"] > 基準日]
    if 後.empty:
        return pd.DataFrame()
    最低 = 後.groupby("代號")["low"].min()
    最新 = 後.sort_values("date").groupby("代號").tail(1).set_index("代號")
    r = pd.DataFrame({"名稱": 最新["名稱"], "前低": 起["low"], "之後最低": 最低, "現價": 最新["收盤"]}).dropna()
    r = r[起["成交值億"].reindex(r.index) >= 最低成交值億]
    r["狀態"] = np.where(r["之後最低"] >= r["前低"], "沒破", np.where(r["現價"] >= r["前低"], "破後收復", "仍在前低下"))
    r["距前低%"] = (r["現價"] / r["前低"] - 1) * 100
    r["最深破低%"] = (r["之後最低"] / r["前低"] - 1) * 100
    return r.reset_index().rename(columns={"index": "代號"}).sort_values("距前低%", ascending=False).reset_index(drop=True)


def 大反彈日回測(K, 漲幅=2.5, 前跌=2.5, 回看=10, 後=(1, 5, 20)):
    """加權『極端大跌後的大反彈日』：當日漲 ≥ 漲幅%，而且過去 回看 日內曾單日跌 ≥ 前跌%。
    統計之後 後 日的報酬，對照所有日子的平均。K：date、close。回傳 dict(事件表, 統計, 基準)。"""
    k = K[["date", "close"]].dropna().sort_values("date").reset_index(drop=True)
    r = k["close"].pct_change() * 100
    近大跌 = r.shift(1).rolling(回看, min_periods=1).min() <= -前跌
    亮 = (r >= 漲幅) & 近大跌
    行 = []
    for i in np.where(亮)[0]:
        e = {"日期": k["date"].iloc[i], "當日%": round(r.iloc[i], 2)}
        for n in 後:
            e[f"{n}日%"] = round((k["close"].iloc[i + n] / k["close"].iloc[i] - 1) * 100, 2) if i + n < len(k) else np.nan
        行.append(e)
    表 = pd.DataFrame(行)
    統, 基 = [], {}
    for n in 後:
        fwd = (k["close"].shift(-n) / k["close"] - 1) * 100
        基[n] = round(float(fwd.mean()), 2)
        if len(表) and f"{n}日%" in 表:
            v = 表[f"{n}日%"].dropna()
            統.append({"天數": n, "次數": len(v), "平均%": round(float(v.mean()), 2) if len(v) else np.nan,
                     "上漲機率%": round(float((v > 0).mean() * 100), 0) if len(v) else np.nan, "基準平均%": 基[n]})
    return {"事件表": 表, "統計": 統, "基準": 基}


def 漲停隔日(指標, 日, 漲停門檻=9.5, 後=(1, 5)):
    """某一天漲停的股票，之後 後 日平均報酬 vs 同日全市場（4 碼股票）平均；日期太新沒有後續就回傳 None。"""
    d = 指標[指標["代號"].astype(str).str.fullmatch(r"\d{4}")].pivot(index="date", columns="代號", values="還原價").sort_index()
    日 = pd.Timestamp(日)
    if 日 not in d.index:
        return None
    i = d.index.get_loc(日)
    當 = (d.iloc[i] / d.iloc[i - 1] - 1) * 100
    停 = 當[當 >= 漲停門檻].index
    if len(停) < 5:
        return None
    out = {"漲停家數": int(len(停))}
    for n in 後:
        if i + n >= len(d):
            continue
        fw = (d.iloc[i + n] / d.iloc[i] - 1) * 100
        out[n] = (round(float(fw[停].mean()), 2), round(float(fw.mean()), 2))
    return out
