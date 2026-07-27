"""GitHub Push 模块 — 代理感知的 Git Push 工具

用法:
    from deliver.github_pusher import GithubPusher
    result = GithubPusher().push("D:/my-project", "更新内容")
    print(result["ok"])  # True / False

功能:
    - 自动检测并配置代理（socks5h 优先，HTTP 代理兜底）
    - 支持 HTTPS / SSH remote
    - 返回结构化结果，供 Agent 组织回复
"""
from __future__ import annotations
import os, subprocess, shlex, urllib.request


# ── 代理端口（与 tool-scripts/tools/v2ray/SKILL.md 一致） ──
_SOCKS5_PORT = 17890     # Agent 旁路（优先）
_V2RAYN_PORT = 10808     # v2rayN 日常
_HTTP_PROXY_PORT = 10809 # v2rayN HTTP 代理端口


def _detect_proxy() -> tuple[str, str]:
    """检测可用代理，返回 (proxy_url, proxy_type)。

    优先级:
        1. 环境变量 ALL_PROXY
        2. Agent 旁路 17890（socks5h）
        3. v2rayN 10808（socks5）
        4. v2rayN HTTP 10809
    """
    env = os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
    if env:
        if env.startswith("socks"):
            return (env, "socks5")
        return (env, "http")

    # Probe: Agent 旁路 17890
    if _probe_port(17890):
        return ("socks5h://127.0.0.1:17890", "socks5")

    # v2rayN 10808
    if _probe_port(10808):
        return ("socks5h://127.0.0.1:10808", "socks5")

    # v2rayN HTTP
    if _probe_port(10809):
        return ("http://127.0.0.1:10809", "http")

    return ("", "")


def _probe_port(port: int, timeout: float = 1.0) -> bool:
    """快速探测端口是否开放。"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except (OSError, socket.timeout):
        return False


def _git(*args: str, cwd: str, proxy_url: str = "") -> subprocess.CompletedProcess:
    """执行 git 命令，附带代理配置。"""
    cmd = ["git"]
    if proxy_url:
        cmd += ["-c", f"http.proxy={proxy_url}", "-c", f"https.proxy={proxy_url}"]
    cmd += list(args)

    env = os.environ.copy()
    if proxy_url and proxy_url.startswith("socks"):
        # git 需要 socks5h 协议前缀
        pass

    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def _ensure_proxy_sidecar() -> bool:
    """尝试拉起 Agent 旁路 17890。

    Windows → agent-proxy.bat；POSIX → agent-proxy.sh；
    失败时非静默警告（BIG-TEACH-012c #12）。
    """
    base = os.path.normpath(os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..",
        "tool-scripts", "tools",
    ))
    import sys
    is_win = sys.platform == "win32"
    script_name = "agent-proxy.bat" if is_win else "agent-proxy.sh"
    script = os.path.join(base, script_name)
    if not os.path.exists(script):
        print(f"[github_pusher] WARNING: proxy sidecar not found at {script} "
              f"(platform={sys.platform})")
        return False
    try:
        if is_win:
            runner = ["cmd.exe", "/c", script, "ensure"]
        else:
            runner = ["bash", script, "ensure"]
        subprocess.run(runner, capture_output=True, timeout=30)
        ok = _probe_port(17890)
        if not ok:
            print(f"[github_pusher] WARNING: proxy sidecar script ran but port 17890 "
                  f"not reachable (platform={sys.platform}, script={script})")
        return ok
    except Exception as e:
        print(f"[github_pusher] WARNING: proxy sidecar failed: {e} "
              f"(platform={sys.platform}, script={script})")
        return False


class GithubPusher:
    """GitHub Push 执行器，处理 Git 操作 + 代理 + 错误报告。"""

    def __init__(self):
        self._proxy_url: str = ""
        self._proxy_type: str = ""
        self._last_output: str = ""

    def push(
        self,
        repo_path: str,
        commit_msg: str = "",
        branch: str = "",
        use_auto_proxy: bool = True,
    ) -> dict:
        """推送指定仓库到 GitHub。

        参数:
            repo_path: 本地仓库绝对路径
            commit_msg: 提交信息（空则使用默认）
            branch: 分支名（空则自动检测当前分支）
            use_auto_proxy: 是否自动检测并配置代理

        返回:
            {"ok": bool, "msg": str, "branch": str, "commit": str, "remote": str}
        """
        repo_path = os.path.normpath(repo_path)
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            return {"ok": False, "msg": f"不是 Git 仓库: {repo_path}", "branch": "", "commit": "", "remote": ""}

        # ── 代理探测 ──
        if use_auto_proxy:
            self._proxy_url, self._proxy_type = _detect_proxy()
            if not self._proxy_url:
                # 旁路断了 → 尝试拉起
                if _ensure_proxy_sidecar():
                    self._proxy_url, self._proxy_type = _detect_proxy()

        proxy_url = self._proxy_url

        # ── 检查远程仓库 ──
        r = _git("remote", "-v", cwd=repo_path, proxy_url=proxy_url)
        remotes = r.stdout.strip()
        if "github.com" not in remotes and "git@github.com" not in remotes:
            return {"ok": False, "msg": f"未检测到 GitHub remote（当前 remote:\n{remotes or '无'}）", "branch": "", "commit": "", "remote": ""}

        # ── 检测当前分支 ──
        r = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_path, proxy_url=proxy_url)
        cur_branch = r.stdout.strip()
        push_branch = branch or cur_branch

        # ── 检查是否有变更 ──
        r = _git("status", "--porcelain", cwd=repo_path, proxy_url=proxy_url)
        has_changes = bool(r.stdout.strip())

        # ── 自动 add + commit（仅在有变更时） ──
        commit_hash = ""
        if has_changes:
            _git("add", "-A", cwd=repo_path, proxy_url=proxy_url)
            msg = commit_msg or f"auto push: {os.path.basename(repo_path)}"
            r = _git("commit", "-m", msg, "--allow-empty", cwd=repo_path, proxy_url=proxy_url)
            if r.returncode != 0:
                return {
                    "ok": False,
                    "msg": f"commit 失败:\n{r.stderr.strip() or r.stdout.strip()}",
                    "branch": push_branch, "commit": "", "remote": detect_remote(repo_path),
                }
        else:
            # 无变更 → 检查是否有未推送的 commit
            r = _git("log", "--oneline", f"origin/{push_branch}..HEAD", cwd=repo_path, proxy_url=proxy_url)
            if not r.stdout.strip():
                return {
                    "ok": True,
                    "msg": f"仓库已是最新，无需推送",
                    "branch": push_branch, "commit": "", "remote": detect_remote(repo_path),
                }

        # ── 获取 commit hash ──
        r = _git("rev-parse", "--short", "HEAD", cwd=repo_path, proxy_url=proxy_url)
        commit_hash = r.stdout.strip()

        # ── Push ──
        remote = detect_remote(repo_path)
        r = _git("push", "-u", "origin", push_branch, cwd=repo_path, proxy_url=proxy_url)

        if r.returncode == 0:
            return {
                "ok": True,
                "msg": f"✅ 推送成功到 {remote}\n分支: {push_branch}\n提交: {commit_hash}",
                "branch": push_branch, "commit": commit_hash, "remote": remote,
            }
        else:
            stderr = r.stderr.strip()
            # 代理相关错误 → 给出明确提示
            hints = ""
            if "Could not resolve host" in stderr or "Failed to connect" in stderr or "timed out" in stderr:
                hints = "\n⚠️ 疑似网络问题。尝试:\n  1. 打开 v2rayN 保证代理可用\n  2. 或运行 tool-scripts\\tools\\agent-proxy.bat ensure"
            return {
                "ok": False,
                "msg": f"❌ 推送失败:\n{stderr}{hints}",
                "branch": push_branch, "commit": commit_hash, "remote": remote,
            }

    @property
    def proxy_info(self) -> str:
        if self._proxy_url:
            return f"代理: {self._proxy_url} ({self._proxy_type})"
        return "代理: 未使用"


def detect_remote(repo_path: str) -> str:
    """检测仓库的 GitHub remote URL（可读格式）。"""
    r = _git("remote", "get-url", "origin", cwd=repo_path)
    url = r.stdout.strip()
    if not url or r.returncode != 0:
        return "（未设置 remote）"
    # SSH → HTTPS
    if url.startswith("git@"):
        url = url.replace(":", "/").replace("git@", "https://").replace(".git", "")
    return url
