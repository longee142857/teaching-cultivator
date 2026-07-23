"""单元：resolve_kp / normalize_kp_for_grade / 多概念不误伤。"""
from __future__ import annotations
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from learner.kp_registry import resolve_kp, normalize_kp_for_grade, reload_registry

reload_registry()


def test_multi_concept_prefers_first_segment():
    hint = "多元函数偏导数、复合函数求导法则、微分方程的建立与求解。"
    got = resolve_kp("math", hint)
    assert got == "多元函数微分学", got
    print("OK multi-concept →", got)


def test_matrix_alias():
    assert resolve_kp("math", "矩阵初等变换") == "矩阵与初等变换"
    assert resolve_kp("math", "矩阵与初等变换") == "矩阵与初等变换"
    print("OK matrix alias")


def test_preferred_overrides_llm_dump():
    dump = "多元函数偏导数、常微分方程、定积分"
    got = normalize_kp_for_grade(
        "math", dump, preferred="矩阵与初等变换"
    )
    assert got == "矩阵与初等变换", got
    print("OK preferred overrides dump →", got)


def test_short_ode():
    assert resolve_kp("math", "微分方程") == "常微分方程"
    print("OK short ode")


if __name__ == "__main__":
    test_multi_concept_prefers_first_segment()
    test_matrix_alias()
    test_preferred_overrides_llm_dump()
    test_short_ode()
    print("\nALL PASSED")
