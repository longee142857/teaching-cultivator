"""RAG 硬调用契约（BIG-TEACH-011-rag）

唯一出题检索入口：rag_retrieve → RagResult。
禁止 cultivate 直调 query_rag / 裸读 store。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR, RAG_FALLBACK

DEFAULT_N = 2
AUDIT_PATH = os.path.join(DATA_DIR, "rag_audit.jsonl")


def _strict_default() -> bool:
    v = os.environ.get("RAG_STRICT", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


@dataclass
class RagResult:
    ok: bool
    hit_count: int
    N: int = DEFAULT_N
    snippets: list[dict] = field(default_factory=list)
    queries_used: list[str] = field(default_factory=list)
    backend: str = ""
    reason: str = ""
    subject: str = ""
    unit_id: str = ""

    def to_prompt_items(self) -> list[dict]:
        """兼容 PromptBuilder rag_items 形状。"""
        items = []
        for s in self.snippets:
            items.append({
                "source": s.get("source") or "rag",
                "page": s.get("page") or "",
                "distance": s.get("distance", 0.0),
                "text": s.get("text") or "",
            })
        return items


def _audit(result: RagResult) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **{k: getattr(result, k) for k in (
                "ok", "hit_count", "N", "backend", "reason", "subject", "unit_id"
            )},
            "queries_used": result.queries_used,
            "snippet_sources": [s.get("source") for s in result.snippets[:4]],
        }
        with open(AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def resolve_unit_queries(subject: str, unit_id: str) -> tuple[list[str], list[str]]:
    """从 syllabus L3 或 L2 解析 (queries, source_allow)。"""
    from learner.kp_registry import load_syllabus, syllabus_subject, content_subject_for_kp

    subj = syllabus_subject(subject) or content_subject_for_kp(unit_id)
    if subj not in ("math", "comm"):
        subj = subject if subject in ("math", "comm") else ""
    syl = load_syllabus(subj)
    kps = syl.get("kps") or {}

    # L3 id 命中
    for l2_name, meta in kps.items():
        if not isinstance(meta, dict):
            continue
        for l3 in meta.get("l3") or []:
            if not isinstance(l3, dict):
                continue
            if l3.get("id") == unit_id or l3.get("name") == unit_id:
                queries = list(l3.get("rag_queries") or [])
                if l3.get("name"):
                    queries.insert(0, str(l3["name"]))
                for a in l3.get("aliases") or []:
                    if a:
                        queries.append(str(a))
                allow = list(l3.get("source_allow") or ["教材", "真题"])
                # dedupe keep order
                seen: set[str] = set()
                qout = []
                for q in queries:
                    q = (q or "").strip()
                    if q and q not in seen:
                        seen.add(q)
                        qout.append(q)
                return qout or [unit_id], allow

    # L2 名命中
    meta = kps.get(unit_id)
    if isinstance(meta, dict):
        queries = [unit_id]
        scope = (meta.get("scope") or "").replace("、", " ").replace("/", " ")
        for part in scope.split():
            if len(part) >= 2:
                queries.append(part)
        for a in meta.get("aliases") or []:
            if a:
                queries.append(str(a))
        seen = set()
        qout = []
        for q in queries:
            q = (q or "").strip()
            if q and q not in seen:
                seen.add(q)
                qout.append(q)
        return qout[:8], ["教材", "真题"]

    return [unit_id], ["教材", "真题"]


def _from_cache(subject: str, unit_id: str, N: int) -> RagResult | None:
    from learner import kb_cache

    entry = kb_cache.peek(subject, unit_id)
    if not entry:
        # 兼容旧键：若 unit 是 l3，也试不到再试
        return None
    items = kb_cache.entry_to_rag_items(entry)
    # bump hits via lookup
    kb_cache.lookup(subject, unit_id)
    snippets = []
    for i, it in enumerate(items):
        snippets.append({
            "id": f"cache-{i:03d}",
            "source": it.get("source"),
            "page": it.get("page"),
            "distance": it.get("distance", 0.0),
            "text": it.get("text"),
        })
    hit = len(snippets)
    ok = hit >= N
    return RagResult(
        ok=ok,
        hit_count=hit,
        N=N,
        snippets=snippets,
        queries_used=[entry.get("query") or unit_id],
        backend="kb_cache",
        reason="ok" if ok else "cache_below_N",
        subject=subject,
        unit_id=unit_id,
    )


# 数一培养主闸：按考点分科，不再把「教材」扩成含卓里奇的大杂烩。
# 卓里奇仍在 Chroma，供 Agent 拓展检索；不进 calc/prob/linalg 主路径。
_SOURCE_HINTS_MATH_TRACK = {
    "calc": ["同济", "高等数学"],
    "linalg": ["丘维声", "高等代数"],
    "prob": ["盛骤", "茆诗松", "概率论", "数理统计"],
}
_SOURCE_HINTS_MATH_TAG = {
    "真题": ["真题", "题库", "灰虎", "考研数学", "数学一"],
    "讲义": ["讲义", "笔记"],
}
_SOURCE_HINTS_COMM = {
    "教材": ["周炯槃", "樊昌信", "通信原理"],
    "真题": ["真题", "题库", "801", "北邮"],
    "讲义": ["讲义", "笔记"],
}
_ALLOW_TAGS = frozenset({"教材", "真题", "讲义"})


def _math_track_for_unit(unit_id: str) -> str:
    """math.calc.* / math.linalg.* / math.prob.* → track；L2 中文名查 syllabus。"""
    uid = (unit_id or "").strip()
    for track in ("calc", "linalg", "prob"):
        if uid.startswith(f"math.{track}."):
            return track
    try:
        from learner.kp_registry import load_syllabus

        meta = (load_syllabus("math").get("kps") or {}).get(uid)
        if isinstance(meta, dict):
            for l3 in meta.get("l3") or []:
                lid = (l3.get("id") or "").strip()
                for track in ("calc", "linalg", "prob"):
                    if lid.startswith(f"math.{track}."):
                        return track
    except Exception:
        pass
    return ""


def _source_hints_from_allow(
    subject: str, source_allow: list[str], unit_id: str = ""
) -> list[str]:
    """映射 source_allow → source_hints。教材按考点分科；非标签项原样作 hint。"""
    hints: list[str] = []
    allow = list(source_allow or ["教材", "真题"])
    if subject == "comm":
        for item in allow:
            if item in _SOURCE_HINTS_COMM:
                hints.extend(_SOURCE_HINTS_COMM[item])
            elif item not in _ALLOW_TAGS:
                hints.append(item)
        if not hints:
            hints = list(_SOURCE_HINTS_COMM["教材"]) + list(_SOURCE_HINTS_COMM["真题"][:2])
    else:
        track = _math_track_for_unit(unit_id)
        for item in allow:
            if item == "教材":
                if track and track in _SOURCE_HINTS_MATH_TRACK:
                    hints.extend(_SOURCE_HINTS_MATH_TRACK[track])
                else:
                    # 未知 L2：三科主书，仍不含卓里奇
                    for t in ("calc", "linalg", "prob"):
                        hints.extend(_SOURCE_HINTS_MATH_TRACK[t])
            elif item in _SOURCE_HINTS_MATH_TAG:
                hints.extend(_SOURCE_HINTS_MATH_TAG[item])
            elif item not in _ALLOW_TAGS:
                hints.append(item)
        if not hints:
            if track and track in _SOURCE_HINTS_MATH_TRACK:
                hints = list(_SOURCE_HINTS_MATH_TRACK[track]) + list(
                    _SOURCE_HINTS_MATH_TAG["真题"][:2]
                )
            else:
                hints = ["同济", "盛骤", "丘维声"]
    seen: set[str] = set()
    out: list[str] = []
    for h in hints:
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _query_local_chroma(
    subject: str,
    unit_id: str,
    queries: list[str],
    source_allow: list[str],
    top_k: int,
    N: int,
) -> RagResult:
    """经独立进程查本机 Chroma（避免 teaching config 与 knowledge-system src.config 冲突）。"""
    import subprocess
    import sys
    from pathlib import Path

    helper = Path(
        os.environ.get(
            "KB_QUERY_HELPER",
            "",
        )
        or ""
    )
    if not helper or not helper.is_file():
        return RagResult(
            ok=False,
            hit_count=0,
            N=N,
            snippets=[],
            backend="chroma_helper_missing",
            reason="Set KB_QUERY_HELPER to an executable query script path",
            subject=subject,
            unit_id=unit_id,
        )
    py = os.environ.get("KB_PYTHON") or sys.executable
    if not os.path.isfile(py):
        py = sys.executable

    try:
        hints = _source_hints_from_allow(subject, source_allow, unit_id)
        req = {
            "subject": subject,
            "kp": unit_id,
            "query": " ".join(queries[:4]),
            "top_k": top_k,
            "source_hints": hints,
        }
        proc = subprocess.run(
            [py, str(helper)],
            input=json.dumps(req, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=180,
            encoding="utf-8",
            errors="replace",
        )
        lines = (proc.stdout or "").strip().splitlines()
        raw = lines[-1] if lines else "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"snippets": [], "error": f"bad_stdout:{(proc.stdout or '')[:200]}"}
        snippets: list[dict] = []
        for i, s in enumerate(data.get("snippets") or []):
            if not isinstance(s, dict):
                continue
            text = (s.get("text") or "").strip()
            if not text:
                continue
            snippets.append({
                "id": f"rag-{i:03d}",
                "source": s.get("source") or "?",
                "page": s.get("page") or "",
                "distance": s.get("distance", 0.0),
                "text": text[:400],
            })
        hit = len(snippets)
        ok = hit >= N
        if snippets:
            try:
                from learner import kb_cache

                kb_cache.upsert(
                    subject,
                    unit_id,
                    snippets,
                    query=" | ".join(queries[:3]),
                )
            except Exception:
                pass
        err = data.get("error") or ""
        reason = "ok" if ok else ("chroma_below_N" if hit else (err or "chroma_empty"))
        if proc.returncode != 0 and not snippets:
            reason = f"chroma_exit_{proc.returncode}:{(err or proc.stderr or '')[:100]}"
        return RagResult(
            ok=ok,
            hit_count=hit,
            N=N,
            snippets=snippets,
            queries_used=queries,
            backend="chroma_local",
            reason=reason,
            subject=subject,
            unit_id=unit_id,
        )
    except Exception as e:
        return RagResult(
            ok=False,
            hit_count=0,
            N=N,
            snippets=[],
            queries_used=queries,
            backend="chroma_local",
            reason=f"chroma_error:{type(e).__name__}:{e}",
            subject=subject,
            unit_id=unit_id,
        )


def rag_retrieve(
    subject: str,
    unit_id: str,
    *,
    ability_goal: str | None = None,
    top_k: int = 4,
    N: int | None = None,
    allow_local_chroma: bool = True,
) -> RagResult:
    """硬契约入口。unit_id = l3_id 或 L2 正式名。

    顺序：kb_cache →（本机）Chroma → enqueue miss。
    """
    _ = ability_goal
    n = int(N if N is not None else DEFAULT_N)
    from learner.kp_registry import syllabus_subject, content_subject_for_kp

    subj = syllabus_subject(subject) or content_subject_for_kp(unit_id or "")
    if subj not in ("math", "comm"):
        subj = subject if subject in ("math", "comm") else ""
    if subj not in ("math", "comm") or not (unit_id or "").strip():
        r = RagResult(
            ok=False, hit_count=0, N=n, reason="invalid_subject_or_unit",
            subject=subj, unit_id=unit_id or "",
        )
        _audit(r)
        return r

    unit_id = unit_id.strip()
    queries, source_allow = resolve_unit_queries(subj, unit_id)

    cached = _from_cache(subj, unit_id, n)
    if cached and cached.hit_count > 0:
        _audit(cached)
        return cached

    # 本机 Chroma（开发机 / warm）
    from config import KB_PATH

    chroma_dir = os.path.join(KB_PATH, "data", "chromadb")
    if allow_local_chroma and os.path.isdir(chroma_dir):
        local = _query_local_chroma(subj, unit_id, queries, source_allow, top_k, n)
        if local.hit_count == 0 and not local.reason.startswith("chroma_error"):
            try:
                from learner import kb_cache

                kb_cache.enqueue(
                    subj,
                    unit_id,
                    query=queries[0] if queries else unit_id,
                    reason="chroma_empty",
                )
            except Exception:
                pass
        _audit(local)
        return local

    # 云端：入队等回填
    try:
        from learner import kb_cache

        kb_cache.enqueue(
            subj, unit_id, query=queries[0] if queries else unit_id, reason="prompt_miss"
        )
        reason = "queued"
    except Exception as e:
        reason = f"enqueue_fail:{type(e).__name__}"

    r = RagResult(
        ok=False,
        hit_count=0,
        N=n,
        snippets=[],
        queries_used=queries,
        backend="kb_cache",
        reason=reason,
        subject=subj,
        unit_id=unit_id,
    )
    _audit(r)
    return r


def rag_strict_enabled() -> bool:
    """RAG strict 检查。当 RAG_FALLBACK=abort（默认）或 RAG_STRICT=1 时开启。"""
    if RAG_FALLBACK == "abort":
        return True
    return _strict_default()
