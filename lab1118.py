"""2026-11-18 網紅摘要的網站補強（純函式，不依賴 streamlit）：
1 國安基金跟買標的追蹤、3 投信連賣＋散戶持股上升、4 權值股跌破 20 週線、5 底高訊號（含回測）、6 風險標記。
（2 EPS 上修但本益比下調：engine.目標價拆解 已有「獲利上修但降倍數」。）"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

資料夾 = Path(__file__).parent / "data"
護盤標的 = {"2330": "台積電", "2308": "台達電", "2382": "廣達", "2317": "鴻海", "2454": "聯發科"}


def 是個股(代號):
    """4 位數字代號才算個股（排除 ETF、權證、反向型 ETF）。"""
    return len(str(代號)) == 4 and str(代號).isdigit() and not str(代號).startswith("0")


# ---------- 1 國安基金跟買標的追蹤 ----------
def 護盤跟買(價, 加權收盤, 紀錄, 天數=(20, 60, 120)):
    """價：index＝日期、欄＝代號的收盤價；加權收盤：Series；紀錄：data/stabilization_fund.csv。
    每次護盤（決議日有完整日期且在資料期間內）從決議日收盤算起，各標的 N 日報酬與同期大盤；
    尚未退場的那次另加「至今」一列。"""
    列 = []
    價 = 價.sort_index()
    大 = 加權收盤.reindex(價.index).ffill()
    for _, r in 紀錄.iterrows():
        日 = pd.to_datetime(r["決議日"], format="%Y-%m-%d", errors="coerce")
        if pd.isna(日) or 日 < 價.index[0]:
            continue
        前 = 價.index[價.index <= 日]
        if not len(前):
            continue
        i = 價.index.get_loc(前[-1])
        已 = len(價) - 1 - i
        未退場 = not str(r.get("退場日") or "").strip()
        期間 = [(n, f"{n} 日") for n in 天數 if i + n < len(價)]
        if 未退場 and 已 > 0:
            期間.append((已, f"至今 {已} 日"))
        for n, 名稱 in 期間:
            j = i + n
            x = {"次": r["次"], "決議日": r["決議日"], "期間": 名稱, "大盤%": round((大.iloc[j] / 大.iloc[i] - 1) * 100, 1)}
            for c, 名 in 護盤標的.items():
                if c in 價.columns and pd.notna(價[c].iloc[i]) and pd.notna(價[c].iloc[j]):
                    x[f"{c} {名}%"] = round((價[c].iloc[j] / 價[c].iloc[i] - 1) * 100, 1)
            列.append(x)
    return pd.DataFrame(列)


def 護盤跟買勝率(表):
    """各標的在已完成期間（20、60、120 日）報酬為正的比例，以及贏過大盤的比例。"""
    if 表.empty:
        return pd.DataFrame()
    完 = 表[~表["期間"].str.startswith("至今")]
    列 = []
    for c in [c for c in 表.columns if c.endswith("%") and c != "大盤%"]:
        s = 完[c].dropna()
        if len(s):
            列.append({"標的": c[:-1], "樣本": len(s), "上漲比例%": round((s > 0).mean() * 100),
                     "贏大盤比例%": round((s > 完.loc[s.index, "大盤%"]).mean() * 100)})
    return pd.DataFrame(列)


# ---------- 3 投信連賣＋散戶持股上升 ----------
def 連賣天數(序列):
    n = 0
    for v in reversed(list(序列)):
        if pd.notna(v) and v < 0:
            n += 1
        else:
            break
    return n


def 投信連賣散戶升(指標, 集保, 連賣下限=10, 散戶升下限=0.0):
    """投信連賣 ≥ 連賣下限 天，且 50 張以下散戶持股比例比 4 週前高（> 散戶升下限 個百分點）。
    集保：DataFrame(code, date, retail)，每週一筆。"""
    d = 指標[指標["代號"].map(是個股)].sort_values("date")
    今 = d[d["date"] == d["date"].max()]
    列 = []
    for 代號, g in d.groupby("代號"):
        n = 連賣天數(g["投信買超"].tail(40))
        if n >= 連賣下限:
            列.append((代號, n, float(g["投信買超"].tail(n).sum())))
    if not 列 or 集保.empty:
        return pd.DataFrame()
    表 = pd.DataFrame(列, columns=["代號", "投信連賣天", "投信累計賣超張"])
    集 = 集保.sort_values("date")
    新 = 集.groupby("code")["retail"].last()
    前 = 集.groupby("code")["retail"].apply(lambda s: s.iloc[max(-5, -len(s))] if len(s) >= 3 else np.nan)  # 約 4 週前；資料不足就用最早一筆
    表["散戶持股%"] = 表["代號"].map(新)
    表["散戶持股變化(個百分點)"] = (表["代號"].map(新) - 表["代號"].map(前)).round(2)
    表 = 表[表["散戶持股變化(個百分點)"] > 散戶升下限]
    欄 = [c for c in ("代號", "名稱", "收盤", "漲跌幅", "20日漲幅") if c in 今.columns]
    return 表.merge(今[欄], on="代號", how="left").sort_values("投信連賣天", ascending=False).reset_index(drop=True)


def 讀集保近六週():
    """data/tdcc 最近 6 個檔合併成 DataFrame(code, date, retail)。"""
    表們 = []
    for f in sorted((資料夾 / "tdcc").glob("*.csv.gz"))[-6:]:
        t = pd.read_csv(f, dtype={"code": str}, usecols=["code", "retail"])
        表們.append(t.assign(date=pd.Timestamp(f.name[:8])))
    return pd.concat(表們, ignore_index=True) if 表們 else pd.DataFrame(columns=["code", "retail", "date"])


# ---------- 4 權值股跌破 20 週線 ----------
def 跌破20週線(指標, 檔數=150):
    """成交值前 檔數 名（20 日平均）的股票，週收盤（每週最後一個交易日）低於 20 週均線。
    狀態：本週剛跌破（上週還在線上）／已在線下。附外資 5 日買賣超（張）。"""
    d = 指標[指標["代號"].map(是個股)].sort_values("date")
    量 = d.groupby("代號")["value"].apply(lambda s: s.tail(20).mean()).nlargest(檔數).index
    小 = d[d["代號"].isin(量)]
    週 = 小.pivot(index="date", columns="代號", values="收盤").resample("W-FRI").last().dropna(how="all")
    if len(週) < 22:
        return pd.DataFrame()
    線 = 週.rolling(20).mean()
    今, 昨, 線今, 線昨 = 週.iloc[-1], 週.iloc[-2], 線.iloc[-1], 線.iloc[-2]
    破 = (今 < 線今) & 今.notna() & 線今.notna()
    外 = 小.groupby("代號")["外資買超"].apply(lambda s: s.tail(5).sum())
    名 = 小.drop_duplicates("代號", keep="last").set_index("代號")["名稱"] if "名稱" in 小.columns else pd.Series(dtype=str)
    列 = [{"代號": c, "名稱": 名.get(c, ""), "收盤": float(今[c]), "20週線": round(float(線今[c]), 2),
          "距20週線%": round((今[c] / 線今[c] - 1) * 100, 1),
          "狀態": "本週剛跌破" if 昨[c] >= 線昨[c] else "已在線下",
          "外資5日買賣超(張)": float(外.get(c, np.nan))} for c in 破[破].index]
    表 = pd.DataFrame(列)
    return 表.sort_values(["狀態", "距20週線%"], ascending=[False, True]).reset_index(drop=True) if len(表) else 表


# ---------- 5 底高訊號 ----------
def 底高訊號日(低, 收, 窗=3, 回看=60, 大跌=0.15):
    """低、收：同一檔的 Series（index＝日期）。傳回 [確認日]：
    波段低點（左右各 窗 天最低）比前一個波段低點高、兩者相隔 ≤ 回看 天，
    且前一個低點比之前 120 日高點低 大跌 以上；確認日＝波段低點後第 窗 天。"""
    n = len(低)
    if n < 130:
        return []
    v = 低.values
    最小 = 低.rolling(2 * 窗 + 1, center=True).min().values
    高120 = 收.rolling(120, min_periods=60).max().values
    日們, 前 = [], None
    for i in range(窗, n - 窗):
        if v[i] != 最小[i]:
            continue
        if 前 is not None and i - 前 <= 回看 and v[i] > v[前] and v[前] <= 高120[前] * (1 - 大跌):
            日們.append(低.index[i + 窗])
        前 = i
    return 日們


def 底高回測(收寬, 低寬, 大盤, 持有=(20, 60)):
    """收寬、低寬：index＝日期、欄＝代號。回傳每個持有天數的平均報酬、平均超額（扣大盤）、勝率、樣本，
    以及全部股票全部日子的基準超額。"""
    大盤 = 大盤.reindex(收寬.index).ffill()
    事件 = []
    for c in 收寬.columns:
        s = 收寬[c].dropna()
        if not 是個股(c) or len(s) < 200 or s.iloc[-60:].mean() < 5:
            continue
        for 日 in 底高訊號日(低寬[c].reindex(s.index), s):
            事件.append((c, 日))
    結果 = {"事件數": len(事件)}
    for h in 持有:
        報, 超 = [], []
        for c, 日 in 事件:
            s = 收寬[c].dropna()
            i = s.index.get_loc(日)
            if i + h < len(s):
                r = s.iloc[i + h] / s.iloc[i] - 1
                報.append(r)
                超.append(r - (大盤.loc[s.index[i + h]] / 大盤.loc[日] - 1))
        全 = (收寬.shift(-h) / 收寬 - 1)
        基 = (全.sub((大盤.shift(-h) / 大盤 - 1), axis=0)).stack().mean()
        結果[f"{h}日"] = {"樣本": len(報), "平均報酬%": round(float(np.mean(報)) * 100, 2) if 報 else None,
                        "平均超額%": round(float(np.mean(超)) * 100, 2) if 超 else None,
                        "勝率%": round(float(np.mean(np.array(報) > 0)) * 100, 1) if 報 else None,
                        "全部日子平均超額%": round(float(基) * 100, 2)}
    return 結果


def 今日底高(指標, 近幾天=5):
    """近 近幾天 個交易日剛確認底高的股票（只看 20 日均成交值 3 千萬以上）。"""
    d = 指標[指標["代號"].map(是個股)].sort_values("date")
    起 = d["date"].drop_duplicates().sort_values().iloc[-近幾天]
    量 = d.groupby("代號")["value"].apply(lambda s: s.tail(20).mean())
    列 = []
    for c, g in d[d["代號"].isin(量[量 > 3e7].index)].groupby("代號"):
        g = g.set_index("date")
        for 日 in 底高訊號日(g["low"], g["收盤"]):
            if 日 >= 起:
                列.append({"代號": c, "名稱": g["名稱"].iloc[-1] if "名稱" in g else "", "確認日": 日.date(),
                         "收盤": float(g["收盤"].iloc[-1])})
    return pd.DataFrame(列).sort_values("確認日", ascending=False).reset_index(drop=True) if 列 else pd.DataFrame()


def 讀底高回測():
    f = 資料夾 / "dibao_backtest.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


# ---------- 6 風險標記 ----------
def 讀風險標記():
    """data/risk_notes.csv（code, 風險, 依據, 更新日），手動維護。"""
    f = 資料夾 / "risk_notes.csv"
    if not f.exists():
        return pd.DataFrame(columns=["code", "風險", "依據", "更新日"])
    return pd.read_csv(f, dtype=str).fillna("")


def 風險標記文字(代號, 表=None):
    表 = 讀風險標記() if 表 is None else 表
    return [f"⚠️ {r['風險']}：{r['依據']}（{r['更新日']}）" for _, r in 表[表["code"] == str(代號)].iterrows()]
