"""心跳检查 — 每小时跑一次，有薄弱点就推≤150字"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DATA_DIR
from bkt import BKTLogger


def heartbeat():
    bkt = BKTLogger(os.path.join(DATA_DIR, "answer-log.jsonl"))
    mastery = bkt.get_all_kp_mastery("wx_123")
    if not mastery:
        return

    weak = [(kp, v) for kp, v in mastery.items() if v < 0.6]
    if not weak:
        return  # 没有薄弱点，沉默

    weak.sort(key=lambda x: x[1])
    print(f"⏰ 心跳：发现 {len(weak)} 个薄弱点，最低 {weak[0][0]}({weak[0][1]:.0%})")


if __name__ == "__main__":
    heartbeat()
