"""统一 Push 子系统 — GitHub Push 门面（X Digest 已关闭）

用法:
    from deliver.push_hub import run
    result = run("github", repo_path="D:/my-project", commit_msg="update")

返回至少包含: {"ok": bool, "kind": str, "msg": str}
"""

from deliver.github_pusher import GithubPusher


def run(kind: str, **kwargs) -> dict:
    """统一推送入口。

    kind="github":
        → GithubPusher().push(repo_path, commit_msg, branch)
        kwargs: repo_path, commit_msg, branch

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

    raise ValueError(f"不支持的推送类型: {kind!r}，可选: github")
