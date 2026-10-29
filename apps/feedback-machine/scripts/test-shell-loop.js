#!/usr/bin/env node
"use strict";

var fs = require("fs");
var path = require("path");
var vm = require("vm");

var root = path.join(__dirname, "..");

function read(rel) {
  return fs.readFileSync(path.join(root, rel), "utf8");
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

var context = {
  console: console,
  setTimeout: setTimeout,
  clearTimeout: clearTimeout
};
context.window = context;
context.self = context;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(read("www/vendor/katex/katex.min.js"), context, { filename: "katex.min.js" });
vm.runInContext(read("www/js/math.js"), context, { filename: "math.js" });
vm.runInContext(read("www/js/loop.js"), context, { filename: "loop.js" });

var math = context.FqmMath;
var loop = context.FqmLoop;

var inline = math.renderMathMarkdown("求 $x^2$ 的值");
assert(inline.indexOf("katex") >= 0, "inline $...$ should render with KaTeX");
assert(inline.indexOf("katex-html") >= 0, "inline math includes katex html");

var display = math.renderMathMarkdown("$$\\frac{1}{2}$$");
assert(display.indexOf("katex-display") >= 0, "$$...$$ should be display mode");

var bracket = math.renderMathMarkdown("行内 \\(a+b\\) 与 \\[c+d\\]");
assert(bracket.indexOf("katex") >= 0, "\\(\\) and \\[\\] should render");
assert((bracket.match(/katex-display/g) || []).length >= 1, "\\[\\] should be display");

var stem = math.renderStemHtml({
  title: "题一",
  stem: "题一：计算 $1+1$",
  options: [{ letter: "A", text: "$2$" }]
});
assert(stem.indexOf("计算") >= 0, "stem keeps body after title prefix");
assert(stem.indexOf("题一：") === -1, "title prefix stripped like the desk");
assert(stem.indexOf("mcq-letter") >= 0, "options render");
assert(stem.indexOf(">A<") >= 0, "option letter kept");

var eigenvalue =
  "设 $n$ 阶可逆矩阵 $\\pmb{A}$ 的各行元之和均为常数 $k$ ，求 $2A^{-1} + 4A$ 的一个特征值与对应的一个特征向量.";
assert(math.prefixCutsMath(eigenvalue, 48), "i1214: index 48 sits inside $2A^{-1}+4A$");
var evHtml = math.renderStemHtml({ title: eigenvalue.slice(0, 48), stem: eigenvalue });
assert(evHtml.indexOf("阶可逆矩阵") >= 0, "bisecting title is not stripped from the stem");
assert(evHtml.indexOf("+ 4A$") === -1, "stem is not left starting at + 4A$");
assert(evHtml.indexOf("katex") >= 0, "full eigenvalue stem still typesets");

var casesStem =
  "考察函数 $f(x) = \\begin{cases} \\sqrt{1 - 4x - x^2}, & -4 \\leqslant x < 0 \\\\ x^3 - x^2 - 2x + 1, & 0 \\leqslant x \\leqslant 1 \\end{cases}$ 在闭区间上求 $\\xi$.";
assert(math.prefixCutsMath(casesStem, 48), "i688: index 48 sits inside cases");
var casesHtml = math.renderStemHtml({ title: casesStem.slice(0, 48), stem: casesStem });
assert(casesHtml.indexOf("考察函数") >= 0, "cases lead-in stays when the title bisects math");
assert(casesHtml.indexOf("katex") >= 0, "cases stem typesets");

var titled = math.renderMathTitle("求 $x^2$ 与 $$\\int_0^1 x\\,dx$$");
assert(titled.indexOf("<p>") === -1, "title math is not wrapped in a paragraph");
assert(titled.indexOf("katex") >= 0, "title inline math typesets");
assert(titled.indexOf("katex-display") >= 0, "title display math typesets");
assert(titled.indexOf("$x^2$") === -1, "title does not keep dollar delimiters");

var appJs = read("www/js/app.js");
assert(appJs.indexOf("FqmMath.renderMathTitle") >= 0, "APK heading uses KaTeX");
var desk = fs.readFileSync(path.join(root, "../../web/static/teaching-shell.html"), "utf8");
assert(desk.indexOf("renderMathTitle(item.title") >= 0, "practice desk heading uses KaTeX");
assert(desk.indexOf("prefixCutsMath") >= 0, "practice desk refuses a mid-math title cut");

var katexOnly = math.renderStemHtml({ stem: "见公式", katex: "x+1" });
assert(katexOnly.indexOf("data-tex=") >= 0, "bare katex field becomes a math block");
var delimited = math.renderStemHtml({ stem: "见 $x$", katex: "x+1" });
assert(delimited.indexOf("data-tex=") === -1, "delimited stem does not duplicate katex field");

assert(loop.bankKind("comm") === null, "empty comm slot does not refill the thin bank");
assert(loop.bankKind("review") === "review", "review slot refills as review");
assert(loop.bankKind("") === "math", "empty kind defaults to math");
assert(loop.bankKind("math") === "math", "math stays math");
assert(loop.rememberKind("math", "comm") === "math", "opening a comm item must not retarget the bank");
assert(loop.rememberKind("math", "review") === "review", "review item is remembered");

var queued = loop.pickNextLocal(
  [
    { id: "c1", kind: "comm", answered: false },
    { id: "m1", kind: "math", answered: false },
    { id: "r1", kind: "review", answered: false }
  ],
  null
);
assert(queued && queued.id === "c1", "already pushed comm stays in the today queue");
var reviewNext = loop.pickNextLocal(
  [
    { id: "m1", kind: "math", answered: true },
    { id: "r1", kind: "review", answered: false }
  ],
  "m1"
);
assert(reviewNext && reviewNext.id === "r1", "default next reaches the review slot");

var sse = loop.parseSse('event: delta\ndata: {"text":"你"}\n\nevent: done\ndata: {"reply":"你好"}\n\n');
assert(sse && sse.length === 2 && sse[0].data.text === "你" && sse[1].data.reply === "你好", "SSE deltas parse");
assert(
  loop.listTutorSessions([{ id: "general-1", title: "新对话" }], { "m1": [] }, [{ id: "m1", subject: "高等数学", title: "导数" }]).length >= 2,
  "recent sessions include general and item threads"
);

var state = { items: [{ id: "m1", kind: "math", answered: false }], current: null };
var route = loop.routeSubmit(
  state,
  { ok: true, httpStatus: 200, result: { correct: true, status: "graded", comment: "ok" } },
  { id: "m1" }
);
assert(route === "feedback", "immediate submit routes to feedback");
assert(state.screen === "feedback", "immediate submit sets feedback screen");
assert(state.busy === false, "immediate submit clears busy");
assert(state.items[0].answered === true, "answered item leaves the local queue");
state.slots = [
  { kind: "math", itemId: "m1", pushId: 1 },
  { kind: "comm", itemId: "c1", pushId: 2 }
];
state.items.push({ id: "m2", kind: "math", answered: false });
state.items.push({ id: "c1", kind: "comm", answered: true });
state.slots = loop.retireFinishedSlots(state.slots, state.items, null);
assert(state.slots[0].itemId === "m2", "finished math slot advances to the next open item");
assert(state.slots[1].itemId === "", "finished comm slot is cleared");
var kept = loop.retireFinishedSlots(
  [{ kind: "review", itemId: "r2" }],
  [{ id: "r1", kind: "review", answered: true }, { id: "r2", kind: "review", answered: false, backlog: true }],
  null
);
assert(kept[0].itemId === "r2", "an open slot occupant stays");
var noBacklog = loop.retireFinishedSlots(
  [{ kind: "review", itemId: "r1" }],
  [{ id: "r1", kind: "review", answered: true }, { id: "r9", kind: "review", answered: false, backlog: true }],
  null
);
assert(noBacklog[0].itemId === "", "backlog does not refill a finished slot");
assert(loop.restorePracticeScreen("feedback", { hasCurrent: true, hasResult: true }) === "feedback", "practice tab restores the grade page");
assert(loop.restorePracticeScreen("practice", { hasCurrent: true, hasResult: false }) === "practice", "practice tab restores the current item");
assert(loop.restorePracticeScreen("practice", { hasCurrent: false }) === "today", "practice tab without an item falls back to today");
assert(loop.restorePracticeScreen("feedback", { hasCurrent: true, hasResult: false }) === "practice", "grade page without a result returns to the item");
assert(loop.restorePracticeScreen("done", {}) === "done", "done page is restored");
assert(loop.tabForScreen("feedback") === "practice" && loop.tabForScreen("exam") === "exam", "practice pages share one tab");
assert(loop.tabForScreen("settings") === "", "settings is not a bottom tab");

var denied = { screen: "practice", busy: true, items: [], error: "" };
assert(loop.routeSubmit(denied, { ok: false, httpStatus: 401, error: "unauthorized" }, null) === "unauthorized");
assert(denied.screen === "settings", "401 opens settings");
assert(denied.error.indexOf("401") >= 0, "401 copy names the status");
assert(denied.error.indexOf("Token") >= 0, "401 copy names the token");
assert(loop.shouldPollAfterSubmit({ ok: false, httpStatus: 401, error: "unauthorized" }) === false, "401 does not poll");

var grading = { screen: "practice", busy: true, items: [] };
assert(
  loop.routeSubmit(grading, { ok: true, httpStatus: 200, pending: true, result: { status: "grading" } }, { id: "m1" }) ===
    "poll",
  "async grade still polls"
);

var leakedGrade =
  "与参考答案不一致（ref 模式）。（LLM 不可用：Could not find a suitable TLS CA certificate bundle, invalid path: /home/ubuntu/teaching-cultivator-practice/venv/lib/python3.12/site-packages/certifi/cacert.pem）";
var cleanGrade = loop.studentGradeComment(leakedGrade);
assert(cleanGrade.indexOf("cacert.pem") < 0 && cleanGrade.indexOf("teaching-cultivator-practice") < 0, "grade comment drops the certifi path");
assert(cleanGrade.indexOf("正式评分") >= 0, "grade comment says the fallback is not a formal grade");
var fallbackBanner = loop.gradeBanner({ correct: false, gradeMode: "ref_fallback" });
assert(fallbackBanner.text === "初判未对齐" && fallbackBanner.sub.indexOf("不是正式评分") >= 0, "LLM-down mismatch is not a normal wrong answer");
assert(loop.gradeBanner({ correct: false, gradeMode: "llm" }).text === "未通过", "a real incorrect grade stays 未通过");
assert(loop.shouldRefreshToday({ screen: "today", busy: false, polling: false }) === true, "today overview can refetch slots");
assert(loop.shouldRefreshToday({ screen: "practice", busy: true, polling: false }) === false, "in-flight submit does not refetch");

var wired = loop.tutorReplyText({ httpStatus: 501, error: "tutor_agent_not_wired" }, "为什么");
assert(wired.indexOf("讲师暂时连不上") >= 0 && wired.indexOf("为什么") >= 0, "501 matches desk copy");
assert(loop.tutorReplyText({ httpStatus: 200, reply: "看这一步" }, "x") === "看这一步", "JSON reply is shown");

var app = read("www/js/app.js");
assert(/route === "feedback"[\s\S]{0,220}state\.busy = false[\s\S]{0,120}render\(/.test(app), "success path sets busy=false and render()");
assert(/if \(state\.screen === "feedback"\) return;/.test(app), "finally still skips an already painted feedback screen");
assert(/FqmLoop\.bankKind\(/.test(app), "empty-slot refill goes through bankKind");
assert(app.indexOf("studentGradeComment") >= 0 && app.indexOf("gradeBanner") >= 0, "feedback render scrubs fallback copy");
assert(app.indexOf("visibilitychange") >= 0, "shell refetches today slots when it returns to the foreground");
assert(app.indexOf("restorePracticeScreen") >= 0 && app.indexOf("showTutorTab") >= 0, "bottom tabs restore the last page instead of remounting");
assert(/id === "tutor"\) showTutorTab\(/.test(app) || /id === "tutor"\)[\s\S]{0,40}showTutorTab\(/.test(app), "讲师 tab does not rebind the thread");
assert(app.indexOf("ensureExam") >= 0 && app.indexOf("state.examUrl") >= 0, "周卷 keeps the paper already open");
assert(app.indexOf("retireFinishedSlots") >= 0, "finished occupants leave the local slots");
assert(desk.indexOf("function retireFinishedSlots") >= 0, "practice desk retires finished slots the same way");
assert(desk.indexOf("scrollMem") >= 0 && desk.indexOf("restoreMode") >= 0, "practice desk restores tab scroll");
assert(desk.indexOf('id="exam-host"') >= 0, "practice desk keeps the exam frame mounted");
assert(app.indexOf("不懂，问讲师") >= 0, "tutor entry uses the desk label");
assert(app.indexOf("/api/v1/tutor/chat") === -1, "tutor URL stays in api.js");

var api = read("www/js/api.js");
assert(api.indexOf("CapacitorHttp") >= 0 && api.indexOf("isNativePlatform") >= 0, "native transport stays CapacitorHttp");
assert(api.indexOf('"/api/v1/tutor/chat"') >= 0, "tutor uses the practice tutor route");
assert(api.indexOf("text/event-stream") >= 0, "tutor asks for the desk SSE stream");
assert(api.indexOf("/api/v1/practice/ocr") >= 0, "ocr uses the practice route");
assert(api.indexOf("/api/v1/practice/report-poor") >= 0, "poor-item uses the practice route");
assert(api.indexOf("/api/v1/exam/papers") >= 0, "exam list uses the practice route");
assert(api.indexOf("/api/v1/notes") < 0, "shell does not call the materials route");
assert(app.indexOf("复制原文") >= 0 && app.indexOf("msgSourceAt") >= 0, "lecturer copy reads the message source");
assert(app.indexOf('tab("notes"') < 0 && app.indexOf("资料库") < 0, "materials tab is removed from the shell");
assert(app.indexOf('tab("brain", "能力"') >= 0 && app.indexOf("brain/index.html") >= 0, "capability tab opens the vendored brain");
assert(desk.indexOf('data-nav="notes"') < 0, "practice desk drops the materials nav");
assert(desk.indexOf("/api/v1/notes") < 0, "practice desk does not fetch materials");
assert(desk.indexOf("复制原文") >= 0 && desk.indexOf("function msgSourceAt") >= 0, "practice desk still copies original lecturer text");
assert(desk.indexOf("repeat(3, 1fr)") >= 0, "practice desk tab bar matches the three remaining tabs");
assert(/SWIPE_THRESHOLD\s*=\s*56/.test(app), "swipe threshold matches the desk");
assert(app.indexOf("function bindSwipe") >= 0, "pointer swipe is bound");
assert(app.indexOf("flip-sheet") >= 0, "pages ride a flip sheet");
assert(app.indexOf('data-theme-pick="desk"') >= 0, "desk theme can be selected");
assert(app.indexOf('data-theme-pick="studio"') >= 0, "studio theme can be selected");
var deskCss = read("www/css/theme-desk.css");
var studioCss = read("www/css/theme-studio.css");
assert(deskCss.indexOf("--card-tilt: -0.15deg") >= 0, "desk cards keep the shell tilt");
assert(deskCss.indexOf("--swipe-drag: 18") >= 0, "desk drag distance matches the shell");
assert(deskCss.indexOf("--flip-enter-x: 10%") >= 0, "desk enter slide matches the shell");
assert(studioCss.indexOf('html[data-theme="studio"]') >= 0, "studio theme is selectable");
assert(studioCss.indexOf("--swipe-drag: 34") >= 0, "studio drag is a larger gesture");
assert(studioCss.indexOf("--card-tilt: -1.15deg") >= 0, "studio cards tilt more than the desk");
assert(read("www/css/app.css").indexOf("visibility: hidden") >= 0, "idle toast cannot cover the tab bar");
assert(read("www/js/app.js").indexOf("题质量差") >= 0, "poor-item entry is on the desk");
assert(app.indexOf("检查更新") >= 0 && app.indexOf("btn-check-update") >= 0, "settings can check for an update");
assert(app.indexOf("checkForUpdate({ silent: true })") >= 0, "startup checks for an update without blocking");
assert(app.indexOf("btn-open-apk") >= 0 && app.indexOf("下载新版本") >= 0, "a newer build offers the apk link");
assert(read("www/js/config.js").indexOf("有新版本") >= 0, "update copy says a new version is available");
assert(api.indexOf("function getAbsolute") >= 0, "version manifest uses the shared HTTP helper");
assert(/versionCode\s+3/.test(read("android/app/build.gradle")), "gradle versionCode matches the shell fallback");
assert(read("android/app/build.gradle").indexOf('versionName "1.0.2"') >= 0, "gradle versionName matches the shell fallback");

vm.runInContext(read("www/js/config.js"), context, { filename: "config.js" });
var cfgApi = context.FqmConfig;
assert(cfgApi.APP_VERSION_CODE === 3 && cfgApi.APP_VERSION_NAME === "1.0.2", "browser fallback matches gradle");
assert(
  cfgApi.DEFAULT_UPDATE_URL === "https://practice.longee.icu/app/feedback-machine/version.json",
  "default manifest is the deployed version.json"
);
assert(
  cfgApi.updateManifestUrl({ practiceBaseUrl: "https://example.test", updateManifestUrl: "" }) ===
    "https://practice.longee.icu/app/feedback-machine/version.json",
  "version check does not follow a guessed path off the practice base"
);
assert(
  cfgApi.updateManifestUrl({ updateManifestUrl: "https://example.com/version.json" }) ===
    "https://example.com/version.json",
  "settings can override the version manifest URL"
);
var liveApk = "https://practice.longee.icu/app/feedback-machine/feedback-machine-debug.apk";
var newer = cfgApi.interpretUpdate(1, {
  okHttp: true,
  package: "icu.longee.feedback",
  versionCode: 2,
  versionName: "1.1",
  apkUrl: liveApk,
  apkMd5: "abc",
  releaseNotes: "修复",
  minVersionCode: 1
});
assert(newer.phase === "available" && newer.message.indexOf("有新版本") >= 0 && newer.apkUrl === liveApk, "higher versionCode offers apkUrl");
assert(newer.notes === "修复" && newer.apkMd5 === "abc", "releaseNotes and apkMd5 are kept");
assert(cfgApi.interpretUpdate(1, { okHttp: true, package: "icu.longee.feedback", versionCode: 1, versionName: "1.0", apkUrl: liveApk, minVersionCode: 1 }).phase === "current", "same versionCode is current");
assert(cfgApi.interpretUpdate(1, { okHttp: true, package: "icu.longee.feedback", versionCode: 1, apkUrl: liveApk, minVersionCode: 2 }).phase === "available", "below minVersionCode still prompts");
assert(cfgApi.interpretUpdate(1, { okHttp: true, package: "other.app", versionCode: 9, apkUrl: liveApk }).phase === "error", "other packages are ignored");
assert(cfgApi.interpretUpdate(1, { okHttp: false, versionCode: 9, apkUrl: liveApk }).phase === "error", "failed manifest does not look like an update");
assert(cfgApi.interpretUpdate(1, { okHttp: true, versionCode: 3, apkUrl: "javascript:alert(1)" }).apkUrl === "", "apk link must be http(s)");

var html = read("www/index.html");
assert(html.indexOf("vendor/katex/katex.min.js") >= 0, "KaTeX is vendored");
assert(html.indexOf("jsdelivr") === -1 && html.indexOf("cdn.") === -1, "no KaTeX CDN");
assert(html.indexOf("css/theme-desk.css") >= 0 && html.indexOf("css/theme-studio.css") >= 0, "both theme sheets are linked");
assert(html.indexOf('id="brain-frame"') >= 0, "capability page has a host frame");
assert(html.indexOf('id="source-sheet-text"') >= 0, "APK keeps the long-press source sheet");
assert(read("www/css/app.css").indexOf("repeat(4, 1fr)") >= 0, "tab bar has practice, exams, tutor, and capability");
assert(read("www/css/app.css").indexOf("../vendor/fonts/source-serif-4-400.woff2") >= 0, "shell fonts are vendored");

var ignore = read(".gitignore");
assert(ignore.indexOf("!artifacts/*.apk") === -1, "APK exception removed");
assert(ignore.indexOf("artifacts/") >= 0, "artifacts directory ignored");

console.log("feedback-machine shell loop: ok");

function manifestHttp() {
  var httpCtx = {
    Promise: Promise,
    fetch: function () { throw new Error("browser fetch should not run when CapacitorHttp exists"); }
  };
  httpCtx.window = httpCtx;
  httpCtx.globalThis = httpCtx;
  httpCtx.Capacitor = {
    isNativePlatform: function () { return true; },
    Plugins: {
      CapacitorHttp: {
        request: function (req) {
          httpCtx.last = req;
          return Promise.resolve({ status: 200, data: { versionCode: 2, versionName: "1.1", apkUrl: "https://practice.longee.icu/a.apk" } });
        }
      }
    }
  };
  vm.createContext(httpCtx);
  vm.runInContext(read("www/js/api.js"), httpCtx, { filename: "api.js" });
  return httpCtx.FqmApi.getAbsolute("https://practice.longee.icu/app/feedback-machine/version.json").then(function (body) {
    assert(httpCtx.last && httpCtx.last.url.indexOf("/app/feedback-machine/version.json") >= 0, "manifest URL is requested as-is");
    assert(!httpCtx.last.headers.Authorization && !httpCtx.last.headers["X-Practice-Token"], "version manifest is fetched without the practice token");
    assert(body && body.versionCode === 2 && body.okHttp === true, "manifest JSON comes back through CapacitorHttp");
  });
}

function runDom() {
  function El(tag) {
    this.tag = tag || "div";
    this.id = "";
    this.className = "";
    this.attrs = {};
    this.children = [];
    this._html = "";
    this._ownedIds = [];
    this.value = "";
    this.textContent = "";
    this.onclick = null;
    this.onsubmit = null;
    this.oninput = null;
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.classList = { add: function () {}, remove: function () {}, toggle: function () {}, contains: function () { return false; } };
  }
  El.prototype.focus = function () {};
  El.prototype.select = function () {};
  El.prototype.setSelectionRange = function () {};
  El.prototype.remove = function () {};
  El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
  El.prototype.setAttribute = function (k, v) { this.attrs[k] = v; if (k === "id") this.id = v; };
  El.prototype.getAttribute = function (k) { return this.attrs[k]; };
  function walk(node, out) {
    out.push(node);
    (node.children || []).forEach(function (ch) { walk(ch, out); });
  }
  El.prototype.querySelectorAll = function (sel) {
    var out = [];
    walk(this, out);
    return out.filter(function (e) {
      if (sel === "[data-tex]") return e.attrs["data-tex"] != null;
      if (sel === "[data-fill-msg]") return e.attrs["data-fill-msg"] != null;
      if (sel === "[data-copy-msg]") return e.attrs["data-copy-msg"] != null;
      if (sel === "[data-tab]") return e.attrs["data-tab"] != null;
      if (sel === ".field-error") return /field-error/.test(e.className || "");
      return false;
    });
  };
  El.prototype.querySelector = function (sel) {
    return this.querySelectorAll(sel)[0] || null;
  };

  var byId = {};
  function indexHtml(html, parent) {
    var re = /<([a-zA-Z0-9]+)([^>]*)>/g;
    var m;
    while ((m = re.exec(html))) {
      var el = new El(m[1]);
      var are = /([:@a-zA-Z0-9-]+)="([^"]*)"/g;
      var am;
      while ((am = are.exec(m[2]))) {
        el.attrs[am[1]] = am[2];
        if (am[1] === "id") el.id = am[2];
        if (am[1] === "class") el.className = am[2];
      }
      parent.children.push(el);
      if (el.id) {
        byId[el.id] = el;
        parent._ownedIds.push(el.id);
      }
    }
  }
  Object.defineProperty(El.prototype, "innerHTML", {
    get: function () { return this._html; },
    set: function (html) {
      var self = this;
      (self._ownedIds || []).forEach(function (id) { delete byId[id]; });
      self._ownedIds = [];
      self.children = [];
      self._html = String(html == null ? "" : html);
      indexHtml(self._html, self);
    }
  });

  var store = {
    fqm_settings_v1: JSON.stringify({
      practiceBaseUrl: "https://practice.longee.icu",
      practiceToken: "test-token",
      learnerId: "demo",
      deepseekApiKey: "",
      deepseekBaseUrl: ""
    })
  };
  var calls = [];
  var copied = [];
  var dom = {
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    Promise: Promise,
    localStorage: {
      getItem: function (k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
      setItem: function (k, v) { store[k] = String(v); }
    },
    document: {
      getElementById: function (id) { return byId[id] || null; },
      createElement: function (tag) { return new El(tag); },
      body: null
    },
    FqmApi: {
      bootstrap: function () {
        return Promise.resolve({
          ok: true,
          httpStatus: 200,
          okHttp: true,
          items: [{
            id: "m1",
            kind: "math",
            title: "导数",
            stem: "导数：求 $x^2$",
            subject: "高等数学",
            kp: "导数",
            answered: false
          }, {
            id: "r1",
            kind: "review",
            title: "复习题",
            stem: "复习 $a+b$",
            subject: "复习",
            kp: "回顾",
            answered: false
          }],
          slots: [],
          weakHint: ""
        });
      },
      getItem: function (_cfg, params) {
        calls.push(params || {});
        return Promise.resolve({
          ok: true,
          httpStatus: 200,
          okHttp: true,
          item: {
            id: "m2",
            kind: "math",
            title: "积分",
            stem: "求 $\\int x\\,dx$",
            subject: "高等数学",
            kp: "积分",
            answered: false
          }
        });
      },
      submit: function () {
        return Promise.resolve({
          ok: true,
          httpStatus: 200,
          okHttp: true,
          result: {
            correct: true,
            status: "graded",
            comment: "对，因为 $2x$",
            explain: "求导得到 $2x$。",
            submitted: "2x",
            gradeMode: "llm",
            masteryBefore: 0.2,
            masteryAfter: 0.41
          }
        });
      },
      tutorChat: function () {
        return Promise.resolve({ httpStatus: 200, okHttp: true, ok: true, reply: "看定义里的 $f'(x)$。" });
      }
    }
  };
  dom.window = dom;
  dom.self = dom;
  dom.globalThis = dom;
  dom.isSecureContext = true;
  dom.navigator = {
    clipboard: {
      writeText: function (text) {
        copied.push(String(text));
        return Promise.resolve();
      }
    }
  };
  dom.document.body = new El("body");
  ["header", "root", "dock", "tabbar", "toast", "source-sheet", "source-sheet-text", "source-sheet-select", "source-sheet-copy", "source-sheet-fill", "source-sheet-close"].forEach(function (id) {
    var node = new El(id === "toast" ? "div" : "div");
    node.id = id;
    byId[id] = node;
  });
  vm.createContext(dom);
  vm.runInContext(read("www/vendor/katex/katex.min.js"), dom, { filename: "katex.min.js" });
  vm.runInContext(read("www/js/math.js"), dom, { filename: "math.js" });
  vm.runInContext(read("www/js/loop.js"), dom, { filename: "loop.js" });
  vm.runInContext(read("www/js/config.js"), dom, { filename: "config.js" });
  vm.runInContext(read("www/js/app.js"), dom, { filename: "app.js" });

  function flush() {
    var p = Promise.resolve();
    var i;
    for (i = 0; i < 8; i++) p = p.then(function () {});
    return p;
  }

  return flush().then(function () {
    var today = byId.root._html;
    assert(today.indexOf("flip-sheet") >= 0, "today is painted on a flip sheet");
    assert(today.indexOf("今日练习") >= 0, "boot lands on the three-slot overview");
    assert(byId["btn-theme-desk"] && byId["btn-theme-studio"], "header can switch desk and studio");
    assert(today.indexOf("导数") >= 0 && today.indexOf("复习") >= 0, "math and review slots are both listed");
    assert(byId["btn-start"], "today has a start control");
    byId["btn-start"].onclick();
    var root = byId.root._html;
    assert(root.indexOf("katex") >= 0, "stem $...$ is painted with vendored KaTeX");
    assert(root.indexOf("不懂，问讲师") >= 0, "desk tutor entry is on the question");
    assert(root.indexOf("题质量差") >= 0, "poor-item entry is on the question");
    var ta = byId["answer-input"];
    assert(ta, "answer box exists");
    ta.value = "2x";
    ta.oninput();
    byId["btn-submit"].onclick();
    return flush();
  }).then(function () {
    assert(byId.dock._html.indexOf("下一题") >= 0, "immediate submit lands on feedback with the next control");
    assert(byId.dock._html.indexOf("提交中") === -1, "submit button is not stuck on 提交中");
    assert(byId.root._html.indexOf("通过") >= 0, "feedback banner is visible");
    assert(byId.root._html.indexOf("katex") >= 0, "feedback comment renders math");
    byId["btn-ask-tutor"].onclick();
    return flush();
  }).then(function () {
    assert(byId.root._html.indexOf("问讲师") >= 0, "tutor screen opens on the item");
    var box = byId["composer-input"];
    box.value = "为什么";
    box.oninput();
    byId["composer-form"].onsubmit({ preventDefault: function () {} });
    return flush();
  }).then(function () {
    assert(byId.root._html.indexOf("看定义") >= 0, "tutor JSON reply is shown");
    assert(byId.root._html.indexOf("复制原文") >= 0, "lecturer message offers copy original");
    var copyBtn = byId.root.querySelectorAll("[data-copy-msg]")[0];
    assert(copyBtn, "copy control is on the lecturer message");
    copyBtn.onclick();
    return flush();
  }).then(function () {
    assert(copied.indexOf("看定义里的 $f'(x)$。") >= 0, "copy writes the raw lecturer text, including math delimiters");
    assert(copied.join("\n").indexOf("katex") < 0 && copied.join("\n").indexOf("<") < 0, "copy does not write rendered markup");
    assert(byId["source-sheet-text"].value === "看定义里的 $f'(x)$。", "source sheet shows the same original text");
    byId["btn-tutor-back"].onclick();
    return flush();
  }).then(function () {
    byId["btn-next"].onclick();
    return flush();
  }).then(function () {
    assert(calls.length === 0, "next unanswered review does not refill the bank");
    assert(byId.root._html.indexOf("复习题") >= 0, "next question is the review slot");
  });
}

Promise.all([runDom(), manifestHttp()]).then(function () {
  console.log("feedback-machine shell dom: ok");
}).catch(function (err) {
  console.error(err);
  process.exit(1);
});
