"""engine/state/use_registry.py — 세 스코프를 끝까지 분리해서 센다."""

import pytest

from analysis.effect_model import LimitScope
from engine.ids import EffectRef, InstanceId
from engine.state.use_registry import UseRegistry


def test_use_registry_keeps_the_three_scopes_apart():
    """같은 카드의 같은 효과라도 스코프가 다르면 서로 영향을 주면 안 된다."""
    registry = UseRegistry()
    instance = InstanceId(7)
    ref = EffectRef(2511, 0)

    registry.mark_card_used(0, instance)

    assert registry.card_used(0, instance)
    assert not registry.card_name_used(0, 2511)
    assert not registry.effect_used(0, ref)

    registry.mark_card_name_used(0, 2511)
    assert registry.card_name_used(0, 2511)
    assert not registry.effect_used(0, ref)

    registry.mark_effect_used(0, ref)
    assert registry.effect_used(0, ref)

    # 세 칸이 따로 저장되어야 한다.
    assert len(registry.per_card) == 1
    assert len(registry.per_card_name) == 1
    assert len(registry.per_effect) == 1


def test_identical_key_shapes_do_not_collide_across_scopes():
    """
    ``PerCardKey`` 와 ``PerCardNameKey`` 는 둘 다 ``(int, int)`` 다. 한 딕셔너리에
    담으면 "인스턴스 7번" 과 "카드 ID 7" 이 같은 칸을 쓴다.
    """
    registry = UseRegistry()
    registry.mark_card_used(0, InstanceId(7))

    assert registry.card_used(0, InstanceId(7))
    assert not registry.card_name_used(0, 7)

    registry.mark_card_name_used(0, 7)
    assert registry.count(LimitScope.PER_CARD, (0, 7)) == 1
    assert registry.count(LimitScope.PER_CARD_NAME, (0, 7)) == 1


def test_per_card_scope_distinguishes_copies_of_the_same_card():
    registry = UseRegistry()
    registry.mark_card_used(0, InstanceId(1))
    assert registry.count(LimitScope.PER_CARD, UseRegistry.card_key(0, InstanceId(1))) == 1
    assert registry.count(LimitScope.PER_CARD, UseRegistry.card_key(0, InstanceId(2))) == 0


def test_per_card_name_scope_covers_every_copy_but_only_one_player():
    registry = UseRegistry()
    registry.mark_card_name_used(0, 2511)
    assert registry.card_name_used(0, 2511)
    assert not registry.card_name_used(1, 2511)
    assert not registry.card_name_used(0, 9999)


def test_per_effect_scope_distinguishes_effects_of_one_card():
    registry = UseRegistry()
    registry.mark_effect_used(0, EffectRef(2511, 0))
    assert registry.effect_used(0, EffectRef(2511, 0))
    assert not registry.effect_used(0, EffectRef(2511, 1))
    assert not registry.effect_used(1, EffectRef(2511, 0))


def test_effect_key_uses_ordinal_not_effect_spec_index():
    """
    ``EffectSpec.index`` (Lua 의 ``e1``) 는 한 카드 안에서 중복되므로
    (실측 4,883장) 키가 될 수 없다. ``EffectRef.ordinal`` 만 쓴다.
    """
    assert UseRegistry.effect_key(0, EffectRef(2511, 3)) == (0, 2511, 3)


def test_use_registry_counts_rather_than_flags():
    """``SetCountLimit(2, ...)`` 같은 효과가 53건 있으므로 횟수로 센다."""
    registry = UseRegistry()
    assert registry.mark_card_used(0, InstanceId(1)) == 1
    assert registry.mark_card_used(0, InstanceId(1)) == 2
    assert registry.count(LimitScope.PER_CARD, UseRegistry.card_key(0, InstanceId(1))) == 2
    assert registry.mark_card_used(0, InstanceId(1), times=3) == 5


def test_use_registry_rejects_scopes_it_cannot_record():
    registry = UseRegistry()
    with pytest.raises(ValueError):
        registry.mark_used(LimitScope.NONE, (0, 1))
    with pytest.raises(ValueError):
        registry.count(LimitScope.UNKNOWN, (0, 1))


def test_use_registry_does_not_decide_when_to_reset():
    """리셋 시점은 규칙(Phase 4)이다. Phase 1 은 지우는 수단만 준다."""
    registry = UseRegistry()
    registry.mark_card_used(0, InstanceId(1))
    registry.mark_card_name_used(0, 2511)
    registry.mark_effect_used(0, EffectRef(2511, 0))

    registry.clear(LimitScope.PER_CARD)
    assert len(registry.per_card) == 0
    assert len(registry.per_card_name) == 1
    assert len(registry.per_effect) == 1

    registry.clear()
    assert len(registry) == 0


def test_clear_can_target_a_single_key():
    registry = UseRegistry()
    registry.mark_card_used(0, InstanceId(1))
    registry.mark_card_used(0, InstanceId(2))
    registry.clear(LimitScope.PER_CARD, UseRegistry.card_key(0, InstanceId(1)))
    assert not registry.card_used(0, InstanceId(1))
    assert registry.card_used(0, InstanceId(2))


def test_use_registry_clone_is_independent():
    registry = UseRegistry()
    registry.mark_card_used(0, InstanceId(1))
    copy = registry.clone()
    copy.mark_card_used(0, InstanceId(2))
    copy.mark_card_name_used(0, 2511)
    copy.mark_effect_used(0, EffectRef(2511, 0))

    assert len(registry.per_card) == 1
    assert len(registry.per_card_name) == 0
    assert len(registry.per_effect) == 0
    assert len(copy.per_card) == 2


def test_canonical_state_is_sorted_and_deterministic():
    a = UseRegistry()
    b = UseRegistry()
    for registry, order in ((a, (1, 2, 3)), (b, (3, 1, 2))):
        for value in order:
            registry.mark_card_used(0, InstanceId(value))
    assert a.canonical_state() == b.canonical_state()
    assert a == b


def test_canonical_state_can_remap_instance_ids():
    """
    ``instance_key`` 를 주면 인스턴스가 만들어진 순서가 해시에 새어 나가지
    않는다. 자리 번호만 같으면 원래 번호가 달라도 같은 표현이다.
    """
    a = UseRegistry()
    a.mark_card_used(0, InstanceId(10))
    b = UseRegistry()
    b.mark_card_used(0, InstanceId(77))

    assert a.canonical_state() != b.canonical_state()
    assert a.canonical_state(lambda i: 0) == b.canonical_state(lambda i: 0)
