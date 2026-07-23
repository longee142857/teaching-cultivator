"""weights.json 知识点权重读写。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from config import DATA_DIR
from learner.kp_registry import resolve_kp as registry_resolve_kp

WEIGHTS_PATH = os.path.join(DATA_DIR, "weights.json")
REFINE_QUEUE = os.path.join(DATA_DIR, "refine-queue.jsonl")
# 细粒度权重量级约 0.01–0.07（math）或 ~1.0（comm 相对）
BUMP_DELTA = 0.015
BUMP_CAP_ABS = 0.12
BUMP_CAP_REL = 2.0  # 相对权重上限：不超过旧值×2，且不超过 old+0.25


def load_weights() -> dict:
    try:
        if os.path.isfile(WEIGHTS_PATH):
            with open(WEIGHTS_PATH, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_weights(weights: dict) -> bool:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
            json.dump(weights, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return True
    except OSError:
        return False


def resolve_kp(subject: str, kp_hint: str) -> str | None:
    """在 syllabus aliases + legacy + kp_weights 中解析知识点名。"""
    weights = load_weights()
    kp_w = (weights.get(subject) or {}).get("kp_weights") or {}
    return registry_resolve_kp(subject, kp_hint, kp_w)


def _bump_cap(old: float) -> float:
    """math 归一化权重用绝对上限；comm 相对权重大时用相对上限。"""
    if old >= 0.5:
        return min(old * BUMP_CAP_REL, old + 0.25)
    return BUMP_CAP_ABS


def bump_kp_weight(subject: str, kp_hint: str, *, reason: str = "") -> dict:
    """提高某知识点出题权重，并写 refine-queue 信号。返回操作详情 dict。"""
    weights = load_weights()
    if subject not in weights:
        return {"ok": False, "error": f"科目 {subject} 不在 weights.json"}
    kp_w = weights[subject].get("kp_weights") or {}
    kp_key = resolve_kp(subject, kp_hint)
    if not kp_key or kp_key not in kp_w:
        available = list(kp_w.keys())
        return {
            "ok": False,
            "error": f"未匹配知识点「{kp_hint}」",
            "available_kps": available[:12],
        }
    old = float(kp_w[kp_key])
    new = round(min(_bump_cap(old), old + BUMP_DELTA), 4)
    # 相对权重（comm）bump 幅度可略大
    if old >= 0.5:
        new = round(min(_bump_cap(old), old + 0.08), 3)
    kp_w[kp_key] = new
    if not save_weights(weights):
        return {"ok": False, "error": "写入 weights.json 失败"}

    _append_refine_signal(subject, kp_key, reason, old, new)

    bkt_msg = ""
    try:
        from bkt import BKTLogger, KCState
        bkt = BKTLogger(os.path.join(DATA_DIR, "answer-log.jsonl"))
        kc = bkt.get_kp_mastery("wx_123", kp_key)
        if kc is None:
            kc = KCState(p_mastery=0.25)
        else:
            kc = KCState.from_dict(kc.to_dict())
        before = kc.p_mastery
        meta = bkt.record(
            "wx_123",
            kp_key,
            False,
            kc,
            conv_tag="self_report_weak",
            item_type="unknown",
        )
        if meta.get("applied"):
            bkt_msg = f"BKT {kp_key} 掌握度 {before*100:.0f}%→{kc.p_mastery*100:.0f}%"
        else:
            bkt_msg = f"BKT {kp_key} 未更新（{meta.get('reason')}），当前 {before*100:.0f}%"
    except Exception as e:
        bkt_msg = f"BKT 更新跳过：{e}"

    return {
        "ok": True,
        "subject": subject,
        "kp": kp_key,
        "weight_before": old,
        "weight_after": new,
        "bkt": bkt_msg,
        "reason": reason or "用户自述薄弱",
    }


def _append_refine_signal(subject: str, kp: str, reason: str, old: float, new: float) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "weak_self_report",
            "subject": subject,
            "kp": kp,
            "reason": reason,
            "weight_before": old,
            "weight_after": new,
        }
        with open(REFINE_QUEUE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def format_bump_result(result: dict) -> str:
    """给 Agent 第二轮 LLM 看的工具返回文本。"""
    if not result.get("ok"):
        err = result.get("error", "未知错误")
        avail = result.get("available_kps")
        if avail:
            return f"失败：{err}\n可选知识点：{', '.join(avail)}"
        return f"失败：{err}"
    return (
        f"已记录薄弱点：{result['kp']}（{result['subject']}）\n"
        f"出题权重：{result['weight_before']:.3f} → {result['weight_after']:.3f}\n"
        f"{result.get('bkt', '')}\n"
        f"原因：{result.get('reason', '')}\n"
        f"后续定时推送会优先覆盖该知识点。"
    )
