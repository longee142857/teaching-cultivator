"""前端挂载点。

答题与讲解 UI 由仓库所有者在独立前端实现；本包只约定深链与资源目录。

约定：
- 深链 query: ``learner``, ``item``, ``push``
- 静态资源可继续放仓根 ``web/static/``（exam.html 等）
- 本模块不实现页面
"""

FRONTEND_OWNED_BY = "repo-owner"
MOUNT_HINT = "web/static/"

__all__ = ["FRONTEND_OWNED_BY", "MOUNT_HINT"]
