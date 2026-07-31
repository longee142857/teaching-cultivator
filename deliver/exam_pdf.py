# -*- coding: utf-8 -*-
"""双周试卷 → PDF（公式预渲染），供钉钉 sampleFile 投递。

钉钉结论（官方）：
- sampleMarkdown：无 LaTeX，仅标题/加粗/图片/列表
- sampleFile：支持 pdf / doc / docx / xlsx / zip / rar，**不含 md**
故发卷用 PDF，不用 md 附件、也不分题刷屏。
"""
from __future__ import annotations

import io
import logging
import os
import re
import tempfile
from typing import Iterable

logger = logging.getLogger(__name__)

_BLOCK_RE = re.compile(r"\$\$\s*([\s\S]+?)\s*\$\$", re.MULTILINE)
_INLINE_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", re.DOTALL)

_CJK_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simkai.ttf",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
]


def _find_cjk_font() -> str:
    for p in _CJK_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    return ""


def _normalize_latex(expr: str) -> str:
    s = (expr or "").strip()
    # matplotlib mathtext 不认 \le/\ge 简写
    s = re.sub(r"\\le(?![a-zA-Z])", r"\\leq", s)
    s = re.sub(r"\\ge(?![a-zA-Z])", r"\\geq", s)
    return s


def _render_formula_png(latex: str, *, fontsize: int = 16) -> bytes | None:
    from deliver.latex_render import render_latex_png

    return render_latex_png(_normalize_latex(latex), fontsize=fontsize, dpi=160)


def _iter_segments(text: str) -> Iterable[tuple[str, str]]:
    """产出 ('text'|'block'|'inline', payload)。"""
    if not text:
        return
    pos = 0
    # 先抽块公式，行内在文本段里再抽
    for m in _BLOCK_RE.finditer(text):
        if m.start() > pos:
            yield from _iter_inline_text(text[pos : m.start()])
        yield ("block", m.group(1).strip())
        pos = m.end()
    if pos < len(text):
        yield from _iter_inline_text(text[pos:])


def _iter_inline_text(chunk: str) -> Iterable[tuple[str, str]]:
    pos = 0
    for m in _INLINE_RE.finditer(chunk):
        if m.start() > pos:
            yield ("text", chunk[pos : m.start()])
        yield ("inline", m.group(1).strip())
        pos = m.end()
    if pos < len(chunk):
        yield ("text", chunk[pos:])


def build_exam_pdf(paper: dict) -> bytes:
    """把 paper dict 渲染成 PDF bytes。"""
    from fpdf import FPDF

    font_path = _find_cjk_font()
    if not font_path:
        raise RuntimeError("未找到中文字体，无法生成试卷 PDF")

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    family = "ExamCJK"
    pdf.add_font(family, fname=font_path)

    def set_body(size: int = 11):
        pdf.set_font(family, size=size)

    def write_text(s: str, size: int = 11):
        if not s:
            return
        # 规范化空白，避免不可见控制符把布局撑坏
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        s = re.sub(r"[\t\xa0]+", " ", s)
        if not s.strip():
            return
        set_body(size)
        pdf.multi_cell(w=pdf.epw, h=6, text=s)

    def write_formula(latex: str, *, block: bool):
        png = _render_formula_png(latex, fontsize=18 if block else 14)
        if not png:
            from deliver.latex_render import latex_to_plain

            write_text(("【公式】" if block else "") + latex_to_plain(latex))
            return
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(png)
            path = tmp.name
        try:
            max_w = min(pdf.epw, 170 if block else 90)
            pdf.image(path, w=max_w)
            pdf.ln(2)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    pid = paper.get("paper_id") or ""
    title = paper.get("title") or pid
    items = paper.get("items") or []

    set_body(16)
    pdf.multi_cell(w=pdf.epw, h=10, text=f"双周检测卷 · {title}")
    set_body(10)
    pdf.multi_cell(
        w=pdf.epw,
        h=6,
        text=(
            f"试卷 ID：{pid}\n"
            f"题数：{len(items)}\n"
            "说明：公式已预渲染。作答请人机单聊发 Markdown 答卷，"
            f"或「交卷」+正文，并保留 paper_id: {pid}"
        ),
    )
    pdf.ln(4)

    form_cn = {
        "blank": "填空/计算",
        "proof_outline": "证明/推导",
        "mcq": "选择",
    }

    for i, it in enumerate(items, 1):
        form = form_cn.get(it.get("item_form") or "", it.get("item_form") or "")
        set_body(13)
        pdf.multi_cell(w=pdf.epw, h=8, text=f"第 {i} 题（{form}）")
        pdf.ln(1)
        q = (it.get("question") or "").strip()
        for kind, payload in _iter_segments(q):
            if kind == "text":
                t = payload.replace("**", "").replace("### ", "").replace("## ", "")
                write_text(t)
            elif kind == "block":
                write_formula(payload, block=True)
            else:
                write_formula(payload, block=False)
        pdf.ln(2)
        set_body(10)
        pdf.multi_cell(
            w=pdf.epw,
            h=6,
            text=f"【作答区 {i}】请在答卷 md 对应代码块填写",
        )
        pdf.ln(4)

    set_body(10)
    pdf.multi_cell(w=pdf.epw, h=6, text=f"答卷元信息：paper_id: {pid}")

    out = pdf.output()
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    return out.encode("latin-1")


def persist_exam_pdf(paper: dict, pdf_bytes: bytes) -> str:
    from config import DATA_DIR

    d = os.path.join(DATA_DIR, "exam_bank", "pdfs")
    os.makedirs(d, exist_ok=True)
    pid = paper.get("paper_id") or "paper"
    path = os.path.join(d, f"{pid}.pdf")
    with open(path, "wb") as f:
        f.write(pdf_bytes)
    return path
