# 每天資料更新後，用瀏覽器打開網站一次，讓網站先把資料讀好、算好（下一位訪客就不用等）
#   python tests/warmup.py https://taisc-stock.streamlit.app
import sys
import time

from playwright.sync_api import sync_playwright

網址 = sys.argv[1] if len(sys.argv) > 1 else "https://taisc-stock.streamlit.app"
期限 = time.time() + 600

with sync_playwright() as p:
    瀏覽器 = p.chromium.launch()
    頁 = 瀏覽器.new_page()
    頁.goto(網址, timeout=120000)
    完成 = False
    while time.time() < 期限 and not 完成:
        for 框 in 頁.frames:  # Streamlit Cloud 把網站包在 iframe 裡
            try:
                if 框.get_by_text("資料日期").count():
                    完成 = True
                    break
                喚醒 = 框.get_by_role("button", name="Yes, get this app back up!")
                if 喚醒.count():
                    print("網站在睡覺，叫醒它")
                    喚醒.first.click()
            except Exception:
                pass
        time.sleep(5)
    print("網站已載入完成" if 完成 else "10 分鐘內沒載入完成")
    瀏覽器.close()
    sys.exit(0 if 完成 else 1)
