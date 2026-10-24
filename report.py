# 個股分析 PDF 報告（黑底、橫式、左圖右文）
# 首頁：大字股價、重點數據卡片、AI 結論、K 線圖與解讀；後面：營收、毛利率、法人圖表各配一段白話解讀、多空清單、完整 AI 報告、數據總表
# 用 fpdf2 排版、matplotlib 畫圖，中文字型放在 fonts/（Noto Sans TC）

import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

字型夾 = Path(__file__).parent / "fonts"

# 與網站一致的配色（台股習慣：紅漲綠跌）
底色, 卡色, 線色 = "#0A0A0A", "#151515", "#2A2A2A"
字色, 次字, 淡字 = "#EDEDED", "#9A9A9A", "#5E5E5E"
紅, 綠, 青, 黃 = "#FF3B5C", "#00D68F", "#00E5FF", "#FFC145"


def _rgb(色):
    色 = 色.lstrip("#")
    return tuple(int(色[i:i + 2], 16) for i in (0, 2, 4))


def _漲跌色(值):
    if 值 is None or pd.isna(值) or 值 == 0:
        return 字色
    return 紅 if 值 > 0 else 綠


# ---------- 圖表 ----------
def _畫布():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    路徑 = str(字型夾 / "NotoSansTC-Regular.ttf")
    if 路徑 not in [f.fname for f in font_manager.fontManager.ttflist]:
        font_manager.fontManager.addfont(路徑)
    plt.rcParams.update({
        "font.family": font_manager.FontProperties(fname=路徑).get_name(), "axes.unicode_minus": False,
        "font.size": 10, "figure.facecolor": 底色, "axes.facecolor": 底色, "savefig.facecolor": 底色,
        "axes.edgecolor": 線色, "axes.labelcolor": 次字, "xtick.color": 次字, "ytick.color": 次字,
        "text.color": 字色, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
        "grid.color": "#1E1E1E", "grid.linewidth": 0.8, "legend.labelcolor": 字色})
    return plt


def _存圖(plt, 圖):
    緩衝 = io.BytesIO()
    圖.savefig(緩衝, format="png", dpi=170, bbox_inches="tight", pad_inches=0.08)
    plt.close(圖)
    緩衝.seek(0)
    return 緩衝


def K線圖(歷史, 天數=120, 寬=9.2, 高=5.0):
    """日 K 線＋5／20／60 日線＋成交量。"""
    from matplotlib.patches import Rectangle

    plt = _畫布()
    h = 歷史.copy()
    for n in (5, 20, 60):
        h[f"均{n}"] = h["收盤"].rolling(n).mean()
    h = h.tail(天數).reset_index(drop=True)
    圖, (上, 下) = plt.subplots(2, 1, figsize=(寬, 高), sharex=True, gridspec_kw={"height_ratios": [3.2, 1], "hspace": 0.04})
    x = np.arange(len(h))
    for i, r in h.iterrows():
        色 = 紅 if r["收盤"] >= r["open"] else 綠
        上.vlines(i, r["low"], r["high"], color=色, linewidth=0.8)
        底 = min(r["open"], r["收盤"])
        上.add_patch(Rectangle((i - 0.32, 底), 0.64, max(abs(r["收盤"] - r["open"]), (r["high"] - r["low"]) * 0.01 + 1e-9),
                               facecolor=色, edgecolor=色, linewidth=0.5))
    for n, 色 in ((5, 黃), (20, 青), (60, "#B388FF")):
        上.plot(x, h[f"均{n}"], color=色, linewidth=1.1, label=f"{n} 日線")
    上.legend(loc="upper left", frameon=False, ncol=3, fontsize=9)
    上.set_xlim(-1, len(h))
    最高, 最低 = h["high"].idxmax(), h["low"].idxmin()
    上.annotate(f"{h['high'][最高]:,.2f}", (最高, h["high"][最高]), xytext=(0, 6), textcoords="offset points",
               ha="center", color=紅, fontsize=8)
    上.annotate(f"{h['low'][最低]:,.2f}", (最低, h["low"][最低]), xytext=(0, -12), textcoords="offset points",
               ha="center", color=綠, fontsize=8)
    下.bar(x, h["volume"] / 1000, color=np.where(h["收盤"] >= h["open"], 紅, 綠), width=0.7)
    下.set_ylabel("張", fontsize=9)
    步 = max(len(h) // 7, 1)
    下.set_xticks(x[::步], h["date"].dt.strftime("%m/%d").iloc[::步])
    return _存圖(plt, 圖)


def 營收圖(營收, 寬=9.2, 高=3.6):
    if 營收 is None or len(營收) < 13:
        return None
    plt = _畫布()
    v = 營收.sort_values("month").copy()
    v["年增率"] = (v["revenue"] / v["revenue"].shift(12) - 1) * 100
    v = v.tail(24)
    圖, 軸 = plt.subplots(figsize=(寬, 高))
    軸.bar(v["month"].str[2:], v["revenue"] / 1e5, color="#2C4A5A", edgecolor=青, linewidth=0.4)
    軸.set_ylabel("營收（億）")
    軸.tick_params(axis="x", rotation=60, labelsize=8)
    右 = 軸.twinx()
    右.plot(v["month"].str[2:], v["年增率"], color=紅, marker="o", markersize=3, linewidth=1.4)
    右.axhline(0, color=淡字, linewidth=0.7)
    右.set_ylabel("年增率 %", color=紅)
    右.tick_params(axis="y", colors=紅)
    右.grid(False)
    右.spines["right"].set_visible(True)
    右.spines["right"].set_color(線色)
    return _存圖(plt, 圖)


def 毛利圖(損益, 寬=9.2, 高=3.6):
    if 損益 is None or 損益.empty or 損益["毛利率"].notna().sum() < 2:
        return None
    plt = _畫布()
    t = 損益.dropna(subset=["毛利率"]).tail(10)
    圖, 軸 = plt.subplots(figsize=(寬, 高))
    q = t["quarter"].str[2:]
    軸.plot(q, t["毛利率"], color=紅, marker="o", linewidth=1.8, label="毛利率")
    軸.plot(q, t["營益率"], color=青, marker="o", linewidth=1.8, label="營業利益率")
    for x, y in zip(q, t["毛利率"]):
        軸.annotate(f"{y:.1f}", (x, y), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=8, color=字色)
    軸.set_ylabel("%")
    軸.legend(loc="upper left", frameon=False, ncol=2)
    return _存圖(plt, 圖)


def 法人圖(歷史, 寬=9.2, 高=3.6):
    if "外資買超" not in 歷史.columns:
        return None
    plt = _畫布()
    h = 歷史.tail(60).reset_index(drop=True)
    圖, 軸 = plt.subplots(figsize=(寬, 高))
    x = np.arange(len(h))
    軸.bar(x - 0.2, h["外資買超"], width=0.4, color=青, label="外資")
    軸.bar(x + 0.2, h["投信買超"], width=0.4, color=黃, label="投信")
    右 = 軸.twinx()
    右.plot(x, h["收盤"], color=字色, linewidth=1.2, label="收盤")
    右.grid(False)
    右.tick_params(axis="y", labelsize=8)
    軸.axhline(0, color=淡字, linewidth=0.7)
    步 = max(len(h) // 7, 1)
    軸.set_xticks(x[::步], h["date"].dt.strftime("%m/%d").iloc[::步])
    軸.set_ylabel("張")
    軸.legend(loc="upper left", frameon=False, ncol=2)
    return _存圖(plt, 圖)


# ---------- 白話解讀 ----------
def _數(v, f="{:,.2f}"):
    return "—" if v is None or pd.isna(v) else f.format(v)


def K線解讀(歷史):
    h = 歷史.copy()
    c = h["收盤"]
    最後 = c.iloc[-1]
    均 = {n: c.rolling(n).mean().iloc[-1] for n in (5, 20, 60)}
    站上 = [n for n in (5, 20, 60) if 最後 >= 均[n]]
    if len(站上) == 3:
        標題 = "站穩所有均線，走勢偏強"
    elif not 站上:
        標題 = "跌破所有均線，走勢偏弱"
    elif 60 in 站上:
        標題 = "短線整理，中期趨勢仍向上"
    else:
        標題 = "短線反彈，中期仍在季線下方"
    漲20 = (最後 / c.iloc[-21] - 1) * 100 if len(c) > 21 else np.nan
    高52 = h["high"].tail(250).max()
    量比 = h["volume"].iloc[-1] / h["volume"].tail(21).iloc[:-1].mean()
    重點 = [
        f"收盤 **{最後:,.2f}**，近 20 日{'上漲' if 漲20 >= 0 else '下跌'} **{abs(漲20):.1f}%**。",
        f"5／20／60 日線分別在 {_數(均[5])}／{_數(均[20])}／{_數(均[60])}，"
        + (f"目前站上 {'、'.join(f'{n} 日' for n in 站上)}線。" if 站上 else "目前都在均線下方。"),
        f"距離一年高點 {高52:,.2f} 還有 **{(最後 / 高52 - 1) * 100:+.1f}%**。",
        f"今天成交量是近 20 日平均的 **{量比:.1f} 倍**，" + ("量能明顯放大。" if 量比 >= 1.5 else "量能偏少。" if 量比 < 0.7 else "量能持平。"),
    ]
    return 標題, 重點


def 營收解讀(營收):
    if 營收 is None or len(營收) < 13:
        return None
    v = 營收.sort_values("month").reset_index(drop=True)
    v["年增"] = (v["revenue"] / v["revenue"].shift(12) - 1) * 100
    最新 = v.iloc[-1]
    年增 = 最新["年增"]
    月增 = (最新["revenue"] / v["revenue"].iloc[-2] - 1) * 100
    連 = 0
    for x in v["年增"].iloc[::-1]:
        if pd.notna(x) and (x > 0) == (年增 > 0):
            連 += 1
        else:
            break
    新高 = 最新["revenue"] >= v["revenue"].iloc[:-1].max()
    三月 = v["年增"].tail(3).mean()
    if 新高:
        標題 = "營收創歷史新高"
    elif 年增 >= 20:
        標題 = "營收高速成長"
    elif 年增 > 0:
        標題 = "營收維持成長"
    else:
        標題 = "營收較去年衰退"
    重點 = [
        f"{最新['month']} 營收 **{最新['revenue'] / 1e5:,.1f} 億**，年增 **{年增:+.1f}%**、月增 {月增:+.1f}%。",
        f"已經連續 **{連} 個月**年{'增' if 年增 > 0 else '減'}。",
        f"近 3 個月平均年增 {三月:+.1f}%，" + ("成長動能加速。" if 三月 > v["年增"].tail(6).head(3).mean() else "成長動能放緩。"),
    ]
    if 新高:
        重點.append("單月營收是資料庫裡（約 5 年）的最高紀錄。")
    return 標題, 重點


def 毛利解讀(損益):
    if 損益 is None or 損益.empty:
        return None
    t = 損益.dropna(subset=["毛利率"])
    if len(t) < 2:
        return None
    最新, 上季 = t.iloc[-1], t.iloc[-2]
    去年 = t[t["quarter"] == f"{int(最新['quarter'][:4]) - 1}{最新['quarter'][4:]}"]
    差 = 最新["毛利率"] - 上季["毛利率"]
    年差 = 最新["毛利率"] - 去年["毛利率"].iloc[0] if len(去年) else np.nan
    升 = 0
    for a, b in zip(t["毛利率"].iloc[::-1].iloc[:-1], t["毛利率"].iloc[::-1].iloc[1:]):
        if (a > b) == (差 > 0):
            升 += 1
        else:
            break
    標題 = "獲利能力提升" if 差 > 0 else "獲利能力下滑"
    重點 = [
        f"{最新['quarter'][:4]} Q{最新['quarter'][-1]} 毛利率 **{最新['毛利率']:.1f}%**，"
        f"較上季{'提升' if 差 > 0 else '降低'} **{abs(差):.1f}** 個百分點"
        + (f"，較去年同季{'提升' if 年差 > 0 else '降低'} {abs(年差):.1f} 個百分點。" if pd.notna(年差) else "。"),
        f"營業利益率 **{最新['營益率']:.1f}%**（上季 {上季['營益率']:.1f}%）。",
        f"毛利率已連續 {升} 季{'上升' if 差 > 0 else '下降'}。" if 升 >= 2 else "毛利率走勢有升有降，還沒形成趨勢。",
    ]
    return 標題, 重點


def 法人解讀(歷史):
    if "外資買超" not in 歷史.columns:
        return None
    h = 歷史.tail(60)
    外60, 投60 = h["外資買超"].sum(), h["投信買超"].sum()
    外10, 投10 = h["外資買超"].tail(10).sum(), h["投信買超"].tail(10).sum()

    def 連續(s):
        n = 0
        方向 = np.sign(s.iloc[-1])
        for x in s.iloc[::-1]:
            if np.sign(x) == 方向 and 方向 != 0:
                n += 1
            else:
                break
        return n, 方向
    外連, 外向 = 連續(h["外資買超"])
    投連, 投向 = 連續(h["投信買超"])
    合 = 外10 + 投10
    標題 = "法人近期偏買" if 合 > 0 else "法人近期偏賣"
    重點 = [
        f"近 60 日外資{'買超' if 外60 >= 0 else '賣超'} **{abs(外60):,.0f} 張**、投信{'買超' if 投60 >= 0 else '賣超'} **{abs(投60):,.0f} 張**。",
        f"近 10 日外資 {外10:+,.0f} 張、投信 {投10:+,.0f} 張。",
        f"外資已連續 **{外連} 天**{'買超' if 外向 > 0 else '賣超'}，投信連續 **{投連} 天**{'買超' if 投向 > 0 else '賣超'}。",
    ]
    return 標題, 重點


def AI段落(報告, 名稱):
    """從 AI 報告抓某一段的條列（例如「利多因素」），最多 4 條。"""
    if not 報告:
        return []
    配 = re.search(r"#+\s*" + 名稱 + r"[^\n]*\n(.*?)(?=\n#+\s|\Z)", 報告, re.S)
    if not 配:
        return []
    條們 = []
    for 行 in 配.group(1).splitlines():
        if re.fullmatch(r"\s*[-*_]{3,}\s*", 行):
            continue
        行 = re.sub(r"^\s*([-*•]|\d+[.、])\s*", "", 行).strip()
        if len(行.replace("*", "").strip()) > 1 and not 行.startswith("|") and not re.fullmatch(r"-{3,}", 行):
            條們.append(_乾淨(行))
    return 條們[:4]


def _乾淨(文字):
    """去掉 Markdown 記號（保留 ** 粗體給 PDF 用的另外處理）與字型沒有的符號。"""
    文字 = re.sub(r"__|`|<br\s*/?>", "", str(文字))
    文字 = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", 文字)
    return re.sub(r"[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F]", "", 文字)


# ---------- PDF ----------
def 產生PDF(代號, 名稱, 資料):
    """資料：收盤、漲跌、漲跌幅、日期、產業、市場、卡片[(標題, 值, 小字, 數值方向)]、基本資料[(段, [(項, 值)])]、
    判讀{分數, 看法, 利多, 利空}、歷史、營收、損益、建議、報告、報告時間。回傳 PDF bytes。"""
    from fpdf import FPDF, FontFace

    class 報告PDF(FPDF):
        def header(self):
            self.set_fill_color(*_rgb(底色))
            self.rect(0, 0, self.w, self.h, style="F")

        def footer(self):
            self.set_y(-10)
            self.set_font("tc", size=7.5)
            self.set_text_color(*_rgb(淡字))
            self.cell(0, 5, f"{代號} {名稱}  //  STOCK REPORT  //  僅供個人研究，不構成投資建議  //  {self.page_no()}", align="R")

    pdf = 報告PDF(orientation="L", format="A4")
    pdf.add_font("tc", "", str(字型夾 / "NotoSansTC-Regular.ttf"))
    pdf.add_font("tc", "B", str(字型夾 / "NotoSansTC-Bold.ttf"))
    pdf.set_auto_page_break(True, margin=14)
    左, 頂 = 12, 12
    pdf.set_margins(左, 頂, 左)
    寬 = pdf.w - 2 * 左
    建議 = 資料.get("建議") or {}

    def 字(大小, 粗=False, 色=字色):
        pdf.set_font("tc", "B" if 粗 else "", 大小)
        pdf.set_text_color(*_rgb(色))

    def 段標(英文, 中文, y=None):
        if y is not None:
            pdf.set_y(y)
        x = pdf.get_x()
        字(8, 色=青)
        pdf.cell(0, 4, 英文.upper(), new_x="LMARGIN", new_y="NEXT")
        字(15, True)
        pdf.set_x(x)
        pdf.cell(0, 8, 中文, new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*_rgb(紅))
        pdf.set_line_width(0.8)
        pdf.line(x, pdf.get_y() + 0.5, x + 14, pdf.get_y() + 0.5)
        pdf.ln(3)

    def 文段(x, y, w, 標題, 重點, 標題色=字色):
        """右側解讀：一句大標＋幾條重點（**粗體**會變成亮色粗體）。"""
        pdf.set_xy(x, y)
        字(14, True, 標題色)
        pdf.multi_cell(w, 7.5, 標題, new_x="LEFT", new_y="NEXT", align="L")
        pdf.ln(2)
        for 條 in 重點:
            pdf.set_x(x)
            字(11, 色=紅)
            pdf.cell(4, 6.5, "▍")
            字(11, 色="#D5D5D5")
            pdf.multi_cell(w - 4, 6.5, _乾淨(條), markdown=True, new_x="LEFT", new_y="NEXT", align="L")
            pdf.set_x(x)
            pdf.ln(1.5)
        return pdf.get_y()

    def 卡片(x, y, w, h, 標題, 值, 小字="", 色=字色):
        pdf.set_fill_color(*_rgb(卡色))
        pdf.set_draw_color(*_rgb(線色))
        pdf.set_line_width(0.2)
        pdf.rect(x, y, w, h, style="DF")
        pdf.set_fill_color(*_rgb(色 if 色 != 字色 else 青))
        pdf.rect(x, y, 1.2, h, style="F")
        pdf.set_xy(x + 3.5, y + 2.5)
        字(8, 色=次字)
        pdf.cell(w - 5, 4, 標題)
        pdf.set_xy(x + 3.5, y + 7.5)
        字(16 if len(str(值)) <= 9 else 12, True, 色)
        pdf.cell(w - 5, 8, str(值))
        if 小字:
            pdf.set_xy(x + 3.5, y + h - 6.5)
            字(7.5, 色=次字)
            pdf.cell(w - 5, 4, _乾淨(小字))

    # ===== 第 1 頁：總覽 =====
    pdf.add_page()
    字(9, 色=青)
    pdf.cell(0, 5, f"STOCK REPORT  //  {資料.get('日期', '')}  //  {資料.get('產業') or ''}  ·  {資料.get('市場', '')}")
    pdf.set_xy(左, 頂 + 6)
    字(34, True)
    pdf.cell(pdf.get_string_width(代號) + 4, 16, 代號)
    字(22, True, 次字)
    pdf.cell(pdf.get_string_width(名稱) + 8, 16, 名稱)
    色 = _漲跌色(資料.get("漲跌"))
    字(30, True, 色)
    價 = f"{資料.get('收盤', 0):,.2f}"
    pdf.cell(pdf.get_string_width(價) + 4, 16, 價)
    字(14, True, 色)
    pdf.cell(0, 16, f"{資料.get('漲跌', 0):+,.2f}（{資料.get('漲跌幅', 0):+.2f}%）")
    if 資料.get("報告時間"):
        pdf.set_xy(左, 頂 + 6)
        字(8, 色=淡字)
        pdf.cell(寬, 4, f"AI 分析時間 {資料['報告時間']}", align="R")
    y = 頂 + 26

    # 重點數據卡片：一排 6 張、兩排
    卡們 = 資料.get("卡片", [])[:12]
    每排 = 6
    卡寬 = (寬 - (每排 - 1) * 3) / 每排
    for i, (標題, 值, 小字, 方向) in enumerate(卡們):
        卡片(左 + (i % 每排) * (卡寬 + 3), y + (i // 每排) * 25, 卡寬, 22, 標題, 值, 小字,
             _漲跌色(方向) if 方向 is not None else 字色)
    y += ((len(卡們) - 1) // 每排 + 1) * 25 + 2

    # AI 結論
    結論 = 建議.get("一句話")
    if 結論 or 建議.get("看法"):
        看 = 建議.get("看法") or "—"
        看色 = {"偏多": 紅, "偏空": 綠}.get(看, 黃)
        pdf.set_fill_color(*_rgb("#1A1A1A"))
        pdf.rect(左, y, 寬, 18, style="F")
        pdf.set_fill_color(*_rgb(看色))
        pdf.rect(左, y, 2, 18, style="F")
        pdf.set_xy(左 + 6, y + 2.5)
        字(8, 色=次字)
        pdf.cell(30, 4, "AI 看法")
        pdf.set_xy(左 + 6, y + 7)
        字(18, True, 看色)
        pdf.cell(30, 9, 看)
        pdf.set_xy(左 + 38, y + 2.5)
        字(8, 色=次字)
        pdf.cell(0, 4, "一句話結論")
        pdf.set_xy(左 + 38, y + 7)
        字(15 if len(結論 or "") <= 40 else 12, True)
        pdf.multi_cell(寬 - 44, 7.5, _乾淨(結論 or ""), align="L")
        y += 22

    # K 線＋解讀
    圖寬 = 寬 * 0.62
    右x = 左 + 圖寬 + 6
    右寬 = 寬 - 圖寬 - 6
    pdf.image(K線圖(資料["歷史"], 寬=9.2, 高=max(3.2, (pdf.h - y - 16) / 25.4 * 9.2 / (圖寬 / 25.4))), x=左, y=y, w=圖寬)
    標題, 重點 = K線解讀(資料["歷史"])
    pdf.set_xy(右x, y)
    字(8, 色=青)
    pdf.cell(右寬, 4, "PRICE ACTION  //  近半年 K 線", new_x="LEFT", new_y="NEXT")
    文段(右x, pdf.get_y() + 1, 右寬, 標題, 重點)

    # ===== 第 2 頁：營收、毛利率 =====
    def 左圖右文(英文, 中文, 圖檔, 解讀, 高):
        if 圖檔 is None or 解讀 is None:
            return
        if pdf.get_y() + 高 > pdf.h - 14:
            pdf.add_page()
        y0 = pdf.get_y()
        段標(英文, 中文)
        y1 = pdf.get_y()
        pdf.image(圖檔, x=左, y=y1, w=圖寬)
        文段(右x, y1, 右寬, *解讀)
        pdf.set_y(max(y1 + 高 - (y1 - y0), pdf.get_y()) + 4)

    pdf.add_page()
    圖高 = 72
    左圖右文("Revenue", "月營收：生意做得怎麼樣", 營收圖(資料.get("營收"), 高=3.3), 營收解讀(資料.get("營收")), 圖高 + 14)
    左圖右文("Margin", "毛利率：賺錢的效率", 毛利圖(資料.get("損益"), 高=3.3), 毛利解讀(資料.get("損益")), 圖高 + 14)
    左圖右文("Institutional", "法人動向：大戶在買還是賣", 法人圖(資料["歷史"], 高=3.3), 法人解讀(資料["歷史"]), 圖高 + 14)

    # 目標價
    if 建議.get("目標價合理") is not None:
        if pdf.get_y() + 45 > pdf.h - 14:
            pdf.add_page()
        段標("Valuation", "AI 目標價與估值")
        y0 = pdf.get_y()
        項 = [("保守", 建議.get("目標價保守"), 綠), ("合理", 建議.get("目標價合理"), 青), ("樂觀", 建議.get("目標價樂觀"), 紅),
             ("券商目標價", 建議.get("券商目標價"), 黃)]
        w = (寬 - 9) / 4
        for i, (名, 值, 色) in enumerate(項):
            空間 = (值 / 資料["收盤"] - 1) * 100 if isinstance(值, (int, float)) and 資料.get("收盤") else np.nan
            卡片(左 + i * (w + 3), y0, w, 24, f"目標價 · {名}" if i < 3 else 名,
                 _數(值, "{:,.0f}") if isinstance(值, (int, float)) else "—",
                 f"距現價 {空間:+.1f}%" if pd.notna(空間) else "", 色)
        pdf.set_y(y0 + 28)
        字(10.5, 色="#D5D5D5")
        f = lambda k, 格="{:,.2f}": _數(建議.get(k), 格) if isinstance(建議.get(k), (int, float)) else "—"
        pdf.multi_cell(寬, 6, f"預估 EPS 今年 **{f('今年EPS')}**、明年 **{f('明年EPS')}**，預估本益比 **{f('預估本益比', '{:.1f}')} 倍**；"
                           f"支撐 **{f('支撐', '{:,.0f}')}**、壓力 **{f('壓力', '{:,.0f}')}**、停損參考 **{f('停損', '{:,.0f}')}**。",
                       markdown=True, align="L", new_x="LMARGIN", new_y="NEXT")

    # 多空清單
    判 = 資料.get("判讀") or {}
    多 = AI段落(資料.get("報告"), "利多") or 判.get("利多", [])
    空 = AI段落(資料.get("報告"), "利空") or 判.get("利空", [])
    if 多 or 空:
        if pdf.get_y() + 70 > pdf.h - 14:
            pdf.add_page()
        段標("Bull vs Bear", f"多空清單" + (f"　·　數據綜合分數 {判['分數']:+d}（{判['看法']}）" if 判 else ""))
        y0 = pdf.get_y()
        半 = (寬 - 6) / 2
        for 欄, (名, 條們, 色) in enumerate((("利多", 多, 紅), ("利空與風險", 空, 綠))):
            x = 左 + 欄 * (半 + 6)
            pdf.set_fill_color(*_rgb(卡色))
            pdf.set_xy(x, y0)
            字(13, True, 色)
            pdf.cell(半, 8, ("▲ " if 欄 == 0 else "▼ ") + 名, new_x="LEFT", new_y="NEXT")
            for 條 in 條們 or ["（無）"]:
                pdf.set_x(x)
                字(10.5, 色="#D5D5D5")
                pdf.multi_cell(半, 6, "・" + _乾淨(條), markdown=True, new_x="LEFT", new_y="NEXT", align="L")
                pdf.ln(1)
            if 欄 == 0:
                y多 = pdf.get_y()
        pdf.set_y(max(y多, pdf.get_y()) + 4)

    # ===== 完整 AI 報告 =====
    報告 = 資料.get("報告")
    if 報告:
        if pdf.get_y() > pdf.h - 70:
            pdf.add_page()
        else:
            pdf.ln(4)
        段標("AI Report", "AI 完整報告")
        表列 = []

        def 印表():
            if not 表列:
                return
            字(9.5, 色="#D5D5D5")
            pdf.set_draw_color(*_rgb(線色))
            pdf.set_fill_color(*_rgb(底色))
            with pdf.table(text_align="LEFT", line_height=5.5, first_row_as_headings=True,
                           headings_style=FontFace(emphasis="BOLD", color=_rgb(青), fill_color=_rgb("#1A1A1A"))) as 表:
                for 格們 in 表列:
                    列 = 表.row()
                    for 格 in 格們:
                        列.cell(格.replace("**", ""))
            表列.clear()
            pdf.ln(3)

        for 行 in str(報告).splitlines() + [""]:
            行 = 行.rstrip()
            if 行.strip().startswith("|"):
                if not re.fullmatch(r"\s*\|?[\s:\-|]+\|?\s*", 行):
                    格 = [_乾淨(c.strip()) for c in 行.strip().strip("|").split("|")]
                    if 表列 and len(格) != len(表列[0]):
                        格 = (格 + [""] * len(表列[0]))[: len(表列[0])]
                    表列.append(格)
                continue
            印表()
            if not 行.strip() or re.fullmatch(r"\s*-{3,}\s*", 行):
                pdf.ln(1.5)
                continue
            if 行.startswith("#"):
                pdf.ln(2)
                字(14, True, 青)
                pdf.multi_cell(寬, 8, _乾淨(行.lstrip("# ")).replace("**", ""), new_x="LMARGIN", new_y="NEXT", align="L")
                pdf.ln(1)
                continue
            縮 = min(len(行) - len(行.lstrip()), 6) * 1.5
            內容 = 行.strip()
            if re.match(r"^[-*•]\s+", 內容):
                內容 = "・" + re.sub(r"^[-*•]\s+", "", 內容)
            字(11, 色="#D5D5D5")
            pdf.set_x(左 + 縮)
            pdf.multi_cell(寬 - 縮, 6.5, _乾淨(內容), markdown=True, new_x="LMARGIN", new_y="NEXT", align="L")

    # ===== 數據總表 =====
    基本 = 資料.get("基本資料") or []
    if 基本:
        pdf.add_page()
        段標("Data Sheet", "數據總表")
        欄寬 = (寬 - 6 * 3) / 4
        y0 = pdf.get_y()
        for 欄, (段, 項目們) in enumerate(基本[:4]):
            x = 左 + 欄 * (欄寬 + 6)
            pdf.set_xy(x, y0)
            字(12, True, 青)
            pdf.cell(欄寬, 8, 段, new_x="LEFT", new_y="NEXT")
            for 名, 值 in 項目們:
                pdf.set_x(x)
                字(9, 色=次字)
                pdf.cell(欄寬 * 0.48, 7, _乾淨(名))
                字(10, True)
                pdf.cell(欄寬 * 0.52, 7, _乾淨(值), align="R", new_x="LEFT", new_y="NEXT")
                pdf.set_draw_color(*_rgb(線色))
                pdf.line(x, pdf.get_y(), x + 欄寬, pdf.get_y())
        pdf.set_y(pdf.h - 30)
        字(8, 色=淡字)
        pdf.multi_cell(寬, 4.5, "資料來源：臺灣證券交易所、證券櫃檯買賣中心、公開資訊觀測站、Google 新聞、Yahoo 奇摩股市。"
                                "AI 分析由大型語言模型彙整，可能有錯誤或過時資訊；解讀文字依數據自動產生。本報告僅供個人研究參考，不構成任何投資建議。",
                       align="L")
    return bytes(pdf.output())
