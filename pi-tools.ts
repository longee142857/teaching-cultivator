/**
 * Pi 交互层工具注册草稿（2026-08-09）— 不部署进程，仅作为接入示例。
 *
 * 依据：docs/pi-tools-whitelist.md（白名单 → tools.py 符号对照表）。
 * 模式：pi --mode rpc --extension pi-tools.ts --provider deepseek --model deepseek-v4-flash[1m]
 *
 * 桥形态（Cursor 裁决第一期）：tool shim —— Pi 工具 execute 内
 * subprocess 调 Python 白名单函数（agent/tools.py）。写状态由系统闸决定，
 * Pi 只触发，不裸写 weights/answer-log。
 */

import { spawnSync } from "node:child_process";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

/** 云端 Python 环境 + teaching-cultivator 根目录 */
const PYTHON = "/home/ubuntu/teaching-cultivator/venv/bin/python3";
const TEACHING_DIR = "/home/ubuntu/teaching-cultivator";

/** 统一 tool shim：调 Python tools.py 函数，返回文本 */
function callTools(fn: string, args: Record<string, unknown>): string {
  const script = [
    "import sys, json",
    "sys.path.insert(0, '.')",
    "from agent import tools",
    `try:`,
    `    out = tools.${fn}(**${JSON.stringify(args)})`,
    `    print(json.dumps({"ok": True, "out": out}, ensure_ascii=False))`,
    `except Exception as e:`,
    `    print(json.dumps({"ok": False, "err": str(e)}, ensure_ascii=False))`,
  ].join("\n");

  const r = spawnSync(PYTHON, ["-c", script], {
    cwd: TEACHING_DIR,
    encoding: "utf-8",
    timeout: 60000,
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
  });
  if (r.status !== 0) {
    return `[tool:${fn}] 调用失败：${r.stderr?.trim() || r.stdout?.trim()}`;
  }
  try {
    const parsed = JSON.parse(r.stdout.trim().split("\n").pop() || "{}");
    if (parsed.ok) return String(parsed.out);
    return `[tool:${fn}] 系统错误：${parsed.err}`;
  } catch {
    return `[tool:${fn}] 返回解析失败`;
  }
}

const SUBJECT = Type.Union([
  Type.Literal("math"),
  Type.Literal("comm"),
  Type.Literal("review"),
]);

const LEVEL = Type.Union([
  Type.Literal("basic"),
  Type.Literal("intermediate"),
  Type.Literal("challenge"),
]);

export default function teachingTools(pi: ExtensionAPI) {
  pi.registerTool({
    name: "get_active_question",
    label: "当前题目",
    description: "获取当前正在做的题（科目/知识点/难度/全文）。用户问「现在哪道题」时用",
    promptSnippet: "获取当前推送的题目",
    parameters: Type.Object({}),
    async execute() {
      return { content: [{ type: "text", text: callTools("get_active_question", {}) }] };
    },
  });

  pi.registerTool({
    name: "get_learner_snapshot",
    label: "学习指标",
    description: "查看学习指标快照（权重/BKT/答题统计）",
    promptSnippet: "查看学习者当前水平指标",
    parameters: Type.Object({ days: Type.Optional(Type.Number()) }),
    async execute(_id, params) {
      return { content: [{ type: "text", text: callTools("get_learner_snapshot", { days: params.days ?? 7 }) }] };
    },
  });

  pi.registerTool({
    name: "list_recent_entries",
    label: "最近题目",
    description: "列出最近 N 天题目索引",
    promptSnippet: "查看最近出的题目",
    parameters: Type.Object({ days: Type.Optional(Type.Number()) }),
    async execute(_id, params) {
      return { content: [{ type: "text", text: callTools("list_recent_entries", { days: params.days ?? 7 }) }] };
    },
  });

  pi.registerTool({
    name: "find_record_entry",
    label: "取题目全文",
    description: "按日期取某条题目全文",
    promptSnippet: "按日期取题目记录",
    parameters: Type.Object({
      date: Type.String({ description: "YYYY-MM-DD" }),
      num: Type.Optional(Type.Number()),
    }),
    async execute(_id, params) {
      return { content: [{ type: "text", text: callTools("find_record_entry", { date: params.date, num: params.num ?? 0 }) }] };
    },
  });

  pi.registerTool({
    name: "generate_question",
    label: "出题",
    description: "出一题（走系统 cultivate/RAG/质检）",
    promptSnippet: "出一道题",
    parameters: Type.Object({ subject: SUBJECT, kp_hint: Type.Optional(Type.String()) }),
    async execute(_id, params) {
      return { content: [{ type: "text", text: callTools("generate_question", { subject: params.subject, kp_hint: params.kp_hint ?? "" }) }] };
    },
  });

  pi.registerTool({
    name: "grade_answer",
    label: "批改",
    description: "批改用户作答（系统判定对错 + BKT/weights；结果回显 [KP=][TS=]）",
    promptSnippet: "批改用户的答案",
    parameters: Type.Object({
      last_question: Type.String({ description: "题目全文，空则系统自动读当前题" }),
      user_answer: Type.String({ description: "用户作答" }),
    }),
    async execute(_id, params) {
      return { content: [{ type: "text", text: callTools("grade_answer", { last_question: params.last_question, user_answer: params.user_answer }) }] };
    },
  });

  pi.registerTool({
    name: "adjust_difficulty",
    label: "调难度",
    description: "调整科目难度偏好（audit_only，不改 mastery）",
    promptSnippet: "调整出题难度",
    parameters: Type.Object({ subject: SUBJECT, level: LEVEL }),
    async execute(_id, params) {
      return { content: [{ type: "text", text: callTools("adjust_difficulty", { subject: params.subject, level: params.level }) }] };
    },
  });

  pi.registerTool({
    name: "note_weak_point",
    label: "记薄弱点",
    description: "用户自述知识点薄弱时抬高该点出题权重（只 bump weights，不写 BKT）",
    promptSnippet: "记录用户自述的薄弱知识点",
    parameters: Type.Object({ subject: SUBJECT, kp: Type.String(), reason: Type.Optional(Type.String()) }),
    async execute(_id, params) {
      return { content: [{ type: "text", text: callTools("note_weak_point", { subject: params.subject, kp: params.kp, reason: params.reason ?? "" }) }] };
    },
  });

  pi.registerTool({
    name: "kb_query",
    label: "查知识库",
    description: "小库只读查询（peek）",
    promptSnippet: "查询教材知识库",
    parameters: Type.Object({ subject: SUBJECT, kp: Type.String() }),
    async execute(_id, params) {
      return { content: [{ type: "text", text: callTools("kb_query", { subject: params.subject, kp: params.kp }) }] };
    },
  });

  // ── 确认类（confirm_add_kp / confirm_override）—— 走确认卡，Pi 工具不直接落盘 ──
  pi.registerTool({
    name: "propose_add_kp",
    label: "提案加知识点",
    description: "登记新增子知识点提案（不落盘，需确认卡）",
    promptSnippet: "提出新增子知识点",
    parameters: Type.Object({ subject: SUBJECT, l2: Type.String(), name: Type.String(), aliases: Type.Optional(Type.String()) }),
    async execute(_id, params) {
      return { content: [{ type: "text", text: callTools("propose_add_kp", { subject: params.subject, l2: params.l2, name: params.name, aliases: params.aliases ?? "" }) }] };
    },
  });

  pi.registerTool({
    name: "propose_override_grade",
    label: "提案纠正批改",
    description: "登记批改纠正提案（不落盘，需确认卡）",
    promptSnippet: "提出批改纠正",
    parameters: Type.Object({ kp: Type.String(), correct: Type.Boolean(), subject: Type.Optional(SUBJECT), credit: Type.Optional(Type.Number()) }),
    async execute(_id, params) {
      return { content: [{ type: "text", text: callTools("propose_override_grade", { kp: params.kp, correct: params.correct, subject: params.subject ?? "", credit: params.credit ?? 0 }) }] };
    },
  });

  // 安全护栏：Pi 不暴露 github_push / 裸写 / decide / 双周卷组卷
}
