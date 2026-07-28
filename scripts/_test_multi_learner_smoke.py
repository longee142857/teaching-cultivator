"""多人学员状态隔离冒烟测试。"""
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
    import importlib
    import config as cfg
    import learner.context as C
    import learner.paths as P

    td = tempfile.mkdtemp()
    old_data = cfg.DATA_DIR
    cfg.DATA_DIR = td
    cfg.OWNER_STAFF_ID = "owner1"
    importlib.reload(P)

    ex = os.path.join(td, "weights.example.json")
    with open(ex, "w", encoding="utf-8") as f:
        json.dump({"math": {"kp_weights": {"极限": 0.1}}}, f)

    from learner.roster import ensure_learner
    from learner.weights_ops import bump_kp_weight, load_weights, save_weights

    ensure_learner("learner_a", nick="A")
    ensure_learner("learner_b", nick="B")

    with C.bind_learner("learner_a", binding="personal"):
        w = load_weights()
        w.setdefault("math", {}).setdefault("kp_weights", {})["极限"] = 0.2
        save_weights(w)
        bump_kp_weight("math", "极限", reason="smoke_a")

    with C.bind_learner("learner_b", binding="personal"):
        w2 = load_weights()
        w2.setdefault("math", {}).setdefault("kp_weights", {})["极限"] = 0.5
        save_weights(w2)

    with C.bind_learner("learner_a", binding="personal"):
        wa = load_weights()["math"]["kp_weights"]["极限"]
    with C.bind_learner("learner_b", binding="personal"):
        wb = load_weights()["math"]["kp_weights"]["极限"]

    check("weights isolated", wa != wb, f"a={wa} b={wb}")

    pub = P.public_last_class_path()
    os.makedirs(os.path.dirname(pub), exist_ok=True)
    with open(pub, "w", encoding="utf-8") as f:
        json.dump({"question": "public Q", "subject": "math"}, f)
    with C.bind_learner("learner_a", binding="personal"):
        lp = P.last_push_path()
        with open(lp, "w", encoding="utf-8") as f:
            json.dump({"question": "private Q", "subject": "math"}, f)

    from agent.tools import _load_last_push_question

    with C.bind_learner("learner_a", binding="personal"):
        q = _load_last_push_question()
    check("personal last_push wins", q == "private Q", q)

    os.remove(lp)
    with C.bind_learner("learner_a", binding="personal"):
        q2 = _load_last_push_question()
    check("fallback public class", q2 == "public Q", q2)

    cfg.DATA_DIR = old_data
    importlib.reload(P)

    print(f"\npassed={len(PASSED)} failed={len(FAILED)}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
