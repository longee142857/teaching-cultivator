"""一次性：把今早对话要点写入 agent_memory，避免部署重启后追问失忆。"""
from __future__ import annotations
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = os.path.join(ROOT, "data", "agent_memory.json")

messages = [
    {
        "role": "user",
        "content": (
            "这道题应该是选ABC，通过行列交换变化就能得到。"
            "不过我有个问题，变换的时候可以任意行变化和列变换吗这个题也可以用秩判断"
        ),
    },
    {
        "role": "assistant",
        "content": (
            "你在问今天 09:00 的「矩阵与初等变换」题（矩阵等价/秩）。\n"
            "求秩：行变换和列变换可混用；解方程组只能行变换。\n"
            "你答选 ABC：若题为单选且按「同秩即等价」，需再核对选项秩是否唯一正确；"
            "可再发一次答案让我正式批改。"
        ),
    },
    {
        "role": "user",
        "content": "今天早上九点的题目，你自己查一下",
    },
    {
        "role": "assistant",
        "content": (
            "找到了：今天早上九点是「矩阵与初等变换」题，已在服务端 last_push / 每日记录中。"
            "完整题干与选项可随时用 find_record_entry 或系统注入的最近推送题查看；"
            "你要批改的话直接把选项发我就行。"
        ),
    },
    {
        "role": "user",
        "content": "结果呢？查到了没有",
    },
    {
        "role": "assistant",
        "content": (
            "查到了。就是早上九点那道矩阵与初等变换（等价/秩）题；"
            "完整内容在服务端。你之前倾向选 ABC，并用秩判断——"
            "发一下你的最终选项，我直接 grade_answer 批改。"
        ),
    },
]

os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump({"updated_at": time.time(), "messages": messages}, f, ensure_ascii=False, indent=2)
print("seeded", path, "msgs", len(messages))
