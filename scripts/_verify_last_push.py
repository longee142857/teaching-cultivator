"""Quick check: last_push has full stem + options."""
import json
import os

path = os.path.join(os.path.dirname(__file__), "..", "data", "last_push.json")
path = os.path.abspath(path)
d = json.load(open(path, encoding="utf-8"))
q = d.get("question") or ""
print("last_push_chars", len(q))
print("has_A", "(A)" in q or "（A）" in q)
print("has_C", "(C)" in q or "（C）" in q)
print("kp", d.get("kp"))
