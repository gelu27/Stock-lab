# LINE 推播：每天收盤摘要、盤中到價提醒（由 GitHub Actions 執行）
#   python notify.py daily   收盤摘要（大盤、強弱族群、自選股、庫存損益、到價）
#   python notify.py alert   盤中檢查到價提醒（同一個提醒一天只通知一次）
#   python notify.py test    傳一則測試訊息
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


def 推播(文字):
    權杖 = os.environ.get("LINE_TOKEN", "").strip()
    if not 權杖:
        print("沒有設定 LINE_TOKEN，略過推播。內容如下：\n" + 文字)
        return
    對象 = os.environ.get("LINE_USER_ID", "").strip()
    網址 = "https://api.line.me/v2/bot/message/" + ("push" if 對象 else "broadcast")
    內容 = {"messages": [{"type": "text", "text": 文字[:4900]}]}
    if 對象:
        內容["to"] = 對象
    r = requests.post(網址, headers={"Authorization": f"Bearer {權杖}"}, json=內容, timeout=15)
    print("LINE 回應", r.status_code, r.text[:200])
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
    代號們 = list(dict.fromkeys(c for v in 自選.values() for c in v))
    if 代號們:
        行們 += ["", "⭐ 自選股"]
        for c in 代號們[:30]:
            列 = t[t["code"] == c]
            if len(列):
                r = 列.iloc[0]
                行們.append(f"{r['name']} {r['close']:,.2f} {r['幅度']:+.2f}%")

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


if __name__ == "__main__":
    模式 = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if 模式 == "test":
        推播("✅ 台股觀測實驗室：LINE 推播設定成功！之後每個交易日收盤後會傳摘要給你。")
    elif 模式 == "alert":
        盤中提醒()
    else:
        收盤摘要(強制=模式 == "daily-force")
