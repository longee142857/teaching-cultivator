# -*- coding: utf-8 -*-
"""双周试卷 → PNG 长图（钉钉 sampleImageMsg 可在线预览）。

背景：
- 钉钉 Markdown 无 LaTeX；PDF 易乱码且难预览；文档酷应用权限重
→ 整卷渲成 1～少量长图发送，手机点开即可看。
"""
from __future__ import annotations

import io
import logging
import os
import re
from typing import Iterable

logger = logging.getLogger(__name__)

_BLOCK_RE = re.compile(r"\$\$\s*([\s\S]+?)\s*\$\$", re.MULTILINE)
_INLINE_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", re.DOTALL)

PAGE_W = 1080
PAGE_H_MAX = 7000
MARGIN = 44
LINE_GAP = 6
MAX_PAGES = 3

_CJK_CANDIDATES = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 3),
    (r"C:\Windows\Fonts\simhei.ttf", 0),
    (r"C:\Windows\Fonts\msyh.ttc", 0),
    (r"C:\Windows\Fonts\simsun.ttc", 0),
]


def _load_font(size: int):
    from PIL import ImageFont

    last_err = None
    for path, idx in _CJK_CANDIDATES:
        if not os.path.isfile(path):
            continue
        try:
            return ImageFont.truetype(path, size=size, index=idx)
        except Exception as e:
            last_err = e
            try:
                return ImageFont.truetype(path, size=size)
            except Exception as e2:
                last_err = e2
    logger.warning("CJK font missing, fallback default: %s", last_err)
    return ImageFont.load_default()


def _normalize_latex(expr: str) -> str:
    s = (expr or "").strip()
    s = re.sub(r"\\le(?![a-zA-Z])", r"\\leq", s)
    s = re.sub(r"\\ge(?![a-zA-Z])", r"\\geq", s)
    return s


def _formula_image(latex: str, *, fontsize: int = 22):
    from deliver.latex_render import render_latex_png
    from PIL import Image

    raw = render_latex_png(_normalize_latex(latex), fontsize=fontsize, dpi=180)
    if not raw:
        return None
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    max_w = PAGE_W - 2 * MARGIN
    if im.width > max_w:
        ratio = max_w / im.width
        im = im.resize((max_w, max(1, int(im.height * ratio))), Image.Resampling.LANCZOS)
    return im


def _iter_segments(text: str) -> Iterable[tuple[str, str]]:
    if not text:
        return
    pos = 0
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


def _wrap_text(text: str, font, max_w: int) -> list[str]:
    from PIL import Image, ImageDraw

    tmp = Image.new("RGB", (10, 10), "white")
    dr = ImageDraw.Draw(tmp)
    lines: list[str] = []
    for para in (text or "").replace("\r", "").split("\n"):
        if not para:
            lines.append("")
            continue
        buf = ""
        for ch in para:
            trial = buf + ch
            bbox = dr.textbbox((0, 0), trial, font=font)
            if bbox[2] - bbox[0] <= max_w:
                buf = trial
            else:
                if buf:
                    lines.append(buf)
                buf = ch
        if buf:
            lines.append(buf)
    return lines


def _text_strip(text: str, font, *, fill=(20, 20, 20), pad_bottom: int = LINE_GAP):
    """把一段文字渲成一条横幅图。"""
    from PIL import Image, ImageDraw

    content_w = PAGE_W - 2 * MARGIN
    lines = _wrap_text(text, font, content_w)
    if not lines:
        return None
    # 测高
    tmp = Image.new("RGB", (10, 10), "white")
    dr = ImageDraw.Draw(tmp)
    heights = []
    for line in lines:
        bbox = dr.textbbox((0, 0), line or " ", font=font)
        heights.append(max(bbox[3] - bbox[1], getattr(font, "size", 20)) + pad_bottom)
    h = sum(heights) + 4
    im = Image.new("RGB", (PAGE_W, h), "white")
    dr = ImageDraw.Draw(im)
    y = 2
    for line, lh in zip(lines, heights):
        dr.text((MARGIN, y), line, font=font, fill=fill)
        y += lh
    return im


def _image_strip(pil_im):
    from PIL import Image

    if pil_im.mode == "RGBA":
        bg = Image.new("RGB", pil_im.size, "white")
        bg.paste(pil_im, mask=pil_im.split()[3])
        pil_im = bg
    canvas = Image.new("RGB", (PAGE_W, pil_im.height + 16), "white")
    canvas.paste(pil_im, (MARGIN, 8))
    return canvas


def _vstack(strips: list) -> "Image.Image":
    from PIL import Image

    if not strips:
        return Image.new("RGB", (PAGE_W, 100), "white")
    h = sum(s.height for s in strips)
    out = Image.new("RGB", (PAGE_W, h), "white")
    y = 0
    for s in strips:
        out.paste(s, (0, y))
        y += s.height
    return out


def _split_pages(full) -> list:
    """超长图按 PAGE_H_MAX 切开，最多 MAX_PAGES。"""
    from PIL import Image, ImageDraw

    pages = []
    y = 0
    while y < full.height and len(pages) < MAX_PAGES:
        chunk_h = min(PAGE_H_MAX, full.height - y)
        # 最后一页若还会超且已到上限：截断
        if len(pages) == MAX_PAGES - 1:
            chunk_h = full.height - y
            if chunk_h > PAGE_H_MAX:
                chunk_h = PAGE_H_MAX
        page = full.crop((0, y, PAGE_W, y + chunk_h))
        pages.append(page)
        y += chunk_h
        if y >= full.height:
            break
    # 页码
    n = len(pages)
    fb = _load_font(20)
    out_pages = []
    for idx, page in enumerate(pages, 1):
        # 底部留白写页码
        canvas = Image.new("RGB", (PAGE_W, page.height + 40), "white")
        canvas.paste(page, (0, 0))
        d = ImageDraw.Draw(canvas)
        foot = f"{idx}/{n}"
        bbox = d.textbbox((0, 0), foot, font=fb)
        tw = bbox[2] - bbox[0]
        d.text(((PAGE_W - tw) // 2, page.height + 8), foot, font=fb, fill=(150, 150, 150))
        out_pages.append(canvas)
    return out_pages


def build_exam_png_pages(paper: dict) -> list[bytes]:
    """渲染试卷为 1～少量 PNG 长图。"""
    from PIL import Image, ImageDraw

    font_title = _load_font(36)
    font_h = _load_font(30)
    font_body = _load_font(26)
    font_small = _load_font(22)

    pid = paper.get("paper_id") or ""
    title = paper.get("title") or pid
    items = paper.get("items") or []
    form_cn = {
        "blank": "填空/计算",
        "proof_outline": "证明/推导",
        "mcq": "选择",
    }

    strips = []

    def add_text(text, font, **kw):
        s = _text_strip(text, font, **kw)
        if s is not None:
            strips.append(s)

    def add_spacer(h: int = 12):
        strips.append(Image.new("RGB", (PAGE_W, h), "white"))

    add_text(f"双周检测卷 · {title}", font_title, fill=(10, 10, 10))
    add_text(f"试卷 ID：{pid}", font_small, fill=(80, 80, 80))
    add_text(
        f"题数：{len(items)}　公式已渲染　点开图片即可预览",
        font_small,
        fill=(80, 80, 80),
    )
    add_text(
        f"作答：私聊发 md /「交卷」+正文，保留 paper_id: {pid}",
        font_small,
        fill=(80, 80, 80),
    )
    add_spacer(8)
    # 分隔线
    line = Image.new("RGB", (PAGE_W, 3), "white")
    ImageDraw.Draw(line).line(
        (MARGIN, 1, PAGE_W - MARGIN, 1), fill=(200, 200, 200), width=2
    )
    strips.append(line)
    add_spacer(12)

    for i, it in enumerate(items, 1):
        form = form_cn.get(it.get("item_form") or "", it.get("item_form") or "")
        add_text(f"第 {i} 题（{form}）", font_h, fill=(0, 90, 160))
        q = (it.get("question") or "").strip().replace("**", "")
        for kind, payload in _iter_segments(q):
            if kind == "text":
                t = payload.replace("### ", "").replace("## ", "").strip()
                if t:
                    add_text(t, font_body)
            else:
                fim = _formula_image(payload, fontsize=22 if kind == "block" else 18)
                if fim is not None:
                    strips.append(_image_strip(fim))
                else:
                    from deliver.latex_render import latex_to_plain

                    add_text(
                        "【公式】" + latex_to_plain(payload),
                        font_body,
                        fill=(120, 40, 40),
                    )
        add_text(
            f"【作答区 {i}】写入答卷 md 对应代码块",
            font_small,
            fill=(100, 100, 100),
        )
        add_spacer(16)

    full = _vstack(strips)
    pages = _split_pages(full)

    out: list[bytes] = []
    for page in pages:
        buf = io.BytesIO()
        page.save(buf, format="PNG", optimize=True)
        out.append(buf.getvalue())
    return out


def persist_exam_pngs(paper: dict, pages: list[bytes]) -> list[str]:
    from config import DATA_DIR

    d = os.path.join(DATA_DIR, "exam_bank", "pngs")
    os.makedirs(d, exist_ok=True)
    pid = paper.get("paper_id") or "paper"
    paths = []
    for i, raw in enumerate(pages, 1):
        path = os.path.join(d, f"{pid}_p{i}.png")
        with open(path, "wb") as f:
            f.write(raw)
        paths.append(path)
    return paths
