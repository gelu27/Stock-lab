# 05 月營收：由 app.py 的 執行頁面() 在同一個命名空間執行，可直接用 app.py 的共用函式與資料。
def 色階(樣式, 表, 欄們):
    """明細色階：成長率、EPS、ROE 正的越大越紅、負的越大越綠；營收、市值越大底色越藍（用對數，才不會只有前幾名有顏色）。"""
    上限 = {"月增%": 100, "年增%": 100, "累計年增%": 100, "近3月年增%": 100, "合計年增%": 50, "年增中位數%": 50,
            "ROE%": 30, "連增月數": 12}
    def 漲跌底(v, 頂):
        if pd.isna(v) or v == 0 or not 頂:
            return ""
        強 = min(abs(v) / 頂, 1) * 0.55 + 0.08
        r, g, b = (255, 59, 92) if v > 0 else (0, 214, 143)
        return f"background-color:rgba({r},{g},{b},{強:.2f})"
    def 大小底(v, 低, 高):
        if pd.isna(v) or v <= 0 or 高 <= 低:
            return ""
        強 = (np.log10(v) - 低) / (高 - 低)
        return f"background-color:rgba(0,229,255,{min(max(強, 0), 1) * 0.45:.2f})"
    for c in 欄們:
        if c not in 表 or 表[c].dropna().empty:
            continue
        if c in ("營收(億)", "市值(億)"):
            對數 = np.log10(表[c][表[c] > 0])
            低, 高 = (對數.quantile(0.05), 對數.quantile(0.99)) if len(對數) else (0, 0)
            樣式 = 樣式.map(lambda v, 低=低, 高=高: 大小底(v, 低, 高), subset=[c])
        else:
            頂 = 上限.get(c) or 表[c].abs().quantile(0.9)
            樣式 = 樣式.map(lambda v, 頂=頂: 漲跌底(v, 頂), subset=[c])
    return 樣式


# ---------- 05 主動式 ETF ----------
def 營收走勢圖(代號, 月份):
    """月營收明細點一列：近 24 個月營收（柱）與年增率（線）。"""
    歷史 = engine.讀取營收歷史(代號)
    if 歷史 is None or 歷史.empty:
        return
    歷史 = 歷史[歷史["month"] <= 月份].copy()
    歷史["去年"] = 歷史["month"].map(lambda m: f"{int(m[:4]) - 1}{m[4:]}").map(dict(zip(歷史["month"], 歷史["revenue"])))
    歷史["年增"] = np.where(歷史["去年"] >= 1000, (歷史["revenue"] / 歷史["去年"] - 1) * 100, np.nan)
    近 = 歷史.tail(24)
    名 = 市場名稱.get(代號, "")
    a, b = st.columns([3, 1])
    a.markdown(f"**📊 {代號} {名}　近 {len(近)} 個月營收**")
    if b.button("看個股頁 →", key="營收前往個股", width="stretch"):
        前往(代號)
        st.rerun()
    圖 = make_subplots(specs=[[{"secondary_y": True}]])
    最高 = 歷史["revenue"].iloc[:-1].tail(60).max() if len(歷史) > 1 else np.nan
    色們 = [紅 if (i == len(近) - 1 and v > 最高) else 青 for i, v in enumerate(近["revenue"])]
    圖.add_trace(go.Bar(x=近["month"], y=近["revenue"] / 1e5, name="營收(億)", marker_color=色們, opacity=0.75,
                        hovertemplate="%{x}<br>營收 %{y:,.1f} 億<extra></extra>"), secondary_y=False)
    圖.add_trace(go.Scatter(x=近["month"], y=近["年增"], name="年增%", mode="lines+markers",
                            line=dict(color="#FFB020", width=2), hovertemplate="年增 %{y:+.1f}%<extra></extra>"),
                 secondary_y=True)
    圖表外觀(圖, 高=320)
    圖.update_yaxes(title_text="億", secondary_y=False, gridcolor="#151515")
    圖.update_yaxes(title_text="年增%", secondary_y=True, showgrid=False, zeroline=True, zerolinecolor="#444")
    圖.update_layout(hovermode="x unified", bargap=0.25)
    st.plotly_chart(圖, width="stretch", config={"displayModeBar": False})
    st.caption("最後一根紅色＝創近 5 年新高。黃線是年增率（去年同月營收不到 100 萬時不畫）。")


def 金融獲利區():
    t = engine.金融股獲利表()
    if t.empty:
        st.caption("金融股財報資料還沒抓到。")
        return
    t = t.reset_index(names="代號")
    t["股票"] = t["代號"] + " " + t["代號"].map(市場名稱).fillna("")
    收盤 = 今日.set_index("代號")["收盤"]
    t["本益比"] = (收盤.reindex(t["代號"]).values / t["近四季EPS"].where(t["近四季EPS"] > 0)).round(1)
    排序 = st.segmented_control("排序", ["近四季EPS", "累計EPS年增%", "單季EPS年增%"], default="近四季EPS", key="金融排序",
                              label_visibility="collapsed") or "近四季EPS"
    t = t.sort_values(排序, ascending=False, na_position="last")
    欄 = ["代號", "股票", "季度", "單季EPS", "去年同季EPS", "單季EPS年增%", "累計EPS", "去年同期累計EPS", "累計EPS年增%",
         "近四季EPS", "本益比", "單季淨利(億)"]
    輸出 = t[欄]
    點選表(輸出, 色階(輸出.style, 輸出, ["單季EPS年增%", "累計EPS年增%"]).format(
        {c: "{:,.2f}" for c in ("單季EPS", "去年同季EPS", "累計EPS", "去年同期累計EPS", "近四季EPS")}
        | {"單季EPS年增%": "{:+,.0f}", "累計EPS年增%": "{:+,.0f}", "本益比": "{:.1f}", "單季淨利(億)": "{:,.1f}"},
        na_rep="—"), "金融獲利表", height=min(35 * (len(輸出) + 1) + 3, 600), column_config={"代號": None})
    st.caption("金融股（金控、銀行、保險、證券）的營收包含投資、匯兌損益，波動很大，看「賺多少錢」比較準。"
               "累計＝今年到最新一季合計；年增用去年同期比；去年同期是虧損或接近 0 時年增會很誇張，顯示「—」或很大的數字要小心。"
               "金控每月 10 日左右也會自結公布當月獲利，網站目前只有每季財報。點一列可到個股查詢。")


@st.cache_data(max_entries=4, show_spinner=False)
def _月營收資料(月份, _資料版本, 程式版本):
    表, 月份們 = engine.月營收總表(月份)
    return 表, 月份們, engine.近四季EPS表()


def 月營收資料(月份, 資料版本):
    """程式（engine.py）更新後要重算，不然網站沿用舊暫存會少欄位。"""
    return _月營收資料(月份, 資料版本, os.path.getmtime(engine.__file__))


段落("MONTHLY REVENUE // 月營收")
_, 月份們, _ = 月營收資料(None, _版本)
if not 月份們:
    st.info("月營收資料還沒抓到。資料每個交易日晚上自動更新。")
    st.stop()
a, b = st.columns([1, 2])
月份 = a.selectbox("營收月份", 月份們, key="營收月份")
營收, _, EPS表 = 月營收資料(月份, _版本)
查 = b.text_input("查代號／名稱", placeholder="如 2408 或 南亞科", key="營收查詢").strip()
快選們 = ["★ 5 年新高", "連續年增 ≥ 3 月", "年增 > 20%", "自選股"]
快選 = st.pills("快速篩選", 快選們, selection_mode="multi", key="營收快選", label_visibility="collapsed") or []
已套用 = sum(st.session_state.get(k, "全部") != "全部" for k in ("營收公告日", "營收產業", "營收規模"))
with st.expander(f"🔍 更多篩選{f'（已套用 {已套用} 項）' if 已套用 else ''}"):
    a, b, c = st.columns(3)
    公告日們 = sorted(營收["公告日"].dropna().loc[lambda s: s != ""].unique(), reverse=True)
    公告 = a.selectbox("公告日", ["全部"] + list(公告日們), key="營收公告日")
    產業們 = sorted(x for x in engine._股本表()["產業"].dropna().unique() if x)
    產業 = b.selectbox("產業", ["全部"] + 產業們, key="營收產業")
    規模 = c.selectbox("規模", ["全部", "大型股", "中型股", "小型股", "微型股"], key="營收規模",
                     help="依上市櫃公司市值排名：大型股＝前 50 名（約等於台灣 50）、中型股＝51～150 名（約等於中型 100）、"
                          "小型股＝151～500 名、微型股＝500 名以後。")
    排除 = st.checkbox("排除基期過低", value=True, key="營收排除基期",
                     help="上個月（或去年同期）營收不到 1,000 萬時，成長率會出現幾萬 % 的極端值，勾選後這些百分比顯示「—」並排到最後。")

表 = 營收.join(EPS表, how="left")
股本 = engine._股本表()
表["產業"] = 股本["產業"].reindex(表.index).fillna("")
收盤 = 今日.set_index("代號")["收盤"]
淨值比 = 今日.set_index("代號")["淨值比"] if "淨值比" in 今日.columns else pd.Series(dtype=float)
每股淨值 = (收盤 / 淨值比.where(淨值比 > 0)).reindex(表.index)
表["ROE%"] = (表["近四季EPS"] / 每股淨值 * 100).round(1)
表["市值(億)"] = (收盤.reindex(表.index) * 股本["發行股數"].reindex(表.index) / 1e8).round(0)
名次 = 表["市值(億)"].rank(ascending=False, method="first")
表["規模"] = pd.cut(名次, [0, 50, 150, 500, np.inf], labels=["大型股", "中型股", "小型股", "微型股"]).astype(str)
if 排除:
    表.loc[表["月增基期低"], "月增"] = np.nan
    表.loc[表["年增基期低"], "年增"] = np.nan
    表.loc[表["累計基期低"], "累計年增"] = np.nan
表 = 表.reset_index().rename(columns={"code": "代號"})
表["名稱"] = 表["代號"].map(市場名稱).fillna("") + np.where(表["五年新高"], " ★", "")
表 = 表.rename(columns={"月增": "月增%", "年增": "年增%", "累計年增": "累計年增%", "累計EPS試算": "今年EPS試算",
                      "近3月年增": "近3月年增%"})
表["營收(億)"] = 表["營收"] / 1e5
全部 = 表
if 公告 != "全部":
    表 = 表[表["公告日"] == 公告]
if 產業 != "全部":
    表 = 表[表["產業"] == 產業]
if 規模 != "全部":
    表 = 表[表["規模"] == 規模]
範圍 = 表  # 產業概況用：只套用「更多篩選」裡的規模、公告日
if 查:
    表 = 表[表["代號"].str.startswith(查) | 表["名稱"].str.contains(查, regex=False)]
if "★ 5 年新高" in 快選:
    表 = 表[表["五年新高"]]
if "連續年增 ≥ 3 月" in 快選:
    表 = 表[表["連增月數"] >= 3]
if "年增 > 20%" in 快選:
    表 = 表[表["年增%"] > 20]
if "自選股" in 快選:
    自選 = {str(c) for 群 in 自選股清單().values() for c in 群}
    表 = 表[表["代號"].isin(自選)]

年增 = 全部["年增%"].dropna()
卡片格([卡片(f"{月份} 已公布", f"{len(全部)} 家", f"年增中位數 {年增.median():+.1f}%"),
       卡片("年增為正", f"{(年增 > 0).mean() * 100:.0f}%", f"{int((年增 > 0).sum())} 家較去年成長",
            漲跌色((年增 > 0).mean() - 0.5)),
       卡片("近 5 年新高 ★", f"{int(全部['五年新高'].sum())} 家",
            f"連續年增 ≥ 12 個月 {int((全部['連增月數'] >= 12).sum())} 家")])

st.caption("🏦 金融股的月營收包含投資損益，常常大起大落，年增率參考價值低，請改看「金融股看獲利」分頁。")
明細頁, 產業頁, 金融頁 = st.tabs(["📋 個股明細", "🏭 產業概況", "🏦 金融股看獲利"])
with 金融頁:
    金融獲利區()
with 明細頁:
    欄位們 = {"營收": ["營收(億)"], "月增": ["月增%"], "年增": ["年增%"], "近3月": ["近3月年增%"], "連增": ["連增月數"],
            "累計": ["累計年增%"], "EPS": ["近四季EPS"], "EPS試算": ["單月EPS試算", "今年EPS試算"], "ROE": ["ROE%"],
            "市值": ["市值(億)"]}
    顯示 = st.pills("欄位", list(欄位們), selection_mode="multi", default=["營收", "月增", "年增", "連增"],
                  key="營收欄位", label_visibility="collapsed") or ["營收"]
    欄 = [c for k in 欄位們 if k in 顯示 for c in 欄位們[k]]
    a, b = st.columns([2, 1])
    排序 = a.selectbox("排序", 欄, key="營收排序") if len(欄) > 1 else 欄[0]
    方向 = b.segmented_control("順序", ["大→小", "小→大"], default="大→小", key="營收順序") or "大→小"
    表 = 表.sort_values(排序, ascending=方向 == "小→大", na_position="last")
    st.caption(f"符合 {len(表)} 檔　·　點一列看近 24 個月營收走勢")
    輸出 = 表.assign(股票=表["代號"] + " " + 表["名稱"], 規模=表["規模"].str[0].replace("n", "—"))[["代號", "股票", "規模"] + 欄]
    百分比 = [c for c in ("月增%", "年增%", "近3月年增%", "累計年增%") if c in 欄]
    樣式 = 色階(輸出.style, 輸出, 欄).format(
        {"市值(億)": "{:,.0f}", "營收(億)": "{:,.1f}", "近四季EPS": "{:,.2f}", "ROE%": "{:,.1f}", "連增月數": "{:.0f}",
         "單月EPS試算": "{:,.2f}", "今年EPS試算": "{:,.2f}", **{c: "{:+,.1f}" for c in 百分比}}, na_rep="—")
    def 選了(代號):
        st.session_state["營收走勢"] = 代號
    點選表(輸出, 樣式, "營收表", 動作=選了, height=min(35 * (len(輸出) + 1) + 3, 700),
           column_config={"代號": None, "規模": st.column_config.TextColumn("規模", width="small",
                          help="市值排名：大＝前 50、中＝51～150、小＝151～500、微＝500 名以後")})
    if st.session_state.get("營收走勢"):
        營收走勢圖(st.session_state["營收走勢"], 月份)
with 產業頁:
    群 = 範圍[範圍["產業"] != ""].groupby("產業")
    概況 = pd.DataFrame({
        "家數": 群.size(),
        "合計年增%": (群["營收"].sum() / 群["去年同月營收"].sum() - 1) * 100,
        "年增中位數%": 群["年增%"].median(),
        "年增為正%": 群["年增%"].apply(lambda s: (s.dropna() > 0).mean() * 100 if s.notna().any() else np.nan),
        "近3月年增%": 群["近3月年增%"].median(),
        "5年新高": 群["五年新高"].sum(),
        "營收(億)": 群["營收"].sum() / 1e5,
    }).reset_index().sort_values("合計年增%", ascending=False)
    st.caption("合計年增＝整個產業營收加總比去年同月；年增中位數比較不會被單一大公司左右。只套用「更多篩選」裡的公告日、規模條件。")
    表格(色階(概況.style, 概況, ["合計年增%", "年增中位數%", "近3月年增%", "營收(億)"])
                 .format({"合計年增%": "{:+.1f}", "年增中位數%": "{:+.1f}", "年增為正%": "{:.0f}",
                          "近3月年增%": "{:+.1f}", "營收(億)": "{:,.0f}", "5年新高": "{:.0f}"}, na_rep="—"),
                 hide_index=True, width="stretch", height=min(35 * (len(概況) + 1) + 3, 700))
最新季 = EPS表["EPS季度"].mode()
with st.expander("ℹ️ 欄位說明"):
    st.markdown(
        "- **月增、年增、累計年增**：最新月份用交易所公布的數字，以前月份用資料庫自己算。\n"
        "- **近3月年增**：最近 3 個月營收合計比去年同期，比單月穩，不受春節等月份錯開影響。\n"
        "- **連增月數**：年增率連續為正的月數（最多看 24 個月；缺資料的月份跳過）。\n"
        "- **★ 5 年新高**：單月營收比前 5 年（至少 12 個月可比）每個月都高。\n"
        "- **公告日**：網站每天 18:00 更新時第一次抓到的日期（晚上才公布的會記成隔天；功能上線前公布的顯示「—」）。\n"
        f"- **近四季 EPS**：最近連續四季合計（最新財報 {最新季.iloc[0] if len(最新季) else '—'}）；"
        "**ROE** = 近四季 EPS ÷ 每股淨值（收盤 ÷ 股價淨值比）。\n"
        "- **EPS 試算**（只算最新月份）：單月 EPS ≈ 當月營收 × 近四季「每 1 元營收賺的 EPS」；今年 EPS 試算 = 今年已公布累計 EPS"
        " ＋ 之後各月試算。只是粗估，回測誤差中位數約 2～4 成；金融股不試算。\n"
        "- **規模**：大＝市值前 50 名、中＝51～150 名、小＝151～500 名、微＝500 名以後。\n"
        "- **色階**：紅色越深成長越多、綠色越深衰退越多；營收、市值越大底色越藍。")
