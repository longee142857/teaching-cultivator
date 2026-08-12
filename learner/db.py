"""SQLite 单一真相源（BIG-TEACH-013）。

运行时读写（推送 / 当前题 / 今日题库 / 作答 / 掌握度）只走本库；
月 MD、*.index.json、last_push.json / public/last_class.json、answer-log.jsonl
迁移后仅作为只读导出或兼容镜像，不再作为权威。

约定：
- 默认库路径 DATA_DIR/teaching.db，可用 env TEACHING_DB 覆盖
- 时区：写入存 UTC ISO；「今天 / 日期槽」按 Asia/Shanghai 日历日解释
- 连接封装在本模块，禁止在别处散落 sqlite3.connect
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

# Asia/Shanghai 恒为 UTC+8 且无夏令时；用固定偏移避免 Windows 缺 tzdata 报错
TZ_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_nodes (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    l1 TEXT,
    l2 TEXT,
    l3 TEXT,
    name TEXT,
    parent_id TEXT
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    q_hash TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT,
    difficulty TEXT,
    kp TEXT,
    l3_id TEXT,
    item_form TEXT,
    ability_goal TEXT,
    ref_source TEXT,
    meta TEXT,
    created_at TEXT,
    UNIQUE (subject, q_hash)
);

CREATE TABLE IF NOT EXISTS item_kcs (
    item_id INTEGER NOT NULL REFERENCES items(id),
    kc_id TEXT NOT NULL,
    PRIMARY KEY (item_id, kc_id)
);

CREATE TABLE IF NOT EXISTS pushes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id),
    learner_id TEXT,             -- NULL = 公共课
    day TEXT,                    -- Asia/Shanghai YYYY-MM-DD
    seq INTEGER,                 -- 当日序号（num，全局按日递增）
    pushed_at TEXT,              -- UTC ISO
    slot TEXT,
    channel TEXT,
    created_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pushes_day_seq
    ON pushes (day, seq, COALESCE(learner_id, ''));

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    push_id INTEGER REFERENCES pushes(id),
    item_id INTEGER REFERENCES items(id),
    knowledge_point TEXT,
    correct INTEGER,
    credit REAL,
    item_type TEXT,
    status TEXT,
    confidence REAL,
    answered_at TEXT,            -- 原 ts（UTC ISO）
    meta TEXT                    -- 完整旧格式条目（state/mastery_before 等）
);
CREATE INDEX IF NOT EXISTS ix_attempts_user ON attempts (user_id);

CREATE TABLE IF NOT EXISTS mastery_states (
    learner_id TEXT NOT NULL,
    kp TEXT NOT NULL,
    state_json TEXT NOT NULL,
    updated_at TEXT,
    PRIMARY KEY (learner_id, kp)
);

CREATE TABLE IF NOT EXISTS ability_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id TEXT,
    ability_json TEXT,
    computed_at TEXT
);
"""

_SEED_SUBJECTS = (("math", "数学一"), ("comm", "通信原理"), ("review", "错题复盘"))

# 旧 jsonl 条目中由 meta 承载的字段（columns 之外的部分）
_META_FIELDS = (
    "turn_id", "conv_tag", "mastery_before", "mastery_after",
    "update_applied", "update_reason", "state", "ref_id",
    "subject", "supersedes_ts", "quarantined", "user_id",
)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_from_shanghai(day: str, hhmm: str = "12:00") -> str:
    """Asia/Shanghai 日历日（+可选 HH:MM）→ UTC ISO。"""
    try:
        local = datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ_SHANGHAI)
    except ValueError:
        local = datetime.strptime(day, "%Y-%m-%d").replace(hour=12, tzinfo=TZ_SHANGHAI)
    return local.astimezone(timezone.utc).isoformat()


def shanghai_day(iso: str | None) -> str:
    if not iso:
        return datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d")
    try:
        s = str(iso).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        # 无 tz 的历史墙钟按上海本地解释（勿当 UTC）
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_SHANGHAI)
        return dt.astimezone(TZ_SHANGHAI).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d")


def shanghai_hhmm(iso: str | None) -> str:
    if not iso:
        return "00:00"
    try:
        s = str(iso).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_SHANGHAI)
        return dt.astimezone(TZ_SHANGHAI).strftime("%H:%M")
    except (ValueError, TypeError):
        return "00:00"


def _q_hash(question: str) -> str:
    return hashlib.sha1((question or "").encode("utf-8")).hexdigest()


def _db_path() -> str:
    try:
        from config import TEACHING_DB, DATA_DIR
        if (TEACHING_DB or "").strip():
            return TEACHING_DB.strip()
        return os.path.join(DATA_DIR, "teaching.db")
    except Exception:
        env = os.environ.get("TEACHING_DB", "").strip()
        if env:
            return env
        return os.path.join("data", "teaching.db")


class Store:
    """SQLite 封装（每操作新建连接；WAL）。

    不持久持有连接：Windows 下避免锁文件导致临时目录清理失败。
    """

    def __init__(self, path: str | None = None):
        self.path = path or _db_path()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def close(self) -> None:
        pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None  # autocommit；事务由 _txn 显式管理
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA)
                self._migrate_bank_columns(conn)
                # 旧库可能已有无 PK 的 item_kcs：补唯一索引（忽略已存在/冲突）
                try:
                    conn.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ux_item_kcs "
                        "ON item_kcs(item_id, kc_id)"
                    )
                except sqlite3.OperationalError:
                    pass
                for code, name in _SEED_SUBJECTS:
                    conn.execute(
                        "INSERT OR IGNORE INTO subjects (code, name) VALUES (?, ?)",
                        (code, name),
                    )
            finally:
                conn.close()

    @staticmethod
    def _migrate_bank_columns(conn: sqlite3.Connection) -> None:
        """幂等：预出题库 / CDP 列 + item_kcs.role。"""
        cols = {r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
        alters = [
            ("status", "TEXT DEFAULT 'retired'"),
            ("bank_subject", "TEXT"),
            ("techniques", "TEXT"),
            ("solution", "TEXT"),
            ("cdps", "TEXT"),
            ("use_count", "INTEGER DEFAULT 0"),
            # 审判层：pending|pass|poor；quality_score 控制抽题权重
            ("quality_tier", "TEXT DEFAULT 'pending'"),
            ("quality_score", "REAL DEFAULT 1.0"),
            ("judge_count", "INTEGER DEFAULT 0"),
            ("judge_meta", "TEXT"),
        ]
        for name, decl in alters:
            if name not in cols:
                try:
                    conn.execute(f"ALTER TABLE items ADD COLUMN {name} {decl}")
                except sqlite3.OperationalError:
                    pass
        # 已有推送关联的题 → retired；无推送的保持（新库默认 retired，ready 由入库写）
        try:
            conn.execute(
                """UPDATE items SET status='retired'
                   WHERE (status IS NULL OR status='')
                     AND id IN (SELECT DISTINCT item_id FROM pushes)"""
            )
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(
                """UPDATE items SET bank_subject=subject
                   WHERE bank_subject IS NULL OR bank_subject=''"""
            )
        except sqlite3.OperationalError:
            pass
        kc_cols = {r[1] for r in conn.execute("PRAGMA table_info(item_kcs)").fetchall()}
        if "role" not in kc_cols:
            try:
                conn.execute(
                    "ALTER TABLE item_kcs ADD COLUMN role TEXT DEFAULT 'primary_kp'"
                )
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_items_ready "
                "ON items (bank_subject, status, kp)"
            )
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_items_judge "
                "ON items (status, quality_tier, judge_count)"
            )
        except sqlite3.OperationalError:
            pass
        # 旧 ready 题未审 → pending
        try:
            conn.execute(
                """UPDATE items SET quality_tier='pending'
                   WHERE status='ready'
                     AND (quality_tier IS NULL OR quality_tier='')"""
            )
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(
                """UPDATE items SET quality_score=1.0
                   WHERE quality_score IS NULL"""
            )
        except sqlite3.OperationalError:
            pass

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = self._connect()
        try:
            cur = conn.execute(sql, params)
            return list(cur.fetchall())
        finally:
            conn.close()

    def _txn(self, fn) -> Any:
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            result = fn(conn)
            conn.execute("COMMIT")
            return result
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    # ── items ──────────────────────────────────────────────

    def upsert_item(
        self,
        *,
        subject: str,
        question: str,
        answer: str = "",
        difficulty: str = "",
        kp: str = "",
        l3_id: str = "",
        item_form: str = "",
        ability_goal: str = "",
        ref_source: str = "",
        meta: dict | None = None,
        created_at: str | None = None,
    ) -> int:
        def _do(conn) -> int:
            qh = _q_hash(question)
            now = created_at or now_utc_iso()
            conn.execute(
                """INSERT INTO items
                   (subject, q_hash, question, answer, difficulty, kp, l3_id,
                    item_form, ability_goal, ref_source, meta, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(subject, q_hash) DO UPDATE SET
                     answer=excluded.answer, difficulty=excluded.difficulty,
                     kp=excluded.kp, l3_id=excluded.l3_id,
                     item_form=excluded.item_form, ability_goal=excluded.ability_goal,
                     ref_source=excluded.ref_source, meta=excluded.meta
                """,
                (
                    subject, qh, question, answer or "", difficulty or "",
                    kp or "", l3_id or "", item_form or "", ability_goal or "",
                    ref_source or "", json.dumps(meta or {}, ensure_ascii=False), now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM items WHERE subject=? AND q_hash=?", (subject, qh)
            ).fetchone()
            return int(row[0])

        return int(self._txn(_do))

    # ── pushes ─────────────────────────────────────────────

    def record_push(
        self,
        *,
        subject: str,
        question: str,
        answer: str = "",
        difficulty: str = "",
        kp: str = "",
        l3_id: str = "",
        item_form: str = "",
        ability_goal: str = "",
        ref_source: str = "",
        decision_type: str = "",
        reason: str = "",
        learner_id: str | None = None,
        slot: str = "",
        pushed_at: str | None = None,
        day: str | None = None,
    ) -> int:
        """同一事务写 items（若新）+ pushes（及需要时 item_kcs）。返回 push_id。"""
        def _do(conn) -> int:
            meta = {"decision_type": decision_type, "reason": reason}
            qh = _q_hash(question)
            now = pushed_at or now_utc_iso()
            conn.execute(
                """INSERT INTO items
                   (subject, q_hash, question, answer, difficulty, kp, l3_id,
                    item_form, ability_goal, ref_source, meta, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(subject, q_hash) DO UPDATE SET
                     answer=excluded.answer, difficulty=excluded.difficulty,
                     kp=excluded.kp, l3_id=excluded.l3_id,
                     item_form=excluded.item_form, ability_goal=excluded.ability_goal,
                     ref_source=excluded.ref_source, meta=excluded.meta
                """,
                (
                    subject, qh, question, answer or "", difficulty or "",
                    kp or "", l3_id or "", item_form or "", ability_goal or "",
                    ref_source or "", json.dumps(meta, ensure_ascii=False), now,
                ),
            )
            item_row = conn.execute(
                "SELECT id FROM items WHERE subject=? AND q_hash=?", (subject, qh)
            ).fetchone()
            item_id = int(item_row[0])
            if kp:
                conn.execute(
                    "INSERT OR IGNORE INTO item_kcs (item_id, kc_id) VALUES (?, ?)",
                    (item_id, kp),
                )
            d = day or shanghai_day(now)
            cnt = conn.execute("SELECT COUNT(*) FROM pushes WHERE day=?", (d,)).fetchone()
            seq = int(cnt[0]) + 1
            conn.execute(
                """INSERT INTO pushes
                   (item_id, learner_id, day, seq, pushed_at, slot, channel, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (item_id, learner_id, d, seq, now, slot or "", "push", now),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        return int(self._txn(_do))

    @staticmethod
    def _push_row(row: sqlite3.Row) -> dict:
        meta = {}
        try:
            meta = json.loads(row["meta"] or "{}")
        except (TypeError, json.JSONDecodeError):
            pass
        pid = int(row["push_id"])
        out = {
            "id": pid,
            "push_id": pid,
            "item_id": int(row["item_id"]),
            "learner_id": row["learner_id"],
            "day": row["day"],
            "date": row["day"],
            "seq": int(row["seq"]),
            "num": int(row["seq"]),
            "time": shanghai_hhmm(row["pushed_at"]),
            "pushed_at": row["pushed_at"],
            "slot": row["slot"] or "",
            "channel": row["channel"] or "",
            "subject": row["subject"],
            "question": row["question"],
            "answer": row["answer"] or "",
            "difficulty": row["difficulty"] or "",
            "kp": row["kp"] or "",
            "l3_id": row["l3_id"] or "",
            "item_form": row["item_form"] or "",
            "ability_goal": row["ability_goal"] or "",
            "ref_source": row["ref_source"] or "",
            "decision_type": meta.get("decision_type", ""),
            "reason": meta.get("reason", ""),
            "timestamp": row["pushed_at"],
            "_source": "db",
        }
        try:
            out["techniques"] = Store._parse_json_field(row["item_techniques"], [])
            out["solution"] = Store._parse_json_field(row["item_solution"], {})
            out["cdps"] = Store._parse_json_field(row["item_cdps"], [])
            out["item_status"] = row["item_status"] or ""
        except (IndexError, KeyError):
            out["techniques"] = []
            out["solution"] = {}
            out["cdps"] = []
            out["item_status"] = ""
        return out

    def _visible_where(self, learner_id: str | None) -> tuple[str, tuple]:
        lid = (learner_id or "").strip()
        if not lid:
            return "p.learner_id IS NULL", ()
        return "(p.learner_id IS NULL OR p.learner_id = ?)", (lid,)

    _PUSH_SELECT = (
        "SELECT p.id AS push_id, p.item_id, p.learner_id, p.day, p.seq, "
        "p.pushed_at, p.slot, p.channel, "
        "i.id AS item_id, i.subject, i.question, i.answer, i.difficulty, "
        "i.kp, i.l3_id, i.item_form, i.ability_goal, i.ref_source, i.meta, "
        "i.techniques AS item_techniques, i.solution AS item_solution, "
        "i.cdps AS item_cdps, i.status AS item_status "
        "FROM pushes p JOIN items i ON i.id = p.item_id "
    )

    def get_latest_push(self, learner_id: str | None = None) -> dict | None:
        where, params = self._visible_where(learner_id)
        rows = self._query(
            self._PUSH_SELECT
            + f"WHERE {where} ORDER BY p.pushed_at DESC, p.id DESC LIMIT 1",
            params,
        )
        return self._push_row(rows[0]) if rows else None

    def get_push(self, push_id: int) -> dict | None:
        rows = self._query(self._PUSH_SELECT + "WHERE p.id = ?", (int(push_id),))
        return self._push_row(rows[0]) if rows else None

    def delete_push(self, push_id: int) -> None:
        self._txn(lambda conn: conn.execute("DELETE FROM pushes WHERE id=?", (int(push_id),)))

    def list_today_pushes(
        self, learner_id: str | None, day: str
    ) -> list[dict]:
        """今日可见 pushes，带 answered（该学员是否已作答）；按 pushed_at ASC。"""
        where, params = self._visible_where(learner_id)
        sql = (
            self._PUSH_SELECT
            + f"WHERE {where} AND p.day = ? "
            + "ORDER BY p.pushed_at ASC, p.id ASC"
        )
        rows = self._query(sql, params + (day,))
        out = []
        for r in rows:
            d = self._push_row(r)
            d["answered"] = self._push_answered(r["push_id"], learner_id)
            out.append(d)
        return out

    def _push_answered(self, push_id: int, learner_id: str | None) -> bool:
        lid = (learner_id or "").strip()
        if not lid:
            return False
        rows = self._query(
            "SELECT 1 FROM attempts WHERE push_id=? AND user_id=? LIMIT 1",
            (push_id, lid),
        )
        return bool(rows)

    def list_recent_pushes(self, learner_id: str | None, days: int = 7) -> list[dict]:
        where, params = self._visible_where(learner_id)
        start_day = (datetime.now(TZ_SHANGHAI) - timedelta(days=max(0, days - 1))).strftime("%Y-%m-%d")
        rows = self._query(
            self._PUSH_SELECT
            + f"WHERE {where} AND p.day >= ? ORDER BY p.day DESC, p.seq DESC, p.id DESC",
            params + (start_day,),
        )
        return [self._push_row(r) for r in rows]

    def list_month_pushes(self, month: str) -> list[dict]:
        rows = self._query(
            self._PUSH_SELECT
            + "WHERE p.day LIKE ? ORDER BY p.day ASC, p.seq ASC, p.id ASC",
            (month + "%",),
        )
        return [self._push_row(r) for r in rows]

    def find_item_id(self, subject: str, question: str) -> int | None:
        rows = self._query(
            "SELECT id FROM items WHERE subject=? AND q_hash=?",
            (subject, _q_hash(question)),
        )
        return int(rows[0][0]) if rows else None

    def push_exists_for_item(self, item_id: int, learner_id: str | None = None) -> bool:
        lid = (learner_id or "").strip() or ""
        rows = self._query(
            "SELECT 1 FROM pushes WHERE item_id=? AND COALESCE(learner_id,'')=? LIMIT 1",
            (int(item_id), lid),
        )
        return bool(rows)

    def next_seq_for_day(self, day: str) -> int:
        rows = self._query("SELECT COUNT(*) FROM pushes WHERE day=?", (day,))
        return int(rows[0][0]) + 1

    def push_exists(self, day: str, seq: int, learner_id: str | None = None) -> bool:
        lid = (learner_id or "").strip() or ""
        rows = self._query(
            "SELECT 1 FROM pushes WHERE day=? AND seq=? AND COALESCE(learner_id,'')=?",
            (day, int(seq), lid),
        )
        return bool(rows)

    def add_push_migrated(
        self,
        *,
        subject: str,
        question: str,
        answer: str = "",
        difficulty: str = "",
        kp: str = "",
        l3_id: str = "",
        item_form: str = "",
        ability_goal: str = "",
        ref_source: str = "",
        decision_type: str = "",
        reason: str = "",
        learner_id: str | None = None,
        day: str,
        seq: int,
        pushed_at: str,
        slot: str = "",
    ) -> int | None:
        """迁移专用：items DO NOTHING 保留首条；push 按 (day,seq,learner) 去重。"""
        def _do(conn):
            qh = _q_hash(question)
            conn.execute(
                """INSERT INTO items
                   (subject, q_hash, question, answer, difficulty, kp, l3_id,
                    item_form, ability_goal, ref_source, meta, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(subject, q_hash) DO NOTHING""",
                (
                    subject, qh, question, answer or "", difficulty or "",
                    kp or "", l3_id or "", item_form or "", ability_goal or "",
                    ref_source or "",
                    json.dumps({"decision_type": decision_type, "reason": reason}, ensure_ascii=False),
                    pushed_at,
                ),
            )
            item_row = conn.execute(
                "SELECT id FROM items WHERE subject=? AND q_hash=?", (subject, qh)
            ).fetchone()
            item_id = int(item_row[0])
            lid = (learner_id or "").strip() or None
            exists = conn.execute(
                "SELECT 1 FROM pushes WHERE day=? AND seq=? AND COALESCE(learner_id,'')=?",
                (day, int(seq), (lid or "")),
            ).fetchone()
            if exists:
                return None
            conn.execute(
                """INSERT INTO pushes
                   (item_id, learner_id, day, seq, pushed_at, slot, channel, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (item_id, lid, day, int(seq), pushed_at, slot or "", "push", pushed_at),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        return self._txn(_do)

    def add_attempt_migrated(self, entry: dict) -> bool:
        """迁移专用：按 (user_id, answered_at) 去重。"""
        user = str(entry.get("user_id") or "")
        ts = entry.get("ts") or ""
        if not user or not ts:
            return False
        rows = self._query(
            "SELECT 1 FROM attempts WHERE user_id=? AND answered_at=?",
            (user, ts),
        )
        if rows:
            return False
        self.add_attempt_entry(entry)
        return True

    def find_entry(self, date: str, num: int = 0, learner_id: str | None = None) -> dict | None:
        """按日期（+可选 seq）定位一条推送。num=0 取该日最后一条。"""
        d = (date or "").strip()
        if not d:
            return None
        where, params = self._visible_where(learner_id)
        if num and num > 0:
            rows = self._query(
                self._PUSH_SELECT + f"WHERE {where} AND p.day = ? AND p.seq = ?",
                params + (d, int(num)),
            )
        else:
            rows = self._query(
                self._PUSH_SELECT + f"WHERE {where} AND p.day = ? ORDER BY p.seq DESC, p.id DESC LIMIT 1",
                params + (d,),
            )
        if not rows:
            return None
        return self._push_row(rows[0])

    def resolve_push_for_question(
        self, learner_id: str | None, question: str
    ) -> tuple[int, int] | None:
        """返回最新可见 push 的 (push_id, item_id)；其题目与给定题干一致。"""
        q = (question or "").strip()
        if not q:
            return None
        where, params = self._visible_where(learner_id)
        rows = self._query(
            self._PUSH_SELECT
            + f"WHERE {where} AND i.question = ? "
            + "ORDER BY p.pushed_at DESC, p.id DESC LIMIT 1",
            params + (q,),
        )
        if not rows:
            # 容错：题干长度变化（如末尾空白）
            like = f"%{q[:50]}%"
            rows = self._query(
                self._PUSH_SELECT
                + f"WHERE {where} AND i.question LIKE ? "
                + "ORDER BY p.pushed_at DESC, p.id DESC LIMIT 1",
                params + (like,),
            )
        if not rows:
            return None
        return int(rows[0]["push_id"]), int(rows[0]["item_id"])

    # ── attempts ───────────────────────────────────────────

    def add_attempt_entry(self, entry: dict) -> int:
        """从旧格式条目 dict 写入 attempts。entry 可含 push_id / item_id。"""
        user_id = str(entry.get("user_id") or "")
        c = entry.get("correct")
        correct = 1 if c is True else (0 if c is False else None)
        try:
            credit = float(entry["credit"]) if entry.get("credit") is not None else None
        except (TypeError, ValueError):
            credit = None
        try:
            confidence = float(entry["confidence"]) if entry.get("confidence") is not None else None
        except (TypeError, ValueError):
            confidence = None
        answered_at = entry.get("ts") or now_utc_iso()

        def _do(conn) -> int:
            conn.execute(
                """INSERT INTO attempts
                   (user_id, push_id, item_id, knowledge_point, correct, credit,
                    item_type, status, confidence, answered_at, meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user_id, entry.get("push_id"), entry.get("item_id"),
                    entry.get("knowledge_point") or "", correct, credit,
                    entry.get("item_type") or "unknown", entry.get("status") or "applied",
                    confidence, answered_at,
                    json.dumps(entry, ensure_ascii=False),
                ),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        return int(self._txn(_do))

    def get_attempts(self, user_id: str) -> list[dict]:
        rows = self._query(
            "SELECT * FROM attempts WHERE user_id=? ORDER BY answered_at ASC, id ASC",
            (user_id,),
        )
        out = []
        for r in rows:
            entry = {}
            try:
                entry = json.loads(r["meta"] or "{}")
            except (TypeError, json.JSONDecodeError):
                pass
            entry["user_id"] = r["user_id"]
            entry["knowledge_point"] = r["knowledge_point"] or ""
            entry["correct"] = None if r["correct"] is None else bool(r["correct"])
            entry["item_type"] = r["item_type"] or "unknown"
            entry["status"] = r["status"] or "applied"
            entry["ts"] = r["answered_at"]
            if r["credit"] is not None:
                entry["credit"] = r["credit"]
            if r["confidence"] is not None:
                entry["confidence"] = r["confidence"]
            entry.setdefault("state", {})
            out.append(entry)
        return out

    def get_attempt_for_push(self, push_id: int) -> dict | None:
        rows = self._query(
            "SELECT * FROM attempts WHERE push_id=? ORDER BY answered_at DESC, id DESC LIMIT 1",
            (push_id,),
        )
        if not rows:
            return None
        r = rows[0]
        entry = {}
        try:
            entry = json.loads(r["meta"] or "{}")
        except (TypeError, json.JSONDecodeError):
            pass
        entry["user_id"] = r["user_id"]
        entry["correct"] = None if r["correct"] is None else bool(r["correct"])
        entry["ts"] = r["answered_at"]
        return entry

    # ── mastery ────────────────────────────────────────────

    def get_mastery(self, user_id: str, kp: str) -> dict | None:
        rows = self._query(
            "SELECT state_json FROM mastery_states WHERE learner_id=? AND kp=?",
            (user_id, kp),
        )
        if not rows:
            return None
        try:
            return json.loads(rows[0][0])
        except (TypeError, json.JSONDecodeError):
            return None

    def set_mastery(self, user_id: str, kp: str, state_dict: dict, updated_at: str | None = None) -> None:
        self._txn(
            lambda conn: conn.execute(
                """INSERT INTO mastery_states (learner_id, kp, state_json, updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(learner_id, kp) DO UPDATE SET
                     state_json=excluded.state_json, updated_at=excluded.updated_at""",
                (user_id, kp, json.dumps(state_dict, ensure_ascii=False),
                 updated_at or now_utc_iso()),
            )
        )

    def get_all_mastery(self, user_id: str) -> dict[str, float]:
        rows = self._query(
            "SELECT kp, state_json FROM mastery_states WHERE learner_id=?", (user_id,)
        )
        out: dict[str, float] = {}
        for kp, sj in rows:
            try:
                d = json.loads(sj)
                out[kp] = float(d.get("p_mastery", 0.2))
            except (TypeError, json.JSONDecodeError, ValueError):
                continue
        return out

    def get_mastery_full(self, user_id: str) -> dict[str, dict]:
        rows = self._query(
            "SELECT kp, state_json FROM mastery_states WHERE learner_id=?", (user_id,)
        )
        out: dict[str, dict] = {}
        for kp, sj in rows:
            try:
                out[kp] = json.loads(sj)
            except (TypeError, json.JSONDecodeError):
                continue
        return out

    def list_knowledge_nodes(self) -> list[dict]:
        rows = self._query("SELECT * FROM knowledge_nodes ORDER BY subject, id")
        return [dict(r) for r in rows]

    def count_rows(self, table: str) -> int:
        rows = self._query(f"SELECT COUNT(*) FROM {table}")
        return int(rows[0][0]) if rows else 0

    # ── item bank (pregen / pick) ───────────────────────────

    @staticmethod
    def _parse_json_field(raw: Any, default: Any):
        if raw is None or raw == "":
            return default
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return default

    def _item_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["techniques"] = self._parse_json_field(d.get("techniques"), [])
        d["solution"] = self._parse_json_field(d.get("solution"), {})
        d["cdps"] = self._parse_json_field(d.get("cdps"), [])
        d["meta"] = self._parse_json_field(d.get("meta"), {})
        d["judge_meta"] = self._parse_json_field(d.get("judge_meta"), {})
        if d.get("quality_tier") in (None, ""):
            d["quality_tier"] = "pending"
        if d.get("quality_score") is None:
            d["quality_score"] = 1.0
        if d.get("judge_count") is None:
            d["judge_count"] = 0
        return d

    def count_ready(self, subject: str, kp: str = "", technique: str = "") -> int:
        subj = (subject or "").strip()
        kp = (kp or "").strip()
        tech = (technique or "").strip()
        if tech:
            rows = self._query(
                """SELECT COUNT(*) FROM items
                   WHERE status='ready' AND COALESCE(bank_subject, subject)=?
                     AND kp=? AND techniques LIKE ?""",
                (subj, kp, f'%"{tech}"%'),
            )
        elif kp:
            rows = self._query(
                """SELECT COUNT(*) FROM items
                   WHERE status='ready' AND COALESCE(bank_subject, subject)=? AND kp=?""",
                (subj, kp),
            )
        else:
            rows = self._query(
                """SELECT COUNT(*) FROM items
                   WHERE status='ready' AND COALESCE(bank_subject, subject)=?""",
                (subj,),
            )
        return int(rows[0][0]) if rows else 0

    def insert_bank_item(
        self,
        *,
        subject: str,
        question: str,
        answer: str = "",
        difficulty: str = "",
        kp: str = "",
        l3_id: str = "",
        item_form: str = "",
        ability_goal: str = "",
        ref_source: str = "",
        techniques: list | None = None,
        solution: dict | None = None,
        cdps: list | None = None,
        meta: dict | None = None,
        status: str = "ready",
    ) -> int:
        """写入预生成题（不写 pushes）。"""
        techs = list(techniques or [])
        sol = solution or {}
        cdps_l = list(cdps or [])

        def _do(conn) -> int:
            qh = _q_hash(question)
            now = now_utc_iso()
            conn.execute(
                """INSERT INTO items
                   (subject, q_hash, question, answer, difficulty, kp, l3_id,
                    item_form, ability_goal, ref_source, meta, created_at,
                    status, bank_subject, techniques, solution, cdps, use_count,
                    quality_tier, quality_score, judge_count, judge_meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,'pending',1.0,0,?)
                   ON CONFLICT(subject, q_hash) DO UPDATE SET
                     answer=excluded.answer, difficulty=excluded.difficulty,
                     kp=excluded.kp, l3_id=excluded.l3_id,
                     item_form=excluded.item_form, ability_goal=excluded.ability_goal,
                     ref_source=excluded.ref_source, meta=excluded.meta,
                     status=excluded.status, bank_subject=excluded.bank_subject,
                     techniques=excluded.techniques, solution=excluded.solution,
                     cdps=excluded.cdps,
                     quality_tier='pending', quality_score=1.0, judge_count=0,
                     judge_meta=excluded.judge_meta""",
                (
                    subject, qh, question, answer or "", difficulty or "",
                    kp or "", l3_id or "", item_form or "", ability_goal or "",
                    ref_source or "",
                    json.dumps(meta or {}, ensure_ascii=False), now,
                    status or "ready", subject,
                    json.dumps(techs, ensure_ascii=False),
                    json.dumps(sol, ensure_ascii=False),
                    json.dumps(cdps_l, ensure_ascii=False),
                    json.dumps({"reviews": []}, ensure_ascii=False),
                ),
            )
            row = conn.execute(
                "SELECT id FROM items WHERE subject=? AND q_hash=?", (subject, qh)
            ).fetchone()
            item_id = int(row[0])
            conn.execute("DELETE FROM item_kcs WHERE item_id=?", (item_id,))
            if kp:
                conn.execute(
                    "INSERT OR IGNORE INTO item_kcs (item_id, kc_id, role) VALUES (?,?,?)",
                    (item_id, kp, "primary_kp"),
                )
            if l3_id:
                conn.execute(
                    "INSERT OR IGNORE INTO item_kcs (item_id, kc_id, role) VALUES (?,?,?)",
                    (item_id, l3_id, "l3"),
                )
            for t in techs:
                t = str(t or "").strip()
                if t:
                    conn.execute(
                        "INSERT OR IGNORE INTO item_kcs (item_id, kc_id, role) VALUES (?,?,?)",
                        (item_id, t, "technique"),
                    )
            return item_id

        return int(self._txn(_do))

    def get_item(self, item_id: int) -> dict | None:
        rows = self._query("SELECT * FROM items WHERE id=?", (int(item_id),))
        return self._item_dict(rows[0]) if rows else None

    def get_item_by_question(self, question: str, subject: str = "") -> dict | None:
        qh = _q_hash(question or "")
        if subject:
            rows = self._query(
                "SELECT * FROM items WHERE subject=? AND q_hash=?",
                (subject, qh),
            )
        else:
            rows = self._query("SELECT * FROM items WHERE q_hash=? LIMIT 1", (qh,))
        return self._item_dict(rows[0]) if rows else None

    def learner_seen_hashes(self, learner_id: str | None, limit: int = 200) -> set[str]:
        lid = (learner_id or "").strip()
        if not lid:
            return set()
        rows = self._query(
            """SELECT i.q_hash FROM pushes p
               JOIN items i ON i.id=p.item_id
               WHERE p.learner_id=? OR p.learner_id IS NULL
               ORDER BY p.pushed_at DESC LIMIT ?""",
            (lid, int(limit)),
        )
        # 公共课也算见过：上面 OR NULL 过宽；改为仅该学员 + 公共
        rows = self._query(
            """SELECT i.q_hash FROM pushes p
               JOIN items i ON i.id=p.item_id
               WHERE (p.learner_id=? OR p.learner_id IS NULL)
               ORDER BY p.pushed_at DESC LIMIT ?""",
            (lid, int(limit)),
        )
        return {str(r[0]) for r in rows}

    def pick_ready_item(
        self,
        *,
        subject: str,
        kp: str = "",
        technique: str = "",
        l1: str = "",
        exclude_hashes: set[str] | None = None,
    ) -> dict | None:
        """按契约顺序抽 ready 题：KP+technique → KP → L1 → 任意。

        同档内优先 quality_score 高（pass > pending > poor），劣质题仍可被抽但权重低。
        """
        subj = (subject or "").strip()
        kp = (kp or "").strip()
        tech = (technique or "").strip()
        excl = exclude_hashes or set()

        def _ok(row) -> bool:
            return str(row["q_hash"]) not in excl

        def _fetch(sql: str, params: tuple) -> dict | None:
            rows = self._query(sql, params)
            # 加权：在匹配集中按 score 选；确定性实现 = 最高分优先，同分 id 升序
            scored: list[tuple[float, dict]] = []
            for r in rows:
                if not _ok(r):
                    continue
                d = self._item_dict(r)
                try:
                    sc = float(d.get("quality_score") if d.get("quality_score") is not None else 1.0)
                except (TypeError, ValueError):
                    sc = 1.0
                # poor 再乘一次软衰减，进一步减小被抽概率
                if (d.get("quality_tier") or "") == "poor":
                    sc = min(sc, 0.12)
                scored.append((sc, d))
            if not scored:
                return None
            scored.sort(key=lambda x: (-x[0], int(x[1].get("id") or 0)))
            # 若最高分是 poor 且存在更高档，已在排序体现；若全是 poor，仍返回最优者
            return scored[0][1]

        base = (
            "SELECT * FROM items WHERE status='ready' "
            "AND COALESCE(bank_subject, subject)=? "
        )
        # 多取一些再按 quality_score 排序挑选
        order = " ORDER BY COALESCE(quality_score, 1.0) DESC, id ASC LIMIT 40"

        if kp and tech:
            hit = _fetch(
                base + "AND kp=? AND techniques LIKE ?" + order,
                (subj, kp, f'%"{tech}"%'),
            )
            if hit:
                return hit
        if kp:
            hit = _fetch(base + "AND kp=?" + order, (subj, kp))
            if hit:
                return hit
        if l1:
            rows = self._query(
                """SELECT i.* FROM items i
                   JOIN knowledge_nodes kn ON kn.l2=i.kp AND kn.subject=?
                   WHERE i.status='ready' AND COALESCE(i.bank_subject,i.subject)=?
                     AND kn.l1=?
                   ORDER BY COALESCE(i.quality_score, 1.0) DESC, i.id ASC LIMIT 40""",
                (subj if subj != "review" else "math", subj, l1),
            )
            scored: list[tuple[float, dict]] = []
            for r in rows:
                if not _ok(r):
                    continue
                d = self._item_dict(r)
                try:
                    sc = float(d.get("quality_score") if d.get("quality_score") is not None else 1.0)
                except (TypeError, ValueError):
                    sc = 1.0
                if (d.get("quality_tier") or "") == "poor":
                    sc = min(sc, 0.12)
                scored.append((sc, d))
            if scored:
                scored.sort(key=lambda x: (-x[0], int(x[1].get("id") or 0)))
                return scored[0][1]
        return _fetch(base + order, (subj,))

    def list_items_for_judge(self, *, max_reviews: int = 2, limit: int = 3) -> list[dict]:
        """待审判：ready 且 judge_count < max_reviews；优先 pending，再 poor（给第二次机会）。"""
        rows = self._query(
            """SELECT * FROM items
               WHERE status='ready'
                 AND COALESCE(judge_count, 0) < ?
                 AND COALESCE(quality_tier, 'pending') IN ('pending', 'poor')
               ORDER BY
                 CASE COALESCE(quality_tier, 'pending')
                   WHEN 'pending' THEN 0
                   WHEN 'poor' THEN 1
                   ELSE 2 END,
                 id ASC
               LIMIT ?""",
            (int(max_reviews), int(limit)),
        )
        return [self._item_dict(r) for r in rows]

    def apply_judge_verdict(
        self,
        item_id: int,
        *,
        verdict: str,
        reasons: list | None = None,
        confidence: float = 0.0,
        details: dict | None = None,
        poor_score: float = 0.12,
    ) -> dict:
        """写入审判结果。verdict: pass|fail。fail → quality_tier=poor 并压低 score。"""
        v = (verdict or "").strip().lower()
        if v not in ("pass", "fail"):
            raise ValueError(f"bad verdict: {verdict}")

        def _do(conn) -> dict:
            row = conn.execute(
                "SELECT * FROM items WHERE id=?", (int(item_id),)
            ).fetchone()
            if not row:
                raise ValueError(f"item not found: {item_id}")
            meta = {}
            try:
                meta = json.loads(row["judge_meta"] or "{}")
            except (TypeError, json.JSONDecodeError, KeyError):
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            reviews = list(meta.get("reviews") or [])
            now = now_utc_iso()
            reviews.append(
                {
                    "at": now,
                    "verdict": v,
                    "reasons": list(reasons or []),
                    "confidence": float(confidence or 0.0),
                    "details": details or {},
                }
            )
            meta["reviews"] = reviews[-8:]
            jc = int(row["judge_count"] or 0) + 1 if "judge_count" in row.keys() else 1
            if v == "pass":
                tier, score = "pass", 1.0
            else:
                tier, score = "poor", float(poor_score)
            conn.execute(
                """UPDATE items SET quality_tier=?, quality_score=?, judge_count=?,
                   judge_meta=? WHERE id=?""",
                (
                    tier,
                    score,
                    jc,
                    json.dumps(meta, ensure_ascii=False),
                    int(item_id),
                ),
            )
            return {
                "item_id": int(item_id),
                "quality_tier": tier,
                "quality_score": score,
                "judge_count": jc,
                "verdict": v,
            }

        return self._txn(_do)

    def record_push_for_item(
        self,
        *,
        item_id: int,
        learner_id: str | None = None,
        slot: str = "",
        decision_type: str = "",
        reason: str = "",
        pushed_at: str | None = None,
    ) -> int:
        """已有 bank item → 只写 pushes；use_count+1。"""
        def _do(conn) -> int:
            row = conn.execute("SELECT * FROM items WHERE id=?", (int(item_id),)).fetchone()
            if not row:
                raise ValueError(f"item not found: {item_id}")
            now = pushed_at or now_utc_iso()
            d = shanghai_day(now)
            cnt = conn.execute("SELECT COUNT(*) FROM pushes WHERE day=?", (d,)).fetchone()
            seq = int(cnt[0]) + 1
            # 合并 meta
            meta = {}
            try:
                meta = json.loads(row["meta"] or "{}")
            except (TypeError, json.JSONDecodeError):
                meta = {}
            if decision_type:
                meta["decision_type"] = decision_type
            if reason:
                meta["reason"] = reason
            conn.execute(
                "UPDATE items SET meta=?, use_count=COALESCE(use_count,0)+1 WHERE id=?",
                (json.dumps(meta, ensure_ascii=False), int(item_id)),
            )
            conn.execute(
                """INSERT INTO pushes
                   (item_id, learner_id, day, seq, pushed_at, slot, channel, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (int(item_id), learner_id, d, seq, now, slot or "", "push", now),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        return int(self._txn(_do))

    def add_ability_snapshot(self, learner_id: str, ability: dict) -> int:
        def _do(conn) -> int:
            conn.execute(
                """INSERT INTO ability_snapshots (learner_id, ability_json, computed_at)
                   VALUES (?,?,?)""",
                (
                    (learner_id or "").strip(),
                    json.dumps(ability or {}, ensure_ascii=False),
                    now_utc_iso(),
                ),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        return int(self._txn(_do))

    def recent_ability_signals(self, learner_id: str, limit: int = 20) -> dict:
        """从 attempts.meta.cdp_results 汇总技巧/CDP 失败（过滤对齐噪声）。"""
        from learner.item_bank import is_learner_cdp_fail

        lid = (learner_id or "").strip()
        rows = self._query(
            """SELECT meta, knowledge_point, correct, answered_at FROM attempts
               WHERE user_id=? ORDER BY answered_at DESC, id DESC LIMIT ?""",
            (lid, int(limit) * 3),
        )
        tech_fail: dict[str, int] = {}
        cdp_fail: list[dict] = []
        weak_kps: dict[str, int] = {}
        for r in rows:
            kp = r["knowledge_point"] or ""
            if r["correct"] == 0 and kp and kp != "未分类":
                weak_kps[kp] = weak_kps.get(kp, 0) + 1
            meta = self._parse_json_field(r["meta"], {})
            for c in meta.get("cdp_results") or []:
                if not is_learner_cdp_fail(c):
                    continue
                tech = str(c.get("technique") or "").strip()
                if tech:
                    tech_fail[tech] = tech_fail.get(tech, 0) + 1
                cdp_fail.append(
                    {
                        "id": c.get("id"),
                        "technique": tech,
                        "note": c.get("note") or "",
                        "kp": kp,
                        "at": r["answered_at"],
                    }
                )
        top_tech = sorted(tech_fail.items(), key=lambda x: -x[1])[:8]
        top_kp = sorted(weak_kps.items(), key=lambda x: -x[1])[:8]
        return {
            "technique_fail_top": [{"technique": t, "n": n} for t, n in top_tech],
            "cdp_fail_recent": cdp_fail[:limit],
            "weak_kps": [{"kp": k, "n": n} for k, n in top_kp],
        }


_store: dict[str, Store] = {}
_store_lock = threading.Lock()


def get_store(path: str | None = None) -> Store:
    resolved = path or _db_path()
    with _store_lock:
        if resolved not in _store:
            _store[resolved] = Store(resolved)
        return _store[resolved]


def reset_store() -> None:
    """测试专用：清空已缓存连接。"""
    global _store
    with _store_lock:
        for s in _store.values():
            try:
                s.close()
            except Exception:
                pass
        _store = {}
