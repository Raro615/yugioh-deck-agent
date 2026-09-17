"""
카드 효과 분석 및 관계 계층.

검색 계층(:mod:`core.card_search`)과 독립적이다. 이 계층은 카드를 읽기만 하며
검색 동작을 바꾸지 않는다.
"""

from analysis.effect_model import (
    ACTION_DESTINATION,
    ActionKind,
    ActivationCondition,
    ActivationLimit,
    ActivationRequirement,
    ConditionKind,
    LimitScope,
    PipelineStage,
    CardAnalysis,
    CardConstraint,
    CostKind,
    EffectAction,
    EffectAnalysis,
    EffectCost,
    EffectSelection,
)
from analysis.effect_analyzer import EffectAnalyzer
from analysis.relationship import (
    MEMBERSHIP_KINDS,
    CardRelationship,
    RelationshipBuilder,
    RelationshipKind,
)

__all__ = [
    "ACTION_DESTINATION",
    "ActionKind",
    "ActivationCondition",
    "ActivationLimit",
    "ActivationRequirement",
    "ConditionKind",
    "LimitScope",
    "PipelineStage",
    "CardAnalysis",
    "CardConstraint",
    "CostKind",
    "EffectAction",
    "EffectAnalysis",
    "EffectAnalyzer",
    "EffectCost",
    "EffectSelection",
    "MEMBERSHIP_KINDS",
    "CardRelationship",
    "RelationshipBuilder",
    "RelationshipKind",
]
