"""验证 transcript condense 不再递归嵌套摘要 (BUG: [对话摘要] 套 [对话摘要])。

模拟多个推送周期，检查每次 condense 后是否仍只有一层摘要。
用 base_dir 隔离到临时目录，不污染真实数据。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.transcript import Transcript


def make_turn(user: str, asst: str) -> list[dict]:
    """构造一轮 user+assistant 对话。"""
    return [
        {"role": "user", "content": user},
        {"role": "assistant", "content": asst},
    ]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        t = Transcript(base_dir=tmp)
        pushes = ["第一题：求极限", "第二题：变限积分", "第三题：傅里叶级数", "第四题：随机过程"]
        for i, p in enumerate(pushes):
            # 每个周期追加 6 条消息 → 触发 condense
            for j in range(3):
                t.append_messages(make_turn(
                    f"{p} 用户提问{j}",
                    f"{p} 回复内容{j}，一段比较长的讲解，用于测试摘要截断逻辑是否正常，超过八十个字符也不会出问题",
                ))
            # 推送后 on_new_push 同款：condense keep_recent=4
            t.condense(keep_recent=4)
            if t.messages and t.messages[0].get("role") == "assistant":
                first = t.messages[0].get("content") or ""
                nested = first.count("[对话摘要]")
                print(f"[周期{i+1}] 摘要嵌套数={nested} 首条60字={first[:60]!r}")
                if nested > 1:
                    print(f"  [FAIL] BUG：摘要出现 {nested} 次嵌套")
                    return 1
    print("[PASS] 多周期无嵌套摘要")
    return 0


if __name__ == "__main__":
    sys.exit(main())
