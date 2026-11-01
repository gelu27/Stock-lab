# 總經、國際資金與事件統計（01 市場總覽「總經」區塊用）。資料由 update_data.py 在 GitHub Actions 抓好：
#   data/us_daily.csv   美股、美元指數、原油、HYG、美債殖利率（Yahoo）
#   data/us_macro.csv   美國經濟數據公布值（美國勞工統計局 BLS）
#   data/us_capex.csv   AI 巨頭每季資本支出與營業現金流（Yahoo 財報）
from pathlib import Path

import numpy as np
import pandas as pd

資料夾 = Path(__file__).parent / "data"

# ---------- 25 全球風險燈 ----------
風險項目 = [  # 名稱, us_daily 名稱, 看法：上漲代表什麼, 壓力門檻（20 日變化）, 寬鬆門檻, 單位
    ("美元指數", "美元指數", "美元走強＝資金回流美國、亞股較有壓力", 2.0, -2.0, "%"),
    ("原油", "原油", "油價大漲＝通膨與降息延後的壓力", 10.0, -10.0, "%"),
    ("高收益債 HYG", "高收益債 HYG", "HYG 下跌＝信用市場緊張、風險資產承壓", -2.0, 1.0, "%"),
    ("美債 10 年殖利率", "美債10年殖利率", "殖利率上升＝科技股評價壓力", 0.25, -0.25, "點"),
]


def 風險燈(美):
    """美＝engine.讀取美股()（日期 × 名稱）。回傳列表：名稱、最新、20 日變化、燈、說明。"""
    列們 = []
    if 美 is None:
        return 列們
    for 名, 欄, 說, 壓, 寬, 位 in 風險項目:
        if 欄 not in 美:
            continue
        s = 美[欄].dropna()
        if len(s) < 25:
            continue
        變 = s.iloc[-1] - s.iloc[-21] if 位 == "點" else (s.iloc[-1] / s.iloc[-21] - 1) * 100
        反向 = 壓 < 0  # HYG：跌是壓力
        壓力 = 變 <= 壓 if 反向 else 變 >= 壓
        寬鬆 = 變 >= 寬 if 反向 else 變 <= 寬
        燈 = "⚠️ 壓力" if 壓力 else ("✅ 寬鬆" if 寬鬆 else "➖ 中性")
        列們.append({"項目": 名, "日期": s.index[-1], "最新": float(s.iloc[-1]), "20日變化": float(變), "單位": 位,
                   "燈": 燈, "說明": 說})
    if "VIX" in 美 and 美["VIX"].notna().sum() > 5:
        v = 美["VIX"].dropna()
        列們.append({"項目": "VIX 恐慌指數", "日期": v.index[-1], "最新": float(v.iloc[-1]),
                   "20日變化": float(v.iloc[-1] - v.iloc[-21]) if len(v) > 21 else np.nan, "單位": "點",
                   "燈": "⚠️ 壓力" if v.iloc[-1] >= 25 else ("✅ 寬鬆" if v.iloc[-1] <= 15 else "➖ 中性"),
                   "說明": "VIX 25 以上＝美股恐慌，15 以下＝很樂觀"})
    return 列們


def 風險總結(列們):
    壓 = sum("壓力" in x["燈"] for x in 列們)
    寬 = sum("寬鬆" in x["燈"] for x in 列們)
    if not 列們:
        return ""
    if 壓 >= 3:
        return f"{壓} 項亮壓力燈：國際資金環境偏緊，台股較容易被外資賣超"
    if 寬 >= 3:
        return f"{寬} 項亮寬鬆燈：國際資金環境寬鬆，有利風險資產"
    return f"壓力 {壓} 項、寬鬆 {寬} 項：國際資金環境中性"


# ---------- 27 費半 ÷ S&P 500 ----------
def 費半相對強弱(美):
    if 美 is None or "費城半導體" not in 美 or "S&P 500" not in 美:
        return None
    比 = (美["費城半導體"] / 美["S&P 500"]).dropna()
    if len(比) < 60:
        return None
    高 = 比.tail(250).max()
    return {"序列": 比.tail(250), "最新": float(比.iloc[-1]), "一年高": float(高), "高點日": 比.tail(250).idxmax(),
            "回撤%": float((比.iloc[-1] / 高 - 1) * 100), "20日變化%": float((比.iloc[-1] / 比.iloc[-21] - 1) * 100)}


# ---------- 29 美股估值溫度（價格面） ----------
def 美股溫度(美):
    """S&P 500：距 200 日線、在兩年區間的位置、RSI，加 VIX 反向，平均成 0～100 的溫度（越高越熱）。
    沒有免費的本益比歷史，所以這是「價格面」溫度，不是真正的估值。"""
    if 美 is None or "S&P 500" not in 美:
        return None
    s = 美["S&P 500"].dropna()
    if len(s) < 220:
        return None
    距 = s / s.rolling(200).mean() - 1
    百 = lambda x: float((x.dropna() <= x.dropna().iloc[-1]).mean() * 100)
    變 = s.diff()
    漲 = 變.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    跌 = (-變.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + 漲 / 跌)
    項 = {"距 200 日線": 百(距.tail(500)), "兩年區間位置": float((s.iloc[-1] - s.tail(500).min()) / (s.tail(500).max() - s.tail(500).min()) * 100),
          "RSI": float(rsi.iloc[-1])}
    if "VIX" in 美:
        項["VIX 反向"] = 100 - 百(美["VIX"].dropna().tail(500))
    溫 = float(np.mean(list(項.values())))
    return {"溫度": 溫, "項目": 項, "距200日線%": float(距.iloc[-1] * 100),
            "看法": "過熱" if 溫 >= 75 else ("偏熱" if 溫 >= 60 else ("偏冷" if 溫 <= 30 else "正常"))}


# ---------- 26 台幣與外資 ----------
def 台幣外資(匯率, 外資億):
    """匯率＝engine.讀取匯率()（date, usdtwd）；外資億＝每日外資買賣超金額（億元，index 日期）。"""
    if 匯率 is None or len(匯率) < 30:
        return None
    x = 匯率.set_index("date")["usdtwd"].dropna()
    五 = (x.iloc[-1] / x.iloc[-6] - 1) * 100
    年 = x.tail(250)
    結果 = {"最新": float(x.iloc[-1]), "日期": x.index[-1], "5日變化%": float(五), "一年高": float(年.max()), "一年低": float(年.min()),
          "距一年高%": float((x.iloc[-1] / 年.max() - 1) * 100), "警示": []}
    外5 = float(外資億.tail(5).sum()) if 外資億 is not None and len(外資億) else np.nan
    結果["外資5日億"] = 外5
    if 五 > 0.5 and not np.isnan(外5) and 外5 < 0:
        結果["警示"].append(f"台幣 5 日貶 {五:.2f}%、外資 5 日賣超 {abs(外5):,.0f} 億：資金同步流出，常見於大盤修正期")
    if 五 < -0.5 and not np.isnan(外5) and 外5 > 0:
        結果["警示"].append(f"台幣 5 日升 {abs(五):.2f}%、外資 5 日買超 {外5:,.0f} 億：資金同步流入")
    if 結果["距一年高%"] > -1:
        結果["警示"].append(f"美元兌台幣 {x.iloc[-1]:.3f}，離一年高點 {年.max():.3f} 不到 1%（台幣接近一年最弱），外資匯出壓力大")
    return 結果


# ---------- 28 AI 巨頭資本支出 ----------
def 讀取資本支出():
    f = 資料夾 / "us_capex.csv"
    return pd.read_csv(f) if f.exists() else None


def AI巨頭資本支出(表):
    """表：symbol, name, quarter(2025Q3), capex, ocf（美元）。回傳 (每季合計表, 各家最新一季表)。"""
    if 表 is None or 表.empty:
        return None, None
    t = 表.copy()
    t["fcf"] = t["ocf"] - t["capex"]
    合 = t.groupby("quarter")[["capex", "ocf", "fcf"]].sum(min_count=1).sort_index() / 1e9
    合["家數"] = t.groupby("quarter")["symbol"].nunique()
    合 = 合[合["家數"] == 合["家數"].max()]
    合["capex 年增%"] = (合["capex"] / 合["capex"].shift(4) - 1) * 100
    新 = t.sort_values("quarter").groupby("symbol").tail(5)
    列們 = []
    for 代, g in 新.groupby("symbol"):
        g = g.sort_values("quarter")
        r = g.iloc[-1]
        去 = t[(t["symbol"] == 代) & (t["quarter"] == f"{int(r['quarter'][:4]) - 1}{r['quarter'][4:]}")]
        列們.append({"公司": r["name"], "季度": r["quarter"], "資本支出(億美元)": r["capex"] / 1e8,
                   "年增%": (r["capex"] / 去["capex"].iloc[0] - 1) * 100 if len(去) and 去["capex"].iloc[0] else np.nan,
                   "營業現金流(億美元)": r["ocf"] / 1e8, "自由現金流(億美元)": r["fcf"] / 1e8,
                   "資本支出÷營業現金流%": r["capex"] / r["ocf"] * 100 if r["ocf"] else np.nan})
    return 合, pd.DataFrame(列們)


# ---------- 30 美國經濟數據公布值 ----------
美國數列 = {  # 美國勞工統計局（BLS）代號: (中文, 轉換, econ_calendar 標題)
    "CUSR0000SA0": ("CPI 月增率（%）", "月增", "CPI m/m"), "CUSR0000SA0L1E": ("核心 CPI 月增率（%）", "月增", "Core CPI m/m"),
    "CES0000000001": ("非農就業人數（千人）", "差", "Non-Farm Employment Change"), "LNS14000000": ("失業率（%）", "值", "Unemployment Rate"),
}
越高越熱 = {"CUSR0000SA0", "CUSR0000SA0L1E", "CES0000000001"}


def 讀取美國數據():
    f = 資料夾 / "us_macro.csv"
    return pd.read_csv(f, parse_dates=["date"]) if f.exists() else None


def _預期數字(字):
    import re
    m = re.search(r"(-?[\d.]+)\s*([KM%]?)", str(字 or ""))
    if not m:
        return np.nan
    v = float(m.group(1))
    return v * 1000 if m.group(2) == "M" else v


def 美國數據表(數據, 行事曆=None):
    """每個數列最新一期、前一期、跟 Forex Factory 預期比（高於／低於預期）。"""
    if 數據 is None or 數據.empty:
        return pd.DataFrame()
    列們 = []
    for 代, (名, 轉, 標題) in 美國數列.items():
        s = 數據[數據["series"] == 代].set_index("date")["value"].dropna().sort_index()
        if len(s) < 3:
            continue
        v = (s.pct_change() * 100).round(2) if 轉 == "月增" else (s.diff().round(0) if 轉 == "差" else s)
        v = v.dropna()
        預 = np.nan
        if 行事曆 is not None and len(行事曆):
            近 = 行事曆[(行事曆["title"] == 標題) & (行事曆["country"] == "USD")].sort_values("date")
            if len(近):
                預 = _預期數字(近["forecast"].iloc[-1])
        最新 = float(v.iloc[-1])
        差 = 最新 - 預 if not np.isnan(預) else np.nan
        判 = "—" if np.isnan(差) or abs(差) < 1e-9 else ("高於預期" if 差 > 0 else "低於預期")
        if 判 != "—" and 代 in 越高越熱:
            判 += "（偏熱）" if 差 > 0 else "（偏冷）"
        elif 判 != "—" and 代 == "UNRATE":
            判 += "（偏冷）" if 差 > 0 else "（偏熱）"
        列們.append({"數據": 名, "期間": f"{v.index[-1]:%Y/%m}", "公布值": 最新, "前一期": float(v.iloc[-2]) if len(v) > 1 else np.nan,
                   "預期": 預, "比預期": 判})
    return pd.DataFrame(列們)


# ---------- 31 重大數據公布後台股反應 ----------
FOMC日 = [  # 美國時間決議日（台股反應在隔天）
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]


def 非農日(起, 迄):
    """非農就業大多在每月第一個週五公布（少數月份延到第二個週五，這裡用近似）。"""
    日們 = []
    for m in pd.period_range(起, 迄, freq="M"):
        d = m.to_timestamp()
        日們.append(d + pd.Timedelta(days=(4 - d.weekday()) % 7))
    return 日們


def 事件反應(K, 事件日們):
    """K＝加權日 K（date, open, close）。事件在美國晚上公布，台股反應＝事件日之後第一個台股交易日。
    回傳 dict：次數、平均漲跌%、上漲機率、平均波動%（絕對值）、平常日平均波動%、明細。"""
    K = K.sort_values("date").reset_index(drop=True)
    K["報酬"] = K["close"].pct_change() * 100
    平常 = K["報酬"].abs().mean()
    列們 = []
    for d in pd.to_datetime(事件日們):
        後 = K[K["date"] > d]
        if 後.empty or d < K["date"].iloc[0]:
            continue
        r = 後.iloc[0]
        列們.append({"事件日": d, "台股日": r["date"], "漲跌%": r["報酬"]})
    t = pd.DataFrame(列們).dropna()
    if t.empty:
        return None
    return {"次數": len(t), "平均%": t["漲跌%"].mean(), "上漲機率%": (t["漲跌%"] > 0).mean() * 100,
            "平均波動%": t["漲跌%"].abs().mean(), "平常波動%": 平常, "明細": t.sort_values("事件日", ascending=False)}


def 下一個大事(行事曆, 現在=None):
    """首頁倒數條：未來 7 天內最近的高影響事件（美國優先，同時間合併）。"""
    if 行事曆 is None or 行事曆.empty:
        return None
    現在 = 現在 or pd.Timestamp.now(tz="Asia/Taipei").tz_localize(None)
    t = 行事曆[(行事曆["impact"] == "High")].copy()
    t["時間"] = pd.to_datetime(t["date"] + " " + t["time"].fillna("00:00"), errors="coerce")
    t = t[(t["時間"] > 現在) & (t["時間"] <= 現在 + pd.Timedelta(days=7))].sort_values("時間")
    if t.empty:
        return None
    t["美"] = t["country"] != "USD"
    第一 = t.sort_values(["時間", "美"]).iloc[0]
    同時 = t[t["時間"] == 第一["時間"]]
    return {"時間": 第一["時間"], "事件們": 同時[["country", "title", "forecast"]].to_dict("records"),
            "剩": 第一["時間"] - 現在}


# ---------- 33 美股財報 → 台股隔日 ----------
def 財報反應(財報, 美, K):
    """財報＝us_earnings.csv（date, symbol, name, time 盤前／盤後）；美＝us_daily 寬表；K＝加權日 K。
    美股反應日：盤後公布看隔天、盤前看當天；台股反應＝美股反應日之後第一個台股交易日的加權漲跌。"""
    if 財報 is None or 美 is None or K is None:
        return pd.DataFrame()
    美報酬 = 美.pct_change(fill_method=None) * 100
    K = K.sort_values("date").assign(報酬=lambda d: d["close"].pct_change() * 100)
    列們 = []
    for _, x in 財報.iterrows():
        if x["name"] not in 美報酬:
            continue
        d = pd.Timestamp(x["date"])
        s = 美報酬[x["name"]].dropna()
        後 = s[s.index > d] if x.get("time") == "盤後" else s[s.index >= d]
        if 後.empty:
            continue
        美日 = 後.index[0]
        台 = K[K["date"] > 美日]
        列們.append({"財報日": d, "公司": x["name"], "時段": x.get("time"), "美股反應日": 美日, "美股漲跌%": float(後.iloc[0]),
                   "台股日": 台["date"].iloc[0] if len(台) else pd.NaT,
                   "加權隔日%": float(台["報酬"].iloc[0]) if len(台) else np.nan,
                   "費半同日%": float(美報酬["費城半導體"].get(美日, np.nan)) if "費城半導體" in 美報酬 else np.nan})
    return pd.DataFrame(列們).sort_values("財報日", ascending=False) if 列們 else pd.DataFrame()


# ---------- 34 季節與事件回測 ----------
def 季節統計(K):
    """加權指數：各月份、星期、結算週的平均漲跌與上漲機率。"""
    K = K.sort_values("date").set_index("date")["close"]
    月 = K.resample("ME").last().pct_change().dropna() * 100
    月表 = 月.groupby(月.index.month).agg(["mean", lambda s: (s > 0).mean() * 100, "count"])
    月表.columns = ["平均%", "上漲機率%", "次數"]
    月表.index = [f"{m} 月" for m in 月表.index]
    日 = K.pct_change().dropna() * 100
    週 = 日.groupby(日.index.weekday).agg(["mean", lambda s: (s > 0).mean() * 100, "count"])
    週.columns = ["平均%", "上漲機率%", "次數"]
    週.index = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"][: len(週)]
    # 結算週：每月第三個週三所在那一週
    def 是結算週(d):
        一 = pd.Timestamp(d.year, d.month, 1)
        三 = 一 + pd.Timedelta(days=(2 - 一.weekday()) % 7 + 14)
        return 三 - pd.Timedelta(days=三.weekday()) <= d <= 三 + pd.Timedelta(days=4 - 三.weekday())
    結 = pd.Series([是結算週(d) for d in 日.index], index=日.index)
    結算 = pd.DataFrame({"平均%": [日[結].mean(), 日[~結].mean()], "上漲機率%": [(日[結] > 0).mean() * 100, (日[~結] > 0).mean() * 100],
                       "次數": [int(結.sum()), int((~結).sum())]}, index=["結算週", "其他週"])
    return 月表.round(2), 週.round(2), 結算.round(2)


# ---------- 35 多波段回檔尺＋等幅測距 ----------
def 轉折點(K, 門檻=0.05):
    """ZigZag：用收盤價找漲跌超過 門檻 的轉折日，價格取那天的最高／最低價。
    回傳 [(日期, 價格, '高'/'低')]，最後一個是還在進行中的波段端點。"""
    收, 高, 低, 日 = K["close"].values, K["high"].values, K["low"].values, K["date"].values
    點們 = []
    方向, 極日 = 0, 0
    for i in range(1, len(K)):
        if 方向 == 0:
            方向 = 1 if 收[i] >= 收[0] else -1
            極日 = i if abs(收[i] - 收[0]) > 0 else 0
            continue
        if 方向 > 0:
            if 收[i] > 收[極日]:
                極日 = i
            elif 收[i] < 收[極日] * (1 - 門檻):
                點們.append((日[極日], float(高[極日]), "高"))
                方向, 極日 = -1, i
        else:
            if 收[i] < 收[極日]:
                極日 = i
            elif 收[i] > 收[極日] * (1 + 門檻):
                點們.append((日[極日], float(低[極日]), "低"))
                方向, 極日 = 1, i
    點們.append((日[極日], float(高[極日] if 方向 > 0 else 低[極日]), "高" if 方向 > 0 else "低"))
    return [(pd.Timestamp(d), p, k) for d, p, k in 點們]


def 回檔尺(K, 門檻=0.05, 小門檻=0.02):
    """最近一段完成的主要波段（門檻 5%）的 0.382／0.5／0.618 回檔價位；
    等幅測距用小波段（2%）的 A→B→C：下跌時目標＝C −（A − B）（點數）或 C ×（B ÷ A）（百分比），上漲相反。"""
    if K is None or len(K) < 60:
        return None
    近 = K.tail(500).reset_index(drop=True)
    點 = 轉折點(近, 門檻)
    if len(點) < 3:
        return None
    (起日, 起價, 起型), (止日, 止價, 止型) = 點[-3], 點[-2]
    幅 = 止價 - 起價
    結果 = {"起": (起日, 起價, 起型), "止": (止日, 止價, 止型), "現價": float(K["close"].iloc[-1]),
          "回檔": {f"{r:g}": 止價 - 幅 * r for r in (0.382, 0.5, 0.618)},
          "方向": "上漲波段的回檔" if 幅 > 0 else "下跌波段的反彈", "已回%": float((止價 - K["close"].iloc[-1]) / 幅 * 100)}
    小 = [x for x in 轉折點(近, 小門檻) if x[0] > 止日]
    if len(小) >= 3:  # A＝主波段終點，B＝之後第一個小轉折，C＝再下一個（第三個是進行中的端點）
        (B日, B, _), (C日, C, _) = 小[0], 小[1]
        A = 止價
        點數, 百分比 = C - (A - B), C * B / A
        結果["等幅"] = {"A": (止日, A), "B": (B日, B), "C": (C日, C), "點數目標": 點數, "百分比目標": 百分比,
                      "型態": "下跌" if 幅 > 0 else "上漲",
                      "已達成": (結果["現價"] <= max(點數, 百分比)) if 幅 > 0 else (結果["現價"] >= min(點數, 百分比))}
    return 結果


# ---------- 36 低檔背離 ----------
def 低檔背離(K, 天數=60):
    """最近 天數 天內兩個低點：價格第二個低點更低，但 RSI 第二個低點更高 → 底背離（賣壓減弱）。高檔頂背離相反。"""
    if K is None or len(K) < 天數 + 20:
        return None
    s = K.set_index("date")["close"]
    變 = s.diff()
    漲 = 變.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    跌 = (-變.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + 漲 / 跌)
    近 = s.tail(天數)
    低們 = [i for i in range(2, len(近) - 2) if 近.iloc[i] == 近.iloc[i - 2:i + 3].min()]
    高們 = [i for i in range(2, len(近) - 2) if 近.iloc[i] == 近.iloc[i - 2:i + 3].max()]
    結果 = []
    if len(低們) >= 2:
        a, b = 低們[-2], 低們[-1]
        if 近.iloc[b] < 近.iloc[a] and rsi.loc[近.index[b]] > rsi.loc[近.index[a]] + 2 and len(近) - b <= 15:
            結果.append({"型態": "底背離", "前低": (近.index[a], float(近.iloc[a]), float(rsi.loc[近.index[a]])),
                       "後低": (近.index[b], float(近.iloc[b]), float(rsi.loc[近.index[b]])),
                       "說明": "價格破底但 RSI 沒破底：賣壓減弱，常是止跌前兆；要等站回前一個高點才算確認"})
    if len(高們) >= 2:
        a, b = 高們[-2], 高們[-1]
        if 近.iloc[b] > 近.iloc[a] and rsi.loc[近.index[b]] < rsi.loc[近.index[a]] - 2 and len(近) - b <= 15:
            結果.append({"型態": "頂背離", "前低": (近.index[a], float(近.iloc[a]), float(rsi.loc[近.index[a]])),
                       "後低": (近.index[b], float(近.iloc[b]), float(rsi.loc[近.index[b]])),
                       "說明": "價格創高但 RSI 沒創高：追價力道變弱，要提防回檔"})
    return 結果


# ---------- 37 劇本條件樹 ----------
def 劇本樹(現價, 支撐們, 壓力們):
    """支撐們、壓力們：[(名稱, 價位)] 由近到遠。回傳兩條分支的文字（守住／跌破）。"""
    支 = sorted([x for x in 支撐們 if x[1] < 現價], key=lambda x: -x[1])[:3]
    壓 = sorted([x for x in 壓力們 if x[1] > 現價], key=lambda x: x[1])[:3]
    if not 支 or not 壓:
        return None
    s1 = 支[0]
    多 = [f"守住 {s1[0]} {s1[1]:,.0f}"] + [f"站上 {n} {p:,.0f} → 下一關看" for n, p in 壓[:1]] + \
         ([f"{壓[1][0]} {壓[1][1]:,.0f}"] if len(壓) > 1 else ["前高"])
    空 = [f"跌破 {s1[0]} {s1[1]:,.0f}"] + ([f"→ 先看 {支[1][0]} {支[1][1]:,.0f}"] if len(支) > 1 else ["→ 找下一個支撐"]) + \
         ([f"再破就看 {支[2][0]} {支[2][1]:,.0f}"] if len(支) > 2 else [])
    return {"現價": 現價, "偏多": 多, "偏空": 空, "關鍵": s1}


# ---------- 27 補充：費半本身的回撤（長期資料 data/sox_long.csv） ----------
def 讀取費半長線():
    f = 資料夾 / "sox_long.csv"
    if not f.exists():
        return None
    t = pd.read_csv(f, parse_dates=["date"])
    return t.pivot_table(index="date", columns="symbol", values="close").sort_index()


def 費半回撤(長, 門檻=-20.0, 重置=-5.0, 往後=(20, 60)):
    """費半距歷史高點的回撤，以及過去「第一次跌破 門檻%」那天之後 20／60 個交易日的報酬。
    回撤回到 重置% 以內才算新的一次，避免同一段大跌被算很多次。"""
    if 長 is None or "^SOX" not in 長:
        return None
    s = 長["^SOX"].dropna()
    if len(s) < 300:
        return None
    撤 = (s / s.cummax() - 1) * 100
    列們, 可觸發 = [], True
    for i, (d, v) in enumerate(撤.items()):
        if v > 重置:
            可觸發 = True
        elif v <= 門檻 and 可觸發:
            可觸發 = False
            列 = {"跌破日": d, "當時回撤%": float(v)}
            for n in 往後:
                列[f"之後{n}日%"] = float((s.iloc[i + n] / s.iloc[i] - 1) * 100) if i + n < len(s) else np.nan
            段 = 撤.iloc[i:]
            回 = 段[段 > 重置]
            底 = 段.loc[: 回.index[0]] if len(回) else 段
            列["該段最深%"] = float(底.min())
            列們.append(列)
    明細 = pd.DataFrame(列們).sort_values("跌破日", ascending=False) if 列們 else pd.DataFrame()
    return {"最新": float(s.iloc[-1]), "日期": s.index[-1], "高點": float(s.cummax().iloc[-1]),
            "高點日": s.idxmax(), "回撤%": float(撤.iloc[-1]), "門檻": 門檻, "明細": 明細,
            "起": s.index[0]}


# ---------- 34 補充：自訂日期區間回測（例如水逆、選舉） ----------
水逆區間 = [("2021-01-30", "2021-02-21"), ("2021-05-29", "2021-06-22"), ("2021-09-27", "2021-10-18"),
          ("2022-01-14", "2022-02-04"), ("2022-05-10", "2022-06-03"), ("2022-09-09", "2022-10-02"),
          ("2022-12-29", "2023-01-18"), ("2023-04-21", "2023-05-15"), ("2023-08-23", "2023-09-15"),
          ("2023-12-13", "2024-01-01"), ("2024-04-01", "2024-04-25"), ("2024-08-05", "2024-08-28"),
          ("2024-11-25", "2024-12-15"), ("2025-03-15", "2025-04-07"), ("2025-07-18", "2025-08-11"),
          ("2025-11-09", "2025-11-29"), ("2026-02-26", "2026-03-20"), ("2026-06-29", "2026-07-23"),
          ("2026-10-24", "2026-11-13")]


def 解析區間(文字):
    """每行一段「起~迄」（也接受「起 迄」「起,迄」），日期格式 YYYY-MM-DD 或 YYYY/MM/DD。回傳 [(起, 迄)]，看不懂的行略過。"""
    import re
    區們 = []
    for 行 in str(文字).splitlines():
        日們 = re.findall(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", 行)
        if len(日們) >= 2:
            起, 迄 = (pd.Timestamp(x.replace("/", "-")) for x in 日們[:2])
            if 起 <= 迄:
                區們.append((起, 迄))
    return 區們


def 區間統計(K, 區們):
    """加權指數在這些日期區間「裡面」和「外面」每天的平均漲跌、上漲機率，加上每一段的累積漲跌。
    t 值絕對值小於 2 通常代表差異可能只是運氣。"""
    c = K.sort_values("date").set_index("date")["close"]
    r = c.pct_change().dropna() * 100
    內 = pd.Series(False, index=r.index)
    段們 = []
    for 起, 迄 in 區們:
        遮 = (r.index >= 起) & (r.index <= 迄)
        內 |= 遮
        前 = c[c.index < 起]
        段 = c[(c.index >= 起) & (c.index <= 迄)]
        if len(前) and len(段):
            段們.append({"起": 起, "迄": 迄, "交易日": int(遮.sum()), "期間漲跌%": float((段.iloc[-1] / 前.iloc[-1] - 1) * 100),
                       "期間最大跌幅%": float((段.min() / 前.iloc[-1] - 1) * 100), "進行中": bool(迄 > c.index[-1])})
    a, b = r[內], r[~內]
    if len(a) < 5 or len(b) < 5:
        return None
    t = (a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b))
    摘要 = pd.DataFrame({"天數": [len(a), len(b)], "平均%": [a.mean(), b.mean()], "上漲機率%": [(a > 0).mean() * 100, (b > 0).mean() * 100],
                       "波動%": [a.std(), b.std()]}, index=["區間內", "其他日子"]).round(3)
    段表 = pd.DataFrame(段們)
    return {"摘要": 摘要, "t值": float(t), "段": 段表,
            "漲段": int((段表["期間漲跌%"] > 0).sum()) if len(段表) else 0, "跌段": int((段表["期間漲跌%"] <= 0).sum()) if len(段表) else 0}


# ---------- 12 補充：夜盤三大法人交易口數（data/futures_night.csv） ----------
def 讀取夜盤法人():
    f = 資料夾 / "futures_night.csv"
    return pd.read_csv(f, parse_dates=["date"]) if f.exists() else None
