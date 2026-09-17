"""engine/vocabulary.py — ScriptConstants 를 그대로 쓰는지 확인한다."""

import pytest

from engine.vocabulary import (
    PLAYER_ZONES,
    ZONE_CAPACITY,
    ZONE_KIND,
    ZONE_VISIBILITY,
    ConstantGroup,
    EngineVocabulary,
    Phase,
    Position,
    Zone,
    ZoneKind,
    ZoneVisibility,
    default_vocabulary,
    zone_capacity,
    zone_kind,
    zone_visibility,
)
from sources.script_constants import ScriptConstants

CONSTANTS = ScriptConstants.load()
requires_constants = pytest.mark.skipif(
    not CONSTANTS.others,
    reason="data/constants/constant.lua 가 없습니다.",
)


@requires_constants
def test_every_zone_position_phase_resolves():
    """Enum 멤버가 전부 실제 엔진 상수에 대응해야 한다."""
    assert default_vocabulary().missing_names() == []


@requires_constants
def test_zone_values_come_from_script_constants():
    """엔진이 쓰는 수치가 constant.lua 의 값과 같아야 한다 (별도 체계 금지)."""
    vocabulary = default_vocabulary()
    for zone in Zone:
        assert vocabulary.zone_value(zone) == CONSTANTS.others[f"LOCATION_{zone.value}"]


@requires_constants
def test_analysis_location_strings_are_engine_zones():
    """``EffectSpec.ranges`` 가 내놓는 문자열이 그대로 Zone 이어야 한다."""
    for name in ("HAND", "DECK", "GRAVE", "MZONE", "SZONE", "REMOVED", "EXTRA"):
        assert Zone(name).value == name


@requires_constants
def test_location_reason_constants_are_not_zones():
    """``LOCATION_REASON_*`` 은 존이 아니라 이동 사유다. 존 어휘에 섞이면 안 된다."""
    vocabulary = default_vocabulary()
    assert "REASON_CONTROL" not in vocabulary.locations
    assert "REASON_TOFIELD" not in vocabulary.locations
    # 진짜 사유 쪽에는 있어야 한다.
    assert vocabulary.reasons.value("COST") is not None


@requires_constants
def test_position_faceup_is_a_bitmask_of_the_two_faceup_positions():
    vocabulary = default_vocabulary()
    faceup = vocabulary.position_value(Position.FACEUP)
    assert faceup == (
        vocabulary.position_value(Position.FACEUP_ATTACK)
        | vocabulary.position_value(Position.FACEUP_DEFENSE)
    )


@requires_constants
def test_phase_names_match_constants():
    vocabulary = default_vocabulary()
    for phase in Phase:
        assert vocabulary.phase_value(phase) == CONSTANTS.others[f"PHASE_{phase.value}"]


def test_player_zones_are_the_ten_designed_zones():
    assert set(PLAYER_ZONES) == {
        Zone.DECK,
        Zone.HAND,
        Zone.EXTRA,
        Zone.MZONE,
        Zone.EMZONE,
        Zone.SZONE,
        Zone.GRAVE,
        Zone.REMOVED,
        Zone.FZONE,
        Zone.PZONE,
    }
    # OVERLAY 는 존 어휘에는 있지만 플레이어가 소유하는 존은 아니다.
    assert Zone.OVERLAY not in PLAYER_ZONES


@requires_constants
def test_extra_monster_zone_is_not_the_main_monster_zone():
    """
    EMZ 를 메인 몬스터 존과 같은 존으로 취급하면 "엑스트라 덱 몬스터를 몇 장
    놓을 수 있는가" 가 통째로 틀어진다. 상수부터 다른 값이다.
    """
    vocabulary = default_vocabulary()
    assert Zone.EMZONE is not Zone.MZONE
    assert vocabulary.zone_value(Zone.EMZONE) != vocabulary.zone_value(Zone.MZONE)
    assert vocabulary.zone_value(Zone.EMZONE) == CONSTANTS.others["LOCATION_EMZONE"]
    assert zone_capacity(Zone.MZONE) == 5
    assert zone_capacity(Zone.EMZONE) == 1


def test_every_player_zone_declares_kind_capacity_and_visibility():
    """셋 중 하나라도 빠지면 표현할 수 없는 상태가 조용히 만들어진다."""
    for zone in Zone:
        assert zone in ZONE_KIND
        assert zone in ZONE_CAPACITY
        assert zone in ZONE_VISIBILITY
        assert zone_kind(zone) in (ZoneKind.ORDERED, ZoneKind.SLOTTED)
        assert zone_visibility(zone) in ZoneVisibility


def test_slotted_zones_are_exactly_the_ones_with_fixed_slots():
    slotted = {zone for zone in Zone if zone_kind(zone) is ZoneKind.SLOTTED}
    assert slotted == {
        Zone.MZONE,
        Zone.EMZONE,
        Zone.SZONE,
        Zone.FZONE,
        Zone.PZONE,
    }
    # 칸 방식 존은 반드시 칸 수가 있고, 순서 방식 존 중 EXTRA 만 상한이 있다.
    for zone in slotted:
        assert zone_capacity(zone) is not None


def test_hidden_and_owner_only_zones_are_not_public():
    assert zone_visibility(Zone.DECK) is ZoneVisibility.HIDDEN
    assert zone_visibility(Zone.HAND) is ZoneVisibility.OWNER_ONLY
    assert zone_visibility(Zone.EXTRA) is ZoneVisibility.OWNER_ONLY
    assert zone_visibility(Zone.GRAVE) is ZoneVisibility.PUBLIC
    assert zone_visibility(Zone.MZONE) is ZoneVisibility.PUBLIC


def test_constant_group_accepts_prefixed_and_bare_names():
    group = ConstantGroup("REASON_", {"COST": 0x80, "EFFECT": 0x10})
    assert group.value("COST") == 0x80
    assert group.value("REASON_COST") == 0x80
    assert group.value("reason_cost") == 0x80
    assert group.COST == 0x80
    assert group.name(0x10) == "EFFECT"
    assert group.value("NOPE") is None


def test_constant_group_unknown_attribute_is_explicit():
    group = ConstantGroup("REASON_", {"COST": 0x80})
    with pytest.raises(AttributeError, match="REASON_NOPE"):
        group.NOPE


def test_vocabulary_survives_missing_constant_files():
    """상수 파일이 없어도 죽지 않고, 무엇이 없는지 말해준다."""
    vocabulary = EngineVocabulary(ScriptConstants())
    assert not vocabulary
    missing = vocabulary.missing_names()
    assert "LOCATION_GRAVE" in missing
    assert "PHASE_MAIN1" in missing


@requires_constants
def test_status_mask_rejects_unknown_names():
    vocabulary = default_vocabulary()
    with pytest.raises(KeyError):
        vocabulary.status_mask("DEFINITELY_NOT_A_STATUS")
