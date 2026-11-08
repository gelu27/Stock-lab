# 順勢做多選股引擎：RS 相對強弱等級、均線多頭排列、VCP 收斂後帶量突破、法人連買、交易計畫、訊號回測
# 只做「規則訊號＋歷史統計」，不承諾報酬；每個訊號都附過去出現後的勝率與最大回撤。
import json
from pathlib import Path

import numpy as np
import pandas as pd

資料夾 = Path(__file__).parent / "data"
回測檔 = 資料夾 / "momentum_backtest.json"

# 訊號名稱 → 白話說明（網站與回測共用）
訊號說明 = {
    "多頭排列": "股價站上 20／50／200 日線，且 50 日線在 200 日線上方（長中短期趨勢都向上）",
    "RS強勢": "RS 等級 ≥ 85：近一年漲幅贏過全市場 85% 的股票",
    "VCP突破": "近 10 日波動比近 50 日明顯收斂後，今天收盤突破前 20 日高點，且成交量 ≥ 前 5 日均量 2 倍",
    "領頭羊": "大盤還在回檔（距 60 日高點 3% 以上）時，這檔已經回到 60 日新高附近（2% 內）且 RS ≥ 85",
    "法人連買": "外資或投信連續買超 3 天以上，且股價在多頭排列",
    "強勢突破": "多頭排列＋RS ≥ 85＋VCP 帶量突破，三個條件同時成立（最嚴格）",
}


def _rs分數(價):
    """IBD 式加權報酬：近 3 個月占 40%、其餘三季各 20%。價＝依日期排序的還原價 Series（同一檔）。"""
    r = lambda n: 價 / 價.shift(n) - 1
    分 = 0.4 * r(63) + 0.2 * r(126) + 0.2 * r(189) + 0.2 * r(252)
    短 = 0.4 * r(63) + 0.6 * r(126)  # 上市不滿一年：用半年資料補
    return 分.fillna(短)


def 加上動能欄位(t):
    """t：計算指標() 的結果（多檔多日）。回傳加上 MA50、MA200、ATR14、RS分數、量倍數、收縮、前高等欄位的新表。
    均線用還原價算，再換回原始股價（除權息不會造成假跌破）。"""
    t = t.sort_values(["代號", "date"]).copy()
    群 = t.groupby("代號", sort=False)
    比 = t["收盤"] / t["還原價"].replace(0, np.nan)
    for n in (10, 20, 50, 200):  # 計算指標() 的 MA 是還原價刻度，這裡全部換回原始股價刻度
        t[f"MA{n}"] = 群["還原價"].transform(lambda s, n=n: s.rolling(n, min_periods=n).mean()) * 比
    前收 = 群["收盤"].shift()
    真實波幅 = pd.concat([t["high"] - t["low"], (t["high"] - 前收).abs(), (t["low"] - 前收).abs()], axis=1).max(axis=1)
    t["_TR"] = 真實波幅 / t["收盤"].replace(0, np.nan)  # 用比例，除權息不影響
    群 = t.groupby("代號", sort=False)
    t["ATR14"] = 群["_TR"].transform(lambda s: s.rolling(14, min_periods=10).mean()) * t["收盤"]
    t["波動10"] = 群["_TR"].transform(lambda s: s.rolling(10, min_periods=8).mean())
    t["波動50"] = 群["_TR"].transform(lambda s: s.rolling(50, min_periods=40).mean())
    t["前高20"] = 群["high"].transform(lambda s: s.rolling(20, min_periods=15).max().shift())
    t["高60"] = 群["還原價"].transform(lambda s: s.rolling(60, min_periods=40).max())
    t["前5均量"] = 群["volume"].transform(lambda s: s.rolling(5, min_periods=5).mean().shift())
    t["量倍數"] = t["volume"] / t["前5均量"].replace(0, np.nan)
    t["RS分數"] = 群["還原價"].transform(_rs分數)
    t["RS"] = (t.groupby("date")["RS分數"].rank(pct=True) * 98 + 1).round()
    t["收縮"] = 群["波動10"].shift() < 0.75 * 群["波動50"].shift()  # 突破前一天的波動已經收斂
    return t.drop(columns=["_TR"])


def 訊號遮罩(t, 大盤回檔=None):
    """回傳 {訊號名: 布林 Series}。大盤回檔：與 t 同索引的布林 Series（加權距 60 日高點 ≥ 3%）。"""
    多 = (t["收盤"] > t["MA20"]) & (t["收盤"] > t["MA50"]) & (t["收盤"] > t["MA200"]) & (t["MA50"] > t["MA200"])
    強 = t["RS"] >= 85
    突 = t["收縮"].fillna(False).astype(bool) & (t["收盤"] > t["前高20"]) & (t["量倍數"] >= 2)
    連 = (t.get("外資連買", 0) >= 3) | (t.get("投信連買", 0) >= 3)
    近高 = t["還原價"] >= 0.98 * t["高60"]
    遮 = {"多頭排列": 多, "RS強勢": 強, "VCP突破": 突, "法人連買": 連 & 多, "強勢突破": 多 & 強 & 突}
    if 大盤回檔 is not None:
        遮["領頭羊"] = 強 & 近高 & 大盤回檔
    return {k: v.fillna(False).astype(bool) for k, v in 遮.items()}


def 大盤回檔序列(加權, 日期們):
    """每個日期大盤是否在回檔（收盤距 60 日高點 ≥ 3%）。"""
    if 加權 is None or not len(加權):
        return pd.Series(False, index=日期們.index)
    w = 加權.sort_values("date").set_index("date")["close"]
    回 = (w / w.rolling(60, min_periods=20).max() - 1) <= -0.03
    return 日期們.map(回).fillna(False).astype(bool)


def 交易計畫(列, 壓力=None):
    """一檔股票的操盤計畫：買點（突破價）、停損、目標 1／2、風報比。列＝最新一天的動能欄位（Series）。
    停損＝max(買點 − 1.5×ATR, 突破當天 K 棒低點)；目標 1＝買點＋2R、目標 2＝買點＋3R（R＝買點−停損），
    有更近的壓力價就一併列出。"""
    收 = float(列["收盤"])
    atr = float(列.get("ATR14") or np.nan)
    前高 = float(列.get("前高20") or np.nan)
    if not np.isfinite(atr) or atr <= 0:
        return None
    已突破 = np.isfinite(前高) and 收 > 前高
    if not 已突破 and np.isfinite(前高) and 前高 > 收 * 1.1:
        return {"買點": None, "已突破": False, "狀態": f"離前 20 日高點 {前高:,.2f} 還有 {(前高 / 收 - 1) * 100:.0f}%，"
                "還不是突破買點，等重新整理出平台再看", "ATR": round(atr, 2)}
    買點 = round(收 if 已突破 or not np.isfinite(前高) else 前高 * 1.002, 2)  # 還沒突破：等站上前高再進
    停們 = {"1.5 倍 ATR": 買點 - 1.5 * atr}
    if 已突破:
        停們["突破紅 K 低點"] = float(列["low"])
    ma10 = float(列.get("MA10") or np.nan)
    停損 = max(v for v in 停們.values() if v < 買點) if any(v < 買點 for v in 停們.values()) else 買點 - 1.5 * atr
    依據 = next(k for k, v in 停們.items() if abs(v - 停損) < 1e-9)
    R = 買點 - 停損
    計畫 = {"買點": 買點, "已突破": bool(已突破), "停損": round(停損, 2), "停損依據": 依據, "每股風險": round(R, 2),
          "停損%": round(-R / 買點 * 100, 1), "目標1": round(買點 + 2 * R, 2), "目標2": round(買點 + 3 * R, 2),
          "10日線": round(ma10, 2) if np.isfinite(ma10) else None, "ATR": round(atr, 2)}
    if 壓力 is not None and np.isfinite(壓力) and 壓力 > 買點:
        計畫["前波壓力"] = round(float(壓力), 2)
        計畫["到壓力風報比"] = round((壓力 - 買點) / R, 1) if R > 0 else None
    return 計畫


# ---------- 回測 ----------
def 訊號統計(t, 遮, 天數們=(5, 20)):
    """t 要有 f5、f20（之後 N 日報酬）、低20（之後 20 日最低價相對進場的跌幅）。回傳每個訊號的統計列。"""
    列們 = []
    for 名, m in 遮.items():
        子 = t[m]
        if not len(子):
            列們.append({"訊號": 名, "次數": 0})
            continue
        列 = {"訊號": 名, "次數": int(len(子))}
        for n in 天數們:
            r = 子[f"f{n}"].dropna()
            列[f"{n}日勝率%"] = round(float((r > 0).mean() * 100), 1) if len(r) else None
            列[f"{n}日平均%"] = round(float(r.mean() * 100), 2) if len(r) else None
            if f"x{n}" in 子:
                x = 子[f"x{n}"].dropna()
                列[f"{n}日超額%"] = round(float(x.mean() * 100), 2) if len(x) else None
        d = 子["低20"].dropna()
        列["20日內平均最大回撤%"] = round(float(d.mean() * 100), 1) if len(d) else None
        列["20日內最大回撤%"] = round(float(d.min() * 100), 1) if len(d) else None
        列們.append(列)
    return 列們


def 計畫模擬(t, m, 停損ATR=1.5, 目標R=3, 最長天數=20):
    """照交易計畫卡操作的歷史結果：訊號當天收盤買進，停損＝買點 − 1.5×ATR，目標＝買點＋3R，最多抱 20 個交易日
    （用收盤價判斷，碰到哪個先算哪個，都沒碰到就第 20 天收盤出場）。回傳 達標率、停損率、平均 R、平均報酬。"""
    結果 = []
    價 = t["還原價"].to_numpy()
    碼 = t["代號"].to_numpy()
    atr比 = (t["ATR14"] / t["收盤"]).to_numpy()
    for i in np.flatnonzero(m.to_numpy()):
        進 = 價[i]
        if not np.isfinite(進) or not np.isfinite(atr比[i]) or atr比[i] <= 0:
            continue
        R = 停損ATR * atr比[i] * 進
        停, 標 = 進 - R, 進 + 目標R * R
        出, 類 = None, "到期"
        for j in range(i + 1, min(i + 1 + 最長天數, len(價))):
            if 碼[j] != 碼[i]:
                break
            if 價[j] <= 停:
                出, 類 = 價[j], "停損"
                break
            if 價[j] >= 標:
                出, 類 = 價[j], "達標"
                break
            出 = 價[j]
        if 出 is None:
            continue
        結果.append((類, (出 - 進) / R, 出 / 進 - 1))
    if not 結果:
        return None
    r = pd.DataFrame(結果, columns=["類", "R", "報酬"])
    return {"筆數": int(len(r)), "達標率%": round(float((r["類"] == "達標").mean() * 100), 1),
            "停損率%": round(float((r["類"] == "停損").mean() * 100), 1),
            "到期出場%": round(float((r["類"] == "到期").mean() * 100), 1),
            "賺錢比例%": round(float((r["報酬"] > 0).mean() * 100), 1),
            "平均R": round(float(r["R"].mean()), 2), "平均報酬%": round(float(r["報酬"].mean() * 100), 2)}


def 加上未來報酬(t):
    群 = t.groupby("代號", sort=False)["還原價"]
    for n in (5, 20):
        t[f"f{n}"] = 群.shift(-n) / t["還原價"] - 1
    # 之後 20 個交易日內最低點（用收盤還原價）相對進場價的跌幅
    t["低20"] = 群.transform(lambda s: s[::-1].rolling(20, min_periods=1).min()[::-1].shift(-1)) / t["還原價"] - 1
    return t


def 全市場回測(最少成交值億=0.5):
    """5 年全市場：每個訊號出現後 5／20 日勝率、平均報酬、超額報酬（扣同日全部樣本平均）、20 日內最大回撤。
    很吃記憶體，在 GitHub Actions 算好存 data/momentum_backtest.json。"""
    import engine
    t = engine.計算指標(engine.讀取資料庫())
    t = t[t["代號"].str.fullmatch(r"\d{4}") & (t["收盤"] > 0)]
    欄 = ["date", "代號", "open", "high", "low", "收盤", "還原價", "volume", "成交值億", "MA10", "MA20",
         "外資連買", "投信連買"]
    t = t[[c for c in 欄 if c in t.columns]].copy()
    engine.釋放記憶體()
    t = 加上動能欄位(t)
    t = 加上未來報酬(t)
    t["均額"] = t.groupby("代號", sort=False)["成交值億"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    t = t[(t["均額"] >= 最少成交值億) & t["MA200"].notna() & t["f20"].notna()]
    for n in (5, 20):
        t[f"x{n}"] = t[f"f{n}"] - t.groupby("date")[f"f{n}"].transform("mean")
    遮 = 訊號遮罩(t, 大盤回檔序列(engine.讀取加權指數(), t["date"]))
    基準 = 訊號統計(t, {"全部樣本": pd.Series(True, index=t.index)})[0]
    t = t.sort_values(["代號", "date"])
    計畫 = {k: 計畫模擬(t, 遮[k].reindex(t.index).fillna(False)) for k in ("VCP突破", "強勢突破", "領頭羊")}
    return {"計畫模擬": 計畫, "計算日": f"{pd.Timestamp.now():%Y-%m-%d}", "起": f"{t['date'].min():%Y-%m-%d}",
            "迄": f"{t['date'].max():%Y-%m-%d}", "樣本": int(len(t)), "基準": 基準, "訊號": 訊號統計(t, 遮)}


def 更新全市場回測(強制=False, 間隔天數=25):
    """GitHub Actions 每天呼叫；距離上次超過 間隔天數 才重算。"""
    if 回測檔.exists() and not 強制:
        舊 = json.loads(回測檔.read_text())
        if (pd.Timestamp.now() - pd.Timestamp(舊.get("計算日", "2000-01-01"))).days < 間隔天數:
            print("順勢做多回測：還不用重算")
            return
    結果 = 全市場回測()
    回測檔.write_text(json.dumps(結果, ensure_ascii=False, indent=1))
    print(f"順勢做多回測：已更新 {len(結果['訊號'])} 個訊號，樣本 {結果['樣本']:,}")


def 讀取全市場回測():
    try:
        return json.loads(回測檔.read_text())
    except Exception:
        return None


def 個股回測(全史, 加權=None, 年數=2):
    """這一檔過去 年數 年，每個訊號出現幾次、之後 5／20 日勝率、平均報酬、20 日內最大回撤。
    全史＝個股全史()（計算指標後的單一檔 5 年資料）。指標要暖身 252 天，所以讀全部再取最後 年數 年統計。"""
    if 全史 is None or len(全史) < 260:
        return None
    t = 加上動能欄位(全史)
    t = 加上未來報酬(t)
    t["RS"] = np.nan  # 單一檔無法算全市場百分位，RS 條件用「近一年報酬 > 大盤近一年報酬 + 20 個百分點」近似
    if 加權 is not None and len(加權):
        w = 加權.sort_values("date").set_index("date")["close"]
        大一年 = t["date"].map(w / w.shift(250) - 1)
        自一年 = t["還原價"] / t["還原價"].shift(250) - 1
        t["RS"] = np.where((自一年 - 大一年) >= 0.2, 90, 50)
    t = t[t["date"] >= t["date"].max() - pd.DateOffset(years=年數)]
    遮 = 訊號遮罩(t, 大盤回檔序列(加權, t["date"]))
    return pd.DataFrame(訊號統計(t, 遮))


def 今日訊號(t, 最新日, 加權=None):
    """全市場最新一天的動能表（每檔一列）與各訊號遮罩。t＝加上動能欄位() 的結果。"""
    今 = t[t["date"] == 最新日].copy()
    return 今, 訊號遮罩(今, 大盤回檔序列(加權, 今["date"]))
