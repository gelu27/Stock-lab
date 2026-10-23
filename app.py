# 台股觀測站 v2：市場總覽、自訂選股、歷史回測
# 執行方式：streamlit run app.py

import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import engine

st.set_page_config(page_title="TW//STOCK LAB", page_icon="◢", layout="wide")

# ---------- 外觀：黑底前衛風格 ----------
青 = "#00E5FF"
紅 = "#FF3B5C"   # 台股習慣：紅漲
綠 = "#00D68F"   # 綠跌
灰 = "#6B6B6B"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;700&family=JetBrains+Mono:wght@400;700&family=Noto+Sans+TC:wght@400;700;900&display=swap');
html, body, [class*="css"], .stApp {{ font-family: 'Space Grotesk', 'Noto Sans TC', sans-serif; }}
.stApp {{ background:
    linear-gradient(#111 1px, transparent 1px) 0 0 / 100% 48px,
    #000; }}
h1, h2, h3 {{ font-family: 'Space Grotesk', 'Noto Sans TC', sans-serif !important; letter-spacing: -0.02em; }}
[data-testid="stSidebar"] {{ background: #050505; border-right: 1px solid #1E1E1E; }}
.hero {{ border: 1px solid #1E1E1E; padding: 28px 28px 20px; margin-bottom: 18px; position: relative; overflow: hidden; }}
.hero::after {{ content: ""; position: absolute; right: -60px; top: -60px; width: 220px; height: 220px;
    border: 1px solid {青}; transform: rotate(45deg); opacity: .35; }}
.hero .kicker {{ font-family: 'JetBrains Mono'; color: {青}; font-size: 12px; letter-spacing: .3em; }}
.hero .title {{ font-size: clamp(34px, 6vw, 72px); font-weight: 900; line-height: .95; margin: 8px 0 6px; }}
.hero .title span {{ color: {青}; }}
.hero .sub {{ font-family: 'JetBrains Mono'; color: {灰}; font-size: 12px; }}
.card {{ border: 1px solid #1E1E1E; padding: 14px 16px; background: #070707; height: 100%; }}
.card .k {{ font-family: 'JetBrains Mono'; font-size: 11px; color: {灰}; letter-spacing: .2em; text-transform: uppercase; }}
.card .v {{ font-family: 'JetBrains Mono'; font-size: 28px; font-weight: 700; margin-top: 4px; }}
.card .d {{ font-family: 'JetBrains Mono'; font-size: 12px; margin-top: 2px; }}
.sec {{ font-family: 'JetBrains Mono'; color: {青}; font-size: 12px; letter-spacing: .3em; margin: 22px 0 6px;
    border-bottom: 1px solid #1E1E1E; padding-bottom: 6px; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 0; border-bottom: 1px solid #1E1E1E; }}
.stTabs [data-baseweb="tab"] {{ font-family: 'JetBrains Mono'; letter-spacing: .15em; padding: 10px 18px; }}
.stButton > button, .stDownloadButton > button {{ border-radius: 0; border: 1px solid {青}; color: {青};
    background: transparent; font-family: 'JetBrains Mono'; letter-spacing: .15em; }}
.stButton > button:hover {{ background: {青}; color: #000; }}
</style>
""", unsafe_allow_html=True)


def 卡片(標題, 數值, 小字="", 顏色="#EDEDED"):
    return (f'<div class="card"><div class="k">{標題}</div>'
            f'<div class="v" style="color:{顏色}">{數值}</div><div class="d" style="color:{顏色}">{小字}</div></div>')


def 卡片列(卡們):
    for 欄, 卡 in zip(st.columns(len(卡們)), 卡們):
        欄.markdown(卡, unsafe_allow_html=True)


def 漲跌色(值):
    if pd.isna(值) or 值 == 0:
        return "#EDEDED"
    return 紅 if 值 > 0 else 綠


def 段落(文字):
    st.markdown(f'<div class="sec">{文字}</div>', unsafe_allow_html=True)


def 圖表外觀(圖, 高=380):
    圖.update_layout(
        template="plotly_dark", height=高, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10), font=dict(family="JetBrains Mono", size=11),
        legend=dict(orientation="h", y=1.08, x=0), hovermode="x unified",
        xaxis=dict(gridcolor="#151515"), yaxis=dict(gridcolor="#151515"),
    )
    return 圖


def 上色(表):
    欄們 = [c for c in ["漲跌幅", "20日漲幅", "報酬率(%)"] if c in 表.columns]
    整數欄 = {c: "{:,.0f}" for c in ["成交張數"] if c in 表.columns}
    return 表.style.map(lambda v: f"color:{漲跌色(v)}", subset=欄們).format(precision=2).format(整數欄)


# ---------- 讀資料 ----------
@st.cache_data(ttl=3600, show_spinner="讀取資料庫中…")
def 載入():
    原始 = engine.讀取資料庫()
    if 原始 is None:
        return None, None
    return engine.計算指標(原始), engine.讀取加權指數()


指標, 加權 = 載入()

st.markdown("""<div class="hero"><div class="kicker">TAIWAN STOCK EXCHANGE // PERSONAL LAB</div>
<div class="title">台股<span>觀測</span>實驗室</div>
<div class="sub">SCREEN · BACKTEST · OBSERVE — 資料來源：臺灣證券交易所</div></div>""",
            unsafe_allow_html=True)

if 指標 is None:
    st.warning("資料庫還是空的。請到 GitHub 專案的「Actions」頁面，點「更新資料庫」→「Run workflow」，"
               "第一次大約需要 1 到 2 小時，完成後重新整理本頁。")
    st.stop()

最新日 = 指標["date"].max()
今日 = 指標[指標["date"] == 最新日]

# ---------- 側邊欄：選股條件（選股與回測共用） ----------
st.sidebar.markdown(f'<div class="sec">SCREEN RULES</div>', unsafe_allow_html=True)
條件 = {}
with st.sidebar.expander("基本面", expanded=True):
    if st.checkbox("本益比上限", True):
        條件["本益比上限"] = st.number_input("本益比 ≤", value=15.0, step=1.0)
    if st.checkbox("殖利率下限", True):
        條件["殖利率下限"] = st.number_input("殖利率(%) ≥", value=4.0, step=0.5)
    if st.checkbox("股價淨值比上限"):
        條件["淨值比上限"] = st.number_input("淨值比 ≤", value=2.0, step=0.1)
with st.sidebar.expander("技術面", expanded=True):
    if st.checkbox("站上均線"):
        條件["站上均線"] = st.selectbox("收盤價站上", [5, 20, 60], index=1, format_func=lambda n: f"{n} 日均線")
    條件["均線多頭排列"] = st.checkbox("均線多頭排列（5 > 20 > 60 日）")
    if st.checkbox("20 日漲幅下限"):
        條件["20日漲幅下限"] = st.number_input("20 日漲幅(%) ≥", value=5.0, step=1.0)
    if st.checkbox("RSI 區間"):
        條件["RSI區間"] = st.slider("RSI(14)", 0, 100, (30, 70))
    if st.checkbox("量比下限（今日量 ÷ 20 日均量）"):
        條件["量比下限"] = st.number_input("量比 ≥", value=1.5, step=0.1)
with st.sidebar.expander("流動性與價格", expanded=True):
    條件["成交張數下限"] = st.number_input("成交張數 ≥", value=500, step=100)
    條件["股價區間"] = st.slider("收盤價", 0, 3000, (10, 1000))
    條件["排除ETF"] = st.checkbox("排除 ETF", True)
條件["排序"] = st.sidebar.selectbox("排序依據", list(engine.排序方式))

分頁 = st.tabs(["01 / 市場總覽", "02 / 選股", "03 / 回測"])

# ---------- 01 市場總覽 ----------
with 分頁[0]:
    上漲 = (今日["漲跌"] > 0).sum()
    下跌 = (今日["漲跌"] < 0).sum()
    卡們 = []
    if 加權 is not None and not 加權.empty:
        最後 = 加權.iloc[-1]
        漲幅 = 最後["change"] / (最後["close"] - 最後["change"]) * 100
        卡們.append(卡片("TAIEX 加權指數", f"{最後['close']:,.0f}",
                       f"{最後['change']:+,.2f}  ({漲幅:+.2f}%)", 漲跌色(最後["change"])))
    卡們 += [
        卡片("資料日期", 最新日.strftime("%m/%d"), 最新日.strftime("%Y")),
        卡片("上漲家數", f"{上漲}", "▲", 紅),
        卡片("下跌家數", f"{下跌}", "▼", 綠),
        卡片("成交金額", f"{今日['成交值億'].sum():,.0f}", "億元"),
    ]
    卡片列(卡們)

    if 加權 is not None and len(加權) > 1:
        段落("TAIEX // 近一年")
        近一年 = 加權[加權["date"] >= 加權["date"].max() - pd.Timedelta(days=365)]
        圖 = go.Figure(go.Scatter(x=近一年["date"], y=近一年["close"], line=dict(color=青, width=1.6),
                                  fill="tozeroy", fillcolor="rgba(0,229,255,0.06)", name="加權指數"))
        圖.update_yaxes(range=[近一年["close"].min() * 0.97, 近一年["close"].max() * 1.02])
        st.plotly_chart(圖表外觀(圖, 300), width="stretch")

    欄 = ["代號", "名稱", "收盤", "漲跌幅", "成交值億"]
    股票 = 今日[~今日["代號"].str.startswith("00")]
    a, b, c = st.columns(3)
    with a:
        段落("TOP GAINERS // 漲幅前十")
        st.dataframe(上色(股票.nlargest(10, "漲跌幅")[欄]), hide_index=True, width="stretch")
    with b:
        段落("TOP LOSERS // 跌幅前十")
        st.dataframe(上色(股票.nsmallest(10, "漲跌幅")[欄]), hide_index=True, width="stretch")
    with c:
        段落("MOST ACTIVE // 成交值前十")
        st.dataframe(上色(股票.nlargest(10, "成交值億")[欄]), hide_index=True, width="stretch")

# ---------- 02 選股 ----------
with 分頁[1]:
    結果 = engine.選股(今日, 條件)
    卡片列([
        卡片("符合條件", f"{len(結果)}", "檔", 青),
        卡片("資料日期", 最新日.strftime("%Y-%m-%d")),
        卡片("排序", 條件["排序"]),
    ])
    段落("RESULT // 選股結果")
    顯示欄 = ["代號", "名稱", "收盤", "漲跌幅", "本益比", "殖利率", "淨值比", "成交張數",
             "20日漲幅", "RSI", "量比", "距52週高點"]
    st.dataframe(上色(結果[顯示欄]), hide_index=True, width="stretch", height=420)
    st.download_button("下載 CSV", 結果[顯示欄].to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"選股_{最新日:%Y%m%d}.csv")

    段落("CHART // 個股走勢")
    選項 = (結果["代號"] + " " + 結果["名稱"]).tolist() or (今日["代號"] + " " + 今日["名稱"]).tolist()
    選擇 = st.selectbox("選一檔股票", 選項)
    個股 = 指標[指標["代號"] == 選擇.split()[0]].tail(250)
    圖 = go.Figure(go.Candlestick(
        x=個股["date"], open=個股["open"], high=個股["high"], low=個股["low"], close=個股["收盤"],
        increasing=dict(line=dict(color=紅), fillcolor=紅),
        decreasing=dict(line=dict(color=綠), fillcolor=綠), name="K 線"))
    # 均線用還原價算，換算回原始股價的比例來畫
    比例 = 個股["收盤"] / 個股["還原價"]
    for 天數, 色 in ((5, "#FFFFFF"), (20, 青), (60, "#FF00E5")):
        圖.add_trace(go.Scatter(x=個股["date"], y=個股[f"MA{天數}"] * 比例, name=f"MA{天數}",
                                line=dict(color=色, width=1)))
    圖.update_layout(xaxis_rangeslider_visible=False)
    st.plotly_chart(圖表外觀(圖, 420), width="stretch")

# ---------- 03 回測 ----------
with 分頁[2]:
    st.caption("規則：每期最後一個交易日收盤後用左側條件選股，隔日收盤價買進前 N 檔，每檔投入總資產 ÷ N；"
               "沒入選的賣出；觸發停損停利當天收盤賣出。已計入手續費 0.1425% 與證交稅 0.3%。")
    最早 = 指標["date"].min().date()
    a, b, c, d, e = st.columns(5)
    開始 = a.date_input("開始日期", max(最早, 最新日.date() - dt.timedelta(days=730)), min_value=最早,
                     max_value=最新日.date())
    結束 = b.date_input("結束日期", 最新日.date(), min_value=最早, max_value=最新日.date())
    調倉 = c.selectbox("調倉頻率", ["每月", "每週"])
    檔數 = d.number_input("最多持有檔數", 1, 50, 10)
    資金 = e.number_input("初始資金", 100_000, 100_000_000, 1_000_000, step=100_000)
    a, b = st.columns(2)
    停損 = a.number_input("停損 %（0 代表不設）", 0.0, 50.0, 10.0, step=1.0)
    停利 = b.number_input("停利 %（0 代表不設）", 0.0, 500.0, 0.0, step=5.0)

    if st.button("▶ 開始回測"):
        with st.spinner("回測計算中…"):
            st.session_state["回測"] = engine.回測(
                指標, 條件, pd.Timestamp(開始), pd.Timestamp(結束), 檔數, 調倉,
                停損 or None, 停利 or None, 資金)

    報告 = st.session_state.get("回測")
    if 報告 is None:
        st.info("設定好左側選股條件與上方參數後，按「開始回測」。")
    else:
        績 = 報告["績效"]
        卡們 = [
            卡片("總報酬", f"{績['總報酬(%)']:+.1f}%", "", 漲跌色(績["總報酬(%)"])),
            卡片("年化報酬", f"{績['年化報酬(%)']:+.1f}%", "", 漲跌色(績["年化報酬(%)"])),
            卡片("最大回撤", f"{績['最大回撤(%)']:.1f}%", "", 綠),
            卡片("勝率", f"{績['勝率(%)']:.0f}%", f"{績['交易次數']} 筆交易"),
            卡片("夏普值", f"{績['夏普值']:.2f}"),
        ]
        if "0050 同期報酬(%)" in 績:
            卡們.append(卡片("0050 同期", f"{績['0050 同期報酬(%)']:+.1f}%", "買進持有",
                           漲跌色(績["0050 同期報酬(%)"])))
        卡片列(卡們)

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
            st.dataframe(上色(報告["交易"]), hide_index=True, width="stretch", height=360)

st.markdown(f'<div class="sub" style="color:{灰};font-family:JetBrains Mono;font-size:11px;margin-top:30px">'
            '僅供個人研究，不構成投資建議 // DATA: TWSE</div>', unsafe_allow_html=True)
