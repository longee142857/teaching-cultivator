"""CLI: GitHub Trending 推送 (手动触发)

用法:
    python scripts/push_github_trending.py                    # 打印到 stdout
    python scripts/push_github_trending.py --webhook <url>    # 推钉钉 webhook
    python scripts/push_github_trending.py --no-dedup          # 不去重
    python scripts/push_github_trending.py --no-cache          # 失败不兜底
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from deliver.github_trending import fetch_formatted, fetch_trending, format_trending, translate_descriptions


def main() -> int:
    args = _parse_args()

    if args.simple:
        # 旧模式：手动分步
        try:
            repos = fetch_trending()
            translate_descriptions(repos)
            text = format_trending(repos)
            print(text)
            print(f"\n[x] 共 {len(repos)} 个项目")
            return 0
        except Exception as e:
            print(f"[失败] {e}", file=sys.stderr)
            return 1

    # 新模式：一站式
    try:
        text, n = fetch_formatted(
            max_count=10,
            channel="stdout" if not args.webhook else "dingtalk",
            use_cache=not args.no_cache,
            skip_dup=not args.no_dedup,
        )
        if not text:
            print("[跳过] 无新项目（7天内已推过）" if not args.no_dedup else "[空] 抓取结果为空")
            return 0

        if args.webhook:
            from deliver.github_trending.sender import send_trending
            ok = send_trending(text, channel="dingtalk", webhook_url=args.webhook)
            print(f"[{'OK' if ok else '失败'}] 推送到 webhook，{n} 个项目")
        else:
            print(text)
            print(f"\n[x] 共 {n} 个项目")

        return 0
    except Exception as e:
        print(f"[失败] {e}", file=sys.stderr)
        return 1


def _parse_args():
    import argparse
    p = argparse.ArgumentParser(description="GitHub Trending 推送")
    p.add_argument("--webhook", "-w", help="钉钉 webhook URL（不传则打 stdout）")
    p.add_argument("--no-dedup", action="store_true", help="不去重（重复推已有项目）")
    p.add_argument("--no-cache", action="store_true", help="失败不读缓存")
    p.add_argument("--simple", "-s", action="store_true", help="旧模式：手动 fetch→translate→format")
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(main())
