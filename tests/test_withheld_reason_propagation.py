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
from engine.action_target import ActionTarget
from engine.activation_timing import ActivationStage
from engine.cost.choice import CandidateSource, ChoiceSpec
from engine.duel import Duel, duel_components, target_combinations
from engine.effect.definition import EffectDefinitionRegistry
from engine.effect.library import EFFECT_LIBRARY
from engine.effect.target import TargetSpec
from engine.ids import EffectRef
from engine.target_bridge import selections_for, target_enumeration_limits
from engine.priority import PriorityState
from engine.state.game_state import GameState
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
    #:
    #: 🔴 **Phase 6-AC 에서 수가 늘었다** (5 → 6걸음 · 효과 해결 1 → 2).
    #: 성유물－『성장』 ② 가 등재되어 기르수 ① 의 해결이 묘지로 보낸 카드가
    #: **다음 유발을 연다** — 그 걸음이 하나 더 붙었고 그것도 효과 해결이다.
    #: 보존하는 대상은 "사용자가 확인한 결과" 이므로, 수를 그대로 두면 이
    #: 시험이 **사라진 출력을 찾는** 셈이 된다. 수를 고치고 **무엇이 늘었는지**
    #: 를 함께 센다 (아래 ② 의 묘지 · 몬스터 존이 그 걸음의 결과다).
    assert "엔진이 실제로 6걸음 실행" in blob
    assert "실행 6걸음 · 상태 변경 6걸음" in blob
    assert "효과가 실제로 해결된 걸음** 2걸음" in blob

    #: ② 판 — 🔴 **한 걸음이 늘어난 만큼 달라졌다.** 패에 있던 성유물－
    #: 『성장』 이 **특수 소환되어** 몬스터 존으로 갔다 (1장 → 2장, 패 1장
    #: → 0장). 묘지의 한 장은 덱에서 보내진 **다른** 사본이고 그대로다.
    assert "몬스터 존: 2장" in blob
    assert "잭나이츠 오르페골 기르수 [69811710]" in blob
    assert "마법·함정 존: 3장" in blob
    for card in ("703897", "2930675", "12989604"):
        assert card in blob
    assert "묘지: 1장 — 성유물－『성장』 [93920420]" in blob
    assert "남은 덱: 34장" in blob

    #: ③ 멈춘 자리 — 🔴 **흐름만 남았고, 그 자리의 보류는 0건이다**
    #: (Phase 6-AC). 세트를 모두 끝낸 뒤라 패에 발동 후보가 남지 않는다.
    #: 도중에 지나온 미지원은 **그대로 1건**이고 보고가 그것을 적는다 —
    #: 그 구분이 보완8 이 세운 것이다.
    assert "end_phase" in blob
    assert "activate_card [activation-timing" in blob


@pytest.mark.real_card
def test_e02_the_generic_activate_card_reason_names_its_scope(repository):
    """
    🔴 **포괄적인 ``activate_card`` 사유가 무엇인지 적는다.**

    실측: 멈춘 자리에서 그 보류는 **실제로 만든 후보**의 판정이다 — 그 자리의
    패를 전부 묻고 (보완8 이 첫 장에서 멈추지 않게 했다) 같은 코드로 묶은
    것이다. 다만 **어느 카드인지는 적지 않는다** (가려진 정보 보호), 그래서
    "특정 카드의 미지원" 으로 추측해 표시하지 않는다.

    이 시험은 그 둘을 함께 센다: 범위는 ``scope`` 가 말하고, 식별자는 없다.

    🔴 **Phase 6-AC 가 재는 자리를 옮기게 만들었다.** 6-AB 때 그 보류는
    전개가 **멈춘 자리**에 남아 있었다. 6-AC 가 지원을 늘려 전개가 한 걸음
    더 나아가고, 마지막 자리는 세트를 모두 끝낸 뒤라 패에 발동 후보가
    남지 않는다 — 그 자리의 보류가 **0건**이 되었다.

    그 보류 자체는 사라지지 않았다: 전개 **도중의** 자리에 그대로 있고
    ``run.unsupported`` 가 그것을 싣는다. 그래서 이 시험은 그 보류가 실제로
    있는 자리, 즉 **전개가 시작되기 전의 자리**에서 센다 — 재는 대상(사유의
    범위와 식별자 없음)은 한 글자도 약해지지 않았다.
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
    duel = setup.duel
    seat = duel.to_act

    #: 🔴 **전개를 돌리기 전에** 그 자리에서 센다 (위 설명).
    legal = duel.legal_actions(seat)
    held = [
        w for w in legal.withheld
        if w.kind is PlayerActionKind.ACTIVATE_CARD
    ]
    assert len(held) == 1, held
    entry = held[0]

    #: ① **후보와 연결된 판정이다** — 그 자리의 패를 실제로 물었다.
    #: 🔴 패는 **전개를 돌리기 전에** 읽는다 (아래에서 돌린다) — 전개가
    #: 끝난 뒤의 패는 비어 있고, 그 자리를 재는 것이 아니다.
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

    #: 🔴 그리고 **전개를 돌려도 그 보류는 보고에 남는다** (Phase 6-AC) —
    #: 멈춘 자리는 깨끗해졌지만 (``flow_only``) 지나온 미지원은 그대로다.
    #: 두 질문을 가른 것이 보완8 이고, 이 자리가 그 구분이 쓰이는 자리다.
    run = execute_opening(setup, repository)
    assert run.stopped_kind == "flow_only", run.stopped_kind
    assert any("activate_card" in line for line in run.unsupported), run.unsupported
    assert run.fully_supported is False


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

    #: ③-2 🔴 **비고 · 기대에 남아 있던 허가 표현도 사라졌다** (보완8 세
    #: 항목 ③). ``StepStatus`` · ``StepBasis`` 만 고쳤을 때 ``note`` 가
    #: *"엔진이 일반 소환을 허가합니다"* 를 그대로 들고 있었다 (실측).
    plan = blob[blob.index("아래는 실행하지 않은 정적 계획입니다"):]
    assert "허가합니다" not in plan
    assert "엔진이 일반 소환을 허가" not in plan
    #: 있는 것은 **종류의 판정 기능**이고, 이 판의 허가가 아니다.
    assert "**판정 계층이 있는 종류**입니다" in plan
    assert "이 판의 허가가 아닙니다" in plan
    #: 그리고 결과를 단정하지 않는다.
    assert "성공하면 앞면 공격 표시로" in plan
    assert "발동이 성공하면 엔진에 등록된 구현대로" in plan
    assert "이 판의 적법성이 아닙니다" in plan

    #: ③-3 🔴 **실행 기록 쪽의 수락 · 해결 표현은 그대로다** — 문구 하나의
    #: 부재가 아니라 **두 절의 뜻이 갈리는지**를 본다.
    executed = blob[blob.index("🔴 실제 엔진 실행"):blob.index(
        "아래는 실행하지 않은 정적 계획입니다")]
    assert "수락 예" in executed
    assert "적용된 효과 기록:" in executed
    assert "를 해결했습니다" in executed
    #: 그 말들은 정적 계획 절에 **없다** — 거기서는 아무것도 수락되지 않았다.
    assert "수락 예" not in plan
    assert "적용된 효과 기록" not in plan

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


# ======================================================================
# F. 같은 효과의 **혼합** 대상 조합 (보완8 세 항목 ②)
#
# 🔴 **왜 이 묶음을 더했는가.** 기존 ``test_b02``~``b04`` 는 *모두 INVALID* ·
# *모두 VALID* · *서로 다른 효과* 를 재었다. 그 셋으로는 **같은 효과 안에서
# 합법 · 거절 · 미확인 조합이 섞인 경우**를 말할 수 없고, 보고서 §8 · §13 이
# 그것을 충족했다고 적은 것은 과장이었다.
#
# 아래는 **실제 등재 카드 싸이크론**(``5318639:e[0]``)으로 그 혼합을 만든다.
# 그 효과의 대상 규칙은 "필드(양쪽)의 마법 · 함정 1장" 이므로 한 판에서
# 세 가지가 함께 나온다:
#
#     내 앞면 마법       → 조건 참      → **VALID** 조합이 된다
#     내 앞면 몬스터     → 조건 거짓    → **INVALID**: 후보가 되지 않는다
#     상대 뒷면 마법·함정 → 정체 모름    → **UNKNOWN**: 셀 수 없다
#
# 🔴 합성은 ``F03`` 하나뿐이고 (들여다보지 못한 자리까지 섞으려면 대상
# 규칙을 넓혀야 한다) 그 자리에 합성이라고 적는다.
# ======================================================================

CYCLONE = 5318639                  # 싸이크론 — 필드(양쪽)의 마법·함정 1장
CYCLONE_REF = EffectRef(CYCLONE, 0)
UNREADABLE = "target-candidate-identity"
UNSEEN_ZONE = "target-candidate-zone"


def _mixed_target_board(repository, *, facedown_opponent=True, definitions=None):
    """
    같은 효과에 **세 종류의 대상**이 함께 있는 판. 🔴 초기 판 구성이다.

    ``facedown_opponent=False`` 면 모름 쪽을 빼고 VALID · INVALID 만 둔다 —
    ``F01`` 과 ``F02`` 가 **같은 판에서 한 가지만 다르게** 비교하도록.
    """
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [LUSTER_DRAGON] * 30),
        turn_player=P0,
        seed=1,
    )
    cyclone = state.create_instance(CYCLONE, owner=P0, zone=Zone.HAND)
    #: ① 조건이 **참**인 대상 — 내 앞면 마법.
    legal_target = state.create_instance(POT_OF_GREED, owner=P0, zone=Zone.SZONE)
    state.move(legal_target, Zone.SZONE, to_player=P0, position=Position.FACEUP)
    #: ② 조건이 **거짓**인 대상 — 같은 규칙이 보는 자리의 몬스터.
    monster = state.create_instance(LUSTER_DRAGON, owner=P0, zone=Zone.MZONE)
    state.move(
        monster, Zone.MZONE, to_player=P0, position=Position.FACEUP_ATTACK
    )
    #: ③ 조건을 **판정할 수 없는** 대상 — 상대의 뒷면 마법·함정.
    hidden = None
    if facedown_opponent:
        hidden = state.create_instance(POT_OF_GREED, owner=P1, zone=Zone.SZONE)
        state.move(
            hidden, Zone.SZONE, to_player=P1, position=Position.FACEDOWN
        )
    state.turn.turn_number = 3
    state.turn.turn_player = P0
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(definitions=definitions)
        if definitions is not None
        else duel_components(),
    )
    return duel, cyclone.instance_id, legal_target.instance_id, monster.instance_id


def _cyclone_held(duel, seat=P0):
    """싸이크론 효과에 대한 보류만."""
    return [
        w
        for w in duel.legal_actions(seat).withheld
        if w.kind is PlayerActionKind.ACTIVATE_EFFECT
        and str(CYCLONE_REF) in w.reason
    ]


@pytest.mark.real_card
def test_f01_a_legal_and_an_illegal_combination_coexist(repository):
    """
    🔴 **사례 A — 같은 효과에 VALID 와 INVALID 가 함께 있다** (실제 카드).

    규칙이 거짓이라고 답한 대상은 **후보가 되지 않고 미지원으로도 집계되지
    않는다** — 그것은 규칙의 답이고 빠진 구현이 아니다. 그리고 합법인 조합은
    그대로 남아 실제로 ``apply`` 에서 수락된다.
    """
    duel, cyclone, legal_target, monster = _mixed_target_board(
        repository, facedown_opponent=False
    )
    definition = duel._activator.definitions.definition_for(CYCLONE_REF)

    #: ① 같은 규칙이 **두 자리를 다 본다** — 그래서 혼합이다.
    spec = definition.targets[0].spec
    assert Zone.SZONE in spec.choice.source.zones
    assert Zone.MZONE in spec.choice.source.zones

    #: ② 조합은 **하나**다 — 몬스터는 조건이 거짓이라 후보가 아니다.
    combos = target_combinations(duel.state, P0, definition, cyclone)
    assert len(combos) == 1, combos
    assert combos[0][0].instance_id == legal_target

    #: ③ 그 하나가 허가 목록에 있고, 몬스터를 가리킨 조합은 없다.
    offered = _activations(duel, P0, CYCLONE)
    assert len(offered) == 1, offered
    picked = offered[0]
    assert [t.instance_id for t in picked.targets] == [legal_target]
    assert all(
        monster not in [t.instance_id for t in a.targets] for a in offered
    )

    #: ④ 🔴 **거짓인 조합이 미지원으로 집계되지 않는다.**
    assert _cyclone_held(duel) == []
    assert all(
        str(CYCLONE_REF) not in w.line_ko()
        for w in duel.legal_actions(P0).unsupported()
    )

    #: ⑤ 그리고 그 조합이 **실제로 수락된다** — 후보 목록만 믿지 않는다.
    before = _fingerprint(duel)
    step = duel.apply(picked)
    assert step.accepted is True, step.reason
    assert _fingerprint(duel) != before


@pytest.mark.real_card
def test_f02_a_legal_and_an_unknown_combination_coexist(repository):
    """
    🔴 **사례 B — 같은 효과에 VALID 와 UNKNOWN 이 함께 있다** (실제 카드).

    실측 (이 보완 전)::

        eligible  = (내 앞면 마법,)        → 조합 1개 · 후보가 된다
        undecided = (상대 뒷면 마법·함정,)  → 🔴 **보류 0건** — 조용히 사라졌다

    즉 *"합법인 대상이 하나 있다"* 가 *"대상 공간을 끝까지 검증했다"* 로
    읽혔다. 지금은 둘을 함께 적는다.
    """
    duel, cyclone, legal_target, _monster = _mixed_target_board(repository)
    definition = duel._activator.definitions.definition_for(CYCLONE_REF)

    #: ① 모름 쪽이 실제로 생겼는지 **판정 계층에서** 확인한다.
    limits = target_enumeration_limits(duel.state, P0, definition, cyclone)
    assert limits is not None
    assert limits.eligible == 1 and limits.undecided == 1, limits
    assert limits.complete is False

    #: ② 🔴 **합법 조합은 그대로 후보다** — 모름 하나가 효과 전체를 막지
    #: 않는다 (사용자 요구 ②).
    offered = _activations(duel, P0, CYCLONE)
    assert len(offered) == 1, offered
    assert [t.instance_id for t in offered[0].targets] == [legal_target]

    #: ③ 🔴 **그런데 모름이 숨지 않는다** — 보류 한 줄이 그 범위를 적는다.
    held = _cyclone_held(duel)
    assert len(held) == 1, held
    entry = held[0]
    assert entry.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert entry.validity is ActionValidity.UNKNOWN
    assert entry.missing is not None and UNREADABLE in entry.missing
    #: 범위를 **수로** 적는다 — 패의 장수가 아니라 대상 후보의 수다.
    assert entry.scope == "대상 후보 2장 중 1장은 정체를 읽을 수 없음"
    assert "합법인 조합은 그대로 후보로 남아 있습니다" in entry.reason
    #: 그리고 미지원 집계에 들어간다 — 검증 한계이기 때문이다.
    assert entry in duel.legal_actions(P0).unsupported()

    #: ④ 🔴 **가려진 카드의 정체가 새지 않는다** (3-E-41).
    line = entry.line_ko()
    assert str(POT_OF_GREED) not in line
    assert "#" not in line
    for forbidden in ("source", "action", "instance_id"):
        assert not hasattr(entry, forbidden), forbidden

    #: ⑤ 효과 전체를 거절한 것으로 적지 않는다 — "모든 조합" 이라고 말하지
    #: 않고, 허가 목록이 비어 있지도 않다.
    assert "모든 조합" not in entry.reason
    assert offered

    #: ⑥ 그리고 그 합법 조합은 실제로 수락된다.
    step = duel.apply(offered[0])
    assert step.accepted is True, step.reason


@pytest.mark.real_card
def test_f03_two_different_unknown_reasons_on_one_effect(repository):
    """
    🔴 **사례 C — 같은 효과에 서로 다른 UNKNOWN 사유가 둘** (**합성**).

    🔴 **합성 조건이다.** 등재된 효과 가운데 발동 시점에 고르면서 *들여다보지
    못한 자리*까지 보는 대상 규칙은 없다. 그래서 싸이크론의 대상 규칙을
    ``{MZONE, HAND}`` · 양쪽으로 넓힌 **테스트 전용 정의**를 쓴다 — 실제
    싸이크론이 패를 보는 카드라는 뜻이 **아니다.** 기존 확장점
    (``CandidateSource``) 만 쓰고 새 판정은 만들지 않는다.

    그 판에서 한 효과가 네 가지를 함께 만난다::

        내 패의 마법            → 조건 참     → VALID 조합
        상대 필드의 뒷면 몬스터   → 정체 모름   → UNKNOWN ①
        상대 패                 → 자리를 못 봄 → UNKNOWN ②
    """
    base = next(
        e.definition
        for e in EFFECT_LIBRARY
        if e.definition.effect_ref == CYCLONE_REF
    )
    wide_spec = TargetSpec.targeting(
        ChoiceSpec(
            source=CandidateSource(
                zones=frozenset({Zone.MZONE, Zone.HAND}),
                owner=None,
                require=base.targets[0].spec.choice.source.require,
            ),
            minimum=1,
            maximum=1,
        )
    )
    wide = dataclasses.replace(
        base,
        targets=(dataclasses.replace(base.targets[0], spec=wide_spec),),
    )
    kept = tuple(
        e.definition
        for e in EFFECT_LIBRARY
        if e.definition.effect_ref != CYCLONE_REF
    )
    registry = EffectDefinitionRegistry(kept + (wide,))

    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [LUSTER_DRAGON] * 30),
        turn_player=P0,
        seed=1,
    )
    cyclone = state.create_instance(CYCLONE, owner=P0, zone=Zone.HAND)
    in_hand = state.create_instance(POT_OF_GREED, owner=P0, zone=Zone.HAND)
    facedown = state.create_instance(LUSTER_DRAGON, owner=P1, zone=Zone.MZONE)
    state.move(
        facedown, Zone.MZONE, to_player=P1, position=Position.FACEDOWN_DEFENSE
    )
    for _ in range(2):
        state.create_instance(LUSTER_DRAGON, owner=P1, zone=Zone.HAND)
    state.turn.turn_number = 3
    state.turn.turn_player = P0
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(definitions=registry),
    )

    limits = target_enumeration_limits(duel.state, P0, wide, cyclone.instance_id)
    assert limits is not None
    assert limits.undecided >= 1 and limits.unchecked, limits

    #: ① 합법 조합은 남는다 — 모름 **둘**이 있어도 막지 않는다.
    offered = _activations(duel, P0, CYCLONE)
    assert offered, duel.legal_actions(P0).withheld
    assert in_hand.instance_id in {
        t.instance_id for a in offered for t in a.targets
    }

    #: ② 🔴 **사유가 둘이고 서로 다르다** — 하나로 뭉개지 않는다.
    held = _cyclone_held(duel)
    missing = {w.missing for w in held}
    assert len(held) == 2, held
    assert any(m and UNREADABLE in m for m in missing), missing
    assert any(m and UNSEEN_ZONE in m for m in missing), missing
    assert len({w.scope for w in held}) == 2, held

    #: ③ 둘 다 모름이고 둘 다 미지원 집계에 들어간다.
    for entry in held:
        assert entry.validity is ActionValidity.UNKNOWN
        assert entry in duel.legal_actions(P0).unsupported()
    #: ④ 그리고 어느 줄에도 카드 식별자가 없다.
    for entry in held:
        assert "#" not in entry.line_ko()
        assert str(LUSTER_DRAGON) not in entry.line_ko()


@pytest.mark.real_card
def test_f04_the_direct_apply_does_not_borrow_another_combinations_reason(
    repository,
):
    """
    🔴 **직접 ``apply`` 가 다른 조합의 사유를 빌려오지 않는다** (요구 ②).

    같은 효과에 보류 한 줄(모름)과 허가 한 줄(합법)이 함께 있는 판에서,
    **거절될 조합**을 직접 넣으면 그 조합 자신의 판정이 와야 한다 — 보류에
    적힌 "정체를 읽을 수 없다" 가 와서는 안 된다.
    """
    duel, cyclone, legal_target, monster = _mixed_target_board(repository)
    held = _cyclone_held(duel)
    assert len(held) == 1 and held[0].missing

    #: 조건이 **거짓**인 대상(몬스터)을 직접 가리킨다 — 후보가 아니다.
    intruder = PlayerAction.activate_effect(
        actor=P0,
        source=cyclone,
        effect_ref=CYCLONE_REF,
        targets=(ActionTarget.instance(monster),),
    )
    assert intruder not in duel.legal_actions(P0).allowed

    before = _fingerprint(duel)
    step = duel.apply(intruder)
    assert step.accepted is False
    #: 🔴 **그 조합 자신의 까닭**이다 — 보류의 모름이 아니다.
    assert step.code is not ValidationCode.INFORMATION_UNAVAILABLE
    assert held[0].missing not in (step.reason or "")
    assert "정체를 읽을 수 없는" not in step.reason
    #: 그리고 판은 그대로다.
    assert _fingerprint(duel) == before


@pytest.mark.real_card
def test_f05_the_mixed_board_reads_the_same_in_a_fork(repository):
    """
    🔴 **원본과 사본이 같은 후보 · 같은 사유를 본다** (요구 ②).

    그리고 조회와 거절은 판을 바꾸지 않는다 — 혼합 판에서도 같다.
    """
    duel, cyclone, legal_target, monster = _mixed_target_board(repository)
    before = _fingerprint(duel)

    def seen(d):
        legal = d.legal_actions(P0)
        return (
            tuple(
                (str(a.effect_ref), tuple(t.instance_id for t in a.targets))
                for a in legal.allowed
                if a.kind is PlayerActionKind.ACTIVATE_EFFECT
            ),
            tuple(
                (w.kind, w.code, w.missing, w.scope, w.reason)
                for w in legal.withheld
            ),
        )

    mine = seen(duel)
    fork = Simulator(duel=duel)._fork()
    assert seen(fork) == mine

    #: 조회를 몇 번 해도, 거절을 받아도 판이 그대로다.
    for _ in range(3):
        duel.legal_actions(P0)
    duel.apply(
        PlayerAction.activate_effect(
            actor=P0,
            source=cyclone,
            effect_ref=CYCLONE_REF,
            targets=(ActionTarget.instance(monster),),
        )
    )
    assert _fingerprint(duel) == before


# ======================================================================
# G. ``/combo`` 의 **종료 원인**과 **전체 지원 상태** (보완8 세 항목 ①)
#
# 🔴 **왜 이 묶음을 더했는가.** ``execute_opening`` 은 중간 사유를
# ``run.unsupported`` 에 **모으고 있었다.** 그런데 종료 판정은 **마지막
# 자리**의 ``missing_here`` 만 보았다. 그래서 중간에 중요한 미지원을
# 지나왔어도 마지막 자리가 깨끗하면 ``stopped_kind="flow_only"`` 가 되고,
# 멈춘 설명이 그 한계를 한 글자도 말하지 않았다. 실측 (이 보완 전)::
#
#     normal_summon 1걸음 · 중간 P1 기회에서 trap-activation-event 미지원
#     → run.unsupported 에는 남는다
#     → 마지막 P0 패는 비어 있어 그 자리의 미지원은 없다
#     → stopped_kind = "flow_only"
#     → ExecutedStep.unsupported = ()  🔴 걸음에도 안 남는다
#     → 종료 설명도 마지막 후보만 언급
#
# 고친 방식: **두 질문을 가른다.** ``stopped_kind`` 는 *"왜 멈췄는가"*,
# ``OpeningRun.fully_supported`` 는 *"끝까지 검증했는가"* 다. 그리고 걸음에
# ``unsupported_during`` 을 더해 **시점**을 구분했다.
# ======================================================================


def _single_summon_hand(duel, seat=P0):
    """
    그 자리의 패를 **일반 소환 가능한 몬스터 한 장**만 남긴다 (나머지는 덱으로).

    🔴 초기 판 구성이다 — 이 뒤의 변화는 전부 ``Duel.apply`` 가 만든다.
    마지막 자리의 패를 비워 *"마지막 상태는 깨끗한데 중간에 미지원을
    지나왔다"* 를 만들려는 것이다.
    """
    for card in list(duel.state.player(seat).hand)[1:]:
        duel.state.move(card, Zone.DECK, to_player=seat)
    return duel


def _run_opening(duel, repository, **kwargs):
    from deck.opening import OpeningSetup, execute_opening

    setup = OpeningSetup(duel=duel, journal=duel.journal)
    return execute_opening(setup, repository, **kwargs)


@pytest.mark.real_card
def test_g01_a_mid_flight_limit_survives_a_clean_final_position(repository):
    """
    🔴 **사례 A — 중간에 중요 UNKNOWN, 마지막 자리는 깨끗하다.**

    🔴 **합성 조건**이다 (``_waiting_gift_registry``). 실제 욕망의 선물이
    사건을 기다리는 카드라는 뜻이 **아니다.**
    """
    duel, _gift = _board_with_facedown_gift(
        repository, definitions=_waiting_gift_registry()
    )
    _single_summon_hand(duel)
    run = _run_opening(duel, repository)

    #: ① 한 걸음 실행하고, 마지막 자리의 패는 비었다.
    assert run.executed == 1
    assert [s.kind for s in run.steps] == ["normal_summon"]
    assert len(duel.state.player(P0).hand) == 0

    #: ② 멈춘 **원인**은 그대로 "흐름뿐" 이다 — 과거 사유로 덮지 않는다.
    assert run.stopped_kind == "flow_only"

    #: ③ 🔴 **그런데 끝까지 검증한 것이 아니다** — 두 질문이 갈렸다.
    assert run.fully_supported is False
    assert any("trap-activation-event" in line for line in run.unsupported)

    #: ④ 🔴 멈춘 설명이 그 한계를 말한다. 그리고 **시점을 분명히 적는다** —
    #: 이 자리의 것이 아니라 앞선 자리의 것이다.
    assert "앞선 자리" in run.stopped_reason
    assert "전개 전체를 지원 범위 안에서 검증한 것은 아닙니다" in run.stopped_reason

    #: ⑤ 🔴 걸음의 두 목록이 **시점으로** 갈린다.
    step = run.steps[0]
    assert step.unsupported == ()
    assert any(
        "trap-activation-event" in line for line in step.unsupported_during
    )

    #: ⑥ 그리고 상대 기회의 사유에는 카드 식별자가 없다 (관측 경계 유지).
    blob = "\n".join(run.unsupported)
    assert str(GIFT_OF_GREED) not in blob
    assert str(GIFT_REF) not in blob
    assert "관측 밖입니다" in blob


@pytest.mark.real_card
def test_g02_a_rule_refusal_alone_is_still_fully_supported(repository):
    """
    🔴 **사례 B — 규칙상 INVALID 만 있다.**

    세트한 턴의 함정은 룰북이 막는다 (``SET_THIS_TURN``). 그것은 규칙의
    답이므로 **미지원이 아니고**, 전체 지원 상태는 참이다 — INVALID 를
    미지원으로 승격하지 않는다.
    """
    from engine.state.rule_usage import RuleActionKind

    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [LUSTER_DRAGON] * 30),
        turn_player=P0,
        seed=1,
    )
    trap = state.create_instance(GIFT_OF_GREED, owner=P0, zone=Zone.SZONE)
    state.move(trap, Zone.SZONE, to_player=P0, position=Position.FACEDOWN)
    #: 🔴 "이 턴에 세웠다" 는 기록을 **초기 판 구성으로** 적는다 — 이 사실은
    #: 관측에 없고 ``rule_uses`` 에만 있다 (``Duel._set_this_turn``).
    state.turn.turn_number = 3
    state.turn.turn_player = P0
    state.turn.set_phase(Phase.MAIN1)
    state.rule_uses.record_card(
        state.turn.turn_number, P0, trap.instance_id,
        RuleActionKind.SET_SPELL_TRAP,
    )
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(),
    )
    assert len(duel.state.player(P0).hand) == 0

    legal = duel.legal_actions(P0)
    held = _held(duel)
    #: ① 보류가 있고 **전부 확정 거부**다.
    assert held, legal.withheld
    assert all(w.is_rule_refusal for w in legal.withheld), legal.withheld
    assert any(w.code is ValidationCode.SET_THIS_TURN for w in held), held
    assert legal.unsupported() == ()

    run = _run_opening(duel, repository)
    #: ② 멈춘 원인은 흐름뿐이고, **끝까지 검증했다.**
    assert run.stopped_kind == "flow_only"
    assert run.unsupported == []
    assert run.fully_supported is True
    #: ③ 그리고 멈춘 설명에 과거 사유가 끼어들지 않는다.
    assert "앞선 자리" not in run.stopped_reason


@pytest.mark.real_card
def test_g03_a_clean_flow_end_says_so(repository):
    """
    🔴 **사례 C — 미지원이 하나도 없는 정상 흐름 종료.**

    패도 비었고 판 위에 등재 효과도 없다. 그러면 ``flow_only`` 와 "끝까지
    검증했다" 가 **함께** 참이고, 그것이 이 낱말을 믿을 수 있는 경우다.
    """
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [LUSTER_DRAGON] * 30),
        turn_player=P0,
        seed=1,
    )
    monster = state.create_instance(LUSTER_DRAGON, owner=P0, zone=Zone.MZONE)
    state.move(
        monster, Zone.MZONE, to_player=P0, position=Position.FACEUP_ATTACK
    )
    state.turn.turn_number = 3
    state.turn.turn_player = P0
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(),
    )
    assert len(duel.state.player(P0).hand) == 0

    run = _run_opening(duel, repository)
    assert run.stopped_kind == "flow_only"
    assert run.fully_supported is True
    assert run.unsupported == []
    assert all(s.unsupported == () for s in run.steps)
    assert all(s.unsupported_during == () for s in run.steps)


@pytest.mark.real_card
def test_g04_a_real_stop_cause_is_not_covered_by_the_cumulative_list(
    repository,
):
    """
    🔴 **사례 D — 중요 미지원과 상한 도달이 함께 있다.**

    그때 ``stopped_kind`` 는 **상한**이라고 말해야 한다 — 누적 미지원이
    실제 종료 원인을 덮지 않는다. 그리고 전체 지원 상태는 따로 거짓이다.
    """
    duel, _gift = _board_with_facedown_gift(
        repository, definitions=_waiting_gift_registry()
    )
    _single_summon_hand(duel)
    run = _run_opening(duel, repository, max_actions=1)

    #: ① 실제 종료 원인이 그대로 남는다.
    assert run.stopped_kind == "limit"
    assert "상한" in run.stopped_reason
    #: ② 그리고 그 설명에 과거 미지원이 끼어들지 않는다 (덮지도, 덮이지도).
    assert "앞선 자리" not in run.stopped_reason
    #: ③ 그런데 전체 지원 상태는 거짓이다 — 두 사실이 함께 남는다.
    assert run.fully_supported is False
    assert any("trap-activation-event" in line for line in run.unsupported)


@pytest.mark.real_card
def test_g05_the_combo_answer_separates_the_two_questions(repository):
    """
    🔴 **사용자에게 가는 문장이 둘을 가른다** — 렌더링까지 확인한다.

    ``flow_only`` 하나만 보고 "정상 검증 완료" 로 읽지 않게 하는 것이
    이 보완의 목적이다 (요구 ①).
    """
    from deck.report import render_opening_run

    duel, _gift = _board_with_facedown_gift(
        repository, definitions=_waiting_gift_registry()
    )
    _single_summon_hand(duel)
    run = _run_opening(duel, repository)
    text = render_opening_run(run)

    #: ① 전체 지원 상태가 **한 줄로** 나온다.
    assert "전체 지원 상태: 🔴 **끝까지 검증하지 못했습니다**" in text
    #: ② 걸음의 두 시점이 서로 다른 말로 나온다.
    #:
    #: 🔴 **도중 사유의 문장은 여기 적지 않는다** — 수와 자리만 적고 누적
    #: 목록으로 연결한다. 걸음마다 문장을 다시 적으면 긴 전개에서 메시지
    #: 상한에 걸려 정적 계획 절이 잘렸다 (실측).
    assert "🔴 **도중에** 만난 미지원 2건 (지나온 자리 · 아래 `미지원 사유`)" in text
    #: ③ 누적 목록이 그 문장을 들고 있다 — 연결이 끊기지 않는다.
    assert "이 전개 중에 만난 **미지원 사유**" in text
    assert any(
        "trap-activation-event" in line for line in text.splitlines()
    )

    #: ④ 🔴 깨끗한 전개에서는 그 반대가 나온다 — 같은 함수로 확인한다.
    clean = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [LUSTER_DRAGON] * 30),
        turn_player=P0,
        seed=1,
    )
    monster = clean.create_instance(LUSTER_DRAGON, owner=P0, zone=Zone.MZONE)
    clean.move(
        monster, Zone.MZONE, to_player=P0, position=Position.FACEUP_ATTACK
    )
    clean.turn.turn_number = 3
    clean.turn.turn_player = P0
    clean.turn.set_phase(Phase.MAIN1)
    quiet = _run_opening(
        Duel(
            state=clean,
            priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
            **duel_components(),
        ),
        repository,
    )
    quiet_text = render_opening_run(quiet)
    assert "전체 지원 상태: ✅" in quiet_text
    assert "끝까지 검증하지 못했습니다" not in quiet_text


# ======================================================================
# H. **발동 자체가 금지된 효과**의 대상 정보 부족 (보완8 마무리2)
#
# 🔴 **고친 결함.** 보완8 세 항목 ②는 *"못 센 대상 범위"* 를 조합 판정보다
# **앞에서** 적었다. 그래서 **발동이 규칙상 금지된** 효과까지 상대의 뒷면
# 카드 하나 때문에 "진행에 영향을 주는 미지원" 으로 집계되었다. 실측
# (실제 등재 카드 싸이크론 · **세트한 턴**)::
#
#     상대 뒷면 카드 없음 → flow_only  · fully_supported=True  · unsupported=[]
#     상대 뒷면 카드 있음 → unsupported · fully_supported=False ·
#                          target-candidate-identity 가 남는다
#
# 두 판 모두 그 효과는 세트한 턴이라 **발동할 수 없다.** 상대의 뒷면 카드가
# 있다는 이유만으로 이번 진행을 미지원으로 분류해서는 안 된다.
#
# 🔴 **고친 방식.** 같은 관문의 **대상 의존이 아닌 단계들**만 지나는
# ``Duel._target_free_verdict`` 를 두고, 그것이 **확정 거절**을 내면 대상 범위
# 보고를 멈춘다. 규칙을 복제하지도, 카드 전용 분기를 만들지도 않는다.
# ``UNKNOWN`` 은 멈추지 않는다 — 발동 가능성이 남아 있기 때문이다.
# ======================================================================

RUTHLESS_REF = EffectRef(RUTHLESS, 0)


def _set_and_reopen(duel, instance, seat=P0):
    """
    그 카드를 **실제 행위로** 세우고 빠른 효과 기회를 지나 판을 다시 연다.

    🔴 손으로 우선권을 돌리지 않는다 — 세트도 기회 통과도 ``Duel.apply`` 다.
    그래서 "세트한 턴" 이라는 사실이 ``rule_uses`` 에 **실행으로** 남는다.
    """
    step = duel.apply(PlayerAction.set_spell_trap(actor=seat, source=instance))
    assert step.accepted, step.reason
    pass_fast_window(duel)
    assert duel._activation_stage() is ActivationStage.OPEN
    return step


@pytest.mark.real_card
def test_h01_a_forbidden_activation_does_not_promote_its_target_gap(repository):
    """
    🔴 **사례 A — 세트한 턴의 싸이크론 + 상대 뒷면 대상** (실제 카드).

    발동 후보는 없고, 실제 거절 이유(``SET_THIS_TURN``)는 **그대로** 남고,
    대상 정보 부족은 **이번 진행의 미지원으로 집계되지 않는다.**
    """
    duel, cyclone, legal_target, _monster = _mixed_target_board(repository)
    _set_and_reopen(duel, cyclone)

    #: ① 대상 공간은 여전히 불완전하다 — 판정 계층이 그렇게 말한다.
    definition = duel._activator.definitions.definition_for(CYCLONE_REF)
    limits = target_enumeration_limits(duel.state, P0, definition, cyclone)
    assert limits is not None and limits.undecided == 1, limits

    #: ② 🔴 그런데 **발동 자체가 금지되었다** — 대상과 무관한 확정 거절이다.
    independent = duel._target_free_verdict(
        P0, CYCLONE_REF, cyclone, validator=duel.activation_validator(P0)
    )
    assert independent is not None
    assert independent.validity is ActionValidity.INVALID
    assert independent.code is ValidationCode.SET_THIS_TURN

    #: ③ 후보가 없다.
    assert _activations(duel, P0, CYCLONE) == []

    #: ④ 🔴 실제 거절 이유가 **기존 코드로** 보존된다.
    held = _cyclone_held(duel)
    assert len(held) == 1, held
    assert held[0].code is ValidationCode.SET_THIS_TURN
    assert held[0].is_rule_refusal
    assert held[0].missing is None
    assert "세트한 턴에는 발동할 수 없습니다" in held[0].reason

    #: ⑤ 🔴 **대상 정보 부족이 미지원으로 집계되지 않는다.**
    legal = duel.legal_actions(P0)
    assert all(
        w.code is not ValidationCode.INFORMATION_UNAVAILABLE
        for w in legal.withheld
    ), legal.withheld
    assert all(
        str(CYCLONE_REF) not in w.line_ko() for w in legal.unsupported()
    ), legal.unsupported()

    #: ⑥ 그리고 거짓 문구가 없다 — 후보가 없으므로 그 말을 할 수 없다.
    assert all(
        "합법인 조합은 그대로 후보로 남아" not in w.reason
        for w in legal.withheld
    )


@pytest.mark.real_card
@pytest.mark.parametrize("facedown", [False, True])
def test_h02_the_hidden_card_alone_does_not_change_the_support_state(
    repository, facedown
):
    """
    🔴 **사례 B — 상대 뒷면 카드 유무 대조** (요구 1-B 의 재현 그대로).

    발동 전체가 금지된 상태에서는 **그 차이만으로** ``/combo`` 의 전체 지원
    상태가 달라지지 않는다. 수정 전 실측::

        facedown=False → flow_only   · fully_supported=True  · unsupported=[]
        facedown=True  → unsupported · fully_supported=False · 사유 1건

    🔴 **초기 판 구성과 실제 실행을 가른다.** 앞면 욕망의 항아리를 묘지로
    옮기는 것은 **초기 판 구성**이다 (그 카드의 별도 발동 미지원 사유가
    섞이지 않게 한다). 세트와 기회 통과는 **실제 행위**다.
    """
    duel, cyclone, legal_target, _monster = _mixed_target_board(
        repository, facedown_opponent=facedown
    )
    duel.state.move(legal_target, Zone.GRAVE, to_player=P0)   # 초기 판 구성
    _set_and_reopen(duel, cyclone)                            # 실제 행위

    run = _run_opening(duel, repository)

    #: 🔴 뒷면 카드가 있든 없든 **같다.**
    assert run.stopped_kind == "flow_only", run.stopped_reason
    assert run.fully_supported is True
    assert run.unsupported == []
    #: 그리고 멈춘 설명이 과거 사유를 끌어오지 않는다.
    assert "앞선 자리" not in run.stopped_reason


@pytest.mark.real_card
def test_h03_an_activatable_effect_still_reports_its_unknown_targets(
    repository,
):
    """
    🔴 **사례 C — 발동 가능한 싸이크론 + 합법 대상 + 미확인 대상.**

    보완8 세 항목 ②의 성과를 **되돌리지 않았다**는 것을 같은 판에서 센다
    (``test_f02`` 와 같은 사실을 이 묶음의 대조로 다시 본다).
    """
    duel, cyclone, legal_target, _monster = _mixed_target_board(repository)

    #: ① 발동이 금지되지 않았다 — 세우지 않았으므로 패에서 쓸 수 있다.
    independent = duel._target_free_verdict(
        P0, CYCLONE_REF, cyclone, validator=duel.activation_validator(P0)
    )
    assert independent is None, independent

    #: ② 합법 조합은 후보이고 **실제로 수락된다.**
    offered = _activations(duel, P0, CYCLONE)
    assert len(offered) == 1, offered
    assert [t.instance_id for t in offered[0].targets] == [legal_target]

    #: ③ 🔴 미확인 대상 범위가 **남는다.**
    held = _cyclone_held(duel)
    assert len(held) == 1, held
    assert held[0].code is ValidationCode.INFORMATION_UNAVAILABLE
    assert held[0].missing and UNREADABLE in held[0].missing
    assert held[0] in duel.legal_actions(P0).unsupported()
    #: ④ 그리고 이번에는 **허가된 조합이 있으므로** 그 사실을 말한다.
    assert "합법인 조합은 그대로 후보로 남아 있습니다" in held[0].reason

    assert duel.apply(offered[0]).accepted is True


@pytest.mark.real_card
def test_h04_unknown_targets_survive_with_no_legal_combination(repository):
    """
    🔴 **사례 D — 발동은 금지되지 않았고 미확인 대상만 있다.**

    VALID 조합이 하나도 없어도 **미확인 범위는 남는다** — "허가 후보가 0개면
    모든 UNKNOWN 삭제" 는 이 수정이 금지한 방법이다. 그리고 보류 문장이
    *"합법인 조합이 남아 있다"* 고 **단정하지 않는다.**
    """
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [LUSTER_DRAGON] * 30),
        turn_player=P0,
        seed=1,
    )
    cyclone = state.create_instance(CYCLONE, owner=P0, zone=Zone.HAND)
    hidden = state.create_instance(POT_OF_GREED, owner=P1, zone=Zone.SZONE)
    state.move(hidden, Zone.SZONE, to_player=P1, position=Position.FACEDOWN)
    state.turn.turn_number = 3
    state.turn.turn_player = P0
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(),
    )

    #: ① 발동 자체는 막히지 않았다.
    assert duel._target_free_verdict(
        P0, CYCLONE_REF, cyclone.instance_id,
        validator=duel.activation_validator(P0),
    ) is None

    #: ② 합법 조합이 **하나도 없다** — 유일한 후보가 가려져 있다.
    definition = duel._activator.definitions.definition_for(CYCLONE_REF)
    assert target_combinations(duel.state, P0, definition, cyclone.instance_id) == []
    assert _activations(duel, P0, CYCLONE) == []

    #: ③ 🔴 그래도 **모름이 남는다.**
    held = _cyclone_held(duel)
    assert len(held) == 1, held
    entry = held[0]
    assert entry.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert entry.validity is ActionValidity.UNKNOWN
    assert entry.missing and UNREADABLE in entry.missing
    assert entry.scope == "대상 후보 1장 중 1장은 정체를 읽을 수 없음"
    assert entry in duel.legal_actions(P0).unsupported()

    #: ④ 🔴 **거짓 문구가 없다** — 대신 무엇을 판정하지 못했는지 적는다.
    assert "합법인 조합은 그대로 후보로 남아" not in entry.reason
    assert "지금 허가된 조합은 없고" in entry.reason
    assert "합법인 조합이 있는지도 말할 수 없습니다" in entry.reason
    #: 🔴 "합법인 조합이 없다" 고도 **단정하지 않는다** — 모르기 때문이다.
    assert "합법인 조합이 없습니다" not in entry.reason
    #: ⑤ 그리고 가려진 카드의 정체는 새지 않는다.
    assert str(POT_OF_GREED) not in entry.line_ko()
    assert "#" not in entry.line_ko()


@pytest.mark.real_card
def test_h05_one_illegal_combination_does_not_condemn_the_effect(repository):
    """
    🔴 **사례 E — 같은 효과의 일부 대상만 INVALID.**

    조건이 거짓인 대상 하나 때문에 다른 VALID · UNKNOWN 대안을 **효과 전체의
    거절로 처리하지 않는다.** 그 혼동이 *"첫 번째 조합의 INVALID 를 효과
    전체의 INVALID 로 간주"* 이고, 이 수정이 금지한 방법이다.
    """
    duel, cyclone, legal_target, monster = _mixed_target_board(repository)

    #: ① 대상과 무관한 확정 거절은 **없다** — 조합 하나가 거짓인 것과 다르다.
    assert duel._target_free_verdict(
        P0, CYCLONE_REF, cyclone, validator=duel.activation_validator(P0)
    ) is None

    #: ② VALID 조합은 후보로 남는다.
    offered = _activations(duel, P0, CYCLONE)
    assert [t.instance_id for a in offered for t in a.targets] == [legal_target]

    #: ③ UNKNOWN 범위도 남는다.
    held = _cyclone_held(duel)
    assert [w.code for w in held] == [ValidationCode.INFORMATION_UNAVAILABLE]

    #: ④ 🔴 그리고 조건이 거짓인 조합은 **미지원이 아니다** (규칙의 답이다).
    unsupported = duel.legal_actions(P0).unsupported()
    assert all(w.code is not ValidationCode.CANDIDATE_NOT_ELIGIBLE
               for w in unsupported)


@pytest.mark.real_card
def test_h06_a_target_independent_refusal_from_the_condition_stage(repository):
    """
    🔴 **다른 단계의 대상 독립 거절도 같은 자리가 본다.**

    ``SET_THIS_TURN`` 은 **타이밍 관문**(둘째 단계)의 답이다. 이 시험은
    **발동 조건**(셋째 단계)의 답도 같은 자리에서 나오는지 센다 — 무정한
    말살은 *"자신 MZONE 에 1장 이상 **그리고** 상대 HAND 에 1장 이상"* 을
    요구하고, 상대 패가 비면 그 조건이 **거짓**이다 (대상과 무관하다).

    🔴 그래서 이 수정은 한 코드에 묶인 것이 아니다 — 같은 관문의 **단계
    전부**를 쓴다.
    """
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [LUSTER_DRAGON] * 30),
        turn_player=P0,
        seed=1,
    )
    spell = state.create_instance(RUTHLESS, owner=P0, zone=Zone.HAND)
    mine = state.create_instance(LUSTER_DRAGON, owner=P0, zone=Zone.MZONE)
    state.move(
        mine, Zone.MZONE, to_player=P0, position=Position.FACEUP_ATTACK
    )
    state.turn.turn_number = 3
    state.turn.turn_player = P0
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(),
    )
    assert len(duel.state.player(P1).hand) == 0

    independent = duel._target_free_verdict(
        P0, RUTHLESS_REF, spell.instance_id,
        validator=duel.activation_validator(P0),
    )
    assert independent is not None
    assert independent.validity is ActionValidity.INVALID
    assert independent.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE

    #: 🔴 **조합별 관문도 같은 코드를 낸다** — 두 자리가 갈라지지 않는다.
    definition = duel._activator.definitions.definition_for(RUTHLESS_REF)
    validator = duel.activation_validator(P0)
    combos = target_combinations(duel.state, P0, definition, spell.instance_id)
    assert combos, "조합이 없으면 이 비교가 성립하지 않는다"
    for targets in combos:
        candidate = PlayerAction.activate_effect(
            actor=P0, source=spell.instance_id,
            effect_ref=RUTHLESS_REF, targets=targets,
        )
        gate = duel._activation_gate(
            candidate,
            validator=validator,
            selections=selections_for(definition, candidate),
        )
        assert gate.code is independent.code, (gate.code, independent.code)

    #: 그리고 보류는 **한 줄**이다 — 두 자리가 같은 열쇠를 쓴다.
    held = [
        w
        for w in duel.legal_actions(P0).withheld
        if w.kind is PlayerActionKind.ACTIVATE_EFFECT
        and str(RUTHLESS_REF) in w.reason
    ]
    assert len(held) == 1, held
    assert held[0].code is ValidationCode.CANDIDATE_NOT_ELIGIBLE


@pytest.mark.real_card
def test_h07_the_direct_apply_agrees_and_reading_changes_nothing(repository):
    """
    🔴 **사례 F — 직접 ``apply`` · 원본과 사본 · 조회 순수성.**
    """
    duel, cyclone, legal_target, monster = _mixed_target_board(repository)
    _set_and_reopen(duel, cyclone)
    before = _fingerprint(duel)

    #: ① 직접 넣어도 **같은 코드**다 — 보류와 근거가 일치한다.
    held = _cyclone_held(duel)
    assert [w.code for w in held] == [ValidationCode.SET_THIS_TURN]
    action = PlayerAction.activate_effect(
        actor=P0,
        source=cyclone,
        effect_ref=CYCLONE_REF,
        targets=(ActionTarget.instance(legal_target),),
    )
    step = duel.apply(action)
    assert step.accepted is False
    assert step.code is ValidationCode.SET_THIS_TURN
    #: 🔴 확정 거부이므로 빠진 규칙의 이름이 붙지 않는다.
    assert "[" not in step.reason

    #: ② 조회와 거절이 판 · 우선권 · 사건 · 소비 이력을 바꾸지 않았다.
    for _ in range(3):
        duel.legal_actions(P0)
    assert _fingerprint(duel) == before

    #: ③ 사본의 후보와 사유가 원본과 같다.
    def seen(d):
        legal = d.legal_actions(P0)
        return (
            tuple(
                (str(a.effect_ref), tuple(t.instance_id for t in a.targets))
                for a in legal.allowed
                if a.kind is PlayerActionKind.ACTIVATE_EFFECT
            ),
            tuple(
                (w.kind, w.code, w.missing, w.scope, w.reason)
                for w in legal.withheld
            ),
        )

    assert seen(Simulator(duel=duel)._fork()) == seen(duel)
    assert _fingerprint(duel) == before
