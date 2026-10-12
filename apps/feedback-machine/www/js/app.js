(function () {
  "use strict";

  var cfg = FqmConfig.load();
  var state = {
    screen: "loading",
    returnScreen: "practice",
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
    threads: {},
    tutorThreadId: null,
    tutorDraft: ""
  };

  var el = {
    header: document.getElementById("header"),
    root: document.getElementById("root"),
    dock: document.getElementById("dock"),
    tabs: document.getElementById("tabbar"),
    toast: document.getElementById("toast")
  };

  function esc(s) {
    return FqmMath.esc(s);
  }

  function showToast(msg) {
    if (!el.toast) return;
    el.toast.textContent = msg;
    el.toast.classList.add("is-on");
    setTimeout(function () {
      el.toast.classList.remove("is-on");
    }, 2800);
  }

  function threadOf(id) {
    var key = id || "general";
    if (!state.threads[key]) state.threads[key] = [];
    return state.threads[key];
  }

  function mergeItemsFromBootstrap(data) {
    state.bootstrap = data;
    state.items = (data && data.items) || [];
    state.slots = (data && data.slots) || [];
  }

  function setCurrent(item) {
    state.current = item;
    state.lastKind = FqmLoop.rememberKind(state.lastKind, item && item.kind);
    state.draft = "";
    state.lastResult = null;
    state.explainOpen = false;
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
    setCurrent(data.item);
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
          state.screen = "practice";
          return;
        }
        mergeItemsFromBootstrap(data);
        var next = FqmLoop.pickNextLocal(state.items, null);
        if (next) {
          setCurrent(next);
          state.screen = "practice";
          return;
        }
        return fetchBankItem(FqmLoop.bankKind(state.lastKind));
      })
      .catch(function (e) {
        state.error = "网络错误：" + (e && e.message ? e.message : "unknown");
        state.screen = "practice";
      })
      .finally(function () {
        state.busy = false;
        render();
      });
  }

  function fetchBankItem(kind) {
    var useKind = FqmLoop.bankKind(kind || state.lastKind);
    state.busy = true;
    state.screen = "practice";
    render();
    return FqmApi.getItem(cfg, { kind: useKind })
      .then(function (data) {
        if (!applyItemResponse(data)) {
          if (state.screen !== "settings") state.screen = "practice";
          return;
        }
        state.screen = "practice";
      })
      .catch(function (e) {
        state.error = "网络错误：" + (e && e.message ? e.message : "unknown");
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

  function goNextQuestion() {
    if (state.current) state.current.answered = true;
    var local = FqmLoop.pickNextLocal(state.items, state.current && state.current.id);
    if (local) {
      setCurrent(local);
      state.screen = "practice";
      render();
      return;
    }
    fetchBankItem(FqmLoop.bankKind(state.lastKind));
  }

  function askTutor() {
    if (state.screen === "practice" || state.screen === "feedback") {
      state.returnScreen = state.screen;
    }
    var it = state.current;
    if (it && it.id) state.tutorThreadId = it.id;
    else if (FqmLoop.isGeneralThread(state.tutorThreadId) === false && state.tutorThreadId) {
      /* keep */
    } else if (!state.tutorThreadId) {
      state.tutorThreadId = "general-" + Date.now();
    }
    state.screen = "tutor";
    state.tutorDraft = state.tutorDraft || "";
    render();
    var box = document.getElementById("composer-input");
    if (box) box.focus();
  }

  function startBlankTutor() {
    state.tutorThreadId = "general-" + Date.now();
    state.threads[state.tutorThreadId] = [];
    state.tutorDraft = "";
    state.screen = "tutor";
    render();
  }

  function backFromTutor() {
    state.screen = state.returnScreen === "feedback" && state.lastResult ? "feedback" : "practice";
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
    var msg =
      "我把手写识别/整理成了下面这份草稿（尚未正式交卷）。请帮我核对识别是否准确、推导有没有明显问题；讨论清楚后我再回练习台点提交。\n\n" +
      "【草稿】\n" +
      clipped;
    sendChat(msg);
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
    FqmApi.tutorChat(cfg, {
      learner: cfg.learnerId,
      item: blank ? null : it.id,
      push: blank ? null : it.pushId != null ? String(it.pushId) : null,
      message: trimmed,
      threadId: tid,
      blank: !!blank
    })
      .then(function (data) {
        if (FqmLoop.isUnauthorized(data)) {
          state.error = FqmLoop.TOKEN_INVALID_MESSAGE;
          state.screen = "settings";
          return;
        }
        msgs.push({
          role: "tutor",
          text: FqmLoop.tutorReplyText(data, trimmed),
          citations: (data && data.citations) || []
        });
      })
      .catch(function () {
        msgs.push({ role: "tutor", text: "讲师服务暂时不可用。", citations: [] });
      })
      .finally(function () {
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
    render();
    var input = document.getElementById("answer-input");
    if (input) input.focus();
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
        window.katex.render(trimmed, node, {
          throwOnError: false,
          displayMode: true,
          strict: "ignore",
          trust: false
        });
        return;
      } catch (e1) {
        /* fall through */
      }
    }
    node.innerHTML = '<div class="math-fallback">' + esc(trimmed) + "</div>";
  }

  var GRADE_MODE_LABEL = {
    llm: "LLM 批改",
    ref: "参考答案比对",
    ref_fallback: "LLM 暂不可用 · 参考答案初判"
  };

  function renderHeader() {
    if (state.screen === "tutor") {
      var it = state.current;
      var general = FqmLoop.isGeneralThread(state.tutorThreadId);
      var title = general
        ? "新对话"
        : (it && it.subject ? it.subject + " · " : "") + ((it && (it.title || it.id)) || "讲题");
      var sub = general
        ? "可问学情或计划。要讲某一题，从练习台点「不懂，问讲师」。"
        : (it && it.kp) || "就这道题问卡住的步骤。";
      return (
        '<div class="tutor-head">' +
        '<span class="tutor-badge">讲题</span>' +
        '<span class="tutor-title">' +
        esc(title) +
        "</span></div>" +
        '<div class="tutor-ops">' +
        '<button type="button" class="text-link" id="btn-new-tutor">新建对话</button>' +
        '<button type="button" class="text-link" id="btn-tutor-back">返回练习</button>' +
        "</div>" +
        '<div class="sub">' +
        esc(sub) +
        "</div>"
      );
    }
    var map = {
      loading: "连接练习台",
      practice: "作答",
      feedback: "批改结果",
      settings: "设置"
    };
    return (
      '<div class="brand-row">' +
      '<span class="brand">反馈出题机</span>' +
      '<div class="meta">' +
      esc(cfg.learnerId || "未指定学员") +
      "</div></div>" +
      '<div class="sub">' +
      esc(map[state.screen] || "练习台") +
      "</div>"
    );
  }

  function field(name, label, help, inputHtml) {
    return (
      "<label><span class=\"field-name\">" +
      label +
      "</span><span class=\"field-help\">" +
      help +
      "</span>" +
      inputHtml +
      "</label>"
    );
  }

  function renderSettings() {
    return (
      '<section class="card stack">' +
      "<h1>设置</h1>" +
      '<p class="lede">密钥只保存在本机，不会写进安装包。批改和出题都走练习台，不走本机 DeepSeek。</p>' +
      (state.error ? '<p class="field-error" role="alert">' + esc(state.error) + "</p>" : "") +
      '<form id="settings-form" class="form stack">' +
      field(
        "deepseekKey",
        'DeepSeek API Key <span class="pill warn">当前未使用</span>',
        "批改仍由练习台服务器完成。这里填写不会参与出题或打分，可以留空。",
        '<input name="deepseekKey" type="password" autocomplete="off" placeholder="留空即可" value="' +
          esc(cfg.deepseekApiKey) +
          '"/>'
      ) +
      field(
        "deepseekBase",
        'DeepSeek Base URL <span class="pill warn">当前未使用</span>',
        "预留字段。当前版本不会用它去请求模型。",
        '<input name="deepseekBase" type="url" inputmode="url" placeholder="https://api.deepseek.com" value="' +
          esc(cfg.deepseekBaseUrl) +
          '"/>'
      ) +
      field(
        "practiceBase",
        "练习台地址",
        "作答、批改、讲题都请求这个地址。默认是现网练习台。",
        '<input name="practiceBase" type="url" inputmode="url" required value="' +
          esc(cfg.practiceBaseUrl) +
          '"/>'
      ) +
      field(
        "practiceToken",
        "Practice API Token",
        "与练习台环境变量 PRACTICE_API_TOKEN 相同。填错时会提示「Token 无效（401）」，而不是笼统的网络错误。",
        '<input name="practiceToken" type="password" autocomplete="off" required value="' +
          esc(cfg.practiceToken) +
          '"/>'
      ) +
      field(
        "learnerId",
        "学员编号",
        "每次请求都会带上，练习台按这个编号取题和记掌握度。",
        '<input name="learnerId" required autocomplete="off" value="' + esc(cfg.learnerId) + '"/>'
      ) +
      '<div class="btn-row"><button type="submit" class="btn primary">保存并连接</button></div>' +
      "</form></section>"
    );
  }

  function renderPractice() {
    var it = state.current;
    if (!it) {
      return (
        '<section class="card stack">' +
        "<h1>今日暂无数学题</h1>" +
        (state.error ? '<p class="field-error" role="alert">' + esc(state.error) + "</p>" : "") +
        '<p class="hint">再出一题和空槽补题都从数学题库抽。</p>' +
        "</section>"
      );
    }
    var weak = state.bootstrap && state.bootstrap.weakHint;
    return (
      '<div class="stack">' +
      '<section class="card stack stem-card">' +
      '<div class="row wrap">' +
      '<span class="pill">' +
      esc(it.subject || "练习") +
      "</span>" +
      (it.kp ? '<span class="pill warn">' + esc(it.kp) + "</span>" : "") +
      '<span class="pill">' +
      esc(it.id || "") +
      "</span></div>" +
      "<h2>" +
      esc(it.title || "题目") +
      "</h2>" +
      FqmMath.renderStemHtml(it) +
      (weak ? '<p class="hint"><strong>薄弱提示</strong> — ' + esc(weak) + "</p>" : "") +
      "</section>" +
      '<section class="card stack">' +
      '<div class="row between wrap"><h3>作答</h3><span class="pill">手打</span></div>' +
      '<label class="hint" for="answer-input">原文（可改）</label>' +
      '<textarea class="answer' +
      (state.error ? " is-invalid" : "") +
      '" id="answer-input" placeholder="写出推导与结论。提交后由练习台批改。"></textarea>' +
      '<div class="answer-preview-wrap">' +
      '<div class="row between wrap"><h3>预览</h3><span class="pill">对照公式</span></div>' +
      '<div class="answer-preview math-block is-empty" id="answer-preview" aria-live="polite"></div>' +
      "</div>" +
      (state.error ? '<p class="field-error" role="alert">' + esc(state.error) + "</p>" : "") +
      '<div class="row wrap link-row">' +
      '<button type="button" class="text-link" id="btn-send-tutor"' +
      (state.busy ? " disabled" : "") +
      ">发给老师讨论</button>" +
      '<button type="button" class="text-link" id="btn-ask-tutor">不懂，问讲师</button>' +
      "</div>" +
      '<p class="hint">可先「发给老师讨论」，确认后再点下方提交。拍照识别仍在练习台网页。</p>' +
      "</section></div>"
    );
  }

  function renderFeedback() {
    var item = state.current || {};
    var r = state.lastResult || { correct: false, comment: "—", explain: "", submitted: state.draft };
    var ok = !!r.correct;
    var partial = !ok && !!r.partial;
    var markCls = ok ? "ok" : partial ? "warn" : "bad";
    var markText = ok ? "通过" : partial ? "部分通过" : "未通过";
    var markSub = ok ? "作答正确" : partial ? "部分正确" : "作答不正确";
    var gmLabel = GRADE_MODE_LABEL[r.gradeMode] || "";
    var gmChip = gmLabel
      ? '<span class="grade-chip' +
        (r.gradeMode === "llm" ? "" : " is-degraded") +
        '">' +
        esc(gmLabel) +
        "</span>"
      : "";
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
      '<div class="stack">' +
      '<section class="card stack">' +
      '<div class="result-banner ' +
      markCls +
      '" role="status">' +
      '<div class="row between wrap"><div class="result-mark ' +
      markCls +
      '">' +
      markText +
      "</div>" +
      gmChip +
      "</div>" +
      '<div class="result-verdict">' +
      esc(markSub) +
      "</div>" +
      '<div class="stem-text">' +
      FqmMath.renderMathMarkdown(r.comment || "") +
      "</div>" +
      '<div class="meta">' +
      mastery +
      "</div></div>" +
      '<div class="hint"><strong>你的作答</strong><br />' +
      esc(r.submitted || state.draft || "") +
      "</div>" +
      '<div class="row wrap link-row">' +
      '<button type="button" class="text-link" id="btn-ask-tutor">不懂，问讲师</button>' +
      "</div></section>" +
      '<section class="card" style="padding:0">' +
      '<div class="fold' +
      (state.explainOpen ? " is-open" : "") +
      '">' +
      '<button type="button" class="fold-toggle" id="btn-fold" aria-expanded="' +
      (state.explainOpen ? "true" : "false") +
      '"><span>查看讲解</span><span class="meta">' +
      (state.explainOpen ? "收起" : "展开") +
      "</span></button>" +
      '<div class="fold-panel">' +
      (explain ? FqmMath.renderMathMarkdown(explain) : "<p>这道题没有另附讲解。</p>") +
      (item.katex
        ? '<div class="math-block" data-tex="' + esc(item.katex) + '"></div>'
        : "") +
      "</div></div></section></div>"
    );
  }

  function renderTutor() {
    var msgs = threadOf(state.tutorThreadId);
    if (!msgs.length && !state.busy) {
      var general = FqmLoop.isGeneralThread(state.tutorThreadId);
      return (
        '<div class="empty">' +
        "<h1>" +
        (general ? "新对话" : "问讲师") +
        "</h1>" +
        "<p>" +
        (general
          ? "可以问学情或接下来怎么练。要讲某一题，从练习台点「不懂，问讲师」。"
          : "就这道题问卡住的步骤。") +
        "</p></div>"
      );
    }
    var html = '<div class="thread" aria-live="polite">';
    msgs.forEach(function (m, i) {
      var who = m.role === "user" ? "你" : "讲师";
      var cites = "";
      if (m.role !== "user" && m.citations && m.citations.length) {
        cites = '<div class="tutor-cites">';
        m.citations.forEach(function (c) {
          cites +=
            '<span class="tutor-cite">[' +
            esc(c.n) +
            "] " +
            esc(c.source || "") +
            "</span>";
        });
        cites += "</div>";
      }
      var fill =
        m.role !== "user"
          ? '<div class="msg-actions"><button type="button" class="msg-action" data-fill-msg="' +
            i +
            '">填入作答</button></div>'
          : "";
      html +=
        '<article class="msg' +
        (m.role === "user" ? " is-user" : "") +
        '"><div class="msg-who">' +
        who +
        '</div><div class="msg-body">' +
        FqmMath.renderMathMarkdown(m.text) +
        "</div>" +
        cites +
        fill +
        "</article>";
    });
    if (state.busy) html += '<div class="pending">讲师正在作答…</div>';
    return html + "</div>";
  }

  function renderMain() {
    if (state.screen === "settings") return renderSettings();
    if (state.screen === "feedback") return renderFeedback();
    if (state.screen === "tutor") return renderTutor();
    if (state.screen === "loading") {
      return '<section class="card stack"><h1>正在连接练习台</h1><p class="hint">读取今日数学题…</p></section>';
    }
    return renderPractice();
  }

  function renderDock() {
    if (state.screen === "tutor") {
      var general = FqmLoop.isGeneralThread(state.tutorThreadId);
      return (
        '<form class="composer-row" id="composer-form">' +
        '<textarea class="composer" id="composer-input" rows="1" placeholder="' +
        (general ? "问学情或计划…" : "问这题卡住的步骤…") +
        '"></textarea>' +
        '<button type="submit" class="btn primary" id="btn-send"' +
        (state.busy ? " disabled" : "") +
        ">发送</button></form>"
      );
    }
    if (state.screen === "feedback") {
      return '<button type="button" class="btn primary" id="btn-next">再出一题</button>';
    }
    if (state.screen === "practice") {
      if (!state.current) {
        return (
          '<button type="button" class="btn primary" id="btn-pull-math"' +
          (state.busy ? " disabled" : "") +
          ">" +
          (state.busy ? "加载中…" : "从题库补一题（数学）") +
          "</button>"
        );
      }
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
    function tab(id, label, on) {
      return (
        '<button type="button" class="tab-btn' +
        (on ? " is-active" : "") +
        '" data-tab="' +
        id +
        '"' +
        (on ? ' aria-current="page"' : "") +
        ">" +
        label +
        "</button>"
      );
    }
    var practiceOn = state.screen === "practice" || state.screen === "feedback" || state.screen === "loading";
    return (
      tab("practice", "练习台", practiceOn) +
      tab("tutor", "讲师", state.screen === "tutor") +
      tab("settings", "设置", state.screen === "settings")
    );
  }

  function render() {
    document.body.classList.toggle("is-tutor", state.screen === "tutor");
    el.header.innerHTML = renderHeader();
    el.root.innerHTML = renderMain();
    el.dock.innerHTML = renderDock();
    el.tabs.innerHTML = renderTabs();
    bind();
    mountMath();
    paintDraftPreview();
    if (state.screen === "tutor") el.root.scrollTop = el.root.scrollHeight;
  }

  function bind() {
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
    var pull = document.getElementById("btn-pull-math");
    if (pull) {
      pull.onclick = function () {
        fetchBankItem(FqmLoop.bankKind(state.lastKind));
      };
    }
    var ask = document.getElementById("btn-ask-tutor");
    if (ask) ask.onclick = askTutor;
    var sendTutor = document.getElementById("btn-send-tutor");
    if (sendTutor) sendTutor.onclick = sendDraftToTutor;
    var fold = document.getElementById("btn-fold");
    if (fold) {
      fold.onclick = function () {
        state.explainOpen = !state.explainOpen;
        render();
      };
    }
    var newer = document.getElementById("btn-new-tutor");
    if (newer) newer.onclick = startBlankTutor;
    var back = document.getElementById("btn-tutor-back");
    if (back) back.onclick = backFromTutor;
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
      composerInput.oninput = function () {
        state.tutorDraft = composerInput.value;
      };
    }
    el.root.querySelectorAll("[data-fill-msg]").forEach(function (btn) {
      btn.onclick = function () {
        var idx = parseInt(btn.getAttribute("data-fill-msg"), 10);
        var msgs = threadOf(state.tutorThreadId);
        var m = msgs[idx];
        if (m) fillFromTutor(m.text);
      };
    });
    el.tabs.querySelectorAll("[data-tab]").forEach(function (btn) {
      btn.onclick = function () {
        var id = btn.getAttribute("data-tab");
        if (id === "settings") openSettings();
        else if (id === "tutor") askTutor();
        else if (state.screen === "feedback" && state.lastResult) {
          state.screen = "feedback";
          render();
        } else {
          state.screen = "practice";
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
          if (err) err.remove();
        }
        paintDraftPreview();
      };
    }
  }

  function boot() {
    if (!FqmConfig.isConfigured(cfg)) {
      state.screen = "settings";
      state.error = "首次使用请填写练习台 Token 与学员编号。DeepSeek Key 现在不用填。";
      render();
      return;
    }
    loadBootstrapThenPick();
  }

  boot();
})();
