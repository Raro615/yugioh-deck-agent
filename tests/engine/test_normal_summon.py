"""
Phase 2-I — 일반 소환.

    PlayerAction(NORMAL_SUMMON) → ActionValidator → ActionExecutor
        → NormalSummonHandler → GameState 변경 → MonsterSummoned

**이 프로젝트에서 처음으로 판을 바꾸는 플레이어 행위다.** 그래서 보는 것이
다섯이다.

1. **허가가 실제로 나는가.** Phase 2-H 까지 어떤 Action 도 ``VALID`` 가
   아니었다. 제물이 필요 없는 일반 소환만 그 한 걸음이 채워졌다.
2. **허가가 나지 않는 것들이 정확히 갈리는가** — "안 된다"(페이즈 · 자리 ·
   소환권)와 "모른다"(제물 · 소환 조건).
3. **실패가 판을 건드리지 않는가.** 특히 소환권만 사라지는 판이 없어야 한다.
4. **카드 정의가 움직이지 않는가.** 움직이는 것은 ``CardInstance`` 다.
5. **소환 계층이 다른 계층의 일을 하지 않는가** — 효과 · 체인 · 트리거 ·
   우선권.

실제 카드로 본다. 가짜 카드는 "레벨 3 통상 몬스터" 라는 사실 자체를 지어내는
것이라, 소환 절차 판정을 시험할 수 없다.
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionExecutor, ActionHandler, ActionStatus
from engine.action_validation import ActionValidator
from engine.effect.delta import MonsterSummoned, StateDelta, SummonKind
from engine.game_state_view import CardDefinitionView, GameStateView
from engine.ids import InstanceId
from engine.normal_summon import (
    NormalSummonError,
    NormalSummonExecutor,
    NormalSummonHandler,
    summoning_executor,
)
from engine.state.game_state import GameState
from engine.state.rule_usage import RuleActionKind, RuleUsageRegistry
from engine.summon_rules import (
    SummonEligibility,
    assess_normal_summon,
    tributes_for_level,
)
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1

#: 실제 카드. 값이 바뀌면 테스트가 알려주는 편이 낫다.
FEATHERMAN = 21844576  # 엘리멘틀 히어로 페더맨 — 레벨 3 통상 몬스터
BLUE_EYES = 89631139  # 푸른 눈의 백룡 — 레벨 8 통상 (제물 2장)
DARK_MAGICIAN = 46986414  # 블랙 매지션 — 레벨 7 통상 (제물 2장)
DARK_HOLE = 53129443  # 블랙홀 — 마법 카드
CHAOS_SOLDIER = 5405694  # 카오스 솔저 — 의식 몬스터
ULTIMATE_DRAGON = 23995346  # 궁극의 푸른 눈의 백룡 — 융합 (엑스트라 덱)
KURIBOH = 40640057  # 크리보 — 레벨 1 **효과** 몬스터


# ======================================================================
# 판 · 도구
# ======================================================================


def new_state(repository) -> GameState:
    """
    p0 의 패: 페더맨 · 푸른 눈 · 블랙홀 · 카오스 솔저 · 크리보 · 궁극의 용.

    궁극의 용은 실제 듀얼에서 패에 있을 수 없지만, **그래서 넣는다** —
    엑스트라 덱 몬스터를 손에 쥐여 줘도 검증기가 거절하는지 본다.
    """
    game = GameState.create(
        repository,
        decks=(
            # 앞의 여섯 장이 패로 오고, 뒤는 덱에 남아 채우기용으로 쓴다.
            [FEATHERMAN, BLUE_EYES, DARK_HOLE, CHAOS_SOLDIER, KURIBOH,
             ULTIMATE_DRAGON, DARK_MAGICIAN] + [DARK_HOLE] * 6,
            [FEATHERMAN, BLUE_EYES] * 4,
        ),
    )
    game.draw(MINE, 6)
    game.draw(THEIRS, 2)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


@pytest.fixture
def executor() -> ActionExecutor:
    return summoning_executor()


def in_hand(state: GameState, card_id: int, player: int = MINE) -> InstanceId:
    return next(
        card.instance_id
        for card in state.player(player).hand
        if card.card_id == card_id
    )


def summon(state: GameState, card_id: int, player: int = MINE) -> PlayerAction:
    return PlayerAction.normal_summon(player, in_hand(state, card_id, player))


def verdict(state: GameState, action: PlayerAction) -> ValidationResult:
    view = GameStateView.from_state(state, viewer=action.actor)
    return ActionValidator(view).validate(action)


def _fill_monster_zone(state: GameState, player: int = MINE) -> None:
    """
    다섯 칸을 덱의 카드로 채운다. 무엇을 채웠는지는 중요하지 않다 — 패는
    건드리지 않는다 (소환하려던 카드가 사라지면 다른 것을 시험하게 된다).
    """
    for index in range(5):
        state.move(state.player(player).deck[0], Zone.MZONE, to_player=player,
                   index=index, position=Position.FACEUP_ATTACK)


def summoned_count(state: GameState, player: int = MINE) -> int:
    return state.rule_uses.count(
        state.turn.turn_number, player, RuleActionKind.NORMAL_SUMMON
    )


# ======================================================================
# 1. 성공 경로
# ======================================================================


@requires_official_db
def test_a_level_three_normal_monster_is_finally_allowed(state):
    """
    **Phase 2-I 의 핵심.** 여기까지 어떤 Action 도 허가를 받지 못했다.
    """
    result = verdict(state, summon(state, FEATHERMAN))

    assert result.validity is ActionValidity.VALID
    assert result.permits_execution is True
    assert result.code is ValidationCode.OK


@requires_official_db
def test_the_summon_moves_the_card_from_hand_to_the_monster_zone(state, executor):
    card = in_hand(state, FEATHERMAN)
    hand_before = len(state.player(MINE).hand)

    execution = executor.execute(state, PlayerAction.normal_summon(MINE, card))

    assert execution.status is ActionStatus.EXECUTED
    assert len(state.player(MINE).hand) == hand_before - 1
    assert state.locate(card).zone is Zone.MZONE
    assert card not in [c.instance_id for c in state.player(MINE).hand]


@requires_official_db
def test_the_monster_arrives_face_up_in_attack_position(state, executor):
    card = in_hand(state, FEATHERMAN)
    executor.execute(state, PlayerAction.normal_summon(MINE, card))

    summoned = state.find_instance(card)
    assert summoned.position is Position.FACEUP_ATTACK
    assert summoned.is_faceup is True


@requires_official_db
def test_the_owner_and_the_controller_do_not_change(state, executor):
    card = state.find_instance(in_hand(state, FEATHERMAN))
    before = (card.owner, card.controller)

    executor.execute(state, PlayerAction.normal_summon(MINE, card.instance_id))

    assert (card.owner, card.controller) == before == (MINE, MINE)


@requires_official_db
def test_a_summon_in_main_phase_two_works_the_same(state, executor):
    state.turn.set_phase(Phase.MAIN2)
    execution = executor.execute(state, summon(state, FEATHERMAN))

    assert execution.status is ActionStatus.EXECUTED
    assert len(state.player(MINE).monster_zone) == 1


@requires_official_db
def test_the_summon_takes_the_first_free_slot(state, executor):
    executor.execute(state, summon(state, FEATHERMAN))
    zone = state.zone(MINE, Zone.MZONE)

    assert zone.slot(0) is not None
    assert zone.free_slots() == [1, 2, 3, 4]


# ======================================================================
# 2. 소환권
# ======================================================================


@requires_official_db
def test_a_successful_summon_spends_the_right(state, executor):
    assert summoned_count(state) == 0
    executor.execute(state, summon(state, FEATHERMAN))
    assert summoned_count(state) == 1


@requires_official_db
def test_a_second_summon_in_the_same_turn_is_refused(state, executor):
    executor.execute(state, summon(state, FEATHERMAN))
    state.draw(MINE, 1)  # 패를 채워도 소환권은 돌아오지 않는다

    second = summon(state, DARK_MAGICIAN)
    result = verdict(state, second)

    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.NORMAL_SUMMON_ALREADY_USED

    before = state.state_hash()
    execution = executor.execute(state, second)
    assert execution.status is ActionStatus.INVALID_ACTION
    assert state.state_hash() == before


@requires_official_db
def test_the_right_comes_back_on_the_next_turn(state, executor):
    executor.execute(state, summon(state, FEATHERMAN))
    state.draw(MINE, 1)
    state.turn.begin_next_turn()
    state.turn.begin_next_turn()  # 다시 내 턴
    state.turn.set_phase(Phase.MAIN1)

    assert state.turn.turn_player == MINE
    assert summoned_count(state) == 0
    assert verdict(state, summon(state, DARK_MAGICIAN)).code is not (
        ValidationCode.NORMAL_SUMMON_ALREADY_USED
    )


@requires_official_db
def test_the_right_is_counted_per_player(state, executor):
    executor.execute(state, summon(state, FEATHERMAN))

    assert summoned_count(state, MINE) == 1
    assert summoned_count(state, THEIRS) == 0


@requires_official_db
def test_a_refused_summon_does_not_spend_the_right(state, executor):
    """
    **가장 중요한 실패 불변식.** 권리만 사라지고 몬스터는 나오지 않는 판이
    생기면 되돌릴 방법이 없다.
    """
    for action in (
        summon(state, BLUE_EYES),  # 제물이 필요하다 (UNKNOWN)
        summon(state, DARK_HOLE),  # 마법 카드 (INVALID)
        summon(state, CHAOS_SOLDIER),  # 의식 몬스터 (INVALID)
        summon(state, KURIBOH),  # 효과 몬스터 (UNKNOWN)
        PlayerAction.normal_summon(MINE, InstanceId(9999)),  # 없는 카드
    ):
        executor.execute(state, action)

    assert summoned_count(state) == 0
    assert len(state.player(MINE).monster_zone) == 0


@requires_official_db
def test_the_rule_usage_is_not_the_effect_usage(state, executor):
    """
    소환권은 **규칙이 준 권리**이고 카드 효과의 "1턴에 1번" 과 다른 것이다.
    한 표에 넣으면 리셋 시점도 판정도 뒤섞인다.
    """
    executor.execute(state, summon(state, FEATHERMAN))

    assert summoned_count(state) == 1
    assert len(state.uses) == 0  # 효과 쪽 표는 비어 있다


def test_the_rule_usage_is_scoped_by_turn_so_nothing_needs_clearing():
    registry = RuleUsageRegistry()
    registry.record(1, MINE, RuleActionKind.NORMAL_SUMMON)

    assert registry.used(1, MINE, RuleActionKind.NORMAL_SUMMON) is True
    assert registry.used(2, MINE, RuleActionKind.NORMAL_SUMMON) is False
    assert registry.used(1, THEIRS, RuleActionKind.NORMAL_SUMMON) is False


def test_the_rule_usage_survives_cloning_independently():
    state = GameState.create()
    state.rule_uses.record(1, MINE, RuleActionKind.NORMAL_SUMMON)
    copy = state.clone()
    copy.rule_uses.record(1, THEIRS, RuleActionKind.NORMAL_SUMMON)

    assert state.rule_uses.used(1, THEIRS, RuleActionKind.NORMAL_SUMMON) is False
    assert copy.rule_uses.used(1, MINE, RuleActionKind.NORMAL_SUMMON) is True


def test_the_rule_usage_is_part_of_the_board(state=None):
    """소환권을 썼는지는 판의 모양이다 — 해시가 달라져야 한다."""
    board = GameState.create()
    before = board.state_hash()
    board.rule_uses.record(1, MINE, RuleActionKind.NORMAL_SUMMON)

    assert board.state_hash() != before


@requires_official_db
def test_both_players_can_see_who_has_summoned(state, executor):
    """소환은 공개된 자리에서 일어난다 — 상대도 본다."""
    executor.execute(state, summon(state, FEATHERMAN))
    theirs = GameStateView.from_state(state, viewer=THEIRS)

    assert theirs.normal_summons_used == (1, 0)


# ======================================================================
# 3. 페이즈
# ======================================================================


@requires_official_db
@pytest.mark.parametrize(
    "phase", [Phase.DRAW, Phase.STANDBY, Phase.BATTLE, Phase.END]
)
def test_a_summon_outside_the_main_phases_is_refused(state, executor, phase):
    state.turn.set_phase(phase)
    action = summon(state, FEATHERMAN)
    before = state.state_hash()

    result = verdict(state, action)
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.WRONG_PHASE

    assert executor.execute(state, action).status is ActionStatus.INVALID_ACTION
    assert state.state_hash() == before


@requires_official_db
def test_only_the_turn_player_may_summon(state, executor):
    """상대 턴에는 소환할 수 없다. 자기 카드라도 마찬가지다."""
    state.turn.begin_next_turn()
    state.turn.set_phase(Phase.MAIN1)
    action = summon(state, FEATHERMAN)

    result = verdict(state, action)
    assert result.code is ValidationCode.NOT_TURN_PLAYER
    assert executor.execute(state, action).status is ActionStatus.INVALID_ACTION


# ======================================================================
# 4. 카드가 갖춰야 하는 것
# ======================================================================


@requires_official_db
def test_someone_elses_hand_card_cannot_be_summoned(state, executor):
    """
    상대의 패는 **보이지 않는다.** 그래서 "없다" 가 아니라 "모른다" 다 —
    검증을 반복하는 것만으로 상대 패를 탐지할 수 있으면 안 된다.
    """
    action = PlayerAction.normal_summon(MINE, in_hand(state, FEATHERMAN, THEIRS))
    result = verdict(state, action)

    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.HIDDEN_CARD
    assert result.permits_execution is False

    before = state.state_hash()
    assert executor.execute(state, action).status is ActionStatus.UNKNOWN_ACTION
    assert state.state_hash() == before


@requires_official_db
def test_a_visible_card_of_the_opponent_is_refused_outright(state, executor):
    """보이는 카드라면 "내 카드가 아니다" 가 확실하다."""
    theirs = state.player(THEIRS).hand[0]
    state.move(theirs, Zone.MZONE, to_player=THEIRS,
               position=Position.FACEUP_ATTACK)
    result = verdict(state, PlayerAction.normal_summon(MINE, theirs.instance_id))

    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.SOURCE_NOT_CONTROLLED


@requires_official_db
def test_a_card_that_is_not_in_hand_cannot_be_summoned(state, executor):
    card = in_hand(state, FEATHERMAN)
    state.move(card, Zone.GRAVE, to_player=MINE)
    action = PlayerAction.normal_summon(MINE, card)

    result = verdict(state, action)
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.SOURCE_WRONG_ZONE
    assert executor.execute(state, action).status is ActionStatus.INVALID_ACTION


@requires_official_db
def test_a_spell_card_cannot_be_summoned(state, executor):
    result = verdict(state, summon(state, DARK_HOLE))

    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.SOURCE_WRONG_CARD_TYPE


@requires_official_db
def test_a_ritual_monster_cannot_be_normal_summoned(state):
    result = verdict(state, summon(state, CHAOS_SOLDIER))

    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.CANNOT_NORMAL_SUMMON


@requires_official_db
def test_an_extra_deck_monster_cannot_be_normal_summoned(state):
    result = verdict(state, summon(state, ULTIMATE_DRAGON))

    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.CANNOT_NORMAL_SUMMON


@requires_official_db
def test_a_monster_that_needs_tributes_is_unknown_not_refused(state):
    """
    제물을 바치면 소환할 수 있다. 없는 것은 **그 절차**뿐이므로
    ``INVALID`` 가 아니다.
    """
    result = verdict(state, summon(state, BLUE_EYES))

    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "tribute" in result.missing_rule
    assert result.permits_execution is False


@requires_official_db
def test_an_effect_monster_is_unknown_because_its_text_is_unread(state):
    """
    룰북은 "most Effect Monsters (**unless they have a specific
    restriction**)" 라고 말한다. 그 제약은 카드 텍스트에 있고, 이 엔진은
    아직 읽지 못한다. 확인하지 못한 것을 허가로 바꾸지 않는다.
    """
    result = verdict(state, summon(state, KURIBOH))

    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "summoning-condition" in result.missing_rule


@requires_official_db
def test_a_full_monster_zone_refuses_the_summon(state, executor):
    _fill_monster_zone(state)
    action = summon(state, FEATHERMAN)

    result = verdict(state, action)
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.ZONE_FULL

    before = state.state_hash()
    assert executor.execute(state, action).status is ActionStatus.INVALID_ACTION
    assert state.state_hash() == before


@requires_official_db
def test_an_instance_that_does_not_exist_is_unknown_not_refused(state, executor):
    """없는 것인지 보이지 않는 것인지 구분할 수 없다."""
    action = PlayerAction.normal_summon(MINE, InstanceId(9999))
    result = verdict(state, action)

    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.HIDDEN_CARD
    assert executor.execute(state, action).status is ActionStatus.UNKNOWN_ACTION


# ======================================================================
# 5. 절차 판정 자체
# ======================================================================


@requires_official_db
def test_the_assessment_separates_four_answers(repository):
    def assess(card_id):
        return assess_normal_summon(
            CardDefinitionView.of(repository.get(card_id))
        ).eligibility

    assert assess(FEATHERMAN) is SummonEligibility.ORDINARY
    assert assess(BLUE_EYES) is SummonEligibility.NEEDS_TRIBUTE
    assert assess(CHAOS_SOLDIER) is SummonEligibility.FORBIDDEN
    assert assess(ULTIMATE_DRAGON) is SummonEligibility.FORBIDDEN
    assert assess(DARK_HOLE) is SummonEligibility.FORBIDDEN
    assert assess(KURIBOH) is SummonEligibility.UNDETERMINED


def test_an_unreadable_definition_is_undetermined_not_refused():
    assessment = assess_normal_summon(None)

    assert assessment.eligibility is SummonEligibility.UNDETERMINED
    assert assessment.permits_procedure is False
    assert assessment.is_refusal is False


def test_the_assessment_cannot_be_read_as_true_or_false():
    with pytest.raises(TypeError):
        bool(assess_normal_summon(None))


def test_the_rulebook_tribute_counts_are_recorded(repository=None):
    """RULE-SUMMON-011 — 레벨 5·6 은 1장, 레벨 7 이상은 2장."""
    assert tributes_for_level(4) == 0
    assert tributes_for_level(5) == 1
    assert tributes_for_level(6) == 1
    assert tributes_for_level(7) == 2
    assert tributes_for_level(12) == 2


@requires_official_db
def test_the_tribute_count_travels_with_the_assessment(repository):
    assessment = assess_normal_summon(
        CardDefinitionView.of(repository.get(BLUE_EYES))
    )

    assert assessment.tributes_required == 2
    assert assessment.permits_procedure is False


def test_a_tribute_count_cannot_be_attached_to_another_answer():
    from engine.summon_rules import SummonAssessment

    with pytest.raises(ValueError):
        SummonAssessment(SummonEligibility.ORDINARY, "", tributes_required=1)
    with pytest.raises(ValueError):
        SummonAssessment(SummonEligibility.NEEDS_TRIBUTE, "")


# ======================================================================
# 6. 변화 기록
# ======================================================================


@requires_official_db
def test_the_summon_records_exactly_one_change(state, executor):
    card = in_hand(state, FEATHERMAN)
    execution = executor.execute(state, PlayerAction.normal_summon(MINE, card))

    assert len(execution.deltas) == 1
    delta = execution.deltas[0]
    assert isinstance(delta, MonsterSummoned)
    assert isinstance(delta, StateDelta)
    assert delta.summon is SummonKind.NORMAL
    assert delta.card == card
    assert (delta.from_zone, delta.to_zone) == (Zone.HAND, Zone.MZONE)
    assert delta.position is Position.FACEUP_ATTACK
    assert (delta.player, delta.owner) == (MINE, MINE)


@requires_official_db
def test_the_record_is_serialisable_and_deterministic(state, executor):
    delta = executor.execute(state, summon(state, FEATHERMAN)).deltas[0]

    assert delta.kind == "monster_summoned"
    assert delta.to_dict()["to"]["position"] == "FACEUP_ATTACK"
    assert delta.canonical_state() == delta.canonical_state()
    assert delta.describe_ko()


def test_a_summon_record_cannot_claim_the_card_stayed_put():
    with pytest.raises(ValueError):
        MonsterSummoned(
            SummonKind.NORMAL, InstanceId(1), MINE, MINE,
            Zone.MZONE, Zone.MZONE, 0, Position.FACEUP_ATTACK,
        )


def test_the_summon_record_is_not_an_effect_operation():
    """
    소환은 효과가 아니다 (ADR-001). ``OperationKind`` 어휘를 쓰면 "효과로
    묘지에 보내졌다" 와 같은 표를 쓰게 된다.
    """
    delta = MonsterSummoned(
        SummonKind.NORMAL, InstanceId(1), MINE, MINE,
        Zone.HAND, Zone.MZONE, 0, Position.FACEUP_ATTACK,
    )

    assert not hasattr(delta, "operation")
    assert not hasattr(delta, "reason_names")


# ======================================================================
# 7. 변경 안전성
# ======================================================================


@requires_official_db
def test_validation_never_touches_the_board(state):
    before = state.state_hash()
    for card_id in (FEATHERMAN, BLUE_EYES, DARK_HOLE, CHAOS_SOLDIER, KURIBOH):
        verdict(state, summon(state, card_id))

    assert state.state_hash() == before


@requires_official_db
def test_planning_never_touches_the_board(state):
    before = state.state_hash()
    NormalSummonExecutor().plan(state, summon(state, FEATHERMAN))

    assert state.state_hash() == before


@requires_official_db
def test_the_plan_refuses_before_touching_anything(state):
    """
    수행할 수 없는 지시는 **판에 손대기 전에** 멈춘다. 계획이 만들어졌다는
    것은 끝까지 갈 수 있다는 뜻이다.
    """
    low_level = NormalSummonExecutor()
    before = state.state_hash()

    with pytest.raises(NormalSummonError):
        low_level.apply(state, PlayerAction.normal_summon(MINE, InstanceId(9999)))
    with pytest.raises(NormalSummonError):
        low_level.apply(state, PlayerAction.normal_summon(
            MINE, in_hand(state, FEATHERMAN, THEIRS)
        ))
    with pytest.raises(NormalSummonError):
        low_level.apply(state, PlayerAction.set_monster(
            MINE, in_hand(state, FEATHERMAN)
        ))

    assert state.state_hash() == before
    assert summoned_count(state) == 0


@requires_official_db
def test_a_full_zone_stops_the_plan_not_the_move(state):
    _fill_monster_zone(state)
    before = state.state_hash()

    with pytest.raises(NormalSummonError):
        NormalSummonExecutor().apply(state, summon(state, FEATHERMAN))

    assert state.state_hash() == before


@requires_official_db
def test_the_card_is_never_in_two_zones_at_once(state, executor):
    card = in_hand(state, FEATHERMAN)
    executor.execute(state, PlayerAction.normal_summon(MINE, card))

    holding = [
        zone
        for zone, container in state.player(MINE).zones.items()
        if card in [c.instance_id for c in container]
    ]
    assert holding == [Zone.MZONE]


@requires_official_db
def test_an_unregistered_executor_changes_nothing(state):
    """
    허가가 나도 구현이 등록되어 있지 않으면 실행되지 않는다 (ADR-006).
    """
    empty = ActionExecutor()
    before = state.state_hash()

    execution = empty.execute(state, summon(state, FEATHERMAN))

    assert execution.status is ActionStatus.UNSUPPORTED_ACTION
    assert execution.deltas == ()
    assert state.state_hash() == before
    assert summoned_count(state) == 0


# ======================================================================
# 8. 정의와 인스턴스
# ======================================================================


@requires_official_db
def test_the_card_definition_does_not_move(state, executor, repository):
    """
    움직이는 것은 ``CardInstance`` 다. 정의는 저장소의 것이고 듀얼이
    건드리지 않는다.
    """
    definition = repository.get(FEATHERMAN)
    before = (definition.name, definition.type_mask, definition.level,
              definition.atk, definition.defense)

    executor.execute(state, summon(state, FEATHERMAN))

    after = (definition.name, definition.type_mask, definition.level,
             definition.atk, definition.defense)
    assert after == before
    assert repository.get(FEATHERMAN) is definition


@requires_official_db
def test_two_copies_of_the_same_card_are_different_instances(state, executor):
    """
    "페더맨이라는 카드" 와 "이 페더맨 한 장" 은 다르다. 소환되는 것은
    후자다.
    """
    other = state.player(THEIRS).hand[0]
    mine = state.find_instance(in_hand(state, FEATHERMAN))
    assert other.card_id == mine.card_id
    assert other.instance_id != mine.instance_id

    executor.execute(state, PlayerAction.normal_summon(MINE, mine.instance_id))

    assert state.locate(mine.instance_id).zone is Zone.MZONE
    assert state.locate(other.instance_id).zone is Zone.HAND


# ======================================================================
# 9. 결정론과 복제
# ======================================================================


@requires_official_db
def test_the_same_board_and_action_give_the_same_board(repository):
    first, second = new_state(repository), new_state(repository)
    assert first.state_hash() == second.state_hash()

    summoning_executor().execute(first, summon(first, FEATHERMAN))
    summoning_executor().execute(second, summon(second, FEATHERMAN))

    assert first.state_hash() == second.state_hash()


@requires_official_db
def test_the_summon_changes_the_board_hash(state, executor):
    before = state.state_hash()
    executor.execute(state, summon(state, FEATHERMAN))

    assert state.state_hash() != before


@requires_official_db
def test_a_clone_is_summoned_into_alone(state, executor):
    copy = state.clone()
    before = state.state_hash()

    executor.execute(copy, summon(copy, FEATHERMAN))

    assert state.state_hash() == before
    assert len(state.player(MINE).monster_zone) == 0
    assert len(copy.player(MINE).monster_zone) == 1
    assert summoned_count(state) == 0
    assert summoned_count(copy) == 1


@requires_official_db
def test_the_same_instance_id_means_the_same_card_in_a_clone(state, executor):
    copy = state.clone()
    card = in_hand(state, FEATHERMAN)

    executor.execute(copy, PlayerAction.normal_summon(MINE, card))

    assert copy.find_instance(card) is not None
    assert copy.find_instance(card) is not state.find_instance(card)
    assert state.locate(card).zone is Zone.HAND


# ======================================================================
# 10. 계층 경계
# ======================================================================


def test_the_handler_matches_the_action_handler_protocol():
    assert isinstance(NormalSummonHandler(), ActionHandler)


def test_the_default_executor_still_knows_nothing():
    assert ActionExecutor().supported == frozenset()


def test_the_summoning_executor_knows_exactly_one_kind():
    assert summoning_executor().supported == frozenset(
        {PlayerActionKind.NORMAL_SUMMON}
    )


def test_the_action_executor_holds_no_summon_knowledge():
    """
    ``ActionExecutor`` 에 ``if NORMAL_SUMMON:`` 같은 분기가 생기면 종류마다
    파일이 자란다. 소환 지식은 전부 핸들러 쪽에 있다.
    """
    source = pathlib.Path("engine/action_execution.py").read_text("utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "engine.normal_summon" not in imported
    assert "engine.summon_rules" not in imported

    # 종류를 **비교하는** 코드가 없어야 한다. 표에 이름이 적히는 것은
    # 괜찮다 (UNSUPPORTED_REASON 이 종류마다 한 줄을 갖는다).
    branches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.If, ast.Compare))
        and "NORMAL_SUMMON" in ast.dump(node)
    ]
    assert branches == []


def test_the_summon_layer_does_not_reach_into_other_layers():
    """
    소환은 효과 해결도 체인도 트리거도 우선권도 아니다. 여기서 부르면
    두 경로가 갈린다.
    """
    tree = ast.parse(
        pathlib.Path("engine/normal_summon.py").read_text("utf-8")
    )
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    for forbidden in (
        "engine.effect.executor",
        "engine.payment",
        "engine.chain",
        "engine.trigger",
        "engine.trigger_chain",
        "engine.trigger_order",
        "engine.timing",
        "engine.priority",
        "engine.turn_progression",
    ):
        assert forbidden not in imported, f"{forbidden} 를 가져오면 안 됩니다."


def test_the_summon_layer_builds_no_triggers_and_no_chain_links():
    tree = ast.parse(
        pathlib.Path("engine/normal_summon.py").read_text("utf-8")
    )
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    for forbidden in ("TimingEvent", "TriggerCandidate", "ChainLink",
                      "PriorityState", "EffectExecutor", "CostPayer"):
        assert forbidden not in called


def test_the_procedure_judgement_lives_in_one_place():
    """
    검증기와 실행기가 같은 답을 쓰려면 판정이 한 곳에만 있어야 한다.
    실행기는 절차를 다시 판정하지 않는다.
    """
    source = pathlib.Path("engine/normal_summon.py").read_text("utf-8")

    assert "assess_normal_summon" not in source
    assert "SummonEligibility" not in source


def test_the_rules_layer_is_cited_not_loaded():
    """
    룰북은 **기준점**이지 실행 시 의존성이 아니다. 엔진이 JSON 을 읽으면
    규칙 데이터가 없는 곳에서 판정이 달라진다.
    """
    tree = ast.parse(
        pathlib.Path("engine/summon_rules.py").read_text("utf-8")
    )
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not any(module.startswith("rules") for module in imported)
    assert "json" not in imported


@requires_official_db
def test_the_summon_does_not_advance_the_phase_or_the_turn(state, executor):
    """턴 진행은 Phase 2-H 의 일이다. 소환이 시간을 옮기지 않는다."""
    before = (state.turn.turn_number, state.turn.turn_player, state.turn.phase)
    executor.execute(state, summon(state, FEATHERMAN))

    assert (state.turn.turn_number, state.turn.turn_player,
            state.turn.phase) == before
