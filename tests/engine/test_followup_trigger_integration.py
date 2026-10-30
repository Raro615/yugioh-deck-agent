"""
Phase 6-AB 보완5 ② — **체인 해결 중 발생한 실제 사건의 후속 유발.**

무엇을 재는가
-------------
체인이 풀리는 **그 안에서** 판이 바뀐다. 기르수 ①이 풀리면 덱의 카드 한
장이 묘지로 간다. 그 이동은 **사건**이고, 그 사건에 반응하는 유발 효과가
있으면 체인이 **다 풀린 뒤에** 발동 기회를 얻는다.

이 파일은 그 한 바퀴를 **실제 카드 · 실제 사건**으로 돌린다.

    실제 해결 → 저널의 ``ZoneMoved`` → 실제 Lua 가 만든 시점 선언 →
    후보 생성 → 체인 중에는 오르지 않음 → 다 풀린 뒤 후보 →
    ``Duel.apply`` → 상대 응답 → 해결 → 판과 저널 일치 →
    같은 사건 재발동 차단 → 일반 흐름 복귀

실제인 것과 합성인 것
---------------------
🔴 **섞어 적지 않는다.**

실제
    카드(``93920420`` 星遺物－『星杖』) · 그 카드가 묘지로 가는 사건 ·
    그 사건의 번호와 개체 · 실제 Lua 가 만든 **시점 선언**
    (``EVENT_TO_GRAVE`` + ``EFFECT_TYPE_TRIGGER_O`` + ``EFFECT_FLAG_DELAY``
    → ``@card_moved subject=SELF to_zones={GRAVE} OPTIONAL IF``) ·
    후보 생성 · 다섯 관문 · 체인 구성 · 응답 · 해결 · 소비 기록

합성
    **조작 하나뿐이다** — 드로우 1장. 실제 효과는 패에서 「星遺物」 몬스터를
    특수 소환하는 것이고, 특수 소환은 이 범위 밖이다. 그래서 그 칸만
    룰북의 드로우로 바꿔 끼웠다.

🔴 **그래서 이것은 ``93920420`` 의 지원 완료가 아니다.** ``E`` 절이 그
사실을 센다 — 프로덕션 등록부에는 이 정의가 **없다.**

무엇이 막고 있었나
------------------
막고 있던 것은 둘이었고 **둘 다 누락이었다** (새 규칙이 필요하지 않았다).

1. **후보를 세는 쪽이 다른 등록부를 보았다.** ``trigger_offers`` 는
   프로덕션 등록부로만 판정했고, 그래서 다른 등록부를 꽂은 판에서는
   발동기 · 해결기는 그 효과를 아는데 후보 판정만 "정의가 등록되어 있지
   않아 조건을 확인할 수 없습니다" 로 끝났다 (실측). 보완4 가
   ``Simulator._fork`` 에서 고친 것과 같은 병이다
   (:func:`integration.autonomy._duel_registries`).

2. **발동 자리를 모른다고 했다.** ``activation_zone`` 관문이
   ``UNKNOWN``(*"발동할 수 있는 자리가 선언되지 않았습니다"*) 을 냈다 —
   ``EFFECT_TYPE_SINGLE`` 트리거 등록은 ``SetRange`` 를 적지 않기 때문이다.
   6-V 가 **소환 사건**에 대해 같은 자리를 이미 풀어 두었고
   (:func:`engine.trigger.summoned_zone_for`), 보완5 가 **묘지 도착**에
   대해 같은 모양으로 풀었다 (:func:`engine.trigger.graveyard_zone_for`).
   근거는 룰북 *Trigger Effect* 절의 예문이다.

   🔴 **묘지만이다.** 덱 · 패 · 제외 도착은 그대로 ``UNKNOWN`` 이고,
   ``D`` 절이 그 경계를 센다.

여기서 하지 않은 것
-------------------
특수 소환 구현 · ``93920420`` 의 실제 효과 · 체인 도중 끼어드는 빠른 효과의
세부 (상자 D~F) · 숨은 자리의 유발 순서 · 카드별 정답 전개.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent.choice import FirstPermittedChoice
from agent.simulation import Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.activation import EffectActivator
from engine.chain import ChainResolver
from engine.condition import PlayerRef, ZoneCountAtLeast
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectProvenance,
)
from engine.effect.delta import ZoneMoved
from engine.effect.executor import EffectImplementationRegistry
from engine.effect.library import (
    EFFECT_LIBRARY,
    OPERATION_RULINGS,
    LibraryEntry,
    build_executor,
    definition_registry,
)
from engine.effect.operation import DrawOperation, OperationKind
from engine.ids import EffectRef, InstanceId
from engine.payment import CostPayer
from engine.priority import ResponseWindow
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerStatus,
    graveyard_zone_for,
    timing_events,
)
from engine.vocabulary import ActivationKind, Zone
from integration.autonomy import (
    TriggerSource,
    _duel_registries,
    _integrator,
    trigger_offers,
)
from integration.trigger_registry import registry_for_view
from tests.conftest import requires_official_db
from tests.engine.test_trigger_normal_path_integration import (
    GIRSU,
    GROWTH,
    MINE,
    THEIRS,
    _board,
    _summon,
    _trigger_action,
)

pytestmark = requires_official_db

#: 실제 Lua 의 **둘째** 효과 등록 — ``EVENT_TO_GRAVE`` 트리거다.
FOLLOW_REF = EffectRef(GROWTH, 1)
GIRSU_REF = EffectRef(GIRSU, 0)


# ======================================================================
# 합성 — **조작 하나뿐**
# ======================================================================
FOLLOW_DEFINITION = EffectDefinition(
    effect_ref=FOLLOW_REF,
    source_card_id=GROWTH,
    targets=(),
    operations=(DrawOperation(count=1, who=PlayerRef.CONTROLLER),),
    activation=ZoneCountAtLeast(PlayerRef.CONTROLLER, Zone.DECK, 1),
    activation_kind=ActivationKind.TRIGGER,
    provenance=EffectProvenance.hand_written(
        verified=True,
        note=(
            "🔴 합성 — **조작만** 바꿔 끼웠다. 시점 선언(묘지 도착 · 임의 · "
            "IF)은 실제 Lua 가 만든 것이고 이 정의가 주장하지 않는다. 실제 "
            "효과는 패에서 「성유물」 몬스터를 특수 소환하는 것이고, 여기서는 "
            "룰북의 드로우 한 장으로 바꾸었다. 이것은 93920420 의 지원 "
            "완료가 아니다. "
            "🔴 **Phase 6-AC 정정** — 이 주석은 '특수 소환은 이 범위 밖이므로' "
            "라고 적고 있었고, 그 문장은 더 이상 참이 아니다 (실제 효과가 "
            "EFFECT_LIBRARY 에 등재되었다). 합성을 **그래도 유지하는** 이유는 "
            "다른 것이다: 이 파일이 재는 것은 **후속 유발의 배선**이고, 조작이 "
            "특수 소환이면 그 측정이 소환 관문(등록된 카드 사실 · 빈 칸)과 "
            "엉킨다. 한 조작만 남겨 두면 배선만 재진다."
        ),
    ),
)

#: 🔴 **실제 등재를 빼고 합성을 끼운다** (Phase 6-AC).
#:
#: 6-AC 가 ``93920420:e[1]`` 을 프로덕션 목록에 등재했으므로, 그냥 더하면
#: 같은 ``EffectRef`` 가 두 번 등록되어 ``EffectDefinitionRegistry`` 가
#: 거절한다 (실측: 수집 단계에서 ``EffectDefinitionError``). 더하는 것이
#: 아니라 **갈아 끼우는** 것이 이 파일의 뜻이다 — 같은 효과의 조작만 바꾼
#: 사본이다.
FOLLOW_ENTRIES = tuple(
    entry for entry in EFFECT_LIBRARY if entry.effect_ref != FOLLOW_REF
) + (
    LibraryEntry(
        definition=FOLLOW_DEFINITION,
        lua_file="(합성 조작 — 선언은 c93920420.lua)",
        lua_excerpt="(합성 — 드로우 1장. 실제 카드 효과가 아니다)",
        executable=True,
    ),
)
assert len(FOLLOW_ENTRIES) == len(EFFECT_LIBRARY), (
    "합성은 **갈아 끼우는** 것이다 — 목록의 길이가 달라지면 실제 등재를 "
    "빼지 못했다는 뜻이다."
)
FOLLOW_DEFINITIONS = EffectDefinitionRegistry(
    tuple(entry.definition for entry in FOLLOW_ENTRIES)
)


def _wired(duel, chooser):
    """
    합성 조작을 **그 판의 등록부에** 꽂은 사본.

    🔴 프로덕션 등록부를 건드리지 않는다 (``E`` 절이 센다). 유발 원천은
    **실제** :class:`TriggerSource` 그대로다 — 제안을 지어내지 않는다.
    """
    implementations = EffectImplementationRegistry()
    for entry in FOLLOW_ENTRIES:
        if entry.executable:
            implementations.register(entry.effect_ref)
    if chooser is not None:
        chooser.definitions = FOLLOW_DEFINITIONS
    return dataclasses.replace(
        duel,
        _activator=EffectActivator(
            FOLLOW_DEFINITIONS,
            implementations,
            payer=CostPayer(journal=duel.journal),
        ),
        _resolver=ChainResolver(
            build_executor(
                journal=duel.journal,
                entries=FOLLOW_ENTRIES,
                rulings=OPERATION_RULINGS,
                chooser=chooser,
            ),
            FOLLOW_DEFINITIONS,
        ),
    )


def _refs(duel, seat: int = MINE):
    return [
        a.effect_ref
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]


def _resolved_girsu(repository):
    """기르수 ①이 **실제로 풀린** 판. 그 해결이 증거 카드를 묘지에 넣었다."""
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = _wired(setup.duel, chooser)

    action = _trigger_action(duel, card_id=GIRSU)
    assert action is not None
    assert duel.apply(action).accepted
    links_during = (_refs(duel, MINE), _refs(duel, THEIRS))

    duel.apply(PlayerAction.passing(actor=duel.priority.holder.seat))
    resolved = duel.apply(PlayerAction.passing(actor=duel.priority.holder.seat))
    assert "해결" in resolved.reason, resolved.reason
    assert duel.chain.is_empty
    return duel, chooser, links_during


def _grave_move(duel):
    """해결이 쓴 **묘지 이동 사건** 하나. 없으면 실패한다."""
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
# A. 실제 사건이 실제로 적혔다
# ======================================================================
def test_a01_resolution_writes_a_real_zone_move(repository):
    """체인 해결이 ``ZoneMoved`` (덱 → 묘지) 를 저널에 쓴다."""
    duel, _, _ = _resolved_girsu(repository)
    recorded, event = _grave_move(duel)

    assert recorded.effect_ref == GIRSU_REF
    assert event.point is TimingPoint.CARD_MOVED
    assert event.delta.movement is OperationKind.SEND_TO_GRAVE
    assert event.delta.source_zone is Zone.DECK
    assert event.delta.destination_zone is Zone.GRAVE
    assert event.delta.destination_player == MINE


def test_a02_the_moved_card_is_the_real_card_and_it_is_visible(repository):
    """그 카드가 **실제 ``93920420``** 이고 관측에 보인다."""
    duel, _, _ = _resolved_girsu(repository)
    _recorded, event = _grave_move(duel)

    instance = duel.state.find_instance(event.delta.card)
    assert instance is not None
    assert instance.card_id == GROWTH
    assert instance.zone is Zone.GRAVE

    seen = duel.view(MINE).find(event.delta.card)
    assert seen is not None and seen.zone is Zone.GRAVE


def test_a03_the_real_lua_produces_the_timing_declaration(repository):
    """
    그 시점 선언은 **실제 Lua 에서 나온다** — 합성이 아니다.

    등록은 **관측에 보이는 카드**만 한다 (``registry_for_view``), 그래서
    카드가 묘지에 보이는 지금 올라 있다.
    """
    duel, _, _ = _resolved_girsu(repository)
    build = registry_for_view(duel.view(MINE), repository)

    spec = next(
        (s for s in build.registry.specs if s.effect_ref == FOLLOW_REF), None
    )
    assert spec is not None, [str(s.effect_ref) for s in build.registry.specs]
    assert spec.point is TimingPoint.CARD_MOVED
    assert Zone.GRAVE in spec.to_zones
    #: 🔴 **``activates_from`` 은 비어 있다** — 그것이 ``D`` 절의 전제다.
    assert spec.activates_from is None


# ======================================================================
# B. 후보 생성 — 끼어들지 않고, 다 풀린 뒤에 오른다
# ======================================================================
def test_b01_the_grave_gate_licenses_the_zone(repository):
    """묘지 도착 관문이 자리를 인정하고 후보가 ``ELIGIBLE`` 이 된다."""
    duel, _, _ = _resolved_girsu(repository)
    _recorded, event = _grave_move(duel)
    view = duel.view(MINE)
    definitions, implementations = _duel_registries(duel)
    integrator = _integrator(
        view,
        registry_for_view(view, repository).registry,
        definitions=definitions,
        implementations=implementations,
    )

    ordering = integrator.collect_and_order(event)
    found = [
        e for e in ordering.canonical_sequence
        if e.candidate.effect_ref == FOLLOW_REF
    ]
    assert found, ordering
    eligibility = found[0]
    assert eligibility.status is TriggerStatus.ELIGIBLE
    zone_gate = next(
        g for g in eligibility.gates if g.gate.value == "activation_zone"
    )
    assert "GRAVE" in zone_gate.result.reason
    assert "이동 사건이" in zone_gate.result.reason


def test_b02_it_does_not_interject_while_the_chain_stands(repository):
    """체인이 서 있는 동안은 **어느 자리에도** 오르지 않는다 (聖鳥クレイン)."""
    _duel, _chooser, during = _resolved_girsu(repository)
    mine_during, theirs_during = during

    assert mine_during == []
    assert theirs_during == []


def test_b03_it_appears_after_the_chain_fully_resolves(repository):
    """다 풀린 뒤에 **후보로** 오른다 — 실제 사건에서 나온 것이다."""
    duel, _, _ = _resolved_girsu(repository)
    _recorded, event = _grave_move(duel)

    offers = trigger_offers(duel, repository, MINE)
    follow = [o for o in offers if o.effect_ref == FOLLOW_REF]
    assert follow, offers
    assert follow[0].source == event.delta.card
    assert follow[0].controller == MINE
    assert FOLLOW_REF in _refs(duel, MINE)


# ======================================================================
# C. 정상 경로 — 발동 · 응답 · 해결 · 재발동 차단 · 복귀
# ======================================================================
def test_c01_activating_it_builds_a_chain_link(repository):
    """``Duel.apply`` 가 체인 1 을 세우고 **상대 응답 기회**를 연다."""
    duel, _, _ = _resolved_girsu(repository)
    action = next(a for a in duel.legal_actions(MINE).allowed
                  if a.effect_ref == FOLLOW_REF)

    step = duel.apply(action)

    assert step.accepted, step.reason
    assert len(duel.chain) == 1
    link = duel.chain.links[0]
    assert link.chain_number == 1
    assert link.effect_ref == FOLLOW_REF
    assert link.actor == MINE
    assert duel.priority.window is ResponseWindow.RESPONSE
    assert duel.priority.holder.seat == THEIRS


def test_c02_resolving_it_changes_the_board_and_the_journal_agrees(repository):
    """
    해결이 **실제로** 판을 바꾸고, 저널과 ``GameState`` 가 같은 말을 한다.

    🔴 우선권 값이 움직인 것을 실행 성공으로 적지 않는다.
    """
    duel, _, _ = _resolved_girsu(repository)
    hand_before = len([c for c in duel.state.player(MINE).hand if c])
    deck_before = len([c for c in duel.state.player(MINE).zone(Zone.DECK) if c])
    events_before = len(duel.journal.events)

    duel.apply(next(a for a in duel.legal_actions(MINE).allowed
                    if a.effect_ref == FOLLOW_REF))
    duel.apply(PlayerAction.passing(actor=THEIRS))
    resolved = duel.apply(PlayerAction.passing(actor=MINE))

    assert resolved.accepted
    assert "해결" in resolved.reason
    assert duel.chain.is_empty

    #: 판 — 드로우 한 장.
    assert len([c for c in duel.state.player(MINE).hand if c]) == hand_before + 1
    assert (
        len([c for c in duel.state.player(MINE).zone(Zone.DECK) if c])
        == deck_before - 1
    )

    #: 저널 — 같은 사실을 **그 효과의 이름으로** 적었다.
    written = list(duel.journal)[events_before:]
    assert len(written) == 1
    assert written[0].effect_ref == FOLLOW_REF
    assert any("드로우" in str(d) for d in written[0].deltas)


def test_c03_the_same_event_cannot_be_used_twice(repository):
    """같은 사건으로 **두 번** 발동할 수 없다 — 소비가 기록된다."""
    duel, _, _ = _resolved_girsu(repository)
    action = next(a for a in duel.legal_actions(MINE).allowed
                  if a.effect_ref == FOLLOW_REF)
    assert duel.apply(action).accepted

    #: 후보에서 사라졌다.
    assert FOLLOW_REF not in _refs(duel, MINE)
    #: 그리고 **직접 넣어도** 거절된다.
    again = duel.apply(action)
    assert not again.accepted

    #: 소비 기록에 (사건, 효과, 개체) 가 남았다.
    consumed = [k for k in duel.consumed_events if k[1] == FOLLOW_REF]
    assert len(consumed) == 1
    assert consumed[0][2] == action.source


def test_c04_after_everything_the_normal_flow_returns(repository):
    """
    해결 뒤 **빠른 효과 기회**를 거쳐 일반 흐름으로 돌아간다.

    ①과 ②가 맞물리는 자리다 — 후속 유발의 체인이 풀린 뒤에도 곧바로 열린
    상태가 되지 않는다.
    """
    duel, _, _ = _resolved_girsu(repository)
    duel.apply(next(a for a in duel.legal_actions(MINE).allowed
                    if a.effect_ref == FOLLOW_REF))
    duel.apply(PlayerAction.passing(actor=THEIRS))
    duel.apply(PlayerAction.passing(actor=MINE))

    #: 🔴 아직 열리지 않았다 — 빠른 효과 기회가 열려 있다.
    assert duel.priority.is_open
    assert duel.priority.window is ResponseWindow.RESPONSE
    assert sorted({a.kind.value for a in duel.legal_actions(MINE).allowed}) == [
        "pass"
    ]

    duel.apply(PlayerAction.passing(actor=duel.priority.holder.seat))
    duel.apply(PlayerAction.passing(actor=duel.priority.holder.seat))

    assert not duel.priority.is_open
    kinds = sorted({a.kind.value for a in duel.legal_actions(MINE).allowed})
    assert "end_phase" in kinds
    assert duel.apply(PlayerAction.end_phase(actor=MINE)).accepted


def test_c05_a_fork_does_not_spend_the_parents_chance(repository):
    """사본에서 후속 유발을 써도 **원본의 기회는 남는다.**"""
    duel, _, _ = _resolved_girsu(repository)
    fork = Simulator(duel=duel)._fork()

    assert FOLLOW_REF in _refs(fork, MINE)
    assert fork.apply(
        next(a for a in fork.legal_actions(MINE).allowed
             if a.effect_ref == FOLLOW_REF)
    ).accepted

    assert FOLLOW_REF in _refs(duel, MINE)
    assert duel.chain.is_empty
    assert not [k for k in duel.consumed_events if k[1] == FOLLOW_REF]


# ======================================================================
# D. 관문의 경계 — ``graveyard_zone_for`` 가 **읽기**임을 센다
# ======================================================================
def _moved(destination: Zone, card: InstanceId) -> TimingEvent:
    return TimingEvent(
        point=TimingPoint.CARD_MOVED,
        delta=ZoneMoved(
            movement=OperationKind.SEND_TO_GRAVE,
            card=card,
            source_player=MINE,
            source_zone=Zone.DECK,
            destination_player=MINE,
            destination_zone=destination,
        ),
        actor=MINE,
    )


@pytest.mark.parametrize(
    "destination",
    [Zone.DECK, Zone.HAND, Zone.REMOVED, Zone.MZONE, Zone.SZONE],
)
def test_d01_only_the_graveyard_is_licensed(destination):
    """
    묘지가 **아닌** 도착지는 ``None`` — 원래의 ``UNKNOWN`` 이 그대로 나간다.

    🔴 모르는 것을 허가로 바꾸지 않는다. 거기서 발동할 수 있다는 공식 근거를
    찾지 못했다.
    """
    card = InstanceId(7)
    assert graveyard_zone_for(_moved(destination, card), card) is None


def test_d02_the_graveyard_is_licensed():
    """묘지 도착은 그 ``Zone`` 을 돌려준다 — 룰북 *Trigger Effect* 의 예문."""
    card = InstanceId(7)
    assert graveyard_zone_for(_moved(Zone.GRAVE, card), card) is Zone.GRAVE


def test_d03_another_cards_move_is_not_mine():
    """**다른 카드**의 이동은 ``None`` — 같은 이름 카드의 자리가 열리지 않는다."""
    moved = _moved(Zone.GRAVE, InstanceId(7))
    assert graveyard_zone_for(moved, InstanceId(8)) is None


def test_d04_a_non_move_event_says_nothing():
    """이동 사건이 아니면 ``None``. 사건이 없어도 ``None``."""
    summoned = TimingEvent(
        point=TimingPoint.EFFECT_RESOLVED, delta=None, effect_ref=GIRSU_REF,
        actor=MINE,
    )
    assert graveyard_zone_for(summoned, InstanceId(7)) is None
    assert graveyard_zone_for(None, InstanceId(7)) is None
    assert graveyard_zone_for(_moved(Zone.GRAVE, InstanceId(7)), None) is None


def test_d05_if_the_card_moved_again_the_gate_says_unknown(repository):
    """
    사건이 적은 도착지와 **지금 자리**가 다르면 ``UNKNOWN`` 이다.

    🔴 사건만 믿고 통과시키지 않는다 — 관측이 규칙의 입력이다.
    """
    duel, _, _ = _resolved_girsu(repository)
    _recorded, event = _grave_move(duel)

    #: 그 카드를 묘지에서 **제외로** 옮긴다 (해결 중의 추가 이동을 흉내).
    instance = duel.state.find_instance(event.delta.card)
    duel.state.move(instance, Zone.REMOVED, to_player=MINE)

    view = duel.view(MINE)
    definitions, implementations = _duel_registries(duel)
    integrator = _integrator(
        view,
        registry_for_view(view, repository).registry,
        definitions=definitions,
        implementations=implementations,
    )
    ordering = integrator.collect_and_order(event)

    #: ``ELIGIBLE`` 이 아니므로 ``canonical_sequence`` 에 들지 않는다.
    assert not [
        e for e in ordering.canonical_sequence
        if e.candidate.effect_ref == FOLLOW_REF
    ]
    #: 그리고 후보에도 오르지 않는다.
    assert FOLLOW_REF not in [
        o.effect_ref for o in trigger_offers(duel, repository, MINE)
    ]


# ======================================================================
# E. 합성을 실제 지원으로 적지 않는다
# ======================================================================
def test_e01_production_knows_the_real_effect_not_this_operation():
    """
    🔴 **프로덕션 등록부가 아는 조작은 이것이 아니다.**

    🔴 **Phase 6-AC 정정.** 이 테스트는 "프로덕션 등록부에는 이 **정의**가
    없다" 였고, 그 근거는 *"실제 효과(특수 소환)는 구현되지 않았다"* 였다.
    6-AC 가 그 효과를 구현해 등재했으므로 앞 문장은 더 이상 참이 아니다.

    재는 요구는 그대로다 — **이 파일의 성공이 그 카드의 지원을 주장하지
    않는다.** 그래서 정의의 유무 대신 **조작의 차이**를 센다: 프로덕션은
    특수 소환을, 이 파일은 드로우를 쓴다.
    """
    from engine.effect.operation import OperationKind

    production = definition_registry()
    real = production.definition_for(FOLLOW_REF)
    assert real is not None
    assert FOLLOW_REF in [entry.effect_ref for entry in EFFECT_LIBRARY]
    assert [op.kind for op in real.operations] == [
        OperationKind.SPECIAL_SUMMON
    ]
    assert [op.kind for op in FOLLOW_DEFINITION.operations] == [
        OperationKind.DRAW
    ]
    assert real.canonical_state() != FOLLOW_DEFINITION.canonical_state()


def test_e02_what_is_synthetic_is_the_operation_only():
    """합성한 것은 **조작 하나**이고, 그 사실이 출처에 적혀 있다."""
    assert len(FOLLOW_DEFINITION.operations) == 1
    assert isinstance(FOLLOW_DEFINITION.operations[0], DrawOperation)
    assert FOLLOW_DEFINITION.targets == ()
    note = FOLLOW_DEFINITION.provenance.note
    assert "합성" in note
    assert "지원 완료가 아니다" in note


def test_e03_the_timing_declaration_is_not_asserted_by_the_definition(
    repository,
):
    """
    시점 · 임의 여부는 **정의가 말하지 않는다** — 등록소가 Lua 에서 만든다.

    그래서 합성 정의를 꽂아도 "이 카드가 언제 유발하는가" 는 실제 Lua 의
    답이 그대로 쓰인다.
    """
    duel, _, _ = _resolved_girsu(repository)
    spec = next(
        s
        for s in registry_for_view(duel.view(MINE), repository).registry.specs
        if s.effect_ref == FOLLOW_REF
    )
    offers = [
        o for o in trigger_offers(duel, repository, MINE)
        if o.effect_ref == FOLLOW_REF
    ]
    assert offers
    #: 제안의 강제 여부는 **선언**에서 왔다.
    assert offers[0].requirement is spec.requirement


# ======================================================================
# F. 등록부 전달 — 후보를 세는 쪽과 해결하는 쪽이 같은 것을 본다
# ======================================================================
def test_f01_duel_registries_reads_the_duels_own(repository):
    """``_duel_registries`` 가 **그 판의** 등록부를 돌려준다."""
    duel, _, _ = _resolved_girsu(repository)
    definitions, implementations = _duel_registries(duel)

    assert definitions is duel._activator.definitions
    assert implementations is duel._activator.lookup
    assert definitions.definition_for(FOLLOW_REF) is not None


def test_f02_without_a_duel_registry_it_says_so():
    """등록부를 들고 있지 않으면 ``(None, None)`` — 그때는 프로덕션이 쓰인다."""
    class _Bare:
        pass

    assert _duel_registries(_Bare()) == (None, None)


def test_f03_the_registry_decides_which_operation_runs(repository):
    """
    🔴 **이것이 ①이 고친 결함이다.** 등록부가 다르면 같은 실제 사건에서
    같은 후보의 **판정과 실행 내용**이 갈린다.

    같은 판 · 같은 사건 · 같은 선언이고 **등록부만 다르다.**

    🔴 **Phase 6-AC 정정.** 전에는 프로덕션 등록부에 이 효과의 정의가
    **없어서** 후보가 아예 오르지 않았고, 그 차이로 결함을 보였다. 6-AC 가
    실제 효과를 등재했으므로 이제 **둘 다** 후보를 올린다 — 갈리는 것은
    후보의 유무가 아니라 **그 후보가 실행할 조작**이다. ①의 요구(사본이
    원본의 등록부를 물려받아야 한다)는 그대로이고, 그 요구를 **더 정확한
    축**으로 센다.
    """
    from engine.effect.operation import OperationKind

    duel, _, _ = _resolved_girsu(repository)
    _recorded, event = _grave_move(duel)
    view = duel.view(MINE)
    registry = registry_for_view(view, repository).registry

    duel_definitions, duel_implementations = _duel_registries(duel)
    with_duel = _integrator(
        view,
        registry,
        definitions=duel_definitions,
        implementations=duel_implementations,
    ).collect_and_order(event)
    with_production = _integrator(view, registry).collect_and_order(event)

    assert [e.candidate.effect_ref for e in with_duel.canonical_sequence] == [
        FOLLOW_REF
    ]
    assert [
        e.candidate.effect_ref for e in with_production.canonical_sequence
    ] == [FOLLOW_REF]

    #: 🔴 **같은 후보 · 다른 조작.** 등록부가 실행 내용을 정한다.
    assert [
        op.kind for op in duel_definitions.definition_for(FOLLOW_REF).operations
    ] == [OperationKind.DRAW]
    assert [
        op.kind
        for op in definition_registry().definition_for(FOLLOW_REF).operations
    ] == [OperationKind.SPECIAL_SUMMON]
