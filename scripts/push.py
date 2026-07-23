"""CLI: 统一推送入口

用法:
    py -3 scripts/push.py github [repo] [msg] [branch]
    py -3 scripts/push.py x-digest [--dry-run] [--force]
    py -3 scripts/push.py          # 打印 usage，exit 0
    py -3 scripts/push.py --help   # exit 0
"""
import sys, os, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from deliver.push_hub import run


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="push",
        description="统一推送子系统 — GitHub Push + X Digest",
    )
    sub = parser.add_subparsers(dest="kind", title="推送类型")

    # github 子命令
    gh = sub.add_parser("github", help="推送到 GitHub")
    gh.add_argument(
        "repo", nargs="?",
        default=os.path.dirname(os.path.dirname(__file__)),
        help="仓库路径（默认 teaching-cultivator）",
    )
    gh.add_argument("msg", nargs="?", default="", help="commit 信息")
    gh.add_argument("branch", nargs="?", default="", help="分支名")

    # x-digest 子命令
    xd = sub.add_parser("x-digest", help="X 资讯双周报")
    xd.add_argument("--dry-run", action="store_true", help="只打印，不推送")
    xd.add_argument("--force", action="store_true", help="忽略今日已推限制")

    args = parser.parse_args()

    if not args.kind:
        parser.print_usage()
        return 0

    if args.kind == "github":
        result = run("github", repo_path=args.repo, commit_msg=args.msg, branch=args.branch)
    elif args.kind == "x-digest":
        try:
            result = run("x_digest", dry_run=args.dry_run, force=args.force)
        except Exception as e:
            print(f"[x-digest] 失败: {e}")
            return 1
    else:
        parser.print_usage()
        return 0

    print(result.get("msg", ""))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
