"""
Phase 2-AG — 수를 보고 다음 일을 할지 정한다.

    Operation A
      → OperationResult (attempted · affected · outcome)
      → ResultRef            **명시적으로** 가리킨다
      → SelectionCount       값을 구한다
      → NumericTest          값을 견준다      ← 이번
      → TRUE / FALSE / UNKNOWN
      → Operation B          한다 / 건너뛴다 / 전체 거절

넷을 뭉개지 않는다
------------------
========================  ==========================================
값                        ``affected_count = 3``
조건                      ``affected_count >= 1``
도메인                    ``affected_count`` 가 1 이상이어야 한다는 규칙
실행 흐름                 조건이 참일 때 다음 일을 한다
========================  ==========================================

세 답이 세 가지 다른 일로 이어진다
----------------------------------
참이면 한다. 거짓이면 **건너뛴다** — 실패가 아니고 효과는 계속된다.
모르면 **전체를 거절한다** — 건너뛰는 것도 결정이고, 모르는 채로
결정하면 그 결정을 엔진이 지어낸 것이 된다.
"""

import ast
import dataclasses
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
from engine.effect.operation import CardOperation, DrawOperation, OperationKind, Partial
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.target import (
    PRIMARY_TARGET,
    SelectionCount,
    TargetBinding,
    TargetSpec,
    ZoneCountTerm,
)
from engine.execution import (
    DECLARED_NUMBER,
    BoardQuantity,
    Comparison,
    DeclarationBinding,
    DeclaredNumber,
    DeclaredNumberSpec,
    ExecutionLookupError,
    ExecutionValues,
    NumberDomain,
    NumericTest,
    OperationOutcome,
    OperationRequirement,
    OperationResult,
    QuantitySource,
    ResultField,
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
LAB = 999_009

MINE = [70368879, 15103313, 55144522]
FILLER = 21844576
AFFECTED = ResultRef(0, ResultField.AFFECTED_COUNT)


class Ruling:
    """카드마다 답을 정해 주는 파괴 판정기. **시험용이다.**"""

    __slots__ = ("answers", "default")

    def __init__(self, answers=None, default=ConditionResult.TRUE):
        self.answers = dict(answers or {})
        self.default = default

    def may_be_destroyed(self, instance: InstanceId) -> ConditionResult:
        return self.answers.get(instance, self.default)


def new_state(repository, seed: int | None = 7) -> GameState:
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
    return new_state(repository)


def monsters(game) -> list[InstanceId]:
    return [card.instance_id for card in game.player(P1).monster_zone if card]


def destroy_then_draw(tests, ordinal=0, value=None) -> EffectDefinition:
    """가능한 만큼 파괴하고, **그 수가 조건을 만족할 때만** 뽑는다."""
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
            OperationGuard(
                1,
                value if value is not None else SelectionCount.from_result(AFFECTED),
                tests,
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True, note="Phase 2-AG"),
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


def untouched(game, before_hash, before_field, result, journal=None):
    assert result.status is not ResolutionStatus.RESOLVED
    assert result.applied == ()
    assert result.deltas == ()
    assert game.state_hash() == before_hash
    assert monsters(game) == before_field
    if journal is not None:
        assert len(journal) == 0


# ======================================================================
# A. 수를 견주는 가장 작은 조건 (§3 · §5)
# ======================================================================


@pytest.mark.parametrize(
    "test,value,expected",
    [
        (NumericTest.any_at_all(), 0, ConditionResult.FALSE),
        (NumericTest.any_at_all(), 1, ConditionResult.TRUE),
        (NumericTest.any_at_all(), 9, ConditionResult.TRUE),
        (NumericTest.none_at_all(), 0, ConditionResult.TRUE),
        (NumericTest.none_at_all(), 1, ConditionResult.FALSE),
        (NumericTest.at_least(2), 1, ConditionResult.FALSE),
        (NumericTest.at_least(2), 2, ConditionResult.TRUE),
        (NumericTest.at_most(2), 3, ConditionResult.FALSE),
    ],
)
def test_a_a_numeric_test_answers_only_about_the_number(test, value, expected):
    assert test.test(value) is expected


def test_a_only_two_comparisons_exist():
    """
    §3 — 실제 카드가 쓰는 것만 만들었다. 97곳 중 **91곳이 0 과
    견준다**: ``>0`` 57 · ``==0`` 26 · ``~=0`` 8.

    장수는 음수가 될 수 없으므로 ``>0`` · ``~=0`` · ``>=1`` 은 같은
    질문이고, ``==0`` · ``<=0`` 도 같은 질문이다.
    """
    assert [c.value for c in Comparison] == ["at_least", "at_most"]
    assert NumericTest.any_at_all() == NumericTest.at_least(1)
    assert NumericTest.none_at_all() == NumericTest.at_most(0)


def test_a_a_numeric_test_never_looks_for_a_value():
    """
    §2 — 값을 구하는 일과 견주는 일은 다르다. 이 타입은 **판도 실행
    문맥도 모른다.**
    """
    tree = ast.parse((ROOT / "engine" / "execution.py").read_text("utf-8"))
    (node,) = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "NumericTest"
    ]
    body = ast.unparse(node)

    for forbidden in ("ExecutionValues", "GameState", "resolve(", "ResultRef"):
        assert forbidden not in body, forbidden


def test_a_a_negative_operand_is_refused():
    with pytest.raises(ValueError, match="0 이상"):
        NumericTest.at_least(-1)


# ======================================================================
# B · C. 참이면 한다 · 거짓이면 건너뛴다 (§8 · §9)
# ======================================================================


def test_b_the_next_operation_runs_when_the_number_satisfies_the_test(state):
    """
    ``if ct>0 then <다음 일> end`` — 실제 카드 66곳의 모양이다.
    """
    field = monsters(state)
    before = len(state.player(P1).hand)

    result = run(
        state,
        destroy_then_draw((NumericTest.any_at_all(),)),
        Ruling({field[0]: ConditionResult.FALSE}),
        field,
    )

    assert result.status is ResolutionStatus.RESOLVED
    destroyed, drew = result.applied
    assert len(destroyed.instances) == 2
    assert drew.amount == 1
    assert len(state.player(P1).hand) == before + 1


def test_c_the_next_operation_is_skipped_when_the_test_fails(state):
    """
    **건너뛴 것은 실패가 아니다.** 효과는 정상적으로 해결되고, 앞의 일은
    그대로 남는다.
    """
    field = monsters(state)
    before = len(state.player(P1).hand)
    journal = EventJournal()

    result = run(
        state,
        destroy_then_draw((NumericTest.at_least(4),)),
        Ruling(),
        field,
        journal,
    )

    assert result.status is ResolutionStatus.RESOLVED
    (destroyed,) = result.applied  # 뽑기는 기록에 없다
    assert len(destroyed.instances) == 3
    assert len(state.player(P1).hand) == before  # 뽑지 않았다
    assert monsters(state) == []  # 파괴는 그대로 일어났다
    assert len(journal) == 1


def test_c_none_at_all_expresses_the_other_corpus_shape(state):
    """
    ``if ct==0 then return end`` — 27곳의 모양이다. 뒤의 일마다
    "하나라도 됐어야 한다" 를 걸면 같은 뜻이 된다.
    """
    field = monsters(state)
    before = len(state.player(P1).hand)

    result = run(
        state,
        destroy_then_draw((NumericTest.none_at_all(),)),
        Ruling({field[0]: ConditionResult.FALSE}),
        field,
    )

    # 둘이 파괴됐으므로 "하나도 안 됐는가" 는 거짓 — 뽑지 않는다.
    assert result.status is ResolutionStatus.RESOLVED
    assert len(state.player(P1).hand) == before


def test_c_several_tests_must_all_hold(state):
    """
    §5 — 불 대수를 새로 만들지 않았다. **정확히 N** 은 두 조건을 함께
    거는 것으로 적는다.
    """
    field = monsters(state)
    before = len(state.player(P1).hand)

    exact = run(
        state,
        destroy_then_draw((NumericTest.at_least(3), NumericTest.at_most(3))),
        Ruling(),
        field,
    )

    assert exact.status is ResolutionStatus.RESOLVED
    assert len(exact.applied) == 2
    assert len(state.player(P1).hand) == before + 1


def test_c_a_guard_without_a_test_is_refused():
    with pytest.raises(ValueError, match="조건 없는 조건문"):
        OperationGuard(1, SelectionCount.from_result(AFFECTED), ())


# ======================================================================
# D · E. 모르면 건너뛰지 않는다 (§6 · §7)
# ======================================================================


def test_d_an_unknown_value_refuses_the_whole_effect(state):
    """
    §6 · §7 — **``UNKNOWN`` 을 ``FALSE`` 로 바꾸지 않는다.**

    건너뛰는 것도 결정이다. 모르는 채로 건너뛰면 그 일을 했어야 하는지
    안 했어야 하는지를 엔진이 지어낸 것이 된다.
    """
    field = monsters(state)
    before, journal = state.state_hash(), EventJournal()
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 1),
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
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert result.missing == "아직 없는 계층"
    untouched(state, before, field, result, journal)


def test_d_an_unresolved_reference_is_unknown_not_false(state):
    """
    건너뛴 일의 수를 **뒤에서 읽으려 하면** 모른다. 0 이 아니다.
    """
    values = ExecutionValues().with_result(
        OperationResult(0, outcome=OperationOutcome.NOT_APPLIED)
    )

    assert values.outcome_of(0) is OperationOutcome.NOT_APPLIED
    with pytest.raises(ExecutionLookupError):
        values.result(AFFECTED)


def test_e_a_value_failure_is_not_a_condition_failure(state):
    """
    §7 — 두 단계의 ``UNKNOWN`` 을 구분한다. 어느 쪽이든 멈추지만
    **다른 것을 고쳐야 한다.**
    """
    field = monsters(state)
    before = state.state_hash()
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 2),
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

    # 선언하지 않았다 — 조건이 거짓인 것이 아니라 **아직 정해지지 않았다.**
    result = run(state, definition)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    untouched(state, before, field, result)


# ======================================================================
# F · G. 건너뛴 자리 (§9)
# ======================================================================


def test_f_a_skipped_operation_keeps_its_place(state):
    """
    번호는 밀리지 않는다 — 뒤의 일이 **번호로** 앞을 가리키기 때문이다.
    건너뛴 자리에는 "하지 않았다" 가 들어간다.
    """
    field = monsters(state)
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 3),
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
                operation=OperationKind.DESTROY, target_ref=PRIMARY_TARGET
            ),
            DrawOperation(count=1),
            # 2번은 0번을 본다 — 건너뛴 1번 때문에 번호가 밀리지 않는다.
            DrawOperation(count=SelectionCount.from_result(AFFECTED)),
        ),
        guards=(
            OperationGuard(
                1, SelectionCount.from_result(AFFECTED), (NumericTest.at_least(9),)
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )
    before = len(state.player(P1).hand)

    result = run(state, definition, Ruling(), field)

    assert result.status is ResolutionStatus.RESOLVED
    destroyed, drew = result.applied  # 1번은 없다
    assert len(destroyed.instances) == 3
    assert drew.amount == 3  # 2번이 0번의 수를 그대로 읽었다
    assert len(state.player(P1).hand) == before + 3


def test_g_a_skipped_operation_has_no_counts():
    """
    **0장을 다룬 것과 하지 않은 것은 다른 사실이다.**
    """
    skipped = OperationResult(0, outcome=OperationOutcome.NOT_APPLIED)
    did_nothing = OperationResult(0, affected_count=0, attempted_count=3)

    assert skipped.was_applied is False
    assert skipped.affected_count is None
    assert skipped.did_nothing is False  # 하려고 한 적이 없다

    assert did_nothing.was_applied is True
    assert did_nothing.did_nothing is True


# ======================================================================
# H · I. 값의 출처 · 명시적 참조 (§4)
# ======================================================================


def test_h_every_value_source_can_feed_a_condition(state):
    """
    §4 — 상수 · 선언한 수 · 앞선 결과 · 판에서 계산 · 모름. 다섯 다
    조건의 입력이 된다.
    """
    from engine.effect.target import CountKind

    sources = (
        SelectionCount.fixed(2),
        SelectionCount.from_declaration(DECLARED_NUMBER),
        SelectionCount.from_result(AFFECTED),
        SelectionCount.derived((ZoneCountTerm(PlayerRef.CONTROLLER, Zone.HAND, 1),)),
        SelectionCount.unknown("아직 없는 계층"),
    )

    assert {source.kind for source in sources} == set(CountKind)
    for source in sources:
        guard = OperationGuard(1, source, (NumericTest.any_at_all(),))
        assert guard.value is source


def test_h_a_board_value_is_read_when_the_plan_is_made(repository):
    """
    **판을 읽는 조건은 계획 시점의 판을 본다.**

    계획이 전부 끝난 뒤에야 적용이 시작되므로(2-V), 같은 효과 안에서
    앞의 일이 판을 바꾼 결과는 뒤의 조건에 **보이지 않는다.** 앞의 일이
    한 것을 보려면 판이 아니라 **결과**를 가리켜야 한다
    (``SelectionCount.from_result``).

    이것을 감추지 않는다 — 여기 적어 두고 STRUCTURAL-94 로 남긴다.
    """
    state = new_state(repository)
    before = len(state.player(P1).hand)
    assert before == 0

    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 4),
        source_card_id=LAB,
        operations=(DrawOperation(count=2), DrawOperation(count=1)),
        guards=(
            OperationGuard(
                1,
                SelectionCount.derived(
                    (ZoneCountTerm(PlayerRef.CONTROLLER, Zone.HAND, 1),)
                ),
                (NumericTest.at_least(3),),
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(state, definition)

    # 0번이 2장을 뽑지만, 조건은 **계획 시점의 패(0장)**를 본다. 3장
    # 이상이 아니므로 1번은 건너뛴다. 판은 뽑은 뒤 2장이 된다.
    assert result.status is ResolutionStatus.RESOLVED
    assert len(result.applied) == 1
    assert len(state.player(P1).hand) == 2

    # 앞의 일이 한 것을 보려면 **결과**를 가리켜야 한다.
    by_result = EffectDefinition(
        effect_ref=EffectRef(LAB, 9),
        source_card_id=LAB,
        operations=(DrawOperation(count=2), DrawOperation(count=1)),
        guards=(
            OperationGuard(
                1, SelectionCount.from_result(AFFECTED), (NumericTest.at_least(2),)
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )
    again = new_state(repository)
    assert run(again, by_result).status is ResolutionStatus.RESOLVED
    assert len(again.player(P1).hand) == 3


def test_i_a_condition_may_only_look_backwards():
    """§4 — "마지막 count" 같은 암묵적 참조는 없다."""
    for index in (1, 2):
        with pytest.raises(EffectDefinitionError, match="앞선 일만"):
            EffectDefinition(
                effect_ref=EffectRef(LAB, 5),
                source_card_id=LAB,
                operations=(DrawOperation(1), DrawOperation(1)),
                guards=(
                    OperationGuard(
                        1,
                        SelectionCount.from_result(ResultRef(index)),
                        (NumericTest.any_at_all(),),
                    ),
                ),
                provenance=EffectProvenance.hand_written(verified=True),
            )

    with pytest.raises(EffectDefinitionError, match="없습니다"):
        EffectDefinition(
            effect_ref=EffectRef(LAB, 5),
            source_card_id=LAB,
            operations=(DrawOperation(1),),
            guards=(
                OperationGuard(
                    7, SelectionCount.fixed(1), (NumericTest.any_at_all(),)
                ),
            ),
            provenance=EffectProvenance.hand_written(verified=True),
        )


def test_i_the_executor_never_reaches_for_the_last_result():
    executor = (ROOT / "engine" / "effect" / "executor.py").read_text("utf-8")

    assert "results[-1]" not in executor
    assert "last_result" not in executor


# ======================================================================
# J. 건너뛰기와 거절은 다른 것이다 (2-AE 와의 관계)
# ======================================================================


def test_j_a_guard_and_a_requirement_do_different_things(state):
    """
    ==========================  ==========================================
    ``OperationRequirement``     앞이 **규칙대로 되었는가** — 아니면 거절
    ``OperationGuard``           앞의 **수가 조건을 만족하는가** — 아니면 건너뜀
    ==========================  ==========================================

    2-AE 가 성패를 수로 읽는 길을 막아 둔 것은 지금도 유효하다.
    """
    with pytest.raises(ValueError, match="성패뿐"):
        OperationRequirement(1, ResultRef(0, ResultField.AFFECTED_COUNT))

    # 조건은 수를 **수로** 읽고, 견주는 방법을 명시적으로 적는다.
    guard = OperationGuard(1, SelectionCount.from_result(AFFECTED), (NumericTest.any_at_all(),))
    assert guard.tests[0].comparison is Comparison.AT_LEAST


def test_j_a_requirement_still_refuses_instead_of_skipping(state):
    """
    성패가 ``UNKNOWN`` 이면 여전히 **거절**이다. 건너뛰기로 바뀌지
    않았다.
    """
    field = monsters(state)
    before = state.state_hash()
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 6),
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
                operation=OperationKind.DESTROY, target_ref=PRIMARY_TARGET
            ),
            DrawOperation(count=1),
        ),
        requirements=(
            OperationRequirement(1, ResultRef(0, ResultField.SUCCEEDED)),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(state, definition, Ruling(), field)

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    untouched(state, before, field, result)


# ======================================================================
# K ~ P. 결정론 · 복제 · 안전 · 정보 · 저널 · 해시
# ======================================================================


def test_k_the_same_board_makes_the_same_decision(repository):
    outcomes = set()
    for _ in range(3):
        game = new_state(repository, seed=5)
        field = monsters(game)
        result = run(
            game,
            destroy_then_draw((NumericTest.at_least(3),)),
            Ruling({field[0]: ConditionResult.FALSE}),
            field,
        )
        outcomes.add((len(result.applied), len(game.player(P1).hand)))
    assert len(outcomes) == 1


def test_l_a_clone_decides_for_itself(repository):
    original = new_state(repository, seed=8)
    copy = original.clone()
    field = monsters(copy)

    run(copy, destroy_then_draw((NumericTest.any_at_all(),)), Ruling(), field)

    assert len(monsters(original)) == 3
    assert len(original.player(P1).hand) == 0
    assert len(copy.player(P1).hand) == 1


def test_m_a_failure_after_a_skip_still_changes_nothing(state):
    """건너뛴 뒤에 다른 일이 막혀도 판은 그대로다."""
    field = monsters(state)
    before, journal = state.state_hash(), EventJournal()
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 7),
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
                operation=OperationKind.DESTROY, target_ref=PRIMARY_TARGET
            ),
            DrawOperation(count=1),
            DrawOperation(count=99),
        ),
        guards=(
            OperationGuard(
                1, SelectionCount.from_result(AFFECTED), (NumericTest.at_least(9),)
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(state, definition, Ruling(), field, journal)

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    untouched(state, before, field, result, journal)


def test_n_a_decision_never_reveals_a_hidden_card(repository):
    """
    조건이 **상대 패의 장수**를 보아도 그 패의 정체는 열리지 않는다.
    """
    state = new_state(repository)
    state.draw(P2, 4)
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 8),
        source_card_id=LAB,
        operations=(DrawOperation(count=1),),
        guards=(
            OperationGuard(
                0,
                SelectionCount.derived(
                    (ZoneCountTerm(PlayerRef.OPPONENT, Zone.HAND, 1),)
                ),
                (NumericTest.at_least(4),),
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(state, definition)

    assert result.status is ResolutionStatus.RESOLVED
    view = GameStateView.from_state(state, viewer=P1)
    assert view.player(P2).zone(Zone.HAND).concealed is True
    assert view.player(P2).zone(Zone.HAND).cards == ()
    hidden = [card.card_id for card in state.player(P2).hand]
    rendered = repr(result.to_dict())
    for card_id in hidden:
        assert str(card_id) not in rendered


def test_o_the_journal_records_what_happened_not_what_was_decided(state):
    field = monsters(state)
    journal = EventJournal()

    run(
        state,
        destroy_then_draw((NumericTest.at_least(9),)),
        Ruling(),
        field,
        journal,
    )

    assert len(journal) == 1
    rendered = repr(journal.to_dict() if hasattr(journal, "to_dict") else list(journal))
    for word in ("guard", "skipped", "not_applied", "at_least"):
        assert word not in rendered


def test_p_decisions_stay_out_of_the_hash(repository):
    left, right = new_state(repository, seed=2), new_state(repository, seed=2)
    assert left.state_hash() == right.state_hash()

    NumericTest.any_at_all().test(3)
    ExecutionValues().with_result(
        OperationResult(0, outcome=OperationOutcome.NOT_APPLIED)
    )

    assert left.state_hash() == right.state_hash()
    rendered = repr(left.canonical_state())
    for word in ("guard", "not_applied", "at_least"):
        assert word not in rendered


# ======================================================================
# Q. 실제 corpus 대표 사례 (§8)
# ======================================================================


def test_q_the_two_corpus_shapes_are_both_expressible():
    """
    실제 카드가 조작의 결과를 조건으로 쓰는 자리 97곳.

    ==========  ===  ==========================================
    ``> 0``      57   하나라도 됐는가
    ``== 0``     26   하나도 안 됐는가
    ``~= 0``      8   하나라도 됐는가
    ``> 1``       2   둘 이상인가
    ``<= 0``      1   하나도 안 됐는가
    ``>= 2``      1   둘 이상인가
    ``>= 1``      1   하나라도 됐는가
    ``== <변수>`` 1   **전부** 됐는가 — 값끼리 견준다 (범위 밖)
    ==========  ===  ==========================================

    96곳이 :meth:`NumericTest.at_least` 와 :meth:`NumericTest.at_most`
    로 적힌다. 나머지 한 곳은 상수가 아니라 **다른 값**과 견주므로
    이번 범위 밖이다 (STRUCTURAL-93).
    """
    at_least_zero_ish = (NumericTest.any_at_all(), NumericTest.at_least(2))
    at_most_zero_ish = (NumericTest.none_at_all(),)

    for test in at_least_zero_ish:
        assert test.comparison is Comparison.AT_LEAST
    for test in at_most_zero_ish:
        assert test.comparison is Comparison.AT_MOST


def test_q_a_value_to_value_comparison_is_not_supported_yet():
    """
    ``if dc==ct then`` (59490397) — 파괴한 수와 대상 수가 **같은가**.

    지금은 :class:`NumericTest` 의 오른쪽이 상수뿐이다. 1곳이므로
    억지로 넓히지 않았다 — 그리고 넓히면 "어느 값이 왼쪽인가" 가 새
    문제로 생긴다.

    그래도 **이 한 곳이 묻는 것**은 이미 적을 수 있다: 시도한 수와
    처리한 수가 같은지는 ``OperationResult.is_complete`` 가 답한다.
    """
    complete = OperationResult(0, affected_count=3, attempted_count=3)
    partial = OperationResult(0, affected_count=2, attempted_count=3)

    assert complete.is_complete and not partial.is_complete
    # 오른쪽은 여전히 상수뿐이다.
    assert isinstance(NumericTest.at_least(2).operand, int)


def test_q_no_real_card_was_registered_this_phase():
    """
    **0장 등재했다.** 조건을 적을 수 있게 됐지만, 그 조건이 보는 수를
    내는 일(파괴)은 여전히 판정기가 없어 일어나지 않는다 (ADR-006).
    """
    from engine.effect.library import EFFECT_LIBRARY

    assert len(EFFECT_LIBRARY) == 15
    for entry in EFFECT_LIBRARY:
        assert entry.definition.guards == ()
