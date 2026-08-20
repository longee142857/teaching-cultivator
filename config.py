"""配置"""
import os, sys

# ── 本地 .env（gitignore）──
def _load_dotenv(path: str | None = None) -> None:
    env_path = path or os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass


_load_dotenv()

# ── DeepSeek API（必须经环境变量 / .env，禁止把 key 写进仓库）──
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_BASE = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")

# ── 模型 ──
MODEL_FLASH = os.environ.get("DEEPSEEK_MODEL_FLASH", "deepseek-v4-flash")
MODEL_PRO = os.environ.get("DEEPSEEK_MODEL_PRO", "deepseek-v4-pro")
# Agent：DeepSeek Flash 直连
AGENT_MODEL = os.environ.get("AGENT_MODEL", "deepseek-v4-flash")
# 审查异厂：默认阿里云百炼（北京）qwen-plus；可改 REVIEWER_PROVIDER=openrouter|deepseek
REVIEWER_PROVIDER = (os.environ.get("REVIEWER_PROVIDER") or "dashscope").strip().lower()
REVIEWER_MODEL = os.environ.get("REVIEWER_MODEL", "qwen-plus")
# Agent thinking：官方 Agent 评测用 max；设 AGENT_THINKING=0 可关
AGENT_THINKING = os.environ.get("AGENT_THINKING", "1") == "1"
AGENT_REASONING_EFFORT = os.environ.get("AGENT_REASONING_EFFORT", "max")

# ── 可选：外置知识库根目录（RAG 回填 / Chroma 查询辅助脚本）──
KB_PATH = os.environ.get("KB_PATH", "")
if KB_PATH:
    sys.path.insert(0, KB_PATH)
    _kb_lib = os.path.join(KB_PATH, "lib")
    if os.path.isdir(_kb_lib):
        sys.path.insert(0, _kb_lib)
else:
    # BIG-TEACH-012a #6: 相对 monorepo 路径 fallback
    _rel_lib = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "../knowledge-system/lib")
    )
    if os.path.isdir(_rel_lib):
        sys.path.insert(0, _rel_lib)

# ── SSL 证书校验（BIG-TEACH-012d #15）──
# 默认启用；企业代理或自签名证书需关闭时设 SSL_VERIFY=0
SSL_VERIFY = os.environ.get("SSL_VERIFY", "1") == "1"

# ── 数据文件 ──
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
# BIG-TEACH-013: SQLite 真相源库；空则用 DATA_DIR/teaching.db
TEACHING_DB = os.environ.get("TEACHING_DB", "")
BKT_OVERRIDES_PATH = os.path.join(DATA_DIR, "bkt_overrides.json")  # BIG-TEACH-012b #2
LP_PATH = os.path.join(DATA_DIR, "learning-progress.json")  # DEPRECATED (BIG-TEACH-012d #16)
# 每日记录目录：默认仓库内 data/daily_export；可用环境变量覆盖
DAILY_RECORD_DIR = os.environ.get(
    "DAILY_RECORD_DIR",
    os.path.join(DATA_DIR, "daily_export"),
)

# ── 推送配置 ──
PUSH_SLOTS = {
    "math":   {"time": "09:00", "name": "数学一", "subject": "数学分析"},
    "comm":   {"time": "15:00", "name": "通信原理", "subject": "通信原理"},
    "review": {"time": "19:00", "name": "错题复盘", "subject": "all"},
}

# ── 钉钉 Stream Mode（主通道） ──
DINGTALK_CLIENT_ID = os.environ.get("DINGTALK_CLIENT_ID", "")
DINGTALK_CLIENT_SECRET = os.environ.get("DINGTALK_CLIENT_SECRET", "")
# 组织 corpId：试卷网页免登 requestAuthCode 需要；钉钉开发者后台可查
DINGTALK_CORP_ID = os.environ.get("DINGTALK_CORP_ID", "")
# 定时主动推送用的群 openConversationId；设置后优先生效，避免私聊覆盖
DINGTALK_GROUP_CONVERSATION_ID = os.environ.get("DINGTALK_GROUP_CONVERSATION_ID", "")
# 1=群里收到讨论时完整回复走私聊（oTo）；群内只回短确认。0=群内直接回全文
DINGTALK_DISCUSS_IN_DM = os.environ.get("DINGTALK_DISCUSS_IN_DM", "1") == "1"

# ── 企业微信 Bot SDK（备用，迁移过渡期保留） ──
WECOM_BOT_ID = os.environ.get("WECOM_BOT_ID", "")
WECOM_BOT_SECRET = os.environ.get("WECOM_BOT_SECRET", "")
WECOM_WEBHOOK = os.environ.get("WECOM_WEBHOOK", "")

# ── GitHub Push 配置 ──
# 代理配置：优先使用 Git 全局代理，自动降级
# 见 tool-scripts/tools/v2ray/SKILL.md
GITHUB_PROXY_ENABLED = os.environ.get("GITHUB_PROXY", "1") == "1"
GITHUB_DEFAULT_REPO = os.path.dirname(__file__)  # teaching-cultivator

# ── 微信桥（过渡期保留） ──
WX_BOT_URL = "https://ilinkai.weixin.qq.com/ilink/bot"
WX_BOT_TOKEN = os.environ.get("WX_BOT_TOKEN", "")

# ── 阿里云百炼 DashScope（review_item / verify_grade 默认通道；OpenAI 兼容）──
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_API_BASE = os.environ.get(
    "DASHSCOPE_API_BASE",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# ── SimpleTex 手写/公式 OCR（私聊发图批改）──
SIMPLETEX_UAT = os.environ.get("SIMPLETEX_UAT", "")
SIMPLETEX_APP_ID = os.environ.get("SIMPLETEX_APP_ID", "")
SIMPLETEX_APP_SECRET = os.environ.get("SIMPLETEX_APP_SECRET", "")
SIMPLETEX_API_BASE = os.environ.get("SIMPLETEX_API_BASE", "https://server.simpletex.cn")
# general=整页混排(默认)；formula_turbo=轻量公式；formula=标准公式
SIMPLETEX_OCR_MODE = os.environ.get("SIMPLETEX_OCR_MODE", "general")
SIMPLETEX_ENABLED = os.environ.get("SIMPLETEX_ENABLED", "1") == "1"

# ── OpenRouter（可选遗留；默认审查已改走 DashScope，不走代理翻墙）──
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# ── RAG Fallback 策略（BIG-TEACH-012c #10）──
RAG_FALLBACK = os.environ.get("RAG_FALLBACK", "abort")

# ── 学习者身份（BIG-TEACH-012c #14 → 多人花名册补正）──
# LEARNER_USER_ID：仅兼容旧单人/测试；运行时请用 learner.context.current_user_id()
LEARNER_USER_ID = os.environ.get("LEARNER_USER_ID", "wx_123")
# 课表/公共课策略账户（钉钉 senderStaffId）；多人模式生产必填
OWNER_STAFF_ID = os.environ.get("OWNER_STAFF_ID", "") or os.environ.get("LEARNER_USER_ID", "")

# ── 双周试卷 H5 阅读页（KaTeX；公网经 nginx 反代）──
# 公网基址，如 https://exam.example.com ；空则不发 H5 链接（可降级 PNG）
EXAM_WEB_PUBLIC_BASE = (os.environ.get("EXAM_WEB_PUBLIC_BASE") or "").rstrip("/")
EXAM_VIEW_SECRET = os.environ.get("EXAM_VIEW_SECRET", "")
EXAM_WEB_PORT = int(os.environ.get("EXAM_WEB_PORT", "8766"))
EXAM_WEB_HOST = os.environ.get("EXAM_WEB_HOST", "127.0.0.1")
EXAM_TOKEN_TTL_DAYS = int(os.environ.get("EXAM_TOKEN_TTL_DAYS", "14"))
EXAM_WEB_HTTP = os.environ.get("EXAM_WEB_HTTP", "1") == "1"
# 1=推送时额外发 PNG 长图（默认关，H5 为主）
EXAM_PUSH_PNG = os.environ.get("EXAM_PUSH_PNG", "0") == "1"
# 单 token 提交限流：每小时次数
EXAM_SUBMIT_LIMIT_PER_HOUR = int(os.environ.get("EXAM_SUBMIT_LIMIT_PER_HOUR", "5"))

# ── 运维看板（驳回题 / 学员参数；公网经 nginx /ops/）──
OPS_WEB_HOST = os.environ.get("OPS_WEB_HOST", "127.0.0.1")
OPS_WEB_PORT = int(os.environ.get("OPS_WEB_PORT", "8767"))
OPS_WEB_HTTP = os.environ.get("OPS_WEB_HTTP", "1") == "1"
OPS_VIEW_TOKEN = os.environ.get("OPS_VIEW_TOKEN", "")

# ── 系统白名单 API（任意 agent；默认本机）──
SYSTEM_API_HTTP = os.environ.get("SYSTEM_API_HTTP", "1") == "1"
SYSTEM_API_HOST = os.environ.get("SYSTEM_API_HOST", "127.0.0.1")
SYSTEM_API_PORT = int(os.environ.get("SYSTEM_API_PORT", "8770"))
SYSTEM_API_TOKEN = os.environ.get("SYSTEM_API_TOKEN", "")

# ── 练习台前端 + Practice API（teaching-shell；公网可经 nginx /practice）──
PRACTICE_WEB_HOST = os.environ.get("PRACTICE_WEB_HOST", "127.0.0.1")
PRACTICE_WEB_PORT = int(os.environ.get("PRACTICE_WEB_PORT", "8768"))
PRACTICE_WEB_HTTP = os.environ.get("PRACTICE_WEB_HTTP", "1") == "1"
PRACTICE_API_TOKEN = os.environ.get("PRACTICE_API_TOKEN", "")
# llm | ref — CI/无密钥用 ref；生产默认 llm（失败自动 ref_fallback）
PRACTICE_GRADE_MODE = os.environ.get("PRACTICE_GRADE_MODE", "llm")
# 1=今日无推送时写入演示三槽（仅本地/联调）
PRACTICE_ALLOW_DEMO_SEED = os.environ.get("PRACTICE_ALLOW_DEMO_SEED", "0") == "1"
# DSH mentor-team base (e.g. http://127.0.0.1:61900); empty → tutor/chat stays 501
TUTOR_BACKEND_URL = (os.environ.get("TUTOR_BACKEND_URL") or "").strip().rstrip("/")

# ── Pi RPC 交互层（钉钉唤醒；扩展/session 在主机 Pi 家目录，不进本仓）──
PI_RPC_ENABLED = os.environ.get("PI_RPC_ENABLED", "0") == "1"
PI_RPC_HOST = os.environ.get("PI_RPC_HOST", "127.0.0.1")
PI_RPC_PORT = int(os.environ.get("PI_RPC_PORT", "8780"))
PI_SESSION_DIR = os.environ.get("PI_SESSION_DIR", "/home/ubuntu/pi-sessions")
PI_WORKSPACE = os.environ.get("PI_WORKSPACE", "/home/ubuntu/pi-workspace")
PI_RPC_CMD = os.environ.get("PI_RPC_CMD", "")
PI_RPC_TIMEOUT = float(os.environ.get("PI_RPC_TIMEOUT", "180"))
