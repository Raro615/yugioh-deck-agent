"""
Phase 2-F-3-B — 트리거 발동 가능성의 최소 판정 계층.

    TriggerCandidate → TriggerEligibilityJudge.judge() → TriggerEligibility

관문을 **따로** 두고 합친다. 하나의 불리언으로 뭉개면 "무엇 때문에 안
되는가" 가 사라지고, 앞으로 규칙이 들어올 자리도 없어진다.

세 가지를 본다.

1. **관문이 분리되어 있고 합치는 순서가 원칙대로인가** — 출처 금지 >
   확실한 거부 > 판정 불가 > 통과.
2. **`ELIGIBLE` 이 "규칙상 발동 가능" 으로 새어 나가지 않는가** —
   ``unchecked_rules`` 가 남아 있는 동안은 완전한 판정이 아니다.
3. **판정이 순수한 관찰인가** — 비용을 치르지 않고, 체인에 넣지 않고,
   판을 바꾸지 않는가.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

from engine.chain import Chain
from engine.condition import (
    Always,
    AttributeIs,
    ConditionResult,
    UnimplementedRule,
)
from engine.cost import CardCost, CostGroup, LifeCost, UnimplementedCost
from engine.effect import (
    CardDrawn,
    DrawOperation,
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectImplementationRegistry,
    EffectProvenance,
    EventJournal,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.priority import PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.trigger import (
    UNCHECKED_RULES,
    EligibilityGate,
    GateVerdict,
    TimingEvent,
    TimingPoint,
    TriggerCollector,
    TriggerEligibility,
    TriggerEligibilityJudge,
    TriggerError,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
    TriggerStatus,
    TriggerWording,
)
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

MINE, THEIRS = 0, 1
WATCHER = 1000
PLAIN = 1001


# ======================================================================
# 판 · 준비
# ======================================================================


def new_state() -> GameState:
    """p0: ``WATCHER`` 1장 필드 · 1장 패 / p1: ``PLAIN`` 2장 패."""
    game = GameState.create(
        decks=([WATCHER, WATCHER, PLAIN, PLAIN], [PLAIN, PLAIN, PLAIN]),
    )
    game.draw(MINE, 2)
    game.draw(THEIRS, 2)
    game.move(game.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=MINE)


def definition(
    *,
    activation=None,
    cost=None,
    provenance=None,
    ordinal: int = 0,
) -> EffectDefinition:
    return EffectDefinition(
        effect_ref=EffectRef(WATCHER, ordinal),
        source_card_id=WATCHER,
        operations=(DrawOperation(1),),
        activation=activation,
        cost=cost if cost is not None else CostGroup(),
        provenance=provenance or EffectProvenance.official_lua(),
    )


def spec_of(
    *,
    activates_from=frozenset({Zone.MZONE}),
    condition=None,
    point: TimingPoint = TimingPoint.CARD_DRAWN,
    requirement: TriggerRequirement = TriggerRequirement.UNKNOWN,
    wording: TriggerWording = TriggerWording.UNKNOWN,
    ordinal: int = 0,
) -> TriggerSpec:
    return TriggerSpec(
        EffectRef(WATCHER, ordinal),
        point,
        requirement=requirement,
        wording=wording,
        activates_from=activates_from,
        condition=condition,
    )


def drawn_event() -> TimingEvent:
    return TimingEvent.from_delta(CardDrawn(MINE, InstanceId(3)))


def judged(
    view,
    spec: TriggerSpec,
    held: EffectDefinition | None = None,
    *,
    register_implementation: bool = True,
    event: TimingEvent | None = None,
) -> tuple[TriggerEligibility, ...]:
    """수집 → 판정을 한 번에. 두 계층이 실제로 이어지는지도 함께 본다."""
    registry = TriggerRegistry((spec,))
    definitions = EffectDefinitionRegistry((held,) if held is not None else ())
    implementations = EffectImplementationRegistry(
        [held.effect_ref] if held is not None and register_implementation else []
    )
    occurrence = event if event is not None else drawn_event()
    collection = TriggerCollector(view, registry, definitions).collect(occurrence)
    judge = TriggerEligibilityJudge(view, definitions, implementations)
    return judge.judge_all(collection, registry)


def on_field(results):
    """필드의 ``WATCHER`` 에 대한 판정 하나."""
    return next(r for r in results if r.candidate.source == InstanceId(0))


# ======================================================================
# 관문 분리와 접기
# ======================================================================


def test_every_gate_is_reported_separately(view):
    results = judged(view, spec_of(), definition())

    assert len(results) == 2  # 필드 1장 + 패 1장
    for eligibility in results:
        assert [verdict.gate for verdict in eligibility.gates] == [
            EligibilityGate.EVENT_RELATION,
            EligibilityGate.ACTIVATION_ZONE,
            EligibilityGate.TRIGGER_CONDITION,
            EligibilityGate.EXECUTION_AUTHORITY,
            EligibilityGate.COST_FEASIBILITY,
        ]


def test_a_blocked_gate_does_not_stop_the_others(view):
    """
    하나가 막혀도 나머지를 계속 본다 — 무엇이 막혔는지 전부 알아야 다음
    단계가 판단할 수 있다.
    """
    results = judged(view, spec_of(activates_from=frozenset({Zone.SZONE})), definition())

    for eligibility in results:
        assert len(eligibility.gates) == 5
        assert eligibility.status is TriggerStatus.INELIGIBLE
        blocked = eligibility.blocking
        assert [v.gate for v in blocked] == [EligibilityGate.ACTIVATION_ZONE]
        # 막힌 뒤의 관문도 실제로 판정되어 있다.
        assert eligibility.gate(EligibilityGate.COST_FEASIBILITY).passed is True


def test_a_gate_only_passes_on_valid():
    """``UNKNOWN`` 이 통과로 새지 않는다."""
    for validity, expected in [
        (ActionValidity.VALID, True),
        (ActionValidity.INVALID, False),
        (ActionValidity.UNKNOWN, False),
    ]:
        verdict = GateVerdict(
            EligibilityGate.TRIGGER_CONDITION,
            ValidationResult(validity, ValidationCode.OK, ""),
        )
        assert verdict.passed is expected


def test_the_fold_order_is_forbidden_then_invalid_then_unknown():
    """**순서가 곧 원칙이다.** 출처 금지는 다른 관문을 전부 이긴다."""
    candidate = _candidate()

    def gate(g, validity, code=ValidationCode.OK):
        return GateVerdict(g, ValidationResult(validity, code, ""))

    forbidden = gate(
        EligibilityGate.EXECUTION_AUTHORITY,
        ActionValidity.INVALID,
        ValidationCode.EXECUTION_FORBIDDEN,
    )
    invalid = gate(EligibilityGate.ACTIVATION_ZONE, ActionValidity.INVALID)
    unknown = gate(EligibilityGate.TRIGGER_CONDITION, ActionValidity.UNKNOWN)
    valid = gate(EligibilityGate.EVENT_RELATION, ActionValidity.VALID)

    assert TriggerEligibility.fold(candidate, (valid,)).status is TriggerStatus.ELIGIBLE
    assert (
        TriggerEligibility.fold(candidate, (valid, unknown)).status
        is TriggerStatus.UNKNOWN
    )
    assert (
        TriggerEligibility.fold(candidate, (valid, unknown, invalid)).status
        is TriggerStatus.INELIGIBLE
    )
    # 금지는 통과·모름·거부가 섞여 있어도 이긴다.
    assert (
        TriggerEligibility.fold(
            candidate, (valid, unknown, invalid, forbidden)
        ).status
        is TriggerStatus.FORBIDDEN
    )


def test_the_same_gate_cannot_be_judged_twice():
    candidate = _candidate()
    verdict = GateVerdict(
        EligibilityGate.EVENT_RELATION,
        ValidationResult(ActionValidity.VALID, ValidationCode.OK, ""),
    )
    with pytest.raises(TriggerError):
        TriggerEligibility(candidate, TriggerStatus.ELIGIBLE, (verdict, verdict))


def _candidate():
    from engine.trigger import TriggerCandidate

    return TriggerCandidate(
        TimingPoint.CARD_DRAWN, EffectRef(WATCHER, 0), InstanceId(0), MINE
    )


# ======================================================================
# eligible / ineligible / unknown / forbidden
# ======================================================================


def test_all_gates_passing_is_eligible(view):
    results = judged(view, spec_of(condition=Always()), definition(activation=Always()))

    field = on_field(results)
    assert field.status is TriggerStatus.ELIGIBLE
    assert field.may_activate is True
    assert field.blocking == ()


def test_eligible_does_not_claim_the_rules_were_all_checked(view):
    """
    **`ELIGIBLE` 은 "규칙상 발동 가능" 이 아니다.** 아직 보지 않은 규칙이
    목록으로 남아 있고, 그것이 이 단계의 정직한 상태다.
    """
    field = on_field(judged(view, spec_of(), definition()))

    assert field.status is TriggerStatus.ELIGIBLE
    assert field.fully_checked is False
    assert field.unchecked_rules == UNCHECKED_RULES
    assert any("timing window" in rule for rule in field.unchecked_rules)
    assert any("spell speed" in rule for rule in field.unchecked_rules)
    assert any("SEGOC" in rule for rule in field.unchecked_rules)
    assert any("activation limit" in rule for rule in field.unchecked_rules)


def test_a_wrong_zone_is_ineligible(view):
    """덱 맨 밑의 몬스터와 필드의 몬스터를 같게 다루지 않는다."""
    results = judged(view, spec_of(activates_from=frozenset({Zone.MZONE})), definition())

    field = on_field(results)
    hand = next(r for r in results if r.candidate.source != InstanceId(0))

    assert field.status is TriggerStatus.ELIGIBLE
    assert hand.status is TriggerStatus.INELIGIBLE
    zone_gate = hand.gate(EligibilityGate.ACTIVATION_ZONE)
    assert zone_gate.code is ValidationCode.SOURCE_WRONG_ZONE
    assert "HAND" in zone_gate.result.reason


def test_a_false_condition_is_ineligible(view):
    field = on_field(
        judged(view, spec_of(condition=Always(ConditionResult.FALSE)), definition())
    )

    assert field.status is TriggerStatus.INELIGIBLE
    assert field.gate(EligibilityGate.TRIGGER_CONDITION).validity is ActionValidity.INVALID


def test_an_unjudgeable_condition_is_unknown_not_ineligible(view):
    """**모르는 것을 거짓으로 접지 않는다.**"""
    field = on_field(
        judged(view, spec_of(condition=UnimplementedRule("체인 위의 카드 수")), definition())
    )

    assert field.status is TriggerStatus.UNKNOWN
    assert field.status is not TriggerStatus.INELIGIBLE
    gate = field.gate(EligibilityGate.TRIGGER_CONDITION)
    assert gate.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert any("체인 위의 카드 수" in note for note in gate.result.notes)


def test_an_undeclared_activation_zone_is_unknown_not_permission(view):
    """
    ``activates_from`` 을 적지 않았으면 "어디서든 발동 가능" 이 아니라
    **모름**이다.
    """
    field = on_field(judged(view, spec_of(activates_from=None), definition()))

    assert field.status is TriggerStatus.UNKNOWN
    gate = field.gate(EligibilityGate.ACTIVATION_ZONE)
    assert gate.validity is ActionValidity.UNKNOWN
    assert "activates_from 미선언" in gate.result.notes


def test_a_text_derived_effect_is_forbidden_even_with_everything_else_passing(view):
    """
    출처 금지가 **가장 먼저**다. 자리 · 조건 · 비용이 전부 통과해도 실행
    후보가 되지 않는다 (ADR-004).
    """
    field = on_field(
        judged(
            view,
            spec_of(condition=Always()),
            definition(activation=Always(), provenance=EffectProvenance.text_derived()),
        )
    )

    assert field.status is TriggerStatus.FORBIDDEN
    assert field.status is not TriggerStatus.INELIGIBLE
    assert field.may_activate is False
    gate = field.gate(EligibilityGate.EXECUTION_AUTHORITY)
    assert gate.code is ValidationCode.EXECUTION_FORBIDDEN
    assert gate.forbids is True
    assert "ADR-004" in gate.result.reason
    # 다른 관문은 실제로 통과해 있었다.
    assert field.gate(EligibilityGate.ACTIVATION_ZONE).passed is True
    assert field.gate(EligibilityGate.TRIGGER_CONDITION).passed is True


def test_an_unregistered_implementation_is_unknown_not_eligible(view):
    """검증된 의미만으로는 실행할 수 없다 (ADR-006)."""
    field = on_field(
        judged(view, spec_of(), definition(), register_implementation=False)
    )

    assert field.status is TriggerStatus.UNKNOWN
    gate = field.gate(EligibilityGate.EXECUTION_AUTHORITY)
    assert gate.validity is ActionValidity.UNKNOWN
    assert "no_implementation" in gate.result.notes


def test_an_unverified_source_is_unknown(view):
    field = on_field(
        judged(
            view,
            spec_of(),
            definition(provenance=EffectProvenance.hand_written(verified=False)),
        )
    )

    assert field.status is TriggerStatus.UNKNOWN
    assert "unverified" in field.gate(EligibilityGate.EXECUTION_AUTHORITY).result.notes


def test_a_missing_definition_blocks_three_gates_with_unknown(view):
    """
    정의가 없으면 조건 · 실행 권위 · 비용을 전부 확인할 수 없다. 세 관문이
    각각 ``UNKNOWN`` 이라고 말한다 — 하나로 뭉개지 않는다.
    """
    registry = TriggerRegistry((spec_of(),))
    empty = EffectDefinitionRegistry()
    collection = TriggerCollector(view, registry, empty).collect(drawn_event())
    results = TriggerEligibilityJudge(view, empty).judge_all(collection, registry)

    field = on_field(results)
    assert field.status is TriggerStatus.UNKNOWN
    for gate in (
        EligibilityGate.TRIGGER_CONDITION,
        EligibilityGate.EXECUTION_AUTHORITY,
        EligibilityGate.COST_FEASIBILITY,
    ):
        assert field.gate(gate).validity is ActionValidity.UNKNOWN
        assert "정의 미등록" in field.gate(gate).result.notes


def test_an_event_the_spec_ignores_is_ineligible(view):
    """
    사건 관계와 조건을 **따로** 둔다 — "무엇이 일어났을 때" 와 "그때 무엇이
    참이어야 하는가" 는 다른 질문이다.
    """
    spec = spec_of(point=TimingPoint.CARD_DRAWN)
    judge = TriggerEligibilityJudge(
        view,
        EffectDefinitionRegistry((definition(),)),
        EffectImplementationRegistry([EffectRef(WATCHER, 0)]),
    )
    candidate = _candidate()

    verdict = judge.judge(
        candidate, spec, TimingEvent.from_journal_event(_effect_event())
    )

    assert verdict.status is TriggerStatus.INELIGIBLE
    gate = verdict.gate(EligibilityGate.EVENT_RELATION)
    assert gate.validity is ActionValidity.INVALID
    assert "effect_resolved" in gate.result.reason


def _effect_event():
    from engine.effect import EffectEvent

    return EffectEvent(0, EffectRef(WATCHER, 0), MINE)


# ======================================================================
# 비용 — 치를 수 있는가만 본다
# ======================================================================


def test_an_affordable_cost_passes_without_being_paid(state, view):
    life = state.player(MINE).life_points
    before = state.state_hash()

    field = on_field(
        judged(view, spec_of(), definition(cost=CostGroup((LifeCost(1000),))))
    )

    assert field.status is TriggerStatus.ELIGIBLE
    assert field.gate(EligibilityGate.COST_FEASIBILITY).passed is True
    # **치르지 않았다.**
    assert state.player(MINE).life_points == life
    assert state.state_hash() == before


def test_an_unaffordable_cost_is_ineligible(state):
    state.player(MINE).life_points = 500
    view = GameStateView.from_state(state, viewer=MINE)

    field = on_field(
        judged(view, spec_of(), definition(cost=CostGroup((LifeCost(1000),))))
    )

    assert field.status is TriggerStatus.INELIGIBLE
    gate = field.gate(EligibilityGate.COST_FEASIBILITY)
    assert gate.code is ValidationCode.INSUFFICIENT_LIFE
    assert state.player(MINE).life_points == 500


def test_an_unrepresentable_cost_is_unknown(view):
    field = on_field(
        judged(
            view,
            spec_of(),
            definition(cost=CostGroup((UnimplementedCost("엑시즈 소재 제거"),))),
        )
    )

    assert field.status is TriggerStatus.UNKNOWN
    gate = field.gate(EligibilityGate.COST_FEASIBILITY)
    assert gate.code is ValidationCode.COST_NOT_IMPLEMENTED
    assert gate.validity is ActionValidity.UNKNOWN


def test_the_judge_never_pays_anything():
    """
    검증기(``CostValidator``)는 쓰고 지불기(``CostPayer``)는 쓰지 않는다.

    이름이 설명문에 나오는 것과 실제로 부르는 것은 다르므로, **import 와
    호출**로 확인한다.
    """
    import ast

    import engine.trigger as module

    source = __import__("pathlib").Path("engine/trigger.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "CostValidator" in imported
    assert "CostPayer" not in imported
    assert not hasattr(module, "CostPayer")

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "CostPayer" not in called

    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(name.startswith("engine.payment") for name in modules)
    assert not any(name.startswith("engine.chain") for name in modules)
    assert not any(name.startswith("engine.priority") for name in modules)

    for forbidden in ("pay", "pay_cost", "settle"):
        assert not hasattr(TriggerEligibilityJudge, forbidden), forbidden


# ======================================================================
# 강제/임의 · WHEN/IF — 실려 나가되 판정에 쓰이지 않는다
# ======================================================================


def test_requirement_and_wording_ride_along_without_changing_the_verdict(view):
    """
    SEGOC 와 trigger ordering 이 쓸 수 있게 **보존**하되, 지금 판정에
    끼어들지 않는다.
    """
    results = {}
    for requirement in (TriggerRequirement.MANDATORY, TriggerRequirement.OPTIONAL):
        for wording in (TriggerWording.WHEN, TriggerWording.IF):
            field = on_field(
                judged(
                    view,
                    spec_of(requirement=requirement, wording=wording),
                    definition(),
                )
            )
            results[(requirement, wording)] = field

    statuses = {field.status for field in results.values()}
    assert statuses == {TriggerStatus.ELIGIBLE}  # 넷 다 같은 판정

    for (requirement, wording), field in results.items():
        assert field.requirement is requirement
        assert field.wording is wording

    # 강제/임의는 불리언 하나로 뭉개지지 않는다.
    assert set(TriggerRequirement) == {
        TriggerRequirement.MANDATORY,
        TriggerRequirement.OPTIONAL,
        TriggerRequirement.UNKNOWN,
    }


def test_no_segoc_or_missed_timing_rule_was_smuggled_in():
    import engine.trigger as module

    source = __import__("pathlib").Path("engine/trigger.py").read_text(encoding="utf-8")

    assert "missed" not in source.lower()
    for forbidden in ("SEGOC", "order_triggers", "sort_by_spell_speed", "SpellSpeed"):
        assert not hasattr(module, forbidden), forbidden
    # 아직 안 본 규칙들은 **숨기지 않고 목록으로** 남아 있다.
    assert len(UNCHECKED_RULES) >= 5


# ======================================================================
# 가려진 정보
# ======================================================================


def test_a_card_that_is_not_visible_keeps_the_zone_gate_unknown(state):
    """
    "보이지 않는다 = 없다 = FALSE" 로 처리하지 않는다.
    """
    hidden = state.player(THEIRS).hand[0]
    view = GameStateView.from_state(state, viewer=MINE)
    judge = TriggerEligibilityJudge(
        view,
        EffectDefinitionRegistry((definition(),)),
        EffectImplementationRegistry([EffectRef(WATCHER, 0)]),
    )
    from engine.trigger import TriggerCandidate

    candidate = TriggerCandidate(
        TimingPoint.CARD_DRAWN, EffectRef(WATCHER, 0), hidden.instance_id, THEIRS
    )

    verdict = judge.judge(candidate, spec_of(), drawn_event())

    assert verdict.status is TriggerStatus.UNKNOWN
    gate = verdict.gate(EligibilityGate.ACTIVATION_ZONE)
    assert gate.validity is ActionValidity.UNKNOWN
    assert gate.code is ValidationCode.HIDDEN_CARD


def test_a_condition_about_an_unreadable_card_stays_unknown(view):
    field = on_field(
        judged(view, spec_of(condition=AttributeIs("DARK")), definition())
    )

    assert field.status is TriggerStatus.UNKNOWN
    assert field.gate(EligibilityGate.TRIGGER_CONDITION).result.notes


def test_the_judge_refuses_a_raw_game_state(state):
    with pytest.raises(TypeError):
        TriggerEligibilityJudge(state)
    view = GameStateView.from_state(state, viewer=MINE)
    with pytest.raises(TypeError):
        TriggerEligibilityJudge(view, object())
    with pytest.raises(TypeError):
        TriggerEligibilityJudge(view, EffectDefinitionRegistry(), object())


def test_a_candidate_and_a_spec_must_name_the_same_effect(view):
    judge = TriggerEligibilityJudge(view)
    with pytest.raises(TriggerError):
        judge.judge(_candidate(), spec_of(ordinal=1), drawn_event())


# ======================================================================
# Mutation safety
# ======================================================================


def test_judging_never_touches_the_board_or_the_history(state):
    view = GameStateView.from_state(state, viewer=MINE)
    journal = EventJournal()
    chain = Chain().activate(MINE, EffectRef(WATCHER, 0))
    priority = PriorityState.opened(ResponseWindow.RESPONSE, THEIRS)

    before = (
        state.state_hash(),
        journal.canonical_state(),
        chain.canonical_state(),
        priority.canonical_state(),
        state.player(MINE).life_points,
        [(c.instance_id, c.zone, c.controller, c.owner) for c in state.all_instances()],
    )

    for held in (
        definition(cost=CostGroup((LifeCost(1000), CardCost.discard(1)))),
        definition(activation=Always(), ordinal=1),
        definition(provenance=EffectProvenance.text_derived(), ordinal=2),
    ):
        spec = spec_of(ordinal=held.effect_ref.ordinal)
        judged(view, spec, held)

    assert state.state_hash() == before[0]
    assert journal.canonical_state() == before[1]
    assert chain.canonical_state() == before[2]
    assert priority.canonical_state() == before[3]
    assert state.player(MINE).life_points == before[4]
    assert [
        (c.instance_id, c.zone, c.controller, c.owner) for c in state.all_instances()
    ] == before[5]
    assert len(journal) == 0 and chain.resolved_count == 0


def test_the_eligibility_layer_cannot_reach_the_chain(view):
    """체인에 넣는 것은 이 계층의 일이 아니다."""
    field = on_field(judged(view, spec_of(), definition()))

    with pytest.raises(TypeError):
        Chain().push(field)
    with pytest.raises(TypeError):
        Chain().push(field.candidate)

    import ast

    tree = ast.parse(
        __import__("pathlib").Path("engine/trigger.py").read_text(encoding="utf-8")
    )
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    for module_name in ("engine.chain", "engine.priority"):
        assert not any(name.startswith(module_name) for name in modules), module_name


def test_an_eligibility_result_is_immutable(view):
    field = on_field(judged(view, spec_of(), definition()))

    for name, value in [("status", TriggerStatus.INELIGIBLE), ("gates", ())]:
        with pytest.raises(Exception):
            setattr(field, name, value)
    assert isinstance(field.gates, tuple)
    assert isinstance(field.unchecked_rules, tuple)


def test_a_cloned_board_is_unaffected(state):
    copy = state.clone()
    judged(GameStateView.from_state(copy, viewer=MINE), spec_of(), definition())

    assert copy.state_hash() == state.state_hash()
    copy.player(MINE).change_life(-1000)
    assert copy.state_hash() != state.state_hash()
    assert state.player(MINE).life_points == 8000


# ======================================================================
# 결정론
# ======================================================================


def test_the_same_input_gives_the_same_verdict():
    results = []
    for _ in range(2):
        board = new_state()
        view = GameStateView.from_state(board, viewer=MINE)
        results.append(
            tuple(
                e.canonical_state()
                for e in judged(
                    view,
                    spec_of(condition=Always()),
                    definition(cost=CostGroup((LifeCost(1000),))),
                )
            )
        )

    assert results[0] == results[1]


def test_the_verdict_serializes_to_plain_data(view):
    field = on_field(
        judged(view, spec_of(condition=Always()), definition(cost=CostGroup((LifeCost(100),))))
    )

    data = field.to_dict()
    text = json.dumps(data, ensure_ascii=False)

    assert "0x" not in text and "object at" not in text
    assert data["status"] == "eligible"
    assert [gate["gate"] for gate in data["gates"]] == [
        "event_relation",
        "activation_zone",
        "trigger_condition",
        "execution_authority",
        "cost_feasibility",
    ]
    assert data["unchecked_rules"]
    assert data["candidate"]["effect_ref"] == {"card_id": WATCHER, "ordinal": 0}
    assert "e1" not in text


def test_the_serialization_does_not_depend_on_the_hash_seed():
    snippet = textwrap.dedent(
        """
        import json
        from engine.condition import Always
        from engine.cost import CostGroup, LifeCost
        from engine.effect import (
            CardDrawn, DrawOperation, EffectDefinition, EffectDefinitionRegistry,
            EffectImplementationRegistry, EffectProvenance,
        )
        from engine.game_state_view import GameStateView
        from engine.ids import EffectRef, InstanceId
        from engine.state.game_state import GameState
        from engine.trigger import (
            TimingEvent, TimingPoint, TriggerCollector, TriggerEligibilityJudge,
            TriggerRegistry, TriggerSpec,
        )
        from engine.vocabulary import Position, Zone

        game = GameState.create(decks=([1000, 1000, 1001], [1001, 1001]))
        game.draw(0, 2)
        game.draw(1, 2)
        game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
        view = GameStateView.from_state(game, viewer=0)

        held = EffectDefinition(
            effect_ref=EffectRef(1000, 0), source_card_id=1000,
            operations=(DrawOperation(1),), activation=Always(),
            cost=CostGroup((LifeCost(500),)),
            provenance=EffectProvenance.official_lua(),
        )
        spec = TriggerSpec(
            EffectRef(1000, 0), TimingPoint.CARD_DRAWN,
            activates_from=frozenset({Zone.MZONE, Zone.SZONE, Zone.GRAVE}),
        )
        registry = TriggerRegistry((spec,))
        definitions = EffectDefinitionRegistry((held,))
        collection = TriggerCollector(view, registry, definitions).collect(
            TimingEvent.from_delta(CardDrawn(0, InstanceId(1)))
        )
        judge = TriggerEligibilityJudge(
            view, definitions, EffectImplementationRegistry([held.effect_ref])
        )
        print(json.dumps(
            [e.canonical_state() for e in judge.judge_all(collection, registry)],
            ensure_ascii=False, sort_keys=True,
        ))
        """
    )
    outputs = []
    for seed in ("0", "1", "31337"):
        finished = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            env=dict(os.environ, PYTHONHASHSEED=seed),
            cwd=os.getcwd(),
        )
        assert finished.returncode == 0, finished.stderr
        outputs.append(finished.stdout)
    assert len(set(outputs)) == 1


def test_collection_status_and_eligibility_status_are_allowed_to_differ(view):
    """
    수집 단계의 ``candidate.status`` 는 타이밍과 조건까지만 본 값이다.
    발동 가능성 전체는 ``TriggerEligibility.status`` 가 답하고, **둘은 다를
    수 있다** — 그 차이가 정보다.
    """
    field = on_field(
        judged(view, spec_of(), definition(), register_implementation=False)
    )

    assert field.candidate.status is TriggerStatus.ELIGIBLE  # 조건은 참이었다
    assert field.status is TriggerStatus.UNKNOWN  # 구현이 없다
    assert field.candidate.status is not field.status
