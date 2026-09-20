"""
Phase 2-Q — 효과 발동 (Activation Core).

    PlayerAction(ACTIVATE_EFFECT)
        ↓  EffectActivator.can_activate()   읽기만 한다
        ↓  EffectActivator.activate()
    비용 지불 (Phase 2-E)                    **발동에서 판이 바뀌는 유일한 곳**
        ↓
    ChainLink → Chain                        Phase 2-F-2
        ↓  ..............................   (다른 시점, 다른 호출)
    ChainResolver.resolve_top()
        ↓
    EffectExecutor                           Phase 2-D-2 · 2-K~2-P

이 파일이 지키려는 것은 하나다.

    **발동 ≠ 해결.**

``ACTIVATE_EFFECT`` 가 성공해도 카드는 아직 아무 데도 가지 않는다. 드로우도
파괴도 라이프 변화도 일어나지 않는다. 그것은 전부 체인이 풀릴 때의 일이다.

허가는 테스트가 준다
--------------------
``ActionValidator`` 는 오늘 ``ACTIVATE_EFFECT`` 에 ``UNKNOWN`` 을 돌려준다 —
발동 타이밍 계층이 없기 때문이다. 그래서 허가를 주지 않으면 아무것도
발동되지 않고, 그 사실을 먼저 확인한 뒤(A 묶음) 나머지를 보기 위해 테스트가
명시적인 ``VALID`` 를 건넨다. Phase 2-M 의 ``DeclaredDestructionRuling``,
Phase 2-O 의 synthetic 판정과 같은 자리다.

AI 는 없다
----------
무엇을 발동해야 하는가는 이 계층의 질문이 아니다. 대상도 비용 선택도
테스트가 값으로 준다.
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionExecutor
from engine.action_validation import ActionValidator
from engine.activation import (
    ActivationError,
    ActivationResult,
    ActivationStatus,
    EffectActivator,
)
from engine.chain import Chain, ChainLink, ChainResolutionStatus, ChainResolver
from engine.condition import IsMonster, PlayerRef, ZoneCountAtLeast
from engine.cost import CandidateSource, CardCost, ChoiceSpec, CostGroup, LifeCost, Selection
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectProvenance,
)
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.library import (
    MYSTICAL_SPACE_TYPHOON,
    POT_OF_GREED,
    build_executor,
    definition_registry,
    implementation_registry,
)
from engine.effect.operation import CardOperation, DrawOperation
from engine.effect.resolution import ResolutionStatus, TargetSelection
from engine.effect.semantics import DeclaredDestructionRuling
from engine.effect.target import PRIMARY_TARGET, TargetBinding, TargetSpec
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.payment import CostPayer, CostSelection
from engine.priority import PriorityHolder, PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1

MST = MYSTICAL_SPACE_TYPHOON  # 싸이크론 — 대상을 지정하는 실제 카드
POT = POT_OF_GREED  # 욕망의 항아리 — 대상이 없는 실제 카드
DARK_HOLE = 53129443
FEATHERMAN = 21844576
LAB = 2511  # synthetic 정의의 **껍데기**. 이 카드의 의미를 주장하지 않는다

MST_EFFECT = EffectRef(MST, 0)
POT_EFFECT = EffectRef(POT, 0)
SYNTHETIC_EFFECT = EffectRef(LAB, 0)
PRIMARY = PRIMARY_TARGET


# ======================================================================
# 판
# ======================================================================


def new_state(repository) -> GameState:
    """
    p0(MINE)
        SZONE  싸이크론 (앞면) · 욕망의 항아리 (앞면)
        MZONE  페더맨 (앞면)
        HAND   페더맨 2장
        DECK   넉넉히
    p1(THEIRS)
        SZONE  블랙홀 (앞면) · 블랙홀 (**뒷면**)
        MZONE  페더맨 (앞면)
    """
    game = GameState.create(
        repository,
        decks=(
            [MST, POT] + [FEATHERMAN] * 18,
            [DARK_HOLE] * 2 + [FEATHERMAN] * 18,
        ),
    )
    game.draw(MINE, 5)  # 싸이크론 · 욕망 · 페더맨 ×3
    game.draw(THEIRS, 3)  # 블랙홀 ×2 · 페더맨

    game.move(
        game.player(MINE).hand[0], Zone.SZONE, to_player=MINE,
        position=Position.FACEUP,
    )
    game.move(
        game.player(MINE).hand[0], Zone.SZONE, to_player=MINE,
        position=Position.FACEUP,
    )
    game.move(
        game.player(MINE).hand[-1], Zone.MZONE, to_player=MINE,
        position=Position.FACEUP_ATTACK,
    )
    game.move(
        game.player(THEIRS).hand[0], Zone.SZONE, to_player=THEIRS,
        position=Position.FACEUP,
    )
    game.move(
        game.player(THEIRS).hand[0], Zone.SZONE, to_player=THEIRS,
        position=Position.FACEDOWN,
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


def card_in_spell_zone(state: GameState, card_id: int) -> InstanceId:
    for card in state.player(MINE).spell_zone:
        if card.card_id == card_id:
            return card.instance_id
    raise AssertionError(f"{card_id} 가 마법/함정 존에 없습니다.")


def the_typhoon(state: GameState) -> InstanceId:
    return card_in_spell_zone(state, MST)


def the_pot(state: GameState) -> InstanceId:
    return card_in_spell_zone(state, POT)


def their_faceup_spell(state: GameState) -> InstanceId:
    return state.player(THEIRS).spell_zone[0].instance_id


def their_facedown_spell(state: GameState) -> InstanceId:
    return state.player(THEIRS).spell_zone[1].instance_id


def their_monster(state: GameState) -> InstanceId:
    return state.player(THEIRS).monster_zone[0].instance_id


def my_monster(state: GameState) -> InstanceId:
    return state.player(MINE).monster_zone[0].instance_id


def my_hand_card(state: GameState) -> InstanceId:
    return state.player(MINE).hand[0].instance_id


# ======================================================================
# 도구 — 전부 기존 계층을 그대로 부른다
# ======================================================================

#: **테스트가 명시적으로 건네는 허가.** 발동 타이밍 계층을 대신하지 않는다 —
#: "이 판정의 책임은 건넨 쪽에 있다" 를 값으로 적는 것뿐이다.
GRANTED = ValidationResult.valid("테스트가 발동 타이밍을 허가했다")


def real_activator(payer: CostPayer | None = None) -> EffectActivator:
    """라이브러리의 정의와 구현 목록을 그대로 쓴다."""
    return EffectActivator(definition_registry(), implementation_registry(), payer)


def synthetic_destroy(
    *,
    cost: CostGroup | None = None,
    provenance: EffectProvenance | None = None,
    activation=None,
    ordinal: int = 0,
) -> EffectDefinition:
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
        activation=activation,
        provenance=provenance
        or EffectProvenance.hand_written(verified=True, note="Phase 2-Q 발동 시험"),
    )


def synthetic_activator(
    definition: EffectDefinition,
    *,
    registered: bool = True,
    payer: CostPayer | None = None,
) -> EffectActivator:
    return EffectActivator(
        EffectDefinitionRegistry((definition,)),
        EffectImplementationRegistry((definition.effect_ref,)) if registered else None,
        payer,
    )


def activation_action(
    state: GameState, effect_ref: EffectRef, source: InstanceId | None = None
) -> PlayerAction:
    return PlayerAction.activate_effect(
        actor=MINE,
        source=source if source is not None else the_typhoon(state),
        effect_ref=effect_ref,
    )


def picked(*instances: InstanceId) -> tuple[TargetSelection, ...]:
    """테스트가 **값으로** 주는 대상. 엔진이 고르지 않는다."""
    return (TargetSelection(PRIMARY, Selection.of(*instances)),)


def resolver(
    definition: EffectDefinition | None = None,
    *,
    destruction=None,
    journal: EventJournal | None = None,
) -> ChainResolver:
    """해결기. **발동 계층과 다른 객체다.**"""
    if definition is None:
        return ChainResolver(
            build_executor(journal=journal, destruction=destruction),
            definition_registry(),
        )
    return ChainResolver(
        EffectExecutor(
            lookup=EffectImplementationRegistry((definition.effect_ref,)),
            journal=journal,
            destruction=destruction,
        ),
        EffectDefinitionRegistry((definition,)),
    )


def confirmed(*instances: InstanceId) -> DeclaredDestructionRuling:
    """synthetic 정의에만 주는, 테스트가 선언한 파괴 판정."""
    return DeclaredDestructionRuling(destructible=frozenset(instances))


# ======================================================================
# A. 허가 — UNKNOWN 은 발동 허가가 아니다
# ======================================================================


@requires_official_db
def test_a_the_validator_still_cannot_authorize_an_activation(state):
    """
    **발동 타이밍 계층이 없다는 사실을 먼저 적는다.** 이 테스트가 깨지는
    날은 그 계층이 생긴 날이다.
    """
    action = activation_action(state, MST_EFFECT)
    verdict = ActionValidator(
        GameStateView.from_state(state, viewer=MINE)
    ).validate(action)

    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.permits_execution is False
    assert verdict.missing_rule


@requires_official_db
def test_a_without_an_explicit_grant_nothing_is_activated(state):
    """허가를 주지 않으면 체인은 자라지 않는다."""
    chain = Chain()
    before = state.state_hash()

    result = real_activator().activate(
        state, chain, activation_action(state, MST_EFFECT), picked(their_faceup_spell(state))
    )

    assert result.status is ActivationStatus.UNAUTHORIZED
    assert result.link is None
    assert len(result.chain) == 0
    assert result.chain is chain
    assert result.missing
    assert state.state_hash() == before


@requires_official_db
def test_a_an_unknown_authorization_is_not_a_grant(state):
    """``UNKNOWN`` 을 건네도 허가가 아니다."""
    maybe = ValidationResult.unknown(
        ValidationCode.RULE_NOT_IMPLEMENTED, "아마 될 것 같다"
    )

    result = real_activator().activate(
        state,
        Chain(),
        activation_action(state, POT_EFFECT, the_pot(state)),
        authorization=maybe,
    )

    assert result.status is ActivationStatus.UNAUTHORIZED
    assert result.link is None


@requires_official_db
def test_a_can_activate_reuses_the_validation_vocabulary(state):
    """
    §5 — "할 수 있는가" 의 어휘를 새로 만들지 않았다.
    """
    activator = real_activator()
    action = activation_action(state, POT_EFFECT, the_pot(state))

    refused = activator.can_activate(state, Chain(), action)
    granted = activator.can_activate(state, Chain(), action, authorization=GRANTED)

    assert isinstance(refused, ValidationResult)
    assert refused.validity is ActionValidity.UNKNOWN
    assert granted.validity is ActionValidity.VALID


@requires_official_db
def test_a_can_activate_never_touches_the_board(state):
    """읽기만 하는 질문이다."""
    before = state.state_hash()
    activator = real_activator()

    for _ in range(3):
        activator.can_activate(
            state,
            Chain(),
            activation_action(state, MST_EFFECT),
            picked(their_faceup_spell(state)),
            authorization=GRANTED,
        )

    assert state.state_hash() == before


# ======================================================================
# B. 발동 ≠ 해결 — 실제 카드
# ======================================================================


@requires_official_db
def test_b_activating_the_pot_draws_nothing_yet(state):
    """
    **이 파일의 핵심이다.** 발동이 성공해도 카드는 뽑히지 않는다.
    """
    hand_before = len(state.player(MINE).hand)
    deck_before = len(state.player(MINE).deck)
    before = state.state_hash()

    result = real_activator().activate(
        state,
        Chain(),
        activation_action(state, POT_EFFECT, the_pot(state)),
        authorization=GRANTED,
    )

    assert result.status is ActivationStatus.ACTIVATED
    assert len(result.chain) == 1
    # 판은 한 글자도 바뀌지 않았다 — 비용이 없는 효과이므로.
    assert len(state.player(MINE).hand) == hand_before
    assert len(state.player(MINE).deck) == deck_before
    assert state.state_hash() == before
    assert result.deltas == ()


@requires_official_db
def test_b_the_link_carries_everything_the_resolution_will_need(state):
    """§8 — 링크가 무엇을 들고 가는가."""
    source = the_typhoon(state)
    target = their_faceup_spell(state)

    result = real_activator().activate(
        state,
        Chain(),
        activation_action(state, MST_EFFECT, source),
        picked(target),
        authorization=GRANTED,
    )
    link = result.link

    assert link is not None
    assert link.effect_ref == MST_EFFECT
    assert link.actor == MINE
    assert link.source == source
    assert link.selections == picked(target)
    assert link.payments == ()
    assert link.sequence == 0
    assert link.chain_number == 1


@requires_official_db
def test_b_the_link_does_not_carry_the_definition(state):
    """정의를 박아 두면 링크가 낡은 정의를 영구히 들고 다닌다."""
    result = real_activator().activate(
        state,
        Chain(),
        activation_action(state, POT_EFFECT, the_pot(state)),
        authorization=GRANTED,
    )

    assert not hasattr(result.link, "definition")
    assert result.link.effect_ref == POT_EFFECT


@requires_official_db
def test_b_resolution_is_what_finally_draws(state):
    """
    발동 → (아무 일 없음) → 해결 → 실제 드로우. **두 호출이다.**
    """
    hand_before = len(state.player(MINE).hand)
    activated = real_activator().activate(
        state,
        Chain(),
        activation_action(state, POT_EFFECT, the_pot(state)),
        authorization=GRANTED,
    )
    assert len(state.player(MINE).hand) == hand_before  # 아직

    resolved = resolver().resolve_top(state, activated.chain)

    assert resolved.status is ChainResolutionStatus.RESOLVED
    assert len(state.player(MINE).hand) == hand_before + 2


@requires_official_db
def test_b_the_activator_never_imports_the_effect_executor():
    """
    §2 · §4 — 발동 계층이 실행기를 **가져오지도 않는다.** 가져오는 순간
    발동이 곧 해결일 수 있게 된다.
    """
    tree = ast.parse(pathlib.Path("engine/activation.py").read_text("utf-8"))
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
    assert "ChainResolver" not in used
    assert "execute" not in used


@requires_official_db
def test_b_activate_effect_is_not_registered_with_the_action_executor():
    """
    🟠 STRUCTURAL-55 — ``ActionHandler`` 는 ``StateDelta`` 만 돌려주는
    모양이라, 결과물이 **판의 모양이 아니라 흐름의 위치**(``Chain``)인
    발동을 표현하지 못한다. 억지로 끼워 넣으면 체인을 숨겨서 주고받게 된다.
    """
    executor = ActionExecutor()

    assert PlayerActionKind.ACTIVATE_EFFECT not in executor.supported
    tree = ast.parse(pathlib.Path("engine/action_execution.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "engine.activation" not in imported
    assert "engine.chain" not in imported


@requires_official_db
def test_b_the_real_typhoon_activates_but_its_resolution_still_stops(state):
    """
    §14 — 실제 카드의 재정을 지어내지 않는다.

    **발동은 된다** — 대상 규칙을 전부 통과한다. 그런데 해결은 파괴 판정에서
    멈춘다 (Phase 2-M · 2-O). 두 사실이 서로 다른 계층의 답이라는 것이
    여기서 눈에 보인다.
    """
    target = their_faceup_spell(state)
    before = state.state_hash()

    activated = real_activator().activate(
        state,
        Chain(),
        activation_action(state, MST_EFFECT),
        picked(target),
        authorization=GRANTED,
    )
    assert activated.status is ActivationStatus.ACTIVATED
    assert len(activated.chain) == 1

    resolved = resolver().resolve_top(state, activated.chain)

    assert resolved.result.status is ResolutionStatus.UNCHECKED_RULES
    assert state.locate(target).zone is Zone.SZONE
    assert state.state_hash() == before


# ======================================================================
# C. synthetic end-to-end — 발동 직후 ≠ 해결 후
# ======================================================================


@requires_official_db
def test_c_the_target_stays_put_until_the_chain_resolves(state):
    """
    §13 — 발동 직후와 해결 후를 **명확히 비교한다.**
    """
    definition = synthetic_destroy()
    target = their_monster(state)
    action = PlayerAction.activate_effect(
        actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
    )
    before = state.state_hash()

    # 1. 발동.
    activated = synthetic_activator(definition).activate(
        state, Chain(), action, picked(target), authorization=GRANTED
    )

    assert activated.status is ActivationStatus.ACTIVATED
    assert len(activated.chain) == 1
    assert activated.chain.top is activated.link
    # **발동 직후** — 대상은 그대로 필드에 있다.
    assert state.locate(target).zone is Zone.MZONE
    assert state.state_hash() == before

    # 2. 해결.
    resolved = resolver(definition, destruction=confirmed(target)).resolve_top(
        state, activated.chain
    )

    # **해결 후** — 이제야 묘지로 간다.
    assert resolved.status is ChainResolutionStatus.RESOLVED
    assert state.locate(target).zone is Zone.GRAVE
    assert state.state_hash() != before
    assert resolved.chain.is_complete


@requires_official_db
def test_c_the_resolution_uses_the_targets_chosen_at_activation(state):
    """링크가 들고 간 선택이 그대로 해결에 쓰인다. 다시 고르지 않는다."""
    definition = synthetic_destroy()
    target = their_monster(state)
    activated = synthetic_activator(definition).activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(target),
        authorization=GRANTED,
    )

    context = activated.link.resolution_context()
    resolved = resolver(definition, destruction=confirmed(target)).resolve_top(
        state, activated.chain
    )

    assert context.selection_for(PRIMARY).chosen == (target,)
    assert resolved.result.applied[0].instances == (target,)


@requires_official_db
def test_c_the_event_pipeline_sees_nothing_at_activation(state):
    """
    §12 — 발동은 사건을 만들지 않는다. 비용이 없으면 변화가 없기 때문이다.
    """
    definition = synthetic_destroy()
    target = their_monster(state)
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))

    activated = synthetic_activator(definition).activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(target),
        authorization=GRANTED,
    )
    at_activation = reader.read(activated, actor=MINE)

    resolved = resolver(definition, destruction=confirmed(target)).resolve_top(
        state, activated.chain
    )
    at_resolution = reader.read(resolved.result, actor=MINE)

    assert at_activation == ()
    assert len(at_resolution) == 1


@requires_official_db
def test_c_a_second_activation_stacks_on_top(state):
    """체인 2 가 체인 1 **위에** 쌓이고, 해결은 뒤에서부터다."""
    definition = synthetic_destroy()
    activator = synthetic_activator(definition)
    action = PlayerAction.activate_effect(
        actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
    )

    first = activator.activate(
        state, Chain(), action, picked(their_monster(state)), authorization=GRANTED
    )
    second = activator.activate(
        state, first.chain, action, picked(my_monster(state)), authorization=GRANTED
    )

    assert [link.sequence for link in second.chain] == [0, 1]
    assert second.chain.top.selections == picked(my_monster(state))
    assert second.chain.resolution_order[0] is second.chain.top


# ======================================================================
# D. 비용 — Phase 2-E 를 그대로 쓴다
# ======================================================================


@requires_official_db
def test_d_a_life_cost_is_paid_at_activation_not_at_resolution(state):
    """
    **비용은 발동의 일이다.** 발동에서 판이 바뀌는 유일한 자리다.
    """
    definition = synthetic_destroy(cost=CostGroup((LifeCost(amount=800),)))
    target = their_monster(state)
    life_before = state.player(MINE).life_points

    activated = synthetic_activator(definition).activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(target),
        authorization=GRANTED,
    )

    assert activated.status is ActivationStatus.ACTIVATED
    assert state.player(MINE).life_points == life_before - 800
    assert activated.deltas  # 비용이 만든 변화
    assert activated.paid_anything is True
    # 효과는 아직 일어나지 않았다.
    assert state.locate(target).zone is Zone.MZONE


@requires_official_db
def test_d_the_receipt_rides_along_and_is_never_charged_again(state):
    """§6 — 링크가 영수증을 참조로만 들고 간다. 해결 중에 다시 내지 않는다."""
    definition = synthetic_destroy(cost=CostGroup((LifeCost(amount=500),)))
    target = their_monster(state)
    activated = synthetic_activator(definition).activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(target),
        authorization=GRANTED,
    )
    life_after_cost = state.player(MINE).life_points

    resolver(definition, destruction=confirmed(target)).resolve_top(
        state, activated.chain
    )

    assert activated.link.payments
    assert activated.link.paid_anything is True
    assert state.player(MINE).life_points == life_after_cost  # 다시 깎이지 않았다


@requires_official_db
def test_d_a_card_cost_uses_the_selection_the_caller_gave(state):
    """비용 선택도 값으로 온다 — 엔진이 고르지 않는다."""
    definition = synthetic_destroy(cost=CostGroup((CardCost.discard(1),)))
    discarded = my_hand_card(state)
    hand_before = len(state.player(MINE).hand)

    activated = synthetic_activator(definition).activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(their_monster(state)),
        cost_selections=(CostSelection(0, Selection.of(discarded)),),
        authorization=GRANTED,
    )

    assert activated.status is ActivationStatus.ACTIVATED
    assert len(state.player(MINE).hand) == hand_before - 1
    assert state.locate(discarded).zone is Zone.GRAVE


@requires_official_db
def test_d_the_cost_payer_is_the_one_from_phase_2e(state):
    """§6 — 비용을 여기서 다시 구현하지 않았다."""
    journal = EventJournal()
    definition = synthetic_destroy(cost=CostGroup((LifeCost(amount=400),)))

    synthetic_activator(definition, payer=CostPayer(journal=journal)).activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(their_monster(state)),
        authorization=GRANTED,
    )

    assert len(journal) == 1  # CostPayer 가 자기 기록을 남겼다


@requires_official_db
def test_d_an_unpayable_cost_leaves_no_link_and_no_change(state):
    """§15 D — 비용을 못 내면 체인은 자라지 않는다."""
    definition = synthetic_destroy(cost=CostGroup((LifeCost(amount=999_999),)))
    before = state.state_hash()

    result = synthetic_activator(definition).activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(their_monster(state)),
        authorization=GRANTED,
    )

    assert result.status is ActivationStatus.COST_UNPAYABLE
    assert result.link is None
    assert len(result.chain) == 0
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_d_can_activate_does_not_promise_the_cost_can_be_paid(state):
    """
    🟠 STRUCTURAL-56 — ``can_activate`` 는 ``VALID`` 인데 ``activate`` 는
    비용에서 멈춘다. ``CostPayer`` 의 preflight 가 비공개라 밖에서 물어볼
    수 없고, 흉내 내면 두 벌이 갈리기 때문이다. 지금은 그 한계를 적어 둔다.
    """
    definition = synthetic_destroy(cost=CostGroup((LifeCost(amount=999_999),)))
    activator = synthetic_activator(definition)
    action = PlayerAction.activate_effect(
        actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
    )

    asked = activator.can_activate(
        state, Chain(), action, picked(their_monster(state)), authorization=GRANTED
    )
    tried = activator.activate(
        state, Chain(), action, picked(their_monster(state)), authorization=GRANTED
    )

    assert asked.validity is ActionValidity.VALID  # 비용은 보지 않았다
    assert tried.status is ActivationStatus.COST_UNPAYABLE
    assert tried.link is None  # 그래도 링크는 생기지 않는다


# ======================================================================
# E. 실패 행렬 — 링크 없음 · 체인 불변 · state_hash 불변
# ======================================================================


@requires_official_db
def test_e_a_the_action_must_point_at_an_effect(state):
    """A — ``effect_ref`` 가 없다."""
    action = PlayerAction(
        kind=PlayerActionKind.ACTIVATE_EFFECT, actor=MINE, source=the_typhoon(state)
    )
    before = state.state_hash()

    result = real_activator().activate(state, Chain(), action, authorization=GRANTED)

    assert result.status is ActivationStatus.INVALID_ACTION
    assert result.code is ValidationCode.EFFECT_REF_REQUIRED
    assert len(result.chain) == 0
    assert state.state_hash() == before


@requires_official_db
def test_e_a_an_unknown_effect_ref_has_no_definition(state):
    """A — 정의가 없는 효과는 발동할 수 없다."""
    action = activation_action(state, EffectRef(99999999, 0))

    result = real_activator().activate(state, Chain(), action, authorization=GRANTED)

    assert result.status is ActivationStatus.NOT_IMPLEMENTED
    assert result.missing == "effect definition"
    assert len(result.chain) == 0


@requires_official_db
def test_e_b_a_text_derived_effect_never_reaches_the_chain(state):
    """B — 출처가 금지한 효과는 체인에 올라가지 않는다 (ADR-004)."""
    definition = synthetic_destroy(
        provenance=EffectProvenance.text_derived("텍스트에서 유추했다고 치자")
    )
    before = state.state_hash()

    result = synthetic_activator(definition).activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(their_monster(state)),
        authorization=GRANTED,
    )

    assert result.status is ActivationStatus.FORBIDDEN
    assert len(result.chain) == 0
    assert state.state_hash() == before


@requires_official_db
def test_e_c_an_unregistered_implementation_never_reaches_the_chain(state):
    """
    C — 해결기가 거절할 효과를 체인에 올리지 않는다. 올리면 "발동은 됐는데
    해결은 안 되는" 링크가 쌓인다.
    """
    definition = synthetic_destroy()
    before = state.state_hash()

    result = synthetic_activator(definition, registered=False).activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(their_monster(state)),
        authorization=GRANTED,
    )

    assert result.status is ActivationStatus.NOT_IMPLEMENTED
    assert result.missing == "registered effect implementation"
    assert len(result.chain) == 0
    assert state.state_hash() == before


@requires_official_db
def test_e_e_an_illegal_target_never_reaches_the_chain(state):
    """E — 싸이크론에 자기 자신을 고른다."""
    before = state.state_hash()

    result = real_activator().activate(
        state,
        Chain(),
        activation_action(state, MST_EFFECT),
        picked(the_typhoon(state)),
        authorization=GRANTED,
    )

    assert result.status is ActivationStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert len(result.chain) == 0
    assert state.state_hash() == before


@requires_official_db
def test_e_f_an_unknown_target_is_not_an_illegal_one(state):
    """F — 상대의 세트 카드는 **모르는** 대상이다."""
    result = real_activator().activate(
        state,
        Chain(),
        activation_action(state, MST_EFFECT),
        picked(their_facedown_spell(state)),
        authorization=GRANTED,
    )

    assert result.status is ActivationStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert len(result.chain) == 0


@requires_official_db
def test_e_f_a_missing_selection_never_reaches_the_chain(state):
    """대상을 요구하는 효과인데 아직 고르지 않았다."""
    result = real_activator().activate(
        state, Chain(), activation_action(state, MST_EFFECT), authorization=GRANTED
    )

    assert result.status is ActivationStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    assert len(result.chain) == 0


@requires_official_db
def test_e_g_a_false_activation_condition_is_not_unknown(state):
    """
    G — 욕망의 항아리의 실제 발동 조건(``덱 2장 이상``)이 거짓인 판.
    **실제 카드의 규칙을 추측하지 않았다** — 스크립트에서 옮긴 그 조건이다.
    """
    while len(state.player(MINE).deck) > 1:
        state.move(state.player(MINE).deck[0], Zone.REMOVED, to_player=MINE)
    before = state.state_hash()

    result = real_activator().activate(
        state,
        Chain(),
        activation_action(state, POT_EFFECT, the_pot(state)),
        authorization=GRANTED,
    )

    assert result.status is ActivationStatus.CONDITION_FALSE
    assert len(result.chain) == 0
    assert state.state_hash() == before


@requires_official_db
def test_e_g_an_unknown_activation_condition_stops_the_activation(state):
    """G — 판정할 수 없는 조건은 허가가 아니다."""
    definition = synthetic_destroy(activation=IsMonster(InstanceId(9999)))
    before = state.state_hash()

    result = synthetic_activator(definition).activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(their_monster(state)),
        authorization=GRANTED,
    )

    assert result.status is ActivationStatus.CONDITION_UNKNOWN
    assert result.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert len(result.chain) == 0
    assert state.state_hash() == before


@requires_official_db
def test_e_h_a_non_activation_action_is_refused(state):
    """H — 일반 소환은 효과 발동이 아니다."""
    action = PlayerAction.normal_summon(actor=MINE, source=my_hand_card(state))

    result = real_activator().activate(state, Chain(), action, authorization=GRANTED)

    assert result.status is ActivationStatus.INVALID_ACTION
    assert len(result.chain) == 0


@requires_official_db
def test_e_h_a_definition_for_another_effect_is_refused(state):
    """H — 저장소가 다른 효과의 정의를 돌려주면 발동하지 않는다."""
    definition = synthetic_destroy()
    registry = EffectDefinitionRegistry((definition,))

    class _Crossed:
        """가리키는 것과 다른 정의를 돌려주는 저장소."""

        def definition_for(self, effect_ref):
            return definition

    activator = EffectActivator(
        _Crossed(), EffectImplementationRegistry((MST_EFFECT,))
    )
    result = activator.activate(
        state,
        Chain(),
        activation_action(state, MST_EFFECT),
        picked(their_faceup_spell(state)),
        authorization=GRANTED,
    )

    assert result.status is ActivationStatus.INVALID_CONTEXT
    assert result.code is ValidationCode.EFFECT_REF_CARD_MISMATCH
    assert registry.definition_for(SYNTHETIC_EFFECT) is definition


@requires_official_db
def test_e_i_a_chain_that_started_resolving_refuses_the_link(state):
    """
    I — 해결이 시작된 체인에는 쌓을 수 없다. **비용을 치르기 전에** 안다.
    """
    definition = synthetic_destroy(cost=CostGroup((LifeCost(amount=800),)))
    started = Chain(
        links=(ChainLink(sequence=0, actor=MINE, effect_ref=SYNTHETIC_EFFECT),),
        resolved_count=1,
    )
    life_before = state.player(MINE).life_points
    before = state.state_hash()

    result = synthetic_activator(definition).activate(
        state,
        started,
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(their_monster(state)),
        authorization=GRANTED,
    )

    assert result.status is ActivationStatus.CHAIN_REFUSED
    assert result.chain is started
    assert len(result.chain) == 1
    # **비용이 빠져나가지 않았다** — 체인 거절을 지불 전에 보기 때문이다.
    assert state.player(MINE).life_points == life_before
    assert state.state_hash() == before


@requires_official_db
def test_e_every_failure_keeps_the_chain_and_the_board(repository):
    """
    실패 아홉 갈래를 한 자리에서 돌린다. 전부 링크 없음 · 체인 그대로 ·
    ``state_hash`` 불변.
    """
    def no_effect_ref(board, activator):
        return activator.activate(
            board,
            Chain(),
            PlayerAction(
                kind=PlayerActionKind.ACTIVATE_EFFECT,
                actor=MINE,
                source=the_typhoon(board),
            ),
            authorization=GRANTED,
        )

    def unknown_ref(board, activator):
        return activator.activate(
            board,
            Chain(),
            activation_action(board, EffectRef(99999999, 0)),
            authorization=GRANTED,
        )

    def unauthorized(board, activator):
        return activator.activate(
            board,
            Chain(),
            activation_action(board, MST_EFFECT),
            picked(their_faceup_spell(board)),
        )

    def illegal_target(board, activator):
        return activator.activate(
            board,
            Chain(),
            activation_action(board, MST_EFFECT),
            picked(the_typhoon(board)),
            authorization=GRANTED,
        )

    def unknown_target(board, activator):
        return activator.activate(
            board,
            Chain(),
            activation_action(board, MST_EFFECT),
            picked(their_facedown_spell(board)),
            authorization=GRANTED,
        )

    def wrong_kind(board, activator):
        return activator.activate(
            board,
            Chain(),
            PlayerAction.normal_summon(actor=MINE, source=my_hand_card(board)),
            authorization=GRANTED,
        )

    answers: dict[str, tuple] = {}
    for name, case in {
        "effect_ref 없음": no_effect_ref,
        "정의 없음": unknown_ref,
        "허가 없음": unauthorized,
        "부적법한 대상": illegal_target,
        "모르는 대상": unknown_target,
        "발동이 아닌 행위": wrong_kind,
    }.items():
        board = new_state(repository)
        before = board.state_hash()
        result = case(board, real_activator())
        assert result.status is not ActivationStatus.ACTIVATED, name
        assert result.link is None, name
        assert len(result.chain) == 0, name
        assert result.deltas == (), name
        assert board.state_hash() == before, name
        answers[name] = (result.status, result.code)

    assert len(set(answers.values())) == len(answers), answers


def test_e_a_result_cannot_claim_a_link_it_did_not_make():
    """실패한 결과가 링크를 들고 다닐 수 없다 — 생성 시점에 막는다."""
    action = PlayerAction.activate_effect(
        actor=MINE, source=InstanceId(1), effect_ref=SYNTHETIC_EFFECT
    )
    link = ChainLink(sequence=0, actor=MINE, effect_ref=SYNTHETIC_EFFECT)

    with pytest.raises(ActivationError):
        ActivationResult(
            ActivationStatus.INVALID_TARGET, action, Chain(), link=link
        )
    with pytest.raises(ActivationError):
        ActivationResult(ActivationStatus.ACTIVATED, action, Chain())


def test_e_a_result_is_never_a_boolean():
    action = PlayerAction.activate_effect(
        actor=MINE, source=InstanceId(1), effect_ref=SYNTHETIC_EFFECT
    )
    result = ActivationResult(ActivationStatus.UNAUTHORIZED, action, Chain())

    with pytest.raises(TypeError):
        bool(result)


# ======================================================================
# F. 우선권 — 기존 구조를 그대로 쓴다
# ======================================================================


@requires_official_db
def test_f_activating_breaks_the_pass_streak(state):
    """§10 — ``PriorityState.acted()`` 를 그대로 부른다."""
    priority = PriorityState.opened(
        ResponseWindow.ACTION, MINE, turn_player=MINE, phase=Phase.MAIN1
    ).passed()

    after = real_activator().advance_priority(priority)

    assert priority.consecutive_passes == 1
    assert after.consecutive_passes == 0
    assert after.window is ResponseWindow.ACTION


@requires_official_db
def test_f_the_activator_does_not_move_priority_on_its_own(state):
    """
    🟠 STRUCTURAL-34 — 누가 언제 우선권을 옮기는지 아직 정해지지 않았다.
    그래서 :meth:`activate` 가 **몰래 옮기지 않는다.**
    """
    import inspect

    signature = inspect.signature(EffectActivator.activate)

    assert "priority" not in signature.parameters


def test_f_no_second_priority_system_was_built():
    """§10 — 새 우선권 시스템 금지."""
    tree = ast.parse(pathlib.Path("engine/activation.py").read_text("utf-8"))
    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }

    assert defined == {"ActivationStatus", "ActivationError", "ActivationResult", "EffectActivator"}


# ======================================================================
# G. 결정론 · 복제 독립성 · 정보 경계
# ======================================================================


@requires_official_db
def test_g_the_same_inputs_give_the_same_link(repository):
    first, second = new_state(repository), new_state(repository)
    definition = synthetic_destroy()

    left = synthetic_activator(definition).activate(
        first,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(first), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(their_monster(first)),
        authorization=GRANTED,
    )
    right = synthetic_activator(definition).activate(
        second,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(second), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(their_monster(second)),
        authorization=GRANTED,
    )

    assert left.link.canonical_state() == right.link.canonical_state()
    assert left.chain.canonical_state() == right.chain.canonical_state()
    assert left.canonical_state() == right.canonical_state()


@requires_official_db
def test_g_failures_are_deterministic_too(repository):
    first, second = new_state(repository), new_state(repository)

    left = real_activator().activate(
        first, Chain(), activation_action(first, MST_EFFECT), picked(the_typhoon(first))
    )
    right = real_activator().activate(
        second,
        Chain(),
        activation_action(second, MST_EFFECT),
        picked(the_typhoon(second)),
    )

    assert left.canonical_state() == right.canonical_state()


@requires_official_db
def test_g_activating_on_a_clone_leaves_the_original_alone(state):
    """비용이 있는 발동이라도 복제본에서만 빠져나간다."""
    copy = state.clone()
    definition = synthetic_destroy(cost=CostGroup((LifeCost(amount=700),)))
    life_before = state.player(MINE).life_points
    before = state.state_hash()

    result = synthetic_activator(definition).activate(
        copy,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(copy), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(their_monster(copy)),
        authorization=GRANTED,
    )

    assert result.status is ActivationStatus.ACTIVATED
    assert copy.player(MINE).life_points == life_before - 700
    assert state.player(MINE).life_points == life_before
    assert state.state_hash() == before


@requires_official_db
def test_g_the_chain_is_never_mutated_in_place(state):
    """체인은 불변이다 — 발동은 **새 체인**을 돌려준다."""
    chain = Chain()
    definition = synthetic_destroy()

    result = synthetic_activator(definition).activate(
        state,
        chain,
        PlayerAction.activate_effect(
            actor=MINE, source=the_typhoon(state), effect_ref=SYNTHETIC_EFFECT
        ),
        picked(their_monster(state)),
        authorization=GRANTED,
    )

    assert len(chain) == 0
    assert len(result.chain) == 1
    assert result.chain is not chain


@requires_official_db
def test_g_no_hidden_identity_leaks_through_a_refusal(state):
    """상대의 세트 카드를 골랐을 때 그 정체가 새지 않는다."""
    result = real_activator().activate(
        state,
        Chain(),
        activation_action(state, MST_EFFECT),
        picked(their_facedown_spell(state)),
        authorization=GRANTED,
    )

    assert str(DARK_HOLE) not in result.reason
    assert str(DARK_HOLE) not in str(result.to_dict())


def test_g_every_observation_is_built_from_the_actors_seat():
    """
    발동 판정은 **행위자의 시점**으로 만든 관측만 쓴다 — 상대의 패를 보고
    판정하면 물어보는 것만으로 손패를 탐지할 수 있다.
    """
    tree = ast.parse(pathlib.Path("engine/activation.py").read_text("utf-8"))
    viewers = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg == "viewer"
    ]

    assert viewers  # 관측을 만들기는 한다
    for value in viewers:
        assert isinstance(value, ast.Attribute), ast.dump(value)
        assert value.attr == "actor", ast.dump(value)


@requires_official_db
def test_g_a_refused_activation_tells_the_actor_nothing_new(state):
    """
    세트 카드를 골라 거절당해도, 거절 사유가 그 카드의 정체를 말하지 않는다.
    """
    refusal = real_activator().activate(
        state,
        Chain(),
        activation_action(state, MST_EFFECT),
        picked(their_facedown_spell(state)),
        authorization=GRANTED,
    )
    text = str(refusal.to_dict())

    for hidden in state.player(THEIRS).hand:
        assert str(hidden.card_id) not in text
    assert str(DARK_HOLE) not in text
