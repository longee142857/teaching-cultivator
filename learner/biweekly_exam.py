"""双周 Markdown 试卷 — 补日常 defer 漏洞 + 全面检测。

节奏：隔周周日 08:00；数学 / 通信各一份 .md（落盘 exam_bank）。
组题优先「kb_cache 已热」子考点，尽量保证整卷能发出。
推送：H5 阅读页（KaTeX，见 deliver/exam_web）为主；EXAM_PUSH_PNG=1 可加长图。
答卷：网页提交，或人机单聊发 .md /「交卷」+ 正文（群聊钉钉不支持收文件）。
题库：data/exam_bank/ 供 LLM 工具检索。
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from config import DATA_DIR

BANK_DIR = os.path.join(DATA_DIR, "exam_bank")
PAPERS_DIR = os.path.join(BANK_DIR, "papers")
KEYS_DIR = os.path.join(BANK_DIR, "keys")
ANSWERS_DIR = os.path.join(BANK_DIR, "answers")
INDEX_PATH = os.path.join(BANK_DIR, "index.json")
STATE_PATH = os.path.join(BANK_DIR, "state.json")

QUESTIONS_PER_SUBJECT = 5
INTERVAL_DAYS = 14
_lock = threading.Lock()


def _ensure_dirs() -> None:
    for d in (BANK_DIR, PAPERS_DIR, KEYS_DIR, ANSWERS_DIR):
        os.makedirs(d, exist_ok=True)


def _now() -> datetime:
    return datetime.now()


def _uid() -> str:
    """当前学员身份；无上下文时回退 anonymous（避免写坏全局）。"""
    try:
        from learner.context import current_user_id
        return current_user_id() or "anonymous"
    except Exception:
        return "anonymous"


def _load_json(path: str, default: Any) -> Any:
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return default


def _save_json(path: str, data: Any) -> None:
    _ensure_dirs()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_state() -> dict:
    return _load_json(STATE_PATH, {"last_run": "", "last_paper_ids": []})


def save_state(state: dict) -> None:
    _save_json(STATE_PATH, state)


def load_index() -> dict:
    return _load_json(INDEX_PATH, {"papers": [], "updated_at": ""})


def save_index(index: dict) -> None:
    index["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_json(INDEX_PATH, index)


def biweekly_is_due(now: datetime | None = None) -> bool:
    """距上次成功发卷 ≥14 天（或从未发过）则为到期。"""
    now = now or _now()
    st = load_state()
    last = (st.get("last_run") or "").strip()
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return True
    return (now - last_dt) >= timedelta(days=INTERVAL_DAYS)


def next_biweekly_slot(now: datetime | None = None) -> datetime:
    """下一个周日 08:00；若已到期则取「即将到来的/今天的」周日 08:00。"""
    now = now or _now()
    # weekday: Mon=0 … Sun=6
    days_ahead = (6 - now.weekday()) % 7
    target = now.replace(hour=8, minute=0, second=0, microsecond=0)
    target = target + timedelta(days=days_ahead)
    if target <= now:
        target += timedelta(days=7)
    # 若未到期，跳到 last_run+14 之后的周日
    if not biweekly_is_due(now):
        st = load_state()
        try:
            last_dt = datetime.fromisoformat(st["last_run"])
            earliest = last_dt + timedelta(days=INTERVAL_DAYS)
            while target < earliest:
                target += timedelta(days=7)
        except Exception:
            pass
    return target


def _warm_l3_ids(subject: str) -> list[str]:
    """kb_cache 中已有条目的 L3 id（点分）。"""
    try:
        from learner import kb_cache
        from learner.kp_registry import looks_like_l3_id, syllabus_subject

        subj = syllabus_subject(subject)
        store = kb_cache._load_store()  # noqa: SLF001 — 只读预热筛选
        out = []
        for k, entry in (store.get("entries") or {}).items():
            if not k.startswith(f"{subj}::"):
                continue
            unit = k.split("::", 1)[-1]
            if looks_like_l3_id(unit):
                snippets = entry.get("snippets") or []
                if len(snippets) >= 2:
                    out.append(unit)
        return out
    except Exception:
        return []


def _l2_for_l3(subject: str, l3_id: str) -> str | None:
    from learner.kp_registry import load_syllabus, syllabus_subject

    syl = load_syllabus(syllabus_subject(subject))
    for l2, meta in (syl.get("kps") or {}).items():
        if not isinstance(meta, dict):
            continue
        for l3 in meta.get("l3") or []:
            if isinstance(l3, dict) and (l3.get("id") or "").strip() == l3_id:
                return l2
    return None


# 双周卷能力池：偏计算/构造/迁移，避开 recognize→mcq
_EXAM_ABILITIES = ("compute", "construct", "transfer", "compute", "construct")


def _looks_like_mcq(question: str) -> bool:
    """粗检：是否仍被模型写成选择题（应尽量拒绝）。"""
    q = question or ""
    hits = sum(
        1
        for m in ("A.", "B.", "C.", "D.", "A．", "B．", "C．", "D．", "(A)", "（A）")
        if m in q
    )
    if hits >= 3:
        return True
    if ("选择题" in q or "单选" in q) and hits >= 2:
        return True
    return False


def _pick_units(subject: str, n: int = QUESTIONS_PER_SUBJECT) -> list[dict]:
    """选 n 个优先已热的 (l2, l3_id, ability)。"""
    import random

    warm = _warm_l3_ids(subject)
    random.shuffle(warm)
    picks: list[dict] = []
    used_l2: set[str] = set()

    # 先尽量分散 L2
    for l3_id in warm:
        if len(picks) >= n:
            break
        l2 = _l2_for_l3(subject, l3_id)
        if not l2 or l2 in used_l2:
            continue
        used_l2.add(l2)
        ability = _EXAM_ABILITIES[len(picks) % len(_EXAM_ABILITIES)]
        picks.append({"l2": l2, "l3_id": l3_id, "ability": ability})

    # 不足：同 L2 再取热 L3
    if len(picks) < n:
        for l3_id in warm:
            if len(picks) >= n:
                break
            if any(p["l3_id"] == l3_id for p in picks):
                continue
            l2 = _l2_for_l3(subject, l3_id)
            if not l2:
                continue
            ability = _EXAM_ABILITIES[len(picks) % len(_EXAM_ABILITIES)]
            picks.append({"l2": l2, "l3_id": l3_id, "ability": ability})

    return picks


def _author_one(subject: str, l2: str, l3_id: str, ability: str) -> dict | None:
    """单题：走 generate 硬闸；强制大题；仍像选择题则再试一次。"""
    from intervention import InterventionDecision
    from cultivate import generate, get_last_answer
    from learner.ability_cycle import encode_ability_reason, exam_item_form

    item_form = exam_item_form(ability)

    def _once() -> dict | None:
        reason = (
            f"{l2}: 双周检测大题 [l3={l3_id}] "
            f"{encode_ability_reason(ability)} [item_form={item_form}]"
        )
        decision = InterventionDecision(
            "push", "intermediate", reason, 3, ability_goal=ability
        )
        try:
            content = generate(subject, decision, source="schedule")
        except Exception:
            return None
        if not content or not str(content).strip():
            return None
        answer = get_last_answer() or ""
        return {
            "l2": l2,
            "l3_id": l3_id,
            "ability": ability,
            "item_form": item_form,
            "question": content.strip(),
            "answer": answer.strip(),
        }

    got = _once()
    if got and _looks_like_mcq(got["question"]):
        # 模型偶发无视约束 → 丢弃重试一次
        got2 = _once()
        if got2 and not _looks_like_mcq(got2["question"]):
            return got2
        # 两次仍像选择题：宁缺毋滥
        return None
    return got


def assemble_paper(subject: str, *, n: int = QUESTIONS_PER_SUBJECT) -> dict:
    """组装一份科目试卷；返回 meta（含 items 与可公开 md / 密钥）。"""
    subject = "math" if subject == "review" else subject
    if subject not in ("math", "comm"):
        raise ValueError(f"unsupported subject: {subject}")

    units = _pick_units(subject, n=n + 4)  # 多备几道以防 generate 失败
    items: list[dict] = []
    for u in units:
        if len(items) >= n:
            break
        got = _author_one(subject, u["l2"], u["l3_id"], u["ability"])
        if got:
            items.append(got)

    paper_id = f"{_now().strftime('%Y-%m-%d')}_{subject}"
    title = "数学一" if subject == "math" else "通信原理801"
    public_md = _render_public_md(paper_id, title, subject, items)
    return {
        "paper_id": paper_id,
        "subject": subject,
        "title": title,
        "created_at": _now().isoformat(),
        "items": items,
        "public_md": public_md,
        "n_ok": len(items),
        "n_target": n,
    }


def _render_public_md(paper_id: str, title: str, subject: str, items: list[dict]) -> str:
    """题库归档用全文（仍为 md）。钉钉推送不再发此文件附件，改群消息分题推送。"""
    lines = [
        f"# 双周检测卷 · {title}",
        "",
        f"- 试卷 ID：`{paper_id}`",
        f"- 科目：{subject}",
        f"- 题数：{len(items)}",
        f"- 说明：题目以 **H5 链接**推送（KaTeX）。"
        f"也可**人机单聊**发回 Markdown 答卷（建议 `{paper_id}_答案.md`），"
        "或「交卷」+ 正文。群聊无法收文件。",
        "",
        "---",
        "",
    ]
    for i, it in enumerate(items, 1):
        form = it.get("item_form") or "blank"
        form_cn = {
            "blank": "填空/计算",
            "proof_outline": "证明/推导",
            "mcq": "选择",
        }.get(form, form)
        lines.append(f"## 第 {i} 题（{form_cn} · {it.get('ability', '')}）")
        lines.append("")
        lines.append(it.get("question") or "")
        lines.append("")
        lines.append(f"### 作答区 {i}")
        lines.append("")
        lines.append("```")
        lines.append("")
        lines.append("```")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 答卷元信息（请保留）")
    lines.append("")
    lines.append(f"- paper_id: {paper_id}")
    lines.append(f"- subject: {subject}")
    return "\n".join(lines)


def render_dingtalk_chunks(paper: dict) -> list[str]:
    """拆成多条钉钉可读消息：封面 + 每题一条（公式交给 send_push 做 CDN）。"""
    pid = paper.get("paper_id") or ""
    title = paper.get("title") or pid
    items = paper.get("items") or []
    chunks: list[str] = [
        (
            f"### 双周检测卷 · {title}\n\n"
            f"- 试卷 ID：`{pid}`\n"
            f"- 题数：{len(items)}（尽量为大题：填空/计算/证明）\n"
            f"- 题目分条推送；公式已按钉钉可读方式渲染\n"
            f"- **作答**：人机单聊发 `.md` 答卷，或「交卷」+ 正文；"
            f"答卷请保留 `paper_id: {pid}`\n"
            f"- 不再发送 `.md` 附件（钉钉打开异常 / 公式不渲染）\n"
        )
    ]
    for i, it in enumerate(items, 1):
        form = it.get("item_form") or "blank"
        form_cn = {
            "blank": "填空/计算",
            "proof_outline": "证明/推导",
            "mcq": "选择",
        }.get(form, form)
        q = (it.get("question") or "").strip()
        chunks.append(
            f"### {title} · 第 {i}/{len(items)} 题（{form_cn}）\n\n"
            f"`paper_id: {pid}`\n\n"
            f"{q}\n\n"
            f"> 作答区请写入答卷 md 的「### 作答区 {i}」代码块中。"
        )
    return chunks


def persist_paper(paper: dict) -> str:
    """写入 papers/ keys/ index；返回 paper_id。"""
    _ensure_dirs()
    pid = paper["paper_id"]
    md_path = os.path.join(PAPERS_DIR, f"{pid}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(paper["public_md"])

    key = {
        "paper_id": pid,
        "subject": paper["subject"],
        "created_at": paper["created_at"],
        "items": [
            {
                "i": i + 1,
                "l2": it["l2"],
                "l3_id": it["l3_id"],
                "ability": it["ability"],
                "item_form": it["item_form"],
                "answer": it.get("answer") or "",
                "question_preview": (it.get("question") or "")[:200],
            }
            for i, it in enumerate(paper["items"])
        ],
    }
    _save_json(os.path.join(KEYS_DIR, f"{pid}.json"), key)

    index = load_index()
    papers = [p for p in index.get("papers", []) if p.get("id") != pid]
    papers.insert(
        0,
        {
            "id": pid,
            "subject": paper["subject"],
            "title": paper["title"],
            "created_at": paper["created_at"],
            "n_questions": len(paper["items"]),
            "path": f"papers/{pid}.md",
            "status": "issued",
            "tags": ["biweekly", paper["subject"], "exam"],
            "summary": f"{paper['title']} 双周卷 {len(paper['items'])} 题",
        },
    )
    index["papers"] = papers[:100]
    save_index(index)
    return pid


def mark_run_success(paper_ids: list[str]) -> None:
    st = load_state()
    st["last_run"] = _now().isoformat()
    st["last_paper_ids"] = paper_ids
    save_state(st)


def list_bank(query: str = "", limit: int = 20) -> str:
    """供 LLM 检索的题库目录文本。"""
    index = load_index()
    papers = index.get("papers") or []
    q = (query or "").strip().lower()
    if q:
        papers = [
            p
            for p in papers
            if q in json.dumps(p, ensure_ascii=False).lower()
        ]
    papers = papers[: max(1, min(limit, 50))]
    if not papers:
        return "题库暂无匹配试卷。"
    lines = [f"双周题库共列出 {len(papers)} 份："]
    for p in papers:
        lines.append(
            f"- `{p.get('id')}` | {p.get('subject')} | {p.get('n_questions')}题 | "
            f"{p.get('status')} | {p.get('summary', '')}"
        )
    lines.append("取全文请用 get_exam_paper(paper_id)。")
    return "\n".join(lines)


def get_exam_paper(paper_id: str) -> str:
    pid = (paper_id or "").strip()
    path = os.path.join(PAPERS_DIR, f"{pid}.md")
    if not os.path.isfile(path):
        return f"未找到试卷 `{pid}`"
    with open(path, encoding="utf-8") as f:
        return f.read()


def _parse_answers_from_md(md: str) -> dict[int, str]:
    """从答卷 md 提取各题作答。支持 ``` 作答区 或 『第 N 题答案』。"""
    answers: dict[int, str] = {}
    text = md or ""
    # 作答区 i + 独立成行的 fenced block（卷面标准格式）
    for m in re.finditer(
        r"###\s*作答区\s*(\d+)\s*\n\s*```[^\n]*\n(.*?)```",
        text,
        flags=re.S | re.I,
    ):
        answers[int(m.group(1))] = (m.group(2) or "").strip()
    if answers:
        return answers
    # 宽松：作答区标题与 fence 之间允许任意空白
    for m in re.finditer(
        r"###\s*作答区\s*(\d+)[\s\S]*?```[^\n]*\n(.*?)```",
        text,
        flags=re.S | re.I,
    ):
        answers[int(m.group(1))] = (m.group(2) or "").strip()
    if answers:
        return answers
    for m in re.finditer(
        r"(?:第\s*(\d+)\s*题\s*(?:答案|作答)|答案\s*(\d+))\s*[:：]?\s*(.+?)(?=(?:第\s*\d+\s*题|答案\s*\d+|$))",
        text,
        flags=re.S | re.I,
    ):
        num = int(m.group(1) or m.group(2))
        answers[num] = (m.group(3) or "").strip()
    return answers


def _extract_paper_id(md: str) -> str | None:
    m = re.search(r"paper_id\s*[:：]\s*`?([0-9]{4}-[0-9]{2}-[0-9]{2}_(?:math|comm))`?", md, re.I)
    if m:
        return m.group(1)
    m = re.search(r"(20\d{2}-\d{2}-\d{2}_(?:math|comm))", md)
    return m.group(1) if m else None


def submit_answer_md(
    md_text: str,
    *,
    paper_id: str = "",
    user_id: str = "",
) -> str:
    """接收用户答卷 md → 逐题批改 → 写入 answers/（按人）更新 index。

    user_id 缺省取当前 learner 上下文；答卷与批改文件均按 (paper, uid) 落盘，
    群内多人各自一份。
    """
    md_text = (md_text or "").strip()
    if not md_text:
        return "答卷为空。请粘贴作答内容，或发送带作答区的 .md 文件。"
    pid = (paper_id or "").strip() or (_extract_paper_id(md_text) or "")
    if not pid:
        # 默认最近一份
        index = load_index()
        if index.get("papers"):
            pid = index["papers"][0]["id"]
        else:
            return (
                "无法识别 paper_id，且题库为空。"
                "请在答卷中保留「paper_id: YYYY-MM-DD_math」一行。"
            )

    key_path = os.path.join(KEYS_DIR, f"{pid}.json")
    key = _load_json(key_path, None)
    if not key:
        return f"找不到试卷密钥 `{pid}`，无法批改。请确认试卷 ID 是否正确。"

    user_ans = _parse_answers_from_md(md_text)
    # 仅有元信息、完全无作答区 → 不进 LLM，避免空批改/假正确
    if not user_ans:
        return (
            f"已识别试卷 `{pid}`，但未解析到任何作答区。\n"
            "请按卷面「### 作答区 N」下的代码块填写，或写「第 N 题答案：…」。\n"
            "空文件 / 只有标题不会进入批改。"
        )

    subject = key.get("subject") or ""
    from grade import grade_answer as grade_one

    results = []
    correct_n = 0
    answered_n = 0
    for it in key.get("items") or []:
        i = int(it["i"])
        ua = (user_ans.get(i) or "").strip()
        q_prev = it.get("question_preview") or f"第{i}题"
        if not ua:
            results.append(f"### 第{i}题\n未作答")
            continue
        answered_n += 1
        q_full = q_prev
        try:
            pub = get_exam_paper(pid)
            m = re.search(
                rf"##\s*第\s*{i}\s*题[\s\S]*?(?=##\s*第\s*\d+\s*题|##\s*答卷元信息|$)",
                pub,
            )
            if m:
                q_full = m.group(0)
        except Exception:
            pass
        try:
            # 传 key 里的 L2 + subject，让掌握度落到考纲正确位置并入周报
            report = grade_one(
                q_full,
                ua,
                kp_name=it.get("l2") or "",
                subject=subject,
            )
        except Exception as e:
            report = f"批改异常（已跳过本题，不影响其它题）：{e}"
        # structured verdict (BIG-TEACH-012c #13): 优先用 GradeResult 字段
        if isinstance(report, str):
            # exception fallback
            results.append(f"### 第{i}题\n{report}")
        else:
            is_correct = report.is_correct
            credit = report.credit
            if is_correct:
                correct_n += 1
            elif credit is not None and credit > 0:
                correct_n += 0.5
            line = f"### 第{i}题\n{report.feedback}"
            if report.kp_name and report.kp_name != "未分类":
                line += (
                    f"\n\n（{report.kp_name} 掌握 "
                    f"{report.p_mastery_before:.0%}→{report.p_mastery_after:.0%}"
                )
                line += "）" if report.status == "applied" else "，置信不足未更新）"
            results.append(line)

    total = len(key.get("items") or [])
    score = int(round(correct_n / total * 100)) if total else 0
    summary = (
        f"# 双周答卷批改 · `{pid}`\n\n"
        f"- 解析到作答区：{len(user_ans)} 个\n"
        f"- 非空作答：{answered_n}/{total}\n"
        f"- 判对（启发式）：{correct_n}/{total}\n"
        f"- **得分：{score}/100**\n\n"
        + "\n\n".join(results)
    )

    uid = (user_id or "").strip() or _uid()
    _ensure_dirs()
    ans_path = os.path.join(ANSWERS_DIR, f"{pid}_{uid}_answer.md")
    with open(ans_path, "w", encoding="utf-8") as f:
        f.write(md_text)
    with open(os.path.join(ANSWERS_DIR, f"{pid}_{uid}_grade.md"), "w", encoding="utf-8") as f:
        f.write(summary)

    index = load_index()
    for p in index.get("papers") or []:
        if p.get("id") == pid:
            p["status"] = "graded" if answered_n else "submitted_empty"
            p["answer_path"] = f"answers/{pid}_{uid}_answer.md"
            p["last_uid"] = uid
            break
    save_index(index)
    return summary


def run_biweekly_issue() -> dict:
    """生成并落盘数学+通信两份卷；不负责推送。"""
    with _lock:
        papers = []
        for subj in ("math", "comm"):
            paper = assemble_paper(subj)
            persist_paper(paper)
            papers.append(paper)
        ids = [p["paper_id"] for p in papers]
        if any(p["n_ok"] > 0 for p in papers):
            mark_run_success(ids)
        return {
            "paper_ids": ids,
            "papers": papers,
            "ok": all(p["n_ok"] >= 3 for p in papers),
        }
