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

var wired = loop.tutorReplyText({ httpStatus: 501, error: "tutor_agent_not_wired" }, "为什么");
assert(wired.indexOf("讲师暂时连不上") >= 0 && wired.indexOf("为什么") >= 0, "501 matches desk copy");
assert(loop.tutorReplyText({ httpStatus: 200, reply: "看这一步" }, "x") === "看这一步", "JSON reply is shown");

var app = read("www/js/app.js");
assert(/route === "feedback"[\s\S]{0,220}state\.busy = false[\s\S]{0,120}render\(/.test(app), "success path sets busy=false and render()");
assert(/if \(state\.screen === "feedback"\) return;/.test(app), "finally still skips an already painted feedback screen");
assert(/FqmLoop\.bankKind\(/.test(app), "empty-slot refill goes through bankKind");
assert(app.indexOf("不懂，问讲师") >= 0, "tutor entry uses the desk label");
assert(app.indexOf("/api/v1/tutor/chat") === -1, "tutor URL stays in api.js");

var api = read("www/js/api.js");
assert(api.indexOf("CapacitorHttp") >= 0 && api.indexOf("isNativePlatform") >= 0, "native transport stays CapacitorHttp");
assert(api.indexOf('"/api/v1/tutor/chat"') >= 0, "tutor uses the practice tutor route");
assert(api.indexOf("text/event-stream") >= 0, "tutor asks for the desk SSE stream");
assert(api.indexOf("/api/v1/practice/ocr") >= 0, "ocr uses the practice route");
assert(api.indexOf("/api/v1/practice/report-poor") >= 0, "poor-item uses the practice route");
assert(api.indexOf("/api/v1/exam/papers") >= 0, "exam list uses the practice route");
assert(api.indexOf("/api/v1/notes") >= 0, "notes use the practice route");
assert(read("www/css/app.css").indexOf("visibility: hidden") >= 0, "idle toast cannot cover the tab bar");
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
assert(read("www/js/app.js").indexOf("题质量差") >= 0, "poor-item entry is on the desk");
assert(read("www/js/app.js").indexOf("brain/index.html") >= 0, "capability page is the vendored brain");

var html = read("www/index.html");
assert(html.indexOf("vendor/katex/katex.min.js") >= 0, "KaTeX is vendored");
assert(html.indexOf("jsdelivr") === -1 && html.indexOf("cdn.") === -1, "no KaTeX CDN");

var ignore = read(".gitignore");
assert(ignore.indexOf("!artifacts/*.apk") === -1, "APK exception removed");
assert(ignore.indexOf("artifacts/") >= 0, "artifacts directory ignored");

console.log("feedback-machine shell loop: ok");

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
  El.prototype.remove = function () {};
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
  dom.document.body = new El("body");
  ["header", "root", "dock", "tabbar", "toast"].forEach(function (id) {
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

runDom().then(function () {
  console.log("feedback-machine shell dom: ok");
}).catch(function (err) {
  console.error(err);
  process.exit(1);
});
