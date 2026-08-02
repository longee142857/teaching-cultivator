"""流式预热 kb_cache：单进程加载模型，逐 unit upsert，空闲超时可杀、可续跑。"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

BATCH = os.environ.get("KB_WARM_BATCH", "")
PY = os.environ.get("KB_PYTHON") or sys.executable
# 0 = 整批一次加载；>0 则分块（每块重载模型，更慢但隔离更好）
CHUNK = int(os.environ.get("WARM_CHUNK", "0"))
IDLE_TIMEOUT = int(os.environ.get("WARM_IDLE_TIMEOUT", "240"))
TOTAL_TIMEOUT = int(os.environ.get("WARM_TOTAL_TIMEOUT", "3600"))


def _build_units():
    from learner.rag_retrieve import resolve_unit_queries, _source_hints_from_allow
    from learner.kp_registry import load_syllabus

    units = []
    for subject in ("math", "comm"):
        syl = load_syllabus(subject)
        for l2, meta in (syl.get("kps") or {}).items():
            if not isinstance(meta, dict):
                continue
            q, allow = resolve_unit_queries(subject, l2)
            units.append({
                "subject": subject,
                "kp": l2,
                "query": " ".join(q[:4]),
                "source_hints": _source_hints_from_allow(subject, allow, l2)[:3],
            })
            for l3 in meta.get("l3") or []:
                if isinstance(l3, dict) and l3.get("id"):
                    q3, a3 = resolve_unit_queries(subject, l3["id"])
                    units.append({
                        "subject": subject,
                        "kp": l3["id"],
                        "query": " ".join(q3[:4]),
                        "source_hints": _source_hints_from_allow(
                            subject, a3, l3["id"]
                        )[:3],
                    })
    return units


def _run_chunk(todo: list[dict], kb_cache, err_path: str) -> tuple[int, int]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    with open(err_path, "w", encoding="utf-8") as errf:
        proc = subprocess.Popen(
            [PY, "-u", BATCH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errf,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            bufsize=1,
        )
        assert proc.stdin and proc.stdout
        proc.stdin.write(json.dumps({"units": todo, "top_k": 4}, ensure_ascii=False))
        proc.stdin.close()

        q: queue.Queue[str | None] = queue.Queue()

        def _reader() -> None:
            try:
                for line in proc.stdout:
                    q.put(line)
            finally:
                q.put(None)

        threading.Thread(target=_reader, daemon=True).start()

        ok = fail = 0
        deadline = time.time() + TOTAL_TIMEOUT
        last_out = time.time()
        while True:
            now = time.time()
            if now > deadline:
                proc.kill()
                print("[timeout] total deadline", flush=True)
                break
            if now - last_out > IDLE_TIMEOUT:
                proc.kill()
                print(f"[timeout] idle {IDLE_TIMEOUT}s — killed", flush=True)
                break
            try:
                line = q.get(timeout=1.0)
            except queue.Empty:
                if proc.poll() is not None and q.empty():
                    break
                continue
            if line is None:
                break
            last_out = time.time()
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                print(f"[skip] bad line {line[:120]}", flush=True)
                continue
            if row.get("heartbeat"):
                print(f"[ready] n={row.get('n')}", flush=True)
                continue
            if row.get("done"):
                break
            if "error" in row and "kp" not in row:
                print(f"[error] {row}", flush=True)
                fail += 1
                break
            snips = row.get("snippets") or []
            subj, kp = row.get("subject") or "", row.get("kp") or ""
            if len(snips) >= 2:
                kb_cache.upsert(subj, kp, snips, query=kp)
                ok += 1
                print(f"[ok] {subj}::{kp} n={len(snips)} {row.get('sec')}s", flush=True)
            else:
                fail += 1
                print(f"[fail] {subj}::{kp} n={len(snips)} {row.get('sec')}s", flush=True)

        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    try:
        with open(err_path, encoding="utf-8", errors="replace") as f:
            lines = f.read().strip().splitlines()
        for el in lines[-10:]:
            print(f"  | {el}", flush=True)
    except Exception:
        pass
    return ok, fail


def main() -> int:
    from learner import kb_cache

    if not BATCH or not os.path.isfile(BATCH):
        print("Set KB_WARM_BATCH to the warm batch worker script path")
        return 1
    if not os.path.isfile(PY):
        print("KB_PYTHON missing", PY)
        return 1

    units = _build_units()
    todo = []
    skipped = 0
    for u in units:
        ent = kb_cache.peek(u["subject"], u["kp"])
        if ent and len(ent.get("snippets") or []) >= 2:
            skipped += 1
            continue
        todo.append(u)

    print(
        f"total={len(units)} skip_cached={skipped} todo={len(todo)} chunk={CHUNK}",
        flush=True,
    )
    if not todo:
        print("nothing to warm", flush=True)
        return 0

    ok = fail = 0
    err_path = os.path.join(ROOT, "data", "kb_cache", "warm_batch.err")
    os.makedirs(os.path.dirname(err_path), exist_ok=True)
    chunks = (
        [todo]
        if CHUNK <= 0
        else [todo[i : i + CHUNK] for i in range(0, len(todo), CHUNK)]
    )
    for ci, chunk in enumerate(chunks):
        print(f"=== batch {ci+1}/{len(chunks)} size={len(chunk)} ===", flush=True)
        o, f = _run_chunk(chunk, kb_cache, err_path)
        ok += o
        fail += f
        store_n = len(kb_cache._load_store().get("entries") or {})
        print(f"=== progress ok={ok} fail={fail} store={store_n} ===", flush=True)
        if o + f < len(chunk):
            print("[warn] incomplete — re-run to resume remaining", flush=True)
            break

    report = {
        "ok": ok,
        "fail": fail,
        "skipped": skipped,
        "store_entries": len(kb_cache._load_store().get("entries") or {}),
        "required": {},
    }
    for key in (
        "math::math.calc.limit.equiv",
        "comm::comm.coding.hamming.code",
    ):
        subj, _, uid = key.partition("::")
        ent = kb_cache.peek(subj, uid)
        report["required"][key] = len((ent or {}).get("snippets") or [])

    out = os.path.join(ROOT, "data", "kb_cache", "warm_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("report", report, flush=True)
    req_ok = all(v >= 2 for v in report["required"].values())
    return 0 if req_ok and fail < max(5, max(len(todo), 1) // 4) else 1


if __name__ == "__main__":
    raise SystemExit(main())
