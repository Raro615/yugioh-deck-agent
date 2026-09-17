"""
같은 룰북을 다시 처리하면 같은 결과가 나오는가.

결정론이 깨지면 문서를 다시 만들 때마다 Rule ID 나 본문이 흔들리고,
``RuleRef`` 로 규칙을 가리키는 일 자체가 의미를 잃는다.
"""

import json
import os
from pathlib import Path

import pytest

from tests.rules.conftest import PROJECT_ROOT, RULEBOOK_DOC, requires_rulebook

RULEBOOK_PDF = os.environ.get("YGO_RULEBOOK_PDF")
_candidates = [Path(RULEBOOK_PDF)] if RULEBOOK_PDF else []
_candidates += sorted((PROJECT_ROOT / "data" / "rules" / "sources").glob("*.pdf"))

pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF 없음 (추출기 전용 의존성)")

requires_pdf = pytest.mark.skipif(
    not any(path.is_file() for path in _candidates),
    reason=(
        "원본 룰북 PDF 가 없습니다. 저작물이라 저장소에 넣지 않습니다. "
        "YGO_RULEBOOK_PDF 환경변수나 data/rules/sources/ 로 지정하세요."
    ),
)


def _pdf_path() -> Path:
    return next(path for path in _candidates if path.is_file())


@requires_pdf
def test_reprocessing_the_same_pdf_gives_identical_sections():
    from scripts.extract_rulebook import build_document

    common = dict(
        doc_id="sd-rulebook-en-v10",
        title="t",
        source="s",
        version="10",
        retrieved_at="2000-01-01T00:00:00Z",
    )
    first, registry, problems = build_document(_pdf_path(), **common)
    assert problems == []
    second, _, _ = build_document(_pdf_path(), registry=registry, **common)
    assert first == second


@requires_pdf
def test_reprocessing_matches_the_checked_in_document():
    """저장된 문서가 지금 추출기로 다시 만든 것과 같아야 한다."""
    from scripts.extract_rulebook import build_document

    stored = json.loads(RULEBOOK_DOC.read_text(encoding="utf-8"))
    index_path = PROJECT_ROOT / "data" / "rules" / "index" / "rule_ids.json"
    registry = json.loads(index_path.read_text(encoding="utf-8"))["ids"]

    rebuilt, _, problems = build_document(
        _pdf_path(),
        doc_id=stored["document"]["doc_id"],
        title=stored["document"]["title"],
        source=stored["document"]["source"],
        version=stored["document"]["version"],
        registry=registry,
        retrieved_at=stored["document"]["retrieved_at"],
    )
    assert problems == []
    assert rebuilt["document"] == stored["document"]
    assert rebuilt["sections"] == stored["sections"]


@requires_pdf
def test_document_hash_matches_the_source_pdf():
    from scripts.extract_rulebook import file_hash

    stored = json.loads(RULEBOOK_DOC.read_text(encoding="utf-8"))
    assert file_hash(_pdf_path()) == stored["document"]["document_hash"]


@requires_pdf
def test_rule_ids_survive_a_reprocess_even_if_sections_move():
    """
    ID 고정 장치가 실제로 동작하는지. 등록부에 이미 있는 항목은 문서 순서가
    바뀌어도 같은 ID 를 유지해야 한다.
    """
    from scripts.extract_rulebook import assign_rule_ids, ExtractedSection

    def make(category: str, title: str) -> ExtractedSection:
        return ExtractedSection(
            rule_id="", chapter=1, level=1, category=category, title=title,
            title_source="heading", anchor=title, printed_pages=[1], pdf_pages=[1],
            lines=[title],
        )

    first = [make("CHAIN", "WHAT IS A CHAIN?"), make("CHAIN", "SPELL SPEED")]
    registry = assign_rule_ids(first)
    assert [s.rule_id for s in first] == ["RULE-CHAIN-001", "RULE-CHAIN-002"]

    # 새 판본에서 앞에 규칙이 하나 끼어들었다.
    second = [
        make("CHAIN", "NEW RULE ABOUT CHAINS"),
        make("CHAIN", "WHAT IS A CHAIN?"),
        make("CHAIN", "SPELL SPEED"),
    ]
    assign_rule_ids(second, registry)
    assert [s.rule_id for s in second] == [
        "RULE-CHAIN-003",  # 새 항목만 새 번호
        "RULE-CHAIN-001",  # 기존 항목은 그대로
        "RULE-CHAIN-002",
    ]


@requires_rulebook
def test_stored_document_is_stable_json():
    """파일을 다시 써도 바이트가 같아야 한다 (키 순서 · 들여쓰기 고정)."""
    raw = RULEBOOK_DOC.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert json.dumps(parsed, ensure_ascii=False, indent=1) + "\n" == raw
