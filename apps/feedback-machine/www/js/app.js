(function () {
  "use strict";

  var cfg = FqmConfig.load();
  var state = {
    screen: "loading",
    error: "",
    busy: false,
    bootstrap: null,
    items: [],
    slots: [],
    current: null,
    draft: "",
    lastResult: null,
    lastKind: "math"
  };

  var el = {
    root: document.getElementById("app"),
    toast: document.getElementById("toast")
  };

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function showToast(msg) {
    if (!el.toast) return;
    el.toast.textContent = msg;
    el.toast.classList.add("is-on");
    setTimeout(function () {
      el.toast.classList.remove("is-on");
    }, 2800);
  }

  function mergeItemsFromBootstrap(data) {
    state.bootstrap = data;
    state.items = (data && data.items) || [];
    state.slots = (data && data.slots) || [];
  }

  function findUnanswered() {
    for (var i = 0; i < state.items.length; i++) {
      var it = state.items[i];
      if (!it.answered) return it;
    }
    return null;
  }

  function slotKindForItem(it) {
    if (!it) return state.lastKind || "math";
    if (it.kind) return it.kind;
    for (var i = 0; i < state.slots.length; i++) {
      if (state.slots[i].itemId === it.id) return state.slots[i].kind || "math";
    }
    return state.lastKind || "math";
  }

  function setCurrent(item) {
    state.current = item;
    if (item && item.kind) state.lastKind = item.kind;
    state.draft = "";
    state.lastResult = null;
  }

  function gradeStillRunning(data) {
    if (!data) return false;
    if (data.pending || data.grading) return true;
    return !!(data.result && data.result.status === "grading");
  }

  function resultReady(data) {
    var r = data && data.result;
    if (!r) return false;
    return r.status !== "grading";
  }

  function applyItemResponse(data) {
    if (!data || !data.ok || !data.item) {
      state.error = (data && (data.error || data.detail)) || "无法加载题目";
      return false;
    }
    setCurrent(data.item);
    if (data.result) state.lastResult = data.result;
    state.error = "";
    return true;
  }

  function loadBootstrapThenPick() {
    state.busy = true;
    state.error = "";
    render();
    return FqmApi.bootstrap(cfg)
      .then(function (data) {
        if (!data || !data.ok) {
          state.error = (data && data.error) || "bootstrap 失败";
          state.screen = "practice";
          return;
        }
        mergeItemsFromBootstrap(data);
        var next = findUnanswered();
        if (next) {
          setCurrent(next);
          state.screen = "practice";
          return;
        }
        return fetchBankItem(state.lastKind || "math");
      })
      .catch(function (e) {
        state.error = "网络错误：" + (e && e.message ? e.message : "unknown");
        state.screen = "settings";
      })
      .finally(function () {
        state.busy = false;
        render();
      });
  }

  function fetchBankItem(kind) {
    state.busy = true;
    render();
    return FqmApi.getItem(cfg, { kind: kind })
      .then(function (data) {
        if (!applyItemResponse(data)) {
          state.screen = "practice";
          return;
        }
        state.screen = "practice";
      })
      .finally(function () {
        state.busy = false;
        render();
      });
  }

  function openSettings() {
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
    if (FqmConfig.isConfigured(cfg)) {
      loadBootstrapThenPick();
    } else {
      state.screen = "settings";
      state.error = "请填写练习台地址、Token 与学员编号";
      render();
    }
  }

  function submitAnswer() {
    var it = state.current;
    if (!it || state.busy) return;
    var ans = (state.draft || "").trim();
    if (!ans) {
      state.error = "请先填写答案";
      render();
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
        if (data && data.ok && data.result && !gradeStillRunning(data)) {
          state.lastResult = data.result;
          if (data.item) state.current = data.item;
          state.screen = "feedback";
          return;
        }
        if (gradeStillRunning(data) || !data.ok) {
          return pollGrade(it);
        }
        state.error = (data && data.error) || "提交失败";
      })
      .catch(function () {
        return pollGrade(it);
      })
      .finally(function () {
        if (state.screen !== "feedback") {
          state.busy = false;
          render();
        }
      });
  }

  function pollGrade(it) {
    var started = Date.now();
    var deadline = 8 * 60 * 1000;
    function tick() {
      if (Date.now() - started > deadline) {
        state.busy = false;
        state.error = "批改超时，请稍后在练习台查看";
        render();
        return;
      }
      FqmApi.getItem(cfg, { item: it.id, push: it.pushId })
        .then(function (data) {
          if (resultReady(data) && !gradeStillRunning(data)) {
            state.lastResult = data.result;
            state.screen = "feedback";
            state.busy = false;
            render();
            return;
          }
          setTimeout(tick, 2000);
        })
        .catch(function () {
          setTimeout(tick, 2000);
        });
    }
    setTimeout(tick, 2000);
  }

  function goNextQuestion() {
    var kind = slotKindForItem(state.current);
    var local = findUnanswered();
    if (local && (!state.current || local.id !== state.current.id)) {
      setCurrent(local);
      state.screen = "practice";
      render();
      return;
    }
    fetchBankItem(kind);
  }

  function renderStem(item) {
    if (!item) return "";
    if (item.katex) {
      try {
        return katex.renderToString(item.katex, { throwOnError: false, displayMode: true });
      } catch (e) {
        /* fall through */
      }
    }
    return esc(item.stem || item.title || "");
  }

  function renderFeedback(result) {
    if (!result) return "<p class=\"muted\">暂无反馈</p>";
    var ok = result.correct === true || result.status === "correct";
    var cls = ok ? "fb-ok" : "fb-bad";
    var head = ok ? "回答正确" : "需要再想想";
    var comment = result.comment || result.feedback || "";
    var explain = result.explain || "";
    var mastery = "";
    if (result.masteryBefore != null && result.masteryAfter != null) {
      mastery =
        "<p class=\"meta\">掌握度 " +
        Math.round(result.masteryBefore * 100) +
        "% → " +
        Math.round(result.masteryAfter * 100) +
        "%</p>";
    }
    return (
      '<div class="feedback ' +
      cls +
      '"><h2>' +
      head +
      "</h2><p>" +
      esc(comment) +
      "</p>" +
      mastery +
      (explain ? '<details class="explain"><summary>讲解</summary><div class="prose">' + esc(explain) + "</div></details>" : "") +
      "</div>"
    );
  }

  function renderSettings() {
    return (
      '<section class="panel">' +
      '<h1>设置</h1>' +
      '<p class="lede">密钥只保存在本机 localStorage；打包进 git 的代码不含真实密钥。正式版可改用 Android Keystore（后续）。</p>' +
      (state.error ? '<p class="err">' + esc(state.error) + "</p>" : "") +
      '<form id="settings-form" class="form">' +
      '<label>DeepSeek API Key<input name="deepseekKey" type="password" autocomplete="off" placeholder="可选，预留本机 OCR/批改" value="' +
      esc(cfg.deepseekApiKey) +
      '"/></label>' +
      '<label>DeepSeek Base URL（可选）<input name="deepseekBase" type="url" placeholder="https://api.deepseek.com" value="' +
      esc(cfg.deepseekBaseUrl) +
      '"/></label>' +
      '<label>练习台 Base URL<input name="practiceBase" type="url" required value="' +
      esc(cfg.practiceBaseUrl) +
      '"/></label>' +
      '<label>Practice API Token<input name="practiceToken" type="password" required autocomplete="off" value="' +
      esc(cfg.practiceToken) +
      '"/></label>' +
      '<label>Learner Id<input name="learnerId" required value="' +
      esc(cfg.learnerId) +
      '"/></label>' +
      '<div class="btn-row"><button type="submit" class="btn primary">保存并连接</button>' +
      (FqmConfig.isConfigured(cfg) ? '<button type="button" class="btn ghost" id="btn-back-practice">返回练习</button>' : "") +
      "</div></form></section>"
    );
  }

  function renderPractice() {
    var it = state.current;
    if (!it) {
      return (
        '<section class="panel center">' +
        '<p class="muted">' +
        (state.busy ? "加载中…" : "今日暂无题目") +
        "</p>" +
        '<button type="button" class="btn primary" id="btn-pull-math">从题库补一题（数学）</button>' +
        "</section>"
      );
    }
    return (
      '<section class="panel practice">' +
      '<header class="item-head"><span class="tag">' +
      esc(it.subject || it.kind || "练习") +
      "</span>" +
      (it.kp ? '<span class="meta">' + esc(it.kp) + "</span>" : "") +
      "</header>" +
      '<div class="stem">' +
      renderStem(it) +
      "</div>" +
      (state.error ? '<p class="err">' + esc(state.error) + "</p>" : "") +
      '<label class="answer-label">你的作答<textarea id="answer-input" rows="5" placeholder="手打答案；手写 OCR 后续接 DeepSeek 本机 key">' +
      esc(state.draft) +
      "</textarea></label>" +
      '<div class="btn-row">' +
      '<button type="button" class="btn primary" id="btn-submit" ' +
      (state.busy ? "disabled" : "") +
      ">" +
      (state.busy ? "提交中…" : "提交批改") +
      "</button>" +
      '<button type="button" class="btn ghost" id="btn-refresh">刷新题目</button>' +
      "</div></section>"
    );
  }

  function renderFeedbackScreen() {
    return (
      '<section class="panel">' +
      "<h1>批改反馈</h1>" +
      renderFeedback(state.lastResult) +
      '<div class="btn-row">' +
      '<button type="button" class="btn primary" id="btn-next">再出一题</button>' +
      '<button type="button" class="btn ghost" id="btn-settings">设置</button>' +
      "</div></section>"
    );
  }

  function render() {
    var html = "";
    if (state.screen === "settings") html = renderSettings();
    else if (state.screen === "feedback") html = renderFeedbackScreen();
    else html = renderPractice();

    el.root.innerHTML =
      '<header class="topbar"><button type="button" class="icon-btn" id="btn-gear" aria-label="设置">⚙</button>' +
      '<span class="title">反馈出题机</span><span class="learner">' +
      esc(cfg.learnerId) +
      "</span></header>" +
      '<main class="main">' +
      html +
      "</main>";

    bind();
  }

  function bind() {
    var gear = document.getElementById("btn-gear");
    if (gear) gear.onclick = openSettings;
    var form = document.getElementById("settings-form");
    if (form) {
      form.onsubmit = function (e) {
        e.preventDefault();
        saveSettings(form);
      };
    }
    var back = document.getElementById("btn-back-practice");
    if (back) back.onclick = function () {
      state.screen = "practice";
      render();
    };
    var submit = document.getElementById("btn-submit");
    if (submit) submit.onclick = submitAnswer;
    var refresh = document.getElementById("btn-refresh");
    if (refresh)
      refresh.onclick = function () {
        if (state.current) {
          FqmApi.getItem(cfg, { item: state.current.id, push: state.current.pushId }).then(function (d) {
            applyItemResponse(d);
            render();
          });
        } else loadBootstrapThenPick();
      };
    var next = document.getElementById("btn-next");
    if (next) next.onclick = goNextQuestion;
    var settingsBtn = document.getElementById("btn-settings");
    if (settingsBtn) settingsBtn.onclick = openSettings;
    var pull = document.getElementById("btn-pull-math");
    if (pull) pull.onclick = function () {
      fetchBankItem("math");
    };
    var ta = document.getElementById("answer-input");
    if (ta) {
      ta.value = state.draft;
      ta.oninput = function () {
        state.draft = ta.value;
      };
    }
  }

  function boot() {
    if (!FqmConfig.isConfigured(cfg)) {
      state.screen = "settings";
      state.error = "首次使用请填写练习台 Token 与学员编号";
      render();
      return;
    }
    loadBootstrapThenPick();
  }

  boot();
})();
