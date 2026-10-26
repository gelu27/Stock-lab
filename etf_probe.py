# 暫時：用瀏覽器找中信、安聯、國泰、群益 00415A 的持股資料網址
import asyncio, json, re
from playwright.async_api import async_playwright

頁們 = {
    "中信00406A": "https://www.ctbcinvestments.com/Etf/00682450/Combination",
    "安聯00984A": "https://etf.allianzgi.com.tw/etf-info/E0001?tab=4",
    "國泰00400A": "https://www.cathaysite.com.tw/ETF/detail/EA?tab=etf3",
    "群益清單": "https://www.capitalfund.com.tw/etf/product/list",
    "兆豐": "https://www.megafunds.com.tw/MEGA/etf/trade_pcf.aspx",
}

async def 看(p, 名, 網址):
    b = await p.chromium.launch()
    c = await b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    pg = await c.new_page()
    記 = []
    async def 回應(r):
        if r.request.resource_type in ("xhr", "fetch"):
            try:
                t = (await r.text())[:300].replace("\n", " ")
            except Exception:
                t = ""
            記.append(f"{r.request.method} {r.status} {r.url}\n     body={r.request.post_data!r:.200}\n     resp={t}")
    pg.on("response", 回應)
    try:
        await pg.goto(網址, timeout=60000, wait_until="networkidle")
    except Exception as e:
        print(名, "goto", repr(e)[:200])
    await pg.wait_for_timeout(4000)
    print("=" * 10, 名, pg.url)
    for x in 記[:40]:
        print("  ", x)
    if 名 == "群益清單":
        連結 = await pg.eval_on_selector_all("a", "els => els.map(e => e.href + ' | ' + e.innerText.trim().slice(0,40))")
        print("\n".join(x for x in 連結 if "/etf/product/detail/" in x)[:3000])
    if 名.startswith("中信"):
        for 字 in ["下載EXCEL", "下載 EXCEL"]:
            try:
                async with pg.expect_download(timeout=20000) as d:
                    await pg.get_by_text(字).first.click()
                dl = await d.value
                print("下載網址", dl.url)
                break
            except Exception as e:
                print("下載失敗", 字, repr(e)[:150])
    await b.close()

async def main():
    async with async_playwright() as p:
        for 名, 網址 in 頁們.items():
            await 看(p, 名, 網址)

asyncio.run(main())
