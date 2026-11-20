"""2026-11-20 網紅摘要的網站補強（純函式，不依賴 streamlit）：
1 台指 VIX 分位與回測、3 營業利益四象限＋ODM 存貨銷售比、4 限空令事件追蹤、5 谷底量與領頭羊墊高底部。
（2 電力鏈產業鏈卡＝ data/supply_chain.csv、data/chain_notes.csv 新增「電力鏈」。）"""
import io
import time
from pathlib import Path

import numpy as np
import pandas as pd

資料夾 = Path(__file__).parent / "data"
ODM = {"2317": "鴻海", "2382": "廣達", "3231": "緯創"}


# ---------- 1 台指 VIX ----------
def 抓台指VIX(起=None, 迄=None):
    """期交所「臺指選擇權波動率指數」→ data/tw_vix.csv（date, close）。期交所擋雲端 IP 時會失敗，失敗不影響其他資料。"""
    import requests
    檔 = 資料夾 / "tw_vix.csv"
    舊 = pd.read_csv(檔, dtype={"date": str}) if 檔.exists() else pd.DataFrame(columns=["date", "close"])
    迄 = pd.Timestamp(迄 or pd.Timestamp.today().normalize())
    起 = pd.Timestamp(起) if 起 is not None else (pd.Timestamp(舊["date"].max()) + pd.Timedelta(days=1) if len(舊) else pd.Timestamp("2021-11-01"))
    列們 = []
    while 起 <= 迄:
        段迄 = min(起 + pd.Timedelta(days=89), 迄)
        t = None
        for 第幾次 in range(3):
            time.sleep(3 + 6 * 第幾次)
            try:
                r = requests.post("https://www.taifex.com.tw/cht/7/vixDataDown", timeout=60,
                                  headers={"User-Agent": "Mozilla/5.0"},
                                  data={"queryStartDate": f"{起:%Y/%m/%d}", "queryEndDate": f"{段迄:%Y/%m/%d}"})
                r.encoding = "big5"
                t = 解析台指VIX(r.text)
                if t is not None:
                    break
                print(f"台指VIX {起:%Y-%m-%d}～{段迄:%Y-%m-%d} 回傳不是資料：{r.text[:100]!r}")
            except Exception as 錯誤:
                print(f"台指VIX {起:%Y-%m-%d}～{段迄:%Y-%m-%d} 失敗：{錯誤}")
        if t is None:
            break
        列們.append(t)
        起 = 段迄 + pd.Timedelta(days=1)
    if not 列們:
        return
    表 = pd.concat([舊] + 列們).drop_duplicates("date", keep="last").sort_values("date")
    表.to_csv(檔, index=False)
    print(f"台指VIX 完成：{len(表)} 筆（{表['date'].min()}～{表['date'].max()}）")


def 解析台指VIX(文字):
    """CSV 第一欄是日期，其餘欄取名稱含「收盤」的，沒有就取最後一個數字欄。解析不出來回傳 None。"""
    try:
        t = pd.read_csv(io.StringIO(文字))
    except Exception:
        return None
    if t.empty or t.shape[1] < 2:
        return None
    日 = pd.to_datetime(t.iloc[:, 0].astype(str).str.strip(), format="mixed", errors="coerce")
    欄 = [c for c in t.columns[1:] if "收盤" in str(c)] or [t.columns[-1]]
    值 = pd.to_numeric(t[欄[0]].astype(str).str.replace(",", "").str.strip(), errors="coerce")
    out = pd.DataFrame({"date": 日.dt.strftime("%Y-%m-%d"), "close": 值}).dropna()
    return out if len(out) else None


def 讀台指VIX():
    f = 資料夾 / "tw_vix.csv"
    if not f.exists():
        return pd.Series(dtype=float)
    t = pd.read_csv(f, parse_dates=["date"]).dropna().drop_duplicates("date").sort_values("date")
    return t.set_index("date")["close"].astype(float)


def VIX現況(vix):
    """最新值、歷史分位（資料期間內）、離近 250 日高點、近 5 日最高。"""
    if len(vix) < 20:
        return None
    今 = float(vix.iloc[-1])
    return {"日期": vix.index[-1], "VIX": round(今, 1), "分位%": round(float((vix <= 今).mean() * 100)),
            "近5日最高": round(float(vix.tail(5).max()), 1), "筆數": len(vix), "起": vix.index[0]}


def VIX回測(vix, 加權, 門檻=(30, 40, 50), 天數=(5, 20, 60), 間隔=20):
    """VIX 第一次站上門檻那天（之後 間隔 個交易日內不重算）起，加權 N 日報酬，對照全部日子。"""
    if len(vix) < 50 or len(加權) < 80:
        return pd.DataFrame()
    大 = 加權.sort_index()
    列 = []
    for 門 in 門檻:
        日們, 上次 = [], -10**9
        v = vix[vix.index.isin(大.index)]
        for i, (d, x) in enumerate(v.items()):
            if x >= 門 and i - 上次 > 間隔:
                日們.append(d)
                上次 = i
        x = {"VIX 門檻": f"≥ {門}", "次數": len(日們)}
        for n in 天數:
            報 = [(大.iloc[大.index.get_loc(d) + n] / 大.loc[d] - 1) * 100 for d in 日們 if 大.index.get_loc(d) + n < len(大)]
            x[f"{n} 日平均%"] = round(float(np.mean(報)), 1) if 報 else None
            x[f"{n} 日上漲%"] = round(float(np.mean(np.array(報) > 0) * 100)) if 報 else None
        列.append(x)
    基 = {"VIX 門檻": "全部日子", "次數": len(大)}
    for n in 天數:
        報 = (大.shift(-n) / 大 - 1).dropna() * 100
        基[f"{n} 日平均%"] = round(float(報.mean()), 1)
        基[f"{n} 日上漲%"] = round(float((報 > 0).mean() * 100))
    列.append(基)
    return pd.DataFrame(列)


# ---------- 3 營業利益四象限、ODM 存貨銷售比 ----------
def 單季(income):
    """income.csv 的損益是年初至今累計，Q2 以後要減掉前一季。回傳多一欄 單季營益、單季營收。"""
    t = income.copy()
    t["年"] = t["quarter"].str[:4].astype(int)
    t["季"] = t["quarter"].str[-1].astype(int)
    t = t.sort_values(["code", "年", "季"])
    for 欄, 新 in (("opinc", "單季營益"), ("revenue", "單季營收")):
        前 = t.groupby(["code", "年"])[欄].shift(1)
        連 = t.groupby(["code", "年"])["季"].shift(1) == t["季"] - 1  # 前一季必須存在才相減
        t[新] = np.where(t["季"] == 1, t[欄], np.where(連, t[欄] - 前, np.nan))
    return t


def 營益四象限(income, 季=None):
    """每檔最新一季：營益年增（對去年同季）與上一季年增比較。
    成長加速＝年增>0 且比上季高；成長放緩＝年增>0 且比上季低；衰退加深＝年增≤0 且比上季低；衰退收斂＝年增≤0 且比上季高。
    年增用「(今-去年)/|去年|」，去年同季營益≤0 的不分類。"""
    t = 單季(income)
    t["去年"] = t.groupby(["code", "季"])["單季營益"].shift(1)
    t["年增"] = np.where(t["去年"] > 0, (t["單季營益"] - t["去年"]) / t["去年"] * 100, np.nan)
    t["上季年增"] = t.groupby("code")["年增"].shift(1)
    季 = 季 or t["quarter"].max()
    s = t[(t["quarter"] == 季) & t["年增"].notna() & t["上季年增"].notna()].copy()
    up = s["年增"] > s["上季年增"]
    pos = s["年增"] > 0
    s["象限"] = np.select([pos & up, pos & ~up, ~pos & ~up, ~pos & up], ["成長加速", "成長放緩", "衰退加深", "衰退收斂"], default="")
    s["毛利率"] = (s["gross"] / s["revenue"] * 100).round(1)
    return s[["code", "quarter", "單季營益", "年增", "上季年增", "象限"]].assign(
        年增=lambda x: x["年增"].round(1), 上季年增=lambda x: x["上季年增"].round(1)), 季


def 四象限回測(income, 價, 加權, 延遲天=75, 持有=60):
    """每個季度財報公布後（季底＋延遲天）依象限分組，持有 持有 個交易日，平均報酬（扣掉同期全市場平均）。
    樣本：每季每組要有 ≥ 10 檔。價：index 日期、欄代號的收盤。"""
    t = 單季(income)
    t["去年"] = t.groupby(["code", "季"])["單季營益"].shift(1)
    t["年增"] = np.where(t["去年"] > 0, (t["單季營益"] - t["去年"]) / t["去年"] * 100, np.nan)
    t["上季年增"] = t.groupby("code")["年增"].shift(1)
    t = t[t["年增"].notna() & t["上季年增"].notna()]
    pos, up = t["年增"] > 0, t["年增"] > t["上季年增"]
    t["象限"] = np.select([pos & up, pos & ~up, ~pos & ~up, ~pos & up], ["成長加速", "成長放緩", "衰退加深", "衰退收斂"], default="")
    大 = 加權.reindex(價.index).ffill()
    列 = []
    for q, g in t.groupby("quarter"):
        年, 季 = int(q[:4]), int(q[-1])
        底 = pd.Timestamp(年, 季 * 3, 1) + pd.offsets.MonthEnd(0)
        進 = 底 + pd.Timedelta(days=延遲天)
        後 = 價.index[價.index >= 進]
        if not len(後):
            continue
        i = 價.index.get_loc(後[0])
        if i + 持有 >= len(價):
            continue
        報 = (價.iloc[i + 持有] / 價.iloc[i] - 1) * 100
        大報 = float(報.mean())   # 對照＝同期全市場平均（等權），加權指數是市值加權，拿來比會被大型股拖偏
        for 象, h in g.groupby("象限"):
            r = 報.reindex(h["code"]).dropna()
            if len(r) >= 10:
                列.append({"季": q, "象限": 象, "檔數": len(r), "平均報酬%": r.mean(), "超額%": r.mean() - 大報})
    if not 列:
        return pd.DataFrame()
    d = pd.DataFrame(列)
    out = d.groupby("象限").agg(季數=("季", "nunique"), 平均檔數=("檔數", "mean"), 平均報酬=("平均報酬%", "mean"),
                              平均超額=("超額%", "mean"), 贏市場季=("超額%", lambda s: (s > 0).mean() * 100)).round(1).reset_index()
    return out.rename(columns={"平均報酬": "平均報酬%", "平均超額": "平均超額%（扣全市場）", "贏市場季": "贏市場的季%"})


def 抓ODM存貨():
    """FinMind 資產負債表的存貨（Inventories）→ data/fundamental/odm_inventory.csv（code, quarter, inventory 千元）。
    只抓鴻海、廣達、緯創三檔；失敗不影響其他資料。"""
    import requests
    檔 = 資料夾 / "fundamental" / "odm_inventory.csv"
    列 = []
    for c in ODM:
        try:
            j = requests.get("https://api.finmindtrade.com/api/v4/data", timeout=60,
                             params={"dataset": "TaiwanStockBalanceSheet", "data_id": c, "start_date": "2022-01-01"}).json()
        except Exception as 錯誤:
            print(f"ODM 存貨 {c} 失敗：{錯誤}")
            continue
        if j.get("status") != 200:
            print(f"ODM 存貨：FinMind 回 {j.get('status')}")
            return
        for x in j.get("data") or []:
            if x.get("type") == "Inventories":
                季 = pd.Timestamp(x["date"])
                列.append({"code": c, "quarter": f"{季.year}Q{(季.month - 1) // 3 + 1}", "inventory": round(x["value"] / 1000)})
        time.sleep(2)
    if 列:
        舊 = pd.read_csv(檔, dtype={"code": str}) if 檔.exists() else pd.DataFrame(columns=["code", "quarter", "inventory"])
        表 = pd.concat([舊, pd.DataFrame(列)]).drop_duplicates(["code", "quarter"], keep="last").sort_values(["code", "quarter"])
        表.to_csv(檔, index=False)
        print(f"ODM 存貨完成：{len(表)} 筆")


def ODM存貨銷售比(income, 存貨, 代號表=None):
    """存貨：odm_inventory.csv（code, quarter, inventory 千元）。比＝期末存貨 ÷ 單季營收；每檔最近 6 季。"""
    if 存貨 is None or 存貨.empty:
        return pd.DataFrame()
    代號表 = 代號表 or ODM
    s = 單季(income)
    列 = []
    for c, 名 in 代號表.items():
        a = s[s["code"] == c][["quarter", "單季營收"]]
        b = 存貨[存貨["code"] == c][["quarter", "inventory"]]
        m = a.merge(b, on="quarter").dropna().tail(6)
        前 = None
        for _, r in m.iterrows():
            比 = r["inventory"] / r["單季營收"]
            列.append({"代號": c, "名稱": 名, "季": r["quarter"], "存貨億": round(r["inventory"] / 1e5), "單季營收億": round(r["單季營收"] / 1e5),
                     "存貨銷售比": round(比, 3), "較上季": None if 前 is None else round(比 - 前, 3)})
            前 = 比
    return pd.DataFrame(列)


def ODM警訊(表):
    """某檔存貨銷售比連 2 季上升 → 列出（網紅說法：存貨高但營收放緩是 AI 轉弱的領先訊號；這只是觀察，沒有回測）。"""
    if 表.empty:
        return []
    出 = []
    for c, g in 表.groupby("代號"):
        上 = g["較上季"].dropna().tail(2)
        if len(上) == 2 and (上 > 0).all():
            出.append(f"{c} {g['名稱'].iloc[0]} 存貨銷售比連 2 季上升（最新 {g['存貨銷售比'].iloc[-1]:.2f}）")
    return 出


# ---------- 4 限空令事件追蹤 ----------
限空事件 = [
    ("2022-07-12", "2022 通膨升息（國安基金決議日）"),
    ("2025-04-08", "2025 對等關稅（國安基金決議日）"),
    ("2026-11-09", "2026 第一波限空令"),
    ("2026-11-20", "2026 第二波限空令（限空令 2.0）"),
]


def 限空事件追蹤(加權, 事件=None, 天數=(1, 5, 20, 60)):
    """從事件日（或其後第一個交易日）收盤算起，加權 N 日報酬；還沒滿的另列「至今 X 日」。回傳 (表, 本次至今)。"""
    大 = 加權.sort_index()
    列, 今 = [], []
    for 日, 名 in (事件 or 限空事件):
        後 = 大.index[大.index >= pd.Timestamp(日)]
        if not len(後):
            continue
        i = 大.index.get_loc(後[0])
        x = {"事件": 名, "事件日": f"{大.index[i]:%Y-%m-%d}", "當日收盤": round(float(大.iloc[i]), 0)}
        for n in 天數:
            x[f"{n} 日%"] = round(float((大.iloc[i + n] / 大.iloc[i] - 1) * 100), 1) if i + n < len(大) else None
        已 = len(大) - 1 - i
        x["至今天數"] = 已
        x["至今%"] = round(float((大.iloc[-1] / 大.iloc[i] - 1) * 100), 1)
        列.append(x)
    return pd.DataFrame(列)


# ---------- 5 谷底量與領頭羊墊高底部 ----------
def 谷底量(成交值, 加權, 回看=60, 比例=0.5):
    """成交值 ÷ 近 回看 日最高 ≤ 比例，且加權收盤沒有跌破近 10 日最低（量縮不破底）。回傳 DataFrame（比例、是否量縮不破底）。"""
    d = pd.DataFrame({"成交值": 成交值, "收盤": 加權}).dropna()
    d["比高峰"] = d["成交值"] / d["成交值"].rolling(回看, min_periods=20).max()
    低 = d["收盤"].shift(1).rolling(10).min()
    d["量縮不破底"] = (d["比高峰"] <= 比例) & (d["收盤"] >= 低)
    return d


def 領頭羊墊高(領頭, 加權, 窗=5):
    """領頭羊（如台積電）近 窗 日最低 > 前 窗 日最低，但加權近 窗 日最低 ≤ 前 窗 日最低 → True。"""
    d = pd.DataFrame({"領": 領頭, "大": 加權}).dropna()
    領新, 領舊 = d["領"].rolling(窗).min(), d["領"].shift(窗).rolling(窗).min()
    大新, 大舊 = d["大"].rolling(窗).min(), d["大"].shift(窗).rolling(窗).min()
    return (領新 > 領舊) & (大新 <= 大舊)


def 落底訊號回測(成交值, 加權, 領頭, 天數=(5, 20, 60), 間隔=20, 跌深=-0.08):
    """只看「加權離近 120 日高點跌 8% 以上」的日子。訊號：量縮不破底、領頭羊墊高、兩者同時。
    連續訊號 間隔 日內只算第一次。對照：跌深日子的平均。"""
    谷 = 谷底量(成交值, 加權)
    d = 谷.join(領頭羊墊高(領頭, 加權).rename("墊高"), how="left")
    d["墊高"] = d["墊高"].fillna(False)
    d["深"] = d["收盤"] / d["收盤"].rolling(120, min_periods=60).max() - 1 <= 跌深
    大 = d["收盤"]
    組 = {"量縮不破底": d["量縮不破底"] & d["深"], "領頭羊墊高底部": d["墊高"] & d["深"],
         "兩者同時": d["量縮不破底"] & d["墊高"] & d["深"]}
    列 = []
    for 名, s in 組.items():
        日們, 上次 = [], -10**9
        for i, (dd, v) in enumerate(s.items()):
            if v and i - 上次 > 間隔:
                日們.append(dd)
                上次 = i
        x = {"訊號": 名, "次數": len(日們)}
        for n in 天數:
            報 = [(大.iloc[大.index.get_loc(dd) + n] / 大.loc[dd] - 1) * 100 for dd in 日們 if 大.index.get_loc(dd) + n < len(大)]
            x[f"{n} 日平均%"] = round(float(np.mean(報)), 1) if 報 else None
            x[f"{n} 日上漲%"] = round(float(np.mean(np.array(報) > 0) * 100)) if 報 else None
        列.append(x)
    基 = {"訊號": "跌深日子（對照）", "次數": int(d["深"].sum())}
    for n in 天數:
        報 = ((大.shift(-n) / 大 - 1) * 100)[d["深"]].dropna()
        基[f"{n} 日平均%"] = round(float(報.mean()), 1) if len(報) else None
        基[f"{n} 日上漲%"] = round(float((報 > 0).mean() * 100)) if len(報) else None
    列.append(基)
    return pd.DataFrame(列)


# ---------- 回測結果檔（離線重算，網頁只讀結果，不必載入全市場價格） ----------
回測檔 = 資料夾 / "lab1120_backtest.json"


def 重算回測():
    """讀 data/prices 全部歷史＋指數，重算 四象限、落底訊號、VIX 回測 → data/lab1120_backtest.json。
    指令：python lab1120.py backtest"""
    import glob
    import json
    列, 值 = [], {}
    for f in sorted(glob.glob(str(資料夾 / "prices" / "*" / "*.csv.gz"))):
        x = pd.read_csv(f, dtype={"code": str}, usecols=["code", "close", "value"])
        x = x[x["code"].str.fullmatch(r"\d{4}")]
        d = pd.Timestamp(f[-15:-7])
        值[d] = x["value"].sum() / 1e8
        列.append(x[["code", "close"]].assign(date=d))
    價 = pd.concat(列).pivot(index="date", columns="code", values="close")
    成交值 = pd.Series(值)
    K = pd.read_csv(資料夾 / "index_ohlc.csv", parse_dates=["date"])
    加權 = K[K["symbol"] == "TAIEX"].set_index("date")["close"]
    income = pd.read_csv(資料夾 / "fundamental" / "income.csv", dtype={"code": str})
    out = {"算於": f"{pd.Timestamp.today():%Y-%m-%d}", "資料區間": f"{價.index[0]:%Y-%m-%d}～{價.index[-1]:%Y-%m-%d}",
           "四象限": 四象限回測(income, 價, 加權).to_dict("records"),
           "落底訊號": 落底訊號回測(成交值, 加權, 價["2330"]).to_dict("records")}
    vix = 讀台指VIX()
    if len(vix) > 50:
        out["VIX"] = VIX回測(vix, 加權).to_dict("records")
        out["VIX區間"] = f"{vix.index[0]:%Y-%m-%d}～{vix.index[-1]:%Y-%m-%d}"
    回測檔.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("完成", 回測檔)


def 讀回測():
    import json
    return json.loads(回測檔.read_text()) if 回測檔.exists() else {}


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["backtest"]:
        重算回測()
