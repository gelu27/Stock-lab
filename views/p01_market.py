# 01 市場總覽：由 app.py 的 執行頁面() 在同一個命名空間執行，可直接用 app.py 的共用函式與資料。
def 排行表(表, 額外=None, 額外標題=None):
    """額外欄位：週轉率、鎖死（漲跌停的首次觸及與鎖死時間）、法人（表要有「法人值」與「法人單位」欄）。"""
    標題額外 = 額外標題 or {"週轉率": "週轉率", "鎖死": "觸及 / 鎖死"}.get(額外, "")
    鎖們 = 鎖死資訊(表) if 額外 == "鎖死" else {}
    列們 = []
    for _, r in 表.iterrows():
        色 = 漲跌色(r["change"])
        底 = ""
        if r.get("漲停"):
            底 = f"background:#9B0000;color:#FFF"
        elif r.get("跌停"):
            底 = f"background:#006B3C;color:#FFF"
        if 額外 == "週轉率":
            加 = f'<td style="color:#EDEDED">{r["週轉率"]:.2f}%</td>' if pd.notna(r["週轉率"]) else "<td>—</td>"
        elif 額外 == "鎖死":
            鎖 = 鎖們.get(r["code"])
            if 鎖:
                字 = f'{鎖["首次"]} / {鎖["鎖死"] or "未鎖住"}' + (f'<small>開{鎖["打開"]}次</small>' if 鎖["打開"] else "")
            else:
                字 = "—"
            加 = f'<td class="t">{字}</td>'
        elif 額外 == "法人":
            v = r["法人值"]
            加 = (f'<td style="color:{漲跌色(v)};font-weight:700">'
                 + (f"{v:+,.0f}" if r["法人單位"] == "張數" else f"{v:+,.2f} 億") + "</td>")
        else:
            加 = ""
        列們.append(
            f'<tr><td class="n"><a href="?s={r["code"]}{登入參數()}" target="_self"><small>{r["code"]}</small>{r["name"]}</a></td>'
            f'<td style="{底 or "color:" + 色}">{r["close"]:,.2f}</td>'
            f'<td style="color:{色}">{r["change"]:+,.2f}</td>'
            f'<td style="color:{色}">{r["幅度"]:+.2f}%</td>'
            f'<td style="color:#BDBDBD">{r["張數"]:,.0f}</td>'
            f'<td style="color:#BDBDBD">{r["成交金額億"]:,.2f}</td>{加}</tr>')
    if not 列們:
        st.caption("今天沒有符合的股票。")
        return
    st.markdown('<div class="rankwrap"><table class="rank"><tr><th>商品</th><th>成交</th><th>漲跌</th><th>幅度</th>'
                f'<th>張數</th><th>金額(億)</th>{f"<th>{標題額外}</th>" if 標題額外 else ""}</tr>'
                + "".join(列們) + "</table></div>", unsafe_allow_html=True)


@st.cache_data(ttl=3600, show_spinner="查詢漲跌停鎖死時間…", max_entries=10)
def _鎖死查詢(清單, 日期):
    """清單：((代號, 市場, 停價, 方向), ...)。用 Yahoo 1 分鐘線計算，平行查詢。"""
    from concurrent.futures import ThreadPoolExecutor

    def 查(項):
        代號, 市場, 價, 方向 = 項
        try:
            k = engine.盤中K線(代號, 市場, "1m", "5d")
            k = k[k["datetime"].dt.strftime("%Y-%m-%d") == 日期] if k is not None else None
            return 代號, engine.鎖死分析(k, 價, 方向)
        except Exception:
            return 代號, None
    with ThreadPoolExecutor(8) as 池:
        return dict(池.map(查, 清單))


def 鎖死資訊(表):
    停 = 表[表["漲停"] | 表["跌停"]]
    清單 = tuple((r["code"], r["市場"], float(r["漲停價"] if r["漲停"] else r["跌停價"]), "漲" if r["漲停"] else "跌")
               for _, r in 停.iterrows())
    return _鎖死查詢(清單, 最新日.strftime("%Y-%m-%d")) if 清單 else {}


def 登入參數():
    k = st.query_params.get("k")
    版 = st.query_params.get("layout")
    近 = st.query_params.get("r")
    return ((f"&k={k}" if k and st.session_state.get("已解鎖") else "") + (f"&layout={urllib.parse.quote(版)}" if 版 else "")
            + (f"&r={urllib.parse.quote(近)}" if 近 else ""))


@st.cache_data(ttl=20, show_spinner=False)
def 大盤即時():
    """加權（t00）、櫃買（o00）盤中即時點數，所有人共用 20 秒快取。抓不到回傳 None。"""
    try:
        表 = engine.即時報價(["t00", "o00"], {"o00": "上櫃"})
        return 表.dropna(subset=["close"]).set_index("code") if not 表.empty else None
    except Exception:
        return None


@st.fragment(run_every=30 if engine.盤中時間() else None)
def 盤中即時條():
    """首頁最上方的盤中即時橫條，只在 9:00～13:35 顯示，每 30 秒更新。"""
    if not engine.盤中時間():
        return
    表 = 大盤即時()
    if 表 is None or 表.empty:
        st.caption("⚡ 盤中即時：證交所即時行情暫時抓不到，稍後會自動重試。")
        return
    卡們 = []
    for 代號, 名稱 in (("t00", "TAIEX 加權"), ("o00", "TPEx 櫃買")):
        if 代號 not in 表.index:
            continue
        r = 表.loc[代號]
        漲幅 = r["change"] / (r["close"] - r["change"]) * 100
        格式 = ",.0f" if r["close"] >= 1000 else ",.2f"
        高低 = f" 高 {r['high']:{格式}} 低 {r['low']:{格式}}" if pd.notna(r.get("high")) and pd.notna(r.get("low")) else ""
        卡們.append(卡片(f"⚡ {名稱} · {r['time']}", f"{r['close']:,.2f}",
                       f"{r['change']:+,.2f}（{漲幅:+.2f}%）{高低}", 漲跌色(r["change"])))
    if 卡們:
        st.markdown(f'<div class="grid2">{"".join(卡們)}</div>', unsafe_allow_html=True)
        st.caption("盤中即時（證交所，延遲約 5～20 秒，每 30 秒自動更新）；下方市場卡片是最近一次收盤的資料。")


@st.fragment(run_every=30 if engine.盤中時間() else None)
def 加權圖():
    段落("TAIEX // 加權指數走勢")
    區間 = st.segmented_control("區間", ["當日", "5日", "1月", "1季", "半年", "1年", "3年", "5年"],
                              default="當日", key="加權區間", label_visibility="collapsed") or "當日"
    分時 = engine.讀取分時()
    即時點 = None
    if engine.盤中時間():
        即時點 = 大盤即時()
        if 即時點 is not None and "t00" in 即時點.index:
            r = 即時點.loc["t00"]
            st.markdown(卡片(f"TAIEX 盤中即時 · {r['time']}", f"{r['close']:,.2f}",
                           f"{r['change']:+,.2f}（{r['change'] / (r['close'] - r['change']) * 100:+.2f}%）",
                           漲跌色(r["change"])), unsafe_allow_html=True)
    if 區間 in ("當日", "5日"):
        # 先用 Yahoo 的分鐘線（盤中也會更新），抓不到再用每天收盤後存下來的分時資料
        線 = 分鐘線("t00", "", "1m" if 區間 == "當日" else "5m", "5d")
        if 線 is not None and len(線):
            線 = 線.assign(day=線["datetime"].dt.normalize())
            天們 = sorted(線["day"].unique())[-1:] if 區間 == "當日" else sorted(線["day"].unique())[-5:]
            資料 = 線[線["day"].isin(天們)]
            x, y = 資料["datetime"], 資料["close"]
        elif 分時:
            天們 = list(分時)[-1:] if 區間 == "當日" else list(分時)[-5:]
            資料 = pd.concat([分時[d] for d in 天們])
            x, y = 資料["datetime"], 資料["taiex"]
        else:
            st.info("分時資料暫時抓不到。")
            return
        基準 = 加權[加權["date"] < pd.Timestamp(天們[0])]["close"]
        昨收 = 基準.iloc[-1] if len(基準) else y.iloc[0]
        st.caption(f"{pd.Timestamp(天們[-1]):%Y/%m/%d} 走勢" + ("（盤中約每 30 秒更新）" if engine.盤中時間() else ""))
    else:
        天數 = {"1月": 31, "1季": 92, "半年": 183, "1年": 365, "3年": 365 * 3, "5年": 365 * 5}[區間]
        資料 = 加權[加權["date"] >= 加權["date"].max() - pd.Timedelta(days=天數)]
        x, y = 資料["date"], 資料["close"]
        昨收 = y.iloc[0]
    色 = 紅 if y.iloc[-1] >= 昨收 else 綠
    填色 = "rgba(255,59,92,0.08)" if 色 == 紅 else "rgba(0,214,143,0.08)"
    圖 = go.Figure(go.Scatter(x=x, y=y, line=dict(color=色, width=1.6), fill="tozeroy",
                              fillcolor=填色, name="加權指數"))
    圖.add_hline(y=昨收, line=dict(color=灰, width=1, dash="dot"))
    圖.update_yaxes(range=[min(y.min(), 昨收) * 0.995, max(y.max(), 昨收) * 1.005])
    if 區間 in ("當日", "5日"):
        # 跳過收盤後與週末的空白時段
        圖.update_xaxes(rangebreaks=[dict(bounds=[13.6, 9], pattern="hour"), dict(bounds=["sat", "mon"])])
    漲跌 = y.iloc[-1] - 昨收
    st.caption(f"{區間}漲跌：{漲跌:+,.2f}（{漲跌 / 昨收 * 100:+.2f}%）")
    st.plotly_chart(圖表外觀(圖, 300), width="stretch")


def 國際行情():
    段落("GLOBAL // 國際行情與台指期")
    國際, 期貨 = 抓國際()
    卡們 = []
    for 盤 in ("夜盤", "日盤"):
        q = 期貨.get(盤)
        if q:
            卡們.append(卡片(f"台指期{盤} · {q['時間']}", f"{q['價']:,.0f}", f"{q['漲跌']:+,.0f}（{q['幅度']:+.2f}%）",
                           漲跌色(q["漲跌"])))
    for 名, q in 國際.items():
        if 名 == "美元/台幣":
            continue
        卡們.append(卡片(f"{名} · {q['時間']:%m/%d}", f"{q['價']:,.2f}" if q["價"] < 1000 else f"{q['價']:,.0f}",
                       f"{q['漲跌']:+,.2f}（{q['幅度']:+.2f}%）", 漲跌色(q["漲跌"])))
    台積 = 今日[今日["代號"] == "2330"]
    if "台積電 ADR" in 國際 and "美元/台幣" in 國際 and len(台積):
        # 1 股 ADR = 5 股台積電
        換算 = 國際["台積電 ADR"]["價"] * 國際["美元/台幣"]["價"] / 5
        溢價 = (換算 / 台積["收盤"].iloc[0] - 1) * 100
        卡們.append(卡片("ADR 溢價", f"{溢價:+.1f}%", f"ADR 換算 {換算:,.0f} 元"))
    if 卡們:
        卡片格(卡們)
        st.caption("美股為前一晚收盤（盤中會更新），台指期夜盤 15:00~隔天 05:00，約每 5 分鐘更新。資料來源：Yahoo 財經、期交所。")
    else:
        st.info("國際行情暫時抓不到，請稍後再試。")


def 族群熱力圖():
    段落("SECTOR // 族群熱力圖")
    避風港區()
    a, b, c = st.columns(3)
    分類 = a.segmented_control("分類", ["產業", "概念股"], default="產業", key="族群分類") or "產業"
    期間 = b.segmented_control("漲跌期間", list(engine.族群期間), default="今日", key="族群期間") or "今日"
    大小 = c.segmented_control("方塊大小", ["市值", "成交值"], default="市值", key="族群大小") or "市值"
    來源 = engine.概念展開(今日) if 分類 == "概念股" else 今日
    if 來源.empty:
        st.info("還沒有概念股清單（data/concepts.csv）。")
        return
    族群, 個股 = engine.族群資料(來源, 期間, 大小)
    界 = {"今日": 5, "5 日": 10, "20 日": 20}[期間]
    熱分頁, 泡分頁 = st.tabs(["熱力圖", "輪動氣泡圖"])
    with 泡分頁:
        輪動氣泡圖(族群, 期間)
    with 熱分頁:
        族群樹圖(族群, 個股, 界, 大小)
    族群排行(族群, 期間, 來源)
    if 分類 == "概念股":
        st.caption("概念股是自己整理的題材清單（data/concepts.csv，約 25 個題材），一檔股票可以同時屬於好幾個概念；"
                   "想增刪可以直接在 GitHub 編輯這個檔案。")


def 避風港區():
    大盤5日 = None
    if 加權 is not None and len(加權) > 5:
        大盤5日 = (float(加權["close"].iloc[-1]) / float(加權["close"].iloc[-6]) - 1) * 100
    try:
        港, 提 = engine.避風港與提款機(今日, 大盤5日)
    except Exception:
        return
    if 港.empty and 提.empty:
        return
    句 = []
    if 大盤5日 is not None:
        句.append(f"近 5 日加權 {大盤5日:+.1f}%。")
    if len(港):
        句.append("<b>避風港</b>（比大盤抗跌）：" + "、".join(f"{k} {r['5日']:+.1f}%" for k, r in 港.iterrows()) + "。")
    if len(提):
        句.append("<b>提款機</b>（前面漲多、這 5 天被賣）：" + "、".join(
            f"{k}（20 日 {r['20日']:+.1f}% → 5 日 {r['5日']:+.1f}%）" for k, r in 提.iterrows()) + "。")
    st.markdown(f'<div class="verdict sub">{"".join(句)}</div>', unsafe_allow_html=True)


def 輪動氣泡圖(族群, 期間):
    t = 族群[族群["家數"] >= 3].copy()
    t["廣度"] = t["上漲"] / t["家數"] * 100
    大 = t["成交值億"].clip(lower=0.1)
    圖 = go.Figure(go.Scatter(
        x=t["漲跌幅"], y=t["廣度"], mode="markers+text", text=t.index, textposition="top center",
        textfont=dict(size=10, color="#CFCFCF", family="Noto Sans TC"),
        marker=dict(size=大, sizemode="area", sizeref=2 * 大.max() / 55 ** 2, sizemin=4,
                    color=t["漲跌幅"], colorscale=[[0, "#00A86B"], [0.5, "#555"], [1, "#E0244A"]],
                    cmid=0, line=dict(color="#000", width=1), opacity=.85),
        customdata=np.stack([t["上漲"], t["家數"], t["成交值億"], t["領漲股"]], axis=1),
        hovertemplate="<b>%{text}</b><br>漲跌 %{x:+.2f}%<br>上漲 %{customdata[0]} / %{customdata[1]} 檔（%{y:.0f}%）"
                      "<br>成交值 %{customdata[2]:,.0f} 億<br>領漲 %{customdata[3]}<extra></extra>"))
    圖.add_vline(x=0, line=dict(color=灰, width=1, dash="dot"))
    圖.add_hline(y=50, line=dict(color=灰, width=1, dash="dot"))
    x界 = max(abs(t["漲跌幅"]).max() * 1.15, 1)
    for x, y, 字, 色 in ((x界 * .97, 103, "全面走強", 紅), (-x界 * .97, 103, "多數上漲但力道弱", "#BDBDBD"),
                        (x界 * .97, -3, "少數股撐場", "#FFB020"), (-x界 * .97, -3, "全面走弱", 綠)):
        圖.add_annotation(x=x, y=y, text=字, showarrow=False, font=dict(color=色, size=11),
                          xanchor="right" if x > 0 else "left")
    圖.update_xaxes(title=f"{期間}平均漲跌（%）", range=[-x界, x界], zeroline=False)
    圖.update_yaxes(title="上漲家數比例（%）", range=[-8, 108])
    圖表外觀(圖, 520).update_layout(hovermode="closest", showlegend=False)
    st.plotly_chart(圖, width="stretch", config={"displayModeBar": False})
    st.caption("往右＝族群漲得多；往上＝族群裡上漲的股票比例高；泡泡越大＝成交值越大。"
               "右上角是「又強又全面」最值得注意；右下角是「只有一兩檔大漲撐住平均」，持續性通常較差。"
               "上方的漲跌期間可切換今日、5 日、20 日。")


def 族群樹圖(族群, 個股, 界, 大小):
    名們 = list(族群.index)
    圖 = go.Figure(go.Treemap(
        ids=名們 + (個股["產業"] + "/" + 個股["名稱"]).tolist(),
        labels=名們 + 個股["名稱"].tolist(),
        parents=[""] * len(名們) + 個股["產業"].tolist(),
        values=[0] * len(名們) + 個股["權重"].tolist(),
        branchvalues="remainder",
        customdata=族群["漲跌幅"].tolist() + 個股["幅度"].tolist(),
        marker=dict(colors=族群["漲跌幅"].tolist() + 個股["幅度"].tolist(), cmin=-界, cmid=0, cmax=界,
                    colorscale=[[0, "#00A86B"], [0.5, "#262626"], [1, "#E0244A"]],
                    line=dict(color="#000", width=1)),
        texttemplate="<b>%{label}</b><br>%{customdata:+.2f}%",
        hovertemplate="<b>%{label}</b><br>漲跌 %{customdata:+.2f}%<extra></extra>",
        textfont=dict(color="#FFF", family="Noto Sans TC"), maxdepth=2, pathbar=dict(visible=True),
        tiling=dict(pad=1),
    ))
    圖.update_layout(height=560, margin=dict(l=0, r=0, t=24, b=0), paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(圖, width="stretch", config={"displayModeBar": False})
    st.caption(f"方塊越大代表{大小}越大；紅漲綠跌，顏色越深漲跌越多（±{界}% 以上最深）。"
               "點一下族群可放大看裡面的股票，點上方路徑可返回。族群漲跌是依" + 大小 + "加權平均。")


def 族群排行(族群, 期間, 來源):
    表 = 族群.reset_index().rename(columns={"產業": "族群"})[
        ["族群", "漲跌幅", "上漲", "下跌", "成交值億", "領漲股"]]
    st.markdown("**族群排行**　點一下族群，下方會列出成分股")
    選 = 表格(表.style.map(lambda v: f"color:{漲跌色(v)}", subset=["漲跌幅"])
                     .format({"漲跌幅": "{:+.2f}%", "成交值億": "{:,.1f}"}),
                     key="族群表", on_select="rerun", selection_mode="single-row", hide_index=True,
                     width="stretch", height=300)
    列們 = 選.selection.rows
    if 列們:
        族 = 表.iloc[列們[0]]["族群"]
        欄 = engine.族群期間[期間]
        成分 = 來源[(來源["產業"] == 族) & (來源["收盤"] > 0)].sort_values(欄, ascending=False)
        成分 = 成分[["名稱", "收盤", "漲跌幅", "5日漲幅", "20日漲幅", "成交張數", "本益比", "代號"]].rename(
            columns={"收盤": "股價"})
        st.markdown(f"**{族}**　{len(成分)} 檔，依{期間}漲跌排序，點股票可看個股查詢")
        點選表(成分, 上色(成分), "族群成分", height=min(35 * (len(成分) + 1) + 3, 420))


@st.cache_resource(max_entries=1, show_spinner=False)
def 市場每日(_資料版本):
    """最近 70 個交易日每天的大盤數字，給前後期比較用。"""
    近 = 指標[指標["date"] >= 指標["date"].max() - pd.Timedelta(days=110)]
    群 = 近.groupby("date")
    表 = pd.DataFrame({"成交金額": 群["成交值億"].sum(), "上漲": 群["漲跌"].apply(lambda s: (s > 0).sum()),
                       "下跌": 群["漲跌"].apply(lambda s: (s < 0).sum())})
    if 有籌碼:
        金額 = lambda 欄: (近[欄] * 1000 * 近["收盤"]).groupby(近["date"]).sum() / 1e8
        表["外資"] = 金額("外資買超")
        表["法人"] = 金額("法人買超")
        表["融資"] = 近.groupby("date")["融資餘額"].sum()
        維持 = engine.融資維持率(近)
        if 維持 is not None:
            表["維持率"] = 維持.reindex(表.index)
    期 = engine.讀取期貨未平倉()
    if 期 is not None and "foreign_oi" in 期:
        表["外資期貨"] = 期["foreign_oi"].reindex(表.index)
        for 英, 中 in (("trust_oi", "投信期貨"), ("dealer_oi", "自營期貨")):
            if 英 in 期:
                表[中] = 期[英].reindex(表.index)
    if 加權 is not None and not 加權.empty:
        表["加權"] = 加權.set_index("date")["close"].reindex(表.index)
    匯率 = engine.讀取匯率()
    if 匯率 is not None and len(匯率):
        表["匯率"] = 匯率.set_index("date")["usdtwd"].reindex(表.index).ffill()
    return 表


def 市場卡片():
    段落("MARKET // 市場")
    上漲 = (今日["漲跌"] > 0).sum()
    下跌 = (今日["漲跌"] < 0).sum()
    卡們 = []
    if 加權 is not None and not 加權.empty:
        最後 = 加權.iloc[-1]
        漲幅 = 最後["change"] / (最後["close"] - 最後["change"]) * 100
        卡們.append(卡片(f"TAIEX 加權指數 · {最後['date']:%m/%d}", f"{最後['close']:,.0f}",
                       f"{最後['change']:+,.2f}  ({漲幅:+.2f}%)", 漲跌色(最後["change"])))
    卡們 += [
        卡片("資料日期", 最新日.strftime("%m/%d"), 最新日.strftime("%Y")),
        卡片("成交金額", f"{今日['成交值億'].sum():,.0f}", "億元"),
        卡片("上漲家數", f"{上漲}", "▲", 紅),
        卡片("下跌家數", f"{下跌}", "▼", 綠),
    ]
    匯率 = engine.讀取匯率()
    if 匯率 is not None and len(匯率) >= 2:
        今, 昨 = 匯率["usdtwd"].iloc[-1], 匯率["usdtwd"].iloc[-2]
        差 = 今 - 昨
        # 美元兌台幣數字變小 = 台幣升值（紅），變大 = 台幣貶值（綠）
        狀態, 色 = ("台幣升值 ▲", 紅) if 差 < 0 else (("台幣貶值 ▼", 綠) if 差 > 0 else ("持平", "#EDEDED"))
        卡們.append(卡片(f"美元/台幣 · {匯率['date'].iloc[-1]:%m/%d}", f"{今:.3f}", f"{差:+.3f} {狀態}", 色))
    else:
        卡們.append(卡片("美元/台幣", "—", "下次更新後提供"))
    卡片格(卡們)
    每日 = 市場每日(_版本)
    if len(每日) >= 2:
        欄位 = {"加權": ("加權指數", "{:,.0f}"), "成交金額": ("成交金額（億）", "{:,.0f}"),
              "上漲": ("上漲家數", "{:,.0f}"), "下跌": ("下跌家數", "{:,.0f}"),
              "外資": ("外資買賣超（億）", "{:,.1f}"), "法人": ("三大法人買賣超（億）", "{:,.1f}"),
              "融資": ("融資餘額（張）", "{:,.0f}"), "維持率": ("上市融資維持率（%）", "{:.1f}"),
              "外資期貨": ("外資台指期淨未平倉（口）", "{:+,.0f}"), "匯率": ("美元/台幣", "{:.3f}")}
        欄位 = {k: v for k, v in 欄位.items() if k in 每日.columns and 每日[k].notna().iloc[-1]}
        with st.expander("📊 前後期比較（昨日、5 日前、20 日前、60 日前）", expanded=True):
            前後期表(每日, 欄位, [("昨日", 1), ("5 日前", 5), ("20 日前", 20), ("60 日前", 60)],
                     lambda d: f"{d:%m/%d}", 反向={"下跌", "融資", "匯率"})
            st.caption("🔴 偏多：指數、成交、上漲家數、法人買超變多，融資減少、台幣升值；🟢 反之。"
                       "外資／法人金額用買賣超張數 × 收盤價估算。")


def 維持率等級(值):
    if 值 >= 170:
        return "偏高：融資戶有餘裕，但市場偏熱", 紅
    if 值 >= 150:
        return "正常範圍", "#EDEDED"
    if 值 >= 140:
        return "偏低：融資戶多數在虧", "#FFB020"
    if 值 >= 130:
        return "接近追繳線，留意斷頭賣壓", 綠
    return "低於 130% 追繳線，斷頭潮", 綠


def 資金面區():
    段落("MONEY // 資金面：漲跌家數、融資維持率、外資期貨")
    每日 = 市場每日(_版本).tail(60)
    卡們 = []
    if "維持率" in 每日 and 每日["維持率"].notna().any():
        維 = 每日["維持率"].dropna()
        差 = 維.iloc[-1] - 維.iloc[-2] if len(維) >= 2 else np.nan
        等級, 色 = 維持率等級(維.iloc[-1])
        卡們.append(卡片(f"上市融資維持率 · {維.index[-1]:%m/%d}", f"{維.iloc[-1]:.1f}%",
                       ("" if pd.isna(差) else f"較前一日 {差:+.1f}　") + 等級, 色))
    if "外資期貨" in 每日 and 每日["外資期貨"].notna().any():
        期 = 每日["外資期貨"].dropna()
        差 = 期.iloc[-1] - 期.iloc[-2] if len(期) >= 2 else np.nan
        卡們.append(卡片(f"外資台指期淨未平倉 · {期.index[-1]:%m/%d}", f"{期.iloc[-1]:+,.0f} 口",
                       "" if pd.isna(差) else f"較前一日 {差:+,.0f} 口", 漲跌色(期.iloc[-1])))
    當沖 = engine.讀取當沖大盤()
    if 當沖 is not None and "上市" in 當沖 and 當沖["上市"].notna().any():
        沖 = 當沖["上市"].dropna()
        卡們.append(卡片(f"上市當沖比重 · {沖.index[-1]:%m/%d}", f"{沖.iloc[-1]:.1f}%",
                       f"近 20 日平均 {沖.tail(20).mean():.1f}%" + (f"；上櫃 {當沖['上櫃'].dropna().iloc[-1]:.1f}%"
                                                                 if "上櫃" in 當沖 and 當沖["上櫃"].notna().any() else ""),
                       "#FFC24B" if 沖.iloc[-1] >= 30 else "#EDEDED"))
    淨 = 每日["上漲"] - 每日["下跌"]
    卡們.append(卡片("上漲減下跌（今日）", f"{淨.iloc[-1]:+,.0f} 家", f"近 20 日平均 {淨.tail(20).mean():+,.0f}", 漲跌色(淨.iloc[-1])))
    卡片格(卡們)
    with st.expander("ℹ️ 融資維持率是什麼？數字高低代表什麼？"):
        st.markdown(
            "**意思**：投資人借錢（融資）買股票，券商只借大約六成，股票押在券商那裡。"
            "融資維持率就是「這些股票現在的市值」除以「借的錢」，用來看融資戶整體還有多少緩衝。\n\n"
            "**怎麼算**：上市所有股票的（融資餘額張數 × 1,000 股 × 收盤價）加總 ÷ 證交所公布的融資金額。"
            "剛融資買進時大約是 166%（自備四成、借六成：100 ÷ 60）。\n\n"
            "**數字高低**：\n"
            "- **170% 以上**：融資戶整體有賺、緩衝充足；但也代表散戶借錢買得多，市場偏熱\n"
            "- **150～170%**：正常範圍\n"
            "- **140～150%**：偏低，融資戶多數在虧，要留意\n"
            "- **130～140%**：接近追繳線，股價再跌容易出現斷頭賣壓\n"
            "- **130% 以下**：個股維持率低於 130% 券商會追繳，補不足就強制賣出（斷頭）；大盤跌到這裡常是恐慌殺盤、也常接近底部\n\n"
            "這裡是自己估算的，跟券商或財經網站公布的數字可能差 1～2%。")
    日 = 每日.index.strftime("%m/%d")
    圖 = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                       subplot_titles=("上漲家數 − 下跌家數", "上市融資維持率（%）", "外資台指期淨未平倉（口）"))
    圖.add_trace(go.Bar(x=日, y=淨, marker_color=[紅 if v > 0 else 綠 for v in 淨], name="漲跌家數差"), 1, 1)
    if "維持率" in 每日:
        圖.add_trace(go.Scatter(x=日, y=每日["維持率"], mode="lines", line=dict(color=青, width=2), name="維持率",
                                connectgaps=True), 2, 1)
    if "外資期貨" in 每日:
        圖.add_trace(go.Bar(x=日, y=每日["外資期貨"], marker_color="#FFB020", name="外資淨未平倉"), 3, 1)
    圖.update_layout(showlegend=False, bargap=0.2)
    圖.update_xaxes(type="category", nticks=8)
    圖.update_annotations(font=dict(size=11, color=灰), x=0, xanchor="left")
    st.plotly_chart(圖表外觀(圖, 520), width="stretch")
    st.caption("融資維持率 = 上市股票融資市值 ÷ 融資金額，意思見上方「ℹ️ 融資維持率是什麼」。"
               "外資淨未平倉 = 外資台指期（大台）多單減空單，負的代表偏空避險。")
    槓桿趨勢()


def 槓桿趨勢():
    """融資餘額、每日增減與三大法人台指期淨部位走勢：看「散戶加槓桿、法人在放空」有沒有同時發生。"""
    st.markdown("**📈 融資與期貨法人趨勢**")
    天數 = st.segmented_control("天數", [10, 20, 30, 45, 60], default=30, key="槓桿天數",
                              format_func=lambda n: f"近 {n} 天", label_visibility="collapsed") or 30
    每日 = 市場每日(_版本).tail(天數)
    if "融資" not in 每日:
        st.caption("沒有融資資料。")
        return
    日 = 每日.index.strftime("%m/%d")
    增減 = 每日["融資"].diff()
    圖 = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                       subplot_titles=("融資餘額（上市櫃合計，張）", "融資每日增減（張）", "三大法人台指期淨部位（口，正＝偏多）"))
    圖.add_trace(go.Scatter(x=日, y=每日["融資"], mode="lines", line=dict(color="#FFB020", width=2), name="融資餘額"), 1, 1)
    圖.add_trace(go.Bar(x=日, y=增減, marker_color=[紅 if v > 0 else 綠 for v in 增減.fillna(0)], name="融資增減"), 2, 1)
    合計 = None
    for 欄, 名, 色 in (("外資期貨", "外資", "#4DA3FF"), ("投信期貨", "投信", "#FF00E5"), ("自營期貨", "自營商", "#9B9B9B")):
        if 欄 in 每日:
            圖.add_trace(go.Scatter(x=日, y=每日[欄], mode="lines", line=dict(color=色, width=1.6), name=名,
                                    connectgaps=True), 3, 1)
            合計 = 每日[欄] if 合計 is None else 合計 + 每日[欄]
    if 合計 is not None:
        圖.add_trace(go.Scatter(x=日, y=合計, mode="lines", line=dict(color="#FFF", width=2, dash="dot"), name="合計",
                                connectgaps=True), 3, 1)
    圖.update_xaxes(type="category", nticks=8)
    圖.update_annotations(font=dict(size=11, color=灰), x=0, xanchor="left")
    圖表外觀(圖, 600).update_layout(legend=dict(orientation="h", y=-0.06, x=0), margin=dict(t=24, b=40))
    st.plotly_chart(圖, width="stretch")
    if len(每日) >= 2 and "外資期貨" in 每日:
        融變 = 每日["融資"].iloc[-1] - 每日["融資"].iloc[0]
        外變 = 每日["外資期貨"].dropna()
        外變 = 外變.iloc[-1] - 外變.iloc[0] if len(外變) >= 2 else np.nan
        if 融變 > 0 and pd.notna(外變) and 外變 < 0:
            st.warning(f"⚠️ 近 {天數} 天融資增加 {融變:+,.0f} 張、外資期貨淨部位減少 {外變:+,.0f} 口："
                       "散戶加槓桿、外資偏空，兩者同時出現時大盤常較脆弱。")
        elif 融變 < 0 and pd.notna(外變) and 外變 > 0:
            st.success(f"近 {天數} 天融資減少 {融變:+,.0f} 張、外資期貨淨部位增加 {外變:+,.0f} 口：籌碼變乾淨、外資轉多。")
    st.caption("投信台指期多半是替 ETF 避險或加碼的多單，主要看外資的方向；合計＝三者相加。資料來源：證交所、櫃買中心、期交所。")


@st.cache_data(ttl=3600, show_spinner=False)
def 指數成交值(代號, _資料版本):
    """加權＝上市、櫃買＝上櫃每天的成交金額（億），算分價量和量價關係用。"""
    t = 指標[指標["市場"] == ("上市" if 代號 == "TAIEX" else "上櫃")]
    return t.groupby("date")["成交值億"].sum()


@st.cache_data(ttl=3600, show_spinner=False)
def 價位分析(代號, _資料版本):
    K = 指數K線(代號, _資料版本)
    if K is None or len(K) < 60:
        return None
    量 = 指數成交值(代號, _資料版本)
    sr = engine.支撐壓力(K, 量=量)
    區們 = engine.共振區(sr["價位"])
    return K, sr, 區們, engine.位置解讀(sr, 區們), engine.黑K一半(K), engine.量價標籤(K, 量)


@st.cache_data(ttl=3600, show_spinner="回測 5 年支撐壓力中…")
def 價位回測(代號, _資料版本):
    K = 指數K線(代號, _資料版本)
    if K is None or len(K) <= 300:
        return pd.DataFrame()
    return engine.回測摘要(engine.支撐壓力回測(K, 指數成交值(代號, _資料版本)))


@st.cache_data(ttl=3600, show_spinner=False)
def 指數跌破站回(代號, _資料版本):
    K = 指數K線(代號, _資料版本)
    if K is None:
        return []
    量 = 指數成交值(代號, _資料版本)
    return engine.跌破站回(K, 量) + engine.技術訊號(K, 量)


@st.cache_data(ttl=3600, show_spinner=False)
def 指數技術觀察(代號, _資料版本):
    K = 指數K線(代號, _資料版本)
    return engine.技術觀察(K, 指數成交值(代號, _資料版本)) if K is not None else []


@st.cache_data(ttl=3600, show_spinner=False)
def 守週線強勢(_資料版本):
    return engine.守週線強勢股(指標)


def 關鍵價位區():
    段落("LEVELS // 關鍵價位：支撐、壓力與觀察條件")
    選 = st.segmented_control("指數", ["加權指數", "櫃買指數"], default="加權指數", key="價位指數",
                            label_visibility="collapsed") or "加權指數"
    代號 = "TAIEX" if 選 == "加權指數" else "TPEX"
    結果 = 價位分析(代號, _版本)
    if 結果 is None:
        st.info(f"{選}的開高低資料下次更新後就會出現。")
        return
    K, sr, 區們, 解, 黑, 量價 = 結果
    價位卡片(sr, 解, float(K["close"].iloc[-2]))
    跌破站回條(指數跌破站回(代號, _版本))
    st.markdown(f'<div class="verdict">{解["文字"]}</div>', unsafe_allow_html=True)
    量價條(量價)
    try:
        項們, 總結 = engine.三條件燈號(指數K線("TAIEX", _版本), 指數K線("TPEX", _版本), engine.讀取美股())
    except Exception:
        項們, 總結 = [], ""
    if 項們:
        st.markdown(f"**本週觀察三條件**：{總結}")
        st.markdown(燈號卡(項們), unsafe_allow_html=True)
    if 黑:
        st.markdown(黑K卡(黑), unsafe_allow_html=True)
    技術 = 指數技術觀察(代號, _版本)
    if 技術:
        st.markdown("**分析師常用條件**：週線、KD、扣抵值、爆量 K 棒")
        st.markdown(燈號卡(技術), unsafe_allow_html=True)
    if 代號 == "TAIEX":
        殺估值區()
    天數 = st.segmented_control("圖表區間", [60, 120, 250], default=120, format_func=lambda d: {60: "3 個月", 120: "半年", 250: "1 年"}[d],
                              key="價位區間", label_visibility="collapsed") or 120
    圖分頁 = st.tabs(["支撐壓力圖", "櫃買 ÷ 加權 強弱", "缺口清單", "準不準？（回測）", "守 5 週線的強勢股"])
    with 圖分頁[0]:
        st.plotly_chart(支撐壓力圖(K, sr, 區們, 天數, 摘要=價位回測(代號, _版本)), width="stretch",
                        config={"displayModeBar": False})
    with 圖分頁[1]:
        強弱圖(天數)
    with 圖分頁[2]:
        缺口表(K, f"缺口{代號}")
    with 圖分頁[3]:
        回測區(代號)
    with 圖分頁[4]:
        守週線表()
    with st.expander("📋 完整價位表"):
        價位明細(sr, 區們, "價位明細", 價位回測(代號, _版本))
    st.caption("自動計算，不是人工畫線：月線／季線／半年線＝20／60／120 日均線；黃線＝最近一段漲勢（或跌勢）的費波那契回檔；"
               "橘色＝還沒回補的跳空缺口；白虛線＝波段高低點；灰虛線＝整數關卡；紫線與左側橫條＝分價量（近 120 日每個價位累積的成交金額，"
               "最長那條＝成交最密集，深紫＝7 成成交集中的區間）；青色色帶＝2 種以上方法重疊的「共振區」，通常比單一條線重要。"
               "量價：漲跌看收盤，量看成交金額比前 5 日平均（多 15% 算量增、少 15% 算量縮）。"
               "三條件燈號參考週報分析者的觀察清單；黑 K 一半規則＝大跌那天之後的反彈，收盤要站上那根黑 K 實體的一半才算有力。"
               "分析師常用條件整理自幾位 YouTube 分析師：20 週線守不守（宏爺）、KD 沒黃金交叉不算反轉（老王）、"
               "扣抵值看 5 日線何時翻揚（通勤族）、跌破爆量那天的低點凶多吉少（老王）。"
               "僅供研究參考，不是買賣建議。")


@st.cache_data(ttl=3600, show_spinner=False)
def 殺估值資料(_資料版本):
    return engine.殺估值觀察組(指標, engine.讀取美股())


def 殺估值區():
    t, 燈, 話 = 殺估值資料(_版本)
    if t.empty:
        return
    st.markdown(燈號卡([("殺估值觀察組", 燈, 話)]), unsafe_allow_html=True)
    with st.expander("看每一檔"):
        表格(t, hide_index=True, width="stretch",
                     column_config={"距60日高%": st.column_config.NumberColumn(format="%+.1f"),
                                    "本益比降幅%": st.column_config.NumberColumn(format="%+.1f")})
        st.caption("通勤族的觀察法：這波下跌主要是「殺估值」（市場不願意再給高本益比），不是公司變差。"
                   "高本益比的領頭股不再創新低（近 5 日低點沒有低於前 20 日低點），才代表修正可能告一段落。"
                   "Lumentum 是美股光通訊股，只有收盤價。")


def 守週線表():
    t = 守週線強勢(_版本)
    if t.empty:
        st.caption("目前沒有守在 5 週線上的股票。")
        return
    表格(t, hide_index=False, width="stretch", height=min(35 * (len(t) + 1) + 3, 520), key="守週線",
                 column_config={"收盤": st.column_config.NumberColumn(format="%.2f"),
                                "5週線": st.column_config.NumberColumn(format="%.2f"),
                                "20日漲幅": st.column_config.NumberColumn("20 日漲幅%", format="%.1f"),
                                "距5週線%": st.column_config.NumberColumn("距 5 週線%", format="%+.1f")})
    st.caption("通勤族的選股方法：大盤被壓在 5 週線下時，先找還守在自己 5 週線上的股票，等大盤止跌時這些通常漲得比較快。"
               "條件：4 碼股票、5 日均量 1,000 張以上，依 20 日漲幅排序，前 30 檔。漲很多的小型股波動也大，要搭配停損。")


def 回測區(代號):
    t = 價位回測(代號, _版本)
    if t.empty:
        st.caption("資料不足，無法回測。")
        return
    回測顯示(t)


def 強弱圖(天數=120):
    r, 均, 文字 = engine.櫃買加權比(指數K線("TAIEX", _版本), 指數K線("TPEX", _版本), max(天數, 60))
    if r is None:
        st.caption("櫃買指數資料不足。")
        return
    st.markdown(f'<div class="verdict sub">{文字}</div>', unsafe_allow_html=True)
    圖 = go.Figure()
    圖.add_trace(go.Scatter(x=r.index, y=r, name="櫃買 ÷ 加權", line=dict(color="#8F7CFF", width=2)))
    圖.add_trace(go.Scatter(x=均.index, y=均, name="20 日均線", line=dict(color="#555", width=1, dash="dot")))
    圖.add_hline(y=100, line=dict(color=灰, width=1, dash="dot"))
    圖表外觀(圖, 300).update_layout(legend=dict(orientation="h", y=1.08, x=0))
    st.plotly_chart(圖, width="stretch", config={"displayModeBar": False})
    st.caption("起點＝100。線往上＝櫃買（中小型股）比加權（大型權值股）強，往下＝資金集中在權值股。")


def 排行區():
    段落("RANKING // 排行（前 50 檔，含上市櫃）")
    排行 = engine.排行資料(今日)
    漲停數, 跌停數 = int(排行["漲停"].sum()), int(排行["跌停"].sum())
    榜 = st.tabs(["漲幅", "跌幅", "成交量", "成交值", "週轉率", f"漲停 {漲停數}", f"跌停 {跌停數}", "法人買賣超"])
    with 榜[0]:
        排行表(排行.nlargest(50, "幅度"), "鎖死")
    with 榜[1]:
        排行表(排行.nsmallest(50, "幅度"), "鎖死")
    with 榜[2]:
        排行表(排行.nlargest(50, "張數"))
    with 榜[3]:
        排行表(排行.nlargest(50, "value"))
    with 榜[4]:
        排行表(排行.nlargest(50, "週轉率"), "週轉率")
        st.caption("週轉率 = 今日成交股數 ÷ 發行股數。")
    with 榜[5]:
        排行表(排行[排行["漲停"]].sort_values("週轉率", ascending=False), "鎖死")
    with 榜[6]:
        排行表(排行[排行["跌停"]].sort_values("週轉率", ascending=False), "鎖死")
    with 榜[7]:
        法人排行(排行)
    st.caption("觸及 / 鎖死：第一次碰到漲跌停的時間 / 最後一次鎖住到收盤的時間（「未鎖住」表示收盤前又打開），"
               "依 Yahoo 1 分鐘線計算，可能有幾分鐘誤差。")


def 法人排行(排行):
    if "外資買超" not in 排行.columns or 排行["外資買超"].isna().all():
        st.caption("今天的法人買賣超資料還沒出來（通常 16:30 後）。")
        return
    a, b, c = st.columns([2, 1, 1])
    誰 = a.segmented_control("法人", ["外資", "投信", "自營商", "三大法人"], default="外資", key="法人排行誰",
                           label_visibility="collapsed") or "外資"
    向 = b.segmented_control("方向", ["買超", "賣超"], default="買超", key="法人排行向", label_visibility="collapsed") or "買超"
    單位 = c.segmented_control("單位", ["張數", "金額"], default="張數", key="法人排行單位", label_visibility="collapsed") or "張數"
    欄 = {"外資": "外資買超", "投信": "投信買超", "自營商": "自營買超", "三大法人": "法人買超"}[誰]
    t = 排行.dropna(subset=[欄]).copy()
    t["法人值"] = t[欄] if 單位 == "張數" else t[欄] * 1000 * t["close"] / 1e8
    t["法人單位"] = 單位
    t = t[t["法人值"] > 0].nlargest(50, "法人值") if 向 == "買超" else t[t["法人值"] < 0].nsmallest(50, "法人值")
    排行表(t, "法人", f"{誰}{向}{'（張）' if 單位 == '張數' else ''}")
    st.caption("用張數排，低價股容易排很前面；用金額排（張數 × 1000 × 收盤價）比較看得出法人真正把錢押在哪裡。"
               "新聞常用張數排，所以兩種排法的前幾名常常不一樣。")


def 權值區():
    段落("WEIGHT // 權值股：今天誰撐盤、誰拖盤")
    期間 = st.segmented_control("貢獻期間", list(engine.族群期間), default="今日", key="權值期間",
                              label_visibility="collapsed") or "今日"
    表, 摘要 = engine.權值貢獻(今日, 加權, 期間)
    if 表["貢獻點數"].isna().all():
        st.caption("加權指數資料不足，暫時無法計算。")
        return
    前十 = 表.nlargest(10, "權重")
    卡片格([卡片(f"加權指數{期間}漲跌", f"{摘要['實際漲跌']:+,.0f} 點", f"估算合計 {摘要['估算合計']:+,.0f} 點",
                漲跌色(摘要["實際漲跌"])),
           卡片("前 10 大權值股貢獻", f"{前十['貢獻點數'].sum():+,.0f} 點", f"合計權重 {前十['權重'].sum():.1f}%",
                漲跌色(前十["貢獻點數"].sum())),
           卡片("台積電貢獻", f"{表.loc[表['代號'] == '2330', '貢獻點數'].sum():+,.0f} 點",
                f"權重 {表.loc[表['代號'] == '2330', '權重'].sum():.1f}%", 漲跌色(表.loc[表['代號'] == '2330', '貢獻點數'].sum()))])
    撐 = 表[表["貢獻點數"] > 0].nlargest(10, "貢獻點數")
    拖 = 表[表["貢獻點數"] < 0].nsmallest(10, "貢獻點數")
    # 像一棵樹：中間一條線，撐盤紅條往左長、拖盤綠條往右長，「代號 名稱」在最外側；各 10 檔，由上往下影響越來越小
    # 兩邊用同一個刻度才比得出大小
    圖 = make_subplots(rows=1, cols=2, horizontal_spacing=0,
                      subplot_titles=(f"撐盤 前 {len(撐)} 檔", f"拖盤 前 {len(拖)} 檔"))
    for 欄, 組, 色 in ((1, 撐, 紅), (2, 拖, 綠)):
        組 = 組.assign(值=組["貢獻點數"].abs())
        圖.add_trace(go.Bar(x=組["值"], y=組["代號"] + " " + 組["名稱"], orientation="h", marker_color=色,
                            text=組["貢獻點數"].map("{:+.1f}".format), textposition="auto", cliponaxis=False,
                            insidetextanchor="end", textfont=dict(size=11), insidetextfont=dict(color="#000"),
                            customdata=np.stack([組["貢獻點數"], 組["幅度"], 組["權重"]], axis=1),
                            hovertemplate="%{y}<br>貢獻 %{customdata[0]:+.1f} 點<br>漲跌 %{customdata[1]:+.2f}%"
                                          "<br>權重 %{customdata[2]:.2f}%<extra></extra>"), row=1, col=欄)
    最大 = max(撐["貢獻點數"].abs().max() if len(撐) else 0, 拖["貢獻點數"].abs().max() if len(拖) else 0) or 1
    圖.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
    圖.update_xaxes(range=[最大 * 1.3, 0], row=1, col=1)  # 左邊反過來，條從中間往左長
    圖.update_xaxes(range=[0, 最大 * 1.3], row=1, col=2)
    圖.update_yaxes(type="category", autorange="reversed", showgrid=False, tickfont=dict(size=11), ticks="")
    圖.update_yaxes(side="right", row=1, col=2)
    圖.add_vline(x=0, line=dict(color="#555", width=1), row=1, col=1)
    圖.update_annotations(font=dict(size=12, color="#BDBDBD"))
    圖表外觀(圖, 30 * max(len(撐), len(拖), 1) + 60).update_layout(hovermode="closest", showlegend=False,
                                                            margin=dict(l=4, r=4, t=28, b=6))
    st.plotly_chart(圖, width="stretch", config={"displayModeBar": False})
    族 = 表[表["產業"].fillna("") != ""].groupby("產業")["貢獻點數"].sum().sort_values()
    族 = pd.concat([族.head(5), 族.tail(5)])
    族 = 族[~族.index.duplicated()]
    _, 撐盤 = engine.撐盤分組(表)
    st.markdown(f'<div class="verdict sub"><b>誰在撐盤</b>　{撐盤}</div>', unsafe_allow_html=True)
    st.markdown("**依族群合計**　" + "　".join(
        f'<font color="{漲跌色(v)}">{k} {v:+.0f}</font>' for k, v in 族.sort_values(ascending=False).items()),
        unsafe_allow_html=True)
    with st.expander("前 50 大權值股明細"):
        明 = 表.nlargest(50, "權重").rename(columns={"幅度": "漲跌幅", "權重": "權重%", "收盤": "股價"})
        明["股票"] = 明["代號"] + " " + 明["名稱"]
        明 = 明[["股票", "股價", "漲跌幅", "權重%", "貢獻點數", "市值億", "代號"]]
        點選表(明, 上色(明).format({"股價": "{:,.2f}", "漲跌幅": "{:+.2f}", "權重%": "{:.2f}", "貢獻點數": "{:+.2f}",
                                 "市值億": "{:,.0f}"}).map(lambda v: f"color:{漲跌色(v)}", subset=["貢獻點數"]),
               "權值明細", height=420, column_config={"代號": None})
    st.caption("權重＝這檔市值 ÷ 上市總市值；貢獻點數＝權重 × 漲跌幅 × 期初指數。"
               "交易所的官方算法還有除權息、增資等調整，所以估算合計跟實際漲跌會差一點。漲跌期間 5 日、20 日用還原股價計算。")


def 焦點區():
    段落("FOCUS // 今天值得研究、需要防守的股票")
    try:
        評分 = 評分資料(_版本)[0]
    except Exception:
        評分 = None
    try:
        ETF變化 = ETF資料(ETF版本())[2]
    except Exception:
        ETF變化 = None
    我的 = []
    if 可編輯():
        我的 = list(庫存代號() or []) + [c for v in 自選股清單().values() for c in v]
    機會, 風險 = engine.焦點清單(今日, 評分, ETF變化, 警示表(_版本), 我的)
    左, 右 = st.columns(2)
    for 欄, 名, 表, 鍵 in ((左, "🔍 值得研究", 機會, "焦點機會"), (右, "🛡️ 需要防守", 風險, "焦點風險")):
        with 欄:
            st.markdown(f"**{名}**（{len(表)} 檔）")
            if 表.empty:
                st.caption("今天沒有符合的股票。")
            else:
                點選表(表, 上色(表).format({"收盤": "{:,.2f}", "漲跌幅": "{:+.2f}", "總分": "{:.0f}"}, na_rep="—"), 鍵,
                       height=min(35 * (len(表) + 1) + 3, 460), column_config={"代號": None,
                                                                        "理由": st.column_config.TextColumn(width="large")})
    st.caption("RESEARCH ONLY 僅供研究：依規則挑出來的名單，不是買賣建議。"
               "值得研究＝評分大升、營收創新高、帶量突破盤整、外資投信連買、3 檔以上主動式 ETF 同時加碼；"
               "需要防守＝注意／處置股、評分大跌、跌破十日線且法人賣、融資暴增但股價跌、法人 5 日大賣。"
               + ("⭐＝你的庫存或自選股，會排在最前面。" if 我的 else "解鎖後你的庫存、自選股會用 ⭐ 標示並排在最前面。")
               + "只看成交 500 張以上的股票。點一下可到個股查詢。")


@st.cache_resource(max_entries=1, show_spinner="計算市場情緒中…")
def 情緒資料(_資料版本):
    return engine.情緒指數(指標, 加權)


@st.cache_data(ttl=3600, show_spinner=False)
def 經濟日程資料(_資料版本, 天數=14, 往前=0):
    市值 = (今日["收盤"] * 今日["發行股數"]).where(~今日["代號"].str.startswith("0"))
    大型 = tuple(今日.loc[市值.nlargest(50).index, "代號"])
    表 = engine.經濟日程(天數=天數, 往前=往前, 大型股=大型)
    表["事件"] = [e.replace(" 除權息", f" {市場名稱.get(e.split()[0], '')} 除權息") if e.endswith(" 除權息") else e
                for e in 表["事件"]]
    return 表


def 狀態區():
    段落("REGIME // 市場狀態判讀")
    try:
        情緒 = 情緒資料(_版本)
    except Exception:
        情緒 = None
    判 = engine.市場狀態(加權, 今日, 市場每日(_版本), 情緒, 經濟日程資料(_版本, 7))
    色 = 紅 if "多" in 判["狀態"] else (綠 if "空" in 判["狀態"] else "#EDEDED")
    卡片格([卡片("目前判讀", 判["狀態"], f"支持 {len(判['支持'])} 項・反向 {len(判['反向'])} 項", 色),
           卡片("大盤評分", f"{判['大盤']['分數']}", 判["大盤"]["看法"], 分數色(判["大盤"]["分數"])),
           卡片("資料日期", f"{最新日:%m/%d}", "收盤後規則判讀")])
    a, b, c = st.columns(3)
    for 欄, 名, 項, 符 in ((a, "🔴 支持因素", 判["支持"], "▲"), (b, "🟢 反向因素", 判["反向"], "▼"),
                          (c, "⏳ 待觀察（未來 7 天大事）", 判["待觀察"], "・")):
        欄.markdown(f"**{名}**" + ("".join(f"\n- {x}" for x in 項) if 項 else "\n- 目前沒有"))
    st.markdown("**👀 下一步觀察**：" + "；".join(判["下一步"]))
    st.caption("用規則整理均線、漲跌家數、外資現貨與期貨、融資、情緒指數與重要行事曆，支持比反向多 3 項以上＝偏多、少 3 項以上＝偏空。"
               "僅供研究參考，不是買賣建議。")


def 恐慌溫度計區():
    try:
        項們, 溫, 級, 話 = engine.恐慌溫度計(engine.讀取美股(), engine.讀取匯率(), engine.讀取小台散戶())
    except Exception:
        return
    if not 項們:
        return
    色 = 綠 if 溫 >= 55 else (紅 if 溫 < 30 else "#EDEDED")
    卡片格([卡片("恐慌溫度計", f"{溫:.0f}", f"{級}（0 樂觀 → 100 恐慌）", 色)]
          + [卡片(名, 值, 說, 綠 if 分 >= 70 else ("#EDEDED" if 分 >= 30 else 紅)) for 名, 值, 說, 分 in 項們])
    st.markdown(f'<div class="thermo"><i style="left:calc({溫:.0f}% - 2px)"></i></div>'
                '<div class="thermo-l"><span>樂觀</span><span>中性</span><span>恐慌</span></div>'
                f'<div class="verdict sub">{話}</div>', unsafe_allow_html=True)
    st.caption("恐慌溫度計＝VIX 在過去一年排第幾、美元兌台幣在一年區間的位置（台幣越貶分數越高）、"
               "韭菜指數（小台散戶多空比：散戶淨多單 ÷ 小台未平倉量，散戶越看空分數越高），各項平均。"
               "參考反向型分析者的看法：大家最怕的時候常接近低點，但仍要等止跌訊號，不是買賣建議。")


def 情緒區():
    段落("SENTIMENT // 市場情緒：法人 × 散戶 × 國際 × 資金")
    恐慌溫度計區()
    情 = 情緒資料(_版本)
    if 情.empty or 情[["散戶", "法人", "資金溫度", "全球"]].dropna(how="all").empty:
        st.info("情緒指數資料累積中。")
        return
    最後 = 情.dropna(how="all", subset=["散戶", "法人", "資金溫度", "全球"]).iloc[-1]
    前 = 情.shift(5).loc[最後.name] if len(情) > 5 else None
    卡們 = []
    for 名 in ("法人", "散戶", "資金溫度", "全球"):
        v = 最後[名]
        差 = "" if 前 is None or pd.isna(前[名]) or pd.isna(v) else f"　5 日前 {前[名]:.0f}"
        卡們.append(卡片(f"{名}情緒" if 名 != "資金溫度" else 名, "—" if pd.isna(v) else f"{v:.0f}",
                       engine.情緒說明(v) + 差, 紅 if v >= 60 else (綠 if v <= 40 else "#EDEDED") if pd.notna(v) else 灰))
    象 = engine.情緒象限(最後["散戶"], 最後["法人"])
    卡們.append(卡片("法人 × 散戶", 象, f"{最後.name:%m/%d}", 青))
    卡片格(卡們)
    分頁 = st.tabs(["趨勢", "四象限"])
    with 分頁[0]:
        選 = st.pills("情緒指標", ["法人", "散戶", "資金溫度", "全球"], selection_mode="multi", default=["法人", "散戶"],
                     key="情緒選", label_visibility="collapsed") or ["法人"]
        近 = 情.tail(180)
        圖 = make_subplots(specs=[[{"secondary_y": True}]])
        if "加權" in 近:
            圖.add_trace(go.Scatter(x=近.index, y=近["加權"], name="加權指數", line=dict(color="#3A3A3A", width=1.4),
                                    fill="tozeroy", fillcolor="rgba(120,120,120,0.06)"), secondary_y=True)
        色們 = {"法人": "#4DA3FF", "散戶": "#FFB020", "資金溫度": "#FF00E5", "全球": 青}
        for 名 in 選:
            圖.add_trace(go.Scatter(x=近.index, y=近[名], name=名, line=dict(color=色們[名], width=2), connectgaps=False))
        圖.update_yaxes(range=[0, 100], secondary_y=False)
        if "加權" in 近:
            圖.update_yaxes(range=[近["加權"].min() * 0.97, 近["加權"].max() * 1.01], secondary_y=True, showgrid=False)
        圖.add_hrect(y0=80, y1=100, fillcolor=紅, opacity=0.06, line_width=0)
        圖.add_hrect(y0=0, y1=20, fillcolor=綠, opacity=0.06, line_width=0)
        st.plotly_chart(圖表外觀(圖, 360), width="stretch")
    with 分頁[1]:
        軌 = 情[["散戶", "法人"]].dropna().tail(20)
        圖 = go.Figure()
        for x0, x1, y0, y1, 字, 色 in ((0, 50, 50, 100, "法人吸籌", 紅), (50, 100, 50, 100, "全市場過熱", "#FFB020"),
                                       (0, 50, 0, 50, "系統恐慌", 綠), (50, 100, 0, 50, "法人出貨", "#9B9B9B")):
            圖.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, fillcolor=色, opacity=0.06, line_width=0)
            圖.add_annotation(x=(x0 + x1) / 2, y=y1 - 5, text=字, showarrow=False, font=dict(color=色, size=12))
        if len(軌):
            圖.add_trace(go.Scatter(x=軌["散戶"], y=軌["法人"], mode="lines+markers", line=dict(color="#555", width=1),
                                    marker=dict(size=np.linspace(4, 10, len(軌)), color=np.linspace(0, 1, len(軌)),
                                                colorscale=[[0, "#333"], [1, 青]]),
                                    text=[f"{d:%m/%d}" for d in 軌.index],
                                    hovertemplate="%{text}<br>散戶 %{x:.0f}・法人 %{y:.0f}<extra></extra>"))
            圖.add_trace(go.Scatter(x=[軌["散戶"].iloc[-1]], y=[軌["法人"].iloc[-1]], mode="markers+text",
                                    marker=dict(size=16, color=青, line=dict(color="#FFF", width=2)),
                                    text=["今天"], textposition="bottom center", hoverinfo="skip"))
        圖.update_xaxes(title="散戶情緒（左恐慌 → 右貪婪）", range=[0, 100])
        圖.update_yaxes(title="法人情緒（下偏空 → 上偏多）", range=[0, 100])
        圖表外觀(圖, 460).update_layout(showlegend=False, hovermode="closest")
        st.plotly_chart(圖, width="stretch", config={"displayModeBar": False})
        st.caption("點越大越新，線條是近 20 個交易日的移動軌跡。左上「法人吸籌」常是較好的研究時機，右上「全市場過熱」要小心追高。")
    with st.expander("ℹ️ 情緒分數怎麼算？"):
        st.markdown(
            "每個項目先看「今天的數字在過去一年排第幾」換成 0～100 分，再把同一類平均：\n"
            "- **法人**：三大法人近 5 日買賣超金額、外資台指期淨部位\n"
            "- **散戶**：融資 20 日增減、融資維持率（越高＝散戶越積極）\n"
            "- **資金溫度**：成交金額比 60 日均量、近 5 日上漲家數比例\n"
            "- **全球**：VIX 恐慌指數（反向）、費城半導體 20 日漲跌（看前一晚美股）\n\n"
            "資料不夠的項目直接不算，不會補 0。80 以上＝極度樂觀、20 以下＝極度悲觀；散戶情緒常是反向指標。")


def 行事曆區():
    段落("CALENDAR // 國內外重要行事曆")
    a, b = st.columns([1, 2])
    範圍 = a.segmented_control("範圍", ["本週", "下週", "未來 30 天"], default="本週", key="行事曆範圍",
                             label_visibility="collapsed") or "本週"
    類別們 = ["經濟數據", "央行會議", "美股財報", "期貨結算", "法說會", "除權息", "月營收", "財報"]
    選 = b.pills("類別", 類別們, selection_mode="multi", default=類別們, key="行事曆類別", label_visibility="collapsed")
    今天 = pd.Timestamp(dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date())
    週一 = 今天 - pd.Timedelta(days=今天.weekday())
    表 = 經濟日程資料(_版本, 35, 7)
    if 範圍 == "本週":
        表 = 表[(表["日期"] >= 週一) & (表["日期"] < 週一 + pd.Timedelta(days=7))]
    elif 範圍 == "下週":
        表 = 表[(表["日期"] >= 週一 + pd.Timedelta(days=7)) & (表["日期"] < 週一 + pd.Timedelta(days=14))]
    else:
        表 = 表[(表["日期"] >= 今天) & (表["日期"] <= 今天 + pd.Timedelta(days=30))]
    表 = 表[表["類別"].isin(選 or 類別們)]
    if 表.empty:
        st.caption("這段期間沒有符合的事件（國際經濟數據每天收盤後更新本週與下週）。")
        return
    顯示 = 表.assign(日期=表["日期"].map(lambda d: f"{d:%m/%d}（{'一二三四五六日'[d.weekday()]}）"),
                   重要性=表["重要性"].map({"高": "🔴 高", "中": "🟡 中"}))[["日期", "時間", "類別", "事件", "重要性", "說明"]]
    表格(顯示.style.apply(lambda r: ["background:#14080B" if "高" in r["重要性"] else "" for _ in r], axis=1),
                 hide_index=True, width="stretch", height=min(35 * (len(顯示) + 1) + 3, 520),
                 column_config={"說明": st.column_config.TextColumn(width="large")})
    st.caption("時間為台灣時間。國際經濟數據與央行會議來自 ForexFactory（只列美、中、日、歐、英的中高重要性），"
               "美股財報來自 Nasdaq（只列台股供應鏈相關龍頭，「盤後」＝台灣隔天早上公布），法說會與除權息只列市值前 50 大。"
               "台灣央行理監事會每季一次（3、6、9、12 月），日期請以央行公告為準。")


def 連動區():
    段落("GLOBAL → TAIWAN // 美股與台股族群連動")
    分類 = st.segmented_control("連動分類", ["產業", "概念股"], default="概念股", key="連動分類",
                              label_visibility="collapsed") or "概念股"
    表, 最新 = 美股連動資料(_版本, 分類)
    if 表.empty:
        st.info("美股歷史資料（data/us_daily.csv）下次資料更新後就會出現。")
        return
    卡片格([卡片(f"{名} · {日:%m/%d}", f"{v:+.2f}%", "美股前一晚", 漲跌色(v)) for 名, (日, v) in 最新.items()][:6])
    美股龍頭區()
    if "落差%" in 表:
        跟漲 = 表[表["費城半導體"] >= 0.3]
        if len(跟漲):
            落後 = 跟漲.nsmallest(3, "落差%")
            超前 = 跟漲.nlargest(3, "落差%")
            st.markdown("**今天跟美股連動高、但走得比推估弱：** " + "、".join(f"{k}（{v:+.1f}%）" for k, v in 落後["落差%"].items())
                        + "　**比推估強：** " + "、".join(f"{k}（{v:+.1f}%）" for k, v in 超前["落差%"].items()))
    顯示 = 表.reset_index(names="族群")
    相關欄 = [c for c in 連動欄 if c in 顯示]
    百分欄 = [c for c in ("今天實際%", "依昨晚費半推估%", "落差%", "明天推估%") if c in 顯示]
    樣式 = 顯示.style.map(lambda v: f"background:rgba(255,59,92,{min(abs(v), 1) * 0.6:.2f})" if pd.notna(v) and v > 0
                  else (f"background:rgba(0,214,143,{min(abs(v), 1) * 0.6:.2f})" if pd.notna(v) else ""), subset=相關欄)
    樣式 = 樣式.map(lambda v: f"color:{漲跌色(v)}", subset=百分欄).format(
        {**{c: "{:+.2f}" for c in 相關欄}, **{c: "{:+.2f}" for c in 百分欄}, "費半敏感度": "{:.2f}"}, na_rep="—")
    表格(樣式, hide_index=True, width="stretch", height=min(35 * (len(顯示) + 1) + 3, 460))
    st.caption("相關係數：近 120 個交易日，台股族群當天漲跌和「前一晚」美股漲跌的關聯（1＝完全同向、0＝沒關係、越紅越同向）。"
               "費半敏感度＝費半漲 1% 時族群平均漲幾 %；推估＝敏感度 × 昨晚費半漲跌；落差＝今天實際 − 推估。"
               "相關不代表因果，只是過去的統計。明天推估在美股比台股新一天時才會出現。")


def 美股龍頭區():
    t = engine.美股超賣(engine.讀取美股())
    if t.empty:
        return
    超 = t[t["狀態"].isin(["超賣", "接近超賣"])]
    if len(超):
        話 = "🧊 <b>美股龍頭超賣提示</b>　" + "、".join(
            f"{k} {r['狀態']}（RSI {r['RSI']:.0f}、距月線 {r['距月線%']:+.1f}%）" for k, r in 超.iterrows()) +             "。超賣常有技術性反彈，但跌深不代表見底，要等止跌。"
    else:
        話 = "美股龍頭目前沒有超賣訊號。"
    st.markdown(f'<div class="verdict sub">{話}</div>', unsafe_allow_html=True)
    with st.expander("📋 美股龍頭 RSI 與乖離"):
        顯示 = t.reset_index(names="名稱")
        表格(顯示.style.map(lambda v: f"color:{綠 if '超賣' in str(v) else (紅 if v == '過熱' else '#EDEDED')}",
                                    subset=["狀態"]).map(lambda v: f"color:{漲跌色(v)}", subset=["距月線%", "距60日高%"])
                     .format({"日期": "{:%m/%d}", "收盤": "{:,.2f}", "RSI": "{:.1f}", "距月線%": "{:+.1f}",
                              "距60日高%": "{:+.1f}", "連跌天數": "{:.0f}"}),
                     hide_index=True, width="stretch", height=35 * (len(顯示) + 1) + 3)
        st.caption("RSI(14) 低於 30 或跌破 20 日均線 8% 以上＝超賣；RSI 低於 35 或跌破月線 5% 以上＝接近超賣；RSI 高於 70＝過熱。")


連動欄 = ["費城半導體", "那斯達克", "輝達", "蘋果", "台積電 ADR"]


@st.cache_data(ttl=3600, show_spinner=False)
def 美股連動資料(_資料版本, 分類):
    return engine.美股連動(指標, 分類)


@st.cache_data(ttl=600, show_spinner=False)
def 大盤解讀紀錄(_快取鍵):
    return engine.讀取大盤解讀(_設定())


def AI解讀區():
    段落("AI BRIEF // AI 大盤解讀")
    設定 = _設定()
    紀錄 = 大盤解讀紀錄(st.session_state.get("_解讀版本", 0))
    try:
        驗 = engine.驗收大盤解讀(紀錄, {"加權": 指數K線("TAIEX", _版本), "櫃買": 指數K線("TPEX", _版本)})
    except Exception:
        驗 = []
    分頁 = st.tabs(["收盤", "盤前", "夜盤"])
    for 模式, 頁 in zip(["收盤", "盤前", "夜盤"], 分頁):
        with 頁:
            這類 = [v for k, v in sorted(紀錄.items()) if v.get("模式") == 模式]
            if not 這類:
                st.caption(f"還沒有{模式}解讀。" + {"收盤": "每個交易日資料更新後（約 18:30）自動產生",
                                                 "盤前": "每個交易日 08:30 自動產生", "夜盤": "每個交易日 22:00 自動產生"}[模式]
                           + "（要在 GitHub 的 Actions secrets 設定 GEMINI_API_KEY）。")
                continue
            選 = 這類[-1]
            if len(這類) > 1:
                時間們 = [v["時間"] for v in 這類][::-1]
                t = st.selectbox("看哪一天", 時間們, key=f"解讀日{模式}", label_visibility="collapsed")
                選 = next(v for v in 這類 if v["時間"] == t)
            st.caption(f"🕒 {選['時間']}　·　{選.get('模型', '')}" + (f"　·　看法 {選['看法']}" if 選.get("看法") else ""))
            st.markdown(re.sub(r"^#{1,3}\s+", "##### ", 選["內容"], flags=re.M))  # 標題縮小，手機比較好讀
            if 選.get("條件"):
                結 = next((x for x in 驗 if x["時間"] == 選["時間"]), None)
                行們 = []
                for c in 選["條件"]:
                    對 = next((d for d in (結 or {}).get("條件", []) if d["說明"] == c["說明"]), None)
                    行們.append(f"- {'⏳' if 對 is None else ('✅' if 對['成立'] else '❌')} {c['說明']}"
                               + ("" if 對 is None else f"（{結['驗收日']:%m/%d} {c['指數']}收 {對['收盤']:,.2f}）"))
                st.markdown("**📌 這篇提出的觀察條件**　⏳ 還沒到收盤、✅ 成立、❌ 沒成立\n" + "\n".join(行們))
    if 驗:
        分 = engine.解讀記分(驗)
        with st.expander(f"🎯 AI 解讀記分板：近 {分['篇數']} 篇看法對 {分['看法命中']}/{分['看法篇數']}、"
                         f"條件成立 {分['條件成立']}/{分['條件數']}"):
            表格(pd.DataFrame([{
                "解讀": f"{x['時間']} {x['模式']}", "看法": x["看法"] or "—", "驗收日": f"{x['驗收日']:%m/%d}",
                "加權": f"{x['加權漲跌%']:+.2f}%", "看法對": "—" if x["看法對"] is None else ("✅" if x["看法對"] else "❌"),
                "條件": "；".join(f"{'✅' if c['成立'] else '❌'}{c['說明']}" for c in x["條件"])} for x in 驗[:20]]),
                hide_index=True, width="stretch", column_config={"條件": st.column_config.TextColumn(width="large")})
            st.caption("看法對＝偏多而隔一個收盤加權收紅、偏空而收黑（中性不計）。條件是 AI 自己提出的觀察價位，"
                       "成立不代表看對，主要用來回頭檢查 AI 抓的價位有沒有參考價值。")
    有金鑰 = str(設定.get("GEMINI_API_KEY", "")).strip() or str(設定.get("ANTHROPIC_API_KEY", "")).strip()
    if 有金鑰 and 可編輯():
        a, b = st.columns([1, 2])
        模式 = a.selectbox("模式", ["收盤", "盤前", "夜盤"], key="解讀模式", label_visibility="collapsed")
        if b.button("🧠 現在產生一份", key="產生解讀"):
            with st.spinner("AI 撰寫中，約 30～60 秒…"):
                try:
                    國際, 期貨 = 抓國際()
                    摘要 = engine.大盤摘要(指標, 加權, 國際, 期貨)
                    內容, 模型 = engine.AI大盤解讀(摘要, 模式, 設定)
                    engine.儲存大盤解讀(設定, 模式, 內容, 模型)
                    st.session_state["_解讀版本"] = st.session_state.get("_解讀版本", 0) + 1
                    st.rerun()
                except Exception as e:
                    st.error(f"產生失敗：{e}")
    st.caption("AI 只根據網站的大盤數據（指數、權值股、族群、法人、融資、期貨、情緒、國際行情、行事曆）撰寫，不會上網找新聞；"
               "僅供研究參考，不是買賣建議。")


def 一句話結論(內容):
    """從大盤解讀抓「一句話結論」那段的第一行。"""
    配 = re.search(r"#+\s*一句話結論[^\n]*\n+(.+?)(?:\n\s*\n|\n#|$)", str(內容), re.S)
    return 配.group(1).strip().replace("**", "") if 配 else ""


def 三十秒卡():
    """手機一眼看完：三條件燈號、加權格局、今天看的兩個價位，加上最新 AI 解讀的一句話。"""
    結果 = 價位分析("TAIEX", _版本)
    if 結果 is None:
        return
    K, sr, 區們, 解, 黑, 量價 = 結果
    try:
        項們, 總結 = engine.三條件燈號(指數K線("TAIEX", _版本), 指數K線("TPEX", _版本), engine.讀取美股())
    except Exception:
        項們, 總結 = [], ""
    燈們 = [燈 for _, 燈, _ in 項們]
    燈 = "🟢" if 燈們 and all(x == "🟢" for x in 燈們) else ("🔴" if 燈們.count("🔴") >= 2 else "🟡")
    格 = engine.格局判斷(K) or {"格局": "—", "說明": ""}
    支, 壓 = 解["最近支撐"], 解["最近壓力"]
    f = lambda r: "—" if r is None else f"{r['價位']:,.0f}"
    段落("30 SEC // 三十秒看盤")
    卡片格([卡片("觀察燈號", f"{燈} {''.join(燈們)}", 總結 or "資料不足", {"🟢": 紅, "🔴": 綠}.get(燈, "#FFC24B")),
           卡片("加權格局", 格["格局"], f"收盤 {sr['收盤']:,.0f}", {"上升": 紅, "下降": 綠}.get(格["格局"], "#EDEDED")),
           卡片("今天看的價位", f"{f(支)} / {f(壓)}",
                f"支撐{'' if 支 is None else 支['名稱']} · 壓力{'' if 壓 is None else 壓['名稱']}")])
    紀錄 = 大盤解讀紀錄(st.session_state.get("_解讀版本", 0))
    if 紀錄:
        最新 = 紀錄[sorted(紀錄)[-1]]
        句 = 一句話結論(最新.get("內容", ""))
        if 句:
            st.markdown(f'<div class="verdict"><b>AI {最新.get("模式", "")}解讀 {str(最新.get("時間", ""))[5:]}</b>　{句}</div>',
                        unsafe_allow_html=True)
    st.caption("燈號＝費半、加權、櫃買三個觀察條件；跌破支撐或站上壓力時，到下方「價位」區看下一個價位。僅供研究參考。")


@st.cache_data(ttl=3600, show_spinner=False, max_entries=1)
def 選擇權資料(_資料版本):
    return engine.讀取選擇權()


def 選擇權區():
    段落("OPTIONS // 選擇權籌碼：Put/Call Ratio、外資買賣權、最大未平倉")
    pc, 法, 分布 = 選擇權資料(_版本)
    if pc is None and 法 is None:
        st.caption("選擇權資料還沒下載，收盤後的資料更新會自動補上。")
        return
    卡們 = []
    if pc is not None and len(pc):
        v = pc["pc_oi"].iloc[-1]
        差 = v - pc["pc_oi"].iloc[-2] if len(pc) > 1 else np.nan
        卡們.append(卡片(f"P/C ratio（未平倉）· {pc.index[-1]:%m/%d}", f"{v:.1f}%",
                       ("" if pd.isna(差) else f"較前一日 {差:+.1f}　") + ("偏多" if v >= 100 else ("偏空" if v < 80 else "中性")),
                       紅 if v >= 100 else (綠 if v < 80 else "#EDEDED")))
    if 法 is not None and {"foreign_call_amt", "foreign_put_amt"} <= set(法.columns):
        買, 賣 = 法["foreign_call_amt"].iloc[-1] / 1e5, 法["foreign_put_amt"].iloc[-1] / 1e5
        卡們.append(卡片(f"外資買權淨未平倉 · {法.index[-1]:%m/%d}", f"{買:+.2f} 億", "正＝外資買進買權較多（偏多）", 漲跌色(買)))
        卡們.append(卡片("外資賣權淨未平倉", f"{賣:+.2f} 億", "正＝外資買進賣權較多（偏空避險）", 漲跌色(-賣)))
    for 種類, 名 in (("week", "本週"), ("month", "本月")):
        壓支 = engine.選擇權壓力支撐(分布, 種類, 1)
        if 壓支 and 壓支["壓力"] and 壓支["支撐"]:
            卡們.append(卡片(f"{名}選擇權壓力／支撐 · {壓支['合約']}", f"{壓支['壓力'][0][0]:,.0f}／{壓支['支撐'][0][0]:,.0f}",
                           f"買權最大未平倉 {壓支['壓力'][0][1]:,.0f} 口；賣權 {壓支['支撐'][0][1]:,.0f} 口", 青))
    卡片格(卡們)
    壓支 = engine.選擇權壓力支撐(分布, "month", 3)
    圖們 = st.columns(2)
    if 壓支:
        t = 壓支["表"]
        中心 = 加權["close"].iloc[-1] if 加權 is not None and len(加權) else t["strike"].median()
        t = t[t["strike"].between(中心 * 0.9, 中心 * 1.1)]
        圖 = go.Figure([go.Bar(x=t[t["cp"] == "call"]["strike"], y=t[t["cp"] == "call"]["oi"], name="買權（壓力）", marker_color=綠),
                        go.Bar(x=t[t["cp"] == "put"]["strike"], y=t[t["cp"] == "put"]["oi"], name="賣權（支撐）", marker_color=紅)])
        圖.add_vline(x=中心, line=dict(color="#FFFFFF", dash="dot", width=1))
        圖.update_layout(barmode="group", title=dict(text=f"{壓支['合約']} 各履約價未平倉（口）", font=dict(size=12)),
                         legend=dict(orientation="h", y=1.12))
        圖們[0].plotly_chart(圖表外觀(圖, 300), width="stretch")
    if pc is not None and len(pc) > 5:
        近 = pc.tail(120)
        圖 = make_subplots(specs=[[{"secondary_y": True}]])
        圖.add_trace(go.Scatter(x=近.index, y=近["pc_oi"], name="P/C ratio（未平倉）%", line=dict(color="#FFB020", width=2)))
        if 加權 is not None and len(加權):
            指 = 加權.set_index("date")["close"].reindex(近.index)
            圖.add_trace(go.Scatter(x=近.index, y=指, name="加權指數", line=dict(color="#FFFFFF", width=1)), secondary_y=True)
        圖.add_hline(y=100, line=dict(color=灰, dash="dot", width=1))
        圖.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
        圖.update_layout(title=dict(text="P/C ratio 與加權指數", font=dict(size=12)), legend=dict(orientation="h", y=1.12))
        圖們[1].plotly_chart(圖表外觀(圖, 300), width="stretch")
    st.caption("P/C ratio＝賣權未平倉量 ÷ 買權未平倉量。台灣通常解讀為：超過 100% 偏多（賣權多，代表有人賣出 put 當支撐）、"
               "低於 80% 偏空。買權未平倉最多的履約價常被當成壓力、賣權最多的當成支撐，結算日前參考性最高。"
               "外資買賣權淨額單位是契約金額（億元）。資料：期交所。")


def 事件區():
    段落("EVENTS // 新股申購抽籤、庫藏股、可轉債")
    分頁們 = st.tabs(["🎫 新股申購抽籤", "🛒 庫藏股", "📜 可轉債"])
    現價 = 今日.set_index("代號")["收盤"]
    with 分頁們[0]:
        申 = engine.讀取新股申購()
        if 申 is None:
            st.caption("公開申購資料還沒下載。")
        else:
            t = engine.申購試算(申, 現價)
            近 = t[t["draw_date"] >= 最新日 - pd.Timedelta(days=7)].sort_values("draw_date")
            if not len(近):
                st.caption("最近沒有可以申購的股票，下面是最近 10 筆。")
                近 = t.sort_values("draw_date").tail(10)
            顯示 = pd.DataFrame({"抽籤日": 近["draw_date"].dt.strftime("%m/%d"), "代號": 近["code"], "名稱": 近["name"],
                                "類型": 近["market"], "申購期間": 近["start"].dt.strftime("%m/%d") + "～" + 近["end"].dt.strftime("%m/%d"),
                                "承銷價": 近["price"], "現價": 近["現價"], "每簽獲利": 近["每簽獲利"], "報酬%": 近["報酬%"],
                                "中籤率%": 近["win_rate"].where(近["win_rate"] > 0), "撥券日": 近["list_date"].dt.strftime("%m/%d")})
            點選表(顯示, 上色(顯示).format({"承銷價": "{:,.2f}", "現價": "{:,.2f}", "每簽獲利": "{:+,.0f}", "報酬%": "{:+.1f}",
                                         "中籤率%": "{:.2f}"}, na_rep="—"), "申購表", column_config={"代號": None})
            st.caption("每簽獲利＝（現價 − 承銷價）× 1,000 股，沒扣申購手續費 20 元與中籤通知郵資 50 元；"
                       "初上市櫃的股票還沒有現價。抽籤前一天價差可能變很多，申購前再確認一次。資料：證交所公開申購公告。")
    with 分頁們[1]:
        庫 = engine.讀取庫藏股()
        if 庫 is None:
            st.caption("庫藏股資料還沒下載。")
        else:
            近 = 庫[(庫["end"] >= 最新日) | (庫["board_date"] >= 最新日 - pd.Timedelta(days=45))].sort_values("board_date", ascending=False)
            顯示 = pd.DataFrame({"決議日": 近["board_date"].dt.strftime("%m/%d"), "代號": 近["code"], "名稱": 近["name"],
                                "預定張數": 近["planned"] / 1000, "價格下限": 近["price_low"], "價格上限": 近["price_high"],
                                "現價": 近["code"].map(現價), "買回期間": 近["start"].dt.strftime("%m/%d") + "～" + 近["end"].dt.strftime("%m/%d"),
                                "狀態": np.where(近["done"].astype(str).str.upper() == "Y", "已完畢", "執行中"),
                                "已買回%": 近["pct_done"], "佔股本%": 近["pct_shares"]})
            點選表(顯示, 上色(顯示).format({"預定張數": "{:,.0f}", "價格下限": "{:,.2f}", "價格上限": "{:,.2f}", "現價": "{:,.2f}",
                                         "已買回%": "{:.1f}", "佔股本%": "{:.2f}"}, na_rep="—"), "庫藏股表", column_config={"代號": None})
            st.caption("近 45 天董事會決議、或還在買回期間的庫藏股。現價接近或低於價格下限時，公司較可能進場買。"
                       "資料：公開資訊觀測站。")
    with 分頁們[2]:
        債 = engine.讀取可轉債()
        if 債 is None:
            st.caption("可轉債資料還沒下載。")
        else:
            近 = 債[債["issue_date"] >= 最新日 - pd.Timedelta(days=120)].sort_values("issue_date", ascending=False)
            顯示 = pd.DataFrame({"發行日": 近["issue_date"].dt.strftime("%Y/%m/%d"), "代號": 近["code"], "債券名稱": 近["name"],
                                "發行億元": 近["amount"] / 1e8, "轉換價": 近["conv_price"], "現價": 近["code"].map(現價),
                                "到期日": 近["maturity"].dt.strftime("%Y/%m/%d")})
            點選表(顯示, 上色(顯示).format({"發行億元": "{:,.1f}", "轉換價": "{:,.2f}", "現價": "{:,.2f}"}, na_rep="—"),
                  "可轉債表", column_config={"代號": None})
            st.caption("近 120 天發行的國內可轉換公司債。可轉債將來轉成股票會稀釋股本；現價高於轉換價越多，越可能被轉換。"
                       "資料：櫃買中心債券發行資料。")


首頁區塊 = ["30秒", "市場", "狀態", "價位", "AI解讀", "焦點", "國際", "連動", "加權指數", "權值", "資金", "選擇權", "情緒", "族群", "行事曆", "事件", "排行"]


新手區塊 = ["30秒", "市場", "狀態", "AI解讀", "焦點", "排行"]
版面們 = {"新手": "只看 6 個重點區塊", "完整": "全部區塊", "自訂": "自己挑、自己排順序"}


def 讀版面():
    """網址 layout=新手／完整／自訂:區塊1,區塊2…；舊的 hide= 書籤當成自訂。"""
    值 = st.query_params.get("layout", "")
    if 值 in ("新手", "完整"):
        return 值, None
    if 值.startswith("自訂:"):
        return "自訂", [x for x in 值[3:].split(",") if x in 首頁區塊]
    隱 = [x for x in st.query_params.get("hide", "").split(",") if x in 首頁區塊]
    if 隱:
        return "自訂", [x for x in 首頁區塊 if x not in 隱]
    return "完整", None


舊模式, 舊順序 = 讀版面()
with st.expander(f"⚙️ 首頁版面：{舊模式}"):
    模式 = st.segmented_control("版面", list(版面們), default=舊模式, key="首頁版面",
                              format_func=lambda m: f"{m}（{版面們[m]}）") or 舊模式
    if 模式 == "自訂":
        顯示 = st.multiselect("要顯示的區塊（照點選的順序排列）", 首頁區塊, key="首頁區塊順序",
                             default=舊順序 if 舊順序 is not None else 首頁區塊)
        st.caption("想把某個區塊移到前面：先按 × 移除其他區塊，再照想要的順序點回來。")
    else:
        顯示 = 新手區塊 if 模式 == "新手" else 首頁區塊
    st.caption("設定記在網址裡，把這個網址加入書籤或手機主畫面就會保留。")
新值 = "自訂:" + ",".join(顯示) if 模式 == "自訂" else 模式
舊值 = "自訂:" + ",".join(舊順序) if 舊模式 == "自訂" else 舊模式
if 新值 != 舊值 or "hide" in st.query_params:
    if 新值 == "完整":
        st.query_params.pop("layout", None)
    else:
        st.query_params["layout"] = 新值
    st.query_params.pop("hide", None)
def _國際():
    try:
        國際行情()
    except Exception:
        st.caption("國際行情暫時無法顯示。")
區塊函式 = {"30秒": 三十秒卡, "市場": 市場卡片, "狀態": 狀態區, "價位": 關鍵價位區, "AI解讀": AI解讀區, "焦點": 焦點區, "國際": _國際, "連動": 連動區,
         "加權指數": 加權圖 if 加權 is not None and len(加權) > 1 else None, "權值": 權值區, "資金": 資金面區, "選擇權": 選擇權區, "事件": 事件區,
         "情緒": 情緒區, "族群": 族群熱力圖, "行事曆": 行事曆區, "排行": 排行區}
盤中即時條()
要畫 = [x for x in 顯示 if 區塊函式.get(x)]
if len(要畫) > 3:  # 首頁很長，上方放一排快速跳轉
    st.markdown('<div class="jump">' + "".join(f'<a href="#h-{x}" target="_self">{x}</a>' for x in 要畫)
                + "</div>", unsafe_allow_html=True)
for x in 要畫:
    st.markdown(f'<div class="anchor" id="h-{x}"></div>', unsafe_allow_html=True)
    區塊函式[x]()
