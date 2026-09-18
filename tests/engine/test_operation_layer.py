"""
Phase 2-L — Operation 계층.

    EffectDefinition → Operation → GameState 변경 → StateDelta → ObservedEvent

세 가지 일이 실제로 판을 바꾼다.

=================  ==========================  ==============================
``DRAW``            ``state.draw()``            ``CardDrawn``
``CHANGE_LIFE``     ``player.change_life()``    ``LifeChanged``
``MOVE``            ``state.move()``            ``ZoneMoved(movement=MOVE)``
=================  ==========================  ==============================

**``MOVE`` 는 게임 의미가 아니다.** 파괴도 · 묘지로 보내기도 · 버리기도 ·
릴리스도 · 제외도 아니다. 그것을 구조로 보장하는 것이 이 파일의 절반이다 —
``reason_names`` 가 비어 있고, 실제 카드의 효과가 될 수 없다.
"""

import ast
import pathlib

import pytest

from engine.chain import Chain, ChainLink, ChainResolutionStatus, ChainResolver
from engine.condition import PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionError,
    EffectProvenance,
)
from engine.effect.delta import CardDrawn, LifeChanged, ZoneMoved
from engine.effect.executor import (
    SUPPORTED,
    EffectExecutor,
    EffectImplementationRegistry,
    destination_player,
)
from engine.effect.journal import EventJournal
from engine.effect.library import (
    POT_OF_GREED,
    RAIN_OF_MERCY,
    LibraryEntry,
    build_executor,
    definition_registry,
    entry_for,
)
from engine.effect.operation import (
    CARD_OPERATION_KINDS,
    MOVABLE_DESTINATIONS,
    REASON_NAMES,
    CardOperation,
    DrawOperation,
    LifeChangeOperation,
    MoveOperation,
    OperationKind,
)
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.target import TargetBinding, TargetRef, TargetSpec
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.trigger import TimingEvent, TimingPoint
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1

FEATHERMAN = 21844576  # 레벨 3 통상 몬스터 — 옮길 카드로 쓴다
LAB = 2511  # 라뷰린스 쿠클락 — 손으로 쓴 정의의 껍데기

PRIMARY = TargetRef("PRIMARY")


# ======================================================================
# 판 · 도구
# ======================================================================


def new_state(repository, deck: int = 8, hand: int = 3) -> GameState:
    game = GameState.create(
        repository, decks=([FEATHERMAN] * (deck + hand), [FEATHERMAN] * 5)
    )
    game.draw(MINE, hand)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def a_target() -> tuple[TargetBinding, ...]:
    """패 · 필드에서 한 장을 고르는 대상 규칙."""
    return (
        TargetBinding(
            PRIMARY,
            TargetSpec.targeting(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=frozenset({Zone.HAND, Zone.MZONE, Zone.GRAVE})
                    )
                )
            ),
        ),
    )


def hand_written(*operations, ordinal: int = 0) -> EffectDefinition:
    """
    **손으로 쓴** 정의. 실제 카드의 의미를 주장하지 않는다 — Operation 계층을
    시험하기 위한 껍데기이고, 출처가 ``hand_written`` 이라고 적혀 있다.
    """
    needs_target = any(operation.target_refs for operation in operations)
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        operations=tuple(operations),
        targets=a_target() if needs_target else (),
        provenance=EffectProvenance.hand_written(verified=True, note="Operation 시험"),
    )


def run(state: GameState, definition: EffectDefinition, *chosen: InstanceId):
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,))
    )
    selections = (
        (TargetSelection(PRIMARY, Selection(chosen=tuple(chosen))),) if chosen else ()
    )
    context = ResolutionContext(
        effect_ref=definition.effect_ref, controller=MINE, selections=selections
    )
    return executor.execute(state, definition, context)


# ======================================================================
# A. DRAW
# ======================================================================


@requires_official_db
def test_draw_moves_cards_from_the_deck_to_the_hand(state):
    deck_before, hand_before = len(state.player(MINE).deck), len(state.player(MINE).hand)
    top = [card.instance_id for card in state.player(MINE).deck[:2]]

    result = run(state, hand_written(DrawOperation(count=2)))

    assert result.status is ResolutionStatus.RESOLVED
    assert len(state.player(MINE).deck) == deck_before - 2
    assert len(state.player(MINE).hand) == hand_before + 2
    assert [c.instance_id for c in state.player(MINE).hand[-2:]] == top


@requires_official_db
def test_a_drawn_card_keeps_its_identity(state):
    card = state.player(MINE).deck[0]
    identity = (card.instance_id, card.card_id, card.owner, card.controller)

    run(state, hand_written(DrawOperation(count=1)))

    assert (card.instance_id, card.card_id, card.owner, card.controller) == identity
    assert state.locate(card.instance_id).zone is Zone.HAND


@requires_official_db
def test_draw_records_one_change_per_card(state):
    result = run(state, hand_written(DrawOperation(count=2)))

    assert len(result.deltas) == 2
    assert all(isinstance(delta, CardDrawn) for delta in result.deltas)
    assert all(delta.player == MINE for delta in result.deltas)


@requires_official_db
def test_a_short_deck_draws_nothing_at_all(repository):
    """
    ``GameState.draw`` 는 있는 만큼만 옮기는 primitive 다. 계획 단계가 **먼저**
    세지 않으면 "3장 드로우" 가 조용히 1장이 된다.
    """
    state = new_state(repository, deck=1, hand=0)
    before = state.state_hash()

    result = run(state, hand_written(DrawOperation(count=3)))

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert result.code is ValidationCode.INSUFFICIENT_DECK
    assert result.deltas == ()
    assert state.state_hash() == before


def test_a_draw_of_zero_cards_cannot_be_written():
    with pytest.raises(ValueError):
        DrawOperation(count=0)


# ======================================================================
# B. LIFE_CHANGE
# ======================================================================


@requires_official_db
def test_life_can_go_up(state):
    before = state.player(MINE).life_points

    result = run(state, hand_written(LifeChangeOperation(delta=1000)))

    assert result.status is ResolutionStatus.RESOLVED
    assert state.player(MINE).life_points == before + 1000


@requires_official_db
def test_life_can_go_down(state):
    before = state.player(MINE).life_points

    run(state, hand_written(LifeChangeOperation(delta=-500)))

    assert state.player(MINE).life_points == before - 500


@requires_official_db
def test_the_opponents_life_changes_when_the_operation_says_so(state):
    mine_before = state.player(MINE).life_points
    theirs_before = state.player(THEIRS).life_points

    run(state, hand_written(LifeChangeOperation(delta=-800, who=PlayerRef.OPPONENT)))

    assert state.player(MINE).life_points == mine_before
    assert state.player(THEIRS).life_points == theirs_before - 800


@requires_official_db
def test_a_life_change_records_what_actually_happened(state):
    """
    **요청한 값이 아니라 실제로 달라진 값**을 적는다. 0 아래로는 내려가지
    않으므로 둘이 다를 수 있다.
    """
    state.player(MINE).change_life(-7500)  # 남은 라이프 500
    result = run(state, hand_written(LifeChangeOperation(delta=-3000)))

    assert len(result.deltas) == 1
    delta = result.deltas[0]
    assert isinstance(delta, LifeChanged)
    assert (delta.before, delta.after) == (500, 0)
    assert delta.amount == -500  # 요청한 -3000 이 아니다


@requires_official_db
def test_a_change_that_changes_nothing_leaves_no_record(state):
    state.player(MINE).change_life(-8000)  # 이미 0
    result = run(state, hand_written(LifeChangeOperation(delta=-1000)))

    assert result.status is ResolutionStatus.RESOLVED
    assert result.deltas == ()


def test_a_life_change_of_zero_cannot_be_written():
    with pytest.raises(ValueError):
        LifeChangeOperation(delta=0)


# ======================================================================
# C. MOVE
# ======================================================================


@requires_official_db
@pytest.mark.parametrize(
    "destination", [Zone.GRAVE, Zone.DECK, Zone.REMOVED]
)
def test_a_card_moves_from_the_hand(state, destination):
    card = state.player(MINE).hand[0].instance_id

    result = run(state, hand_written(MoveOperation(destination, PRIMARY)), card)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(card).zone is destination
    assert card not in [c.instance_id for c in state.player(MINE).hand]


@requires_official_db
def test_a_card_moves_from_the_graveyard_back_to_the_hand(state):
    card = state.player(MINE).hand[0]
    state.move(card, Zone.GRAVE, to_player=MINE)
    assert state.locate(card.instance_id).zone is Zone.GRAVE

    run(state, hand_written(MoveOperation(Zone.HAND, PRIMARY)), card.instance_id)

    assert state.locate(card.instance_id).zone is Zone.HAND


@requires_official_db
def test_a_card_moves_from_the_field_to_the_graveyard(state):
    card = state.player(MINE).hand[0]
    state.move(card, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK)

    run(state, hand_written(MoveOperation(Zone.GRAVE, PRIMARY)), card.instance_id)

    assert state.locate(card.instance_id).zone is Zone.GRAVE
    assert len(state.player(MINE).monster_zone) == 0


@requires_official_db
def test_a_moved_card_keeps_its_identity_and_its_people(state):
    card = state.player(MINE).hand[0]
    identity = (card.instance_id, card.card_id, card.owner)

    run(state, hand_written(MoveOperation(Zone.GRAVE, PRIMARY)), card.instance_id)

    assert (card.instance_id, card.card_id, card.owner) == identity
    assert card.owner == MINE
    assert card.controller == MINE


@requires_official_db
def test_a_move_records_where_the_card_came_from(state):
    card = state.player(MINE).hand[0].instance_id

    result = run(state, hand_written(MoveOperation(Zone.GRAVE, PRIMARY)), card)

    assert len(result.deltas) == 1
    delta = result.deltas[0]
    assert isinstance(delta, ZoneMoved)
    assert (delta.from_zone, delta.to_zone) == (Zone.HAND, Zone.GRAVE)
    assert delta.instance == card
    assert delta.operation is OperationKind.MOVE


def test_a_move_cannot_aim_at_the_field():
    """칸 선택과 표시 형식은 소환 절차의 일이다 (Phase 2-I)."""
    for zone in (Zone.MZONE, Zone.EMZONE, Zone.SZONE, Zone.FZONE, Zone.EXTRA):
        with pytest.raises(ValueError):
            MoveOperation(zone, PRIMARY)

    assert MOVABLE_DESTINATIONS == frozenset(
        {Zone.GRAVE, Zone.REMOVED, Zone.HAND, Zone.DECK}
    )


def test_a_move_must_say_which_card():
    with pytest.raises(TypeError):
        MoveOperation(Zone.GRAVE, "PRIMARY")


@requires_official_db
def test_a_move_with_no_chosen_card_changes_nothing(state):
    before = state.state_hash()

    result = run(state, hand_written(MoveOperation(Zone.GRAVE, PRIMARY)))

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_a_move_of_a_card_that_is_not_here_changes_nothing(state):
    before = state.state_hash()

    result = run(
        state, hand_written(MoveOperation(Zone.GRAVE, PRIMARY)), InstanceId(9999)
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_FOUND
    assert state.state_hash() == before


# ======================================================================
# D. 의미의 분리
# ======================================================================


def test_a_move_claims_no_reason_at_all():
    """
    **이것이 분리의 핵심이다.** ``REASON_*`` 을 하나도 주장하지 않으므로
    트리거 계층이 이것을 "효과로 묘지에 갔다" 로 읽을 수 없다.
    """
    assert REASON_NAMES[OperationKind.MOVE] == ()
    assert MoveOperation(Zone.GRAVE, PRIMARY).reason_names == ()

    for kind in (
        OperationKind.DESTROY,
        OperationKind.SEND_TO_GRAVE,
        OperationKind.DISCARD,
        OperationKind.RELEASE,
        OperationKind.BANISH,
        OperationKind.RETURN_TO_HAND,
    ):
        assert REASON_NAMES[kind] != ()


def test_a_move_is_not_one_of_the_meanings():
    assert OperationKind.MOVE not in CARD_OPERATION_KINDS
    move = MoveOperation(Zone.GRAVE, PRIMARY)

    for kind in (
        OperationKind.DESTROY,
        OperationKind.SEND_TO_GRAVE,
        OperationKind.DISCARD,
        OperationKind.RELEASE,
        OperationKind.BANISH,
    ):
        assert move.kind is not kind


def test_the_same_destination_is_not_the_same_event():
    """
    묘지로 가는 길이 다섯이다. 목적지만 적으면 다섯이 하나로 뭉개진다
    (ADR-002).
    """
    sent = CardOperation.send_to_grave(PRIMARY)
    discarded = CardOperation.discard(PRIMARY)
    released = CardOperation.release(PRIMARY)
    moved = MoveOperation(Zone.GRAVE, PRIMARY)

    kinds = {sent.kind, discarded.kind, released.kind, moved.kind}
    assert len(kinds) == 4

    reasons = {sent.reason_names, discarded.reason_names, released.reason_names}
    assert len(reasons) == 3


def test_a_move_has_no_place_in_the_destination_table():
    """
    의미가 목적지를 정하는 표에 ``MOVE`` 가 없다. 의미가 없으므로 "이 일은
    주인에게 간다" 는 규칙 자체가 없고, 조작이 직접 말한다.
    """
    with pytest.raises(KeyError):
        destination_player(OperationKind.MOVE, object())


def test_destroy_is_still_not_executable():
    """
    파괴는 여전히 지원하지 않는다. 목적지가 묘지라는 이유로 ``MOVE`` 를
    파괴라고 부르지 않는다.
    """
    assert OperationKind.DESTROY not in SUPPORTED
    assert OperationKind.MOVE in SUPPORTED


def test_a_real_card_effect_can_never_be_a_bare_move():
    """
    **목록이 구조로 막는다.** 실제 카드의 효과라면 무슨 일인지 말해야 한다.
    """
    with pytest.raises(EffectDefinitionError):
        LibraryEntry(
            definition=EffectDefinition(
                effect_ref=EffectRef(LAB, 0),
                source_card_id=LAB,
                operations=(MoveOperation(Zone.GRAVE, PRIMARY),),
                targets=a_target(),
                provenance=EffectProvenance.official_lua("스크립트를 읽었다"),
            ),
            lua_file="c2511.lua",
            lua_excerpt="Duel.SendtoGrave(...)",
            executable=True,
        )


def test_no_entry_in_the_library_uses_a_bare_move():
    from engine.effect.library import EFFECT_LIBRARY

    for entry in EFFECT_LIBRARY:
        kinds = {operation.kind for operation in entry.definition.operations}
        assert OperationKind.MOVE not in kinds, entry.effect_ref


# ======================================================================
# E. EffectExecutor 연결 · 실제 카드
# ======================================================================


@requires_official_db
def test_rain_of_mercy_gives_both_players_a_thousand(repository):
    """
    실제 카드다 — ``c66719324.lua`` 의 ``Duel.Recover(tp,1000)`` 두 줄.
    """
    state = new_state(repository)
    before = [state.player(p).life_points for p in (MINE, THEIRS)]

    result = build_executor().execute(
        state,
        entry_for(EffectRef(RAIN_OF_MERCY, 0)).definition,
        ResolutionContext(effect_ref=EffectRef(RAIN_OF_MERCY, 0), controller=MINE),
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert [state.player(p).life_points for p in (MINE, THEIRS)] == [
        value + 1000 for value in before
    ]


@requires_official_db
def test_rain_of_mercy_is_written_as_two_separate_operations(repository):
    """
    한 줄로 합치면 "누가 얼마를 회복했는가" 가 뭉개진다.
    """
    definition = entry_for(EffectRef(RAIN_OF_MERCY, 0)).definition

    assert len(definition.operations) == 2
    assert {op.who for op in definition.operations} == {
        PlayerRef.CONTROLLER,
        PlayerRef.OPPONENT,
    }
    assert all(op.delta == 1000 for op in definition.operations)


@requires_official_db
def test_the_library_still_refuses_what_it_cannot_run(repository):
    """Phase 2-K 의 세 가지 상태가 그대로다."""
    from engine.effect.definition import ExecutionAvailability
    from engine.effect.library import DARK_HOLE, availability

    assert availability(EffectRef(POT_OF_GREED, 0)) is ExecutionAvailability.EXECUTABLE
    assert availability(EffectRef(RAIN_OF_MERCY, 0)) is (
        ExecutionAvailability.EXECUTABLE
    )
    assert availability(EffectRef(DARK_HOLE, 0)) is (
        ExecutionAvailability.NO_IMPLEMENTATION
    )


@requires_official_db
def test_an_effect_with_no_implementation_runs_no_operation(state):
    """구현이 등록되어 있지 않으면 일이 하나도 수행되지 않는다."""
    definition = hand_written(LifeChangeOperation(delta=-1000))
    before = state.state_hash()

    result = EffectExecutor().execute(
        state,
        definition,
        ResolutionContext(effect_ref=definition.effect_ref, controller=MINE),
    )

    assert result.status is not ResolutionStatus.RESOLVED
    assert state.state_hash() == before


@requires_official_db
def test_a_text_derived_effect_runs_no_operation(state):
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 1),
        source_card_id=LAB,
        operations=(LifeChangeOperation(delta=-1000),),
        provenance=EffectProvenance.text_derived("텍스트에서 유추"),
    )
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,))
    )
    before = state.state_hash()

    result = executor.execute(
        state,
        definition,
        ResolutionContext(effect_ref=definition.effect_ref, controller=MINE),
    )

    assert result.status is ResolutionStatus.FORBIDDEN
    assert state.state_hash() == before


@requires_official_db
def test_several_operations_run_in_order(state):
    """
    순서가 곧 사실이다. 먼저 뽑고 나서 버리는 것과 그 반대는 다른 결과다.
    """
    card = state.player(MINE).hand[0].instance_id
    definition = hand_written(
        DrawOperation(count=1),
        MoveOperation(Zone.GRAVE, PRIMARY),
        LifeChangeOperation(delta=-100),
    )

    result = run(state, definition, card)

    assert result.status is ResolutionStatus.RESOLVED
    assert [type(delta).__name__ for delta in result.deltas] == [
        "CardDrawn",
        "ZoneMoved",
        "LifeChanged",
    ]


@requires_official_db
def test_one_failing_operation_stops_the_whole_effect(repository):
    """
    계획이 실패하면 적용은 **시작도 하지 않는다.** 라이프는 그대로다.
    """
    state = new_state(repository, deck=0, hand=2)
    card = state.player(MINE).hand[0].instance_id
    before = state.state_hash()

    result = run(
        state,
        hand_written(
            LifeChangeOperation(delta=-100),
            DrawOperation(count=3),  # 덱이 비었다
            MoveOperation(Zone.GRAVE, PRIMARY),
        ),
        card,
    )

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert result.deltas == ()
    assert state.state_hash() == before


# ======================================================================
# F. EventPipeline 연결
# ======================================================================


@requires_official_db
def test_every_operation_kind_reaches_the_event_pipeline(state):
    card = state.player(MINE).hand[0].instance_id
    result = run(
        state,
        hand_written(
            DrawOperation(count=1),
            MoveOperation(Zone.GRAVE, PRIMARY),
            LifeChangeOperation(delta=-100),
        ),
        card,
    )

    events = EventReader(GameStateView.from_state(state, viewer=MINE)).read(
        result, actor=MINE
    )

    assert [event.point for event in events] == [
        TimingPoint.CARD_DRAWN,
        TimingPoint.CARD_MOVED,
        TimingPoint.LIFE_CHANGED,
    ]
    assert [event.context.sequence for event in events] == [0, 1, 2]


@requires_official_db
def test_the_move_event_carries_no_reason_into_the_trigger_layer(state):
    card = state.player(MINE).hand[0].instance_id
    result = run(state, hand_written(MoveOperation(Zone.GRAVE, PRIMARY)), card)

    event = TimingEvent.from_delta(result.deltas[0])

    assert event.point is TimingPoint.CARD_MOVED
    assert event.operation is OperationKind.MOVE
    assert event.delta.reason_names == ()


@requires_official_db
def test_reading_the_events_changes_nothing(state):
    result = run(state, hand_written(LifeChangeOperation(delta=-100)))
    after = state.state_hash()

    EventReader(GameStateView.from_state(state, viewer=MINE)).read(result, actor=MINE)

    assert state.state_hash() == after


# ======================================================================
# G. 체인 경계
# ======================================================================


@requires_official_db
def test_a_chain_link_runs_the_operations(repository):
    state = new_state(repository)
    state.move(
        state.player(MINE).hand[0], Zone.SZONE, to_player=MINE,
        position=Position.FACEUP,
    )
    source = state.player(MINE).spell_zone[0].instance_id
    ref = EffectRef(RAIN_OF_MERCY, 0)
    journal = EventJournal()
    before = state.player(MINE).life_points

    resolution = ChainResolver(
        build_executor(journal), definition_registry()
    ).resolve_top(
        state,
        Chain(links=(ChainLink(sequence=0, actor=MINE, effect_ref=ref, source=source),)),
    )

    assert resolution.status is ChainResolutionStatus.RESOLVED
    assert state.player(MINE).life_points == before + 1000
    assert len(journal) == 1


def test_the_chain_layer_still_runs_no_operation_itself():
    tree = ast.parse(pathlib.Path("engine/chain.py").read_text("utf-8"))
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    for forbidden in ("move", "draw", "change_life", "create_instance"):
        assert forbidden not in attributes


def test_the_operation_layer_knows_nothing_above_it():
    tree = ast.parse(pathlib.Path("engine/effect/operation.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    for forbidden in (
        "engine.chain",
        "engine.trigger",
        "engine.event_pipeline",
        "engine.state.game_state",
        "engine.effect.executor",
    ):
        assert forbidden not in imported


def test_operations_do_not_touch_the_board_by_themselves():
    """
    ``operation.execute(state)`` 를 만들지 않았다. 일은 **의미**이고, 그것을
    상태 조작으로 옮기는 것은 실행기 하나의 책임이다.
    """
    for operation in (
        DrawOperation(count=1),
        LifeChangeOperation(delta=1),
        MoveOperation(Zone.GRAVE, PRIMARY),
        CardOperation.send_to_grave(PRIMARY),
    ):
        assert not hasattr(operation, "execute")
        assert not hasattr(operation, "apply")


# ======================================================================
# H. 결정론 · 관측 경계
# ======================================================================


@requires_official_db
def test_the_same_board_and_operations_give_the_same_board(repository):
    first, second = new_state(repository), new_state(repository)
    assert first.state_hash() == second.state_hash()

    for board in (first, second):
        card = board.player(MINE).hand[0].instance_id
        run(
            board,
            hand_written(
                DrawOperation(count=1),
                MoveOperation(Zone.GRAVE, PRIMARY),
                LifeChangeOperation(delta=-300),
            ),
            card,
        )

    assert first.state_hash() == second.state_hash()


@requires_official_db
def test_a_clone_runs_the_operations_on_its_own(state):
    copy = state.clone()
    before = state.state_hash()
    card = copy.player(MINE).hand[0].instance_id

    run(copy, hand_written(MoveOperation(Zone.GRAVE, PRIMARY)), card)

    assert state.state_hash() == before
    assert len(state.player(MINE).grave) == 0
    assert len(copy.player(MINE).grave) == 1


@requires_official_db
def test_a_move_lands_in_a_deterministic_place(repository):
    """묘지는 순서 존이라 맨 뒤에 쌓인다. 자리를 고르지 않는다."""
    first, second = new_state(repository), new_state(repository)

    for board in (first, second):
        for index in range(2):
            card = board.player(MINE).hand[0].instance_id
            run(
                board,
                hand_written(MoveOperation(Zone.GRAVE, PRIMARY), ordinal=index),
                card,
            )

    assert [c.instance_id for c in first.player(MINE).grave] == [
        c.instance_id for c in second.player(MINE).grave
    ]


@requires_official_db
def test_the_operation_layer_does_not_open_a_window_into_hidden_cards(state):
    """
    실행기는 실제 ``GameState`` 를 쓰지만, 그 결과가 관측 경계를 넘겨주지
    않는다. 변화 기록에는 상대의 가려진 카드 정체가 들어가지 않는다.
    """
    result = run(state, hand_written(DrawOperation(count=1)))
    text = str([delta.to_dict() for delta in result.deltas])

    for hidden in state.player(THEIRS).hand:
        assert str(hidden.card_id) not in text
