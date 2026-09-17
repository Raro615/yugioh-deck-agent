"""engine/action.py · engine/action_target.py — 의도를 표현하되 실행하지 않는다."""

import dataclasses

import pytest

from engine.action import MalformedAction, PlayerAction, PlayerActionKind
from engine.action_target import ActionTarget, ActionTargetKind
from engine.ids import EffectRef, InstanceId
from engine.vocabulary import Phase, Zone


# ----------------------------------------------------------------------
# Action 생성 — 종류마다 필요한 칸이 다르다
# ----------------------------------------------------------------------


def test_normal_summon_action_names_the_card_and_nothing_else():
    action = PlayerAction.normal_summon(actor=0, source=InstanceId(3))

    assert action.kind is PlayerActionKind.NORMAL_SUMMON
    assert action.actor == 0
    assert action.source == InstanceId(3)
    assert action.targets == ()
    assert action.effect_ref is None
    assert action.phase is None


def test_activate_effect_action_points_at_one_effect():
    ref = EffectRef(2511, 1)
    action = PlayerAction.activate_effect(actor=1, source=InstanceId(9), effect_ref=ref)

    assert action.kind is PlayerActionKind.ACTIVATE_EFFECT
    assert action.effect_ref == ref
    assert action.source == InstanceId(9)


def test_attack_action_names_attacker_and_target():
    action = PlayerAction.attack(
        actor=0, source=InstanceId(5), target=ActionTarget.instance(InstanceId(7))
    )

    assert action.kind is PlayerActionKind.ATTACK
    assert action.source == InstanceId(5)
    assert action.instance_targets() == (InstanceId(7),)


def test_direct_attack_targets_the_player_not_a_monster():
    """
    "대상이 없으면 다이렉트 어택" 으로 두지 않는다. 빠뜨린 대상과
    의도한 직접 공격이 구분되지 않기 때문이다.
    """
    action = PlayerAction.attack_directly(actor=0, source=InstanceId(5))

    assert action.target is not None
    assert action.target.kind is ActionTargetKind.PLAYER
    assert action.target.player == 1
    assert action.instance_targets() == ()


def test_change_phase_action_carries_a_phase_and_no_card():
    action = PlayerAction.change_phase(actor=0, phase=Phase.MAIN1)

    assert action.kind is PlayerActionKind.CHANGE_PHASE
    assert action.phase is Phase.MAIN1
    assert action.source is None


def test_set_and_position_and_pass_actions_exist():
    assert PlayerAction.set_monster(0, InstanceId(1)).kind is PlayerActionKind.SET_MONSTER
    assert (
        PlayerAction.set_spell_trap(0, InstanceId(1)).kind
        is PlayerActionKind.SET_SPELL_TRAP
    )
    assert (
        PlayerAction.change_position(0, InstanceId(1)).kind
        is PlayerActionKind.CHANGE_POSITION
    )
    assert PlayerAction.end_phase(0).kind is PlayerActionKind.END_PHASE
    assert PlayerAction.passing(0).kind is PlayerActionKind.PASS


def test_actor_outside_the_two_players_is_refused():
    with pytest.raises(MalformedAction):
        PlayerAction.end_phase(actor=2)


# ----------------------------------------------------------------------
# 효과의 결과는 Action 이 아니다 (ADR-001 / ADR-002)
# ----------------------------------------------------------------------


def test_effect_results_are_not_player_actions():
    """
    ADR-002.

    이것들이 어휘에 들어가는 순간 AI 가 "카드 B 를 파괴한다" 를 직접
    고르게 되고, 규칙 계산이 엔진에서 AI 로 넘어간다.
    """
    names = {member.value for member in PlayerActionKind}
    for forbidden in (
        "destroy",
        "banish",
        "send_to_grave",
        "to_grave",
        "discard",
        "release",
        "return_to_hand",
        "to_hand",
        "change_control",
    ):
        assert forbidden not in names, (
            f"PlayerActionKind 에 {forbidden} 가 들어왔습니다. 그것은 효과의 "
            "결과이지 누가 고르는 것이 아닙니다 (ADR-002)."
        )


def test_player_action_kind_is_not_the_analysis_vocabulary():
    """
    ADR-001.

    ``analysis.ActionKind`` 는 효과가 하는 일을 담는다. 두 enum 은 서로
    다른 타입이고, 같은 이름의 멤버조차 같은 값으로 비교되면 안 된다.
    """
    from analysis.effect_model import ActionKind

    assert PlayerActionKind is not ActionKind
    assert PlayerActionKind.NORMAL_SUMMON is not ActionKind.NORMAL_SUMMON

    # 겹치는 이름은 normal_summon 하나뿐이고, 그것도 뜻이 다르다.
    engine_names = {m.value for m in PlayerActionKind}
    analysis_names = {m.value for m in ActionKind}
    assert engine_names & analysis_names == {"normal_summon"}


# ----------------------------------------------------------------------
# 불변성
# ----------------------------------------------------------------------


def test_action_is_immutable():
    action = PlayerAction.normal_summon(0, InstanceId(3))

    with pytest.raises(dataclasses.FrozenInstanceError):
        action.kind = PlayerActionKind.ATTACK
    with pytest.raises(dataclasses.FrozenInstanceError):
        action.source = InstanceId(4)
    with pytest.raises(dataclasses.FrozenInstanceError):
        action.actor = 1


def test_action_targets_cannot_be_grown_after_creation():
    action = PlayerAction.attack_directly(0, InstanceId(5))
    assert isinstance(action.targets, tuple)
    with pytest.raises(AttributeError):
        action.targets.append(ActionTarget.instance(InstanceId(9)))


def test_a_list_of_targets_is_refused_outright():
    """tuple 을 강제하지 않으면 Action 이 조용히 가변이 된다."""
    with pytest.raises(MalformedAction):
        PlayerAction(
            kind=PlayerActionKind.ATTACK,
            actor=0,
            source=InstanceId(1),
            targets=[ActionTarget.instance(InstanceId(2))],  # type: ignore[arg-type]
        )


def test_action_target_is_immutable():
    target = ActionTarget.instance(InstanceId(3))
    with pytest.raises(dataclasses.FrozenInstanceError):
        target.instance_id = InstanceId(4)


# ----------------------------------------------------------------------
# 동등성
# ----------------------------------------------------------------------


def test_logically_identical_actions_are_equal():
    a = PlayerAction.normal_summon(actor=0, source=InstanceId(123))
    b = PlayerAction.normal_summon(actor=0, source=InstanceId(123))

    assert a is not b
    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}


def test_a_different_instance_is_a_different_action():
    a = PlayerAction.normal_summon(0, InstanceId(123))
    b = PlayerAction.normal_summon(0, InstanceId(124))
    assert a != b


def test_a_different_actor_is_a_different_action():
    assert PlayerAction.normal_summon(0, InstanceId(1)) != PlayerAction.normal_summon(
        1, InstanceId(1)
    )


def test_a_different_effect_ordinal_is_a_different_action():
    source = InstanceId(9)
    a = PlayerAction.activate_effect(0, source, EffectRef(2511, 0))
    b = PlayerAction.activate_effect(0, source, EffectRef(2511, 1))
    assert a != b


def test_target_order_is_part_of_the_action():
    """대상의 순서가 의미를 갖는 효과가 있으므로 정렬하지 않는다."""
    one = ActionTarget.instance(InstanceId(1))
    two = ActionTarget.instance(InstanceId(2))
    a = PlayerAction.activate_card(0, InstanceId(9), targets=(one, two))
    b = PlayerAction.activate_card(0, InstanceId(9), targets=(two, one))
    assert a != b


# ----------------------------------------------------------------------
# 대상 표현
# ----------------------------------------------------------------------


def test_instance_target_holds_an_id_not_an_object():
    target = ActionTarget.instance(InstanceId(7))
    assert target.kind is ActionTargetKind.INSTANCE
    assert target.instance_id == InstanceId(7)
    assert target.canonical_state() == ("instance", 7, None, None, None)


def test_player_target():
    target = ActionTarget.player_target(1)
    assert target.kind is ActionTargetKind.PLAYER
    assert target.player == 1


def test_zone_target_can_name_a_whole_zone_or_one_slot():
    whole = ActionTarget.zone_target(0, Zone.MZONE)
    slot = ActionTarget.zone_target(0, Zone.MZONE, 3)

    assert whole.index is None
    assert slot.index == 3
    assert whole != slot


def test_extra_monster_zone_is_addressable_and_has_one_slot():
    assert ActionTarget.zone_target(0, Zone.EMZONE, 0).index == 0
    with pytest.raises(ValueError):
        ActionTarget.zone_target(0, Zone.EMZONE, 1)  # 칸이 1개뿐이다


def test_slot_number_on_an_ordered_zone_is_refused():
    """덱·패·묘지에는 칸이 없다. 없는 자리를 가리키는 Action 을 만들지 않는다."""
    for zone in (Zone.HAND, Zone.DECK, Zone.GRAVE, Zone.REMOVED, Zone.EXTRA):
        with pytest.raises(ValueError):
            ActionTarget.zone_target(0, zone, 0)
        # 존 전체를 가리키는 것은 괜찮다.
        assert ActionTarget.zone_target(0, zone).index is None


def test_out_of_range_slot_is_refused():
    with pytest.raises(ValueError):
        ActionTarget.zone_target(0, Zone.MZONE, 5)
    with pytest.raises(ValueError):
        ActionTarget.zone_target(0, Zone.MZONE, -1)


def test_malformed_target_structures_are_refused():
    with pytest.raises(ValueError):
        ActionTarget(kind=ActionTargetKind.INSTANCE)  # id 가 없다
    with pytest.raises(ValueError):
        ActionTarget(kind=ActionTargetKind.INSTANCE, player=0)  # 엉뚱한 칸
    with pytest.raises(ValueError):
        ActionTarget(kind=ActionTargetKind.PLAYER, player=5)
    with pytest.raises(ValueError):
        ActionTarget(kind=ActionTargetKind.ZONE, player=0)  # zone 이 없다
    with pytest.raises(ValueError):
        ActionTarget(kind=ActionTargetKind.NONE, player=0)


# ----------------------------------------------------------------------
# owner / controller / actor
# ----------------------------------------------------------------------


def test_actor_is_independent_of_owner_and_controller():
    """
    컨트롤을 빼앗긴 카드로 상대가 공격하는 상황.

    ``owner=0`` 인 카드를 ``controller=1`` 이 쥐고 있고, 그 공격을 선언하는
    ``actor`` 도 1 이다. 셋이 서로 다른 축이라는 것을 Action 이 표현할 수
    있어야 한다.
    """
    from engine.state.card_instance import CardInstance

    stolen = CardInstance(
        instance_id=InstanceId(4),
        card_id=1000,
        owner=0,
        controller=1,
        zone=Zone.MZONE,
    )
    action = PlayerAction.attack_directly(actor=1, source=stolen.instance_id)

    assert stolen.owner == 0
    assert stolen.controller == 1
    assert action.actor == 1
    assert action.opponent == 0
    # Action 은 카드를 id 로만 가리키므로 owner/controller 를 복제하지 않는다.
    assert action.source == stolen.instance_id


# ----------------------------------------------------------------------
# 직렬화 — 결정론 (§28)
# ----------------------------------------------------------------------


def _json(action: PlayerAction) -> str:
    import json

    return json.dumps(action.to_dict(), sort_keys=True, ensure_ascii=False)


def test_identical_actions_serialize_identically():
    a = PlayerAction.activate_effect(0, InstanceId(9), EffectRef(2511, 1))
    b = PlayerAction.activate_effect(0, InstanceId(9), EffectRef(2511, 1))
    assert a.canonical_state() == b.canonical_state()
    assert _json(a) == _json(b)


def test_a_different_target_serializes_differently():
    a = PlayerAction.attack(0, InstanceId(5), ActionTarget.instance(InstanceId(7)))
    b = PlayerAction.attack(0, InstanceId(5), ActionTarget.instance(InstanceId(8)))
    assert a.canonical_state() != b.canonical_state()
    assert _json(a) != _json(b)


def test_a_different_actor_serializes_differently():
    a = PlayerAction.end_phase(0)
    b = PlayerAction.end_phase(1)
    assert _json(a) != _json(b)


def test_a_different_effect_ordinal_serializes_differently():
    source = InstanceId(9)
    a = PlayerAction.activate_effect(0, source, EffectRef(2511, 0))
    b = PlayerAction.activate_effect(0, source, EffectRef(2511, 1))
    assert a.canonical_state() != b.canonical_state()
    assert _json(a) != _json(b)


def test_serialization_holds_no_object_identity():
    """
    메모리 주소 · repr · 난수 UUID 가 섞이면 replay 가 불가능해진다.
    값은 정수 · 문자열 · 불리언 · ``None`` 뿐이어야 한다.
    """
    action = PlayerAction.activate_effect(
        1,
        InstanceId(9),
        EffectRef(2511, 1),
        targets=(
            ActionTarget.instance(InstanceId(3)),
            ActionTarget.zone_target(0, Zone.MZONE, 2),
        ),
    )

    def leaves(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from leaves(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from leaves(item)
        else:
            yield value

    for value in leaves(action.to_dict()):
        assert value is None or isinstance(value, (int, str, bool)), (
            f"직렬화에 값 타입이 아닌 것이 들어 있습니다: {value!r}"
        )
    for value in leaves(action.canonical_state()):
        assert value is None or isinstance(value, (int, str, bool))

    text = _json(action)
    assert "0x" not in text
    assert "object at" not in text
    assert "InstanceId(" not in text


def test_serialization_survives_a_round_trip():
    """향후 EventJournal 이 Action 을 저장했다가 다시 읽을 수 있어야 한다."""
    for action in (
        PlayerAction.normal_summon(0, InstanceId(3)),
        PlayerAction.change_phase(1, Phase.MAIN2),
        PlayerAction.attack_directly(0, InstanceId(5)),
        PlayerAction.passing(1),
        PlayerAction.activate_effect(
            0,
            InstanceId(9),
            EffectRef(2511, 2),
            targets=(
                ActionTarget.instance(InstanceId(1)),
                ActionTarget.zone_target(1, Zone.SZONE, 4),
                ActionTarget.player_target(1),
            ),
        ),
    ):
        assert PlayerAction.from_dict(action.to_dict()) == action


def test_canonical_state_is_stable_across_processes():
    """``PYTHONHASHSEED`` 가 달라도 같은 값이어야 한다."""
    import pathlib
    import subprocess
    import sys

    snippet = (
        "from engine.action import PlayerAction;"
        "from engine.ids import InstanceId, EffectRef;"
        "import json;"
        "print(json.dumps(PlayerAction.activate_effect("
        "0, InstanceId(9), EffectRef(2511, 1)).canonical_state()))"
    )
    outputs = set()
    for seed in ("0", "12345"):
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
            cwd=str(pathlib.Path(__file__).resolve().parents[2]),
        )
        assert result.returncode == 0, result.stderr
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1
