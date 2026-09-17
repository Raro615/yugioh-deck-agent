"""
비용과 선택 (Phase 2-C).

    CostGroup / Cost
          ↓  choice_spec()
    ChoiceSpec
          ↓  CandidateResolver(view).resolve(spec, context)
    CandidateSet          확실한 후보 · 판정 불가 · 왜 모르는가
          ↓  플레이어가 고른다  (이 계층 밖)
    Selection
          ↓  SelectionValidator(view).validate(spec, selection, context)
    ValidationResult

**아무것도 치르지 않고 아무것도 고르지 않는다.** 청구서를 읽고, 후보를 세고,
고른 것이 맞는지 볼 뿐이다.

지키는 구분
-----------
``Cost`` ≠ ``CostPayment`` · ``ChoiceSpec`` ≠ ``Selection`` ·
``CandidateSet`` ≠ ``Selection`` · 릴리스 ≠ 묘지로 보내기 ≠ 파괴.

자세한 것은 ``docs/phase2c-cost-choice.md``.
"""

from engine.cost.choice import CandidateSet, CandidateSource, ChoiceSpec, Selection
from engine.cost.model import (
    FIELD_MONSTER_ZONES,
    CardCost,
    Cost,
    CostGroup,
    CostSemantics,
    LifeCost,
    UnimplementedCost,
)
from engine.cost.resolver import CandidateResolver
from engine.cost.validation import CostValidator, SelectionValidator

__all__ = [
    "CostSemantics",
    "Cost",
    "CardCost",
    "LifeCost",
    "UnimplementedCost",
    "CostGroup",
    "FIELD_MONSTER_ZONES",
    "CandidateSource",
    "ChoiceSpec",
    "CandidateSet",
    "Selection",
    "CandidateResolver",
    "CostValidator",
    "SelectionValidator",
]
