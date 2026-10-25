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
    # 個股頁換一檔上櫃股、一檔 ETF 再檢查
    頁面切換器(at).set_value("03 / 個股查詢").run()
    for 代號 in ("8069", "0050"):
        選 = at.selectbox(key="個股查詢")
        項 = next((v for v in 選.options if v.startswith(代號 + " ")), None)
        if 項:
            選.set_value(項).run()
            訊息 = [e.value for e in at.exception]
            print(f"個股 {代號}：{'❌ ' + 訊息[0][:200] if 訊息 else '✅ 正常'}")
            if 訊息:
                錯誤.append((f"個股 {代號}", 訊息))
    if 錯誤:
        print(f"\n共 {len(錯誤)} 個頁面有錯誤")
        sys.exit(1)


if __name__ == "__main__":
    main()
