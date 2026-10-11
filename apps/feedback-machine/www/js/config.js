(function (global) {
  "use strict";

  var STORAGE_KEY = "fqm_settings_v1";

  var DEFAULTS = {
    deepseekApiKey: "",
    deepseekBaseUrl: "",
    practiceBaseUrl: "https://practice.longee.icu",
    practiceToken: "",
    learnerId: "04022300566420984205"
  };

  function load() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return Object.assign({}, DEFAULTS);
      var parsed = JSON.parse(raw);
      return Object.assign({}, DEFAULTS, parsed || {});
    } catch (e) {
      return Object.assign({}, DEFAULTS);
    }
  }

  function save(partial) {
    var next = Object.assign(load(), partial || {});
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    return next;
  }

  function isConfigured(cfg) {
    cfg = cfg || load();
    return !!(
      (cfg.practiceBaseUrl || "").trim() &&
      (cfg.learnerId || "").trim() &&
      (cfg.practiceToken || "").trim()
    );
  }

  global.FqmConfig = {
    STORAGE_KEY: STORAGE_KEY,
    DEFAULTS: DEFAULTS,
    load: load,
    save: save,
    isConfigured: isConfigured
  };
})(typeof window !== "undefined" ? window : globalThis);
