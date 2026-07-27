"""学习者快照 — 供 Agent 每轮可见的只读指标摘要。

聚合 weights.json、BKT answer-log、difficulty 偏好、最近推送。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from config import DATA_DIR, LEARNER_USER_ID
from learner.kp_registry import get_l1, get_l1_name, load_syllabus

WEIGHTS_PATH = os.path.join(DATA_DIR, "weights.json")
DIFFICULTY_PATH = os.path.join(DATA_DIR, "difficulty.json")
ANSWER_LOG = os.path.join(DATA_DIR, "answer-log.jsonl")
LAST_PUSH_PATH = os.path.join(DATA_DIR, "last_push.json")
USER_ID = LEARNER_USER_ID

_SUBJECT_CN = {"math": "数学一", "comm": "通信原理", "review": "错题复盘"}


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
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows: list[dict] = []
    try:
        if not os.path.isfile(ANSWER_LOG):
            return rows
        with open(ANSWER_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("user_id") not in (USER_ID, None, ""):
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
        from bkt import BKTLogger
        bkt = BKTLogger(ANSWER_LOG)
        return bkt.get_all_kp_mastery(USER_ID) or {}
    except Exception:
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
    # L1 汇总：按该 L1 下最低掌握度 / 平均权重粗看薄弱
    l1_summaries = []
    for l1_id in l1_order:
        items = by_l1.get(l1_id) or []
        if not items:
            continue
        ms = [mastery[k] for k, _ in items if k in mastery]
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
    weights = _load_json(WEIGHTS_PATH)
    difficulty = _load_json(DIFFICULTY_PATH)
    mastery = _bkt_mastery_map()
    recent = _load_answer_log(days)
    last_push = _load_json(LAST_PUSH_PATH)

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
        weak = sorted(mastery.items(), key=lambda x: x[1])[:5]
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
    return "\n".join(lines)
