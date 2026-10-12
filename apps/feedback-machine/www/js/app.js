(function () {
  "use strict";

  var TUTOR_KEY = "fqm_tutor_v1";
  var THEME_KEY = "fqm_theme_v1";
  var cfg = FqmConfig.load();
  var savedTutor = {};
  var themeSaved = "desk";
  try {
    savedTutor = JSON.parse(localStorage.getItem(TUTOR_KEY) || "{}") || {};
  } catch (e) {
    savedTutor = {};
  }
  try {
    var storedTheme = localStorage.getItem(THEME_KEY);
    if (storedTheme === "studio" || storedTheme === "desk") themeSaved = storedTheme;
  } catch (eTheme) {
    themeSaved = "desk";
  }

  var state = {
    screen: "loading",
    returnScreen: "today",
    error: "",
    busy: false,
    polling: false,
    bootstrap: null,
    items: [],
    slots: [],
    current: null,
    draft: "",
    lastResult: null,
    lastKind: "math",
    explainOpen: false,
    threads: savedTutor.threads || {},
    recents: savedTutor.recents || [],
    tutorThreadId: null,
    tutorDraft: "",
    ocrBusy: false,
    ocrMsg: "",
    ocrMode: "document",
    theme: themeSaved
  };
  var ocrPayload = null;
  var streamTimer = null;
  var SWIPE_THRESHOLD = 56;
  var SCREEN_ORDER = { today: 0, practice: 1, feedback: 2, done: 3 };
  var flipOverride = null;
  var flipGen = 0;
  var flipBusy = false;
  var lastPaintScreen = "";
  var swipeBound = false;

  var el = {
    header: document.getElementById("header"),
    root: document.getElementById("root"),
    dock: document.getElementById("dock"),
    tabs: document.getElementById("tabbar"),
    toast: document.getElementById("toast"),
    chrome: document.getElementById("page-chrome"),
    strip: document.getElementById("tutor-strip"),
    brain: document.getElementById("brain-host")
  };

  function esc(s) {
    return FqmMath.esc(s);
  }

  function paintTheme() {
    var theme = state.theme === "studio" ? "studio" : "desk";
    var rootEl = document.documentElement;
    if (rootEl && rootEl.setAttribute) rootEl.setAttribute("data-theme", theme);
    if (document.body && document.body.setAttribute) document.body.setAttribute("data-theme", theme);
    var meta = document.getElementById("theme-color");
    if (meta && meta.setAttribute) meta.setAttribute("content", theme === "studio" ? "#D5E2EA" : "#F4EDE0");
  }

  function applyTheme(name) {
    state.theme = name === "studio" ? "studio" : "desk";
    try {
      localStorage.setItem(THEME_KEY, state.theme);
    } catch (e) {}
    paintTheme();
  }

  function motionVars() {
    var fallback = { drag: 18, scale: 0.015, fade: 0.18, tilt: 0 };
    var rootEl = document.documentElement;
    if (!rootEl || !window.getComputedStyle) return fallback;
    var cs = window.getComputedStyle(rootEl);
    function num(name, fb) {
      var v = parseFloat(cs.getPropertyValue(name));
      return isNaN(v) ? fb : v;
    }
    return {
      drag: num("--swipe-drag", fallback.drag),
      scale: num("--swipe-scale", fallback.scale),
      fade: num("--swipe-fade", fallback.fade),
      tilt: num("--swipe-tilt", fallback.tilt)
    };
  }

  function canSwipe() {
    return (
      state.screen === "today" ||
      state.screen === "practice" ||
      state.screen === "feedback" ||
      state.screen === "done" ||
      state.screen === "settings"
    );
  }

  function inferDir(prev, next) {
    if (SCREEN_ORDER[prev] != null && SCREEN_ORDER[next] != null && prev !== next) {
      return SCREEN_ORDER[next] > SCREEN_ORDER[prev] ? -1 : 1;
    }
    if (next === "settings") return -1;
    if (prev === "settings") return 1;
    if (next === "tutor" || next === "exam" || next === "notes" || next === "brain") return -1;
    if (prev === "tutor" || prev === "exam" || prev === "notes" || prev === "brain") return 1;
    return 0;
  }

  function playFlip(sheet, gen) {
    if (!sheet || !sheet.classList) return;
    flipBusy = true;
    var raf = window.requestAnimationFrame || function (fn) { setTimeout(fn, 16); };
    raf(function () {
      raf(function () {
        if (gen !== flipGen) return;
        sheet.classList.remove("is-enter-right", "is-enter-left");
        sheet.classList.add("is-open");
        setTimeout(function () {
          if (gen === flipGen) flipBusy = false;
        }, 260);
      });
    });
  }

  function leaveSettings() {
    flipOverride = 1;
    var back = state.returnScreen;
    if (back === "feedback" && state.lastResult) state.screen = "feedback";
    else if (back === "practice" && state.current) state.screen = "practice";
    else if (back === "tutor" || back === "exam" || back === "notes" || back === "done" || back === "today") state.screen = back;
    else state.screen = "today";
    render();
  }

  function nextDisabled() {
    if (state.screen === "today") return false;
    if (state.screen === "practice") return !(state.lastResult && state.current);
    if (state.screen === "feedback") return false;
    return true;
  }

  function flipBack() {
    if (flipBusy) return;
    if (state.screen === "settings") {
      leaveSettings();
      return;
    }
    if (state.screen === "feedback" && state.current) {
      flipOverride = 1;
      state.screen = "practice";
      render();
      return;
    }
    if (state.screen === "done") {
      flipOverride = 1;
      state.screen = state.lastResult && state.current ? "feedback" : "today";
      render();
      return;
    }
    if (state.screen === "practice") {
      flipOverride = 1;
      state.screen = "today";
      render();
    }
  }

  function flipForward() {
    if (flipBusy) return;
    if (state.screen === "settings") return;
    if (state.screen === "today") {
      startToday();
      return;
    }
    if (state.screen === "practice") {
      if (state.lastResult && state.current) {
        flipOverride = -1;
        state.screen = "feedback";
        render();
      }
      return;
    }
    if (state.screen === "feedback") goNextQuestion();
  }

  function goToPageDot(page) {
    if (page === state.screen) return;
    if (page === "today") {
      flipOverride = 1;
      state.screen = "today";
      render();
      return;
    }
    if (page === "practice") {
      if (state.current && (state.screen === "feedback" || state.screen === "done")) {
        flipOverride = 1;
        state.screen = "practice";
        render();
        return;
      }
      if (state.current && state.screen !== "today") {
        state.screen = "practice";
        render();
        return;
      }
      startToday();
      return;
    }
    if (page === "feedback") {
      if (state.lastResult && state.current) {
        flipOverride = state.screen === "done" ? 1 : -1;
        state.screen = "feedback";
        render();
      } else if (state.screen === "today") startToday();
      return;
    }
    if (page === "done") {
      if (countOpen() === 0) {
        flipOverride = -1;
        state.screen = "done";
        render();
      } else {
        flipOverride = 1;
        state.screen = "today";
        render();
      }
    }
  }

  function themeSwitchHtml(withIds) {
    var studio = state.theme === "studio";
    var idDesk = withIds ? ' id="btn-theme-desk"' : "";
    var idStudio = withIds ? ' id="btn-theme-studio"' : "";
    return (
      '<div class="theme-switch" role="group" aria-label="视觉方案">' +
      '<button type="button" class="theme-opt' +
      (studio ? "" : " is-on") +
      '"' +
      idDesk +
      ' data-theme-pick="desk" aria-pressed="' +
      (studio ? "false" : "true") +
      '" aria-label="练习台画法">练习台</button>' +
      '<button type="button" class="theme-opt' +
      (studio ? " is-on" : "") +
      '"' +
      idStudio +
      ' data-theme-pick="studio" aria-pressed="' +
      (studio ? "true" : "false") +
      '" aria-label="工作室画法">工作室</button></div>'
    );
  }

  function markBox(inner) {
    return (
      '<div class="mark-box"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">' +
      inner +
      "</svg></div>"
    );
  }

  function showToast(msg) {
    if (!el.toast) return;
    el.toast.textContent = msg;
    el.toast.classList.add("is-on");
    setTimeout(function () {
      el.toast.classList.remove("is-on");
      el.toast.textContent = "";
    }, 2800);
  }

  function persistTutor() {
    try {
      localStorage.setItem(
        TUTOR_KEY,
        JSON.stringify({ threads: state.threads, recents: state.recents })
      );
    } catch (e) {}
  }

  function threadOf(id) {
    var key = id || "general";
    if (!state.threads[key]) state.threads[key] = [];
    return state.threads[key];
  }

  function itemById(id) {
    var i;
    for (i = 0; i < state.items.length; i++) {
      if (state.items[i] && state.items[i].id === id) return state.items[i];
    }
    return null;
  }

  function viewSlots() {
    var labels = { math: "高等数学", comm: "通信", review: "复习" };
    var windows = { math: "08:00–12:00", comm: "12:00–18:00", review: "18:00–22:00" };
    var byKind = {};
    (state.slots || []).forEach(function (s) {
      if (s && s.kind) byKind[s.kind] = s;
    });
    return ["math", "comm", "review"].map(function (k) {
      var s = byKind[k] || {
        kind: k,
        label: labels[k],
        window: windows[k],
        windowKey: "",
        itemId: ""
      };
      if (!s.itemId) {
        var i;
        for (i = 0; i < state.items.length; i++) {
          if (state.items[i] && state.items[i].kind === k) {
            s = Object.assign({}, s, { itemId: state.items[i].id });
            break;
          }
        }
      }
      if (!s.label) s.label = labels[k] || k;
      if (!s.window) s.window = windows[k] || "";
      return s;
    });
  }

  function todayLabel() {
    var d = new Date();
    var mm = String(d.getMonth() + 1);
    var dd = String(d.getDate());
    if (mm.length < 2) mm = "0" + mm;
    if (dd.length < 2) dd = "0" + dd;
    return mm + "-" + dd + " · 周" + ["日", "一", "二", "三", "四", "五", "六"][d.getDay()];
  }

  function countOpen() {
    var n = 0;
    var i;
    for (i = 0; i < state.items.length; i++) if (state.items[i] && !state.items[i].answered) n++;
    return n;
  }

  function mergeItemsFromBootstrap(data) {
    state.bootstrap = data;
    state.items = (data && data.items) || [];
    state.slots = (data && data.slots) || [];
    var answered = (data && data.answered) || {};
    Object.keys(answered).forEach(function (id) {
      var it = itemById(id);
      if (it) it.answered = true;
    });
  }

  function setCurrent(item) {
    state.current = item;
    state.lastKind = FqmLoop.rememberKind(state.lastKind, item && item.kind);
    state.draft = "";
    state.lastResult = null;
    state.explainOpen = false;
    ocrPayload = null;
    state.ocrMsg = "";
    if (item && item.id) state.tutorThreadId = item.id;
  }

  function applyItemResponse(data) {
    if (FqmLoop.isUnauthorized(data)) {
      state.error = FqmLoop.TOKEN_INVALID_MESSAGE;
      state.screen = "settings";
      return false;
    }
    if (!data || !data.ok || !data.item) {
      state.error = FqmLoop.failureMessage(data, "无法加载题目");
      return false;
    }
    var it = data.item;
    var ix = -1;
    var i;
    for (i = 0; i < state.items.length; i++) if (state.items[i] && state.items[i].id === it.id) ix = i;
    if (ix < 0) state.items.push(it);
    else state.items[ix] = it;
    if (it.kind) {
      var slots = viewSlots();
      state.slots = slots.map(function (s) {
        if (s.kind === it.kind) return Object.assign({}, s, { itemId: it.id });
        return s;
      });
    }
    setCurrent(it);
    if (data.result) state.lastResult = data.result;
    state.error = "";
    return true;
  }

  function loadBootstrapThenPick() {
    state.busy = true;
    state.error = "";
    state.screen = "loading";
    render();
    return FqmApi.bootstrap(cfg)
      .then(function (data) {
        if (FqmLoop.isUnauthorized(data)) {
          state.error = FqmLoop.TOKEN_INVALID_MESSAGE;
          state.screen = "settings";
          return;
        }
        if (!data || !data.ok) {
          state.error = FqmLoop.failureMessage(data, "练习台暂时连不上，请稍后重试。");
          state.screen = "today";
          return;
        }
        mergeItemsFromBootstrap(data);
        state.screen = "today";
      })
      .catch(function (e) {
        state.error = "网络错误：" + (e && e.message ? e.message : "unknown");
        state.screen = "today";
      })
      .finally(function () {
        state.busy = false;
        render();
      });
  }

  function fetchBankItem(kind) {
    var useKind = FqmLoop.bankKind(kind);
    if (!useKind) {
      state.error = "通信空槽不从题库补货。已推送的通信题会留在这个槽里。";
      state.screen = "today";
      render();
      return Promise.resolve();
    }
    state.busy = true;
    state.screen = "practice";
    render();
    return FqmApi.getItem(cfg, { kind: useKind })
      .then(function (data) {
        if (!applyItemResponse(data)) {
          if (state.screen !== "settings") state.screen = "today";
          return;
        }
        state.screen = "practice";
      })
      .catch(function (e) {
        state.error = "网络错误：" + (e && e.message ? e.message : "unknown");
        state.screen = "today";
      })
      .finally(function () {
        state.busy = false;
        render();
      });
  }

  function openSettings() {
    if (state.screen !== "settings") state.returnScreen = state.screen;
    state.screen = "settings";
    render();
  }

  function saveSettings(form) {
    cfg = FqmConfig.save({
      deepseekApiKey: form.deepseekKey.value.trim(),
      deepseekBaseUrl: form.deepseekBase.value.trim(),
      practiceBaseUrl: form.practiceBase.value.trim() || FqmConfig.DEFAULTS.practiceBaseUrl,
      practiceToken: form.practiceToken.value.trim(),
      learnerId: form.learnerId.value.trim() || FqmConfig.DEFAULTS.learnerId
    });
    showToast("已保存到本机");
    if (FqmConfig.isConfigured(cfg)) loadBootstrapThenPick();
    else {
      state.screen = "settings";
      state.error = "请填写练习台地址、Practice API Token 与学员编号";
      render();
    }
  }

  function submitAnswer() {
    var it = state.current;
    if (!it || state.busy) return;
    var ans = (state.draft || "").trim();
    if (!ans) {
      state.error = "请先填写作答内容再提交。";
      render();
      var focus = document.getElementById("answer-input");
      if (focus) focus.focus();
      return;
    }
    state.busy = true;
    state.error = "";
    render();
    var payload = {
      learner: cfg.learnerId,
      item: it.id,
      push: it.pushId != null ? String(it.pushId) : null,
      answer: ans
    };
    FqmApi.submit(cfg, payload)
      .then(function (data) {
        var route = FqmLoop.routeSubmit(state, data, it);
        if (route === "feedback") {
          // Immediate grade must paint feedback here. finally skips this
          // screen, which used to leave the button stuck on「提交中」.
          state.busy = false;
          state.screen = "feedback";
          render();
          return;
        }
        if (route === "poll") return pollGrade(it);
        state.busy = false;
        render();
      })
      .catch(function () {
        return pollGrade(it);
      })
      .finally(function () {
        if (state.screen === "feedback") return;
        if (state.polling) return;
        state.busy = false;
        render();
      });
  }

  function pollGrade(it) {
    state.polling = true;
    var started = Date.now();
    var deadline = 8 * 60 * 1000;
    return new Promise(function (resolve) {
      function finish() {
        state.polling = false;
        resolve();
      }
      function tick() {
        if (Date.now() - started > deadline) {
          state.busy = false;
          state.error = "批改仍在进行，请勿重复提交。稍后从练习台查看结果。";
          render();
          finish();
          return;
        }
        FqmApi.getItem(cfg, { item: it.id, push: it.pushId })
          .then(function (data) {
            if (FqmLoop.isUnauthorized(data)) {
              state.busy = false;
              state.error = FqmLoop.TOKEN_INVALID_MESSAGE;
              state.screen = "settings";
              render();
              finish();
              return;
            }
            if (FqmLoop.resultReady(data) && !FqmLoop.gradeStillRunning(data)) {
              FqmLoop.applyImmediateSubmit(state, data, it);
              state.busy = false;
              state.screen = "feedback";
              render();
              finish();
              return;
            }
            setTimeout(tick, 2000);
          })
          .catch(function () {
            setTimeout(tick, 2000);
          });
      }
      setTimeout(tick, 2000);
    });
  }

  function startToday() {
    flipOverride = -1;
    var next = FqmLoop.pickNextLocal(state.items, null);
    if (!next) {
      state.screen = "done";
      render();
      return;
    }
    setCurrent(next);
    state.screen = "practice";
    render();
  }

  function goNextQuestion() {
    flipOverride = -1;
    if (state.current) state.current.answered = true;
    var local = FqmLoop.pickNextLocal(state.items, state.current && state.current.id);
    if (local) {
      setCurrent(local);
      state.screen = "practice";
      render();
      return;
    }
    state.screen = "done";
    render();
  }

  function openSlot(kind, itemId) {
    var it = itemById(itemId);
    if (it) {
      setCurrent(it);
      state.screen = "practice";
      render();
      return;
    }
    fetchBankItem(kind);
  }

  function bumpRecent(it) {
    if (!it || !it.id) return;
    state.recents = (state.recents || []).filter(function (r) { return r.id !== it.id; });
    state.recents.unshift({
      id: it.id,
      title: (it.subject ? it.subject + " · " : "") + (it.title || it.id)
    });
    persistTutor();
  }

  function askTutor() {
    if (state.screen === "practice" || state.screen === "feedback" || state.screen === "today") {
      state.returnScreen = state.screen;
    }
    if (state.current && state.current.id) {
      state.tutorThreadId = state.current.id;
      bumpRecent(state.current);
    } else if (!state.tutorThreadId) {
      state.tutorThreadId = "general-" + Date.now();
    }
    state.screen = "tutor";
    render();
    var box = document.getElementById("composer-input");
    if (box) box.focus();
  }

  function startBlankTutor() {
    if (streamTimer) clearInterval(streamTimer);
    state.tutorThreadId = "general-" + Date.now();
    state.threads[state.tutorThreadId] = [];
    state.recents.unshift({ id: state.tutorThreadId, title: "新对话" });
    state.tutorDraft = "";
    state.screen = "tutor";
    persistTutor();
    render();
  }

  function selectThread(id) {
    state.tutorThreadId = id;
    if (!FqmLoop.isGeneralThread(id)) {
      var it = itemById(id);
      if (it) state.current = it;
    }
    state.screen = "tutor";
    render();
  }

  function backFromTutor() {
    if (state.returnScreen === "feedback" && state.lastResult) state.screen = "feedback";
    else if (state.returnScreen === "practice" && state.current) state.screen = "practice";
    else state.screen = "today";
    render();
  }

  function sendDraftToTutor() {
    var draft = String(state.draft || "").trim();
    if (!draft) {
      state.error = "请先填写原文，再发给老师讨论。";
      render();
      return;
    }
    if (state.busy) return;
    askTutor();
    var clipped = draft.length > 3500 ? draft.slice(0, 3500) + "\n…（已截断，完整稿仍在作答框）" : draft;
    sendChat(
      "我把手写识别/整理成了下面这份草稿（尚未正式交卷）。请帮我核对识别是否准确、推导有没有明显问题；讨论清楚后我再回练习台点提交。\n\n【草稿】\n" +
        clipped
    );
  }

  function applyEv(msg, ev) {
    var d = (ev && ev.data) || {};
    if (d.text) msg.text += d.text;
    if (d.reply && (ev.event === "done" || !d.text)) msg.text = d.reply;
    if (d.citations) msg.citations = d.citations;
    if (ev && ev.event === "error") msg.text += (msg.text ? "\n" : "") + (d.message || "讲师出错");
  }

  function patchLast(msg) {
    var node = el.root.querySelector("[data-last-msg] .msg-body");
    if (!node) {
      render();
      return;
    }
    node.innerHTML =
      FqmMath.renderMathMarkdown(msg.text) + (msg.streaming ? '<span class="stream-cursor"></span>' : "");
    el.root.scrollTop = el.root.scrollHeight;
  }

  function replayEvents(msgs, events) {
    var msg = { role: "tutor", text: "", streaming: true, citations: [] };
    msgs.push(msg);
    state.busy = false;
    render();
    var i = 0;
    if (streamTimer) clearInterval(streamTimer);
    streamTimer = setInterval(function () {
      if (state.screen !== "tutor") {
        clearInterval(streamTimer);
        return;
      }
      if (i >= events.length) {
        msg.streaming = false;
        clearInterval(streamTimer);
        persistTutor();
        patchLast(msg);
        return;
      }
      applyEv(msg, events[i]);
      i += 1;
      patchLast(msg);
    }, 32);
  }

  function sendChat(text) {
    var trimmed = String(text || state.tutorDraft || "").trim();
    if (!trimmed || state.busy) return;
    var tid = state.tutorThreadId;
    if (!tid) {
      tid = state.current && state.current.id ? state.current.id : "general-" + Date.now();
      state.tutorThreadId = tid;
    }
    var msgs = threadOf(tid);
    msgs.push({ role: "user", text: trimmed });
    state.tutorDraft = "";
    state.busy = true;
    state.screen = "tutor";
    render();
    var it = state.current;
    var blank = FqmLoop.isGeneralThread(tid) || !it;
    var live = null;
    FqmApi.tutorChat(
      cfg,
      {
        learner: cfg.learnerId,
        item: blank ? null : it.id,
        push: blank ? null : it.pushId != null ? String(it.pushId) : null,
        message: trimmed,
        threadId: tid,
        blank: !!blank
      },
      function (ev) {
        if (!live) {
          live = { role: "tutor", text: "", streaming: true, citations: [] };
          msgs.push(live);
          state.busy = false;
          render();
        }
        applyEv(live, ev);
        patchLast(live);
      }
    )
      .then(function (data) {
        if (FqmLoop.isUnauthorized(data)) {
          state.error = FqmLoop.TOKEN_INVALID_MESSAGE;
          state.screen = "settings";
          return;
        }
        if (data && data.streamed) {
          if (live) live.streaming = false;
          persistTutor();
          return;
        }
        var events = data && data.events;
        if (!events && data && data.sseText) events = FqmLoop.parseSse(data.sseText);
        if (events && events.length) {
          replayEvents(msgs, events);
          return;
        }
        msgs.push({
          role: "tutor",
          text: FqmLoop.tutorReplyText(data, trimmed),
          citations: (data && data.citations) || []
        });
        persistTutor();
      })
      .catch(function () {
        msgs.push({ role: "tutor", text: "讲师服务暂时不可用。", citations: [] });
      })
      .finally(function () {
        if (streamTimer) return;
        state.busy = false;
        render();
      });
  }

  function fillFromTutor(text) {
    var raw = String(text || "").trim();
    if (!raw) return;
    state.draft = raw;
    state.error = "";
    state.screen = "practice";
    state.returnScreen = "practice";
    render();
  }

  function reportPoor() {
    var it = state.current;
    if (!it || state.busy) return;
    if (window.confirm && !window.confirm("确认本题质量差？将隔离该题并尽量换同槽新题。")) return;
    state.busy = true;
    state.error = "";
    render();
    FqmApi.reportPoor(cfg, {
      learner: cfg.learnerId,
      item: it.id,
      push: it.pushId != null ? String(it.pushId) : null,
      reason: "user_report_poor"
    })
      .then(function (data) {
        state.busy = false;
        if (FqmLoop.isUnauthorized(data)) {
          state.error = FqmLoop.TOKEN_INVALID_MESSAGE;
          state.screen = "settings";
          render();
          return;
        }
        if (!data || !data.ok) {
          state.error = FqmLoop.failureMessage(data, "标记失败");
          render();
          return;
        }
        it.answered = true;
        if (data.replaced && data.item) {
          applyItemResponse(data);
          state.screen = "practice";
          state.ocrMsg = "已换题（原题已标 poor）";
          render();
          return;
        }
        state.error = "已标记 poor。";
        goNextQuestion();
      })
      .catch(function () {
        state.busy = false;
        state.error = "标记请求失败，请稍后重试。";
        render();
      });
  }

  function fileToOcrPayload(file, done) {
    if (!file) {
      done(new Error("empty"));
      return;
    }
    var reader = new FileReader();
    reader.onload = function () {
      done(null, {
        dataUrl: String(reader.result || ""),
        filename: file.name || "answer.jpg",
        name: file.name || "handwriting.jpg"
      });
    };
    reader.onerror = function () { done(new Error("read")); };
    reader.readAsDataURL(file);
  }

  function runOcr() {
    if (!ocrPayload || !ocrPayload.dataUrl || state.ocrBusy) return;
    state.ocrBusy = true;
    state.ocrMsg = state.ocrMode === "formula" ? "正在识别公式…" : "正在整页识别…";
    state.error = "";
    render();
    FqmApi.ocr(cfg, {
      learner: cfg.learnerId,
      image: ocrPayload.dataUrl,
      filename: ocrPayload.filename || "answer.jpg",
      mode: state.ocrMode === "formula" ? "formula" : "document"
    })
      .then(function (data) {
        state.ocrBusy = false;
        if (FqmLoop.isUnauthorized(data)) {
          state.error = FqmLoop.TOKEN_INVALID_MESSAGE;
          state.screen = "settings";
          render();
          return;
        }
        if (!data || !data.ok || !String(data.text || "").trim()) {
          state.error = FqmLoop.failureMessage(data, "未识别出文字，请换一张更清晰的图。");
          state.ocrMsg = state.error;
          render();
          return;
        }
        state.draft = String(data.text).trim();
        state.error = "";
        state.ocrMsg = "识别完成。可先发给老师讨论，确认后再提交。";
        render();
      })
      .catch(function () {
        state.ocrBusy = false;
        state.error = "网络错误，识别未完成。";
        render();
      });
  }

  function absPractice(path) {
    var base = String(cfg.practiceBaseUrl || "").replace(/\/+$/, "");
    if (!path) return base;
    if (/^https?:/i.test(path)) return path;
    return base + (path.charAt(0) === "/" ? path : "/" + path);
  }

  function loadExam() {
    var list = document.getElementById("exam-list");
    if (!list) return;
    FqmApi.examPapers(cfg)
      .then(function (d) {
        if (!list) return;
        if (FqmLoop.isUnauthorized(d)) {
          state.error = FqmLoop.TOKEN_INVALID_MESSAGE;
          state.screen = "settings";
          render();
          return;
        }
        var papers = (d && d.papers) || [];
        if (!papers.length) {
          list.innerHTML = '<p class="hint">这期还没有可打开的周卷。</p>';
          return;
        }
        list.innerHTML = papers
          .map(function (p, i) {
            var subj = p.subject === "math" ? "数学" : p.subject === "comm" ? "通信" : p.subject || "试卷";
            return (
              '<button type="button" class="btn' +
              (i === 0 ? " primary" : "") +
              '" data-exam-url="' +
              esc(p.url) +
              '">' +
              esc(subj + " · " + (p.title || p.id || "周卷")) +
              "</button>"
            );
          })
          .join("");
        list.querySelectorAll("[data-exam-url]").forEach(function (btn) {
          btn.onclick = function () {
            openExam(btn.getAttribute("data-exam-url"));
          };
        });
        openExam(papers[0].url);
      })
      .catch(function () {
        if (list) list.innerHTML = '<p class="hint">周卷暂时打不开。</p>';
      });
  }

  function openExam(url) {
    var frame = document.getElementById("exam-frame");
    if (!frame || !url) return;
    var abs = absPractice(url);
    if (frame.getAttribute("src") !== abs) frame.src = abs;
  }

  function loadNotes() {
    var list = document.getElementById("notes-list");
    if (!list) return;
    FqmApi.notes(cfg)
      .then(function (d) {
        if (FqmLoop.isUnauthorized(d)) {
          state.error = FqmLoop.TOKEN_INVALID_MESSAGE;
          state.screen = "settings";
          render();
          return;
        }
        var notes = (d && d.notes) || [];
        if (!notes.length) {
          list.innerHTML = '<p class="hint">还没有手写笔记。点上方放入图片即可。</p>';
          return;
        }
        list.innerHTML = notes
          .map(function (n) {
            return (
              '<button type="button" class="note-row" data-note-id="' +
              esc(n.id) +
              '">' +
              esc(n.name || "手写笔记") +
              "</button>"
            );
          })
          .join("");
        list.querySelectorAll("[data-note-id]").forEach(function (btn) {
          btn.onclick = function () {
            showNote(btn.getAttribute("data-note-id"), btn.textContent);
          };
        });
        showNote(notes[0].id, notes[0].name);
      })
      .catch(function () {
        list.innerHTML = '<p class="hint">资料库暂时打不开。</p>';
      });
  }

  function showNote(id, name) {
    var view = document.getElementById("notes-view");
    if (!view) return;
    view.innerHTML = '<p class="hint">正在打开这张笔记…</p>';
    FqmApi.noteItem(cfg, id)
      .then(function (d) {
        if (!view) return;
        if (!d || !d.data_url) {
          view.innerHTML = '<p class="hint">这张笔记打不开。</p>';
          return;
        }
        view.innerHTML =
          '<img alt="' + esc(name || "手写笔记") + '" src="' + esc(d.data_url) + '"><p class="hint">' + esc(name || "手写笔记") + "</p>";
      })
      .catch(function () {
        if (view) view.innerHTML = '<p class="hint">这张笔记打不开。</p>';
      });
  }

  function openBrain() {
    state.screen = "brain";
    render();
    var frame = document.getElementById("brain-frame");
    if (!frame) return;
    var src = "brain/index.html?embed=1&tab=events&learner=" + encodeURIComponent(cfg.learnerId || "");
    if (frame.getAttribute("src") !== src) frame.src = src;
  }

  function mountMath() {
    if (!el.root || !window.katex) return;
    el.root.querySelectorAll("[data-tex]").forEach(function (node) {
      var tex = node.getAttribute("data-tex") || "";
      if (!tex) return;
      try {
        window.katex.render(tex, node, { throwOnError: false, displayMode: true, strict: "ignore", trust: false });
      } catch (e) {
        node.innerHTML = '<div class="math-fallback">' + esc(tex) + "</div>";
      }
    });
  }

  function paintDraftPreview() {
    var node = document.getElementById("answer-preview");
    if (!node) return;
    var src = String(state.draft || "");
    var trimmed = src.trim();
    node.classList.toggle("is-empty", !trimmed);
    if (!trimmed) {
      node.innerHTML = "预览将显示在这里。含 $…$ 的公式按练习台同样的规则排版。提交仍用上方原文。";
      return;
    }
    if (FqmMath.hasMathDelimiters(src)) {
      node.innerHTML = FqmMath.renderMathMarkdown(src);
      return;
    }
    if (window.katex) {
      try {
        window.katex.render(trimmed, node, { throwOnError: false, displayMode: true, strict: "ignore", trust: false });
        return;
      } catch (e1) {}
    }
    node.innerHTML = '<div class="math-fallback">' + esc(trimmed) + "</div>";
  }

  var GRADE_MODE_LABEL = {
    llm: "LLM 批改",
    ref: "参考答案比对",
    ref_fallback: "LLM 暂不可用 · 参考答案初判"
  };

  function renderHeader() {
    var themes = themeSwitchHtml(true);
    var gear = '<button type="button" class="icon-btn" id="btn-gear" aria-label="设置">⚙</button>';
    if (state.screen === "settings") {
      return (
        '<div class="brand-row"><button type="button" class="text-link" id="btn-settings-back">返回</button>' +
        '<span class="brand">设置</span>' +
        themes +
        "</div>"
      );
    }
    if (state.screen === "tutor") {
      var it = state.current;
      var general = FqmLoop.isGeneralThread(state.tutorThreadId);
      var title = general
        ? "新对话"
        : (it && it.subject ? it.subject + " · " : "") + ((it && (it.title || it.id)) || "讲题");
      return (
        '<div class="tutor-head"><span class="tutor-badge">讲题</span><span class="tutor-title">' +
        esc(title) +
        "</span></div>" +
        '<div class="tutor-ops">' +
        '<button type="button" class="text-link" id="btn-new-tutor">新建对话</button>' +
        '<button type="button" class="text-link" id="btn-tutor-back">返回练习</button>' +
        themes +
        gear +
        "</div>" +
        '<div class="sub">' +
        esc(general ? "可问学情或计划。要讲某一题，从练习台点「不懂，问讲师」。" : (it && it.kp) || "就这道题问卡住的步骤。") +
        "</div>"
      );
    }
    var map = {
      loading: "连接练习台",
      today: "今日练习",
      practice: "作答",
      feedback: "批改结果",
      done: "今日已完成",
      settings: "设置",
      exam: "周卷",
      notes: "资料库",
      brain: "能力"
    };
    var practiceChrome =
      state.screen === "today" || state.screen === "practice" || state.screen === "feedback" || state.screen === "done";
    return (
      '<div class="brand-row"><span class="brand">反馈出题机</span><div class="meta">' +
      esc(cfg.learnerId || "未指定学员") +
      "</div>" +
      themes +
      gear +
      "</div>" +
      '<div class="sub">' +
      esc(map[state.screen] || "练习台") +
      "</div>" +
      (practiceChrome ? '<div class="flip-hint">左右滑动，或用两侧箭头翻页</div>' : "")
    );
  }

  function renderChrome() {
    var order = ["today", "practice", "feedback", "done"];
    var labels = { today: "今日", practice: "主台", feedback: "批改", done: "完成" };
    var dots = order
      .map(function (p) {
        var on = state.screen === p;
        return (
          '<button type="button" class="page-dot' +
          (on ? " is-on" : "") +
          '" data-page="' +
          p +
          '" role="tab" aria-selected="' +
          (on ? "true" : "false") +
          '" aria-label="' +
          labels[p] +
          '"></button>'
        );
      })
      .join("");
    var prevOff = state.screen === "today" ? " disabled" : "";
    var nextOff = nextDisabled() ? " disabled" : "";
    return (
      '<button type="button" class="page-nav" id="page-prev" aria-label="上一页"' +
      prevOff +
      ">‹</button>" +
      '<div class="page-dots" role="tablist" aria-label="页码">' +
      dots +
      "</div>" +
      '<button type="button" class="page-nav" id="page-next" aria-label="下一页"' +
      nextOff +
      ">›</button>" +
      '<span class="page-index">' +
      esc(labels[state.screen] || "") +
      "</span>"
    );
  }

  function renderStrip() {
    var sessions = FqmLoop.listTutorSessions(state.recents, state.threads, state.items);
    var html =
      '<button type="button" class="tutor-chip is-new" id="btn-new-tutor-strip"><span class="tc-title">新建对话</span><span class="tc-sub">空白</span></button>';
    sessions.forEach(function (s) {
      html +=
        '<button type="button" class="tutor-chip' +
        (s.id === state.tutorThreadId ? " is-active" : "") +
        '" data-thread-id="' +
        esc(s.id) +
        '"><span class="tc-title">' +
        esc(s.title) +
        '</span><span class="tc-sub">' +
        (s.general ? "不绑题" : "讲题") +
        "</span></button>";
    });
    return html;
  }

  function field(label, help, inputHtml) {
    return '<label><span class="field-name">' + label + '</span><span class="field-help">' + help + "</span>" + inputHtml + "</label>";
  }

  function renderSettings() {
    return (
      '<section class="card stack"><h1>设置</h1>' +
      '<p class="lede">密钥只保存在本机，不会写进安装包。批改和出题都走练习台，不走本机 DeepSeek。</p>' +
      '<div class="stack"><span class="field-name">视觉方案</span>' +
      themeSwitchHtml(false) +
      '<p class="field-help">「练习台」对齐现网纸色、卡片微倾和滑动翻页。「工作室」是同一条作答路径上更大胆的对照画法。选择记在本机，页头也能切。</p></div>' +
      (state.error ? '<p class="field-error" role="alert">' + esc(state.error) + "</p>" : "") +
      '<form id="settings-form" class="form stack">' +
      field(
        'DeepSeek API Key <span class="pill warn">当前未使用</span>',
        "批改仍由练习台服务器完成。这里填写不会参与出题或打分，可以留空。",
        '<input name="deepseekKey" type="password" autocomplete="off" placeholder="留空即可" value="' + esc(cfg.deepseekApiKey) + '"/>'
      ) +
      field(
        'DeepSeek Base URL <span class="pill warn">当前未使用</span>',
        "预留字段。当前版本不会用它去请求模型。",
        '<input name="deepseekBase" type="url" placeholder="https://api.deepseek.com" value="' + esc(cfg.deepseekBaseUrl) + '"/>'
      ) +
      field(
        "练习台地址",
        "作答、批改、讲题、周卷、资料和能力都请求这个地址。",
        '<input name="practiceBase" type="url" required value="' + esc(cfg.practiceBaseUrl) + '"/>'
      ) +
      field(
        "Practice API Token",
        "与练习台环境变量 PRACTICE_API_TOKEN 相同。填错时会提示「Token 无效（401）」，而不是笼统的网络错误。",
        '<input name="practiceToken" type="password" autocomplete="off" required value="' + esc(cfg.practiceToken) + '"/>'
      ) +
      field(
        "学员编号",
        "每次请求都会带上，练习台按这个编号取题和记掌握度。",
        '<input name="learnerId" required autocomplete="off" value="' + esc(cfg.learnerId) + '"/>'
      ) +
      '<div class="btn-row"><button type="submit" class="btn primary">保存并连接</button></div></form></section>'
    );
  }

  function renderToday() {
    var slots = viewSlots();
    var open = countOpen();
    var done = state.items.length - open;
    var slotHtml = slots
      .map(function (slot) {
        var it = itemById(slot.itemId);
        var status = it ? (it.answered ? "已完成" : "可做") : FqmLoop.bankKind(slot.kind) ? "从题库补练" : "待推送";
        var title = it ? slot.label + " · " + (it.title || it.id) : slot.label + " · 今日未排程";
        var meta = "时段 " + (slot.window || "") + (it && it.kp ? " · " + it.kp : "");
        return (
          '<button type="button" class="slot-row' +
          (it && it.answered ? " is-done" : "") +
          '" data-item-id="' +
          esc(slot.itemId || "") +
          '" data-slot-kind="' +
          esc(slot.kind) +
          '"><div class="slot-title">' +
          esc(title) +
          '</div><div class="slot-status">' +
          esc(status) +
          '</div><div class="slot-meta">' +
          esc(meta) +
          "</div></button>"
        );
      })
      .join("");
    var backlog = state.items.filter(function (it) { return it && it.backlog && !it.answered; });
    var backlogHtml = backlog.length
      ? backlog
          .map(function (it) {
            return (
              '<button type="button" class="backlog-item" data-item-id="' +
              esc(it.id) +
              '"><div class="bi-title">' +
              esc((it.subject || "") + " · " + (it.title || it.id)) +
              '</div><div class="bi-meta">' +
              esc("缓存日 " + (it.day || "") + " · " + (it.kp || "")) +
              "</div></button>"
            );
          })
          .join("")
      : '<p class="calm-note">没有历史未答。今日槽或题库补练可直接开做。</p>';
    var weak = state.bootstrap && state.bootstrap.weakHint;
    var cta = open === 0 ? "查看完成状态" : "从最早未答开始";
    return (
      '<div class="stack"><section class="card stack">' +
      '<div class="row between wrap"><h1>今日练习</h1><span class="pill">' +
      esc(todayLabel()) +
      "</span></div>" +
      '<div class="stats"><div class="stat"><div class="n">' +
      slots.length +
      '</div><div class="t">今日题</div></div><div class="stat"><div class="n">' +
      open +
      '</div><div class="t">今日剩余</div></div><div class="stat"><div class="n">' +
      done +
      '</div><div class="t">今日完成</div></div></div>' +
      (state.error ? '<p class="calm-note" role="status">' + esc(state.error) + "</p>" : "") +
      '<p class="hint">数学、通信、复习各一题。过了时间窗没做的，今天仍可补，不占明天的题。</p>' +
      '<div class="stack">' +
      slotHtml +
      "</div>" +
      (weak ? '<p class="hint"><strong>薄弱提示</strong> — ' + esc(weak) + "</p>" : "") +
      '<button type="button" class="btn primary" id="btn-start">' +
      esc(cta) +
      "</button></section>" +
      '<section class="card stack"><h2>历史未答</h2>' +
      backlogHtml +
      "</section></div>"
    );
  }

  function renderPractice() {
    var it = state.current;
    if (!it) return renderToday();
    var weak = (state.bootstrap && state.bootstrap.weakHint) || "完成今日最早未答槽";
    var total = state.items.length || 0;
    var openN = countOpen();
    var doneN = total - openN;
    var pct = total ? Math.round((doneN / total) * 100) : 0;
    return (
      '<div class="stack"><div class="desk-split">' +
      '<section class="card stack stem-card"><div class="row wrap"><span class="pill">' +
      esc(it.subject || "练习") +
      "</span>" +
      (it.kp ? '<span class="pill warn">' + esc(it.kp) + "</span>" : "") +
      '<span class="pill">' +
      esc(it.id || "") +
      "</span></div><h2>" +
      esc(it.title || "题目") +
      "</h2>" +
      FqmMath.renderStemHtml(it) +
      '</section><aside class="card progress-card"><div class="side-rail">' +
      '<div class="rail-item"><div class="k">进度</div><div class="row between"><strong>' +
      doneN +
      "/" +
      total +
      '</strong><span class="meta">' +
      pct +
      '%</span></div><div class="progress-track"><div class="progress-fill" style="width:' +
      pct +
      '%"></div></div></div>' +
      '<div class="rail-item"><div class="k">当前知识点</div><div>' +
      esc(it.kp || "—") +
      '</div></div><div class="rail-item"><div class="k">薄弱提示</div><div>' +
      esc(weak) +
      "</div></div></div></aside>" +
      '<section class="card stack answer-card"><div class="row between wrap"><h3>作答</h3><span class="pill">手写可拍照</span></div>' +
      '<div class="ocr-zone"><div class="ocr-modes">' +
      '<button type="button" class="ocr-mode' +
      (state.ocrMode !== "formula" ? " is-on" : "") +
      '" data-ocr-mode="document">整页识别</button>' +
      '<button type="button" class="ocr-mode' +
      (state.ocrMode === "formula" ? " is-on" : "") +
      '" data-ocr-mode="formula">公式加强</button></div>' +
      '<input type="file" id="ocr-file" accept="image/*" hidden>' +
      '<div class="ocr-actions"><button type="button" class="btn ghost" id="btn-ocr-pick">选择手写图片</button>' +
      '<button type="button" class="btn ghost" id="btn-ocr-run"' +
      (ocrPayload && !state.ocrBusy ? "" : " disabled") +
      ">" +
      (state.ocrBusy ? "识别中…" : "识别") +
      "</button></div>" +
      (ocrPayload
        ? '<div class="ocr-preview"><img alt="手写预览" src="' +
          esc(ocrPayload.dataUrl) +
          '"><p class="hint">' +
          esc(state.ocrMsg || ocrPayload.name) +
          "</p></div>"
        : '<p class="hint">演算纸用「整页识别」；只拍一条公式用「公式加强」。点「识别」填入下方原文。</p>') +
      "</div>" +
      '<label class="hint" for="answer-input">原文（可改）</label>' +
      '<textarea class="answer' +
      (state.error ? " is-invalid" : "") +
      '" id="answer-input" placeholder="写出推导与结论，或先识别手写再核对。提交后由练习台批改。"></textarea>' +
      '<div class="answer-preview-wrap"><div class="row between wrap"><h3>预览</h3><span class="pill">对照公式</span></div>' +
      '<div class="answer-preview math-block is-empty" id="answer-preview" aria-live="polite"></div></div>' +
      (state.error ? '<p class="field-error" role="alert">' + esc(state.error) + "</p>" : "") +
      '<div class="row wrap link-row">' +
      '<button type="button" class="text-link" id="btn-send-tutor">发给老师讨论</button>' +
      '<button type="button" class="text-link" id="btn-ask-tutor">不懂，问讲师</button>' +
      '<button type="button" class="text-link is-warn" id="btn-report-poor">题质量差</button>' +
      "</div></section></div></div>"
    );
  }

  function renderFeedback() {
    var item = state.current || {};
    var r = state.lastResult || { correct: false, comment: "", explain: "", submitted: state.draft };
    var ok = !!r.correct;
    var partial = !ok && !!r.partial;
    var markCls = ok ? "ok" : partial ? "warn" : "bad";
    var markText = ok ? "通过" : partial ? "部分通过" : "未通过";
    var markSub = ok ? "作答正确" : partial ? "部分正确" : "作答不正确";
    var gmLabel = GRADE_MODE_LABEL[r.gradeMode] || "";
    var mastery =
      typeof r.masteryBefore === "number" && typeof r.masteryAfter === "number"
        ? esc((item.id || "") + (item.kp ? " · " + item.kp : "")) +
          " · 掌握度 p̂ " +
          Number(r.masteryBefore).toFixed(3) +
          " → " +
          Number(r.masteryAfter).toFixed(3)
        : esc((item.id || "") + (item.kp ? " · " + item.kp : ""));
    var explain = r.explain || item.explain || "";
    return (
      '<div class="stack"><section class="card stack"><div class="result-banner ' +
      markCls +
      '" role="status"><div class="row between wrap"><div class="result-mark ' +
      markCls +
      '">' +
      markText +
      "</div>" +
      (gmLabel
        ? '<span class="grade-chip' + (r.gradeMode && r.gradeMode !== "llm" ? " is-degraded" : "") + '">' + esc(gmLabel) + "</span>"
        : "") +
      '</div><div class="result-verdict">' +
      esc(markSub) +
      '</div><div class="stem-text">' +
      FqmMath.renderMathMarkdown(r.comment || "") +
      '</div><div class="meta">' +
      mastery +
      "</div></div>" +
      '<div class="hint"><strong>你的作答</strong><br />' +
      esc(r.submitted || state.draft || "") +
      "</div>" +
      '<div class="row wrap link-row"><button type="button" class="text-link" id="btn-ask-tutor">不懂，问讲师</button>' +
      '<button type="button" class="text-link is-warn" id="btn-report-poor">题质量差</button></div></section>' +
      '<section class="card" style="padding:0"><div class="fold' +
      (state.explainOpen ? " is-open" : "") +
      '"><button type="button" class="fold-toggle" id="btn-fold" aria-expanded="' +
      (state.explainOpen ? "true" : "false") +
      '"><span>查看讲解</span><span class="meta">' +
      (state.explainOpen ? "收起" : "展开") +
      "</span></button><div class=\"fold-panel\">" +
      (explain ? FqmMath.renderMathMarkdown(explain) : "<p>这道题没有另附讲解。</p>") +
      (item.katex ? '<div class="math-block" data-tex="' + esc(item.katex) + '"></div>' : "") +
      "</div></div></section></div>"
    );
  }

  function renderDone() {
    return (
      '<div class="empty">' +
      markBox('<path d="M5 13l4 4L19 7"/>') +
      "<h1>今日练习已完成</h1><p>今天的题都交过了。明天会有新题；漏做的仍可从今日入口补。</p>" +
      '<div class="stack"><button type="button" class="btn ghost" id="btn-done-home">回到今日入口</button>' +
      '<button type="button" class="btn primary" id="btn-pull-math">从数学题库再补一题</button></div></div>'
    );
  }

  function renderTutor() {
    var msgs = threadOf(state.tutorThreadId);
    if (!msgs.length && !state.busy) {
      var general = FqmLoop.isGeneralThread(state.tutorThreadId);
      return (
        '<div class="empty">' +
        markBox('<path d="M5 6.5h10.5A2.5 2.5 0 0 1 18 9v5.5A2.5 2.5 0 0 1 15.5 17H10l-4.5 3v-3H5A2 2 0 0 1 3 15V8.5A2 2 0 0 1 5 6.5Z"/>') +
        "<h1>" +
        (general ? "新对话" : "问讲师") +
        "</h1><p>" +
        (general ? "可以问学情或接下来怎么练。要讲某一题，从练习台点「不懂，问讲师」。" : "就这道题问卡住的步骤。") +
        "</p></div>"
      );
    }
    var html = '<div class="thread" aria-live="polite">';
    msgs.forEach(function (m, i) {
      var last = i === msgs.length - 1;
      var cites = "";
      if (m.role !== "user" && m.citations && m.citations.length) {
        cites = '<div class="tutor-cites">';
        m.citations.forEach(function (c) {
          cites += '<span class="tutor-cite">[' + esc(c.n) + "] " + esc(c.source || "") + "</span>";
        });
        cites += "</div>";
      }
      html +=
        '<article class="msg' +
        (m.role === "user" ? " is-user" : "") +
        '"' +
        (last ? ' data-last-msg="1"' : "") +
        '><div class="msg-who">' +
        (m.role === "user" ? "你" : "讲师") +
        '</div><div class="msg-body">' +
        FqmMath.renderMathMarkdown(m.text) +
        (m.streaming ? '<span class="stream-cursor"></span>' : "") +
        "</div>" +
        cites +
        (m.role !== "user" && !m.streaming
          ? '<div class="msg-actions"><button type="button" class="msg-action" data-fill-msg="' + i + '">填入作答</button></div>'
          : "") +
        "</article>";
    });
    if (state.busy) html += '<div class="pending">讲师正在作答…</div>';
    return html + "</div>";
  }

  function renderExam() {
    return (
      '<div class="stack"><h1>周卷</h1><div class="exam-pick" id="exam-list"><p class="hint">正在查看是否有卷…</p></div>' +
      '<iframe class="exam-embed" id="exam-frame" title="周卷" src="about:blank"></iframe></div>'
    );
  }

  function renderNotes() {
    return (
      '<div class="stack"><section class="card stack"><div class="row between wrap"><h1>资料库</h1>' +
      '<label class="btn">放入手写图片<input id="note-file" type="file" accept="image/*" hidden></label></div>' +
      '<p class="hint">点名字看原图。图片存在练习台，问讲师时可以让他看这些笔记。</p>' +
      '<div class="notes-layout"><div class="notes-list" id="notes-list"><p class="hint">正在读取…</p></div>' +
      '<div class="notes-view" id="notes-view"><p class="hint">选一条笔记，在这里看原图。</p></div></div></section></div>'
    );
  }

  function renderMain() {
    if (state.screen === "settings") return renderSettings();
    if (state.screen === "feedback") return renderFeedback();
    if (state.screen === "tutor") return renderTutor();
    if (state.screen === "exam") return renderExam();
    if (state.screen === "notes") return renderNotes();
    if (state.screen === "done") return renderDone();
    if (state.screen === "loading") return '<section class="card stack"><h1>正在连接练习台</h1><p class="hint">读取今日三槽…</p></section>';
    if (state.screen === "practice") return renderPractice();
    return renderToday();
  }

  function renderDock() {
    if (state.screen === "tutor") {
      var general = FqmLoop.isGeneralThread(state.tutorThreadId);
      return (
        '<form class="composer-row" id="composer-form"><textarea class="composer" id="composer-input" rows="1" placeholder="' +
        (general ? "问学情或计划…" : "问这题卡住的步骤…") +
        '"></textarea><button type="submit" class="btn primary" id="btn-send"' +
        (state.busy ? " disabled" : "") +
        ">发送</button></form>"
      );
    }
    if (state.screen === "feedback") {
      var nxt = FqmLoop.pickNextLocal(state.items, state.current && state.current.id);
      return '<button type="button" class="btn primary" id="btn-next">' + (nxt ? "下一题" : "完成今日") + "</button>";
    }
    if (state.screen === "practice" && state.current) {
      return (
        '<button type="button" class="btn primary" id="btn-submit"' +
        (state.busy ? " disabled" : "") +
        ">" +
        (state.busy ? "提交中…" : "提交") +
        "</button>"
      );
    }
    return "";
  }

  function renderTabs() {
    var icons = {
      practice: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="5" y="3.5" width="14" height="17" rx="2"/><path d="M8.5 8.5h7M8.5 12h7M8.5 15.5h4"/></svg>',
      exam: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M7 3.5h7l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-9.5A1.5 1.5 0 0 1 5.5 20V5A1.5 1.5 0 0 1 7 3.5Z"/><path d="M14 3.5V8h4.5"/></svg>',
      notes: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="4" y="5" width="16" height="14" rx="1.5"/><circle cx="9" cy="10" r="1.4"/><path d="M4 16.5 9 12l3.5 3L20 17"/></svg>',
      tutor: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M5 6.5h10.5A2.5 2.5 0 0 1 18 9v5.5A2.5 2.5 0 0 1 15.5 17H10l-4.5 3v-3H5A2 2 0 0 1 3 15V8.5A2 2 0 0 1 5 6.5Z"/></svg>',
      brain: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="7"/><path d="M12 8.5v7M8.5 12h7"/></svg>'
    };
    function tab(id, label, on) {
      return (
        '<button type="button" class="tab-btn' +
        (on ? " is-active" : "") +
        '" data-tab="' +
        id +
        '"' +
        (on ? ' aria-current="page"' : "") +
        ">" +
        (icons[id] || "") +
        "<span>" +
        label +
        "</span></button>"
      );
    }
    var practiceOn =
      state.screen === "today" || state.screen === "practice" || state.screen === "feedback" || state.screen === "done" || state.screen === "loading";
    return (
      tab("practice", "练习", practiceOn) +
      tab("exam", "周卷", state.screen === "exam") +
      tab("notes", "资料", state.screen === "notes") +
      tab("tutor", "讲师", state.screen === "tutor") +
      tab("brain", "能力", state.screen === "brain")
    );
  }

  function render() {
    var gen = ++flipGen;
    var prev = lastPaintScreen;
    var next = state.screen;
    var changed = !!(prev && prev !== next);
    if (changed && next === "settings" && prev !== "settings" && prev !== "loading") state.returnScreen = prev;
    var dir = 0;
    if (changed) {
      if (flipOverride != null) dir = flipOverride;
      else dir = inferDir(prev, next);
    }
    flipOverride = null;
    paintTheme();
    var tutor = next === "tutor";
    var brain = next === "brain";
    var onPractice = next === "today" || next === "practice" || next === "feedback" || next === "done";
    if (document.body && document.body.classList) {
      document.body.classList.toggle("is-tutor", tutor);
      document.body.classList.toggle("is-brain", brain);
    }
    var appNode = document.getElementById("app");
    if (appNode && appNode.classList) {
      appNode.classList.toggle("is-tutor", tutor);
      appNode.classList.toggle("is-brain", brain);
    }
    if (el.brain) el.brain.hidden = !brain;
    var keepY = el.root.scrollTop || 0;
    el.header.innerHTML = renderHeader();
    if (el.chrome) {
      el.chrome.hidden = !onPractice;
      el.chrome.innerHTML = onPractice ? renderChrome() : "";
    }
    if (el.strip) {
      el.strip.hidden = !tutor;
      el.strip.innerHTML = tutor ? renderStrip() : "";
    }
    var enter = changed && dir ? (dir < 0 ? "is-enter-right" : "is-enter-left") : "is-open";
    el.root.innerHTML = '<div class="flip-sheet ' + enter + '">' + renderMain() + "</div>";
    el.dock.innerHTML = renderDock();
    el.tabs.innerHTML = renderTabs();
    bind();
    mountMath();
    paintDraftPreview();
    if (!changed) el.root.scrollTop = keepY;
    else if (next === "practice" || next === "feedback" || next === "today" || next === "done" || next === "settings") el.root.scrollTop = 0;
    if (tutor) el.root.scrollTop = el.root.scrollHeight;
    if (changed && dir && el.root.querySelector) {
      var sheet = el.root.querySelector(".flip-sheet");
      if (sheet) playFlip(sheet, gen);
      else flipBusy = false;
    } else flipBusy = false;
    lastPaintScreen = next;
    if (next === "exam") loadExam();
    if (next === "notes") loadNotes();
  }

  function bindTheme(scope) {
    if (!scope || !scope.querySelectorAll) return;
    var nodes = scope.querySelectorAll("[data-theme-pick]");
    if (!nodes || !nodes.forEach) return;
    nodes.forEach(function (btn) {
      btn.onclick = function () {
        applyTheme(btn.getAttribute("data-theme-pick"));
        render();
      };
    });
  }

  function bind() {
    var gear = document.getElementById("btn-gear");
    if (gear) gear.onclick = openSettings;
    var settingsBack = document.getElementById("btn-settings-back");
    if (settingsBack) settingsBack.onclick = leaveSettings;
    bindTheme(el.header);
    bindTheme(el.root);
    var form = document.getElementById("settings-form");
    if (form) {
      form.onsubmit = function (e) {
        e.preventDefault();
        saveSettings(form);
      };
    }
    var submit = document.getElementById("btn-submit");
    if (submit) submit.onclick = submitAnswer;
    var next = document.getElementById("btn-next");
    if (next) next.onclick = goNextQuestion;
    var start = document.getElementById("btn-start");
    if (start) start.onclick = startToday;
    var pull = document.getElementById("btn-pull-math");
    if (pull) pull.onclick = function () { fetchBankItem("math"); };
    var home = document.getElementById("btn-done-home");
    if (home) home.onclick = function () { state.screen = "today"; render(); };
    var ask = document.getElementById("btn-ask-tutor");
    if (ask) ask.onclick = askTutor;
    var sendTutor = document.getElementById("btn-send-tutor");
    if (sendTutor) sendTutor.onclick = sendDraftToTutor;
    var poor = document.getElementById("btn-report-poor");
    if (poor) poor.onclick = reportPoor;
    var fold = document.getElementById("btn-fold");
    if (fold) fold.onclick = function () { state.explainOpen = !state.explainOpen; render(); };
    var newer = document.getElementById("btn-new-tutor");
    if (newer) newer.onclick = startBlankTutor;
    var stripNew = document.getElementById("btn-new-tutor-strip");
    if (stripNew) stripNew.onclick = startBlankTutor;
    var back = document.getElementById("btn-tutor-back");
    if (back) back.onclick = backFromTutor;
    var brainBack = document.getElementById("btn-brain-back");
    if (brainBack) brainBack.onclick = function () { state.screen = "today"; render(); };
    var prev = document.getElementById("page-prev");
    if (prev) prev.onclick = flipBack;
    var pageNext = document.getElementById("page-next");
    if (pageNext) pageNext.onclick = flipForward;
    if (el.chrome && el.chrome.querySelectorAll) {
      el.chrome.querySelectorAll("[data-page]").forEach(function (dot) {
        dot.onclick = function () { goToPageDot(dot.getAttribute("data-page")); };
      });
    }
    if (el.strip) {
      el.strip.querySelectorAll("[data-thread-id]").forEach(function (btn) {
        btn.onclick = function () { selectThread(btn.getAttribute("data-thread-id")); };
      });
    }
    el.root.querySelectorAll("[data-slot-kind], [data-item-id]").forEach(function (btn) {
      if (btn.classList && btn.className.indexOf("slot-row") < 0 && btn.className.indexOf("backlog-item") < 0) return;
      btn.onclick = function () {
        var id = btn.getAttribute("data-item-id");
        var kind = btn.getAttribute("data-slot-kind");
        if (id) openSlot(kind || "", id);
        else if (kind) openSlot(kind, "");
      };
    });
    el.root.querySelectorAll("[data-ocr-mode]").forEach(function (btn) {
      btn.onclick = function () {
        state.ocrMode = btn.getAttribute("data-ocr-mode") === "formula" ? "formula" : "document";
        render();
      };
    });
    var ocrFile = document.getElementById("ocr-file");
    if (ocrFile) {
      ocrFile.onchange = function () {
        var file = ocrFile.files && ocrFile.files[0];
        fileToOcrPayload(file, function (err, payload) {
          if (err || !payload) {
            state.error = "无法读取这张图片，请换一张 JPG / PNG。";
            render();
            return;
          }
          ocrPayload = payload;
          state.ocrMsg = "已选图，点「识别」填入下方文本。";
          state.error = "";
          render();
        });
      };
    }
    var ocrPick = document.getElementById("btn-ocr-pick");
    if (ocrPick) ocrPick.onclick = function () {
      var input = document.getElementById("ocr-file");
      if (input) input.click();
    };
    var ocrRun = document.getElementById("btn-ocr-run");
    if (ocrRun) ocrRun.onclick = runOcr;
    var noteFile = document.getElementById("note-file");
    if (noteFile) {
      noteFile.onchange = function () {
        var file = noteFile.files && noteFile.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.onload = function () {
          FqmApi.saveNote(cfg, {
            learner: cfg.learnerId,
            name: file.name || "手写笔记",
            image: String(reader.result || "")
          }).then(function () { loadNotes(); });
        };
        reader.readAsDataURL(file);
      };
    }
    var composer = document.getElementById("composer-form");
    if (composer) {
      composer.onsubmit = function (e) {
        e.preventDefault();
        sendChat(state.tutorDraft);
      };
    }
    var composerInput = document.getElementById("composer-input");
    if (composerInput) {
      composerInput.value = state.tutorDraft;
      composerInput.oninput = function () { state.tutorDraft = composerInput.value; };
    }
    el.root.querySelectorAll("[data-fill-msg]").forEach(function (btn) {
      btn.onclick = function () {
        var idx = parseInt(btn.getAttribute("data-fill-msg"), 10);
        var msgs = threadOf(state.tutorThreadId);
        if (msgs[idx]) fillFromTutor(msgs[idx].text);
      };
    });
    el.tabs.querySelectorAll("[data-tab]").forEach(function (btn) {
      btn.onclick = function () {
        var id = btn.getAttribute("data-tab");
        if (id === "exam") {
          state.screen = "exam";
          render();
        } else if (id === "notes") {
          state.screen = "notes";
          render();
        } else if (id === "tutor") askTutor();
        else if (id === "brain") openBrain();
        else {
          state.screen = "today";
          render();
        }
      };
    });
    var ta = document.getElementById("answer-input");
    if (ta) {
      ta.value = state.draft;
      ta.oninput = function () {
        state.draft = ta.value;
        if (state.error) {
          state.error = "";
          ta.classList.remove("is-invalid");
          var err = el.root.querySelector(".field-error");
          if (err && err.remove) err.remove();
        }
        paintDraftPreview();
      };
    }
  }

  function bindSwipe() {
    if (swipeBound) return;
    var stageEl = document.getElementById("stage");
    if (!stageEl || !stageEl.addEventListener) return;
    swipeBound = true;
    var tracking = false;
    var startX = 0;
    var startY = 0;
    var dx = 0;
    var axis = null;
    var pointerId = null;
    var captured = false;

    function onDown(e) {
      if (e.button != null && e.button !== 0) return;
      var t = e.target;
      if (t && t.closest && t.closest("button, a, input, textarea, select, .page-nav, .page-dot, .theme-opt, .composer, .tabbar, label")) return;
      if (!canSwipe()) return;
      tracking = true;
      pointerId = e.pointerId;
      startX = e.clientX;
      startY = e.clientY;
      dx = 0;
      axis = null;
      captured = false;
    }
    function onMove(e) {
      if (!tracking || e.pointerId !== pointerId) return;
      var mx = e.clientX - startX;
      var my = e.clientY - startY;
      if (!axis) {
        if (Math.abs(mx) < 8 && Math.abs(my) < 8) return;
        axis = Math.abs(mx) > Math.abs(my) * 1.15 ? "x" : "y";
        if (axis === "x") {
          if (stageEl.classList) stageEl.classList.add("is-swiping");
          if (!captured && stageEl.setPointerCapture) {
            try { stageEl.setPointerCapture(pointerId); captured = true; } catch (err) {}
          }
          if (e.preventDefault) e.preventDefault();
        }
      }
      if (axis !== "x") return;
      if (e.preventDefault) e.preventDefault();
      dx = mx;
      var sheet = el.root && el.root.querySelector ? el.root.querySelector(".flip-sheet.is-open") : null;
      if (sheet && sheet.style && canSwipe()) {
        var mot = motionVars();
        var amount = Math.max(-1, Math.min(1, dx / 180));
        sheet.style.transform =
          "translateX(" + (amount * mot.drag) + "%) rotate(" + (mot.tilt * amount) + "deg) scale(" + (1 - Math.abs(amount) * mot.scale) + ")";
        sheet.style.opacity = String(1 - Math.abs(amount) * mot.fade);
        sheet.style.transition = "none";
      }
    }
    function clearSheet() {
      var sheet = el.root && el.root.querySelector ? el.root.querySelector(".flip-sheet") : null;
      if (!sheet || !sheet.style) return;
      sheet.style.transform = "";
      sheet.style.opacity = "";
      sheet.style.transition = "";
    }
    function onUp(e) {
      if (!tracking || (pointerId != null && e.pointerId !== pointerId)) return;
      tracking = false;
      if (stageEl.classList) stageEl.classList.remove("is-swiping");
      clearSheet();
      if (captured && stageEl.releasePointerCapture) {
        try { stageEl.releasePointerCapture(pointerId); } catch (err2) {}
      }
      captured = false;
      pointerId = null;
      if (!flipBusy && axis === "x" && Math.abs(dx) >= SWIPE_THRESHOLD) {
        if (dx < 0) flipForward();
        else flipBack();
      }
      axis = null;
      dx = 0;
    }
    stageEl.addEventListener("pointerdown", onDown);
    stageEl.addEventListener("pointermove", onMove, { passive: false });
    stageEl.addEventListener("pointerup", onUp);
    stageEl.addEventListener("pointercancel", onUp);
    if (window.addEventListener) {
      window.addEventListener("keydown", function (e) {
        var tag = e.target && e.target.tagName;
        if (tag && /^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
        if (!canSwipe()) return;
        if (e.key === "ArrowLeft") {
          if (e.preventDefault) e.preventDefault();
          flipBack();
        } else if (e.key === "ArrowRight") {
          if (e.preventDefault) e.preventDefault();
          flipForward();
        }
      });
    }
  }

  function boot() {
    if (window.addEventListener) {
      window.addEventListener("message", function (ev) {
        var data = ev && ev.data;
        if (data && data.type === "cap-embed-exit") {
          state.screen = "today";
          render();
        }
      });
    }
    if (!FqmConfig.isConfigured(cfg)) {
      state.screen = "settings";
      state.error = "首次使用请填写练习台 Token 与学员编号。DeepSeek Key 现在不用填。";
      render();
      return;
    }
    loadBootstrapThenPick();
  }

  bindSwipe();
  boot();
})();
