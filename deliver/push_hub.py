"""统一 Push 子系统 — GitHub Push + X Digest 共享门面

用法:
    from deliver.push_hub import run
    result = run("github", repo_path="D:/my-project", commit_msg="update")
    result = run("x_digest", dry_run=True)

返回至少包含: {"ok": bool, "kind": str, "msg": str}
"""

from deliver.github_pusher import GithubPusher
from deliver.x_digest import XDigest


def run(kind: str, **kwargs) -> dict:
    """统一推送入口。

    kind="github":
        → GithubPusher().push(repo_path, commit_msg, branch)
        kwargs: repo_path, commit_msg, branch

    kind="x_digest":
        → XDigest().run(dry_run, force)
        kwargs: dry_run, force

    返回至少包含 {"ok": bool, "kind": str, "msg": str}，
    并保留被委托方法返回的其他字段。
    """
    if kind == "github":
        repo_path = kwargs.get("repo_path", "")
        commit_msg = kwargs.get("commit_msg", "")
        branch = kwargs.get("branch", "")
        result = GithubPusher().push(repo_path, commit_msg, branch)
        result["kind"] = "github"
        return result

    if kind == "x_digest":
        dry_run = kwargs.get("dry_run", False)
        force = kwargs.get("force", False)
        result = XDigest().run(dry_run=dry_run, force=force)
        result["kind"] = "x_digest"
        # 确保 msg 始终存在（XDigest.run() 在 skip/dry_run/success 场景下不总是带 msg）
        if "msg" not in result:
            if result.get("skipped"):
                result["msg"] = "今日已推送，跳过"
            elif result.get("dry_run"):
                result["msg"] = f"dry-run 完成，共 {result.get('items', 0)} 条"
            elif result.get("ok"):
                result["msg"] = f"推送成功，共 {result.get('items', 0)} 条"
            else:
                result["msg"] = "推送失败"
        return result

    raise ValueError(f"不支持的推送类型: {kind!r}，可选: github, x_digest")
