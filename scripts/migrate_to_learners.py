#!/usr/bin/env python3
"""将全局 data/* 学员状态迁移到 data/learners/{owner}/ 与 data/public/。

用法:
  python scripts/migrate_to_learners.py --dry-run
  python scripts/migrate_to_learners.py --apply [--owner STAFF_ID]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config
from learner import paths as P
from deliver.dingtalk_users import get_discuss_user_id, load_discuss_user

GLOBAL_STATE_FILES = (
    "weights.json",
    "answer-log.jsonl",
    "difficulty.json",
    "last_push.json",
    "memory_blocks.json",
    "agent_transcript.json",
    "agent_memory.json",
    "recent_kp_picks.json",
    "recent_ability_picks.json",
    "refine-queue.jsonl",
)

LEGACY_USER_IDS = ("wx_123",)


def _resolve_owner(explicit: str) -> str:
    oid = (explicit or config.OWNER_STAFF_ID or get_discuss_user_id() or "").strip()
    if oid:
        return oid
    legacy = load_discuss_user().get("user_id") or ""
    return (legacy or "").strip()


def _remap_answer_log(src: str, dst: str, owner_id: str, dry_run: bool) -> int:
    if not os.path.isfile(src):
        return 0
    changed = 0
    lines_out: list[str] = []
    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                lines_out.append(line)
                continue
            uid = (e.get("user_id") or "").strip()
            if not uid or uid in LEGACY_USER_IDS or uid == config.LEARNER_USER_ID:
                e["user_id"] = owner_id
                changed += 1
            lines_out.append(json.dumps(e, ensure_ascii=False))
    if dry_run:
        return changed
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        for ln in lines_out:
            f.write(ln + "\n")
    return changed


def migrate(*, dry_run: bool, owner: str) -> dict:
    owner_id = _resolve_owner(owner)
    if not owner_id:
        raise SystemExit("无法确定 owner staffId：请设 OWNER_STAFF_ID 或 --owner")

    data_dir = config.DATA_DIR
    learner_dir = os.path.join(P.learners_root(), P.safe_learner_id(owner_id))
    public_dir = P.public_dir()
    report: dict = {
        "owner": owner_id,
        "learner_dir": learner_dir,
        "moved": [],
        "skipped": [],
        "answer_log_remapped": 0,
        "dry_run": dry_run,
    }

    if not dry_run:
        os.makedirs(learner_dir, exist_ok=True)
        os.makedirs(public_dir, exist_ok=True)

    for name in GLOBAL_STATE_FILES:
        src = os.path.join(data_dir, name)
        if not os.path.isfile(src):
            report["skipped"].append(name)
            continue
        if name == "last_push.json":
            dst = os.path.join(public_dir, "last_class.json")
        elif name == "answer-log.jsonl":
            dst = os.path.join(learner_dir, name)
            n = _remap_answer_log(src, dst, owner_id, dry_run)
            report["answer_log_remapped"] = n
            if not dry_run:
                report["moved"].append(f"{name} -> learners/... (remap {n})")
            else:
                report["moved"].append(f"{name} -> learners/... (dry remap {n})")
            continue
        else:
            dst = os.path.join(learner_dir, name)
        if dry_run:
            report["moved"].append(f"{name} -> {os.path.relpath(dst, data_dir)}")
        else:
            shutil.copy2(src, dst)
            report["moved"].append(f"{name} -> {os.path.relpath(dst, data_dir)}")

    arc_src = os.path.join(data_dir, "refine-queue-archive")
    if os.path.isdir(arc_src):
        arc_dst = os.path.join(learner_dir, "refine-queue-archive")
        if dry_run:
            report["moved"].append("refine-queue-archive/ -> learners/...")
        else:
            if os.path.isdir(arc_dst):
                for fn in os.listdir(arc_src):
                    shutil.copy2(os.path.join(arc_src, fn), os.path.join(arc_dst, fn))
            else:
                shutil.copytree(arc_src, arc_dst)
            report["moved"].append("refine-queue-archive/ -> learners/...")

    if not dry_run:
        from learner.roster import upsert_roster

        upsert_roster(owner_id, nick="", source="migrate", status="active")
        idx = {
            "learners": {
                owner_id: {
                    "staff_id": owner_id,
                    "safe_id": P.safe_learner_id(owner_id),
                    "nick": "",
                    "source": "migrate",
                    "status": "active",
                    "enrolled_at": time.time(),
                    "updated_at": time.time(),
                }
            },
            "updated_at": time.time(),
        }
        os.makedirs(P.learners_root(), exist_ok=True)
        with open(P.roster_index_path(), "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)

    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--owner", default="")
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        ap.error("specify --dry-run or --apply")
    rep = migrate(dry_run=bool(args.dry_run and not args.apply), owner=args.owner)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
