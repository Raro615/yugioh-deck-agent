"""
실제 데이터(공식 DB + 12,000여 개 Lua 스크립트)를 사용한 통합 검증.

cards.cdb 가 없으면 건너뛴다.
"""

import pytest

from core import constants as C
from core.card_search import EffectLocationFilter, SearchFilters
from tests.conftest import requires_official_db

pytestmark = requires_official_db

# 인수인계서에 명시된 예시 질의
EXAMPLE_QUERIES = [
    "패에서 특수 소환 가능한 4레벨 몬스터",
    "기계족 빛속성 몬스터",
    "4레벨 빛속성 기계족 몬스터 중 특수 소환 효과가 있는 카드",
    "마법사족에 좋은 드로우 카드",
    "묘지에서 효과를 발동하는 카드",
]


def test_repository_joins_both_sources(repository):
    stats = repository.stats()
    assert stats["with_official_data"] > 14000
    assert stats["with_script"] > 12000
    # 같은 카드의 다른 일러스트/에라타 판본은 중복 제거 대상으로 표시된다.
    assert stats["alternate_art"] > 0
    assert stats["canonical"] == stats["total"] - stats["alternate_art"]


def test_card_gets_data_from_both_sources(repository):
    card = repository.get(2511)  # Labrynth Cooclock
    # 공식 DB 쪽
    assert card.race_mask == C.RACE_FIEND
    assert card.attribute_mask == C.ATTRIBUTE_DARK
    assert card.level == 1
    assert card.desc  # 카드 텍스트 원문
    # Lua 쪽
    assert card.name_ja == "白銀の城の狂時計"
    assert card.has_effect_from("GRAVE", "SPECIAL_SUMMON")


@pytest.mark.parametrize("query", EXAMPLE_QUERIES)
def test_every_example_query_returns_results(query, parser, engine):
    parsed = parser.parse(query)
    result = engine.search(parsed.filters)
    assert result.total > 0, f"'{query}' 가 아무것도 찾지 못했습니다"


def test_stat_filters_are_exact(engine):
    filters = SearchFilters(
        levels=[4],
        attributes=[C.ATTRIBUTE_LIGHT],
        races=[C.RACE_MACHINE],
        required_types=C.TYPE_MONSTER,
    )
    result = engine.search(filters)
    assert result.total > 0
    for card in result:
        assert card.level == 4
        assert card.attribute_mask & C.ATTRIBUTE_LIGHT
        assert card.race_mask & C.RACE_MACHINE
        assert card.is_monster


def test_hand_special_summon_results_are_semantically_correct(parser, engine):
    parsed = parser.parse("패에서 특수 소환 가능한 4레벨 몬스터")
    result = engine.search(parsed.filters)
    assert result.total > 0
    for card in result:
        assert card.level == 4
        # 자체 특수 소환 절차이거나, 패에서 발동하는 특수 소환 효과여야 한다.
        assert (
            card.can_self_special_summon_from_hand
            or card.has_effect_from("HAND", "SPECIAL_SUMMON")
        )


def test_grave_activation_results_have_a_grave_ranged_effect(engine):
    filters = SearchFilters(effect_locations=[EffectLocationFilter("GRAVE")])
    result = engine.search(filters)
    assert result.total > 1000
    for card in result.cards[:200]:
        assert any("GRAVE" in effect.ranges for effect in card.effects)


def test_support_race_matches_own_race_or_text_reference(engine):
    filters = SearchFilters(
        support_races=[C.RACE_SPELLCASTER], effect_categories=["DRAW"]
    )
    result = engine.search(filters)
    assert result.total > 0
    for card in result.cards[:50]:
        # 한국어 데이터가 적용되면 desc 가 한국어가 되므로 양쪽을 모두 본다.
        assert (
            card.race_mask & C.RACE_SPELLCASTER
            or "마법사족" in card.desc
            or "Spellcaster" in card.desc_en
        )


def test_archetype_combines_official_setcode_and_script_series(repository):
    cards = repository.by_archetype("LABRYNTH")
    assert len(cards) >= 10
    # 표시명은 한국어 데이터 적용 여부에 따라 달라지므로 원문으로 확인한다.
    names = {c.name_en for c in cards}
    assert "Labrynth Cooclock" in names
    # 상수 접두사가 있든 없든 같은 결과를 준다.
    assert {c.id for c in cards} == {c.id for c in repository.by_archetype("SET_LABRYNTH")}


def test_named_card_constants_are_resolved_into_relations(repository):
    # CARD_DARK_MAGICIAN 상수가 실제 ID 46986414 로 해석되어야 관계가 잡힌다.
    referencing = repository.referenced_by(46986414)
    assert len(referencing) > 20
    assert any(c.name_en == "Dark Magic Attack" for c in referencing)


def test_results_are_deduplicated_by_default(repository, engine):
    filters = SearchFilters(races=[C.RACE_MACHINE], required_types=C.TYPE_MONSTER)
    result = engine.search(filters)
    ids = [c.id for c in result]
    assert len(ids) == len(set(ids))
    assert not any(c.is_alternate_art for c in result)


def test_limit_does_not_change_reported_total(engine):
    unlimited = engine.search(SearchFilters(races=[C.RACE_DRAGON]))
    limited = engine.search(SearchFilters(races=[C.RACE_DRAGON], limit=5))
    assert limited.total == unlimited.total
    assert len(limited.cards) == 5
