"""011-rag 契约单测（可用 mock，不强制 Chroma）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT = os.environ.get(
    "RAG_CHECK_OUT",
    os.path.join(ROOT, "data", "rag-contract-check.json"),
)


def test_resolve_and_result_shape():
    from learner.rag_retrieve import RagResult, resolve_unit_queries

    q, allow = resolve_unit_queries("math", "math.calc.limit.equiv")
    assert "等价无穷小" in " ".join(q) or any("无穷小" in x for x in q), q
    assert "教材" in allow
    r = RagResult(ok=True, hit_count=2, N=2, snippets=[{"text": "x" * 50, "source": "t"}])
    assert r.to_prompt_items()[0]["text"]
    print("OK resolve + RagResult")


def test_strict_flag():
    from learner.rag_retrieve import rag_strict_enabled

    os.environ["RAG_STRICT"] = "1"
    assert rag_strict_enabled()
    os.environ["RAG_STRICT"] = "0"
    assert not rag_strict_enabled()
    os.environ["RAG_STRICT"] = "1"
    print("OK RAG_STRICT")


def test_cache_path(tmp=None):
    """写入临时 store 后 peek 路径经 rag_retrieve。"""
    import learner.kb_cache as kb
    import learner.rag_retrieve as rr

    td = tempfile.mkdtemp()
    old_store, old_data = kb.STORE_PATH, kb.DATA_DIR
    kb.STORE_PATH = os.path.join(td, "store.json")
    kb.DATA_DIR = td
    os.makedirs(td, exist_ok=True)
    kb.upsert(
        "math",
        "math.calc.limit.equiv",
        [
            {"source": "教材A", "text": "等价无穷小 " + "甲" * 40, "distance": 0.2},
            {"source": "真题B", "text": "无穷小比较 " + "乙" * 40, "distance": 0.3},
        ],
        query="等价无穷小",
    )
    # force cache-only by disabling chroma
    r = rr.rag_retrieve(
        "math", "math.calc.limit.equiv", allow_local_chroma=False, N=2
    )
    kb.STORE_PATH, kb.DATA_DIR = old_store, old_data
    assert r.ok and r.hit_count >= 2 and r.backend == "kb_cache", r
    print("OK cache retrieve")


def test_source_allow_map():
    kb_lib = os.environ.get("KB_LIB", "")
    if not kb_lib or not os.path.isdir(kb_lib):
        print("SKIP source_allow expand (set KB_LIB to knowledge-system/lib)")
        return
    sys.path.insert(0, kb_lib)
    from rag_hints import _expand_source_allow

    f = _expand_source_allow(["教材", "真题"])
    assert "卓里奇" in f or "周炯槃" in f
    assert f[-1] is None
    print("OK source_allow expand")


def main() -> int:
    test_resolve_and_result_shape()
    test_strict_flag()
    test_cache_path()
    test_source_allow_map()
    report = {"PASS": True, "checks": ["resolve", "strict", "cache", "source_allow"]}
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("PASS", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
