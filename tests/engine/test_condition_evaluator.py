"""
engine/condition/evaluator.py — 경계를 지킨다.

조건은 **질문이지 명령이 아니다.** 이 파일은 그것이 코드로 보장되는지 본다.

- D. 평가 전후로 ``state_hash()`` 가 같다
- E. 조건은 ``GameStateView`` 를 통해서만 판을 읽는다
- G. Phase 2-A 의 스냅숏 의미론이 유지된다
"""

import ast
import dataclasses
import pathlib

import pytest

from engine.condition import (
    Always,
    And,
    CardIsInZone,
    ConditionContext,
    ConditionEvaluator,
    ConditionResult,
    ConditionVerdict,
    IsTurnPlayer,
    LifePointsAtLeast,
    Not,
    Or,
    PhaseIs,
    PlayerRef,
    UnimplementedRule,
    ZoneCountAtLeast,
)
from engine.game_state_view import GameStateView
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

DECK_A = list(range(1000, 1040))
DECK_B = list(range(2000, 2040))


@pytest.fixture
def state() -> GameState:
    game = GameState.create(decks=(DECK_A, DECK_B), extra_decks=(list(range(3000, 3015)), []))
    game.draw(0, 5)
    game.draw(1, 5)
    game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    return game


@pytest.fixture
def evaluator(state) -> ConditionEvaluator:
    return ConditionEvaluator(GameStateView.from_state(state, viewer=0))


@pytest.fixture
def context() -> ConditionContext:
    return ConditionContext(player=0)


def _snapshot(state: GameState) -> tuple:
    """해시에 안 들어가는 것까지 함께 본다."""
    return (
        state.state_hash(),
        state.allocator.next_value,
        len(state.uses),
        state.turn.canonical_state(),
        [len(state.player(p).zone(z)) for p in (0, 1) for z in Zone if z in state.player(p).zones],
    )


# ----------------------------------------------------------------------
# 판정과 근거
# ----------------------------------------------------------------------


def test_evaluator_returns_a_verdict_with_a_description(evaluator, context):
    verdict = evaluator.evaluate(PhaseIs((Phase.DRAW,)), context)
    assert isinstance(verdict, ConditionVerdict)
    assert verdict.result is ConditionResult.TRUE
    assert verdict.is_true is True
    assert verdict.description == "페이즈가 DRAW"
    assert verdict.unknown_reasons == ()


def test_verdict_names_what_is_missing_when_unknown(evaluator, context):
    verdict = evaluator.evaluate(
        And((PhaseIs((Phase.DRAW,)), UnimplementedRule("chain (Phase 2-F)"))), context
    )
    assert verdict.is_unknown is True
    assert verdict.unknown_reasons == ("규칙 미구현: chain (Phase 2-F)",)


def test_verdict_cannot_be_used_as_a_boolean(evaluator, context):
    """``if verdict:`` 로 UNKNOWN 이 참이 되는 길을 막는다."""
    verdict = evaluator.evaluate(UnimplementedRule("chain"), context)
    with pytest.raises(TypeError):
        bool(verdict)
    with pytest.raises(TypeError):
        if verdict:  # noqa: SIM103
            pass


def test_result_shortcut_gives_the_bare_value(evaluator, context):
    assert evaluator.result(PhaseIs((Phase.DRAW,)), context) is ConditionResult.TRUE


def test_verdict_is_immutable(evaluator, context):
    verdict = evaluator.evaluate(PhaseIs((Phase.DRAW,)), context)
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.result = ConditionResult.FALSE


# ----------------------------------------------------------------------
# E. 조건은 View 를 통해서만 판을 읽는다
# ----------------------------------------------------------------------


def test_evaluator_refuses_a_raw_game_state(state):
    """
    ``GameState`` 를 받으면 ``move()`` · ``change_life()`` 가 손에 닿는다.
    조건이 판을 바꿀 수 있게 되는 것이므로 타입 단계에서 막는다.
    """
    with pytest.raises(TypeError) as excinfo:
        ConditionEvaluator(state)
    assert "GameStateView" in str(excinfo.value)


def test_the_condition_package_never_imports_game_state():
    """
    조건 코드가 ``GameState`` 를 직접 가져오면 우회 경로가 생긴다.
    타입 검사용 ``TYPE_CHECKING`` 블록의 ``GameStateView`` 만 허용한다.
    """
    root = pathlib.Path("engine/condition")
    offenders: list[str] = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "game_state" in node.module and "game_state_view" not in node.module:
                    offenders.append(f"{path}: {node.module}")
            if isinstance(node, ast.Name) and node.id in {"GameState", "move_card"}:
                offenders.append(f"{path}: {node.id}")
    assert offenders == [], (
        f"조건 계층이 상태 계층을 직접 만집니다: {offenders}. "
        "조건은 GameStateView 로만 판을 읽어야 합니다."
    )


def test_the_condition_package_borrows_nothing_from_analysis():
    """
    ADR-007 의 경계. ``analysis.ConditionNode`` 는 Lua 를 읽은 **기록**이고
    여기의 조건은 **실행용**이다. 한 타입으로 합치면 "스크립트가 무엇이라
    적혀 있는가" 와 "지금 판에서 참인가" 가 섞인다.
    """
    root = pathlib.Path("engine/condition")
    offenders: list[str] = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "analysis"
            ):
                offenders.append(f"{path}: {node.module}")
    assert offenders == [], f"조건 계층이 analysis 를 가져옵니다: {offenders}"


def test_evaluator_exposes_no_mutation_path(evaluator):
    for forbidden in (
        "move",
        "move_card",
        "draw",
        "change_life",
        "apply",
        "execute",
        "resolve",
        "state",
        "game_state",
    ):
        assert not hasattr(evaluator, forbidden), (
            f"ConditionEvaluator.{forbidden} 이 생겼습니다. 조건은 질문이지 "
            "명령이 아닙니다."
        )


# ----------------------------------------------------------------------
# D. 평가는 판을 바꾸지 않는다
# ----------------------------------------------------------------------


def test_evaluating_does_not_change_the_state(state, context):
    before = _snapshot(state)
    evaluator = ConditionEvaluator(GameStateView.from_state(state, viewer=0))

    on_field = state.player(0).monster_zone[0].instance_id
    for condition in (
        PhaseIs((Phase.DRAW, Phase.MAIN1)),
        IsTurnPlayer(PlayerRef.CONTROLLER),
        LifePointsAtLeast(PlayerRef.OPPONENT, 4000),
        ZoneCountAtLeast(PlayerRef.OPPONENT, Zone.HAND, 3),
        CardIsInZone(Zone.MZONE, PlayerRef.CONTROLLER, on_field),
        Not(UnimplementedRule("chain")),
        And((Always(ConditionResult.TRUE), Or((Always(ConditionResult.FALSE),)))),
    ):
        evaluator.evaluate(condition, context)
        evaluator.result(condition, context)

    assert _snapshot(state) == before


def test_evaluating_an_unknown_condition_does_not_change_the_state(state, context):
    """근거 수집이 한 번 더 순회하므로 그 경로도 확인한다."""
    before = _snapshot(state)
    evaluator = ConditionEvaluator(GameStateView.from_state(state, viewer=0))
    verdict = evaluator.evaluate(
        And((UnimplementedRule("chain"), UnimplementedRule("timing"))), context
    )
    assert verdict.is_unknown
    assert len(verdict.unknown_reasons) == 2
    assert _snapshot(state) == before


def test_evaluator_holds_no_state_of_its_own(evaluator, context):
    """같은 질문을 반복해도 답이 흔들리지 않아야 한다."""
    condition = And(
        (PhaseIs((Phase.DRAW,)), ZoneCountAtLeast(PlayerRef.OPPONENT, Zone.HAND, 4))
    )
    first = evaluator.evaluate(condition, context)
    for _ in range(5):
        assert evaluator.evaluate(condition, context).canonical_state() == (
            first.canonical_state()
        )


# ----------------------------------------------------------------------
# G. 스냅숏 의미론 (Phase 2-A)
# ----------------------------------------------------------------------


def test_the_evaluator_keeps_answering_from_its_snapshot(state, context):
    """
    관측은 만들어진 순간에 고정된다. 평가기를 만든 뒤 판이 바뀌어도 답은
    그대로여야 한다 — MCTS 가 한 노드를 평가하는 동안 흔들리면 안 된다.
    """
    evaluator = ConditionEvaluator(GameStateView.from_state(state, viewer=0))
    condition = LifePointsAtLeast(PlayerRef.CONTROLLER, 8000)
    assert evaluator.result(condition, context) is ConditionResult.TRUE

    state.player(0).change_life(-5000)

    # 옛 관측은 그대로다.
    assert evaluator.result(condition, context) is ConditionResult.TRUE
    # 새 관측은 새 값을 본다.
    fresh = ConditionEvaluator(GameStateView.from_state(state, viewer=0))
    assert fresh.result(condition, context) is ConditionResult.FALSE


def test_a_condition_cannot_reach_a_mutable_collection_through_the_view(state, context):
    """
    관측이 내부 리스트를 그대로 넘겨주면 조건 코드가 판을 건드릴 수 있다.
    Phase 2-A 가 tuple 로 막아 두었고, 조건 계층에서도 그대로여야 한다.
    """
    view = GameStateView.from_state(state, viewer=0)
    hand = view.me.hand
    assert isinstance(hand.cards, tuple)
    assert hand.cards is not state.player(0).hand
    with pytest.raises(AttributeError):
        hand.cards.append(None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.me.life_points = 0


# ----------------------------------------------------------------------
# 관점에 따라 답이 달라진다
# ----------------------------------------------------------------------


def test_two_viewers_can_get_different_answers_to_the_same_condition(state):
    """
    같은 조건이라도 보는 사람이 다르면 답이 다를 수 있다. 정보 은닉이
    조건 계층까지 이어진다는 뜻이다.
    """
    hidden = state.player(1).hand[0].instance_id
    condition = CardIsInZone(Zone.HAND, PlayerRef.CONTROLLER, hidden)
    context = ConditionContext(player=1)

    owner = ConditionEvaluator(GameStateView.from_state(state, viewer=1))
    foe = ConditionEvaluator(GameStateView.from_state(state, viewer=0))

    assert owner.result(condition, context) is ConditionResult.TRUE
    assert foe.result(condition, context) is ConditionResult.UNKNOWN
