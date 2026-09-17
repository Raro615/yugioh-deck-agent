"""
조건 leaf 의 의미 구조화 검증.

세 가지 상태를 구분하는 것이 목적이다.

1. EVALUABLE      — 게임 상태(필드/패/묘지/턴/페이즈)만으로 평가 가능
2. NEEDS_CONTEXT  — 술어와 인자는 알지만 체인·이벤트 문맥이 있어야 평가 가능
3. UNKNOWN        — 안전하게 해석할 수 없음. 원문만 보존

모든 사례는 저장소에 실제로 있는 스크립트에서 가져왔고, 술어 이름만 보고
게임 의미를 추측하지 않는다. 이 테스트는 구현보다 먼저 작성되었다.
"""

import pytest

from analysis import (
    BoolOp,
    EffectAnalyzer,
    EvalReadiness,
    PredicateKind,
    PredicateSubject,
)
from core import constants as C
from tests.conftest import requires_official_db

pytestmark = requires_official_db


@pytest.fixture(scope="module")
def analyzer(repository):
    return EffectAnalyzer(repository)


def predicates_of(analyzer, repository, card_id):
    """카드의 모든 조건 leaf 술어를 모은다."""
    analysis = analyzer.analyze(repository.get(card_id))
    found = []
    for effect in analysis.effects:
        if effect.activation.tree is None:
            continue
        for leaf in effect.activation.tree.leaves():
            if leaf.predicate is not None:
                found.append(leaf.predicate)
    return found


def find(predicates, kind, needle=None):
    for predicate in predicates:
        if predicate.kind is kind and (needle is None or needle in predicate.raw):
            return predicate
    raise AssertionError(f"{kind} ({needle}) 술어를 찾지 못했다")


# ===================================================================
# 1. 평가 가능한 조건 — CardConstraint 로 연결
# ===================================================================


def test_is_setcard_becomes_a_card_constraint(analyzer, repository):
    """라뷰린스 쿠클락: rc:IsSetCard(SET_LABRYNTH)"""
    predicate = find(predicates_of(analyzer, repository, 2511), PredicateKind.CARD_PROPERTY, "IsSetCard")
    assert predicate.constraint is not None
    assert predicate.constraint.setcodes == ["LABRYNTH"]
    assert predicate.readiness is EvalReadiness.EVALUABLE


def test_is_race_becomes_a_card_constraint(analyzer, repository):
    """천화의 감옥: re:GetHandler():IsRace(RACE_CYBERSE)"""
    predicate = find(predicates_of(analyzer, repository, 269510), PredicateKind.CARD_PROPERTY, "IsRace")
    assert predicate.constraint.races == [C.RACE_CYBERSE]


def test_is_attribute_becomes_a_card_constraint(analyzer, repository):
    """해황의 저격병: re:GetHandler():IsAttribute(ATTRIBUTE_WATER)"""
    predicate = find(predicates_of(analyzer, repository, 706925), PredicateKind.CARD_PROPERTY, "IsAttribute")
    assert predicate.constraint.attributes == [C.ATTRIBUTE_WATER]


def test_level_comparison_becomes_a_range(analyzer, repository):
    """라바르 란스로드: c:GetLevel()>4 — 레벨 5 이상이라는 뜻이다."""
    predicate = find(predicates_of(analyzer, repository, 123709), PredicateKind.CARD_PROPERTY, "GetLevel")
    assert predicate.comparison == ">"
    assert predicate.value == 4
    assert predicate.constraint.level_min == 5


def test_is_location_is_evaluable(analyzer, repository):
    """키 마우스: e:GetHandler():IsLocation(LOCATION_GRAVE)"""
    predicate = find(predicates_of(analyzer, repository, 135598), PredicateKind.CARD_LOCATION)
    assert predicate.locations == ["GRAVE"]
    assert predicate.readiness is EvalReadiness.EVALUABLE
    assert predicate.subject is PredicateSubject.SELF


def test_is_faceup_is_evaluable(analyzer, repository):
    """SR 윙 싱크론: c:IsFaceup()"""
    predicate = find(predicates_of(analyzer, repository, 2254222), PredicateKind.CARD_POSITION)
    assert predicate.readiness is EvalReadiness.EVALUABLE


def test_field_spell_check_is_evaluable(analyzer, repository):
    """전설의 어부: Duel.IsEnvironment(CARD_UMI) — 필드에 '바다'가 있는지."""
    predicate = find(predicates_of(analyzer, repository, 3643300), PredicateKind.FIELD_SPELL)
    assert predicate.readiness is EvalReadiness.EVALUABLE
    assert predicate.constraint is not None
    assert predicate.constraint.card_codes  # CARD_UMI 가 ID 로 풀린다


def test_phase_check_is_evaluable(analyzer, repository):
    """패러렐포트 아머: Duel.IsBattlePhase()"""
    predicate = find(predicates_of(analyzer, repository, 879958), PredicateKind.PHASE)
    assert predicate.readiness is EvalReadiness.EVALUABLE


def test_existing_matching_card_is_evaluable(analyzer, repository):
    """EM 스카이 퓨필: Duel.IsExistingMatchingCard(...) — 필드 상태 질의."""
    predicate = find(predicates_of(analyzer, repository, 122520), PredicateKind.CARD_EXISTS)
    assert predicate.readiness is EvalReadiness.EVALUABLE
    assert "MZONE" in predicate.locations


# ===================================================================
# 2. 구조는 알지만 평가에 문맥이 필요한 조건
# ===================================================================


@pytest.mark.parametrize(
    "card_id,kind,needle",
    [
        (2511, PredicateKind.CHAIN_EFFECT_TYPE, "IsTrapEffect"),
        (2511, PredicateKind.CHAIN_EFFECT_TYPE, "IsHasType"),
        (132308, PredicateKind.CHAIN_EFFECT_TYPE, "IsMonsterEffect"),
        (27551, PredicateKind.EVENT_REASON, "IsReason"),
        (27551, PredicateKind.GROUP_CONTAINS, "IsContains"),
        (263926, PredicateKind.GROUP_EXISTS, "IsExists"),
        (983995, PredicateKind.PREVIOUS_POSITION, "IsPreviousPosition"),
        (1003840, PredicateKind.PREVIOUS_CONTROLLER, "IsPreviousControler"),
        (269012, PredicateKind.BATTLE, "IsRelateToBattle"),
        (1287123, PredicateKind.CARD_STATUS, "IsStatus"),
        (131182, PredicateKind.FLAG_EFFECT, "GetFlagEffect"),
        (21441617, PredicateKind.PLAYER_AFFECTED, "IsPlayerAffectedByEffect"),
    ],
)
def test_context_dependent_predicates_are_structured(
    analyzer, repository, card_id, kind, needle
):
    """
    술어와 인자는 읽었지만, 평가하려면 체인이나 이벤트 문맥이 필요하다.
    '해석 실패'와 구분해서 표시해야 한다.
    """
    predicate = find(predicates_of(analyzer, repository, card_id), kind, needle)
    assert predicate.readiness is EvalReadiness.NEEDS_CONTEXT
    assert predicate.raw.strip()


def test_previous_location_keeps_its_location(analyzer, repository):
    """라뷰린스 쿠클락: Card.IsPreviousLocation ... LOCATION_HAND"""
    predicate = find(
        predicates_of(analyzer, repository, 2511), PredicateKind.GROUP_EXISTS
    )
    assert "HAND" in predicate.locations
    assert predicate.readiness is EvalReadiness.NEEDS_CONTEXT


# ===================================================================
# 3. 해석할 수 없는 조건은 원문만 보존
# ===================================================================


def test_unreadable_leaf_is_marked_unknown_not_guessed(analyzer, repository):
    """
    'rp==tp' 처럼 술어가 없는 비교식은 의미를 지어내지 않는다.
    UNKNOWN 으로 두되 원문은 남긴다.
    """
    predicates = predicates_of(analyzer, repository, 2511)
    unknown = [p for p in predicates if p.readiness is EvalReadiness.UNKNOWN]
    assert unknown
    for predicate in unknown:
        assert predicate.kind is PredicateKind.UNKNOWN
        assert predicate.raw.strip()


def test_every_leaf_has_a_predicate(analyzer, repository):
    """
    leaf 는 반드시 술어를 가진다. 해석하지 못했더라도 UNKNOWN 술어가 붙어
    '조건이 없다'와 '조건을 못 읽었다'가 섞이지 않는다.
    """
    for card_id in (2511, 27551, 132308, 122520):
        analysis = analyzer.analyze(repository.get(card_id))
        for effect in analysis.effects:
            if effect.activation.tree is None:
                continue
            for leaf in effect.activation.tree.leaves():
                assert leaf.predicate is not None
                assert leaf.raw.strip()


# ===================================================================
# 구조 보존 — 기존 트리를 깨뜨리지 않는다
# ===================================================================


def test_boolean_tree_is_unchanged(analyzer, repository):
    """leaf 의미를 붙여도 AND/OR/NOT 구조는 그대로여야 한다."""
    analysis = analyzer.analyze(repository.get(2511))
    grave = next(e for e in analysis.effects if e.activation_locations == ["GRAVE"])
    tree = grave.activation.tree
    counts = tree.count_ops()
    assert counts["or"] >= 1
    assert counts["not"] >= 1
    assert tree.depth() >= 3


def test_negation_flows_into_the_predicate(analyzer, repository):
    """NOT 아래의 leaf 는 술어에도 negated 로 표시된다."""
    analysis = analyzer.analyze(repository.get(2511))
    grave = next(e for e in analysis.effects if e.activation_locations == ["GRAVE"])
    negated = [
        leaf.predicate
        for leaf in grave.activation.tree.leaves()
        if leaf.predicate is not None and leaf.predicate.negated
    ]
    assert negated


def test_readiness_counts_are_reported(analyzer, repository):
    analysis = analyzer.analyze(repository.get(2511))
    coverage = analysis.coverage()
    assert coverage["leaf_total"] > 0
    assert (
        coverage["leaf_evaluable"]
        + coverage["leaf_needs_context"]
        + coverage["leaf_unknown"]
        == coverage["leaf_total"]
    )


def test_subject_is_only_inferred_from_engine_names(analyzer, repository):
    """
    엔진이 보장하는 이름(e, eg, re, tp …)에서만 주체를 판정한다.
    스크립트가 임의로 붙인 지역 변수는 LOCAL 로 두고 추측하지 않는다.
    """
    predicates = predicates_of(analyzer, repository, 2511)
    subjects = {p.subject for p in predicates}
    assert PredicateSubject.SELF in subjects or PredicateSubject.CHAIN_CARD in subjects
    for predicate in predicates:
        assert predicate.subject in set(PredicateSubject)
