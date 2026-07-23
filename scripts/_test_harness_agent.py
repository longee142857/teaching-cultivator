"""回归：Harness Agent 的 loop / blocks / transcript / on_new_push（不调真 LLM）。

用法:
  cd ai-systems/teaching-cultivator
  python scripts/_test_harness_agent.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _isolate_data(tmpdir: str):
    """把 DATA_DIR 指到临时目录，避免污染真实 data/。"""
    import config

    config.DATA_DIR = tmpdir
    # 子模块在 import 时可能已绑定旧路径 — 重新绑定
    import agent.memory_blocks as mb
    import agent.transcript as tr

    mb.DATA_DIR = tmpdir
    mb.BLOCKS_PATH = os.path.join(tmpdir, "memory_blocks.json")
    mb.LAST_PUSH_PATH = os.path.join(tmpdir, "last_push.json")
    tr.DATA_DIR = tmpdir
    tr.TRANSCRIPT_PATH = os.path.join(tmpdir, "agent_transcript.json")
    tr.LEGACY_MEMORY_PATH = os.path.join(tmpdir, "agent_memory.json")
    return mb, tr


def test_memory_blocks_and_on_new_push():
    with tempfile.TemporaryDirectory() as td:
        mb, tr = _isolate_data(td)
        blocks = mb.MemoryBlocks()
        assert blocks.phase == mb.PHASE_IDLE

        q = "求极限 $\\lim_{x\\to 0} \\frac{\\sin x}{x}$"
        blocks.on_new_push(q, subject="math", kp="极限与连续")
        assert blocks.phase == mb.PHASE_AWAITING
        assert blocks._data["active_question"]["char_len"] == len(q)
        assert any(t["id"] == "await_answer" for t in blocks.todos)

        blocks.apply_tool_effects("list_recent_entries")
        assert blocks.phase == mb.PHASE_RETRIEVING
        assert any(t["id"] == "fetch_full" for t in blocks.todos)

        blocks.apply_tool_effects("find_record_entry")
        assert any(
            t["id"] == "fetch_full" and t["status"] == "completed" for t in blocks.todos
        )

        blocks.apply_tool_effects("grade_answer")
        assert blocks.phase == mb.PHASE_REVIEWING

        text = blocks.format_blocks_for_system()
        assert "Core Memory Blocks" in text
        assert "active_question" in text
        rem = blocks.format_reminder(last_tools=["list_recent_entries"], step=1)
        assert "list_recent_entries" in rem
        print("OK memory_blocks")


def test_transcript_structure_and_condense():
    with tempfile.TemporaryDirectory() as td:
        mb, tr = _isolate_data(td)
        t = tr.Transcript()
        t.append_messages([
            {"role": "user", "content": "最近出过什么题"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "list_recent_entries", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "1. 2026-07-16 #1 math"},
            {"role": "assistant", "content": "最近有一道数学题。"},
        ])
        assert any(m.get("tool_calls") for m in t.messages)
        assert any(m.get("role") == "tool" for m in t.messages)

        # 再塞一批后 condense
        for i in range(10):
            t.append_messages([
                {"role": "user", "content": f"追问{i}"},
                {"role": "assistant", "content": f"答{i}"},
            ])
        before = len(t.messages)
        t.condense(keep_recent=4)
        assert len(t.messages) <= 5  # 1 summary + 4 recent
        assert t.messages[0]["role"] == "assistant"
        assert "摘要" in t.messages[0]["content"] or "工具" in t.messages[0]["content"]
        print(f"OK transcript (before_condense~{before}, after={len(t.messages)})")


def test_legacy_migrate():
    with tempfile.TemporaryDirectory() as td:
        mb, tr = _isolate_data(td)
        legacy = {
            "updated_at": __import__("time").time(),
            "messages": [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好，我是瑞贝卡"},
            ],
        }
        with open(tr.LEGACY_MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(legacy, f)
        t = tr.Transcript()
        assert len(t.messages) == 2
        assert os.path.isfile(tr.TRANSCRIPT_PATH)
        print("OK legacy migrate")


def test_harness_multi_step_loop_mocked():
    """Mock _call_llm：第一步 list，第二步 find，第三步纯文本。"""
    with tempfile.TemporaryDirectory() as td:
        mb, tr = _isolate_data(td)
        # 延迟 import agent（依赖已改 DATA_DIR）
        import importlib
        import agent.agent as ag

        importlib.reload(ag)

        agent = ag.TeachingAgent(bot=None)
        # 重新挂临时 blocks/transcript
        agent.blocks = mb.MemoryBlocks()
        agent.transcript = tr.Transcript()

        calls = {"n": 0}
        progress_log = []

        def fake_llm(messages):
            calls["n"] += 1
            n = calls["n"]
            if n == 1:
                return {
                    "choices": [{
                        "message": {
                            "content": "",
                            "tool_calls": [{
                                "id": "call_list",
                                "type": "function",
                                "function": {
                                    "name": "list_recent_entries",
                                    "arguments": '{"days": 3}',
                                },
                            }],
                        }
                    }]
                }
            if n == 2:
                return {
                    "choices": [{
                        "message": {
                            "content": "",
                            "tool_calls": [{
                                "id": "call_find",
                                "type": "function",
                                "function": {
                                    "name": "find_record_entry",
                                    "arguments": '{"date": "2026-07-16", "num": 1}',
                                },
                            }],
                        }
                    }]
                }
            return {
                "choices": [{
                    "message": {
                        "content": "今天早上那道多元函数题干如下：……（全文）",
                    }
                }]
            }

        def fake_run_tool(name, args):
            if name == "list_recent_entries":
                return "2026-07-16 #1 math 多元函数\n2026-07-15 #1 comm"
            if name == "find_record_entry":
                return "题目：设 f(x,y)=… 求偏导"
            return f"ok:{name}"

        agent._call_llm = fake_llm  # type: ignore
        agent._run_tool = fake_run_tool  # type: ignore

        reply = agent.handle(
            "今天早上那道多元函数",
            on_progress=lambda s: progress_log.append(s),
        )
        assert "多元函数" in reply or "偏导" in reply or "题干" in reply
        assert calls["n"] == 3, f"expected 3 LLM calls, got {calls['n']}"
        # transcript 应含 tool_calls
        roles = [m["role"] for m in agent.transcript.messages]
        assert "tool" in roles
        assert any(m.get("tool_calls") for m in agent.transcript.messages)
        assert len(progress_log) >= 1
        print(f"OK multi-step loop (llm_calls={calls['n']}, progress={progress_log})")


def test_on_new_push_keeps_transcript():
    with tempfile.TemporaryDirectory() as td:
        mb, tr = _isolate_data(td)
        import importlib
        import agent.agent as ag
        importlib.reload(ag)

        agent = ag.TeachingAgent(bot=None)
        agent.blocks = mb.MemoryBlocks()
        agent.transcript = tr.Transcript()
        agent.transcript.append_messages([
            {"role": "user", "content": "上一题答案是什么"},
            {"role": "assistant", "content": "上一题是极限，答案是 1"},
            {"role": "user", "content": "再讲一遍"},
            {"role": "assistant", "content": "好的，极限定义是…"},
            {"role": "user", "content": "明白了"},
            {"role": "assistant", "content": "行，有问题再说"},
        ])
        before = len(agent.transcript.messages)
        agent.on_new_push("新题：傅里叶级数展开", subject="math")
        after = len(agent.transcript.messages)
        assert after > 0, "transcript should not be cleared"
        assert agent.blocks.phase == mb.PHASE_AWAITING
        assert "傅里叶" in agent.blocks._data["active_question"]["preview"]
        # condense keep_recent=4 → 最多 5（1+4）
        assert after <= 5
        assert before >= after
        print(f"OK on_new_push keeps memory (before={before}, after={after})")


def main():
    test_memory_blocks_and_on_new_push()
    test_transcript_structure_and_condense()
    test_legacy_migrate()
    test_harness_multi_step_loop_mocked()
    test_on_new_push_keeps_transcript()
    print("\nALL PASSED")


if __name__ == "__main__":
    main()
