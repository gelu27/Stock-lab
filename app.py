# 台股觀測站 v2：市場總覽、自訂選股、歷史回測
# 執行方式：streamlit run app.py

import datetime as dt
import hashlib
import hmac
import io
import os
import re
import threading
import urllib.parse
from pathlib import Path

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pandas.io.formats.style import Styler
import streamlit as st

import importlib

import engine
import etf_data
import etf_analysis

importlib.reload(engine)
importlib.reload(etf_data)  # 程式更新後確保用的是最新版的計算規則
importlib.reload(etf_analysis)

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
.hero .sub {{ font-family: 'JetBrains Mono'; color: {灰}; font-size: 12px; margin-top: 8px; }}
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
.grid2 {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 4px; }}
.grid2 .card .v {{ font-size: clamp(18px, 5vw, 28px); }}
.grid2 .card .k {{ font-size: clamp(9px, 2.4vw, 11px); letter-spacing: .1em; }}
.grid2 .card .d {{ font-size: clamp(10px, 2.6vw, 12px); }}
.grid2 .card {{ padding: 10px 10px; }}
.grid3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
.grid3 .card .v {{ font-size: clamp(17px, 4.6vw, 28px); }}
.grid3 .card .k {{ font-size: clamp(9px, 2.4vw, 11px); letter-spacing: .1em; }}
.grid3 .card .d {{ font-size: clamp(10px, 2.6vw, 12px); }}
.grid3 .card {{ padding: 10px 10px; }}
.rankwrap {{ overflow-x: auto; }}
@media (max-width: 480px) {{ .rank td, .rank td.n {{ font-size: 14px; padding: 8px 6px; }} .rank th {{ padding: 8px 6px; }}
    .rank td:nth-child(5), .rank th:nth-child(5) {{ display: none; }} }}
.rank {{ width: 100%; border-collapse: collapse; font-family: 'Noto Sans TC', sans-serif; }}
.rank th {{ background: #141414; color: #9A9A9A; font-weight: 400; padding: 8px 10px; text-align: right;
    font-size: 14px; }}
.rank th:first-child, .rank td:first-child {{ text-align: center; }}
.rank td {{ padding: 9px 10px; border-bottom: 1px solid #1E1E1E; text-align: right;
    font-family: 'JetBrains Mono', monospace; font-size: 16px; }}
.rank td.n {{ font-family: 'Noto Sans TC', sans-serif; color: #EDEDED; font-size: 16px; white-space: nowrap; }}
.rank td.n small {{ color: {灰}; font-size: 12px; margin-right: 5px; font-family: 'JetBrains Mono'; }}
.rank td.n a {{ color: inherit; text-decoration: none; }}
.rank td.t {{ color: #EDEDED; white-space: nowrap; font-size: 13px; }}
.rank td.t small {{ color: {灰}; margin-left: 4px; font-size: 11px; }}
.ticker {{ overflow: hidden; white-space: nowrap; border-top: 1px solid #1E1E1E; border-bottom: 1px solid #1E1E1E;
    margin: -6px 0 14px; padding: 6px 0; }}
.ticker .tr {{ display: inline-block; animation: tk 70s linear infinite; }}
.ticker:hover .tr, .ticker:active .tr {{ animation-play-state: paused; }}
.ticker span {{ font-family: 'JetBrains Mono', 'Noto Sans TC', monospace; font-size: 13px; margin-right: 30px; }}
.ticker span b {{ color: #9A9A9A; font-weight: 400; margin-right: 6px; font-family: 'Noto Sans TC', sans-serif; }}
@keyframes tk {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}
/* 全站一致：直角、提示框、表頭不換行 */
.stMain {{ scroll-behavior: smooth; }}
[data-testid="stExpander"] details, [data-testid="stPopoverBody"], [data-baseweb="select"] > div,
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input {{ border-radius: 0 !important; }}
[data-testid="stExpander"] details {{ border-color: #1E1E1E; background: #050505; }}
[data-testid="stAlert"] > div {{ border-radius: 0; }}
[data-testid="stAlertContainer"] {{ border-radius: 0; background: #0A0A0A; border-left: 3px solid {青}; }}
.rank th {{ white-space: nowrap; }}
[data-testid="stCaptionContainer"] {{ color: #8A8A8A; }}
/* 首頁快速跳轉列與回到頂端 */
.jump {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 10px; }}
.jump a {{ font-family: 'Noto Sans TC', sans-serif; font-size: 13px; color: #BDBDBD; text-decoration: none;
    border: 1px solid #1E1E1E; padding: 3px 10px; background: #070707; }}
.jump a:hover {{ border-color: {青}; color: {青}; }}
.anchor {{ position: relative; top: -70px; height: 0; }}
[data-testid="stElementContainer"]:has(.anchor) {{ margin-bottom: -1rem; }}
.totop {{ position: fixed; right: 16px; bottom: 18px; z-index: 999; width: 40px; height: 40px; line-height: 38px;
    text-align: center; border: 1px solid {青}; background: rgba(0,0,0,.85); color: {青} !important;
    text-decoration: none !important; font-family: 'JetBrains Mono'; font-size: 18px; }}
.totop:hover {{ background: {青}; color: #000 !important; }}
/* 關鍵價位：燈號卡、價位條 */
.lamps {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 6px 0; }}
.lamp {{ border: 1px solid #1E1E1E; background: #070707; padding: 10px 12px; }}
.lamp .t {{ font-family: 'Noto Sans TC', sans-serif; font-size: 14px; color: #EDEDED; font-weight: 700; }}
.lamp .t i {{ font-style: normal; margin-right: 6px; }}
.lamp .s {{ font-family: 'JetBrains Mono', 'Noto Sans TC', monospace; font-size: 12px; color: #9A9A9A; margin-top: 4px; line-height: 1.5; }}
.lamp.g {{ border-left: 3px solid {綠}; }} .lamp.y {{ border-left: 3px solid #FFC24B; }} .lamp.r {{ border-left: 3px solid {紅}; }}
.verdict {{ border: 1px solid #1E1E1E; border-left: 3px solid {青}; background: #050505; padding: 10px 14px; margin: 8px 0;
    font-family: 'Noto Sans TC', sans-serif; font-size: 15px; line-height: 1.7; color: #DADADA; }}
.verdict.sub {{ border-left-color: #8F7CFF; font-size: 14px; padding: 8px 14px; }}
.pv {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 8px; align-items: center; }}
.pv span {{ font-family: 'JetBrains Mono', 'Noto Sans TC', monospace; font-size: 12px; padding: 3px 8px; border: 1px solid #222;
    background: #080808; color: #9A9A9A; }}
.pv span b {{ font-weight: 700; margin-left: 4px; }}
.pv span.now {{ border-color: #8F7CFF; color: #EDEDED; }}
.cross {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 8px; }}
.cross span {{ font-family: 'Noto Sans TC', sans-serif; font-size: 13px; padding: 4px 10px; border: 1px solid; font-weight: 700; }}
.cross .dn {{ color: {綠}; border-color: {綠}; background: rgba(0,214,143,.08); }}
.cross .up {{ color: {紅}; border-color: {紅}; background: rgba(255,59,92,.08); }}
.thermo {{ position: relative; height: 12px; margin: 10px 0 4px;
    background: linear-gradient(90deg, {紅} 0%, #555 45%, #555 55%, {綠} 100%); opacity: .9; }}
.thermo i {{ position: absolute; top: -5px; width: 4px; height: 22px; background: #FFF; box-shadow: 0 0 6px #FFF; }}
.thermo-l {{ display: flex; justify-content: space-between; font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #777; }}
@media (max-width: 640px) {{ .lamps {{ grid-template-columns: 1fr; gap: 6px; }} .verdict {{ font-size: 14px; }} }}
/* 手機：頁首縮小、頁面選單改成一排可左右滑 */
@media (max-width: 640px) {{
    .hero {{ padding: 16px 16px 12px; margin-bottom: 10px; }}
    .hero::after {{ width: 120px; height: 120px; right: -40px; top: -40px; }}
    .hero .kicker {{ font-size: 10px; letter-spacing: .15em; }}
    .hero .title {{ font-size: 34px; margin: 4px 0 0; }}
    .hero .sub, .hide-m {{ display: none; }}
    .st-key-nav [data-testid="stButtonGroup"] > div {{ display: grid !important; grid-template-columns: repeat(3, 1fr); }}
    .st-key-nav button {{ width: 100%; margin: 0 !important; border-radius: 0 !important; white-space: nowrap;
        padding: 2px 4px; min-height: 32px; }}
    .st-key-nav button p {{ font-size: 13px; }}
    .jump {{ flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; }}
    .jump a {{ flex: 0 0 auto; }}
    .sec {{ letter-spacing: .15em; margin-top: 18px; }}
    .st-key-toolbar [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; gap: 4px 16px; }}
    .st-key-toolbar [data-testid="stColumn"] {{ width: auto !important; flex: 0 0 auto !important; min-width: 0 !important; }}
    .st-key-toolbar [data-testid="stColumn"]:first-child {{ flex: 1 0 100% !important; }}
}}
</style>
""", unsafe_allow_html=True)


def 卡片(標題, 數值, 小字="", 顏色="#EDEDED"):
    return (f'<div class="card"><div class="k">{標題}</div>'
            f'<div class="v" style="color:{顏色}">{數值}</div><div class="d" style="color:{顏色}">{小字}</div></div>')


def 卡片格(卡們):
    """固定一排三格，手機上也維持兩排三欄。"""
    st.markdown(f'<div class="grid3">{"".join(卡們)}</div>', unsafe_allow_html=True)


def 漲跌色(值):
    if pd.isna(值) or 值 == 0:
        return "#EDEDED"
    return 紅 if 值 > 0 else 綠


def 段落(文字):
    st.markdown(f'<div class="sec">{文字}</div>', unsafe_allow_html=True)


def 圖表外觀(圖, 高=380):
    圖.update_layout(
        template="plotly_dark", height=高, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10), font=dict(family="JetBrains Mono, Noto Sans TC, sans-serif", size=11),
        hoverlabel=dict(bgcolor="#0A0A0A", bordercolor="#333", font=dict(family="JetBrains Mono, Noto Sans TC")),
        legend=dict(orientation="h", y=1.08, x=0), hovermode="x unified",
        xaxis=dict(gridcolor="#151515"), yaxis=dict(gridcolor="#151515"),
    )
    return 圖


def 上色(表):
    欄們 = [c for c in ["漲跌幅", "5日漲幅", "20日漲幅", "報酬率(%)", "加入至今%", "報告後漲跌%", "今日損益", "總損益", "法人(張)"] if c in 表.columns]
    整數 = {"成交張數", "報告次數", "今日損益", "總損益", "股數", "總成本", "法人(張)", "市值億"}
    格式 = {c: ("{:,.0f}" if c in 整數 else "{:,.2f}") for c in 表.select_dtypes("number").columns}
    return 表.style.map(lambda v: f"color:{漲跌色(v)}", subset=欄們).format(格式, na_rep="—")


# ---------- 讀資料 ----------
常駐天數 = 300  # 52 週高點要 240 天，多留一點


@st.cache_data(max_entries=30, ttl=43200, show_spinner=False)
def 個股全史(代號, 資料版本=None):
    """這一檔完整 5 年的指標（K 線週月季、本益比河流圖、個股回測用），只讀這檔所以很快、也不佔記憶體。"""
    原始 = engine.讀取資料庫(代號=代號)
    return None if 原始 is None else engine.計算指標(原始)


@st.cache_resource(max_entries=1, show_spinner="讀取資料庫中…")  # 不複製資料，省一半記憶體
def 載入(資料版本):
    # 資料版本變了（每天更新後）就會重新讀取，不會一直用舊的暫存
    原始 = engine.讀取資料庫(最近天數=常駐天數)  # 平常只放近一年多，完整 5 年要用時再臨時讀
    if 原始 is None:
        return None, None
    指標 = engine.計算指標(原始)
    del 原始
    engine.釋放記憶體()
    return 指標, engine.讀取加權指數()


def 資料版本():
    紀錄們 = list((engine.資料夾 / "status").glob("*.txt")) + list(engine.資料夾.glob("dates.txt"))
    最新 = max((f.stat().st_mtime for f in 紀錄們 + list(engine.資料夾.glob("updated.txt"))), default=0)
    檔數 = len(list((engine.資料夾 / "prices").glob("**/*.csv.gz")))
    return f"{最新}-{檔數}"


@st.cache_resource
def _目前版本():
    return {"版本": None}


_版本 = 資料版本()
if _目前版本()["版本"] not in (None, _版本):
    # 資料更新了：先丟掉舊資料再讀新的，避免新舊兩份同時佔記憶體
    載入.clear()
    engine.釋放記憶體()
_目前版本()["版本"] = _版本
指標, 加權 = 載入(_版本)

st.markdown("""<div id="top"></div><a class="totop" href="#top" target="_self" title="回到頂端">↑</a><div class="hero"><div class="kicker">TAIWAN STOCK EXCHANGE // PERSONAL LAB</div>
<div class="title">台股<span>觀測</span>實驗室</div>
<div class="sub">SCREEN · BACKTEST · OBSERVE — 資料來源：臺灣證券交易所、證券櫃檯買賣中心</div></div>""",
            unsafe_allow_html=True)

def 最後更新():
    f = engine.資料夾 / "updated.txt"
    return f.read_text().strip() if f.exists() else "（下次自動更新後顯示）"


if 指標 is None:
    載入.clear()
    st.warning("資料庫還是空的。請到 GitHub 專案的「Actions」頁面，點「更新資料庫」→「Run workflow」，"
               "第一次大約需要 1 到 2 小時，完成後重新整理本頁。")
    st.stop()

最新日 = 指標["date"].max()
if "精簡表格" not in st.session_state:  # 手機預設精簡
    try:
        st.session_state["精簡表格"] = "Mobile" in st.context.headers.get("User-Agent", "")
    except Exception:
        st.session_state["精簡表格"] = False
a, c, b = st.container(key="toolbar").columns([3, 1, 1], vertical_alignment="center")
a.caption(f"📅 資料日期 {最新日:%Y/%m/%d}　·　資料庫最後更新 {最後更新()}"
          '<span class="hide-m">（每個交易日約 18:00 自動更新）</span>', unsafe_allow_html=True)
c.toggle("📱 精簡表格", key="精簡表格", help="表格只留名稱、股價、漲跌等重點欄位，手機不用左右滑")
with b.popover("🔄 更新"):
    st.markdown("**重新載入**：資料庫已經更新、但網站顯示的還是舊資料時按。")
    if st.button("🔄 重新載入網站資料", key="重新載入"):
        載入.clear()
        st.cache_data.clear()
        for k in ("自選股", "到價提醒"):
            st.session_state.pop(k, None)
        engine.釋放記憶體()
        st.rerun()
    st.markdown("**重新執行更新**：請 GitHub 立刻再抓一次交易所資料（約 5～15 分鐘），完成後再按上面的重新載入。")
    if st.button("⚡ 重新執行資料更新", key="觸發更新"):
        try:
            秘密 = dict(st.secrets)
        except Exception:
            秘密 = {}
        if 秘密.get("password") and not st.session_state.get("已解鎖"):
            st.warning("請先到「02 / 我的股票」輸入密碼解鎖。")
        else:
            成功, 說明 = engine.觸發更新(秘密)
            (st.success if 成功 else st.error)(說明)
今日 = engine.加基本面(指標[指標["date"] == 最新日], engine.讀取基本面())
市場名稱 = dict(zip(今日["代號"], 今日["名稱"]))
有籌碼 = "法人買超" in 指標.columns


@st.cache_data(ttl=300, show_spinner=False)
def 抓國際():
    return engine.國際行情(), engine.台指期()


def 跑馬燈():
    """頁首一條會捲動的行情：加權、漲跌家數、台指期、美股、匯率。手指按住（滑鼠移上去）會暫停。"""
    項們 = []
    def 加(名, 價, 漲跌, 幅度=None, 格式="{:,.2f}"):
        色 = 漲跌色(漲跌)
        尾 = f"{漲跌:+,.2f}" + (f"（{幅度:+.2f}%）" if 幅度 is not None and pd.notna(幅度) else "")
        項們.append(f'<span><b>{名}</b><font color="{色}">{格式.format(價)} {尾}</font></span>')
    if 加權 is not None and len(加權):
        r = 加權.iloc[-1]
        加("加權", r["close"], r["change"], r["change"] / (r["close"] - r["change"]) * 100)
    上, 下 = int((今日["漲跌"] > 0).sum()), int((今日["漲跌"] < 0).sum())
    項們.append(f'<span><b>漲跌家數</b><font color="{紅}">▲{上}</font> <font color="{綠}">▼{下}</font></span>')
    項們.append(f'<span><b>成交金額</b>{今日["成交值億"].sum():,.0f} 億</span>')
    try:
        國際, 期貨 = 抓國際()
    except Exception:
        國際, 期貨 = {}, {}
    for 盤 in ("日盤", "夜盤"):
        q = 期貨.get(盤)
        if q:
            加(f"台指期{盤}", q["價"], q["漲跌"], q["幅度"], "{:,.0f}")
    for 名 in ("費城半導體", "那斯達克", "道瓊", "S&P 500", "台積電 ADR", "日經 225", "美元/台幣"):
        q = 國際.get(名)
        if q:
            加(名, q["價"], q["漲跌"], q["幅度"], "{:,.3f}" if 名 == "美元/台幣" else "{:,.2f}")
    內容 = "".join(項們)
    st.markdown(f'<div class="ticker"><div class="tr">{內容}{內容}</div></div>', unsafe_allow_html=True)


跑馬燈()

# ---------- 選股條件（04 選股與 08 組合回測共用，原本在左側欄） ----------
def 選股條件區():
    """畫出選股條件，回傳 (條件, 範本)。換頁時 Streamlit 會清掉沒顯示的元件狀態，所以另外記一份。"""
    記憶 = st.session_state.setdefault("_條件記憶", {})
    for k, v in 記憶.items():
        if k not in st.session_state:
            st.session_state[k] = v
    條件 = {}
    條件["市場"] = st.multiselect("市場", ["上市", "上櫃"], default=["上市", "上櫃"], key="條_市場")
    範本 = st.selectbox("策略範本", ["自訂條件"] + list(engine.烏賊條件), key="條_策略範本",
                      help="烏賊 0530 課程的五組選股條件，選了之後下面的自訂條件會暫停使用")
    if 範本 == "自訂條件":
        格 = st.columns(2)
        with 格[0].container(border=True):
            st.markdown("**基本面**")
            if st.checkbox("本益比上限", True, key="條_本益比上限"):
                條件["本益比上限"] = st.number_input("本益比 ≤", value=15.0, step=1.0, key="條_本益比 ≤")
            if st.checkbox("殖利率下限", True, key="條_殖利率下限"):
                條件["殖利率下限"] = st.number_input("殖利率(%) ≥", value=4.0, step=0.5, key="條_殖利率(%) ≥")
            if st.checkbox("股價淨值比上限", key="條_股價淨值比上限"):
                條件["淨值比上限"] = st.number_input("淨值比 ≤", value=2.0, step=0.1, key="條_淨值比 ≤")
            if st.checkbox("月營收年增率下限", key="條_月營收年增率下限"):
                條件["營收年增率下限"] = st.number_input("營收年增率(%) ≥", value=20.0, step=5.0, key="條_營收年增率(%) ≥")
            if st.checkbox("月營收月增率下限", key="條_月營收月增率下限"):
                條件["營收月增率下限"] = st.number_input("營收月增率(%) ≥", value=0.0, step=5.0, key="條_營收月增率(%) ≥")
            if st.checkbox("累計營收年增率下限", key="條_累計營收年增率下限"):
                條件["累計營收年增率下限"] = st.number_input("累計營收年增率(%) ≥", value=10.0, step=5.0, key="條_累計營收年增率(%) ≥")
            if st.checkbox("最新一季 EPS 下限", key="條_最新一季 EPS 下限"):
                條件["EPS下限"] = st.number_input("EPS(元) ≥", value=1.0, step=0.5, key="條_EPS(元) ≥")
            st.caption("月營收與 EPS 只有最新一期，組合回測時不會套用。")
        with 格[1].container(border=True):
            st.markdown("**籌碼面**")
            if st.checkbox("外資連續買超", key="條_外資連續買超"):
                條件["外資連買下限"] = st.number_input("外資連買天數 ≥", value=3, step=1, key="條_外資連買天數 ≥")
            if st.checkbox("投信連續買超", key="條_投信連續買超"):
                條件["投信連買下限"] = st.number_input("投信連買天數 ≥", value=3, step=1, key="條_投信連買天數 ≥")
            if st.checkbox("外資連續賣超", key="條_外資連續賣超"):
                條件["外資連賣下限"] = st.number_input("外資連賣天數 ≥", value=5, step=1, key="條_外資連賣天數 ≥")
            if st.checkbox("土洋對作（外資賣、投信買）", key="條_土洋對作"):
                條件["土洋對作下限"] = st.number_input("連續天數 ≥", value=3, step=1, key="條_土洋對作天數 ≥")
            if st.checkbox("三大法人 5 日合計買超", key="條_三大法人 5 日合計買超"):
                條件["法人5日買超下限"] = st.number_input("法人 5 日買超(張) ≥", value=1000, step=500, key="條_法人 5 日買超(張) ≥")
            if st.checkbox("融資 5 日增減上限", key="條_融資 5 日增減上限"):
                條件["融資5日增減上限"] = st.number_input("融資 5 日增減(%) ≤", value=0.0, step=1.0, key="條_融資 5 日增減(%) ≤")
        with 格[0].container(border=True):
            st.markdown("**技術面**")
            if st.checkbox("站上均線", key="條_站上均線"):
                條件["站上均線"] = st.selectbox("收盤價站上", [5, 20, 60], index=1, format_func=lambda n: f"{n} 日均線", key="條_收盤價站上")
            條件["均線多頭排列"] = st.checkbox("均線多頭排列（5 > 20 > 60 日）", key="條_均線多頭排列（5 > 20 > 60 日）")
            if st.checkbox("20 日漲幅下限", key="條_20 日漲幅下限"):
                條件["20日漲幅下限"] = st.number_input("20 日漲幅(%) ≥", value=5.0, step=1.0, key="條_20 日漲幅(%) ≥")
            if st.checkbox("RSI 區間", key="條_RSI 區間"):
                條件["RSI區間"] = st.slider("RSI(14)", 0, 100, (30, 70), key="條_RSI(14)")
            if st.checkbox("量比下限（今日量 ÷ 20 日均量）", key="條_量比下限（今日量 ÷ 20 日均量）"):
                條件["量比下限"] = st.number_input("量比 ≥", value=1.5, step=0.1, key="條_量比 ≥")
        with 格[1].container(border=True):
            st.markdown("**流動性與價格**")
            條件["成交張數下限"] = st.number_input("成交張數 ≥", value=500, step=100, key="條_成交張數 ≥")
            條件["股價區間"] = st.slider("收盤價", 0, 3000, (10, 1000), key="條_收盤價")
            條件["排除ETF"] = st.checkbox("排除 ETF", True, key="條_排除 ETF")
        條件["排序"] = st.selectbox("排序依據", list(engine.排序方式), key="條_排序依據")
    else:
        st.info(engine.烏賊條件[範本]["說明"])
        條件.update(engine.烏賊條件[範本]["條件"])
        條件["排除ETF"] = True
    st.session_state["_條件記憶"] = {k: v for k, v in st.session_state.items() if str(k).startswith("條_")}
    return 條件, 範本


# ---------- 頁面切換（用按鈕列代替分頁，才能點股票後直接跳到個股查詢） ----------
頁面檔 = ['p01_market', 'p02_mystocks', 'p03_stock', 'p04_screener', 'p05_revenue', 'p06_etf', 'p07_score', 'p08_backtest', 'p09_stats']
頁面們 = ["01 / 市場總覽", "02 / 我的股票", "03 / 個股查詢", "04 / 選股", "05 / 月營收", "06 / 主動式 ETF", "07 / 每日評分", "08 / 回測", "09 / 使用統計"]
股票選項 = (今日["代號"] + " " + 今日["名稱"]).tolist()


def 前往(代號):
    """跳到個股查詢並選好這檔股票。"""
    選項 = next((v for v in 股票選項 if v.split()[0] == str(代號)), None)
    if 選項:
        st.session_state["個股查詢"] = 選項
        st.session_state["頁面"] = 頁面們[2]
        st.session_state["要跳轉"] = True


def _密碼():
    try:
        return str(st.secrets.get("password", ""))
    except Exception:
        return ""


def 登入憑證(天數=None):
    """密碼通過後發一張有期限的通行證放在網址（?k=...），重新整理或點排行榜連結都不用再輸入密碼。"""
    try:
        天數 = 天數 or int(st.secrets.get("LOGIN_DAYS", 30))
    except Exception:
        天數 = 30
    到期 = int(dt.datetime.now().timestamp()) + 天數 * 86400
    簽 = hmac.new(_密碼().encode(), str(到期).encode(), "sha256").hexdigest()[:24]
    return f"{到期}.{簽}"


def 憑證有效(k):
    try:
        到期, 簽 = str(k).split(".")
        對 = hmac.new(_密碼().encode(), 到期.encode(), "sha256").hexdigest()[:24]
        return bool(_密碼()) and hmac.compare_digest(簽, 對) and int(到期) > dt.datetime.now().timestamp()
    except Exception:
        return False


if "k" in st.query_params:
    if 憑證有效(st.query_params["k"]):
        st.session_state["已解鎖"] = True
    else:
        del st.query_params["k"]

if "已計來訪" not in st.session_state:  # 每個瀏覽階段記一次來客數（背景存檔，不拖慢網頁）
    st.session_state["已計來訪"] = True
    try:
        # 依序用：真實 IP（經過 Streamlit 的轉送標頭）、連線 IP、瀏覽器的 cookie
        _ip = (st.context.headers.get("X-Forwarded-For", "").split(",")[0].strip() or st.context.ip_address
               or st.context.cookies.get("_streamlit_xsrf", ""))
    except Exception:
        _ip = ""
    try:
        _秘 = dict(st.secrets)
    except Exception:
        _秘 = {}
    _碼 = hashlib.sha256(f"{_秘.get('password', '')}|{_ip}".encode()).hexdigest()[:8] if _ip else ""
    threading.Thread(target=engine.記錄來訪, args=(_秘, bool(st.session_state.get("已解鎖")), _碼), daemon=True).start()

if "s" in st.query_params:  # 排行榜的連結：?s=2330
    前往(st.query_params["s"])
    del st.query_params["s"]
st.session_state.pop("要跳轉", None)
if st.session_state.get("頁面") not in 頁面們:
    st.session_state["頁面"] = 頁面們[0]


def _搜尋跳轉():
    選 = st.session_state.get("全站搜尋")
    if 選:
        前往(選.split()[0])
    st.session_state["全站搜尋"] = None


if st.session_state.get("頁面") != 頁面們[2]:  # 個股查詢頁本身就有搜尋框
    st.selectbox("搜尋股票", 股票選項, index=None, key="全站搜尋", on_change=_搜尋跳轉, label_visibility="collapsed",
                 placeholder="🔍 輸入代號或名稱，直接跳到個股查詢（例如 2330、台積電）")
with st.container(key="nav"):
    頁面 = st.segmented_control("頁面", 頁面們, key="頁面", label_visibility="collapsed") or 頁面們[0]


def 加代號(資料, 參數):
    """明細的「名稱」前面加上代號（例如「2330 台積電」），手機精簡表格藏掉代號欄時也看得到；合併後代號欄就不重複顯示。"""
    表 = 資料.data if isinstance(資料, Styler) else 資料
    if not isinstance(表, pd.DataFrame) or "名稱" not in 表.columns:
        return 資料
    if "代號" in 表.columns:
        碼們 = 表["代號"]
    elif 表.index.name == "代號":
        碼們 = 表.index
    else:
        return 資料
    名們 = [f"{c} {n}" if isinstance(n, str) and isinstance(c, str) and c and not n.startswith(c) else n
          for c, n in zip(碼們, 表["名稱"])]
    表 = 表.copy()
    表["名稱"] = 名們
    if "代號" in 表.columns:
        參數["column_config"] = {"代號": None, **(參數.get("column_config") or {})}
    if isinstance(資料, Styler):
        資料.data = 表
        return 資料
    return 表


def 表格(資料, **參數):
    """st.dataframe，名稱前面自動加代號。"""
    return st.dataframe(加代號(資料, 參數), **參數)


def 點選表(表, 樣式, key, 動作=None, **參數):
    """可以點選列的表格：點一下就跳到那檔股票的個股查詢（或改做 動作(代號)）。"""
    def 點了():
        列們 = st.session_state[key].selection.rows
        if 列們:
            (動作 or 前往)(表.iloc[列們[0]]["代號"])
    if st.session_state.get("精簡表格"):
        留 = [c for c in 表.columns if c in 精簡欄位]
        if len(留) >= 3:
            參數["column_config"] = {**{c: None for c in 表.columns if c not in 留}, **參數.get("column_config", {})}
    表格(樣式, key=key, on_select=點了, selection_mode="single-row", hide_index=True, width="stretch", **參數)


# 手機精簡表格只留這些欄（有的才顯示）
精簡欄位 = {"名稱", "股票", "股價", "收盤", "漲跌幅", "今日損益", "總損益", "報酬率(%)", "總分", "較昨日", "看法",
          "加入至今%", "驗收", "距目標價%", "20日漲幅", "符合策略", "市值億", "規模", "營收(億)", "年增%",
          "理由", "金額(億)", "貢獻點數", "投信(張)"}

@st.cache_data(show_spinner=False)
def 警示表(_資料版本):
    return engine.讀取警示()


@st.cache_data(show_spinner=False)
def 日程資料(代號們, _資料版本, 天數=30):
    return engine.重要日程(代號們, 天數)


@st.cache_resource
def AI用量():
    """全站每日 AI 分析次數（避免網站公開時被一直按）。"""
    return {}


@st.cache_data(ttl=600, show_spinner=False, max_entries=50)
def AI紀錄快取(代號, _權杖):
    try:
        設定 = dict(st.secrets)
    except Exception:
        設定 = {}
    return engine.讀取AI紀錄(代號, 設定)



# ---------- 每日評分（規則打分數，網站與 LINE 收盤摘要共用 engine 的規則） ----------
@st.cache_resource(max_entries=1, show_spinner="計算每日評分中…")
def 評分資料(_資料版本):
    return engine.今昨評分(指標[指標["date"] >= 指標["date"].max() - pd.Timedelta(days=20)],
                         engine.讀取基本面(), 加權)


def ETF版本():
    檔們 = sorted(etf_data.持股資料夾.glob("*/*.csv.gz"))
    return f"{檔們[-1].name}-{檔們[-1].stat().st_mtime}-{len(檔們)}" if 檔們 else ""


@st.cache_data(max_entries=2, ttl=43200, show_spinner="讀取主動式 ETF 持股中…")
def ETF資料(版本):
    持股 = etf_data.讀持股(70)
    資訊 = etf_data.讀資訊()
    return 持股, 資訊, etf_data.每日變化(持股, 資訊)


def 分數色(分):
    if pd.isna(分):
        return 灰
    return 紅 if 分 >= 58 else (綠 if 分 <= 42 else 灰)


def 評分卡片(代號):
    """個股的總分與四個面向分數卡片，加上加分、扣分理由。"""
    分, d, _ = 評分資料(_版本)
    if 代號 not in 分.index or pd.isna(分.at[代號, "總分"]):
        st.caption("這檔沒有足夠資料可以評分。")
        return
    r = 分.loc[代號]
    變 = r["較昨日"]
    卡們 = [卡片("總分", f"{r['總分']:.0f}", f"{r['看法']}" + ("" if pd.isna(變) else f" · 較昨日 {變:+.0f}"), 分數色(r["總分"]))]
    for 面 in engine.評分權重:
        卡們.append(卡片(f"{面}面 · 佔 {engine.評分權重[面]:.0%}", "—" if pd.isna(r[面]) else f"{r[面]:.0f}",
                       "", 分數色(r[面])))
    名次 = int((分["總分"] > r["總分"]).sum()) + 1
    卡們.append(卡片("全市場排名", f"{名次:,}", f"共 {分['總分'].notna().sum():,} 檔"))
    卡片格(卡們)
    明細 = engine.評分明細(d, 代號)
    with st.expander("看加分、扣分理由"):
        for 面, 項 in 明細.items():
            if pd.isna(r[面]):
                st.markdown(f"**{面}面**：沒有資料，不計分")
                continue
            理由 = [f"🔴 {x}" for x in 項["利多"]] + [f"🟢 {x}" for x in 項["利空"]]
            st.markdown(f"**{面}面 {r[面]:.0f} 分**" + ("".join(f"\n- {x}" for x in 理由) or "\n- 沒有加減分（50 分＝中性）"))


def 庫存代號():
    """有設定庫存、而且已解鎖（或沒設密碼）時，回傳庫存的代號清單。"""
    設定 = _設定()
    if "holdings" not in 設定 or not 可編輯():
        return []
    try:
        持股 = pd.read_csv(io.StringIO(str(設定["holdings"]).strip()), dtype={"代號": str})
        return list(dict.fromkeys(持股["代號"].astype(str).str.strip()))
    except Exception:
        return []


def 前後期表(歷史, 欄位, 比較們, 期名, 反向=()):
    """本期跟前幾期的數字並排，附上增減。歷史：以日期/月份為索引；欄位：{欄: (中文名, 格式)}；
    比較們：[(名稱, 往前幾期)]；反向：數字變大代表籌碼變分散的欄位（散戶、股東人數），顏色反過來。"""
    本 = 歷史.iloc[-1]
    列們 = []
    for 欄, (名, 式) in 欄位.items():
        列 = {"項目": 名, f"本期 {期名(歷史.index[-1])}": 式.format(本[欄])}
        for 比名, n in 比較們:
            if len(歷史) > n:
                舊 = 歷史.iloc[-1 - n]
                差 = 本[欄] - 舊[欄]
                色 = "🔴" if (差 > 0) != (欄 in 反向) and 差 != 0 else ("🟢" if 差 != 0 else "⚪")
                列[f"{比名} {期名(歷史.index[-1 - n])}"] = 式.format(舊[欄])
                列[f"較{比名}"] = f"{色} {('+' if 差 > 0 else '')}{式.format(差)}"
        列們.append(列)
    表格(pd.DataFrame(列們), hide_index=True, width="stretch")


@st.cache_data(ttl=30, show_spinner=False)
def 分鐘線(代號, 市場="上市", 間隔="1m", 範圍="5d"):
    try:
        return engine.盤中K線(代號, 市場, 間隔, 範圍)
    except Exception:
        return None


def _設定():
    try:
        return dict(st.secrets)
    except Exception:
        return {}


def 可編輯():
    """有設密碼時，要先解鎖才能看/改自選股。"""
    return not _密碼() or st.session_state.get("已解鎖")


自選紀錄鍵 = "_加入紀錄"  # watchlist.json 裡記每檔加入的日期與當天收盤價（不是群組）


def 自選股清單():
    """{群組名: [代號, ...]}，每個瀏覽階段只從 GitHub 讀一次。"""
    if "自選股" not in st.session_state:
        try:
            全部 = engine.讀取自選股(_設定()) or {}
        except Exception as e:
            st.caption(f"自選股暫時讀不到（{type(e).__name__}），稍後重新整理再試。")
            return {"自選股": []}
        st.session_state["自選紀錄"] = 全部.pop(自選紀錄鍵, {})
        st.session_state["自選股"] = 全部 or {"自選股": []}
    return st.session_state["自選股"]


def 自選紀錄():
    自選股清單()
    return st.session_state.get("自選紀錄", {})


def 存自選股(自選):
    舊 = {c for v in 自選股清單().values() for c in v}
    新 = {c for v in 自選.values() for c in v}
    紀錄 = {c: v for c, v in 自選紀錄().items() if c in 新}  # 移除的股票就不記了，之後重新加入會重新起算
    收盤 = 今日.set_index("代號")["收盤"]
    for c in 新 - 舊:
        if c not in 紀錄:
            紀錄[c] = {"日期": f"{dt.datetime.now(dt.timezone(dt.timedelta(hours=8))):%Y-%m-%d}",
                      "收盤": float(收盤.get(c, np.nan)) if pd.notna(收盤.get(c, np.nan)) else None,
                      "收盤日": f"{最新日:%Y-%m-%d}"}
    st.session_state["自選股"] = 自選
    st.session_state["自選紀錄"] = 紀錄
    try:
        if engine.儲存自選股({**自選, 自選紀錄鍵: 紀錄}, _設定()):
            st.toast("自選股已儲存")
        else:
            st.toast("已暫存（網站重新啟動會消失；在 Secrets 設定 GITHUB_TOKEN 就能永久保存）")
    except Exception as e:
        st.error(f"自選股存檔失敗：{e}")


def 提醒清單():
    if "到價提醒" not in st.session_state:
        try:
            st.session_state["到價提醒"] = engine.讀取提醒(_設定())
        except Exception:
            return {}
    return st.session_state["到價提醒"]


def 提醒文字(設):
    部分 = []
    if 設.get("上"):
        部分.append(f"≥{設['上']:g}")
    if 設.get("下"):
        部分.append(f"≤{設['下']:g}")
    return " ".join(部分)


@st.cache_data(ttl=3600, show_spinner=False)
def 指數K線(代號, _資料版本):
    return engine.讀取指數K線(代號)


def 跌破站回條(項們):
    if 項們:
        st.markdown('<div class="cross">' + "".join(
            f'<span class="{"dn" if 動 == "跌破" else "up"}">{"⚠️" if 動 == "跌破" else "✅"} 今天{動}{名}'
            f'{"" if 價 is None or "共振區" in 名 else f" {價:,.2f}"}</span>'
            for 動, 名, 價 in 項們) + "</div>", unsafe_allow_html=True)


價位色 = {"回檔": "#FFC24B", "缺口": "#FF8A3D", "前高低": "#BDBDBD", "整數": "#555555", "分價量": "#8F7CFF"}


def 支撐壓力圖(K, sr, 區們, 天數=120, 高=440, 均線們=((20, 青, "月線"), (60, "#FF00E5", "季線"), (120, "#FFC24B", "半年線"))):
    """K 線＋均線＋自動畫的支撐壓力線：黃＝費波那契回檔、橘＝未回補缺口、白＝前高前低、灰＝整數關卡，青色色帶＝共振區。"""
    k = K.tail(天數 + 240).reset_index(drop=True)
    for n, _, _ in 均線們:
        k[f"MA{n}"] = k["close"].rolling(n).mean()
    k = k.tail(天數)
    收 = sr["收盤"]
    小數 = 0 if 收 > 1000 else 2
    有K = engine.有開高低(k)
    圖 = go.Figure()
    if 有K:
        圖.add_trace(go.Candlestick(x=k["date"], open=k["open"], high=k["high"], low=k["low"], close=k["close"], name="K 線",
                                    increasing=dict(line=dict(color=紅, width=1), fillcolor=紅),
                                    decreasing=dict(line=dict(color=綠, width=1), fillcolor=綠)))
    else:
        圖.add_trace(go.Scatter(x=k["date"], y=k["close"], name="收盤", line=dict(color="#EDEDED", width=1.4)))
    for n, 色, 名 in 均線們:
        圖.add_trace(go.Scatter(x=k["date"], y=k[f"MA{n}"], name=名, line=dict(color=色, width=1.1), hoverinfo="skip"))
    低, 高_ = float(k["low"].min()), float(k["high"].max())
    下界, 上界 = min(低, 收 * 0.94), max(高_, 收 * 1.06)
    for z in 區們:
        if z["上"] >= 下界 and z["下"] <= 上界:
            寬 = max(z["上"] - z["下"], 收 * 0.002)
            圖.add_hrect(y0=z["中"] - 寬 / 2 - 收 * 0.001, y1=z["中"] + 寬 / 2 + 收 * 0.001, fillcolor=青, opacity=0.13,
                         line_width=0, layer="below")
    for 下, 上, 日, 向 in sr["缺口"]:
        if 上 >= 下界 and 下 <= 上界:
            圖.add_shape(type="rect", x0=日, x1=k["date"].iloc[-1], y0=下, y1=上, fillcolor="#FF8A3D", opacity=0.12,
                         line_width=0, layer="below")
    線們 = sr["價位"][(sr["價位"]["類別"] != "均線") & sr["價位"]["價位"].between(下界, 上界)].sort_values("價位")
    標籤們 = []   # 很靠近的價位合併成一個標籤，避免字疊在一起
    for _, r in 線們.iterrows():
        色 = 價位色.get(r["類別"], 灰)
        圖.add_hline(y=r["價位"], line=dict(color=色, width=1, dash="dot" if r["類別"] in ("整數", "前高低") else "dash"))
        if 標籤們 and r["價位"] - 標籤們[-1]["價"] < (上界 - 下界) * 0.05:
            標籤們[-1]["名"].append(r["名稱"])
        else:
            標籤們.append({"價": r["價位"], "名": [r["名稱"]], "色": 色})
    for t in 標籤們:
        圖.add_annotation(x=1, xref="paper", xanchor="right", y=t["價"], yanchor="bottom", showarrow=False,
                          text=f"{'／'.join(t['名'])} {t['價']:,.{小數}f}", font=dict(size=10, color=t["色"]),
                          bgcolor="rgba(0,0,0,0.55)")
    分量 = sr.get("分價量")
    if 分量:   # 左側橫條＝分價量（近 120 日每個價位累積的成交金額），條越長越多人在這裡買賣
        t = 分量["表"]
        圖.add_trace(go.Bar(x=t["量"], y=t["中"], orientation="h", xaxis="x2", width=(t["上"] - t["下"]) * 0.9,
                            marker=dict(color=["#8F7CFF" if 分量["VAL"] <= y <= 分量["VAH"] else "#3A3550" for y in t["中"]]),
                            opacity=0.35, name="分價量", hovertemplate="%{y:,.0f} 附近<br>成交 %{x:,.0f} 億<extra>分價量</extra>"))
        圖.update_layout(xaxis2=dict(overlaying="x", side="top", range=[0, float(t["量"].max()) * 4], visible=False,
                                     fixedrange=True))
    圖.add_hline(y=收, line=dict(color="#FFFFFF", width=1), opacity=0.35)
    缺日 = pd.bdate_range(k["date"].min(), k["date"].max()).difference(pd.DatetimeIndex(k["date"]))
    圖.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]), dict(values=list(缺日))])
    圖.update_yaxes(range=[下界 * 0.995, 上界 * 1.005], side="right")
    圖.update_layout(xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.06, x=0))
    return 圖表外觀(圖, 高)


def 量價條(量價):
    """最近 5 天的量價標籤，最後一個是今天，附白話。"""
    if not 量價:
        return
    色 = lambda 標: 紅 if 標.startswith("價漲") else (綠 if 標.startswith("價跌") else "#BDBDBD")
    片們 = [f'<span class="{"now" if i == len(量價) - 1 else ""}">{d:%m/%d}<b style="color:{色(標)}">{標}</b></span>'
           for i, (d, 標, 比) in enumerate(量價)]
    d, 標, 比 = 量價[-1]
    st.markdown(f'<div class="pv"><span style="border:0;background:none;padding-left:0">量價</span>{"".join(片們)}</div>'
                f'<div class="verdict sub">{d:%m/%d} {標}：{engine.量價說明[標]}（成交金額是前 5 日平均的 {比:.2f} 倍）</div>',
                unsafe_allow_html=True)


def 黑K卡(黑):
    類 = {"🟢": "g", "🟡": "y", "🔴": "r"}.get(黑["燈"], "y")
    return (f'<div class="lamp {類}" style="margin:6px 0"><div class="t"><i>{黑["燈"]}</i>黑 K 一半規則</div>'
            f'<div class="s">{黑["日期"]:%m/%d} 大黑 K（開 {黑["開"]:,.2f}／收 {黑["收"]:,.2f}）：{黑["狀態"]}</div></div>')


def 燈號卡(項們):
    類 = {"🟢": "g", "🟡": "y", "🔴": "r"}
    return '<div class="lamps">' + "".join(
        f'<div class="lamp {類.get(燈, "y")}"><div class="t"><i>{燈}</i>{名}</div><div class="s">{說}</div></div>'
        for 名, 燈, 說 in 項們) + "</div>"


def 價位卡片(sr, 解, 昨收=None):
    收 = sr["收盤"]
    小數 = 0 if 收 > 1000 else 2
    漲 = 收 - 昨收 if 昨收 else None
    卡們 = [卡片(f"收盤 · {sr['日期']:%m/%d}", f"{收:,.{小數}f}",
                (f"{漲:+,.{小數}f}（{漲 / 昨收 * 100:+.2f}%）・" if 漲 is not None else "")
                + f"站上 {len(解['站上'])}／跌破 {len(解['跌破'])} 條均線", 漲跌色(漲) if 漲 is not None else "#EDEDED")]
    for 名, r, 色 in (("最近支撐", 解["最近支撐"], 綠), ("最近壓力", 解["最近壓力"], 紅)):
        卡們.append(卡片(名, "—" if r is None else f"{r['價位']:,.{小數}f}",
                       "" if r is None else f"{r['名稱']}・{r['距離%']:+.1f}%", 色))
    卡片格(卡們)


def 價位明細(sr, 區們, key):
    t = sr["價位"].copy()
    共 = {n for z in 區們 for n in z["成員"]}
    t["共振"] = t["名稱"].map(lambda n: "◆" if n in 共 else "")
    t = t[["角色", "名稱", "價位", "距離%", "共振", "說明"]]
    表格(t.style.map(lambda v: f"color:{紅 if v == '壓力' else 綠}", subset=["角色"])
                 .format({"價位": "{:,.2f}", "距離%": "{:+.2f}"}), hide_index=True, width="stretch",
                 height=min(35 * (len(t) + 1) + 3, 520), key=key,
                 column_config={"說明": st.column_config.TextColumn(width="large")})


def 缺口表(K, key):
    t = engine.缺口清單(K)
    if t.empty:
        st.caption("目前沒有還沒回補的缺口。")
        return
    表格(t.style.map(lambda v: f"color:{綠 if '支撐' in v else 紅}", subset=["方向"])
                 .format({"日期": "{:%Y/%m/%d}", "下緣": "{:,.2f}", "上緣": "{:,.2f}", "缺口大小%": "{:.2f}",
                          "距離%": "{:+.1f}"}), hide_index=True, width="stretch",
                 height=min(35 * (len(t) + 1) + 3, 400), key=key)
    st.caption(f"共 {len(t)} 個還沒回補的缺口，依離目前價位遠近排列。距離＝最先會碰到的那一邊（下方缺口看上緣、上方缺口看下緣）。"
               "後來的 K 線碰到一部分，缺口會跟著縮小；整個碰到就算回補，從清單移除。")


@st.cache_data(ttl=600, show_spinner=False)
def 券商報告清單(_快取鍵):
    return engine.讀取券商報告(_設定())


def 個股價格(代號):
    """驗收用的每日價格（date, high, low, 收盤）：先用常駐的近一年資料，沒有再讀這檔全史。"""
    t = 指標[指標["代號"] == str(代號)]
    if len(t) < 5:
        全 = 個股全史(str(代號), _版本)
        t = 全 if 全 is not None else t
    return t[["date", "high", "low", "收盤"]] if len(t) else None


@st.cache_data(ttl=600, show_spinner=False)
def 網紅說法清單(_快取鍵):
    return engine.讀取網紅說法(_設定())


def 張(股):
    return 股 / 1000



# ---------- 各頁內容在 views/ 資料夾（一頁一個檔案，只執行目前這一頁） ----------
def 執行頁面(索引):
    檔 = Path(__file__).parent / "views" / f"{頁面檔[索引]}.py"
    exec(compile(檔.read_text("utf-8"), str(檔), "exec"), globals())


執行頁面(頁面們.index(頁面))


@st.cache_data(ttl=3600, show_spinner=False)
def 新鮮度表(_版本):
    return engine.資料新鮮度()


_鮮 = 新鮮度表(_版本)
_落後 = (~_鮮["狀態"].str.startswith("✅")).sum()
with st.expander(f"🩺 資料新鮮度：{'全部正常' if not _落後 else f'{_落後} 項落後'}", expanded=bool(_落後)):
    表格(_鮮, hide_index=True, width="stretch")
    st.caption("每日資料跟最新交易日比；月營收、內部人、季報看距離該期結束多久。休市日不算落後。")

st.markdown(f'<div class="sub" style="color:{灰};font-family:JetBrains Mono;font-size:11px;margin-top:30px">'
            '僅供個人研究，不構成投資建議 // DATA: TWSE · TPEx</div>', unsafe_allow_html=True)
