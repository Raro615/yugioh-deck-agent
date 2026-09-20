"""
Phase 2-R — 체인 응답 루프 (Chain Response / Priority Loop).

    Chain [L1] + PriorityState(RESPONSE, P1)
        ↓  ResponseLoop.act(...)
        ├ PASS             우선권만 넘어간다
        └ ACTIVATE_EFFECT  EffectActivator (2-Q) → Chain [L1, L2]
        ↓  둘 다 연속 패스
    ResponseLoop.resolve(..., ChainResolver)  →  L2 → L1 (LIFO)

이 파일이 지키려는 것은 둘이다.

1. **응답 ≠ 트리거.** 하나의 사건 때문에 동시에 후보가 되는 것과, 이미 쌓인
   체인에 우선권을 쥔 사람이 하나를 더 얹는 것은 다른 개념이다.
2. **차례가 값으로 표현된다.** "지금 누가 체인에 무엇을 더할 차례인가" 가
   ``ResponseState`` 하나로 읽힌다.

AI 는 없다
----------
PASS 도 발동도 **테스트가 값으로 준다.** 무엇을 해야 하는가는 이 계층의
질문이 아니다.
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.activation import ActivationStatus, EffectActivator
from engine.chain import Chain, ChainLink, ChainResolutionStatus, ChainResolver
from engine.condition import Always, IsMonster
from engine.cost import CandidateSource, ChoiceSpec, CostGroup, LifeCost, Selection
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectProvenance,
)
from engine.effect.delta import CardDrawn
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.operation import CardOperation, DrawOperation
from engine.effect.resolution import ResolutionStatus, TargetSelection
from engine.effect.semantics import DeclaredDestructionRuling
from engine.effect.target import PRIMARY_TARGET, TargetBinding, TargetSpec
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.priority import PriorityHolder, PriorityState, ResponseWindow
from engine.response import (
    AFTER_CHAIN_RULE,
    RESPONDABLE,
    ResponseError,
    ResponseLoop,
    ResponseOutcome,
    ResponseResult,
    ResponseState,
    ResponseStep,
)
from engine.state.game_state import GameState
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
)
from engine.trigger_chain import TriggerChainIntegrator
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

A_SEAT, B_SEAT = 0, 1  # A = 턴 플레이어, B = 상대

FEATHERMAN = 21844576
DARK_HOLE = 53129443  # A 의 패에만 있는 카드 — 정보 경계 시험용
QUICKPLAY = 5318639  # 싸이크론 — 속공 마법. 발동하는 카드의 **종류**만 쓴다
LAB = 2511  # synthetic 정의의 **껍데기**. 이 카드의 의미를 주장하지 않는다
ALPHA, BETA = 1000, 1001  # 트리거 시험용 synthetic 카드 번호

PRIMARY = PRIMARY_TARGET

#: 판 없이 링크의 **모양**만 볼 때 쓰는 자리표시. 어떤 카드도 가리키지 않는다.
SOME_CARD = InstanceId(7)

#: **테스트가 명시적으로 건네는 발동 허가.** 발동 타이밍 계층을 대신하지
#: 않는다 (Phase 2-Q 와 같은 자리).
GRANTED = ValidationResult.valid("테스트가 발동 타이밍을 허가했다")


# ======================================================================
# 판 · synthetic 정의
# ======================================================================


def new_state(repository) -> GameState:
    """
    p0(A) 몬스터 1장 · 패 3장, p1(B) 몬스터 1장 · 패 3장.

    양쪽이 똑같이 생긴 이유는 A 와 B 가 **같은 모양의 응답**을 할 수 있어야
    하기 때문이다.
    """
    game = GameState.create(
        repository,
        # 발동하는 카드는 **속공 마법**이다 — 응답 루프가 성립하려면 응수하는
        # 카드가 실제로 응수할 수 있는 종류여야 한다 (Phase 2-S 의 스펠
        # 스피드 관문). A 의 패에는 **필드 어디에도 없는** 카드가 섞여
        # 있다: 정보 경계를 시험하려면 새어 나올 번호가 유일해야 한다.
        decks=(
            [FEATHERMAN, QUICKPLAY] + [DARK_HOLE] * 18,
            [FEATHERMAN, QUICKPLAY] + [FEATHERMAN] * 18,
        ),
    )
    game.draw(A_SEAT, 4)
    game.draw(B_SEAT, 4)
    for seat in (A_SEAT, B_SEAT):
        game.move(
            game.player(seat).hand[0], Zone.MZONE, to_player=seat,
            position=Position.FACEUP_ATTACK,
        )
        # 발동할 속공 마법은 **앞면으로** 놓는다. 뒷면이면 상대가 그 링크의
        # 스펠 스피드를 판정할 수 없고, 그것은 다른 시험이다.
        game.move(
            game.player(seat).hand[0], Zone.SZONE, to_player=seat,
            position=Position.FACEUP,
        )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def a_monster(state: GameState) -> InstanceId:
    return state.player(A_SEAT).monster_zone[0].instance_id


def b_monster(state: GameState) -> InstanceId:
    return state.player(B_SEAT).monster_zone[0].instance_id


def a_card(state: GameState) -> InstanceId:
    """A 가 발동에 쓰는 카드 — 필드의 **앞면 속공 마법**."""
    return state.player(A_SEAT).spell_zone[0].instance_id


def b_card(state: GameState) -> InstanceId:
    """B 가 응수에 쓰는 카드 — 필드의 **앞면 속공 마법**."""
    return state.player(B_SEAT).spell_zone[0].instance_id


def destroy_effect(ordinal: int, *, cost: CostGroup | None = None) -> EffectDefinition:
    """
    **synthetic 정의.** "필드의 몬스터 1장을 대상으로 파괴한다" 의 모양만
    만든다 — 어떤 실제 카드의 의미도 주장하지 않는다.
    """
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.targeting(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=frozenset({Zone.MZONE}), owner=None, require=IsMonster()
                    )
                )
            )
        ),
        operations=(CardOperation.destroy(PRIMARY),),
        cost=cost or CostGroup(),
        provenance=EffectProvenance.hand_written(
            verified=True, note="Phase 2-R 응답 루프 시험"
        ),
    )


EFFECT_X = EffectRef(LAB, 0)  # A 가 발동할 효과
EFFECT_Y = EffectRef(LAB, 1)  # B 가 응답으로 발동할 효과


def definitions(*extra: EffectDefinition) -> EffectDefinitionRegistry:
    return EffectDefinitionRegistry(
        extra or (destroy_effect(0), destroy_effect(1))
    )


def loop(registry: EffectDefinitionRegistry | None = None, **kwargs) -> ResponseLoop:
    held = registry if registry is not None else definitions()
    refs = tuple(
        EffectRef(LAB, ordinal) for ordinal in (0, 1)
    )
    return ResponseLoop(
        EffectActivator(held, EffectImplementationRegistry(refs), **kwargs)
    )


def opened(chain: Chain = Chain(), holder: int = A_SEAT) -> ResponseState:
    return ResponseLoop.opened(
        chain, PriorityHolder.of(holder), turn_player=A_SEAT, phase=Phase.MAIN1
    )


def activate(
    actor: int, source: InstanceId, effect_ref: EffectRef
) -> PlayerAction:
    return PlayerAction.activate_effect(
        actor=actor, source=source, effect_ref=effect_ref
    )


def picked(*instances: InstanceId) -> tuple[TargetSelection, ...]:
    """테스트가 **값으로** 주는 대상. 엔진이 고르지 않는다."""
    return (TargetSelection(PRIMARY, Selection.of(*instances)),)


def chain_resolver(
    registry: EffectDefinitionRegistry | None = None, *, destructible=()
) -> ChainResolver:
    """기존 해결기. **응답 루프가 새로 만들지 않는다.**"""
    held = registry if registry is not None else definitions()
    return ChainResolver(
        EffectExecutor(
            lookup=EffectImplementationRegistry(
                (EffectRef(LAB, 0), EffectRef(LAB, 1))
            ),
            destruction=DeclaredDestructionRuling(destructible=frozenset(destructible)),
        ),
        held,
    )


# ======================================================================
# A. ResponseState — 차례를 값으로 읽는다
# ======================================================================


def test_a_an_empty_chain_has_nothing_to_respond_to():
    assert opened().step is ResponseStep.NO_CHAIN


def test_a_a_standing_chain_awaits_a_response():
    chain = Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=SOME_CARD)

    assert opened(chain, B_SEAT).step is ResponseStep.AWAIT_RESPONSE


def test_a_two_consecutive_passes_mean_resolve():
    chain = Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=SOME_CARD)
    response = opened(chain, B_SEAT)

    after = response.with_priority(response.priority.passed().passed())

    assert after.step is ResponseStep.RESOLVE
    assert after.priority.both_passed is True


def test_a_passing_on_an_empty_chain_does_not_mean_resolve():
    """
    빈 체인에서의 연속 패스는 **다른 뜻**이다 (페이즈 넘김 등). 그 뜻은
    이 계층이 정하지 않는다.
    """
    response = opened()

    after = response.with_priority(response.priority.passed().passed())

    assert after.priority.both_passed is True
    assert after.step is ResponseStep.NO_CHAIN


def test_a_the_state_holds_the_two_values_side_by_side():
    """
    ``Chain`` 에도 ``PriorityState`` 에도 새 칸을 만들지 않았다 — 나란히
    담기만 한다.
    """
    chain = Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=SOME_CARD)
    response = ResponseState(chain, PriorityState.idle(turn_player=A_SEAT))

    assert response.chain is chain
    assert not hasattr(chain, "priority")
    assert not hasattr(response.priority, "chain")


def test_a_the_step_is_derived_not_stored():
    """저장하면 체인·우선권과 어긋날 수 있고, 어긋나면 어느 쪽이 맞는지 모른다."""
    fields = {f for f in ResponseState.__dataclass_fields__}

    assert fields == {"chain", "priority"}
    assert isinstance(ResponseState.step, property)


# ======================================================================
# B. §8 시나리오 — A → B → PASS → PASS → LIFO 해결
# ======================================================================


@requires_official_db
def test_b_the_whole_response_loop_runs_and_resolves_lifo(state):
    """
    A 가 X 를 발동 → B 가 Y 로 응답 → A 패스 → B 패스 → **Y 부터** 해결.
    """
    machine = loop()
    target_of_x, target_of_y = b_monster(state), a_monster(state)
    response = opened()

    # 1. A 가 발동한다.
    first = machine.act(
        state,
        response,
        activate(A_SEAT, a_card(state), EFFECT_X),
        picked(target_of_x),
        authorization=GRANTED,
    )
    assert first.outcome is ResponseOutcome.LINK_ADDED
    assert len(first.chain) == 1
    assert first.priority.holder.is_seat(B_SEAT)  # 우선권이 상대에게
    assert first.state.step is ResponseStep.AWAIT_RESPONSE

    # 2. B 가 응답한다.
    second = machine.act(
        state,
        first.state,
        activate(B_SEAT, b_card(state), EFFECT_Y),
        picked(target_of_y),
        authorization=GRANTED,
    )
    assert second.outcome is ResponseOutcome.LINK_ADDED
    assert len(second.chain) == 2
    assert second.priority.holder.is_seat(A_SEAT)  # 다시 A 에게

    # 3. 둘 다 패스한다.
    third = machine.act(state, second.state, PlayerAction.passing(A_SEAT))
    fourth = machine.act(state, third.state, PlayerAction.passing(B_SEAT))

    assert third.outcome is fourth.outcome is ResponseOutcome.PASSED
    assert fourth.state.step is ResponseStep.RESOLVE
    # 아직 아무것도 파괴되지 않았다.
    assert state.locate(target_of_x).zone is Zone.MZONE
    assert state.locate(target_of_y).zone is Zone.MZONE

    # 4. 해결 — **뒤에서부터**.
    done = machine.resolve(
        state,
        fourth.state,
        chain_resolver(destructible=(target_of_x, target_of_y)),
    )

    assert done.permitted.validity is ActionValidity.VALID
    assert [step.status for step in done.steps] == [
        ChainResolutionStatus.RESOLVED,
        ChainResolutionStatus.RESOLVED,
    ]
    # **LIFO** — 체인 2(Y)가 먼저, 체인 1(X)이 나중.
    assert [step.link.effect_ref for step in done.steps] == [EFFECT_Y, EFFECT_X]
    assert done.fully_resolved is True
    assert state.locate(target_of_x).zone is Zone.GRAVE
    assert state.locate(target_of_y).zone is Zone.GRAVE


@requires_official_db
def test_b_the_link_order_is_activation_order_not_resolution_order(state):
    """쌓인 순서는 발동 순서, 푸는 순서는 그 역순이다."""
    machine = loop()
    first = machine.act(
        state,
        opened(),
        activate(A_SEAT, a_card(state), EFFECT_X),
        picked(b_monster(state)),
        authorization=GRANTED,
    )
    second = machine.act(
        state,
        first.state,
        activate(B_SEAT, b_card(state), EFFECT_Y),
        picked(a_monster(state)),
        authorization=GRANTED,
    )

    chain = second.chain

    assert [link.effect_ref for link in chain] == [EFFECT_X, EFFECT_Y]
    assert [link.sequence for link in chain] == [0, 1]
    assert [link.actor for link in chain] == [A_SEAT, B_SEAT]
    assert [link.effect_ref for link in chain.resolution_order] == [
        EFFECT_Y,
        EFFECT_X,
    ]


# ======================================================================
# C. PASS — 효과가 아니다
# ======================================================================


@requires_official_db
def test_c_passing_changes_nothing_but_priority(state):
    """§5 — GameState mutation 과 우선권 전이를 구분한다."""
    chain = Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state))
    response = opened(chain, B_SEAT)
    before = state.state_hash()

    result = loop().act(state, response, PlayerAction.passing(B_SEAT))

    assert result.outcome is ResponseOutcome.PASSED
    assert result.link is None
    assert result.deltas == ()
    assert result.chain is chain  # 체인 내용도 객체도 그대로
    assert state.state_hash() == before
    assert result.priority.holder.is_seat(A_SEAT)  # 우선권만 넘어갔다


@requires_official_db
def test_c_passing_counts_up_and_activating_resets_it(state):
    """연속 패스는 **누가 무엇을 하면** 끊긴다."""
    machine = loop()
    chain = Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state))
    passed = machine.act(state, opened(chain, B_SEAT), PlayerAction.passing(B_SEAT))

    assert passed.priority.consecutive_passes == 1

    acted = machine.act(
        state,
        passed.state,
        activate(A_SEAT, a_card(state), EFFECT_Y),
        picked(b_monster(state)),
        authorization=GRANTED,
    )

    assert acted.priority.consecutive_passes == 0


@requires_official_db
def test_c_a_pass_out_of_turn_is_refused(state):
    """차례가 아닌 사람의 패스는 차례를 넘기지 못한다."""
    response = opened(Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state)), B_SEAT)

    result = loop().act(state, response, PlayerAction.passing(A_SEAT))

    assert result.outcome is ResponseOutcome.REFUSED
    assert result.code is ValidationCode.NOT_PRIORITY_HOLDER
    assert result.priority is response.priority  # 우선권도 그대로


@requires_official_db
def test_c_resolving_before_both_passed_is_refused(state):
    """§9 — 한 명만 패스했으면 아직 풀 때가 아니다."""
    machine = loop()
    chain = Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state))
    passed = machine.act(state, opened(chain, B_SEAT), PlayerAction.passing(B_SEAT))
    before = state.state_hash()

    done = machine.resolve(state, passed.state, chain_resolver())

    assert done.permitted.validity is ActionValidity.INVALID
    assert done.steps == ()
    assert done.started is False
    assert done.state is passed.state
    assert state.state_hash() == before


# ======================================================================
# D. ACTIVATE_EFFECT 응답
# ======================================================================


@requires_official_db
def test_d_a_response_reuses_the_phase_2q_activator(state):
    """§6 — 발동 규칙을 여기서 다시 만들지 않는다."""
    result = loop().act(
        state,
        opened(Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state)), B_SEAT),
        activate(B_SEAT, b_card(state), EFFECT_Y),
        picked(a_monster(state)),
        authorization=GRANTED,
    )

    assert result.activation is not None
    assert result.activation.status is ActivationStatus.ACTIVATED
    assert result.link is result.activation.link


@requires_official_db
def test_d_a_response_cost_is_paid_at_activation_not_at_resolution(state):
    """비용은 응답 시점에 빠져나간다 — 해결은 아직 멀었다."""
    registry = EffectDefinitionRegistry(
        (destroy_effect(0), destroy_effect(1, cost=CostGroup((LifeCost(amount=600),))))
    )
    machine = loop(registry)
    life_before = state.player(B_SEAT).life_points

    result = machine.act(
        state,
        opened(Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state)), B_SEAT),
        activate(B_SEAT, b_card(state), EFFECT_Y),
        picked(a_monster(state)),
        authorization=GRANTED,
    )

    assert result.outcome is ResponseOutcome.LINK_ADDED
    assert state.player(B_SEAT).life_points == life_before - 600
    assert result.deltas  # 비용이 만든 변화
    assert result.link.payments
    assert state.locate(a_monster(state)).zone is Zone.MZONE  # 효과는 아직


@requires_official_db
def test_d_the_response_loop_does_not_execute_effects():
    """§6 — 루프가 ``EffectExecutor`` 도 ``Operation`` 도 부르지 않는다."""
    tree = ast.parse(pathlib.Path("engine/response.py").read_text("utf-8"))
    imported = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert ("engine.effect.executor", "EffectExecutor") not in imported
    assert "EffectExecutor" not in used
    assert "execute" not in used
    assert "CardOperation" not in used


@requires_official_db
def test_d_the_loop_only_knows_pass_and_activate(state):
    """§11 — 그 이상의 행위는 이 루프의 질문이 아니다."""
    response = opened(Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state)), A_SEAT)

    result = loop().act(
        state, response, PlayerAction.normal_summon(actor=A_SEAT, source=a_card(state))
    )

    assert RESPONDABLE == frozenset(
        {PlayerActionKind.ACTIVATE_EFFECT, PlayerActionKind.PASS}
    )
    assert result.outcome is ResponseOutcome.REFUSED
    assert result.missing
    assert result.chain is response.chain


# ======================================================================
# E. 체인 무결성
# ======================================================================


@requires_official_db
def test_e_the_earlier_link_is_untouched_by_the_response(state):
    """§13 — 기존 링크의 효과 · 대상 · 영수증이 그대로다."""
    machine = loop()
    first = machine.act(
        state,
        opened(),
        activate(A_SEAT, a_card(state), EFFECT_X),
        picked(b_monster(state)),
        authorization=GRANTED,
    )
    original = first.chain[0]
    snapshot = original.canonical_state()

    second = machine.act(
        state,
        first.state,
        activate(B_SEAT, b_card(state), EFFECT_Y),
        picked(a_monster(state)),
        authorization=GRANTED,
    )

    assert second.chain[0] is original
    assert second.chain[0].canonical_state() == snapshot
    assert second.chain[0].effect_ref == EFFECT_X
    assert second.chain[0].selections == picked(b_monster(state))
    assert second.chain[0].payments == ()


@requires_official_db
def test_e_the_chain_is_never_mutated_in_place(state):
    """체인은 불변이다 — 응답은 **새 체인**을 돌려준다."""
    chain = Chain()
    response = ResponseState(
        chain,
        PriorityState.opened(
            ResponseWindow.RESPONSE, A_SEAT, turn_player=A_SEAT, phase=Phase.MAIN1
        ),
    )

    result = loop().act(
        state,
        response,
        activate(A_SEAT, a_card(state), EFFECT_X),
        picked(b_monster(state)),
        authorization=GRANTED,
    )

    assert len(chain) == 0
    assert len(result.chain) == 1
    assert result.chain is not chain


@requires_official_db
def test_e_resolution_closes_the_window_instead_of_inventing_a_rule(state):
    """
    🟠 STRUCTURAL-34 — 체인이 끝난 뒤 누구에게 우선권이 가는지 정해지지
    않았다. 지어내는 대신 기회를 **닫는다.**
    """
    machine = loop()
    chain = Chain().activate(
        actor=A_SEAT, effect_ref=EFFECT_X, selections=picked(b_monster(state))
    )
    response = opened(chain, B_SEAT)
    passed = machine.act(state, response, PlayerAction.passing(B_SEAT))
    passed = machine.act(state, passed.state, PlayerAction.passing(A_SEAT))

    done = machine.resolve(
        state, passed.state, chain_resolver(destructible=(b_monster(state),))
    )

    assert done.started is True
    assert done.state.priority.holder is PriorityHolder.NOBODY
    assert done.state.priority.window is ResponseWindow.NONE
    assert done.state.priority.reason == AFTER_CHAIN_RULE


# ======================================================================
# F. 트리거와 응답은 다른 개념이다 (§10)
# ======================================================================


def test_f_test_a_one_event_makes_two_trigger_candidates():
    """
    **Test A — 트리거.** 하나의 사건에서 둘이 **동시에** 후보가 된다.
    누가 고른 것이 아니고, 순서는 순서화 계층이 정한다.
    """
    game = GameState.create(decks=([ALPHA, ALPHA, ALPHA], [BETA, BETA]))
    game.draw(0, 2)
    game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.turn.set_phase(Phase.MAIN1)
    view = GameStateView.from_state(game, viewer=0)

    held = EffectDefinition(
        effect_ref=EffectRef(ALPHA, 0),
        source_card_id=ALPHA,
        operations=(DrawOperation(1),),
        activation=Always(),
        provenance=EffectProvenance.official_lua(),
    )
    integrator = TriggerChainIntegrator(
        view,
        TriggerRegistry(
            (
                TriggerSpec(
                    EffectRef(ALPHA, 0),
                    TimingPoint.CARD_DRAWN,
                    requirement=TriggerRequirement.OPTIONAL,
                    activates_from=frozenset({Zone.MZONE}),
                ),
            )
        ),
        EffectDefinitionRegistry((held,)),
        EffectImplementationRegistry((held.effect_ref,)),
    )
    event = TimingEvent.from_delta(CardDrawn(0, InstanceId(5)))

    ordering = integrator.collect_and_order(event)
    plan = integrator.plan(Chain(), ordering)
    chain = integrator.extend(Chain(), plan)

    # 같은 사건 하나에서 **둘이 동시에** 후보가 되었다.
    assert len(plan.insertable) == 2
    assert len(chain) == 2
    assert {link.effect_ref for link in chain} == {EffectRef(ALPHA, 0)}
    assert len({link.source for link in chain}) == 2  # 서로 다른 인스턴스


@requires_official_db
def test_f_test_b_a_standing_chain_gets_one_response_from_one_player(state):
    """
    **Test B — 응답.** 이미 쌓인 체인에 **우선권을 쥔 한 사람**이 하나를
    얹는다. 사건이 아니라 결정이 이유다.
    """
    chain = Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state))

    result = loop().act(
        state,
        opened(chain, B_SEAT),
        activate(B_SEAT, b_card(state), EFFECT_Y),
        picked(a_monster(state)),
        authorization=GRANTED,
    )

    assert len(result.chain) == 2
    assert result.chain[1].actor == B_SEAT
    assert result.activation is not None  # 결정이 링크가 되었다


def test_f_the_response_loop_never_collects_triggers():
    """
    §2 · §10 — 두 흐름을 하나의 collector 로 합치지 않는다. 합치면 "동시에
    발생한 유발 효과" 와 "체인에 대응한 효과" 를 영영 구분할 수 없다.
    """
    tree = ast.parse(pathlib.Path("engine/response.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    for forbidden in ("engine.trigger", "engine.trigger_chain", "engine.trigger_order"):
        assert forbidden not in imported
    for name in (
        "TriggerCollector",
        "TriggerChainIntegrator",
        "TriggerOrderer",
        "TimingEvent",
    ):
        assert name not in used


def test_f_the_trigger_layer_never_asks_who_has_priority():
    """반대 방향도 막혀 있다 — 트리거는 우선권을 모른다."""
    tree = ast.parse(pathlib.Path("engine/trigger_chain.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "engine.priority" not in imported
    assert "engine.response" not in imported


# ======================================================================
# G. 실패 행렬 — 체인 · 판 불변
# ======================================================================


@requires_official_db
@pytest.mark.parametrize(
    "name, seat, target_of, kind, authorize",
    [
        ("차례가 아님", A_SEAT, "a", "activate", True),
        ("허가 없음", B_SEAT, "a", "activate", False),
        ("부적법한 대상", B_SEAT, "hand", "activate", True),
        ("대상 없음", B_SEAT, None, "activate", True),
        ("발동이 아닌 행위", B_SEAT, None, "summon", True),
    ],
)
def test_g_a_refused_response_leaves_everything_alone(
    state, name, seat, target_of, kind, authorize
):
    chain = Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state))
    response = opened(chain, B_SEAT)
    before = state.state_hash()
    targets = {
        "a": lambda: picked(a_monster(state)),
        "hand": lambda: picked(b_card(state)),
        None: lambda: (),
    }[target_of]()

    if kind == "summon":
        action = PlayerAction.normal_summon(actor=seat, source=b_card(state))
    else:
        action = activate(seat, b_card(state), EFFECT_Y)

    result = loop().act(
        state,
        response,
        action,
        targets,
        authorization=GRANTED if authorize else None,
    )

    assert result.outcome is ResponseOutcome.REFUSED, name
    assert result.link is None, name
    assert result.chain is chain, name
    assert len(result.chain) == 1, name
    assert result.priority is response.priority, name  # 우선권도 그대로
    assert state.state_hash() == before, name


@requires_official_db
def test_g_a_text_derived_response_never_reaches_the_chain(state):
    """출처가 금지한 효과는 응답으로도 올라가지 않는다 (ADR-004)."""
    forged = EffectDefinition(
        effect_ref=EFFECT_Y,
        source_card_id=LAB,
        targets=destroy_effect(1).targets,
        operations=destroy_effect(1).operations,
        provenance=EffectProvenance.text_derived("텍스트에서 유추했다고 치자"),
    )
    chain = Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state))
    before = state.state_hash()

    result = loop(EffectDefinitionRegistry((destroy_effect(0), forged))).act(
        state,
        opened(chain, B_SEAT),
        activate(B_SEAT, b_card(state), EFFECT_Y),
        picked(a_monster(state)),
        authorization=GRANTED,
    )

    assert result.outcome is ResponseOutcome.REFUSED
    assert result.activation.status is ActivationStatus.FORBIDDEN
    assert len(result.chain) == 1
    assert state.state_hash() == before


@requires_official_db
def test_g_an_unregistered_response_never_reaches_the_chain(state):
    """해결기가 거절할 효과를 체인에 얹지 않는다 (ADR-006)."""
    machine = ResponseLoop(EffectActivator(definitions()))  # 구현 등록 없음
    chain = Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state))

    result = machine.act(
        state,
        opened(chain, B_SEAT),
        activate(B_SEAT, b_card(state), EFFECT_Y),
        picked(a_monster(state)),
        authorization=GRANTED,
    )

    assert result.outcome is ResponseOutcome.REFUSED
    assert result.activation.status is ActivationStatus.NOT_IMPLEMENTED
    assert len(result.chain) == 1


@requires_official_db
def test_g_an_unpayable_response_cost_leaves_the_chain_alone(state):
    """비용을 못 내면 링크도 없고 판도 그대로다."""
    registry = EffectDefinitionRegistry(
        (
            destroy_effect(0),
            destroy_effect(1, cost=CostGroup((LifeCost(amount=999_999),))),
        )
    )
    chain = Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state))
    before = state.state_hash()

    result = loop(registry).act(
        state,
        opened(chain, B_SEAT),
        activate(B_SEAT, b_card(state), EFFECT_Y),
        picked(a_monster(state)),
        authorization=GRANTED,
    )

    assert result.outcome is ResponseOutcome.REFUSED
    assert result.activation.status is ActivationStatus.COST_UNPAYABLE
    assert len(result.chain) == 1
    assert state.state_hash() == before


@requires_official_db
def test_g_a_refusal_does_not_cost_the_player_their_turn(state):
    """
    §12 — 거절은 "아무 일도 일어나지 않았다" 이므로 차례도 그대로다.
    실패를 패스로 바꾸면 되돌릴 수 없는 차례가 조용히 날아간다.
    """
    chain = Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state))
    response = opened(chain, B_SEAT)
    machine = loop()

    refused = machine.act(
        state,
        response,
        activate(B_SEAT, b_card(state), EFFECT_Y),  # 대상 없음
        authorization=GRANTED,
    )
    retried = machine.act(
        state,
        refused.state,
        activate(B_SEAT, b_card(state), EFFECT_Y),
        picked(a_monster(state)),
        authorization=GRANTED,
    )

    assert refused.outcome is ResponseOutcome.REFUSED
    assert retried.outcome is ResponseOutcome.LINK_ADDED  # 다시 시도할 수 있다


def test_g_a_result_cannot_claim_a_link_it_did_not_add():
    action = PlayerAction.passing(A_SEAT)
    response = ResponseState(Chain(), PriorityState.idle())

    with pytest.raises(ResponseError):
        ResponseResult(ResponseOutcome.LINK_ADDED, action, response)


def test_g_a_result_is_never_a_boolean():
    result = ResponseResult(
        ResponseOutcome.PASSED,
        PlayerAction.passing(A_SEAT),
        ResponseState(Chain(), PriorityState.idle()),
    )

    with pytest.raises(TypeError):
        bool(result)


# ======================================================================
# H. 결정론 · 복제 독립성
# ======================================================================


def _run_scenario(board: GameState, machine: ResponseLoop):
    """A 발동 → B 응답 → 양쪽 패스. 같은 순서, 같은 값."""
    steps = []
    response = opened()
    for action, targets in (
        (activate(A_SEAT, a_card(board), EFFECT_X), picked(b_monster(board))),
        (activate(B_SEAT, b_card(board), EFFECT_Y), picked(a_monster(board))),
        (PlayerAction.passing(A_SEAT), ()),
        (PlayerAction.passing(B_SEAT), ()),
    ):
        result = machine.act(board, response, action, targets, authorization=GRANTED)
        steps.append(result)
        response = result.state
    return steps, response


@requires_official_db
def test_h_the_same_action_sequence_gives_the_same_state(repository):
    first, second = new_state(repository), new_state(repository)

    left_steps, left = _run_scenario(first, loop())
    right_steps, right = _run_scenario(second, loop())

    assert [s.outcome for s in left_steps] == [s.outcome for s in right_steps]
    assert left.canonical_state() == right.canonical_state()
    assert first.state_hash() == second.state_hash()


@requires_official_db
def test_h_the_same_sequence_gives_the_same_resolution_order(repository):
    first, second = new_state(repository), new_state(repository)
    machine = loop()

    _, left = _run_scenario(first, machine)
    _, right = _run_scenario(second, machine)
    left_done = machine.resolve(
        first, left, chain_resolver(destructible=(a_monster(first), b_monster(first)))
    )
    right_done = machine.resolve(
        second,
        right,
        chain_resolver(destructible=(a_monster(second), b_monster(second))),
    )

    assert [s.link.effect_ref for s in left_done.steps] == [
        s.link.effect_ref for s in right_done.steps
    ]
    assert left_done.canonical_state() == right_done.canonical_state()


@requires_official_db
def test_h_responding_on_a_clone_leaves_the_original_alone(state):
    copy = state.clone()
    registry = EffectDefinitionRegistry(
        (destroy_effect(0), destroy_effect(1, cost=CostGroup((LifeCost(amount=500),))))
    )
    life_before = state.player(B_SEAT).life_points
    before = state.state_hash()

    result = loop(registry).act(
        copy,
        opened(Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state)), B_SEAT),
        activate(B_SEAT, b_card(copy), EFFECT_Y),
        picked(a_monster(copy)),
        authorization=GRANTED,
    )

    assert result.outcome is ResponseOutcome.LINK_ADDED
    assert copy.player(B_SEAT).life_points == life_before - 500
    assert state.player(B_SEAT).life_points == life_before
    assert state.state_hash() == before


@requires_official_db
def test_h_asking_whose_turn_it_is_never_changes_anything(state):
    machine = loop()
    response = opened(Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state)), B_SEAT)
    before = state.state_hash()

    for _ in range(3):
        machine.may_act(state, response, A_SEAT)
        machine.may_act(state, response, B_SEAT)
        machine.ready_to_resolve(response)

    assert state.state_hash() == before
    assert response.canonical_state() == opened(response.chain, B_SEAT).canonical_state()


# ======================================================================
# I. 정보 경계 · 중복 시스템 금지 · AI 없음
# ======================================================================


@requires_official_db
def test_i_a_refusal_names_no_hidden_card(state):
    """상대의 패에 있는 카드를 대상으로 골라 거절당해도 정체가 새지 않는다."""
    hidden = state.player(A_SEAT).hand[-1]
    assert hidden.card_id == DARK_HOLE  # 판 어디에도 없는 번호여야 의미가 있다

    result = loop().act(
        state,
        opened(Chain().activate(actor=A_SEAT, effect_ref=EFFECT_X, source=a_card(state)), B_SEAT),
        activate(B_SEAT, b_card(state), EFFECT_Y),
        picked(hidden.instance_id),
        authorization=GRANTED,
    )
    text = str(result.to_dict())

    assert result.outcome is ResponseOutcome.REFUSED
    assert str(hidden.card_id) not in text


def test_i_every_observation_is_built_from_the_deciding_seat():
    """관측은 **그 자리의 시점**으로 만든다 — 물어보는 것만으로 탐지할 수 없다."""
    tree = ast.parse(pathlib.Path("engine/response.py").read_text("utf-8"))
    viewers = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg == "viewer"
    ]

    assert viewers
    for value in viewers:
        # ``seat`` 이거나 ``action.actor`` — 둘 다 **결정하는 자리**다.
        # 상대 자리나 전지적 시점으로 만든 관측이 하나도 없어야 한다.
        if isinstance(value, ast.Name):
            assert value.id == "seat", ast.dump(value)
        else:
            assert isinstance(value, ast.Attribute), ast.dump(value)
            assert value.attr == "actor", ast.dump(value)


def test_i_no_second_chain_or_priority_system_was_built():
    """§17 — 새 Chain / Priority / Resolver 를 만들지 않았다."""
    tree = ast.parse(pathlib.Path("engine/response.py").read_text("utf-8"))
    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }

    assert defined == {
        "ResponseStep",
        "ResponseOutcome",
        "ResponseError",
        "ResponseState",
        "ResponseResult",
        "ResponseResolution",
        "ResponseLoop",
    }
    for forbidden in ("Chain", "ChainLink", "PriorityState", "ChainResolver"):
        assert forbidden not in defined


def test_i_the_loop_makes_no_decision_of_its_own():
    """§17 — PASS 도 발동도 밖에서 온 ``PlayerAction`` 이다."""
    source = pathlib.Path("engine/response.py").read_text("utf-8")
    tree = ast.parse(source)
    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for forbidden in ("choose", "decide", "score", "policy", "best"):
        assert not any(forbidden in name for name in functions)
    assert "random" not in source


def test_i_the_activation_layer_does_not_know_about_the_loop():
    """방향이 한쪽이다 — 응답이 발동을 부르고, 그 반대는 없다."""
    tree = ast.parse(pathlib.Path("engine/activation.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "engine.response" not in imported
