"""能力模型量化：统一 LearnerParams（BKT L2 + 域 η + 选题信号）。

两层能力，禁止混用：

1. **L2 BKT**（``mastery``）—— 练习选题 / 复查 / 批改写回的粒度主键
2. **域潜特质 η**（``eta``）—— {calc,linalg,prob} 上的 IRT MAP；供事件预测与跨 KP 量化

红线（对齐 capability-prob）：
- 不得把单一 BKT mastery 标量直接当作事件成功概率
- η̂ 在题参 (a,d) 未标定前仅有相对序意义
"""
from __future__ import annotations

from .params import (
    DOMAIN_NAMES,
    AbilitySignal,
    DomainEta,
    ItemIrtParams,
    LearnerParams,
    MasteryEntry,
    ParamAssumptions,
    default_assumptions,
)
from .domain_map import DOMAINS, load_kp_l1_map, map_kp_to_domain
from .latent import LatentResult, estimate_latent, irt_mle
from .evidence import (
    ADAPTER_ASSUMPTIONS,
    attempts_to_bundle,
    bundle_from_store,
    difficulty_to_d,
)
from .irt import build_irt_meta, merge_irt_into_meta
from .service import (
    CapabilityService,
    build_learner_params,
    estimate_eta_for_learner,
    refresh_after_grade,
)
from .select import (
    PickContext,
    domain_boost_for_kp,
    eta_map_from_params,
    pick_best_item,
    rank_kps,
    score_kp_need,
    score_ready_item,
    weak_domain_boosts,
    weighted_choice_kp,
)

__all__ = [
    "ADAPTER_ASSUMPTIONS",
    "AbilitySignal",
    "CapabilityService",
    "DOMAIN_NAMES",
    "DOMAINS",
    "DomainEta",
    "ItemIrtParams",
    "LatentResult",
    "LearnerParams",
    "MasteryEntry",
    "ParamAssumptions",
    "PickContext",
    "attempts_to_bundle",
    "build_irt_meta",
    "build_learner_params",
    "bundle_from_store",
    "default_assumptions",
    "difficulty_to_d",
    "domain_boost_for_kp",
    "estimate_eta_for_learner",
    "estimate_latent",
    "eta_map_from_params",
    "irt_mle",
    "load_kp_l1_map",
    "map_kp_to_domain",
    "merge_irt_into_meta",
    "pick_best_item",
    "rank_kps",
    "refresh_after_grade",
    "score_kp_need",
    "score_ready_item",
    "weak_domain_boosts",
    "weighted_choice_kp",
]
