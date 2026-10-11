(function (global) {
  "use strict";

  function baseUrl(cfg) {
    return String((cfg && cfg.practiceBaseUrl) || "").replace(/\/+$/, "");
  }

  function headers(cfg, extra) {
    var h = { Accept: "application/json" };
    if (extra) {
      Object.keys(extra).forEach(function (k) {
        h[k] = extra[k];
      });
    }
    var tok = (cfg && cfg.practiceToken) || "";
    if (tok) {
      h.Authorization = "Bearer " + tok;
      h["X-Practice-Token"] = tok;
    }
    if (cfg && cfg.learnerId) h["X-Learner-Id"] = cfg.learnerId;
    return h;
  }

  function url(cfg, path) {
    var u = baseUrl(cfg) + path;
    var tok = (cfg && cfg.practiceToken) || "";
    if (!tok) return u;
    return u + (u.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(tok);
  }

  function request(cfg, path, opts) {
    opts = opts || {};
    var init = {
      method: opts.method || "GET",
      headers: headers(cfg, opts.headers)
    };
    if (opts.body !== undefined) init.body = opts.body;
    return fetch(url(cfg, path), init).then(function (r) {
      return r.text().then(function (t) {
        var j = null;
        try {
          j = t ? JSON.parse(t) : null;
        } catch (e) {
          j = { ok: false, error: "bad_json", raw: t.slice(0, 200) };
        }
        return { okHttp: r.ok, status: r.status, body: j };
      });
    });
  }

  function bootstrap(cfg, day) {
    var q =
      "/api/v1/practice/bootstrap?learner=" + encodeURIComponent(cfg.learnerId);
    if (day) q += "&day=" + encodeURIComponent(day);
    return request(cfg, q).then(function (p) {
      return p.body;
    });
  }

  function getItem(cfg, params) {
    params = params || {};
    var q = "/api/v1/practice/item?learner=" + encodeURIComponent(cfg.learnerId);
    if (params.item) q += "&item=" + encodeURIComponent(params.item);
    if (params.push != null && params.push !== "") {
      q += "&push=" + encodeURIComponent(String(params.push));
    }
    if (params.kind) q += "&kind=" + encodeURIComponent(params.kind);
    return request(cfg, q).then(function (p) {
      return p.body;
    });
  }

  function submit(cfg, payload) {
    return request(cfg, "/api/v1/practice/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (p) {
      return Object.assign({ httpStatus: p.status, okHttp: p.okHttp }, p.body || {});
    });
  }

  global.FqmApi = {
    bootstrap: bootstrap,
    getItem: getItem,
    submit: submit,
    request: request
  };
})(typeof window !== "undefined" ? window : globalThis);
