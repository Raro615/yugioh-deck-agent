"""engine/state/player.py — LP, 존, 일반소환 횟수, UseRegistry 3 스코프."""

import pytest

from analysis.effect_model import LimitScope
from engine.ids import EffectRef, InstanceId
from engine.state.card_instance import CardInstance
from engine.state.player import DEFAULT_LIFE_POINTS, PlayerState, UseRegistry
from engine.vocabulary import PLAYER_ZONES, Zone


def test_player_has_all_nine_zones():
    player = PlayerState(player_id=0)
    assert set(player.zones) == set(PLAYER_ZONES)
    for zone in PLAYER_ZONES:
        assert player.zone(zone).owner == 0
        assert len(player.zone(zone)) == 0


def test_zone_accessors_point_at_the_same_containers():
    player = PlayerState(player_id=1)
    assert player.hand is player.zones[Zone.HAND]
    assert player.deck is player[Zone.DECK]
    assert player.monster_zone is player.zones[Zone.MZONE]
    assert player.spell_zone is player.zones[Zone.SZONE]
    assert player.removed is player.zones[Zone.REMOVED]


def test_unknown_zone_is_an_explicit_error():
    player = PlayerState(player_id=0)
    del player.zones[Zone.PZONE]
    with pytest.raises(KeyError):
        player.zone(Zone.PZONE)


def test_life_points_default_and_change():
    player = PlayerState(player_id=0)
    assert player.life_points == DEFAULT_LIFE_POINTS
    assert player.change_life(-3000) == 5000
    assert player.change_life(1000) == 6000
    assert player.change_life(-99999) == 0  # 0 아래로 내려가지 않는다


def test_normal_summon_counters_are_records_not_rules():
    player = PlayerState(player_id=0)
    assert (player.normal_summon_used, player.normal_summon_allowed) == (0, 1)
    player.record_normal_summon()
    assert player.normal_summon_used == 1
    # 판정하지 않으므로 허용치를 넘겨도 막지 않는다 (Phase 4 의 일).
    player.record_normal_summon()
    assert player.normal_summon_used == 2


def test_reset_for_turn_clears_turn_scoped_state():
    player = PlayerState(player_id=0)
    player.record_normal_summon()
    player.turn_flags.drew_for_turn = True
    player.uses.record_card(InstanceId(1))

    player.reset_for_turn()

    assert player.normal_summon_used == 0
    assert player.turn_flags.drew_for_turn is False
    assert len(player.uses) == 0


# ----------------------------------------------------------------------
# UseRegistry — 세 스코프
# ----------------------------------------------------------------------


def test_use_registry_keeps_the_three_scopes_apart():
    """같은 카드의 같은 효과라도 스코프가 다르면 서로 영향을 주면 안 된다."""
    registry = UseRegistry()
    instance = InstanceId(7)
    ref = EffectRef(2511, 0)

    registry.record(LimitScope.PER_CARD, player=0, instance_id=instance)

    assert registry.used(LimitScope.PER_CARD, player=0, instance_id=instance)
    assert not registry.used(LimitScope.PER_CARD_NAME, player=0, effect_ref=ref)
    assert not registry.used(LimitScope.PER_EFFECT, player=0, effect_ref=ref)

    registry.record(LimitScope.PER_CARD_NAME, player=0, card_id=2511)
    assert registry.used(LimitScope.PER_CARD_NAME, player=0, card_id=2511)
    assert not registry.used(LimitScope.PER_EFFECT, player=0, effect_ref=ref)

    registry.record(LimitScope.PER_EFFECT, player=0, effect_ref=ref)
    assert registry.used(LimitScope.PER_EFFECT, player=0, effect_ref=ref)

    # 세 칸이 따로 저장되어야 한다.
    assert len(registry.per_card) == 1
    assert len(registry.per_card_name) == 1
    assert len(registry.per_effect) == 1


def test_per_card_scope_distinguishes_copies_of_the_same_card():
    registry = UseRegistry()
    registry.record_card(InstanceId(1))
    assert registry.count_card(InstanceId(1)) == 1
    assert registry.count_card(InstanceId(2)) == 0


def test_per_card_name_scope_covers_every_copy_but_only_one_player():
    registry = UseRegistry()
    registry.record_card_name(0, 2511)
    assert registry.count_card_name(0, 2511) == 1
    assert registry.count_card_name(1, 2511) == 0
    assert registry.count_card_name(0, 9999) == 0


def test_per_effect_scope_distinguishes_effects_of_one_card():
    registry = UseRegistry()
    registry.record_effect(0, EffectRef(2511, 0))
    assert registry.count_effect(0, EffectRef(2511, 0)) == 1
    assert registry.count_effect(0, EffectRef(2511, 1)) == 0
    assert registry.count_effect(1, EffectRef(2511, 0)) == 0


def test_use_registry_counts_rather_than_flags():
    """``SetCountLimit(2, ...)`` 같은 효과가 53건 있으므로 횟수로 센다."""
    registry = UseRegistry()
    registry.record_card(InstanceId(1))
    registry.record_card(InstanceId(1))
    assert registry.count_card(InstanceId(1)) == 2


def test_use_registry_rejects_records_missing_their_key():
    registry = UseRegistry()
    with pytest.raises(ValueError):
        registry.record(LimitScope.PER_CARD, player=0)
    with pytest.raises(ValueError):
        registry.record(LimitScope.PER_EFFECT, player=0)
    with pytest.raises(ValueError):
        registry.record(LimitScope.PER_CARD_NAME, player=0)
    with pytest.raises(ValueError):
        registry.record(LimitScope.NONE, player=0, instance_id=InstanceId(1))
    with pytest.raises(ValueError):
        registry.count(LimitScope.UNKNOWN, player=0, instance_id=InstanceId(1))


def test_use_registry_clone_is_independent():
    registry = UseRegistry()
    registry.record_card(InstanceId(1))
    copy = registry.clone()
    copy.record_card(InstanceId(2))
    copy.record_card_name(0, 2511)
    copy.record_effect(0, EffectRef(2511, 0))

    assert len(registry.per_card) == 1
    assert len(registry.per_card_name) == 0
    assert len(registry.per_effect) == 0
    assert len(copy.per_card) == 2


def test_player_clone_is_independent():
    player = PlayerState(player_id=0)
    player.deck.append(
        CardInstance(
            instance_id=InstanceId(0),
            card_id=1,
            owner=0,
            controller=0,
            zone=Zone.DECK,
        )
    )
    copy = player.clone()
    copy.change_life(-1000)
    copy.record_normal_summon()
    copy.turn_flags.drew_for_turn = True
    copy.uses.record_card(InstanceId(0))
    copy.deck.pop()

    assert player.life_points == DEFAULT_LIFE_POINTS
    assert player.normal_summon_used == 0
    assert player.turn_flags.drew_for_turn is False
    assert len(player.uses) == 0
    assert len(player.deck) == 1


def test_find_instance_searches_every_zone():
    player = PlayerState(player_id=0)
    card = CardInstance(
        instance_id=InstanceId(3), card_id=1, owner=0, controller=0, zone=Zone.GRAVE
    )
    player.grave.append(card)

    assert player.find_instance(InstanceId(3)) is card
    assert player.locate(InstanceId(3)) is player.grave
    assert player.find_instance(InstanceId(4)) is None
    assert player.locate(InstanceId(4)) is None
    assert player.all_instances() == [card]
