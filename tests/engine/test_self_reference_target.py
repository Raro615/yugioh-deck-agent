"""
Phase 6-L — **효과를 발동한 카드 자신**을 가리키는 공통 참조.

    EffectDefinition(operations=(CardOperation.return_to_hand(SELF_TARGET),))
        ↓  EffectExecutor._resolve_selection
    Selection((context.source,))          ← 후보를 세지 않는다
        ↓  자리 규칙 · 관문 · "판에 있는가"   ← 하나도 건너뛰지 않는다
    GameState 변경 + EventJournal

이 파일이 지키는 것
-------------------
**자기 참조는 "대상으로 지정" 이 아니다.** 어니스트 ① 의 공식 텍스트에
「대상으로 하고」 가 없으므로 ``targets`` 는 비어 있고 ``requires_target``
은 거짓이며 ``PlayerAction.targets`` 도 비어 있다 (§D).

**같은 카드 ID 두 장을 혼동하지 않는다.** 가리키는 것은 ``InstanceId``
하나이고, 후보 선택으로 흉내 내면 발동하지 않은 쪽도 움직인다 (§B).

**정보가 없으면 지어내지 않는다.** ``source`` 가 ``None`` 이면 같은 카드의
다른 인스턴스로 대신하지 않고 멈춘다 (§H).

**``CandidateResolver`` 를 바꾸지 않았다.** 자기 참조는 후보가 아니다 (§C ·
§L).

**자기 참조라는 이유로 공짜가 되는 검사가 하나도 없다.** 관문 · 자리 규칙 ·
"판에 있는가" 는 그대로 지난다 (§F · §G).
"""

import ast
import dataclasses
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.condition import ConditionContext, ConditionResult, PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.cost.resolver import CandidateResolver
from engine.duel import Duel
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionError,
    EffectProvenance,
)
from engine.effect.executor import (
    EffectExecutor,
    EffectImplementationRegistry,
)
from engine.effect.library import (
    EFFECT_LIBRARY,
    GIRSU,
    HONEST,
    OPERATION_RULINGS,
    POT_OF_GREED,
    WORLD_WAND,
    definition_registry,
)
from engine.effect.operation import CardOperation, OperationKind
from engine.effect.resolution import ResolutionContext, ResolutionStatus
from engine.effect.ruling import RuleBasis, RuleQuestion
from engine.effect.semantics import (
    FIELD_ZONES,
    MISSING_SAME_ZONE_MOVEMENT,
    ORIGIN_RULES,
    origin_rule,
)
from engine.effect.target import (
    PRIMARY_TARGET,
    SELF_TARGET,
    TargetBinding,
    TargetRef,
    TargetRequirement,
    TargetSpec,
)
from engine.ids import EffectRef, InstanceId
from engine.priority import PriorityState
from engine.spell_activation import duel_components
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db, settle_chain

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

HONEST_REF = EffectRef(HONEST, 0)
#: 엘리멘틀 히어로 페더맨 — 통상 몬스터이고 ``OPERATION_RULINGS`` 에 있다.
#: 덱을 이것으로 채우는 이유: 필드에 **미등록 앞면 카드**를 두지 않기 위해서다
#: (``BoardRuling._interference`` 가 모르는 카드를 만나면 멈춘다).
FEATHERMAN = 21844576
#: 룡기병 — ``OPERATION_RULINGS`` 에 **없다.** 간섭 사례에 쓴다.
#: 🔴 **Phase 6-O 가 표본 카드를 바꿨다.** 전에는 사파이어 드래곤
#: (11091375) 이었는데 그 카드는 **통상 몬스터**이고, 6-O 가 룰북 한
#: 줄(``NORMAL_MONSTER_RULE``)을 그 줄이 덮는 684장 전체에 연결하면서
#: 더 이상 "모르는 카드" 가 아니게 되었다. 이 시험이 재는 사실(판에
#: 모르는 앞면 카드가 있으면 멈춘다)은 **그대로**이고, 표본만 룰북이
#: 답하지 않는 카드로 바꿨다 — 단언은 하나도 약해지지 않았다.
#: 사이버 드래곤 — **효과 몬스터**이고 판정 지식에 없다.
UNKNOWN_EFFECT_MONSTER = 70095154


# ======================================================================
# 판 만들기
# ======================================================================


def board(repository, *cards, phase: Phase = Phase.MAIN1, zone: Zone = Zone.MZONE):
    """앞면 몬스터 몇 장이 놓인 판. 배치는 전부 실제 엔진이 한다."""
    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    placed = [
        state.create_instance(card_id, owner=MINE, zone=zone, position=Position.FACEUP)
        for card_id in cards
    ]
    state.turn.set_phase(phase)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=phase),
        **duel_components(),
    )
    return duel, placed


def self_definition(operation, *, card_id: int = HONEST):
    """그 조작 하나만 하는, 자기 참조 정의. **production 을 건드리지 않는다.**"""
    return EffectDefinition(
        effect_ref=EffectRef(card_id, 0),
        source_card_id=card_id,
        operations=(operation,),
        provenance=EffectProvenance.official_lua("시험용"),
    )


def executed(
    repository, definition, *, source, cards=(HONEST,), rulings=OPERATION_RULINGS
):
    """그 정의를 실제 실행기로 돌린다. ``(결과, state, 놓인 카드들)``."""
    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    placed = [
        state.create_instance(card_id, owner=MINE, zone=Zone.MZONE,
                              position=Position.FACEUP)
        for card_id in cards
    ]
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        rulings=rulings,
    )
    context = ResolutionContext(
        effect_ref=definition.effect_ref,
        controller=MINE,
        source=placed[source].instance_id if source is not None else None,
    )
    return executor.execute(state, definition, context), state, placed


# ======================================================================
# A. 자기 자신 참조 — 발동한 그 인스턴스를 가리킨다
# ======================================================================


@pytest.mark.real_card
def test_a01_the_operation_moves_exactly_the_activating_card(repository):
    """
    **§13-A** — 자기 참조가 발동한 카드 **하나**를 움직인다.

    ``ResolutionContext.source`` 는 ``InstanceId`` 이고 (카드 정의가 아니다),
    실행기가 그것을 선택 하나로 만든다.
    """
    definition = self_definition(
        CardOperation.return_to_hand(SELF_TARGET, gated=True)
    )
    result, state, placed = executed(repository, definition, source=0)

    assert result.status is ResolutionStatus.RESOLVED, result.reason
    assert len(result.deltas) == 1
    moved = state.find_instance(placed[0].instance_id)
    assert moved.zone is Zone.HAND
    #: 델타가 **그 인스턴스**를 적는다.
    delta = result.deltas[0]
    assert delta.instance == placed[0].instance_id
    assert delta.destination_zone is Zone.HAND


def test_a02_the_reference_is_a_name_not_an_instance():
    """
    ``SELF_TARGET`` 은 **이름**이다. 정의는 어느 카드가 발동할지 모른다.

    같은 정의를 여러 판에서 쓰므로 정의에 ``InstanceId`` 를 박을 수 없다
    (``TargetRef`` 의 설명).
    """
    assert isinstance(SELF_TARGET, TargetRef)
    assert SELF_TARGET.name == "self"
    assert SELF_TARGET != PRIMARY_TARGET
    assert "instance" not in {f.name for f in dataclasses.fields(TargetRef)}


def test_a03_the_definition_says_it_references_itself():
    """
    ``references_self`` 가 ``requires_target`` 과 **다른 질문**이다.

    둘을 한 값으로 합치면 "자기 자신을 패로 되돌린다" 가 대상 지정 효과로
    읽힌다.
    """
    me = self_definition(CardOperation.return_to_hand(SELF_TARGET, gated=True))
    assert me.references_self is True
    assert me.requires_target is False
    assert me.targets == ()

    other = EffectDefinition(
        effect_ref=EffectRef(1, 0),
        source_card_id=1,
        targets=TargetBinding.single(
            TargetSpec.targeting(
                ChoiceSpec(
                    source=CandidateSource(zones=frozenset({Zone.MZONE})),
                    minimum=1,
                    maximum=1,
                )
            )
        ),
        operations=(CardOperation.return_to_hand(PRIMARY_TARGET),),
        provenance=EffectProvenance.official_lua("시험용"),
    )
    assert other.references_self is False
    assert other.requires_target is True


# ======================================================================
# B. 같은 카드 ID 복수 인스턴스
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize("which", [0, 1])
def test_b01_only_the_activating_instance_moves(repository, which):
    """
    **§13-B** — 같은 카드 ID 두 장 중 **발동한 쪽만** 움직인다.

    이것이 자기 참조를 후보 선택으로 흉내 내지 않은 이유다.
    """
    definition = self_definition(
        CardOperation.return_to_hand(SELF_TARGET, gated=True)
    )
    result, state, placed = executed(
        repository, definition, source=which, cards=(HONEST, HONEST)
    )
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    zones = [state.find_instance(p.instance_id).zone for p in placed]
    assert zones[which] is Zone.HAND
    assert zones[1 - which] is Zone.MZONE
    assert result.deltas[0].instance == placed[which].instance_id


@pytest.mark.real_card
def test_b02_candidate_selection_would_have_offered_the_wrong_card(repository):
    """
    🔴 **대안이 왜 틀렸는지 실측으로 남긴다.**

    "컨트롤러의 몬스터 존에서 1장" 이라는 후보 선택으로 "이 카드" 를 적으면,
    같은 카드 두 장이 깔린 판에서 **발동하지 않은 쪽**도 후보가 된다.
    자기 참조는 후보가 아니라 **참조**다.
    """
    from engine.game_state_view import GameStateView

    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    first = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP
    )
    second = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP
    )

    spec = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.MZONE}), owner=PlayerRef.CONTROLLER
        ),
        minimum=1,
        maximum=1,
    )
    context = ConditionContext(
        player=MINE, source=first.instance_id, effect_ref=HONEST_REF
    )
    found = CandidateResolver(
        GameStateView.from_state(state, viewer=MINE)
    ).resolve(spec, context)

    #: 발동한 것은 하나인데 후보는 둘이다.
    assert set(found.eligible) == {first.instance_id, second.instance_id}
    assert len(found.eligible) == 2


@pytest.mark.real_card
def test_b03_exclude_source_is_the_opposite_axis(repository):
    """
    ``exclude_source`` 는 자기 참조의 **정확한 여집합**이다.

    "이 카드 이외의" 를 적는 자리이고, 둘을 섞으면 후보가 빈다. 그래서 이
    Phase 는 ``CandidateResolver`` 를 **건드리지 않았다.**
    """
    from engine.game_state_view import GameStateView

    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    first = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP
    )
    second = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP
    )
    view = GameStateView.from_state(state, viewer=MINE)
    context = ConditionContext(
        player=MINE, source=first.instance_id, effect_ref=HONEST_REF
    )

    def resolve(exclude: bool):
        spec = ChoiceSpec(
            source=CandidateSource(
                zones=frozenset({Zone.MZONE}),
                owner=PlayerRef.CONTROLLER,
                exclude_source=exclude,
            ),
            minimum=1,
            maximum=1,
        )
        return set(CandidateResolver(view).resolve(spec, context).eligible)

    everything, without_self = resolve(False), resolve(True)
    #: 🔴 차가 정확히 **발동한 카드 하나**다.
    assert everything - without_self == {first.instance_id}
    assert second.instance_id in without_self


# ======================================================================
# C. 자기 자신 제외 — CandidateResolver 를 바꾸지 않았다
# ======================================================================


def test_c01_the_candidate_resolver_was_not_touched():
    """
    **§13-C · §13-L** — ``CandidateResolver`` 가 자기 참조를 **모른다.**

    후보를 세는 일과 발동한 카드를 가리키는 일은 다른 질문이고, 섞으면
    "이 카드" 와 "이 카드 이외의" 가 같은 코드에서 갈린다.
    """
    source = (PROJECT_ROOT / "engine" / "cost" / "resolver.py").read_text(
        encoding="utf-8"
    )
    assert "SELF_TARGET" not in source
    assert "self_reference" not in source
    #: 후보를 거르는 규칙 평가기도 그대로 하나다.
    tree = ast.parse(source)
    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    assert classes == ["CandidateResolver"], classes


def test_c02_the_target_requirement_axis_was_not_widened():
    """
    ``TargetRequirement`` 에 다섯 번째 값을 **더하지 않았다.**

    자기 참조는 "어떻게 고르는가" 의 한 종류가 아니다 — 고르지 않는다.
    """
    assert [m.value for m in TargetRequirement] == [
        "none", "targeting", "choosing", "all", "random"
    ]


def test_c03_the_reserved_name_cannot_be_declared_as_a_target():
    """
    🔴 ``SELF_TARGET`` 에 :class:`TargetBinding` 을 **걸 수 없다.**

    선언하면 그 효과가 대상 지정 효과가 되고, 무효화 · 회피의 대상이 되며
    발동 시점에 확정되어야 한다. 셋 다 공식 텍스트가 말하지 않은 것이다.
    """
    choice = ChoiceSpec(
        source=CandidateSource(zones=frozenset({Zone.MZONE})), minimum=1, maximum=1
    )
    for spec in (
        TargetSpec.none(),
        TargetSpec.targeting(choice),
        TargetSpec.choosing(choice),
    ):
        with pytest.raises(ValueError, match="고르는 대상이 아닙니다"):
            TargetBinding(SELF_TARGET, spec)


def test_c04_an_undeclared_name_is_still_refused():
    """
    자기 참조를 열었지만 **아무 이름이나 열린 것이 아니다.**

    ``@self`` 가 아닌 선언되지 않은 이름은 정의를 만들 때 그대로 거부된다.
    """
    with pytest.raises(EffectDefinitionError, match="선언되지 않은 대상"):
        EffectDefinition(
            effect_ref=EffectRef(1, 0),
            source_card_id=1,
            operations=(CardOperation.return_to_hand(TargetRef("nope")),),
            provenance=EffectProvenance.official_lua("시험용"),
        )


def test_c05_the_spec_lookup_splits_three_ways_not_two():
    """
    🔴 ``EffectExecutor._target_spec_of`` 는 **세 갈래**다.

    mutation N4 가 여기서 살아남았다 — ``_target_spec_of`` 가 모든 이름에
    ``None`` 을 돌려주게 바꿔도 이 파일의 41개가 전부 통과했다. 기존
    ``tests/engine/test_targeted_effect.py`` 가 25개로 그 결함을 잡기는
    하지만, **6-L 이 더한 함수를 6-L 의 테스트가 재지 않고 있었다.** 그래서
    그 세 갈래를 여기서 직접 못박는다.

    1. 자기 참조 → ``None`` ("고를 규칙이 없다")
    2. 선언된 이름 → **그 규칙 자체** (``None`` 이 아니다)
    3. 선언되지 않은 이름 → :class:`KeyError` (조용히 넘어가지 않는다)

    ``None`` 이 1번과 3번을 **함께** 뜻하게 되면, 선언을 빠뜨린 정의가
    "규칙 없음" 으로 읽혀서 ``_check_target`` 을 건너뛴다.
    """
    choice = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.MZONE}), owner=PlayerRef.CONTROLLER
        ),
        minimum=1,
        maximum=1,
    )
    declared = TargetSpec.targeting(choice)
    definition = EffectDefinition(
        effect_ref=EffectRef(HONEST, 0),
        source_card_id=HONEST,
        targets=TargetBinding.single(declared),
        operations=(CardOperation.return_to_hand(PRIMARY_TARGET, gated=True),),
        provenance=EffectProvenance.official_lua("시험용"),
    )

    #: 1. 자기 참조만 ``None`` 이다.
    assert EffectExecutor._target_spec_of(definition, SELF_TARGET) is None

    #: 2. 선언된 이름은 **그 규칙 자체**가 돌아온다 — ``None`` 으로
    #:    뭉개지지 않는다. 뭉개지면 고른 것의 자리 · 주인 · 조건을 다시
    #:    보는 검사가 사라진다.
    found = EffectExecutor._target_spec_of(definition, PRIMARY_TARGET)
    assert found is declared
    assert found.requirement is TargetRequirement.TARGETING

    #: 3. 선언되지 않은 이름은 여전히 :class:`KeyError` 다.
    with pytest.raises(KeyError):
        EffectExecutor._target_spec_of(definition, TargetRef("nope"))


# ======================================================================
# D. 일반적인 대상 선택이 그대로다
# ======================================================================


@pytest.mark.real_card
def test_d01_a_targeting_effect_still_needs_its_target(repository):
    """
    **§13-D** — 대상을 선언한 효과는 여전히 밖에서 고른 것을 받아야 한다.

    자기 참조가 열렸다고 "고르지 않아도 된다" 가 되지 않는다.
    """
    definition = EffectDefinition(
        effect_ref=EffectRef(HONEST, 0),
        source_card_id=HONEST,
        targets=TargetBinding.single(
            TargetSpec.targeting(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=frozenset({Zone.MZONE}), owner=PlayerRef.CONTROLLER
                    ),
                    minimum=1,
                    maximum=1,
                )
            )
        ),
        operations=(CardOperation.return_to_hand(PRIMARY_TARGET, gated=True),),
        provenance=EffectProvenance.official_lua("시험용"),
    )
    result, state, placed = executed(repository, definition, source=0)
    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    assert state.find_instance(placed[0].instance_id).zone is Zone.MZONE


@pytest.mark.real_card
def test_d02_the_bridge_asks_for_no_target_on_a_self_reference(repository):
    """
    ``target_bridge`` 가 자기 참조에 ``PlayerAction.targets`` 를 요구하지
    않는다 — 선언된 대상이 없으므로 짝지을 것도 없다.
    """
    from engine.target_bridge import (
        chosen_bindings,
        required_target_count,
        selections_for,
        target_combinations,
    )

    definition = definition_registry().definition_for(HONEST_REF)
    assert definition is not None and definition.references_self
    assert chosen_bindings(definition) == ()
    assert required_target_count(definition) == 0

    duel, placed = board(repository, HONEST)
    action = PlayerAction.activate_effect(
        actor=MINE, source=placed[0].instance_id, effect_ref=HONEST_REF
    )
    assert selections_for(definition, action) == ()
    assert target_combinations(
        duel.state, MINE, definition, placed[0].instance_id
    ) == [()]


# ======================================================================
# E. 영역 이동 — 인스턴스 정체성과 남은 공백
# ======================================================================


def test_e01_the_instance_id_survives_a_zone_move():
    """
    ``InstanceId`` 는 자리를 옮겨도 **그대로**다 (``engine/ids.py``).

    그래서 자기 참조가 발동 시점의 카드를 해결 시점까지 들고 갈 수 있다 —
    카드 ID 가 같다는 이유로 다른 인스턴스를 쓰는 길이 아니다.
    """
    source = (PROJECT_ROOT / "engine" / "ids.py").read_text(encoding="utf-8")
    assert "카드가 존을 옮겨도 번호는 그대로" in source


@pytest.mark.real_card
def test_e02_a_vanished_source_stops_the_effect(repository):
    """
    **§13-E** — 해결 시점에 그 인스턴스가 판에 없으면 **멈춘다.**

    자기 참조라는 이유로 "성공" 이 되지 않는다. 이 검사는 실행기가 모든
    대상에 쓰는 것과 **같은 검사**다.
    """
    definition = self_definition(
        CardOperation.return_to_hand(SELF_TARGET, gated=True)
    )
    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        rulings=OPERATION_RULINGS,
    )
    #: 이 듀얼에 **없는** 번호를 가리킨다.
    context = ResolutionContext(
        effect_ref=definition.effect_ref, controller=MINE, source=InstanceId(9999)
    )
    result = executor.execute(state, definition, context)
    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_FOUND
    assert result.deltas == ()


@pytest.mark.real_card
@pytest.mark.parametrize("zone", [Zone.HAND, Zone.GRAVE, Zone.SZONE])
def test_e03_return_to_hand_has_no_origin_rule_today(repository, zone):
    """
    🔴 **남은 공백을 숨기지 않고 센다** (§16).

    어니스트 ① 의 공식 텍스트는 「**필드의 앞면 표시의** 이 카드를 패로
    되돌린다」 인데, 6-L 은 그 제약을 **하나도 옮기지 못했다.**

    - ``Card.IsRelateToEffect`` — 발동 뒤 그 카드가 떠났는지 (STRUCTURAL-50)
    - ``Card.IsFaceup`` — 해결 시점의 표시 형식
    - ``ORIGIN_RULES`` 에 ``RETURN_TO_HAND`` 항목이 **없다** (출발 자리 무제약)

    🔴 **Phase 6-M 이 셋 중 하나를 옮겼다.** 「필드의」 가
    :attr:`~engine.effect.operation.CardOperation.origin_zones` 로 들어갔다
    — 그런데 그것은 **이 효과 하나**의 제약이고, ``ORIGIN_RULES`` 는
    여전히 비어 있다. 그것이 틀린 것이 아니다: 그 표는 일의 종류마다
    **전역**이고, 묘지 · 덱 · 제외 구역에서 패로 되돌리는 실제 카드가
    많으므로 전역으로 막으면 그 카드들이 틀린다.

    그래서 이 시험은 **두 축을 갈라서** 센다.

    1. 전역 표는 그대로 비어 있고, **자리를 적지 않은** 조작은 어느
       자리에서든 지난다 (단, 아래 3번).
    2. 등재된 어니스트 ① 은 자리를 적었으므로 필드 밖에서 **거절된다.**
    3. 🔴 ``HAND`` 는 둘 다 거절한다 — 이미 그 자리에 있어서 **옮길 것이
       없기** 때문이고, 그것은 자리 규칙이 아니라 "일어나지 않은 이동을
       성공으로 적지 않는다" 는 불변 조건이다 (Phase 6-M).
    """
    #: 1. 전역 표는 **비어 있다.** 6-M 도 여기에 줄을 더하지 않았다.
    assert OperationKind.RETURN_TO_HAND not in ORIGIN_RULES
    assert origin_rule(OperationKind.RETURN_TO_HAND) is None

    bare = self_definition(CardOperation.return_to_hand(SELF_TARGET, gated=True))
    assert bare.operations[0].origin_zones is None

    deck = [FEATHERMAN] * 20

    def run(definition):
        state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
        placed = state.create_instance(
            HONEST, owner=MINE, zone=zone, position=Position.FACEUP
        )
        executor = EffectExecutor(
            lookup=EffectImplementationRegistry((definition.effect_ref,)),
            rulings=OPERATION_RULINGS,
        )
        result = executor.execute(
            state,
            definition,
            ResolutionContext(
                effect_ref=definition.effect_ref,
                controller=MINE,
                source=placed.instance_id,
            ),
        )
        return result, state.find_instance(placed.instance_id).zone

    bare_result, bare_zone = run(bare)
    registered = definition_registry().definition_for(HONEST_REF)
    assert registered is not None
    #: 2. 등재된 쪽은 **자리를 적었다** (Phase 6-M).
    assert registered.operations[0].origin_zones == FIELD_ZONES
    real_result, real_zone = run(registered)

    if zone is Zone.HAND:
        #: 3. 🔴 둘 다 거절하고 판은 그대로인데, **이유가 다르다.**
        #:
        #: 자리를 적지 않은 쪽은 "옮길 것이 없다" 로 멈춘다 — 모르는 것
        #: (그 효과가 불발되는지)이므로 ``UNSUPPORTED_OPERATION`` 이다.
        assert bare_result.status is ResolutionStatus.UNSUPPORTED_OPERATION, (
            bare_result.reason
        )
        assert bare_result.code is ValidationCode.RULE_NOT_IMPLEMENTED
        assert MISSING_SAME_ZONE_MOVEMENT in bare_result.missing
        #: 등재된 쪽은 **그보다 먼저** 자리에서 걸린다 — 공식 텍스트가
        #: 「필드의」 라고 적었으므로 **아는 규칙**이고 확실한 거절이다.
        #: 순서가 이렇게 되는 것이 맞다: 더 강한 말을 먼저 한다.
        assert real_result.status is ResolutionStatus.INVALID_TARGET, (
            real_result.reason
        )
        assert real_result.code is ValidationCode.SOURCE_WRONG_ZONE
        assert real_result.missing is None
        for result, after in ((bare_result, bare_zone), (real_result, real_zone)):
            assert result.deltas == ()
            assert after is Zone.HAND
    elif zone in FIELD_ZONES:
        #: 필드 안이므로 둘 다 지난다.
        assert bare_result.status is ResolutionStatus.RESOLVED, bare_result.reason
        assert bare_zone is Zone.HAND
        assert real_result.status is ResolutionStatus.RESOLVED, real_result.reason
        assert real_zone is Zone.HAND
    else:
        #: 자리를 적지 않은 쪽은 **여전히 지난다** — 전역 공백이 그대로다.
        assert bare_result.status is ResolutionStatus.RESOLVED, bare_result.reason
        assert bare_zone is Zone.HAND
        #: 🔴 등재된 쪽은 **거절된다** (Phase 6-M 이 옮긴 「필드의」).
        assert real_result.status is ResolutionStatus.INVALID_TARGET, (
            real_result.reason
        )
        assert real_result.code is ValidationCode.SOURCE_WRONG_ZONE
        assert real_result.deltas == ()
        assert real_zone is zone


# ======================================================================
# F. 발동 비용 — 자기 참조로 열리지 않는다
# ======================================================================


def test_f01_a_cost_cannot_use_the_reference_name():
    """
    **§13-F** — 비용은 ``TargetRef`` 를 쓰지 않는다. 그래서 자기 참조가
    비용 축을 열지 **않는다.**

    어니스트 ②(``Cost.SelfToGrave``)가 여전히 미지원인 이유이고, 비용 ·
    대상 · 해결 셋이 구조로 갈려 있다는 증거다 (§8).
    """
    from engine.cost.model import Cost, CostGroup

    assert "target_ref" not in {f.name for f in dataclasses.fields(Cost)}
    assert {f.name for f in dataclasses.fields(CostGroup)} == {"costs"}
    cost_source = (PROJECT_ROOT / "engine" / "cost").rglob("*.py")
    for path in cost_source:
        assert "SELF_TARGET" not in path.read_text(encoding="utf-8"), path.name


@pytest.mark.real_card
def test_f02_the_registered_self_reference_effect_has_no_cost(repository):
    """
    등재된 자기 참조 효과(어니스트 ①)에 비용이 **없다.**

    비용이 있는 효과를 자기 참조로 열지 않았다는 뜻이고, 비용이 생기는 날
    그것은 ``CostPayer`` 가 따로 본다.
    """
    definition = definition_registry().definition_for(HONEST_REF)
    assert definition is not None
    assert definition.cost.costs == ()
    assert definition.cost.is_free


# ======================================================================
# G. 효과 해결 — 관문은 그대로 걸린다
# ======================================================================


@pytest.mark.real_card
def test_g01_the_declared_gate_still_refuses_without_an_answer(repository):
    """
    **§13-G** — 판정 지식을 주지 않으면 자기 참조도 **해결되지 않는다.**

    ``gated=True`` 는 공식 스크립트가 ``Card.IsAbleToHand`` 를 물었다는
    기록이고, 그 답이 없으면 실행기가 멈춘다. 자기 참조라는 이유로 관문이
    열리지 않는다.
    """
    definition = self_definition(
        CardOperation.return_to_hand(SELF_TARGET, gated=True)
    )
    result, state, placed = executed(repository, definition, source=0, rulings=None)
    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert result.missing == "return-to-hand-legality (Card.IsAbleToHand 판정)"
    assert state.find_instance(placed[0].instance_id).zone is Zone.MZONE
    assert result.deltas == ()


@pytest.mark.real_card
def test_g02_an_unknown_face_up_card_on_the_field_stops_it(repository):
    """
    🔴 판에 **모르는 앞면 카드**가 있으면 멈춘다.

    "아무도 안 막는다" 는 판 전체를 읽었을 때만 할 수 있는 말이다
    (``BoardRuling._interference``). 룡기병은 ``OPERATION_RULINGS`` 에 없다.
    """
    definition = self_definition(
        CardOperation.return_to_hand(SELF_TARGET, gated=True)
    )
    result, state, placed = executed(
        repository, definition, source=0, cards=(HONEST, UNKNOWN_EFFECT_MONSTER)
    )
    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.missing == "return-to-hand-legality (Card.IsAbleToHand 판정)"
    assert state.find_instance(placed[0].instance_id).zone is Zone.MZONE
    assert result.deltas == ()

    #: 🔴 **막은 것이 무엇인지는 판정기가 안다.** 실행기의 이유 문장은
    #: 종류별로 정해진 일반문이므로 (``_check_rule_gate``), 간섭한 카드
    #: 이름은 여기서 직접 확인한다 — 이유가 사라진 것이 아니다.
    from engine.effect.ruling import BoardRuling
    from engine.game_state_view import GameStateView

    verdict = BoardRuling(
        GameStateView.from_state(state, viewer=MINE), OPERATION_RULINGS
    ).explain(RuleQuestion.MAY_BE_RETURNED_TO_HAND, placed[0].instance_id)
    assert verdict.answer is ConditionResult.UNKNOWN
    assert str(UNKNOWN_EFFECT_MONSTER) in verdict.reason


@pytest.mark.real_card
def test_g03_a_rule_gated_kind_still_refuses(repository):
    """
    ``destroy`` 는 **종류만으로** 관문을 받는다 (파괴 내성 · 대체 효과).

    자기 참조가 풀렸어도 그 관문은 그대로다 — 블랙홀이 막혀 있는 것과
    같은 자리다.
    """
    definition = self_definition(CardOperation.destroy(SELF_TARGET))
    result, state, placed = executed(repository, definition, source=0)
    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.missing == "destruction-legality (파괴 내성 · 대체 효과 판정)"
    assert state.find_instance(placed[0].instance_id).zone is Zone.MZONE


@pytest.mark.real_card
@pytest.mark.parametrize(
    "operation,destination",
    [
        (CardOperation.send_to_grave(SELF_TARGET), Zone.GRAVE),
        (CardOperation.banish(SELF_TARGET), Zone.REMOVED),
        (CardOperation.return_to_deck(SELF_TARGET), Zone.DECK),
        (CardOperation.release(SELF_TARGET), Zone.GRAVE),
    ],
)
def test_g04_the_same_reference_works_for_other_operation_kinds(
    repository, operation, destination
):
    """
    **§11 재사용** — 같은 이름이 서로 다른 조작 넷에서 그대로 동작한다.

    카드별 분기가 아니라 **공통 참조 표현**이라는 증거다. 어느 것도
    production 목록에 등재하지 않았다 — 확인한 것은 참조가 재사용된다는
    사실 하나다.
    """
    definition = self_definition(operation)
    result, state, placed = executed(repository, definition, source=0)
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    assert state.find_instance(placed[0].instance_id).zone is destination
    assert result.deltas[0].instance == placed[0].instance_id


# ======================================================================
# H. 정보 부족 — 지어내지 않는다
# ======================================================================


@pytest.mark.real_card
def test_h01_a_missing_source_is_refused_not_guessed(repository):
    """
    **§13-H** — ``source`` 가 ``None`` 이면 멈춘다.

    같은 카드 ID 의 다른 인스턴스로 대신하지 않는다 — 그러면 **발동하지
    않은 카드**가 움직인다. 이유 문장이 그것을 적는다.
    """
    definition = self_definition(
        CardOperation.return_to_hand(SELF_TARGET, gated=True)
    )
    result, state, placed = executed(
        repository, definition, source=None, cards=(HONEST, HONEST)
    )
    assert result.status is ResolutionStatus.INVALID_CONTEXT
    assert result.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert "다른 인스턴스로 대신하지 않습니다" in result.reason
    #: 두 장 **다** 그대로다.
    for card in placed:
        assert state.find_instance(card.instance_id).zone is Zone.MZONE
    assert result.deltas == ()


def test_h02_the_resolver_does_not_search_by_card_id():
    """
    자기 참조를 푸는 코드가 **카드 ID 로 찾지 않는다.**

    ``context.source`` 하나만 읽는다 — 찾는 코드가 있으면 "같은 이름의 다른
    카드" 로 새는 길이 생긴다.
    """
    source = (PROJECT_ROOT / "engine" / "effect" / "executor.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_resolve_self_reference"
    )
    body = ast.unparse(function)
    assert "context.source" in body
    for forbidden in ("card_id", "source_card_id", "find_by", "all_cards"):
        assert forbidden not in body, forbidden


# ======================================================================
# I. 어니스트 — 실제 사례
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_i01_honest_is_registered_from_its_own_lua(repository):
    """
    **§13-I** — 등재가 공식 스크립트에서 왔다.

    ``SetType(EFFECT_TYPE_IGNITION)`` · ``SetRange(LOCATION_MZONE)`` ·
    ``IsAbleToHand`` · ``SendtoHand(c,…)`` 넷이 모두 근거에 적혀 있다.
    """
    entry = next(
        e for e in EFFECT_LIBRARY if e.definition.effect_ref == HONEST_REF
    )
    assert entry.executable is True
    assert entry.lua_file == "c37742478.lua"
    assert "IsAbleToHand" in entry.lua_excerpt
    assert "SendtoHand" in entry.lua_excerpt

    definition = entry.definition
    assert definition.references_self is True
    assert definition.requires_target is False
    assert [op.kind for op in definition.operations] == [
        OperationKind.RETURN_TO_HAND
    ]
    assert definition.operations[0].gated is True
    assert definition.operations[0].target_ref == SELF_TARGET

    #: 🔴 옮기지 **못한** 것이 근거에 적혀 있다.
    note = definition.provenance.note
    assert "IsRelateToEffect" in note and "IsFaceup" in note

    #: 공식 Lua 원문이 실제로 그렇게 적는다.
    lua = (PROJECT_ROOT / "c37742478.lua").read_text(encoding="utf-8")
    assert "e1:SetType(EFFECT_TYPE_IGNITION)" in lua
    assert "e:GetHandler():IsAbleToHand()" in lua
    assert "Duel.SendtoHand(c,nil,REASON_EFFECT)" in lua


@requires_official_db
@pytest.mark.real_card
def test_i02_the_movement_answer_cites_the_card_text(repository):
    """
    ``MAY_BE_RETURNED_TO_HAND`` 의 답이 **근거를 들고 있다.**

    ``RuleBasis.CARD_TEXT`` 는 "공식 텍스트 전문을 읽었다" 이고, 그 텍스트가
    실제로 「이 카드를 패로 되돌린다」 라고 적는다.
    """
    facts = OPERATION_RULINGS.facts_for(HONEST)
    assert facts is not None
    fact = facts.answer_for(RuleQuestion.MAY_BE_RETURNED_TO_HAND)
    assert fact is not None
    assert fact.answer is ConditionResult.TRUE
    assert fact.basis is RuleBasis.CARD_TEXT

    card = repository.get(HONEST)
    assert "이 카드를 패로 되돌린다" in (card.desc or "")

    #: 🔴 **다른 질문에는 답하지 않았다.**
    assert set(facts.answers) == {RuleQuestion.MAY_BE_RETURNED_TO_HAND}
    for question in (
        RuleQuestion.MAY_BE_BANISHED,
        RuleQuestion.MAY_BE_SENT_TO_GRAVE,
        RuleQuestion.MAY_BE_DISCARDED,
        RuleQuestion.MAY_BE_RETURNED_TO_DECK,
    ):
        assert facts.answer_for(question) is None, question


@requires_official_db
@pytest.mark.real_card
def test_i03_honest_resolves_through_the_real_duel(repository):
    """
    🔴 **§19 수준 2** — 실제 ``Duel`` 수직 경로가 끝까지 간다.

        legal_actions → apply → 체인 1 → 응답 창 → 해결
          → GameState 변경 → EventJournal

    발동 시점에는 아직 움직이지 않고 (체인에 올라간 뒤 상대가 응답할 수
    있다 — RULE-CHAIN-001), 해결 시점에 패로 돌아간다.
    """
    duel, placed = board(repository, HONEST)
    honest = placed[0].instance_id

    candidates = [
        action
        for action in duel.legal_actions(MINE).allowed
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert len(candidates) == 1
    assert candidates[0].source == honest
    assert candidates[0].effect_ref == HONEST_REF
    #: 🔴 **대상이 없다** — 자기 참조는 대상 지정이 아니다.
    assert candidates[0].targets == ()

    before_hand = len(duel.state.player(MINE).hand)
    step = duel.apply(candidates[0])
    assert step.accepted, step.reason
    assert len(duel.chain) == 1
    assert duel.priority.is_open
    #: 발동만으로는 움직이지 않는다.
    assert duel.state.find_instance(honest).zone is Zone.MZONE

    settled = settle_chain(duel)
    assert settled is not None and settled.accepted, settled.reason if settled else ""
    assert duel.state.find_instance(honest).zone is Zone.HAND
    assert len(duel.state.player(MINE).hand) == before_hand + 1


@requires_official_db
@pytest.mark.real_card
def test_i04_the_journal_records_what_actually_happened(repository):
    """
    **§13-K** — ``EventJournal`` 에 **실제 적용된 결과**가 적힌다.

    기록이 실행을 대신하지 않는다 — 판이 바뀐 해결만 적힌다.
    """
    duel, placed = board(repository, HONEST)
    honest = placed[0].instance_id
    action = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    )
    assert duel.journal is not None
    assert duel.journal.events == ()

    duel.apply(action)
    settle_chain(duel)

    effects = [e for e in duel.journal.events if e.effect_ref == HONEST_REF]
    assert len(effects) == 1
    event = effects[0]
    assert event.actor == MINE
    assert event.source == honest
    assert len(event.deltas) == 1
    delta = event.deltas[0]
    assert delta.instance == honest
    assert delta.source_zone is Zone.MZONE
    assert delta.destination_zone is Zone.HAND


@requires_official_db
@pytest.mark.real_card
def test_i05_two_honests_give_two_candidates_and_move_one(repository):
    """
    실제 듀얼에서 같은 카드 두 장이면 후보가 **둘**이고, 고른 쪽만 움직인다.
    """
    duel, placed = board(repository, HONEST, HONEST)
    first, second = (card.instance_id for card in placed)
    candidates = [
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert {a.source for a in candidates} == {first, second}

    chosen = next(a for a in candidates if a.source == second)
    duel.apply(chosen)
    settle_chain(duel)
    assert duel.state.find_instance(second).zone is Zone.HAND
    assert duel.state.find_instance(first).zone is Zone.MZONE


@requires_official_db
@pytest.mark.real_card
def test_i06_honest_second_effect_is_still_unregistered(repository):
    """
    🔴 어니스트 ②(유발 즉시, 비용 ``Cost.SelfToGrave``)는 **여전히 없다.**

    자기 참조가 열린 것은 **하는 일** 쪽이고 **비용** 쪽이 아니다 (§F).
    """
    assert definition_registry().definition_for(EffectRef(HONEST, 1)) is None
    lua = (PROJECT_ROOT / "c37742478.lua").read_text(encoding="utf-8")
    assert "e2:SetCost(Cost.SelfToGrave)" in lua


# ======================================================================
# J. 기존 ACTIVATE 효과가 그대로다
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_j01_the_normal_spell_still_runs_end_to_end(repository):
    """
    **§13-J** — 욕망의 항아리가 그대로 발동되고 2장 뽑고 묘지로 간다.

    이 Phase 가 마법 경로를 건드리지 않았다는 것이 여기서 증명된다.
    """
    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    spell = state.create_instance(POT_OF_GREED, owner=MINE, zone=Zone.HAND)
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1),
        **duel_components(),
    )
    before = len(duel.state.player(MINE).deck)
    action = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and a.effect_ref == EffectRef(POT_OF_GREED, 0)
    )
    assert duel.apply(action).accepted
    settle_chain(duel)
    assert len(duel.state.player(MINE).deck) == before - 2
    assert duel.state.find_instance(spell.instance_id).zone is Zone.GRAVE


def test_j02_the_library_grew_by_exactly_one_executable():
    """
    등재는 17건 그대로이고 **실행되는 것이 13 에서 14 로** 늘었다.

    늘어난 하나가 어니스트 ① 이고, 그것이 **첫 몬스터 효과 실행**이다.

    🔴 **Phase 6-V 가 둘 다 하나씩 늘렸다** (18 · 15). 늘어난 하나가
    기르수 ① 이고 그것이 **첫 유발 효과 실행**이다 — 6-L 이 "첫 몬스터
    효과" 였던 것과 같은 자리의 다음 걸음이다.

    🔴 **Phase 6-AC 가 다시 하나씩 늘렸다** (19 · 16). 늘어난 하나가
    성유물－『성장』 ① 이고, 그것이 **특수 소환을 실행하는 첫 효과**다.
    """
    assert len(EFFECT_LIBRARY) == 19
    executable = [e for e in EFFECT_LIBRARY if e.executable]
    assert len(executable) == 16
    monsters = [
        e.definition.source_card_id
        for e in executable
        if e.definition.activation_kind is not None
    ]
    assert monsters == [HONEST, GIRSU, WORLD_WAND], monsters


# ======================================================================
# K. 금지 사항 — AST 로 센다
# ======================================================================


def _production_files():
    for package in ("engine", "agent", "integration", "app", "core"):
        yield from sorted((PROJECT_ROOT / package).rglob("*.py"))


def test_k01_no_card_id_branch_resolves_the_reference():
    """
    🔴 **카드 ID 로 자기 참조를 하드코딩하지 않았다** (§3-4 · §10).

    어니스트의 번호가 production 코드에 나타나는 자리는 ``library.py`` 의
    **선언**뿐이고, 비교문은 하나도 없다.
    """
    sites = []
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        numbers = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, int)
        }
        if HONEST in numbers:
            sites.append(str(path.relative_to(PROJECT_ROOT)))
    assert sites == ["engine/effect/library.py"], sites

    tree = ast.parse(
        (PROJECT_ROOT / "engine" / "effect" / "library.py").read_text(
            encoding="utf-8"
        )
    )
    comparisons = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(
            isinstance(operand, ast.Constant) and operand.value == HONEST
            for operand in [node.left, *node.comparators]
        )
    ]
    assert comparisons == []


def test_k02_the_reference_is_resolved_in_exactly_one_place():
    """
    자기 참조를 선택으로 바꾸는 자리가 **하나**다.

    둘이 되면 두 벌이 갈리고, 갈린 뒤에는 어느 쪽이 맞는지 알 수 없다.
    """
    builders = []
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Selection"
                and any(
                    isinstance(kw.value, ast.Tuple)
                    and any(
                        isinstance(element, ast.Attribute)
                        and element.attr == "source"
                        for element in kw.value.elts
                    )
                    for kw in node.keywords
                )
            ):
                builders.append(str(path.relative_to(PROJECT_ROOT)))
    assert builders == ["engine/effect/executor.py"], builders


def test_k03_the_public_action_contract_is_unchanged():
    """
    ``PlayerAction`` · ``EffectRef`` · ``ResolutionContext`` 의 칸이
    **하나도 바뀌지 않았다** (§3-1 · §3-2).
    """
    #: 🔴 **Phase 6-AC 가 ``materials`` 를 더했다.** 이 단언은 "칸이 하나도
    #: 바뀌지 않았다" 를 지키던 것이고, 바뀐 이유를 함께 적어 둔다 — 링크
    #: 소재는 **대상이 아니므로** ``targets`` 에 넣을 수 없었다
    #: (``PlayerAction.materials`` 의 설명).
    assert [f.name for f in dataclasses.fields(PlayerAction)] == [
        "kind", "actor", "source", "targets", "effect_ref", "phase", "materials"
    ]
    assert [f.name for f in dataclasses.fields(EffectRef)] == ["card_id", "ordinal"]
    assert [f.name for f in dataclasses.fields(ResolutionContext)] == [
        "effect_ref",
        "controller",
        "source",
        "selections",
        "cost_selections",
        "declarations",
    ]


def test_k04_the_duel_resolver_is_given_the_knowledge_it_needs():
    """
    ``duel_resolver`` 가 조작 판정 지식을 **명시적으로** 넘긴다.

    ``build_executor`` 는 그것을 기본값으로 넣지 않는다 (ADR-006) — "목록에
    실렸다는 사실이 판정을 대신하게" 되기 때문이고, 그래서 부르는 쪽이
    고른다. 넘기지 않으면 ``gated=True`` 이동이 하나도 일어나지 않는다.
    """
    import inspect

    from engine.effect.library import build_executor
    from engine.spell_activation import duel_resolver

    signature = inspect.signature(build_executor)
    assert signature.parameters["rulings"].default is None

    source = inspect.getsource(duel_resolver)
    assert "rulings=OPERATION_RULINGS" in source
