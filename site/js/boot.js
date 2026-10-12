/* Apply saved language and skin before CSS paints. */
(function () {
  var style = "desk";
  var lang = "zh";
  try {
    var params = new URLSearchParams(location.search);
    var queryStyle = params.get("style");
    var queryLang = params.get("lang");
    var savedStyle = localStorage.getItem("tc-style");
    var savedLang = localStorage.getItem("tc-lang");
    if (queryStyle === "studio" || queryStyle === "desk") style = queryStyle;
    else if (savedStyle === "studio" || savedStyle === "desk") style = savedStyle;
    if (queryLang === "en" || queryLang === "zh") lang = queryLang;
    else if (savedLang === "en" || savedLang === "zh") lang = savedLang;
    if (queryStyle === "studio" || queryStyle === "desk") localStorage.setItem("tc-style", style);
    if (queryLang === "en" || queryLang === "zh") localStorage.setItem("tc-lang", lang);
  } catch (err) {
    /* private mode or a non-browser environment */
  }
  var root = document.documentElement;
  root.setAttribute("data-style", style);
  root.lang = lang === "en" ? "en" : "zh-CN";
})();
