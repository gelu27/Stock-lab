# 自動檢查：views/ 各頁用到的名稱都找得到定義（app.py 共用的、或頁面自己定義的）
#   各頁在 app.py 的命名空間執行，拼錯字或 app.py 改名時，要點到那一頁才會 NameError；這個檢查在 CI 先抓出來。
#   之後把 engine.py 拆成小模組、或改成頁面明確 import 時，這個檢查也確保不會漏搬名稱。
#   本機執行：python tests/test_view_names.py
import ast
import builtins
import sys
from pathlib import Path

根 = Path(__file__).resolve().parent.parent


def 定義過的(樹):
    名們 = set()
    for n in ast.walk(樹):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            名們.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            名們.add(n.name)
        elif isinstance(n, ast.arg):
            名們.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            名們 |= {(a.asname or a.name).split(".")[0] for a in n.names}
        elif isinstance(n, ast.ExceptHandler) and n.name:
            名們.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            名們 |= set(n.names)
        elif isinstance(n, ast.MatchAs) and n.name:
            名們.add(n.name)
    return 名們


共用 = 定義過的(ast.parse((根 / "app.py").read_text(encoding="utf-8"))) | set(dir(builtins)) | {"__file__"}
缺 = []
for 檔 in sorted((根 / "views").glob("p*.py")):
    樹 = ast.parse(檔.read_text(encoding="utf-8"))
    有 = 共用 | 定義過的(樹)
    for n in ast.walk(樹):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in 有:
            缺.append(f"{檔.relative_to(根)}:{n.lineno} 用到 {n.id}，但 app.py 和這一頁都沒有定義")

if 缺:
    print("\n".join(dict.fromkeys(缺)))
    sys.exit(1)
print("✅ 各頁用到的名稱都有定義")
