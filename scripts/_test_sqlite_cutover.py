# -*- coding: utf-8 -*-
"""BIG-TEACH-013 SQLite 切换验收（临时 DB，不污染生产库）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config as config_mod
from learner import db as db_mod
from learner.db import get_store, reset_store, shanghai_day, now_utc_iso, utc_from_shanghai
from learner.bkt_db import DbBKTLogger
from learner.context import bind_learner
from bkt import KCState

_fails = 0


def check(cond: bool, msg: str) -> None:
    global _fails
    safe = msg.encode("ascii", "backslashreplace").decode("ascii")
    print(f"[{'PASS' if cond else 'FAIL'}] {safe}")
    if not cond:
        _fails += 1


SCHEMA_TABLES = [
    "subjects", "knowledge_nodes", "items", "item_kcs", "pushes",
    "attempts", "mastery_states", "ability_snapshots",
]


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        with patch.object(config_mod, "DATA_DIR", td):
            reset_store()
            store = get_store()

            _test_schema(store)
            _test_push_and_active(store)
            _test_today_ordering(store)
            _test_cultivate_record(store, td)
            _test_grade_links(store)
            _test_export_and_db_reads(store, td)
            _test_migration_idempotent(td)
            # 迁移后重新取主 store，避免握着已关闭实例
            store = get_store()
            _test_system_api_whitelist()
            _test_gate2_corrections(store)

    print("\n" + "=" * 60)
    if _fails:
        print(f"DONE with {_fails} FAIL(s)")
        return 1
    print("ALL SQLITE CUTOVER TESTS PASSED")
    return 0


def _test_gate2_corrections(store) -> None:
    print("\n== 8. Gate2 CORRECTION: record fail raises; pending push_id; no latest fallback ==")
    from cultivate import record
    from intervention import InterventionDecision
    from learner.bkt_db import DbBKTLogger

    # P0: record_push 失败必须向上抛，不得静默
    class Boom(Exception):
        pass

    raised = False
    try:
        with patch.object(store, "record_push", side_effect=Boom("db down")):
            with patch("learner.db.get_store", return_value=store):
                with bind_learner("g2", binding="schedule"):
                    decision = InterventionDecision(
                        "push", "basic", "函数极限与连续:test", 3
                    )
                    try:
                        record("math", "Q_GATE2_FAIL", decision, answer="A")
                    except Boom:
                        raised = True
    except Exception as e:
        check(False, f"unexpected outer error: {e}")
        raised = False
    check(raised, "record() re-raises when record_push fails")

    # pending 作答带 push_id → list_today answered
    q = "Gate2 pending Q\nA.1\nB.2"
    with bind_learner("penduser", binding="personal"):
        pid = store.record_push(
            subject="math", question=q, answer="A", difficulty="basic",
            kp="函数极限与连续", learner_id="penduser", pushed_at=now_utc_iso(),
        )
        from grade import grade_answer

        def _llm(system, user, task_type="grade", *a, **kw):
            if task_type == "verify_grade":
                return json.dumps({"agrees": True, "confidence": 0.2, "reasoning": "unsure"},
                                  ensure_ascii=False)
            return json.dumps({"verdict": "correct", "confidence": 0.3,
                               "explanation": "low"}, ensure_ascii=False)

        with patch("grade.call_llm", side_effect=_llm), \
             patch("learner.kp_registry.normalize_kp_for_grade", return_value="函数极限与连续"), \
             patch("learner.weights_ops.bump_kp_weight"), \
             patch("learner.weights_ops.decay_kp_weight"):
            r = grade_answer(q, "A", kp_name="函数极限与连续", subject="math")
        check(r.status == "pending", f"pending status got {r.status}")
        atts = [a for a in store.get_attempts("penduser") if a.get("push_id") == pid]
        check(len(atts) >= 1, "pending attempt has matching push_id")
        today = store.list_today_pushes("penduser", shanghai_day(None))
        hit = [t for t in today if t.get("push_id") == pid]
        check(hit and hit[0].get("answered") is True, "pending counts as answered for today")

    # bkt_db: 无 push_id 时不挂 latest
    other = store.record_push(
        subject="math", question="OTHER LATEST", answer="x",
        difficulty="basic", kp="函数极限与连续", learner_id="nofall",
        pushed_at=now_utc_iso(),
    )
    logger = DbBKTLogger(store)
    kc = KCState()
    logger.record(
        "nofall", "函数极限与连续", True, kc,
        subject="math", item_type="mcq", status="applied",
        push_id=None, item_id=None,
    )
    atts2 = store.get_attempts("nofall")
    check(atts2 and atts2[-1].get("push_id") is None,
          "no silent attach to latest push")
    check(other > 0, "latest push id exists but unused")

    from agent.pi_rpc_bridge import TOOL_PROGRESS
    check("write_feedback" in TOOL_PROGRESS, "write_feedback progress tip")


def _test_schema(store) -> None:
    print("\n== 1. schema ==")
    tables = {r[0] for r in store._query(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in SCHEMA_TABLES:
        check(t in tables, f"table {t}")
    check(store.count_rows("subjects") >= 3, "subjects seeded")
    check(store.count_rows("ability_snapshots") >= 0, "ability_snapshots present")


def _test_push_and_active(store) -> None:
    print("\n== 2. push -> items+pushes (transaction), get_active_question ==")
    pub_pid = store.record_push(
        subject="math", question="公共课：求极限", answer="1",
        difficulty="basic", kp="函数极限与连续", learner_id=None,
        pushed_at=utc_from_shanghai("2099-01-01", "09:00"),
    )
    per_pid = store.record_push(
        subject="comm", question="个人题：香农公式", answer="C",
        difficulty="intermediate", kp="香农公式", learner_id="alice",
        pushed_at=utc_from_shanghai("2099-01-01", "15:00"),
    )
    check(store.count_rows("items") >= 2, "items written")
    check(store.count_rows("pushes") >= 2, "pushes written")
    check(pub_pid > 0 and per_pid > 0, "push ids returned")

    # 公共可见：bob 只见公共题（个人题不可见）
    lp_pub = store.get_latest_push("bob")
    check(lp_pub is not None and lp_pub["question"] == "公共课：求极限",
          "latest visible to bob = public push")
    # alice 自己：最新是 comm 个人题
    lp_alice = store.get_latest_push("alice")
    check(lp_alice is not None and lp_alice["question"] == "个人题：香农公式", "alice latest = personal")

    with bind_learner("alice", binding="personal"):
        from agent.tools import get_active_question as tool_aq
        text = tool_aq()
        check("香农公式" in text and "comm" in text, f"tool get_active_question: {text[:60]!r}")

        from learner.active_question import get_active_question as raw_aq
        aq = raw_aq("alice")
        check(aq.get("found") is True and aq.get("kp") == "香农公式", "raw get_active_question kp")


def _test_today_ordering(store) -> None:
    print("\n== 3. list_today_questions: answered + 非未答优先 ==")
    today = shanghai_day(None)
    old_pid = store.record_push(
        subject="math", question="旧未答：极限题", answer="",
        difficulty="basic", kp="函数极限与连续", learner_id="learnerX",
        pushed_at=utc_from_shanghai(today, "09:00"),
    )
    new_pid = store.record_push(
        subject="comm", question="新已答：香农", answer="C",
        difficulty="basic", kp="香农公式", learner_id="learnerX",
        pushed_at=utc_from_shanghai(today, "15:00"),
    )
    # 作答新题 → 新题 answered=True
    store.add_attempt_entry({
        "ts": now_utc_iso(), "user_id": "learnerX", "knowledge_point": "香农公式",
        "correct": True, "item_type": "mcq", "status": "applied", "push_id": new_pid,
    })
    rows = store.list_today_pushes("learnerX", today)
    check(len(rows) == 2, f"today 2 pushes, got {len(rows)}")
    check(rows[0]["question"] == "旧未答：极限题" and rows[0]["answered"] is False,
          "old unanswered first (time ASC)")
    check(rows[1]["question"] == "新已答：香农" and rows[1]["answered"] is True,
          "new answered second (time ASC)")

    with bind_learner("learnerX", binding="personal"):
        from agent.tools import list_today_questions
        text = list_today_questions()
        i_old = text.find("09:00")   # 旧未答（推送时间早）
        i_new = text.find("15:00")   # 新已答（推送时间晚）
        check(i_old != -1 and i_new != -1 and i_old < i_new,
              "tool text 未答在前（时间序，非未答优先）")
        check("未作答" in text and "已作答" in text, "tool text has answered flags")


def _test_cultivate_record(store, td) -> None:
    print("\n== 3b. cultivate.record 推送落库（items+pushes）==")
    import cultivate as cultivate_mod
    from intervention import InterventionDecision
    export_dir = os.path.join(td, "export_out2")
    with patch.object(cultivate_mod, "DAILY_RECORD_DIR", export_dir):
        decision = InterventionDecision("push", "basic", "函数极限与连续: 测试", 3)
        cultivate_mod._last_item_form = "mcq"
        cultivate_mod._last_ref_source = "2026年真题"

        # 定时公共课 → 公共 push
        with bind_learner("pub_owner", binding="schedule"):
            cultivate_mod.record("math", "推送题：求极限", decision, answer="1", ref_source="2026年真题")
        item_id = store.find_item_id("math", "推送题：求极限")
        check(item_id is not None and store.push_exists_for_item(item_id, None),
              "公共课 record 落库公共 push")

        # 私聊自出题 → 个人 push
        with bind_learner("learnerY", binding="personal"):
            cultivate_mod.record("comm", "个人题：信号", decision, answer="A")
        item_id2 = store.find_item_id("comm", "个人题：信号")
        check(item_id2 is not None and store.push_exists_for_item(item_id2, "learnerY"),
              "私聊 record 落库个人 push")

    check(store.count_rows("items") >= 3, "items >=3 (含 cultivate.record)")


def _test_grade_links(store) -> None:
    print("\n== 4. grade_answer -> attempt 联 push_id；applied 更新 mastery_states ==")
    q = "下列正确的是\nA. 1\nB. 2\nC. 3\nD. 4"
    with bind_learner("grader", binding="personal"):
        pid = store.record_push(
            subject="math", question=q, answer="A", difficulty="basic",
            kp="函数极限与连续", learner_id="grader",
            pushed_at=now_utc_iso(),
        )
        from grade import grade_answer

        def _llm(system, user, task_type="grade", *a, **kw):
            if task_type == "verify_grade":
                return json.dumps({"agrees": True, "confidence": 0.9, "reasoning": "ok"},
                                  ensure_ascii=False)
            return json.dumps({"verdict": "correct", "confidence": 0.95,
                               "explanation": "ok"}, ensure_ascii=False)

        with patch("grade.call_llm", side_effect=_llm), \
             patch("learner.kp_registry.normalize_kp_for_grade", return_value="函数极限与连续"), \
             patch("learner.weights_ops.bump_kp_weight"), \
             patch("learner.weights_ops.decay_kp_weight"):
            r = grade_answer(q, "A", kp_name="函数极限与连续", subject="math")
        check(r.status == "applied", f"grade applied, got {r.status}")
        attempts = store.get_attempts("grader")
        check(len(attempts) == 1, "one attempt written")
        check(attempts[0].get("push_id") == pid, f"attempt linked push_id {pid}")
        check(attempts[0].get("correct") is True, "attempt correct=True")
        st = store.get_mastery("grader", "函数极限与连续")
        check(st is not None and st.get("opportunity_count", 0) >= 1,
              "mastery_states updated")


def _test_export_and_db_reads(store, td) -> None:
    print("\n== 5. MD 导出可读；运行时读路径不依赖 MD 权威 ==")
    from scripts.export_daily_md import export_month
    out = os.path.join(td, "export_out")
    os.makedirs(out, exist_ok=True)
    n = export_month("2099-01", out_dir=out)
    md_path = os.path.join(out, "2099-01.md")
    check(n >= 2, f"exported {n} entries")
    check(os.path.isfile(md_path), "md file exists")
    with open(md_path, encoding="utf-8") as f:
        content = f.read()
    check("## 2099-01-01" in content and "### 题目" in content, "md readable format")

    # 删掉 MD/index 后，list_recent_entries / find_record_entry 仍走 DB
    idx_path = os.path.join(out, "2099-01.index.json")
    if os.path.isfile(idx_path):
        os.remove(idx_path)
    with bind_learner("alice", binding="personal"):
        from agent.tools import list_recent_entries, find_record_entry
        txt = list_recent_entries(days=30)
        check("香农" in txt or "极限" in txt, f"list_recent_entries from DB: {txt[:60]!r}")
        found = find_record_entry("2099-01-01")
        check("题目" in found, f"find_record_entry from DB: {found[:50]!r}")


def _test_migration_idempotent(td) -> None:
    print("\n== 6. 迁移幂等；迁移后查询不依赖月 index ==")
    sample = os.path.join(td, "sample")
    os.makedirs(os.path.join(sample, "daily_export"), exist_ok=True)
    os.makedirs(os.path.join(sample, "public"), exist_ok=True)
    os.makedirs(os.path.join(sample, "learners", "alice"), exist_ok=True)

    md_text = (
        "## 2026-06-01 09:00 #1\n"
        "### 题目\n"
        "**math · basic**\n\n"
        "求极限。\n\n"
        "### 解答\n1\n\n"
        "### 出题逻辑\n"
        "- 决策类型：push\n"
        "- 决策原因：函数极限与连续\n"
        "---\n"
    )
    with open(os.path.join(sample, "daily_export", "2026-06.md"), "w", encoding="utf-8") as f:
        f.write(md_text)
    idx = {
        "month": "2026-06", "file": "2026-06.md",
        "entries": [{
            "date": "2026-06-01", "time": "09:00", "num": 1,
            "subject": "math", "difficulty": "basic",
            "kp": "函数极限与连续", "ref_source": "", "char_offset": 0,
        }],
    }
    with open(os.path.join(sample, "daily_export", "2026-06.index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    lp = {
        "subject": "comm", "difficulty": "basic",
        "question": "简述香农公式。", "answer": "C=Blog2(1+S/N)",
        "kp": "香农公式", "timestamp": "2026-06-02T15:00:00",
    }
    with open(os.path.join(sample, "last_push.json"), "w", encoding="utf-8") as f:
        json.dump(lp, f, ensure_ascii=False)
    with open(os.path.join(sample, "public", "last_class.json"), "w", encoding="utf-8") as f:
        json.dump({"subject": "math", "question": "公共：数列极限", "kp": "函数极限与连续",
                   "timestamp": "2026-06-03T09:00:00"}, f, ensure_ascii=False)
    alog = {
        "ts": "2026-06-01T01:00:00+00:00", "user_id": "alice",
        "knowledge_point": "函数极限与连续", "correct": False, "item_type": "mcq",
        "mastery_before": 0.2, "mastery_after": 0.15,
        "update_applied": True, "status": "applied",
        "state": {"p_mastery": 0.15, "opportunity_count": 1},
    }
    with open(os.path.join(sample, "learners", "alice", "answer-log.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(alog, ensure_ascii=False) + "\n")
    syl = {"subject": "数学一", "l1": {"calc": {"name": "高等数学"}},
           "kps": {"函数极限与连续": {"l1": "calc", "l3": []}}}
    with open(os.path.join(sample, "syllabus_math.json"), "w", encoding="utf-8") as f:
        json.dump(syl, f, ensure_ascii=False)

    mig_db = os.path.join(td, "mig.db")
    import scripts.migrate_to_sqlite as mig
    saved = config_mod.DATA_DIR
    try:
        rc = mig.main(["--data-dir", sample, "--db", mig_db])
        check(rc == 0, "migration exit 0")
        s = get_store(mig_db)
        pushes1 = s.count_rows("pushes")
        attempts1 = s.count_rows("attempts")
        nodes1 = s.count_rows("knowledge_nodes")
        check(pushes1 >= 3, f"pushes migrated >=3, got {pushes1}")
        check(attempts1 >= 1, f"attempts migrated >=1, got {attempts1}")
        check(nodes1 >= 1, f"knowledge_nodes migrated >=1, got {nodes1}")
        lp = s.get_latest_push(None)
        check(lp is not None and lp["subject"] == "math" and "公共" in lp["question"],
              f"latest public from last_class: {lp and lp['question']!r}")
        st = s.get_mastery("alice", "函数极限与连续")
        check(st is not None, "mastery rebuilt from answer-log")

        # 幂等重跑
        mig.main(["--data-dir", sample, "--db", mig_db])
        s2 = get_store(mig_db)
        check(s2.count_rows("pushes") == pushes1, "idempotent pushes")
        check(s2.count_rows("attempts") == attempts1, "idempotent attempts")

        # 删除月 index 后关键查询仍工作（不依赖 index 权威）
        os.remove(os.path.join(sample, "daily_export", "2026-06.index.json"))
        lp2 = s2.get_latest_push(None)
        check(lp2 is not None and lp2["subject"] == "math", "query works without month index")
    finally:
        config_mod.DATA_DIR = saved
        # 只丢掉迁移用的 store，勿 reset 整表缓存，否则后续门闩仍握着已关闭的主 store。
        with db_mod._store_lock:
            dead = [p for p in list(db_mod._store) if os.path.normpath(p) == os.path.normpath(mig_db)]
            for p in dead:
                try:
                    db_mod._store[p].close()
                except Exception:
                    pass
                db_mod._store.pop(p, None)


def _test_system_api_whitelist() -> None:
    print("\n== 7. system_api 白名单 + docs + pi_rpc_bridge ==")
    from deliver.system_api import WHITELIST, _READ_TOOLS
    check("list_today_questions" in WHITELIST, "WHITELIST has list_today_questions")
    check("list_today_questions" in _READ_TOOLS, "READ_TOOLS has list_today_questions")
    from agent.pi_rpc_bridge import TOOL_PROGRESS
    check("list_today_questions" in TOOL_PROGRESS, "pi_rpc_bridge progress")

    docs = [
        os.path.join(ROOT, "docs", "system-api.md"),
        os.path.join(ROOT, "docs", "pi-tools-whitelist.md"),
    ]
    for d in docs:
        if not os.path.isfile(d):
            check(False, f"missing doc {d}")
            continue
        with open(d, encoding="utf-8") as f:
            check("list_today_questions" in f.read(), f"doc mentions list_today_questions: {os.path.basename(d)}")


if __name__ == "__main__":
    raise SystemExit(main())
