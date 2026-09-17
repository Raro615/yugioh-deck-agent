"""
효과 분석 데이터 모델.

검색 계층(:mod:`core.card_search`)은 "이 카드가 조건에 맞는가"를 판단한다.
이 계층은 한 단계 더 들어가 "이 효과가 무엇을, 어디에서, 어디로, 어떤 비용으로
옮기는가"를 구조화한다. 나중에 콤보를 탐색하려면 이 전이 정보가 필요하다.

설계 원칙
---------
1. **기존 Lua 파싱 결과를 재사용한다.** :class:`~core.card_model.EffectSpec` 이
   이미 효과 블록 단위로 묶어 둔 정보를 출발점으로 쓴다.
2. **추론하지 않는다.** 스크립트에서 읽어낼 수 없는 것은 비워 두거나
   ``unparsed`` 에 원문 그대로 남긴다. 그럴듯한 값을 지어내지 않는다.
3. **원본을 버리지 않는다.** 모든 분석 결과는 ``raw`` 로 원래 효과 블록을 가리킨다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.card_model import EffectSpec


class ActionKind(str, Enum):
    """효과가 실제로 하는 일. Lua 의 ``Duel.*`` 호출에서 유도한다."""

    SPECIAL_SUMMON = "special_summon"
    NORMAL_SUMMON = "normal_summon"
    TO_HAND = "to_hand"
    """패로 보낸다. 덱에서 가져오면 서치가 된다."""
    TO_GRAVE = "to_grave"
    TO_DECK = "to_deck"
    BANISH = "banish"
    DESTROY = "destroy"
    DRAW = "draw"
    DISCARD = "discard"
    RELEASE = "release"
    NEGATE = "negate"
    DAMAGE = "damage"
    RECOVER = "recover"
    POSITION = "position"
    EQUIP = "equip"
    TOKEN = "token"
    CONTROL = "control"
    ATK_DEF_CHANGE = "atk_def_change"
    UNKNOWN = "unknown"
    """무엇을 하는지 구조화하지 못했다. ``raw`` 에 원문이 남는다."""


#: 액션이 카드를 어디로 옮기는지. 이동이 아니면 ``None``.
ACTION_DESTINATION: dict[ActionKind, str | None] = {
    ActionKind.SPECIAL_SUMMON: "MZONE",
    ActionKind.NORMAL_SUMMON: "MZONE",
    ActionKind.TO_HAND: "HAND",
    ActionKind.TO_GRAVE: "GRAVE",
    ActionKind.TO_DECK: "DECK",
    ActionKind.BANISH: "REMOVED",
    ActionKind.DESTROY: "GRAVE",
    ActionKind.DRAW: "HAND",
    ActionKind.DISCARD: "GRAVE",
    ActionKind.RELEASE: "GRAVE",
    ActionKind.EQUIP: "SZONE",
    ActionKind.TOKEN: "MZONE",
}


class CostKind(str, Enum):
    """발동 비용."""

    SELF_BANISH = "self_banish"
    SELF_DISCARD = "self_discard"
    SELF_TRIBUTE = "self_tribute"
    SELF_TO_GRAVE = "self_to_grave"
    SELF_TO_DECK = "self_to_deck"
    SELF_TO_HAND = "self_to_hand"
    SELF_TO_EXTRA = "self_to_extra"
    SELF_REVEAL = "self_reveal"
    DETACH = "detach"
    """엑시즈 소재를 뗀다."""
    DISCARD = "discard"
    RELEASE = "release"
    PAY_LP = "pay_lp"
    SEND_DECK_TO_GRAVE = "send_deck_to_grave"
    BANISH = "banish"
    UNKNOWN = "unknown"
    """비용이 있다는 것만 알고 내용은 구조화하지 못했다."""


@dataclass(slots=True)
class CardConstraint:
    """
    '어떤 카드'인지를 나타내는 조건. Lua 필터 함수의 ``Card.Is*`` 호출에서 읽는다.

    모든 필드는 선택적이다. 읽어내지 못한 조건은 :attr:`raw_predicates` 에
    원문 그대로 남는다.
    """

    races: list[int] = field(default_factory=list)
    attributes: list[int] = field(default_factory=list)
    levels: list[int] = field(default_factory=list)
    level_max: int | None = None
    level_min: int | None = None
    card_types: list[str] = field(default_factory=list)
    """TYPE_* 상수 이름 (접두사 제외). 예: ['MONSTER', 'TUNER']"""
    setcodes: list[str] = field(default_factory=list)
    """SET_* 카드군 이름 (접두사 제외). 예: ['ORCUST']"""
    card_codes: list[int] = field(default_factory=list)
    """특정 카드 ID 지정."""
    excluded_card_codes: list[int] = field(default_factory=list)
    """``not c:IsCode(id)`` 처럼 제외되는 카드 ID."""
    raw_predicates: list[str] = field(default_factory=list)
    """구조화하지 못한 조건 원문."""

    def is_empty(self) -> bool:
        return not any(
            (
                self.races,
                self.attributes,
                self.levels,
                self.level_max is not None,
                self.level_min is not None,
                self.card_types,
                self.setcodes,
                self.card_codes,
            )
        )

    def describe_ko(self) -> str:
        from core import constants as C

        parts: list[str] = []
        for bit in self.races:
            parts.append(f"{C.RACE_KO.get(bit, '?')}족")
        for bit in self.attributes:
            parts.append(f"{C.ATTRIBUTE_KO.get(bit, '?')}속성")
        if self.levels:
            parts.append("레벨 " + "/".join(str(v) for v in self.levels))
        if self.level_max is not None:
            parts.append(f"레벨 {self.level_max} 이하")
        if self.level_min is not None:
            parts.append(f"레벨 {self.level_min} 이상")
        for name in self.setcodes:
            parts.append(f"{name} 카드군")
        for code in self.card_codes:
            parts.append(f"카드 {code}")
        parts.extend(self.card_types)
        return ", ".join(parts) if parts else "(조건 미상)"


@dataclass(slots=True)
class EffectCost:
    kind: CostKind
    raw: str
    """Lua 원문 (``Cost.SelfBanish``, 함수 이름 등)."""
    constraint: CardConstraint | None = None


@dataclass(slots=True)
class EffectSelection:
    """
    효과가 고르는 카드. 대상 지정(target)일 수도, 단순 선택일 수도 있다.

    유희왕 규칙에서 '대상으로 한다'와 '고른다'는 다르므로 구분한다.
    대상 지정 여부는 :attr:`EffectAnalysis.targets_card` 가 가진다.
    """

    locations: list[str] = field(default_factory=list)
    """LOCATION_* 이름 (접두사 제외). 어디에서 고르는가."""
    constraint: CardConstraint = field(default_factory=CardConstraint)
    min_count: int | None = None
    max_count: int | None = None
    raw: str = ""


@dataclass(slots=True)
class EffectAction:
    """효과가 일으키는 하나의 처리."""

    kind: ActionKind
    from_locations: list[str] = field(default_factory=list)
    to_location: str | None = None
    constraint: CardConstraint | None = None
    raw: str = ""
    """유도 근거가 된 Lua 호출."""


@dataclass(slots=True)
class EffectAnalysis:
    """효과 블록 하나의 구조화 결과."""

    index: str
    raw: EffectSpec
    """원본 효과 블록. 분석이 놓친 정보는 여기에 그대로 있다."""

    effect_types: list[str] = field(default_factory=list)
    trigger_event: str | None = None
    """SetCode 가 EVENT_* 이면 그 값. 아니면 ``None``."""
    effect_code: str | None = None
    """SetCode 가 EFFECT_* 이면 그 값."""
    activation_locations: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)

    targets_card: bool = False
    """EFFECT_FLAG_CARD_TARGET — 규칙상 '대상으로 지정'한다."""
    once_per_turn: bool = False
    count_limit_raw: str | None = None
    has_condition: bool = False
    """SetCondition 이 걸려 있는가 (내용은 별도)."""
    condition_raw: str | None = None

    costs: list[EffectCost] = field(default_factory=list)
    selection: EffectSelection | None = None
    actions: list[EffectAction] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    """구조화하지 못한 Lua 호출 원문."""

    is_summon_procedure: bool = False
    """소환 절차(EFFECT_SPSUMMON_PROC 등). 발동하는 효과가 아니다."""
    is_registered: bool = True
    """``s.initial_effect`` 에서 카드에 등록된 효과인가.

    처리 함수 안에서 만들어지는 효과(예: "이 턴 어둠 속성 이외를 특수 소환할 수
    없다")는 카드가 가진 효과가 아니라 해결 중에 적용되는 제약이다. 콤보 탐색이
    "이 카드가 무엇을 할 수 있는가"를 볼 때 섞이면 안 되므로 따로 둔다."""

    def has_action(self, kind: ActionKind) -> bool:
        return any(a.kind is kind for a in self.actions)

    def describe_ko(self) -> str:
        bits: list[str] = []
        if self.activation_locations:
            bits.append("/".join(self.activation_locations) + "에서")
        if self.costs:
            bits.append("비용 " + "/".join(c.kind.value for c in self.costs))
        if self.selection and self.selection.locations:
            where = "/".join(self.selection.locations)
            bits.append(f"{where}의 {self.selection.constraint.describe_ko()} 선택")
        for action in self.actions:
            label = action.kind.value
            if action.to_location:
                label += f"→{action.to_location}"
            bits.append(label)
        if self.once_per_turn:
            bits.append("턴 1회")
        return " · ".join(bits) if bits else "(구조화 안 됨)"


@dataclass(slots=True)
class CardAnalysis:
    """카드 한 장의 분석 결과."""

    card_id: int
    has_script: bool = False
    effects: list[EffectAnalysis] = field(default_factory=list)
    """카드에 등록된 효과."""
    resolution_effects: list[EffectAnalysis] = field(default_factory=list)
    """효과 처리 중에 생성되는 효과(적용 제약 등)."""
    listed_card_codes: list[int] = field(default_factory=list)
    """카드 텍스트가 이름으로 지명하는 카드 ID."""
    listed_series: list[str] = field(default_factory=list)
    """카드 텍스트가 지명하는 카드군."""
    setcodes: list[str] = field(default_factory=list)
    """공식 DB 기준 소속 카드군 (지명과 구분된다)."""
    unparsed_calls: list[str] = field(default_factory=list)
    """어떤 효과에도 붙이지 못한 Lua 호출."""

    def coverage(self) -> dict[str, float]:
        """분석이 얼마나 구조화했는지. 한계를 숨기지 않기 위한 값이다."""
        total = len(self.effects)
        with_actions = sum(1 for e in self.effects if e.actions)
        with_costs = sum(1 for e in self.effects if e.costs)
        with_selection = sum(1 for e in self.effects if e.selection)
        return {
            "effects": total,
            "with_actions": with_actions,
            "with_costs": with_costs,
            "with_selection": with_selection,
            "resolution_effects": len(self.resolution_effects),
            "unparsed_calls": len(self.unparsed_calls),
            "action_ratio": (with_actions / total) if total else 0.0,
        }
