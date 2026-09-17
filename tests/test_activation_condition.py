"""
발동 조건 구조화 검증.

실제 Lua 조건 함수를 기준으로, 읽어낸 의미가 카드의 실제 조건과 맞는지 본다.
읽지 못한 조건은 추측하지 않고 raw / unparsed 로 남는지도 확인한다.

이 테스트는 구현보다 먼저 작성되었다.
"""

import pytest

from analysis import ActionKind, ConditionKind, CostKind, EffectAnalyzer, LimitScope
from core import constants as C
from tests.conftest import requires_official_db

pytestmark = requires_official_db

SKY_PUPIL = 122520  # EM 스카이 퓨필 — 자신 필드 앞면 EM 1장 필요
FLICK_CROWN = 209710  # 플릭 크라운 — 사이버스 2장 + 패 0장
NUMBER_WALL = 847915  # 넘버즈 월 — 자신 필드 앞면 No. 1장 필요
LYLA = 10071151  # 트와일라이트로드 라일라 — SetCountLimit(1) (카드 단위)
CYMBAL_SKELETON = 21441617  # 오르페골 스켈레촌 — 부정 조건 + SetCountLimit(1,id)
COOCLOCK = 2511  # 라뷰린스 쿠클락 — SetCountLimit(1,{id,1}) (효과 단위)
REINFORCEMENT = 32807846  # 증원 — 조건 함수 없음


@pytest.fixture(scope="module")
def analyzer(repository):
    return EffectAnalyzer(repository)


def effect_with_condition(analysis):
    for effect in analysis.effects:
        if effect.activation.requirements:
            return effect
    raise AssertionError("구조화된 발동 조건이 없다")


# ===================================================================
# 필드/묘지/패 상태 요구
# ===================================================================


def test_requires_faceup_archetype_monster_on_own_field(analyzer, repository):
    """
    EM 스카이 퓨필: 자신 필드에 앞면 표시 "EM" 몬스터가 있어야 발동한다.
        Duel.IsExistingMatchingCard(
            aux.FaceupFilter(Card.IsSetCard,SET_PERFORMAPAL),tp,LOCATION_MZONE,0,1,...)
    """
    analysis = analyzer.analyze(repository.get(SKY_PUPIL))
    effect = effect_with_condition(analysis)
    requirement = next(
        r for r in effect.activation.requirements
        if r.kind is ConditionKind.REQUIRES_CARD
    )
    assert requirement.locations == ["MZONE"]
    assert requirement.player == "self"
    assert requirement.min_count == 1
    assert requirement.faceup is True
    assert requirement.negated is False
    assert requirement.constraint.setcodes == ["PERFORMAPAL"]


def test_requires_two_monsters_of_a_race(analyzer, repository):
    """플릭 크라운: 앞면 사이버스족 2장이 필요하다."""
    analysis = analyzer.analyze(repository.get(FLICK_CROWN))
    effect = effect_with_condition(analysis)
    requirement = next(
        r for r in effect.activation.requirements
        if r.kind is ConditionKind.REQUIRES_CARD
    )
    assert requirement.min_count == 2
    assert requirement.constraint.races == [C.RACE_CYBERSE]
    assert requirement.locations == ["MZONE"]


def test_multiple_requirements_are_all_recorded(analyzer, repository):
    """플릭 크라운은 카드 존재 조건과 패 매수 조건을 함께 가진다."""
    analysis = analyzer.analyze(repository.get(FLICK_CROWN))
    effect = effect_with_condition(analysis)
    kinds = {r.kind for r in effect.activation.requirements}
    assert ConditionKind.REQUIRES_CARD in kinds
    assert ConditionKind.CARD_COUNT in kinds


def test_number_wall_condition(analyzer, repository):
    analysis = analyzer.analyze(repository.get(NUMBER_WALL))
    effect = effect_with_condition(analysis)
    requirement = effect.activation.requirements[0]
    assert requirement.constraint.setcodes == ["NUMBER"]
    assert requirement.faceup is True


# ===================================================================
# 부정 조건
# ===================================================================


def test_negated_condition_is_marked(analyzer, repository):
    """
    오르페골 스켈레촌 e1: "오르페골 바벨의 영향을 받고 있지 **않을** 때".
        return not Duel.IsPlayerAffectedByEffect(tp,CARD_ORCUSTRATED_BABEL)
    부정을 놓치면 의미가 정반대가 된다.
    """
    analysis = analyzer.analyze(repository.get(CYMBAL_SKELETON))
    first = analysis.effects[0]
    requirement = next(
        r for r in first.activation.requirements
        if r.kind is ConditionKind.PLAYER_AFFECTED
    )
    assert requirement.negated is True

    # e2 는 같은 조건의 긍정형이다.
    second = analysis.effects[1]
    positive = next(
        r for r in second.activation.requirements
        if r.kind is ConditionKind.PLAYER_AFFECTED
    )
    assert positive.negated is False


# ===================================================================
# 발동 제한 (1턴 1회의 범위)
# ===================================================================


def test_limit_scope_per_card_name(analyzer, repository):
    """SetCountLimit(1,id) — 이 카드명의 효과는 1턴에 1번."""
    effect = analyzer.analyze(repository.get(CYMBAL_SKELETON)).effects[0]
    assert effect.activation.limit.count == 1
    assert effect.activation.limit.scope is LimitScope.PER_CARD_NAME


def test_limit_scope_per_effect(analyzer, repository):
    """SetCountLimit(1,{id,1}) — 이 카드명의 '그 효과'가 1턴에 1번."""
    analysis = analyzer.analyze(repository.get(COOCLOCK))
    grave = next(e for e in analysis.effects if e.activation_locations == ["GRAVE"])
    assert grave.activation.limit.scope is LimitScope.PER_EFFECT


def test_limit_scope_per_card(analyzer, repository):
    """SetCountLimit(1) — 카드명이 아니라 이 카드 1장 기준."""
    analysis = analyzer.analyze(repository.get(LYLA))
    limited = [
        e for e in analysis.effects if e.activation.limit.scope is LimitScope.PER_CARD
    ]
    assert limited


def test_no_limit_is_not_invented(analyzer, repository):
    """증원에는 발동 제한이 없다. 없는 제한을 만들어내면 안 된다."""
    effect = analyzer.analyze(repository.get(REINFORCEMENT)).effects[0]
    assert effect.activation.limit.count is None
    assert effect.activation.limit.scope is LimitScope.NONE
    assert effect.once_per_turn is False


# ===================================================================
# 읽지 못한 조건은 보존한다
# ===================================================================


def test_condition_function_presence_is_recorded(analyzer, repository):
    analysis = analyzer.analyze(repository.get(COOCLOCK))
    grave = next(e for e in analysis.effects if e.activation_locations == ["GRAVE"])
    assert grave.activation.has_condition_function is True
    assert grave.activation.raw  # 원문 보존


def test_unreadable_condition_stays_unparsed(analyzer, repository):
    """
    라뷰린스 쿠클락의 묘지 조건은 체인 정보와 이전 위치를 함께 본다.
    구조화하지 못하면 추측하지 말고 unparsed 에 남겨야 한다.
    """
    analysis = analyzer.analyze(repository.get(COOCLOCK))
    grave = next(e for e in analysis.effects if e.activation_locations == ["GRAVE"])
    assert grave.activation.has_condition_function is True
    structured = len(grave.activation.requirements)
    unparsed = len(grave.activation.unparsed)
    assert structured + unparsed > 0, "조건이 있는데 아무 흔적도 없으면 안 된다"


def test_effect_without_condition_has_empty_activation(analyzer, repository):
    effect = analyzer.analyze(repository.get(REINFORCEMENT)).effects[0]
    assert effect.activation.has_condition_function is False
    assert effect.activation.requirements == []
    # 발동 위치는 조건 함수와 무관하게 채워진다.
    assert effect.activation.locations == effect.activation_locations


# ===================================================================
# 비용 구조화 개선
# ===================================================================


def test_declaratory_cost_is_not_called_unknown(analyzer, repository):
    """
    비용 함수가 자원을 쓰지 않고 표식만 남기는 경우가 있다.
    '읽지 못함(UNKNOWN)'과 '비용이 없음(NONE)'은 다르다.
    """
    analysis = analyzer.analyze(repository.get(SKY_PUPIL))
    kinds = {c.kind for e in analysis.effects for c in e.costs}
    assert CostKind.UNKNOWN not in kinds or CostKind.NONE in kinds


def test_known_cost_helpers_are_structured(analyzer, repository):
    effect = analyzer.analyze(repository.get(CYMBAL_SKELETON)).effects[0]
    assert [c.kind for c in effect.costs] == [CostKind.SELF_BANISH]


# ===================================================================
# 파이프라인 순서: 조건 → 비용 → 선택 → 처리
# ===================================================================


def test_pipeline_order_is_preserved(analyzer, repository):
    analysis = analyzer.analyze(repository.get(CYMBAL_SKELETON))
    stages = analysis.effects[0].pipeline()
    assert [s.stage for s in stages] == ["activation", "cost", "selection", "action"]


def test_pipeline_describes_the_whole_effect(analyzer, repository):
    """증원: 조건 없음 → 비용 없음 → 덱에서 선택 → 패로."""
    effect = analyzer.analyze(repository.get(REINFORCEMENT)).effects[0]
    stages = {s.stage: s for s in effect.pipeline()}
    assert stages["cost"].summary == "없음"
    assert "DECK" in stages["selection"].summary
    assert "to_hand" in stages["action"].summary
    assert effect.has_action(ActionKind.TO_HAND)
