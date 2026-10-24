import requests, re
u = "https://news.google.com/rss/search"
r = requests.get(u, params={"q": "台積電 2330 when:180d", "hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant"}, timeout=20,
                 headers={"User-Agent": "Mozilla/5.0"})
print(r.status_code, len(r.text))
items = re.findall(r"<item>(.*?)</item>", r.text, re.S)
print("items", len(items))
for it in items[:5]:
    print(it[:400]); print("---")
