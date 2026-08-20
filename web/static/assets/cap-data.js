// 事件目录 + 默认快照（P̂/路径为本地 DAG mock；η/BKT 会被 VPS live 覆盖）
window.GATE_LABEL = {
  calc_mastery_gate: "微积分掌握",
  linalg_mastery_gate: "线代掌握",
  prob_mastery_gate: "概率掌握",
  timed_mock_pass: "限时模拟通过",
  biweekly_math_gate: "双周数学卷",
  biweekly_comm_gate: "双周通信卷",
  daily_three_slots: "今日三槽完成",
  weak_kp_lift: "最弱 KP 回升",
  ofdm_unit_gate: "OFDM 单元",
  nyquist_isi_gate: "奈奎斯特/ISI",
  modulation_gate: "调制阶 / MASK·MPSK",
  midterm_calc_gate: "微积分阶段测",
  review_catchup: "错题复盘清零",
  streak_7d: "7 日连做",
};

window.DOMAIN_LABEL = {
  calc: "微积分",
  linalg: "线代",
  prob: "概率",
  comm: "通信",
  signals: "信号",
};

window.EVENTS = [
  {
    id: "grad_exam_math_pass",
    title: "考研数学通过",
    blurb: "条件于 calc / linalg / prob η̂",
    domains: ["calc", "linalg", "prob"],
    p_hat: 0.342,
    ci: [0.281, 0.408],
    n_paths: 12,
    top_paths: [
      { passed_gates: ["calc_mastery_gate", "linalg_mastery_gate"], failed_gates: ["prob_mastery_gate"], freq: 0.214 },
      { passed_gates: ["calc_mastery_gate"], failed_gates: ["linalg_mastery_gate", "prob_mastery_gate"], freq: 0.187 },
      { passed_gates: ["calc_mastery_gate", "linalg_mastery_gate", "prob_mastery_gate"], failed_gates: ["timed_mock_pass"], freq: 0.142 },
      { passed_gates: ["linalg_mastery_gate"], failed_gates: ["calc_mastery_gate", "prob_mastery_gate"], freq: 0.098 },
      { passed_gates: ["calc_mastery_gate", "prob_mastery_gate"], failed_gates: ["linalg_mastery_gate"], freq: 0.086 },
    ],
    bottlenecks: [
      { node: "prob_mastery_gate", when_fail: 412, share: 0.381 },
      { node: "timed_mock_pass", when_fail: 298, share: 0.276 },
      { node: "linalg_mastery_gate", when_fail: 186, share: 0.172 },
      { node: "calc_mastery_gate", when_fail: 94, share: 0.087 },
    ],
  },
  {
    id: "biweekly_math_pass",
    title: "双周数学卷及格",
    blurb: "对齐 exam_web 数学卷门槛",
    domains: ["calc", "linalg"],
    p_hat: 0.518,
    ci: [0.451, 0.584],
    n_paths: 10,
    top_paths: [
      { passed_gates: ["calc_mastery_gate", "biweekly_math_gate"], failed_gates: [], freq: 0.268 },
      { passed_gates: ["calc_mastery_gate"], failed_gates: ["biweekly_math_gate"], freq: 0.201 },
      { passed_gates: ["linalg_mastery_gate", "biweekly_math_gate"], failed_gates: ["calc_mastery_gate"], freq: 0.155 },
      { passed_gates: ["calc_mastery_gate", "linalg_mastery_gate"], failed_gates: ["timed_mock_pass"], freq: 0.122 },
      { passed_gates: ["review_catchup"], failed_gates: ["biweekly_math_gate"], freq: 0.091 },
    ],
    bottlenecks: [
      { node: "biweekly_math_gate", when_fail: 340, share: 0.332 },
      { node: "calc_mastery_gate", when_fail: 220, share: 0.215 },
      { node: "timed_mock_pass", when_fail: 168, share: 0.164 },
      { node: "review_catchup", when_fail: 112, share: 0.109 },
    ],
  },
  {
    id: "biweekly_comm_pass",
    title: "双周通信卷及格",
    blurb: "通信槽为主；数学域仅作对照",
    domains: ["comm", "signals", "linalg"],
    p_hat: 0.447,
    ci: [0.381, 0.514],
    n_paths: 11,
    top_paths: [
      { passed_gates: ["nyquist_isi_gate", "modulation_gate"], failed_gates: ["ofdm_unit_gate"], freq: 0.231 },
      { passed_gates: ["modulation_gate", "biweekly_comm_gate"], failed_gates: [], freq: 0.198 },
      { passed_gates: ["nyquist_isi_gate"], failed_gates: ["modulation_gate", "biweekly_comm_gate"], freq: 0.164 },
      { passed_gates: ["ofdm_unit_gate"], failed_gates: ["nyquist_isi_gate"], freq: 0.121 },
      { passed_gates: ["modulation_gate"], failed_gates: ["ofdm_unit_gate", "biweekly_comm_gate"], freq: 0.088 },
    ],
    bottlenecks: [
      { node: "ofdm_unit_gate", when_fail: 305, share: 0.298 },
      { node: "nyquist_isi_gate", when_fail: 248, share: 0.242 },
      { node: "biweekly_comm_gate", when_fail: 190, share: 0.186 },
      { node: "modulation_gate", when_fail: 132, share: 0.129 },
    ],
  },
  {
    id: "daily_slot_streak",
    title: "今日三槽连续完成",
    blurb: "练习台 morning / afternoon / evening",
    domains: ["calc", "comm", "prob"],
    p_hat: 0.612,
    ci: [0.548, 0.672],
    n_paths: 9,
    top_paths: [
      { passed_gates: ["daily_three_slots", "streak_7d"], failed_gates: [], freq: 0.294 },
      { passed_gates: ["daily_three_slots"], failed_gates: ["streak_7d"], freq: 0.241 },
      { passed_gates: ["review_catchup", "daily_three_slots"], failed_gates: [], freq: 0.167 },
      { passed_gates: ["calc_mastery_gate"], failed_gates: ["daily_three_slots"], freq: 0.112 },
      { passed_gates: ["modulation_gate"], failed_gates: ["daily_three_slots"], freq: 0.079 },
    ],
    bottlenecks: [
      { node: "daily_three_slots", when_fail: 276, share: 0.301 },
      { node: "streak_7d", when_fail: 198, share: 0.216 },
      { node: "review_catchup", when_fail: 141, share: 0.154 },
      { node: "timed_mock_pass", when_fail: 96, share: 0.105 },
    ],
  },
  {
    id: "weak_kp_recover",
    title: "最弱 KP 回升至 0.60",
    blurb: "BKT 最低项抬升（练习选题目标）",
    domains: ["calc", "linalg", "prob", "comm"],
    p_hat: 0.389,
    ci: [0.328, 0.453],
    n_paths: 10,
    top_paths: [
      { passed_gates: ["weak_kp_lift", "review_catchup"], failed_gates: [], freq: 0.255 },
      { passed_gates: ["weak_kp_lift"], failed_gates: ["review_catchup"], freq: 0.208 },
      { passed_gates: ["calc_mastery_gate", "weak_kp_lift"], failed_gates: [], freq: 0.146 },
      { passed_gates: ["nyquist_isi_gate", "weak_kp_lift"], failed_gates: [], freq: 0.119 },
      { passed_gates: ["review_catchup"], failed_gates: ["weak_kp_lift"], freq: 0.094 },
    ],
    bottlenecks: [
      { node: "weak_kp_lift", when_fail: 388, share: 0.361 },
      { node: "review_catchup", when_fail: 210, share: 0.195 },
      { node: "prob_mastery_gate", when_fail: 154, share: 0.143 },
      { node: "ofdm_unit_gate", when_fail: 101, share: 0.094 },
    ],
  },
  {
    id: "midterm_calc_pass",
    title: "微积分阶段测通过",
    blurb: "偏 calc 域；线代作辅证",
    domains: ["calc"],
    p_hat: 0.571,
    ci: [0.509, 0.631],
    n_paths: 8,
    top_paths: [
      { passed_gates: ["midterm_calc_gate", "calc_mastery_gate"], failed_gates: [], freq: 0.312 },
      { passed_gates: ["calc_mastery_gate"], failed_gates: ["midterm_calc_gate"], freq: 0.224 },
      { passed_gates: ["midterm_calc_gate"], failed_gates: ["timed_mock_pass"], freq: 0.168 },
      { passed_gates: ["review_catchup", "midterm_calc_gate"], failed_gates: [], freq: 0.121 },
      { passed_gates: ["calc_mastery_gate", "timed_mock_pass"], failed_gates: ["midterm_calc_gate"], freq: 0.082 },
    ],
    bottlenecks: [
      { node: "midterm_calc_gate", when_fail: 290, share: 0.318 },
      { node: "calc_mastery_gate", when_fail: 205, share: 0.225 },
      { node: "timed_mock_pass", when_fail: 148, share: 0.162 },
      { node: "review_catchup", when_fail: 99, share: 0.109 },
    ],
  },
  {
    id: "ofdm_unit_ready",
    title: "OFDM 单元就绪",
    blurb: "通信进阶关卡（与双周卷解耦）",
    domains: ["comm", "signals"],
    p_hat: 0.296,
    ci: [0.241, 0.357],
    n_paths: 9,
    top_paths: [
      { passed_gates: ["nyquist_isi_gate", "modulation_gate"], failed_gates: ["ofdm_unit_gate"], freq: 0.278 },
      { passed_gates: ["ofdm_unit_gate"], failed_gates: [], freq: 0.166 },
      { passed_gates: ["modulation_gate"], failed_gates: ["ofdm_unit_gate", "nyquist_isi_gate"], freq: 0.151 },
      { passed_gates: ["nyquist_isi_gate"], failed_gates: ["ofdm_unit_gate"], freq: 0.134 },
      { passed_gates: ["biweekly_comm_gate"], failed_gates: ["ofdm_unit_gate"], freq: 0.097 },
    ],
    bottlenecks: [
      { node: "ofdm_unit_gate", when_fail: 456, share: 0.422 },
      { node: "nyquist_isi_gate", when_fail: 211, share: 0.195 },
      { node: "modulation_gate", when_fail: 167, share: 0.155 },
      { node: "biweekly_comm_gate", when_fail: 88, share: 0.081 },
    ],
  },
  {
    id: "nyquist_isi_clear",
    title: "奈奎斯特 / ISI 关卡通关",
    blurb: "对齐真实薄弱 KP：ISI与奈奎斯特准则",
    domains: ["comm", "signals"],
    p_hat: 0.463,
    ci: [0.401, 0.526],
    n_paths: 8,
    top_paths: [
      { passed_gates: ["nyquist_isi_gate"], failed_gates: [], freq: 0.301 },
      { passed_gates: ["nyquist_isi_gate", "modulation_gate"], failed_gates: [], freq: 0.214 },
      { passed_gates: ["modulation_gate"], failed_gates: ["nyquist_isi_gate"], freq: 0.172 },
      { passed_gates: ["weak_kp_lift", "nyquist_isi_gate"], failed_gates: [], freq: 0.128 },
      { passed_gates: ["review_catchup"], failed_gates: ["nyquist_isi_gate"], freq: 0.091 },
    ],
    bottlenecks: [
      { node: "nyquist_isi_gate", when_fail: 318, share: 0.341 },
      { node: "modulation_gate", when_fail: 176, share: 0.189 },
      { node: "weak_kp_lift", when_fail: 124, share: 0.133 },
      { node: "review_catchup", when_fail: 87, share: 0.093 },
    ],
  },
];

window.MOCK = {
  learner_id: "stu_1024",
  snapshot_id: "ability_snapshots.local.mock",
  source: "teaching.modules.capability",
  event_id: window.EVENTS[0].id,
  event_title: window.EVENTS[0].title,
  p_hat: window.EVENTS[0].p_hat,
  ci: window.EVENTS[0].ci.slice(),
  n_paths: window.EVENTS[0].n_paths,
  eta_hat: { calc: 0.124, linalg: -0.051, prob: -0.183, comm: 0.0 },
  eta_note: "域 IRT η 服务事件预测；切换事件会重算展示域集合",
  bkt_l2: [
    { kp: "极限 · 夹逼定理", p_mastery: 0.42, slot: "math", domain: "calc" },
    { kp: "导数 · 隐函数求导", p_mastery: 0.55, slot: "review", domain: "calc" },
    { kp: "矩阵与初等变换", p_mastery: 0.35, slot: "math", domain: "linalg" },
    { kp: "多元函数微分学", p_mastery: 0.43, slot: "math", domain: "calc" },
    { kp: "ISI与奈奎斯特准则", p_mastery: 0.69, slot: "comm", domain: "comm" },
    { kp: "M进制调制MASK/MPSK/MQAM", p_mastery: 0.47, slot: "comm", domain: "comm" },
    { kp: "OFDM基本原理", p_mastery: 0.20, slot: "comm", domain: "signals" },
    { kp: "信号与系统 · 卷积", p_mastery: 0.31, slot: "comm", domain: null },
  ],
  top_paths: window.EVENTS[0].top_paths,
  bottlenecks: window.EVENTS[0].bottlenecks,
  assumptions: [
    "BKT p_mastery 只用于练习选题 / 复查，禁止当作事件成功概率 P̂",
    "事件目录为本地 DAG mock；η̂ / BKT 可接 VPS practice/params",
    "不同事件吃不同域集合（见事件下拉的 domains）",
    "Wilson CI 未含 η 参数不确定性",
  ],
};

window.applyEventToMock = function applyEventToMock(eventId) {
  const ev = (window.EVENTS || []).find(function (e) { return e.id === eventId; }) || window.EVENTS[0];
  if (!ev || !window.MOCK) return ev;
  window.MOCK.event_id = ev.id;
  window.MOCK.event_title = ev.title;
  window.MOCK.event_blurb = ev.blurb || "";
  window.MOCK.event_domains = (ev.domains || []).slice();
  window.MOCK.p_hat = ev.p_hat;
  window.MOCK.ci = (ev.ci || [0, 0]).slice();
  window.MOCK.n_paths = ev.n_paths;
  window.MOCK.top_paths = (ev.top_paths || []).map(function (p) {
    return {
      passed_gates: (p.passed_gates || []).slice(),
      failed_gates: (p.failed_gates || []).slice(),
      freq: p.freq,
    };
  });
  window.MOCK.bottlenecks = (ev.bottlenecks || []).map(function (b) {
    return { node: b.node, when_fail: b.when_fail, share: b.share };
  });
  return ev;
};

window.applyEventToMock(window.EVENTS[0].id);
