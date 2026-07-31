"""两阶段出题：模型档位 + polish 模板（不调真 LLM）。"""
from __future__ import annotations
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from decide.router import select_model, REASONING_EFFORT_MAX
from prompts.prompt_builder import PromptBuilder


def test_model_tiers():
    for t in ("author", "generate", "grade", "explain"):
        cfg = select_model(t)
        assert cfg.model == "deepseek-v4-pro", t
        assert cfg.provider == "deepseek", t
        assert cfg.thinking is True, t
        assert cfg.effort == REASONING_EFFORT_MAX == "max", t
    for t in ("polish", "orchestrate"):
        cfg = select_model(t)
        assert cfg.model == "deepseek-v4-flash", t
        assert cfg.provider == "deepseek", t
        assert cfg.thinking is False, t
    flash = select_model("other")
    assert flash.model == "deepseek-v4-flash"
    assert flash.thinking is False
    print("OK model tiers (pro author/grade; flash polish)")


def test_polish_template():
    b = PromptBuilder()
    sys_p, user_p = b.build_polish(
        draft_body="概念…\n\n(A) 1\n(B) 2",
        answer_body="正确选项：(B)\n解析：…",
    )
    assert "文案编辑" in sys_p or "整理" in sys_p
    assert "概念…" in user_p
    assert "正确选项：(B)" in user_p
    assert "{{" not in sys_p and "{{" not in user_p
    print("OK polish template")


def test_author_templates_exist():
    b = PromptBuilder()
    for t in ("push", "explain", "review"):
        s, u = b.build(
            subject_cn="数学一",
            kp="极限",
            difficulty_cn="基础",
            action_cn="出题",
            reason="极限: test",
            decision_type=t,
            topic_desc="数学一考研",
        )
        assert "验算" in s or "验算" in u
        assert "{{" not in s
        print(f"OK author template {t}")


if __name__ == "__main__":
    test_model_tiers()
    test_polish_template()
    test_author_templates_exist()
    print("ALL PASS")
