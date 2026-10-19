"""
Phase 6-P — 다중 대상 선택 및 효과 해결 경로 검증.

막고 있던 것은 대상 모델이 아니었다
-----------------------------------
조사 결과 **복수 선택을 표현하는 모델은 이미 전부 있었다.**

    ``ChoiceSpec.minimum`` / ``maximum``   몇 장을 고르는가 — **있었다**
    ``allow_duplicates``                   같은 카드를 두 번 — **있었다**
    ``TargetResolver._check_count``        부족 · 초과 · 중복 — **있었다**
    ``selections_for``                     N장을 이름에 짝지음 — **있었다**
    ``EffectExecutor``                     한 조작을 여러 장에 — **있었다**

없던 것은 **열거 한 줄**이었다. ``target_combinations`` 가 이렇게 적혀
있었다.

    if choice is None or choice.minimum != 1 or choice.maximum != 1:
        return []

그래서 벌금(92595643, 공식 텍스트 "자신은 패를 2장 버린다") 은 조합이
**0개**였고 ``legal_actions`` 에 오를 수 없었다. 손으로 2장을 지정하면
그때도 ``can_activate`` 가 ``VALID`` 였고 해결까지 갔다 — 즉 차단은
**발동도 해결도 아니라 후보 열거**에 있었다.

이 파일이 지키는 것
-------------------
**정확히 N장까지만 넓혔다.** 최소≠최대 · 자리 둘 이상 · 중복 허용 · 상한
초과는 :func:`~engine.target_bridge.unsupported_enumeration` 이 **이유의
이름을 대고** 빈 목록이 된다. 모르는 모양을 추측해서 열거하지 않는다.

**자르지 않는다.** 조합이 선언한 상한을 넘으면 일부를 돌려주는 대신
**열거를 포기한다.** 잘라서 주면 "legal_actions 가 전부다" 가 거짓이 되고
정책은 자기가 못 본 수가 있다는 것조차 모른다.

**장수를 조용히 깎지 않는다.** ``selections_for`` 는 가변 장수를 거부한다 —
"최대 2장" 효과에서 최소값 1장만 집어 들면 플레이어가 2장을 골랐다는
사실이 말없이 사라진다.

**대상 지정과 해결 시 선택을 가르지 않았다.** 모델은 구분하지만
(``TARGETING`` vs ``CHOOSING``) 실행 경로는 아직 양쪽을 같은 자리에서
받는다. 그것을 가르려면 체인 해결 절차가 새로 필요하고, 이 Phase 는 그것을
하지 않는다. 벌금은 ``CHOOSING`` 이므로 넓힌 것은 **기존 계약 안**이다.

🔴 **함정 관문은 그대로 닫혀 있다.** 벌금은 함정이고, 함정은
``TRAP_TRIGGER_MISSING`` (Phase 3-E-16) 때문에 ``ActionValidator`` 에서
``UNKNOWN`` 이다. 그래서 ``legal_actions`` 에는 여전히 오르지 않는다 — 이
Phase 가 그 관문을 열지 않았고, ``G`` 절이 그 사실을 **센다.**
"""

import ast
import itertools
import math
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidator
from engine.condition import ConditionContext, PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.duel import Duel, duel_components
from engine.effect.definition import EffectDefinition, EffectProvenance
from engine.effect.journal import EffectEvent, EventJournal
from engine.effect.library import EFFECT_LIBRARY, definition_registry, entry_for
from engine.effect.operation import CardOperation
from engine.effect.target import (
    PRIMARY_TARGET,
    SELF_TARGET,
    TargetBinding,
    TargetRef,
    TargetSpec,
)
from engine.effect.targeting import TargetLegality, TargetResolver
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.target_bridge import (
    MAX_TARGET_COMBINATIONS,
    UNSUPPORTED_COMBINATION_COUNT,
    UNSUPPORTED_DUPLICATE_CHOICE,
    UNSUPPORTED_MULTIPLE_BINDINGS,
    UNSUPPORTED_VARIABLE_COUNT,
    TargetBridgeError,
    chosen_bindings,
    required_target_count,
    selections_for,
    target_combinations,
    targets_from,
    unsupported_enumeration,
)
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "engine" / "target_bridge.py"
MINE, THEIRS = 0, 1

#: 벌금 — 공식 텍스트 "자신은 패를 2장 버린다" (``desc`` 그대로).
#: ``Duel.DiscardHand(p,nil,2,2,...)`` 이고 ``minimum == maximum == 2`` 다.
#: 🔴 등재된 효과 중 **유일한** 다중 선택이다 (``test_a01`` 이 센다).
FINE = 92595643
#: 강제 탈출 장치 — Phase 6-O 가 실행시킨 단일 대상 효과. 회귀용.
FORCEOUT = 94192409
#: 어니스트 — Phase 6-L 의 ``SELF_TARGET``. 회귀용.
HONEST = 37742478
#: 무정한 말살 — ``@primary`` (고른다) + ``@random`` (아무도 고르지 않는다).
RUTHLESS_DENIAL = 73148972
#: 어리석은 매장 — 대상이 **덱**에 있다. 관측 경계 회귀용.
FOOLISH_BURIAL = 81439173
#: 욕망의 항아리 — 대상이 없다.
POT_OF_GREED = 55144522
#: 싸이크론 — 단일 대상 ``TARGETING``. 파괴 판정 공백에서 멈춘다.
MYSTICAL_SPACE_TYPHOON = 5318639
#: 자기 미라화 — 단일 대상 ``TARGETING`` 이고 **관문 없이 실행된다**.
SELF_MUMMIFICATION = 15103313

LUSTER_DRAGON = 11091375  # 통상 몬스터 (6-O 의 룰북 줄이 덮는다)
BATTLE_OX = 5053103
#: 사이버 드래곤 — **효과 몬스터**. 어느 계층도 답하지 않는다 (6-O).
UNKNOWN_EFFECT_MONSTER = 70095154

FINE_REF = EffectRef(FINE, 0)
DEFINITIONS = definition_registry()


# ======================================================================
# 판 만들기 — 전부 실제 엔진으로
# ======================================================================


def staged(
    repository,
    *,
    hand=(),
    hand_fodder: int = 0,
    mine=(),
    theirs=(),
    opponent_hand: int = 0,
    journal=None,
):
    """
    메인 페이즈의 판 하나.

    ``hand_fodder`` 는 **고를 수 있는 패 카드**의 수다 (취옥의 비룡). 벌금의
    후보가 바로 그것이므로 조합 수를 이 값으로 조절한다.
    """
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [POT_OF_GREED] * 30),
        turn_player=MINE,
        seed=1,
    )
    sources = [
        state.create_instance(card_id, owner=MINE, zone=Zone.HAND).instance_id
        for card_id in hand
    ]
    fodder = [
        state.create_instance(
            LUSTER_DRAGON, owner=MINE, zone=Zone.HAND
        ).instance_id
        for _ in range(hand_fodder)
    ]
    placed = {MINE: [], THEIRS: []}
    for seat, layout in ((MINE, mine), (THEIRS, theirs)):
        for card_id in layout:
            card = state.create_instance(card_id, owner=seat, zone=Zone.HAND)
            state.move(
                card, Zone.MZONE, to_player=seat, position=Position.FACEUP_ATTACK
            )
            placed[seat].append(card.instance_id)
    if opponent_hand:
        state.draw(THEIRS, opponent_hand)
    state.turn.turn_number = 5
    state.turn.turn_player = MINE
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1),
        **duel_components(journal=journal),
    )
    return duel, sources, fodder, placed


def set_down(duel, instance: InstanceId) -> InstanceId:
    """세트한다 — 실제 ``SET_SPELL_TRAP`` 행위로."""
    step = duel.apply(PlayerAction.set_spell_trap(actor=MINE, source=instance))
    assert step.accepted, step.reason
    duel.state.turn.turn_number += 2
    duel.state.turn.set_phase(Phase.MAIN1)
    duel.priority = PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1)
    return instance


def fine_board(repository, *, fodder: int = 5, journal=None):
    """벌금을 세워 둔 판. 돌려주는 것은 (duel, 벌금, 패의 후보들)."""
    duel, (fine,), fodder_ids, _ = staged(
        repository, hand=(FINE,), hand_fodder=fodder, journal=journal
    )
    set_down(duel, fine)
    return duel, fine, fodder_ids


def resolver_for(duel, definition, source, binding=None):
    """규칙이 선언한 ``looked_at`` 을 열고 본 판정기와 문맥."""
    binding = binding if binding is not None else chosen_bindings(definition)[0]
    view = GameStateView.from_state(
        duel.state, viewer=MINE, looked_at=binding.spec.looked_at_zones()
    )
    context = ConditionContext(
        player=MINE, source=source, effect_ref=definition.effect_ref
    )
    return TargetResolver(view), context, binding


def verdict_for(duel, definition, source, chosen):
    resolver, context, binding = resolver_for(duel, definition, source)
    return resolver.validate(
        binding.spec, Selection(tuple(chosen)), context, binding.ref
    )


def force_resolve(duel, source, definition, targets):
    """
    허가를 손으로 넣고 발동 → 해결까지 돌린다.

    🔴 **이것은 "적법하다" 는 주장이 아니다.** 함정 유발 조건
    (``TRAP_TRIGGER_MISSING``) 은 이 Phase 의 범위가 아니므로, 그 관문만
    가정하고 **그 뒤의 경로**를 잰다. ``_force_execute``
    (``test_set_trap_timing_audit``) 와 같은 태도다.
    """
    action = PlayerAction.activate_effect(
        actor=MINE, source=source, effect_ref=definition.effect_ref, targets=targets
    )
    selections = selections_for(definition, action)
    permit = ValidationResult.valid("감사용 허가 — 함정 관문은 별개 BLOCKER")
    allowed = duel._activator.can_activate(
        duel.state, duel.chain, action, selections=selections, authorization=permit
    )
    if allowed.validity is not ActionValidity.VALID:
        return action, allowed, None
    activated = duel._activator.activate(
        duel.state, duel.chain, action, selections=selections, authorization=permit
    )
    placed = duel._place_activated(action)
    duel.chain = activated.chain
    steps = duel._resolver.resolve_all(duel.state, duel.chain)
    duel._placement.retire(duel.state, placed)
    return action, allowed, (steps[-1] if len(steps) else None)


def fabricated_definition(
    *,
    card_id: int = 999001,
    minimum: int = 2,
    maximum: int = 2,
    zones=frozenset({Zone.HAND}),
    allow_duplicates: bool = False,
    extra_binding: bool = False,
):
    """
    🔴 **지어낸 정의.** 저장소에 없는 모양을 재기 위한 것이다 (Phase 6-P).

    등재된 효과에는 "최소≠최대" · "자리 둘" · "중복 허용" 이 **하나도
    없다** (``test_a01`` 이 0건임을 센다). 그래서 그 가지를 밟으려면 모양을
    손으로 만들어야 한다 — 실제 카드로는 영원히 닿지 않는 코드가 거부를
    제대로 하는지 확인하기 위해서다.

    프로덕션에 카드 ID 분기를 넣지 않았으므로, 이 정의가 어느 카드인지는
    열거 결과에 영향을 주지 않는다 (``test_f04`` 가 AST 로 지킨다).
    """
    choice = ChoiceSpec(
        source=CandidateSource(zones=zones, owner=PlayerRef.CONTROLLER),
        minimum=minimum,
        maximum=maximum,
        chooser=PlayerRef.CONTROLLER,
        allow_duplicates=allow_duplicates,
    )
    targets = [TargetBinding(PRIMARY_TARGET, TargetSpec.choosing(choice))]
    operations = [CardOperation.discard(PRIMARY_TARGET)]
    if extra_binding:
        secondary = TargetRef("secondary")
        targets.append(
            TargetBinding(
                secondary,
                TargetSpec.choosing(
                    ChoiceSpec(
                        source=CandidateSource(
                            zones=frozenset({Zone.MZONE}),
                            owner=PlayerRef.CONTROLLER,
                        )
                    )
                ),
            )
        )
        #: 🔴 선언한 이름은 **반드시 쓰여야** 한다 — ``EffectDefinition``
        #: 이 "고르게 해 놓고 쓰지 않는 정의" 를 거부한다. 그 계약을
        #: 우회하지 않고 지킨다.
        operations.append(CardOperation.send_to_grave(secondary))
    return EffectDefinition(
        effect_ref=EffectRef(card_id, 0),
        source_card_id=card_id,
        targets=tuple(targets),
        operations=tuple(operations),
        provenance=EffectProvenance.hand_written(
            note="Phase 6-P 테스트용 — 저장소에 없는 모양을 재기 위한 정의"
        ),
    )


# ======================================================================
# A. 감사 — 기존 모델이 이미 무엇을 표현했는가 (§4-A · §14-1 · §14-2)
# ======================================================================


@pytest.mark.real_card
def test_a01_the_library_has_exactly_one_multi_select_and_no_variable_count():
    """
    🔴 **실측 — 등재된 다중 선택은 한 장, 가변 장수는 0건이다** (§14).

    이 수가 이 Phase 의 범위를 정했다. "모든 범주를 한꺼번에 구현하지
    않는다" (§6) 를 지킬 수 있는 것은 **실제로 필요한 범주가 하나**임을
    세었기 때문이다.
    """
    exact_one, multi, variable, optional, duplicates = [], [], [], [], []
    bindings = 0
    for entry in EFFECT_LIBRARY:
        for binding in entry.definition.targets:
            bindings += 1
            choice = binding.spec.choice
            if not isinstance(choice, ChoiceSpec):
                continue
            card = entry.definition.source_card_id
            if choice.minimum != choice.maximum:
                variable.append(card)
            elif choice.minimum == 1:
                exact_one.append(card)
            elif choice.minimum > 1:
                multi.append(card)
            if choice.minimum == 0:
                optional.append(card)
            if choice.allow_duplicates:
                duplicates.append(card)

    #: 🔴 17 → 18 (Phase 6-V, 기르수 ①). 기르수의 선택은 **정확히 1장**
    #: (``Duel.SelectMatchingCard(...,1,1,nil)``) 이므로 ``exact_one`` 이
    #: 5 → 6 이고, 여러 장 선택(``multi``)과 가변 장수(``variable``)는
    #: 그대로다 — 이 Phase 가 지키는 사실은 그 둘이다.
    assert len(EFFECT_LIBRARY) == 18, "정의 수가 바뀌면 이 Phase 를 다시 읽는다"
    assert bindings == 10
    assert multi == [FINE], multi
    assert len(exact_one) == 6, exact_one
    assert variable == [], "가변 장수 효과가 생겼다 — §6 을 다시 읽어야 한다"
    assert optional == [], optional
    assert duplicates == [], duplicates


@pytest.mark.real_card
def test_a02_more_than_one_chosen_binding_does_not_exist_yet():
    """**§4-A-4 — 서로 다른 종류의 대상을 각각 고르는 효과는 0건이다.**

    모델은 표현할 수 있다 (``targets`` 가 튜플이다). 표현할 수 없는 것이
    아니라 **등재된 것이 없다** — 그 둘을 섞어 적으면 안 된다.
    """
    many = [
        entry.definition.source_card_id
        for entry in EFFECT_LIBRARY
        if len(chosen_bindings(entry.definition)) > 1
    ]
    assert many == [], many
    #: 무정한 말살은 바인딩이 둘이지만 하나는 ``@random`` 이라 **고르는
    #: 사람이 없다** — 그래서 짝에서 빠지고 "자리 둘" 이 아니다.
    denial = DEFINITIONS.definition_for(EffectRef(RUTHLESS_DENIAL, 0))
    assert len(denial.targets) == 2
    assert len(chosen_bindings(denial)) == 1


@pytest.mark.real_card
def test_a03_the_official_text_says_exactly_two(repository):
    """
    🔴 **§5-1 · §6 — 장수의 근거는 공식 텍스트다.** 내가 센 것이 아니다.

    ``cards.cdb`` 의 ``desc`` 를 그대로 읽는다 — 번역하지 않고 비교한다.
    "최대 2장" 이 아니라 "2장" 이므로 ``minimum == maximum`` 이 옳다.
    """
    card = repository.get(FINE)
    assert card is not None
    assert card.desc == "자신은 패를 2장 버린다."
    assert card.desc_en == "Discard 2 cards."
    choice = chosen_bindings(entry_for(FINE_REF).definition)[0].spec.choice
    assert (choice.minimum, choice.maximum) == (2, 2)
    assert required_target_count(entry_for(FINE_REF).definition) == 2


@pytest.mark.real_card
def test_a04_the_count_rules_already_existed(repository):
    """
    🔴 **§4-A-7 · §12-A · §12-E — 부족 · 초과 · 중복은 이미 잡혔다.**

    이 Phase 가 만든 것이 아니다. ``TargetResolver._check_count`` 가
    처음부터 세 코드를 들고 있었고, 이 시험은 그것을 **확인**한다 —
    없던 것은 후보 열거뿐임을 증명하는 자리다.
    """
    duel, fine, fodder = fine_board(repository)
    definition = entry_for(FINE_REF).definition
    cases = (
        (fodder[:2], TargetLegality.LEGAL, ValidationCode.OK),
        (fodder[:1], TargetLegality.ILLEGAL, ValidationCode.TOO_FEW_SELECTED),
        (fodder[:3], TargetLegality.ILLEGAL, ValidationCode.TOO_MANY_SELECTED),
        ((), TargetLegality.ILLEGAL, ValidationCode.TOO_FEW_SELECTED),
        (
            (fodder[0], fodder[0]),
            TargetLegality.ILLEGAL,
            ValidationCode.DUPLICATE_SELECTION,
        ),
    )
    for chosen, legality, code in cases:
        found = verdict_for(duel, definition, fine, chosen)
        assert found.legality is legality, (len(chosen), found.reason)
        assert found.code is code, (len(chosen), found.reason)


@pytest.mark.real_card
def test_a05_the_executor_already_applied_one_operation_to_many_cards(repository):
    """
    **§4-C-5 — 실행기는 처음부터 여러 장을 받을 수 있었다.**

    한 ``AppliedOperation`` 에 ``instances`` 가 둘이고 ``ZoneMoved`` 가
    둘이다. 즉 "여러 장을 한 번에" 는 실행기의 공백이 아니었다.
    """
    journal = EventJournal()
    duel, fine, fodder = fine_board(repository, journal=journal)
    definition = entry_for(FINE_REF).definition
    combos = target_combinations(duel.state, MINE, definition, fine)
    _, _, last = force_resolve(duel, fine, definition, combos[0])
    assert last is not None and last.resolved

    effects = [e for e in journal if isinstance(e, EffectEvent)]
    assert len(effects) == 1, effects
    applied = effects[0].applied
    assert len(applied) == 1, "한 조작이다 — 두 조작으로 쪼개지 않았다"
    assert len(applied[0].instances) == 2, applied[0]
    assert len(effects[0].deltas) == 2, effects[0].deltas


# ======================================================================
# B. 정확히 N장 열거 (§12-A · §12-D · §9)
# ======================================================================


@pytest.mark.real_card
def test_b01_exactly_two_enumerates_every_pair(repository):
    """🔴 **§12-A — 후보 5장이면 조합이 ``C(5,2) = 10`` 개다** (전에는 0개)."""
    duel, fine, fodder = fine_board(repository, fodder=5)
    definition = entry_for(FINE_REF).definition
    combos = target_combinations(duel.state, MINE, definition, fine)
    assert len(combos) == math.comb(5, 2) == 10
    assert all(len(c) == 2 for c in combos)
    picked = {tuple(t.instance_id for t in c) for c in combos}
    assert picked == set(itertools.combinations(tuple(fodder), 2))


@pytest.mark.real_card
@pytest.mark.parametrize("fodder", [2, 3, 4, 6, 7])
def test_b02_the_count_follows_the_binomial(repository, fodder):
    """**후보 수가 바뀌면 조합 수가 ``C(n,2)`` 로 따라간다.** 상수가 아니다."""
    duel, fine, _ = fine_board(repository, fodder=fodder)
    combos = target_combinations(
        duel.state, MINE, entry_for(FINE_REF).definition, fine
    )
    assert len(combos) == math.comb(fodder, 2)


@pytest.mark.real_card
def test_b03_no_combination_repeats_an_instance(repository):
    """🔴 **§12-E · §13 — 한 조합 안에 같은 인스턴스가 두 번 들어가지 않는다.**

    검사로 막는 것이 아니라 ``itertools.combinations`` 가 **구조적으로**
    그렇다. 그래도 그 사실을 세어 둔다 — 열거 방식을 바꾸면 깨지도록.
    """
    duel, fine, _ = fine_board(repository, fodder=6)
    combos = target_combinations(
        duel.state, MINE, entry_for(FINE_REF).definition, fine
    )
    for combo in combos:
        ids = [t.instance_id for t in combo]
        assert len(set(ids)) == len(ids), ids
    #: 조합끼리도 중복되지 않는다 (같은 짝이 두 번 나오지 않는다).
    keys = [tuple(sorted(t.instance_id.value for t in c)) for c in combos]
    assert len(set(keys)) == len(keys)


@pytest.mark.real_card
def test_b04_the_order_is_deterministic(repository):
    """**§9 — 같은 판이면 같은 목록이다.** ``set`` 을 쓰지 않는다."""
    definition = entry_for(FINE_REF).definition
    runs = []
    for _ in range(3):
        duel, fine, _ = fine_board(repository, fodder=5)
        combos = target_combinations(duel.state, MINE, definition, fine)
        runs.append([tuple(t.instance_id.value for t in c) for c in combos])
    assert runs[0] == runs[1] == runs[2]
    #: 관측 순서의 **사전식**이다 — 첫 조합이 가장 앞의 두 장이다.
    assert runs[0][0] == tuple(sorted(runs[0][0]))
    assert runs[0] == sorted(runs[0])


@pytest.mark.real_card
def test_b05_same_card_id_different_instances_are_different_combinations(repository):
    """
    🔴 **§8-1 · §12-D — 카드 ID 가 같아도 인스턴스가 다르면 다른 조합이다.**

    후보 5장이 **전부 취옥의 비룡**인데 조합이 10개다. ID 로 동일성을
    판단했다면 1개여야 한다.
    """
    duel, fine, fodder = fine_board(repository, fodder=5)
    ids = {duel.state.find_instance(i).card_id for i in fodder}
    assert ids == {LUSTER_DRAGON}, "표본이 같은 카드여야 이 시험이 성립한다"
    combos = target_combinations(
        duel.state, MINE, entry_for(FINE_REF).definition, fine
    )
    assert len(combos) == 10
    assert len({tuple(t.instance_id for t in c) for c in combos}) == 10


@pytest.mark.real_card
def test_b06_each_combination_is_accepted_by_the_existing_validator(repository):
    """**열거한 10개가 전부 기존 적법성 판정을 통과한다.**

    열거가 적법성을 대신하지 않는다는 뜻이기도 하다 — 관문은 둘이고,
    여기서는 둘이 같은 답을 낸다.
    """
    duel, fine, _ = fine_board(repository, fodder=5)
    definition = entry_for(FINE_REF).definition
    combos = target_combinations(duel.state, MINE, definition, fine)
    assert len(combos) == 10
    for combo in combos:
        chosen = [t.instance_id for t in combo]
        found = verdict_for(duel, definition, fine, chosen)
        assert found.legality is TargetLegality.LEGAL, (chosen, found.reason)
        selections = selections_for(
            definition,
            PlayerAction.activate_effect(
                actor=MINE, source=fine, effect_ref=FINE_REF, targets=combo
            ),
        )
        assert len(selections) == 1
        assert selections[0].ref == PRIMARY_TARGET
        assert selections[0].selection.chosen == tuple(chosen)


# ======================================================================
# C. 후보 부족 (§12-C)
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize("fodder", [0, 1])
def test_c01_too_few_candidates_enumerates_nothing(repository, fodder):
    """
    🔴 **§12-C · §6 — 후보가 2장보다 적으면 조합이 없다.**

    "임의로 선택 수를 줄이지 않는다" (§6) 가 여기다. 1장만 있을 때 1장짜리
    조합을 만들면 공식 텍스트("2장")를 엔진이 고쳐 쓴 셈이 된다.
    """
    duel, fine, _ = fine_board(repository, fodder=fodder)
    combos = target_combinations(
        duel.state, MINE, entry_for(FINE_REF).definition, fine
    )
    assert combos == [], combos


@pytest.mark.real_card
def test_c02_too_few_candidates_is_not_a_refusal_of_the_shape(repository):
    """**후보 부족과 모양 미지원은 다른 사실이다.**

    ``unsupported_enumeration`` 은 ``None`` (모양은 지원한다) 인데도 조합이
    0개다. 둘을 한 값으로 합치면 "이 효과를 영원히 못 쓴다" 와 "지금 판에
    후보가 없다" 가 구분되지 않는다.
    """
    definition = entry_for(FINE_REF).definition
    assert unsupported_enumeration(definition) is None
    duel, fine, _ = fine_board(repository, fodder=1)
    assert target_combinations(duel.state, MINE, definition, fine) == []
    #: 그리고 후보가 늘면 같은 정의로 조합이 생긴다.
    duel2, fine2, _ = fine_board(repository, fodder=2)
    assert len(target_combinations(duel2.state, MINE, definition, fine2)) == 1


@pytest.mark.real_card
def test_c03_the_activation_condition_still_guards_the_hand_size(repository):
    """
    **§3-11 — 발동 조건은 그대로다.** 열거가 조건을 대신하지 않는다.

    벌금의 발동 조건은 ``ZoneCountAtLeast(CONTROLLER, HAND, 2)`` 이고,
    패가 1장이면 ``can_activate`` 가 거절한다 — 조합이 0개인 것과 **다른
    자리**의 거절이다.
    """
    duel, fine, fodder = fine_board(repository, fodder=1)
    definition = entry_for(FINE_REF).definition
    action = PlayerAction.activate_effect(
        actor=MINE,
        source=fine,
        effect_ref=FINE_REF,
        targets=targets_from((fodder[0], fodder[0])),
    )
    #: 모양이 2장이므로 다리는 통과시킨다 (적법성이 아니라 모양이다).
    selections = selections_for(definition, action)
    allowed = duel._activator.can_activate(
        duel.state,
        duel.chain,
        action,
        selections=selections,
        authorization=ValidationResult.valid("감사용"),
    )
    assert allowed.validity is not ActionValidity.VALID, allowed.reason


# ======================================================================
# D. 지원하지 않는 모양 — 이유의 이름을 댄다 (§6 · §13)
# ======================================================================


@pytest.mark.real_card
def test_d01_a_variable_count_is_refused_by_name():
    """
    🔴 **§6 · §12-B — "최대 N장" 은 아직 지원하지 않는다.**

    등재된 효과에 0건이므로 (``test_a01``) 규칙을 확정할 근거가 없다.
    "최대 2장" 이 곧 "0장도 된다" 는 뜻이 **아니고**, 그 최소값은 효과
    문장과 규칙이 정한다 (§6). 그래서 추측하지 않고 거부한다.
    """
    for minimum, maximum in ((1, 2), (0, 2), (0, 1), (2, 3)):
        definition = fabricated_definition(minimum=minimum, maximum=maximum)
        assert unsupported_enumeration(definition) == UNSUPPORTED_VARIABLE_COUNT


@pytest.mark.real_card
def test_d02_a_zero_count_choice_is_refused_too():
    """**"고를 것이 있는데 0장" 은 모순이다.** 빈 선택을 지어내지 않는다."""
    definition = fabricated_definition(minimum=0, maximum=0)
    assert unsupported_enumeration(definition) == UNSUPPORTED_VARIABLE_COUNT


@pytest.mark.real_card
def test_d03_two_chosen_bindings_are_refused_by_name():
    """
    🔴 **§6 — 자리가 둘이면 순서 규칙을 먼저 정해야 한다.**

    "어느 자리를 먼저 고르는가" 가 적법성을 바꾸는지 모르는 채로 곱집합을
    열거하면 엔진이 규칙을 지어낸 것이 된다.
    """
    definition = fabricated_definition(minimum=1, maximum=1, extra_binding=True)
    assert len(chosen_bindings(definition)) == 2
    assert unsupported_enumeration(definition) == UNSUPPORTED_MULTIPLE_BINDINGS


@pytest.mark.real_card
def test_d04_allowing_duplicates_is_refused_by_name():
    """**같은 카드를 두 번 고르는 효과는 등재에 0건이다.**"""
    definition = fabricated_definition(allow_duplicates=True)
    assert unsupported_enumeration(definition) == UNSUPPORTED_DUPLICATE_CHOICE


@pytest.mark.real_card
def test_d05_a_refused_shape_enumerates_nothing_on_a_real_board(repository):
    """
    **거부된 모양은 조합이 0개다** — 즉 후보가 되지 않는다 (NOT_REACHED).

    이유의 이름은 **진단용**이고, 행동은 "없던 허가를 만들지 않는다" 다.
    """
    duel, _, fodder, _ = staged(repository, hand_fodder=6)
    source = fodder[0]
    for definition in (
        fabricated_definition(minimum=1, maximum=3),
        fabricated_definition(minimum=2, maximum=2, allow_duplicates=True),
        fabricated_definition(minimum=1, maximum=1, extra_binding=True),
    ):
        assert unsupported_enumeration(definition) is not None
        assert target_combinations(duel.state, MINE, definition, source) == []


@pytest.mark.real_card
def test_d06_selections_for_refuses_a_variable_count_instead_of_trimming(repository):
    """
    🔴 **§13 — 장수를 조용히 깎지 않는다.**

    ``take = choice.minimum`` 은 ``minimum == maximum`` 일 때만 참이다.
    "최대 2장" 효과에서 1장만 집어 들면 플레이어가 2장을 골랐다는 사실이
    **말없이** 사라진다. 그래서 거부한다 — 미지원 절차를 자동 성공으로
    처리하지 않는다.
    """
    duel, _, fodder, _ = staged(repository, hand_fodder=3)
    definition = fabricated_definition(minimum=1, maximum=2)
    action = PlayerAction.activate_effect(
        actor=MINE,
        source=fodder[0],
        effect_ref=definition.effect_ref,
        targets=targets_from(fodder[:1]),
    )
    with pytest.raises(TargetBridgeError) as error:
        selections_for(definition, action)
    assert UNSUPPORTED_VARIABLE_COUNT in str(error.value)


@pytest.mark.real_card
def test_d07_multiple_bindings_still_pass_through_selections_for(repository):
    """
    **거부는 장수에만 건다.** 자리가 둘인 것은 환전 자체는 할 수 있다 —
    못 하는 것은 **열거**이고, 둘을 같은 거부로 묶으면 고칠 곳을 틀리게
    가리킨다.
    """
    duel, _, fodder, placed = staged(
        repository, hand_fodder=3, mine=(LUSTER_DRAGON,)
    )
    definition = fabricated_definition(minimum=1, maximum=1, extra_binding=True)
    action = PlayerAction.activate_effect(
        actor=MINE,
        source=fodder[0],
        effect_ref=definition.effect_ref,
        targets=targets_from((fodder[1], placed[MINE][0])),
    )
    selections = selections_for(definition, action)
    assert [str(s.ref) for s in selections] == ["@primary", "@secondary"]
    assert selections[0].selection.chosen == (fodder[1],)
    assert selections[1].selection.chosen == (placed[MINE][0],)


# ======================================================================
# E. 상한 — 자르지 않고 포기한다 (§13)
# ======================================================================


@pytest.mark.real_card
def test_e01_the_ceiling_is_declared_and_is_not_a_rule():
    """**상한은 선언한 공학적 수치이고, 룰북에서 온 것이 아니다.**

    그 사실을 주석이 적고 있어야 한다 — 적지 않으면 다음 사람이 이것을
    유희왕 규칙으로 읽는다.
    """
    assert MAX_TARGET_COMBINATIONS == 256
    text = BRIDGE.read_text(encoding="utf-8")
    assert "유희왕 규칙이 아니라" in text
    assert "자르지 않고" in text


@pytest.mark.real_card
def test_e02_under_the_ceiling_everything_is_enumerated(repository):
    """``C(10,5) = 252`` 는 상한 아래다 — 전부 열거한다."""
    duel, _, fodder, _ = staged(repository, hand_fodder=10)
    definition = fabricated_definition(minimum=5, maximum=5)
    assert math.comb(10, 5) == 252 <= MAX_TARGET_COMBINATIONS
    combos = target_combinations(duel.state, MINE, definition, fodder[0])
    assert len(combos) == 252


@pytest.mark.real_card
def test_e03_over_the_ceiling_gives_nothing_rather_than_a_truncated_list(repository):
    """
    🔴 **``C(11,5) = 462`` 는 상한 위다 — 빈 목록이다.**

    252개를 돌려주고 나머지를 버리면 "legal_actions 가 전부다" 가 거짓이
    된다. 포기하면 지금까지와 똑같이 **후보가 아니다** — 안전한 쪽으로
    틀린다.
    """
    duel, _, fodder, _ = staged(repository, hand_fodder=11)
    definition = fabricated_definition(minimum=5, maximum=5)
    assert math.comb(11, 5) == 462 > MAX_TARGET_COMBINATIONS
    assert unsupported_enumeration(definition, 11) == UNSUPPORTED_COMBINATION_COUNT
    combos = target_combinations(duel.state, MINE, definition, fodder[0])
    assert combos == [], f"{len(combos)}개를 잘라서 돌려줬다"


@pytest.mark.real_card
def test_e04_the_ceiling_looks_at_the_filtered_pool(repository):
    """
    **상한은 거른 뒤의 후보 수로 본다.**

    가려진 카드를 세어서 상한을 넘겼다고 하면, 쓸 수 없는 후보 때문에 쓸
    수 있는 효과가 막힌다. 덱에 30장이 있어도 패의 후보만 센다.
    """
    from engine.target_bridge import decided_at_resolution

    duel, _, fodder, _ = staged(repository, hand_fodder=10)
    assert len(duel.state.player(MINE).zones[Zone.DECK]) == 30

    #: ① **가려진 자리를 보는 고르기는 열거하지 않는다** (Phase 6-Z). 덱의
    #:    30장이 상한을 넘기지 않는 것은 그대로이고, 이유가 더 강해졌다 —
    #:    아예 발동 시점에 정하지 않는다.
    hidden = fabricated_definition(
        minimum=5, maximum=5, zones=frozenset({Zone.HAND, Zone.DECK})
    )
    assert [decided_at_resolution(b.spec) for b in hidden.targets] == [True]
    assert target_combinations(duel.state, MINE, hidden, fodder[0]) == [()]

    #: ② **보이는 자리만 보는 고르기는 거른 뒤의 수로 상한을 본다.** 패의
    #:    10장에서 5장 → 252 조합이고, 전부 평소 관측에 보이는 카드다.
    definition = fabricated_definition(
        minimum=5, maximum=5, zones=frozenset({Zone.HAND})
    )
    assert [decided_at_resolution(b.spec) for b in definition.targets] == [False]
    combos = target_combinations(duel.state, MINE, definition, fodder[0])
    assert len(combos) == 252, "패의 10장을 세지 않았다"
    for combo in combos:
        for target in combo:
            assert duel.view(MINE).find(target.instance_id) is not None


@pytest.mark.real_card
def test_e05_the_shape_check_runs_before_candidates_are_counted():
    """
    **모양만으로 거를 수 있으면 후보를 세기 전에 거른다.**

    ``pool_size`` 를 주지 않은 호출이 상한을 보지 않는다는 뜻이고, 그래서
    모양이 틀린 정의에서 후보 수집 비용을 치르지 않는다.
    """
    definition = fabricated_definition(minimum=5, maximum=5)
    assert unsupported_enumeration(definition) is None
    assert unsupported_enumeration(definition, 10) is None
    assert unsupported_enumeration(definition, 11) == UNSUPPORTED_COMBINATION_COUNT


@pytest.mark.real_card
def test_e06_enumeration_only_proceeds_when_the_count_is_fixed():
    """
    🔴 **불변식 — 열거가 진행되는 모양은 반드시 ``minimum == maximum`` 이다.**

    ``target_combinations`` 의 ``take = choice.minimum`` 이 옳은 이유가 이
    불변식이고, 그래서 ``take = choice.maximum`` 으로 바꿔도 **같은
    프로그램**이다 (mutation M11 이 생존한 이유 — 테스트의 구멍이 아니라
    **동등 변이**다).

    이 시험은 그 동등성을 **명시한다.** 누군가 가변 장수를 열거하도록
    관문을 풀면 여기서 깨지고, 그때 ``minimum`` 과 ``maximum`` 중 어느
    것을 집어야 하는지 §6 을 다시 읽게 된다.
    """
    shapes = [
        (minimum, maximum)
        for minimum in range(0, 4)
        for maximum in range(0, 4)
        if maximum >= minimum
    ]
    enumerable = []
    for minimum, maximum in shapes:
        definition = fabricated_definition(minimum=minimum, maximum=maximum)
        if unsupported_enumeration(definition) is None:
            enumerable.append((minimum, maximum))
    assert enumerable == [(1, 1), (2, 2), (3, 3)], enumerable
    assert all(minimum == maximum for minimum, maximum in enumerable)

    #: 등재된 효과에서도 같다 — 열거되는 것은 전부 고정 장수다.
    for entry in EFFECT_LIBRARY:
        if unsupported_enumeration(entry.definition) is not None:
            continue
        for binding in chosen_bindings(entry.definition):
            choice = binding.spec.choice
            if isinstance(choice, ChoiceSpec):
                assert choice.minimum == choice.maximum, entry.definition.effect_ref


# ======================================================================
# F. 금지 사항 — 무엇을 만들지 않았는가 (§1 · §10 · §16)
# ======================================================================


@pytest.mark.real_card
def test_f01_only_one_production_file_changed():
    """**새 대상 선택 엔진을 만들지 않았다.** 바뀐 프로덕션은 한 파일이다."""
    for name in (
        "target_engine.py",
        "target_graph.py",
        "target_search.py",
        "multi_target.py",
        "selection_engine.py",
    ):
        assert not (ROOT / "engine" / name).exists(), name
    text = BRIDGE.read_text(encoding="utf-8")
    assert "새 Target Engine" in text


@pytest.mark.real_card
def test_f02_no_new_data_type_was_added():
    """
    🔴 **§10 — 새 데이터 타입 0개.**

    미지원 사유는 ``str`` 상수다 — ``engine.effect.semantics`` 의
    ``MISSING_*`` 와 같은 모양이고, 새 ``Enum`` 이나 ``dataclass`` 를 만들지
    않았다.
    """
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    classes = [
        node.name for node in tree.body if isinstance(node, ast.ClassDef)
    ]
    assert classes == ["TargetBridgeError"], classes
    for name in (
        UNSUPPORTED_VARIABLE_COUNT,
        UNSUPPORTED_MULTIPLE_BINDINGS,
        UNSUPPORTED_DUPLICATE_CHOICE,
        UNSUPPORTED_COMBINATION_COUNT,
    ):
        assert isinstance(name, str)
        assert "(" in name and ")" in name, "이름과 설명을 함께 적는다"


@pytest.mark.real_card
def test_f03_the_enumeration_lives_in_exactly_one_place():
    """**조합을 만드는 자리가 하나다.** 두 곳이 같은 규칙을 갖지 않는다."""
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"combinations", "combinations_with_replacement"}
    ]
    assert len(sites) == 1, [ast.unparse(s) for s in sites]
    assert ast.unparse(sites[0]) == "itertools.combinations(pool, take)"


@pytest.mark.real_card
def test_f04_the_bridge_never_branches_on_a_card_id():
    """
    🔴 **§3-5 · §3-10 — 카드 ID 와 카드명으로 대상 선택을 하드코딩하지
    않는다.**

    다리 전체에 카드 번호 리터럴이 하나도 없다 (문서 문자열은 뺀다 —
    근거를 적는 것은 분기가 아니다).
    """
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    numbers = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
    ]
    assert all(value <= MAX_TARGET_COMBINATIONS for value in numbers), numbers
    assert "card_id" not in {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }


@pytest.mark.real_card
def test_f05_the_model_still_distinguishes_targeting_from_choosing():
    """
    🔴 **§7 — 대상 지정과 해결 시 선택을 가르지 않았다 (가를 수 있다고
    주장하지도 않는다).**

    모델은 둘을 구분한다. 그런데 ``is_targeting`` 을 읽는 프로덕션 자리는
    **설명 문구 하나뿐**이다 — 즉 실행 경로는 아직 양쪽을 같은 자리에서
    받는다. 벌금은 ``CHOOSING`` 이므로 이 Phase 가 넓힌 것은 그 기존 계약
    **안**이고, 가르는 일은 체인 해결 절차가 필요하므로 하지 않았다 (§9).

    이 시험은 그 공백을 **못 박는다.** 누군가 가르기 시작하면 깨지고,
    그때 §7 을 다시 읽게 된다.
    """
    fine_spec = chosen_bindings(entry_for(FINE_REF).definition)[0].spec
    forceout_spec = chosen_bindings(
        DEFINITIONS.definition_for(EffectRef(FORCEOUT, 0))
    )[0].spec
    assert fine_spec.is_targeting is False, "벌금은 대상 지정이 아니다"
    assert forceout_spec.is_targeting is True, "강제 탈출 장치는 대상 지정이다"

    #: 그런데 다리는 둘을 **같은 자리**에서 받는다.
    assert unsupported_enumeration(entry_for(FINE_REF).definition) is None
    assert (
        unsupported_enumeration(
            DEFINITIONS.definition_for(EffectRef(FORCEOUT, 0))
        )
        is None
    )
    #: 🔴 **읽는 프로덕션 자리가 둘이 되었다** (Phase 6-Z). 이 시험이 못
    #: 박아 둔 공백에 실제로 손이 닿았고, 그래서 여기서 **무엇을 갈랐는지**
    #: 적는다.
    #:
    #: 6-Z 가 가른 축은 "대상 지정 대 해결 시 선택" 이 **아니다** — 가려진
    #: 자리를 보는 고르기만 해결 시점으로 미룬다. ``is_targeting`` 은 그
    #: 판단에서 **배제 조건**으로만 쓰인다: 대상 지정은 미루지 않는다. 그래서
    #: 대상 지정 효과의 경로는 한 글자도 달라지지 않았다.
    readers = []
    for path in sorted((ROOT / "engine").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "is_targeting":
                readers.append(path.relative_to(ROOT).as_posix())
    assert readers == [
        "engine/effect/target.py",
        "engine/target_bridge.py",
    ], readers

    #: 🔴 **다리에서 읽는 자리는 하나이고, 그것은 미루기를 막는 자리다.**
    from engine.target_bridge import decided_at_resolution

    bridge_tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    owners = [
        node.name
        for node in ast.walk(bridge_tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(inner, ast.Attribute) and inner.attr == "is_targeting"
            for inner in ast.walk(node)
        )
    ]
    assert owners == ["decided_at_resolution"], owners
    #: 그리고 대상 지정은 **미뤄지지 않는다** — 강제 탈출 장치로 센다.
    assert (
        decided_at_resolution(forceout_spec) is False
    ), "대상 지정을 미루면 기존 발동 경로가 달라진다"
    assert decided_at_resolution(fine_spec) is False, "패는 가려진 자리가 아니다"


# ======================================================================
# G. 🔴 남은 관문 — 함정이라서 막힌다 (§17 · §18-17)
# ======================================================================


@pytest.mark.real_card
def test_g01_the_multi_target_effect_is_now_a_legal_action(repository):
    """
    🔴 **Phase 6-Q 가 함정 관문을 열었다 — 이 Phase 의 남은 BLOCKER 였다.**

    6-P 는 여기서 멈췄다: 조합은 10개가 되었지만 벌금은 **함정**이고,
    함정은 ``TRAP_TRIGGER_MISSING`` (Phase 3-E-16) 때문에
    ``ActionValidator`` 에서 ``UNKNOWN`` 이었다. 그 문장이 적은 이유는
    *"유발 조건을 효과마다 구분할 수 없다 — ``SetCode(EVENT_*)`` 가
    ``EffectDefinition`` 에 없다"* 였고, 6-P 는 그것을 **별개 BLOCKER** 로
    보고했다.

    🔴 **6-Q 가 바로 그 칸을 만들었다** (``EffectDefinition.
    activation_waits_for_event``). 그래서 이제 **열거한 조합 10개가 그대로
    적법한 ``PlayerAction`` 10개**가 된다 — 6-P 가 만든 것이 실제로
    쓰이게 되었고, 이 시험의 이름도 과거형이 아니라 현재형으로 바꿨다.

    등록소를 받지 못한 검증기는 **여전히 모른다** — "적지 않았다" 는
    6-Q 뒤에도 허가가 아니다. 그 축을 함께 센다.
    """
    duel, fine, _ = fine_board(repository, fodder=5)
    definition = entry_for(FINE_REF).definition
    combos = target_combinations(duel.state, MINE, definition, fine)
    assert len(combos) == 10, "열거는 6-P 가 풀었다"

    #: ``set_down`` 이 이미 다음 턴으로 넘겨 두었다 (이 파일의 헬퍼) —
    #: 세트한 턴 제약 자체는 Phase 6-Q 의 타깃 시험이 따로 센다.
    assert duel._set_this_turn(
        PlayerAction.activate_effect(
            actor=MINE, source=fine, effect_ref=FINE_REF, targets=combos[0]
        )
    ) is False

    #: 🔴 **열거한 조합 전부**가 후보가 된다.
    activations = [
        action
        for action in duel.legal_actions(MINE).allowed
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
        and action.effect_ref == FINE_REF
    ]
    assert len(activations) == 10, len(activations)
    assert {tuple(t.instance_id for t in a.targets) for a in activations} == {
        tuple(t.instance_id for t in combo) for combo in combos
    }

    #: 등록소를 받지 못한 검증기는 여전히 ``UNKNOWN`` 이다.
    verdict = ActionValidator(duel.view(MINE)).validate(
        PlayerAction.activate_effect(
            actor=MINE, source=fine, effect_ref=FINE_REF, targets=combos[0]
        )
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED


@pytest.mark.real_card
def test_g02_the_same_gate_closes_on_the_single_target_trap(repository):
    """
    **그 관문은 다중 대상과 무관했다** — 단일 대상 함정도 같은 자리에서
    막혔다. 즉 6-P 의 남은 BLOCKER 는 "여러 장" 이 아니라 "함정" 이었고,
    🔴 **Phase 6-Q 가 그것을 열었다.**

    이 시험은 이제 **등록소를 받지 못한 검증기**를 잰다 — 그쪽은 여전히
    ``UNKNOWN`` 이다. 재는 사실(막는 것이 다중 대상이 아니다)은 그대로이고,
    관문이 **카드 종류가 아니라 적어 둔 사실**에 달려 있음을 보인다.
    """
    duel, (forceout,), _, _ = staged(
        repository, hand=(FORCEOUT,), theirs=(LUSTER_DRAGON,)
    )
    set_down(duel, forceout)
    definition = DEFINITIONS.definition_for(EffectRef(FORCEOUT, 0))
    combos = target_combinations(duel.state, MINE, definition, forceout)
    assert len(combos) == 1
    verdict = ActionValidator(duel.view(MINE)).validate(
        PlayerAction.activate_effect(
            actor=MINE,
            source=forceout,
            effect_ref=EffectRef(FORCEOUT, 0),
            targets=combos[0],
        )
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED


# ======================================================================
# H. 🔴 실제 다중 대상 효과 실행 (§11 · §12-N · §18-11)
# ======================================================================


@pytest.mark.real_card
def test_h01_the_engine_enumerated_combination_resolves_and_changes_the_state(
    repository,
):
    """
    🔴 **§11 · §18-11 — 엔진이 스스로 열거한 조합으로 해결되고 판이 바뀐다.**

    손으로 고른 두 장이 아니라 ``target_combinations`` 가 만든 조합을
    그대로 쓴다. 실측: 패 5 → 3, 묘지 0 → 3 (버린 2장 + 벌금 자신).

    허가만 손으로 넣는다 (``force_resolve``) — 함정 관문은 별개 BLOCKER
    이고 ``G`` 절이 그 사실을 따로 센다.
    """
    duel, fine, _ = fine_board(repository, fodder=5)
    definition = entry_for(FINE_REF).definition
    combos = target_combinations(duel.state, MINE, definition, fine)
    chosen = combos[0]
    picked = [t.instance_id for t in chosen]

    before = {
        zone: len(duel.state.player(MINE).zones[zone])
        for zone in (Zone.HAND, Zone.GRAVE, Zone.SZONE)
    }
    action, allowed, last = force_resolve(duel, fine, definition, chosen)
    assert allowed.validity is ActionValidity.VALID, allowed.reason
    assert last is not None and last.resolved, last

    assert len(duel.state.player(MINE).zones[Zone.HAND]) == before[Zone.HAND] - 2
    assert len(duel.state.player(MINE).zones[Zone.GRAVE]) == before[Zone.GRAVE] + 3
    for instance in picked:
        assert duel.state.find_instance(instance).zone is Zone.GRAVE
    assert duel.state.find_instance(fine).zone is Zone.GRAVE
    assert len(duel.state.player(MINE).zones[Zone.SZONE]) == before[Zone.SZONE] - 1


@pytest.mark.real_card
def test_h02_a_different_combination_discards_different_cards(repository):
    """
    **조합마다 결과가 다르다.** 열거가 의미를 갖는다는 증거다 — 하나로
    뭉쳤다면 AI 가 무엇을 버릴지 말할 수 없다.
    """
    definition = entry_for(FINE_REF).definition
    outcomes = []
    for index in (0, 9):
        duel, fine, _ = fine_board(repository, fodder=5)
        combos = target_combinations(duel.state, MINE, definition, fine)
        picked = tuple(t.instance_id for t in combos[index])
        _, _, last = force_resolve(duel, fine, definition, combos[index])
        assert last is not None and last.resolved
        in_grave = tuple(
            i
            for i in picked
            if duel.state.find_instance(i).zone is Zone.GRAVE
        )
        assert in_grave == picked
        outcomes.append(tuple(i.value for i in picked))
    assert outcomes[0] != outcomes[1], outcomes


@pytest.mark.real_card
def test_h03_the_journal_records_what_actually_happened(repository):
    """
    🔴 **§12-O · §18-12 — EventJournal 이 실제 결과와 일치한다.**

    한 ``EffectEvent`` 안에 조작 하나(``DISCARD``) 와 인스턴스 둘, 그리고
    ``ZoneMoved`` 둘이 있다. 적용되지 않은 이동을 성공으로 적지 않는다.
    """
    journal = EventJournal()
    duel, fine, _ = fine_board(repository, fodder=5, journal=journal)
    definition = entry_for(FINE_REF).definition
    combos = target_combinations(duel.state, MINE, definition, fine)
    picked = tuple(t.instance_id for t in combos[0])
    _, _, last = force_resolve(duel, fine, definition, combos[0])
    assert last is not None and last.resolved

    effects = [event for event in journal if isinstance(event, EffectEvent)]
    assert len(effects) == 1
    event = effects[0]
    assert event.effect_ref == FINE_REF
    assert event.actor == MINE
    assert event.source == fine
    assert len(event.applied) == 1
    assert event.applied[0].instances == picked
    moved = {delta.card: delta for delta in event.deltas}
    assert set(moved) == set(picked)
    for delta in moved.values():
        assert delta.source_zone is Zone.HAND
        assert delta.destination_zone is Zone.GRAVE
        assert delta.source_player == MINE
        assert delta.destination_player == MINE


@pytest.mark.real_card
def test_h04_the_chain_link_keeps_both_chosen_cards(repository):
    """**§4-B-3 — 체인 링크가 고른 두 장을 보존한다.**"""
    duel, fine, _ = fine_board(repository, fodder=5)
    definition = entry_for(FINE_REF).definition
    combos = target_combinations(duel.state, MINE, definition, fine)
    picked = tuple(t.instance_id for t in combos[0])
    action = PlayerAction.activate_effect(
        actor=MINE, source=fine, effect_ref=FINE_REF, targets=combos[0]
    )
    selections = selections_for(definition, action)
    permit = ValidationResult.valid("감사용")
    activated = duel._activator.activate(
        duel.state, duel.chain, action, selections=selections, authorization=permit
    )
    link = activated.chain.links[-1]
    assert len(link.selections) == 1
    assert link.selections[0].ref == PRIMARY_TARGET
    assert link.selections[0].selection.chosen == picked


# ======================================================================
# I. 선택 후 변화 · 해결 시 유효성 (§8-6 · §8-7 · §9 · §12-F · §12-G)
# ======================================================================


@pytest.mark.real_card
def test_i01_a_target_that_left_the_zone_is_no_longer_legal(repository):
    """
    🔴 **§12-F — 고른 뒤 영역이 바뀌면 적법성도 바뀐다.**

    같은 ``InstanceId`` 가 같은 판정기에서 ``LEGAL`` 에서
    ``CANDIDATE_NOT_ELIGIBLE`` 로 바뀐다. 즉 선택은 발동 시점의 기록이고,
    적법성은 **볼 때마다 다시** 본다.
    """
    duel, fine, fodder = fine_board(repository, fodder=5)
    definition = entry_for(FINE_REF).definition
    chosen = fodder[:2]
    assert verdict_for(duel, definition, fine, chosen).legality is TargetLegality.LEGAL

    duel.state.move(chosen[0], Zone.GRAVE, to_player=MINE)
    later = verdict_for(duel, definition, fine, chosen)
    assert later.legality is TargetLegality.ILLEGAL
    assert later.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    #: 그리고 그 장은 조합에서도 빠진다.
    combos = target_combinations(duel.state, MINE, definition, fine)
    assert len(combos) == math.comb(4, 2)
    assert all(chosen[0] not in {t.instance_id for t in c} for c in combos)


@pytest.mark.real_card
def test_i02_partial_resolution_is_neither_allowed_nor_forbidden_here(repository):
    """
    🔴 **§9 · §12-G — 부분 해결을 이 Phase 가 정하지 않았다.**

    "일부 대상만 유효할 때 유효한 것만 처리하는가" 는 카드와 공식 재정이
    정하는 일이고, 등재된 다중 선택은 한 장뿐이므로 그 근거가 없다. 그래서
    **무조건 허용하지도 무조건 금지하지도 않는다** — 기존 실행기의 행동을
    그대로 두고, 그 행동이 무엇인지만 **센다.**

    실측: 고른 두 장 중 한 장을 미리 묘지로 옮기면 해결이 **되지 않는다**
    (``resolved`` 가 거짓). 즉 지금 엔진은 "전원이 필요하다" 쪽으로
    행동하고, 그 사실을 못 박아 둔다 — 누군가 부분 해결을 넣으면 이 시험이
    깨지고 그때 §9 를 다시 읽게 된다.
    """
    duel, fine, fodder = fine_board(repository, fodder=5)
    definition = entry_for(FINE_REF).definition
    chosen = targets_from(fodder[:2])
    duel.state.move(fodder[0], Zone.GRAVE, to_player=MINE)

    grave_before = len(duel.state.player(MINE).zones[Zone.GRAVE])
    _, allowed, last = force_resolve(duel, fine, definition, chosen)
    resolved = last is not None and last.resolved
    assert not (allowed.validity is ActionValidity.VALID and resolved), (
        "부분 해결이 생겼다 — §9 의 근거를 먼저 확인해야 한다",
        allowed.reason,
        last,
    )
    #: 남은 한 장이 **조용히** 버려지지 않았다.
    assert duel.state.find_instance(fodder[1]).zone is Zone.HAND
    assert len(duel.state.player(MINE).zones[Zone.GRAVE]) == grave_before


@pytest.mark.real_card
def test_i03_a_vanished_target_is_unknown_not_illegal(repository):
    """
    **§8-7 — 사라진 카드와 가려진 카드를 구분하지 못한다.**

    관측에 없는 카드는 ``HIDDEN_CARD`` 로 ``UNKNOWN`` 이다 — 없다고
    단정하지 않는다. ``UNKNOWN`` 을 허가로 바꾸지 않는 것이 핵심이다.
    """
    duel, fine, fodder = fine_board(repository, fodder=5)
    definition = entry_for(FINE_REF).definition
    deck_card = duel.state.player(MINE).deck.cards()[0].instance_id
    assert duel.view(MINE).find(deck_card) is None
    found = verdict_for(duel, definition, fine, (fodder[0], deck_card))
    assert found.legality is TargetLegality.UNKNOWN
    assert found.code is ValidationCode.HIDDEN_CARD


# ======================================================================
# J. 비공개 정보 (§3-12 · §8 · §12-M)
# ======================================================================


@pytest.mark.real_card
def test_j01_the_opponent_hand_never_becomes_a_candidate(repository):
    """
    🔴 **§12-M — 상대 패는 후보가 되지 않는다.**

    벌금은 ``owner=CONTROLLER`` 이므로 상대 패를 보지 않는다. 조합에
    상대의 카드가 하나도 없고, 손으로 적어 넣으면 ``UNKNOWN`` 이다.
    """
    duel, fine, _ = fine_board(repository, fodder=5)
    duel.state.draw(THEIRS, 3)
    definition = entry_for(FINE_REF).definition
    theirs = {c.instance_id for c in duel.state.player(THEIRS).zones[Zone.HAND]}
    assert len(theirs) == 3

    combos = target_combinations(duel.state, MINE, definition, fine)
    assert len(combos) == 10
    for combo in combos:
        assert not ({t.instance_id for t in combo} & theirs)

    stolen = sorted(theirs, key=lambda i: i.value)[:2]
    found = verdict_for(duel, definition, fine, stolen)
    assert found.legality is not TargetLegality.LEGAL
    assert found.code in {
        ValidationCode.HIDDEN_CARD,
        ValidationCode.CANDIDATE_NOT_ELIGIBLE,
        ValidationCode.INFORMATION_UNAVAILABLE,
    }, found.code


@pytest.mark.real_card
def test_j02_the_candidate_count_does_not_leak_the_opponent_hand(repository):
    """
    **상대 패가 몇 장이든 내 조합 수가 변하지 않는다.**

    조합 수를 읽는 것만으로 상대 패를 세는 길이 없어야 한다.
    """
    definition = entry_for(FINE_REF).definition
    counts = []
    for opponent_hand in (0, 3, 6):
        duel, (fine,), _, _ = staged(
            repository, hand=(FINE,), hand_fodder=5, opponent_hand=opponent_hand
        )
        set_down(duel, fine)
        counts.append(
            len(target_combinations(duel.state, MINE, definition, fine))
        )
    assert counts == [10, 10, 10], counts


@pytest.mark.real_card
def test_j03_a_face_down_card_of_mine_is_not_silently_counted(repository):
    """
    **§8-3 — 뒷면 카드는 패의 후보와 섞이지 않는다.**

    세워 둔 벌금 자신은 마법 & 함정 존에 있고, 벌금의 후보 자리는 패다.
    그래서 조합에 자기 자신이 들어가지 않는다 (``exclude_source`` 를 쓰지
    않고도 자리로 갈린다).
    """
    duel, fine, fodder = fine_board(repository, fodder=5)
    assert duel.state.find_instance(fine).zone is Zone.SZONE
    combos = target_combinations(
        duel.state, MINE, entry_for(FINE_REF).definition, fine
    )
    for combo in combos:
        assert fine not in {t.instance_id for t in combo}
        for target in combo:
            assert duel.state.find_instance(target.instance_id).zone is Zone.HAND


# ======================================================================
# K. 기존 기능 회귀 (§12-H ~ §12-L · §18-13 · §18-14)
# ======================================================================


@pytest.mark.real_card
def test_k01_a_single_target_effect_is_unchanged(repository):
    """🔴 **§12-J — 단일 대상은 그대로 1개 조합이다.**"""
    duel, (forceout,), _, _ = staged(
        repository, hand=(FORCEOUT,), theirs=(LUSTER_DRAGON, BATTLE_OX)
    )
    set_down(duel, forceout)
    definition = DEFINITIONS.definition_for(EffectRef(FORCEOUT, 0))
    combos = target_combinations(duel.state, MINE, definition, forceout)
    assert len(combos) == 2, "상대 몬스터 2장 → 1장씩 두 후보"
    assert all(len(c) == 1 for c in combos)


@pytest.mark.real_card
def test_k02_an_effect_with_no_target_still_gets_one_empty_combination(repository):
    """**§12-H — 대상 지정 절차를 없는 곳에 추가하지 않았다.**"""
    duel, (pot,), _, _ = staged(repository, hand=(POT_OF_GREED,))
    definition = DEFINITIONS.definition_for(EffectRef(POT_OF_GREED, 0))
    assert chosen_bindings(definition) == ()
    assert target_combinations(duel.state, MINE, definition, pot) == [()]
    assert required_target_count(definition) == 0
    assert unsupported_enumeration(definition) is None


@pytest.mark.real_card
def test_k03_a_random_binding_is_still_excluded(repository):
    """**§7-C — 무작위가 정하는 대상은 짝에서 빠진다.**"""
    duel, (denial,), _, placed = staged(
        repository, hand=(RUTHLESS_DENIAL,), mine=(LUSTER_DRAGON, BATTLE_OX)
    )
    definition = DEFINITIONS.definition_for(EffectRef(RUTHLESS_DENIAL, 0))
    combos = target_combinations(duel.state, MINE, definition, denial)
    assert len(combos) == 2, "고르는 자리는 @primary 하나뿐"
    assert all(len(c) == 1 for c in combos)
    assert {t.instance_id for c in combos for t in c} == set(placed[MINE])


@pytest.mark.real_card
def test_k04_the_deck_target_is_still_outside_the_ordinary_view(repository):
    """
    **어리석은 매장의 덱은 여전히 평소 관측 밖이다** (STRUCTURAL-125).

    🔴 **Phase 6-Z 가 모양을 바꿨다.** 그 고르기가 해결 시점으로 옮겨졌으므로
    발동 시점에 짝지울 자리가 **없고** (``chosen_bindings`` 가 빈 짝이다),
    조합은 빈 조합 하나다 — "대상 없이 발동한다". 지키려던 것은 그대로다:
    ``PlayerAction`` 에 덱의 카드가 실리지 않는다.
    """
    from engine.target_bridge import decided_at_resolution

    duel, (burial,), _, _ = staged(repository, hand=(FOOLISH_BURIAL,))
    definition = DEFINITIONS.definition_for(EffectRef(FOOLISH_BURIAL, 0))
    #: 규칙은 이 효과에게 덱을 열어 준다 — 그 선언은 그대로다.
    binding = definition.targets[0]
    assert binding.spec.looked_at_zones() == frozenset({Zone.DECK})
    #: 🔴 그리고 그 선언이 **미루는 이유**다.
    assert decided_at_resolution(binding.spec) is True
    assert chosen_bindings(definition) == ()
    assert target_combinations(duel.state, MINE, definition, burial) == [()]
    #: 평소 관측에는 덱이 보이지 않는다 — 경계의 근거다.
    deck = duel.state.player(MINE).zones[Zone.DECK].cards()
    assert deck
    assert all(duel.view(MINE).find(c.instance_id) is None for c in deck)


@pytest.mark.real_card
def test_k05_the_self_reference_target_is_unchanged(repository):
    """
    🔴 **§12-I — Phase 6-L 의 ``SELF_TARGET`` 처리가 유지된다.**

    어니스트 ①은 자기 자신을 패로 되돌린다. 고르는 자리가 **아니므로**
    조합은 빈 조합 하나이고, 열거를 넓힌 것이 그 사실을 바꾸지 않았다.
    """
    definition = DEFINITIONS.definition_for(EffectRef(HONEST, 0))
    assert definition.references_self
    assert chosen_bindings(definition) == ()
    assert unsupported_enumeration(definition) is None
    duel, (honest,), _, _ = staged(repository, hand=(HONEST,))
    assert target_combinations(duel.state, MINE, definition, honest) == [()]
    assert selections_for(
        definition,
        PlayerAction.activate_effect(
            actor=MINE, source=honest, effect_ref=EffectRef(HONEST, 0)
        ),
    ) == ()


@pytest.mark.real_card
def test_k06_the_phase_6o_movement_still_executes(repository):
    """
    🔴 **§12-L · §18-13 — Phase 6-O 의 ``MZONE → HAND`` 가 유지된다.**

    강제 탈출 장치가 통상 몬스터를 패로 되돌리고 상대 패가 1장 늘어난다.
    """
    duel, (forceout,), _, placed = staged(
        repository, hand=(FORCEOUT,), theirs=(LUSTER_DRAGON,)
    )
    set_down(duel, forceout)
    victim = placed[THEIRS][0]
    their_hand = len(duel.state.player(THEIRS).zones[Zone.HAND])
    definition = DEFINITIONS.definition_for(EffectRef(FORCEOUT, 0))
    combos = target_combinations(duel.state, MINE, definition, forceout)
    assert len(combos) == 1
    _, allowed, last = force_resolve(duel, forceout, definition, combos[0])
    assert allowed.validity is ActionValidity.VALID, allowed.reason
    assert last is not None and last.resolved, last
    assert duel.state.find_instance(victim).zone is Zone.HAND
    assert len(duel.state.player(THEIRS).zones[Zone.HAND]) == their_hand + 1


@pytest.mark.real_card
def test_k07_an_effect_monster_target_still_stops(repository):
    """
    **그리고 룰북이 덮지 않는 대상은 여전히 멈춘다** (6-O 의 경계).

    열거를 넓힌 것이 규칙 지식을 넓히지 않았다는 확인이다 — ``UNKNOWN`` 이
    허가로 바뀌지 않았다.
    """
    duel, (forceout,), _, placed = staged(
        repository, hand=(FORCEOUT,), theirs=(UNKNOWN_EFFECT_MONSTER,)
    )
    set_down(duel, forceout)
    stubborn = placed[THEIRS][0]
    definition = DEFINITIONS.definition_for(EffectRef(FORCEOUT, 0))
    combos = target_combinations(duel.state, MINE, definition, forceout)
    assert len(combos) == 1, "대상은 찾는다"
    _, _, last = force_resolve(duel, forceout, definition, combos[0])
    assert last is not None and not last.resolved, last
    assert "IsAbleToHand" in last.reason, last.reason
    assert duel.state.find_instance(stubborn).zone is Zone.MZONE


@pytest.mark.real_card
def test_k08_a_single_target_spell_still_resolves_end_to_end(repository):
    """
    **§18-14 — 단일 대상 효과의 발동과 해결이 변하지 않았다.**

    자기 미라화(15103313) — 자신 몬스터 존의 1장을 묘지로 보낸다. 관문이
    없는 이유가 원본에 있다 (``s.target`` 의 필터가 ``nil``). 몬스터 2장이면
    조합 2개, 해결 성공, 고른 쪽만 묘지로 간다.
    """
    duel, (mummy,), _, placed = staged(
        repository, hand=(SELF_MUMMIFICATION,), mine=(LUSTER_DRAGON, BATTLE_OX)
    )
    definition = DEFINITIONS.definition_for(EffectRef(SELF_MUMMIFICATION, 0))
    combos = target_combinations(duel.state, MINE, definition, mummy)
    assert len(combos) == 2
    assert all(len(c) == 1 for c in combos)
    victim = combos[0][0].instance_id
    survivor = next(i for i in placed[MINE] if i != victim)
    _, allowed, last = force_resolve(duel, mummy, definition, combos[0])
    assert allowed.validity is ActionValidity.VALID, allowed.reason
    assert last is not None and last.resolved, last
    assert duel.state.find_instance(victim).zone is Zone.GRAVE
    assert duel.state.find_instance(survivor).zone is Zone.MZONE


@pytest.mark.real_card
def test_k09_the_destruction_gap_is_still_a_destruction_gap(repository):
    """
    **싸이크론은 여전히 파괴 판정 공백에서 멈춘다** (6-M · 6-O 의 경계).

    조합은 1개로 그대로이고, 멈추는 이유가 **대상이 아니라 파괴**임을
    세어 둔다 — 열거를 넓힌 것이 파괴 지식을 넓히지 않았다.
    """
    duel, (storm,), _, _ = staged(repository, hand=(MYSTICAL_SPACE_TYPHOON,))
    victim = duel.state.create_instance(POT_OF_GREED, owner=THEIRS, zone=Zone.HAND)
    duel.state.move(victim, Zone.SZONE, to_player=THEIRS, position=Position.FACEUP)
    definition = DEFINITIONS.definition_for(EffectRef(MYSTICAL_SPACE_TYPHOON, 0))
    combos = target_combinations(duel.state, MINE, definition, storm)
    assert len(combos) == 1
    _, allowed, last = force_resolve(duel, storm, definition, combos[0])
    assert allowed.validity is ActionValidity.VALID, allowed.reason
    assert last is not None and not last.resolved, last
    assert "파괴" in last.reason, last.reason
    assert duel.state.find_instance(victim.instance_id).zone is Zone.SZONE
