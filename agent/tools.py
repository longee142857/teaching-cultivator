"""工具箱 — Agent 可调用的工具函数。

每个工具返回纯文本结果，由 Agent 组织为自然语言回复。
需要 bot 引用的工具（出题）通过参数传入，其余为纯函数。

题目上下文优先从按月记录 + 侧车索引读取（非内存），保证重启后不丢。
"""
import re, os, json
from config import DAILY_RECORD_DIR
from learner.context import current_user_id
from learner import paths as P


def _uid() -> str:
    return current_user_id()


def _read_latest_entry() -> dict | None:
    """从当月索引取最新一条题目字段。"""
    from record_index import latest_entry
    return latest_entry(DAILY_RECORD_DIR)


def find_record_entry(date: str, num: int = 0) -> str:
    """按日期（+可选题号）定位一条题目记录全文。

    num=0 表示取该日最后一条。供跨推送时段讨论使用。
    """
    from record_index import find_entry
    date = (date or "").strip()
    if not date:
        return "请提供日期，格式 YYYY-MM-DD"
    try:
        num = int(num or 0)
    except (TypeError, ValueError):
        num = 0
    entry = find_entry(DAILY_RECORD_DIR, date, num)
    if not entry:
        hint = f"#{num}" if num else "任意题号"
        return f"未找到 {date} {hint} 的题目记录"
    parts = [
        f"日期：{entry.get('date', date)} {entry.get('time', '')} #{entry.get('num', '?')}",
        f"科目：{entry.get('subject', '')} · {entry.get('difficulty', '')}",
    ]
    if entry.get("kp"):
        parts.append(f"知识点：{entry['kp']}")
    if entry.get("ref_source"):
        parts.append(f"参考来源：{entry['ref_source']}")
    parts.append("")
    parts.append("题目：")
    parts.append(entry.get("question") or entry.get("raw", ""))
    if entry.get("answer"):
        parts.append("")
        parts.append("解答：")
        parts.append(entry["answer"])
    return "\n".join(parts)


def get_learner_snapshot(days: int = 7) -> str:
    """返回当前学习者指标快照（与 system 注入同源）。"""
    from learner.snapshot import build_learner_snapshot
    return build_learner_snapshot(days=days)


def list_exam_bank(query: str = "", limit: int = 20) -> str:
    """双周检测卷题库目录（LLM 可查）。"""
    from learner.biweekly_exam import list_bank
    return list_bank(query=query, limit=limit)


def get_exam_paper(paper_id: str = "") -> str:
    """双周试卷全文。"""
    from learner.biweekly_exam import get_exam_paper as _get
    return _get(paper_id)


def submit_exam_answer_md(md_text: str = "", paper_id: str = "") -> str:
    """提交双周答卷 md 并批改。"""
    from learner.biweekly_exam import submit_answer_md
    return submit_answer_md(md_text, paper_id=paper_id or "")


def note_weak_point(subject: str, kp: str, reason: str = "") -> str:
    """用户自述某知识点薄弱 → 提高 weights 出题权重 + BKT 信号。"""
    from learner.weights_ops import bump_kp_weight, format_bump_result
    result = bump_kp_weight(subject, kp, reason=reason)
    text = format_bump_result(result)
    if result.get("ok"):
        from learner.snapshot import build_learner_snapshot
        text += "\n\n【更新后快照】\n" + build_learner_snapshot(days=7)
    return text


def list_recent_entries(days: int = 7) -> str:
    """列出最近 N 天题目索引（不含正文），供 LLM 选条目后再 find_record_entry。"""
    from record_index import list_recent
    try:
        days = int(days or 7)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 62))
    rows = list_recent(DAILY_RECORD_DIR, days)
    if not rows:
        return f"最近 {days} 天无题目记录"
    lines = [f"最近 {days} 天共 {len(rows)} 条："]
    for r in rows:
        kp = r.get("kp") or "-"
        ref = r.get("ref_source") or ""
        ref_s = f" | 参考:{ref}" if ref else ""
        lines.append(
            f"- {r.get('date')} {r.get('time', '')} #{r.get('num')} "
            f"{r.get('subject', '')}/{r.get('difficulty', '')} | {kp}{ref_s}"
        )
    lines.append("需要某条全文时调用 find_record_entry(date, num)。")
    return "\n".join(lines)


def generate_question(subject: str, kp_hint: str = "") -> str:
    """出一题（与定时推送共用编排闸），返回题目内容。"""
    from cultivate import (
        assess_state, decide, generate, record, get_last_answer, _save_last_push,
        _last_ref_source,
    )
    state = assess_state(subject)
    decision = decide(subject, state["bkt_log"])
    if decision.type == "defer":
        return f"【跳过】{decision.reason}"
    content = generate(subject, decision, source="chat")
    if not content:
        from cultivate import _rag_strict_blocked
        if _rag_strict_blocked:
            return "【生成失败：RAG 检索未达标，考点资料不足，无法出题】"
        return "【生成失败：编排质检未通过】"
    answer = get_last_answer()
    record(subject, content, decision, answer)
    kp = decision.reason.split(":")[0] if ":" in decision.reason else decision.reason
    # 去掉 [l3=]/[ability=] 后缀再存 kp
    kp = kp.split("[")[0].strip()
    _save_last_push(
        subject, decision, content, answer, _last_ref_source, kp=kp, source="personal",
    )
    return content


def _load_last_push_record() -> dict:
    """个人 last_push 或公共 last_class。"""
    for path in (P.last_push_path(), P.public_last_class_path()):
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def _load_last_push_question() -> str:
    """从 last_push / last_class 取完整题干（推送后权威源）。"""
    data = _load_last_push_record()
    return (data.get("question") or "").strip()


def _looks_truncated(provided: str, stored: str) -> bool:
    """判断 LLM 传入的题干是否为服务端全文的截断前缀。"""
    if not provided or not stored:
        return False
    if provided == stored:
        return False
    if stored.startswith(provided) and len(provided) < len(stored):
        return True
    # 历史 bug：内存/system 只留 200~300 字前缀
    if len(provided) <= 400 and provided[:80] in stored[:500]:
        return True
    return False


def grade_answer(last_question: str, user_answer: str) -> str:
    """批改作答，返回结果摘要。

    优先用 last_push / 题库全文；若 LLM 传入了截断片段则丢弃改用全文。
    """
    ua = (user_answer or "").strip()
    if not ua:
        return "未作答。请先写出解答再让我批改（空消息不会调用批改）。"

    provided = (last_question or "").strip()
    stored = _load_last_push_question()
    if not stored:
        entry = _read_latest_entry()
        if entry:
            stored = (entry.get("question") or "").strip()

    if not provided:
        question = stored
    elif _looks_truncated(provided, stored):
        question = stored
    else:
        question = provided

    if not question:
        return "批改失败：找不到完整题目，请先确认今日推送是否已记录"
    kp_name = ""
    subject = ""
    lp = _load_last_push_record()
    try:
        if lp:
            # 批改最近推送：始终带上 last_push 的 subject/kp（权威考点）
            if (lp.get("question") or "").strip() == question or not provided:
                kp_name = (lp.get("kp") or "").strip()
                subject = (lp.get("subject") or "").strip()
            elif not kp_name:
                subject = (lp.get("subject") or "").strip()
    except Exception:
        pass
    from grade import grade_answer as _grade
    try:
        result = _grade(question, ua, kp_name=kp_name, subject=subject)
        if result.credit is not None:
            tag = "🔶 部分正确"
        elif result.is_correct:
            tag = "✅ 正确"
        else:
            tag = "❌ 错误"
        extra = ""
        if result.kp_name:
            extra = f"（L2={result.kp_name}，掌握 {result.p_mastery_before:.0%}→{result.p_mastery_after:.0%}）"
        return f"{tag}，{result.feedback}\n{extra}".rstrip()
    except Exception as e:
        return f"批改失败：{e}"


def show_solution() -> str:
    """根据题库中最新的题目，调 LLM 生成解答。

    不是查缓存，是真做一遍——读题、理解、给出完整推导。
    """
    entry = _read_latest_entry()
    if not entry:
        return "NO_ENTRY"
    question = entry.get("question", "")
    if not question:
        return "NO_ENTRY"
    subject = entry.get("subject", "math")
    diff = entry.get("difficulty", "intermediate")

    from decide.router import call_llm
    system = (
        f"你是瑞贝卡，考研导师。请给下面这道{subject}题做完整解答。\n"
        "要求：步骤详细、推导完整、讲清思路，像老师在黑板上写板书一样。\n\n"
        "书写格式：行内公式只用 $...$；独立公式块单独成行用 $$...$$；"
        "禁止 \\(...\\) 和 \\[...\\]；选择题每选项单独一行。"
    )
    user = f"题目（难度{diff}）：\n{question}\n\n请给出完整解答。"
    try:
        solution = call_llm(system, user, "explain", diff)
        from math_format import normalize_markdown_body
        question = normalize_markdown_body(question)
        solution = normalize_markdown_body(solution)
        return f"题目：{question}\n\n解答：\n{solution}"
    except Exception as e:
        return f"SOLUTION_FAILED|{question}"


def adjust_difficulty(subject: str, level: str) -> str:
    """调整科目难度偏好（只改偏好，不改变掌握度 — BIG-TEACH-012a #5）。"""
    from cultivate import set_difficulty_pref
    ok = set_difficulty_pref(subject, level)
    result = f"{subject} 难度已调整为 {level}" if ok else "调整失败"
    # 可选审计日志（不影响 mastery）
    try:
        from datetime import datetime, timezone
        entry = _read_latest_entry()
        kp = ""
        if entry:
            kp = (entry.get("kp") or "").strip()
            if not kp and entry.get("raw"):
                m = re.search(r"决策原因：(.+)", entry["raw"])
                if m:
                    kp = m.group(1).split(":")[0].strip()
        if kp:
            log_path = P.answer_log_path()
            audit = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "user_id": _uid(),
                "knowledge_point": kp,
                "correct": None,
                "conv_tag": "adjust_difficulty",
                "mastery_before": None,
                "mastery_after": None,
                "update_applied": False,
                "update_reason": "audit_only",
                "status": "audit",
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(audit, ensure_ascii=False) + "\n")
            result += f"\n（已记录 '{kp}' 审计日志，不影响掌握度）"
    except Exception:
        pass
    return result


def build_report(days: int = 7) -> str:
    """生成学习报告。"""
    from learner.profile import build_weekly
    from learner.reporter import format_detailed
    profile = build_weekly(weeks=max(1, days // 7))
    return format_detailed(profile)


def override_grade(kp: str, correct: bool, subject: str = "", credit: float = 0.0) -> str:
    """覆盖最近一条批改记录并重算掌握度（BIG-TEACH-012a #7a）。"""
    from bkt import KCState
    from datetime import datetime, timezone

    log_path = P.answer_log_path()
    if not os.path.exists(log_path):
        return f"'{kp}' 无批改记录可覆盖"

    entries: list[dict] = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line_s = line.strip()
                if not line_s:
                    continue
                try:
                    e = json.loads(line_s)
                    if e.get("knowledge_point") == kp:
                        entries.append(e)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        return f"读取 answer-log 失败：{e}"

    if not entries:
        return f"'{kp}' 无历史记录"

    skip_status = {"pending", "audit"}
    # 最近一条仍有效的已应用作答 → 被本次 override 取代
    supersedes_ts = ""
    already_superseded: set[str] = set()
    for entry in entries:
        if entry.get("supersedes_ts"):
            already_superseded.add(str(entry["supersedes_ts"]))
    for entry in reversed(entries):
        if entry.get("status") in skip_status:
            continue
        ts = str(entry.get("ts") or "")
        if ts in already_superseded:
            continue
        if entry.get("update_applied") and isinstance(entry.get("correct"), bool):
            supersedes_ts = ts
            break

    superseded = set(already_superseded)
    if supersedes_ts:
        superseded.add(supersedes_ts)

    kc = KCState()
    replayed = 0
    for entry in entries:
        if entry.get("status") in skip_status:
            continue
        if str(entry.get("ts") or "") in superseded:
            continue
        if not entry.get("update_applied"):
            continue
        ec = entry.get("correct")
        if not isinstance(ec, bool):
            continue
        try:
            kc.update(
                ec,
                item_type=str(entry.get("item_type", "unknown")),
                credit=entry.get("credit"),
                force=True,
            )
            replayed += 1
        except Exception:
            pass

    # 应用覆盖判定（一次）
    if isinstance(correct, bool):
        cr = float(credit) if credit else None
        kc.update(correct, item_type="unknown", credit=cr, force=True)
        replayed += 1

    override_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user_id": _uid(),
        "knowledge_point": kp,
        "correct": correct,
        "credit": float(credit) if credit else None,
        "item_type": "unknown",
        "update_applied": True,
        "update_reason": "user_override",
        "status": "overridden",
        "supersedes_ts": supersedes_ts,
        "state": kc.to_dict(),
        "mastery_after": round(kc.p_mastery, 4),
    }
    if subject:
        override_entry["subject"] = subject
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(override_entry, ensure_ascii=False) + "\n")
    except Exception as e:
        return f"写入 override 失败：{e}"

    return (
        f"'{kp}' 已覆盖（correct={correct}）。"
        f"当前掌握度 {kc.p_mastery:.0%}（重放 {replayed} 条，opportunity={kc.opportunity_count}）"
    )


def github_push(repo_path: str = "", commit_msg: str = "") -> str:
    """推送本地仓库到 GitHub。

    参数:
        repo_path: 仓库路径（空=推送 teaching-cultivator 自身）
        commit_msg: 提交信息（空=自动生成）
    返回:
        推送结果文本
    """
    from deliver.github_pusher import GithubPusher, detect_remote
    if not repo_path:
        repo_path = os.path.dirname(os.path.dirname(__file__))
    repo_path = os.path.normpath(repo_path)
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        # 尝试向上查找 .git
        for parent in iter(lambda: os.path.dirname(repo_path), repo_path):
            if os.path.isdir(os.path.join(parent, ".git")):
                repo_path = parent
                break
    if not commit_msg:
        commit_msg = f"auto push: {os.path.basename(repo_path)}"
    pusher = GithubPusher()
    result = pusher.push(repo_path, commit_msg)
    lines = [result["msg"]]
    if result["ok"]:
        remote = result.get("remote") or detect_remote(repo_path)
        lines.append(f"链接: {remote}")
    else:
        lines.append(pusher.proxy_info)
    return "\n".join(lines)
