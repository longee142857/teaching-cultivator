"""工具箱 — Agent 可调用的工具函数。

每个工具返回纯文本结果，由 Agent 组织为自然语言回复。
需要 bot 引用的工具（出题）通过参数传入，其余为纯函数。

题目上下文优先从按月记录 + 侧车索引读取（非内存），保证重启后不丢。
"""
import re, os, json
from learner.context import current_user_id


def _uid() -> str:
    return current_user_id()


def _db_sid() -> str:
    try:
        return current_user_id() or ""
    except Exception:
        return ""


def _read_latest_entry() -> dict | None:
    """DB 中该学员最新可见推送（当前题字段）。"""
    try:
        from learner.db import get_store
        return get_store().get_latest_push(_db_sid() or None)
    except Exception:
        return None


def find_record_entry(date: str, num: int = 0) -> str:
    """按日期（+可选题号）定位一条题目记录全文。

    num=0 表示取该日最后一条。供跨推送时段讨论使用。
    """
    date = (date or "").strip()
    if not date:
        return "请提供日期，格式 YYYY-MM-DD"
    try:
        num = int(num or 0)
    except (TypeError, ValueError):
        num = 0
    try:
        from learner.db import get_store
        entry = get_store().find_entry(date, num, _db_sid() or None)
    except Exception:
        entry = None
    if not entry:
        hint = f"#{num}" if num else "任意题号"
        return f"未找到 {date} {hint} 的题目记录"
    parts = [
        f"日期：{entry.get('day', date)} {entry.get('time', '')} #{entry.get('seq', '?')}",
        f"科目：{entry.get('subject', '')} · {entry.get('difficulty', '')}",
    ]
    if entry.get("kp"):
        parts.append(f"知识点：{entry['kp']}")
    if entry.get("ref_source"):
        parts.append(f"参考来源：{entry['ref_source']}")
    parts.append("")
    parts.append("题目：")
    parts.append(entry.get("question") or "")
    if entry.get("answer"):
        parts.append("")
        parts.append("解答：")
        parts.append(entry["answer"])
    return "\n".join(parts)


def get_learner_snapshot(days: int = 7) -> str:
    """返回当前学习者指标快照（与 system 注入同源）。"""
    from learner.snapshot import build_learner_snapshot
    return build_learner_snapshot(days=days)


def get_active_question() -> str:
    """返回当前正在做的题（单一真相源：合并个人 last_push 与公共 last_class，取最新）。"""
    from learner.active_question import get_active_question as _get
    from learner.context import current_user_id
    try:
        sid = current_user_id() or ""
    except Exception:
        sid = ""
    aq = _get(sid)
    if not aq.get("found"):
        return "当前没有进行中的题目。"
    parts = [
        f"科目：{aq.get('subject', '') or '?'}",
        f"知识点：{aq.get('kp', '') or '?'}",
        f"难度：{aq.get('difficulty', '') or '?'}",
        f"来源：{aq.get('source', '') or '?'}",
        f"推送时间：{aq.get('timestamp', '') or '?'}",
        "",
        "题目：",
        aq.get("question", ""),
    ]
    return "\n".join(parts)


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


def get_exam_result(paper_id: str = "", user_id: str = "") -> str:
    """查看某人对某张双周卷的批改报告与作答（试卷库按人可查）。"""
    from learner.biweekly_exam import get_exam_result as _get
    return _get(paper_id, user_id=user_id or "")


def note_weak_point(subject: str, kp: str, reason: str = "") -> str:
    """用户自述某知识点薄弱 → 只提高出题权重，不记 BKT 假答错。

    record_bkt=False：自述薄弱 ≠ 答错，掌握度只由实际作答决定。
    """
    from learner.weights_ops import bump_kp_weight, format_bump_result
    result = bump_kp_weight(subject, kp, reason=reason, record_bkt=False)
    text = format_bump_result(result)
    if result.get("ok"):
        from learner.snapshot import build_learner_snapshot
        text += "\n\n【更新后快照】\n" + build_learner_snapshot(days=7)
    return text


def list_recent_entries(days: int = 7) -> str:
    """列出最近 N 天题目索引（不含正文），供 LLM 选条目后再 find_record_entry。"""
    try:
        days = int(days or 7)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 62))
    try:
        from learner.db import get_store
        rows = get_store().list_recent_pushes(_db_sid() or None, days)
    except Exception:
        rows = []
    if not rows:
        return f"最近 {days} 天无题目记录"
    rows = sorted(
        rows, key=lambda r: (r.get("day", ""), r.get("seq", 0), r.get("pushed_at", ""))
    )
    lines = [f"最近 {days} 天共 {len(rows)} 条："]
    for r in rows:
        kp = r.get("kp") or "-"
        ref = r.get("ref_source") or ""
        ref_s = f" | 参考:{ref}" if ref else ""
        lines.append(
            f"- {r.get('day')} {r.get('time', '')} #{r.get('seq')} "
            f"{r.get('subject', '')}/{r.get('difficulty', '')} | {kp}{ref_s}"
        )
    lines.append("需要某条全文时调用 find_record_entry(date, num)。")
    return "\n".join(lines)


def list_today_questions(subject: str = "") -> str:
    """列出今日（Asia/Shanghai）可见推送题，带已答标记；按推送时间序（非未答优先）。"""
    try:
        from learner.db import get_store, shanghai_day
        today = shanghai_day(None)
        rows = get_store().list_today_pushes(_db_sid() or None, today)
    except Exception:
        return "今日题目查询失败"
    if subject:
        subj = (subject or "").strip().lower()
        rows = [r for r in rows if (r.get("subject") or "").lower() == subj]
    if not rows:
        return f"今日（{today}）没有进行中的题目"
    lines = [f"今日（{today}）共 {len(rows)} 道："]
    for r in rows:
        answered = "已作答" if r.get("answered") else "未作答"
        lines.append(
            f"- {r.get('time', '')} #{r.get('seq')} [{answered}] "
            f"{r.get('subject', '')}/{r.get('difficulty', '')} | {r.get('kp', '-')}"
        )
    lines.append("需要全文时调用 find_record_entry(date, num)。")
    return "\n".join(lines)


def generate_question(subject: str, kp_hint: str = "") -> str:
    """从 ready 题库抽取一题（与定时推送同一 pick 契约）；尊重 kp_hint。"""
    from cultivate import (
        assess_state, decide, _save_last_push, _bkt_available,
    )
    from learner.item_bank import (
        pick_for_push, pick_technique_for_kp, live_fallback_enabled,
    )
    from learner.db import get_store
    from intervention import InterventionDecision

    if not _bkt_available:
        return "【失败】BKT 不可用"
    state = assess_state(subject)
    decision = decide(subject, state["bkt_log"])
    hint = (kp_hint or "").strip()
    if hint and decision.type != "defer":
        ability = getattr(decision, "ability_goal", "") or ""
        reason = f"{hint}[ability={ability}]" if ability else hint
        decision = InterventionDecision(
            type=decision.type,
            difficulty=decision.difficulty,
            reason=reason,
            priority=getattr(decision, "priority", 3),
            ability_goal=ability,
        )
    if decision.type == "defer":
        return f"【跳过】{decision.reason}"

    kp = decision.reason.split(":")[0] if ":" in decision.reason else decision.reason
    kp = kp.split("[")[0].strip()
    tech = pick_technique_for_kp(kp)
    item = pick_for_push(subject, kp=kp, technique=tech, learner_id=_db_sid() or None)
    if not item:
        if live_fallback_enabled():
            from cultivate import generate, record, get_last_answer, _last_ref_source
            content = generate(subject, decision, source="chat")
            if not content:
                return "【生成失败：编排质检未通过】"
            answer = get_last_answer()
            record(subject, content, decision, answer)
            _save_last_push(
                subject, decision, content, answer, _last_ref_source, kp=kp, source="personal",
            )
            return content
        return f"【题库为空】暂无匹配 ready 题（kp={kp}）。请等待分时段预生成补货。"

    store = get_store()
    try:
        push_id = store.record_push_for_item(
            item_id=int(item["id"]),
            learner_id=_db_sid() or None,
            slot=subject,
            decision_type=decision.type,
            reason=decision.reason,
        )
    except Exception as e:
        return f"【失败】落库推送失败：{e}"

    content = item.get("question") or ""
    answer = item.get("answer") or ""
    ref_source = item.get("ref_source") or ""
    try:
        from cultivate import enqueue_sync_from_push
        enqueue_sync_from_push(
            store, push_id, subject, decision, content, answer, ref_source
        )
    except Exception:
        pass
    _save_last_push(
        subject,
        decision,
        content,
        answer,
        ref_source,
        kp=kp,
        source="personal",
    )
    return content


def _load_last_push_record() -> dict:
    """DB 中该学员最新可见推送（当前题元信息，权威源）。"""
    try:
        from learner.db import get_store
        rec = get_store().get_latest_push(_db_sid() or None)
        return rec or {}
    except Exception:
        return {}


def _load_last_push_question() -> str:
    """从 DB 最新推送取完整题干（权威源）。"""
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


def grade_answer(last_question: str = "", user_answer: str = "") -> str:
    """批改作答，返回结果摘要。

    优先用 last_push / 题库全文；若 LLM 传入了截断片段则丢弃改用全文。
    last_question 可空（系统自动读当前题），与 HTTP API TS 端 Optional 语义对齐。
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
        pending_note = ""
        if getattr(result, "status", "applied") == "pending":
            pending_note = (
                "\n⚠️ 批改置信不足，掌握度未更新（pending）。"
                "若你认为批错了，直接说「批错了」即可纠正。"
            )
        # 横幅回显「批的是哪道」：KP + 题目时间戳，让 LLM 明确批改对象（防串题/静默批错题）
        kp_banner = f"[KP={result.kp_name}]" if result.kp_name else "[KP=未分类]"
        ts = (lp.get("timestamp") or "").strip()[:19] if lp else ""
        ts_banner = f"[TS={ts}]" if ts else ""
        return f"{kp_banner}{ts_banner} {tag}，{result.feedback}\n{extra}{pending_note}".rstrip()
    except Exception as e:
        return f"批改失败：{e}"


def show_solution() -> str:
    """优先渲染题库结构化 solution；否则现场 LLM 解答。"""
    entry = _read_latest_entry()
    if not entry:
        # DB 最新推送
        entry = _load_last_push_record()
    if not entry:
        return "NO_ENTRY"
    question = entry.get("question", "")
    if not question:
        return "NO_ENTRY"

    solution = entry.get("solution") or {}
    if not solution:
        try:
            from learner.db import get_store
            item = get_store().get_item_by_question(question, entry.get("subject") or "")
            if item:
                solution = item.get("solution") or {}
                entry.setdefault("answer", item.get("answer") or "")
        except Exception:
            pass

    steps = (solution or {}).get("steps") or []
    if steps:
        from math_format import normalize_markdown_body
        question = normalize_markdown_body(question)
        lines = [f"题目：{question}", "", "解答（结构化）："]
        for s in steps:
            if isinstance(s, dict):
                lines.append(f"- ({s.get('id') or '?'}) {s.get('text') or ''}")
            else:
                lines.append(f"- {s}")
        fa = (solution or {}).get("final_answer") or entry.get("answer") or ""
        if fa:
            lines.append("")
            lines.append(f"最终答案：{fa}")
        return normalize_markdown_body("\n".join(lines))

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
        sol = call_llm(system, user, "explain", diff)
        from math_format import normalize_markdown_body
        question = normalize_markdown_body(question)
        sol = normalize_markdown_body(sol)
        return f"题目：{question}\n\n解答：\n{sol}"
    except Exception:
        return f"SOLUTION_FAILED|{question}"


def adjust_difficulty(subject: str, level: str) -> str:
    """调整科目难度偏好（只改偏好，不改变掌握度 — BIG-TEACH-012a #5）。"""
    from cultivate import set_difficulty_pref
    ok = set_difficulty_pref(subject, level)
    result = f"{subject} 难度已调整为 {level}" if ok else "调整失败"
    # 可选审计日志（不影响 mastery）
    try:
        from learner.roster import allows_learning_writes

        if not allows_learning_writes():
            return result
        from datetime import datetime, timezone
        entry = _read_latest_entry()
        kp = ""
        if entry:
            kp = (entry.get("kp") or "").strip()
            if not kp and entry.get("reason"):
                kp = entry["reason"].split(":")[0].strip()
        if kp:
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
            from learner.db import get_store
            get_store().add_attempt_entry(audit)
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


def propose_override_grade(kp: str, correct: bool, subject: str = "",
                           credit: float = 0.0) -> str:
    """用户说「批错了」→ 登记纠正提案，确认卡确认后才覆盖 mastery。

    不直接写 answer-log。成功时末尾带 `[OVERRIDE]<token>` 供 harness 发确认卡。
    """
    from learner.override_edit import propose_override
    from learner.context import current_user_id
    result = propose_override(
        kp, correct, subject=subject, credit=credit,
        staff_id=current_user_id(),
    )
    if not result.get("ok"):
        return f"登记失败：{result.get('error', '未知错误')}"
    return (
        f"已登记「{result['kp']}」的批改纠正提案（correct={'对' if result['correct'] else '错'}）。\n"
        f"等待用户点击确认卡片后才会重算掌握度。\n"
        f"[OVERRIDE]{result['token']}"
    )


def confirm_override(token: str = "") -> str:
    """确认批改纠正提案并覆盖 mastery。"""
    from learner.override_edit import confirm_override as _confirm
    from learner.context import current_user_id
    r = _confirm(token, staff_id=current_user_id())
    if r.get("ok"):
        return r.get("msg", "已覆盖")
    return r.get("error", "确认失败")


def cancel_override(token: str = "") -> str:
    """取消批改纠正提案（不覆盖）。"""
    from learner.override_edit import cancel_override as _cancel
    from learner.context import current_user_id
    r = _cancel(token, staff_id=current_user_id())
    if r.get("ok"):
        return f"已取消「{r.get('kp', '')}」的纠正，未重算掌握度。"
    return r.get("error", "取消失败")


def override_grade(kp: str, correct: bool, subject: str = "", credit: float = 0.0) -> str:
    """覆盖最近一条批改记录并重算掌握度（BIG-TEACH-012a #7a；DB 读写）。"""
    from bkt import KCState
    from datetime import datetime, timezone
    from learner.db import get_store

    store = get_store()
    uid = _uid()
    try:
        entries = [
            e for e in store.get_attempts(uid) if e.get("knowledge_point") == kp
        ]
    except Exception as e:
        return f"读取作答记录失败：{e}"

    if not entries:
        return f"'{kp}' 无批改记录可覆盖"

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
        "user_id": uid,
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
        store.add_attempt_entry(override_entry)
        store.set_mastery(uid, kp, kc.to_dict(), override_entry["ts"])
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


# ── 交互层升级（KB-0121）：小库只读 / 回填登记 / 考纲全量 / 知识点提案 ──


def list_knowledge_points(subject: str = "math", query: str = "") -> str:
    """列出考纲全部知识点（L2 章节 + 子 L3 考点），可按关键词过滤。"""
    from learner.kp_registry import load_syllabus, syllabus_subject
    subj = syllabus_subject(subject)
    syl = load_syllabus(subj)
    kps = syl.get("kps") or {}
    if not kps:
        return f"{subj} 考纲暂无知识点。"
    q = (query or "").strip().lower()
    lines = [f"{subj} 考纲知识点（共 {len(kps)} 个章节）："]
    for l2, meta in kps.items():
        if not isinstance(meta, dict):
            continue
        l3s = [l3 for l3 in meta.get("l3") or [] if isinstance(l3, dict)]
        parts = [
            f"{l3.get('name', '')} `{l3.get('id', '')}`" for l3 in l3s
        ]
        row = f"- {l2}（{len(parts)} 子考点）：{'、'.join(parts)[:200] if parts else '无'}"
        if q:
            hay = json.dumps({"l2": l2, "names": parts}, ensure_ascii=False).lower()
            if q not in hay:
                continue
        lines.append(row)
        if len(lines) > 120:
            lines.append("…（考点较多，可加关键词过滤）")
            break
    return "\n".join(lines) if len(lines) > 1 else f"未找到含「{q}」的知识点。"


def kb_query(subject: str = "math", kp: str = "") -> str:
    """查询小库中某考点的已收录教材证据（只读，不增加命中计数）。"""
    from learner import kb_cache
    from learner.kp_registry import resolve_kp, syllabus_subject
    subj = syllabus_subject(subject)
    kp = (kp or "").strip()
    if not kp:
        return "请提供考点关键词，如「洛必达法则」。"
    entry = kb_cache.peek(subj, kp)
    if not entry:
        resolved = resolve_kp(subj, kp)
        if resolved:
            entry = kb_cache.peek(subj, resolved)
    if not entry:
        return (
            f"小库未收录「{kp}」。可调用 kb_enqueue 把该考点加入教材回填队列，"
            "回填后再来查，我就能给出教材原文依据。"
        )
    lines = [f"考点「{kp}」小库已收录（{len(entry.get('snippets') or [])} 条证据）："]
    for s in entry.get("snippets") or []:
        if not isinstance(s, dict):
            continue
        src = (s.get("source") or "?").strip()
        page = str(s.get("page") or "").strip()
        text = (s.get("text") or "").strip()
        loc = f"{src} {page}".strip()
        lines.append(f"- [{loc}] {text[:160]}")
    return "\n".join(lines)


def kb_enqueue(subject: str = "math", kp: str = "", query: str = "") -> str:
    """把考点加入小库教材回填队列（由本机教材检索回填，不直接写证据）。"""
    from learner import kb_cache
    from learner.kp_registry import syllabus_subject
    subj = syllabus_subject(subject)
    kp = (kp or "").strip()
    if not kp:
        return "请提供考点关键词。"
    r = kb_cache.enqueue(subj, kp, query=query or kp, reason="agent_chat")
    if r.get("ok") and r.get("deduped"):
        return f"「{kp}」已在回填队列中，无需重复登记。"
    if r.get("ok") and r.get("cached"):
        return f"「{kp}」小库已有缓存，无需回填。"
    if r.get("ok"):
        return f"已把「{kp}」加入教材回填队列，稍后会自动回填，回填后即可查询。"
    return f"登记失败：{r.get('error') or '未知'}"


def propose_add_kp(subject: str, l2: str, name: str, aliases: str = "") -> str:
    """登记新 L3 子考点提案（不写入）；成功时末尾带 `[PROPOSAL]<token>` 供 harness 发确认卡。"""
    from learner import kp_edit
    from learner.context import current_user_id
    al = [a for a in re.split(r"[、，,；;]", aliases or "") if (a or "").strip()]
    r = kp_edit.propose_l3(subject, l2, name, al or None,
                           staff_id=current_user_id())
    if not r.get("ok"):
        return r.get("error", "登记失败")
    return (
        f"已登记待确认的子考点提案：\n"
        f"- 章节：{r['l2']}\n"
        f"- 子考点：{r['name']}\n"
        f"- 拟生成 l3_id：{r['l3_id']}\n"
        f"等待用户点击确认卡片后写入考纲。\n"
        f"[PROPOSAL]{r['token']}"
    )


def confirm_add_kp(token: str = "") -> str:
    """确认知识点提案并写入考纲。"""
    from learner import kp_edit
    from learner.context import current_user_id
    r = kp_edit.confirm_l3(token, staff_id=current_user_id())
    if r.get("ok"):
        return (
            f"已确认并写入考纲：{r['l2']} → 「{r['name']}」"
            f"（l3_id={r['l3_id']}）。之后出题/双周卷可覆盖该子考点。"
        )
    return r.get("error", "确认失败")


def cancel_add_kp(token: str = "") -> str:
    """取消知识点提案（不写入）。"""
    from learner import kp_edit
    from learner.context import current_user_id
    r = kp_edit.cancel_l3(token, staff_id=current_user_id())
    if r.get("ok"):
        return f"已取消「{r['name']}」的添加，未写入考纲。"
    return r.get("error", "取消失败")


def write_feedback(title: str = "", content: str = "") -> str:
    """Cow 写反馈/想法到云端 problem_queue，同步到本机 tasks/problem/。

    用于 Cow 向开发者传递系统问题、改进建议或想法。写的是队列目录，
    不是系统状态；不触发任何修改。
    """
    title = (title or "").strip() or "untitled"
    content = (content or "").strip()
    if not content:
        return "反馈内容为空，未写入。请提供 content。"
    from config import DATA_DIR
    qdir = os.path.join(DATA_DIR, "problem_queue")
    os.makedirs(qdir, exist_ok=True)
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # 文件名 sanitize
    slug = re.sub(r"[^\w一-鿿-]+", "_", title)[:40].strip("_")
    path = os.path.join(qdir, f"{ts}_{slug}.md")
    block = (
        f"# {title}\n\n"
        f"- 时间：{datetime.datetime.now().isoformat()}\n"
        f"- 来源：cow\n\n"
        f"## 内容\n\n{content}\n"
    )
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(block)
    except OSError as e:
        return f"写入反馈失败：{e}"
    return f"已写入反馈：{os.path.basename(path)}（将同步到本机 tasks/problem/）"


def ocr_handwriting(image_id: str = "") -> str:
    """识别私聊暂存的手写/演算图片（不批改）。

    image_id 可空：用该学员最近一张入站图。用户说「帮我看看图里写了什么」时用。
    """
    from learner.context import current_user_id
    from deliver.inbound_images import resolve_image
    from deliver.simpletex import is_configured, ocr_image

    if not is_configured():
        return "SimpleTex 未配置，无法识别。请管理员写入 SIMPLETEX_UAT 或 APP 凭证。"
    try:
        uid = current_user_id()
    except Exception:
        uid = ""
    try:
        iid, data, meta = resolve_image(uid, image_id)
    except FileNotFoundError:
        return (
            "没有可用的暂存图片。请让用户在人机私聊直接发图（可附说明），"
            "然后再调用本工具。"
        )
    out = ocr_image(data, filename=str(meta.get("filename") or "handwriting.jpg"))
    if not out.get("ok"):
        return f"识别失败（{out.get('error') or 'unknown'}）。可请用户换更清晰的照片。"
    text = (out.get("text") or "").strip()
    conf = out.get("conf")
    conf_note = f"，置信 {conf:.0%}" if isinstance(conf, (int, float)) else ""
    return f"[image_id={iid}{conf_note}]\n{text}"


def grade_handwriting(image_id: str = "") -> str:
    """把私聊暂存图片 OCR 后，按当前题调用 grade_answer 批改。

    仅当用户明确这是作答/交卷/重做时调用；不要对随便发的截图、表情包调用。
    image_id 可空：用该学员最近一张入站图。
    """
    from learner.context import current_user_id
    from deliver.inbound_images import resolve_image
    from deliver.simpletex import is_configured, ocr_image

    if not is_configured():
        return "SimpleTex 未配置，无法识别作答图。"
    try:
        uid = current_user_id()
    except Exception:
        uid = ""
    try:
        iid, data, meta = resolve_image(uid, image_id)
    except FileNotFoundError:
        return (
            "没有可用的暂存图片。请用户先在人机私聊发作答照片，"
            "再说「这是作答」后你再调用 grade_handwriting。"
        )
    out = ocr_image(data, filename=str(meta.get("filename") or "handwriting.jpg"))
    if not out.get("ok"):
        return (
            f"识别失败（{out.get('error') or 'unknown'}），未批改。"
            "请用户重拍更清晰的照片。"
        )
    text = (out.get("text") or "").strip()
    if not text:
        return "识别结果为空，未批改。"
    grade_msg = grade_answer("", text)
    conf = out.get("conf")
    conf_note = f"（置信 {conf:.0%}）" if isinstance(conf, (int, float)) else ""
    preview = text if len(text) <= 600 else (text[:600] + "…")
    return (
        f"📷 OCR{conf_note} image_id={iid}：\n```\n{preview}\n```\n\n"
        f"——\n{grade_msg}"
    )
