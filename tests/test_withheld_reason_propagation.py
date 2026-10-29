"""
Phase 6-AB 보완8 마무리 — **거절 사유가 결과까지 가는가.**

보완8 이 끝낸 것과 이 파일이 재는 것
------------------------------------
``c31067c`` 가 **엔진 쪽**을 끝냈다 (후보 제외 사유 보존 · 흐름 거절을 규칙
거절로 적기). 이 파일은 그 뒤에 남은 **전달**을 잰다.

1. ``agent.simulation`` 의 자동 PASS 가 **중간 기회의 미지원 사유를 버렸다.**
   실측 (검토 기준 HEAD ``c31067c``)::

       [1] P0 빠른 효과 기회 → activate_card [activation-timing]
       [2] P1 빠른 효과 기회 → 🔴 activate_effect [trap-activation-event]
       최종 (판이 다시 열림) → activate_card [activation-timing]
       SimulationResult.unsupported = (activate_card … ,)   ← 둘째가 없다

   🔴 그 재현에서 ``fully_supported`` 는 **다른 사유 때문에 이미 거짓**이었다.
   그래서 *"참으로 잘못 성공했다"* 가 아니라 **"진행 도중의 구체적인 사유가
   결과에서 유실된다"** 가 확인된 결함이다.

2. ``deck.opening._settle_chain`` 도 같은 모양이었다 — 조용히 패스만 하고
   부르는 쪽은 반복이 **끝난 뒤**의 자리만 읽었다.

관측 경계
---------
🔴 **다른 자리의 기회에서 만난 사유는 ``reason`` 을 싣지 않는다.** 보완8 이
비유발 후보의 사유에 ``EffectRef`` 를 넣었고, 뒷면 카드의 ``EffectRef`` 는
**그 카드의 정체**다. 종류와 ``missing``(규칙의 이름)만 넘기면 "이 미래는
끝까지 검증된 것이 아니다" 를 말하는 데 필요한 전부가 남는다.

실제와 합성
-----------
========================================  ==========================
``94192409`` 세트 전 발동 요청의 UNKNOWN    🔴 실제 카드
``73148972`` 두 조합 모두 거절               🔴 실제 카드
``94192409`` 네 조합 모두 허가               🔴 실제 카드
어니스트 · 욕망의 항아리 · 기르수 경로        🔴 실제 카드
``5915629`` 의 ``activation_waits_for_event``  **합성** (기존 관문을 밟기
                                            위한 조건이고 카드 수정 제안이
                                            아니다)
같은 카드에 효과 둘 (한쪽만 적법)             **합성**
========================================  ==========================
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from agent.simulation import SimulationStatus, Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.activation_timing import ActivationStage
from engine.duel import Duel, duel_components, target_combinations
from engine.effect.definition import EffectDefinitionRegistry
from engine.effect.library import EFFECT_LIBRARY
from engine.ids import EffectRef
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.target_bridge import selections_for
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone
from tests.conftest import requires_official_db
from tests.engine.test_trap_activation_free_chain import (
    GIFT_OF_GREED,
    LUSTER_DRAGON,
    POT_OF_GREED,
    next_turn,
    set_down,
    staged,
)
from tests.engine.window_helpers import pass_fast_window

pytestmark = requires_official_db

P0, P1 = 0, 1
GIFT_REF = EffectRef(GIFT_OF_GREED, 0)
COMPULSORY = 94192409          # 강제 탈출 장치 — 필드의 몬스터 1장을 패로
RUTHLESS = 73148972            # 무정한 거절 — 조합 둘이 모두 거절된다
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ======================================================================
# 공용 도구
# ======================================================================
def _fingerprint(duel):
    """판 · 체인 · 우선권 · 기회 수명 · 소비 · 기록을 **한 묶음**으로."""
    return (
        duel.state.state_hash(),
        duel.state.turn.phase,
        len(duel.chain),
        duel.chain.resolved_count,
        duel.window_floor,
        duel.chain_floor,
        duel.window_passed,
        frozenset(duel.consumed_events),
        duel.priority.window,
        duel.priority.holder.seat,
        duel.priority.consecutive_passes,
        len(duel.journal.events) if duel.journal is not None else 0,
        duel.state.randomness.draws,
    )


def _activations(duel, seat=P0, card_id=None):
    return [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and (card_id is None or a.effect_ref.card_id == card_id)
    ]


def _held(duel, seat=P0, kind=PlayerActionKind.ACTIVATE_EFFECT):
    return [w for w in duel.legal_actions(seat).withheld if w.kind is kind]


def _waiting_gift_registry():
    """
    🔴 **합성** — 욕망의 선물의 정의에서 ``activation_waits_for_event`` 만
    참으로 바꾼 등록부.

    기존 "이 발동은 특정 사건을 기다린다" 관문(``trap-activation-event``)을
    밟기 위한 조건이고, **실제 카드 효과를 고치자는 제안이 아니다.** 그
    관문은 보완8 이 만든 것이 아니라 Phase 6-Q 가 세운 자리다.
    """
    base = next(
        e.definition for e in EFFECT_LIBRARY if e.definition.effect_ref == GIFT_REF
    )
    assert base.activation_waits_for_event is False, "원래 값을 먼저 확인한다"
    waiting = dataclasses.replace(base, activation_waits_for_event=True)
    kept = tuple(
        e.definition for e in EFFECT_LIBRARY if e.definition.effect_ref != GIFT_REF
    )
    return EffectDefinitionRegistry(kept + (waiting,))


def _board_with_facedown_gift(repository, *, definitions):
    """
    P0 에게 세울 몬스터, P1 의 마법·함정 존에 **뒷면** 욕망의 선물.

    🔴 **초기 판 구성이다** — 이 뒤의 모든 변화는 ``Duel.apply`` 가 만든다.
    """
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [LUSTER_DRAGON] * 30),
        turn_player=P0,
        seed=1,
    )
    for _ in range(3):
        state.create_instance(LUSTER_DRAGON, owner=P0, zone=Zone.HAND)
    for _ in range(2):
        state.create_instance(LUSTER_DRAGON, owner=P1, zone=Zone.HAND)
    gift = state.create_instance(GIFT_OF_GREED, owner=P1, zone=Zone.SZONE)
    state.move(gift, Zone.SZONE, to_player=P1, position=Position.FACEDOWN)
    state.turn.turn_number = 5
    state.turn.turn_player = P0
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(definitions=definitions),
    )
    return duel, gift.instance_id


# ======================================================================
# A. 자동 PASS 중 사유 유실 — 최소 재현과 회귀
# ======================================================================
def test_a01_the_opponents_opportunity_is_walked_through(repository):
    """
    **먼저 흐름을 확인한다** — 자동 PASS 가 정말 상대 기회를 지나는가.

    이것을 확인하지 않으면 아래 ``a02`` 는 "중간 기회가 있었다" 를 재지 못한다.
    """
    duel, gift = _board_with_facedown_gift(
        repository, definitions=_waiting_gift_registry()
    )
    sets = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.SET_MONSTER
    ]
    assert sets

    probe = Simulator(duel=duel)._fork()
    assert probe.apply(sets[0]).accepted is True

    seats: list[int] = []
    met: list[tuple[int, str]] = []
    for _ in range(8):
        if not probe.priority.is_open:
            break
        seat = probe.to_act
        legal = probe.legal_actions(seat)
        seats.append(seat)
        met.extend((seat, w.missing) for w in legal.unsupported())
        passes = [a for a in legal.allowed if a.kind is PlayerActionKind.PASS]
        if not passes or len(passes) != len(legal.allowed):
            break
        probe.apply(passes[0])

    #: ① 양쪽 기회를 지난다 — 그래서 중간 자리가 **둘** 있다.
    assert seats == [P0, P1], seats
    #: ② 그리고 P1 의 기회에서 그 관문이 걸린다.
    assert any(
        seat == P1 and missing is not None and "trap-activation-event" in missing
        for seat, missing in met
    ), met
    #: ③ 판이 다시 열리고 턴 플레이어의 차례다.
    assert probe._activation_stage() is ActivationStage.OPEN
    assert probe.to_act == P0


def test_a02_a_mid_flight_reason_survives_the_auto_passes(repository):
    """
    🔴 **보완8 마무리의 본문** — 자동 PASS 중에 만난 사유가 결과에 남는다.

    🔴 **``fully_supported`` 는 이 재현에서 전후 모두 거짓이다** (다른 사유
    하나가 이미 있다). 고친 것은 *"성공으로 잘못 보고한다"* 가 아니라
    **"구체적인 사유가 사라진다"** 다 — 그 구분을 이 시험이 함께 센다.
    """
    duel, gift = _board_with_facedown_gift(
        repository, definitions=_waiting_gift_registry()
    )
    sets = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.SET_MONSTER
    ]
    before = _fingerprint(duel)

    result = Simulator(duel=duel).simulate(sets[0], viewer=P0)

    assert result.status is SimulationStatus.SUPPORTED
    #: 🔴 중간 기회의 사유가 **남아 있다.**
    assert any("trap-activation-event" in line for line in result.unsupported), (
        result.unsupported
    )
    #: 🔴 그리고 마지막 자리의 사유도 **그대로** 남아 있다 — 하나가 다른
    #: 하나를 밀어내지 않는다.
    assert any("activation-timing" in line for line in result.unsupported)
    #: 🔴 전후 모두 거짓이다 — 이 재현은 "성공으로 잘못 보고" 가 아니다.
    assert result.fully_supported is False

    #: 🔴 **원본은 그대로다** — 사본에서 걸었고 조회만 했다.
    assert _fingerprint(duel) == before


def test_a03_the_opponents_card_identity_does_not_leak(repository):
    """
    🔴 **상대 기회의 사유에 ``EffectRef`` 가 실리지 않는다.**

    보완8 이 비유발 후보의 사유에 효과 이름을 넣었으므로, 그 문장이 그대로
    넘어가면 **뒷면 카드의 정체**가 새어 나간다. 종류와 규칙 이름만 넘긴다.
    """
    duel, gift = _board_with_facedown_gift(
        repository, definitions=_waiting_gift_registry()
    )
    sets = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.SET_MONSTER
    ]
    result = Simulator(duel=duel).simulate(sets[0], viewer=P0)

    blob = "\n".join(result.unsupported)
    #: ① 그 카드 번호도 ``EffectRef`` 도 없다.
    assert str(GIFT_OF_GREED) not in blob
    assert str(GIFT_REF) not in blob
    #: ② 그런데 **사실은 남아 있다** — 누구의 기회였고 무엇이 없어서인지.
    assert "P1 의 기회에서 만났고" in blob
    assert "trap-activation-event" in blob
    #: ③ 지웠다는 것도 적는다 — "사유가 없다" 로 읽히지 않게.
    assert "관측 밖입니다" in blob

    #: ④ 🔴 **자기 자리의 사유는 문장째로 온다** — 경계가 과하게 지우지
    #: 않는다는 것을 같은 판에서 센다.
    theirs = Simulator(duel=duel).simulate(sets[0], viewer=P1)
    assert any("P0 의 기회에서 만났고" in line for line in theirs.unsupported)


def test_a04_the_same_reason_is_not_repeated(repository):
    """
    🔴 **같은 사유는 한 줄이다** — 자리마다 반복되지 않는다 (요구 ②).

    그리고 **다른 효과의 사유를 합치지 않는다**: 묶는 열쇠가 완성된 한 줄이고
    그 안에 종류 · 규칙 이름 · (자기 자리면) 효과 이름이 들어 있다.
    """
    duel, gift = _board_with_facedown_gift(
        repository, definitions=_waiting_gift_registry()
    )
    sets = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.SET_MONSTER
    ]
    result = Simulator(duel=duel).simulate(sets[0], viewer=P0)

    assert len(result.unsupported) == len(set(result.unsupported))
    #: ``activation-timing`` 은 양쪽 자리에서 다 걸리지만 **서로 다른 자리**
    #: 이므로 두 줄이고, 같은 자리의 반복은 없다.
    timing = [line for line in result.unsupported if "activation-timing" in line]
    assert len(timing) == 2, result.unsupported
    assert len({line for line in timing}) == 2


def test_a05_a_rule_refusal_is_never_collected_as_unsupported(repository):
    """
    🔴 **규칙상 거절은 미지원으로 집계되지 않는다** (요구 ②).

    빠른 효과 기회의 욕망의 항아리는 ``INVALID`` / ``SPELL_SPEED_TOO_LOW``
    이고 ``missing`` 이 비어 있다 — 그래서 ``unsupported()`` 에 들어가지
    않고, 자동 PASS 가 지나가며 모으는 목록에도 오지 않는다.
    """
    duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=3)
    sets = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.SET_SPELL_TRAP
    ]
    assert sets
    result = Simulator(duel=duel).simulate(sets[0], viewer=P0)

    #: ① 그 거절은 **보류에 있다** (보완8 이 보존한다).
    fork = Simulator(duel=duel)._fork()
    fork.apply(sets[0])
    refusals = _held(fork, P0)
    assert refusals, "빠른 효과 기회의 거절이 보류에 남아야 한다"
    assert all(w.code is ValidationCode.SPELL_SPEED_TOO_LOW for w in refusals)
    assert all(w.is_rule_refusal for w in refusals)

    #: ② 🔴 그런데 미지원 목록에는 **없다.**
    assert not any("스펠 스피드" in line for line in result.unsupported)
    assert not any(
        "spell_speed" in line.lower() for line in result.unsupported
    )


# ======================================================================
# B. 비유발 후보의 사유 — 실제 카드
# ======================================================================
def test_b01_a_real_unknown_survives_in_the_candidate_list(repository):
    """
    🔴 **실제 카드의 UNKNOWN 이 보류에 남는다** — 합성이 아니다.

    강제 탈출 장치(``94192409``)를 **패에서** 발동하려 하면 세트가 앞서야
    한다는 관문이 ``UNKNOWN`` 을 낸다 (``trap-activation-location``).
    보완8 전에는 그 판정이 조용히 버려졌다.
    """
    duel, sources, _ = staged(repository, mine=[COMPULSORY], fodder=2)
    for owner in (P0, P1):
        card = duel.state.create_instance(
            LUSTER_DRAGON, owner=owner, zone=Zone.MZONE
        )
        duel.state.move(
            card, Zone.MZONE, to_player=owner, position=Position.FACEUP_ATTACK
        )

    held = _held(duel, P0)
    assert len(held) == 1, held
    entry = held[0]
    assert entry.validity is ActionValidity.UNKNOWN
    assert entry.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert entry.missing is not None
    assert "trap-activation-location" in entry.missing
    #: 어느 효과인지가 문장에 남는다 — 자기 자리의 카드다.
    assert str(EffectRef(COMPULSORY, 0)) in entry.reason
    #: 그리고 미지원 집계에 **들어간다** — 모름이기 때문이다.
    assert entry in duel.legal_actions(P0).unsupported()


def test_b02_every_combination_refused_collapses_to_one_line(repository):
    """
    🔴 **조합이 여럿이어도 같은 사유는 한 줄이다** — 실제 카드로 센다.

    무정한 거절(``73148972``)은 이 판에서 조합 둘을 내고 **둘 다** 관문이
    거절한다. 보류는 한 줄이어야 한다 (요구 ③-8).
    """
    duel, sources, _ = staged(repository, mine=[RUTHLESS], fodder=2)
    for owner in (P0, P1):
        for _ in range(2):
            card = duel.state.create_instance(
                LUSTER_DRAGON, owner=owner, zone=Zone.MZONE
            )
            duel.state.move(
                card, Zone.MZONE, to_player=owner,
                position=Position.FACEUP_ATTACK,
            )

    definition = duel._activator.definitions.definition_for(
        EffectRef(RUTHLESS, 0)
    )
    validator = duel.activation_validator(P0)
    combos = list(
        target_combinations(duel.state, P0, definition, sources[0])
    )
    verdicts = []
    for targets in combos:
        candidate = PlayerAction.activate_effect(
            actor=P0, source=sources[0],
            effect_ref=definition.effect_ref, targets=targets,
        )
        verdicts.append(
            duel._activation_gate(
                candidate,
                validator=validator,
                selections=selections_for(definition, candidate),
            )
        )
    #: ① 조합이 둘이고 둘 다 거절이다 — 그 사실을 먼저 센다.
    assert len(combos) >= 2, combos
    assert all(v.validity is ActionValidity.INVALID for v in verdicts)

    #: ② 🔴 그런데 보류는 **한 줄**이다.
    held = [
        w for w in _held(duel, P0)
        if str(EffectRef(RUTHLESS, 0)) in w.reason
    ]
    assert len(held) == 1, held
    assert held[0].is_rule_refusal
    assert held[0].missing is None
    #: ③ 그래서 미지원 집계에도 들어가지 않는다.
    assert held[0] not in duel.legal_actions(P0).unsupported()


def test_b03_all_legal_combinations_stay_candidates(repository):
    """
    🔴 **합법 조합이 있으면 전부 후보로 남는다** — 과도하게 막지 않는다.

    세트해 둔 강제 탈출 장치는 양쪽 몬스터 넷 전부를 대상으로 삼을 수 있다.
    보류는 그 효과에 대해 **없어야** 한다.
    """
    duel, sources, _ = staged(repository, mine=[COMPULSORY], fodder=3)
    for owner in (P0, P1):
        for _ in range(2):
            card = duel.state.create_instance(
                LUSTER_DRAGON, owner=owner, zone=Zone.MZONE
            )
            duel.state.move(
                card, Zone.MZONE, to_player=owner,
                position=Position.FACEUP_ATTACK,
            )
    set_down(duel, sources[0])
    next_turn(duel, to_seat=P0)

    offered = _activations(duel, P0, COMPULSORY)
    assert len(offered) == 4, offered
    assert not [
        w for w in _held(duel, P0)
        if str(EffectRef(COMPULSORY, 0)) in w.reason
    ]


def test_b04_two_different_effects_keep_two_reasons(repository):
    """
    🔴 **서로 다른 효과의 사유를 합쳐 잃지 않는다** (요구 ②).

    패의 함정 둘(욕망의 선물 · 강제 탈출 장치)은 **같은 코드 · 같은 모자란
    것**으로 거절된다 (세트가 앞서야 한다). 코드만으로 묶으면 한 줄이 되고
    어느 효과가 걸렸는지 사라진다 — 묶는 열쇠에 효과가 들어 있어야 한다.

    🔴 **실제 카드 둘이다** — 합성이 아니다.
    """
    duel, sources, _ = staged(
        repository, mine=[GIFT_OF_GREED, COMPULSORY], fodder=2, their_hand=2
    )
    for owner in (P0, P1):
        card = duel.state.create_instance(
            LUSTER_DRAGON, owner=owner, zone=Zone.MZONE
        )
        duel.state.move(
            card, Zone.MZONE, to_player=owner, position=Position.FACEUP_ATTACK
        )

    held = _held(duel, P0)
    refs = {str(GIFT_REF), str(EffectRef(COMPULSORY, 0))}
    named = {ref for ref in refs if any(ref in w.reason for w in held)}
    assert named == refs, (named, [w.reason for w in held])
    #: 🔴 **두 줄이다** — 같은 코드·같은 모자란 것이어도 합치지 않는다.
    same = [w for w in held if any(ref in w.reason for ref in refs)]
    assert len(same) == 2, [w.reason for w in same]
    assert len({w.code for w in same}) == 1
    assert len({w.missing for w in same}) == 1
    #: 그리고 둘 다 모름이므로 미지원 집계에 들어간다.
    unsupported = duel.legal_actions(P0).unsupported()
    assert all(w in unsupported for w in same)


def test_b05_an_effect_with_no_definition_never_reaches_the_gate(repository):
    """
    🔴 **정의가 없어 후보 자체를 만들지 못하는 범위는 따로 적는다** (요구 ③).

    ``activatable_effects`` 가 ``EFFECT_LIBRARY`` 의 ``executable`` 항목만
    돌려주므로, 등재되지 않은 효과는 **관문에 닿지 않는다** — 그러면 적을
    판정도 없다. 보완8 이 보존한 것은 *관문이 낸 판정*이고, 이 범위는
    그것과 **다른 사실**이다.

    🔴 이 한계는 보고서에 남는다 — 모든 카드의 미지원 가능성을 새로 열거하는
    일은 이번 범위가 아니다.
    """
    from engine.spell_activation import activatable_effects

    duel, sources, _ = staged(repository, mine=[COMPULSORY], fodder=2)
    #: ① 등재된 자리는 ``e[0]`` 하나다 — ``e[1]`` 은 목록에 없다.
    offered = activatable_effects(COMPULSORY)
    assert [str(ref) for ref in offered] == [str(EffectRef(COMPULSORY, 0))]
    #: ② 그래서 ``e[1]`` 에 대한 보류도 없다 (판정이 없으므로).
    assert not [
        w
        for w in _held(duel, P0)
        if str(EffectRef(COMPULSORY, 1)) in w.reason
    ]


# ======================================================================
# C. 흐름 거절과 직접 apply 의 일치
# ======================================================================
@pytest.mark.parametrize(
    "scenario",
    ["fast_window_summon", "fast_window_end_phase", "off_turn_activation"],
)
def test_c01_the_withheld_reason_and_the_direct_apply_agree(repository, scenario):
    """
    🔴 **후보 제외 이유와 직접 ``apply`` 의 코드가 같다** — 세 흐름 제약에서.

    그리고 어느 것도 ``RULE_NOT_IMPLEMENTED`` 가 아니다 — 확인된 규칙이
    막은 것이므로.
    """
    if scenario == "off_turn_activation":
        duel, sources, _ = staged(
            repository, mine=[], fodder=3, their_hand=2, turn_player=P1
        )
        gift = duel.state.create_instance(
            GIFT_OF_GREED, owner=P1, zone=Zone.HAND
        ).instance_id
        set_down(duel, gift, seat=P1)
        next_turn(duel, to_seat=P0)
        seat = P1
        action = PlayerAction.activate_effect(
            actor=P1, source=gift, effect_ref=GIFT_REF
        )
        expected = ValidationCode.NOT_TURN_PLAYER
    else:
        duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=3)
        sets = [
            a
            for a in duel.legal_actions(P0).allowed
            if a.kind is PlayerActionKind.SET_SPELL_TRAP
        ]
        assert duel.apply(sets[0]).accepted
        assert duel._activation_stage() is ActivationStage.FAST_WINDOW
        seat = P0
        expected = ValidationCode.STAGE_FORBIDS_ACTION
        if scenario == "fast_window_end_phase":
            action = PlayerAction.end_phase(actor=P0)
        else:
            mine = [
                c
                for c in duel.state.player(P0).hand
                if c and c.card_id == LUSTER_DRAGON
            ]
            assert mine
            action = PlayerAction.normal_summon(
                actor=P0, source=mine[0].instance_id
            )

    held = _held(duel, seat, kind=action.kind)
    assert held, f"{scenario}: 보류가 없다"
    assert any(w.code is expected for w in held), [w.code for w in held]

    before = _fingerprint(duel)
    step = duel.apply(action)
    assert step.accepted is False
    assert step.code is expected, step.code
    assert step.code is not ValidationCode.RULE_NOT_IMPLEMENTED
    #: 🔴 거절은 판 · 체인 · 우선권 · 사건 · 소비 · 난수를 바꾸지 않는다.
    assert _fingerprint(duel) == before


def test_c02_a_different_effect_of_the_same_kind_is_not_borrowed(repository):
    """
    🔴 ``_withheld_for`` 가 **종류만 같은 다른 효과의 거절**을 가져오지
    않는다 (요구 ③).

    세트한 턴의 함정과 패의 통상 마법이 같은 ``activate_effect`` 종류로
    보류에 있을 때, 각자의 ``apply`` 가 **자기 이유**를 받아야 한다.
    """
    duel, sources, _ = staged(
        repository, mine=[GIFT_OF_GREED, POT_OF_GREED], fodder=3, their_hand=2
    )
    set_down(duel, sources[0])
    #: 🔴 **세트 뒤의 빠른 효과 기회를 지나 판을 다시 연다** — 그러지 않으면
    #: 통상 마법이 그 단계 때문에 거절되고 (보완6), 재려는 것이 그것이
    #: 아니다.
    pass_fast_window(duel)
    assert duel._activation_stage() is ActivationStage.OPEN
    trap = PlayerAction.activate_effect(
        actor=P0, source=sources[0], effect_ref=GIFT_REF
    )
    pot = PlayerAction.activate_effect(
        actor=P0, source=sources[1], effect_ref=EffectRef(POT_OF_GREED, 0)
    )

    #: ① 세트한 턴이므로 함정은 거절, 통상 마법은 **허가**다.
    assert pot in duel.legal_actions(P0).allowed
    assert trap not in duel.legal_actions(P0).allowed

    #: ② 함정의 ``apply`` 는 **자기 이유**를 받는다 — 관문의 판정이다.
    step = duel.apply(trap)
    assert step.accepted is False
    assert step.code is ValidationCode.SET_THIS_TURN

    #: ③ 그리고 통상 마법은 그대로 수락된다 — 무관한 거절 하나가 적법한
    #: 진행을 막지 않는다 (요구 ②).
    assert duel.apply(pot).accepted is True


# ======================================================================
# D. 사본 격리와 조회 순수성
# ======================================================================
def test_d01_a_fork_sees_the_same_candidates_and_reasons(repository):
    """원본 · 사본의 후보와 **제외 사유**가 같다."""
    duel, sources, _ = staged(repository, mine=[COMPULSORY], fodder=2)
    fork = Simulator(duel=duel)._fork()

    def snapshot(d):
        legal = d.legal_actions(P0)
        return (
            sorted(a.kind.value for a in legal.allowed),
            sorted(
                (w.kind.value, w.code.value, w.missing, w.reason, w.scope)
                for w in legal.withheld
            ),
        )

    assert snapshot(fork) == snapshot(duel)


def test_d02_reading_and_refusing_never_moves_the_board(repository):
    """
    🔴 **조회와 거절이 판을 바꾸지 않는다** — 보고를 위한 재조회도 포함한다.

    보완8 은 거절할 때 관문과 검증기를 **한 번 더** 돌린다. 그것이 상태를
    건드리면 보고가 판을 움직이는 셈이 된다.
    """
    duel, sources, _ = staged(repository, mine=[GIFT_OF_GREED], fodder=3)
    set_down(duel, sources[0])
    before = _fingerprint(duel)

    for _ in range(3):
        for seat in (P0, P1):
            duel.legal_actions(seat)
        duel.apply(
            PlayerAction.activate_effect(
                actor=P0, source=sources[0], effect_ref=GIFT_REF
            )
        )
    assert _fingerprint(duel) == before


def test_d03_a_forks_auto_passes_do_not_spend_the_parent(repository):
    """사본의 자동 PASS 가 원본의 기회 수명을 쓰지 않는다."""
    duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=3)
    sets = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.SET_SPELL_TRAP
    ]
    before = _fingerprint(duel)
    result = Simulator(duel=duel).simulate(sets[0], viewer=P0)
    assert result.status is SimulationStatus.SUPPORTED
    assert _fingerprint(duel) == before


# ======================================================================
# E. /combo 전달 — 토큰 없는 문자열 검사다
# ======================================================================
def _combo_blob(repository, hand: str, recipe: str) -> str:
    """
    🔴 **토큰 없는 응답 생성 검사다.** Discord 에 접속하지 않고, 접속했다고
    적지도 않는다 — ``combo_messages`` 가 돌려주는 문자열을 센다.
    """
    import app.discord_bot as bot

    class _Agent:
        def __init__(self, repo):
            self.repository = repo

    return "\n".join(
        bot.combo_messages(_Agent(repository), hand, recipe_text=recipe)
    )


USER_HAND = "69811710,703897,2930675,12989604,93920420"
USER_RECIPE = (
    "69811710 x3, 703897 x3, 2930675 x3, 12989604 x3, 93920420 x3, "
    "11091375 x25"
)


@pytest.mark.real_card
def test_e01_the_user_five_card_run_is_preserved(repository):
    """
    🔴 **사용자가 직접 확인한 5장 입력의 결과를 보존한다.**

    🔴 이 레시피는 **동작 확인용**이다 — 같은 카드 25장을 포함하므로 실제
    대회용 합법 덱도 추천 덱도 아니다. 그리고 여기서 검사하는 것은 *패가
    레시피에 포함되는가* 이고, 금제 · 동명 카드 매수 제한은 **다른 검사**다.
    """
    blob = _combo_blob(repository, USER_HAND, USER_RECIPE)

    #: ① 실행 걸음과 해결 걸음.
    assert "엔진이 실제로 5걸음 실행" in blob
    assert "실행 5걸음 · 상태 변경 5걸음" in blob
    assert "효과가 실제로 해결된 걸음** 1걸음" in blob

    #: ② 판 — 사용자가 적은 장수 그대로.
    assert "몬스터 존: 1장 — 잭나이츠 오르페골 기르수 [69811710]" in blob
    assert "마법·함정 존: 3장" in blob
    for card in ("703897", "2930675", "12989604"):
        assert card in blob
    assert "패: 1장 — 성유물－『성장』 [93920420]" in blob
    assert "묘지: 1장 — 성유물－『성장』 [93920420]" in blob
    assert "남은 덱: 34장" in blob

    #: ③ 멈춘 자리 — 흐름만 남았지만 **정상 종료가 아니다**.
    assert "end_phase" in blob
    assert "activate_card [activation-timing" in blob
    assert "정상 전개 종료가 아닙니다" in blob


@pytest.mark.real_card
def test_e02_the_generic_activate_card_reason_names_its_scope(repository):
    """
    🔴 **포괄적인 ``activate_card`` 사유가 무엇인지 적는다.**

    실측: 멈춘 자리에서 그 보류는 **실제로 만든 후보**의 판정이다 — 그 자리의
    패를 전부 묻고 (보완8 이 첫 장에서 멈추지 않게 했다) 같은 코드로 묶은
    것이다. 다만 **어느 카드인지는 적지 않는다** (가려진 정보 보호), 그래서
    "특정 카드의 미지원" 으로 추측해 표시하지 않는다.

    이 시험은 그 둘을 함께 센다: 범위는 ``scope`` 가 말하고, 식별자는 없다.
    """
    from deck.opening import build_opening, execute_opening
    from deck.recipe import parse_recipe
    from app.main import opening_wiring

    chooser, triggers = opening_wiring(repository)
    draft = parse_recipe(USER_RECIPE, repository).draft
    setup = build_opening(
        repository, draft, [69811710, 703897, 2930675, 12989604, 93920420],
        chooser=chooser, triggers=triggers,
    )
    assert setup.duel is not None, setup.blockers
    run = execute_opening(setup, repository)

    assert run.stopped_kind == "unsupported"
    duel = setup.duel
    seat = duel.to_act
    legal = duel.legal_actions(seat)
    held = [
        w for w in legal.withheld
        if w.kind is PlayerActionKind.ACTIVATE_CARD
    ]
    assert len(held) == 1, held
    entry = held[0]

    #: ① **후보와 연결된 판정이다** — 그 자리의 패를 실제로 물었다.
    hand = [c for c in duel.state.player(seat).hand if c]
    assert hand, "패가 비어 있으면 이 측정이 무의미하다"
    from engine.action_validation import ActionValidator

    verdict = ActionValidator(duel.view(seat)).validate(
        PlayerAction.activate_card(actor=seat, source=hand[0].instance_id)
    )
    assert entry.code is verdict.code
    assert entry.missing == verdict.missing_rule
    assert entry.validity is ActionValidity.UNKNOWN

    #: ② 🔴 **어느 카드인지는 적지 않는다** — 추측해 표시하지 않는다.
    for card in hand:
        assert str(card.card_id) not in entry.reason
    assert "instance" not in entry.reason

    #: ③ 패가 한 장뿐이면 ``scope`` 를 붙이지 않는다 (셀 것이 없다).
    assert (entry.scope is None) is (len(hand) <= 1)


@pytest.mark.real_card
def test_e03_the_output_separates_what_ran_from_what_did_not(repository):
    """
    🔴 **실제 실행과 정적 계획의 안내가 상충하지 않는다** (요구 ⑥).

    * 실제 입력 검사 결과는 **한 번** 적힌다.
    * 플래너가 별도 입력을 받지 않았다는 내부 사정이 **검사 결과로** 가지
      않는다.
    * 실행하지 않은 걸음에 "확정" · "엔진이 허가함" 이 붙지 않는다.
    """
    blob = _combo_blob(repository, USER_HAND, USER_RECIPE)

    #: ① 실제 실행 절과 정적 계획 절이 갈려 있다.
    assert "실제 엔진 실행" in blob
    assert "아래는 실행하지 않은 정적 계획입니다" in blob
    assert "엔진으로 돌린 것이 아닙니다" in blob

    #: ② 🔴 상충하는 검사 결과가 가지 않는다.
    assert "검증하지 않았습니다" not in blob
    assert "덱에서 나올 수 있는가" not in blob
    assert blob.count("이미 검사했습니다") == 1

    #: ③ 🔴 실행하지 않은 걸음에 실행 허가의 말이 붙지 않는다.
    assert "엔진이 이 행위를 허가함" not in blob
    assert "상태: 확정" not in blob
    #: 대신 정적 확인임을 적는다.
    assert "돌려볼 수 있음 (정적 확인)" in blob
    assert "엔진의 행위 계층이 판정할 수 있음 (정적 확인)" in blob

    #: ④ 지원 범위 내 실행을 전체 합법성 보장으로 적지 않는다.
    assert "최선의 전개가 아닙니다" in blob
    assert "사람이 확인해야" in blob


@pytest.mark.real_card
def test_e04_regenerating_the_report_does_not_move_the_board(repository):
    """🔴 **보고서를 다시 만들어도 결과가 같다** (요구 ④)."""
    first = _combo_blob(repository, USER_HAND, USER_RECIPE)
    second = _combo_blob(repository, USER_HAND, USER_RECIPE)
    assert first == second


@pytest.mark.real_card
def test_e05_the_rejected_input_still_reports_its_rule(repository):
    """패의 매수가 덱 보유 매수를 넘으면 거절한다 — 기존 동작 그대로."""
    blob = _combo_blob(
        repository, "69811710,69811710,69811710,69811710,93920420", USER_RECIPE
    )
    assert "패의 매수가 덱 보유 매수 이내인가" in blob
    assert "패 4장 > 덱 3장" in blob
    #: 🔴 거절한 입력에는 정적 계획을 보여 주지 않는다 (6-AA 의 성과).
    assert "아래는 실행하지 않은 정적 계획입니다" not in blob
