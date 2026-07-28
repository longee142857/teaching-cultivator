"""请求级学员身份（ContextVar）。

多人模式下运行时有效 ID：
- 入站消息：senderStaffId
- 定时公共课：OWNER_STAFF_ID（课表策略账户）
- 无上下文且未配置 owner：拒绝写状态（测试可 bind 显式 id）
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator, Optional

_learner_id: ContextVar[Optional[str]] = ContextVar("learner_id", default=None)
# public_class | personal | schedule | None
_binding: ContextVar[Optional[str]] = ContextVar("grade_binding", default=None)


class LearnerIdentityError(RuntimeError):
    """缺少可用的 learner / staffId。"""


def get_learner_id() -> Optional[str]:
    v = _learner_id.get()
    return (v or "").strip() or None


def set_learner_id(staff_id: str | None) -> Token:
    sid = (staff_id or "").strip() or None
    return _learner_id.set(sid)


def reset_learner_id(token: Token) -> None:
    _learner_id.reset(token)


def get_binding() -> Optional[str]:
    v = _binding.get()
    return (v or "").strip() or None


def set_binding(binding: str | None) -> Token:
    b = (binding or "").strip() or None
    return _binding.set(b)


def reset_binding(token: Token) -> None:
    _binding.reset(token)


def owner_staff_id() -> str:
    """课表/公共课策略账户。优先 env OWNER_STAFF_ID。"""
    try:
        from config import OWNER_STAFF_ID
        return (OWNER_STAFF_ID or "").strip()
    except Exception:
        return ""


def current_user_id(*, allow_owner_fallback: bool = True) -> str:
    """当前 BKT / 个人状态写入用的 user_id。

    allow_owner_fallback=True：无入站上下文时用 OWNER（定时公共课选题）。
    """
    sid = get_learner_id()
    if sid:
        return sid
    if allow_owner_fallback:
        owner = owner_staff_id()
        if owner:
            return owner
    raise LearnerIdentityError(
        "无 learner 上下文且未配置 OWNER_STAFF_ID；拒绝使用全局 LEARNER_USER_ID"
    )


@contextmanager
def bind_learner(staff_id: str, *, binding: str | None = None) -> Iterator[str]:
    """绑定当前请求的学员身份。"""
    sid = (staff_id or "").strip()
    if not sid:
        raise LearnerIdentityError("staff_id 为空，禁止绑定")
    t1 = set_learner_id(sid)
    t2 = set_binding(binding) if binding is not None else None
    try:
        yield sid
    finally:
        if t2 is not None:
            reset_binding(t2)
        reset_learner_id(t1)


@contextmanager
def bind_owner_schedule() -> Iterator[str]:
    """定时公共课：绑定 owner 课表账户。"""
    owner = owner_staff_id()
    if not owner:
        raise LearnerIdentityError("定时公共课需要 OWNER_STAFF_ID")
    with bind_learner(owner, binding="schedule") as sid:
        yield sid
