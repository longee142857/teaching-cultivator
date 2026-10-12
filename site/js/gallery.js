/* Gallery mock screens. Copy comes from TC.t so both skins stay in the active language. */
(function () {
  var SCREENS = ["queue", "answer", "feedback", "tutor", "notice", "shell"];

  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function t(key) {
    return esc(window.TC.t(key));
  }

  function tabs(active) {
    var items = [
      ["practice", "mock.tabPractice"],
      ["exam", "mock.tabExam"],
      ["notes", "mock.tabNotes"],
      ["tutor", "mock.tabTutor"]
    ];
    var html = '<nav class="tabs">';
    for (var i = 0; i < items.length; i++) {
      html += '<span class="' + (items[i][0] === active ? "is-on" : "") + '">' + t(items[i][1]) + "</span>";
    }
    return html + "</nav>";
  }

  function top(titleKey) {
    return '<header class="device-top"><strong>' + t(titleKey) + '</strong><span class="ribbon">' + t("mock.ribbon") + "</span></header>";
  }

  function slot(index, subject, when, kp, state) {
    return (
      '<li class="slot"><span class="idx">' + index + "</span><div><div class=\"slot-title\"><b>" +
      t(subject) + "</b> · " + t(when) + '</div><div class="slot-kp">' + t(kp) +
      '</div></div><em class="state">' + t(state) + "</em></li>"
    );
  }

  function screenHtml(id) {
    if (id === "answer") {
      return (
        '<article class="device">' + top("mock.appName") +
        '<p class="kicker">' + t("mock.stemEyebrow") + "</p>" +
        '<h3 class="stem-title">' + t("mock.stemTitle") + "</h3>" +
        '<div class="stem"><p>' + t("mock.stemMath") + "</p></div>" +
        '<p class="fake-input">' + t("mock.answerHint") + "</p>" +
        '<button type="button" class="mock-btn" data-demo="submit">' + t("mock.submit") + "</button>" +
        '<button type="button" class="mock-link" data-demo="ask">' + t("mock.ask") + "</button>" +
        tabs("practice") + "</article>"
      );
    }
    if (id === "feedback") {
      return (
        '<article class="device">' + top("mock.appName") +
        '<p class="kicker">' + t("mock.partial") + "</p>" +
        '<ol class="steps-mini"><li>' + t("mock.step1") + "</li><li>" + t("mock.step2") + "</li></ol>" +
        '<div class="mastery"><div class="bar" aria-hidden="true"><i></i></div><p>' + t("mock.mastery") + "</p><p class=\"fine\">" + t("mock.masteryNote") + "</p></div>" +
        '<button type="button" class="mock-btn" data-demo="next">' + t("mock.next") + "</button>" +
        tabs("practice") + "</article>"
      );
    }
    if (id === "tutor") {
      return (
        '<article class="device">' + top("mock.appName") +
        '<div class="bubble tutor"><span class="who">' + t("mock.tutor") + "</span><p>" + t("mock.tutor1") + "</p></div>" +
        '<div class="bubble user"><span class="who">' + t("mock.you") + "</span><p>" + t("mock.user1") + "</p></div>" +
        '<div class="bubble tutor"><span class="who">' + t("mock.tutor") + "</span><p>" + t("mock.tutor2") + "</p></div>" +
        '<p class="fake-input">' + t("mock.askMore") + "</p>" +
        tabs("tutor") + "</article>"
      );
    }
    if (id === "notice") {
      return (
        '<article class="device">' + top("mock.noticeKicker") +
        '<div class="notice"><p class="kicker">' + t("mock.ribbon") + "</p><h3 class=\"stem-title\">" + t("mock.noticeTitle") + "</h3><p>" + t("mock.noticeBody") + "</p>" +
        '<button type="button" class="mock-btn" data-demo="open">' + t("mock.openDesk") + "</button>" +
        '<p class="fine">' + t("mock.noId") + "</p></div></article>"
      );
    }
    if (id === "shell") {
      return (
        '<article class="device">' + top("mock.shellName") +
        '<p class="loop">' + t("mock.loop") + "</p>" +
        '<p class="kicker">' + t("mock.stemCommEyebrow") + "</p>" +
        '<div class="stem"><p>' + t("mock.stemComm") + "</p></div>" +
        '<p class="chip">' + t("mock.chip") + "</p>" +
        '<button type="button" class="mock-btn" data-demo="next">' + t("mock.next") + "</button>" +
        '<p class="fine">' + t("mock.shellHint") + "</p>" +
        tabs("practice") + "</article>"
      );
    }
    return (
      '<article class="device">' + top("mock.appName") +
      '<p class="device-sub">' + t("mock.today") + "</p>" +
      '<ul class="slots">' +
      slot("01", "mock.math", "mock.morning", "mock.kpLimit", "mock.open") +
      slot("02", "mock.comm", "mock.afternoon", "mock.kpBase", "mock.open") +
      slot("03", "mock.review", "mock.evening", "mock.kpReview", "mock.live") +
      "</ul><p class=\"fine\">" + t("mock.hintQueue") + "</p>" +
      tabs("practice") + "</article>"
    );
  }

  function column(style) {
    var name = style === "desk" ? t("style.desk") : t("style.studio");
    var stage = document.getElementById("gallery-stage");
    var id = (stage && stage.getAttribute("data-screen")) || "queue";
    return (
      '<div class="skin-col" data-style="' + style + '"><p class="skin-kicker">' + name +
      '</p><div class="skin" data-style="' + style + '">' + screenHtml(id) + "</div></div>"
    );
  }

  function render() {
    var stage = document.getElementById("gallery-stage");
    if (!stage || !window.TC) return;
    var screen = stage.getAttribute("data-screen") || "queue";
    var layout = stage.getAttribute("data-layout") || "pair";
    stage.innerHTML = column("desk") + column("studio");
    var tabsBtns = document.querySelectorAll(".screen-tabs [data-screen]");
    for (var i = 0; i < tabsBtns.length; i++) {
      var on = tabsBtns[i].getAttribute("data-screen") === screen;
      tabsBtns[i].setAttribute("aria-selected", on ? "true" : "false");
      tabsBtns[i].classList.toggle("is-on", on);
    }
    var layoutBtns = document.querySelectorAll(".gallery-tools [data-layout]");
    for (var j = 0; j < layoutBtns.length; j++) {
      var layoutOn = layoutBtns[j].getAttribute("data-layout") === layout;
      layoutBtns[j].setAttribute("aria-pressed", layoutOn ? "true" : "false");
      layoutBtns[j].classList.toggle("is-on", layoutOn);
    }
  }

  function persist(key, value) {
    try { sessionStorage.setItem(key, value); } catch (err) { /* ignore */ }
  }

  function init() {
    var stage = document.getElementById("gallery-stage");
    if (!stage) return;
    var hash = (location.hash || "").replace(/^#/, "");
    var saved = "";
    var savedLayout = "";
    try {
      saved = sessionStorage.getItem("tc-screen") || "";
      savedLayout = sessionStorage.getItem("tc-layout") || "";
    } catch (err) { /* ignore */ }
    var screen = SCREENS.indexOf(hash) >= 0 ? hash : (SCREENS.indexOf(saved) >= 0 ? saved : "queue");
    var layout = savedLayout === "focus" || savedLayout === "pair" ? savedLayout : "pair";
    stage.setAttribute("data-screen", screen);
    stage.setAttribute("data-layout", layout);
    render();
  }

  document.addEventListener("click", function (ev) {
    var stage = document.getElementById("gallery-stage");
    if (!stage) return;
    var screenBtn = ev.target.closest(".screen-tabs [data-screen]");
    if (screenBtn && SCREENS.indexOf(screenBtn.getAttribute("data-screen")) >= 0) {
      var id = screenBtn.getAttribute("data-screen");
      stage.setAttribute("data-screen", id);
      persist("tc-screen", id);
      if (history.replaceState) history.replaceState(null, "", "#" + id);
      render();
      return;
    }
    var layoutBtn = ev.target.closest(".gallery-tools [data-layout]");
    if (layoutBtn) {
      var layout = layoutBtn.getAttribute("data-layout");
      if (layout !== "pair" && layout !== "focus") return;
      stage.setAttribute("data-layout", layout);
      persist("tc-layout", layout);
      render();
    }
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
    var tab = ev.target.closest(".screen-tabs [data-screen]");
    if (!tab) return;
    var stage = document.getElementById("gallery-stage");
    if (!stage) return;
    var index = SCREENS.indexOf(tab.getAttribute("data-screen"));
    if (index < 0) return;
    var next = ev.key === "ArrowRight" ? (index + 1) % SCREENS.length : (index - 1 + SCREENS.length) % SCREENS.length;
    var id = SCREENS[next];
    stage.setAttribute("data-screen", id);
    persist("tc-screen", id);
    if (history.replaceState) history.replaceState(null, "", "#" + id);
    render();
    var buttons = document.querySelectorAll("[data-screen]");
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i].getAttribute("data-screen") === id) buttons[i].focus();
    }
    ev.preventDefault();
  });

  document.addEventListener("tc:lang", render);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
