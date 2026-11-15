# 每天資料更新後（以及開盤前），用瀏覽器打開網站，讓網站先把資料讀好、算好（下一位訪客就不用等）
#   python tests/warmup.py https://taisc-stock.streamlit.app
#   依序預熱：預設首頁 → 完整首頁（關鍵價位、焦點、排行最花時間，第一次約 10～20 秒）→ 手機首頁 → 個股頁
import sys
import time

from playwright.sync_api import sync_playwright

網址 = sys.argv[1] if len(sys.argv) > 1 else "https://taisc-stock.streamlit.app"
網址 = 網址.rstrip("/") + "/"


def 等到(頁, 文字, 秒數):
    """等網頁（Streamlit Cloud 把網站包在 iframe 裡）出現某段文字；網站在睡覺就按叫醒。"""
    期限 = time.time() + 秒數
    while time.time() < 期限:
        for 框 in 頁.frames:
            try:
                if 框.get_by_text(文字).count():
                    return True
                喚醒 = 框.get_by_role("button", name="Yes, get this app back up!")
                if 喚醒.count():
                    print("網站在睡覺，叫醒它")
                    喚醒.first.click()
            except Exception:
                pass
        time.sleep(5)
    return False


with sync_playwright() as p:
    瀏覽器 = p.chromium.launch()
    頁 = 瀏覽器.new_page()
    頁.goto(網址, timeout=120000)
    完成 = 等到(頁, "資料日期", 600)
    print("網站已載入完成" if 完成 else "10 分鐘內沒載入完成")
    if 完成:
        for 參數, 說明 in (("?p=01&layout=完整", "完整首頁"), ("?p=01&m=1", "手機首頁"), ("?s=2330", "個股頁")):
            t = time.time()
            try:
                頁.goto(網址 + 參數, timeout=120000)
                好 = 等到(頁, "資料新鮮度", 300)  # 頁尾最後才畫，出現代表整頁都算完了
            except Exception as e:
                好 = False
                print(說明, "預熱失敗：", repr(e)[:200])
            print(f"{說明}預熱{'完成' if 好 else '逾時'}（{time.time() - t:.0f} 秒）")
    瀏覽器.close()
    sys.exit(0 if 完成 else 1)
