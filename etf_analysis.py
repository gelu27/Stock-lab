# 主動式 ETF 進階分析：持股總排名、分 ETF 小計、全部異動、規則版今日解讀、AI 指令、PDF 報告
# 網站（app.py 06 主動式 ETF）與 PDF 共用；輸入都是 etf_data.每日變化() 的結果，只看「扣除申贖」後的主動調整

import re

import numpy as np
import pandas as pd

主動類型 = ["新增", "加碼", "減碼", "出清"]


def _億(v):
    """金額（元）→「+1.23 億」或「+456 萬」。"""
    if v is None or pd.isna(v):
        return "—"
    return f"{v / 1e8:+,.2f} 億" if abs(v) >= 1e8 else f"{v / 1e4:+,.0f} 萬"


def _名(代號, 名稱, 預設=""):
    return f"{名稱.get(代號) or 預設 or 代號}"


def 持股排名(最新持股, 最新變化, 收盤, 發行股數=None):
    """所有主動式 ETF 合計持有每檔股票的張數、市值、持有檔數、占股本比例與今天扣申贖的增減。"""
    if 最新持股.empty:
        return pd.DataFrame()
    群 = 最新持股[最新持股["shares"] > 0].groupby("code")
    排 = pd.DataFrame({"名稱": 群["name"].first(), "張數": 群["shares"].sum() / 1000,
                      "檔數": 群["etf"].nunique(), "最高權重": 群["weight"].max(),
                      "持有ETF": 群["etf"].apply(lambda s: "、".join(sorted(set(s))))})
    排["現價"] = 排.index.map(lambda c: 收盤.get(c, np.nan))
    排["市值億"] = 排["張數"] * 1000 * 排["現價"] / 1e8
    if 發行股數:
        排["占股本%"] = 排["張數"] * 1000 / 排.index.map(lambda c: 發行股數.get(c, np.nan)) * 100
    if len(最新變化):
        今 = 最新變化.groupby("code")["adj_delta"].sum() / 1000
        排["今日增減"] = 排.index.map(lambda c: 今.get(c, 0.0))
    排 = 排.sort_values(["市值億", "張數"], ascending=False, na_position="last")
    排.insert(0, "排名", range(1, len(排) + 1))
    return 排.rename_axis("代號").reset_index()


def 全部異動(最新變化, 最新持股):
    """每檔 ETF 今天的新增、加碼、減碼、出清，加上那檔股票在該 ETF 的比重排名（出清者沒有排名）。"""
    if 最新變化.empty:
        return pd.DataFrame()
    動 = 最新變化[最新變化["type"].isin(主動類型)].copy()
    排名 = 最新持股[最新持股["shares"] > 0].copy()
    排名["rank"] = 排名.groupby("etf")["weight"].rank(ascending=False, method="min")
    名次 = dict(zip(zip(排名["etf"], 排名["code"]), 排名["rank"]))
    動["比重排名"] = [名次.get((e, c), np.nan) for e, c in zip(動["etf"], 動["code"])]
    return 動.sort_values(["etf", "adj_amount"], ascending=[True, False])


def 基金小計(最新變化, 規模=None):
    """每檔 ETF 今天扣申贖的流入、流出、淨額（元）、動了幾檔、最大買進與最大賣出。"""
    if 最新變化.empty:
        return pd.DataFrame()
    列們 = []
    for e, t in 最新變化.groupby("etf"):
        動 = t[t["type"].isin(主動類型)]
        金 = 動["adj_amount"].fillna(0)
        買 = 動[金 > 0].sort_values("adj_amount", ascending=False)
        賣 = 動[金 < 0].sort_values("adj_amount")
        列們.append({"etf": e, "流入": 金[金 > 0].sum(), "流出": 金[金 < 0].sum(), "淨額": 金.sum(), "動檔數": len(動),
                    "新增": int((動["type"] == "新增").sum()), "出清": int((動["type"] == "出清").sum()),
                    "最大買": (買["code"].iloc[0], 買["name"].iloc[0], 買["adj_amount"].iloc[0]) if len(買) else None,
                    "最大賣": (賣["code"].iloc[0], 賣["name"].iloc[0], 賣["adj_amount"].iloc[0]) if len(賣) else None,
                    "週轉%": abs(金).sum() / 規模[e] * 100 if 規模 and 規模.get(e) else np.nan})
    return pd.DataFrame(列們).sort_values("淨額", ascending=False, key=lambda s: s.abs()).reset_index(drop=True)


def 個股彙總(變化範圍):
    """每檔股票：幾檔 ETF 買、幾檔賣、扣申贖張數與金額、買進與賣出的 ETF 清單。"""
    動 = 變化範圍[變化範圍["type"].isin(主動類型)]
    if 動.empty:
        return pd.DataFrame()
    買, 賣 = 動[動["adj_delta"] > 0], 動[動["adj_delta"] < 0]
    彙 = pd.DataFrame({"名稱": 動.groupby("code")["name"].first(),
                      "買進檔數": 買.groupby("code")["etf"].nunique(), "賣出檔數": 賣.groupby("code")["etf"].nunique(),
                      "張數": 動.groupby("code")["adj_delta"].sum() / 1000, "金額": 動.groupby("code")["adj_amount"].sum(),
                      "買金額": 買.groupby("code")["adj_amount"].sum(), "賣金額": 賣.groupby("code")["adj_amount"].sum(),
                      "買進ETF": 買.groupby("code")["etf"].apply(lambda s: "、".join(sorted(set(s)))),
                      "賣出ETF": 賣.groupby("code")["etf"].apply(lambda s: "、".join(sorted(set(s))))})
    for c in ["買進檔數", "賣出檔數"]:
        彙[c] = 彙[c].fillna(0).astype(int)
    for c in ["買金額", "賣金額"]:
        彙[c] = 彙[c].fillna(0)
    彙[["買進ETF", "賣出ETF"]] = 彙[["買進ETF", "賣出ETF"]].fillna("")
    return 彙.rename_axis("code").reset_index()


def 揭露狀態(最新日期, 資料日, 全部清單=()):
    """(較晚揭露：最新資料比別人早一天以上的 ETF, 未追蹤：有在交易但我們沒有持股資料的 ETF)。"""
    較晚 = sorted(e for e, d in 最新日期.items() if d < 資料日)
    未追蹤 = sorted(set(全部清單) - set(最新日期))
    return 較晚, 未追蹤


def 申贖金額(資訊, 最新日期):
    """每檔 ETF 最新一天的申購（正）／買回（負）金額 ≈ 單位數變化 × 淨值。"""
    結果 = {}
    for e, d in 最新日期.items():
        資 = 資訊[資訊["etf"] == e].sort_values("date")
        今, 前 = 資[資["date"] == d].tail(1), 資[資["date"] < d].tail(1)
        if len(今) and len(前) and pd.notna(今["units"].iloc[0]) and pd.notna(前["units"].iloc[0]):
            結果[e] = (今["units"].iloc[0] - 前["units"].iloc[0]) * 今["nav"].iloc[0]
    return 結果


# ---------- 規則版今日解讀 ----------
def 規則解讀(最新變化, 產業, 名稱, 資訊=None, 最新日期=None, ETF名=None):
    """依今天扣申贖後的異動，自動寫出幾段重點。回傳 [{"標題", "段落": [..], "色": 紅/綠/黃/紫/青}]。
    段落裡的 **粗體** 會在網站與 PDF 變成亮色。"""
    ETF名 = ETF名 or {}
    動 = 最新變化[最新變化["type"].isin(主動類型)].copy() if len(最新變化) else pd.DataFrame()
    if 動.empty:
        return [{"標題": "今天沒有主動調整", "段落": ["各檔主動式 ETF 今天的持股和前一份相比，扣除申購買回後都沒有明顯加減碼。"], "色": "黃"}]
    動["產業"] = 動["code"].map(lambda c: 產業.get(c) or "其他")
    動["股名"] = [_名(c, 名稱, n) for c, n in zip(動["code"], 動["name"])]
    段們 = []
    有價 = 動[動["adj_amount"].notna()]

    # 1. 族群資金流向
    群 = 有價.groupby("產業").agg(淨額=("adj_amount", "sum"),
                                 買檔=("etf", lambda s: s[有價.loc[s.index, "adj_amount"] > 0].nunique()),
                                 賣檔=("etf", lambda s: s[有價.loc[s.index, "adj_amount"] < 0].nunique()))
    群 = 群[群.index != "其他"]
    def 主角(產, 方向):
        t = 有價[有價["產業"] == 產].groupby("股名")["adj_amount"].sum()
        t = t[t > 0].nlargest(3) if 方向 > 0 else t[t < 0].nsmallest(3)
        return "、".join(f"**{n}**（{_億(v)}）" for n, v in t.items())
    流入 = 群[群["淨額"] > 0].nlargest(2, "淨額")
    流出 = 群[群["淨額"] < 0].nsmallest(2, "淨額")
    if len(流入) or len(流出):
        段 = []
        for 產, x in 流入.iterrows():
            段.append(f"**{產}** 族群獲 {int(x['買檔'])} 檔 ETF 買進、合計淨流入 **{_億(x['淨額'])}**，主要買 {主角(產, 1)}。")
        for 產, x in 流出.iterrows():
            段.append(f"**{產}** 族群遭 {int(x['賣檔'])} 檔 ETF 減碼、合計淨流出 **{_億(x['淨額'])}**，主要賣 {主角(產, -1)}。")
        標 = "資金流向：" + ("、".join(流入.index) + " 獲加碼" if len(流入) else "") + \
            ("；" if len(流入) and len(流出) else "") + ("、".join(流出.index) + " 遭提款" if len(流出) else "")
        段們.append({"標題": 標, "段落": 段, "色": "青"})

    彙 = 個股彙總(最新變化)
    彙["股名"] = [_名(c, 名稱, n) for c, n in zip(彙["code"], 彙["名稱"])]
    彙["產業"] = 彙["code"].map(lambda c: 產業.get(c) or "")

    # 2. 一致買進／一致賣出（至少 2 檔同方向、沒有人反向）
    def 共識(方向):
        檔, 反 = ("買進檔數", "賣出檔數") if 方向 > 0 else ("賣出檔數", "買進檔數")
        t = 彙[(彙[檔] >= 2) & (彙[反] == 0)].sort_values([檔, "金額"], ascending=[False, 方向 < 0]).head(5)
        if t.empty:
            return None
        清單 = "買進ETF" if 方向 > 0 else "賣出ETF"
        段 = [f"**{x['股名']}**{f'（{x.產業}）' if x['產業'] else ''}：{x[清單]} 共 {x[檔]} 檔同步{'買進' if 方向 > 0 else '賣出'}，"
             f"合計 {x['張數']:+,.0f} 張、**{_億(x['金額'])}**。" for _, x in t.iterrows()]
        首 = t.iloc[0]
        標 = (f"一致加碼：{首['股名']} 獲 {首[檔]} 檔 ETF 同步買進" if 方向 > 0
             else f"一致提款：{首['股名']} 遭 {首[檔]} 檔 ETF 同步賣出")
        return {"標題": 標, "段落": 段, "色": "紅" if 方向 > 0 else "綠"}
    for 方向 in (1, -1):
        結果 = 共識(方向)
        if 結果:
            段們.append(結果)

    # 3. 看法分歧（同一檔有人買有人賣）
    分 = 彙[(彙["買進檔數"] >= 1) & (彙["賣出檔數"] >= 1)].copy()
    if len(分):
        分["規模"] = 分["買金額"].abs() + 分["賣金額"].abs()
        分 = 分.sort_values(["規模"], ascending=False).head(3)
        段 = [f"**{x['股名']}**：{x['買進ETF']} 買進（{_億(x['買金額'])}），{x['賣出ETF']} 賣出（{_億(x['賣金額'])}），"
             f"淨額 {_億(x['金額'])}。" for _, x in 分.iterrows()]
        段.append("同一檔股票經理人看法相反，代表市場對它的評價正在分歧，股價波動可能放大。")
        段們.append({"標題": f"看法分歧：{分.iloc[0]['股名']} 出現同股不同向", "段落": 段, "色": "紫"})

    # 4. 單一基金大動作（新增／出清金額最大，或換手最多的那檔）
    大 = 有價[有價["type"].isin(["新增", "出清"])].copy()
    if len(大):
        大["絕對"] = 大["adj_amount"].abs()
        首 = 大.sort_values("絕對", ascending=False).iloc[0]
        e = 首["etf"]
        同 = 大[大["etf"] == e].sort_values("絕對", ascending=False)
        新增 = "、".join(f"**{n}**（{_億(v)}）" for n, v in zip(同[同["type"] == "新增"]["股名"], 同[同["type"] == "新增"]["adj_amount"]))
        出清 = "、".join(f"**{n}**（{_億(v)}）" for n, v in zip(同[同["type"] == "出清"]["股名"], 同[同["type"] == "出清"]["adj_amount"]))
        段 = []
        基金 = f"**{e} {ETF名.get(e, '')}**".replace(" **", "**")
        if 出清:
            段.append(f"{基金} 今天整筆出清 {出清}。")
        if 新增:
            段.append(("同時" if 出清 else f"{基金} 今天") + f"新建倉 {新增}。")
        段.append("整筆進出比漸進式加減碼更能看出經理人的信心，值得追蹤後續幾天是否延續。")
        段們.append({"標題": f"{e} {'出清' if 首['type'] == '出清' else '新建倉'} {首['股名']}，今天動作最大",
                    "段落": 段, "色": "黃"})

    # 5. 申購買回
    if 資訊 is not None and 最新日期:
        申 = 申贖金額(資訊, 最新日期)
        申 = {e: v for e, v in 申.items() if pd.notna(v) and abs(v) >= 5e7}
        if 申:
            多 = sorted(申.items(), key=lambda x: -x[1])
            進 = [f"**{e}**（{_億(v)}）" for e, v in 多 if v > 0][:3]
            出 = [f"**{e}**（{_億(v)}）" for e, v in 多[::-1] if v < 0][:3]
            段 = []
            if 進:
                段.append(f"申購淨流入：{'、'.join(進)}，經理人須依比例買進全部持股。")
            if 出:
                段.append(f"買回淨流出：{'、'.join(出)}，經理人須依比例賣出持股。")
            段.append("這部分是被動的等比例買賣，上面的分析都已扣除，不算經理人看好或看壞。")
            段們.append({"標題": f"申購買回：合計 {_億(sum(申.values()))}", "段落": 段, "色": "青"})
    return 段們


def 解讀純文字(段們):
    """規則解讀 → 純文字（給 AI 指令、複製用）。"""
    return "\n\n".join(f"【{s['標題']}】\n" + "\n".join(s["段落"]) for s in 段們).replace("**", "")


# ---------- AI 指令 ----------
AI說明 = """你是台灣股市的籌碼研究助理。以下是台灣主動式 ETF 今天的持股異動資料，所有張數與金額都已扣除申購買回造成的等比例增減，只代表經理人的主動加減碼。

請用繁體中文寫一份「今日法人視角」：
1. 寫 4～6 段，每段一個粗體小標題（一句話點出重點），再用 2～4 句說明。
2. 聚焦：哪些族群被一致加碼或提款、背後可能的產業邏輯、哪些股票出現同股不同向的分歧、哪一檔基金的動作最值得追蹤。
3. 提到股票時寫名稱，提到 ETF 時寫代號；金額用「億」。
4. 只根據提供的資料推論，不要編造新聞；推論的部分用「可能」「顯示」等字眼。
5. 最後一行寫：「以上為籌碼面解讀，僅供參考，不構成投資建議。」"""


def AI資料摘要(資料日, 最新變化, 產業, 名稱, ETF名, 小計, 資訊=None, 最新日期=None, 筆數=25):
    """把今天的異動整理成給 AI 看的文字。"""
    彙 = 個股彙總(最新變化)
    行們 = [f"資料日期：{pd.Timestamp(資料日):%Y-%m-%d}"]
    if len(彙):
        彙["股名"] = [_名(c, 名稱, n) for c, n in zip(彙["code"], 彙["名稱"])]
        彙["產業"] = 彙["code"].map(lambda c: 產業.get(c) or "—")
        def 列(t):
            return [f"- {x['code']} {x['股名']}（{x['產業']}）：{x['張數']:+,.0f} 張、{_億(x['金額'])}；"
                    f"買進 {x['買進檔數']} 檔 {x['買進ETF'] or '—'}；賣出 {x['賣出檔數']} 檔 {x['賣出ETF'] or '—'}"
                    for _, x in t.iterrows()]
        行們 += ["", "【買超金額前幾名】"] + 列(彙[彙["金額"] > 0].nlargest(筆數, "金額"))
        行們 += ["", "【賣超金額前幾名】"] + 列(彙[彙["金額"] < 0].nsmallest(筆數, "金額"))
        動 = 最新變化[最新變化["type"].isin(主動類型)].copy()
        動["產業"] = 動["code"].map(lambda c: 產業.get(c) or "其他")
        群 = 動.groupby("產業")["adj_amount"].sum().sort_values()
        行們 += ["", "【族群淨流入（扣申贖）】"] + [f"- {k}：{_億(v)}" for k, v in 群[群 != 0].items()]
        整 = 動[動["type"].isin(["新增", "出清"])]
        if len(整):
            行們 += ["", "【整筆新增／出清】"] + [
                f"- {x['etf']} {x['type']} {x['code']} {_名(x['code'], 名稱, x['name'])}（{_億(x['adj_amount'])}）"
                for _, x in 整.sort_values("adj_amount").iterrows()]
    if len(小計):
        行們 += ["", "【各 ETF 小計】"] + [
            f"- {x['etf']} {ETF名.get(x['etf'], '')}：淨額 {_億(x['淨額'])}，流入 {_億(x['流入'])}，流出 {_億(x['流出'])}，動 {x['動檔數']} 檔"
            for _, x in 小計.iterrows()]
    if 資訊 is not None and 最新日期:
        申 = {e: v for e, v in 申贖金額(資訊, 最新日期).items() if pd.notna(v) and abs(v) >= 1e7}
        if 申:
            行們 += ["", "【申購買回（被動，已從上面扣除）】"] + [f"- {e}：{_億(v)}" for e, v in sorted(申.items(), key=lambda x: -x[1])]
    return "\n".join(行們)


def AI指令(摘要):
    return f"{AI說明}\n\n以下是資料：\n\n{摘要}"


def AI解讀(摘要, 引擎, 金鑰, 模型):
    """呼叫 Gemini 或 Claude 寫解讀，回傳 Markdown。"""
    if 引擎 == "Gemini":
        import engine
        回應, _ = engine.Gemini呼叫({"systemInstruction": {"parts": [{"text": AI說明}]},
                                    "contents": [{"role": "user", "parts": [{"text": f"以下是資料：\n\n{摘要}"}]}]},
                                   金鑰, 模型)
        候選 = (回應.json().get("candidates") or [{}])[0]
        文字 = "".join(p.get("text", "") for p in (候選.get("content") or {}).get("parts", [])).strip()
    else:
        import anthropic
        回應 = anthropic.Anthropic(api_key=金鑰).messages.create(
            model=模型, max_tokens=8000, system=AI說明,
            messages=[{"role": "user", "content": f"以下是資料：\n\n{摘要}"}])
        if 回應.stop_reason == "refusal":
            raise RuntimeError("Claude 拒絕了這次請求，請改用複製指令。")
        文字 = "".join(b.text for b in 回應.content if b.type == "text").strip()
    if not 文字:
        raise RuntimeError("AI 沒有產生內容，請稍後再試。")
    return 文字


def AI分段(文字):
    """把 AI 的 Markdown 拆成 [{"標題", "段落", "色"}]：以粗體或 # 開頭的行當小標題。"""
    段們, 目前 = [], None
    色們 = ["青", "紅", "綠", "紫", "黃"]
    for 行 in str(文字).splitlines():
        行 = 行.strip()
        if not 行 or re.fullmatch(r"[-*_]{3,}", 行):
            continue
        標 = re.fullmatch(r"(?:#+\s*|\d+[.、]\s*)?\*\*(.+?)\*\*[:：]?\s*(.*)", 行) or re.fullmatch(r"#+\s*(.+)()", 行)
        if 標:
            目前 = {"標題": 標.group(1).strip(), "段落": [], "色": 色們[len(段們) % len(色們)]}
            段們.append(目前)
            if 標.group(2).strip():
                目前["段落"].append(標.group(2).strip())
        else:
            行 = re.sub(r"^\s*([-*•]|\d+[.、])\s*", "", 行)
            if 目前 is None:
                目前 = {"標題": "", "段落": [], "色": "青"}
                段們.append(目前)
            目前["段落"].append(行)
    return [s for s in 段們 if s["標題"] or s["段落"]]


# ---------- PDF 報告 ----------
def 族群圖(最新變化, 產業, 寬=9.2, 高=3.6, 筆數=8):
    """族群淨流入／流出長條圖（扣申贖，億）。"""
    import report
    動 = 最新變化[最新變化["type"].isin(主動類型)].copy()
    if 動.empty:
        return None
    動["產業"] = 動["code"].map(lambda c: 產業.get(c) or "其他")
    群 = 動.groupby("產業")["adj_amount"].sum() / 1e8
    群 = 群[群.index != "其他"]
    群 = pd.concat([群[群 > 0].nlargest(筆數), 群[群 < 0].nsmallest(筆數)]).sort_values()
    if 群.empty:
        return None
    plt = report._畫布()
    圖, 軸 = plt.subplots(figsize=(寬, 高))
    軸.barh(群.index, 群.values, color=[report.紅 if v > 0 else report.綠 for v in 群.values], height=0.6)
    for y, v in enumerate(群.values):
        軸.annotate(f"{v:+.2f}", (v, y), xytext=(4 if v > 0 else -4, 0), textcoords="offset points",
                   ha="left" if v > 0 else "right", va="center", fontsize=8, color=report.字色)
    軸.axvline(0, color=report.線色, linewidth=1)
    軸.set_xlabel("億元（扣除申贖）", fontsize=9)
    軸.grid(axis="y", visible=False)
    return report._存圖(plt, 圖)


def 產生PDF(資料):
    """資料：日期、卡片[(標題, 值, 小字, 方向)]、解讀[段]、AI解讀[段]、AI時間、共識買(DataFrame)、共識賣、小計、排名、異動、
    族群圖(BytesIO 或 None)、ETF名、名稱。回傳 PDF bytes。"""
    import report
    from fpdf import FPDF
    R = report
    ETF名, 名稱 = 資料.get("ETF名", {}), 資料.get("名稱", {})

    class 報告PDF(FPDF):
        def header(self):
            self.set_fill_color(*R._rgb(R.底色))
            self.rect(0, 0, self.w, self.h, style="F")

        def footer(self):
            self.set_y(-10)
            self.set_font("tc", size=7.5)
            self.set_text_color(*R._rgb(R.淡字))
            self.cell(0, 5, f"主動式 ETF 籌碼報告  //  {資料['日期']}  //  僅供個人研究，不構成投資建議  //  {self.page_no()}", align="R")

    pdf = 報告PDF(orientation="L", format="A4")
    pdf.add_font("tc", "", str(R.字型夾 / "NotoSansTC-Regular.ttf"))
    pdf.add_font("tc", "B", str(R.字型夾 / "NotoSansTC-Bold.ttf"))
    pdf.set_auto_page_break(True, margin=14)
    左, 頂 = 12, 12
    pdf.set_margins(左, 頂, 左)
    寬 = pdf.w - 2 * 左
    色表 = {"紅": R.紅, "綠": R.綠, "青": R.青, "黃": R.黃, "紫": "#B388FF"}

    def 字(大小, 粗=False, 色=R.字色):
        pdf.set_font("tc", "B" if 粗 else "", 大小)
        pdf.set_text_color(*R._rgb(色))

    def 段標(英文, 中文):
        字(8, 色=R.青)
        pdf.cell(0, 4, 英文.upper(), new_x="LMARGIN", new_y="NEXT")
        字(15, True)
        pdf.cell(0, 8, 中文, new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*R._rgb(R.紅))
        pdf.set_line_width(0.8)
        pdf.line(左, pdf.get_y() + 0.5, 左 + 14, pdf.get_y() + 0.5)
        pdf.ln(3)

    def 卡片(x, y, w, h, 標題, 值, 小字="", 色=R.字色):
        pdf.set_fill_color(*R._rgb(R.卡色))
        pdf.set_draw_color(*R._rgb(R.線色))
        pdf.set_line_width(0.2)
        pdf.rect(x, y, w, h, style="DF")
        pdf.set_fill_color(*R._rgb(色 if 色 != R.字色 else R.青))
        pdf.rect(x, y, 1.2, h, style="F")
        pdf.set_xy(x + 3.5, y + 2.5)
        字(8, 色=R.次字)
        pdf.cell(w - 5, 4, 標題)
        pdf.set_xy(x + 3.5, y + 7.5)
        字(15 if len(str(值)) <= 10 else 12, True, 色)
        pdf.cell(w - 5, 8, str(值))
        if 小字:
            pdf.set_xy(x + 3.5, y + h - 6.5)
            字(7.5, 色=R.次字)
            pdf.cell(w - 5, 4, R._乾淨(小字))

    def 解讀塊(段們, x, w):
        """左邊一條色線＋粗體標題＋條列。"""
        for s in 段們:
            if pdf.get_y() > pdf.h - 40:
                pdf.add_page()
            y0 = pdf.get_y()
            pdf.set_x(x + 4)
            if s.get("標題"):
                字(12, True, 色表.get(s.get("色"), R.字色))
                pdf.multi_cell(w - 4, 6.5, R._乾淨(s["標題"]), new_x="LEFT", new_y="NEXT", align="L")
                pdf.ln(1)
            for 條 in s["段落"]:
                pdf.set_x(x + 4)
                字(10, 色="#D5D5D5")
                pdf.multi_cell(w - 4, 5.6, R._乾淨(條), markdown=True, new_x="LEFT", new_y="NEXT", align="L")
                pdf.ln(0.8)
            y1 = pdf.get_y()
            if y1 > y0:
                pdf.set_fill_color(*R._rgb(色表.get(s.get("色"), R.青)))
                pdf.rect(x, y0, 1.2, y1 - y0, style="F")
            pdf.ln(3)

    def 表格(欄們, 列們, 寬們, x=None, 色們=None, 列高=6.2, 標題=None):
        """欄們：[(標題, 對齊)]；列們：[[文字…]]；色們：[[色或 None…]]。超過頁尾自動換頁並重印表頭。"""
        x = 左 if x is None else x
        def 表頭():
            pdf.set_x(x)
            pdf.set_fill_color(*R._rgb("#1F1F1F"))
            字(8.5, True, R.次字)
            for (名, 對), w in zip(欄們, 寬們):
                pdf.cell(w, 列高, 名, align=對, fill=True)
            pdf.ln(列高)
        if 標題:
            字(11, True)
            pdf.set_x(x)
            pdf.cell(sum(寬們), 7, 標題, new_x="LMARGIN", new_y="NEXT")
        表頭()
        for i, 列 in enumerate(列們):
            if pdf.get_y() + 列高 > pdf.h - 14:
                pdf.add_page()
                表頭()
            pdf.set_x(x)
            pdf.set_fill_color(*R._rgb(R.卡色 if i % 2 == 0 else R.底色))
            for j, ((名, 對), w) in enumerate(zip(欄們, 寬們)):
                色 = (色們[i][j] if 色們 else None) or R.字色
                字(8.5, 色=色)
                文字 = str(列[j])
                while pdf.get_string_width(文字) > w - 1.5 and len(文字) > 2:
                    文字 = 文字[:-2] + "…"
                pdf.cell(w, 列高, 文字, align=對, fill=True)
            pdf.ln(列高)

    def 方向色(v):
        return R._漲跌色(v) if v is not None and not pd.isna(v) else R.字色

    # ===== 第 1 頁：總覽＋今日解讀 =====
    pdf.add_page()
    字(9, 色=R.青)
    pdf.cell(0, 5, f"ACTIVE ETF REPORT  //  {資料['日期']}")
    pdf.set_xy(左, 頂 + 6)
    字(26, True)
    pdf.cell(0, 13, "主動式 ETF 每日籌碼報告", new_x="LMARGIN", new_y="NEXT")
    y = pdf.get_y() + 3
    卡們 = 資料.get("卡片", [])[:6]
    卡寬 = (寬 - (len(卡們) - 1) * 3) / max(len(卡們), 1)
    for i, (標題, 值, 小字, 方向) in enumerate(卡們):
        卡片(左 + i * (卡寬 + 3), y, 卡寬, 22, 標題, 值, 小字, 方向色(方向) if 方向 is not None else R.字色)
    pdf.set_y(y + 28)
    if 資料.get("族群圖") is not None:
        圖寬 = 寬 * 0.46
        y0 = pdf.get_y()
        字(8, 色=R.青)
        pdf.cell(圖寬, 4, "SECTOR FLOW  //  族群資金流向（扣除申贖）", new_x="LMARGIN", new_y="NEXT")
        pdf.image(資料["族群圖"], x=左, y=pdf.get_y() + 1, w=圖寬)
        pdf.set_xy(左 + 圖寬 + 6, y0)
        字(8, 色=R.青)
        pdf.cell(0, 4, "TODAY  //  今日解讀（規則自動產生）", new_x="LEFT", new_y="NEXT")
        pdf.ln(1)
        解讀塊(資料.get("解讀", []), 左 + 圖寬 + 6, 寬 - 圖寬 - 6)
    else:
        段標("Today", "今日解讀（規則自動產生）")
        解讀塊(資料.get("解讀", []), 左, 寬)

    if 資料.get("AI解讀"):
        pdf.add_page()
        段標("AI View", f"AI 解讀{('　' + 資料['AI時間']) if 資料.get('AI時間') else ''}")
        解讀塊(資料["AI解讀"], 左, 寬)

    # ===== 共識買賣 =====
    pdf.add_page()
    段標("Consensus", "經理人共識：一起買、一起賣的股票（扣除申贖）")
    半 = (寬 - 6) / 2
    y表 = pdf.get_y()
    for k, (鍵, 標, 清單欄) in enumerate([("共識買", "買超前 20", "買進ETF"), ("共識賣", "賣超前 20", "賣出ETF")]):
        t = 資料.get(鍵)
        x = 左 + k * (半 + 6)
        pdf.set_y(y表)
        if t is None or t.empty:
            continue
        列們 = [[f"{r['code']} {_名(r['code'], 名稱, r['名稱'])}", f"{r['買進檔數']}/{r['賣出檔數']}", f"{r['張數']:+,.0f}",
                 _億(r["金額"]).replace(" ", ""), r[清單欄]] for _, r in t.iterrows()]
        色們 = [[None, None, 方向色(r["張數"]), 方向色(r["金額"]), R.次字] for _, r in t.iterrows()]
        表格([("股票", "L"), ("買/賣檔", "C"), ("張數", "R"), ("金額", "R"), ("ETF", "L")], 列們,
             [半 * .27, 半 * .12, 半 * .14, 半 * .15, 半 * .32], x=x, 色們=色們, 標題=標)

    # ===== 分 ETF 小計 =====
    小計 = 資料.get("小計")
    if 小計 is not None and len(小計):
        pdf.add_page()
        段標("By Fund", "分 ETF 小計（扣除申贖）")
        列們, 色們 = [], []
        for _, r in 小計.iterrows():
            買 = f"{_名(r['最大買'][0], 名稱, r['最大買'][1])} {_億(r['最大買'][2])}" if r["最大買"] else "—"
            賣 = f"{_名(r['最大賣'][0], 名稱, r['最大賣'][1])} {_億(r['最大賣'][2])}" if r["最大賣"] else "—"
            列們.append([f"{r['etf']} {ETF名.get(r['etf'], '')}", _億(r["淨額"]), _億(r["流入"]), _億(r["流出"]),
                        f"{r['動檔數']}", f"{r['新增']}/{r['出清']}", 買, 賣])
            色們.append([None, 方向色(r["淨額"]), R.紅 if r["流入"] else None, R.綠 if r["流出"] else None, None, None, R.紅, R.綠])
        表格([("ETF", "L"), ("淨額", "R"), ("流入", "R"), ("流出", "R"), ("動檔數", "C"), ("新增/出清", "C"),
             ("最大買進", "L"), ("最大賣出", "L")], 列們,
             [寬 * .2, 寬 * .09, 寬 * .09, 寬 * .09, 寬 * .06, 寬 * .07, 寬 * .2, 寬 * .2], 色們=色們)

    # ===== 持股總排名 =====
    排 = 資料.get("排名")
    if 排 is not None and len(排):
        pdf.add_page()
        段標("Ranking", "主動式 ETF 合計持股排名前 50（依持有市值）")
        前 = 排.head(50)
        半 = (寬 - 6) / 2
        y表 = pdf.get_y()
        for k in range(2):
            t = 前.iloc[k * 25:(k + 1) * 25]
            if t.empty:
                continue
            pdf.set_y(y表)
            列們 = [[f"{int(r['排名'])}", f"{r['代號']} {_名(r['代號'], 名稱, r['名稱'])}",
                     f"{r['市值億']:,.2f}" if pd.notna(r["市值億"]) else "—", f"{r['張數']:,.0f}", f"{int(r['檔數'])}",
                     f"{r.get('今日增減', 0):+,.0f}"] for _, r in t.iterrows()]
            色們 = [[R.次字, None, None, None, None, 方向色(r.get("今日增減", 0))] for _, r in t.iterrows()]
            表格([("#", "C"), ("股票", "L"), ("市值(億)", "R"), ("張數", "R"), ("檔數", "C"), ("今日增減", "R")], 列們,
                 [半 * .08, 半 * .36, 半 * .16, 半 * .16, 半 * .1, 半 * .14], x=左 + k * (半 + 6), 色們=色們, 列高=5.6)

    # ===== 全部異動 =====
    異 = 資料.get("異動")
    if 異 is not None and len(異):
        pdf.add_page()
        段標("By Fund Detail", "基金視角：每檔 ETF 今天的異動")
        類色 = {"新增": R.紅, "加碼": "#FF8FA3", "減碼": "#7FE8C1", "出清": R.綠}
        列們, 色們 = [], []
        for _, r in 異.iterrows():
            列們.append([f"{r['etf']} {ETF名.get(r['etf'], '')}", f"{r['code']} {_名(r['code'], 名稱, r['name'])}", r["type"],
                        f"{r['adj_delta'] / 1000:+,.0f}", f"{r['shares'] / 1000:,.0f}",
                        f"{int(r['比重排名'])}" if pd.notna(r["比重排名"]) else "—",
                        _億(r["adj_amount"]) if pd.notna(r["adj_amount"]) else "—"])
            色們.append([R.次字, None, 類色.get(r["type"]), 方向色(r["adj_delta"]), None, None, 方向色(r["adj_amount"])])
        表格([("ETF", "L"), ("股票", "L"), ("動作", "C"), ("扣申贖(張)", "R"), ("持股(張)", "R"), ("比重排名", "C"),
             ("金額", "R")], 列們, [寬 * .24, 寬 * .22, 寬 * .08, 寬 * .12, 寬 * .12, 寬 * .1, 寬 * .12], 色們=色們, 列高=5.6)

    return bytes(pdf.output())
