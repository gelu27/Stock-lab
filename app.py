# 台股觀測站 v2：市場總覽、自訂選股、歷史回測
# 執行方式：streamlit run app.py

import datetime as dt
import hmac
import io
import urllib.parse

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import importlib

import engine

importlib.reload(engine)  # 程式更新後確保用的是最新版的計算規則

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
.grid3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
.grid3 .card .v {{ font-size: clamp(17px, 4.6vw, 28px); }}
.grid3 .card .k {{ font-size: clamp(9px, 2.4vw, 11px); letter-spacing: .1em; }}
.grid3 .card .d {{ font-size: clamp(10px, 2.6vw, 12px); }}
.grid3 .card {{ padding: 10px 10px; }}
.rankwrap {{ overflow-x: auto; }}
@media (max-width: 480px) {{ .rank td, .rank td.n {{ font-size: 14px; padding: 8px 6px; }} .rank th {{ padding: 8px 6px; }}
    .rank td.n small, .rank td:nth-child(5), .rank th:nth-child(5) {{ display: none; }} }}
.rank {{ width: 100%; border-collapse: collapse; font-family: 'Noto Sans TC', sans-serif; }}
.rank th {{ background: #141414; color: #9A9A9A; font-weight: 400; padding: 8px 10px; text-align: right;
    font-size: 14px; }}
.rank th:first-child, .rank td:first-child {{ text-align: center; }}
.rank td {{ padding: 9px 10px; border-bottom: 1px solid #1E1E1E; text-align: right;
    font-family: 'JetBrains Mono', monospace; font-size: 16px; }}
.rank td.n {{ font-family: 'Noto Sans TC', sans-serif; color: #EDEDED; font-size: 16px; white-space: nowrap; }}
.rank td.n small {{ color: {灰}; font-size: 11px; margin-left: 4px; font-family: 'JetBrains Mono'; }}
.rank td.n a {{ color: inherit; text-decoration: none; }}
.rank td.t {{ color: #EDEDED; white-space: nowrap; font-size: 13px; }}
.rank td.t small {{ color: {灰}; margin-left: 4px; font-size: 11px; }}
</style>
""", unsafe_allow_html=True)


def 卡片(標題, 數值, 小字="", 顏色="#EDEDED"):
    return (f'<div class="card"><div class="k">{標題}</div>'
            f'<div class="v" style="color:{顏色}">{數值}</div><div class="d" style="color:{顏色}">{小字}</div></div>')


def 卡片列(卡們):
    for 欄, 卡 in zip(st.columns(len(卡們)), 卡們):
        欄.markdown(卡, unsafe_allow_html=True)


def 卡片格(卡們):
    """固定一排三格，手機上也維持兩排三欄。"""
    st.markdown(f'<div class="grid3">{"".join(卡們)}</div>', unsafe_allow_html=True)


def 排行表(表, 額外=None):
    """額外欄位：週轉率、鎖死（漲跌停的首次觸及與鎖死時間）。"""
    標題額外 = {"週轉率": "週轉率", "鎖死": "觸及 / 鎖死"}.get(額外, "")
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
        else:
            加 = ""
        列們.append(
            f'<tr><td class="n"><a href="?s={r["code"]}{登入參數()}" target="_self">{r["name"]}<small>{r["code"]}</small></a></td>'
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
    欄們 = [c for c in ["漲跌幅", "5日漲幅", "20日漲幅", "報酬率(%)", "今日損益", "總損益", "法人(張)"] if c in 表.columns]
    整數 = {"成交張數", "今日損益", "總損益", "股數", "總成本", "法人(張)", "市值億"}
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

st.markdown("""<div class="hero"><div class="kicker">TAIWAN STOCK EXCHANGE // PERSONAL LAB</div>
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
a, b = st.columns([4, 1])
a.caption(f"📅 資料日期 {最新日:%Y/%m/%d}　·　資料庫最後更新 {最後更新()}（每個交易日約 18:00 自動更新）")
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
市場對照 = dict(zip(今日["代號"], 今日["市場"]))
有籌碼 = "法人買超" in 指標.columns

# ---------- 選股條件（04 選股與 05 組合回測共用，原本在左側欄） ----------
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
頁面們 = ["01 / 市場總覽", "02 / 我的股票", "03 / 個股查詢", "04 / 選股", "05 / 回測", "06 / 每日評分"]
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


def 登入參數():
    k = st.query_params.get("k")
    隱 = st.query_params.get("hide")
    return (f"&k={k}" if k and st.session_state.get("已解鎖") else "") + (f"&hide={urllib.parse.quote(隱)}" if 隱 else "")


if "k" in st.query_params:
    if 憑證有效(st.query_params["k"]):
        st.session_state["已解鎖"] = True
    else:
        del st.query_params["k"]

if "s" in st.query_params:  # 排行榜的連結：?s=2330
    前往(st.query_params["s"])
    del st.query_params["s"]
st.session_state.pop("要跳轉", None)
if st.session_state.get("頁面") not in 頁面們:
    st.session_state["頁面"] = 頁面們[0]
頁面 = st.segmented_control("頁面", 頁面們, key="頁面", label_visibility="collapsed") or 頁面們[0]


def 點選表(表, 樣式, key, **參數):
    """可以點選列的表格：點一下就跳到那檔股票的個股查詢。"""
    def 點了():
        列們 = st.session_state[key].selection.rows
        if 列們:
            前往(表.iloc[列們[0]]["代號"])
    st.dataframe(樣式, key=key, on_select=點了, selection_mode="single-row", hide_index=True, width="stretch", **參數)

@st.cache_data(ttl=3600, show_spinner=False, max_entries=100)
def 抓新聞(代號, 名稱):
    return engine.個股新聞(代號, 名稱)


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
        以前 = 去年四季 / (舊["收盤"].iloc[0] / 舊["淨值比"].iloc[0]) * 100
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
                  ("月營收年增", 數(g("營收年增率"), 尾="%")), ("累計營收年增", 數(g("累計營收年增率"), 尾="%")),
                  ("單季毛利率", 數(g("毛利率"), 尾="%")), ("毛利率較上季", 數(g("毛利率季增"), "{:+.1f}", " pt")),
                  ("營業利益率", 數(g("營益率"), 尾="%")), ("營益率較上季", 數(g("營益率季增"), "{:+.1f}", " pt")),
                  ("營益率較去年", 數(g("營益率年增"), "{:+.1f}", " pt"))]),
    ]
    if 有籌碼:
        基本.append(("籌碼面", [("外資", 數(r["外資買超"], "{:+,.0f}", " 張")), ("投信", 數(r["投信買超"], "{:+,.0f}", " 張")),
                             ("自營商", 數(r["自營買超"], "{:+,.0f}", " 張")), ("法人 5 日", 數(r["法人5日買超"], "{:+,.0f}", " 張")),
                             ("法人 10 日", 數(r["法人10日買超"], "{:+,.0f}", " 張")), ("外資連買", 數(r["外資連買"], "{:.0f}", " 天")),
                             ("投信連買", 數(r["投信連買"], "{:.0f}", " 天")), ("融資餘額", 數(r["融資餘額"], "{:,.0f}", " 張")),
                             ("融資 5 日", 數(r["融資5日增減"], "{:+.1f}", "%"))]))
    基本.append(("技術面", [(f"{n} 日線", 數(r[f"MA{n}"] * 比)) for n in (5, 10, 20, 60)] + [
        ("RSI(14)", 數(r["RSI"], "{:.1f}")), ("20 日漲幅", 數(r["20日漲幅"], "{:+.2f}", "%")),
        ("距 52 週高點", 數(r["距52週高點"], "{:+.1f}", "%")), ("箱頂", 數(r["箱頂"])), ("箱底", 數(r["箱底"]))]))
    資料 = {"收盤": float(r["收盤"]), "漲跌": float(r["漲跌"]), "漲跌幅": float(r["漲跌幅"]), "日期": 最新日.strftime("%Y-%m-%d"),
            "產業": g("產業"), "市場": r["市場"], "卡片": 卡們, "基本資料": 基本, "判讀": engine.規則判讀(r),
            "歷史": 個股全史(代號, _版本), "營收": engine.讀取營收歷史(代號), "損益": engine.單季損益(代號),
            "建議": 建議, "報告": 內文, "報告時間": 時間}
    try:
        h, 週轉, 大 = 變化資料(代號, 126)
        資料["變化"] = {"歷史": h, "週轉": 週轉, "大戶": 大, "解讀": engine.變化解讀(h, 週轉, 大)}
    except Exception:
        pass
    return report.產生PDF(代號, r["名稱"], 資料)



# ---------- 每日評分（規則打分數，網站與 LINE 收盤摘要共用 engine 的規則） ----------
@st.cache_resource(max_entries=1, show_spinner="計算每日評分中…")
def 評分資料(_資料版本):
    return engine.今昨評分(指標[指標["date"] >= 指標["date"].max() - pd.Timedelta(days=20)],
                         engine.讀取基本面(), 加權)


def 分數色(分):
    if pd.isna(分):
        return 灰
    return 紅 if 分 >= 58 else (綠 if 分 <= 42 else 灰)


def 評分表(代號們=None, 篩選=None):
    """總分、各面向分數與較昨日變化，代號們給了就照那個順序。"""
    分 = 評分資料(_版本)[0]
    表 = 分.reindex(list(代號們)) if 代號們 is not None else 分
    if 篩選 is not None:
        表 = 表[篩選(表)]
    表 = 表.dropna(subset=["總分"]).reset_index(names="代號")
    return 表[["名稱", "總分", "較昨日", "看法", "技術", "籌碼", "基本", "市場", "收盤", "漲跌幅", "產業", "代號"]]


def 評分樣式(表):
    分欄 = [c for c in ("總分", "技術", "籌碼", "基本", "市場") if c in 表.columns]
    格式 = {c: "{:.0f}" for c in 分欄} | {"較昨日": "{:+.0f}", "收盤": "{:,.2f}", "漲跌幅": "{:+.2f}"}
    return (表.style.map(lambda v: f"color:{分數色(v)}", subset=分欄)
            .map(lambda v: f"color:{漲跌色(v)}", subset=[c for c in ("較昨日", "漲跌幅") if c in 表.columns])
            .format({k: v for k, v in 格式.items() if k in 表.columns}, na_rep="—"))


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
    st.dataframe(pd.DataFrame(列們), hide_index=True, width="stretch")


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
    股 = engine._股本表()
    股數 = 股.at[代號, "發行股數"] if 代號 in 股.index else np.nan
    週轉 = 歷史["volume"] / 股數 * 100 if pd.notna(股數) and 股數 else pd.Series(np.nan, index=歷史.index)
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


# ---------- 01 市場總覽 ----------
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
    if 密碼:
        a, b = st.columns([4, 1])
        a.caption("已記住登入（網址裡的 k=… 就是通行證，請勿分享登入後的網址）。可把這個網址加入書籤或主畫面。")
        if b.button("🔒 登出", key="登出"):
            st.session_state["已解鎖"] = False
            st.query_params.pop("k", None)
            st.rerun()


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
    卡片列([
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
    點選表(明細, 上色(明細), "庫存表", height=35 * (len(明細) + 1) + 3)
    if st.session_state.get("要跳轉"):
        st.rerun(scope="app")  # 這裡在自動更新區塊裡，要整頁重跑才會切到個股查詢
    st.caption("點一下股票可看個股查詢，也可以直接點表格標題排序。")
    if 合計["缺報價"]:
        st.caption(f"以下代號暫時沒有報價，未計入合計：{'、'.join(合計['缺報價'])}")


@st.cache_data(ttl=30, show_spinner=False)
def 分鐘線(代號, 市場="上市", 間隔="1m", 範圍="5d"):
    try:
        return engine.盤中K線(代號, 市場, 間隔, 範圍)
    except Exception:
        return None


@st.fragment(run_every=30 if engine.盤中時間() else None)
def 加權圖():
    段落("TAIEX // 加權指數走勢")
    區間 = st.segmented_control("區間", ["當日", "5日", "1月", "1季", "半年", "1年", "3年", "5年"],
                              default="當日", key="加權區間", label_visibility="collapsed") or "當日"
    分時 = engine.讀取分時()
    即時點 = None
    if engine.盤中時間():
        try:
            即時點 = engine.即時報價(["t00"], {})
        except Exception:
            pass
        if 即時點 is not None and not 即時點.empty:
            r = 即時點.iloc[0]
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


def _設定():
    try:
        return dict(st.secrets)
    except Exception:
        return {}


def 可編輯():
    """有設密碼時，要先解鎖才能看/改自選股。"""
    return not _密碼() or st.session_state.get("已解鎖")


def 自選股清單():
    """{群組名: [代號, ...]}，每個瀏覽階段只從 GitHub 讀一次。"""
    if "自選股" not in st.session_state:
        try:
            st.session_state["自選股"] = engine.讀取自選股(_設定()) or {"自選股": []}
        except Exception as e:
            st.caption(f"自選股暫時讀不到（{type(e).__name__}），稍後重新整理再試。")
            return {"自選股": []}
    return st.session_state["自選股"]


def 存自選股(自選):
    st.session_state["自選股"] = 自選
    try:
        if engine.儲存自選股(自選, _設定()):
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


def 存提醒(提醒):
    st.session_state["到價提醒"] = 提醒
    try:
        if engine.儲存提醒(提醒, _設定()):
            st.toast("到價提醒已儲存")
        else:
            st.toast("已暫存（網站重新啟動會消失；在 Secrets 設定 GITHUB_TOKEN 就能永久保存）")
    except Exception as e:
        st.error(f"到價提醒存檔失敗：{e}")


def 提醒文字(設):
    部分 = []
    if 設.get("上"):
        部分.append(f"≥{設['上']:g}")
    if 設.get("下"):
        部分.append(f"≤{設['下']:g}")
    return " ".join(部分)


def 自選股區():
    段落("WATCHLIST // 自選股")
    自選 = 自選股清單()
    群組們 = list(自選) or ["自選股"]
    if "自選群組_切換" in st.session_state:
        st.session_state["自選群組"] = st.session_state.pop("自選群組_切換")
    if st.session_state.get("自選群組") not in 群組們:
        st.session_state["自選群組"] = 群組們[0]
    if len(群組們) > 1:
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
        新名 = a.text_input("新增群組", placeholder="例如：觀察中、想買", key="自選新群組").strip()
        if b.button("＋ 建立", key="自選建立") and 新名 and 新名 not in 自選:
            存自選股({**自選, 新名: []})
            st.session_state["自選群組_切換"] = 新名
            st.rerun()
        if len(群組們) > 1 and st.button(f"🗑 刪除「{群組}」群組", key="自選刪除"):
            存自選股({k: v for k, v in 自選.items() if k != 群組})
            st.rerun()


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
    顯示 = 表[["名稱", "收盤", "漲跌幅", "提醒", "成交張數", "5日漲幅", "20日漲幅", "法人買超", "本益比", "殖利率", "代號"]]
    顯示 = 顯示.rename(columns={"收盤": "股價", "法人買超": "法人(張)"})
    點選表(顯示, 上色(顯示), "自選表", height=35 * (len(顯示) + 1) + 3)
    if st.session_state.get("要跳轉"):
        st.rerun(scope="app")
    st.caption("點一下股票可看個股查詢。法人(張) = 三大法人今日買賣超。🔔 = 已到達提醒價格（到價提醒在個股頁設定）。")


@st.cache_data(ttl=3600, show_spinner=False, max_entries=50)
def 集保資料(代號):
    return engine.讀取集保(代號)


@st.cache_data(ttl=300, show_spinner=False)
def 抓國際():
    return engine.國際行情(), engine.台指期()


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
    a, b = st.columns(2)
    期間 = a.segmented_control("漲跌期間", list(engine.族群期間), default="今日", key="族群期間") or "今日"
    大小 = b.segmented_control("方塊大小", ["市值", "成交值"], default="市值", key="族群大小") or "市值"
    族群, 個股 = engine.族群資料(今日, 期間, 大小)
    界 = {"今日": 5, "5 日": 10, "20 日": 20}[期間]
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

    表 = 族群.reset_index().rename(columns={"產業": "族群"})[
        ["族群", "漲跌幅", "上漲", "下跌", "成交值億", "領漲股"]]
    st.markdown("**族群排行**　點一下族群，下方會列出成分股")
    選 = st.dataframe(表.style.map(lambda v: f"color:{漲跌色(v)}", subset=["漲跌幅"])
                     .format({"漲跌幅": "{:+.2f}%", "成交值億": "{:,.1f}"}),
                     key="族群表", on_select="rerun", selection_mode="single-row", hide_index=True,
                     width="stretch", height=300)
    列們 = 選.selection.rows
    if 列們:
        族 = 表.iloc[列們[0]]["族群"]
        欄 = engine.族群期間[期間]
        成分 = 今日[(今日["產業"] == 族) & (今日["收盤"] > 0)].sort_values(欄, ascending=False)
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
              "融資": ("融資餘額（張）", "{:,.0f}"), "匯率": ("美元/台幣", "{:.3f}")}
        欄位 = {k: v for k, v in 欄位.items() if k in 每日.columns and 每日[k].notna().iloc[-1]}
        with st.expander("📊 前後期比較（昨日、5 日前、20 日前、60 日前）", expanded=True):
            前後期表(每日, 欄位, [("昨日", 1), ("5 日前", 5), ("20 日前", 20), ("60 日前", 60)],
                     lambda d: f"{d:%m/%d}", 反向={"下跌", "融資", "匯率"})
            st.caption("🔴 偏多：指數、成交、上漲家數、法人買超變多，融資減少、台幣升值；🟢 反之。"
                       "外資／法人金額用買賣超張數 × 收盤價估算。")


def 排行區():
    段落("RANKING // 排行（前 50 檔，含上市櫃）")
    排行 = engine.排行資料(今日)
    漲停數, 跌停數 = int(排行["漲停"].sum()), int(排行["跌停"].sum())
    榜 = st.tabs(["漲幅", "跌幅", "成交量", "成交值", "週轉率", f"漲停 {漲停數}", f"跌停 {跌停數}"])
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
    st.caption("觸及 / 鎖死：第一次碰到漲跌停的時間 / 最後一次鎖住到收盤的時間（「未鎖住」表示收盤前又打開），"
               "依 Yahoo 1 分鐘線計算，可能有幾分鐘誤差。")


首頁區塊 = ["市場", "國際", "加權指數", "族群", "排行"]

if 頁面 == 頁面們[0]:
    隱藏 = [x for x in st.query_params.get("hide", "").split(",") if x in 首頁區塊]
    with st.expander("⚙️ 首頁要顯示哪些區塊"):
        顯示 = st.pills("首頁區塊", 首頁區塊, selection_mode="multi", key="首頁區塊", label_visibility="collapsed",
                       default=[x for x in 首頁區塊 if x not in 隱藏])
        st.caption("點一下開關。關掉不常看的區塊，首頁會比較短、也開得比較快；設定記在網址裡，加入書籤就會保留。")
    新隱藏 = ",".join(x for x in 首頁區塊 if x not in 顯示)
    if 新隱藏 != ",".join(隱藏):
        if 新隱藏:
            st.query_params["hide"] = 新隱藏
        else:
            st.query_params.pop("hide", None)
    if "市場" in 顯示:
        市場卡片()
    if "國際" in 顯示:
        try:
            國際行情()
        except Exception:
            st.caption("國際行情暫時無法顯示。")
    if "加權指數" in 顯示 and 加權 is not None and len(加權) > 1:
        加權圖()
    if "族群" in 顯示:
        族群熱力圖()
    if "排行" in 顯示:
        排行區()

# ---------- 02 我的股票：庫存、自選股 ----------
if 頁面 == 頁面們[1]:
    我的庫存()
    if 可編輯():
        自選股區()
    else:
        st.caption("自選股要先輸入上面的密碼解鎖才會顯示。")

# ---------- 04 選股 ----------
if 頁面 == 頁面們[3]:
  選股分頁 = st.tabs(["條件選股", "烏賊每日功課", "烏賊策略總覽"])
  with 選股分頁[2]:
    總表, 名單, 重複 = engine.烏賊總覽(今日)
    多 = 總表[總表["多空"] == "多"]["符合檔數"].sum()
    空 = 總表[總表["多空"] == "空"]["符合檔數"].sum()
    卡片格([卡片("多方策略符合", f"{多}", "檔次（可能重複）", 紅), 卡片("空方策略符合", f"{空}", "檔次（可能重複）", 綠),
           卡片("同時符合 2 個以上", f"{len(重複)}", "檔", 青)])
    st.caption("多＝適合找買點（講義：強勢股買拉回、盤整突破）；空＝轉弱、避開或減碼（講義：跌破十日線、弱勢股）。"
               "資料日期 " + 最新日.strftime("%Y-%m-%d"))
    段落("SUMMARY // 各策略符合檔數")
    st.dataframe(總表.style.map(lambda v: f"color:{紅 if v == '多' else 綠}", subset=["多空"]),
                 hide_index=True, width="stretch",
                 column_config={"說明": st.column_config.TextColumn(width="large")})
    段落("OVERLAP // 同時符合多個策略")
    if 重複.empty:
        st.write("今天沒有股票同時符合 2 個以上的策略。")
    else:
        點選表(重複, 上色(重複).map(lambda v: f"color:{紅 if v == '多' else (綠 if v == '空' else '#FFC24B')}",
                                subset=["多空"]), "重複表")
    段落("DETAIL // 各策略名單")
    清單欄 = ["代號", "名稱", "市場", "收盤", "漲跌幅", "成交張數", "量對5日均", "3日漲幅", "5日漲幅", "20日漲幅",
             "40日漲幅", "週轉率", "股本億", "法人5日買超", "法人10日買超", "營收年增率", "近三季EPS"]
    for 名, 結果 in 名單.items():
        方向 = engine.烏賊條件[名]["方向"]
        with st.expander(f"{'🔴 多' if 方向 == '多' else '🟢 空'}｜{名.replace('烏賊', '')}｜{len(結果)} 檔"):
            st.caption(engine.烏賊條件[名]["說明"])
            if len(結果):
                點選表(結果, 上色(結果[[c for c in 清單欄 if c in 結果.columns]]), f"策略表{名}")
  with 選股分頁[1]:
    st.caption("講義「每天的功課」：每天看這六張榜，熟悉股性。三&五日強勢股的重點是找貼近 5 日或 10 日線、"
               "均線剛勾起來的股票（★）；股本小、量大、有題材最好。")
    功課 = engine.每日功課(今日)
    功課欄 = [c for c in ["代號", "名稱", "市場", "收盤", "漲跌幅", "3日漲幅", "5日漲幅", "振幅", "成交張數",
                        "量對5日均", "股本億", "外資買超", "投信買超", "重點"] if c in 今日.columns or c == "重點"]
    for 標籤, 分頁表 in zip(功課, st.tabs(list(功課))):
        with 分頁表:
            表 = 功課[標籤]
            if "股本億" not in 表.columns:
                表 = 表.join(engine._股本表(), on="代號")
            點選表(表, 上色(表[[c for c in 功課欄 if c in 表.columns]]), f"功課表{標籤}", height=420)
    with st.expander("課程重點：盤整、上升、下降趨勢怎麼操作"):
        st.markdown("""
- **盤整格局**：找出最高點與最低點畫成箱型（框框），注意箱子左右兩邊爆量的日子；**收盤突破箱頂**、量放大是轉強訊號。
- **上升趨勢**：沿著 5 日、10 日線走，突破前波高點後一路墊高；**怎麼買？靠近昨天高點買**，強勢股別人追高，你買拉回點。
- **下降趨勢**：**跌破十日線後**轉弱，反彈到壓力就該小心；弱勢股別人追空，你買反彈點。
- **五分 K**：用盤中 5 分鐘 K 線找當日進出場點，避免看到大單就追或被嚇跑（本站目前只有日線資料）。
- **烏賊的話**：勇於嘗試＋嚴格停損；隔日沖反應不如預期就砍；小波段請把握反轉點或跌破關鍵價位。

這些規則已做成「個股回測」裡的 **盤整突破（烏賊）** 與 **均線勾起（烏賊）** 兩個策略，「條件選股」分頁的「策略範本」可直接套用五組選股條件。
""")
  with 選股分頁[0]:
    with st.expander("⚙️ 選股條件（組合回測也用這組）", expanded=True):
        條件, 範本 = 選股條件區()
    結果 = engine.選股(今日, 條件)
    卡片列([
        卡片("符合條件", f"{len(結果)}", "檔", 青),
        卡片("資料日期", 最新日.strftime("%Y-%m-%d")),
        卡片("排序", 條件["排序"]),
    ])
    段落("RESULT // 選股結果")
    顯示欄 = [c for c in ["代號", "名稱", "市場", "收盤", "漲跌幅", "本益比", "殖利率", "淨值比",
                        "營收年增率", "營收月增率", "累計營收年增率", "EPS", "成交張數",
                        "外資買超", "投信買超", "法人5日買超", "外資連買", "投信連買", "融資5日增減",
                        "20日漲幅", "RSI", "量比", "距52週高點"] if c in 結果.columns]
    if 範本 != "自訂條件":  # 烏賊條件多看幾個相關欄位
        顯示欄[3:3] = [c for c in ["週轉率", "股本億", "量對5日均", "5日均量", "10日漲幅", "30日漲幅", "40日漲幅",
                                 "法人10日買超", "近三季EPS"] if c in 結果.columns]
    點選表(結果, 上色(結果[顯示欄]), "選股表", height=420)
    st.caption("點一下任何一列，就會跳到那檔股票的個股查詢。")
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

# ---------- 05 回測 ----------
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
    卡片格(卡們)


if 頁面 == 頁面們[4]:
    回測分頁 = st.tabs(["組合回測", "個股回測"])
    with 回測分頁[0]:
        with st.expander("⚙️ 選股條件（跟 04 / 選股 共用）"):
            條件, 範本 = 選股條件區()
        st.caption("規則：每期最後一個交易日收盤後用上面的條件選股，隔日收盤價買進前 N 檔，每檔投入總資產 ÷ N；"
                   "沒入選的賣出；觸發停損停利當天收盤賣出。已計入手續費 0.1425% 與證交稅 0.3%。"
                   "月營收與 EPS 條件只有最新一期，回測時不套用。")
        最早 = engine.資料起訖()[0].date()
        a, b, c, d, e = st.columns(5)
        開始 = a.date_input("開始日期", max(最早, 最新日.date() - dt.timedelta(days=730)), min_value=最早,
                         max_value=最新日.date())
        結束 = b.date_input("結束日期", 最新日.date(), min_value=最早, max_value=最新日.date())
        調倉 = c.selectbox("調倉頻率", ["每月", "每週", "每日"])
        檔數 = d.number_input("最多持有檔數", 1, 50, 10)
        資金 = e.number_input("初始資金", 100_000, 100_000_000, 1_000_000, step=100_000)
        a, b = st.columns(2)
        停損 = a.number_input("停損 %（0 代表不設）", 0.0, 50.0, 10.0, step=1.0)
        停利 = b.number_input("停利 %（0 代表不設）", 0.0, 500.0, 0.0, step=5.0)

        if st.button("▶ 開始回測"):
            with st.spinner("回測計算中…"):
                每日, 調倉日表 = engine.回測資料(開始, 結束, 調倉)
                st.session_state["回測"] = engine.回測(
                    每日, 條件, pd.Timestamp(開始), pd.Timestamp(結束), 檔數, 調倉,
                    停損 or None, 停利 or None, 資金, 選股資料=調倉日表)
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
                st.dataframe(上色(報告["交易"]), hide_index=True, width="stretch", height=360)

    with 回測分頁[1]:
        st.caption("訊號在收盤後產生，隔一個交易日以收盤價成交；已計入手續費與證交稅，價格使用還原股價。")
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
        if st.button("▶ 開始個股回測"):
            st.session_state["個股回測"] = engine.個股回測(
                個股全史(標的.split()[0], _版本), 標的.split()[0], pd.Timestamp(開始2), pd.Timestamp(結束2), 策略, 短, 長, RSI下, RSI上,
                停損2 or None, 停利2 or None)
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
                st.dataframe(上色(交易), hide_index=True, width="stretch")


# ---------- 03 個股查詢 ----------
if 頁面 == 頁面們[2]:
    if st.session_state.get("個股查詢") not in 股票選項:
        st.session_state["個股查詢"] = next((v for v in 股票選項 if v.startswith("2330 ")), 股票選項[0])
    查詢 = st.selectbox("輸入代號或名稱查詢", 股票選項, key="個股查詢")
    代號 = 查詢.split()[0]
    r = 今日[今日["代號"] == 代號].iloc[0]
    股 = engine._股本表()
    if "股本億" not in 今日.columns and 代號 in 股.index:
        r = pd.concat([r, 股.loc[代號]])
    數 = lambda v, f="{:,.2f}", 尾="": "—" if pd.isna(v) else f.format(v) + 尾
    比 = r["收盤"] / r["還原價"] if r["還原價"] else 1  # 均線用還原價算，換回原始股價
    色 = 漲跌色(r["漲跌"])

    段落(f"PROFILE // {代號} {r['名稱']}")
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
    if 有籌碼:
        段落("CHIPS // 籌碼面（張）")
        卡片格([
            卡片("外資", 數(r["外資買超"], "{:+,.0f}"), f"連買 {數(r['外資連買'], '{:.0f}')} 天", 漲跌色(r["外資買超"])),
            卡片("投信", 數(r["投信買超"], "{:+,.0f}"), f"連買 {數(r['投信連買'], '{:.0f}')} 天", 漲跌色(r["投信買超"])),
            卡片("自營商", 數(r["自營買超"], "{:+,.0f}"), "", 漲跌色(r["自營買超"])),
            卡片("法人 5 日合計", 數(r["法人5日買超"], "{:+,.0f}"), "", 漲跌色(r["法人5日買超"])),
            卡片("法人 10 日合計", 數(r["法人10日買超"], "{:+,.0f}"), "", 漲跌色(r["法人10日買超"])),
            卡片("融資餘額", 數(r["融資餘額"], "{:,.0f}"), f"5 日 {數(r['融資5日增減'], '{:+.1f}', '%')}"),
        ])
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
            st.dataframe(顯示.style.format({"權值+息值": "{:.4g}", "除權息前收盤": "{:,.2f}", "參考價": "{:,.2f}"}),
                         hide_index=True, width="stretch", height=min(35 * (len(顯示) + 1) + 3, 320))
            st.caption("填息天數 = 除權息後，收盤價回到除權息前收盤價花了幾個交易日。資料：證交所、櫃買中心（近 6 年）。")

    段落("CHART // 走勢與指標")
    週期 = st.segmented_control("週期", ["當日", "5分", "日", "週", "月", "季"], default="日", key="個股週期",
                              label_visibility="collapsed") or "日"
    可選 = ["成交量", "三大法人", "外資", "投信", "自營商", "融資", "RSI", "MACD"] if 有籌碼 else ["成交量", "RSI", "MACD"]
    if 週期 in ("當日", "5分"):
        可選 = ["成交量", "RSI", "MACD"]
    指標們 = st.multiselect("下方指標", 可選, default=[x for x in ["成交量", "三大法人", "MACD"] if x in 可選],
                           key=f"個股指標{週期 in ('當日', '5分')}")

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

    段落("FLOW // 股價・週轉率・大戶・法人 變化")
    期間 = st.segmented_control("期間", ["3 個月", "半年", "1 年"], default="半年", key="變化期間",
                              label_visibility="collapsed") or "半年"
    變化圖(代號, r, {"3 個月": 63, "半年": 126, "1 年": 250}[期間])

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
        圖.update_layout(hovermode="x unified")
        st.plotly_chart(圖表外觀(圖, 360), width="stretch")
        st.caption("每條線 = 近四季 EPS × 本益比倍數（取過去 5 年本益比的 10%~90% 區間）。"
                   "股價在越下面的帶子代表以歷史標準看越便宜；EPS 衰退時便宜也可能是合理的。")

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
        新聞["情緒"] = 新聞["標題"].map(engine.新聞情緒)
        計 = 新聞["情緒"].value_counts()
        st.caption(f"共 {len(新聞)} 則：標題偏多 {計.get('利多', 0)}、偏空 {計.get('利空', 0)}、中性 {計.get('中性', 0)}"
                   "（依標題關鍵字粗略判斷，請點開原文確認）")
        圖示 = {"利多": "🔴", "利空": "🟢", "中性": "⚪"}
        列 = lambda x: f"- `{x['日期']:%m/%d}` {圖示[x['情緒']]} [{x['標題']}]({x['連結']}) · {x['來源']}"
        st.markdown("\n".join(列(x) for _, x in 新聞.head(15).iterrows()))
        if len(新聞) > 15:
            with st.expander(f"更多新聞（{len(新聞) - 15}）"):
                st.markdown("\n".join(列(x) for _, x in 新聞.iloc[15:].iterrows()))

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
                   f"75% {本益.quantile(.75):.1f}、最高 {本益.max():.1f}")
        if 新聞 is not None and not 新聞.empty:
            摘要 += "\n\n近半年新聞標題（新到舊）：\n" + "\n".join(
                f"- {x['日期']:%Y-%m-%d} {x['標題']}（{x['來源']}）" for _, x in 新聞.head(60).iterrows())

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
                       "已設定「台股個股分析師」Gem 或 Claude 技能的話也可以直接貼。")
            st.code(f"請分析台股 {代號} {r['名稱']}。\n\n以下是「股市觀測網站」資料庫的最新數據（以此為準）：\n{摘要}\n\n"
                    f"請上網搜尋近六個月的新聞、法說會與券商報告，依照以下要求寫報告：\n\n{engine.AI系統提示}",
                    language=None, wrap_lines=True)
        if st.session_state.get("顯示貼上") and 可寫:
            with st.form("貼上表單", clear_on_submit=True):
                來源 = st.radio("報告來自", ["Gemini App", "Claude App", "其他"], horizontal=True)
                內容 = st.text_area("把 AI 的完整回答貼在這裡（最後的 json 區塊也要一起貼，網站才能做卡片）", height=220)
                if st.form_submit_button("💾 存成這檔的 AI 報告", type="primary"):
                    if len(內容.strip()) < 50:
                        st.warning("內容太短，請貼上完整的報告。")
                    else:
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
                    卡片("停損參考", 數(價("停損"), "{:,.0f}"), "", 綠),
                ])
                if 建議.get("一句話"):
                    st.markdown(f"**AI 結論：** {建議['一句話']}")
            with st.expander("完整 AI 報告", expanded=not 建議):
                st.markdown(內文)
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

# ---------- 06 每日評分 ----------
if 頁面 == 頁面們[5]:
    分, d, 大 = 評分資料(_版本)
    段落(f"MARKET // 大盤評分　{大['日期']:%Y/%m/%d}")
    數 = 大["數字"]
    變 = 大.get("較昨日", np.nan)
    卡片格([
        卡片("大盤分數", f"{大['分數']}", 大["看法"] + ("" if pd.isna(變) else f" · 較昨日 {變:+.0f}"), 分數色(大["分數"])),
        卡片("上漲 / 下跌", f"{數.get('上漲', 0)} / {數.get('下跌', 0)}", "上市櫃普通股家數"),
        卡片("外資買賣超", "—" if "外資億" not in 數 else f"{數['外資億']:+,.0f} 億", "依收盤價估算金額",
           漲跌色(數.get("外資億", 0))),
    ])
    a, b = st.columns(2)
    a.markdown("**🔴 加分**" + ("".join(f"\n- {x}" for x in 大["利多"]) or "\n- 無"))
    b.markdown("**🟢 扣分**" + ("".join(f"\n- {x}" for x in 大["利空"]) or "\n- 無"))

    庫 = 庫存代號()
    if 庫:
        段落("PORTFOLIO // 我的庫存評分")
        表 = 評分表(庫).sort_values("總分", ascending=False)
        點選表(表, 評分樣式(表), "庫存評分表", height=35 * (len(表) + 1) + 3)
    if 可編輯():
        自選 = list(dict.fromkeys(c for v in 自選股清單().values() for c in v if c not in 庫))
        if 自選:
            段落("WATCHLIST // 自選股評分")
            表 = 評分表(自選).sort_values("總分", ascending=False)
            點選表(表, 評分樣式(表), "自選評分表", height=35 * (len(表) + 1) + 3)

    段落("RANKING // 評分排行")
    a, b = st.columns([3, 2])
    市場們 = a.pills("市場", ["上市", "上櫃"], selection_mode="multi", default=["上市", "上櫃"], key="評分市場")
    含ETF = b.toggle("包含 ETF", key="評分ETF")
    篩 = lambda t: (t["5日均量"] >= 500) & t["上市櫃"].isin(市場們 or ["上市", "上櫃"]) & (含ETF | ~t.index.str.startswith("00"))
    for 標籤, 分頁 in zip(["高分", "低分", "分數進步", "分數退步"], st.tabs(["高分榜", "低分榜", "分數進步", "分數退步"])):
        with 分頁:
            表 = 評分表(篩選=篩)
            欄, 小到大 = {"高分": ("總分", False), "低分": ("總分", True), "分數進步": ("較昨日", False),
                       "分數退步": ("較昨日", True)}[標籤]
            表 = 表.sort_values([欄, "總分"], ascending=[小到大, 小到大], na_position="last").head(30)
            點選表(表, 評分樣式(表), f"評分榜{標籤}", height=35 * 31 + 3)
    st.caption("排行只列五日均量 500 張以上的股票（避免冷門股）。點一下股票可看個股查詢。")

    段落("CHECK // 單檔評分明細")
    選 = st.selectbox("輸入代號或名稱", 股票選項, key="評分查詢",
                     index=next((i for i, v in enumerate(股票選項) if v.startswith("2330 ")), 0))
    評分卡片(選.split()[0])
    if st.button("看這檔的個股查詢 →", key="評分前往"):
        前往(選.split()[0])
        st.rerun()

    with st.expander("📖 評分怎麼算？"):
        st.markdown(f"""
每一面都從 **50 分（中性）** 開始，符合條件就加分或扣分，最後限制在 0～100 分。
總分 = 技術面 {engine.評分權重['技術']:.0%} ＋ 籌碼面 {engine.評分權重['籌碼']:.0%} ＋ 基本面 {engine.評分權重['基本']:.0%} ＋ 市場面 {engine.評分權重['市場']:.0%}
（沒有資料的面向不算，例如 ETF 沒有營收、EPS，就只看其他三面）。

- **70 分以上 強勢**、58～69 偏多、43～57 中性、31～42 偏空、30 分以下 弱勢
- **技術面**：是否站上 20 日線、60 日線，均線多空排列，近 20 日漲跌，距 52 週高點，RSI 過熱／超賣，價量配合
- **籌碼面**：三大法人 5 日買賣超（跟成交量比）、外資／投信連買、外資今日買賣、融資增減
- **基本面**：月營收年增率、累計營收、營收創新高、近三季 EPS、毛利率比去年同季、本益比、殖利率
- **市場面**：大盤分數（指數均線、漲跌家數、外資買賣超金額）、所屬族群近 20 日強弱、近 5／20 日是否贏大盤

規則寫在 `engine.py` 的「評分規則」表，可以自己調整分數。每天收盤後的 LINE 摘要也會附上大盤與庫存的評分。
""")
    st.caption("⚠️ 分數只是把公開數據套進固定規則的結果，不含新聞、產業前景與突發事件，不構成投資建議。")

st.markdown(f'<div class="sub" style="color:{灰};font-family:JetBrains Mono;font-size:11px;margin-top:30px">'
            '僅供個人研究，不構成投資建議 // DATA: TWSE · TPEx</div>', unsafe_allow_html=True)
