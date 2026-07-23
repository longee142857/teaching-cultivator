import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deliver.latex_render import extract_formulas, render_latex_png

t = "极限\n$$\n\\lim_{x\\to 0}\\frac{\\sin x}{x}=1\n$$\n对吗"
print("input ok", "$$" in t)
a, p = extract_formulas(t)
print("out:", a)
print("pieces:", len(p), [x.latex for x in p])
if p:
    b = render_latex_png(p[0].latex)
    print("png", len(b) if b else None)
else:
    b = render_latex_png(r"\lim_{x\to 0}\frac{\sin x}{x}=1")
    print("direct png", len(b) if b else None)
