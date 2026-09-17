"""룰북이 정상적으로 적재되고, 원문이 손상되지 않았는지."""

import json

import pytest

from rules.rule_model import RuleCategory, RuleRef
from rules.rule_repository import RuleDataError, RuleRepository, load_document
from tests.rules.conftest import DOCUMENT_DIR, RULEBOOK_DOC, requires_rulebook


# ----------------------------------------------------------------------
# 적재
# ----------------------------------------------------------------------
@requires_rulebook
def test_rulebook_loads(rule_repository):
    assert len(rule_repository) > 0
    assert len(rule_repository.documents) == 1
    document = rule_repository.documents[0]
    assert document.doc_id == "sd-rulebook-en-v10"
    assert document.title.startswith("Yu-Gi-Oh!")


@requires_rulebook
def test_document_provenance_is_complete(rule_repository):
    """규칙 provenance 는 카드 provenance 와 별개로 완전해야 한다."""
    provenance = rule_repository.documents[0].provenance
    assert provenance.source
    assert provenance.version == "10"
    assert provenance.language == "en"
    assert provenance.document_hash.startswith("sha256:")
    assert len(provenance.document_hash) == len("sha256:") + 64
    assert provenance.retrieved_at.endswith("Z")
    assert provenance.extractor == "scripts/extract_rulebook.py"


@requires_rulebook
def test_rule_provenance_authority_beats_supplementary():
    """어떤 보조 출처도 공식 룰을 덮어쓰지 못한다."""
    from rules.rule_model import RULE_AUTHORITY

    assert RULE_AUTHORITY["official_rulebook"] < RULE_AUTHORITY["lua_script"]
    assert RULE_AUTHORITY["official_rulebook"] < RULE_AUTHORITY["supplementary"]
    assert min(RULE_AUTHORITY.values()) == RULE_AUTHORITY["official_rulebook"]


def test_unknown_schema_version_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(RuleDataError, match="schema_version"):
        load_document(path)


def test_missing_document_directory_is_an_explicit_error(tmp_path):
    with pytest.raises(RuleDataError):
        RuleRepository.load(tmp_path / "nope")


# ----------------------------------------------------------------------
# Rule ID
# ----------------------------------------------------------------------
@requires_rulebook
def test_rule_ids_are_unique(rule_repository):
    ids = [section.rule_id for section in rule_repository]
    assert len(ids) == len(set(ids))


@requires_rulebook
def test_every_rule_id_is_well_formed(rule_repository):
    for section in rule_repository:
        ref = RuleRef(section.rule_id)  # 형식이 틀리면 여기서 터진다
        assert ref.category is section.category
        assert ref.number >= 1


@requires_rulebook
def test_rule_id_numbers_are_dense_within_each_category(rule_repository):
    """분류마다 1부터 빠짐없이 매겨져야 한다 (구멍은 부여 버그의 신호)."""
    for category in RuleCategory:
        numbers = sorted(
            RuleRef(s.rule_id).number for s in rule_repository.by_category(category)
        )
        if numbers:
            assert numbers == list(range(1, len(numbers) + 1)), category


@requires_rulebook
def test_rule_ids_are_stable_against_the_checked_in_index():
    """
    ``data/rules/index/rule_ids.json`` 이 ID 고정의 근거다. 문서와 어긋나면
    같은 ID 가 다른 규칙을 가리키게 된다.
    """
    from tests.rules.conftest import PROJECT_ROOT

    index_path = PROJECT_ROOT / "data" / "rules" / "index" / "rule_ids.json"
    if not index_path.is_file():
        import pytest as _pytest

        _pytest.skip("ID 인덱스 없음")
    index = json.loads(index_path.read_text(encoding="utf-8"))["ids"]
    document = json.loads(RULEBOOK_DOC.read_text(encoding="utf-8"))
    assert set(index.values()) == {s["rule_id"] for s in document["sections"]}
    assert len(set(index.values())) == len(index)


# ----------------------------------------------------------------------
# 섹션 접근
# ----------------------------------------------------------------------
@requires_rulebook
def test_every_section_is_reachable_by_id(rule_repository):
    for section in rule_repository:
        assert rule_repository.get(section.rule_id) is section
        assert rule_repository[section.rule_id] is section
        assert section.rule_id in rule_repository


@requires_rulebook
def test_missing_rule_id_raises_rather_than_returning_none(rule_repository):
    assert rule_repository.get("RULE-CHAIN-999") is None
    with pytest.raises(KeyError):
        rule_repository.require("RULE-CHAIN-999")


@requires_rulebook
def test_section_tree_is_consistent(rule_repository):
    assert rule_repository.check_integrity() == []


@requires_rulebook
def test_path_to_a_nested_section(rule_repository):
    path = rule_repository.path_to("RULE-CHAIN-004")  # Spell Speed 1
    assert [s.rule_id for s in path] == [
        "RULE-CHAIN-002",  # SPELL SPEED
        "RULE-CHAIN-003",  # Spell Speeds
        "RULE-CHAIN-004",  # Spell Speed 1
    ]


@requires_rulebook
def test_every_section_has_a_source_reference(rule_repository):
    for section in rule_repository:
        reference = section.source_reference
        assert reference.document == "sd-rulebook-en-v10"
        assert reference.printed_pages, section.rule_id
        assert reference.pdf_pages, section.rule_id
        assert all(1 <= page <= 55 for page in reference.printed_pages)


# ----------------------------------------------------------------------
# 원문 무결성
# ----------------------------------------------------------------------
@requires_rulebook
def test_no_section_is_empty(rule_repository):
    for section in rule_repository:
        assert section.text.strip(), section.rule_id


@requires_rulebook
def test_section_text_starts_at_its_printed_heading(rule_repository):
    """본문은 룰북에 인쇄된 제목 줄에서 시작한다 — 임의로 잘라내지 않았다."""
    for section in rule_repository:
        if section.category is RuleCategory.TERM:
            continue
        first_line = section.text.splitlines()[0]
        stripped = "".join(ch for ch in first_line if not "" <= ch <= "")
        assert " ".join(stripped.split()) == " ".join(
            section.anchor.split()
        ), section.rule_id


# 본문 글꼴의 올드스타일 숫자 때문에 추출기가 숫자를 '•' 로 바꿔버리는 자리들.
# 여기가 깨지면 규칙의 의미 자체가 사라진다.
NUMERIC_PHRASES = (
    ("RULE-CHAIN-002", "Spell Speed 2 or higher"),
    ("RULE-CHAIN-004", "cannot be Chain Link 2 or higher"),
    ("RULE-CHAIN-005", "a Spell Speed 1 or 2 effect"),
    ("RULE-EFFECT-001", "Monsters with 2000 or less ATK"),
    ("RULE-SUMMON-011", "require 2 Tributes"),
    ("RULE-SUMMON-008", "categorized into 2 groups"),
    ("RULE-GAME-003", "best 2-out-of-3"),
    ("RULE-CHAIN-010", "If there are 2 or more effects"),
    ("RULE-DECK-005", "Semi-Limited cards are restricted to 2 copies"),
)


@requires_rulebook
@pytest.mark.parametrize("rule_id,phrase", NUMERIC_PHRASES)
def test_numbers_survived_extraction(rule_repository, rule_id, phrase):
    section = rule_repository.require(rule_id)
    assert phrase in section.normalized_text, (
        f"{rule_id} 에서 {phrase!r} 가 사라졌습니다. "
        "PDF 추출기가 올드스타일 숫자를 잘못 읽었을 수 있습니다."
    )


@requires_rulebook
def test_no_stray_bullet_replaced_a_digit(rule_repository):
    """숫자가 있어야 할 자리에 '•' 가 남아 있으면 안 된다."""
    import re

    pattern = re.compile(
        r"(Spell Speed|Chain Link|Main Phase|Tributes?|copies|groups)\s*•"
        r"|•\s*(Tributes|out-of|000)"
    )
    for section in rule_repository:
        assert not pattern.search(section.normalized_text), section.rule_id


@requires_rulebook
def test_known_verbatim_passages(rule_repository):
    """원문을 그대로 들고 있는지 몇 군데 직접 확인한다."""
    chain = rule_repository.require("RULE-CHAIN-007")
    assert (
        "the outcome is resolved starting with the most recent card to be "
        "activated at the top of the Chain and proceeding down to Chain Link 1"
        in chain.normalized_text
    )
    tribute = rule_repository.require("RULE-TERM-023")
    assert (
        "A monster sent to the Graveyard by Tributing is not treated as “destroyed.”"
        in tribute.normalized_text
    )
    priority = rule_repository.require("RULE-CHAIN-009")
    assert "The turn player always starts with Priority" in priority.normalized_text
