// 本地模拟：对齐 teaching LearnerParams（BKT L2 + 域 η）
// 不写云端；结构贴近 modules.capability + EvidenceBundle
window.MOCK = {
  learner_id: "stu_1024",
  snapshot_id: "ability_snapshots.local.mock",
  source: "teaching.modules.capability",
  event_id: "grad_exam_math_pass",
  event_title: "考研数学通过（条件于 teaching η̂ 快照）",
  p_hat: 0.342,
  ci: [0.281, 0.408],
  n_paths: 8,
  eta_hat: { calc: 0.124, linalg: -0.051, prob: -0.183 },
  eta_note: "域 IRT η 只服务事件预测；通信槽 comm 不进本 DAG",
  bkt_l2: [
    { kp: "极限 · 夹逼定理", p_mastery: 0.42, slot: "math", domain: "calc" },
    { kp: "导数 · 隐函数求导", p_mastery: 0.55, slot: "review", domain: "calc" },
    { kp: "信号与系统 · 卷积", p_mastery: 0.31, slot: "comm", domain: null }
  ],
  top_paths: [
    {
      passed_gates: ["calc_mastery_gate", "linalg_mastery_gate"],
      failed_gates: ["prob_mastery_gate"],
      freq: 0.214
    },
    {
      passed_gates: ["calc_mastery_gate"],
      failed_gates: ["linalg_mastery_gate", "prob_mastery_gate"],
      freq: 0.187
    }
  ],
  bottlenecks: [
    { node: "prob_mastery_gate", when_fail: 412, share: 0.381 },
    { node: "timed_mock_pass", when_fail: 298, share: 0.276 }
  ],
  assumptions: [
    "BKT p_mastery 只用于练习选题 / 复查，禁止当作事件成功概率 P̂",
    "η̂ 为 teaching ability_snapshots 的 plug-in（learner=stu_1024，本地 mock）",
    "事件 DAG 来自 YAML；本事件只吃 calc / linalg / prob，comm 槽不进入",
    "Wilson CI 未含 η 参数不确定性 · 未写入云端"
  ]
};

window.GATE_LABEL = {
  calc_mastery_gate: "微积分掌握",
  linalg_mastery_gate: "线代掌握",
  prob_mastery_gate: "概率掌握",
  timed_mock_pass: "限时模拟通过"
};
