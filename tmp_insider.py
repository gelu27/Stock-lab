import time, re, requests, engine
x=requests.post("https://mopsov.twse.com.tw/mops/web/ajax_stapap1",headers={"User-Agent":"Mozilla/5.0"},timeout=30,data={
    "encodeURIComponent":"1","step":"1","firstin":"1","off":"1","queryName":"co_id","inpuType":"co_id",
    "TYPEK":"all","isnew":"false","co_id":"2330","year":"115","month":"08"}).text
i=x.find("魏哲家"); print(repr(x[i-600:i+500]))
t=time.time(); print(engine.內部人歷史("2330")); print(engine.內部人歷史("6488")); print(time.time()-t)
