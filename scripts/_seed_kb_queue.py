import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from learner.kb_cache import enqueue, stats

print(enqueue("math", "特征值与特征向量", query="特征值 特征向量 对角化"))
print(enqueue("comm", "QPSK与OQPSK", query="QPSK OQPSK 误码率"))
print(stats())
