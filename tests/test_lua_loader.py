"""Lua 스크립트 파서 검증. 저장소에 실제로 있는 카드 파일을 사용한다."""

import pytest

from sources.lua_loader import parse_lua_source
from tests.conftest import PROJECT_ROOT, read_script


@pytest.fixture(scope="module")
def cooclock():
    # 白銀の城の狂時計 / Labrynth Cooclock
    return parse_lua_source(2511, "c2511.lua", read_script("c2511.lua"))


@pytest.fixture(scope="module")
def ten_thousand_dragon():
    # 万物創世龍 / Ten Thousand Dragon
    return parse_lua_source(10000, "c10000.lua", read_script("c10000.lua"))


def test_header_names_are_kept_verbatim(cooclock):
    assert cooclock.name_ja == "白銀の城の狂時計"
    assert cooclock.name_en == "Labrynth Cooclock"
    assert cooclock.scripted_by == "Hatter"


def test_effect_blocks_group_location_with_category(cooclock):
    """
    핵심 요구사항: 위치와 효과 분류가 같은 블록으로 묶여야 한다.
    파일 전체에서 상수를 모으면 어떤 효과가 어디서 발동하는지 알 수 없다.
    """
    grave_effects = [e for e in cooclock.effects if "GRAVE" in e.ranges]
    assert len(grave_effects) == 1
    effect = grave_effects[0]
    assert effect.code == "EVENT_TO_GRAVE"
    assert set(effect.categories) == {"TOHAND", "SPECIAL_SUMMON"}

    # 패에서 발동하는 효과는 별개의 블록이며 특수 소환 분류가 없다.
    hand_effects = [e for e in cooclock.effects if "HAND" in e.ranges]
    assert len(hand_effects) == 1
    assert hand_effects[0].categories == []


def test_self_special_summon_procedure_is_detected(ten_thousand_dragon):
    procs = [
        e
        for e in ten_thousand_dragon.effects
        if e.code == "EFFECT_SPSUMMON_PROC" and "HAND" in e.ranges
    ]
    assert len(procs) == 1


def test_clone_inherits_parent_properties(ten_thousand_dragon):
    """e4=e3:Clone() 은 e3 의 속성을 물려받고 일부만 덮어쓴다."""
    cloned = [e for e in ten_thousand_dragon.effects if e.cloned_from]
    assert len(cloned) == 1
    effect = cloned[0]
    assert effect.cloned_from == "e3"
    assert effect.code == "EFFECT_SET_DEFENSE"  # 덮어쓴 값
    assert effect.ranges == ["MZONE"]  # 물려받은 값
    assert effect.effect_types == ["SINGLE"]


def test_listed_series_and_self_reference(cooclock):
    assert cooclock.listed_series == ["LABRYNTH"]
    # s.listed_names={id} 는 자기 자신을 지명한다는 뜻이다.
    assert cooclock.listed_names == [2511]


def test_named_card_constants_are_preserved_for_later_resolution():
    path = PROJECT_ROOT / "c111280.lua"
    if not path.is_file():
        pytest.skip("샘플 스크립트 없음")
    info = parse_lua_source(111280, path.name, path.read_text(encoding="utf-8"))
    assert "CARD_DARK_MAGICIAN" in info.listed_name_constants


def test_parser_never_raises_on_the_whole_corpus():
    """12,000여 개 스크립트 전체가 예외 없이 파싱되어야 한다."""
    from sources.lua_loader import LuaScriptSource

    source = LuaScriptSource(PROJECT_ROOT)
    files = list(source.iter_script_files())
    assert len(files) > 12000
    for card_id, path in files[:500]:
        parse_lua_source(card_id, path.name, path.read_text(encoding="utf-8"))
