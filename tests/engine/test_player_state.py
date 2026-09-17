"""engine/state/player.py — LP 와 존. **그뿐이다.**

사용 횟수(UseRegistry)는 듀얼 전체에 하나뿐이라 GameState 가 들고 있고,
테스트는 tests/engine/test_use_registry.py 에 있다.
"""

import dataclasses

import pytest

from engine.ids import InstanceId
from engine.state.card_instance import CardInstance
from engine.state.player import DEFAULT_LIFE_POINTS, PlayerState
from engine.vocabulary import PLAYER_ZONES, Zone


def test_player_has_every_player_zone():
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


def test_player_state_carries_no_rule_state():
    """
    "일반 소환을 몇 번 했는가", "이번 턴에 드로우했는가" 는 **턴 진행 규칙에
    속하는 상태**다. Phase 1 의 PlayerState 에 넣어두면 규칙을 구현하기도
    전에 규칙의 모양을 못박게 되므로, 필드 자체가 없어야 한다.

    사용 횟수도 여기 없다 — 키가 ``(player, ...)`` 로 시작하므로 듀얼 전체에
    하나면 되고 GameState 가 들고 있다.
    """
    fields = {f.name for f in dataclasses.fields(PlayerState)}
    assert fields == {"player_id", "life_points", "zones"}

    player = PlayerState(player_id=0)
    for forbidden in (
        "normal_summon_used",
        "normal_summon_allowed",
        "turn_flags",
        "uses",
        "record_normal_summon",
        "reset_for_turn",
    ):
        assert not hasattr(player, forbidden), (
            f"PlayerState 가 {forbidden} 을 다시 갖게 되었습니다. "
            "턴 진행 규칙 상태는 Phase 4 의 몫입니다."
        )


def test_extra_monster_zone_is_a_separate_zone():
    """EMZ 는 메인 몬스터 존과 다른 존이다. 같은 존으로 뭉뚱그리면 안 된다."""
    player = PlayerState(player_id=0)
    assert Zone.EMZONE in player.zones
    assert player.zone(Zone.EMZONE) is not player.zone(Zone.MZONE)
    assert player.zone(Zone.MZONE).capacity == 5
    assert player.zone(Zone.EMZONE).capacity == 1


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
    copy.deck.pop()

    assert player.life_points == DEFAULT_LIFE_POINTS
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
