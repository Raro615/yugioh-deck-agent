"""
Phase 2-H — Turn / Phase Progression.

    GameState → TurnProgressor.plan → TransitionPlan → advance → PhaseChanged

다섯 가지를 본다.

1. **시간이 정해진 순서로 가는가.** DRAW → STANDBY → MAIN1 → BATTLE →
   MAIN2 → END → *다음 턴의* DRAW.
2. **턴 경계에서 턴 번호와 턴 플레이어가 함께 움직이는가.**
3. **턴 플레이어와 우선권이 섞이지 않는가.** 진행 계층은
   ``PriorityState`` 를 읽지도 쓰지도 않는다.
4. **거절이 '안 된다' 와 '모른다' 로 나뉘는가.**
5. **옮기지 못한 시도가 판을 한 글자도 바꾸지 않는가.**
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionExecutor, ActionHandler, ActionStatus
from engine.action_validation import ActionValidator
from engine.effect.delta import PhaseChanged, StateDelta
from engine.game_state_view import GameStateView
from engine.priority import PriorityHolder, PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.state.turn import TurnState
from engine.turn_progression import (
    TURN_BOUNDARY_RESETS,
    UNRESOLVED_PROGRESSION_RULES,
    PhaseTransition,
    PhaseTransitionHandler,
    ProgressionResult,
    ProgressionStatus,
    TransitionKind,
    TransitionPlan,
    TurnPosition,
    TurnProgressionError,
    TurnProgressor,
)
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import TURN_PHASE_ORDER, Phase, Position, Zone

MINE, THEIRS = 0, 1


# ======================================================================
# 판 · 도구
# ======================================================================


def new_state() -> GameState:
    game = GameState.create(decks=(range(1000, 1020), range(2000, 2020)))
    game.draw(MINE, 5)
    game.draw(THEIRS, 5)
    game.move(game.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


@pytest.fixture
def progressor() -> TurnProgressor:
    return TurnProgressor()


def authorized(reason: str = "규칙 계층이 허가했다고 가정한다") -> ValidationResult:
    """
    **규칙 계층이 내줄 허가**를 공개 생성자로 만든다.

    ``ActionValidator`` 는 ``CHANGE_PHASE`` 에 아직 ``VALID`` 를 주지 않는다.
    그래서 실행 경로를 보려면 허가를 밖에서 넣어야 하는데, private 필드를
    건드리거나 monkeypatch 하는 대신 **공개 생성자**로 만든다 — 규칙 계층이
    생기면 똑같은 값이 그쪽에서 나온다.
    """
    return ValidationResult.valid(reason)


def position(state: GameState) -> tuple[int, int, Phase]:
    return (state.turn.turn_number, state.turn.turn_player, state.turn.phase)


# ======================================================================
# 1. 초기 상태
# ======================================================================


def test_a_new_duel_starts_at_the_first_phase_of_the_first_turn(state):
    """초기 자리는 정해져 있다 — 1턴 · 선공 · 첫 페이즈."""
    assert state.turn.turn_number == 1
    assert state.turn.turn_player == MINE
    assert state.turn.phase is TURN_PHASE_ORDER[0]
    assert state.turn.phase is Phase.DRAW


def test_the_starting_player_is_the_one_the_duel_was_created_with():
    """후공으로 시작하는 판도 표현된다. **초기 자리를 지어내지 않는다.**"""
    game = GameState.create(turn_player=THEIRS)
    assert TurnPosition.from_state(game) == TurnPosition(1, THEIRS, Phase.DRAW)


def test_progression_does_not_draw_or_deal_starting_hands(state, progressor):
    """
    시작 드로우 · 스탠바이 처리 · 엔드 페이즈 처리는 **하지 않는다.**
    이번 계층이 옮기는 것은 시간뿐이다.
    """
    before = [len(state.player(p).hand) for p in (MINE, THEIRS)]
    for _ in range(len(TURN_PHASE_ORDER) + 1):
        progressor.advance(state)
    assert [len(state.player(p).hand) for p in (MINE, THEIRS)] == before


# ======================================================================
# 2. 페이즈 순서
# ======================================================================


@pytest.mark.parametrize(
    ("here", "there"),
    [
        (Phase.DRAW, Phase.STANDBY),
        (Phase.STANDBY, Phase.MAIN1),
        (Phase.MAIN1, Phase.BATTLE),
        (Phase.BATTLE, Phase.MAIN2),
        (Phase.MAIN2, Phase.END),
    ],
)
def test_each_phase_leads_to_the_next_one(state, progressor, here, there):
    state.turn.set_phase(here)
    result = progressor.advance(state)

    assert result.advanced is True
    assert state.turn.phase is there
    assert state.turn.turn_number == 1
    assert state.turn.turn_player == MINE
    assert result.transition.kind is TransitionKind.PHASE_ADVANCE
    assert result.transition.changes_turn is False


def test_the_whole_turn_is_walked_in_order(state, progressor):
    """한 턴을 끝까지 걸어도 순서가 흐트러지지 않는다."""
    walked = [state.turn.phase]
    for _ in range(len(TURN_PHASE_ORDER) - 1):
        progressor.advance(state)
        walked.append(state.turn.phase)

    assert tuple(walked) == TURN_PHASE_ORDER


def test_a_phase_outside_the_turn_order_is_unknown_not_invalid(state, progressor):
    """
    배틀 스텝 · 데미지 스텝은 순서 위에 없다. **모르는 것이지 틀린 것이
    아니다** — 그 안의 진행은 아직 구현하지 않았다.
    """
    state.turn.set_phase(Phase.DAMAGE)
    before = state.state_hash()
    result = progressor.advance(state)

    assert result.status is ProgressionStatus.UNKNOWN_TRANSITION
    assert result.verdict.validity is ActionValidity.UNKNOWN
    assert result.verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert result.verdict.missing_rule is not None
    assert result.transition is None
    assert result.deltas == ()
    assert state.state_hash() == before


# ======================================================================
# 3. 턴 경계
# ======================================================================


def test_the_end_phase_leads_to_the_next_turns_first_phase(state, progressor):
    state.turn.set_phase(Phase.END)
    result = progressor.advance(state)

    assert result.advanced is True
    assert result.transition.kind is TransitionKind.TURN_CHANGE
    assert result.transition.changes_turn is True
    assert position(state) == (2, THEIRS, Phase.DRAW)


def test_the_turn_number_grows_by_one_each_turn(state, progressor):
    """두 턴을 돌면 턴 번호는 3, 턴 플레이어는 다시 선공이다."""
    seen = []
    for _ in range(len(TURN_PHASE_ORDER) * 2):
        progressor.advance(state)
        seen.append((state.turn.turn_number, state.turn.turn_player))

    assert seen[-1] == (3, MINE)
    assert [turn for turn, _ in seen] == sorted(turn for turn, _ in seen)


def test_a_turn_change_flips_the_turn_player(state, progressor):
    state.turn.set_phase(Phase.END)
    progressor.advance(state)
    assert state.turn.turn_player == THEIRS

    state.turn.set_phase(Phase.END)
    progressor.advance(state)
    assert state.turn.turn_player == MINE


def test_a_turn_change_cannot_be_built_with_a_mismatched_shape():
    """
    "턴은 늘었는데 플레이어는 그대로" 같은 전이는 **값으로도 만들 수 없다.**
    """
    with pytest.raises(ValueError):
        PhaseTransition(
            TransitionKind.TURN_CHANGE,
            TurnPosition(1, MINE, Phase.END),
            TurnPosition(2, MINE, Phase.DRAW),
        )
    with pytest.raises(ValueError):
        PhaseTransition(
            TransitionKind.TURN_CHANGE,
            TurnPosition(1, MINE, Phase.END),
            TurnPosition(2, THEIRS, Phase.MAIN1),
        )
    with pytest.raises(ValueError):
        PhaseTransition(
            TransitionKind.PHASE_ADVANCE,
            TurnPosition(1, MINE, Phase.MAIN1),
            TurnPosition(2, MINE, Phase.BATTLE),
        )


def test_turn_boundary_resets_are_recorded_and_not_performed(state, progressor):
    """
    **턴이 바뀌어도 아무것도 지우지 않는다.**

    무엇이 언제 지워지는가는 규칙이고, 규칙 없이 지우면 되돌릴 수 없다.
    그래서 :data:`TURN_BOUNDARY_RESETS` 에 목록만 남긴다 — ``UseRegistry``
    가 리셋 시점을 정하지 않은 Phase 1 의 정책을 그대로 지킨다.
    """
    state.uses.mark_card_name_used(MINE, 1000)
    state.turn.set_phase(Phase.END)
    progressor.advance(state)

    assert state.uses.card_name_used(MINE, 1000) is True
    assert any("UseRegistry" in rule for rule in TURN_BOUNDARY_RESETS)


# ======================================================================
# 4. 요청한 페이즈
# ======================================================================


def test_asking_for_the_next_phase_by_name_is_allowed(state, progressor):
    state.turn.set_phase(Phase.MAIN1)
    result = progressor.advance(state, Phase.BATTLE)

    assert result.advanced is True
    assert state.turn.phase is Phase.BATTLE


def test_asking_for_the_phase_we_are_already_in_is_refused(state, progressor):
    state.turn.set_phase(Phase.MAIN1)
    before = state.state_hash()
    result = progressor.advance(state, Phase.MAIN1)

    assert result.status is ProgressionStatus.INVALID_TRANSITION
    assert result.verdict.code is ValidationCode.PHASE_UNCHANGED
    assert state.state_hash() == before


def test_going_backwards_is_refused(state, progressor):
    """시간은 되감기지 않는다. 이것은 **확실히 안 되는 것**이다."""
    state.turn.set_phase(Phase.MAIN2)
    before = state.state_hash()
    result = progressor.advance(state, Phase.DRAW)

    assert result.status is ProgressionStatus.INVALID_TRANSITION
    assert result.verdict.validity is ActionValidity.INVALID
    assert result.verdict.code is ValidationCode.WRONG_PHASE
    assert state.state_hash() == before


def test_skipping_a_phase_forward_is_unknown_not_invalid(state, progressor):
    """
    실제 규칙에서는 메인 페이즈 1 에서 엔드 페이즈로 바로 갈 수 있다.
    **그래서 '안 된다' 고 말하지 않는다** — 건너뛴 배틀 페이즈가 없었다는
    사실이 무엇을 바꾸는지 아직 모를 뿐이다.
    """
    state.turn.set_phase(Phase.MAIN1)
    before = state.state_hash()
    result = progressor.advance(state, Phase.END)

    assert result.status is ProgressionStatus.UNKNOWN_TRANSITION
    assert result.verdict.validity is ActionValidity.UNKNOWN
    assert result.verdict.missing_rule is not None
    assert state.state_hash() == before


def test_a_phase_that_is_not_on_the_turn_order_cannot_be_asked_for(state, progressor):
    state.turn.set_phase(Phase.MAIN1)
    result = progressor.advance(state, Phase.DAMAGE)

    assert result.status is ProgressionStatus.INVALID_TRANSITION
    assert result.verdict.code is ValidationCode.WRONG_PHASE
    assert state.turn.phase is Phase.MAIN1


# ======================================================================
# 5. 끝난 듀얼
# ======================================================================


def test_time_does_not_move_in_a_finished_duel(state, progressor):
    state.set_result(MINE, "테스트")
    before = state.state_hash()
    result = progressor.advance(state)

    assert result.status is ProgressionStatus.INVALID_TRANSITION
    assert result.verdict.code is ValidationCode.DUEL_ALREADY_OVER
    assert result.deltas == ()
    assert state.state_hash() == before


# ======================================================================
# 6. 결과 모델이 거짓말하지 못하게
# ======================================================================


def test_a_refused_plan_never_carries_a_transition():
    refusal = ValidationResult.invalid(ValidationCode.WRONG_PHASE, "안 됩니다.")
    with pytest.raises(ValueError):
        TransitionPlan(
            refusal,
            PhaseTransition(
                TransitionKind.PHASE_ADVANCE,
                TurnPosition(1, MINE, Phase.DRAW),
                TurnPosition(1, MINE, Phase.STANDBY),
            ),
        )


def test_an_allowed_plan_must_carry_a_transition():
    with pytest.raises(ValueError):
        TransitionPlan(ValidationResult.valid("됩니다."))


def test_a_result_that_did_not_advance_cannot_carry_deltas():
    plan = TransitionPlan(
        ValidationResult.unknown(ValidationCode.RULE_NOT_IMPLEMENTED, "모릅니다.")
    )
    with pytest.raises(ValueError):
        ProgressionResult(
            ProgressionStatus.UNKNOWN_TRANSITION,
            plan,
            (PhaseChanged(1, MINE, Phase.DRAW, 1, MINE, Phase.STANDBY),),
        )


def test_the_plan_and_the_result_cannot_be_read_as_true_or_false(state, progressor):
    plan = progressor.plan(state)
    result = progressor.advance(state)

    with pytest.raises(TypeError):
        bool(plan)
    with pytest.raises(TypeError):
        bool(result)


def test_an_allowed_plan_still_lists_the_rules_it_did_not_look_at(state, progressor):
    """
    ``VALID`` 는 "순서가 맞다" 는 뜻일 뿐이다. 보지 않은 규칙은 허가와
    **함께** 남아 있어야 한다 — 사라지면 다음 사람이 전체 허가로 읽는다.
    """
    plan = progressor.plan(state)

    assert plan.permits_transition is True
    assert plan.unresolved_rules == UNRESOLVED_PROGRESSION_RULES
    assert any("선공 첫 턴" in rule for rule in plan.unresolved_rules)
    assert any("우선권" in rule for rule in plan.unresolved_rules)


def test_the_first_turn_battle_phase_rule_is_recorded_not_guessed(state, progressor):
    """
    선공 첫 턴에는 배틀 페이즈를 실행할 수 없다. **이 엔진은 그 규칙을 아직
    구현하지 않았고, 구현한 척하지도 않는다** — 목록에 적어 둘 뿐이다.
    """
    state.turn.set_phase(Phase.MAIN1)
    plan = progressor.plan(state)

    assert state.turn.turn_number == 1
    assert plan.transition.after.phase is Phase.BATTLE
    assert any("선공 첫 턴" in rule for rule in plan.unresolved_rules)


# ======================================================================
# 7. 변화 기록
# ======================================================================


def test_advancing_records_exactly_one_change(state, progressor):
    result = progressor.advance(state)

    assert len(result.deltas) == 1
    delta = result.deltas[0]
    assert isinstance(delta, PhaseChanged)
    assert delta.from_phase is Phase.DRAW
    assert delta.to_phase is Phase.STANDBY
    assert delta.changes_turn is False


def test_a_turn_change_is_one_event_not_two(state, progressor):
    """
    턴 넘김은 **한 사건**이다. 페이즈 변화와 턴 변화를 두 장으로 적으면
    세는 쪽이 한 번의 일을 두 번 센다.
    """
    state.turn.set_phase(Phase.END)
    result = progressor.advance(state)

    assert len(result.deltas) == 1
    delta = result.deltas[0]
    assert delta.changes_turn is True
    assert delta.changes_turn_player is True
    assert (delta.from_turn, delta.to_turn) == (1, 2)


def test_a_change_that_changes_nothing_cannot_be_recorded():
    with pytest.raises(ValueError):
        PhaseChanged(1, MINE, Phase.DRAW, 1, MINE, Phase.DRAW)


def test_the_record_is_a_state_delta_like_every_other_change(state, progressor):
    """
    새 이벤트 모델을 만들지 않았다. 기존 :class:`StateDelta` 그대로이므로
    ``EventJournal`` 이 붙을 자리가 이미 있다.
    """
    delta = progressor.advance(state).deltas[0]

    assert isinstance(delta, StateDelta)
    assert delta.kind == "phase_changed"
    assert delta.to_dict()["from"]["phase"] == "DRAW"
    assert delta.describe_ko()


# ======================================================================
# 8. 결정론
# ======================================================================


def test_the_same_board_and_the_same_command_give_the_same_board(progressor):
    first, second = new_state(), new_state()
    assert first.state_hash() == second.state_hash()

    progressor.advance(first)
    progressor.advance(second)

    assert first.state_hash() == second.state_hash()


def test_advancing_changes_the_board_hash(state, progressor):
    """페이즈는 판의 모양에 들어간다 — 같은 카드 배치라도 자리가 다르면 다르다."""
    before = state.state_hash()
    progressor.advance(state)

    assert state.state_hash() != before


def test_the_plan_is_the_same_value_every_time(state, progressor):
    assert (
        progressor.plan(state).canonical_state()
        == progressor.plan(state).canonical_state()
    )


def test_planning_never_moves_the_board(state, progressor):
    before = state.state_hash()
    for _ in range(3):
        progressor.plan(state)
        progressor.plan(state, Phase.BATTLE)
    assert state.state_hash() == before


def test_a_cloned_board_advances_on_its_own(state, progressor):
    """복제본을 옮겨도 원본은 그대로다."""
    copy = state.clone()
    before = state.state_hash()

    progressor.advance(copy)

    assert state.state_hash() == before
    assert state.turn.phase is Phase.DRAW
    assert copy.turn.phase is Phase.STANDBY


def test_two_clones_walked_the_same_way_end_up_identical(state, progressor):
    left, right = state.clone(), state.clone()
    for _ in range(len(TURN_PHASE_ORDER) + 2):
        progressor.advance(left)
        progressor.advance(right)

    assert left.state_hash() == right.state_hash()


def test_card_definitions_are_untouched(state, progressor):
    """진행 계층은 카드 정의를 읽지도 않는다."""
    instance = state.player(MINE).monster_zone[0]
    before = (instance.card_id, instance.owner, instance.controller, instance.position)

    for _ in range(len(TURN_PHASE_ORDER) + 1):
        progressor.advance(state)

    after = (instance.card_id, instance.owner, instance.controller, instance.position)
    assert after == before


# ======================================================================
# 9. 우선권과의 경계
# ======================================================================


def test_the_turn_player_changing_does_not_move_priority(state, progressor):
    """
    **턴 플레이어 ≠ 우선권 보유자.** 턴이 넘어가도 진행 계층은 우선권을
    건드리지 않는다 — 그것은 우선권 계층의 규칙이다.
    """
    priority = PriorityState(
        holder=PriorityHolder.PLAYER_0,
        window=ResponseWindow.ACTION,
        turn_player=MINE,
        phase=Phase.END,
    )
    state.turn.set_phase(Phase.END)
    before = priority.canonical_state()

    progressor.advance(state)

    assert state.turn.turn_player == THEIRS
    assert priority.canonical_state() == before
    assert priority.holder is PriorityHolder.PLAYER_0


def test_a_transition_says_priority_must_be_redecided_but_not_by_whom(state, progressor):
    transition = progressor.plan(state).transition

    assert transition.requires_priority_update is True
    assert not hasattr(transition, "priority")
    assert not hasattr(transition, "holder")


def test_progression_does_not_touch_the_priority_layer():
    """
    문자열이 아니라 **AST** 로 본다 — 설명문에 ``PriorityState`` 가 적혀
    있다고 해서 쓰는 것은 아니다.
    """
    tree = ast.parse(pathlib.Path("engine/turn_progression.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    for forbidden in ("engine.priority", "engine.chain", "engine.trigger",
                      "engine.timing", "engine.trigger_chain", "engine.trigger_order"):
        assert forbidden not in imported, f"{forbidden} 를 가져오면 안 됩니다."


def test_progression_builds_no_triggers_and_no_chain_links():
    """
    페이즈 변화는 사건이지만, 후보를 만드는 것은 트리거 계층의 일이다.
    여기서 만들기 시작하면 수집 경로가 둘로 갈린다.
    """
    tree = ast.parse(pathlib.Path("engine/turn_progression.py").read_text("utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    for forbidden in ("TimingEvent", "TriggerCandidate", "ChainLink", "PriorityState"):
        assert forbidden not in called


# ======================================================================
# 10. ActionExecutor 와의 경계
# ======================================================================


def test_change_phase_is_still_not_authorized_by_the_rules(state):
    """
    **진행 계층이 생겼다고 해서 Action 이 허가되지는 않는다.** 우선권 ·
    체인 · 페이즈 진입 규칙이 아직 없으므로 검증기는 여전히 모른다고 말한다.
    """
    action = PlayerAction.change_phase(MINE, Phase.STANDBY)
    verdict = ActionValidator(GameStateView.from_state(state, viewer=MINE)).validate(
        action
    )

    assert verdict.permits_execution is False
    assert verdict.validity is ActionValidity.UNKNOWN


def test_the_default_executor_still_knows_no_actions():
    """기본 실행기는 여전히 비어 있다 — 핸들러를 손으로 등록해야 한다."""
    assert ActionExecutor().supported == frozenset()


def test_the_handler_matches_the_action_handler_protocol():
    assert isinstance(PhaseTransitionHandler(), ActionHandler)


def test_a_registered_handler_advances_the_phase_when_the_rules_allow_it(state):
    """
    규칙 계층이 허가를 내주는 날의 경로를 미리 확인한다. 허가는 공개
    생성자로 만들고, 실행은 ``ActionExecutor`` 를 그대로 통과한다.
    """
    executor = ActionExecutor().register(
        PlayerActionKind.CHANGE_PHASE, PhaseTransitionHandler()
    )
    action = PlayerAction.change_phase(MINE, Phase.STANDBY)

    execution = executor.execute(state, action, authorization=authorized())

    assert execution.status is ActionStatus.EXECUTED
    assert state.turn.phase is Phase.STANDBY
    assert len(execution.deltas) == 1
    assert isinstance(execution.deltas[0], PhaseChanged)


def test_the_handler_refuses_to_guess_what_end_phase_means(state):
    """
    ``END_PHASE`` 가 "엔드 페이즈로 간다" 인지 "턴을 끝낸다" 인지 정해져
    있지 않다. **고르지 않는다** — 고르는 순간 추측이 규칙이 된다.
    """
    handler = PhaseTransitionHandler()
    with pytest.raises(TurnProgressionError):
        handler.apply(state, PlayerAction.end_phase(MINE))


def test_an_authorization_that_contradicts_the_order_does_not_silently_pass(state):
    """
    허가가 났는데 진행 순서가 거절하면 **조용히 넘어가지 않는다.** 판은
    그대로이고, 실행기는 오류로 받는다.
    """
    executor = ActionExecutor().register(
        PlayerActionKind.CHANGE_PHASE, PhaseTransitionHandler()
    )
    state.turn.set_phase(Phase.MAIN2)
    before = state.state_hash()

    execution = executor.execute(
        state,
        PlayerAction.change_phase(MINE, Phase.DRAW),
        authorization=authorized(),
    )

    assert execution.status is ActionStatus.EXECUTION_ERROR
    assert execution.deltas == ()
    assert state.state_hash() == before


def test_the_executor_layer_holds_no_turn_rules_of_its_own():
    """
    ``action_execution.py`` 는 진행 계층을 가져오지 않는다 — 규칙이 두 곳에
    있으면 둘이 갈린다.
    """
    tree = ast.parse(pathlib.Path("engine/action_execution.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "engine.turn_progression" not in imported


def test_the_handler_itself_holds_no_rules():
    """
    핸들러는 껍데기다. 자기 안에 페이즈 순서를 들고 있지 않고,
    ``TurnProgressor`` 에게 전부 넘긴다.
    """
    source = pathlib.Path("engine/turn_progression.py").read_text("utf-8")
    tree = ast.parse(source)
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "PhaseTransitionHandler"
    )
    names = {node.id for node in ast.walk(handler) if isinstance(node, ast.Name)}

    assert "TURN_PHASE_ORDER" not in names
    assert "Phase" not in names


# ======================================================================
# 11. 낮은 계층을 그대로 쓴다
# ======================================================================


def test_progression_adds_no_new_mutation_api_to_the_board(state, progressor):
    """
    옮기는 일은 Phase 1 의 ``TurnState`` API 로만 한다. ``GameState`` 에
    새 메서드를 붙이지 않았다.
    """
    assert not hasattr(state, "advance_phase")
    assert not hasattr(state, "begin_next_turn")
    assert hasattr(state.turn, "advance_phase")
    assert hasattr(state.turn, "begin_next_turn")


def test_the_end_of_turn_step_that_turn_state_cannot_do_alone():
    """
    ``TurnState.advance_phase()`` 는 엔드 페이즈에서 **멈춘다.** 턴을 넘기는
    한 걸음이 이 계층이 더하는 전부다.
    """
    turn = TurnState(phase=Phase.END)
    assert turn.advance_phase() is Phase.END
    assert turn.turn_number == 1

    position_after = TurnProgressor().next_position(TurnPosition.of(turn))
    assert position_after == TurnPosition(2, THEIRS, Phase.DRAW)


def test_next_position_is_a_pure_calculation():
    """계산에는 판이 필요 없다 — 자리 하나면 다음 자리가 나온다."""
    progressor = TurnProgressor()

    assert progressor.next_position(TurnPosition(3, THEIRS, Phase.DAMAGE)) is None
    assert progressor.next_position(TurnPosition(3, THEIRS, Phase.BATTLE)) == (
        TurnPosition(3, THEIRS, Phase.MAIN2)
    )


def test_the_progressor_keeps_no_state_between_calls(state):
    """같은 판을 두 실행기가 번갈아 옮겨도 결과가 같다."""
    left, right = state.clone(), state.clone()
    TurnProgressor().advance(left)
    TurnProgressor().advance(right)

    assert left.state_hash() == right.state_hash()


def test_a_view_cannot_be_advanced(state, progressor):
    """관측은 읽기 전용이다. 실수로 넘기면 곧바로 거절한다."""
    with pytest.raises(TypeError):
        progressor.advance(GameStateView.from_state(state, viewer=MINE))
