"""2026-11-23 網紅摘要建議 N1～N6：流動性恢復燈、鎖死跌停、超跌洗盤積分、護盤跌深榜、循環股本淨比、標普條件價位。
都是純函式（輸入 DataFrame、輸出 DataFrame／dict），方便測試；畫面在 views/p01_market.py 的「氣氛」區塊。"""
import numpy as np
import pandas as pd

import engine

ABF名單 = {"3037": "欣興", "8046": "南電", "3189": "景碩"}
循環股 = {"2408": "南亞科", "2344": "華邦電", "2337": "旺宏", "8299": "群聯", "2603": "長榮", "2609": "陽明", "2615": "萬海", "2409": "友達", "3481": "群創"}
標普門檻 = 6845.0  # 彭博／BofA：標普 500 跌破此價＝Fed 最在意的門檻之一（網紅 11/23 引述，2026 年數字）


def _股票(表):
    """只留 4 碼普通股。"""
    return 表[表["code"].astype(str).str.fullmatch(r"\d{4}")]


def 逐日漲跌(價):
    """價：date, code, open, high, low, close。回傳加上 昨收、漲跌%、跌停價、漲停價、收跌停、全日鎖死跌停、收漲停 的表。"""
    d = _股票(價).sort_values(["code", "date"]).copy()
    d["昨收"] = d.groupby("code")["close"].shift(1)
    d = d[d["昨收"].notna()]
    d["漲跌%"] = (d["close"] / d["昨收"] - 1) * 100
    限 = d["昨收"].map(engine.漲跌停價)
    d["漲停價"] = 限.map(lambda x: x[0])
    d["跌停價"] = 限.map(lambda x: x[1])
    d["收跌停"] = (d["close"] <= d["跌停價"] + 1e-6)
    d["全日鎖死"] = d["收跌停"] & (d["high"] <= d["跌停價"] + 1e-6)
    d["收漲停"] = (d["close"] >= d["漲停價"] - 1e-6)
    return d


def 鎖死跌停表(價, 天數=10):
    """N2：每日 收盤跌停家數、全日鎖死（開盤到收盤都沒打開）家數、漲停家數，上市／上櫃合計。"""
    d = 逐日漲跌(價)
    if d.empty:
        return pd.DataFrame()
    g = d.groupby("date").agg(收跌停=("收跌停", "sum"), 全日鎖死=("全日鎖死", "sum"), 收漲停=("收漲停", "sum"), 上漲=("漲跌%", lambda s: int((s > 0).sum())),
                              下跌=("漲跌%", lambda s: int((s < 0).sum()))).reset_index()
    return g.tail(天數).sort_values("date", ascending=False).reset_index(drop=True)


def 連續鎖死(價, 最少=2):
    """連續 N 天（含最新日）收盤都在跌停的股票。"""
    d = 逐日漲跌(價)
    if d.empty:
        return pd.DataFrame()
    最新 = d["date"].max()
    列 = []
    for 代號, g in d.groupby("code"):
        g = g.sort_values("date")
        if g.iloc[-1]["date"] != 最新:
            continue
        n = 0
        for v in g["收跌停"].values[::-1]:
            if not v:
                break
            n += 1
        if n >= 最少:
            列.append({"代號": 代號, "名稱": g.iloc[-1].get("name", ""), "連續跌停天數": n, "收盤": g.iloc[-1]["close"]})
    return pd.DataFrame(列).sort_values("連續跌停天數", ascending=False).reset_index(drop=True) if 列 else pd.DataFrame()


def 流動性四燈(價, 日=None):
    """N1：通勤族的氣氛指標（只用行情，不用新聞）。回傳 [(燈, 項目, 說明)]。
    ① ABF 載板（欣興、南電、景碩）有沒有「盤中打到跌停、收盤打開」或跌幅縮到 5% 內；
    ② 漲停家數 ≥ 跌停家數；③ 本益比低於 15 的股票漲跌中位數高於全部股票的中位數；④ 成交金額不比 5 日均量少 20% 以上。"""
    d = 逐日漲跌(價)
    if d.empty:
        return []
    日 = 日 or d["date"].max()
    今 = d[d["date"] == 日]
    結果 = []
    a = 今[今["code"].isin(ABF名單)]
    if len(a):
        打開 = a[(a["low"] <= a["跌停價"] + 1e-6) & (a["close"] > a["跌停價"] * 1.02)]
        收小 = a[a["漲跌%"] > -5]
        字 = "、".join(f"{r['code']}{ABF名單[r['code']]} {r['漲跌%']:+.1f}%" for _, r in a.iterrows())
        成 = len(打開) > 0 or len(收小) == len(a)
        結果.append(("🟢" if 成 else "🔴", "ABF 載板跌停打開／跌幅收斂", 字 + ("（有檔盤中跌停後打開）" if len(打開) else "")))
    漲, 跌 = int(今["收漲停"].sum()), int(今["收跌停"].sum())
    結果.append(("🟢" if 漲 >= 跌 else "🔴", "漲停家數 ≥ 跌停家數", f"漲停 {漲} 家、跌停 {跌} 家"))
    if "pe" in 價.columns:
        低 = 價[(價["date"] == 日) & (價["pe"] > 0) & (價["pe"] < 15)]
        低 = 今[今["code"].isin(低["code"])]
        if len(低) > 20:
            m1, m2 = 低["漲跌%"].median(), 今["漲跌%"].median()
            結果.append(("🟢" if m1 >= m2 else "🔴", "低本益比股比大家強", f"本益比<15 的 {len(低)} 檔中位數 {m1:+.2f}%、全部 {m2:+.2f}%"))
    if "value" in 價.columns:
        每日 = _股票(價).groupby("date")["value"].sum().sort_index()
        if len(每日) >= 6 and 日 in 每日.index:
            均 = 每日.loc[:日].iloc[-6:-1].mean()
            比 = 每日.loc[日] / 均 - 1
            結果.append(("🟢" if 比 >= -0.2 else "🔴", "成交金額沒有萎縮", f"今日是 5 日均量的 {比 * 100 + 100:.0f}%"))
    return 結果


def 護盤跌深榜(價, 檔數=30, 回看=60, 前幾=10):
    """N4：成交值前 N 大的權值股，依「距 60 日高點跌幅」排序，並列今日漲跌、是否漲停。看護盤／反彈時資金先拉誰。"""
    d = _股票(價)
    if d.empty:
        return pd.DataFrame()
    最新 = d["date"].max()
    近 = d[d["date"] > d["date"].drop_duplicates().sort_values().iloc[-21]] if d["date"].nunique() > 21 else d
    大 = 近.groupby("code")["value"].mean().nlargest(檔數).index
    列 = []
    for c in 大:
        g = d[d["code"] == c].sort_values("date").tail(回看)
        if len(g) < 5 or g.iloc[-1]["date"] != 最新:
            continue
        昨, 今 = g.iloc[-2]["close"], g.iloc[-1]["close"]
        上, 下 = engine.漲跌停價(昨)
        列.append({"代號": c, "名稱": g.iloc[-1].get("name", ""), "距60日高%": round((今 / g["high"].max() - 1) * 100, 1),
                 "今日%": round((今 / 昨 - 1) * 100, 2), "漲停": bool(今 >= 上 - 1e-6)})
    return pd.DataFrame(列).sort_values("距60日高%").head(前幾).reset_index(drop=True) if 列 else pd.DataFrame()


def 循環股本淨比(價, 名單=None):
    """N5：循環股改看本淨比位階（資料期間內的百分位，越低越便宜）。價：date, code, pb。"""
    名單 = 名單 or 循環股
    列 = []
    for c, n in 名單.items():
        g = 價[(價["code"] == c) & (價["pb"] > 0)].sort_values("date")
        if len(g) < 120:
            continue
        pb = g["pb"].astype(float)
        列.append({"代號": c, "名稱": n, "本淨比": round(pb.iloc[-1], 2), "位階%": round((pb < pb.iloc[-1]).mean() * 100),
                 "中位數": round(pb.median(), 2), "最低": round(pb.min(), 2), "最高": round(pb.max(), 2),
                 "本益比": round(float(g["pe"].iloc[-1]), 1) if "pe" in g and pd.notna(g["pe"].iloc[-1]) else np.nan})
    return pd.DataFrame(列).sort_values("位階%").reset_index(drop=True) if 列 else pd.DataFrame()


def 標普條件(美, 門檻=標普門檻):
    """N6：標普 500 距離門檻（預設 6,845）的空間；美：engine.讀取美股() 的收盤表（欄位用中文名）。"""
    if 美 is None or "S&P 500" not in 美.columns:
        return None
    s = 美["S&P 500"].dropna()
    if len(s) < 2:
        return None
    收 = float(s.iloc[-1])
    r = {"日期": s.index[-1], "標普收盤": 收, "門檻": 門檻, "距門檻%": (收 / 門檻 - 1) * 100, "破門檻": 收 < 門檻, "單日%": (收 / float(s.iloc[-2]) - 1) * 100}
    高 = [c for c in 美.columns if "HYG" in c]
    if 高:
        h = 美[高[0]].dropna()
        if len(h) >= 21:
            r["HYG"] = float(h.iloc[-1])
            r["HYG距20日均%"] = (float(h.iloc[-1]) / float(h.tail(20).mean()) - 1) * 100
    return r


def 超跌洗盤積分(價, 基本面, 前幾=15, 營收門檻=30.0):
    """N3（簡化版）：累計營收年增 > 門檻的股票，依「距一年高點跌幅（越深分越低＝越前面）」與「近 5 日融資減幅（越多越前面）」排名加總，
    總分越低越前面。原影片第三項是融資維持率（網站沒有個股維持率），改用融資減幅當洗盤深度的替代。"""
    最新 = 價["date"].max()
    d = _股票(價)
    今 = d[d["date"] == 最新][["code", "name", "close"]].set_index("code")
    高 = d[d["date"] > 最新 - pd.Timedelta(days=365)].groupby("code")["high"].max()
    今["距一年高%"] = (今["close"] / 高.reindex(今.index) - 1) * 100
    if "margin" in d.columns:
        前 = d[d["date"] == d["date"].drop_duplicates().sort_values().iloc[-6]].set_index("code")["margin"] if d["date"].nunique() > 6 else None
        後 = d[d["date"] == 最新].set_index("code")["margin"]
        if 前 is not None:
            今["5日融資減%"] = ((後.reindex(今.index) / 前.reindex(今.index) - 1) * 100)
    營 = 基本面["累計營收年增率"] if "累計營收年增率" in 基本面.columns else None
    if 營 is None:
        return pd.DataFrame()
    今["累計營收年增%"] = 營.reindex(今.index)
    今 = 今[今["累計營收年增%"] > 營收門檻].dropna(subset=["距一年高%"])
    今["空間分"] = 今["距一年高%"].rank(method="min")  # 跌最深＝1
    今["洗盤分"] = 今["5日融資減%"].rank(method="min") if "5日融資減%" in 今 else 0  # 融資減最多（負最大）＝1
    今["總分"] = 今["空間分"] + 今["洗盤分"]
    今 = 今.sort_values(["總分", "距一年高%"]).head(前幾).reset_index()
    return 今.rename(columns={"code": "代號", "name": "名稱", "close": "收盤"})[[c for c in ["代號", "名稱", "收盤", "累計營收年增%", "距一年高%", "5日融資減%", "總分"] if c in 今.rename(columns={"code": "代號", "name": "名稱", "close": "收盤"}).columns]]
