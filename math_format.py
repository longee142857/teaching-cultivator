"""数学 / Markdown 格式规范化 — LLM 输出后处理兜底。

Obsidian 默认只认 $...$ 与 $$...$$；钉钉 Markdown 不支持 LaTeX 渲染，
但 $ 定界比 \\( \\) 更易读。本模块统一把常见 LaTeX 定界符纠正过来。
"""
from __future__ import annotations

import re


# 块级：\[ ... \] → $$ ... $$
_BLOCK_RE = re.compile(
    r"\\\[\s*([\s\S]*?)\s*\\\]",
    re.MULTILINE,
)

# 行内：\( ... \) → $ ... $
_INLINE_RE = re.compile(r"\\\((.+?)\\\)", re.DOTALL)


def normalize_math_delimiters(text: str) -> str:
    """把 \\( \\)、\\[ \\] 转为 $、$$；已是 $ 的保持不变。"""
    if not text:
        return text

    def _block(m: re.Match) -> str:
        body = m.group(1).strip()
        return f"\n$$\n{body}\n$$\n"

    out = _BLOCK_RE.sub(_block, text)

    def _inline(m: re.Match) -> str:
        body = m.group(1).strip()
        return f"${body}$"

    out = _INLINE_RE.sub(_inline, out)
    return out


def normalize_markdown_body(text: str) -> str:
    """题目正文：修定界符 + 去掉 LLM 误加的重复标题行。"""
    if not text:
        return text
    out = normalize_math_delimiters(text.strip())
    # 去掉正文开头的冗余「**题目**」
    out = re.sub(r"^\*\*题目\*\*\s*\n+", "", out)
    out = re.sub(r"^###\s*题目\s*\n+", "", out, flags=re.IGNORECASE)
    # 收紧连续空行（最多保留双换行）
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def format_for_dingtalk(text: str) -> str:
    """钉钉 sampleMarkdown：规范化 + 段落间双换行（钉钉换行依赖空行）。"""
    out = normalize_markdown_body(text)
    # 块公式前后确保空行，便于钉钉分段显示
    out = re.sub(r"\n?\$\$\n?", "\n\n$$\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def prepare_dingtalk_with_formulas(text: str) -> tuple[str, list]:
    """规范化正文：公式换成 markdown 图片（CDN），不再堆原生 LaTeX。

    返回 (可直接 reply 的 markdown, FormulaPiece列表)。
    pieces 仅作统计/可选跟发本地图；正文已含 ![](cdn)。
    """
    from deliver.latex_render import extract_formulas, formula_to_markdown_image

    out = format_for_dingtalk(text)
    body, pieces = extract_formulas(out)
    for p in pieces:
        body = body.replace(
            p.placeholder,
            formula_to_markdown_image(p.latex, kind=p.kind),
            1,
        )
    return body, pieces


def normalize_answer_block(text: str) -> str:
    """<answer> 内解答块，与正文同一套定界符规则。"""
    return normalize_markdown_body(text)


def split_question_answer(raw: str) -> tuple[str, str]:
    """分离题目与 <answer>，并对两侧分别规范化。"""
    content = raw
    answer = ""
    if "<answer>" in raw:
        parts = raw.split("<answer>", 1)
        content = parts[0].strip()
        tail = parts[1]
        if "</answer>" in tail:
            answer = tail.split("</answer>", 1)[0].strip()
        else:
            answer = tail.strip()
    return normalize_markdown_body(content), normalize_answer_block(answer)


# LLM 偶发把「自我纠错 / 重新出题」写进 <answer>，污染记录
_ANSWER_META_MARKERS = (
    "重新出题",
    "我们调整一下",
    "但由于我之前",
    "为了贴合题目难度",
    "为避免歧义",
    "修改：将",
    "建议保持原题",
    "所以确定以下题目",
)


def sanitize_answer_meta(answer: str) -> str:
    """去掉解答里的出题元思考；保留此前的正确选项与解析。"""
    if not answer:
        return answer
    cut = len(answer)
    for m in _ANSWER_META_MARKERS:
        idx = answer.find(m)
        if 0 <= idx < cut:
            cut = idx
    head = answer[:cut].strip()
    if not head:
        return ""
    # 元思考后若又贴了完整题干，丢弃
    if "正确选项" not in head and "**答案**" not in head and "答案" not in head[:40]:
        # 仍可能是简答（无「正确选项」字样）——仅当明显被截断过才清空
        if cut < len(answer) and len(head) < 40:
            return ""
    return normalize_answer_block(head)
