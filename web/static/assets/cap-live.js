// Live overlay: fill η̂ / BKT from VPS practice_web (same-origin).
// Event P̂ / paths stay mock until capability-prob event engine is hosted.
(function () {
  function learnerFromPage() {
    try {
      const q = new URLSearchParams(window.location.search || "");
      const fromQ = (q.get("learner") || "").trim();
      if (fromQ) return fromQ;
    } catch (e) {}
    try {
      const raw = localStorage.getItem("teaching-shell-v2-state");
      if (raw) {
        const s = JSON.parse(raw);
        if (s && s.learner) return String(s.learner);
      }
    } catch (e) {}
    return (window.MOCK && window.MOCK.learner_id) || "stu_1024";
  }

  function mapEta(raw) {
    const out = {};
    if (!raw) return { calc: 0, linalg: 0, prob: 0 };
    if (Array.isArray(raw)) {
      raw.forEach(function (e) {
        if (!e || e.domain == null) return;
        out[String(e.domain)] = Number(e.eta != null ? e.eta : 0);
      });
      return out;
    }
    if (typeof raw === "object") {
      Object.keys(raw).forEach(function (k) {
        const v = raw[k];
        if (typeof v === "number") out[k] = v;
        else if (v && typeof v === "object") out[k] = Number(v.eta != null ? v.eta : 0);
      });
    }
    return out;
  }

  function mapBkt(mastery, weak) {
    const rows = [];
    if (Array.isArray(mastery) && mastery.length) {
      mastery.forEach(function (w) {
        if (!w) return;
        const kp = w.kp || w.knowledge_point || w.id;
        const p = Number(w.p != null ? w.p : w.p_mastery);
        if (!kp || Number.isNaN(p)) return;
        rows.push({ kp: String(kp), p_mastery: p, slot: w.slot || w.domain || "—", domain: w.domain || null });
      });
    } else if (mastery && typeof mastery === "object") {
      Object.keys(mastery).forEach(function (kp) {
        const v = mastery[kp];
        const p = typeof v === "number" ? v : Number(v && (v.p_mastery != null ? v.p_mastery : v.p));
        if (Number.isNaN(p)) return;
        rows.push({ kp: kp, p_mastery: p, slot: (v && v.domain) || "—", domain: (v && v.domain) || null });
      });
    }
    rows.sort(function (a, b) { return a.p_mastery - b.p_mastery; });
    if (rows.length) return rows.slice(0, 24);
    return (weak || []).map(function (w) {
      return { kp: w.kp, p_mastery: Number(w.p || 0), slot: "weak", domain: null };
    });
  }

  window.loadLiveCapability = async function loadLiveCapability() {
    const learner = learnerFromPage();
    const r = await fetch("/api/v1/practice/params?learner=" + encodeURIComponent(learner), {
      headers: { "X-Learner-Id": learner },
    });
    const d = await r.json();
    if (!(d && d.ok)) throw new Error((d && d.error) || ("params http " + r.status));
    const p = d.params || {};
    const summary = d.summary || {};
    window.MOCK.learner_id = d.learner || learner;
    window.MOCK.snapshot_id = "ability_snapshots.live";
    window.MOCK.source = "practice_web → LearnerParams (VPS)";
    window.MOCK.eta_hat = mapEta(p.eta || summary.eta || {});
    window.MOCK.eta_note = "域 η 来自 VPS teaching.db / ability_snapshots（相对序）";
    window.MOCK.bkt_l2 = mapBkt(p.mastery, summary.masteryWeak);
    const liveAssumptions = Array.isArray(p.assumptions) ? p.assumptions.slice(0, 10) : [];
    window.MOCK.assumptions = [
      "η̂ / BKT 已接 VPS practice/params（learner=" + window.MOCK.learner_id + "）",
      "事件目录可切换；P̂ / 路径仍为本地 DAG mock",
      "BKT 最多展示 24 个 KP（按掌握度升序）",
    ].concat(liveAssumptions);
    return window.MOCK;
  };
})();
