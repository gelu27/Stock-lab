# LINE 打字查詢的完整報告：不靠 Streamlit，在 GitHub Actions 裡組出跟網站個股頁一樣的數據、
# 請 Gemini 寫 AI 分析（存回網站的 AI 報告紀錄）、用 report.py 做 PDF、把第 1 頁轉成圖片，
# 上傳後回傳網址給 notify.py 傳到 LINE。
import base64
import datetime as dt
import io
import json
import os
import secrets

import numpy as np
import pandas as pd
import requests

import engine

倉庫 = os.environ.get("GITHUB_REPOSITORY") or "gelu27/Stock-lab"
網站 = "https://taisc-stock.streamlit.app"
預覽分支 = "ai-reports"
報告標籤 = "line-reports"   # PDF 放在這個 Release 的附件（刪了就真的不佔空間，不會讓 repo 越來越大）
保留天數 = 30


def 數(v, f="{:,.2f}", 尾=""):
    try:
        return "—" if v is None or pd.isna(v) else f.format(v) + 尾
    except (TypeError, ValueError):
        return "—"


# ---------- 資料 ----------
def 準備(代號):
    """這一檔完整 5 年指標＋最新一天（含基本面）。回傳 (r, 全史)，找不到回傳 (None, None)。"""
    原始 = engine.讀取資料庫(代號=代號)
    if 原始 is None or not len(原始):
        return None, None
    全 = engine.計算指標(原始)
    r = engine.加基本面(全.tail(1), engine.讀取基本面()).iloc[0]
    return r, 全


def ROE資料(代號, r, 全):
    四季, 季度, 去年四季 = engine.近四季EPS(代號)
    淨值比 = r.get("淨值比")
    現在 = 四季 / (r["收盤"] / 淨值比) * 100 if pd.notna(四季) and pd.notna(淨值比) and 淨值比 > 0 else np.nan
    舊 = 全[全["date"] <= 全["date"].max() - pd.Timedelta(days=365)].tail(1)
    以前 = np.nan
    if pd.notna(去年四季) and len(舊) and 舊["淨值比"].iloc[0] > 0:
        # 一年前的每股淨值是舊股數，期間有面額分割要換成現在的股數（EPS 已換過）
        以前 = 去年四季 / (舊["收盤"].iloc[0] / 舊["淨值比"].iloc[0] / engine.分割倍數(代號, 舊["date"].iloc[0])) * 100
    return 現在, 以前, 季度, 四季


def 變化資料(代號, r, 全, 天數=126):
    歷史 = 全.tail(天數)
    股數 = r.get("發行股數", np.nan)
    週轉 = (歷史["volume"] * engine.分割倍數序列(代號, 歷史["date"]) / 股數 * 100 if pd.notna(股數) and 股數
            else pd.Series(np.nan, index=歷史.index))  # 分割前的成交股數換成現在的股數基準
    表們 = []
    for 取 in (lambda: engine.讀取集保(代號), lambda: engine.集保歷史(代號, 26)):
        try:
            t = 取()
            if t is not None and len(t):
                表們.append(t)
        except Exception as e:
            print("集保失敗：", repr(e))
    大 = None
    if 表們:
        大 = pd.concat(表們).drop_duplicates("date", keep="last").sort_values("date", ignore_index=True)
        大 = 大[大["date"] >= 歷史["date"].iloc[0] - pd.Timedelta(days=7)]
    return 歷史, 週轉, 大


def 均線位置(r):
    """還原價對 5/20/60 日線：站上或跌破。"""
    字 = []
    for n in (5, 20, 60):
        m = r.get(f"MA{n}")
        if pd.notna(m) and m:
            字.append(f"{'站上' if r['還原價'] >= m else '跌破'} {n} 日線")
    return "、".join(字)


def 重點行們(代號, r, 全):
    """LINE 文字報告的基本面、籌碼、技術面、綜合判讀幾行。"""
    行們 = []
    比 = r["收盤"] / r["還原價"] if r.get("還原價") else 1
    營 = r.get("營收年增率")
    if pd.notna(營):
        行們.append(f"📈 營收 {r.get('營收月份') or ''} 年增 {營:+.1f}%、累計 {數(r.get('累計營收年增率'), '{:+.1f}', '%')}"
                  + ("（創新高）" if r.get("營收創新高") == True else ""))
    現, 以前, 季度, 四季 = ROE資料(代號, r, 全)
    基 = []
    if pd.notna(四季):
        基.append(f"近四季 EPS {四季:.2f}")
    if pd.notna(r.get("毛利率", np.nan)):
        基.append(f"毛利率 {r['毛利率']:.1f}%（較上季 {數(r.get('毛利率季增'), '{:+.1f}')} pt）")
    if pd.notna(現):
        基.append(f"ROE {現:.1f}%")
    if 基:
        行們.append("🏭 " + "、".join(基))
    if "法人5日買超" in r and pd.notna(r.get("法人5日買超")):
        連 = []
        if r.get("外資連買", 0) >= 2:
            連.append(f"外資連買 {int(r['外資連買'])} 天")
        elif r.get("外資連賣", 0) >= 2:
            連.append(f"外資連賣 {int(r['外資連賣'])} 天")
        if r.get("投信連買", 0) >= 2:
            連.append(f"投信連買 {int(r['投信連買'])} 天")
        行們.append(f"💰 法人今日 {數(r.get('法人買超'), '{:+,.0f}')} 張、5 日 {數(r['法人5日買超'], '{:+,.0f}')} 張"
                  + (f"（{'、'.join(連)}）" if 連 else "")
                  + (f"，融資 5 日 {數(r.get('融資5日增減'), '{:+.1f}', '%')}" if pd.notna(r.get("融資5日增減")) else ""))
    技 = [x for x in (均線位置(r), f"RSI {數(r.get('RSI'), '{:.0f}')}",
                     f"距 52 週高 {數(r.get('距52週高點'), '{:+.1f}', '%')}") if x]
    行們.append("📊 " + "、".join(技) + f"（20 日線 {數(r['MA20'] * 比)}）")
    try:
        判 = engine.規則判讀(r)
        行們.append(f"🧭 綜合判讀 {判['分數']:+.0f}　{判['看法']}")
    except Exception as e:
        print("規則判讀失敗：", repr(e))
    return 行們


def 數據摘要(代號, r, 全):
    """給 AI 的數據（跟網站個股頁的 AI 分析同一套內容，少了公司介紹與產業鏈）。"""
    股數 = r.get("發行股數", np.nan)
    比 = r["收盤"] / r["還原價"] if r.get("還原價") else 1
    現, 以前, 季度, 四季 = ROE資料(代號, r, 全)
    日 = 全["date"].max()
    行們 = [
        f"- 資料日期 {日:%Y-%m-%d}，收盤 {數(r['收盤'])}，漲跌 {r['漲跌幅']:+.2f}%，產業 {r.get('產業') or '—'}，"
        f"股本 {數(r.get('股本億'), '{:,.1f}', ' 億')}，市值 {數(股數 * r['收盤'] / 1e8 if pd.notna(股數) else np.nan, '{:,.0f}', ' 億')}",
        f"- 本益比 {數(r['本益比'])}，殖利率 {數(r['殖利率'], 尾='%')}，股價淨值比 {數(r['淨值比'])}，"
        f"今年累計 EPS {數(r.get('EPS'))}（{r.get('EPS季度') or ''}），近三季 EPS {數(r.get('近三季EPS'))}",
        f"- 月營收（{r.get('營收月份') or ''}）年增 {數(r.get('營收年增率'), 尾='%')}，月增 {數(r.get('營收月增率'), 尾='%')}，"
        f"累計年增 {數(r.get('累計營收年增率'), 尾='%')}" + ("，創歷史新高" if r.get("營收創新高") == True else ""),
        (f"- 單季毛利率（{r.get('毛利率季度')}）{數(r.get('毛利率'), 尾='%')}，較上季 {數(r.get('毛利率季增'), '{:+.1f}', ' 個百分點')}，"
         f"較去年同季 {數(r.get('毛利率年增'), '{:+.1f}', ' 個百分點')}，營益率 {數(r.get('營益率'), 尾='%')}"
         if pd.notna(r.get("毛利率", np.nan)) else "- 無毛利率資料"),
        (f"- ROE（近四季，至 {季度}）{現:.1f}%，去年同期 {數(以前, '{:.1f}', '%')}，近四季 EPS {四季:.2f}"
         if pd.notna(現) else "- 無 ROE 資料"),
        (f"- 外資 {數(r['外資買超'], '{:+,.0f}')} 張、投信 {數(r['投信買超'], '{:+,.0f}')} 張、"
         f"法人 10 日合計 {數(r['法人10日買超'], '{:+,.0f}')} 張，融資 5 日 {數(r['融資5日增減'], '{:+.1f}', '%')}"
         if "外資買超" in r else "- 無籌碼資料"),
        f"- 5/10/20/60 日線 {' / '.join(數(r[f'MA{n}'] * 比) for n in (5, 10, 20, 60))}，RSI {數(r['RSI'], '{:.1f}')}，"
        f"20 日漲幅 {數(r['20日漲幅'], '{:+.2f}', '%')}，距 52 週高點 {數(r['距52週高點'], '{:+.1f}', '%')}",
    ]
    摘要 = "\n".join(行們)
    try:
        摘要 += "\n\n近半年股價、週轉率、千張大戶、三大法人變化：\n" + engine.變化摘要(*變化資料(代號, r, 全))
    except Exception as e:
        print("變化摘要失敗：", repr(e))
    本益 = 全.loc[全["date"] >= 日 - pd.Timedelta(days=3 * 365), "本益比"]
    本益 = 本益[本益 > 0]
    if len(本益) > 60:
        摘要 += (f"\n- 近三年本益比區間：最低 {本益.min():.1f}、中位數 {本益.median():.1f}、最高 {本益.max():.1f}"
               f"（目前 {數(r['本益比'])}）")
    try:
        摘要 += f"\n- 建議評價方法：{engine.評價方法建議(r.get('產業'), r.get('近三季EPS'))}"
    except Exception:
        pass
    return 摘要


# ---------- AI ----------
def AI報告(代號, r, 全, 設定):
    """今天已有網站 AI 報告就沿用；沒有且有 GEMINI_API_KEY 就請 Gemini 寫一份並存回網站紀錄。
    回傳 (內文, 建議 dict, 時間, 是否新寫)；沒有金鑰也沒有舊報告回傳 (None, {}, None, False)。"""
    try:
        紀錄們 = engine.讀取AI紀錄(代號, 設定)
    except Exception as e:
        print("讀取 AI 紀錄失敗：", repr(e))
        紀錄們 = []
    今天 = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    資料日 = f"{全['date'].max():%Y-%m-%d}"
    上次 = 紀錄們[0] if 紀錄們 else None
    # 2026-11-01 第一版 LINE 查詢把全市場資料誤當成個股歷史，那幾份 AI 報告的數據不對，重寫並取代
    取代 = bool(上次) and 上次.get("引擎") == "Gemini（LINE 查詢）" and str(上次.get("時間", "")) < "2026-11-01 23:30"
    if 取代:
        上次 = 紀錄們[1] if len(紀錄們) > 1 else None
    if 上次 and not 取代 and (str(上次.get("時間", ""))[:10] == 今天 or 上次.get("資料日期") == 資料日):
        內文, 建議 = engine.拆解AI建議(上次["內容"])
        return 內文, 上次.get("建議") or 建議 or {}, 上次["時間"], False
    金鑰 = 設定.get("GEMINI_API_KEY")
    if not 金鑰:
        if 上次:
            內文, 建議 = engine.拆解AI建議(上次["內容"])
            return 內文, 上次.get("建議") or 建議 or {}, 上次["時間"], False
        return None, {}, None, False
    模型 = 設定.get("GEMINI_MODEL") or "gemini-flash-latest"
    摘要 = 數據摘要(代號, r, 全)
    if 上次:
        卡 = engine.拆解AI建議(上次.get("內容", ""))[1] or {}
        摘要 += (f"\n\n上次網站 AI 報告（{上次['時間'][:10]}，當時收盤 {上次.get('收盤')}）：看法 {卡.get('看法')}、"
               f"合理價 {卡.get('目標價合理')}、看錯條件 {卡.get('看錯條件')}")
    文字, 來源 = engine.AI分析Gemini(代號, r["名稱"], 摘要, 金鑰, 模型,
                                 搜尋=str(設定.get("GEMINI_SEARCH", "")).lower() == "true")
    時間 = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    新 = {"時間": 時間, "資料日期": 資料日, "收盤": float(r["收盤"]), "引擎": "Gemini（LINE 查詢）", "模型": 模型,
         "內容": 文字, "來源": 來源}
    try:
        engine.儲存AI紀錄(代號, 新, 設定, 取代=取代)
    except Exception as e:
        print("AI 報告存檔失敗：", repr(e))
    內文, 建議 = engine.拆解AI建議(文字)
    return 內文, 建議 or {}, 時間, True


def _價(v):
    """100 元以下留兩位小數（不然 16.76、16.95 都會變成 17）。"""
    return f"{v:,.2f}" if abs(v) < 100 else f"{v:,.0f}"


def 目標價提醒(建議, r, 全):
    """用現價、目前本益比、近三年最高收盤檢查 AI 目標價（engine.檢查AI目標價）。"""
    try:
        近 = 全[全["date"] >= 全["date"].max() - pd.Timedelta(days=3 * 365)]
        本益比 = float(r["本益比"]) if pd.notna(r.get("本益比")) and r["本益比"] > 0 else None
        return engine.檢查AI目標價(建議, float(r["收盤"]), 本益比, float(近["收盤"].max()))
    except Exception as e:
        print("目標價檢查失敗：", repr(e))
        return []


def AI結論(內文, 建議, 提醒=None):
    """LINE 上顯示的 AI 重點：看法、一句話、目標價、支撐壓力停損、看錯條件（完整內容看 PDF）。"""
    import re
    行們 = []
    if 建議.get("看法"):
        行們.append(f"🤖 看法：{建議['看法']}" + (f"（短線 {建議['短線']}、中期 {建議['中期']}）"
                                              if 建議.get("短線") and 建議.get("中期") else ""))
    if 建議.get("一句話"):
        行們.append(f"💬 {建議['一句話']}")
    價 = [f"{名} {_價(建議[k])}" for k, 名 in (("目標價保守", "保守"), ("目標價合理", "合理"), ("目標價樂觀", "樂觀"))
         if isinstance(建議.get(k), (int, float))]
    if 價:
        行們.append("🎯 目標價 " + "／".join(價))
    位 = [f"{k} {建議[k]:,.2f}" for k in ("壓力", "支撐", "停損") if isinstance(建議.get(k), (int, float))]
    if 位:
        行們.append("📐 " + "、".join(位))
    if 建議.get("看錯條件"):
        行們.append(f"⚠️ 看錯條件：{建議['看錯條件']}")
    if 提醒:
        行們.append("🔎 數字檢查：\n" + "\n".join("・" + 句 for 句 in 提醒))
    if len(行們) <= 1 and 內文:
        純 = re.sub(r"[#*>`|]", "", 內文)
        純 = re.sub(r"\n\s*\n", "\n", 純).strip()
        行們.append(純[:500] + ("…" if len(純) > 500 else ""))
    return "\n".join(行們)


# ---------- PDF ----------
def 產生PDF(代號, r, 全, 建議, 內文, 時間):
    """跟網站個股頁「產生 PDF 報告」同一個版型（少了公司介紹）。回傳 PDF bytes。"""
    import report
    g = lambda k: r.get(k, np.nan)
    股數 = g("發行股數")
    比 = r["收盤"] / r["還原價"] if r["還原價"] else 1
    現, 以前, 季度, 四季 = ROE資料(代號, r, 全)
    合理 = 建議.get("目標價合理")
    空間 = (合理 / r["收盤"] - 1) * 100 if isinstance(合理, (int, float)) else np.nan
    最新日 = 全["date"].max()
    有籌碼 = "外資買超" in r
    卡們 = [
        ("收盤 " + 最新日.strftime("%m/%d"), 數(r["收盤"]), f"{r['漲跌幅']:+.2f}%", r["漲跌"]),
        ("AI 合理目標價", _價(合理) if isinstance(合理, (int, float)) else "—",
         f"距現價 {空間:+.1f}%" if pd.notna(空間) else "", 空間),
        ("本益比", 數(r["本益比"], "{:.1f}"), f"預估 {數(建議.get('預估本益比'), '{:.1f}')} 倍"
         if isinstance(建議.get("預估本益比"), (int, float)) else "", None),
        ("ROE（近四季）", 數(現, "{:.1f}", "%"), f"去年 {數(以前, '{:.1f}', '%')}", 現 - 以前 if pd.notna(以前) else None),
        ("單季毛利率", 數(g("毛利率"), "{:.1f}", "%"), f"較上季 {數(g('毛利率季增'), '{:+.1f}')} 個百分點", g("毛利率季增")),
        ("營業利益率", 數(g("營益率"), "{:.1f}", "%"), f"較上季 {數(g('營益率季增'), '{:+.1f}')} 個百分點", g("營益率季增")),
        ("月營收年增", 數(g("營收年增率"), "{:+.1f}", "%"), str(g("營收月份") or ""), g("營收年增率")),
        ("近四季 EPS", 數(四季), f"至 {季度 or '—'}", None),
        ("法人 10 日", 數(g("法人10日買超"), "{:+,.0f}"), "張", g("法人10日買超")),
        ("外資連買", 數(g("外資連買"), "{:.0f}", " 天"), f"投信連買 {數(g('投信連買'), '{:.0f}')} 天", None),
        ("殖利率", 數(r["殖利率"], "{:.2f}", "%"), f"淨值比 {數(r['淨值比'])}", None),
        ("市值", 數(股數 * r["收盤"] / 1e8 if pd.notna(股數) else np.nan, "{:,.0f}", " 億"), f"股本 {數(g('股本億'), '{:,.1f}')} 億", None),
    ]
    基本 = [
        ("基本資料", [("產業", str(g("產業") or "—")), ("市場", r["市場"]), ("股本", 數(g("股本億"), "{:,.1f}", " 億")),
                    ("市值", 數(股數 * r["收盤"] / 1e8 if pd.notna(股數) else np.nan, "{:,.0f}", " 億")),
                    ("成交量", 數(r["成交張數"], "{:,.0f}", " 張")),
                    ("週轉率", 數(r["volume"] / 股數 * 100 if pd.notna(股數) else np.nan, "{:.2f}", "%")),
                    ("本益比", 數(r["本益比"])), ("殖利率", 數(r["殖利率"], 尾="%")), ("股價淨值比", 數(r["淨值比"]))]),
        ("基本面", [("ROE（近四季）", 數(現, "{:.1f}", "%")), ("今年累計 EPS", 數(g("EPS"))), ("近四季 EPS", 數(四季)),
                  ("月營收年增", 數(g("營收年增率"), 尾="%")), ("累計營收年增", 數(g("累計營收年增率"), 尾="%")),
                  ("單季毛利率", 數(g("毛利率"), 尾="%")), ("毛利率較上季", 數(g("毛利率季增"), "{:+.1f}", " pt")),
                  ("營業利益率", 數(g("營益率"), 尾="%")), ("營益率較上季", 數(g("營益率季增"), "{:+.1f}", " pt")),
                  ("營益率較去年", 數(g("營益率年增"), "{:+.1f}", " pt"))]),
    ]
    if 有籌碼:
        基本.append(("籌碼面", [("外資", 數(r["外資買超"], "{:+,.0f}", " 張")), ("投信", 數(r["投信買超"], "{:+,.0f}", " 張")),
                             ("自營商", 數(r["自營買超"], "{:+,.0f}", " 張")), ("法人 5 日", 數(r["法人5日買超"], "{:+,.0f}", " 張")),
                             ("法人 10 日", 數(r["法人10日買超"], "{:+,.0f}", " 張")), ("外資連買", 數(r["外資連買"], "{:.0f}", " 天")),
                             ("投信連買", 數(r["投信連買"], "{:.0f}", " 天")), ("融資餘額", 數(r["融資餘額"], "{:,.0f}", " 張")),
                             ("融資 5 日", 數(r["融資5日增減"], "{:+.1f}", "%"))]))
    基本.append(("技術面", [(f"{n} 日線", 數(r[f"MA{n}"] * 比)) for n in (5, 10, 20, 60)] + [
        ("RSI(14)", 數(r["RSI"], "{:.1f}")), ("20 日漲幅", 數(r["20日漲幅"], "{:+.2f}", "%")),
        ("距 52 週高點", 數(r["距52週高點"], "{:+.1f}", "%")), ("箱頂", 數(r["箱頂"])), ("箱底", 數(r["箱底"]))]))
    資料 = {"收盤": float(r["收盤"]), "漲跌": float(r["漲跌"]), "漲跌幅": float(r["漲跌幅"]), "日期": 最新日.strftime("%Y-%m-%d"),
            "產業": g("產業"), "市場": r["市場"], "卡片": 卡們, "基本資料": 基本, "判讀": engine.規則判讀(r),
            "歷史": 全, "營收": engine.讀取營收歷史(代號), "損益": engine.單季損益(代號),
            "建議": 建議, "報告": 內文 or "", "報告時間": 時間 or ""}
    try:
        h, 週轉, 大 = 變化資料(代號, r, 全)
        資料["變化"] = {"歷史": h, "週轉": 週轉, "大戶": 大, "解讀": engine.變化解讀(h, 週轉, 大)}
    except Exception as e:
        print("變化圖失敗：", repr(e))
    return bytes(report.產生PDF(代號, r["名稱"], 資料))


def 第一頁圖片(pdf, 寬=1600):
    """PDF 第 1 頁轉成 JPEG（LINE 預覽圖上限 1MB，所以壓到 1MB 以內）。"""
    import pymupdf
    文件 = pymupdf.open(stream=pdf, filetype="pdf")
    頁 = 文件[0]
    圖 = 頁.get_pixmap(matrix=pymupdf.Matrix(寬 / 頁.rect.width, 寬 / 頁.rect.width))
    for 品質 in (85, 70, 55):
        資料 = 圖.tobytes("jpeg", jpg_quality=品質)
        if len(資料) < 1_000_000:
            return 資料
    return 資料


# ---------- 上傳 ----------
def _標頭(權杖):
    return {"Authorization": f"Bearer {權杖}", "Accept": "application/vnd.github+json"}


def _取得Release(權杖):
    h = _標頭(權杖)
    r = requests.get(f"https://api.github.com/repos/{倉庫}/releases/tags/{報告標籤}", headers=h, timeout=15)
    if r.status_code == 200:
        return r.json()
    r = requests.post(f"https://api.github.com/repos/{倉庫}/releases", headers=h, timeout=15, json={
        "tag_name": 報告標籤, "target_commitish": 預覽分支, "name": "LINE 查詢 PDF 報告",
        "body": f"LINE 打字查詢自動產生的個股 PDF，保留 {保留天數} 天後自動刪除。僅供個人研究，不構成投資建議。",
        "prerelease": True, "make_latest": "false"})
    r.raise_for_status()
    return r.json()


def 上傳PDF(檔名, pdf, 權杖):
    """傳到 Release 附件，回傳下載網址；順便刪掉超過保留天數的舊檔。"""
    rel = _取得Release(權杖)
    h = _標頭(權杖)
    期限 = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=保留天數)
    for a in rel.get("assets", []):
        try:
            if dt.datetime.fromisoformat(a["created_at"].replace("Z", "+00:00")) < 期限:
                requests.delete(a["url"], headers=h, timeout=15)
        except Exception as e:
            print("刪舊 PDF 失敗：", repr(e))
    r = requests.post(f"https://uploads.github.com/repos/{倉庫}/releases/{rel['id']}/assets",
                      params={"name": 檔名}, data=pdf, timeout=60,
                      headers={**h, "Content-Type": "application/pdf"})
    r.raise_for_status()
    return r.json()["browser_download_url"]


def 上傳預覽圖(檔名, 圖, 權杖):
    """預覽圖放 ai-reports 分支的 line/ 資料夾（LINE 要能直接讀到圖片的網址），刪掉超過保留天數的舊圖。"""
    h = _標頭(權杖)
    基 = f"https://api.github.com/repos/{倉庫}/contents/line"
    try:
        清單 = requests.get(基, params={"ref": 預覽分支}, headers=h, timeout=15)
        if 清單.status_code == 200:
            期限 = (dt.date.today() - dt.timedelta(days=保留天數)).strftime("%Y%m%d")
            for f in 清單.json():
                日 = f["name"].split("_")[1] if f["name"].count("_") >= 2 else ""
                if 日.isdigit() and 日 < 期限:
                    requests.delete(f["url"], headers=h, timeout=15, json={
                        "message": f"刪除舊預覽圖 {f['name']}", "sha": f["sha"], "branch": 預覽分支})
    except Exception as e:
        print("清舊預覽圖失敗：", repr(e))
    r = requests.put(f"{基}/{檔名}", headers=h, timeout=30, json={
        "message": f"LINE 查詢預覽圖 {檔名}", "branch": 預覽分支, "content": base64.b64encode(圖).decode()})
    r.raise_for_status()
    return f"https://raw.githubusercontent.com/{倉庫}/{預覽分支}/line/{檔名}"


def 完整報告(代號, r, 全, 設定):
    """AI＋PDF＋預覽圖。回傳要傳到 LINE 的訊息清單（每一則是 LINE message object）。"""
    內文, 建議, 時間, 新寫 = AI報告(代號, r, 全, 設定)
    訊息 = []
    if 內文 or 建議:
        訊息.append({"type": "text", "text": (f"🧠 {代號} {r['名稱']} AI 分析（{時間}{'，新產生' if 新寫 else '，沿用今天的報告'}）\n"
                                             + AI結論(內文, 建議, 目標價提醒(建議, r, 全)))[:4900]})
    pdf = 產生PDF(代號, r, 全, 建議, 內文, 時間)
    權杖 = engine.清理金鑰(設定.get("GITHUB_TOKEN"))
    if not 權杖:
        print(f"沒有 GITHUB_TOKEN，PDF 不上傳（{len(pdf):,} bytes）")
        return 訊息
    名 = f"{代號}_{dt.date.today():%Y%m%d}_{secrets.token_hex(4)}"
    try:
        圖 = 第一頁圖片(pdf)
        圖址 = 上傳預覽圖(名 + ".jpg", 圖, 權杖)
        訊息.append({"type": "image", "originalContentUrl": 圖址, "previewImageUrl": 圖址})
    except Exception as e:
        print("預覽圖失敗：", repr(e))
    try:
        網址 = 上傳PDF(名 + ".pdf", pdf, 權杖)
        訊息.append({"type": "text", "text": f"📄 完整 PDF 報告（{保留天數} 天內有效）：\n{網址}\n\n🌐 網站個股頁：{網站}/?s={代號}"})
    except Exception as e:
        print("PDF 上傳失敗：", repr(e))
        訊息.append({"type": "text", "text": f"PDF 上傳失敗，請到網站個股頁下載：{網站}/?s={代號}"})
    return 訊息
