"""本地验收：误 escalate + answer meta 清理。"""
from __future__ import annotations
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import config  # noqa: F401 — inject KB lib path

from cultivate import (
    _get_consecutive_failures,
    _kp_history_match,
    _remap_dead_escalate,
)
from intervention import InterventionDecision
from math_format import sanitize_answer_meta


class _FakeBKT:
    def __init__(self, history):
        self._h = history

    def get_user_history(self, _uid):
        return self._h


def test_no_global_fallback():
    hist = [
        {"knowledge_point": "多元函数偏导数、复合函数求导法则", "correct": False},
        {"knowledge_point": "多元函数偏导数的计算", "correct": False},
        {"knowledge_point": "多元复合函数求偏导", "correct": False},
    ]
    n = _get_consecutive_failures("wx_123", _FakeBKT(hist), "矩阵与初等变换")
    assert n == 0, n
    print("ok no_global_fallback", n)


def test_alias_match_counts():
    # 别名命中；他科正确不打断本 L2 连续错
    hist = [
        {"knowledge_point": "矩阵初等变换", "correct": False},
        {"knowledge_point": "矩阵初等变换", "correct": False},
        {"knowledge_point": "其他无关知识点", "correct": True},
    ]
    n = _get_consecutive_failures("wx_123", _FakeBKT(hist), "矩阵与初等变换")
    assert n == 2, n
    hist2 = [
        {"knowledge_point": "矩阵初等变换", "correct": True},
        {"knowledge_point": "矩阵初等变换", "correct": False},
        {"knowledge_point": "矩阵初等变换", "correct": False},
        {"knowledge_point": "矩阵初等变换", "correct": False},
    ]
    n2 = _get_consecutive_failures("wx_123", _FakeBKT(hist2), "矩阵与初等变换")
    assert n2 == 3, n2
    print("ok alias_match_counts", n, n2)


def test_remap_escalate():
    d = InterventionDecision(
        "escalate", "basic", "矩阵与初等变换: 连续 4 次异常，需 Claude 排查", 1
    )
    out = _remap_dead_escalate(d)
    assert out.type == "explain"
    assert out.difficulty == "basic"
    assert "Claude" not in out.reason
    print("ok remap", out.reason)


def test_sanitize():
    ans = (
        "**正确选项**：(C)\n\n**解析**：\n1. 秩为2。\n\n"
        "为避免歧义，我们选择(C)。重新出题：设矩阵..."
    )
    clean = sanitize_answer_meta(ans)
    assert "重新出题" not in clean
    assert "正确选项" in clean
    assert "(C)" in clean
    print("ok sanitize", len(clean))


def test_kp_match():
    assert _kp_history_match("矩阵初等变换", "矩阵与初等变换")
    assert not _kp_history_match("多元函数偏导数", "矩阵与初等变换")
    print("ok kp_match")


if __name__ == "__main__":
    test_no_global_fallback()
    test_alias_match_counts()
    test_remap_escalate()
    test_sanitize()
    test_kp_match()
    print("ALL PASS")
