"""engine/state/zones.py — 순서 보존, 이동, clone 독립."""

import pytest

from engine.ids import InstanceId
from engine.state.card_instance import CardInstance
from engine.state.zones import ZoneContainer, move_card
from engine.vocabulary import Position, Zone


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
