"""
Phase 2-AE — 성패와 처리량, 그리고 판에서 만들어지는 값.

    Operation
      → OperationResult
          ├── outcome         규칙대로 되었는가
          └── affected_count  몇 장을 다뤘는가
      → ResultRef / OperationRequirement   **명시적으로** 가리킨다
      → 후속 Operation

다섯을 뭉개지 않는다
--------------------
========================  ==========================================
성공했는가                  ``OperationOutcome``
몇 장을 다뤘는가             ``affected_count``
몇 장을 골랐는가             ``Selection`` · 무작위 선택의 장수
계산된 값                   ``SelectionCount`` · ``DerivedNumberDomain``
판                         ``GameState``
========================  ==========================================

``affected_count == 0`` 은 실패가 아니다
----------------------------------------
"최대 2장까지" 에서 0장을 고른 것은 **규칙대로 된 일**이다. 대상 계층이
이미 그렇게 판정한다 (``ChoiceSpec.is_optional``).

``UNKNOWN`` 은 ``FAILED`` 가 아니다
-----------------------------------
묘지로 보내면서 "묘지로 보내는 것을 막는 효과" 를 보지 않았다면, 카드는
움직였어도 그것이 규칙대로였다고 주장할 수 없다. 그 위에 다음 일을
쌓지 않는다.
"""

import ast
import pathlib

import pytest

from engine.condition import PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, CostGroup, Selection
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionError,
    EffectProvenance,
)
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.operation import CardOperation, DrawOperation, LifeChangeOperation
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
    TargetSpec,
    ZoneCountTerm,
)
from engine.execution import (
    DECLARED_NUMBER,
    BoardQuantity,
    DeclarationBinding,
    DeclaredNumber,
    DeclaredNumberSpec,
    DerivedNumberDomain,
    ExecutionValues,
    NumberDomain,
    OperationOutcome,
    OperationRequirement,
    OperationResult,
    QuantitySource,
    ResolvedDomain,
    ResultField,
    ResultRef,
    ValueOutcome,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
P1, P2 = 0, 1
LAB = 999_007

A, B, C, D = 55144522, 66719324, 5318639, 83764718
FILLER = 21844576
SUCCEEDED = ResultField.SUCCEEDED


def new_state(repository, seed: int | None = 7, opponent_hand: int = 4) -> GameState:
    game = GameState.create(
        repository,
        decks=([FILLER] * 16, [A, B, C, D] + [FILLER] * 12),
        seed=seed,
    )
    game.draw(P1, 3)
    game.draw(P2, opponent_hand)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def run(state, definition, journal=None, **context):
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        journal=journal,
    )
    return executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref, controller=P1, **context
        ),
    )


def define(ordinal, operations, **kwargs) -> EffectDefinition:
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        operations=operations,
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True, note="Phase 2-AE"),
        **kwargs,
    )


def optional_hand(minimum=0, maximum=2) -> TargetSpec:
    """"자신의 패에서 최대 2장까지" — 고르지 않아도 된다."""
    return TargetSpec.choosing(
        ChoiceSpec(
            source=CandidateSource(
                zones=frozenset({Zone.HAND}), owner=PlayerRef.CONTROLLER
            ),
            minimum=minimum,
            maximum=maximum,
        )
    )


def random_opponent_hand(count=1) -> TargetSpec:
    return TargetSpec.at_random(
        RandomSelectionSpec(
            source=CandidateSource(
                zones=frozenset({Zone.HAND}), owner=PlayerRef.OPPONENT
            ),
            count=count if isinstance(count, SelectionCount)
            else SelectionCount.fixed(count),
        )
    )


def hand_ids(game, owner):
    return [card.card_id for card in game.player(owner).hand]


def untouched(game, before_hash, before_hand, result, journal=None):
    assert result.status is not ResolutionStatus.RESOLVED
    assert result.applied == ()
    assert result.deltas == ()
    assert game.state_hash() == before_hash
    assert hand_ids(game, P2) == before_hand
    assert game.randomness.draws == 0
    if journal is not None:
        assert len(journal) == 0


# ======================================================================
# A · B · C. 성패와 장수는 다른 값이다 (§28 A · B · C · §2 · §7)
# ======================================================================


def test_a_an_operation_that_sees_every_rule_succeeds(state):
    """
    드로우는 주장하는 의미가 없으므로 (Phase 2-M 의 표가 비어 있다)
    **규칙대로 되었다고 말할 수 있다.**
    """
    result = run(state, define(0, (DrawOperation(count=1),)))

    assert result.status is ResolutionStatus.RESOLVED
    values = ExecutionValues().with_result(
        OperationResult(0, affected_count=1, outcome=OperationOutcome.SUCCEEDED)
    )
    assert values.outcome_of(0) is OperationOutcome.SUCCEEDED
    assert values.result(ResultRef(0)) == 1


def test_b_choosing_nothing_from_an_optional_target_still_resolves(state):
    """
    §2 — ``success = True`` 이면서 ``affected_count = 0`` 인 경우가
    **실제로 있다.**

    대상 계층은 이미 이것을 적법하다고 판정한다
    (``test_an_optional_target_accepts_nothing_at_all``). 실행기가
    거절하면 두 계층이 서로 다른 말을 하게 되고, 무엇보다 **0장을
    실패로 읽는 셈**이 된다.
    """
    before = len(state.player(P1).hand)

    result = run(
        state,
        define(
            1,
            (
                CardOperation.send_to_grave(PRIMARY_TARGET),
                DrawOperation(count=1),
            ),
            targets=TargetBinding.single(optional_hand()),
        ),
        selections=(TargetSelection(PRIMARY_TARGET, Selection()),),
    )

    assert result.status is ResolutionStatus.RESOLVED
    sent, drew = result.applied
    assert len(sent.instances) == 0  # 아무것도 안 갔다
    assert drew.amount == 1  # 그래도 뒤의 일은 일어났다
    assert len(state.player(P1).hand) == before + 1
    assert len(state.player(P1).grave) == 0


def test_b_a_required_target_still_refuses_an_empty_choice(state):
    """
    **고르지 않아도 되는 규칙에서만** 그렇다. 한 장 이상을 요구하면
    빈 선택은 여전히 거절이다.
    """
    before, hand = state.state_hash(), hand_ids(state, P2)

    result = run(
        state,
        define(
            2,
            (CardOperation.send_to_grave(PRIMARY_TARGET),),
            targets=TargetBinding.single(optional_hand(minimum=1, maximum=2)),
        ),
        selections=(TargetSelection(PRIMARY_TARGET, Selection()),),
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    untouched(state, before, hand, result)


def test_c_a_failed_operation_leaves_no_result_at_all(state):
    """
    §5 — 실패는 **조작의 결과가 아니라 효과 단위의 사실**이다.

    계획에서 막힌 조작은 적용되지 않으므로 결과를 남길 수 없고, 그래서
    ``OperationOutcome`` 에 ``FAILED`` 가 없다. 실패는
    ``ResolutionStatus`` 가 답한다.
    """
    before, hand = state.state_hash(), hand_ids(state, P2)

    result = run(state, define(3, (DrawOperation(count=99),)))

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert result.applied == ()
    assert [o.value for o in OperationOutcome] == ["succeeded", "unknown"]
    untouched(state, before, hand, result)


def test_c_count_is_never_read_as_success_in_the_engine():
    """
    §30 — ``affected_count == 0`` 을 실패로 접는 코드가 없다.

    실제 카드는 그렇게 쓴다 (``if ct==0 then return end`` 91곳). 그것은
    Lua 의 편의이지 규칙이 아니고, 이 엔진은 둘을 따로 답한다.
    """
    source = (ROOT / "engine" / "execution.py").read_text("utf-8")
    tree = ast.parse(source)

    # **장수를 세는 코드와 성패를 정하는 코드를 가른다** (Phase 2-AF 에서
    # 날카롭게 했다). 장수끼리 비교하는 것은 장수 질문이고 (``did_nothing``
    # 은 "하나도 못 했는가" 이지 "실패했는가" 가 아니다), 막아야 하는 것은
    # **성패를 장수에서 뽑아내는 것**이다.
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        body = ast.unparse(node)
        if "OperationOutcome" not in body:
            continue
        assert "affected_count" not in body, node.name
        assert "attempted_count" not in body, node.name

    # 성패를 만드는 코드도 장수를 보지 않는다.
    executor = ast.parse(
        (ROOT / "engine" / "effect" / "executor.py").read_text("utf-8")
    )
    (result_method,) = [
        node
        for node in ast.walk(executor)
        if isinstance(node, ast.FunctionDef) and node.name == "result"
    ]
    outcome_lines = [
        ast.unparse(node)
        for node in ast.walk(result_method)
        if isinstance(node, ast.IfExp)
    ]
    assert outcome_lines
    for line in outcome_lines:
        assert "affected" not in line and "instances" not in line


# ======================================================================
# D · E. 모르는 성패 (§28 D · E · §5)
# ======================================================================


def test_d_an_operation_that_could_not_check_its_rules_is_unknown(state):
    """
    묘지로 보내면서 "묘지로 보내는 것을 막는 효과" 를 보지 않았다.
    카드는 움직였지만 **규칙대로였다고 주장할 수 없다.**
    """
    result = run(
        state,
        define(
            4,
            (CardOperation.send_to_grave(PRIMARY_TARGET),),
            targets=TargetBinding.single(random_opponent_hand(1)),
        ),
    )

    assert result.status is ResolutionStatus.RESOLVED
    # 일어난 것은 사실이고, 못 본 규칙도 사실이다. 둘 다 들고 나온다.
    assert result.unchecked_rules
    assert len(state.player(P2).grave) == 1


def test_e_a_later_operation_may_require_the_earlier_one_to_have_succeeded(
    repository,
):
    """
    §28 E — 앞선 일의 **성패**를 명시적으로 가리킨다.

    드로우는 규칙을 다 보므로 뒤의 일이 그 위에 설 수 있다.
    """
    state = new_state(repository)
    before = len(state.player(P1).hand)

    result = run(
        state,
        define(
            5,
            (DrawOperation(count=1), DrawOperation(count=1)),
            requirements=(OperationRequirement(1, ResultRef(0, SUCCEEDED)),),
        ),
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert len(state.player(P1).hand) == before + 2


def test_e_an_unknown_outcome_stops_the_effect_instead_of_guessing(state):
    """
    §5 · §21 — ``UNKNOWN`` 을 ``FAILED`` 로도 ``SUCCEEDED`` 로도 바꾸지
    않는다. 모르는 것 위에 다음 일을 쌓지 않으므로 **전체를 거절**한다.

    건너뛰지 않는 이유는 이 실행기에 부분 적용이 없기 때문이다 — 앞의
    일만 남기고 뒤를 빼면 그것은 다른 효과다.
    """
    before, hand = state.state_hash(), hand_ids(state, P2)
    journal = EventJournal()

    result = run(
        state,
        define(
            6,
            (CardOperation.send_to_grave(PRIMARY_TARGET), DrawOperation(count=1)),
            targets=TargetBinding.single(random_opponent_hand(1)),
            requirements=(OperationRequirement(1, ResultRef(0, SUCCEEDED)),),
        ),
        journal,
    )

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert result.missing
    assert result.applied == ()
    assert result.deltas == ()
    assert state.state_hash() == before
    assert hand_ids(state, P2) == hand
    assert len(journal) == 0
    # 앞의 일을 **계획하면서** 난수는 이미 꺼냈다. 감추지 않는다
    # (Phase 2-AB 와 같은 사실이고, 같은 seed 면 같은 자리에서 같은 답이다).
    assert state.randomness.draws == 1


def test_e_success_cannot_be_read_as_a_number():
    """성패는 수가 아니다. 장수를 묻는 자리에 쓸 수 없다."""
    with pytest.raises(KeyError):
        OperationResult(0, affected_count=2).value_of(SUCCEEDED)
    with pytest.raises(ValueError, match="성패뿐"):
        OperationRequirement(1, ResultRef(0, ResultField.AFFECTED_COUNT))


# ======================================================================
# F · G. 장수 참조 · 없는 참조 (§28 F · G)
# ======================================================================


def test_f_a_later_operation_reads_the_earlier_count(state):
    """Phase 2-AD 의 흐름이 그대로다."""
    before = len(state.player(P1).hand)

    result = run(
        state,
        define(
            7,
            (
                CardOperation.send_to_grave(PRIMARY_TARGET),
                DrawOperation(count=SelectionCount.from_result(ResultRef(0))),
            ),
            targets=TargetBinding.single(random_opponent_hand(2)),
        ),
    )

    assert result.applied[1].amount == 2
    assert len(state.player(P1).hand) == before + 2


def test_f_zero_is_a_number_too(state):
    """
    §2 — 0장을 다룬 일의 결과는 **0** 이다. "없다" 가 아니다.
    그래서 뒤에서 그것을 가리키면 "0장을 뽑아라" 가 되고, 0장 드로우는
    의미가 없으므로 **거절**된다. 조용히 1장으로 바꾸지 않는다.
    """
    before, hand = state.state_hash(), hand_ids(state, P2)

    result = run(
        state,
        define(
            8,
            (
                CardOperation.send_to_grave(PRIMARY_TARGET),
                DrawOperation(count=SelectionCount.from_result(ResultRef(0))),
            ),
            targets=TargetBinding.single(optional_hand()),
        ),
        selections=(TargetSelection(PRIMARY_TARGET, Selection()),),
    )

    assert result.status is ResolutionStatus.INVALID_OPERATION
    assert result.code is ValidationCode.INVALID_AMOUNT
    untouched(state, before, hand, result)


def test_g_a_requirement_must_point_backwards():
    """자기 자신도, 없는 조작도 가리킬 수 없다. **앞만** 읽는다."""
    for index in (1, 5):
        with pytest.raises(EffectDefinitionError):
            define(
                9,
                (DrawOperation(1), DrawOperation(1)),
                requirements=(OperationRequirement(1, ResultRef(index, SUCCEEDED)),),
            )

    # 앞을 가리키는 것은 된다 — 그것이 이 기능의 전부다.
    assert define(
        9,
        (DrawOperation(1), DrawOperation(1)),
        requirements=(OperationRequirement(1, ResultRef(0, SUCCEEDED)),),
    ).requirements_for(1)


def test_g_a_missing_result_is_unknown_not_zero():
    values = ExecutionValues()

    assert values.outcome_of(0) is None
    answer = SelectionCount.from_result(ResultRef(0)).resolve(lambda r, z: 9)
    assert answer.outcome is ValueOutcome.UNKNOWN
    assert answer.value is None


# ======================================================================
# H ~ L. 계산되는 값 (§28 H ~ L · §9 · §10 · §11)
# ======================================================================


def test_h_a_constant_is_a_value_source():
    answer = SelectionCount.fixed(2).resolve(lambda r, z: 0)
    assert answer.outcome is ValueOutcome.RESOLVED
    assert answer.value == 2


def test_i_a_declared_number_is_a_value_source(state):
    result = run(
        state,
        define(
            10,
            (CardOperation.send_to_grave(PRIMARY_TARGET),),
            targets=TargetBinding.single(
                random_opponent_hand(SelectionCount.from_declaration(DECLARED_NUMBER))
            ),
            declarations=(
                DeclarationBinding(
                    DECLARED_NUMBER, DeclaredNumberSpec(NumberDomain.between(1, 3))
                ),
            ),
        ),
        declarations=(DeclaredNumber(DECLARED_NUMBER, 3),),
    )

    assert len(result.applied[0].instances) == 3


def test_j_the_board_is_a_value_source(repository):
    """
    §28 J — 자리 장수와 라이프를 **권위 있는 판**에서 읽는다.
    """
    state = new_state(repository, opponent_hand=4)
    read = EffectExecutor()._read_quantity(
        state, ResolutionContext(effect_ref=EffectRef(LAB, 0), controller=P1)
    )

    assert read(BoardQuantity(QuantitySource.ZONE_COUNT, PlayerRef.OPPONENT, Zone.HAND)) == 4
    assert read(BoardQuantity(QuantitySource.ZONE_COUNT, PlayerRef.CONTROLLER, Zone.HAND)) == 3
    assert read(BoardQuantity(QuantitySource.LIFE_POINTS, PlayerRef.CONTROLLER)) == 8000


def test_j_a_domain_is_built_from_the_board(repository):
    """
    §12 — **선언 도메인과 계산값은 다른 개념이고, 여기서 만난다.**
    도메인은 고를 수 있는 수의 목록이고, 그 **끝**이 계산값이다.
    """
    state = new_state(repository, opponent_hand=4)
    read = EffectExecutor()._read_quantity(
        state, ResolutionContext(effect_ref=EffectRef(LAB, 0), controller=P1)
    )

    hand = DerivedNumberDomain(
        BoardQuantity(QuantitySource.ZONE_COUNT, PlayerRef.OPPONENT, Zone.HAND)
    )
    life = DerivedNumberDomain(
        BoardQuantity(QuantitySource.LIFE_POINTS, PlayerRef.CONTROLLER), step=1000
    )

    assert hand.resolve(read).domain == NumberDomain.between(1, 4)
    assert life.resolve(read).domain.values == tuple(
        1000 * i for i in range(1, 9)
    )


@pytest.mark.parametrize("declared,status", [(4, "ok"), (5, "no")])
def test_j_a_built_domain_actually_bounds_the_declaration(
    repository, declared, status
):
    state = new_state(repository, opponent_hand=4)
    definition = define(
        11,
        (CardOperation.send_to_grave(PRIMARY_TARGET),),
        targets=TargetBinding.single(
            random_opponent_hand(SelectionCount.from_declaration(DECLARED_NUMBER))
        ),
        declarations=(
            DeclarationBinding(
                DECLARED_NUMBER,
                DeclaredNumberSpec(
                    DerivedNumberDomain(
                        BoardQuantity(
                            QuantitySource.ZONE_COUNT, PlayerRef.OPPONENT, Zone.HAND
                        )
                    )
                ),
            ),
        ),
    )

    result = run(
        state, definition, declarations=(DeclaredNumber(DECLARED_NUMBER, declared),)
    )

    if status == "ok":
        assert result.status is ResolutionStatus.RESOLVED
        assert len(result.applied[0].instances) == 4
    else:
        assert result.status is ResolutionStatus.INVALID_CONTEXT
        assert "1, 2, 3, 4" in result.reason


def test_k_a_domain_that_cannot_be_built_is_unknown_not_empty():
    """§11 — ``UNKNOWN ≠ 0`` 이고 ``UNKNOWN ≠ 빈 목록`` 이다."""
    domain = DerivedNumberDomain(
        BoardQuantity(QuantitySource.LIFE_POINTS, PlayerRef.CONTROLLER), step=1000
    )

    answer = domain.resolve(lambda quantity: None)

    assert answer.outcome is ValueOutcome.UNKNOWN
    assert answer.domain is None
    with pytest.raises(TypeError):
        bool(answer)


def test_l_a_domain_with_nothing_to_choose_is_invalid(repository):
    """
    고를 것이 하나도 없으면 그것은 **선언이 아니라 조건**이다. 빈 목록을
    만들어 넘기지 않는다.
    """
    state = new_state(repository, opponent_hand=4)
    state.player(P1).change_life(-7500)  # 라이프 500
    read = EffectExecutor()._read_quantity(
        state, ResolutionContext(effect_ref=EffectRef(LAB, 0), controller=P1)
    )

    answer = DerivedNumberDomain(
        BoardQuantity(QuantitySource.LIFE_POINTS, PlayerRef.CONTROLLER), step=1000
    ).resolve(read)

    assert answer.outcome is ValueOutcome.INVALID
    assert answer.domain is None


def test_l_an_invalid_domain_stops_before_anything_happens(repository):
    state = new_state(repository, opponent_hand=0)
    before, hand = state.state_hash(), hand_ids(state, P2)

    result = run(
        state,
        define(
            12,
            (CardOperation.send_to_grave(PRIMARY_TARGET),),
            targets=TargetBinding.single(
                random_opponent_hand(SelectionCount.from_declaration(DECLARED_NUMBER))
            ),
            declarations=(
                DeclarationBinding(
                    DECLARED_NUMBER,
                    DeclaredNumberSpec(
                        DerivedNumberDomain(
                            BoardQuantity(
                                QuantitySource.ZONE_COUNT,
                                PlayerRef.OPPONENT,
                                Zone.HAND,
                            )
                        )
                    ),
                ),
            ),
        ),
        declarations=(DeclaredNumber(DECLARED_NUMBER, 1),),
    )

    assert result.status is ResolutionStatus.INVALID_OPERATION
    assert result.code is ValidationCode.INVALID_AMOUNT
    untouched(state, before, hand, result)


def test_the_five_value_sources_are_all_expressible():
    """
    §10 — 값의 출처를 나누어 둔다. **하나의 사전에 뭉치지 않는다.**

    ==========  =============================================
    상수         ``SelectionCount.fixed``
    선언한 수     ``SelectionCount.from_declaration``
    앞선 결과     ``SelectionCount.from_result``
    판에서       ``SelectionCount.derived`` · ``BoardQuantity``
    모름         ``SelectionCount.unknown``
    ==========  =============================================
    """
    from engine.effect.target import CountKind

    kinds = {
        SelectionCount.fixed(1).kind,
        SelectionCount.from_declaration(DECLARED_NUMBER).kind,
        SelectionCount.from_result(ResultRef(0)).kind,
        SelectionCount.derived(
            (ZoneCountTerm(PlayerRef.CONTROLLER, Zone.HAND, 1),)
        ).kind,
        SelectionCount.unknown("아직 없는 계층").kind,
    }
    assert kinds == set(CountKind)


# ======================================================================
# M · N · O. 선택 · 무작위 · 난수 (§28 M · N · O · §16 · §17)
# ======================================================================


def test_m_a_choice_becomes_a_value_without_becoming_the_value_layer(state):
    """
    §16 — 고르는 **행위**와 이미 정해진 값을 **참조**하는 것은 다르다.
    선언은 문맥으로 들어오고, 값 계층은 그것을 이름으로 읽을 뿐이다.
    """
    values = ExecutionValues(declarations=(DeclaredNumber(DECLARED_NUMBER, 2),))

    count = SelectionCount.from_declaration(DECLARED_NUMBER)

    assert count.resolve(lambda r, z: 0, values).value == 2
    # 값 계층은 **고르지 않는다** — 고르는 자리가 비어 있으면 그대로 모른다.
    assert count.resolve(lambda r, z: 0).outcome is ValueOutcome.UNKNOWN


def test_n_a_random_selection_reports_how_many_it_took(state):
    """
    §17 — 무작위로 고른 장수가 뒤의 일로 이어진다. 그래도 난수원은
    값을 계산하지 않는다 — 고른 것을 **세는 것은 결과**다.
    """
    result = run(
        state,
        define(
            13,
            (
                CardOperation.send_to_grave(PRIMARY_TARGET),
                DrawOperation(count=SelectionCount.from_result(ResultRef(0))),
            ),
            targets=TargetBinding.single(random_opponent_hand(3)),
        ),
    )

    assert result.applied[0].instances and len(result.applied[0].instances) == 3
    assert result.applied[1].amount == 3
    assert state.randomness.draws == 3


def test_n_the_random_source_still_calculates_nothing():
    tree = ast.parse((ROOT / "engine" / "randomness.py").read_text("utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {
        "SelectionCount",
        "BoardQuantity",
        "DerivedNumberDomain",
        "OperationResult",
    }


def test_o_building_a_value_consumes_no_randomness(repository):
    """§19 — 값 계산 때문에 게임 난수가 소비되지 않는다."""
    state = new_state(repository)
    read = EffectExecutor()._read_quantity(
        state, ResolutionContext(effect_ref=EffectRef(LAB, 0), controller=P1)
    )

    DerivedNumberDomain(
        BoardQuantity(QuantitySource.LIFE_POINTS, PlayerRef.CONTROLLER), step=1000
    ).resolve(read)
    SelectionCount.derived(
        (ZoneCountTerm(PlayerRef.OPPONENT, Zone.HAND, 1),)
    ).resolve(lambda ref, zone: 4)

    assert state.randomness.draws == 0


# ======================================================================
# P ~ T. 복제 · 실패 안전 · 정보 · 저널 · 해시 (§28 P ~ T)
# ======================================================================


def test_p_results_made_in_one_execution_never_reach_another(repository):
    original = new_state(repository, seed=51)
    copy = original.clone()

    run(
        copy,
        define(
            14,
            (CardOperation.send_to_grave(PRIMARY_TARGET),),
            targets=TargetBinding.single(random_opponent_hand(2)),
        ),
    )

    assert original.randomness.draws == 0
    assert len(original.player(P2).hand) == 4
    assert len(copy.player(P2).hand) == 2
    # 실행 값은 애초에 판에 붙어 있지 않다.
    assert not hasattr(original, "results")
    assert not hasattr(copy, "results")


def test_p_the_values_are_immutable():
    empty = ExecutionValues()
    one = empty.with_result(OperationResult(0, 2, OperationOutcome.UNKNOWN))

    assert empty.results == ()
    assert one.outcome_of(0) is OperationOutcome.UNKNOWN
    assert empty.outcome_of(0) is None


def test_q_a_failure_in_the_middle_changes_nothing(state):
    """§21 — 값 계산이 실패해도 판이 반쯤 바뀌지 않는다."""
    before, hand = state.state_hash(), hand_ids(state, P2)
    journal = EventJournal()

    result = run(
        state,
        define(
            15,
            (
                CardOperation.send_to_grave(PRIMARY_TARGET),
                DrawOperation(count=SelectionCount.unknown("아직 없는 계층")),
            ),
            targets=TargetBinding.single(random_opponent_hand(2)),
        ),
        journal,
    )

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert result.applied == ()
    assert result.deltas == ()
    assert state.state_hash() == before
    assert hand_ids(state, P2) == hand
    assert len(journal) == 0
    # 난수는 이미 꺼냈다 — 감추지 않는다 (Phase 2-AB 와 같다).
    assert state.randomness.draws == 2


def test_r_reading_a_count_never_opens_a_hand(state):
    """
    §18 — 장수는 규칙이 아는 사실이고 **정체는 아니다.** 도메인을 상대
    패의 장수로 만들어도 그 패는 여전히 가려져 있다.
    """
    result = run(
        state,
        define(
            16,
            (CardOperation.send_to_grave(PRIMARY_TARGET),),
            targets=TargetBinding.single(
                random_opponent_hand(SelectionCount.from_declaration(DECLARED_NUMBER))
            ),
            declarations=(
                DeclarationBinding(
                    DECLARED_NUMBER,
                    DeclaredNumberSpec(
                        DerivedNumberDomain(
                            BoardQuantity(
                                QuantitySource.ZONE_COUNT,
                                PlayerRef.OPPONENT,
                                Zone.HAND,
                            )
                        )
                    ),
                ),
            ),
        ),
        declarations=(DeclaredNumber(DECLARED_NUMBER, 1),),
    )

    assert result.status is ResolutionStatus.RESOLVED
    view = GameStateView.from_state(state, viewer=P1)
    assert view.player(P2).zone(Zone.HAND).concealed is True
    assert view.player(P2).zone(Zone.HAND).cards == ()
    assert view.player(P2).zone(Zone.HAND).size == 3  # 장수는 보인다


def test_r_the_value_layer_never_reads_an_observation():
    """값 계층은 관측을 알지 못한다."""
    tree = ast.parse((ROOT / "engine" / "execution.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "engine.game_state_view" not in imported
    assert "engine.observation" not in imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"GameStateView", "ObservationPolicy", "GameState"}


def test_s_the_journal_records_only_the_change(state):
    journal = EventJournal()

    run(
        state,
        define(
            17,
            (CardOperation.send_to_grave(PRIMARY_TARGET),),
            targets=TargetBinding.single(random_opponent_hand(1)),
        ),
        journal,
    )

    assert len(journal) == 1
    rendered = repr(journal.to_dict() if hasattr(journal, "to_dict") else list(journal))
    for word in ("outcome", "succeeded", "affected_count", "domain"):
        assert word not in rendered


def test_s_an_operation_that_moved_nothing_writes_no_event(state):
    """
    0장을 다룬 일은 **판을 바꾸지 않았으므로** 사건도 없다.
    결과는 남고 (``affected_count = 0``) 역사는 남지 않는다.
    """
    journal = EventJournal()

    result = run(
        state,
        define(
            18,
            (CardOperation.send_to_grave(PRIMARY_TARGET),),
            targets=TargetBinding.single(optional_hand()),
        ),
        selections=(TargetSelection(PRIMARY_TARGET, Selection()),),
        journal=journal,
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert result.deltas == ()
    assert len(journal) == 0


def test_t_values_and_outcomes_stay_out_of_the_hash(repository):
    left, right = new_state(repository, seed=13), new_state(repository, seed=13)
    assert left.state_hash() == right.state_hash()

    read = EffectExecutor()._read_quantity(
        left, ResolutionContext(effect_ref=EffectRef(LAB, 0), controller=P1)
    )
    DerivedNumberDomain(
        BoardQuantity(QuantitySource.LIFE_POINTS, PlayerRef.CONTROLLER), step=1000
    ).resolve(read)
    ExecutionValues().with_result(OperationResult(0, 2, OperationOutcome.UNKNOWN))

    assert left.state_hash() == right.state_hash()
    rendered = repr(left.canonical_state())
    for word in ("outcome", "succeeded", "affected_count"):
        assert word not in rendered


# ======================================================================
# U. 실제 corpus 대표 사례 (§24 · §25)
# ======================================================================


def test_u_the_shape_of_a_success_checking_card_is_expressible():
    """
    **"파괴했다면 그 다음" (91곳)** 의 모양이다.

    ::

        local ct=Duel.Destroy(g,REASON_EFFECT)
        if ct~=0 then <다음 일> end

    Lua 는 **장수를 성패처럼** 읽는다. 이 엔진은 둘을 따로 답하고,
    의존은 ``OperationRequirement`` 로 적는다.

    그러나 **건너뛰지는 못한다.** 앞이 ``UNKNOWN`` 이면 전체를 거절할
    뿐이고, "앞은 남기고 뒤만 빼는" 부분 적용이 없다. 그것이 지금의
    한계이고 (STRUCTURAL-88), 적을 수 있다는 것과 실행할 수 있다는 것을
    섞지 않는다.
    """
    definition = define(
        19,
        (DrawOperation(count=1), DrawOperation(count=1)),
        requirements=(OperationRequirement(1, ResultRef(0, SUCCEEDED)),),
    )

    (requirement,) = definition.requirements_for(1)
    assert requirement.after.operation_index == 0
    assert definition.requirements_for(0) == ()


def test_u_the_shape_of_wall_of_revealing_light_is_expressible():
    """
    **광명의 벽 (17078030)** — "1000 의 배수로 라이프를 지불하고 발동."

    ::

        local lp=Duel.GetLP(tp)
        local t={}
        for i=1,math.floor((lp)/1000) do t[i]=i*1000 end
        local announce=Duel.AnnounceNumber(tp,table.unpack(t))

    ``table.unpack`` 이 하는 일은 **판에서 만든 목록을 넘기는 것**이고,
    그 목록의 모양이 정확히 :class:`DerivedNumberDomain` 이다.

    **등재하지 않았다** — 지불한 만큼을 기억해 지속 효과로 쓰는 계층이
    없다. 모양을 적을 수 있다는 것과 카드를 실행할 수 있다는 것은 다른
    말이다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    domain = DerivedNumberDomain(
        BoardQuantity(QuantitySource.LIFE_POINTS, PlayerRef.CONTROLLER), step=1000
    )

    built = domain.resolve(lambda quantity: 4300)
    assert built.outcome is ValueOutcome.RESOLVED
    assert built.domain.values == (1000, 2000, 3000, 4000)
    assert isinstance(built, ResolvedDomain)

    assert 17078030 not in {entry.card_id for entry in EFFECT_LIBRARY}


def test_u_a_literal_domain_did_not_need_this_phase():
    """
    ``table.unpack`` 이 있다고 모두 계산이 필요한 것은 아니다.

    식스 센스(3280747)는 ``for i=1,6 do t[i]=i end`` 로 **상수 목록**을
    만든다. Phase 2-AD 의 ``NumberDomain`` 으로 이미 적을 수 있었다.
    """
    assert NumberDomain.between(1, 6).values == (1, 2, 3, 4, 5, 6)
    assert not DeclaredNumberSpec(NumberDomain.between(1, 6)).is_derived
    assert DeclaredNumberSpec(
        DerivedNumberDomain(
            BoardQuantity(QuantitySource.LIFE_POINTS, PlayerRef.CONTROLLER), 1000
        )
    ).is_derived
