"""
Phase 2-AD — 선언한 수와 앞선 결과.

    Effect
      → DeclaredNumberSpec    누가 어떤 수를 선언하는가   (규칙)
      → DeclaredNumber        실제로 선언한 수            (입력)
      → ExecutionValues       이번 해결 동안만 산다
      → 후속 Operation

    Operation A
      → OperationResult       그 일이 얼마나 했는가
      → ResultRef(번호, 칸)    **명시적으로** 가리킨다
      → Operation B

네 가지를 뭉개지 않는다
-----------------------
========================  ==========================================
고른 카드                  ``Selection``          — 사람이 고른 것
무작위로 고른 카드          ``RandomSelectionSpec``— 아무도 안 고른 것
**선언한 수**              ``DeclaredNumber``     — 사람이 정한 수
**앞선 조작의 결과**        ``OperationResult``    — 판이 정한 수
========================  ==========================================

"바로 앞의 결과" 는 없다
------------------------
앞의 일을 쓰려면 **몇 번째인지 적어야** 한다. 마지막 결과를 자동으로
집어 오면, 정의에 일을 하나 끼워 넣는 순간 조용히 다른 수가 된다.
"""

import ast
import pathlib

import pytest

from engine.condition import PlayerRef
from engine.cost import CandidateSource, CostGroup
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionError,
    EffectProvenance,
)
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.operation import CardOperation, DrawOperation, LifeChangeOperation
from engine.effect.resolution import ResolutionContext, ResolutionStatus
from engine.effect.target import (
    PRIMARY_TARGET,
    CountKind,
    RandomSelectionSpec,
    SelectionCount,
    TargetBinding,
    TargetSpec,
)
from engine.execution import (
    ResolvedValue,
    ValueOutcome,
    DECLARED_NUMBER,
    NO_EXECUTION_VALUES,
    DeclarationBinding,
    DeclarationOutcome,
    DeclaredNumber,
    DeclaredNumberSpec,
    ExecutionLookupError,
    ExecutionValues,
    NumberDomain,
    OperationOutcome,
    OperationResult,
    ResolvedDeclaration,
    ResultField,
    ResultRef,
    ValueRef,
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
LAB = 999_006  # synthetic 정의의 자리. 실제 카드 번호가 아니다.

A, B, C, D = 55144522, 66719324, 5318639, 83764718
FILLER = 21844576
SECOND = ValueRef("second")


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


def opponent_hand_spec(count) -> RandomSelectionSpec:
    return RandomSelectionSpec(
        source=CandidateSource(
            zones=frozenset({Zone.HAND}), owner=PlayerRef.OPPONENT
        ),
        count=count,
    )


def declares(
    domain=NumberDomain.between(1, 3),
    chooser=PlayerRef.OPPONENT,
    ref=DECLARED_NUMBER,
    ordinal=0,
) -> EffectDefinition:
    """상대가 1~3 중 하나를 선언하고, 그만큼 상대 패를 무작위로 버린다."""
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.at_random(
                opponent_hand_spec(SelectionCount.from_declaration(ref))
            )
        ),
        declarations=(
            DeclarationBinding(ref, DeclaredNumberSpec(domain, chooser=chooser)),
        ),
        operations=(CardOperation.send_to_grave(PRIMARY_TARGET),),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True, note="Phase 2-AD"),
    )


def chains(first_count=2, ref=ResultRef(0), ordinal=1) -> EffectDefinition:
    """0번이 상대 패를 N장 보내고, 1번이 **그만큼** 뽑는다."""
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.at_random(opponent_hand_spec(SelectionCount.fixed(first_count)))
        ),
        operations=(
            CardOperation.send_to_grave(PRIMARY_TARGET),
            DrawOperation(count=SelectionCount.from_result(ref)),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True, note="Phase 2-AD"),
    )


def run(state, definition, declarations=(), journal=None):
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        journal=journal,
    )
    return executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref,
            controller=P1,
            declarations=tuple(declarations),
        ),
    )


def hand_ids(game, owner):
    return [card.card_id for card in game.player(owner).hand]


def untouched(game, before_hash, before_hand, result, journal=None):
    """판도 난수도 그대로다."""
    assert result.status is not ResolutionStatus.RESOLVED
    assert result.applied == ()
    assert result.deltas == ()
    assert game.state_hash() == before_hash
    assert hand_ids(game, P2) == before_hand
    assert game.randomness.draws == 0
    if journal is not None:
        assert len(journal) == 0


# ======================================================================
# A. 선언한 수 (§25 A · §19)
# ======================================================================


@pytest.mark.parametrize("declared", [1, 2, 3])
def test_a_a_declared_number_decides_how_many(state, declared):
    """
    §19 의 흐름이 끝까지 돈다.

        정의가 묻는다 → 사람이 답한다 → 그 수만큼 일어난다
    """
    before = len(state.player(P2).hand)

    result = run(state, declares(), [DeclaredNumber(DECLARED_NUMBER, declared)])

    assert result.status is ResolutionStatus.RESOLVED, declared
    (applied,) = result.applied
    assert len(applied.instances) == declared
    assert len(state.player(P2).hand) == before - declared


def test_a_the_same_declaration_always_gives_the_same_count(repository):
    """§15 — 같은 입력이면 같은 결과다."""
    counts = []
    for _ in range(3):
        game = new_state(repository, seed=4)
        result = run(game, declares(), [DeclaredNumber(DECLARED_NUMBER, 2)])
        counts.append(len(result.applied[0].instances))
    assert counts == [2, 2, 2]


# ======================================================================
# B. 허용되지 않은 수 (§25 B)
# ======================================================================


@pytest.mark.parametrize("declared", [0, 4, -1, 99])
def test_b_a_number_outside_the_domain_is_refused(state, declared):
    """
    **가까운 수로 고쳐 주지 않는다.** 4 를 선언했는데 3 으로 읽으면
    규칙을 정한 것은 플레이어가 아니라 실행기다.
    """
    before, hand = state.state_hash(), hand_ids(state, P2)
    journal = EventJournal()

    result = run(
        state, declares(), [DeclaredNumber(DECLARED_NUMBER, declared)], journal
    )

    assert result.status is ResolutionStatus.INVALID_CONTEXT
    assert result.code is ValidationCode.INVALID_AMOUNT
    assert str(declared) in result.reason
    untouched(state, before, hand, result, journal)


def test_b_a_number_this_effect_never_asked_for_is_refused(state):
    """묻지 않은 수가 들어오면 **조용히 무시하지 않는다.**"""
    before, hand = state.state_hash(), hand_ids(state, P2)

    result = run(
        state,
        declares(),
        [DeclaredNumber(DECLARED_NUMBER, 2), DeclaredNumber(SECOND, 1)],
    )

    assert result.status is ResolutionStatus.INVALID_CONTEXT
    assert "second" in result.reason
    untouched(state, before, hand, result)


# ======================================================================
# C. 아직 선언하지 않았다 (§25 C)
# ======================================================================


def test_c_a_pending_declaration_stops_before_anything_happens(state):
    """
    **대신 정해 주지 않는다.** 1 로 채우면 "1장" 이라는 틀린 규칙이
    되고, 0 으로 채우면 효과가 조용히 사라진다.
    """
    before, hand = state.state_hash(), hand_ids(state, P2)
    journal = EventJournal()

    result = run(state, declares(), journal=journal)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    assert result.missing == f"declared number {DECLARED_NUMBER}"
    untouched(state, before, hand, result, journal)


def test_c_pending_is_not_false(state):
    """``PENDING`` 이 거짓이 되면 "아직" 이 "안 된다" 로 접힌다."""
    answer = NO_EXECUTION_VALUES.declared(DECLARED_NUMBER)

    assert answer.outcome is DeclarationOutcome.PENDING
    assert answer.value is None
    with pytest.raises(TypeError):
        bool(answer)


def test_c_a_resolved_declaration_must_carry_a_number():
    with pytest.raises(ValueError):
        ResolvedDeclaration(DeclarationOutcome.RESOLVED)
    with pytest.raises(ValueError):
        ResolvedDeclaration(DeclarationOutcome.PENDING, value=1)


# ======================================================================
# D. 고를 수 있는 수의 집합 (§25 D · §5)
# ======================================================================


def test_d_the_domain_is_a_list_not_a_range():
    """
    공식 스크립트의 ``Duel.AnnounceNumber(tp, ...)`` 는 **고를 수 있는
    수를 하나하나 나열한다.** 그래서 목록이 본래 모양이고, 범위는 그것을
    적는 줄임말이다.
    """
    assert NumberDomain.between(1, 3) == NumberDomain.of(1, 2, 3)
    assert NumberDomain.exact(2).only == 2
    assert NumberDomain.of(100, 200, 300).values == (100, 200, 300)
    assert 200 in NumberDomain.of(100, 200, 300)
    assert 150 not in NumberDomain.of(100, 200, 300)


def test_d_an_empty_or_crooked_domain_is_refused():
    with pytest.raises(ValueError, match="하나도 없습니다"):
        NumberDomain(())
    with pytest.raises(ValueError, match="두 번"):
        NumberDomain((1, 1))
    with pytest.raises(ValueError, match="오름차순"):
        NumberDomain((2, 1))


@pytest.mark.parametrize(
    "domain,good,bad",
    [
        (NumberDomain.exact(1), 1, 2),
        (NumberDomain.between(1, 3), 3, 4),
        (NumberDomain.of(1, 2, 4), 4, 3),  # 가운데가 비어 있어도 된다
    ],
)
def test_d_every_domain_shape_works_end_to_end(repository, domain, good, bad):
    left = new_state(repository)
    right = new_state(repository)

    ok = run(left, declares(domain), [DeclaredNumber(DECLARED_NUMBER, good)])
    no = run(right, declares(domain), [DeclaredNumber(DECLARED_NUMBER, bad)])

    assert ok.status is ResolutionStatus.RESOLVED
    assert len(ok.applied[0].instances) == good
    assert no.status is ResolutionStatus.INVALID_CONTEXT


# ======================================================================
# §7. 누가 선언하는가
# ======================================================================


def test_the_chooser_may_be_someone_other_than_the_controller():
    """
    **효과의 컨트롤러 ≠ 선언하는 사람** 일 수 있다.

    부작용?(30922149)에서 1~3 을 정하는 것은 뽑는 쪽, 즉 상대다.
    기존 ``PlayerRef`` 어휘를 그대로 쓰므로 새 뜻을 만들지 않았다.
    """
    from engine.condition import ConditionContext

    mine = DeclaredNumberSpec(NumberDomain.between(1, 3))
    theirs = DeclaredNumberSpec(NumberDomain.between(1, 3), chooser=PlayerRef.OPPONENT)
    context = ConditionContext(player=P1)

    assert NO_EXECUTION_VALUES.chooser_of(mine, context) == P1
    assert NO_EXECUTION_VALUES.chooser_of(theirs, context) == P2
    assert declares(chooser=PlayerRef.OPPONENT).declarations[0].spec.chooser is (
        PlayerRef.OPPONENT
    )


def test_the_declaration_names_are_a_different_space_from_target_names():
    """
    "2장" 과 "2" 를 한 이름표에 담지 않는다.
    """
    from engine.effect.target import TargetRef

    assert ValueRef("primary") != TargetRef("primary")
    assert not isinstance(DECLARED_NUMBER, TargetRef)


def test_declaring_a_number_is_checked_by_the_definition():
    """묻지 않고 쓰거나, 묻고 안 쓰면 정의가 거부한다."""
    with pytest.raises(EffectDefinitionError, match="선언되지 않은 수"):
        EffectDefinition(
            effect_ref=EffectRef(LAB, 0),
            source_card_id=LAB,
            operations=(
                DrawOperation(count=SelectionCount.from_declaration(SECOND)),
            ),
            provenance=EffectProvenance.hand_written(verified=True),
        )
    with pytest.raises(EffectDefinitionError, match="묻고 버리는"):
        EffectDefinition(
            effect_ref=EffectRef(LAB, 0),
            source_card_id=LAB,
            declarations=(
                DeclarationBinding(SECOND, DeclaredNumberSpec(NumberDomain.exact(1))),
            ),
            operations=(DrawOperation(1),),
            provenance=EffectProvenance.hand_written(verified=True),
        )


# ======================================================================
# E. 선언한 수가 문맥에 산다 (§25 E · §8)
# ======================================================================


def test_e_the_declared_number_is_read_by_name(state):
    values = ExecutionValues(declarations=(DeclaredNumber(DECLARED_NUMBER, 2),))
    spec = DeclaredNumberSpec(NumberDomain.between(1, 3))

    answer = values.declared(DECLARED_NUMBER, spec)

    assert answer.outcome is DeclarationOutcome.RESOLVED
    assert answer.value == 2
    # 다른 이름은 여전히 비어 있다 — 이름 하나에 값 하나다.
    assert values.declared(SECOND).outcome is DeclarationOutcome.PENDING


def test_e_a_count_asked_outside_an_execution_says_so():
    """
    실행 밖에서 선언을 물으면 ``PENDING`` 이 그대로 나온다. 기본값이
    ``None`` 이 아니라 **"아무것도 생기지 않았다"** 인 이유다.
    """
    count = SelectionCount.from_declaration(DECLARED_NUMBER)

    answer = count.resolve(lambda ref, zone: 5)

    assert answer.outcome is ValueOutcome.UNKNOWN
    assert answer.value is None
    assert answer.missing == f"declared number {DECLARED_NUMBER}"


def test_e_the_execution_values_never_reach_the_game_state(state):
    """
    §8 — 실행 중의 값은 **판이 아니다.**
    """
    run(state, declares(), [DeclaredNumber(DECLARED_NUMBER, 2)])

    assert not hasattr(state, "declarations")
    assert not hasattr(state, "execution_values")
    rendered = repr(state.canonical_state())
    assert "declared" not in rendered and "affected_count" not in rendered


# ======================================================================
# F · G. 앞선 조작의 결과 (§25 F · G · §20)
# ======================================================================


def test_f_a_later_operation_reads_an_earlier_result(state):
    """
    §20 — 0번이 2장을 보냈으면 1번은 **정확히 2장** 뽑는다.
    """
    before = len(state.player(P1).hand)

    result = run(state, chains(first_count=2))

    assert result.status is ResolutionStatus.RESOLVED
    sent, drew = result.applied
    assert len(sent.instances) == 2
    assert drew.amount == 2
    assert len(state.player(P1).hand) == before + 2


def test_f_the_number_follows_the_earlier_operation(repository):
    """1장을 보냈으면 1장, 3장을 보냈으면 3장이다."""
    for sent in (1, 3):
        game = new_state(repository)
        result = run(game, chains(first_count=sent))
        assert result.applied[1].amount == sent, sent


def test_f_a_multiplier_is_allowed_because_real_cards_use_one(state):
    """
    ``dr*2000`` (부작용? 30922149) 같은 곱셈까지다. **수식 언어가
    아니다** — 더 필요해지면 그때 근거를 들고 온다.
    """
    values = ExecutionValues().with_result(OperationResult(0, 3))

    assert values.result(ResultRef(0)) == 3
    assert values.result(ResultRef(0, multiplier=2000)) == 6000


def test_g_an_earlier_result_is_not_used_unless_it_is_named(state):
    """
    §20 — "마지막 조작" 같은 암묵적 지시가 없다. 가리키지 않은 정의는
    앞의 수를 **모른다.**
    """
    plain = EffectDefinition(
        effect_ref=EffectRef(LAB, 3),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.at_random(opponent_hand_spec(SelectionCount.fixed(3)))
        ),
        operations=(
            CardOperation.send_to_grave(PRIMARY_TARGET),
            DrawOperation(1),  # 가리키지 않았다
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )

    result = run(state, plain)

    sent, drew = result.applied
    assert len(sent.instances) == 3
    assert drew.amount == 1  # 3 이 아니다


def test_g_a_reference_may_only_look_backwards():
    """앞선 일만 읽을 수 있다. 자기 자신도 안 된다."""
    for index in (0, 1):
        with pytest.raises(EffectDefinitionError, match="앞선 일만"):
            EffectDefinition(
                effect_ref=EffectRef(LAB, 0),
                source_card_id=LAB,
                operations=(
                    DrawOperation(
                        count=SelectionCount.from_result(ResultRef(index))
                    ),
                    DrawOperation(1),
                ),
                provenance=EffectProvenance.hand_written(verified=True),
            )


def test_g_the_executor_never_reaches_for_the_last_result():
    """코드에서도 그렇다 — ``results[-1]`` 같은 것이 없다."""
    source = (ROOT / "engine" / "execution.py").read_text("utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.UnaryOp):
            raise AssertionError(f"뒤에서부터 집는다: {ast.unparse(node)}")
    executor = (ROOT / "engine" / "effect" / "executor.py").read_text("utf-8")
    assert "results[-1]" not in executor
    assert "last_result" not in executor


# ======================================================================
# H · I. 없는 결과 · 실패한 결과 (§25 H · I)
# ======================================================================


def test_h_a_result_that_does_not_exist_is_not_zero():
    """
    **0 으로 때우지 않는다.** "아무것도 안 했다" 와 "그 일이 아직
    없다" 는 다른 사실이다.
    """
    values = ExecutionValues()

    with pytest.raises(ExecutionLookupError):
        values.result(ResultRef(0))

    answer = SelectionCount.from_result(ResultRef(0)).resolve(lambda r, z: 9)
    assert answer.outcome is ValueOutcome.UNKNOWN
    assert answer.value is None
    assert answer.missing


def test_h_an_operation_without_a_count_has_no_count(state):
    """
    라이프 증감에는 **장수가 없다.** 없는 것을 0 으로 답하면 뒤의 일이
    "0장을 다뤘다" 고 읽는다.

    **Phase 2-AH 에서 막는 자리가 앞당겨졌다.** 예전에는 실행해 봐야
    알았지만(``UNSUPPORTED_OPERATION``), 어느 종류가 장수를 내는지는
    **정의를 적는 순간** 알 수 있다. 그래서 정의가 만들어지지 않는다 —
    거짓말을 실행 때까지 들고 다니지 않는다.

    이 시험이 지키려던 것("없는 것을 0 으로 답하지 않는다")은 그대로이고,
    더 일찍 지켜진다.
    """
    with pytest.raises(EffectDefinitionError, match="장수를 내지 않습니다"):
        EffectDefinition(
            effect_ref=EffectRef(LAB, 4),
            source_card_id=LAB,
            operations=(
                LifeChangeOperation(delta=1000),
                DrawOperation(count=SelectionCount.from_result(ResultRef(0))),
            ),
            cost=CostGroup(),
            provenance=EffectProvenance.hand_written(verified=True),
        )

    # 그래도 **값 계층은 여전히 0 을 지어내지 않는다.**
    values = ExecutionValues().with_result(OperationResult(0))
    with pytest.raises(ExecutionLookupError):
        values.result(ResultRef(0))


def test_i_a_failure_in_the_first_operation_stops_the_second(repository):
    """
    §17 — 앞이 막히면 뒤는 **시작하지 않는다.** 그래서 이 실행기에는
    "앞이 성공했는가" 를 뒤에서 물을 순간이 없다.
    """
    state = new_state(repository, opponent_hand=1)
    before, hand = state.state_hash(), hand_ids(state, P2)
    journal = EventJournal()

    result = run(state, chains(first_count=3), journal=journal)

    assert result.status is ResolutionStatus.INVALID_TARGET
    untouched(state, before, hand, result, journal)


def test_i_a_failed_operation_still_leaves_no_result():
    """
    **Phase 2-AD 의 판단은 절반만 맞았다.**

    그때 이 시험은 ``ResultField`` 에 ``affected_count`` 하나뿐이라고
    단언했다. 근거는 "앞이 실패하면 뒤는 시작조차 하지 않으므로 성패는
    언제나 참" 이었고, 그 근거의 **앞부분은 지금도 맞다** — 계획에서
    막힌 조작은 결과를 남기지 않는다.

    틀린 것은 뒷부분이다. ``FAILED`` 는 정말로 생기지 않지만,
    **``UNKNOWN`` 은 생긴다** — 규칙을 다 보지 못한 채 일어난 조작이
    있고, 그 위에 다음 일을 쌓아도 되는지는 다른 질문이다 (Phase 2-AE).

    그래서 이 시험은 **여전히 참인 것**을 단언한다: 실패한 조작은
    결과를 남기지 않고, 성패 어휘에 ``FAILED`` 가 없다.
    """
    # Phase 2-AG 에서 ``not_applied`` 가 늘었다 — 조건이 거짓이라 **하지
    # 않은** 일이 생겼기 때문이다. 그것은 실패가 아니고, ``FAILED`` 는
    # 여전히 없다. 이 시험이 지키려는 것이 그것이다.
    assert "failed" not in [o.value for o in OperationOutcome]
    assert [o.value for o in OperationOutcome] == [
        "succeeded",
        "not_applied",
        "unknown",
    ]
    # Phase 2-AF 에서 ``attempted_count`` 가 늘었다 — **하려고 한 수와 실제로
    # 한 수는 다른 질문**이기 때문이다. 여기서 세는 이유는 칸이 조용히
    # 늘어나는 것을 막기 위해서이므로, 늘어난 것을 적어 두고 계속 센다.
    assert set(f.value for f in ResultField) == {
        "attempted_count",
        "affected_count",
        "succeeded",
    }


# ======================================================================
# J · K. 선언과 무작위는 다른 것이다 (§25 J · K · §14)
# ======================================================================


def test_j_declaring_a_number_consumes_no_randomness(state):
    """
    §14 — 사람이 고르는 데 게임 난수를 쓰지 않는다.
    """
    values = ExecutionValues(declarations=(DeclaredNumber(DECLARED_NUMBER, 2),))

    values.declared(DECLARED_NUMBER)
    SelectionCount.from_declaration(DECLARED_NUMBER).resolve(lambda r, z: 0, values)

    assert state.randomness.draws == 0


def test_j_a_refused_declaration_consumes_no_randomness(state):
    """허용되지 않은 수를 선언해도 난수원은 그대로다."""
    run(state, declares(), [DeclaredNumber(DECLARED_NUMBER, 4)])
    assert state.randomness.draws == 0

    run(state, declares())  # 선언하지 않음
    assert state.randomness.draws == 0


def test_j_the_execution_layer_knows_nothing_about_randomness():
    """코드에서도 그렇다."""
    tree = ast.parse((ROOT / "engine" / "execution.py").read_text("utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"RandomSource", "randomness", "choose", "choose_many"}
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "engine.randomness" not in imported
    assert "engine.state.game_state" not in imported


def test_k_random_selection_still_behaves_as_before(repository):
    """
    Phase 2-AB 의 결정론이 그대로다. 선언한 수가 **몇 장인지**를
    정해도, **어느 카드인지**는 여전히 난수원이 정한다.
    """
    picks = []
    for _ in range(2):
        game = new_state(repository, seed=21)
        picks.append(
            run(game, declares(), [DeclaredNumber(DECLARED_NUMBER, 2)])
            .applied[0]
            .instances
        )
    assert picks[0] == picks[1]

    seen = set()
    for seed in range(1, 8):
        game = new_state(repository, seed=seed)
        result = run(game, declares(), [DeclaredNumber(DECLARED_NUMBER, 2)])
        seen.add(tuple(result.applied[0].instances))
    assert len(seen) > 1


# ======================================================================
# L · M. 복제 · 실패 안전성 (§25 L · M · §16 · §17)
# ======================================================================


def test_l_a_declaration_in_one_execution_never_reaches_another(repository):
    """
    §16 — 실행 중의 값은 판에 붙어 있지 않으므로, 복제본에서 선언해도
    원본에는 아무것도 생기지 않는다.
    """
    original = new_state(repository, seed=33)
    copy = original.clone()

    run(copy, declares(), [DeclaredNumber(DECLARED_NUMBER, 2)])

    assert original.randomness.draws == 0
    assert len(original.player(P2).hand) == 4
    assert len(copy.player(P2).hand) == 2

    # 원본에서 다시 돌려도 **복제본의 선언을 물려받지 않는다.**
    again = run(original, declares())
    assert again.status is ResolutionStatus.INVALID_TARGET


def test_m_a_failure_after_the_declaration_leaves_the_board_alone(state):
    """
    선언은 받았고 앞의 일도 계획됐지만 뒤가 막힌다. 계획이 전부 끝난
    뒤에야 적용이 시작되므로 부분 적용이 없다.
    """
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 5),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.at_random(
                opponent_hand_spec(SelectionCount.from_declaration(DECLARED_NUMBER))
            )
        ),
        declarations=(
            DeclarationBinding(
                DECLARED_NUMBER,
                DeclaredNumberSpec(NumberDomain.between(1, 3)),
            ),
        ),
        operations=(
            CardOperation.send_to_grave(PRIMARY_TARGET),
            DrawOperation(count=99),  # 덱보다 많다
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True),
    )
    before, hand = state.state_hash(), hand_ids(state, P2)
    journal = EventJournal()

    result = run(state, definition, [DeclaredNumber(DECLARED_NUMBER, 2)], journal)

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert result.applied == ()
    assert result.deltas == ()
    assert state.state_hash() == before
    assert hand_ids(state, P2) == hand
    assert len(journal) == 0
    # 난수는 이미 꺼냈다. 감추지 않는다 (Phase 2-AB 와 같다).
    assert state.randomness.draws == 2


def test_m_a_forbidden_effect_never_reaches_the_declaration(state):
    """
    §6 — ``FORBIDDEN`` 은 선언의 상태가 아니다. 출처 검사가 **가장
    먼저** 답하므로 (ADR-004), 수를 물어볼 자리까지 오지 않는다.
    """
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 6),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.at_random(
                opponent_hand_spec(SelectionCount.from_declaration(DECLARED_NUMBER))
            )
        ),
        declarations=(
            DeclarationBinding(
                DECLARED_NUMBER, DeclaredNumberSpec(NumberDomain.exact(2))
            ),
        ),
        operations=(CardOperation.send_to_grave(PRIMARY_TARGET),),
        cost=CostGroup(),
        provenance=EffectProvenance.text_derived("텍스트에서 유추"),
    )
    before, hand = state.state_hash(), hand_ids(state, P2)

    # 허용된 수를 제대로 선언해도 마찬가지다.
    result = run(state, definition, [DeclaredNumber(DECLARED_NUMBER, 2)])

    assert result.status is ResolutionStatus.FORBIDDEN
    assert [o.value for o in DeclarationOutcome] == ["resolved", "pending", "invalid"]
    untouched(state, before, hand, result)


# ======================================================================
# N · O · P. 숨은 정보 · 저널 · 해시 (§25 N · O · P)
# ======================================================================


def test_n_declaring_a_number_reveals_no_card(state):
    """
    §13 — 수를 선언하는 것과 패를 공개하는 것은 다른 일이다.
    """
    hidden = [card.card_id for card in state.player(P2).hand]

    result = run(state, declares(), [DeclaredNumber(DECLARED_NUMBER, 1)])

    view = GameStateView.from_state(state, viewer=P1)
    assert view.player(P2).zone(Zone.HAND).concealed is True
    assert view.player(P2).zone(Zone.HAND).cards == ()

    moved = result.applied[0].instances
    remaining = [
        card_id
        for card_id in hidden
        if card_id not in {state.find_instance(i).card_id for i in moved}
    ]
    rendered = repr(result.to_dict())
    for card_id in remaining:
        assert str(card_id) not in rendered


def test_o_the_journal_records_the_move_not_the_declaration(state):
    journal = EventJournal()

    run(state, declares(), [DeclaredNumber(DECLARED_NUMBER, 2)], journal)

    assert len(journal) == 1
    rendered = repr(journal.to_dict() if hasattr(journal, "to_dict") else list(journal))
    for word in ("declared", "declaration", "affected_count"):
        assert word not in rendered


def test_o_a_result_reference_never_reads_the_journal():
    """
    §11 — 저널은 **역사**이고 실행 문맥은 **지금 해결의 중간 결과**다.
    역사를 뒤져 수를 짐작하면 같은 효과가 두 번 돌았을 때 어느 것을
    읽었는지 알 수 없다.
    """
    tree = ast.parse((ROOT / "engine" / "execution.py").read_text("utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"EventJournal", "ObservedEvent", "EventReader", "record"}


def test_p_execution_local_values_do_not_move_the_hash(repository):
    """§23 — 실행 중의 값 때문에 해시가 움직이지 않는다."""
    left, right = new_state(repository, seed=6), new_state(repository, seed=6)
    assert left.state_hash() == right.state_hash()

    # 값만 만들어 본다 — 판을 읽지도 바꾸지도 않는다.
    values = ExecutionValues(declarations=(DeclaredNumber(DECLARED_NUMBER, 3),))
    values.with_result(OperationResult(0, 3))
    assert left.state_hash() == right.state_hash()

    # 선언이 실제로 카드를 움직이면 그때 움직인다.
    run(left, declares(), [DeclaredNumber(DECLARED_NUMBER, 1)])
    assert left.state_hash() != right.state_hash()


def test_p_the_values_are_immutable_and_carry_their_history():
    """
    결과가 붙을 때마다 **새 값**이 생긴다. 앞의 값은 그대로 남으므로
    누가 언제 무엇을 읽었는지가 값에 남는다.
    """
    empty = ExecutionValues()
    one = empty.with_result(OperationResult(0, 2))
    two = one.with_result(OperationResult(1, 5))

    assert empty.results == ()
    assert len(one.results) == 1
    assert len(two.results) == 2
    assert two.result(ResultRef(0)) == 2
    assert two.result(ResultRef(1)) == 5


# ======================================================================
# Q. 실제 카드의 모양 (§18 · §21)
# ======================================================================


def test_q_side_effects_has_a_shape_we_can_write_but_not_a_card_we_run():
    """
    **부작용? (30922149)** — "상대는 덱에서 1~3장 드로우하고, 자신은
    그 드로우한 수 x2000 LP 를 회복한다."

    ::

        if ct==2 then ac=Duel.AnnounceNumber(p,1,2)
        else ac=Duel.AnnounceNumber(p,1,2,3) end
        local dr=Duel.Draw(p,ac,REASON_EFFECT)
        ... Duel.Recover(tp,dr*2000,REASON_EFFECT)

    이 카드 한 장에 이번 단계의 두 문제가 **나란히** 있다. 수를 정하는
    것은 컨트롤러가 아니라 **상대**이고, 회복량은 앞선 드로우의
    **결과**에서 나온다.

    모양은 적을 수 있다. 그러나 **등재하지 않았다** — 라이프 증감의
    양이 아직 고정 수만 받기 때문이다. 적을 수 있다는 것과 실행할 수
    있다는 것은 다른 말이고, 그 둘을 섞지 않는 것이 이 시험의 일이다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    declaration = DeclaredNumberSpec(
        NumberDomain.between(1, 3), chooser=PlayerRef.OPPONENT
    )
    draw_count = SelectionCount.from_declaration(DECLARED_NUMBER)
    recover = ResultRef(0, ResultField.AFFECTED_COUNT, multiplier=2000)

    assert declaration.chooser is PlayerRef.OPPONENT
    assert draw_count.kind is CountKind.DECLARED
    values = ExecutionValues(
        declarations=(DeclaredNumber(DECLARED_NUMBER, 3),)
    ).with_result(OperationResult(0, 3))
    assert draw_count.resolve(lambda r, z: 0, values).value == 3
    assert values.result(recover) == 6000

    # 라이프 증감은 아직 고정 수만 받는다 — 그래서 등재하지 않았다.
    assert isinstance(LifeChangeOperation(delta=1000).delta, int)
    assert 30922149 not in {entry.card_id for entry in EFFECT_LIBRARY}
