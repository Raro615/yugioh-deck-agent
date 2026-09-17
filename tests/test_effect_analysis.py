"""
효과 분석 계층 검증.

실제 카드 스크립트를 기준으로 발동 조건 / 비용 / 대상 / 결과를 대조한다.
구조화하지 못한 부분은 억지로 추론하지 않고 unparsed 로 남는지도 확인한다.

이 테스트는 구현보다 먼저 작성되었다.
"""

import pytest

from analysis import ActionKind, CostKind, EffectAnalyzer
from core import constants as C
from tests.conftest import PROJECT_ROOT, requires_official_db

pytestmark = requires_official_db

# 분석 대상 카드 (실제 저장소에 있는 스크립트)
REINFORCEMENT = 32807846  # 증원 — 덱에서 레벨 4 이하 전사족 서치
CYMBAL_SKELETON = 21441617  # 오르페골 스켈레촌 — 자신 제외 비용, 묘지에서 특수 소환
COOCLOCK = 2511  # 라뷰린스 쿠클락 — 패에서 버리는 비용 + 묘지 트리거
TEN_THOUSAND_DRAGON = 10000  # 만물창세룡 — 패에서 자체 특수 소환 절차


@pytest.fixture(scope="module")
def analyzer(repository):
    return EffectAnalyzer(repository)


def effect_with_category(analysis, category):
    for effect in analysis.effects:
        if category in effect.categories:
            return effect
    raise AssertionError(f"{category} 효과를 찾지 못했다")


# ===================================================================
# 증원 — 조건 없는 발동, 비용 없음, 대상 지정 없음, 덱에서 서치
# ===================================================================


def test_search_effect_activation(analyzer, repository):
    analysis = analyzer.analyze(repository.get(REINFORCEMENT))
    assert len(analysis.effects) == 1
    effect = analysis.effects[0]
    assert "ACTIVATE" in effect.effect_types
    assert effect.trigger_event == "EVENT_FREE_CHAIN"
    assert set(effect.categories) == {"TOHAND", "SEARCH"}


def test_search_effect_has_no_cost(analyzer, repository):
    effect = analyzer.analyze(repository.get(REINFORCEMENT)).effects[0]
    assert effect.costs == []


def test_search_effect_does_not_target(analyzer, repository):
    """증원은 카드를 대상으로 지정하지 않는다 (EFFECT_FLAG_CARD_TARGET 없음)."""
    effect = analyzer.analyze(repository.get(REINFORCEMENT)).effects[0]
    assert effect.targets_card is False


def test_search_effect_constraint_is_extracted(analyzer, repository):
    """s.filter 의 IsLevelBelow(4) / IsRace(RACE_WARRIOR) 를 읽어야 한다."""
    effect = analyzer.analyze(repository.get(REINFORCEMENT)).effects[0]
    selection = effect.selection
    assert selection is not None
    assert "DECK" in selection.locations
    assert selection.constraint.races == [C.RACE_WARRIOR]
    assert selection.constraint.level_max == 4


def test_search_effect_action(analyzer, repository):
    effect = analyzer.analyze(repository.get(REINFORCEMENT)).effects[0]
    kinds = [a.kind for a in effect.actions]
    assert ActionKind.TO_HAND in kinds
    action = next(a for a in effect.actions if a.kind is ActionKind.TO_HAND)
    # 덱에서 패로 — 콤보 탐색이 쓰는 상태 전이
    assert action.to_location == "HAND"
    assert "DECK" in action.from_locations


# ===================================================================
# 오르페골 스켈레촌 — 자신을 제외하는 비용, 대상 지정, 묘지에서 특수 소환
# ===================================================================


def test_cymbal_skeleton_activates_from_graveyard(analyzer, repository):
    analysis = analyzer.analyze(repository.get(CYMBAL_SKELETON))
    effect = analysis.effects[0]
    assert effect.activation_locations == ["GRAVE"]
    assert "IGNITION" in effect.effect_types


def test_cymbal_skeleton_cost_is_self_banish(analyzer, repository):
    effect = analyzer.analyze(repository.get(CYMBAL_SKELETON)).effects[0]
    assert [c.kind for c in effect.costs] == [CostKind.SELF_BANISH]
    assert effect.costs[0].raw == "Cost.SelfBanish"


def test_cymbal_skeleton_targets_a_card(analyzer, repository):
    effect = analyzer.analyze(repository.get(CYMBAL_SKELETON)).effects[0]
    assert effect.targets_card is True
    assert "GRAVE" in effect.selection.locations


def test_cymbal_skeleton_target_must_be_orcust(analyzer, repository):
    effect = analyzer.analyze(repository.get(CYMBAL_SKELETON)).effects[0]
    assert "ORCUST" in effect.selection.constraint.setcodes


def test_cymbal_skeleton_special_summons(analyzer, repository):
    effect = analyzer.analyze(repository.get(CYMBAL_SKELETON)).effects[0]
    action = next(
        a for a in effect.actions if a.kind is ActionKind.SPECIAL_SUMMON
    )
    assert action.to_location == "MZONE"
    assert "GRAVE" in action.from_locations


def test_cymbal_skeleton_is_once_per_turn(analyzer, repository):
    effect = analyzer.analyze(repository.get(CYMBAL_SKELETON)).effects[0]
    assert effect.once_per_turn is True


def test_cloned_effect_inherits_cost_and_target(analyzer, repository):
    """e2=e1:Clone() 은 비용과 대상을 물려받고 발동 방식만 바꾼다."""
    analysis = analyzer.analyze(repository.get(CYMBAL_SKELETON))
    assert len(analysis.effects) == 2
    cloned = analysis.effects[1]
    assert [c.kind for c in cloned.costs] == [CostKind.SELF_BANISH]
    assert "QUICK_O" in cloned.effect_types


# ===================================================================
# 라뷰린스 쿠클락 — 패에서 버리는 비용, 묘지 트리거
# ===================================================================


def test_cooclock_hand_effect_cost_is_self_discard(analyzer, repository):
    analysis = analyzer.analyze(repository.get(COOCLOCK))
    hand = next(e for e in analysis.effects if e.activation_locations == ["HAND"])
    assert [c.kind for c in hand.costs] == [CostKind.SELF_DISCARD]


def test_cooclock_graveyard_effect_is_a_trigger(analyzer, repository):
    analysis = analyzer.analyze(repository.get(COOCLOCK))
    grave = next(e for e in analysis.effects if e.activation_locations == ["GRAVE"])
    assert grave.trigger_event == "EVENT_TO_GRAVE"
    assert set(grave.categories) == {"TOHAND", "SPECIAL_SUMMON"}
    assert grave.has_condition is True


# ===================================================================
# 만물창세룡 — 소환 절차는 효과가 아니라 절차로 구분된다
# ===================================================================


def test_summon_procedure_is_marked_as_such(analyzer, repository):
    analysis = analyzer.analyze(repository.get(TEN_THOUSAND_DRAGON))
    procs = [e for e in analysis.effects if e.is_summon_procedure]
    assert len(procs) == 1
    assert "HAND" in procs[0].activation_locations


# ===================================================================
# 구조화하지 못한 부분은 보존한다
# ===================================================================


def test_raw_effect_spec_is_preserved(analyzer, repository):
    analysis = analyzer.analyze(repository.get(CYMBAL_SKELETON))
    for effect in analysis.effects:
        assert effect.raw is not None
        assert effect.raw.index.startswith("e")


def test_unstructured_calls_are_kept_not_guessed(analyzer, repository):
    """분석기가 모르는 Duel 호출은 UNKNOWN 으로 버리지 않고 기록해 둔다."""
    analysis = analyzer.analyze(repository.get(COOCLOCK))
    assert isinstance(analysis.unparsed_calls, list)
    for entry in analysis.unparsed_calls:
        assert isinstance(entry, str)


def test_analysis_reports_its_own_coverage(analyzer, repository):
    analysis = analyzer.analyze(repository.get(CYMBAL_SKELETON))
    coverage = analysis.coverage()
    assert coverage["effects"] == 2
    assert coverage["with_actions"] >= 1
    assert 0.0 <= coverage["action_ratio"] <= 1.0


def test_card_without_script_analyses_cleanly(analyzer, repository):
    """일반 몬스터는 스크립트가 없다. 예외 없이 빈 분석이 나와야 한다."""
    analysis = analyzer.analyze(repository.get(89631139))  # 푸른 눈의 백룡
    assert analysis.effects == []
    assert analysis.has_script is False


# ===================================================================
# 액션이 효과의 선택 조건을 잘못 물려받지 않는다
# ===================================================================


@requires_official_db
def test_draw_does_not_inherit_the_selection(analyzer, repository):
    """
    라뷰린스 서번츠 아리안나는 "1장 드로우" 뒤에 패의 악마족을 특수 소환한다.
    드로우는 덱에서 무조건 뽑는 것이므로, 뒤따르는 선택의 위치(패)나
    카드 조건(악마족)을 물려받으면 카드 텍스트와 어긋난다.
    """
    cards = repository.find_by_exact_name("라뷰린스 서번츠 아리안나")
    if not cards:
        pytest.skip("한국어 데이터 없음")
    analysis = analyzer.analyze(cards[0])
    draws = [
        action
        for effect in analysis.effects
        for action in effect.actions
        if action.kind is ActionKind.DRAW
    ]
    assert draws
    for action in draws:
        assert action.from_locations == ["DECK"]
        assert action.constraint is None


@requires_official_db
def test_life_point_actions_carry_no_card_condition(analyzer, repository):
    """데미지와 회복은 카드를 고르지 않는다. 카드 조건이 붙으면 안 된다."""
    checked = 0
    for card in list(repository.all_cards())[:1500]:
        if card.script is None:
            continue
        for effect in analyzer.analyze(card).effects:
            for action in effect.actions:
                if action.kind in (ActionKind.DAMAGE, ActionKind.RECOVER):
                    assert action.constraint is None, card.display_name()
                    checked += 1
    assert checked > 0


@requires_official_db
def test_card_moving_actions_still_inherit_the_selection(analyzer, repository):
    """
    반대로, 고른 카드를 옮기는 액션은 선택 조건을 그대로 이어받아야 한다.
    수정이 과하게 적용되면 이쪽이 깨진다.
    """
    analysis = analyzer.analyze(repository.get(CYMBAL_SKELETON))
    action = next(
        a
        for effect in analysis.effects
        for a in effect.actions
        if a.kind is ActionKind.SPECIAL_SUMMON
    )
    assert "GRAVE" in action.from_locations
    assert action.constraint is not None
    assert "ORCUST" in action.constraint.setcodes
