"""SQLite 去重 + JSON 兜底缓存。

去重逻辑：
  - 同一 repo 7 天内不重复推送（从首次推送日算起）
  - dedup 库自动清理 30 天前的记录

兜底缓存：
  - 每次成功抓取后写 JSON
  - 下次抓取失败时读缓存替代
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

_DB_DIR = Path(__file__).resolve().parents[2] / "data"
_DB_PATH = _DB_DIR / "github_trending.db"
_CACHE_PATH = _DB_DIR / "github_trending_cache.json"

_DEDUP_DAYS = 7       # 同项目 N 天内不重复
_CLEANUP_DAYS = 30    # 清理 N 天前的记录


class TrendingCache:
    """GitHub Trending 去重 + 缓存。"""

    def __init__(self, db_path: str | Path = _DB_PATH, cache_path: str | Path = _CACHE_PATH):
        self._db_path = Path(db_path)
        self._cache_path = Path(cache_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── 去重 ──

    def _init_db(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS seen_repos ("
            "  repo TEXT NOT NULL,"
            "  push_date TEXT NOT NULL,"   # YYYY-MM-DD
            "  PRIMARY KEY (repo, push_date)"
            ")"
        )
        conn.commit()
        conn.close()

    def _cleanup(self):
        """清理超过 CLEANUP_DAYS 天的记录。"""
        cutoff = date.today().isoformat()
        # 简单实现：删最早 N 天的数据（不够精确但够用）
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(
            "DELETE FROM seen_repos WHERE push_date < date(?, '-' || ? || ' days')",
            (cutoff, _CLEANUP_DAYS)
        )
        conn.commit()
        conn.close()

    def is_duplicate(self, repo_name: str) -> bool:
        """repo_name 在 DEDUP_DAYS 内是否已推过。"""
        today = date.today().isoformat()
        cutoff = date.today().isoformat()  # 用 SQL 算
        conn = sqlite3.connect(str(self._db_path))
        cur = conn.execute(
            "SELECT 1 FROM seen_repos "
            "WHERE repo=? AND push_date >= date(?,'-'||?||' days')",
            (repo_name, today, _DEDUP_DAYS)
        )
        dup = cur.fetchone() is not None
        conn.close()
        return dup

    def mark_seen(self, repo_name: str):
        """标记 repo 今日已推。"""
        today = date.today().isoformat()
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(
            "INSERT OR IGNORE INTO seen_repos (repo, push_date) VALUES (?, ?)",
            (repo_name, today)
        )
        conn.commit()
        conn.close()
        self._cleanup()

    def filter_new(self, repos: list[dict]) -> list[dict]:
        """过滤掉近期已推过的项目，返回新项目。"""
        fresh = [r for r in repos if not self.is_duplicate(r["name"])]
        for r in fresh:
            self.mark_seen(r["name"])
        return fresh

    def mark_all_seen(self, repos: list[dict]):
        """批量标记（用于缓存恢复时避免重复推）。"""
        for r in repos:
            self.mark_seen(r["name"])

    # ── 缓存 ──

    def save_cache(self, repos: list[dict]):
        """保存成功抓取的结果到磁盘。"""
        data = {
            "timestamp": datetime.now().isoformat(),
            "repos": repos,
        }
        self._cache_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_cache(self) -> list[dict] | None:
        """读取上次成功缓存，返回 None 表示无缓存。"""
        if not self._cache_path.exists():
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return data.get("repos")
        except (json.JSONDecodeError, KeyError):
            return None

    @property
    def cache_age_hours(self) -> float:
        """缓存距今多少小时。"""
        if not self._cache_path.exists():
            return float("inf")
        mtime = self._cache_path.stat().st_mtime
        return (time.time() - mtime) / 3600
