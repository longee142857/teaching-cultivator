# -*- coding: utf-8 -*-
"""Discuss follow-ups keep the same item thread and see prior turns in the LLM prompt."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = os.path.join(ROOT, "integrations", "dsh-mentor-team", "host.js")
SHELL = os.path.join(ROOT, "web", "static", "teaching-shell.html")

DRAFT = "DRAFT_TOKEN_QX7"
KEEP = "KEEP_TOKEN_MID"
SEED = (
    "我把手写识别/整理成了下面这份草稿（尚未正式交卷）。请帮我核对识别是否准确、推导有没有明显问题；"
    "讨论清楚后我再回练习台点提交。\n\n【草稿】\n" + DRAFT + " 夹逼两端都趋于 L"
)
FOLLOW = "第二步的符号对吗"
OTHER = "另一题只问定义"
WINDOW_OUT = "窗口外了吗"

HARNESS = r"""
const fs = require('fs');
const hostPath = process.argv[2];
const llmCalls = [];

const web = {
  async fetch({ url, method, body }) {
    const u = String(url || '');
    if (u.indexOf('/chat/completions') >= 0) {
      let parsed = {};
      try { parsed = JSON.parse(body || '{}'); } catch (e) { parsed = {}; }
      const messages = parsed.messages || [];
      llmCalls.push(messages.map(function (m) {
        return { role: m.role, content: String(m.content || '') };
      }));
      const n = llmCalls.length;
      return {
        statusCode: 200,
        body: { content: JSON.stringify({ choices: [{ message: { content: 'ack-' + n } }] }) },
      };
    }
    return { statusCode: 404, body: { content: '{}' } };
  },
};

const harnessHandlers = new Map();
const harness = {
  handle(name, fn) {
    harnessHandlers.set(name, fn);
    return () => harnessHandlers.delete(name);
  },
};

const ctx = {
  get(key) {
    if (key === 'web') return web;
    if (key === 'webServer') return null;
    if (key === 'fs') return null;
    if (key === 'sandboxPolicy') return { workspaceRoot: '' };
    return undefined;
  },
  effect() { return () => {}; },
};

const plugin = new Function('harness', fs.readFileSync(hostPath, 'utf8'))(harness);
plugin.apply(ctx);

function blob(messages, token) {
  return (messages || []).some(function (m) { return String(m.content || '').indexOf(token) >= 0; });
}

(async () => {
  const chat = harnessHandlers.get('mentor.chat');
  const base = { learner: 'cow', mentor: 'lecturer', item: 'i12', push: 'p12', threadId: 'i12', blank: false };

  const seed = await chat(Object.assign({}, base, { message: process.env.SEED_MSG }));
  const otherLearner = await chat({
    learner: 'cow2', mentor: 'lecturer', item: 'i12', threadId: 'i12', blank: false, message: 'hello-other-learner',
  });
  const otherThread = await chat({
    learner: 'cow', mentor: 'lecturer', item: 'i99', push: 'p99', threadId: 'i99', blank: false, message: process.env.OTHER_MSG,
  });
  const follow = await chat(Object.assign({}, base, { message: process.env.FOLLOW_MSG }));

  await chat(Object.assign({}, base, { message: 'filler-3 ' + process.env.KEEP_TOKEN }));
  for (let n = 4; n <= 8; n++) {
    await chat(Object.assign({}, base, { message: 'filler-' + n }));
  }
  const overflow = await chat(Object.assign({}, base, { message: process.env.WINDOW_MSG }));

  const exported = await harnessHandlers.get('mentor.export')({ learner: 'cow' });
  const exportedOther = await harnessHandlers.get('mentor.export')({ learner: 'cow2' });
  const keys = Object.keys((exported && exported.threads) || {});
  const otherKeys = Object.keys((exportedOther && exportedOther.threads) || {});

  console.log(JSON.stringify({
    seedReply: seed && seed.reply,
    followReply: follow && follow.reply,
    otherLearnerReply: otherLearner && otherLearner.reply,
    otherThreadReply: otherThread && otherThread.reply,
    overflowReply: overflow && overflow.reply,
    callCount: llmCalls.length,
    seedMessages: llmCalls[0] || [],
    otherLearnerMessages: llmCalls[1] || [],
    otherThreadMessages: llmCalls[2] || [],
    followMessages: llmCalls[3] || [],
    overflowMessages: llmCalls[llmCalls.length - 1] || [],
    threadKeys: keys,
    otherLearnerThreadKeys: otherKeys,
    i12Len: ((exported.threads || {}).i12 || []).length,
    i99HasDraft: blob((((exported.threads || {}).i99) || []).map(function (t) { return { content: t.text }; }), process.env.DRAFT_TOKEN),
    cow2HasDraft: blob((((exportedOther.threads || {}).i12) || []).map(function (t) { return { content: t.text }; }), process.env.DRAFT_TOKEN),
  }));
})().catch(function (e) {
  console.error(String(e && e.stack ? e.stack : e));
  process.exit(1);
});
"""


def _has(messages, token: str, role: str | None = None) -> bool:
    for m in messages or []:
        if role is not None and m.get("role") != role:
            continue
        if token in str(m.get("content") or ""):
            return True
    return False


def main() -> int:
    fails = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal fails
        print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails += 1

    js = open(HOST, encoding="utf-8").read()
    html = open(SHELL, encoding="utf-8").read()
    cap_m = re.search(r"const THREAD_PROMPT_TURNS = (\d+)", js)
    check(cap_m is not None, "THREAD_PROMPT_TURNS constant")
    cap = int(cap_m.group(1)) if cap_m else 0
    check(1 <= cap <= 40, f"prompt window bounded, got {cap}")
    check("function recentThreadMessages" in js, "recentThreadMessages reader")
    check("recentThreadMessages(learnerId, opts && opts.threadId, msg)" in js, "buildMessages reads this threadId")
    check("threadId: threadId" in js, "runAgent opts carry the chat threadId")
    check("if (arr.length > 40) arr.splice(0, arr.length - 40)" in js, "store cap stays 40")

    fn = re.search(r"function sendDraftToTutor\(\) \{([\s\S]*?)\n      function reportPoorItem", html)
    check(fn is not None, "sendDraftToTutor present")
    if fn:
        body = fn.group(1)
        parts = body.split("} else {", 1)
        check(len(parts) == 2, "sendDraftToTutor has item and no-item branches")
        if len(parts) == 2:
            check("state.contextItemId = item.id" in parts[0], "item discussion keeps item id as thread")
            check("newGeneralThreadId" not in parts[0], "item discussion does not mint general-*")
            check("newGeneralThreadId" in parts[1], "general-* only when there is no current item")
    send = re.search(r"function sendChat\(text\) \{([\s\S]*?)\n      function consumeSse", html)
    check(send is not None and "newGeneralThreadId" not in send.group(1), "sendChat does not mint a thread id")
    check(send is not None and "threadId: tid" in send.group(1), "sendChat posts the current thread id")

    node = "node"
    try:
        subprocess.run([node, "-v"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        print("[FAIL] node is required for DSH host harness")
        return fails + 1

    env = os.environ.copy()
    for k in ("PRACTICE_API_TOKEN", "DEEPSEEK_API_KEY", "LLM_API_KEY", "SYSTEM_API_TOKEN"):
        env.pop(k, None)
    env["DEEPSEEK_API_KEY"] = "test-llm-key"
    env["SEED_MSG"] = SEED
    env["FOLLOW_MSG"] = FOLLOW
    env["OTHER_MSG"] = OTHER
    env["WINDOW_MSG"] = WINDOW_OUT
    env["KEEP_TOKEN"] = KEEP
    env["DRAFT_TOKEN"] = DRAFT

    with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False, encoding="utf-8") as fh:
        fh.write(HARNESS)
        path = fh.name
    try:
        p = subprocess.run(
            [node, path, HOST],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if p.returncode != 0:
        print(p.stderr or p.stdout)
        print("[FAIL] harness exited")
        return fails + 1
    data = json.loads((p.stdout or "").strip().splitlines()[-1])

    seed_msgs = data["seedMessages"]
    follow_msgs = data["followMessages"]
    other_learner = data["otherLearnerMessages"]
    other_thread = data["otherThreadMessages"]
    overflow = data["overflowMessages"]

    check(data["seedReply"] == "ack-1", f"seed turn used LLM, got {data['seedReply']!r}")
    check(len(seed_msgs) == 2 and seed_msgs[0]["role"] == "system" and seed_msgs[-1]["role"] == "user",
          "first discuss turn is system + current user only")
    check(DRAFT in seed_msgs[-1]["content"], "seed prompt contains the draft")
    check("承接上文" not in seed_msgs[0]["content"], "first turn does not claim prior thread")

    check(not _has(other_learner, DRAFT), "other learner does not see this thread")
    check(not _has(other_thread, DRAFT), "other item thread does not see this draft")
    check(data["otherThreadReply"] == "ack-3", f"other thread still answered, got {data['otherThreadReply']!r}")

    check(data["followReply"] == "ack-4", f"follow-up used LLM, got {data['followReply']!r}")
    check(follow_msgs and follow_msgs[0]["role"] == "system" and follow_msgs[-1]["role"] == "user",
          "follow-up keeps system then history then current user")
    check(len(follow_msgs) == 4, f"follow-up sees one prior exchange, got {len(follow_msgs)} messages")
    prior_users = [m for m in follow_msgs[:-1] if m["role"] == "user"]
    check(any(m["content"] == SEED for m in prior_users), "prior user turn is the stored discuss seed")
    check(all("【接地上下文】" not in m["content"] for m in prior_users), "history is the raw turn, not re-grounded")
    check(_has(follow_msgs[:-1], "ack-1", role="assistant"), "prior lecturer reply is in the prompt")
    check(FOLLOW in follow_msgs[-1]["content"] and "【学员消息】" in follow_msgs[-1]["content"],
          "short follow-up is the current user turn")
    check(DRAFT not in follow_msgs[-1]["content"], "draft is not only inside the latest short message")
    check("承接上文" in follow_msgs[0]["content"], "follow-up system prompt says to continue the thread")

    check(data["callCount"] == 11, f"expected 11 LLM calls, got {data['callCount']}")
    check(len(overflow) == cap + 2, f"overflow prompt is system+{cap} history+current, got {len(overflow)}")
    check(not _has(overflow, DRAFT), "turns older than the prompt window are dropped")
    check(_has(overflow, KEEP), "a turn still inside the window remains")
    check(WINDOW_OUT in overflow[-1]["content"], "latest short turn is still sent")
    check(data["overflowReply"].startswith("ack-"), "windowed follow-up still called the LLM")

    keys = data["threadKeys"]
    check("i12" in keys and "i99" in keys, f"export keeps item thread ids, got {keys}")
    check(not any(k == "general" or str(k).startswith("general-") for k in keys),
          f"discuss did not spawn general-*, got {keys}")
    check(data["i12Len"] == 18, f"i12 stored 9 exchanges (18 turns), got {data['i12Len']}")
    check(data["i99HasDraft"] is False, "i99 transcript has no draft token")
    check(data["otherLearnerThreadKeys"] == ["i12"], f"cow2 thread key is i12, got {data['otherLearnerThreadKeys']}")
    check(data["cow2HasDraft"] is False, "cow2 i12 transcript has no cow draft")

    return fails


if __name__ == "__main__":
    n = main()
    sys.exit(1 if n else 0)
