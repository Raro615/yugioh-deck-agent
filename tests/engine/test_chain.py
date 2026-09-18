"""
Phase 2-F-2 — 체인의 최소 실행 구조.

    ChainLink → Chain.push → ChainResolver.resolve_top → EffectExecutor

여기서 답하는 것은 **무엇을 언제 해결하는가**뿐이다. 효과를 *어떻게*
적용하는지는 실행기의 일이고, 이 파일은 그 경계가 지켜지는지를 본다.

세 가지를 본다.

1. 쌓인 것이 **역순으로** 해결되는가 (LIFO).
2. 체인이 효과를 스스로 적용하지 않는가 — Delta · Journal 이 실행기의
   것과 같은가.
3. 해결하지 못한 링크를 **성공으로 적지 않는가.**
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

from engine.chain import (
    STATUS_MAP,
    Chain,
    ChainError,
    ChainLink,
    ChainResolution,
    ChainResolutionStatus,
    ChainResolver,
)
from engine.condition import Always, ConditionResult, UnimplementedRule
from engine.cost import (
    CandidateSource,
    ChoiceSpec,
    CostPayment,
    CostSemantics,
    Selection,
)
from engine.effect import (
    PRIMARY_TARGET,
    CardOperation,
    DrawOperation,
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectExecutor,
    EffectImplementationRegistry,
    EffectProvenance,
    EventJournal,
    EventKind,
    LifeChangeOperation,
    OperationKind,
    ResolutionStatus,
    TargetBinding,
    TargetSelection,
    TargetSpec,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.priority import PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

CARD = 2511
MINE, THEIRS = 0, 1


# ======================================================================
# 판 · 정의
# ======================================================================


def new_state() -> GameState:
    game = GameState.create(decks=(range(1000, 1040), range(2000, 2040)))
    game.draw(MINE, 5)
    game.draw(THEIRS, 5)
    for player in (MINE, THEIRS):
        game.move(
            game.player(player).hand[0],
            Zone.MZONE,
            position=Position.FACEUP_ATTACK,
        )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


def anywhere() -> ChoiceSpec:
    return ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.MZONE, Zone.EMZONE, Zone.HAND}), owner=None
        )
    )


def definition(
    ordinal: int,
    *operations,
    activation=None,
    provenance=None,
) -> EffectDefinition:
    needs_target = any(operation.target_refs for operation in operations)
    return EffectDefinition(
        effect_ref=EffectRef(CARD, ordinal),
        source_card_id=CARD,
        operations=tuple(operations),
        targets=(
            TargetBinding.single(TargetSpec.targeting(anywhere()))
            if needs_target
            else ()
        ),
        activation=activation,
        provenance=provenance or EffectProvenance.official_lua(),
    )


class Engine:
    """정의 · 구현 등록 · 기록 · 실행기 · 해결기를 한 번에 묶어 둔다."""

    def __init__(self, *definitions, register_implementations: bool = True):
        self.definitions = EffectDefinitionRegistry()
        self.implementations = EffectImplementationRegistry()
        self.journal = EventJournal()
        for held in definitions:
            self.definitions.register(held)
            if register_implementations:
                self.implementations.register(held.effect_ref)
        self.executor = EffectExecutor(self.implementations, journal=self.journal)
        self.resolver = ChainResolver(self.executor, self.definitions)


def draw_engine(*counts: int) -> Engine:
    """``counts[i]`` 장을 뽑는 효과를 ordinal ``i`` 로 등록한다."""
    return Engine(
        *(definition(i, DrawOperation(count)) for i, count in enumerate(counts))
    )


def chain_of(*links: tuple[int, int]) -> Chain:
    """``(actor, ordinal)`` 쌍을 순서대로 쌓는다."""
    chain = Chain()
    for actor, ordinal in links:
        chain = chain.activate(actor, EffectRef(CARD, ordinal))
    return chain


# ======================================================================
# A~E. ChainLink
# ======================================================================


def test_a_link_records_an_activation_that_was_already_decided():
    link = ChainLink(
        sequence=0,
        actor=THEIRS,
        effect_ref=EffectRef(CARD, 2),
        source=InstanceId(9),
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(4))),),
        payments=(CostPayment(CostSemantics.DISCARD, (InstanceId(7),), player=THEIRS),),
    )

    assert link.sequence == 0
    assert link.chain_number == 1  # 사람이 부르는 "체인 1"
    assert link.actor == THEIRS
    assert link.effect_ref == EffectRef(CARD, 2)
    assert link.card_id == CARD
    assert link.source == InstanceId(9)
    assert link.paid_anything is True


def test_a_link_is_immutable():
    link = ChainLink(0, MINE, EffectRef(CARD, 0))
    for field, value in [
        ("sequence", 5),
        ("actor", THEIRS),
        ("effect_ref", EffectRef(CARD, 1)),
        ("selections", ()),
    ]:
        with pytest.raises(Exception):
            setattr(link, field, value)


def test_a_link_never_carries_a_definition_or_a_board():
    """
    링크에 정의를 박아 두면 같은 링크가 낡은 정의를 영구히 들고 다닌다.
    identity 는 ``EffectRef`` 이고 정의는 등록소에서 찾는다.
    """
    from dataclasses import fields

    link = ChainLink(0, MINE, EffectRef(CARD, 0))
    names = {f.name for f in fields(link)}

    assert "definition" not in names
    assert "state" not in names and "view" not in names
    for value in (getattr(link, name) for name in names):
        assert not isinstance(value, (EffectDefinition, GameState, GameStateView))


def test_a_link_uses_the_effect_ref_never_the_lua_variable_name():
    """
    ``EffectSpec.index`` 는 Lua 변수명(``"e1"``)이고 한 카드 안에서 중복된다
    (실측 4,884장). 실행 identity 로 쓰지 않는다.
    """
    link = ChainLink(0, MINE, EffectRef(CARD, 1))
    assert link.to_dict()["effect_ref"] == {"card_id": CARD, "ordinal": 1}
    assert "e1" not in json.dumps(link.to_dict(), ensure_ascii=False)


def test_a_link_keeps_the_selection_it_was_given_and_does_not_recompute_it():
    """
    후보(``CandidateSet``)와 고른 결과(``Selection``)는 다른 것이다. 링크가
    담는 것은 결과뿐이고, 해결 시점에 다시 고르지 않는다.
    """
    chosen = Selection.of(InstanceId(11), InstanceId(12))
    link = ChainLink(
        0, MINE, EffectRef(CARD, 0), selections=(TargetSelection(PRIMARY_TARGET, chosen),)
    )

    context = link.resolution_context()

    assert context.selection_for(PRIMARY_TARGET) == chosen
    assert context.chosen_instances == (InstanceId(11), InstanceId(12))
    # 후보를 세는 것은 링크의 일이 아니다.
    assert not hasattr(link, "candidates")
    assert not hasattr(link, "resolve_candidates")


def test_a_link_carries_the_receipt_but_never_pays_again():
    """
    비용은 링크가 만들어지기 **전에** 이미 치러졌다. 문맥의
    ``cost_selections`` 를 비우는 이유가 그것이다 — 넣으면 실행기가 두 번
    치를 길이 생긴다.
    """
    receipt = CostPayment(CostSemantics.PAY_LIFE, amount=1000, player=MINE)
    link = ChainLink(0, MINE, EffectRef(CARD, 0), payments=(receipt,))

    assert link.payments == (receipt,)
    assert link.resolution_context().cost_selections == ()
    for forbidden in ("pay", "pay_cost", "cost_payer"):
        assert not hasattr(link, forbidden), forbidden


def test_the_resolution_context_is_built_from_the_link_alone():
    link = ChainLink(
        1, THEIRS, EffectRef(CARD, 3), source=InstanceId(2),
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(8))),),
    )

    context = link.resolution_context()

    assert context.effect_ref == EffectRef(CARD, 3)
    assert context.controller == THEIRS
    assert context.opponent == MINE
    assert context.source == InstanceId(2)
    # 체인 전체를 문맥에 넣지 않는다.
    from dataclasses import fields

    assert "chain" not in {f.name for f in fields(context)}


@pytest.mark.parametrize("bad", [(-1, MINE), (0, 5), (0, -1)])
def test_a_malformed_link_is_refused(bad):
    sequence, actor = bad
    with pytest.raises((ChainError, ValueError)):
        ChainLink(sequence, actor, EffectRef(CARD, 0))


def test_the_same_target_name_cannot_be_chosen_twice_in_one_link():
    with pytest.raises(ChainError):
        ChainLink(
            0,
            MINE,
            EffectRef(CARD, 0),
            selections=(
                TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(1))),
                TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(2))),
            ),
        )


# ======================================================================
# F~G. Chain 쌓기
# ======================================================================


def test_pushing_a_link_leaves_the_old_chain_untouched():
    first = Chain()
    second = first.activate(MINE, EffectRef(CARD, 0))
    third = second.activate(THEIRS, EffectRef(CARD, 1))

    assert len(first) == 0 and first.is_empty
    assert len(second) == 1
    assert len(third) == 2
    assert second.links == (third.links[0],)  # 앞부분은 같은 링크다


def test_links_keep_the_order_they_were_activated():
    chain = chain_of((MINE, 0), (THEIRS, 1), (MINE, 2))

    assert [link.sequence for link in chain] == [0, 1, 2]
    assert [link.chain_number for link in chain] == [1, 2, 3]
    assert [link.actor for link in chain] == [MINE, THEIRS, MINE]
    assert [link.effect_ref.ordinal for link in chain] == [0, 1, 2]


def test_a_chain_does_not_expose_a_mutable_list():
    chain = chain_of((MINE, 0))

    assert isinstance(chain.links, tuple)
    assert isinstance(chain.pending, tuple)
    assert isinstance(chain.resolution_order, tuple)
    for forbidden in ("append", "insert", "pop", "remove", "clear", "extend"):
        assert not hasattr(chain, forbidden), forbidden


def test_a_link_with_the_wrong_number_is_refused():
    chain = chain_of((MINE, 0))
    with pytest.raises(ChainError):
        chain.push(ChainLink(5, MINE, EffectRef(CARD, 1)))
    with pytest.raises(ChainError):
        chain.push(ChainLink(0, MINE, EffectRef(CARD, 1)))
    assert len(chain) == 1


def test_a_chain_cannot_be_built_with_gaps():
    with pytest.raises(ChainError):
        Chain(links=(ChainLink(0, MINE, EffectRef(CARD, 0)),
                     ChainLink(2, MINE, EffectRef(CARD, 1))))


def test_nothing_can_be_pushed_onto_a_chain_that_has_started_resolving():
    """
    규칙상 가능한지의 문제가 아니라, LIFO 순서와 번호를 **구조적으로
    표현할 수 없기** 때문이다. 해결 중 발동은 타이밍 계층의 몫이다.
    """
    chain = chain_of((MINE, 0), (THEIRS, 1)).advanced()

    with pytest.raises(ChainError):
        chain.activate(MINE, EffectRef(CARD, 2))
    assert len(chain) == 2


def test_only_links_can_be_pushed():
    with pytest.raises(TypeError):
        Chain().push("체인 1")


# ======================================================================
# H~L. LIFO 해결
# ======================================================================


def test_the_resolution_order_is_the_reverse_of_activation():
    chain = chain_of((MINE, 0), (THEIRS, 1), (MINE, 2))

    assert [link.chain_number for link in chain.resolution_order] == [3, 2, 1]
    assert chain.top.chain_number == 3


def test_an_empty_chain_resolves_nothing(state):
    engine = draw_engine(1)
    before = state.state_hash()

    resolution = engine.resolver.resolve_top(state, Chain())

    assert resolution.status is ChainResolutionStatus.EMPTY_CHAIN
    assert resolution.code is ValidationCode.CHAIN_EMPTY
    assert resolution.link is None
    assert resolution.result is None
    assert resolution.deltas == ()
    assert state.state_hash() == before
    assert len(engine.journal) == 0


def test_an_empty_chain_is_not_the_same_as_a_finished_one(state):
    """하나도 쌓이지 않은 것과 다 해결한 것은 **다른 사실**이다."""
    engine = draw_engine(1)
    finished = engine.resolver.resolve_top(state, chain_of((MINE, 0))).chain

    assert finished.is_complete is True
    assert finished.is_empty is False

    again = engine.resolver.resolve_top(state, finished)
    assert again.status is ChainResolutionStatus.CHAIN_COMPLETE
    assert again.status is not ChainResolutionStatus.EMPTY_CHAIN
    assert Chain().is_empty is True and Chain().is_complete is True


def test_a_single_link_chain_resolves(state):
    engine = draw_engine(2)
    hand = len(state.player(MINE).hand)

    resolution = engine.resolver.resolve_top(state, chain_of((MINE, 0)))

    assert resolution.resolved is True
    assert resolution.status is ChainResolutionStatus.RESOLVED
    assert resolution.link.chain_number == 1
    assert resolution.chain.is_complete is True
    assert resolution.chain.remaining == 0
    assert len(state.player(MINE).hand) == hand + 2


def test_a_two_link_chain_resolves_top_down(state):
    """체인 2 가 먼저 해결된다."""
    engine = draw_engine(1, 3)
    mine, theirs = len(state.player(MINE).hand), len(state.player(THEIRS).hand)

    chain = chain_of((MINE, 0), (THEIRS, 1))
    first = engine.resolver.resolve_top(state, chain)

    assert first.link.chain_number == 2
    assert first.link.actor == THEIRS
    assert len(state.player(THEIRS).hand) == theirs + 3
    assert len(state.player(MINE).hand) == mine  # 체인 1 은 아직이다

    second = engine.resolver.resolve_top(state, first.chain)

    assert second.link.chain_number == 1
    assert len(state.player(MINE).hand) == mine + 1
    assert second.chain.is_complete is True


def test_a_three_link_chain_resolves_three_two_one(state):
    engine = draw_engine(1, 1, 1)
    chain = chain_of((MINE, 0), (THEIRS, 1), (MINE, 2))

    steps = engine.resolver.resolve_all(state, chain)

    assert [step.status for step in steps] == [ChainResolutionStatus.RESOLVED] * 3
    assert [step.link.chain_number for step in steps] == [3, 2, 1]
    assert steps[-1].chain.is_complete is True
    assert [link.chain_number for link in steps[-1].chain.resolved] == [3, 2, 1]
    assert len(engine.journal) == 3


def test_the_chain_tracks_what_is_left_while_resolving(state):
    engine = draw_engine(1, 1, 1)
    chain = chain_of((MINE, 0), (THEIRS, 1), (MINE, 2))

    assert (chain.remaining, chain.resolved_count) == (3, 0)
    assert [link.chain_number for link in chain.pending] == [1, 2, 3]

    chain = engine.resolver.resolve_top(state, chain).chain
    assert (chain.remaining, chain.resolved_count) == (2, 1)
    assert [link.chain_number for link in chain.pending] == [1, 2]
    assert chain.top.chain_number == 2

    chain = engine.resolver.resolve_top(state, chain).chain
    assert [link.chain_number for link in chain.pending] == [1]
    assert chain.link(2).chain_number == 3  # 번호로 찾는 것은 계속 된다


def test_advancing_a_finished_chain_is_refused():
    with pytest.raises(ChainError):
        Chain().advanced()
    chain = chain_of((MINE, 0)).advanced()
    with pytest.raises(ChainError):
        chain.advanced()


def test_the_next_link_can_be_inspected_without_resolving_it(state):
    engine = draw_engine(1, 1)
    chain = chain_of((MINE, 0), (THEIRS, 1))
    before = state.state_hash()

    peeked = engine.resolver.next_link(chain)
    held = engine.resolver.definition_for(peeked)

    assert peeked.chain_number == 2
    assert held is not None and held.effect_ref == EffectRef(CARD, 1)
    assert state.state_hash() == before


# ======================================================================
# M~O. 실패
# ======================================================================


def test_a_link_without_a_registered_definition_cannot_resolve(state):
    engine = draw_engine(1)  # ordinal 0 만 등록했다
    before = state.state_hash()

    resolution = engine.resolver.resolve_top(state, chain_of((MINE, 7)))

    assert resolution.status is ChainResolutionStatus.INVALID_CHAIN_LINK
    assert resolution.code is ValidationCode.CHAIN_DEFINITION_UNAVAILABLE
    assert resolution.result is None
    assert resolution.chain.resolved_count == 0  # 건너뛰지 않는다
    assert state.state_hash() == before
    assert len(engine.journal) == 0


def test_an_unsupported_effect_is_not_silently_a_success(state):
    """파괴는 실행기가 다루지 못한다. 체인이 임의로 성공 처리하지 않는다."""
    engine = Engine(definition(0, CardOperation.destroy(PRIMARY_TARGET)))
    target = state.player(MINE).monster_zone[0].instance_id
    chain = Chain().activate(
        MINE,
        EffectRef(CARD, 0),
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(target)),),
    )
    before = state.state_hash()

    resolution = engine.resolver.resolve_top(state, chain)

    assert resolution.status is ChainResolutionStatus.UNSUPPORTED_EFFECT
    assert resolution.resolved is False
    assert resolution.result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert "destruction semantics" in (resolution.result.missing or "")
    assert resolution.chain.resolved_count == 0
    assert state.state_hash() == before
    assert len(engine.journal) == 0


def test_a_text_derived_effect_never_resolves_through_a_chain(state):
    """
    출처 금지는 체인을 거쳐도 그대로다 (ADR-004). "지원하지 않는다" 와
    **합치지 않는다** — 전혀 다른 말이다.
    """
    engine = Engine(
        definition(0, DrawOperation(1), provenance=EffectProvenance.text_derived())
    )
    before = state.state_hash()

    resolution = engine.resolver.resolve_top(state, chain_of((MINE, 0)))

    assert resolution.status is ChainResolutionStatus.FORBIDDEN_EFFECT
    assert resolution.status is not ChainResolutionStatus.UNSUPPORTED_EFFECT
    assert resolution.result.status is ResolutionStatus.FORBIDDEN
    assert state.state_hash() == before
    assert len(engine.journal) == 0


def test_an_unregistered_implementation_does_not_resolve(state):
    """정의가 있다고 실행할 수 있는 것이 아니다 (ADR-006)."""
    engine = Engine(definition(0, DrawOperation(1)), register_implementations=False)
    before = state.state_hash()

    resolution = engine.resolver.resolve_top(state, chain_of((MINE, 0)))

    assert resolution.status is ChainResolutionStatus.EFFECT_NOT_APPLIED
    assert resolution.result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert state.state_hash() == before
    assert len(engine.journal) == 0


@pytest.mark.parametrize(
    "activation, expected",
    [
        (Always(ConditionResult.FALSE), ResolutionStatus.CONDITION_FALSE),
        (UnimplementedRule("아직 없는 규칙"), ResolutionStatus.CONDITION_UNKNOWN),
    ],
)
def test_a_condition_that_is_not_true_leaves_the_link_unresolved(
    state, activation, expected
):
    engine = Engine(definition(0, DrawOperation(1), activation=activation))
    before = state.state_hash()

    resolution = engine.resolver.resolve_top(state, chain_of((MINE, 0)))

    assert resolution.status is ChainResolutionStatus.EFFECT_NOT_APPLIED
    assert resolution.result.status is expected
    assert resolution.chain.resolved_count == 0
    assert state.state_hash() == before
    assert len(engine.journal) == 0


def test_resolve_all_stops_at_the_first_link_it_cannot_resolve(state):
    """
    **불발 규칙을 지어내지 않는다.** "해결할 수 없는 링크는 건너뛴다" 는
    유희왕 규칙이지만 그것은 규칙이고 이 단계에 없다.
    """
    engine = Engine(
        definition(0, DrawOperation(1)),
        definition(1, CardOperation.destroy(PRIMARY_TARGET)),
    )
    target = state.player(MINE).monster_zone[0].instance_id
    chain = Chain().activate(MINE, EffectRef(CARD, 0)).activate(
        THEIRS,
        EffectRef(CARD, 1),
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(target)),),
    )
    hand = len(state.player(MINE).hand)

    steps = engine.resolver.resolve_all(state, chain)

    # 체인 2(파괴)부터 시도하고 거기서 멈춘다 — 체인 1 은 손대지 않는다.
    assert len(steps) == 1
    assert steps[0].status is ChainResolutionStatus.UNSUPPORTED_EFFECT
    assert steps[0].chain.resolved_count == 0
    assert len(state.player(MINE).hand) == hand
    assert len(engine.journal) == 0


def test_a_resolution_cannot_claim_changes_it_did_not_make(state):
    engine = draw_engine(1)
    ok = engine.resolver.resolve_top(state, chain_of((MINE, 0)))
    assert ok.changed_state is True

    with pytest.raises(ChainError):
        ChainResolution(
            ChainResolutionStatus.UNSUPPORTED_EFFECT,
            ok.chain,
            link=ok.link,
            result=ok.result,  # deltas 가 붙어 있는 성공 결과
        )


def test_a_resolution_cannot_be_read_as_a_boolean(state):
    engine = draw_engine(1)
    resolution = engine.resolver.resolve_top(state, Chain())
    with pytest.raises(TypeError):
        bool(resolution)


def test_the_status_map_covers_every_resolution_status():
    """
    실행기의 상태가 하나라도 빠지면 그 결과가 조용히 기본값으로 분류된다.
    """
    assert set(STATUS_MAP) == set(ResolutionStatus)
    assert STATUS_MAP[ResolutionStatus.RESOLVED] is ChainResolutionStatus.RESOLVED
    assert (
        STATUS_MAP[ResolutionStatus.FORBIDDEN]
        is not STATUS_MAP[ResolutionStatus.UNSUPPORTED_OPERATION]
    )


# ======================================================================
# P~Q. Delta · Journal 연결
# ======================================================================


def test_a_resolved_link_carries_the_executors_deltas(state):
    engine = Engine(
        definition(
            0,
            CardOperation.send_to_grave(PRIMARY_TARGET),
            DrawOperation(1),
            LifeChangeOperation(-500),
        )
    )
    target = state.player(MINE).monster_zone[0].instance_id
    chain = Chain().activate(
        MINE,
        EffectRef(CARD, 0),
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(target)),),
    )

    resolution = engine.resolver.resolve_top(state, chain)

    assert resolution.resolved is True
    assert resolution.deltas == resolution.result.deltas
    assert [type(delta).__name__ for delta in resolution.deltas] == [
        "ZoneMoved",
        "CardDrawn",
        "LifeChanged",
    ]
    assert resolution.deltas[0].operation is OperationKind.SEND_TO_GRAVE


def test_the_journal_records_the_effect_the_executor_applied(state):
    engine = draw_engine(1, 1)
    chain = chain_of((MINE, 0), (THEIRS, 1))

    steps = engine.resolver.resolve_all(state, chain)

    assert len(engine.journal) == 2
    # 해결 순서대로 적힌다 — 체인 2 가 먼저다.
    assert [event.sequence for event in engine.journal] == [0, 1]
    assert [event.actor for event in engine.journal] == [THEIRS, MINE]
    assert all(event.kind is EventKind.EFFECT for event in engine.journal)
    for step, event in zip(steps, engine.journal):
        assert event.effect_ref == step.link.effect_ref
        assert event.deltas == step.deltas


def test_the_chain_does_not_journal_anything_of_its_own(state):
    """
    기록은 실행기가 하던 그대로다. 체인이 따로 적으면 같은 사건이 두 번
    남는다.
    """
    engine = draw_engine(1)
    engine.resolver.resolve_top(state, chain_of((MINE, 0)))

    assert len(engine.journal) == 1
    assert engine.journal[0].kind is EventKind.EFFECT
    assert engine.journal.of_kind(EventKind.COST_PAYMENT) == ()


def test_resolving_through_a_chain_leaves_the_same_trace_as_resolving_directly():
    """
    **경계가 지켜졌다는 증거.** 체인을 거친 해결과 직접 해결이 판도 기록도
    같아야 한다 — 다르면 체인이 실행기를 흉내 내고 있다는 뜻이다.
    """
    held = definition(0, DrawOperation(2), LifeChangeOperation(-300))

    direct_state = new_state()
    direct = Engine(held)
    direct_result = direct.executor.execute(
        direct_state,
        held,
        ChainLink(0, MINE, EffectRef(CARD, 0)).resolution_context(),
    )

    chained_state = new_state()
    chained = Engine(held)
    chained_step = chained.resolver.resolve_top(chained_state, chain_of((MINE, 0)))

    assert direct_state.state_hash() == chained_state.state_hash()
    assert direct_result.canonical_state() == chained_step.result.canonical_state()
    assert direct.journal.journal_hash() == chained.journal.journal_hash()


def test_the_resolver_refuses_to_apply_effects_itself():
    engine = draw_engine(1)
    for forbidden in ("move", "draw", "change_life", "_apply", "_plan"):
        assert not hasattr(engine.resolver, forbidden), forbidden
    assert engine.resolver.executor is engine.executor


def test_the_resolver_refuses_an_observation(state):
    engine = draw_engine(1)
    view = GameStateView.from_state(state, viewer=MINE)
    with pytest.raises(TypeError):
        engine.resolver.resolve_top(view, chain_of((MINE, 0)))


def test_a_resolver_needs_a_real_executor_and_a_definition_source():
    with pytest.raises(TypeError):
        ChainResolver("not an executor", EffectDefinitionRegistry())
    with pytest.raises(TypeError):
        ChainResolver(EffectExecutor(), object())


# ======================================================================
# R~S. 결정론
# ======================================================================


def test_the_canonical_state_is_plain_data():
    chain = Chain().activate(
        THEIRS,
        EffectRef(CARD, 1),
        source=InstanceId(3),
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(5))),),
        payments=(CostPayment(CostSemantics.PAY_LIFE, amount=800, player=THEIRS),),
    )

    canonical = chain.canonical_state()
    text = json.dumps(canonical, ensure_ascii=False)

    assert "0x" not in text and "object at" not in text
    json.dumps(chain.to_dict(), ensure_ascii=False)
    assert chain.canonical_state() == chain.canonical_state()


def test_the_same_chain_compares_equal():
    first = chain_of((MINE, 0), (THEIRS, 1))
    same = chain_of((MINE, 0), (THEIRS, 1))
    other = chain_of((THEIRS, 0), (THEIRS, 1))

    assert first == same
    assert first.canonical_state() == same.canonical_state()
    assert first != other
    assert first.canonical_state() != other.canonical_state()


def test_the_same_input_resolves_the_same_way():
    steps, states, journals = [], [], []
    for _ in range(2):
        board = new_state()
        engine = draw_engine(1, 2, 1)
        run = engine.resolver.resolve_all(board, chain_of((MINE, 0), (THEIRS, 1), (MINE, 2)))
        steps.append(run)
        states.append(board)
        journals.append(engine.journal)

    assert [s.canonical_state() for s in steps[0]] == [
        s.canonical_state() for s in steps[1]
    ]
    assert states[0].state_hash() == states[1].state_hash()
    assert journals[0].journal_hash() == journals[1].journal_hash()


def test_the_serialization_does_not_depend_on_the_hash_seed():
    """``PYTHONHASHSEED`` 를 바꿔 별도 프로세스에서 실제로 확인한다."""
    snippet = textwrap.dedent(
        """
        import json
        from engine.chain import Chain
        from engine.cost import CostPayment, CostSemantics, Selection
        from engine.effect import PRIMARY_TARGET, TargetSelection
        from engine.ids import EffectRef, InstanceId

        chain = Chain().activate(
            0, EffectRef(2511, 0), source=InstanceId(4),
            selections=(TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(9))),),
            payments=(CostPayment(CostSemantics.DISCARD, (InstanceId(2),), player=0),),
        ).activate(1, EffectRef(2511, 1))
        print(json.dumps([chain.canonical_state(), chain.to_dict()],
                         ensure_ascii=False, sort_keys=True))
        """
    )
    outputs = []
    for seed in ("0", "1", "98765"):
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
# T. 우선권과의 분리
# ======================================================================


def test_priority_and_chain_stay_separate():
    """
    ``PriorityState.resolve_chain()`` 같은 것은 만들지 않는다. 우선권은
    체인을 모르고, 체인은 우선권을 모른다.
    """
    import engine.chain as chain_module
    import engine.priority as priority_module

    priority = PriorityState.opened(ResponseWindow.RESPONSE, THEIRS)
    for forbidden in ("chain", "resolve_chain", "links", "top"):
        assert not hasattr(priority, forbidden), forbidden

    chain = chain_of((MINE, 0))
    for forbidden in ("priority", "holder", "window", "passed", "give_to"):
        assert not hasattr(chain, forbidden), forbidden

    # 두 모듈은 서로를 import 하지 않는다.
    assert not hasattr(priority_module, "Chain")
    assert not hasattr(chain_module, "PriorityState")
    chain_source = __import__("pathlib").Path("engine/chain.py").read_text(
        encoding="utf-8"
    )
    priority_source = __import__("pathlib").Path("engine/priority.py").read_text(
        encoding="utf-8"
    )
    assert "from engine.priority" not in chain_source
    assert "import engine.priority" not in chain_source
    assert "engine.chain" not in priority_source


def test_passing_priority_does_not_touch_the_chain(state):
    """우선권 전이는 체인을 건드리지 않는다. 둘은 서로를 모른다."""
    engine = draw_engine(1, 1)
    chain = chain_of((MINE, 0), (THEIRS, 1))
    priority = PriorityState.opened(ResponseWindow.RESPONSE, MINE)
    before = (chain.canonical_state(), state.state_hash())

    after = priority.passed().passed()

    assert after.both_passed is True
    assert chain.canonical_state() == before[0]
    assert chain.resolved_count == 0  # 패스가 체인을 해결하지 않는다
    assert state.state_hash() == before[1]
    assert len(engine.journal) == 0


def test_both_passing_does_not_decide_what_happens_to_the_chain():
    """
    "둘 다 패스했다" 는 사실일 뿐이다. 체인이 끝나는지는 여기서 정하지
    않는다.
    """
    priority = PriorityState.opened(ResponseWindow.RESPONSE, MINE).passed().passed()
    chain = chain_of((MINE, 0))

    assert priority.both_passed is True
    assert chain.is_complete is False  # 패스와 해결은 별개다
    assert priority.is_open is True


# ======================================================================
# U. 가려진 정보
# ======================================================================


def test_the_chain_layer_never_reads_the_board(state):
    """
    ``Chain`` · ``ChainLink`` 는 ``GameStateView`` 를 만들지도 읽지도 않는다.
    그래서 가려진 정보가 이 계층을 통해 새어 나갈 길이 없다.
    """
    source = __import__("pathlib").Path("engine/chain.py").read_text(encoding="utf-8")

    assert "GameStateView.from_state" not in source
    assert "analysis" not in source

    chain = chain_of((MINE, 0))
    for forbidden in ("view", "state", "find", "player"):
        assert not hasattr(chain, forbidden), forbidden


def test_a_link_only_names_what_its_activator_supplied(state):
    """
    링크에 들어가는 것은 발동한 쪽이 스스로 내놓은 식별자뿐이다. 상대의
    가려진 카드의 ``card_id`` 나 정의를 임의로 끼워 넣는 길이 없다.
    """
    hidden = state.player(THEIRS).hand[0]
    link = ChainLink(0, MINE, EffectRef(CARD, 0))

    data = link.to_dict()
    assert set(data) <= {
        "sequence",
        "actor",
        "effect_ref",
        "source",
        "selections",
        "payments",
    }
    assert str(hidden.card_id) not in json.dumps(data, ensure_ascii=False)


def test_the_chain_resolves_the_same_way_whoever_is_watching():
    """
    체인 해결은 관측자에 따라 달라지지 않는다 — 무엇이 발동되었는지는 공개
    정보다. 가려진 정보에 새어 들어가 있었다면 두 판이 갈렸을 것이다.

    상대 패에 실제로 다른 카드가 들어 있는 두 판에서 같은 체인을 해결하고,
    **해결 결과가 같은지**를 본다.
    """
    boards, results = [], []
    for extra in (5000, 6000):
        board = new_state()
        # 상대 패의 내용만 다르게 만든다.
        board.create_instance(extra, owner=THEIRS, zone=Zone.HAND)
        engine = draw_engine(1, 1)
        steps = engine.resolver.resolve_all(
            board, chain_of((MINE, 0), (THEIRS, 1))
        )
        boards.append(board)
        results.append(steps)

    assert [s.canonical_state() for s in results[0]] == [
        s.canonical_state() for s in results[1]
    ]
    # 내 쪽 판은 똑같이 변했다. 상대 패의 차이는 해결에 끼어들지 않았다.
    assert boards[0].player(MINE).canonical_state(
        boards[0].instance_numbering()
    ) == boards[1].player(MINE).canonical_state(boards[1].instance_numbering())


# ======================================================================
# Mutation safety (§17)
# ======================================================================


def test_building_and_inspecting_a_chain_never_touches_the_board(state):
    engine = draw_engine(1, 1)
    before = state.state_hash()

    chain = chain_of((MINE, 0), (THEIRS, 1))
    _ = chain.top, chain.pending, chain.resolved, chain.resolution_order
    _ = chain.remaining, chain.is_empty, chain.is_complete
    engine.resolver.next_link(chain)
    engine.resolver.definition_for(chain.top)
    chain.advanced()

    assert state.state_hash() == before
    assert len(engine.journal) == 0


def test_a_cloned_board_resolves_independently(state):
    """체인은 판 밖에 살지만, 같은 체인을 두 판에 써도 서로 섞이지 않는다."""
    copy = state.clone()
    assert copy.state_hash() == state.state_hash()

    engine = draw_engine(1)
    chain = chain_of((MINE, 0))
    engine.resolver.resolve_top(copy, chain)

    assert copy.state_hash() != state.state_hash()
    assert len(state.player(MINE).hand) == 4
    assert chain.resolved_count == 0  # 원래 체인도 그대로다


def test_a_chain_is_not_part_of_the_board_hash(state):
    """
    체인은 판의 **모양**이 아니라 흐름의 위치다 (``EventJournal`` ·
    ``PriorityState`` 와 같은 이유).
    """
    twin = new_state()
    assert state.state_hash() == twin.state_hash()

    _ = chain_of((MINE, 0), (THEIRS, 1)).advanced()

    assert state.state_hash() == twin.state_hash()
    assert state.journal == []  # GameState.journal 자리표시는 여전히 비어 있다


def test_selections_inside_a_link_cannot_be_mutated_from_outside():
    chosen = Selection.of(InstanceId(4))
    link = ChainLink(
        0, MINE, EffectRef(CARD, 0), selections=(TargetSelection(PRIMARY_TARGET, chosen),)
    )

    assert isinstance(link.selections, tuple)
    with pytest.raises(Exception):
        link.selections[0].selection = Selection.of(InstanceId(99))
    assert link.selections[0].selection == chosen
