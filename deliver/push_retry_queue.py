"""推送失败重试队列（BIG-TEACH-012c #8）

持久化 data/push-retry-queue.jsonl，每条含待重试的推送载荷。
scheduler 每轮消费队列：最多重试 N=2 次，间隔 30min / 60min。
耗尽则移入 data/push-retry-dead.jsonl 并打日志。
"""
from __future__ import annotations

import json
import os
import time
import logging
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR

logger = logging.getLogger(__name__)

def _retry_queue_path() -> str:
    return os.path.join(DATA_DIR, "push-retry-queue.jsonl")


def _dead_letter_path() -> str:
    return os.path.join(DATA_DIR, "push-retry-dead.jsonl")

MAX_RETRIES = 2
# 第 1 次重试等 30 分钟后，第 2 次再等 60 分钟
RETRY_INTERVAL_MINUTES: list[int] = [30, 60]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_queue() -> list[dict]:
    path = _retry_queue_path()
    if not os.path.isfile(path):
        return []
    entries: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return entries


def _save_queue(entries: list[dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(_retry_queue_path(), "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    except OSError:
        logger.error("cannot write retry queue")


def _append_dead(entry: dict, reason: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        dead = {**entry, "dead_ts": _now_iso(), "dead_reason": reason}
        with open(_dead_letter_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(dead, ensure_ascii=False) + "\n")
    except OSError:
        logger.error("cannot write dead letter queue")


def enqueue_retry(subject: str, content: str = "") -> None:
    """推送失败后入队。content 为已生成的推送正文（空则在重试时允许重新 cultivate 一次）。"""
    entry: dict[str, Any] = {
        "subject": subject,
        "attempt": 0,
        "max_attempts": MAX_RETRIES,
        "first_attempt_ts": _now_iso(),
        "last_attempt_ts": _now_iso(),
        "content": content,
        "next_retry_ts": "",
    }
    entries = _load_queue()
    # 同一 subject 已有活跃条目则不重复入队（避免堆积）
    for existing in entries:
        if existing.get("subject") == subject and existing.get("attempt", 0) <= MAX_RETRIES:
            logger.info(
                "[retry-queue] subject=%s already queued (attempt=%d), skip duplicate",
                subject, existing.get("attempt", 0),
            )
            return
    entries.append(entry)
    _save_queue(entries)
    logger.info("[retry-queue] enqueued subject=%s", subject)


def _is_ready_for_retry(entry: dict) -> bool:
    """检查条目是否到达重试时间。"""
    next_ts = entry.get("next_retry_ts", "")
    if not next_ts:
        return True  # 首次重试立即执行
    try:
        next_dt = datetime.fromisoformat(next_ts)
        return datetime.now(timezone.utc) >= next_dt
    except (ValueError, TypeError):
        return True


def process_retry_queue(bot) -> int:
    """消费就绪的重试条目。返回本轮回溯数。"""
    entries = _load_queue()
    if not entries:
        return 0

    remain: list[dict] = []
    processed = 0
    for entry in entries:
        subject = entry.get("subject", "")
        attempt = int(entry.get("attempt", 0))
        content = entry.get("content", "") or ""

        if attempt > MAX_RETRIES:
            _append_dead(entry, f"exhausted after {attempt} attempts")
            logger.warning("[retry-queue] subject=%s exhausted after %d attempts", subject, attempt)
            continue

        if not _is_ready_for_retry(entry):
            remain.append(entry)
            continue

        attempt += 1
        logger.info("[retry-queue] retry subject=%s attempt=%d/%d", subject, attempt, MAX_RETRIES)

        # 有保存的内容则直接重发；无则尝试重新 cultivate（仅第一次）
        if content:
            ok = _redeliver_saved(bot, subject, content)
        else:
            ok = _recultivate_once(bot, subject)

        if ok:
            logger.info("[retry-queue] subject=%s retry OK", subject)
            processed += 1
            # 重试成功不出队（若下次推送再失败会重新入队）
            continue

        # 重试失败：更新状态 + 调度下次
        if attempt <= MAX_RETRIES:
            interval = RETRY_INTERVAL_MINUTES[attempt - 1]
            next_ts = datetime.now(timezone.utc)
            import datetime as dt_mod
            next_ts += dt_mod.timedelta(minutes=interval)
            entry["attempt"] = attempt
            entry["last_attempt_ts"] = _now_iso()
            entry["next_retry_ts"] = next_ts.isoformat()
            logger.info("[retry-queue] subject=%s next retry in %d min", subject, interval)
            remain.append(entry)
        else:
            _append_dead(entry, f"exhausted after {attempt} retries")
            logger.warning("[retry-queue] subject=%s dead after %d retries", subject, attempt)

    _save_queue(remain)
    return processed


def _redeliver_saved(bot, subject: str, content: str) -> bool:
    """用已保存的内容重试推送。"""
    try:
        import deliver.bridge as db
        bridge = bot._make_push_bridge()
        orig = db.get_bridge
        db.get_bridge = lambda: bridge
        try:
            ok = bridge.send(content)
            return ok
        finally:
            db.get_bridge = orig
    except Exception as e:
        logger.error("[retry-queue] redeliver error: %s", e)
        return False


def _recultivate_once(bot, subject: str) -> bool:
    """无保存载荷时重新培养一次。"""
    try:
        bot.push_cultivate(subject)
        return True
    except Exception as e:
        logger.error("[retry-queue] recultivate error: %s", e)
        return False
