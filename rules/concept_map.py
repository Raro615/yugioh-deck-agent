"""
룰북 개념 <-> 엔진 개념 <-> 조건 술어(predicate) 연결표.

목적은 하나다. Duel Engine 이 조건을 판정하러 갈 때 **"이 판정의 근거가 룰북
어디에 있는가"** 를 즉시 찾을 수 있게 하는 것.

    Rule concept  ->  Engine concept  ->  Condition predicate
    "Chain"           ChainState          chain_state / chain_effect_type
    "Battle Phase"    Phase.BATTLE        phase / battle

**중요: 여기서 ConditionEvaluator 를 구현하지 않는다.** 이 모듈은 표일 뿐이고,
판정 로직은 Phase 3 이다.

더 중요한 것은 **연결되지 않는 술어를 정직하게 표시하는 것**이다.
``previous_location`` 처럼 Lua 스크립트와 게임 엔진에는 있지만 이 룰북이
정의하지 않는 개념이 있다. 그런 술어는 ``rules=()`` 이고
``support=NO_RULEBOOK_BASIS`` 다. 억지로 비슷해 보이는 절에 갖다 붙이면,
나중에 그 절을 근거로 잘못된 판정을 구현하게 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from rules.rule_model import RuleRef


class ConceptSupport(str, Enum):
    """룰북이 이 개념을 얼마나 뒷받침하는가."""

    DEFINED = "defined"
    """룰북이 개념을 직접 정의한다 (전용 절 또는 용어집 항목)."""
    MENTIONED = "mentioned"
    """룰북이 쓰기는 하지만 따로 정의하지 않는다."""
    NO_RULEBOOK_BASIS = "no_rulebook_basis"
    """이 룰북에 근거가 없다. 판정 근거는 Lua / 상급 룰 문서에서 찾아야 한다."""


@dataclass(frozen=True, slots=True)
class ConceptLink:
    """술어 하나에 대한 연결."""

    predicate: str
    """:class:`~analysis.predicate_model.PredicateKind` 의 값."""
    rule_concept: str
    """룰북이 쓰는 표현."""
    engine_concept: str
    """:mod:`engine` 에서 이 개념을 담는 자리. 아직 없으면 예정 위치."""
    support: ConceptSupport
    rules: tuple[RuleRef, ...] = ()
    note: str = ""

    @property
    def grounded(self) -> bool:
        return self.support is not ConceptSupport.NO_RULEBOOK_BASIS


def _ref(*rule_ids: str) -> tuple[RuleRef, ...]:
    return tuple(RuleRef(rule_id) for rule_id in rule_ids)


# ``analysis.predicate_model.PredicateKind`` 25종 + unknown 에 대한 연결.
CONCEPT_LINKS: tuple[ConceptLink, ...] = (
    ConceptLink(
        predicate="card_property",
        rule_concept="Type / Attribute / Level / ATK / DEF",
        engine_concept="CardInstance.definition (core.card_model.Card)",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-CARD-001", "RULE-TERM-014"),
        note="원래 공격력/수비력의 정의는 용어집에 있다.",
    ),
    ConceptLink(
        predicate="card_location",
        rule_concept="Zones on the Game Mat",
        engine_concept="engine.vocabulary.Zone / CardInstance.zone",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-ZONE-001", "RULE-TERM-005"),
    ),
    ConceptLink(
        predicate="card_position",
        rule_concept="battle position (face-up Attack / Defense, face-down Defense)",
        engine_concept="engine.vocabulary.Position / CardInstance.position",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-ZONE-001", "RULE-TERM-021"),
    ),
    ConceptLink(
        predicate="card_controller",
        rule_concept="Control / Possess",
        engine_concept="CardInstance.controller / owner",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-TERM-007"),
        note="룰북이 control 과 possession 을 명확히 구분한다.",
    ),
    ConceptLink(
        predicate="previous_location",
        rule_concept="(없음)",
        engine_concept="CardInstance.previous.location",
        support=ConceptSupport.NO_RULEBOOK_BASIS,
        note=(
            "이 룰북은 '직전 위치'를 개념으로 정의하지 않는다. "
            "Leaves the Field 절이 가장 가깝지만 그것은 '필드를 떠났는가'이지 "
            "'어디에 있었는가'가 아니다. 판정 근거는 Lua 다."
        ),
    ),
    ConceptLink(
        predicate="previous_position",
        rule_concept="(없음)",
        engine_concept="CardInstance.previous.position",
        support=ConceptSupport.NO_RULEBOOK_BASIS,
    ),
    ConceptLink(
        predicate="previous_controller",
        rule_concept="(없음)",
        engine_concept="CardInstance.previous.controller",
        support=ConceptSupport.NO_RULEBOOK_BASIS,
        note="컨트롤 이전 자체는 정의되지만, '직전 컨트롤러' 상태는 정의되지 않는다.",
    ),
    ConceptLink(
        predicate="card_exists",
        rule_concept="cards on the field",
        engine_concept="GameState.find_instance / ZoneContainer",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-TERM-005"),
    ),
    ConceptLink(
        predicate="group_exists",
        rule_concept="cards on the field",
        engine_concept="ZoneContainer 순회",
        support=ConceptSupport.MENTIONED,
        rules=_ref("RULE-TERM-005"),
    ),
    ConceptLink(
        predicate="group_contains",
        rule_concept="cards on the field",
        engine_concept="ZoneContainer 순회",
        support=ConceptSupport.MENTIONED,
        rules=_ref("RULE-TERM-005"),
    ),
    ConceptLink(
        predicate="zone_count",
        rule_concept="zone capacity (5 Monster Zones, 5 Spell & Trap Zones)",
        engine_concept="ZoneContainer.__len__ (칸 제약은 Phase 4)",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-ZONE-001"),
    ),
    ConceptLink(
        predicate="card_count",
        rule_concept="number of cards in hand / Deck",
        engine_concept="ZoneContainer.__len__",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-MISC-002", "RULE-TURN-007"),
    ),
    ConceptLink(
        predicate="turn_player",
        rule_concept="turn player",
        engine_concept="TurnState.turn_player",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-TURN-002", "RULE-CHAIN-009"),
    ),
    ConceptLink(
        predicate="phase",
        rule_concept="Phase / Step",
        engine_concept="engine.vocabulary.Phase / TurnState.phase",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-TURN-001"),
    ),
    ConceptLink(
        predicate="life_points",
        rule_concept="LP (Life Points)",
        engine_concept="PlayerState.life_points",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-GAME-004"),
    ),
    ConceptLink(
        predicate="field_spell",
        rule_concept="Field Spell Card / Field Zone",
        engine_concept="PlayerState.zones[Zone.FZONE]",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-SPELLTRAP-006", "RULE-ZONE-001"),
    ),
    ConceptLink(
        predicate="chain_effect_type",
        rule_concept="Spell Speed / card type on a Chain Link",
        engine_concept="ChainState (Phase 5)",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-CHAIN-002", "RULE-CHAIN-003"),
    ),
    ConceptLink(
        predicate="chain_state",
        rule_concept="Chain / Chain Link",
        engine_concept="ChainState (Phase 5)",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-CHAIN-001", "RULE-CHAIN-007"),
    ),
    ConceptLink(
        predicate="event_reason",
        rule_concept="destroyed / sent to the Graveyard / Tributed / discarded",
        engine_concept="engine.vocabulary REASON_* (Phase 2 GameEvent)",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-TERM-008", "RULE-TERM-020", "RULE-TERM-023", "RULE-TERM-009"),
        note=(
            "룰북이 '파괴'와 '묘지로 보내기'를 명확히 구분한다 — "
            "릴리스나 코스트로 묘지에 간 카드는 '파괴'가 아니다."
        ),
    ),
    ConceptLink(
        predicate="battle",
        rule_concept="Battle / Battled",
        engine_concept="BattleContext (Phase 4)",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-TERM-003", "RULE-BATTLE-010"),
        note="'battled' 는 데미지 계산까지 도달해야 성립한다고 룰북이 못박는다.",
    ),
    ConceptLink(
        predicate="card_status",
        rule_concept="(없음)",
        engine_concept="CardInstance.status_flags (STATUS_*)",
        support=ConceptSupport.NO_RULEBOOK_BASIS,
        note="STATUS_* 는 EDOPro 엔진 내부 상태이며 룰북 개념이 아니다.",
    ),
    ConceptLink(
        predicate="flag_effect",
        rule_concept="(없음)",
        engine_concept="엔진 내부 플래그 (Phase 8)",
        support=ConceptSupport.NO_RULEBOOK_BASIS,
    ),
    ConceptLink(
        predicate="summon_type",
        rule_concept="Normal / Flip / Special Summon 과 각 소환법",
        engine_concept="engine.vocabulary SUMMON_TYPE_*",
        support=ConceptSupport.DEFINED,
        rules=_ref("RULE-SUMMON-008", "RULE-SUMMON-013"),
    ),
    ConceptLink(
        predicate="player_affected",
        rule_concept="effects that apply to BOTH players",
        engine_concept="지속 효과 적용 대상 (Phase 8)",
        support=ConceptSupport.MENTIONED,
        rules=_ref("RULE-SPELLTRAP-006"),
        note="필드 마법 설명에서 언급될 뿐, 일반 규칙으로 정의되지는 않는다.",
    ),
    ConceptLink(
        predicate="player_comparison",
        rule_concept="you / your opponent",
        engine_concept="PlayerState.player_id 비교",
        support=ConceptSupport.MENTIONED,
        rules=_ref("RULE-TERM-007"),
    ),
    ConceptLink(
        predicate="unknown",
        rule_concept="(해석 불가)",
        engine_concept="(없음)",
        support=ConceptSupport.NO_RULEBOOK_BASIS,
        note="파서가 해석하지 못한 조건. 룰북으로도 메울 수 없다.",
    ),
)

_BY_PREDICATE = {link.predicate: link for link in CONCEPT_LINKS}


def link_for(predicate: str) -> ConceptLink | None:
    """술어 이름으로 연결을 찾는다."""
    return _BY_PREDICATE.get(predicate)


def rules_for(predicate: str) -> tuple[RuleRef, ...]:
    """이 술어를 판정할 때 근거가 되는 룰북 절."""
    link = _BY_PREDICATE.get(predicate)
    return link.rules if link else ()


def ungrounded_predicates() -> list[str]:
    """이 룰북에 근거가 없는 술어. Phase 3 에서 별도 취급해야 한다."""
    return [link.predicate for link in CONCEPT_LINKS if not link.grounded]


def coverage() -> dict[str, int]:
    counts: dict[str, int] = {}
    for link in CONCEPT_LINKS:
        counts[link.support.value] = counts.get(link.support.value, 0) + 1
    return counts
