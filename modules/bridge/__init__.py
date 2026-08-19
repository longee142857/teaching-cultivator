"""桥 — 前端 / DSH 调用面（通知与 IM 全量 UX 分离）。

本轮提供：
- ``LearnerBridge``：params / active item / practice desk / notify 深链
- ``practice_service``：teaching-shell 对齐的 bootstrap / submit
- ``mount_capability_routes``：挂到既有 system_api 白名单的新工具名

旧 ``deliver.system_api`` 仍可用；新调用方优先本包。
讲师 chat（tutor agent）本轮仅暴露 501 契约，不实现。
"""
from __future__ import annotations

import os
from typing import Any, Optional

from modules.capability import CapabilityService, build_learner_params
from modules.notify import build_deep_link, notify_new_item, get_default_channel

from modules.bridge import practice_service
from modules.bridge.practice_service import (
    agent_manifest,
    practice_bootstrap,
    practice_get_item,
    practice_submit,
)


class LearnerBridge:
    """编排 store + capability + practice；不直接发长文讲解。"""

    def __init__(self, store=None, *, frontend_base: str | None = None):
        if store is None:
            from modules.store import get_store

            store = get_store()
        self.store = store
        self.capability = CapabilityService(store)
        self.frontend_base = frontend_base if frontend_base is not None else os.environ.get(
            "FRONTEND_BASE_URL", ""
        )

    def get_learner_params(self, user_id: str, **kwargs) -> dict[str, Any]:
        params = self.capability.params(user_id, **kwargs)
        return params.to_dict()

    def get_evidence_bundle(self, user_id: str, **kwargs) -> dict[str, Any]:
        return self.capability.evidence_bundle(user_id, **kwargs)

    def get_active_item(self, learner_id: str) -> Optional[dict[str, Any]]:
        """当前题：SQLite 权威；返回给前端，不经 IM 渲染。"""
        if hasattr(self.store, "get_latest_push"):
            row = self.store.get_latest_push(learner_id)
            if row:
                return row
        try:
            from learner.active_question import get_active_question

            return get_active_question(learner_id) or None
        except Exception:
            return None

    def practice_bootstrap(self, learner_id: str, *, day: str | None = None) -> dict[str, Any]:
        return practice_service.bootstrap(learner_id, day=day, store=self.store)

    def practice_submit(
        self,
        learner_id: str,
        *,
        answer: str,
        item: str | int | None = None,
        push: str | int | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        return practice_service.submit(
            learner_id,
            answer=answer,
            item=item,
            push=push,
            store=self.store,
            mode=mode,
        )

    def notify_item_ready(
        self,
        learner_id: str,
        *,
        subject: str,
        item_id: int | None = None,
        push_id: int | None = None,
        kp: str = "",
        channel=None,
    ) -> bool:
        ch = channel or get_default_channel()
        return notify_new_item(
            ch,
            learner_id=learner_id,
            subject=subject,
            item_id=item_id,
            push_id=push_id,
            frontend_base=self.frontend_base,
            kp=kp,
        )

    def practice_link(
        self,
        learner_id: str,
        *,
        item_id: int | None = None,
        push_id: int | None = None,
    ) -> str:
        return build_deep_link(
            self.frontend_base,
            path="/practice",
            learner_id=learner_id,
            item_id=item_id,
            push_id=push_id,
        )


def get_learner_params(user_id: str = "", **kwargs) -> dict[str, Any]:
    """system_api / DSH 可挂的工具函数。user_id 缺省时用 bind_learner 上下文。"""
    uid = (user_id or "").strip()
    if not uid:
        try:
            from learner.context import current_user_id

            uid = current_user_id()
        except Exception:
            uid = ""
    if not uid:
        raise ValueError("missing user_id (pass param or X-Learner-Id)")
    return LearnerBridge().get_learner_params(uid, **kwargs)


def get_capability_evidence(user_id: str = "", **kwargs) -> dict[str, Any]:
    uid = (user_id or "").strip()
    if not uid:
        try:
            from learner.context import current_user_id

            uid = current_user_id()
        except Exception:
            uid = ""
    if not uid:
        raise ValueError("missing user_id (pass param or X-Learner-Id)")
    return LearnerBridge().get_evidence_bundle(uid, **kwargs)


def capability_whitelist() -> dict[str, Any]:
    """可并入 deliver.system_api.WHITELIST 的新工具。"""
    return {
        "get_learner_params": get_learner_params,
        "get_capability_evidence": get_capability_evidence,
        "practice_bootstrap": practice_bootstrap,
        "practice_get_item": practice_get_item,
        "practice_submit": practice_submit,
        "practice_agent_manifest": agent_manifest,
    }


__all__ = [
    "LearnerBridge",
    "agent_manifest",
    "build_learner_params",
    "capability_whitelist",
    "get_capability_evidence",
    "get_learner_params",
    "practice_bootstrap",
    "practice_get_item",
    "practice_service",
    "practice_submit",
]
