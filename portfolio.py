"""庫存（投資組合）層級的計算：停損全觸發試算、庫存風險體檢。

從 engine.py 拆出來的第一個模組（只用 pandas／numpy，不依賴 engine）；
engine 仍然 re-export 這些函式，舊程式寫 engine.庫存風險(...) 照樣能用。
"""
import numpy as np
import pandas as pd


def 停損全觸發(持股, 現價, 停損表=None, 預設跌幅=0.08, 現金=0.0):
    """組合層級的停損試算：每檔用交易日記記的停損價，沒記的用「現價 −8%」；
    回傳 (明細表, 總結 dict)：全部停損都觸發會少多少錢、佔總資產幾 %、單檔占比燈號。"""
    停損表 = 停損表 or {}
    列們 = []
    for _, r in 持股.iterrows():
        代 = str(r["代號"]).strip()
        價 = 現價.get(代)
        if 價 is None or not np.isfinite(價) or 價 <= 0:
            continue
        股 = float(r["股數"])
        停 = 停損表.get(代)
        來源 = "日記停損" if 停 and 停 > 0 else f"預設 −{預設跌幅 * 100:.0f}%"
        停 = float(停) if 停 and 停 > 0 else 價 * (1 - 預設跌幅)
        列們.append({"代號": 代, "股數": 股, "現價": 價, "停損": round(停, 2), "停損來源": 來源,
                   "市值": 股 * 價, "觸發損失": -max(股 * (價 - 停), 0)})
    表 = pd.DataFrame(列們)
    if 表.empty:
        return 表, None
    股票市值 = 表["市值"].sum()
    總資產 = 股票市值 + max(float(現金 or 0), 0)
    表["占總資產%"] = 表["市值"] / 總資產 * 100
    表["占比燈"] = np.select([表["占總資產%"] > 30, 表["占總資產%"] > 20], ["🔴 過重", "🟡 偏重"], "🟢")
    損 = 表["觸發損失"].sum()
    return 表.sort_values("觸發損失"), {"總損失": 損, "占總資產%": 損 / 總資產 * 100, "股票水位%": 股票市值 / 總資產 * 100,
                                    "總資產": 總資產, "現金": max(float(現金 or 0), 0), "用預設": int((表["停損來源"] != "日記停損").sum())}


# ========== 庫存風險體檢 ==========
def 庫存風險(持股, 指標, 指數收盤, 產業表=None, 天數=250, 名稱表=None):
    """持股：代號、股數。回傳 dict：占比表、產業表、Beta、大盤跌 10% 估計、最大單日跌幅、相關最高的組合、提醒。"""
    股數 = 持股.assign(代號=持股["代號"].astype(str).str.strip()).groupby("代號")["股數"].sum()
    寬 = 指標[指標["代號"].isin(股數.index)].pivot_table(index="date", columns="代號", values="還原價").sort_index()
    收 = 指標[指標["代號"].isin(股數.index)].pivot_table(index="date", columns="代號", values="收盤").sort_index()
    if 寬.empty:
        return None
    最新 = 收.ffill().iloc[-1]
    市值 = (最新 * 股數.reindex(最新.index)).dropna()
    市值 = 市值[市值 > 0]
    權 = 市值 / 市值.sum()
    報 = 寬[權.index].pct_change().tail(天數)
    大 = 指數收盤.sort_index().pct_change().reindex(報.index)
    beta = {}
    for c in 權.index:
        x = pd.concat([報[c], 大], axis=1).dropna()
        beta[c] = float(x.iloc[:, 0].cov(x.iloc[:, 1]) / x.iloc[:, 1].var()) if len(x) >= 60 and x.iloc[:, 1].var() > 0 else np.nan
    beta = pd.Series(beta)
    組合 = (報.fillna(0) * 權).sum(axis=1)
    淨值 = (1 + 組合).cumprod()
    產 = pd.Series({c: ("ETF" if c.startswith("00") else ((產業表 or {}).get(c) or "其他")) for c in 權.index})
    產業 = 權.groupby(產).sum().sort_values(ascending=False)
    占比 = pd.DataFrame({"市值": 市值.round(), "占比%": (權 * 100).round(1), "Beta": beta.round(2), "產業": 產})
    占比 = 占比.sort_values("占比%", ascending=False)
    組Beta = float((beta.fillna(1) * 權).sum())
    相關 = 報.corr()
    對們 = [(a, b, 相關.at[a, b]) for i, a in enumerate(相關.columns) for b in 相關.columns[i + 1:] if pd.notna(相關.at[a, b])]
    對們 = sorted(對們, key=lambda x: -x[2])[:3]
    提醒 = []
    名 = lambda c: f"{c} {(名稱表 or {}).get(c, '')}".strip()
    if len(占比) and 占比["占比%"].iloc[0] > 30:
        提醒.append(f"單一股票 {名(占比.index[0])} 占 {占比['占比%'].iloc[0]:.0f}%，超過 3 成，這檔一跌整體就跟著大跌。")
    if len(產業) and 產業.iloc[0] > 0.5 and 產業.index[0] != "ETF":
        提醒.append(f"「{產業.index[0]}」占 {產業.iloc[0] * 100:.0f}%，超過一半集中在同一個產業。")
    if 組Beta > 1.2:
        提醒.append(f"整體 Beta {組Beta:.2f}，大盤跌 1% 你的庫存平均跌 {組Beta:.1f}%，比大盤更敏感。")
    if 對們 and 對們[0][2] > 0.8:
        提醒.append(f"{名(對們[0][0])} 和 {名(對們[0][1])} 走勢高度同步（相關 {對們[0][2]:.2f}），分散效果有限。")
    return {"占比": 占比, "產業": 產業, "Beta": 組Beta, "跌10%": 市值.sum() * 組Beta * -0.10,
            "最大單日": float(組合.min()) if len(組合) else np.nan, "最大單日日": 組合.idxmin() if len(組合) else None,
            "最大回撤": float((淨值 / 淨值.cummax() - 1).min()) if len(淨值) else np.nan,
            "大盤最大回撤": float(((1 + 大.fillna(0)).cumprod() / (1 + 大.fillna(0)).cumprod().cummax() - 1).min()),
            "相關": 對們, "提醒": 提醒, "市值": float(市值.sum()), "天數": len(報)}


# ========== 長中短分倉 ==========
分倉名 = ("長線", "波段", "短線")


def 預設分倉(代號, 大型股=()):
    """沒設定時的猜測：ETF（00 開頭）與市值前 50 大＝長線，其他＝波段。"""
    代 = str(代號).strip()
    return "長線" if 代.startswith("00") or 代 in set(大型股) else "波段"


def 分倉配置(持股, 現價, 分倉表=None, 現金=0.0, 目標=None, 已實現獲利=0.0, 大型股=()):
    """持股（代號、股數、總成本）依長線／波段／短線分組。回傳 (明細, 各倉表, 總結)。
    總結：短線市值、短線額度（＝已實現獲利，心法說短線只用賺來的錢）、超出額度、現金%。"""
    分倉表 = {str(k): v for k, v in (分倉表 or {}).items() if v in 分倉名}
    目標 = 目標 or {"長線": 50, "波段": 30, "短線": 5, "現金": 15}
    列們 = []
    for _, r in 持股.iterrows():
        代 = str(r["代號"]).strip()
        價 = 現價.get(代)
        if 價 is None or not np.isfinite(價) or 價 <= 0:
            continue
        股 = float(r["股數"])
        成本 = float(r.get("總成本", np.nan)) if "總成本" in r else np.nan
        倉 = 分倉表.get(代) or 預設分倉(代, 大型股)
        列們.append({"代號": 代, "分倉": 倉, "設定": "自訂" if 代 in 分倉表 else "預設", "股數": 股, "現價": 價, "市值": 股 * 價,
                   "報酬%": (股 * 價 / 成本 - 1) * 100 if 成本 and np.isfinite(成本) and 成本 > 0 else np.nan})
    明細 = pd.DataFrame(列們)
    現金 = max(float(現金 or 0), 0)
    總資產 = (明細["市值"].sum() if len(明細) else 0) + 現金
    if 總資產 <= 0:
        return 明細, pd.DataFrame(), None
    市 = 明細.groupby("分倉")["市值"].sum() if len(明細) else pd.Series(dtype=float)
    各倉 = pd.DataFrame({"分倉": list(分倉名) + ["現金"],
                       "市值": [float(市.get(k, 0)) for k in 分倉名] + [現金]})
    各倉["目前%"] = 各倉["市值"] / 總資產 * 100
    各倉["目標%"] = [float(目標.get(k, 0)) for k in 各倉["分倉"]]
    各倉["差距%"] = 各倉["目前%"] - 各倉["目標%"]
    各倉["調整金額"] = -各倉["差距%"] / 100 * 總資產
    短 = float(市.get("短線", 0))
    額度 = max(float(已實現獲利 or 0), 0)
    return 明細, 各倉, {"總資產": 總資產, "現金%": 現金 / 總資產 * 100, "短線市值": 短, "短線額度": 額度,
                       "短線超出": max(短 - 額度, 0)}


def 分倉紀律(明細, 線們, 波段燈=None, 停損表=None, 波段停損=0.08, 停利提醒=0.15):
    """每檔依分倉給一句紀律提醒。線們＝{代號: 近 250 日收盤 Series}。
    長線：距一年高點（ETF 才建議越跌越買，個股提醒別無限攤平）；波段：停損／停利／大盤燈；短線：破 5 日線就走。"""
    停損表 = 停損表 or {}
    出 = []
    for _, r in 明細.iterrows():
        s = 線們.get(r["代號"])
        燈, 字 = "⚪", "資料不足"
        if s is not None and len(s.dropna()) >= 20:
            s = s.dropna()
            收 = float(s.iloc[-1])
            距 = (收 / float(s.tail(250).max()) - 1) * 100
            m5 = float(s.tail(5).mean())
            if r["分倉"] == "長線":
                etf = str(r["代號"]).startswith("00")
                if 距 <= -20:
                    燈, 字 = "🟢", f"離一年高點 {距:.0f}%，在越跌越買的區間" + ("（分批，不要一次用完）" if etf else "；個股跌深可能是基本面變了，先確認再加")
                elif 距 <= -10:
                    燈, 字 = "🟡", f"離一年高點 {距:.0f}%，可以照計畫小量分批"
                else:
                    燈, 字 = "⚪", f"離一年高點 {距:.0f}%，照平常定期定額"
            elif r["分倉"] == "波段":
                停 = 停損表.get(r["代號"])
                報 = r.get("報酬%")
                if 停 and 收 <= float(停):
                    燈, 字 = "🔴", f"跌破你設的停損 {float(停):,.2f}，照紀律出場"
                elif pd.notna(報) and 報 <= -波段停損 * 100:
                    燈, 字 = "🔴", f"虧損 {報:.1f}%，已超過波段停損 −{波段停損 * 100:.0f}%"
                elif pd.notna(報) and 報 >= 停利提醒 * 100:
                    燈, 字 = "🟡", f"賺 {報:.1f}%：可以把停損上移保本；回測顯示急著全賣會砍掉大波段"
                elif 波段燈 and 波段燈["燈"] == "🔴":
                    燈, 字 = "🟡", "大盤不是多頭，這檔先不加碼"
                else:
                    燈, 字 = "🟢", "照計畫續抱，停損不要往下移"
            else:
                if 收 < m5:
                    燈, 字 = "🔴", f"收盤 {收:,.2f} 跌破 5 日線 {m5:,.2f}：技術走弱，照紀律離場"
                else:
                    燈, 字 = "🟢", f"還在 5 日線 {m5:,.2f} 上，破線就走"
        出.append({"代號": r["代號"], "紀律": f"{燈} {字}"})
    return pd.DataFrame(出)
