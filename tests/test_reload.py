# 自動檢查：網站用到的自家模組（engine、macro…）都要在 app.py 用 importlib.reload 重新載入
#   不然部署新版後，Streamlit 會沿用記憶體裡的舊版模組，出現「module 'macro' has no attribute ...」
#   本機執行：python tests/test_reload.py
import re
import sys
from pathlib import Path

根 = Path(__file__).resolve().parent.parent
自家 = {p.stem for p in 根.glob("*.py")} - {"app"}

app = (根 / "app.py").read_text(encoding="utf-8")
已重載 = set(re.findall(r"importlib\.reload\((\w+)\)", app))
for 檔 in sorted((根 / "views").glob("*.py")):
    已重載 |= set(re.findall(r"importlib\.reload\((\w+)\)", 檔.read_text(encoding="utf-8")))

缺 = []
for 檔 in [根 / "app.py", *sorted((根 / "views").glob("*.py"))]:
    for 名 in re.findall(r"^\s*import (\w+)\s*$", 檔.read_text(encoding="utf-8"), re.M):
        if 名 in 自家 and 名 not in 已重載:
            缺.append(f"{檔.relative_to(根)}：import {名} 沒有 importlib.reload({名})")

if 缺:
    print("\n".join(缺))
    sys.exit(1)
print("✅ 自家模組都有重新載入")
