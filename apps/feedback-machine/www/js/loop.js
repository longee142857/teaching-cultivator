(function (global) {
  "use strict";

  /** Distinct from network failures. DeepSeek Key is not part of this check. */
  var TOKEN_INVALID_MESSAGE =
    "Token 无效（401）。请到设置把 Practice API Token 改成与练习台 PRACTICE_API_TOKEN 相同的值。";

  function isUnauthorized(data) {
    if (!data) return false;
    if (Number(data.httpStatus) === 401) return true;
    return String(data.error || "").toLowerCase() === "unauthorized";
  }

  function failureMessage(data, fallback) {
    if (isUnauthorized(data)) return TOKEN_INVALID_MESSAGE;
    var err = data && (data.error || data.detail);
    if (err) return String(err);
    return fallback || "请求失败";
  }

  /**
   * Empty-slot bank refill.
   * math is the generic default. review is a real slot and may refill.
   * An empty comm slot must not call kind=comm.
   */
  function bankKind(kind) {
    if (kind === "comm") return null;
    if (kind === "review") return "review";
    return "math";
  }

  function rememberKind(lastKind, itemKind) {
    if (itemKind === "math" || itemKind === "review") return itemKind;
    if (lastKind === "review") return "review";
    return "math";
  }

  /** Next unanswered item in list order, including review and already-pushed comm. */
  function pickNextLocal(items, currentId) {
    var list = items || [];
    var start = 0;
    var i;
    if (currentId) {
      for (i = 0; i < list.length; i++) {
        if (list[i] && list[i].id === currentId) {
          start = i + 1;
          break;
        }
      }
    }
    for (i = start; i < list.length; i++) {
      if (list[i] && !list[i].answered) return list[i];
    }
    if (!currentId) return null;
    for (i = 0; i < start - 1; i++) {
      if (list[i] && !list[i].answered) return list[i];
    }
    return null;
  }

  function parseSse(text) {
    var src = String(text || "");
    if (src.indexOf("data:") < 0) return null;
    var events = [];
    var evt = "";
    var dataLines = [];
    function flush() {
      if (!dataLines.length) {
        evt = "";
        return;
      }
      var payload = dataLines.join("\n");
      dataLines = [];
      var data;
      try {
        data = JSON.parse(payload);
      } catch (e) {
        data = { text: payload };
      }
      events.push({ event: evt || "message", data: data });
      evt = "";
    }
    src.split(/\r?\n/).forEach(function (line) {
      if (!line.trim()) {
        flush();
        return;
      }
      if (line.indexOf("event:") === 0) evt = line.slice(6).trim();
      else if (line.indexOf("data:") === 0) dataLines.push(line.slice(5).replace(/^ /, ""));
    });
    flush();
    return events.length ? events : null;
  }

  function listTutorSessions(recents, threads, items) {
    var seen = {};
    var out = [];
    function add(id, title) {
      id = String(id || "");
      if (!id || seen[id]) return;
      seen[id] = true;
      out.push({ id: id, title: title || id, general: isGeneralThread(id) });
    }
    (recents || []).forEach(function (r) {
      if (r && r.id) add(r.id, r.title);
    });
    Object.keys(threads || {}).forEach(function (id) {
      add(id, isGeneralThread(id) ? "新对话" : id);
    });
    (items || []).forEach(function (it) {
      if (!it || !it.id) return;
      add(it.id, (it.subject ? it.subject + " · " : "") + (it.title || it.id));
    });
    return out;
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

  function applyImmediateSubmit(state, data, item) {
    state.lastResult = data.result;
    if (data.item) state.current = data.item;
    else if (item && !state.current) state.current = item;
    var id = (state.current && state.current.id) || (item && item.id);
    if (state.current) state.current.answered = true;
    var items = state.items || [];
    var i;
    for (i = 0; i < items.length; i++) {
      if (items[i] && id && items[i].id === id) items[i].answered = true;
    }
    state.screen = "feedback";
    state.busy = false;
    state.error = "";
    state.explainOpen = false;
    return state;
  }

  function shouldPollAfterSubmit(data) {
    if (!data) return true;
    if (isUnauthorized(data)) return false;
    if (gradeStillRunning(data)) return true;
    if (data.ok && resultReady(data)) return false;
    var st = Number(data.httpStatus || 0);
    if (st === 401 || st === 403 || st === 400) return false;
    if (st >= 500 || st === 408 || st === 504 || st === 0) return true;
    if (data.ok === false) return false;
    if (data.okHttp === false) return true;
    return false;
  }

  function routeSubmit(state, data, item) {
    if (isUnauthorized(data)) {
      state.busy = false;
      state.error = TOKEN_INVALID_MESSAGE;
      state.screen = "settings";
      return "unauthorized";
    }
    if (data && data.ok && resultReady(data) && !gradeStillRunning(data)) {
      applyImmediateSubmit(state, data, item);
      return "feedback";
    }
    if (shouldPollAfterSubmit(data)) return "poll";
    state.busy = false;
    state.error = failureMessage(data, "提交失败，请稍后重试。");
    return "error";
  }

  function isGeneralThread(id) {
    var s = String(id == null ? "" : id);
    return !s || s === "general" || /^general-\d+$/.test(s);
  }

  /**
   * Drop TLS / certifi paths from a grade comment. Legacy API rows stored
   * the raw exception after 「LLM 不可用：」.
   */
  function studentGradeComment(text) {
    var raw = String(text || "");
    var leaked = /（\s*LLM\s*不可用：|cacert\.pem|Could not find a suitable TLS|invalid path:|llm_failed:/i.test(raw);
    var s = raw.replace(/（\s*LLM\s*不可用：[\s\S]*?）/g, "");
    s = s.replace(/Could not find a suitable TLS CA certificate bundle[^\n）]*/gi, "");
    s = s.replace(/invalid path:\s*\S+/gi, "");
    s = s.replace(/\/[^\s）]*cacert\.pem/gi, "");
    s = s.replace(/\s*llm_failed:\S*/gi, "");
    s = s.replace(/[ \t]{2,}/g, " ").trim();
    if (leaked && s.indexOf("LLM 暂不可用") < 0 && s.indexOf("正式评分") < 0) {
      s = (s ? s + " " : "") + "讲师暂时无法批改，以上为参考答案初判，不是正式评分。";
    }
    return s;
  }

  function gradeBanner(result) {
    var r = result || {};
    var ok = !!r.correct;
    var partial = !ok && !!r.partial;
    if (r.gradeMode === "ref_fallback" && !partial) {
      if (ok) {
        return { cls: "ok", text: "初判通过", sub: "参考答案初判为一致，不是正式评分" };
      }
      return { cls: "warn", text: "初判未对齐", sub: "讲师暂时无法批改，不是正式评分" };
    }
    return {
      cls: ok ? "ok" : partial ? "warn" : "bad",
      text: ok ? "通过" : partial ? "部分通过" : "未通过",
      sub: ok ? "作答正确" : partial ? "部分正确" : "作答不正确"
    };
  }

  /** Foreground refetch of today's slots. Skip while a submit is in flight. */
  function shouldRefreshToday(state) {
    if (!state || state.busy || state.polling) return false;
    if (state.screen === "settings" || state.screen === "loading") return false;
    return true;
  }

  function tutorReplyText(pack, asked) {
    pack = pack || {};
    if (isUnauthorized(pack)) return TOKEN_INVALID_MESSAGE;
    if (Number(pack.httpStatus) === 501 || pack.error === "tutor_agent_not_wired") {
      return "讲师暂时连不上。你刚才问：「" + String(asked || "") + "」。";
    }
    if (pack.reply && Number(pack.httpStatus || 200) < 500) return String(pack.reply);
    var err = pack.error || pack.detail || pack.hint || "";
    if (err) return String(err);
    return "讲师服务暂时不可用" + (pack.httpStatus ? "（" + pack.httpStatus + "）" : "") + "。";
  }

  global.FqmLoop = {
    TOKEN_INVALID_MESSAGE: TOKEN_INVALID_MESSAGE,
    isUnauthorized: isUnauthorized,
    failureMessage: failureMessage,
    bankKind: bankKind,
    rememberKind: rememberKind,
    pickNextLocal: pickNextLocal,
    parseSse: parseSse,
    listTutorSessions: listTutorSessions,
    gradeStillRunning: gradeStillRunning,
    resultReady: resultReady,
    applyImmediateSubmit: applyImmediateSubmit,
    shouldPollAfterSubmit: shouldPollAfterSubmit,
    routeSubmit: routeSubmit,
    studentGradeComment: studentGradeComment,
    gradeBanner: gradeBanner,
    shouldRefreshToday: shouldRefreshToday,
    isGeneralThread: isGeneralThread,
    tutorReplyText: tutorReplyText
  };
})(typeof window !== "undefined" ? window : globalThis);
