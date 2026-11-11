# LINE 推播：每天收盤摘要、盤中到價提醒（由 GitHub Actions 執行）
#   python notify.py daily   收盤摘要（大盤、強弱族群、自選股、庫存損益、到價、80 分以上名單與新增／剔除）
#   python notify.py alert   盤中檢查到價提醒（同一個提醒一天只通知一次）
#   python notify.py test    傳一則測試訊息
#   python notify.py health  檢查各資料來源有沒有正常更新，有問題才通知（休市日不算問題）
#   python notify.py weekly  每週六週報（大盤、庫存、自選股一週表現，主動式 ETF 一週加減碼，下週日程）
#   python notify.py query 2330  查一檔股票（LINE 打字查詢用，由 Cloudflare Worker 觸發 query.yml）
#   python notify.py brief 盤前|收盤|夜盤  AI 大盤解讀（要設定 GEMINI_API_KEY 或 ANTHROPIC_API_KEY），存到 ai-reports 並傳 LINE
#
# 需要在 GitHub 專案 Settings → Secrets and variables → Actions 設定：
#   LINE_TOKEN    LINE Messaging API 的 Channel access token（必填）
#   LINE_USER_ID  你的 LINE User ID（選填；沒填就用 broadcast 傳給所有加好友的人，只有你自己的話效果一樣）
#   HOLDINGS      庫存 CSV（選填，跟 Streamlit Secrets 的 holdings 一樣格式），有填才會附上今日損益
#   SITE_PASSWORD 網站密碼（選填，跟 Streamlit Secrets 的 password 一樣）。有填就直接讀網站上改過的庫存與交易日記
#                 （停損價跌破會通知），不用再手動改 HOLDINGS
# 自選股與到價提醒在網站上設定，存在 ai-reports 分支的 watchlist.json、alerts.json。

import base64
import datetime as dt
import io
import json
import os
import sys
from pathlib import Path

import numpy as np
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


_日記快取 = {}


def 讀日記():
    """網站的交易日記（ai-reports 分支 journal.json，有設密碼會加密），要設定 SITE_PASSWORD 才解得開。"""
    if "v" not in _日記快取:
        日記 = {}
        包, _ = 讀設定("journal.json")
        if 包:
            try:
                import engine
                日記 = engine.解密(包, os.environ.get("SITE_PASSWORD", "").strip()) if 包.get("加密") else 包
            except Exception as e:
                print("交易日記解不開（SITE_PASSWORD 沒設或不對）：", repr(e))
        _日記快取["v"] = 日記
    return _日記快取["v"]


def 持股文字():
    """庫存 CSV 文字（代號,股數,總成本）。順序跟網站一樣：交易日記勾「當作庫存」→ 網站上的庫存清單
    → Secrets HOLDINGS → 交易日記推算。"""
    日記 = 讀日記()
    推算 = None
    if 日記.get("交易"):
        import engine
        推算 = engine.交易日記統計(日記["交易"])[1]
    欄 = ["代號", "股數", "總成本"]
    if 日記.get("當作庫存") and 推算 is not None and len(推算):
        return 推算[欄].to_csv(index=False)
    if 日記.get("庫存清單"):
        return pd.DataFrame(日記["庫存清單"], columns=欄).to_csv(index=False)
    h = os.environ.get("HOLDINGS", "").strip()
    if h:
        return h
    return 推算[欄].to_csv(index=False) if 推算 is not None and len(推算) else ""


def 停損們():
    """還持有、最近一筆買進有記停損價的股票 → {代號: 停損價}。"""
    日記 = 讀日記()
    if not 日記.get("交易"):
        return {}
    import engine
    庫 = engine.交易日記統計(日記["交易"])[1]
    結果 = {}
    for 代 in (庫["代號"] if 庫 is not None and len(庫) else []):
        買們 = [t for t in 日記["交易"] if str(t["代號"]) == 代 and t["買賣"] == "買" and t.get("停損")]
        if 買們:
            結果[代] = float(max(買們, key=lambda x: x["日期"])["停損"])
    return 結果


def 停損提醒(t):
    行們 = []
    for 代, 停 in 停損們().items():
        列 = t[t["code"] == 代]
        if len(列) and 列["close"].iloc[0] <= 停:
            行們.append(f"{名稱(t, 代)} 收 {列['close'].iloc[0]:,.2f}，已跌破停損 {停:g}")
    return ["", "🛑 停損（交易日記）"] + 行們 if 行們 else []


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
    # 一則最多 5000 字，太長就照換行切成多則（一次送最多 5 則，只算 1 次推播額度）
    段們, 段 = [], ""
    for 行 in 文字.split("\n"):
        if len(段) + len(行) + 1 > 4900 and 段:
            段們.append(段)
            段 = ""
        段 = (段 + "\n" + 行) if 段 else 行[:4900]
    段們.append(段)
    內容 = {"messages": [{"type": "text", "text": t} for t in 段們[:5]]}
    if 對象:
        內容["to"] = 對象
    r = requests.post(網址, headers={"Authorization": f"Bearer {權杖}"}, json=內容, timeout=15)
    print("LINE 回應", r.status_code, r.text[:200])
    if r.status_code == 401:
        print(f"金鑰長度 {len(權杖)} 個字（正確的 Channel access token 通常 170 字左右；"
              "32 個字的是 Channel secret，貼錯了）")
    r.raise_for_status()


def 送出(訊息們):
    """傳多則訊息（LINE message object，最多 5 則算 1 次）。有 REPLY_TOKEN（LINE 打字查詢）先用「回覆」，
    回覆不算每月免費額度；權杖過期或用過了就改用推播。"""
    權杖 = 清理(os.environ.get("LINE_TOKEN"))
    訊息們 = [m for m in 訊息們 if m][:5]
    if not 訊息們:
        return
    if not 權杖:
        print("沒有設定 LINE_TOKEN，略過。內容如下：\n" + json.dumps(訊息們, ensure_ascii=False, indent=1))
        return
    標頭 = {"Authorization": f"Bearer {權杖}"}
    回覆 = 清理(os.environ.pop("REPLY_TOKEN", ""))   # 回覆權杖只能用一次
    if 回覆:
        r = requests.post("https://api.line.me/v2/bot/message/reply", headers=標頭, timeout=15,
                          json={"replyToken": 回覆, "messages": 訊息們})
        print("LINE 回覆", r.status_code, r.text[:200])
        if r.ok:
            return
    對象 = 清理(os.environ.get("LINE_USER_ID"))
    內容 = {"messages": 訊息們}
    if 對象:
        內容["to"] = 對象
    r = requests.post("https://api.line.me/v2/bot/message/" + ("push" if 對象 else "broadcast"),
                      headers=標頭, json=內容, timeout=15)
    print("LINE 推播", r.status_code, r.text[:200])
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

    持股 = 持股文字().strip()
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
        行們 += 停損提醒(t)
    except Exception as e:
        print("停損提醒失敗：", repr(e))

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
        行們 += 集體升降評提醒(狀態)
    except Exception as e:
        print("集體升降評失敗：", repr(e))
    try:
        行們 += 條件訂閱提醒(狀態)
    except Exception as e:
        print("選股訂閱失敗：", repr(e))
    try:
        行們 += 董監轉讓提醒(代號們, 狀態)
    except Exception as e:
        print("董監轉讓失敗：", repr(e))
    try:
        行們 += 網紅條件提醒(狀態)
    except Exception as e:
        print("網紅條件失敗：", repr(e))
    try:
        行們 += 興櫃承銷提醒(代號們, 狀態)
    except Exception as e:
        print("興櫃承銷失敗：", repr(e))
    try:
        行們 += 自選重訊提醒(代號們, 狀態)
    except Exception as e:
        print("自選重訊失敗：", repr(e))
    try:
        行們 += 預估修正提醒(代號們, 狀態)
    except Exception as e:
        print("預估修正提醒失敗：", repr(e))
    try:
        行們 += 跌深融資提醒(狀態)
    except Exception as e:
        print("跌深融資提醒失敗：", repr(e))
    try:
        行們 += 大盤融資洗盤提醒(狀態)
    except Exception as e:
        print("大盤融資洗盤提醒失敗：", repr(e))
    try:
        行們 += 台幣提醒(狀態)
    except Exception as e:
        print("台幣提醒失敗：", repr(e))
    try:
        行們 += 季線VIX提醒(狀態)
    except Exception as e:
        print("季線／VIX 提醒失敗：", repr(e))
    try:
        行們 += 領頭站回提醒(狀態)
    except Exception as e:
        print("領頭站回提醒失敗：", repr(e))
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


def 台幣提醒(狀態):
    """美元兌台幣接近一年高點（台幣最弱）或台幣與外資同步流出入時通知；同一種警示 5 天內只通知一次。"""
    import engine
    import macro
    匯 = engine.讀取匯率()
    if 匯 is None or len(匯) < 30:
        return []
    外資億 = None
    價 = engine.讀取資料庫(最近天數=10)
    if 價 is not None and "foreign" in 價:
        外資億 = (價["foreign"].astype(float) * 價["close"].astype(float)).groupby(價["date"]).sum() / 1e8
    結 = macro.台幣外資(匯, 外資億)
    if not 結 or not 結["警示"]:
        return []
    今 = dt.datetime.now(台北).date()
    記 = 狀態.setdefault("fx", {})
    新 = []
    for w in 結["警示"]:
        鍵 = "high" if "一年高點" in w else ("out" if "流出" in w else "in")
        上次 = 記.get(鍵)
        if 上次 and (今 - dt.date.fromisoformat(上次)).days < 5:
            continue
        記[鍵] = 今.isoformat()
        新.append(w)
    return (["", "💱 台幣與外資"] + 新) if 新 else []


def 領頭站回提醒(狀態):
    """data/leader_groups.csv 的領頭股今天站回月線（前 10 天都在月線下）就通知一次，附同組跟隨股。"""
    import engine
    組 = engine.讀取領頭連動()
    if 組.empty:
        return []
    代們 = set(組["領頭"]) | {c for x in 組["跟隨"] for c in x.split()}
    表 = engine.讀取資料庫(最近天數=60, 代號=list(代們))
    if 表 is None or not len(表):
        return []
    t = 表.rename(columns={"code": "代號", "close": "收盤"})[["代號", "date", "收盤"]]
    行們 = []
    日 = f"{pd.to_datetime(t['date']).max():%Y-%m-%d}"
    for 名, 頭, 跟 in engine.今日領頭站回(組, t):
        鍵 = f"領頭站回_{頭}"
        if 狀態.get(鍵) == 日:
            continue
        狀態[鍵] = 日
        行們 += ["", f"🚩 {名}：領頭股 {頭} 今天站回月線，同組 {跟} 可以留意是否跟上（只是連動觀察，不是買進訊號）"]
    return 行們


def 季線VIX提醒(狀態):
    """股癌 EP712：加權季線保衛戰狀態改變（等站上 → 站上第 N 天 → 站穩／又跌破）、VIX 單日跳升 ≥ 30% 時通知。
    季線狀態只在「燈」改變時通知（第一次執行只記錄）；VIX 同一天只通知一次。"""
    import engine
    行們 = []
    K = engine.讀取指數K線("TAIEX")
    狀 = engine.季線狀態(K)
    if 狀:
        舊 = 狀態.get("季線燈")
        狀態["季線燈"] = 狀["燈"]
        if 舊 and 舊 != 狀["燈"] and 狀["燈"] != "⚪":
            行們 += ["", f"📏 季線保衛戰：{狀['燈']} {狀['狀態']}（季線 {狀['季線']:,.0f}、乖離 {狀['乖離%']:+.1f}%）", 狀["說明"]]
    v = engine.讀取VIX長線()
    for d, 名, 值, 變 in engine.VIX今日觸發(v, 最近天數=1):
        鍵 = f"{d:%Y-%m-%d}"
        if 狀態.get("VIX跳升_最後") == 鍵:
            break
        狀態["VIX跳升_最後"] = 鍵
        f = engine.資料夾 / "sox_long.csv"
        話 = ""
        if f.exists():
            t = pd.read_csv(f, parse_dates=["date"])
            標 = t[t["symbol"] == "^GSPC"].set_index("date")["close"]
            表, _ = engine.VIX跳升統計(v, 標)
            r = 表[表["條件"] == 名]
            if len(r) and r["次數"].iloc[0]:
                r = r.iloc[0]
                話 = f"1994 年來（含這次）{r['次數']:.0f} 次，S&P 500 之後 20 日上漲 {r['20日上漲%']:.0f}%、平均 {r['20日平均%']:+.1f}%；250 日 {r['250日平均%']:+.1f}%"
        行們 += ["", f"😨 {d:%m/%d} {名}：VIX {值:.1f}（單日 {變:+.0f}%）", 話 or "短線常是好買點，但先想清楚是做反彈還是長抱。"]
        break
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
    try:  # 選股條件可能用到預估本益比（網站今日表也有加）
        預 = engine.預估EPS表()
        if 預 is not None:
            今日 = engine.加預估本益比(今日.join(預, on="代號"))
    except Exception as e:
        print("預估 EPS 加入失敗：", repr(e))
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


def 預估修正提醒(代號們, 狀態, 門檻=5.0, 最多=15):
    """上傳新一份預估 EPS 快照後，庫存＋自選股的今年預估跟上一份比上修／下修超過 門檻% 就通知（每份快照只通知一次）。"""
    import engine
    t = engine.預估EPS表()
    if t is None or "預估修正%" not in t.columns:
        return []
    日 = f"{pd.Timestamp(t['預估資料日'].iloc[0]):%Y-%m-%d}"
    if 狀態.get("預估修正_日") == 日:
        return []
    狀態["預估修正_日"] = 日
    t = t.reindex([c for c in dict.fromkeys(代號們) if c in t.index])
    修 = t["預估修正%"].dropna()
    下, 上 = 修[修 <= -門檻].sort_values(), 修[修 >= 門檻].sort_values(ascending=False)
    if not len(下) and not len(上):
        return []
    try:
        _, 行情 = 最新行情()
        名表 = dict(zip(行情["code"], 行情["name"]))
    except Exception:
        名表 = {}
    前 = pd.Timestamp(t["前期資料日"].dropna().iloc[0]) if t["前期資料日"].notna().any() else None
    def 行(c, v):
        r = t.loc[c]
        return f"{'🔻' if v < 0 else '🔺'} {c} {名表.get(c, '')} 今年預估 EPS {r['前期預估EPS今年']:.2f} → {r['預估EPS今年']:.2f}（{v:+.1f}%）"
    行們 = ["", f"📐 預估 EPS 修正（庫存＋自選，{前:%m/%d} → {日[5:].replace('-', '/')}）" if 前 else "📐 預估 EPS 修正（庫存＋自選）"]
    行們 += [行(c, v) for c, v in 下.head(最多).items()] + [行(c, v) for c, v in 上.head(最多).items()]
    return 行們


def 跌深融資提醒(狀態, 冷卻天數=30):
    """0050 成分股（跌深榜）剛出現「🧹 融資洗完」就通知，同一檔 30 天內只通知一次；第一次執行只記錄不通知。
    融資約 21:00 才公布，收盤摘要用的是最近一次公布的融資。"""
    import engine
    指標 = engine.計算指標(engine.讀取資料庫(最近天數=300))   # 融資成本要夠長的歷史才估得準
    最新 = 指標["date"].max()
    今日 = engine.加基本面(指標[指標["date"] == 最新], engine.讀取基本面())
    榜, _ = engine.跌深榜(今日)
    初次 = "跌深_啟用" not in 狀態
    今天 = pd.Timestamp(dt.datetime.now(台北).date())
    行們 = []
    for _, r in 榜[榜["融資洗完"].astype(bool)].iterrows():
        鍵 = f"跌深洗完_{r['代號']}"
        if 鍵 in 狀態 and (今天 - pd.Timestamp(狀態[鍵])).days < 冷卻天數:
            continue
        狀態[鍵] = f"{今天:%Y-%m-%d}"
        if not 初次:
            行們.append(f"🧹 {r['代號']} {r['名稱']} 距今年高點 {r['距今年高點']:+.1f}%、融資維持率約 {r['融資維持率']:.0f}%、"
                       f"融資 20 日 {r['融資20日增減']:+.1f}%")
    狀態["跌深_啟用"] = 狀態.get("跌深_啟用", f"{今天:%Y-%m-%d}")
    return (["", "📉 0050 跌深股融資洗完（實測比單純跌深好，仍要設停損）"] + 行們) if 行們 else []


def 大盤融資洗盤提醒(狀態, 門檻=-1.5):
    """大盤融資單日減少超過 1.5%（融資洗盤日）就通知一次，附 5 年回測與融資維持率離 165%／130% 還多遠。
    融資約 21:00 才公布，所以通常隔天的收盤摘要才看得到前一天的洗盤。"""
    import engine
    表 = engine.讀取資料庫(最近天數=6)
    變 = engine.大盤融資變化(表)
    if not len(變):
        return []
    日, v = 變.index[-1], float(變.iloc[-1])
    if v > 門檻 or 狀態.get("融資洗盤_最後") == f"{日:%Y-%m-%d}":
        return []
    狀態["融資洗盤_最後"] = f"{日:%Y-%m-%d}"
    行們 = ["", f"🧹 大盤融資洗盤日 {日:%m/%d}：融資單日 {v:+.2f}%（門檻 {門檻}%）"]
    洗 = engine.讀取大盤融資洗盤() or {}
    for r in 洗.get("洗盤", {}).get("統計", []):
        if r["天數"] == 20 and r.get("次數"):
            行們.append(f"過去 {r['次數']} 次，20 日後上漲 {r['上漲機率%']}%、平均 {r['平均%']:+.1f}%（一般日子 {r['基準平均%']:+.1f}%）")
    try:
        指 = engine.計算指標(engine.讀取資料庫(最近天數=3))
        維 = engine.融資維持率(指)
        K = engine.讀取指數K線("TAIEX")
        if 維 is not None and len(維) and K is not None:
            收 = K.set_index("date")["close"].asof(維.index[-1])
            點們 = engine.維持率警戒點位(float(維.iloc[-1]), float(收))
            if 點們:
                行們.append(f"上市融資維持率約 {維.iloc[-1]:.0f}%（網站估算）；" + "、".join(f"到 {a}% 加權約 {b:,.0f}" for a, b, _ in 點們[:2]))
    except Exception as e:
        print("維持率估算失敗：", repr(e))
    行們.append("洗盤後偏多但不保證，還是要等止跌訊號、設停損。")
    return 行們


def 集體升降評提醒(狀態):
    """近 3 天 3 家以上券商同方向改目標價（同一檔同方向只通知一次）。"""
    import engine
    報告們 = (讀設定("broker_reports.json")[0] or {}).get("報告", [])
    行們 = []
    for 代, 名, 方向, 家, 名們 in engine.集體升降評(報告們):
        鍵 = f"集體_{代}_{方向}"
        if 狀態.get(鍵) != 家:
            狀態[鍵] = 家
            行們.append(f"{代} {名}：{家} 家{方向}目標價（{名們[:40]}）")
    return ["", "📣 券商集體調整目標價（近 3 天）"] + 行們 if 行們 else []


def 董監轉讓提醒(代號們, 狀態):
    """庫存、自選股的董監大股東申報轉讓（同一筆只通知一次）。"""
    import engine
    轉 = engine.讀取內部人轉讓()
    if 轉 is None or not len(轉):
        return []
    轉 = 轉[(轉["date"] >= 轉["date"].max() - pd.Timedelta(days=3)) & 轉["code"].isin(set(代號們))]
    行們 = []
    for _, x in 轉.iterrows():
        鍵 = f"轉讓_{x['code']}_{x['date']:%Y%m%d}_{x['姓名']}"
        if 狀態.get(鍵):
            continue
        狀態[鍵] = 1
        比 = f"，佔其持股 {x['股數'] / x['持股'] * 100:.0f}%" if x["持股"] else ""
        行們.append(f"{x['code']} {x['身分']} {x['姓名']}：{str(x['方式']).split('(')[0]} {x['股數'] / 1000:,.0f} 張{比}")
    return ["", "🧾 董監申報轉讓（庫存／自選）"] + 行們 if 行們 else []


def 網紅條件提醒(狀態, 天數=30):
    """網紅影片裡看得懂的「如果…就…」條件，從「還沒」變成「成立」時通知一次。"""
    import engine
    import hashlib
    影片們 = (讀設定("influencer_notes.json")[0] or {}).get("影片", [])
    if not 影片們:
        return []
    最新 = engine.讀取資料庫(最近天數=7)
    名表 = {}
    if 最新 is not None and "name" in 最新:
        最新 = 最新[最新["date"] == 最新["date"].max()]
        名表 = dict(zip(最新["name"], 最新["code"]))
    清單 = engine.網紅條件清單(影片們, 天數=天數, 名表=名表)
    代們 = sorted({r["代號"] for r in 清單 if r["代號"] and r["代號"] != "TAIEX"})
    價 = engine.讀取資料庫(最近天數=200, 代號=代們) if 代們 else None
    K加, 匯 = engine.讀取指數K線("TAIEX"), engine.讀取匯率()
    行們 = []
    for r in 清單:
        K = K加 if r["代號"] == "TAIEX" else (價[價["code"] == r["代號"]].sort_values("date")
                                            if 價 is not None and r["代號"] else None)
        狀, 說 = engine.檢查條件(r["條件"], r["標的"] or "", K, 匯, None)
        if not 狀:
            continue
        鍵 = "網紅條件_" + hashlib.md5(f"{r['頻道']}{r['條件']}".encode()).hexdigest()[:10]
        if 狀態.get(鍵) == "未成立" and 狀 == "成立":
            行們.append(f"{r['頻道']}（{r['日期']:%m/%d}）：{r['條件'][:50]}\n  → {說}")
        狀態[鍵] = 狀
    return ["", "🎬 網紅條件成立了"] + 行們[:8] if 行們 else []


def 興櫃承銷提醒(代號們, 狀態):
    """庫存／自選的推薦券商變動，以及所有公司新的申請上市櫃、審議通過重大訊息（同一則只通知一次）。"""
    import engine
    行們 = []
    變 = engine.讀取推薦變動()
    if 變 is not None and len(變):
        近 = 變[(變["date"] >= 變["date"].max() - pd.Timedelta(days=3)) & 變["code"].isin(set(代號們))]
        for _, x in 近.iterrows():
            鍵 = f"推薦_{x['code']}_{x['dealer']}_{x['change']}"
            if not 狀態.get(鍵):
                狀態[鍵] = 1
                行們.append(f"{x['code']} {x.get('name', '')}：{x['dealer']} {x['change']}")
    訊 = engine.讀取重大訊息()
    if 訊 is not None and len(訊):
        近 = 訊[(訊["date"] >= 訊["date"].max() - pd.Timedelta(days=3)) & 訊["subject"].str.contains(engine.掛牌字, na=False)]
        for _, x in 近.tail(8).iterrows():
            鍵 = f"重訊_{x['code']}_{x['date']:%Y%m%d}_{str(x['subject'])[:12]}"
            if not 狀態.get(鍵):
                狀態[鍵] = 1
                行們.append(f"{x['code']} {x['name']}：{str(x['subject'])[:50]}")
    return ["", "🌱 興櫃推薦券商／掛牌消息"] + 行們 if 行們 else []


def 自選重訊提醒(代號們, 狀態, 上限=10):
    """庫存、自選股近 3 天的重大訊息（公開資訊觀測站全部重訊，同一則只通知一次）。"""
    import engine
    訊 = engine.讀取全部重訊(天數=5)
    if 訊 is None or not 代號們:
        return []
    近 = 訊[(訊["date"] >= 訊["date"].max() - pd.Timedelta(days=3)) & 訊["code"].isin(set(代號們))]
    期限 = f"{pd.Timestamp.now() - pd.Timedelta(days=30):%Y%m%d}"
    for k in [k for k in 狀態 if k.startswith("自選重訊_") and k.split("_")[2] < 期限]:
        del 狀態[k]   # 一個月前的不用記了，免得狀態檔越來越大
    行們 = []
    for _, x in 近.sort_values(["date", "time"]).iterrows():
        鍵 = f"自選重訊_{x['code']}_{x['date']:%Y%m%d}_{str(x['subject'])[:12]}"
        if 狀態.get(鍵):
            continue
        狀態[鍵] = 1
        行們.append(f"{x['code']} {x['name']}（{x['date']:%m/%d}）：{str(x['subject'])[:50]}")
    if not 行們:
        return []
    多 = len(行們) - 上限
    return ["", "📢 自選股重大訊息"] + 行們[:上限] + ([f"…還有 {多} 則，到網站個股頁看"] if 多 > 0 else [])


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
            行們 += [f"{r['名稱']} {r['總分']:.1f} {r['看法']} {變(r['較昨日'])}".rstrip() for _, r in 庫.iterrows()]
    庫存們 = pd.read_csv(io.StringIO(持股), dtype={"代號": str})["代號"].str.strip().tolist() if 持股 else []
    大變 = 分.reindex(list(dict.fromkeys(庫存們 + list(自選們)))).dropna(subset=["總分", "較昨日"])
    大變 = 大變[大變["較昨日"].abs() >= 10].sort_values("較昨日")
    if len(大變):
        行們.append("📈 評分大變動（一天 ±10 分以上）：" + "、".join(
            f"{r['名稱']} {r['總分'] - r['較昨日']:.1f}→{r['總分']:.1f}" for _, r in 大變.iterrows()))
    可 = 分[(分["5日均量"] >= 500) & ~分.index.str.startswith("00")]
    新 = 可[(可["總分"] >= 75) & ((可["總分"] - 可["較昨日"].fillna(0)) < 75)].sort_values("總分", ascending=False)
    if len(新):
        行們.append("🆕 新進 75 分以上：" + "、".join(f"{r['名稱']} {r['總分']:.1f}" for _, r in 新.head(15).iterrows()))
    高 = 可.sort_values("總分", ascending=False).head(10)
    行們.append("🔝 高分前 10：" + "、".join(f"{r['名稱']} {r['總分']:.1f}" for _, r in 高.iterrows()))
    try:
        行們 += 八十分名單(可, 分, 庫存們, list(自選們), 大.get("日期"))
    except Exception as e:
        print("80 分名單失敗：", repr(e))
    行們.append("（規則計分，僅供參考，非投資建議）")
    return 行們


高分門檻 = 80
高分名單檔 = "score80_list.json"


def 高分名單變化(分, 日期, 存檔, 門檻=高分門檻, 庫存們=(), 自選們=(), 全=None, 價=None, 價說明="收盤"):
    """總分 ≥ 門檻 的名單，跟「前一交易日推播的名單」比對新增與剔除。
    存檔 = {"日期", "名單": {代號: [名稱, 總分]}, "前一日": {...}}；同一天重跑時跟「前一日」比，不會把自己當成昨天。
    沒有存檔（第一次跑）就用評分的「較昨日」推算昨天分數。分＝有入選資格的股票，全＝全部（查剔除股現在幾分）。
    價＝{代號: (股價, 漲跌幅%)}，沒給就用評分表的收盤、漲跌幅。回傳 (訊息行們, 新存檔)。"""
    日 = f"{pd.Timestamp(日期):%Y-%m-%d}"
    今 = 分[分["總分"] >= 門檻].sort_values("總分", ascending=False)
    今名單 = {c: [str(r["名稱"]), round(float(r["總分"]), 1)] for c, r in 今.iterrows()}
    前 = None
    if 存檔.get("日期") and 存檔["日期"] < 日:
        前 = 存檔
    elif 存檔.get("日期") == 日 and 存檔.get("前一日"):
        前 = 存檔["前一日"]
    if 前 is not None:
        前名單, 前日 = 前.get("名單", {}), 前.get("日期", "")
    else:   # 第一次：用今昨評分推回昨天的分數
        昨分 = 分["總分"] - 分["較昨日"]
        前名單 = {c: [str(分.at[c, "名稱"]), round(float(v), 1)] for c, v in 昨分.items() if pd.notna(v) and v >= 門檻}
        前日 = ""
    標 = lambda c: ("💼" if c in 庫存們 else "⭐" if c in 自選們 else "")
    新增 = [c for c in 今名單 if c not in 前名單]
    剔除 = sorted((c for c in 前名單 if c not in 今名單), key=lambda c: -前名單[c][1])
    比對 = f"（比 {前日[5:].replace('-', '/')}）" if 前日 else "（比前一交易日）"
    表 = 分 if 全 is None else 全
    價 = dict(價 or {})
    for c in list(今名單) + 剔除:
        if c not in 價 and c in 表.index and "收盤" in 表.columns:
            價[c] = (表.at[c, "收盤"], 表.at[c, "漲跌幅"] if "漲跌幅" in 表.columns else np.nan)
    def 價字(c):
        p, f = 價.get(c, (np.nan, np.nan))
        if pd.isna(p):
            return ""
        return f"｜{p:,.2f}" + (f" {符號(f)}{abs(f):.2f}%" if pd.notna(f) else "")
    行們 = ["", f"🏅 {門檻} 分以上 {len(今名單)} 檔（股價：{價說明}）"]
    行們 += [f"{標(c)}{c} {v[0]} {v[1]:.1f}分{價字(c)}" for c, v in 今名單.items()]
    行們.append(f"🟢 新增 {len(新增)} 檔{比對}" + ("：" + "、".join(
        f"{標(c)}{今名單[c][0]}" for c in 新增) if 新增 else ""))
    def 剔(c):
        現 = 表["總分"].get(c)
        return (f"{標(c)}{c} {前名單[c][0]} {前名單[c][1]:.1f}→" + (f"{現:.1f}分" if pd.notna(現) else "無資料")
                + 價字(c))
    行們.append(f"🔴 剔除 {len(剔除)} 檔{比對}" + ("：" if 剔除 else ""))
    行們 += [剔(c) for c in 剔除]
    新存檔 = {"日期": 日, "門檻": 門檻, "名單": 今名單}
    if 前 is not None:
        新存檔["前一日"] = {"日期": 前.get("日期", ""), "名單": 前.get("名單", {})}
    return 行們, 新存檔


def 即時價們(分, 代號們):
    """證交所即時報價（延遲約 5～20 秒；收盤後就是收盤價）→ ({代號: (股價, 漲跌幅%)}, 說明)。抓不到就回空的，改用收盤。"""
    代號們 = list(dict.fromkeys(c for c in 代號們 if c))
    if not 代號們:
        return {}, "收盤"
    try:
        import engine
        市場 = 分["上市櫃"].to_dict() if "上市櫃" in 分.columns else {}
        即 = engine.即時報價(代號們, 市場).dropna(subset=["close"])
    except Exception as e:
        print("即時報價抓不到，改用收盤價：", repr(e))
        return {}, "收盤"
    if 即.empty:
        return {}, "收盤"
    昨 = 即["close"] - 即["change"]
    即 = 即.assign(幅=(即["change"] / 昨 * 100).where(昨 > 0))
    價 = {r["code"]: (r["close"], r["幅"]) for _, r in 即.iterrows()}
    時 = 即["time"].dropna().max() if "time" in 即 else None
    日 = 即["date"].dropna().max() if "date" in 即 else None
    說明 = "即時報價" + (f" {日:%m/%d}" if pd.notna(日) else "") + (f" {str(時)[:5]}" if 時 else "")
    return 價, 說明


def 八十分名單(可, 全, 庫存們, 自選們, 日期):
    存檔, sha = 讀設定(高分名單檔)
    價, 說明 = 即時價們(全, 全.index[全["總分"] >= 高分門檻].tolist() + list((存檔 or {}).get("名單", {})))
    行們, 新存檔 = 高分名單變化(可, 日期 if 日期 is not None else dt.date.today(), 存檔 or {},
                       庫存們=set(庫存們), 自選們=set(自選們), 全=全, 價=價, 價說明=說明)
    try:
        寫設定(高分名單檔, 新存檔, sha)
    except Exception as e:
        print("80 分名單存檔失敗（明天會改用分數推算比對）：", repr(e))
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
    try:
        for c, 停 in 停損們().items():
            提醒.setdefault(c, {})["停損"] = 停
    except Exception as e:
        print("讀停損失敗：", repr(e))
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
        if 設.get("停損") and 價 <= 設["停損"] and 狀態.get(f"{c}_停損") != 今天:
            訊息.append(f"🛑 {m.get('n', c)} 跌破交易日記停損 {設['停損']:g}（現在 {價:,.2f}）{m.get('t', '')}")
            狀態[f"{c}_停損"] = 今天
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

    # 融資約 21:00 才公布，22:23 會補抓；今天以前的籌碼檔還缺融資就是補抓失敗
    缺融 = []
    for f in sorted((資料夾 / "chips").glob("*/*.csv.gz"))[-8:]:
        if pd.Timestamp(f.name[:8]).date() >= 今天:
            continue
        欄 = pd.read_csv(f, nrows=200)
        if "margin" not in 欄.columns or 欄["margin"].notna().sum() < 50:
            缺融.append(f"{pd.Timestamp(f.name[:8]):%m/%d}")
    if 缺融:
        問題.append("融資融券缺漏：" + "、".join(缺融) + "（晚上 22:23 補抓沒成功，可到 Actions 手動跑「補融資融券」）")
    公司 = 資料夾 / "company_profile.csv"
    if 公司.exists():
        更 = pd.read_csv(公司, usecols=["更新日"])["更新日"].dropna()
        # 輪抓是補空缺、每 60 天更新一輪，跑完一輪後最新更新日本來就會停很久；只在最舊的一筆快超過 60 天還沒輪到時才報
        if len(更) and (今天 - pd.Timestamp(更.min()).date()).days > 75:
            問題.append(f"公司介紹資料：最舊一筆更新於 {pd.Timestamp(更.min()):%m/%d}，已超過 75 天沒輪抓")

    def 太舊(名稱, 最新, 容許天數):
        if 最新 is None:
            問題.append(f"{名稱}：沒有資料")
        elif (今天 - 最新).days > 容許天數:
            問題.append(f"{名稱}：最新是 {最新:%Y/%m/%d}，已經 {(今天 - 最新).days} 天沒更新")

    def 讀(檔, 欄):
        f = 資料夾 / 檔
        return pd.read_csv(f, usecols=[欄])[欄].astype(str).max() if f.exists() else None

    太舊("集保股權分散（每週）", _最新檔日("tdcc"), 10)
    # 借券賣出（TWT93U、櫃買 sbl）和融資一樣約 21:00 後才公布，18:17 更新時只會有前一個交易日，
    # 22:23「補融資融券」會補當天的；所以落後一個交易日是正常，落後兩個交易日以上才算抓取失敗
    借 = _最新檔日("sbl")
    交易日們 = sorted({pd.Timestamp(f.name[:8]).date() for f in (資料夾 / "prices").glob("*/*.csv.gz")})
    前一交易日 = 交易日們[-2] if len(交易日們) >= 2 else 價
    if 價 and 借 is None:
        問題.append("沒有借券賣出資料")
    elif 價 and 借 < 前一交易日:
        問題.append(f"借券賣出資料落後（最新 {借:%m/%d}，股價 {價:%m/%d}；晚上 22:23 補抓也沒補到，"
                    "可到 Actions 手動跑「補融資融券」）")
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
    # 只看最近 4 天內還有發生的錯誤（涵蓋週末）：已經修好、不再發生的舊錯誤，
    # 就算通知紀錄沒存成功（例如沒有 GITHUB_TOKEN），也不會每天重複推播
    界線 = (dt.datetime.now(台北) - dt.timedelta(days=4)).strftime("%Y-%m-%d %H:%M")
    新 = [(k, v) for k, v in 紀錄.items()
         if v.get("次數", 0) > 已通知.get(k, 0) and str(v.get("最近", "")) >= 界線]
    if not 新:
        return []
    狀態["網站錯誤已通知"] = {**已通知, **{k: v["次數"] for k, v in 新}}
    try:
        寫設定("alert_state.json", 狀態, sha)
    except Exception as e:
        print("⚠️ 網站錯誤的通知紀錄存檔失敗，下次可能重複通知：", repr(e))
    return [f"{v['頁面']}：{v['類型']} {v['訊息'][:80]}（{v.get('位置', '')}，共 {v['次數']} 次，最近 {v['最近']}）" for _, v in 新]


def 主動ETF月報(迄):
    """上個月、今年以來，主動式 ETF 對同 beta 組合（台股型＝0050＋正 2）的超額前 3、後 3 名。"""
    import engine
    import etf_perf
    月起 = (迄.replace(day=1) - pd.DateOffset(months=1)).normalize()
    月迄 = 迄.replace(day=1) - pd.Timedelta(days=1)
    年起 = pd.Timestamp(f"{月迄.year}-01-01")
    原始 = engine.讀取資料庫(起日=min(年起, 月起) - pd.Timedelta(days=30))
    指標 = engine.計算指標(原始)
    del 原始
    主 = etf_perf.主動式代號(指標["code"].unique())
    寬 = etf_perf.報酬寬表(指標, 主 + ["0050", etf_perf.正2代號] + sorted(set(etf_perf.基準名) - {"0050"}))
    名 = 指標.drop_duplicates("code", keep="last").set_index("code")["名稱"].str.replace("主動", "", regex=False).to_dict()
    行們 = etf_perf.月報文字(寬, 主, 月起, 月迄, 年起, 名)
    if 行們:
        行們[1] = 行們[1].replace("📊 主動式 ETF", f"📊 主動式 ETF {月起:%m} 月報")
    return 行們


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

    持股 = 持股文字().strip()
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

    if 迄.day <= 7 or os.environ.get("ETF_MONTHLY") == "1":   # 每月第一份週報附上個月主動式 ETF 績效（月報）
        try:
            行們 += 主動ETF月報(迄)
        except Exception as e:
            print("主動式 ETF 月報失敗：", repr(e))

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
    摘要 = engine.大盤摘要(指標, engine.讀取加權指數(), 國際, 期貨, 設定)
    print(摘要)
    內容, 模型 = engine.AI大盤解讀(摘要, 模式, 設定)
    try:
        engine.AI用量紀錄(設定, "大盤解讀")
    except Exception as e:
        print("用量紀錄失敗：", repr(e))
    try:
        engine.儲存大盤解讀(設定, 模式, 內容, 模型)
    except Exception as e:
        print("存檔失敗：", repr(e))
    文字 = re.sub(r"^#+\s*", "▍", engine.拆解解讀條件(內容)[0], flags=re.M).replace("**", "")
    推播(f"🧠 {模式}大盤解讀（{dt.datetime.now(台北):%m/%d %H:%M}）\n\n{文字}")


def 個股查詢(問, 完整=True):
    """LINE 打字查詢：代號或名稱 → 股價、評分、基本面、籌碼、技術、支撐壓力、券商共識、董監轉讓、網紅點名；
    完整=True 再附 AI 分析、PDF 第 1 頁圖片與 PDF 下載連結（約多 1～2 分鐘，第二批訊息）。"""
    import engine
    問 = str(問 or "").strip()
    最新 = engine.讀取資料庫(最近天數=7)
    最新 = 最新[最新["date"] == 最新["date"].max()]
    列 = 最新[(最新["code"] == 問) | (最新["name"] == 問)]
    if not len(列):
        列 = 最新[最新["name"].astype(str).str.contains(問, regex=False)] if 問 else 列
    if not len(列):
        送出([{"type": "text", "text": f"🔍 找不到「{問}」，請輸入股票代號（例如 2330）或完整名稱。"}])
        return
    r = 列.iloc[0]
    代, 名 = str(r["code"]), str(r["name"])
    import line_report
    今, 個股史 = line_report.準備(代)
    即時 = None
    if 今 is not None:   # 盤中（或收盤後到晚上更新前）用證交所即時價，AI 報告與 PDF 也跟著用
        今, 即時 = engine.套用即時價(今, 代, r["date"])
    指標 = 個股史.tail(400) if 個股史 is not None else engine.計算指標(engine.讀取資料庫(最近天數=400, 代號=[代]))
    if 即時:
        行們 = [f"🔍 {代} {名}　{即時}", f"現價 {今['收盤']:,.2f}（{符號(今['漲跌'])}{abs(今['漲跌']):,.2f}，{今['漲跌幅']:+.2f}%）"
              + (f"，本益比 {今['本益比']:.1f}" if pd.notna(今.get("本益比")) and 今["本益比"] > 0 else "")
              + f"\n（籌碼、評分、技術是 {r['date']:%m/%d} 收盤資料）"]
    else:
        行們 = [f"🔍 {代} {名}　{r['date']:%m/%d}", f"收盤 {r['close']:,.2f}（{符號(r['change'])}{abs(r['change']):,.2f}）"
              + (f"，本益比 {r['pe']:.1f}" if pd.notna(r.get("pe")) and r["pe"] > 0 else "")]
    try:
        全 = engine.計算指標(engine.讀取資料庫(最近天數=40))
        分, _, _ = engine.今昨評分(全, engine.讀取基本面(), engine.讀取加權指數())
        if 代 in 分.index:
            行們.append(f"🧮 評分 {分.at[代, '總分']:.1f}　{分.at[代, '看法']}")
    except Exception as e:
        print("評分失敗：", repr(e))
    if 今 is not None:
        try:
            行們 += line_report.重點行們(代, 今, 個股史)
        except Exception as e:
            print("重點失敗：", repr(e))
    K = engine.還原K線(指標)
    if K is not None:
        sr = engine.支撐壓力(K, 量=指標.set_index("date")["成交值億"])
        位 = sr["價位"]
        壓 = 位[位["角色"] == "壓力"].sort_values("價位").head(2)
        撐 = 位[位["角色"] == "支撐"].sort_values("價位", ascending=False).head(2)
        if len(壓):
            行們.append("⬆️ 壓力 " + "、".join(f"{x['價位']:,.2f}（{x['名稱']}）" for _, x in 壓.iterrows()))
        if len(撐):
            行們.append("⬇️ 支撐 " + "、".join(f"{x['價位']:,.2f}（{x['名稱']}）" for _, x in 撐.iterrows()))
    try:
        報告們 = [x for x in (讀設定("broker_reports.json")[0] or {}).get("報告", []) if str(x.get("代號")) == 代]
        字 = engine.共識文字(engine.券商共識(報告們, float(今["收盤"] if 即時 else r["close"])))
        if 字:
            行們.append("🏦 " + 字)
    except Exception as e:
        print("券商共識失敗：", repr(e))
    try:
        行們 += line_report.公司新聞文字(line_report.公司資料(代), line_report.近期新聞(代, 名, 筆數=4))
    except Exception as e:
        print("公司介紹／新聞失敗：", repr(e))
    轉 = engine.讀取內部人轉讓()
    if 轉 is not None:
        近 = 轉[(轉["code"] == 代) & (轉["date"] >= 轉["date"].max() - pd.Timedelta(days=30))]
        if len(近):
            行們.append(f"🧾 近 30 天董監申報轉讓 {len(近)} 筆，共 {近['股數'].sum() / 1000:,.0f} 張")
    try:
        片 = (讀設定("influencer_notes.json")[0] or {}).get("影片", [])
        說 = [(v["頻道"], x["看法"]) for v in 片 for x in v.get("股票", []) if str(x.get("代號")) == 代
             and str(v.get("日期") or "") >= f"{dt.date.today() - dt.timedelta(days=30)}"]
        if 說:
            多 = sum(1 for _, k in 說 if k == "看多")
            行們.append(f"🎬 近 30 天 {len({c for c, _ in 說})} 個頻道提到（看多 {多}、看空 {sum(1 for _, k in 說 if k == '看空')}）")
    except Exception as e:
        print("網紅失敗：", repr(e))
    設定 = {k: os.environ.get(k, "") for k in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_SEARCH", "GITHUB_TOKEN")}
    設定 = {k: v for k, v in 設定.items() if v}
    設定["AI_REPO"] = 倉庫
    要完整 = 完整 and 今 is not None
    行們.append("（規則計分，僅供參考，非投資建議）"
              + ("\n⏳ AI 分析與 PDF 報告產生中，約 1～2 分鐘後送到。" if 要完整 else ""))
    送出([{"type": "text", "text": "\n".join(行們)[:4900]}])
    if not 要完整:
        return
    try:
        送出(line_report.完整報告(代, 今, 個股史, 設定))
    except Exception as e:
        print("完整報告失敗：", repr(e))
        送出([{"type": "text", "text": f"⚠️ {代} {名} 的 AI／PDF 報告產生失敗：{str(e)[:150]}\n可到網站個股頁查看：{line_report.網站}/?s={代}"}])


if __name__ == "__main__":
    模式 = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if 模式 == "check":
        設 = bool(os.environ.get("SITE_PASSWORD", "").strip())
        包, _ = 讀設定("journal.json")
        日 = 讀日記()
        if not 設:
            結果 = "❌ 還沒有設定 SITE_PASSWORD"
        elif 包 and 包.get("加密") and not 日:
            結果 = "⚠️ 有設定 SITE_PASSWORD，但解不開交易日記，密碼可能跟網站不一樣"
        else:
            庫 = 持股文字().strip().count("\n")
            結果 = f"✅ SITE_PASSWORD 設定正確，讀到網站庫存 {庫} 檔"
        print(結果)
        推播("🔧 設定檢查：" + 結果)
    elif 模式 == "test":
        推播("✅ 台股觀測實驗室：LINE 推播設定成功！之後每個交易日收盤後會傳摘要給你。")
    elif 模式 == "alert":
        盤中提醒()
    elif 模式 == "health":
        健康檢查()
    elif 模式 == "weekly":
        週報()
    elif 模式 == "query":
        問 = " ".join(sys.argv[2:]).strip()
        簡 = 問.endswith(("快", "簡")) and len(問) > 2   # 「2330快」只要文字摘要，不做 AI 與 PDF
        個股查詢(問[:-1].strip() if 簡 else 問, 完整=not 簡)
    elif 模式 == "brief":
        大盤解讀(sys.argv[2] if len(sys.argv) > 2 else "收盤")
    else:
        收盤摘要(強制=模式 == "daily-force")
