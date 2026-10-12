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
   * Bank refill and「再出一题」stay on math.
   * comm stock is thin; review is not the recording/default path either.
   * A stored lastKind of comm/review must not win.
   */
  function bankKind(lastKind) {
    if (lastKind === "math") return "math";
    return "math";
  }

  function rememberKind(lastKind, itemKind) {
    if (itemKind === "math") return "math";
    return bankKind(lastKind);
  }

  /** Next local item for the default loop: unanswered math only (missing kind counts). */
  function pickNextLocal(items, currentId) {
    var list = items || [];
    var i, it;
    for (i = 0; i < list.length; i++) {
      it = list[i];
      if (!it || it.answered) continue;
      if (it.kind && it.kind !== "math") continue;
      if (currentId && it.id === currentId) continue;
      return it;
    }
    return null;
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
    gradeStillRunning: gradeStillRunning,
    resultReady: resultReady,
    applyImmediateSubmit: applyImmediateSubmit,
    shouldPollAfterSubmit: shouldPollAfterSubmit,
    routeSubmit: routeSubmit,
    isGeneralThread: isGeneralThread,
    tutorReplyText: tutorReplyText
  };
})(typeof window !== "undefined" ? window : globalThis);
