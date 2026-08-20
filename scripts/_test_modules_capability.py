"""验收：模块拆分 + LearnerParams（BKT + η）核心契约。"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_import_modules():
    import modules
    from modules import capability, notify, bridge, store, items, frontend

    assert modules.__all__
    assert capability.DOMAINS == ("calc", "linalg", "prob")
    assert frontend.MOUNT_HINT
    print("ok import_modules")


def test_irt_mle_monotonic():
    from modules.capability import irt_mle

    # 全对 → η 应明显高于全错
    a = [1.0, 1.0, 1.0, 1.0]
    d = [0.0, 0.0, 0.0, 0.0]
    eta_hi = irt_mle([1, 1, 1, 1], a, d)
    eta_lo = irt_mle([0, 0, 0, 0], a, d)
    assert eta_hi > eta_lo
    print(f"ok irt_mle_monotonic hi={eta_hi:.3f} lo={eta_lo:.3f}")


def test_attempts_to_bundle_and_eta():
    from modules.capability import attempts_to_bundle, estimate_latent, DOMAINS

    rows = [
        {"knowledge_point": "极限", "correct": 1, "difficulty": "medium", "status": "applied",
         "ts": "2026-08-01T00:00:00+00:00"},
        {"knowledge_point": "矩阵", "correct": 0, "difficulty": "hard", "status": "applied",
         "ts": "2026-08-02T00:00:00+00:00"},
        {"knowledge_point": "概率分布", "correct": 1, "difficulty": "easy", "status": "applied",
         "ts": "2026-08-03T00:00:00+00:00"},
        {"knowledge_point": "未分类", "correct": 1, "status": "applied",
         "ts": "2026-08-03T00:00:00+00:00"},
        {"knowledge_point": "极限", "correct": 0, "status": "pending",
         "ts": "2026-08-03T00:00:00+00:00"},
    ]
    # 用真实 syllabus 映射；若极限/矩阵不在图中，子串仍可能命中
    syllabus = os.path.join(ROOT, "data", "syllabus_math.json")
    bundle = attempts_to_bundle(
        rows, learner_id="t1", days=3650, syllabus_path=syllabus
    )
    assert bundle["learner_id"] == "t1"
    assert bundle["meta"]["skipped"]["bad"] >= 1  # 未分类 + pending
    latent = estimate_latent(bundle, domains=list(DOMAINS))
    assert len(latent.eta_hat) == 3
    assert "BKT" not in str(bundle.get("items"))
    print(
        "ok attempts_bundle",
        "n=", bundle["meta"]["n_items"],
        "eta=", [round(x, 3) for x in latent.eta_hat],
    )


def test_learner_params_from_store():
    from learner.db import Store
    from modules.capability import build_learner_params

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        store = Store(path)
        store.set_mastery(
            "u1",
            "极限",
            {"p_mastery": 0.4, "opportunity_count": 2, "is_mastered": False},
        )
        store._txn(
            lambda conn: conn.execute(
                """INSERT INTO attempts
                   (user_id, knowledge_point, correct, status, answered_at, credit, item_type, meta)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    "u1",
                    "极限",
                    1,
                    "applied",
                    "2026-08-10T12:00:00+00:00",
                    1.0,
                    "open",
                    "{}",
                ),
            )
        )
        store._txn(
            lambda conn: conn.execute(
                """INSERT INTO attempts
                   (user_id, knowledge_point, correct, status, answered_at, credit, item_type, meta)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    "u1",
                    "矩阵的秩",
                    0,
                    "applied",
                    "2026-08-11T12:00:00+00:00",
                    0.0,
                    "open",
                    "{}",
                ),
            )
        )

        syllabus = os.path.join(ROOT, "data", "syllabus_math.json")
        params = build_learner_params(
            store, "u1", learner_id="u1", days=3650, syllabus_path=syllabus
        )
        d = params.to_dict()
        assert d["learner_id"] == "u1"
        assert any(m["kp"] == "极限" for m in d["mastery"])
        assert len(d["eta"]) == 3
        assert any("不直接作为事件" in a for a in d["assumptions"])
        print("ok learner_params", "mastery_n=", len(d["mastery"]), "eta=", d["eta"])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def test_notify_deep_link():
    from modules.notify import build_deep_link, notify_new_item, Notification

    link = build_deep_link(
        "https://app.example",
        learner_id="04022300",
        item_id=12,
        push_id=3,
    )
    assert link.startswith("https://app.example/practice?")
    assert "learner=04022300" in link
    assert "item=12" in link

    sent = []

    class Cap:
        def send_notification(self, note: Notification) -> bool:
            sent.append(note)
            return True

    ok = notify_new_item(
        Cap(),
        learner_id="u1",
        subject="math",
        item_id=1,
        frontend_base="https://app.example",
        kp="极限",
    )
    assert ok and sent[0].kind == "new_item"
    assert "前端" in sent[0].body
    print("ok notify_deep_link", link)


def test_bridge_whitelist():
    from modules.bridge import capability_whitelist

    w = capability_whitelist()
    assert "get_learner_params" in w
    assert "get_capability_evidence" in w
    print("ok bridge_whitelist")


def test_bkt_not_confused_with_eta():
    """红线：LearnerParams.to_evidence_bundle 不含 mastery 冒充 items。"""
    from modules.capability.params import LearnerParams, DomainEta, MasteryEntry

    p = LearnerParams(
        learner_id="x",
        mastery=[MasteryEntry(kp="极限", p_mastery=0.9)],
        eta=[DomainEta(domain="calc", eta=1.2, n_items=3)],
    )
    slim = p.to_evidence_bundle()
    assert "items" not in slim
    assert slim["eta_hat"] == [1.2]
    print("ok bkt_eta_separation")


if __name__ == "__main__":
    test_import_modules()
    test_irt_mle_monotonic()
    test_attempts_to_bundle_and_eta()
    test_learner_params_from_store()
    test_notify_deep_link()
    test_bridge_whitelist()
    test_bkt_not_confused_with_eta()
    print("ALL PASS")
