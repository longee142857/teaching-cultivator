"""方案 A：超过一天未作答 → silent，保留 id，隔绝学习态写入。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"OK  {name}")
    else:
        FAILED.append(name)
        print(f"FAIL {name} {detail}")


def main() -> int:
    import importlib
    import config as cfg
    import learner.context as C
    import learner.paths as P
    import learner.roster as R
    from learner.weights_ops import load_weights, save_weights

    td = tempfile.mkdtemp()
    old_data = cfg.DATA_DIR
    old_owner = getattr(cfg, "OWNER_STAFF_ID", "")
    old_env = os.environ.get("SILENT_AFTER_SEC")
    cfg.DATA_DIR = td
    cfg.OWNER_STAFF_ID = "owner1"
    os.environ["SILENT_AFTER_SEC"] = "3600"  # 1h for test
    importlib.reload(P)
    importlib.reload(R)

    ex = os.path.join(td, "weights.example.json")
    with open(ex, "w", encoding="utf-8") as f:
        json.dump({"math": {"kp_weights": {"极限": 0.1}}}, f)

    entry = R.ensure_learner("u_silent", nick="S", source="auto")
    check("new active", entry.get("status") == "active")
    check("no last_answer", entry.get("last_answer_at") in (None, 0))

    # 私聊 upsert 不得把 silent 刷回 active
    R.upsert_roster("u_silent", nick="S2", source="dm", status=None)
    # force silent via old enrolled_at
    data = json.load(open(P.roster_index_path(), encoding="utf-8"))
    data["learners"]["u_silent"]["enrolled_at"] = time.time() - 7200
    data["learners"]["u_silent"]["last_answer_at"] = None
    data["learners"]["u_silent"]["status"] = "active"
    with open(P.roster_index_path(), "w", encoding="utf-8") as f:
        json.dump(data, f)

    flipped = R.refresh_silent_status("u_silent")
    check("flip silent", flipped and flipped.get("status") == "silent", str(flipped))

    R.upsert_roster("u_silent", nick="chat", source="dm")  # preserve
    again = R.resolve_learner("u_silent")
    check("dm preserves silent", again and again.get("status") == "silent", str(again))

    with C.bind_learner("u_silent", binding="personal"):
        check("gate blocks", not R.allows_learning_writes())
        w = load_weights()
        w["math"]["kp_weights"]["极限"] = 0.99
        ok = save_weights(w)
        check("weights blocked", ok is False)
        w2 = load_weights()
        check("weights unchanged", abs(float(w2["math"]["kp_weights"]["极限"]) - 0.1) < 1e-9)

    # schedule still allowed
    with C.bind_learner("owner1", binding="schedule"):
        check("schedule allows", R.allows_learning_writes())

    # answer wakes
    woken = R.mark_answered("u_silent")
    check("wake active", woken and woken.get("status") == "active")
    check("last_answer set", isinstance(woken.get("last_answer_at"), (int, float)))

    with C.bind_learner("u_silent", binding="personal"):
        check("gate open after answer", R.allows_learning_writes())
        w = load_weights()
        w["math"]["kp_weights"]["极限"] = 0.42
        check("weights write ok", save_weights(w) is True)
        check("weights updated", abs(float(load_weights()["math"]["kp_weights"]["极限"]) - 0.42) < 1e-9)

    # memory sync blocked while silent
    R.upsert_roster("u_mem", source="auto", status="active")
    data = json.load(open(P.roster_index_path(), encoding="utf-8"))
    data["learners"]["u_mem"]["enrolled_at"] = time.time() - 9000
    data["learners"]["u_mem"]["last_answer_at"] = None
    with open(P.roster_index_path(), "w", encoding="utf-8") as f:
        json.dump(data, f)
    R.refresh_silent_status("u_mem")

    pub = P.public_last_class_path()
    os.makedirs(os.path.dirname(pub), exist_ok=True)
    with open(pub, "w", encoding="utf-8") as f:
        json.dump({"question": "PUBLIC_Q_SHOULD_NOT_SYNC", "subject": "math", "kp": "极限"}, f)

    from agent.memory_blocks import MemoryBlocks

    with C.bind_learner("u_mem", binding="personal"):
        mb = MemoryBlocks(staff_id="u_mem")
        mb.refresh_from_last_push()
        mb.save()
        preview = (mb._data.get("active_question") or {}).get("preview") or ""
        check("silent no public sync", "PUBLIC_Q" not in preview, preview)

    # roster paths regression: enroll phrase still works
    check("enroll phrase", R.is_enroll_utterance("报名培养"))

    # restore
    cfg.DATA_DIR = old_data
    cfg.OWNER_STAFF_ID = old_owner
    if old_env is None:
        os.environ.pop("SILENT_AFTER_SEC", None)
    else:
        os.environ["SILENT_AFTER_SEC"] = old_env
    importlib.reload(P)
    importlib.reload(R)

    print(f"\npassed={len(PASSED)} failed={len(FAILED)}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
