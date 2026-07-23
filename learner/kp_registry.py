"""考纲知识点注册表：syllabus + aliases + 旧桶兼容。"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from config import DATA_DIR

SYLLABUS_PATHS = {
    "math": os.path.join(DATA_DIR, "syllabus_math.json"),
    "comm": os.path.join(DATA_DIR, "syllabus_comm.json"),
}
LEGACY_PATH = os.path.join(DATA_DIR, "legacy_kp_map.json")
RECENT_PICKS_PATH = os.path.join(DATA_DIR, "recent_kp_picks.json")
WEIGHTS_PATH = os.path.join(DATA_DIR, "weights.json")

ROTATE_N = 3
DEFAULT_MASTERY = 0.2


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


@lru_cache(maxsize=1)
def load_legacy_map() -> dict:
    return _load_json(LEGACY_PATH)


@lru_cache(maxsize=4)
def load_syllabus(subject: str) -> dict:
    path = SYLLABUS_PATHS.get(subject)
    if not path:
        return {}
    return _load_json(path)


def reload_registry() -> None:
    """测试或热更新后清缓存。"""
    load_legacy_map.cache_clear()
    load_syllabus.cache_clear()


def list_kps(subject: str) -> list[str]:
    syl = load_syllabus(subject)
    return list((syl.get("kps") or {}).keys())


def get_l1(subject: str, kp: str) -> str | None:
    meta = (load_syllabus(subject).get("kps") or {}).get(kp) or {}
    return meta.get("l1")


def get_l1_name(subject: str, l1_id: str) -> str:
    l1 = (load_syllabus(subject).get("l1") or {}).get(l1_id) or {}
    return l1.get("name") or l1_id


def _split_kp_parts(hint: str) -> list[str]:
    """拆 LLM 批改产出的「A、B、C」多概念串。"""
    parts = re.split(r"[、，,；;/\n]|以及", hint or "")
    out: list[str] = []
    for p in parts:
        p = p.strip().strip("。．.；;")
        if len(p) >= 2:
            out.append(p)
    return out


def _looks_multi_concept(hint: str) -> bool:
    if len(hint) < 12:
        return False
    return bool(re.search(r"[、，,；;]", hint))


def _is_known_l2(subject: str, name: str, kp_weights: dict) -> bool:
    if not name:
        return False
    if name in kp_weights:
        return True
    return name in (load_syllabus(subject).get("kps") or {})


# ── L3 helpers (BIG-TEACH-011c) ──


def syllabus_subject(subject: str) -> str:
    """规范化考纲科目：review 映射到 math，其余原样。

    rag_retrieve 已有同样映射（review → math）；保持一致。
    """
    return "math" if subject == "review" else subject


def list_l3_for_l2(subject: str, l2_name: str) -> list[dict]:
    """返回该 L2 在考纲中的 l3[] 列表；无 l3 或 l2 不存在则返空列表。"""
    subj = syllabus_subject(subject)
    syl = load_syllabus(subj)
    kps = syl.get("kps") or {}
    meta = kps.get(l2_name)
    if not isinstance(meta, dict):
        return []
    return list(meta.get("l3") or [])


def pick_l3(subject: str, l2_name: str, *,
            recent_l3: list[str] | None = None, rotate_n: int = 3,
            rng=None) -> str | None:
    """从指定 L2 的 l3[] 中选取一个 L3 id。

    用轮转避免连续选同一子知识点；
    若 L2 无 l3[] 或列表为空返回 None。
    """
    import random as _random
    rng = rng or _random
    l3_list = list_l3_for_l2(subject, l2_name)
    if not l3_list:
        return None

    # 轮转：对 recent_l3 降权
    recent = set(recent_l3 or [])
    # 按可选权重（若 l3 有 weight 字段）或在列表内均匀随机
    candidates = [l3 for l3 in l3_list if isinstance(l3, dict)]
    if not candidates:
        return None

    # 无权重时均匀随机；有 weight 字段可加权
    weights = []
    for l3 in candidates:
        w = float(l3.get("weight", 1.0))
        l3_id = (l3.get("id") or "").strip()
        if l3_id in recent:
            w *= 0.1  # 最近选过的降权
        weights.append(max(w, 0.01))

    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for l3, w in zip(candidates, weights):
        acc += w
        if r <= acc:
            return (l3.get("id") or "").strip()
    last = candidates[-1]
    return (last.get("id") or "").strip()


def is_valid_l3_id(subject: str, l3_id: str) -> bool:
    """检查 l3_id 是否存在于该科目考纲的任 L2 的 l3[] 中。"""
    if not l3_id or not isinstance(l3_id, str):
        return False
    l3_id = l3_id.strip()
    if not l3_id:
        return False
    subj = syllabus_subject(subject)
    syl = load_syllabus(subj)
    kps = syl.get("kps") or {}
    for meta in kps.values():
        if not isinstance(meta, dict):
            continue
        for l3 in meta.get("l3") or []:
            if isinstance(l3, dict) and (l3.get("id") or "").strip() == l3_id:
                return True
    return False


def looks_like_l3_id(unit_id: str) -> bool:
    """判断 unit_id 是否为点分式 L3 id（如 'math.calc.limit.def'），而非 L2 中文名。

    用于生产路径拒绝 L2 传入的硬闸检查。
    """
    if not unit_id:
        return False
    # L3 id 特征：包含点号且无中文字符
    if "." in unit_id:
        # 确认无中文字符
        for ch in unit_id:
            if "一" <= ch <= "鿿" or "　" <= ch <= "〿":
                return False
        return True
    return False


def parse_l3_from_reason(reason: str) -> str | None:
    """从 decision.reason 提取 [l3=...] 中编码的 L3 id。

    格式约定：
        "{kp}: {detail} [l3={l3_id}]"
    无 [l3=...] 时返回 None（旧格式兼容）。
    """
    import re
    m = re.search(r'\[l3=([^\]]+)\]', reason or "")
    return m.group(1).strip() if m else None


def resolve_kp(subject: str, kp_hint: str, kp_weights: dict | None = None) -> str | None:
    """精确 → legacy →（多概念先拆段）→ 别名/标准名打分。

    长串（批改 LLM 的「涉及知识点：A、B、C」）按**第一段**可解析结果为准，
    避免「偏导…、微分方程…」被短别名「微分方程」整串抢走。
    """
    hint = (kp_hint or "").strip()
    if not hint:
        return None

    if kp_weights is None:
        weights = _load_json(WEIGHTS_PATH)
        kp_weights = (weights.get(subject) or {}).get("kp_weights") or {}

    if hint in kp_weights:
        return hint
    syl = load_syllabus(subject)
    kps_meta = syl.get("kps") or {}
    if hint in kps_meta:
        return hint

    legacy = (load_legacy_map().get(subject) or {}).get(hint)
    if legacy:
        return legacy

    # 多概念：优先解析靠前片段（通常是本题主考点）
    if _looks_multi_concept(hint):
        for part in _split_kp_parts(hint):
            got = resolve_kp(subject, part, kp_weights)
            if got:
                return got

    # 别名 / 标准名：更长匹配优先，同长度取更靠前
    best_name: str | None = None
    best_key: tuple[int, int] | None = None  # (len, -pos)
    for name, meta in kps_meta.items():
        terms = [name] + list(meta.get("aliases") or [])
        for term in terms:
            if not term or len(term) < 2:
                continue
            if hint == term:
                return name
            pos = hint.find(term)
            if pos >= 0:
                key = (len(term), -pos)
                if best_key is None or key > best_key:
                    best_key = key
                    best_name = name
            elif len(hint) >= 2 and hint in term:
                # hint 是某 alias/标准名的短写
                key = (len(hint), 0)
                if best_key is None or key > best_key:
                    best_key = key
                    best_name = name

    if best_name and (_is_known_l2(subject, best_name, kp_weights) or not kp_weights):
        return best_name

    # 权重表标准名互含（无 syllabus 时的兜底）
    for name in kp_weights or ():
        if hint in name or name in hint:
            return name
    return None


def normalize_kp_for_grade(
    subject: str,
    hint: str = "",
    *,
    preferred: str | None = None,
    kp_weights: dict | None = None,
) -> str | None:
    """批改落盘用：preferred（last_push.kp）若已是考纲 L2 则优先，否则 resolve。"""
    if kp_weights is None:
        weights = _load_json(WEIGHTS_PATH)
        kp_weights = (weights.get(subject) or {}).get("kp_weights") or {}

    pref = (preferred or "").strip()
    if pref:
        if _is_known_l2(subject, pref, kp_weights):
            return pref
        resolved_pref = resolve_kp(subject, pref, kp_weights)
        if resolved_pref:
            return resolved_pref

    hint = (hint or "").strip()
    if not hint:
        return None
    return resolve_kp(subject, hint, kp_weights)


def load_recent_picks(subject: str) -> list[str]:
    data = _load_json(RECENT_PICKS_PATH)
    picks = data.get(subject) or []
    return [p for p in picks if isinstance(p, str)]


def append_recent_pick(subject: str, kp: str, *, maxlen: int = 12) -> None:
    if not kp or subject not in ("math", "comm"):
        return
    data = _load_json(RECENT_PICKS_PATH)
    picks = [p for p in (data.get(subject) or []) if isinstance(p, str)]
    picks = [kp] + [p for p in picks if p != kp]
    data[subject] = picks[:maxlen]
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(RECENT_PICKS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError:
        pass


def pick_kp_weighted(
    subject: str,
    kp_weights: dict[str, float],
    mastery: dict[str, float],
    *,
    recent: list[str] | None = None,
    rotate_n: int = ROTATE_N,
    rng=None,
    due_kps: set[str] | None = None,
) -> str | None:
    """score = weight × (1-mastery)，加权随机；同 L1 近 N 次同 kp 降权；到期提权。"""
    import random

    if not kp_weights:
        return None
    if rng is None:
        rng = random

    recent = recent if recent is not None else load_recent_picks(subject)
    recent_window = recent[:rotate_n]
    due = due_kps or set()

    scores: list[tuple[str, float]] = []
    for kp, w in kp_weights.items():
        try:
            weight = float(w)
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        m = mastery.get(kp)
        if m is None:
            m = DEFAULT_MASTERY
        m = max(0.0, min(1.0, float(m)))
        score = weight * (1.0 - m)
        if score < 1e-9:
            score = 1e-9
        if kp in recent_window:
            score *= 0.05
        if kp in due:
            score *= 3.0
        scores.append((kp, score))

    if not scores:
        return None
    total = sum(s for _, s in scores)
    r = rng.random() * total
    acc = 0.0
    for kp, s in scores:
        acc += s
        if r <= acc:
            return kp
    return scores[-1][0]
