"""
공식 한국어 데이터가 적용된 상태의 검색 동작 검증.

data/ko/ 에 한국어 데이터가 없으면 건너뛴다.
여기 나오는 카드명은 공식 한국어 데이터에서 온 것이며, 임의 번역이 아니다.
"""

import pytest

from tests.conftest import PROJECT_ROOT, requires_official_db

pytestmark = requires_official_db

KO_DATA = PROJECT_ROOT / "data" / "ko" / "ko-KR.json"

requires_korean_data = pytest.mark.skipif(
    not KO_DATA.is_file(),
    reason="한국어 데이터가 없습니다. python -m scripts.fetch_korean_db 로 수집하세요.",
)


@pytest.fixture(scope="module")
def agent():
    from app.main import DeckAgent

    return DeckAgent.build(
        db_path=str(PROJECT_ROOT / "data" / "cards.cdb"),
        script_dir=str(PROJECT_ROOT),
        default_limit=None,
    )


@requires_korean_data
def test_korean_names_are_applied(agent):
    card = agent.repository.get(89631139)  # Blue-Eyes White Dragon
    assert card.name_ko == "푸른 눈의 백룡"
    assert card.display_name() == "푸른 눈의 백룡"
    # 원문은 지우지 않는다.
    assert card.name_en == "Blue-Eyes White Dragon"
    assert card.name_ja == "青眼の白龍"


@requires_korean_data
def test_korean_card_text_is_applied(agent):
    card = agent.repository.get(89631139)
    assert card.desc
    # 공식 한국어 텍스트가 들어가 있어야 한다.
    assert any("가" <= ch <= "힣" for ch in card.desc)


@requires_korean_data
def test_search_by_korean_card_name(agent):
    _, result = agent.search_korean("푸른 눈의 백룡")
    assert result.total >= 1
    assert any(c.id == 89631139 for c in result)


@requires_korean_data
def test_card_name_wins_over_game_term_collision(agent):
    """
    "마법족의 마을" 은 카드명이지만 '마법' 이 카드 종류로 읽힌다.
    실제로 그런 이름의 카드가 있으면 이름 검색이 이겨야 한다.
    """
    parsed, result = agent.search_korean("마법족의 마을")
    assert parsed.filters.name == "마법족의 마을"
    assert parsed.filters.required_types == 0
    assert result.total >= 1
    assert all("마법족의 마을" in (c.name_ko or "") for c in result)


@requires_korean_data
def test_clean_term_query_is_not_hijacked_by_name_search(agent):
    """용어만으로 온전히 해석되는 질의는 이름 검색에 가로채이면 안 된다."""
    parsed, result = agent.search_korean("기계족 빛속성 몬스터")
    assert parsed.filters.name is None
    assert parsed.filters.races
    assert parsed.filters.attributes
    assert result.total > 100


@requires_korean_data
def test_korean_data_covers_most_of_the_official_database(agent):
    cards = agent.repository.all_cards()
    with_korean = [c for c in cards if c.name_ko]
    # 한국 미발매 카드가 있으므로 100% 는 될 수 없다.
    assert len(with_korean) / len(cards) > 0.85


def test_example_queries_still_work_with_korean_names(agent):
    """한국어 데이터 적용 여부와 무관하게 예시 질의는 동작해야 한다."""
    for query in [
        "패에서 특수 소환 가능한 4레벨 몬스터",
        "4레벨 빛속성 기계족 몬스터 중 특수 소환 효과가 있는 카드",
        "묘지에서 효과를 발동하는 카드",
    ]:
        _, result = agent.search_korean(query)
        assert result.total > 0, query
