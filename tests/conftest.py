"""테스트 공용 픽스처."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CARDS_CDB = PROJECT_ROOT / "data" / "cards.cdb"

requires_official_db = pytest.mark.skipif(
    not CARDS_CDB.is_file(),
    reason="cards.cdb 가 없습니다. python -m scripts.fetch_official_db 로 내려받으세요.",
)


@pytest.fixture(scope="session")
def repository():
    """전체 데이터로 만든 리포지토리 (세션 동안 한 번만 만든다)."""
    from core.card_repository import CardRepository

    if not CARDS_CDB.is_file():
        pytest.skip("cards.cdb 없음")
    return CardRepository.build(db_path=CARDS_CDB, script_dir=PROJECT_ROOT)


@pytest.fixture(scope="session")
def engine(repository):
    from core.card_search import CardSearchEngine

    return CardSearchEngine(repository)


@pytest.fixture(scope="session")
def parser():
    from core.query_parser import KoreanQueryParser

    return KoreanQueryParser(default_limit=None)


def read_script(name: str) -> str:
    return (PROJECT_ROOT / name).read_text(encoding="utf-8")
