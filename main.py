"""teaching-cultivator — 钉钉 Bot (DingTalk Stream Mode)

Stream 长连接 + 定时推送 + 自动批改 + BKT 追踪。
"""
from __future__ import annotations
import sys, os, time, datetime, threading, json, logging, io

# Windows GBK 终端兼容：print 遇到非 BMP 字符不炸
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 配置 Python logging（DingTalk SDK + 自定义 logger 共用）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)

from config import DATA_DIR, DINGTALK_CLIENT_ID, DINGTALK_CLIENT_SECRET
from learner import paths as P
from learner.context import bind_owner_schedule
from deliver.push_retry_queue import enqueue_retry, process_retry_queue
from deliver.dingtalk_bot import DingTalkBot, DingTalkPushBridge
from deliver.bridge import WecomWebhookBridge, StdoutBridge
from agent.agent import TeachingAgent


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "kb_cache"), exist_ok=True)


LOCK_FILE = os.path.join(DATA_DIR, "run.lock")
_LOCK_MUTEX = None  # Windows named mutex handle


def _pid_alive(pid: int) -> bool:
    """跨进程存活检测。Windows 用 OpenProcess，POSIX 用 os.kill(pid, 0)。"""
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x400 | 0x10, False, pid)  # QUERY_INFO | VM_READ
            if not handle:
                return False
            exit_code = ctypes.c_ulong(0)
            kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            return exit_code.value == 259  # STILL_ACTIVE
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _read_lock_pid() -> int | None:
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE) as f:
                return int(f.read().strip())
    except (OSError, ValueError):
        pass
    return None


def _acquire_lock() -> bool:
    """跨平台单实例锁。Windows: 命名 mutex + PID 文件；POSIX: PID 文件 + 存活检测。"""
    global _LOCK_MUTEX
    os.makedirs(DATA_DIR, exist_ok=True)

    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            _LOCK_MUTEX = kernel32.CreateMutexW(None, False, "TeachingCultivator_Bot")
            if _LOCK_MUTEX and kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                pid = _read_lock_pid()
                if pid and _pid_alive(pid):
                    log("另一个实例已在运行，退出")
                    return False
                log("检测到残留锁（原进程已死），接管")
        except Exception as e:
            log(f"锁警告: {e}")
    else:
        # POSIX：PID 文件 + 进程存活检测
        pid = _read_lock_pid()
        if pid and _pid_alive(pid):
            log(f"另一个实例已在运行 (pid={pid})，退出")
            return False
        if pid:
            log("检测到残留锁（原进程已死），接管")

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def _release_lock():
    global _LOCK_MUTEX
    try:
        if _LOCK_MUTEX and os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.CloseHandle(_LOCK_MUTEX)
            _LOCK_MUTEX = None
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


def log(msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(os.path.join(DATA_DIR, "logs", "listener.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── Bot + 培养逻辑 ───────────────────────────────
class TeachingBot:
    """教学 Bot：钉钉 Stream 长连 + Agent 交互 + 定时推送。"""

    def __init__(self, client_id: str, client_secret: str):
        self.dingtalk = DingTalkBot(client_id, client_secret)
        self._last_question = ""
        self._last_question_time = 0
        self.agent = TeachingAgent(bot=self)
        self.dingtalk.set_agent(self.agent)
        self._restore_last_question()

    # ── 生命周期 ────────────────────────────────────

    def start(self):
        self.dingtalk.start()

    def stop(self):
        self.dingtalk.stop()

    # ── 上下文恢复 ──────────────────────────────────

    def _restore_last_question(self):
        path = P.public_last_class_path()
        if not os.path.exists(path):
            path = P.last_push_path()
        try:
            if not os.path.exists(path):
                return
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            q = (data.get("question") or "").strip()
            if q:
                self._last_question = q
                self._last_question_time = time.time()
                log(f"恢复 last_push 题目 ({len(q)} chars)")
        except Exception as e:
            log(f"恢复 last_push 失败: {e}")

    def _save_last_push(self, subject, decision, content, answer=""):
        """Deprecated：推送正文由 cultivate._save_last_push 写入 public/last_class。"""
        pass

    def _record_push(self, question: str):
        self._last_question = question
        self._last_question_time = time.time()

    # ── 推送 ────────────────────────────────────────

    def push_cultivate(self, subject: str):
        """执行一次培养推送（钉钉 OpenAPI → webhook 回退 → 日志兜底）。

        失败时写入重试队列（BIG-TEACH-012c #8）。
        """
        from cultivate import cultivate as run
        import cultivate as _cultivate
        import deliver.bridge as db
        orig_db = db.get_bridge
        orig_cult = _cultivate.get_bridge

        bridge = self._make_push_bridge()
        db.get_bridge = lambda: bridge
        _cultivate.get_bridge = lambda: bridge
        saved_content = ""
        delivery_ok = True
        try:
            from learner.context import bind_owner_schedule, owner_staff_id

            run(subject)
            if self._last_question:
                oid = owner_staff_id()
                if oid:
                    with bind_owner_schedule():
                        self.agent.bind_for_learner(oid)
                        # 从 public/last_class 读 kp（_save_last_push 已写入），
                        # 保证 blocks 的 active_question 有正确 kp（防错题叙事粘滞）
                        push_kp = ""
                        try:
                            _pub = P.public_last_class_path()
                            if os.path.isfile(_pub):
                                with open(_pub, encoding="utf-8") as _f:
                                    push_kp = (json.load(_f).get("kp") or "").strip()
                        except Exception:
                            pass
                        self.agent.on_new_push(
                            self._last_question, subject=subject, kp=push_kp,
                            public_class=True,
                        )
                # 出题后跟发快捷按钮 ActionCard
                try:
                    self.dingtalk.send_question_action_card(subject)
                except Exception as e:
                    log(f"[action-card] 出题卡失败: {e}")
            log(f"[OK] {subject} 推送执行完毕")
        except Exception as e:
            log(f"[失败] {subject} 推送异常: {e}")
            saved_content = self._last_question
            delivery_ok = False
        finally:
            db.get_bridge = orig_db
            _cultivate.get_bridge = orig_cult

        if not delivery_ok:
            enqueue_retry(subject, content=saved_content)

    def push_weekly_report(self):
        """生成并推送学习周报 ActionCard。"""
        try:
            from agent.tools import build_report
            report = build_report(days=7)
        except Exception as e:
            log(f"[weekly] 生成周报失败: {e}")
            return
        ok = self.dingtalk.send_weekly_action_card(report)
        if ok:
            log("[OK] 周报 ActionCard 推送完成")
        else:
            # 回退：纯 markdown
            if self.dingtalk.send_push(report):
                log("[OK] 周报 markdown 回退推送完成")
            else:
                log("[失败] 周报推送失败")

    def push_biweekly_exams(self):
        """隔周双周试卷：数学+通信各一份 md，入题库并推送。"""
        try:
            from learner.biweekly_exam import biweekly_is_due, run_biweekly_issue
        except Exception as e:
            log(f"[biweekly] import fail: {e}")
            return
        if not biweekly_is_due():
            log("[biweekly] 未到期，跳过")
            return
        log("[biweekly] 开始组卷…")
        try:
            result = run_biweekly_issue()
        except Exception as e:
            log(f"[biweekly] 组卷失败: {e}")
            return
        papers = result.get("papers") or []
        ids = result.get("paper_ids") or []
        log(f"[biweekly] 已落盘 {ids} ok={result.get('ok')}")
        try:
            if self.dingtalk.send_biweekly_papers(papers):
                log("[OK] 双周试卷已推送")
            else:
                log("[失败] 双周试卷推送未成功（文件可能已写入 exam_bank）")
        except Exception as e:
            log(f"[biweekly] 推送异常: {e}")

    def _make_push_bridge(self):
        """创建推送桥：钉钉 OpenAPI 优先 → webhook 回退 → stdout 兜底。"""

        class _PushBridge:
            def __init__(self, bot):
                self.dd_bridge = DingTalkPushBridge(bot.dingtalk)
                self.webhook = WecomWebhookBridge()
                self.stdout = StdoutBridge()
                self._bot = bot

            def send(self, content):
                if not content:
                    return False
                # 必须存全文：Agent 批改依赖 _last_question；截断会导致「题目被截断」误判
                self._bot._record_push(content)

                if self.dd_bridge.send(content):
                    return True
                log("[push] 钉钉推送失败，尝试 webhook 回退")
                if self.webhook.is_ready() and self.webhook.send(content):
                    return True
                log("[push] webhook 也失败，stdout 兜底")
                self.stdout.send(content)
                return False

        return _PushBridge(self)

    def push_github_trending(self):
        """GitHub Trending 推送到钉钉。"""
        import deliver.bridge as db
        import cultivate as _cultivate
        from deliver.github_trending import fetch_formatted, send_trending

        orig_db = db.get_bridge
        orig_cult = _cultivate.get_bridge
        bridge = self._make_push_bridge()
        db.get_bridge = lambda: bridge
        _cultivate.get_bridge = lambda: bridge
        try:
            text, n = fetch_formatted(max_count=10, channel="dingtalk", use_cache=True, skip_dup=True)
            if not text:
                log(f"[github-trending] 无新项目（已去重），跳过")
                return
            log(f"[github-trending] {n} 个项目，推送中...")
            send_trending(text, channel="dingtalk", bridge_send=bridge.send)
            log(f"[OK] github-trending 推送完成 ({n} 条)")
        except Exception as e:
            log(f"[失败] github-trending 异常: {e}")
        finally:
            db.get_bridge = orig_db
            _cultivate.get_bridge = orig_cult


# ── 定时器 ───────────────────────────────────────

PUSH_SLOTS = [("09:00", "math"), ("15:00", "comm"), ("19:00", "review")]

_WEEKDAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


# 周日 20:00 学习周报
WEEKLY_REPORT_SLOT = ("20:00", "sun")

# 隔周周日 08:00 双周检测卷（与每日 github 08:00 错开到同日批次：见 scheduler）
BIWEEKLY_EXAM_SLOT = ("08:00", "sun")


def _next_scheduled_event(now: datetime.datetime):
    """返回最近待触发的 (target_dt, kind, payload)。"""
    candidates: list[tuple[datetime.datetime, str, str | None]] = []

    for time_str, subject in PUSH_SLOTS:
        h, m = map(int, time_str.split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        candidates.append((target, "cultivate", subject))

    # GitHub 自动推送：每天 08:00
    target_gh = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if target_gh <= now:
        target_gh += datetime.timedelta(days=1)
    candidates.append((target_gh, "github_push", None))

    # 学习周报：每周日 20:00
    wh, wm = map(int, WEEKLY_REPORT_SLOT[0].split(":"))
    target_dow = _WEEKDAY_MAP.get(WEEKLY_REPORT_SLOT[1], 6)
    days_ahead = (target_dow - now.weekday()) % 7
    target_w = now.replace(hour=wh, minute=wm, second=0, microsecond=0)
    target_w += datetime.timedelta(days=days_ahead)
    if target_w <= now:
        target_w += datetime.timedelta(days=7)
    candidates.append((target_w, "weekly_report", None))

    # 双周试卷：挂下一个周日 08:00（是否组卷由 push 内 is_due 决定）
    try:
        from learner.biweekly_exam import next_biweekly_slot

        candidates.append((next_biweekly_slot(now), "biweekly_exam", None))
    except Exception:
        pass

    candidates.sort(key=lambda x: x[0])
    return candidates[0]


def _do_github_push(bot: TeachingBot | None = None):
    """GitHub Trending 推送：每天早上 08:00 触发。"""
    if bot is not None:
        bot.push_github_trending()
    else:
        # 兜底：没有 bot 时打印到 stdout
        try:
            from deliver.github_trending import fetch_formatted
            text, n = fetch_formatted(max_count=10, channel="stdout", use_cache=True, skip_dup=True)
            if text:
                print(text)
            log(f"[github-trending] stdout 打印 {n} 条")
        except Exception as e:
            log(f"[github-trending] 兜底失败: {e}")


def scheduler_loop(bot: TeachingBot):
    """后台线程：到点触发题目推送或 GitHub 自动推送。"""
    while True:
        now = datetime.datetime.now()
        target, kind, payload = _next_scheduled_event(now)
        wait = (target - now).total_seconds()
        label_map = {
            "cultivate": payload,
            "github_push": "github-push",
            "weekly_report": "weekly-report",
            "biweekly_exam": "biweekly-exam",
        }
        label = label_map.get(kind, kind)
        if wait < 120:
            log(f"[定时] {label} 推送倒计时 {wait:.0f}s")
            time.sleep(max(0, wait))
            log(f"[推送] 推送 {label}")
            try:
                if kind == "cultivate":
                    bot.push_cultivate(payload)
                    log(f"[OK] {payload} 完成")
                elif kind == "github_push":
                    _do_github_push(bot)
                    # 与周日 08:00 同槽：若双周到期则一并发卷（防候选撞车丢事件）
                    if datetime.datetime.now().weekday() == 6:
                        bot.push_biweekly_exams()
                elif kind == "weekly_report":
                    bot.push_weekly_report()
                elif kind == "biweekly_exam":
                    bot.push_biweekly_exams()
            except Exception as e:
                log(f"[失败] {label} 失败: {e}")
        # 消费推送重试队列（BIG-TEACH-012c #8）
        try:
            retried = process_retry_queue(bot)
            if retried:
                log(f"[retry-queue] 本轮重试 {retried} 条")
        except Exception as e:
            log(f"[retry-queue] 处理异常: {e}")
        time.sleep(30)


# ── 入口 ─────────────────────────────────────────

def main():
    ensure_dirs()
    if not _acquire_lock():
        return
    import atexit; atexit.register(_release_lock)

    # DingTalk conversation_id 持久化路径
    cid_path = os.path.join(DATA_DIR, "conversation_id.json")

    log("启动中...")

    bot = TeachingBot(DINGTALK_CLIENT_ID, DINGTALK_CLIENT_SECRET)
    bot.dingtalk.set_cid_file(cid_path)

    # scheduler 在后台线程跑，Stream 客户端在主线程（asyncio 需要主线程）
    t = threading.Thread(target=scheduler_loop, args=(bot,), daemon=True)
    t.start()
    log("定时器已启动")

    # 考点小库 HTTP 站点（本机 sync_kb_cache 可直连；失败不阻断 Bot）
    try:
        from kb_cache_api import start_in_thread
        if start_in_thread():
            log("kb_cache API 已启动")
        else:
            log("kb_cache API 未启动（KB_CACHE_HTTP=0 或端口占用）")
    except Exception as e:
        log(f"kb_cache API 跳过: {e}")

    # 双周试卷 H5（localhost；公网经 nginx 反代 /e/）
    try:
        from deliver.exam_web import start_in_thread as start_exam_web

        if start_exam_web():
            log("exam_web H5 已启动")
        else:
            log("exam_web 未启动（EXAM_WEB_HTTP=0 或端口占用）")
    except Exception as e:
        log(f"exam_web 跳过: {e}")

    # 运维看板（驳回/学员参数；公网经 nginx 反代 /ops/）
    try:
        from deliver.ops_web import start_in_thread as start_ops_web

        if start_ops_web():
            log("ops_web 已启动")
        else:
            log("ops_web 未启动（OPS_WEB_HTTP=0 或端口占用）")
    except Exception as e:
        log(f"ops_web 跳过: {e}")

    # 阻塞：DingTalk Stream 在主线程运行
    bot.start()


if __name__ == "__main__":
    main()
