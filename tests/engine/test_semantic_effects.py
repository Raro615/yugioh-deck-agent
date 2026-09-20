"""
Phase 2-M — 의미 계층.

    DESTROY  ≠  SEND_TO_GRAVE  ≠  DISCARD  ≠  MOVE

넷 다 결국 묘지로 간다. 목적지로는 구분할 수 없으므로, 구분은 **값으로**
들고 다녀야 한다 (ADR-002).

네 가지를 본다.

1. **셋이 실제로 판을 바꾸는가** — 카드가 묘지로 간다.
2. **그런데 서로 다른 일로 기록되는가** — ``kind`` · ``reason_names`` ·
   Delta · Event 어디에서도 뭉개지지 않는다.
3. **보지 않은 규칙을 말하는가** — 파괴를 실행하면서 내성을 보지 않은 것은
   거짓말이 아니라 미완성이고, 그 차이는 적어 두는가 하나다.
4. **실패가 판을 건드리지 않는가.**

여기서 쓰는 정의는 대부분 **synthetic** 이다. 파괴 · 보내기 · 버리기는
전부 대상 선택이 필요하고 그 계층이 아직 없어서, 실제 카드로는 이 경로를
시험할 수 없다 (문서 §5 참고).
"""

import ast
import pathlib

import pytest

from engine.chain import Chain, ChainLink, ChainResolutionStatus, ChainResolver
from engine.condition import ConditionResult
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionError,
    EffectProvenance,
)
from engine.effect.delta import ZoneMoved
from engine.effect.executor import (
    SUPPORTED,
    UNSUPPORTED_REASON,
    EffectExecutor,
    EffectImplementationRegistry,
)
from engine.effect.journal import EventJournal
from engine.effect.library import LibraryEntry, build_executor, definition_registry
from engine.effect.operation import (
    CardOperation,
    DrawOperation,
    MoveOperation,
    OperationKind,
    UnimplementedOperation,
)
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.semantics import (
    FIELD_ZONES,
    GATING_RULES,
    ORIGIN_RULES,
    RULE_GATED,
    SEMANTIC_KINDS,
    UNCHECKED_SEMANTIC_RULES,
    DeclaredDestructionRuling,
    DestructionRuling,
    OriginRule,
    UnknownDestructionRuling,
    collect_unchecked,
    is_rule_gated,
    is_semantic,
    origin_rule,
    unchecked_rules,
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

FEATHERMAN = 21844576  # 레벨 3 통상 몬스터
LAB = 2511  # 라뷰린스 쿠클락 — synthetic 정의의 껍데기

PRIMARY = TargetRef("PRIMARY")

DESTROY = OperationKind.DESTROY
SEND = OperationKind.SEND_TO_GRAVE
DISCARD = OperationKind.DISCARD
MOVE = OperationKind.MOVE


# ======================================================================
# 판 · 도구
# ======================================================================


def new_state(repository) -> GameState:
    """p0: 패 3장 · 앞면 몬스터 1장. p1: 앞면 몬스터 1장."""
    game = GameState.create(
        repository, decks=([FEATHERMAN] * 12, [FEATHERMAN] * 6)
    )
    game.draw(MINE, 4)
    game.draw(THEIRS, 2)
    game.move(
        game.player(MINE).hand[0], Zone.MZONE, to_player=MINE,
        position=Position.FACEUP_ATTACK,
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


def synthetic(*operations, ordinal: int = 0) -> EffectDefinition:
    """
    **synthetic 정의**다. 실제 카드의 의미를 주장하지 않는다 — 출처가
    ``hand_written`` 이라고 적혀 있고, 의미 계층의 경로만 시험한다.
    """
    needs_target = any(operation.target_refs for operation in operations)
    targets = (
        (
            TargetBinding(
                PRIMARY,
                TargetSpec.targeting(
                    ChoiceSpec(
                        source=CandidateSource(
                            zones=frozenset(
                                {Zone.HAND, Zone.MZONE, Zone.GRAVE, Zone.DECK}
                            ),
                            # 주인을 가리지 않는다 — 상대 몬스터도 대상이 된다.
                            owner=None,
                        ),
                        maximum=2,
                    )
                ),
            ),
        )
        if needs_target
        else ()
    )
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        operations=tuple(operations),
        targets=targets,
        provenance=EffectProvenance.hand_written(verified=True, note="의미 계층 시험"),
    )


def confirmed(*instances: InstanceId) -> DeclaredDestructionRuling:
    """
    **사람이 확인했다고 선언한** 파괴 판정.

    내성 계층을 대신하지 않는다 — "이 카드에 대해서는 확인했다" 를 값으로
    적는 것뿐이고, 적히지 않은 카드는 여전히 ``UNKNOWN`` 이라 파괴되지
    않는다. 구현 등록을 손으로만 받는 ADR-006 과 같은 자리다.
    """
    return DeclaredDestructionRuling(destructible=frozenset(instances))


def run(
    state: GameState,
    definition: EffectDefinition,
    *chosen: InstanceId,
    destruction: DestructionRuling | None = None,
):
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        destruction=destruction,
    )
    selections = (
        (TargetSelection(PRIMARY, Selection(chosen=tuple(chosen))),) if chosen else ()
    )
    return executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref, controller=MINE, selections=selections
        ),
    )


def my_monster(state: GameState) -> InstanceId:
    return state.player(MINE).monster_zone[0].instance_id


def my_hand_card(state: GameState) -> InstanceId:
    return state.player(MINE).hand[0].instance_id


# ======================================================================
# A. DESTROY
# ======================================================================


@requires_official_db
def test_destroy_actually_removes_the_monster_from_the_field(state):
    target = my_monster(state)

    result = run(
        state,
        synthetic(CardOperation.destroy(PRIMARY)),
        target,
        destruction=confirmed(target),
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(target).zone is Zone.GRAVE
    assert len(state.player(MINE).monster_zone) == 0


@requires_official_db
def test_a_destruction_is_recorded_as_a_destruction(state):
    target = my_monster(state)

    result = run(
        state,
        synthetic(CardOperation.destroy(PRIMARY)),
        target,
        destruction=confirmed(target),
    )

    assert result.applied[0].kind is DESTROY
    assert result.applied[0].reason_names == ("DESTROY", "EFFECT")
    assert result.deltas[0].operation is DESTROY
    assert "DESTROY" in result.deltas[0].reason_names


@requires_official_db
def test_a_destruction_says_which_rules_it_did_not_look_at(state):
    """
    **이 단계의 핵심이다.** 파괴를 실행하면서 내성을 보지 않은 것은
    거짓말이 아니라 미완성이고, 그 차이는 적어 두는가 하나다.
    """
    target = my_monster(state)
    result = run(
        state,
        synthetic(CardOperation.destroy(PRIMARY)),
        target,
        destruction=confirmed(target),
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert result.unchecked_rules == UNCHECKED_SEMANTIC_RULES[DESTROY]
    assert any("내성" in rule for rule in result.unchecked_rules)
    assert any("대체" in rule for rule in result.unchecked_rules)
    assert any("유발" in rule for rule in result.unchecked_rules)


@requires_official_db
def test_destroying_a_card_outside_the_field_is_unknown_not_refused(state):
    """
    필드 밖 파괴는 **이 엔진이 모르는 것**이지 "규칙상 안 되는 것" 이 아니다.
    """
    target = my_hand_card(state)
    before = state.state_hash()

    result = run(state, synthetic(CardOperation.destroy(PRIMARY)), target)

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "off-field destruction" in (result.missing or "")
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_the_opponents_monster_can_be_destroyed_and_goes_to_its_owner(state):
    """파괴된 카드는 **주인의** 묘지로 간다 (Owner ≠ Controller)."""
    target = state.player(THEIRS).monster_zone[0].instance_id

    run(
        state,
        synthetic(CardOperation.destroy(PRIMARY)),
        target,
        destruction=confirmed(target),
    )

    card = state.find_instance(target)
    assert card.zone is Zone.GRAVE
    assert card.owner == THEIRS
    assert len(state.player(THEIRS).grave) == 1
    assert len(state.player(MINE).grave) == 0


# ======================================================================
# B. SEND_TO_GRAVE
# ======================================================================


@requires_official_db
def test_send_to_grave_moves_the_card(state):
    target = my_monster(state)

    result = run(state, synthetic(CardOperation.send_to_grave(PRIMARY)), target)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(target).zone is Zone.GRAVE


@requires_official_db
def test_send_to_grave_is_not_a_destruction(state):
    """
    같은 칸에서 같은 묘지로 갔다. **그래도 같은 사건이 아니다** — 파괴
    내성이 막지 못하고, "파괴되었을 때" 가 발동하지 않는다.
    """
    result = run(
        state, synthetic(CardOperation.send_to_grave(PRIMARY)), my_monster(state)
    )

    assert result.applied[0].kind is SEND
    assert result.applied[0].kind is not DESTROY
    assert "DESTROY" not in result.deltas[0].reason_names
    assert result.unchecked_rules == UNCHECKED_SEMANTIC_RULES[SEND]
    assert result.unchecked_rules != UNCHECKED_SEMANTIC_RULES[DESTROY]


@requires_official_db
def test_send_to_grave_does_not_care_where_the_card_starts(state):
    """
    보내기는 패 · 덱 · 필드 어디서든 일어난다. **모르는 제약을 지어내지
    않는다** — 출발 자리 규칙을 적지 않은 것이 그 사실이다.
    """
    assert origin_rule(SEND) is None

    from_hand = my_hand_card(state)
    result = run(state, synthetic(CardOperation.send_to_grave(PRIMARY)), from_hand)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(from_hand).zone is Zone.GRAVE


# ======================================================================
# C. DISCARD
# ======================================================================


@requires_official_db
def test_discard_moves_a_card_from_the_hand(state):
    target = my_hand_card(state)
    hand_before = len(state.player(MINE).hand)

    result = run(state, synthetic(CardOperation.discard(PRIMARY)), target)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(target).zone is Zone.GRAVE
    assert len(state.player(MINE).hand) == hand_before - 1


@requires_official_db
def test_discarding_a_card_that_is_not_in_hand_is_refused(state):
    """
    버리기는 패에서만 일어난다. **이것은 규칙을 아는 경우**라 "모른다" 가
    아니라 "안 된다" 다.
    """
    target = my_monster(state)
    before = state.state_hash()

    result = run(state, synthetic(CardOperation.discard(PRIMARY)), target)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.SOURCE_WRONG_ZONE
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_discard_is_neither_destruction_nor_a_plain_send(state):
    result = run(state, synthetic(CardOperation.discard(PRIMARY)), my_hand_card(state))

    assert result.applied[0].kind is DISCARD
    assert result.applied[0].reason_names == ("DISCARD", "EFFECT")
    assert result.unchecked_rules == UNCHECKED_SEMANTIC_RULES[DISCARD]
    assert any("버려졌을 때" in rule for rule in result.unchecked_rules)


# ======================================================================
# D. 세 의미의 분리
# ======================================================================


@requires_official_db
def test_three_meanings_land_in_the_same_place_and_stay_different(state):
    """
    **한 화면에서 보는 분리.** 셋 다 묘지로 갔는데 셋 다 다른 사건이다.
    """
    state.draw(MINE, 2)
    cards = [card.instance_id for card in state.player(MINE).hand[:3]]
    kinds, reasons = [], []

    plan = (
        # 파괴는 필드에서만 일어나므로 먼저 필드로 옮겨 둔다.
        (CardOperation.destroy(PRIMARY), True),
        (CardOperation.send_to_grave(PRIMARY), False),
        (CardOperation.discard(PRIMARY), False),
    )
    for index, (operation, onto_field) in enumerate(plan):
        if onto_field:
            state.move(
                state.find_instance(cards[index]), Zone.MZONE, to_player=MINE,
                position=Position.FACEUP_ATTACK,
            )
        result = run(
            state,
            synthetic(operation, ordinal=index),
            cards[index],
            destruction=confirmed(cards[index]),
        )
        assert result.status is ResolutionStatus.RESOLVED, operation
        assert state.locate(cards[index]).zone is Zone.GRAVE
        kinds.append(result.applied[0].kind)
        reasons.append(result.applied[0].reason_names)

    assert kinds == [DESTROY, SEND, DISCARD]
    assert len(set(kinds)) == 3
    assert len(set(reasons)) == 3


def test_the_semantic_kinds_are_exactly_the_three():
    assert SEMANTIC_KINDS == {DESTROY, SEND, DISCARD}
    for kind in SEMANTIC_KINDS:
        assert is_semantic(kind)
        assert unchecked_rules(kind)


def test_a_bare_move_claims_no_meaning_and_no_missing_rules():
    """
    ``MOVE`` 는 의미가 **없다.** 그래서 "보지 않은 규칙" 도 없다 — 애초에
    주장한 것이 없기 때문이다. 빈 목록이 "전부 봤다" 가 아니다.
    """
    assert is_semantic(MOVE) is False
    assert unchecked_rules(MOVE) == ()
    assert MoveOperation(Zone.GRAVE, PRIMARY).reason_names == ()


@requires_official_db
def test_a_move_to_the_graveyard_is_not_recorded_as_any_meaning(state):
    target = my_hand_card(state)

    result = run(state, synthetic(MoveOperation(Zone.GRAVE, PRIMARY)), target)

    assert result.applied[0].kind is MOVE
    assert result.applied[0].kind not in SEMANTIC_KINDS
    assert result.deltas[0].reason_names == ()
    assert result.unchecked_rules == ()


def test_the_three_meanings_do_not_share_their_unchecked_rules():
    lists = [UNCHECKED_SEMANTIC_RULES[kind] for kind in (DESTROY, SEND, DISCARD)]

    assert len({tuple(rules) for rules in lists}) == 3
    assert all(rules for rules in lists)


def test_collecting_unchecked_rules_is_ordered_and_deduplicated():
    """집합으로 만들면 같은 입력이 다른 순서를 낳는다 — 결정론이 깨진다."""
    collected = collect_unchecked([DESTROY, DISCARD, DESTROY, MOVE])

    assert collected[: len(UNCHECKED_SEMANTIC_RULES[DESTROY])] == (
        UNCHECKED_SEMANTIC_RULES[DESTROY]
    )
    assert len(collected) == len(set(collected))
    assert collect_unchecked([DESTROY, DISCARD]) == collect_unchecked(
        [DESTROY, DISCARD]
    )


def test_an_origin_rule_must_say_whether_it_knows():
    with pytest.raises(ValueError):
        OriginRule(zones=frozenset({Zone.HAND}), known=False, detail="모름")
    with pytest.raises(ValueError):
        OriginRule(
            zones=frozenset({Zone.HAND}), known=True, detail="앎", missing="없는 규칙"
        )


def test_the_two_origin_rules_say_different_things():
    """
    "규칙상 불가능" 과 "아직 안 옮겼다" 를 한 덩어리로 만들지 않는다.
    """
    assert ORIGIN_RULES[DISCARD].known is True
    assert ORIGIN_RULES[DISCARD].missing is None
    assert ORIGIN_RULES[DESTROY].known is False
    assert ORIGIN_RULES[DESTROY].missing
    assert ORIGIN_RULES[DESTROY].zones == FIELD_ZONES


# ======================================================================
# E. Delta · Event
# ======================================================================


@requires_official_db
def test_the_meaning_survives_all_the_way_to_the_timing_event(state):
    """
    사건이 트리거 계층에 닿을 때까지 **왜 움직였는가**가 남아 있어야 한다.
    """
    target = my_monster(state)
    result = run(
        state,
        synthetic(CardOperation.destroy(PRIMARY)),
        target,
        destruction=confirmed(target),
    )

    event = TimingEvent.from_delta(result.deltas[0])

    assert event.point is TimingPoint.CARD_MOVED
    assert event.operation is DESTROY
    assert "DESTROY" in event.delta.reason_names
    assert (event.from_zone, event.to_zone) == (Zone.MZONE, Zone.GRAVE)


@requires_official_db
def test_the_event_pipeline_keeps_the_three_apart(state):
    """
    2-J 의 통로를 그대로 쓴다. 새 ``EventKind`` 도 새 Delta 도 만들지 않았다.
    """
    state.draw(MINE, 2)
    cards = [card.instance_id for card in state.player(MINE).hand[:2]]
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))
    seen = []

    for index, factory in enumerate(
        (CardOperation.send_to_grave, CardOperation.discard)
    ):
        result = run(state, synthetic(factory(PRIMARY), ordinal=index), cards[index])
        events = reader.read(result, actor=MINE)
        assert len(events) == 1
        assert events[0].point is TimingPoint.CARD_MOVED
        seen.append(events[0].delta.operation)

    assert seen == [SEND, DISCARD]


@requires_official_db
def test_a_trigger_declaration_can_tell_destruction_from_sending(state):
    """
    기존 ``TriggerSpec.operations`` 필터가 그대로 쓸 수 있는 정보다.
    새 트리거 시스템을 만들지 않는다 (§9).
    """
    from engine.trigger import TriggerRegistry, TriggerSpec

    registry = TriggerRegistry().register(
        TriggerSpec(
            EffectRef(FEATHERMAN, 0),
            TimingPoint.CARD_MOVED,
            operations=frozenset({DESTROY}),
        )
    )
    destroyed = run(
        state,
        synthetic(CardOperation.destroy(PRIMARY)),
        my_monster(state),
        destruction=confirmed(my_monster(state)),
    )
    sent = run(
        state,
        synthetic(CardOperation.send_to_grave(PRIMARY), ordinal=1),
        my_hand_card(state),
    )

    assert registry.watching(TimingEvent.from_delta(destroyed.deltas[0]))
    assert registry.watching(TimingEvent.from_delta(sent.deltas[0])) == ()


@requires_official_db
def test_the_journal_keeps_the_meaning_too(state):
    journal = EventJournal()
    definition = synthetic(CardOperation.destroy(PRIMARY))
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        journal=journal,
        destruction=confirmed(my_monster(state)),
    )

    executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref,
            controller=MINE,
            selections=(
                TargetSelection(PRIMARY, Selection(chosen=(my_monster(state),))),
            ),
        ),
    )

    assert len(journal) == 1
    recorded = list(journal)[0]
    assert recorded.applied[0].kind is DESTROY
    assert recorded.deltas[0].operation is DESTROY


# ======================================================================
# F. 실패 안전성
# ======================================================================


@requires_official_db
@pytest.mark.parametrize(
    "factory",
    [CardOperation.destroy, CardOperation.send_to_grave, CardOperation.discard],
)
def test_a_missing_card_stops_every_meaning(state, factory):
    before = state.state_hash()

    result = run(state, synthetic(factory(PRIMARY)), InstanceId(9999))

    # **없는 것과 보이지 않는 것을 구분하지 못한다** (Phase 2-N).
    # 관측에 없는 카드를 "이 듀얼에 없다" 고 단정하면 그것 자체가 정보다.
    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.HIDDEN_CARD
    assert result.applied == ()
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_a_later_failure_undoes_nothing_because_nothing_started(state):
    """
    계획을 먼저 다 세운다. 파괴가 멀쩡해도 뒤의 드로우가 걸리면 파괴도
    일어나지 않는다.
    """
    empty = GameState.create(decks=([], []))
    assert len(empty.player(MINE).deck) == 0
    target = my_monster(state)
    state.player(MINE).deck.clear()
    before = state.state_hash()

    result = run(
        state,
        synthetic(CardOperation.destroy(PRIMARY), DrawOperation(count=2)),
        target,
        destruction=confirmed(target),
    )

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert result.deltas == ()
    assert state.locate(target).zone is Zone.MZONE
    assert state.state_hash() == before


def test_a_result_that_did_nothing_cannot_claim_unchecked_rules():
    """
    무엇을 보지 않았는가는 **무엇을 했는가**에서 나온다.
    """
    from engine.effect.resolution import EffectResult

    with pytest.raises(ValueError):
        EffectResult(
            ResolutionStatus.UNSUPPORTED_OPERATION,
            unchecked_rules=("파괴 내성",),
        )


# ======================================================================
# G. 실행 권위 — 의미가 생겼다고 달라지지 않는다
# ======================================================================


@requires_official_db
def test_a_text_derived_destruction_never_runs(state):
    """
    **의미 계층을 만들었다고 ``TEXT_DERIVED`` 가 실행되지 않는다.**
    """
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 7),
        source_card_id=LAB,
        operations=(CardOperation.destroy(PRIMARY),),
        targets=synthetic(CardOperation.destroy(PRIMARY)).targets,
        provenance=EffectProvenance.text_derived("텍스트에서 유추"),
    )
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,))
    )
    before = state.state_hash()

    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref,
            controller=MINE,
            selections=(
                TargetSelection(PRIMARY, Selection(chosen=(my_monster(state),))),
            ),
        ),
    )

    assert result.status is ResolutionStatus.FORBIDDEN
    assert result.unchecked_rules == ()
    assert state.state_hash() == before


@requires_official_db
def test_a_destruction_without_an_implementation_never_runs(state):
    definition = synthetic(CardOperation.destroy(PRIMARY))
    before = state.state_hash()

    result = EffectExecutor().execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref,
            controller=MINE,
            selections=(
                TargetSelection(PRIMARY, Selection(chosen=(my_monster(state),))),
            ),
        ),
    )

    assert result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert state.state_hash() == before


def test_an_unrepresented_operation_is_still_unsupported():
    """
    파괴가 지원 목록에 들어갔다고 아무거나 들어간 것이 아니다.
    """
    assert OperationKind.UNKNOWN not in SUPPORTED
    assert OperationKind.UNKNOWN in UNSUPPORTED_REASON
    assert DESTROY in SUPPORTED


def test_the_library_still_refuses_a_bare_move_as_a_card_effect():
    """Phase 2-L 의 가드가 그대로다."""
    with pytest.raises(EffectDefinitionError):
        LibraryEntry(
            definition=synthetic(MoveOperation(Zone.GRAVE, PRIMARY)),
            lua_file="c2511.lua",
            lua_excerpt="Duel.SendtoGrave(...)",
            executable=True,
        )


# ======================================================================
# H. 결정론 · 체인 경계
# ======================================================================


@requires_official_db
def test_the_same_board_and_meaning_give_the_same_board(repository):
    first, second = new_state(repository), new_state(repository)
    assert first.state_hash() == second.state_hash()

    for board in (first, second):
        target = my_monster(board)
        run(
            board,
            synthetic(CardOperation.destroy(PRIMARY)),
            target,
            destruction=confirmed(target),
        )

    assert first.state_hash() == second.state_hash()


@requires_official_db
def test_the_unchecked_rules_are_the_same_value_every_time(state):
    first_target = my_monster(state)
    first = run(
        state,
        synthetic(CardOperation.destroy(PRIMARY)),
        first_target,
        destruction=confirmed(first_target),
    )
    state.move(
        state.player(MINE).hand[0], Zone.MZONE, to_player=MINE,
        position=Position.FACEUP_ATTACK,
    )
    second_target = my_monster(state)
    second = run(
        state,
        synthetic(CardOperation.destroy(PRIMARY), ordinal=1),
        second_target,
        destruction=confirmed(second_target),
    )

    assert first.unchecked_rules == second.unchecked_rules


@requires_official_db
def test_a_clone_is_destroyed_on_its_own(state):
    copy = state.clone()
    before = state.state_hash()

    run(
        copy,
        synthetic(CardOperation.destroy(PRIMARY)),
        my_monster(copy),
        destruction=confirmed(my_monster(copy)),
    )

    assert state.state_hash() == before
    assert len(state.player(MINE).monster_zone) == 1
    assert len(copy.player(MINE).monster_zone) == 0


@requires_official_db
def test_a_chain_link_can_destroy(state):
    """체인은 무엇을 언제만 정한다. 파괴는 실행기의 일이다."""
    from engine.effect.definition import EffectDefinitionRegistry

    definition = synthetic(CardOperation.destroy(PRIMARY))
    target = my_monster(state)
    resolver = ChainResolver(
        EffectExecutor(
            lookup=EffectImplementationRegistry((definition.effect_ref,)),
            destruction=confirmed(target),
        ),
        EffectDefinitionRegistry((definition,)),
    )
    chain = Chain(
        links=(
            ChainLink(
                sequence=0,
                actor=MINE,
                effect_ref=definition.effect_ref,
                source=target,
                selections=(
                    TargetSelection(PRIMARY, Selection(chosen=(target,))),
                ),
            ),
        )
    )

    resolution = resolver.resolve_top(state, chain)

    assert resolution.status is ChainResolutionStatus.RESOLVED
    assert state.locate(target).zone is Zone.GRAVE
    assert resolution.result.unchecked_rules == UNCHECKED_SEMANTIC_RULES[DESTROY]


def test_the_semantic_layer_touches_no_board_and_no_layer_above_it():
    tree = ast.parse(pathlib.Path("engine/effect/semantics.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    for forbidden in (
        "engine.state.game_state",
        "engine.chain",
        "engine.trigger",
        "engine.event_pipeline",
        "engine.effect.executor",
        "engine.effect.library",
    ):
        assert forbidden not in imported

    # 상태 계층을 **아예** 가져오지 않는다 — 설명문에 이름이 적혀 있는 것과
    # 실제로 쓰는 것은 다르므로 import 로만 본다.
    assert not any(module.startswith("engine.state") for module in imported)

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("move", "draw", "change_life"):
        assert forbidden not in called


def test_the_chain_layer_still_runs_nothing_itself():
    tree = ast.parse(pathlib.Path("engine/chain.py").read_text("utf-8"))
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    for forbidden in ("move", "draw", "change_life", "create_instance"):
        assert forbidden not in attributes


@requires_official_db
def test_the_card_definition_is_untouched_by_a_destruction(state, repository):
    definition = repository.get(FEATHERMAN)
    before = (definition.name, definition.type_mask, definition.atk)

    target = my_monster(state)
    run(
        state,
        synthetic(CardOperation.destroy(PRIMARY)),
        target,
        destruction=confirmed(target),
    )

    assert (definition.name, definition.type_mask, definition.atk) == before
    assert repository.get(FEATHERMAN) is definition


# ======================================================================
# I. 관문 — UNKNOWN 은 허가가 아니다 (STRUCTURAL-47 수정)
# ======================================================================


@requires_official_db
def test_a_destruction_that_cannot_be_judged_does_not_happen(state):
    """
    **이 수정의 핵심이다.**

    내성을 판정할 수 없는데 파괴하면 내성을 가진 카드가 실제로 파괴된다.
    "보지 않았다" 고 적어 두는 메모는 그것을 막지 못한다.
    """
    target = my_monster(state)
    before = state.state_hash()

    result = run(state, synthetic(CardOperation.destroy(PRIMARY)), target)

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.applied == ()
    assert result.deltas == ()
    assert state.state_hash() == before
    assert state.locate(target).zone is Zone.MZONE
    assert len(state.player(MINE).monster_zone) == 1


@requires_official_db
def test_the_refusal_still_says_what_it_could_not_judge(state):
    """멈췄다고 정보가 사라지지 않는다 (§1)."""
    result = run(state, synthetic(CardOperation.destroy(PRIMARY)), my_monster(state))

    assert result.unchecked_rules == UNCHECKED_SEMANTIC_RULES[DESTROY]
    assert "destruction-legality" in (result.missing or "")
    assert any("내성" in rule for rule in GATING_RULES[DESTROY])
    assert any("내성" in text for text in (result.reason,))


def test_the_default_ruling_judges_nothing():
    """
    판정기를 주지 않으면 아무것도 판정하지 못하는 것이 들어간다 —
    ``EmptyImplementationLookup`` 과 같은 자리다 (ADR-006).
    """
    executor = EffectExecutor()

    assert isinstance(executor.destruction, UnknownDestructionRuling)
    assert isinstance(executor.destruction, DestructionRuling)
    assert executor.destruction.may_be_destroyed(InstanceId(1)) is (
        ConditionResult.UNKNOWN
    )


@requires_official_db
def test_a_confirmed_ruling_is_what_lets_the_destruction_happen(state):
    """
    같은 판 · 같은 효과인데 **판정기만 다르다.** 그것이 갈림길이다.
    """
    target = my_monster(state)
    definition = synthetic(CardOperation.destroy(PRIMARY))
    copy = state.clone()

    refused = run(state, definition, target)
    allowed = run(copy, definition, target, destruction=confirmed(target))

    assert refused.status is ResolutionStatus.UNCHECKED_RULES
    assert allowed.status is ResolutionStatus.RESOLVED
    assert state.locate(target).zone is Zone.MZONE
    assert copy.locate(target).zone is Zone.GRAVE


@requires_official_db
def test_a_card_judged_indestructible_is_not_destroyed(state):
    """
    ``FALSE`` 는 ``UNKNOWN`` 과 다른 답이다 — "판정했고 안 된다" 이므로
    "판정하지 못했다" 로 적지 않는다.
    """
    target = my_monster(state)
    before = state.state_hash()
    ruling = DeclaredDestructionRuling(protected=frozenset({target}))

    result = run(
        state, synthetic(CardOperation.destroy(PRIMARY)), target, destruction=ruling
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert result.status is not ResolutionStatus.UNCHECKED_RULES
    assert result.deltas == ()
    assert state.state_hash() == before


def test_a_card_cannot_be_both_destructible_and_protected():
    instance = InstanceId(1)
    with pytest.raises(ValueError):
        DeclaredDestructionRuling(
            destructible=frozenset({instance}), protected=frozenset({instance})
        )


@requires_official_db
def test_one_unjudged_card_stops_the_whole_destruction(state):
    """
    **부분 파괴를 만들지 않는다.** "내성을 가진 한 장만 남고 나머지는
    파괴된다" 는 규칙을 아직 옮기지 못했으므로, 안전한 쪽으로 통째로
    멈춘다 (STRUCTURAL-49).
    """
    state.move(
        state.player(MINE).hand[0], Zone.MZONE, to_player=MINE,
        position=Position.FACEUP_ATTACK,
    )
    judged, unjudged = (card.instance_id for card in state.player(MINE).monster_zone)
    before = state.state_hash()

    result = run(
        state,
        synthetic(CardOperation.destroy(PRIMARY)),
        judged,
        unjudged,
        destruction=confirmed(judged),
    )

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.deltas == ()
    assert state.state_hash() == before
    assert len(state.player(MINE).monster_zone) == 2


@requires_official_db
def test_a_permissive_ruling_cannot_unlock_a_text_derived_effect(state):
    """
    **판정기는 출처 금지를 뚫지 못한다** (ADR-004). 권위 확인이 먼저다.
    """
    target = my_monster(state)
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 8),
        source_card_id=LAB,
        operations=(CardOperation.destroy(PRIMARY),),
        targets=synthetic(CardOperation.destroy(PRIMARY)).targets,
        provenance=EffectProvenance.text_derived("텍스트에서 유추"),
    )
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        destruction=confirmed(target),
    )
    before = state.state_hash()

    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref,
            controller=MINE,
            selections=(TargetSelection(PRIMARY, Selection(chosen=(target,))),),
        ),
    )

    assert result.status is ResolutionStatus.FORBIDDEN
    assert state.state_hash() == before


@requires_official_db
def test_the_chain_does_not_advance_on_an_unjudged_destruction(state):
    """체인이 해결하지 못한 링크를 해결한 것으로 치지 않는다."""
    from engine.effect.definition import EffectDefinitionRegistry

    definition = synthetic(CardOperation.destroy(PRIMARY))
    target = my_monster(state)
    resolver = ChainResolver(
        EffectExecutor(
            lookup=EffectImplementationRegistry((definition.effect_ref,))
        ),
        EffectDefinitionRegistry((definition,)),
    )
    chain = Chain(
        links=(
            ChainLink(
                sequence=0,
                actor=MINE,
                effect_ref=definition.effect_ref,
                source=target,
                selections=(TargetSelection(PRIMARY, Selection(chosen=(target,))),),
            ),
        )
    )
    before = state.state_hash()

    resolution = resolver.resolve_top(state, chain)

    assert resolution.status is ChainResolutionStatus.EFFECT_NOT_APPLIED
    assert resolution.result.status is ResolutionStatus.UNCHECKED_RULES
    assert resolution.chain.resolved_count == 0
    assert state.state_hash() == before


def test_only_destruction_is_gated_for_now():
    """
    보내기와 버리기는 아직 관문이 없다. **알면서 남겨 둔 것**이고
    (STRUCTURAL-48), 괜찮다고 판단한 것이 아니다.
    """
    assert RULE_GATED == {DESTROY}
    assert is_rule_gated(DESTROY)
    assert not is_rule_gated(SEND)
    assert not is_rule_gated(DISCARD)
    assert not is_rule_gated(MOVE)


@requires_official_db
def test_sending_and_discarding_still_run_without_a_ruling(state):
    """관문을 더했다고 다른 의미가 막히지 않는다."""
    for index, operation in enumerate(
        (CardOperation.send_to_grave(PRIMARY), CardOperation.discard(PRIMARY))
    ):
        card = my_hand_card(state)
        result = run(state, synthetic(operation, ordinal=index), card)

        assert result.status is ResolutionStatus.RESOLVED, operation
        assert state.locate(card).zone is Zone.GRAVE


@requires_official_db
def test_the_refusal_is_the_same_value_every_time(repository):
    first, second = new_state(repository), new_state(repository)

    left = run(
        first, synthetic(CardOperation.destroy(PRIMARY)), my_monster(first)
    )
    right = run(
        second, synthetic(CardOperation.destroy(PRIMARY)), my_monster(second)
    )

    assert left.canonical_state() == right.canonical_state()
    assert first.state_hash() == second.state_hash()
