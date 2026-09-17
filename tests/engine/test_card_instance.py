"""engine/state/card_instance.py — 정의 참조, 상태 변경, previous, clone 독립."""

import pytest

from core.card_model import Card
from engine.ids import EffectRef, InstanceId
from engine.state.card_instance import AppliedEffect, CardInstance, PreviousState
from engine.vocabulary import Position, Zone


class FakeRepository:
    """``CardRepository.get`` 만 흉내 낸다 (같은 객체를 계속 돌려준다)."""

    def __init__(self, card: Card):
        self._card = card

    def get(self, card_id: int) -> Card | None:
        return self._card if card_id == self._card.id else None


def make_instance(**kwargs) -> CardInstance:
    defaults = dict(
        instance_id=InstanceId(0),
        card_id=2511,
        owner=0,
        controller=0,
        zone=Zone.DECK,
    )
    defaults.update(kwargs)
    return CardInstance(**defaults)


def test_definition_is_a_reference_not_a_copy():
    card = Card(id=2511, name="라뷰린스 쿠클락")
    instance = make_instance().bind(FakeRepository(card))
    assert instance.definition is card
    assert instance.name == "라뷰린스 쿠클락"


def test_instance_does_not_carry_definition_fields():
    """정의 필드를 인스턴스에 복사해두면 곧 원본과 어긋난다."""
    instance = make_instance()
    for forbidden in ("name", "atk", "defense", "level", "type_mask", "desc"):
        if forbidden == "name":
            continue  # name 은 정의를 그때그때 읽는 프로퍼티다
        assert not hasattr(instance, forbidden), f"{forbidden} 를 들고 있으면 안 된다"


def test_definition_without_repository_is_an_explicit_error():
    instance = make_instance()
    with pytest.raises(RuntimeError):
        instance.definition
    assert instance.name == "2511"  # 이름은 카드 ID 로 대신한다


def test_definition_missing_from_repository_is_an_explicit_error():
    instance = make_instance(card_id=999999).bind(FakeRepository(Card(id=2511)))
    with pytest.raises(KeyError):
        instance.definition


def test_place_records_previous_state():
    instance = make_instance(zone=Zone.MZONE, position=Position.FACEUP_ATTACK)
    instance.place(Zone.GRAVE, position=Position.FACEUP)

    assert instance.zone is Zone.GRAVE
    assert instance.position is Position.FACEUP
    assert instance.previous.location is Zone.MZONE
    assert instance.previous.position is Position.FACEUP_ATTACK
    assert instance.previous.controller == 0


def test_place_can_skip_previous_state():
    instance = make_instance(zone=Zone.MZONE)
    instance.place(Zone.GRAVE, remember_previous=False)
    assert instance.previous == PreviousState()


def test_set_controller_records_previous_controller():
    instance = make_instance(zone=Zone.MZONE, controller=0)
    instance.set_controller(1)
    assert instance.controller == 1
    assert instance.previous.controller == 0


def test_previous_state_is_immutable():
    previous = PreviousState(location=Zone.HAND)
    with pytest.raises(Exception):
        previous.location = Zone.DECK  # type: ignore[misc]


def test_counters():
    instance = make_instance()
    assert instance.counter("SPELL") == 0
    instance.add_counter("spell", 2)
    assert instance.counter("SPELL") == 2
    instance.remove_counter("SPELL")
    assert instance.counter("SPELL") == 1
    instance.remove_counter("SPELL", 5)
    assert instance.counter("SPELL") == 0
    assert "SPELL" not in instance.counters


def test_status_flags_are_bitmask_operations():
    instance = make_instance()
    instance.set_status(0b0101)
    assert instance.has_status(0b0100)
    instance.clear_status(0b0100)
    assert not instance.has_status(0b0100)
    assert instance.has_status(0b0001)


def test_is_faceup():
    assert make_instance(position=Position.FACEUP_ATTACK).is_faceup
    assert make_instance(position=Position.FACEUP_DEFENSE).is_faceup
    assert not make_instance(position=Position.FACEDOWN_DEFENSE).is_faceup


def test_clone_is_independent():
    card = Card(id=2511, name="원본")
    original = make_instance(zone=Zone.MZONE).bind(FakeRepository(card))
    original.add_counter("SPELL", 1)
    original.materials.append(InstanceId(9))
    original.temporary_effects.append(AppliedEffect(EffectRef(2511, 0)))

    copy = original.clone()
    copy.place(Zone.GRAVE)
    copy.add_counter("SPELL", 5)
    copy.materials.append(InstanceId(10))
    copy.temporary_effects.append(AppliedEffect(EffectRef(2511, 1)))
    copy.status_flags = 0xFF
    copy.set_controller(1)

    assert original.zone is Zone.MZONE
    assert original.counter("SPELL") == 1
    assert original.materials == [InstanceId(9)]
    assert len(original.temporary_effects) == 1
    assert original.status_flags == 0
    assert original.controller == 0
    # 카드 정의는 공유해도 된다 (읽기 전용이므로).
    assert copy.definition is original.definition


def test_canonical_state_uses_only_value_types():
    instance = make_instance()
    instance.add_counter("SPELL")
    instance.materials.append(InstanceId(3))
    instance.temporary_effects.append(AppliedEffect(EffectRef(2511, 0)))

    def check(value):
        if isinstance(value, tuple):
            for item in value:
                check(item)
        else:
            assert value is None or isinstance(value, (int, str, bool)), value

    check(instance.canonical_state())


def test_canonical_state_is_stable_for_equal_instances():
    a = make_instance()
    b = make_instance()
    assert a.canonical_state() == b.canonical_state()
    b.place(Zone.HAND)
    assert a.canonical_state() != b.canonical_state()
