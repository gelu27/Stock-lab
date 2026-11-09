# 08 回測：由 app.py 的 執行頁面() 在同一個命名空間執行，可直接用 app.py 的共用函式與資料。
# ---------- 07 回測 ----------
def 績效卡(績, 基準名, 基準鍵):
    卡們 = [
        卡片("總報酬", f"{績['總報酬(%)']:+.1f}%", "", 漲跌色(績["總報酬(%)"])),
        卡片("年化報酬", f"{績['年化報酬(%)']:+.1f}%", "", 漲跌色(績["年化報酬(%)"])),
        卡片("最大回撤", f"{績['最大回撤(%)']:.1f}%", "", 綠),
        卡片("勝率", f"{績['勝率(%)']:.0f}%", f"{績['交易次數']} 筆交易"),
        卡片("夏普值", f"{績['夏普值']:.2f}"),
    ]
    if 基準鍵 in 績:
        卡們.append(卡片(基準名, f"{績[基準鍵]:+.1f}%", "買進持有", 漲跌色(績[基準鍵])))
    if 基準鍵 != "0050 同期報酬(%)" and "0050 同期報酬(%)" in 績:
        卡們.append(卡片("0050 同期", f"{績['0050 同期報酬(%)']:+.1f}%", "買進持有", 漲跌色(績["0050 同期報酬(%)"])))
    if "交易成本(元)" in 績:
        卡們.append(卡片("手續費＋證交稅", f"{績['交易成本(元)']:,.0f}", "元"))
    卡片格(卡們)


回測存檔 = "backtest_presets.json"


def 回測條件存取():
    """把目前的選股條件與回測參數存成一組名字，下次一鍵套用（存在 ai-reports 分支，需密碼）。"""
    if "回測條件組" not in st.session_state:
        try:
            st.session_state["回測條件組"] = engine.讀取設定檔(_設定(), 回測存檔) or {}
        except Exception:
            st.session_state["回測條件組"] = {}
    組們 = st.session_state["回測條件組"]
    with st.expander(f"💾 常用條件（已存 {len(組們)} 組）"):
        if 組們:
            a, b, c = st.columns([3, 1, 1])
            選 = a.selectbox("已存的條件", list(組們), key="回測條件選", label_visibility="collapsed")
            if b.button("套用", key="回測條件套用"):
                st.session_state["_套用回測條件"] = 組們[選]
                st.rerun()
            if 可編輯() and c.button("🗑 刪除", key="回測條件刪"):
                新 = {k: v for k, v in 組們.items() if k != 選}
                if 回測條件存檔(新):
                    st.rerun()
        if not 可編輯():
            st.caption("存新條件需要先在「02 / 我的股票」輸入密碼解鎖；已存的條件可以直接套用。")
            return
        a, b = st.columns([3, 1])
        名 = a.text_input("名稱", placeholder="例如：高殖利率＋投信連買", key="回測條件名", label_visibility="collapsed").strip()
        if b.button("存目前條件", key="回測條件存") and 名:
            內容 = {k: (list(v) if isinstance(v, tuple) else v) for k, v in st.session_state.items()
                  if str(k).startswith(("條_", "回_")) and isinstance(v, (bool, int, float, str, list, tuple))}
            if 回測條件存檔({**組們, 名: 內容}):
                st.rerun()


def 回測條件存檔(組們):
    try:
        engine.儲存設定檔(_設定(), 回測存檔, 組們, "更新回測常用條件")
        st.session_state["回測條件組"] = 組們
        st.toast("已儲存")
        return True
    except Exception as e:
        st.error(f"存檔失敗：{e}")
        return False


def 套用回測條件():
    組 = st.session_state.pop("_套用回測條件", None)
    if not 組:
        return
    for k, v in 組.items():
        if k in ("條_市場",) or not isinstance(v, list):
            st.session_state[k] = v
        else:
            st.session_state[k] = tuple(v)  # 滑桿區間
    st.session_state["_條件記憶"] = {k: v for k, v in st.session_state.items() if str(k).startswith("條_")}


套用回測條件()
回測分頁 = st.tabs(["組合回測", "個股回測", "💰 定期定額"])
with 回測分頁[0]:
    回測條件存取()
    with st.expander("⚙️ 選股條件（跟 04 / 選股 共用）"):
        條件, 範本 = 選股條件區()
    st.caption("規則：每期最後一個交易日收盤後用上面的條件選股，隔日收盤價買進前 N 檔，每檔投入總資產 ÷ N；"
               "沒入選的賣出；觸發停損停利當天收盤賣出。已計入手續費 0.1425%（可打折）與證交稅（股票 0.3%、ETF 0.1%）。"
               "月營收與 EPS 條件只有最新一期，回測時不套用。")
    最早 = engine.資料起訖()[0].date()
    a, b, c, d, e = st.columns(5)
    開始 = a.date_input("開始日期", max(最早, 最新日.date() - dt.timedelta(days=730)), min_value=最早,
                     max_value=最新日.date())
    結束 = b.date_input("結束日期", 最新日.date(), min_value=最早, max_value=最新日.date())
    調倉 = c.selectbox("調倉頻率", ["每月", "每週", "每日"], key="回_調倉")
    檔數 = d.number_input("最多持有檔數", 1, 50, 10, key="回_檔數")
    資金 = e.number_input("初始資金", 100_000, 100_000_000, 1_000_000, step=100_000, key="回_資金")
    a, b, c = st.columns(3)
    停損 = a.number_input("停損 %（0 代表不設）", 0.0, 50.0, 10.0, step=1.0, key="回_停損")
    停利 = b.number_input("停利 %（0 代表不設）", 0.0, 500.0, 0.0, step=5.0, key="回_停利")
    折扣 = c.number_input("手續費折扣（1 = 不打折，0.28 = 2.8 折）", 0.1, 1.0, 1.0, step=0.05, key="回_折扣")

    if st.button("▶ 開始回測"):
        with st.spinner("回測計算中…"):
            每日, 調倉日表 = engine.回測資料(開始, 結束, 調倉)
            st.session_state["回測"] = engine.回測(
                每日, 條件, pd.Timestamp(開始), pd.Timestamp(結束), 檔數, 調倉,
                停損 or None, 停利 or None, 資金, 選股資料=調倉日表, 手續費折扣=折扣)
            del 每日, 調倉日表
            engine.釋放記憶體()

    報告 = st.session_state.get("回測")
    if 報告 is None:
        st.info("設定好上面的選股條件與參數後，按「開始回測」。")
    else:
        績效卡(報告["績效"], "0050 同期", "0050 同期報酬(%)")

        段落("EQUITY // 資產曲線")
        曲線 = 報告["曲線"]
        圖 = go.Figure(go.Scatter(x=曲線.index, y=(曲線 - 1) * 100, name="我的策略",
                                  line=dict(color=青, width=2)))
        if 報告["基準"] is not None:
            圖.add_trace(go.Scatter(x=報告["基準"].index, y=(報告["基準"] - 1) * 100, name="0050",
                                    line=dict(color=灰, width=1, dash="dot")))
        圖.update_yaxes(ticksuffix="%")
        st.plotly_chart(圖表外觀(圖), width="stretch")

        段落("DRAWDOWN // 回撤")
        回撤 = (曲線 / 曲線.cummax() - 1) * 100
        圖 = go.Figure(go.Scatter(x=回撤.index, y=回撤, fill="tozeroy", line=dict(color=綠, width=1),
                                  fillcolor="rgba(0,214,143,0.15)", name="回撤"))
        圖.update_yaxes(ticksuffix="%")
        st.plotly_chart(圖表外觀(圖, 200), width="stretch")

        段落("TRADES // 交易明細")
        if 報告["交易"].empty:
            st.write("這段期間沒有任何股票符合條件。")
        else:
            表格(上色(報告["交易"]), hide_index=True, width="stretch", height=360)

with 回測分頁[1]:
    st.caption("訊號在收盤後產生，隔一個交易日以收盤價成交；已計入手續費（可打折）與證交稅，價格使用還原股價。")
    全部選項 = (今日["代號"] + " " + 今日["名稱"]).tolist()
    預設 = next((i for i, v in enumerate(全部選項) if v.startswith("2330 ")), 0)
    a, b = st.columns([2, 1])
    標的 = a.selectbox("股票", 全部選項, index=預設, key="個股標的")
    策略 = b.selectbox("策略", list(engine.個股策略), index=1, key="個股策略")
    st.caption(engine.個股策略[策略])
    a, b, c, d = st.columns(4)
    開始2 = a.date_input("開始日期", max(最早, 最新日.date() - dt.timedelta(days=730)), min_value=最早,
                      max_value=最新日.date(), key="個股開始")
    結束2 = b.date_input("結束日期", 最新日.date(), min_value=最早, max_value=最新日.date(), key="個股結束")
    短 = c.number_input("短均線（日）", 2, 60, 5, key="短均線")
    長 = d.number_input("長均線（日）", 5, 240, 20, key="長均線")
    a, b, c, d = st.columns(4)
    RSI下 = a.number_input("RSI 買進（低於）", 5, 50, 30, key="RSI下")
    RSI上 = b.number_input("RSI 賣出（高於）", 50, 95, 70, key="RSI上")
    停損2 = c.number_input("停損 %（0 不設）", 0.0, 50.0, 0.0, step=1.0, key="個股停損")
    停利2 = d.number_input("停利 %（0 不設）", 0.0, 500.0, 0.0, step=5.0, key="個股停利")
    折扣2 = st.number_input("手續費折扣（1 = 不打折，0.28 = 2.8 折）", 0.1, 1.0, 1.0, step=0.05, key="個股折扣")
    if st.button("▶ 開始個股回測"):
        st.session_state["個股回測"] = engine.個股回測(
            個股全史(標的.split()[0], _版本), 標的.split()[0], pd.Timestamp(開始2), pd.Timestamp(結束2), 策略, 短, 長, RSI下, RSI上,
            停損2 or None, 停利2 or None, 手續費折扣=折扣2, 大盤=個股全史("0050", _版本))
    報告 = st.session_state.get("個股回測")
    if 報告 is None:
        st.info("選好股票和策略後，按「開始個股回測」。")
    else:
        績效卡(報告["績效"], "買進持有", "買進持有(%)")
        段落("EQUITY // 資產曲線與買賣點")
        價 = 報告["價格"]
        圖 = go.Figure(go.Scatter(x=報告["曲線"].index, y=(報告["曲線"] - 1) * 100, name="策略",
                                  line=dict(color=青, width=2)))
        圖.add_trace(go.Scatter(x=報告["基準"].index, y=(報告["基準"] - 1) * 100, name="買進持有",
                                line=dict(color=灰, width=1, dash="dot")))
        if 報告.get("大盤") is not None:
            圖.add_trace(go.Scatter(x=報告["大盤"].index, y=(報告["大盤"] - 1) * 100, name="0050",
                                    line=dict(color="#FFB020", width=1, dash="dash")))
        交易 = 報告["交易"]
        if not 交易.empty:
            對照 = (報告["曲線"] - 1) * 100
            進 = pd.to_datetime(交易["進場日"])
            出 = pd.to_datetime(交易["出場日"].dropna())
            圖.add_trace(go.Scatter(x=進, y=對照.reindex(進).values, mode="markers", name="買進",
                                    marker=dict(color=紅, size=9, symbol="triangle-up")))
            圖.add_trace(go.Scatter(x=出, y=對照.reindex(出).values, mode="markers", name="賣出",
                                    marker=dict(color=綠, size=9, symbol="triangle-down")))
        圖.update_yaxes(ticksuffix="%")
        st.plotly_chart(圖表外觀(圖), width="stretch")
        段落("TRADES // 交易明細")
        if 交易.empty:
            st.write("這段期間沒有產生任何交易。")
        else:
            表格(上色(交易), hide_index=True, width="stretch")
with 回測分頁[2]:
    st.caption("每個月固定日期買進同一檔股票或 ETF（可買零股），現金股利自動再投入，看存到現在變多少；同時跟「同一筆總金額第一天全部買進」比。")
    全部選項 = (今日["代號"] + " " + 今日["名稱"]).tolist()
    a, b = st.columns([2, 1])
    標 = a.selectbox("股票／ETF", 全部選項, index=next((i for i, v in enumerate(全部選項) if v.startswith("0050 ")), 0), key="定額標的")
    每月 = b.number_input("每月扣款（元）", 1000, 1_000_000, 10000, step=1000, key="定額金額")
    a, b, c, d = st.columns(4)
    開 = a.date_input("開始", max(最早, 最新日.date() - dt.timedelta(days=365 * 5)), min_value=最早, max_value=最新日.date(), key="定額開始")
    結 = b.date_input("結束", 最新日.date(), min_value=最早, max_value=最新日.date(), key="定額結束")
    日 = c.number_input("每月幾號扣款", 1, 28, 6, key="定額日", help="遇到假日就順延到下一個交易日")
    折 = d.number_input("手續費折扣", 0.1, 1.0, 1.0, step=0.05, key="定額折扣", help="定期定額多半是每筆 1 元起或固定低手續費，可填較低折扣")
    代 = 標.split()[0]
    曲, 摘 = engine.定期定額(個股全史(代, _版本), 每月, 日, pd.Timestamp(開), pd.Timestamp(結), 折)
    if 曲 is None or not 摘["扣款次數"]:
        st.info("這段期間沒有資料。")
    else:
        卡片格([
            卡片("總投入", f"{摘['總投入']:,.0f}", f"扣款 {摘['扣款次數']} 次"),
            卡片("現在市值", f"{摘['市值']:,.0f}", f"報酬 {摘['報酬率%']:+.1f}%", 漲跌色(摘["報酬率%"])),
            卡片("年化報酬（XIRR）", f"{摘['年化%']:+.1f}%", "考慮每筆錢投入的時間", 漲跌色(摘["年化%"])),
            卡片("一次全買", f"{摘['一次投入市值']:,.0f}", f"報酬 {摘['一次投入報酬率%']:+.1f}%、年化 {摘['一次投入年化%']:+.1f}%",
                 漲跌色(摘["一次投入報酬率%"])),
            卡片("最大回檔", f"{摘['最大回檔%']:.1f}%", f"一次全買 {摘['一次投入最大回檔%']:.1f}%", 綠),
        ])
        圖 = go.Figure([go.Scatter(x=曲.index, y=曲["投入"], name="累積投入", line=dict(color=灰, width=1, shape="hv")),
                        go.Scatter(x=曲.index, y=曲["市值"], name="定期定額市值", line=dict(color=青, width=2)),
                        go.Scatter(x=曲.index, y=曲["一次投入"], name="第一天一次全買", line=dict(color="#FFC24B", width=1.2, dash="dot"))])
        圖.update_layout(hovermode="x unified", legend=dict(orientation="h", y=1.12))
        圖.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
        st.plotly_chart(圖表外觀(圖, 340), width="stretch")
        st.caption("用還原股價計算（含息、分割與減資不會算錯），扣款當天收盤價成交，買進手續費最低 1 元，還沒賣出所以不扣證交稅。"
                   "一次全買通常報酬較高但回檔也較大；定期定額的好處是分散進場時間、不用猜高低點。歷史結果不代表未來。")


段落("RULES // 教科書規則實測（基礎撐壓講義、跌深融資說法）")
_實 = 讀檔("讀取規則實測", _版本)
if not _實:
    st.info("規則實測每月在 GitHub 更新時重算一次，下次資料更新後就會出現。")
else:
    _表 = pd.DataFrame(_實["規則"]).drop(columns="鍵")
    _表["結論"] = _表["結論"].map({"成立": "✅ 成立", "相反": "❌ 相反", "沒差": "➖ 沒差", "偏弱": "🟢 偏弱", "偏強": "🔴 偏強"}).fillna(_表["結論"])
    表格(_表.rename(columns={"講義說法": "常見說法"})[["規則", "常見說法", "結論", "天數", "筆數", "平均報酬%", "勝率%", "超額%"]], hide_index=True, width="stretch",
         column_config={"超額%": st.column_config.NumberColumn(format="%+.2f"), "平均報酬%": st.column_config.NumberColumn(format="%+.2f"),
                        "筆數": st.column_config.NumberColumn(format="%d")})
    st.caption(f"樣本：{_實['起']}～{_實['迄']} 上市櫃普通股、近 20 日平均成交額 5,000 萬以上，共 {_實['樣本']:,} 筆（{_實['計算日']} 計算，約每月重算）。"
               "超額＝之後 N 日報酬減去同一天所有樣本的平均，正的才代表真的比較好；差距不到 ±0.3% 算「沒差」。"
               "沒有扣手續費，也不代表未來。這段期間台股是大多頭，追強勢的規則本來就占優勢。")


段落("CLAIMS // 說法查核紀錄：網紅、Podcast 的說法對不對")
_查 = engine.讀取說法查核()
if len(_查):
    _來源們 = list(dict.fromkeys(_查["來源"][::-1]))
    _選 = st.segmented_control("來源", _來源們, default=_來源們[0], key="查核來源") or _來源們[0]
    _顯 = _查[_查["來源"] == _選]
    _計 = _顯["判定"].str.extract(r"^(相符|大致相符|不成立|查不到)")[0].value_counts()
    st.markdown(f"**{_選}**（{_顯['日期'].iloc[0]} 查核）：" + "、".join(f"{k} {v} 項" for k, v in _計.items()))
    _圖示 = lambda x: ("✅ " if x.startswith("相符") else "🟡 " if x.startswith("大致") else "❌ " if x.startswith("不成立") else "❔ ") + x
    表格(_顯.assign(判定=_顯["判定"].map(_圖示))[["編號", "說法", "查到的事實", "判定"]], hide_index=True, width="stretch")
    st.caption("數字用網站資料庫與新聞核對，回測細節在各頁的 ℹ️ 說明裡。新的查核在 GitHub 的 data/claims.csv 加列（來源, 日期, 編號, 說法, 查到的事實, 判定）。")


段落("BACKLOG // 合約負債全市場驗證：預收款能不能領先股價與營收")
_約 = 讀檔("讀取合約負債驗證", _版本)
if not _約 or not _約.get("結果"):
    st.info("合約負債驗證每月在 GitHub 更新時重算一次，歷史資料補齊後就會出現。")
else:
    _表 = pd.DataFrame(_約["結果"]).drop(columns="每季", errors="ignore")
    表格(_表[["指標", "高減低%", "t值", "勝率%", "季數", "筆數", "高組平均%", "低組平均%"]], hide_index=True, width="stretch",
         column_config={c: st.column_config.NumberColumn(format="%+.2f") for c in ("高減低%", "高組平均%", "低組平均%")})
    _主 = next((r for r in _約["結果"] if r["指標"] == "合約負債年增率"), None)
    if _主 and _主.get("每季"):
        _季 = pd.Series(_主["每季"])
        _圖 = go.Figure(go.Bar(x=_季.index, y=_季.values, marker_color=[紅 if v > 0 else 綠 for v in _季.values]))
        _圖.update_layout(yaxis_title="高組減低組（%）")
        st.plotly_chart(圖表外觀(_圖, 240), width="stretch")
    _預 = _約.get("營收預告") or {}
    if _預:
        _中 = _預.get("各組未來兩季營收年增中位數%", {})
        st.markdown(f"**能不能預告營收**：合約負債年增率分三組，未來兩季營收年增中位數 低 {_中.get('低', '—')}%、中 {_中.get('中', '—')}%、"
                    f"高 {_中.get('高', '—')}%；扣掉近兩季營收年增的影響後，偏相關 {_預['偏相關']:+.2f}（{_預['筆數']:,} 筆）。")
    st.caption(f"樣本：{_約['起']}～{_約['迄']}，合約負債至少是近四季營收 5% 的上市櫃公司 {_約['家數']:,} 家；每季在財報期限"
               f"（季底後 45 天、第四季 90 天）隔天買進、持有 {_約['天數']} 個交易日，超額＝減掉同一季所有樣本平均。"
               f"每季依指標分三組，比較高組減低組。t 值 2 以上才算穩定（目前結論：{_約['結論']}，{_約['計算日']} 計算）。"
               "較早的季度只有流動部分的合約負債（FinMind），沒有扣手續費，也不代表未來。")


段落("EVENT // 事件反應表：消息出來後股價怎麼走")
事件存檔 = "events.json"


@st.cache_data(ttl=3600, show_spinner=False, max_entries=30)
def 事件計算(代號們, 前置日, 事件日, 版本鍵):
    起 = pd.Timestamp(min(d for d in (前置日, 事件日) if d)) - pd.Timedelta(days=15)
    價 = engine.讀取資料庫(代號=list(代號們), 起日=起)
    指 = engine.讀取指數K線("TAIEX")
    if 價 is None or 指 is None:
        return pd.DataFrame()
    return engine.事件反應(價, 指, 代號們, 事件日, 前置日)


def 事件清單():
    if "事件清單" not in st.session_state:
        try:
            st.session_state["事件清單"] = engine.讀取設定檔(_設定(), 事件存檔) or {}
        except Exception:
            st.session_state["事件清單"] = {}
    已存 = st.session_state["事件清單"]
    return {**{x["名稱"]: x for x in engine.事件範本}, **已存}


def 百分比上色(表):
    欄 = [c for c in 表.columns if str(c).endswith("%")]
    return 表.style.map(lambda v: f"color:{漲跌色(v)}" if pd.notna(v) else "", subset=欄).format(
        {c: "{:+.2f}" for c in 欄}, na_rep="—")


def 拆代號(文字):
    return tuple(dict.fromkeys(c for c in re.split(r"[\s,、，]+", str(文字)) if c))


_事件們 = 事件清單()
_選 = st.selectbox("事件", ["（自己輸入）"] + list(_事件們), index=1 if _事件們 else 0, key="事件選")
_預 = _事件們.get(_選, {})
a, b = st.columns([2, 3])
_名 = a.text_input("事件名稱", _預.get("名稱", ""), key=f"事件名_{_選}")
_碼 = b.text_input("股票代號（用逗號分開）", _預.get("代號", "2330"), key=f"事件碼_{_選}")
a, b, c = st.columns(3)
_有前置 = c.checkbox("媒體有先報導", bool(_預.get("前置日")), key=f"事件有前置_{_選}")
_事件日 = a.date_input("反應日（盤後公告填隔天）", pd.Timestamp(_預.get("事件日", 最新日)).date(),
                      min_value=engine.資料起訖()[0].date(), max_value=最新日.date(), key=f"事件日_{_選}")
_前置日 = b.date_input("媒體先報導日", pd.Timestamp(_預.get("前置日") or _事件日).date(),
                      min_value=engine.資料起訖()[0].date(), max_value=最新日.date(), key=f"事件前置_{_選}",
                      disabled=not _有前置)
if _預.get("說明"):
    st.caption(_預["說明"])
_代們 = 拆代號(_碼)
if _代們:
    _結 = 事件計算(_代們, _前置日.isoformat() if _有前置 else None, _事件日.isoformat(), _版本)
    if _結.empty:
        st.caption("這些代號在資料庫裡找不到那段期間的股價。")
    else:
        _欄 = [c for c in ["代號", "名稱", "前置日漲跌%", "前置日超額%", "事件日漲跌%", "事件日超額%", "後1日漲跌%",
                          "後5日漲跌%", "後5日超額%", "後20日漲跌%", "後20日超額%"] if c in _結.columns]
        表格(百分比上色(_結[_欄]), hide_index=True, width="stretch")
        st.caption("漲跌＝那一天（或之後 N 個交易日）的漲跌幅；超額＝再減掉加權指數同期漲跌，正的才是真的比大盤強。"
                   "「後 N 日」從反應日收盤起算，所以不含反應日當天；已還原除權息。資料不夠 N 天的留空。")
    if 可編輯() and _名 and st.button("💾 存成事件（下面的統計會一起算）", key="事件存"):
        新 = {**st.session_state.get("事件清單", {}),
             _名: {"名稱": _名, "代號": ",".join(_代們), "前置日": _前置日.isoformat() if _有前置 else "",
                  "事件日": _事件日.isoformat()}}
        try:
            engine.儲存設定檔(_設定(), 事件存檔, 新, "更新事件反應清單")
            st.session_state["事件清單"] = 新
            st.toast("已儲存")
            st.rerun()
        except Exception as e:
            st.error(f"存檔失敗：{e}")
    elif not 可編輯():
        st.caption("存新事件需要先在「02 / 我的股票」輸入密碼解鎖。")

段落("LEAK // 消息先走？媒體先報 vs 正式公告 vs 利多出盡")
_結們 = []
for _n, _x in _事件們.items():
    _c = 拆代號(_x.get("代號", ""))
    if _c and _x.get("事件日"):
        try:
            _結們.append((_n, 事件計算(_c, _x.get("前置日") or None, _x["事件日"], _版本)))
        except Exception:
            pass
_統, _總 = engine.消息先走統計(_結們)
if _統.empty:
    st.caption("還沒有可以統計的事件，先在上面存幾個事件。")
else:
    _卡 = [卡片("事件數", f"{_總['事件數']}")]
    if "前置日超額%" in _總:
        _卡.append(卡片("媒體先報那天", f"{_總['前置日超額%']:+.2f}%", "平均超額", 漲跌色(_總["前置日超額%"])))
    _卡.append(卡片("正式公告反應日", f"{_總.get('事件日超額%', np.nan):+.2f}%", "平均超額", 漲跌色(_總.get("事件日超額%", 0))))
    if "後20日超額%" in _總:
        _卡.append(卡片("公告後 20 日", f"{_總['後20日超額%']:+.2f}%", "平均超額", 漲跌色(_總["後20日超額%"])))
    if "利多出盡比例%" in _總:
        _卡.append(卡片("利多出盡比例", f"{_總['利多出盡比例%']:.0f}%", "公告後 20 日輸給大盤的事件比例"))
    卡片格(_卡)
    表格(百分比上色(_統), hide_index=True, width="stretch")
    _先 = (f"有媒體先報的 {_總['有前置日事件數']} 個事件中，{_總['先走事件數']} 個在媒體先報那天的反應比正式公告還大。"
          if _總.get("有前置日事件數") else "")
    st.caption(_先 + "每個事件是裡面所有股票的平均超額。事件太少時只能當參考，至少累積 10 個以上再看比例比較有意義；"
               "台積電與 Sony 合資是內建範例（8/10 媒體先報、8/11 盤後公告）。")


段落("CRASH // 加權單日大跌之後：多久收復？（緯來吳采妮 2026-11）")
_K大 = 指數K線("TAIEX", _版本)
_大 = engine.大跌日收復表(_K大) if _K大 is not None else pd.DataFrame()
if not len(_大):
    st.caption("指數資料還不夠。")
else:
    _統大 = engine.大跌日統計(_大)
    _卡 = [卡片("單日跌 3% 以上", f"{_統大['次數']} 次", f"已收復 {_統大['已收復']} 次"),
          卡片("收復天數中位數", f"{_統大['收復天數中位數']:.0f} 個交易日" if _統大["收復天數中位數"] else "—", "收盤回到大跌前一天")]
    for _n in (20, 60):
        _s = _統大.get(f"{_n}日", {})
        if _s.get("次數"):
            _卡.append(卡片(f"{_n} 日後", f"{_s['平均%']:+.1f}%", f"上漲 {_s['上漲機率%']}%（{_s['次數']} 次）", 漲跌色(_s["平均%"])))
    卡片格(_卡)
    表格(_大.assign(日期=_大["日期"].dt.strftime("%Y/%m/%d")), hide_index=True, width="stretch",
         column_config={**{c: st.column_config.NumberColumn(format="%+.2f") for c in ("跌點", "跌幅%", "之後最深%", "5日後%", "20日後%", "60日後%")},
                        "收盤": st.column_config.NumberColumn(format="%,.2f"), "收復天數": st.column_config.NumberColumn(format="%d")})
    st.caption("大跌＝加權收盤比前一天跌 3% 以上（指數 4 萬點時約 1,200 點）。收復天數＝之後第幾個交易日收盤回到大跌前一天的收盤，"
               "空白代表還沒收復；之後最深＝收復前（或到今天）最多再跌多少。連續大跌的日子會各算一次，所以樣本不是獨立的。"
               "吳采妮說「情緒造成的下跌多半幾週內收復」，資料從 2021-11 起，碰到 2022 年那種空頭時收復要十幾到二十幾天，過去不代表下次一樣。")

段落("LIMIT DOWN // 權值股碰跌停之後：跌停打開是好訊號嗎？（關我什麼事 2026-11）")
_事, _基 = 讀檔("讀取跌停打開事件", _版本)
if not len(_事):
    st.caption("價格資料還不夠。")
else:
    表格(engine.跌停打開統計(_事, _基), hide_index=True, width="stretch",
         column_config={**{c: st.column_config.NumberColumn(format="%+.2f") for c in ("5日後平均%", "20日後平均%", "60日後平均%")},
                        "次數": st.column_config.NumberColumn(format="%d"), "不同日期": st.column_config.NumberColumn(format="%d")})
    _查 = st.text_input("只看某一檔（代號）", placeholder="如 2330", key="跌停打開查詢").strip()
    _列 = _事[_事["代號"] == _查] if _查 else _事
    表格(_列.assign(日期=_列["日期"].dt.strftime("%Y/%m/%d")).head(200), hide_index=True, width="stretch",
         column_config={c: st.column_config.NumberColumn(format="%+.2f") for c in ("當天%", "從低點拉回%", "5日後%", "20日後%", "60日後%")})
    st.caption("範圍：0050 成分股，2021-11 起。碰跌停＝當天最低價 ≤ 前一天收盤 × 0.905；打開＝收盤從最低價拉回 5% 以上，"
               "沒打開＝收在跌停附近。之後報酬從當天收盤算起，「任何一天買進」是同一批股票每天買的平均。"
               "很多事件集中在同幾天（例如 2025/4 關稅、2024/8 日圓平倉），要看「不同日期」那欄，實際獨立的機會沒有次數那麼多。"
               "台積電 2024/8/5、2025/4/7 都是收在跌停沒打開，之後 60 日都漲超過 27%；2026/11/6 是第一次碰跌停又打開。")


段落("REBOUND // 反彈力道：反彈第一天站不站得上 5 日線？")
_K弱 = 指數K線("TAIEX", _版本)
_彈事, _彈統, _彈今 = engine.反彈首日(_K弱) if _K弱 is not None else (pd.DataFrame(), pd.DataFrame(), None)
if not len(_彈事):
    st.caption("指數資料還不夠。")
else:
    if _彈今:
        st.markdown(f"**最近的反彈首日：{pd.Timestamp(_彈今['日期']):%Y/%m/%d}　{_彈今['類型']}**（收盤 {_彈今['收盤']:,.0f}，5 日線 {_彈今['5日線']:,.0f}）")
    表格(_彈統, hide_index=True, width="stretch",
         column_config={c: st.column_config.NumberColumn(format="%+.2f") for c in ("5日平均%", "10日平均%", "20日平均%")})
    表格(_彈事.assign(日期=_彈事["日期"].dt.strftime("%Y/%m/%d"), 大跌日=_彈事["大跌日"].dt.strftime("%Y/%m/%d")), hide_index=True, width="stretch",
         column_config={c: st.column_config.NumberColumn(format="%+.2f") for c in ("大跌%", "反彈日%", "5日後%", "10日後%", "20日後%")})
    st.caption("反彈首日＝加權單日跌 3% 以上之後 5 天內，第一個漲 1.5% 以上的日子。站上＝當天收盤在 5 日線上（強反彈）；碰線被壓＝最高碰到但收在下面（弱反彈）。"
               "報酬從反彈首日收盤算起。樣本很少（2021-11 起），只能當參考；「任何一天買進」是同期間每天買的平均。")

段落("STOP FALL // 量縮止跌：KD 黃金交叉＋站上 5、10 日線")
_KD事, _KD統, _KD今 = engine.止跌KD條件(_K弱) if _K弱 is not None else (pd.DataFrame(), pd.DataFrame(), None)
if _KD今:
    卡片格([卡片("KD 黃金交叉", "✅ 有" if _KD今["KD 黃金交叉"] else "還沒", f"K {_KD今['K']:.0f}／D {_KD今['D']:.0f}"),
          卡片("站上 5、10 日線", "✅ 是" if _KD今["站上 5、10 日線"] else "還沒", ""),
          卡片("離 20 日高點", f"{_KD今['離 20 日高%']:+.1f}%", "回落 8% 以上才算「跌過」")])
    if len(_KD統):
        表格(_KD統, hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%+.2f") for c in ("5日平均%", "10日平均%", "20日平均%")})
    if len(_KD事):
        表格(_KD事.assign(日期=_KD事["日期"].dt.strftime("%Y/%m/%d")), hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%+.2f") for c in ("離20日高%", "5日後%", "10日後%", "20日後%")})
    st.caption("條件：KD（9,3,3）K 線由下往上穿過 D 線，同一天收盤站上 5 日與 10 日均線，而且收盤離 20 日高點已回落 8% 以上；同一段 10 天內只算一次。"
               "樣本少，結果只當參考。")

段落("ROTATION // 反彈兩階段：資金先回跌深股，還是已輪到高位階成長股？")
_輪 = 讀檔("讀取反彈輪動", _版本)
if not _輪:
    st.caption("價格資料還不夠。")
else:
    st.markdown(f"**{pd.Timestamp(_輪['日期']):%Y/%m/%d}　{_輪['階段']}**　{_輪['說明']}")
    表格(_輪["組別"], hide_index=True, width="stretch",
         column_config={c: st.column_config.NumberColumn(format="%+.2f") for c in ("今日平均%", "近 3 日平均%")})
    st.caption(f"跌深＝收盤離近 60 日高點 25% 以上；高位階高本益比＝離高點不到 10% 且本益比高於全市場中位數（{_輪['本益比中位']}）。"
               "原本的說法是「融資維持率爆掉」，網站沒有每檔融資維持率，所以用跌深＋本益比近似。兩組平均差 1 個百分點以上才判斷偏向哪一階段。")

段落("RESCUE HISTORY // 國安基金進場後：歷次平均")
_國表, _國本 = engine.國安基金統計(engine.讀取長期指數(_K弱)) if _K弱 is not None else (pd.DataFrame(), None)
_國均 = engine.國安基金平均(_國表)
if len(_國均):
    表格(_國均, hide_index=True, width="stretch", column_config={"平均%": st.column_config.NumberColumn(format="%+.1f")})
    st.caption("決議日起算，只算已有資料的次數。長期指數（2000 年起）每天自動補一段，補完後 2000～2020 年的幾次會自動納入；"
               "目前資料不足時次數偏少。2008 年「進場又限空仍續跌」要等補齊後才看得到。")

段落("VOLATILITY // 標普單日重挫之後：未來 20 天波動是不是比平常大？")
_標 = engine.資料夾 / "sox_long.csv"
_標價 = pd.read_csv(_標, parse_dates=["date"]) if _標.exists() else pd.DataFrame()
_標價 = _標價[_標價["symbol"] == "^GSPC"].set_index("date")["close"] if len(_標價) else None
_波 = engine.單日大跌後波動(_標價) if _標價 is not None else None
if not _波:
    st.caption("美股資料還不夠。")
else:
    卡片格([卡片("單日跌 4% 以上", f"{_波['次數']} 次", f"{_波['起']} 起"),
          卡片("之後 20 天年化波動", f"{_波['之後波動%']:.1f}%", f"全期間平均 {_波['全期間波動%']:.1f}%", 綠 if _波["之後波動%"] > _波["全期間波動%"] else "#EDEDED"),
          卡片("波動比平常大", f"{_波['放大次數']}／{_波['次數']}", "次數")])
    st.caption("標普 500 單日重挫 4% 以上，隔天起 20 個交易日的年化波動率平均，對照全期間 20 日波動率平均。波動放大不等於方向，只代表追價風險高；樣本少且集中在 2008、2020 年。")
