"""
카드 관계 모델 검증.

가장 중요한 구분: '같은 카드군이다'(소속)와 '상호작용한다'(관계)는 다르다.
카드 텍스트에 이름이 등장한다는 이유만으로 카드군 소속으로 판정하면 안 된다.

이 테스트는 구현보다 먼저 작성되었다.
"""

import pytest

from analysis import RelationshipBuilder, RelationshipKind
from tests.conftest import PROJECT_ROOT, requires_official_db

pytestmark = requires_official_db

CYMBAL_SKELETON = 21441617  # 오르페골 스켈레촌 (ORCUST 소속)
WORLD_WAND = 93920420  # 성유물－『성장』 (WORLD_LEGACY 소속, 오르페골을 지명)
REINFORCEMENT = 32807846  # 증원 (카드군 없음, 전사족 서치)


@pytest.fixture(scope="module")
def builder(repository):
    from analysis import EffectAnalyzer

    return RelationshipBuilder(repository, EffectAnalyzer(repository))


def kinds_between(relationships, target_id):
    return {r.kind for r in relationships if r.target_card_id == target_id}


# ===================================================================
# 소속과 관계의 구분
# ===================================================================


def test_archetype_membership_comes_from_setcode(builder, repository):
    rels = builder.for_card(CYMBAL_SKELETON)
    memberships = [r for r in rels if r.is_membership]
    assert memberships, "카드군 소속이 하나는 있어야 한다"
    for relation in memberships:
        assert relation.kind is RelationshipKind.ARCHETYPE
        assert relation.target_archetype is not None
        # 소속 판정의 근거는 공식 setcode 여야 한다.
        assert relation.evidence.startswith("setcode")


def test_naming_an_archetype_is_not_membership(builder, repository):
    """
    성유물－『성장』 은 성유물 카드군이고, 카드 텍스트가 오르페골을 지명할 뿐이다.
    ORCUST 소속으로 판정하면 안 된다.
    """
    rels = builder.for_card(WORLD_WAND)
    orcust = [r for r in rels if r.target_archetype == "ORCUST"]
    assert orcust, "오르페골과의 관계 자체는 있어야 한다"

    # 핵심: 오르페골을 지명하고 실제로 다루기까지 하지만, 소속은 아니다.
    for relation in orcust:
        assert relation.is_membership is False
    assert any(r.kind is RelationshipKind.SERIES for r in orcust)

    memberships = {r.target_archetype for r in rels if r.is_membership}
    assert memberships == {"WORLD_LEGACY"}, memberships


def test_interaction_with_another_archetype_is_recorded(builder):
    """
    성유물－『성장』은 제외된 오르페골 몬스터를 특수 소환한다.
    소속이 아니라는 이유로 이 상호작용까지 버리면 안 된다.
    """
    rels = builder.for_card(WORLD_WAND)
    summons = [
        r
        for r in rels
        if r.kind is RelationshipKind.SUMMONS and r.target_archetype == "ORCUST"
    ]
    assert summons
    assert summons[0].from_location == "REMOVED"
    assert summons[0].to_location == "MZONE"


def test_membership_and_interaction_are_separable(builder, repository):
    rels = builder.for_card(CYMBAL_SKELETON)
    assert any(r.is_membership for r in rels)
    assert any(not r.is_membership for r in rels)
    # 두 집합이 kind 로 확실히 갈린다.
    for relation in rels:
        assert relation.is_membership == (
            relation.kind is RelationshipKind.ARCHETYPE
        )


# ===================================================================
# 효과에서 유도되는 관계
# ===================================================================


def test_effect_derived_relationship_kinds(builder, repository):
    """오르페골 스켈레촌은 오르페골 몬스터를 특수 소환한다."""
    rels = builder.for_card(CYMBAL_SKELETON)
    summons = [r for r in rels if r.kind is RelationshipKind.SUMMONS]
    assert summons
    relation = summons[0]
    assert relation.target_archetype == "ORCUST"
    assert relation.from_location == "GRAVE"
    assert relation.to_location == "MZONE"


def test_search_relationship_carries_the_constraint(builder, repository):
    """증원은 특정 카드가 아니라 '조건에 맞는 카드'를 서치한다."""
    rels = builder.for_card(REINFORCEMENT)
    searches = [r for r in rels if r.kind is RelationshipKind.SEARCHES]
    assert searches
    relation = searches[0]
    assert relation.target_card_id is None  # 특정 카드 지정이 아니다
    assert relation.constraint is not None
    assert relation.from_location == "DECK"
    assert relation.to_location == "HAND"


def test_listed_name_relationship_points_at_a_specific_card(builder, repository):
    rels = builder.for_card(CYMBAL_SKELETON)
    listed = [r for r in rels if r.kind is RelationshipKind.LISTED_NAME]
    for relation in listed:
        assert relation.target_card_id is not None


# ===================================================================
# 콤보 탐색을 위한 구조
# ===================================================================


def test_relationships_expose_state_transitions(builder, repository):
    """
    콤보 탐색은 '어떤 카드를 어디에서 어디로 옮기는가'를 필요로 한다.
    이동을 일으키는 관계는 출발지와 도착지를 가져야 한다.
    """
    moving = {
        RelationshipKind.SUMMONS,
        RelationshipKind.SEARCHES,
        RelationshipKind.SENDS_TO_GRAVE,
        RelationshipKind.BANISHES,
    }
    for card_id in (CYMBAL_SKELETON, REINFORCEMENT):
        for relation in builder.for_card(card_id):
            if relation.kind in moving:
                assert relation.to_location is not None, relation


def test_relationship_records_its_evidence(builder, repository):
    for relation in builder.for_card(CYMBAL_SKELETON):
        assert relation.evidence, relation
        assert relation.source_card_id == CYMBAL_SKELETON


def test_builder_does_not_touch_the_search_layer(repository):
    """분석 계층은 기존 검색 계층을 바꾸지 않는다."""
    from core.card_search import CardSearchEngine, SearchFilters

    engine = CardSearchEngine(repository)
    before = engine.search(SearchFilters(name="오르페골")).total
    from analysis import EffectAnalyzer, RelationshipBuilder

    RelationshipBuilder(repository, EffectAnalyzer(repository)).for_card(
        CYMBAL_SKELETON
    )
    after = engine.search(SearchFilters(name="오르페골")).total
    assert before == after


def test_cards_that_can_put_a_card_into_play_are_findable(builder, repository):
    """
    콤보 탐색의 기본 질의: '이 카드군 몬스터를 묘지에서 꺼낼 수 있는 카드'.
    관계 그래프로 답할 수 있어야 한다.
    """
    found = builder.find_sources(
        archetype="ORCUST",
        kind=RelationshipKind.SUMMONS,
        from_location="GRAVE",
    )
    assert CYMBAL_SKELETON in {r.source_card_id for r in found}
