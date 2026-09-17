"""한국어 자연어 질의 파서 검증."""

import pytest

from core import constants as C
from core.query_parser import KoreanQueryParser


@pytest.fixture(scope="module")
def parser():
    return KoreanQueryParser(default_limit=None)


def test_hand_special_summon_level_4(parser):
    f = parser.parse("패에서 특수 소환 가능한 4레벨 몬스터").filters
    assert f.levels == [4]
    assert f.required_types & C.TYPE_MONSTER
    assert f.special_summon_from_hand is True


def test_race_and_attribute(parser):
    f = parser.parse("기계족 빛속성 몬스터").filters
    assert f.races == [C.RACE_MACHINE]
    assert f.attributes == [C.ATTRIBUTE_LIGHT]
    assert f.required_types & C.TYPE_MONSTER


def test_combined_stats_and_effect_category(parser):
    f = parser.parse("4레벨 빛속성 기계족 몬스터 중 특수 소환 효과가 있는 카드").filters
    assert f.levels == [4]
    assert f.attributes == [C.ATTRIBUTE_LIGHT]
    assert f.races == [C.RACE_MACHINE]
    assert f.effect_categories == ["SPECIAL_SUMMON"]
    # 위치 조건이 없으므로 '패에서' 조건은 붙지 않아야 한다.
    assert f.special_summon_from_hand is False


def test_support_query_does_not_filter_by_own_race(parser):
    """'마법사족에 좋은' 은 그 카드가 마법사족이라는 뜻이 아니다."""
    f = parser.parse("마법사족에 좋은 드로우 카드").filters
    assert f.support_races == [C.RACE_SPELLCASTER]
    assert f.races == []
    assert f.effect_categories == ["DRAW"]


def test_location_only_query(parser):
    f = parser.parse("묘지에서 효과를 발동하는 카드").filters
    assert len(f.effect_locations) == 1
    assert f.effect_locations[0].location == "GRAVE"
    assert f.effect_locations[0].category is None


def test_rank_and_link_imply_card_type(parser):
    f = parser.parse("랭크 4 엑시즈").filters
    assert f.levels == [4]
    assert f.required_types & C.TYPE_XYZ

    f = parser.parse("링크 3 몬스터").filters
    assert f.levels == [3]
    assert f.required_types & C.TYPE_LINK


def test_atk_bounds(parser):
    f = parser.parse("공격력 2500 이상 드래곤족").filters
    assert f.atk_min == 2500
    assert f.races == [C.RACE_DRAGON]

    f = parser.parse("공격력 1000 이하 몬스터").filters
    assert f.atk_max == 1000


def test_compound_spell_types(parser):
    f = parser.parse("속공 마법").filters
    assert f.required_types & C.TYPE_SPELL
    assert f.required_types & C.TYPE_QUICKPLAY


def test_location_plus_category_pairs_up(parser):
    f = parser.parse("묘지에서 발동하는 파괴 효과").filters
    assert len(f.effect_locations) == 1
    assert f.effect_locations[0].location == "GRAVE"
    assert f.effect_locations[0].category == "DESTROY"


def test_unrecognized_query_falls_back_to_name_search(parser):
    parsed = parser.parse("블루아이즈 화이트 드래곤")
    assert parsed.filters.name == "블루아이즈 화이트 드래곤"


def test_quoted_name_is_used_verbatim(parser):
    parsed = parser.parse('"Dark Magician" 관련 카드')
    assert parsed.filters.name == "Dark Magician"


def test_explain_reports_interpretation(parser):
    parsed = parser.parse("4레벨 빛속성 기계족 몬스터")
    text = parsed.explain_ko()
    assert "기계족" in text and "빛속성" in text and "레벨 4" in text
