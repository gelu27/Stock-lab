# 03 個股查詢：由 app.py 的 執行頁面() 在同一個命名空間執行，可直接用 app.py 的共用函式與資料。
@st.cache_data(ttl=43200, show_spinner=False, max_entries=50)
def 借券資料(代號, 版本鍵):
    return engine.讀取借券(代號)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=100)
def 抓新聞(代號, 名稱):
    return engine.個股新聞(代號, 名稱)


def 毛利卡片(r):
    """單季毛利率、營益率，並標出比上一季、去年同季是提升還是降低。"""
    if pd.isna(r.get("毛利率", np.nan)):
        return []
    def 變化(v, 名):
        if pd.isna(v):
            return f"{名} —"
        return f"{名} {'▲ 提升' if v > 0 else ('▼ 降低' if v < 0 else '持平')} {abs(v):.1f} 個百分點"
    季增, 年增 = r.get("毛利率季增"), r.get("毛利率年增")
    主 = 季增 if pd.notna(季增) else (年增 if pd.notna(年增) else 0)
    季度 = str(r.get("毛利率季度") or "")
    return [
        卡片(f"毛利率 · {季度[:4]} Q{季度[-1:]}", f"{r['毛利率']:.1f}%",
             變化(季增, "較上季") + "<br>" + 變化(年增, "較去年同季"), 漲跌色(主)),
        卡片(f"營業利益率 · {季度[:4]} Q{季度[-1:]}", f"{r['營益率']:.1f}%" if pd.notna(r.get("營益率")) else "—",
             變化(r.get("營益率季增"), "較上季") + "<br>" + 變化(r.get("營益率年增"), "較去年同季"),
             漲跌色(r.get("營益率季增") if pd.notna(r.get("營益率季增")) else 0)),
    ]


def ROE資料(代號, r):
    """ROE = 近四季 EPS ÷ 每股淨值（收盤 ÷ 股價淨值比）；去年同期用一年前的淨值比換算。"""
    四季, 季度, 去年四季 = engine.近四季EPS(代號)
    淨值比 = r.get("淨值比")
    現在 = 四季 / (r["收盤"] / 淨值比) * 100 if pd.notna(四季) and pd.notna(淨值比) and 淨值比 > 0 else np.nan
    全 = 個股全史(代號, _版本)
    舊 = 全[全["date"] <= 最新日 - pd.Timedelta(days=365)].tail(1) if 全 is not None else pd.DataFrame()
    以前 = np.nan
    if pd.notna(去年四季) and len(舊) and 舊["淨值比"].iloc[0] > 0:
        # 一年前的每股淨值是舊股數，期間有面額分割要換成現在的股數（EPS 已換過）
        以前 = 去年四季 / (舊["收盤"].iloc[0] / 舊["淨值比"].iloc[0] / engine.分割倍數(代號, 舊["date"].iloc[0])) * 100
    return 現在, 以前, 季度, 四季


def ROE卡片(代號, r):
    現在, 以前, 季度, 四季 = ROE資料(代號, r)
    if pd.isna(現在):
        return []
    差 = 現在 - 以前
    小字 = (f"較去年同期 {'▲ 提升' if 差 > 0 else '▼ 降低'} {abs(差):.1f} 個百分點" if pd.notna(差) else "較去年同期 —")
    return [卡片(f"ROE（近四季）· 至 {季度[:4]} Q{季度[-1]}", f"{現在:.1f}%",
                 f"{小字}<br>近四季 EPS {四季:.2f}", 漲跌色(差 if pd.notna(差) else 0))]


def PDF按鈕(代號, r, 建議, 內文, 時間):
    """先按「產生 PDF」做檔（要畫圖，約數秒），做好再出現下載按鈕。"""
    鍵 = f"PDF_{代號}_{時間}"
    if 鍵 not in st.session_state:
        if st.button("📄 產生 PDF 報告（含圖表）", key=f"PDF按鈕{代號}"):
            with st.spinner("產生 PDF 中…"):
                try:
                    st.session_state[鍵] = 做PDF(代號, r, 建議, 內文, 時間)
                except Exception as 錯:
                    st.error(f"PDF 產生失敗：{錯}")
    if 鍵 in st.session_state:
        st.download_button("⬇️ 下載 PDF 報告", st.session_state[鍵], file_name=f"{代號}_{r['名稱']}_個股分析_{時間[:10]}.pdf",
                           mime="application/pdf", key=f"PDF下載{代號}", type="primary")


def 預估EPS區(r):
    """FORWARD // 三個來源的今年、明年預估 EPS，算預估本益比，跟已公布累計 EPS 對照。"""
    g = lambda k: r.get(k, np.nan)
    if pd.isna(g("預估EPS今年")) and pd.isna(g("預估Vera今年")):
        return
    年 = int(g("預估年度"))
    日 = pd.Timestamp(g("預估資料日"))
    段落(f"FORWARD // 預估 EPS 與預估本益比（資料日 {日:%Y-%m-%d}）")
    分歧 = g("預估分歧%")
    卡們 = [
        卡片(f"{年} 預估 EPS", 數(g("預估EPS今年")), f"{int(g('預估來源數') or 0)} 個來源" +
             (f"，兩源差 {分歧:.0f}%" if pd.notna(分歧) else ""), 紅 if pd.notna(分歧) and 分歧 > engine.預估分歧門檻 else "#EDEDED"),
        卡片(f"{年} 預估本益比", 數(g("預估本益比"), "{:.1f}", " 倍"), f"近四季本益比 {數(r['本益比'], '{:.1f}')} 倍"),
        卡片(f"{年 + 1} 預估 EPS", 數(g("預估EPS明年")), f"成長 {數(g('明年EPS成長%'), '{:+.1f}', '%')}",
             漲跌色(g("明年EPS成長%") if pd.notna(g("明年EPS成長%")) else 0)),
        卡片(f"{年 + 1} 預估本益比", 數(g("明年預估本益比"), "{:.1f}", " 倍")),
    ]
    if pd.notna(g("隱含剩餘EPS")):
        季成長 = g("隱含季成長%")
        卡們.append(卡片("全年預估還差多少", 數(g("隱含剩餘EPS")),
                         f"已公布 {數(g('已公布累計EPS'))}（至 {g('累計至')}）" +
                         (f"，每季要比最新一季 {季成長:+.0f}%" if pd.notna(季成長) else ""),
                         漲跌色(季成長 if pd.notna(季成長) else 0)))
    修 = g("預估修正%")
    if pd.notna(修) and pd.notna(g("前期資料日")):
        卡們.append(卡片("跟上一份比", f"{修:+.1f}%", f"{pd.Timestamp(g('前期資料日')):%m/%d} 是 {數(g('前期預估EPS今年'))}" +
                         (f"，明年 {g('明年預估修正%'):+.1f}%" if pd.notna(g("明年預估修正%")) else ""), 漲跌色(修)))
    卡片格(卡們)
    表 = pd.DataFrame({"來源": ["A", "B", "Vera"],
                       f"{年} EPS": [g("預估A今年"), g("預估B今年"), g("預估Vera今年")],
                       f"{年 + 1} EPS": [g("預估A明年"), g("預估B明年"), np.nan]})
    表[f"{年} 本益比"] = (r["收盤"] / 表[f"{年} EPS"]).where(表[f"{年} EPS"] > 0)
    表[f"{年 + 1} 本益比"] = (r["收盤"] / 表[f"{年 + 1} EPS"]).where(表[f"{年 + 1} EPS"] > 0)
    表 = 表.dropna(subset=[f"{年} EPS", f"{年 + 1} EPS"], how="all")
    with st.expander("三個來源的數字"):
        表格(表.style.format({c: "{:.2f}" for c in 表.columns if "EPS" in c} | {c: "{:.1f}" for c in 表.columns if "本益比" in c},
                            na_rep="—"), hide_index=True, width="stretch")
    提醒 = []
    if g("預估低於累計") == True:
        提醒.append("今年預估比已公布的累計 EPS 還低：可能是舊預估沒更新，或預期後面幾季虧損，使用前先查證。")
    v, 今, 累 = g("預估Vera今年"), g("預估EPS今年"), g("已公布累計EPS")
    if pd.notna(v) and pd.notna(累) and 累 > 0.5 and v < 累 * 0.95:
        提醒.append(f"Vera 預估 {v:.2f} 比已公布累計 {累:.2f} 還低，這檔的 Vera 數字不採用。")
    if g("預估來源數") == 1 and pd.isna(g("預估B今年")):
        提醒.append("只有 A 來源：沒有法人研究的股票，A 的數字多半接近近四季 EPS，參考性較低。")
    for 文 in 提醒:
        st.warning(文)
    if 日 < 最新日 - pd.Timedelta(days=45):
        st.warning(f"預估資料是 {日:%m/%d} 的，已超過 45 天，可能沒反映最新財報。")
    st.caption("預估 EPS 來自使用者匯出的全市場預估（A、B、Vera 三個來源）。網站用 A、B 的中位數當共識，Vera 只列出不採用"
               "（全市場比對：Vera 有 18% 的股票全年預估比已公布累計還低，跟 A 的差距中位數 27%；A、B 只差 4%）。"
               "預估本益比每天用最新收盤重算；預估 EPS 要等使用者上傳新的一份才會更新。")


def 做PDF(代號, r, 建議, 內文, 時間):
    import report
    importlib.reload(report)  # 網站更新後確保用的是最新版的報告排版

    數 = lambda v, f="{:,.2f}", 尾="": "—" if v is None or pd.isna(v) else f.format(v) + 尾
    g = lambda k: r.get(k, np.nan)
    股數 = g("發行股數")
    比 = r["收盤"] / r["還原價"] if r["還原價"] else 1
    現, 以前, 季度, 四季 = ROE資料(代號, r)
    建議 = 建議 or {}
    合理 = 建議.get("目標價合理")
    空間 = (合理 / r["收盤"] - 1) * 100 if isinstance(合理, (int, float)) else np.nan
    卡們 = [
        ("收盤 " + 最新日.strftime("%m/%d"), 數(r["收盤"]), f"{r['漲跌幅']:+.2f}%", r["漲跌"]),
        ("AI 合理目標價", 數(合理, "{:,.0f}") if isinstance(合理, (int, float)) else "—",
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
                  ("今年預估 EPS", 數(g("預估EPS今年"))), ("預估本益比", 數(g("預估本益比"), "{:.1f}", " 倍")),
                  ("明年預估 EPS", 數(g("預估EPS明年"))),
                  ("月營收年增", 數(g("營收年增率"), 尾="%")), ("累計營收年增", 數(g("累計營收年增率"), 尾="%")),
                  ("單季毛利率", 數(g("毛利率"), 尾="%")), ("毛利率較上季", 數(g("毛利率季增"), "{:+.1f}", " pt")),
                  ("營業利益率", 數(g("營益率"), 尾="%")), ("營益率較上季", 數(g("營益率季增"), "{:+.1f}", " pt")),
                  ("營益率較去年", 數(g("營益率年增"), "{:+.1f}", " pt")),
                  ("合約負債", 數(g("合約負債億"), "{:,.1f}", " 億")), ("合約負債年增", 數(g("合約負債年增"), "{:+.1f}", "%")),
                  ("合約負債能見度", 數(g("能見度月"), "{:.1f}", " 個月"))]),
    ]
    if 有籌碼:
        基本.append(("籌碼面", [("外資", 數(r["外資買超"], "{:+,.0f}", " 張")), ("投信", 數(r["投信買超"], "{:+,.0f}", " 張")),
                             ("自營商", 數(r["自營買超"], "{:+,.0f}", " 張")), ("法人 5 日", 數(r["法人5日買超"], "{:+,.0f}", " 張")),
                             ("法人 10 日", 數(r["法人10日買超"], "{:+,.0f}", " 張")), ("外資連買", 數(r["外資連買"], "{:.0f}", " 天")),
                             ("投信連買", 數(r["投信連買"], "{:.0f}", " 天")), ("融資餘額", 數(r["融資餘額"], "{:,.0f}", " 張")),
                             ("融資 5 日", 數(r["融資5日增減"], "{:+.1f}", "%")),
                             ("融資維持率（估）", 數(r.get("融資維持率", np.nan), "{:.0f}", "%"))]))
    基本.append(("技術面", [(f"{n} 日線", 數(r[f"MA{n}"] * 比)) for n in (5, 10, 20, 60)] + [
        ("RSI(14)", 數(r["RSI"], "{:.1f}")), ("20 日漲幅", 數(r["20日漲幅"], "{:+.2f}", "%")),
        ("距 52 週高點", 數(r["距52週高點"], "{:+.1f}", "%")), ("箱頂", 數(r["箱頂"])), ("箱底", 數(r["箱底"]))]))
    資料 = {"收盤": float(r["收盤"]), "漲跌": float(r["漲跌"]), "漲跌幅": float(r["漲跌幅"]), "日期": 最新日.strftime("%Y-%m-%d"),
            "產業": g("產業"), "市場": r["市場"], "卡片": 卡們, "基本資料": 基本, "判讀": engine.規則判讀(r),
            "歷史": 個股全史(代號, _版本), "營收": engine.讀取營收歷史(代號), "損益": engine.單季損益(代號),
            "建議": 建議, "報告": 內文, "報告時間": 時間, "合約負債": engine.讀取合約負債(代號)}
    if not 代號.startswith("0"):
        try:
            資料["公司"] = 公司資料(代號)
            段 = re.search(r"#+\s*公司介紹[^\n]*\n(.*?)(?=\n#+\s|\Z)", 內文 or "", re.S)
            if 段 and not 資料["公司"]["AI介紹"]:   # 沒有另外產生公司介紹時，用 AI 報告裡的公司介紹段落
                資料["公司"] = {**資料["公司"], "AI介紹": "### 公司介紹\n" + 段.group(1).strip()}
        except Exception:
            pass
    try:
        h, 週轉, 大 = 變化資料(代號, 126)
        資料["變化"] = {"歷史": h, "週轉": 週轉, "大戶": 大, "解讀": engine.變化解讀(h, 週轉, 大)}
    except Exception:
        pass
    return report.產生PDF(代號, r["名稱"], 資料)


@st.cache_data(ttl=43200, show_spinner="查詢內部人持股歷史中…", max_entries=50)
def 內部人資料(代號):
    """先向公開資訊觀測站查近 7 個月，查不到就用資料庫每月存的。"""
    try:
        歷史 = engine.內部人歷史(代號)
        if 歷史 is not None and len(歷史):
            return 歷史
    except Exception:
        pass
    return engine.讀取內部人(代號)


@st.cache_data(ttl=43200, show_spinner="查詢集保大戶歷史中（第一次約 10～20 秒）…", max_entries=50)
def 大戶歷史(代號):
    """集保網站查過去一年每週的大戶比例，再補上資料庫裡每週存下來的。"""
    表們 = [集保資料(代號)]
    try:
        表們.append(engine.集保歷史(代號, 52))
    except Exception:
        pass
    表們 = [t for t in 表們 if t is not None and len(t)]
    if not 表們:
        return None
    return pd.concat(表們).drop_duplicates("date", keep="last").sort_values("date", ignore_index=True)


def 變化資料(代號, 天數=126):
    """FLOW 用的資料：近 N 個交易日的歷史、每日週轉率（%）、每週千張大戶。"""
    歷史 = 指標[指標["代號"] == 代號].tail(天數)
    股 = 讀檔("_股本表", _版本)
    股數 = 股.at[代號, "發行股數"] if 代號 in 股.index else np.nan
    週轉 = (歷史["volume"] * engine.分割倍數序列(代號, 歷史["date"]) / 股數 * 100 if pd.notna(股數) and 股數
            else pd.Series(np.nan, index=歷史.index))  # 分割前的成交股數換成現在的股數基準
    大 = 大戶歷史(代號)
    if 大 is not None and len(歷史):
        大 = 大[大["date"] >= 歷史["date"].iloc[0] - pd.Timedelta(days=7)]
    return 歷史, 週轉, 大


def 變化圖(代號, r, 天數):
    """一張圖看四件事：股價、週轉率、千張大戶持股比例、三大法人買賣超，下面附白話解讀。"""
    歷史, 週轉, 大 = 變化資料(代號, 天數)
    if len(歷史) < 5:
        st.caption("資料太少，畫不出變化圖。")
        return
    列們 = ["股價", "週轉率 %", "千張大戶持股 %", "三大法人買賣超（張）"]
    圖 = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.34, 0.18, 0.24, 0.24],
                       subplot_titles=列們)
    圖.add_trace(go.Scatter(x=歷史["date"], y=歷史["收盤"], name="收盤", line=dict(color=青, width=1.6)), row=1, col=1)
    圖.add_trace(go.Bar(x=歷史["date"], y=週轉, name="週轉率 %", marker_color="#FFC24B"), row=2, col=1)
    if 大 is not None and len(大):
        圖.add_trace(go.Scatter(x=大["date"], y=大["big1000"], name="千張大戶 %", mode="lines+markers",
                                line=dict(color=紅, width=1.6), marker=dict(size=5)), row=3, col=1)
    if 有籌碼:
        for 欄, 名, 色 in (("外資買超", "外資", "#4DA3FF"), ("投信買超", "投信", "#FF00E5"), ("自營買超", "自營商", "#9B9B9B")):
            圖.add_trace(go.Bar(x=歷史["date"], y=歷史[欄], name=名, marker_color=色), row=4, col=1)
    圖.update_layout(barmode="relative", xaxis_rangeslider_visible=False, showlegend=True,
                    legend=dict(orientation="h", y=-0.06, x=0))
    圖.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    圖.update_annotations(font=dict(size=11, color=灰), x=0, xanchor="left")
    圖 = 圖表外觀(圖, 720)
    圖.update_layout(legend=dict(orientation="h", y=-0.06, x=0))
    st.plotly_chart(圖, width="stretch")
    st.markdown("\n".join(f"- {x}" for x in engine.變化解讀(歷史, 週轉, 大)))
    st.caption("週轉率 = 當天成交股數 ÷ 發行股數；千張大戶 = 持有 1,000 張以上的股東合計持股比例（集保每週五公布）。"
               "股價上漲時大戶比例上升、法人買超，通常代表籌碼健康；反過來則要小心。")


def 存提醒(提醒):
    st.session_state["到價提醒"] = 提醒
    try:
        if engine.儲存提醒(提醒, _設定()):
            st.toast("到價提醒已儲存")
        else:
            st.toast("已暫存（網站重新啟動會消失；在 Secrets 設定 GITHUB_TOKEN 就能永久保存）")
    except Exception as e:
        st.error(f"到價提醒存檔失敗：{e}")


def 個股比較(代號):
    """2～4 檔股票走勢疊在一起（起點 = 100）＋評分、估值、籌碼並排。"""
    段落("COMPARE // 個股比較")
    對照 = {v.split()[0]: v for v in 股票選項}
    群 = engine.同族群(今日, 代號, 3)
    預設 = [c for c in (群["代號"].tolist() if 群 is not None else []) if c != 代號][:2]
    其他 = st.multiselect("跟哪些股票比（最多 3 檔，預設同產業市值最大的兩檔）", [v for v in 股票選項 if not v.startswith(代號 + " ")],
                        default=[對照[c] for c in 預設 if c in 對照], max_selections=3, key=f"比較_{代號}")
    代號們 = [代號] + [v.split()[0] for v in 其他]
    期間 = st.segmented_control("期間", ["1 個月", "3 個月", "6 個月", "1 年"], default="3 個月", key="比較期間",
                              label_visibility="collapsed") or "3 個月"
    起 = 最新日 - pd.DateOffset(months={"1 個月": 1, "3 個月": 3, "6 個月": 6, "1 年": 12}[期間])
    史 = 指標[(指標["代號"].isin(代號們)) & (指標["date"] >= 起)].pivot_table(index="date", columns="代號", values="還原價")
    色們 = [青, "#FFB020", "#B388FF", "#FF7AB6"]
    名 = dict(zip(今日["代號"], 今日["名稱"]))
    圖 = go.Figure()
    for i, c in enumerate(代號們):
        if c in 史 and 史[c].notna().any():
            線 = 史[c].dropna()
            圖.add_trace(go.Scatter(x=線.index, y=線 / 線.iloc[0] * 100, mode="lines", name=f"{c} {名.get(c, '')}",
                                   line=dict(color=色們[i], width=2.5 if i == 0 else 1.8)))
    圖.add_hline(y=100, line=dict(color=灰, dash="dot", width=1))
    圖.update_layout(legend=dict(orientation="h", y=1.08, x=0))
    st.plotly_chart(圖表外觀(圖, 340), width="stretch")
    st.caption("用還原股價（含配息）換算，起點都從 100 開始，100 以上代表這段期間是賺的。")
    分 = 評分資料(_版本)[0]
    t = 今日.set_index("代號").reindex(代號們)
    期間漲 = (史.ffill().iloc[-1] / 史.bfill().iloc[0] - 1) * 100 if len(史) else pd.Series(dtype=float)
    表 = pd.DataFrame({
        "股票": [f"{c} {名.get(c, '')}" for c in 代號們],
        "股價": t["收盤"].values, "今日%": t["漲跌幅"].values, f"{期間}%": 期間漲.reindex(代號們).values,
        "總分": 分["總分"].reindex(代號們).values, "看法": 分["看法"].reindex(代號們).values,
        "本益比": t["本益比"].values, "殖利率": t["殖利率"].values, "淨值比": t["淨值比"].values,
        "營收年增%": t.get("營收年增率", pd.Series(np.nan, index=t.index)).values,
        "法人5日(張)": t.get("法人5日買超", pd.Series(np.nan, index=t.index)).values,
        "產業": t["產業"].values if "產業" in t else None,
    })
    財 = 同業財務(_版本)
    毛, 四, 簡 = 財["毛"].reindex(代號們), 財["四"].reindex(代號們), 財["簡"].reindex(代號們)
    淨值 = t["收盤"] / t["淨值比"].where(t["淨值比"] > 0)
    表["毛利率%"] = 毛["毛利率"].values
    表["ROE%"] = (四["近四季EPS"] / 淨值 * 100).round(1).values
    表["主要營收"] = [str(x).split("、")[0][:24] if isinstance(x, str) and x else "—" for x in 簡["營收比重"]]
    漲欄 = ["今日%", f"{期間}%", "營收年增%", "法人5日(張)"]
    樣式 = (表.style.format({"股價": "{:,.2f}", "今日%": "{:+.2f}", f"{期間}%": "{:+.1f}", "總分": "{:.1f}",
                            "本益比": "{:.1f}", "殖利率": "{:.2f}", "淨值比": "{:.2f}", "營收年增%": "{:+.1f}",
                            "法人5日(張)": "{:+,.0f}", "毛利率%": "{:.1f}", "ROE%": "{:.1f}"}, na_rep="—")
          .map(lambda v: f"color:{漲跌色(v)}", subset=漲欄).map(lambda v: f"color:{分數色(v)}", subset=["總分"]))
    表格(樣式, hide_index=True, width="stretch", height=35 * (len(表) + 1) + 3)
    st.caption("總分是規則計分（50 為中性），僅供參考，非投資建議。毛利率是最新一季單季；ROE＝近四季 EPS ÷ 每股淨值；"
               "主要營收取公司簡介的第一大營收項目。")


@st.cache_data(ttl=43200, max_entries=1, show_spinner=False)
def 同業財務(版本鍵):
    簡 = engine.讀取公司簡介()
    return {"毛": engine.毛利率表(), "四": engine.近四季EPS表(),
            "簡": 簡 if "營收比重" in 簡 else pd.DataFrame(columns=["營收比重"])}


@st.cache_data(ttl=3600, show_spinner=False, max_entries=50)
def 集保資料(代號):
    return engine.讀取集保(代號)


def 個股K線(代號):
    """個股日 K 換成「還原」後的開高低收（最新一天等於實際股價），避免除權息被當成跳空缺口。"""
    return engine.還原K線(個股全史(代號, _版本))


@st.cache_data(ttl=43200, show_spinner="回測這檔的支撐壓力中…", max_entries=30)
def 個股價位回測(代號, 版本鍵):
    K = engine.還原K線(個股全史(代號, 版本鍵))
    if K is None or len(K) <= 300:
        return pd.DataFrame()
    歷史 = 個股全史(代號, 版本鍵)
    return engine.回測摘要(engine.支撐壓力回測(K, 歷史.set_index("date")["成交值億"]))


def 個股價位區(代號):
    K = 個股K線(代號)
    if K is None:
        st.caption("資料不足，無法計算支撐壓力。")
        return
    歷史 = 個股全史(代號, _版本)
    量 = (歷史.set_index("date")["成交值億"] if 歷史 is not None and "成交值億" in 歷史 else None)
    sr = engine.支撐壓力(K, 量=量)
    區們 = engine.共振區(sr["價位"])
    解 = engine.位置解讀(sr, 區們)
    價位卡片(sr, 解, float(K["close"].iloc[-2]))
    跌破站回條(engine.跌破站回(K, 量) + engine.技術訊號(K, 量))
    st.markdown(f'<div class="verdict">{解["文字"]}</div>', unsafe_allow_html=True)
    if 量 is not None:
        量價條(engine.量價標籤(K, 量))
    黑 = engine.黑K一半(K)
    if 黑:
        st.markdown(黑K卡(黑), unsafe_allow_html=True)
    技術 = engine.技術觀察(K, 量)
    if 技術:
        st.markdown(燈號卡(技術), unsafe_allow_html=True)
    紀 = engine.停損紀律狀態(K)
    if 紀:
        類 = {"🟢": "g", "🟡": "y", "🔴": "r"}.get(紀["燈"], "y")
        st.markdown(f'<div class="lamp {類}" style="margin:6px 0"><div class="t"><i>{紀["燈"]}</i>老王停損紀律：{紀["建議"]}</div>'
                    f'<div class="s">{紀["說明"]}</div></div>', unsafe_allow_html=True)
        with st.expander("🧪 這套紀律在這檔有用嗎？（5 年回測）"):
            停損紀律回測表(代號)
    貴 = engine.買貴檢查(歷史)
    if 貴:
        燈 = "r" if 貴["跌幅%"] <= -30 else ("y" if 貴["跌幅%"] <= -10 else "g")
        st.markdown(f'<div class="lamp {燈}" style="margin:6px 0"><div class="t"><i>💸</i>買貴檢查</div>'
                    f'<div class="s">{貴["說明"]}</div></div>', unsafe_allow_html=True)
    摘要 = 個股價位回測(代號, _版本)
    st.plotly_chart(支撐壓力圖(K, sr, 區們, 120, 420, 摘要=摘要), width="stretch", config={"displayModeBar": False})
    with st.expander("🧪 這檔的價位準不準？（5 年回測）"):
        if 摘要.empty:
            st.caption("上市不到一年半，資料不足，無法回測。")
        else:
            回測顯示(摘要)
    with st.expander("📋 完整價位表與缺口清單"):
        價位明細(sr, 區們, f"個股價位明細{代號}", 摘要)
        缺口表(K, f"個股缺口{代號}")
    with st.expander("🧮 這檔該買多少？（部位計算器）"):
        部位計算器(代號, sr)
    st.caption("用還原股價計算（除權息不會被當成缺口），最新一天等於實際股價。線的意思跟首頁「關鍵價位」相同。僅供研究參考。")


def 部位計算器(代號, sr):
    """停損時最多只賠總資金的幾 %，反推可以買幾股。停損預設用最近的支撐價。"""
    現 = float(sr["收盤"])
    下 = sr["價位"]
    下 = 下[(下["角色"] == "支撐") & (下["價位"] < 現 * 0.995)].sort_values("價位", ascending=False)
    預設停損 = round(float(下["價位"].iloc[0]) * 0.99, 2) if len(下) else round(現 * 0.92, 2)
    a, b, c = st.columns(3)
    資金 = a.number_input("總資金（元）", min_value=10000, value=1_000_000, step=100000, key="部位_資金")
    風險 = b.number_input("停損時最多賠總資金的 %", min_value=0.1, max_value=20.0, value=2.0, step=0.5, key="部位_風險")
    折扣 = c.number_input("手續費折扣", min_value=0.1, max_value=1.0, value=1.0, step=0.05, key="部位_折扣")
    a, b = st.columns(2)
    進 = a.number_input("買進價", min_value=0.01, value=現, step=0.05, format="%.2f", key=f"部位_進{代號}")
    停 = b.number_input("停損價", min_value=0.01, value=預設停損, step=0.05, format="%.2f", key=f"部位_停{代號}",
                       help="預設＝最近一個支撐價再往下 1%（跌破支撐才出場）；找不到支撐就用 −8%")
    r = engine.部位建議(資金, 風險 / 100, 進, 停, 代號, 折扣)
    if not r:
        st.warning("停損價要低於買進價。")
        return
    卡片格([
        卡片("建議買進", f"{r['張']} 張" + (f" {r['零股']} 股" if r["零股"] else ""), f"共 {r['股數']:,} 股", 青),
        卡片("投入金額", f"{r['金額']:,.0f}", f"占資金 {r['占資金%']:.1f}%"),
        卡片("跌到停損會賠", f"{r['最多虧損']:,.0f}", f"停損幅度 {r['停損幅度%']:.1f}%（含手續費與稅）", 綠),
    ])
    st.caption(f"算法：可賠金額 {r['可賠']:,.0f} 元 ÷ 每股風險 {r['每股風險']:.2f} 元（買進價 − 停損價 ＋ 買賣手續費 ＋ 證交稅）。"
               "停損越近可以買越多、停損越遠就要買少一點；錢不夠時以總資金為上限。很多交易者把每筆風險控制在總資金的 1%～2%。")


@st.cache_data(ttl=3600, show_spinner="回測中…")
def 停損紀律回測資料(代號, 版本鍵):
    return engine.停損紀律回測(個股全史(代號, 版本鍵))


def 停損紀律回測表(代號):
    t = 停損紀律回測資料(代號, _版本)
    if t.empty:
        st.caption("資料不足，無法回測。")
        return
    表格(t, hide_index=True, width="stretch",
                 column_config={"總報酬%": st.column_config.NumberColumn(format="%+.1f"),
                                "最大回檔%": st.column_config.NumberColumn(format="%.1f")})
    抱, 老 = t.iloc[0], t.iloc[2]
    話 = ("在這檔，紀律的報酬比一直抱著好" if 老["總報酬%"] > 抱["總報酬%"] else "在這檔，一直抱著的報酬比較高，紀律常被洗出場")
    話 += ("，但最大回檔比較小，抱得比較安心。" if 老["最大回檔%"] > 抱["最大回檔%"] + 3 else "，回檔也沒有明顯變小。")
    st.markdown(f'<div class="verdict sub">{話}</div>', unsafe_allow_html=True)
    st.caption(f"從 {t.attrs.get('起', pd.NaT):%Y/%m/%d} 起算。進場都是收盤站上 5、10、20 日線；訊號收盤產生、隔天收盤成交，已扣手續費與證交稅。"
               "停損紀律的好處是避開大跌，代價是盤整時被來回洗、手續費變多；適合短線操作，長期好公司不一定適用。")


@st.cache_data(ttl=3600, show_spinner=False, max_entries=30)
def 外資持股歷史(代號, 版本鍵):
    q = engine.讀取外資持股()
    return None if q is None else q[q["code"] == 代號][["date", "ratio"]].sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=30)
def 當沖資料(代號, 版本鍵):
    """這檔每天的當沖比率（當沖成交股數 ÷ 成交股數，%），只有上市股票。"""
    d = engine.讀取當沖()
    if d is None:
        return None
    d = d[d["code"] == 代號]
    史 = 個股全史(代號, 版本鍵)
    if not len(d) or 史 is None:
        return None
    t = d.merge(史[["date", "成交張數"]], on="date")
    t["比率"] = (t["shares"] / 1000 / t["成交張數"] * 100).where(t["成交張數"] > 0)
    return t.dropna(subset=["比率"])[["date", "比率", "shares"]].sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=30)
def 財報資料(代號, 版本鍵):
    t = engine.讀取財報(代號)
    return None if t is None or not len(t) else t.sort_values("quarter").reset_index(drop=True)


def 個股事件(代號):
    """這檔近一年的公司事件：庫藏股、可轉債、公開申購（初上市櫃、現金增資）。回傳 DataFrame（日期、事件、內容）。"""
    列們 = []
    庫 = 讀檔("讀取庫藏股", _版本)
    if 庫 is not None:
        for _, x in 庫[庫["code"] == 代號].iterrows():
            狀態 = "已執行完畢" if str(x["done"]).upper() == "Y" else "執行中"
            列們.append({"日期": x["board_date"], "事件": "🛒 庫藏股",
                        "內容": f"預定買回 {x['planned'] / 1000:,.0f} 張，價格 {x['price_low']:g}～{x['price_high']:g} 元，"
                               f"期間 {x['start']:%m/%d}～{x['end']:%m/%d}（{狀態}"
                               + (f"，已買回 {x['bought'] / 1000:,.0f} 張、均價 {x['avg_price']:g} 元" if pd.notna(x["bought"]) else "")
                               + "）"})
    債 = 讀檔("讀取可轉債", _版本)
    if 債 is not None:
        for _, x in 債[債["code"] == 代號].iterrows():
            列們.append({"日期": x["issue_date"], "事件": "📜 可轉債",
                        "內容": str(x["name"]) + (f"，發行 {x['amount'] / 1e8:,.1f} 億元" if pd.notna(x["amount"]) else "")
                               + (f"，轉換價 {x['conv_price']:g} 元" if pd.notna(x["conv_price"]) else "")})
    申 = 讀檔("讀取新股申購", _版本)
    if 申 is not None:
        for _, x in 申[申["code"] == 代號].iterrows():
            列們.append({"日期": x["draw_date"], "事件": "🎫 " + ("現金增資" if "增資" in str(x["market"]) else "公開申購"),
                        "內容": f"{x['market']}，承銷價 {x['price']:g} 元、{x['shares'] / 1000:,.0f} 張，"
                               f"申購 {x['start']:%m/%d}～{x['end']:%m/%d}，抽籤 {x['draw_date']:%m/%d}"
                               + (f"，中籤率 {x['win_rate']:g}%" if pd.notna(x["win_rate"]) and x["win_rate"] else "")})
    轉 = 讀檔("讀取內部人轉讓", _版本)
    if 轉 is not None:
        for _, x in 轉[轉["code"] == 代號].iterrows():
            列們.append({"日期": x["date"], "事件": "🧾 董監轉讓",
                        "內容": f"{x['身分']} {x['姓名']} 申報{str(x['方式']).split('(')[0]} {x['股數'] / 1000:,.0f} 張"
                               + (f"（佔其持股 {x['股數'] / x['持股'] * 100:.0f}%）" if x["持股"] else "") + f"，期間 {x['期間']}"})
    if not 列們:
        return None
    t = pd.DataFrame(列們).dropna(subset=["日期"]).sort_values("日期", ascending=False)
    return t[t["日期"] >= pd.Timestamp.now() - pd.Timedelta(days=400)]


def 個股重大訊息(代號):
    """總覽分頁：這檔近 120 天的重大訊息（公開資訊觀測站）。"""
    try:
        訊 = 讀檔("讀取全部重訊", _版本, 代號)
    except Exception:
        訊 = None
    段落("MOPS // 重大訊息（公開資訊觀測站，近 120 天）")
    if 訊 is None:
        st.caption("目前沒有這檔的重大訊息紀錄（每天收盤後更新時累積，剛開始只有最近幾天的）。")
        return
    顯示 = 訊.assign(日期=訊["date"].dt.strftime("%Y/%m/%d"), 時間=訊["time"].astype(str).str[:5])[["日期", "時間", "subject"]]
    表格(顯示.rename(columns={"subject": "主旨"}).head(30), hide_index=True, width="stretch",
         column_config={"主旨": st.column_config.TextColumn(width="large")})
    st.caption("公司自己發的正式公告，比新聞早也比新聞準；完整內容到公開資訊觀測站用代號查詢。"
               "加入自選股後，有新的重大訊息會在每天收盤 LINE 通知。")


def 海外布局區(代號):
    """基本面分頁：data/overseas.csv 有整理的公司（目前是台積電）才顯示海外廠、合資與轉投資。"""
    t = 讀檔("讀取海外布局", _版本, 代號)
    if t is None:
        return
    段落("GLOBAL // 海外布局、合資與轉投資")
    顯示 = t.rename(columns={"item": "項目", "region": "地區", "kind": "性質", "stake": "持股", "invest": "投資金額",
                            "timeline": "時程", "status": "狀態", "note": "說明", "source": "來源"})
    表格(顯示.drop(columns="code"), hide_index=True, width="stretch",
         column_config={"說明": st.column_config.TextColumn(width="large")})
    st.caption("自己整理的資料（data/overseas.csv，可直接在 GitHub 上修改或增加其他公司）。台積電沒有控制權的合資公司"
               "（例如與 Sony 合資的熊本影像感測器廠）不會併入營收，只會在「業外」認列投資損益；持股比例以公司年報為準。")


def 業外損益區(代號):
    """基本面分頁：各季業外收支（含採權益法認列的合資、轉投資損益）與占稅前淨利比例。"""
    t = 讀檔("業外損益", _版本, 代號)
    if t is None or not len(t):
        return
    段落("NON-OP // 業外損益：合資、轉投資賺多少")
    近 = t.tail(8)
    最 = 近.iloc[-1]
    卡片格([
        卡片("最新一季業外", 數(最["業外收支(億)"], "{:+,.1f}", " 億"), 最["季度"], 漲跌色(最["業外收支(億)"] or 0)),
        卡片("業外占稅前", 數(最["業外占稅前%"], "{:.1f}", "%"), "超過 30% 代表獲利很靠本業以外",
             "#FFC24B" if abs(最["業外占稅前%"] or 0) >= 30 else "#EDEDED"),
        卡片("近四季業外", 數(近["業外收支(億)"].tail(4).sum(), "{:+,.1f}", " 億"), "", 漲跌色(近["業外收支(億)"].tail(4).sum())),
    ])
    圖 = go.Figure([go.Bar(x=近["季度"], y=近["營業利益(億)"], name="營業利益（億）", marker_color=青),
                    go.Bar(x=近["季度"], y=近["業外收支(億)"], name="業外收支（億）", marker_color="#FFB020")])
    圖.update_layout(barmode="relative", legend=dict(orientation="h", y=1.12))
    st.plotly_chart(圖表外觀(圖, 240), width="stretch")
    st.caption("業外收支＝稅前淨利 − 營業利益，包含採權益法認列的合資、轉投資損益，也包含利息、匯兌、處分資產等。"
               "合資公司剛成立、還沒量產時常常是虧損，會先拖累業外；業外比重很高時，EPS 比較不能代表本業實力。"
               "資料：公開資訊觀測站綜合損益表彙總（單季由今年累計數相減）。")


def 投資金額換算區(代號, r):
    """基本面分頁：新聞裡的投資金額（外幣）換成台幣，再看占營收、資本支出、淨值、市值多少。"""
    with st.expander("🧮 新聞裡的投資金額有多大？（換算成占公司營收、資本支出的比例）"):
        美元 = None
        try:
            fx = engine.讀取匯率()
            美元 = float(fx["usdtwd"].dropna().iloc[-1]) if fx is not None and len(fx) else None
        except Exception:
            pass
        預設匯率 = {"台幣": 1.0, "美元": round(美元 or 32.0, 2), "日圓": 0.21, "歐元": 35.0, "人民幣": 4.4}
        a, b, c = st.columns([2, 1, 1])
        金額 = a.number_input("金額（單位：億）", 0.0, 1e7, 2820.0, step=10.0, key="換算金額")
        幣 = b.selectbox("幣別", list(預設匯率), index=2, key="換算幣別")
        匯率 = c.number_input("匯率（1 單位外幣＝幾元台幣）", 0.0001, 1000.0, 預設匯率[幣], step=0.01, format="%.4f",
                            key=f"換算匯率_{幣}")
        規模 = engine.財務規模(代號)
        台幣, 表 = engine.投資金額換算(金額, 匯率, 規模, r.get("市值億"))
        st.markdown(f"**{金額:,.0f} 億{幣} ≈ 台幣 {台幣:,.0f} 億元**")
        if len(表):
            表格(表.style.format({"金額(億)": "{:,.0f}", "占比%": "{:.1f}"}, na_rep="—"), hide_index=True, width="stretch")
        st.caption("預設是台積電與 Sony 合資的 2,820 億日圓，換成其他新聞的數字就能比較。美元匯率用資料庫最新一天，"
                   "其他幣別是約略值，請自己改成當天匯率。資本支出用「近四季投資現金流」近似，會包含買賣金融資產。"
                   "占比不到 5% 通常對公司財務影響不大；分好幾年投入的話，影響還要再除以年數。")


def AI設定():
    """回傳 (引擎, 金鑰, 模型, 可執行)：有 Gemini 金鑰用 Gemini，否則用 Claude；有密碼時要先解鎖才能用。"""
    設定 = _設定()
    if str(設定.get("GEMINI_API_KEY", "")).strip():
        引擎, 金鑰, 模型 = "Gemini", engine.清理金鑰(設定["GEMINI_API_KEY"]), str(設定.get("GEMINI_MODEL", "gemini-flash-latest"))
    else:
        引擎, 金鑰, 模型 = "Claude", engine.清理金鑰(設定.get("ANTHROPIC_API_KEY")), str(設定.get("AI_MODEL", "claude-opus-5-5"))
    return 引擎, 金鑰, 模型, bool(金鑰) and 可編輯()


def 公司介紹區(代號, r):
    段落("COMPANY // 公司介紹：做什麼、靠什麼賺錢、規模多大")
    if 代號.startswith("0"):
        st.caption("ETF 沒有公司介紹，成分股請看「06 / 主動式 ETF」或發行投信網站。")
        return
    資 = 公司資料(代號)
    簡, 規 = 資["簡介"], 資["規模資料"]
    卡們 = [卡片("產業", r.get("產業") or "—", r["市場"])]
    if 規:
        卡們 += [卡片("市值", f"{規['市值億']:,.0f} 億", f"全市場第 {規['市值排名']:,} 名"),
                卡片("同業市值排名", "—" if not 規.get("同業市值排名") else f"第 {規['同業市值排名']} / {規['同業家數']}",
                     "🏆 產業市值龍頭" if 規.get("同業市值排名") == 1 else 規["產業"], 紅 if 規.get("同業市值排名") == 1 else "#EDEDED")]
        if 規.get("近12月營收億"):
            卡們.append(卡片("近 12 月營收", f"{規['近12月營收億']:,.0f} 億",
                           f"同業第 {規['同業營收排名']} 名" if 規.get("同業營收排名") else ""))
    if 簡.get("董事長"):
        卡們.append(卡片("董事長 / 總經理", 簡.get("董事長", "—"), 簡.get("總經理", "")))
    if 簡.get("成立日期") or 簡.get("上市日期"):
        卡們.append(卡片("成立 / 上市", 簡.get("成立日期") or "—", f"上市櫃 {簡.get('上市日期') or '—'}"))
    卡片格(卡們)
    if 資["業務"]:
        st.markdown(f'<div class="verdict sub"><b>主要經營業務</b>　{資["業務"]}</div>', unsafe_allow_html=True)
    if 資["概念"]:
        st.caption("🏷️ " + 資["概念"])
    比 = 資["比重表"]
    if len(比):
        顯 = 比.head(8)
        if len(比) > 8:
            顯 = pd.concat([顯, pd.DataFrame([{"項目": f"其他 {len(比) - 8} 項", "比重": 比["比重"].iloc[8:].sum()}])])
        圖 = go.Figure(go.Bar(x=顯["比重"], y=顯["項目"], orientation="h", marker_color=青,
                              text=顯["比重"].map("{:.1f}%".format), textposition="outside", cliponaxis=False))
        圖.update_yaxes(autorange="reversed")
        圖.update_layout(title=f"營收比重（{資['比重年度'] or '最近'} 年）", hovermode="closest")
        st.plotly_chart(圖表外觀(圖, 60 + 30 * len(顯)), width="stretch", config={"displayModeBar": False})
    elif not 資["業務"]:
        st.caption("這檔的主要業務、營收比重還沒抓到（資料每天自動補一批）。")
    # AI 公司介紹：產品、客戶、龍頭地位、競爭對手（官方資料沒有，用 AI 整理）
    引擎, 金鑰, 模型, 可執行 = AI設定()
    if 資["AI介紹"]:
        with st.expander(f"🤖 AI 公司介紹：產品、主要客戶、產業地位（{資['AI時間'][:10]}）", expanded=True):
            st.markdown(re.sub(r"^#{1,3}\s+", "##### ", 資["AI介紹"], flags=re.M))
            st.caption("AI 依公開資料整理，客戶與市占率可能不完整或過時，重要決定請以年報、法說會為準。")
    a, b = st.columns(2)
    if 可執行 and a.button("✨ AI 產生公司介紹" if not 資["AI介紹"] else "🔄 重新產生公司介紹", key=f"公司介紹{代號}"):
        with st.spinner("AI 整理公司介紹中，約 30 秒…"):
            try:
                內容 = engine.AI公司介紹(代號, r["名稱"], 公司文字(資), 引擎, 金鑰, 模型,
                                    搜尋=str(_設定().get("GEMINI_SEARCH", "")).lower() == "true")
                if 內容:
                    engine.儲存公司介紹(代號, {"時間": pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m-%d %H:%M"),
                                             "引擎": 引擎, "內容": 內容}, _設定())
                    st.session_state["_公司介紹版本"] = st.session_state.get("_公司介紹版本", 0) + 1
                    st.rerun()
            except Exception as 錯:
                st.error(f"產生失敗：{錯}")
    if b.button("📋 複製公司介紹指令（Gemini／Claude App）", key=f"公司指令{代號}"):
        st.session_state["顯示公司指令"] = not st.session_state.get("顯示公司指令", False)
    if st.session_state.get("顯示公司指令"):
        st.code(f"{engine.公司介紹提示}\n\n請介紹台股 {代號} {r['名稱']}。\n\n官方與網站資料：\n{公司文字(資)}",
                language=None, wrap_lines=True)
    st.caption("主要經營業務：公開資訊觀測站；營收比重：MoneyDJ（公司年報）；市值、營收排名：網站資料庫依證交所產業分類計算。"
               "同業市值第一名標為產業龍頭只是規模參考。")


def 個股筆記(代號):
    if not 可編輯():
        return
    筆 = engine.研究時間軸(研究筆記(), 代號=代號)
    段落("NOTES // 我的研究筆記")
    for _, x in 筆.head(8).iterrows():
        圖 = {"看多": "🔴", "看空": "🟢"}.get(x["看法"], "⚪")
        st.markdown(f"- `{x['日期']:%Y/%m/%d}` {圖} {x['內容']}")
    with st.expander("✏️ 幫這檔寫一則筆記", expanded=筆.empty):
        筆記輸入(f"個股{代號}", 代號)
    st.caption("所有筆記、券商報告、網紅說法的時間軸在「04 選股 → 📝 研究筆記」。")


def 全年EPS反推區(代號):
    with st.expander("🧮 網紅／券商說「今年 EPS 約 X 元」？算算剩下的季度每季要賺多少"):
        全年 = st.number_input("全年 EPS 預估（元）", min_value=-100.0, max_value=1000.0, value=0.0, step=0.1,
                             key=f"全年EPS_{代號}")
        if not 全年:
            st.caption("輸入影片或報告說的全年 EPS，例如鈔錢部署 11/03 說台達電今年約 40.7 元。")
            return
        x = engine.全年EPS反推(代號, 全年)
        if not x:
            st.caption("沒有這檔的季報 EPS 資料。")
            return
        if x["已公布季數"] >= 4:
            st.caption(x["說明"])
            return
        倍 = x["倍數"]
        卡片格([
            卡片(f"{x['年度']} 前 {x['已公布季數']} 季累計", f"{x['累計EPS']:.2f}", f"平均每季 {x['今年平均每季']:.2f}"),
            卡片(f"剩下 {x['剩下季數']} 季每季要賺", f"{x['剩下每季要賺']:.2f}",
                 f"是今年平均的 {倍:.1f} 倍" if pd.notna(倍) else "", 紅 if pd.notna(倍) and 倍 >= 1.3 else "#EDEDED"),
            卡片("最近一季單季", 數(x["最近一季單季"])),
            卡片("全年年增", 數(x["全年年增%"], "{:+.1f}", "%"), f"去年全年 {數(x['去年全年'])}"),
        ])
        st.caption("剩下每季要賺 ＝（全年預估 − 已公布累計）÷ 剩下季數。要賺的比今年平均高很多（1.3 倍以上標紅），"
                   "代表預估假設後面大幅成長，要確認有沒有根據（新產品、漲價、業外收益），或只是口誤。")


def 個股網紅說法(代號):
    說們 = [(v, x) for v in 網紅說法清單(st.session_state.get("_網紅版本", 0)) for x in v.get("股票", [])
           if str(x.get("代號")) == str(代號)]
    if not 說們:
        return
    段落("INFLUENCER // 網紅怎麼說")
    列 = 今日[今日["代號"] == str(代號)]
    _本益比 = float(列["本益比"].iloc[0]) if len(列) and "本益比" in 列 and pd.notna(列["本益比"].iloc[0]) else None
    _EPS = engine.近四季EPS(str(代號))[0] if any("EPS" in str(x.get("理由")) for _, x in 說們) else None
    _EPS = _EPS if _EPS is not None and pd.notna(_EPS) else None
    現 = float(列["收盤"].iloc[0]) if len(列) else None
    價 = engine.網紅價位(list({id(v): v for v, _ in 說們}.values()), {str(代號): 現} if 現 else None, 天數=90)
    價 = 價[價["代號"] == str(代號)] if len(價) else 價
    if len(價):
        st.markdown("**評論者的價位計畫**：" + "；".join(
            f"{r['頻道']} {r['類型']} {r['價位']:,.0f}" + (f"（距今 {r['距離%']:+.1f}%）" if pd.notna(r["距離%"]) else "") for _, r in 價.head(6).iterrows()))
    for v, x in sorted(說們, key=lambda t: str(t[0].get("日期")), reverse=True)[:8]:
        圖 = {"看多": "🔴", "看空": "🟢"}.get(x["看法"], "⚪")
        查 = engine.數字查核(x.get("理由"), _本益比, _EPS)
        st.markdown(f"- `{v.get('日期') or '—'}` {圖} **{v['頻道']}**：{x.get('原文看法') or x['看法']}。{x.get('理由', '')}"
                    + (" 🚩" if v.get("紅旗") else "") + (f"  \n  🔢 _{查}_" if 查 else ""))
    st.caption("紅色＝看多、綠色＝看空（跟台股漲跌顏色一樣）。🚩＝那支影片有紅旗，見 04 選股 → 網紅說法。")


def 個股券商報告(代號, 收盤):
    """03 個股 AI 分頁：這檔的券商報告、共識面板、目標價拆解、EPS 共識走勢、白話翻譯與交叉驗證。"""
    報告們 = [x for x in 券商報告清單(st.session_state.get("_券商版本", 0)) if str(x.get("代號")) == str(代號)]
    段落("BROKER // 券商報告")
    if not 報告們:
        st.caption("還沒有這檔的券商報告，可以到「04 選股 → 券商報告」上傳 PDF 或目標價截圖。")
        return
    表 = engine.券商報告表(報告們)
    共 = engine.券商共識(報告們, 收盤)
    if 共 and 共["目標價數"]:
        卡們 = [卡片("目標價區間（每家最新）", f"{共['最低']:,.0f} ~ {共['最高']:,.0f}",
                    f"{共['家數']} 家；最樂觀 {共['最樂觀']}、最悲觀 {共['最悲觀']}"),
               卡片("共識中位數", f"{共['中位數']:,.0f}", f"距現價 {共['中位數空間%']:+.1f}%", 漲跌色(共["中位數空間%"])),
               卡片("多／中／空", f"{共['看多']}／{共['中性']}／{共['看空']}", f"上修 {共['上修']} 家、下修 {共['下修']} 家"),
               卡片("現價在區間的位置", "—" if pd.isna(共.get("現價位置%")) else f"{共['現價位置%']:.0f}%", "0%＝最低目標價、100%＝最高")]
        if 共["外資家數"] and 共["本土家數"]:
            卡們.append(卡片("外資 vs 本土中位數", f"{共['外資中位數']:,.0f} / {共['本土中位數']:,.0f}",
                            f"外資 {共['外資家數']} 家、本土 {共['本土家數']} 家"))
        卡片格(卡們)
        st.caption("共識只算近半年、每家券商最新一份，用中位數不用平均，避免被一個極端目標價帶走。")
    集 = [x for x in engine.集體升降評(報告們) if x[0] == str(代號)]
    for _, _, 方向, 家, 名們 in 集:
        (st.success if 方向 == "上修" else st.warning)(f"📣 近 3 天 {家} 家券商同時{方向}目標價：{名們}")
    表 = engine.加潛在空間(表, {str(代號): 收盤})
    表格(表.drop(columns=["代號", "名稱", "現價"]), hide_index=True, width="stretch",
                 column_config={"日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
                                "潛在空間%": st.column_config.NumberColumn(format="%+.1f%%")})
    st.caption("標籤：「一次性」＝報告提到業外、處分、回沖等不會重複的獲利；「估 2027」＝用哪一年 EPS 估值；"
               "「追價上修」＝前次目標價已經低於報告前股價才上修，不當成新的看多訊號。")
    拆 = engine.目標價拆解(報告們)
    if len(拆):
        with st.expander(f"🔍 目標價為什麼變？（{len(拆)} 份有前次目標價）"):
            表格(拆.drop(columns=["代號", "名稱"]), hide_index=True, width="stretch",
                 column_config={"日期": st.column_config.DateColumn(format="YYYY-MM-DD")})
            st.caption("目標價＝倍數 × EPS，所以總變動可以拆成「倍數變動」和「EPS 與估值年度變動」兩塊。"
                       "主要是倍數變的話，代表券商換了估值看法，不是公司獲利變好。")
    走 = engine.EPS共識走勢(報告們)
    if len(走) and 走["日期"].nunique() >= 2:
        圖 = go.Figure()
        for 年, g in 走.groupby("年度"):
            圖.add_trace(go.Scatter(x=g["日期"], y=g["中位數"], mode="lines+markers", name=年,
                                    customdata=g["家數"], hovertemplate="%{x|%m/%d} %{y:.2f}（%{customdata} 家）<extra></extra>"))
        st.markdown("**EPS 共識走勢（各券商最新預估的中位數）**")
        st.plotly_chart(圖表外觀(圖, 260), width="stretch")
    營收 = engine.讀取營收歷史(代號)
    價 = 個股價格(代號)
    全部 = st.toggle(f"顯示全部 {len(報告們)} 份報告", key=f"券商全部_{代號}") if len(報告們) > 5 else True
    for x in (報告們 if 全部 else 報告們[:5]):
        驗 = engine.驗收券商報告(x, 價) if 價 is not None else {"結果": "無資料"}
        目 = engine._數(x.get("目標價"))
        空 = f"，空間 {(目 / 收盤 - 1) * 100:+.0f}%" if not np.isnan(目) and 收盤 else ""
        標 = f"{x.get('日期')} {x.get('券商')} {x.get('評等')}，目標價 {x.get('目標價') or '—'}{空}（{驗['結果']}）"
        with st.expander(標):
            if x.get("白話"):
                st.markdown("**白話翻譯**\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(x["白話"], 1)))
            for k in ("理由", "評價方法", "風險", "追蹤指標", "評等定義"):
                if x.get(k):
                    st.markdown(f"**{k}**：{x[k]}")
            if pd.notna(驗.get("報酬%", np.nan)):
                st.caption(f"報告日到現在 {驗['報酬%']:+.1f}%（{驗['天數']} 個交易日）")
            核 = engine.交叉驗證(x, 營收, 價)
            if 核:
                st.markdown("**數字核對（跟網站資料比）**\n" + "\n".join(f"- {燈} {說}（{網}）" for 說, 燈, 網 in 核))
    if 價 is not None:
        命 = engine.券商命中率(報告們, {str(代號): 價})
        if not 命.empty:
            st.markdown("**這檔各券商的準度**")
            表格(命, width="stretch")


def 循環股提醒(r, 概念們):
    """景氣循環股本益比很低時提醒：可能是獲利高峰，不是便宜。"""
    循環 = r.get("產業") in engine.循環產業 or any(k in "".join(概念們) for k in engine.循環概念字)
    pe = r.get("本益比")
    if 循環 and pd.notna(pe) and 0 < pe < 12:
        st.info(f"🔄 這是景氣循環股，本益比只有 {pe:.1f} 倍。循環股常在**獲利高峰時本益比最低**（EPS 很大）、"
                "谷底時本益比最高甚至虧損，所以低本益比不一定便宜。建議改看股價淨值比在歷史的位置，"
                "或用景氣全周期的平均 EPS 估值；同時留意報價、庫存、運價等領先指標有沒有轉弱。")




def 技術替代卡(概念們):
    風險 = [(k, engine.技術替代風險[k]) for k in 概念們 if k in engine.技術替代風險]
    if 風險:
        st.warning("🔁 **技術替代風險**：" + "　".join(f"**{k}**｜{v}" for k, v in 風險))


# ---------- 03 個股查詢 ----------
if st.session_state.get("個股查詢") not in 股票選項:
    st.session_state["個股查詢"] = next((v for v in 股票選項 if v.startswith("2330 ")), 股票選項[0])
最近 = [c for c in st.query_params.get("r", "").split(",") if c in 市場名稱]
if 最近:
    def 切換最近():
        選 = st.session_state.get("最近看過")
        if 選:
            st.session_state["個股查詢"] = next((v for v in 股票選項 if v.split()[0] == 選.split()[0]), st.session_state["個股查詢"])
        st.session_state["最近看過"] = None
    st.pills("最近看過", [f"{c} {市場名稱[c]}" for c in 最近], key="最近看過", on_change=切換最近)
查詢 = st.selectbox("輸入代號或名稱查詢", 股票選項, key="個股查詢")
代號 = 查詢.split()[0]
新最近 = ",".join(([代號] + [c for c in 最近 if c != 代號])[:8])
if 新最近 != st.query_params.get("r", ""):
    st.query_params["r"] = 新最近  # 記在網址，加入書籤或重新整理都還在
r = 今日[今日["代號"] == 代號].iloc[0]
股 = 讀檔("_股本表", _版本)
if "股本億" not in 今日.columns and 代號 in 股.index:
    r = pd.concat([r, 股.loc[代號]])
數 = lambda v, f="{:,.2f}", 尾="": "—" if pd.isna(v) else f.format(v) + 尾
比 = r["收盤"] / r["還原價"] if r["還原價"] else 1  # 均線用還原價算，換回原始股價
色 = 漲跌色(r["漲跌"])

段落(f"PROFILE // {代號} {r['名稱']}")
概念們 = engine.個股概念(代號)
if 概念們:
    st.caption("🏷️ 概念股：" + "、".join(概念們))
循環股提醒(r, 概念們)
技術替代卡(概念們)
鏈 = engine.產業鏈位置(代號, dict(zip(今日["代號"], 今日["名稱"])))
if 鏈:
    st.caption("🔗 " + 鏈.replace("\n", "　｜　"))
if 警示表(_版本).get(代號):
    st.warning("⚠️ " + 警示表(_版本)[代號] + "　（處置股要先付款／交券才能下單，注意股代表近期交易異常）")
if not 可編輯():
    with st.popover("☆ 加入自選股"):
        輸入 = st.text_input("自選股有密碼保護，請輸入密碼", type="password", key="自選解鎖")
        if 輸入 and hmac.compare_digest(輸入, _密碼()):
            st.session_state["已解鎖"] = True
            st.query_params["k"] = 登入憑證()
            自選 = 自選股清單()
            if not any(代號 in v for v in 自選.values()):
                群 = next(iter(自選), "自選股")
                存自選股({**自選, 群: 自選.get(群, []) + [代號]})
            st.rerun()
        elif 輸入:
            st.error("密碼不正確")
if 可編輯():
    自選 = 自選股清單()
    在 = [g for g, v in 自選.items() if 代號 in v]
    if 在:
        if st.button(f"★ 已在自選股「{'、'.join(在)}」· 點此移除", key="移除自選"):
            存自選股({g: [c for c in v if c != 代號] for g, v in 自選.items()})
            st.rerun()
    else:
        群組們 = list(自選) or ["自選股"]
        a, b = st.columns([1, 1]) if len(群組們) > 1 else (st, None)
        加到 = b.selectbox("加到群組", 群組們, label_visibility="collapsed", key="加到群組") if b else 群組們[0]
        if a.button("☆ 加入自選股", key="加入自選"):
            存自選股({**自選, 加到: 自選.get(加到, []) + [代號]})
            st.rerun()
    提醒 = 提醒清單()
    設 = 提醒.get(代號, {})
    with st.expander("🔔 到價提醒" + (f"（目前：{提醒文字(設)}）" if 提醒文字(設) else "")):
        a, b = st.columns(2)
        上 = a.number_input("漲到（含）以上", min_value=0.0, value=float(設.get("上") or 0), step=1.0,
                           key=f"提醒上{代號}", help="0 = 不設定")
        下 = b.number_input("跌到（含）以下", min_value=0.0, value=float(設.get("下") or 0), step=1.0,
                           key=f"提醒下{代號}", help="0 = 不設定")
        a, b = st.columns(2)
        if a.button("💾 儲存提醒", key="存提醒"):
            新 = {k: v for k, v in 提醒.items() if k != 代號}
            if 上 or 下:
                新[代號] = {"名稱": r["名稱"], "上": 上 or None, "下": 下 or None}
            存提醒(新)
            st.rerun()
        if 設 and b.button("🗑 取消提醒", key="刪提醒"):
            存提醒({k: v for k, v in 提醒.items() if k != 代號})
            st.rerun()
        st.caption("盤中約每 15 分鐘檢查一次，到價會發 LINE 通知（需先設定 LINE，見說明）。"
                   "網站上的自選股也會標 🔔。")
股數 = r.get("發行股數")
卡片格([
    卡片("收盤 · " + 最新日.strftime("%m/%d"), 數(r["收盤"]), f"{r['漲跌']:+.2f}（{r['漲跌幅']:+.2f}%）", 色),
    卡片("產業", r.get("產業") or "—", r["市場"]),
    卡片("股本", 數(r.get("股本億"), "{:,.1f}", " 億")),
    卡片("發行股數", 數(股數 / 1000 if pd.notna(股數) else np.nan, "{:,.0f}", " 張")),
    卡片("市值", 數(股數 * r["收盤"] / 1e8 if pd.notna(股數) else np.nan, "{:,.0f}", " 億")),
    卡片("成交量", 數(r["成交張數"], "{:,.0f}", " 張"), f"週轉率 {數(r['volume'] / 股數 * 100 if pd.notna(股數) else np.nan, '{:.2f}', '%')}"),
])
分頁 = st.tabs(["📋 總覽", "💰 籌碼", "📊 基本面", "📈 技術", "🤖 AI 分析", "⚖️ 比較"])
with 分頁[5]:
    個股比較(代號)
with 分頁[0]:
    法 = 日程資料((代號,), _版本, 60)
    法 = 法[法["類型"] == "法說會"]
    if len(法):
        st.info("📅 " + "；".join(f"{x['日期']:%m/%d} 法說會 {x['說明'][:60]}" for _, x in 法.iterrows()))
    段落("SCORE // 每日評分（大盤、技術、籌碼、基本面規則計分，僅供參考）")
    評分卡片(代號)

    段落("OUTLOOK // 綜合判讀（依數據規則，免費）")
    判 = engine.規則判讀(r)
    卡片格([卡片("綜合分數", f"{判['分數']:+d}", 判["看法"], 紅 if 判["分數"] >= 30 else (綠 if 判["分數"] <= -30 else 灰)),
           卡片("利多因素", f"{len(判['利多'])} 項", "", 紅), 卡片("利空因素", f"{len(判['利空'])} 項", "", 綠)])
    a, b = st.columns(2)
    a.markdown("**🔴 利多**\n" + ("".join(f"\n- {x}" for x in 判["利多"]) or "\n- 無"))
    b.markdown("**🟢 利空**\n" + ("".join(f"\n- {x}" for x in 判["利空"]) or "\n- 無"))
    st.caption("分數 = 利多權重 − 利空權重，換算成 −100 ~ +100；+30 以上偏多、−30 以下偏空。只看數據，不含新聞內容。")

    段落("FLOW // 股價・週轉率・大戶・法人 變化")
    期間 = st.segmented_control("期間", ["3 個月", "半年", "1 年"], default="半年", key="變化期間",
                              label_visibility="collapsed") or "半年"
    變化圖(代號, r, {"3 個月": 63, "半年": 126, "1 年": 250}[期間])

    段落("NEWS // 近半年新聞")
    try:
        新聞 = 抓新聞(代號, r["名稱"])
    except Exception:
        新聞 = None
    if 新聞 is None:
        st.caption("暫時抓不到新聞，稍後再試。")
    elif 新聞.empty:
        st.caption("近半年沒有找到相關新聞。")
    else:
        新聞 = engine.新聞舊聞標記(新聞)
        新聞["情緒"] = 新聞["標題"].map(engine.新聞情緒)
        計 = 新聞["情緒"].value_counts()
        近月 = int((~新聞["舊聞"]).sum())
        重提 = int(新聞["首見日"].notna().sum())
        st.caption(f"共 {len(新聞)} 則（近 30 天 {近月} 則" + (f"，其中 {重提} 則是舊聞重提" if 重提 else "") + "）："
                   f"標題偏多 {計.get('利多', 0)}、偏空 {計.get('利空', 0)}、中性 {計.get('中性', 0)}"
                   "（依標題關鍵字粗略判斷，請點開原文確認）")
        圖示 = {"利多": "🔴", "利空": "🟢", "中性": "⚪"}
        列 = lambda x: (f"- `{engine.新聞日期標籤(x)}` {圖示[x['情緒']]} [{x['標題']}]({x['連結']}) · {x['來源']}")
        st.markdown("\n".join(列(x) for _, x in 新聞.head(15).iterrows()))
        if len(新聞) > 15:
            with st.expander(f"更多新聞（{len(新聞) - 15}）"):
                st.markdown("\n".join(列(x) for _, x in 新聞.iloc[15:].iterrows()))
        st.caption("超過 30 天的新聞會標「舊聞」；標題跟 30 天以前的新聞很像的會標「舊聞重提」，"
                   "代表同一件事之前就報導過，股價多半已經反應，不要當成新消息追。")

    個股重大訊息(代號)

with 分頁[1]:
    if not 有籌碼:
        st.caption("目前沒有籌碼資料。")
    if 有籌碼:
        段落("CHIPS // 籌碼面（張）")
        卡片格([
            卡片("外資", 數(r["外資買超"], "{:+,.0f}"),
                 f"連賣 {數(r['外資連賣'], '{:.0f}')} 天" if r.get("外資連賣", 0) > 0 else f"連買 {數(r['外資連買'], '{:.0f}')} 天",
                 漲跌色(r["外資買超"])),
            卡片("投信", 數(r["投信買超"], "{:+,.0f}"),
                 f"土洋對作 {r['土洋對作']:.0f} 天（外資賣、投信買）" if r.get("土洋對作", 0) >= 2 else
                 f"連買 {數(r['投信連買'], '{:.0f}')} 天", 漲跌色(r["投信買超"])),
            卡片("自營商", 數(r["自營買超"], "{:+,.0f}"), "", 漲跌色(r["自營買超"])),
            卡片("法人 5 日合計", 數(r["法人5日買超"], "{:+,.0f}"), "", 漲跌色(r["法人5日買超"])),
            卡片("法人 10 日合計", 數(r["法人10日買超"], "{:+,.0f}"), "", 漲跌色(r["法人10日買超"])),
            卡片("融資餘額", 數(r["融資餘額"], "{:,.0f}"), f"5 日 {數(r['融資5日增減'], '{:+.1f}', '%')}"),
            卡片("融資維持率（估算）", 數(r.get("融資維持率", np.nan), "{:.0f}", "%"),
                 f"成本約 {數(r.get('融資成本', np.nan), '{:,.1f}')}　20 日 {數(r.get('融資20日增減', np.nan), '{:+.1f}', '%')}　"
                 + (engine.融資訊號(r) or "130% 以下會追繳"),
                 綠 if r.get("融資維持率", 200) < 145 else "#EDEDED"),
        ])
    內部 = 內部人資料(代號)
    if 內部 is not None:
        段落("INSIDER // 公司內部人（董監、經理人、大股東）")
        最近 = 內部.iloc[-1]
        前月 = 內部.iloc[-2] if len(內部) > 1 else None
        增減 = (最近["insider"] - 前月["insider"]) / 1000 if 前月 is not None else np.nan
        卡片格([
            卡片(f"內部人持股 · {最近['month']}", 數(最近["insider"] / 1000, "{:,.0f}", " 張"),
                 f"佔 {數(最近['insider'] / 股數 * 100 if pd.notna(股數) else np.nan, '{:.1f}', '%')}"),
            卡片("董監持股", 數(最近["directors"] / 1000, "{:,.0f}", " 張"),
                 f"佔 {數(最近['directors'] / 股數 * 100 if pd.notna(股數) else np.nan, '{:.1f}', '%')}"),
            卡片("較上月增減", 數(增減, "{:+,.0f}", " 張"), "", 漲跌色(增減)),
            卡片("設質（質押）", 數(最近["pledged"] / 1000, "{:,.0f}", " 張"),
                 f"佔內部人 {數(最近['pledged'] / 最近['insider'] * 100 if 最近['insider'] else np.nan, '{:.1f}', '%')}"),
        ])
        if 前月 is not None:
            張 = 內部.set_index("month")[["insider", "directors", "pledged"]] / 1000
            前後期表(張, {"insider": ("內部人持股（張）", "{:,.0f}"), "directors": ("董監持股（張）", "{:,.0f}"),
                        "pledged": ("設質（張）", "{:,.0f}")},
                     [("上月", 1), ("3 個月前", 3), ("6 個月前", 6)], str, 反向={"pledged"})
            st.caption("資料：公開資訊觀測站每月董監事持股餘額（同一人有多個職稱只算一次）。"
                       "內部人增持通常代表看好自家公司；設質（拿股票去借錢）增加要留意。")

    集保 = 大戶歷史(代號)
    if 集保 is not None and len(集保):
        段落("HOLDERS // 集保股權分散（大戶與散戶）")
        最新 = 集保.iloc[-1]
        前 = 集保.iloc[-2] if len(集保) > 1 else None
        差 = lambda 欄: 最新[欄] - 前[欄] if 前 is not None else np.nan
        週 = f"較上週 {差('big1000'):+.2f}" if 前 is not None else "下週起可比較"
        卡片格([
            卡片(f"千張大戶 · {最新['date']:%m/%d}", f"{最新['big1000']:.2f}%", 週, 漲跌色(差("big1000"))),
            卡片("400 張以上大戶", f"{最新['big400']:.2f}%",
                 f"較上週 {差('big400'):+.2f}" if 前 is not None else "", 漲跌色(差("big400"))),
            卡片("50 張以下散戶", f"{最新['retail']:.2f}%",
                 f"較上週 {差('retail'):+.2f}" if 前 is not None else "", 漲跌色(-差("retail"))),
            卡片("股東人數", f"{最新['holders']:,.0f}",
                 f"較上週 {差('holders'):+,.0f}" if 前 is not None else ""),
        ])
        if 前 is not None:
            前後期表(集保.set_index("date"), {"big1000": ("千張大戶 %", "{:.2f}"), "big400": ("400 張以上 %", "{:.2f}"),
                                             "retail": ("50 張以下散戶 %", "{:.2f}"), "holders": ("股東人數", "{:,.0f}")},
                     [("上週", 1), ("4 週前", 4), ("12 週前", 12)], lambda d: f"{d:%m/%d}", 反向={"retail", "holders"})
        if len(集保) >= 3:
            圖 = make_subplots(specs=[[{"secondary_y": True}]])
            圖.add_trace(go.Scatter(x=集保["date"], y=集保["big1000"], name="千張大戶 %", line=dict(color=紅)))
            圖.add_trace(go.Scatter(x=集保["date"], y=集保["retail"], name="散戶 %", line=dict(color=綠)))
            圖.add_trace(go.Bar(x=集保["date"], y=集保["holders"], name="股東人數", marker_color="#333",
                                opacity=0.6), secondary_y=True)
            st.plotly_chart(圖表外觀(圖, 260), width="stretch")
        st.caption("集保結算所每週五公布。大戶比例上升、股東人數下降，通常代表籌碼往大戶集中（表中紅色＝籌碼變集中）。")

    借 = 借券資料(代號, _版本)
    if 借 is not None and len(借):
        段落("SBL // 借券賣出（空方籌碼，張）")
        最 = 借.iloc[-1]
        前5 = 借.iloc[-6]["sbl_balance"] if len(借) > 5 else np.nan
        前20 = 借.iloc[-21]["sbl_balance"] if len(借) > 20 else np.nan
        近5賣 = 借.tail(5)["sbl_sell"].sum()
        卡片格([
            卡片(f"借券賣出餘額 · {最['date']:%m/%d}", f"{最['sbl_balance']:,.0f}",
                 f"佔發行 {數(最['sbl_balance'] * 1000 / 股數 * 100 if pd.notna(股數) else np.nan, '{:.2f}', '%')}"),
            卡片("較 5 日前", 數(最["sbl_balance"] - 前5, "{:+,.0f}"), "", 漲跌色(-(最["sbl_balance"] - 前5) if pd.notna(前5) else 0)),
            卡片("較 20 日前", 數(最["sbl_balance"] - 前20, "{:+,.0f}"), "", 漲跌色(-(最["sbl_balance"] - 前20) if pd.notna(前20) else 0)),
            卡片("近 5 日借券賣出", f"{近5賣:,.0f}", f"約 {近5賣 / max(r['5日均量'] * 5, 1) * 100:.1f}% 成交量"),
        ])
        if len(借) >= 5:
            價 = 個股全史(代號, _版本)[["date", "收盤"]]
            價 = 價[價["date"] >= 借["date"].min()]
            圖 = make_subplots(specs=[[{"secondary_y": True}]])
            圖.add_trace(go.Bar(x=借["date"], y=借["sbl_balance"], name="借券賣出餘額(張)", marker_color="#5A3A8C"))
            圖.add_trace(go.Scatter(x=價["date"], y=價["收盤"], name="股價", line=dict(color="#FFFFFF", width=1.4)),
                         secondary_y=True)
            圖.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
            st.plotly_chart(圖表外觀(圖, 260), width="stretch")
        st.caption("借券賣出＝法人借股票來放空。餘額增加代表看空的人變多（綠）；減少代表空方回補（紅），"
                   "股價上漲時空方回補會加大漲勢。")

    外資史, 當沖史 = 外資持股歷史(代號, _版本), 當沖資料(代號, _版本)
    投信佔 = r.get("投信60日買超佔股本")
    if (外資史 is not None and len(外資史)) or (當沖史 is not None and len(當沖史)) or pd.notna(投信佔):
        段落("HOLDING // 外資持股比、投信買超佔股本、當沖比率")
        卡們 = []
        if 外資史 is not None and len(外資史):
            最, 前 = 外資史.iloc[-1], 外資史.iloc[max(len(外資史) - 21, 0)]
            差 = 最["ratio"] - 前["ratio"]
            卡們.append(卡片(f"外資持股比 · {最['date']:%m/%d}", f"{最['ratio']:.2f}%",
                           f"較 {前['date']:%m/%d} {差:+.2f} 個百分點", 漲跌色(差)))
        if pd.notna(投信佔):
            卡們.append(卡片("投信近 60 日買超佔股本", f"{投信佔:+.2f}%", "投信不公布持股，用累計買超估算", 漲跌色(投信佔)))
        if 當沖史 is not None and len(當沖史):
            近5 = 當沖史.tail(5)["比率"].mean()
            卡們.append(卡片(f"當沖比率 · {當沖史['date'].iloc[-1]:%m/%d}", f"{當沖史['比率'].iloc[-1]:.1f}%",
                           f"近 5 日平均 {近5:.1f}%、近 20 日 {當沖史.tail(20)['比率'].mean():.1f}%",
                           "#FFC24B" if 近5 >= 40 else "#EDEDED"))
        卡片格(卡們)
        if 外資史 is not None and len(外資史) >= 5:
            價 = 個股全史(代號, _版本)[["date", "收盤"]]
            價 = 價[價["date"] >= 外資史["date"].min()]
            圖 = make_subplots(specs=[[{"secondary_y": True}]])
            圖.add_trace(go.Scatter(x=外資史["date"], y=外資史["ratio"], name="外資持股比 %", line=dict(color="#FFB020", width=2)))
            if 當沖史 is not None and len(當沖史):
                圖.add_trace(go.Bar(x=當沖史["date"], y=當沖史["比率"], name="當沖比率 %", marker_color="#5A3A8C", opacity=0.6))
            圖.add_trace(go.Scatter(x=價["date"], y=價["收盤"], name="股價", line=dict(color="#FFFFFF", width=1.2)),
                         secondary_y=True)
            圖.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
            st.plotly_chart(圖表外觀(圖, 260), width="stretch")
        st.caption("外資持股比：證交所、櫃買中心每天公布，持續上升代表外資長線布局。"
                   "當沖比率＝當沖成交股數 ÷ 成交股數（只有上市股票），超過 40% 代表短線客多、股價容易暴漲暴跌。")

with 分頁[2]:
    公司介紹區(代號, r)
    段落("FUNDAMENTAL // 基本面")
    營收 = r.get("營收年增率")
    卡片格([
        卡片("本益比", 數(r["本益比"])), 卡片("殖利率", 數(r["殖利率"], 尾="%")), 卡片("股價淨值比", 數(r["淨值比"])),
        卡片("EPS（今年累計）", 數(r.get("EPS")), r.get("EPS季度") or ""),
        卡片("近三季 EPS 合計", 數(r.get("近三季EPS"))),
        卡片("月營收年增率", 數(營收, 尾="%"), f"{r.get('營收月份') or ''}"
             + ("　★ 創歷史新高" if r.get("營收創新高") == True else ""), 漲跌色(營收 if pd.notna(營收) else 0)),
        卡片("月營收月增率", 數(r.get("營收月增率"), 尾="%"), "", 漲跌色(r.get("營收月增率") or 0)),
        卡片("累計營收年增率", 數(r.get("累計營收年增率"), 尾="%"), "", 漲跌色(r.get("累計營收年增率") or 0)),
        卡片("距 52 週高點", 數(r["距52週高點"], "{:+.1f}", "%")),
    ] + 毛利卡片(r) + ROE卡片(代號, r))
    預估EPS區(r)
    全年EPS反推區(代號)
    河流 = engine.本益比河流(個股全史(代號, _版本))
    if 河流:
        段落("VALUATION // 本益比河流圖")
        h, 倍數們, 百分位 = 河流
        目前 = h["本益比"].iloc[-1]
        位置 = "偏便宜" if 百分位 < 25 else ("偏貴" if 百分位 > 75 else "合理區間")
        卡片格([
            卡片("目前本益比", f"{目前:.1f} 倍", 位置, 綠 if 百分位 < 25 else (紅 if 百分位 > 75 else "#EDEDED")),
            卡片("歷史位置", f"{百分位:.0f}%", f"比過去 {百分位:.0f}% 的日子貴"),
            卡片("近四季 EPS", f"{h['EPS'].iloc[-1]:.2f}", f"本益比區間 {倍數們[0]}~{倍數們[-1]} 倍"),
        ])
        圖 = go.Figure()
        河色 = ["#0B3D2E", "#145A41", "#1F6F4F", "#5C5A1E", "#7A3B1E", "#7A1E2E"]
        for i, 倍 in enumerate(倍數們):
            圖.add_trace(go.Scatter(x=h["date"], y=h[f"{倍}倍"], name=f"{倍} 倍", mode="lines",
                                    line=dict(width=0.5, color=河色[min(i, len(河色) - 1)]),
                                    fill="tonexty" if i else None, fillcolor=河色[min(i, len(河色) - 1)]))
        圖.add_trace(go.Scatter(x=h["date"], y=h["收盤"], name="股價", line=dict(color="#FFFFFF", width=1.6)))
        預位 = engine.預估河流位置(h, r["收盤"], {str(int(r["預估年度"])) if pd.notna(r.get("預估年度")) else "今年": r.get("預估EPS今年"),
                                               str(int(r["預估年度"]) + 1) if pd.notna(r.get("預估年度")) else "明年": r.get("預估EPS明年")})
        for 位, 色 in zip(預位, ("#FFC24B", "#FF00E5")):
            圖.add_hline(y=位["中位價"], line_dash="dot", line_color=色, line_width=1,
                        annotation_text=f"{位['年度']} 預估 EPS × {位['中位倍']:.0f} 倍＝{位['中位價']:,.0f}",
                        annotation_font_color=色, annotation_position="top left")
        圖.update_layout(hovermode="x unified")
        st.plotly_chart(圖表外觀(圖, 360), width="stretch")
        if 預位:
            卡片格([卡片(f"用 {位['年度']} 預估 EPS 算", f"{位['預估本益比']:.1f} 倍",
                        f"比過去 {位['歷史百分位']}% 的日子貴；合理區 {位['低標價']:,.0f}～{位['高標價']:,.0f}",
                        綠 if 位["歷史百分位"] < 25 else (紅 if 位["歷史百分位"] > 75 else "#EDEDED")) for 位 in 預位])
            st.caption("虛線＝預估 EPS × 過去 5 年本益比中位數；合理區＝預估 EPS × 過去本益比 10%～90% 分位。"
                       "預估本益比通常比近四季本益比低（獲利成長時），所以「歷史位置」會看起來比較便宜，要一起看預估 EPS 可不可信。")
        st.caption("每條線 = 近四季 EPS × 本益比倍數（取過去 5 年本益比的 10%~90% 區間）。"
                   "股價在越下面的帶子代表以歷史標準看越便宜；EPS 衰退時便宜也可能是合理的。")

    除權息, 預告 = engine.讀取除權息(代號)
    if 除權息 is not None and (len(除權息) or (預告 is not None and len(預告))):
        段落("DIVIDEND // 股利與除權息")
        if 預告 is not None and len(預告):
            for _, p in 預告.iterrows():
                st.markdown(f"📅 **即將除{p['type']}：{p['date']:%Y/%m/%d}**"
                            + (f"，現金股利 {p['cash']:g} 元" if pd.notna(p["cash"]) and p["cash"] else "")
                            + (f"，股票股利每千股 {p['stock_ratio'] * 1000:g} 股"
                               if pd.notna(p.get("stock_ratio")) and p.get("stock_ratio") else ""))
        if len(除權息):
            價格 = 個股全史(代號, _版本)[["date", "收盤"]]
            表 = 除權息.assign(填息=engine.填息(除權息, 價格)).sort_values("date", ascending=False)
            近一年 = 表[表["date"] >= 表["date"].max() - pd.Timedelta(days=365)]
            年配 = 近一年["value"].sum()
            卡片格([
                卡片("近一年配發", f"{年配:.2f} 元", f"{len(近一年)} 次"),
                卡片("以現價計殖利率", f"{年配 / r['收盤'] * 100:.2f}%" if r["收盤"] else "—", "含股票股利換算"),
                卡片("最近一次填息", 表["填息"].iloc[0], f"{表['date'].iloc[0]:%Y/%m/%d}"),
            ])
            顯示 = pd.DataFrame({"除權息日": 表["date"].dt.strftime("%Y/%m/%d"), "類型": 表["type"],
                                "權值+息值": 表["value"], "除權息前收盤": 表["pre_close"], "參考價": 表["ref"],
                                "填息天數": 表["填息"]})
            表格(顯示.style.format({"權值+息值": "{:.4g}", "除權息前收盤": "{:,.2f}", "參考價": "{:,.2f}"}),
                         hide_index=True, width="stretch", height=min(35 * (len(顯示) + 1) + 3, 320))
            st.caption("填息天數 = 除權息後，收盤價回到除權息前收盤價花了幾個交易日。資料：證交所、櫃買中心（近 6 年）。")

    財 = 財報資料(代號, _版本)
    if 財 is not None and "cfo" in 財.columns and 財["cfo"].notna().any():
        段落("HEALTH // 財務體質：負債與現金流")
        最 = 財.dropna(subset=["assets"]).iloc[-1] if "assets" in 財 and 財["assets"].notna().any() else None
        卡片格([
            卡片("負債比", 數(r.get("負債比"), "{:.1f}", "%"), f"{最['quarter']} 季底" if 最 is not None else "",
                 "#FFC24B" if (r.get("負債比") or 0) >= 70 else "#EDEDED"),
            卡片("流動比", 數(r.get("流動比"), "{:.0f}", "%"), "流動資產 ÷ 流動負債，低於 100% 要留意"),
            卡片("近四季營業現金流", 數(r.get("近四季營業現金流億"), "{:+,.1f}", " 億"), "", 漲跌色(r.get("近四季營業現金流億") or 0)),
            卡片("近四季自由現金流", 數(r.get("近四季自由現金流億"), "{:+,.1f}", " 億"), "營業＋投資現金流",
                 漲跌色(r.get("近四季自由現金流億") or 0)),
            卡片("期末現金", 數(財["cash_end"].dropna().iloc[-1] / 1e5 if 財["cash_end"].notna().any() else np.nan, "{:,.1f}", " 億"),
                 財.dropna(subset=["cash_end"])["quarter"].iloc[-1] if 財["cash_end"].notna().any() else ""),
        ])
        近 = 財.tail(8)
        圖 = go.Figure([go.Bar(x=近["quarter"], y=近["cfo"] / 1e5, name="營業現金流（億）", marker_color=青),
                        go.Bar(x=近["quarter"], y=近["fcf"] / 1e5, name="自由現金流（億）", marker_color="#FFB020")])
        圖.update_layout(barmode="group", legend=dict(orientation="h", y=1.12))
        st.plotly_chart(圖表外觀(圖, 260), width="stretch")
        顯示 = pd.DataFrame({"季度": 近["quarter"], "營業現金流(億)": 近["cfo"] / 1e5, "投資現金流(億)": 近["cfi"] / 1e5,
                            "自由現金流(億)": 近["fcf"] / 1e5, "籌資現金流(億)": 近["cff"] / 1e5,
                            "期末現金(億)": 近["cash_end"] / 1e5,
                            "負債比%": 近["liabilities"] / 近["assets"] * 100 if "assets" in 近 else np.nan,
                            "流動比%": 近["cur_assets"] / 近["cur_liab"] * 100 if "cur_liab" in 近 else np.nan}).iloc[::-1]
        表格(顯示.style.format("{:,.1f}", subset=[c for c in 顯示.columns if c != "季度"], na_rep="—"),
             hide_index=True, width="stretch")
        st.caption("資料：公開資訊觀測站各季財報彙總（單季數字由今年累計數相減而來）。自由現金流這裡用「營業＋投資現金流」簡單估算；"
                   "營業現金流長期為負、或負債比持續升高的公司要特別小心。金融業沒有流動比。")

    約 = 讀檔("讀取合約負債", _版本, 代號)
    if 約 is not None and 約["src"].eq("mops").any() and 約["合約負債"].isna().all():
        段落("BACKLOG // 合約負債：預收款與營收能見度")
        st.caption("這家公司財報沒有單獨列「合約負債」（像台積電、鴻海都沒有），沒辦法用預收款看營收能見度。")
    elif 約 is not None and 約["合約負債"].notna().any():
        段落("BACKLOG // 合約負債：預收款與營收能見度")
        約 = 約.dropna(subset=["合約負債"])
        最 = 約.iloc[-1]
        卡片格([
            卡片("合約負債", 數(最["合約負債"] / 1e5, "{:,.1f}", " 億"), f"{最['quarter']} 季底", 青),
            卡片("年增率", 數(最["合約負債年增"], "{:+.1f}", "%"), "跟去年同季比；金額不到 1 億不算",
                 漲跌色(最["合約負債年增"] if pd.notna(最["合約負債年增"]) else 0)),
            卡片("能見度", 數(最["能見度月"], "{:.1f}", " 個月"), "合約負債 ÷ 近四季營收 × 12"),
            卡片("佔股本", 數(r.get("合約負債佔股本"), "{:,.0f}", "%"), "每股背後有多少預收款"),
        ])
        近 = 約.tail(8)
        圖 = go.Figure([go.Bar(x=近["quarter"], y=近["合約負債"] / 1e5, name="合約負債（億）", marker_color=青),
                        go.Scatter(x=近["quarter"], y=近["單季營收"] / 1e5, name="單季營收（億）", mode="lines+markers",
                                   line=dict(color="#FFB020"))])
        圖.update_layout(legend=dict(orientation="h", y=1.12))
        st.plotly_chart(圖表外觀(圖, 260), width="stretch")
        st.caption("合約負債＝已經收款、還沒交貨的預收款，交貨後才變成營收，所以常被當成未來一兩季營收的領先指標；"
                   "設備、廠務工程、IC 設計服務、重電最有參考價值。營建股的預售屋訂金要等交屋才認列，可能拖 2～4 年。"
                   "季增率容易被單筆大額預付款影響，看年增率比較穩。資料：公開資訊觀測站個別資產負債表（流動＋非流動），"
                   "較早的季度用 FinMind 補（只有流動部分）。")

    事件 = 個股事件(代號)
    if 事件 is not None and len(事件):
        段落("EVENTS // 公司事件：庫藏股、可轉債、現金增資")
        表格(事件.assign(日期=事件["日期"].dt.strftime("%Y/%m/%d")), hide_index=True, width="stretch",
             column_config={"內容": st.column_config.TextColumn(width="large")})
        st.caption("庫藏股（公司買回自家股票）通常代表公司認為股價偏低；可轉債、現金增資會增加股數（稀釋），"
                   "但募到的錢若用在擴產也可能是利多。資料：公開資訊觀測站、櫃買中心、證交所。")

    海外布局區(代號)
    業外損益區(代號)
    投資金額換算區(代號, r)

    同業 = engine.同族群(今日, 代號)
    if 同業 is not None and len(同業) > 1:
        段落(f"PEERS // 同族群比較（{r.get('產業')}，市值前 {len(同業)} 大）")
        欄們 = [c for c in ["名稱", "市值億", "收盤", "漲跌幅", "20日漲幅", "本益比", "殖利率", "淨值比",
                          "營收年增率", "毛利率", "EPS", "代號"] if c in 同業.columns]
        比較 = 同業[欄們].rename(columns={"收盤": "股價", "EPS": "EPS(今年)"})
        樣式 = 上色(比較).apply(lambda 列: ["background:#0E2A33" if 列["代號"] == 代號 else "" for _ in 列], axis=1)
        點選表(比較, 樣式, "同業表", height=35 * (len(比較) + 1) + 3)
        中位 = 同業[同業["代號"] != 代號][["本益比", "營收年增率"]].median()
        st.caption(f"同業本益比中位數 {中位['本益比']:.1f} 倍、營收年增率中位數 {中位['營收年增率']:+.1f}%；"
                   "點一下股票可切換到那一檔。")

with 分頁[3]:
    段落("TECHNICAL // 技術面")
    均線 = {n: r[f"MA{n}"] * 比 for n in (5, 10, 20, 60)}
    卡片格([卡片(f"{n} 日線", 數(v), "站上" if r["收盤"] >= v else "跌破", 紅 if r["收盤"] >= v else 綠)
           for n, v in 均線.items()] + [
        卡片("RSI(14)", 數(r["RSI"], "{:.1f}"), "超買" if r["RSI"] > 70 else ("超賣" if r["RSI"] < 30 else "")),
        卡片("量比（÷20 日均量）", 數(r["量比"])),
        卡片("20 日漲幅", 數(r["20日漲幅"], "{:+.2f}", "%"), "", 漲跌色(r["20日漲幅"])),
        卡片("盤整箱頂 / 箱底", f"{數(r['箱頂'])} / {數(r['箱底'])}", f"箱寬 {數(r['箱寬'], '{:.1f}', '%')}"),
        卡片("今日振幅", 數(r["振幅"], 尾="%")),
    ])
    符合 = [名 for 名, 設定 in engine.烏賊條件.items()
            if 代號 in engine.選股(今日[今日["代號"] == 代號], dict(設定["條件"], 排除ETF=False))["代號"].values]
    st.markdown("**今天符合的烏賊策略：** " + ("、".join(
        f"{'🔴' if engine.烏賊條件[x]['方向'] == '多' else '🟢'} {x.replace('烏賊', '')}" for x in 符合) or "無"))

    段落("LEVELS // 支撐壓力（自動計算）")
    個股價位區(代號)

    _全 = 個股全史(代號, _版本)
    if _全 is not None and len(_全) > 61:
        _尾 = _全.tail(130)
        K棒解讀區(pd.DataFrame({"date": _尾["date"], "open": _尾["open"], "high": _尾["high"], "low": _尾["low"],
                               "close": _尾["收盤"]}), _尾["volume"])

    段落("CHART // 走勢與指標")
    週期 = st.segmented_control("週期", ["當日", "5分", "日", "週", "月", "季"], default="日", key="個股週期",
                              label_visibility="collapsed") or "日"
    可選 = ["成交量", "三大法人", "外資", "投信", "自營商", "融資", "RSI", "MACD"] if 有籌碼 else ["成交量", "RSI", "MACD"]
    if 週期 in ("當日", "5分"):
        可選 = ["成交量", "RSI", "MACD"]
    指標們 = st.multiselect("下方指標", 可選, default=[x for x in ["成交量", "三大法人", "MACD"] if x in 可選],
                           key=f"個股指標{週期 in ('當日', '5分')}")
    疊加 = [] if 週期 in ("當日", "5分") else st.multiselect(
        "K 線圖疊加", ["布林通道", "成交均價線"], default=[], key="個股疊加",
        help="布林通道＝20 日均線 ± 2 個標準差；成交均價線＝近 20／60 日成交金額 ÷ 成交股數，比均線更接近這段期間買進者的平均成本")

    def 走勢圖():
        if 週期 in ("當日", "5分"):
            線 = 分鐘線(代號, r["市場"], "1m" if 週期 == "當日" else "5m", "5d")
            if 線 is None or 線.empty:
                st.info("分鐘線暫時抓不到，請稍後再試。")
                return
            線 = 線.assign(day=線["datetime"].dt.normalize())
            if 週期 == "當日":
                線 = 線[線["day"] == 線["day"].max()]
            K = pd.DataFrame({"x": 線["datetime"], "open": 線["open"], "high": 線["high"], "low": 線["low"],
                              "close": 線["close"], "量": 線["volume"] / 1000})
            st.caption(f"{線['datetime'].iloc[-1]:%Y/%m/%d %H:%M} 為止，資料來源 Yahoo 奇摩股市（盤中約延遲數分鐘）")
        else:
            歷史 = 個股全史(代號, _版本)
            if 週期 != "日":
                歷史 = engine.週期K線(歷史, 週期)
            歷史 = 歷史.tail({"日": 180, "週": 156, "月": 72, "季": 40}[週期])
            K = pd.DataFrame({"x": 歷史["date"], "open": 歷史["open"], "high": 歷史["high"], "low": 歷史["low"],
                              "close": 歷史["收盤"], "量": 歷史["成交張數"]})
            if 週期 == "日" and "成交均價線" in 疊加:
                全 = 個股全史(代號, _版本)
                for n in (20, 60):
                    K[f"均價{n}"] = engine.成交均價線(全["value"], 全["volume"], n).reindex(歷史.index).values
            for 欄, 名 in (("法人買超", "三大法人"), ("外資買超", "外資"), ("投信買超", "投信"), ("自營買超", "自營商"),
                          ("融資餘額", "融資")):
                if 欄 in 歷史.columns:
                    K[名] = 歷史[欄].values
        K = K.reset_index(drop=True)
        列數 = 1 + len(指標們)
        圖 = make_subplots(rows=列數, cols=1, shared_xaxes=True, vertical_spacing=0.025,
                           row_heights=[0.5] + [0.5 / max(len(指標們), 1)] * len(指標們),
                           subplot_titles=[""] + 指標們)
        if 週期 == "當日":
            昨收 = 線.attrs.get("昨收") or K["close"].iloc[0]
            色 = 紅 if K["close"].iloc[-1] >= 昨收 else 綠
            圖.add_trace(go.Scatter(x=K["x"], y=K["close"], name="成交價", line=dict(color=色, width=1.6)), row=1, col=1)
            圖.add_hline(y=昨收, line=dict(color=灰, width=1, dash="dot"), row=1, col=1)
        else:
            圖.add_trace(go.Candlestick(x=K["x"], open=K["open"], high=K["high"], low=K["low"], close=K["close"],
                                        name="K 線", increasing=dict(line=dict(color=紅), fillcolor=紅),
                                        decreasing=dict(line=dict(color=綠), fillcolor=綠)), row=1, col=1)
            for n, c in ((5, "#FFFFFF"), (10, "#FFC24B"), (20, 青), (60, "#FF00E5")):
                圖.add_trace(go.Scatter(x=K["x"], y=K["close"].rolling(n).mean(), name=f"MA{n}",
                                        line=dict(color=c, width=1)), row=1, col=1)
            if "布林通道" in 疊加:
                _, 上, 下 = engine.布林通道(K["close"])
                for 線, 名 in ((上, "布林上軌"), (下, "布林下軌")):
                    圖.add_trace(go.Scatter(x=K["x"], y=線, name=名, line=dict(color="#8F7CFF", width=1, dash="dot")),
                                 row=1, col=1)
            for n, c in ((20, "#FF8A3D"), (60, "#BDBDBD")):
                if f"均價{n}" in K:
                    圖.add_trace(go.Scatter(x=K["x"], y=K[f"均價{n}"], name=f"{n} 日成交均價",
                                            line=dict(color=c, width=1.4, dash="dash")), row=1, col=1)
        漲跌色列 = lambda v: [紅 if x >= 0 else 綠 for x in pd.Series(v).fillna(0)]
        for i, 名 in enumerate(指標們, start=2):
            if 名 == "成交量":
                圖.add_trace(go.Bar(x=K["x"], y=K["量"], name="成交量(張)",
                                    marker_color=漲跌色列(K["close"].diff())), row=i, col=1)
            elif 名 == "RSI":
                圖.add_trace(go.Scatter(x=K["x"], y=engine.RSI(K["close"]), name="RSI",
                                        line=dict(color=青, width=1.2)), row=i, col=1)
                for 線值 in (30, 70):
                    圖.add_hline(y=線值, line=dict(color=灰, width=1, dash="dot"), row=i, col=1)
            elif 名 == "MACD":
                DIF, DEA, 柱 = engine.MACD(K["close"])
                圖.add_trace(go.Bar(x=K["x"], y=柱, name="MACD 柱", marker_color=漲跌色列(柱)), row=i, col=1)
                圖.add_trace(go.Scatter(x=K["x"], y=DIF, name="DIF", line=dict(color="#FFC24B", width=1)), row=i, col=1)
                圖.add_trace(go.Scatter(x=K["x"], y=DEA, name="DEA", line=dict(color=青, width=1)), row=i, col=1)
            elif 名 == "融資":
                圖.add_trace(go.Scatter(x=K["x"], y=K.get("融資"), name="融資餘額(張)",
                                        line=dict(color="#FFC24B", width=1.2)), row=i, col=1)
            elif 名 in K.columns:
                圖.add_trace(go.Bar(x=K["x"], y=K[名], name=f"{名}(張)", marker_color=漲跌色列(K[名])), row=i, col=1)
        圖.update_layout(xaxis_rangeslider_visible=False, showlegend=False)
        if 週期 in ("當日", "5分"):
            圖.update_xaxes(rangebreaks=[dict(bounds=[13.6, 9], pattern="hour"), dict(bounds=["sat", "mon"])])
        elif 週期 == "日":
            圖.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
        圖.update_annotations(font=dict(size=11, color=灰), x=0, xanchor="left")
        st.plotly_chart(圖表外觀(圖, 380 + 150 * len(指標們)), width="stretch")

    走勢圖()

with 分頁[4]:
    段落("AI // 新聞彙整與投資觀點")
    try:
        設定 = dict(st.secrets)
    except Exception:
        設定 = {}
    if str(設定.get("GEMINI_API_KEY", "")).strip():
        引擎, 金鑰, 模型 = "Gemini", engine.清理金鑰(設定["GEMINI_API_KEY"]), str(設定.get("GEMINI_MODEL", "gemini-flash-latest"))
    else:
        引擎, 金鑰, 模型 = "Claude", engine.清理金鑰(設定.get("ANTHROPIC_API_KEY")), str(設定.get("AI_MODEL", "claude-opus-5-5"))
    密碼 = str(設定.get("password", ""))
    if not 金鑰:
        st.info("AI 會上網搜尋這檔股票近半年的新聞與法人報告，彙整後給出短、中期看法。"
                "要啟用，請到 aistudio.google.com 申請 Gemini API 金鑰（有免費額度），"
                "貼到 Streamlit 的 App settings →「Secrets」：`GEMINI_API_KEY = \"你的金鑰\"`")
    elif 密碼 and not st.session_state.get("已解鎖"):
        st.caption("產生或重新分析會用到你的 API 額度，請先在 01 市場總覽的庫存區輸入密碼解鎖；已有的報告卡片照常顯示。")
    可執行 = bool(金鑰) and not (密碼 and not st.session_state.get("已解鎖"))
    if True:  # 過去的報告與卡片不需要金鑰或密碼也能看
        今天 = 最新日.strftime("%Y-%m-%d")
        摘要 = "\n".join([
            f"- 資料日期 {今天}，收盤 {數(r['收盤'])}，漲跌 {r['漲跌幅']:+.2f}%，產業 {r.get('產業') or '—'}，"
            f"股本 {數(r.get('股本億'), '{:,.1f}', ' 億')}，市值 {數(股數 * r['收盤'] / 1e8 if pd.notna(股數) else np.nan, '{:,.0f}', ' 億')}",
            f"- 本益比 {數(r['本益比'])}，殖利率 {數(r['殖利率'], 尾='%')}，股價淨值比 {數(r['淨值比'])}，"
            f"今年累計 EPS {數(r.get('EPS'))}（{r.get('EPS季度') or ''}），近三季 EPS {數(r.get('近三季EPS'))}",
            f"- 月營收（{r.get('營收月份') or ''}）年增 {數(營收, 尾='%')}，月增 {數(r.get('營收月增率'), 尾='%')}，"
            f"累計年增 {數(r.get('累計營收年增率'), 尾='%')}" + ("，創歷史新高" if r.get("營收創新高") == True else ""),
            (f"- 單季毛利率（{r.get('毛利率季度')}）{數(r.get('毛利率'), 尾='%')}，較上季 {數(r.get('毛利率季增'), '{:+.1f}', ' 個百分點')}，"
             f"較去年同季 {數(r.get('毛利率年增'), '{:+.1f}', ' 個百分點')}，營益率 {數(r.get('營益率'), 尾='%')}"
             f"（較上季 {數(r.get('營益率季增'), '{:+.1f}')}、較去年同季 {數(r.get('營益率年增'), '{:+.1f}')} 個百分點）"
             if pd.notna(r.get("毛利率", np.nan)) else "- 無毛利率資料"),
            (lambda x: f"- ROE（近四季，至 {x[2]}）{x[0]:.1f}%，去年同期 {數(x[1], '{:.1f}', '%')}，近四季 EPS {x[3]:.2f}"
             if pd.notna(x[0]) else "- 無 ROE 資料")(ROE資料(代號, r)),
            (f"- 外資 {數(r['外資買超'], '{:+,.0f}')} 張、投信 {數(r['投信買超'], '{:+,.0f}')} 張、"
             f"法人 10 日合計 {數(r['法人10日買超'], '{:+,.0f}')} 張，融資 5 日 {數(r['融資5日增減'], '{:+.1f}', '%')}"
             if 有籌碼 else "- 無籌碼資料"),
            f"- 5/10/20/60 日線 {' / '.join(數(v) for v in 均線.values())}，RSI {數(r['RSI'], '{:.1f}')}，"
            f"20 日漲幅 {數(r['20日漲幅'], '{:+.2f}', '%')}，距 52 週高點 {數(r['距52週高點'], '{:+.1f}', '%')}",
            f"- 符合的烏賊策略：{'、'.join(符合) or '無'}",
        ])
        try:
            摘要 += "\n\n近半年股價、週轉率、千張大戶、三大法人變化：\n" + engine.變化摘要(*變化資料(代號, 126))
        except Exception:
            pass
        全 = 個股全史(代號, _版本)
        本益 = 全.loc[全["date"] >= 最新日 - pd.Timedelta(days=3 * 365), "本益比"]
        本益 = 本益[本益 > 0]
        if len(本益) > 60:
            摘要 += (f"\n- 近三年本益比區間：最低 {本益.min():.1f}、25% {本益.quantile(.25):.1f}、中位數 {本益.median():.1f}、"
                   f"75% {本益.quantile(.75):.1f}、最高 {本益.max():.1f}（目前 {數(r['本益比'])}）")
        淨 = 全.loc[全["date"] >= 最新日 - pd.Timedelta(days=3 * 365), "淨值比"] if "淨值比" in 全 else pd.Series(dtype=float)
        淨 = 淨[淨 > 0]
        if len(淨) > 60:
            摘要 += (f"\n- 近三年股價淨值比區間：最低 {淨.min():.2f}、中位數 {淨.median():.2f}、最高 {淨.max():.2f}"
                   f"（目前 {數(r['淨值比'], '{:.2f}')}，每股淨值約 {數(r['收盤'] / r['淨值比'] if r['淨值比'] else np.nan)}）")
        合約摘要 = engine.合約負債摘要(代號)
        if 合約摘要:
            摘要 += "\n" + 合約摘要
        摘要 += f"\n- 建議評價方法：{engine.評價方法建議(r.get('產業'), r.get('近三季EPS'))}"
        if not 代號.startswith("0"):
            try:
                公司 = 公司文字(公司資料(代號))
                if 公司:
                    摘要 = "公司資料：\n" + 公司 + "\n\n最新數據：\n" + 摘要
            except Exception:
                pass
        預 = engine.預估EPS文字(r)
        if 預:
            摘要 += f"\n- {預}"
        鏈 = engine.產業鏈位置(代號, dict(zip(今日["代號"], 今日["名稱"])))
        if 鏈:
            摘要 += f"\n- 產業鏈位置：{鏈}"
        券們 = [x for x in 券商報告清單(st.session_state.get("_券商版本", 0)) if str(x.get("代號")) == 代號][:6]
        if 券們:
            摘要 += "\n\n使用者上傳的券商報告摘要（數字以此為準，再上網補充）：\n" + "\n".join(
                f"- {x.get('日期')} {x.get('券商')} {x.get('評等')}，目標價 {x.get('目標價')}（前次 {x.get('前次目標價')}），"
                f"EPS 今年 {x.get('EPS今年')}／明年 {x.get('EPS明年')}，{x.get('評價方法') or ''}；{x.get('理由') or ''}"
                + (f"〔{engine.報告標籤(x)}〕" if engine.報告標籤(x) else "") for x in 券們)
        全券 = [x for x in 券商報告清單(st.session_state.get("_券商版本", 0)) if str(x.get("代號")) == 代號]
        if 全券:
            摘要 += "\n- 券商共識：" + engine.共識文字(engine.券商共識(全券, float(r["收盤"])))
            集 = [x for x in engine.集體升降評(全券) if x[0] == 代號]
            if 集:
                摘要 += "\n- 近 3 天集體調整：" + "；".join(f"{家} 家{方}目標價（{名}）" for _, _, 方, 家, 名 in 集)
        try:
            網 = engine.網紅觀點摘要(網紅說法清單(st.session_state.get("_網紅版本", 0)), 指標, 代號=代號)
            if 網:
                摘要 += "\n\n" + "\n".join(網)
        except Exception:
            pass
        try:
            K = 個股K線(代號)
            價文 = engine.價位摘要(K, 全.set_index("date")["成交值億"] if "成交值億" in 全 else None)
            if 價文:
                摘要 += "\n\n網站算好的格局與支撐壓力（還原股價）：\n" + "\n".join(f"- {x}" for x in 價文.splitlines())
        except Exception:
            pass
        if 新聞 is not None and not 新聞.empty:
            摘要 += "\n\n近半年新聞標題（新到舊）：\n" + "\n".join(
                f"- {engine.新聞日期標籤(x, '%Y-%m-%d')} {x['標題']}（{x['來源']}）"
                for _, x in 新聞.head(60).iterrows())
            if "舊聞" in 新聞.columns:
                摘要 += "\n（標「舊聞」的是 30 天以前的消息；「舊聞重提」代表同一件事之前就報導過，判斷時要當成已知消息、可能已反映在股價。）"

        try:
            紀錄們 = AI紀錄快取(代號, 設定.get("GITHUB_TOKEN", ""))
        except Exception as 錯:
            紀錄們 = []
            權杖 = engine.清理金鑰(設定.get("GITHUB_TOKEN"))
            if "401" in str(錯) or not (權杖.startswith(("github_pat_", "ghp_")) and len(權杖) >= 40):
                原始 = str(設定.get("GITHUB_TOKEN", ""))
                怪字 = sorted({f"U+{ord(c):04X}" for c in 原始 if not 33 <= ord(c) <= 126})
                st.warning("Secrets 裡的 GITHUB_TOKEN 看起來不正確（可能貼上時被改到或少了字），"
                           "請刪掉那一行重新貼上；報告暫時只會存在網站上。\n\n"
                           f"檢查資訊（不含金鑰內容）：原始長度 {len(原始)}、清理後長度 {len(權杖)}（正確約 93）、"
                           f"開頭 {權杖[:11]}、特殊字元 {len([c for c in 原始 if not 33 <= ord(c) <= 126])} 個"
                           f"{' ' + ' '.join(怪字[:5]) if 怪字 else ''}、錯誤：{str(錯)[:80]}")
            else:
                st.caption(f"讀取過去的 AI 報告失敗：{錯}")
        上次 = 紀錄們[0] if 紀錄們 else None
        if 上次:
            卡 = engine.拆解AI建議(上次.get("內容", ""))[1] or {}
            摘要 += (f"\n\n上次網站 AI 報告（{上次['時間'][:10]}，當時收盤 {上次.get('收盤')}）：看法 {卡.get('看法')}、"
                   f"合理價 {卡.get('目標價合理')}、評價方法 {卡.get('評價方法')}、今年 EPS {卡.get('今年EPS')}、明年 EPS {卡.get('明年EPS')}、"
                   f"看錯條件 {卡.get('看錯條件')}")
        天數 = (pd.Timestamp.now(tz="Asia/Taipei").tz_localize(None).normalize()
                - pd.Timestamp(上次["時間"][:10])).days if 上次 else None
        過久 = int(設定.get("AI_STALE_DAYS", 7))
        if 上次:
            說明 = "今天" if 天數 == 0 else f"{天數} 天前"
            if 天數 >= 過久:
                st.warning(f"上次分析：{上次['時間']}（{說明}，當時收盤 {上次.get('收盤', '—')}）。已超過 {過久} 天，建議重新分析。")
            else:
                st.caption(f"上次分析：{上次['時間']}（{說明}，當時收盤 {上次.get('收盤', '—')}，{上次.get('引擎', '')}）")
        elif 可執行:
            st.caption(f"使用 {引擎}。AI 會彙整近半年新聞、法人觀點與網站數據，給出目標價、預估本益比與短中期看法，約需 1 分鐘。")

        可寫 = not (密碼 and not st.session_state.get("已解鎖"))
        a, b = st.columns(2)
        if a.button("📋 複製分析指令（Gemini／Claude App）", key="複製指令", width="stretch"):
            st.session_state["顯示指令"] = not st.session_state.get("顯示指令", False)
        if b.button("📥 貼上 AI 報告", key="貼上報告", width="stretch", disabled=not 可寫,
                    help=None if 可寫 else "請先在 01 市場總覽輸入庫存密碼解鎖"):
            st.session_state["顯示貼上"] = not st.session_state.get("顯示貼上", False)
        if st.session_state.get("顯示指令"):
            st.caption("按右上角的複製圖示，貼到 Gemini（建議選 Pro 或「深入研究」）或 Claude App；"
                       "已設定「台股個股分析師」Gem 或 Claude 技能的話也可以直接貼。回答完把整份（含最後的 json）用右邊「📥 貼上 AI 報告」存回網站。")
            st.code(f"# 任務\n請分析台股 {代號} {r['名稱']}，今天是 {pd.Timestamp.now(tz='Asia/Taipei'):%Y-%m-%d}。\n\n"
                    f"# 網站資料（{今天} 收盤，數字以這裡為準）\n{摘要}\n\n"
                    "# 要做的事\n1. 上網搜尋近六個月的新聞、月營收、法說會與券商報告（注意日期，舊聞不要當新聞）\n"
                    "2. 先寫公司介紹：主要產品與營收比重、主要客戶、產業地位（是不是龍頭）、競爭對手\n"
                    "3. 再依下面的規則寫分析報告，最後附 json\n\n"
                    f"# 報告規則\n{engine.AI系統提示}",
                    language=None, wrap_lines=True)
        if st.session_state.get("顯示貼上") and 可寫:
            with st.form("貼上表單", clear_on_submit=True):
                來源 = st.radio("報告來自", ["Gemini App", "Claude App", "其他"], horizontal=True)
                內容 = st.text_area("把 AI 的完整回答貼在這裡（最後的 json 區塊也要一起貼，網站才能做卡片）", height=220)
                if st.form_submit_button("💾 存成這檔的 AI 報告", type="primary"):
                    if len(內容.strip()) < 50:
                        st.warning("內容太短，請貼上完整的報告。")
                    elif not engine.拆解AI建議(內容)[0].strip() and not st.session_state.get("只貼json確認"):
                        st.session_state["只貼json確認"] = True
                        st.warning("這段只有最後的 json 卡片資料，沒有完整報告內文。建議回 Gemini 複製整份回答再貼；"
                                   "真的只要存卡片，再按一次存檔。")
                    else:
                        st.session_state.pop("只貼json確認", None)
                        新 = {"時間": pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m-%d %H:%M"),
                             "資料日期": 今天, "收盤": float(r["收盤"]), "引擎": 來源, "模型": "手動貼上",
                             "內容": 內容.strip(), "來源": []}
                        try:
                            永久 = engine.儲存AI紀錄(代號, 新, 設定)
                            st.success("已存檔" + ("（GitHub 永久保存）" if 永久 else "（暫存在網站上）") + "，下面的卡片已更新。")
                        except Exception as 錯:
                            st.error(f"存檔失敗：{錯}")
                        AI紀錄快取.clear()
                        紀錄們 = [新] + 紀錄們
                        上次, 天數 = 新, 0
                        st.session_state["顯示貼上"] = False

        if 可執行 and 引擎 == "Gemini":
            會鍵 = f"會診_{代號}_{今天}"
            if st.button("🩺 AI 多角色會診（技術／籌碼／基本面／唱反調，各 3 句）", key="會診鈕"):
                用量 = AI用量()
                if 用量.get(今天, 0) >= int(設定.get("AI_DAILY_LIMIT", 20)):
                    st.warning("今天的 AI 次數已達上限，明天再試。")
                else:
                    with st.spinner("4 位 AI 分析師討論中，約 20 秒…"):
                        try:
                            st.session_state[會鍵] = engine.AI多角色會診(代號, r["名稱"], 摘要, 金鑰, 模型)
                            用量[今天] = 用量.get(今天, 0) + 1
                        except Exception as 錯:
                            st.error(f"會診失敗：{錯}")
            if st.session_state.get(會鍵):
                with st.container(border=True):
                    st.markdown(st.session_state[會鍵])

        按鈕字 = f"✨ 產生 {代號} {r['名稱']} 的 AI 分析" if not 上次 else "🔄 重新分析"
        if 可執行 and st.button(按鈕字, key="AI按鈕", type="primary" if not 上次 or 天數 >= 過久 else "secondary"):
            用量 = AI用量()
            if 用量.get(今天, 0) >= int(設定.get("AI_DAILY_LIMIT", 20)):
                st.warning("今天的 AI 分析次數已達上限，明天再試。")
            else:
                with st.spinner("AI 整理中，約 1 分鐘…"):
                    try:
                        if 引擎 == "Gemini":  # 開了付費才有 Google 搜尋，Secrets 設 GEMINI_SEARCH = true
                            文字, 來源 = engine.AI分析Gemini(代號, r["名稱"], 摘要, 金鑰, 模型,
                                                         搜尋=str(設定.get("GEMINI_SEARCH", "")).lower() == "true")
                        else:
                            文字, 來源 = engine.AI分析(代號, r["名稱"], 摘要, 金鑰, 模型)
                        用量[今天] = 用量.get(今天, 0) + 1
                        新 = {"時間": pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m-%d %H:%M"),
                             "資料日期": 今天, "收盤": float(r["收盤"]), "引擎": 引擎, "模型": 模型,
                             "內容": 文字, "來源": 來源}
                        try:
                            永久 = engine.儲存AI紀錄(代號, 新, 設定)
                        except Exception as 錯:
                            永久 = False
                            st.warning(f"報告已產生，但存到 GitHub 失敗：{錯}")
                        if not 永久 and not engine.清理金鑰(設定.get("GITHUB_TOKEN")):
                            st.caption("目前報告只暫存在網站上，網站重新啟動後會消失。設定 GITHUB_TOKEN 後可永久保存。")
                        AI紀錄快取.clear()
                        紀錄們 = [新] + 紀錄們
                        上次 = 新
                    except Exception as 錯:
                        st.error(f"AI 分析失敗：{錯}")
        if 上次:
            內文, 建議 = engine.拆解AI建議(上次["內容"])
            if 上次.get("建議"):
                建議 = 上次["建議"]
            elif 可執行 and (not 建議 or "目標價合理" not in 建議):
                # 舊報告：自動請 AI 從報告整理出卡片資料，存回紀錄，下次就不用再整理
                try:
                    with st.spinner("把這份報告整理成卡片…"):
                        補 = engine.AI補卡片(內文, 引擎, 金鑰, 模型)
                    if 補:
                        建議 = 補
                        上次 = dict(上次, 建議=補)
                        engine.儲存AI紀錄(代號, 上次, 設定, 取代=True)
                        AI紀錄快取.clear()
                except Exception as 錯:
                    st.caption(f"整理卡片失敗：{錯}")
            if 建議:
                def 價(k):
                    v = 建議.get(k)
                    return float(v) if isinstance(v, (int, float)) else np.nan
                看 = 建議.get("看法") or "—"
                合理 = 價("目標價合理")
                空間 = (合理 / r["收盤"] - 1) * 100 if pd.notna(合理) else np.nan
                色 = {"偏多": 紅, "偏空": 綠}.get(看, 灰)
                段落(f"AI 建議 // {上次['時間'][:10]}")
                卡片格([卡片("AI 看法", 看, "舊版報告，重新分析後會有目標價卡片", 色)] if "目標價合理" not in 建議 else [
                    卡片("AI 看法", 看, f"短線 {建議.get('短線') or '—'} · 中期 {建議.get('中期') or '—'}", 色),
                    卡片("合理目標價", 數(合理), f"距現價 {數(空間, '{:+.1f}', '%')}", 漲跌色(空間 if pd.notna(空間) else 0)),
                    卡片("目標價區間", f"{數(價('目標價保守'), '{:,.0f}')} ~ {數(價('目標價樂觀'), '{:,.0f}')}",
                         f"券商目標價 {數(價('券商目標價'), '{:,.0f}')}"),
                    卡片("預估本益比", 數(價("預估本益比"), "{:.1f}", " 倍"),
                         f"EPS 今年 {數(價('今年EPS'))} / 明年 {數(價('明年EPS'))}"),
                    卡片("支撐 / 壓力", f"{數(價('支撐'), '{:,.0f}')} / {數(價('壓力'), '{:,.0f}')}"),
                    卡片("停損參考", 數(價("停損"), "{:,.0f}"), 建議.get("看錯條件") or "", 綠),
                ])
                if 建議.get("評價方法"):
                    st.caption(f"目標價怎麼算：{建議['評價方法']}")
                if 建議.get("一句話"):
                    st.markdown(f"**AI 結論：** {建議['一句話']}")
                try:
                    全史 = 個股全史(代號, _版本)
                    近 = 全史[全史["date"] >= 全史["date"].max() - pd.Timedelta(days=3 * 365)]
                    提醒 = engine.檢查AI目標價(建議, r["收盤"], r["本益比"] if r["本益比"] > 0 else None, 近["收盤"].max(),
                                          共識={k: r.get(k) for k in ("預估EPS今年", "預估EPS明年", "預估年度")})
                except Exception:
                    提醒 = engine.檢查AI目標價(建議, r["收盤"])
                if 提醒:
                    st.warning("🔎 數字檢查（網站自動比對，AI 的數字未修改）\n\n" + "\n".join(f"- {句}" for 句 in 提醒))
            if 內文.strip():
                with st.expander("完整 AI 報告", expanded=not 建議):
                    st.markdown(內文)
            else:
                st.caption("這份只有卡片資料（json），沒有完整報告內文。")
            if 上次.get("來源"):
                with st.expander(f"參考來源（{len(上次['來源'])}）"):
                    st.markdown("\n".join(f"- [{標題}]({網址})" for 網址, 標題 in 上次["來源"]))
            PDF按鈕(代號, r, 建議, 內文, 上次["時間"])
            if len(紀錄們) > 1:
                with st.expander(f"過去的 AI 報告（{len(紀錄們) - 1}）"):
                    for 舊 in 紀錄們[1:]:
                        st.markdown(f"#### {舊['時間']}（當時收盤 {舊.get('收盤', '—')}，{舊.get('引擎', '')}）")
                        st.markdown(engine.拆解AI建議(舊["內容"])[0])
                        st.divider()
    個股券商報告(代號, float(r["收盤"]))
    個股網紅說法(代號)
    個股筆記(代號)
