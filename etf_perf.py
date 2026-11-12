# 主動式 ETF 績效體檢：跟 0050（或分類基準）比夏普值、beta、上下行捕獲率、同 beta 組合超額、滾動超額、
# 台積電權重差、公布持股後隔天表現。只用網站已有的行情（指標表的「日報酬」已含除權息、面額分割）與每日持股。
# 2026-11-08 PTT「主動式 ETF 攻守比」查核後新增（建議 1～9）。
from pathlib import Path

import numpy as np
import pandas as pd

資料夾 = Path(__file__).resolve().parent / "data"
無風險利率 = 0.017      # 年化，約一年期定存
借款成本 = 0.03         # 年化，基準是美股等沒有正 2 可配時，用借錢放大的成本
正2代號 = "00631L"      # 元大台灣50正2：台股型同 beta 組合用「0050＋00631L」
正2倍數 = 2.0

# 分類基準：(類型, 基準代號, 說明)。沒列的主動式 ETF 一律當台股型，對 0050。
分類 = {
    "00402A": ("美股", "00662"), "00983A": ("美股", "00662"), "00989A": ("美股", "00662"), "00997A": ("美股", "00662"),
    "00409A": ("全球", "00646"), "00988A": ("全球", "00646"), "00990A": ("全球", "00646"),
    "00412A": ("亞洲半導體", "00830"),
    "00400A": ("高股息", "0056"), "00401A": ("高股息", "0056"), "00406A": ("高股息", "0056"),
    "00408A": ("高股息", "0056"), "00984A": ("高股息", "0056"), "00999A": ("高股息", "0056"),
    "00998A": ("金融", "0055"),
}
基準名 = {"0050": "元大台灣50", "00662": "富邦NASDAQ", "00646": "元大S&P500（全球近似）",
         "00830": "國泰費城半導體（近似）", "0056": "元大高股息", "0055": "元大MSCI金融"}


海外基準 = {"00662", "00646", "00830"}


def 類型(代號):
    return 分類.get(代號, ("台股", "0050"))[0]


def 分類基準(代號):
    return 分類.get(代號, ("台股", "0050"))[1]


def 主動式代號(代號們):
    return sorted(c for c in 代號們 if isinstance(c, str) and len(c) == 6 and c.startswith("00") and c.endswith("A")
                  and c[2:5].isdigit())


def 報酬寬表(指標, 代號們, 起日=None):
    """日報酬寬表（列＝日期、欄＝代號），日報酬已含除權息與分割；每檔上市第一天設成缺值（從第一個收盤價起算，不用募集價）。"""
    t = 指標[指標["code"].isin(list(代號們))]
    if 起日 is not None:
        t = t[t["date"] >= pd.Timestamp(起日) - pd.Timedelta(days=10)]
    寬 = t.pivot_table(index="date", columns="code", values="日報酬", aggfunc="last").sort_index().astype(float)
    首日 = t.groupby("code")["date"].min()
    全首日 = 指標.groupby("code")["date"].min()
    for c, d in 首日.items():
        if d == 全首日.get(c) and c in 寬.columns:   # 真的是上市第一天（不是資料起點），那天的漲跌是對募集淨值算的
            寬.loc[d, c] = np.nan
    return 寬


def _捕獲(r, m, 方向):
    sel = m > 0 if 方向 > 0 else m < 0
    if sel.sum() < 3:
        return np.nan
    a = (1 + r[sel]).prod() ** (1 / sel.sum()) - 1
    b = (1 + m[sel]).prod() ** (1 / sel.sum()) - 1
    return a / b * 100 if b else np.nan


def 同beta組合(m, beta, 正2=None, 槓桿倍數=正2倍數):
    """跟基準同 beta、每天再平衡的組合日報酬：beta>1 → 基準＋正 2（沒有正 2 就用借錢放大）；beta<1 → 基準＋現金。"""
    if beta >= 1:
        if 正2 is not None:
            w = (beta - 1) / (槓桿倍數 - 1)
            return (1 - w) * m + w * 正2.fillna(槓桿倍數 * m)
        return beta * m - (beta - 1) * 借款成本 / 252
    return beta * m + (1 - beta) * 無風險利率 / 252


def _週beta(r, m):
    """用每 5 個交易日的累積報酬估 beta：海外基準（美股收盤在台股收盤之後）每日報酬時間對不齊，日 beta 會失真。"""
    組 = np.arange(len(r)) // 5
    rw = (1 + r).groupby(組).prod() - 1
    mw = (1 + m).groupby(組).prod() - 1
    return float(np.cov(rw, mw)[0, 1] / mw.var()) if len(rw) >= 4 and mw.var() > 0 else np.nan


def 指標計算(r, m, 正2=None, 最少天數=20, 週beta=False):
    """一檔 ETF 跟基準比較的標準指標。r、m 是同一段期間的日報酬（r 的缺值當作還沒上市，自動略過）。
    週beta=True：beta 用 5 日報酬估（海外基準用）。"""
    r = r.dropna()
    m = m.reindex(r.index).fillna(0)
    n = len(r)
    if n < 最少天數:
        return None
    累 = (1 + r).prod() - 1
    基累 = (1 + m).prod() - 1
    波動 = r.std() * np.sqrt(252)
    var = m.var()
    beta = _週beta(r, m) if 週beta else (float(np.cov(r, m)[0, 1] / var) if var > 0 else np.nan)
    夏普 = (r.mean() * 252 - 無風險利率) / 波動 if 波動 > 0 else np.nan
    alpha = ((r - 無風險利率 / 252) - beta * (m - 無風險利率 / 252)).mean() * 252 if pd.notna(beta) else np.nan
    上, 下 = _捕獲(r, m, 1), _捕獲(r, m, -1)
    淨 = (1 + r).cumprod()
    組 = 同beta組合(m, beta, None if 正2 is None else 正2.reindex(r.index)) if pd.notna(beta) else None
    組累 = (1 + 組).prod() - 1 if 組 is not None else np.nan
    return {"起": r.index[0], "天數": n, "報酬%": 累 * 100, "基準報酬%": 基累 * 100, "beta": beta,
            "相關": float(r.corr(m)), "夏普": 夏普, "年化alpha%": alpha * 100, "上行捕獲%": 上, "下行捕獲%": 下,
            "捕獲比": 上 / 下 if pd.notna(上) and pd.notna(下) and 下 > 0 else np.nan,
            "最大回檔%": float((淨 / 淨.cummax() - 1).min() * 100), "年化波動%": 波動 * 100,
            "同beta組合%": 組累 * 100, "超額vs組合%": (累 - 組累) * 100}


def 體檢表(寬, 主動們, 起日, 迄日=None, 基準="0050", 最少天數=20):
    """每檔主動式 ETF（加上 0050、正 2 當參考列）的績效體檢。基準＝"0050" 全部對 0050；="分類" 用各自的分類基準。
    同 beta 組合：基準是 0050 時用 0050＋00631L；其他基準用基準＋借錢（或現金）。"""
    寬 = 寬.loc[pd.Timestamp(起日):迄日] if 迄日 is not None else 寬.loc[pd.Timestamp(起日):]
    列們 = []
    for c in list(主動們) + ["0050", 正2代號]:
        if c not in 寬.columns:
            continue
        b = 分類基準(c) if 基準 == "分類" and c in 主動們 else "0050"
        if b not in 寬.columns:
            b = "0050"
        正2 = 寬[正2代號] if b == "0050" and 正2代號 in 寬.columns and c != 正2代號 else None
        結果 = 指標計算(寬[c], 寬[b], 正2, 最少天數, 週beta=b in 海外基準)
        if 結果 and c == 正2代號:
            結果["同beta組合%"] = 結果["超額vs組合%"] = np.nan   # 正 2 本身就是組合的一部分，不比
        if 結果:
            列們.append({"代號": c, "類型": "參考" if c in ("0050", 正2代號) else 類型(c), "基準": b, **結果})
    return pd.DataFrame(列們)


def 滾動超額(寬, 代號, 基準="0050", 窗=60):
    """每天往回 窗 個交易日：ETF 報酬 − 同 beta 組合報酬（beta 也用那 窗 天估），單位百分點。看經理人加分是不是一直都在。"""
    if 代號 not in 寬.columns or 基準 not in 寬.columns:
        return pd.Series(dtype=float)
    r = 寬[代號].dropna()
    m = 寬[基準].reindex(r.index).fillna(0)
    l2 = 寬[正2代號].reindex(r.index) if 基準 == "0050" and 正2代號 in 寬.columns else None
    結果 = {}
    for i in range(窗, len(r) + 1):
        rr, mm = r.iloc[i - 窗:i], m.iloc[i - 窗:i]
        var = mm.var()
        if var <= 0:
            continue
        beta = np.cov(rr, mm)[0, 1] / var
        組 = 同beta組合(mm, beta, None if l2 is None else l2.iloc[i - 窗:i])
        結果[r.index[i - 1]] = ((1 + rr).prod() - (1 + 組).prod()) * 100
    return pd.Series(結果, dtype=float)


def 純槓桿攻守比(m, 倍數, 漲段, 跌段):
    """每天固定 倍數、零選股能力的假想基金，用 PTT 原文的攻守比公式算出來是多少（說明「沒加分」不是 1）。"""
    def 段(a, b, k):
        x = m.loc[pd.Timestamp(a):pd.Timestamp(b)]
        return (1 + k * x).prod() - 1
    漲 = 段(*漲段, 倍數) / 段(*漲段, 1)
    跌 = 段(*跌段, 倍數) / 段(*跌段, 1)
    return 漲 / 跌 if 跌 else np.nan


# ---------- 7 台積電權重差 ----------
def 台積電權重(持股, 起日=None):
    """每檔主動式 ETF 每天的台積電權重（%）。持股表要有 etf、date、code、weight。"""
    t = 持股 if 起日 is None else 持股[持股["date"] >= pd.Timestamp(起日)]
    全日 = t[["etf", "date"]].drop_duplicates()
    台 = t[t["code"] == "2330"][["etf", "date", "weight"]]
    台 = 全日.merge(台, on=["etf", "date"], how="left").fillna({"weight": 0.0})
    return 台


def 估計0050台積電權重(成分, 市值):
    """用 0050 成分股的市值算台積電占比（%）；指數其實用自由流通市值，這是近似值。"""
    值 = pd.Series({c: 市值.get(c, np.nan) for c in 成分}).dropna()
    if "2330" not in 值.index or 值.sum() <= 0:
        return np.nan
    return float(值["2330"] / 值.sum() * 100)


def 台積電因素(台權, 基準權重, 台積電日報酬, 寬=None):
    """每檔：最新、期間平均台積電權重，跟 0050 的差，以及「少（多）抱台積電」粗估讓報酬差了幾個百分點
    ＝ 平均權重差 × 台積電同期報酬。期間＝這檔持股資料的第一天到最後一天（每檔各自算）；有 寬 時一起列 ETF 同期報酬。"""
    if 台權.empty or pd.isna(基準權重):
        return pd.DataFrame()
    def 期間(s, 起, 迄):
        x = s.loc[起:迄].iloc[1:].dropna()   # 第一天的持股是當天收盤後的，從隔天起算
        return ((1 + x).prod() - 1) * 100
    列們 = []
    for e, g in 台權.sort_values("date").groupby("etf"):
        起, 迄 = g["date"].min(), g["date"].max()
        台 = 期間(台積電日報酬, 起, 迄)
        列 = {"代號": e, "起": 起, "最新權重%": g["weight"].iloc[-1], "平均權重%": g["weight"].mean(), "資料天數": len(g),
             "0050權重%": 基準權重, "權重差": g["weight"].mean() - 基準權重, "台積電同期%": 台}
        列["台積電影響(百分點)"] = 列["權重差"] / 100 * 台
        if 寬 is not None and e in 寬.columns:
            列["ETF同期%"] = 期間(寬[e], 起, 迄)
        列們.append(列)
    return pd.DataFrame(列們).sort_values("台積電影響(百分點)", ignore_index=True)


# ---------- 8 公布持股後隔天表現（被狙擊？） ----------
def 公布後表現(變化, 行情, 類型們=("新增", "加碼")):
    """持股日 d 的加碼／新增（扣申贖），投信多在 d 晚上公布，看下一個交易日：
    跳空＝開盤 ÷ 前一天收盤 − 1、盤中＝收盤 ÷ 開盤 − 1、5 日＝之後 5 天還原報酬，都扣掉同一天全市場平均。
    行情要有 code、date、open、收盤、日報酬（指標表）。回傳 (每筆明細, 彙總)。"""
    if 變化 is None or len(變化) == 0:
        return pd.DataFrame(), {}
    t = 行情.loc[行情["code"].str.fullmatch(r"\d{4}") & (行情["date"] >= pd.to_datetime(變化["date"]).min()),
               ["code", "date", "open", "收盤", "日報酬"]].copy()
    t["前收"] = t["收盤"] / (1 + t["日報酬"])
    t["跳空"] = (t["open"] / t["前收"] - 1) * 100
    t["盤中"] = (t["收盤"] / t["open"] - 1) * 100
    t = t.replace([np.inf, -np.inf], np.nan)
    t = t[(t["open"] > 0) & (t["跳空"].abs() < 11)]
    t = t.sort_values(["code", "date"])
    對數 = np.log1p(t["日報酬"].astype(float))
    t["後5日"] = (np.exp(對數.groupby(t["code"]).transform(lambda s: s.rolling(5).sum().shift(-4))) - 1) * 100
    市 = t.groupby("date")[["跳空", "盤中", "後5日"]].mean()
    市["開高走低"] = t.assign(x=(t["跳空"] > 0) & (t["盤中"] < 0)).groupby("date")["x"].mean()
    交易日 = pd.Index(sorted(t["date"].unique()))
    e = 變化[變化["type"].isin(類型們)][["etf", "date", "code", "type"]].copy()
    e = e[e["code"].astype(str).str.fullmatch(r"\d{4}")]
    if e.empty:
        return pd.DataFrame(), {}
    位 = 交易日.searchsorted(pd.to_datetime(e["date"]), side="right")
    e = e[位 < len(交易日)]
    e["隔日"] = 交易日[位[位 < len(交易日)]]
    # 同一檔股票同一天被好幾檔 ETF 加碼，只算一次
    e = e.groupby(["code", "隔日"]).agg(檔數=("etf", "nunique"), ETF=("etf", lambda s: "、".join(sorted(set(s))))).reset_index()
    明 = e.merge(t.rename(columns={"date": "隔日"})[["code", "隔日", "跳空", "盤中", "後5日"]], on=["code", "隔日"], how="inner")
    明 = 明.join(市.rename(columns=lambda c: "市場" + c), on="隔日")
    if 明.empty:
        return 明, {}
    明["超額跳空"] = 明["跳空"] - 明["市場跳空"]
    明["超額盤中"] = 明["盤中"] - 明["市場盤中"]
    明["超額後5日"] = 明["後5日"] - 明["市場後5日"]
    明["開高走低"] = (明["跳空"] > 0) & (明["盤中"] < 0)
    彙 = {"筆數": len(明), "平均超額跳空": 明["超額跳空"].mean(), "平均超額盤中": 明["超額盤中"].mean(),
         "平均超額後5日": 明["超額後5日"].dropna().mean(), "後5日筆數": int(明["超額後5日"].notna().sum()),
         "開高走低比例": 明["開高走低"].mean() * 100, "市場開高走低比例": 明["市場開高走低"].mean() * 100,
         "多檔一起加碼筆數": int((明["檔數"] >= 2).sum()),
         "多檔一起加碼超額盤中": 明.loc[明["檔數"] >= 2, "超額盤中"].mean()}
    return 明.sort_values("隔日", ascending=False), 彙


# ---------- 9 費用 ----------
def 讀費用():
    """data/etf/fees.csv（etf_data.更新費用 自動從 MoneyDJ 補，也可手動改）：etf, 經理費, 保管費, 總費用率, 來源, 更新日。"""
    f = 資料夾 / "etf" / "fees.csv"
    if not f.exists():
        return pd.DataFrame(columns=["etf", "經理費", "保管費", "總費用率", "來源", "更新日"])
    return pd.read_csv(f, dtype={"etf": str})


def 年費用(費用表):
    """每檔一年內扣（%）：總費用率（不小於經理費才可信）優先，否則經理費＋保管費。"""
    if 費用表.empty:
        return {}
    t = 費用表.set_index("etf")
    經 = pd.to_numeric(t["經理費"], errors="coerce")
    保 = pd.to_numeric(t["保管費"], errors="coerce").fillna(0)
    總 = pd.to_numeric(t["總費用率"], errors="coerce")
    總 = 總.where(總 >= 經)          # 新基金的總費用率常是未滿一年的部分數字（比經理費還小），不採用
    合 = 總.fillna(經 + 保)
    return 合.dropna().to_dict()


# ---------- 10 LINE 月報 ----------
def 月報文字(寬, 主動們, 月起, 月迄, 年起, 名稱=None, 筆數=3):
    """主動式 ETF 上個月與今年以來「同 beta 組合超額」前 3 名與後 3 名（台股型對 0050＋正 2）。"""
    名稱 = 名稱 or {}
    行們 = []
    for 標, 起, 少 in (("上月", 月起, 10), ("今年以來", 年起, 60)):
        t = 體檢表(寬, 主動們, 起, 月迄, 基準="分類", 最少天數=少)
        t = t[t["類型"] != "參考"].dropna(subset=["超額vs組合%"]).sort_values("超額vs組合%", ascending=False)
        if t.empty:
            continue
        f = lambda r: f"{r['代號']} {名稱.get(r['代號'], '')[:6]} {r['超額vs組合%']:+.1f}"
        行們.append(f"{標}（{len(t)} 檔，贏 {(t['超額vs組合%'] > 0).sum()} 檔）")
        行們.append("　前：" + "、".join(f(r) for _, r in t.head(筆數).iterrows()))
        行們.append("　後：" + "、".join(f(r) for _, r in t.tail(筆數).iloc[::-1].iterrows()))
    if not 行們:
        return []
    return ["", "📊 主動式 ETF 對同 beta 組合（百分點，台股型＝0050＋正2）"] + 行們
