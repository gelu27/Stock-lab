# 暫時：第一次抓齊全部公司的主要業務與營收比重（之後每天的更新會補新的、刷新舊的）
import sys, time
sys.path.insert(0, ".")
import update_data
t = time.time()
update_data.抓公司簡介(每次=3000)
print("花了", round(time.time() - t), "秒")
