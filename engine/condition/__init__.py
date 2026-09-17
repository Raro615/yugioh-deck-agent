"""
조건 계층 (Phase 2-B-1).

    GameState → GameStateView → ConditionEvaluator → ConditionVerdict

조건은 **질문이지 명령이 아니다.** 판을 읽고 ``TRUE`` / ``FALSE`` /
``UNKNOWN`` 을 돌려줄 뿐, 아무것도 바꾸지 않는다.

``analysis`` 의 조건 트리(:class:`~analysis.effect_model.ConditionNode`)와는
목적이 다르다. 그쪽은 **Lua 를 읽은 기록**(가변, 원문 보존, 평가기 없음)이고
이쪽은 **실행용**(불변, 원문 없음, 관측을 받아 판정)이다. 자세한 것은
``engine/condition/model.py`` 의 설명과 ``docs/phase2b1-condition.md``.

아직 없는 것: 체인 · 트리거 · 타이밍 · 소환 절차. 그것이 필요한 조건은
:class:`UnimplementedRule` 로 ``UNKNOWN`` 을 돌려주고 무엇이 없는지 밝힌다.
"""

from engine.condition.context import ConditionContext, PlayerRef
from engine.condition.evaluator import ConditionEvaluator, ConditionVerdict
from engine.condition.model import (
    Always,
    And,
    AttackAtLeast,
    AttributeIs,
    CardIsFaceUp,
    CardIsInZone,
    Condition,
    IsMonster,
    IsTurnPlayer,
    LevelAtLeast,
    LifePointsAtLeast,
    Not,
    Or,
    PhaseIs,
    UnimplementedRule,
    ZoneCountAtLeast,
    ZoneHasFreeSlot,
)
from engine.condition.result import ConditionResult

__all__ = [
    "ConditionResult",
    "ConditionContext",
    "PlayerRef",
    "Condition",
    "Always",
    "UnimplementedRule",
    "And",
    "Or",
    "Not",
    "PhaseIs",
    "IsTurnPlayer",
    "LifePointsAtLeast",
    "ZoneCountAtLeast",
    "ZoneHasFreeSlot",
    "CardIsInZone",
    "CardIsFaceUp",
    "IsMonster",
    "LevelAtLeast",
    "AttackAtLeast",
    "AttributeIs",
    "ConditionEvaluator",
    "ConditionVerdict",
]
