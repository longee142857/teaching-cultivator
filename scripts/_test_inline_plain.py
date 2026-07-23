"""Quick check: inline → plain, block → cdn image."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from math_format import prepare_dingtalk_with_formulas

t = """不定积分的定义：

$$\\int f(x)\\,dx = F(x) + C$$

其中 $F(x)$ 是原函数，满足 $F'=f$，$C$ 是任意常数。
"""
b, p = prepare_dingtalk_with_formulas(t)
print("pieces", len(p), "(expect 1 block only)")
print("has_cdn", "codecogs" in b)
print("has_Fx_img", b.count("![]("))
print("---")
print(b)
assert len(p) == 1, p
assert "F(x)" in b and "![](" in b
assert b.count("![](") == 1
print("OK")
