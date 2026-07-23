import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from learner.kb_cache import STORE_PATH, _key, _load_store, _save_store, enqueue, stats

store = _load_store()
k = _key("math", "特征值与特征向量")
if k in store.get("entries", {}):
    del store["entries"][k]
    _save_store(store)
    print("removed", k)
print(enqueue("math", "特征值与特征向量", query="特征值 特征向量 对角化 矩阵"))
print(stats())
