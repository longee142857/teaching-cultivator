"""CLI: GitHub Trending 推送 (手动触发)

用法:
    python scripts/push_github_trending.py
"""
import sys, os, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from deliver.github_trending import fetch_trending, format_trending


def main() -> int:
    try:
        repos = fetch_trending()
        text = format_trending(repos)
        print(text)
        print(f"\n[x] 共 {len(repos)} 个项目")
        return 0
    except Exception as e:
        print(f"[失败] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
