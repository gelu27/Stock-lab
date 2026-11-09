# AI 多空辯論庭與防幻覺：把網站數據打包成 JSON 餵給 AI，輸出強制 JSON，產出後逐一核對數字
import json
import re

import numpy as np
import pandas as pd


def _數(v, 位=2):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(v) else round(v, 位)


def 數據包(代號, 名稱, r, 動能列=None, 計畫=None, 估值百分位=None, 支撐=None, 壓力=None, 回測=None, 全市場=None):
    """AI 只能用這包數字。r＝今日資料一列；動能列＝動能資料的一列；回測＝個股動能回測表；全市場＝momentum_backtest.json。"""
    包 = {
        "股票": f"{代號} {名稱}",
        "價格": {"收盤": _數(r.get("收盤")), "漲跌幅%": _數(r.get("漲跌幅")), "20日漲幅%": _數(r.get("20日漲幅")),
               "距52週高點%": _數(r.get("距52週高點"), 1)},
        "技術": {"RSI": _數(r.get("RSI"), 1), "量比": _數(r.get("量比")),
               "20日線": _數(動能列.get("MA20")) if 動能列 is not None else None,
               "50日線": _數(動能列.get("MA50")) if 動能列 is not None else None,
               "200日線": _數(動能列.get("MA200")) if 動能列 is not None else None,
               "RS等級": _數(動能列.get("RS"), 0) if 動能列 is not None else None,
               "支撐": _數(支撐), "壓力": _數(壓力)},
        "籌碼": {"外資買超張": _數(r.get("外資買超"), 0), "投信買超張": _數(r.get("投信買超"), 0),
               "法人5日買超張": _數(r.get("法人5日買超"), 0), "外資連買天數": _數(r.get("外資連買"), 0),
               "融資5日增減%": _數(r.get("融資5日增減"), 1)},
        "基本面": {"本益比": _數(r.get("本益比"), 1), "本益比歷史百分位": _數(估值百分位, 0), "殖利率%": _數(r.get("殖利率")),
                "股價淨值比": _數(r.get("淨值比")), "月營收年增%": _數(r.get("營收年增率"), 1),
                "累計營收年增%": _數(r.get("累計營收年增率"), 1), "毛利率%": _數(r.get("毛利率"), 1),
                "毛利率較去年同季": _數(r.get("毛利率年增"), 1), "今年累計EPS": _數(r.get("EPS"))},
    }
    if 動能列 is not None:
        包["今日做多訊號"] = [k for k in ("強勢突破", "VCP突破", "領頭羊", "RS強勢", "多頭排列", "法人連買") if bool(動能列.get(k))]
    if 計畫 and 計畫.get("買點"):
        包["交易計畫"] = {k: 計畫.get(k) for k in ("買點", "停損", "目標1", "目標2", "停損%")}
    if 回測 is not None and len(回測):
        包["這檔2年訊號回測"] = 回測.replace({np.nan: None}).to_dict("records")
    if 全市場:
        包["全市場5年訊號回測"] = [{k: x.get(k) for k in ("訊號", "次數", "20日勝率%", "20日平均%", "20日超額%", "20日內平均最大回撤%")}
                           for x in [全市場.get("基準", {})] + 全市場.get("訊號", [])]
    return 包


def _攤平(包, 前綴=""):
    """{'價格': {'收盤': 100}} → [('收盤', 100.0), …]，只留數字。"""
    出 = []
    for k, v in 包.items():
        if isinstance(v, dict):
            出 += _攤平(v, k)
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and v is not None:
            出.append((k, float(v)))
    return 出


_別稱 = {"收盤": ["收盤", "股價", "收在"], "本益比": ["本益比", "PE"], "RSI": ["RSI"], "月營收年增%": ["營收年增", "月營收年增"],
       "毛利率%": ["毛利率"], "殖利率%": ["殖利率"], "股價淨值比": ["淨值比"], "今年累計EPS": ["EPS"],
       "20日線": ["20 日線", "20日線", "月線"], "RS等級": ["RS"], "支撐": ["支撐"], "壓力": ["壓力"]}


def 數字查核(文字, 包, 容許=0.03):
    """在 AI 文字裡找「關鍵字＋數字」，跟數據包比對；差超過 容許（3%）就列出來。回傳 (核對過幾個, 對不上的清單)。"""
    值們 = dict(_攤平(包))
    核, 錯 = 0, []
    for 欄, 稱們 in _別稱.items():
        真 = 值們.get(欄)
        if 真 is None:
            continue
        看過 = set()  # 「股價收在 1200」同一個數字被「股價」「收在」各抓一次，只算一次
        for 稱 in 稱們:
            for m in re.finditer(rf"{re.escape(稱)}[^0-9\-+\n]{{0,8}}([-+]?\d[\d,]*\.?\d*)", str(文字)):
                try:
                    說 = float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
                if m.start(1) in 看過:
                    continue
                看過.add(m.start(1))
                核 += 1
                基 = max(abs(真), 1e-9)
                if abs(說 - 真) / 基 > 容許 and abs(說 - 真) > 0.05:
                    錯.append(f"「{m.group(0)[:20]}」：AI 寫 {說:g}，網站資料是 {真:g}")
    return 核, 錯


角色 = {
    "多方": "你是激進的順勢做多操盤手。只找支持買進的理由，但每個理由都必須引用數據包裡的一個數字。",
    "空方": "你是嚴格的風險控管空頭分析師。專門找下跌風險、估值過高、籌碼鬆動、訊號失敗率，並逐點反駁多方。每點引用數據包裡的一個數字。",
}


def AI多空辯論(包, 呼叫, api_key, 模型="gemini-flash-latest"):
    """三位 AI：多方立論 → 空方反駁 → 首席投資長（只能用回測數字講勝率）給 JSON 結論。
    呼叫＝engine.Gemini呼叫。回傳 {"多方": 文字, "空方": 文字, "投資長": dict}。"""
    資料 = json.dumps(包, ensure_ascii=False)
    規則 = "規則：只能使用下面 JSON 裡的數字，不可以自己編股價、財務數字或勝率；數據包沒有的就說「資料沒有」。用繁體中文。"

    def 問(系統, 內文, json輸出=False, 字數=1200):
        設定 = {"temperature": 0.4, "maxOutputTokens": 字數 * 2}
        if json輸出:
            設定["responseMimeType"] = "application/json"
        回應, _ = 呼叫({"systemInstruction": {"parts": [{"text": 系統 + "\n" + 規則}]},
                       "contents": [{"role": "user", "parts": [{"text": 內文}]}], "generationConfig": 設定}, api_key, 模型)
        j = 回應.json()
        return "".join(p.get("text", "") for p in (j.get("candidates") or [{}])[0].get("content", {}).get("parts", [])).strip()

    多 = 問(角色["多方"], f"數據包：{資料}\n\n請列出最多 5 點做多理由（每點一行，以「- 」開頭，每點帶一個數字）。")
    空 = 問(角色["空方"], f"數據包：{資料}\n\n多方的論點：\n{多}\n\n請逐點反駁，再補充最多 3 點多方沒提到的風險（每點一行，以「- 」開頭）。")
    長 = 問("你是首席投資長，負責裁決多空辯論。勝率只能引用數據包裡「這檔2年訊號回測」或「全市場5年訊號回測」的數字，"
           "不可自己估算；今天沒有做多訊號就說明沒有可引用的勝率。",
           f"數據包：{資料}\n\n多方：\n{多}\n\n空方：\n{空}\n\n"
           "請只輸出 JSON，欄位：{\"結論\": \"偏多|中性|偏空\", \"信心\": \"低|中|高\", \"一句話\": \"給新手的一句話\", "
           "\"引用回測\": \"引用的回測數字與出處（例如：全市場5年 強勢突破 20日勝率 43.4%）\", \"多方最強論點\": \"\", "
           "\"空方最強論點\": \"\", \"觀察指標\": [\"要追蹤的數字1\", \"數字2\"], \"論點失效條件\": \"\"}",
           json輸出=True, 字數=800)
    try:
        長 = json.loads(re.sub(r"^```(?:json)?|```$", "", 長.strip(), flags=re.M))
    except Exception:
        長 = {"結論": "無法解析", "一句話": 長[:300]}
    return {"多方": 多, "空方": 空, "投資長": 長}
