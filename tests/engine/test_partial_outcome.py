"""
Phase 2-AF — 일부만 되는 일, 그리고 값이 되는지 보는 일.

    Operation
      → OperationResult
          ├── outcome           규칙대로 되었는가   (2-AE)
          ├── attempted_count   **하려고 한** 수    ← 이번
          └── affected_count    실제로 한 수
      → ResultRef → 후속 Operation

    SelectionCount  (값을 정한다)
      → ValueDomain (그 값이 되는지 본다)           ← 이번
      → Operation

일부만 되는 것은 실패가 아니다
------------------------------
공식 텍스트 **203장**이 "as many … as possible" 을 자기 텍스트에 적어
두었다. 적어 두지 않은 카드는 이 길을 타지 않는다 — "하나라도 못 하면
전부 안 한다" 도, "되는 것만 한다" 도 엔진이 정할 일이 아니다.

모르는 것은 건너뛰지 않는다
---------------------------
규칙이 "안 된다" 고 답한 것과 "모르겠다" 는 다른 사실이다. 모르는 것을
건너뛰면 그 카드가 처리됐어야 하는지를 엔진이 멋대로 정하게 된다.

값과 도메인은 다른 것이다
-------------------------
``SelectionCount`` 는 "몇 개인가" 에 답하고 ``ValueDomain`` 은 "그 수가
되는가" 에 답한다. ``NumberDomain`` (고를 수 있는 수들)과도 다르다 —
저쪽은 고르기 **전**, 이쪽은 값이 나온 **뒤**다.
"""

import ast
import dataclasses
import pathlib

import pytest

from engine.condition import ConditionResult, PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, CostGroup, Selection
from engine.effect.definition import EffectDefinition, EffectProvenance
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
)
from engine.execution import (
    DECLARED_NUMBER,
    BoardQuantity,
    DomainVerdict,
    ExecutionValues,
    NumberDomain,
    OperationOutcome,
    OperationResult,
    QuantitySource,
    ResultField,
    ResultRef,
    ValueDomain,
    ValueDomainKind,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
P1, P2 = 0, 1
LAB = 999_008

MINE = [70368879, 15103313, 55144522]
FILLER = 21844576
LIFE = BoardQuantity(QuantitySource.LIFE_POINTS, PlayerRef.CONTROLLER)


class Ruling:
    """카드마다 답을 정해 주는 파괴 판정기. **시험용 판정기다.**"""

    __slots__ = ("answers", "default")

    def __init__(self, answers=None, default=ConditionResult.TRUE):
        self.answers = dict(answers or {})
        self.default = default

    def may_be_destroyed(self, instance: InstanceId) -> ConditionResult:
        return self.answers.get(instance, self.default)



def _is_docstring(node) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def new_state(repository, seed: int | None = 7) -> GameState:
    """P1 필드에 몬스터 3장."""
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


def destroy_all(partial=Partial.ALL_OR_NOTHING, ordinal=0) -> EffectDefinition:
    """자신 필드의 몬스터를 최대 3장까지 고르고 파괴한다."""
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
                partial=partial,
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True, note="Phase 2-AF"),
    )


def run(game, definition, ruling=None, chosen=None, journal=None):
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
            effect_ref=definition.effect_ref, controller=P1, selections=selections
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
# A · B · C. 전부 · 일부 · 하나도 (§32 A · B · C · §4 · §8)
# ======================================================================


def test_a_every_target_goes_when_the_rules_allow_it(state):
    field = monsters(state)

    result = run(state, destroy_all(), Ruling(), field)

    assert result.status is ResolutionStatus.RESOLVED
    (applied,) = result.applied
    assert len(applied.instances) == 3
    assert monsters(state) == []


def test_b_a_card_that_says_as_many_as_possible_does_what_it_can(state):
    """
    §4 — 셋 중 하나를 규칙이 막았다. **나머지 둘은 된다.**

    공식 텍스트 203장이 이것을 자기 텍스트에 적어 두었다
    ("destroy as many other cards on the field as possible").
    """
    field = monsters(state)
    protected = field[1]

    result = run(
        state,
        destroy_all(Partial.AS_MANY_AS_POSSIBLE),
        Ruling({protected: ConditionResult.FALSE}),
        field,
    )

    assert result.status is ResolutionStatus.RESOLVED
    (applied,) = result.applied
    assert len(applied.instances) == 2
    assert protected not in applied.instances
    assert monsters(state) == [protected]


def test_b_a_card_that_does_not_say_so_does_nothing(state):
    """
    **기본은 전부 아니면 무**이고, 그것이 일반 규칙이라서가 아니라
    카드가 아무 말도 하지 않았기 때문이다.
    """
    field = monsters(state)
    before, journal = state.state_hash(), EventJournal()

    result = run(
        state,
        destroy_all(Partial.ALL_OR_NOTHING),
        Ruling({field[1]: ConditionResult.FALSE}),
        field,
        journal,
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    untouched(state, before, field, result, journal)


def test_c_when_the_rules_block_everything_nothing_happens(state):
    """
    "가능한 만큼" 이라고 적혀 있어도 **가능한 것이 없으면** 일어난 일이
    없다.
    """
    field = monsters(state)
    before, journal = state.state_hash(), EventJournal()

    result = run(
        state,
        destroy_all(Partial.AS_MANY_AS_POSSIBLE),
        Ruling(default=ConditionResult.FALSE),
        field,
        journal,
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    untouched(state, before, field, result, journal)


# ======================================================================
# D. 모르는 것은 건너뛰지 않는다 (§32 D · §7)
# ======================================================================


@pytest.mark.parametrize(
    "partial", [Partial.ALL_OR_NOTHING, Partial.AS_MANY_AS_POSSIBLE]
)
def test_d_an_unknown_target_is_never_skipped(state, partial):
    """
    §7 — ``TARGET FAILED ≠ TARGET UNKNOWN``.

    "안 된다" 는 규칙의 답이고 "모르겠다" 는 규칙이 없다는 뜻이다. 뒤엣
    것을 건너뛰면 그 카드가 처리됐어야 하는지를 **엔진이 정하는 것**이
    된다.
    """
    field = monsters(state)
    before, journal = state.state_hash(), EventJournal()

    result = run(
        state,
        destroy_all(partial),
        Ruling({field[1]: ConditionResult.UNKNOWN}),
        field,
        journal,
    )

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    untouched(state, before, field, result, journal)


def test_d_skipping_needs_both_a_declaration_and_a_refusal():
    """코드에서도 그렇다 — 둘이 **동시에** 참일 때만 건너뛴다."""
    tree = ast.parse((ROOT / "engine" / "effect" / "executor.py").read_text("utf-8"))
    (skip,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_may_skip"
    ]
    # **설명이 아니라 코드를 본다.** docstring 은 `UNCHECKED_RULES` 를
    # 왜 건너뛰지 않는지 설명하므로, 문자열로 찾으면 그 설명이 걸린다.
    body = ast.unparse(
        ast.Module(
            body=[n for n in skip.body if not _is_docstring(n)], type_ignores=[]
        )
    )

    assert "AS_MANY_AS_POSSIBLE" in body
    assert "INVALID_TARGET" in body
    assert "UNCHECKED_RULES" not in body


# ======================================================================
# E · F · G. 시도한 수와 처리한 수 (§32 E · F · G · §9)
# ======================================================================


def test_e_the_result_says_both_how_many_were_tried_and_how_many_went(state):
    """
    §9 — 실패한 수를 **따로 저장하지 않는다.** 그것은 이 둘의 차이다.
    """
    field = monsters(state)

    result = run(
        state,
        destroy_all(Partial.AS_MANY_AS_POSSIBLE),
        Ruling({field[1]: ConditionResult.FALSE}),
        field,
    )

    assert result.status is ResolutionStatus.RESOLVED
    record = OperationResult(0, affected_count=2, attempted_count=3)
    assert record.is_partial and not record.is_complete and not record.did_nothing
    assert not hasattr(record, "failed_count")


@pytest.mark.parametrize(
    "attempted,affected,complete,partial,nothing",
    [
        (3, 3, True, False, False),
        (3, 2, False, True, False),
        (3, 0, False, False, True),
        (0, 0, True, False, False),  # 하려던 것이 없으면 다 한 것이다
    ],
)
def test_f_the_three_questions_are_answered_separately(
    attempted, affected, complete, partial, nothing
):
    record = OperationResult(0, affected_count=affected, attempted_count=attempted)

    assert record.is_complete is complete
    assert record.is_partial is partial
    assert record.did_nothing is nothing


def test_f_partial_is_not_failure(state):
    """
    §34 — 일부만 된 것을 **실패로 바꾸지 않는다.** 그리고 성패는 장수와
    독립이다 (2-AE).
    """
    field = monsters(state)

    result = run(
        state,
        destroy_all(Partial.AS_MANY_AS_POSSIBLE),
        Ruling({field[1]: ConditionResult.FALSE}),
        field,
    )

    assert result.status is ResolutionStatus.RESOLVED
    # 파괴는 못 본 규칙이 있는 의미다 — 장수와 무관하게 UNKNOWN 이다.
    assert result.unchecked_rules


def test_g_a_later_operation_may_read_either_count(state):
    """
    §10 — 명시적으로 가리킨다. "마지막 결과" 는 없다.
    """
    values = ExecutionValues().with_result(
        OperationResult(0, affected_count=2, attempted_count=3)
    )

    assert values.result(ResultRef(0, ResultField.AFFECTED_COUNT)) == 2
    assert values.result(ResultRef(0, ResultField.ATTEMPTED_COUNT)) == 3


def test_g_an_operation_without_counts_answers_neither():
    """
    라이프 증감에는 장수가 없다. **없는 것을 0 으로 답하지 않는다.**
    """
    from engine.execution import ExecutionLookupError

    values = ExecutionValues().with_result(OperationResult(0))

    for field in (ResultField.AFFECTED_COUNT, ResultField.ATTEMPTED_COUNT):
        with pytest.raises(ExecutionLookupError):
            values.result(ResultRef(0, field))


# ======================================================================
# H · I · J · K. 값이 되는가 (§32 H · I · J · K · §12 · §14 · §15)
# ======================================================================


def test_h_a_value_inside_the_domain_is_valid():
    verdict = ValueDomain.bounded_by(LIFE, step=1000).validate(3, lambda q: 8000)

    assert verdict.validity is ActionValidity.VALID
    assert isinstance(verdict, DomainVerdict)


def test_i_a_value_outside_the_domain_is_invalid():
    verdict = ValueDomain.bounded_by(LIFE, step=1000).validate(9, lambda q: 8000)

    assert verdict.validity is ActionValidity.INVALID
    assert "8000" in verdict.reason


def test_j_a_domain_we_cannot_judge_is_unknown():
    """
    §15 — **값은 있는데 허용 범위를 모른다.** 값을 못 구한 것과 다르다.
    """
    verdict = ValueDomain.unresolved("수를 인자로 받는 조건").validate(3)

    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing
    with pytest.raises(TypeError):
        bool(verdict)


def test_j_a_bounded_domain_without_a_board_is_unknown_not_valid():
    """판을 못 봤다는 사실을 **통과로 덮지 않는다.**"""
    assert ValueDomain.bounded_by(LIFE).validate(3).validity is ActionValidity.UNKNOWN
    assert (
        ValueDomain.bounded_by(LIFE).validate(3, lambda q: None).validity
        is ActionValidity.UNKNOWN
    )


def test_k_a_value_we_cannot_compute_is_a_different_failure(state):
    """
    §15 — ``VALUE UNKNOWN ≠ DOMAIN UNKNOWN``. 둘 다 멈추지만 **다른
    이유**로 멈추고, 그래서 다른 것을 고쳐야 한다.
    """
    before, field = state.state_hash(), monsters(state)

    value_unknown = run(
        state,
        EffectDefinition(
            effect_ref=EffectRef(LAB, 1),
            source_card_id=LAB,
            operations=(DrawOperation(count=SelectionCount.unknown("없는 계층")),),
            cost=CostGroup(),
            provenance=EffectProvenance.hand_written(verified=True),
        ),
    )
    domain_unknown = run(
        state,
        EffectDefinition(
            effect_ref=EffectRef(LAB, 2),
            source_card_id=LAB,
            operations=(
                DrawOperation(
                    count=dataclasses.replace(
                        SelectionCount.fixed(1),
                        domain=ValueDomain.unresolved("수를 인자로 받는 조건"),
                    )
                ),
            ),
            cost=CostGroup(),
            provenance=EffectProvenance.hand_written(verified=True),
        ),
    )

    assert value_unknown.missing == "없는 계층"
    assert domain_unknown.missing == "수를 인자로 받는 조건"
    untouched(state, before, field, value_unknown)
    untouched(state, before, field, domain_unknown)


@pytest.mark.parametrize(
    "value,expected",
    [(3, ResolutionStatus.RESOLVED), (9, ResolutionStatus.INVALID_OPERATION)],
)
def test_domain_validation_runs_inside_a_real_execution(
    repository, value, expected
):
    state = new_state(repository)
    before, field = state.state_hash(), monsters(state)
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 3),
        source_card_id=LAB,
        operations=(
            DrawOperation(
                count=dataclasses.replace(
                    SelectionCount.fixed(value),
                    domain=ValueDomain.bounded_by(LIFE, step=1000),
                )
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(state, definition)

    assert result.status is expected
    if expected is not ResolutionStatus.RESOLVED:
        assert result.code is ValidationCode.INVALID_AMOUNT
        untouched(state, before, field, result)


# ======================================================================
# L · M. 세 도메인을 섞지 않는다 (§32 L · M · §17 · §18)
# ======================================================================


def test_l_a_choice_domain_and_a_value_domain_are_different_types():
    """
    §18 — 고를 수 있는 수들과, 이미 정해진 값이 되는지 보는 규칙.
    **앞은 고르기 전, 뒤는 값이 나온 뒤**다.
    """
    choice = NumberDomain.between(1, 3)
    value = ValueDomain.bounded_by(LIFE, step=1000)

    assert not isinstance(choice, ValueDomain)
    assert not isinstance(value, NumberDomain)
    assert not hasattr(choice, "validate")
    assert not hasattr(value, "allows")


def test_m_a_count_and_a_domain_are_different_types():
    """
    §17 — ``SelectionCount`` 는 "몇 개인가", ``ValueDomain`` 은 "그 수가
    되는가". 한 칸으로 이어져 있을 뿐 같은 것이 아니다.
    """
    count = dataclasses.replace(
        SelectionCount.fixed(2), domain=ValueDomain.at_least_one()
    )

    assert not isinstance(count.domain, SelectionCount)
    assert not hasattr(count, "validate")
    # 도메인을 적지 않은 것은 "무엇이든 된다" 가 아니라 **안 봤다** 는 뜻이다.
    assert SelectionCount.fixed(2).domain is None


def test_m_a_domain_of_the_wrong_shape_is_refused():
    with pytest.raises(ValueError, match="무엇을 넘지 않아야"):
        ValueDomain(ValueDomainKind.BOUNDED)
    with pytest.raises(ValueError, match="한계가 붙지 않습니다"):
        ValueDomain(ValueDomainKind.AT_LEAST_ONE, bound=LIFE)
    with pytest.raises(ValueError, match="무엇이 없어서"):
        ValueDomain(ValueDomainKind.RULE_UNRESOLVED)


# ======================================================================
# N. 일부 결과가 다음 값이 된다 (§32 N · §19)
# ======================================================================


def test_n_a_partial_count_flows_into_the_next_operation(repository):
    """
    §19 — 셋 중 둘만 파괴됐으면 다음 일은 **둘**이다. 셋이 아니다.
    """
    state = new_state(repository)
    field = monsters(state)
    before = len(state.player(P1).hand)
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 4),
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
            DrawOperation(
                count=dataclasses.replace(
                    SelectionCount.from_result(ResultRef(0)),
                    domain=ValueDomain.at_least_one(),
                )
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(
        state, definition, Ruling({field[1]: ConditionResult.FALSE}), field
    )

    assert result.status is ResolutionStatus.RESOLVED
    destroyed, drew = result.applied
    assert len(destroyed.instances) == 2
    assert drew.amount == 2
    assert len(state.player(P1).hand) == before + 2


def test_n_the_attempted_count_is_a_different_number(repository):
    """같은 일에서 **시도는 3, 처리는 2** 다."""
    state = new_state(repository)
    field = monsters(state)
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 5),
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
            DrawOperation(
                count=SelectionCount.from_result(
                    ResultRef(0, ResultField.ATTEMPTED_COUNT)
                )
            ),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(
        state, definition, Ruling({field[1]: ConditionResult.FALSE}), field
    )

    assert len(result.applied[0].instances) == 2
    assert result.applied[1].amount == 3


# ======================================================================
# O ~ T. 정보 · 결정론 · 복제 · 안전 · 저널 · 해시 (§32 O ~ T)
# ======================================================================


def test_o_a_refused_target_never_reaches_the_observation(state):
    """
    §29 — 규칙이 막은 카드의 **정체**가 결과로 새지 않는다. 남은 것은
    판에서 보면 알 수 있지만, 그것은 관측 계층의 일이다.
    """
    field = monsters(state)
    protected = field[1]

    result = run(
        state,
        destroy_all(Partial.AS_MANY_AS_POSSIBLE),
        Ruling({protected: ConditionResult.FALSE}),
        field,
    )

    rendered = repr(result.to_dict()) + (result.reason or "")
    card_id = state.find_instance(protected).card_id
    assert str(card_id) not in rendered


def test_o_the_value_layer_still_knows_nothing_about_observation():
    tree = ast.parse((ROOT / "engine" / "execution.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "engine.game_state_view" not in imported
    assert "engine.state.game_state" not in imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"GameState", "GameStateView", "ObservationPolicy"}


def test_p_the_same_board_gives_the_same_partial_result(repository):
    """§25 — 대상 순서가 흔들리지 않으므로 결과도 흔들리지 않는다."""
    seen = set()
    for _ in range(3):
        game = new_state(repository, seed=4)
        field = monsters(game)
        result = run(
            game,
            destroy_all(Partial.AS_MANY_AS_POSSIBLE),
            Ruling({field[1]: ConditionResult.FALSE}),
            field,
        )
        seen.add(tuple(monsters(game)))
        assert len(result.applied[0].instances) == 2
    assert len(seen) == 1


def test_q_a_clone_keeps_its_own_results(repository):
    original = new_state(repository, seed=9)
    copy = original.clone()
    field = monsters(copy)

    run(
        copy,
        destroy_all(Partial.AS_MANY_AS_POSSIBLE),
        Ruling({field[1]: ConditionResult.FALSE}),
        field,
    )

    assert len(monsters(original)) == 3
    assert len(monsters(copy)) == 1
    assert not hasattr(original, "results")


def test_r_a_failure_after_a_partial_step_still_changes_nothing(repository):
    """
    §24 — 일부는 할 수 있었지만 **뒤가 막혔다.** 계획이 전부 끝난 뒤에야
    적용이 시작되므로 반쯤 바뀐 판은 없다.
    """
    state = new_state(repository)
    field = monsters(state)
    before, journal = state.state_hash(), EventJournal()
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
                operation=OperationKind.DESTROY,
                target_ref=PRIMARY_TARGET,
                partial=Partial.AS_MANY_AS_POSSIBLE,
            ),
            DrawOperation(count=99),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(
        state, definition, Ruling({field[1]: ConditionResult.FALSE}), field, journal
    )

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    untouched(state, before, field, result, journal)


def test_s_the_journal_records_what_happened_not_what_was_tried(state):
    field = monsters(state)
    journal = EventJournal()

    run(
        state,
        destroy_all(Partial.AS_MANY_AS_POSSIBLE),
        Ruling({field[1]: ConditionResult.FALSE}),
        field,
        journal,
    )

    assert len(journal) == 1
    rendered = repr(journal.to_dict() if hasattr(journal, "to_dict") else list(journal))
    for word in ("attempted", "refused", "partial", "domain"):
        assert word not in rendered


def test_t_none_of_this_reaches_the_hash(repository):
    left, right = new_state(repository, seed=3), new_state(repository, seed=3)
    assert left.state_hash() == right.state_hash()

    OperationResult(0, affected_count=2, attempted_count=3)
    ValueDomain.bounded_by(LIFE, step=1000).validate(3, lambda q: 8000)

    assert left.state_hash() == right.state_hash()
    rendered = repr(left.canonical_state())
    for word in ("attempted", "partial", "domain", "validity"):
        assert word not in rendered


# ======================================================================
# U. 실제 corpus 대표 사례 (§21 · §22)
# ======================================================================


def test_u_as_many_as_possible_is_card_declared_not_a_general_rule():
    """
    **공식 텍스트 203장**이 "가능한 만큼" 을 적어 두었다.

    ::

        2333466   "destroy as many other cards on the field as possible"
        21623008  "(or as many as possible)"
        35699     "Destroy as many cards you control as possible"

    적어 두지 않은 카드는 이 길을 타지 않는다. 기본값이 곧 그 사실이다.
    """
    assert CardOperation.destroy(PRIMARY_TARGET).partial is Partial.ALL_OR_NOTHING
    assert [p.value for p in Partial] == ["all_or_nothing", "as_many_as_possible"]


def test_u_a_per_value_rule_is_recorded_as_unresolved():
    """
    **값마다 규칙 판정이 필요한 도메인** (10건 안팎).

    ::

        for i=1,#g do
            if Duel.IsExistingMatchingCard(s.spfilter,tp,LOCATION_EXTRA,0,1,nil,e,tp,i,g)
            then table.insert(nums,i) end
        end                                        -- 14816857 · 50810455 · 56196385

    "그 수에 해당하는 카드가 있는가" 를 답하려면 조건 계층이 **수를
    인자로** 받아야 한다. 그 계층이 없으므로 ``RULE_UNRESOLVED`` 이고,
    언제나 ``UNKNOWN`` 이다 — 적을 수는 있고 통과시키지는 않는다.
    """
    domain = ValueDomain.unresolved(
        "수를 인자로 받는 조건 (IsExistingMatchingCard(..., i, g))"
    )

    for value in (1, 2, 3):
        assert domain.validate(value).validity is ActionValidity.UNKNOWN


def test_u_an_affordability_domain_needs_no_new_rule():
    """
    **판이 그 수를 치를 수 있는가** (5건 안팎).

    ::

        for i=5,1,-1 do
            if Duel.IsPlayerCanDiscardDeckAsCost(tp,i) then table.insert(ct,i) end
        end                                        -- 11834972 · 11851647 · 42256406
        if Duel.CheckLPCost(tp,1000*p) then ... end -- 17956906

    둘 다 "i 가 판의 어떤 양을 넘지 않는가" 이고, 그것은
    :attr:`ValueDomainKind.BOUNDED` 로 그대로 적힌다. 새 규칙이 필요하지
    않다.
    """
    deck = BoardQuantity(QuantitySource.ZONE_COUNT, PlayerRef.CONTROLLER, Zone.DECK)
    mill = ValueDomain.bounded_by(deck)
    pay = ValueDomain.bounded_by(LIFE, step=1000)

    assert mill.validate(3, lambda q: 5).validity is ActionValidity.VALID
    assert mill.validate(7, lambda q: 5).validity is ActionValidity.INVALID
    assert pay.validate(2, lambda q: 8000).validity is ActionValidity.VALID
    assert pay.validate(9, lambda q: 8000).validity is ActionValidity.INVALID


def test_u_no_real_card_was_registered_this_phase():
    """
    **0장 등재했다.** "가능한 만큼" 카드 203장 중 마법·함정이 103장이지만,
    파괴 관문을 답할 판정기가 없으므로 어느 것도 실행되지 않는다
    (``UnknownDestructionRuling`` — ADR-006 과 같은 자리).

    적을 수 있다는 것과 실행할 수 있다는 것은 다른 말이다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    assert len(EFFECT_LIBRARY) == 15
    for entry in EFFECT_LIBRARY:
        for operation in entry.definition.operations:
            assert getattr(operation, "partial", Partial.ALL_OR_NOTHING) is (
                Partial.ALL_OR_NOTHING
            )
