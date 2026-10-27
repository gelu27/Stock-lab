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
