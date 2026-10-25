# LINE 推播：每天收盤摘要、盤中到價提醒（由 GitHub Actions 執行）
#   python notify.py daily   收盤摘要（大盤、強弱族群、自選股、庫存損益、到價）
#   python notify.py alert   盤中檢查到價提醒（同一個提醒一天只通知一次）
#   python notify.py test    傳一則測試訊息
#   python notify.py health  檢查各資料來源有沒有正常更新，有問題才通知（休市日不算問題）
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
        行們 += 評分摘要(持股)
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


def 評分摘要(持股):
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
    高 = 分[(分["5日均量"] >= 500) & ~分.index.str.startswith("00")].sort_values("總分", ascending=False).head(5)
    行們.append("🔝 高分股：" + "、".join(f"{r['名稱']} {r['總分']:.0f}" for _, r in 高.iterrows()))
    行們.append("（規則計分，僅供參考，非投資建議）")
    return 行們


def 盤中提醒():
    現在 = dt.datetime.now(台北)
    if 現在.weekday() >= 5 or not (dt.time(9, 0) <= 現在.time() <= dt.time(13, 35)):
        print("不在盤中時間，略過")
        return
    提醒, _ = 讀設定("alerts.json")
    if not 提醒:
        print("沒有設定到價提醒")
        return
    _, t = 最新行情()
    市場 = dict(zip(t["code"], t.get("market", pd.Series("上市", index=t.index))))
    頻道 = "|".join(f"{'otc' if 市場.get(c) == '上櫃' else 'tse'}_{c}.tw" for c in 提醒)
    r = requests.get("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?json=1&delay=0&ex_ch=" + 頻道,
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    今天 = 現在.strftime("%Y-%m-%d")
    狀態, sha = 讀設定("alert_state.json")
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

    if 問題:
        推播("⚠️ 台股觀測實驗室：資料來源異常\n" + "\n".join(f"・{x}" for x in 問題)
             + "\n\n網站其他功能照常，可以到 GitHub Actions 看「更新資料庫」的紀錄。")
    else:
        print("資料來源全部正常")


if __name__ == "__main__":
    模式 = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if 模式 == "test":
        推播("✅ 台股觀測實驗室：LINE 推播設定成功！之後每個交易日收盤後會傳摘要給你。")
    elif 模式 == "alert":
        盤中提醒()
    elif 模式 == "health":
        健康檢查()
    else:
        收盤摘要(強制=模式 == "daily-force")
