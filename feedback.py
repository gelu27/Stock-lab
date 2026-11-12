"""回饋循環（2026-11-12，F1～F8）：把「過去說對說錯」整理給 AI 和網站。

語言模型不會自己學習；網站變準靠的是：累積資料 → 對答案 → 把結果寫回提示與規則。這個檔案負責中間那一段：
- F1 AI 錯誤本：大盤解讀與個股 AI 報告過去說錯的事，整理成文字放進下一次的提示。
- F2 券商過去紀錄：每家券商報告後 20／60 日的超額報酬與 6 個月達標率（到期前先用短期表現）。
- F3 網紅記分板：預先算好存檔，LINE 代號查詢與個股 AI 也能用。
- F4 規則體檢：每月重看網站各燈號、訊號的回測，失效或轉弱就標出來（LINE 每月第一份週報附上）。
- F5 資料累積進度：每個記分板目前有幾筆樣本、大概什麼時候才有統計意義。
- F6 LINE 推播額度：官方 API 查本月已用幾則、上限幾則。
- F7 週報的 AI 自我檢討。
- F8 提示版本：每份解讀／報告記下當時的提示版本，命中率可以按版本比較。

每天 update.yml 跑 更新回饋統計() → data/feedback.json；每月跑 更新規則體檢() → data/rule_health.json。
"""
import datetime as dt
import json
import os

import numpy as np
import pandas as pd

import engine

資料夾 = engine.資料夾
回饋檔 = 資料夾 / "feedback.json"
體檢檔 = 資料夾 / "rule_health.json"
台北 = dt.timezone(dt.timedelta(hours=8))
樣本門檻 = 10        # 少於這個數字的統計只當參考
可參考門檻 = 30       # 資料累積進度：到這個樣本數才算「有統計意義」

# F8：每次改提示就在這裡加一行（版本碼會自動算，這裡只是給人看的說明）
提示修改紀錄 = [
    ("2026-11-12", "加入 AI 錯誤本、券商與網紅過去紀錄、規則體檢（回饋循環 F1～F4）；開始記錄提示版本"),
]


# ---------- 共用 ----------
def _數(v):
    try:
        v = float(v)
        return v if np.isfinite(v) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _今天():
    return pd.Timestamp(dt.datetime.now(台北).date())


def 讀取回饋():
    try:
        return json.loads(回饋檔.read_text("utf-8")) if 回饋檔.exists() else {}
    except Exception:
        return {}


def 讀取規則體檢():
    try:
        return json.loads(體檢檔.read_text("utf-8")) if 體檢檔.exists() else {}
    except Exception:
        return {}


# ---------- F1 大盤解讀錯誤本 ----------
def 錯因(x):
    """看法說錯的粗分類（用加權當天漲跌幅判斷錯得多離譜）。"""
    幅 = abs(x.get("加權漲跌%") or 0)
    if 幅 < 0.3:
        return "幾乎平盤，差一點"
    if 幅 >= 1.5:
        return "大幅看錯方向"
    return "方向看錯"


def 大盤錯誤本(驗收, 篇數=20, 最多=5):
    """給大盤 AI 的文字：最近 篇數 篇的命中率、說錯的例子與偏誤提醒。驗收＝engine.驗收大盤解讀() 的結果（新到舊）。"""
    近 = (驗收 or [])[:篇數]
    if not 近:
        return ""
    分 = engine.解讀記分(近, 篇數)
    行 = [f"【AI 錯誤本：網站最近 {分['篇數']} 篇大盤解讀對答案】"
         f"看法命中 {分['看法命中']}/{分['看法篇數']} 篇（中性不計）、價位條件成立 {分['條件成立']}/{分['條件數']} 條"]
    錯 = [x for x in 近 if x.get("看法對") is False]
    if 錯:
        行.append("看錯的（新到舊）：")
        行 += [f"- {str(x['時間'])[:10]} {x['模式']}說「{x['看法']}」，{pd.Timestamp(x['驗收日']):%m/%d} 加權 "
              f"{x['加權漲跌%']:+.2f}%（{錯因(x)}）" for x in 錯[:最多]]
        多錯 = sum(1 for x in 錯 if x["看法"] == "偏多")
        空錯 = len(錯) - 多錯
        if 多錯 >= 3 and 多錯 >= 2 * max(空錯, 1):
            行.append(f"偏誤提醒：看錯多半是「偏多」（{多錯} 次），留意是否太樂觀。")
        elif 空錯 >= 3 and 空錯 >= 2 * max(多錯, 1):
            行.append(f"偏誤提醒：看錯多半是「偏空」（{空錯} 次），留意是否太悲觀。")
    else:
        行.append("最近沒有看錯方向的紀錄。")
    if 分["條件數"] >= 6 and 分["條件成立"] / 分["條件數"] < 0.3:
        行.append("提出的價位條件多半沒有發生，價位可能設得離現價太遠，請挑最近、最可能被測試的價位。")
    if 分["看法篇數"] >= 6 and 分["看法命中"] / 分["看法篇數"] < 0.5:
        行.append("看法命中率不到一半：方向沒把握時寫「中性」並把重點放在條件，不要硬猜漲跌。")
    return "\n".join(行)


# ---------- F1 個股 AI 報告回顧 ----------
def 個股AI回顧(紀錄們, 價格, 最多=3):
    """這檔過去網站 AI 報告的對答案（新到舊）。價格：這檔 date、high、low、收盤。"""
    if not 紀錄們 or 價格 is None or not len(價格):
        return ""
    p = 價格.sort_values("date")
    現 = float(p["收盤"].iloc[-1])
    行 = []
    for 紀 in 紀錄們[:最多]:
        建 = 紀.get("建議") or engine.拆解AI建議(紀.get("內容", ""))[1] or {}
        驗 = engine.驗收AI報告(紀, p)
        當時 = _數(紀.get("收盤"))
        漲 = f"{(現 / 當時 - 1) * 100:+.1f}%" if 當時 == 當時 and 當時 else "—"
        結果 = {"達標": "先碰到目標價", "停損": "先跌到停損價（看錯）", "進行中": "還沒碰到目標或停損",
               "無目標價": "沒有目標價"}[驗["結果"]]
        行.append(f"- {str(紀.get('時間', ''))[:10]} 看法 {建.get('看法') or '未標'}、合理價 {建.get('目標價合理')}、"
                 f"停損 {建.get('停損')}；之後到現在 {漲}，{結果}")
    if not 行:
        return ""
    return "\n".join(["網站 AI 過去對這檔的報告（對答案）："] + 行 +
                     ["如果上次看錯（停損或方向相反），先寫出這次跟上次有什麼不同，再下結論。"])


def AI報告整體文字(回饋=None):
    """全部個股 AI 報告的整體成績（給個股 AI 當自我提醒）。"""
    a = (回饋 or 讀取回饋()).get("AI報告") or {}
    結 = a.get("達標", 0) + a.get("停損", 0)
    if not 結:
        return ""
    行 = f"網站 AI 個股報告整體成績：已結案 {結} 份，達標 {a['達標']}、停損 {a['停損']}（命中 {a['達標'] / 結 * 100:.0f}%）"
    多 = a.get("看多停損率%")
    if 多 is not None:
        行 += f"；偏多報告停損率 {多:.0f}%"
    if 結 < 樣本門檻:
        行 += "（樣本還少，只當參考）"
    return 行 + "。目標價與停損請保守一點，停損放在真正的支撐下方。"


# ---------- F2 券商過去紀錄 ----------
def 券商紀錄表(報告們, 價格們, 加權K=None, 天數=(20, 60)):
    """每份報告之後 N 個交易日的報酬扣掉同期加權（超額%），依券商彙總。
    看多＋超額 > 0、看空＋超額 < 0 算說對（中性不算）。另附 6 個月達標（engine.驗收券商報告）。
    價格們＝{代號: DataFrame(date, high, low, 收盤)}。回傳 DataFrame（index＝券商）。"""
    加 = 加權K.set_index("date")["close"].astype(float).sort_index() if 加權K is not None and len(加權K) else None
    列們 = []
    for x in 報告們 or []:
        p = 價格們.get(str(x.get("代號")))
        d = pd.to_datetime(x.get("日期"), errors="coerce")
        if p is None or pd.isna(d) or not x.get("券商"):
            continue
        p = p.sort_values("date")
        前, 後 = p[p["date"] <= d], p[p["date"] > d]
        if not len(前):
            continue
        基 = float(前["收盤"].iloc[-1])
        驗 = engine.驗收券商報告(x, p)
        # 達標會提早出現、沒達標要等滿 6 個月，所以達標率只算「已經滿 6 個月」的報告，免得一開始虛高
        列 = {"券商": x["券商"], "看法": x.get("看法"), "結果": 驗["結果"], "滿期": 驗["天數"] >= 126}
        for n in 天數:
            if len(後) >= n and 基:
                迄 = 後["date"].iloc[n - 1]
                超 = (float(後["收盤"].iloc[n - 1]) / 基 - 1) * 100
                if 加 is not None:
                    a, b = 加[加.index <= d], 加[加.index <= 迄]
                    if len(a) and len(b):
                        超 -= (float(b.iloc[-1]) / float(a.iloc[-1]) - 1) * 100
                列[f"{n}日超額%"] = 超
        列們.append(列)
    if not 列們:
        return pd.DataFrame()
    t = pd.DataFrame(列們)
    for n in 天數:
        if f"{n}日超額%" not in t:
            t[f"{n}日超額%"] = np.nan
    彙 = {}
    for 券, g in t.groupby("券商"):
        r = {"報告數": len(g), "看多比例%": round(float((g["看法"] == "看多").mean() * 100))}
        for n in 天數:
            s = g.dropna(subset=[f"{n}日超額%"])
            s = s[s["看法"].isin(["看多", "看空"])]
            對 = ((s["看法"] == "看多") & (s[f"{n}日超額%"] > 0)) | ((s["看法"] == "看空") & (s[f"{n}日超額%"] < 0))
            r[f"{n}日到期"] = len(s)
            r[f"{n}日說對%"] = round(float(對.mean() * 100)) if len(s) else None
            r[f"{n}日平均超額%"] = round(float(s[f"{n}日超額%"].mean()), 2) if len(s) else None
        滿 = g[g["滿期"]]
        達, 未 = int((滿["結果"] == "達標").sum()), int((滿["結果"] == "到期未達標").sum())
        r.update({"已達標": 達, "到期未達標": 未, "達標率%": round(達 / (達 + 未) * 100) if 達 + 未 else None,
                  "提前達標": int((g["結果"] == "達標").sum())})
        彙[券] = r
    return pd.DataFrame.from_dict(彙, orient="index").sort_values("報告數", ascending=False)


def 券商紀錄文字(紀錄, 券商們):
    """給個股 AI：這檔有出報告的券商，過去整體準不準。紀錄＝feedback.json 的「券商」（{券商: {...}}）。"""
    if not 紀錄 or not 券商們:
        return ""
    行 = []
    for 券 in dict.fromkeys(券商們):
        r = 紀錄.get(券)
        if not r:
            continue
        段 = [f"報告 {r['報告數']} 份"]
        if r.get("20日到期"):
            段.append(f"20 日後說對 {r['20日說對%']}%（{r['20日到期']} 份到期，平均超額 {r['20日平均超額%']:+.1f}%）")
        if r.get("60日到期"):
            段.append(f"60 日後說對 {r['60日說對%']}%（{r['60日到期']} 份）")
        if r.get("達標率%") is not None:
            段.append(f"6 個月達標 {r['已達標']}/{r['已達標'] + r['到期未達標']}")
        else:
            段.append(f"6 個月目標價還沒有滿期的（已提前達標 {r.get('提前達標', 0)} 份）")
        少 = "（樣本少，只當參考）" if (r.get("20日到期") or 0) < 樣本門檻 else ""
        行.append(f"- {券}：" + "，".join(段) + 少)
    if not 行:
        return ""
    return "\n".join(["這檔有出報告的券商，過去在全部股票的紀錄（說對＝看多後跑贏加權）：", *行,
                      "引用券商目標價時，紀錄好的可以多參考，紀錄差或樣本少的要打折，並寫出依據。"])


# ---------- F3 網紅記分板（預先算好） ----------
def 網紅記分板表(回饋=None):
    t = (回饋 or 讀取回饋()).get("網紅") or {}
    return pd.DataFrame.from_dict(t, orient="index") if t else pd.DataFrame()


def LINE個股摘要(代號, 收盤, 紀錄們, 價格, 報告們, 影片們, 回饋=None):
    """LINE 代號查詢的 AI 數據摘要補充：券商報告與共識、券商過去紀錄、網紅說法（附記分板）、過去 AI 報告對答案。"""
    回饋 = 回饋 if 回饋 is not None else 讀取回饋()
    段 = []
    券們 = [x for x in 報告們 or [] if str(x.get("代號")) == str(代號)]
    if 券們:
        段.append("使用者上傳的券商報告摘要（數字以此為準）：\n" + "\n".join(
            f"- {x.get('日期')} {x.get('券商')} {x.get('評等')}，目標價 {x.get('目標價')}（前次 {x.get('前次目標價')}），"
            f"EPS 今年 {x.get('EPS今年')}／明年 {x.get('EPS明年')}，{x.get('評價方法') or ''}；{x.get('理由') or ''}"
            for x in 券們[:6]))
        try:
            段.append("- 券商共識：" + engine.共識文字(engine.券商共識(券們, float(收盤))))
        except Exception as e:
            print("券商共識失敗：", repr(e))
        紀 = 券商紀錄文字(回饋.get("券商"), [x.get("券商") for x in 券們])
        if 紀:
            段.append(紀)
    try:
        網 = engine.網紅觀點摘要(影片們, 代號=代號, 記分板=網紅記分板表(回饋))
        if 網:
            段.append("\n".join(網))
    except Exception as e:
        print("網紅觀點失敗：", repr(e))
    for x in (個股AI回顧(紀錄們, 價格), AI報告整體文字(回饋)):
        if x:
            段.append(x)
    return "\n\n".join(段)


def LINE券商紀錄短句(券商們, 回饋=None):
    """LINE 第一批文字用：這檔有報告的券商，20 日後說對率（樣本夠的才列）。"""
    紀 = (回饋 if 回饋 is not None else 讀取回饋()).get("券商") or {}
    句 = [f"{券} {紀[券]['20日說對%']}%（{紀[券]['20日到期']} 份）" for 券 in dict.fromkeys(券商們)
         if 券 in 紀 and (紀[券].get("20日到期") or 0) >= 樣本門檻]
    return ("　過去 20 日說對率：" + "、".join(句[:4])) if 句 else ""


def LINE網紅記分短句(頻道們, 回饋=None):
    彙 = (回饋 if 回饋 is not None else 讀取回饋()).get("網紅") or {}
    句 = [f"{頻} {彙[頻]['命中率%']:.0f}%（{彙[頻]['到期']} 則）" for 頻 in dict.fromkeys(頻道們)
         if 頻 in 彙 and (彙[頻].get("到期") or 0) >= 3 and 彙[頻].get("命中率%") is not None]
    return ("　記分板：" + "、".join(句[:4])) if 句 else ""


# ---------- F4 規則體檢 ----------
def _判定(超額, 次數, 門=0.3):
    if 次數 is None or 次數 < 8 or 超額 is None or 超額 != 超額:
        return "樣本太少"
    if 超額 >= 門:
        return "有效"
    if 超額 <= -門:
        return "反向"
    return "沒有優勢"


def _統計列(名, 統計, 基準=None, 說明=""):
    """把 {天數, 次數, 平均%, 基準平均%} 的清單轉成體檢列（看 20 日；沒有就看最接近的）。"""
    if not 統計:
        return None
    s = sorted(統計, key=lambda r: abs(r.get("天數", 0) - 20))[0]
    基 = s.get("基準平均%")
    if 基 is None and 基準:
        基 = next((b.get("基準平均%") for b in 基準 if b.get("天數") == s.get("天數")), None)
    if s.get("平均%") is None or 基 is None:
        return None
    超 = round(float(s["平均%"]) - float(基), 2)
    return {"規則": 名, "說明": 說明, "天數": s.get("天數"), "次數": s.get("次數"), "超額%": 超,
            "判定": _判定(超, s.get("次數"))}


def 規則體檢():
    """收集網站各燈號／訊號的回測結果，統一成「亮燈後 20 日比任何一天多賺幾 %」。回傳 list of dict。"""
    列們 = []
    融 = engine.讀取大盤融資洗盤() or {}
    基準 = (融.get("洗盤") or {}).get("統計")
    for 鍵, 名, 說 in (("洗盤", "大盤融資洗盤日（單日減 1.5%）", "01 資金面"),
                     ("大洗盤", "大盤融資大洗盤（單日減 2.5%）", "01 資金面"),
                     ("減幅比", "融資減幅比 ≥ 70%", "01 資金面"),
                     ("正2背離", "大盤跌、正2融資大增", "01 資金面")):
        r = _統計列(名, (融.get(鍵) or {}).get("統計"), 說明=說)
        if r:
            列們.append(r)
    恐 = 融.get("恐慌日") or {}
    for 鍵, 名 in (("全部", "恐慌日"), ("融資有洗", "恐慌日＋融資有洗"), ("融資沒洗", "恐慌日但融資沒洗")):
        r = _統計列(名, 恐.get(鍵), 基準, "01 資金面")
        if r:
            列們.append(r)
    try:
        止 = engine.止跌三階段回測(engine.讀取指數K線("TAIEX"))
        r = _統計列("止跌三階段", (止 or {}).get("統計"), 說明="01 價位區")
        if r:
            列們.append(r)
    except Exception as e:
        print("止跌三階段體檢失敗：", repr(e))
    for 檔, 說 in (("momentum_backtest.json", "04 順勢訊號（個股）"), ("rule_backtest.json", "講義 K 棒規則（個股）")):
        try:
            d = json.loads((資料夾 / 檔).read_text("utf-8"))
        except Exception:
            continue
        for s in d.get("訊號") or d.get("規則") or []:
            超 = s.get("20日超額%", s.get("超額%"))
            次 = s.get("次數", s.get("筆數"))
            名 = s.get("規則") or s.get("訊號")
            if 超 is None or not 名:
                continue
            結論 = {"成立": "有效", "相反": "反向", "沒差": "沒有優勢", "偏弱": "沒有優勢"}.get(s.get("結論"))
            if 次 is not None and 次 < 8:
                結論 = "樣本太少"
            列們.append({"規則": 名, "說明": 說 + (f"：{s['講義說法']}" if s.get("講義說法") else ""),
                       "天數": s.get("天數", 20), "次數": 次, "超額%": round(float(超), 2),
                       "判定": 結論 or _判定(float(超), 次, 0.2)})
    try:
        評 = json.loads((資料夾 / "score_backtest.json").read_text("utf-8")).get("相關") or {}
        for 欄, v in 評.items():
            t = v.get("t")
            列們.append({"規則": f"評分：{欄}", "說明": "07 評分（IC 的 t 值）", "天數": 20, "次數": None,
                       "超額%": v.get("IC"), "判定": "有效" if t is not None and t >= 2 else
                       "反向" if t is not None and t <= -2 else "沒有優勢"})
    except Exception:
        pass
    return 列們


def 更新規則體檢(強制=False, 間隔天數=25, 保留=24):
    """GitHub Actions 每天呼叫；距上次超過 間隔天數 才重算，結果加到歷史（最多 保留 次）。"""
    舊 = 讀取規則體檢()
    歷史 = 舊.get("歷史", [])
    if 歷史 and not 強制 and (_今天() - pd.Timestamp(歷史[-1]["計算日"])).days < 間隔天數:
        print("規則體檢：還不用重算")
        return 舊
    結果 = {"計算日": f"{_今天():%Y-%m-%d}", "規則": 規則體檢()}
    歷史 = (歷史 + [結果])[-保留:]
    體檢檔.write_text(json.dumps({"歷史": 歷史}, ensure_ascii=False, indent=1), "utf-8")
    print(f"規則體檢：{len(結果['規則'])} 條")
    return {"歷史": 歷史}


def 體檢變化(體檢=None):
    """最新一次跟前一次比，判定有變的規則。回傳 [(規則, 前判定, 今判定, 今超額%)]。"""
    歷 = (體檢 or 讀取規則體檢()).get("歷史", [])
    if len(歷) < 2:
        return []
    前 = {r["規則"]: r for r in 歷[-2]["規則"]}
    return [(r["規則"], 前[r["規則"]]["判定"], r["判定"], r["超額%"]) for r in 歷[-1]["規則"]
            if r["規則"] in 前 and 前[r["規則"]]["判定"] != r["判定"]]


def 規則體檢文字(體檢=None, 給AI=False):
    """LINE 月報或大盤 AI 用的文字。"""
    體檢 = 體檢 or 讀取規則體檢()
    歷 = 體檢.get("歷史", [])
    if not 歷:
        return []
    最新 = 歷[-1]
    無效 = [r for r in 最新["規則"] if r["判定"] in ("沒有優勢", "反向") and not str(r["規則"]).startswith("評分")]
    有效 = [r for r in 最新["規則"] if r["判定"] == "有效" and not str(r["規則"]).startswith("評分")]
    if 給AI:
        if not 無效:
            return []
        return [f"【規則體檢 {最新['計算日']}】這些燈號回測後沒有優勢或反向，不要當主要依據："
                + "、".join(f"{r['規則']}（{r['天數']} 日超額 {r['超額%']:+.1f}%）" for r in 無效[:8])]
    行 = ["", f"🩺 規則體檢（{最新['計算日']}，亮燈後 20 日比任何一天多賺幾 %）",
         f"有效 {len(有效)} 條、沒有優勢 {sum(r['判定'] == '沒有優勢' for r in 最新['規則'])} 條、"
         f"反向 {sum(r['判定'] == '反向' for r in 最新['規則'])} 條、樣本太少 {sum(r['判定'] == '樣本太少' for r in 最新['規則'])} 條"]
    變 = 體檢變化(體檢)
    if 變:
        行.append("這個月有變化：" + "；".join(f"{名} {前}→{今}（{超:+.2f}）" for 名, 前, 今, 超 in 變[:8]))
    else:
        行.append("跟上個月比沒有規則改變判定。" if len(歷) >= 2 else "第一次體檢，下個月開始比較變化。")
    if 無效:
        行.append("目前不建議當依據：" + "、".join(r["規則"] for r in 無效[:8]))
    return 行


# ---------- F5 資料累積進度 ----------
def _預估日(樣本, 起, 門檻=可參考門檻):
    """依目前累積速度推估什麼時候到 門檻 筆。"""
    if 樣本 >= 門檻:
        return "已達到"
    if not 樣本 or 起 is None or pd.isna(起):
        return "還沒有樣本"
    天 = max((_今天() - pd.Timestamp(起)).days, 1)
    return f"約 {_今天() + pd.Timedelta(days=int(天 / 樣本 * (門檻 - 樣本))):%Y-%m}"


def _預估到期(日期們, 門檻, 延遲天數):
    """要等 延遲天數 才能對答案的記分板：第 門檻 筆資料的日期 ＋ 延遲天數；資料還不夠就照目前速度推。"""
    d = pd.Series(pd.to_datetime(pd.Series(list(日期們)), errors="coerce")).dropna().sort_values().reset_index(drop=True)
    if not len(d):
        return "還沒有樣本"
    if len(d) >= 門檻:
        日 = d.iloc[門檻 - 1] + pd.Timedelta(days=延遲天數)
    else:
        天 = max((_今天() - d.iloc[0]).days, 1)
        日 = _今天() + pd.Timedelta(days=int(天 / len(d) * (門檻 - len(d)) + 延遲天數))
    return "已達到" if 日 <= _今天() else f"約 {日:%Y-%m}"


def _體檢預估(歷史, 次數=6):
    if len(歷史) >= 次數:
        return "已達到"
    起 = pd.Timestamp(歷史[0]["計算日"]) if 歷史 else _今天()
    return f"約 {起 + pd.Timedelta(days=30 * (次數 - 1)):%Y-%m}"


# ---------- F6 LINE 推播額度 ----------
推播來源估計 = [  # (功能, 每月約幾則, 說明)；回覆代號查詢不算額度
    ("收盤摘要", 21, "每個交易日 1 則（一次最多 5 段只算 1 則）"),
    ("AI 大盤解讀", 63, "盤前、收盤、夜盤各 1 則 × 約 21 個交易日"),
    ("網紅新片提醒", 30, "每天 10:41、21:11，有新片才傳"),
    ("到價與條件提醒", 15, "盤中到價、條件訂閱、營收新高等，有觸發才傳"),
    ("週報＋Gemini 用量小卡", 8, "每週六 2 則"),
    ("資料健康檢查", 3, "有問題才傳"),
]


def LINE推播額度(權杖=None):
    """官方 API：本月上限與已用則數。回傳 {上限, 已用, 類型} 或 None（沒有權杖或查不到）。"""
    import requests
    權杖 = engine.清理金鑰(權杖 or os.environ.get("LINE_TOKEN"))
    if not 權杖:
        return None
    標 = {"Authorization": f"Bearer {權杖}"}
    try:
        q = requests.get("https://api.line.me/v2/bot/message/quota", headers=標, timeout=10)
        c = requests.get("https://api.line.me/v2/bot/message/quota/consumption", headers=標, timeout=10)
        q.raise_for_status()
        c.raise_for_status()
        q, c = q.json(), c.json()
        return {"上限": q.get("value") if q.get("type") == "limited" else None, "類型": q.get("type"),
                "已用": int(c.get("totalUsage", 0)), "查詢時間": f"{dt.datetime.now(台北):%Y-%m-%d %H:%M}"}
    except Exception as e:
        print("LINE 額度查詢失敗：", repr(e))
        return None


def 額度文字(額):
    if not 額:
        return ""
    if not 額.get("上限"):
        return f"📮 LINE 本月已推播 {額['已用']} 則（沒有上限）"
    今 = _今天()
    月天 = 今.days_in_month
    估 = round(額["已用"] / max(今.day, 1) * 月天)
    文 = f"📮 LINE 本月已推播 {額['已用']}/{額['上限']} 則，照目前速度月底約 {估} 則"
    if 估 > 額["上限"]:
        文 += "，⚠️ 會超過免費上限（超過後推播會失敗，代號查詢的回覆不受影響）"
    return 文


# ---------- 每天彙總：data/feedback.json ----------
def 計算回饋統計(設定, 價格們=None, 加權K=None):
    """讀 ai-reports 的解讀、AI 報告、券商報告、網紅說法，算出記分板與進度。價格們不給就自己讀資料庫。"""
    今 = _今天()
    加權K = 加權K if 加權K is not None else engine.讀取指數K線("TAIEX")
    結果 = {"計算日": f"{今:%Y-%m-%d}"}
    報告們 = engine.讀取券商報告(設定)
    影片們 = [v for v in engine.讀取網紅說法(設定) if not engine.是AI工具影片(v)]
    try:
        AI們 = engine.列出AI報告(設定)
    except Exception as e:
        print("讀 AI 報告失敗：", repr(e))
        AI們 = {}
    if 價格們 is None:
        代們 = sorted({str(x.get("代號")) for x in 報告們} | {str(s.get("代號")) for v in 影片們 for s in v.get("股票", [])}
                    | set(AI們))
        代們 = [c for c in 代們 if c[:1].isdigit()]
        原 = engine.讀取資料庫(代號=代們, 起日=今 - pd.Timedelta(days=400)) if 代們 else None
        價格們 = {} if 原 is None else {c: g.rename(columns={"close": "收盤"})[["date", "high", "low", "收盤"]]
                                       for c, g in 原.groupby("code")}
        del 原

    # 大盤解讀（含 F8 版本）
    驗 = engine.驗收大盤解讀(engine.讀取大盤解讀(設定), {"加權": 加權K, "櫃買": engine.讀取指數K線("TPEX")})
    紀 = engine.讀取大盤解讀(設定)
    for x in 驗:
        x["提示版本"] = (紀.get(x["鍵"]) or {}).get("提示版本") or "未記錄"
    分 = engine.解讀記分(驗, len(驗))
    結果["大盤解讀"] = {**分, "最早": str(驗[-1]["時間"])[:10] if 驗 else None,
                     "近20篇": engine.解讀記分(驗, 20),
                     "明細": [{"時間": x["時間"], "模式": x["模式"], "看法": x["看法"], "驗收日": f"{pd.Timestamp(x['驗收日']):%Y-%m-%d}",
                             "加權漲跌%": round(x["加權漲跌%"], 2), "看法對": x["看法對"],
                             "條件": [{"說明": c["說明"], "成立": c["成立"]} for c in x["條件"]],
                             "提示版本": x["提示版本"]} for x in 驗[:60]]}

    # 個股 AI 報告（含 F8 版本）
    明細 = []
    for 代, 紀錄們 in AI們.items():
        p = 價格們.get(代)
        if p is None or not 紀錄們:
            continue
        for 紀1 in 紀錄們:
            v = engine.驗收AI報告(紀1, p)
            建 = 紀1.get("建議") or engine.拆解AI建議(紀1.get("內容", ""))[1] or {}
            明細.append({"代號": 代, "時間": str(紀1.get("時間", ""))[:16], "看法": 建.get("看法"), "結果": v["結果"],
                       "結案日": f"{v['日期']:%Y-%m-%d}" if pd.notna(v["日期"]) else None,
                       "提示版本": 紀1.get("提示版本") or "未記錄"})
    m = pd.DataFrame(明細)
    if len(m):
        多 = m[m["看法"] == "偏多"]
        多結 = 多[多["結果"].isin(["達標", "停損"])]
        結果["AI報告"] = {"份數": len(m), "達標": int((m["結果"] == "達標").sum()), "停損": int((m["結果"] == "停損").sum()),
                        "進行中": int((m["結果"] == "進行中").sum()), "最早": m["時間"].min()[:10],
                        "看多停損率%": round(float((多結["結果"] == "停損").mean() * 100)) if len(多結) >= 3 else None,
                        "近期結案": m.dropna(subset=["結案日"]).sort_values("結案日", ascending=False).head(30).to_dict("records"),
                        "版本": {k: {"份數": len(g), "達標": int((g["結果"] == "達標").sum()), "停損": int((g["結果"] == "停損").sum())}
                               for k, g in m.groupby("提示版本")}}
    else:
        結果["AI報告"] = {"份數": 0, "達標": 0, "停損": 0, "進行中": 0}

    # F2 券商
    券 = 券商紀錄表(報告們, 價格們, 加權K)
    結果["券商"] = {k: {c: (None if isinstance(v, float) and np.isnan(v) else v) for c, v in r.items()}
                  for k, r in 券.to_dict("index").items()} if len(券) else {}

    # F3 網紅
    彙 = engine.網紅記分板(影片們, 價格們, 加權K)
    結果["網紅"] = {k: {c: (None if isinstance(v, float) and np.isnan(v) else (int(v) if isinstance(v, (np.integer,)) else v))
                       for c, v in r.items()} for k, r in 彙.to_dict("index").items()} if len(彙) else {}

    # F5 進度
    大 = 結果["大盤解讀"]
    a = 結果["AI報告"]
    券到20 = int(券["20日到期"].sum()) if len(券) else 0
    券到期 = int((券["已達標"] + 券["到期未達標"]).sum()) if len(券) else 0
    多空日 = [x.get("日期") for x in 報告們 if x.get("看法") in ("看多", "看空")]
    網日 = [v.get("日期") for v in 影片們 for s in v.get("股票", []) if s.get("看法") in ("看多", "看空")]
    網到 = int(彙["到期"].sum()) if len(彙) else 0
    結果["進度"] = [
        {"記分板": "大盤解讀看法", "樣本": 大["看法篇數"], "說明": "盤前／收盤／夜盤的偏多偏空，隔一個收盤對答案",
         "預估": _預估日(大["看法篇數"], 大["最早"])},
        {"記分板": "個股 AI 報告", "樣本": a["達標"] + a["停損"], "說明": "先碰到目標價或停損價才算結案",
         "預估": _預估日(a["達標"] + a["停損"], a.get("最早"))},
        {"記分板": "券商報告（20 日）", "樣本": 券到20, "說明": "報告後 20 個交易日跑贏加權沒",
         "預估": "已達到" if 券到20 >= 100 else _預估到期(多空日, 100, 28)},
        {"記分板": "券商目標價（6 個月）", "樣本": 券到期, "說明": "6 個月內有沒有碰到目標價",
         "預估": "已達到" if 券到期 >= 100 else _預估到期(多空日, 100, 183)},
        {"記分板": "網紅說法（20 日）", "樣本": 網到, "說明": "看多看空 20 個交易日後對答案",
         "預估": "已達到" if 網到 >= 100 else _預估到期(網日, 100, 28)},
        {"記分板": "規則體檢", "樣本": len(讀取規則體檢().get("歷史", [])), "說明": "每月一次，看燈號有沒有失效",
         "預估": _體檢預估(讀取規則體檢().get("歷史", []))},
    ]
    for r in 結果["進度"]:
        門 = 100 if "券商" in r["記分板"] or "網紅" in r["記分板"] else 6 if r["記分板"] == "規則體檢" else 可參考門檻
        r["門檻"] = 門
        r["狀態"] = "✅ 可參考" if r["樣本"] >= 門 else "⏳ 累積中"
    # F6
    額 = LINE推播額度()
    if 額:
        結果["LINE額度"] = 額
    elif 回饋檔.exists():
        舊 = 讀取回饋().get("LINE額度")
        if 舊:
            結果["LINE額度"] = 舊
    return 結果


def 更新回饋統計():
    """GitHub Actions（update.yml）呼叫：寫 data/feedback.json。"""
    設定 = {"GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
            "AI_REPO": os.environ.get("GITHUB_REPOSITORY", "gelu27/Stock-lab")}
    結果 = 計算回饋統計(設定)
    回饋檔.write_text(json.dumps(結果, ensure_ascii=False, indent=1, default=str), "utf-8")
    print(f"回饋統計：大盤解讀 {結果['大盤解讀']['篇數']} 篇、AI 報告 {結果['AI報告']['份數']} 份、"
          f"券商 {len(結果['券商'])} 家、網紅 {len(結果['網紅'])} 個頻道")
    return 結果


# ---------- F7 週報：AI 自我檢討 ----------
def 週報自我檢討(起, 迄, 回饋=None):
    """這週（起～迄）大盤解讀與個股 AI 報告的對答案，回傳 LINE 文字行。"""
    回饋 = 回饋 or 讀取回饋()
    起, 迄 = pd.Timestamp(起), pd.Timestamp(迄)
    行 = []
    週 = [x for x in (回饋.get("大盤解讀") or {}).get("明細", []) if 起 <= pd.Timestamp(x["驗收日"]) <= 迄]
    if 週:
        看 = [x for x in 週 if x["看法對"] is not None]
        對 = sum(1 for x in 看 if x["看法對"])
        條 = [c for x in 週 for c in x["條件"]]
        行 += ["", "🤖 AI 本週自我檢討",
               f"大盤解讀 {len(週)} 篇：看法說對 {對}/{len(看)}（中性不計）、價位條件成立 {sum(c['成立'] for c in 條)}/{len(條)}"]
        for x in [x for x in 看 if not x["看法對"]][:3]:
            行.append(f"✗ {x['時間'][5:10]} {x['模式']}說{x['看法']}，{x['驗收日'][5:]} 加權 {x['加權漲跌%']:+.2f}%（{錯因(x)}）")
        if 看 and 對 == len(看):
            行.append("本週看法全對。")
    結 = [x for x in (回饋.get("AI報告") or {}).get("近期結案", []) if x.get("結案日") and 起 <= pd.Timestamp(x["結案日"]) <= 迄]
    if 結:
        if not 行:
            行 += ["", "🤖 AI 本週自我檢討"]
        達 = list(dict.fromkeys(x["代號"] for x in 結 if x["結果"] == "達標"))
        損 = list(dict.fromkeys(x["代號"] for x in 結 if x["結果"] == "停損"))
        行.append(f"個股 AI 報告本週結案 {len(結)} 份：達標 {sum(x['結果'] == '達標' for x in 結)} 份"
                 + (f"（{'、'.join(達[:6])}）" if 達 else "")
                 + f"、停損 {sum(x['結果'] == '停損' for x in 結)} 份" + (f"（{'、'.join(損[:6])}）" if 損 else ""))
    if 行:
        a = 回饋.get("AI報告") or {}
        結數 = a.get("達標", 0) + a.get("停損", 0)
        if 結數:
            行.append(f"累計：個股報告命中 {a['達標'] / 結數 * 100:.0f}%（{結數} 份結案）")
        行.append("說錯的已經自動放進下次 AI 的提示（錯誤本）。")
    return 行
