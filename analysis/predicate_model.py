"""
조건 leaf 의 의미 모델.

조건 트리는 논리 구조(AND/OR/NOT)를 보존하지만, leaf 안의 Lua 술어가 무슨
뜻인지는 별개 문제다. 이 모듈은 leaf 를 세 상태로 나눈다.

1. :attr:`EvalReadiness.EVALUABLE`
   필드/패/묘지/턴/페이즈 같은 게임 상태만으로 판정할 수 있다.
2. :attr:`EvalReadiness.NEEDS_CONTEXT`
   술어와 인자는 읽었지만, 체인이나 직전 이벤트 문맥이 있어야 판정할 수 있다.
   "구조를 못 읽었다"와 반드시 구분해야 한다.
3. :attr:`EvalReadiness.UNKNOWN`
   안전하게 해석할 수 없다. 원문만 보존한다.

술어 이름만 보고 게임 의미를 추측하지 않는다. 주체(subject) 역시 EDOPro 가
콜백 서명으로 보장하는 이름(``e``, ``eg``, ``re``, ``tp`` …)에서만 판정하고,
스크립트가 임의로 붙인 지역 변수는 :attr:`PredicateSubject.LOCAL` 로 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from analysis.effect_model import CardConstraint


class PredicateKind(str, Enum):
    """조건 leaf 가 무엇을 묻는가."""

    # --- 카드 자체의 성질 (CardConstraint 로 연결) ---
    CARD_PROPERTY = "card_property"
    """종족/속성/레벨/카드 종류/카드명 등."""
    CARD_LOCATION = "card_location"
    CARD_POSITION = "card_position"
    CARD_CONTROLLER = "card_controller"

    # --- 직전 상태 (이벤트 문맥 필요) ---
    PREVIOUS_LOCATION = "previous_location"
    PREVIOUS_POSITION = "previous_position"
    PREVIOUS_CONTROLLER = "previous_controller"

    # --- 존재·수량 ---
    CARD_EXISTS = "card_exists"
    """Duel.IsExistingMatchingCard — 필드/묘지 상태 질의."""
    GROUP_EXISTS = "group_exists"
    """이벤트 그룹 안에 조건을 만족하는 카드가 있는가."""
    GROUP_CONTAINS = "group_contains"
    ZONE_COUNT = "zone_count"
    CARD_COUNT = "card_count"

    # --- 턴 진행 ---
    TURN_PLAYER = "turn_player"
    PHASE = "phase"
    LIFE_POINTS = "life_points"
    FIELD_SPELL = "field_spell"
    """Duel.IsEnvironment — 특정 필드 마법이 적용 중인가."""

    # --- 체인·이벤트 문맥 ---
    CHAIN_EFFECT_TYPE = "chain_effect_type"
    """re:IsMonsterEffect / IsTrapEffect / IsHasType 등."""
    CHAIN_STATE = "chain_state"
    EVENT_REASON = "event_reason"
    BATTLE = "battle"
    CARD_STATUS = "card_status"
    FLAG_EFFECT = "flag_effect"
    SUMMON_TYPE = "summon_type"
    PLAYER_AFFECTED = "player_affected"
    PLAYER_COMPARISON = "player_comparison"
    """rp==tp / ep==1-tp 처럼 엔진이 넘겨준 플레이어끼리 비교한다.
    누가 발동했는지는 체인 문맥이 있어야 정해진다."""

    UNKNOWN = "unknown"


class EvalReadiness(str, Enum):
    """평가 가능성. 구조화 여부와 별개다."""

    EVALUABLE = "evaluable"
    NEEDS_CONTEXT = "needs_context"
    UNKNOWN = "unknown"


class PredicateSubject(str, Enum):
    """
    누구에 대한 질문인가.

    EDOPro 의 효과 콜백 서명 ``(e,tp,eg,ep,ev,re,r,rp)`` 와 ``c`` 는 엔진이
    의미를 보장하므로 판정에 쓴다. 그 밖의 이름은 추측하지 않는다.
    """

    SELF = "self"
    """효과를 가진 카드 자신 (``c``, ``e:GetHandler()``)."""
    EFFECT = "effect"
    """효과 객체 ``e``."""
    EVENT_GROUP = "event_group"
    """직전 이벤트의 카드 묶음 ``eg``."""
    CHAIN_EFFECT = "chain_effect"
    """체인 상대의 효과 ``re``."""
    CHAIN_CARD = "chain_card"
    """체인 상대 효과의 카드 ``re:GetHandler()``."""
    PLAYER = "player"
    DUEL = "duel"
    """``Duel.*`` — 듀얼 전체 상태."""
    LOCAL = "local"
    """스크립트 지역 변수. 무엇을 가리키는지 확정할 수 없다."""


#: 술어 종류별 평가 가능성. 게임 상태 스냅숏만으로 판정되는지가 기준이다.
READINESS_BY_KIND: dict[PredicateKind, EvalReadiness] = {
    PredicateKind.CARD_PROPERTY: EvalReadiness.EVALUABLE,
    PredicateKind.CARD_LOCATION: EvalReadiness.EVALUABLE,
    PredicateKind.CARD_POSITION: EvalReadiness.EVALUABLE,
    PredicateKind.CARD_CONTROLLER: EvalReadiness.EVALUABLE,
    PredicateKind.CARD_EXISTS: EvalReadiness.EVALUABLE,
    PredicateKind.ZONE_COUNT: EvalReadiness.EVALUABLE,
    PredicateKind.CARD_COUNT: EvalReadiness.EVALUABLE,
    PredicateKind.TURN_PLAYER: EvalReadiness.EVALUABLE,
    PredicateKind.PHASE: EvalReadiness.EVALUABLE,
    PredicateKind.LIFE_POINTS: EvalReadiness.EVALUABLE,
    PredicateKind.FIELD_SPELL: EvalReadiness.EVALUABLE,
    # 아래는 구조는 읽었지만 체인/이벤트 문맥이 있어야 판정할 수 있다.
    PredicateKind.PREVIOUS_LOCATION: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.PREVIOUS_POSITION: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.PREVIOUS_CONTROLLER: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.GROUP_EXISTS: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.GROUP_CONTAINS: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.CHAIN_EFFECT_TYPE: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.CHAIN_STATE: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.EVENT_REASON: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.BATTLE: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.CARD_STATUS: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.FLAG_EFFECT: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.SUMMON_TYPE: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.PLAYER_AFFECTED: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.PLAYER_COMPARISON: EvalReadiness.NEEDS_CONTEXT,
    PredicateKind.UNKNOWN: EvalReadiness.UNKNOWN,
}


@dataclass(slots=True)
class ConditionPredicate:
    """조건 leaf 하나의 의미."""

    kind: PredicateKind = PredicateKind.UNKNOWN
    readiness: EvalReadiness = EvalReadiness.UNKNOWN
    subject: PredicateSubject = PredicateSubject.LOCAL
    constraint: CardConstraint | None = None
    """카드 성질 조건. 검색 계층과 같은 :class:`CardConstraint` 를 쓴다."""
    locations: list[str] = field(default_factory=list)
    player: str | None = None
    value: int | None = None
    comparison: str | None = None
    """``>`` ``>=`` ``==`` 등. 수량/레벨 비교일 때만 채워진다."""
    negated: bool = False
    raw: str = ""
    """Lua 원문. 어떤 경우에도 버리지 않는다."""

    @property
    def is_evaluable(self) -> bool:
        return self.readiness is EvalReadiness.EVALUABLE

    def describe_ko(self) -> str:
        subject_ko = {
            PredicateSubject.SELF: "자신 카드",
            PredicateSubject.EVENT_GROUP: "이벤트 카드",
            PredicateSubject.CHAIN_EFFECT: "체인 효과",
            PredicateSubject.CHAIN_CARD: "체인 카드",
            PredicateSubject.DUEL: "듀얼",
            PredicateSubject.PLAYER: "플레이어",
            PredicateSubject.EFFECT: "효과",
            PredicateSubject.LOCAL: "",
        }.get(self.subject, "")
        parts = [p for p in (subject_ko, self.kind.value) if p]
        if self.constraint is not None and not self.constraint.is_empty():
            parts.append(self.constraint.describe_ko())
        if self.locations:
            parts.append("/".join(self.locations))
        if self.comparison and self.value is not None:
            parts.append(f"{self.comparison}{self.value}")
        text = " ".join(parts)
        return ("아님: " if self.negated else "") + text
