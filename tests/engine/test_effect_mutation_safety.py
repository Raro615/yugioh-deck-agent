"""
Phase 2-D-2 Hotfix — mutation 경계의 두 가지 정확성.

**BLOCKER-1** 목적지의 주인을 implicit default 에 맡기지 않는다.
    ``GameState.move`` 의 ``to_player`` 기본값은 **컨트롤러**다. 소유권 기반
    존(묘지 · 제외 · 패 · 덱)으로 보낼 때 그 기본값에 기대면 컨트롤을
    빼앗긴 카드가 빼앗은 쪽으로 간다.

**BLOCKER-2** 모자란 드로우를 부분 적용하지 않는다.
    ``GameState.draw`` 는 있는 만큼만 옮기고 멈추는 primitive 다. 그대로
    부르면 "3장 드로우" 가 조용히 1장이 된다.

두 문제의 공통점은 하나다 — **실패할 수 있는 조건을 바꾸기 전에 검사한다.**
"""

import pytest

from engine.condition import PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.effect import (
    DESTINATION,
    DESTINATION_OWNER,
    PRIMARY_TARGET,
    CardOperation,
    DestinationOwner,
    DrawOperation,
    EffectDefinition,
    EffectExecutor,
    EffectImplementationRegistry,
    EffectProvenance,
    OperationKind,
    ResolutionContext,
    ResolutionStatus,
    TargetBinding,
    TargetSelection,
    TargetSpec,
)
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Position, Zone

KUKLOK = 2511
MINE, THEIRS = 0, 1


# ======================================================================
# 판 — 주인과 컨트롤러가 다른 카드가 반드시 있다
# ======================================================================


def anywhere() -> ChoiceSpec:
    """주인을 가리지 않고 찾는다. 빼앗은 카드도 후보가 되어야 한다."""
    return ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.MZONE, Zone.EMZONE, Zone.HAND, Zone.SZONE}),
            owner=None,
        )
    )


def new_state() -> GameState:
    game = GameState.create(decks=(range(1000, 1030), range(2000, 2030)))
    game.draw(MINE, 5)
    game.draw(THEIRS, 5)
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


def steal_to_field(state: GameState):
    """
    상대 카드 1장을 **내가 컨트롤하는** 몬스터 존에 놓는다.

    ``owner`` 는 그대로 상대다. 이것이 이 파일 전체의 전제다.
    """
    card = state.player(THEIRS).hand[0]
    state.move(card, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK)
    assert card.owner == THEIRS
    assert card.controller == MINE
    return card


def steal_to_hand(state: GameState):
    """상대 카드 1장을 **내 패**에 놓는다. 버리기를 시험하기 위해서다."""
    card = state.player(THEIRS).hand[0]
    state.move(card, Zone.HAND, to_player=MINE)
    assert card.owner == THEIRS and card.controller == MINE
    return card


def run(state: GameState, operation, chosen: InstanceId, ordinal: int = 0):
    definition = EffectDefinition(
        effect_ref=EffectRef(KUKLOK, ordinal),
        source_card_id=KUKLOK,
        targets=TargetBinding.single(TargetSpec.targeting(anywhere())),
        operations=(operation,),
        provenance=EffectProvenance.official_lua(),
    )
    context = ResolutionContext(
        definition.effect_ref,
        controller=MINE,
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(chosen)),),
    )
    executor = EffectExecutor(EffectImplementationRegistry([definition.effect_ref]))
    return executor.execute(state, definition, context)


def holder_of(state: GameState, card) -> int:
    """그 카드가 **누구의** 존에 들어 있는가. 인스턴스가 아니라 판에게 묻는다."""
    for player in (MINE, THEIRS):
        if card.instance_id in {
            held.instance_id for held in state.zone(player, card.zone)
        }:
            return player
    raise AssertionError(f"{card.instance_id} 가 어느 존에도 없습니다.")


# ======================================================================
# 1~9. Owner / controller
# ======================================================================


def test_the_rule_is_written_down_for_every_card_operation():
    """
    "전부 주인" 을 한 줄로 쓰지 않고 일마다 적는다. 소환처럼 **필드로**
    보내는 일이 들어오면 그때는 컨트롤러이고, 그 차이가 표에 드러나야 한다.
    """
    card_kinds = {
        OperationKind.DESTROY,
        OperationKind.SEND_TO_GRAVE,
        OperationKind.RELEASE,
        OperationKind.DISCARD,
        OperationKind.BANISH,
        OperationKind.RETURN_TO_HAND,
        OperationKind.RETURN_TO_DECK,
    }
    assert set(DESTINATION_OWNER) == card_kinds
    assert all(
        rule is DestinationOwner.OWNER for rule in DESTINATION_OWNER.values()
    )
    # 실행하는 일은 전부 목적지의 주인이 정해져 있어야 한다.
    assert set(DESTINATION) <= set(DESTINATION_OWNER)


@pytest.mark.parametrize(
    "factory, destination",
    [
        (CardOperation.send_to_grave, Zone.GRAVE),
        (CardOperation.release, Zone.GRAVE),
        (CardOperation.banish, Zone.REMOVED),
        (CardOperation.return_to_hand, Zone.HAND),
        (CardOperation.return_to_deck, Zone.DECK),
    ],
)
def test_a_stolen_card_goes_to_its_owners_zone(state, factory, destination):
    """
    **소유권 기반 존은 언제나 주인 쪽이다.**

    내가 컨트롤하고 있어도, 내가 발동한 효과여도, 카드는 주인에게 돌아간다.
    """
    card = steal_to_field(state)
    instance_id, owner = card.instance_id, card.owner

    result = run(state, factory(PRIMARY_TARGET), instance_id)

    assert result.status is ResolutionStatus.RESOLVED
    assert card.zone is destination
    assert holder_of(state, card) == THEIRS
    assert card.instance_id == instance_id
    assert card.owner == owner == THEIRS
    # 내 쪽 존에는 흔적이 없어야 한다.
    assert instance_id not in {
        held.instance_id for held in state.zone(MINE, destination)
    }


def test_a_stolen_card_is_discarded_to_its_owners_graveyard(state):
    """버리기도 같다. 내 패에 있던 상대 카드는 **상대** 묘지로 간다."""
    card = steal_to_hand(state)
    instance_id = card.instance_id

    result = run(state, CardOperation.discard(PRIMARY_TARGET), instance_id)

    assert result.status is ResolutionStatus.RESOLVED
    assert card.zone is Zone.GRAVE
    assert holder_of(state, card) == THEIRS
    assert card.owner == THEIRS
    assert card.instance_id == instance_id
    assert len(state.player(MINE).grave) == 0


def test_an_effect_never_changes_who_owns_a_card(state):
    """
    **소유권은 이 단계에서 바뀌지 않는다.** 목적지만 고를 뿐이다.
    """
    card = steal_to_field(state)
    before = (card.instance_id, card.owner, card.card_id)

    run(state, CardOperation.banish(PRIMARY_TARGET), card.instance_id)

    assert (card.instance_id, card.owner, card.card_id) == before


def test_the_controller_follows_the_zone_it_lands_in_as_before(state):
    """
    컨트롤러 정책은 기존 규칙 그대로다 — 카드는 자기가 들어간 존의 주인이
    컨트롤한다 (``ZoneContainer._sync_from``). 실행기가 이것을 바꾸지 않는다.

    직접 ``GameState.move`` 를 부른 경우와 효과로 옮긴 경우가 **같아야**
    한다.
    """
    by_hand = new_state()
    stolen = steal_to_field(by_hand)
    by_hand.move(stolen, Zone.GRAVE, to_player=stolen.owner)

    by_effect = new_state()
    moved = steal_to_field(by_effect)
    run(by_effect, CardOperation.send_to_grave(PRIMARY_TARGET), moved.instance_id)

    assert stolen.controller == moved.controller == THEIRS
    assert stolen.zone is moved.zone is Zone.GRAVE
    assert by_hand.state_hash() == by_effect.state_hash()


def test_a_card_i_own_still_goes_to_my_own_zone(state):
    """당연한 쪽도 확인한다. 주인 기준이 "언제나 상대" 가 되면 안 된다."""
    mine = state.player(MINE).hand[0]

    result = run(state, CardOperation.send_to_grave(PRIMARY_TARGET), mine.instance_id)

    assert result.status is ResolutionStatus.RESOLVED
    assert holder_of(state, mine) == MINE
    assert mine.owner == mine.controller == MINE


def test_both_players_cards_in_one_effect_go_to_their_own_owners(state):
    """
    한 번의 해결에서 여러 장을 옮길 때 **장마다** 주인을 본다. 첫 장의
    주인으로 전부 보내지 않는다.
    """
    stolen = steal_to_field(state)
    mine = state.player(MINE).hand[0]

    definition = EffectDefinition(
        effect_ref=EffectRef(KUKLOK, 0),
        source_card_id=KUKLOK,
        targets=TargetBinding.single(TargetSpec.targeting(anywhere())),
        operations=(CardOperation.banish(PRIMARY_TARGET),),
        provenance=EffectProvenance.official_lua(),
    )
    context = ResolutionContext(
        definition.effect_ref,
        controller=MINE,
        selections=(
            TargetSelection(
                PRIMARY_TARGET, Selection.of(stolen.instance_id, mine.instance_id)
            ),
        ),
    )
    executor = EffectExecutor(EffectImplementationRegistry([definition.effect_ref]))
    result = executor.execute(state, definition, context)

    assert result.status is ResolutionStatus.RESOLVED
    assert holder_of(state, stolen) == THEIRS
    assert holder_of(state, mine) == MINE


def test_relying_on_the_default_would_send_it_to_the_wrong_player(state):
    """
    이 테스트는 **기본값이 왜 위험한가**를 고정한다.

    ``to_player`` 를 주지 않으면 ``GameState.move`` 는 컨트롤러를 쓰고,
    빼앗은 카드는 빼앗은 쪽 묘지로 간다. 실행기는 그 경로를 쓰지 않는다.
    """
    naive = new_state()
    stolen = steal_to_field(naive)
    naive.move(stolen, Zone.GRAVE)  # 기본값 = 컨트롤러
    assert holder_of(naive, stolen) == MINE  # ← 규칙상 틀린 결과

    correct = new_state()
    card = steal_to_field(correct)
    run(correct, CardOperation.send_to_grave(PRIMARY_TARGET), card.instance_id)
    assert holder_of(correct, card) == THEIRS  # ← 실행기가 내는 결과


def test_a_card_sent_to_a_hidden_zone_disappears_from_the_view(state):
    """
    이동은 정보를 새게 하지 않는다. 상대 덱으로 돌아간 카드는 **관측에
    아예 없다** — 가려진 정보는 표시되는 것이 아니라 없는 것이다.

    장수는 보인다. "빈 덱" 과 "안 보이는 덱" 은 다르기 때문이다.
    """
    from engine.game_state_view import GameStateView

    card = steal_to_field(state)
    before = GameStateView.from_state(state, viewer=MINE).player(THEIRS).deck.size

    run(state, CardOperation.return_to_deck(PRIMARY_TARGET), card.instance_id)

    view = GameStateView.from_state(state, viewer=MINE)
    assert view.find(card.instance_id) is None
    deck = view.player(THEIRS).deck
    assert deck.concealed is True
    assert deck.cards == ()
    assert deck.size == before + 1


# ======================================================================
# 10~16. Draw
# ======================================================================


def draw_definition(count: int, who: PlayerRef = PlayerRef.CONTROLLER, ordinal: int = 0):
    return EffectDefinition(
        effect_ref=EffectRef(KUKLOK, ordinal),
        source_card_id=KUKLOK,
        operations=(DrawOperation(count, who=who),),
        provenance=EffectProvenance.official_lua(),
    )


def run_draw(state: GameState, definition: EffectDefinition):
    context = ResolutionContext(definition.effect_ref, controller=MINE)
    executor = EffectExecutor(EffectImplementationRegistry([definition.effect_ref]))
    return executor.execute(state, definition, context)


def empty_the_deck(state: GameState, leave: int) -> None:
    """내 덱에 ``leave`` 장만 남긴다."""
    deck = state.player(MINE).deck
    while len(deck) > leave:
        state.move(deck[0], Zone.REMOVED, to_player=MINE)
    assert len(state.player(MINE).deck) == leave


def test_a_draw_that_fits_the_deck_succeeds(state):
    empty_the_deck(state, 3)
    hand = len(state.player(MINE).hand)

    result = run_draw(state, draw_definition(3))

    assert result.status is ResolutionStatus.RESOLVED
    assert len(state.player(MINE).hand) == hand + 3
    assert len(state.player(MINE).deck) == 0
    assert len(result.applied[0].instances) == 3


def test_a_draw_larger_than_the_deck_fails_explicitly(state):
    empty_the_deck(state, 1)

    result = run_draw(state, draw_definition(3))

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert result.code is ValidationCode.INSUFFICIENT_DECK
    assert result.status is not ResolutionStatus.RESOLVED
    assert result.changed_state is False
    assert result.applied == ()
    # 무엇이 없어서 거절했는지 남긴다. 덱 데스 규칙은 아직 없다.
    assert result.missing == "deck-out rule (Phase 2-G)"


def test_a_short_draw_leaves_the_board_byte_identical(state):
    empty_the_deck(state, 1)
    before = state.state_hash()

    run_draw(state, draw_definition(3))

    assert state.state_hash() == before


def test_a_short_draw_leaves_the_hand_untouched(state):
    empty_the_deck(state, 1)
    hand = [card.instance_id for card in state.player(MINE).hand]

    run_draw(state, draw_definition(3))

    assert [card.instance_id for card in state.player(MINE).hand] == hand


def test_a_short_draw_leaves_the_deck_untouched(state):
    """
    **한 장도 뽑지 않는다.** 남은 1장이 손패로 새어 나가면 부분 적용이다.
    """
    empty_the_deck(state, 1)
    deck = [card.instance_id for card in state.player(MINE).deck]

    run_draw(state, draw_definition(3))

    assert [card.instance_id for card in state.player(MINE).deck] == deck
    assert len(state.player(MINE).deck) == 1


def test_an_empty_deck_refuses_even_a_single_draw(state):
    empty_the_deck(state, 0)
    before = state.state_hash()

    result = run_draw(state, draw_definition(1))

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert state.state_hash() == before


def test_the_opponents_deck_is_the_one_that_is_counted(state):
    """
    상대에게 뽑게 하는 효과는 **상대** 덱을 센다. 내 덱이 두꺼워도 소용없다.
    """
    deck = state.player(THEIRS).deck
    while len(deck) > 1:
        state.move(deck[0], Zone.REMOVED, to_player=THEIRS)
    before = state.state_hash()

    result = run_draw(state, draw_definition(3, who=PlayerRef.OPPONENT))

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert state.state_hash() == before


@pytest.mark.parametrize("count", [0, -1, -5])
def test_a_meaningless_draw_count_cannot_even_be_written(count):
    """
    0장 · 음수 드로우는 **만들어지지도 않는다.** 가장 이른 곳에서 막는 것이
    가장 안전하다.
    """
    with pytest.raises(ValueError):
        DrawOperation(count)


@pytest.mark.parametrize("count", [0, -3])
def test_a_meaningless_draw_count_is_refused_at_execution_too(state, count):
    """
    생성 방어를 우회해서 들어온 값도 조용히 통과시키지 않는다.
    ``UNKNOWN`` 도 ``UNSUPPORTED`` 도 아닌 **잘못된 일**이다.
    """
    operation = DrawOperation(1)
    object.__setattr__(operation, "count", count)  # 방어를 우회한다
    definition = EffectDefinition(
        effect_ref=EffectRef(KUKLOK, 0),
        source_card_id=KUKLOK,
        operations=(operation,),
        provenance=EffectProvenance.official_lua(),
    )
    before = state.state_hash()

    result = run_draw(state, definition)

    assert result.status is ResolutionStatus.INVALID_OPERATION
    assert result.code is ValidationCode.INVALID_AMOUNT
    assert result.applied == ()
    assert state.state_hash() == before


# ======================================================================
# 17. 순서 — 검사가 먼저, 변경이 나중
# ======================================================================


def test_a_short_draw_after_a_valid_move_applies_neither(state):
    """
    **mutation-before-validation 이 아님을 고정한다.**

    첫 일(제외)은 멀쩡하지만 두 번째 일(드로우)이 계획에서 걸린다. 계획이
    실패하면 적용은 시작도 하지 않으므로 제외도 일어나지 않는다.
    """
    empty_the_deck(state, 1)
    card = steal_to_field(state)
    before = state.state_hash()

    definition = EffectDefinition(
        effect_ref=EffectRef(KUKLOK, 0),
        source_card_id=KUKLOK,
        targets=TargetBinding.single(TargetSpec.targeting(anywhere())),
        operations=(CardOperation.banish(PRIMARY_TARGET), DrawOperation(3)),
        provenance=EffectProvenance.official_lua(),
    )
    context = ResolutionContext(
        definition.effect_ref,
        controller=MINE,
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(card.instance_id)),),
    )
    executor = EffectExecutor(EffectImplementationRegistry([definition.effect_ref]))
    result = executor.execute(state, definition, context)

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert card.zone is Zone.MZONE
    assert state.state_hash() == before


def test_a_bad_target_after_a_valid_draw_applies_neither(state):
    """반대 방향. 드로우가 먼저 적혀 있어도 뒤의 대상이 틀리면 뽑지 않는다."""
    hand = len(state.player(MINE).hand)
    before = state.state_hash()

    definition = EffectDefinition(
        effect_ref=EffectRef(KUKLOK, 0),
        source_card_id=KUKLOK,
        targets=TargetBinding.single(TargetSpec.targeting(anywhere())),
        operations=(DrawOperation(2), CardOperation.banish(PRIMARY_TARGET)),
        provenance=EffectProvenance.official_lua(),
    )
    context = ResolutionContext(
        definition.effect_ref,
        controller=MINE,
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(9999))),),
    )
    executor = EffectExecutor(EffectImplementationRegistry([definition.effect_ref]))
    result = executor.execute(state, definition, context)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert len(state.player(MINE).hand) == hand
    assert state.state_hash() == before


def test_operation_identity_survives_the_hotfix(state):
    """
    목적지와 주인이 같아도 **같은 사건이 아니다.** 릴리스 · 묘지로 보내기 ·
    버리기가 전부 주인의 묘지로 가지만 기록은 서로 다르다.
    """
    records = []
    for ordinal, (factory, chosen) in enumerate(
        [
            (CardOperation.send_to_grave, "field"),
            (CardOperation.release, "field"),
            (CardOperation.discard, "hand"),
        ]
    ):
        board = new_state()
        card = steal_to_field(board) if chosen == "field" else steal_to_hand(board)
        result = run(board, factory(PRIMARY_TARGET), card.instance_id, ordinal=ordinal)
        assert result.status is ResolutionStatus.RESOLVED
        assert holder_of(board, card) == THEIRS
        records.append(result.applied[0])

    kinds = [record.kind for record in records]
    assert kinds == [
        OperationKind.SEND_TO_GRAVE,
        OperationKind.RELEASE,
        OperationKind.DISCARD,
    ]
    assert len({record.reason_names for record in records}) == 3
