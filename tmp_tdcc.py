import re, time, requests, engine
r = requests.get("https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
print(r.status_code, len(r.text))
print(re.findall(r'<option[^>]*value="(\d{8})"', r.text)[:5])
print([m for m in re.findall(r'<input[^>]*>', r.text)][:12])
t = time.time()
h = engine.集保歷史("2330", 8)
print(time.time() - t); print(h)
if h is None:
    s = requests.Session(); p = s.get("https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", headers={"User-Agent": "Mozilla/5.0"}).text
    tok = re.search(r'name="SYNCHRONIZER_TOKEN"[^>]*value="([^"]+)"', p)
    d = re.findall(r'<option[^>]*value="(\d{8})"', p)
    x = s.post("https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", headers={"User-Agent": "Mozilla/5.0"}, data={"SYNCHRONIZER_TOKEN": tok.group(1) if tok else "", "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock", "method": "submit", "firDate": d[0], "scaDate": d[1], "sqlMethod": "StockNo", "stockNo": "2330", "stockName": ""}).text
    i = x.find("持股分級"); print(x[i-200:i+3000])
