# 自動收件：不用再把 Gemini 的整理結果複製貼上，也不用每晚開 Claude 分案讀檔。
#   python auto_intake.py videos    讀 ai-reports 的 video_sources.json（頻道 RSS＋手動網址），請 Gemini 直接看 YouTube 影片，
#                                   照網站的整理指令寫成重點，解析後存進 influencer_notes.json
#   python auto_intake.py brokers   讀 Google 雲端資料夾（分享給「知道連結的人」）裡的新 PDF／截圖，
#                                   請 Gemini 抽成 JSON 存進 broker_reports.json
#   python auto_intake.py all       兩個都跑（排程用）
#   python auto_intake.py usage     傳 LINE：近 7 天 Gemini 呼叫次數
# 需要的 Secrets：GEMINI_API_KEY、GITHUB_TOKEN；券商報告另需 GOOGLE_API_KEY、DRIVE_FOLDER_ID。
# 失敗會傳 LINE 通知；每日呼叫上限 AI_DAILY_CAP（預設 80 次）。
import datetime as dt
import os
import re
import sys
import time
import traceback
import urllib.parse

import requests

import engine

台北 = dt.timezone(dt.timedelta(hours=8))
倉庫 = os.environ.get("GITHUB_REPOSITORY", "gelu27/Stock-lab")
影片時限秒 = 18 * 60   # 超過這個時間就不再開始新的影片，剩下的下次再做（workflow 上限 30 分鐘）
sys.stdout.reconfigure(line_buffering=True)   # Actions 上才看得到即時進度

# 與 views/p04_screener.py 的「網紅指令」相同（網站解析器 engine.解析影片整理 吃這個格式）
網紅指令 = ("請用繁體中文完整整理這支影片，不要只寫摘要，也不要加入你自己的看法。\n"
          "格式：一、基本資料，頻道、日期（YYYY-MM-DD）、長度各占一行，例如「頻道：xxx」「日期：2026-11-07」。二、逐段內容（時間點、講什麼、理由），保留所有數字。"
          "三、提到的股票（每檔一行：代號 名稱：看多或看空。理由：…，有價位要寫）。四、所有「如果…就…」的判斷條件（有提到股票名稱、均線天數或價位的要原樣寫出來，例如「台積電站回 20 週均線就買回」）。"
          "五、引用的資料來源。六、畫面上的圖表與字卡。七、影片本身前後矛盾或沒說清楚的地方"
          "（不要用你自己的知識判斷股價、EPS 等數字對不對，你的資料可能不是最新的）。")


def _設定():
    設 = {k: os.environ.get(k, "") for k in ("GEMINI_API_KEY", "GEMINI_MODEL", "GITHUB_TOKEN")}
    設 = {k: v for k, v in 設.items() if v}
    設["AI_REPO"] = 倉庫
    return 設


def _通知(文字):
    try:
        import notify
        notify.推播(文字)
    except Exception as e:
        print("LINE 通知失敗：", repr(e))


def _額度夠(設, 流程):
    上限 = int(os.environ.get("AI_DAILY_CAP") or 80)
    用了 = engine.AI今日呼叫數(設)
    if 用了 >= 上限:
        print(f"今天 Gemini 已呼叫 {用了} 次，達上限 {上限}，{流程}略過")
        _通知(f"⚠️ 自動收件（{流程}）略過：今天 Gemini 呼叫已達上限 {上限} 次。")
        return False
    return True


def _已看(設):
    表 = engine.讀取設定檔(設, "intake_seen.json") or {}
    return 表, set(表.get("影片", [])), set(表.get("檔案", []))


# ---------- 影片 ----------
def 影片清單(設, 已看影片, 天數=3):
    """回傳 [(影片id, 網址, 標題, 日期)]：頻道 RSS 近 天數 天的新片＋手動網址。"""
    來源 = engine.讀取設定檔(設, "video_sources.json") or {}
    結果 = {}
    下限 = dt.datetime.now(台北) - dt.timedelta(days=天數)
    for 頻 in 來源.get("頻道", []):
        try:
            r = requests.get("https://www.youtube.com/feeds/videos.xml", params={"channel_id": 頻["channel_id"]}, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print(f"RSS 失敗 {頻.get('名稱')}：{e!r}")
            continue
        for 項 in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
            vid = re.search(r"<yt:videoId>([^<]+)", 項)
            發 = re.search(r"<published>([^<]+)", 項)
            標 = re.search(r"<title>([^<]*)", 項)
            if not (vid and 發):
                continue
            時 = dt.datetime.fromisoformat(發.group(1)).astimezone(台北)
            if 時 >= 下限:
                結果[vid.group(1)] = (vid.group(1), f"https://www.youtube.com/watch?v={vid.group(1)}",
                                    (標.group(1) if 標 else ""), f"{時:%Y-%m-%d}")
    網址們 = list(來源.get("網址", [])) + [u for u in os.environ.get("VIDEO_URLS", "").split() if u]
    for u in 網址們:
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", u)
        if m:
            結果.setdefault(m.group(1), (m.group(1), f"https://www.youtube.com/watch?v={m.group(1)}", "", ""))
    略過 = [k for k in (來源.get("略過關鍵字") or ["直播"]) if k]   # 直播常常好幾個小時，額度吃不消
    def 要處理(v):
        return v[0] not in 已看影片 and not any(k in v[2] for k in 略過)
    return [v for v in 結果.values() if 要處理(v)]


def 取字幕(vid):
    """用 youtube-transcript-api 抓字幕（文字比影片便宜很多）。抓不到（被 YouTube 擋、沒字幕）回傳 None。"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        段 = YouTubeTranscriptApi().fetch(vid, languages=["zh-TW", "zh-Hant", "zh", "zh-Hans", "en"])
        文 = " ".join(x.text for x in 段).strip()
        return 文 if len(文) > 200 else None
    except Exception as e:
        print(f"  字幕抓不到（{type(e).__name__}），改請 Gemini 直接看影片", flush=True)
        return None


def 收影片(設):
    金鑰 = engine.清理金鑰(設.get("GEMINI_API_KEY"))
    if not 金鑰:
        print("沒有 GEMINI_API_KEY，略過影片")
        return 0, 0
    表, 已看影片, 已看檔 = _已看(設)
    待 = 影片清單(設, 已看影片)[: int(os.environ.get("INTAKE_MAX") or 4)]
    print(f"待處理影片 {len(待)} 支")
    if not 待:
        return 0, 0
    今 = engine.讀取資料庫(最近天數=7)
    今 = 今[今["date"] == 今["date"].max()]
    名稱表 = dict(zip(今["name"], 今["code"]))
    名表 = dict(zip(今["code"], 今["name"]))
    模型 = 設.get("GEMINI_MODEL") or "gemini-flash-latest"
    新, 失敗, 開始, 待人工 = [], 0, time.time(), []
    for vid, 網址, 標題, 日期 in 待:
        if time.time() - 開始 > 影片時限秒:
            print("已超過時間上限，剩下的影片下次再處理")
            break
        if not _額度夠(設, "影片"):
            break
        t0 = time.time()
        print(f"處理 {網址} {標題}", flush=True)
        try:
            字幕 = 取字幕(vid)
            if 字幕:
                print(f"  用字幕（{len(字幕)} 字）", flush=True)
                素材 = {"text": "以下是這支影片的逐字稿（YouTube 自動字幕，可能有同音錯字，請依上下文修正股票與公司名稱；沒有畫面資訊，第六點請寫「無」）：\n"
                               + 字幕[:200000] + f"\n\n影片標題：{標題}\n影片網址：{網址}"}
            else:
                素材 = {"file_data": {"file_uri": 網址}}
            內容 = {"contents": [{"role": "user", "parts": [素材, {"text": 網紅指令}]}],
                  "generationConfig": {"temperature": 0.2, "maxOutputTokens": 12000,
                                     "mediaResolution": "MEDIA_RESOLUTION_LOW"}}   # 低解析度：影片用的字數約少 2/3，省額度
            # 影片很長：不換模型；遇到 429（每分鐘上限）等 65 秒再試一次
            回應, _ = engine.Gemini呼叫(內容, 金鑰, 模型, 每個試幾次=2, 逾時=240, 換模型=False, 等429秒=65)
            候選 = (回應.json().get("candidates") or [{}])[0]
            文字 = "".join(p.get("text", "") for p in (候選.get("content") or {}).get("parts", [])).strip()
            v = engine.解析影片整理(文字, 名稱表)
            if not v:
                raise RuntimeError("解析不出「三、提到的股票」")
            v["標題"] = v.get("標題") or 標題
            v["日期"] = v.get("日期") or 日期
            v["影片"] = 網址
            v["查核"] = engine.初步查核網紅(v, 名表)
            新.append(v)
            已看影片.add(vid)
            # 每支做完就存檔：中途被截斷也不會白做
            engine.儲存網紅說法(設, engine.合併網紅說法(engine.讀取網紅說法(設), [v]))
            表["影片"] = sorted(已看影片)[-500:]
            engine.儲存設定檔(設, "intake_seen.json", 表, f"自動收件：影片 {vid}")
            print(f"  完成（{time.time() - t0:.0f} 秒，{len(v['股票'])} 檔股票）", flush=True)
        except Exception as e:
            失敗 += 1
            print(f"  失敗（{time.time() - t0:.0f} 秒）：{e!r}", flush=True)
            待人工.append(f"{標題[:30]} {網址}")
    if 新 or 失敗:
        旗 = [f"{v['頻道']} {v['日期']}：" + "；".join(v["查核"]) for v in 新 if v["查核"]]
        _通知(f"🎬 自動收到 {len(新)} 支網紅影片摘要" + (f"（{失敗} 支失敗）" if 失敗 else "")
            + ("\n🚩 初步查核：\n" + "\n".join(旗) if 旗 else "")
            + ("\n\n✋ 這些沒整理成功，可貼連結到 Gemini 手動整理（指令在網站 04 選股 → 網紅收件匣）：\n" + "\n".join(待人工[:8]) if 待人工 else ""))
    return len(新), 失敗


# ---------- 券商報告 ----------
def 雲端檔案(資料夾, 金鑰):
    r = requests.get("https://www.googleapis.com/drive/v3/files", timeout=30, params={
        "q": f"'{資料夾}' in parents and trashed=false", "key": 金鑰, "pageSize": 200, "orderBy": "createdTime desc",
        "fields": "files(id,name,mimeType,createdTime)"})
    r.raise_for_status()
    return [f for f in r.json().get("files", []) if f["mimeType"] in ("application/pdf", "image/jpeg", "image/png")]


def 收券商(設):
    金鑰 = engine.清理金鑰(設.get("GEMINI_API_KEY"))
    谷歌, 資料夾 = os.environ.get("GOOGLE_API_KEY", "").strip(), os.environ.get("DRIVE_FOLDER_ID", "").strip()
    if not (金鑰 and 谷歌 and 資料夾):
        print("沒有設定 GEMINI_API_KEY／GOOGLE_API_KEY／DRIVE_FOLDER_ID，略過券商報告")
        return 0, 0
    表, _, 已看檔 = _已看(設)
    待 = [f for f in 雲端檔案(資料夾, 谷歌) if f["id"] not in 已看檔][: int(os.environ.get("INTAKE_MAX") or 15)]
    print(f"待處理檔案 {len(待)} 個")
    if not 待:
        return 0, 0
    模型 = 設.get("GEMINI_MODEL") or "gemini-flash-latest"
    筆數, 失敗, 全 = 0, 0, engine.讀取券商報告(設)
    for f in 待:
        if not _額度夠(設, "券商報告"):
            break
        try:
            檔 = requests.get(f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(f['id'])}",
                            params={"alt": "media", "key": 谷歌}, timeout=120)
            檔.raise_for_status()
            列 = engine.AI讀券商報告(檔.content, f["name"], "Gemini", 金鑰, 模型)
            全 = engine.合併券商報告(全, 列)
            筆數 += len(列)
            已看檔.add(f["id"])   # 讀成功（就算 0 筆，例如不是報告）才登記，失敗的下次再試
        except Exception as e:
            失敗 += 1
            print(f"檔案 {f['name']} 失敗：{e!r}")
    if 已看檔 - set(表.get("檔案", [])):
        if 筆數:
            engine.儲存券商報告(設, 全)
        表["檔案"] = sorted(已看檔)[-2000:]
        engine.儲存設定檔(設, "intake_seen.json", 表, f"自動收件：券商報告 {筆數} 筆")
        _通知(f"📑 自動收到券商報告 {筆數} 筆" + (f"（{失敗} 個檔案失敗，下次重試）" if 失敗 else ""))
    return 筆數, 失敗


if __name__ == "__main__":
    模式 = sys.argv[1] if len(sys.argv) > 1 else "all"
    設 = _設定()
    if 模式 == "usage":
        _通知(engine.AI用量小卡(設))
        sys.exit(0)
    出錯 = []
    for 名, 函 in (("videos", 收影片), ("brokers", 收券商)):
        if 模式 in ("all", 名):
            try:
                _, 敗 = 函(設)
                if 敗:
                    出錯.append(f"{名}：{敗} 筆失敗")
            except Exception as e:
                traceback.print_exc()
                出錯.append(f"{名}：{e!r}"[:200])
            finally:
                try:
                    engine.AI用量紀錄(設, "自動收件-" + 名)
                except Exception as e:
                    print("用量紀錄失敗：", repr(e))
    if 出錯:
        _通知("❌ 自動收件有問題\n" + "\n".join(出錯) + "\n（可到 GitHub Actions 看詳細紀錄）")
        sys.exit(1)
