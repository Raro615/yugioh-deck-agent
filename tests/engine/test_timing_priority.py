"""
Phase 2-F-4 — 타이밍 창과 우선권의 통합.

    사건 → TimingWindow → 수집 → 적격성 → 정리 → 계획 → 체인 → 우선권 확인

네 가지를 본다.

1. **각 계층이 자기 일만 하는가** — 조정자가 판정을 다시 만들지 않는가.
2. **아무것도 진행되지 않는가** — 체인이 해결되지 않고, 우선권이 돌지
   않고, 판이 바뀌지 않는가.
3. **모르는 것이 보존되는가** — ``UNKNOWN`` 과 ``unchecked`` 가 살아서
   결과까지 오는가.
4. **관측 경계가 지켜지는가** — 관측자가 다르면 보이는 것이 다른가.
"""

import ast
import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from engine.chain import Chain
from engine.condition import Always, ConditionResult, UnimplementedRule
from engine.cost import CostGroup, LifeCost
from engine.effect import (
    CardDrawn,
    CostPaymentEvent,
    DrawOperation,
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectEvent,
    EffectImplementationRegistry,
    EffectProvenance,
    EventJournal,
    LifeChanged,
    OperationKind,
    ZoneMoved,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.priority import PriorityHolder, PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.timing import (
    WINDOW_UNRESOLVED_RULES,
    TimingCoordinator,
    TimingOutcome,
    TimingWindow,
)
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerError,
    TriggerRegistry,
    TriggerSpec,
    TriggerStatus,
)
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

MINE, THEIRS = 0, 1
ALPHA, BETA = 1000, 1001


# ======================================================================
# 판 · 준비
# ======================================================================


def new_state(turn_player: int = MINE) -> GameState:
    game = GameState.create(
        decks=([ALPHA, ALPHA, BETA, ALPHA], [BETA, BETA, BETA]),
        turn_player=turn_player,
    )
    game.draw(MINE, 3)
    game.draw(THEIRS, 2)
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


def definition(
    card_id: int = ALPHA,
    ordinal: int = 0,
    *,
    activation=Always(),
    cost=None,
    provenance=None,
) -> EffectDefinition:
    return EffectDefinition(
        effect_ref=EffectRef(card_id, ordinal),
        source_card_id=card_id,
        operations=(DrawOperation(1),),
        activation=activation,
        cost=cost if cost is not None else CostGroup(),
        provenance=provenance or EffectProvenance.official_lua(),
    )


def spec(
    card_id: int = ALPHA,
    ordinal: int = 0,
    *,
    point: TimingPoint = TimingPoint.CARD_DRAWN,
    activates_from=frozenset({Zone.MZONE}),
) -> TriggerSpec:
    return TriggerSpec(
        EffectRef(card_id, ordinal), point, activates_from=activates_from
    )


def coordinator(view, specs=(), definitions=(), *, implemented=True):
    return TimingCoordinator(
        view,
        TriggerRegistry(tuple(specs)),
        EffectDefinitionRegistry(tuple(definitions)),
        EffectImplementationRegistry(
            [d.effect_ref for d in definitions] if implemented else []
        ),
    )


def drawn_event() -> TimingEvent:
    return TimingEvent.from_delta(CardDrawn(MINE, InstanceId(4)))


def priority_of(holder=MINE, *, turn_player=MINE, phase=Phase.MAIN1) -> PriorityState:
    return PriorityState.opened(
        ResponseWindow.ACTION, holder, turn_player=turn_player, phase=phase
    )


# ======================================================================
# A. 사건 → TimingWindow
# ======================================================================


@pytest.mark.parametrize(
    "event, point",
    [
        (
            TimingEvent.from_delta(
                ZoneMoved(
                    OperationKind.SEND_TO_GRAVE,
                    InstanceId(0),
                    MINE,
                    Zone.MZONE,
                    MINE,
                    Zone.GRAVE,
                )
            ),
            TimingPoint.CARD_MOVED,
        ),
        (TimingEvent.from_delta(CardDrawn(MINE, InstanceId(4))), TimingPoint.CARD_DRAWN),
        (
            TimingEvent.from_delta(LifeChanged(MINE, 8000, 7000)),
            TimingPoint.LIFE_CHANGED,
        ),
        (
            TimingEvent.from_journal_event(EffectEvent(0, EffectRef(ALPHA, 0), MINE)),
            TimingPoint.EFFECT_RESOLVED,
        ),
        (
            TimingEvent.from_journal_event(CostPaymentEvent(0, MINE)),
            TimingPoint.COST_PAID,
        ),
    ],
    ids=["moved", "drawn", "life", "resolved", "cost"],
)
def test_every_event_kind_opens_a_window_with_the_right_point(view, event, point):
    window = coordinator(view).open_window(event, priority_of(), Chain())

    assert window.event is event
    assert window.point is point
    assert window.viewer == MINE
    assert window.turn_player == MINE
    assert window.phase is Phase.MAIN1


def test_a_window_reads_the_turn_context_from_the_observation():
    board = new_state(turn_player=THEIRS)
    board.turn.set_phase(Phase.END)
    view = GameStateView.from_state(board, viewer=MINE)

    window = coordinator(view).open_window(drawn_event(), priority_of(), Chain())

    assert window.turn_player == THEIRS
    assert window.opponent == MINE
    assert window.phase is Phase.END
    assert window.viewer == MINE  # 관측자와 턴 플레이어는 다른 것이다


def test_a_window_holds_no_board(view):
    from dataclasses import fields

    window = coordinator(view).open_window(drawn_event(), priority_of(), Chain())

    for field in fields(window):
        assert not isinstance(getattr(window, field.name), (GameState, GameStateView))
    for forbidden in ("state", "view", "move", "draw"):
        assert not hasattr(window, forbidden), forbidden


def test_opening_a_window_refuses_a_bad_event_or_chain(view):
    coord = coordinator(view)
    with pytest.raises(TypeError):
        coord.open_window("not an event", priority_of(), Chain())
    with pytest.raises(TypeError):
        TimingWindow(drawn_event(), MINE, MINE, Phase.MAIN1, priority_of(), "not a chain")
    with pytest.raises(TypeError):
        TimingWindow(drawn_event(), MINE, MINE, Phase.MAIN1, "not priority", Chain())


def test_the_coordinator_refuses_a_raw_game_state(state):
    with pytest.raises(TypeError):
        TimingCoordinator(state, TriggerRegistry())


# ======================================================================
# B. 트리거가 없는 창
# ======================================================================


def test_a_window_with_no_triggers_changes_nothing(state):
    view = GameStateView.from_state(state, viewer=MINE)
    journal = EventJournal()
    chain = Chain()
    priority = priority_of()
    before = (state.state_hash(), journal.journal_hash(), chain.canonical_state())

    outcome = coordinator(view).review(drawn_event(), priority, chain)

    assert len(outcome.collection) == 0
    assert outcome.plan.links == ()
    assert outcome.chain == chain
    assert outcome.chain_changed is False
    assert state.state_hash() == before[0]
    assert journal.journal_hash() == before[1]
    assert chain.canonical_state() == before[2]
    assert len(journal) == 0


def test_no_triggers_does_not_advance_anything(view):
    """
    **트리거가 없다고 게임을 진행시키지 않는다.** 페이즈도 우선권도 그대로다.
    """
    priority = priority_of()
    outcome = coordinator(view).review(drawn_event(), priority, Chain())

    assert outcome.priority is priority
    assert outcome.priority.phase is priority.phase
    assert outcome.priority.consecutive_passes == priority.consecutive_passes
    assert outcome.window.phase is Phase.MAIN1
    for forbidden in ("advance_phase", "next_turn", "resolve", "execute"):
        assert not hasattr(outcome, forbidden), forbidden


def test_an_event_nobody_watches_produces_an_empty_review(view):
    outcome = coordinator(view, (spec(),), (definition(),)).review(
        TimingEvent.from_delta(LifeChanged(MINE, 8000, 7000)), priority_of(), Chain()
    )

    assert len(outcome.collection) == 0
    assert outcome.inserted_links == ()
    assert outcome.chain_changed is False


# ======================================================================
# C. ELIGIBLE 트리거
# ======================================================================


def test_an_eligible_trigger_runs_through_every_existing_layer(view):
    """
    ``ALPHA`` 는 필드 1장 · 패 1장이다. 수집은 둘 다 찾지만, 발동 자리
    관문이 패의 것을 거른다 — **각 계층이 자기 몫을 한다**는 뜻이다.
    """
    coord = coordinator(view, (spec(),), (definition(),))
    outcome = coord.review(drawn_event(), priority_of(), Chain())

    assert len(outcome.collection) == 2  # 수집은 사본을 모두 본다
    assert len(outcome.ordering.canonical_sequence) == 1  # 자리 관문이 걸렀다
    assert len(outcome.ordering.excluded) == 1
    assert len(outcome.plan.insertable) == 1
    assert len(outcome.chain) == 1
    assert outcome.chain_changed is True
    assert outcome.chain[0].source == state_field_instance(outcome)


def state_field_instance(outcome):
    """필드에 있던 사본. 체인에 들어간 것이 그것인지 확인하기 위해서다."""
    return outcome.ordering.canonical_sequence[0].candidate.source


def test_candidate_identity_survives_to_the_chain_link(view):
    coord = coordinator(view, (spec(),), (definition(),))
    outcome = coord.review(drawn_event(), priority_of(), Chain())

    candidate = outcome.ordering.canonical_sequence[0].candidate
    link = outcome.chain[0]

    assert link.effect_ref == candidate.effect_ref == EffectRef(ALPHA, 0)
    assert link.source == candidate.source
    assert link.actor == candidate.controller
    assert "e1" not in json.dumps(outcome.to_dict(), ensure_ascii=False)


def test_each_step_can_be_called_on_its_own(view):
    """
    **하나의 거대한 함수가 아니다.** ``review`` 는 조립일 뿐이고, 단계마다
    따로 부를 수 있다.
    """
    coord = coordinator(view, (spec(),), (definition(),))

    window = coord.open_window(drawn_event(), priority_of(), Chain())
    collection = coord.collect_triggers(window)
    ordering = coord.order_triggers(window)
    plan = coord.build_trigger_plan(window, ordering)
    prepared = coord.prepare_chain(window, plan)
    verdict = coord.check_priority(window)

    assembled = coord.review(drawn_event(), window.priority, Chain())

    assert collection.canonical_state() == assembled.collection.canonical_state()
    assert ordering.canonical_state() == assembled.ordering.canonical_state()
    assert plan.canonical_state() == assembled.plan.canonical_state()
    assert prepared.canonical_state() == assembled.chain.canonical_state()
    assert verdict.canonical_state() == assembled.priority_check.canonical_state()


def test_the_coordinator_reuses_the_integrator_instead_of_rebuilding_judgments(view):
    from engine.trigger_chain import TriggerChainIntegrator

    coord = coordinator(view, (spec(),), (definition(),))
    assert isinstance(coord.integrator, TriggerChainIntegrator)

    source = pathlib.Path("engine/timing.py").read_text(encoding="utf-8")
    for forbidden in ("class TriggerEligibilityJudge", "def _judge", "def _bucket"):
        assert forbidden not in source, forbidden


# ======================================================================
# D. UNKNOWN 보존
# ======================================================================


def test_an_unknown_trigger_is_preserved_not_turned_into_ineligible(view):
    coord = coordinator(
        view,
        (spec(),),
        (definition(activation=UnimplementedRule("체인 위의 카드 수")),),
    )
    outcome = coord.review(drawn_event(), priority_of(), Chain())

    assert outcome.ordering.unordered
    # 패의 사본은 자리 관문에서 걸리고, 필드의 사본은 조건을 판정할 수 없다.
    assert all(
        e.status is TriggerStatus.UNKNOWN for e in outcome.ordering.unordered
    )
    assert all(
        e.status is not TriggerStatus.UNKNOWN for e in outcome.ordering.excluded
    )
    assert outcome.plan.unresolved
    for entry in outcome.plan.unresolved:
        assert entry.code is ValidationCode.INFORMATION_UNAVAILABLE
        assert any("체인 위의 카드 수" in note for note in entry.notes)
    assert outcome.inserted_links == ()


def test_unknown_reasons_reach_the_serialized_outcome(view):
    coord = coordinator(
        view, (spec(),), (definition(activation=UnimplementedRule("모르는 규칙")),)
    )
    outcome = coord.review(drawn_event(), priority_of(), Chain())

    text = json.dumps(outcome.to_dict(), ensure_ascii=False)
    assert "모르는 규칙" in text
    assert "트리거가 없다는 뜻이 아닙니다" in text


def test_unchecked_places_survive_the_whole_review(view):
    """
    볼 수 없어서 확인하지 못한 곳이 결과까지 살아 온다 — "후보 없음" 과
    "못 봤음" 이 구분된다.
    """
    coord = coordinator(view, (spec(),), (definition(),))
    outcome = coord.review(drawn_event(), priority_of(), Chain())

    assert outcome.collection.fully_checked is False
    assert any("P1 HAND" in note for note in outcome.collection.unchecked)
    assert "unchecked" in json.dumps(outcome.to_dict(), ensure_ascii=False)


def test_a_verified_effect_without_an_implementation_stays_unknown(view):
    coord = coordinator(view, (spec(),), (definition(),), implemented=False)
    outcome = coord.review(drawn_event(), priority_of(), Chain())

    assert outcome.inserted_links == ()
    assert outcome.ordering.unordered or outcome.plan.unresolved


# ======================================================================
# E. FORBIDDEN / INELIGIBLE
# ======================================================================


def test_a_text_derived_trigger_never_becomes_a_chain_link(view):
    coord = coordinator(
        view, (spec(),), (definition(provenance=EffectProvenance.text_derived()),)
    )
    outcome = coord.review(drawn_event(), priority_of(), Chain())

    assert outcome.inserted_links == ()
    assert len(outcome.chain) == 0
    assert outcome.ordering.excluded
    assert all(
        e.status is TriggerStatus.FORBIDDEN for e in outcome.ordering.excluded
    )
    assert all(
        entry.code is ValidationCode.EXECUTION_FORBIDDEN
        for entry in outcome.plan.skipped
    )


def test_an_ineligible_trigger_creates_no_link(view):
    coord = coordinator(
        view, (spec(),), (definition(activation=Always(ConditionResult.FALSE)),)
    )
    outcome = coord.review(drawn_event(), priority_of(), Chain())

    assert outcome.inserted_links == ()
    assert outcome.plan.skipped
    assert all(entry.link is None for entry in outcome.plan.skipped)


def test_a_cost_bearing_effect_is_not_linked_without_a_receipt(view):
    coord = coordinator(
        view, (spec(),), (definition(cost=CostGroup((LifeCost(500),))),)
    )
    outcome = coord.review(drawn_event(), priority_of(), Chain())

    assert outcome.inserted_links == ()
    assert outcome.plan.blocked
    assert outcome.needs_decision is True


# ======================================================================
# F. 우선권
# ======================================================================


def test_the_holder_need_not_be_the_turn_player(state):
    """``holder == turn_player`` 를 강제하지 않는다 (Phase 2-F-1 설계 유지)."""
    view = GameStateView.from_state(state, viewer=MINE)
    priority = PriorityState.opened(
        ResponseWindow.RESPONSE, THEIRS, turn_player=MINE, phase=Phase.MAIN1
    )

    outcome = coordinator(view).review(drawn_event(), priority, Chain())

    assert isinstance(outcome, TimingOutcome)
    assert outcome.window.turn_player == MINE
    assert outcome.priority.holder is PriorityHolder.PLAYER_1
    assert outcome.priority.holder_is_turn_player is False
    assert outcome.priority_check.validity is ActionValidity.VALID


def test_the_priority_state_is_never_advanced(view):
    """
    **우선권을 돌리지 않는다.** 누구에게 가는가는 아직 규칙이 없다.
    """
    priority = priority_of().passed()
    outcome = coordinator(view, (spec(),), (definition(),)).review(
        drawn_event(), priority, Chain()
    )

    assert outcome.priority is priority
    assert outcome.priority.consecutive_passes == 1
    assert outcome.priority.holder is priority.holder
    assert outcome.priority.window is priority.window


def test_an_outcome_cannot_claim_a_changed_priority(view):
    coord = coordinator(view)
    window = coord.open_window(drawn_event(), priority_of(), Chain())
    outcome = coord.review(drawn_event(), window.priority, Chain())

    with pytest.raises(Exception):
        outcome.priority_check = None
    # 우선권 필드는 창에서 파생된다 — 따로 세울 수 없다.
    assert outcome.priority is outcome.window.priority


def test_a_closed_priority_reports_no_open_window(view):
    idle = PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1)

    outcome = coordinator(view).review(drawn_event(), idle, Chain())

    assert outcome.priority_check.validity is ActionValidity.INVALID
    assert outcome.priority_check.code is ValidationCode.NO_RESPONSE_WINDOW
    assert outcome.priority_is_actionable is False


def test_a_stale_priority_state_is_unknown_not_invalid(state):
    """어느 쪽이 낡았는지 모르는 채로 "안 된다" 고 단정하지 않는다."""
    view = GameStateView.from_state(state, viewer=MINE)  # T0 MAIN1
    stale = PriorityState.opened(
        ResponseWindow.ACTION, MINE, turn_player=THEIRS, phase=Phase.MAIN1
    )

    outcome = coordinator(view).review(drawn_event(), stale, Chain())

    assert outcome.priority_check.validity is ActionValidity.UNKNOWN
    assert outcome.priority_check.code is ValidationCode.PRIORITY_STATE_STALE
    assert outcome.priority_is_actionable is False


def test_priority_is_actionable_only_on_valid(view):
    """``UNKNOWN`` 이 허가로 새지 않는다."""
    ok = coordinator(view).review(drawn_event(), priority_of(), Chain())
    assert ok.priority_check.validity is ActionValidity.VALID
    assert ok.priority_is_actionable is True

    idle = coordinator(view).review(
        drawn_event(), PriorityState.idle(MINE, Phase.MAIN1), Chain()
    )
    assert idle.priority_is_actionable is False


def test_pass_handling_is_not_implemented_here():
    """
    PASS → 상대 → 둘 다 PASS → 체인 해결 전체를 구현하지 않는다.
    """
    import engine.timing as module

    source = pathlib.Path("engine/timing.py").read_text(encoding="utf-8")
    for forbidden in ("def pass_priority", "def advance_priority", "both_passed"):
        assert forbidden not in source, forbidden
    assert not hasattr(module, "PassResolver")


# ======================================================================
# G. 가려진 정보
# ======================================================================


def test_two_viewers_see_different_things(state):
    """
    같은 판이라도 관측자가 다르면 후보와 확인 못 한 곳이 다르다 — 정보
    경계가 살아 있다는 증거다.
    """
    mine = coordinator(
        GameStateView.from_state(state, viewer=MINE), (spec(BETA, 0),), (definition(BETA, 0),)
    ).review(drawn_event(), priority_of(), Chain())
    theirs = coordinator(
        GameStateView.from_state(state, viewer=THEIRS),
        (spec(BETA, 0),),
        (definition(BETA, 0),),
    ).review(drawn_event(), priority_of(), Chain())

    assert mine.window.viewer == MINE and theirs.window.viewer == THEIRS
    assert mine.collection.unchecked != theirs.collection.unchecked
    assert any("P1 HAND" in note for note in mine.collection.unchecked)
    assert any("P0 HAND" in note for note in theirs.collection.unchecked)


def test_a_hidden_card_never_appears_in_the_outcome(state):
    hidden = state.create_instance(ALPHA, owner=THEIRS, zone=Zone.HAND)
    view = GameStateView.from_state(state, viewer=MINE)

    outcome = coordinator(view, (spec(),), (definition(),)).review(
        drawn_event(), priority_of(), Chain()
    )

    sources = {c.source for c in outcome.collection}
    assert hidden.instance_id not in sources
    assert hidden.instance_id not in {link.source for link in outcome.chain}
    # 상대 패는 "확인하지 못한 곳" 으로만 남는다.
    assert any("P1 HAND" in note for note in outcome.collection.unchecked)


def test_a_window_from_another_viewer_is_refused(state):
    theirs_view = GameStateView.from_state(state, viewer=THEIRS)
    mine_view = GameStateView.from_state(state, viewer=MINE)

    window = coordinator(theirs_view).open_window(drawn_event(), priority_of(), Chain())

    with pytest.raises(TriggerError):
        coordinator(mine_view).collect_triggers(window)
    with pytest.raises(TriggerError):
        coordinator(mine_view).check_priority(window)


# ======================================================================
# H. Mutation safety
# ======================================================================


def test_the_whole_review_never_touches_the_board(state):
    view = GameStateView.from_state(state, viewer=MINE)
    journal = EventJournal()

    before = (
        state.state_hash(),
        journal.journal_hash(),
        state.player(MINE).life_points,
        [(c.instance_id, c.zone, c.controller, c.owner) for c in state.all_instances()],
    )

    coord = coordinator(
        view,
        (spec(ALPHA, 0), spec(ALPHA, 1), spec(BETA, 0)),
        (
            definition(ALPHA, 0),
            definition(ALPHA, 1, cost=CostGroup((LifeCost(500),))),
            definition(BETA, 0, provenance=EffectProvenance.text_derived()),
        ),
    )
    coord.review(drawn_event(), priority_of(), Chain())

    assert state.state_hash() == before[0]
    assert journal.journal_hash() == before[1]
    assert state.player(MINE).life_points == before[2]
    assert [
        (c.instance_id, c.zone, c.controller, c.owner) for c in state.all_instances()
    ] == before[3]
    assert len(journal) == 0


def test_the_timing_layer_cannot_execute_anything():
    """
    **판단과 연결 단계다.** 실행 경로를 import 하지도 부르지도 않는다.
    """
    tree = ast.parse(pathlib.Path("engine/timing.py").read_text(encoding="utf-8"))

    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    for forbidden in ("EffectExecutor", "CostPayer", "ChainResolver", "GameState"):
        assert forbidden not in imported, forbidden

    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    for forbidden in ("engine.state", "engine.payment", "analysis"):
        assert not any(name.startswith(forbidden) for name in modules), forbidden

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in (
        "execute",
        "_apply",
        "pay",
        "resolve",
        "resolve_top",
        "resolve_all",
        "move",
        "draw",
        "change_life",
        "push",
    ):
        assert forbidden not in called, forbidden


def test_the_outcome_is_immutable(view):
    outcome = coordinator(view, (spec(),), (definition(),)).review(
        drawn_event(), priority_of(), Chain()
    )

    for name, value in [("chain", Chain()), ("unresolved_rules", ())]:
        with pytest.raises(Exception):
            setattr(outcome, name, value)
    assert isinstance(outcome.unresolved_rules, tuple)
    assert isinstance(outcome.inserted_links, tuple)
    with pytest.raises(Exception):
        outcome.window.turn_player = THEIRS


def test_a_cloned_board_is_unaffected(state):
    copy = state.clone()
    coordinator(
        GameStateView.from_state(copy, viewer=MINE), (spec(),), (definition(),)
    ).review(drawn_event(), priority_of(), Chain())

    assert copy.state_hash() == state.state_hash()


# ======================================================================
# I. 기존 체인 보존
# ======================================================================


def test_an_existing_chain_is_never_reset(view):
    existing = Chain().activate(THEIRS, EffectRef(BETA, 0))
    coord = coordinator(view, (spec(),), (definition(),))

    outcome = coord.review(drawn_event(), priority_of(), existing)

    assert len(existing) == 1  # 원래 체인은 그대로
    assert len(outcome.chain) == 2
    assert outcome.chain[0] == existing[0]  # 기존 링크가 앞에 남는다
    assert outcome.chain[1].effect_ref == EffectRef(ALPHA, 0)
    assert outcome.window.chain is existing
    assert outcome.window.chain_is_open is True


def test_a_chain_that_started_resolving_accepts_nothing_new(view):
    started = Chain().activate(THEIRS, EffectRef(BETA, 0)).advanced()
    coord = coordinator(view, (spec(),), (definition(),))

    outcome = coord.review(drawn_event(), priority_of(), started)

    assert outcome.chain == started
    assert outcome.inserted_links == ()
    assert outcome.chain.resolved_count == 1  # 해결 진행도도 그대로


def test_the_prepared_chain_is_never_resolved(view):
    coord = coordinator(view, (spec(),), (definition(),))
    outcome = coord.review(drawn_event(), priority_of(), Chain())

    assert len(outcome.chain) == 1
    assert outcome.chain.resolved_count == 0
    assert outcome.chain.is_complete is False
    assert outcome.chain.top is not None


# ======================================================================
# J. 결정론
# ======================================================================


def test_the_same_input_gives_the_same_outcome():
    results = []
    for _ in range(2):
        board = new_state()
        view = GameStateView.from_state(board, viewer=MINE)
        results.append(
            coordinator(
                view,
                (spec(ALPHA, 0), spec(BETA, 0)),
                (definition(ALPHA, 0), definition(BETA, 0)),
            )
            .review(drawn_event(), priority_of(), Chain())
            .canonical_state()
        )

    assert results[0] == results[1]


def test_the_outcome_carries_every_unresolved_rule_forward(view):
    outcome = coordinator(view, (spec(),), (definition(),)).review(
        drawn_event(), priority_of(), Chain()
    )

    # 이 계층의 미정 규칙 + 정리 계층의 미정 규칙이 모두 실린다.
    for rule in WINDOW_UNRESOLVED_RULES:
        assert rule in outcome.unresolved_rules
    for rule in outcome.ordering.unresolved_rules:
        assert rule in outcome.unresolved_rules
    assert any("우선권" in rule for rule in outcome.unresolved_rules)
    assert any("SEGOC" in rule for rule in outcome.unresolved_rules)
    assert outcome.needs_decision is True


def test_the_outcome_serializes_to_plain_data(view):
    outcome = coordinator(view, (spec(),), (definition(),)).review(
        drawn_event(), priority_of(), Chain()
    )

    data = outcome.to_dict()
    text = json.dumps(data, ensure_ascii=False)

    assert "0x" not in text and "object at" not in text
    assert set(data) >= {
        "window",
        "collection",
        "ordering",
        "plan",
        "chain",
        "priority",
        "priority_check",
        "unresolved_rules",
        "needs_decision",
    }
    assert data["window"]["viewer"] == MINE
    assert data["needs_decision"] is True


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
        from engine.priority import PriorityState, ResponseWindow
        from engine.state.game_state import GameState
        from engine.timing import TimingCoordinator
        from engine.trigger import TimingEvent, TimingPoint, TriggerRegistry, TriggerSpec
        from engine.vocabulary import Phase, Position, Zone

        game = GameState.create(decks=([1000, 1000, 1001, 1000], [1001, 1001, 1001]))
        game.draw(0, 3)
        game.draw(1, 2)
        game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
        game.move(game.player(1).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
        game.turn.set_phase(Phase.MAIN1)
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
        coord = TimingCoordinator(
            view, TriggerRegistry(specs), EffectDefinitionRegistry(held),
            EffectImplementationRegistry([d.effect_ref for d in held]),
        )
        outcome = coord.review(
            TimingEvent.from_delta(CardDrawn(0, InstanceId(5))),
            PriorityState.opened(ResponseWindow.ACTION, 0, turn_player=0,
                                 phase=Phase.MAIN1),
            Chain(),
        )
        print(json.dumps([outcome.canonical_state(), outcome.to_dict()],
                         ensure_ascii=False, sort_keys=True))
        """
    )
    outputs = []
    for seed in ("0", "1", "12345"):
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


def test_several_triggers_keep_the_order_the_ordering_decided(view):
    coord = coordinator(
        view,
        (spec(ALPHA, 0), spec(ALPHA, 1), spec(BETA, 0)),
        (definition(ALPHA, 0), definition(ALPHA, 1), definition(BETA, 0)),
    )

    outcome = coord.review(drawn_event(), priority_of(), Chain())

    expected = [
        (e.candidate.effect_ref, e.candidate.source)
        for e in outcome.ordering.canonical_sequence
    ]
    actual = [(link.effect_ref, link.source) for link in outcome.chain]
    assert actual == expected
    assert outcome.ordering.is_rule_ordered is False  # 규칙 순서가 아니다
