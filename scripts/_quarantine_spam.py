# -*- coding: utf-8 -*-
"""一次性脚本：软隔离 2026-07-31 凌晨测试灌库的"未分类" answer-log 条目。

不物理删除；给匹配条目打 `"quarantined": true` 并改写 update_reason，
同时写 data/answer-log-quarantine.jsonl 记录被隔离的 ts 清单。

用法（云端）：
    venv/bin/python3 scripts/_quarantine_spam.py <answer_log_path>
"""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python _quarantine_spam.py <answer-log.jsonl>")
        return 1
    path = sys.argv[1]
    q_path = os.path.join(os.path.dirname(path), "answer-log-quarantine.jsonl")

    # 匹配窗口：2026-07-31 02:59 - 03:42 UTC（测试灌库爆发段）
    start = "2026-07-31T02:59:00+00:00"
    end = "2026-07-31T03:43:00+00:00"

    lines = open(path, encoding="utf-8").readlines()
    out = []
    quarantined = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        ts = str(e.get("ts") or "")
        kp = str(e.get("knowledge_point") or "")
        is_spam = (
            kp == "未分类"
            and start <= ts <= end
        )
        if is_spam:
            e["quarantined"] = True
            orig = e.get("update_reason") or "applied"
            e["update_reason"] = f"{orig}; quarantined: spam"
            quarantined.append(ts)
        out.append(json.dumps(e, ensure_ascii=False))

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    with open(q_path, "w", encoding="utf-8") as f:
        for ts in quarantined:
            f.write(json.dumps({"ts": ts, "quarantined": True,
                                "reason": "test_spam_0731"},
                               ensure_ascii=False) + "\n")

    print(f"隔离 {len(quarantined)} 条 (窗口 {start[:16]}~{end[:16]} UTC)")
    print(f"清单: {q_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
