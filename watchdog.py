"""教学培养 Bot 守护进程（Python 版）

用法（独立终端窗口）：
    python watchdog.py

启动 main.py，崩溃后自动重启。重启前清理残留锁。
"""
import subprocess, time, os, sys

SCRIPT_DIR = os.path.dirname(__file__)
MAIN_PY = os.path.join(SCRIPT_DIR, "main.py")
PYTHON = sys.executable  # 用同一个 Python

log_path = os.path.join(SCRIPT_DIR, "data", "logs", "watchdog.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)


def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] watchdog: {msg}"
    print(line, flush=True)
    try:
        with open(log_path, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def cleanup():
    lock_file = os.path.join(SCRIPT_DIR, "data", "run.lock")
    try:
        if os.path.exists(lock_file):
            os.remove(lock_file)
            log("清理残留 run.lock")
    except Exception:
        pass


def main():
    log("守护进程启动")
    while True:
        cleanup()
        log("启动 main.py ...")
        proc = subprocess.Popen(
            [PYTHON, MAIN_PY],
            cwd=SCRIPT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        # 阻塞等待进程退出
        proc.wait()
        log(f"⚠️ main.py 已退出 (code={proc.returncode})，10秒后重启")
        time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("守护进程手动停止")
