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
    """庫存來源：Streamlit 的 Secrets（不會出現在公開的 GitHub），或交易日記推算（加密存放）。"""
    設定 = _設定()
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

    持股, 來源 = 目前持股()
    if 持股 is None:
        段落("PORTFOLIO // 我的庫存")
        st.info("尚未設定庫存。到 Streamlit 的 App settings →「Secrets」貼上庫存清單，或在下方「交易日記」記下買賣，就會顯示。")
    else:
        if 來源 == "交易日記":
            st.caption("📒 這裡的庫存是由下方「交易日記」的買賣紀錄推算出來的。")
        庫存區(持股)
        try:
            庫存歷史區(持股)
        except Exception as e:
            st.caption(f"庫存走勢暫時算不出來（{type(e).__name__}）")
        try:
            風險體檢區(持股)
        except Exception as e:
            st.caption(f"庫存體檢暫時算不出來（{type(e).__name__}）")
    交易日記區()
    if 密碼:
        a, b = st.columns([4, 1])
        a.caption("已記住登入（網址裡的 k=… 就是通行證，請勿分享登入後的網址）。可把這個網址加入書籤或主畫面。")
        if b.button("🔒 登出", key="登出"):
            st.session_state["已解鎖"] = False
            st.query_params.pop("k", None)
            st.rerun()


@st.cache_data(ttl=3600, show_spinner=False)
def 風險資料(持股, _資料版本):
    產業 = dict(zip(今日["代號"], 今日["產業"])) if "產業" in 今日.columns else {}
    K = 指數K線("TAIEX", _資料版本)
    return engine.庫存風險(持股, 指標, K.set_index("date")["close"], 產業, 名稱表=市場名稱)


def 風險體檢區(持股):
    r = 風險資料(持股[["代號", "股數"]].assign(代號=持股["代號"].astype(str).str.strip()), _版本)
    if not r:
        return
    段落("RISK // 庫存風險體檢")
    卡片格([
        卡片("整體 Beta", f"{r['Beta']:.2f}", "大盤漲跌 1%，庫存平均漲跌幾 %", 紅 if r["Beta"] > 1.2 else "#EDEDED"),
        卡片("大盤跌 10% 估計", f"{r['跌10%']:+,.0f}", f"約 {r['Beta'] * -10:+.1f}%（用 Beta 推算）", 綠),
        卡片("近一年最大單日跌", f"{r['最大單日'] * 100:+.1f}%",
             f"{r['最大單日日']:%Y/%m/%d}" if r["最大單日日"] is not None else "", 綠),
        卡片("近一年最大回撤", f"{r['最大回撤'] * 100:.1f}%", f"大盤同期 {r['大盤最大回撤'] * 100:.1f}%",
             綠 if r["最大回撤"] < r["大盤最大回撤"] else "#EDEDED"),
    ])
    for 句 in r["提醒"]:
        st.warning("⚠️ " + 句)
    if not r["提醒"]:
        st.success("沒有明顯過度集中：單一股票不到 3 成、同產業不到一半、整體 Beta 不高。")
    左, 右 = st.columns([1, 1])
    with 左:
        產 = r["產業"].sort_values()
        圖 = go.Figure(go.Bar(x=產.values * 100, y=產.index, orientation="h", marker_color=青,
                              text=[f"{v * 100:.0f}%" for v in 產.values], textposition="outside"))
        圖.update_layout(title="產業占比（依市值）", xaxis_title="%")
        st.plotly_chart(圖表外觀(圖, 60 + 32 * len(產)), width="stretch")
    with 右:
        表 = r["占比"].reset_index(names="代號")
        表["名稱"] = 表["代號"].map(市場名稱).fillna(表["代號"])
        表格(表[["名稱", "占比%", "Beta", "產業", "市值", "代號"]].style.format({"占比%": "{:.1f}", "Beta": "{:.2f}", "市值": "{:,.0f}"}, na_rep="—"),
             hide_index=True, width="stretch")
    if r["相關"]:
        st.caption("走勢最同步的組合（相關係數，1＝完全同漲同跌）：" + "、".join(
            f"{市場名稱.get(a, a)}－{市場名稱.get(b, b)} {v:.2f}" for a, b, v in r["相關"]))
    st.caption(f"用近 {r['天數']} 個交易日的每日漲跌計算。Beta＝個股跟加權指數一起動的程度（1＝跟大盤一樣，1.5＝大盤跌 1% 它平均跌 1.5%）；"
               "「大盤跌 10%」是用 Beta 推算的平均情況，實際可能更多或更少。")


交易欄 = ["日期", "代號", "買賣", "股數", "價格", "手續費", "稅", "停損", "目標", "理由"]


def 交易日記區():
    段落("JOURNAL // 交易日記")
    if not _密碼():
        st.caption("⚠️ 網站沒有設密碼，交易日記會以明文存到公開的 GitHub 分支；在 Secrets 設 password 就會自動加密。")
    if 錯 := st.session_state.pop("交易日記讀取錯誤", None):
        st.error(f"交易日記讀不到：{錯}")
    日記 = 交易日記()
    交易們 = 日記["交易"]
    現價 = dict(zip(今日["代號"], 今日["收盤"]))
    實, 庫, 摘 = engine.交易日記統計(交易們, 現價)
    if 交易們:
        數 = lambda v, f="{:+,.0f}": f.format(v) if pd.notna(v) else "—"
        卡片格([
            卡片("已實現損益", 數(摘["已實現損益"]), f"賣出 {摘['賣出筆數']} 筆", 漲跌色(摘["已實現損益"])),
            卡片("勝率", 數(摘["勝率"], "{:.0f}%"), "賣出時賺錢的比例"),
            卡片("賺賠比", 數(摘["賺賠比"], "{:.2f}"), f"平均賺 {數(摘['平均賺'])}／平均賠 {數(摘['平均賠'])}"),
            卡片("平均持有", 數(摘["平均持有天數"], "{:.0f} 天"), "從買進到賣出"),
            卡片("未實現損益", 數(摘["未實現損益"]), f"還持有 {len(庫)} 檔", 漲跌色(摘["未實現損益"])),
        ])
    else:
        st.caption("把每一筆買賣記下來（含當時的理由與停損），網站會自動算已實現損益、勝率、平均持有天數，"
                   "之後回頭對答案。有設密碼時，紀錄會加密後才存到 GitHub，別人看不到內容。")
    分頁 = st.tabs(["➕ 記一筆", "📒 全部紀錄", "✅ 已實現損益", "🎯 停損／目標", "⚙️ 匯入匯出"])
    with 分頁[0]:
        with st.form("記一筆", clear_on_submit=True):
            a, b, c = st.columns([2, 1, 1])
            股 = a.selectbox("股票", 股票選項, index=None, placeholder="輸入代號或名稱")
            買賣 = b.segmented_control("買賣", ["買", "賣"], default="買")
            日 = c.date_input("日期", value=dt.date.today())
            a, b, c = st.columns(3)
            股數 = a.number_input("股數", min_value=1, value=1000, step=1000, help="一張 = 1000 股；零股直接填股數")
            價格 = b.number_input("成交價", min_value=0.0, value=0.0, step=0.05, format="%.2f")
            折扣 = c.number_input("手續費折扣", min_value=0.1, max_value=1.0, value=float(日記.get("折扣", 1.0)), step=0.05,
                                help="例如 6 折填 0.6；手續費＝成交金額 × 0.1425% × 折扣，最低 20 元")
            a, b = st.columns(2)
            停損 = a.number_input("停損價（買進時填，可空白）", min_value=0.0, value=0.0, step=0.05, format="%.2f")
            目標 = b.number_input("目標價（可空白）", min_value=0.0, value=0.0, step=0.05, format="%.2f")
            理由 = st.text_input("理由（為什麼買／賣）", placeholder="例如：站回 5 週線、月營收創新高、跌破停損")
            送出 = st.form_submit_button("記下來", type="primary")
        if 送出:
            if not 股 or 價格 <= 0 or not 買賣:
                st.error("請選股票、填成交價。")
            else:
                代 = 股.split(" ")[0]
                費, 稅 = engine.交易費用(代, 買賣, 股數, 價格, 折扣)
                持有 = 庫.set_index("代號")["股數"].get(代, 0) if len(庫) else 0
                if 買賣 == "賣" and 股數 > 持有:
                    st.warning(f"日記裡 {代} 只有 {持有:,.0f} 股，賣出 {股數:,.0f} 股會有一部分配不到買進紀錄（之前的買進可以補記）。")
                新 = {"日期": f"{日:%Y-%m-%d}", "代號": 代, "買賣": 買賣, "股數": int(股數), "價格": float(價格),
                     "手續費": 費, "稅": 稅, "停損": float(停損) or None, "目標": float(目標) or None, "理由": 理由.strip()}
                存交易日記({**日記, "交易": 交易們 + [新], "折扣": float(折扣)})
                st.rerun()
    with 分頁[1]:
        if not 交易們:
            st.caption("還沒有紀錄。")
        else:
            表 = pd.DataFrame(交易們).reindex(columns=交易欄)
            表["名稱"] = 表["代號"].map(市場名稱).fillna("")
            表["金額"] = (表["股數"] * 表["價格"]).round()
            表 = 表.sort_values("日期", ascending=False)
            表格(表[["日期", "名稱", "買賣", "股數", "價格", "金額", "手續費", "稅", "停損", "目標", "理由", "代號"]]
                 .style.map(lambda v: f"color:{紅 if v == '買' else 綠}", subset=["買賣"])
                 .format({"股數": "{:,.0f}", "價格": "{:,.2f}", "金額": "{:,.0f}", "手續費": "{:,.0f}", "稅": "{:,.0f}",
                          "停損": "{:,.2f}", "目標": "{:,.2f}"}, na_rep="—"), hide_index=True, width="stretch")
            標籤 = [f"{t['日期']} {t['買賣']} {t['代號']} {市場名稱.get(t['代號'], '')} {t['股數']:,} 股 @{t['價格']:g}" for t in 交易們]
            刪 = st.multiselect("要刪除的紀錄", range(len(交易們)), format_func=lambda i: 標籤[i], key="刪交易")
            if 刪 and st.button(f"🗑️ 刪除 {len(刪)} 筆", key="刪交易鈕"):
                存交易日記({**日記, "交易": [t for i, t in enumerate(交易們) if i not in set(刪)]})
                st.rerun()
    with 分頁[2]:
        if 實.empty:
            st.caption("還沒有賣出紀錄。")
        else:
            顯 = 實.assign(名稱=實["代號"].map(市場名稱).fillna("")).sort_values("賣出日", ascending=False)
            表格(顯[["賣出日", "名稱", "股數", "買進均價", "賣出價", "損益", "報酬率(%)", "持有天數", "理由", "代號"]].style
                 .map(lambda v: f"color:{漲跌色(v)}", subset=["損益", "報酬率(%)"])
                 .format({"股數": "{:,.0f}", "買進均價": "{:,.2f}", "賣出價": "{:,.2f}", "損益": "{:+,.0f}", "報酬率(%)": "{:+.2f}"}),
                 hide_index=True, width="stretch")
            st.caption("先進先出：賣出時先配最早買進的那幾筆。損益已扣買賣手續費與證交稅。")
    with 分頁[3]:
        檢 = engine.停損目標檢查(交易們, 庫, 現價) if len(庫) else pd.DataFrame()
        if 檢.empty:
            st.caption("還持有的股票沒有記停損／目標價。")
        else:
            檢["名稱"] = 檢["代號"].map(市場名稱).fillna("")
            表格(檢[["名稱", "狀態", "現價", "停損", "距停損%", "目標", "距目標%", "買進理由", "代號"]].style
                 .format({"現價": "{:,.2f}", "停損": "{:,.2f}", "目標": "{:,.2f}", "距停損%": "{:+.1f}", "距目標%": "{:+.1f}"}, na_rep="—"),
                 hide_index=True, width="stretch")
            st.caption("距停損%＝現價比停損價高多少（越小越危險）；距目標%＝還要漲多少才到目標。用最近一次有填的買進紀錄。")
    with 分頁[4]:
        設定 = _設定()
        if "holdings" in 設定 and len(庫):
            當 = st.toggle("用交易日記當「我的庫存」（不用再改 Secrets）", value=bool(日記.get("當作庫存")), key="日記當庫存")
            if 當 != bool(日記.get("當作庫存")):
                存交易日記({**日記, "當作庫存": 當})
                st.rerun()
            秘 = pd.read_csv(io.StringIO(str(設定["holdings"]).strip()), dtype={"代號": str})
            秘 = 秘.assign(代號=秘["代號"].astype(str).str.strip()).groupby("代號")["股數"].sum()
            差 = pd.concat([秘.rename("Secrets"), 庫.set_index("代號")["股數"].rename("交易日記")], axis=1).fillna(0)
            差 = 差[差["Secrets"] != 差["交易日記"]]
            if len(差):
                st.caption("Secrets 庫存和交易日記不一致的股票（日記少記的買進可以補上）：" + "、".join(
                    f"{市場名稱.get(c, c)} {r['Secrets']:,.0f}／{r['交易日記']:,.0f} 股" for c, r in 差.iterrows()))
            else:
                st.caption("✅ Secrets 庫存和交易日記推算的股數一致。")
        if 交易們:
            st.download_button("⬇️ 下載交易日記 CSV", pd.DataFrame(交易們).reindex(columns=交易欄).to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"交易日記_{dt.date.today():%Y%m%d}.csv", mime="text/csv")
        上傳 = st.file_uploader("匯入 CSV（欄位：日期,代號,買賣,股數,價格，可加 手續費,稅,停損,目標,理由）", type=["csv"], key="匯入日記")
        if 上傳 is not None and st.button("匯入", key="匯入日記鈕"):
            try:
                新表 = pd.read_csv(上傳, dtype={"代號": str})
                新們 = []
                for _, r in 新表.iterrows():
                    代, 買賣 = str(r["代號"]).strip(), str(r["買賣"]).strip()[:1]
                    股數, 價 = int(r["股數"]), float(r["價格"])
                    費, 稅 = engine.交易費用(代, 買賣, 股數, 價, float(日記.get("折扣", 1.0)))
                    取 = lambda k, 預設: r[k] if k in 新表.columns and pd.notna(r[k]) else 預設
                    新們.append({"日期": str(pd.Timestamp(r["日期"]).date()), "代號": 代, "買賣": "賣" if 買賣 == "賣" else "買",
                               "股數": 股數, "價格": 價, "手續費": float(取("手續費", 費)), "稅": float(取("稅", 稅)),
                               "停損": float(取("停損", 0)) or None, "目標": float(取("目標", 0)) or None, "理由": str(取("理由", ""))})
                存交易日記({**日記, "交易": 交易們 + 新們})
                st.success(f"已匯入 {len(新們)} 筆")
                st.rerun()
            except Exception as e:
                st.error(f"匯入失敗：{e}")


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
