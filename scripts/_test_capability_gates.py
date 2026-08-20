"""逐闸冒烟：capability × teaching 结合。

Gate1 — 题参 IRT 附着 + EvidenceBundle 从 store 拼回
Gate2 — grade applied 后 refresh LearnerParams / ability_snapshots
Gate3 — weak_kp_ranked 消费域 η boost
"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SYLLABUS = os.path.join(ROOT, "data", "syllabus_math.json")


def _fresh_store():
    from learner.db import Store

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Store(path), path


def gate1_irt_and_evidence():
    from modules.capability import merge_irt_into_meta, bundle_from_store, estimate_latent, DOMAINS

    store, path = _fresh_store()
    try:
        meta = merge_irt_into_meta(
            {"source": "pregen"}, kp="极限", difficulty="hard", syllabus_path=SYLLABUS
        )
        assert "irt" in meta and meta["irt"]["a"] == 1.0
        assert meta["irt"]["d"] == 0.5
        assert meta["irt"]["domain"] == "calc"

        iid = store.insert_bank_item(
            subject="math",
            question="gate1 Q limit",
            answer="A",
            difficulty="hard",
            kp="极限",
            meta=meta,
            techniques=["limit"],
            solution={"steps": [{"id": "s1", "text": "t"}], "final_answer": "A"},
            cdps=[
                {"id": "cdp1", "prompt": "p", "expected": "e", "technique": "limit"},
                {"id": "cdp2", "prompt": "p2", "expected": "e2", "technique": "limit"},
            ],
            status="ready",
        )
        item = store.get_item(iid)
        assert isinstance(item.get("meta"), dict)
        assert item["meta"]["irt"]["domain"] == "calc"

        store._txn(
            lambda conn: conn.execute(
                """INSERT INTO attempts
                   (user_id, item_id, knowledge_point, correct, status, answered_at, item_type, meta)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    "u_g1",
                    iid,
                    "极限",
                    1,
                    "applied",
                    "2026-08-10T12:00:00+00:00",
                    "open",
                    "{}",
                ),
            )
        )
        store._txn(
            lambda conn: conn.execute(
                """INSERT INTO attempts
                   (user_id, item_id, knowledge_point, correct, status, answered_at, item_type, meta)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    "u_g1",
                    None,
                    "矩阵",
                    0,
                    "applied",
                    "2026-08-11T12:00:00+00:00",
                    "open",
                    "{}",
                ),
            )
        )

        attempts = store.get_attempts("u_g1")
        assert attempts[0].get("item_id") == iid

        bundle = bundle_from_store(store, "u_g1", days=3650, syllabus_path=SYLLABUS)
        # 带 item 的那题应吃到 d=0.5
        calc_items = [it for it in bundle["items"] if it["domain"] == "calc"]
        assert calc_items, bundle
        assert calc_items[0]["d"] == 0.5
        assert calc_items[0]["irt_source"] in ("meta", "difficulty_map")
        latent = estimate_latent(bundle, domains=list(DOMAINS))
        assert len(latent.eta_hat) == 3
        print("GATE1 PASS", "calc_d=", calc_items[0]["d"], "eta=", [round(x, 3) for x in latent.eta_hat])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def gate2_refresh_after_grade():
    from modules.capability import refresh_after_grade
    from learner.db import reset_store

    store, path = _fresh_store()
    try:
        os.environ["TEACHING_DB"] = path
        reset_store()

        store.set_mastery(
            "u_g2",
            "极限",
            {"p_mastery": 0.35, "opportunity_count": 2, "is_mastered": False},
        )
        store._txn(
            lambda conn: conn.execute(
                """INSERT INTO attempts
                   (user_id, knowledge_point, correct, status, answered_at, item_type, meta)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    "u_g2",
                    "极限",
                    1,
                    "applied",
                    "2026-08-12T12:00:00+00:00",
                    "open",
                    "{}",
                ),
            )
        )
        store._txn(
            lambda conn: conn.execute(
                """INSERT INTO attempts
                   (user_id, knowledge_point, correct, status, answered_at, item_type, meta)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    "u_g2",
                    "矩阵",
                    0,
                    "applied",
                    "2026-08-12T13:00:00+00:00",
                    "open",
                    "{}",
                ),
            )
        )

        before = store._query("SELECT COUNT(*) FROM ability_snapshots")[0][0]
        params = refresh_after_grade("u_g2", store=store, persist_snapshot=True, days=3650)
        assert params is not None
        assert params.learner_id == "u_g2"
        assert len(params.eta) == 3
        after = store._query("SELECT COUNT(*) FROM ability_snapshots")[0][0]
        assert after == before + 1
        row = store._query(
            "SELECT ability_json FROM ability_snapshots ORDER BY id DESC LIMIT 1"
        )[0][0]
        assert "eta" in row and "mastery" in row
        print("GATE2 PASS", "snapshots=", after, "eta=", [round(e.eta, 3) for e in params.eta])
    finally:
        os.environ.pop("TEACHING_DB", None)
        reset_store()
        try:
            os.remove(path)
        except OSError:
            pass


def gate3_domain_boost_selection():
    from modules.capability import weak_domain_boosts, domain_boost_for_kp
    from modules.capability.select import eta_map_from_params
    from modules.capability.params import LearnerParams, DomainEta, MasteryEntry
    from learner.db import reset_store
    from learner.context import bind_learner
    from learner import item_bank

    boosts = weak_domain_boosts({"calc": 1.0, "linalg": -1.0, "prob": 0.0}, scale=0.12)
    assert boosts["linalg"] > boosts["calc"]
    assert abs(boosts["linalg"] - 0.12) < 1e-9

    params = LearnerParams(
        learner_id="x",
        mastery=[MasteryEntry(kp="极限", p_mastery=0.4)],
        eta=[
            DomainEta("calc", 1.0, n_items=3),
            DomainEta("linalg", -1.0, n_items=2),
            DomainEta("prob", 0.0, n_items=0),
        ],
    )
    emap = eta_map_from_params(params)
    assert "prob" not in emap
    b2 = weak_domain_boosts(emap)
    assert domain_boost_for_kp("极限", b2, syllabus_path=SYLLABUS) == b2.get("calc", 0)
    assert domain_boost_for_kp("矩阵", b2, syllabus_path=SYLLABUS) == b2.get("linalg", 0)
    assert b2["linalg"] > b2["calc"]

    store, path = _fresh_store()
    try:
        os.environ["TEACHING_DB"] = path
        reset_store()
        bind_learner("u_g3")
        store.set_mastery(
            "u_g3",
            "极限",
            {"p_mastery": 0.3, "opportunity_count": 1, "is_mastered": False},
        )
        # cultivate 依赖仓外 intervention / heartbeat_summary；stub 后走真实 weak_kp_ranked
        from types import ModuleType
        from unittest.mock import patch

        kl = os.path.join(ROOT, "knowledge-lib")
        if kl not in sys.path:
            sys.path.insert(0, kl)

        iv = ModuleType("intervention")

        class InterventionDecision:
            pass

        def decide_intervention(**_kw):
            return InterventionDecision()

        iv.InterventionDecision = InterventionDecision
        iv.decide_intervention = decide_intervention

        hb = ModuleType("heartbeat_summary")
        hb.extract = lambda *a, **k: {}

        cult = ModuleType("cultivate")
        cult._load_weights = lambda: {
            "math": {"kp_weights": {"极限": 2.0, "矩阵与初等变换": 1.0}}
        }
        cult._uid = lambda: "u_g3"

        with patch.dict(
            sys.modules,
            {"intervention": iv, "heartbeat_summary": hb, "cultivate": cult},
        ):
            ranked = item_bank.weak_kp_ranked("math", limit=5)
        assert isinstance(ranked, list) and len(ranked) >= 1
        assert all(isinstance(x[0], str) and isinstance(x[1], float) for x in ranked)
        print(
            "GATE3 PASS",
            "boosts=",
            {k: round(v, 4) for k, v in boosts.items()},
            "ranked=",
            [(k, round(s, 4)) for k, s in ranked],
        )
    finally:
        os.environ.pop("TEACHING_DB", None)
        reset_store()
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == "__main__":
    which = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    if which in ("1", "gate1", "all"):
        gate1_irt_and_evidence()
    if which in ("2", "gate2", "all"):
        gate2_refresh_after_grade()
    if which in ("3", "gate3", "all"):
        gate3_domain_boost_selection()
    print("ALL REQUESTED GATES PASS")
