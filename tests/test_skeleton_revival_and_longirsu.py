"""
Phase 6-AQ — **오르페골 스켈레촌 ① 과 롱기르수까지의 전개.**

이 파일이 재는 것
-----------------
``c21441617.lua`` 의 ``e1`` 을 옮긴 결과와, 그것이 디베르 ① 과 **갈리는
자리**다.

=========================================  ===============================
디베르 ①                                    스켈레촌 ①
=========================================  ===============================
``EFFECT_FLAG_CARD_TARGET`` **없음**        **있음** → 대상 지정
해결 중 ``SelectMatchingCard`` 로 고른다     발동 시 ``SelectTarget`` 로 지정
``s.spop`` 첫 줄에 빈 칸 ``return`` **있음**  **없음** → 조건 재검사가 없다
덱에서 특수 소환                             **묘지**에서 특수 소환
후보 0장이면 소환만 생략 (제한은 걸림)        **지정한 대상**을 쓸 수 없으면
                                            소환만 생략 (제한은 걸림)
=========================================  ===============================

실제와 합성
-----------
====================================================  ==================
``21441617`` · ``57835716`` · ``69811710`` 경로 전체    🔴 실제 카드
``30741503`` · ``76145142`` 링크 소환                   🔴 실제 카드
``42009836`` 파슬 다이너 파키세팔로 (실제 금지)          🔴 실제 카드
초기 판 구성 (필드 · 묘지 · 덱에 카드 놓기)              **테스트의 구성**
발동과 해결 사이의 카드 이동 · 칸 채우기                 **테스트의 조작**
====================================================  ==================

🔴 **발동과 해결 사이의 변화는 시험이 손으로 만든 조작이다** — 실제 등재된
상대 카드로 그 상황을 만들었다고 주장하지 않는다 (6-AO 후속과 같은 규율).
"""

from __future__ import annotations

import pathlib

import pytest

from agent.simulation import Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.action_target import ActionTarget
from engine.condition import ConditionResult
from engine.duel import Duel
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionError,
    EffectProvenance,
    NoCandidateScope,
    ResolutionSkip,
)
from engine.effect.executor import UNUSABLE_TARGET_CODES
from engine.effect.library import (
    EFFECT_LIBRARY,
    OPERATION_RULINGS,
    entry_for,
)
from engine.effect.operation import OperationKind
from engine.effect.resolution import ResolutionStatus
from engine.effect.ruling import (
    REVIVAL_LIMIT_FREE_ZONES,
    REVIVAL_LIMIT_TYPE_NAMES,
    RuleQuestion,
    revival_limit_applies,
)
from engine.effect.target import TargetRequirement
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.priority import PriorityState
from engine.spell_activation import duel_components
from engine.state.game_state import GameState
from engine.use_limit import LimitScope
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db, settle_chain

GIRSU = 69811710
DIBER = 57835716
SKELETON = 21441617
CANNONE = 94046012
GALATEA = 30741503
LONGIRSU = 76145142
BABEL = 90351981
#: 🔴 통상 몬스터이고 **스크립트가 없다** — 판에 놓으면 그 뒤의 모든 소환
#: 판정이 ``UNKNOWN`` 이 된다. 판을 채우는 용도로만 쓰고, 소환 관문을 지나야
#: 하는 시험에서는 등재된 카노네를 쓴다.
FEATHERMAN = 21844576
#: 🔴 **실제로 특수 소환을 금지하는** 카드 (손으로 읽은 표에 ``prohibits=True``).
PACHYCEPHALO = 42009836

SKELETON_EFFECT = EffectRef(SKELETON, 0)
DIBER_EFFECT = EffectRef(DIBER, 0)
P0, P1 = 0, 1

pytestmark = requires_official_db


# ======================================================================
# 공용 — **시작 상태**만 만든다
# ======================================================================
def _board(
    repository,
    *,
    mine=(),
    theirs=(),
    emzone=(),
    grave=(),
    deck=(),
    extra=(),
    hand=(),
    fzone=(),
    fill=0,
):
    """**시작 상태**를 만든다. 첫 행동 뒤의 모든 변화는 엔진이 만든다."""
    from app.main import opening_wiring

    state = GameState.create(
        repository,
        decks=(list(deck) + [FEATHERMAN] * 20, [FEATHERMAN] * 20),
        turn_player=P0,
        seed=1,
        shuffle=False,
    )
    mine_ids = []
    slot = 0
    for card_id in list(mine) + [CANNONE] * fill:
        instance = state.create_instance(card_id, owner=P0, zone=Zone.MZONE)
        state.move(
            instance,
            Zone.MZONE,
            to_player=P0,
            index=slot,
            position=Position.FACEUP_ATTACK,
        )
        mine_ids.append(instance.instance_id)
        slot += 1
    their_ids = []
    for index, card_id in enumerate(theirs):
        instance = state.create_instance(card_id, owner=P1, zone=Zone.MZONE)
        state.move(
            instance,
            Zone.MZONE,
            to_player=P1,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
        their_ids.append(instance.instance_id)
    em_ids = []
    for index, card_id in enumerate(emzone):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.EMZONE)
        state.move(
            instance,
            Zone.EMZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
        em_ids.append(instance.instance_id)
    for index, card_id in enumerate(fzone):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.FZONE)
        state.move(
            instance,
            Zone.FZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP,
        )
    grave_ids = []
    for card_id in grave:
        instance = state.create_instance(card_id, owner=P0, zone=Zone.GRAVE)
        state.move(instance, Zone.GRAVE, to_player=P0)
        grave_ids.append(instance.instance_id)
    for card_id in extra:
        state.create_instance(card_id, owner=P0, zone=Zone.EXTRA)
    hand_ids = [
        state.create_instance(card_id, owner=P0, zone=Zone.HAND).instance_id
        for card_id in hand
    ]
    state.turn.turn_number = 3
    state.turn.set_phase(Phase.MAIN1)
    wired, triggers = opening_wiring(repository, None)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        triggers=triggers,
        **duel_components(chooser=wired),
    )
    return duel, mine_ids, their_ids, em_ids, grave_ids, hand_ids


def _ids(duel, zone, seat=P0):
    return [card.card_id for card in duel.state.zone(seat, zone)]


def _limits(duel, seat=P0):
    state = duel.state
    return state.summon_limits.active(state.turn.turn_number, seat)


def _offers(duel, effect_ref=SKELETON_EFFECT):
    duel.advance()
    return [
        action
        for action in duel.legal_actions(P0).allowed
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
        and action.effect_ref == effect_ref
    ]


def _gate(duel, source, targets=(), effect_ref=SKELETON_EFFECT):
    action = PlayerAction.activate_effect(
        actor=P0, source=source, effect_ref=effect_ref, targets=targets
    )
    return duel._activation_gate(
        action, validator=duel.activation_validator(P0), selections=()
    )


def _snapshot(duel):
    state = duel.state
    return (
        state.state_hash(),
        state.summon_limits.canonical_state(),
        tuple(
            tuple(card.card_id for card in state.zone(seat, zone))
            for seat in (P0, P1)
            for zone in (
                Zone.MZONE,
                Zone.EMZONE,
                Zone.GRAVE,
                Zone.REMOVED,
                Zone.HAND,
            )
        ),
    )


# ======================================================================
# A. 카드 계약 — 정의가 ``c21441617.lua`` 를 그대로 옮겼는가
# ======================================================================
def test_a01_the_effect_is_registered_as_a_targeting_ignition_from_the_grave():
    """
    🔴 **다섯 가지를 한자리에서 센다.** 발동 분류 · 발동 자리 · 대상 지정 ·
    비용 · 사용 제한. 하나라도 어긋나면 그 효과는 다른 카드가 된다.
    """
    entry = entry_for(SKELETON_EFFECT)
    assert entry is not None
    assert entry.executable is True
    assert entry.lua_file == "c21441617.lua"
    definition = entry.definition

    from engine.vocabulary import ActivationKind

    assert definition.activation_kind is ActivationKind.IGNITION
    assert definition.activation_zones == frozenset({Zone.GRAVE})
    #: 🔴 **대상 지정이다** — 디베르와 갈리는 자리.
    assert len(definition.targets) == 1
    spec = definition.targets[0].spec
    assert spec.requirement is TargetRequirement.TARGETING
    assert spec.chosen_at_resolution is False
    assert spec.existence_requires_gate is True
    #: 비용은 **자기 자신을 묘지에서 제외**한다.
    assert definition.has_cost is True
    assert len(definition.cost.costs) == 1
    #: 사용 제한은 **카드명 기준**이다 (``SetCountLimit(1,id)``).
    assert definition.use_limit is not None
    assert definition.use_limit.scope is LimitScope.PER_CARD_NAME


def test_a02_the_candidate_rule_names_the_grave_the_archetype_and_the_name():
    """
    🔴 ``s.spfilter`` 의 세 항과 ``chkc`` 의 두 항을 **선택 명세가** 들고
    있는가. 숫자를 손으로 적지 않았는지도 함께 본다.
    """
    definition = entry_for(SKELETON_EFFECT).definition
    source = definition.targets[0].spec.choice.source
    assert source.zones == frozenset({Zone.GRAVE})
    from engine.condition import PlayerRef

    assert source.owner is PlayerRef.CONTROLLER
    #: ``Duel.SelectTarget(...,e:GetHandler(),...)`` 의 예외 카드.
    assert source.exclude_source is True
    said = source.require.describe_ko()
    #: 「"오르페골 스켈레촌" 이외의」 · 「"오르페골"」 · 「몬스터」.
    assert str(SKELETON) in said
    assert "0x11b" in said
    assert "몬스터" in said
    #: 한 장만 고른다 (``1,1``).
    assert definition.targets[0].spec.choice.minimum == 1
    assert definition.targets[0].spec.choice.maximum == 1


def test_a03_the_operations_are_the_summon_then_the_dark_restriction():
    """
    🔴 **순서가 규칙이다** (``EFFECT_FLAG_OATH``). 공식 스크립트가 소환을
    먼저 하고 제한을 나중에 등록한다.
    """
    definition = entry_for(SKELETON_EFFECT).definition
    kinds = [operation.kind for operation in definition.operations]
    assert kinds == [
        OperationKind.SPECIAL_SUMMON,
        OperationKind.RESTRICT_SPECIAL_SUMMON,
    ]
    restriction = definition.operations[1]
    assert restriction.attribute == "DARK"
    assert "c21441617.lua" in restriction.basis


def test_a04_nothing_is_rechecked_at_resolution():
    """
    🔴 **이 효과의 ``s.spop`` 에는 조건 재검사가 하나도 없다.** 디베르의
    같은 함수 첫 줄에 있는 ``GetLocationCount<=0 then return`` 이 **없다** —
    그래서 빈 조건을 명시하고, 그 사실이 생략 범위를 가른다.
    """
    definition = entry_for(SKELETON_EFFECT).definition
    assert definition.resolution_condition is not None
    assert definition.resolution_condition.describe_ko() == "(조건 없음)"
    skip = definition.resolution_skip
    assert skip is not None
    assert skip.when_target_unusable is True
    #: 🔴 **다른 두 칸은 적지 않았다** — 디베르를 베껴 적지 않았다.
    assert skip.when_condition_false is False
    assert skip.when_no_candidate is False
    assert skip.no_candidate_scope is NoCandidateScope.WHOLE_EFFECT
    #: 근거가 그 ``if`` 와 ``RegisterEffect`` 를 가리킨다.
    assert "IsRelateToEffect" in skip.basis
    assert "RegisterEffect" in skip.basis

    #: 🔴 디베르는 **반대로** 적혀 있다 — 한 글자도 달라지지 않았다.
    diber = entry_for(DIBER_EFFECT).definition.resolution_skip
    assert diber.when_condition_false is True
    assert diber.when_no_candidate is True
    assert diber.no_candidate_scope is NoCandidateScope.TARGET_OPERATIONS
    assert diber.when_target_unusable is False


def test_a05_babel_closes_this_effect_too():
    """
    🔴 ``s.spcon1`` — 바벨이 적용되고 있으면 ①이 아니라 ②(유발즉시)가
    쓰이고, 그 분류는 미지원이다. 디베르와 **같은 경계**다.
    """
    definition = entry_for(SKELETON_EFFECT).definition
    said = definition.activation.describe_ko()
    assert str(BABEL) in said
    #: ②(``EFFECT_TYPE_QUICK_O``)는 등재하지 않았다.
    assert entry_for(EffectRef(SKELETON, 1)) is None
    assert "e2" in definition.provenance.note


def test_a06_the_card_facts_were_rewritten_when_the_effect_was_registered():
    """
    🔴 **6-AO 의 근거가 6-AQ 에서 더 이상 참이 아니다.** 그때 스켈레촌의
    ``restricts_others=False`` 는 "① 이 등재되지 않았다" 를 근거로 적혀
    있었고, 이제 ① 이 등재되었다.
    """
    facts = OPERATION_RULINGS.facts_for(SKELETON)
    assert facts is not None
    assert facts.restricts_others is False
    note = facts.restriction_note
    #: 등재 범위를 근거로 들지 않는다 — 디베르와 같은 근거다.
    assert "비용으로" in note
    assert "6-AQ" in note
    #: 세 질문이 적혀 있다.
    for question in (
        RuleQuestion.MAY_BE_SPECIAL_SUMMONED,
        RuleQuestion.MAY_BE_SENT_TO_GRAVE,
        RuleQuestion.MAY_BE_BANISHED,
    ):
        answer = facts.answer_for(question)
        assert answer is not None, question
        assert answer.answer is ConditionResult.TRUE, question

    #: 🔴 **카노네는 그대로다** — 그 ① 은 여전히 등재되지 않았고, 그
    #: 사실을 기계가 지킨다.
    cannone = OPERATION_RULINGS.facts_for(CANNONE)
    assert cannone is not None
    assert "등재되지 않았" in cannone.restriction_note
    assert [
        entry.effect_ref for entry in EFFECT_LIBRARY if entry.card_id == CANNONE
    ] == []


# ======================================================================
# B. 소생 제한 — 룰북이 그 질문을 **누구에게** 거는가
# ======================================================================
def test_b01_the_revival_limit_is_a_card_kind_question_from_the_rulebook():
    """
    🔴 **``RULE-SUMMON-014`` 를 옮긴 자리.** 소생 제한은 "묘지의 모든
    몬스터" 의 문제가 아니라 **정규 소환 절차를 거쳐야 하는 종류**의
    문제다.

    🔴 **완화가 아니다** — 읽지 못한 카드는 그대로 ``UNKNOWN`` 이다.
    """

    class _Kind:
        def __init__(self, *, extra=False, names=("MONSTER", "EFFECT"), signals=()):
            self.is_monster = True
            self.is_extra_deck = extra
            self.type_names = names
            self.normal_summon_restriction_signals = signals

    #: 일반 소환할 수 있는 메인 덱 효과 몬스터 — 질문이 생기지 않는다.
    assert revival_limit_applies(_Kind()) is ConditionResult.FALSE
    #: 엑스트라 덱 — 룰북의 예시가 가리키는 쪽이다.
    assert revival_limit_applies(_Kind(extra=True)) is ConditionResult.TRUE
    #: 「"Special Summon Monsters"」 와 의식.
    for name in sorted(REVIVAL_LIMIT_TYPE_NAMES):
        assert (
            revival_limit_applies(_Kind(names=("MONSTER", "EFFECT", name)))
            is ConditionResult.TRUE
        ), name
    #: 🔴 스크립트를 읽지 못했으면 **모름**이다 (``None``).
    assert revival_limit_applies(_Kind(signals=None)) is ConditionResult.UNKNOWN
    #: 🔴 조건부 제약 상수를 찾았으면 **모름**이다 — 누구에게 걸리는지 이
    #: 신호가 말하지 않는다.
    assert (
        revival_limit_applies(_Kind(signals=("EFFECT_CANNOT_SUMMON",)))
        is ConditionResult.UNKNOWN
    )
    #: 정의가 없으면 모름이다.
    assert revival_limit_applies(None) is ConditionResult.UNKNOWN
    #: 🔴 **자리 표는 지우지 않았다** — 패 · 덱은 여전히 그 질문이 생기지
    #: 않는 자리다 (6-AC · 6-AO 의 근거 그대로).
    assert REVIVAL_LIMIT_FREE_ZONES == frozenset({Zone.HAND, Zone.DECK})


@pytest.mark.real_card
def test_b02_an_extra_deck_monster_in_the_grave_is_refused_not_revived(
    repository,
):
    """
    🔴 **소생 제한이 걸리는 몬스터는 거절된다.** 묘지의 갈라테아를 대상으로
    지정하면 해결 시 ``UNCHECKED_RULES`` 이고, **소환도 제한도 없다** —
    모름은 생략으로 바뀌지 않는다.
    """
    duel, _m, _t, _e, grave, _h = _board(
        repository, grave=(SKELETON, GALATEA)
    )
    skeleton, galatea = grave
    offers = _offers(duel)
    assert len(offers) == 1
    assert offers[0].targets[0].instance_id == galatea
    assert duel.apply(offers[0]).accepted is True
    settle_chain(duel)

    #: 소환은 없다.
    assert _ids(duel, Zone.MZONE) == []
    assert _ids(duel, Zone.GRAVE) == [GALATEA]
    #: 🔴 **제한도 없다** — 모름은 "소환하지 않았다" 와 다르다.
    assert _limits(duel) == ()
    #: 비용과 사용 기록은 그대로 치러져 있다.
    assert _ids(duel, Zone.REMOVED) == [SKELETON]


# ======================================================================
# C. 정상 발동 — 대상 지정과 소생
# ======================================================================
@pytest.mark.real_card
def test_c01_the_designated_target_is_revived_and_the_limit_is_registered(
    repository,
):
    """🔴 **이 Phase 의 본문.** 묘지의 기르수를 대상으로 지정해 소생한다."""
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    skeleton, girsu = grave
    offers = _offers(duel)
    assert len(offers) == 1
    assert offers[0].source == skeleton
    assert offers[0].targets[0].instance_id == girsu
    assert duel.apply(offers[0]).accepted is True
    #: 🔴 비용은 **발동 시점**에 이미 치러졌다.
    assert _ids(duel, Zone.REMOVED) == [SKELETON]

    settle_chain(duel)

    assert _ids(duel, Zone.MZONE) == [GIRSU]
    assert _ids(duel, Zone.GRAVE) == []
    limits = _limits(duel)
    assert len(limits) == 1
    assert limits[0].attribute == "DARK"
    assert limits[0].source_card_id == SKELETON
    #: 사용 기록도 남는다.
    limit = entry_for(SKELETON_EFFECT).definition.use_limit
    key = limit.key_for(P0, SKELETON_EFFECT, skeleton)
    assert duel.state.uses.count(limit.scope, key) == 1


@pytest.mark.real_card
def test_c02_the_card_name_limit_blocks_the_second_copy(repository):
    """
    🔴 **카드명 기준 사용 제한.** 묘지에 스켈레촌이 두 장 있어도 두 번째는
    발동할 수 없다 (``SetCountLimit(1,id)``).
    """
    duel, _m, _t, _e, grave, _h = _board(
        repository, grave=(SKELETON, SKELETON, GIRSU, CANNONE)
    )
    first = _offers(duel)
    #: 두 사본이 각각 후보다 (대상은 기르수 · 카노네 둘 중 하나씩).
    assert len({action.source for action in first}) == 2
    assert duel.apply(first[0]).accepted is True
    settle_chain(duel)

    #: 🔴 두 번째 사본은 더 이상 후보가 아니다.
    assert _offers(duel) == []


@pytest.mark.real_card
def test_c03_the_cost_is_not_refunded_and_the_target_is_not_reselected(
    repository,
):
    """
    🔴 **비용을 치른 뒤 다른 몬스터를 새로 고르지 않는다.** 묘지에 적격
    대상이 둘 있어도 지정한 쪽만 나온다.
    """
    duel, _m, _t, _e, grave, _h = _board(
        repository, grave=(SKELETON, GIRSU, CANNONE)
    )
    skeleton, girsu, cannone = grave
    chosen = next(
        action
        for action in _offers(duel)
        if action.targets[0].instance_id == cannone
    )
    assert duel.apply(chosen).accepted is True
    settle_chain(duel)

    #: 지정한 카노네가 나왔고 기르수는 묘지에 그대로다.
    assert _ids(duel, Zone.MZONE) == [CANNONE]
    assert _ids(duel, Zone.GRAVE) == [GIRSU]
    assert _ids(duel, Zone.REMOVED) == [SKELETON]


@pytest.mark.real_card
def test_c04_ineligible_targets_are_not_offered(repository):
    """
    🔴 **같은 이름 · 다른 카드군 · 다른 자리는 대상이 아니다.** 셋을 한
    판에 놓고 후보가 하나도 없음을 센다.
    """
    #: 같은 이름뿐 — ``not c:IsCode(id)``.
    duel, *_rest = _board(repository, grave=(SKELETON, SKELETON))
    assert _offers(duel) == []
    #: 「오르페골」 이 아닌 몬스터뿐 — ``IsSetCard(SET_ORCUST)``.
    duel, *_rest = _board(repository, grave=(SKELETON, FEATHERMAN))
    assert _offers(duel) == []
    #: 필드의 「오르페골」 은 대상이 아니다 — ``LOCATION_GRAVE``.
    duel, *_rest = _board(repository, mine=(GIRSU,), grave=(SKELETON,))
    assert _offers(duel) == []
    #: 패의 스켈레촌은 **발동 자리**가 아니다 — ``SetRange(LOCATION_GRAVE)``.
    duel, _m, _t, _e, grave, hand = _board(
        repository, grave=(GIRSU,), hand=(SKELETON,)
    )
    assert _offers(duel) == []
    #: 🔴 손으로 조립해도 거절된다 — 발동 자리가 묘지로 적혀 있다.
    gate = _gate(duel, hand[0], (ActionTarget.instance(grave[0]),))
    assert gate.validity is ActionValidity.INVALID, gate.reason


@pytest.mark.real_card
def test_c05_a_wrong_or_missing_target_is_refused_at_activation(repository):
    """
    🔴 **잘못된 대상 선택은 거절된다** — 생략이 아니다. 그리고 거절이 판을
    바꾸지 않는다 (비용도 치러지지 않는다).
    """
    duel, _m, _t, _e, grave, _h = _board(
        repository, grave=(SKELETON, GIRSU, FEATHERMAN)
    )
    skeleton, _girsu, feather = grave
    before = _snapshot(duel)

    #: 부적격 카드를 대상으로.
    wrong = _gate(duel, skeleton, (ActionTarget.instance(feather),))
    assert wrong.validity is ActionValidity.INVALID
    #: 대상 없이.
    empty = _gate(duel, skeleton, ())
    assert empty.validity is ActionValidity.INVALID
    #: 🔴 어느 쪽도 판을 바꾸지 않았다.
    assert _snapshot(duel) == before


@pytest.mark.real_card
def test_c06_a_full_monster_zone_closes_the_activation(repository):
    """
    🔴 ``s.sptg`` 의 ``GetLocationCount(tp,LOCATION_MZONE)>0`` 은 **발동
    조건**이다. 칸이 없으면 후보가 되지 않는다.
    """
    duel, *_rest = _board(repository, grave=(SKELETON, GIRSU), fill=5)
    assert _offers(duel) == []


@pytest.mark.real_card
def test_c07_a_forbidden_board_closes_the_activation(repository):
    """
    🔴 ``SpecialSummonPermitted`` — 특수 소환이 금지된 판에서는 발동
    자체가 거절된다 (디베르와 같은 자리).
    """
    duel, *_rest = _board(
        repository, mine=(PACHYCEPHALO,), grave=(SKELETON, GIRSU)
    )
    assert _offers(duel) == []


# ======================================================================
# D. 해결 시점의 변화 — **이 Phase 가 더한 최소 기능**
# ======================================================================
@pytest.mark.real_card
def test_d01_a_target_that_left_the_grave_skips_only_the_summon(repository):
    """
    🔴 **이 Phase 의 두 번째 본문** — ``if tc and tc:IsRelateToEffect(e)``.

    지정한 대상이 묘지를 벗어나면 **소환만** 하지 않고 어둠 속성 제한은
    그대로 걸린다 (``RegisterEffect`` 가 그 ``if`` 밖이다).

    🔴 발동 뒤의 카드 이동은 **시험이 손으로 만든 조작**이다.
    """
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    skeleton, girsu = grave
    offers = _offers(duel)
    assert duel.apply(offers[0]).accepted is True

    state = duel.state
    moved = [c for c in state.zone(P0, Zone.GRAVE) if c.instance_id == girsu][0]
    state.move(moved, Zone.HAND, to_player=P0)

    settle_chain(duel)

    #: ① 소환은 없다.
    assert _ids(duel, Zone.MZONE) == []
    assert GIRSU in _ids(duel, Zone.HAND)
    #: ② 🔴 **제한은 걸렸다.**
    limits = _limits(duel)
    assert len(limits) == 1
    assert limits[0].attribute == "DARK"
    #: ③ 비용과 사용 기록은 되돌아오지 않는다.
    assert _ids(duel, Zone.REMOVED) == [SKELETON]
    limit = entry_for(SKELETON_EFFECT).definition.use_limit
    key = limit.key_for(P0, SKELETON_EFFECT, skeleton)
    assert state.uses.count(limit.scope, key) == 1


@pytest.mark.real_card
def test_d02_a_full_zone_at_resolution_skips_only_the_summon(repository):
    """
    🔴 **디베르와 갈리는 자리.** 디베르는 ``s.spop`` 첫 줄의 ``return`` 이
    ``RegisterEffect`` **앞**이라 그때 제한도 걸리지 않지만, 이 카드의
    ``s.spop`` 에는 그 줄이 **없다** — ``Duel.SpecialSummon`` 이 0장을
    소환하고 그 뒤가 그대로 실행된다.

    🔴 발동 뒤 몬스터 존을 채우는 것은 **시험이 손으로 만든 조작**이다.
    """
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    offers = _offers(duel)
    assert duel.apply(offers[0]).accepted is True

    state = duel.state
    for index in range(5):
        filler = state.create_instance(CANNONE, owner=P0, zone=Zone.MZONE)
        state.move(
            filler,
            Zone.MZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )

    settle_chain(duel)

    assert _ids(duel, Zone.MZONE) == [CANNONE] * 5
    assert _ids(duel, Zone.GRAVE) == [GIRSU]
    #: 🔴 **제한은 걸렸다** — 디베르의 같은 상황과 반대다.
    assert len(_limits(duel)) == 1


@pytest.mark.real_card
def test_d03_a_forbidden_board_at_resolution_skips_only_the_summon(repository):
    """
    🔴 **확정 금지**도 같은 갈래다 — ``Duel.SpecialSummon`` 이 0장을
    소환하는 것이고, 그 뒤의 ``RegisterEffect`` 는 실행된다.

    🔴 발동 **뒤에** 놓는다 — 먼저 있으면 발동 자체가 거절된다
    (``test_c07``).
    """
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    offers = _offers(duel)
    assert duel.apply(offers[0]).accepted is True

    state = duel.state
    blocker = state.create_instance(PACHYCEPHALO, owner=P1, zone=Zone.MZONE)
    state.move(
        blocker,
        Zone.MZONE,
        to_player=P1,
        index=0,
        position=Position.FACEUP_ATTACK,
    )

    settle_chain(duel)

    assert _ids(duel, Zone.MZONE) == []
    assert _ids(duel, Zone.GRAVE) == [GIRSU]
    assert len(_limits(duel)) == 1


@pytest.mark.real_card
def test_d04_a_target_moved_to_a_concealed_zone_skips_only_the_summon(
    repository,
):
    """
    🔴 **이 보완의 본문 하나** (요구 B). 지정한 대상이 **관측되지 않는
    자리**(덱)로 가면 소환만 생략하고 어둠 속성 제한은 걸린다.

    🔴 **6-AQ 는 여기서 효과 전체를 거절했고, 그때 그 설명은 사실이었다** —
    후보 조건을 판정할 수 없어 ``UNCHECKED_TARGET`` 이 되었다 (보고서
    §4.1). 바뀐 것은 **묻는 순서와 묻는 것**이다: 관계 기록을 먼저 묻고
    (:meth:`~engine.effect.executor.EffectExecutor._check_target_relations`),
    그 답이 "끊겼다" 면 관측을 만들지 않는다.

    🔴 **비공개 정보를 더 열지 않았다.** 아래가 그것을 센다 — 덱은 여전히
    가려져 있고, 판정에 쓴 것은 판에 적힌 관계 기록 하나다.
    """
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    skeleton, girsu = grave
    offers = _offers(duel)
    assert duel.apply(offers[0]).accepted is True
    #: 발동 시점에 관계가 적혔다.
    assert (
        duel.state.relations.status(skeleton, SKELETON_EFFECT, girsu) is True
    )

    state = duel.state
    moved = [c for c in state.zone(P0, Zone.GRAVE) if c.instance_id == girsu][0]
    state.move(moved, Zone.DECK, to_player=P0)
    #: 🔴 **이동 하나로 관계가 끊겼다** — 판이 그 사실을 들고 있다.
    assert state.relations.status(skeleton, SKELETON_EFFECT, girsu) is False

    settle_chain(duel)

    #: ① 소환은 없다.
    assert _ids(duel, Zone.MZONE) == []
    #: ② 🔴 **제한은 걸렸다** — 6-AQ 와 갈리는 자리다.
    limits = _limits(duel)
    assert len(limits) == 1
    assert limits[0].source_card_id == SKELETON
    #: ③ 비용과 사용 기록은 유지된다.
    assert _ids(duel, Zone.REMOVED) == [SKELETON]
    limit = entry_for(SKELETON_EFFECT).definition.use_limit
    key = limit.key_for(P0, SKELETON_EFFECT, skeleton)
    assert duel.state.uses.count(limit.scope, key) == 1

    #: ④ 🔴 **덱은 여전히 가려져 있다.** 플레이어 관측에 그 카드가 보이지
    #: 않고, 판정이 그것을 열지도 않았다.
    view = GameStateView.from_state(duel.state, viewer=P0)
    assert view.find(girsu) is None
    #: 그리고 그 카드가 **어느 관측에도** 보이지 않는다 — 덱은 가려진
    #: 자리이고, 이 판정이 그것을 열지 않았다.
    assert girsu not in view.visible_instances()
    assert all(
        girsu
        not in GameStateView.from_state(
            duel.state, viewer=seat
        ).visible_instances()
        for seat in (P0, P1)
    )


@pytest.mark.real_card
def test_d05_a_target_that_left_and_came_back_is_not_summoned(repository):
    """
    🔴 **이 보완의 본문 둘** (요구 A). 지정한 뒤 그 카드가 묘지를 떠났다
    **돌아오면** 소생하지 않는다.

    🔴 **6-AQ 는 여기서 소환했고, 그 측정은 사실이었다** —
    ``InstanceId`` 는 자리를 옮겨도 그대로이므로 같은 개체로 읽혔다
    (보고서 §4.2). 바뀐 것은 **무엇을 비교하는가**다: 영구한 개체 번호가
    아니라 **발동 때 적어 둔 관계**를 본다
    (:mod:`engine.state.target_relation`).
    """
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    skeleton, girsu = grave
    offers = _offers(duel)
    assert duel.apply(offers[0]).accepted is True

    state = duel.state
    away = [c for c in state.zone(P0, Zone.GRAVE) if c.instance_id == girsu][0]
    state.move(away, Zone.HAND, to_player=P0)
    back = [c for c in state.zone(P0, Zone.HAND) if c.instance_id == girsu][0]
    state.move(back, Zone.GRAVE, to_player=P0)

    #: 🔴 **같은 번호로 묘지에 돌아와 있다** — 그런데 관계는 끊긴 채다.
    assert state.find_instance(girsu).zone is Zone.GRAVE
    assert state.relations.status(skeleton, SKELETON_EFFECT, girsu) is False

    settle_chain(duel)

    #: ① 소환은 없다 — 기르수는 묘지에 그대로다.
    assert _ids(duel, Zone.MZONE) == []
    assert _ids(duel, Zone.GRAVE) == [GIRSU]
    #: ② 제한은 걸렸다.
    assert len(_limits(duel)) == 1
    #: ③ 비용은 유지된다.
    assert _ids(duel, Zone.REMOVED) == [SKELETON]


@pytest.mark.real_card
def test_d06_banished_and_back_does_not_restore_the_relation(repository):
    """🔴 묘지 → 제외 → 묘지도 같다 — **돌아와도 되살아나지 않는다.**"""
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    skeleton, girsu = grave
    offers = _offers(duel)
    assert duel.apply(offers[0]).accepted is True

    state = duel.state
    state.move(
        [c for c in state.zone(P0, Zone.GRAVE) if c.instance_id == girsu][0],
        Zone.REMOVED,
        to_player=P0,
    )
    state.move(
        [c for c in state.zone(P0, Zone.REMOVED) if c.instance_id == girsu][0],
        Zone.GRAVE,
        to_player=P0,
    )
    assert state.relations.status(skeleton, SKELETON_EFFECT, girsu) is False

    settle_chain(duel)
    assert _ids(duel, Zone.MZONE) == []
    assert len(_limits(duel)) == 1


@pytest.mark.real_card
def test_d07_another_card_is_not_summoned_in_its_place(repository):
    """
    🔴 **대상을 다시 고르지 않는다.** 관계가 끊긴 뒤 **같은 카드명**의 다른
    개체를 묘지에 놓아도 그 카드가 대신 나오지 않는다.
    """
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    skeleton, girsu = grave
    offers = _offers(duel)
    assert duel.apply(offers[0]).accepted is True

    state = duel.state
    state.move(
        [c for c in state.zone(P0, Zone.GRAVE) if c.instance_id == girsu][0],
        Zone.DECK,
        to_player=P0,
    )
    #: 🔴 **시험용 조작** — 같은 카드명의 **다른 개체**를 묘지에 놓는다.
    other = state.create_instance(GIRSU, owner=P0, zone=Zone.GRAVE)
    state.move(other, Zone.GRAVE, to_player=P0)
    assert other.instance_id != girsu

    settle_chain(duel)

    #: 소환은 없고, 새 개체는 묘지에 그대로다.
    assert _ids(duel, Zone.MZONE) == []
    assert _ids(duel, Zone.GRAVE) == [GIRSU]
    assert state.find_instance(other.instance_id).zone is Zone.GRAVE
    assert len(_limits(duel)) == 1


@pytest.mark.real_card
def test_d08_moves_that_do_not_break_the_relation(repository):
    """
    🔴 **끊는 범위를 좁게 적었다** (요구 ⑦). 이번에 정의한 범위 밖의
    조작으로는 관계가 끊기지 않는다.

    🔴 **끊는 것은 존 종류가 바뀌는 이동 하나다** — 같은 존에 다른 카드가
    들어오는 것도, 묘지의 순서가 바뀌는 것도, 표시 형식이 바뀌는 것도
    아니다.
    """
    duel, _m, _t, _e, grave, _h = _board(
        repository, mine=(CANNONE,), grave=(SKELETON, GIRSU)
    )
    skeleton, girsu = grave
    offers = _offers(duel)
    assert duel.apply(offers[0]).accepted is True
    state = duel.state

    #: ① 같은 존에 **다른 카드**가 들어온다 (시험용 조작).
    filler = state.create_instance(FEATHERMAN, owner=P0, zone=Zone.GRAVE)
    state.move(filler, Zone.GRAVE, to_player=P0)
    #: ② 묘지의 **순서**가 바뀐다 — ``reorder`` 는 이동이 아니다.
    container = state.player(P0).zone(Zone.GRAVE)
    container.reorder(tuple(reversed(range(len(container)))))
    #: ③ **필드의 다른 카드**의 표시 형식이 바뀐다.
    state.find_instance(_m[0]).set_position(Position.FACEUP_DEFENSE)

    #: 🔴 셋 다 관계를 끊지 않았다.
    assert state.relations.status(skeleton, SKELETON_EFFECT, girsu) is True

    settle_chain(duel)
    #: 그래서 정상 소생이다.
    assert GIRSU in _ids(duel, Zone.MZONE)
    assert len(_limits(duel)) == 1


@pytest.mark.real_card
def test_d09_a_missing_relation_record_stays_unknown(repository):
    """
    🔴 **기록이 없으면 모름이다** (요구 ⑧). 정상적인 관계 단절로 흡수되지
    않는다.

    🔴 **시험용 조작이다** — 발동 경로는 언제나 관계를 적으므로
    (:meth:`~engine.activation.EffectActivator._note_target_relations`),
    기록이 없는 상태는 손으로 지워야 만들어진다. 실제 상대 카드로 이 상황을
    만들었다고 주장하지 않는다.
    """
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    skeleton, girsu = grave
    offers = _offers(duel)
    assert duel.apply(offers[0]).accepted is True
    state = duel.state
    #: 🔴 기록을 **지운다** (끊는 것이 아니다).
    state.relations.clear()
    assert state.relations.status(skeleton, SKELETON_EFFECT, girsu) is None

    settle_chain(duel)

    #: ① 소환도 없고 **제한도 없다** — 모름은 생략으로 바뀌지 않는다.
    assert _ids(duel, Zone.MZONE) == []
    assert _limits(duel) == ()
    #: ② 그 사유가 "관계 단절" 이 아니라 **모름**이다.
    from engine.effect.executor import TARGET_RELATION_RULE

    said = duel.history[-1].reason if hasattr(duel, "history") else ""
    assert "기록이 없습니다" in said or TARGET_RELATION_RULE, said
    #: ③ 비용은 그대로 치러져 있다.
    assert _ids(duel, Zone.REMOVED) == [SKELETON]


@pytest.mark.real_card
def test_d10_a_broken_relation_is_a_different_code_from_not_eligible(
    repository,
):
    """
    🔴 **두 사실을 다른 코드로 적는다.** "관계가 끊겼다" 와 "후보 조건을
    만족하지 않는다" 는 다른 일이고, 그래서 다른 ``ValidationCode`` 다.
    """
    from engine.validation import CODE_VALIDITY

    assert (
        ValidationCode.TARGET_RELATION_LOST
        is not ValidationCode.CANDIDATE_NOT_ELIGIBLE
    )
    #: 🔴 **확인된 거부다** — 모름이 아니다.
    assert CODE_VALIDITY[ValidationCode.TARGET_RELATION_LOST] is (
        ActionValidity.INVALID
    )
    #: 그리고 그 코드가 생략으로 바뀌는 쪽에 들어 있다.
    assert ValidationCode.TARGET_RELATION_LOST in UNUSABLE_TARGET_CODES


# ======================================================================
# E. 선언과 실행기 — 완화가 아니라 선언이다
# ======================================================================
def test_e01_the_target_skip_can_only_be_declared_on_a_targeting_effect():
    """
    🔴 **고르기 효과에 적을 수 없다.** 적으면 "후보가 없었다" 와 뒤섞이고,
    읽는 쪽은 무엇이 완화되었는지 알 수 없다.
    """
    from engine.effect.operation import DrawOperation

    with pytest.raises(EffectDefinitionError):
        EffectDefinition(
            effect_ref=EffectRef(1, 0),
            source_card_id=1,
            operations=(DrawOperation(count=1),),
            resolution_skip=ResolutionSkip(
                when_target_unusable=True, basis="시험용"
            ),
            provenance=EffectProvenance.hand_written("시험용"),
        )
    #: 조건을 하나도 적지 않은 선언은 만들어지지 않는다.
    with pytest.raises(ValueError):
        ResolutionSkip(basis="시험용")
    #: 근거 없는 선언도 만들어지지 않는다.
    with pytest.raises(ValueError):
        ResolutionSkip(when_target_unusable=True, basis="  ")
    #: 🔴 정규 표현에 들어간다 — 선언한 효과와 안 한 효과가 같지 않다.
    assert ResolutionSkip(
        when_target_unusable=True, basis="시험용"
    ).canonical_state() != ResolutionSkip(
        when_condition_false=True, basis="시험용"
    ).canonical_state()


def test_e02_only_one_refusal_code_becomes_a_skip():
    """
    🔴 **좁게 삼킨다.** 장수가 어긋났다 · 대상이 없다 · 모른다 는 생략으로
    바뀌지 않는다.
    """
    #: 🔴 **둘이다** (6-AQ 후속). 늘어난 하나는 "발동 때 지정한 관계가
    #: 끊겼다" 이고, 그것은 **확인된 거부**다 (모름이 아니다).
    assert UNUSABLE_TARGET_CODES == frozenset(
        {
            ValidationCode.CANDIDATE_NOT_ELIGIBLE,
            ValidationCode.TARGET_RELATION_LOST,
        }
    )
    for code in (
        ValidationCode.TOO_FEW_SELECTED,
        ValidationCode.TOO_MANY_SELECTED,
        ValidationCode.DUPLICATE_SELECTION,
        ValidationCode.TARGET_COUNT_MISMATCH,
        ValidationCode.HIDDEN_CARD,
        ValidationCode.INFORMATION_UNAVAILABLE,
        ValidationCode.RULE_NOT_IMPLEMENTED,
    ):
        assert code not in UNUSABLE_TARGET_CODES, code


def test_e03_the_executor_names_no_card():
    """
    🔴 **해결기에 스켈레촌 카드 ID 가 없다.** 생략 여부는 정의가 선언하고,
    어느 일이 그 대상을 쓰는지는 ``Operation.target_refs`` 가 답한다.
    """
    source = pathlib.Path("engine/effect/executor.py").read_text("utf-8")
    assert str(SKELETON) not in source
    assert str(DIBER) not in source
    assert "operation.target_refs" in source
    #: 그리고 삼키는 거절이 ``INVALID_TARGET`` 하나로 좁혀져 있다.
    assert "ResolutionStatus.INVALID_TARGET" in source
    assert "UNUSABLE_TARGET_CODES" in source


def test_e04_the_search_does_not_know_this_line():
    """
    🔴 **탐색기에 정답 수순을 하드코딩하지 않았다.** 고정 경로의 이름도,
    이 Phase 의 카드 ID 도, ``COMBO_LINES`` 도 탐색기 안에 없다.
    """
    import inspect

    import agent.bounded_search as bs
    from deck.combo_policy import COMBO_LINES, ORCUST_SKELETON_LONGIRSU_LINE

    assert (
        COMBO_LINES["orcust-skeleton-longirsu"]
        is ORCUST_SKELETON_LONGIRSU_LINE
    )
    assert "검증용" in ORCUST_SKELETON_LONGIRSU_LINE.note
    assert ORCUST_SKELETON_LONGIRSU_LINE.reproduction_ready is True
    source = inspect.getsource(bs)
    for needle in (
        "orcust-skeleton-longirsu",
        str(SKELETON),
        str(LONGIRSU),
        "COMBO_LINES",
    ):
        assert needle not in source, needle


def test_e05_no_other_effect_was_loosened():
    """
    🔴 **일괄 완화가 아니다.** 이 선언을 적은 효과가 스켈레촌 ① 하나뿐이다.
    """
    declared = [
        str(entry.definition.effect_ref)
        for entry in EFFECT_LIBRARY
        if entry.definition.resolution_skip is not None
        and entry.definition.resolution_skip.when_target_unusable
    ]
    assert declared == [str(SKELETON_EFFECT)], declared
    #: 그리고 대상 지정으로 선언된 **몬스터** 효과도 이것 하나다.
    targeting = [
        str(entry.definition.effect_ref)
        for entry in EFFECT_LIBRARY
        if any(
            binding.spec.requirement is TargetRequirement.TARGETING
            for binding in entry.definition.targets
        )
        and entry.definition.activation_zones is not None
    ]
    assert targeting == [str(SKELETON_EFFECT)], targeting


# ======================================================================
# F. 격리와 재생
# ======================================================================
@pytest.mark.real_card
def test_f01_a_fork_resolves_without_touching_the_original(repository):
    """🔴 분기가 치른 비용 · 걸어 둔 제한이 원본에 새지 않는다."""
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    duel.advance()
    before = _snapshot(duel)

    fork = Simulator(duel).fork()
    fork.advance()
    action = next(
        a
        for a in fork.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and a.effect_ref == SKELETON_EFFECT
    )
    assert fork.apply(action).accepted is True
    settle_chain(fork)

    assert [c.card_id for c in fork.state.zone(P0, Zone.MZONE)] == [GIRSU]
    assert len(
        fork.state.summon_limits.active(fork.state.turn.turn_number, P0)
    ) == 1
    #: 🔴 원본은 한 칸도 바뀌지 않았다.
    assert _snapshot(duel) == before
    assert _limits(duel) == ()


@pytest.mark.real_card
def test_f03_a_fork_does_not_break_the_original_relation(repository):
    """
    🔴 **한 분기의 이동이 다른 분기의 관계를 끊지 않는다** (요구 ⑩).

    사본에서 대상을 묘지 밖으로 보내고, **원본**에서 해결한다 — 원본은
    정상 소생이어야 한다.
    """
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    skeleton, girsu = grave
    offers = _offers(duel)
    assert duel.apply(offers[0]).accepted is True

    fork = Simulator(duel).fork()
    moved = [
        c for c in fork.state.zone(P0, Zone.GRAVE) if c.instance_id == girsu
    ][0]
    fork.state.move(moved, Zone.HAND, to_player=P0)
    #: 🔴 사본에서는 끊겼고 **원본에서는 살아 있다.**
    assert fork.state.relations.status(skeleton, SKELETON_EFFECT, girsu) is (
        False
    )
    assert (
        duel.state.relations.status(skeleton, SKELETON_EFFECT, girsu) is True
    )

    settle_chain(duel)
    assert _ids(duel, Zone.MZONE) == [GIRSU]


@pytest.mark.real_card
def test_f04_the_relation_is_part_of_the_state_hash(repository):
    """
    🔴 **관계가 살아 있는 판과 끊긴 판은 다른 상태다** (요구 ⑩). 빼면
    탐색의 중복 제거가 둘을 합치고, 한쪽에서만 일어나는 소환이 다른 쪽
    경로로 보고된다.

    🔴 **그런데 들어가는 것은 단절뿐이다.** 살아 있는 기록은 "해결을
    기다리는 대상 지정 링크가 있다" 와 같은 말이고, 체인은 정규 표현에서
    일부러 빠져 있다 — 그 사실을 관계 표로 우회해 들여놓지 않는다. 그래서
    발동만 한 판의 해시는 **한 글자도 달라지지 않고** (아래 ②-b 가 그것을
    센다), 단절이 일어난 판만 새 해시를 갖는다.
    """
    #: ① 기록이 비어 있는 판 — 정규 표현의 그 자리가 빈 tuple 이다.
    plain, *_rest = _board(repository, grave=(SKELETON, GIRSU))
    assert plain.state.relations.canonical_state() == ()

    #: ② 같은 판에서 발동만 한 뒤, 사본 하나에서 대상을 옮긴다.
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    skeleton, girsu = grave
    assert duel.apply(_offers(duel)[0]).accepted is True
    intact = Simulator(duel).fork()
    broken = Simulator(duel).fork()
    moved = [
        c for c in broken.state.zone(P0, Zone.GRAVE) if c.instance_id == girsu
    ][0]
    broken.state.move(moved, Zone.HAND, to_player=P0)
    broken.state.move(
        [
            c
            for c in broken.state.zone(P0, Zone.HAND)
            if c.instance_id == girsu
        ][0],
        Zone.GRAVE,
        to_player=P0,
    )

    #: 🔴 **자리는 같다** — 둘 다 묘지에 기르수 하나다.
    assert [c.card_id for c in intact.state.zone(P0, Zone.GRAVE)] == [
        c.card_id for c in broken.state.zone(P0, Zone.GRAVE)
    ]
    #: 🔴 **그런데 다른 상태다** — 끊긴 관계가 정규 표현에 들어 있다.
    assert intact.state.relations.canonical_state() != (
        broken.state.relations.canonical_state()
    )
    assert intact.state.state_hash() != broken.state.state_hash()

    #: ②-b 🔴 **살아 있는 기록은 해시를 움직이지 않는다.** 같은 판에서
    #: 기록만 지워 보면 (시험용 조작이다 — 실제 경로에는 이런 판이 없다)
    #: 해시가 같다. 반대로 끊긴 기록은 위에서 본 대로 해시를 바꾼다.
    #: 그래서 이 변경으로 **기존 판의 해시가 하나도 움직이지 않았다** —
    #: 대상 지정 효과가 해결을 기다리는 판까지 포함해서다.
    forgotten = Simulator(duel).fork()
    assert len(forgotten.state.relations) == 1
    forgotten.state.relations.clear()
    assert forgotten.state.relations.canonical_state() == ()
    assert forgotten.state.state_hash() == intact.state.state_hash()
    assert forgotten.state.state_hash() != broken.state.state_hash()

    #: ③ 해결하면 결과도 다르다 — 그것이 둘을 합칠 수 없는 이유다.
    settle_chain(intact)
    settle_chain(broken)
    assert [c.card_id for c in intact.state.zone(P0, Zone.MZONE)] == [GIRSU]
    assert [c.card_id for c in broken.state.zone(P0, Zone.MZONE)] == []


@pytest.mark.real_card
def test_f05_the_record_is_cleaned_up_after_the_link_resolves(repository):
    """
    🔴 **체인이 끝나면 기록이 남지 않는다** (요구 ⑥). 남겨 두면 판의 정규
    표현에 쓸모없는 기록이 쌓이고, 같은 카드가 같은 효과를 다시 발동할 때
    지난 번 관계가 보인다.
    """
    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    skeleton, girsu = grave
    assert duel.apply(_offers(duel)[0]).accepted is True
    assert len(duel.state.relations) == 1
    settle_chain(duel)
    #: 🔴 해결이 끝났으므로 기록이 지워졌다.
    assert len(duel.state.relations) == 0
    assert duel.state.relations.canonical_state() == ()
    assert (
        duel.state.relations.status(skeleton, SKELETON_EFFECT, girsu) is None
    )


@pytest.mark.real_card
def test_f02_the_same_input_reproduces_the_same_state(repository):
    """🔴 같은 시작 상태 · 같은 행동이면 같은 해시가 나온다."""
    hashes = []
    for _ in range(2):
        duel, _m, _t, _e, grave, _h = _board(
            repository, grave=(SKELETON, GIRSU)
        )
        offers = _offers(duel)
        duel.apply(offers[0])
        settle_chain(duel)
        hashes.append(_snapshot(duel))
    assert hashes[0] == hashes[1]


# ======================================================================
# G. 시작 패부터의 전체 경로 (B 계층)
# ======================================================================
@pytest.mark.real_card
def test_g01_the_whole_line_runs_from_the_opening_hand(repository):
    """
    🔴 **이 Phase 의 세 번째 본문.** 시작 패와 레시피만 주고, 그 뒤의 모든
    상태 변화를 **엔진이** 만든다 — 손으로 판을 만들지 않는다.
    """
    from app.main import opening_wiring
    from deck.combo_policy import (
        ORCUST_SKELETON_LONGIRSU_LINE as line,
        line_progress,
    )
    from deck.opening import build_opening, execute_opening
    from deck.recipe import parse_recipe

    parsed = parse_recipe(line.recipe_ydk, repository)
    assert parsed.draft is not None
    chooser, triggers = opening_wiring(repository, line)
    setup = build_opening(
        repository,
        parsed.draft,
        list(line.hand),
        chooser=chooser,
        triggers=triggers,
    )
    assert setup.can_run, setup.blockers
    run = execute_opening(setup, repository, choose=line.policy())
    progress = line_progress(run, line)

    assert progress.completed, progress.describe_ko()
    assert progress.done == 6
    assert progress.blocked_at is None
    kinds = [step.kind for step in run.steps if step.accepted]
    assert kinds[:6] == [
        "normal_summon",
        "activate_effect",
        "activate_effect",
        "link_summon",
        "activate_effect",
        "link_summon",
    ], kinds

    state = setup.duel.state
    #: 🔴 **최종 자원** — 롱기르수가 엑스트라 몬스터 존에 있다.
    assert [c.card_id for c in state.zone(P0, Zone.EMZONE)] == [LONGIRSU]
    assert [c.card_id for c in state.zone(P0, Zone.MZONE)] == []
    #: 소재가 된 갈라테아와 기르수가 묘지에 있다.
    assert sorted(c.card_id for c in state.zone(P0, Zone.GRAVE)) == sorted(
        [GALATEA, GIRSU]
    )
    #: 비용으로 제외된 둘.
    assert sorted(c.card_id for c in state.zone(P0, Zone.REMOVED)) == sorted(
        [DIBER, SKELETON]
    )
    #: 🔴 **어둠 속성 제한이 두 번 걸렸고** 두 링크 소환이 그것을 지났다.
    limits = state.summon_limits.active(state.turn.turn_number, P0)
    assert sorted(limit.source_card_id for limit in limits) == sorted(
        [DIBER, SKELETON]
    )
    assert {limit.attribute for limit in limits} == {"DARK"}


@pytest.mark.real_card
def test_g02_the_revived_girsu_does_not_fire_its_summon_trigger_again(
    repository,
):
    """
    🔴 **특수 소환 쪽 유발은 미지원이다 — 이번 범위에서 더하지 않았다.**

    ``c69811710.lua`` 는 ``e1``(``EVENT_SUMMON_SUCCESS``) 과
    ``e2``(``EVENT_SPSUMMON_SUCCESS``) 를 **다른 효과로** 적는데 이
    저장소는 ``e[0]`` 만 등재했다. 그래서 소생한 기르수는 ① 을 다시 쓰지
    않고, **일반 소환 유발이 잘못 다시 발동되지도 않는다.**
    """
    assert entry_for(EffectRef(GIRSU, 1)) is None
    registered = sorted(
        entry.definition.effect_ref.ordinal
        for entry in EFFECT_LIBRARY
        if entry.card_id == GIRSU
    )
    assert registered == [0, 2]

    duel, _m, _t, _e, grave, _h = _board(repository, grave=(SKELETON, GIRSU))
    offers = _offers(duel)
    duel.apply(offers[0])
    settle_chain(duel)
    assert _ids(duel, Zone.MZONE) == [GIRSU]
    #: 🔴 소생 뒤에 기르수 ① 의 발동 기회가 생기지 않는다.
    duel.advance()
    girsu_offers = [
        action
        for action in duel.legal_actions(P0).allowed
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
        and action.effect_ref == EffectRef(GIRSU, 0)
    ]
    assert girsu_offers == []


@pytest.mark.real_card
def test_g03_the_line_replays_to_the_same_board_from_a_fresh_state(repository):
    """
    🔴 **새 초기 상태에서 전체 경로가 재생된다** — 비용 · 대상 지정 · 소생 ·
    제한 · 링크 소재를 모두 포함해서.

    🔴 **탐색이 만든 최종 상태를 내보내는 것이 아니다.** 같은 입력으로
    ``build_opening`` 을 **다시** 불러 만든 판에서 여섯 걸음을 다시 밟고,
    두 판의 **해시 · 제한 · 자리**를 비교한다.
    """
    from app.main import opening_wiring
    from deck.combo_policy import (
        ORCUST_SKELETON_LONGIRSU_LINE as line,
        line_progress,
    )
    from deck.opening import build_opening, execute_opening
    from deck.recipe import parse_recipe

    def once():
        parsed = parse_recipe(line.recipe_ydk, repository)
        chooser, triggers = opening_wiring(repository, line)
        setup = build_opening(
            repository,
            parsed.draft,
            list(line.hand),
            chooser=chooser,
            triggers=triggers,
        )
        assert setup.can_run, setup.blockers
        run = execute_opening(setup, repository, choose=line.policy())
        assert line_progress(run, line).completed
        state = setup.duel.state
        return (
            state.state_hash(),
            state.summon_limits.canonical_state(),
            tuple(
                tuple(card.card_id for card in state.zone(P0, zone))
                for zone in (
                    Zone.MZONE,
                    Zone.EMZONE,
                    Zone.GRAVE,
                    Zone.REMOVED,
                    Zone.HAND,
                )
            ),
        )

    first = once()
    second = once()
    assert first == second
    #: 🔴 그 재생이 **실제로 이 Phase 의 일을 지난다** — 비용으로 제외된
    #: 둘과 걸린 제한 둘이 해시와 함께 같다.
    assert sorted(first[2][3]) == sorted([DIBER, SKELETON])
    assert first[2][1] == (LONGIRSU,)
    assert len(first[1]) == 2, first[1]


# ======================================================================
# H. 기존 경로 · 기존 경계가 그대로인가
# ======================================================================
@pytest.mark.real_card
def test_h01_the_diber_no_candidate_branch_still_registers_the_limit(
    repository,
):
    """🔴 6-AO 후속이 고친 자리가 그대로다 (범위가 다르다는 것을 함께 센다)."""
    duel, _m, _t, _e, grave, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    duel.advance()
    action = next(
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and a.effect_ref == DIBER_EFFECT
    )
    assert duel.apply(action).accepted is True
    state = duel.state
    only = [c for c in state.zone(P0, Zone.DECK) if c.card_id == SKELETON][0]
    state.move(only, Zone.GRAVE, to_player=P0)
    settle_chain(duel)

    assert _ids(duel, Zone.MZONE) == [GIRSU]
    limits = _limits(duel)
    assert len(limits) == 1
    assert limits[0].source_card_id == DIBER


@pytest.mark.real_card
def test_h02_the_three_earlier_lines_still_complete(repository):
    """
    🔴 **기존 경로를 바꾸지 않았다.** 토큰 경로와 『성장』 없는 갈라테아
    경로를 포함해 네 경로가 그대로 돈다.
    """
    from app.main import opening_wiring
    from deck.combo_policy import COMBO_LINES, line_progress
    from deck.opening import build_opening, execute_opening
    from deck.recipe import parse_recipe

    assert len(COMBO_LINES) == 5
    for name in (
        "orcust-girsu",
        "orcust-girsu-token",
        "orcust-harp-horror",
        "orcust-token-diber",
    ):
        line = COMBO_LINES[name]
        parsed = parse_recipe(line.recipe_ydk, repository)
        chooser, triggers = opening_wiring(repository, line)
        setup = build_opening(
            repository,
            parsed.draft,
            list(line.hand),
            chooser=chooser,
            triggers=triggers,
        )
        assert setup.can_run, (name, setup.blockers)
        run = execute_opening(setup, repository, choose=line.policy())
        progress = line_progress(run, line)
        assert progress.completed, (name, progress.describe_ko())
