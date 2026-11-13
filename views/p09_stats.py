# 09 使用統計：由 app.py 的 執行頁面() 在同一個命名空間執行，可直接用 app.py 的共用函式與資料。
# ---------- 08 使用統計 ----------
@st.cache_data(ttl=60, show_spinner=False)
def 來訪資料(_權杖):
    return engine.讀取來訪(_設定())


@st.cache_data(ttl=600, show_spinner="讀取 AI 報告中…")
def AI報告總覽(_權杖):
    return engine.列出AI報告(_設定())


if not 可編輯():
    段落("STATS // 使用統計")
    輸入 = st.text_input("使用統計只有站長能看，請輸入密碼", type="password", key="統計解鎖")
    if 輸入 and hmac.compare_digest(輸入, _密碼()):
        st.session_state["已解鎖"] = True
        st.query_params["k"] = 登入憑證()
        st.rerun()
    elif 輸入:
        st.error("密碼不正確")
    st.stop()
權杖 = str(_設定().get("GITHUB_TOKEN", ""))
段落("VISITORS // 來客數")
try:
    統計 = 來訪資料(權杖)
except Exception as e:
    統計 = {}
    st.caption(f"來客數暫時讀不到（{type(e).__name__}）")
if not 統計:
    st.info("從這次更新開始記錄，之後每有人打開網站就會累計。")
else:
    日表 = pd.DataFrame([{"日期": pd.Timestamp(d), "瀏覽": v.get("次數", 0) - v.get("自己", 0),
                         "訪客": len(v.get("訪客", [])), "自己": v.get("自己", 0)} for d, v in 統計.items()])
    日表 = 日表.sort_values("日期")
    今 = pd.Timestamp(dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date())
    def 區間(天):
        t = 日表[日表["日期"] > 今 - pd.Timedelta(days=天)]
        碼 = {c for d, v in 統計.items() if pd.Timestamp(d) > 今 - pd.Timedelta(days=天) for c in v.get("訪客", [])}
        return int(t["瀏覽"].sum()), len(碼)
    卡們 = []
    for 名, 天 in (("今天", 1), ("近 7 天", 7), ("近 30 天", 30), (f"累計（{日表['日期'].min():%m/%d} 起）", 100000)):
        次, 人 = 區間(天)
        卡們.append(卡片(名, f"{人:,} 人", f"瀏覽 {次:,} 次"))
    卡片格(卡們)
    近 = 日表[日表["日期"] > 今 - pd.Timedelta(days=30)]
    日 = 近["日期"].dt.strftime("%m/%d")
    圖 = go.Figure([go.Bar(x=日, y=近["瀏覽"], name="瀏覽次數", marker_color=青),
                    go.Scatter(x=日, y=近["訪客"], name="訪客人數", mode="lines+markers",
                               line=dict(color="#FFC24B", width=2))])
    圖.update_layout(hovermode="x unified", legend=dict(orientation="h", y=1.1))
    圖.update_xaxes(type="category")
    st.plotly_chart(圖表外觀(圖, 280), width="stretch")
    st.caption("瀏覽＝打開網站的次數（重新整理也算一次）；訪客＝不同網路位址（同一個 Wi-Fi 下的人會算成一位）。"
               f"都不含你自己登入後的瀏覽（你自己共 {int(日表['自己'].sum()):,} 次）。"
               "Streamlit 後台（share.streamlit.io → 這個 App →「Analytics」）也有官方的觀看人數。")

段落("AI REPORTS // 產生過 AI 報告的個股")
try:
    報告們 = AI報告總覽(權杖)
except Exception as e:
    報告們 = {}
    st.caption(f"AI 報告暫時讀不到（{type(e).__name__}）")
列們, 驗收們 = [], []
現價 = 今日.set_index("代號")
for 代號, 紀錄們 in 報告們.items():
    if not 紀錄們:
        continue
    價格 = 指標.loc[指標["代號"] == 代號, ["date", "high", "low", "收盤"]]
    for 紀 in 紀錄們:
        驗 = engine.驗收AI報告(紀, 價格)
        驗收們.append(dict(驗, 代號=代號, 看法=(紀.get("建議") or engine.拆解AI建議(紀.get("內容", ""))[1] or {}).get("看法")))
    驗 = engine.驗收AI報告(紀錄們[0], 價格)
    驗收文字 = {"達標": f"🎯 達標 {驗['日期']:%m/%d}" if pd.notna(驗["日期"]) else "🎯 達標",
                "停損": f"🛑 停損 {驗['日期']:%m/%d}" if pd.notna(驗["日期"]) else "🛑 停損",
                "進行中": f"⏳ 進行中（{驗['天數']} 天）", "無目標價": "—"}[驗["結果"]]
    新 = 紀錄們[0]
    建議 = 新.get("建議") or engine.拆解AI建議(新.get("內容", ""))[1] or {}
    def 數值(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return np.nan
    當時, 目標 = 數值(新.get("收盤")), 數值(建議.get("目標價合理"))
    現 = 現價["收盤"].get(代號, np.nan)
    列們.append({"股票": f"{代號} {現價['名稱'].get(代號, '')}".strip(), "報告次數": len(紀錄們),
                "最新報告": 新.get("時間", ""), "AI 看法": 建議.get("看法") or "—",
                "當時收盤": 當時, "現在股價": 現, "報告後漲跌%": round((現 / 當時 - 1) * 100, 2) if 當時 else np.nan,
                "AI 目標價": 目標, "距目標價%": round((目標 / 現 - 1) * 100, 1) if pd.notna(目標) and 現 else np.nan,
                "驗收": 驗收文字, "停損價": 驗["停損"], "引擎": 新.get("引擎", ""), "代號": 代號})
if not 列們:
    st.info("還沒有產生過 AI 報告。")
else:
    表 = pd.DataFrame(列們).sort_values("最新報告", ascending=False)
    驗 = pd.DataFrame(驗收們)
    達, 損 = int((驗["結果"] == "達標").sum()), int((驗["結果"] == "停損").sum())
    卡片格([卡片("產生過報告的個股", f"{len(表)} 檔", f"報告共 {int(表['報告次數'].sum())} 份"),
           卡片("AI 命中率", f"{達 / (達 + 損) * 100:.0f}%" if 達 + 損 else "—",
                f"已結案 {達 + 損} 份：達標 {達}、停損 {損}；進行中 {int((驗['結果'] == '進行中').sum())}",
                紅 if 達 + 損 and 達 >= 損 else (綠 if 達 + 損 else "#EDEDED")),
           卡片("報告後平均漲跌", f"{表['報告後漲跌%'].mean():+.2f}%", "以最新一份報告的收盤價起算",
                漲跌色(表["報告後漲跌%"].mean()))])
    點選表(表, 上色(表).format({"報告後漲跌%": "{:+.2f}", "距目標價%": "{:+.1f}", "當時收盤": "{:,.0f}",
                             "現在股價": "{:,.0f}", "AI 目標價": "{:,.0f}",
                             "停損價": "{:,.0f}"}, na_rep="—")
           .map(lambda v: f"color:{漲跌色(v)}", subset=["距目標價%"]), "AI報告表",
           height=35 * (len(表) + 1) + 3, column_config={"代號": None})
    st.caption("驗收：報告之後股價先碰到目標價＝🎯達標、先碰到停損價＝🛑停損（同一天都碰到算停損），還沒碰到＝⏳進行中；"
               "命中率＝達標 ÷（達標＋停損），統計所有報告（含舊的）。"
               "AI 目標價＝報告裡的「合理目標價」，距目標價% ＝ 目標價比現在股價高（紅）或低（綠）多少。"
               "舊版報告沒有目標價，到個股的「🤖 AI 分析」分頁打開一次就會自動補上。點一下股票可到個股查詢。")

import feedback as _回饋模組
_回饋 = _回饋模組.讀取回饋()
段落("FEEDBACK // 資料累積進度")
if not _回饋:
    st.info("每天收盤資料更新後會自動計算（data/feedback.json），明天起這裡就會有數字。")
else:
    _進 = pd.DataFrame(_回饋.get("進度", []))
    if len(_進):
        表格(_進[["記分板", "狀態", "樣本", "門檻", "預估", "說明"]].rename(columns={"預估": "預估可參考"}),
             hide_index=True, width="stretch")
    st.caption(f"計算日 {_回饋.get('計算日')}。語言模型不會自己學習，網站變準靠的是：累積樣本 → 對答案 → 把說錯的寫回提示（AI 錯誤本）。"
               "樣本到門檻前的命中率只當參考；預估日期是照目前累積速度推算。")
    _券 = pd.DataFrame.from_dict(_回饋.get("券商") or {}, orient="index")
    if len(_券):
        with st.expander(f"券商過去紀錄（{len(_券)} 家，報告後 20／60 日跑贏加權沒）"):
            表格(_券, width="stretch")
            st.caption("說對＝看多後超額報酬 > 0、看空後 < 0（中性不算）；超額＝個股漲跌扣掉同期加權。"
                       "達標率要等 6 個月到期才有。這張表也會餵給個股 AI，紀錄差或樣本少的券商要打折。")
    _網 = pd.DataFrame.from_dict(_回饋.get("網紅") or {}, orient="index")
    if len(_網):
        with st.expander(f"網紅記分板（{len(_網)} 個頻道，20 日後對答案）"):
            表格(_網, width="stretch")

段落("RULES // 規則體檢")
_體 = _回饋模組.讀取規則體檢().get("歷史", [])
if not _體:
    st.info("每月重算一次（update.yml），第一次算完就會出現。")
else:
    _新 = pd.DataFrame(_體[-1]["規則"])
    _圖示 = {"有效": "✅ 有效", "沒有優勢": "⚪ 沒有優勢", "反向": "🔻 反向", "樣本太少": "⏳ 樣本太少"}
    _新["判定"] = _新["判定"].map(lambda v: _圖示.get(v, v))
    卡片格([卡片(_k, f"{int((_新['判定'] == _v).sum())} 條", "") for _k, _v in _圖示.items()])
    表格(_新[["判定", "規則", "超額%", "次數", "天數", "說明"]], hide_index=True, width="stretch")
    _變 = _回饋模組.體檢變化()
    if _變:
        st.warning("跟上個月比判定有變：" + "；".join(f"{_名} {_前}→{_今}" for _名, _前, _今, _x in _變))
    st.caption(f"計算日 {_體[-1]['計算日']}（共 {len(_體)} 次）。超額%＝亮燈後 N 日平均漲跌 − 任何一天的平均（評分列是 IC，t ≥ 2 算有效）。"
               "沒有優勢或反向的燈號會告訴大盤 AI 不要當主要依據；每月第一份 LINE 週報附體檢摘要。")

段落("PROMPT // 提示版本")
_明 = pd.DataFrame((_回饋.get("大盤解讀") or {}).get("明細", []))
_版列 = []
if len(_明):
    for _版, _g in _明.groupby("提示版本"):
        _看 = _g[_g["看法對"].notna()]
        _條 = [c for cs in _g["條件"] for c in cs]
        _版列.append({"類型": "大盤解讀", "提示版本": _版, "篇數": len(_g), "起": _g["時間"].min()[:10],
                     "看法命中": f"{int(_看['看法對'].sum())}/{len(_看)}" if len(_看) else "—",
                     "條件成立": f"{sum(c['成立'] for c in _條)}/{len(_條)}" if _條 else "—"})
for _版, _v in ((_回饋.get("AI報告") or {}).get("版本") or {}).items():
    _結 = _v["達標"] + _v["停損"]
    _版列.append({"類型": "個股 AI 報告", "提示版本": _版, "篇數": _v["份數"], "起": "",
                 "看法命中": f"達標 {_v['達標']}/{_結}" if _結 else "—", "條件成立": ""})
if _版列:
    表格(pd.DataFrame(_版列), hide_index=True, width="stretch")
表格(pd.DataFrame(_回饋模組.提示修改紀錄, columns=["日期", "改了什麼"]), hide_index=True, width="stretch")
st.caption(f"目前版本：大盤解讀 {engine.大盤提示版本()}、個股 AI {engine.個股提示版本()}。"
           "版本碼是提示文字的指紋，提示一改就換；「未記錄」是 2026-11-12 以前的解讀與報告。同一版本累積夠多篇再比較才有意義。")

段落("LINE // 推播額度")
_額 = _回饋.get("LINE額度")
if _額:
    st.markdown(_回饋模組.額度文字(_額) + f"（{_額.get('查詢時間', '')} 查詢）")
else:
    st.caption("還沒查到額度（每天收盤更新時用 LINE 官方 API 查一次，需要 Actions 的 LINE_TOKEN）。")
try:
    _用 = (engine.讀取設定檔(_設定(), "line_usage.json") or {}).get(f"{pd.Timestamp.now(tz='Asia/Taipei'):%Y-%m}", {})
except Exception:
    _用 = {}
if _用:
    _功能們 = sorted(set(_用.get("推播", {})) | set(_用.get("回覆", {})) | set(_用.get("略過", {})),
                  key=lambda k: -_用.get("推播", {}).get(k, 0))
    表格(pd.DataFrame([{"功能": k, "推播（算額度）": _用.get("推播", {}).get(k, 0),
                       "回覆（不算）": _用.get("回覆", {}).get(k, 0), "節省模式略過": _用.get("略過", {}).get(k, 0)}
                      for k in _功能們]), hide_index=True, width="stretch")
    st.caption(f"本月實際推播 {_用.get('總則數', 0)} 則（同一次合併送出的幾個功能各記 1 次，但只算 1 則額度）。")
_估 = pd.DataFrame(_回饋模組.推播來源估計, columns=["功能", "每月約幾則", "說明"])
表格(_估, hide_index=True, width="stretch")
st.caption(f"估計合計每月約 {int(_估['每月約幾則'].sum())} 則（免費上限 200 則；一次送最多 5 個訊息框只算 1 則）。"
           "同一個排程的通知會合成一則；照目前速度月底會超過上限時自動進入節省模式，"
           "新片提醒、盤中大盤價位、ETF 斷線、網站錯誤改成只在網站顯示；剩下的額度比剩餘天數少時只推收盤摘要、到價和停損。"
           "在 LINE 打「新片」「解讀」「額度」會用回覆傳，不算額度。")

段落("ERRORS // 網站錯誤紀錄")
try:
    錯誤們 = engine.讀取設定檔(_設定(), "errors.json") or {}
except Exception as e:
    錯誤們 = {}
    st.caption(f"錯誤紀錄暫時讀不到（{type(e).__name__}）")
if not 錯誤們:
    st.caption("✅ 沒有記錄到網站錯誤。頁面出錯時會自動記在這裡，每天收盤後的資料檢查也會用 LINE 通知。")
else:
    錯表 = pd.DataFrame(錯誤們.values()).sort_values("最近", ascending=False)
    表格(錯表[["最近", "頁面", "類型", "訊息", "位置", "次數", "首次"]], hide_index=True, width="stretch")
    with st.expander("看完整錯誤訊息（可以複製貼給 Claude 修）"):
        for _, x in 錯表.head(5).iterrows():
            st.code(f"{x['最近']} {x['頁面']}\n{x.get('追蹤', '')}", language=None)

段落("BACKUP // 個人資料備份")
st.caption("把自選股、到價提醒、選股訂閱、回測常用條件、交易日記、研究筆記、券商報告、網紅說法打包成一個 zip 下載，"
           "可以自己存到 Google 雲端硬碟。交易日記和研究筆記在 zip 裡是解密後的內容，請放在只有自己看得到的地方。"
           "另外 GitHub 每週六也會自動備份一份（Actions →「LINE 週報」→ Artifacts，保留 90 天，日記和筆記保持加密）。")
if st.button("📦 產生備份檔", key="產生備份"):
    import json as _json
    import zipfile
    檔 = io.BytesIO()
    設 = _設定()
    with zipfile.ZipFile(檔, "w", zipfile.ZIP_DEFLATED) as z:
        for 名 in ("watchlist.json", "alerts.json", "subscriptions.json", "backtest_presets.json",
                   "broker_reports.json", "influencer_notes.json"):
            try:
                內 = engine.讀取設定檔(設, 名)
                if 內:
                    z.writestr(名, _json.dumps(內, ensure_ascii=False, indent=1))
            except Exception as e:
                z.writestr(f"{名}.讀取失敗.txt", repr(e))
        for 名, 讀 in (("journal.json", lambda: engine.讀取日記(設)), ("notes.json", lambda: {"筆記": engine.讀取筆記(設)})):
            try:
                z.writestr(名, _json.dumps(讀(), ensure_ascii=False, indent=1))
            except Exception as e:
                z.writestr(f"{名}.讀取失敗.txt", repr(e))
    st.session_state["備份檔"] = 檔.getvalue()
if st.session_state.get("備份檔"):
    st.download_button("⬇️ 下載備份 zip", st.session_state["備份檔"], file_name=f"台股觀測備份_{dt.date.today():%Y%m%d}.zip",
                       mime="application/zip", key="下載備份")
