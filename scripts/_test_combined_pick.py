"""抽题结合模型冒烟：score / pick_for_push 偏好与 η 提权。"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
KL = os.path.join(ROOT, "knowledge-lib")
if KL not in sys.path:
    sys.path.insert(0, KL)


def _store():
    from learner.db import Store, reset_store

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["TEACHING_DB"] = path
    reset_store()
    return Store(path), path


def _cleanup(path):
    from learner.db import reset_store

    os.environ.pop("TEACHING_DB", None)
    reset_store()
    try:
        os.remove(path)
    except OSError:
        pass


def test_score_prefers_weak_domain_and_quality():
    from modules.capability import PickContext, score_ready_item, pick_best_item

    ctx = PickContext(
        learner_id="u",
        mastery={"极限": 0.8, "矩阵与初等变换": 0.2},
        kp_weights={"极限": 1.0, "矩阵与初等变换": 1.0},
        domain_boosts={"calc": 0.0, "linalg": 0.15, "prob": 0.0},
        tech_boost={},
        due_kps=set(),
        recent_kps=[],
    )
    items = [
        {
            "id": 1,
            "kp": "极限",
            "quality_score": 1.0,
            "quality_tier": "pass",
            "techniques": ["t"],
        },
        {
            "id": 2,
            "kp": "矩阵与初等变换",
            "quality_score": 0.95,
            "quality_tier": "pass",
            "techniques": ["t"],
        },
        {
            "id": 3,
            "kp": "矩阵与初等变换",
            "quality_score": 0.1,
            "quality_tier": "poor",
            "techniques": ["t"],
        },
    ]
    best, sc = pick_best_item(items, ctx)
    assert best and best["id"] == 2, best
    # prefer_kp 可抬高 calc
    best2, _ = pick_best_item(items, ctx, prefer_kp="极限")
    assert best2 and best2["id"] == 1
    # poor 同 KP 不应胜过 pass
    assert score_ready_item(items[1], ctx) > score_ready_item(items[2], ctx)
    print("ok score_prefers", "best=", best["id"], "prefer_kp→", best2["id"])


def test_pick_for_push_combined():
    from types import ModuleType
    from unittest.mock import patch
    from learner.context import bind_learner
    from learner import item_bank

    store, path = _store()
    try:
        sol = {"steps": [{"id": "s1", "text": "x"}], "final_answer": "1"}
        cdps = [
            {"id": "cdp1", "prompt": "p", "expected": "e", "technique": "t_a"},
            {"id": "cdp2", "prompt": "p2", "expected": "e2", "technique": "t_a"},
        ]
        # 强掌握 KP 高质量
        store.insert_bank_item(
            subject="math",
            question="Q calc strong",
            answer="1",
            difficulty="medium",
            kp="极限",
            techniques=["t_a"],
            solution=sol,
            cdps=cdps,
            status="ready",
        )
        # 弱掌握 KP（linalg）高质量 — 应被结合模型优先（无 prefer 时）
        store.insert_bank_item(
            subject="math",
            question="Q linalg weak",
            answer="2",
            difficulty="hard",
            kp="矩阵与初等变换",
            techniques=["t_b"],
            solution=sol,
            cdps=cdps,
            status="ready",
        )
        # 给 linalg 题 pass、calc 题 pass
        for row in store._query("SELECT id, kp FROM items"):
            store._txn(
                lambda conn, i=row[0]: conn.execute(
                    "UPDATE items SET quality_tier='pass', quality_score=1.0 WHERE id=?",
                    (i,),
                )
            )

        store.set_mastery(
            "u_pick",
            "极限",
            {"p_mastery": 0.85, "opportunity_count": 5, "is_mastered": True},
        )
        store.set_mastery(
            "u_pick",
            "矩阵与初等变换",
            {"p_mastery": 0.25, "opportunity_count": 2, "is_mastered": False},
        )
        # 作答以估 η：linalg 全错 → 域弱
        store._txn(
            lambda conn: conn.execute(
                """INSERT INTO attempts
                   (user_id, knowledge_point, correct, status, answered_at, item_type, meta)
                   VALUES (?,?,?,?,?,?,?)""",
                ("u_pick", "矩阵与初等变换", 0, "applied", "2026-08-10T00:00:00+00:00", "open", "{}"),
            )
        )
        store._txn(
            lambda conn: conn.execute(
                """INSERT INTO attempts
                   (user_id, knowledge_point, correct, status, answered_at, item_type, meta)
                   VALUES (?,?,?,?,?,?,?)""",
                ("u_pick", "极限", 1, "applied", "2026-08-11T00:00:00+00:00", "open", "{}"),
            )
        )

        # stub cultivate weights / uid
        cult = ModuleType("cultivate")
        cult._load_weights = lambda: {
            "math": {
                "kp_weights": {"极限": 1.0, "矩阵与初等变换": 1.0},
            }
        }
        cult._uid = lambda: "u_pick"

        bind_learner("u_pick")
        with patch.dict(sys.modules, {"cultivate": cult}):
            hit = item_bank.pick_for_push("math", learner_id="u_pick")
            assert hit is not None
            assert hit["kp"] == "矩阵与初等变换", hit
            # hard L2：prefer 极限只抽该 KP，不再跨到弱项抢戏
            hit2 = item_bank.pick_for_push(
                "math", kp="极限", learner_id="u_pick"
            )
            assert hit2 is not None
            assert hit2["kp"] == "极限", hit2
            hit3 = item_bank.pick_for_push(
                "math", kp="不存在的KP名", learner_id="u_pick"
            )
            assert hit3 is None, hit3
        print("ok pick_for_push_combined", hit["kp"], "prefer→", hit2["kp"])
    finally:
        _cleanup(path)


if __name__ == "__main__":
    test_score_prefers_weak_domain_and_quality()
    test_pick_for_push_combined()
    print("ALL PASS")
