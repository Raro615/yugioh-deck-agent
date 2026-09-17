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
    # 공식 DB 원문은 지우지 않는다.
    assert card.name_en == "Blue-Eyes White Dragon"
    # 일반 몬스터는 Lua 스크립트가 없어 일본어명도 없다 (주석에서 오기 때문).
    assert card.script is None
    assert card.name_ja is None


@requires_korean_data
def test_korean_name_coexists_with_japanese_name_from_script(agent):
    """스크립트가 있는 카드는 세 언어 표기를 모두 유지해야 한다."""
    card = agent.repository.get(2511)  # Labrynth Cooclock
    assert card.name_ko == "라뷰린스 쿠클락"
    assert card.name_en == "Labrynth Cooclock"
    assert card.name_ja == "白銀の城の狂時計"


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


@requires_korean_data
def test_original_card_text_survives_korean_overlay(agent):
    """한국어 텍스트를 덮어써도 원문은 desc_en 에 남아야 한다."""
    card = agent.repository.get(46986414)  # Dark Magician
    assert any("가" <= ch <= "힣" for ch in card.desc)
    assert card.desc_en == "The ultimate wizard in terms of attack and defense."


@requires_korean_data
def test_support_race_still_matches_after_korean_overlay(agent):
    """
    종족 서포트 판정은 카드 텍스트를 근거로 한다. 텍스트가 한국어로 바뀌어도
    한국어 표기("마법사족")나 보존된 원문("Spellcaster") 중 하나로 잡혀야 한다.
    """
    from core import constants as C
    from core.card_search import SearchFilters

    result = agent.engine.search(
        SearchFilters(support_races=[C.RACE_SPELLCASTER], effect_categories=["DRAW"])
    )
    assert result.total >= 50
    for card in result.cards[:40]:
        assert (
            card.race_mask & C.RACE_SPELLCASTER
            or "마법사족" in card.desc
            or "Spellcaster" in card.desc_en
        )
