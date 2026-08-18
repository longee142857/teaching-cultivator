"""存储模块 facade — SQLite SSOT。

权威实现仍在 ``learner.db``；新代码经本包导入，便于后续物理搬迁。
"""
from __future__ import annotations

from learner.db import Store, get_store, now_utc_iso, TZ_SHANGHAI

__all__ = ["Store", "TZ_SHANGHAI", "get_store", "now_utc_iso"]
