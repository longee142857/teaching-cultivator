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
    if (typeof j === "string") {
      var t = j.trim();
      if (t.charAt(0) === "{" || t.charAt(0) === "[") j = parseBody(t);
      else j = j;
    } else if (j == null) j = null;
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

  function withMeta(p) {
    var body = p && p.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      body = {
        ok: false,
        error: p && p.okHttp ? "empty" : "http_" + ((p && p.status) || 0)
      };
    } else {
      body = Object.assign({}, body);
    }
    body.httpStatus = p ? p.status : 0;
    body.okHttp = !!(p && p.okHttp);
    return body;
  }

  /** Public JSON (version manifest). No practice token — static file, CapacitorHttp on device. */
  function getAbsolute(fullUrl) {
    var reqOpts = {
      method: "GET",
      headers: { Accept: "application/json" }
    };
    var http = capacitorHttpPlugin();
    if (http) return requestViaCapacitor(http, fullUrl, reqOpts).then(withMeta);
    return requestViaFetch(fullUrl, reqOpts).then(withMeta);
  }

  function bootstrap(cfg, day) {
    var q =
      "/api/v1/practice/bootstrap?learner=" + encodeURIComponent(cfg.learnerId);
    if (day) q += "&day=" + encodeURIComponent(day);
    return request(cfg, q).then(withMeta);
  }

  function getItem(cfg, params) {
    params = params || {};
    var q = "/api/v1/practice/item?learner=" + encodeURIComponent(cfg.learnerId);
    if (params.item) q += "&item=" + encodeURIComponent(params.item);
    if (params.push != null && params.push !== "") {
      q += "&push=" + encodeURIComponent(String(params.push));
    }
    if (params.kind) q += "&kind=" + encodeURIComponent(params.kind);
    return request(cfg, q).then(withMeta);
  }

  function submit(cfg, payload) {
    return request(cfg, "/api/v1/practice/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(withMeta);
  }

  /**
   * Tutor chat. Accept includes text/event-stream so practice_web proxies SSE.
   * CapacitorHttp returns the finished body (no chunk callback); the shell replays
   * those events as the typing stream. Browser fetch reads the stream live.
   */
  function tutorChat(cfg, payload, onEvent) {
    var fullUrl = url(cfg, "/api/v1/tutor/chat");
    var reqOpts = {
      method: "POST",
      headers: headers(cfg, {
        "Content-Type": "application/json",
        Accept: "text/event-stream, application/json"
      }),
      body: JSON.stringify(payload || {})
    };
    var http = capacitorHttpPlugin();
    var pending = http
      ? requestViaCapacitor(http, fullUrl, reqOpts)
      : requestViaFetchStream(fullUrl, reqOpts, onEvent);
    return pending.then(function (p) {
      if (p && p.streamed) return p;
      if (p && typeof p.body === "string") {
        return { httpStatus: p.status, okHttp: p.okHttp, sseText: p.body };
      }
      return withMeta(p);
    });
  }

  function requestViaFetchStream(fullUrl, opts, onEvent) {
    var init = {
      method: opts.method || "GET",
      headers: opts.headers || {}
    };
    if (opts.body !== undefined) init.body = opts.body;
    return fetch(fullUrl, init).then(function (r) {
      var ct = (r.headers && r.headers.get && r.headers.get("content-type")) || "";
      if (ct.indexOf("text/event-stream") >= 0 && r.body && r.body.getReader) {
        return readSse(r, onEvent).then(function (events) {
          return { okHttp: r.ok, status: r.status, streamed: true, sse: true, events: events };
        });
      }
      return r.text().then(function (t) {
        return { okHttp: r.ok, status: r.status, body: parseBody(t) };
      });
    });
  }

  function readSse(response, onEvent) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buf = "";
    var events = [];
    var evt = "";
    function handleLine(line) {
      line = String(line || "").replace(/\r$/, "");
      if (line.indexOf("event:") === 0) {
        evt = line.slice(6).trim();
        return;
      }
      if (line.indexOf("data:") !== 0) {
        if (!line.trim()) evt = "";
        return;
      }
      var payload = line.slice(5).trim();
      if (!payload) return;
      var data;
      try {
        data = JSON.parse(payload);
      } catch (e) {
        data = { text: payload };
      }
      var ev = { event: evt || "message", data: data };
      events.push(ev);
      evt = "";
      if (onEvent) onEvent(ev);
    }
    function pump() {
      return reader.read().then(function (step) {
        if (step.done) {
          if (buf) handleLine(buf);
          return events;
        }
        buf += decoder.decode(step.value, { stream: true });
        var idx;
        while ((idx = buf.indexOf("\n")) >= 0) {
          handleLine(buf.slice(0, idx));
          buf = buf.slice(idx + 1);
        }
        return pump();
      });
    }
    return pump();
  }

  function ocr(cfg, payload) {
    return request(cfg, "/api/v1/practice/ocr", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {})
    }).then(withMeta);
  }

  function reportPoor(cfg, payload) {
    return request(cfg, "/api/v1/practice/report-poor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {})
    }).then(withMeta);
  }

  function examPapers(cfg) {
    return request(cfg, "/api/v1/exam/papers").then(withMeta);
  }


  global.FqmApi = {
    getAbsolute: getAbsolute,
    bootstrap: bootstrap,
    getItem: getItem,
    submit: submit,
    tutorChat: tutorChat,
    ocr: ocr,
    reportPoor: reportPoor,
    examPapers: examPapers,
    request: request,
    /** @internal smoke / diagnostics */
    transport: function () {
      return capacitorHttpPlugin() ? "capacitor-http" : "fetch";
    }
  };
})(typeof window !== "undefined" ? window : globalThis);
