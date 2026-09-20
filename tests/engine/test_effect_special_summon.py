"""
Phase 2-U — 효과가 몬스터를 **특수 소환**한다.

    Card Effect
        ↓  EffectActivator → ChainLink → ChainResolver   (2-Q · 2-R)
        ↓  EffectExecutor
        ↓  OperationKind.SPECIAL_SUMMON
        ↓  SummonProcedure          ← Phase 2-T 와 **같은 절차**
    GameState  +  MonsterSummoned(summon=SPECIAL)
        ↓  EventReader
    TimingEvent(MONSTER_SUMMONED)  →  TriggerCandidate

이 파일이 지키려는 것은 넷이다.

1. **소환법을 구현한 것이 아니다.** "이 카드를 특수 소환할 수 있는가" 는
   여전히 모르고, 모르면 소환하지 않는다 (``UNCHECKED_RULES``).
2. **플레이어가 선언한 소환과 같은 절차를 쓴다.** 두 번째 소환 엔진이
   아니다.
3. **효과로 소환되었다는 사실을 잃지 않는다** — 기존 이유 모델로.
4. **체인을 만들지 않는다.** 사건까지만 내보낸다.
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction
from engine.activation import ActivationStatus, EffectActivator
from engine.chain import Chain, ChainResolutionStatus, ChainResolver
from engine.condition import ConditionResult, IsMonster
from engine.cost import CandidateSource, ChoiceSpec, CostGroup, Selection
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectProvenance,
)
from engine.effect.delta import MonsterSummoned, SummonKind
from engine.effect.executor import (
    SUPPORTED,
    EffectExecutor,
    EffectImplementationRegistry,
)
from engine.effect.journal import EventJournal
from engine.effect.library import (
    MONSTER_REBORN,
    availability,
    definition_registry,
    entry_for,
)
from engine.effect.operation import (
    CardOperation,
    DrawOperation,
    OperationKind,
    SpecialSummonOperation,
)
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.semantics import (
    GATING_RULES,
    MISSING_GATE,
    RULE_GATED,
    UNCHECKED_SEMANTIC_RULES,
    DeclaredSummonRuling,
    UnknownSummonRuling,
)
from engine.effect.target import PRIMARY_TARGET, TargetBinding, TargetSpec
from engine.event_pipeline import EventReader, ObservedEvent
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.priority import PriorityHolder
from engine.response import ResponseLoop, ResponseOutcome
from engine.special_summon import SPECIAL_SUMMON_PROCEDURE
from engine.state.game_state import GameState
from engine.summon import SummonProcedure
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerCollector,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
)
from engine.validation import ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1

FEATHERMAN = 21844576  # 엘리멘틀 히어로 페더맨 — 통상 몬스터
BURSTINATRIX = 58932615  # 엘리멘틀 히어로 버스트레이디
DARK_HOLE = 53129443  # 블랙홀 — 몬스터가 아닌 카드
QUICKPLAY = 5318639  # 싸이크론 — 발동 경로에 쓰는 속공 마법
LAB = 2511  # synthetic 정의의 **껍데기**

PRIMARY = PRIMARY_TARGET
FROM_GRAVE = EffectRef(LAB, 0)
FROM_HAND = EffectRef(LAB, 1)

#: **테스트가 명시적으로 건네는 허가.** 소환 조건 계층을 대신하지 않는다.
GRANTED = ValidationResult.valid("테스트가 발동 타이밍을 허가했다")


# ======================================================================
# 판 · synthetic 정의
# ======================================================================


def new_state(repository) -> GameState:
    """
    p0(MINE) 패: 페더맨 · 버스트레이디 · 블랙홀
             묘지: 페더맨 1장 / SZONE: 싸이크론 (앞면, 발동에 쓴다)
    p1(THEIRS) 패: 페더맨 ×3 (가려져 있다) / 묘지: 페더맨 1장
    """
    game = GameState.create(
        repository,
        decks=(
            [QUICKPLAY, FEATHERMAN, FEATHERMAN, BURSTINATRIX, DARK_HOLE]
            + [FEATHERMAN] * 15,
            [FEATHERMAN] * 20,
        ),
    )
    game.draw(MINE, 5)
    game.draw(THEIRS, 4)
    game.move(
        game.player(MINE).hand[0], Zone.SZONE, to_player=MINE,
        position=Position.FACEUP,
    )
    game.move(game.player(MINE).hand[0], Zone.GRAVE, to_player=MINE)
    game.move(game.player(THEIRS).hand[0], Zone.GRAVE, to_player=THEIRS)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def my_grave(state: GameState) -> InstanceId:
    return state.player(MINE).grave[0].instance_id


def their_grave(state: GameState) -> InstanceId:
    return state.player(THEIRS).grave[0].instance_id


def my_hand(state: GameState, card_id: int = FEATHERMAN) -> InstanceId:
    for card in state.player(MINE).hand:
        if card.card_id == card_id:
            return card.instance_id
    raise AssertionError(f"패에 {card_id} 가 없습니다.")


def their_hand(state: GameState) -> InstanceId:
    return state.player(THEIRS).hand[0].instance_id


def the_quickplay(state: GameState) -> InstanceId:
    return state.player(MINE).spell_zone[0].instance_id


def summon_effect(
    *zones: Zone,
    ordinal: int = 0,
    owner=None,
    provenance: EffectProvenance | None = None,
    extra=(),
) -> EffectDefinition:
    """
    **synthetic 정의.** "그 몬스터를 특수 소환한다" 의 모양만 만든다 —
    어떤 실제 카드의 의미도 주장하지 않는다.
    """
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.targeting(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=frozenset(zones or (Zone.GRAVE,)),
                        owner=owner,
                        require=IsMonster(),
                    )
                )
            )
        ),
        operations=tuple(extra) + (SpecialSummonOperation(PRIMARY),),
        cost=CostGroup(),
        provenance=provenance
        or EffectProvenance.hand_written(verified=True, note="Phase 2-U 시험"),
    )


def confirmed(*instances: InstanceId) -> DeclaredSummonRuling:
    """
    **테스트가 명시적으로 선언한** 소환 판정 (Phase 2-M 의 파괴 판정과 같은
    도구). 소환 조건 계층을 대신하지 않는다 — 적히지 않은 카드는 여전히
    ``UNKNOWN`` 이라 소환되지 않는다.
    """
    return DeclaredSummonRuling(summonable=frozenset(instances))


def run(
    state: GameState,
    definition: EffectDefinition,
    *chosen: InstanceId,
    summoning=None,
    journal: EventJournal | None = None,
    registered: bool = True,
    controller: int = MINE,
    effect_ref: EffectRef | None = None,
):
    executor = EffectExecutor(
        lookup=(
            EffectImplementationRegistry((definition.effect_ref,))
            if registered
            else None
        ),
        journal=journal,
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
            controller=controller,
            selections=selections,
        ),
    )


def events_of(state: GameState, result, viewer: int = MINE):
    return EventReader(GameStateView.from_state(state, viewer=viewer)).read(
        result, actor=MINE
    )


# ======================================================================
# A. Operation 어휘 (§17 A)
# ======================================================================


def test_a_special_summon_is_its_own_operation_kind():
    operation = SpecialSummonOperation(PRIMARY)

    assert operation.kind is OperationKind.SPECIAL_SUMMON
    assert operation.target_refs == (PRIMARY,)
    assert operation.kind in SUPPORTED


def test_a_the_operation_says_it_happened_by_effect():
    """
    §4 — 기존 이유 모델을 그대로 쓴다. ``SpecialSummonReason`` 같은 새
    체계를 만들지 않았다.
    """
    operation = SpecialSummonOperation(PRIMARY)

    assert operation.reason_names == ("SPSUMMON", "EFFECT")
    assert operation.reason_mask() > 0  # constant.lua 에서 읽힌다


def test_a_the_action_kind_and_the_operation_kind_stay_apart():
    """
    §2 — 고르는 주체가 고르는 행위와 효과가 하는 일은 **다른 어휘**다
    (ADR-001). 이름이 같다고 같은 enum 으로 합치지 않는다.
    """
    from engine.action import PlayerActionKind

    assert OperationKind.SPECIAL_SUMMON is not PlayerActionKind.SPECIAL_SUMMON
    assert OperationKind.SPECIAL_SUMMON.value == PlayerActionKind.SPECIAL_SUMMON.value


def test_a_it_is_not_a_card_operation():
    """
    ``CardOperation`` 의 일들은 목적지가 표로 정해진다. 소환은 칸과 표시
    형식이 필요하고 남기는 변화도 다르다 — 그 표에 끼워 넣지 않았다.
    """
    from engine.effect.executor import DESTINATION

    assert OperationKind.SPECIAL_SUMMON not in DESTINATION
    assert not isinstance(SpecialSummonOperation(PRIMARY), CardOperation)


def test_a_the_operation_needs_a_name_not_a_card():
    """§6 — 정의에 ``InstanceId`` 를 박지 않는다."""
    with pytest.raises(TypeError):
        SpecialSummonOperation(InstanceId(3))


# ======================================================================
# B. 관문 — 소환 조건을 모르면 소환하지 않는다
# ======================================================================


@requires_official_db
def test_b_without_a_ruling_nothing_is_summoned(state):
    """
    **이 파일의 핵심이다.** "이 카드를 특수 소환할 수 있는가" 를 모르면
    소환하지 않는다 — 모르는 것을 허가로 바꾸면 소생 제한을 무시한 몬스터가
    판에 올라온다.
    """
    target = my_grave(state)
    before = state.state_hash()

    result = run(state, summon_effect(Zone.GRAVE), target)

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.applied == ()
    assert result.deltas == ()
    assert state.locate(target).zone is Zone.GRAVE
    assert state.state_hash() == before


@requires_official_db
def test_b_the_unchecked_rules_are_named(state):
    result = run(state, summon_effect(Zone.GRAVE), my_grave(state))

    assert result.unchecked_rules == UNCHECKED_SEMANTIC_RULES[
        OperationKind.SPECIAL_SUMMON
    ]
    assert any("소환 조건" in rule for rule in result.unchecked_rules)
    assert any("소생 제한" in rule for rule in result.unchecked_rules)
    assert result.missing == MISSING_GATE[OperationKind.SPECIAL_SUMMON]


@requires_official_db
def test_b_a_card_declared_unsummonable_is_refused(state):
    """판정이 ``FALSE`` 면 **틀린 대상**이지 "모름" 이 아니다."""
    target = my_grave(state)
    before = state.state_hash()

    result = run(
        state,
        summon_effect(Zone.GRAVE),
        target,
        summoning=DeclaredSummonRuling(forbidden=frozenset({target})),
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert state.state_hash() == before


def test_b_the_default_executor_carries_an_empty_ruling():
    executor = EffectExecutor()

    assert isinstance(executor.summoning, UnknownSummonRuling)
    assert (
        executor.summoning.may_be_special_summoned(InstanceId(1))
        is ConditionResult.UNKNOWN
    )


def test_b_the_gate_reuses_the_phase_2m_structure():
    """새 관문 구조를 만들지 않았다 — 파괴와 같은 표를 쓴다."""
    assert OperationKind.SPECIAL_SUMMON in RULE_GATED
    assert GATING_RULES[OperationKind.SPECIAL_SUMMON]
    assert MISSING_GATE[OperationKind.SPECIAL_SUMMON]


@requires_official_db
def test_b_a_ruling_for_another_card_does_not_carry_over(state):
    target = my_grave(state)
    before = state.state_hash()

    result = run(
        state, summon_effect(Zone.GRAVE), target, summoning=confirmed(my_hand(state))
    )

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert state.state_hash() == before


# ======================================================================
# C. 성공 경로 (§17 D · E · F · G)
# ======================================================================


@requires_official_db
def test_c_a_confirmed_effect_summon_moves_the_card(state):
    target = my_grave(state)
    before = state.state_hash()

    result = run(
        state, summon_effect(Zone.GRAVE), target, summoning=confirmed(target)
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(target).zone is Zone.MZONE
    assert state.state_hash() != before


@requires_official_db
def test_c_a_monster_can_come_from_the_hand_too(state):
    """§17 E — ``HAND → MZONE`` 도 같은 절차다."""
    target = my_hand(state)

    result = run(
        state,
        summon_effect(Zone.HAND, ordinal=1),
        target,
        summoning=confirmed(target),
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert result.deltas[0].from_zone is Zone.HAND
    assert state.locate(target).zone is Zone.MZONE


@requires_official_db
def test_c_owner_and_controller_are_preserved(state):
    """§17 G — 효과가 소환해도 주인은 바뀌지 않는다."""
    target = my_grave(state)
    before = state.find_instance(target)
    owner_before, card_id_before = before.owner, before.card_id

    run(state, summon_effect(Zone.GRAVE), target, summoning=confirmed(target))

    after = state.find_instance(target)
    assert after.instance_id == target  # 같은 CardInstance
    assert after.card_id == card_id_before
    assert after.owner == owner_before == MINE
    assert after.controller == MINE


@requires_official_db
def test_c_an_opponents_monster_lands_on_the_summoners_field(state):
    """
    **Owner ≠ Controller.** 상대의 묘지에서 소환해도 주인은 상대이고
    컨트롤러는 발동한 쪽이다.
    """
    target = their_grave(state)

    result = run(
        state,
        summon_effect(Zone.GRAVE, owner=None),
        target,
        summoning=confirmed(target),
    )
    card = state.find_instance(target)

    assert result.status is ResolutionStatus.RESOLVED
    assert card.owner == THEIRS
    assert card.controller == MINE
    assert result.deltas[0].changed_side is True


@requires_official_db
def test_c_the_normal_summon_right_is_untouched(state):
    """§16 — 효과에 의한 특수 소환도 일반 소환권을 쓰지 않는다."""
    target = my_grave(state)

    run(state, summon_effect(Zone.GRAVE), target, summoning=confirmed(target))

    assert len(state.rule_uses) == 0


@requires_official_db
def test_c_the_journal_records_the_effect_summon(state):
    journal = EventJournal()
    target = my_grave(state)

    run(
        state,
        summon_effect(Zone.GRAVE),
        target,
        summoning=confirmed(target),
        journal=journal,
    )

    assert len(journal) == 1
    recorded = list(journal)[0]
    assert recorded.applied[0].kind is OperationKind.SPECIAL_SUMMON
    assert recorded.applied[0].reason_names == ("SPSUMMON", "EFFECT")


# ======================================================================
# D. Event pipeline (§17 H · I · J · K · L)
# ======================================================================


@requires_official_db
def test_d_the_delta_is_a_monster_summoned(state):
    target = my_grave(state)

    result = run(
        state, summon_effect(Zone.GRAVE), target, summoning=confirmed(target)
    )
    delta = result.deltas[0]

    assert isinstance(delta, MonsterSummoned)
    assert delta.summon is SummonKind.SPECIAL
    assert (delta.from_zone, delta.to_zone) == (Zone.GRAVE, Zone.MZONE)
    assert delta.position is Position.FACEUP_ATTACK


@requires_official_db
def test_d_the_event_reader_sees_a_summon_not_a_move(state):
    target = my_grave(state)
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))

    result = run(
        state, summon_effect(Zone.GRAVE), target, summoning=confirmed(target)
    )
    observed = reader.read(result, actor=MINE)

    assert len(observed) == 1
    assert isinstance(observed[0], ObservedEvent)
    assert observed[0].timing.point is TimingPoint.MONSTER_SUMMONED
    assert observed[0].timing.point is not TimingPoint.CARD_MOVED
    assert observed[0].event_id


@requires_official_db
def test_d_several_triggers_share_one_summon_event(state):
    """§15 — 후보가 여럿이어도 **사건은 하나**다."""
    target = my_grave(state)
    result = run(
        state, summon_effect(Zone.GRAVE), target, summoning=confirmed(target)
    )
    event = events_of(state, result)[0]

    registry = TriggerRegistry(
        tuple(
            TriggerSpec(
                EffectRef(FEATHERMAN, ordinal),
                TimingPoint.MONSTER_SUMMONED,
                requirement=TriggerRequirement.OPTIONAL,
                activates_from=frozenset({Zone.MZONE}),
            )
            for ordinal in (0, 1)
        )
    )
    collected = TriggerCollector(
        GameStateView.from_state(state, viewer=MINE), registry
    ).collect(event.timing)

    assert len(collected.candidates) >= 2
    assert collected.event.canonical_state() == event.timing.canonical_state()
    assert target in {c.source for c in collected.candidates}


@requires_official_db
def test_d_the_summon_event_carries_the_turn_and_phase(state):
    target = my_grave(state)

    result = run(
        state, summon_effect(Zone.GRAVE), target, summoning=confirmed(target)
    )
    event = events_of(state, result)[0]

    assert event.context.turn_number == state.turn.turn_number
    assert event.context.phase is Phase.MAIN1
    assert event.instance == target


# ======================================================================
# E. 발동 → 체인 → 해결 (§9)
# ======================================================================


@requires_official_db
def test_e_an_activated_effect_summons_only_when_the_chain_resolves(state):
    """
    §9 — 기존 발동/체인 구조를 우회하지 않는다. **발동해도 아직 나오지
    않는다.**
    """
    definition = summon_effect(Zone.GRAVE)
    target = my_grave(state)
    registry = EffectDefinitionRegistry((definition,))
    activator = EffectActivator(
        registry, EffectImplementationRegistry((definition.effect_ref,))
    )
    before = state.state_hash()

    activated = activator.activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=the_quickplay(state), effect_ref=definition.effect_ref
        ),
        (TargetSelection(PRIMARY, Selection.of(target)),),
        authorization=GRANTED,
    )

    assert activated.status is ActivationStatus.ACTIVATED
    assert state.locate(target).zone is Zone.GRAVE  # 아직
    assert state.state_hash() == before

    resolver = ChainResolver(
        EffectExecutor(
            lookup=EffectImplementationRegistry((definition.effect_ref,)),
            summoning=confirmed(target),
        ),
        registry,
    )
    resolved = resolver.resolve_top(state, activated.chain)

    assert resolved.status is ChainResolutionStatus.RESOLVED
    assert state.locate(target).zone is Zone.MZONE


@requires_official_db
def test_e_a_response_loop_summon_goes_through_the_same_door(state):
    """응답으로 발동한 효과도 해결될 때에야 소환한다."""
    definition = summon_effect(Zone.GRAVE)
    target = my_grave(state)
    registry = EffectDefinitionRegistry((definition,))
    loop = ResponseLoop(
        EffectActivator(
            registry, EffectImplementationRegistry((definition.effect_ref,))
        )
    )
    response = ResponseLoop.opened(
        Chain(), PriorityHolder.of(MINE), turn_player=MINE, phase=Phase.MAIN1
    )

    result = loop.act(
        state,
        response,
        PlayerAction.activate_effect(
            actor=MINE, source=the_quickplay(state), effect_ref=definition.effect_ref
        ),
        (TargetSelection(PRIMARY, Selection.of(target)),),
        authorization=GRANTED,
    )

    assert result.outcome is ResponseOutcome.LINK_ADDED
    assert state.locate(target).zone is Zone.GRAVE  # 응답만으로는 나오지 않는다


def test_e_the_executor_never_calls_the_chain_layer():
    """§10 — 실행기가 체인 · 트리거 · 우선권을 부르지 않는다."""
    tree = ast.parse(pathlib.Path("engine/effect/executor.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    for module in ("engine.chain", "engine.trigger", "engine.response", "engine.priority"):
        assert module not in imported
    for name in ("ChainResolver", "TriggerCollector", "ResponseLoop", "resolve_all"):
        assert name not in used


def test_e_the_summon_layer_does_not_call_the_effect_executor():
    """§3 — 순환 호출을 만들지 않는다."""
    for path in ("engine/summon.py", "engine/special_summon.py"):
        tree = ast.parse(pathlib.Path(path).read_text("utf-8"))
        used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        assert "EffectExecutor" not in used, path


# ======================================================================
# F. 절차를 공유한다 (§5)
# ======================================================================


def test_f_the_effect_path_uses_the_phase_2t_procedure():
    source = pathlib.Path("engine/effect/executor.py").read_text("utf-8")

    assert "SPECIAL_SUMMON_PROCEDURE" in source
    assert isinstance(SPECIAL_SUMMON_PROCEDURE, SummonProcedure)


def test_f_the_executor_does_not_place_cards_by_itself():
    """
    자리 찾기 · 칸 고르기가 두 벌 있으면 한쪽만 고쳐지는 날이 온다.
    실행기는 ``free_slots`` 를 부르지 않는다.
    """
    tree = ast.parse(pathlib.Path("engine/effect/executor.py").read_text("utf-8"))
    used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    assert "free_slots" not in used


@requires_official_db
def test_f_both_paths_land_the_card_the_same_way(repository):
    """
    플레이어가 선언한 특수 소환과 효과에 의한 특수 소환이 **같은 자리에
    같은 표시 형식으로** 놓인다.
    """
    from engine.special_summon import special_summoning_executor

    by_effect, by_action = new_state(repository), new_state(repository)
    target_effect, target_action = my_grave(by_effect), my_grave(by_action)

    run(
        by_effect,
        summon_effect(Zone.GRAVE),
        target_effect,
        summoning=confirmed(target_effect),
    )
    special_summoning_executor().execute(
        by_action,
        PlayerAction.special_summon(MINE, target_action),
        authorization=GRANTED,
    )

    left = by_effect.find_instance(target_effect)
    right = by_action.find_instance(target_action)
    assert left.zone is right.zone is Zone.MZONE
    assert left.position is right.position
    assert by_effect.state_hash() == by_action.state_hash()


@requires_official_db
def test_f_but_the_two_paths_are_recorded_differently(state, repository):
    """
    같은 자리에 놓여도 **효과로 소환되었다는 사실**은 남는다 (§4).
    ``AppliedOperation`` 이 이유를 들고 있다.
    """
    target = my_grave(state)

    result = run(
        state, summon_effect(Zone.GRAVE), target, summoning=confirmed(target)
    )

    assert result.applied[0].kind is OperationKind.SPECIAL_SUMMON
    assert "EFFECT" in result.applied[0].reason_names
    assert "SPSUMMON" in result.applied[0].reason_names


# ======================================================================
# G. 실패 행렬 (§11 · §17 M~S · W)
# ======================================================================


@requires_official_db
def test_g_1_no_target_stops_the_effect(state):
    before = state.state_hash()

    result = run(state, summon_effect(Zone.GRAVE))

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    assert state.state_hash() == before


@requires_official_db
def test_g_2_an_illegal_target_stops_the_effect(state):
    """묘지에서 고르라고 적어 놓고 패의 카드를 골랐다."""
    before = state.state_hash()

    result = run(
        state,
        summon_effect(Zone.GRAVE),
        my_hand(state),
        summoning=confirmed(my_hand(state)),
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert state.state_hash() == before


@requires_official_db
def test_g_3_an_unknown_target_is_not_an_illegal_one(state):
    """상대의 패는 **모르는** 대상이다."""
    before = state.state_hash()

    result = run(
        state,
        summon_effect(Zone.HAND, ordinal=1, owner=None),
        their_hand(state),
        summoning=confirmed(their_hand(state)),
    )

    # 상대의 패는 **관측에 실리지 않는다** — "그 카드가 조건을 만족하는지
    # 모른다" 가 아니라 **"그 카드를 보지 못했다"** 이고, 둘은 다른 사실이다.
    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.HIDDEN_CARD
    assert result.missing  # 어느 자리를 못 봤는지 남는다
    assert state.state_hash() == before


@requires_official_db
def test_g_4_a_full_monster_zone_stops_the_effect(state):
    zone = state.zone(MINE, Zone.MZONE)
    while zone.free_slots():
        state.move(
            state.player(MINE).deck[0],
            Zone.MZONE,
            to_player=MINE,
            index=zone.free_slots()[0],
            position=Position.FACEUP_ATTACK,
        )
    target = my_grave(state)
    before = state.state_hash()

    result = run(
        state, summon_effect(Zone.GRAVE), target, summoning=confirmed(target)
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.deltas == ()
    assert state.locate(target).zone is Zone.GRAVE
    assert state.state_hash() == before


@requires_official_db
def test_g_5_a_stale_instance_stops_the_effect(state):
    """고른 뒤 그 카드가 자리를 떠났다."""
    target = my_grave(state)
    state.move(target, Zone.REMOVED, to_player=MINE)
    before = state.state_hash()

    result = run(
        state, summon_effect(Zone.GRAVE), target, summoning=confirmed(target)
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_g_6_a_card_that_never_existed_is_unknown(state):
    before = state.state_hash()

    result = run(
        state,
        summon_effect(Zone.GRAVE),
        InstanceId(9999),
        summoning=confirmed(InstanceId(9999)),
    )

    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.HIDDEN_CARD
    assert state.state_hash() == before


@requires_official_db
def test_g_7_a_text_derived_effect_never_summons(state):
    """§12 — 출처가 금지한 효과는 판정을 받아도 실행하지 않는다."""
    target = my_grave(state)
    definition = summon_effect(
        Zone.GRAVE, provenance=EffectProvenance.text_derived("유추했다고 치자")
    )
    before = state.state_hash()

    result = run(state, definition, target, summoning=confirmed(target))

    assert result.status is ResolutionStatus.FORBIDDEN
    assert state.locate(target).zone is Zone.GRAVE
    assert state.state_hash() == before


@requires_official_db
def test_g_8_an_unregistered_effect_never_summons(state):
    """§12 — ``LUA_VERIFIED`` 라도 구현이 등록되지 않으면 실행하지 않는다."""
    target = my_grave(state)
    before = state.state_hash()

    result = run(
        state,
        summon_effect(Zone.GRAVE),
        target,
        summoning=confirmed(target),
        registered=False,
    )

    assert result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert state.state_hash() == before


@requires_official_db
def test_g_9_a_context_for_another_effect_stops_it(state):
    """§17 — 다른 효과의 ``EffectRef`` 를 쓴 문맥."""
    target = my_grave(state)
    before = state.state_hash()

    result = run(
        state,
        summon_effect(Zone.GRAVE),
        target,
        summoning=confirmed(target),
        effect_ref=EffectRef(MONSTER_REBORN, 0),
    )

    assert result.status is ResolutionStatus.INVALID_CONTEXT
    assert result.code is ValidationCode.EFFECT_REF_CARD_MISMATCH
    assert state.state_hash() == before


@requires_official_db
def test_g_10_an_earlier_operation_is_cancelled_too(state):
    """
    §11 — 앞의 드로우가 멀쩡해도 뒤의 소환이 막히면 **한 장도 뽑지 않는다.**
    계획이 전부 끝난 뒤에야 적용이 시작되기 때문이다. 새 rollback 을
    만든 것이 아니라 기존 계획-후-적용 그대로다.
    """
    definition = summon_effect(
        Zone.GRAVE, extra=(DrawOperation(count=1),)
    )
    hand_before = len(state.player(MINE).hand)
    before = state.state_hash()

    result = run(state, definition, my_grave(state))  # 판정기 없음

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert len(state.player(MINE).hand) == hand_before
    assert state.state_hash() == before


# ======================================================================
# H. 결정론 · 복제 (§14 · §17 T · V)
# ======================================================================


@requires_official_db
def test_h_the_same_input_gives_the_same_result(repository):
    first, second = new_state(repository), new_state(repository)

    left = run(
        first,
        summon_effect(Zone.GRAVE),
        my_grave(first),
        summoning=confirmed(my_grave(first)),
    )
    right = run(
        second,
        summon_effect(Zone.GRAVE),
        my_grave(second),
        summoning=confirmed(my_grave(second)),
    )

    assert left.canonical_state() == right.canonical_state()
    assert first.state_hash() == second.state_hash()


@requires_official_db
def test_h_the_event_id_comes_from_the_content(repository):
    first, second = new_state(repository), new_state(repository)

    left = events_of(
        first,
        run(
            first,
            summon_effect(Zone.GRAVE),
            my_grave(first),
            summoning=confirmed(my_grave(first)),
        ),
    )
    right = events_of(
        second,
        run(
            second,
            summon_effect(Zone.GRAVE),
            my_grave(second),
            summoning=confirmed(my_grave(second)),
        ),
    )

    assert [e.event_id for e in left] == [e.event_id for e in right]


@requires_official_db
def test_h_failures_are_deterministic_too(repository):
    first, second = new_state(repository), new_state(repository)

    left = run(first, summon_effect(Zone.GRAVE), my_grave(first))
    right = run(second, summon_effect(Zone.GRAVE), my_grave(second))

    assert left.canonical_state() == right.canonical_state()
    assert left.status is ResolutionStatus.UNCHECKED_RULES


@requires_official_db
def test_h_summoning_on_a_clone_leaves_the_original_alone(state):
    copy = state.clone()
    target = my_grave(copy)
    before = state.state_hash()

    result = run(
        copy, summon_effect(Zone.GRAVE), target, summoning=confirmed(target)
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert copy.locate(target).zone is Zone.MZONE
    assert state.locate(my_grave(state)).zone is Zone.GRAVE
    assert state.state_hash() == before


# ======================================================================
# I. 정보 경계 · 실제 카드 (§8 · §13)
# ======================================================================


@requires_official_db
def test_i_a_refusal_names_no_hidden_card(state):
    hidden = state.player(THEIRS).hand[0]

    result = run(
        state,
        summon_effect(Zone.HAND, ordinal=1, owner=None),
        hidden.instance_id,
        summoning=confirmed(hidden.instance_id),
    )
    text = str(result.to_dict())

    assert str(hidden.card_id) not in text
    assert str(DARK_HOLE) not in text


@requires_official_db
def test_i_monster_reborn_is_carried_but_not_executable():
    """
    §8 — 실제 카드를 찾았고, **실행하지 않는다.**

    죽은 자의 소생(83764718)은 모양이 이 경로에 정확히 맞는다. 그런데
    후보 조건이 ``c:IsCanBeSpecialSummoned(...)`` — 카드마다 다른 소환
    조건이고, 그것을 추측 없이 옮길 수 없다. 그래서 하는 일을 적지 않은
    채로 싣는다.
    """
    from engine.effect.definition import ExecutionAvailability

    entry = entry_for(EffectRef(MONSTER_REBORN, 0))

    assert entry is not None
    assert entry.lua_file == "c83764718.lua"
    assert entry.executable is False
    assert "IsCanBeSpecialSummoned" in entry.lua_excerpt
    assert "소환 조건" in entry.note
    assert entry.definition.operations == ()
    assert (
        availability(EffectRef(MONSTER_REBORN, 0))
        is ExecutionAvailability.NO_IMPLEMENTATION
    )


@requires_official_db
def test_i_monster_reborn_does_not_run(state):
    """라이브러리에 실렸다는 사실이 실행 허가가 아니다 (ADR-006)."""
    before = state.state_hash()
    definition = definition_registry().definition_for(EffectRef(MONSTER_REBORN, 0))

    result = EffectExecutor(summoning=confirmed(my_grave(state))).execute(
        state,
        definition,
        ResolutionContext(effect_ref=definition.effect_ref, controller=MINE),
    )

    assert result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert state.state_hash() == before


def test_i_no_summon_method_was_invented():
    """§5 — 융합 · 싱크로 · 엑시즈 · 링크 · 의식 · 펜듈럼을 만들지 않았다."""
    for path in (
        "engine/effect/operation.py",
        "engine/effect/executor.py",
        "engine/special_summon.py",
        "engine/summon.py",
    ):
        source = pathlib.Path(path).read_text("utf-8")
        tree = ast.parse(source)
        names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        }
        for forbidden in ("fusion", "synchro", "xyz", "link_summon", "ritual", "pendulum"):
            assert not any(forbidden in name.lower() for name in names), (path, forbidden)


def test_i_no_second_engine_was_built():
    """§18 — 새 실행기 · 새 절차 클래스를 만들지 않았다."""
    tree = ast.parse(pathlib.Path("engine/effect/executor.py").read_text("utf-8"))
    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }

    for forbidden in (
        "SpecialSummonEngine",
        "SummonProcedure",
        "GameState",
        "EventBus",
        "TargetResolver",
    ):
        assert forbidden not in defined
