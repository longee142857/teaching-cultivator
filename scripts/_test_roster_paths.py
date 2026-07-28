"""多人花名册 / paths / ContextVar 验收。"""
from __future__ import annotations

import json
import os
import sys
import tempfile

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
    import learner.paths as P
    import learner.context as C
    import learner.roster as R
    import config as cfg

    td = tempfile.mkdtemp()
    old_data = cfg.DATA_DIR
    cfg.DATA_DIR = td
    # paths 模块在 import 时绑了 DATA_DIR — 需同步
    import importlib
    importlib.reload(P)
    importlib.reload(R)

    # empty staff rejected
    try:
        P.safe_learner_id("")
        check("reject empty staff", False)
    except ValueError:
        check("reject empty staff", True)

    check("safe id", P.safe_learner_id("04022300") == "04022300")

    # no context → error without owner
    cfg.OWNER_STAFF_ID = ""
    try:
        C.current_user_id(allow_owner_fallback=True)
        check("no context no owner", False)
    except C.LearnerIdentityError:
        check("no context no owner", True)

    cfg.OWNER_STAFF_ID = "owner_staff_1"
    check("owner fallback", C.current_user_id() == "owner_staff_1")

    with C.bind_learner("staff_a", binding="personal") as sid:
        check("bind learner", sid == "staff_a" and C.get_learner_id() == "staff_a")
        check("binding personal", C.get_binding() == "personal")
        check("current in bind", C.current_user_id() == "staff_a")
        d = P.ensure_learner_dir()
        check("learner dir", d.endswith(os.path.join("learners", "staff_a")))
        check("weights path under learner", "learners" in P.weights_path() and P.weights_path().endswith("weights.json"))
        check("public class separate", "public" in P.public_last_class_path())

    check("unbind", C.get_learner_id() is None)

    # ensure_learner seeds weights
    ex = os.path.join(td, "weights.example.json")
    with open(ex, "w", encoding="utf-8") as f:
        json.dump({"math": {"kps": {"极限": 1.0}}}, f)
    entry = R.ensure_learner("staff_b", nick="Bob", source="test")
    check("roster entry", entry["staff_id"] == "staff_b" and entry["nick"] == "Bob")
    check("weights seeded", os.path.isfile(P.weights_path("staff_b")))
    check("resolve", R.resolve_learner("staff_b") is not None)
    check("enroll phrase", R.is_enroll_utterance("我想报名培养"))
    check("enroll neg", not R.is_enroll_utterance("选B"))

    # isolation: two learners different dirs
    check(
        "isolation",
        P.learner_dir("staff_a") != P.learner_dir("staff_b"),
    )

    cfg.DATA_DIR = old_data
    importlib.reload(P)
    importlib.reload(R)

    print(f"\npassed={len(PASSED)} failed={len(FAILED)}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
