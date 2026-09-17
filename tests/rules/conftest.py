"""규칙 계층 테스트 공용 픽스처."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DOCUMENT_DIR = PROJECT_ROOT / "data" / "rules" / "documents"
STRUCTURED_DIR = PROJECT_ROOT / "data" / "rules" / "structured"
RULEBOOK_DOC = DOCUMENT_DIR / "sd-rulebook-en-v10.json"

requires_rulebook = pytest.mark.skipif(
    not RULEBOOK_DOC.is_file(),
    reason=(
        "룰북 문서가 없습니다. "
        "python -m scripts.extract_rulebook <룰북.pdf> 로 만드세요."
    ),
)


@pytest.fixture(scope="session")
def rule_repository():
    from rules.rule_repository import RuleRepository

    if not RULEBOOK_DOC.is_file():
        pytest.skip("룰북 문서 없음")
    return RuleRepository.load(DOCUMENT_DIR)


@pytest.fixture(scope="session")
def rule_search(rule_repository):
    from rules.rule_search import RuleSearch

    return RuleSearch(rule_repository)


@pytest.fixture(scope="session")
def structured_rules():
    from rules.structured import load_all

    documents = load_all(STRUCTURED_DIR)
    if not documents:
        pytest.skip("구조화 규칙 없음")
    return documents[0]
