"""一键推送入口 — 后备通道

用法:
    python push.py math       # 数学一
    python push.py comm       # 通信原理
    python push.py review     # 错题复盘

正常情况下 main.py 内部定时器处理推送，此脚本由 Task Scheduler 调用作为后备。
"""
import sys, os, io

# Windows GBK 终端兼容
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(__file__))
os.makedirs(os.path.join(os.path.dirname(__file__), "data"), exist_ok=True)

from cultivate import cultivate as run_cultivate
from config import DATA_DIR


LOCK_FILE = os.path.join(DATA_DIR, "run.lock")


def _bot_is_running() -> bool:
    """检查 main.py 是否在运行。Windows 用命名 mutex，POSIX 用 PID 文件 + 存活检测。"""
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            mutex = kernel32.OpenMutexW(0x1F0001, False, "TeachingCultivator_Bot")
            if mutex:
                kernel32.CloseHandle(mutex)
                return True
            return False
        except Exception:
            pass
    # POSIX 或 Windows mutex 异常时：fallback 到 PID 文件
    pid = None
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE) as f:
                pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main():
    subject = sys.argv[1] if len(sys.argv) > 1 else "math"

    if _bot_is_running():
        print(f"[push] main.py 正在运行，内部定时器会处理 {subject}，跳过")
        return

    from deliver.bridge import get_bridge
    bridge = get_bridge()
    if not bridge.is_ready():
        print("[push] 无可用推送通道（WECOM_WEBHOOK 未配置，且 bot 未运行）")
        print("[push] 设置 WECOM_WEBHOOK 环境变量指向企业微信群机器人 webhook")
        return

    print(f"\n=== 培养推送: {subject} ===")
    run_cultivate(subject)
    print(f"=== {subject} 完成 ===\n")


if __name__ == "__main__":
    main()
