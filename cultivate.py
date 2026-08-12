"""培养闭环：assess → decide → generate → deliver → record

用法:
    python cultivate.py math      # 推数学一
    python cultivate.py comm      # 推通信原理
    python cultivate.py review    # 错题复盘
"""
from __future__ import annotations
import sys, os, json, datetime

from config import DATA_DIR, DAILY_RECORD_DIR, RAG_FALLBACK
from learner import paths as P
from learner.context import current_user_id, get_binding, bind_owner_schedule
from decide.router import call_llm
from deliver.bridge import get_bridge
from prompts.prompt_builder import PromptBuilder
from prompts.ref_picker import RefPicker

# ── 基建模块（复用 knowledge-system/lib/） ──
try:
    from bkt import BKTLogger, KCState
    _bkt_available = True
except ImportError as _bkt_err:
    print(f"[cultivate] WARNING: cannot import bkt: {_bkt_err}")
    print("[cultivate] Set KB_PATH or ensure knowledge-system/lib is accessible")
    BKTLogger = None  # type: ignore[assignment]
    KCState = None  # type: ignore[assignment]
    _bkt_available = False
from intervention import decide_intervention, InterventionDecision
from heartbeat_summary import extract as get_heartbeat_summary


# ── 答案追踪 + 难度偏好 ──
_last_answer = ""
_last_ref_source = ""
_last_item_form = ""  # BIG-TEACH-011d
_rag_strict_blocked = False  # BIG-TEACH-011c: agent 区分 RAG miss vs 质检失败


def _uid() -> str:
    return current_user_id()


def _difficulty_path() -> str:
    return P.difficulty_path()


def _last_push_write_path(*, source: str = "") -> str:
    """定时公共课写 public/last_class；私聊自出题写个人 last_push。"""
    binding = get_binding()
    if binding == "schedule" or source == "schedule":
        return P.public_last_class_path()
    return P.last_push_path()


def _last_push_read_path() -> str:
    """读取最近推送元信息：公共课优先 public，否则个人。"""
    pub = P.public_last_class_path()
    if os.path.isfile(pub):
        return pub
    return P.last_push_path()


def _load_difficulty_pref() -> dict:
    try:
        path = _difficulty_path()
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def set_difficulty_pref(subject: str, level: str) -> bool:
    """设置用户难度偏好。level: basic / intermediate / challenge"""
    if level not in ("basic", "intermediate", "challenge"):
        return False
    try:
        from learner.roster import allows_learning_writes

        if not allows_learning_writes():
            return False
    except Exception:
        pass
    pref = _load_difficulty_pref()
    pref[subject] = level
    try:
        path = _difficulty_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(pref, f)
        return True
    except Exception:
        return False


def get_difficulty_pref(subject: str) -> str:
    return _load_difficulty_pref().get(subject, "")


def get_last_answer() -> str:
    return _last_answer


def _save_last_push(subject: str, decision: InterventionDecision, content: str,
                    answer: str = "", ref_source: str = "", kp: str = "",
                    *, source: str = ""):
    try:
        from learner.roster import allows_learning_writes

        if not allows_learning_writes():
            return
    except Exception:
        pass
    try:
        record = {
            "subject": subject,
            "difficulty": decision.difficulty,
            "question": content,
            "answer": answer,
            "timestamp": datetime.datetime.now().isoformat(),
        }
        if ref_source:
            record["ref_source"] = ref_source
        if kp:
            record["kp"] = kp
        # BIG-TEACH-011d: 记录 ability_goal / item_form / l3_id
        if hasattr(decision, 'ability_goal') and decision.ability_goal:
            record["ability_goal"] = decision.ability_goal
        global _last_item_form
        if _last_item_form:
            record["item_form"] = _last_item_form
        from learner.kp_registry import parse_l3_from_reason
        l3_id = parse_l3_from_reason(getattr(decision, "reason", "") or "")
        if l3_id:
            record["l3_id"] = l3_id
        path = _last_push_write_path(source=source)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
        if kp and subject in ("math", "comm", "review"):
            from learner.kp_registry import append_recent_pick
            append_recent_pick(subject if subject != "review" else "math", kp)
        # 成功推送后才记 ability 轮换（避免 RAG/编排失败污染）
        if hasattr(decision, "ability_goal") and decision.ability_goal:
            from learner.ability_cycle import append_recent_ability
            append_recent_ability(subject, decision.ability_goal)
    except Exception:
        pass


# ═══════════════════════════════════════════
# 1. ASSESS — 评估当前状态
# ═══════════════════════════════════════════

def assess_state(subject: str) -> dict:
    """返回当前学习状态摘要。"""
    summary = get_heartbeat_summary()
    from learner.bkt_db import DbBKTLogger
    return {
        "heartbeat": summary,
        "subject": subject,
        "bkt_log": DbBKTLogger(),
    }


# ═══════════════════════════════════════════
# 2. DECIDE — 干预决策
# ═══════════════════════════════════════════


def _load_weights() -> dict:
    """加载当前学员 weights.json。"""
    from learner.weights_ops import load_weights
    return load_weights()


def _get_days_since_last_push(subject: str) -> float | None:
    """从 DB 读取该科目距上次推送天数。

    若 subject != "all" 且最新推送科目不匹配，视为未知返回 None。
    """
    try:
        from learner.db import get_store
        from learner.context import current_user_id
        sid = current_user_id() or ""
    except Exception:
        sid = ""
    try:
        data = get_store().get_latest_push(sid or None)
        if not data:
            return None
        if subject != "all" and data.get("subject") != subject:
            return None
        ts = data.get("pushed_at") or ""
        if ts:
            last = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=datetime.timezone.utc)
            delta = datetime.datetime.now(datetime.timezone.utc) - last
            return max(0.0, delta.total_seconds() / 86400)
    except Exception:
        pass
    return None


def _resolve_log_kp(entry_kp: str) -> str | None:
    """把 answer-log 里的自由文本/别名归一到考纲 L2 名。"""
    hint = (entry_kp or "").strip()
    if not hint:
        return None
    try:
        from learner.kp_registry import resolve_kp
        for subj in ("math", "comm"):
            resolved = resolve_kp(subj, hint)
            if resolved:
                return resolved
    except Exception:
        pass
    return None


def _kp_history_match(entry_kp: str, target_kp: str) -> bool:
    """判断日志知识点是否对应目标 L2（精确 / 互含 / 别名归一）。"""
    ek = (entry_kp or "").strip()
    tk = (target_kp or "").strip()
    if not ek or not tk:
        return False
    if ek == tk:
        return True
    if tk in ek or ek in tk:
        return True
    return _resolve_log_kp(ek) == tk


def _get_consecutive_failures(user_id: str, bkt_log: BKTLogger,
                              kp: str | None = None) -> int:
    """从 answer-log 读取该知识点连续答错次数。

    指定 kp 时只计该 L2（含别名）；无匹配记录返回 0，绝不回退全局。
    """
    history = bkt_log.get_user_history(user_id) if hasattr(bkt_log, 'get_user_history') else []
    if not history:
        return 0
    if kp:
        kp_history = [e for e in history if _kp_history_match(e.get("knowledge_point", ""), kp)]
        if not kp_history:
            return 0
    else:
        kp_history = history

    count = 0
    for entry in reversed(kp_history):
        if entry.get("correct") is False:
            count += 1
        else:
            break
    return count


def _remap_dead_escalate(decision: InterventionDecision) -> InterventionDecision:
    """定时培养没有 Claude escalate 通道：改为基础讲解+小题。"""
    if decision.type != "escalate":
        return decision
    kp = decision.reason.split(":")[0].strip() if ":" in decision.reason else decision.reason
    return InterventionDecision(
        "explain",
        "basic",
        f"{kp}: 连续受挫，改为基础讲解并配 1 道小题巩固",
        decision.priority,
    )


def _get_last_error_text(bkt_log: BKTLogger, kp: str = "") -> str:
    """从 answer-log 取最近一条答错记录，拼成 review 用的摘要。"""
    history = bkt_log.get_user_history(_uid()) if hasattr(bkt_log, "get_user_history") else []
    if not history:
        return ""
    for entry in reversed(history):
        if entry.get("correct") is not False:
            continue
        entry_kp = entry.get("knowledge_point", "")
        if kp and entry_kp and entry_kp != kp:
            continue
        parts = [f"知识点：{entry_kp or kp or '未知'}", "结果：上次答错，需巩固"]
        try:
            from learner.db import get_store
            lp = get_store().get_latest_push(_uid() or None)
            q = (lp.get("question") or "").strip() if lp else ""
            if q:
                parts.insert(1, f"题目摘要：{q[:300]}")
        except Exception:
            pass
        return "；".join(parts)
    return ""


def _dynamic_style_pcts(consecutive_failures: int, subject: str) -> tuple[int, int]:
    """连续答错越多越偏向真题套路；分科基线+斜率（BIG-TEACH-012c #11）。"""
    style_table = {
        "math": {"base_exam": 70, "per_fail": 8, "floor": 60, "ceil": 90},
        "comm": {"base_exam": 55, "per_fail": 5, "floor": 50, "ceil": 85},
    }
    cfg = style_table.get(subject, {"base_exam": 60, "per_fail": 8, "floor": 60, "ceil": 80})
    exam_pct = max(cfg["floor"], min(cfg["ceil"], cfg["base_exam"] + consecutive_failures * cfg["per_fail"]))
    return exam_pct, 100 - exam_pct


def _pick_kp_from_weights(weights: dict, subject: str, bkt_log: BKTLogger) -> str | None:
    """按 weight×(1-mastery) 加权随机选题；同 L1 近 3 次不重复同一 L2。"""
    if subject not in weights:
        return None
    kp_w = weights[subject].get("kp_weights") or {}
    if not kp_w:
        return None
    mastery: dict[str, float] = {}
    try:
        if hasattr(bkt_log, "get_all_kp_mastery"):
            mastery = bkt_log.get_all_kp_mastery(_uid()) or {}
        for kp in kp_w:
            if kp in mastery:
                continue
            if hasattr(bkt_log, "get_kp_mastery"):
                kc = bkt_log.get_kp_mastery(_uid(), kp)
                if kc and hasattr(kc, "p_effective"):
                    mastery[kp] = kc.p_effective
    except Exception:
        pass
    from learner.kp_registry import pick_kp_weighted
    due_kps = set()
    try:
        if hasattr(bkt_log, "get_due_kps"):
            due_kps = bkt_log.get_due_kps(_uid()) or set()
    except Exception:
        due_kps = set()
    return pick_kp_weighted(subject, kp_w, mastery, due_kps=due_kps)


def decide(subject: str, bkt_log: BKTLogger) -> InterventionDecision:
    """基于 weights.json + BKT + 规则决定干预方案。

    选题优先级：
    1. weight×(1-mastery) 加权随机（同 L1 近 3 次降权重复；到期提权）
    2. 无 weights → 回退 BKT 最低掌握度
    """
    from learner.kp_registry import (
        pick_l3, syllabus_subject, resolve_kp, list_l3_for_l2,
    )
    weights = _load_weights()
    target_kp = None
    target_val = 0.0  # mastery for the selected KP
    kc = None
    # review 与 math 共用考纲/weights（与 rag_retrieve 一致）
    weight_subj = syllabus_subject(subject)

    # ── 优先从 weights 选题（含 review→math）──
    if weight_subj in ("math", "comm") and weight_subj in weights:
        kp_from_w = _pick_kp_from_weights(weights, weight_subj, bkt_log)
        if kp_from_w:
            target_kp = kp_from_w
            kc = bkt_log.get_kp_mastery(_uid(), kp_from_w) \
                if hasattr(bkt_log, 'get_kp_mastery') else None
            if kc and hasattr(kc, 'p_effective'):
                target_val = kc.p_effective
            else:
                target_val = 0.2  # 新知识点默认初始掌握度

    # ── 回退：BKT 全局最低掌握度（需 resolve 到正式 L2）──
    if target_kp is None:
        mastery = bkt_log.get_all_kp_mastery(_uid()) \
            if hasattr(bkt_log, 'get_all_kp_mastery') else {}
        if mastery:
            raw_kp = min(mastery, key=mastery.get)
            kp_w = (weights.get(weight_subj) or {}).get("kp_weights")
            resolved = resolve_kp(weight_subj, raw_kp, kp_w)
            target_kp = resolved or raw_kp
            target_val = mastery[raw_kp]

    if target_kp:
        # 确保 target_kp 是考纲 L2（BKT 脏键 / 别名 → 正式名）
        kp_w = (weights.get(weight_subj) or {}).get("kp_weights")
        resolved_l2 = resolve_kp(weight_subj, target_kp, kp_w)
        if resolved_l2:
            target_kp = resolved_l2

        days_since_last_push = _get_days_since_last_push(subject)
        consecutive_failures = _get_consecutive_failures(_uid(), bkt_log, target_kp)
        opportunity_count = 0
        if kc is None:
            kc = bkt_log.get_kp_mastery(_uid(), target_kp) \
                if hasattr(bkt_log, 'get_kp_mastery') else None
        if kc and hasattr(kc, 'opportunity_count'):
            opportunity_count = kc.opportunity_count
        is_mastered = bool(getattr(kc, "is_mastered", False)) if kc else False
        is_due = bool(kc.is_due()) if kc and hasattr(kc, "is_due") else False
        recent_correct = None
        if hasattr(bkt_log, "get_recent_correct"):
            try:
                recent_correct = bkt_log.get_recent_correct(_uid(), target_kp)
            except Exception:
                recent_correct = None

        decision = decide_intervention(
            kp_name=target_kp,
            mastery=target_val,
            opportunity_count=opportunity_count,
            is_mastered=is_mastered,
            recent_correct=recent_correct,
            days_since_last_push=days_since_last_push,
            consecutive_failures=consecutive_failures,
            is_due=is_due,
        )
        decision = _remap_dead_escalate(decision)
        # ── L3 选取 (BIG-TEACH-011c) ──
        if decision.type != "defer" and target_kp:
            l3_id = pick_l3(weight_subj, target_kp)
            if not l3_id and not list_l3_for_l2(weight_subj, target_kp):
                # 仍非考纲 L2：再从 weights 抽一个有 L3 的 L2
                kp_alt = _pick_kp_from_weights(weights, weight_subj, bkt_log) \
                    if weight_subj in weights else None
                if kp_alt and list_l3_for_l2(weight_subj, kp_alt):
                    target_kp = kp_alt
                    l3_id = pick_l3(weight_subj, target_kp)
            if l3_id:
                decision.reason = f"{decision.reason} [l3={l3_id}]"
            else:
                decision = InterventionDecision(
                    "defer", decision.difficulty,
                    f"{target_kp}: 无 L3 子知识点，跳过", 5,
                )
    else:
        decision = InterventionDecision("push", "intermediate", "无薄弱点，出综合题", 3)

    # ── ability_goal 选取 (BIG-TEACH-011d)；轮换记账延后到成功 _save_last_push ──
    if decision.type != "defer":
        from learner.ability_cycle import decide_ability, encode_ability_reason
        ability_goal = decide_ability(
            subject, decision.type,
            is_mastered=is_mastered if target_kp else True,
            opportunity_count=opportunity_count if target_kp else 0,
            recent_correct=recent_correct if target_kp else None,
            consecutive_failures=consecutive_failures if target_kp else 0,
            is_due=is_due if target_kp else False,
            mastery=target_val if target_kp else 0.0,
        )
        decision.ability_goal = ability_goal
        decision.reason = f"{decision.reason} {encode_ability_reason(ability_goal)}"

    pref = get_difficulty_pref(subject)
    if pref:
        decision.difficulty = pref
    return decision


# ═══════════════════════════════════════════
# 3. GENERATE — 两阶段 LLM（出题验算 → 发送文案）
# ═══════════════════════════════════════════

TOPIC_MAP = {
    "math":   "数学一考研（教育部考试大纲；题型与难度对齐近年真题，教材体系同济高数/线代、浙大概率）",
    "comm":   "北邮801通信原理（周炯槃教材第4版 Ch2–11，严格考纲范围）",
    "review": "错题巩固（数学一+通信原理）",
}

def _answer_looks_contaminated(answer: str) -> bool:
    from quality_gate import looks_contaminated

    return looks_contaminated(answer)


def _author_once(
    builder: PromptBuilder,
    *,
    subject_cn: str,
    kp: str,
    diff: str,
    action: str,
    decision: InterventionDecision,
    tpl_type: str,
    topic_desc: str,
    mastery: float,
    opportunity_count: int,
    consecutive_failures: int,
    ref_entry,
    rag_items: list,
    exam_pct: int,
    theory_pct: int,
    last_error: str,
    item_form: str = "mcq",
) -> tuple[str, str]:
    """阶段1：出题+验算。返回 (draft_body, answer)。"""
    system, user = builder.build(
        subject_cn=subject_cn,
        kp=kp,
        difficulty_cn=diff,
        action_cn=action,
        reason=decision.reason,
        decision_type=tpl_type,
        topic_desc=topic_desc,
        mastery=mastery,
        opportunity_count=opportunity_count,
        consecutive_failures=consecutive_failures,
        ref_entry=ref_entry,
        rag_items=rag_items,
        exam_style_pct=exam_pct,
        theory_extension_pct=theory_pct,
        last_error=last_error,
        item_form=item_form,
    )
    raw = call_llm(system, user, "author", decision.difficulty)
    from math_format import split_question_answer, sanitize_answer_meta
    draft, answer = split_question_answer(raw)
    answer = sanitize_answer_meta(answer)
    return draft, answer


def _polish_once(builder: PromptBuilder, draft: str, answer: str, difficulty: str) -> str:
    """阶段2：整理发送文案（不含答案）。"""
    system, user = builder.build_polish(draft_body=draft, answer_body=answer)
    polished = call_llm(system, user, "polish", difficulty)
    # 防模型把 <answer> 又带出来
    from math_format import split_question_answer, normalize_markdown_body
    body, leaked = split_question_answer(polished)
    if leaked:
        print("[cultivate] polish leaked answer — stripped")
    return normalize_markdown_body(body) or normalize_markdown_body(draft)


def generate(subject: str, decision: InterventionDecision, *,
             mastery: float = 0.0, opportunity_count: int = 0,
             consecutive_failures: int = 0,
             source: str = "schedule",
             exam_allow_low_rag: bool = False) -> str:
    """出题契约 → 编排质检/文案 → 可发送正文（Phase C）。"""
    topic_desc = TOPIC_MAP.get(subject, subject)
    difficulty_map = {"basic": "基础", "intermediate": "中等", "challenge": "挑战"}
    diff = difficulty_map.get(decision.difficulty, "中等")
    intervention_map = {"push": "出题", "explain": "讲解概念", "review": "复诊错题", "defer": "", "escalate": ""}
    action = intervention_map.get(decision.type, "出题")

    if decision.type == "defer":
        return ""

    tpl_type = decision.type if decision.type in ("push", "explain", "review") else "explain"
    kp = decision.reason.split(":")[0] if ":" in decision.reason else decision.reason
    subject_map = {"math": "数学一", "comm": "通信原理", "review": "数学一（错题复盘）"}
    subject_cn = subject_map.get(subject, subject)

    # ── RefPicker：选 YAML 锚点 ──
    global _last_ref_source
    _last_ref_source = ""
    ref_entry = None
    try:
        picker = RefPicker(subject)
        ref_entry = picker.pick(kp=kp, difficulty=decision.difficulty)
        if ref_entry:
            src = ref_entry.get("source", {})
            if isinstance(src, dict):
                _last_ref_source = f"{src.get('year', '')}年{src.get('subject', '')}"
            else:
                _last_ref_source = str(src)
    except Exception:
        pass

    # ── L3 硬闸 (BIG-TEACH-011c) ──
    from learner.kp_registry import parse_l3_from_reason, is_valid_l3_id, pick_l3, syllabus_subject
    l3_subj = syllabus_subject(subject)
    l3_id = parse_l3_from_reason(decision.reason)
    if l3_id and not is_valid_l3_id(l3_subj, l3_id):
        print(f"[cultivate] l3_id '{l3_id}' not in syllabus — treated as miss")
        l3_id = None

    # ── RAG 硬契约（011-rag）：唯一入口 rag_retrieve；禁止直调 query_rag ──
    rag_items: list[dict] = []
    try:
        from learner.rag_retrieve import rag_retrieve, rag_strict_enabled
        global _rag_strict_blocked
        _rag_strict_blocked = False

        if not l3_id:
            print(f"[cultivate] no valid l3_id — L2='{kp}' blocked (need L3)")
            if rag_strict_enabled():
                _rag_strict_blocked = True
                return ""
            unit_id = kp  # RAG_STRICT=0 兼容旧路径
        else:
            unit_id = l3_id

        rag = rag_retrieve(subject, unit_id, top_k=4, N=2)
        print(
            f"[cultivate] rag_retrieve ok={rag.ok} hit={rag.hit_count} "
            f"backend={rag.backend} reason={rag.reason} unit={unit_id}"
        )
        if rag_strict_enabled() and not rag.ok and not exam_allow_low_rag:
            # 换 L3 重试：同 L2 再试 1 个其他 L3
            if l3_id:
                retry_l3 = pick_l3(l3_subj, kp, recent_l3=[l3_id])
                if retry_l3 and retry_l3 != l3_id:
                    print(f"[cultivate] retry alternate L3: {retry_l3}")
                    unit_id = retry_l3
                    rag = rag_retrieve(subject, unit_id, top_k=4, N=2)
                    print(
                        f"[cultivate] rag_retrieve (retry) ok={rag.ok} hit={rag.hit_count} "
                        f"backend={rag.backend} reason={rag.reason} unit={unit_id}"
                    )
            if rag_strict_enabled() and not rag.ok:
                print(f"[cultivate] RAG_STRICT: abort author ({rag.reason})")
                _rag_strict_blocked = True
                return ""
        rag_items = rag.to_prompt_items()
    except Exception as e:
        print(f"[cultivate] rag_retrieve failed: {e}")
        from learner.rag_retrieve import rag_strict_enabled

        if rag_strict_enabled() and not exam_allow_low_rag:
                _rag_strict_blocked = True
                return ""

    exam_pct, theory_pct = _dynamic_style_pcts(consecutive_failures, subject)

    last_error = ""
    if subject == "review" or decision.type == "review":
        try:
            from learner.bkt_db import DbBKTLogger
            log = DbBKTLogger()
            last_error = _get_last_error_text(log, kp)
        except Exception:
            pass

    builder = PromptBuilder()

    # ── ability_goal → item_form (BIG-TEACH-011d)；transfer 继承上次 form ──
    # 双周卷可在 reason 写 [item_form=blank|proof_outline] 强制大题
    from learner.ability_cycle import (
        ability_to_item_form,
        parse_ability_from_reason,
        parse_item_form_from_reason,
        _load_last_push_item_form,
    )
    ability_goal = getattr(decision, 'ability_goal', '') or parse_ability_from_reason(decision.reason) or ''
    global _last_item_form
    forced_form = parse_item_form_from_reason(decision.reason)
    if forced_form:
        _last_item_form = forced_form
    else:
        last_form = _load_last_push_item_form() if ability_goal == "transfer" else ""
        _last_item_form = (
            ability_to_item_form(ability_goal, last_form=last_form or None, subject=subject)
            if ability_goal else "mcq"
        )

    author_kwargs = dict(
        subject_cn=subject_cn,
        kp=kp,
        diff=diff,
        action=action,
        decision=decision,
        tpl_type=tpl_type,
        topic_desc=topic_desc,
        mastery=mastery,
        opportunity_count=opportunity_count,
        consecutive_failures=consecutive_failures,
        ref_entry=ref_entry,
        rag_items=rag_items,
        exam_pct=exam_pct,
        theory_pct=theory_pct,
        last_error=last_error,
        item_form=_last_item_form,
    )

    global _last_answer
    _last_answer = ""

    # ── 出题 LLM（短契约）──
    print(f"[cultivate] author ({tpl_type}/{decision.difficulty})")
    draft, answer = _author_once(builder, **author_kwargs)
    if not draft:
        print("[cultivate] author produced empty draft")
        return ""

    ref_id = ""
    if isinstance(ref_entry, dict):
        ref_id = str(ref_entry.get("id") or "")

    def _reauthor():
        d, a = _author_once(builder, **author_kwargs)
        return {"draft": d, "answer": a, "kp": kp, "ref_id": ref_id}

    # ── 编排：质检 + 文案（含 memory digest）──
    from orchestrate import orchestrate_push

    result = orchestrate_push(
        {
            "draft": draft,
            "answer": answer,
            "kp": kp,
            "ref_id": ref_id,
            "decision_type": tpl_type,
            "item_form": _last_item_form,
        },
        subject=subject,
        difficulty=decision.difficulty,
        source=source,
        max_author_retries=2,
        reauthor_fn=_reauthor,
    )
    _last_answer = result.get("answer") or answer
    if result.get("status") != "accept":
        print(f"[cultivate] orchestrate reject: {result.get('reason')}")
        return ""
    return (result.get("content") or "").strip()


# ═══════════════════════════════════════════
# 4. DELIVER — 推送
# ═══════════════════════════════════════════

def deliver(content: str) -> bool:
    """通过可用推送桥发送。"""
    if not content:
        return False
    from math_format import format_for_dingtalk
    content = format_for_dingtalk(content)
    bridge = get_bridge()
    ok = bridge.send(content)
    if not ok:
        print(content)  # fallback: print to stdout
    return ok


# ═══════════════════════════════════════════
# 5. RECORD — 记录到每日题目文件
# ═══════════════════════════════════════════

def record(subject: str, content: str, decision: InterventionDecision, answer: str = "",
           ref_source: str = ""):
    """先落库：同一事务写 items+pushes；MD 导出/同步队列为附属。

    SQLite 写入失败必须向上抛出（禁止静默成功）。导出失败不回滚已成功的 DB 事务。
    """
    if not content:
        return
    from learner.db import get_store, shanghai_hhmm
    from learner.context import get_binding, current_user_id
    from learner.kp_registry import parse_l3_from_reason

    kp = decision.reason.split(":")[0] if ":" in decision.reason else decision.reason
    kp = kp.split("[")[0].strip()
    l3_id = parse_l3_from_reason(getattr(decision, "reason", "") or "")
    sid = ""
    try:
        sid = current_user_id() or ""
    except Exception:
        sid = ""
    is_public = get_binding() == "schedule"
    learner_id = None if is_public else (sid or None)

    store = get_store()
    push_id = store.record_push(
        subject=subject,
        question=content,
        answer=answer,
        difficulty=getattr(decision, "difficulty", ""),
        kp=kp,
        l3_id=l3_id or "",
        item_form=_last_item_form,
        ability_goal=getattr(decision, "ability_goal", "") or "",
        ref_source=ref_source or _last_ref_source,
        decision_type=getattr(decision, "type", ""),
        reason=getattr(decision, "reason", ""),
        learner_id=learner_id,
    )
    push = store.get_push(push_id) or {}
    day = push.get("day") or datetime.date.today().isoformat()
    num = push.get("seq") or 1
    now = shanghai_hhmm(push.get("pushed_at") or "") or datetime.datetime.now().strftime("%H:%M")

    try:
        from scripts.export_daily_md import export_month
        export_month(day[:7], out_dir=DAILY_RECORD_DIR)
    except Exception as e:
        print(f"[cultivate] MD export failed (DB ok): {e}")

    try:
        block = _build_md_block(day, now, num, subject, decision, content, answer, ref_source)
        SYNC_QUEUE_DIR = os.path.join(DATA_DIR, "sync-queue")
        os.makedirs(SYNC_QUEUE_DIR, exist_ok=True)
        qpath = os.path.join(SYNC_QUEUE_DIR, f"{day}-{num:03d}.md")
        with open(qpath, "w", encoding="utf-8") as f:
            f.write("\n" + block.lstrip("\n").rstrip() + "\n\n")
    except Exception as e:
        print(f"[cultivate] sync-queue export failed (DB ok): {e}")



def _build_md_block(day: str, now: str, num: int, subject: str,
                    decision: InterventionDecision, content: str,
                    answer: str, ref_source: str) -> str:
    block = (
        f"## {day} {now} #{num}\n"
        f"### 题目\n"
        f"**{subject} · {decision.difficulty}**\n\n"
        f"{content}\n\n"
    )
    if answer:
        block += f"### 解答\n{answer}\n\n"
    block += (
        f"### 出题逻辑\n"
        f"- 决策类型：{decision.type}\n"
        f"- 决策原因：{decision.reason}\n"
    )
    if ref_source:
        block += f"- 参考来源：{ref_source}\n"
    block += "---\n"
    return block


# ═══════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════

def cultivate(subject: str):
    """一次完整的培养循环。"""
    if not _bkt_available:
        print(f"[cultivate] bkt unavailable, cannot cultivate ({subject})")
        return
    with bind_owner_schedule():
        _cultivate_inner(subject)


def _cultivate_inner(subject: str):
    """推送：优先从 ready 题库抽取；默认不做 live author。"""
    global _last_answer, _last_ref_source, _last_item_form
    state = assess_state(subject)
    bkt_log = state["bkt_log"]
    decision = decide(subject, bkt_log)
    if decision.type == "defer":
        print(f"[cultivate] {subject}: 跳过（{decision.reason}）")
        return

    kp = decision.reason.split(":")[0] if ":" in decision.reason else decision.reason
    kp = kp.split("[")[0].strip()

    from learner.item_bank import pick_for_push, live_fallback_enabled, pick_technique_for_kp
    from learner.db import get_store

    tech = pick_technique_for_kp(kp)
    try:
        sid = _uid()
    except Exception:
        sid = ""
    item = pick_for_push(subject, kp=kp, technique=tech, learner_id=sid or None)
    if not item:
        if not live_fallback_enabled():
            print(
                f"[cultivate] {subject}: ready 题库为空/无匹配 "
                f"(kp={kp} tech={tech or '-'})，跳过（BANK_LIVE_FALLBACK=0）"
            )
            try:
                from pathlib import Path
                from config import DATA_DIR
                qdir = Path(DATA_DIR) / "problem_queue"
                qdir.mkdir(parents=True, exist_ok=True)
                (qdir / f"bank_empty_{subject}.md").write_text(
                    f"# bank empty\nsubject={subject}\nkp={kp}\ntech={tech}\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
            return
        # 旧路径 live author（仅 flag 打开）
        content = generate(subject, decision, source="schedule")
        if not content:
            print(f"[cultivate] {subject}: live fallback 也失败")
            return
        answer = _last_answer
        ref_source = _last_ref_source
        try:
            record(subject, content, decision, answer, ref_source)
        except Exception as e:
            print(f"[cultivate] {subject}: record failed: {e}")
            return
        _save_last_push(
            subject, decision, content, answer, ref_source, kp=kp, source="schedule"
        )
        if deliver(content):
            print(f"[cultivate] {subject}: OK live / {kp}")
        return

    # bank pick → push only
    store = get_store()
    is_public = True  # schedule binding
    try:
        from learner.context import get_binding
        is_public = get_binding() == "schedule"
    except Exception:
        pass
    learner_id = None if is_public else (sid or None)
    try:
        push_id = store.record_push_for_item(
            item_id=int(item["id"]),
            learner_id=learner_id,
            slot=subject,
            decision_type=decision.type,
            reason=decision.reason,
        )
    except Exception as e:
        print(f"[cultivate] {subject}: record_push_for_item failed: {e}")
        return

    content = item.get("question") or ""
    answer = item.get("answer") or ""
    ref_source = item.get("ref_source") or ""
    _last_answer = answer
    _last_ref_source = ref_source
    _last_item_form = item.get("item_form") or ""

    try:
        _save_last_push(
            subject, decision, content, answer, ref_source, kp=kp, source="schedule"
        )
    except Exception as e:
        print(f"[cultivate] {subject}: last_push mirror failed: {e}")

    # MD export (best-effort)
    try:
        from scripts.export_daily_md import export_month
        from learner.db import shanghai_day
        export_month(shanghai_day(None)[:7], out_dir=DAILY_RECORD_DIR)
    except Exception:
        pass

    if deliver(content):
        print(
            f"[cultivate] {subject}: OK bank#{item['id']} push={push_id} / "
            f"{decision.difficulty} / {kp}"
        )
    else:
        print(
            f"[cultivate] {subject}: deliver failed after bank push "
            f"(item={item['id']} push={push_id})"
        )


if __name__ == "__main__":
    subject = sys.argv[1] if len(sys.argv) > 1 else "math"
    cultivate(subject)
