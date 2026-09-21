"""
Phase 2-V — Operation 계층 통합 검증.

    Effect → EffectExecutor → OPERATION_HANDLERS → GameState → Delta → Event

이 파일이 묻는 것은 "얼마나 많은 일을 구현했는가" 가 아니다.

    **서로 다른 일들이 같은 약속을 지키는가.**

DESTROY · MOVE · SPECIAL_SUMMON · DRAW · CHANGE_LIFE 가 각자 다른 계층을
쓰면서도 성공·실패·기록·사건의 모양이 하나인지 본다.

dispatch 가 하나다
------------------
예전에는 계획이 ``isinstance`` 로, 적용이 ``kind`` 로 갈라져 있었다. 새
일을 더할 때 **한 곳만 고쳐도 조용히 지나가는** 모양이었다. 이제
:data:`OPERATION_HANDLERS` 하나가 두 쪽을 함께 들고 있고,
:data:`SUPPORTED` 도 그 표에서 나온다.

AI 는 없다
----------
대상도 판정도 **테스트가 값으로 준다.**
"""

import ast
import inspect
import pathlib
import textwrap

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.activation import ActivationStatus, EffectActivator
from engine.chain import Chain, ChainResolutionStatus, ChainResolver
from engine.condition import IsMonster
from engine.cost import CandidateSource, ChoiceSpec, CostGroup, Selection
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectProvenance,
)
from engine.effect.delta import CardDrawn, LifeChanged, MonsterSummoned, ZoneMoved
from engine.effect.executor import (
    DESTINATION,
    OPERATION_HANDLERS,
    SUPPORTED,
    UNSUPPORTED_REASON,
    EffectExecutor,
    EffectImplementationRegistry,
    OperationHandler,
)
from engine.effect.journal import EventJournal
from engine.effect.library import (
    MYSTICAL_SPACE_TYPHOON,
    POT_OF_GREED,
    RAIN_OF_MERCY,
    build_executor,
    definition_registry,
    implementation_registry,
)
from engine.effect.operation import (
    CARD_OPERATION_KINDS,
    CardOperation,
    DrawOperation,
    LifeChangeOperation,
    MoveOperation,
    OperationKind,
    SpecialSummonOperation,
    UnimplementedOperation,
)
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.semantics import (
    RULE_GATED,
    DeclaredDestructionRuling,
    DeclaredSummonRuling,
)
from engine.effect.target import PRIMARY_TARGET, TargetBinding, TargetSpec
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.trigger import TimingEvent, TimingPoint
from engine.validation import ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1

FEATHERMAN = 21844576
BURSTINATRIX = 58932615
DARK_HOLE = 53129443
LAB = 2511  # synthetic 정의의 **껍데기**

PRIMARY = PRIMARY_TARGET
GRANTED = ValidationResult.valid("테스트가 발동 타이밍을 허가했다")


# ======================================================================
# 판 · synthetic 정의
# ======================================================================


def new_state(repository) -> GameState:
    """
    p0(MINE) SZONE: 욕망의 항아리 · 은혜의 단비 · 싸이크론 (전부 앞면)
             MZONE: 페더맨 / 묘지: 페더맨 / 패: 페더맨 · 버스트레이디
    p1(THEIRS) SZONE: 블랙홀 (앞면) / MZONE: 페더맨 / 패: 가려짐
    """
    game = GameState.create(
        repository,
        decks=(
            [POT_OF_GREED, RAIN_OF_MERCY, MYSTICAL_SPACE_TYPHOON, FEATHERMAN,
             FEATHERMAN, FEATHERMAN, BURSTINATRIX] + [FEATHERMAN] * 13,
            [DARK_HOLE, FEATHERMAN] + [FEATHERMAN] * 18,
        ),
    )
    game.draw(MINE, 7)
    game.draw(THEIRS, 4)
    for _ in range(3):  # 마법 3장을 앞면으로
        game.move(
            game.player(MINE).hand[0], Zone.SZONE, to_player=MINE,
            position=Position.FACEUP,
        )
    game.move(
        game.player(MINE).hand[0], Zone.MZONE, to_player=MINE,
        position=Position.FACEUP_ATTACK,
    )
    game.move(game.player(MINE).hand[0], Zone.GRAVE, to_player=MINE)
    game.move(
        game.player(THEIRS).hand[0], Zone.SZONE, to_player=THEIRS,
        position=Position.FACEUP,
    )
    game.move(
        game.player(THEIRS).hand[0], Zone.MZONE, to_player=THEIRS,
        position=Position.FACEUP_ATTACK,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def spell(state: GameState, card_id: int) -> InstanceId:
    for card in state.player(MINE).spell_zone:
        if card.card_id == card_id:
            return card.instance_id
    raise AssertionError(f"마법/함정 존에 {card_id} 가 없습니다.")


def my_monster(state: GameState) -> InstanceId:
    return state.player(MINE).monster_zone[0].instance_id


def their_monster(state: GameState) -> InstanceId:
    return state.player(THEIRS).monster_zone[0].instance_id


def their_spell(state: GameState) -> InstanceId:
    return state.player(THEIRS).spell_zone[0].instance_id


def my_grave(state: GameState) -> InstanceId:
    return state.player(MINE).grave[0].instance_id


def my_hand(state: GameState) -> InstanceId:
    return state.player(MINE).hand[0].instance_id


def their_hand(state: GameState) -> InstanceId:
    return state.player(THEIRS).hand[0].instance_id


def synthetic(
    *operations,
    zones=(Zone.MZONE,),
    owner=None,
    require=None,
    ordinal: int = 0,
    provenance: EffectProvenance | None = None,
) -> EffectDefinition:
    """
    **synthetic 정의.** 실제 카드의 의미를 주장하지 않는다 — 출처가
    ``hand_written`` 이라고 적혀 있고, 실행 경로의 모양만 시험한다.
    """
    needs_target = any(operation.target_refs for operation in operations)
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        targets=(
            TargetBinding.single(
                TargetSpec.targeting(
                    ChoiceSpec(
                        source=CandidateSource(
                            zones=frozenset(zones), owner=owner, require=require
                        )
                    )
                )
            )
            if needs_target
            else ()
        ),
        operations=tuple(operations),
        cost=CostGroup(),
        provenance=provenance
        or EffectProvenance.hand_written(verified=True, note="Phase 2-V 시험"),
    )


def run(
    state: GameState,
    definition: EffectDefinition,
    *chosen: InstanceId,
    destruction=None,
    summoning=None,
    journal: EventJournal | None = None,
    registered: bool = True,
    effect_ref: EffectRef | None = None,
):
    executor = EffectExecutor(
        lookup=(
            EffectImplementationRegistry((definition.effect_ref,))
            if registered
            else None
        ),
        journal=journal,
        destruction=destruction,
        summoning=summoning,
    )
    selections = (
        (TargetSelection(PRIMARY, Selection(chosen=tuple(chosen))),) if chosen else ()
    )
    return executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=effect_ref or definition.effect_ref,
            controller=MINE,
            selections=selections,
        ),
    )


def events_of(state: GameState, result, viewer: int = MINE):
    return EventReader(GameStateView.from_state(state, viewer=viewer)).read(
        result, actor=MINE
    )


def confirmed_destroy(*instances: InstanceId) -> DeclaredDestructionRuling:
    """테스트가 명시적으로 선언한 파괴 판정 (Phase 2-M)."""
    return DeclaredDestructionRuling(destructible=frozenset(instances))


def confirmed_summon(*instances: InstanceId) -> DeclaredSummonRuling:
    """테스트가 명시적으로 선언한 소환 판정 (Phase 2-U)."""
    return DeclaredSummonRuling(summonable=frozenset(instances))


# ======================================================================
# A. Operation taxonomy — 표가 유일한 출처다
# ======================================================================


def test_a_supported_is_built_from_the_handler_table():
    """
    목록을 따로 적어 두지 않는다 — 적어 두면 표와 어긋나는 날이 온다.
    """
    assert SUPPORTED == frozenset(OPERATION_HANDLERS)


def test_a_every_handler_has_both_halves():
    """계획만 더하고 수행을 빠뜨릴 수 없다."""
    for kind, handler in OPERATION_HANDLERS.items():
        assert isinstance(handler, OperationHandler), kind
        assert callable(handler.plan), kind
        assert callable(handler.apply), kind
        assert handler.note, kind


def test_a_the_taxonomy_is_exactly_what_is_executable():
    """
    지금 실행할 수 있는 일의 **전부**다. 늘어나면 이 테스트가 깨지고,
    그때 무엇이 늘었는지 여기 적는다.
    """
    assert {kind.value for kind in SUPPORTED} == {
        # 수치
        "draw",
        "change_life",
        # 의미 있는 카드 이동 (Phase 2-L · 2-M)
        "destroy",
        "send_to_grave",
        "banish",
        "release",
        "discard",
        "return_to_hand",
        "return_to_deck",
        # 의미 없는 이동 (Phase 2-L)
        "move",
        # 소환 (Phase 2-U)
        "special_summon",
    }


def test_a_unknown_is_not_executable():
    """표현하지 못한 일은 실행되지 않는다."""
    assert OperationKind.UNKNOWN not in SUPPORTED
    assert OperationKind.UNKNOWN in UNSUPPORTED_REASON


def test_a_each_kind_has_exactly_one_operation_class():
    """
    표를 ``kind`` 로 키잡아도 안전하다 — 종류와 클래스가 1:1 이기 때문이다.
    ``CardOperation`` 은 생성 시점에 자기 종류를 제한한다.
    """
    for kind in OperationKind:
        if kind in CARD_OPERATION_KINDS:
            assert CardOperation(kind, PRIMARY).kind is kind
        else:
            with pytest.raises(ValueError):
                CardOperation(kind, PRIMARY)

    assert DrawOperation(1).kind is OperationKind.DRAW
    assert LifeChangeOperation(delta=1).kind is OperationKind.CHANGE_LIFE
    assert (
        MoveOperation(destination=Zone.GRAVE, target_ref=PRIMARY).kind
        is OperationKind.MOVE
    )
    assert SpecialSummonOperation(PRIMARY).kind is OperationKind.SPECIAL_SUMMON
    assert UnimplementedOperation("x").kind is OperationKind.UNKNOWN


def _code_of(function) -> str:
    """
    함수의 **코드만** 돌려준다. docstring 과 주석은 설명이지 dispatch 가
    아니므로, 거기에 적힌 ``isinstance`` 같은 낱말을 코드로 세지 않는다.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    body = tree.body[0]
    if (
        body.body
        and isinstance(body.body[0], ast.Expr)
        and isinstance(body.body[0].value, ast.Constant)
        and isinstance(body.body[0].value.value, str)
    ):
        body.body = body.body[1:]
    return ast.unparse(tree)


# ======================================================================
# B. Dispatch — 하나의 표가 두 쪽을 든다
# ======================================================================


def test_b_there_is_no_isinstance_chain_left():
    """
    §3 — 거대한 ``if/elif`` 하나로 모든 일을 처리하지 않는다. 더 중요한
    것은 **dispatch 가 둘로 갈라져 있지 않다**는 점이다.
    """
    source = _code_of(EffectExecutor._plan_operation)
    applied = _code_of(EffectExecutor._apply)

    assert "isinstance" not in source
    assert "isinstance" not in applied
    assert "OPERATION_HANDLERS" in source
    assert "OPERATION_HANDLERS" in applied
    # 종류별 분기가 dispatch 함수 안에 남아 있지 않다. 남은 ``if`` 하나는
    # "표에 없다" 는 실패 처리이지 종류별 분기가 아니다.
    assert source.count("if ") <= 1
    assert applied.count("if ") <= 1


def test_b_the_two_sides_cover_the_same_kinds():
    """계획과 적용이 **같은 표**를 본다."""
    planners = {kind: handler.plan for kind, handler in OPERATION_HANDLERS.items()}
    appliers = {kind: handler.apply for kind, handler in OPERATION_HANDLERS.items()}

    assert set(planners) == set(appliers) == SUPPORTED


def test_b_card_movements_share_one_pair():
    """
    파괴 · 보내기 · 버리기 …는 **같은 계획기와 수행기**를 쓴다. 의미는
    ``kind`` 가 들고 다니고, 코드가 갈라지지 않는다 (ADR-002).
    """
    movers = {OperationKind.MOVE} | set(DESTINATION)
    plans = {OPERATION_HANDLERS[kind].plan for kind in movers}
    applies = {OPERATION_HANDLERS[kind].apply for kind in movers}

    assert len(plans) == 1
    assert len(applies) == 1


def test_b_summon_and_numbers_have_their_own_pairs():
    """같은 표를 쓴다고 같은 코드를 쓰는 것은 아니다."""
    distinct = {
        OPERATION_HANDLERS[kind].apply
        for kind in (
            OperationKind.DRAW,
            OperationKind.CHANGE_LIFE,
            OperationKind.SPECIAL_SUMMON,
            OperationKind.DESTROY,
        )
    }

    assert len(distinct) == 4


@requires_official_db
def test_b_an_unsupported_operation_names_what_is_missing(state):
    before = state.state_hash()

    result = run(state, synthetic(UnimplementedOperation("표시 형식 변경")))

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert result.missing
    assert state.state_hash() == before


# ======================================================================
# C. 공통 실행 계약 (§4)
# ======================================================================


def _case(state, name):
    """(정의, 고른 대상, 판정기) — 종류마다 성공하는 한 벌."""
    if name == "draw":
        return synthetic(DrawOperation(1), ordinal=0), (), {}
    if name == "change_life":
        return synthetic(LifeChangeOperation(delta=500), ordinal=1), (), {}
    if name == "destroy":
        target = their_monster(state)
        return (
            synthetic(CardOperation.destroy(PRIMARY), require=IsMonster(), ordinal=2),
            (target,),
            {"destruction": confirmed_destroy(target)},
        )
    if name == "send_to_grave":
        target = their_monster(state)
        return (
            synthetic(
                CardOperation.send_to_grave(PRIMARY), require=IsMonster(), ordinal=3
            ),
            (target,),
            {},
        )
    if name == "move":
        target = my_hand(state)
        return (
            synthetic(
                MoveOperation(destination=Zone.GRAVE, target_ref=PRIMARY),
                zones=(Zone.HAND,),
                ordinal=4,
            ),
            (target,),
            {},
        )
    if name == "special_summon":
        target = my_grave(state)
        return (
            synthetic(
                SpecialSummonOperation(PRIMARY),
                zones=(Zone.GRAVE,),
                require=IsMonster(),
                ordinal=5,
            ),
            (target,),
            {"summoning": confirmed_summon(target)},
        )
    raise AssertionError(name)


SUCCESS_CASES = ["draw", "change_life", "destroy", "send_to_grave", "move", "special_summon"]


@requires_official_db
@pytest.mark.parametrize("name", SUCCESS_CASES)
def test_c_every_operation_keeps_the_success_contract(state, name):
    """
    §4 — 성공하면 ``applied`` 와 ``deltas`` 가 있고 판이 달라진다.
    **일이 달라도 약속은 하나다.**
    """
    definition, chosen, rulings = _case(state, name)
    before = state.state_hash()

    result = run(state, definition, *chosen, **rulings)

    assert result.status is ResolutionStatus.RESOLVED, name
    assert result.applied != (), name
    assert result.deltas != (), name
    assert result.changed_state is True, name
    assert state.state_hash() != before, name


@requires_official_db
@pytest.mark.parametrize("name", SUCCESS_CASES)
def test_c_every_operation_records_what_it_did(state, name):
    definition, chosen, rulings = _case(state, name)

    result = run(state, definition, *chosen, **rulings)
    record = result.applied[0]

    assert record.kind is definition.operations[0].kind, name
    assert record.reason_names == definition.operations[0].reason_names, name


@requires_official_db
@pytest.mark.parametrize("name", SUCCESS_CASES)
def test_c_every_operation_reaches_the_event_pipeline(state, name):
    """§12 — 같은 통로를 쓴다. 새 EventBus 가 없다."""
    definition, chosen, rulings = _case(state, name)

    result = run(state, definition, *chosen, **rulings)
    observed = events_of(state, result)

    assert observed, name
    assert all(event.is_observable for event in observed), name
    assert all(event.event_id for event in observed), name


@requires_official_db
@pytest.mark.parametrize("name", SUCCESS_CASES)
def test_c_every_operation_is_journalled(state, name):
    definition, chosen, rulings = _case(state, name)
    journal = EventJournal()

    run(state, definition, *chosen, journal=journal, **rulings)

    assert len(journal) == 1, name
    assert list(journal)[0].applied[0].kind is definition.operations[0].kind, name


# ======================================================================
# D. DESTROY — Phase 2-M 의미를 유지한다 (§5)
# ======================================================================


@requires_official_db
def test_d_destroy_still_stops_without_a_ruling(state):
    target = their_monster(state)
    before = state.state_hash()

    result = run(
        state, synthetic(CardOperation.destroy(PRIMARY), require=IsMonster()), target
    )

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.unchecked_rules
    assert state.state_hash() == before


@requires_official_db
def test_d_destroy_is_recorded_as_destruction(state):
    target = their_monster(state)

    result = run(
        state,
        synthetic(CardOperation.destroy(PRIMARY), require=IsMonster()),
        target,
        destruction=confirmed_destroy(target),
    )

    assert result.deltas[0].operation is OperationKind.DESTROY
    assert "DESTROY" in result.deltas[0].reason_names
    assert TimingEvent.from_delta(result.deltas[0]).operation is OperationKind.DESTROY


def test_d_the_gate_list_is_unchanged_in_shape():
    """§5 — 관문에 든 것만 판정을 요구한다. 새 규칙을 추측하지 않았다."""
    assert OperationKind.DESTROY in RULE_GATED
    assert OperationKind.SEND_TO_GRAVE not in RULE_GATED
    assert OperationKind.MOVE not in RULE_GATED


# ======================================================================
# E. MOVE — 의미를 주장하지 않는다 (§6)
# ======================================================================


@requires_official_db
@pytest.mark.parametrize(
    "origin, destination, finder",
    [
        (Zone.HAND, Zone.GRAVE, my_hand),
        (Zone.HAND, Zone.DECK, my_hand),
        (Zone.GRAVE, Zone.HAND, my_grave),
    ],
)
def test_e_move_still_supports_the_same_three_paths(
    state, origin, destination, finder
):
    target = finder(state)
    definition = synthetic(
        MoveOperation(destination=destination, target_ref=PRIMARY), zones=(origin,)
    )

    result = run(state, definition, target)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(target).zone is destination


@requires_official_db
def test_e_move_claims_no_reason(state):
    """§6 — ``REASON_EFFECT`` 조차 붙이지 않았다."""
    target = my_hand(state)
    definition = synthetic(
        MoveOperation(destination=Zone.GRAVE, target_ref=PRIMARY), zones=(Zone.HAND,)
    )

    result = run(state, definition, target)

    assert result.applied[0].reason_names == ()
    assert result.deltas[0].reason_names == ()


@requires_official_db
def test_e_move_and_destroy_stay_different(state):
    """
    같은 수행기를 쓰면서도 **다른 사건**이다. 의미는 ``kind`` 가 들고
    다닌다 (ADR-002).
    """
    moved, destroyed = my_hand(state), their_monster(state)

    by_move = run(
        state,
        synthetic(
            MoveOperation(destination=Zone.GRAVE, target_ref=PRIMARY),
            zones=(Zone.HAND,),
        ),
        moved,
    )
    by_destroy = run(
        state,
        synthetic(
            CardOperation.destroy(PRIMARY), require=IsMonster(), ordinal=1
        ),
        destroyed,
        destruction=confirmed_destroy(destroyed),
    )

    assert state.locate(moved).zone is state.locate(destroyed).zone is Zone.GRAVE
    assert by_move.deltas[0].operation is OperationKind.MOVE
    assert by_destroy.deltas[0].operation is OperationKind.DESTROY
    assert by_move.deltas[0].reason_names == ()
    assert "DESTROY" in by_destroy.deltas[0].reason_names


# ======================================================================
# F. SPECIAL_SUMMON — Phase 2-U 를 그대로 쓴다 (§7)
# ======================================================================


@requires_official_db
def test_f_special_summon_still_stops_without_a_ruling(state):
    target = my_grave(state)
    before = state.state_hash()

    result = run(
        state,
        synthetic(
            SpecialSummonOperation(PRIMARY), zones=(Zone.GRAVE,), require=IsMonster()
        ),
        target,
    )

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert state.state_hash() == before


@requires_official_db
def test_f_special_summon_makes_a_summon_event_not_a_move(state):
    target = my_grave(state)

    result = run(
        state,
        synthetic(
            SpecialSummonOperation(PRIMARY), zones=(Zone.GRAVE,), require=IsMonster()
        ),
        target,
        summoning=confirmed_summon(target),
    )

    assert isinstance(result.deltas[0], MonsterSummoned)
    assert not isinstance(result.deltas[0], ZoneMoved)
    assert events_of(state, result)[0].timing.point is TimingPoint.MONSTER_SUMMONED


def test_f_no_second_summon_executor_was_built():
    """§7 — Phase 2-U 의 절차를 그대로 부른다."""
    source = pathlib.Path("engine/effect/executor.py").read_text("utf-8")
    tree = ast.parse(source)
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}

    assert "SpecialSummonExecutor" not in defined
    assert "SummonProcedure" not in defined
    assert "SPECIAL_SUMMON_PROCEDURE" in source


# ======================================================================
# G. DRAW / CHANGE_LIFE — 이미 있던 것을 확인만 한다 (§8)
# ======================================================================


@requires_official_db
def test_g_draw_uses_the_existing_primitive(state):
    hand_before = len(state.player(MINE).hand)

    result = run(state, synthetic(DrawOperation(2)))

    assert len(state.player(MINE).hand) == hand_before + 2
    assert all(isinstance(delta, CardDrawn) for delta in result.deltas)
    assert result.applied[0].amount == 2


@requires_official_db
def test_g_a_draw_bigger_than_the_deck_draws_nothing(state):
    """있는 만큼만 뽑아 놓고 성공처럼 끝내지 않는다."""
    before = state.state_hash()

    result = run(state, synthetic(DrawOperation(99)))

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_g_life_change_uses_the_existing_primitive(state):
    before = state.player(MINE).life_points

    result = run(state, synthetic(LifeChangeOperation(delta=-800)))

    assert state.player(MINE).life_points == before - 800
    assert isinstance(result.deltas[0], LifeChanged)


def test_g_no_new_engine_was_designed():
    """§8 — ``DrawEngine`` · ``LifePointEngine`` · ``DamageEngine`` 없음."""
    for path in pathlib.Path("engine").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        defined = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        }
        for forbidden in ("DrawEngine", "LifePointEngine", "DamageEngine", "EffectEngine", "OperationEngine"):
            assert forbidden not in defined, path


# ======================================================================
# H. 실제 카드 end-to-end (§13 · §17)
# ======================================================================


def real_definition(card_id: int) -> EffectDefinition:
    found = definition_registry().definition_for(EffectRef(card_id, 0))
    assert found is not None
    return found


def activate_real(
    state: GameState, card_id: int, *chosen: InstanceId
):
    """발동 → 체인 → 해결. **기존 경로를 우회하지 않는다.**"""
    registry = definition_registry()
    activator = EffectActivator(registry, implementation_registry())
    selections = (
        (TargetSelection(PRIMARY, Selection.of(*chosen)),) if chosen else ()
    )
    activated = activator.activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=spell(state, card_id), effect_ref=EffectRef(card_id, 0)
        ),
        selections,
        authorization=GRANTED,
    )
    resolved = ChainResolver(build_executor(), registry).resolve_top(
        state, activated.chain
    )
    return activated, resolved


@requires_official_db
def test_h_pot_of_greed_runs_the_draw_path(state):
    """실제 카드 1 — DRAW."""
    hand_before = len(state.player(MINE).hand)

    activated, resolved = activate_real(state, POT_OF_GREED)

    assert activated.status is ActivationStatus.ACTIVATED
    assert resolved.status is ChainResolutionStatus.RESOLVED
    assert resolved.result.applied[0].kind is OperationKind.DRAW
    assert len(state.player(MINE).hand) == hand_before + 2
    assert [e.timing.point for e in events_of(state, resolved.result)] == [
        TimingPoint.CARD_DRAWN,
        TimingPoint.CARD_DRAWN,
    ]


@requires_official_db
def test_h_rain_of_mercy_runs_the_life_path(state):
    """실제 카드 2 — CHANGE_LIFE. 두 개의 일, 두 개의 변화."""
    before = (state.player(MINE).life_points, state.player(THEIRS).life_points)

    activated, resolved = activate_real(state, RAIN_OF_MERCY)

    assert activated.status is ActivationStatus.ACTIVATED
    assert resolved.status is ChainResolutionStatus.RESOLVED
    assert [a.kind for a in resolved.result.applied] == [
        OperationKind.CHANGE_LIFE,
        OperationKind.CHANGE_LIFE,
    ]
    assert (state.player(MINE).life_points, state.player(THEIRS).life_points) == (
        before[0] + 1000,
        before[1] + 1000,
    )


@requires_official_db
def test_h_the_typhoon_runs_the_destroy_path_and_stops_at_the_gate(state):
    """
    실제 카드 3 — DESTROY. **발동은 되고 해결은 관문에서 멈춘다.**
    실제 카드의 파괴 재정을 지어내지 않는다 (Phase 2-O).
    """
    target = their_spell(state)
    before = state.state_hash()

    activated, resolved = activate_real(state, MYSTICAL_SPACE_TYPHOON, target)

    assert activated.status is ActivationStatus.ACTIVATED
    assert resolved.result.status is ResolutionStatus.UNCHECKED_RULES
    assert state.locate(target).zone is Zone.SZONE
    assert state.state_hash() == before


@requires_official_db
def test_h_three_real_cards_take_three_different_paths(state):
    """
    §17 — 서로 다른 operation path 가 **같은 실행기**를 지난다.
    """
    paths = []
    for card_id, chosen in (
        (POT_OF_GREED, ()),
        (RAIN_OF_MERCY, ()),
        (MYSTICAL_SPACE_TYPHOON, (their_spell(state),)),
    ):
        _, resolved = activate_real(state, card_id, *chosen)
        definition = real_definition(card_id)
        paths.append(definition.operations[0].kind)

    assert paths == [
        OperationKind.DRAW,
        OperationKind.CHANGE_LIFE,
        OperationKind.DESTROY,
    ]
    assert len(set(OPERATION_HANDLERS[kind].apply for kind in paths)) == 3


def test_h_no_real_card_uses_move_or_special_summon_yet():
    """
    §13 의 정직한 결과: MOVE 는 **설계상** 실제 카드가 될 수 없고
    (``LibraryEntry`` 가 거부한다), 특수 소환은 소환 조건 계층이 없어서
    아직 실행 가능한 카드가 없다 (Phase 2-U · STRUCTURAL-64).
    """
    from engine.effect.library import EFFECT_LIBRARY

    executable = [entry for entry in EFFECT_LIBRARY if entry.executable]
    kinds = {
        operation.kind
        for entry in executable
        for operation in entry.definition.operations
    }

    assert kinds == {
        OperationKind.DRAW,
        OperationKind.CHANGE_LIFE,
        OperationKind.DESTROY,
    }
    assert OperationKind.MOVE not in kinds
    assert OperationKind.SPECIAL_SUMMON not in kinds


# ======================================================================
# I. 실패 행렬 (§14)
# ======================================================================


@requires_official_db
def test_i_every_failure_leaves_the_board_alone(state):
    """
    열한 갈래를 한 자리에서 돌린다. 전부 ``applied == ()`` ·
    ``deltas == ()`` · ``state_hash`` 불변.
    """
    destroy = lambda ordinal=0: synthetic(
        CardOperation.destroy(PRIMARY), require=IsMonster(), ordinal=ordinal
    )

    cases = {
        "부적법한 대상": lambda: run(
            state,
            synthetic(
                CardOperation.destroy(PRIMARY),
                zones=(Zone.MZONE,),
                owner=None,
                require=IsMonster(),
            ),
            my_hand(state),
            destruction=confirmed_destroy(my_hand(state)),
        ),
        "모르는 대상": lambda: run(
            state,
            synthetic(
                CardOperation.send_to_grave(PRIMARY),
                zones=(Zone.HAND,),
                owner=None,
                require=IsMonster(),
            ),
            their_hand(state),
        ),
        "없는 카드": lambda: run(state, destroy(), InstanceId(9999)),
        "못 하는 일": lambda: run(state, synthetic(UnimplementedOperation("무효화"))),
        "TEXT_DERIVED": lambda: run(
            state,
            synthetic(
                DrawOperation(1), provenance=EffectProvenance.text_derived("유추")
            ),
        ),
        "구현 없음": lambda: run(state, synthetic(DrawOperation(1)), registered=False),
        "파괴 규칙 미상": lambda: run(state, destroy(), their_monster(state)),
        "소환 규칙 미상": lambda: run(
            state,
            synthetic(
                SpecialSummonOperation(PRIMARY),
                zones=(Zone.GRAVE,),
                require=IsMonster(),
            ),
            my_grave(state),
        ),
        "출발 자리 어긋남": lambda: run(
            state,
            synthetic(
                CardOperation.discard(PRIMARY), zones=(Zone.MZONE,), require=IsMonster()
            ),
            my_monster(state),
        ),
        "다른 효과의 문맥": lambda: run(
            state,
            synthetic(DrawOperation(1)),
            effect_ref=EffectRef(POT_OF_GREED, 0),
        ),
    }

    answers = {name: _expect_failure(state, name, case) for name, case in cases.items()}
    # 열한째 갈래는 **판을 미리 흔들어 둔 뒤**에야 잴 수 있다 (아래 참고).
    answers["떠난 대상"] = _stale(state)

    assert len(answers) == 11

    # 열한 갈래가 **여덟** 답으로 갈린다. 겹치는 두 쌍은 겹치는 것이 맞다:
    #
    # * "없는 카드" 와 "모르는 대상" — 관측 경계 밖의 카드는 *없는 것*과
    #   *안 보이는 것*을 구분할 수 없다. 구분하면 숨은 정보가 샌다 (§16).
    # * "떠난 대상" 과 "부적법한 대상" — 자리를 떠난 카드는 더 이상 후보가
    #   아니다. 둘 다 "고른 것이 후보가 아니다" 라는 같은 사실이다.
    #
    # 나머지 아홉은 서로 다른 답이어야 한다. 뭉개지면 이 단언이 깨진다.
    assert len(set(answers.values())) == 8
    assert len({status for status, _ in answers.values()}) == 7
    assert answers["없는 카드"] == answers["모르는 대상"]
    assert answers["떠난 대상"] == answers["부적법한 대상"]


def _expect_failure(state: GameState, name: str, invoke) -> tuple:
    """실행기가 실패했고, 판은 부른 그 순간 그대로다."""
    before = state.state_hash()
    result = invoke()
    assert result.status is not ResolutionStatus.RESOLVED, name
    assert result.applied == (), name
    assert result.deltas == (), name
    assert state.state_hash() == before, name
    return result.status, result.code


def _stale(state: GameState) -> tuple:
    """
    고른 뒤 그 카드가 자리를 떠났다.

    카드를 옮기는 것은 **이 갈래의 준비**이지 실행기의 일이 아니다. 그래서
    판을 재는 자는 이동을 마친 뒤에 찍는다. 되돌리는 이동도 마찬가지로
    실행기 밖이며, ``GameState.move`` 는 ``PreviousState`` 를 남기므로
    왕복이 원래 해시로 돌아오지는 않는다 — 뒤 갈래들이 필요로 하는 것은
    "묘지에 몬스터가 있다" 뿐이다.
    """
    target = my_grave(state)
    state.move(target, Zone.REMOVED, to_player=MINE)
    try:
        return _expect_failure(
            state,
            "떠난 대상",
            lambda: run(
                state,
                synthetic(
                    SpecialSummonOperation(PRIMARY),
                    zones=(Zone.GRAVE,),
                    require=IsMonster(),
                ),
                target,
                summoning=confirmed_summon(target),
            ),
        )
    finally:
        state.move(target, Zone.GRAVE, to_player=MINE)


@requires_official_db
def test_i_an_earlier_operation_is_cancelled_with_the_later_one(state):
    """
    §14 — 새 rollback 을 만들지 않았다. 계획이 **전부** 끝난 뒤에야 적용이
    시작되므로, 뒤의 일이 막히면 앞의 일도 일어나지 않는다.
    """
    definition = synthetic(
        DrawOperation(1),
        CardOperation.destroy(PRIMARY),
        require=IsMonster(),
    )
    hand_before = len(state.player(MINE).hand)
    before = state.state_hash()

    result = run(state, definition, their_monster(state))  # 판정기 없음

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert len(state.player(MINE).hand) == hand_before
    assert state.state_hash() == before


# ======================================================================
# J. 결정론 · 복제 · 정보 경계 (§15 · §16)
# ======================================================================


@requires_official_db
@pytest.mark.parametrize("name", SUCCESS_CASES)
def test_j_every_operation_is_deterministic(repository, name):
    first, second = new_state(repository), new_state(repository)

    left_def, left_chosen, left_rules = _case(first, name)
    right_def, right_chosen, right_rules = _case(second, name)

    left = run(first, left_def, *left_chosen, **left_rules)
    right = run(second, right_def, *right_chosen, **right_rules)

    assert left.canonical_state() == right.canonical_state(), name
    assert first.state_hash() == second.state_hash(), name


@requires_official_db
@pytest.mark.parametrize("name", SUCCESS_CASES)
def test_j_every_event_id_comes_from_the_content(repository, name):
    first, second = new_state(repository), new_state(repository)
    left_def, left_chosen, left_rules = _case(first, name)
    right_def, right_chosen, right_rules = _case(second, name)

    left = events_of(first, run(first, left_def, *left_chosen, **left_rules))
    right = events_of(second, run(second, right_def, *right_chosen, **right_rules))

    assert [e.event_id for e in left] == [e.event_id for e in right], name


@requires_official_db
@pytest.mark.parametrize("name", SUCCESS_CASES)
def test_j_running_on_a_clone_leaves_the_original_alone(state, name):
    copy = state.clone()
    definition, chosen, rulings = _case(copy, name)
    before = state.state_hash()

    result = run(copy, definition, *chosen, **rulings)

    assert result.status is ResolutionStatus.RESOLVED, name
    assert copy.state_hash() != before, name
    assert state.state_hash() == before, name


@requires_official_db
def test_j_a_refusal_names_no_hidden_card(state):
    """§16 — ``UNKNOWN`` 이 card_id 를 공개하는 우회가 없어야 한다."""
    hidden = state.player(THEIRS).hand[0]

    result = run(
        state,
        synthetic(
            CardOperation.send_to_grave(PRIMARY),
            zones=(Zone.HAND,),
            owner=None,
            require=IsMonster(),
        ),
        hidden.instance_id,
    )
    text = str(result.to_dict())

    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert str(hidden.card_id) not in text


@requires_official_db
def test_j_the_observation_boundary_is_the_actors(state):
    """관측은 행위자의 시점으로만 만든다."""
    tree = ast.parse(pathlib.Path("engine/effect/executor.py").read_text("utf-8"))
    viewers = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg == "viewer"
    ]

    assert viewers
    for value in viewers:
        assert isinstance(value, ast.Attribute), ast.dump(value)
        assert value.attr == "controller", ast.dump(value)


# ======================================================================
# K. 경계 (§9 · §11 · §18)
# ======================================================================


def test_k_operation_and_player_action_stay_apart():
    """§9 — ADR-001 의 경계를 유지한다."""
    assert OperationKind.SPECIAL_SUMMON is not PlayerActionKind.SPECIAL_SUMMON
    assert type(OperationKind.SPECIAL_SUMMON) is not type(
        PlayerActionKind.SPECIAL_SUMMON
    )


def test_k_the_executor_never_calls_the_flow_layers():
    """§11 — 체인 · 응답 · 우선권 · 트리거를 부르지 않는다."""
    tree = ast.parse(pathlib.Path("engine/effect/executor.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    for module in (
        "engine.chain",
        "engine.trigger",
        "engine.trigger_chain",
        "engine.response",
        "engine.priority",
        "engine.event_pipeline",
    ):
        assert module not in imported
    for name in (
        "ChainResolver",
        "ResponseLoop",
        "PriorityResolver",
        "TriggerCollector",
        "TriggerChainIntegrator",
    ):
        assert name not in used


def test_k_no_duplicate_execution_architecture():
    """§18 — 새 EventBus · Chain · EffectEngine 이 없다."""
    for path in pathlib.Path("engine").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        defined = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        }
        assert not any("Bus" in name for name in defined), path
        assert sum(name == "EffectExecutor" for name in defined) <= 1, path


def test_k_the_executor_makes_no_choice_of_its_own():
    """§10 — 실행기가 임의로 대상을 고르지 않는다."""
    source = pathlib.Path("engine/effect/executor.py").read_text("utf-8")
    tree = ast.parse(source)
    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for forbidden in ("choose", "select_", "score", "policy"):
        assert not any(forbidden in name for name in functions)
    assert "random" not in source
