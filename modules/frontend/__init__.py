"""前端挂载点。

权威静态页：``web/static/teaching-shell.html``（练习台；讲师 chat UI 在，agent 未接）。
HTTP：``deliver.practice_web``（默认 ``:8768``，路径 ``/practice``）。

约定：
- 深链 query: ``learner``, ``item`` (``i{n}``), ``push``
- API：见 ``docs/practice-api.md`` / ``GET /api/v1/agent/manifest``
- 本模块不实现页面逻辑；编排在 ``modules.bridge.practice_service``
"""

FRONTEND_OWNED_BY = "repo-owner"
MOUNT_HINT = "web/static/"
SHELL_FILE = "web/static/teaching-shell.html"
PRACTICE_PATH = "/practice"
TUTOR_STATUS = "stub_501"

__all__ = [
    "FRONTEND_OWNED_BY",
    "MOUNT_HINT",
    "PRACTICE_PATH",
    "SHELL_FILE",
    "TUTOR_STATUS",
]
