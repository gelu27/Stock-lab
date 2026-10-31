# 07 每日評分：由 app.py 的 執行頁面() 在同一個命名空間執行，可直接用 app.py 的共用函式與資料。
@st.cache_data(show_spinner=False, max_entries=2)
def 今年漲幅(版本鍵):
    """今年以來漲跌幅（%）：還原股價跟去年最後一個交易日比，含除權息。"""
    年初 = pd.Timestamp(year=最新日.year, month=1, day=1)
    還原 = 指標[["date", "代號", "還原價"]]
    基 = 還原[還原["date"] < 年初].groupby("代號")["還原價"].last()
    今 = 還原[還原["date"] == 最新日].set_index("代號")["還原價"]
    return ((今 / 基 - 1) * 100).round(1)


def 評分表(代號們=None, 篩選=None):
    """總分、昨日總分、各面向分數與較昨日變化、今年漲幅，代號們給了就照那個順序。"""
    分 = 評分資料(_版本)[0]
    表 = 分.reindex(list(代號們)) if 代號們 is not None else 分
    if 篩選 is not None:
        表 = 表[篩選(表)]
    表 = 表.dropna(subset=["總分"]).reset_index(names="代號")
    表["昨日總分"] = 表["總分"] - 表["較昨日"]
    表["今年漲幅%"] = 表["代號"].map(今年漲幅(_版本))
    return 表[["名稱", "總分", "昨日總分", "較昨日", "看法", "技術", "籌碼", "基本", "市場", "收盤", "漲跌幅", "今年漲幅%",
              "產業", "代號"]]


def 評分樣式(表):
    分欄 = [c for c in ("總分", "昨日總分", "技術", "籌碼", "基本", "市場") if c in 表.columns]
    格式 = ({c: "{:.0f}" for c in 分欄} | {"總分": "{:.1f}", "昨日總分": "{:.1f}", "較昨日": "{:+.1f}", "收盤": "{:,.2f}",
                                        "漲跌幅": "{:+.1f}", "今年漲幅%": "{:+.1f}"})
    return (表.style.map(lambda v: f"color:{分數色(v)}", subset=分欄)
            .map(lambda v: f"color:{漲跌色(v)}", subset=[c for c in ("較昨日", "漲跌幅", "今年漲幅%") if c in 表.columns])
            .format({k: v for k, v in 格式.items() if k in 表.columns}, na_rep="—"))


def 評分驗證區():
    驗 = engine.讀取評分回測()
    段落("VALIDATION // 評分歷史驗證")
    if not 驗:
        st.caption("還沒有驗證結果（每天自動更新後會計算，每月重算一次）。")
        return
    st.caption(f"{驗['起']}～{驗['迄']} 每月最後一個交易日打分數（共 {驗['期數']} 次、平均 {驗['平均檔數']} 檔，"
               f"五日均量 500 張以上、不含 ETF），看之後 {驗['持有天數']} 個交易日的報酬。"
               f"「超額」＝減掉同一天全部股票的平均報酬。計算時間 {驗['計算時間']}。")
    組 = 驗["五分組"]["總分"]
    看 = 驗["看法"]
    a, b = st.columns(2)
    with a:
        st.markdown("**總分由低到高分五組 · 之後 20 日超額報酬**")
        圖 = go.Figure(go.Bar(x=[f"第{x['組']}組" for x in 組], y=[x["超額"] for x in 組],
                              marker_color=[紅 if x["超額"] > 0 else 綠 for x in 組],
                              text=[f"{x['超額']:+.2f}%" for x in 組], textposition="outside", cliponaxis=False))
        圖.update_yaxes(ticksuffix="%")
        st.plotly_chart(圖表外觀(圖, 300), width="stretch")
    with b:
        st.markdown("**依看法分 · 之後 20 日超額報酬**")
        圖 = go.Figure(go.Bar(x=[f"{x['看法']}<br>{x['檔次']:,}次" for x in 看], y=[x["超額"] for x in 看],
                              marker_color=[紅 if x["超額"] > 0 else 綠 for x in 看],
                              text=[f"{x['超額']:+.2f}%" for x in 看], textposition="outside", cliponaxis=False))
        圖.update_yaxes(ticksuffix="%")
        st.plotly_chart(圖表外觀(圖, 300), width="stretch")
    相 = 驗["相關"]
    表 = pd.DataFrame([{"項目": k if k == "總分" else f"{k}面", "目前權重": "—" if k == "總分" else f"{驗['權重'][k]:.0%}",
                       "分數與報酬的相關（IC）": v["IC"], "顯著性 t": v["t"], "相關為正的月份": v["勝率"] * 100,
                       "最高分組超額 %": 驗["五分組"][k][-1]["超額"], "最低分組超額 %": 驗["五分組"][k][0]["超額"]}
                      for k, v in 相.items()])
    表格(表.style.format({"分數與報酬的相關（IC）": "{:+.3f}", "顯著性 t": "{:+.1f}", "相關為正的月份": "{:.0f}%",
                                 "最高分組超額 %": "{:+.2f}", "最低分組超額 %": "{:+.2f}"}),
                 hide_index=True, width="stretch")
    前, 後 = 驗["前後半"]["前半"][-1]["超額"], 驗["前後半"]["後半"][-1]["超額"]
    with st.expander("📖 怎麼看這些數字？"):
        st.markdown(f"""
- **IC** 是「分數排名」和「之後報酬排名」的相關係數，0 代表沒關係；股票裡 IC 有 0.03～0.05 就算有用。**t 超過 2** 才比較不像巧合。
- 目前只有**基本面**明顯有效（分數越高之後越會漲）；技術面、市場面平均起來是**負的**，代表「已經漲很多、很強勢」的股票之後常會拉回。
- 但**總分最高的那 20%** 前後兩段期間都贏平均（前半 {前:+.2f}%、後半 {後:+.2f}%），「強勢」也明顯贏。比較適合拿來**挑前段班**，不適合用分數高低排整個市場。
- 2026/10 依這份結果把權重從「技術 30%、籌碼 25%、基本 30%、市場 15%」改成現在的權重（舊權重的總分 IC 是 −0.028）。
- 同時調整技術面規則：拿掉實際效果相反的「RSI 過熱扣分／超賣加分」「價漲量增」「跌深、遠離高點扣分」，新增「5 日急跌 10% 以上加分」（短線超跌常反彈）；族群強弱降為 ±5 分。調整後「強勢→弱勢」五種看法的後續表現由好到壞排列。
- 限制：歷史 EPS、毛利率沒有資料，回測裡的基本面只有營收、本益比、殖利率；也沒扣交易成本。
""")


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def 評分明細資料(版本鍵):
    return engine.讀取評分回測明細()


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def 權重驗證資料(權重tuple, 版本鍵):
    明 = 評分明細資料(版本鍵)
    return engine.權重驗證(明, dict(權重tuple)) if 明 is not None else None


def 自訂權重區():
    段落("CUSTOM // 自訂評分權重")
    st.caption("拉一拉四個面向的權重，馬上看：①用這組權重，過去幾年分數有沒有用（跟目前權重比）②今天的高分榜會變成什麼樣。只是試算，不會改到網站的正式分數。")
    目前 = engine.評分權重
    cols = st.columns(4)
    權 = {面: cols[i].slider(f"{面}面 %", 0, 100, int(round(目前[面] * 100)), 5, key=f"自訂權重_{面}")
         for i, 面 in enumerate(目前)}
    if sum(權.values()) == 0:
        st.warning("至少要有一個面向大於 0。")
        return
    權 = {k: v / sum(權.values()) for k, v in 權.items()}
    新 = 權重驗證資料(tuple(權.items()), _版本)
    舊 = 權重驗證資料(tuple(目前.items()), _版本)
    if 新 and 舊:
        卡片格([
            卡片("你的權重 IC", f"{新['IC']:+.3f}", f"目前權重 {舊['IC']:+.3f}", 紅 if 新["IC"] > 舊["IC"] else 綠),
            卡片("顯著性 t", f"{新['t']:+.1f}", "超過 2 才比較不像巧合"),
            卡片("最高分組 − 最低分組", f"{新['高減低']:+.2f}%", f"目前權重 {舊['高減低']:+.2f}%（之後 20 日超額）",
                 紅 if 新["高減低"] > 舊["高減低"] else 綠),
            卡片("IC 為正的月份", f"{新['IC為正'] * 100:.0f}%", f"共 {新['期數']} 個月"),
        ])
        圖 = go.Figure([go.Bar(x=[f"第{i}組" for i in 舊["五分組"].index], y=舊["五分組"].values, name="目前權重", marker_color=灰),
                        go.Bar(x=[f"第{i}組" for i in 新["五分組"].index], y=新["五分組"].values, name="你的權重", marker_color=青)])
        圖.update_layout(title="總分由低到高分五組 · 之後 20 日超額報酬（%）", barmode="group", legend=dict(orientation="h", y=1.15))
        st.plotly_chart(圖表外觀(圖, 300), width="stretch")
    else:
        st.caption("歷史驗證明細還沒產生（每天資料更新後自動計算），先只顯示今天的排行。")
    t = 分.copy()
    t["自訂總分"] = engine.加權總分(t, 權)
    t = t[(t["5日均量"] >= 500) & ~t.index.str.startswith("00")].dropna(subset=["自訂總分"])
    t["原排名"] = t["總分"].rank(ascending=False, method="min")
    t = t.sort_values(["自訂總分", "總分"], ascending=False).head(30).reset_index(names="代號")
    t["名次變化"] = (t["原排名"] - (t.index + 1)).astype(int)
    st.markdown("**用你的權重，今天的前 30 名**")
    點選表(t[["名稱", "自訂總分", "總分", "名次變化", "技術", "籌碼", "基本", "市場", "收盤", "漲跌幅", "代號"]],
           評分樣式(t[["名稱", "自訂總分", "總分", "名次變化", "技術", "籌碼", "基本", "市場", "收盤", "漲跌幅", "代號"]])
           .format({"自訂總分": "{:.1f}", "名次變化": "{:+d}"}), "自訂權重榜", height=35 * 31 + 3)
    st.caption("名次變化＝跟目前正式權重的排名比，往前幾名（＋）或往後幾名（−）。歷史驗證的基本面只有營收、本益比、殖利率（沒有歷史 EPS、毛利率），"
               "所以基本面的實際效果可能比回測更好或更差。")


def 評分依據區():
    段落("RULES // 評分依據：每一條加減分規則")
    依據 = pd.DataFrame(engine.評分規則說明, columns=["面向", "加減分", "條件"])
    依據["面向"] = 依據["面向"] + "面（佔 " + 依據["面向"].map(lambda 面: f"{engine.評分權重[面]:.0%}") + "）"
    表格(依據.style.map(lambda v: f"color:{紅 if str(v).startswith('+') else 綠}", subset=["加減分"]),
         hide_index=True, width="stretch", height=35 * (len(依據) + 1) + 3,
         column_config={"條件": st.column_config.TextColumn(width="large")})
    st.caption("每一面從 50 分起算，把符合的條件加總後限制在 0～100 分，再依權重算總分（取到小數第一位）。"
               "權重是用近 4 年的歷史資料驗證後調整的（見下方「評分歷史驗證」）：基本面最能預測之後的報酬，所以佔一半。"
               "單一股票為什麼得到這個分數，在上方「單檔評分明細」的「看加分、扣分理由」。")


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def 高分回測資料(門檻, 前幾名, 版本鍵):
    明 = 評分明細資料(版本鍵)
    if 明 is None:
        return None, None
    return engine.高分股回測(明, engine.評分權重, 門檻, 前幾名)


def 高分回測區():
    段落("BACKTEST // 高分股之後賺不賺？（用過去每月底的分數回測）")
    a, b = st.columns([1, 2])
    方式 = a.segmented_control("選法", ["總分門檻", "每月前幾名"], default="總分門檻", key="高分選法") or "總分門檻"
    if 方式 == "總分門檻":
        門檻 = b.slider("總分 ≥", 60, 90, 85, 1, key="高分門檻")
        前幾名 = None
    else:
        前幾名 = b.segmented_control("每月取前", [10, 20, 30], default=30, key="高分前幾名",
                                  format_func=lambda n: f"前 {n} 名") or 30
        門檻 = None
    選, 每月 = 高分回測資料(門檻, 前幾名, _版本)
    if 選 is None:
        st.caption("歷史分數明細還沒產生（每天資料更新後會自動計算）。")
        return
    區間 = st.segmented_control("期間", ["近一年", "全部"], default="近一年", key="高分期間") or "近一年"
    if 區間 == "近一年":
        選 = 選[選["date"] >= 最新日 - pd.Timedelta(days=365)]
    if 選.empty:
        st.info(f"這段期間沒有總分達 {門檻} 分的股票。回測的分數沒有歷史 EPS、毛利率（基本面最多少約 15 分），"
                "所以很難達到 85 分；建議把門檻調到 75～80，或改用「每月前幾名」。")
        return
    還原 = 指標[["date", "代號", "還原價"]]
    現 = 還原[還原["date"] == 最新日].set_index("代號")["還原價"]
    當時 = 還原.set_index(["date", "代號"])["還原價"]
    鍵 = pd.MultiIndex.from_arrays([選["date"], 選["代號"]])
    選 = 選.assign(至今=((選["代號"].map(現).values / 當時.reindex(鍵).values - 1) * 100))
    有 = lambda c: 選[c].dropna() if c in 選 else pd.Series(dtype=float)
    平 = lambda c: f"{有(c).mean():+.1f}%" if len(有(c)) else "—"
    勝 = lambda c: f"上漲機率 {(有(c) > 0).mean() * 100:.0f}%" if len(有(c)) else ""
    卡片格([
        卡片("選到", f"{len(選):,} 次", f"{選['代號'].nunique()} 檔、{選['date'].nunique()} 個月底"),
        卡片("之後 20 日平均", 平("報酬"), f"{勝('報酬')}・贏全體 {有('超額20').mean():+.1f}%" if len(有("超額20")) else "",
             漲跌色(有("報酬").mean() if len(有("報酬")) else 0)),
        卡片("之後 60 日平均", 平("報酬60"), f"{勝('報酬60')}・贏全體 {有('超額60').mean():+.1f}%" if len(有("超額60")) else "資料累積中",
             漲跌色(有("報酬60").mean() if len(有("報酬60")) else 0)),
        卡片("之後 120 日平均", 平("報酬120"), f"{勝('報酬120')}・贏全體 {有('超額120').mean():+.1f}%" if len(有("超額120")) else "資料累積中",
             漲跌色(有("報酬120").mean() if len(有("報酬120")) else 0)),
        卡片("買進持有至今", 平("至今"), (勝("至今") + f"・{有('至今').size} 次") if len(有("至今")) else "只算近 14 個月",
             漲跌色(有("至今").mean() if len(有("至今")) else 0)),
    ])
    月 = 每月[每月.index.isin(選["date"].unique())]
    圖 = go.Figure([go.Bar(x=月.index, y=月["平均報酬"], name="選到的股票", marker_color=青),
                    go.Bar(x=月.index, y=月["全體報酬"], name="全部股票平均", marker_color=灰)])
    圖.update_layout(title="每個月底選股，之後 20 個交易日的平均報酬（%）", barmode="group", legend=dict(orientation="h", y=1.15))
    st.plotly_chart(圖表外觀(圖, 300), width="stretch")
    顯 = 選.assign(日期=選["date"].dt.strftime("%Y/%m/%d"), 名稱=選["代號"].map(市場名稱).fillna(""))
    欄 = ["日期", "名稱", "總分", "技術", "籌碼", "基本", "市場", "報酬", "報酬60", "報酬120", "至今", "代號"]
    顯 = 顯[[c for c in 欄 if c in 顯]].rename(columns={"報酬": "20日%", "報酬60": "60日%", "報酬120": "120日%", "至今": "至今%"})
    百分 = [c for c in ("20日%", "60日%", "120日%", "至今%") if c in 顯]
    點選表(顯, 顯.style.map(lambda v: f"color:{漲跌色(v)}", subset=百分).map(lambda v: f"color:{分數色(v)}", subset=["總分"])
           .format({**{c: "{:+.1f}" for c in 百分}, "總分": "{:.1f}", "技術": "{:.0f}", "籌碼": "{:.0f}", "基本": "{:.0f}",
                    "市場": "{:.0f}"}, na_rep="—"), "高分回測表", height=min(35 * (len(顯) + 1) + 3, 520))
    st.caption("做法：每個月最後一個交易日，只用當時看得到的資料打分數（五日均量 500 張以上、不含 ETF），"
               "挑出分數夠高的股票，看之後 20／60／120 個交易日的報酬（含除權息），「贏全體」＝減掉同一天全部股票的平均。"
               "至今＝從那天買進持有到最新收盤（網站只留近 14 個月的股價，更早的不算）。"
               "限制：歷史沒有 EPS、毛利率資料，所以回測分數比現在網站上的分數低一些，85 分以上很少見；沒扣交易成本。"
               "過去有效不代表未來一定有效。")


# ---------- 06 每日評分 ----------
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
- **技術面**：是否站上 20 日線、60 日線，均線多空排列，近 20 日大漲，接近 52 週高點，近 5 日急跌（短線超跌易反彈），價跌量增
- **籌碼面**：三大法人 5 日買賣超（跟成交量比）、外資／投信連買、外資今日買賣、融資增減
- **基本面**：月營收年增率、累計營收、營收創新高、近三季 EPS、毛利率比去年同季、本益比、殖利率
- **市場面**：大盤分數（指數均線、漲跌家數、外資買賣超金額）、所屬族群近 20 日強弱、近 5／20 日是否贏大盤

規則寫在 `engine.py` 的「評分規則」表，可以自己調整分數。每天收盤後的 LINE 摘要也會附上大盤與庫存的評分。
""")
評分依據區()
評分驗證區()
高分回測區()
自訂權重區()
st.caption("⚠️ 分數只是把公開數據套進固定規則的結果，不含新聞、產業前景與突發事件，不構成投資建議。")
