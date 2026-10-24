# 個股分析 PDF 報告：基本資料、AI 建議、股價／營收／毛利率／法人圖表、完整 AI 報告
# 用 fpdf2 排版、matplotlib 畫圖，中文字型放在 fonts/（Noto Sans TC）

import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

字型夾 = Path(__file__).parent / "fonts"
紅, 綠, 藍, 橘, 灰 = "#D7263D", "#1B998B", "#2E86AB", "#F18F01", "#888888"


def _畫布():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    路徑 = str(字型夾 / "NotoSansTC-Regular.ttf")
    if 路徑 not in [f.fname for f in font_manager.fontManager.ttflist]:
        font_manager.fontManager.addfont(路徑)
    plt.rcParams.update({"font.family": font_manager.FontProperties(fname=路徑).get_name(),
                         "axes.unicode_minus": False, "font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True, "grid.color": "#E5E5E5",
                         "grid.linewidth": 0.6})
    return plt


def _存圖(plt, 圖):
    緩衝 = io.BytesIO()
    圖.savefig(緩衝, format="png", dpi=160, bbox_inches="tight")
    plt.close(圖)
    緩衝.seek(0)
    return 緩衝


def 股價圖(歷史):
    """近一年收盤、20／60 日均線與成交量。"""
    plt = _畫布()
    h = 歷史.tail(250)
    圖, (上, 下) = plt.subplots(2, 1, figsize=(7.2, 3.6), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    上.plot(h["date"], h["收盤"], color="#222222", linewidth=1.2, label="收盤")
    上.plot(h["date"], h["收盤"].rolling(20).mean(), color=橘, linewidth=1, label="20 日線")
    上.plot(h["date"], h["收盤"].rolling(60).mean(), color=藍, linewidth=1, label="60 日線")
    上.legend(loc="upper left", frameon=False, ncol=3)
    上.set_title("近一年股價", loc="left", fontsize=10)
    色 = np.where(h["收盤"].diff().fillna(0) >= 0, 紅, 綠)
    下.bar(h["date"], h["volume"] / 1000, color=色, width=1)
    下.set_ylabel("張")
    return _存圖(plt, 圖)


def 營收圖(營收):
    """近 24 個月營收（億）與年增率。營收：month、revenue（千元）。"""
    if 營收 is None or len(營收) < 2:
        return None
    plt = _畫布()
    v = 營收.sort_values("month").copy()
    v["年增率"] = (v["revenue"] / v["revenue"].shift(12) - 1) * 100
    v = v.tail(24)
    圖, 軸 = plt.subplots(figsize=(7.2, 2.6))
    軸.bar(v["month"], v["revenue"] / 1e5, color="#9DB4C0")
    軸.set_ylabel("營收（億）")
    軸.tick_params(axis="x", rotation=60, labelsize=7)
    右 = 軸.twinx()
    右.plot(v["month"], v["年增率"], color=紅, marker="o", markersize=2.5, linewidth=1)
    右.axhline(0, color=灰, linewidth=0.6)
    右.set_ylabel("年增率 %")
    右.grid(False)
    軸.set_title("月營收與年增率", loc="left", fontsize=10)
    return _存圖(plt, 圖)


def 毛利圖(損益):
    """單季毛利率、營益率。"""
    if 損益 is None or 損益["毛利率"].notna().sum() < 2:
        return None
    plt = _畫布()
    t = 損益.dropna(subset=["毛利率"]).tail(10)
    圖, 軸 = plt.subplots(figsize=(7.2, 2.4))
    軸.plot(t["quarter"], t["毛利率"], color=紅, marker="o", label="毛利率")
    軸.plot(t["quarter"], t["營益率"], color=藍, marker="o", label="營業利益率")
    for x, y in zip(t["quarter"], t["毛利率"]):
        軸.annotate(f"{y:.1f}", (x, y), textcoords="offset points", xytext=(0, 5), ha="center", fontsize=7)
    軸.set_ylabel("%")
    軸.legend(loc="upper left", frameon=False, ncol=2)
    軸.set_title("單季毛利率與營業利益率", loc="left", fontsize=10)
    return _存圖(plt, 圖)


def 法人圖(歷史):
    """近 60 日外資、投信買賣超（張）。"""
    if "外資買超" not in 歷史.columns:
        return None
    plt = _畫布()
    h = 歷史.tail(60)
    圖, 軸 = plt.subplots(figsize=(7.2, 2.4))
    x = np.arange(len(h))
    軸.bar(x - 0.2, h["外資買超"], width=0.4, color=藍, label="外資")
    軸.bar(x + 0.2, h["投信買超"], width=0.4, color=橘, label="投信")
    軸.axhline(0, color=灰, linewidth=0.6)
    步 = max(len(h) // 6, 1)
    軸.set_xticks(x[::步], h["date"].dt.strftime("%m/%d").iloc[::步])
    軸.set_ylabel("張")
    軸.legend(loc="upper left", frameon=False, ncol=2)
    軸.set_title("近 60 日法人買賣超", loc="left", fontsize=10)
    return _存圖(plt, 圖)


def _乾淨(文字):
    """去掉 Markdown 記號與 PDF 字型沒有的符號。"""
    文字 = re.sub(r"\*\*|__|`|<br\s*/?>", "", str(文字))
    文字 = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", 文字)
    return re.sub(r"[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F]", "", 文字)


def 產生PDF(代號, 名稱, 基本資料, 歷史, 營收=None, 損益=None, 建議=None, 報告=None, 報告時間=""):
    """基本資料：[(段落名稱, [(項目, 值), ...]), ...]。回傳 PDF bytes。"""
    from fpdf import FPDF

    class 報告PDF(FPDF):
        def footer(self):
            self.set_y(-12)
            self.set_font("tc", size=7)
            self.set_text_color(140)
            self.cell(0, 6, f"{代號} {名稱} · 僅供個人研究，不構成投資建議 · 第 {self.page_no()} 頁", align="C")

    pdf = 報告PDF(format="A4")
    pdf.add_font("tc", "", str(字型夾 / "NotoSansTC-Regular.ttf"))
    pdf.add_font("tc", "B", str(字型夾 / "NotoSansTC-Bold.ttf"))
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(14, 14, 14)
    pdf.add_page()
    寬 = pdf.w - 28

    # 標題
    pdf.set_fill_color(20, 20, 20)
    pdf.rect(0, 0, pdf.w, 30, style="F")
    pdf.set_xy(14, 8)
    pdf.set_text_color(255)
    pdf.set_font("tc", "B", 18)
    pdf.cell(0, 9, f"{代號} {名稱}　個股分析報告")
    pdf.set_xy(14, 18)
    pdf.set_font("tc", size=9)
    pdf.set_text_color(190)
    pdf.cell(0, 6, f"產生時間 {pd.Timestamp.now(tz='Asia/Taipei'):%Y-%m-%d %H:%M}"
             + (f"　·　AI 分析時間 {報告時間}" if 報告時間 else ""))
    pdf.set_y(36)
    pdf.set_text_color(30)

    def 標題(字):
        pdf.ln(2)
        pdf.set_font("tc", "B", 12)
        pdf.set_text_color(30)
        pdf.cell(0, 8, 字, new_x="LMARGIN", new_y="NEXT", align="L")
        pdf.set_draw_color(215, 38, 61)
        pdf.set_line_width(0.6)
        pdf.line(14, pdf.get_y(), 14 + 18, pdf.get_y())
        pdf.ln(2)

    def 表格(項目們, 欄數=4):
        pdf.set_font("tc", size=9)
        pdf.set_draw_color(225)
        pdf.set_line_width(0.2)
        欄寬 = 寬 / 欄數
        for i in range(0, len(項目們), 欄數 // 2):
            for 名, 值 in 項目們[i:i + 欄數 // 2]:
                pdf.set_text_color(120)
                pdf.cell(欄寬 * 0.85, 7, _乾淨(名), border="B")
                pdf.set_text_color(25)
                pdf.set_font("tc", "B", 9)
                pdf.cell(欄寬 * 1.15, 7, _乾淨(值), border="B")
                pdf.set_font("tc", size=9)
            pdf.ln(7)

    def 放圖(圖檔, 高):
        if 圖檔 is None:
            return
        if pdf.get_y() + 高 > pdf.h - 18:
            pdf.add_page()
        pdf.image(圖檔, x=14, w=寬)
        pdf.ln(2)

    # AI 建議
    if 建議:
        標題("AI 建議")
        看 = 建議.get("看法") or "—"
        pdf.set_font("tc", "B", 14)
        pdf.set_text_color(*{"偏多": (215, 38, 61), "偏空": (27, 153, 139)}.get(看, (80, 80, 80)))
        pdf.cell(28, 9, 看)
        pdf.set_font("tc", size=10)
        pdf.set_text_color(40)
        pdf.multi_cell(寬 - 28, 6, _乾淨(建議.get("一句話") or ""), new_x="LMARGIN", new_y="NEXT", align="L")
        pdf.ln(1)
        數 = lambda k, f="{:,.0f}": f.format(建議[k]) if isinstance(建議.get(k), (int, float)) else "—"
        項目 = [("短線 / 中期", f"{建議.get('短線') or '—'} / {建議.get('中期') or '—'}"),
                ("合理目標價", 數("目標價合理")),
                ("目標價區間", f"{數('目標價保守')} ~ {數('目標價樂觀')}"),
                ("券商目標價", 數("券商目標價")),
                ("預估 EPS 今年 / 明年", f"{數('今年EPS', '{:.2f}')} / {數('明年EPS', '{:.2f}')}"),
                ("預估本益比", 數("預估本益比", "{:.1f} 倍")),
                ("支撐 / 壓力", f"{數('支撐')} / {數('壓力')}"),
                ("停損參考", 數("停損"))]
        表格(項目)

    for 段, 項目 in 基本資料:
        if 段 == "基本面":
            放圖(股價圖(歷史), 95)
        標題(段)
        表格(項目)
        if 段 == "基本面":
            放圖(營收圖(營收), 70)
            放圖(毛利圖(損益), 65)
        if 段 == "籌碼面":
            放圖(法人圖(歷史), 65)

    # 完整 AI 報告
    if 報告:
        if pdf.get_y() > pdf.h - 60:
            pdf.add_page()
        標題("AI 完整報告")
        表列 = []

        def 印表():
            if not 表列:
                return
            pdf.set_font("tc", size=8)
            pdf.set_text_color(45)
            pdf.set_draw_color(200)
            pdf.set_fill_color(255)
            with pdf.table(text_align="LEFT", line_height=5, first_row_as_headings=True,
                           headings_style=__import__("fpdf").FontFace(emphasis="BOLD", fill_color=(240, 240, 240))) as 表:
                for 格們 in 表列:
                    列 = 表.row()
                    for 格 in 格們:
                        列.cell(格)
            表列.clear()
            pdf.ln(2)

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
                pdf.ln(1)
                pdf.set_font("tc", "B", 11)
                pdf.set_text_color(30)
                pdf.multi_cell(寬, 7, _乾淨(行.lstrip("# ")), new_x="LMARGIN", new_y="NEXT", align="L")
                continue
            pdf.set_font("tc", size=9)
            pdf.set_text_color(45)
            縮 = len(行) - len(行.lstrip())
            內容 = 行.strip()
            if re.match(r"^[-*•]\s+", 內容):
                內容 = "・" + re.sub(r"^[-*•]\s+", "", 內容)
            pdf.set_x(14 + min(縮, 6) * 1.5)
            pdf.multi_cell(寬 - min(縮, 6) * 1.5, 5.5, _乾淨(內容), new_x="LMARGIN", new_y="NEXT", align="L")

    pdf.ln(4)
    pdf.set_font("tc", size=8)
    pdf.set_text_color(130)
    pdf.multi_cell(寬, 5, "資料來源：臺灣證券交易所、證券櫃檯買賣中心、公開資訊觀測站、Google 新聞；AI 分析由大型語言模型彙整，"
                         "可能有錯誤或過時資訊。本報告僅供個人研究參考，不構成任何投資建議。", align="L")
    return bytes(pdf.output())
