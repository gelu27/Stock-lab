# 06 主動式 ETF：由 app.py 的 執行頁面() 在同一個命名空間執行，可直接用 app.py 的共用函式與資料。
@st.cache_data(max_entries=2, ttl=43200, show_spinner="整理主動式 ETF 分析中…")
def ETF分析(版本, 資料版本):
    """持股排名、分 ETF 小計、全部異動、規則版今日解讀、給 AI 的資料摘要（都只看各檔最新一份）。"""
    持股, 資訊, 變化 = ETF資料(版本)
    最新 = 持股.sort_values("date").groupby("etf").tail(1)
    最新日期 = dict(zip(最新["etf"], 最新["date"]))
    最新持股 = 持股[[最新日期.get(e) == d for e, d in zip(持股["etf"], 持股["date"])]]
    最新變化 = 變化[[最新日期.get(e) == d for e, d in zip(變化["etf"], 變化["date"])]] if len(變化) else 變化
    資料日 = max(最新日期.values())
    名稱 = dict(zip(今日["代號"], 今日["名稱"]))
    產業 = {c: v for c, v in zip(今日["代號"], 今日.get("產業", pd.Series(index=今日.index, dtype=object))) if isinstance(v, str) and v}
    股數 = {c: v for c, v in zip(今日["代號"], 今日.get("發行股數", pd.Series(index=今日.index, dtype=float))) if pd.notna(v) and v > 0}
    ETF名 = {e: 名稱.get(e, "") for e in 最新日期}
    規模 = {e: 資訊.loc[(資訊["etf"] == e) & (資訊["date"] == d), "aum"].iloc[-1] for e, d in 最新日期.items()
           if ((資訊["etf"] == e) & (資訊["date"] == d)).any()}
    小計 = etf_analysis.基金小計(最新變化, 規模)
    彙總 = etf_analysis.個股彙總(最新變化) if len(最新變化) else pd.DataFrame()
    較晚, 未追蹤 = etf_analysis.揭露狀態(最新日期, 資料日, etf_data.主動式清單())
    return {"小計": 小計, "彙總": 彙總, "產業": 產業, "ETF名": ETF名, "較晚": 較晚, "未追蹤": 未追蹤,
            "排名": etf_analysis.持股排名(最新持股, 最新變化, dict(zip(今日["代號"], 今日["收盤"])), 股數),
            "異動": etf_analysis.全部異動(最新變化, 最新持股),
            "解讀": etf_analysis.規則解讀(最新變化, 產業, 名稱, 資訊, 最新日期, ETF名),
            "摘要": etf_analysis.AI資料摘要(資料日, 最新變化, 產業, 名稱, ETF名, 小計, 資訊, 最新日期),
            "申贖": etf_analysis.申贖金額(資訊, 最新日期),
            "一致買": int(((彙總["買進檔數"] >= 2) & (彙總["賣出檔數"] == 0)).sum()) if len(彙總) else 0,
            "一致賣": int(((彙總["賣出檔數"] >= 2) & (彙總["買進檔數"] == 0)).sum()) if len(彙總) else 0}


_億 = etf_analysis._億


解讀色 = {"紅": 紅, "綠": 綠, "青": 青, "黃": "#FFC145", "紫": "#B388FF"}


def 解讀卡(段們):
    """今日解讀：左邊一條色線、粗體標題、內文的 **粗體** 變亮色。"""
    import html
    import re
    亮 = lambda 文: re.sub(r"\*\*(.+?)\*\*", r'<b style="color:#FFFFFF">\1</b>', html.escape(文))
    塊們 = []
    for s in 段們:
        色 = 解讀色.get(s.get("色"), 青)
        內 = "".join(f'<p style="margin:4px 0;line-height:1.7">{亮(p)}</p>' for p in s["段落"])
        標 = (f'<div style="font-weight:700;font-size:15px;color:{色};margin-bottom:6px">'
              f'{html.escape(s["標題"].replace("**", ""))}</div>') if s.get("標題") else ""
        塊們.append(f'<div style="border-left:3px solid {色};background:#0D0D0D;padding:12px 14px;margin:10px 0;'
                   f'color:#CFCFCF;font-size:14px">{標}{內}</div>')
    st.markdown("".join(塊們), unsafe_allow_html=True)


def 小計卡(小計, ETF名):
    """每檔 ETF 一張卡：淨額、流入流出、動了幾檔、最大買進與賣出（手機一欄、電腦三欄）。"""
    if 小計.empty:
        st.info("今天沒有異動資料。")
        return
    def 股(t):
        return f"{名稱.get(t[0]) or t[1]} {_億(t[2])}" if t else "—"
    名稱 = dict(zip(今日["代號"], 今日["名稱"]))
    卡們 = []
    for _, r in 小計.iterrows():
        色 = 漲跌色(r["淨額"])
        卡們.append(
            f'<div style="border:1px solid #1E1E1E;background:#070707;padding:10px 12px">'
            f'<div style="display:flex;justify-content:space-between;gap:8px"><span><b style="color:{青}">{r["etf"]}</b> '
            f'{ETF名.get(r["etf"], "")}</span><b style="color:{色};white-space:nowrap">淨 {_億(r["淨額"])}</b></div>'
            f'<div style="font-size:12px;color:#9A9A9A;margin-top:4px">流入 <span style="color:{紅}">{_億(r["流入"]) if r["流入"] else "—"}</span>　'
            f'流出 <span style="color:{綠}">{_億(r["流出"]) if r["流出"] else "—"}</span>　動 {r["動檔數"]} 檔'
            f'{f"　新增 {r.新增}" if r["新增"] else ""}{f"　出清 {r.出清}" if r["出清"] else ""}</div>'
            f'<div style="font-size:12px;color:#9A9A9A">最買 <span style="color:{紅}">{股(r["最大買"])}</span>　'
            f'最賣 <span style="color:{綠}">{股(r["最大賣"])}</span></div></div>')
    st.markdown(f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:8px">'
                f'{"".join(卡們)}</div>', unsafe_allow_html=True)


def 投信拆解區(變化):
    段落("TRUST // 投信買賣超拆解：主動式 ETF vs 其他投信")
    日, 表 = engine.投信拆解(指標, 變化)
    if 日 is None or 表.empty:
        st.info("要有同一天的法人資料和主動式 ETF 持股才能拆解，資料更新後就會出現。")
        return
    合 = 表[["投信金額", "主動ETF金額", "其他投信金額"]].sum()
    卡片格([卡片(f"投信合計 · {日:%m/%d}", f"{合['投信金額']:+,.1f} 億", "官方三大法人資料", 漲跌色(合["投信金額"])),
           卡片("其中 主動式 ETF", f"{合['主動ETF金額']:+,.1f} 億", "持股張數變化（含申贖）", 漲跌色(合["主動ETF金額"])),
           卡片("其他投信", f"{合['其他投信金額']:+,.1f} 億", "一般基金＋被動式 ETF（相減估算）", 漲跌色(合["其他投信金額"]))])
    看 = st.segmented_control("排行依據", ["投信合計", "主動式 ETF", "其他投信"], default="投信合計", key="投信拆解依據",
                            label_visibility="collapsed") or "投信合計"
    欄 = {"投信合計": "投信金額", "主動式 ETF": "主動ETF金額", "其他投信": "其他投信金額"}[看]
    表 = 表.assign(股票=表["代號"] + " " + 表["名稱"])
    顯示 = {"股票": "股票", "投信": "投信(張)", "主動ETF": "主動ETF(張)", "主動ETF扣申贖": "其中經理人主動(張)",
          "其他投信": "其他投信(張)", 欄: "金額(億)", "代號": "代號"}
    格式 = {"投信(張)": "{:+,.0f}", "主動ETF(張)": "{:+,.0f}", "其中經理人主動(張)": "{:+,.0f}", "其他投信(張)": "{:+,.0f}",
          "金額(億)": "{:+,.2f}"}
    左, 右 = st.columns(2)
    for 位, 名, 段 in ((左, "🔴 買超前 20", 表.nlargest(20, 欄)), (右, "🟢 賣超前 20", 表.nsmallest(20, 欄))):
        段 = 段[段[欄] > 0] if "買" in 名 else 段[段[欄] < 0]
        with 位:
            st.markdown(f"**{名}**（依{看}金額）")
            t = 段[list(顯示)].rename(columns=顯示)
            點選表(t, 上色(t).format(格式, na_rep="—").map(lambda v: f"color:{漲跌色(v)}", subset=list(格式)),
                   f"投信拆解{名}", height=35 * (len(t) + 1) + 3, column_config={"代號": None})
    st.caption("投信合計是交易所公布的投信買賣超；主動式 ETF 是各檔持股張數的變化加總（含申購買回，因為那也是投信的買賣）；"
               "其他投信＝合計減主動式 ETF，包含一般基金與 0050 等被動式 ETF（被動式持股沒有每日資料，只能相減估算）。"
               "「其中經理人主動」是扣掉申贖後的部分。投信合計和主動式 ETF 方向一致時，代表買盤主要來自主動式 ETF；"
               "其他投信很大時，常是被動式 ETF 申購或一般基金在買。金額＝張數 × 收盤估算。")


類型色 = {"新增": 紅, "加碼": "#FF8FA3", "減碼": "#7FE8C1", "出清": 綠, "持平": "#EDEDED"}


持股, 資訊, 變化 = ETF資料(ETF版本())
if 持股.empty:
    st.info("主動式 ETF 的持股資料還沒抓到。資料每個交易日晚上自動更新（GitHub Actions「主動式 ETF 持股」）。")
    st.stop()
名稱 = dict(zip(今日["代號"], 今日["名稱"]))
收盤 = dict(zip(今日["代號"], 今日["收盤"]))
最新 = 持股.sort_values("date").groupby("etf").tail(1)[["etf", "date"]].drop_duplicates()
最新日期 = dict(zip(最新["etf"], 最新["date"]))
最新持股 = 持股[持股.apply(lambda x: 最新日期.get(x["etf"]) == x["date"], axis=1)]
if len(變化):
    最新變化 = 變化[變化.apply(lambda x: 最新日期.get(x["etf"]) == x["date"], axis=1)]
else:
    最新變化 = 變化
資料日 = max(最新日期.values())

段落("ACTIVE ETF // 主動式 ETF 總覽")
列們 = []
for 代號, d in sorted(最新日期.items()):
    資 = 資訊[(資訊["etf"] == 代號)].sort_values("date")
    今資 = 資[資["date"] == d].tail(1)
    前資 = 資[資["date"] < d].tail(1)
    規模 = 今資["aum"].iloc[0] / 1e8 if len(今資) else np.nan
    前規模 = 前資["aum"].iloc[0] / 1e8 if len(前資) else np.nan
    單位變 = (今資["units"].iloc[0] / 前資["units"].iloc[0] - 1) * 100 if len(今資) and len(前資) else np.nan
    變 = 最新變化[最新變化["etf"] == 代號] if len(最新變化) else pd.DataFrame(columns=["type"])
    數 = 變["type"].value_counts()
    列們.append({"ETF": f"{代號} {名稱.get(代號, '')}".strip(), "投信": 今資["issuer"].iloc[0] if len(今資) else "",
                "規模(億)": 規模, "申贖%": 單位變, "持股檔數": int((持股[(持股["etf"] == 代號) & (持股["date"] == d)]).shape[0]),
                "新增": int(數.get("新增", 0)), "加碼": int(數.get("加碼", 0)), "減碼": int(數.get("減碼", 0)),
                "出清": int(數.get("出清", 0)), "資料日": f"{d:%m/%d}",
                "來源": 今資["source"].iloc[0] if len(今資) else ""})
總表 = pd.DataFrame(列們)
總表[["規模(億)", "申贖%"]] = 總表[["規模(億)", "申贖%"]].apply(pd.to_numeric, errors="coerce")
總表 = 總表.fillna({"投信": "—", "來源": "—"}).sort_values("規模(億)", ascending=False)
卡片格([卡片("追蹤檔數", f"{len(總表)} 檔", f"最新資料 {資料日:%Y/%m/%d}"),
       卡片("總規模", f"{總表['規模(億)'].sum():,.0f} 億"),
       卡片("今日有調整", f"{int((總表[['新增', '加碼', '減碼', '出清']].sum(axis=1) > 0).sum())} 檔",
            f"新增 {int(總表['新增'].sum())}・出清 {int(總表['出清'].sum())}")])
分析 = ETF分析(ETF版本(), _版本)
小計 = 分析["小計"]
淨額 = 小計["淨額"].sum() if len(小計) else 0
申贖 = sum(v for v in 分析["申贖"].values() if pd.notna(v))
卡片格([卡片("扣申贖淨買超", _億(淨額).replace(" ", ""), "經理人主動加減碼合計", 漲跌色(淨額)),
       卡片("申購買回", _億(申贖).replace(" ", ""), "被動等比例買賣（已扣除）", 漲跌色(申贖)),
       卡片("一致買進", f"{分析['一致買']} 檔", f"一致賣出 {分析['一致賣']} 檔")])
if 分析["較晚"] or 分析["未追蹤"]:
    st.caption(("**較晚揭露**（資料日比其他檔早，多為 T+1 公布）：" + "、".join(分析["較晚"]) + "　" if 分析["較晚"] else "")
               + ("**沒有每日持股資料**：" + "、".join(分析["未追蹤"]) + "（多為投資海外，或投信未公開每日持股）"
                  if 分析["未追蹤"] else ""))
ETF頁 = st.tabs(["📝 今日解讀", "🔥 個股視角", "🏦 基金視角", "🏆 持股排名", "🔍 單一 ETF", "🔎 個股反查"])

with ETF頁[0]:
    段落(f"TODAY // 今日解讀　{資料日:%Y/%m/%d}")
    解讀卡(分析["解讀"])
    st.caption("以上由規則自動整理（全部扣除申購買回後的主動調整），不是 AI 撰寫；想要更完整的解讀可以按下面的 AI 按鈕。")

    段落("AI // AI 解讀")
    try:
        設定 = dict(st.secrets)
    except Exception:
        設定 = {}
    if str(設定.get("GEMINI_API_KEY", "")).strip():
        引擎, 金鑰, 模型 = "Gemini", engine.清理金鑰(設定["GEMINI_API_KEY"]), str(設定.get("GEMINI_MODEL", "gemini-flash-latest"))
    else:
        引擎, 金鑰, 模型 = "Claude", engine.清理金鑰(設定.get("ANTHROPIC_API_KEY")), str(設定.get("AI_MODEL", "claude-opus-5-5"))
    可寫 = not (str(設定.get("password", "")) and not st.session_state.get("已解鎖"))
    try:
        紀錄們 = AI紀錄快取("ETF_ACTIVE", 設定.get("GITHUB_TOKEN", ""))
    except Exception:
        紀錄們 = []
    上次 = 紀錄們[0] if 紀錄們 else None
    今天 = f"{資料日:%Y-%m-%d}"
    a, b, c = st.columns(3)
    if a.button(f"✨ AI 解讀（{引擎}）" if 金鑰 else "✨ AI 解讀", key="ETF_AI", width="stretch", type="primary" if not 上次 or 上次.get("資料日期") != 今天 else "secondary",
                disabled=not (金鑰 and 可寫),
                help="請先在 01 市場總覽輸入庫存密碼解鎖" if not 可寫 else (None if 金鑰 else "Secrets 還沒設定 GEMINI_API_KEY")):
        用量 = AI用量()
        日 = pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m-%d")
        if 用量.get(日, 0) >= int(設定.get("AI_DAILY_LIMIT", 20)):
            st.warning("今天的 AI 次數已達上限，明天再試。")
        else:
            with st.spinner("AI 撰寫中，約 30 秒…"):
                try:
                    文字 = etf_analysis.AI解讀(分析["摘要"], 引擎, 金鑰, 模型)
                    用量[日] = 用量.get(日, 0) + 1
                    上次 = {"時間": pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m-%d %H:%M"), "資料日期": 今天,
                           "引擎": 引擎, "模型": 模型, "內容": 文字}
                    try:
                        engine.儲存AI紀錄("ETF_ACTIVE", 上次, 設定)
                    except Exception as 錯:
                        st.caption(f"解讀已產生，但存檔失敗：{錯}")
                    AI紀錄快取.clear()
                except Exception as 錯:
                    st.error(f"AI 解讀失敗：{錯}")
    if b.button("📋 複製 AI 指令", key="ETF指令", width="stretch"):
        st.session_state["ETF顯示指令"] = not st.session_state.get("ETF顯示指令", False)
    if c.button("📥 貼上 AI 結果", key="ETF貼上", width="stretch", disabled=not 可寫,
                help=None if 可寫 else "請先在 01 市場總覽輸入庫存密碼解鎖"):
        st.session_state["ETF顯示貼上"] = not st.session_state.get("ETF顯示貼上", False)
    if st.session_state.get("ETF顯示指令"):
        st.caption("按右上角的複製圖示，貼到 Gemini 或 Claude App，再把回答用「貼上 AI 結果」存回來。")
        st.code(etf_analysis.AI指令(分析["摘要"]), language=None, wrap_lines=True)
    if st.session_state.get("ETF顯示貼上") and 可寫:
        with st.form("ETF貼上表單", clear_on_submit=True):
            來源 = st.radio("結果來自", ["Gemini App", "Claude App", "其他"], horizontal=True)
            內容 = st.text_area("把 AI 的完整回答貼在這裡", height=220)
            if st.form_submit_button("💾 存成今天的 AI 解讀", type="primary"):
                if len(內容.strip()) < 50:
                    st.warning("內容太短，請貼上完整的回答。")
                else:
                    上次 = {"時間": pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m-%d %H:%M"), "資料日期": 今天,
                           "引擎": 來源, "模型": "手動貼上", "內容": 內容.strip()}
                    try:
                        永久 = engine.儲存AI紀錄("ETF_ACTIVE", 上次, 設定)
                        st.success("已存檔" + ("（GitHub 永久保存）" if 永久 else "（暫存在網站上）"))
                    except Exception as 錯:
                        st.error(f"存檔失敗：{錯}")
                    AI紀錄快取.clear()
                    st.session_state["ETF顯示貼上"] = False
    if 上次:
        舊 = 上次.get("資料日期") != 今天
        st.caption(f"{上次.get('引擎', '')} 解讀　{上次['時間']}　資料日 {上次.get('資料日期', '—')}"
                   + ("　⚠️ 這份是較早資料日的解讀，可以重新產生" if 舊 else ""))
        解讀卡(etf_analysis.AI分段(上次["內容"]))
    elif not 金鑰:
        st.caption("網站還沒設定 AI 金鑰，可以用「複製 AI 指令」貼到 Gemini 或 Claude App，再把結果貼回來。")

    段落("REPORT // 研究報告 PDF")
    鍵 = f"ETF_PDF_{今天}_{(上次 or {}).get('時間', '')}"
    if 鍵 not in st.session_state:
        if st.button("📄 產生研究報告 PDF", key="ETF_PDF按鈕"):
            with st.spinner("產生 PDF 中…"):
                try:
                    彙 = 分析["彙總"]
                    st.session_state[鍵] = etf_analysis.產生PDF({
                        "日期": 今天,
                        "卡片": [("追蹤檔數", f"{len(總表)} 檔", f"資料日 {資料日:%m/%d}", None),
                               ("總規模", f"{總表['規模(億)'].sum():,.0f} 億", "", None),
                               ("今日有調整", f"{int((總表[['新增', '加碼', '減碼', '出清']].sum(axis=1) > 0).sum())} 檔",
                                f"新增 {int(總表['新增'].sum())}・出清 {int(總表['出清'].sum())}", None),
                               ("扣申贖淨買超", _億(淨額), "經理人主動加減碼", 淨額),
                               ("申購買回", _億(申贖), "被動、已扣除", 申贖),
                               ("一致買進／賣出", f"{分析['一致買']} / {分析['一致賣']} 檔", "2 檔以上同方向", None)],
                        "解讀": 分析["解讀"], "AI解讀": etf_analysis.AI分段(上次["內容"]) if 上次 else None,
                        "AI時間": f"{上次.get('引擎', '')} {上次['時間']}（資料日 {上次.get('資料日期', '—')}）" if 上次 else "",
                        "共識買": 彙[彙["金額"] > 0].nlargest(20, "金額") if len(彙) else None,
                        "共識賣": 彙[彙["金額"] < 0].nsmallest(20, "金額") if len(彙) else None,
                        "小計": 小計, "排名": 分析["排名"], "異動": 分析["異動"],
                        "族群圖": etf_analysis.族群圖(最新變化, 分析["產業"]), "名稱": 名稱, "ETF名": 分析["ETF名"]})
                except Exception as 錯:
                    st.error(f"PDF 產生失敗：{錯}")
    if 鍵 in st.session_state:
        st.download_button("⬇️ 下載研究報告 PDF", st.session_state[鍵], file_name=f"主動式ETF籌碼報告_{今天}.pdf",
                           mime="application/pdf", key="ETF_PDF下載", type="primary")
    st.caption("PDF 內容：總覽卡片、族群資金流向圖、今日解讀（有 AI 解讀也會附上）、共識買賣超、分 ETF 小計、持股排名前 50、每檔 ETF 異動明細。")

with ETF頁[2]:
    段落("FUNDS // 各檔 ETF 總覽")
    表格(總表.style.format({"規模(億)": "{:,.0f}", "申贖%": "{:+.2f}"}, na_rep="—")
                 .map(lambda v: f"color:{漲跌色(v)}", subset=["申贖%"]),
                 hide_index=True, width="stretch", height=35 * (len(總表) + 1) + 3)
    st.caption("每檔都和自己的前一份持股比；申贖%＝在外流通單位數的變化（正＝有人申購、基金變大）。"
               "各投信公布時間不同（有的當晚、有的隔天早上），資料日可能差一天。")
    段落("FLOW // 分 ETF 小計（扣除申贖）")
    小計卡(小計, 分析["ETF名"])
    段落("DETAIL // 每檔 ETF 今天的異動")
    異 = 分析["異動"]
    if 異.empty:
        st.info("今天各檔都沒有主動調整。")
    else:
        有動 = [e for e in 小計["etf"] if e in set(異["etf"])]
        選基金 = st.selectbox("ETF", ["全部"] + [f"{e} {分析['ETF名'].get(e, '')}" for e in 有動], key="ETF基金視角")
        t = 異 if 選基金 == "全部" else 異[異["etf"] == 選基金.split()[0]]
        表 = pd.DataFrame({"ETF": t["etf"] + " " + t["etf"].map(分析["ETF名"]).fillna(""), "代號": t["code"],
                          "股票": t["code"] + " " + t["code"].map(名稱).fillna(t["name"]), "動作": t["type"],
                          "扣申贖(張)": 張(t["adj_delta"]), "持股(張)": 張(t["shares"]), "比重排名": t["比重排名"],
                          "金額(萬)": t["adj_amount"] / 1e4})
        點選表(表, 上色(表).format({"扣申贖(張)": "{:+,.0f}", "持股(張)": "{:,.0f}", "比重排名": "{:.0f}", "金額(萬)": "{:+,.0f}"},
                                na_rep="—").map(lambda v: f"color:{類型色.get(v, '#EDEDED')}", subset=["動作"])
               .map(lambda v: f"color:{漲跌色(v)}", subset=["扣申贖(張)", "金額(萬)"]),
               "ETF基金異動表", height=min(35 * (len(表) + 1) + 3, 700), column_config={"代號": None})
        st.caption("比重排名＝這檔股票在該 ETF 裡的權重名次（出清的沒有名次）。點一下股票可到個股查詢。")

with ETF頁[3]:
    段落("RANKING // 主動式 ETF 合計持股排名")
    排 = 分析["排名"]
    門檻 = st.segmented_control("持有檔數", ["全部", "5 檔以上", "10 檔以上"], default="全部", key="ETF排名門檻") or "全部"
    t = 排 if 門檻 == "全部" else 排[排["檔數"] >= int(門檻.split()[0])]
    表 = pd.DataFrame({"排名": t["排名"], "代號": t["代號"], "股票": t["代號"] + " " + t["代號"].map(名稱).fillna(t["名稱"]),
                      "市值(億)": t["市值億"], "張數": t["張數"], "持有檔數": t["檔數"], "占股本%": t.get("占股本%"),
                      "今日增減(張)": t.get("今日增減"), "最高權重%": t["最高權重"], "持有的 ETF": t["持有ETF"]})
    點選表(表, 上色(表).format({"市值(億)": "{:,.2f}", "張數": "{:,.0f}", "占股本%": "{:.2f}", "今日增減(張)": "{:+,.0f}",
                             "最高權重%": "{:.2f}"}, na_rep="—").map(lambda v: f"color:{漲跌色(v)}", subset=["今日增減(張)"]),
           "ETF持股排名", height=700, column_config={"代號": None})
    st.caption(f"共 {len(排)} 檔股票被主動式 ETF 持有。市值＝合計張數×最新收盤；占股本％＝合計持股占發行股數的比例；"
               "今日增減已扣除申購買回。海外股票沒有台股價格，排在最後。")

with ETF頁[1]:
    段落("CONSENSUS // 經理人共識：大家一起買、一起賣的股票")
    區間 = st.segmented_control("期間", ["最新一天", "近 5 天", "近 20 天"], default="最新一天", key="ETF共識期間",
                              label_visibility="collapsed") or "最新一天"
    if len(變化):
        if 區間 == "最新一天":
            範圍 = 最新變化
        else:
            天 = 5 if 區間 == "近 5 天" else 20
            日們 = sorted(變化["date"].unique())[-天:]
            範圍 = 變化[變化["date"].isin(日們)]
        主動 = 範圍[範圍["type"] != "持平"]
        if 主動.empty:
            st.info("這段期間沒有主動調整的紀錄。")
        else:
            彙 = 主動.groupby("code").agg(
                買進檔數=("etf", lambda s: s[主動.loc[s.index, "adj_delta"] > 0].nunique()),
                賣出檔數=("etf", lambda s: s[主動.loc[s.index, "adj_delta"] < 0].nunique()),
                張數=("adj_delta", lambda v: v.sum() / 1000), 金額=("adj_amount", lambda v: v.sum() / 1e8),
                名稱=("name", "first"),
                買進ETF=("etf", lambda s: "、".join(sorted(set(s[主動.loc[s.index, "adj_delta"] > 0])))),
                賣出ETF=("etf", lambda s: "、".join(sorted(set(s[主動.loc[s.index, "adj_delta"] < 0]))))).reset_index()
            彙["代號"] = 彙["code"]
            彙["股票"] = 彙["code"] + " " + 彙["code"].map(名稱).fillna(彙["名稱"])
            彙["現價"] = 彙["code"].map(收盤)
            欄 = ["股票", "買進檔數", "賣出檔數", "張數", "金額", "現價", "代號"]
            左, 右 = st.columns(2)
            with 左:
                st.markdown(f"**🔴 買超（扣除申贖）**")
                買 = 彙[彙["張數"] > 0].sort_values(["金額", "買進檔數"], ascending=False).head(20)
                點選表(買[欄 + ["買進ETF"]].rename(columns={"金額": "金額(億)", "買進ETF": "買進的 ETF"}),
                       上色(買[欄 + ["買進ETF"]].rename(columns={"金額": "金額(億)", "買進ETF": "買進的 ETF"}))
                       .format({"張數": "{:+,.0f}", "金額(億)": "{:+,.2f}", "現價": "{:,.2f}"}, na_rep="—"),
                       "ETF共識買", height=35 * (len(買) + 1) + 3, column_config={"代號": None})
            with 右:
                st.markdown(f"**🟢 賣超（扣除申贖）**")
                賣 = 彙[彙["張數"] < 0].sort_values(["金額", "賣出檔數"], ascending=[True, False]).head(20)
                點選表(賣[欄 + ["賣出ETF"]].rename(columns={"金額": "金額(億)", "賣出ETF": "賣出的 ETF"}),
                       上色(賣[欄 + ["賣出ETF"]].rename(columns={"金額": "金額(億)", "賣出ETF": "賣出的 ETF"}))
                       .format({"張數": "{:+,.0f}", "金額(億)": "{:+,.2f}", "現價": "{:,.2f}"}, na_rep="—"),
                       "ETF共識賣", height=35 * (len(賣) + 1) + 3, column_config={"代號": None})
            st.caption("扣除申贖：基金被申購時經理人要等比例買進全部持股，那不代表看好，所以先扣掉，只看「多買、少買」的部分。"
                       "金額＝張數×當天收盤，海外股票沒有台股價格不算金額。點一下股票可到個股查詢。")

    投信拆解區(變化)

with ETF頁[4]:
    段落("HOLDINGS // 單一 ETF 持股明細")
    選項 = [f"{c} {名稱.get(c, '')}".strip() for c in 總表["ETF"].str.split().str[0]]
    選 = st.selectbox("選擇 ETF", 選項, key="ETF明細").split()[0]
    d = 最新日期[選]
    資 = 資訊[資訊["etf"] == 選].sort_values("date")
    今 = 持股[(持股["etf"] == 選) & (持股["date"] == d)].copy()
    變 = 變化[(變化["etf"] == 選)] if len(變化) else pd.DataFrame()
    今變 = 變[變["date"] == d].set_index("code") if len(變) else pd.DataFrame()
    今資 = 資[資["date"] == d].tail(1)
    卡片格([卡片("規模", f"{今資['aum'].iloc[0] / 1e8:,.0f} 億" if len(今資) and pd.notna(今資['aum'].iloc[0]) else "—",
                f"資料日 {d:%Y/%m/%d}"),
           卡片("淨值 / 市價", f"{今資['nav'].iloc[0]:,.2f}" if len(今資) and pd.notna(今資['nav'].iloc[0]) else "—",
                f"收盤 {收盤.get(選, np.nan):,.2f}" if pd.notna(收盤.get(選, np.nan)) else ""),
           卡片("持股", f"{len(今)} 檔", f"前十大占 {今['weight'].nlargest(10).sum():.1f}%")])
    分頁 = st.tabs(["持股明細", "異動紀錄", "權重走勢", "規模走勢"])
    with 分頁[0]:
        明細 = pd.DataFrame({"代號": 今["code"], "股票": 今["code"] + " " + 今["code"].map(名稱).fillna(今["name"]),
                            "權重%": 今["weight"], "張數": 張(今["shares"])})
        if len(今變):
            明細["張數變化"] = 張(今["code"].map(今變["delta"]))
            明細["扣申贖"] = 張(今["code"].map(今變["adj_delta"]))
            明細["權重變化"] = 今["code"].map(今變["weight"] - 今變["prev_weight"])
            明細["動作"] = 今["code"].map(今變["type"]).replace("持平", "")
        明細["現價"] = 今["code"].map(收盤)
        明細 = 明細.sort_values("權重%", ascending=False)
        出清 = 今變[今變["type"] == "出清"] if len(今變) else pd.DataFrame()
        樣式 = 上色(明細).format({"權重%": "{:.2f}", "張數": "{:,.0f}", "張數變化": "{:+,.0f}", "扣申贖": "{:+,.0f}",
                                "權重變化": "{:+.2f}", "現價": "{:,.2f}"}, na_rep="—")
        if "動作" in 明細:
            樣式 = 樣式.map(lambda v: f"color:{類型色.get(v, '#EDEDED')}", subset=["動作"]).map(
                lambda v: f"color:{漲跌色(v)}", subset=["張數變化", "扣申贖", "權重變化"])
        點選表(明細, 樣式, "ETF明細表", height=min(35 * (len(明細) + 1) + 3, 700), column_config={"代號": None})
        if len(出清):
            st.markdown("**今天出清：** " + "、".join(f"{c} {名稱.get(c, n)}（{張(s):,.0f} 張）"
                                                for c, n, s in zip(出清.index, 出清["name"], 出清["prev_shares"])))
        if len(今變):
            st.caption(f"和前一份（{今變['prev_date'].iloc[0]:%m/%d}）比較。扣申贖＝扣掉基金申購買回造成的等比例增減，"
                       "才是經理人主動加減碼；變化不到 0.5% 視為沒有調整。")
    with 分頁[1]:
        if 變.empty:
            st.info("要有兩天以上的資料才能比較，明天起就會出現。")
        else:
            紀 = 變[變["type"] != "持平"].sort_values(["date", "adj_amount"], ascending=[False, False])
            紀 = pd.DataFrame({"日期": 紀["date"].dt.strftime("%m/%d"), "代號": 紀["code"],
                              "股票": 紀["code"] + " " + 紀["code"].map(名稱).fillna(紀["name"]), "動作": 紀["type"],
                              "張數變化": 張(紀["delta"]), "扣申贖": 張(紀["adj_delta"]),
                              "金額(萬)": 紀["adj_amount"] / 1e4, "權重%": 紀["weight"]})
            點選表(紀, 上色(紀).format({"張數變化": "{:+,.0f}", "扣申贖": "{:+,.0f}", "金額(萬)": "{:+,.0f}", "權重%": "{:.2f}"},
                                    na_rep="—").map(lambda v: f"color:{類型色.get(v, '#EDEDED')}", subset=["動作"])
                   .map(lambda v: f"color:{漲跌色(v)}", subset=["張數變化", "扣申贖", "金額(萬)"]),
                   "ETF異動表", height=min(35 * (len(紀) + 1) + 3, 600), column_config={"代號": None})
            st.caption(f"近 {變['date'].nunique()} 個資料日的新增、加碼、減碼、出清（扣除申贖後）。")
    with 分頁[2]:
        史 = 持股[持股["etf"] == 選]
        前十 = 今.nlargest(10, "weight")["code"].tolist()
        圖 = go.Figure()
        for c in 前十:
            t = 史[史["code"] == c].sort_values("date")
            圖.add_trace(go.Scatter(x=t["date"], y=t["weight"], mode="lines+markers", name=f"{c} {名稱.get(c, '')}"))
        圖.update_yaxes(title="權重%")
        st.plotly_chart(圖表外觀(圖, 360), width="stretch")
        st.caption("目前前十大持股的權重變化。")
    with 分頁[3]:
        if len(資) >= 2:
            圖 = make_subplots(specs=[[{"secondary_y": True}]])
            圖.add_trace(go.Bar(x=資["date"], y=資["aum"] / 1e8, name="規模(億)", marker_color=青, opacity=.5))
            圖.add_trace(go.Scatter(x=資["date"], y=資["nav"], name="淨值", line=dict(color="#FFC24B", width=2)), secondary_y=True)
            st.plotly_chart(圖表外觀(圖, 320), width="stretch")
        else:
            st.info("資料累積兩天以上後會出現規模走勢。")

with ETF頁[5]:
    段落("STOCK // 個股被哪些主動式 ETF 持有")
    全部 = 最新持股.groupby("code").agg(檔數=("etf", "nunique"), 張數=("shares", lambda v: v.sum() / 1000),
                                     名稱=("name", "first")).reset_index().sort_values("檔數", ascending=False)
    股選項 = (全部["code"] + " " + 全部["code"].map(名稱).fillna(全部["名稱"])).tolist()
    預設 = next((i for i, v in enumerate(股選項) if v.startswith("2330 ")), 0)
    股 = st.selectbox("選擇股票（依被持有檔數排序）", 股選項, index=預設, key="ETF反查").split()[0]
    有 = 最新持股[最新持股["code"] == 股]
    股變 = 最新變化[最新變化["code"] == 股].set_index("etf") if len(最新變化) else pd.DataFrame()
    反 = pd.DataFrame({"ETF": 有["etf"] + " " + 有["etf"].map(名稱).fillna(""), "權重%": 有["weight"].values,
                      "張數": 張(有["shares"]).values}, index=有["etf"].values)
    if len(股變):
        反["扣申贖"] = 張(股變["adj_delta"].reindex(反.index))
        反["動作"] = 股變["type"].reindex(反.index).replace("持平", "")
        出 = 股變[股變["type"] == "出清"]
        for e in 出.index:
            反.loc[e] = {"ETF": f"{e} {名稱.get(e, '')}", "權重%": 0, "張數": 0, "扣申贖": 張(-出.loc[e, "prev_shares"]), "動作": "出清"}
    反 = 反.sort_values("權重%", ascending=False)
    現 = 收盤.get(股, np.nan)
    卡片格([卡片("持有的主動式 ETF", f"{(反['張數'] > 0).sum()} 檔"), 卡片("合計持有", f"{反['張數'].sum():,.0f} 張",
                f"約 {反['張數'].sum() * 1000 * 現 / 1e8:,.1f} 億" if pd.notna(現) else ""),
           卡片("最新一天", f"{反['扣申贖'].sum():+,.0f} 張" if "扣申贖" in 反 else "—", "扣除申贖後合計",
                漲跌色(反["扣申贖"].sum()) if "扣申贖" in 反 else "#EDEDED")])
    樣式 = 上色(反).format({"權重%": "{:.2f}", "張數": "{:,.0f}", "扣申贖": "{:+,.0f}"}, na_rep="—")
    if "動作" in 反:
        樣式 = 樣式.map(lambda v: f"color:{類型色.get(v, '#EDEDED')}", subset=["動作"]).map(
            lambda v: f"color:{漲跌色(v)}", subset=["扣申贖"])
    表格(樣式, hide_index=True, width="stretch", height=35 * (len(反) + 1) + 3)
    史 = 持股[持股["code"] == 股].groupby("date")["shares"].sum() / 1000
    if len(史) >= 2:
        圖 = go.Figure(go.Scatter(x=史.index, y=史.values, mode="lines+markers", line=dict(color=青, width=2), name="合計張數"))
        st.plotly_chart(圖表外觀(圖, 260), width="stretch")
        st.caption("所有主動式 ETF 合計持有張數（含申購買回造成的增減）。")
    if st.button(f"到個股查詢看 {股}", key="ETF到個股"):
        前往(股)
        st.rerun()
st.caption("資料來源：優先用各投信官網每日公布的持股（野村、統一、群益、復華、中信、第一金、富邦、凱基、摩根、台新、永豐、聯博、安聯）；"
           "官網抓不到時改用公開彙整 nctuwanglin.github.io/active-etf，再不行用 github.com/janeytu/tw-etf-pages 的快照"
           "（國泰、兆豐官網擋 GitHub，只能靠彙整）。總覽表的「來源」欄可看每檔用的是哪一個。僅供研究參考，不構成投資建議。")
