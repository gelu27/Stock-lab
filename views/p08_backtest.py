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
回測分頁 = st.tabs(["組合回測", "個股回測"])
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
