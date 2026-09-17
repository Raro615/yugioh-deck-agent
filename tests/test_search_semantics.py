"""
검색 계층의 의미 검증.

숫자를 맞추는 테스트가 아니라, 결과가 실제 카드 데이터의 조건을 정말
만족하는지 상위 결과를 직접 대조한다.
"""

import pytest

from core import constants as C
from core.card_repository import (
    RELATION_ARCHETYPE,
    RELATION_LISTED_NAME,
    RELATION_REFERENCED_BY,
    RELATION_SERIES,
)
from core.query_parser import (
    SEARCH_MODE_ARCHETYPE,
    SEARCH_MODE_CONDITION,
    SEARCH_MODE_EXACT_NAME,
    SEARCH_MODE_PARTIAL_NAME,
    SEARCH_MODE_RELATED,
)
from tests.conftest import PROJECT_ROOT, requires_official_db

pytestmark = requires_official_db

VERIFY_TOP = 30


@pytest.fixture(scope="module")
def agent():
    from app.main import DeckAgent

    return DeckAgent.build(
        db_path=str(PROJECT_ROOT / "data" / "cards.cdb"),
        script_dir=str(PROJECT_ROOT),
        default_limit=None,
    )


# ===================================================================
# 문제 1: 레벨 / 랭크 / 링크 구분
# ===================================================================


@pytest.mark.parametrize(
    "query,level,race",
    [
        ("레벨 5 기계족", 5, C.RACE_MACHINE),
        ("레벨 4 전사족", 4, C.RACE_WARRIOR),
    ],
)
def test_level_search_returns_only_real_levels(agent, query, level, race):
    """상위 30장을 실제 카드 데이터와 대조한다."""
    parsed, result = agent.search_korean(query)
    assert result.total > 0
    checked = result.cards[:VERIFY_TOP]
    assert len(checked) == VERIFY_TOP

    for card in checked:
        assert card.is_monster, f"{card.display_name()} 는 몬스터가 아니다"
        assert not card.is_xyz, f"{card.display_name()} 는 엑시즈(랭크)다"
        assert not card.is_link, f"{card.display_name()} 는 링크다"
        assert card.monster_level == level, (
            f"{card.display_name()} 의 레벨은 {card.monster_level}"
        )
        assert card.race_mask & race


def test_no_xyz_or_link_anywhere_in_level_results(agent):
    """상위 30장뿐 아니라 결과 전체에 랭크/링크 카드가 없어야 한다."""
    for query in ("레벨 5 기계족", "레벨 4 전사족"):
        _, result = agent.search_korean(query)
        offenders = [c for c in result.cards if c.is_xyz or c.is_link]
        assert offenders == [], [c.display_name() for c in offenders]


def test_rank_search_returns_only_xyz(agent):
    parsed, result = agent.search_korean("랭크 5 기계족")
    assert result.total > 0
    for card in result.cards[:VERIFY_TOP]:
        assert card.is_xyz
        assert card.rank == 5
        assert card.monster_level is None  # 엑시즈에는 레벨이 없다
        assert card.race_mask & C.RACE_MACHINE


def test_link_search_returns_only_link_monsters(agent):
    parsed, result = agent.search_korean("링크 3 기계족")
    assert result.total > 0
    for card in result.cards[:VERIFY_TOP]:
        assert card.is_link
        assert card.link_rating == 3
        assert card.monster_level is None


def test_level_and_rank_results_do_not_overlap(agent):
    _, level5 = agent.search_korean("레벨 5 기계족")
    _, rank5 = agent.search_korean("랭크 5 기계족")
    assert not ({c.id for c in level5.cards} & {c.id for c in rank5.cards})


# ===================================================================
# 문제 2 + 4: 관련 카드 / 카드군 / 이름 검색의 구분
# ===================================================================


def test_related_query_is_not_empty(agent):
    """"오르페골과 관련된 카드" 가 0장이 되면 안 된다."""
    parsed, result = agent.search_korean("오르페골과 관련된 카드")
    assert parsed.search_mode == SEARCH_MODE_RELATED
    assert result.total > 0


def test_related_query_uses_repository_relations(agent):
    """검색 계층이 리포지토리의 관계 기능을 그대로 쓰는지 확인한다."""
    parsed, result = agent.search_korean("오르페골과 관련된 카드")
    direct = agent.repository.relations_for_term("오르페골")
    assert direct is not None
    assert {c.id for c in result.cards} == {r.card.id for r in direct.relations}


def test_relation_types_are_recorded(agent):
    parsed, _ = agent.search_korean("오르페골과 관련된 카드")
    counts = parsed.relation.counts_by_type()
    assert counts.get(RELATION_ARCHETYPE, 0) > 0
    # 근거 없는 관계가 붙어 있으면 안 된다.
    allowed = {
        RELATION_ARCHETYPE,
        RELATION_LISTED_NAME,
        RELATION_REFERENCED_BY,
        RELATION_SERIES,
    }
    assert set(counts) <= allowed
    for relation in parsed.relation.relations:
        assert relation.relation_types


def test_archetype_members_are_verified_against_setcode(agent):
    parsed, result = agent.search_korean("오르페골 카드")
    assert parsed.search_mode == SEARCH_MODE_ARCHETYPE
    assert parsed.relation.names == ["ORCUST"]
    orcust = agent.repository.constants.setcode("ORCUST")
    for card in result.cards:
        assert orcust in card.setcodes, card.display_name()


def test_bare_name_stays_a_name_search(agent):
    """"오르페골" 만 입력하면 카드명 검색이다 (카드군 검색이 아니다)."""
    parsed, result = agent.search_korean("오르페골")
    assert parsed.search_mode == SEARCH_MODE_PARTIAL_NAME
    for card in result.cards:
        assert "오르페골" in (card.name_ko or card.name_en or "")


def test_game_term_plus_카드_is_not_an_archetype(agent):
    """"마법 카드" 는 카드군이 아니라 카드 종류다."""
    parsed, result = agent.search_korean("마법 카드")
    assert parsed.search_mode == SEARCH_MODE_CONDITION
    assert parsed.relation is None
    for card in result.cards[:VERIFY_TOP]:
        assert card.is_spell


def test_search_modes_are_distinguished(agent):
    expected = {
        "마법족의 마을": SEARCH_MODE_EXACT_NAME,
        "오르페골": SEARCH_MODE_PARTIAL_NAME,
        "오르페골 카드": SEARCH_MODE_ARCHETYPE,
        "오르페골과 관련된 카드": SEARCH_MODE_RELATED,
        "레벨 5 기계족": SEARCH_MODE_CONDITION,
    }
    for query, mode in expected.items():
        parsed, _ = agent.search_korean(query)
        assert parsed.search_mode == mode, query


# ===================================================================
# 문제 3: 자연어 기능어가 조각으로 남지 않는다
# ===================================================================


@pytest.mark.parametrize(
    "query",
    [
        "패에서 특수 소환할 수 있는 레벨 4",
        "묘지에서 특수 소환 가능한 카드",
        "기계족 몬스터 찾아줘",
        "빛속성 기계족 알려줘",
    ],
)
def test_filler_expressions_do_not_leak(agent, query):
    parsed, result = agent.search_korean(query)
    assert parsed.unknown_terms == [], parsed.unknown_terms
    assert result.total > 0


def test_filler_removal_does_not_break_exact_card_names(agent):
    """
    '카드' 는 군더더기지만 카드명에 들어 있을 수도 있다.
    정확 일치 검사가 먼저 돌므로 카드명이 우선이어야 한다.
    """
    names = [
        c.name_ko
        for c in agent.repository.all_cards()
        if c.name_ko and c.name_ko.endswith("카드")
    ]
    if not names:
        pytest.skip("이름이 '카드' 로 끝나는 카드가 없음")
    parsed, result = agent.search_korean(names[0])
    assert parsed.search_mode == SEARCH_MODE_EXACT_NAME
    assert result.total >= 1


# ===================================================================
# 기존 기능 회귀
# ===================================================================


def test_previously_working_queries_are_unchanged(agent):
    cases = {
        "마법족의 마을": (SEARCH_MODE_EXACT_NAME, 1),
        "푸른 눈의 백룡": (SEARCH_MODE_EXACT_NAME, 1),
        "K9": (SEARCH_MODE_PARTIAL_NAME, 14),
        "Spellcaster": (SEARCH_MODE_CONDITION, 794),
    }
    for query, (mode, total) in cases.items():
        parsed, result = agent.search_korean(query)
        assert parsed.search_mode == mode, query
        assert result.total == total, f"{query}: {result.total}"


def test_effect_condition_queries_still_verify(agent):
    _, result = agent.search_korean("묘지에서 특수 소환")
    assert result.total > 0
    for card in result.cards[:VERIFY_TOP]:
        assert any(
            "GRAVE" in e.ranges and "SPECIAL_SUMMON" in e.categories
            for e in card.effects
        ), card.display_name()


def test_hand_special_summon_level_4_still_verifies(agent):
    _, result = agent.search_korean("패에서 특수 소환할 수 있는 레벨 4")
    assert result.total > 0
    for card in result.cards[:VERIFY_TOP]:
        assert card.monster_level == 4
        assert (
            card.can_self_special_summon_from_hand
            or card.has_effect_from("HAND", "SPECIAL_SUMMON")
        ), card.display_name()
