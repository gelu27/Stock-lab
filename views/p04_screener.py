# 04 選股：由 app.py 的 執行頁面() 在同一個命名空間執行，可直接用 app.py 的共用函式與資料。
def _AI引擎():
    設定 = _設定()
    if str(設定.get("GEMINI_API_KEY", "")).strip():
        return "Gemini", engine.清理金鑰(設定["GEMINI_API_KEY"]), str(設定.get("GEMINI_MODEL", "gemini-flash-latest"))
    return "Claude", engine.清理金鑰(設定.get("ANTHROPIC_API_KEY")), str(設定.get("AI_MODEL", "claude-opus-5-5"))


def 券商報告上傳區():
    if not 可編輯():
        st.caption("上傳報告會用到 AI 額度，請先在 01 市場總覽的庫存區輸入密碼解鎖。")
        return
    引擎, 金鑰, 模型 = _AI引擎()
    if not 金鑰:
        st.caption("要讀報告需要在 Secrets 設定 GEMINI_API_KEY。")
        return
    檔們 = st.file_uploader("上傳券商報告 PDF，或「每日研究報告」這類目標價截圖（可一次多個）",
                           type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True, key="券商上傳")
    if 檔們 and st.button(f"🤖 讀取 {len(檔們)} 個檔案", key="讀券商", type="primary"):
        新們, 錯們 = [], []
        進度 = st.progress(0.0, "AI 讀報告中…")
        for i, f in enumerate(檔們):
            try:
                新們 += engine.AI讀券商報告(f.getvalue(), f.name, 引擎, 金鑰, 模型)
            except Exception as e:
                錯們.append(f"{f.name}：{e}")
            進度.progress((i + 1) / len(檔們), f"已讀 {i + 1}/{len(檔們)}")
        st.session_state["券商預覽"] = 新們
        for e in 錯們:
            st.warning(e)
    預覽 = st.session_state.get("券商預覽")
    if 預覽:
        st.markdown(f"**讀到 {len(預覽)} 筆**，確認數字沒問題再存檔：")
        表格(engine.券商報告表(預覽).drop(columns=["前次目標價"]), hide_index=True, width="stretch")
        a, b = st.columns(2)
        if a.button("💾 存檔", key="存券商", type="primary"):
            舊 = engine.讀取券商報告(_設定())
            全 = engine.合併券商報告(舊, 預覽)
            永久 = engine.儲存券商報告(_設定(), 全)
            st.session_state.pop("券商預覽", None)
            st.session_state["_券商版本"] = st.session_state.get("_券商版本", 0) + 1
            st.success(f"已存 {len(預覽)} 筆" + ("（GitHub 永久保存）" if 永久 else "（暫存在網站上）"))
        if b.button("✖ 不要存", key="棄券商"):
            st.session_state.pop("券商預覽", None)
            st.rerun()
    st.caption("網站只保存評等、目標價、EPS 等數字和 AI 用自己的話寫的摘要，不保存報告原文（報告有版權）。")


def 券商報告總覽():
    報告們 = 券商報告清單(st.session_state.get("_券商版本", 0))
    段落("BROKER // 券商報告收件匣")
    with st.expander("📥 上傳新報告", expanded=not 報告們):
        券商報告上傳區()
    if not 報告們:
        st.caption("還沒有報告。上傳後這裡會整理目標價與 EPS 的上修／下修、到期驗收和各券商命中率。")
        return
    表 = engine.券商報告表(報告們)
    上 = engine.上修名單(報告們)
    卡片格([卡片("報告筆數", f"{len(表)}", f"{表['代號'].nunique()} 檔、{表['券商'].nunique()} 家券商"),
           卡片("近 30 天上修", f"{len(上)}", "檔（EPS 或目標價）", 紅),
           卡片("看多比例", f"{(表['看法'] == '看多').mean() * 100:.0f}%", "券商報告多半偏多，要打折看", 灰)])
    段落("REVISION // 近 30 天被上修的股票")
    if 上:
        今上 = 今日[今日["代號"].isin(上)][["代號", "名稱", "收盤", "漲跌幅", "20日漲幅", "本益比"]]
        if len(今上):
            點選表(今上, 上色(今上), "上修表")
        st.caption("EPS 被上修通常比評等本身更有資訊（券商幾乎都給買進），可以搭配下面的驗收與自己的選股條件一起看。")
    else:
        st.caption("近 30 天沒有上修紀錄。")
    集 = engine.集體升降評(報告們)
    if 集:
        段落("CONSENSUS SHIFT // 近 3 天集體調整目標價（3 家以上同方向）")
        表格(pd.DataFrame(集, columns=["代號", "名稱", "方向", "家數", "券商"]), hide_index=True, width="stretch")
        st.caption("很多家券商同時改目標價，比任何單一份報告更能代表法人共識在轉向。")
    段落("HEAT // 近 7 天被寫最多的股票")
    熱 = engine.覆蓋熱度(報告們).head(20)
    if len(熱):
        表格(熱, hide_index=True, width="stretch", column_config={"目標價中位數": st.column_config.NumberColumn(format="%.1f")})
    拆 = engine.目標價拆解(報告們)
    if len(拆):
        with st.expander(f"🔍 目標價變動拆解（{len(拆)} 份，其中 {拆['倍數變動%'].notna().sum()} 份拆得出倍數）"):
            表格(拆, hide_index=True, width="stretch", column_config={"日期": st.column_config.DateColumn(format="YYYY-MM-DD")})
            st.caption("目標價＝倍數 × EPS。主要是倍數變的上修，代表券商在追估值，不是獲利變好。")
    段落("LIST // 全部報告")
    表 = engine.加潛在空間(表, dict(zip(今日["代號"].astype(str), 今日["收盤"])))
    表格(表.drop(columns=["報告收盤價"]), hide_index=True, width="stretch",
                 column_config={"日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
                                "潛在空間%": st.column_config.NumberColumn(format="%+.1f%%")})
    st.caption("潛在空間＝目標價 ÷ 今天收盤 − 1，每天跟著收盤價更新；負數代表股價已經超過目標價。")
    段落("SCORE // 券商目標價驗收")
    價們 = {c: 個股價格(c) for c in 表["代號"].unique() if str(c).isdigit()}
    命 = engine.券商命中率(報告們, {k: v for k, v in 價們.items() if v is not None})
    if 命.empty:
        st.caption("還沒有可以驗收的報告。")
    else:
        表格(命, width="stretch")
        st.caption("達標率＝已達標 ÷（已達標＋到期未達標）；看多後平均＝這家給看多之後的平均報酬。"
                   "達標＝報告後 6 個月內股價碰到目標價；平均報酬＝報告日收盤到現在（最多 6 個月）。"
                   "多數報告定義「買進」是 6 個月報酬 15～30%，時間還不到 6 個月的算進行中。")


網紅指令 = ("請用繁體中文完整整理這支影片，不要只寫摘要，也不要加入你自己的看法：（貼上影片連結）\n"
          "格式：一、頻道、日期、長度。二、逐段內容（時間點、講什麼、理由），保留所有數字。"
          "三、提到的股票（每檔一行：代號 名稱：看多或看空。理由：…，有價位要寫）。四、所有「如果…就…」的判斷條件（有提到股票名稱、均線天數或價位的要原樣寫出來，例如「台積電站回 20 週均線就買回」）。"
          "五、引用的資料來源。六、畫面上的圖表與字卡。七、影片本身前後矛盾或沒說清楚的地方"
          "（不要用你自己的知識判斷股價、EPS 等數字對不對，你的資料可能不是最新的）。")


def 網紅說法上傳區():
    if not 可編輯():
        st.caption("新增影片要先在 01 市場總覽的庫存區輸入密碼解鎖。")
        return
    with st.popover("📋 給 Gemini 的整理指令（複製用）"):
        st.code(網紅指令, language=None, wrap_lines=True)
    文 = st.text_area("把 Gemini 整理好的文字整段貼上（一次可以貼好幾支）", height=180, key="網紅貼上")
    if 文 and st.button("🔍 解析", key="網紅解析", type="primary"):
        名表 = dict(zip(今日["名稱"], 今日["代號"]))
        片們 = [v for v in (engine.解析影片整理(p, 名表) for p in engine.拆開多支影片(文)) if v]
        st.session_state["網紅預覽"] = 片們
        if not 片們:
            st.warning("看不出格式，請確認有「三、提到的股票」這一段。")
    預覽 = st.session_state.get("網紅預覽")
    if 預覽:
        for v in 預覽:
            st.markdown(f"**{v['頻道']}**（{v['日期'] or '沒有日期'}）：{len(v['股票'])} 檔、{v['條件數']} 個條件"
                        + (f"，🚩 {len(v['紅旗'])}" if v["紅旗"] else ""))
            表格(pd.DataFrame(v["股票"])[["代號", "名稱", "看法", "理由"]], hide_index=True, width="stretch")
        a, b = st.columns(2)
        if a.button("💾 存檔", key="存網紅", type="primary"):
            全 = engine.合併網紅說法(engine.讀取網紅說法(_設定()), 預覽)
            永久 = engine.儲存網紅說法(_設定(), 全)
            st.session_state.pop("網紅預覽", None)
            st.session_state["_網紅版本"] = st.session_state.get("_網紅版本", 0) + 1
            st.success(f"已存 {len(預覽)} 支" + ("（GitHub 永久保存）" if 永久 else "（暫存在網站上）"))
        if b.button("✖ 不要存", key="棄網紅"):
            st.session_state.pop("網紅預覽", None)
            st.rerun()
    st.caption("不用 AI 額度：網站直接讀「三、提到的股票」和「四、如果…就…」兩段。只保存股票、看法和一句理由。")


def 網紅說法總覽():
    影片們 = 網紅說法清單(st.session_state.get("_網紅版本", 0))
    段落("INFLUENCER // 網紅說法收件匣")
    with st.expander("📥 新增影片", expanded=not 影片們):
        網紅說法上傳區()
    if not 影片們:
        st.caption("還沒有影片。存進來後，這裡會整理每位分析師的看法、紅旗，並在 20 個交易日後對答案。")
        return
    排除 = [v for v in 影片們 if engine.是AI工具影片(v)]
    影片們 = [v for v in 影片們 if not engine.是AI工具影片(v)]
    if 排除:
        st.caption(f"已排除 {len(排除)} 支在講 AI 工具用法的影片（不是在講股票）：" + "、".join(str(v.get("標題") or v["頻道"])[:20] for v in 排除[:5]))
    代們 = {str(x["代號"]) for v in 影片們 for x in v.get("股票", []) if str(x.get("代號", "")).isdigit()}
    價們 = {c: 個股價格(c) for c in 代們}
    網紅熱度區(影片們)
    網紅條件區(影片們, 價們)
    漲跌停查核區(影片們)
    網紅價位區(影片們)
    明細, 彙 = engine.網紅對答案(影片們, {k: v for k, v in 價們.items() if v is not None}, 指數K線("TAIEX", _版本))
    段落("SCORE // 誰說得準（20 個交易日後，扣掉大盤漲跌）")
    if 彙.empty:
        st.caption("還沒有可以對答案的資料。")
    else:
        表格(彙, width="stretch", column_config={"平均超額%": st.column_config.NumberColumn(format="%+.1f")})
        st.caption("超額報酬＝個股報酬減同期加權報酬。看多且贏大盤、看空且輸大盤算說對；不到 20 天的算「暫時」，不計入命中率。"
                   "中立的不算。樣本少的時候命中率只是參考。")
    混 = engine.摘要混稿偵測(影片們)
    if 混:
        段落("DUPLICATE // 摘要可能重複或混稿")
        表格(pd.DataFrame(混), hide_index=True, width="stretch",
             column_config={"理由相似度": st.column_config.NumberColumn(format="percent")})
        st.caption("前後 1 天內兩個不同頻道點名 3 檔以上相同股票、理由句子又很像（兩字一組重疊 55% 以上），"
                   "可能是同一支影片整理兩次，或 Gemini 把兩支影片混在一起。這種在「被多個頻道點名」裡等於只算一次，要回去看原影片確認。")
    段落("FLAGS // 紅旗：哪些說法要打折")
    for v in 影片們:
        旗 = v.get("紅旗") or []
        st.markdown(f"{'🚩' * min(len(旗), 3) or '✅'} **{v['頻道']}**（{v.get('日期') or '—'}）：{len(v.get('股票', []))} 檔、"
                    f"{v.get('條件數', 0)} 個「如果…就…」條件" + (f"。{'；'.join(旗)}" if 旗 else "。沒有明顯紅旗"))
    if not 明細.empty:
        段落("LIST // 每一則看法")
        表格(明細.sort_values("日期", ascending=False), hide_index=True, width="stretch",
                     column_config={"日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
                                    "報酬%": st.column_config.NumberColumn(format="%+.1f"),
                                    "超額%": st.column_config.NumberColumn(format="%+.1f")})
    st.caption("紅旗是規則自動標的：用績效建立可信度、保證獲利用語、業配、沒有條件、幾乎全部看多、點名太多檔、沒有價位。"
               "有紅旗不代表說錯，只是要多查證。")


def 網紅熱度區(影片們):
    熱 = engine.網紅共識熱度(影片們, 天數=14)
    段落("HEAT // 近 14 天被多個頻道點名")
    if 熱.empty:
        st.caption("近 14 天沒有被 2 個以上頻道點名的股票。")
        return
    熱 = 熱.head(15)
    表格(熱, hide_index=True, width="stretch")
    st.caption("同一檔被很多頻道一起講，常是題材最熱的時候；全部看多時要小心是不是已經漲一段。看多／看空是各有幾個頻道。")


def 網紅條件區(影片們, 價們):
    清單 = engine.網紅條件清單(影片們, 天數=30, 名表=dict(zip(今日["名稱"], 今日["代號"])))
    段落("CHECK // 「如果…就…」條件現在成立了嗎（近 30 天影片）")
    if not 清單:
        st.caption("近 30 天的影片沒有條件。")
        return
    匯 = 讀檔("讀取匯率", _版本)
    外 = None
    if 有籌碼:
        近 = 指標[指標["date"] >= 最新日 - pd.Timedelta(days=20)]
        外 = (近["外資買超"] * 1000 * 近["收盤"]).groupby(近["date"]).sum() / 1e8
    K加 = 指數K線("TAIEX", _版本)
    列們 = []
    for r in 清單:
        K = None
        if r["代號"] == "TAIEX":
            K = K加
        elif r["代號"]:
            p = 價們.get(r["代號"]) if r["代號"] in 價們 else 個股價格(r["代號"])
            K = p.rename(columns={"收盤": "close"}) if p is not None else None
        狀, 說 = engine.檢查條件(r["條件"], r["標的"] or "", K, 匯, 外)
        if 狀:
            列們.append({"影片日": r["日期"], "頻道": r["頻道"], "條件": r["條件"],
                       "現在": "✅ 成立" if 狀 == "成立" else "⏳ 還沒", "依據": 說})
    if not 列們:
        st.caption(f"{len(清單)} 個條件裡，沒有網站看得懂的（只會判斷均線、價位、KD 交叉、台幣、外資）。")
        return
    表格(pd.DataFrame(列們), hide_index=True, width="stretch",
         column_config={"影片日": st.column_config.DateColumn(format="MM/DD")})
    st.caption(f"{len(清單)} 個條件裡有 {len(列們)} 個網站能自動判斷，只看條件的前半段（例如「站回 20 週線」）現在是不是真的。"
               "條件成立不代表後半段（就會漲）一定發生。")


def 漲跌停查核區(影片們):
    起 = 最新日 - pd.Timedelta(days=45)
    日表 = 指標[指標["date"] >= 起][["date", "代號", "日報酬"]].copy()
    日表["名稱"] = 日表["代號"].map(市場名稱).fillna("")
    t = engine.漲跌停查核(影片們, 日表, 天數=30)
    if t.empty:
        return
    段落("LIMIT // 網紅說「漲停／跌停」，真的有嗎（近 30 天影片）")
    t = t.sort_values("影片日", ascending=False)
    表格(t, hide_index=True, width="stretch",
         column_config={"影片日": st.column_config.DateColumn(format="MM/DD"),
                        "交易日": st.column_config.DateColumn(format="MM/DD"),
                        "實際漲跌%": st.column_config.NumberColumn(format="%+.2f")})
    錯 = int((t["結果"] == "❌ 不符").sum())
    st.caption(f"{len(t)} 則漲跌停說法有 {錯} 則對不上。對不上時，從當天真的漲停（跌停）的股票裡找名字念起來最像的，列在「可能是」；"
               "例如汪海華 11/02 說「萬泰科漲停」，字幕其實是「忘久」，當天漲停的是旺玖（6233）。漲跌幅 9.5% 以上算漲停。")


def 網紅價位區(影片們):
    價 = engine.網紅價位(影片們, dict(zip(今日["代號"], 今日["收盤"])), 天數=60)
    if 價.empty:
        return
    段落("PLAN // 評論者給的價位（近 60 天）")
    表格(價.sort_values("日期", ascending=False), hide_index=True, width="stretch",
         column_config={"日期": st.column_config.DateColumn(format="MM/DD"),
                        "距離%": st.column_config.NumberColumn(format="%+.1f")})
    st.caption("從理由裡挑出「支撐、停損、目標價 … 元」。距離%＝價位比現價高或低多少。")


@st.cache_data(ttl=6 * 3600, show_spinner="計算各策略過去的表現（第一次約 10 秒）…")
def 策略排行資料(版本鍵):
    return engine.策略排行(指標)


def 策略排行區():
    st.caption("把站上所有內建選股策略，用同一套方法比：過去一年每 5 個交易日，看那天選出來的股票，"
               "之後 5 日、20 日平均漲多少，再跟同期「全部股票平均」比。多方策略要贏大盤才算有用，空方策略要輸大盤才算有用。")
    總, 明 = 策略排行資料(_版本)
    if 總.empty:
        st.info("資料不足，算不出來。")
        return
    最好, 最差 = 總.iloc[0], 總.iloc[-1]
    卡片格([
        卡片("最有用", 最好["策略"].replace("烏賊", ""), f"20 日{'贏' if 最好['多空'] == '多' else '輸'}大盤 {abs(最好['20日超額%']):.1f} 個百分點", 紅),
        卡片("最沒用", 最差["策略"].replace("烏賊", ""), f"有用程度 {最差['有用程度']:+.1f}", 綠),
        卡片("比較期間", f"{明['日期'].min():%Y/%m}～{明['日期'].max():%Y/%m}", f"取樣 {明['日期'].nunique()} 天"),
    ])
    顯 = 總.rename(columns={"20日方向對%": "20日方向對的比例%"})
    欄 = ["策略", "多空", "有用程度", "20日超額%", "20日贏過大盤次數%", "20日方向對的比例%", "20日平均報酬%",
         "5日超額%", "5日平均報酬%", "平均檔數", "出現次數"]
    表格(顯[欄].style.map(lambda v: f"color:{紅 if v == '多' else 綠}", subset=["多空"])
         .map(lambda v: f"color:{漲跌色(v)}", subset=["有用程度", "20日超額%", "5日超額%"])
         .format({c: "{:+.2f}" for c in ("有用程度", "20日超額%", "5日超額%", "20日平均報酬%", "5日平均報酬%")}
                 | {"20日贏過大盤次數%": "{:.0f}", "20日方向對的比例%": "{:.0f}", "平均檔數": "{:.1f}"}),
         hide_index=True, width="stretch")
    圖 = go.Figure()
    for 名 in 總["策略"].head(4).tolist() + 總["策略"].tail(2).tolist():
        m = 明[明["策略"] == 名].sort_values("日期")
        方向 = 1 if m["多空"].iloc[0] == "多" else -1
        圖.add_trace(go.Scatter(x=m["日期"], y=(m["20日超額"] * 方向).cumsum(), name=名.replace("烏賊", ""), mode="lines"))
    圖.update_layout(title="累積有用程度（每次選股之後 20 日的超額，越往上越有用）", hovermode="x unified",
                     legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(圖表外觀(圖, 360), width="stretch")
    st.caption("有用程度＝多方看「20 日超額」，空方看它的相反數。贏過大盤次數%＝每次選股後，有幾成次數方向對又贏過大盤。"
               "注意：只有近一年資料，而且這一年大多是多頭，強勢股策略容易看起來特別好；「低價成長股」用到最新一期財報，"
               "會偷看未來，所以沒列入。這是歷史統計，不代表之後也會一樣。")


def 研究筆記區():
    段落("NOTES // 研究筆記")
    st.caption("自己的筆記、券商報告、網紅說法放在同一條時間軸，可以只看某一檔。有設密碼時，自己的筆記會加密後才存到 GitHub。")
    if not 可編輯():
        st.caption("要先到「02 / 我的股票」輸入密碼解鎖，才能看和寫自己的筆記。")
        筆記們 = []
    else:
        with st.expander("✏️ 寫一則筆記", expanded=not 研究筆記()):
            筆記輸入("總頁")
        筆記們 = 研究筆記()
    a, b = st.columns([2, 1])
    股 = a.selectbox("只看這檔", 股票選項, index=None, placeholder="全部股票", key="筆記篩選")
    來源們 = b.pills("來源", ["📝 我的筆記", "🏦 券商報告", "🎬 網紅說法"], selection_mode="multi",
                    default=["📝 我的筆記", "🏦 券商報告", "🎬 網紅說法"], key="筆記來源")
    t = engine.研究時間軸(筆記們, 券商報告清單(st.session_state.get("_券商版本", 0)),
                      網紅說法清單(st.session_state.get("_網紅版本", 0)), 股.split(" ")[0] if 股 else None)
    t = t[t["來源"].isin(來源們 or [])]
    if t.empty:
        st.caption("沒有符合的紀錄。")
    else:
        t["名稱"] = t["代號"].map(市場名稱).fillna("")
        t["日期"] = t["日期"].dt.strftime("%Y/%m/%d")
        表格(t[["日期", "來源", "名稱", "出處", "看法", "內容", "代號"]].style
             .map(lambda v: f"color:{紅}" if v in ("看多", "偏多", "買進") else (f"color:{綠}" if v in ("看空", "偏空", "賣出") else ""), subset=["看法"]),
             hide_index=True, width="stretch", height=min(35 * (len(t) + 1) + 3, 600),
             column_config={"內容": st.column_config.TextColumn(width="large")})
    if 筆記們:
        標籤 = [f"{x['日期']} {x.get('代號') or '（大盤）'} {市場名稱.get(x.get('代號'), '')}：{x['內容'][:30]}" for x in 筆記們]
        刪 = st.multiselect("要刪除的筆記", range(len(筆記們)), format_func=lambda i: 標籤[i], key="刪筆記")
        if 刪 and st.button(f"🗑️ 刪除 {len(刪)} 則", key="刪筆記鈕"):
            存研究筆記([x for i, x in enumerate(筆記們) if i not in set(刪)])
            st.rerun()


@st.cache_data(ttl=6 * 3600, show_spinner="計算長均線（年線、月 10MA、72 週線）…")
def 抄底名單(版本鍵, 距離上限):
    """三條件抄底：先用今天的融資、營收篩，剩下的才讀 1 年半歷史算長均線，省時間也省記憶體。"""
    營, _ = engine.月營收總表()
    年增 = 營["近3月年增"].dropna().to_dict() if len(營) and "近3月年增" in 營 else {}
    t = 今日[今日["代號"].str.fullmatch(r"\d{4}") & (今日["收盤"] > 0)]
    洗 = t["融資洗完"].astype(bool) if "融資洗完" in t.columns else pd.Series(False, index=t.index)
    減 = t["融資20日增減"] <= -10 if "融資20日增減" in t.columns else pd.Series(False, index=t.index)
    t = t[(洗 | 減) & t["代號"].map(lambda c: (年增.get(c) or 0) > 0)]
    if t.empty:
        return pd.DataFrame(), 0
    歷 = engine.讀取資料庫(代號=t["代號"].tolist(), 起日=最新日 - pd.Timedelta(days=560))
    if 歷 is None:
        return pd.DataFrame(), len(t)
    距 = engine.長均線距離(歷)
    del 歷
    return engine.抄底三條件(t, 距, 年增, 距離上限=距離上限), len(t)


def 抄底區():
    段落("DIP BUY // 三條件抄底：跌到長均線＋營收沒壞＋融資洗掉")
    st.caption("通勤族（阿信，2026-11-04）的選股法：① 技術面跌到長均線支撐（年線、月 10MA、72 週線任一條，上下幾 % 內）、"
               "② 基本面沒壞（近 3 個月營收年增 > 0）、③ 融資已經退場（🧹 融資洗完，或融資 20 日減少 10% 以上）。")
    距離上限 = st.segmented_control("離均線多近", [2.0, 3.0, 5.0], default=3.0, key="抄底距離",
                                format_func=lambda v: f"±{v:.0f}%") or 3.0
    表, 候選 = 抄底名單(_版本, 距離上限)
    if 表.empty:
        st.caption(f"今天沒有三個條件都符合的股票（融資＋營收先篩出 {候選} 檔，沒有一檔靠近長均線）。")
        return
    點選表(表, 上色(表).format({c: "{:+.1f}" for c in ("距年線%", "距月10MA%", "距72週線%", "近3月營收年增", "融資20日增減")}
                             | {"融資維持率": "{:.0f}", "本益比": "{:.1f}"}, na_rep="—"), "抄底表",
          height=min(35 * (len(表) + 1) + 3, 520))
    st.caption(f"融資＋營收先篩出 {候選} 檔，其中 {len(表)} 檔靠近長均線。距離用原始收盤價（沒有還原除權息），"
               "月 10MA＝最近 10 個月底收盤平均（含本月）、72 週線＝最近 72 個週收盤平均（含本週）。"
               "阿信的做法是等震盪中均線不破、再站回 5 週線才加碼；這張表只是觀察名單，"
               "網站回測過「融資洗完」單獨當策略並不好（見 01 跌深榜說明），不是買賣建議。")


def 訂閱清單():
    if "條件訂閱" not in st.session_state:
        try:
            st.session_state["條件訂閱"] = engine.讀取設定檔(_設定(), "subscriptions.json") or {}
        except Exception:
            return {}
    return st.session_state["條件訂閱"]


def 存訂閱(訂閱):
    st.session_state["條件訂閱"] = 訂閱
    try:
        if engine.儲存設定檔(_設定(), "subscriptions.json", 訂閱, "更新選股訂閱"):
            st.toast("選股訂閱已儲存")
        else:
            st.toast("已暫存（網站重新啟動會消失；在 Secrets 設定 GITHUB_TOKEN 就能永久保存）")
    except Exception as e:
        st.error(f"選股訂閱存檔失敗：{e}")


def 條件訂閱區(條件, 範本, 結果):
    with st.expander(f"🔔 訂閱這組條件：每天收盤後 LINE 通知「新符合」「剛剔除」的股票（目前 {len(訂閱清單())} 組）"):
        if not 可編輯():
            st.caption("要先到「02 / 我的股票」輸入密碼解鎖才能訂閱。")
            return
        訂 = 訂閱清單()
        a, b = st.columns([3, 1])
        名 = a.text_input("幫這組條件取個名字", value=範本 if 範本 != "自訂條件" else "", placeholder="例如：高殖利率低本益比",
                         key="訂閱名稱", label_visibility="collapsed")
        if b.button("🔔 訂閱", key="訂閱鈕", disabled=not 名.strip()):
            存訂閱({**訂, 名.strip(): {"條件": 條件, "建立": f"{最新日:%Y-%m-%d}", "檔數": len(結果)}})
            st.rerun()
        if len(結果) > 50:
            st.caption(f"⚠️ 這組條件今天有 {len(結果)} 檔，太多的話每天變動會很多，LINE 只會列前 15 檔。")
        for n, v in list(訂.items()):
            a, b = st.columns([4, 1])
            a.markdown(f"**{n}**　{v.get('建立', '')} 建立，當時 {v.get('檔數', '—')} 檔")
            if b.button("取消", key=f"取消訂閱_{n}"):
                存訂閱({k: x for k, x in 訂.items() if k != n})
                st.rerun()
        st.caption("訂閱的條件存在 ai-reports 分支的 subscriptions.json。第一天只記錄名單、不通知；之後每天收盤摘要會附上變動。")


# ---------- 04 選股 ----------
@st.cache_data(ttl=43200, max_entries=2, show_spinner=False)
def 預估修正驗證資料(版本鍵, 快照們):
    """快照們只用來當快取鍵（上傳新快照就重算）。用記憶體裡的 300 天還原價，不另外讀資料庫。"""
    價 = 指標.pivot(index="date", columns="代號", values="還原價").sort_index()
    return engine.預估修正驗證(價)


def 預估上傳區():
    if not 可編輯():
        st.caption("上傳新的預估 EPS 要先在 01 市場總覽的庫存區輸入密碼解鎖。")
        return
    檔 = st.file_uploader("上傳全市場預估 EPS（CSV，跟 11/07 那份同格式：股號、A_2026E_EPS、B_2026E_EPS、Vera_2026E_EPS…）",
                         type=["csv"], key="預估上傳")
    if not 檔:
        return
    try:
        原始 = pd.read_csv(檔, dtype={"股號": str, "代號": str, "code": str}, encoding="utf-8-sig")
        t = engine.轉換預估檔(原始)
    except Exception as e:
        st.error(f"讀不懂這個檔：{e}")
        return
    import re as _re
    m = _re.search(r"(20\d{6})", 檔.name)
    預設 = pd.Timestamp(m.group(1)) if m else pd.Timestamp(最新日)
    日 = st.date_input("這份預估的資料日", value=預設.date(), key="預估資料日")
    st.caption(f"讀到 {len(t)} 檔，欄位：{'、'.join(c for c in t.columns if c != 'code')}")
    if st.button("💾 存成新的一份快照", key="存預估", type="primary"):
        try:
            永久 = engine.存預估檔(t, 日, _設定())
        except Exception as e:
            st.error(f"存檔失敗：{e}")
            return
        st.cache_data.clear()
        st.success(f"已存 {pd.Timestamp(日):%Y-%m-%d} 的預估（" + ("已寫入 GitHub，網站重新部署後全站生效）" if 永久 else "只存在網站上，重啟會消失）"))


def 預估EPS分頁():
    段落("FORECAST // 預估 EPS 快照：上修、下修追蹤")
    快照 = engine.預估檔們()
    卡片格([卡片("快照份數", f"{len(快照)}", "、".join(f"{d:%m/%d}" for d, _ in 快照[-4:]) or "—"),
           卡片("最新一份", f"{快照[-1][0]:%Y-%m-%d}" if 快照 else "—"),
           卡片("涵蓋檔數", f"{int(今日['預估EPS今年'].notna().sum()) if '預估EPS今年' in 今日 else 0}", "有 A 或 B 預估")])
    with st.expander("📥 上傳新的一份預估 EPS", expanded=not 快照):
        預估上傳區()
    st.caption("建議每週（或每月）上傳一份同樣格式的匯出檔。網站會跟上一份比，算出上修、下修，"
               "累積幾份之後自動驗證「預估上修的股票之後有沒有比較會漲」。")
    if "預估修正%" not in 今日.columns:
        st.info("目前只有一份預估快照，等下一份上傳後這裡就會列出上修、下修名單。")
    else:
        t = 今日[今日["預估修正%"].notna() & (今日["成交張數"] >= 200)]
        欄 = [c for c in ["代號", "名稱", "收盤", "漲跌幅", "前期預估EPS今年", "預估EPS今年", "預估修正%", "明年預估修正%",
                         "預估本益比", "明年預估本益比"] if c in t.columns]
        上, 下 = st.columns(2)
        with 上:
            st.markdown("**🔺 上修最多**")
            a = t[t["預估修正%"] > 0].nlargest(20, "預估修正%")
            點選表(a, 上色(a[欄]), "預估上修表", height=400)
        with 下:
            st.markdown("**🔻 下修最多**")
            b = t[t["預估修正%"] < 0].nsmallest(20, "預估修正%")
            點選表(b, 上色(b[欄]), "預估下修表", height=400)
        st.caption("修正%＝今年預估 EPS（A、B 中位數）跟上一份比；上一份太小（< 0.3 元）的不算。只列成交 200 張以上。")
    段落("TEST // 預估上修的股票，之後有比較會漲嗎？")
    結果, 說明 = 預估修正驗證資料(_版本, tuple(str(d) for d, _ in 快照))
    st.markdown(說明)
    if 結果 is not None:
        表格(結果.style.format({"前期": "{:%Y-%m-%d}", "本期": "{:%Y-%m-%d}", "上修超額%": "{:+.2f}", "下修超額%": "{:+.2f}",
                               "上修減下修%": "{:+.2f}"}), hide_index=True, width="stretch")
    st.caption("每兩份相鄰快照：今年預估上修 ≥ 2% 與下修 ≤ −2% 的股票，下一份資料日後 20 個交易日的平均報酬減全體平均。"
               "期數少的時候結果不穩定，至少累積 6 期以上再當參考。")


選股分頁 = st.tabs(["條件選股", "烏賊每日功課", "烏賊策略總覽", "🏆 策略排行榜", "券商報告", "網紅說法", "📝 研究筆記", "🧲 三條件抄底", "📐 預估 EPS"])
with 選股分頁[8]:
  預估EPS分頁()
with 選股分頁[7]:
  抄底區()
with 選股分頁[6]:
  研究筆記區()
with 選股分頁[3]:
  策略排行區()
with 選股分頁[4]:
  券商報告總覽()
with 選股分頁[5]:
  網紅說法總覽()
with 選股分頁[2]:
  總表, 名單, 重複 = engine.烏賊總覽(今日)
  多 = 總表[總表["多空"] == "多"]["符合檔數"].sum()
  空 = 總表[總表["多空"] == "空"]["符合檔數"].sum()
  卡片格([卡片("多方策略符合", f"{多}", "檔次（可能重複）", 紅), 卡片("空方策略符合", f"{空}", "檔次（可能重複）", 綠),
         卡片("同時符合 2 個以上", f"{len(重複)}", "檔", 青)])
  st.caption("多＝適合找買點（講義：強勢股買拉回、盤整突破）；空＝轉弱、避開或減碼（講義：跌破十日線、弱勢股）。"
             "資料日期 " + 最新日.strftime("%Y-%m-%d"))
  段落("SUMMARY // 各策略符合檔數")
  表格(總表.style.map(lambda v: f"color:{紅 if v == '多' else 綠}", subset=["多空"]),
               hide_index=True, width="stretch",
               column_config={"說明": st.column_config.TextColumn(width="large")})
  段落("OVERLAP // 同時符合多個策略")
  if 重複.empty:
      st.write("今天沒有股票同時符合 2 個以上的策略。")
  else:
      點選表(重複, 上色(重複).map(lambda v: f"color:{紅 if v == '多' else (綠 if v == '空' else '#FFC24B')}",
                              subset=["多空"]), "重複表")
  段落("DETAIL // 各策略名單")
  清單欄 = ["代號", "名稱", "市場", "收盤", "漲跌幅", "成交張數", "量對5日均", "3日漲幅", "5日漲幅", "20日漲幅",
           "40日漲幅", "週轉率", "股本億", "法人5日買超", "法人10日買超", "營收年增率", "近三季EPS"]
  for 名, 結果 in 名單.items():
      方向 = engine.烏賊條件[名]["方向"]
      with st.expander(f"{'🔴 多' if 方向 == '多' else '🟢 空'}｜{名.replace('烏賊', '')}｜{len(結果)} 檔"):
          st.caption(engine.烏賊條件[名]["說明"])
          if len(結果):
              點選表(結果, 上色(結果[[c for c in 清單欄 if c in 結果.columns]]), f"策略表{名}")
with 選股分頁[1]:
  st.caption("講義「每天的功課」：每天看這六張榜，熟悉股性。三&五日強勢股的重點是找貼近 5 日或 10 日線、"
             "均線剛勾起來的股票（★）；股本小、量大、有題材最好。")
  功課 = engine.每日功課(今日)
  功課欄 = [c for c in ["代號", "名稱", "市場", "收盤", "漲跌幅", "3日漲幅", "5日漲幅", "振幅", "成交張數",
                      "量對5日均", "股本億", "外資買超", "投信買超", "重點"] if c in 今日.columns or c == "重點"]
  for 標籤, 分頁表 in zip(功課, st.tabs(list(功課))):
      with 分頁表:
          表 = 功課[標籤]
          if "股本億" not in 表.columns:
              表 = 表.join(讀檔("_股本表", _版本), on="代號")
          點選表(表, 上色(表[[c for c in 功課欄 if c in 表.columns]]), f"功課表{標籤}", height=420)
  with st.expander("課程重點：盤整、上升、下降趨勢怎麼操作"):
      st.markdown("""
- **盤整格局**：找出最高點與最低點畫成箱型（框框），注意箱子左右兩邊爆量的日子；**收盤突破箱頂**、量放大是轉強訊號。
- **上升趨勢**：沿著 5 日、10 日線走，突破前波高點後一路墊高；**怎麼買？靠近昨天高點買**，強勢股別人追高，你買拉回點。
- **下降趨勢**：**跌破十日線後**轉弱，反彈到壓力就該小心；弱勢股別人追空，你買反彈點。
- **五分 K**：用盤中 5 分鐘 K 線找當日進出場點，避免看到大單就追或被嚇跑（本站目前只有日線資料）。
- **烏賊的話**：勇於嘗試＋嚴格停損；隔日沖反應不如預期就砍；小波段請把握反轉點或跌破關鍵價位。

這些規則已做成「個股回測」裡的 **盤整突破（烏賊）** 與 **均線勾起（烏賊）** 兩個策略，「條件選股」分頁的「策略範本」可直接套用五組選股條件。
""")
with 選股分頁[0]:
  with st.expander("⚙️ 選股條件（組合回測也用這組）", expanded=True):
      條件, 範本 = 選股條件區()
  結果 = engine.選股(今日, 條件)
  卡片格([
      卡片("符合條件", f"{len(結果)}", "檔", 青),
      卡片("資料日期", 最新日.strftime("%Y-%m-%d")),
      卡片("排序", 條件["排序"]),
  ])
  段落("RESULT // 選股結果")
  顯示欄 = [c for c in ["代號", "名稱", "市場", "收盤", "漲跌幅", "本益比", "殖利率", "淨值比",
                      "營收年增率", "營收月增率", "累計營收年增率", "EPS", "成交張數",
                      "外資買超", "投信買超", "法人5日買超", "外資連買", "投信連買", "融資5日增減",
                      "20日漲幅", "RSI", "量比", "距52週高點"] if c in 結果.columns]
  for 鍵, 欄們 in (("外資持股比下限", ["外資持股比", "外資持股20日變化"]), ("外資持股20日變化下限", ["外資持股比", "外資持股20日變化"]),
                 ("當沖比率上限", ["當沖比率"]), ("負債比上限", ["負債比", "流動比"]),
                 ("自由現金流為正", ["近四季營業現金流億", "近四季自由現金流億"]),
                 ("合約負債年增下限", ["合約負債億", "合約負債年增", "能見度月"]), ("能見度月下限", ["合約負債億", "合約負債年增", "能見度月"]),
                 ("預估本益比上限", ["預估EPS今年", "預估本益比", "預估EPS明年", "明年預估本益比", "明年EPS成長%", "預估分歧%"]), ("明年預估本益比上限", ["預估EPS今年", "預估本益比", "預估EPS明年", "明年預估本益比", "明年EPS成長%", "預估分歧%"]),
                 ("預估修正下限", ["預估EPS今年", "前期預估EPS今年", "預估修正%", "預估本益比"]),
                 ("明年EPS成長下限", ["預估EPS今年", "預估本益比", "預估EPS明年", "明年預估本益比", "明年EPS成長%", "預估分歧%"]), ("排除預估分歧", ["預估EPS今年", "預估本益比", "預估EPS明年", "明年預估本益比", "明年EPS成長%", "預估分歧%"])):
      if 條件.get(鍵) is not None:
          顯示欄 += [c for c in 欄們 if c in 結果.columns and c not in 顯示欄]
  if str(條件.get("排序", "")).startswith(("預估", "明年")):
      顯示欄 += [c for c in ["預估EPS今年", "預估本益比", "預估EPS明年", "明年預估本益比", "明年EPS成長%", "預估修正%"]
                if c in 結果.columns and c not in 顯示欄]
  if 範本 != "自訂條件":  # 烏賊條件多看幾個相關欄位
      顯示欄[3:3] = [c for c in ["週轉率", "股本億", "量對5日均", "5日均量", "10日漲幅", "30日漲幅", "40日漲幅",
                               "法人10日買超", "近三季EPS"] if c in 結果.columns]
  點選表(結果, 上色(結果[顯示欄]), "選股表", height=420)
  st.caption("點一下任何一列，就會跳到那檔股票的個股查詢。")
  st.download_button("下載 CSV", 結果[顯示欄].to_csv(index=False).encode("utf-8-sig"),
                     file_name=f"選股_{最新日:%Y%m%d}.csv")
  條件訂閱區(條件, 範本, 結果)

  段落("CHART // 個股走勢")
  選項 = (結果["代號"] + " " + 結果["名稱"]).tolist() or (今日["代號"] + " " + 今日["名稱"]).tolist()
  選擇 = st.selectbox("選一檔股票", 選項)
  個股 = 指標[指標["代號"] == 選擇.split()[0]].tail(250)
  圖 = go.Figure(go.Candlestick(
      x=個股["date"], open=個股["open"], high=個股["high"], low=個股["low"], close=個股["收盤"],
      increasing=dict(line=dict(color=紅), fillcolor=紅),
      decreasing=dict(line=dict(color=綠), fillcolor=綠), name="K 線"))
  # 均線用還原價算，換算回原始股價的比例來畫
  比例 = 個股["收盤"] / 個股["還原價"]
  for 天數, 色 in ((5, "#FFFFFF"), (20, 青), (60, "#FF00E5")):
      圖.add_trace(go.Scatter(x=個股["date"], y=個股[f"MA{天數}"] * 比例, name=f"MA{天數}",
                              line=dict(color=色, width=1)))
  圖.update_layout(xaxis_rangeslider_visible=False)
  st.plotly_chart(圖表外觀(圖, 420), width="stretch")
