"""규칙 검색 — 축별 조회와 요구된 질문들."""

import pytest

from rules.rule_model import RuleCategory
from rules.rule_search import KO_QUERY_TERMS, RuleSearch, expand_query
from tests.rules.conftest import requires_rulebook


@requires_rulebook
def test_search_by_rule_id(rule_search):
    section = rule_search.by_rule_id("RULE-CHAIN-001")
    assert section is not None and section.title == "WHAT IS A CHAIN?"
    assert rule_search.by_rule_id("rule-chain-001") is section  # 대소문자 무관
    assert rule_search.by_rule_id("RULE-CHAIN-999") is None


@requires_rulebook
def test_search_by_title(rule_search):
    titles = {s.title for s in rule_search.by_title("spell speed")}
    assert "SPELL SPEED" in titles
    assert "Spell Speed 1" in titles


@requires_rulebook
def test_search_by_category(rule_search):
    chain = rule_search.by_category(RuleCategory.CHAIN)
    assert chain and all(s.category is RuleCategory.CHAIN for s in chain)
    assert rule_search.by_category("CHAIN") == chain


@requires_rulebook
def test_search_by_text_crosses_printed_line_breaks(rule_search):
    """
    원문은 인쇄된 줄바꿈을 그대로 갖고 있다. 구절 검색이 줄을 넘어서도
    걸려야 쓸모가 있다.
    """
    hits = rule_search.by_text("resolved starting with the most recent card")
    assert [s.rule_id for s in hits] == ["RULE-CHAIN-007"]
    # 실제로 그 구절은 원문에서 줄바꿈에 걸쳐 있다.
    assert "\n" in rule_search.repository.require("RULE-CHAIN-007").text


@requires_rulebook
def test_within_section_collects_the_whole_subtree(rule_search):
    ids = {s.rule_id for s in rule_search.within_section("RULE-CHAIN-002")}
    assert ids == {
        "RULE-CHAIN-002",  # SPELL SPEED
        "RULE-CHAIN-003",  # Spell Speeds
        "RULE-CHAIN-004",
        "RULE-CHAIN-005",
        "RULE-CHAIN-006",
    }


@requires_rulebook
def test_search_can_be_scoped(rule_search):
    unscoped = rule_search.search("effect", limit=None)
    scoped = rule_search.search("effect", category=RuleCategory.CHAIN, limit=None)
    assert scoped and len(scoped) < len(unscoped)
    assert all(h.section.category is RuleCategory.CHAIN for h in scoped)

    within = rule_search.search("effect", within="RULE-CHAIN-002", limit=None)
    assert {h.rule_id for h in within} <= {
        s.rule_id for s in rule_search.within_section("RULE-CHAIN-002")
    }


@requires_rulebook
def test_hits_carry_their_source_and_excerpt(rule_search):
    hit = rule_search.search("chain link resolution order")[0]
    assert hit.matched_terms
    assert hit.excerpt
    assert hit.section.source_reference.printed_pages
    # 발췌는 원문에서 잘라낸 것이지 다시 쓴 것이 아니다.
    assert hit.excerpt.strip("… ") in hit.section.normalized_text


# 요구사항 6 에 적힌 질문들. 관련 규칙이 상위에 나와야 한다.
REQUIRED_QUESTIONS = (
    ("체인이 어떻게 처리되는가?", {"RULE-CHAIN-001", "RULE-CHAIN-007"}),
    ("데미지 스텝에서 어떤 효과를 발동할 수 있는가?", {"RULE-BATTLE-006", "RULE-BATTLE-007"}),
    ("일반 소환과 특수 소환의 차이는?", {"RULE-SUMMON-009", "RULE-SUMMON-013"}),
    ("타겟과 비타겟 효과의 차이는?", {"RULE-EFFECT-002", "RULE-BATTLE-009", "RULE-EFFECT-003"}),
    ("How does a Chain resolve?", {"RULE-CHAIN-007", "RULE-CHAIN-001"}),
)


@requires_rulebook
@pytest.mark.parametrize("question,expected", REQUIRED_QUESTIONS)
def test_required_questions_surface_relevant_rules(rule_search, question, expected):
    found = {hit.rule_id for hit in rule_search.search(question, limit=5)}
    assert found & expected, f"{question!r} -> {sorted(found)}"


@requires_rulebook
def test_korean_query_terms_expand_to_rulebook_vocabulary():
    """
    룰북은 영어 원문 그대로다. 한국어 질의는 **번역이 아니라 별칭표**를 거쳐
    룰북 어휘로 바뀐다.
    """
    assert "chain" in expand_query("체인이 어떻게 처리되는가?")
    assert "damage" in expand_query("데미지 스텝")
    assert "summon" in expand_query("특수소환")
    # 표에 없는 한국어는 조용히 버린다 — 없는 뜻을 지어내지 않는다.
    assert expand_query("고구마") == []


@requires_rulebook
def test_korean_alias_targets_actually_occur_in_the_rulebook(rule_search):
    """별칭이 가리키는 영어 낱말이 실제로 룰북에 있어야 한다."""
    corpus = " ".join(s.normalized_text.lower() for s in rule_search.repository)
    missing = sorted(
        {
            word
            for words in KO_QUERY_TERMS.values()
            for word in words
            if word not in corpus
        }
    )
    assert missing == [], f"룰북에 없는 별칭 대상: {missing}"


@requires_rulebook
def test_empty_and_stopword_only_queries_return_nothing(rule_search):
    assert rule_search.search("") == []
    assert rule_search.search("the of a to") == []
