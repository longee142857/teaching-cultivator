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


# Shell (apps/feedback-machine/www/js/math.js) and deliver/latex_render.py only
# render delimited math. Same order as renderMathMarkdown: $$ , \[ \] , \( \) , $ $
# (inline $ does not cross newlines). Anything left is invisible to KaTeX.
_DELIM_DISPLAY_DOLLAR = re.compile(r"\$\$[\s\S]+?\$\$")
_DELIM_DISPLAY_BRACKET = re.compile(r"\\\[[\s\S]+?\\\]")
_DELIM_INLINE_PAREN = re.compile(r"\\\([\s\S]+?\\\)")
_DELIM_INLINE_DOLLAR = re.compile(r"\$([^$\n]+?)\$")
_DELIM_PATTERNS = (
    _DELIM_DISPLAY_DOLLAR,
    _DELIM_DISPLAY_BRACKET,
    _DELIM_INLINE_PAREN,
    _DELIM_INLINE_DOLLAR,
)
# \command or \begin{ — the forms that leak as raw TeX outside delimiters.
_BARE_TEX_CMD = re.compile(r"\\(?:begin\{|[a-zA-Z]+)")
_STUB_ANSWER_RE = re.compile(
    r"^[\s（(【\[]*(?:得证|证毕|略|见题解)[\s）)】\]]*[。．.！!]*$"
)
_BARE_TEX_FIELDS_SHOWN = 8
_BARE_TEX_CMDS_SHOWN = 4


def _delimited_mask(text: str) -> list[bool]:
    """Mark characters that sit inside a shell-recognized math span."""
    occupied = [False] * len(text)
    for pat in _DELIM_PATTERNS:
        for match in pat.finditer(text):
            start, end = match.span()
            if any(occupied[start:end]):
                continue
            for i in range(start, end):
                occupied[i] = True
    return occupied


def bare_tex_commands(text: str) -> list[str]:
    """LaTeX commands that sit outside $ / $$ / \\( \\) / \\[ \\].

    ``$\\operatorname{rank}(A)$`` is inside a delimiter and returns [].
    A bare ``\\iint`` or ``\\begin{`` returns the command text.
    """
    if not text:
        return []
    occupied = _delimited_mask(text)
    return [
        match.group(0)
        for match in _BARE_TEX_CMD.finditer(text)
        if not occupied[match.start()]
    ]


def _unique_cmds(cmds: list[str]) -> list[str]:
    out: list[str] = []
    for cmd in cmds:
        if cmd not in out:
            out.append(cmd)
        if len(out) >= _BARE_TEX_CMDS_SHOWN:
            break
    return out


def bare_tex_payload_error(
    *,
    question: str = "",
    answer: str = "",
    solution: dict | None = None,
    cdps: list | None = None,
) -> str:
    """Hard-fail reason when learner-visible fields contain undelimited TeX.

    Empty string means those fields are clean. Checked fields: question,
    answer, solution.final_answer, solution.steps[].text, cdp prompt/expected.
    """
    hits: list[tuple[str, list[str]]] = []

    def consider(name: str, text: object) -> None:
        cmds = bare_tex_commands(text if isinstance(text, str) else "")
        if cmds:
            hits.append((name, cmds))

    consider("question", question)
    consider("answer", answer)
    sol = solution if isinstance(solution, dict) else {}
    consider("solution.final_answer", sol.get("final_answer"))
    for i, step in enumerate(sol.get("steps") or []):
        step_text = step.get("text") if isinstance(step, dict) else step
        consider(f"solution.steps[{i}].text", step_text)
    for i, cdp in enumerate(cdps or []):
        if not isinstance(cdp, dict):
            continue
        consider(f"cdps[{i}].prompt", cdp.get("prompt"))
        consider(f"cdps[{i}].expected", cdp.get("expected"))
    if not hits:
        return ""
    shown = hits[:_BARE_TEX_FIELDS_SHOWN]
    parts = [f"{name}:{','.join(_unique_cmds(cmds))}" for name, cmds in shown]
    extra = len(hits) - len(shown)
    if extra:
        parts.append(f"+{extra}")
    return "bare_tex:" + ";".join(parts)


def math_render_warnings(*, answer: str = "", solution: dict | None = None) -> list[str]:
    """Soft warnings. Do not fail import.

    Stub answers (得证 / 证毕 / 略 / 见题解) and steps whose stripped text
    is at most 4 characters (例如「所以」).
    """
    warns: list[str] = []
    if _STUB_ANSWER_RE.match(answer or ""):
        warns.append("short_answer")
    sol = solution if isinstance(solution, dict) else {}
    for i, step in enumerate(sol.get("steps") or []):
        text = step.get("text") if isinstance(step, dict) else step
        if len((text if isinstance(text, str) else "").strip()) <= 4:
            warns.append(f"thin_step:{i}")
    return warns
