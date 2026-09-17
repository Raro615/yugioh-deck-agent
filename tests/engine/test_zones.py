"""engine/state/zones.py — 순서 보존, 이동, clone 독립."""

import pytest

from engine.ids import InstanceId
from engine.state.card_instance import CardInstance
from engine.state.zones import ZoneContainer, ZoneFull, move_card
from engine.vocabulary import Position, Zone, ZoneKind, ZoneVisibility


def make_cards(count: int, zone: Zone = Zone.DECK, owner: int = 0):
    return [
        CardInstance(
            instance_id=InstanceId(i),
            card_id=1000 + i,
            owner=owner,
            controller=owner,
            zone=zone,
        )
        for i in range(count)
    ]


def test_append_keeps_order_and_syncs_sequence():
    container = ZoneContainer(Zone.DECK, owner=0)
    cards = make_cards(3)
    container.extend(cards)

    assert len(container) == 3
    assert container.card_ids() == [1000, 1001, 1002]
    assert [c.sequence for c in container] == [0, 1, 2]
    assert all(c.zone is Zone.DECK for c in container)


def test_insert_at_top_shifts_the_rest():
    container = ZoneContainer(Zone.DECK, owner=0)
    container.extend(make_cards(3))
    newcomer = CardInstance(
        instance_id=InstanceId(99), card_id=7, owner=0, controller=0, zone=Zone.HAND
    )
    container.insert(0, newcomer)

    assert container.card_ids() == [7, 1000, 1001, 1002]
    assert [c.sequence for c in container] == [0, 1, 2, 3]
    assert container.top() is newcomer
    assert newcomer.zone is Zone.DECK


def test_remove_resequences_the_remainder():
    container = ZoneContainer(Zone.DECK, owner=0)
    cards = make_cards(4)
    container.extend(cards)
    container.remove(cards[1])

    assert container.card_ids() == [1000, 1002, 1003]
    assert [c.sequence for c in container] == [0, 1, 2]


def test_remove_accepts_an_instance_id():
    container = ZoneContainer(Zone.GRAVE, owner=0)
    cards = make_cards(2)
    container.extend(cards)
    removed = container.remove(InstanceId(0))
    assert removed is cards[0]


def test_remove_missing_card_raises():
    container = ZoneContainer(Zone.GRAVE, owner=0)
    with pytest.raises(KeyError):
        container.remove(InstanceId(5))


def test_pop_defaults_to_the_back_and_pop_zero_is_the_top():
    container = ZoneContainer(Zone.DECK, owner=0)
    container.extend(make_cards(3))
    assert container.pop().card_id == 1002
    assert container.pop(0).card_id == 1000
    assert container.card_ids() == [1001]


def test_pop_from_empty_zone_raises():
    with pytest.raises(IndexError):
        ZoneContainer(Zone.DECK, owner=0).pop()


def test_membership_and_iteration_and_indexing():
    container = ZoneContainer(Zone.HAND, owner=0)
    cards = make_cards(2)
    container.extend(cards)

    assert cards[0] in container
    assert InstanceId(1) in container
    assert InstanceId(42) not in container
    assert "not a card" not in container
    assert [c.card_id for c in container] == [1000, 1001]
    assert container[0] is cards[0]
    assert container.find(InstanceId(1)) is cards[1]
    assert container.find(InstanceId(42)) is None
    assert container.index(cards[1]) == 1


def test_container_owner_sets_controller():
    container = ZoneContainer(Zone.MZONE, owner=1)
    card = make_cards(1)[0]  # owner=0 으로 만들었다
    container.append(card)
    assert card.controller == 1
    assert card.owner == 0  # 소유자는 바뀌지 않는다


def test_move_card_preserves_counts_and_records_previous():
    deck = ZoneContainer(Zone.DECK, owner=0)
    hand = ZoneContainer(Zone.HAND, owner=0)
    cards = make_cards(5)
    deck.extend(cards)

    move_card(cards[0], deck, hand)

    assert len(deck) == 4
    assert len(hand) == 1
    assert cards[0].zone is Zone.HAND
    assert cards[0].previous.location is Zone.DECK
    assert deck.card_ids() == [1001, 1002, 1003, 1004]
    assert [c.sequence for c in deck] == [0, 1, 2, 3]


def test_move_card_can_set_a_position_without_losing_previous():
    deck = ZoneContainer(Zone.DECK, owner=0)
    field = ZoneContainer(Zone.MZONE, owner=0)
    card = make_cards(1)[0]
    card.position = Position.FACEDOWN
    deck.append(card)

    move_card(card, deck, field, position=Position.FACEUP_ATTACK)

    assert card.position is Position.FACEUP_ATTACK
    assert card.previous.location is Zone.DECK
    assert card.previous.position is Position.FACEDOWN


def test_move_card_to_a_specific_index():
    grave = ZoneContainer(Zone.GRAVE, owner=0)
    deck = ZoneContainer(Zone.DECK, owner=0)
    deck.extend(make_cards(3))
    buried = grave  # 묘지에서 덱 맨 위로 되돌리는 효과의 모양
    card = deck.pop()
    buried.append(card)

    move_card(card, buried, deck, index=0)
    assert deck.top() is card
    assert len(buried) == 0


def test_clone_is_independent():
    container = ZoneContainer(Zone.DECK, owner=0)
    container.extend(make_cards(3))
    copy = container.clone()

    copy.pop()
    copy[0].add_counter("SPELL")

    assert len(container) == 3
    assert len(copy) == 2
    assert container[0].counter("SPELL") == 0
    assert copy[0].counter("SPELL") == 1
    assert container[0] is not copy[0]


def test_clone_preserves_order():
    container = ZoneContainer(Zone.DECK, owner=0)
    container.extend(make_cards(10))
    assert container.clone().card_ids() == container.card_ids()


def test_canonical_state_reflects_order():
    a = ZoneContainer(Zone.DECK, owner=0)
    b = ZoneContainer(Zone.DECK, owner=0)
    a.extend(make_cards(3))
    b.extend(make_cards(3))
    assert a.canonical_state() == b.canonical_state()

    b.insert(0, b.pop())
    assert a.canonical_state() != b.canonical_state()


# ----------------------------------------------------------------------
# §8/§23 칸 방식 존 — 가운데가 비어도 양옆이 밀려나지 않는다
# ----------------------------------------------------------------------


def test_zone_declares_its_kind_capacity_and_visibility():
    deck = ZoneContainer(Zone.DECK, owner=0)
    monsters = ZoneContainer(Zone.MZONE, owner=0)

    assert deck.kind is ZoneKind.ORDERED
    assert deck.capacity is None
    assert deck.visibility is ZoneVisibility.HIDDEN
    assert not deck.is_slotted

    assert monsters.kind is ZoneKind.SLOTTED
    assert monsters.capacity == 5
    assert monsters.visibility is ZoneVisibility.PUBLIC
    assert monsters.is_slotted


def test_slotted_zone_starts_with_every_slot_empty():
    monsters = ZoneContainer(Zone.MZONE, owner=0)
    assert monsters.slots() == [None] * 5
    assert monsters.free_slots() == [0, 1, 2, 3, 4]
    assert len(monsters) == 0


def test_place_puts_a_card_in_the_slot_you_asked_for():
    monsters = ZoneContainer(Zone.MZONE, owner=0)
    (card,) = make_cards(1, zone=Zone.MZONE)
    monsters.place(3, card)

    assert monsters.slot(3) is card
    assert monsters.free_slots() == [0, 1, 2, 4]
    assert card.sequence == 3  # sequence 는 칸 번호다
    assert len(monsters) == 1


def test_removing_from_the_middle_leaves_a_hole():
    """몬스터 존 1번이 비었다고 2번 몬스터가 1번으로 당겨지면 안 된다."""
    monsters = ZoneContainer(Zone.MZONE, owner=0)
    cards = make_cards(3, zone=Zone.MZONE)
    for index, card in enumerate(cards):
        monsters.place(index, card)

    monsters.remove(cards[1])

    assert monsters.slots() == [cards[0], None, cards[2], None, None]
    assert cards[2].sequence == 2
    assert monsters.free_slots() == [1, 3, 4]


def test_append_to_a_slotted_zone_takes_the_lowest_free_slot():
    monsters = ZoneContainer(Zone.MZONE, owner=0)
    cards = make_cards(3, zone=Zone.MZONE)
    monsters.place(2, cards[0])
    monsters.append(cards[1])
    monsters.append(cards[2])

    assert monsters.slots() == [cards[1], cards[2], cards[0], None, None]


def test_insert_into_a_slotted_zone_does_not_shift_slots():
    """순서 존의 insert 와 달리 칸은 밀리지 않는다 — place 와 같은 뜻이다."""
    monsters = ZoneContainer(Zone.MZONE, owner=0)
    cards = make_cards(2, zone=Zone.MZONE)
    monsters.place(1, cards[0])
    monsters.insert(0, cards[1])

    assert monsters.slots() == [cards[1], cards[0], None, None, None]


def test_occupied_slot_is_refused():
    monsters = ZoneContainer(Zone.MZONE, owner=0)
    cards = make_cards(2, zone=Zone.MZONE)
    monsters.place(0, cards[0])
    with pytest.raises(ZoneFull):
        monsters.place(0, cards[1])


def test_a_full_slotted_zone_refuses_more_cards():
    """
    이것은 **규칙 판정이 아니라 표현 불가**다. "소환해도 되는가" 는 Phase 4 이고,
    여기서는 6번째 몬스터가 있는 존재할 수 없는 상태를 막을 뿐이다.
    """
    monsters = ZoneContainer(Zone.MZONE, owner=0)
    cards = make_cards(6, zone=Zone.MZONE)
    for card in cards[:5]:
        monsters.append(card)

    assert monsters.is_full
    with pytest.raises(ZoneFull):
        monsters.append(cards[5])


def test_out_of_range_slot_is_an_index_error_not_a_silent_append():
    monsters = ZoneContainer(Zone.MZONE, owner=0)
    (card,) = make_cards(1, zone=Zone.MZONE)
    with pytest.raises(IndexError):
        monsters.place(5, card)


def test_extra_monster_zone_holds_exactly_one_card():
    emz = ZoneContainer(Zone.EMZONE, owner=0)
    cards = make_cards(2, zone=Zone.EMZONE)
    assert emz.capacity == 1
    emz.append(cards[0])
    assert emz.is_full
    with pytest.raises(ZoneFull):
        emz.append(cards[1])


def test_ordered_zones_have_no_slots():
    deck = ZoneContainer(Zone.DECK, owner=0)
    (card,) = make_cards(1)
    assert deck.free_slots() == []
    with pytest.raises(TypeError):
        deck.slots()
    with pytest.raises(TypeError):
        deck.slot(0)
    with pytest.raises(TypeError):
        deck.place(0, card)


def test_extra_deck_is_ordered_but_still_capped():
    extra = ZoneContainer(Zone.EXTRA, owner=0)
    cards = make_cards(16, zone=Zone.EXTRA)
    for card in cards[:15]:
        extra.append(card)
    assert extra.kind is ZoneKind.ORDERED
    assert extra.is_full
    with pytest.raises(ZoneFull):
        extra.insert(0, cards[15])


def test_slotted_clone_keeps_the_holes():
    monsters = ZoneContainer(Zone.MZONE, owner=0)
    cards = make_cards(2, zone=Zone.MZONE)
    monsters.place(0, cards[0])
    monsters.place(4, cards[1])

    copy = monsters.clone()
    assert [None if c is None else c.card_id for c in copy.slots()] == [
        cards[0].card_id,
        None,
        None,
        None,
        cards[1].card_id,
    ]
    assert copy[0] is not cards[0]


def test_canonical_state_distinguishes_which_slots_are_occupied():
    """0·2번에 놓인 판과 0·1번에 놓인 판은 서로 다른 상태다."""
    a = ZoneContainer(Zone.MZONE, owner=0)
    b = ZoneContainer(Zone.MZONE, owner=0)
    for index, container in ((2, a), (1, b)):
        cards = make_cards(2, zone=Zone.MZONE)
        container.place(0, cards[0])
        container.place(index, cards[1])

    assert a.canonical_state() != b.canonical_state()
    assert len(a.canonical_state()[2]) == 5  # 빈 칸까지 표현한다


def test_move_card_into_a_specific_monster_zone_slot():
    hand = ZoneContainer(Zone.HAND, owner=0)
    monsters = ZoneContainer(Zone.MZONE, owner=0)
    (card,) = make_cards(1, zone=Zone.HAND)
    hand.append(card)

    move_card(card, hand, monsters, index=3, position=Position.FACEUP_ATTACK)

    assert monsters.slot(3) is card
    assert card.sequence == 3
    assert card.previous.location is Zone.HAND
    assert len(hand) == 0


def test_the_same_card_cannot_occupy_two_slots_at_once():
    """
    칸을 지정해 넣을 때 이미 그 존에 있는 카드인지 보지 않으면, 같은 카드가
    두 칸에 동시에 나타나고 ``len()`` 이 2를 돌려준다. 규칙 위반이 아니라
    **표현할 수 없는 상태**이므로 자료구조가 막는다.
    """
    monsters = ZoneContainer(Zone.MZONE, owner=0)
    (card,) = make_cards(1, zone=Zone.MZONE)
    monsters.place(4, card)

    with pytest.raises(ZoneFull):
        monsters.place(3, card)
    with pytest.raises(ZoneFull):
        monsters.insert(3, card)

    assert len(monsters) == 1
    assert monsters.slots() == [None, None, None, None, card]


def test_moving_within_a_slotted_zone_works_once_the_card_is_removed():
    """막는 것은 중복이지 이동이 아니다."""
    monsters = ZoneContainer(Zone.MZONE, owner=0)
    (card,) = make_cards(1, zone=Zone.MZONE)
    monsters.place(4, card)

    monsters.remove(card)
    monsters.place(3, card)

    assert monsters.slots() == [None, None, None, card, None]
    assert card.sequence == 3
