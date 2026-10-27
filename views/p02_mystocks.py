# 02 我的股票：由 app.py 的 執行頁面() 在同一個命名空間執行，可直接用 app.py 的共用函式與資料。
市場對照 = dict(zip(今日["代號"], 今日["市場"]))


def 標警示(表):
    """名稱前面加 ⚠️（處置股、注意股）。"""
    警 = 警示表(_版本)
    if 警 and "代號" in 表.columns and "名稱" in 表.columns:
        表 = 表.copy()
        表["名稱"] = [("⚠️ " + n if c in 警 else n) for c, n in zip(表["代號"], 表["名稱"])]
    return 表


# ---------- 我的庫存 ----------
def 我的庫存():
    """庫存放在 Streamlit 的 Secrets（不會出現在公開的 GitHub）。"""
    try:
        設定 = dict(st.secrets)
    except Exception:
        設定 = {}
    if "holdings" not in 設定:
        段落("PORTFOLIO // 我的庫存")
        st.info("尚未設定庫存。到 Streamlit 的 App settings →「Secrets」貼上庫存清單即可顯示。")
        return
    密碼 = str(設定.get("password", ""))
    if 密碼 and not st.session_state.get("已解鎖"):
        段落("PORTFOLIO // 我的庫存")
        輸入 = st.text_input("輸入密碼查看庫存", type="password")
        if 輸入 and hmac.compare_digest(輸入, 密碼):
            st.session_state["已解鎖"] = True
            st.query_params["k"] = 登入憑證()
            st.rerun()
        elif 輸入:
            st.error("密碼不正確")
        return

    持股 = pd.read_csv(io.StringIO(str(設定["holdings"]).strip()), dtype={"代號": str})
    庫存區(持股)
    try:
        庫存歷史區(持股)
    except Exception as e:
        st.caption(f"庫存走勢暫時算不出來（{type(e).__name__}）")
    if 密碼:
        a, b = st.columns([4, 1])
        a.caption("已記住登入（網址裡的 k=… 就是通行證，請勿分享登入後的網址）。可把這個網址加入書籤或主畫面。")
        if b.button("🔒 登出", key="登出"):
            st.session_state["已解鎖"] = False
            st.query_params.pop("k", None)
            st.rerun()


def 庫存歷史區(持股):
    """以目前持股回推近一年的市值走勢，加上這段期間領到的股利（以目前股數估算）。"""
    股數 = 持股.assign(代號=持股["代號"].astype(str).str.strip()).groupby("代號")["股數"].sum()
    價 = 指標[指標["代號"].isin(股數.index)].pivot_table(index="date", columns="代號", values="收盤")
    價 = 價[價.index >= 價.index.max() - pd.Timedelta(days=365)].ffill()
    有 = [c for c in 股數.index if c in 價.columns and 價[c].notna().any()]
    if not 有:
        return
    價 = 價[有].bfill()
    市值 = (價 * 股數[有]).sum(axis=1)
    除 = engine.讀取全部除權息()
    除 = 除[除["code"].isin(有) & (除["date"] > 價.index.min()) & (除["date"] <= 價.index.max())]
    除 = 除.assign(金額=除["value"] * 除["code"].map(股數))
    累積股利 = 除.groupby("date")["金額"].sum().reindex(市值.index, fill_value=0).cumsum()
    段落("HISTORY // 庫存市值走勢（以目前持股回推一年）")
    基準 = 指標[指標["代號"] == "0050"].set_index("date")["還原價"].reindex(市值.index).ffill()
    卡片格([
        卡片("一年前市值", f"{市值.iloc[0]:,.0f}", f"{市值.index[0]:%Y/%m/%d}"),
        卡片("現在市值", f"{市值.iloc[-1]:,.0f}", f"{(市值.iloc[-1] / 市值.iloc[0] - 1) * 100:+.1f}%",
             漲跌色(市值.iloc[-1] - 市值.iloc[0])),
        卡片("期間股利（估）", f"{累積股利.iloc[-1]:,.0f}", f"{len(除)} 次除權息，含股票股利換算"),
        卡片("含息報酬", f"{((市值.iloc[-1] + 累積股利.iloc[-1]) / 市值.iloc[0] - 1) * 100:+.1f}%",
             f"同期 0050 {(基準.iloc[-1] / 基準.iloc[0] - 1) * 100:+.1f}%" if 基準.notna().all() else ""),
    ])
    圖 = go.Figure([go.Scatter(x=市值.index, y=市值 + 累積股利, name="市值＋領到的股利", line=dict(color="#FFC24B", width=1.4)),
                    go.Scatter(x=市值.index, y=市值, name="股票市值", line=dict(color=青, width=2))])
    if 基準.notna().all():
        圖.add_trace(go.Scatter(x=市值.index, y=基準 / 基準.iloc[0] * 市值.iloc[0], name="同金額買 0050（含息）",
                                line=dict(color=灰, width=1, dash="dot")))
    圖.update_layout(hovermode="x unified", legend=dict(orientation="h", y=1.12))
    圖.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    st.plotly_chart(圖表外觀(圖, 300), width="stretch")
    預 = engine.讀取全部除權息(預告=True)
    預 = 預[預["code"].isin(股數.index) & (預["date"] >= pd.Timestamp.now().normalize())]
    if len(預):
        st.markdown("**📅 即將除權息**　" + "；".join(
            f"{r['date']:%m/%d} {市場名稱.get(r['code'], r['code'])} 除{r['type']}"
            + (f"，現金 {r['cash']:g} 元 × {股數[r['code']]:,.0f} 股 ≈ {r['cash'] * 股數[r['code']]:,.0f} 元" if pd.notna(r["cash"]) and r["cash"] else "")
            for _, r in 預.sort_values("date").iterrows()))
    沒 = [c for c in 股數.index if c not in 有]
    st.caption("假設這一年都持有「目前的股數」回推，不是實際的買賣紀錄；股利以除權息日的權值＋息值 × 目前股數估算。"
               + (f"沒有歷史股價、未計入：{'、'.join(沒)}" if 沒 else ""))


@st.fragment(run_every=30 if engine.盤中時間() else None)
def 庫存區(持股):
    """盤中每 30 秒自動抓一次即時報價；收盤後用資料庫的收盤價。"""
    即時 = None
    if engine.盤中時間():
        try:
            即時 = engine.即時報價(持股["代號"].astype(str).str.strip().tolist(), 市場對照)
        except Exception:
            st.caption("即時報價暫時抓不到，先顯示最近收盤價。")
    明細, 合計 = engine.計算庫存(持股, 今日, engine.讀取上櫃最新(), engine.讀取興櫃最新(), 即時)
    日期 = 合計["日期"].strftime("%Y/%m/%d") if pd.notna(合計["日期"]) else "—"
    if 即時 is not None and not 即時.empty:
        日期 += f" {即時['time'].dropna().max()} 即時"
    段落(f"PORTFOLIO // 我的庫存　{日期}")
    卡片格([
        卡片(f"今日損益 · {日期}", f"{合計['今日損益']:+,.0f}", f"{合計['今日損益(%)']:+.2f}%",
           漲跌色(合計["今日損益"])),
        卡片("累積損益", f"{合計['累積損益']:+,.0f}", f"{合計['累積損益(%)']:+.2f}%", 漲跌色(合計["累積損益"])),
        卡片("股票市值", f"{合計['股票市值']:,.0f}", f"成本 {合計['總成本']:,.0f}"),
    ])
    a, b = st.columns([4, 1])
    依據 = a.segmented_control("排序", ["今日損益", "漲跌幅", "總損益", "報酬率(%)", "股價", "總成本"],
                              default="今日損益", key="庫存排序")
    方向 = b.segmented_control("順序", ["大→小", "小→大"], default="大→小", key="庫存順序")
    明細 = 明細.sort_values(依據 or "今日損益", ascending=(方向 == "小→大"), na_position="last")
    明細 = 標警示(明細)
    點選表(明細, 上色(明細), "庫存表", height=35 * (len(明細) + 1) + 3)
    if st.session_state.get("要跳轉"):
        st.rerun(scope="app")  # 這裡在自動更新區塊裡，要整頁重跑才會切到個股查詢
    st.caption("點一下股票可看個股查詢，也可以直接點表格標題排序。")
    if 合計["缺報價"]:
        st.caption(f"以下代號暫時沒有報價，未計入合計：{'、'.join(合計['缺報價'])}")


def 自選股區():
    段落("WATCHLIST // 自選股")
    自選 = 自選股清單()
    群組們 = list(自選) or ["自選股"]
    if "自選群組_切換" in st.session_state:
        st.session_state["自選群組"] = st.session_state.pop("自選群組_切換")
    if st.session_state.get("自選群組") not in 群組們:
        st.session_state["自選群組"] = 群組們[0]
    if len(群組們) > 1:
        群組績效(自選)
        群組 = st.segmented_control("群組", 群組們, key="自選群組", label_visibility="collapsed") or 群組們[0]
    else:
        群組 = 群組們[0]
    代號們 = [c for c in 自選.get(群組, []) if c in 市場對照]
    if 代號們:
        自選表(tuple(代號們))
    else:
        st.info("這個群組還沒有股票。可以在下面「編輯自選股」加入，或在個股查詢頁按「☆ 加入自選股」。")
    with st.expander("✏️ 編輯自選股"):
        對照 = {v.split()[0]: v for v in 股票選項}
        選 = st.multiselect(f"「{群組}」的股票（可打代號或名稱搜尋）", 股票選項,
                           default=[對照[c] for c in 代號們 if c in 對照], key=f"自選編輯_{群組}")
        if st.button("💾 儲存", key="自選儲存"):
            存自選股({**自選, 群組: [v.split()[0] for v in 選]})
            st.rerun()
        a, b = st.columns([3, 1])
        新名 = a.text_input("新增群組", placeholder="例如：長抱、短線、觀察", key="自選新群組").strip()
        if b.button("＋ 建立", key="自選建立") and 新名 and 新名 not in 自選:
            存自選股({**自選, 新名: []})
            st.session_state["自選群組_切換"] = 新名
            st.rerun()
        if len(群組們) > 1 and 代號們:
            a, b, c = st.columns([2, 2, 1])
            移 = a.selectbox("把股票移到別的群組", [對照.get(x, x) for x in 代號們], key="自選移動股")
            到 = b.selectbox("移到", [g for g in 群組們 if g != 群組], key="自選移動到")
            if c.button("➜ 移動", key="自選移動") and 移 and 到:
                x = 移.split()[0]
                存自選股({g: ([y for y in v if y != x] if g == 群組 else v + [x] if g == 到 and x not in v else v)
                       for g, v in 自選.items()})
                st.rerun()
        if len(群組們) > 1 and st.button(f"🗑 刪除「{群組}」群組", key="自選刪除"):
            存自選股({k: v for k, v in 自選.items() if k != 群組})
            st.rerun()


def 群組績效(自選):
    """每個群組的平均表現（等權重），比較長抱、短線、觀察哪一組比較好。"""
    表 = 今日.set_index("代號")
    紀錄 = 自選紀錄()
    列們 = []
    for 群, 代號們 in 自選.items():
        有 = [c for c in 代號們 if c in 表.index]
        if not 有:
            continue
        t = 表.loc[有]
        加入 = pd.Series({c: (紀錄.get(c, {}).get("收盤") or np.nan) for c in 有}, dtype=float)
        至今 = (t["收盤"] / 加入 - 1) * 100
        列們.append({"群組": 群, "檔數": len(有), "今日%": t["漲跌幅"].mean(), "5日%": t["5日漲幅"].mean(),
                    "20日%": t["20日漲幅"].mean(), "加入至今%": 至今.mean(),
                    "最強": f"{t['漲跌幅'].idxmax()} {t.loc[t['漲跌幅'].idxmax(), '名稱']}" if t["漲跌幅"].notna().any() else "—"})
    if not 列們:
        return
    績 = pd.DataFrame(列們)
    數欄 = ["今日%", "5日%", "20日%", "加入至今%"]
    樣式 = 績.style.format({k: "{:+.2f}" for k in 數欄}, na_rep="—").map(lambda v: f"color:{漲跌色(v)}", subset=數欄)
    表格(樣式, hide_index=True, width="stretch", height=35 * (len(績) + 1) + 3)
    st.caption("各群組等權重平均；最強 = 今天漲最多的一檔。")


@st.fragment(run_every=30 if engine.盤中時間() else None)
def 自選表(代號們):
    """盤中每 30 秒更新即時報價，收盤後用資料庫的收盤價。"""
    表 = 今日.set_index("代號").reindex(list(代號們)).reset_index()
    if engine.盤中時間():
        try:
            即時 = engine.即時報價(list(代號們), 市場對照).dropna(subset=["close"]).set_index("code")
            有 = 表["代號"].isin(即時.index)
            表.loc[有, "收盤"] = 表.loc[有, "代號"].map(即時["close"])
            表.loc[有, "漲跌"] = 表.loc[有, "代號"].map(即時["change"])
            表.loc[有, "漲跌幅"] = (表["漲跌"] / (表["收盤"] - 表["漲跌"]) * 100).round(2)
            st.caption(f"盤中即時 {即時['time'].dropna().max()}（約每 30 秒更新）")
        except Exception:
            st.caption("即時報價暫時抓不到，先顯示最近收盤價。")
    提醒 = 提醒清單()
    表["提醒"] = 表["代號"].map(lambda c: 提醒文字(提醒.get(c, {})))
    for i, 列 in 表.iterrows():
        設 = 提醒.get(列["代號"], {})
        if (設.get("上") and 列["收盤"] >= 設["上"]) or (設.get("下") and 列["收盤"] <= 設["下"]):
            表.at[i, "提醒"] = "🔔 " + 表.at[i, "提醒"]
    紀錄 = 自選紀錄()
    表["加入日期"] = 表["代號"].map(lambda c: 紀錄.get(c, {}).get("日期", "—"))
    表["加入價"] = 表["代號"].map(lambda c: 紀錄.get(c, {}).get("收盤")).astype(float)
    表["加入至今%"] = ((表["收盤"] / 表["加入價"] - 1) * 100).round(2)
    顯示 = 表[["名稱", "收盤", "漲跌幅", "加入日期", "加入價", "加入至今%", "提醒", "成交張數", "5日漲幅", "20日漲幅",
              "法人買超", "本益比", "殖利率", "代號"]]
    顯示 = 顯示.rename(columns={"收盤": "股價", "法人買超": "法人(張)"})
    顯示 = 標警示(顯示)
    點選表(顯示, 上色(顯示), "自選表", height=35 * (len(顯示) + 1) + 3)
    if st.session_state.get("要跳轉"):
        st.rerun(scope="app")
    st.caption("點一下股票可看個股查詢。加入價 = 加入當時最新的收盤價，加入至今% = 現在股價比加入價漲跌多少。"
               "法人(張) = 三大法人今日買賣超。🔔 = 已到達提醒價格（到價提醒在個股頁設定）。")


# ---------- 02 我的股票：庫存、自選股 ----------
我的庫存()
if 可編輯():
    自選股區()
else:
    st.caption("自選股要先輸入上面的密碼解鎖才會顯示。")
if 可編輯():
    關注 = tuple(sorted(set(庫存代號() or []) | {c for v in 自選股清單().values() for c in v}))
    段落("CALENDAR // 近 30 天重要日程（庫存、自選股）")
    日程 = 日程資料(關注, _版本)
    if 日程.empty:
        st.caption("近 30 天沒有庫存、自選股的法說會。")
    else:
        表格(日程.assign(日期=日程["日期"].dt.strftime("%m/%d（%a）"))[["日期", "類型", "股票", "說明"]],
                     hide_index=True, width="stretch")
    警 = {c: 警示表(_版本)[c] for c in 關注 if c in 警示表(_版本)}
    if 警:
        段落("WARNING // 處置股、注意股")
        for c, t in 警.items():
            st.warning(f"{c} {市場名稱.get(c, '')}：{t}")
    st.caption("法說會資料：公開資訊觀測站（本月、下月）。每天收盤摘要的 LINE 也會提醒明後天的法說會。")
