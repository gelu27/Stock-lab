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
        st.caption("達標＝報告後 6 個月內股價碰到目標價；平均報酬＝報告日收盤到現在（最多 6 個月）。"
                   "多數報告定義「買進」是 6 個月報酬 15～30%，時間還不到 6 個月的算進行中。")


網紅指令 = ("請用繁體中文完整整理這支影片，不要只寫摘要，也不要加入你自己的看法：（貼上影片連結）\n"
          "格式：一、頻道、日期、長度。二、逐段內容（時間點、講什麼、理由），保留所有數字。"
          "三、提到的股票（每檔一行：代號 名稱：看多或看空。理由：…，有價位要寫）。四、所有「如果…就…」的判斷條件。"
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
    代們 = {str(x["代號"]) for v in 影片們 for x in v.get("股票", []) if str(x.get("代號", "")).isdigit()}
    價們 = {c: 個股價格(c) for c in 代們}
    明細, 彙 = engine.網紅對答案(影片們, {k: v for k, v in 價們.items() if v is not None}, 指數K線("TAIEX", _版本))
    段落("SCORE // 誰說得準（20 個交易日後，扣掉大盤漲跌）")
    if 彙.empty:
        st.caption("還沒有可以對答案的資料。")
    else:
        表格(彙, width="stretch", column_config={"平均超額%": st.column_config.NumberColumn(format="%+.1f")})
        st.caption("超額報酬＝個股報酬減同期加權報酬。看多且贏大盤、看空且輸大盤算說對；不到 20 天的算「暫時」，不計入命中率。"
                   "中立的不算。樣本少的時候命中率只是參考。")
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


# ---------- 04 選股 ----------
選股分頁 = st.tabs(["條件選股", "烏賊每日功課", "烏賊策略總覽", "券商報告", "網紅說法"])
with 選股分頁[3]:
  券商報告總覽()
with 選股分頁[4]:
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
              表 = 表.join(engine._股本表(), on="代號")
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
  if 範本 != "自訂條件":  # 烏賊條件多看幾個相關欄位
      顯示欄[3:3] = [c for c in ["週轉率", "股本億", "量對5日均", "5日均量", "10日漲幅", "30日漲幅", "40日漲幅",
                               "法人10日買超", "近三季EPS"] if c in 結果.columns]
  點選表(結果, 上色(結果[顯示欄]), "選股表", height=420)
  st.caption("點一下任何一列，就會跳到那檔股票的個股查詢。")
  st.download_button("下載 CSV", 結果[顯示欄].to_csv(index=False).encode("utf-8-sig"),
                     file_name=f"選股_{最新日:%Y%m%d}.csv")

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
