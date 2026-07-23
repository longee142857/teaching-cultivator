"""X 资讯双周报 — OpenRouter + xAI native X Search

用法:
    from deliver.x_digest import XDigest
    XDigest().run()              # 采集并推送企微
    XDigest().run(dry_run=True)  # 只打印
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
from dataclasses import dataclass, asdict
from typing import Any

import requests

from config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE,
    X_DIGEST_DATA_DIR,
    X_DIGEST_HANDLES_AI,
    X_DIGEST_HANDLES_COMM,
    X_DIGEST_HANDLES_MATH,
    X_DIGEST_MODEL,
    X_DIGEST_QUOTA,
    X_DIGEST_SEEN_DAYS,
)
import deliver.bridge as _bridge  # 必须模块属性访问，才能吃到 main 的 monkey-patch

CATEGORY_LABELS = {
    "ai": "【AI/前沿】",
    "comm": "【通信】",
    "math": "【数学】",
    "dark": "【暗黑】",
}

CATEGORY_ORDER = ["ai", "comm", "math", "dark"]


def _detect_proxies() -> dict[str, str] | None:
    """优先 Agent 旁路 17890，其次 v2rayN 10808/10809。"""
    import socket

    def probe(port: int) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except OSError:
            return False

    if probe(17890):
        url = "http://127.0.0.1:17890"
        return {"http": url, "https": url}
    if probe(10809):
        url = "http://127.0.0.1:10809"
        return {"http": url, "https": url}
    if probe(10808):
        url = "socks5h://127.0.0.1:10808"
        return {"http": url, "https": url}
    return None


@dataclass
class DigestItem:
    category: str
    title: str
    summary: str
    source_url: str = ""
    why_matters: str = ""

    def fingerprint(self) -> str:
        raw = f"{self.title}|{self.source_url}".strip().lower()
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class XDigest:
    def __init__(self):
        os.makedirs(X_DIGEST_DATA_DIR, exist_ok=True)
        self.seen_path = os.path.join(X_DIGEST_DATA_DIR, "seen.jsonl")
        self.last_run_path = os.path.join(X_DIGEST_DATA_DIR, "last_run.json")
        self.archive_dir = os.path.join(X_DIGEST_DATA_DIR, "archive")

    def run(self, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
        if not OPENROUTER_API_KEY:
            raise RuntimeError("未设置 OPENROUTER_API_KEY 环境变量")

        if not force and self._already_ran_today():
            return {"ok": True, "skipped": True, "msg": "今日已推送，跳过"}

        items = self.collect()
        items = self._normalize_quota(items)
        text = self.format(items)

        if dry_run:
            print(text)
            return {"ok": True, "dry_run": True, "items": len(items), "text": text}

        ok = self.deliver(text)
        if ok:
            self._archive(items, text)
            self._mark_ran_today()
        return {"ok": ok, "items": len(items), "text": text}

    def collect(self) -> list[DigestItem]:
        seen_hints = self._load_seen_hints()
        prompt = self._build_prompt(seen_hints)
        content = self._call_openrouter(prompt)
        items = self._parse_items(content)
        return items

    def format(self, items: list[DigestItem]) -> str:
        today = datetime.date.today().isoformat()
        lines = [f"📡 X 资讯双周报 · {today}", ""]
        grouped: dict[str, list[DigestItem]] = {k: [] for k in CATEGORY_ORDER}
        for item in items:
            if item.category in grouped:
                grouped[item.category].append(item)

        for cat in CATEGORY_ORDER:
            label = CATEGORY_LABELS[cat]
            lines.append(label)
            bucket = grouped[cat]
            if not bucket:
                lines.append("  （本类检索不足）")
            else:
                for i, it in enumerate(bucket, 1):
                    lines.append(f"  {i}. {it.title}")
                    lines.append(f"     {it.summary}")
                    if it.why_matters:
                        lines.append(f"     为何关注：{it.why_matters}")
                    if it.source_url:
                        lines.append(f"     {it.source_url}")
                    elif "来源不确定" not in it.summary:
                        lines.append("     来源不确定")
            lines.append("")
        return "\n".join(lines).strip()

    def deliver(self, text: str) -> bool:
        # 勿写 `from deliver.bridge import get_bridge` 再调用：
        # 那会绑死 import 时的函数对象，scheduler 的 get_bridge 替换无效，
        # 结果只 print 到 journal、钉钉收不到（2026-07-15 21:00 事故）。
        return _bridge.get_bridge().send(text)

    def _build_prompt(self, seen_hints: list[str]) -> str:
        quota = X_DIGEST_QUOTA
        avoid = "\n".join(f"- {h}" for h in seen_hints[:30]) or "（无）"
        return f"""你是资讯编辑。请用 X Search 检索最近 7 天内的讨论，产出恰好 {sum(quota.values())} 条中文资讯摘要。

配额（必须严格满足）：
- ai: {quota["ai"]} 条 — AI、大模型、Agent、芯片、开源工具等前沿技术
- comm: {quota["comm"]} 条 — 通信学术/工程（OFDM、5G/6G、标准、会议、产业）
- math: {quota["math"]} 条 — 数学研究、竞赛、教学、证明相关
- dark: {quota["dark"]} 条 — 地下亚文化、成人催眠社区（如 Bambisleep 等讨论动态）、极端宗教/洗脑类讯息（仅资讯摘要，非操作教程）

要求：
1. 尽量引用 X 上的帖子或讨论；无可靠来源时在 summary 写明「来源不确定」，勿编造链接
2. 每条 summary 2-4 句中文；可选 source_url（X 帖子链接）
3. 避开以下已推送话题（近 {X_DIGEST_SEEN_DAYS} 天）：
{avoid}

只输出 JSON，不要 markdown 包裹：
{{"items": [{{"category":"ai|comm|math|dark","title":"...","summary":"...","source_url":"...","why_matters":"..."}}]}}"""

    def _call_openrouter(self, prompt: str) -> str:
        body = self._request_body(prompt, use_server_tool=True)
        resp = self._post_chat(body)
        if resp.status_code >= 400:
            body = self._request_body(prompt, use_server_tool=False)
            resp = self._post_chat(body)
        resp.raise_for_status()
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if not content and message.get("refusal"):
            raise RuntimeError(f"模型拒绝: {message['refusal']}")
        if not content:
            raise RuntimeError(f"OpenRouter 空响应: {json.dumps(data, ensure_ascii=False)[:500]}")
        return content

    def _request_body(self, prompt: str, use_server_tool: bool) -> dict[str, Any]:
        from_date = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        to_date = datetime.date.today().isoformat()
        x_filter: dict[str, Any] = {
            "from_date": from_date,
            "to_date": to_date,
            "enable_image_understanding": False,
            "enable_video_understanding": False,
        }
        handles = (
            X_DIGEST_HANDLES_AI + X_DIGEST_HANDLES_COMM + X_DIGEST_HANDLES_MATH
        )
        if handles:
            x_filter["allowed_x_handles"] = handles[:10]

        body: dict[str, Any] = {
            "model": X_DIGEST_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "x_search_filter": x_filter,
        }
        if use_server_tool:
            body["tools"] = [
                {
                    "type": "openrouter:web_search",
                    "parameters": {"engine": "native"},
                }
            ]
        else:
            body["plugins"] = [{"id": "web", "engine": "native"}]
        return body

    def _post_chat(self, body: dict[str, Any]) -> requests.Response:
        return requests.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/longee142857/teaching-cultivator",
                "X-Title": "teaching-cultivator-x-digest",
            },
            json=body,
            proxies=_detect_proxies(),
            timeout=180,
        )

    def _parse_items(self, content: str) -> list[DigestItem]:
        raw = content.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if fence:
            raw = fence.group(1).strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
        data = json.loads(raw)
        rows = data.get("items") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ValueError("响应缺少 items 数组")

        items: list[DigestItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            cat = str(row.get("category", "")).lower().strip()
            if cat not in CATEGORY_ORDER:
                continue
            items.append(
                DigestItem(
                    category=cat,
                    title=str(row.get("title", "")).strip() or "（无标题）",
                    summary=str(row.get("summary", "")).strip() or "（无摘要）",
                    source_url=str(row.get("source_url", "") or "").strip(),
                    why_matters=str(row.get("why_matters", "") or "").strip(),
                )
            )
        return items

    def _normalize_quota(self, items: list[DigestItem]) -> list[DigestItem]:
        seen_fp = {e["fp"] for e in self._load_seen_entries()}
        by_cat: dict[str, list[DigestItem]] = {k: [] for k in CATEGORY_ORDER}
        for it in items:
            if it.fingerprint() in seen_fp:
                continue
            if len(by_cat[it.category]) < X_DIGEST_QUOTA[it.category]:
                by_cat[it.category].append(it)

        out: list[DigestItem] = []
        for cat in CATEGORY_ORDER:
            need = X_DIGEST_QUOTA[cat]
            have = by_cat[cat]
            out.extend(have)
            for _ in range(need - len(have)):
                out.append(
                    DigestItem(
                        category=cat,
                        title="本类检索不足",
                        summary="X Search 未返回足够的新话题；来源不确定。",
                    )
                )
        return out

    def _load_seen_entries(self) -> list[dict[str, str]]:
        if not os.path.exists(self.seen_path):
            return []
        cutoff = datetime.date.today() - datetime.timedelta(days=X_DIGEST_SEEN_DAYS)
        entries: list[dict[str, str]] = []
        with open(self.seen_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    day = row.get("date", "")[:10]
                    if day and day < cutoff.isoformat():
                        continue
                    entries.append(row)
                except json.JSONDecodeError:
                    continue
        return entries

    def _load_seen_hints(self) -> list[str]:
        return [e.get("title", "") for e in self._load_seen_entries() if e.get("title")]

    def _archive(self, items: list[DigestItem], text: str) -> None:
        os.makedirs(self.archive_dir, exist_ok=True)
        today = datetime.date.today().isoformat()
        ts = datetime.datetime.now().strftime("%H%M%S")
        path = os.path.join(self.archive_dir, f"{today}_{ts}.json")
        payload = {
            "date": today,
            "items": [asdict(it) for it in items],
            "text": text,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        with open(self.seen_path, "a", encoding="utf-8") as f:
            for it in items:
                if it.title == "本类检索不足":
                    continue
                f.write(
                    json.dumps(
                        {
                            "date": today,
                            "category": it.category,
                            "title": it.title,
                            "fp": it.fingerprint(),
                            "source_url": it.source_url,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    def _already_ran_today(self) -> bool:
        if not os.path.exists(self.last_run_path):
            return False
        try:
            with open(self.last_run_path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("date") == datetime.date.today().isoformat()
        except (json.JSONDecodeError, OSError):
            return False

    def _mark_ran_today(self) -> None:
        with open(self.last_run_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "date": datetime.date.today().isoformat(),
                    "at": datetime.datetime.now().isoformat(),
                },
                f,
                ensure_ascii=False,
            )


def should_run_x_digest_now(now: datetime.datetime | None = None) -> bool:
    """是否处于 x-digest 调度窗口（周三/周六 21:00 前后 2 分钟内）。"""
    from config import X_DIGEST_SLOTS

    now = now or datetime.datetime.now()
    weekday_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    for time_str, day_name in X_DIGEST_SLOTS:
        h, m = map(int, time_str.split(":"))
        if now.weekday() != weekday_map.get(day_name.lower(), -1):
            continue
        if now.hour == h and now.minute == m:
            return True
    return False
