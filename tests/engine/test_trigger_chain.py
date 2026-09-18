"""
Phase 2-F-3-D — 트리거 결과를 체인에 잇는 최소 통합.

    TimingEvent → 수집 → 적격성 → 정리 → TriggerChainPlan → 새 Chain

네 가지를 본다.

1. **후보와 링크가 다른 것인가** — 필요한 정보가 없으면 링크를 만들지
   않는가.
2. **삽입 경계가 지켜지는가** — ``ELIGIBLE`` 만 들어가고, ``UNKNOWN`` 은
   빠지되 "없다" 로 결론나지 않는가.
3. **`TEXT_DERIVED` 가 실행 경로에 들어가지 못하는가.**
4. **아무것도 실행되지 않는가** — 체인에 넣는 것과 해결하는 것이 따로인가.
"""

import ast
import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from engine.chain import Chain, ChainError, ChainLink, ChainResolver
from engine.condition import Always, ConditionResult, UnimplementedRule
from engine.cost import CandidateSource, CardCost, ChoiceSpec, CostGroup, LifeCost
from engine.effect import (
    CardDrawn,
    DrawOperation,
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectExecutor,
    EffectImplementationRegistry,
    EffectProvenance,
    EventJournal,
    TargetBinding,
    TargetSpec,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerCandidate,
    TriggerEligibility,
    TriggerError,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
    TriggerStatus,
)
from engine.trigger_chain import (
    ChainInsertion,
    TriggerChainEntry,
    TriggerChainIntegrator,
    TriggerChainPlan,
)
from engine.trigger_order import TriggerOrderer
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

MINE, THEIRS = 0, 1
ALPHA, BETA = 1000, 1001


# ======================================================================
# 판 · 준비
# ======================================================================


def new_state() -> GameState:
    """p0: ``ALPHA`` 2장 필드 · ``BETA`` 1장 패 / p1: ``BETA`` 1장 필드."""
    game = GameState.create(
        decks=([ALPHA, ALPHA, BETA, ALPHA], [BETA, BETA, BETA]),
    )
    game.draw(MINE, 3)
    game.draw(THEIRS, 2)
    game.move(game.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.move(game.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.move(game.player(THEIRS).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=MINE)


def drawn_event() -> TimingEvent:
    return TimingEvent.from_delta(CardDrawn(MINE, InstanceId(5)))


def definition(
    card_id: int = ALPHA,
    ordinal: int = 0,
    *,
    activation=Always(),
    cost=None,
    targets=(),
    provenance=None,
) -> EffectDefinition:
    return EffectDefinition(
        effect_ref=EffectRef(card_id, ordinal),
        source_card_id=card_id,
        operations=(DrawOperation(1),) if not targets else (),
        activation=activation,
        cost=cost if cost is not None else CostGroup(),
        targets=targets,
        provenance=provenance or EffectProvenance.official_lua(),
    )


def spec(
    card_id: int = ALPHA,
    ordinal: int = 0,
    *,
    requirement: TriggerRequirement = TriggerRequirement.UNKNOWN,
    activates_from=frozenset({Zone.MZONE}),
) -> TriggerSpec:
    return TriggerSpec(
        EffectRef(card_id, ordinal),
        TimingPoint.CARD_DRAWN,
        requirement=requirement,
        activates_from=activates_from,
    )


def integrator(
    view,
    specs,
    definitions=(),
    *,
    register_implementations=True,
) -> TriggerChainIntegrator:
    registry = TriggerRegistry(tuple(specs))
    held = EffectDefinitionRegistry(tuple(definitions))
    implementations = EffectImplementationRegistry(
        [d.effect_ref for d in definitions] if register_implementations else []
    )
    return TriggerChainIntegrator(view, registry, held, implementations)


def planned(view, specs, definitions=(), chain=None, **kwargs) -> TriggerChainPlan:
    integ = integrator(view, specs, definitions, **kwargs)
    ordering = integ.collect_and_order(drawn_event())
    return integ.plan(chain if chain is not None else Chain(), ordering)


# ======================================================================
# A. ELIGIBLE → 체인 1개
# ======================================================================


def test_an_eligible_trigger_becomes_exactly_one_link(view):
    held = definition()
    integ = integrator(view, (spec(),), (held,))
    ordering = integ.collect_and_order(drawn_event())
    plan = integ.plan(Chain(), ordering)

    # 필드에 ALPHA 가 2장이므로 후보도 2개다.
    assert len(plan.insertable) == 2
    extended = integ.extend(Chain(), plan)

    assert len(extended) == 2
    assert all(isinstance(link, ChainLink) for link in extended)
    assert [link.sequence for link in extended] == [0, 1]
    assert {link.effect_ref for link in extended} == {EffectRef(ALPHA, 0)}
    assert {link.actor for link in extended} == {MINE}


def test_a_link_carries_the_candidates_instance_not_just_the_card(view):
    """
    **Card Definition 과 Card Instance 를 혼동하지 않는다.** 같은 카드 2장이
    각자의 링크가 된다.
    """
    plan = planned(view, (spec(),), (definition(),))

    sources = [entry.link.source for entry in plan.insertable]
    assert len(sources) == 2
    assert len(set(sources)) == 2  # 서로 다른 인스턴스
    assert all(isinstance(source, InstanceId) for source in sources)


def test_extending_returns_a_new_chain_and_leaves_the_old_one_alone(view):
    original = Chain()
    integ = integrator(view, (spec(),), (definition(),))
    plan = integ.plan(original, integ.collect_and_order(drawn_event()))

    extended = integ.extend(original, plan)

    assert len(original) == 0
    assert len(extended) == 2
    assert original.canonical_state() != extended.canonical_state()


def test_a_plan_built_for_another_chain_is_refused(view):
    integ = integrator(view, (spec(),), (definition(),))
    plan = integ.plan(Chain(), integ.collect_and_order(drawn_event()))
    other = Chain().activate(THEIRS, EffectRef(BETA, 0))

    with pytest.raises(TriggerError):
        integ.extend(other, plan)


def test_links_continue_the_numbering_of_a_chain_that_already_has_links(view):
    existing = Chain().activate(THEIRS, EffectRef(BETA, 0))
    integ = integrator(view, (spec(),), (definition(),))
    plan = integ.plan(existing, integ.collect_and_order(drawn_event()))

    assert [entry.link.sequence for entry in plan.insertable] == [1, 2]
    extended = integ.extend(existing, plan)
    assert [link.sequence for link in extended] == [0, 1, 2]


def test_a_chain_that_started_resolving_accepts_nothing(view):
    """해결 중 발동은 타이밍 계층의 몫이다. 조용히 끼워 넣지 않는다."""
    started = Chain().activate(THEIRS, EffectRef(BETA, 0)).advanced()
    plan = planned(view, (spec(),), (definition(),), chain=started)

    assert plan.insertable == ()
    assert plan.links == ()
    assert all(
        entry.insertion is ChainInsertion.NOT_INSERTABLE for entry in plan.entries
    )
    assert integrator(view, (spec(),), (definition(),)).extend(started, plan) == started

    # 체인에 직접 넣으면 예외다. 통합 계층은 예외 대신 **판정**을 돌려준다.
    with pytest.raises(ChainError):
        started.push(ChainLink(1, MINE, EffectRef(ALPHA, 0)))


# ======================================================================
# B~D. INELIGIBLE / FORBIDDEN / UNKNOWN
# ======================================================================


def test_an_ineligible_trigger_never_reaches_the_chain(view):
    plan = planned(
        view,
        (spec(),),
        (definition(activation=Always(ConditionResult.FALSE)),),
    )

    assert plan.insertable == ()
    assert len(plan.skipped) == 2
    assert all(
        entry.insertion is ChainInsertion.NOT_INSERTABLE for entry in plan.skipped
    )
    assert all("조건" in entry.reason for entry in plan.skipped)


def test_a_forbidden_trigger_never_reaches_the_chain(view):
    plan = planned(
        view,
        (spec(),),
        (definition(provenance=EffectProvenance.text_derived()),),
    )

    assert plan.insertable == ()
    assert len(plan.skipped) == 2
    for entry in plan.skipped:
        assert entry.insertion is ChainInsertion.NOT_INSERTABLE
        assert entry.code is ValidationCode.EXECUTION_FORBIDDEN
        assert entry.link is None


def test_an_unknown_trigger_is_kept_apart_and_not_called_absent(view):
    """
    **``UNKNOWN`` 을 "트리거가 없다" 로 결론내지 않는다.** 이유도 남는다.
    """
    plan = planned(
        view,
        (spec(),),
        (definition(activation=UnimplementedRule("체인 위의 카드 수")),),
    )

    assert plan.insertable == ()
    assert len(plan.unresolved) == 2
    for entry in plan.unresolved:
        assert entry.insertion is ChainInsertion.UNKNOWN
        assert entry.insertion is not ChainInsertion.NOT_INSERTABLE
        assert entry.code is ValidationCode.INFORMATION_UNAVAILABLE
        assert "트리거가 없다는 뜻이 아닙니다" in entry.reason
        assert any("체인 위의 카드 수" in note for note in entry.notes)
    assert plan.skipped == ()  # 제외 통에 섞이지 않았다


def test_unknown_is_never_promoted_to_insertable():
    """``permits_insertion`` 은 ``INSERTABLE`` 일 때만 참이다."""
    assert ChainInsertion.INSERTABLE.permits_insertion is True
    for insertion in ChainInsertion:
        if insertion is not ChainInsertion.INSERTABLE:
            assert insertion.permits_insertion is False


def test_every_judged_candidate_lands_in_exactly_one_bucket(view):
    """조용히 사라지는 후보가 없다."""
    plan = planned(
        view,
        (spec(ALPHA, 0), spec(ALPHA, 1), spec(BETA, 0)),
        (
            definition(ALPHA, 0),
            definition(ALPHA, 1, activation=Always(ConditionResult.FALSE)),
            definition(BETA, 0, activation=UnimplementedRule("모르는 규칙")),
        ),
    )

    landed = plan.entries + plan.skipped + plan.unresolved
    identities = [entry.identity for entry in landed]
    assert len(identities) == len(set(identities))
    assert len(plan.skipped) >= 2 and len(plan.unresolved) >= 1


# ======================================================================
# E~F. 실행 권한 경계
# ======================================================================


def test_a_text_derived_effect_is_analysed_but_never_becomes_a_link(view):
    """
    후보 분석 자체는 된다. **실행 경로로 승격되지 않는다** (ADR-004).
    """
    held = definition(provenance=EffectProvenance.text_derived("공식 텍스트"))
    integ = integrator(view, (spec(),), (held,))
    ordering = integ.collect_and_order(drawn_event())

    # 후보로는 존재한다.
    assert len(ordering.excluded) == 2
    assert all(e.status is TriggerStatus.FORBIDDEN for e in ordering.excluded)

    plan = integ.plan(Chain(), ordering)
    assert plan.links == ()
    assert integ.extend(Chain(), plan) == Chain()


def test_a_forbidden_source_is_refused_even_if_the_verdict_says_eligible(view):
    """
    **마지막 문에서 다시 확인한다.** 손으로 만든 ``ELIGIBLE`` 판정이
    ADR-004 를 뚫지 못한다.
    """
    held = definition(provenance=EffectProvenance.text_derived())
    integ = integrator(view, (spec(),), (held,))
    forged = TriggerEligibility(
        TriggerCandidate(
            TimingPoint.CARD_DRAWN, EffectRef(ALPHA, 0), InstanceId(0), MINE,
            status=TriggerStatus.ELIGIBLE,
        ),
        TriggerStatus.ELIGIBLE,
    )
    ordering = TriggerOrderer(view).order(drawn_event(), (forged,))
    assert len(ordering.canonical_sequence) == 1  # 정리 계층은 통과했다

    plan = integ.plan(Chain(), ordering)

    assert plan.links == ()
    entry = plan.entries[0]
    assert entry.insertion is ChainInsertion.NOT_INSERTABLE
    assert entry.code is ValidationCode.EXECUTION_FORBIDDEN


def test_verified_meaning_is_not_the_same_as_implemented(view):
    """``LUA_VERIFIED`` 라도 구현이 등록되어 있지 않으면 실행하지 않는다 (ADR-006)."""
    plan = planned(
        view, (spec(),), (definition(),), register_implementations=False
    )

    assert plan.links == ()
    assert len(plan.unresolved) == 2
    for entry in plan.unresolved:
        assert entry.insertion is ChainInsertion.UNKNOWN
        assert "no_implementation" in entry.notes


def test_a_missing_definition_is_unknown_not_a_fabricated_link(view):
    """정의가 없으면 무엇이 필요한지도 모른다. 링크를 지어내지 않는다."""
    forged = TriggerEligibility(
        TriggerCandidate(
            TimingPoint.CARD_DRAWN, EffectRef(ALPHA, 9), InstanceId(0), MINE,
            status=TriggerStatus.ELIGIBLE,
        ),
        TriggerStatus.ELIGIBLE,
    )
    integ = integrator(view, (spec(),), ())
    ordering = TriggerOrderer(view).order(drawn_event(), (forged,))

    plan = integ.plan(Chain(), ordering)

    entry = plan.entries[0]
    assert entry.insertion is ChainInsertion.UNKNOWN
    assert entry.code is ValidationCode.CHAIN_DEFINITION_UNAVAILABLE
    assert entry.link is None


# ======================================================================
# O. 실행 정보가 없는 후보 — 가짜 링크를 만들지 않는다
# ======================================================================


def test_an_effect_that_needs_a_target_is_not_inserted_with_an_empty_selection(view):
    """
    **핵심이다.** 대상 선택은 트리거 계층 밖에서 정해진다. 빈 선택으로
    채워 넣으면 대상 없이 해결되는 효과가 조용히 판에 들어간다.
    """
    targeting = EffectDefinition(
        effect_ref=EffectRef(ALPHA, 0),
        source_card_id=ALPHA,
        targets=TargetBinding.single(
            TargetSpec.targeting(
                ChoiceSpec(source=CandidateSource(zones=frozenset({Zone.MZONE})))
            )
        ),
        activation=Always(),
        provenance=EffectProvenance.official_lua(),
    )

    plan = planned(view, (spec(),), (targeting,))

    assert plan.links == ()
    assert len(plan.blocked) == 2
    for entry in plan.blocked:
        assert entry.insertion is ChainInsertion.NOT_INSERTABLE
        assert entry.code is ValidationCode.TOO_FEW_SELECTED
        assert any("대상 선택" in note for note in entry.notes)
        assert entry.link is None


def test_an_effect_with_a_cost_is_not_inserted_without_a_receipt(view):
    """비용은 링크가 만들어지기 **전에** 치러진다 (Phase 2-E · 2-F-2)."""
    plan = planned(
        view, (spec(),), (definition(cost=CostGroup((LifeCost(500),))),)
    )

    assert plan.links == ()
    assert len(plan.blocked) == 2
    for entry in plan.blocked:
        assert entry.code is ValidationCode.COST_NOT_IMPLEMENTED
        assert any("영수증" in note for note in entry.notes)
        assert "가짜로 채워 넣지 않습니다" in entry.reason


def test_a_blocked_candidate_is_not_the_same_as_an_absent_one(view):
    """
    조건은 통과했는데 정보가 없어 막힌 것은 "다음 계층이 할 일이 있다" 는
    뜻이다.
    """
    plan = planned(
        view,
        (spec(),),
        (definition(cost=CostGroup((CardCost.discard(1),))),),
    )

    assert plan.blocked and plan.skipped == () and plan.unresolved == ()
    assert plan.needs_decision is True
    assert plan.is_empty is True


def test_an_entry_cannot_claim_insertable_without_a_link():
    forged = TriggerEligibility(
        TriggerCandidate(
            TimingPoint.CARD_DRAWN, EffectRef(ALPHA, 0), InstanceId(0), MINE
        ),
        TriggerStatus.ELIGIBLE,
    )
    with pytest.raises(TriggerError):
        TriggerChainEntry(forged, ChainInsertion.INSERTABLE)
    with pytest.raises(TriggerError):
        TriggerChainEntry(
            forged,
            ChainInsertion.UNKNOWN,
            link=ChainLink(0, MINE, EffectRef(ALPHA, 0)),
        )


# ======================================================================
# G~H. identity
# ======================================================================


def test_two_copies_of_one_card_make_two_distinct_links(view):
    plan = planned(view, (spec(),), (definition(),))

    links = plan.links
    assert len(links) == 2
    assert len({link.source for link in links}) == 2
    assert len({link.effect_ref for link in links}) == 1  # 정의는 하나


def test_two_cards_sharing_a_lua_variable_name_never_collide(view):
    """
    ``EffectSpec.index`` 는 Lua 변수명(``"e1"``)이라 서로 다른 카드가 같은
    이름을 쓴다. identity 가 ``EffectRef(card_id, ordinal)`` 이므로 섞이지
    않는다.
    """
    # BETA 는 상대 필드에 있으므로 BETA 트리거는 상대 것이 된다.
    plan = planned(
        view,
        (spec(ALPHA, 0), spec(BETA, 0)),
        (definition(ALPHA, 0), definition(BETA, 0)),
    )

    refs = {link.effect_ref for link in plan.links}
    assert EffectRef(ALPHA, 0) in refs
    assert EffectRef(BETA, 0) in refs
    assert len({ref.card_id for ref in refs}) == 2
    assert len({ref.ordinal for ref in refs}) == 1  # ordinal 은 같다
    assert "e1" not in json.dumps(plan.to_dict(), ensure_ascii=False)


def test_the_link_actor_is_the_controller_not_the_turn_player(state):
    """owner · controller · actor 를 섞지 않는다."""
    view = GameStateView.from_state(state, viewer=MINE)
    plan = planned(view, (spec(BETA, 0),), (definition(BETA, 0),))

    assert view.turn_player == MINE
    assert plan.links  # 상대 필드의 BETA
    for link in plan.links:
        assert link.actor == THEIRS
        assert link.actor != view.turn_player


def test_the_candidate_identity_survives_even_when_not_inserted(view):
    plan = planned(
        view, (spec(),), (definition(activation=Always(ConditionResult.FALSE)),)
    )

    for entry in plan.skipped:
        assert entry.identity == entry.candidate.identity
        assert entry.identity[1] == ALPHA
        assert isinstance(entry.identity[3], int)


# ======================================================================
# I. 결정론
# ======================================================================


def test_the_plan_does_not_reorder_what_the_ordering_decided(view):
    integ = integrator(
        view,
        (spec(ALPHA, 0, requirement=TriggerRequirement.OPTIONAL),
         spec(ALPHA, 1, requirement=TriggerRequirement.MANDATORY)),
        (definition(ALPHA, 0), definition(ALPHA, 1)),
    )
    ordering = integ.collect_and_order(drawn_event())

    plan = integ.plan(Chain(), ordering)

    assert [entry.identity for entry in plan.entries] == [
        e.candidate.identity for e in ordering.canonical_sequence
    ]


def test_the_same_input_gives_the_same_plan():
    results = []
    for _ in range(2):
        board = new_state()
        view = GameStateView.from_state(board, viewer=MINE)
        results.append(
            planned(
                view,
                (spec(ALPHA, 0), spec(BETA, 0)),
                (definition(ALPHA, 0), definition(BETA, 0)),
            ).canonical_state()
        )

    assert results[0] == results[1]


def test_the_plan_carries_the_unresolved_order_rules_forward(view):
    """
    순서가 규칙으로 정해지지 않았다는 사실이 여기서 사라지지 않는다.
    """
    plan = planned(view, (spec(),), (definition(),))

    assert plan.is_rule_ordered is False
    assert plan.unresolved_rules
    assert any("SEGOC" in rule for rule in plan.unresolved_rules)
    assert plan.needs_decision is True


def test_the_plan_serializes_to_plain_data(view):
    plan = planned(
        view,
        (spec(ALPHA, 0), spec(ALPHA, 1)),
        (definition(ALPHA, 0), definition(ALPHA, 1, cost=CostGroup((LifeCost(100),)))),
    )

    data = plan.to_dict()
    text = json.dumps(data, ensure_ascii=False)

    assert "0x" not in text and "object at" not in text
    assert data["is_rule_ordered"] is False
    assert data["needs_decision"] is True
    assert any(entry["insertion"] == "insertable" for entry in data["entries"])
    assert any(entry.get("link") for entry in data["entries"])


def test_the_serialization_does_not_depend_on_the_hash_seed():
    snippet = textwrap.dedent(
        """
        import json
        from engine.chain import Chain
        from engine.condition import Always
        from engine.cost import CostGroup, LifeCost
        from engine.effect import (
            CardDrawn, DrawOperation, EffectDefinition, EffectDefinitionRegistry,
            EffectImplementationRegistry, EffectProvenance,
        )
        from engine.game_state_view import GameStateView
        from engine.ids import EffectRef, InstanceId
        from engine.state.game_state import GameState
        from engine.trigger import TimingEvent, TimingPoint, TriggerRegistry, TriggerSpec
        from engine.trigger_chain import TriggerChainIntegrator
        from engine.vocabulary import Position, Zone

        game = GameState.create(decks=([1000, 1000, 1001, 1000], [1001, 1001, 1001]))
        game.draw(0, 3)
        game.draw(1, 2)
        game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
        game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
        game.move(game.player(1).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
        view = GameStateView.from_state(game, viewer=0)

        held = tuple(
            EffectDefinition(
                effect_ref=EffectRef(card, ordinal), source_card_id=card,
                operations=(DrawOperation(1),), activation=Always(),
                cost=CostGroup((LifeCost(100),)) if ordinal else CostGroup(),
                provenance=EffectProvenance.official_lua(),
            )
            for card in (1000, 1001)
            for ordinal in (0, 1)
        )
        specs = tuple(
            TriggerSpec(d.effect_ref, TimingPoint.CARD_DRAWN,
                        activates_from=frozenset({Zone.MZONE, Zone.HAND}))
            for d in held
        )
        integ = TriggerChainIntegrator(
            view, TriggerRegistry(specs), EffectDefinitionRegistry(held),
            EffectImplementationRegistry([d.effect_ref for d in held]),
        )
        ordering = integ.collect_and_order(
            TimingEvent.from_delta(CardDrawn(0, InstanceId(5)))
        )
        plan = integ.plan(Chain(), ordering)
        print(json.dumps([plan.canonical_state(), plan.to_dict()],
                         ensure_ascii=False, sort_keys=True))
        """
    )
    outputs = []
    for seed in ("0", "1", "246810"):
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


# ======================================================================
# J. Mutation safety
# ======================================================================


def test_planning_and_extending_never_touch_the_board(state):
    view = GameStateView.from_state(state, viewer=MINE)
    journal = EventJournal()

    before = (
        state.state_hash(),
        journal.journal_hash(),
        [(c.instance_id, c.zone, c.controller, c.owner) for c in state.all_instances()],
        state.player(MINE).life_points,
    )

    integ = integrator(
        view,
        (spec(ALPHA, 0), spec(ALPHA, 1), spec(BETA, 0)),
        (
            definition(ALPHA, 0),
            definition(ALPHA, 1, cost=CostGroup((LifeCost(500),))),
            definition(BETA, 0, provenance=EffectProvenance.text_derived()),
        ),
    )
    ordering = integ.collect_and_order(drawn_event())
    plan = integ.plan(Chain(), ordering)
    integ.extend(Chain(), plan)

    assert state.state_hash() == before[0]
    assert journal.journal_hash() == before[1]
    assert [
        (c.instance_id, c.zone, c.controller, c.owner) for c in state.all_instances()
    ] == before[2]
    assert state.player(MINE).life_points == before[3]
    assert len(journal) == 0


def test_the_integrator_never_receives_a_game_state(state):
    """``GameState`` 를 아예 받지 않으므로 판을 바꿀 수단이 없다."""
    with pytest.raises(TypeError):
        TriggerChainIntegrator(state, TriggerRegistry())
    view = GameStateView.from_state(state, viewer=MINE)
    with pytest.raises(TypeError):
        TriggerChainIntegrator(view, "not a registry")

    tree = ast.parse(pathlib.Path("engine/trigger_chain.py").read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(name.startswith("engine.state") for name in modules)
    assert not any(name.startswith("analysis") for name in modules)


def test_a_failed_plan_changes_nothing_at_all(state):
    view = GameStateView.from_state(state, viewer=MINE)
    before = state.state_hash()
    chain = Chain().activate(THEIRS, EffectRef(BETA, 0))

    integ = integrator(
        view, (spec(),), (definition(activation=Always(ConditionResult.FALSE)),)
    )
    plan = integ.plan(chain, integ.collect_and_order(drawn_event()))
    extended = integ.extend(chain, plan)

    assert plan.links == ()
    assert extended == chain
    assert extended.canonical_state() == chain.canonical_state()
    assert state.state_hash() == before


def test_the_plan_is_immutable(view):
    plan = planned(view, (spec(),), (definition(),))

    for name, value in [("entries", ()), ("is_rule_ordered", True)]:
        with pytest.raises(Exception):
            setattr(plan, name, value)
    assert isinstance(plan.entries, tuple)
    assert isinstance(plan.links, tuple)
    with pytest.raises(Exception):
        plan.entries[0].insertion = ChainInsertion.UNKNOWN


def test_a_cloned_board_is_unaffected(state):
    copy = state.clone()
    planned(GameStateView.from_state(copy, viewer=MINE), (spec(),), (definition(),))

    assert copy.state_hash() == state.state_hash()


# ======================================================================
# K~L. 자동 실행 금지 · 타입 경계
# ======================================================================


def test_putting_a_link_on_the_chain_does_not_resolve_it(state):
    """
    **"트리거 발생 → 체인 → 실행" 을 한 번의 호출로 만들지 않는다.**
    """
    view = GameStateView.from_state(state, viewer=MINE)
    hand = len(state.player(MINE).hand)
    journal = EventJournal()

    held = definition()
    integ = integrator(view, (spec(),), (held,))
    plan = integ.plan(Chain(), integ.collect_and_order(drawn_event()))
    extended = integ.extend(Chain(), plan)

    # 링크는 쌓였지만 아무것도 해결되지 않았다.
    assert len(extended) == 2
    assert extended.resolved_count == 0
    assert len(state.player(MINE).hand) == hand
    assert len(journal) == 0

    # 해결은 별도의 호출이고, 여기서는 하지 않는다.
    resolver = ChainResolver(
        EffectExecutor(
            EffectImplementationRegistry([held.effect_ref]), journal=journal
        ),
        EffectDefinitionRegistry((held,)),
    )
    assert resolver.next_link(extended) is not None
    assert len(state.player(MINE).hand) == hand  # 조회만으로는 여전히 그대로


def test_the_integrator_never_calls_the_resolver_or_the_executor():
    module = pathlib.Path("engine/trigger_chain.py").read_text(encoding="utf-8")
    tree = ast.parse(module)

    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    for forbidden in ("ChainResolver", "EffectExecutor", "CostPayer"):
        assert forbidden not in imported, forbidden

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("resolve", "resolve_top", "resolve_all", "execute", "pay"):
        assert forbidden not in called, forbidden


def test_a_candidate_can_never_be_pushed_onto_a_chain_directly(view):
    """``TriggerCandidate`` ≠ ``ChainLink``. 타입이 그것을 막는다."""
    plan = planned(view, (spec(),), (definition(),))
    entry = plan.insertable[0]

    for wrong in (entry, entry.eligibility, entry.candidate, plan):
        with pytest.raises(TypeError):
            Chain().push(wrong)

    # 링크만 들어간다.
    assert isinstance(entry.link, ChainLink)
    assert len(Chain().push(entry.link)) == 1


def test_the_integrator_does_not_touch_priority():
    tree = ast.parse(pathlib.Path("engine/trigger_chain.py").read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(name.startswith("engine.priority") for name in modules)
    assert not any(name.startswith("engine.payment") for name in modules)


# ======================================================================
# M~N. 여러 트리거 · 빈 후보
# ======================================================================


def test_several_triggers_enter_in_the_order_the_ordering_decided(view):
    integ = integrator(
        view,
        (spec(ALPHA, 0), spec(ALPHA, 1), spec(BETA, 0)),
        (definition(ALPHA, 0), definition(ALPHA, 1), definition(BETA, 0)),
    )
    ordering = integ.collect_and_order(drawn_event())
    plan = integ.plan(Chain(), ordering)
    extended = integ.extend(Chain(), plan)

    expected = [
        (e.candidate.effect_ref, e.candidate.source)
        for e in ordering.canonical_sequence
    ]
    actual = [(link.effect_ref, link.source) for link in extended]
    assert actual == expected
    assert [link.sequence for link in extended] == list(range(len(extended)))


def test_no_candidates_is_an_empty_plan_not_an_error(view):
    """빈 후보를 예외로 만들지 않는다."""
    integ = integrator(view, (), ())
    ordering = integ.collect_and_order(drawn_event())
    plan = integ.plan(Chain(), ordering)

    assert plan.entries == ()
    assert plan.links == ()
    assert plan.is_empty is True
    assert len(plan) == 0
    assert integ.extend(Chain(), plan) == Chain()
    assert plan.describe_ko()


def test_an_event_nobody_watches_produces_nothing(view):
    integ = integrator(view, (spec(),), (definition(),))
    from engine.effect import LifeChanged

    ordering = integ.collect_and_order(
        TimingEvent.from_delta(LifeChanged(MINE, 8000, 7000))
    )
    plan = integ.plan(Chain(), ordering)

    assert plan.entries == ()
    assert plan.links == ()


def test_the_whole_pipeline_runs_end_to_end(state):
    """
    **다섯 계층이 실제로 이어지는지** 확인한다: 수집 → 적격성 → 정리 →
    통합 → 체인. 그리고 판은 그대로다.
    """
    view = GameStateView.from_state(state, viewer=MINE)
    before = state.state_hash()

    definitions = (
        definition(ALPHA, 0),
        definition(ALPHA, 1, activation=Always(ConditionResult.FALSE)),
        definition(BETA, 0, cost=CostGroup((LifeCost(200),))),
        definition(BETA, 1, provenance=EffectProvenance.text_derived()),
    )
    integ = integrator(
        view,
        tuple(spec(d.effect_ref.card_id, d.effect_ref.ordinal) for d in definitions),
        definitions,
    )

    ordering = integ.collect_and_order(drawn_event())
    plan = integ.plan(Chain(), ordering)
    extended = integ.extend(Chain(), plan)

    assert len(extended) == len(plan.links) == 2  # ALPHA:0 두 장
    assert {link.effect_ref for link in extended} == {EffectRef(ALPHA, 0)}
    assert plan.skipped  # 조건 거짓 + TEXT_DERIVED
    assert plan.blocked  # 비용 영수증 없음
    assert plan.needs_decision is True
    assert state.state_hash() == before
    assert extended.resolved_count == 0
