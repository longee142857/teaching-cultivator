"""weights.json 知识点权重读写。"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Optional

from config import DATA_DIR
from learner.kp_registry import resolve_kp as registry_resolve_kp
from learner.context import current_user_id
from learner import paths as P

# 兼容旧测试 patch 的模块级名（动态解析优先走函数）
WEIGHTS_PATH = os.path.join(DATA_DIR, "weights.json")
REFINE_QUEUE = os.path.join(DATA_DIR, "refine-queue.jsonl")
REFINE_QUEUE_ARCHIVE_DIR = os.path.join(DATA_DIR, "refine-queue-archive")
# 细粒度权重量级约 0.01–0.07（math）或 ~1.0（comm 相对）
BUMP_DELTA = 0.015
BUMP_CAP_ABS = 0.12
BUMP_CAP_REL = 2.0  # 相对权重上限：不超过旧值×2，且不超过 old+0.25

# ── 权重衰减（BIG-TEACH-012b #1）──
DECAY_DELTA = 0.01   # math 归一化权重衰减步长（略小于 bump 0.015）
DECAY_DELTA_COMM = 0.05  # comm 相对权重大时衰减步长（略小于 bump 0.08）

# ── Refine-queue 归档阈值（BIG-TEACH-012d #17）──
REFINE_QUEUE_MAX_ENTRIES = 500
REFINE_QUEUE_MAX_AGE_DAYS = 30


def _weights_path() -> str:
    try:
        return P.weights_path()
    except Exception:
        return WEIGHTS_PATH


def _refine_queue() -> str:
    try:
        return P.refine_queue_path()
    except Exception:
        return REFINE_QUEUE


def _refine_archive_dir() -> str:
    try:
        return P.refine_archive_dir()
    except Exception:
        return REFINE_QUEUE_ARCHIVE_DIR


def _answer_log() -> str:
    try:
        return P.answer_log_path()
    except Exception:
        return os.path.join(DATA_DIR, "answer-log.jsonl")


def _uid() -> str:
    return current_user_id()


def load_weights() -> dict:
    path = _weights_path()
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_weights(weights: dict) -> bool:
    try:
        path = _weights_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
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
        bkt = BKTLogger(_answer_log())
        kc = bkt.get_kp_mastery(_uid(), kp_key)
        if kc is None:
            kc = KCState(p_mastery=0.25)
        else:
            kc = KCState.from_dict(kc.to_dict())
        before = kc.p_mastery
        meta = bkt.record(
            _uid(),
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


def archive_refine_queue(max_entries: int = REFINE_QUEUE_MAX_ENTRIES,
                         max_age_days: int = REFINE_QUEUE_MAX_AGE_DAYS) -> dict:
    """归档 refine-queue 旧条目。

    活跃队列超过 max_entries 条或最旧条目超过 max_age_days 时，
    将旧段移到 data/refine-queue-archive/ 按月 rotate。

    Returns:
        {"ok": True, "archived": N, "remaining": M} 或 {"ok": False, "error": ...}
    """
    rq = _refine_queue()
    if not os.path.isfile(rq):
        return {"ok": True, "archived": 0, "remaining": 0}

    try:
        with open(rq, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        return {"ok": False, "error": str(e)}

    n = len(lines)
    if n == 0:
        return {"ok": True, "archived": 0, "remaining": 0}

    # 检查最旧条目年龄
    oldest_ts: str | None = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            ts = entry.get("ts", "")
            if ts and (oldest_ts is None or ts < oldest_ts):
                oldest_ts = ts
        except (json.JSONDecodeError, ValueError):
            continue

    should_archive = n > max_entries
    if oldest_ts and not should_archive:
        try:
            oldest_dt = datetime.fromisoformat(oldest_ts.replace("Z", "+00:00"))
            # Handle naive datetime (no timezone)
            now_utc = datetime.now(timezone.utc)
            if oldest_dt.tzinfo is None:
                oldest_dt = oldest_dt.replace(tzinfo=timezone.utc)
            age_days = (now_utc - oldest_dt).days
            if age_days > max_age_days:
                should_archive = True
        except (ValueError, TypeError):
            pass

    if not should_archive:
        return {"ok": True, "archived": 0, "remaining": n}

    # 超龄条目移入归档
    now_utc = datetime.now(timezone.utc)
    archive_lines: list[str] = []
    keep: list[str] = []
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue
        try:
            entry = json.loads(line_s)
            ts = entry.get("ts", "")
            if ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_days = (now_utc - dt).days
                if age_days > max_age_days:
                    archive_lines.append(line)
                    continue
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        keep.append(line)

    # 若归档后仍超量，再按数量截断
    if len(keep) > max_entries:
        extra = len(keep) - max_entries
        archive_lines.extend(keep[:extra])
        keep = keep[extra:]

    # 避免全部归档导致空队列
    if not keep and archive_lines:
        keep = archive_lines[-1:]
        archive_lines = archive_lines[:-1]

    if archive_lines:
        now = datetime.now(timezone.utc)
        archive_name = f"refine-queue-{now.strftime('%Y-%m')}.jsonl"
        adir = _refine_archive_dir()
        archive_path = os.path.join(adir, archive_name)
        try:
            os.makedirs(adir, exist_ok=True)
            with open(archive_path, "a", encoding="utf-8") as f:
                f.writelines(archive_lines)
        except OSError as e:
            return {"ok": False, "error": f"write archive failed: {e}"}

    try:
        with open(rq, "w", encoding="utf-8") as f:
            f.writelines(keep)
    except OSError as e:
        return {"ok": False, "error": f"rewrite queue failed: {e}"}

    return {
        "ok": True,
        "archived": len(archive_lines),
        "remaining": len(keep),
    }


def _append_refine_signal(subject: str, kp: str, reason: str, old: float, new: float) -> None:
    try:
        rq = _refine_queue()
        os.makedirs(os.path.dirname(rq) or ".", exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "weak_self_report",
            "subject": subject,
            "kp": kp,
            "reason": reason,
            "weight_before": old,
            "weight_after": new,
        }
        with open(rq, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # 惰性归档（BIG-TEACH-012d #17）
        archive_refine_queue()
    except OSError:
        pass


def _load_baseline(subject: str, kp: str) -> float:
    """从 weights.example.json 读取基线权重（decay 地板）。"""
    example_path = P.weights_example_path()
    try:
        if os.path.isfile(example_path):
            with open(example_path, encoding="utf-8") as f:
                example = json.load(f)
            if isinstance(example, dict):
                return float((example.get(subject) or {}).get("kp_weights", {}).get(kp, 0.0))
    except (OSError, json.JSONDecodeError):
        pass
    return 0.0


def decay_kp_weight(subject: str, kp_hint: str, *, reason: str = "") -> dict:
    """答对时降低出题权重（不低于 baseline），写 refine-queue 信号。"""
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
    baseline = _load_baseline(subject, kp_key)
    delta = DECAY_DELTA_COMM if old >= 0.5 else DECAY_DELTA
    new = round(max(baseline, old - delta), 4)
    if old >= 0.5:
        new = round(max(baseline, old - DECAY_DELTA_COMM), 3)

    if new >= old:
        return {
            "ok": True,
            "subject": subject,
            "kp": kp_key,
            "weight_before": old,
            "weight_after": old,
            "baseline": baseline,
            "reason": reason or "答对衰减（已到基线）",
            "note": "already at or below baseline",
        }

    kp_w[kp_key] = new
    if not save_weights(weights):
        return {"ok": False, "error": "写入 weights.json 失败"}

    _append_decay_signal(subject, kp_key, reason, old, new, baseline)
    return {
        "ok": True,
        "subject": subject,
        "kp": kp_key,
        "weight_before": old,
        "weight_after": new,
        "baseline": baseline,
        "reason": reason or "答对衰减",
    }


def _append_decay_signal(subject: str, kp: str, reason: str,
                         old: float, new: float, baseline: float) -> None:
    try:
        rq = _refine_queue()
        os.makedirs(os.path.dirname(rq) or ".", exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "decay",
            "subject": subject,
            "kp": kp,
            "reason": reason,
            "weight_before": old,
            "weight_after": new,
            "baseline": baseline,
        }
        with open(rq, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # 惰性归档（BIG-TEACH-012d #17）
        archive_refine_queue()
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
