"""学习者快照 — 供 Agent 每轮可见的只读指标摘要。

聚合 weights.json、BKT answer-log、difficulty 偏好、最近推送。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from learner.context import current_user_id
from learner import paths as P
from learner.kp_registry import get_l1, get_l1_name, load_syllabus

_SUBJECT_CN = {"math": "数学一", "comm": "通信原理", "review": "错题复盘"}


def _user_id() -> str:
    return current_user_id()


def _load_json(path: str) -> dict:
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _load_answer_log(days: int = 7) -> list[dict]:
    uid = _user_id()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows: list[dict] = []
    log_path = P.answer_log_path()
    try:
        if not os.path.isfile(log_path):
            return rows
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("user_id") not in (uid, None, ""):
                    continue
                # 跳过测试污染（未分类/被隔离条目），避免污染快照统计
                if e.get("knowledge_point") == "未分类" or e.get("quarantined"):
                    continue
                ts = e.get("ts", "")
                if ts:
                    try:
                        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if t < cutoff:
                            continue
                    except ValueError:
                        pass
                rows.append(e)
    except OSError:
        pass
    return rows


def _bkt_mastery_map() -> dict[str, float]:
    try:
        from learner.bkt_db import DbBKTLogger
        from learner.db import get_store

        return DbBKTLogger(get_store()).get_all_kp_mastery(_user_id()) or {}
    except Exception:
        return {}


def _last_push_meta() -> dict:
    try:
        from learner.db import get_store

        rec = get_store().get_latest_push(_user_id() or None)
        if rec and rec.get("question"):
            return rec
    except Exception:
        pass
    for path in (P.last_push_path(), P.public_last_class_path()):
        data = _load_json(path)
        if data.get("question"):
            return data
    return {}


def _format_subject_by_l1(
    subject: str, kp_w: dict, mastery: dict[str, float]
) -> list[str]:
    """按 L1 分组各显示 TOP3。"""
    syl = load_syllabus(subject)
    l1_order = list((syl.get("l1") or {}).keys())
    by_l1: dict[str, list[tuple[str, float]]] = {}
    for kp, w in kp_w.items():
        l1 = get_l1(subject, kp) or "_other"
        by_l1.setdefault(l1, []).append((kp, float(w)))

    lines: list[str] = []
    l1_summaries = []
    for l1_id in l1_order:
        items = by_l1.get(l1_id) or []
        if not items:
            continue
        ms = [mastery[k] for k, _ in items if mastery.get(k) is not None]
        weak = f"最低掌握{min(ms)*100:.0f}%" if ms else "掌握?"
        l1_summaries.append(f"{get_l1_name(subject, l1_id)}({weak})")
    if l1_summaries:
        lines.append(
            f"- {_SUBJECT_CN.get(subject, subject)} L1：{' / '.join(l1_summaries)}"
        )

    for l1_id in l1_order:
        items = by_l1.get(l1_id) or []
        if not items:
            continue
        ranked = sorted(items, key=lambda x: -x[1])[:3]
        parts = []
        for kp, w in ranked:
            m = mastery.get(kp)
            m_s = f"掌握{m*100:.0f}%" if m is not None else "掌握?"
            parts.append(f"{kp} 权重{w:.3g}/{m_s}")
        l1_name = get_l1_name(subject, l1_id)
        lines.append(
            f"- {_SUBJECT_CN.get(subject, subject)}·{l1_name} TOP："
            f"{'；'.join(parts)}"
        )
    return lines


def build_learner_snapshot(days: int = 7) -> str:
    """生成注入 Agent system 的 Markdown 快照（尽量控制在 ~1.5k 字符）。"""
    weights = _load_json(P.weights_path())
    difficulty = _load_json(P.difficulty_path())
    mastery = _bkt_mastery_map()
    recent = _load_answer_log(days)
    last_push = _last_push_meta()

    lines = ["## 学习者快照（只读，每轮自动更新）"]

    if difficulty:
        prefs = ", ".join(
            f"{_SUBJECT_CN.get(k, k)}={v}" for k, v in sorted(difficulty.items())
        )
        lines.append(f"- 难度偏好：{prefs}")
    else:
        lines.append("- 难度偏好：（未设置，按 BKT 推荐）")

    for subject in ("math", "comm"):
        if subject not in weights:
            continue
        kp_w = weights[subject].get("kp_weights") or {}
        if not kp_w:
            continue
        lines.extend(_format_subject_by_l1(subject, kp_w, mastery))

    if mastery:
        valid = {k: v for k, v in mastery.items() if v is not None}
        weak = sorted(valid.items(), key=lambda x: x[1])[:5]
        weak_s = "；".join(f"{kp} {v*100:.0f}%" for kp, v in weak)
        lines.append(f"- BKT 薄弱知识点：{weak_s}")

    if recent:
        correct = sum(1 for e in recent if e.get("correct") is True)
        lines.append(f"- 近{days}天答题：{len(recent)} 次，正确 {correct} 次")
    else:
        lines.append(f"- 近{days}天答题：无记录")

    if last_push.get("question"):
        subj = last_push.get("subject", "?")
        diff = last_push.get("difficulty", "?")
        ts = (last_push.get("timestamp") or "")[:16]
        kp = last_push.get("kp") or ""
        q_preview = (last_push.get("question") or "")[:80].replace("\n", " ")
        kp_s = f"/{kp}" if kp else ""
        lines.append(
            f"- 上次推送：{_SUBJECT_CN.get(subj, subj)}{kp_s}/{diff} @ {ts} …{q_preview}"
        )

    lines.append(
        "- 说明：用户自述薄弱点请用 note_weak_point；嫌太难/太简单才用 adjust_difficulty"
    )

    # 结构化能力信号（供云端 agent 解析；markdown 之外附 JSON 块）
    try:
        from learner.db import get_store
        from learner.context import current_user_id

        sig = get_store().recent_ability_signals(current_user_id(), limit=15)
        if any(sig.values()):
            lines.append("- 技巧失误 Top：" + (
                "；".join(
                    f"{x['technique']}×{x['n']}" for x in (sig.get("technique_fail_top") or [])[:5]
                ) or "无"
            ))
            fails = sig.get("cdp_fail_recent") or []
            if fails:
                lines.append(
                    "- 近期 CDP 失败："
                    + "；".join(
                        f"{f.get('id')}({f.get('technique') or '-'})" for f in fails[:5]
                    )
                )
            import json as _json
            lines.append("")
            lines.append("```ability_json")
            lines.append(_json.dumps(sig, ensure_ascii=False))
            lines.append("```")
    except Exception:
        pass

    return "\n".join(lines)
