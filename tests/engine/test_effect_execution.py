"""
engine/effect/executor.py — 효과가 **실제로 판을 바꾸는** 유일한 문.

여기가 보는 것은 세 가지다.

1. 바꿔도 되는 경우에만 바꾸는가 (권위 · 조건 · 대상).
2. 바꿀 때 **정확히 그만큼만** 바꾸는가 (목적지 · 주인 · 장수).
3. 바꾸지 않기로 했으면 **한 글자도** 바꾸지 않는가 (``state_hash`` 동일).

세 번째가 가장 중요하다. "실패했는데 절반 적용" 은 조용히 틀린 판을 만든다.
"""

import pytest

from engine.condition import (
    Always,
    CardIsFaceUp,
    ConditionResult,
    IsMonster,
    PlayerRef,
    UnimplementedRule,
)
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.effect import (
    PRIMARY_TARGET,
    SUPPORTED,
    AppliedOperation,
    CardOperation,
    DrawOperation,
    EffectDefinition,
    EffectExecutor,
    EffectImplementationRegistry,
    EffectProvenance,
    LifeChangeOperation,
    OperationKind,
    ResolutionContext,
    ResolutionStatus,
    TargetBinding,
    TargetRef,
    TargetSelection,
    TargetSpec,
    UnimplementedOperation,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Position, Zone

KUKLOK = 2511
DECK_A = list(range(1000, 1040))
DECK_B = list(range(2000, 2040))

FIELD_ZONES = (Zone.MZONE, Zone.EMZONE, Zone.SZONE)


# ======================================================================
# 판
# ======================================================================


def new_state() -> GameState:
    """
    같은 모양의 판을 몇 번이든 만든다. **셔플하지 않는다** — 결정론 테스트가
    이 함수에 의존한다.

    p0: 패 5장 · 앞면 몬스터 1장 / p1: 패 5장 · 앞면 몬스터 1장
    """
    game = GameState.create(decks=(DECK_A, DECK_B))
    game.draw(0, 5)
    game.draw(1, 5)
    for player in (0, 1):
        game.move(
            game.player(player).hand[0],
            Zone.MZONE,
            position=Position.FACEUP_ATTACK,
        )
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


def my_monster(state: GameState) -> InstanceId:
    return state.player(0).monster_zone[0].instance_id


def their_monster(state: GameState) -> InstanceId:
    return state.player(1).monster_zone[0].instance_id


def my_hand_card(state: GameState) -> InstanceId:
    return state.player(0).hand[0].instance_id


def total_cards(state: GameState) -> int:
    return len(state.all_instances())


# ======================================================================
# 정의 · 문맥 · 실행기
# ======================================================================


def monsters(owner: PlayerRef | None = None) -> ChoiceSpec:
    return ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.MZONE, Zone.EMZONE, Zone.HAND}), owner=owner
        )
    )


def one_target() -> tuple[TargetBinding, ...]:
    return TargetBinding.single(TargetSpec.targeting(monsters()))


def make_definition(
    *operations,
    targets=None,
    activation=None,
    provenance=None,
    ordinal: int = 0,
) -> EffectDefinition:
    """카드를 다루는 일이 있으면 ``@primary`` 대상을 자동으로 선언해 준다."""
    needs_target = any(operation.target_refs for operation in operations)
    if targets is None:
        targets = one_target() if needs_target else ()
    return EffectDefinition(
        effect_ref=EffectRef(KUKLOK, ordinal),
        source_card_id=KUKLOK,
        operations=tuple(operations),
        targets=targets,
        activation=activation,
        provenance=provenance or EffectProvenance.official_lua(),
    )


def make_context(
    definition: EffectDefinition,
    *chosen: InstanceId,
    controller: int = 0,
    selections=None,
    effect_ref: EffectRef | None = None,
) -> ResolutionContext:
    if selections is None:
        selections = (
            (TargetSelection(PRIMARY_TARGET, Selection.of(*chosen)),) if chosen else ()
        )
    return ResolutionContext(
        effect_ref or definition.effect_ref,
        controller=controller,
        selections=tuple(selections),
    )


def executor_for(*definitions) -> EffectExecutor:
    """이 정의들의 구현이 등록되어 있다고 선언한 실행기."""
    registry = EffectImplementationRegistry()
    for definition in definitions:
        registry.register(definition.effect_ref)
    return EffectExecutor(registry)


def run(state: GameState, definition: EffectDefinition, context: ResolutionContext):
    """실행하고 (결과, 실행 전 해시, 실행 후 해시) 를 돌려준다."""
    before = state.state_hash()
    result = executor_for(definition).execute(state, definition, context)
    return result, before, state.state_hash()


# ======================================================================
# 1~4. Executor contract
# ======================================================================


def test_an_executor_without_a_registry_runs_nothing(state):
    """
    기본 실행기는 구현이 하나도 등록되어 있지 않은 것으로 본다.

    자리표시가 아니라 **지금 엔진의 사실**이다 (ADR-006).
    """
    definition = make_definition(DrawOperation(1))
    context = make_context(definition)
    before = state.state_hash()

    result = EffectExecutor().execute(state, definition, context)

    assert result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert result.missing == "registered effect implementation"
    assert state.state_hash() == before


def test_a_successful_execution_reports_what_it_did(state):
    definition = make_definition(DrawOperation(2))
    result, before, after = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.RESOLVED
    assert result.changed_state is True
    assert result.code is ValidationCode.OK
    assert len(result.applied) == 1
    assert result.applied[0].kind is OperationKind.DRAW
    assert after != before


def test_a_failed_execution_carries_no_applied_record(state):
    """문맥이 다른 효과를 가리키면 그 상태에서 무엇을 하든 틀린 카드를 건드린다."""
    definition = make_definition(DrawOperation(1))
    context = make_context(definition, effect_ref=EffectRef(KUKLOK, 7))

    result, before, after = run(state, definition, context)

    assert result.status is ResolutionStatus.INVALID_CONTEXT
    assert result.code is ValidationCode.EFFECT_REF_CARD_MISMATCH
    assert result.applied == ()
    assert result.changed_state is False
    assert after == before


def test_destroy_is_never_silently_a_trip_to_the_graveyard(state):
    """
    파괴는 묘지로 보내기가 **아니다** (ADR-002).

    실행기는 파괴를 **할 줄 안다.** 다만 해도 되는지를 모른다 — 내성도
    대체 효과도 판정할 계층이 없다. 그래서 기본 실행기로는 파괴가
    일어나지 않는다. **``UNKNOWN`` 은 허가가 아니다.**

    무엇을 판정하지 못했는지는 결과가 그대로 들고 나온다.
    """
    definition = make_definition(CardOperation.destroy(PRIMARY_TARGET))
    target = their_monster(state)
    context = make_context(definition, target)

    result, before, after = run(state, definition, context)

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert after == before
    assert state.find_instance(target).zone is Zone.MZONE
    assert result.applied == ()
    assert result.deltas == ()

    # 멈췄지만 **무엇을 판정하지 못했는지** 말한다.
    assert result.unchecked_rules
    assert any("내성" in rule for rule in result.unchecked_rules)
    assert "destruction-legality" in (result.missing or "")

    # 그리고 파괴는 여전히 이 실행기가 **아는** 일이다.
    assert OperationKind.DESTROY in SUPPORTED


def test_an_unrepresented_operation_is_unsupported(state):
    """구조화하지 못한 일을 추측해서 실행하지 않는다."""
    definition = make_definition(UnimplementedOperation("특수 소환"))
    result, before, after = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert after == before


def test_the_executor_refuses_an_observation(state):
    """관측(GameStateView)으로 판을 고칠 수 없다."""
    definition = make_definition(DrawOperation(1))
    view = GameStateView.from_state(state, viewer=0)
    with pytest.raises(TypeError):
        executor_for(definition).execute(view, definition, make_context(definition))


def test_a_result_cannot_be_read_as_a_boolean(state):
    definition = make_definition(DrawOperation(1))
    result, _, _ = run(state, definition, make_context(definition))
    with pytest.raises(TypeError):
        bool(result)


# ======================================================================
# 5~12. Mutation — 하는 일 하나하나
# ======================================================================


def test_draw_moves_cards_from_the_deck_to_the_hand(state):
    definition = make_definition(DrawOperation(2))
    deck_before = len(state.player(0).deck)
    hand_before = len(state.player(0).hand)
    top_two = [card.instance_id for card in state.player(0).deck[:2]]

    result, _, _ = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.RESOLVED
    assert len(state.player(0).deck) == deck_before - 2
    assert len(state.player(0).hand) == hand_before + 2
    assert result.applied[0].instances == tuple(top_two)
    assert result.applied[0].amount == 2
    assert result.applied[0].player == 0


def test_draw_to_the_opponent_uses_the_opponents_deck(state):
    definition = make_definition(DrawOperation(1, who=PlayerRef.OPPONENT))
    mine = len(state.player(0).hand)

    result, _, _ = run(state, definition, make_context(definition, controller=0))

    assert result.status is ResolutionStatus.RESOLVED
    assert result.applied[0].player == 1
    assert len(state.player(0).hand) == mine


def test_a_draw_that_would_empty_the_deck_is_refused_not_half_done(state):
    """
    덱이 모자랄 때의 규칙(덱 데스)이 없다. 절반만 뽑아 놓고 끝내지 않는다.

    "실행기가 못 하는 일" 이 아니라 **"지금 판에 카드가 모자라다"** 이므로
    상태와 코드가 따로 있다.
    """
    definition = make_definition(DrawOperation(99))
    result, before, after = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert result.code is ValidationCode.INSUFFICIENT_DECK
    assert result.missing == "deck-out rule (Phase 2-G)"
    assert after == before


@pytest.mark.parametrize(
    "factory, destination, reasons",
    [
        (CardOperation.send_to_grave, Zone.GRAVE, ("EFFECT",)),
        (CardOperation.banish, Zone.REMOVED, ("EFFECT",)),
        (CardOperation.return_to_hand, Zone.HAND, ("RETURN", "EFFECT")),
        (CardOperation.return_to_deck, Zone.DECK, ("RETURN", "EFFECT")),
        (CardOperation.release, Zone.GRAVE, ("RELEASE",)),
    ],
)
def test_a_card_operation_moves_the_chosen_card(state, factory, destination, reasons):
    definition = make_definition(factory(PRIMARY_TARGET))
    target = my_monster(state)
    context = make_context(definition, target)

    result, _, _ = run(state, definition, context)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.find_instance(target).zone is destination
    assert result.applied[0].instances == (target,)
    assert result.applied[0].reason_names == reasons


def test_send_to_grave_and_release_end_up_in_the_same_place_but_are_not_the_same_event(
    state,
):
    """
    목적지로는 구분할 수 없다. 구분은 ``kind`` 와 ``reason_names`` 가 지킨다
    (ADR-002).
    """
    sent = my_monster(state)
    released = their_monster(state)

    send = make_definition(CardOperation.send_to_grave(PRIMARY_TARGET))
    release = make_definition(CardOperation.release(PRIMARY_TARGET), ordinal=1)

    first, _, _ = run(state, send, make_context(send, sent))
    second, _, _ = run(state, release, make_context(release, released))

    assert first.status is second.status is ResolutionStatus.RESOLVED
    assert state.find_instance(sent).zone is Zone.GRAVE
    assert state.find_instance(released).zone is Zone.GRAVE
    assert first.applied[0].kind is OperationKind.SEND_TO_GRAVE
    assert second.applied[0].kind is OperationKind.RELEASE
    assert first.applied[0].reason_names != second.applied[0].reason_names


def test_discard_sends_a_card_from_the_hand(state):
    definition = make_definition(CardOperation.discard(PRIMARY_TARGET))
    target = my_hand_card(state)
    context = make_context(definition, target)

    result, _, _ = run(state, definition, context)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.find_instance(target).zone is Zone.GRAVE
    assert result.applied[0].reason_names == ("DISCARD", "EFFECT")


def test_change_life_moves_life_points(state):
    definition = make_definition(LifeChangeOperation(-1200))
    before = state.player(0).life_points

    result, _, _ = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.RESOLVED
    assert state.player(0).life_points == before - 1200
    assert result.applied[0].amount == -1200
    assert result.applied[0].player == 0


def test_change_life_can_target_the_opponent(state):
    definition = make_definition(LifeChangeOperation(-800, who=PlayerRef.OPPONENT))
    mine = state.player(0).life_points
    theirs = state.player(1).life_points

    result, _, _ = run(state, definition, make_context(definition, controller=0))

    assert result.status is ResolutionStatus.RESOLVED
    assert state.player(0).life_points == mine
    assert state.player(1).life_points == theirs - 800


def test_several_operations_apply_in_order(state):
    definition = make_definition(
        CardOperation.send_to_grave(PRIMARY_TARGET),
        DrawOperation(1),
        LifeChangeOperation(500),
    )
    target = my_monster(state)
    life = state.player(0).life_points
    hand = len(state.player(0).hand)

    result, _, _ = run(state, definition, make_context(definition, target))

    assert result.status is ResolutionStatus.RESOLVED
    assert [applied.kind for applied in result.applied] == [
        OperationKind.SEND_TO_GRAVE,
        OperationKind.DRAW,
        OperationKind.CHANGE_LIFE,
    ]
    assert state.find_instance(target).zone is Zone.GRAVE
    assert len(state.player(0).hand) == hand + 1
    assert state.player(0).life_points == life + 500


# ======================================================================
# 13~16. Target
# ======================================================================


def test_each_operation_uses_the_target_it_names(state):
    """
    이름으로 잇는다. 일이 둘이고 대상이 둘이면 **서로 바뀌지 않아야** 한다.
    """
    first = TargetRef("first")
    second = TargetRef("second")
    definition = EffectDefinition(
        effect_ref=EffectRef(KUKLOK, 0),
        source_card_id=KUKLOK,
        targets=(
            TargetBinding(first, TargetSpec.targeting(monsters())),
            TargetBinding(second, TargetSpec.targeting(monsters())),
        ),
        operations=(
            CardOperation.banish(first),
            CardOperation.send_to_grave(second),
        ),
        provenance=EffectProvenance.official_lua(),
    )
    banished = my_monster(state)
    sent = their_monster(state)
    context = make_context(
        definition,
        selections=(
            TargetSelection(first, Selection.of(banished)),
            TargetSelection(second, Selection.of(sent)),
        ),
    )

    result, _, _ = run(state, definition, context)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.find_instance(banished).zone is Zone.REMOVED
    assert state.find_instance(sent).zone is Zone.GRAVE
    assert result.applied[0].instances == (banished,)
    assert result.applied[1].instances == (sent,)


def test_a_missing_selection_stops_the_whole_effect(state):
    """
    **아직 고르지 않았다** 는 "대상이 없다" 가 아니다. 뒤의 드로우도 하지
    않는다 — 반쯤 해결된 효과를 만들지 않는다.
    """
    definition = make_definition(
        CardOperation.banish(PRIMARY_TARGET), DrawOperation(1)
    )
    hand = len(state.player(0).hand)

    result, before, after = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    assert after == before
    assert len(state.player(0).hand) == hand


def test_an_empty_selection_is_not_a_selection(state):
    """빈 선택과 고르지 않음은 다르지만, 어느 쪽도 실행으로 이어지지 않는다."""
    definition = make_definition(CardOperation.banish(PRIMARY_TARGET))
    context = make_context(
        definition, selections=(TargetSelection(PRIMARY_TARGET, Selection()),)
    )

    result, before, after = run(state, definition, context)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert after == before


def test_a_card_that_is_not_in_this_duel_cannot_be_chosen(state):
    definition = make_definition(CardOperation.banish(PRIMARY_TARGET))
    context = make_context(definition, InstanceId(9999))

    result, before, after = run(state, definition, context)

    # **없는 것과 보이지 않는 것을 구분하지 못한다** (Phase 2-N). 관측에
    # 없는 카드를 "이 듀얼에 없다" 고 단정하는 것 자체가 정보이므로,
    # 대상 계층은 UNKNOWN 으로 남긴다. 판이 그대로인 것은 변함없다.
    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.HIDDEN_CARD
    assert result.applied == ()
    assert result.deltas == ()
    assert after == before


def test_a_card_on_the_field_cannot_be_discarded(state):
    """
    버리기는 **패에서만** 일어난다. 필드의 카드를 "버렸다" 고 기록하면
    트리거 계층이 틀린 사건을 보게 된다.
    """
    definition = make_definition(CardOperation.discard(PRIMARY_TARGET))
    target = my_monster(state)
    context = make_context(definition, target)

    result, before, after = run(state, definition, context)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.SOURCE_WRONG_ZONE
    assert after == before
    assert state.find_instance(target).zone is Zone.MZONE


def test_one_bad_card_stops_the_whole_operation(state):
    """
    여러 장 중 한 장이라도 잘못되면 **한 장도 옮기지 않는다.**
    """
    definition = make_definition(CardOperation.banish(PRIMARY_TARGET))
    good = my_monster(state)
    context = make_context(definition, good, InstanceId(9999))

    result, before, after = run(state, definition, context)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert after == before
    assert state.find_instance(good).zone is Zone.MZONE


# ======================================================================
# 17~19. Authority — 출처와 등록은 다른 질문이다
# ======================================================================


def test_a_text_derived_effect_never_runs_even_with_an_implementation(state):
    """
    **출처 금지가 가장 먼저**다. 구현이 등록되어 있어도 실행하지 않는다
    (ADR-004).
    """
    definition = make_definition(
        DrawOperation(1), provenance=EffectProvenance.text_derived("공식 텍스트")
    )
    result, before, after = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.FORBIDDEN
    assert result.missing == "executable implementation from official script"
    assert after == before


def test_verified_semantics_alone_do_not_permit_execution(state):
    """``LUA_VERIFIED`` 라고 실행되지 않는다. 등록된 구현이 있어야 한다 (ADR-006)."""
    definition = make_definition(DrawOperation(1))
    before = state.state_hash()

    result = EffectExecutor(EffectImplementationRegistry()).execute(
        state, definition, make_context(definition)
    )

    assert result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert state.state_hash() == before


def test_an_unverified_effect_is_unknown_not_forbidden_and_not_run(state):
    """
    "확인되지 않았다" 는 "금지" 와도 "거짓" 과도 다르다. 어느 쪽이든 실행은
    하지 않는다.
    """
    definition = make_definition(
        DrawOperation(1), provenance=EffectProvenance.hand_written(verified=False)
    )
    result, before, after = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.UNKNOWN
    assert result.missing == "verified semantics"
    assert after == before


def test_only_a_registered_and_permitted_effect_runs(state):
    """
    같은 정의라도 등록 여부에 따라 갈린다. 등록은 **손으로** 한다.
    """
    definition = make_definition(DrawOperation(1))
    registry = EffectImplementationRegistry()
    executor = EffectExecutor(registry)

    assert (
        executor.execute(state, definition, make_context(definition)).status
        is ResolutionStatus.NOT_IMPLEMENTED
    )

    registry.register(definition.effect_ref)
    assert (
        executor.execute(state, definition, make_context(definition)).status
        is ResolutionStatus.RESOLVED
    )


def test_registering_one_effect_does_not_register_its_sibling(state):
    """``EffectRef`` 는 ``(card_id, ordinal)`` 이다. 카드 단위 등록이 아니다."""
    first = make_definition(DrawOperation(1), ordinal=0)
    second = make_definition(DrawOperation(1), ordinal=1)
    executor = executor_for(first)

    assert (
        executor.execute(state, first, make_context(first)).status
        is ResolutionStatus.RESOLVED
    )
    assert (
        executor.execute(state, second, make_context(second)).status
        is ResolutionStatus.NOT_IMPLEMENTED
    )


# ======================================================================
# 20~22. Condition — 모르는 것을 실행으로 바꾸지 않는다
# ======================================================================


def test_a_true_condition_lets_the_effect_run(state):
    definition = make_definition(DrawOperation(1), activation=Always())
    result, before, after = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.RESOLVED
    assert after != before


def test_a_false_condition_changes_nothing(state):
    definition = make_definition(
        DrawOperation(1), activation=Always(ConditionResult.FALSE)
    )
    result, before, after = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.CONDITION_FALSE
    assert result.applied == ()
    assert after == before


def test_an_unknown_condition_changes_nothing_and_is_not_false(state):
    """
    ``UNKNOWN`` 을 ``TRUE`` 로도 ``FALSE`` 로도 접지 않는다. 별도의 상태로
    남고, 무엇을 몰랐는지 남긴다.
    """
    definition = make_definition(
        DrawOperation(1), activation=UnimplementedRule("체인 위의 카드 수")
    )
    result, before, after = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.CONDITION_UNKNOWN
    assert result.status is not ResolutionStatus.CONDITION_FALSE
    assert result.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert "체인 위의 카드 수" in (result.missing or "")
    assert after == before


def test_hidden_information_makes_the_condition_unknown_not_true(state):
    """
    상대의 세트 카드가 **무엇인가**는 보이지 않는다. 그것을 묻는 조건의
    답은 모름이고, 모름은 실행되지 않는다.

    "뒷면인가" 는 다른 질문이다 — 그것은 공개 정보라서 판정된다. 여기서
    묻는 것은 정체다.
    """
    facedown = state.move(
        state.player(1).hand[0], Zone.SZONE, position=Position.FACEDOWN
    )
    definition = make_definition(
        DrawOperation(1), activation=IsMonster(facedown.instance_id)
    )
    result, before, after = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.CONDITION_UNKNOWN
    assert after == before
    assert GameStateView.from_state(state, viewer=0).find(
        facedown.instance_id
    ).definition is None


def test_being_face_down_is_public_information_and_answers_false(state):
    """
    가려진 것과 알려진 것을 섞지 않는다. 상대 세트 카드의 **표시 형식**은
    보이므로 ``UNKNOWN`` 이 아니라 ``FALSE`` 다.
    """
    facedown = state.move(
        state.player(1).hand[0], Zone.SZONE, position=Position.FACEDOWN
    )
    definition = make_definition(
        DrawOperation(1), activation=CardIsFaceUp(facedown.instance_id)
    )
    result, before, after = run(state, definition, make_context(definition))

    assert result.status is ResolutionStatus.CONDITION_FALSE
    assert after == before


# ======================================================================
# 23~27. Integrity — 바꾼 뒤에도 판이 판인가
# ======================================================================


def test_an_instance_keeps_its_id_through_an_effect(state):
    definition = make_definition(CardOperation.banish(PRIMARY_TARGET))
    target = my_monster(state)
    card_id = state.find_instance(target).card_id

    run(state, definition, make_context(definition, target))

    moved = state.find_instance(target)
    assert moved is not None
    assert moved.instance_id == target
    assert moved.card_id == card_id


def test_a_stolen_card_goes_to_its_owners_graveyard(state):
    """
    **주인 ≠ 컨트롤러.** 컨트롤을 빼앗긴 카드도 묘지는 주인 쪽으로 간다.
    ``GameState.move`` 의 기본값은 컨트롤러이므로, 실행기가 주인을 명시하지
    않으면 여기서 틀린다.
    """
    stolen = state.player(1).monster_zone[0]
    state.move(stolen, Zone.MZONE, to_player=0, position=Position.FACEUP_ATTACK)
    assert stolen.owner == 1 and stolen.controller == 0

    definition = make_definition(CardOperation.send_to_grave(PRIMARY_TARGET))
    result, _, _ = run(state, definition, make_context(definition, stolen.instance_id))

    assert result.status is ResolutionStatus.RESOLVED
    assert stolen.owner == 1
    assert stolen.zone is Zone.GRAVE
    assert stolen.instance_id in [c.instance_id for c in state.player(1).grave]
    assert stolen.instance_id not in [c.instance_id for c in state.player(0).grave]


def test_a_card_is_in_exactly_one_zone_after_an_effect(state):
    definition = make_definition(
        CardOperation.send_to_grave(PRIMARY_TARGET), DrawOperation(2)
    )
    run(state, definition, make_context(definition, my_monster(state)))

    seen: dict[InstanceId, int] = {}
    for player in (0, 1):
        for zone in Zone:
            try:
                container = state.zone(player, zone)
            except KeyError:
                continue
            for card in container:
                seen[card.instance_id] = seen.get(card.instance_id, 0) + 1
    assert seen and all(count == 1 for count in seen.values())


def test_no_card_is_created_or_lost(state):
    before = total_cards(state)
    ids_before = {card.instance_id for card in state.all_instances()}

    definition = make_definition(
        CardOperation.banish(PRIMARY_TARGET),
        DrawOperation(3),
        LifeChangeOperation(-100),
    )
    run(state, definition, make_context(definition, my_monster(state)))

    assert total_cards(state) == before
    assert {card.instance_id for card in state.all_instances()} == ids_before


def test_slotted_zones_stay_within_their_slots(state):
    """
    MZONE · EMZONE · SZONE 은 칸이 정해져 있다. 효과가 지나간 뒤에도
    칸 수를 넘지 않고, 같은 카드가 두 칸에 있지 않아야 한다.
    """
    extra = state.create_instance(1500, owner=0, zone=Zone.HAND)
    state.move(extra, Zone.EMZONE, position=Position.FACEUP_ATTACK)

    definition = make_definition(CardOperation.return_to_hand(PRIMARY_TARGET))
    run(state, definition, make_context(definition, extra.instance_id))

    for player in (0, 1):
        for zone in FIELD_ZONES:
            container = state.zone(player, zone)
            assert container.capacity is not None
            assert len(container) <= container.capacity
            occupied = [card for card in container.slots() if card is not None]
            assert len(occupied) == len(container)
            assert len({card.instance_id for card in occupied}) == len(occupied)

    assert extra.zone is Zone.HAND
    assert len(state.zone(0, Zone.EMZONE)) == 0


def test_returning_a_monster_frees_its_zone_for_another(state):
    """존을 비웠는데 다시 못 채우면 그것은 비운 것이 아니다."""
    definition = make_definition(CardOperation.return_to_hand(PRIMARY_TARGET))
    target = my_monster(state)
    run(state, definition, make_context(definition, target))

    assert not state.zone(0, Zone.MZONE).is_full
    replacement = state.player(0).hand[0]
    state.move(replacement, Zone.MZONE, position=Position.FACEUP_ATTACK)
    assert replacement.zone is Zone.MZONE


# ======================================================================
# 28. Determinism
# ======================================================================


def test_the_same_input_gives_the_same_result_and_the_same_board():
    first, second = new_state(), new_state()
    assert first.state_hash() == second.state_hash()

    definition = make_definition(
        CardOperation.send_to_grave(PRIMARY_TARGET),
        DrawOperation(2),
        LifeChangeOperation(-300),
    )

    outcomes = []
    for state in (first, second):
        result, _, _ = run(state, definition, make_context(definition, my_monster(state)))
        outcomes.append(result)

    assert outcomes[0].canonical_state() == outcomes[1].canonical_state()
    assert first.state_hash() == second.state_hash()


def test_the_record_of_what_happened_serializes(state):
    definition = make_definition(
        CardOperation.banish(PRIMARY_TARGET), LifeChangeOperation(-200)
    )
    result, _, _ = run(state, definition, make_context(definition, my_monster(state)))

    data = result.to_dict()
    assert data["status"] == "resolved"
    assert [entry["kind"] for entry in data["applied"]] == ["banish", "change_life"]
    assert data["applied"][0]["reasons"] == ["EFFECT"]
    assert data["applied"][1]["amount"] == -200


def test_an_applied_record_is_not_a_state_delta():
    """
    :class:`AppliedOperation` 은 **무슨 일이 있었는지의 기록**이지 되돌리기
    위한 것이 아니다 (ADR-008).
    """
    record = AppliedOperation(OperationKind.BANISH, ("EFFECT",), (InstanceId(1),))
    assert not hasattr(record, "undo")
    assert not hasattr(record, "before")


# ======================================================================
# 29. Failure atomicity — 실패하면 한 글자도 바뀌지 않는다
# ======================================================================


def failure_cases(state: GameState):
    """§25 가 요구하는 다섯 가지 실패. 각각 (이름, 정의, 문맥)."""
    forbidden = make_definition(
        CardOperation.banish(PRIMARY_TARGET),
        DrawOperation(1),
        provenance=EffectProvenance.text_derived(),
    )
    # 파괴는 Phase 2-M 부터 실행된다. "실행기가 못 하는 일" 의 표본은
    # 여전히 구조화하지 못한 일이다 — 이 표본이 가리키는 사실은 그대로다.
    unsupported = make_definition(
        UnimplementedOperation("특수 소환"), DrawOperation(1), ordinal=1
    )
    false_condition = make_definition(
        CardOperation.banish(PRIMARY_TARGET),
        DrawOperation(1),
        activation=Always(ConditionResult.FALSE),
        ordinal=2,
    )
    unknown_condition = make_definition(
        CardOperation.banish(PRIMARY_TARGET),
        DrawOperation(1),
        activation=UnimplementedRule("아직 없는 규칙"),
        ordinal=3,
    )
    bad_target = make_definition(
        CardOperation.banish(PRIMARY_TARGET), DrawOperation(1), ordinal=4
    )
    target = my_monster(state)
    return [
        ("forbidden source", forbidden, make_context(forbidden, target)),
        ("unsupported operation", unsupported, make_context(unsupported, target)),
        ("condition false", false_condition, make_context(false_condition, target)),
        ("condition unknown", unknown_condition, make_context(unknown_condition, target)),
        ("invalid target", bad_target, make_context(bad_target, InstanceId(9999))),
    ]


def test_every_refusal_leaves_the_board_byte_identical(state):
    """
    성공한 실행만 판을 바꾼다. 나머지는 **전부** 해시가 같아야 한다.
    드로우가 뒤에 붙어 있어도 한 장도 뽑히지 않는다.
    """
    for name, definition, context in failure_cases(state):
        before = state.state_hash()
        life = state.player(0).life_points
        hand = len(state.player(0).hand)

        result = executor_for(definition).execute(state, definition, context)

        assert result.status is not ResolutionStatus.RESOLVED, name
        assert result.changed_state is False, name
        assert result.applied == (), name
        assert state.state_hash() == before, name
        assert state.player(0).life_points == life, name
        assert len(state.player(0).hand) == hand, name


def test_a_later_failure_does_not_apply_the_earlier_operations(state):
    """
    **계획을 먼저 다 세운다.** 첫 일이 멀쩡해도 뒤의 일이 걸리면 첫 일도
    일어나지 않는다.
    """
    definition = make_definition(
        CardOperation.banish(PRIMARY_TARGET),
        DrawOperation(99),  # 덱이 모자라 계획에서 걸린다
    )
    target = my_monster(state)

    result, before, after = run(state, definition, make_context(definition, target))

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert after == before
    assert state.find_instance(target).zone is Zone.MZONE


def test_a_refusal_never_touches_the_other_players_board(state):
    definition = make_definition(
        UnimplementedOperation("특수 소환"),
        provenance=EffectProvenance.official_lua(),
    )
    context = make_context(definition, their_monster(state), controller=0)
    theirs_before = state.player(1).canonical_state()

    result, before, after = run(state, definition, context)

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert after == before
    assert state.player(1).canonical_state() == theirs_before
