"""CLI: X 资讯双周报

用法:
    python scripts/push_x_digest.py              # 立即采集并推送
    python scripts/push_x_digest.py --dry-run    # 只打印，不推企微
    python scripts/push_x_digest.py --force      # 忽略今日已推限制
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from deliver.push_hub import run


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    try:
        result = run("x_digest", dry_run=dry_run, force=force)
    except Exception as e:
        print(f"[x-digest] 失败: {e}")
        return 1

    if result.get("skipped"):
        print(f"[x-digest] {result.get('msg', '跳过')}")
        return 0

    if dry_run:
        print(f"\n[x-digest] dry-run 完成，共 {result.get('items', 0)} 条")
        return 0

    if result.get("ok"):
        print(f"[x-digest] 推送成功，共 {result.get('items', 0)} 条")
        return 0

    print("[x-digest] 推送失败")
    if result.get("text"):
        print(result["text"])
    return 1


if __name__ == "__main__":
    sys.exit(main())
