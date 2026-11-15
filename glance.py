"""一眼判斷（2026-11 參考台股 App 介面改版）：清單表情與徽章、本益比位階刻度、個股重點卡三格、風險框、
成長／價值檢查表、三方意見、持股「最該注意」排序、籌碼集中度、PEG。

跟 App 不同的地方：每個符號都盡量附上「這條規則回測準不準」（data/rule_health.json、score_backtest.json），
規則失效就不當成徽章顯示。純計算、不碰 Streamlit，網站與 LINE 共用。"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

資料夾 = Path(__file__).parent / "data"
位階檔 = 資料夾 / "pe_band.csv"
期貨標的檔 = 資料夾 / "stock_futures.csv"


def _數(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return np.nan
    return v if np.isfinite(v) else np.nan


# ========== 規則可信度（N1） ==========
def 讀規則體檢():
    """{規則名: {"判定", "超額%", "次數", "說明"}}，最新一次規則體檢；沒有檔案回傳 {}。"""
    try:
        歷史 = json.loads((資料夾 / "rule_health.json").read_text(encoding="utf-8"))["歷史"]
        return {x["規則"]: x for x in 歷史[-1]["規則"]}
    except Exception:
        return {}


def 可信度(體檢, 規則):
    """(圖示, 說明)：🟢 有效、⚪ 沒有優勢、🔴 反向、空字串＝沒驗證過。"""
    x = 體檢.get(規則)
    if not x:
        return "", ""
    判 = x.get("判定")
    圖 = {"有效": "🟢", "沒有優勢": "⚪", "反向": "🔴"}.get(判, "")
    次 = x.get("次數")
    超 = x.get("超額%")
    尾 = f"，{x.get('天數', 20)} 日平均超額 {超:+.2f}%" if isinstance(超, (int, float)) and 次 else ""
    return 圖, f"回測{判}（{次:,} 次{尾}）" if 次 else f"回測{判}"


def 評分回測摘要():
    """評分五分組：最高、最低 1/5 的 20 日平均超額（%），給表情的可信度說明。"""
    try:
        s = json.loads((資料夾 / "score_backtest.json").read_text(encoding="utf-8"))
        組 = {k: (v[-1]["超額"], v[0]["超額"]) for k, v in s["五分組"].items()}
        return {"起": s.get("起"), "迄": s.get("迄"), "組": 組, "相關": s.get("相關", {})}
    except Exception:
        return None


# ========== 本益比位階（A3、N3） ==========
分位們 = (0.1, 0.25, 0.5, 0.75, 0.9)
分位欄 = [f"pe_p{int(q * 100)}" for q in 分位們]


def 計算本益比位階(價格, 最少天數=120):
    """價格：code、date、pe（5 年每日）。回傳以代號為索引的本益比 10／25／50／75／90 百分位與天數。
    本益比 ≤ 0（虧損）或 > 300（獲利極小、數字失真）不算。"""
    t = 價格[(價格["pe"] > 0) & (價格["pe"] <= 300)][["code", "date", "pe"]]
    g = t.groupby("code")["pe"]
    out = g.quantile(list(分位們)).unstack()
    out.columns = 分位欄
    out["pe_n"] = g.size()
    out["起"] = t.groupby("code")["date"].min().dt.strftime("%Y-%m-%d")
    out = out[out["pe_n"] >= 最少天數]
    out.index.name = "code"
    return out.round(2)


def 更新本益比位階():
    """GitHub Actions 每天跑：讀 5 年每日行情（已修正分割），寫 data/pe_band.csv。"""
    import engine
    t = engine._讀每日檔("prices")
    if t is None:
        return
    t = engine.修正分割估值(t.sort_values(["code", "date"], ignore_index=True))
    out = 計算本益比位階(t)
    out.to_csv(位階檔, encoding="utf-8")
    print(f"本益比位階：{len(out)} 檔")


def 讀本益比位階():
    if not 位階檔.exists():
        return pd.DataFrame(columns=分位欄)
    t = pd.read_csv(位階檔, dtype={"code": str}).set_index("code")
    return t


def 位階百分位(pe, 列):
    """本益比 pe 在這檔過去 5 年的大約百分位（0～100）：用 10／25／50／75／90 分位線性內插，兩端外插到 0、100。"""
    pe = _數(pe)
    if not pe > 0 or 列 is None:
        return np.nan
    p = [_數(列.get(c)) for c in 分位欄]
    if any(not v > 0 for v in p) or not all(a <= b for a, b in zip(p, p[1:])):
        return np.nan
    xs = [p[0] * 0.6] + p + [p[-1] * 1.5]
    ys = [0, 10, 25, 50, 75, 90, 100]
    return float(np.clip(np.interp(pe, xs, ys), 0, 100))


def 估值標籤(百分位):
    if pd.isna(百分位):
        return "—"
    if 百分位 < 10:
        return "特價"
    if 百分位 < 30:
        return "便宜"
    if 百分位 <= 70:
        return "合理"
    if 百分位 <= 90:
        return "偏貴"
    return "昂貴"


估值色 = {"特價": "#00D68F", "便宜": "#5BE7A9", "合理": "#BDBDBD", "偏貴": "#FFB020", "昂貴": "#FF3B5C", "—": "#6B6B6B"}


def 估值價位(eps, 列):
    """EPS × 過去 5 年本益比分位 → 特價／便宜／合理／偏貴／昂貴的價格（list of (名, 價, 倍數)）。"""
    eps = _數(eps)
    if not eps > 0 or 列 is None:
        return []
    名們 = ("特價", "便宜", "合理", "偏貴", "昂貴")
    out = []
    for 名, c in zip(名們, 分位欄):
        倍 = _數(列.get(c))
        if 倍 > 0:
            out.append((名, round(eps * 倍, 2), round(倍, 1)))
    return out


def 估值位階表(今日, 位階=None):
    """每檔：近四季本益比位階、預估本益比位階（N3：用券商預估 EPS，成長股不會永遠顯示昂貴）。"""
    位階 = 讀本益比位階() if 位階 is None else 位階
    t = 今日[["代號", "收盤", "本益比"] + [c for c in ("預估本益比", "明年預估本益比", "預估年度") if c in 今日.columns]].copy()
    t = t.set_index("代號")
    今年 = pd.Timestamp.now().year
    下半年 = pd.Timestamp.now().month >= 7
    結果 = {}
    for 代號, r in t.iterrows():
        列 = 位階.loc[代號] if 代號 in 位階.index else None
        現 = 位階百分位(r.get("本益比"), 列)
        預pe = r.get("預估本益比")
        預名 = "今年"
        年 = _數(r.get("預估年度"))
        if 下半年 and _數(r.get("明年預估本益比")) > 0 and (pd.isna(年) or 年 <= 今年):
            預pe, 預名 = r.get("明年預估本益比"), "明年"
        預 = 位階百分位(預pe, 列)
        結果[代號] = {"位階": 現, "估值": 估值標籤(現), "預估位階": 預, "預估估值": 估值標籤(預),
                    "預估用": 預名 if pd.notna(預) else ""}
    return pd.DataFrame.from_dict(結果, orient="index")


# ========== 清單徽章（A1、N1、N7） ==========
def 連續配息年數(股利):
    """每檔連續配現金股利的年數（從去年往回數；今年已配也算一年）。資料只有近幾年，最多就是資料年數。"""
    if 股利 is None or not len(股利):
        return {}
    t = 股利.copy()
    t["年"] = pd.to_datetime(t["date"], errors="coerce").dt.year
    現金 = pd.to_numeric(t.get("cash"), errors="coerce")
    t = t[t["type"].astype(str).str.contains("息") | (現金 > 0)]
    今年 = pd.Timestamp.now().year
    年們 = t.groupby("code")["年"].apply(set)
    結果 = {}
    for 代號, s in 年們.items():
        n, 年 = (1, 今年 - 1) if 今年 in s else (0, 今年 - 1)
        while 年 in s:
            n += 1
            年 -= 1
        結果[str(代號)] = n
    return 結果


def 配息資料起年(股利):
    try:
        return int(pd.to_datetime(股利["date"], errors="coerce").dt.year.min())
    except Exception:
        return None


def 連續獲利季數(損益):
    """每檔最近連續幾季單季 EPS > 0（income.csv 的 eps 是單季）。"""
    if 損益 is None or not len(損益):
        return {}
    t = 損益[["code", "quarter", "eps"]].dropna().sort_values(["code", "quarter"])
    結果 = {}
    for 代號, g in t.groupby("code"):
        n = 0
        for v in g["eps"].to_numpy()[::-1]:
            if v > 0:
                n += 1
            else:
                break
        結果[str(代號)] = n
    return 結果


def 讀期貨標的():
    if not 期貨標的檔.exists():
        return set()
    try:
        return set(pd.read_csv(期貨標的檔, dtype={"code": str})["code"])
    except Exception:
        return set()


def 表情(基本分):
    """表情看「基本面分數」：5 年回測只有基本面分數有效（IC t 值約 4），總分、技術面都沒有優勢。"""
    v = _數(基本分)
    if pd.isna(v):
        return "·"
    return "😀" if v >= 58 else ("😟" if v <= 42 else "😐")


順勢徽章 = {"領頭羊": "領頭", "法人連買": "法買", "RS強勢": "RS強", "多頭排列": "多頭", "強勢突破": "突破", "VCP突破": "VCP"}


def 徽章表(代號們, 今日, 分數=None, 動能=None, 警示=None, 配息=None, 獲利=None, 期貨=None, 位階表=None, 體檢=None, 配息上限=None):
    """回傳以代號為索引：表情、徽章（字串）、估值、位階、預估估值、預估位階、徽章說明（list）。
    徽章：
      連配N＝連續 N 年配息（N ≥ 3 才標，＋＝資料起點以前可能也有配）；賺＝近 8 季都賺錢；期＝有個股期貨；營收高＝月營收創新高；
      順勢訊號（領頭、法買、RS強、多頭、突破）只在規則體檢判定「有效」時才標，失效自動拿掉；
      ⚠處置／⚠注意；融資危＝個股融資維持率 < 140%。"""
    代號們 = [str(c) for c in 代號們]
    今 = 今日.set_index("代號").reindex(代號們)
    體檢 = 讀規則體檢() if 體檢 is None else 體檢
    配息 = 配息 or {}
    獲利 = 獲利 or {}
    期貨 = 期貨 if 期貨 is not None else 讀期貨標的()
    警示 = 警示 or {}
    估 = 估值位階表(今.reset_index(), 位階表) if len(今) else pd.DataFrame()
    有效訊號 = [k for k in 順勢徽章 if 體檢.get(k, {}).get("判定") == "有效"] if 體檢 else list(順勢徽章)
    列們 = {}
    for c in 代號們:
        r = 今.loc[c] if c in 今.index else pd.Series(dtype=object)
        章 = []
        n = 配息.get(c, 0)
        if n >= 3:
            章.append(f"連配{n}" + ("+" if 配息上限 and n >= 配息上限 else ""))
        if 獲利.get(c, 0) >= 8:
            章.append("賺")
        if c in 期貨:
            章.append("期")
        if bool(r.get("營收創新高")) and r.get("營收創新高") is not np.nan:
            章.append("營收高")
        if 動能 is not None and c in 動能.index:
            for k in 有效訊號:
                if k in 動能.columns and bool(動能.at[c, k]):
                    章.append(順勢徽章[k])
        警 = 警示.get(c, "")
        if 警:
            章.append("⚠處置" if "處置" in 警 else "⚠注意")
        if _數(r.get("融資維持率")) < 140:
            章.append("融資危")
        基 = 分數.at[c, "基本"] if 分數 is not None and c in 分數.index and "基本" in 分數.columns else np.nan
        變 = 分數.at[c, "較昨日"] if 分數 is not None and c in 分數.index and "較昨日" in 分數.columns else np.nan
        箭 = "↑" if _數(變) >= 3 else ("↓" if _數(變) <= -3 else "")
        e = 估.loc[c] if c in 估.index else {}
        列們[c] = {"表情": 表情(基) + 箭, "徽章": " ".join(章), "估值": e.get("估值", "—"), "位階": e.get("位階", np.nan),
                 "預估估值": e.get("預估估值", "—"), "預估位階": e.get("預估位階", np.nan)}
    return pd.DataFrame.from_dict(列們, orient="index")


def 徽章圖例(體檢=None, 回測=None):
    """清單下面的一段說明（含可信度）。"""
    體檢 = 讀規則體檢() if 體檢 is None else 體檢
    回測 = 評分回測摘要() if 回測 is None else 回測
    表 = ""
    if 回測 and "基本" in 回測["組"]:
        高, 低 = 回測["組"]["基本"]
        表 = f"（{回測['起']}～{回測['迄']} 回測：基本面分數最高 1/5 的股票 20 日平均超額 {高:+.2f}%、最低 1/5 {低:+.2f}%）"
    句 = [f"表情＝基本面分數：😀 ≥ 58、😐 中性、😟 ≤ 42，↑↓＝總分比昨天變動 3 分以上{表}"]
    句.append("連配N＝連續 N 年配息（＋＝已到資料起點，實際可能更久）、賺＝近 8 季都賺錢、期＝有個股期貨、營收高＝月營收創新高、融資危＝融資維持率低於 140%")
    訊 = []
    for k, 短 in 順勢徽章.items():
        圖, 說 = 可信度(體檢, k)
        if 圖:
            訊.append(f"{短}{圖}")
    if 訊:
        句.append("順勢徽章只有回測「有效」才會出現：" + "、".join(訊) + "（🟢 有效、⚪ 沒有優勢、🔴 反向，每月自動體檢）")
    句.append("估值＝本益比在這檔過去 5 年的位置：特價 < 10%、便宜 < 30%、合理 30～70%、偏貴 ≤ 90%、昂貴 > 90%；預估＝改用券商預估 EPS")
    return "。".join(句) + "。"


# ========== 個股重點卡：短、中、長線三格（A4、A5、N2、N4） ==========
def _判(分):
    return "偏多" if 分 >= 2 else ("偏空" if 分 <= -2 else "中性")


def 三格判斷(r, 動能列=None, 位階=np.nan, 分數列=None, 體檢=None):
    """三個期間各自的看法與依據。依據＝(文字, +1/−1/0, 可信度圖示)。只用數字規則，不需要 AI。"""
    體檢 = 讀規則體檢() if 體檢 is None else 體檢
    g = lambda k: _數(r.get(k))
    比 = g("收盤") / g("還原價") if g("還原價") > 0 else 1
    ma = {n: g(f"MA{n}") * 比 for n in (5, 10, 20, 60)}
    收 = g("收盤")

    def 加(列, 文字, 向, 規則=None):
        列.append((文字, 向, 可信度(體檢, 規則)[0] if 規則 else ""))

    短 = []
    if ma[5] > 0 and ma[10] > 0:
        if 收 > ma[5] and 收 > ma[10]:
            加(短, "站上 5 日、10 日線", 1)
        elif 收 < ma[5] and 收 < ma[10]:
            加(短, "跌破 5 日、10 日線", -1)
    if pd.notna(g("5日漲幅")):
        if g("5日漲幅") >= 5:
            加(短, f"近 5 日漲 {g('5日漲幅'):.1f}%", 1)
        elif g("5日漲幅") <= -5:
            加(短, f"近 5 日跌 {abs(g('5日漲幅')):.1f}%", -1)
    if pd.notna(g("法人5日買超")) and g("法人5日買超") != 0:
        加(短, f"法人 5 日{'買' if g('法人5日買超') > 0 else '賣'}超 {abs(g('法人5日買超')):,.0f} 張", 1 if g("法人5日買超") > 0 else -1)
    if g("RSI") >= 80:
        加(短, f"RSI {g('RSI'):.0f} 過熱，追高風險大", -1)
    elif 0 < g("RSI") <= 20:
        加(短, f"RSI {g('RSI'):.0f} 超賣", 0)

    中 = []
    if ma[20] > 0 and ma[60] > 0:
        if 收 > ma[20] and 收 > ma[60]:
            加(中, "站上月線、季線", 1)
        elif 收 < ma[20] and 收 < ma[60]:
            加(中, "跌破月線、季線", -1)
    if all(ma[n] > 0 for n in (5, 10, 20, 60)):
        if ma[5] > ma[10] > ma[20] > ma[60]:
            加(中, "均線多頭排列（5>10>20>60）", 1, "均線多頭排列（5>10>20>60）")
        elif ma[5] < ma[10] < ma[20] < ma[60]:
            加(中, "均線空頭排列", -1, "均線空頭排列")
    if 動能列 is not None:
        if bool(動能列.get("法人連買")):
            加(中, "法人連買＋多頭", 1, "法人連買")
        if bool(動能列.get("RS強勢")):
            加(中, f"RS {_數(動能列.get('RS')):.0f}，強過 85% 的股票", 1, "RS強勢")
    if pd.notna(g("外資持股20日變化")) and abs(g("外資持股20日變化")) >= 1:
        加(中, f"外資持股 20 日{'增' if g('外資持股20日變化') > 0 else '減'} {abs(g('外資持股20日變化')):.1f} 個百分點",
          1 if g("外資持股20日變化") > 0 else -1)

    長 = []
    基 = _數(分數列.get("基本")) if 分數列 is not None else np.nan
    if pd.notna(基):
        if 基 >= 58:
            加(長, f"基本面分數 {基:.0f}", 1, "評分：基本")
        elif 基 <= 42:
            加(長, f"基本面分數 {基:.0f}", -1, "評分：基本")
    if pd.notna(g("營收年增率")):
        if g("營收年增率") >= 20:
            加(長, f"月營收年增 {g('營收年增率'):.0f}%", 1)
        elif g("營收年增率") <= -10:
            加(長, f"月營收年減 {abs(g('營收年增率')):.0f}%", -1)
    if pd.notna(位階):
        if 位階 < 30:
            加(長, f"本益比在 5 年的 {位階:.0f}% 位置，偏便宜", 1)
        elif 位階 > 90:
            加(長, f"本益比在 5 年的 {位階:.0f}% 位置，偏貴", -1)
    距 = g("距52週高點")
    if pd.notna(距) and 距 <= -30:
        圖 = 可信度(體檢, "距 52 週高點跌 > 30%")[0]
        長.append((f"距 52 週高點跌 {abs(距):.0f}%（回測：跌深之後常續跌，不是便宜訊號）", -1, 圖))
    if 收 > 0 and g("EPS") < 0:
        加(長, "最近一季虧損", -1)

    結果 = []
    for 名, 小, 項 in (("短線", "近 5 個交易日", 短), ("中線", "近 20～60 個交易日", 中), ("長線", "基本面與估值", 長)):
        分 = sum(x[1] for x in 項)
        結果.append({"期": 名, "說明": 小, "看法": _判(分), "依據": 項})
    return 結果


def 重點摘要(三格, 估值=None, 風險們=()):
    """一句話：三格看法＋估值＋最重要的風險。"""
    看 = {x["期"]: x["看法"] for x in 三格}
    句 = f"短線{看['短線']}、中線{看['中線']}、長線{看['長線']}"
    if 估值 and 估值 != "—":
        句 += f"；本益比位階{估值}"
    if 風險們:
        句 += f"；注意{風險們[0][1].split('：')[0]}"
    return 句 + "。"


def 風險清單(r, 警示文字="", 位階=np.nan, 停損=None):
    """[(等級, 文字)]：等級 高／中。處置注意、融資維持率、停損紀律、估值、營收衰退、當沖過熱、虧損。"""
    g = lambda k: _數(r.get(k))
    險 = []
    if 警示文字:
        險.append(("高", f"{'處置股' if '處置' in 警示文字 else '注意股'}：{警示文字}"))
    if g("融資維持率") < 140:
        險.append(("高", f"融資維持率 {g('融資維持率'):.0f}%，低於 140% 容易有斷頭賣壓"))
    elif g("融資維持率") < 160:
        險.append(("中", f"融資維持率 {g('融資維持率'):.0f}%，偏低"))
    if 停損 and 停損.get("建議") in ("減碼一半", "出清"):
        險.append(("高" if 停損["建議"] == "出清" else "中",
                  "停損紀律：" + ("收盤跌破 10 日線，紀律上應該出清" if 停損["建議"] == "出清" else "跌破 5 日線，紀律上先減碼一半")))
    if pd.notna(位階) and 位階 > 90:
        險.append(("中", f"估值：本益比在過去 5 年的 {位階:.0f}% 位置"))
    if g("營收年增率") <= -20:
        險.append(("中", f"營收衰退：月營收年減 {abs(g('營收年增率')):.0f}%"))
    if g("當沖比率") >= 40:
        險.append(("中", f"當沖過熱：當沖比率 {g('當沖比率'):.0f}%，股價容易暴漲暴跌"))
    if g("融資佔股本%") >= 15:
        險.append(("中", f"融資佔股本 {g('融資佔股本%'):.0f}%，散戶籌碼多"))
    if g("RSI") >= 85:
        險.append(("中", f"短線過熱：RSI {g('RSI'):.0f}"))
    return 險


def 最壞情境(收盤, 天數=20):
    """N4「看錯會怎樣」：過去 5 年任一天買進，之後 天數 日內最深跌幅的中位數與最差 1/4（%）。收盤＝依日期排序的 Series。"""
    c = pd.Series(收盤).dropna().astype(float).reset_index(drop=True)
    if len(c) < 天數 * 5:
        return None
    a = c.to_numpy()
    低 = pd.Series(a[::-1]).rolling(天數, min_periods=天數).min().to_numpy()[::-1]  # 含當天起往後 天數 日最低
    未來低 = np.r_[低[1:], np.nan]
    跌 = (未來低 / a - 1) * 100
    跌 = 跌[np.isfinite(跌)]
    if not len(跌):
        return None
    return {"中位數": round(float(np.median(跌)), 1), "差的1/4": round(float(np.percentile(跌, 25)), 1), "次數": int(len(跌))}


def 三方意見(評分看法=None, 券商=None, 影片=None, AI=None, 回饋=None, 總分=None):
    """N2：網站評分、券商共識、影片觀點、AI 報告各自偏多／偏空，加上一致或分歧，與各方過去命中率（只用彙總，不寫人名）。
    券商＝engine.券商共識() 結果；影片＝{"看多": n, "看空": n}；AI＝最新 AI 報告的看法字串；回饋＝data/feedback.json。"""
    回饋 = 回饋 or {}
    方們 = []
    if 評分看法:
        看 = "偏多" if "多" in str(評分看法) else ("偏空" if "空" in str(評分看法) else "中性")
        方們.append({"方": "網站評分", "看法": 看, "細節": f"總分 {_數(總分):.0f}" if pd.notna(_數(總分)) else str(評分看法),
                   "準度": "總分回測沒有優勢，基本面分數有效（見 07 評分）"})
    if 券商 and 券商.get("家數"):
        多, 空 = 券商.get("看多", 0), 券商.get("看空", 0)
        看 = "偏多" if 多 > 空 and 多 >= 券商["家數"] / 2 else ("偏空" if 空 > 多 else "中性")
        空間 = 券商.get("中位數空間%")
        細 = f"{券商['家數']} 家：看多 {多}／中性 {券商.get('中性', 0)}／看空 {空}" + (f"，目標價中位數距現價 {空間:+.1f}%" if pd.notna(_數(空間)) else "")
        券 = [v for v in (回饋.get("券商") or {}).values() if isinstance(v, dict)]
        報 = sum(v.get("報告數", 0) for v in 券)
        比例 = round(sum(v.get("看多比例%", 0) * v.get("報告數", 0) for v in 券) / 報) if 報 else None
        準 = f"券商報告 {比例}% 看多，命中率樣本累積中" if 比例 is not None else "命中率樣本累積中"
        方們.append({"方": "券商共識", "看法": 看, "細節": 細, "準度": 準})
    if 影片 and (影片.get("看多", 0) + 影片.get("看空", 0)):
        多, 空 = 影片.get("看多", 0), 影片.get("看空", 0)
        看 = "偏多" if 多 > 空 else ("偏空" if 空 > 多 else "中性")
        網 = [v for v in (回饋.get("網紅") or {}).values() if isinstance(v, dict)]
        到, 對 = sum(v.get("到期", 0) for v in 網), sum(v.get("說對", 0) for v in 網)
        超 = [v.get("平均超額%") for v in 網 if isinstance(v.get("平均超額%"), (int, float))]
        準 = (f"影片說法已到期 {到} 則、說對 {對 / 到 * 100:.0f}%" if 到 >= 5 else "命中率樣本累積中") + (
            f"，點名後平均超額 {np.median(超):+.1f}%" if 超 else "")
        方們.append({"方": "影片觀點", "看法": 看, "細節": f"近 60 天 {多 + 空} 則：看多 {多}、看空 {空}", "準度": 準})
    if AI:
        看 = "偏多" if "多" in str(AI) else ("偏空" if "空" in str(AI) else "中性")
        a = 回饋.get("AI報告") or {}
        結 = a.get("達標", 0) + a.get("停損", 0)
        準 = f"AI 個股報告已結案 {結} 份、達標 {a.get('達標', 0) / 結 * 100:.0f}%" if 結 else "命中率樣本累積中"
        方們.append({"方": "AI 報告", "看法": 看, "細節": str(AI), "準度": 準})
    多 = sum(x["看法"] == "偏多" for x in 方們)
    空 = sum(x["看法"] == "偏空" for x in 方們)
    if len(方們) < 2:
        總 = "資料不足"
    elif 多 and 空:
        總 = f"分歧（{多} 方偏多、{空} 方偏空）"
    elif 多 == len(方們) or 空 == len(方們):
        總 = f"一致{'偏多' if 多 else '偏空'}"
    else:
        總 = f"大致{'偏多' if 多 > 空 else ('偏空' if 空 > 多 else '中性')}"
    return 方們, 總


def 影片多空(影片們, 代號, 天數=60, 今天=None):
    今天 = pd.Timestamp(今天 or pd.Timestamp.today().normalize())
    多 = 空 = 0
    for v in 影片們 or []:
        d = pd.to_datetime(v.get("日期"), errors="coerce")
        if pd.isna(d) or d < 今天 - pd.Timedelta(days=天數):
            continue
        for x in v.get("股票", []):
            if str(x.get("代號")) == str(代號):
                多 += x.get("看法") == "看多"
                空 += x.get("看法") == "看空"
    return {"看多": 多, "看空": 空}


# ========== 成長／價值檢查表（A2） ==========
def 檢查表(r, 配息年=0, 獲利季=0, 位階=np.nan, 預估位階=np.nan):
    """[(類別, 項目, 數值文字, 評等)]，評等 優／可／-。"""
    g = lambda k: _數(r.get(k))
    列 = []

    def 評(類, 項, 值, 優, 可):
        列.append((類, 項, 值, "優" if 優 else ("可" if 可 else "-")))

    v = g("營收年增率")
    評("成長", "月營收年增率", "—" if pd.isna(v) else f"{v:+.1f}%", v >= 20, v >= 0)
    v = g("累計營收年增率")
    評("成長", "今年累計營收年增", "—" if pd.isna(v) else f"{v:+.1f}%", v >= 15, v >= 0)
    評("成長", "月營收創新高", "是" if bool(r.get("營收創新高")) and r.get("營收創新高") is not np.nan else "否",
       bool(r.get("營收創新高")) and r.get("營收創新高") is not np.nan, False)
    v = g("毛利率年增")
    評("成長", "毛利率比去年同季", "—" if pd.isna(v) else f"{v:+.1f} 個百分點", v >= 1, v >= 0)
    v = g("距52週高點")
    評("成長", "股價離 52 週高點", "—" if pd.isna(v) else f"{v:+.1f}%", v >= -3, v >= -15)
    v = g("合約負債年增")
    if pd.notna(v):
        評("成長", "合約負債年增（接單）", f"{v:+.0f}%", v >= 30, v >= 0)
    評("價值", "連續配息", f"{配息年} 年" if 配息年 else "—", 配息年 >= 5, 配息年 >= 3)
    評("價值", "連續獲利", f"{獲利季} 季" if 獲利季 else "—", 獲利季 >= 8, 獲利季 >= 4)
    v = g("本益比")
    評("價值", "本益比", "—" if not v > 0 else f"{v:.1f} 倍", 0 < v <= 12, 0 < v <= 20)
    評("價值", "本益比 5 年位階", "—" if pd.isna(位階) else f"{位階:.0f}%（{估值標籤(位階)}）", 位階 < 30, 位階 <= 70)
    if pd.notna(預估位階):
        評("價值", "預估本益比位階", f"{預估位階:.0f}%（{估值標籤(預估位階)}）", 預估位階 < 30, 預估位階 <= 70)
    v = g("殖利率")
    評("價值", "殖利率", "—" if pd.isna(v) else f"{v:.2f}%", v >= 5, v >= 3)
    v = g("淨值比")
    評("價值", "股價淨值比", "—" if not v > 0 else f"{v:.2f} 倍", 0 < v <= 1.2, 0 < v <= 2.5)
    v = g("負債比")
    if pd.notna(v):
        評("價值", "負債比", f"{v:.0f}%", v <= 40, v <= 60)
    return 列


# ========== 持股最該注意（N6） ==========
def 注意分數(r, 分數列=None, 停損=None, 警示文字="", 位階=np.nan):
    """持股每檔的「該處理程度」與理由：越高越該先看。"""
    分, 理 = 0, []
    if 警示文字:
        分 += 3
        理.append("處置" if "處置" in 警示文字 else "注意股")
    if 停損 and 停損.get("建議") == "出清":
        分 += 3
        理.append("破 10 日線")
    elif 停損 and 停損.get("建議") == "減碼一半":
        分 += 2
        理.append("破 5 日線")
    報 = _數(r.get("報酬率(%)"))
    if 報 <= -15:
        分 += 2
        理.append(f"虧 {abs(報):.0f}%")
    elif 報 <= -8:
        分 += 1
        理.append(f"虧 {abs(報):.0f}%")
    if 分數列 is not None:
        變 = _數(分數列.get("較昨日"))
        if 變 <= -5:
            分 += 1
            理.append(f"評分降 {abs(變):.0f}")
        if _數(分數列.get("基本")) <= 42:
            分 += 1
            理.append("基本面弱")
    if _數(r.get("融資維持率")) < 140:
        分 += 1
        理.append("融資危")
    if pd.notna(位階) and 位階 > 90:
        分 += 1
        理.append("估值昂貴")
    if _數(r.get("漲跌幅")) <= -5:
        分 += 1
        理.append(f"今天跌 {abs(_數(r.get('漲跌幅'))):.1f}%")
    return 分, "、".join(理)


# ========== 籌碼集中度（A12 主力分點的替代） ==========
def 籌碼集中度(r, 大戶變化=np.nan):
    """沒有免費的券商分點資料，改用：千張大戶持股週變化、外資持股比 20 日變化、投信 60 日買超佔股本、當沖比率、融資 20 日增減。
    回傳 (0～100 分, [(項目, 文字, +1/−1/0)])；50＝中性，越高代表籌碼越往大戶、法人集中。"""
    g = lambda k: _數(r.get(k))
    項 = []
    分 = 50.0
    if pd.notna(大戶變化):
        分 += float(np.clip(大戶變化 * 10, -15, 15))
        項.append(("千張大戶週變化", f"{大戶變化:+.2f} 個百分點", int(np.sign(round(大戶變化, 2)))))
    v = g("外資持股20日變化")
    if pd.notna(v):
        分 += float(np.clip(v * 8, -15, 15))
        項.append(("外資持股 20 日", f"{v:+.2f} 個百分點", int(np.sign(round(v, 2)))))
    v = g("投信60日買超佔股本")
    if pd.notna(v):
        分 += float(np.clip(v * 5, -10, 10))
        項.append(("投信 60 日買超佔股本", f"{v:+.2f}%", int(np.sign(round(v, 2)))))
    v = g("融資20日增減")
    if pd.notna(v):
        分 -= float(np.clip(v / 2, -10, 10))
        項.append(("融資 20 日增減", f"{v:+.1f}%", -int(np.sign(round(v, 1)))))
    v = g("當沖比率")
    if pd.notna(v):
        分 -= float(np.clip((v - 25) / 2, 0, 10))
        項.append(("當沖比率", f"{v:.0f}%", -1 if v >= 40 else 0))
    if not 項:
        return None, []
    return round(float(np.clip(分, 0, 100))), 項


# ========== PEG（A11，先回測） ==========
def 近四季EPS成長(損益):
    """每檔每季：近四季 EPS 合計、去年同期近四季合計、年成長 %（index＝(code, quarter)）。"""
    t = 損益[["code", "quarter", "eps"]].dropna().sort_values(["code", "quarter"]).copy()
    t["四季"] = t.groupby("code")["eps"].transform(lambda s: s.rolling(4).sum())
    t["去年四季"] = t.groupby("code")["四季"].shift(4)
    t["成長%"] = (t["四季"] / t["去年四季"] - 1) * 100
    t.loc[~(t["去年四季"] > 0) | ~(t["四季"] > 0), "成長%"] = np.nan
    return t


def PEG(本益比, 成長):
    pe, g = _數(本益比), _數(成長)
    if not (pe > 0 and g > 0):
        return np.nan
    return pe / g


# ========== 排行、熱力圖的「為什麼」（N5） ==========
def 讀重大訊息(日期=None):
    f = 資料夾 / "material_news.csv"
    if not f.exists():
        return {}
    try:
        t = pd.read_csv(f, dtype={"code": str})
    except Exception:
        return {}
    if 日期 is not None:
        日 = pd.Timestamp(日期)
        d = pd.to_datetime(t["date"], errors="coerce")
        # 前一天盤後到當天收盤公布的重訊（盤後 14:30 以後的算到下一個交易日）
        t = t[(d == 日) | ((d >= 日 - pd.Timedelta(days=4)) & (d < 日) & (t["time"].astype(str) >= "14:30"))]
    return t.groupby("code")["subject"].first().to_dict()


def 漲跌原因(r, 重訊=None, 族群漲跌=None):
    """一行「可能原因」：漲跌停、重大訊息、月營收、法人大買賣、族群齊漲齊跌、爆量。只是線索，不是因果。"""
    g = lambda k: _數(r.get(k))
    c = str(r.get("代號") or r.get("code") or "")
    因 = []
    if bool(r.get("漲停")):
        因.append("漲停")
    elif bool(r.get("跌停")):
        因.append("跌停")
    if 重訊 and c in 重訊:
        因.append("重訊：" + str(重訊[c])[:16])
    if pd.notna(g("營收年增率")) and abs(g("營收年增率")) >= 30 and bool(r.get("營收創新高")):
        因.append(f"營收創新高（年增 {g('營收年增率'):.0f}%）")
    elif pd.notna(g("營收年增率")) and abs(g("營收年增率")) >= 50:
        因.append(f"營收年{'增' if g('營收年增率') > 0 else '減'} {abs(g('營收年增率')):.0f}%")
    量 = g("成交張數") if pd.notna(g("成交張數")) else g("張數")
    法 = g("法人買超")
    if 量 > 0 and pd.notna(法) and abs(法) / 量 >= 0.2 and abs(法) >= 500:
        因.append(f"法人{'大買' if 法 > 0 else '大賣'} {abs(法):,.0f} 張")
    if 族群漲跌 is not None:
        業 = r.get("產業")
        v = _數(族群漲跌.get(業)) if 業 else np.nan
        if pd.notna(v) and abs(v) >= 2.5:
            因.append(f"{業}族群{'齊漲' if v > 0 else '齊跌'} {v:+.1f}%")
    if g("量對5日均") >= 3:
        因.append(f"爆量 {g('量對5日均'):.1f} 倍")
    return "、".join(因[:3])


# ========== 今晚籌碼快訊（N10） ==========
def 百分位(序列, 值, 天數=250):
    s = pd.Series(序列).dropna().astype(float).tail(天數)
    v = _數(值)
    if len(s) < 20 or pd.isna(v):
        return np.nan
    return float((s < v).mean() * 100)


def 籌碼快訊():
    """外資台指期淨未平倉與增減、外資選擇權買權／賣權淨未平倉、小台散戶多空比；每項附近一年百分位（極端才有意義）。
    回傳 list of dict(項目, 值, 增減, 單位, 百分位, 說明, 偏多)。"""
    項們 = []

    def 讀(檔):
        f = 資料夾 / 檔
        return pd.read_csv(f, parse_dates=["date"]).sort_values("date") if f.exists() else None

    oi = 讀("futures_oi.csv")
    if oi is not None and len(oi) > 2:
        v, 前 = oi["foreign_oi"].iloc[-1], oi["foreign_oi"].iloc[-2]
        項們.append({"項目": "外資台指期淨未平倉", "值": v, "增減": v - 前, "單位": "口", "日期": oi["date"].iloc[-1],
                   "百分位": 百分位(oi["foreign_oi"], v), "偏多": v > 0,
                   "說明": "淨多單" if v > 0 else "淨空單"})
    op = 讀("options_inst.csv")
    if op is not None and len(op) > 2:
        for 欄, 名, 多 in (("foreign_call_oi", "外資買權淨未平倉", True), ("foreign_put_oi", "外資賣權淨未平倉", False)):
            v, 前 = op[欄].iloc[-1], op[欄].iloc[-2]
            項們.append({"項目": 名, "值": v, "增減": v - 前, "單位": "口", "日期": op["date"].iloc[-1],
                       "百分位": 百分位(op[欄], v), "偏多": (v > 0) == 多,
                       "說明": ("買權" if 多 else "賣權") + ("淨買方" if v > 0 else "淨賣方")})
    mt = 讀("mtx_retail.csv")
    if mt is not None and len(mt) > 2:
        v, 前 = mt["ratio"].iloc[-1], mt["ratio"].iloc[-2]
        項們.append({"項目": "小台散戶多空比", "值": v, "增減": v - 前, "單位": "%", "日期": mt["date"].iloc[-1],
                   "百分位": 百分位(mt["ratio"], v), "偏多": v < 0,
                   "說明": "散戶偏多（反向指標，偏空）" if v > 0 else "散戶偏空（反向指標，偏多）"})
    return 項們


def 極端標籤(p):
    if pd.isna(p):
        return ""
    if p >= 90:
        return "一年高檔"
    if p <= 10:
        return "一年低檔"
    return ""


# ========== LINE 代號查詢的一行健檢（N8） ==========
def LINE健檢行(代號, r):
    """LINE 打代號回覆的第一行：短中長線看法、本益比位階（含預估）、徽章。只用 r 與 data/ 檔案，出錯回傳空字串。"""
    try:
        代號 = str(代號)
        位階 = 讀本益比位階()
        列 = 位階.loc[代號] if 代號 in 位階.index else None
        位 = 位階百分位(r.get("本益比"), 列)
        預 = np.nan
        try:
            import engine
            e = engine.預估EPS表()
            if e is not None and 代號 in e.index:
                eps = _數(e.at[代號, "預估EPS明年" if pd.Timestamp.now().month >= 7 and _數(e.at[代號, "預估EPS明年"]) > 0 else "預估EPS今年"])
                if eps > 0 and _數(r.get("收盤")) > 0:
                    預 = 位階百分位(_數(r.get("收盤")) / eps, 列)
        except Exception:
            pass
        三 = 三格判斷(r, 位階=位, 體檢={})
        章 = []
        try:
            股利 = pd.read_csv(資料夾 / "fundamental" / "dividend.csv", dtype={"code": str})
            n = 連續配息年數(股利[股利["code"] == 代號]).get(代號, 0)
            if n >= 3:
                章.append(f"連配{n}")
        except Exception:
            pass
        try:
            損 = pd.read_csv(資料夾 / "fundamental" / "income.csv", dtype={"code": str}, usecols=["code", "quarter", "eps"])
            if 連續獲利季數(損[損["code"] == 代號]).get(代號, 0) >= 8:
                章.append("賺")
        except Exception:
            pass
        if 代號 in 讀期貨標的():
            章.append("期")
        if bool(r.get("營收創新高")) and r.get("營收創新高") is not np.nan:
            章.append("營收高")
        try:
            w = pd.read_csv(資料夾 / "warning.csv", dtype={"code": str})
            w = w[w["code"] == 代號]
            if len(w):
                章.append("⚠" + str(w["type"].iloc[0]))
        except Exception:
            pass
        估 = 估值標籤(位) + (f"（預估{估值標籤(預)}）" if pd.notna(預) and 估值標籤(預) != 估值標籤(位) else "")
        看 = "｜".join(f"{x['期']}{x['看法']}" for x in 三)
        return f"🩺 {看}｜估值{估}" + (f"｜{' '.join(章)}" if 章 else "")
    except Exception as e:
        print("LINE健檢行失敗：", repr(e))
        return ""
