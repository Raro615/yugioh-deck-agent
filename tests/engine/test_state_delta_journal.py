"""
Phase 2-D-3 — StateDelta + EventJournal 최소 골격.

세 가지를 본다.

1. **기록이 실제 변화와 일치하는가.** Delta 가 판과 다른 말을 하면 그
   기록은 없느니만 못하다.
2. **실패했을 때 기록도 없는가.** 판이 그대로면 역사도 그대로여야 한다.
3. **같은 입력이 같은 기록을 내는가.** 무작위 · 시각 · 객체 주소가 새어
   들어가면 재생도 비교도 불가능해진다.

되돌리기(rollback)와 재생(replay)은 여기 없다. 그것들이 나중에 필요로 할
정보가 지금 빠짐없이 남는지만 본다.
"""

import json

import pytest

from engine.condition import Always, ConditionResult, PlayerRef, UnimplementedRule
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.effect import (
    PRIMARY_TARGET,
    AppliedOperation,
    CardDrawn,
    CardMovement,
    CardOperation,
    UnimplementedOperation,
    DrawOperation,
    EffectDefinition,
    EffectEvent,
    EffectExecutor,
    EffectImplementationRegistry,
    EffectProvenance,
    EffectResult,
    EventJournal,
    JournalError,
    LifeChangeOperation,
    LifeChanged,
    OperationKind,
    ResolutionContext,
    ResolutionStatus,
    StateDelta,
    TargetBinding,
    TargetSelection,
    TargetSpec,
    ZoneMoved,
)
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Position, Zone

KUKLOK = 2511
MINE, THEIRS = 0, 1


# ======================================================================
# 판 · 정의 · 실행
# ======================================================================


def new_state() -> GameState:
    game = GameState.create(decks=(range(1000, 1030), range(2000, 2030)))
    game.draw(MINE, 5)
    game.draw(THEIRS, 5)
    for player in (MINE, THEIRS):
        game.move(
            game.player(player).hand[0],
            Zone.MZONE,
            position=Position.FACEUP_ATTACK,
        )
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


@pytest.fixture
def journal() -> EventJournal:
    return EventJournal()


def anywhere(maximum: int = 3) -> ChoiceSpec:
    """
    ``maximum`` 은 Phase 2-N 때문이다 — 대상 계층이 생긴 뒤로 "1장" 이라고
    적어 놓고 여러 장을 고르면 거절된다. 이 테스트들은 실제로 여러 장을
    옮기므로 명세도 그렇게 말해야 한다.
    """
    return ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.MZONE, Zone.EMZONE, Zone.HAND}), owner=None
        ),
        maximum=maximum,
    )


def make_definition(*operations, activation=None, provenance=None, ordinal=0):
    needs_target = any(operation.target_refs for operation in operations)
    return EffectDefinition(
        effect_ref=EffectRef(KUKLOK, ordinal),
        source_card_id=KUKLOK,
        operations=tuple(operations),
        targets=(
            TargetBinding.single(TargetSpec.targeting(anywhere()))
            if needs_target
            else ()
        ),
        activation=activation,
        provenance=provenance or EffectProvenance.official_lua(),
    )


def make_context(definition, *chosen, controller=MINE, source=None):
    selections = (
        (TargetSelection(PRIMARY_TARGET, Selection.of(*chosen)),) if chosen else ()
    )
    return ResolutionContext(
        definition.effect_ref,
        controller=controller,
        source=source,
        selections=selections,
    )


def run(state, definition, context, journal=None) -> EffectResult:
    executor = EffectExecutor(
        EffectImplementationRegistry([definition.effect_ref]), journal=journal
    )
    return executor.execute(state, definition, context)


def my_monster(state) -> InstanceId:
    return state.player(MINE).monster_zone[0].instance_id


def steal_to_field(state):
    """상대 카드를 **내가 컨트롤하는** 몬스터 존에 놓는다. 주인은 그대로다."""
    card = state.player(THEIRS).hand[0]
    state.move(card, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK)
    assert card.owner == THEIRS and card.controller == MINE
    return card


# ======================================================================
# 1~5. StateDelta 자체
# ======================================================================


def test_a_delta_is_immutable():
    delta = ZoneMoved(
        OperationKind.BANISH, InstanceId(7), MINE, Zone.MZONE, MINE, Zone.REMOVED
    )
    with pytest.raises(Exception):
        delta.movement = OperationKind.DESTROY
    with pytest.raises(Exception):
        delta.card = InstanceId(8)


def test_a_delta_cannot_change_the_board():
    """
    **Delta 에는 ``apply`` 도 ``undo`` 도 없다.** 기록이 판을 바꿀 수 있게
    되는 순간 "무슨 일이 있었는가" 와 "무슨 일을 하겠다" 가 섞인다.
    """
    for delta in (
        ZoneMoved(
            OperationKind.RELEASE, InstanceId(1), MINE, Zone.MZONE, MINE, Zone.GRAVE
        ),
        CardDrawn(MINE, InstanceId(2)),
        LifeChanged(MINE, 8000, 7000),
    ):
        assert isinstance(delta, StateDelta)
        for forbidden in ("apply", "undo", "revert", "rollback"):
            assert not hasattr(delta, forbidden), forbidden


def test_deltas_compare_by_value():
    first = ZoneMoved(
        OperationKind.BANISH, InstanceId(7), MINE, Zone.MZONE, MINE, Zone.REMOVED
    )
    same = ZoneMoved(
        OperationKind.BANISH, InstanceId(7), MINE, Zone.MZONE, MINE, Zone.REMOVED
    )
    other_operation = ZoneMoved(
        OperationKind.SEND_TO_GRAVE, InstanceId(7), MINE, Zone.MZONE, MINE, Zone.REMOVED
    )
    assert first == same
    assert first != other_operation
    assert LifeChanged(MINE, 8000, 7000) != LifeChanged(THEIRS, 8000, 7000)
    assert CardDrawn(MINE, InstanceId(2)) == CardDrawn(MINE, InstanceId(2))


def test_a_delta_serializes_to_plain_data():
    delta = ZoneMoved(
        OperationKind.DISCARD, InstanceId(4), MINE, Zone.HAND, THEIRS, Zone.GRAVE
    )
    data = delta.to_dict()
    assert data == {
        "kind": "zone_moved",
        "operation": "discard",
        "reasons": ["DISCARD", "EFFECT"],
        "instance": 4,
        "from": {"player": 0, "zone": "HAND"},
        "to": {"player": 1, "zone": "GRAVE"},
    }
    # 실제로 JSON 이 되어야 한다 — 객체가 섞여 있으면 여기서 터진다.
    json.dumps(data, ensure_ascii=False)


def test_a_canonical_state_carries_no_object_identity():
    """주소도, 파이썬 기본 ``hash()`` 도, ``repr`` 도 들어가지 않는다."""
    delta = CardDrawn(MINE, InstanceId(11))
    canonical = delta.canonical_state()
    assert canonical == ("card_drawn", 0, 11)
    text = json.dumps(canonical)
    assert "0x" not in text and "object at" not in text
    # 프로세스 안에서 몇 번을 물어도 같다.
    assert delta.canonical_state() == CardDrawn(MINE, InstanceId(11)).canonical_state()


def test_a_draw_can_only_be_written_one_way():
    """
    같은 사실을 두 모양으로 적을 수 있으면 세는 쪽이 반드시 두 번 센다.
    """
    with pytest.raises(ValueError):
        ZoneMoved(OperationKind.DRAW, InstanceId(1), MINE, Zone.DECK, MINE, Zone.HAND)
    with pytest.raises(ValueError):
        ZoneMoved(
            OperationKind.CHANGE_LIFE, InstanceId(1), MINE, Zone.MZONE, MINE, Zone.GRAVE
        )


def test_every_card_movement_answers_the_same_questions():
    """
    트리거 계층이 "이번에 움직인 카드" 를 물을 때 종류를 하나하나 세지
    않아도 된다.
    """
    moves = [
        ZoneMoved(
            OperationKind.RELEASE, InstanceId(1), MINE, Zone.MZONE, THEIRS, Zone.GRAVE
        ),
        CardDrawn(THEIRS, InstanceId(2)),
    ]
    for move in moves:
        assert isinstance(move, CardMovement)
        assert isinstance(move.instance, InstanceId)
        assert isinstance(move.operation, OperationKind)
        assert isinstance(move.from_zone, Zone) and isinstance(move.to_zone, Zone)
        assert move.from_player in (0, 1) and move.to_player in (0, 1)
    assert moves[0].changed_side is True
    assert moves[1].changed_side is False
    assert not isinstance(LifeChanged(MINE, 8000, 7000), CardMovement)


# ======================================================================
# 6~11. Zone mutation → Delta
# ======================================================================


@pytest.mark.parametrize(
    "factory, kind, destination",
    [
        (CardOperation.send_to_grave, OperationKind.SEND_TO_GRAVE, Zone.GRAVE),
        (CardOperation.banish, OperationKind.BANISH, Zone.REMOVED),
        (CardOperation.return_to_hand, OperationKind.RETURN_TO_HAND, Zone.HAND),
        (CardOperation.return_to_deck, OperationKind.RETURN_TO_DECK, Zone.DECK),
        (CardOperation.release, OperationKind.RELEASE, Zone.GRAVE),
    ],
)
def test_a_card_move_produces_a_matching_delta(state, factory, kind, destination):
    definition = make_definition(factory(PRIMARY_TARGET))
    target = my_monster(state)

    result = run(state, definition, make_context(definition, target))

    assert result.status is ResolutionStatus.RESOLVED
    assert len(result.deltas) == 1
    delta = result.deltas[0]
    assert isinstance(delta, ZoneMoved)
    assert delta.operation is kind
    assert delta.instance == target
    assert delta.from_zone is Zone.MZONE
    assert delta.from_player == MINE
    assert delta.to_zone is destination
    assert delta.to_player == MINE
    # 기록이 실제 판과 일치해야 한다.
    card = state.find_instance(target)
    assert card.zone is delta.to_zone
    assert card.controller == delta.to_player


def test_discard_records_the_hand_as_the_source(state):
    definition = make_definition(CardOperation.discard(PRIMARY_TARGET))
    target = state.player(MINE).hand[0].instance_id

    result = run(state, definition, make_context(definition, target))

    delta = result.deltas[0]
    assert delta.operation is OperationKind.DISCARD
    assert delta.from_zone is Zone.HAND
    assert delta.to_zone is Zone.GRAVE
    assert delta.reason_names == ("DISCARD", "EFFECT")


def test_release_and_send_to_grave_end_alike_but_record_differently(state):
    """
    **Delta 가 목적지만 적으면 그 둘은 영영 구분되지 않는다** (ADR-002).
    """
    sent = my_monster(state)
    released = state.player(THEIRS).monster_zone[0].instance_id

    send = make_definition(CardOperation.send_to_grave(PRIMARY_TARGET))
    release = make_definition(CardOperation.release(PRIMARY_TARGET), ordinal=1)

    first = run(state, send, make_context(send, sent))
    second = run(state, release, make_context(release, released))

    a, b = first.deltas[0], second.deltas[0]
    assert a.to_zone is b.to_zone is Zone.GRAVE
    assert a.operation is not b.operation
    assert a.reason_names != b.reason_names
    assert a.canonical_state()[1] == "send_to_grave"
    assert b.canonical_state()[1] == "release"


def test_moving_several_cards_produces_one_delta_each(state):
    """일 하나가 변화 여럿을 낳는다. ``AppliedOperation`` 은 하나다."""
    definition = make_definition(CardOperation.banish(PRIMARY_TARGET))
    first = my_monster(state)
    second = state.player(MINE).hand[0].instance_id
    context = ResolutionContext(
        definition.effect_ref,
        controller=MINE,
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(first, second)),),
    )

    result = run(state, definition, context)

    assert len(result.applied) == 1
    assert len(result.deltas) == 2
    assert [delta.instance for delta in result.deltas] == [first, second]
    assert [delta.from_zone for delta in result.deltas] == [Zone.MZONE, Zone.HAND]


# ======================================================================
# 12. Life
# ======================================================================


def test_a_life_change_records_before_and_after(state):
    definition = make_definition(LifeChangeOperation(-1200))
    before = state.player(MINE).life_points

    result = run(state, definition, make_context(definition))

    assert len(result.deltas) == 1
    delta = result.deltas[0]
    assert isinstance(delta, LifeChanged)
    assert delta.player == MINE
    assert delta.before == before
    assert delta.after == before - 1200
    assert delta.amount == -1200
    assert delta.is_loss is True
    assert state.player(MINE).life_points == delta.after


def test_a_life_change_records_what_actually_happened_not_what_was_asked(state):
    """
    ``change_life`` 는 0 아래로 내려가지 않는다. 요청한 값은
    ``AppliedOperation.amount`` 에, **실제로 달라진 값**은 Delta 에 남는다.
    둘의 차이가 곧 "얼마가 막혔는가" 다.
    """
    state.player(MINE).life_points = 1000
    definition = make_definition(LifeChangeOperation(-3000))

    result = run(state, definition, make_context(definition))

    assert result.applied[0].amount == -3000  # 요청한 값
    assert result.deltas[0].amount == -1000  # 실제 변화
    assert result.deltas[0].after == 0
    assert state.player(MINE).life_points == 0


def test_a_life_change_that_changes_nothing_records_nothing(state):
    """이미 0 인 라이프를 더 깎아도 달라진 것이 없으면 변화도 없다."""
    state.player(MINE).life_points = 0
    definition = make_definition(LifeChangeOperation(-500))

    result = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.RESOLVED
    assert result.deltas == ()
    assert result.changed_state is False


# ======================================================================
# 13~14. Draw
# ======================================================================


def test_a_draw_produces_one_delta_per_card(state):
    definition = make_definition(DrawOperation(3))
    top_three = [card.instance_id for card in state.player(MINE).deck[:3]]

    result = run(state, definition, make_context(definition))

    assert len(result.deltas) == 3
    assert all(isinstance(delta, CardDrawn) for delta in result.deltas)
    assert [delta.instance for delta in result.deltas] == top_three
    for delta in result.deltas:
        assert delta.player == MINE
        assert delta.operation is OperationKind.DRAW
        assert delta.from_zone is Zone.DECK and delta.to_zone is Zone.HAND
        assert state.find_instance(delta.instance).zone is Zone.HAND


def test_a_draw_for_the_opponent_records_the_opponent(state):
    definition = make_definition(DrawOperation(1, who=PlayerRef.OPPONENT))
    result = run(state, definition, make_context(definition, controller=MINE))
    assert result.deltas[0].player == THEIRS


def test_a_short_draw_produces_no_delta_at_all(state, journal):
    deck = state.player(MINE).deck
    while len(deck) > 1:
        state.move(deck[0], Zone.REMOVED, to_player=MINE)
    definition = make_definition(DrawOperation(3))
    before = state.state_hash()

    result = run(state, definition, make_context(definition), journal)

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert result.code is ValidationCode.INSUFFICIENT_DECK
    assert result.deltas == ()
    assert state.state_hash() == before
    assert len(journal) == 0


# ======================================================================
# 15~16. EffectResult
# ======================================================================


def test_a_success_carries_both_what_was_done_and_what_changed(state):
    definition = make_definition(
        CardOperation.send_to_grave(PRIMARY_TARGET),
        DrawOperation(2),
        LifeChangeOperation(-300),
    )

    result = run(state, definition, make_context(definition, my_monster(state)))

    assert result.resolved is True
    assert result.changed_state is True
    assert [applied.kind for applied in result.applied] == [
        OperationKind.SEND_TO_GRAVE,
        OperationKind.DRAW,
        OperationKind.CHANGE_LIFE,
    ]
    # 일 3개, 변화 4개 (묘지 1 + 드로우 2 + 라이프 1)
    assert len(result.deltas) == 4
    assert [type(delta).__name__ for delta in result.deltas] == [
        "ZoneMoved",
        "CardDrawn",
        "CardDrawn",
        "LifeChanged",
    ]


def test_an_effect_that_does_nothing_succeeds_and_changes_nothing(state, journal):
    """
    하는 일이 적혀 있지 않은 정의. **성공했지만 판은 그대로다.**
    ``resolved`` 와 ``changed_state`` 가 다른 질문인 이유가 이것이다.
    """
    definition = make_definition()
    before = state.state_hash()

    result = run(state, definition, make_context(definition), journal)

    assert result.resolved is True
    assert result.changed_state is False
    assert result.deltas == ()
    assert state.state_hash() == before
    assert len(journal) == 0


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(
            lambda: (
                make_definition(
                    CardOperation.banish(PRIMARY_TARGET),
                    provenance=EffectProvenance.text_derived(),
                ),
                "chosen",
            ),
            id="forbidden-source",
        ),
        pytest.param(
            # 파괴는 Phase 2-M 부터 실행된다. "실행기가 못 하는 일" 의
            # 표본만 바뀌고, 이 표본이 지키는 사실은 그대로다.
            lambda: (make_definition(UnimplementedOperation("특수 소환")), "chosen"),
            id="unsupported",
        ),
        pytest.param(
            lambda: (
                make_definition(
                    CardOperation.banish(PRIMARY_TARGET),
                    activation=Always(ConditionResult.FALSE),
                ),
                "chosen",
            ),
            id="condition-false",
        ),
        pytest.param(
            lambda: (
                make_definition(
                    CardOperation.banish(PRIMARY_TARGET),
                    activation=UnimplementedRule("아직 없는 규칙"),
                ),
                "chosen",
            ),
            id="condition-unknown",
        ),
        pytest.param(
            lambda: (make_definition(CardOperation.banish(PRIMARY_TARGET)), "missing"),
            id="invalid-target",
        ),
        pytest.param(
            lambda: (make_definition(DrawOperation(999)), "none"),
            id="insufficient-cards",
        ),
    ],
)
def test_every_failure_carries_no_delta_and_leaves_no_trace(state, journal, build):
    definition, target_mode = build()
    if target_mode == "chosen":
        context = make_context(definition, my_monster(state))
    elif target_mode == "missing":
        context = make_context(definition, InstanceId(9999))
    else:
        context = make_context(definition)

    before_state = state.state_hash()
    before_journal = journal.canonical_state()

    result = run(state, definition, context, journal)

    assert result.status is not ResolutionStatus.RESOLVED
    assert result.deltas == ()
    assert result.changed_state is False
    assert state.state_hash() == before_state
    assert journal.canonical_state() == before_journal
    assert len(journal) == 0


# ======================================================================
# 17~21. EventJournal
# ======================================================================


def test_a_success_appends_one_event(state, journal):
    definition = make_definition(
        CardOperation.banish(PRIMARY_TARGET), DrawOperation(1)
    )
    source = InstanceId(3)
    target = my_monster(state)

    result = run(
        state, definition, make_context(definition, target, source=source), journal
    )

    assert len(journal) == 1
    event = journal[0]
    assert event.sequence == 0
    assert event.effect_ref == definition.effect_ref
    assert event.actor == MINE
    assert event.source == source
    assert event.applied == result.applied
    assert event.deltas == result.deltas
    assert event.changed_state is True
    assert event.instances == (target,) + tuple(
        delta.instance for delta in result.deltas[1:]
    )


def test_an_event_is_immutable():
    event = EffectEvent(0, EffectRef(KUKLOK, 0), MINE)
    with pytest.raises(Exception):
        event.sequence = 5
    with pytest.raises(Exception):
        event.actor = THEIRS
    with pytest.raises(TypeError):
        EffectEvent(0, EffectRef(KUKLOK, 0), MINE, applied=[])


def test_events_keep_the_order_they_happened(state, journal):
    banish = make_definition(CardOperation.banish(PRIMARY_TARGET), ordinal=0)
    draw = make_definition(DrawOperation(1), ordinal=1)
    life = make_definition(LifeChangeOperation(-100), ordinal=2)

    run(state, banish, make_context(banish, my_monster(state)), journal)
    run(state, draw, make_context(draw), journal)
    run(state, life, make_context(life), journal)

    assert [event.sequence for event in journal] == [0, 1, 2]
    assert [event.effect_ref.ordinal for event in journal] == [0, 1, 2]
    assert len(journal.deltas()) == 3


def test_an_event_always_uses_the_effect_ref_never_the_lua_variable_name(state, journal):
    """
    ``EffectSpec.index`` 는 Lua 변수명(``"e1"``)이고 한 카드 안에서 중복된다.
    실행 identity 로 쓰지 않는다는 Phase 2-D-1 의 원칙 그대로다.
    """
    definition = make_definition(DrawOperation(1), ordinal=2)
    run(state, definition, make_context(definition), journal)

    event = journal[0]
    assert event.effect_ref == EffectRef(KUKLOK, 2)
    text = json.dumps(journal.to_dict(), ensure_ascii=False)
    assert "e1" not in text
    assert event.to_dict()["effect_ref"] == {"card_id": KUKLOK, "ordinal": 2}


def test_the_journal_state_is_deterministic(state, journal):
    definition = make_definition(
        CardOperation.send_to_grave(PRIMARY_TARGET), DrawOperation(1)
    )
    run(state, definition, make_context(definition, my_monster(state)), journal)

    twin = new_state()
    twin_journal = EventJournal()
    run(
        twin,
        definition,
        make_context(definition, my_monster(twin)),
        twin_journal,
    )

    assert journal.canonical_state() == twin_journal.canonical_state()
    assert journal.journal_hash() == twin_journal.journal_hash()
    assert journal == twin_journal
    text = json.dumps(journal.canonical_state())
    assert "0x" not in text and "object at" not in text


def test_the_journal_only_grows(state, journal):
    """지우기 · 고치기 · 바꿔치기는 **없다.**"""
    for forbidden in ("delete", "remove", "pop", "clear", "edit", "replace", "insert"):
        assert not hasattr(journal, forbidden), forbidden

    definition = make_definition(DrawOperation(1))
    run(state, definition, make_context(definition), journal)

    # 밖으로 나가는 것은 tuple 이라 밖에서 늘릴 수 없다.
    events = journal.events
    assert isinstance(events, tuple)
    assert len(journal) == 1

    # 번호를 건너뛰거나 되돌리면 거부한다.
    with pytest.raises(JournalError):
        journal.append(EffectEvent(5, EffectRef(KUKLOK, 0), MINE))
    with pytest.raises(JournalError):
        journal.append(EffectEvent(0, EffectRef(KUKLOK, 0), MINE))
    assert len(journal) == 1


def test_a_journal_is_optional_and_never_changes_the_outcome(state):
    """
    기록이 판정에 끼어들면 기록이 아니다. 같은 실행을 journal 있이/없이
    돌렸을 때 결과도 판도 같아야 한다.
    """
    definition = make_definition(
        CardOperation.banish(PRIMARY_TARGET), DrawOperation(2)
    )

    without = new_state()
    quiet = run(without, definition, make_context(definition, my_monster(without)))

    with_journal = new_state()
    recorded = run(
        with_journal,
        definition,
        make_context(definition, my_monster(with_journal)),
        EventJournal(),
    )

    assert quiet.canonical_state() == recorded.canonical_state()
    assert without.state_hash() == with_journal.state_hash()


def test_the_journal_does_not_own_or_touch_the_board(state, journal):
    """
    **방향은 한 쪽뿐이다.** journal 은 ``GameState`` 를 참조조차 하지 않는다.
    """
    definition = make_definition(DrawOperation(1))
    run(state, definition, make_context(definition), journal)

    # 기록은 사건만 들고 있다. 판으로 가는 손잡이가 없다.
    assert EventJournal.__slots__ == ("_events",)
    assert all(
        not isinstance(held, GameState)
        for event in journal
        for held in (event.effect_ref, event.actor, event.source)
    )

    # 기록을 읽는다고 판이 달라지지 않는다.
    before = state.state_hash()
    journal.canonical_state()
    journal.journal_hash()
    journal.to_dict()
    journal.deltas()
    assert state.state_hash() == before


# ======================================================================
# 22~23. Authority
# ======================================================================


def test_a_text_derived_effect_never_reaches_the_journal(state, journal):
    """
    출처가 금지된 효과는 실행 경로에도 기록 경로에도 들어가지 않는다
    (ADR-004).
    """
    definition = make_definition(
        DrawOperation(1), provenance=EffectProvenance.text_derived("공식 텍스트")
    )
    before = state.state_hash()

    result = run(state, definition, make_context(definition), journal)

    assert result.status is ResolutionStatus.FORBIDDEN
    assert result.deltas == ()
    assert len(journal) == 0
    assert state.state_hash() == before


def test_an_unregistered_effect_leaves_no_delta_and_no_event(state, journal):
    definition = make_definition(DrawOperation(1))
    before = state.state_hash()

    result = EffectExecutor(EffectImplementationRegistry(), journal=journal).execute(
        state, definition, make_context(definition)
    )

    assert result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert result.deltas == ()
    assert len(journal) == 0
    assert state.state_hash() == before


def test_an_unsupported_operation_leaves_no_delta_and_no_event(state, journal):
    definition = make_definition(UnimplementedOperation("특수 소환"))
    before = state.state_hash()

    result = run(state, definition, make_context(definition, my_monster(state)), journal)

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert result.deltas == ()
    assert len(journal) == 0
    assert state.state_hash() == before


# ======================================================================
# 24~28. Identity — 기록이 판과 같은 말을 하는가
# ======================================================================


def test_a_delta_records_the_owners_zone_not_the_controllers(state, journal):
    """
    Hotfix 에서 확립한 ``destination = owner`` 가 **기록에도** 그대로 나와야
    한다. 판은 맞는데 기록이 틀리면 트리거 계층이 틀린 사건을 보게 된다.
    """
    card = steal_to_field(state)

    definition = make_definition(CardOperation.send_to_grave(PRIMARY_TARGET))
    result = run(
        state, definition, make_context(definition, card.instance_id), journal
    )

    delta = result.deltas[0]
    assert delta.from_player == MINE  # 내가 컨트롤하고 있었다
    assert delta.to_player == THEIRS  # 주인에게 돌아간다
    assert delta.changed_side is True
    assert delta.to_zone is Zone.GRAVE
    # 판과 일치한다.
    assert card.owner == THEIRS
    assert card.instance_id in {c.instance_id for c in state.player(THEIRS).grave}
    assert journal[0].deltas == result.deltas


def test_identity_survives_the_recording(state):
    definition = make_definition(CardOperation.banish(PRIMARY_TARGET))
    card = steal_to_field(state)
    before = (card.instance_id, card.owner, card.card_id)

    result = run(state, definition, make_context(definition, card.instance_id))

    assert (card.instance_id, card.owner, card.card_id) == before
    assert card.controller == THEIRS  # 도착한 존의 주인
    assert result.deltas[0].instance == card.instance_id


def test_a_delta_never_names_a_card_that_is_not_there(state, journal):
    """기록에 나온 카드는 전부 기록된 자리에 실제로 있어야 한다."""
    definition = make_definition(
        CardOperation.send_to_grave(PRIMARY_TARGET), DrawOperation(2)
    )
    run(state, definition, make_context(definition, my_monster(state)), journal)

    for delta in journal.deltas():
        if not isinstance(delta, CardMovement):
            continue
        card = state.find_instance(delta.instance)
        assert card is not None
        assert card.zone is delta.to_zone
        assert card.controller == delta.to_player


# ======================================================================
# 29~30. Determinism
# ======================================================================


def test_the_same_input_gives_the_same_deltas_and_the_same_history():
    definition = make_definition(
        CardOperation.release(PRIMARY_TARGET),
        DrawOperation(2),
        LifeChangeOperation(-700),
    )

    states, journals, results = [], [], []
    for _ in range(2):
        board = new_state()
        book = EventJournal()
        outcome = run(
            board, definition, make_context(definition, my_monster(board)), book
        )
        states.append(board)
        journals.append(book)
        results.append(outcome)

    assert results[0].canonical_state() == results[1].canonical_state()
    assert [d.canonical_state() for d in results[0].deltas] == [
        d.canonical_state() for d in results[1].deltas
    ]
    assert journals[0].canonical_state() == journals[1].canonical_state()
    assert journals[0].journal_hash() == journals[1].journal_hash()
    assert states[0].state_hash() == states[1].state_hash()


def test_a_different_history_hashes_differently(state):
    """같은 판에 도달해도 지나온 길이 다르면 기록은 다르다."""
    first, second = EventJournal(), EventJournal()
    banish = make_definition(CardOperation.banish(PRIMARY_TARGET), ordinal=0)
    draw = make_definition(DrawOperation(1), ordinal=1)

    board_a = new_state()
    run(board_a, banish, make_context(banish, my_monster(board_a)), first)
    run(board_a, draw, make_context(draw), first)

    board_b = new_state()
    run(board_b, draw, make_context(draw), second)
    run(board_b, banish, make_context(banish, my_monster(board_b)), second)

    assert board_a.state_hash() == board_b.state_hash()  # 판은 같다
    assert first.journal_hash() != second.journal_hash()  # 역사는 다르다


def test_the_board_hash_does_not_depend_on_the_journal(state):
    """
    **판의 해시와 역사의 해시는 다른 질문이다.** journal 을 ``GameState``
    안에 넣으면 "같은 판은 경로와 무관하게 같은 해시" 가 깨진다.
    """
    definition = make_definition(DrawOperation(1))

    quiet = new_state()
    run(quiet, definition, make_context(definition))

    recorded = new_state()
    book = EventJournal()
    run(recorded, definition, make_context(definition), book)

    assert quiet.state_hash() == recorded.state_hash()
    assert len(book) == 1
