import requests, io
H = {"User-Agent": "Mozilla/5.0"}
def show(u, n=600, enc=None):
    try:
        r = requests.get(u, headers=H, timeout=30)
        if enc: r.encoding = enc
        print("==", u, r.status_code, r.headers.get("content-type"), len(r.content))
        print(r.text[:n].replace("\n", " | "))
    except Exception as e:
        print("==", u, "ERR", e)
show("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", 900)
show("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", 900)
show("https://openapi.twse.com.tw/v1/opendata/t187ap14_L", 700)
show("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap14_O", 700)
for host in ("https://mopsov.twse.com.tw", "https://mops.twse.com.tw"):
    show(f"{host}/nas/t21/sii/t21sc03_113_9_0.html", 300, "big5")
    show(f"{host}/nas/t21/otc/t21sc03_113_9_0.html", 300, "big5")
    show(f"{host}/server-java/FileDownLoad?step=9&functionName=show_file2&filePath=/home/html/nas/t21/sii/&fileName=t21sc03_113_9.csv", 500, "utf-8")
show("https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_113_9.csv", 300, "utf-8")
