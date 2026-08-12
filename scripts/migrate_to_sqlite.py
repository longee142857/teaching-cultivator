"""一次性迁移：月 MD/index、last_push/last_class、answer-log、syllabus → SQLite。

幂等可重复跑（按自然键 / entry 去重）。迁移后关键查询不依赖月 index 权威。
不删除任何旧文件（保留只读/归档）。

用法:
    py -3 scripts/migrate_to_sqlite.py
    py -3 scripts/migrate_to_sqlite.py --data-dir <dir> --db <path>
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from bkt import KCState
except ImportError:  # 独立运行缺 knowledge-system/lib 时回退
    for _rel in (
        os.path.normpath(os.path.join(ROOT, "knowledge-lib")),
        os.path.normpath(os.path.join(ROOT, "../knowledge-system/lib")),
    ):
        if os.path.isdir(_rel) and _rel not in sys.path:
            sys.path.insert(0, _rel)
    from bkt import KCState


def _parse_args(argv: list[str]) -> dict:
    data_dir = None
    db_path = None
    i = 0
    while i < len(argv):
        if argv[i] == "--data-dir" and i + 1 < len(argv):
            data_dir = argv[i + 1]
            i += 2
        elif argv[i] == "--db" and i + 1 < len(argv):
            db_path = argv[i + 1]
            i += 2
        else:
            i += 1
    return {"data_dir": data_dir, "db_path": db_path}


def _read_json(path: str) -> dict:
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _read_jsonl(path: str) -> list[dict]:
    out: list[dict] = []
    try:
        if not os.path.isfile(path):
            return out
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    if isinstance(e, dict):
                        out.append(e)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


def _migrate_syllabus(store, data_dir: str) -> int:
    from learner.db import get_store
    st = get_store() if store is None else store
    count = 0
    for subject in ("math", "comm"):
        syl_path = os.path.join(data_dir, f"syllabus_{subject}.json")
        syl = _read_json(syl_path)
        if not syl:
            continue
        kps = syl.get("kps") or {}
        for l2, meta in kps.items():
            if not isinstance(meta, dict):
                continue
            l1 = str(meta.get("l1") or "")
            st._txn(
                lambda conn, s=subject, l1=l1, l2=l2: conn.execute(
                    "INSERT OR IGNORE INTO knowledge_nodes (id, subject, l1, l2, l3, name, parent_id) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (f"{subject}.{l1}.{l2}", subject, l1, l2, None, str(l2), l1 or None),
                )
            )
            count += 1
            for l3 in meta.get("l3") or []:
                if not isinstance(l3, dict):
                    continue
                nid = str(l3.get("id") or "")
                if not nid:
                    continue
                st._txn(
                    lambda conn, s=subject, nid=nid, l2=l2, l3=l3: conn.execute(
                        "INSERT OR IGNORE INTO knowledge_nodes (id, subject, l1, l2, l3, name, parent_id) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (nid, s, l1, l2, str(l3.get("name") or ""), str(l3.get("name") or ""), f"{s}.{l1}.{l2}"),
                    )
                )
                count += 1
    return count


def _migrate_monthly_md(store, data_dir: str) -> int:
    from learner.db import utc_from_shanghai
    import record_index

    # 云端常用 daily_records（DAILY_RECORD_DIR）；测试/默认多为 daily_export
    record_dir = None
    for name in ("daily_records", "daily_export"):
        p = os.path.join(data_dir, name)
        if not os.path.isdir(p):
            continue
        has_index = any(f.endswith(".index.json") for f in os.listdir(p))
        if has_index or record_dir is None:
            record_dir = p
        if has_index:
            break
    if not record_dir:
        return 0
    pushed = 0
    for fname in sorted(os.listdir(record_dir)):
        if not fname.endswith(".index.json"):
            continue
        month = fname[:7]
        index = record_index.load_index(record_dir, month)
        for e in index.get("entries", []):
            date = str(e.get("date") or "")
            if not date:
                continue
            num = int(e.get("num") or 0)
            if num <= 0:
                continue
            block = record_index.read_entry_at_offset(record_dir, month, int(e.get("char_offset", 0)))
            fields = record_index.parse_entry_fields(block) if block else {}
            question = fields.get("question") or e.get("question") or ""
            if not question:
                continue
            time = str(e.get("time") or "12:00")
            pushed_at = utc_from_shanghai(date, time)
            store.add_push_migrated(
                subject=str(e.get("subject") or "math"),
                question=question,
                answer=fields.get("answer") or "",
                difficulty=str(e.get("difficulty") or ""),
                kp=str(e.get("kp") or ""),
                ref_source=str(e.get("ref_source") or ""),
                learner_id=None,  # 旧 MD 为公共记录
                day=date,
                seq=num,
                pushed_at=pushed_at,
                decision_type="push",
                reason=str(e.get("kp") or ""),
            )
            pushed += 1
    return pushed


def _migrate_last_push_files(store, data_dir: str, owner: str) -> int:
    from learner.db import shanghai_day, utc_from_shanghai

    pushed = 0

    def _one(path: str, learner_id):
        nonlocal pushed
        data = _read_json(path)
        q = (data.get("question") or "").strip()
        if not q:
            return
        subj = str(data.get("subject") or "math")
        # 幂等：同 item + 同 learner 已迁过则跳过
        existing_item = store.find_item_id(subj, q)
        if existing_item and store.push_exists_for_item(existing_item, learner_id):
            return
        ts = data.get("timestamp") or ""
        day = shanghai_day(ts or None)
        seq = store.next_seq_for_day(day)
        pushed_at = ts or utc_from_shanghai(day, "12:00")
        store.add_push_migrated(
            subject=subj,
            question=q,
            answer=str(data.get("answer") or ""),
            difficulty=str(data.get("difficulty") or ""),
            kp=str(data.get("kp") or ""),
            item_form=str(data.get("item_form") or ""),
            ability_goal=str(data.get("ability_goal") or ""),
            ref_source=str(data.get("ref_source") or ""),
            learner_id=learner_id,
            day=day,
            seq=seq,
            pushed_at=pushed_at,
            decision_type="push",
            reason=str(data.get("kp") or ""),
        )
        pushed += 1

    _one(os.path.join(data_dir, "public", "last_class.json"), None)
    _one(os.path.join(data_dir, "last_push.json"), owner or None)

    learners_root = os.path.join(data_dir, "learners")
    if os.path.isdir(learners_root):
        for name in os.listdir(learners_root):
            lp = os.path.join(learners_root, name, "last_push.json")
            if os.path.isfile(lp):
                _one(lp, name)
    return pushed


def _migrate_answer_logs(store, data_dir: str, owner: str) -> int:
    paths: list[str] = []
    root_log = os.path.join(data_dir, "answer-log.jsonl")
    if os.path.isfile(root_log):
        paths.append(root_log)
    learners_root = os.path.join(data_dir, "learners")
    if os.path.isdir(learners_root):
        for name in os.listdir(learners_root):
            p = os.path.join(learners_root, name, "answer-log.jsonl")
            if os.path.isfile(p):
                paths.append(p)

    groups: dict[tuple[str, str], list[dict]] = {}
    inserted = 0
    for path in paths:
        for e in _read_jsonl(path):
            uid = e.get("user_id") or ""
            if not uid:
                # 单用户根日志补 owner
                uid = owner or "wx_123"
            if not store.add_attempt_migrated({**e, "user_id": uid}):
                continue
            inserted += 1
            kp = e.get("knowledge_point") or ""
            if kp and kp != "未分类":
                groups.setdefault((uid, kp), []).append(e)

    # 重放重建 mastery_states（与 BKTLogger.get_kp_mastery 旧回放逻辑一致）
    skip_status = {"pending", "audit"}
    for (uid, kp), entries in groups.items():
        superseded = {str(r.get("supersedes_ts")) for r in entries if r.get("supersedes_ts")}
        kc = KCState()
        for r in entries:
            if r.get("status") in skip_status:
                continue
            if r.get("update_applied") is False:
                continue
            ts = str(r.get("ts") or "")
            if ts in superseded:
                continue
            if not isinstance(r.get("correct"), bool):
                continue
            kc.update(
                bool(r.get("correct")),
                item_type=str(r.get("item_type") or "unknown"),
                credit=r.get("credit"),
                ref_id=str(r.get("ref_id") or ""),
                force=True,
            )
        store.set_mastery(uid, kp, kc.to_dict())
    return inserted


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    opts = _parse_args(argv)

    if opts["data_dir"]:
        import config as _cfg
        _cfg.DATA_DIR = opts["data_dir"]

    from learner.db import get_store, reset_store
    reset_store()
    store = get_store(opts["db_path"])

    data_dir = opts["data_dir"] or os.path.join(ROOT, "data")
    owner = os.environ.get("OWNER_STAFF_ID", "") or os.environ.get("LEARNER_USER_ID", "") or ""

    counts = {}
    counts["knowledge_nodes"] = _migrate_syllabus(store, data_dir)
    counts["pushes_from_md"] = _migrate_monthly_md(store, data_dir)
    counts["pushes_from_lastpush"] = _migrate_last_push_files(store, data_dir, owner)
    counts["attempts"] = _migrate_answer_logs(store, data_dir, owner)

    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
