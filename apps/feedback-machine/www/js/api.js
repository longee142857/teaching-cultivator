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

  function parseBody(text) {
    var j = null;
    try {
      j = text ? JSON.parse(text) : null;
    } catch (e) {
      j = { ok: false, error: "bad_json", raw: String(text || "").slice(0, 200) };
    }
    return j;
  }

  function normalizeHttpResult(status, data) {
    var j = data;
    if (typeof j === "string") j = parseBody(j);
    else if (j == null) j = null;
    var okHttp = status >= 200 && status < 300;
    return { okHttp: okHttp, status: status, body: j };
  }

  /** Native Capacitor HTTP — bypasses WebView CORS (Origin https://localhost). */
  function capacitorHttpPlugin() {
    try {
      var cap = global.Capacitor;
      if (!cap || !cap.isNativePlatform || !cap.isNativePlatform()) return null;
      return (cap.Plugins && cap.Plugins.CapacitorHttp) || null;
    } catch (e) {
      return null;
    }
  }

  function bodyForCapacitor(opts, rawBody) {
    if (rawBody === undefined || rawBody === null) return undefined;
    var ct = "";
    if (opts.headers) {
      Object.keys(opts.headers).forEach(function (k) {
        if (k.toLowerCase() === "content-type") ct = String(opts.headers[k] || "");
      });
    }
    if (ct.indexOf("application/json") >= 0 && typeof rawBody === "string") {
      try {
        return JSON.parse(rawBody);
      } catch (e) {
        return rawBody;
      }
    }
    return rawBody;
  }

  function requestViaCapacitor(http, fullUrl, opts) {
    var method = (opts.method || "GET").toUpperCase();
    var req = {
      url: fullUrl,
      method: method,
      headers: opts.headers || {}
    };
    var data = bodyForCapacitor(opts, opts.body);
    if (data !== undefined) req.data = data;
    return http.request(req).then(function (res) {
      return normalizeHttpResult(res.status || 0, res.data);
    });
  }

  function requestViaFetch(fullUrl, opts) {
    var init = {
      method: opts.method || "GET",
      headers: opts.headers || {}
    };
    if (opts.body !== undefined) init.body = opts.body;
    return fetch(fullUrl, init).then(function (r) {
      return r.text().then(function (t) {
        return { okHttp: r.ok, status: r.status, body: parseBody(t) };
      });
    });
  }

  function request(cfg, path, opts) {
    opts = opts || {};
    var fullUrl = url(cfg, path);
    var reqOpts = {
      method: opts.method || "GET",
      headers: headers(cfg, opts.headers),
      body: opts.body
    };
    var http = capacitorHttpPlugin();
    if (http) return requestViaCapacitor(http, fullUrl, reqOpts);
    return requestViaFetch(fullUrl, reqOpts);
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
    request: request,
    /** @internal smoke / diagnostics */
    transport: function () {
      return capacitorHttpPlugin() ? "capacitor-http" : "fetch";
    }
  };
})(typeof window !== "undefined" ? window : globalThis);
