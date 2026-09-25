"""
Phase 2-AH — 계획이 내다보는 판.

    plan
      board = state.project()      판의 **모양**만 복제, 난수원은 공유
      for 조작:
          조건 ← board · values
          step ← plan(board)
          values ← step.result()
          apply(board, step)       **투영에** 반영 → 뒤의 일이 앞을 본다
    apply
      for step: apply(state, step) 진짜 판은 계획이 끝난 뒤에야 바뀐다

STRUCTURAL-94 의 진짜 원인
---------------------------
**앞선 조작의 결과는 계획 시점에 이미 있었다.** 계획이 무엇을 할지
확정하고, 적용은 확정된 것만 하기 때문이다 (2-AD). 없던 것은 결과가
아니라 **판**이었다 — 계획이 읽는 판이 효과 시작 시점에 멈춰 있었다.

그래서 상대 패에서 무작위로 두 장을 따로 고르는 효과가 **같은 카드를 두
번 고를 수 있었다.** 이 파일의 첫 시험이 그것을 재현한다.

셋을 뭉개지 않는다
------------------
========================  ==========================================
아직 닿지 않았다            ``ResultAvailability.NOT_YET``
하지 않았다                 ``ResultAvailability.NOT_APPLIED``  (2-AG)
그 칸이 없다                ``ResultAvailability.NO_FIELD``
========================  ==========================================

셋 다 "수가 없다" 로 끝나지만 **고쳐야 할 것이 다르다.** 그리고 셋 다
``UNKNOWN`` ("규칙을 판정할 수 없다")과 다르다.
"""

import ast
import pathlib

import pytest

from engine.condition import ConditionResult, PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, CostGroup, Selection
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionError,
    EffectProvenance,
    OperationGuard,
)
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.operation import (
    COUNTING_KINDS,
    CardOperation,
    DrawOperation,
    LifeChangeOperation,
    OperationKind,
    Partial,
)
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.target import (
    PRIMARY_TARGET,
    RandomSelectionSpec,
    SelectionCount,
    TargetBinding,
    TargetRef,
    TargetSpec,
    ZoneCountTerm,
)
from engine.execution import (
    DECLARED_NUMBER,
    DeclarationBinding,
    DeclaredNumber,
    DeclaredNumberSpec,
    ExecutionLookupError,
    ExecutionValues,
    NumberDomain,
    NumericTest,
    OperationOutcome,
    OperationResult,
    ResultAvailability,
    ResultField,
    ResultLookup,
    ResultRef,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
P1, P2 = 0, 1
LAB = 999_010

A, B, C, D = 55144522, 66719324, 5318639, 83764718
MINE = [70368879, 15103313, 55144522]
FILLER = 21844576
FIRST, SECOND = TargetRef("first"), TargetRef("second")
AFFECTED = ResultRef(0, ResultField.AFFECTED_COUNT)


class Ruling:
    """시험용 파괴 판정기."""

    __slots__ = ("answers", "default")

    def __init__(self, answers=None, default=ConditionResult.TRUE):
        self.answers = dict(answers or {})
        self.default = default

    def may_be_destroyed(self, instance: InstanceId) -> ConditionResult:
        return self.answers.get(instance, self.default)


def hand_state(repository, seed: int | None = 7, opponent_hand: int = 4) -> GameState:
    game = GameState.create(
        repository,
        decks=([FILLER] * 16, [A, B, C, D] + [FILLER] * 12),
        seed=seed,
    )
    game.draw(P1, 1)
    game.draw(P2, opponent_hand)
    game.turn.set_phase(Phase.MAIN1)
    return game


def field_state(repository, seed: int | None = 7) -> GameState:
    game = GameState.create(
        repository, decks=(MINE + [FILLER] * 13, [FILLER] * 16), seed=seed
    )
    game.draw(P1, 3)
    for _ in range(3):
        game.move(
            game.player(P1).hand[0].instance_id,
            Zone.MZONE,
            to_player=P1,
            position=Position.FACEUP_ATTACK,
        )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return hand_state(repository)


def one_random_from_opponent_hand() -> TargetSpec:
    return TargetSpec.at_random(
        RandomSelectionSpec(
            source=CandidateSource(
                zones=frozenset({Zone.HAND}), owner=PlayerRef.OPPONENT
            ),
            count=SelectionCount.fixed(1),
        )
    )


def two_random_sends(ordinal=0) -> EffectDefinition:
    """상대 패에서 무작위로 한 장씩, **두 번** 따로 고른다."""
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        targets=(
            TargetBinding(FIRST, one_random_from_opponent_hand()),
            TargetBinding(SECOND, one_random_from_opponent_hand()),
        ),
        operations=(
            CardOperation.send_to_grave(FIRST),
            CardOperation.send_to_grave(SECOND),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True, note="Phase 2-AH"),
    )


def run(game, definition, ruling=None, chosen=None, journal=None, **context):
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        destruction=ruling if ruling is not None else Ruling(),
        journal=journal,
    )
    selections = ()
    if chosen is not None:
        selections = (TargetSelection(PRIMARY_TARGET, Selection(tuple(chosen))),)
    return executor.execute(
        game,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref,
            controller=P1,
            selections=selections,
            **context,
        ),
    )


def monsters(game) -> list[InstanceId]:
    return [card.instance_id for card in game.player(P1).monster_zone if card]


def untouched(game, before_hash, result, journal=None):
    assert result.status is not ResolutionStatus.RESOLVED
    assert result.applied == ()
    assert result.deltas == ()
    assert game.state_hash() == before_hash
    if journal is not None:
        assert len(journal) == 0


# ======================================================================
# A. 진짜 원인 — 계획이 읽던 판이 멈춰 있었다
# ======================================================================


def test_a_two_random_picks_never_take_the_same_card(state):
    """
    **이것이 STRUCTURAL-94 의 실제 증상이었다.**

    두 무작위 선택이 같은 판을 두 번 보면 같은 카드를 두 번 고를 수
    있고, 그러면 "두 장을 보냈다" 고 기록하면서 한 장만 움직인다.

    이제 뒤의 선택은 **앞의 선택이 끝난 판**을 본다.
    """
    result = run(state, two_random_sends())

    assert result.status is ResolutionStatus.RESOLVED
    first, second = result.applied
    (one,), (two,) = first.instances, second.instances
    assert one != two
    assert len(state.player(P2).hand) == 2
    assert len(state.player(P2).grave) == 2


def test_a_the_second_pick_refuses_when_nothing_is_left(repository):
    """
    상대 패가 한 장뿐이면 **두 번째는 고를 것이 없다.** 예전에는 같은
    카드를 또 골라 성공했다고 답했다.

    그리고 거절이므로 **첫 번째도 일어나지 않는다** — 전부 아니면 무는
    그대로다.
    """
    state = hand_state(repository, opponent_hand=1)
    before, journal = state.state_hash(), EventJournal()

    result = run(state, two_random_sends(), journal=journal)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert len(state.player(P2).hand) == 1
    assert len(state.player(P2).grave) == 0
    untouched(state, before, result, journal)


def test_a_the_plan_looks_at_a_projection_not_the_board():
    """
    §21 — 계획 단계는 **진짜 판을 바꾸지 않는다.** 대신 투영을 만든다.
    """
    tree = ast.parse((ROOT / "engine" / "effect" / "executor.py").read_text("utf-8"))
    (plan,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_plan"
    ]
    body = ast.unparse(plan)

    assert "state.project()" in body
    # 계획이 부르는 적용은 **투영에만** 한다.
    assert "self._apply(board, step)" in body
    assert "self._apply(state" not in body


def test_a_a_projection_shares_the_randomness_but_not_the_board(repository):
    """
    **판의 모양은 복제되고 흐름의 위치는 공유된다** — 해시에서 난수원을
    뺀 것과 같은 가름이다.

    난수원을 복제하면 계획이 꺼낸 횟수가 진짜 판에 남지 않아 같은
    seed 로 다시 돌렸을 때 다른 판이 된다.
    """
    state = hand_state(repository)
    board = state.project()

    assert board.state_hash() == state.state_hash()

    board.draw(P1, 1)
    assert board.state_hash() != state.state_hash()  # 판은 따로다
    assert len(state.player(P1).hand) == 1

    board.randomness.next_index(4)
    assert state.randomness.draws == board.randomness.draws  # 난수원은 함께다

    # ``clone`` 은 여전히 난수원까지 복제한다 — 다른 도구다.
    copy = state.clone()
    copy.randomness.next_index(4)
    assert copy.randomness.draws != state.randomness.draws


# ======================================================================
# B · C. 결과는 계획 시점에 이미 있다
# ======================================================================


def test_b_a_result_exists_as_soon_as_the_operation_is_planned(state):
    """
    요청서가 걱정한 "계획 시점에는 결과가 없다" 는 **이 엔진에서는
    사실이 아니었다.** 계획이 무엇을 할지 확정하고 적용은 확정된 것만
    하므로, 뒤의 일이 읽는 수와 실제로 일어날 일이 어긋나지 않는다.
    """
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 1),
        source_card_id=LAB,
        targets=TargetBinding.single(one_random_from_opponent_hand()),
        operations=(
            CardOperation.send_to_grave(PRIMARY_TARGET),
            DrawOperation(count=SelectionCount.from_result(AFFECTED)),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )
    before = len(state.player(P1).hand)

    result = run(state, definition)

    assert result.status is ResolutionStatus.RESOLVED
    sent, drew = result.applied
    assert len(sent.instances) == 1 and drew.amount == 1
    assert len(state.player(P1).hand) == before + 1


def test_c_the_applied_record_matches_what_was_planned(state):
    """
    적용이 계획과 어긋나면 결과가 거짓말이 된다. 기록된 카드가 실제로
    그 자리에 있는지 확인한다.
    """
    result = run(state, two_random_sends())

    for applied in result.applied:
        for instance in applied.instances:
            assert state.locate(instance).zone is Zone.GRAVE


# ======================================================================
# D · E · F. 조건이 보는 수 (§11)
# ======================================================================


def destroy_then_draw(tests, ordinal=2) -> EffectDefinition:
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.choosing(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=frozenset({Zone.MZONE}), owner=PlayerRef.CONTROLLER
                    ),
                    minimum=1,
                    maximum=3,
                )
            )
        ),
        operations=(
            CardOperation(
                operation=OperationKind.DESTROY,
                target_ref=PRIMARY_TARGET,
                partial=Partial.AS_MANY_AS_POSSIBLE,
            ),
            DrawOperation(count=1),
        ),
        guards=(
            OperationGuard(1, SelectionCount.from_result(AFFECTED), tests),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )


def test_d_two_of_three_destroyed_satisfies_at_least_two(repository):
    """§11 첫 번째 — ``affected_count = 2`` · ``2 >= 2`` → TRUE → B 실행."""
    state = field_state(repository)
    field = monsters(state)

    result = run(
        state,
        destroy_then_draw((NumericTest.at_least(2),)),
        Ruling({field[0]: ConditionResult.FALSE}),
        field,
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert len(result.applied) == 2
    assert len(state.player(P1).hand) == 1


def test_e_one_of_three_destroyed_fails_at_least_two(repository):
    """§11 두 번째 — ``1 >= 2`` → FALSE → B 실행하지 않는다."""
    state = field_state(repository)
    field = monsters(state)

    result = run(
        state,
        destroy_then_draw((NumericTest.at_least(2),)),
        Ruling({field[0]: ConditionResult.FALSE, field[1]: ConditionResult.FALSE}),
        field,
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert len(result.applied) == 1  # 파괴만 일어났다
    assert len(state.player(P1).hand) == 0
    assert len(monsters(state)) == 2


def test_f_an_unknown_value_never_decides(repository):
    """§11 세 번째 — 수를 모르면 **임의로 실행하지 않는다.**"""
    state = field_state(repository)
    before, journal = state.state_hash(), EventJournal()
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 3),
        source_card_id=LAB,
        operations=(DrawOperation(count=1), DrawOperation(count=1)),
        guards=(
            OperationGuard(
                1,
                SelectionCount.unknown("아직 없는 계층"),
                (NumericTest.any_at_all(),),
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(state, definition, journal=journal)

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    untouched(state, before, result, journal)


# ======================================================================
# G · H · I. 없는 참조 · 미래 참조 · 고리 (§17 · §18 · §19)
# ======================================================================


@pytest.mark.parametrize(
    "values,expected",
    [
        (ExecutionValues(), ResultAvailability.NOT_YET),
        (
            ExecutionValues().with_result(
                OperationResult(0, outcome=OperationOutcome.NOT_APPLIED)
            ),
            ResultAvailability.NOT_APPLIED,
        ),
        (
            ExecutionValues().with_result(OperationResult(0)),
            ResultAvailability.NO_FIELD,
        ),
        (
            ExecutionValues().with_result(OperationResult(0, affected_count=2)),
            ResultAvailability.AVAILABLE,
        ),
    ],
)
def test_g_why_a_result_is_missing_is_part_of_the_answer(values, expected):
    """
    §4 · §19 — 셋 다 "수가 없다" 로 끝나지만 **고쳐야 할 것이 다르다.**
    """
    found = values.look_up(AFFECTED)

    assert found.availability is expected
    assert isinstance(found, ResultLookup)
    if expected is ResultAvailability.AVAILABLE:
        assert found.value == 2
    else:
        assert found.value is None
        assert found.reason
        with pytest.raises(ExecutionLookupError) as raised:
            values.result(AFFECTED)
        assert raised.value.availability is expected


def test_g_a_lookup_is_not_a_truth_value():
    with pytest.raises(TypeError):
        bool(ResultLookup(ResultAvailability.NOT_YET, reason="아직"))


def test_g_a_skipped_operation_is_not_a_rule_gap(repository):
    """
    건너뛴 일의 수를 읽으면 **"규칙이 없다" 가 아니라 "그 일을 하지
    않았다"** 고 답한다. 그리고 그 차이가 ``missing`` 에 남는다.
    """
    state = field_state(repository)
    before = state.state_hash()
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 4),
        source_card_id=LAB,
        operations=(
            DrawOperation(count=1),
            DrawOperation(count=1),
            DrawOperation(count=SelectionCount.from_result(ResultRef(1))),
        ),
        guards=(
            OperationGuard(
                1, SelectionCount.fixed(1), (NumericTest.at_least(9),)
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(state, definition)

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert "하지 않았습니다" in result.reason
    assert result.missing == "rule for reading a skipped operation's count"
    untouched(state, before, result)


def test_h_a_future_reference_cannot_be_written():
    """§17 — 미래를 가리키는 정의는 **만들어지지 않는다.**"""
    for index in (1, 2):
        with pytest.raises(EffectDefinitionError, match="앞선 일만"):
            EffectDefinition(
                effect_ref=EffectRef(LAB, 5),
                source_card_id=LAB,
                operations=(
                    DrawOperation(count=SelectionCount.from_result(ResultRef(index))),
                    DrawOperation(1),
                ),
                provenance=EffectProvenance.hand_written(verified=True),
            )


def test_h_an_operation_that_yields_no_count_cannot_be_read():
    """
    §19 — **없는 칸**을 가리키는 것도 적는 순간 막는다. 라이프 증감과
    셔플에는 장수가 없다.
    """
    with pytest.raises(EffectDefinitionError, match="장수를 내지 않습니다"):
        EffectDefinition(
            effect_ref=EffectRef(LAB, 6),
            source_card_id=LAB,
            operations=(
                LifeChangeOperation(delta=1000),
                DrawOperation(count=SelectionCount.from_result(AFFECTED)),
            ),
            provenance=EffectProvenance.hand_written(verified=True),
        )

    assert OperationKind.CHANGE_LIFE not in COUNTING_KINDS
    assert OperationKind.SHUFFLE not in COUNTING_KINDS
    assert OperationKind.DRAW in COUNTING_KINDS


def test_i_a_cycle_cannot_be_built_so_no_solver_is_needed():
    """
    §18 — A 가 B 를, B 가 A 를 가리키는 고리는 **만들어질 수 없다.**
    참조가 언제나 **앞**을 가리켜야 하므로 순서가 이미 위상 정렬이다.

    그래서 고리를 푸는 장치를 따로 두지 않았다 — 무한 대기가 생길 자리가
    없다.
    """
    with pytest.raises(EffectDefinitionError, match="앞선 일만"):
        EffectDefinition(
            effect_ref=EffectRef(LAB, 7),
            source_card_id=LAB,
            operations=(
                DrawOperation(count=SelectionCount.from_result(ResultRef(1))),
                DrawOperation(count=SelectionCount.from_result(AFFECTED)),
            ),
            provenance=EffectProvenance.hand_written(verified=True),
        )

    source = (ROOT / "engine" / "effect").glob("*.py")
    for path in source:
        text = path.read_text("utf-8")
        for word in ("topological", "cycle_solver", "while True"):
            assert word not in text, f"{path.name}: {word}"


# ======================================================================
# J · K · L. 선택 · 무작위 · 부분 결과 의존 (§14 · §15 · §16)
# ======================================================================


def test_j_a_pending_choice_is_not_a_number(state):
    """
    §14 — 선언이 아직 없으면 조건도 정할 수 없다. **임의의 숫자를 넣지
    않는다.**
    """
    before = state.state_hash()
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 8),
        source_card_id=LAB,
        operations=(DrawOperation(count=1), DrawOperation(count=1)),
        guards=(
            OperationGuard(
                1,
                SelectionCount.from_declaration(DECLARED_NUMBER),
                (NumericTest.any_at_all(),),
            ),
        ),
        declarations=(
            DeclarationBinding(
                DECLARED_NUMBER, DeclaredNumberSpec(NumberDomain.between(1, 3))
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(state, definition)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    untouched(state, before, result)

    # 선언이 들어오면 그때 정해진다.
    again = run(
        state, definition, declarations=(DeclaredNumber(DECLARED_NUMBER, 2),)
    )
    assert again.status is ResolutionStatus.RESOLVED


def test_k_a_random_selection_is_counted_only_after_it_is_rolled(state):
    """
    §15 — 고르기 전에 장수를 짐작하지 않는다. 그리고 조건을 보는 일이
    **난수를 꺼내지 않는다.**
    """
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 9),
        source_card_id=LAB,
        targets=TargetBinding.single(one_random_from_opponent_hand()),
        operations=(
            CardOperation.send_to_grave(PRIMARY_TARGET),
            DrawOperation(count=1),
        ),
        guards=(
            OperationGuard(1, SelectionCount.from_result(AFFECTED), (NumericTest.any_at_all(),)),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(state, definition)

    assert result.status is ResolutionStatus.RESOLVED
    # 무작위 선택 한 번 = 한 번 꺼냈다. 조건은 더 꺼내지 않았다.
    assert state.randomness.draws == 1


def test_k_the_condition_layer_never_touches_randomness():
    tree = ast.parse((ROOT / "engine" / "effect" / "executor.py").read_text("utf-8"))
    (guards,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_check_guards"
    ]
    body = ast.unparse(guards)

    for forbidden in ("randomness", "choose", "shuffle"):
        assert forbidden not in body


def test_l_a_partial_result_is_what_the_condition_sees(repository):
    """
    §16 — 부분 적용 자체를 조건으로 만들지 않는다. ``ResultRef`` 로
    필요한 수를 가져온다.
    """
    state = field_state(repository)
    field = monsters(state)

    result = run(
        state,
        destroy_then_draw((NumericTest.at_least(2), NumericTest.at_most(2))),
        Ruling({field[0]: ConditionResult.FALSE}),
        field,
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert len(result.applied[0].instances) == 2
    assert len(result.applied) == 2


# ======================================================================
# M ~ S. 복제 · 결정론 · 안전 · 정보 · 저널 · 해시
# ======================================================================


def test_m_a_clone_resolves_for_itself(repository):
    original = hand_state(repository, seed=21)
    copy = original.clone()

    run(copy, two_random_sends())

    assert len(original.player(P2).hand) == 4
    assert len(copy.player(P2).hand) == 2
    assert original.randomness.draws == 0
    assert copy.randomness.draws == 2


def test_n_the_same_board_gives_the_same_resolution(repository):
    picks = set()
    for _ in range(3):
        game = hand_state(repository, seed=13)
        result = run(game, two_random_sends())
        picks.add(
            tuple(i.value for applied in result.applied for i in applied.instances)
        )
    assert len(picks) == 1


def test_o_planning_consumes_randomness_exactly_once_per_roll(repository):
    """
    §24 — 투영이 제 난수원을 가지면 계획이 꺼낸 횟수가 진짜 판에 남지
    않는다. 공유하므로 남는다.
    """
    state = hand_state(repository)

    run(state, two_random_sends())

    assert state.randomness.draws == 2


def test_p_a_refused_plan_leaves_no_trace(repository):
    """
    §20 — 계획이 막히면 진짜 판은 한 글자도 바뀌지 않는다. 투영에서
    막히는 것도 마찬가지다.
    """
    state = hand_state(repository, opponent_hand=1)
    before, journal = state.state_hash(), EventJournal()

    result = run(state, two_random_sends(), journal=journal)

    untouched(state, before, result, journal)
    # 난수는 첫 선택에서 이미 꺼냈다 — 감추지 않는다 (Phase 2-AB 와 같다).
    assert state.randomness.draws == 1


def test_q_a_hidden_hand_stays_hidden_through_the_projection(state):
    """
    §25 — 투영은 **엔진이 보는 판**이다. 관측은 그대로다.
    """
    hidden = [card.card_id for card in state.player(P2).hand]

    result = run(state, two_random_sends())

    view = GameStateView.from_state(state, viewer=P1)
    assert view.player(P2).zone(Zone.HAND).concealed is True
    assert view.player(P2).zone(Zone.HAND).cards == ()

    moved = {
        state.find_instance(i).card_id
        for applied in result.applied
        for i in applied.instances
    }
    rendered = repr(result.to_dict())
    for card_id in hidden:
        if card_id not in moved:
            assert str(card_id) not in rendered


def test_r_the_journal_records_one_resolution(state):
    journal = EventJournal()

    run(state, two_random_sends(), journal=journal)

    assert len(journal) == 1
    rendered = repr(journal.to_dict() if hasattr(journal, "to_dict") else list(journal))
    for word in ("project", "not_yet", "availability"):
        assert word not in rendered


def test_s_the_projection_never_touches_the_hash(repository):
    left, right = hand_state(repository, seed=6), hand_state(repository, seed=6)
    assert left.state_hash() == right.state_hash()

    board = left.project()
    board.draw(P1, 2)

    assert left.state_hash() == right.state_hash()
    rendered = repr(left.canonical_state())
    for word in ("project", "not_yet", "availability"):
        assert word not in rendered


# ======================================================================
# T. 실제 corpus (§28)
# ======================================================================


def test_t_the_corpus_reads_the_board_after_an_operation(state):
    """
    한 효과 안에서 조작을 한 **뒤에** 판을 다시 읽는 함수가 실제
    스크립트에 **941개** 있다 (그중 30개는 결과 변수도 함께 쓴다).

    ::

        Duel.Destroy(g,REASON_EFFECT)
        ... Duel.GetLocationCount(tp,LOCATION_MZONE)   -- 13210191 · 2333466
        Duel.SpecialSummon(...)
        ... Duel.GetMatchingGroup(...)                  -- 24731453

    그 941개가 **이번 수정이 필요했던 이유**다. 계획이 멈춘 판을 보면
    이 모양을 옮길 때마다 틀린 답이 나온다.

    이 시험은 그 모양이 이제 실제로 도는지를 본다 — 앞의 일이 상대 패를
    줄였고, 뒤의 일이 줄어든 패를 본다.
    """
    result = run(state, two_random_sends())

    first, second = result.applied
    assert first.instances[0] != second.instances[0]
    assert len(state.player(P2).hand) == 2


def test_t_no_real_card_was_registered_this_phase():
    """
    **0장 등재했다.** 계획이 보는 판을 고친 것이지 새 카드를 옮긴 것이
    아니다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    assert len(EFFECT_LIBRARY) == 15
    for entry in EFFECT_LIBRARY:
        assert entry.definition.guards == ()
