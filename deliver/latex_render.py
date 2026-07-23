"""LaTeX → 钉钉可读。

钉钉 Markdown 的 ![](url) **总会拉满气泡宽度**，因此：
  - 仅 $$ 块公式 → CDN 图片（全宽可接受）
  - 行内 $...$ → 纯文本/Unicode，绝不出图
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from urllib.parse import quote

logger = logging.getLogger(__name__)

_BLOCK_RE = re.compile(r"\$\$\s*([\s\S]+?)\s*\$\$", re.MULTILINE)
_INLINE_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", re.DOTALL)

# 常见宏 → 纯文本（行内用）
_CMD_MAP = [
    (r"\\int", "∫"),
    (r"\\sum", "Σ"),
    (r"\\prod", "Π"),
    (r"\\infty", "∞"),
    (r"\\partial", "∂"),
    (r"\\nabla", "∇"),
    (r"\\pm", "±"),
    (r"\\mp", "∓"),
    (r"\\times", "×"),
    (r"\\cdot", "·"),
    (r"\\div", "÷"),
    (r"\\leq", "≤"),
    (r"\\geq", "≥"),
    (r"\\neq", "≠"),
    (r"\\approx", "≈"),
    (r"\\equiv", "≡"),
    (r"\\to", "→"),
    (r"\\rightarrow", "→"),
    (r"\\leftarrow", "←"),
    (r"\\Rightarrow", "⇒"),
    (r"\\in", "∈"),
    (r"\\subset", "⊂"),
    (r"\\subseteq", "⊆"),
    (r"\\cup", "∪"),
    (r"\\cap", "∩"),
    (r"\\emptyset", "∅"),
    (r"\\forall", "∀"),
    (r"\\exists", "∃"),
    (r"\\alpha", "α"),
    (r"\\beta", "β"),
    (r"\\gamma", "γ"),
    (r"\\delta", "δ"),
    (r"\\Delta", "Δ"),
    (r"\\epsilon", "ε"),
    (r"\\varepsilon", "ε"),
    (r"\\theta", "θ"),
    (r"\\lambda", "λ"),
    (r"\\mu", "μ"),
    (r"\\pi", "π"),
    (r"\\sigma", "σ"),
    (r"\\phi", "φ"),
    (r"\\omega", "ω"),
    (r"\\Omega", "Ω"),
    (r"\\xi", "ξ"),
    (r"\\lim", "lim"),
    (r"\\sin", "sin"),
    (r"\\cos", "cos"),
    (r"\\tan", "tan"),
    (r"\\log", "log"),
    (r"\\ln", "ln"),
    (r"\\exp", "exp"),
    (r"\\max", "max"),
    (r"\\min", "min"),
    (r"\\sup", "sup"),
    (r"\\inf", "inf"),
    (r"\\, ", " "),
    (r"\\,", " "),
    (r"\\;", " "),
    (r"\\!", ""),
    (r"\\quad", " "),
    (r"\\qquad", "  "),
    (r"\\left", ""),
    (r"\\right", ""),
    (r"\\mathrm", ""),
    (r"\\mathbf", ""),
    (r"\\boldsymbol", ""),
    (r"\\text", ""),
    (r"\\operatorname", ""),
]


@dataclass
class FormulaPiece:
    kind: str  # block only（行内不再出图）
    latex: str
    placeholder: str


def latex_to_plain(latex: str) -> str:
    """行内公式 → 可读纯文本（不去 CDN）。"""
    s = (latex or "").strip()
    if not s:
        return s

    # \frac{a}{b} → (a)/(b)
    def _frac(m: re.Match) -> str:
        return f"({m.group(1)})/({m.group(2)})"

    s = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", _frac, s)
    s = re.sub(r"\\dfrac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", _frac, s)

    # \sqrt{x} → √(x)
    s = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"√(\1)", s)
    s = re.sub(r"\\sqrt\s*([A-Za-z0-9])", r"√\1", s)

    # 下标/上标：x_{i} → x_i ，x^{2} → x^2
    s = re.sub(r"_\{([^{}]+)\}", r"_\1", s)
    s = re.sub(r"\^\{([^{}]+)\}", r"^\1", s)

    for pat, rep in _CMD_MAP:
        s = re.sub(pat + r"(?![A-Za-z])", rep, s)

    # 残余反斜杠命令：去掉 \
    s = re.sub(r"\\([A-Za-z]+)", r"\1", s)
    # 花括号
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def latex_cdn_url(latex: str, *, dpi: int = 200) -> str:
    """块公式 CDN。钉钉会拉满宽，故用较高 dpi 保证拉伸后仍清晰。"""
    body = (latex or "").strip()
    for prefix in ("\\displaystyle", "\\textstyle", "\\scriptstyle", "\\small"):
        if body.lstrip().startswith(prefix):
            body = body.lstrip()[len(prefix) :].lstrip()
    body = "\\displaystyle " + body
    return (
        "https://latex.codecogs.com/png.image?"
        + quote(f"\\dpi{{{dpi}}}\\bg{{white}}{body}", safe="")
    )


def formula_to_markdown_image(latex: str, *, kind: str = "block") -> str:
    """仅块公式用图；行内不应调用此函数。"""
    url = latex_cdn_url(latex, dpi=200)
    return f"\n\n![]({url})\n\n"


def extract_formulas(text: str, *, inline_min_len: int = 3) -> tuple[str, list[FormulaPiece]]:
    """块公式 → 占位符（稍后换图）；行内 → 纯文本。"""
    if not text:
        return text, []

    pieces: list[FormulaPiece] = []
    n = [0]

    def _ph_block(latex: str) -> str:
        n[0] += 1
        p = FormulaPiece(kind="block", latex=latex.strip(), placeholder=f"【公式{n[0]}】")
        pieces.append(p)
        return p.placeholder

    def repl_block(m: re.Match) -> str:
        body = m.group(1).strip()
        if not body:
            return m.group(0)
        return "\n\n" + _ph_block(body) + "\n\n"

    out = _BLOCK_RE.sub(repl_block, text)

    def repl_inline(m: re.Match) -> str:
        body = m.group(1).strip()
        if not body:
            return m.group(0)
        return latex_to_plain(body)

    out = _INLINE_RE.sub(repl_inline, out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip(), pieces


def render_latex_png(latex: str, *, fontsize: int = 18, dpi: int = 160) -> bytes | None:
    latex = (latex or "").strip()
    if not latex:
        return None
    expr = latex
    if not (expr.startswith("$") and expr.endswith("$")):
        expr = f"${expr}$"
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig = plt.figure(figsize=(0.01, 0.01))
        fig.patch.set_facecolor("white")
        text = fig.text(0, 0, expr, fontsize=fontsize, color="black")
        fig.canvas.draw()
        bbox = text.get_window_extent(renderer=fig.canvas.get_renderer())
        w, h = bbox.width / dpi + 0.3, bbox.height / dpi + 0.25
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(max(w, 1.2), max(h, 0.5)))
        ax.set_facecolor("white")
        fig.patch.set_facecolor("white")
        ax.axis("off")
        ax.text(0.5, 0.5, expr, fontsize=fontsize, ha="center", va="center")
        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=dpi,
            bbox_inches="tight",
            pad_inches=0.15,
            facecolor="white",
            edgecolor="none",
        )
        plt.close(fig)
        data = buf.getvalue()
        return data if len(data) > 50 else None
    except Exception as e:
        logger.warning("render_latex_png failed: %s | %s", e, latex[:80])
        return None


def render_pieces(pieces: list[FormulaPiece]) -> list[tuple[FormulaPiece, bytes]]:
    out = []
    for p in pieces:
        png = render_latex_png(p.latex, fontsize=20 if p.kind == "block" else 16)
        if png:
            out.append((p, png))
    return out
