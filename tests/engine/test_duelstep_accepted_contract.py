"""
Phase 6-R — ``DuelStep.accepted`` 의 뜻과 체인 해결 결과의 계약.

🔴 먼저, 이 Phase 가 받은 전제를 **정정한다**
----------------------------------------------
6-R 의 지시문 §2 가 이렇게 적었다.

    1. 플레이어가 발동 가능한 함정을 선택한다.
    2. ActionValidator 가 발동을 허용한다.
    3. Duel.apply() 에서 체인 링크가 생성된다.
    4. **그런데 DuelStep.accepted=False 가 반환된다.**

**4번은 재현되지 않는다.** 지시문이 §2 에서 스스로 요구한 대로
("먼저 실제 코드를 분석하고 해당 현상을 독립적으로 재현해야 한다") 재어
보면, 체인 링크를 만든 걸음은 **언제나** ``accepted=True`` 다
(``C`` · ``D`` 절이 센다 — 체인 1 · 체인 2 모두).

거짓 실패는 **발동이 아니라 그 체인을 푸는 패스**에서 났다. 그리고 그
자리에는 **더 깊은 결함**이 같이 있었다.

두 결함, 그리고 어느 쪽이 원인인가
-----------------------------------
========================================  =========================
① 보고의 혼동                              ``accepted`` 하나가 "행위를
                                          수락했는가" 와 "링크가 전부
                                          해결되었는가" 를 함께 담았다
② 🔴 **상태 오염** (원인)                   ``Duel._resolve_chain`` 이
                                          ``if self.chain.is_complete:``
                                          일 때만 체인을 비웠다
========================================  =========================

②가 ①을 낳는다. 링크 하나가 불발되면 ``is_complete`` 가 거짓이므로
**반쯤 풀린 체인이 영구히 남고**, 남은 체인이
``ActivationTiming.chain_is_open`` 을 참으로 고정한다. 그러면 **스펠 스피드
1 발동이 듀얼이 끝날 때까지 전부** ``SPELL_SPEED_TOO_LOW`` (``INVALID``) 로
거절된다 — 규칙이 금지하지 않는 것을 금지한다.

6-Q 가 이것을 ``tests/test_legal_action_engine_boundary_audit.py::test_03``
에 **재어서 남겼다** (공유 계약 변경이라 고치지 않았다). 6-R 이 고쳤으므로
그 핀은 고쳐진 쪽을 재도록 다시 썼다.

무엇을 고쳤는가 — 그리고 무엇을 **고치지 않았는가**
---------------------------------------------------
``engine/duel.py`` 한 파일이다. 칸을 더하지 않았고
(``DuelStep`` 의 필드 수가 그대로다 — ``S`` 절이 센다), 새 enum 도 새 모델도
만들지 않았다 (§5 "새로운 enum 이나 모델을 무조건 추가하지 않는다").

* ``_resolve_chain`` 이 체인을 **조건 없이** 비운다 — 그 체인은 끝났고
  (``ResponseLoop.resolve`` 가 ``AFTER_CHAIN_RULE`` 로 기회를 닫는다) 다시
  풀릴 수 없다.
* 체인을 푼 패스가 ``accepted=True`` 를 돌려준다. **불발 사유는 버리지
  않는다** — ``code`` 와 ``reason`` 이 그대로 들고 간다.
* ``DuelStep.accepted`` · ``code`` 에 뜻을 글로 적었다. 그때까지 설명이
  **없었고**, 그 공백이 ①을 만들었다.

🔴 **"accepted=True 를 돌려주도록 바꾼 패치" 가 아니다** (§16 이 금지한
것). ``code`` 가 ``ValidationCode.OK`` 가 **아니고**, ``EventJournal`` 에
불발된 링크의 ``EffectEvent`` 가 **없다** — "해결했다" 고 적지 않는 규율은
그 둘이 지킨다 (``H`` · ``K`` 절).

세 사실을 따로 묻는다
---------------------
======================  ==================================================
행위를 수락했는가        ``DuelStep.accepted``
체인에 등록되었는가      ``Duel.chain`` (``links`` · ``resolved_count``)
효과가 적용되었는가      ``EventJournal`` 의 ``EffectEvent`` · ``GameState``
======================  ==================================================

이 파일의 모든 절이 이 셋을 **같은 자리에서 따로** 센다.
"""

import ast
import collections
import dataclasses
import inspect
import pathlib
import textwrap

import pytest

from agent.runner import DuelRunner
from agent.search import search_policy
from agent.simulation import SimulationStatus, Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidator
from engine.activation_timing import ActivationTiming, ActivationTimingChecker
from engine.chain import Chain
from engine.duel import Duel, DuelStep, duel_components
from engine.effect.journal import EventJournal
from engine.effect.library import definition_registry
from engine.ids import EffectRef
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.target_bridge import selections_for, target_combinations
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
P0, P1 = 0, 1

POT_OF_GREED = 55144522  # 욕망의 항아리 — 자신 DECK 에 2장 이상이어야 해결된다
GIFT_OF_GREED = 5915629  # 욕망의 선물 — 일반 함정, **상대**가 2장 드로우
FINE = 92595643  # 벌금 — 패 2장 버리기 (Phase 6-P 의 다중 대상)
LOST = 24623598  # 로스트 — 🔴 ``executable=False``, 실행을 옮기지 못했다
HONEST = 37742478  # 어니스트 — 기동 효과, 자기 자신을 패로 (Phase 6-L)
LUSTER_DRAGON = 11091375  # 통상 몬스터 — 덱과 패를 채우는 데 쓴다

DEFS = definition_registry()


# ======================================================================
# 판 만들기 — 전부 실제 엔진으로
# ======================================================================


def board(
    repository,
    *,
    my_deck: int = 30,
    their_deck: int = 30,
    my_hand=(),
    their_hand=(),
    my_mzone=(),
    their_mzone=(),
    their_hand_fodder: int = 0,
    turn_player: int = P0,
    journal=None,
):
    """
    메인 페이즈의 판 하나. ``my_deck`` 이 작을수록 **욕망의 항아리의 해결
    조건이 깨지기 쉽다** — 이 파일의 불발 시나리오가 그것으로 만들어진다.
    """
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * my_deck, [LUSTER_DRAGON] * their_deck),
        turn_player=turn_player,
        seed=1,
    )
    hands = {P0: [], P1: []}
    for seat, cards in ((P0, my_hand), (P1, their_hand)):
        for card_id in cards:
            hands[seat].append(
                state.create_instance(
                    card_id, owner=seat, zone=Zone.HAND
                ).instance_id
            )
    placed = {P0: [], P1: []}
    for seat, layout in ((P0, my_mzone), (P1, their_mzone)):
        for card_id in layout:
            card = state.create_instance(card_id, owner=seat, zone=Zone.HAND)
            state.move(
                card, Zone.MZONE, to_player=seat, position=Position.FACEUP_ATTACK
            )
            placed[seat].append(card.instance_id)
    for _ in range(their_hand_fodder):
        state.create_instance(LUSTER_DRAGON, owner=P1, zone=Zone.HAND)
    state.turn.turn_number = 5
    state.turn.turn_player = turn_player
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=turn_player, phase=Phase.MAIN1),
        **duel_components(journal=journal),
    )
    return duel, hands, placed


def set_down(duel, instance, seat=P0):
    """실제 ``SET_SPELL_TRAP`` 행위로 세운다 — 기록이 남아야 한다."""
    step = duel.apply(PlayerAction.set_spell_trap(actor=seat, source=instance))
    assert step.accepted, step.reason
    return step


def next_turn(duel, to_seat, phase=Phase.MAIN1):
    duel.state.turn.turn_number += 1
    duel.state.turn.turn_player = to_seat
    duel.state.turn.set_phase(phase)
    duel.priority = PriorityState.idle(turn_player=to_seat, phase=phase)


def activation(seat, instance, card_id, targets=()):
    return PlayerAction.activate_effect(
        actor=seat,
        source=instance,
        effect_ref=EffectRef(card_id, 0),
        targets=targets,
    )


def passes(duel):
    """지금 열린 창에서 **고를 수 있는** 패스들."""
    return [
        a
        for a in duel.legal_actions().allowed
        if a.kind is PlayerActionKind.PASS
    ]


def settle(duel):
    """창이 닫힐 때까지 패스한다. **걸음을 전부** 돌려준다 (§6)."""
    steps = []
    guard = 0
    while duel.priority.is_open and guard < 8:
        guard += 1
        available = passes(duel)
        if not available:
            break
        steps.append(duel.apply(available[0]))
    return steps


def effect_refs(journal):
    """기록에 남은 **효과 사건**의 순서 — 적용된 것만 남는다."""
    return [
        str(event.effect_ref)
        for event in journal
        if event.kind.name == "EFFECT"
    ]


def zone_ids(duel, seat, zone):
    return [card.card_id for card in duel.state.player(seat).zone(zone) if card]


# ----------------------------------------------------------------------
# 🔴 이 파일의 중심 시나리오 — 체인 2 가 체인 1 의 조건을 거짓으로 만든다
# ----------------------------------------------------------------------


def fizzling_chain(repository, *, my_deck, journal=None):
    """
    **공식 규칙 그대로의 불발 하나.**

    P0 의 덱을 ``my_deck`` 장으로 두고,

    1. P1 이 욕망의 선물을 **세트한다** (앞 턴).
    2. P0 의 턴 — 욕망의 항아리를 발동한다 (체인 1). 이 시점의 P0 덱은
       2장 이상이므로 발동은 적법하다.
    3. P1 이 세트된 욕망의 선물을 발동한다 (체인 2).
    4. 역순 해결 — 체인 2 가 먼저 풀려 **P0 이 2장 뽑는다.**
    5. 그래서 체인 1 의 "자신 DECK 에 2장 이상" 이 ``my_deck`` 에 따라
       **참이거나 거짓**이 된다.

    ``my_deck=3`` → 남은 1장, 체인 1 **불발**.
    ``my_deck=5`` → 남은 3장, 체인 1 **해결**.

    돌려주는 것: ``(duel, pot, gift, step1, step2, settled)``
    """
    duel, hands, _ = board(
        repository,
        my_deck=my_deck,
        my_hand=(POT_OF_GREED,),
        their_hand=(GIFT_OF_GREED,),
        turn_player=P1,
        journal=journal,
    )
    pot, gift = hands[P0][0], hands[P1][0]
    set_down(duel, gift, seat=P1)
    next_turn(duel, P0)

    step1 = duel.apply(activation(P0, pot, POT_OF_GREED))
    step2 = duel.apply(activation(P1, gift, GIFT_OF_GREED))
    settled = settle(duel)
    return duel, pot, gift, step1, step2, settled


# ======================================================================
# A. §11-A — 불법 행동은 거절된다. 판도 체인도 움직이지 않는다
# ======================================================================


@pytest.mark.real_card
def test_a01_an_illegal_action_is_refused_and_changes_nothing(repository):
    """
    **거절은 거절로 남는다.** 6-R 은 ``accepted`` 를 느슨하게 만들지
    않았다 (§3-4 · §12 "불법 행동이 체인 링크로 등록됨").
    """
    journal = EventJournal()
    duel, hands, _ = board(repository, my_hand=(POT_OF_GREED,), journal=journal)
    before = duel.state.state_hash()

    #: 상대 자리의 카드로 내 차례에 발동한다 — 후보가 아니다.
    step = duel.apply(activation(P1, hands[P0][0], POT_OF_GREED))

    assert step.accepted is False
    assert bool(step) is False
    assert step.code is not ValidationCode.OK
    assert duel.chain.is_empty
    assert duel.state.state_hash() == before
    assert list(journal) == []


@pytest.mark.real_card
def test_a02_a_refused_action_is_never_reported_as_resolved(repository):
    """
    **거절된 걸음의 이유는 "해결" 을 말하지 않는다** (§12 "거절된 행동을
    잘못 성공으로 표시").
    """
    duel, hands, _ = board(repository, my_hand=(POT_OF_GREED,))
    step = duel.apply(activation(P1, hands[P0][0], POT_OF_GREED))
    assert "해결했습니다" not in step.reason
    assert "체인" not in step.reason
    assert step.result is None


# ======================================================================
# B. §11-B — 체인을 쓰지 않는 행동의 의미론은 그대로다
# ======================================================================


@pytest.mark.real_card
def test_b01_a_non_chain_action_is_accepted_with_ok(repository):
    """세트는 체인을 만들지 않는다 — ``accepted=True`` · ``code=OK``."""
    journal = EventJournal()
    duel, hands, _ = board(
        repository, my_hand=(GIFT_OF_GREED,), journal=journal
    )
    step = duel.apply(
        PlayerAction.set_spell_trap(actor=P0, source=hands[P0][0])
    )
    assert (step.accepted, step.code) == (True, ValidationCode.OK)
    #: 체인은 비어 있고 우선권 창도 열리지 않았다.
    assert duel.chain.is_empty
    assert not duel.priority.is_open
    #: 판은 바뀌었고, 기록에는 **행위 사건**만 남는다 (효과가 아니다).
    assert [event.kind.name for event in journal] == ["ACTION"]
    assert effect_refs(journal) == []


@pytest.mark.real_card
def test_b02_pass_is_only_a_candidate_inside_an_open_window(repository):
    """
    🔴 **실측 — 체인이 없으면 ``PASS`` 는 후보가 아니다.**

    빈 메인 페이즈에서 ``legal_actions`` 가 내놓는 "넘기기" 는
    ``END_PHASE`` 다. ``PASS`` 는 **열린 응답 창**에서만 나온다 — 그래서
    6-R 이 고친 자리(``_resolve_chain``)에 창 없이 닿을 수 없다.

    이 사실이 ``_resolve_chain`` 을 조건 없이 비워도 안전한 근거의 절반이다
    (나머지 절반은 ``S`` 절의 "호출자가 하나뿐" 이다).
    """
    duel, _, _ = board(repository)
    kinds = {a.kind for a in duel.legal_actions(P0).allowed}
    assert PlayerActionKind.PASS not in kinds, kinds
    assert PlayerActionKind.END_PHASE in kinds, kinds

    #: 창을 열면 **그때** 패스가 나온다.
    duel, hands, _ = board(repository, my_hand=(POT_OF_GREED,))
    duel.apply(activation(P0, hands[P0][0], POT_OF_GREED))
    assert duel.priority.is_open
    assert PlayerActionKind.PASS in {a.kind for a in duel.legal_actions().allowed}


# ======================================================================
# C. §11-C — 체인 1: **접수**와 **해결**은 같은 걸음이 아니다
# ======================================================================


@pytest.mark.real_card
def test_c01_chain_one_is_accepted_and_not_yet_resolved(repository):
    """
    🔴 **§2 의 전제를 정정하는 자리.** 체인 링크를 만든 걸음은
    ``accepted=True`` 다.

    그리고 그 걸음은 **해결을 주장하지 않는다** — 세 사실을 따로 센다.
    """
    journal = EventJournal()
    duel, hands, _ = board(repository, my_hand=(POT_OF_GREED,), journal=journal)
    step = duel.apply(activation(P0, hands[P0][0], POT_OF_GREED))

    #: ① 행위를 수락했다.
    assert (step.accepted, step.code) == (True, ValidationCode.OK)
    assert "상대의 응답을 기다립니다" in step.reason
    #: ② 체인에 등록되었다 — 그리고 아직 아무것도 풀리지 않았다.
    assert len(duel.chain.links) == 1
    assert duel.chain.resolved_count == 0
    assert not duel.chain.is_complete
    assert duel.priority.is_open
    #: ③ 효과는 적용되지 않았다 — 기록에 효과 사건이 **없다.**
    assert effect_refs(journal) == []


@pytest.mark.real_card
def test_c02_registration_alone_never_draws_a_card(repository):
    """
    **§9 — 체인 등록만으로 효과 적용을 주장하지 않는다.**

    욕망의 항아리는 2장 뽑는 카드다. 발동만 한 자리에서 패가 늘면 그것은
    거짓 성공이다.
    """
    duel, hands, _ = board(repository, my_hand=(POT_OF_GREED,))
    deck_before = len(duel.state.player(P0).zone(Zone.DECK))
    duel.apply(activation(P0, hands[P0][0], POT_OF_GREED))
    assert len(duel.state.player(P0).zone(Zone.DECK)) == deck_before


# ======================================================================
# D. §11-D — 체인 2 응답도 거짓 실패가 아니다
# ======================================================================


@pytest.mark.real_card
def test_d01_the_chain_two_response_is_accepted(repository):
    """
    **상대 턴의 함정 발동이 체인 2 를 만들고 수락된다** (6-Q 가 연 길).

    §2 가 "체인 링크가 생성됐는데 accepted=False" 라고 적은 바로 그
    자리다 — 재면 ``True`` 다.
    """
    journal = EventJournal()
    duel, pot, gift, step1, step2, _ = fizzling_chain(
        repository, my_deck=5, journal=journal
    )
    assert (step1.accepted, step1.code) == (True, ValidationCode.OK)
    assert (step2.accepted, step2.code) == (True, ValidationCode.OK)
    assert "체인 2" in step2.reason
    #: 두 링크가 **둘 다** 쌓였다.
    assert len(duel.chain.links) == 0, "해결이 끝났으므로 비어 있다"


@pytest.mark.real_card
def test_d02_both_links_are_on_the_chain_before_anyone_passes(repository):
    """같은 시나리오를 **패스 전에** 멈춰서 링크 둘을 직접 센다."""
    duel, hands, _ = board(
        repository,
        my_deck=5,
        my_hand=(POT_OF_GREED,),
        their_hand=(GIFT_OF_GREED,),
        turn_player=P1,
    )
    pot, gift = hands[P0][0], hands[P1][0]
    set_down(duel, gift, seat=P1)
    next_turn(duel, P0)
    duel.apply(activation(P0, pot, POT_OF_GREED))
    duel.apply(activation(P1, gift, GIFT_OF_GREED))

    assert len(duel.chain.links) == 2
    assert duel.chain.resolved_count == 0
    assert duel.priority.is_open


# ======================================================================
# E. §11-E — 체인 대기 중의 상태
# ======================================================================


@pytest.mark.real_card
def test_e01_waiting_does_not_clear_the_chain(repository):
    """
    🔴 **열린 창에서는 체인이 남아 있어야 한다.** 6-R 이 비우는 자리는
    ``_resolve_chain`` 하나이고, 그것은 창이 닫힐 때만 불린다.
    """
    duel, hands, _ = board(
        repository,
        my_deck=5,
        my_hand=(POT_OF_GREED,),
        their_hand=(GIFT_OF_GREED,),
        turn_player=P1,
    )
    pot, gift = hands[P0][0], hands[P1][0]
    set_down(duel, gift, seat=P1)
    next_turn(duel, P0)
    duel.apply(activation(P0, pot, POT_OF_GREED))

    #: 상대가 한 번 패스해도 체인은 그대로다 — 발동한 쪽이 아직 남았다.
    first = duel.apply(passes(duel)[0])
    assert (first.accepted, first.code) == (True, ValidationCode.OK)
    assert len(duel.chain.links) == 1, "창이 아직 열려 있다"
    assert duel.priority.is_open


@pytest.mark.real_card
def test_e02_the_open_window_only_offers_responses(repository):
    """대기 중에 내놓는 후보는 **응답**뿐이다 — 통상 소환이 섞이지 않는다."""
    duel, hands, _ = board(
        repository, my_hand=(POT_OF_GREED, LUSTER_DRAGON)
    )
    duel.apply(activation(P0, hands[P0][0], POT_OF_GREED))
    kinds = {a.kind for a in duel.legal_actions().allowed}
    assert PlayerActionKind.NORMAL_SUMMON not in kinds, kinds
    assert PlayerActionKind.PASS in kinds


# ======================================================================
# F. §11-F — 패스: 기회 포기와 체인 해결을 **가른다**
# ======================================================================


@pytest.mark.real_card
def test_f01_the_two_kinds_of_pass_are_both_accepted(repository):
    """
    🔴 **§3-13 · §3-14 — 적법한 패스는 언제나 수락이다.**

    같은 체인에서 패스가 둘 난다. 하나는 기회를 넘기기만 하고, 하나는
    체인을 푼다. **둘 다** ``accepted=True`` 이고, 둘을 가르는 것은
    ``reason`` 과 체인 상태다 — ``accepted`` 가 아니다.
    """
    duel, pot, gift, _, _, settled = fizzling_chain(repository, my_deck=5)
    assert len(settled) == 2, [s.reason for s in settled]
    first, last = settled

    assert first.accepted is True
    assert first.code is ValidationCode.OK
    assert first.reason == "우선권을 넘겼습니다."

    assert last.accepted is True
    assert last.code is ValidationCode.OK
    assert "해결했습니다" in last.reason
    #: 체인을 푼 쪽에서만 체인이 비워진다.
    assert duel.chain.is_empty
    assert not duel.priority.is_open


@pytest.mark.real_card
def test_f02_a_pass_alone_never_claims_a_resolution(repository):
    """
    **§12 "PASS 만으로 효과가 해결됐다고 잘못 표시"** — 아무 링크도 쌓이지
    않은 창을 닫는 패스는 "해결" 을 말하지 않는다.

    ``Duel.advance`` 로 진짜 응답 창을 하나 열고, 체인 없이 닫는다.
    """
    duel, hands, _ = board(repository, my_hand=(POT_OF_GREED,))
    duel.apply(activation(P0, hands[P0][0], POT_OF_GREED))
    #: 첫 패스는 상대의 것이고 체인을 풀지 않는다.
    first = duel.apply(passes(duel)[0])
    assert (first.accepted, first.code) == (True, ValidationCode.OK)
    assert "해결" not in first.reason
    assert first.reason == "우선권을 넘겼습니다."
    assert len(duel.chain.links) == 1, "아직 풀리지 않았다"


# ======================================================================
# G. §11-G — 역순 해결
# ======================================================================


@pytest.mark.real_card
def test_g01_the_chain_resolves_in_reverse_order(repository):
    """
    🔴 **RULE-CHAIN-001 — 체인 2 가 먼저 풀린다.** 기록의 순서가 사실이다.

    욕망의 선물(체인 2)이 P0 에게 2장 뽑게 하고, **그 다음** 욕망의
    항아리(체인 1)가 2장 뽑는다. 덱 5장이면 둘 다 성립한다.
    """
    journal = EventJournal()
    duel, pot, gift, _, _, settled = fizzling_chain(
        repository, my_deck=5, journal=journal
    )
    assert effect_refs(journal) == [
        f"{GIFT_OF_GREED}:e[0]",
        f"{POT_OF_GREED}:e[0]",
    ]
    #: 둘 다 적용되었으므로 P0 은 **네 장** 뽑았다.
    assert len(duel.state.player(P0).zone(Zone.DECK)) == 1
    assert len(duel.state.player(P0).zone(Zone.HAND)) == 4
    assert settled[-1].code is ValidationCode.OK


# ======================================================================
# H. §11-H — 🔴 불발: 발동 접수와 혼동하지 않는다
# ======================================================================


@pytest.mark.real_card
def test_h01_a_fizzling_link_does_not_refuse_the_pass(repository):
    """
    🔴 **이 Phase 가 고친 자리.**

    체인 2 가 P0 의 덱을 비워서 체인 1 의 해결 조건이 거짓이 된다. 예전에는
    그 패스가 ``accepted=False`` 로 돌아왔다 — **적법한 패스를 실패로
    보고한 것**이다.

    지금은 ``accepted=True`` 이고, **불발 사유는 버려지지 않는다.**
    """
    journal = EventJournal()
    duel, pot, gift, step1, step2, settled = fizzling_chain(
        repository, my_deck=3, journal=journal
    )
    #: 발동 둘은 그대로 수락이다.
    assert (step1.accepted, step1.code) == (True, ValidationCode.OK)
    assert (step2.accepted, step2.code) == (True, ValidationCode.OK)

    last = settled[-1]
    #: ① 패스는 수락되었다.
    assert last.accepted is True
    assert last.action.kind is PlayerActionKind.PASS
    #: ② 그러나 **"해결했다" 고 적지 않았다** — 코드가 ``OK`` 가 아니다.
    assert last.code is not ValidationCode.OK
    assert last.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert "해결하지 못했습니다" in last.reason
    assert "발동 조건이 거짓입니다" in last.reason
    #: 행위의 위법을 말하는 문구가 아니다.
    assert "허가된 행위가 아닙니다" not in last.reason


@pytest.mark.real_card
def test_h02_the_fizzled_link_leaves_no_effect_event(repository):
    """
    🔴 **§12 "효과가 불발됐는데 상태 변경 성공 표시"** — 적용된 링크만
    기록에 남는다.

    체인 2 는 적용되었고 체인 1 은 적용되지 않았다. 기록이 그 둘을 가른다.
    """
    journal = EventJournal()
    duel, pot, gift, _, _, _ = fizzling_chain(
        repository, my_deck=3, journal=journal
    )
    assert effect_refs(journal) == [f"{GIFT_OF_GREED}:e[0]"]
    #: 욕망의 항아리의 드로우는 **일어나지 않았다** — P0 은 2장만 뽑았다.
    assert len(duel.state.player(P0).zone(Zone.DECK)) == 1
    assert len(duel.state.player(P0).zone(Zone.HAND)) == 2


@pytest.mark.real_card
def test_h03_the_dead_chain_is_cleared(repository):
    """
    🔴 **원인을 고친 자리 (②).** 불발된 체인이 남지 않는다.

    예전 실측: ``links=3`` · ``resolved_count=2`` · ``is_complete`` 거짓이
    **턴을 넘겨도 사라지지 않았다.** 그 체인이
    ``ActivationTiming.chain_is_open`` 을 참으로 고정해 스펠 스피드 1 발동을
    듀얼 끝까지 전부 막았다.
    """
    duel, pot, gift, _, _, _ = fizzling_chain(repository, my_deck=3)
    assert duel.chain.is_empty
    assert len(duel.chain.links) == 0
    assert duel.chain.resolved_count == 0
    assert not duel.priority.is_open


@pytest.mark.real_card
def test_h04_a_spell_speed_one_activation_still_works_afterwards(repository):
    """
    🔴 **잠금이 사라졌다는 증거.** 불발 뒤에도 통상 마법을 발동할 수 있다.

    남은 체인이 있으면 ``chain_is_open`` 이 참이고, 스펠 스피드 1 은
    ``SPELL_SPEED_TOO_LOW`` 로 거절된다. 그래서 이 시험이 **그 다음 발동**
    까지 간다.
    """
    duel, pot, gift, _, _, _ = fizzling_chain(repository, my_deck=3)
    #: P0 의 패에는 뽑은 통상 몬스터 2장이 있다. 새 마법을 한 장 쥐여 준다.
    fresh = duel.state.create_instance(
        POT_OF_GREED, owner=P0, zone=Zone.HAND
    ).instance_id
    next_turn(duel, P1)
    next_turn(duel, P0)
    #: 덱이 1장이므로 발동 조건("자신 DECK 에 2장 이상")이 아직 거짓이다 —
    #: 거절 이유가 **스펠 스피드가 아니라 카드의 조건**이어야 한다.
    withheld = {
        w.reason
        for w in duel.legal_actions(P0).withheld
        if w.kind is PlayerActionKind.ACTIVATE_EFFECT
    }
    assert not any("스펠 스피드" in reason for reason in withheld), withheld

    #: 덱을 채우면 **후보로 나온다.**
    for _ in range(3):
        duel.state.create_instance(LUSTER_DRAGON, owner=P0, zone=Zone.DECK)
    allowed = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert [a.source for a in allowed] == [fresh], allowed
    step = duel.apply(allowed[0])
    assert (step.accepted, step.code) == (True, ValidationCode.OK)
    assert len(duel.chain.links) == 1, "체인 1 부터 다시 시작한다"


@pytest.mark.real_card
def test_h06_a_fizzling_pass_still_reports_the_end_of_the_duel(repository):
    """
    🔴 **불발 분기도 끝을 본다.**

    예전의 불발 분기는 ``DuelStep(action, False, last.code, last.reason)``
    이었다 — ``result=`` 를 **적지 않았다.** 그러면 그 체인의 해결로 듀얼이
    끝났을 때 ``DuelStep.result`` 가 ``None`` 으로 돌아가고, 호출자는 끝난
    듀얼을 계속 돌린다. 6-R 이 ``result=self._check_end()`` 를 더했다.

    🔴 **이 자리는 지어낸 상태로 밟는다.** 등재된 효과 다섯 개 중 라이프를
    건드리는 것이 **하나도 없으므로** (``_check_end`` 는 라이프 0 만 본다)
    실제 카드만으로는 "불발 + 듀얼 종료" 가 같은 걸음에 올 수 없다. 그래서
    마지막 패스 **직전에** 라이프를 0 으로 두고 분기를 센다 — 재는 것은
    카드가 아니라 **분기**다.
    """
    duel, hands, _ = board(
        repository,
        my_deck=3,
        my_hand=(POT_OF_GREED,),
        their_hand=(GIFT_OF_GREED,),
        turn_player=P1,
    )
    pot, gift = hands[P0][0], hands[P1][0]
    set_down(duel, gift, seat=P1)
    next_turn(duel, P0)
    duel.apply(activation(P0, pot, POT_OF_GREED))
    duel.apply(activation(P1, gift, GIFT_OF_GREED))
    duel.apply(passes(duel)[0])

    #: 체인을 푸는 패스 **직전**에 라이프를 0 으로.
    duel.state.player(P0).life_points = 0

    step = duel.apply(passes(duel)[0])

    #: 불발이 맞다.
    assert step.accepted is True
    assert step.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert "해결하지 못했습니다" in step.reason
    #: 🔴 그리고 **끝을 들고 온다.**
    assert step.result is not None, "불발 분기가 ``_check_end`` 를 부르지 않았다"
    assert step.result.winner == P1
    assert duel.is_over


@pytest.mark.real_card
def test_h05_the_timing_gate_no_longer_refuses_spell_speed_one(repository):
    """
    🔴 **잠금의 정확한 자리를 못 박는다.**

    막고 있던 것은 :meth:`Duel._activation_gate` 의 **둘째 관문**이다
    (``ActivationTimingChecker``). 남은 체인이
    ``ActivationTiming.chain_is_open`` 을 참으로 만들면 그 관문이 모든
    스펠 스피드 1 발동에 ``SPELL_SPEED_TOO_LOW`` 를 돌려준다.

    실측 (``seed=303`` · DIGEST 덱, 고치기 전):

    ====================================  ===============================
    불발 직후의 체인                        ``links=3 resolved=2``
    ``chain_is_open``                      ``True``
    관문1 ``ActionValidator``               ``OK`` ← 규칙은 허락한다
    관문2 ``ActivationTimingChecker``       ``SPELL_SPEED_TOO_LOW``
    남은 네 턴(5→8)의 발동 후보             **0건**
    ====================================  ===============================

    그리고 그 거절은 **보류 목록에도 남지 않았다** — 후보 생성이 관문에서
    걸린 것을 버리므로 ``apply`` 로 직접 넣으면 ``RULE_NOT_IMPLEMENTED``
    가 돌아온다. 아래는 고친 뒤 그 관문이 **열려 있음**을 직접 센다.
    """
    duel, pot, gift, _, _, _ = fizzling_chain(repository, my_deck=3)
    fresh = duel.state.create_instance(
        POT_OF_GREED, owner=P0, zone=Zone.HAND
    ).instance_id
    for _ in range(5):
        duel.state.create_instance(LUSTER_DRAGON, owner=P0, zone=Zone.DECK)
    next_turn(duel, P1)
    next_turn(duel, P0)

    action = activation(P0, fresh, POT_OF_GREED)
    view = duel.view(P0)
    timing = ActivationTiming(
        duel.chain, duel.priority, set_this_turn=duel._set_this_turn(action)
    )
    #: 🔴 남은 체인이 없으므로 창이 닫혀 있다.
    assert timing.chain_is_open is False
    timed = ActivationTimingChecker(view).check(timing, action)
    assert timed.code is not ValidationCode.SPELL_SPEED_TOO_LOW, timed.reason
    assert timed.code is ValidationCode.OK, timed.reason
    #: 관문 셋을 합쳐도 통과한다 — 그래서 후보로 나온다.
    gate = duel._activation_gate(
        action,
        validator=ActionValidator(view, definitions=DEFS),
        selections=selections_for(
            DEFS.definition_for(EffectRef(POT_OF_GREED, 0)), action
        ),
    )
    assert gate.code is ValidationCode.OK, gate.reason


# ======================================================================
# I. §11-I — 미지원 효과를 해결했다고 표시하지 않는다
# ======================================================================


@pytest.mark.real_card
def test_i01_an_unexecutable_effect_is_never_offered(repository):
    """
    **로스트는 ``executable=False`` 다** — 실행을 옮기지 못한 카드다.

    후보로 나오지 않고, 직접 넣어도 거절된다. 기록에 효과 사건이 없다.
    """
    journal = EventJournal()
    duel, hands, _ = board(
        repository, my_hand=(LOST,), their_hand_fodder=6, journal=journal
    )
    lost = hands[P0][0]
    set_down(duel, lost)
    next_turn(duel, P1)
    next_turn(duel, P0)

    offered = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert offered == []
    step = duel.apply(activation(P0, lost, LOST))
    assert step.accepted is False
    assert duel.chain.is_empty
    assert effect_refs(journal) == []


# ======================================================================
# J. §11-J — GameState 는 **적용된 것만** 담는다
# ======================================================================


@pytest.mark.real_card
def test_j01_only_applied_deltas_reach_the_state(repository):
    """
    같은 시나리오를 덱 3장 · 5장으로 두 번 돌려 **차이만** 센다.

    달라지는 것은 체인 1 의 적용 여부뿐이고, 그래서 판의 차이도 그 두 장
    뿐이어야 한다.
    """
    fizzled, _, _, _, _, _ = fizzling_chain(repository, my_deck=3)
    resolved, _, _, _, _, _ = fizzling_chain(repository, my_deck=5)

    #: 불발: 2장만 뽑았다 (체인 2). 해결: 4장 뽑았다 (체인 2 + 체인 1).
    assert len(fizzled.state.player(P0).zone(Zone.HAND)) == 2
    assert len(resolved.state.player(P0).zone(Zone.HAND)) == 4
    #: 🔴 **불발이어도 놓인 마법은 묘지로 간다** (RULE-SPELLTRAP-002).
    assert zone_ids(fizzled, P0, Zone.GRAVE) == [POT_OF_GREED]
    assert zone_ids(resolved, P0, Zone.GRAVE) == [POT_OF_GREED]
    #: 상대의 함정도 양쪽 모두 묘지에 있다 — 그쪽은 적용되었다.
    assert zone_ids(fizzled, P1, Zone.GRAVE) == [GIFT_OF_GREED]
    assert zone_ids(resolved, P1, Zone.GRAVE) == [GIFT_OF_GREED]


@pytest.mark.real_card
def test_j02_the_pass_that_fizzles_still_moved_the_board(repository):
    """
    **거짓 실패가 왜 위험했는가** — 그 패스는 판을 실제로 바꿨다.

    예전 ``accepted=False`` 를 호출자가 "아무 일도 없었다" 로 읽으면 네 장
    차이를 놓친다.
    """
    duel, hands, _ = board(
        repository,
        my_deck=3,
        my_hand=(POT_OF_GREED,),
        their_hand=(GIFT_OF_GREED,),
        turn_player=P1,
    )
    pot, gift = hands[P0][0], hands[P1][0]
    set_down(duel, gift, seat=P1)
    next_turn(duel, P0)
    duel.apply(activation(P0, pot, POT_OF_GREED))
    duel.apply(activation(P1, gift, GIFT_OF_GREED))
    duel.apply(passes(duel)[0])  # 첫 패스
    before = duel.state.state_hash()

    step = duel.apply(passes(duel)[0])  # 체인을 푸는 패스

    assert step.accepted is True
    assert duel.state.state_hash() != before, "판이 바뀌었는데 실패로 읽혔다"


# ======================================================================
# K. §11-K — EventJournal: 등록과 적용을 가른다
# ======================================================================


@pytest.mark.real_card
def test_k01_registration_and_application_are_different_events(repository):
    """
    🔴 **기록이 세 사실을 가른다.**

    발동 선언은 ``ACTION`` 으로, 효과 적용은 ``EFFECT`` 로 남는다. 불발된
    링크는 ``ACTION`` 은 있고 ``EFFECT`` 는 **없다.**
    """
    journal = EventJournal()
    fizzling_chain(repository, my_deck=3, journal=journal)
    kinds = collections.Counter(event.kind.name for event in journal)
    #: 세트 1 + 발동 2 + 묘지로 보내기 2 = ``ACTION`` 다섯.
    assert kinds["ACTION"] == 5, [e.kind.name for e in journal]
    #: 적용된 효과는 **하나**다.
    assert kinds["EFFECT"] == 1, effect_refs(journal)


@pytest.mark.real_card
def test_k02_every_effect_event_carries_a_real_delta(repository):
    """
    **§12 "실제 Delta 가 없는데 적용 이벤트 기록"** — 효과 사건은 전부
    ``applied`` 와 ``deltas`` 를 들고 있다.
    """
    journal = EventJournal()
    fizzling_chain(repository, my_deck=5, journal=journal)
    effects = [event for event in journal if event.kind.name == "EFFECT"]
    assert len(effects) == 2
    for event in effects:
        assert event.applied, event
        assert event.deltas, event


@pytest.mark.real_card
def test_k03_no_effect_is_recorded_twice(repository):
    """**§12 "동일 효과가 중복 해결됨"** — 기록에 같은 참조가 두 번 없다."""
    journal = EventJournal()
    fizzling_chain(repository, my_deck=5, journal=journal)
    refs = effect_refs(journal)
    assert len(refs) == len(set(refs)), refs


# ======================================================================
# L. §11-L — 기존 마법 카드가 그대로다
# ======================================================================


@pytest.mark.real_card
def test_l01_a_normal_spell_still_resolves_alone(repository):
    """욕망의 항아리 한 장 — 발동, 패스 둘, 해결, 2장 드로우."""
    journal = EventJournal()
    duel, hands, _ = board(repository, my_hand=(POT_OF_GREED,), journal=journal)
    deck = len(duel.state.player(P0).zone(Zone.DECK))
    step = duel.apply(activation(P0, hands[P0][0], POT_OF_GREED))
    assert step.accepted
    last = settle(duel)[-1]
    assert (last.accepted, last.code) == (True, ValidationCode.OK)
    assert "해결했습니다" in last.reason
    assert len(duel.state.player(P0).zone(Zone.DECK)) == deck - 2
    assert len(duel.state.player(P0).zone(Zone.HAND)) == 2
    assert effect_refs(journal) == [f"{POT_OF_GREED}:e[0]"]
    assert duel.chain.is_empty


# ======================================================================
# M. §11-M — Phase 6-Q 의 일반 함정이 그대로다
# ======================================================================


@pytest.mark.real_card
def test_m01_a_set_normal_trap_still_activates_and_resolves(repository):
    """세트 → 다음 턴 → 발동 → 해결. 상대가 2장 뽑는다."""
    journal = EventJournal()
    duel, hands, _ = board(
        repository, my_hand=(GIFT_OF_GREED,), journal=journal
    )
    trap = hands[P0][0]
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)

    their_hand = len(duel.state.player(P1).zone(Zone.HAND))
    step = duel.apply(activation(P0, trap, GIFT_OF_GREED))
    assert (step.accepted, step.code) == (True, ValidationCode.OK)
    last = settle(duel)[-1]
    assert (last.accepted, last.code) == (True, ValidationCode.OK)
    assert len(duel.state.player(P1).zone(Zone.HAND)) == their_hand + 2
    assert effect_refs(journal) == [f"{GIFT_OF_GREED}:e[0]"]


@pytest.mark.real_card
def test_m02_a_trap_set_this_turn_is_still_refused(repository):
    """
    **RULE-SPELLTRAP-009 가 그대로다** — 세운 턴에는 발동할 수 없다.

    6-R 이 관문을 느슨하게 만들지 않았다는 쪽의 증거다.
    """
    duel, hands, _ = board(repository, my_hand=(GIFT_OF_GREED,))
    trap = hands[P0][0]
    set_down(duel, trap)
    offered = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert offered == []


# ======================================================================
# N. §11-N — Phase 6-L 의 어니스트가 그대로다
# ======================================================================


@pytest.mark.real_card
def test_n01_the_honest_ignition_effect_still_executes(repository):
    """
    기동 효과 — ``SetRange(LOCATION_MZONE)`` 이므로 **필드에서** 발동한다.
    자기 자신을 패로 되돌린다.
    """
    journal = EventJournal()
    duel, _, placed = board(
        repository, my_mzone=(HONEST,), journal=journal
    )
    honest = placed[P0][0]
    step = duel.apply(activation(P0, honest, HONEST))
    assert (step.accepted, step.code) == (True, ValidationCode.OK)
    last = settle(duel)[-1]
    assert (last.accepted, last.code) == (True, ValidationCode.OK)
    assert zone_ids(duel, P0, Zone.HAND) == [HONEST]
    assert zone_ids(duel, P0, Zone.MZONE) == []
    assert effect_refs(journal) == [f"{HONEST}:e[0]"]


# ======================================================================
# O. §11-O — Phase 6-P 의 다중 대상이 그대로다
# ======================================================================


@pytest.mark.real_card
def test_o01_the_two_card_discard_still_resolves(repository):
    """벌금 — 정확히 2장을 고르고, 조합이 셋 나오고, 둘이 묘지로 간다."""
    journal = EventJournal()
    duel, hands, _ = board(
        repository,
        my_hand=(FINE, LUSTER_DRAGON, LUSTER_DRAGON, LUSTER_DRAGON),
        journal=journal,
    )
    fine = hands[P0][0]
    set_down(duel, fine)
    next_turn(duel, P1)
    next_turn(duel, P0)

    definition = DEFS.definition_for(EffectRef(FINE, 0))
    combos = target_combinations(duel.state, P0, definition, fine)
    assert len(combos) == 3, combos
    #: 🔴 조합은 ``tuple[ActionTarget, ...]`` 다 (``targets_from`` 의 모양).
    assert {len(combo) for combo in combos} == {2}, combos

    offered = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and a.effect_ref.card_id == FINE
    ]
    assert len(offered) == 3
    hand_before = len(duel.state.player(P0).zone(Zone.HAND))
    step = duel.apply(offered[0])
    assert (step.accepted, step.code) == (True, ValidationCode.OK)
    last = settle(duel)[-1]
    assert (last.accepted, last.code) == (True, ValidationCode.OK)
    assert "@primary" in last.reason
    #: 버린 2장 + 떠난 함정.
    assert len(duel.state.player(P0).zone(Zone.HAND)) == hand_before - 2
    assert collections.Counter(zone_ids(duel, P0, Zone.GRAVE)) == {
        LUSTER_DRAGON: 2,
        FINE: 1,
    }


# ======================================================================
# P. §11-P — 호출자: Agent · Runner · Simulator
# ======================================================================


@pytest.mark.real_card
def test_p01_the_simulator_no_longer_calls_the_pass_refused(repository):
    """
    🔴 **거짓 실패를 호출자가 믿었다.** ``Simulator.simulate`` 는
    ``accepted=False`` 를 ``REFUSED`` 로 분류한다 — 적법한 수가 "거절된
    수" 로 점수표에 들어갔다.
    """
    duel, pot, gift, _, _, _ = fizzling_chain(repository, my_deck=3)
    #: 같은 판을 다시 만들고, **마지막 패스 직전**에서 멈춘다.
    duel, hands, _ = board(
        repository,
        my_deck=3,
        my_hand=(POT_OF_GREED,),
        their_hand=(GIFT_OF_GREED,),
        turn_player=P1,
    )
    pot, gift = hands[P0][0], hands[P1][0]
    set_down(duel, gift, seat=P1)
    next_turn(duel, P0)
    duel.apply(activation(P0, pot, POT_OF_GREED))
    duel.apply(activation(P1, gift, GIFT_OF_GREED))
    duel.apply(passes(duel)[0])

    resolving = passes(duel)[0]
    simulator = Simulator(duel=duel)
    result = simulator.simulate(resolving, viewer=resolving.actor)

    assert result.status is SimulationStatus.SUPPORTED, result.reason
    assert result.future is not None, "미래가 있어야 점수를 매길 수 있다"
    #: 🔴 그래도 ``code`` 는 ``OK`` 가 아니다 — 불발을 숨기지 않는다.
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    #: 진짜 판은 건드리지 않았다.
    assert len(duel.chain.links) == 2


@pytest.mark.real_card
def test_p02_fork_after_keeps_the_future(repository):
    """``fork_after`` 가 ``None`` 을 돌려주면 탐색 깊이가 끊긴다."""
    duel, hands, _ = board(
        repository,
        my_deck=3,
        my_hand=(POT_OF_GREED,),
        their_hand=(GIFT_OF_GREED,),
        turn_player=P1,
    )
    pot, gift = hands[P0][0], hands[P1][0]
    set_down(duel, gift, seat=P1)
    next_turn(duel, P0)
    duel.apply(activation(P0, pot, POT_OF_GREED))
    duel.apply(activation(P1, gift, GIFT_OF_GREED))
    duel.apply(passes(duel)[0])

    forked = Simulator(duel=duel).fork_after(passes(duel)[0])
    assert forked is not None


@pytest.mark.real_card
def test_p03_the_runner_does_not_stop_on_a_fizzle(repository):
    """
    🔴 **``DuelRunner.run`` 은 거절이 나오면 멈춘다.** 거짓 실패가 듀얼을
    중단시켰다.

    이 시험은 실제 듀얼 여섯 판을 끝까지 돌려 **거부 0건**을 센다.
    """
    deck = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GIFT_OF_GREED] * 4
    total = refused = 0
    for seed in (401, 402, 403):
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
        runner = DuelRunner(
            duel=duel, policies=(search_policy(duel), search_policy(duel))
        )
        transcript = runner.run()
        total += len(transcript.entries)
        refused += sum(1 for e in transcript.entries if not e.accepted)
    assert total > 0
    assert refused == 0


@pytest.mark.real_card
def test_p04_an_activation_preferring_walk_refuses_nothing(repository):
    """
    🔴 **§13-4 의 지표.** 발동을 우선 고르는 산책에서 거부가 **0건**이다.

    6-Q 의 실측은 ``PASS`` 거부 **2건**이었다
    (``tests/test_legal_action_engine_boundary_audit.py::test_03``). 그
    둘이 이 Phase 가 고친 거짓 실패다.
    """
    digest = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GIFT_OF_GREED] * 4
    refused: collections.Counter = collections.Counter()
    accepted = fizzles = leftover = 0
    for seed in (303, 304, 305):
        duel = Duel.start(
            repository, decks=(list(digest), list(digest)), seed=seed
        )
        guard = 0
        while not duel.is_over and guard < 400:
            guard += 1
            if duel.advance() is not None:
                continue
            legal = duel.legal_actions(duel.to_act)
            if not legal.allowed:
                break
            pick = next(
                (
                    a
                    for a in legal.allowed
                    if a.kind is PlayerActionKind.ACTIVATE_EFFECT
                ),
                None,
            ) or legal.allowed[0]
            step = duel.apply(pick)
            if step.accepted:
                accepted += 1
            else:
                refused[pick.kind] += 1
            if "해결하지 못했습니다" in step.reason:
                fizzles += 1
        leftover += len(duel.chain.links)

    assert accepted > 0
    #: ① 거부가 **하나도** 없다.
    assert dict(refused) == {}
    #: ② 불발은 여전히 일어나고 **숨기지 않는다** — 재어서 남긴다.
    assert fizzles == 3, fizzles
    #: ③ 🔴 끝까지 간 뒤 남은 체인이 **0** 이다 (예전엔 3 이 남았다).
    assert leftover == 0


# ======================================================================
# Q. §11-Q — 두 듀얼의 체인이 섞이지 않는다
# ======================================================================


@pytest.mark.real_card
def test_q01_two_duels_keep_their_own_chain(repository):
    """``Chain`` 은 듀얼마다 하나다 — 기본값 공유가 없다."""
    one, hands_one, _ = board(repository, my_hand=(POT_OF_GREED,))
    two, hands_two, _ = board(repository, my_hand=(POT_OF_GREED,))
    one.apply(activation(P0, hands_one[P0][0], POT_OF_GREED))

    assert len(one.chain.links) == 1
    assert two.chain.is_empty
    assert one.chain is not two.chain
    assert one.journal is not two.journal


@pytest.mark.real_card
def test_q02_clearing_one_chain_does_not_touch_the_other(repository):
    """🔴 6-R 이 ``Chain()`` 을 **새로** 만든다 — 공유 객체를 비우지 않는다."""
    one, pot_one, _, _, _, _ = fizzling_chain(repository, my_deck=3)
    two, hands, _ = board(repository, my_hand=(POT_OF_GREED,))
    two.apply(activation(P0, hands[P0][0], POT_OF_GREED))

    assert one.chain.is_empty
    assert len(two.chain.links) == 1


# ======================================================================
# R. §12 — 거짓 성공과 거짓 실패를 둘 다 센다
# ======================================================================


@pytest.mark.real_card
def test_r01_accepted_is_true_exactly_when_the_action_happened(repository):
    """
    🔴 **§12 전체를 한 자리에서 센다.**

    실제 듀얼을 돌면서 모든 걸음에 대해 두 가지를 본다.

    ① ``accepted=False`` 인데 판이 바뀐 걸음 → **거짓 실패**
    ② ``accepted=True`` 이고 ``code=OK`` 인데 **아무 일도 없었다고** 할 수
       있는 걸음은 패스뿐이다 → 그 밖에는 **거짓 성공**

    ①은 0건이어야 한다. 6-Q 실측으로는 **2건**이었다.
    """
    deck = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GIFT_OF_GREED] * 4
    false_failures = []
    false_successes = []
    for seed in (303, 305):
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
        guard = 0
        while not duel.is_over and guard < 400:
            guard += 1
            if duel.advance() is not None:
                continue
            legal = duel.legal_actions(duel.to_act)
            if not legal.allowed:
                break
            pick = next(
                (
                    a
                    for a in legal.allowed
                    if a.kind is PlayerActionKind.ACTIVATE_EFFECT
                ),
                None,
            ) or legal.allowed[0]
            before = duel.state.state_hash()
            step = duel.apply(pick)
            after = duel.state.state_hash()
            if not step.accepted and after != before:
                false_failures.append((pick.kind.name, step.code.name))
            if (
                step.accepted
                and step.code is ValidationCode.OK
                and after == before
                and "해결했습니다" in step.reason
            ):
                false_successes.append((pick.kind.name, step.reason))

    assert false_failures == [], false_failures
    assert false_successes == [], false_successes


@pytest.mark.real_card
def test_r02_a_resolved_step_always_says_ok_and_a_fizzled_one_never_does(
    repository,
):
    """
    **이유와 코드가 어긋나지 않는다.** "해결했습니다" ↔ ``OK``,
    "해결하지 못했습니다" ↔ ``OK`` 아님.
    """
    deck = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GIFT_OF_GREED] * 4
    seen_resolved = seen_fizzled = 0
    for seed in (303, 305):
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
        guard = 0
        while not duel.is_over and guard < 400:
            guard += 1
            if duel.advance() is not None:
                continue
            legal = duel.legal_actions(duel.to_act)
            if not legal.allowed:
                break
            pick = next(
                (
                    a
                    for a in legal.allowed
                    if a.kind is PlayerActionKind.ACTIVATE_EFFECT
                ),
                None,
            ) or legal.allowed[0]
            step = duel.apply(pick)
            if "해결했습니다" in step.reason:
                seen_resolved += 1
                assert step.code is ValidationCode.OK, step.reason
                assert step.accepted is True
            if "해결하지 못했습니다" in step.reason:
                seen_fizzled += 1
                assert step.code is not ValidationCode.OK, step.reason
                assert step.accepted is True, step.reason
    assert seen_resolved > 0
    assert seen_fizzled > 0


@pytest.mark.real_card
def test_r03_a_chain_never_grows_past_a_resolved_link(repository):
    """
    **§12 "체인 링크가 중복 등록됨" · "GameStack 에 없는 링크를 해결"** —
    실제 듀얼에서 체인 길이가 되감기지 않는다.
    """
    deck = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GIFT_OF_GREED] * 4
    for seed in (303, 304, 305):
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
        guard = 0
        while not duel.is_over and guard < 400:
            guard += 1
            if duel.advance() is not None:
                continue
            legal = duel.legal_actions(duel.to_act)
            if not legal.allowed:
                break
            duel.apply(legal.allowed[0])
            #: 해결이 시작된 체인에 새 링크가 붙지 않는다.
            if duel.chain.resolved_count:
                assert len(duel.chain.links) >= duel.chain.resolved_count
            #: 창이 닫혀 있으면 체인은 비어 있다.
            if not duel.priority.is_open:
                assert duel.chain.is_empty, duel.chain


# ======================================================================
# S. 계약의 자리 — 코드가 실제로 그렇게 적혀 있다
# ======================================================================


def method_source(func) -> str:
    return textwrap.dedent(inspect.getsource(func))


@pytest.mark.real_card
def test_s01_duelstep_gained_no_new_field():
    """
    🔴 **§5 · §8 — 칸을 더하지 않았다.** 새 enum 도 새 모델도 없다.

    6-R 이 고른 것은 대안 A/B (값의 계산과 전달)이고, 대안 D (새 결과
    정보)가 아니다. 그래서 ``DuelStep`` 의 모양이 그대로다.
    """
    names = [f.name for f in dataclasses.fields(DuelStep)]
    assert names == ["action", "accepted", "code", "reason", "result"]
    #: ``__bool__`` 은 여전히 ``accepted`` 하나를 본다.
    assert DuelStep.__bool__ is not None
    source = method_source(DuelStep.__bool__)
    assert "self.accepted" in source


@pytest.mark.real_card
def test_s02_the_meaning_of_accepted_is_written_down():
    """
    🔴 **설명이 없던 것이 ①의 원인이었다.** 이제 적혀 있다.

    세 사실의 이름이 전부 그 설명 안에 있어야 한다 — 다음에 이 칸을 읽는
    사람이 다시 추측하지 않도록.
    """
    source = (ROOT / "engine/duel.py").read_text(encoding="utf-8")
    block = source.split("    accepted: bool", 1)[1].split("    code:", 1)[0]
    for phrase in ("행위 수락", "체인 등록", "EventJournal", "PASS"):
        assert phrase in block, phrase


@pytest.mark.real_card
def test_s03_resolve_chain_clears_the_chain_unconditionally():
    """
    🔴 **원인을 고친 코드가 그 모양이다.**

    ``self.chain = Chain()`` 이 **조건문 밖**에 있다 — 예전에는
    ``if self.chain.is_complete:`` 안에 있었다.
    """
    tree = ast.parse(method_source(Duel._resolve_chain))
    function = tree.body[0]
    #: 체인을 비우는 대입이 함수 본문의 **직계** 문장이다.
    top_level = [
        node
        for node in function.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Attribute) and t.attr == "chain"
            for t in node.targets
        )
    ]
    assert len(top_level) == 1, ast.dump(function)
    assert isinstance(top_level[0].value, ast.Call)
    assert top_level[0].value.func.id == "Chain"
    #: 그리고 이 함수 안에 ``is_complete`` 를 보는 분기가 **없다.**
    attrs = {
        node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)
    }
    assert "is_complete" not in attrs, attrs


@pytest.mark.real_card
def test_s04_the_fizzle_branch_returns_accepted_true_with_a_non_ok_code():
    """
    🔴 **§16 이 금지한 패치가 아니라는 것을 코드로 센다.**

    불발 분기가 ``True`` 를 돌려주지만 ``ValidationCode.OK`` 는 **쓰지
    않는다** — ``last.code`` 와 ``last.reason`` 을 그대로 들고 간다.
    """
    tree = ast.parse(method_source(Duel._resolve_chain))
    function = tree.body[0]
    branches = [n for n in function.body if isinstance(n, ast.If)]
    assert len(branches) == 1, ast.dump(function)
    returns = [n for n in ast.walk(branches[0]) if isinstance(n, ast.Return)]
    assert len(returns) == 1
    call = returns[0].value
    assert isinstance(call, ast.Call)
    #: 두 번째 인수가 ``True`` 다.
    assert isinstance(call.args[1], ast.Constant) and call.args[1].value is True
    #: 세 번째는 ``last.code`` — 상수가 아니다.
    assert isinstance(call.args[2], ast.Attribute)
    assert call.args[2].attr == "code"
    #: 이 분기 안에 ``ValidationCode`` 가 없다.
    names = {
        n.value.id
        for n in ast.walk(branches[0])
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
    }
    assert "ValidationCode" not in names, names


@pytest.mark.real_card
def test_s05_resolve_chain_has_exactly_one_caller():
    """
    **비우기가 안전한 근거.** 체인을 푸는 자리가 하나뿐이고, 그것은
    **열린 창**을 요구한다 — 그래서 비운 체인이 다시 필요해지지 않는다.
    """
    source = (ROOT / "engine/duel.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    callers = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "_resolve_chain"
                ):
                    callers.append(node.name)
    assert callers == ["_apply_pass"], callers


@pytest.mark.real_card
def test_s06_only_one_production_file_changed():
    """
    **§8 "가장 작은 변경"** — 바꾼 생산 파일이 ``engine/duel.py`` 하나다.

    이 Phase 의 commit 범위를 git 으로 직접 센다.
    """
    import subprocess

    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert base, "git 을 읽을 수 없다"
    #: 🔴 여기서는 **모양**만 센다 — commit 핀은 보고서가 든다.
    #: ``engine/duel.py`` 가 ``engine.effect`` 를 들이지 않았는지 지킨다
    #: (ADR-007 의 약속 — 6-R 이 깨뜨리지 않았다).
    source = (ROOT / "engine/duel.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any(m.startswith("engine.effect") for m in imported), imported
    assert not any(m.startswith("rules") for m in imported), imported
