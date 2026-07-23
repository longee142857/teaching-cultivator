"""按月题目记录 + 侧车索引。

文件布局（DAILY_RECORD_DIR 下）:
  2026-07.md              当月 Markdown 正文
  2026-07.index.json      侧车索引（char_offset 可 seek 单条）

索引条目字段:
  date, time, num, subject, difficulty, kp, ref_source, char_offset
"""
from __future__ import annotations

import datetime
import json
import os
import re
from typing import Any


HEADER_RE = re.compile(
    r"^##\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+#(\d+)\s*$",
    re.MULTILINE,
)
ENTRY_SPLIT_RE = re.compile(r"\n(?=## \d{4}-\d{2}-\d{2})")


def month_of(date_str: str) -> str:
    """YYYY-MM-DD → YYYY-MM"""
    return date_str[:7]


def month_md_path(record_dir: str, month: str) -> str:
    return os.path.join(record_dir, f"{month}.md")


def month_index_path(record_dir: str, month: str) -> str:
    return os.path.join(record_dir, f"{month}.index.json")


def load_index(record_dir: str, month: str) -> dict[str, Any]:
    path = month_index_path(record_dir, month)
    if not os.path.isfile(path):
        return {"month": month, "file": f"{month}.md", "entries": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"month": month, "file": f"{month}.md", "entries": []}
        data.setdefault("month", month)
        data.setdefault("file", f"{month}.md")
        data.setdefault("entries", [])
        return data
    except (OSError, json.JSONDecodeError):
        return {"month": month, "file": f"{month}.md", "entries": []}


def save_index(record_dir: str, index: dict[str, Any]) -> None:
    month = index.get("month") or "unknown"
    os.makedirs(record_dir, exist_ok=True)
    path = month_index_path(record_dir, month)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        f.write("\n")


def append_index_entry(record_dir: str, entry: dict[str, Any]) -> None:
    """追加一条索引；按 (date, num) 去重覆盖。"""
    month = month_of(entry["date"])
    index = load_index(record_dir, month)
    entries = index["entries"]
    key = (entry["date"], int(entry["num"]))
    replaced = False
    for i, e in enumerate(entries):
        if (e.get("date"), int(e.get("num", 0))) == key:
            entries[i] = entry
            replaced = True
            break
    if not replaced:
        entries.append(entry)
    entries.sort(key=lambda e: (e.get("date", ""), int(e.get("num", 0)), e.get("time", "")))
    index["entries"] = entries
    save_index(record_dir, index)


def file_char_size(path: str) -> int:
    """UTF-8 字符偏移（与 Python 字符串索引一致，非字节）。"""
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as f:
        return len(f.read())


def ensure_trailing_blank(path: str) -> None:
    """若文件非空且不以 \\n\\n 结尾，补空行，避免 ---## 粘连。"""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        tail_n = min(4, size)
        f.seek(-tail_n, os.SEEK_END)
        tail = f.read()
    if not tail.endswith(b"\n\n"):
        with open(path, "ab") as f:
            if not tail.endswith(b"\n"):
                f.write(b"\n\n")
            else:
                f.write(b"\n")


def count_today_entries(record_dir: str, today: str) -> int:
    """数当月文件里今天已有的 ## 标题数。"""
    month = month_of(today)
    path = month_md_path(record_dir, month)
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return sum(1 for line in text.split("\n") if line.startswith(f"## {today}"))


def parse_entry_meta(block: str, char_offset: int = 0) -> dict[str, Any] | None:
    """从单条 markdown block 抽索引元数据。"""
    m = HEADER_RE.search(block)
    if not m:
        return None
    date, time, num = m.group(1), m.group(2), int(m.group(3))
    subject, difficulty = "", ""
    sm = re.search(r"\*\*(\w+)\s*·\s*(\w+)\*\*", block)
    if sm:
        subject, difficulty = sm.group(1), sm.group(2)
    kp = ""
    km = re.search(r"决策原因：(.+)", block)
    if km:
        reason = km.group(1).strip()
        kp = reason.split(":")[0].strip() if ":" in reason else reason
        if len(kp) > 80:
            kp = kp[:80]
    ref_source = ""
    rm = re.search(r"参考来源：(.+)", block)
    if rm:
        ref_source = rm.group(1).strip()
    return {
        "date": date,
        "time": time,
        "num": num,
        "subject": subject,
        "difficulty": difficulty,
        "kp": kp,
        "ref_source": ref_source,
        "char_offset": char_offset,
    }


def parse_entry_fields(block: str) -> dict[str, Any]:
    """解析单条正文为 agent 用字段。"""
    result: dict[str, Any] = {"raw": block}
    m = re.search(r"\*\*(\w+)\s*·\s*(\w+)\*\*", block)
    if m:
        result["subject"] = m.group(1)
        result["difficulty"] = m.group(2)
    m = re.search(r"### 题目\n(?:\*\*.*?\*\*\n)?(.*?)(?=\n### |\Z)", block, re.DOTALL)
    if m:
        result["question"] = m.group(1).strip()
    m = re.search(r"### 解答\n(.*?)(?=\n### |\Z)", block, re.DOTALL)
    if m:
        result["answer"] = m.group(1).strip()
    meta = parse_entry_meta(block)
    if meta:
        result["date"] = meta["date"]
        result["time"] = meta["time"]
        result["num"] = meta["num"]
        result["kp"] = meta["kp"]
        result["ref_source"] = meta["ref_source"]
    return result


def read_entry_at_offset(record_dir: str, month: str, char_offset: int) -> str | None:
    path = month_md_path(record_dir, month)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if char_offset < 0 or char_offset >= len(text):
        return None
    chunk = text[char_offset:]
    parts = ENTRY_SPLIT_RE.split(chunk.lstrip("\n") if char_offset == 0 else chunk)
    # char_offset 指向条目起点时，chunk 本身应以 ## 开头
    if chunk.lstrip("\n").startswith("## "):
        block = chunk if chunk.startswith("## ") else chunk.lstrip("\n")
        # 截到下一条之前
        nxt = re.search(r"\n## \d{4}-\d{2}-\d{2}", block[1:])
        if nxt:
            block = block[: nxt.start() + 1]
        return block.strip()
    if parts:
        return parts[0].strip()
    return None


def find_entry(record_dir: str, date: str, num: int = 0) -> dict[str, Any] | None:
    """按日期（+可选 num）定位；num=0 取该日最后一条。"""
    month = month_of(date)
    index = load_index(record_dir, month)
    candidates = [e for e in index.get("entries", []) if e.get("date") == date]
    if not candidates:
        # 无索引时 fallback：扫月文件
        return _find_entry_scan(record_dir, date, num)
    if num > 0:
        match = next((e for e in candidates if int(e.get("num", 0)) == num), None)
    else:
        match = max(candidates, key=lambda e: int(e.get("num", 0)))
    if not match:
        return None
    block = read_entry_at_offset(record_dir, month, int(match.get("char_offset", 0)))
    if not block:
        return _find_entry_scan(record_dir, date, num)
    return parse_entry_fields(block)


def _find_entry_scan(record_dir: str, date: str, num: int = 0) -> dict[str, Any] | None:
    month = month_of(date)
    path = month_md_path(record_dir, month)
    # 兼容旧单文件
    legacy = os.path.join(record_dir, "每日题目记录.md")
    paths = [p for p in (path, legacy) if os.path.isfile(p)]
    for p in paths:
        with open(p, encoding="utf-8") as f:
            text = f.read()
        blocks = ENTRY_SPLIT_RE.split(text.strip())
        day = []
        for b in blocks:
            m = HEADER_RE.search(b)
            if m and m.group(1) == date:
                day.append((int(m.group(3)), b))
        if not day:
            continue
        if num > 0:
            hit = next((b for n, b in day if n == num), None)
        else:
            hit = max(day, key=lambda x: x[0])[1]
        if hit:
            return parse_entry_fields(hit)
    return None


def latest_entry(record_dir: str) -> dict[str, Any] | None:
    """取全局最新一条（按当月/上月索引）。"""
    today = datetime.date.today()
    for delta in range(0, 62):
        d = today - datetime.timedelta(days=delta)
        month = d.strftime("%Y-%m")
        index = load_index(record_dir, month)
        entries = index.get("entries") or []
        if entries:
            e = entries[-1]
            block = read_entry_at_offset(record_dir, month, int(e.get("char_offset", 0)))
            if block:
                return parse_entry_fields(block)
    # legacy fallback
    legacy = os.path.join(record_dir, "每日题目记录.md")
    if os.path.isfile(legacy):
        with open(legacy, encoding="utf-8") as f:
            text = f.read()
        blocks = ENTRY_SPLIT_RE.split(text.strip())
        if blocks:
            return parse_entry_fields(blocks[-1])
    return None


def list_recent(record_dir: str, days: int = 7) -> list[dict[str, Any]]:
    """最近 N 天索引精简列表（不含正文）。"""
    today = datetime.date.today()
    start = today - datetime.timedelta(days=max(0, days - 1))
    months: set[str] = set()
    d = start
    while d <= today:
        months.add(d.strftime("%Y-%m"))
        d += datetime.timedelta(days=1)
    out: list[dict[str, Any]] = []
    for month in sorted(months):
        for e in load_index(record_dir, month).get("entries", []):
            try:
                ed = datetime.date.fromisoformat(e["date"])
            except (KeyError, ValueError):
                continue
            if start <= ed <= today:
                out.append({
                    "date": e.get("date"),
                    "time": e.get("time"),
                    "num": e.get("num"),
                    "subject": e.get("subject", ""),
                    "difficulty": e.get("difficulty", ""),
                    "kp": e.get("kp", ""),
                    "ref_source": e.get("ref_source", ""),
                })
    out.sort(key=lambda x: (x.get("date", ""), int(x.get("num") or 0), x.get("time", "")))
    return out


def rebuild_index_from_md(record_dir: str, month: str) -> int:
    """从月 md 重建索引，返回条目数。"""
    path = month_md_path(record_dir, month)
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as f:
        text = f.read()
    entries = []
    for m in HEADER_RE.finditer(text):
        offset = m.start()
        # 找到本条结束
        nxt = HEADER_RE.search(text, m.end())
        end = nxt.start() if nxt else len(text)
        block = text[offset:end]
        meta = parse_entry_meta(block, char_offset=offset)
        if meta:
            entries.append(meta)
    index = {"month": month, "file": f"{month}.md", "entries": entries}
    save_index(record_dir, index)
    return len(entries)


def split_legacy_file(legacy_path: str, record_dir: str) -> dict[str, int]:
    """把旧「每日题目记录.md」按月拆分，返回 {month: count}。"""
    with open(legacy_path, encoding="utf-8") as f:
        text = f.read()
    # 修粘连：---## → ---\n\n##
    text = re.sub(r"---##", "---\n\n##", text)
    blocks = ENTRY_SPLIT_RE.split(text.strip())
    by_month: dict[str, list[str]] = {}
    for b in blocks:
        b = b.strip()
        if not b:
            continue
        if not b.startswith("## "):
            continue
        m = HEADER_RE.search(b)
        if not m:
            # 早期可能无 #num，尽量保留
            dm = re.match(r"##\s+(\d{4}-\d{2}-\d{2})", b)
            if not dm:
                continue
            month = month_of(dm.group(1))
        else:
            month = month_of(m.group(1))
        # 保证块以 --- 结尾并带尾空行
        if not b.rstrip().endswith("---"):
            b = b.rstrip() + "\n---"
        by_month.setdefault(month, []).append(b.strip())

    counts: dict[str, int] = {}
    os.makedirs(record_dir, exist_ok=True)
    for month, blist in sorted(by_month.items()):
        out_path = month_md_path(record_dir, month)
        body = "\n\n".join(blist) + "\n"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(body)
        counts[month] = rebuild_index_from_md(record_dir, month)
    return counts
