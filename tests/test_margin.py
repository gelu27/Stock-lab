# 個股融資成本／維持率估算的小測試：python tests/test_margin.py
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine  # noqa: E402


def main():
    # 第 1 天 100 張@100；第 2 天加 100 張@110 → 成本 105；第 3 天減少 → 成本不變
    代 = np.array(["A"] * 3 + ["B"] * 2)
    價 = np.array([100.0, 110, 120, 50, 50])
    報 = np.array([0, 0.1, 0.0909, 0, 0])
    融 = np.array([100.0, 200, 150, 10, np.nan])
    c = engine.融資成本估算(代, 價, 報, 融)
    assert abs(c[1] - 105) < 1e-9 and abs(c[2] - 105) < 1e-9, c
    assert c[3] == 50 and c[4] == 50, c          # 換股票重算、融資沒公布沿用
    # 面額分割 1 拆 4：收盤 400 → 100、交易所漲跌 0，成本跟著 ÷4，張數 ×4 不算新買進
    c = engine.融資成本估算(np.array(["C"] * 3), np.array([400.0, 100, 100]), np.array([0, 0, 0.0]),
                         np.array([100.0, 400, 500]))
    assert abs(c[1] - 100) < 1e-9, c
    assert abs(c[2] - 100) < 1e-9, c
    print("✅ 融資成本估算正常")


if __name__ == "__main__":
    main()
