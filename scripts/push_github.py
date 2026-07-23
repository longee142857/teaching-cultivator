"""CLI: GitHub Push 入口

用法:
    python scripts/push_github.py                         # 推 teaching-cultivator 自身
    python scripts/push_github.py D:/some/project          # 推指定仓库
    python scripts/push_github.py D:/some/project "msg"    # 推指定仓库 + 自定义 commit
    python scripts/push_github.py D:/some/project "msg" main  # 指定分支
"""
import sys, os, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from deliver.push_hub import run


def main():
    repo_path = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(__file__))
    commit_msg = sys.argv[2] if len(sys.argv) > 2 else ""
    branch = sys.argv[3] if len(sys.argv) > 3 else ""

    result = run("github", repo_path=repo_path, commit_msg=commit_msg, branch=branch)
    print(result["msg"])
    if result["ok"]:
        print(f"链接: {result.get('remote', '')}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
