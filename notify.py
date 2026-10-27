# LINE 推播：每天收盤摘要、盤中到價提醒（由 GitHub Actions 執行）
#   python notify.py daily   收盤摘要（大盤、強弱族群、自選股、庫存損益、到價）
#   python notify.py alert   盤中檢查到價提醒（同一個提醒一天只通知一次）
#   python notify.py test    傳一則測試訊息
#   python notify.py health  檢查各資料來源有沒有正常更新，有問題才通知（休市日不算問題）
#   python notify.py weekly  每週六週報（大盤、庫存、自選股一週表現，主動式 ETF 一週加減碼，下週日程）
#   python notify.py brief 盤前|收盤|夜盤  AI 大盤解讀（要設定 GEMINI_API_KEY 或 ANTHROPIC_API_KEY），存到 ai-reports 並傳 LINE
#
# 需要在 GitHub 專案 Settings → Secrets and variables → Actions 設定：
#   LINE_TOKEN    LINE Messaging API 的 Channel access token（必填）
#   LINE_USER_ID  你的 LINE User ID（選填；沒填就用 broadcast 傳給所有加好友的人，只有你自己的話效果一樣）
#   HOLDINGS      庫存 CSV（選填，跟 Streamlit Secrets 的 holdings 一樣格式），有填才會附上今日損益
# 自選股與到價提醒在網站上設定，存在 ai-reports 分支的 watchlist.json、alerts.json。

import base64
import datetime as dt
import io
import json
import os
import sys
from pathlib import Path

import pandas as pd
import requests

資料夾 = Path(__file__).parent / "data"
倉庫 = os.environ.get("GITHUB_REPOSITORY", "gelu27/Stock-lab")
分支 = "ai-reports"
台北 = dt.timezone(dt.timedelta(hours=8))


def _gh標頭():
    權杖 = os.environ.get("GITHUB_TOKEN", "")
    return {"Authorization": f"Bearer {權杖}", "Accept": "application/vnd.github+json"} if 權杖 else {}


def 讀設定(檔名):
    try:
        r = requests.get(f"https://api.github.com/repos/{倉庫}/contents/{檔名}", params={"ref": 分支},
                         headers=_gh標頭(), timeout=15)
    except requests.RequestException:
        return {}, None
    if r.status_code != 200:
        return {}, None
    return json.loads(base64.b64decode(r.json()["content"]).decode("utf-8")), r.json()["sha"]


def 寫設定(檔名, 內容物, sha):
    資料 = {"message": f"更新 {檔名}", "branch": 分支,
          "content": base64.b64encode(json.dumps(內容物, ensure_ascii=False, indent=1).encode()).decode()}
    if sha:
        資料["sha"] = sha
    requests.put(f"https://api.github.com/repos/{倉庫}/contents/{檔名}", headers=_gh標頭(), json=資料,
                 timeout=30).raise_for_status()


def 清理(值):
    """手機複製貼上常夾帶全形字、換行或看不見的字元，轉成半形並只留英數符號。"""
    import unicodedata
    值 = unicodedata.normalize("NFKC", str(值 or ""))
    return "".join(c for c in 值 if 33 <= ord(c) <= 126).strip('"\'')


def 推播(文字):
    權杖 = 清理(os.environ.get("LINE_TOKEN"))
    if not 權杖:
        print("沒有設定 LINE_TOKEN，略過推播。內容如下：\n" + 文字)
        return
    對象 = 清理(os.environ.get("LINE_USER_ID"))
    網址 = "https://api.line.me/v2/bot/message/" + ("push" if 對象 else "broadcast")
    內容 = {"messages": [{"type": "text", "text": 文字[:4900]}]}
    if 對象:
        內容["to"] = 對象
    r = requests.post(網址, headers={"Authorization": f"Bearer {權杖}"}, json=內容, timeout=15)
    print("LINE 回應", r.status_code, r.text[:200])
    if r.status_code == 401:
        print(f"金鑰長度 {len(權杖)} 個字（正確的 Channel access token 通常 170 字左右；"
              "32 個字的是 Channel secret，貼錯了）")
    r.raise_for_status()


def 最新行情():
    """最新一天的上市櫃收盤（代號、名稱、市場、收盤、漲跌、漲跌幅、成交值），加上產業與市值。"""
    檔 = sorted((資料夾 / "prices").glob("*/*.csv.gz"))[-1]
    t = pd.read_csv(檔, dtype={"code": str})
    t["幅度"] = t["change"] / (t["close"] - t["change"]) * 100
    股本 = 資料夾 / "fundamental" / "capital.csv"
    if 股本.exists():
        c = pd.read_csv(股本, dtype={"code": str}).drop_duplicates("code", keep="last").set_index("code")
        t = t.join(c[["shares", "industry"]], on="code")
    return pd.Timestamp(檔.name[:8]), t


def 名稱(t, 代號):
    列 = t[t["code"] == 代號]
    return 列["name"].iloc[0] if len(列) else 代號


def 符號(值):
    return "▲" if 值 > 0 else ("▼" if 值 < 0 else "－")


def 收盤摘要(強制=False):
    日期, t = 最新行情()
    if not 強制 and 日期.date() != dt.datetime.now(台北).date():
        print(f"最新資料是 {日期:%m/%d}，今天沒有新資料（休市），不推播")
        return
    行們 = [f"📊 台股收盤 {日期:%m/%d}"]
    指數檔 = sorted((資料夾 / "index").glob("*.csv"))
    if 指數檔:
        i = pd.read_csv(指數檔[-1]).iloc[-1]
        幅 = i["change"] / (i["close"] - i["change"]) * 100
        行們.append(f"加權 {i['close']:,.0f} {符號(i['change'])}{abs(i['change']):,.0f}（{幅:+.2f}%）")
    股 = t[t["code"].str.fullmatch(r"\d{4}")]
    行們.append(f"上漲 {(股['change'] > 0).sum()}／下跌 {(股['change'] < 0).sum()}，"
              f"成交 {t['value'].sum() / 1e8:,.0f} 億")
    if "industry" in 股:
        g = 股[股["industry"] != "存託憑證"].dropna(subset=["industry", "幅度"]).assign(市值=lambda d: d["close"] * d["shares"])
        g = g[g["市值"] > 0]
        族 = (g["幅度"] * g["市值"]).groupby(g["industry"]).sum() / g.groupby("industry")["市值"].sum()
        族 = 族.sort_values(ascending=False)
        行們.append("強勢族群：" + "、".join(f"{k} {v:+.1f}%" for k, v in 族.head(3).items()))
        行們.append("弱勢族群：" + "、".join(f"{k} {v:+.1f}%" for k, v in 族.tail(3)[::-1].items()))

    持股 = os.environ.get("HOLDINGS", "").strip()
    if 持股:
        h = pd.read_csv(io.StringIO(持股), dtype={"代號": str})
        h["代號"] = h["代號"].str.strip()
        h = h.join(t.set_index("code")[["close", "change"]], on="代號").dropna(subset=["close"])
        今日 = (h["change"] * h["股數"]).sum()
        總 = (h["close"] * h["股數"]).sum() - h["總成本"].sum()
        行們 += ["", f"💼 庫存今日 {今日:+,.0f} 元，累積 {總:+,.0f} 元"]

    自選, _ = 讀設定("watchlist.json")
    代號們 = list(dict.fromkeys(c for k, v in 自選.items() if not k.startswith("_") for c in v))
    if 代號們:
        行們 += ["", "⭐ 自選股"]
        for c in 代號們[:30]:
            列 = t[t["code"] == c]
            if len(列):
                r = 列.iloc[0]
                行們.append(f"{r['name']} {r['close']:,.2f} {r['幅度']:+.2f}%")

    try:
        行們 += 提醒事項(([] if not 持股 else h["代號"].tolist()) + 代號們)
    except Exception as e:
        print("日程／警示失敗：", repr(e))

    try:
        行們 += 價位提醒(([] if not 持股 else h["代號"].tolist()) + 代號們)
    except Exception as e:
        print("價位提醒失敗：", repr(e))

    try:
        行們 += 評分摘要(持股, 代號們)
    except Exception as e:  # 評分失敗不影響其他摘要
        print("評分計算失敗：", repr(e))

    提醒, _ = 讀設定("alerts.json")
    到價 = []
    for c, 設 in 提醒.items():
        列 = t[t["code"] == c]
        if not len(列):
            continue
        價 = 列["close"].iloc[0]
        if 設.get("上") and 價 >= 設["上"]:
            到價.append(f"{名稱(t, c)} 收 {價:,.2f}，已達 {設['上']:g} 以上")
        if 設.get("下") and 價 <= 設["下"]:
            到價.append(f"{名稱(t, c)} 收 {價:,.2f}，已跌到 {設['下']:g} 以下")
    if 到價:
        行們 += ["", "🔔 到價"] + 到價
    推播("\n".join(行們))


def 價位提醒(代號們):
    """加權、櫃買和庫存＋自選股今天跌破或站回重要價位（月線、季線、半年線、年線、共振區、黑 K 一半、爆量 K 低點）、
    KD 低檔黃金交叉，以及美股龍頭超賣。"""
    import engine
    跌站 = []
    for 代, 名 in (("TAIEX", "加權"), ("TPEX", "櫃買")):
        K = engine.讀取指數K線(代)
        for 動, 價名, 價 in (engine.跌破站回(K) + engine.技術訊號(K) if K is not None else []):
            跌站.append(f"{'⚠️' if 動 == '跌破' else '✅'} {名}{動}{價名}" + ("" if 價 is None or "共振區" in 價名 else f" {價:,.2f}"))
    代號們 = list(dict.fromkeys(代號們))[:40]
    if 代號們:
        原始 = engine.讀取資料庫(最近天數=400, 代號=代號們)
        if 原始 is not None:
            指標 = engine.計算指標(原始)
            for c, 歷史 in 指標.groupby("代號"):
                K = engine.還原K線(歷史)
                量 = 歷史.set_index("date")["成交值億"]
                紀 = engine.停損紀律狀態(K) if K is not None else None
                事件 = (engine.跌破站回(K, 量) + engine.技術訊號(K, 量) if K is not None else [])
                if 紀 and 紀["今天"]:
                    事件.append(紀["今天"])
                for 動, 價名, 價 in 事件:
                    跌站.append(f"{'⚠️' if 動 == '跌破' else '✅'} {歷史['名稱'].iloc[-1]} {動}{價名}"
                              + ("" if 價 is None or "共振區" in 價名 else f" {價:,.2f}"))
    行們 = (["", "📍 跌破／站回重要價位"] + 跌站) if 跌站 else []
    超 = engine.美股超賣(engine.讀取美股())
    if len(超):
        超 = 超[超["狀態"] == "超賣"]
        if len(超):
            行們 += ["", "🧊 美股龍頭超賣：" + "、".join(f"{k}（RSI {r['RSI']:.0f}、距月線 {r['距月線%']:+.1f}%）"
                                               for k, r in 超.iterrows())]
    return 行們


def 提醒事項(代號們):
    """庫存、自選股的處置／注意股，以及未來 3 天內的法說會、營收與財報期限。"""
    import engine
    行們 = []
    警 = engine.讀取警示()
    警示 = [f"{c} {警[c]}" for c in dict.fromkeys(代號們) if c in 警]
    if 警示:
        行們 += ["", "⚠️ 處置／注意股"] + 警示
    # AI 報告今天剛達標或停損
    try:
        報告們 = engine.列出AI報告({"GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""), "AI_REPO": 倉庫})
        價 = engine.讀取資料庫(最近天數=60, 代號=list(報告們))
        結案 = []
        if 價 is not None:
            價 = 價.rename(columns={"code": "代號", "close": "收盤"})
            最新 = 價["date"].max()
            for c, 紀錄們 in 報告們.items():
                if 紀錄們:
                    驗 = engine.驗收AI報告(紀錄們[0], 價[價["代號"] == c])
                    if 驗["結果"] in ("達標", "停損") and 驗["日期"] == 最新:
                        結案.append(f"{'🎯' if 驗['結果'] == '達標' else '🛑'} {c} AI 報告{驗['結果']}"
                                  f"（目標 {驗['目標']:g}、停損 {驗['停損']:g}）")
        if 結案:
            行們 += ["", "🤖 AI 報告驗收"] + 結案
    except Exception as e:
        print("AI 報告驗收失敗：", repr(e))
    狀態, sha = 讀設定("alert_state.json")
    舊狀態 = dict(狀態)
    try:
        行們 += 營收新高提醒(代號們, 狀態)
    except Exception as e:
        print("營收新高失敗：", repr(e))
    try:
        行們 += ETF共識提醒(代號們, 狀態)
    except Exception as e:
        print("ETF 共識失敗：", repr(e))
    try:
        行們 += 條件訂閱提醒(狀態)
    except Exception as e:
        print("選股訂閱失敗：", repr(e))
    if 狀態 != 舊狀態:
        try:
            寫設定("alert_state.json", 狀態, sha)
        except Exception as e:
            print("提醒狀態存檔失敗：", repr(e))
    日程 = engine.重要日程(set(代號們), 天數=3)
    if len(日程):
        行們 += ["", "📅 近 3 天日程"] + [f"{r['日期']:%m/%d} {r['類型']} {r['股票'] if r['代號'] else ''} {r['說明'][:40]}".replace("  ", " ")
                                        for _, r in 日程.iterrows()]
    return 行們


def 營收新高提醒(代號們, 狀態):
    """庫存、自選股公布月營收就通知（每檔每個月只通知一次），創近 5 年新高的加 🏆。
    月初上個月和上上個月都可能還在公布，兩個月都看。第一次執行只記下已公布的，不通知，免得一次洗版。"""
    import engine
    _, 月份們 = engine.月營收總表()
    初次 = "營收公布_啟用" not in 狀態
    今天 = dt.datetime.now(台北).strftime("%Y-%m-%d")
    行們 = []
    for 月 in 月份們[:2 if dt.datetime.now(台北).day <= 12 else 1]:
        t, _ = engine.月營收總表(月)
        for c in dict.fromkeys(代號們):
            鍵 = f"營收公布_{c}_{月}"
            if c not in t.index or 鍵 in 狀態 or f"營收新高_{c}_{月}" in 狀態:
                continue
            狀態[鍵] = 今天
            if 初次:
                continue
            r = t.loc[c]
            def 幅(v, 低):
                return "—" if pd.isna(v) or 低 else f"{v:+.1f}%"
            新高 = bool(r["五年新高"])
            行們.append(f"{'🏆' if 新高 else '•'} {c} {月[5:]} 月 {r['營收'] / 1e5:,.1f} 億，"
                       f"月增 {幅(r['月增'], r['月增基期低'])}、年增 {幅(r['年增'], r['年增基期低'])}"
                       + ("，近 5 年新高" if 新高 else ""))
    狀態["營收公布_啟用"] = 狀態.get("營收公布_啟用", 今天)
    return (["", "💰 月營收公布（庫存＋自選）"] + 行們) if 行們 else []


def 條件訂閱提醒(狀態, 最多=15):
    """網站「04 選股」訂閱的條件：跟上次比，新符合、剛剔除的股票。第一次只記名單不通知。"""
    import engine
    訂閱, _ = 讀設定("subscriptions.json")
    if not 訂閱:
        return []
    指標 = engine.計算指標(engine.讀取資料庫(最近天數=130))
    最新 = 指標["date"].max()
    今日 = engine.加基本面(指標[指標["date"] == 最新], engine.讀取基本面())
    名 = dict(zip(今日["代號"], 今日["名稱"]))
    日 = f"{最新:%Y-%m-%d}"
    行們 = []
    for n, v in 訂閱.items():
        鍵 = f"訂閱_{n}"
        if 狀態.get(鍵, {}).get("日期") == 日:
            continue
        條件 = {k: (tuple(x) if k in ("股價區間", "RSI區間") and isinstance(x, list) else x) for k, x in v.get("條件", {}).items()}
        現 = engine.選股(今日, 條件)["代號"].tolist()
        舊 = 狀態.get(鍵, {}).get("名單")
        狀態[鍵] = {"日期": 日, "名單": 現}
        if 舊 is None:
            continue
        新 = [c for c in 現 if c not in 舊]
        出 = [c for c in 舊 if c not in 現]
        if 新 or 出:
            行們.append(f"【{n}】共 {len(現)} 檔")
            if 新:
                行們.append("　🆕 新符合：" + "、".join(f"{c} {名.get(c, '')}" for c in 新[:最多]) + (f" 等 {len(新)} 檔" if len(新) > 最多 else ""))
            if 出:
                行們.append("　👋 剛剔除：" + "、".join(f"{c} {名.get(c, '')}" for c in 出[:最多]) + (f" 等 {len(出)} 檔" if len(出) > 最多 else ""))
    return (["", "🔔 選股訂閱變動"] + 行們) if 行們 else []


def ETF共識提醒(代號們, 狀態, 門檻=3):
    """最新一天有 門檻 家以上主動式 ETF 一起新增／加碼的股票（每個資料日只通知一次）。"""
    import etf_data
    持股 = etf_data.讀持股(天數=8)
    if 持股.empty:
        return []
    變 = etf_data.每日變化(持股, etf_data.讀資訊())
    if 變.empty:
        return []
    日 = 變["date"].max()
    鍵 = f"ETF共識_{日:%Y%m%d}"
    if 鍵 in 狀態:
        return []
    今 = 變[變["date"] == 日]
    買 = 今[今["type"].isin(["新增", "加碼"])].groupby("code").agg(家數=("etf", "nunique"), 名稱=("name", "first"),
                                                              金額=("adj_amount", "sum"))
    賣 = 今[今["type"].isin(["減碼", "出清"])].groupby("code")["etf"].nunique()
    買["淨家數"] = 買["家數"] - 賣.reindex(買.index).fillna(0)
    共識 = 買[買["家數"] >= 門檻].sort_values(["家數", "金額"], ascending=False).head(8)
    狀態[鍵] = dt.datetime.now(台北).strftime("%Y-%m-%d")
    if 共識.empty:
        return []
    自選 = set(代號們)
    return ["", f"🏦 主動式 ETF 共識加碼（{日:%m/%d}，{門檻} 家以上）"] + [
        f"{'⭐' if c in 自選 else ''}{c} {r['名稱']} {r['家數']:.0f} 家" + (f"（{r['金額'] / 1e8:+.1f} 億）" if pd.notna(r["金額"]) else "")
        for c, r in 共識.iterrows()]


def 評分摘要(持股, 自選們=()):
    """大盤分數、庫存每檔分數、高分榜前 5（規則計分，跟網站「每日評分」頁同一套）。"""
    import engine
    原始 = engine.讀取資料庫(最近天數=260)  # 52 週高點要用到約一年的資料
    指標 = engine.計算指標(原始)
    del 原始
    分, _, 大 = engine.今昨評分(指標[指標["date"] >= 指標["date"].max() - pd.Timedelta(days=20)],
                          engine.讀取基本面(), engine.讀取加權指數())
    變 = lambda v: "" if pd.isna(v) or v == 0 else f"{符號(v)}{abs(v):.0f}"
    行們 = ["", f"🧮 今日評分（滿分 100，50 為中性）", f"大盤 {大['分數']} 分 {大['看法']} {變(大.get('較昨日'))}".rstrip()]
    if 持股:
        h = pd.read_csv(io.StringIO(持股), dtype={"代號": str})
        庫 = 分.reindex(h["代號"].str.strip().unique()).dropna(subset=["總分"]).sort_values("總分", ascending=False)
        if len(庫):
            行們.append("💼 庫存：")
            行們 += [f"{r['名稱']} {r['總分']:.0f} {r['看法']} {變(r['較昨日'])}".rstrip() for _, r in 庫.iterrows()]
    庫存們 = pd.read_csv(io.StringIO(持股), dtype={"代號": str})["代號"].str.strip().tolist() if 持股 else []
    大變 = 分.reindex(list(dict.fromkeys(庫存們 + list(自選們)))).dropna(subset=["總分", "較昨日"])
    大變 = 大變[大變["較昨日"].abs() >= 10].sort_values("較昨日")
    if len(大變):
        行們.append("📈 評分大變動（一天 ±10 分以上）：" + "、".join(
            f"{r['名稱']} {r['總分'] - r['較昨日']:.0f}→{r['總分']:.0f}" for _, r in 大變.iterrows()))
    高 = 分[(分["5日均量"] >= 500) & ~分.index.str.startswith("00")].sort_values("總分", ascending=False).head(5)
    行們.append("🔝 高分股：" + "、".join(f"{r['名稱']} {r['總分']:.0f}" for _, r in 高.iterrows()))
    行們.append("（規則計分，僅供參考，非投資建議）")
    return 行們


def 盤中價位提醒(狀態, 今天):
    """加權、櫃買盤中跌破或站回重要價位（月線、季線、半年線、年線、共振區、黑 K 一半）：
    把即時價當成今天的收盤接在日 K 後面判斷，同一個價位一天只通知一次。"""
    import engine
    try:
        即 = engine.即時報價(["t00", "o00"], {"o00": "上櫃"})
    except Exception as e:
        print("即時指數抓不到：", repr(e))
        return []
    訊息 = []
    for 代, 碼, 名 in (("TAIEX", "t00", "加權"), ("TPEX", "o00", "櫃買")):
        K = engine.讀取指數K線(代)
        r = 即[即["code"] == 碼]
        if K is None or r.empty or pd.isna(r["close"].iloc[0]):
            continue
        r = r.iloc[0]
        if K["date"].iloc[-1].strftime("%Y-%m-%d") == 今天:   # 已經有今天的收盤（理論上盤中不會），不重複
            continue
        今K = pd.DataFrame([{"date": pd.Timestamp(今天), "open": r["close"], "high": r["high"], "low": r["low"],
                            "close": r["close"]}]).fillna(r["close"])
        for 動, 價名, 價 in engine.跌破站回(pd.concat([K, 今K], ignore_index=True)):
            鍵 = f"盤中_{代}_{動}_{價名}"
            if 狀態.get(鍵) != 今天:
                狀態[鍵] = 今天
                訊息.append(f"{'⚠️' if 動 == '跌破' else '✅'} {名}盤中{動}{價名}"
                          + ("" if "共振區" in 價名 else f" {價:,.2f}") + f"（現在 {r['close']:,.2f}，{r['time']}）")
    return 訊息


def 盤中提醒():
    現在 = dt.datetime.now(台北)
    if 現在.weekday() >= 5 or not (dt.time(9, 0) <= 現在.time() <= dt.time(13, 35)):
        print("不在盤中時間，略過")
        return
    今天 = 現在.strftime("%Y-%m-%d")
    狀態, sha = 讀設定("alert_state.json")
    價位訊息 = 盤中價位提醒(狀態, 今天)
    提醒, _ = 讀設定("alerts.json")
    if not 提醒:
        if 價位訊息:
            推播("📍 大盤盤中關鍵價位\n" + "\n".join(價位訊息))
            寫設定("alert_state.json", 狀態, sha)
        else:
            print("沒有設定到價提醒，大盤也沒有跌破／站回")
        return
    _, t = 最新行情()
    市場 = dict(zip(t["code"], t.get("market", pd.Series("上市", index=t.index))))
    頻道 = "|".join(f"{'otc' if 市場.get(c) == '上櫃' else 'tse'}_{c}.tw" for c in 提醒)
    r = requests.get("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?json=1&delay=0&ex_ch=" + 頻道,
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    訊息 = []
    for m in r.json().get("msgArray", []):
        c = m.get("c")
        try:
            價 = float(m.get("z"))
        except (TypeError, ValueError):
            try:
                價 = float(str(m.get("b", "")).split("_")[0])
            except ValueError:
                continue
        設 = 提醒.get(c, {})
        for 方向, 條件 in (("上", lambda: 設.get("上") and 價 >= 設["上"]), ("下", lambda: 設.get("下") and 價 <= 設["下"])):
            鍵 = f"{c}_{方向}"
            if 條件() and 狀態.get(鍵) != 今天:
                字 = "漲到" if 方向 == "上" else "跌到"
                訊息.append(f"🔔 {m.get('n', c)} {字} {價:,.2f}（提醒價 {設[方向]:g}）{m.get('t', '')}")
                狀態[鍵] = 今天
    if 價位訊息:
        訊息 = ["📍 大盤盤中關鍵價位"] + 價位訊息 + ([""] if 訊息 else []) + 訊息
    if 訊息:
        推播("\n".join(訊息))
        寫設定("alert_state.json", 狀態, sha)
    else:
        print("沒有觸發的提醒")


def _最新檔日(子):
    檔們 = [f.name[:8] for f in (資料夾 / 子).glob("**/*.csv.gz")]
    return pd.Timestamp(max(檔們)).date() if 檔們 else None


def 健康檢查():
    """每天更新完檢查一次：今天有開盤卻沒抓到、每週每月資料太久沒更新、網站即時查詢的來源連不上，就 LINE 通知。"""
    import engine
    問題 = []
    今天 = dt.datetime.now(台北).date()
    if os.environ.get("UPDATE_OUTCOME") == "failure":
        問題.append("資料更新程式執行失敗（到 GitHub Actions 看錯誤訊息）")
    # 今天有沒有開盤：問證交所即時行情，加權指數的資料日期是不是今天
    開盤 = None
    try:
        r = requests.get("https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
                         params={"ex_ch": "tse_t00.tw", "json": 1, "delay": 0},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        開盤 = r.json()["msgArray"][0]["d"] == 今天.strftime("%Y%m%d")
    except Exception as e:
        問題.append(f"證交所即時行情連不上（{type(e).__name__}），無法確認今天有沒有開盤")
    價 = _最新檔日("prices")
    print(f"今天 {今天}，{'有' if 開盤 else '沒有' if 開盤 is False else '不確定有沒有'}開盤，股價最新 {價}")
    if 開盤 and 價 != 今天:
        問題.append(f"今天有開盤，但股價資料沒抓到（最新 {價:%m/%d}）")
    籌 = _最新檔日("chips")
    if 價 and (籌 is None or 籌 < 價):
        問題.append(f"三大法人／融資資料落後（最新 {籌:%m/%d}，股價 {價:%m/%d}）" if 籌 else "沒有三大法人／融資資料")

    def 太舊(名稱, 最新, 容許天數):
        if 最新 is None:
            問題.append(f"{名稱}：沒有資料")
        elif (今天 - 最新).days > 容許天數:
            問題.append(f"{名稱}：最新是 {最新:%Y/%m/%d}，已經 {(今天 - 最新).days} 天沒更新")

    def 讀(檔, 欄):
        f = 資料夾 / 檔
        return pd.read_csv(f, usecols=[欄])[欄].astype(str).max() if f.exists() else None

    太舊("集保股權分散（每週）", _最新檔日("tdcc"), 10)
    借 = _最新檔日("sbl")
    if 價 and 借 and 借 < 價:
        問題.append(f"借券賣出資料落後（最新 {借:%m/%d}，股價 {價:%m/%d}）")
    for 名稱, 檔 in (("融資金額（融資維持率用）", "margin_total.csv"), ("外資台指期未平倉", "futures_oi.csv"),
                     ("外資持股比", "qfii.csv.gz"), ("上市個股當沖", "daytrade.csv.gz"), ("選擇權籌碼", "options_pc.csv")):
        最新 = 讀(檔, "date")
        if 價 and 最新 and (價 - pd.Timestamp(最新).date()).days > 4:
            問題.append(f"{名稱}落後（最新 {pd.Timestamp(最新):%m/%d}，股價 {價:%m/%d}）")
    fx = 讀("fx.csv", "date")
    太舊("美元匯率", fx and pd.Timestamp(fx).date(), 5)
    # 月營收次月 10 日前公布、內部人持股次月 15 日前、季報最晚季後 75～90 天
    營 = 讀("fundamental/revenue.csv", "month")
    太舊("月營收", 營 and (pd.Period(營, "M") + 1).to_timestamp().date(), 45)
    內 = 讀("fundamental/insider.csv", "month")
    太舊("內部人持股", 內 and (pd.Period(內, "M") + 1).to_timestamp().date(), 50)
    季 = 讀("fundamental/eps.csv", "quarter")
    太舊("季報 EPS", 季 and (pd.Period(季, "Q") + 1).to_timestamp().date(), 140)

    # 網站點個股時才即時查的來源
    for 名稱, 查 in (("集保結算所歷史查詢（FLOW、HOLDERS 用）", lambda: engine.集保歷史("2330", 週數=2)),
                   ("公開資訊觀測站內部人查詢（INSIDER 用）", lambda: engine.內部人歷史("2330", 月數=2))):
        try:
            結果 = 查()
            if 結果 is None or len(結果) == 0:
                問題.append(f"{名稱}：查不到資料，網頁格式可能改了")
        except Exception as e:
            問題.append(f"{名稱}：連不上（{type(e).__name__}）")

    try:
        錯 = 網站錯誤()
    except Exception as e:
        print("網站錯誤紀錄讀取失敗：", repr(e))
        錯 = []
    if 錯:
        推播("🐞 台股觀測實驗室：網站有新的錯誤\n" + "\n".join(f"・{x}" for x in 錯)
             + "\n\n可以把這段訊息貼給 Claude 修。")
    if 問題:
        推播("⚠️ 台股觀測實驗室：資料來源異常\n" + "\n".join(f"・{x}" for x in 問題)
             + "\n\n網站其他功能照常，可以到 GitHub Actions 看「更新資料庫」的紀錄。")
    else:
        print("資料來源全部正常")


def 網站錯誤():
    """網站 errors.json 裡上次通知之後新發生（或又發生）的錯誤。"""
    紀錄, _ = 讀設定("errors.json")
    if not 紀錄:
        return []
    狀態, sha = 讀設定("alert_state.json")
    已通知 = 狀態.get("網站錯誤已通知", {})
    新 = [(k, v) for k, v in 紀錄.items() if v.get("次數", 0) > 已通知.get(k, 0)]
    if not 新:
        return []
    狀態["網站錯誤已通知"] = {**已通知, **{k: v["次數"] for k, v in 新}}
    try:
        寫設定("alert_state.json", 狀態, sha)
    except Exception as e:
        print("提醒狀態存檔失敗：", repr(e))
    return [f"{v['頁面']}：{v['類型']} {v['訊息'][:80]}（{v.get('位置', '')}，共 {v['次數']} 次，最近 {v['最近']}）" for _, v in 新]


def 週報():
    """這週（最近 5 個交易日）的大盤、庫存、自選股表現，主動式 ETF 一週加減碼，下週日程。"""
    import engine
    檔們 = sorted((資料夾 / "prices").glob("*/*.csv.gz"))[-6:]
    if len(檔們) < 2:
        print("資料不夠，不傳週報")
        return
    讀 = lambda f: pd.read_csv(f, dtype={"code": str}, usecols=["code", "name", "close"]).set_index("code")
    本週, 上週 = 讀(檔們[-1]), 讀(檔們[0])
    起, 迄 = pd.Timestamp(檔們[1].name[:8]), pd.Timestamp(檔們[-1].name[:8])
    週漲 = (本週["close"] / 上週["close"].reindex(本週.index) - 1) * 100
    行們 = [f"🗓 台股週報 {起:%m/%d}～{迄:%m/%d}"]
    指數 = pd.concat(pd.read_csv(f) for f in sorted((資料夾 / "index").glob("*.csv"))[-2:]).drop_duplicates("date")
    指數 = 指數.set_index("date")["close"]
    基 = 指數[指數.index < f"{起:%Y-%m-%d}"]
    if len(基):
        行們.append(f"加權 {指數.iloc[-1]:,.0f}，本週 {(指數.iloc[-1] / 基.iloc[-1] - 1) * 100:+.2f}%")
    上 = 週漲.dropna()
    上 = 上[上.index.str.fullmatch(r"\d{4}")]
    行們.append(f"本週上漲 {(上 > 0).sum()} 檔／下跌 {(上 < 0).sum()} 檔")

    持股 = os.environ.get("HOLDINGS", "").strip()
    庫存們 = []
    if 持股:
        h = pd.read_csv(io.StringIO(持股), dtype={"代號": str})
        h["代號"] = h["代號"].str.strip()
        h = h.join(本週["close"].rename("今"), on="代號").join(上週["close"].rename("前"), on="代號").dropna(subset=["今", "前"])
        庫存們 = h["代號"].tolist()
        損益 = ((h["今"] - h["前"]) * h["股數"]).sum()
        行們 += ["", f"💼 庫存本週 {損益:+,.0f} 元（{損益 / (h['前'] * h['股數']).sum() * 100:+.2f}%）"]
        g = h.assign(幅=(h["今"] / h["前"] - 1) * 100).groupby("代號")["幅"].first().sort_values(ascending=False)
        行們.append("　" + "、".join(f"{本週.at[c, 'name']} {v:+.1f}%" for c, v in g.items()))

    自選, _ = 讀設定("watchlist.json")
    群們 = {k: v for k, v in 自選.items() if not k.startswith("_")}
    自選們 = list(dict.fromkeys(c for v in 群們.values() for c in v))
    if 自選們:
        行們 += ["", "⭐ 自選股本週"]
        for 群, v in 群們.items():
            幅 = 週漲.reindex(v).dropna()
            if len(幅):
                強 = 幅.sort_values(ascending=False)
                行們.append(f"{群}（平均 {幅.mean():+.1f}%）：" + "、".join(f"{本週.at[c, 'name']} {x:+.1f}%" for c, x in 強.head(8).items()))

    try:
        import etf_data
        變 = etf_data.每日變化(etf_data.讀持股(天數=8), etf_data.讀資訊())
        週 = 變[(變["date"] >= 起) & (變["date"] <= 迄)] if not 變.empty else 變
        if not 週.empty:
            金 = 週.groupby("code").agg(名稱=("name", "first"), 金額=("adj_amount", "sum")).dropna()
            加 = 金.nlargest(5, "金額")
            減 = 金.nsmallest(5, "金額")
            行們 += ["", "🏦 主動式 ETF 本週合計（扣除申贖）",
                    "加碼：" + "、".join(f"{c} {r['名稱']} {r['金額'] / 1e8:+.1f} 億" for c, r in 加.iterrows() if r["金額"] > 0),
                    "減碼：" + "、".join(f"{c} {r['名稱']} {r['金額'] / 1e8:+.1f} 億" for c, r in 減.iterrows() if r["金額"] < 0)]
    except Exception as e:
        print("ETF 週統計失敗：", repr(e))

    日程 = engine.重要日程(set(庫存們 + 自選們), 天數=9)
    if len(日程):
        行們 += ["", "📅 下週日程"] + [f"{r['日期']:%m/%d} {r['類型']} {r['股票'] if r['代號'] else ''} {r['說明'][:40]}".replace("  ", " ")
                                     for _, r in 日程.iterrows()]
    行們.append("（僅供參考，非投資建議）")
    推播("\n".join(行們))


def 大盤解讀(模式):
    """AI 大盤解讀：整理網站同一套大盤數據＋即時國際行情，請 AI 寫成白話解讀，存到 ai-reports 分支 briefs.json 並傳 LINE。"""
    import re
    import engine
    設定 = {k: os.environ.get(k, "") for k in ("GEMINI_API_KEY", "GEMINI_MODEL", "ANTHROPIC_API_KEY", "AI_MODEL", "GITHUB_TOKEN")}
    設定 = {k: v for k, v in 設定.items() if v}
    設定["AI_REPO"] = 倉庫
    if not (設定.get("GEMINI_API_KEY") or 設定.get("ANTHROPIC_API_KEY")):
        print("沒有設定 GEMINI_API_KEY 或 ANTHROPIC_API_KEY，略過 AI 大盤解讀")
        return
    現在 = dt.datetime.now(台北)
    if os.environ.get("BRIEF_AUTO") == "1":  # 排程或外部定時觸發：已寫過、或時間太晚就不重複發
        if f"{現在:%Y-%m-%d}_{模式}" in engine.讀取大盤解讀(設定):
            print(f"今天的{模式}解讀已經寫過，略過")
            return
        太晚 = {"盤前": 現在.time() > dt.time(9, 30), "夜盤": 現在.hour < 12}.get(模式, False)
        if 太晚:
            print(f"排程延遲到 {現在:%H:%M} 才執行，{模式}解讀已失去時效，略過")
            return
    if 模式 == "收盤":
        日期, _ = 最新行情()
        if 日期.date() != dt.datetime.now(台北).date():
            print(f"最新資料是 {日期:%m/%d}，今天休市，不寫收盤解讀")
            return
    原始 = engine.讀取資料庫(最近天數=130)
    指標 = engine.計算指標(原始)
    del 原始
    try:
        國際, 期貨 = engine.國際行情(), engine.台指期()
    except Exception as e:
        print("國際行情失敗：", repr(e))
        國際, 期貨 = {}, {}
    摘要 = engine.大盤摘要(指標, engine.讀取加權指數(), 國際, 期貨)
    print(摘要)
    內容, 模型 = engine.AI大盤解讀(摘要, 模式, 設定)
    try:
        engine.儲存大盤解讀(設定, 模式, 內容, 模型)
    except Exception as e:
        print("存檔失敗：", repr(e))
    文字 = re.sub(r"^#+\s*", "▍", engine.拆解解讀條件(內容)[0], flags=re.M).replace("**", "")
    推播(f"🧠 {模式}大盤解讀（{dt.datetime.now(台北):%m/%d %H:%M}）\n\n{文字}")


if __name__ == "__main__":
    模式 = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if 模式 == "test":
        推播("✅ 台股觀測實驗室：LINE 推播設定成功！之後每個交易日收盤後會傳摘要給你。")
    elif 模式 == "alert":
        盤中提醒()
    elif 模式 == "health":
        健康檢查()
    elif 模式 == "weekly":
        週報()
    elif 模式 == "brief":
        大盤解讀(sys.argv[2] if len(sys.argv) > 2 else "收盤")
    else:
        收盤摘要(強制=模式 == "daily-force")
