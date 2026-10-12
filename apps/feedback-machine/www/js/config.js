(function (global) {
  "use strict";

  var STORAGE_KEY = "fqm_settings_v1";

  var DEFAULTS = {
    deepseekApiKey: "",
    deepseekBaseUrl: "",
    practiceBaseUrl: "https://practice.longee.icu",
    practiceToken: "",
    learnerId: "04022300566420984205",
    updateManifestUrl: ""
  };

  /** Fallback when Capacitor App.getInfo is unavailable. Keep equal to android/app/build.gradle. */
  var APP_VERSION_CODE = 2;
  var APP_VERSION_NAME = "1.0.1";
  var APP_PACKAGE = "icu.longee.feedback";
  var DEFAULT_UPDATE_URL = "https://practice.longee.icu/app/feedback-machine/version.json";

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

  function safeHttpUrl(url) {
    var u = String(url || "").trim();
    if (!/^https?:\/\//i.test(u)) return "";
    return u;
  }

  function updateManifestUrl(cfg) {
    cfg = cfg || load();
    var custom = safeHttpUrl(cfg && cfg.updateManifestUrl);
    if (custom) return custom;
    return DEFAULT_UPDATE_URL;
  }

  function interpretUpdate(localCode, body) {
    body = body || {};
    var empty = {
      phase: "error",
      message: "检查失败，不影响做题",
      apkUrl: "",
      notes: "",
      apkMd5: "",
      remoteName: "",
      remoteCode: null
    };
    if (body.okHttp === false) return empty;
    if (body.package && String(body.package) !== APP_PACKAGE) {
      return {
        phase: "error",
        message: "清单不是这个应用",
        apkUrl: "",
        notes: "",
        apkMd5: "",
        remoteName: "",
        remoteCode: null
      };
    }
    var remote = parseInt(body.versionCode, 10);
    var local = parseInt(localCode, 10);
    var minCode = parseInt(body.minVersionCode, 10);
    if (!isFinite(remote) || !isFinite(local)) return empty;
    var notes = body.releaseNotes ? String(body.releaseNotes) : "";
    var md5 = body.apkMd5 ? String(body.apkMd5) : "";
    var name = body.versionName ? String(body.versionName) : "";
    var belowMin = isFinite(minCode) && local < minCode;
    if (remote > local || belowMin) {
      var apk = safeHttpUrl(body.apkUrl);
      if (!apk) {
        return {
          phase: "error",
          message: "有新版本，但清单里没有下载地址",
          apkUrl: "",
          notes: notes,
          apkMd5: md5,
          remoteName: name,
          remoteCode: remote
        };
      }
      return {
        phase: "available",
        message: name ? "有新版本 " + name : "有新版本",
        apkUrl: apk,
        notes: notes,
        apkMd5: md5,
        remoteName: name,
        remoteCode: remote
      };
    }
    return {
      phase: "current",
      message: "已是最新版本",
      apkUrl: "",
      notes: notes,
      apkMd5: md5,
      remoteName: name,
      remoteCode: remote
    };
  }

  global.FqmConfig = {
    STORAGE_KEY: STORAGE_KEY,
    DEFAULTS: DEFAULTS,
    APP_VERSION_CODE: APP_VERSION_CODE,
    APP_VERSION_NAME: APP_VERSION_NAME,
    APP_PACKAGE: APP_PACKAGE,
    DEFAULT_UPDATE_URL: DEFAULT_UPDATE_URL,
    load: load,
    save: save,
    isConfigured: isConfigured,
    safeHttpUrl: safeHttpUrl,
    updateManifestUrl: updateManifestUrl,
    interpretUpdate: interpretUpdate
  };
})(typeof window !== "undefined" ? window : globalThis);
