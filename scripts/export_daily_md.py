"""从 SQLite 导出与现格式兼容的 YYYY-MM.md（+ 可选 index.json）。

BIG-TEACH-013：月 MD 仅为只读导出；运行时读路径走 DB。
导出失败不得回滚已成功的 DB 事务（调用方记录日志即可）。
"""
from __future__ import annotations

import json
import os
import sys


def _entry_block(day: str, time: str, seq: int, subject: str, difficulty: str,
                 question: str, answer: str, decision_type: str,
                 reason: str, ref_source: str) -> str:
    block = (
        f"## {day} {time} #{seq}\n"
        f"### 题目\n"
        f"**{subject} · {difficulty}**\n\n"
        f"{question}\n\n"
    )
    if answer:
        block += f"### 解答\n{answer}\n\n"
    block += "### 出题逻辑\n"
    block += f"- 决策类型：{decision_type}\n"
    block += f"- 决策原因：{reason}\n"
    if ref_source:
        block += f"- 参考来源：{ref_source}\n"
    block += "---\n"
    return block


def export_month(month: str, *, db_path: str | None = None, out_dir: str | None = None) -> int:
    """导出某月（YYYY-MM）MD 到 out_dir（默认 DAILY_RECORD_DIR）。返回条目数。"""
    from learner.db import get_store

    month = (month or "").strip()
    if not month or len(month) != 7 or "-" not in month:
        raise ValueError(f"month 应为 YYYY-MM: {month!r}")

    store = get_store(db_path) if db_path else get_store()
    pushes = store.list_month_pushes(month)
    if not pushes:
        return 0

    out_dir = out_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "daily_export")
    os.makedirs(out_dir, exist_ok=True)

    blocks: list[str] = []
    entries: list[dict] = []
    char_offset = 0
    for p in pushes:
        block = _entry_block(
            day=p.get("day", ""),
            time=p.get("time", ""),
            seq=p.get("seq", 1),
            subject=p.get("subject", ""),
            difficulty=p.get("difficulty", ""),
            question=p.get("question", ""),
            answer=p.get("answer", ""),
            decision_type=p.get("decision_type", ""),
            reason=p.get("reason", ""),
            ref_source=p.get("ref_source", ""),
        )
        prefix = "" if char_offset == 0 else "\n"
        full = prefix + block
        # ## 行起点（跳过前缀换行）
        entry_offset = char_offset + len(prefix)
        entries.append({
            "date": p.get("day", ""),
            "time": p.get("time", ""),
            "num": p.get("seq", 1),
            "subject": p.get("subject", ""),
            "difficulty": p.get("difficulty", ""),
            "kp": p.get("kp", ""),
            "ref_source": p.get("ref_source", ""),
            "char_offset": entry_offset,
        })
        blocks.append(full)
        char_offset += len(full)

    md_path = os.path.join(out_dir, f"{month}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("".join(blocks))

    index_path = os.path.join(out_dir, f"{month}.index.json")
    index = {
        "month": month,
        "file": f"{month}.md",
        "entries": entries,
    }
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return len(entries)


def export_all(db_path: str | None = None, out_dir: str | None = None) -> dict[str, int]:
    """导出所有有数据月份。返回 {month: count}。"""
    from learner.db import get_store
    store = get_store(db_path) if db_path else get_store()
    months: set[str] = set()
    for p in store.list_month_pushes(""):
        day = p.get("day") or ""
        if len(day) >= 7:
            months.add(day[:7])
    out: dict[str, int] = {}
    for m in sorted(months):
        out[m] = export_month(m, db_path=db_path, out_dir=out_dir)
    return out


if __name__ == "__main__":
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)
    if len(sys.argv) > 1 and sys.argv[1] in ("--all", "all"):
        counts = export_all()
        print(json.dumps(counts, ensure_ascii=False))
    else:
        month = sys.argv[1] if len(sys.argv) > 1 else ""
        if not month:
            print("用法: py -3 scripts/export_daily_md.py YYYY-MM 或 --all")
            sys.exit(2)
        n = export_month(month)
        print(f"exported {month}: {n} entries")
