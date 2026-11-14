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


@st.cache_data(ttl=20, show_spinner=False)
def _大盤即時():
    表 = engine.即時報價(["t00", "o00"], {"o00": "上櫃"})
    表 = 表.dropna(subset=["close"]).set_index("code") if not 表.empty else 表
    if 表.empty:
        raise ValueError("沒有即時報價")  # 失敗不快取
    return 表


def 大盤即時():
    """加權（t00）、櫃買（o00）盤中即時點數，所有人共用 20 秒快取；抓不到先用上一筆，都沒有才回傳 None。"""
    return 抓取留底(("大盤即時",), _大盤即時, 冷卻秒=30)


@st.fragment(run_every=刷新秒(30))
def 盤中即時條():
    """首頁最上方的盤中即時橫條，只在 9:00～13:35 顯示，每 30 秒更新。"""
    輪詢檢查()  # 開盤／收盤時切換自動更新頻率
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
        卡 = 卡片(f"⚡ {名稱} · {r['time']}", f"{r['close']:,.2f}",
                f"{r['change']:+,.2f}（{漲幅:+.2f}%）{高低}", 漲跌色(r["change"]),
                錨("大盤走勢") if 代號 == "t00" else 錨("價位"))
        前 = st.session_state.get(f"_即時前值{代號}")  # 跟上次更新比：漲了閃紅、跌了閃綠
        st.session_state[f"_即時前值{代號}"] = float(r["close"])
        if 前 is not None and float(r["close"]) != 前:
            卡 = f'<div class="{"flash-up" if float(r["close"]) > 前 else "flash-dn"}">{卡}</div>'
        卡們.append(卡)
    if 卡們:
        st.markdown(f'<div class="grid2">{"".join(卡們)}</div>', unsafe_allow_html=True)
        st.caption("盤中即時（證交所，延遲約 5～20 秒，每 30 秒自動更新）；點加權卡片可看當日即時走勢。"
                   "成交金額、漲跌家數、排行與法人是收盤後的資料。")


@st.fragment(run_every=刷新秒(30))
def 加權圖():
    輪詢檢查()  # 開盤／收盤時切換自動更新頻率
    段落("INDEX // 大盤走勢 K 線")
    指數 = st.segmented_control("指數", ["加權指數", "櫃買指數", "台指期", "美元/台幣"], default="加權指數", key="大盤指數",
                              label_visibility="collapsed") or "加權指數"
    if 指數 in ("台指期", "美元/台幣"):   # 這兩個只有日資料，直接畫日 K
        區間 = st.segmented_control("區間", ["1月", "1季", "半年", "1年"], default="1季", key="其他區間",
                                  label_visibility="collapsed") or "1季"
        K = engine.讀取台指期K線() if 指數 == "台指期" else engine.讀取匯率K線()
        if K is None or len(K) < 2:
            st.info(f"{指數}資料暫時抓不到。")
            return
        量 = K.set_index("date")["volume"] if "volume" in K.columns else None
        大盤日K(K, 區間, {"1月": 31, "1季": 92, "半年": 183, "1年": 365}[區間], 指數, 量=量, 量名="成交量（口）")
        st.caption("台指期是大台近月合約（期交所一般盤），換月那天價格會跳一下。" if 指數 == "台指期" else
                   "美元/台幣：數字變大＝台幣貶值（外資常同時賣超台股），變小＝台幣升值。")
        return
    櫃 = 指數 == "櫃買指數"
    即時代號, K代號 = ("o00", "TPEX") if 櫃 else ("t00", "TAIEX")
    日線 = 指數K線("TPEX", _版本) if 櫃 else 加權
    預設區間 = "當日" if engine.盤中時間() else "1季"   # 盤中先看當日走勢，收盤後先看日 K
    區間 = st.segmented_control("區間", ["當日", "5日", "1月", "1季", "半年", "1年", "3年", "5年"],
                              default=預設區間, key="加權區間", label_visibility="collapsed") or 預設區間
    分時 = 讀檔("讀取分時", _版本)
    即時點 = None
    if engine.盤中時間():
        即時點 = 大盤即時()
        if 即時點 is not None and 即時代號 in 即時點.index:
            r = 即時點.loc[即時代號]
            st.markdown(卡片(f"{'TPEx 櫃買' if 櫃 else 'TAIEX 加權'} 盤中即時 · {r['time']}", f"{r['close']:,.2f}",
                           f"{r['change']:+,.2f}（{r['change'] / (r['close'] - r['change']) * 100:+.2f}%）",
                           漲跌色(r["change"])), unsafe_allow_html=True)
    if 區間 in ("當日", "5日"):
        # 先用 Yahoo 的分鐘線（盤中也會更新），抓不到再用每天收盤後存下來的分時資料
        線 = 分鐘線(即時代號, "", "1m" if 區間 == "當日" else "5m", "5d")
        過期提示(線)
        if 線 is not None and len(線):
            線 = 線.assign(day=線["datetime"].dt.normalize())
            天們 = sorted(線["day"].unique())[-1:] if 區間 == "當日" else sorted(線["day"].unique())[-5:]
            資料 = 線[線["day"].isin(天們)]
            x, y = 資料["datetime"], 資料["close"]
        elif 分時 and not 櫃:
            天們 = list(分時)[-1:] if 區間 == "當日" else list(分時)[-5:]
            資料 = pd.concat([分時[d] for d in 天們])
            x, y = 資料["datetime"], 資料["taiex"]
        else:
            st.info("分時資料暫時抓不到。")
            return
        基準 = 日線[日線["date"] < pd.Timestamp(天們[0])]["close"]
        昨收 = 基準.iloc[-1] if len(基準) else y.iloc[0]
        st.caption(f"{pd.Timestamp(天們[-1]):%Y/%m/%d} 走勢" + ("（盤中約每 30 秒更新）" if engine.盤中時間() else ""))
    else:
        天數 = {"1月": 31, "1季": 92, "半年": 183, "1年": 365, "3年": 365 * 3, "5年": 365 * 5}[區間]
        K = 指數K線(K代號, _版本)
        if engine.有開高低(K):
            大盤日K(K, 區間, 天數, "櫃買" if 櫃 else "加權", 量=指數成交值(K代號, _版本))
            return
        資料 = 日線[日線["date"] >= 日線["date"].max() - pd.Timedelta(days=天數)]
        x, y = 資料["date"], 資料["close"]
        昨收 = y.iloc[0]
    色 = 紅 if y.iloc[-1] >= 昨收 else 綠
    填色 = "rgba(255,59,92,0.08)" if 色 == 紅 else "rgba(0,214,143,0.08)"
    圖 = go.Figure(go.Scatter(x=x, y=y, line=dict(color=色, width=1.6), fill="tozeroy",
                              fillcolor=填色, name=指數))
    圖.add_hline(y=昨收, line=dict(color=灰, width=1, dash="dot"))
    圖.update_yaxes(range=[min(y.min(), 昨收) * 0.995, max(y.max(), 昨收) * 1.005])
    if 區間 in ("當日", "5日"):
        # 跳過收盤後與週末的空白時段
        圖.update_xaxes(rangebreaks=[dict(bounds=[13.6, 9], pattern="hour"), dict(bounds=["sat", "mon"])])
    漲跌 = y.iloc[-1] - 昨收
    st.caption(f"{區間}漲跌：{漲跌:+,.2f}（{漲跌 / 昨收 * 100:+.2f}%）")
    st.plotly_chart(圖表外觀(圖, 300), width="stretch")


def 大盤日K(K, 區間, 天數, 名稱="加權", 量=None, 量名="成交金額（億）"):
    """日 K 線＋5 日／月線／季線＋下方量能副圖；3 年、5 年改看週 K，K 棒才不會擠成一條線。
    量：index＝date 的 Series（成交金額或成交口數），沒有就不畫副圖。圖上標最新價、區間最高最低。"""
    from plotly.subplots import make_subplots
    k = K.copy()
    週K = 區間 in ("3年", "5年")
    if 量 is not None and len(量):
        k = k.merge(量.rename("量").rename_axis("date").reset_index(), on="date", how="left")
    if 週K:
        聚 = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "量" in k.columns:
            聚["量"] = "sum"
        k = k.set_index("date").resample("W-FRI").agg(聚).dropna(subset=["close"]).reset_index()
    均線們 = ((5, "#FFC24B", "5週線"), (13, 青, "季線"), (52, "#FF00E5", "年線")) if 週K else \
        ((5, "#FFC24B", "5日線"), (20, 青, "月線"), (60, "#FF00E5", "季線"))
    for n, _, _ in 均線們:
        k[f"MA{n}"] = k["close"].rolling(n).mean()
    k["前收"] = k["close"].shift()
    k = k[k["date"] >= k["date"].max() - pd.Timedelta(days=天數)].reset_index(drop=True)
    if len(k) < 2:
        st.info("日 K 資料暫時抓不到。")
        return
    尾 = k.iloc[-1]
    前收 = 尾["前收"] if pd.notna(尾["前收"]) else k["close"].iloc[-2]
    格 = ",.0f" if 尾["close"] >= 1000 else ",.3f" if 尾["close"] < 100 else ",.2f"   # 匯率看到小數第三位
    價格 = 格.replace(",.0f", ",.2f")
    # 重點卡：收盤、當日（本週）、區間漲跌
    當日 = 尾["close"] - 前收
    漲跌 = 尾["close"] - k["close"].iloc[0]
    卡們 = [卡片(f"{名稱} · {尾['date']:%m/%d} 收盤", f"{尾['close']:{價格}}", f"{當日:+{格}}（{當日 / 前收 * 100:+.2f}%）", 漲跌色(當日)),
           卡片(f"{區間}漲跌", f"{漲跌 / k['close'].iloc[0] * 100:+.2f}%", f"{漲跌:+{格}}", 漲跌色(漲跌))]
    if not 手機:   # 手機上高低點已標在圖上，少一張卡讓圖早點出現
        卡們.append(卡片(f"{區間}高／低", f"{k['high'].max():{格}}", f"低 {k['low'].min():{格}}"))
    卡片格(卡們)
    位置 = []
    for n, _, 名 in 均線們[1:]:
        v = 尾[f"MA{n}"]
        if pd.notna(v):
            位置.append(f"{'✅ 站上' if 尾['close'] >= v else '⚠️ 跌破'}{名} {v:{格}}")
    if 位置:
        st.caption("　".join(位置))
    有量 = "量" in k.columns and k["量"].notna().sum() > len(k) * 0.5
    有K = engine.有開高低(k)
    圖 = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.76, 0.24]) if 有量 \
        else make_subplots(rows=1, cols=1)
    漲 = k["close"] >= k["open"] if 有K else k["close"] >= k["前收"].fillna(k["close"])
    幅 = (k["close"] / k["前收"] - 1) * 100
    提示 = [f"{d:%Y/%m/%d}<br>開 {o:{格}}　高 {h:{格}}<br>低 {l:{格}}　收 {c:{格}}<br>漲跌 {'—' if pd.isna(f) else f'{f:+.2f}%'}"
            for d, o, h, l, c, f in zip(k["date"], k["open"], k["high"], k["low"], k["close"], 幅)]
    if 有K:
        圖.add_trace(go.Candlestick(x=k["date"], open=k["open"], high=k["high"], low=k["low"], close=k["close"],
                                    name="K 線", text=提示, hoverinfo="text",
                                    increasing=dict(line=dict(color=紅, width=1), fillcolor=紅),
                                    decreasing=dict(line=dict(color=綠, width=1), fillcolor=綠)), row=1, col=1)
    else:   # 還沒有開高低資料先畫收盤線
        圖.add_trace(go.Scatter(x=k["date"], y=k["close"], name="收盤", text=提示, hoverinfo="text",
                                line=dict(color="#EDEDED", width=1.6)), row=1, col=1)
    for n, 色, 名 in 均線們:
        圖.add_trace(go.Scatter(x=k["date"], y=k[f"MA{n}"], name=名, line=dict(color=色, width=1.2), hoverinfo="skip"),
                    row=1, col=1)
    if 有量:
        圖.add_trace(go.Bar(x=k["date"], y=k["量"], name=量名, showlegend=False,
                            marker=dict(color=[紅 if u else 綠 for u in 漲], opacity=0.55),
                            hovertemplate=f"{量名} %{{y:,.0f}}<extra></extra>"), row=2, col=1)
        圖.update_yaxes(row=2, col=1, showgrid=False, tickfont=dict(size=9), nticks=3)
    # 最新價虛線＋右側標籤；區間最高、最低標出來
    最新色 = 漲跌色(當日)
    圖.add_hline(y=尾["close"], line=dict(color=最新色, width=1, dash="dot"), row=1, col=1)
    圖.add_annotation(x=1, xref="paper", y=尾["close"], yref="y", xanchor="left", showarrow=False,
                      text=f"{尾['close']:{格}}", font=dict(size=11, color="#000"), bgcolor=最新色, borderpad=2)
    高i, 低i = k["high"].idxmax(), k["low"].idxmin()
    圖.add_annotation(x=k["date"][高i], y=k["high"][高i], yref="y", text=f"高 {k['high'][高i]:{格}}", showarrow=True,
                      arrowhead=0, ax=0, ay=-18, font=dict(size=10, color=紅))
    圖.add_annotation(x=k["date"][低i], y=k["low"][低i], yref="y", text=f"低 {k['low'][低i]:{格}}", showarrow=True,
                      arrowhead=0, ax=0, ay=18, font=dict(size=10, color=綠))
    if not 週K:   # 跳過週末與休市日，K 棒才會連在一起
        缺 = sorted(set(pd.date_range(k["date"].min(), k["date"].max(), freq="D")) - set(k["date"]))
        圖.update_xaxes(rangebreaks=[dict(values=[d.strftime("%Y-%m-%d") for d in 缺])])
    圖表外觀(圖, (360 if 有量 else 300) if 手機 else (440 if 有量 else 380))
    圖.update_layout(xaxis_rangeslider_visible=False, showlegend=True, hovermode="x",
                    margin=dict(l=8, r=62, t=10, b=10),
                    legend=dict(orientation="h", y=1.01, yanchor="bottom", x=0, font=dict(size=10 if 手機 else 11)))
    圖.update_xaxes(showspikes=True, spikemode="across", spikethickness=1, spikecolor="#555", spikedash="dot")
    圖.update_xaxes(nticks=5 if 手機 else 8)
    st.plotly_chart(圖, width="stretch")
    說明 = ("週 K" if 週K else "日 K") + "：紅棒收漲、綠棒收跌；細線是均線，價格在均線上方代表短中期趨勢偏多。" if 有K else "目前只有收盤價，先畫收盤線。"
    if 有量:
        說明 += f"下方柱子是{量名}，紅柱＝當天收漲。"
    st.caption(說明)

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
    族群輪動區(來源)
    連板與流入區(分類)
    if 分類 == "概念股":
        st.caption("概念股是自己整理的題材清單（data/concepts.csv，約 25 個題材），一檔股票可以同時屬於好幾個概念；"
                   "想增刪可以直接在 GitHub 編輯這個檔案。")


def 連板與流入區(分類):
    """連續漲停名單與歷史統計、族群連續資金流入天數（短線追強、老二老三補漲用）。"""
    try:
        今連, 連統 = engine.連板統計(指標)
        流 = engine.族群連續流入(指標, 分類)
    except Exception:
        return
    with st.expander(f"🔥 連續漲停與連續資金流入（連板 {len(今連)} 檔、連續流入族群 {len(流)} 個）", expanded=False):
        if len(今連):
            st.markdown("**今天連續漲停（2 天以上）**")
            表格(今連, hide_index=True, width="stretch", height=min(360, 38 + 35 * len(今連)),
                 column_config={"漲跌幅": st.column_config.NumberColumn(format="%+.2f%%")})
        if len(連統):
            st.markdown("**歷史上連板之後隔天、5 天的報酬**")
            表格(連統, hide_index=True, width="stretch")
        if len(流):
            st.markdown(f"**連續資金流入 3 天以上的{分類}**")
            表格(流, hide_index=True, width="stretch")
        st.caption("連板＝收盤接近漲停（漲幅 9.5% 以上且收在最高）；統計用近一年多資料的一般股票，不含 ETF，沒有扣手續費，連板股有流動性風險（可能鎖到買不到）。"
                   "資金流入日＝族群當天上漲且成交值占全市場比例高於前 20 日平均。看的是熱度，連續流入 3 天以上之後熱度退了就要出場。")


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
        # 個股方塊的 id 以代號結尾（產業/2330），點一下就會切到那檔的個股查詢
        ids=名們 + (個股["產業"] + "/" + 個股["代號"].fillna("").astype(str).where(個股["代號"].notna() & (個股["代號"] != ""), 個股["名稱"])).tolist(),
        labels=名們 + 個股["名稱"].tolist(),
        parents=[""] * len(名們) + 個股["產業"].tolist(),
        values=[0] * len(名們) + 個股["權重"].tolist(),
        branchvalues="remainder",
        customdata=族群["漲跌幅"].tolist() + 個股["幅度"].tolist(),
        marker=dict(colors=族群["漲跌幅"].tolist() + 個股["幅度"].tolist(), cmin=-界, cmid=0, cmax=界,
                    colorscale=[[0, "#00A86B"], [0.5, "#262626"], [1, "#E0244A"]],
                    line=dict(color="#000", width=1)),
        texttemplate="<b>%{label}</b><br>%{customdata:+.2f}%",
        hovertext=[(f"預估本益比 {v:.1f} 倍" if pd.notna(v) else "") for v in 族群.get("預估本益比", pd.Series(np.nan, index=族群.index))]
                  + [""] * len(個股),
        hovertemplate="<b>%{label}</b><br>漲跌 %{customdata:+.2f}%<br>%{hovertext}<extra></extra>",
        textfont=dict(color="#FFF", family="Noto Sans TC"), maxdepth=2, pathbar=dict(visible=True),
        tiling=dict(pad=1),
    ))
    圖.update_layout(height=560, margin=dict(l=0, r=0, t=24, b=0), paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(圖, width="stretch", config={"displayModeBar": False})
    st.caption(f"方塊越大代表{大小}越大；紅漲綠跌，顏色越深漲跌越多（±{界}% 以上最深）。"
               "點一下族群可放大看裡面的股票，再點個股方塊就會切到那檔的個股查詢；點上方路徑可返回。族群漲跌是依" + 大小 + "加權平均。")


@st.cache_data(ttl=43200, max_entries=1, show_spinner=False)
def 營收體質(版本鍵):
    """題材股是「有營收」還是「還在做夢」：近 3 個月營收年增 ≥ 20% 算有營收，≤ 0 算做夢。"""
    t, _ = engine.月營收總表()
    if t.empty:
        return {}
    y = t["近3月年增"]
    return pd.Series(np.select([y >= 20, y <= 0], ["📈 有營收", "💭 做夢"], "➖ 持平"), index=t.index).where(y.notna()).dropna().to_dict()


def 族群排行(族群, 期間, 來源):
    表 = 族群.reset_index().rename(columns={"產業": "族群"})
    表 = 表[[c for c in ["族群", "漲跌幅", "上漲", "下跌", "成交值億", "預估本益比", "明年預估本益比", "領漲股"] if c in 表.columns]]
    st.markdown("**族群排行**　點一下族群，下方會列出成分股")
    選 = 表格(表.style.map(lambda v: f"color:{漲跌色(v)}", subset=["漲跌幅"])
                     .format({"漲跌幅": "{:+.2f}%", "成交值億": "{:,.1f}", "預估本益比": "{:.1f}", "明年預估本益比": "{:.1f}"},
                             na_rep="—"),
                     key="族群表", on_select="rerun", selection_mode="single-row", hide_index=True,
                     width="stretch", height=300)
    列們 = 選.selection.rows
    if 列們:
        族 = 表.iloc[列們[0]]["族群"]
        欄 = engine.族群期間[期間]
        成分 = 來源[(來源["產業"] == 族) & (來源["收盤"] > 0)].sort_values(欄, ascending=False)
        成分 = 成分[[c for c in ["名稱", "收盤", "漲跌幅", "5日漲幅", "20日漲幅", "成交張數", "本益比", "預估本益比",
                              "明年預估本益比", "代號"] if c in 成分.columns]].rename(columns={"收盤": "股價"})
        if 來源 is not 今日:
            營 = 營收體質(_版本)
            成分.insert(1, "營收", 成分["代號"].map(營).fillna("—"))
        st.markdown(f"**{族}**　{len(成分)} 檔，依{期間}漲跌排序，點股票可看個股查詢")
        點選表(成分, 上色(成分), "族群成分", height=min(35 * (len(成分) + 1) + 3, 420))
        if "營收" in 成分:
            st.caption("營收：近 3 個月營收年增 20% 以上＝📈 有營收；0 以下＝💭 還在做夢（題材還沒變成營收）。")
    if "預估本益比" in 表.columns:
        st.caption("族群預估本益比＝族群裡有正的預估 EPS 的股票，合計市值 ÷ 合計預估獲利（大型股影響較大，虧損股不算）。"
                   "預估 EPS 是使用者上傳的全市場預估（A、B 兩源中位數）。")


@st.cache_resource(max_entries=1, show_spinner=False)
def 市場每日(版本鍵):
    """最近 70 個交易日每天的大盤數字，給前後期比較用。"""
    近 = 指標[指標["date"] >= 指標["date"].max() - pd.Timedelta(days=110)]
    群 = 近.groupby("date")
    表 = pd.DataFrame({"成交金額": 群["成交值億"].sum(), "上漲": 群["漲跌"].apply(lambda s: (s > 0).sum()),
                       "下跌": 群["漲跌"].apply(lambda s: (s < 0).sum())})
    if 有籌碼:
        金額 = lambda 欄: (近[欄] * 1000 * 近["收盤"]).groupby(近["date"]).sum() / 1e8
        表["外資"] = 金額("外資買超")
        表["法人"] = 金額("法人買超")
        表["融資"] = 近.groupby("date")["融資餘額"].sum(min_count=1)
        維持 = engine.融資維持率(近)
        if 維持 is not None:
            表["維持率"] = 維持.reindex(表.index)
        表["融資變化%"] = engine.大盤融資變化(近, "代號", "收盤", "融資餘額").reindex(表.index)
    期 = 讀檔("讀取期貨未平倉", _版本)
    if 期 is not None and "foreign_oi" in 期:
        表["外資期貨"] = 期["foreign_oi"].reindex(表.index)
        for 英, 中 in (("trust_oi", "投信期貨"), ("dealer_oi", "自營期貨")):
            if 英 in 期:
                表[中] = 期[英].reindex(表.index)
    if 加權 is not None and not 加權.empty:
        表["加權"] = 加權.set_index("date")["close"].reindex(表.index)
    匯率 = 讀檔("讀取匯率", _版本)
    if 匯率 is not None and len(匯率):
        表["匯率"] = 匯率.set_index("date")["usdtwd"].reindex(表.index).ffill()
    return 表


@st.fragment(run_every=刷新秒(60))
def 市場卡片():
    輪詢檢查()  # 開盤／收盤時切換自動更新頻率
    段落("MARKET // 市場")
    上漲 = (今日["漲跌"] > 0).sum()
    下跌 = (今日["漲跌"] < 0).sum()
    卡們 = []
    即 = 大盤即時() if engine.盤中時間() else None
    即時加權 = 即.loc["t00"] if 即 is not None and "t00" in 即.index else None
    if 即時加權 is not None:
        r = 即時加權
        卡們.append(卡片(f"⚡ TAIEX 加權 · 盤中 {r['time']}", f"{r['close']:,.0f}",
                       f"{r['change']:+,.2f}（{r['change'] / (r['close'] - r['change']) * 100:+.2f}%）",
                       漲跌色(r["change"]), 錨("大盤走勢")))
    elif 加權 is not None and not 加權.empty:
        最後 = 加權.iloc[-1]
        漲幅 = 最後["change"] / (最後["close"] - 最後["change"]) * 100
        卡們.append(卡片(f"TAIEX 加權指數 · {最後['date']:%m/%d}", f"{最後['close']:,.0f}",
                       f"{最後['change']:+,.2f}  ({漲幅:+.2f}%)", 漲跌色(最後["change"]), 錨("大盤走勢")))
    卡們 += [
        卡片("資料日期", 最新日.strftime("%m/%d"), 最新日.strftime("%Y") + ("・收盤資料" if 即時加權 is not None else "")),
        卡片("成交金額", f"{今日['成交值億'].sum():,.0f}", "億元", 連結=錨("資金")),
        卡片("上漲家數", f"{上漲}", "▲", 紅, 錨("排行")),
        卡片("下跌家數", f"{下跌}", "▼", 綠, 錨("排行")),
    ]
    匯率 = 讀檔("讀取匯率", _版本)
    if 匯率 is not None and len(匯率) >= 2:
        今, 昨 = 匯率["usdtwd"].iloc[-1], 匯率["usdtwd"].iloc[-2]
        差 = 今 - 昨
        # 美元兌台幣數字變小 = 台幣升值（紅），變大 = 台幣貶值（綠）
        狀態, 色 = ("台幣升值 ▲", 紅) if 差 < 0 else (("台幣貶值 ▼", 綠) if 差 > 0 else ("持平", "#EDEDED"))
        卡們.append(卡片(f"美元/台幣 · {匯率['date'].iloc[-1]:%m/%d}", f"{今:.3f}", f"{差:+.3f} {狀態}", 色, 錨("國際")))
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
        欄位 = {k: v for k, v in 欄位.items() if k in 每日.columns and 每日[k].tail(5).notna().any()}
        with st.expander("📊 前後期比較（昨日、5 日前、20 日前、60 日前）", expanded=not 手機):
            即時欄 = None
            if 即時加權 is not None and "加權" in 欄位:
                即時欄 = (f"⚡盤中 {即時加權['time'][:5]}", {"加權": float(即時加權["close"])})
            前後期表(每日, 欄位, [("昨日", 1), ("5 日前", 5), ("20 日前", 20), ("60 日前", 60)],
                     lambda d: f"{d:%m/%d}", 反向={"下跌", "融資", "匯率"}, 即時=即時欄)
            st.caption("🔴 偏多：指數、成交、上漲家數、法人買超變多，融資減少、台幣升值；🟢 反之。"
                       "外資／法人金額用買賣超張數 × 收盤價估算。本期＝最近一次收盤（每天約 18:00 更新）"
                       + ("；盤中另外列出加權指數的即時點數與較本期漲跌。" if 即時欄 else "。"))


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
                       ("" if pd.isna(差) else f"較前一日 {差:+.1f}　") + 等級 + "（網站估算）", 色))
        官方 = float(st.session_state.get("官方維持率") or 0) or None
        加收 = 每日["加權"].get(維.index[-1]) if "加權" in 每日 else None   # 用跟維持率同一天的收盤
        加收 = None if 加收 is None or pd.isna(加收) else float(加收)
        點們 = engine.維持率警戒點位(維.iloc[-1], 加收, 官方) if 加收 else []
        if 點們:
            線, 點, 跌 = 點們[0]
            其他 = "、".join(f"{a}% 約 {b:,.0f}" for a, b, _ in 點們[1:])
            卡們.append(卡片(f"維持率到 {線}% 加權約", f"{點:,.0f}",
                           f"還要跌 {abs(跌):.1f}%" + (f"；{其他}" if 其他 else "")
                           + ("（用官方值 " + f"{官方:.2f}%）" if 官方 else "（用網站估算）"),
                           綠 if 跌 > -5 else "#EDEDED"))
    if "外資期貨" in 每日 and 每日["外資期貨"].notna().any():
        期 = 每日["外資期貨"].dropna()
        差 = 期.iloc[-1] - 期.iloc[-2] if len(期) >= 2 else np.nan
        卡們.append(卡片(f"外資台指期淨未平倉 · {期.index[-1]:%m/%d}", f"{期.iloc[-1]:+,.0f} 口",
                       "" if pd.isna(差) else f"較前一日 {差:+,.0f} 口", 漲跌色(期.iloc[-1])))
    當沖 = 讀檔("讀取當沖大盤", _版本)
    if 當沖 is not None and "上市" in 當沖 and 當沖["上市"].notna().any():
        沖 = 當沖["上市"].dropna()
        卡們.append(卡片(f"上市當沖比重 · {沖.index[-1]:%m/%d}", f"{沖.iloc[-1]:.1f}%",
                       f"近 20 日平均 {沖.tail(20).mean():.1f}%" + (f"；上櫃 {當沖['上櫃'].dropna().iloc[-1]:.1f}%"
                                                                 if "上櫃" in 當沖 and 當沖["上櫃"].notna().any() else ""),
                       "#FFC24B" if 沖.iloc[-1] >= 30 else "#EDEDED"))
    洗 = engine.讀取大盤融資洗盤()
    if "融資變化%" in 每日 and 每日["融資變化%"].notna().any():
        變 = 每日["融資變化%"].dropna()
        統 = {r["天數"]: r for r in (洗 or {}).get("洗盤", {}).get("統計", [])}
        r20 = 統.get(20)
        是 = 變.iloc[-1] <= -1.5
        說 = (f"🧹 融資洗盤日（≤ −1.5%）" if 是 else f"洗盤門檻 −1.5%；近 20 日最大減 {變.tail(20).min():+.1f}%")
        if r20 and r20.get("次數"):
            說 += f"；過去 {r20['次數']} 次 20 日後上漲 {r20['上漲機率%']}%（平均 {r20['平均%']:+.1f}%，一般日子 {r20['基準平均%']:+.1f}%）"
        卡們.append(卡片(f"大盤融資單日增減 · {變.index[-1]:%m/%d}", f"{變.iloc[-1]:+.2f}%", 說,
                       綠 if 是 else 漲跌色(變.iloc[-1])))
    比 = 融資減幅比(_版本)
    if 比 is not None and len(比) and pd.notna(比["指數跌幅"].iloc[-1]):
        燈, 話 = engine.融資減幅燈(比.iloc[-1])
        卡們.append(卡片(f"融資減幅 ÷ 指數跌幅 · {比.index[-1]:%m/%d}",
                       "—" if pd.isna(比["比例"].iloc[-1]) else f"{比['比例'].iloc[-1]:.0%}",
                       f"{燈} {話}；從 {比['高點日'].iloc[-1]:%m/%d} 高點起算", 綠 if 燈 == "🟢" else ("#FFC24B" if 燈 == "🟡" else 紅)))
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
            "這裡是自己估算的（只算上市、用收盤市值），跟券商或財經網站公布的數字可能差 1～2%；"
            "有些網紅或媒體講的「大盤融資維持率」用的是別的算法（例如含上櫃、或只算某些券商客戶），可能差到 10% 以上。"
            "不同來源不要直接比高低，看同一個來源的變化方向比較準。")
        st.number_input("官方公布的整戶維持率（選填，例如 173.46）：填了「到警戒線加權約幾點」就用官方值當基準",
                        min_value=0.0, max_value=400.0, step=0.01, key="官方維持率",
                        help="證交所／金管會或財經新聞公布的「整戶擔保維持率」。網站估算只算上市、用收盤市值，跟官方會差幾個百分點。")
        st.caption("「到警戒線加權約幾點」假設融資股跟著大盤同比例跌；融資股通常跌得比大盤重，實際會更早碰到。"
                   "165% 是網紅常說的警戒區，130% 是券商追繳線。")
    融資洗盤區(洗)
    融資減幅比區(洗)
    恐慌日區(洗)
    正2融資區(每日, 洗)
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


@st.cache_data(ttl=3600, show_spinner=False)
def 正2融資資料(版本鍵):
    return engine.正2融資明細(engine.讀取資料庫(代號=list(engine.台股正2)))


def 正2融資區(每日, 洗):
    """槓桿 ETF 融資追蹤（建議 1）、正2 融資維持率估算（建議 2）、「大盤洗融資、正2 加碼」背離回測（建議 4）。"""
    天, 檔們 = 正2融資資料(_版本)
    if 天 is None or not len(天) or not 檔們:
        return
    st.markdown("**🎢 正2 融資追蹤：散戶用融資買槓桿 ETF 有多少？**")
    最 = 天.iloc[-1]
    金額 = engine.讀取融資金額()
    佔 = None
    if 金額 is not None and 天.index[-1] in 金額.index and 金額.loc[天.index[-1]] > 0:
        佔 = 最["估借款億"] / (金額.loc[天.index[-1]] * 1000 / 1e8) * 100
    最長 = max(檔們, key=lambda r: r["連增天數"])
    卡們 = [卡片(f"4 檔台股正2 融資市值 · {天.index[-1]:%m/%d}", f"{最['融資市值億']:,.0f} 億",
                 f"單日 {最['單日增減億']:+.1f} 億；估借款 {最['估借款億']:,.0f} 億"
                 + (f"，只佔上市融資金額 {佔:.1f}%" if 佔 is not None else ""), "#EDEDED"),
            卡片(f"{最長['代號']} 融資連增", f"{最長['連增天數']} 天",
                 f"今天 {最長['單日增減張'] or 0:+,} 張（約 {(最長['單日增減張'] or 0) * 最長['收盤'] / 1e5:+.1f} 億元）",
                 "#FFB020" if 最長["連增天數"] >= 10 else "#EDEDED")]
    維 = 最["估維持率"]
    差 = 維 - 天["估維持率"].iloc[-2] if len(天) >= 2 else np.nan
    if 維 >= 130:
        小 = f"大盤再跌約 {(1 - 130 / 維) * 50:.1f}% 平均就到 130% 追繳線"
    else:
        小 = "平均已低於 130% 追繳線，高檔買的多半已被追繳"
    卡們.append(卡片("正2 融資估維持率（4 檔合計）", f"{維:.0f}%",
                   ("" if pd.isna(差) else f"較前一日 {差:+.1f}　") + 小, 維持率等級(維)[1]))
    背 = engine.今日正2背離(每日["融資變化%"].dropna() if "融資變化%" in 每日 else None, 天)
    回 = (洗 or {}).get("正2背離") or {}
    統 = {r["天數"]: r for r in 回.get("統計", [])}
    if 背:
        是, 大, 正 = 背
        r60 = 統.get(60)
        卡們.append(卡片("大盤洗融資、正2 加碼？", "🔪 背離" if 是 else "—",
                       f"大盤融資 {大:+.2f}%、正2 融資 {正:+.2f}%"
                       + (f"；過去 {r60['次數']} 次 60 日後平均 {r60['平均%']:+.1f}%（一般日子 {r60['基準平均%']:+.1f}%）"
                          if r60 and r60.get("次數") else ""), "#FFB020" if 是 else "#EDEDED"))
    卡片格(卡們)
    with st.expander("📋 正2 融資明細與「接刀」回測"):
        表格(pd.DataFrame([{"代號": r["代號"], "名稱": r["名稱"], "融資(張)": r["融資張數"], "單日增減(張)": r["單日增減張"],
                            "連增天數": r["連增天數"], "收盤": r["收盤"], "融資市值(億)": r["融資市值億"], "估成本": r["估成本"],
                            "估維持率%": r["估維持率"]} for r in 檔們]),
             hide_index=True, width="stretch",
             column_config={"收盤": st.column_config.NumberColumn(format="%.2f"),
                            "單日增減(張)": st.column_config.NumberColumn(format="%+d")})
        st.caption("張數看起來很大，是因為 00631L（2026-03-31 一拆 22）、00685L（2026-07-07 一拆 25）分割過，一張只值幾千到兩萬多元；"
                   "要看金額。融資自備四成 → 2.5 倍，再乘正2 的 2 倍＝買進當下約 5 倍曝險；大盤跌約 11%，正2 跌約 22%，"
                   "自備款虧掉一半多，維持率剛好到 130%。估成本：融資增加的張數用當天收盤計入，減少時成本不變，"
                   "可能高估維持率幾個百分點；追繳看的是整戶維持率，不是單一檔。")
        if 回.get("統計"):
            st.markdown(f"**大盤融資單日減 ≥ {abs(回['大盤門檻'])}%、正2 融資同日增 ≥ {回['正2門檻']:g}% 之後，加權怎麼走？**")
            表格(pd.DataFrame([{"天數": f"{r['天數']} 日後", "次數": r["次數"], "上漲機率%": r["上漲機率%"], "平均%": r["平均%"],
                                "一般日子上漲機率%": r["基準上漲機率%"], "一般日子平均%": r["基準平均%"]} for r in 回["統計"]]),
                 hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%+.2f") for c in ("平均%", "一般日子平均%")})
            事 = pd.DataFrame(回.get("事件", []))
            if len(事):
                表格(事.iloc[::-1].rename(columns={"date": "日期"}), hide_index=True, width="stretch")
            st.caption("常見說法：大盤融資斷頭、正2 融資卻逆勢大增，是散戶「接刀」、之後會再崩。"
                       f"資料 {洗.get('起')}～{洗.get('迄')}，同一段 14 天內只算第一次。2026-11 實測：這種背離不是少見的異象，"
                       "之後 20、60 日加權都不比一般日子差；但 2022 空頭年 6 次裡有 3 次 60 日後還在跌。只是參考，不是買賣訊號。")
        else:
            st.caption("背離回測還沒算好（GitHub Actions 每月重算時會補上）。")


@st.cache_data(ttl=3600, show_spinner=False)
def 融資減幅比(版本鍵):
    """近 110 天的融資減幅 ÷ 指數跌幅（每日融資變化用 市場每日 的「融資變化%」）。"""
    每 = 市場每日(版本鍵)
    if "融資變化%" not in 每 or not 每["融資變化%"].notna().any():
        return None
    K = 指數K線("TAIEX", 版本鍵)
    return engine.融資減幅比序列(每["融資變化%"].dropna(), K) if K is not None else None


@st.cache_data(ttl=3600, show_spinner=False)
def 止跌回測(代號, 版本鍵):
    return engine.止跌三階段回測(指數K線(代號, 版本鍵))


def 融資減幅比區(洗):
    """「大盤跌 10%，融資要減 7～8%」的 5 年回測（data/margin_flush.json 的「減幅比」，GitHub Actions 每月重算）。"""
    回 = (洗 or {}).get("減幅比")
    with st.expander("📉 融資減幅 ÷ 指數跌幅：融資跟上跌幅就是底？實測結果"):
        st.markdown("**常見說法**（鄭廳宜、吳嘉隆 2026-11）：大盤回檔 10%，融資餘額要減 7～8% 以上才算洗乾淨，是跌深反轉訊號。\n\n"
                    "**網站怎麼算**：加權距近 60 個交易日收盤高點的跌幅，對照同一段（高點前 5 天起算）融資的減幅；"
                    "融資用「張數 × 收盤」加權的每日增減累積，不受股價下跌影響（純粹看有沒有人還錢）。"
                    "加權跌超過 8%、而且融資減幅 ÷ 指數跌幅 ≥ 70% 亮綠燈。")
        if 回 and 回.get("統計"):
            表格(pd.DataFrame([{"天數": f"{r['天數']} 日後", "次數": r["次數"], "上漲機率%": r["上漲機率%"], "平均%": r["平均%"],
                                "一般日子上漲機率%": r["基準上漲機率%"], "一般日子平均%": r["基準平均%"]} for r in 回["統計"]]),
                 hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%+.2f") for c in ("平均%", "一般日子平均%")})
            事 = pd.DataFrame(回.get("事件", []))
            if len(事):
                表格(事.iloc[::-1].rename(columns={"date": "第一次亮綠燈"}), hide_index=True, width="stretch")
            st.caption(f"資料 {洗.get('起')}～{洗.get('迄')}，同一段 20 個交易日內只算第一次。"
                       "2026-11 實測：亮綠燈之後 20、60 日平均都輸給「任何一天買進」，2022 空頭時常常亮了還繼續跌，"
                       "所以這只能說明「融資已經在退場」，不能單獨當買進訊號。樣本只有十幾次，只是參考。")
        else:
            st.caption("回測還沒算好（GitHub Actions 每天更新資料時會補算）。")


def 融資洗盤區(洗):
    """大盤融資單日大減（融資洗盤日）的 5 年回測：data/margin_flush.json，GitHub Actions 約每月重算。"""
    if not 洗 or not 洗.get("洗盤"):
        return
    with st.expander("🧹 大盤融資洗盤日：融資單日大減之後，大盤通常怎麼走？"):
        列們 = []
        for 名, 鍵 in (("減 ≥ 1.5%", "洗盤"), ("減 ≥ 2.5%", "大洗盤")):
            for r in 洗.get(鍵, {}).get("統計", []):
                列們.append({"條件": 名, "天數": f"{r['天數']} 日後", "次數": r["次數"], "上漲機率%": r["上漲機率%"],
                            "平均%": r["平均%"], "一般日子上漲機率%": r["基準上漲機率%"], "一般日子平均%": r["基準平均%"]})
        表格(pd.DataFrame(列們), hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%+.2f") for c in ("平均%", "一般日子平均%")})
        事 = pd.DataFrame(洗["洗盤"].get("事件", []))
        if len(事):
            表格(事.iloc[::-1].rename(columns={"date": "日期", "融資%": "融資單日%"}), hide_index=True, width="stretch")
        st.caption(f"融資單日增減＝每檔「融資張數變化 × 當天收盤」加總 ÷ 前一天融資市值（上市櫃普通股，不受股價漲跌影響）。"
                   f"資料 {洗.get('起')}～{洗.get('迄')}，最大單日減 {洗.get('最大單日減%')}%；同一段 14 天內只算第一次。"
                   "網紅常說「融資單日大減 200 億以上才是洗盤」，但 5 年內只有 2 天達到，所以改用百分比。"
                   "這 5 年大多是多頭，結果偏樂觀，只是參考。")


def 恐慌日區(洗):
    """大盤恐慌日（跌超過 2%、收在最低點附近）＋融資有沒有洗出來：data/margin_flush.json 的「恐慌日」。"""
    K = 指數K線("TAIEX", _版本)
    if K is None or len(K) < 2 or "low" not in K:
        return
    今 = engine.恐慌日判斷(K).iloc[-1]
    恐 = (洗 or {}).get("恐慌日")
    標題 = "😱 大盤恐慌日：一路殺到底、沒有下影線之後，大盤怎麼走？"
    if bool(今["恐慌日"]):
        標題 = f"😱 今天是恐慌日（加權 {今['漲跌%']:+.2f}%、下影線只有 {今['下影線%']:.2f}%）：之後大盤怎麼走？"
    with st.expander(標題, expanded=bool(今["恐慌日"])):
        st.markdown(f"今天加權 {今['漲跌%']:+.2f}%，下影線 {今['下影線%']:.2f}%（收盤離當天最低點多遠）。"
                    + ("**符合恐慌日**：跌超過 2%，而且收在最低點附近。接下來看今晚和明晚的融資有沒有一起大減。"
                       if bool(今["恐慌日"]) else "不是恐慌日（恐慌日＝跌超過 2%、下影線 0.3% 以內）。"))
        if not 恐:
            st.caption("回測資料還沒算好（GitHub Actions 每天更新時會補上）。")
            return
        列們 = []
        for 名, 鍵 in (("全部恐慌日", "全部"), ("融資兩日減 ≥ 1.5%", "融資有洗"), ("融資沒洗", "融資沒洗")):
            for r, b in zip(恐.get(鍵, []), 恐.get("基準", [])):
                列們.append({"情況": 名, "天數": f"{r['天數']} 日後", "次數": r["次數"], "上漲機率%": r["上漲機率%"],
                           "平均%": r["平均%"], "一般日子上漲機率%": b["上漲機率%"], "一般日子平均%": b["平均%"]})
        表格(pd.DataFrame(列們), hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%+.2f") for c in ("平均%", "一般日子平均%")})
        事 = pd.DataFrame(恐.get("事件", []))
        if len(事):
            表格(事.iloc[::-1].rename(columns={"date": "日期", "漲跌%": "當天漲跌%", "融資兩日%": "當天＋隔天融資%"}),
                 hide_index=True, width="stretch")
        st.caption("通勤族 11/03 的看法：前幾天開低會拉出下影線，真正恐慌是一路殺到底、幾乎沒有下影線；"
                   "恐慌之後融資也大減（洗出來），才開始觀察止跌。融資要隔天晚上才知道，所以報酬從恐慌日「隔天收盤」算起。"
                   "同一段 10 天內只算第一次；樣本少，只是參考。")


def 跌深區():
    段落("DIP // 0050 跌深榜：今年高點到現在跌最多的權值股")
    t, 來源 = engine.跌深榜(今日)
    if t.empty or "距今年高點" not in t.columns:
        st.caption("還沒有足夠的資料。")
        return
    前五 = t.head(5)
    卡片格([卡片(f"{r['代號']} {r['名稱']}", f"{r['距今年高點']:+.1f}%",
                 (f"維持率約 {r['融資維持率']:.0f}%　" if pd.notna(r.get("融資維持率")) else "") + (r["訊號"] or ""),
                 綠, 連結=股連結(r["代號"])) for _, r in 前五.iterrows()])
    欄 = [c for c in ["代號", "名稱", "產業", "收盤", "距今年高點", "距52週高點", "融資維持率", "融資20日增減", "訊號",
                     "本益比", "營收年增率", "市值億"] if c in t.columns]
    表 = t[欄].reset_index(drop=True)
    點選表(表, 表.style.format({"收盤": "{:,.2f}", "距今年高點": "{:+.1f}", "距52週高點": "{:+.1f}", "融資維持率": "{:.0f}",
                              "融資20日增減": "{:+.1f}", "本益比": "{:.1f}", "營收年增率": "{:+.1f}", "市值億": "{:,.0f}"},
                             na_rep="—"), key="跌深榜", height=min(35 * (len(表) + 1) + 3, 520),
          column_config={"距今年高點": st.column_config.NumberColumn("距今年高點%"),
                         "距52週高點": st.column_config.NumberColumn("距 52 週高點%"),
                         "融資維持率": st.column_config.NumberColumn("融資維持率%（估）"),
                         "融資20日增減": st.column_config.NumberColumn("融資 20 日%")})
    st.caption(f"成分股來源：{來源}。跌幅用還原價（扣除除權息、面額分割）。點一列看個股。")
    實 = 讀檔("讀取規則實測", _版本)
    句 = engine.規則實測句(實, ["跌深", "跌深低維持", "跌深已追繳", "跌深融資洗完", "跌深融資增加"])
    with st.expander("ℹ️ 跌深＋融資維持率低＝反彈首選？實測結果"):
        st.markdown(
            "**常見說法**：0050 成分股跌最深的前 5 名、融資維持率 140% 附近越低越好，加上產業龍頭，是反彈首選。\n\n"
            "**2022-11～2026-10 回測**：\n"
            "- 每週挑 0050 成分股跌最深 5 檔，持有 120 日平均 **輸 0050 約 9.6 個百分點**；再加「維持率 < 150%」輸更多（約 16.5）\n"
            "- 維持率 140% 代表融資還沒洗掉，再跌約 7% 就碰 130% 追繳線，常還有斷頭賣壓\n"
            "- 比較有用的是 **🧹 融資洗完**：距 52 週高點跌超過 30%，而且融資 20 日減少超過 15% 或維持率曾跌破 130%，"
            "比單純跌深好（成交值 2 億以上的股票，之後 60 日中位數比大家多約 2%；全部股票用平均數算仍略輸），"
            "但都不如距高點不到 10% 的強勢股\n"
            "- **🔪 接刀風險**：跌深但融資 20 日還增加 15% 以上，最差\n"
            "- 08 回測頁組合回測（2023-01～2026-09，每月挑成交值最大 10 檔「融資洗完」股、停損不設）：總報酬約 −1%，"
            "同期 0050 +307%。**只適合當觀察名單，不適合當主要策略**\n\n"
            "**個股融資維持率是估算的**：用每天融資餘額變化推平均成本，上市 ÷ 60%、上櫃 ÷ 50%；"
            "跟大盤實際值比對可能偏高 2～15 個百分點，看級距就好。"
            + ("\n\n**最新實測（每月自動更新）**：\n" + "\n".join(f"- {x}" for x in 句) if 句 else ""))
    籌碼不安定區()


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
    燈列 = []
    for 欄, 名 in (("外資期貨", "外資"), ("投信期貨", "投信"), ("自營期貨", "自營商")):
        x = 每日.get(欄, pd.Series(dtype=float)).dropna()
        if len(x) < 2:
            continue
        變 = x.diff().dropna()
        連 = 0
        for v in 變[::-1]:
            if v == 0 or (連 and np.sign(v) != np.sign(連)):
                break
            連 += int(np.sign(v))
        燈列.append({"法人": 名, "淨未平倉(口)": x.iloc[-1], "較前日(口)": 變.iloc[-1], "近 5 日(口)": x.iloc[-1] - x.iloc[max(-6, -len(x))],
                     "連續": f"{'加多' if 連 > 0 else '加空'} {abs(連)} 天" if 連 else "—",
                     "燈號": "🔴 偏多加碼" if 變.iloc[-1] > 0 and x.iloc[-1] > 0 else "🟢 偏空加碼" if 變.iloc[-1] < 0 and x.iloc[-1] < 0
                     else "🟡 空單回補" if 變.iloc[-1] > 0 else "🟡 多單減碼" if 變.iloc[-1] < 0 else "⚪ 持平"})
    if 燈列:
        表格(pd.DataFrame(燈列), hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%+d") for c in ("淨未平倉(口)", "較前日(口)", "近 5 日(口)")})
    對 = engine.期貨多空對手(讀檔("讀取期貨未平倉", _版本))
    if 對:
        卡片格([卡片(f"外資淨空 ÷ 投信淨多 · {對['日期']:%m/%d}", f"{對['最新']:.2f} 倍",
                     f"{對['燈']} {對['說明']}；外資 {對['外資']:+,} 口、投信 {對['投信']:+,} 口；平常 {對['低']}～{對['高']} 倍（中位 {對['中位']}）",
                     "#FFB020" if 對["燈"] == "🟡" else "#EDEDED")])
        with st.expander("🤝 期貨多空對手方：外資空單創新高，是外資在大舉作空嗎？"):
            s = 對["序列"]
            圖 = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                               subplot_titles=("外資淨空單 vs 投信淨多單（口）", "外資淨空 ÷ 投信淨多（倍）"))
            期 = 讀檔("讀取期貨未平倉", _版本).reindex(s.index)
            圖.add_trace(go.Scatter(x=s.index, y=-期["foreign_oi"], mode="lines", line=dict(color="#4DA3FF", width=2), name="外資淨空"), 1, 1)
            圖.add_trace(go.Scatter(x=s.index, y=期["trust_oi"], mode="lines", line=dict(color="#FF00E5", width=2), name="投信淨多"), 1, 1)
            圖.add_trace(go.Scatter(x=s.index, y=s, mode="lines", line=dict(color="#FFB020", width=2), name="比值"), 2, 1)
            圖.add_hline(y=對["中位"], line=dict(color=灰, dash="dot"), row=2, col=1)
            圖.update_annotations(font=dict(size=11, color=灰), x=0, xanchor="left")
            圖表外觀(圖, 420).update_layout(legend=dict(orientation="h", y=-0.1, x=0))
            st.plotly_chart(圖, width="stretch")
            st.caption("期貨是零和：有人做多就有人做空。投信的台指期多單主要是正2 ETF 的期貨部位，一年多從 2 萬口長到 9 萬口，"
                       "外資空單跟著同步變大（一部分是對手方、一部分是替手上台股現貨避險）。所以「外資空單歷史新高」在正2 變大以後會一直出現，"
                       "比較有用的是看比值：比值高於平常（黃燈）才代表外資空得比正2 對手方更多。每天的增減兩者並不同步，外資仍有自己的方向。")
    夜 = 夜盤法人資料(_版本)
    if 夜 is not None and len(夜):
        最 = 夜["date"].max()
        近 = 夜[夜["date"] == 最]
        名 = {"TX": "台指期", "MTX": "小台", "TMF": "微台"}
        身 = {"foreign": "外資", "trust": "投信", "dealer": "自營商"}
        夜表 = 近.assign(商品=近["product"].map(名), 法人=近["who"].map(身)).pivot_table(
            index="法人", columns="商品", values="net", aggfunc="sum").reindex(columns=[v for v in 名.values() if v in 近["product"].map(名).values])
        st.markdown(f"**🌙 夜盤法人交易口數**（歸屬 {最:%m/%d} 的夜盤，多空淨額，口）")
        表格(夜表.reset_index(), hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%+d") for c in 夜表.columns})
        外 = 近[(近["product"] == "TX") & (近["who"] == "foreign")]
        if len(外) and len(燈列):
            未 = next((x["淨未平倉(口)"] for x in 燈列 if x["法人"] == "外資"), None)
            if 未 is not None:
                st.caption(f"對照：外資夜盤台指期淨{'買' if 外['net'].iloc[0] >= 0 else '賣'} {abs(外['net'].iloc[0]):,} 口，"
                           f"但日盤收盤後的淨未平倉是 {未:+,.0f} 口——夜盤的一兩千口只是當晚的動作，方向要看未平倉。")
    價差區()
    with st.expander("🧮 期貨部位試算（大台／小台／微台：保證金、槓桿、追繳點位）"):
        期貨試算區()
    st.caption("投信台指期多半是替 ETF 避險或加碼的多單，主要看外資的方向；合計＝三者相加。"
               "「未平倉」是收盤後還留著的多空部位（口數），跟新聞常說的「成交量／交易口數」不同：交易口數是當天買賣了多少口，"
               "隔天就歸零；未平倉才代表法人押的方向。夜盤（15:00～隔天 05:00）的交易算在下一個交易日；期交所只公布夜盤的法人"
               "「交易口數」（上表），不公布夜盤單獨的未平倉，所以網路上說的「夜盤未平倉」其實多半是交易口數。"
               "資料來源：證交所、櫃買中心、期交所。")


@st.cache_data(ttl=3600, show_spinner=False)
def 指數成交值(代號, 版本鍵):
    """加權＝上市、櫃買＝上櫃每天的成交金額（億），算分價量和量價關係用。"""
    t = 指標[指標["市場"] == ("上市" if 代號 == "TAIEX" else "上櫃")]
    return t.groupby("date")["成交值億"].sum()


@st.cache_data(ttl=3600, show_spinner=False)
def 價位分析(代號, 版本鍵):
    K = 指數K線(代號, 版本鍵)
    if K is None or len(K) < 60:
        return None
    量 = 指數成交值(代號, 版本鍵)
    sr = engine.支撐壓力(K, 量=量)
    區們 = engine.共振區(sr["價位"])
    return K, sr, 區們, engine.位置解讀(sr, 區們), engine.黑K一半(K), engine.量價標籤(K, 量)


@st.cache_data(ttl=3600, show_spinner="回測 5 年支撐壓力中…")
def 價位回測(代號, 版本鍵):
    K = 指數K線(代號, 版本鍵)
    if K is None or len(K) <= 300:
        return pd.DataFrame()
    return engine.回測摘要(engine.支撐壓力回測(K, 指數成交值(代號, 版本鍵)))


@st.cache_data(ttl=3600, show_spinner=False)
def 指數跌破站回(代號, 版本鍵):
    K = 指數K線(代號, 版本鍵)
    if K is None:
        return []
    量 = 指數成交值(代號, 版本鍵)
    return engine.跌破站回(K, 量) + engine.技術訊號(K, 量)


@st.cache_data(ttl=3600, show_spinner=False)
def 指數技術觀察(代號, 版本鍵):
    K = 指數K線(代號, 版本鍵)
    return engine.技術觀察(K, 指數成交值(代號, 版本鍵)) if K is not None else []


@st.cache_data(ttl=3600, show_spinner=False)
def 守週線強勢(版本鍵):
    return engine.守週線強勢股(指標)


def 波段區(K, sr):
    """回檔尺（0.382／0.5／0.618）、等幅測距、底背離與劇本條件樹。"""
    尺 = macro.回檔尺(K)
    背 = macro.低檔背離(K) or []
    價 = sr["價位"]
    樹 = macro.劇本樹(float(K["close"].iloc[-1]), list(zip(價.loc[價["角色"] == "支撐", "名稱"], 價.loc[價["角色"] == "支撐", "價位"])),
                    list(zip(價.loc[價["角色"] == "壓力", "名稱"], 價.loc[價["角色"] == "壓力", "價位"])))
    if 尺:
        (起日, 起價, _), (止日, 止價, _) = 尺["起"], 尺["止"]
        話 = (f"📏 <b>回檔尺</b>：{起日:%m/%d} {起價:,.0f} → {止日:%m/%d} {止價:,.0f}（{尺['方向']}），目前已回 {尺['已回%']:.0f}%；"
              + "、".join(f"{k} 在 {v:,.0f}" for k, v in 尺["回檔"].items()))
        等 = 尺.get("等幅")
        if 等:
            話 += (f"<br>📐 <b>等幅測距</b>：A {等['A'][1]:,.0f}（{等['A'][0]:%m/%d}）→ B {等['B'][1]:,.0f}（{等['B'][0]:%m/%d}）→ "
                   f"C {等['C'][1]:,.0f}（{等['C'][0]:%m/%d}），第二段{等['型態']}跟第一段一樣大的話目標約 "
                   f"{等['點數目標']:,.0f}（點數）／{等['百分比目標']:,.0f}（百分比）" + ("，<b>已達成</b>" if 等["已達成"] else ""))
        st.markdown(f'<div class="verdict">{話}</div>', unsafe_allow_html=True)
    for b in 背:
        (st.success if b["型態"] == "底背離" else st.warning)(
            f"{'🟢' if b['型態'] == '底背離' else '🟠'} {b['型態']}：{b['前低'][0]:%m/%d} {b['前低'][1]:,.0f}（RSI {b['前低'][2]:.0f}）→ "
            f"{b['後低'][0]:%m/%d} {b['後低'][1]:,.0f}（RSI {b['後低'][2]:.0f}）。{b['說明']}")
    if 樹:
        a, b = st.columns(2)
        a.markdown("**🌳 劇本：偏多**\n" + "\n".join(f"- {x}" for x in 樹["偏多"]))
        b.markdown("**🌳 劇本：偏空**\n" + "\n".join(f"- {x}" for x in 樹["偏空"]))
        st.caption(f"關鍵價位是最近的支撐 {樹['關鍵'][0]} {樹['關鍵'][1]:,.0f}；條件成立才換劇本，不預測哪一天會到。"
                   "回檔尺用 5% 以上的波段；等幅測距是「第二段跟第一段一樣長」的經驗法則，不一定會到。")


@st.cache_data(ttl=3600, show_spinner=False)
def 季節資料(代號, 版本鍵):
    return engine.季節統計(指數K線(代號, 版本鍵))


def 季節區(K, 名稱):
    """年底做帳行情：每年 11 月底 → 隔年 2/5 的漲跌、12 月漲跌，跟任意同樣長度的期間比。"""
    表, 基, 今 = 季節資料("TAIEX" if 名稱 == "加權指數" else "TPEX", _版本)
    if 表.empty or not 基:
        return
    標 = (f"🗓️ 年底做帳行情：過去 {基['區間次數']} 年 11 月底→2/5 上漲 {基['區間上漲次數']} 次、平均 {基['區間平均%']:+.1f}%"
         f"（任意 {基['天數']} 個交易日平均 {基['平均%']:+.1f}%、上漲 {基['上漲%']}%）")
    with st.expander(標):
        if 今:
            if 今.get("還沒開始"):
                st.caption(f"今年的區間還沒開始（{今['距開始天數']} 天後，11 月底起算）。")
            else:
                st.caption(f"今年（{今['年度']}）進行中：從 11 月底 {今['起點']:,.2f} 起至今 {今['區間%']:+.1f}%，期間最大回檔 {今['最大回檔%']:+.1f}%。")
        表格(表.drop(columns="完整").sort_values("年度", ascending=False), hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in ("區間%", "12月%", "最大回檔%")})
        st.caption("市場常說「選後做帳行情到農曆年前」（今年九合一選舉 11/28）。過去 5 年加權每年都漲，但任意同長度期間也有 7 成會漲，"
                   "優勢只有 1～2 個百分點；「12 月會有喘息」在 5 年裡只有 2022 成立，不過每年這段期間都有 4% 左右的回檔。"
                   "只有 5 年、而且多半是多頭年，只是參考。")


def 預估估值區(K):
    """大盤預估本益比（共識 EPS）＋下修情境＋目標點位換算；台股半導體相對大盤本益比。"""
    估 = engine.大盤預估本益比(今日)
    本 = 大盤本益比資料(_版本)
    現 = float(K["close"].iloc[-1])
    卡們 = []
    if 估 and "明年" in 估:
        明 = 估["明年"]
        卡們.append(卡片("上市預估本益比（明年共識 EPS）", f"{明['本益比']:.1f} 倍",
                       f"不含台積電 {明['不含龍頭']:.1f}；今年 EPS 算 {估.get('今年', {}).get('本益比', np.nan):.1f} 倍", 青))
        最差 = 明["情境"][-1]
        卡們.append(卡片("如果明年 EPS 全部下修 20%", f"{最差['大盤預估本益比']:.1f} 倍",
                       f"台積電佔上市市值 {估['龍頭權重%']:.0f}%，它下修大盤就跟著變貴", "#FFC24B"))
    if len(本) and "半導體相對" in 本.columns and 本["半導體相對"].notna().sum() >= 12:
        近 = 本.dropna(subset=["半導體相對"])
        v = float(近["半導體相對"].iloc[-1])
        卡們.append(卡片("台股半導體本益比 ÷ 大盤", f"{v:.2f} 倍",
                       f"5 年平均 {近['半導體相對'].mean():.2f}、最低 {近['半導體相對'].min():.2f}；不含台積電 {近['不含台積電相對'].iloc[-1]:.2f}",
                       "#7EE2A8" if v <= 近["半導體相對"].quantile(0.2) else "#EDEDED"))
    if not 卡們:
        return
    卡片格(卡們)
    with st.expander("🧮 預估本益比情境、目標點位換算、半導體相對本益比"):
        if 估 and "明年" in 估:
            列 = []
            for 名 in ("今年", "明年"):
                if 名 in 估:
                    x = 估[名]
                    列.append({"口徑": f"{名}共識 EPS", "大盤": round(x["本益比"], 2), "不含台積電": round(x["不含龍頭"], 2),
                              "台積電": round(x["龍頭本益比"], 2), "涵蓋市值%": x["涵蓋%"]})
            表格(pd.DataFrame(列), hide_index=True, width="stretch")
            表格(pd.DataFrame(估["明年"]["情境"]), hide_index=True, width="stretch")
            a, b = st.columns(2)
            目標 = a.number_input("目標點位", min_value=1000, value=int(round(現 * 1.2, -3)), step=1000, key="目標點位")
            pe = engine.點位本益比換算(現, 估["明年"]["本益比"], 目標點位=目標)
            a.caption(f"加權 {現:,.0f} → {目標:,.0f}，明年共識 EPS 不變的話，預估本益比要從 {估['明年']['本益比']:.1f} 倍變成 **{pe:.1f} 倍**。")
            倍 = b.number_input("目標預估本益比", min_value=5.0, value=12.0, step=0.5, key="目標本益比")
            點 = engine.點位本益比換算(現, 估["明年"]["本益比"], 目標本益比=倍)
            b.caption(f"明年共識 EPS 不變，{倍:.1f} 倍對應加權約 **{點:,.0f}**。")
            st.caption("預估 EPS＝網站預估 EPS 檔裡 A、B 兩個法人常用來源的中位數（04「📐 預估 EPS」可上傳新的）；"
                       "大盤預估本益比＝上市股票（不含 ETF、只算預估 EPS > 0 的）總市值 ÷ 總預估獲利。"
                       "「便宜」是建立在明年 EPS 不下修上：明年共識比今年再成長約 3 成，若景氣放緩被下修，倍數會一起變高。")
        if len(本) and "半導體相對" in 本.columns:
            近 = 本.dropna(subset=["半導體相對"])
            圖 = go.Figure([go.Scatter(x=近["date"], y=近["半導體相對"], name="半導體 ÷ 大盤", line=dict(color=青, width=2)),
                           go.Scatter(x=近["date"], y=近["不含台積電相對"], name="不含台積電", line=dict(color="#FFB020", width=1.5, dash="dot"))])
            圖.add_hline(y=1, line_dash="dot", line_color="#666")
            st.plotly_chart(圖表外觀(圖, 260), width="stretch", config={"displayModeBar": False})
            st.caption("用證交所個股本益比（近四季獲利）算：高於 1＝半導體比大盤貴。美股有研究指出費半相對 S&P 500 的預估本益比"
                       "跌到 0.75 倍、2018 年來最低；台股半導體目前沒有出現同樣的折價。")


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
        項們, 總結 = engine.三條件燈號(指數K線("TAIEX", _版本), 指數K線("TPEX", _版本), 讀檔("讀取美股", _版本))
    except Exception:
        項們, 總結 = [], ""
    if 項們:
        st.markdown(f"**本週觀察三條件**：{總結}")
        st.markdown(燈號卡(項們), unsafe_allow_html=True)
    if 黑:
        st.markdown(黑K卡(黑), unsafe_allow_html=True)
    波段區(K, sr)
    年線反彈區(K, 是大盤=True)
    季節區(K, 選)
    K棒解讀區(K, None, f"{'加權' if 代號 == 'TAIEX' else '櫃買'}今天的 K 棒怎麼看", 是大盤=True)
    技術 = 指數技術觀察(代號, _版本)
    if 技術:
        st.markdown("**分析師常用條件**：週線、KD、扣抵值、爆量 K 棒")
        st.markdown(燈號卡(技術), unsafe_allow_html=True)
    止 = engine.止跌三階段(K)
    if 止:
        st.markdown(f"**止跌三階段**（通勤族）：目前到第 {止['已到']} 階段" + ("，三個都成立 ✅" if 止["已到"] == 3 else ""))
        st.markdown(燈號卡(止["階段們"]), unsafe_allow_html=True)
        回 = 止跌回測(代號, _版本)
        if 回 and 回.get("統計"):
            統 = {r["天數"]: r for r in 回["統計"]}
            st.caption(f"過去 5 年加權跌超過 {abs(回['跌深']):.0f}% 之後、三階段第一次全部成立共 {回['次數']} 次：" +
                       "；".join(f"{n} 日後上漲 {統[n]['上漲機率%']}%（平均 {統[n]['平均%']:+.1f}%，一般日子 {統[n]['基準平均%']:+.1f}%）"
                                for n in (5, 20, 60) if n in 統 and 統[n]["次數"]) +
                       "。只有 5 日明顯比一般日子好，20、60 日的上漲機率反而比一般日子低，2022 空頭時常常止跌後又破底。"
                       "阿信也說前兩階段就會小量試單，不是一次買滿。")
    if 代號 == "TAIEX":
        殺估值區()
        光通訊區()
        估值週線區(K)
        預估估值區(K)
    天數 = st.segmented_control("圖表區間", [20, 60, 120, 250], default=120,
                              format_func=lambda d: {20: "1 個月", 60: "3 個月", 120: "半年", 250: "1 年"}[d],
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
def 大盤本益比資料(版本鍵):
    return engine.大盤本益比(天數=60)


def 估值週線區(K):
    """大盤本益比在 5 年的哪裡＋週線連跌、離 5 週線很遠之後，過去通常怎麼走。"""
    本 = 大盤本益比資料(_版本)
    目, 歷, 彙 = engine.週線連跌統計(K)
    卡們 = []
    if len(本) >= 12:
        近 = 本[本["date"] >= 本["date"].max() - pd.Timedelta(days=365 * 5)]["本益比"]
        v = 本["本益比"].iloc[-1]
        位 = (近 < v).mean() * 100
        卡們.append(卡片(f"上市本益比 · {本['date'].iloc[-1]:%m/%d}", f"{v:.1f} 倍",
                       f"5 年區間 {近.min():.1f}～{近.max():.1f}，比 {位:.0f}% 的時候貴", "#FF8A8A" if 位 >= 80 else ("#7EE2A8" if 位 <= 20 else "#EDEDED")))
    卡們.append(卡片("加權週線", f"連跌 {目['連跌週數']} 週", f"週收盤比 5 週線 {目['乖離%']:+.1f}%",
                   "#7EE2A8" if 目["乖離%"] <= -5 else "#EDEDED"))
    if len(彙):
        r = 彙.iloc[0]
        卡們.append(卡片("過去連跌 3 週＋乖離 −5% 後", f"1 週後上漲機率 {r['上漲機率%']:.0f}%",
                       f"{r['次數']} 次，平均 {r['平均%']:+.1f}%", "#EDEDED"))
    月目, 月歷, 月彙 = engine.月線連跌統計(K)
    本月 = (f"本月至今 {月目['本月%']:+.1f}%（還沒收完）" if not 月目["本月完整"] else f"本月 {月目['本月%']:+.1f}%")
    卡們.append(卡片("加權月 K", f"今年 {月目['今年跌月數']}/{月目['今年月數']} 個月收跌",
                   f"已連跌 {月目['連跌月數']} 個月、今年最長連跌 {月目['今年最長連跌']} 個月；{本月}",
                   綠 if 月目["連跌月數"] >= 2 else "#EDEDED"))
    if 月彙:
        卡們.append(卡片("前兩月漲、這月跌之後", f"下月上漲 {月彙['上漲次數']}/{月彙['次數']} 次",
                       f"平均 {月彙['平均%']:+.1f}%、最差 {月彙['最差%']:+.1f}%；5 年連跌兩個月 {月目['連跌兩月次數']} 次",
                       "#EDEDED"))
    卡片格(卡們)
    with st.expander("📈 大盤本益比走勢、週線與月 K 連跌統計"):
        if len(本) >= 12:
            圖 = go.Figure(go.Scatter(x=本["date"], y=本["本益比"], line=dict(color=青, width=2), name="本益比"))
            圖.add_hline(y=float(本["本益比"].median()), line_dash="dot", line_color="#888", annotation_text="中位數")
            圖.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
            st.plotly_chart(圖, width="stretch", config={"displayModeBar": False})
            st.caption("本益比＝上市股票總市值 ÷ 總獲利（近四季，虧損股不算）。網站自己用證交所個股本益比和股數估算，"
                       "每月取月底一天；跟財經媒體講的「預估本益比」（用明年獲利算，通常比較低）不同。")
        if len(彙):
            表格(彙, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in ("平均%", "最差%", "最好%")})
            表格(歷.sort_values("週", ascending=False).assign(週=lambda d: d["週"].dt.strftime("%Y/%m/%d")), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in 歷.columns if c.endswith("%")})
        st.caption("條件：週 K 連跌 3 週以上，而且週收盤比 5 週線低 5% 以上（負乖離），同一段只算第一次。"
                   "網紅常說「負乖離大有機會反彈」，這裡用過去 5 年的加權指數檢查；樣本少，只是參考。")
        if len(月歷):
            st.markdown("**月 K：前兩個月漲、這個月跌之後，下個月怎麼走**")
            表格(月歷.sort_values("月份", ascending=False).assign(月份=lambda d: d["月份"].dt.strftime("%Y/%m")),
                 hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in ("前兩月%", "當月%", "下月%")})
            st.caption("網紅常說「月 K 今年沒有連跌兩個月，拉回就是買點」。這裡把它變成數字：過去 5 年這種情況下個月多半反彈，"
                       "但 2022/09、2025/02 下個月又跌 3.5%、10.2%，連跌兩個月 5 年內也發生過好幾次（多在 2022 空頭）。"
                       "這是描述過去，不代表下個月一定漲。")


@st.cache_data(ttl=3600, show_spinner=False)
def 殺估值資料(版本鍵):
    return engine.殺估值觀察組(指標, 讀檔("讀取美股", _版本))


@st.cache_data(ttl=3600, show_spinner=False)
def 光通訊資料(版本鍵):
    return engine.光通訊美台對照(指標, 讀檔("讀取美股", _版本))


def 光通訊區():
    t, 美 = 光通訊資料(_版本)
    if t.empty:
        return
    美字 = "、".join(f"{名} {v:+.1f}%（{d:%m/%d}）" for 名, (d, v) in 美.items())
    with st.expander(f"🔦 光通訊：昨晚美股 {美字} → 台股光通訊"):
        欄 = {c: st.column_config.NumberColumn(format="%+.2f") for c in t.columns if c.endswith("%")}
        表格(t, hide_index=True, width="stretch", column_config=欄)
        st.caption("相關＝近 120 個交易日，台股當天漲跌跟「前一晚」美股的相關係數（1＝完全同向）。"
                   "Lumentum 漲 1% 跟漲%＝前一晚 Lumentum 漲 1%，台股隔天平均漲幾 %。"
                   "11/03 Lumentum 前一晚跌 18.6%（被邁威爾換股收購），聯亞、全新、穩懋全部跌停。"
                   "推估只看單一美股，實際還有大盤與題材影響，只是參考。")


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


def 盤中即時排行():
    """按了才抓：昨天成交值前 200 檔的盤中即時價（證交所延遲約 5～20 秒），排出漲幅、跌幅、成交量。"""
    with st.expander("⚡ 盤中即時排行（按了才抓，昨天成交值前 200 檔，約 3 秒）"):
        if st.button("抓盤中即時排行", key="即時排行鈕"):
            池 = 今日[~今日["代號"].str.startswith("00")].nlargest(200, "成交值億")
            try:
                即 = engine.即時報價(池["代號"].tolist(), dict(zip(池["代號"], 池["市場"])))
                即 = 即.dropna(subset=["close"]).assign(幅度=lambda d: d["change"] / (d["close"] - d["change"]) * 100)
                st.session_state["即時排行"] = 即
            except Exception as e:
                st.warning(f"即時行情暫時抓不到（{type(e).__name__}），等一下再試。")
        即 = st.session_state.get("即時排行")
        if 即 is None or 即.empty:
            st.caption("盤中按一下就會抓；收盤後看下面的正式排行即可。")
            return
        顯 = 即.rename(columns={"code": "代號", "name": "名稱", "close": "現價", "幅度": "漲跌幅%", "volume": "成交張數", "time": "時間"})
        欄 = ["代號", "名稱", "現價", "漲跌幅%", "成交張數", "時間"]
        格式 = {"現價": st.column_config.NumberColumn(format="%.2f"), "漲跌幅%": st.column_config.NumberColumn(format="%+.2f"),
              "成交張數": st.column_config.NumberColumn(format="%d")}
        分 = st.tabs(["漲幅", "跌幅", "成交量"])
        for 頁, (欄名, 大) in zip(分, (("漲跌幅%", True), ("漲跌幅%", False), ("成交張數", True))):
            with 頁:
                表格((顯.nlargest(20, 欄名) if 大 else 顯.nsmallest(20, 欄名))[欄], hide_index=True, width="stretch", column_config=格式)
        st.caption(f"抓取時間 {即['time'].dropna().max() or ''}；只含昨天最熱門的 200 檔，冷門股盤中暴衝不會出現在這裡。")


def 排行區():
    段落("RANKING // 排行（前 50 檔，含上市櫃）")
    盤中即時排行()
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


@st.cache_data(ttl=30, show_spinner=False)
def 盤中權值報價(代號們):
    try:
        t = engine.即時報價(list(代號們), {})
        return t.dropna(subset=["close"]).set_index("code") if not t.empty else None
    except Exception:
        return None


def 盤中權值來源():
    """盤中：市值前 80 大上市股用即時報價、其他當作平盤，加權指數接上即時點數。抓不到回傳 None。"""
    上市 = 今日[(今日["市場"] == "上市") & ~今日["代號"].str.startswith("0") & 今日["發行股數"].notna()]
    大 = 上市.assign(市值=上市["收盤"] * 上市["發行股數"]).nlargest(80, "市值")["代號"]
    即 = 盤中權值報價(tuple(大))
    指 = 大盤即時()
    if 即 is None or 指 is None or "t00" not in 指.index or 加權 is None:
        return None
    來源 = 今日.copy()
    來源["收盤"] = 來源["收盤"].astype("float64")  # 資料庫是 float32，pandas 3 不允許把 float64 即時價寫進去
    來源["漲跌幅"] = 0.0
    有 = 來源["代號"].isin(即.index)
    現 = 來源.loc[有, "代號"].map(即["close"])
    漲 = 來源.loc[有, "代號"].map(即["change"])
    來源.loc[有, "收盤"] = 現
    來源.loc[有, "漲跌幅"] = (漲 / (現 - 漲) * 100).astype(float)
    r = 指.loc["t00"]
    今天 = pd.Timestamp.now(tz="Asia/Taipei").normalize().tz_localize(None)
    加 = pd.concat([加權[加權["date"] < 今天], pd.DataFrame({"date": [今天], "close": [r["close"]], "change": [r["change"]]})],
                  ignore_index=True)
    return 來源, 加, r["time"]


@st.fragment(run_every=刷新秒(60))
def 權值區():
    輪詢檢查()  # 開盤／收盤時切換自動更新頻率
    段落("WEIGHT // 權值股：今天誰撐盤、誰拖盤")
    期間 = st.segmented_control("貢獻期間", list(engine.族群期間), default="今日", key="權值期間",
                              label_visibility="collapsed") or "今日"
    盤中 = 盤中權值來源() if engine.盤中時間() and 期間 == "今日" else None
    if 盤中:
        st.caption(f"⚡ 盤中即時 {盤中[2]}（市值前 80 大上市股，約佔加權 8 成，每分鐘更新；其他股票先當平盤）")
        表, 摘要 = engine.權值貢獻(盤中[0], 盤中[1], 期間)
    else:
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
                f"權重 {表.loc[表['代號'] == '2330', '權重'].sum():.1f}%", 漲跌色(表.loc[表['代號'] == '2330', '貢獻點數'].sum()),
                股連結("2330"))])
    撐 = 表[表["貢獻點數"] > 0].nlargest(20, "貢獻點數")
    拖 = 表[表["貢獻點數"] < 0].nsmallest(20, "貢獻點數")
    # 像一棵樹：中間一條線，撐盤紅條往左長、拖盤綠條往右長，「代號 名稱」在最外側；各 20 檔，由上往下影響越來越小
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
    圖表外觀(圖, 26 * max(len(撐), len(拖), 1) + 60).update_layout(hovermode="closest", showlegend=False,
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
    try:
        集 = engine.集體升降評(券商報告清單(st.session_state.get("_券商版本", 0)))
    except Exception:
        集 = []
    if 集:
        st.markdown("📣 **券商集體調整目標價（近 3 天 3 家以上）**：" + "、".join(
            f"{代} {名} {'⬆' if 方 == '上修' else '⬇'}{家} 家" for 代, 名, 方, 家, _ in 集[:10]))
    if 手機:  # 手機：大字清單，每檔一行＋理由，點了到個股
        for 名, 表 in (("🛡️ 需要防守", 風險), ("🔍 值得研究", 機會)):
            st.markdown(f"**{名}**（{len(表)} 檔）")
            if 表.empty:
                st.caption("今天沒有符合的股票。")
                continue
            列 = []
            for _, x in 表.head(8).iterrows():
                幅 = x.get("漲跌幅")
                幅字 = "" if pd.isna(幅) else f' <span style="color:{漲跌色(幅)}">{幅:+.1f}%</span>'
                列.append(f'<a href="?s={x["代號"]}" target="_self">{html.escape(str(x["股票"]))}{幅字}'
                          f'<small>{html.escape(str(x["理由"]))}</small></a>')
            st.markdown('<div class="flist">' + "".join(列) + "</div>", unsafe_allow_html=True)
            if len(表) > 8:
                with st.expander(f"其餘 {len(表) - 8} 檔"):
                    點選表(表.iloc[8:], 上色(表.iloc[8:]).format({"收盤": "{:,.2f}", "漲跌幅": "{:+.2f}", "總分": "{:.1f}"}, na_rep="—"),
                           f"焦點更多{名}", column_config={"代號": None})
        st.caption("依規則挑出來的名單，不是買賣建議。⭐＝你的庫存或自選股。點一下到個股查詢。")
        return
    左, 右 = st.columns(2)
    for 欄, 名, 表, 鍵 in ((左, "🔍 值得研究", 機會, "焦點機會"), (右, "🛡️ 需要防守", 風險, "焦點風險")):
        with 欄:
            st.markdown(f"**{名}**（{len(表)} 檔）")
            if 表.empty:
                st.caption("今天沒有符合的股票。")
            else:
                點選表(表, 上色(表).format({"收盤": "{:,.2f}", "漲跌幅": "{:+.2f}", "總分": "{:.1f}"}, na_rep="—"), 鍵,
                       height=min(35 * (len(表) + 1) + 3, 460), column_config={"代號": None,
                                                                        "理由": st.column_config.TextColumn(width="large")})
    st.caption("RESEARCH ONLY 僅供研究：依規則挑出來的名單，不是買賣建議。"
               "值得研究＝評分大升、營收創新高、帶量突破盤整、外資投信連買、3 檔以上主動式 ETF 同時加碼；"
               "需要防守＝注意／處置股、評分大跌、跌破十日線且法人賣、融資暴增但股價跌、法人 5 日大賣。"
               + ("⭐＝你的庫存或自選股，會排在最前面。" if 我的 else "解鎖後你的庫存、自選股會用 ⭐ 標示並排在最前面。")
               + "只看成交 500 張以上的股票。點一下可到個股查詢。")


@st.cache_resource(max_entries=1, show_spinner="計算市場情緒中…")
def 情緒資料(版本鍵):
    return engine.情緒指數(指標, 加權)


@st.cache_data(ttl=3600, show_spinner=False)
def 經濟日程資料(版本鍵, 天數=14, 往前=0):
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
           卡片("大盤評分", f"{判['大盤']['分數']}", 判["大盤"]["看法"], 分數色(判["大盤"]["分數"]), 頁連結("07")),
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
        項們, 溫, 級, 話 = engine.恐慌溫度計(讀檔("讀取美股", _版本), 讀檔("讀取匯率", _版本), 讀檔("讀取小台散戶", _版本))
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
    VIX跳升區()
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
    法說反應區()


@st.cache_data(ttl=3600, show_spinner=False)
def 法說反應資料(版本鍵):
    法 = engine.讀取法說會()
    if 法 is None:
        return pd.DataFrame()
    法 = 法[法["date"] < pd.Timestamp(今日["date"].max())]
    return engine.法說後反應(法, 指標[指標["代號"].isin(set(法["code"]))][["代號", "date", "收盤"]], 指數K線("TAIEX", _版本))


def 法說反應區():
    with st.expander("🎤 法說會後隔天股價反應（扣掉大盤）"):
        t = 法說反應資料(_版本)
        if t.empty:
            st.caption("法說會資料累積中（從 11 月起保留已開過的法說會）。")
            return
        st.markdown(f"近期 {len(t)} 場法說會：隔天贏大盤 {(t['隔天超額%'] > 0).sum()} 場、輸大盤 {(t['隔天超額%'] < 0).sum()} 場，"
                    f"隔天平均超額 {t['隔天超額%'].mean():+.1f}%")
        表格(t.head(60), hide_index=True, width="stretch",
             column_config={"法說日": st.column_config.DateColumn(format="MM/DD")}
             | {c: st.column_config.NumberColumn(format="%+.1f") for c in t.columns if c.endswith("%")})
        st.caption("隔天＝法說會之後第一個交易日收盤比法說日收盤；超額＝再扣掉同期加權漲跌。"
                   "網紅說「法說很好、隔天還跌，代表市場有問題」：如果最近很多公司法說後都輸大盤，就是市場情緒偏弱的線索。")


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
    t = engine.美股超賣(讀檔("讀取美股", _版本))
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
def 美股連動資料(版本鍵, 分類):
    return engine.美股連動(指標, 分類)


@st.cache_data(ttl=600, show_spinner=False)
def 大盤解讀紀錄(快取鍵):
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
                    摘要 = engine.大盤摘要(指標, 加權, 國際, 期貨, 設定)
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
        項們, 總結 = engine.三條件燈號(指數K線("TAIEX", _版本), 指數K線("TPEX", _版本), 讀檔("讀取美股", _版本))
    except Exception:
        項們, 總結 = [], ""
    燈們 = [燈 for _, 燈, _ in 項們]
    燈 = "🟢" if 燈們 and all(x == "🟢" for x in 燈們) else ("🔴" if 燈們.count("🔴") >= 2 else "🟡")
    格 = engine.格局判斷(K) or {"格局": "—", "說明": ""}
    支, 壓 = 解["最近支撐"], 解["最近壓力"]
    f = lambda r: "—" if r is None else f"{r['價位']:,.0f}"
    段落("30 SEC // 三十秒看盤")
    卡片格([卡片("觀察燈號", f"{燈} {''.join(燈們)}", 總結 or "資料不足", {"🟢": 紅, "🔴": 綠}.get(燈, "#FFC24B"), 錨("價位")),
           卡片("加權格局", 格["格局"], f"收盤 {sr['收盤']:,.0f}", {"上升": 紅, "下降": 綠}.get(格["格局"], "#EDEDED"),
                錨("大盤走勢")),
           卡片("今天看的價位", f"{f(支)} / {f(壓)}",
                f"支撐{'' if 支 is None else 支['名稱']} · 壓力{'' if 壓 is None else 壓['名稱']}", 連結=錨("價位"))])
    紀錄 = 大盤解讀紀錄(st.session_state.get("_解讀版本", 0))
    if 紀錄:
        最新 = 紀錄[sorted(紀錄)[-1]]
        句 = 一句話結論(最新.get("內容", ""))
        if 句:
            st.markdown(f'<div class="verdict"><b>AI {最新.get("模式", "")}解讀 {str(最新.get("時間", ""))[5:]}</b>　{句}</div>',
                        unsafe_allow_html=True)
    st.caption("燈號＝費半、加權、櫃買三個觀察條件；跌破支撐或站上壓力時，到下方「價位」區看下一個價位。僅供研究參考。")


@st.cache_data(ttl=3600, show_spinner=False, max_entries=1)
def 選擇權資料(版本鍵):
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
    段落("EVENTS // 新股申購抽籤、庫藏股、可轉債、董監轉讓、興櫃")
    分頁們 = st.tabs(["🎫 新股申購抽籤", "🛒 庫藏股", "📜 可轉債", "🧾 董監轉讓", "🌱 興櫃"])
    現價 = 今日.set_index("代號")["收盤"]
    with 分頁們[0]:
        申 = 讀檔("讀取新股申購", _版本)
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
        庫 = 讀檔("讀取庫藏股", _版本)
        if 庫 is None:
            st.caption("庫藏股資料還沒下載。")
        else:
            近 = 庫[(庫["end"] >= 最新日) | (庫["board_date"] >= 最新日 - pd.Timedelta(days=45))].sort_values("board_date", ascending=False)
            顯示 = pd.DataFrame({"決議日": 近["board_date"].dt.strftime("%m/%d"), "代號": 近["code"], "名稱": 近["name"],
                                "預定張數": 近["planned"] / 1000, "價格下限": 近["price_low"], "價格上限": 近["price_high"],
                                "現價": 近["code"].map(現價), "買回期間": 近["start"].dt.strftime("%m/%d") + "～" + 近["end"].dt.strftime("%m/%d"),
                                "狀態": np.where(近["done"].astype(str).str.upper() == "Y", "已完畢", "執行中"),
                                "價位": np.where((近["done"].astype(str).str.upper() == "Y") | 近["code"].map(現價).isna(), "",
                                               np.where(近["code"].map(現價) < 近["price_low"], "⚠️ 低於下限，暫時買不了",
                                                        np.where(近["code"].map(現價) > 近["price_high"], "高於上限，暫停買", "區間內，可買"))),
                                "已買回%": 近["pct_done"], "佔股本%": 近["pct_shares"]})
            點選表(顯示, 上色(顯示).format({"預定張數": "{:,.0f}", "價格下限": "{:,.2f}", "價格上限": "{:,.2f}", "現價": "{:,.2f}",
                                         "已買回%": "{:.1f}", "佔股本%": "{:.2f}"}, na_rep="—"), "庫藏股表", column_config={"代號": None})
            st.caption("近 45 天董事會決議、或還在買回期間的庫藏股。公司只能在「價格下限～上限」之間買回：現價在區間內才買得到；"
                       "現價低於下限（⚠️）時公司不能買，高於上限也暫停，要等股價回到區間或公司另開新一輪。"
                       "所以「老闆護盤」要看現價有沒有在區間內。資料：公開資訊觀測站。")
    with 分頁們[2]:
        債 = 讀檔("讀取可轉債", _版本)
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
    with 分頁們[3]:
        董監轉讓區(現價)
    with 分頁們[4]:
        興櫃區()


def 興櫃區():
    總 = engine.興櫃總覽(讀檔("讀取興櫃歷史", _版本), 讀檔("讀取推薦券商", _版本), 讀檔("讀取推薦變動", _版本),
                       讀檔("讀取重大訊息", _版本))
    if 總.empty:
        st.caption("興櫃行情還沒下載。")
        return
    try:
        我的 = {c for v in 自選股清單().values() for c in v} if 可編輯() else set()
    except Exception:
        我的 = set()
    看 = st.segmented_control("看哪些", ["申請掛牌中", "推薦券商有變動", "我的自選", "成交最熱"], default="成交最熱",
                             key="興櫃篩選") or "成交最熱"
    t = {"申請掛牌中": 總[總["掛牌進度"] != ""], "推薦券商有變動": 總[總["推薦變動"] != ""],
         "我的自選": 總[總["代號"].isin(我的)], "成交最熱": 總.sort_values("成交張數", ascending=False).head(30)}[看]
    if not len(t):
        st.caption({"申請掛牌中": "近 90 天沒有抓到申請上市櫃的重大訊息（從 2026/11 開始累積）。",
                    "推薦券商有變動": "近 30 天推薦券商沒有變動（從 2026/11 開始比對）。",
                    "我的自選": "自選股裡沒有興櫃股票，可以在 02 我的股票加入。"}.get(看, "沒有資料。"))
    else:
        點選表(t, 上色(t).format({"收盤": "{:,.2f}", "均價": "{:,.2f}", "20日均價": "{:,.2f}", "漲幅%": "{:+.1f}",
                               "成交張數": "{:,.0f}", "推薦家數": "{:.0f}"}, na_rep="—"), "興櫃表", column_config={"代號": None})
    申 = 讀檔("讀取新股申購", _版本)
    表現 = engine.新股掛牌表現(engine.申購試算(申, 今日.set_index("代號")["收盤"])) if 申 is not None else None
    st.caption("漲幅%＝近 20 個交易日。推薦家數＝推薦券商（造市）家數，家數變少常是券商不看好或準備轉上市櫃；"
               "估計承銷價＝近 20 日均價 × 0.7～0.85，是經驗法則，實際以公告為準。"
               + (f"參考：過去 {表現['檔數']} 檔初上市櫃，現價比承銷價的中位數 {表現['中位數%']:+.0f}%，"
                  f"{表現['上漲比例%']:.0f}% 高於承銷價。" if 表現 else "") + "興櫃沒有漲跌幅限制、成交量小，風險比上市櫃高很多。")
    興櫃估值試算(總)


def 興櫃估值試算(總):
    with st.expander("🧮 掛牌前估值試算：同業本益比 × 自己估的 EPS"):
        選項 = [f"{c} {n}" for c, n in zip(總["代號"], 總["名稱"])]
        預設 = next((i for i, v in enumerate(選項) if v.startswith("3595 ")), 0)
        選 = st.selectbox("興櫃股", 選項, index=預設, key="興櫃估值股")
        代號 = 選.split()[0]
        列 = 總[總["代號"] == 代號].iloc[0]
        概念們 = engine.個股概念(代號)
        概 = engine.讀取概念()
        同概念 = 概[概["concept"].isin(概念們) & (概["code"] != 代號)]["code"].unique().tolist()
        有價 = set(今日["代號"])
        同業字 = st.text_input("同業代號（上市櫃，用逗號分開）", ", ".join(c for c in 同概念 if c in 有價),
                             key=f"興櫃估值同業_{代號}", placeholder="例如 7734")
        同業 = [c.strip() for c in re.split(r"[,，、\s]+", 同業字) if c.strip()]
        欄 = st.columns(2)
        今年 = 欄[0].number_input("今年 EPS（自己估）", min_value=0.0, value=0.0, step=0.5, key=f"興櫃估值今年_{代號}")
        明年 = 欄[1].number_input("明年 EPS（自己估，可空白）", min_value=0.0, value=0.0, step=0.5, key=f"興櫃估值明年_{代號}")
        同業表 = 今日[今日["代號"].isin(同業)][["代號", "名稱", "收盤", "本益比"]]
        if len(同業表):
            表格(同業表.style.format({"收盤": "{:,.2f}", "本益比": "{:.1f}"}, na_rep="—"), hide_index=True, width="stretch")
        elif 同業:
            st.caption("找不到這些同業的上市櫃行情，請確認代號。")
        結果 = engine.掛牌估值試算(列["收盤"], {"今年": 今年, "明年": 明年}, 同業表["本益比"].tolist())
        if len(結果):
            表格(結果, hide_index=True, width="stretch")
        else:
            st.caption("輸入同業代號和至少一個 EPS 就會算出參考價。興櫃公司的 EPS 可以看公開資訊觀測站的半年報、月營收自己推。")
        風險 = [(k, engine.技術替代風險[k]) for k in 概念們 if k in engine.技術替代風險]
        if 風險:
            st.warning("🔁 **技術替代風險**：" + "　".join(f"**{k}**｜{v}" for k, v in 風險))
        try:
            影片們 = 網紅說法清單(st.session_state.get("_網紅版本", 0))
            價 = engine.網紅價位(影片們, {代號: float(列["收盤"])}, 天數=90)
            價 = 價[價["代號"] == 代號] if len(價) else 價
        except Exception:
            價 = pd.DataFrame()
        if len(價):
            st.markdown("**評論者的價位計畫**：" + "；".join(
                f"{r['頻道']} {r['類型']} {r['價位']:,.0f}" + (f"（距今 {r['距離%']:+.1f}%）" if pd.notna(r["距離%"]) else "")
                for _, r in 價.head(6).iterrows()))
        st.caption("同業本益比用網站的近四季本益比，取低四分位、中位數、高四分位。掛牌時承銷商常拿同業本益比定價，"
                   "所以現價換算的倍數比同業高很多時，要小心掛牌後往同業靠攏。EPS 是你自己的假設，不是公司財測。")


def 董監轉讓區(現價):
    轉 = 讀檔("讀取內部人轉讓", _版本)
    if 轉 is None or not len(轉):
        st.caption("董監轉讓申報從 2026/11 開始每天累積，還沒有資料。")
        return
    try:
        我的 = (set(map(str, 庫存代號() or [])) | {c for v in 自選股清單().values() for c in v}) if 可編輯() else set()
    except Exception:
        我的 = set()
    近 = 轉[轉["date"] >= 最新日 - pd.Timedelta(days=30)].sort_values("date", ascending=False)
    顯示 = pd.DataFrame({"申報日": 近["date"].dt.strftime("%m/%d"), "代號": 近["code"], "名稱": 近["code"].map(市場名稱),
                        "身分": 近["身分"], "姓名": 近["姓名"], "方式": 近["方式"].str.replace(r"\(.*\)", "", regex=True),
                        "張數": 近["股數"] / 1000, "佔持股%": (近["股數"] / 近["持股"] * 100).round(1),
                        "現價": 近["code"].map(現價), "期間": 近["期間"]})
    if 我的:
        顯示.insert(0, "我的", np.where(顯示["代號"].isin(我的), "⭐", ""))
    點選表(顯示, 上色(顯示).format({"張數": "{:,.0f}", "佔持股%": "{:.1f}", "現價": "{:,.2f}"}, na_rep="—"), "轉讓表",
          column_config={"代號": None})
    st.caption("董監、大股東要賣股票前要先申報（事前申報），一般交易＝在市場上賣，最值得注意；"
               "贈與、信託、盤後定價給特定人通常是家族或稅務安排。佔持股%＝這次要賣的股數 ÷ 申報人原本持股。資料：證交所、櫃買中心。")
    明, 彙 = engine.內部人記分板(轉, 寬價格(_版本), 指數K線("TAIEX", _版本))
    段落("SCORE // 申報轉讓之後，股價有沒有比大盤差")
    if 彙.empty or 彙["20天到期"].sum() == 0:
        st.caption(f"目前累積 {len(轉)} 筆申報，要等申報後滿 20 個交易日才能對答案。")
    else:
        表格(彙, width="stretch", column_config={c: st.column_config.NumberColumn(format="%+.1f")
                                               for c in ("20天平均超額%", "60天平均超額%")})
        st.caption("超額＝申報後的股價報酬 − 同期加權報酬。平均是負的、輸大盤%高，代表內部人賣得有道理。樣本少時只是參考。")



@st.cache_data(ttl=3600, show_spinner=False)
def 總經資料(版本鍵):
    美 = engine.讀取美股()
    行 = pd.read_csv(engine.資料夾 / "econ_calendar.csv") if (engine.資料夾 / "econ_calendar.csv").exists() else None
    財 = pd.read_csv(engine.資料夾 / "us_earnings.csv") if (engine.資料夾 / "us_earnings.csv").exists() else None
    K = engine.讀取指數K線("TAIEX")
    return 美, 行, 財, K


@st.cache_data(ttl=3600, show_spinner=False)
def 費半回撤資料(版本鍵):
    return macro.費半回撤(macro.讀取費半長線())


@st.cache_data(ttl=3600, show_spinner=False)
def 台指期價差資料(版本鍵):
    return engine.讀取台指期價差()


def 價差區():
    """基礎撐壓講義：正逆價差 × 全市場未平倉增減四象限。"""
    t = 台指期價差資料(_版本)
    if t is None or len(t) < 2:
        st.caption("台指期正逆價差：資料下次每日更新後開始累積（期交所近月收盤＋全市場未平倉）。")
        return
    r = t.iloc[-1]
    燈, 說 = engine.象限解讀.get(r["象限"], ("⚪", "換月或資料不足，今天不判斷"))
    st.markdown(f"**📐 台指期正逆價差 × 未平倉**（{t.index[-1]:%m/%d}，近月 {r['月份']}）")
    卡們 = [
        卡片("期貨 − 加權", f"{r['價差']:+,.0f} 點", f"{'正價差' if r['價差'] > 0 else '逆價差' if r['價差'] < 0 else '平'}"
             + (f"，較前日 {r['價差變化']:+,.0f}" if pd.notna(r["價差變化"]) else ""), 漲跌色(r["價差"])),
        卡片("台指期全市場未平倉", f"{r['未平倉']:,.0f} 口",
             f"較前日 {r['未平倉變化']:+,.0f}" if pd.notna(r["未平倉變化"]) else ""),
        卡片("四象限", f"{燈} {r['象限']}", 說),
    ]
    卡片格(卡們)
    統 = engine.象限統計(t)
    with st.expander("📋 四象限準不準？（之後 5 日加權報酬）＋近 20 日明細"):
        if 統 is not None:
            表格(統.reset_index().rename(columns={"index": "象限", "平均報酬": "平均報酬(%)", "上漲機率": "上漲機率(%)"}),
                 hide_index=True, width="stretch")
            st.caption(f"統計 {t.index[0]:%Y/%m/%d} 起的 {int(統.loc['全部日子', '次數'])} 天。跟「全部日子」差不多就代表這個象限沒有預測力。")
        else:
            st.caption("資料還不到 20 天，統計之後才會出現。")
        近 = t.tail(20).iloc[::-1].reset_index()
        表格(近[["date", "期貨", "加權", "價差", "價差變化", "未平倉", "未平倉變化", "象限"]].rename(columns={"date": "日期"}),
             hide_index=True, width="stretch",
             column_config={"日期": st.column_config.DateColumn(format="MM/DD"),
                            **{c: st.column_config.NumberColumn(format="%+.0f") for c in ("價差", "價差變化", "未平倉變化")}})
    st.caption("價差＝台指期近月收盤（13:45）− 加權收盤（13:30），兩者收盤時間不同，盤後 15 分鐘的波動也會算進去。"
               "換月那天價差跳動是合約換了，不判斷。除息旺季（6～8 月）的逆價差主要是期貨先扣掉預估除息點數，不代表看空。"
               "四象限是講義的口訣，網站會自動統計之後的實際結果。")


def 期貨試算區():
    保, 來源 = engine.讀取期貨保證金()
    加 = 指數K線("TAIEX", _版本)
    預設點 = int(round(float(加["close"].iloc[-1]))) if 加 is not None else 45000
    a, b, c = st.columns(3)
    商品 = a.selectbox("商品", list(engine.期貨規格), index=1, key="試算商品")
    點位 = b.number_input("進場點位", value=預設點, step=100, key="試算點位")
    方向 = c.segmented_control("方向", ["多", "空"], default="多", key="試算方向") or "多"
    d, e, f = st.columns(3)
    口數 = d.number_input("口數", value=1, min_value=1, step=1, key="試算口數")
    資金 = e.number_input("帳戶資金（元）", value=保[商品]["原始"] * 4, step=10_000, key=f"試算資金{商品}")
    手續費 = f.number_input("手續費（單邊每口，元）", value={"大台（TX）": 50, "小台（MTX）": 25, "微台（TMF）": 15}[商品],
                          step=5, key=f"試算手續費{商品}")
    x = engine.期貨試算(商品, 點位, 口數, 資金, 方向, 手續費, 保)
    卡們 = [
        卡片("契約價值", f"{x['契約價值']:,.0f} 元", f"每點 {x['每點損益']:,} 元"),
        卡片("原始／維持保證金", f"{x['原始保證金']:,.0f}", f"維持 {x['維持保證金']:,.0f}" + ("" if x["資金夠不夠"] else "　⚠️ 資金不足")),
        卡片("實際槓桿", f"{x['槓桿（對帳戶資金）']:.1f} 倍", f"只放原始保證金是 {x['槓桿（對保證金）']:.1f} 倍；{x['幾口錢做一口']:.1f} 口錢做一口"),
        卡片("來回交易成本", f"{x['來回交易成本']:,.0f} 元", f"含期交稅 {x['期交稅（來回）']:,.0f}，約 {x['成本折合點數']:.1f} 點"),
        卡片("追繳點位", f"{x['追繳點位']:,.0f}", f"{'跌' if 方向 == '多' else '漲'} {x['追繳距離（點）']:,.0f} 點會被追繳"),
        卡片("指數跌 10% 損益", f"{x['指數跌 10% 損益']:+,.0f} 元", f"占帳戶 {x['指數跌 10% 損益'] / 資金 * 100:+.0f}%"),
    ]
    卡片格(卡們)
    st.caption(f"保證金來源：{來源}，期交所會依行情調整。期交稅＝契約價值 × 10 萬分之 2（單邊），手續費依各期貨商不同。"
               "講義建議「4 口的錢做 1 口」：以現在的點位，大台約要準備 280 萬，實際槓桿約 3 倍。"
               "帳戶權益低於維持保證金會被追繳，期貨商在盤中風險指標過低時也可能代為沖銷（砍倉），夜盤一樣要注意。")


@st.cache_data(ttl=3600, show_spinner=False)
def 夜盤法人資料(版本鍵):
    return macro.讀取夜盤法人()


def 大事倒數條():
    """首頁最上面：未來 7 天最近的高影響國際事件倒數。"""
    try:
        _, 行, _, _ = 總經資料(_版本)
        事 = macro.下一個大事(行)
    except Exception:
        事 = None
    if not 事:
        return
    剩 = 事["剩"]
    時 = f"{剩.days} 天 {剩.seconds // 3600} 小時" if 剩.days else f"{剩.seconds // 3600} 小時 {剩.seconds % 3600 // 60} 分"
    名們 = "、".join(f"{engine.國別.get(e['country'], e['country'])} {engine.經濟中文.get(e['title'], e['title'])}"
                    + (f"（預期 {e['forecast']}）" if isinstance(e.get("forecast"), str) and e["forecast"] else "") for e in 事["事件們"][:3])
    st.markdown(f'<div class="verdict">⏰ <b>{時}後</b>（台北 {事["時間"]:%m/%d %H:%M}）：{名們}</div>', unsafe_allow_html=True)


def 總經區():
    段落("MACRO // 總經與國際資金：風險燈、美股溫度、經濟數據、事件統計")
    美, 行, 財, K = 總經資料(_版本)
    燈們 = macro.風險燈(美)
    if 燈們:
        st.markdown(f"**🌐 全球風險燈**：{macro.風險總結(燈們)}")
        卡片格([卡片(f"{x['項目']} · {x['日期']:%m/%d}", f"{x['最新']:,.2f}",
                    f"{x['燈']}　20 日 {x['20日變化']:+.2f}{'%' if x['單位'] == '%' else ''}",
                    "#FFC24B" if "壓力" in x["燈"] else ("#00D68F" if "寬鬆" in x["燈"] else "#EDEDED")) for x in 燈們])
        st.caption("；".join(f"{x['項目']}：{x['說明']}" for x in 燈們) + "。資料：Yahoo 財經（美股收盤後更新）。")
    else:
        st.caption("美元指數、原油、HYG、美債殖利率下次資料更新後就會出現。")
    a, b = st.columns(2)
    with a:
        比 = macro.費半相對強弱(美)
        if 比:
            st.markdown(f"**📉 費半 ÷ S&P 500**：{比['最新']:.3f}，比一年高點（{比['高點日']:%m/%d}）{比['回撤%']:+.1f}%，"
                        f"20 日 {比['20日變化%']:+.1f}%")
            圖 = go.Figure(go.Scatter(x=比["序列"].index, y=比["序列"].values, mode="lines", line=dict(color=青, width=2)))
            st.plotly_chart(圖表外觀(圖, 200), width="stretch", config={"displayModeBar": False})
            st.caption("比值往下＝半導體輸給大盤，資金從 AI 半導體流出；台股電子權值常跟著弱。")
        撤 = 費半回撤資料(_版本)
        if 撤:
            st.markdown(f"**🕳️ 費半距歷史高點**：{撤['最新']:,.0f}，比 {撤['高點日']:%Y/%m/%d} 高點 {撤['高點']:,.0f} "
                        f"{撤['回撤%']:+.1f}%")
            明 = 撤["明細"]
            if len(明):
                有 = 明.dropna(subset=["之後20日%"])
                st.markdown(f"{撤['起']:%Y} 年以來費半第一次跌破 −20% 共 {len(明)} 次；之後 20 個交易日平均 "
                            f"{有['之後20日%'].mean():+.1f}%（上漲 {(有['之後20日%'] > 0).sum()}/{len(有)} 次），"
                            f"60 日平均 {明['之後60日%'].mean():+.1f}%")
                with st.expander("歷次費半跌破 −20% 之後"):
                    表格(明.assign(跌破日=明["跌破日"].dt.strftime("%Y/%m/%d")), hide_index=True, width="stretch",
                         column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in ("當時回撤%", "之後20日%", "之後60日%", "該段最深%")})
                    st.caption("同一段大跌只算第一次跌破（回撤要先回到 −5% 以內才算新的一段）。"
                               "「該段最深」看出跌破 −20% 之後通常還會再跌多少；過去統計不代表下次一樣。")
    with b:
        溫 = macro.美股溫度(美)
        if 溫:
            st.markdown(f"**🌡️ 美股溫度（價格面）**：{溫['溫度']:.0f} / 100，{溫['看法']}")
            st.markdown("、".join(f"{k} {v:.0f}" for k, v in 溫["項目"].items()) + f"（距 200 日線 {溫['距200日線%']:+.1f}%）")
            st.caption("S&P 500 距 200 日線與兩年區間位置、RSI、VIX 反向的百分位平均；75 以上過熱、30 以下偏冷。"
                       "沒有免費的本益比歷史，所以只看價格，不是真正的估值。")
        台 = macro.台幣外資(讀檔("讀取匯率", _版本), 市場每日(_版本).get("外資"))
        if 台:
            st.markdown(f"**💱 台幣與外資**：美元兌台幣 {台['最新']:.3f}（5 日 {台['5日變化%']:+.2f}%，數字變大＝台幣貶），"
                        f"外資 5 日 {台['外資5日億']:+,.0f} 億")
            for w in 台["警示"]:
                st.warning(w)
    合, 家 = macro.AI巨頭資本支出(macro.讀取資本支出())
    if 家 is not None and len(家):
        燈, 話, 明 = engine.資本支出警示(macro.讀取資本支出())
        st.markdown(燈號卡([("AI 資本支出縮手警示", 燈, 話 + "。大廠停資本支出時，AI 供應鏈的獲利預估與本益比通常會一起下修")]),
                    unsafe_allow_html=True)
        if len(明):
            with st.expander("各家最新一季：比上一季、比去年同季"):
                表格(明, hide_index=True, width="stretch", column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in ("季增%", "年增%")})
        st.markdown("**🏗️ AI 巨頭資本支出與自由現金流**（最新一季，億美元）")
        表格(家, hide_index=True, width="stretch", column_config={c: st.column_config.NumberColumn(format="%.0f") for c in
             ("資本支出(億美元)", "營業現金流(億美元)", "自由現金流(億美元)")} | {"年增%": st.column_config.NumberColumn(format="%+.0f"),
             "資本支出÷營業現金流%": st.column_config.NumberColumn(format="%.0f")})
        if 合 is not None and len(合) >= 2:
            圖 = go.Figure([go.Bar(x=合.index, y=合["capex"], name="資本支出", marker_color="#FFB020"),
                           go.Scatter(x=合.index, y=合["fcf"], name="自由現金流", mode="lines+markers", line=dict(color=青))])
            st.plotly_chart(圖表外觀(圖, 240).update_layout(legend=dict(orientation="h", y=1.1)), width="stretch")
        st.caption("資本支出越大＝AI 伺服器、散熱、PCB 等台廠訂單越多；但自由現金流（營業現金流 − 資本支出）轉負，代表要靠借錢撐，"
                   "市場會擔心「AI 投資回不了本」。資料：各公司財報（Yahoo 財經整理）。")
    _費缺 = engine.美股指數缺口("^SOX")
    _那缺 = engine.美股指數缺口("^IXIC")
    _資成 = engine.資料中心成長趨緩()
    if _費缺 or _那缺 or _資成:
        _燈們 = []
        if _費缺:
            _燈們.append(("費半缺口（隔天台股氣氛指標）", _費缺["燈"], _費缺["說明"]))
        if _那缺:
            _燈們.append(("那斯達克缺口", _那缺["燈"], _那缺["說明"]))
        if _資成:
            _燈們.append(("資料中心投資成長趨緩", _資成["燈"], _資成["說明"] + f"（外資報告，{_資成['來源日期']}）"))
        st.markdown(燈號卡(_燈們), unsafe_allow_html=True)
        st.caption("缺口：費半沒站上上方缺口，常被當成反彈力道不夠強的訊號；缺口資料每天更新，只看最近 120 個交易日。"
                   "資料中心：成長率逐年下滑時，市場常先下修本益比，EPS 還沒變；數字手動從外資報告整理（data/dc_capex_growth.csv），有新報告再更新。")
    數 = macro.美國數據表(macro.讀取美國數據(), 行)
    if len(數):
        st.markdown("**📊 美國經濟數據：公布值 vs 預期**")
        表格(數, hide_index=True, width="stretch", column_config={c: st.column_config.NumberColumn(format="%.2f") for c in ("公布值", "前一期", "預期")})
        st.caption("通膨、就業「高於預期（偏熱）」＝降息可能延後，對科技股不利；「偏冷」相反。資料：美國勞工統計局（BLS）；預期：Forex Factory（網站開始收集後才有）。")
    if K is not None:
        with st.expander("📅 事件與季節統計（加權指數 5 年）"):
            分 = st.tabs(["FOMC 後隔天", "非農後隔天", "美股財報後隔天", "月份／星期／結算週", "自訂區間"])
            for 頁, (名, 日們) in zip(分[:2], (("FOMC", macro.FOMC日), ("非農", macro.非農日(K["date"].min(), K["date"].max())))):
                with 頁:
                    r = macro.事件反應(K, 日們)
                    if r:
                        卡片格([卡片(f"{名}後隔天平均", f"{r['平均%']:+.2f}%", f"{r['次數']} 次，上漲機率 {r['上漲機率%']:.0f}%", 漲跌色(r["平均%"])),
                               卡片("平均波動", f"{r['平均波動%']:.2f}%", f"平常日 {r['平常波動%']:.2f}%")])
                        表格(r["明細"].head(12).assign(**{"事件日": lambda d: d["事件日"].dt.strftime("%Y/%m/%d"),
                                                          "台股日": lambda d: d["台股日"].dt.strftime("%Y/%m/%d")}),
                             hide_index=True, width="stretch", column_config={"漲跌%": st.column_config.NumberColumn(format="%+.2f")})
                    st.caption("事件在美國晚上公布，台股反應看隔天。非農日用「每月第一個週五」近似。過去統計不代表下次一定一樣。")
            with 分[2]:
                反 = macro.財報反應(財, 美, K)
                if len(反):
                    st.markdown(f"美股龍頭財報後：加權隔天平均 {反['加權隔日%'].mean():+.2f}%（{len(反)} 次），"
                                f"美股本身漲時加權平均 {反.loc[反['美股漲跌%'] > 0, '加權隔日%'].mean():+.2f}%、"
                                f"跌時 {反.loc[反['美股漲跌%'] < 0, '加權隔日%'].mean():+.2f}%")
                    表格(反.head(30), hide_index=True, width="stretch",
                         column_config={c: st.column_config.NumberColumn(format="%+.2f") for c in ("美股漲跌%", "加權隔日%", "費半同日%")}
                         | {c: st.column_config.DateColumn(format="MM/DD") for c in ("財報日", "美股反應日", "台股日")})
                    st.caption("盤後公布看美股隔天、盤前看當天；台股看美股反應之後的第一個交易日。財報資料從 10 月下旬開始累積。")
                else:
                    st.caption("美股財報資料累積中（財報公司的股價下次資料更新後補齊）。")
            with 分[3]:
                月, 週, 結 = macro.季節統計(K)
                c1, c2 = st.columns([3, 2])
                c1.markdown("**月份效應**")
                c1.dataframe(月, width="stretch")
                c2.markdown("**星期效應**")
                c2.dataframe(週, width="stretch")
                c2.markdown("**結算週（每月第三個週三那週）**")
                c2.dataframe(結, width="stretch")
                st.caption("只有約 5 年資料，每個月份只有 4～5 次樣本，差異多半不顯著，當參考就好。")
            with 分[4]:
                預設 = st.segmented_control("範本", ["水逆", "自己輸入"], default="水逆", key="區間範本") or "水逆"
                文字 = "\n".join(f"{a}~{b}" for a, b in macro.水逆區間) if 預設 == "水逆" else ""
                文字 = st.text_area("日期區間（每行一段：起~迄）", 文字, height=120, key=f"區間文字{預設}",
                                    placeholder="例如\n2024-01-13~2024-01-13（總統大選）\n2026-11-03~2026-11-10")
                區們 = macro.解析區間(文字)
                結 = macro.區間統計(K, 區們) if 區們 else None
                if 結:
                    摘, t = 結["摘要"], 結["t值"]
                    卡片格([卡片("區間內每天平均", f"{摘.loc['區間內', '平均%']:+.3f}%", f"{int(摘.loc['區間內', '天數'])} 天，上漲機率 {摘.loc['區間內', '上漲機率%']:.0f}%",
                                漲跌色(摘.loc["區間內", "平均%"])),
                           卡片("其他日子平均", f"{摘.loc['其他日子', '平均%']:+.3f}%", f"上漲機率 {摘.loc['其他日子', '上漲機率%']:.0f}%",
                                漲跌色(摘.loc["其他日子", "平均%"])),
                           卡片("差異可信嗎", "可能有差" if abs(t) >= 2 else "看不出差別", f"t 值 {t:+.2f}（絕對值 2 以上才算明顯）",
                                "#FFC24B" if abs(t) >= 2 else "#EDEDED"),
                           卡片("各段漲跌", f"{結['漲段']} 漲 / {結['跌段']} 跌", f"共 {len(結['段'])} 段")])
                    段 = 結["段"]
                    if len(段):
                        表格(段.sort_values("起", ascending=False).assign(起=lambda d: d["起"].dt.strftime("%Y/%m/%d"),
                                                                       迄=lambda d: d["迄"].dt.strftime("%Y/%m/%d")),
                             hide_index=True, width="stretch",
                             column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in ("期間漲跌%", "期間最大跌幅%")})
                    st.caption("用加權指數收盤算：區間內＝落在這些日期裡的交易日。水逆日期是天文曆，拿來檢驗「水逆股市比較差」的說法；"
                               "期間漲跌從區間開始前一天收盤算到區間最後一天。玄學或節日說法都可以貼日期進來驗證。")
                elif 文字.strip():
                    st.caption("看不懂日期或區間內交易日太少，請用「2026-10-24~2026-11-13」這種格式，每行一段。")
    供應鏈政策區()


@st.cache_data(ttl=3600, show_spinner=False)
def 借券趨勢資料(版本鍵):
    借 = engine.讀取全部借券()
    價 = 指標[["date", "代號", "收盤"]].rename(columns={"代號": "code", "收盤": "close"})
    return engine.大盤借券趨勢(借, 價)


@st.cache_data(ttl=3600, show_spinner=False)
def 破低不破資料(版本鍵):
    return engine.破低不破榜(指標, 指數K線("TAIEX", 版本鍵))


@st.cache_data(ttl=3600, show_spinner=False)
def 賣壓消散資料(版本鍵):
    匯, 期, K = 讀檔("讀取匯率", 版本鍵), 讀檔("讀取期貨未平倉", 版本鍵), 指數K線("TAIEX", 版本鍵)
    return engine.賣壓消散燈號(匯, 期, K), engine.賣壓消散回測(匯, 期, K)


def 止跌訊號區():
    """網紅摘要 2026-11-07 的 W1～W4：賣壓消散三燈號、指數 vs 融資、全市場借券、破低不破強勢榜。"""
    段落("BOTTOM // 止跌訊號：賣壓消散、融資跟上了沒、空方回補了沒、誰最抗跌")
    # W4 賣壓消散三燈號（宏爺）
    燈, 回 = 賣壓消散資料(_版本)
    st.markdown(f"**賣壓消散三燈號**（宏爺）：目前亮 {燈['亮幾個']} / 3 個" + ("，三個都亮 ✅" if 燈["亮幾個"] == 3 else ""))
    st.markdown(燈號卡(燈["燈們"]), unsafe_allow_html=True)
    if 回 and 回.get("統計"):
        統 = {r["天數"]: r for r in 回["統計"]}
        if 回["次數"]:
            st.caption(f"{回['起']} 起（外資期貨資料開始）三燈同時亮共 {回['次數']} 次：" + "；".join(
                f"{n} 日後上漲 {統[n]['上漲機率%']}%（平均 {統[n]['平均%']:+.1f}%，一般日子 {統[n]['基準平均%']:+.1f}%）"
                for n in (5, 20) if n in 統 and 統[n]["次數"]) + "。樣本很少，只是參考。")
        else:
            st.caption(f"{回['起']} 起（外資期貨資料開始）三燈從來沒有同時亮過，條件很嚴格；先看亮了幾個、往哪個方向變。")
    # W1 指數 vs 融資（雪寶學院、關我什麼事）
    K = 指數K線("TAIEX", _版本)
    對 = engine.指數融資對照(K, engine.讀取融資金額())
    if 對:
        表 = 對["表"]
        st.markdown(f"**加權 vs 上市融資金額**（從 {對['起日']:%m/%d} 高點＝100 起算）：加權 {對['指數跌幅%']:+.1f}%、"
                    f"融資 {對['融資減幅%']:+.1f}%" + (f"，融資約還要再減 **{對['同步還要減億']:,.0f} 億** 才跟指數同比例"
                                                   if 對["同步還要減億"] > 0 else "，融資減幅已經跟上指數"))
        日 = 表.index.strftime("%m/%d")
        圖 = go.Figure()
        圖.add_trace(go.Scatter(x=日, y=表["指數"], mode="lines", name="加權", line=dict(color=青, width=2)))
        圖.add_trace(go.Scatter(x=日, y=表["融資"], mode="lines", name="上市融資金額", line=dict(color="#FFB020", width=2)))
        圖.add_hline(y=100, line=dict(color=灰, width=1, dash="dot"))
        圖.update_xaxes(type="category", nticks=8)
        圖.update_layout(legend=dict(orientation="h", y=1.12, x=0))
        st.plotly_chart(圖表外觀(圖, 300), width="stretch")
        st.caption("融資線在加權線上面＝融資減得比指數慢（還沒洗乾淨）；掉到加權線下面＝融資退場比指數跌得快。"
                   "融資金額用證交所公布的上市融資金額（借出去的錢，不會因股價下跌變少），所以只有還錢、斷頭才會讓它下降。")
    # W3 全市場借券（關我什麼事）
    借 = 借券趨勢資料(_版本)
    if 借 is not None and len(借) > 5:
        燈色, 話 = engine.借券轉向燈(借)
        st.markdown(f"**全市場借券賣出餘額**：{借.index[-1]:%m/%d} 約 {借['餘額億'].iloc[-1]:,.0f} 億　{燈色} {話}")
        近 = 借.tail(60)
        日 = 近.index.strftime("%m/%d")
        圖 = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.6, 0.4],
                           subplot_titles=("借券賣出餘額（不受股價影響，第一天＝100）", "每天借券賣出 − 還券（張）"))
        圖.add_trace(go.Scatter(x=日, y=近["指數"], mode="lines", line=dict(color="#FF8A3D", width=2), name="餘額"), 1, 1)
        淨 = 近["借券賣出張"] - 近["還券張"]
        圖.add_trace(go.Bar(x=日, y=淨, marker_color=[紅 if v < 0 else 綠 for v in 淨], name="賣出−還券"), 2, 1)
        圖.update_layout(showlegend=False, bargap=0.2)
        圖.update_xaxes(type="category", nticks=8)
        圖.update_annotations(font=dict(size=11, color=灰), x=0, xanchor="left")
        st.plotly_chart(圖表外觀(圖, 380), width="stretch")
        st.caption("包含所有上市櫃股票與 ETF。綠柱＝當天借券賣出比還券多（空方加碼），紅柱＝還券比較多（空方回補）。"
                   "7 月那波是 8/01 起借券開始回補、大盤隨後反彈（關我什麼事的說法）；資料從 2026-07-28 開始，只是參考。")
    # W2 破低不破強勢榜（關我什麼事）
    表, 資 = 破低不破資料(_版本)
    if 資:
        狀 = (f"加權近 20 日低點 {資['近期低']:,.0f} 已跌破 {資['前波日']:%m/%d} 前波低點 {資['前波低']:,.0f}（{資['大盤距前低%']:+.1f}%）"
              if 資["大盤破了"] else f"加權近 20 日低點 {資['近期低']:,.0f} 還在 {資['前波日']:%m/%d} 前波低點 {資['前波低']:,.0f} 之上，"
              "大盤沒破，這張表參考價值較低")
        st.markdown(f"**大盤破低、個股不破**（關我什麼事）：{狀}")
        if len(表):
            顯 = 表.head(50)
            點選表(顯, 顯.style.format({"收盤": "{:,.2f}", "前波時低點": "{:,.2f}", "近期低點": "{:,.2f}",
                                     "高於前低%": "{:+.1f}", "收盤距近期低%": "{:+.1f}"}, na_rep="—"),
                  key="破低不破表", height=min(35 * (len(顯) + 1) + 3, 420))
            st.caption(f"共 {len(表)} 檔近 20 日低點還高於「大盤前波低點那幾天（前後 3 天）自己的低點」，"
                       "依高出多少排序、顯示前 50 檔；只看普通股、近 20 日平均成交值 2 億以上。用原始價（沒有還原除權息）。"
                       "高於前低很多的通常是這一段本來就大漲的股票，可搭配「收盤距近期低%」看是不是已經從低點拉回來。點一列看個股。")


# ---------- 股癌 EP712（2026-11-08）：國安基金、季線保衛戰、季線乖離、VIX 跳升、籌碼不安定、Permit、砍單長鞭 ----------
@st.cache_data(ttl=3600, show_spinner=False)
def 標普長線(版本鍵):
    f = engine.資料夾 / "sox_long.csv"
    if not f.exists():
        return None
    t = pd.read_csv(f, parse_dates=["date"])
    return t[t["symbol"] == "^GSPC"].set_index("date")["close"].sort_index()


@st.cache_data(ttl=3600, show_spinner=False)
def 護盤資料(版本鍵):
    K = 指數K線("TAIEX", 版本鍵)
    表, 本次 = engine.國安基金統計(engine.讀取長期指數(K))
    狀 = engine.季線狀態(K)
    乖 = engine.季線乖離位置(K)
    標 = 標普長線(版本鍵)
    統台 = engine.季線站上統計(engine.季線站上事件(K.set_index("date")["close"])) if K is not None else pd.DataFrame()
    統美 = engine.季線站上統計(engine.季線站上事件(標)) if 標 is not None and len(標) > 300 else pd.DataFrame()
    return 表, 本次, 狀, 乖, 統台, 統美


def 護盤區():
    """股癌 EP712 建議 1、2、5：國安基金護盤追蹤、季線保衛戰燈號、季線乖離位置。"""
    段落("RESCUE // 護盤與季線保衛戰：國安基金之後怎麼走、季線站不站得穩")
    表, 本次, 狀, 乖, 統台, 統美 = 護盤資料(_版本)
    卡們 = []
    if 狀:
        卡們.append(卡片("季線保衛戰", f"{狀['燈']} {狀['狀態']}", f"季線 {狀['季線']:,.0f}　乖離 {狀['乖離%']:+.1f}%",
                      {"🟢": 紅, "🟡": "#FFC24B", "🟠": "#FF8A3D", "🔴": 綠}.get(狀["燈"], "#EDEDED")))
    if 乖:
        卡們.append(卡片("季線乖離位置", f"{乖['乖離%']:+.1f}%", f"比 {乖['起']:%Y/%m} 以來 {100 - 乖['百分位']:.1f}% 的日子還低",
                      綠 if 乖["乖離%"] <= -10 else "#EDEDED"))
    if 本次 and not 本次["已過交易日"]:
        前 = 表[表["次"].isin([x["次"] for x in 本次["前幾次"]])] if 表 is not None and "20日%" in 表 else pd.DataFrame()
        卡們.append(卡片(f"國安基金第 {本次['次']} 次", "剛決議", f"{本次['決議日']} 盤後決議，從當天收盤起算；前幾次 20 日 "
                      + "、".join(f"{r['20日%']:+.1f}%" for _, r in 前.iterrows() if pd.notna(r["20日%"])), "#EDEDED"))
    elif 本次:
        比 = "、".join(f"第 {x['次']} 次 {x['同天數%']:+.1f}%" for x in 本次["前幾次"])
        卡們.append(卡片(f"國安基金第 {本次['次']} 次", f"{本次['目前%']:+.1f}%",
                      f"{本次['決議日']} 決議後第 {本次['已過交易日']} 個交易日" + (f"；前幾次同一天 {比}" if 本次["已過交易日"] and 比 else ""),
                      漲跌色(本次["目前%"])))
    if 卡們:
        卡片格(卡們)
    if 狀:
        st.markdown(f"**{狀['燈']} {狀['狀態']}**：{狀['說明']}")
    with st.expander("ℹ️ 站上季線又跌破＝大頭部？回測結果"):
        st.markdown("**股癌 EP712 說法**：跌深反彈先看季線，站上去要守住再往上；站上又掉下來可能是很大的頭部，要把現金拉高。\n\n"
                    "**網站規則**：加權離一年高點跌超過 10% 又在季線下 → 🔴 等站上季線；第一次收盤站上 → 🟡 觀察 10 個交易日；"
                    "10 天都沒跌回去 → 🟢 站穩；10 天內跌回去 → 🟠 又跌破。報酬從第 10 天收盤算起（已經知道結果的時候）。")
        for 名, 統 in (("S&P 500（1994 年起）", 統美), ("加權（網站資料期間）", 統台)):
            if len(統):
                st.markdown(f"**{名}**")
                表格(統, hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in ("60日平均%", "120日平均%", "250日平均%")})
        st.caption("美股 30 年裡跌深後站上季線，七成會在 10 天內又跌回去，跌破組之後一年平均反而沒有比較差；"
                   "差別是之後 120 天內再跌 10% 的機率比較高。所以「又跌破」適合當「先別加碼」的訊號，不是「要大跌」。"
                   "台股只有 5 年資料、樣本很少，方向支持「站穩再加碼」。")
    if 乖 is not None and len(乖["段落"]):
        with st.expander(f"📏 季線乖離 ≤ −10% 的歷史段落（{len(乖['段落'])} 段）"):
            段 = 乖["段落"].sort_values("開始日", ascending=False).assign(開始日=lambda d: d["開始日"].dt.strftime("%Y/%m/%d"))
            表格(段, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in ("當天乖離%", "最低乖離%", "5日%", "20日%", "60日%")})
            st.caption("每一段從乖離第一次跌破 −10% 那天算（40 天內再跌破算同一段）。之後 20 日全部上漲，"
                       "但 2022/07 那段 60 日又跌回去，乖離大是短線反彈的條件，不是見底保證。")
    if 表 is not None and len(表):
        with st.expander("🏦 國安基金歷次護盤"):
            欄 = [c for c in ["次", "決議日", "事件", "退場日", "投入億", "獲利億", "收盤", "距一年高點%", "季線乖離%",
                             "1日%", "5日%", "20日%", "60日%", "120日%", "之後最低再跌%"] if c in 表.columns]
            顯 = 表[欄].iloc[::-1].reset_index(drop=True)
            表格(顯, hide_index=True, width="stretch",
                 column_config={**{c: st.column_config.NumberColumn(format="%+.1f") for c in 欄 if c.endswith("%")},
                                "收盤": st.column_config.NumberColumn(format="%.2f")})
            驗 = engine.國安隔日一季(表)
            if 驗:
                st.markdown(f"**對答案：進場隔天真的噴嗎？一季後呢？** 網站有資料的 {驗['隔日次數']} 次裡，隔天上漲 {驗['隔日上漲']} 次、"
                            f"漲 {驗['門檻']:.0f}% 以上 {驗['隔日噴出']} 次；已滿一季（60 個交易日）的 {驗['一季次數']} 次裡上漲 {驗['一季上漲']} 次、"
                            f"平均 {驗['一季平均%']:+.1f}%。")
                st.caption("兆華艾綸說「歷史 9 次進場，8 次隔天噴出 3% 以上，但一季後 4 勝 5 敗」。網站加權資料從 2021-11 起，只能驗證最近 3 次，"
                           "樣本太少，不能當證據；較早的幾次只有月份沒有日期。")
            st.caption("報酬從決議日收盤算（多半是盤後決議，隔天才可能進場）。網站加權資料從 2021-11 開始，更早的只列事件；"
                       "投入、獲利是媒體整理，口徑不一。新的護盤在 GitHub 的 data/stabilization_fund.csv 加一列就會出現。"
                       "國安基金沒有法定進場點位，「跌到十年線才護盤」只是市場說法。")


@st.cache_data(ttl=3600, show_spinner=False)
def VIX回測資料(版本鍵):
    v = engine.讀取VIX長線()
    標 = 標普長線(版本鍵)
    K = 指數K線("TAIEX", 版本鍵)
    美, _ = engine.VIX跳升統計(v, 標) if 標 is not None else (pd.DataFrame(), {})
    台, _ = engine.VIX跳升統計(v, K.set_index("date")["close"], 隔天=True) if K is not None else (pd.DataFrame(), {})
    return v, 美, 台, engine.VIX今日觸發(v)


def VIX跳升區():
    """股癌 EP712 建議 3：VIX 跳上去、大家極度害怕的時候是短線好買點？"""
    v, 美, 台, 觸 = VIX回測資料(_版本)
    if v is None or 美.empty:
        return
    標題 = "😨 VIX 跳升之後，美股和台股怎麼走？"
    if 觸:
        d, 名, 值, 變 = 觸[0]
        標題 = f"😨 {d:%m/%d} {名}（VIX {值:.1f}、單日 {變:+.0f}%）：之後美股和台股怎麼走？"
    with st.expander(標題, expanded=bool(觸)):
        基 = 美.iloc[0]
        分 = st.tabs(["S&P 500（1994 年起）", "加權（網站資料期間）"])
        for 頁, 表 in zip(分, (美, 台)):
            with 頁:
                if len(表):
                    表格(表, hide_index=True, width="stretch",
                         column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in 表.columns if c.endswith("平均%")})
        st.caption(f"VIX 資料從 {v.index[0]:%Y} 年開始。同一個條件 20 個交易日內只算第一次；S&P 500 用當天收盤、加權用隔天收盤進場。"
                   "次數包含還沒滿天數的最近一次。VIX 單日跳升 50% 以上非常少見，之後 20 日 S&P 500 每次都上漲，但抱一年跟平常差不多："
                   "主委說的「先想清楚 Horizon」——做這一波反彈勝率高，看創新高就沒有優勢。"
                   + f"任意一天之後 20 日平均 {基['20日平均%']:+.1f}%，可以拿來比較。")


@st.cache_data(ttl=3600, show_spinner=False)
def 籌碼不安定資料(版本鍵):
    return engine.籌碼不安定榜(今日, 指標[["date", "代號", "日報酬"]], 指數K線("TAIEX", 版本鍵))


def 籌碼不安定區():
    """股癌 EP712 建議 4：融資佔股本最高的股票＝籌碼不安定，殺盤重災區。"""
    t = 籌碼不安定資料(_版本)
    if t is None or t.empty:
        return
    with st.expander(f"🎲 籌碼不安定榜：融資佔股本最高的 {len(t)} 檔（殺盤時常是重災區）"):
        欄 = [c for c in ["代號", "名稱", "產業", "收盤", "融資佔股本%", "融資餘額", "融資5日增減", "融資維持率", "beta",
                         "5日漲幅", "20日漲幅", "距52週高點"] if c in t.columns]
        點選表(t[欄], t[欄].style.format({"收盤": "{:,.2f}", "融資佔股本%": "{:.1f}", "融資餘額": "{:,.0f}",
                                         "融資5日增減": "{:+.1f}", "融資維持率": "{:.0f}", "beta": "{:.2f}",
                                         "5日漲幅": "{:+.1f}", "20日漲幅": "{:+.1f}", "距52週高點": "{:+.1f}"}, na_rep="—"),
              key="籌碼不安定榜", height=min(35 * (len(t) + 1) + 3, 420),
              column_config={"融資餘額": st.column_config.NumberColumn("融資(張)"),
                             "融資維持率": st.column_config.NumberColumn("維持率%（估）")})
        st.caption("融資佔股本＝融資餘額張數 × 1,000 ÷ 發行股數；只看普通股、融資 500 張以上、成交值 5,000 萬以上。"
                   "2026-11 回測：加權 5 日跌超過 6% 的 9 次急跌裡，融資佔股本最高的 1/5 每次都跌得比最低的 1/5 深"
                   "（平均 −10.5% 對 −4.9%），之後反彈也比較大；但同樣 beta（波動度）的股票比，只多跌 1～4 個百分點，"
                   "所以這張表主要是在抓「高波動、題材股」。另外「週三融資大增的股票跌最慘」實測不成立。點一列看個股。")


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def Permit新聞資料():
    try:
        return engine.Permit新聞()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def 長鞭資料(版本鍵):
    return engine.砍單長鞭()


def 供應鏈政策區():
    """股癌 EP712 建議 7、8：美國資料中心 Permit 有沒有被卡住、砍單有沒有從小料件開始往上傳。"""
    a, b = st.columns(2)
    with a:
        追 = engine.讀取Permit追蹤()
        燈 = 追["燈"].iloc[0] if len(追) else "⚪"
        st.markdown(f"**🏗️ 美國資料中心 Permit**：{燈} " + ({"🔴": "卡住中", "🟡": "部分暫停／審查中", "🟢": "恢復發放"}.get(燈, "")
                     + (f"（{追['日期'].iloc[0]:%m/%d} {追['地區'].iloc[0]}：{追['事件'].iloc[0].replace('（查到日）', '')}）" if len(追) else "還沒有紀錄")))
        st.caption("股癌 EP712：「只要新的 Permit 沒有被卡住，政客嘴巴上要怎麼喊都隨便他」。卡住影響的是 2028～2029 年營收，"
                   "但股價會提早反應。🔴 卡住擴大、🟡 部分暫停或審查中、🟢 恢復發放。")
        with st.expander(f"📋 紀錄（{len(追)} 筆）與最新新聞"):
            if len(追):
                表格(追.assign(日期=追["日期"].dt.strftime("%Y/%m/%d")), hide_index=True, width="stretch",
                     column_config={"來源": st.column_config.LinkColumn("來源", display_text="開啟")})
            新 = Permit新聞資料()
            if len(新):
                st.markdown("**近兩週新聞**（Google 新聞英文搜尋 data center permit／moratorium／ERCOT）")
                for _, r in 新.head(10).iterrows():
                    st.markdown(f"- {r['日期']:%m/%d} {r['訊號']} [{r['標題']}]({r['連結']})　{r['來源']}")
            st.caption("紀錄要手動加：在 GitHub 的 data/permit_watch.csv 加一列（日期, 地區, 事件, 燈, 來源），最新一列的燈就是目前燈號。")
    with b:
        表, 燈 = 長鞭資料(_版本)
        if 燈:
            st.markdown(f"**🪢 砍單長鞭燈**：{燈['燈']} {燈['說明']}（{燈['月份']:%Y/%m} 營收，小料件 {燈['小料件%']}%、上游 {燈['上游%']}% 公司年衰退）")
            圖 = go.Figure()
            色們 = {"被動元件": "#FF8A3D", "電子零組件": "#FFC24B", "電腦及週邊（組裝）": "#B388FF", "半導體": 青, "晶圓代工": "#4DD0E1"}
            for c in 表.columns:
                圖.add_trace(go.Scatter(x=表.index, y=表[c], mode="lines", name=c,
                                        line=dict(color=色們.get(c, "#EDEDED"), width=2, dash="dot" if c in ("半導體", "晶圓代工") else None)))
            圖.add_hline(y=50, line=dict(color=灰, width=1, dash="dot"))
            圖.update_layout(legend=dict(orientation="h", y=-0.15, x=0), yaxis_title="年衰退公司%")
            st.plotly_chart(圖表外觀(圖, 320), width="stretch", config={"displayModeBar": False})
            st.caption("股癌 EP712：砍單通常先從違約代價低的小料件（機構件、沖壓件、被動元件）開始，再像甩長鞭一樣往上傳到台積電。"
                       "線＝各族群「近 3 個月營收合計年減」的公司比例。2022～2023 那次：被動元件 2023/02 衰退比例到 100%，"
                       "晶圓代工晚約 2 個月才到 100%。營收資料從 2021-10 開始，只看得到一次循環。")


階段色 = {"龍頭領漲期": "#E0244A", "全面上攻": "#FF6B6B", "二線補漲期": "#FFB020", "整理": "#888888", "退潮": "#00A86B"}


def 族群輪動區(來源):
    """族群輪動階段：每個族群市值前 3 大當龍頭，看龍頭和二線股誰在漲。"""
    try:
        表 = momentum.族群輪動階段(來源)
    except Exception:
        return
    if 表 is None or 表.empty:
        return
    with st.expander("🔄 族群輪動階段：龍頭領漲 → 二線補漲 → 退潮（點開看每個族群走到哪）", expanded=False):
        數 = 表["階段"].value_counts()
        st.markdown(" ".join(f'<span style="display:inline-block;padding:2px 10px;margin:0 6px 6px 0;border:1px solid {階段色.get(k, "#888")};border-radius:12px;color:{階段色.get(k, "#888")}">'
                             f'{k} {數.get(k, 0)}</span>' for k in momentum.階段順序), unsafe_allow_html=True)
        表格(表, hide_index=True, width="stretch", height=min(420, 38 + 35 * len(表)))
        st.caption("龍頭＝族群市值前 3 大，二線＝其餘股票的中位數。龍頭先漲、二線沒跟＝「龍頭領漲期」（族群剛發動，通常買龍頭）；"
                   "龍頭漲過一段、近 5 日換二線股漲比較多＝「二線補漲期」（資金往落後股擴散，常是行情中後段，追二線要小心）；"
                   "兩邊都跌＝退潮。這是用近 20 日／5 日漲幅做的簡單分類，沒有做過歷史回測，只當觀察族群位置的參考。")


@st.cache_data(ttl=43200, show_spinner=False)
def 資金水位資料(版本鍵):
    v = engine.讀取VIX長線()
    vix = None if v is None else v.rename("close").rename_axis("date").reset_index()
    return momentum.資金水位(指標, 加權, vix)


def 資金水位區():
    段落("LEVEL // 市場健康分數與建議持股水位")
    try:
        匯警 = engine.台幣外資警示(engine.讀取匯率(), 指標)
    except Exception:
        匯警 = None
    if 匯警:
        st.markdown(f'<div class="verdict sub">{匯警["燈"]} <b>新台幣×外資</b>：{匯警["說明"]}（美元兌台幣 {匯警["匯率"]:.2f}）</div>', unsafe_allow_html=True)
    日, 回 = 資金水位資料(_版本)
    if 日 is None or 日.empty:
        st.caption("資料不足，暫時算不出市場健康分數。")
        return
    今 = 日.iloc[-1]
    分, 水位 = float(今["分數"]), float(今["建議持股%"])
    色 = 綠 if 分 <= 35 else (紅 if 分 > 65 else "#FFB020")
    a, b = st.columns([1, 1.3])
    圖 = go.Figure(go.Indicator(
        mode="gauge+number", value=分, number=dict(suffix=" 分", font=dict(color=色)),
        title=dict(text=f"{pd.Timestamp(今['date']):%m/%d} 市場健康分數", font=dict(size=14)),
        gauge=dict(axis=dict(range=[0, 100]), bar=dict(color=色),
                   steps=[dict(range=[0, 35], color="rgba(0,168,107,.18)"), dict(range=[35, 65], color="rgba(255,176,32,.15)"),
                          dict(range=[65, 100], color="rgba(224,36,74,.18)")])))
    圖表外觀(圖, 260)
    a.plotly_chart(圖, width="stretch", config={"displayModeBar": False})
    成分 = []
    for k, 說 in (("站上月線", "站上 20 日線的股票比例 {:.0f}%"), ("騰落10日", "近 10 日騰落（淨上漲家數佔比）{:+.0f}%"),
                 ("加權對季線%", "加權距 60 日線 {:+.1f}%"), ("VIX", "VIX {:.1f}（越低越好）")):
        if k in 今 and pd.notna(今[k]):
            成分.append("- " + 說.format(float(今[k])))
    b.markdown(f"**建議持股水位：約 {水位:.0f}%**（分數 0 → 20%，100 → 90%）\n\n" + "\n".join(成分))
    b.caption("每個指標都換算成「在近一年多裡排第幾」的百分位，再平均。")
    近 = 日.tail(120)
    線 = go.Figure(go.Scatter(x=近["date"], y=近["分數"], mode="lines", line=dict(color="#FFB020", width=2), name="分數"))
    線.add_hline(y=35, line=dict(color=綠, dash="dot", width=1))
    線.add_hline(y=65, line=dict(color=紅, dash="dot", width=1))
    圖表外觀(線, 220).update_layout(showlegend=False)
    st.plotly_chart(線, width="stretch", config={"displayModeBar": False})
    if 回 is not None and len(回):
        st.markdown("**實測：分數高／中／低的時候，加權之後 20 個交易日怎麼走**")
        表格(回, hide_index=True, width="stretch")
    st.caption("⚠️ 誠實說明：這段資料只有約一年多（重疊的 20 日區間，實際獨立樣本很少）。實測反而是「分數低的時候」之後 20 日漲比較多，"
               "代表這個分數比較像「市場體溫計」（現在有多熱、多冷），不是進出場的時機訊號；分數低時降低持股是控制回撤，"
               "不是因為之後一定會跌。持股水位只是風險控管的參考，不是報酬保證。")


@st.cache_data(ttl=3600, show_spinner=False)
def 輝達週資料(版本鍵):
    return engine.輝達事件(engine.讀取美股(), 指標)


def 輝達週區():
    """2026-11-13 網紅摘要：輝達換帥週，財報倒數與台股連動度。"""
    段落("NVDA // 輝達換帥週：財報倒數、哪些台股最跟著輝達動")
    d = 輝達週資料(_版本)
    if not d:
        st.caption("資料不足，暫時算不出輝達連動。")
        return
    卡們 = [卡片("輝達收盤", f"{d['收盤']:,.1f}", f"{d['日期']:%m/%d} 單日 {d['單日%']:+.1f}%；離一年高點 {d['距高%']:+.1f}%", 漲跌色(d["單日%"]))]
    if d["財報日"] is not None:
        卡們.append(卡片("輝達財報", f"{d['倒數天']} 天後" if d["倒數天"] else "今天", f"{d['財報日']:%m/%d}{d['時段']}（台灣時間隔天清晨）", "#FFC24B"))
    卡片格(卡們)
    if len(d["表"]):
        表格(d["表"], hide_index=True, width="stretch",
             column_config={"相關": st.column_config.NumberColumn(format="%.2f"), "最近一日%": st.column_config.NumberColumn(format="%+.1f")})
    st.caption("相關＝近 60 個交易日「輝達前一個美股交易日報酬」與「台股隔天報酬」的相關係數（供應鏈名單＋大型權值股）。"
               "只代表過去一起動的程度，不是營收占比，也不是因果；財報前後連動度常會改變。")


@st.cache_data(ttl=3600, show_spinner=False)
def 延續資料(版本鍵):
    美, 匯, K = engine.讀取美股(), engine.讀取匯率(), 指數K線("TAIEX", 版本鍵)
    return engine.反彈延續燈(美, 匯, K), engine.反彈延續回測(美, 匯, K)


def 反彈延續區():
    """2026-11-13 網紅摘要（老王）：費半、那指守 5 日線、台幣不重貶、加權守 5／10 日線＝反彈延續。"""
    段落("REBOUND // 反彈延續燈：美股守住、台幣不重貶、加權守均線")
    燈, 回 = 延續資料(_版本)
    if not 燈:
        st.caption("資料不足，暫時算不出反彈延續燈。")
        return
    st.markdown(f'<div class="verdict sub">{燈["燈"]} <b>{燈["說明"]}</b></div>', unsafe_allow_html=True)
    for 字, 成 in 燈["條件"]:
        st.markdown(f"{'✅' if 成 else '❌'} {字}")
    if len(回):
        with st.expander("📊 這組條件歷史上有用嗎？（實測）"):
            表格(回, hide_index=True, width="stretch",
                 column_config={"平均%": st.column_config.NumberColumn(format="%+.2f"), "上漲機率%": st.column_config.NumberColumn(format="%.0f")})
            st.caption("誠實說明：美股資料只有約兩年，樣本不多且重疊。結果是條件全成立的日子，之後 5 日、20 日表現反而沒有比較好，"
                       "代表這組條件比較像「現在是不是在反彈中」的描述，不是進場訊號；跌破時是提醒降低追高，不代表一定回檔。")


def 必知項目():
    """手機模式首頁最上面：今天必須知道的 5～8 件事（規則整理，不用 AI）。回傳 [(圖示, HTML 文字, 是否警示[, 迷你圖 SVG])]。"""
    項 = []
    每日 = 市場每日(_版本)
    上漲, 下跌 = int((今日["漲跌"] > 0).sum()), int((今日["漲跌"] < 0).sum())
    即 = 大盤即時() if engine.盤中時間() else None
    if 即 is not None and "t00" in 即.index:
        r = 即.loc["t00"]
        幅 = r["change"] / (r["close"] - r["change"]) * 100
        項.append(("📈" if r["change"] >= 0 else "📉",
                  f'<b>加權盤中 {r["close"]:,.0f}</b>（{r["change"]:+,.0f}，<span style="color:{漲跌色(幅)}">{幅:+.2f}%</span>）{r["time"][:5]}', False))
    elif 加權 is not None and not 加權.empty:
        r = 加權.iloc[-1]
        幅 = r["change"] / (r["close"] - r["change"]) * 100
        量 = 今日["成交值億"].sum()
        均 = 每日["成交金額"].tail(6).iloc[:-1].mean() if len(每日) >= 6 else np.nan
        量字 = f"，成交 {量:,.0f} 億" + (f"（比 5 日均量{'多' if 量 >= 均 else '少'} {abs(量 / 均 - 1) * 100:.0f}%）" if pd.notna(均) and 均 else "")
        項.append(("📈" if r["change"] >= 0 else "📉",
                  f'<b>加權 {r["close"]:,.0f}</b>（{r["change"]:+,.0f}，<span style="color:{漲跌色(幅)}">{幅:+.2f}%</span>）{量字}', False,
                  迷你線(加權["close"].tail(20))))
    項.append(("⚖️", f'漲 <span style="color:{紅}">{上漲}</span> 家・跌 <span style="color:{綠}">{下跌}</span> 家'
               + ("，<b>多數股票在漲</b>" if 上漲 > 下跌 * 1.5 else ("，<b>多數股票在跌</b>" if 下跌 > 上漲 * 1.5 else "，漲跌互見")), False))
    try:
        情緒 = 情緒資料(_版本)
    except Exception:
        情緒 = None
    判 = engine.市場狀態(加權, 今日, 每日, 情緒, 經濟日程資料(_版本, 7))
    try:
        日, _ = 資金水位資料(_版本)
        水位 = None if 日 is None or 日.empty else float(日.iloc[-1]["建議持股%"])
    except Exception:
        水位 = None
    色 = 紅 if "多" in 判["狀態"] else (綠 if "空" in 判["狀態"] else "#EDEDED")
    項.append(("🧭", f'市場判讀 <b style="color:{色}">{判["狀態"]}</b>（支持 {len(判["支持"])} 項・反向 {len(判["反向"])} 項）'
               + (f"，建議持股約 <b>{水位:.0f}%</b>" if 水位 is not None else ""), "空" in 判["狀態"]))
    if "外資" in 每日 and 每日["外資"].notna().any():
        今外, 五外 = float(每日["外資"].iloc[-1]), float(每日["外資"].tail(5).sum())
        項.append(("🏦", f'外資今天{"買" if 今外 >= 0 else "賣"}超約 <b>{abs(今外):,.0f} 億</b>，近 5 日{"買" if 五外 >= 0 else "賣"}超 {abs(五外):,.0f} 億', 五外 < -500,
                  迷你柱(每日["外資"].tail(10))))
    if "維持率" in 每日 and 每日["維持率"].notna().any():
        維 = float(每日["維持率"].dropna().iloc[-1])
        級, _ = 維持率等級(維)
        項.append(("💳", f"融資維持率 <b>{維:.0f}%</b>：{級}", 維 < 150, 迷你線(每日["維持率"].tail(20), "#FFB020")))
    try:
        _, 行, _, _ = 總經資料(_版本)
        事 = macro.下一個大事(行)
    except Exception:
        事 = None
    大事 = list(判["待觀察"][:2])
    if 事:
        名 = "、".join(f"{engine.國別.get(e['country'], e['country'])} {engine.經濟中文.get(e['title'], e['title'])}" for e in 事["事件們"][:2])
        大事.insert(0, f"{事['時間']:%m/%d %H:%M} {名}")
    if 大事:
        項.append(("⏰", "接下來的大事：" + "；".join(html.escape(x) for x in 大事[:3]), False))
    if 判["下一步"]:
        項.append(("👀", "下一步看：" + html.escape(判["下一步"][0]), False))
    # 你的股票：到價、注意／處置、大漲大跌（解鎖後才看得到）
    if 可編輯():
        try:
            我的 = list(dict.fromkeys(list(庫存代號() or []) + [c for v in 自選股清單().values() for c in v]))
        except Exception:
            我的 = []
        價 = 今日.set_index("代號")
        警 = 警示表(_版本)
        for 代, 設 in (提醒清單() or {}).items():
            if 代 not in 價.index:
                continue
            收 = float(價.at[代, "收盤"])
            if (設.get("上") and 收 >= 設["上"]) or (設.get("下") and 收 <= 設["下"]):
                項.append(("🔔", f'<a href="?s={代}" target="_self">{代} {價.at[代, "名稱"]}</a> 收 {收:,.2f}，已到提醒價（{提醒文字(設)}）', True))
        for 代 in 我的:
            if 代 in 警:
                項.append(("⚠️", f'<a href="?s={代}" target="_self">{代} {價.at[代, "名稱"] if 代 in 價.index else ""}</a>：{html.escape(警[代])}', True))
        動 = 價.loc[[c for c in 我的 if c in 價.index]]
        動 = 動[動["漲跌幅"].abs() >= 5].sort_values("漲跌幅")
        if len(動):
            項.append(("⭐", "你的股票大動：" + "、".join(
                f'<a href="?s={代}" target="_self">{代} {x["名稱"]}</a> <span style="color:{漲跌色(x["漲跌幅"])}">{x["漲跌幅"]:+.1f}%</span>'
                for 代, x in 動.head(6).iterrows()), True))
    return 項


def 必知區():
    段落("MUST KNOW // 今天必須知道")
    項 = 必知項目()
    st.markdown('<div class="must">' + "".join(
        f'<div class="{"warn" if x[2] else ""}"><i>{x[0]}</i><span>{x[1]}</span>{x[3] if len(x) > 3 else ""}</div>' for x in 項) + "</div>",
        unsafe_allow_html=True)
    st.caption("依收盤資料用規則整理，不是買賣建議。右邊小圖：加權、融資維持率是近 20 日走勢，外資是近 10 日買賣超（紅買綠賣）。" + ("" if 可編輯() else "解鎖後（02 / 我的股票）也會列出你的股票到價、警示、大漲大跌。"))


def 漲跌月曆區():
    """加權指數近 3 個月每天漲跌的月曆熱圖：一格一天，紅漲綠跌、越深漲跌越大，連漲連跌一眼看出。"""
    段落("CALENDAR // 加權漲跌月曆（近 3 個月）")
    if 加權 is None or len(加權) < 10:
        st.caption("資料不足。")
        return
    K = 加權.sort_values("date").tail(66).copy()
    K["幅"] = K["change"] / (K["close"] - K["change"]) * 100
    K["週"] = K["date"] - pd.to_timedelta(K["date"].dt.weekday, unit="D")
    K["星期"] = K["date"].dt.weekday
    週們 = sorted(K["週"].unique())
    z = [[None] * len(週們) for _ in range(5)]
    字 = [[""] * len(週們) for _ in range(5)]
    提示 = [[""] * len(週們) for _ in range(5)]
    for _, r in K.iterrows():
        if r["星期"] > 4:
            continue
        j = 週們.index(r["週"])
        z[r["星期"]][j] = float(r["幅"])
        字[r["星期"]][j] = f'{r["date"].day}'
        提示[r["星期"]][j] = f'{r["date"]:%m/%d}（{"一二三四五"[r["星期"]]}）加權 {r["close"]:,.0f}　{r["幅"]:+.2f}%'
    界 = max(2.0, float(K["幅"].abs().quantile(.9)))
    圖 = go.Figure(go.Heatmap(
        z=z, x=[f"{pd.Timestamp(w):%m/%d}" for w in 週們], y=["一", "二", "三", "四", "五"], text=字, customdata=提示,
        texttemplate="%{text}", textfont=dict(size=12 if 手機 else 11, color="#EDEDED"),
        colorscale=[[0, "#00A870"], [.5, "#2A2A2A"], [1, "#E0244A"]], zmin=-界, zmax=界, zmid=0,
        xgap=3, ygap=3, showscale=False, hovertemplate="%{customdata}<extra></extra>"))
    圖表外觀(圖, 230 if 手機 else 210).update_layout(
        hovermode="closest", yaxis=dict(autorange="reversed", gridcolor="rgba(0,0,0,0)", fixedrange=True),
        xaxis=dict(side="top", gridcolor="rgba(0,0,0,0)", tickfont=dict(size=10), fixedrange=True, dtick=2 if 手機 else 1),
        margin=dict(l=4, r=4, t=26, b=4))
    st.plotly_chart(圖, width="stretch", config={"displayModeBar": False})
    連 = 0
    for v in K["幅"].iloc[::-1]:
        if 連 == 0:
            連 = 1 if v > 0 else -1
        elif (v > 0) == (連 > 0):
            連 += 1 if 連 > 0 else -1
        else:
            break
    漲日 = int((K["幅"] > 0).sum())
    st.caption(f"近 {len(K)} 個交易日：上漲 {漲日} 天、下跌 {len(K) - 漲日} 天；目前{'連漲' if 連 > 0 else '連跌'} {abs(連)} 天。"
               f"一格一天，格子裡是日期；顏色越深漲跌越大（±{界:.1f}% 以上最深）。上方是每週一的日期。")


@st.cache_data(ttl=3600, show_spinner=False, max_entries=4)
def 流向資料(版本鍵, 天數=1):
    """三大法人 × 產業的淨買賣超金額（億）。回傳 DataFrame：產業 × [外資, 投信, 自營]。"""
    if not 有籌碼:
        return pd.DataFrame()
    日們 = sorted(指標["date"].unique())[-天數:]
    t = 指標[指標["date"].isin(日們) & ~指標["代號"].str.startswith("0")][["代號", "收盤", "外資買超", "投信買超", "自營買超"]].copy()
    t["產業"] = t["代號"].map(今日.set_index("代號")["產業"])
    t = t.dropna(subset=["產業"])
    結果 = {}
    for 欄, 名 in (("外資買超", "外資"), ("投信買超", "投信"), ("自營買超", "自營")):
        結果[名] = (t[欄].fillna(0) * 1000 * t["收盤"] / 1e8).groupby(t["產業"]).sum()
    return pd.DataFrame(結果).fillna(0)


def 資金流向區():
    """法人資金流向：左邊是被賣的產業，中間是外資／投信／自營，右邊是被買的產業；帶子越粗金額越大。"""
    段落("FLOW // 法人資金流向")
    期 = st.segmented_control("期間", ["今日", "近 5 日"], default="今日", key="流向期間", label_visibility="collapsed") or "今日"
    d = 流向資料(_版本, 1 if 期 == "今日" else 5)
    if d.empty or not d.abs().values.sum():
        st.caption("今天的法人買賣超資料還沒出來（通常 16:30 後）。")
        return
    淨 = d.sum(axis=1)
    買業 = 淨[淨 > 0].nlargest(6).index.tolist()
    賣業 = 淨[淨 < 0].nsmallest(6).index.tolist()
    法人們 = ["外資", "投信", "自營"]
    節點 = [f"{x} ▼" for x in 賣業] + 法人們 + [f"{x} ▲" for x in 買業]
    idx = {名: i for i, 名 in enumerate(節點)}
    來, 去, 量, 色, 註 = [], [], [], [], []
    for 業 in 賣業:
        for 人 in 法人們:
            v = d.at[業, 人]
            if v < -0.05:
                來.append(idx[f"{業} ▼"]); 去.append(idx[人]); 量.append(-v); 色.append("rgba(0,214,143,.35)"); 註.append(f"{人}賣 {業} {-v:,.1f} 億")
    for 業 in 買業:
        for 人 in 法人們:
            v = d.at[業, 人]
            if v > 0.05:
                來.append(idx[人]); 去.append(idx[f"{業} ▲"]); 量.append(v); 色.append("rgba(255,59,92,.35)"); 註.append(f"{人}買 {業} {v:,.1f} 億")
    if not 量:
        st.caption("今天法人買賣都很小，沒有明顯流向。")
        return
    節點色 = ["#00D68F"] * len(賣業) + ["#7FE9FF"] * 3 + ["#FF3B5C"] * len(買業)
    圖 = go.Figure(go.Sankey(
        arrangement="snap", textfont=dict(color="#EDEDED", size=12 if 手機 else 12, family="Noto Sans TC"),
        node=dict(label=節點, color=節點色, pad=10, thickness=12, line=dict(width=0),
                  hovertemplate="%{label}：%{value:,.1f} 億<extra></extra>"),
        link=dict(source=來, target=去, value=量, color=色, customdata=註, hovertemplate="%{customdata}<extra></extra>")))
    圖.update_layout(height=420 if 手機 else 400, paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=4, r=4, t=8, b=8),
                    font=dict(family="Noto Sans TC, sans-serif"))
    st.plotly_chart(圖, width="stretch", config={"displayModeBar": False})
    總 = d.sum()
    st.caption(f"{期}：外資 {總['外資']:+,.0f} 億、投信 {總['投信']:+,.0f} 億、自營 {總['自營']:+,.0f} 億。"
               "左邊綠色是法人賣出最多的產業（錢流出），右邊紅色是買進最多的產業（錢流入），帶子越粗金額越大。"
               "金額用買賣超張數 × 收盤價估算。")


def 滑卡區():
    """手機首頁：解鎖後滑自選股，沒解鎖就滑今天成交值前 15 檔。"""
    我的 = []
    if 可編輯():
        try:
            我的 = list(dict.fromkeys(list(庫存代號() or []) + [c for v in 自選股清單().values() for c in v]))
        except Exception:
            我的 = []
    if 我的:
        段落("SWIPE // 滑卡看我的股票")
        滑卡(我的, "左右滑看庫存與自選股")
    else:
        段落("SWIPE // 滑卡看今天的熱門股")
        值欄 = "成交值億" if "成交值億" in 今日 else "成交張數"
        滑卡(今日[~今日["代號"].str.startswith("0")].nlargest(15, 值欄)["代號"].tolist(), "左右滑看成交值前 15 檔")


def 晨報區():
    """開盤前晨報卡：昨晚美股、台積電 ADR、AI 盤前一句話、今天的行事曆、台股昨收，一張卡看完。"""
    現在 = pd.Timestamp.now(tz="Asia/Taipei")
    段落(f"MORNING // 開盤前晨報 {現在:%m/%d}（{'一二三四五六日'[現在.weekday()]}）")
    列 = []
    美 = 讀檔("讀取美股", _版本)
    if 美 is not None and len(美) >= 2:
        片 = []
        for 名 in ("費城半導體", "那斯達克", "S&P 500", "輝達", "台積電 ADR"):
            if 名 in 美:
                s2 = 美[名].dropna()
                if len(s2) >= 2:
                    幅 = (s2.iloc[-1] / s2.iloc[-2] - 1) * 100
                    片.append(f'{名} <span style="color:{漲跌色(幅)}">{幅:+.1f}%</span>')
        if 片:
            列.append(("🇺🇸", f"美股 {美.index[-1]:%m/%d}：" + "、".join(片)))
        if "VIX" in 美 and 美["VIX"].notna().any():
            v = float(美["VIX"].dropna().iloc[-1])
            列.append(("😨", f"VIX 恐慌指數 <b>{v:.1f}</b>" + ("（偏高，市場緊張）" if v >= 25 else "（平穩）" if v < 18 else "（中等）")))
    紀錄 = 大盤解讀紀錄(st.session_state.get("_解讀版本", 0))
    if 紀錄:
        盤前 = [v for k, v in sorted(紀錄.items()) if v.get("模式") in ("盤前", "夜盤")]
        if 盤前:
            最新 = 盤前[-1]
            句 = 一句話結論(最新.get("內容", ""))
            if 句:
                列.append(("🤖", f"AI {最新.get('模式', '')}解讀（{str(最新.get('時間', ''))[5:16]}）：{html.escape(句)}"))
    try:
        日 = 經濟日程資料(_版本, 1)
        今 = 日[pd.to_datetime(日["日期"]).dt.date == 現在.date()]
        if len(今):
            列.append(("📅", "今天：" + "；".join(html.escape(str(x)) for x in 今["事件"].head(4))))
    except Exception:
        pass
    if 加權 is not None and len(加權):
        r = 加權.iloc[-1]
        幅 = r["change"] / (r["close"] - r["change"]) * 100
        列.append(("🇹🇼", f'台股上一個交易日 {r["date"]:%m/%d}：加權 {r["close"]:,.0f}（<span style="color:{漲跌色(幅)}">{幅:+.2f}%</span>）'))
    if not 列:
        st.caption("晨報資料還沒準備好。")
        return
    st.markdown('<div class="must morning">' + "".join(f"<div><i>{a}</i><span>{b}</span></div>" for a, b in 列) + "</div>",
                unsafe_allow_html=True)
    st.caption("美股是台灣時間今天清晨收盤的漲跌；AI 盤前解讀每個交易日約 08:07 更新，也會傳 LINE。")


def 週報區():
    """一週成績單：本週大盤、最強／最弱產業、本週漲最多的大型股、外資本週動向，以及你的股票本週表現。"""
    日們 = sorted(指標["date"].unique())
    週一 = 最新日 - pd.Timedelta(days=最新日.weekday())
    本週 = [d for d in 日們 if d >= 週一]
    前 = [d for d in 日們 if d < 週一]
    if not 本週 or not 前:
        return
    段落(f"WEEKLY // 一週成績單 {pd.Timestamp(本週[0]):%m/%d}～{最新日:%m/%d}")
    基日 = 前[-1]
    基 = 指標[指標["date"] == 基日].set_index("代號")["收盤"]
    今 = 今日.set_index("代號")
    週幅 = (今["收盤"] / 基.reindex(今.index) - 1) * 100
    卡們 = []
    if 加權 is not None and len(加權):
        K = 加權.set_index("date")["close"]
        if 基日 in K.index:
            幅 = (K.iloc[-1] / K.loc[基日] - 1) * 100
            卡們.append(卡片("加權本週", f"{幅:+.2f}%", f"{K.loc[基日]:,.0f} → {K.iloc[-1]:,.0f}", 漲跌色(幅)))
    普 = 週幅[~今.index.str.startswith("0")].dropna()
    卡們.append(卡片("本週上漲家數", f"{(普 > 0).mean() * 100:.0f}%", f"{int((普 > 0).sum())} 漲 / {int((普 < 0).sum())} 跌", 漲跌色((普 > 0).mean() - .5)))
    每日 = 市場每日(_版本)
    if "外資" in 每日:
        外 = float(每日.loc[每日.index >= 週一, "外資"].sum())
        卡們.append(卡片("外資本週", f"{外:+,.0f} 億", "買賣超合計", 漲跌色(外)))
    卡片格(卡們)
    市值 = 今["收盤"] * 今["發行股數"]
    t = pd.DataFrame({"幅": 週幅, "市值": 市值, "產業": 今["產業"], "名稱": 今["名稱"]}).dropna()
    t = t[~t.index.str.startswith("0")]
    業 = t.groupby("產業").apply(lambda g: np.average(g["幅"], weights=g["市值"]) if g["市值"].sum() > 0 else np.nan).dropna()
    業 = 業[t.groupby("產業").size().reindex(業.index) >= 5].sort_values()
    大 = t.nlargest(150, "市值")
    行 = []
    if len(業) >= 6:
        行.append(("🏆", "最強產業：" + "、".join(f'{k} <span style="color:{漲跌色(v)}">{v:+.1f}%</span>' for k, v in 業.iloc[::-1][:3].items())))
        行.append(("🥶", "最弱產業：" + "、".join(f'{k} <span style="color:{漲跌色(v)}">{v:+.1f}%</span>' for k, v in 業[:3].items())))
    if len(大):
        行.append(("🚀", "大型股漲最多：" + "、".join(f'<a href="?s={c}" target="_self">{x["名稱"]}</a> <span style="color:{紅}">{x["幅"]:+.1f}%</span>'
                                              for c, x in 大.nlargest(3, "幅").iterrows())))
        行.append(("🪂", "大型股跌最多：" + "、".join(f'<a href="?s={c}" target="_self">{x["名稱"]}</a> <span style="color:{綠}">{x["幅"]:+.1f}%</span>'
                                              for c, x in 大.nsmallest(3, "幅").iterrows())))
    if 可編輯():
        try:
            我的 = [c for c in dict.fromkeys(list(庫存代號() or []) + [c for v in 自選股清單().values() for c in v]) if c in 週幅.index]
        except Exception:
            我的 = []
        if 我的:
            m = 週幅.reindex(我的).dropna().sort_values(ascending=False)
            if len(m):
                行.append(("⭐", f"你的股票本週：平均 {m.mean():+.1f}%；最好 {今.at[m.index[0], '名稱']} {m.iloc[0]:+.1f}%、"
                                f"最差 {今.at[m.index[-1], '名稱']} {m.iloc[-1]:+.1f}%"))
    if 行:
        st.markdown('<div class="must">' + "".join(f"<div><i>{a}</i><span>{b}</span></div>" for a, b in 行) + "</div>", unsafe_allow_html=True)
    st.caption("本週＝這週一到最新資料日，跟上週最後一個交易日收盤比；產業用市值加權、至少 5 檔才列入；大型股＝市值前 150 檔。"
               "想分享可以直接截圖這一塊。")


漲跌區間 = [(-99, -9.5, "跌停"), (-9.5, -7, "−7<br>−9.5"), (-7, -5, "−5<br>−7"), (-5, -3, "−3<br>−5"), (-3, -1, "−1<br>−3"), (-1, -1e-9, "0<br>−1"),
          (-1e-9, 1e-9, "平盤"), (1e-9, 1, "0<br>+1"), (1, 3, "+1<br>+3"), (3, 5, "+3<br>+5"), (5, 7, "+5<br>+7"), (7, 9.5, "+7<br>+9.5"), (9.5, 99, "漲停")]


def 漲跌分布表(表):
    """把每檔股票的漲跌幅分到 13 個區間（跌停…平盤…漲停），回傳 [(標籤, 家數, 中點)]。ETF 不算。"""
    幅 = 表.loc[~表["代號"].str.startswith("0") & (表["成交張數"] > 0), "漲跌幅"].dropna()
    列 = []
    for 低, 高, 名 in 漲跌區間:
        if 名 == "平盤":
            n = int((幅.abs() < 1e-9).sum())
        elif 高 <= 0:
            n = int(((幅 > 低) & (幅 <= 高)).sum()) if 低 > -99 else int((幅 <= 高).sum())
        else:
            n = int(((幅 >= 低) & (幅 < 高)).sum()) if 高 < 99 else int((幅 >= 低).sum())
        列.append((名, n, (max(低, -10) + min(高, 10)) / 2))
    return 列, 幅


def 漲跌分布區():
    """市場溫度帶：全部股票今天的漲跌幅分布。一眼看出是「普漲」「普跌」還是「少數權值股撐盤」。"""
    段落("SPREAD // 漲跌溫度帶")
    列, 幅 = 漲跌分布表(今日)
    if not len(幅):
        st.caption("資料不足。")
        return
    名們 = [x[0] for x in 列]
    數們 = [x[1] for x in 列]
    # 顏色：越往兩端越深（綠跌、紅漲），平盤灰
    色們 = ["#5A5A5A" if i == 6 else
            (f"rgba(255,59,92,{.32 + .68 * (i - 7) / 5:.2f})" if i > 6 else f"rgba(0,214,143,{.32 + .68 * (5 - i) / 5:.2f})")
            for i in range(len(列))]
    上, 下 = int((幅 > 0).sum()), int((幅 < 0).sum())
    全 = len(幅)
    卡片格([卡片("上漲比例", f"{上 / 全 * 100:.0f}%", f"{上} 家", 紅), 卡片("中位數漲跌", f"{幅.median():+.2f}%", "一半股票漲超過這個數", 漲跌色(幅.median())),
           卡片("漲停／跌停", f"{數們[-1]} / {數們[0]}", "約略計算（≥9.5%）", "#EDEDED")])
    圖 = go.Figure(go.Bar(x=名們, y=數們, marker=dict(color=色們, line=dict(width=0), cornerradius=4),
                          text=[f"{n:,}" if n else "" for n in 數們], textposition="outside", cliponaxis=False,
                          textfont=dict(color="#BDBDBD", size=13 if 手機 else 11),
                          customdata=[x.replace("<br>", "～") for x in 名們], hovertemplate="%{customdata}%：%{y:,} 家<extra></extra>"))
    圖表外觀(圖, 260 if 手機 else 240).update_layout(bargap=.18, hovermode="closest", showlegend=False,
                                                yaxis=dict(visible=False), xaxis=dict(tickangle=0, tickfont=dict(size=11 if 手機 else 11), gridcolor="rgba(0,0,0,0)"),
                                                margin=dict(l=4, r=4, t=24, b=4))
    st.plotly_chart(圖, width="stretch", config={"displayModeBar": False})
    判 = ("普漲：大部分股票都在漲" if 上 / 全 > .65 else "普跌：大部分股票都在跌" if 下 / 全 > .65
         else "漲跌互見：個股表現分歧")
    尾 = 數們[-1] + 數們[-2] - 數們[0] - 數們[1]
    st.caption(f"{判}；大漲（7% 以上）比大跌多 {尾:+d} 家。每根柱子＝漲跌幅落在那個區間（%）的股票家數，越往兩邊顏色越亮代表漲跌越大；只算上市櫃普通股，不含 ETF。")


首頁區塊 = ["晨報", "必知", "大盤走勢", "30秒", "市場", "分布", "狀態", "價位", "AI解讀", "焦點", "國際", "總經", "連動", "月曆", "流向", "滑卡", "週報", "權值", "資金", "跌深", "止跌", "護盤", "選擇權", "情緒", "水位", "族群", "行事曆", "事件", "輝達", "延續", "排行"]


新手區塊 = ["大盤走勢", "30秒", "市場", "分布", "流向", "狀態", "水位", "AI解讀", "焦點", "排行"]
手機區塊 = ["必知", "大盤走勢", "滑卡", "分布", "30秒", "流向", "月曆", "焦點"]
版面們 = {"手機": "今天必須知道＋大盤 K 線＋滑卡＋漲跌溫度帶＋三十秒看盤＋法人資金流向＋漲跌月曆＋焦點股，字大好讀", "新手": "只看 10 個重點區塊", "完整": "全部區塊", "自訂": "自己挑、自己排順序"}
預設版面 = "手機" if 手機 else "新手"
_時 = pd.Timestamp.now(tz="Asia/Taipei")
if (_時.hour, _時.minute) < (9, 30) and _時.weekday() < 5:  # 開盤前：晨報放最上面
    手機區塊 = ["晨報"] + 手機區塊
else:
    手機區塊 = 手機區塊[:-1] + ["晨報"] + 手機區塊[-1:]
if _時.weekday() >= 5 or (_時.weekday() == 4 and _時.hour >= 14):  # 週五收盤後到週日：一週成績單放必知後面
    手機區塊.insert(手機區塊.index("大盤走勢") + 1, "週報")


def 讀版面():
    """網址 layout=新手／完整／自訂:區塊1,區塊2…；舊的 hide= 書籤當成自訂。"""
    值 = st.query_params.get("layout", "").replace("加權指數", "大盤走勢")  # 舊書籤的區塊名稱
    if 值 in ("手機", "新手", "完整"):
        return 值, None
    if 值.startswith("自訂:"):
        return "自訂", [x for x in 值[3:].split(",") if x in 首頁區塊]
    隱 = [x for x in st.query_params.get("hide", "").replace("加權指數", "大盤走勢").split(",") if x in 首頁區塊]
    if 隱:
        return "自訂", [x for x in 首頁區塊 if x not in 隱]
    return 預設版面, None  # 預設新手版面；手機模式預設手機版面（只看重點）


舊模式, 舊順序 = 讀版面()
with st.expander(f"⚙️ 首頁版面：{舊模式}"):
    模式 = st.segmented_control("版面", list(版面們), default=舊模式, key="首頁版面",
                              format_func=lambda m: f"{m}（{版面們[m]}）") or 舊模式
    if 模式 == "自訂":
        顯示 = st.multiselect("要顯示的區塊（照點選的順序排列）", 首頁區塊, key="首頁區塊順序",
                             default=舊順序 if 舊順序 is not None else 首頁區塊)
        st.caption("想把某個區塊移到前面：先按 × 移除其他區塊，再照想要的順序點回來。")
    else:
        顯示 = {"手機": 手機區塊, "新手": 新手區塊}.get(模式, 首頁區塊)
    st.caption("設定記在網址裡，把這個網址加入書籤或手機主畫面就會保留。")
新值 = "自訂:" + ",".join(顯示) if 模式 == "自訂" else 模式
舊值 = "自訂:" + ",".join(舊順序) if 舊模式 == "自訂" else 舊模式
if 新值 != 舊值 or "hide" in st.query_params:
    if 新值 == 預設版面:
        st.query_params.pop("layout", None)
    else:
        st.query_params["layout"] = 新值
    st.query_params.pop("hide", None)
def _國際():
    try:
        國際行情()
    except Exception:
        st.caption("國際行情暫時無法顯示。")
區塊函式 = {"必知": 必知區, "分布": 漲跌分布區, "月曆": 漲跌月曆區, "流向": 資金流向區, "滑卡": 滑卡區, "晨報": 晨報區, "週報": 週報區, "30秒": 三十秒卡, "市場": 市場卡片, "狀態": 狀態區, "價位": 關鍵價位區, "AI解讀": AI解讀區, "焦點": 焦點區, "國際": _國際, "總經": 總經區, "連動": 連動區,
         "大盤走勢": 加權圖 if 加權 is not None and len(加權) > 1 else None, "權值": 權值區, "資金": 資金面區, "跌深": 跌深區, "止跌": 止跌訊號區, "護盤": 護盤區, "選擇權": 選擇權區, "事件": 事件區, "輝達": 輝達週區, "延續": 反彈延續區,
         "情緒": 情緒區, "水位": 資金水位區, "族群": 族群熱力圖, "行事曆": 行事曆區, "排行": 排行區}
要畫 = [x for x in 顯示 if 區塊函式.get(x)]
if len(要畫) > 3 and not (手機 and 模式 == "手機"):  # 首頁很長，上方放一排快速跳轉
    st.markdown('<div class="jump">' + "".join(f'<a href="#h-{x}" target="_self">{x}</a>' for x in 要畫)
                + "</div>", unsafe_allow_html=True)


def 錨(區塊):
    """首頁有顯示這個區塊才回傳跳轉連結（卡片點了會捲到那裡）。"""
    return f"#h-{區塊}" if 區塊 in 要畫 else None


@st.fragment
def 區塊片段(名):
    """每個區塊各自獨立：在區塊裡切換選項只重畫這一塊（以前整頁重跑約 3 秒），某一塊出錯也不影響其他區塊。"""
    try:
        區塊函式[名]()
    except Exception as e:
        import traceback
        st.caption(f"「{名}」區塊暫時無法顯示（{type(e).__name__}），已記錄，其他區塊不受影響。")
        threading.Thread(target=engine.記錄錯誤, args=(_設定(), f"01 首頁 {名}", e, traceback.format_exc()), daemon=True).start()
    if st.session_state.get("要跳轉"):  # 點了表格裡的股票，要整頁重跑才會切到個股查詢
        st.rerun(scope="app")


大事倒數條()
盤中即時條()
for x in 要畫:
    st.markdown(f'<div class="anchor" id="h-{x}"></div>', unsafe_allow_html=True)
    區塊片段(x)


if 模式 == "手機":
    def _換版面(值):
        st.session_state["首頁版面"] = 值
    段落("MORE // 想看更多")
    a, b = st.columns(2)
    a.button("🔰 新手版首頁（9 區塊）", on_click=_換版面, args=("新手",), key="換新手版面", width="stretch")
    b.button("📚 完整首頁（全部區塊）", on_click=_換版面, args=("完整",), key="換完整版面", width="stretch")
    st.caption("手機版首頁只放最重要的五塊；其他頁面（個股查詢、我的股票…）從上方選單進入，字體一樣會放大。")
