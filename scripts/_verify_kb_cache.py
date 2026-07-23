import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from learner.kb_cache import peek, stats

print(stats())
for subj, kp in (("math", "特征值与特征向量"), ("comm", "QPSK与OQPSK")):
    e = peek(subj, kp)
    n = len((e or {}).get("snippets") or [])
    src = ((e or {}).get("snippets") or [{}])[0].get("source", "none")
    print(f"{subj}/{kp}: snippets={n} src={src}")
