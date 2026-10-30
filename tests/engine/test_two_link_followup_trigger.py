"""
Phase 6-AB 보완6 ② — **2링크 체인 해결 중 발생한 사건의 후속 유발.**

보완5 가 재지 못한 것
---------------------
보완5 는 실제 기르수 해결 → 묘지 이동 사건 → 후속 후보 → 해결까지 쟀다.
**그 성과는 그대로다.** 다만 그 체인은 **링크 하나**였고, "이미 발생한
후속 사건이 남은 링크의 해결을 기다린다" 는 재지 못했다.

보완5 의 ``_resolved_girsu`` 는 ``links_during`` 을 기르수 **발동 직후**,
즉 묘지 이동 사건이 일어나기 **전**에 조회했다. 그때 후보가 없다는 사실은
*"사건이 아직 없다"* 는 뜻이고 *"사건은 있는데 남은 링크를 기다린다"* 가
아니다. 보완5 보고서의 BLOCKER-F5-3 이 그 미완료를 적었다.

이 파일이 재는 순서
-------------------
**CL2 의 사건 발생 → CL1 해결 → 후속 유발 등재 → 후속 효과 해결.**

    CL1 = 69811710:e[1]   합성 드로우 — 나중에 해결된다
    CL2 = 69811710:e[0]   🔴 **실제 기르수 ①** — 덱의 카드를 묘지로 보낸다
    후속 = 93920420:e[1]  🔴 실제 Lua 선언 (EVENT_TO_GRAVE) · 합성 조작

체인은 역순으로 풀리므로 **CL2 가 먼저** 해결되어 사건을 쓰고, 그때 CL1 은
아직 남아 있다. 두 링크 모두 ``legal_actions`` → ``Duel.apply`` 로 등재하고,
순서는 **고르는 쪽**이 정한다 (룰북의 *"in any order"*).

해결 경계를 어떻게 관찰했나
---------------------------
🔴 **테스트를 위한 공개 step API 를 만들지 않았다.**
:meth:`~engine.chain.ChainResolver.resolve_all` 이 체인 전체를 한
``Duel.apply`` 안에서 해결하므로 **중간에서 후보를 조회할 자리가 구조상
없다.** 그 사실을 숨기지 않고, 대신 셋으로 입증한다.

1. **저널의 실행 순서** — CL2 의 기록이 CL1 의 기록보다 앞이다 (``B`` 절).
2. **해결 걸음의 체인 상태** — ``ChainResolver`` 를 상속해 ``super()`` 를
   그대로 부르고 결과만 적는 계측으로, CL2 가 해결된 **그 걸음**에서
   체인이 ``resolved_count=1 · is_complete=False`` 임을 본다. 즉 그 순간
   CL1 이 남아 있었다 (``B`` 절). 🔴 **계측은 허가 · 상태 · 제어 흐름을
   바꾸지 않는다** — ``C`` 절이 계측 있는 판과 없는 판의 결과가 같음을 센다.
3. **후보의 부재와 등장** — 체인이 서 있는 동안 양측 후보가 비어 있고,
   전부 해결된 뒤에 나타난다 (``C`` 절).

🔴 **1번을 "규칙상 동시성" 으로 읽지 않는다.** 저널이 적는 것은 **실행
순서**이고, 그것이 여기서 재려는 것이다.

실제와 합성
-----------
========================================  ==========================
카드 `69811710` · `93920420`               🔴 실제 (cdb · Lua)
기르수 ①의 조작 (덱 → 묘지)                🔴 실제
그 사건 · 사건 번호 · 개체 · 자리           🔴 실제
후속의 시점 선언 (``EVENT_TO_GRAVE``)       🔴 실제 Lua
후보 생성 · 다섯 관문 · 체인 · 해결 · 소비   🔴 실제
**CL1 의 조작** (드로우 1장)                합성
**후속의 조작** (드로우 1장)                합성
========================================  ==========================

🔴 **그래서 실제 카드 지원 완료가 아니다** — ``H`` 절이 프로덕션 등록부에
두 합성 정의가 **없다**는 것을 센다.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent.choice import FirstPermittedChoice
from agent.simulation import Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.activation import EffectActivator
from engine.activation_timing import ActivationStage
from engine.chain import ChainResolver
from engine.effect.definition import EffectDefinitionRegistry
from engine.effect.delta import ZoneMoved
from engine.effect.executor import EffectImplementationRegistry
from engine.effect.library import (
    EFFECT_LIBRARY,
    OPERATION_RULINGS,
    build_executor,
    definition_registry,
)
from engine.effect.operation import OperationKind
from engine.ids import EffectRef
from engine.payment import CostPayer
from engine.priority import ResponseWindow
from engine.trigger import TimingPoint, timing_events
from engine.vocabulary import Zone
from integration.autonomy import TriggerSource
from tests.conftest import requires_official_db
from tests.engine.test_followup_trigger_integration import (
    FOLLOW_DEFINITION,
    FOLLOW_ENTRIES,
    FOLLOW_REF,
)
from tests.engine.test_trigger_normal_path_integration import (
    GIRSU,
    GROWTH,
    MINE,
    THEIRS,
    _board,
    _summon,
)
from tests.engine.test_trigger_window_completion import (
    REAL_REF,
    SYNTH_DEFINITION,
    SYNTH_ENTRIES,
    SYNTH_REF,
)
from tests.engine.window_helpers import pass_fast_window

pytestmark = requires_official_db

#: CL1 — 합성 드로우가 앉는 칸 (기르수의 둘째 효과 자리).
CL1_REF = SYNTH_REF
#: CL2 — **실제** 기르수 ①. 덱의 증거 카드를 묘지로 보낸다.
CL2_REF = REAL_REF

#: 합성 정의 **둘**을 한 등록부에 — CL1 의 드로우와 후속의 드로우.
#:
#: 🔴 **갈아 끼운다** (Phase 6-AC). 6-AC 가 ``93920420:e[1]`` 의 실제 효과를
#: 프로덕션 목록에 등재했으므로, 합성을 그냥 더하면 같은 ``EffectRef`` 가 두
#: 번 등록되어 등록부가 거절한다 (실측: 수집 단계의
#: ``EffectDefinitionError``). ``test_followup_trigger_integration`` 이 같은
#: 이유로 같은 모양을 쓴다.
_FOLLOW_ENTRY = next(e for e in FOLLOW_ENTRIES if e.effect_ref == FOLLOW_REF)
ENTRIES = tuple(
    e for e in SYNTH_ENTRIES if e.effect_ref != FOLLOW_REF
) + (_FOLLOW_ENTRY,)
assert len(ENTRIES) == len(SYNTH_ENTRIES), (
    "합성은 갈아 끼우는 것이다 — 길이가 달라지면 실제 등재를 빼지 못했다."
)
DEFINITIONS = EffectDefinitionRegistry(
    tuple(entry.definition for entry in ENTRIES)
)


class _PairOnce:
    """
    🔴 **합성 — 기르수 ① 제안 하나만 쌍으로 만든다.**

    보완5 의 ``_Pair`` 는 실제 원천이 낸 **모든** 제안을 ``SYNTH_REF`` 로
    복제한다. 그러면 **후속 유발 제안까지 가짜 쌍이 생기고**, 이 파일이
    재려는 것(실제 사건에서 나온 후속 제안)이 흐려진다.

    그래서 복제 대상을 하나로 못박고 나머지는 **그대로 흘린다** — 후속
    제안은 실제 :class:`TriggerSource` 가 만든 것 그대로다.

    🔴 **원하는 시점의 제안을 하드코딩하지 않는다.** 이 자리가 하는 일은
    실제 제안 하나의 ``effect_ref`` 칸을 바꾼 짝을 하나 더 내는 것뿐이고,
    사건 · 사건 번호 · 개체 · 자리는 전부 실제 값이다. 후속 제안은
    **손대지 않는다.**
    """

    def __init__(self, repository):
        self._inner = TriggerSource(repository)

    def offers(self, duel, seat: int):
        out = []
        for offer in self._inner.offers(duel, seat):
            if offer.effect_ref == CL2_REF:
                out.append(dataclasses.replace(offer, effect_ref=CL1_REF))
            out.append(offer)
        return tuple(out)


class _WatchingResolver(ChainResolver):
    """
    🔴 **읽기만 하는 계측.** ``super()`` 를 그대로 부르고 결과를 적는다.

    바꾸지 않는 것: 허가 · 상태 · 제어 흐름 · 돌려주는 값. ``resolve_all``
    의 반환을 그대로 돌려주므로 부르는 쪽이 보는 것이 달라지지 않는다
    (``C`` 절이 계측 있는 판과 없는 판을 대조한다).

    왜 상속인가 — :meth:`~engine.response.ResponseLoop.resolve` 가
    ``isinstance(resolver, ChainResolver)`` 를 요구한다. 감싸는 객체는
    거절되므로, **같은 타입**이면서 아무것도 바꾸지 않는 쪽을 쓴다.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observed: list[tuple] = []

    def resolve_all(self, state, chain):
        steps = super().resolve_all(state, chain)
        self.observed.append(
            tuple(
                (
                    step.link.chain_number,
                    step.link.effect_ref,
                    len(step.chain.links),
                    step.chain.resolved_count,
                    step.chain.is_complete,
                )
                for step in steps
            )
        )
        return steps


def _wire(duel, chooser, repository, *, watching: bool = False):
    """합성 정의 둘을 **그 판의 등록부에** 꽂은 사본."""
    implementations = EffectImplementationRegistry()
    for entry in ENTRIES:
        if entry.executable:
            implementations.register(entry.effect_ref)
    if chooser is not None:
        chooser.definitions = DEFINITIONS
    executor = build_executor(
        journal=duel.journal,
        entries=ENTRIES,
        rulings=OPERATION_RULINGS,
        chooser=chooser,
    )
    resolver_type = _WatchingResolver if watching else ChainResolver
    return dataclasses.replace(
        duel,
        _activator=EffectActivator(
            DEFINITIONS,
            implementations,
            payer=CostPayer(journal=duel.journal),
        ),
        _resolver=resolver_type(executor, DEFINITIONS),
        triggers=_PairOnce(repository),
    )


def _activations(duel, seat: int = MINE, ref: EffectRef | None = None):
    return [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and (ref is None or a.effect_ref == ref)
    ]


def _two_links(repository, *, watching: bool = False):
    """
    **CL1 · CL2 가 정상 경로로 올라간** 판. 아직 풀지 않는다.

    순서는 고르는 쪽이 정한다 — 합성 드로우를 먼저 올려 **실제 기르수 ①이
    CL2** 가 되게 한다. 그러면 역순 해결로 기르수 ①이 먼저 풀린다.
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = _wire(setup.duel, chooser, repository, watching=watching)

    first = next(a for a in _activations(duel, MINE, CL1_REF))
    assert duel.apply(first).accepted
    second = next(a for a in _activations(duel, MINE, CL2_REF))
    assert duel.apply(second).accepted

    assert [link.effect_ref for link in duel.chain.links] == [CL1_REF, CL2_REF]
    return duel, chooser


def _resolve(duel):
    """체인을 **실제 PASS 로** 푼다. 해결 걸음을 돌려준다."""
    resolution = None
    for _ in range(6):
        if not duel.priority.is_open:
            break
        holder = duel.priority.holder.seat
        passing = PlayerAction.passing(actor=holder)
        assert passing in duel.legal_actions(holder).allowed
        had_chain = not duel.chain.is_empty
        step = duel.apply(passing)
        if had_chain and duel.chain.is_empty:
            resolution = step
            break
    assert resolution is not None
    return resolution


def _grave_move(duel):
    """해결이 쓴 **묘지 이동 사건** 하나와 그 기록."""
    for recorded in duel.journal:
        for event in timing_events(recorded):
            delta = event.delta
            if (
                isinstance(delta, ZoneMoved)
                and delta.destination_zone is Zone.GRAVE
            ):
                return recorded, event
    raise AssertionError("해결이 묘지 이동 사건을 쓰지 않았습니다")


# ======================================================================
# A. 두 링크를 **정상 경로로** 올린다
# ======================================================================
def test_a01_both_links_go_through_legal_actions_and_apply(repository):
    """
    🔴 **체인 링크를 주입하지 않는다.** 둘 다 후보 목록에 오르고
    ``Duel.apply`` 가 수락한다.
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = _wire(setup.duel, chooser, repository)

    assert duel._activation_stage() is ActivationStage.TRIGGER_REGISTRATION
    offered = [a.effect_ref for a in _activations(duel, MINE)]
    assert CL1_REF in offered and CL2_REF in offered, offered

    first = next(a for a in _activations(duel, MINE, CL1_REF))
    step1 = duel.apply(first)
    assert step1.accepted is True
    assert len(duel.chain) == 1

    second = next(a for a in _activations(duel, MINE, CL2_REF))
    step2 = duel.apply(second)
    assert step2.accepted is True
    assert len(duel.chain) == 2

    assert [l.chain_number for l in duel.chain.links] == [1, 2]
    assert [l.effect_ref for l in duel.chain.links] == [CL1_REF, CL2_REF]
    assert all(l.actor == MINE for l in duel.chain.links)


def test_a02_the_order_is_the_choosers(repository):
    """
    묶음 안의 순서는 **고르는 쪽**의 것이다 (룰북 *"in any order"*).

    같은 판에서 반대로 올리면 체인도 반대다 — 그래서 이 파일이 CL2 를
    실제 기르수 ①로 **만들 수 있다.**
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = _wire(setup.duel, chooser, repository)

    duel.apply(next(a for a in _activations(duel, MINE, CL2_REF)))
    duel.apply(next(a for a in _activations(duel, MINE, CL1_REF)))

    assert [l.effect_ref for l in duel.chain.links] == [CL2_REF, CL1_REF]


# ======================================================================
# B. 필수 실행 순서 — CL2 의 사건 → CL1 해결
# ======================================================================
def test_b01_the_journal_records_cl2_before_cl1(repository):
    """
    🔴 **저널이 실행 순서를 적는다** — CL2 의 기록이 CL1 의 기록보다 앞이다.

    그리고 CL2 의 기록이 들고 있는 것이 **후속 유발이 기다리던 사건**이다
    (덱 → 묘지).
    """
    duel, _ = _two_links(repository)
    before = len(duel.journal.events)

    _resolve(duel)

    written = [
        rec for rec in list(duel.journal)[before:] if rec.kind.name == "EFFECT"
    ]
    assert [rec.effect_ref for rec in written] == [CL2_REF, CL1_REF], [
        (r.sequence, str(r.effect_ref)) for r in written
    ]
    #: CL2 의 기록이 사건을 들고 있다.
    cl2 = written[0]
    moves = [d for d in cl2.deltas if isinstance(d, ZoneMoved)]
    assert len(moves) == 1
    assert moves[0].source_zone is Zone.DECK
    assert moves[0].destination_zone is Zone.GRAVE
    assert moves[0].movement is OperationKind.SEND_TO_GRAVE
    #: 그리고 CL1 의 기록은 **그 뒤**다.
    assert written[1].sequence > cl2.sequence


def test_b02_when_cl2_resolved_cl1_was_still_on_the_chain(repository):
    """
    🔴 **이것이 보완5 가 재지 못한 것이다.**

    CL2 가 해결된 **그 걸음**에서 체인은 링크 둘 · 해결 하나 · 미완료다 —
    즉 사건이 일어난 그 순간 **CL1 이 아직 남아 있었다.** 그 다음 걸음이
    CL1 이다.

    관찰은 기존 해결 경계에서 읽기만 한다 (:class:`_WatchingResolver`).
    """
    duel, _ = _two_links(repository, watching=True)
    _resolve(duel)

    observed = duel._resolver.observed
    assert len(observed) == 1, observed
    steps = observed[0]
    assert len(steps) == 2, steps

    #: ① 먼저 CL2 가 해결된다 — 그때 체인은 **미완료**다.
    number, ref, links, resolved, complete = steps[0]
    assert (number, ref) == (2, CL2_REF)
    assert links == 2
    assert resolved == 1
    assert complete is False

    #: ② 그 뒤에 CL1 이 해결되고 체인이 완료된다.
    number, ref, links, resolved, complete = steps[1]
    assert (number, ref) == (1, CL1_REF)
    assert resolved == 2
    assert complete is True


def test_b03_the_moved_card_is_the_real_evidence_card(repository):
    """사건의 주체가 **실제 ``93920420``** 이고 해결 뒤 묘지에 보인다."""
    duel, _ = _two_links(repository)
    _resolve(duel)
    _recorded, event = _grave_move(duel)

    instance = duel.state.find_instance(event.delta.card)
    assert instance is not None
    assert instance.card_id == GROWTH
    assert instance.zone is Zone.GRAVE
    assert event.point is TimingPoint.CARD_MOVED

    seen = duel.view(MINE).find(event.delta.card)
    assert seen is not None and seen.zone is Zone.GRAVE


# ======================================================================
# C. 후속 유발 — 끼어들지 않고, 전부 풀린 뒤에 나타난다
# ======================================================================
def test_c01_nothing_is_offered_while_the_chain_stands(repository):
    """
    체인이 서 있는 동안 **양측 후보가 비어 있다.**

    🔴 이것만으로 "지연 처리" 를 주장하지 않는다 — 그 시점에는 사건이 아직
    없다. 지연을 입증하는 것은 ``B`` 절이고, 이 줄은 **끼어들지 않는다**는
    별개의 사실이다.
    """
    duel, _ = _two_links(repository)

    assert len(duel.chain) == 2
    assert duel._activation_stage() is ActivationStage.CHAIN_RESPONSE
    assert _activations(duel, MINE) == []
    assert _activations(duel, THEIRS) == []


def test_c02_the_followup_appears_only_after_the_whole_chain(repository):
    """전부 풀린 뒤에 후속 유발이 **후보로** 오른다."""
    duel, _ = _two_links(repository)
    _resolve(duel)
    _recorded, event = _grave_move(duel)

    offered = _activations(duel, MINE, FOLLOW_REF)
    assert offered, [str(a.effect_ref) for a in _activations(duel, MINE)]
    assert offered[0].source == event.delta.card
    assert duel.chain.is_empty


def test_c03_the_instrumentation_changes_nothing(repository):
    """
    🔴 **계측이 결과를 바꾸지 않는다.** 계측 있는 판과 없는 판이 같은
    판 · 같은 기록 · 같은 후보를 낸다.
    """
    plain, _ = _two_links(repository, watching=False)
    watched, _ = _two_links(repository, watching=True)
    _resolve(plain)
    _resolve(watched)

    assert plain.state.state_hash() == watched.state.state_hash()
    assert [
        (r.sequence, str(getattr(r, "effect_ref", "")), r.kind.name)
        for r in plain.journal
    ] == [
        (r.sequence, str(getattr(r, "effect_ref", "")), r.kind.name)
        for r in watched.journal
    ]
    assert [a.effect_ref for a in _activations(plain, MINE)] == [
        a.effect_ref for a in _activations(watched, MINE)
    ]
    assert plain.consumed_events == watched.consumed_events


# ======================================================================
# D. 후속 효과를 정상 경로로
# ======================================================================
def test_d01_it_builds_a_new_chain_and_opens_a_response(repository):
    """``Duel.apply`` 가 **새** 체인 1 을 세우고 상대 응답 기회를 연다."""
    duel, _ = _two_links(repository)
    _resolve(duel)

    step = duel.apply(_activations(duel, MINE, FOLLOW_REF)[0])

    assert step.accepted is True
    assert len(duel.chain) == 1
    link = duel.chain.links[0]
    assert link.chain_number == 1
    assert link.effect_ref == FOLLOW_REF
    assert link.actor == MINE
    assert duel.priority.window is ResponseWindow.RESPONSE
    assert duel.priority.holder.seat == THEIRS


def test_d02_resolving_it_changes_the_board_and_the_journal_agrees(repository):
    """해결이 판을 바꾸고 ``GameState`` 와 ``EventJournal`` 이 같은 말을 한다."""
    duel, _ = _two_links(repository)
    _resolve(duel)

    hand_before = len([c for c in duel.state.player(MINE).hand if c])
    deck_before = len([c for c in duel.state.player(MINE).zone(Zone.DECK) if c])
    events_before = len(duel.journal.events)

    duel.apply(_activations(duel, MINE, FOLLOW_REF)[0])
    duel.apply(PlayerAction.passing(actor=THEIRS))
    resolved = duel.apply(PlayerAction.passing(actor=MINE))

    assert resolved.accepted
    assert "해결" in resolved.reason
    assert duel.chain.is_empty

    assert len([c for c in duel.state.player(MINE).hand if c]) == hand_before + 1
    assert (
        len([c for c in duel.state.player(MINE).zone(Zone.DECK) if c])
        == deck_before - 1
    )

    written = list(duel.journal)[events_before:]
    assert len(written) == 1
    assert written[0].effect_ref == FOLLOW_REF
    assert any("드로우" in str(d) for d in written[0].deltas)


def test_d03_the_same_event_cannot_be_used_twice(repository):
    """같은 사건으로 **두 번** 발동할 수 없다 — 소비가 기록된다."""
    duel, _ = _two_links(repository)
    _resolve(duel)
    action = _activations(duel, MINE, FOLLOW_REF)[0]
    assert duel.apply(action).accepted

    assert _activations(duel, MINE, FOLLOW_REF) == []
    again = duel.apply(action)
    assert again.accepted is False

    consumed = [k for k in duel.consumed_events if k[1] == FOLLOW_REF]
    assert len(consumed) == 1
    assert consumed[0][2] == action.source
    #: 세 효과가 각각 자기 사건을 소비했다.
    assert {k[1] for k in duel.consumed_events} == {CL1_REF, CL2_REF, FOLLOW_REF}


def test_d04_and_then_the_normal_flow_returns(repository):
    """필요한 빠른 효과 기회를 거쳐 **정상 진행으로 돌아온다**."""
    duel, _ = _two_links(repository)
    _resolve(duel)
    duel.apply(_activations(duel, MINE, FOLLOW_REF)[0])
    duel.apply(PlayerAction.passing(actor=THEIRS))
    duel.apply(PlayerAction.passing(actor=MINE))

    #: 아직 열리지 않았다 — 해결 뒤의 빠른 효과 기회다.
    assert duel._activation_stage() is ActivationStage.FAST_WINDOW
    assert sorted({a.kind.value for a in duel.legal_actions(MINE).allowed}) == [
        "pass"
    ]

    pass_fast_window(duel)
    assert duel._activation_stage() is ActivationStage.OPEN
    kinds = sorted({a.kind.value for a in duel.legal_actions(MINE).allowed})
    assert "end_phase" in kinds
    assert duel.apply(PlayerAction.end_phase(actor=MINE)).accepted


# ======================================================================
# E. 사본 — 2링크 체인과 후속 기회가 섞이지 않는다
# ======================================================================
def test_e01_a_fork_sees_the_same_two_link_chain(repository):
    """사본이 **같은 체인 · 같은 단계 · 같은 후보**를 본다."""
    duel, _ = _two_links(repository)
    fork = Simulator(duel=duel)._fork()

    assert [l.effect_ref for l in fork.chain.links] == [
        l.effect_ref for l in duel.chain.links
    ]
    assert fork.chain.resolved_count == duel.chain.resolved_count
    assert fork._activation_stage() is duel._activation_stage()
    assert fork.priority.holder.seat == duel.priority.holder.seat
    assert _activations(fork, MINE) == _activations(duel, MINE)


def test_e02_a_fork_resolving_does_not_spend_the_parents_chain(repository):
    """사본이 체인을 풀고 후속까지 써도 **원본은 그대로**다."""
    duel, _ = _two_links(repository)
    before = (
        duel.state.state_hash(),
        len(duel.chain),
        duel.chain.resolved_count,
        frozenset(duel.consumed_events),
        len(duel.journal.events),
    )
    fork = Simulator(duel=duel)._fork()

    _resolve(fork)
    assert _activations(fork, MINE, FOLLOW_REF)
    assert fork.apply(_activations(fork, MINE, FOLLOW_REF)[0]).accepted

    assert (
        duel.state.state_hash(),
        len(duel.chain),
        duel.chain.resolved_count,
        frozenset(duel.consumed_events),
        len(duel.journal.events),
    ) == before
    assert len(duel.chain) == 2


# ======================================================================
# H. 합성을 실제 지원으로 적지 않는다
# ======================================================================
def test_h01_production_does_not_know_these_synthetic_operations():
    """
    🔴 **프로덕션 등록부에 이 파일의 합성 조작이 없다.**

    그래서 이 파일의 성공은 ``69811710`` 의 둘째 효과 지원이 **아니다.**

    🔴 **Phase 6-AC 정정.** 이 테스트는 "두 합성 정의가 **없다**" 였고,
    둘 중 하나(``93920420:e[1]``)는 이제 프로덕션에 **있다** — 6-AC 가 실제
    효과를 등재했다. 그래서 재는 것을 **정의의 유무에서 조작의 차이로**
    옮긴다: 프로덕션이 아는 그 효과의 조작은 **특수 소환**이고, 이 파일이
    쓰는 것은 **드로우**다. 즉 이 파일의 성공은 여전히 그 카드의 지원을
    주장하지 않는다.
    """
    from engine.effect.operation import DrawOperation, OperationKind

    production = definition_registry()
    refs = {entry.effect_ref for entry in EFFECT_LIBRARY}

    #: ① 기르수의 둘째 효과는 **여전히 없다.**
    assert production.definition_for(CL1_REF) is None
    assert CL1_REF not in refs

    #: ② 『성장』 ② 는 **있다.** 그런데 조작이 다르다 — 그것이 요점이다.
    real = production.definition_for(FOLLOW_REF)
    assert real is not None
    assert FOLLOW_REF in refs
    assert [op.kind for op in real.operations] == [
        OperationKind.SPECIAL_SUMMON
    ]
    assert isinstance(FOLLOW_DEFINITION.operations[0], DrawOperation)
    assert real.canonical_state() != FOLLOW_DEFINITION.canonical_state()


def test_h02_what_is_synthetic_is_the_operation_only():
    """합성한 것은 **조작 둘**이고, 그 사실이 각 출처에 적혀 있다."""
    for definition in (SYNTH_DEFINITION, FOLLOW_DEFINITION):
        assert len(definition.operations) == 1
        assert definition.targets == ()
        assert "합성" in definition.provenance.note


def test_h03_cl2_and_its_event_are_real(repository):
    """
    🔴 **CL2 는 합성이 아니다.** 실제 기르수 ①이고, 그 조작이 만든 사건이
    후속 유발이 기다린 사건이다 — 그것이 이 시나리오의 요점이다.
    """
    duel, _ = _two_links(repository)
    _resolve(duel)

    production = definition_registry()
    assert production.definition_for(CL2_REF) is not None
    assert CL2_REF.card_id == GIRSU

    recorded, event = _grave_move(duel)
    assert recorded.effect_ref == CL2_REF
    assert duel.state.find_instance(event.delta.card).card_id == GROWTH
