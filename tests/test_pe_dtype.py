# 大盤本益比／預估本益比遇到字串（Arrow 字串）欄位也不能出「字串乘數字」錯誤（11/23 估值週線、預估估值區塊）
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd

import engine

s = engine._轉浮點(pd.Series(["1,2", "3.5", "--", None], dtype="str"))
assert s.dtype == "float64" and s.iloc[1] == 3.5 and np.isnan(s.iloc[2])
assert engine._轉浮點(pd.Series([1, 2])).dtype == "float64"

n = 150
今日 = pd.DataFrame({"代號": [f"{1000 + i}" for i in range(n)], "名稱": ["x"] * n, "市場": ["上市"] * n,
                   "收盤": pd.Series([str(10 + i % 5) for i in range(n)], dtype="str"),
                   "發行股數": pd.Series(["1000000"] * n, dtype="str"),
                   "預估EPS今年": pd.Series(["1.5"] * n, dtype="str"), "預估EPS明年": pd.Series(["2.0"] * n, dtype="str")})
try:
    結果 = engine.大盤預估本益比(今日.assign(收盤=pd.to_numeric(今日["收盤"]), 發行股數=pd.to_numeric(今日["發行股數"])))
except Exception as e:
    raise SystemExit(f"❌ {e!r}")
assert 結果 and "明年" in 結果
t = engine.大盤本益比(天數=3)
assert len(t) and t["本益比"].dtype == "float64"
print("test_pe_dtype ✅")
