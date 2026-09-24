# -*- coding: utf-8 -*-
"""DSH mentor host: forward PRACTICE_API_TOKEN; never enrich demo ids against live DB."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

HOST = os.path.join(ROOT, "integrations", "dsh-mentor-team", "host.js")

HARNESS = r"""
const fs = require('fs');
const hostPath = process.argv[2];
const mode = process.argv[3];
const calls = [];
let llmTurns = 0;

const web = {
  async fetch({ url, headers, method, body, stream }) {
    const rec = { url: String(url || ''), headers: Object.assign({}, headers || {}), method: method || 'GET' };
    calls.push(rec);
    const u = rec.url;
    if (u.indexOf('/chat/completions') >= 0) {
      llmTurns += 1;
      if (llmTurns === 1) {
        const payload = {
          choices: [{
            message: {
              content: null,
              tool_calls: [{
                id: 'call_demo_item',
                function: {
                  name: 'practice_get_item',
                  arguments: JSON.stringify({ item: 'demo-i2' }),
                },
              }],
            },
          }],
        };
        return { statusCode: 200, body: { content: JSON.stringify(payload) } };
      }
      return {
        statusCode: 200,
        body: { content: JSON.stringify({ choices: [{ message: { content: '已按工具结果讲解' } }] }) },
      };
    }
    if (u.indexOf('/api/v1/practice/') >= 0) {
      const tok = (headers && (headers['X-Practice-Token'] || headers['x-practice-token'])) || '';
      const need = process.env.PRACTICE_API_TOKEN || '';
      if (need && tok !== need) {
        return { statusCode: 401, body: { content: JSON.stringify({ ok: false, error: 'unauthorized' }) } };
      }
      if (mode === 'notoken') {
        return { statusCode: 401, body: { content: JSON.stringify({ ok: false, error: 'unauthorized' }) } };
      }
      if (u.indexOf('/practice/item') >= 0) {
        return {
          statusCode: 200,
          body: { content: JSON.stringify({
            ok: true,
            item: { id: 'i177', itemId: 177, title: '偏导数混入', kp: '偏导数', stem: 'REAL_PARTIAL', solutionSteps: ['live'] },
          }) },
        };
      }
      return {
        statusCode: 200,
        body: { content: JSON.stringify({
          ok: true,
          learner: 'cow',
          items: [{ id: 'i177', itemId: 177, title: '今日数学', kp: '夹逼', stem: 'live stem', answered: false }],
          capability: { masteryWeak: [], eta: {} },
        }) },
      };
    }
    if (u.indexOf('/v1/tools/') >= 0) {
      return {
        statusCode: 200,
        body: { content: JSON.stringify({
          ok: true,
          result: { id: 2, title: '偏导数', stem: 'REAL_PARTIAL', solutionSteps: ['DB item 2'] },
        }) },
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

const hostCode = fs.readFileSync(hostPath, 'utf8');
const plugin = new Function('harness', hostCode)(harness);
plugin.apply(ctx);

(async () => {
  const status = await harnessHandlers.get('mentor.status')({ learner: 'cow' });
  const chat = await harnessHandlers.get('mentor.chat')({
    learner: 'cow',
    item: 'demo-i2',
    message: '讲这道题',
    mentor: 'lecturer',
  });
  const livePractice = calls.filter((c) => c.url.indexOf('/api/v1/practice/') >= 0);
  const sysTools = calls.filter((c) => c.url.indexOf('/v1/tools/') >= 0);
  const itemLookups = calls.filter((c) => {
    const u = c.url;
    return u.indexOf('/practice/item') >= 0 || /[?&]item=i2(?:&|$)/.test(u) || /[?&]item=2(?:&|$)/.test(u);
  });
  const practiceTokenHeaders = livePractice.map((c) => c.headers['X-Practice-Token'] || c.headers['x-practice-token'] || '');
  const blob = JSON.stringify({ status, chat, calls });
  const mixed = /REAL_PARTIAL|偏导数/.test(blob) && /卷积/.test(String((chat && chat.reply) || ''));
  console.log(JSON.stringify({
    mode,
    connected: !!(status && status.connected),
    detached: !!(chat && chat.detached),
    groundKind: chat && chat.groundKind,
    practiceTokenConfigured: !!(status && status.practiceTokenConfigured),
    practiceError: (status && status.practiceError) || '',
    reply: (chat && chat.reply) || '',
    livePracticeCount: livePractice.length,
    sysToolsCount: sysTools.length,
    itemLookupCount: itemLookups.length,
    practiceTokenHeaders,
    mixed,
    liveUrls: livePractice.map((c) => c.url),
    sysUrls: sysTools.map((c) => c.url),
  }));
})().catch((e) => {
  console.error(String(e && e.stack ? e.stack : e));
  process.exit(1);
});
"""


def main() -> int:
    fails = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal fails
        print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails += 1

    js = open(HOST, encoding="utf-8").read()
    check("PRACTICE_API_TOKEN" in js and "X-Practice-Token" in js, "host reads PRACTICE_API_TOKEN → X-Practice-Token")
    check("async function practiceHeaders" in js, "practiceHeaders helper")
    check("function isDemoRef" in js, "isDemoRef isolates demo ids")
    check("id: 'demo-i1'" in js and "id: 'demo-i2'" in js and "id: 'demo-i3'" in js, "DEMO_ITEMS use demo-i* ids")
    check("id: 'i2'" not in js, "DEMO_ITEMS no longer use live-looking i2")
    check("pushId: 'demo-p2'" in js, "demo push ids are prefixed")
    idx_demo = js.find("if (isDemoRef(args.item, args.push))")
    idx_sys = js.find("SYSTEM_API_BASE + '/v1/tools/'")
    check(idx_demo >= 0 and idx_sys >= 0 and idx_demo < idx_sys, "execTool skips system_api for demo refs")
    check("if (isDemoRef(itemId, pushId)) return null" in js, "enrichItem skips demo refs")
    idx_try = js.find("async function tryLive")
    chunk = js[idx_try:idx_try + 800] if idx_try >= 0 else ""
    check("practiceHeaders" in chunk, "tryLive uses practiceHeaders")
    check("practiceFallback" in js and "await practiceHeaders(lid)" in js, "practiceFallback forwards practice auth")

    from modules.bridge.practice_dto import parse_item_id, parse_push_id

    check(parse_item_id("demo-i2") is None, "parse_item_id(demo-i2) is None")
    check(parse_item_id("i2") == 2, "parse_item_id(i2) still maps live public ids")
    check(parse_push_id("demo-p2") is None, "parse_push_id(demo-p2) is None")
    check(parse_push_id("2") == 2, "parse_push_id(2) still maps live pushes")

    node = "node"
    try:
        subprocess.run([node, "-v"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        print("[FAIL] node is required for DSH host harness")
        return fails + 1

    def run_mode(mode: str, extra_env: dict) -> dict:
        env = os.environ.copy()
        for k in ("PRACTICE_API_TOKEN", "DEEPSEEK_API_KEY", "LLM_API_KEY", "SYSTEM_API_TOKEN"):
            env.pop(k, None)
        env.update(extra_env)
        with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False, encoding="utf-8") as fh:
            fh.write(HARNESS)
            path = fh.name
        try:
            p = subprocess.run(
                [node, path, HOST, mode],
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
            raise RuntimeError(f"harness {mode} exited {p.returncode}")
        line = (p.stdout or "").strip().splitlines()[-1]
        return json.loads(line)

    missing = run_mode("notoken", {"DEEPSEEK_API_KEY": "test-llm-key"})
    check(missing.get("connected") is False, "missing token: tryLive not connected")
    check(missing.get("detached") is True and missing.get("groundKind") == "demo", "missing token: detached demo ground")
    check(missing.get("practiceTokenConfigured") is False, "missing token: practiceTokenConfigured=false")
    check(missing.get("practiceError") == "unauthorized", "missing token: 401 recorded, not silent live")
    check(missing.get("sysToolsCount") == 0, "missing token: demo-i2 must not hit system_api /v1/tools")
    check(missing.get("itemLookupCount") == 0, "missing token: demo-i2 must not enrich via /practice/item")
    check(not missing.get("mixed"), "missing token: demo 卷积 must not mix with live 偏导数")
    check("REAL_PARTIAL" not in (missing.get("reply") or ""), "missing token: reply has no live DB stem")
    check(
        all(not t for t in missing.get("practiceTokenHeaders") or []),
        "missing token: live practice calls have no X-Practice-Token",
    )

    secret = "test-practice-token-xyz"
    with_tok = run_mode("token", {"PRACTICE_API_TOKEN": secret})
    check(with_tok.get("practiceTokenConfigured") is True, "with token: practiceTokenConfigured")
    check(with_tok.get("connected") is True, "with token: tryLive connected")
    hdrs = with_tok.get("practiceTokenHeaders") or []
    check(len(hdrs) > 0 and all(h == secret for h in hdrs), "with token: X-Practice-Token on every live practice call")
    check(with_tok.get("livePracticeCount", 0) >= 1, "with token: at least one live practice call")

    return fails


if __name__ == "__main__":
    n = main()
    sys.exit(1 if n else 0)
