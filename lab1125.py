"""2026-11-25 網紅摘要建議的三個回測（跑一次存 data/lab1125_backtest.json，網站讀這個檔）。
 ① 跌深（距月線 ≥20%）反彈到月線：會不會到、多久、碰到之後 5 日怎麼走
 ② 歷次急殺低點後 20 日勝大盤的「反彈基因」：每檔勝幾次、平均超額；用前面幾次選、最後一次驗證
 ③ 低檔「價弱籌碼強」：年線負乖離 ≥15%、近 5 日外資＋投信合計買超、股價沒漲，之後 20 日對大盤超額
用法：python lab1125.py"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import engine  # noqa: E402


def 載入():
    d = engine.讀取資料庫()
    d = d[d["code"].astype(str).str.fullmatch(r"\d{4}") & d["market"].isin(["上市", "上櫃"])].copy()
    d = d.sort_values(["code", "date"]).reset_index(drop=True)
    return d


def 加權長線():
    """2000 年起加權收盤：index_long（到 2021-08）接 index_ohlc（2021-11 起）。"""
    a = pd.read_csv(engine.資料夾 / "index_long.csv", parse_dates=["date"])
    b = pd.read_csv(engine.資料夾 / "index_ohlc.csv", parse_dates=["date"])
    b = b[b["symbol"] == "TAIEX"][["date", "close"]]
    x = pd.concat([a[a["date"] < b["date"].min()], b]).drop_duplicates("date").sort_values("date")
    return x.set_index("date")["close"]


def 大盤():
    return 加權長線()


def 加指標(d):
    g = d.groupby("code", sort=False)["close"]
    d["ma20"] = g.transform(lambda s: s.rolling(20).mean())
    d["ma240"] = g.transform(lambda s: s.rolling(240, min_periods=200).mean())
    d["成交值億"] = d["value"] / 1e8
    return d


def 月線反彈(d):
    d = d.copy()
    d["距月線%"] = (d["ma20"] / d["close"] - 1) * 100
    事件 = []
    for c, g in d.groupby("code", sort=False):
        g = g.reset_index(drop=True)
        條 = ((g["距月線%"] >= 20) & (g["成交值億"] >= 1)).to_numpy()
        收, m20, 日 = g["close"].to_numpy(), g["ma20"].to_numpy(), g["date"].to_numpy()
        i, n = 0, len(g)
        while i < n - 21:
            if 條[i]:
                目標 = m20[i]
                後 = 收[i + 1:i + 21]
                碰 = np.where(後 >= 目標)[0]
                r = {"天": int(碰[0]) + 1 if len(碰) else None, "20日%": (收[i + 20] / 收[i] - 1) * 100}
                if len(碰) and i + 碰[0] + 6 < n:
                    k = i + 碰[0] + 1
                    r["碰後5日%"] = (收[k + 5] / 收[k] - 1) * 100
                事件.append(r)
                i += 20
            else:
                i += 1
    e = pd.DataFrame(事件)
    if e.empty:
        return {}
    碰 = e["天"].notna()
    return {"事件數": int(len(e)), "5日內碰到%": round(float((e["天"] <= 5).mean() * 100), 1),
            "10日內碰到%": round(float((e["天"] <= 10).mean() * 100), 1), "20日內碰到%": round(float(碰.mean() * 100), 1),
            "碰到的中位天數": float(e.loc[碰, "天"].median()), "20日平均報酬%": round(float(e["20日%"].mean()), 1),
            "20日中位數報酬%": round(float(e["20日%"].median()), 1),
            "碰到月線後5日平均%": round(float(e["碰後5日%"].mean()), 2), "碰到月線後5日上漲比例%": round(float((e["碰後5日%"].dropna() > 0).mean() * 100), 1)}


def 急殺低點(K, 跌=-15, 間隔=40):
    高 = K.rolling(60, min_periods=20).max()
    回 = (K / 高 - 1) * 100
    低點 = []
    在段 = False
    段低 = None
    for dt, v in 回.items():
        if v <= 跌:
            在段 = True
            if 段低 is None or K[dt] < K[段低]:
                段低 = dt
        elif 在段 and v > 跌 / 2:
            低點.append(段低)
            在段, 段低 = False, None
    if 在段 and 段低 is not None:
        低點.append(段低)
    out = []
    for x in 低點:
        if not out or (x - out[-1]).days > 間隔:
            out.append(x)
    return [x for x in out if x >= pd.Timestamp("2021-12-01")]


def 反彈基因(d, K):
    低點們 = 急殺低點(K)
    px = d.pivot(index="date", columns="code", values="close")
    名 = d.drop_duplicates("code", keep="last").set_index("code")["name"]
    量 = d.pivot(index="date", columns="code", values="成交值億").rolling(20).mean().iloc[-1]
    結果, 完整 = {}, []
    for t in 低點們:
        if t not in px.index:
            t = px.index[px.index.get_indexer([t], method="nearest")[0]]
        i = px.index.get_loc(t)
        if i + 20 >= len(px):
            continue
        r = (px.iloc[i + 20] / px.iloc[i] - 1) * 100
        大 = (K.loc[px.index[i + 20]] / K.loc[t] - 1) * 100
        結果[str(t.date())] = r - 大
        完整.append((str(t.date()), float(大)))
    if len(結果) < 3:
        return {}
    超 = pd.DataFrame(結果)
    勝 = (超 > 0).sum(axis=1)
    有 = 超.notna().sum(axis=1)
    平均 = 超.mean(axis=1)
    前 = 超.iloc[:, :-1]
    選 = ((前 > 0).sum(axis=1) == 前.notna().sum(axis=1)) & (前.notna().sum(axis=1) >= len(前.columns) - 0)
    選 = 選 & (量.reindex(超.index) >= 1)
    驗 = 超.iloc[:, -1][選].dropna()
    全 = 超.iloc[:, -1].dropna()
    表 = pd.DataFrame({"名稱": 名.reindex(超.index), "勝大盤次數": 勝, "事件數": 有, "平均超額%": 平均.round(1)})
    表 = 表[(有 == len(超.columns)) & (量.reindex(超.index) >= 1)].sort_values(["勝大盤次數", "平均超額%"], ascending=False).head(20)
    return {"事件": [{"低點日": a, "大盤20日%": round(b, 1)} for a, b in 完整],
            "榜單": [{"代號": c, "名稱": r["名稱"], "勝大盤次數": int(r["勝大盤次數"]), "事件數": int(r["事件數"]), "平均超額%": float(r["平均超額%"])}
                   for c, r in 表.iterrows()],
            "樣本外": {"驗證事件": str(超.columns[-1]), "前幾次全勝大盤的檔數": int(len(驗)),
                    "之後平均超額%": round(float(驗.mean()), 1) if len(驗) else None,
                    "之後勝大盤比例%": round(float((驗 > 0).mean() * 100), 1) if len(驗) else None,
                    "全市場平均超額%": round(float(全.mean()), 1), "全市場勝大盤比例%": round(float((全 > 0).mean() * 100), 1)}}


def 價弱籌碼強(d, K):
    d = d.copy()
    g = d.groupby("code", sort=False)
    d["法人"] = (d["foreign"].fillna(0) + d["trust"].fillna(0))
    d["法人5"] = g["法人"].transform(lambda s: s.rolling(5).sum())
    d["漲5%"] = g["close"].transform(lambda s: s.pct_change(5)) * 100
    d["fwd20"] = g["close"].transform(lambda s: s.shift(-20) / s - 1) * 100
    d["負乖離%"] = (d["close"] / d["ma240"] - 1) * 100
    大 = (K.shift(-20) / K - 1) * 100
    d["大盤fwd"] = d["date"].map(大)
    d["超額"] = d["fwd20"] - d["大盤fwd"]
    基 = d[(d["負乖離%"] <= -15) & (d["成交值億"] >= 1) & d["超額"].notna()]
    條 = 基[(基["法人5"] > 0) & (基["漲5%"] <= 3)]
    弱 = 基[(基["法人5"] <= 0)]

    def 摘(x):
        return {"樣本": int(len(x)), "20日平均超額%": round(float(x["超額"].mean()), 2), "20日中位數超額%": round(float(x["超額"].median()), 2),
                "勝大盤%": round(float((x["超額"] > 0).mean() * 100), 1)}
    今 = d[d["date"] == d["date"].max()]
    今 = 今[(今["負乖離%"] <= -15) & (今["成交值億"] >= 1) & (今["法人5"] > 0) & (今["漲5%"] <= 3)]
    名單 = [{"代號": r["code"], "名稱": r["name"], "收盤": float(r["close"]), "年線負乖離%": round(float(r["負乖離%"]), 1),
           "近5日法人買超張": int(r["法人5"] / 1000)} for _, r in 今.sort_values("法人5", ascending=False).head(15).iterrows()]
    return {"年線負乖離≥15%且成交值≥1億（基準）": 摘(基), "＋近5日外資投信合計買超、股價5日漲幅≤3%": 摘(條), "年線負乖離但法人5日沒買": 摘(弱), "今日符合": 名單}


def main():
    d = 加指標(載入())
    K = 大盤()
    out = {"更新": str(d["date"].max().date()), "跌深反彈到月線": 月線反彈(d), "反彈基因": 反彈基因(d, K), "價弱籌碼強": 價弱籌碼強(d, K)}
    (engine.資料夾 / "lab1125_backtest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])


if __name__ == "__main__":
    main()
