from math_format import prepare_dingtalk_with_formulas

t = "黎曼积分\n$$\n\\int_{a}^{b} f(x)\\,dx\n$$\n结束"
b, p = prepare_dingtalk_with_formulas(t)
print("pieces", len(p))
print("has_cdn", "codecogs.com" in b)
print("has_raw_int", "\\int" in b and "![" not in b.split("\\int")[0][-20:])
print("has_image_md", "![](" in b)
print(b[:300])
