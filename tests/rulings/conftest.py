"""재정 계층 테스트 공용 픽스처."""

import gzip
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
RULING_DIR = PROJECT_ROOT / "data" / "rulings" / "ocg"
IDENTITY_PATH = PROJECT_ROOT / "data" / "identity" / "cid_map.json"

requires_samples = pytest.mark.skipif(
    not RULING_DIR.is_dir() or not any(RULING_DIR.glob("*.json")),
    reason=(
        "수집된 재정 표본이 없습니다. "
        "python -m scripts.fetch_ocg_rulings --sample 로 만드세요."
    ),
)

requires_identity = pytest.mark.skipif(
    not IDENTITY_PATH.is_file(),
    reason="식별자 매핑이 없습니다. python -m scripts.build_card_identity 로 만드세요.",
)


def fixture_html(name: str) -> str:
    """공식 사이트에서 실제로 받아 둔 페이지. 손대지 않은 원본이다."""
    path = FIXTURE_DIR / f"{name}.html.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="session")
def ruling_repository():
    from rulings.ruling_repository import RulingRepository

    if not RULING_DIR.is_dir() or not any(RULING_DIR.glob("*.json")):
        pytest.skip("재정 표본 없음")
    return RulingRepository.load(RULING_DIR)


@pytest.fixture(scope="session")
def ruling_search(ruling_repository):
    from rulings.ruling_search import RulingSearch

    return RulingSearch(ruling_repository)


@pytest.fixture(scope="session")
def identity():
    from core.card_identity import CardIdentityMapping

    if not IDENTITY_PATH.is_file():
        pytest.skip("식별자 매핑 없음")
    return CardIdentityMapping.load(IDENTITY_PATH)
