# 自動檢查：台灣時區、網址記住頁面與股票（?p=03&s=2330）、換股票停在同一分頁
#   本機執行：python tests/test_navigation.py
import sys
import time
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

程式 = Path(__file__).resolve().parent.parent / "app.py"
錯誤 = []


def 檢查(條件, 說明):
    print(("✅ " if 條件 else "❌ ") + 說明)
    if not 條件:
        錯誤.append(說明)


def 頁面(at):
    return at.session_state["頁面"]


def main():
    # 1. 網址 ?s=2317 → 直接打開個股查詢的鴻海
    at = AppTest.from_file(str(程式), default_timeout=600)
    at.query_params["s"] = "2317"
    at.run()
    檢查(not at.exception, "帶 ?s=2317 打開網站沒有錯誤")
    檢查(頁面(at) == "03 / 個股查詢", "?s=2317 會切到 03 個股查詢")
    檢查(str(at.session_state["個股查詢"]).startswith("2317 "), "?s=2317 會選好 2317")
    檢查(at.query_params.get("p") == ["03"] or at.query_params.get("p") == "03", "網址會補上 p=03")

    # 2. 換到 04 選股：網址 p 跟著變，股票不會被重設
    next(w for w in at.get("segmented_control") if "04 / 選股" in (w.options or [])).set_value("04 / 選股").run()
    p = at.query_params.get("p")
    檢查((p[0] if isinstance(p, list) else p) == "04", "換頁後網址 p=04（重新整理會留在 04）")

    # 3. 網址 ?p=07&s=2330（例如重新整理）→ 停在 07，不會被 s 拉回個股頁
    at2 = AppTest.from_file(str(程式), default_timeout=600)
    at2.query_params["p"] = "07"
    at2.query_params["s"] = "2330"
    at2.run()
    檢查(頁面(at2).startswith("07"), "?p=07&s=2330 重新整理後停在 07")

    # 4. 個股頁分頁：換股票時停在同一個分頁
    at3 = AppTest.from_file(str(程式), default_timeout=600)
    at3.query_params["s"] = "2330"
    at3.run()
    at3.session_state["個股分頁"] = "📈 技術"
    at3.run()
    選 = at3.selectbox(key="個股查詢")
    選.set_value(next(v for v in 選.options if v.startswith("2454 "))).run()
    檢查(at3.session_state["個股分頁"] == "📈 技術", "換一檔股票後仍停在「技術」分頁")
    檢查(not at3.exception, "技術分頁換股票沒有錯誤")

    # 5. 時區：雲端主機是 UTC，網站要用台灣時間
    import os
    檢查(os.environ.get("TZ") == "Asia/Taipei", "網站執行時 TZ=Asia/Taipei")
    台北 = pd.Timestamp.now(tz="Asia/Taipei").tz_localize(None)
    檢查(abs((pd.Timestamp.now() - 台北).total_seconds()) < 60, "pd.Timestamp.now() 等於台灣時間")

    if 錯誤:
        print(f"\n共 {len(錯誤)} 項失敗")
        sys.exit(1)


if __name__ == "__main__":
    main()
