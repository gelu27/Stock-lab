# 自動檢查：每個頁面都能打開、沒有錯誤（GitHub Actions 每次改程式都會跑）
#   本機執行：python tests/test_pages.py
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

程式 = Path(__file__).resolve().parent.parent / "app.py"


def 頁面切換器(at):
    return next(w for w in at.get("segmented_control") if "03 / 個股查詢" in (w.options or []))


def main():
    at = AppTest.from_file(str(程式), default_timeout=600)
    at.run()
    錯誤 = []
    if at.exception:
        錯誤.append(("開啟網站", [e.value for e in at.exception]))
    for 頁 in 頁面切換器(at).options:
        頁面切換器(at).set_value(頁).run()
        訊息 = [e.value for e in at.exception]
        print(f"{頁}：{'❌ ' + 訊息[0][:200] if 訊息 else '✅ 正常'}")
        if 訊息:
            錯誤.append((頁, 訊息))
    # 首頁完整版面（22 個區塊）：區塊出錯不會丟例外，只會顯示「暫時無法顯示」，所以也要看說明文字
    at.query_params["layout"] = "完整"
    頁面切換器(at).set_value("01 / 市場總覽").run()
    訊息 = [e.value for e in at.exception] + [c.value for c in at.caption if "暫時無法顯示" in c.value]
    print(f"首頁完整版面：{'❌ ' + 訊息[0][:200] if 訊息 else '✅ 正常'}")
    if 訊息:
        錯誤.append(("首頁完整版面", 訊息))
    # 個股頁：上市、上櫃、ETF 各一檔，6 個分頁都打開檢查（分頁只計算打開的那一個，所以要逐一切換）
    頁面切換器(at).set_value("03 / 個股查詢").run()
    for 代號 in ("2330", "8069", "0050"):
        選 = at.selectbox(key="個股查詢")
        項 = next((v for v in 選.options if v.startswith(代號 + " ")), None)
        if not 項:
            continue
        選.set_value(項).run()
        for 分頁 in ["📋 總覽", "💰 籌碼", "📊 基本面", "📈 技術", "🤖 AI 分析", "⚖️ 比較"]:
            at.session_state["個股分頁"] = 分頁
            at.run()
            訊息 = [e.value for e in at.exception] + [w.value for w in at.warning if "暫時無法顯示" in w.value]
            print(f"個股 {代號} {分頁}：{'❌ ' + 訊息[0][:200] if 訊息 else '✅ 正常'}")
            if 訊息:
                錯誤.append((f"個股 {代號} {分頁}", 訊息))
    # 新手模式：個股頁多一段白話結論，名詞旁邊有 ❓ 小卡
    at.session_state["新手模式"] = True
    at.session_state["個股分頁"] = "📋 總覽"
    at.run()
    訊息 = [e.value for e in at.exception] + [w.value for w in at.warning if "暫時無法顯示" in w.value]
    有白話 = any("白話一句話" in str(x.label) for x in at.expander)
    print(f"新手模式個股頁：{'❌ ' + 訊息[0][:200] if 訊息 else ('✅ 正常' if 有白話 else '❌ 沒看到白話結論')}")
    if 訊息 or not 有白話:
        錯誤.append(("新手模式個股頁", 訊息 or ["沒看到白話結論"]))
    if 錯誤:
        print(f"\n共 {len(錯誤)} 個頁面有錯誤")
        sys.exit(1)


if __name__ == "__main__":
    main()
