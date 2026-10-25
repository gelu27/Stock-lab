import requests, re
h={"User-Agent":"Mozilla/5.0"}
r=requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap11_L",headers=h,timeout=60).json()
print(r[0])
for 年,月 in (("115","08"),("115","07")):
    x=requests.post("https://mopsov.twse.com.tw/mops/web/ajax_stapap1",headers=h,timeout=30,data={
        "encodeURIComponent":"1","step":"1","firstin":"1","off":"1","queryName":"co_id","inpuType":"co_id",
        "TYPEK":"all","isnew":"false","co_id":"2330","year":年,"month":月})
    print(x.status_code,len(x.text))
    t=re.sub(r"<[^>]+>"," ",x.text); t=re.sub(r"\s+"," ",t)
    print(t[:2500])
    print("...", t[-1500:])
