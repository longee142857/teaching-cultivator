/**
 * Pi extension: whitelist tools → Teaching System HTTP API.
 * Deploy to: ~/.pi/agent/extensions/teaching-api-client.ts  (NOT teaching git)
 *
 * Env:
 *   SYSTEM_API_BASE=http://127.0.0.1:8770
 *   SYSTEM_API_TOKEN=...
 *   TEACHING_LEARNER_ID=...  (fallback only; prefer session / pi_active_learner.json)
 *   TEACHING_ROOT=...        (default /home/ubuntu/teaching-cultivator)
 *
 * X-Learner-Id resolution (first hit wins):
 *   1. params.learner_id (optional override, stripped from body)
 *   2. current Pi session path/name: learners/{id}.jsonl or learner-{id}
 *   3. data/pi_active_learner.json (written by teaching pi_rpc_bridge per ask)
 *   4. TEACHING_LEARNER_ID / OWNER_STAFF_ID env fallback
 */
import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";

const BASE = (process.env.SYSTEM_API_BASE || "http://127.0.0.1:8770").replace(/\/$/, "");
const TOKEN = process.env.SYSTEM_API_TOKEN || "";
const DEFAULT_LEARNER = process.env.TEACHING_LEARNER_ID || process.env.OWNER_STAFF_ID || "";
const TEACHING_ROOT = (process.env.TEACHING_ROOT || "/home/ubuntu/teaching-cultivator").replace(/\/$/, "");

/** Updated on session / before_agent_start; bridge also writes a file under lock. */
let ACTIVE_LEARNER = DEFAULT_LEARNER;

function learnerFromSession(ctx?: ExtensionContext): string {
  try {
    const file = ctx?.sessionManager?.getSessionFile?.() || "";
    const m = /[/\\]learners[/\\]([^/\\]+)\.jsonl$/i.exec(file);
    if (m?.[1]) return m[1];
    const name = ctx?.sessionManager?.getSessionName?.() || "";
    if (name.startsWith("learner-")) return name.slice("learner-".length);
  } catch {
    /* ignore */
  }
  return "";
}

function learnerFromBridgeFile(): string {
  try {
    const p = path.join(TEACHING_ROOT, "data", "pi_active_learner.json");
    const raw = fs.readFileSync(p, "utf8");
    const j = JSON.parse(raw) as { learner_id?: string };
    return String(j.learner_id || "").trim();
  } catch {
    return "";
  }
}

function resolveLearnerId(ctx?: ExtensionContext, explicit?: string): string {
  const ex = (explicit || "").trim();
  if (ex) return ex;
  // 桥在 ask 锁内写入的是钉钉 staffId（权威）
  const fromFile = learnerFromBridgeFile();
  if (fromFile) return fromFile;
  const fromSession = learnerFromSession(ctx);
  if (fromSession) return fromSession;
  const active = (ACTIVE_LEARNER || "").trim();
  if (active) return active;
  return (DEFAULT_LEARNER || "").trim();
}

async function apiCall(
  tool: string,
  params: Record<string, unknown>,
  ctx?: ExtensionContext,, ctx): Promise<string> {
  const body: Record<string, unknown> = { ...params };
  let explicit = "";
  if (typeof body.learner_id === "string") {
    explicit = body.learner_id;
    delete body.learner_id;
  }
  const lid = resolveLearnerId(ctx, explicit);
  if (!lid) {
    return `[system_api:${tool}] missing learner_id (no session/file/env)`;
  }
  ACTIVE_LEARNER = lid;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Learner-Id": lid,
  };
  if (TOKEN) {
    headers.Authorization = `Bearer ${TOKEN}`;
    headers["X-System-Token"] = TOKEN;
  }
  const url = `${BASE}/v1/tools/${encodeURIComponent(tool)}`;
  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const text = await res.text();
  try {
    const j = JSON.parse(text);
    if (j.ok) return String(j.result ?? "");
    return `[system_api:${tool}] ${j.error || text}`;
  } catch {
    return `[system_api:${tool}] HTTP ${res.status}: ${text.slice(0, 500)}`;
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

function textResult(s: string) {
  return { content: [{ type: "text" as const, text: s }] };
}

export default function teachingApiClient(pi: ExtensionAPI) {
  const refreshLearner = (_ev: unknown, ctx: ExtensionContext) => {
    const id = learnerFromSession(ctx) || learnerFromBridgeFile();
    if (id) ACTIVE_LEARNER = id;
  };
  pi.on("session_start", refreshLearner);
  pi.on("before_agent_start", refreshLearner);


  pi.registerTool({
    name: "get_active_question",
    label: "当前题目",
    description: "获取当前正在做的题（系统单一真相源）",
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _onUpdate, ctx) {
      return textResult(await apiCall("get_active_question", {}, ctx));
    },
  });

  pi.registerTool({
    name: "list_today_questions",
    label: "今日题库",
    description: "今日推送题列表（含 answered；按推送时间升序，非未答优先）",
    parameters: Type.Object({
      subject: Type.Optional(SUBJECT),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("list_today_questions", {
          subject: params.subject ?? "",
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "get_learner_snapshot",
    label: "学习指标",
    description: "学习指标快照",
    parameters: Type.Object({ days: Type.Optional(Type.Number()) }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(await apiCall("get_learner_snapshot", { days: params.days ?? 7 }, ctx));
    },
  });

  pi.registerTool({
    name: "list_recent_entries",
    label: "最近题目",
    description: "近 N 天题目索引",
    parameters: Type.Object({ days: Type.Optional(Type.Number()) }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(await apiCall("list_recent_entries", { days: params.days ?? 7 }, ctx));
    },
  });

  pi.registerTool({
    name: "find_record_entry",
    label: "取题目全文",
    description: "按日期取题目记录",
    parameters: Type.Object({
      date: Type.String(),
      num: Type.Optional(Type.Number()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("find_record_entry", { date: params.date, num: params.num ?? 0 }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "list_knowledge_points",
    label: "考纲知识点",
    description: "列出考纲 L2/L3",
    parameters: Type.Object({
      subject: Type.Optional(SUBJECT),
      query: Type.Optional(Type.String()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("list_knowledge_points", {
          subject: params.subject ?? "math",
          query: params.query ?? "",
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "kb_query",
    label: "查知识库",
    description: "小库只读 peek",
    parameters: Type.Object({ subject: SUBJECT, kp: Type.String() }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(await apiCall("kb_query", { subject: params.subject, kp: params.kp }, ctx));
    },
  });

  pi.registerTool({
    name: "kb_enqueue",
    label: "知识回填排队",
    description: "只进回填队列，不直写 Chroma",
    parameters: Type.Object({
      subject: SUBJECT,
      kp: Type.String(),
      query: Type.Optional(Type.String()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("kb_enqueue", {
          subject: params.subject,
          kp: params.kp,
          query: params.query ?? "",
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "generate_question",
    label: "出题",
    description: "走系统 cultivate/RAG/质检出题",
    parameters: Type.Object({
      subject: SUBJECT,
      kp_hint: Type.Optional(Type.String()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("generate_question", {
          subject: params.subject,
          kp_hint: params.kp_hint ?? "",
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "grade_answer",
    label: "批改",
    description: "批改作答；结果含 [KP=][TS=]；空 last_question 时系统读当前题",
    parameters: Type.Object({
      last_question: Type.Optional(Type.String()),
      user_answer: Type.String(),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("grade_answer", {
          last_question: params.last_question ?? "",
          user_answer: params.user_answer,
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "show_solution",
    label: "看解答",
    description: "系统生成解答（不写 BKT）",
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _onUpdate, ctx) {
      return textResult(await apiCall("show_solution", {}, ctx));
    },
  });

  pi.registerTool({
    name: "adjust_difficulty",
    label: "调难度",
    description: "audit_only，不改 mastery",
    parameters: Type.Object({ subject: SUBJECT, level: LEVEL }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("adjust_difficulty", { subject: params.subject, level: params.level }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "note_weak_point",
    label: "记薄弱点",
    description: "抬高权重，不写 BKT",
    parameters: Type.Object({
      subject: SUBJECT,
      kp: Type.String(),
      reason: Type.Optional(Type.String()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("note_weak_point", {
          subject: params.subject,
          kp: params.kp,
          reason: params.reason ?? "",
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "build_report",
    label: "周报",
    description: "学习周报",
    parameters: Type.Object({ days: Type.Optional(Type.Number()) }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(await apiCall("build_report", { days: params.days ?? 7 }, ctx));
    },
  });

  pi.registerTool({
    name: "list_exam_bank",
    label: "双周卷目录",
    description: "试卷列表",
    parameters: Type.Object({
      query: Type.Optional(Type.String()),
      limit: Type.Optional(Type.Number()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("list_exam_bank", {
          query: params.query ?? "",
          limit: params.limit ?? 20,
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "get_exam_paper",
    label: "取试卷",
    description: "试卷全文",
    parameters: Type.Object({ paper_id: Type.Optional(Type.String()) }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(await apiCall("get_exam_paper", { paper_id: params.paper_id ?? "" }, ctx));
    },
  });

  pi.registerTool({
    name: "get_exam_result",
    label: "取批改结果",
    description: "某人某卷批改报告",
    parameters: Type.Object({
      paper_id: Type.String(),
      user_id: Type.Optional(Type.String()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("get_exam_result", {
          paper_id: params.paper_id,
          user_id: params.user_id ?? "",
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "submit_exam_answer_md",
    label: "提交双周答卷",
    description: "Markdown 答卷提交",
    parameters: Type.Object({
      md_text: Type.String(),
      paper_id: Type.Optional(Type.String()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("submit_exam_answer_md", {
          md_text: params.md_text,
          paper_id: params.paper_id ?? "",
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "propose_add_kp",
    label: "提案加知识点",
    description: "只登记提案，需确认卡",
    parameters: Type.Object({
      subject: SUBJECT,
      l2: Type.String(),
      name: Type.String(),
      aliases: Type.Optional(Type.String()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("propose_add_kp", {
          subject: params.subject,
          l2: params.l2,
          name: params.name,
          aliases: params.aliases ?? "",
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "confirm_add_kp",
    label: "确认加知识点",
    parameters: Type.Object({ token: Type.String() }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(await apiCall("confirm_add_kp", { token: params.token }, ctx));
    },
  });

  pi.registerTool({
    name: "cancel_add_kp",
    label: "取消加知识点",
    parameters: Type.Object({ token: Type.String() }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(await apiCall("cancel_add_kp", { token: params.token }, ctx));
    },
  });

  pi.registerTool({
    name: "propose_override_grade",
    label: "提案纠正批改",
    parameters: Type.Object({
      kp: Type.String(),
      correct: Type.Boolean(),
      subject: Type.Optional(SUBJECT),
      credit: Type.Optional(Type.Number()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("propose_override_grade", {
          kp: params.kp,
          correct: params.correct,
          subject: params.subject ?? "",
          credit: params.credit ?? 0,
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "confirm_override",
    label: "确认纠正批改",
    parameters: Type.Object({ token: Type.String() }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(await apiCall("confirm_override", { token: params.token }, ctx));
    },
  });

  pi.registerTool({
    name: "cancel_override",
    label: "取消纠正批改",
    parameters: Type.Object({ token: Type.String() }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(await apiCall("cancel_override", { token: params.token }, ctx));
    },
  });

  pi.registerTool({
    name: "ocr_handwriting",
    label: "识别手写图",
    description:
      "识别人机私聊已暂存的手写/演算图片（不批改）。image_id 可空=该学员最新一张。用户只想看图里写了什么时用。",
    parameters: Type.Object({
      image_id: Type.Optional(Type.String()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("ocr_handwriting", {
          image_id: params.image_id ?? "",
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "grade_handwriting",
    label: "批改手写作答",
    description:
      "把私聊暂存图片 OCR 后按当前题 grade_answer。仅当用户明确说这是作答/交卷/重做时调用；勿对表情包、无关截图调用。image_id 可空=最新一张。",
    parameters: Type.Object({
      image_id: Type.Optional(Type.String()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("grade_handwriting", {
          image_id: params.image_id ?? "",
        }, ctx)
      );
    },
  });

  pi.registerTool({
    name: "write_feedback",
    label: "写反馈",
    description:
      "把系统问题/改进建议写入 problem_queue（同步到本机 tasks/problem/）；不改教学状态",
    parameters: Type.Object({
      title: Type.Optional(Type.String()),
      content: Type.String(),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      return textResult(
        await apiCall("write_feedback", {
          title: params.title ?? "",
          content: params.content,
        }, ctx)
      );
    },
  });
}
