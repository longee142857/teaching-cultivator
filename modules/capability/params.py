"""核心参数契约（LearnerParams）。

teaching 选题写回用 BKT；跨域量化与 capability-prob 事件预测用 η。
本模块只定义数据结构与默认假设，不触达 IM / 通知。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


DOMAIN_NAMES = ("calc", "linalg", "prob")


@dataclass(frozen=True)
class ParamAssumptions:
    """诚实边界：任何对外快照都应带上。"""

    irt_calibrated: bool = False
    eta_is_ordinal_only: bool = True
    bkt_not_event_prob: bool = True
    notes: tuple[str, ...] = ()

    def to_list(self) -> list[str]:
        out = [
            "BKT mastery 不直接作为事件成功概率",
        ]
        if not self.irt_calibrated:
            out.append("题参未标定：默认 a=1.0，d 由 difficulty 粗映射")
        if self.eta_is_ordinal_only:
            out.append("η̂ 仅相对序有意义（未联合标定前）")
        out.extend(self.notes)
        return out


def default_assumptions(*, notes: tuple[str, ...] = ()) -> ParamAssumptions:
    return ParamAssumptions(notes=notes)


@dataclass
class ItemIrtParams:
    """单题 IRT 参数（写入 items.meta 或未来列）。"""

    a: float = 1.0
    d: float = 0.0
    domain: Optional[str] = None
    source: str = "default"  # default | difficulty_map | calibrated

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MasteryEntry:
    """L2 粒度 BKT 快照。"""

    kp: str
    p_mastery: float
    opportunity_count: int = 0
    is_mastered: bool = False
    due: bool = False
    domain: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DomainEta:
    """域级潜特质。"""

    domain: str
    eta: float
    n_items: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AbilitySignal:
    """选题用能力目标（recognize/compute/…），非 η。"""

    goal: str
    item_form: str = ""
    subject: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LearnerParams:
    """统一能力参数快照。

    - ``mastery``：练习闭环权威（L2）
    - ``eta``：域量化 + 导出给 capability-prob
    - ``ability``：当前轮 ability_goal（可选）
    """

    learner_id: str
    mastery: list[MasteryEntry] = field(default_factory=list)
    eta: list[DomainEta] = field(default_factory=list)
    ability: Optional[AbilitySignal] = None
    assumptions: ParamAssumptions = field(default_factory=default_assumptions)
    meta: dict[str, Any] = field(default_factory=dict)

    def eta_by_domain(self) -> dict[str, float]:
        return {e.domain: e.eta for e in self.eta}

    def mastery_by_kp(self) -> dict[str, float]:
        return {m.kp: m.p_mastery for m in self.mastery}

    def weak_kps(self, *, threshold: float = 0.6, limit: int = 10) -> list[str]:
        ranked = sorted(self.mastery, key=lambda m: m.p_mastery)
        out = [m.kp for m in ranked if m.p_mastery < threshold]
        return out[:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "learner_id": self.learner_id,
            "mastery": [m.to_dict() for m in self.mastery],
            "eta": [e.to_dict() for e in self.eta],
            "ability": self.ability.to_dict() if self.ability else None,
            "assumptions": self.assumptions.to_list(),
            "meta": dict(self.meta),
        }

    def to_evidence_bundle(self) -> dict[str, Any]:
        """供 capability-prob ``predict`` 的瘦包装：仅 η 不够，需完整 items。

        完整 EvidenceBundle 请用 ``evidence.attempts_to_bundle``；
        此处只暴露已估 η，避免误把 mastery 当证据。
        """
        return {
            "learner_id": self.learner_id,
            "eta_hat": [e.eta for e in self.eta],
            "domains": [e.domain for e in self.eta],
            "assumptions": self.assumptions.to_list(),
        }
