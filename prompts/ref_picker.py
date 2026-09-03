"""RefPicker — YAML 锚点选题器

按知识点匹配（含考纲别名/legacy）→ 难度对齐 → 排除近 N 次已用 id → 轮换锚点。
**无 kp 命中时返回 None**，禁止跨知识点任意兜底（008b）。

Usage:
    picker = RefPicker("math")
    entry = picker.pick(kp="函数极限与连续", difficulty="basic")
    # => {"id": "2022-math1-001", ...} or None
"""
from __future__ import annotations

import datetime
import json
import os
from functools import lru_cache

from config import DAILY_RECORD_DIR, DATA_DIR

USED_REFS_PATH = os.path.join(DATA_DIR, "used-refs.jsonl")
EXCLUDE_WINDOW = 20  # 排除最近 N 条引用记录


class RefPicker:
    """从 YAML 种子文件中按策略选取参考题。"""

    def __init__(self, subject: str):
        self.subject = subject
        self._entries: list[dict] = []
        self._used_ids: set[str] = set()
        self._load()

    def _load(self):
        self._entries = _load_yaml_by_subject(self.subject)
        self._used_ids = _load_used_ids(EXCLUDE_WINDOW)

    def reload(self):
        """Force reload from disk (if YAML / used-refs changed at runtime)."""
        self._load()

    def pick(self, kp: str, difficulty: str = "") -> dict | None:
        """按策略选一道参考题。返回 entry dict 或 None。

        优先级（均限制在 kp 命中集内）：
        1. kp 匹配 + 难度对齐 + 未使用
        2. kp 匹配 + 未使用（忽略难度）
        3. kp 匹配（忽略 used-window）
        无命中 → None（禁止跨 kp 兜底）
        """
        if not self._entries or not (kp or "").strip():
            return None

        by_kp = [e for e in self._entries if _entry_matches_kp(self.subject, e, kp)]
        if not by_kp:
            return None

        by_kp_diff = (
            [e for e in by_kp if e.get("difficulty") == difficulty] if difficulty else []
        )

        for candidates in (by_kp_diff, by_kp):
            if not candidates:
                continue
            available = [e for e in candidates if e.get("id") not in self._used_ids]
            pool = available or candidates  # 同 kp 内允许复用
            pick = pool[0]
            self._mark_used(pick.get("id", ""), kp)
            return pick

        return None

    def _mark_used(self, ref_id: str, kp: str):
        """Append to used-refs.jsonl and update in-memory set."""
        if not ref_id:
            return
        record = {
            "ts": datetime.datetime.now().isoformat(),
            "ref_id": ref_id,
            "kp": kp,
            "subject": self.subject,
        }
        try:
            os.makedirs(os.path.dirname(USED_REFS_PATH), exist_ok=True)
            with open(USED_REFS_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._used_ids = _load_used_ids(EXCLUDE_WINDOW)
        except Exception:
            pass


# ── kp 匹配 ──


@lru_cache(maxsize=8)
def _match_tokens_for_subject(subject: str) -> dict[str, set[str]]:
    """formal_l2 -> set of match tokens (formal + aliases + legacy keys that map to it)."""
    from learner.kp_registry import load_legacy_map, load_syllabus, syllabus_subject

    subj = syllabus_subject(subject) or (subject if subject in ("math", "comm") else "")
    syl = load_syllabus(subj)
    kps = syl.get("kps") or {}
    out: dict[str, set[str]] = {}
    for formal, meta in kps.items():
        toks = {formal, formal.lower()}
        for a in meta.get("aliases") or []:
            if a:
                toks.add(a)
                toks.add(a.lower())
        out[formal] = toks

    legacy = (load_legacy_map().get(subj) or {})
    for old, formal in legacy.items():
        if formal in out and old:
            out[formal].add(old)
            out[formal].add(old.lower())
        # also allow matching legacy name as if it were a tag on entry
    return out


def _normalize_query_kp(subject: str, kp: str) -> tuple[str | None, set[str]]:
    """Return (formal_l2 or None, query_tokens)."""
    from learner.kp_registry import list_kps, load_legacy_map, load_syllabus, resolve_kp, syllabus_subject

    subj = syllabus_subject(subject) or (subject if subject in ("math", "comm") else "")
    raw = (kp or "").strip()
    if not raw:
        return None, set()

    weights = {k: 1.0 for k in list_kps(subj)}
    formal = resolve_kp(subj, raw, weights)
    tokens = {raw, raw.lower()}
    if formal:
        tokens |= _match_tokens_for_subject(subj).get(formal, {formal, formal.lower()})
    else:
        # unresolved: still allow exact/alias token match against entry tags
        syl = load_syllabus(subj)
        for fname, meta in (syl.get("kps") or {}).items():
            aliases = meta.get("aliases") or []
            if raw == fname or raw in aliases:
                formal = fname
                tokens |= _match_tokens_for_subject(subj).get(fname, set())
                break
        legacy = load_legacy_map().get(subj) or {}
        if raw in legacy:
            formal = legacy[raw]
            tokens |= _match_tokens_for_subject(subj).get(formal, set())
    return formal, tokens


def _entry_matches_kp(subject: str, entry: dict, kp: str) -> bool:
    """True if entry.kp intersects query formal/aliases (no cross-subject guessing)."""
    tags = entry.get("kp") or []
    if not isinstance(tags, list) or not tags:
        return False
    tag_set = {str(t).strip() for t in tags if t}
    tag_lower = {t.lower() for t in tag_set}

    formal, q_tokens = _normalize_query_kp(subject, kp)
    # exact overlap
    if tag_set & q_tokens or tag_lower & {t.lower() for t in q_tokens}:
        return True

    # entry tags may be informal; map each tag via resolve and compare formal
    if formal:
        from learner.kp_registry import list_kps, resolve_kp, syllabus_subject

        subj = syllabus_subject(subject) or (subject if subject in ("math", "comm") else "")
        weights = {k: 1.0 for k in list_kps(subj)}
        for t in tag_set:
            resolved = resolve_kp(subj, t, weights)
            if resolved == formal:
                return True
            # direct alias membership
            if t in _match_tokens_for_subject(subj).get(formal, set()):
                return True
    return False


# ── 模块级辅助函数 ──


def _load_yaml_by_subject(subject: str) -> list[dict]:
    """Load YAML seed questions for a subject (returns [] on any error)."""
    subj_map = {"math": "math", "comm": "comm"}
    subj_dir = subj_map.get(subject, subject if subject in ("math", "comm") else "")
    if not subj_dir:
        return []
    yaml_dir = os.path.join(DAILY_RECORD_DIR, "structured", subj_dir)
    if not os.path.isdir(yaml_dir):
        return []
    try:
        import yaml

        entries = []
        for fname in sorted(os.listdir(yaml_dir)):
            if not fname.endswith((".yaml", ".yml")):
                continue
            with open(os.path.join(yaml_dir, fname), encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, list):
                    entries.extend(data)
        return entries
    except ImportError:
        return []
    except Exception:
        return []


def _load_used_ids(window: int = EXCLUDE_WINDOW) -> set[str]:
    """Load the most recent `window` ref IDs from used-refs.jsonl."""
    ids: set[str] = set()
    try:
        if not os.path.isfile(USED_REFS_PATH):
            return ids
        with open(USED_REFS_PATH, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        for line in lines[-window:]:
            try:
                data = json.loads(line)
                if isinstance(data, dict) and data.get("ref_id"):
                    ids.add(data["ref_id"])
            except (json.JSONDecodeError, TypeError):
                continue
    except (OSError, json.JSONDecodeError):
        pass
    return ids


def iter_used_refs() -> list[dict]:
    """Return all used-ref records for inspection / debugging."""
    records = []
    try:
        if not os.path.isfile(USED_REFS_PATH):
            return records
        with open(USED_REFS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return records
