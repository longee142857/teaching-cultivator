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
# OpenRouter：审查校验（异厂）；交互 Agent 已改走 DeepSeek Flash 直连
AGENT_MODEL = os.environ.get("AGENT_MODEL", "deepseek-v4-flash")
REVIEWER_MODEL = os.environ.get("REVIEWER_MODEL", "qwen/qwen3.6-plus")
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

# ── OpenRouter（reviewer 异厂校验；X Digest 已退役；Agent 走 DeepSeek）──
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
