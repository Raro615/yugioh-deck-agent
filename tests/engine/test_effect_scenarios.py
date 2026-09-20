"""
Phase 2-P — 효과 실행 시나리오 검증.

**새 기능을 만들지 않는다.** 지금까지 쌓인 실행 경로가 서로 다른 효과
유형에서도 같은 약속을 지키는지, 실제 시나리오로 확인한다.

    정의 → (대상) → 의미 → 조작 → GameState → Delta → 사건 → 기록

다섯 시나리오를 본다.

=====  ==================================================================
**A**  대상을 지정하는 효과 (Phase 2-O 회귀)
**B**  대상을 **쓰지 않는** 효과 — 대상 계층에 들어가지 않는다
**C**  ``MOVE`` — 의미를 주장하지 않는 저수준 이동
**D**  실패 행렬 — 아홉 가지 실패가 서로 다른 답을 유지한다
**E**  결정론 · 복제 독립성
=====  ==================================================================

여기서 쓰는 도구는 전부 이미 있던 것이다. ``TargetResolver`` 도
``EffectExecutor`` 도 ``EventReader`` 도 새로 만들지 않았고, 새 ``EventBus``
도 없다 — 마지막 묶음이 그것을 AST 로 확인한다.

실제 카드와 synthetic 을 섞지 않는다
------------------------------------
실제 카드의 재정을 지어내지 않는다 (Phase 2-O 의 §8 과 같은 규칙).
``DeclaredDestructionRuling`` 을 받는 것은 **아무 카드의 의미도 주장하지
않는 synthetic 정의**뿐이고, 실제 카드는 규칙 지식이 없으면 멈춘 상태
그대로 둔다.
"""

import ast
import pathlib

import pytest

from engine.condition import Always, IsMonster, PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.effect.definition import (
    EffectDefinition,
    EffectProvenance,
    ExecutionAvailability,
)
from engine.effect.delta import CardDrawn, LifeChanged, ZoneMoved
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.library import (
    DARK_HOLE,
    MYSTICAL_SPACE_TYPHOON,
    POT_OF_GREED,
    RAIN_OF_MERCY,
    availability,
    build_executor,
    definition_registry,
    entry_for,
)
from engine.effect.operation import (
    CardOperation,
    DrawOperation,
    LifeChangeOperation,
    MoveOperation,
    OperationKind,
    UnimplementedOperation,
)
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.semantics import DeclaredDestructionRuling
from engine.effect.target import (
    PRIMARY_TARGET,
    TargetBinding,
    TargetSpec,
)
from engine.effect.targeting import TargetLegality, TargetResolver
from engine.event_pipeline import EventReader, ObservedEvent
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.trigger import TimingEvent, TimingPoint
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1

MST = MYSTICAL_SPACE_TYPHOON  # 싸이크론 — 대상 지정 효과
FEATHERMAN = 21844576  # 엘리멘틀 히어로 페더맨 — 통상 몬스터
LAB = 2511  # synthetic 정의의 **껍데기**. 이 카드의 의미를 주장하지 않는다

PRIMARY = PRIMARY_TARGET

MST_EFFECT = EffectRef(MST, 0)
POT_EFFECT = EffectRef(POT_OF_GREED, 0)
RAIN_EFFECT = EffectRef(RAIN_OF_MERCY, 0)
DARK_HOLE_EFFECT = EffectRef(DARK_HOLE, 0)


# ======================================================================
# 판
# ======================================================================


def new_state(repository) -> GameState:
    """
    p0(MINE)
        SZONE  싸이크론 (앞면)
        MZONE  페더맨 (앞면)
        GRAVE  페더맨 1장
        HAND   욕망의 항아리 · 은혜의 단비 · 페더맨
        DECK   넉넉히
    p1(THEIRS)
        SZONE  블랙홀 (앞면) · 블랙홀 (**뒷면**)
        MZONE  페더맨 (앞면)
        HAND   비어 있음
    """
    game = GameState.create(
        repository,
        decks=(
            [MST, POT_OF_GREED, RAIN_OF_MERCY] + [FEATHERMAN] * 17,
            [DARK_HOLE] * 2 + [FEATHERMAN] * 18,
        ),
    )
    game.draw(MINE, 6)  # 싸이크론 · 욕망 · 단비 · 페더맨 ×3
    game.draw(THEIRS, 3)  # 블랙홀 ×2 · 페더맨

    game.move(
        game.player(MINE).hand[0], Zone.SZONE, to_player=MINE,
        position=Position.FACEUP,
    )
    game.move(
        game.player(MINE).hand[-1], Zone.MZONE, to_player=MINE,
        position=Position.FACEUP_ATTACK,
    )
    game.move(game.player(MINE).hand[-1], Zone.GRAVE, to_player=MINE)
    game.move(
        game.player(THEIRS).hand[0], Zone.SZONE, to_player=THEIRS,
        position=Position.FACEUP,
    )
    game.move(
        game.player(THEIRS).hand[0], Zone.SZONE, to_player=THEIRS,
        position=Position.FACEDOWN,
    )
    game.move(
        game.player(THEIRS).hand[0], Zone.MZONE, to_player=THEIRS,
        position=Position.FACEUP_ATTACK,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


# ======================================================================
# 자리 찾기
# ======================================================================


def the_typhoon(state: GameState) -> InstanceId:
    for card in state.player(MINE).spell_zone:
        if card.card_id == MST:
            return card.instance_id
    raise AssertionError("싸이크론이 필드에 없습니다.")


def their_faceup_spell(state: GameState) -> InstanceId:
    return state.player(THEIRS).spell_zone[0].instance_id


def their_facedown_spell(state: GameState) -> InstanceId:
    return state.player(THEIRS).spell_zone[1].instance_id


def their_monster(state: GameState) -> InstanceId:
    return state.player(THEIRS).monster_zone[0].instance_id


def my_monster(state: GameState) -> InstanceId:
    return state.player(MINE).monster_zone[0].instance_id


def my_grave_card(state: GameState) -> InstanceId:
    return state.player(MINE).grave[0].instance_id


def my_hand_card(state: GameState, card_id: int | None = None) -> InstanceId:
    for card in state.player(MINE).hand:
        if card_id is None or card.card_id == card_id:
            return card.instance_id
    raise AssertionError(f"패에 {card_id} 가 없습니다.")


# ======================================================================
# 실행 도구 — 전부 기존 계층을 그대로 부른다
# ======================================================================


def real(effect_ref: EffectRef) -> EffectDefinition:
    """라이브러리가 들고 있는 **그** 정의. 테스트가 만들지 않는다."""
    found = definition_registry().definition_for(effect_ref)
    assert found is not None, f"{effect_ref} 가 라이브러리에 없습니다."
    return found


def run_real(
    state: GameState,
    effect_ref: EffectRef,
    *chosen: InstanceId,
    source: InstanceId | None = None,
    journal: EventJournal | None = None,
):
    """
    실제 카드를 **판정 없이** 실행한다.

    ``destruction`` 을 주지 않는 것이 요점이다 — 실제 카드의 파괴 재정을
    이 저장소가 주장하지 않는다.
    """
    selections = (
        (TargetSelection(PRIMARY, Selection(chosen=tuple(chosen))),) if chosen else ()
    )
    return build_executor(journal=journal).execute(
        state,
        real(effect_ref),
        ResolutionContext(
            effect_ref=effect_ref,
            controller=MINE,
            source=source,
            selections=selections,
        ),
    )


def synthetic(
    *operations,
    targets: tuple[TargetBinding, ...] = (),
    ordinal: int = 0,
    provenance: EffectProvenance | None = None,
    activation=None,
) -> EffectDefinition:
    """
    **synthetic 정의.** 실제 카드의 의미를 주장하지 않는다 — 출처가
    ``hand_written`` 이라고 적혀 있고, 실행 경로의 모양만 시험한다.
    """
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        operations=tuple(operations),
        targets=targets,
        activation=activation,
        provenance=provenance
        or EffectProvenance.hand_written(verified=True, note="Phase 2-P 시나리오"),
    )


def single_target(
    *zones: Zone,
    owner: PlayerRef | None = None,
    require=None,
    minimum: int = 1,
    maximum: int = 1,
) -> tuple[TargetBinding, ...]:
    return TargetBinding.single(
        TargetSpec.targeting(
            ChoiceSpec(
                source=CandidateSource(
                    zones=frozenset(zones), owner=owner, require=require
                ),
                minimum=minimum,
                maximum=maximum,
            )
        )
    )


def run_synthetic(
    state: GameState,
    definition: EffectDefinition,
    *chosen: InstanceId,
    destruction=None,
    journal: EventJournal | None = None,
    registered: bool = True,
    context: ResolutionContext | None = None,
):
    executor = EffectExecutor(
        lookup=(
            EffectImplementationRegistry((definition.effect_ref,))
            if registered
            else None
        ),
        journal=journal,
        destruction=destruction,
    )
    if context is None:
        selections = (
            (TargetSelection(PRIMARY, Selection(chosen=tuple(chosen))),)
            if chosen
            else ()
        )
        context = ResolutionContext(
            effect_ref=definition.effect_ref,
            controller=MINE,
            selections=selections,
        )
    return executor.execute(state, definition, context)


def confirmed(*instances: InstanceId) -> DeclaredDestructionRuling:
    """
    **테스트가 명시적으로 선언한** 파괴 판정. synthetic 정의에만 준다.
    """
    return DeclaredDestructionRuling(destructible=frozenset(instances))


def events_of(state: GameState, result, viewer: int = MINE):
    return EventReader(GameStateView.from_state(state, viewer=viewer)).read(
        result, actor=MINE
    )


# ======================================================================
# 시나리오 A — 대상을 지정하는 효과 (Phase 2-O 회귀)
# ======================================================================


@requires_official_db
def test_a_the_real_typhoon_still_stops_at_the_destruction_ruling(state):
    """실제 카드는 대상까지 통과하고 **파괴 판정에서** 멈춘다."""
    target = their_faceup_spell(state)
    before = state.state_hash()

    checked = TargetResolver(GameStateView.from_state(state, viewer=MINE)).validate(
        real(MST_EFFECT).target_spec(PRIMARY),
        Selection.of(target),
        ResolutionContext(
            effect_ref=MST_EFFECT, controller=MINE, source=the_typhoon(state)
        ).condition_context(),
        PRIMARY,
    )
    result = run_real(state, MST_EFFECT, target, source=the_typhoon(state))

    assert checked.legality is TargetLegality.LEGAL
    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_a_a_confirmed_synthetic_destroy_still_runs_the_whole_way(state):
    """synthetic 은 판정을 받고 끝까지 간다."""
    target = their_monster(state)
    definition = synthetic(
        CardOperation.destroy(PRIMARY),
        targets=single_target(Zone.MZONE, require=IsMonster()),
    )
    journal = EventJournal()
    before = state.state_hash()

    result = run_synthetic(
        state, definition, target, destruction=confirmed(target), journal=journal
    )
    observed = events_of(state, result)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(target).zone is Zone.GRAVE
    assert state.state_hash() != before
    assert result.applied[0].kind is OperationKind.DESTROY
    assert observed[0].timing.point is TimingPoint.CARD_MOVED
    assert observed[0].timing.operation is OperationKind.DESTROY
    assert len(journal) == 1


# ======================================================================
# 시나리오 B — 대상을 쓰지 않는 효과
# ======================================================================


@requires_official_db
def test_b_a_real_non_targeted_card_resolves_without_the_target_layer(state):
    """
    욕망의 항아리. **실제 카드가 끝까지 간다** — 파괴가 아니므로 판정을
    받을 것이 없다.
    """
    definition = real(POT_EFFECT)
    hand_before = len(state.player(MINE).hand)
    before = state.state_hash()

    result = run_real(state, POT_EFFECT)

    assert definition.targets == ()
    assert availability(POT_EFFECT) is ExecutionAvailability.EXECUTABLE
    assert result.status is ResolutionStatus.RESOLVED
    assert len(state.player(MINE).hand) == hand_before + 2
    assert state.state_hash() != before
    assert all(isinstance(delta, CardDrawn) for delta in result.deltas)


@requires_official_db
def test_b_a_non_targeted_effect_never_enters_target_selection(state):
    """
    §4 — 고를 것이 없으므로 기다릴 것도 없다. 빈 ``selections`` 로도
    해결된다.
    """
    definition = real(POT_EFFECT)
    context = ResolutionContext(effect_ref=POT_EFFECT, controller=MINE)

    assert context.pending_targets(definition) == ()
    assert context.selections == ()
    assert run_real(state, POT_EFFECT).status is ResolutionStatus.RESOLVED


@requires_official_db
def test_b_a_targeted_effect_with_no_selection_is_not_the_same_thing(state):
    """
    **"대상이 없다" 와 "대상을 빠뜨렸다" 를 구분한다.** 모양이 비슷해도
    답이 다르다.
    """
    definition = real(MST_EFFECT)
    context = ResolutionContext(
        effect_ref=MST_EFFECT, controller=MINE, source=the_typhoon(state)
    )

    assert context.pending_targets(definition) == (PRIMARY,)
    assert run_real(state, MST_EFFECT, source=the_typhoon(state)).status is (
        ResolutionStatus.INVALID_TARGET
    )


@requires_official_db
def test_b_a_life_changing_card_reaches_both_players(state):
    """은혜의 단비 — 두 개의 일이고, 두 개의 변화다."""
    before = (state.player(MINE).life_points, state.player(THEIRS).life_points)

    result = run_real(state, RAIN_EFFECT)

    assert result.status is ResolutionStatus.RESOLVED
    assert len(result.applied) == 2
    assert len(result.deltas) == 2
    assert all(isinstance(delta, LifeChanged) for delta in result.deltas)
    assert (state.player(MINE).life_points, state.player(THEIRS).life_points) == (
        before[0] + 1000,
        before[1] + 1000,
    )


@requires_official_db
def test_b_the_event_pipeline_reads_non_targeted_effects_too(state):
    """드로우와 라이프 변화도 같은 통로를 지난다. 새 통로가 없다."""
    drawn = run_real(state, POT_EFFECT)
    healed = run_real(state, RAIN_EFFECT)

    points = [event.timing.point for event in events_of(state, drawn)] + [
        event.timing.point for event in events_of(state, healed)
    ]

    assert points == [
        TimingPoint.CARD_DRAWN,
        TimingPoint.CARD_DRAWN,
        TimingPoint.LIFE_CHANGED,
        TimingPoint.LIFE_CHANGED,
    ]


@requires_official_db
def test_b_a_synthetic_non_targeted_effect_resolves(state):
    """정의 쪽에서도 ``targets=()`` 하나로 충분하다."""
    definition = synthetic(DrawOperation(count=1, who=PlayerRef.CONTROLLER))
    hand_before = len(state.player(MINE).hand)

    result = run_synthetic(state, definition)

    assert definition.targets == ()
    assert result.status is ResolutionStatus.RESOLVED
    assert len(state.player(MINE).hand) == hand_before + 1


@requires_official_db
def test_b_no_targets_does_not_mean_the_target_rule_was_understood(state):
    """
    🟠 **``targets == ()`` 하나로는 두 가지가 구분되지 않는다.**

    - 욕망의 항아리: 대상을 **요구하지 않는다**
    - 블랙홀: "필드의 몬스터 **전부**" 를 ``TargetSpec`` 이 담지 못한다
      (STRUCTURAL-10)

    지금은 ``LibraryEntry.executable`` 과 ``note`` 가 그 차이를 들고 있고,
    등록되지 않은 블랙홀은 실행되지 않는다. 정의 **자체**는 둘을 구분하지
    못한다 — 그 사실을 여기 적어 둔다.
    """
    pot, dark_hole = real(POT_EFFECT), real(DARK_HOLE_EFFECT)

    assert pot.targets == dark_hole.targets == ()  # 모양이 같다
    # 구분은 정의 밖에 있다.
    assert entry_for(POT_EFFECT).executable is True
    assert entry_for(DARK_HOLE_EFFECT).executable is False
    assert entry_for(DARK_HOLE_EFFECT).note
    assert availability(DARK_HOLE_EFFECT) is ExecutionAvailability.NO_IMPLEMENTATION


@requires_official_db
def test_b_the_unexpressed_card_does_not_run(state):
    """블랙홀은 실행되지 않는다. 판은 그대로다."""
    before = state.state_hash()

    result = run_real(state, DARK_HOLE_EFFECT)

    assert result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert result.deltas == ()
    assert state.state_hash() == before


# ======================================================================
# 시나리오 C — MOVE 는 의미를 주장하지 않는다
# ======================================================================


@requires_official_db
@pytest.mark.parametrize(
    "origin, destination, finder",
    [
        (Zone.HAND, Zone.GRAVE, my_hand_card),
        (Zone.HAND, Zone.DECK, my_hand_card),
        (Zone.GRAVE, Zone.HAND, my_grave_card),
    ],
)
def test_c_move_actually_moves_the_card(state, origin, destination, finder):
    target = finder(state)
    definition = synthetic(
        MoveOperation(destination=destination, target_ref=PRIMARY),
        targets=single_target(origin, owner=PlayerRef.CONTROLLER),
    )

    result = run_synthetic(state, definition, target)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(target).zone is destination


@requires_official_db
def test_c_move_claims_no_reason_at_all(state):
    """
    **비어 있는 것이 사실이다.** ``REASON_EFFECT`` 조차 주장하지 않는다 —
    주장하는 순간 트리거 계층이 "효과로 묘지에 갔다" 로 읽는다.
    """
    target = my_hand_card(state)
    definition = synthetic(
        MoveOperation(destination=Zone.GRAVE, target_ref=PRIMARY),
        targets=single_target(Zone.HAND, owner=PlayerRef.CONTROLLER),
    )

    result = run_synthetic(state, definition, target)

    assert result.applied[0].kind is OperationKind.MOVE
    assert result.applied[0].reason_names == ()
    assert result.deltas[0].reason_names == ()


@requires_official_db
def test_c_move_to_the_graveyard_is_not_a_discard(state):
    """
    같은 패에서 같은 묘지로 가지만 **다른 사건**이다 (ADR-002).
    """
    moved_card, discarded_card = (
        card.instance_id for card in state.player(MINE).hand[:2]
    )
    moving = synthetic(
        MoveOperation(destination=Zone.GRAVE, target_ref=PRIMARY),
        targets=single_target(Zone.HAND, owner=PlayerRef.CONTROLLER),
    )
    discarding = synthetic(
        CardOperation.discard(PRIMARY),
        targets=single_target(Zone.HAND, owner=PlayerRef.CONTROLLER),
        ordinal=1,
    )

    moved = run_synthetic(state, moving, moved_card)
    discarded = run_synthetic(state, discarding, discarded_card)

    assert state.locate(moved_card).zone is state.locate(discarded_card).zone
    assert moved.deltas[0].operation is OperationKind.MOVE
    assert discarded.deltas[0].operation is OperationKind.DISCARD
    assert moved.deltas[0].reason_names == ()
    assert "DISCARD" in discarded.deltas[0].reason_names


@requires_official_db
def test_c_move_is_not_gated_the_way_destroy_is(state):
    """
    같은 판 · 같은 대상 · 판정기 없음. ``MOVE`` 는 지나가고 ``DESTROY`` 는
    멈춘다 — 판정을 요구하는 것은 **의미를 주장하는 쪽**이기 때문이다.
    """
    target = their_monster(state)
    rule = single_target(Zone.MZONE, require=IsMonster())
    moving = synthetic(
        MoveOperation(destination=Zone.GRAVE, target_ref=PRIMARY), targets=rule
    )
    destroying = synthetic(CardOperation.destroy(PRIMARY), targets=rule, ordinal=1)

    blocked = run_synthetic(state, destroying, target)  # 판정기 없음
    assert blocked.status is ResolutionStatus.UNCHECKED_RULES
    assert state.locate(target).zone is Zone.MZONE

    passed = run_synthetic(state, moving, target)  # 역시 판정기 없음

    assert passed.status is ResolutionStatus.RESOLVED
    assert state.locate(target).zone is Zone.GRAVE


@requires_official_db
def test_c_a_move_event_says_move_not_destroy(state):
    target = my_hand_card(state)
    definition = synthetic(
        MoveOperation(destination=Zone.GRAVE, target_ref=PRIMARY),
        targets=single_target(Zone.HAND, owner=PlayerRef.CONTROLLER),
    )

    result = run_synthetic(state, definition, target)
    observed = events_of(state, result)

    assert observed[0].timing.point is TimingPoint.CARD_MOVED
    assert observed[0].timing.operation is OperationKind.MOVE
    assert observed[0].timing.operation is not OperationKind.DESTROY


@requires_official_db
def test_c_move_records_where_it_came_from(state):
    target = my_grave_card(state)
    definition = synthetic(
        MoveOperation(destination=Zone.HAND, target_ref=PRIMARY),
        targets=single_target(Zone.GRAVE, owner=PlayerRef.CONTROLLER),
    )

    result = run_synthetic(state, definition, target)
    delta = result.deltas[0]

    assert isinstance(delta, ZoneMoved)
    assert (delta.from_zone, delta.to_zone) == (Zone.GRAVE, Zone.HAND)


def test_c_move_cannot_reach_the_field():
    """필드로 보내는 것은 소환 절차의 일이다. 여기서 흉내 내지 않는다."""
    for zone in (Zone.MZONE, Zone.SZONE, Zone.EMZONE, Zone.FZONE, Zone.PZONE):
        with pytest.raises(ValueError):
            MoveOperation(destination=zone, target_ref=PRIMARY)


# ======================================================================
# 시나리오 D — 실패 행렬 (아홉 가지)
# ======================================================================


@requires_official_db
def test_d_1_text_derived_is_forbidden(state):
    definition = synthetic(
        DrawOperation(count=1, who=PlayerRef.CONTROLLER),
        provenance=EffectProvenance.text_derived("텍스트에서 유추했다고 치자"),
    )
    before = state.state_hash()

    result = run_synthetic(state, definition)

    assert result.status is ResolutionStatus.FORBIDDEN
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_d_2_verified_meaning_without_an_implementation_does_not_run(state):
    """ADR-006 — 검증된 의미만으로는 실행하지 않는다."""
    before = state.state_hash()

    result = run_synthetic(
        state,
        synthetic(DrawOperation(count=1, who=PlayerRef.CONTROLLER)),
        registered=False,
    )

    assert result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_d_3_an_illegal_target_is_refused(state):
    """자신 필드라고 적어 놓고 상대 몬스터를 골랐다."""
    definition = synthetic(
        CardOperation.send_to_grave(PRIMARY),
        targets=single_target(Zone.MZONE, owner=PlayerRef.CONTROLLER),
    )
    before = state.state_hash()

    result = run_synthetic(state, definition, their_monster(state))

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert state.state_hash() == before


@requires_official_db
def test_d_4_an_unknown_target_is_not_an_illegal_one(state):
    """상대의 세트 카드는 **모르는** 대상이다."""
    definition = synthetic(
        CardOperation.send_to_grave(PRIMARY),
        targets=single_target(Zone.SZONE, require=IsMonster()),
    )
    before = state.state_hash()

    result = run_synthetic(state, definition, their_facedown_spell(state))

    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert state.state_hash() == before


@requires_official_db
def test_d_5_a_missing_selection_is_refused(state):
    definition = synthetic(
        CardOperation.send_to_grave(PRIMARY),
        targets=single_target(Zone.MZONE),
    )
    before = state.state_hash()

    result = run_synthetic(state, definition)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    assert state.state_hash() == before


@requires_official_db
def test_d_6_a_stale_target_is_caught_before_anything_moves(state):
    """고른 뒤 그 카드가 자리를 떠났다."""
    target = my_monster(state)
    definition = synthetic(
        CardOperation.send_to_grave(PRIMARY),
        targets=single_target(Zone.MZONE, require=IsMonster()),
    )
    state.move(state.find_instance(target), Zone.REMOVED, to_player=MINE)
    before = state.state_hash()

    result = run_synthetic(state, definition, target)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_d_7_an_unknown_destruction_rule_stops_the_effect(state):
    target = their_monster(state)
    definition = synthetic(
        CardOperation.destroy(PRIMARY),
        targets=single_target(Zone.MZONE, require=IsMonster()),
    )
    before = state.state_hash()

    result = run_synthetic(state, definition, target)  # 판정기 없음

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.unchecked_rules
    assert state.state_hash() == before


@requires_official_db
def test_d_8_an_unsupported_operation_stops_the_effect(state):
    """
    "이 실행기가 못 한다" 는 "그 일이 말이 안 된다" 와 다른 답이다.
    """
    before = state.state_hash()

    result = run_synthetic(state, synthetic(UnimplementedOperation("특수 소환")))

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert result.missing
    assert state.state_hash() == before


@requires_official_db
def test_d_9_a_context_for_another_effect_is_refused(state):
    """문맥이 다른 효과를 가리키면 실행하지 않는다."""
    definition = synthetic(DrawOperation(count=1, who=PlayerRef.CONTROLLER))
    before = state.state_hash()

    result = run_synthetic(
        state,
        definition,
        context=ResolutionContext(effect_ref=POT_EFFECT, controller=MINE),
    )

    assert result.status is ResolutionStatus.INVALID_CONTEXT
    assert result.code is ValidationCode.EFFECT_REF_CARD_MISMATCH
    assert state.state_hash() == before


@requires_official_db
def test_d_every_failure_keeps_its_own_answer(repository):
    """
    아홉 가지를 **한 자리에서** 돌려 놓고, ``(status, code)`` 가 아홉 개
    모두 다른지 본다. 하나로 뭉개지면 무엇을 고쳐야 하는지 알 수 없다.

    판마다 새로 세운다 — 앞선 실패가 뒤의 답을 바꾸지 않아야 하고, 그러려면
    서로 영향을 주지 않는 자리에서 돌려야 한다.
    """
    draw = DrawOperation(count=1, who=PlayerRef.CONTROLLER)

    def text_derived(board):
        return run_synthetic(
            board,
            synthetic(draw, provenance=EffectProvenance.text_derived()),
        )

    def unregistered(board):
        return run_synthetic(board, synthetic(draw), registered=False)

    def illegal_target(board):
        return run_synthetic(
            board,
            synthetic(
                CardOperation.send_to_grave(PRIMARY),
                targets=single_target(Zone.MZONE, owner=PlayerRef.CONTROLLER),
            ),
            their_monster(board),
        )

    def unknown_target(board):
        return run_synthetic(
            board,
            synthetic(
                CardOperation.send_to_grave(PRIMARY),
                targets=single_target(Zone.SZONE, require=IsMonster()),
            ),
            their_facedown_spell(board),
        )

    def no_target(board):
        return run_synthetic(
            board,
            synthetic(
                CardOperation.send_to_grave(PRIMARY),
                targets=single_target(Zone.MZONE),
            ),
        )

    def stale_target(board):
        target = my_monster(board)
        board.move(board.find_instance(target), Zone.REMOVED, to_player=MINE)
        return run_synthetic(
            board,
            synthetic(
                CardOperation.send_to_grave(PRIMARY),
                targets=single_target(Zone.MZONE, require=IsMonster()),
            ),
            target,
        )

    def unknown_rule(board):
        return run_synthetic(
            board,
            synthetic(
                CardOperation.destroy(PRIMARY),
                targets=single_target(Zone.MZONE, require=IsMonster()),
            ),
            their_monster(board),
        )

    def unsupported(board):
        return run_synthetic(board, synthetic(UnimplementedOperation("특수 소환")))

    def wrong_context(board):
        return run_synthetic(
            board,
            synthetic(draw),
            context=ResolutionContext(effect_ref=POT_EFFECT, controller=MINE),
        )

    cases = {
        "TEXT_DERIVED": text_derived,
        "구현 없음": unregistered,
        "부적법한 대상": illegal_target,
        "모르는 대상": unknown_target,
        "대상 없음": no_target,
        "떠난 대상": stale_target,
        "모르는 파괴 규칙": unknown_rule,
        "못 하는 일": unsupported,
        "다른 효과의 문맥": wrong_context,
    }

    answers: dict[str, tuple] = {}
    for name, case in cases.items():
        board = new_state(repository)
        if name == "떠난 대상":
            # 이 갈래만 **준비 단계에서** 판을 바꾼다 (대상이 자리를 떠난다).
            # 해시는 그 뒤부터 센다 — 재는 것은 "실행이 판을 바꿨는가" 다.
            target = my_monster(board)
            board.move(board.find_instance(target), Zone.REMOVED, to_player=MINE)
            before = board.state_hash()
            result = run_synthetic(
                board,
                synthetic(
                    CardOperation.send_to_grave(PRIMARY),
                    targets=single_target(Zone.MZONE, require=IsMonster()),
                ),
                target,
            )
        else:
            before = board.state_hash()
            result = case(board)
        assert result.status is not ResolutionStatus.RESOLVED, name
        assert result.applied == (), name
        assert result.deltas == (), name
        assert board.state_hash() == before, name
        answers[name] = (result.status, result.code)

    # 🟠 아홉 갈래가 **여덟 개**의 답으로 나온다. 겹치는 하나는 아래가
    #    따로 본다 — 지금 겹친다는 사실을 덮지 않으려고 숫자를 그대로 적는다.
    assert len(set(answers.values())) == 8, answers
    assert answers["TEXT_DERIVED"][0] is ResolutionStatus.FORBIDDEN
    assert answers["구현 없음"][0] is ResolutionStatus.NOT_IMPLEMENTED
    assert answers["모르는 대상"][0] is ResolutionStatus.UNCHECKED_TARGET
    assert answers["대상 없음"][1] is ValidationCode.TOO_FEW_SELECTED
    assert answers["모르는 파괴 규칙"][0] is ResolutionStatus.UNCHECKED_RULES
    assert answers["못 하는 일"][0] is ResolutionStatus.UNSUPPORTED_OPERATION
    assert answers["다른 효과의 문맥"][1] is ValidationCode.EFFECT_REF_CARD_MISMATCH


@requires_official_db
def test_d_a_stale_target_is_indistinguishable_from_one_that_never_qualified(state):
    """
    🟠 **STRUCTURAL-53 — 이번 단계에서 드러난 것.**

    두 가지가 같은 답으로 나온다.

    1. **애초에 후보가 아니었다** — "자신 필드의 몬스터" 인데 상대 몬스터를
       골랐다. 고른 순간부터 틀렸다.
    2. **고를 때는 후보였는데 그 사이에 자리를 떠났다** — 유희왕에서는
       "대상이 필드를 벗어나 효과가 불발" 이고, 발동 자체가 위법이었던 것과
       **다른 사건**이다.

    둘 다 지금은 ``INVALID_TARGET`` / ``CANDIDATE_NOT_ELIGIBLE`` 이다.
    실행기가 "지금 후보인가" 만 볼 수 있고, **발동 시점에 확정된 대상**을
    들고 있지 않기 때문이다 (STRUCTURAL-51).

    위험하지는 않다 — 둘 다 거절하고 판을 건드리지 않는다. 다만 이 구분이
    없으면 "불발" 과 "위법한 발동" 을 영영 나눌 수 없으므로 적어 둔다.
    이번 단계에서 고치지 않는다 (§8: 새 시스템을 만들지 않는다).
    """
    rule = single_target(Zone.MZONE, owner=PlayerRef.CONTROLLER, require=IsMonster())
    never_qualified = run_synthetic(
        state,
        synthetic(CardOperation.send_to_grave(PRIMARY), targets=rule),
        their_monster(state),
    )

    left_the_field = my_monster(state)
    state.move(state.find_instance(left_the_field), Zone.REMOVED, to_player=MINE)
    went_away = run_synthetic(
        state,
        synthetic(CardOperation.send_to_grave(PRIMARY), targets=rule, ordinal=1),
        left_the_field,
    )

    assert (never_qualified.status, never_qualified.code) == (
        (went_away.status, went_away.code)
    )
    assert never_qualified.status is ResolutionStatus.INVALID_TARGET
    assert never_qualified.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    # 둘 다 판을 건드리지 않는다 — 구분이 없다고 위험한 것은 아니다.
    assert never_qualified.deltas == went_away.deltas == ()


@requires_official_db
def test_d_a_failed_operation_cancels_the_ones_before_it(state):
    """
    앞의 드로우가 멀쩡해도, 뒤의 일이 막히면 **한 장도 뽑지 않는다.**
    계획이 전부 끝난 뒤에야 적용이 시작되기 때문이다.
    """
    definition = synthetic(
        DrawOperation(count=1, who=PlayerRef.CONTROLLER),
        CardOperation.destroy(PRIMARY),
        targets=single_target(Zone.MZONE, require=IsMonster()),
    )
    hand_before = len(state.player(MINE).hand)
    before = state.state_hash()

    result = run_synthetic(state, definition, their_monster(state))

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert len(state.player(MINE).hand) == hand_before
    assert state.state_hash() == before


# ======================================================================
# 시나리오 E — 결정론 · 복제 독립성 · 정보 경계
# ======================================================================


@requires_official_db
def test_e_the_same_inputs_give_the_same_result(repository):
    first, second = new_state(repository), new_state(repository)
    definition = synthetic(
        CardOperation.destroy(PRIMARY),
        targets=single_target(Zone.MZONE, require=IsMonster()),
    )

    left = run_synthetic(
        first, definition, their_monster(first), destruction=confirmed(their_monster(first))
    )
    right = run_synthetic(
        second, definition, their_monster(second), destruction=confirmed(their_monster(second))
    )

    assert left.canonical_state() == right.canonical_state()
    assert first.state_hash() == second.state_hash()


@requires_official_db
def test_e_the_same_inputs_give_the_same_event_identity(repository):
    """사건 식별자는 **내용에서** 나온다 — 시각도 주소도 쓰지 않는다."""
    first, second = new_state(repository), new_state(repository)
    definition = synthetic(
        CardOperation.send_to_grave(PRIMARY),
        targets=single_target(Zone.MZONE, require=IsMonster()),
    )

    left = events_of(first, run_synthetic(first, definition, their_monster(first)))
    right = events_of(second, run_synthetic(second, definition, their_monster(second)))

    assert [event.event_id for event in left] == [event.event_id for event in right]
    assert left[0].canonical_state() == right[0].canonical_state()


@requires_official_db
def test_e_failures_are_deterministic_too(repository):
    first, second = new_state(repository), new_state(repository)

    left = run_real(first, MST_EFFECT, their_faceup_spell(first), source=the_typhoon(first))
    right = run_real(
        second, MST_EFFECT, their_faceup_spell(second), source=the_typhoon(second)
    )

    assert left.canonical_state() == right.canonical_state()


@requires_official_db
def test_e_executing_on_a_clone_leaves_the_original_alone(state):
    """§12.6 — 복제본에서 실행해도 원본은 한 글자도 바뀌지 않는다."""
    copy = state.clone()
    target = their_monster(copy)
    definition = synthetic(
        CardOperation.destroy(PRIMARY),
        targets=single_target(Zone.MZONE, require=IsMonster()),
    )
    before = state.state_hash()

    result = run_synthetic(copy, definition, target, destruction=confirmed(target))

    assert result.status is ResolutionStatus.RESOLVED
    assert state.state_hash() == before
    assert state.locate(their_monster(state)).zone is Zone.MZONE
    assert copy.state_hash() != before


@requires_official_db
def test_e_a_clone_answers_the_same_way(state):
    copy = state.clone()
    definition = synthetic(
        CardOperation.send_to_grave(PRIMARY),
        targets=single_target(Zone.MZONE, require=IsMonster()),
    )

    here = run_synthetic(state, definition, their_monster(state))
    there = run_synthetic(copy, definition, their_monster(copy))

    assert here.canonical_state() == there.canonical_state()
    assert state.state_hash() == copy.state_hash()


@requires_official_db
def test_e_the_opponents_hand_is_never_a_candidate(state):
    """가려진 존은 후보가 될 수 없고, 비어 있다고 "없다" 고 말하지 않는다."""
    state.draw(THEIRS, 2)
    found = TargetResolver(GameStateView.from_state(state, viewer=MINE)).candidates(
        TargetSpec.targeting(
            ChoiceSpec(
                source=CandidateSource(
                    zones=frozenset({Zone.HAND}), owner=PlayerRef.OPPONENT
                )
            )
        ),
        ResolutionContext(effect_ref=MST_EFFECT, controller=MINE).condition_context(),
    )

    assert found.eligible == ()
    assert found.unchecked  # 대신 "못 봤다" 가 남는다
    assert found.fully_checked is False


@requires_official_db
def test_e_no_hidden_identity_leaks_through_a_failure(state):
    """실패 메시지가 뒷면 카드의 정체를 말하지 않는다."""
    definition = synthetic(
        CardOperation.send_to_grave(PRIMARY),
        targets=single_target(Zone.SZONE, require=IsMonster()),
    )

    result = run_synthetic(state, definition, their_facedown_spell(state))

    assert str(DARK_HOLE) not in result.reason
    assert str(DARK_HOLE) not in str(result.to_dict())


# ======================================================================
# F. 중복 시스템이 생기지 않았는가 (§9)
# ======================================================================


def test_f_this_phase_added_no_engine_module():
    """
    §1 — 이번 단계는 검증이다. 엔진에 새 파일이 생기지 않았다.
    """
    expected = {
        "__init__.py",
        "definition.py",
        "delta.py",
        "executor.py",
        "journal.py",
        "library.py",
        "operation.py",
        "resolution.py",
        "semantics.py",
        "target.py",
        "targeting.py",
    }
    found = {
        path.name
        for path in pathlib.Path("engine/effect").glob("*.py")
    }

    assert found == expected


def test_f_there_is_exactly_one_executor_and_one_target_resolver():
    """§9 — 중복 시스템 금지. 이름이 정의된 곳이 하나뿐이다."""
    homes: dict[str, list[str]] = {}
    for path in pathlib.Path("engine").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in (
                "EffectExecutor",
                "TargetResolver",
                "CandidateResolver",
                "EventReader",
                "EventPipeline",
            ):
                homes.setdefault(node.name, []).append(str(path))

    for name, paths in homes.items():
        assert len(paths) == 1, f"{name} 이 여러 곳에 있습니다: {paths}"


def test_f_no_event_bus_was_introduced():
    """§9 — 새 ``EventBus`` 금지."""
    for path in pathlib.Path("engine").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        defined = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        }
        assert not any("Bus" in name for name in defined), path


def test_f_the_scenario_tests_build_no_engine_of_their_own():
    """
    이 파일이 실행기나 대상 계층을 흉내 내지 않는다 — 흉내 내면 검증이
    아니라 두 번째 구현이 된다.
    """
    tree = ast.parse(pathlib.Path(__file__).read_text("utf-8"))
    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }

    assert defined == set()
