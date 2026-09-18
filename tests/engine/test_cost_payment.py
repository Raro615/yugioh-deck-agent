"""
Phase 2-E — CostPayment.

비용이 **처음으로 실제로 치러진다.** 지금까지 ``engine/cost/`` 는 청구서를
읽고 후보를 세기만 했다.

세 가지를 본다.

1. 낼 수 있을 때만 내는가 (지원 · 가능성 · 선택).
2. 낼 때 **정확히 그만큼만** 내는가 (의미 · 주인 · 장수).
3. 내지 않기로 했으면 **한 글자도** 바뀌지 않는가 — 묶음 중간까지만
   내놓고 멈추는 일이 없는가.

세 번째가 핵심이다. ``CostGroup`` 은 AND 관계라서, 앞의 비용을 내고 뒤에서
막히면 낸 것이 그냥 사라진다.
"""

import json

import pytest

from engine.condition import AttributeIs, PlayerRef
from engine.cost import (
    CardCost,
    CostGroup,
    CostPayment,
    CostSemantics,
    LifeCost,
    Selection,
    UnimplementedCost,
)
from engine.effect import (
    CardMovement,
    EventJournal,
    EventKind,
    LifeChanged,
    OperationKind,
    ZoneMoved,
)
from engine.ids import EffectRef, InstanceId
from engine.payment import (
    SUPPORTED_COSTS,
    CostPayer,
    CostPaymentResult,
    CostSelection,
    PaymentContext,
    PaymentStatus,
)
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Position, Zone

MINE, THEIRS = 0, 1
KUKLOK = 2511


# ======================================================================
# 판
# ======================================================================


def new_state() -> GameState:
    """p0: 패 5장 · 앞면 몬스터 1장 / p1: 패 5장 · 앞면 몬스터 1장."""
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


def my_hand(state, index: int = 0) -> InstanceId:
    return state.player(MINE).hand[index].instance_id


def my_monster(state) -> InstanceId:
    return state.player(MINE).monster_zone[0].instance_id


def steal_to_field(state):
    """상대 카드를 **내가 컨트롤하는** 몬스터 존에. 주인은 그대로 상대다."""
    state.move(state.player(MINE).monster_zone[0], Zone.GRAVE, to_player=MINE)
    card = state.player(THEIRS).monster_zone[0]
    state.move(card, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK)
    assert card.owner == THEIRS and card.controller == MINE
    return card


def context(*selections, payer: int = MINE, effect_ref=None, source=None):
    return PaymentContext(
        payer=payer,
        selections=tuple(selections),
        effect_ref=effect_ref,
        source=source,
    )


def pay(state, group, ctx, journal=None) -> CostPaymentResult:
    return CostPayer(journal).pay(state, group, ctx)


# ======================================================================
# 1~6. 단일 비용
# ======================================================================


def test_a_discard_moves_the_chosen_card_to_the_graveyard(state):
    card = my_hand(state)
    hand = len(state.player(MINE).hand)

    result = pay(state, CostGroup((CardCost.discard(1),)), context(CostSelection(0, Selection.of(card))))

    assert result.status is PaymentStatus.PAID
    assert result.paid is True
    assert result.changed_state is True
    assert state.find_instance(card).zone is Zone.GRAVE
    assert len(state.player(MINE).hand) == hand - 1
    assert result.payments == (
        CostPayment(CostSemantics.DISCARD, (card,), player=MINE),
    )


def test_a_discard_with_nothing_chosen_pays_nothing(state):
    before = state.state_hash()

    result = pay(state, CostGroup((CardCost.discard(1),)), context())

    assert result.status is PaymentStatus.INVALID_SELECTION
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    assert result.deltas == ()
    assert state.state_hash() == before


def test_an_empty_hand_cannot_pay_a_discard(state):
    for card in list(state.player(MINE).hand):
        state.move(card, Zone.REMOVED, to_player=MINE)
    before = state.state_hash()

    result = pay(state, CostGroup((CardCost.discard(1),)), context())

    assert result.status is PaymentStatus.CANNOT_PAY
    assert result.code is ValidationCode.NO_CANDIDATES
    assert result.payments == () and result.deltas == ()
    assert state.state_hash() == before


def test_a_card_on_the_field_cannot_be_discarded(state):
    """
    버리기는 **패에서만** 일어난다. 필드의 카드를 "버렸다" 고 기록하면
    트리거 계층이 틀린 사건을 보게 된다.
    """
    target = my_monster(state)
    before = state.state_hash()

    result = pay(
        state,
        CostGroup((CardCost.discard(1),)),
        context(CostSelection(0, Selection.of(target))),
    )

    assert result.status is PaymentStatus.INVALID_SELECTION
    assert result.deltas == ()
    assert state.find_instance(target).zone is Zone.MZONE
    assert state.state_hash() == before


def test_a_card_that_is_not_in_this_duel_cannot_be_paid(state):
    before = state.state_hash()

    result = pay(
        state,
        CostGroup((CardCost.discard(1),)),
        context(CostSelection(0, Selection.of(InstanceId(9999)))),
    )

    assert result.status in (
        PaymentStatus.INVALID_SELECTION,
        PaymentStatus.UNKNOWN,
    )
    assert result.deltas == ()
    assert state.state_hash() == before


def test_a_life_payment_reduces_life(state):
    before = state.player(MINE).life_points

    result = pay(state, CostGroup((LifeCost(1000),)), context())

    assert result.status is PaymentStatus.PAID
    assert state.player(MINE).life_points == before - 1000
    assert result.payments == (
        CostPayment(CostSemantics.PAY_LIFE, amount=1000, player=MINE),
    )


def test_not_enough_life_pays_nothing(state):
    state.player(MINE).life_points = 800
    before = state.state_hash()

    result = pay(state, CostGroup((LifeCost(1000),)), context())

    assert result.status is PaymentStatus.CANNOT_PAY
    assert result.code is ValidationCode.INSUFFICIENT_LIFE
    assert state.player(MINE).life_points == 800
    assert state.state_hash() == before


def test_paying_exactly_all_remaining_life_is_allowed_and_not_a_loss(state):
    """
    0 이 되어도 되는가는 규칙 계층의 문제다. 여기서는 **남은 값 이상인가**
    만 본다 — 그리고 승패는 판정하지 않는다.
    """
    state.player(MINE).life_points = 1000

    result = pay(state, CostGroup((LifeCost(1000),)), context())

    assert result.status is PaymentStatus.PAID
    assert state.player(MINE).life_points == 0
    assert state.result is None  # 승패 판정은 이 계층의 일이 아니다


def test_a_release_sends_the_monster_to_the_graveyard(state):
    target = my_monster(state)

    result = pay(
        state,
        CostGroup((CardCost.release(1),)),
        context(CostSelection(0, Selection.of(target))),
    )

    assert result.status is PaymentStatus.PAID
    assert state.find_instance(target).zone is Zone.GRAVE
    assert result.payments[0].semantics is CostSemantics.RELEASE


def test_the_opponents_card_is_not_a_candidate_for_my_cost(state):
    """비용은 **자신의** 카드로 낸다. 상대 몬스터를 릴리스할 수 없다."""
    theirs = state.player(THEIRS).monster_zone[0].instance_id
    before = state.state_hash()

    result = pay(
        state,
        CostGroup((CardCost.release(1),)),
        context(CostSelection(0, Selection.of(theirs))),
    )

    assert result.status is PaymentStatus.INVALID_SELECTION
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert state.state_hash() == before


# ======================================================================
# 7~9. CostGroup — AND 이므로 중간까지 내지 않는다
# ======================================================================


def test_a_group_pays_every_cost_in_order(state):
    card = my_hand(state)
    life = state.player(MINE).life_points
    group = CostGroup((CardCost.discard(1), LifeCost(1000)))

    result = pay(state, group, context(CostSelection(0, Selection.of(card))))

    assert result.status is PaymentStatus.PAID
    assert [p.semantics for p in result.payments] == [
        CostSemantics.DISCARD,
        CostSemantics.PAY_LIFE,
    ]
    assert [type(d).__name__ for d in result.deltas] == ["ZoneMoved", "LifeChanged"]
    assert state.find_instance(card).zone is Zone.GRAVE
    assert state.player(MINE).life_points == life - 1000


def test_a_payable_discard_is_not_made_when_the_life_cost_fails(state):
    """
    **가장 중요한 테스트다.** 버릴 수는 있지만 라이프가 모자라면 카드도
    버려지지 않아야 한다. 앞의 비용을 내고 뒤에서 막히면 낸 것이 그냥
    사라진다.
    """
    state.player(MINE).life_points = 500
    card = my_hand(state)
    hand = len(state.player(MINE).hand)
    before = state.state_hash()

    result = pay(
        state,
        CostGroup((CardCost.discard(1), LifeCost(1000))),
        context(CostSelection(0, Selection.of(card))),
    )

    assert result.status is PaymentStatus.CANNOT_PAY
    assert result.code is ValidationCode.INSUFFICIENT_LIFE
    assert result.payments == () and result.deltas == ()
    assert state.find_instance(card).zone is Zone.HAND
    assert len(state.player(MINE).hand) == hand
    assert state.player(MINE).life_points == 500
    assert state.state_hash() == before


def test_a_payable_life_cost_is_not_paid_when_the_selection_fails(state):
    """반대 방향. 라이프는 충분해도 카드 선택이 틀리면 라이프도 그대로다."""
    life = state.player(MINE).life_points
    before = state.state_hash()

    result = pay(
        state,
        CostGroup((LifeCost(1000), CardCost.discard(1))),
        context(CostSelection(1, Selection.of(my_monster(state)))),
    )

    assert result.status is PaymentStatus.INVALID_SELECTION
    assert result.deltas == ()
    assert state.player(MINE).life_points == life
    assert state.state_hash() == before


def test_a_selection_is_bound_to_the_cost_by_its_position(state):
    """
    **자리 번호로 잇는다.** 고를 것이 있는 비용만 세는 방식을 쓰면, 중간에
    비용이 끼거나 빠질 때 선택이 조용히 다른 비용에 붙는다.
    """
    card = my_hand(state)
    group = CostGroup((LifeCost(500), CardCost.discard(1)))

    # 0번(라이프)에 붙이면 1번(버리기)이 비어 있는 것이다.
    wrong = pay(state, group, context(CostSelection(0, Selection.of(card))))
    assert wrong.status is PaymentStatus.INVALID_SELECTION
    assert state.find_instance(card).zone is Zone.HAND

    right = pay(state, group, context(CostSelection(1, Selection.of(card))))
    assert right.status is PaymentStatus.PAID
    assert state.find_instance(card).zone is Zone.GRAVE


def test_the_same_cost_cannot_be_chosen_twice():
    with pytest.raises(ValueError):
        PaymentContext(
            payer=MINE,
            selections=(
                CostSelection(0, Selection.of(InstanceId(1))),
                CostSelection(0, Selection.of(InstanceId(2))),
            ),
        )


def test_an_empty_group_is_paid_without_changing_anything(state, journal):
    before = state.state_hash()

    result = pay(state, CostGroup(), context(), journal)

    assert result.status is PaymentStatus.PAID
    assert result.paid is True
    assert result.changed_state is False
    assert result.deltas == ()
    assert state.state_hash() == before
    assert len(journal) == 0


# ======================================================================
# 10~13. State · Journal
# ======================================================================


def test_a_successful_payment_changes_the_board_hash(state):
    before = state.state_hash()
    pay(
        state,
        CostGroup((CardCost.discard(1),)),
        context(CostSelection(0, Selection.of(my_hand(state)))),
    )
    assert state.state_hash() != before


def test_a_successful_payment_is_recorded_as_a_cost_not_an_effect(state, journal):
    """
    **비용 지불과 효과 해결은 다른 사건이다.** 기록에서 갈려야 "비용으로
    버려졌을 때" 를 나중에 구분할 수 있다.
    """
    card = my_hand(state)
    result = pay(
        state,
        CostGroup((CardCost.discard(1), LifeCost(700))),
        context(
            CostSelection(0, Selection.of(card)),
            effect_ref=EffectRef(KUKLOK, 1),
            source=InstanceId(3),
        ),
        journal,
    )

    assert len(journal) == 1
    event = journal[0]
    assert event.kind is EventKind.COST_PAYMENT
    assert event.sequence == 0
    assert event.actor == MINE
    assert event.effect_ref == EffectRef(KUKLOK, 1)
    assert event.source == InstanceId(3)
    assert event.payments == result.payments
    assert event.deltas == result.deltas
    assert event.instances == (card,)
    assert journal.of_kind(EventKind.COST_PAYMENT) == (event,)
    assert journal.of_kind(EventKind.EFFECT) == ()


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(
            lambda state: (CostGroup((LifeCost(99999),)), context()),
            id="insufficient-life",
        ),
        pytest.param(
            lambda state: (CostGroup((CardCost.discard(1),)), context()),
            id="no-selection",
        ),
        pytest.param(
            lambda state: (
                CostGroup((CardCost.discard(1),)),
                context(CostSelection(0, Selection.of(my_monster(state)))),
            ),
            id="wrong-zone",
        ),
        pytest.param(
            lambda state: (
                CostGroup((UnimplementedCost("엑시즈 소재 제거"),)),
                context(),
            ),
            id="unsupported",
        ),
        pytest.param(
            lambda state: (
                CostGroup((CardCost.banish(frozenset({Zone.GRAVE}), 1),)),
                context(),
            ),
            id="banish-cost",
        ),
    ],
)
def test_every_refusal_leaves_the_board_and_the_history_untouched(
    state, journal, build
):
    group, ctx = build(state)
    before_state = state.state_hash()
    before_journal = journal.canonical_state()

    result = pay(state, group, ctx, journal)

    assert result.status is not PaymentStatus.PAID
    assert result.paid is False
    assert result.payments == ()
    assert result.deltas == ()
    assert state.state_hash() == before_state
    assert journal.canonical_state() == before_journal
    assert len(journal) == 0


def test_a_result_cannot_be_read_as_a_boolean(state):
    result = pay(state, CostGroup((LifeCost(1),)), context())
    with pytest.raises(TypeError):
        bool(result)


def test_a_failed_result_cannot_carry_payments():
    from engine.effect import CardDrawn

    for status in PaymentStatus:
        if status is PaymentStatus.PAID:
            continue
        with pytest.raises(ValueError):
            CostPaymentResult(status, deltas=(CardDrawn(MINE, InstanceId(1)),))
        with pytest.raises(ValueError):
            CostPaymentResult(
                status,
                payments=(CostPayment(CostSemantics.PAY_LIFE, amount=1, player=MINE),),
            )


# ======================================================================
# 14~16. Identity
# ======================================================================


def test_a_cost_card_keeps_its_identity(state):
    card = state.player(MINE).hand[0]
    before = (card.instance_id, card.owner, card.card_id)

    pay(
        state,
        CostGroup((CardCost.discard(1),)),
        context(CostSelection(0, Selection.of(card.instance_id))),
    )

    assert (card.instance_id, card.owner, card.card_id) == before
    assert state.find_instance(before[0]) is card


def test_a_stolen_card_paid_as_a_cost_goes_to_its_owners_graveyard(state, journal):
    """
    Hotfix 의 ``destination = owner`` 가 **비용 경로에도** 적용된다.
    실행기와 같은 표를 쓰므로 둘이 갈리지 않는다.
    """
    card = steal_to_field(state)
    instance_id = card.instance_id

    result = pay(
        state,
        CostGroup((CardCost.release(1),)),
        context(CostSelection(0, Selection.of(instance_id))),
        journal,
    )

    assert result.status is PaymentStatus.PAID
    assert card.owner == THEIRS  # 소유권은 바뀌지 않는다
    assert card.zone is Zone.GRAVE
    assert instance_id in {c.instance_id for c in state.player(THEIRS).grave}
    assert instance_id not in {c.instance_id for c in state.player(MINE).grave}
    assert card.controller == THEIRS  # 도착한 존의 주인

    delta = result.deltas[0]
    assert delta.from_player == MINE and delta.to_player == THEIRS
    assert delta.changed_side is True
    assert journal[0].deltas == result.deltas


def test_no_card_is_created_or_lost_by_a_payment(state):
    before = {card.instance_id for card in state.all_instances()}

    pay(
        state,
        CostGroup((CardCost.discard(2), LifeCost(400))),
        context(CostSelection(0, Selection.of(my_hand(state, 0), my_hand(state, 1)))),
    )

    assert {card.instance_id for card in state.all_instances()} == before


# ======================================================================
# 17~19. Delta — 의미를 잃지 않는다
# ======================================================================


def test_a_discard_cost_records_discard_not_send_to_grave(state):
    card = my_hand(state)

    result = pay(
        state,
        CostGroup((CardCost.discard(1),)),
        context(CostSelection(0, Selection.of(card))),
    )

    delta = result.deltas[0]
    assert isinstance(delta, ZoneMoved)
    assert delta.operation is OperationKind.DISCARD
    assert delta.operation is not OperationKind.SEND_TO_GRAVE
    assert delta.reason_names == ("DISCARD", "EFFECT")
    assert delta.from_zone is Zone.HAND and delta.to_zone is Zone.GRAVE


def test_a_release_cost_records_release_not_send_to_grave(state):
    target = my_monster(state)

    result = pay(
        state,
        CostGroup((CardCost.release(1),)),
        context(CostSelection(0, Selection.of(target))),
    )

    delta = result.deltas[0]
    assert delta.operation is OperationKind.RELEASE
    assert delta.operation is not OperationKind.SEND_TO_GRAVE
    assert delta.reason_names == ("RELEASE",)
    assert delta.to_zone is Zone.GRAVE


def test_discard_and_release_end_alike_but_never_merge(state):
    """목적지가 같아도 같은 사건이 아니다 (ADR-002)."""
    discarded = my_hand(state)
    released = my_monster(state)

    first = pay(
        state,
        CostGroup((CardCost.discard(1),)),
        context(CostSelection(0, Selection.of(discarded))),
    )
    second = pay(
        state,
        CostGroup((CardCost.release(1),)),
        context(CostSelection(0, Selection.of(released))),
    )

    a, b = first.deltas[0], second.deltas[0]
    assert a.to_zone is b.to_zone is Zone.GRAVE
    assert a.operation is not b.operation
    assert a.canonical_state() != b.canonical_state()
    assert first.payments[0].semantics is not second.payments[0].semantics


def test_a_life_payment_records_before_and_after(state):
    state.player(MINE).life_points = 3000

    result = pay(state, CostGroup((LifeCost(1200),)), context())

    delta = result.deltas[0]
    assert isinstance(delta, LifeChanged)
    assert (delta.before, delta.after) == (3000, 1800)
    assert delta.amount == -1200
    assert not isinstance(delta, CardMovement)
    assert state.player(MINE).life_points == delta.after


def test_a_multi_card_cost_makes_one_receipt_and_many_deltas(state):
    first, second = my_hand(state, 0), my_hand(state, 1)

    result = pay(
        state,
        CostGroup((CardCost.discard(2),)),
        context(CostSelection(0, Selection.of(first, second))),
    )

    assert len(result.payments) == 1
    assert result.payments[0].instances == (first, second)
    assert len(result.deltas) == 2
    assert [d.instance for d in result.deltas] == [first, second]


# ======================================================================
# 20. UNKNOWN — 모르는 것을 "일단 지불" 로 바꾸지 않는다
# ======================================================================


def test_an_unjudgeable_requirement_pays_nothing(state):
    """
    카드 정의를 읽을 수 없으면 후보 조건을 판정할 수 없다. 그때 답은
    **모름**이고, 모름은 지불로 바뀌지 않는다.
    """
    cost = CardCost.discard(1, require=AttributeIs("DARK"))
    before = state.state_hash()

    result = pay(
        state,
        CostGroup((cost,)),
        context(CostSelection(0, Selection.of(my_hand(state)))),
    )

    assert result.status is PaymentStatus.UNKNOWN
    assert result.status is not PaymentStatus.CANNOT_PAY
    assert result.code in (
        ValidationCode.INFORMATION_UNAVAILABLE,
        ValidationCode.HIDDEN_CARD,
    )
    assert result.deltas == ()
    assert state.state_hash() == before


def test_a_hidden_card_is_never_paid_and_never_leaks(state):
    """
    상대 패는 내 관측에 통째로 가려져 있다. 그 카드를 비용으로 고르면
    **지불되지 않고**, 그 카드가 무엇인지도 새어 나가지 않는다.

    .. warning::
       지금 돌아오는 상태는 ``CANNOT_PAY`` 다 — 규칙대로라면 **모름**이어야
       한다. ``CandidateResolver`` 가 가려진 존을 통째로 건너뛰기 때문에
       (``resolver.py``: ``if zone_view.concealed: continue``) 후보가 0장으로
       세어지고, ``CostValidator`` 가 그것을 "확실히 못 낸다" 로 읽는다.
       상대 패에 4장이 있는데 "0장뿐" 이라고 말하는 셈이다.

       Phase 2-C 에서 넘어온 문제이고 (STRUCTURAL-15), 고치려면
       ``CandidateSet`` 이 "보이지 않는 후보가 몇 장 있을 수 있는가" 를
       담아야 한다 — 이번 단계의 범위 밖이다. 다만 **지불은 일어나지 않고
       정보도 새지 않는다**, 그 둘을 여기서 고정한다.
    """
    hidden = state.player(THEIRS).hand[0]
    cost = CardCost.discard(1, who=PlayerRef.OPPONENT)
    before = state.state_hash()

    result = pay(
        state,
        CostGroup((cost,)),
        context(CostSelection(0, Selection.of(hidden.instance_id))),
    )

    # 안전 성질 — 이 둘은 반드시 지켜져야 한다.
    assert result.paid is False
    assert result.deltas == () and result.payments == ()
    assert state.state_hash() == before
    assert hidden.zone is Zone.HAND
    text = json.dumps(result.to_dict(), ensure_ascii=False)
    assert str(hidden.card_id) not in text

    # 지금의 (부정확한) 상태. 고쳐지면 UNKNOWN 이 되어야 한다.
    assert result.status is PaymentStatus.CANNOT_PAY
    assert result.code is ValidationCode.NO_CANDIDATES


def test_a_hidden_card_that_passes_as_a_candidate_is_still_not_paid(state):
    """
    후보 판정을 통과하더라도 **고른 카드가 관측에 없으면** 지불하지 않는다.
    이쪽은 제대로 ``UNKNOWN`` 이 나온다 — 있는지 없는지 모르기 때문이다.
    """
    hidden = state.player(THEIRS).hand[0].instance_id
    # 내 패에서 버리는 비용인데 상대 패 카드를 골랐다.
    before = state.state_hash()

    result = pay(
        state,
        CostGroup((CardCost.discard(1),)),
        context(CostSelection(0, Selection.of(hidden))),
    )

    assert result.status is PaymentStatus.UNKNOWN
    assert result.code is ValidationCode.HIDDEN_CARD
    assert result.deltas == ()
    assert state.state_hash() == before


# ======================================================================
# 21~22. 지원하지 않는 비용
# ======================================================================


def test_a_tribute_is_not_representable_and_pays_nothing(state):
    """
    제물 바치기는 소환 절차와 얽혀 있어 이번 단계에서 만들지 않았다.
    ``UnimplementedCost`` 로 **솔직하게** 남고, 지불되지 않는다.
    """
    cost = UnimplementedCost("제물 바치기 (소환 절차)", kind=CostSemantics.RELEASE)
    before = state.state_hash()

    result = pay(state, CostGroup((cost,)), context(), EventJournal())

    assert result.status is PaymentStatus.UNSUPPORTED_COST
    assert result.code is ValidationCode.COST_NOT_IMPLEMENTED
    assert result.missing == "제물 바치기 (소환 절차)"
    assert state.state_hash() == before


@pytest.mark.parametrize(
    "cost",
    [
        CardCost.banish(frozenset({Zone.GRAVE}), 1),
        CardCost.send_to_grave(frozenset({Zone.DECK}), 1),
        CardCost(kind=CostSemantics.DETACH, zones=frozenset({Zone.MZONE})),
    ],
)
def test_unsupported_cost_kinds_are_named_not_guessed(state, cost):
    before = state.state_hash()

    result = pay(
        state,
        CostGroup((cost,)),
        context(CostSelection(0, Selection.of(my_hand(state)))),
    )

    assert result.status is PaymentStatus.UNSUPPORTED_COST
    assert result.missing  # 무엇이 없어서 못 하는지 적혀 있다
    assert cost.semantics not in SUPPORTED_COSTS
    assert state.state_hash() == before


def test_the_supported_set_is_exactly_what_the_step_promised():
    assert SUPPORTED_COSTS == {
        CostSemantics.DISCARD,
        CostSemantics.RELEASE,
        CostSemantics.PAY_LIFE,
    }


# ======================================================================
# 23~24. Determinism
# ======================================================================


def test_the_same_input_gives_the_same_payment_and_the_same_board():
    group = CostGroup((CardCost.discard(1), CardCost.release(1), LifeCost(900)))

    results, states, journals = [], [], []
    for _ in range(2):
        board = new_state()
        book = EventJournal()
        outcome = pay(
            board,
            group,
            context(
                CostSelection(0, Selection.of(my_hand(board))),
                CostSelection(1, Selection.of(my_monster(board))),
            ),
            book,
        )
        results.append(outcome)
        states.append(board)
        journals.append(book)

    assert results[0].status is PaymentStatus.PAID
    assert results[0].canonical_state() == results[1].canonical_state()
    assert [d.canonical_state() for d in results[0].deltas] == [
        d.canonical_state() for d in results[1].deltas
    ]
    assert states[0].state_hash() == states[1].state_hash()
    assert journals[0].journal_hash() == journals[1].journal_hash()


def test_a_payment_record_serializes_to_plain_data(state, journal):
    pay(
        state,
        CostGroup((CardCost.discard(1), LifeCost(600))),
        context(CostSelection(0, Selection.of(my_hand(state)))),
        journal,
    )

    text = json.dumps(journal.to_dict(), ensure_ascii=False)
    assert "0x" not in text and "object at" not in text
    data = journal.to_dict()["events"][0]
    assert data["kind"] == "cost_payment"
    assert [p["semantics"] for p in data["payments"]] == ["discard", "pay_life"]
    assert [d["kind"] for d in data["deltas"]] == ["zone_moved", "life_changed"]


def test_a_journal_is_optional_and_never_changes_the_outcome():
    group = CostGroup((CardCost.discard(1), LifeCost(300)))

    quiet_board = new_state()
    quiet = pay(
        quiet_board, group, context(CostSelection(0, Selection.of(my_hand(quiet_board))))
    )

    loud_board = new_state()
    loud = pay(
        loud_board,
        group,
        context(CostSelection(0, Selection.of(my_hand(loud_board)))),
        EventJournal(),
    )

    assert quiet.canonical_state() == loud.canonical_state()
    assert quiet_board.state_hash() == loud_board.state_hash()


# ======================================================================
# 경계 — 비용과 효과를 합치지 않는다
# ======================================================================


def test_the_payer_refuses_an_observation(state):
    from engine.game_state_view import GameStateView

    view = GameStateView.from_state(state, viewer=MINE)
    with pytest.raises(TypeError):
        CostPayer().pay(view, CostGroup((LifeCost(100),)), context())


def test_a_cost_object_never_changes_the_board(state):
    """
    ``Cost`` · ``ChoiceSpec`` · ``Selection`` 은 어느 것도 판을 바꾸지
    않는다. 바꾸는 것은 :class:`CostPayer` 뿐이다.
    """
    cost = CardCost.discard(1)
    before = state.state_hash()

    cost.choice_spec()
    cost.describe_ko()
    cost.to_dict()
    Selection.of(my_hand(state))

    assert state.state_hash() == before
    for forbidden in ("pay", "apply", "execute", "mutate"):
        assert not hasattr(cost, forbidden), forbidden


def test_a_cost_definition_never_stores_a_chosen_card():
    """
    비용 정의에 ``InstanceId`` 를 박으면 그 정의는 한 판에서 한 번밖에 쓸 수
    없다. 고른 카드는 문맥에 있다.
    """
    cost = CardCost.discard(1)
    text = json.dumps(cost.to_dict(), ensure_ascii=False)
    assert "instance" not in text
