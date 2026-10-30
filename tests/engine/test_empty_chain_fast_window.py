"""
Phase 6-AB 보완5 ① — **유발 등록이 끝났지만 체인이 없는 경우의 빠른 효과
기회.**

무엇이 비어 있었나
------------------
보완4 까지 유발 등재 단계는 올바르게 끝났다 — 양측이 ``window_passed`` 에
들어가면 그 기회는 닫혔다. 그런데 **아무도 발동하지 않아 체인이 비어 있으면
판이 곧바로 열린 상태로 돌아갔다.** 실측 (보완5 A):

    상대 포기: priority.window=none holder=None open=False
    🔴 내 허가 = ['end_phase', 'set_spell_trap']
    🔴 END_PHASE 즉시 수락 = True → 페이즈=BATTLE

즉 턴 플레이어가 **빠른 효과 기회 없이** 다음 행동으로 넘어갔다. 상대는 그
자리에서 함정도 속공 마법도 발동할 기회를 받지 못했다.

공식 근거
---------
공식 Fast Effect Timing 도표가 이 자리를 **그림으로** 적어 두었다.

* 상자 A 는 *열린 상태*다 — *"Many actions can ONLY be performed when the
  game state is open (when you're in box A)"*.
* *"Whenever either player performs an action, the game state is no longer
  open."*
* *"If there is no effect that can be triggered."* → 턴 플레이어가 **상자
  B** 로 간다. 즉 **유발할 효과가 없을 때 가는 곳이 열린 상태가 아니라
  상자 B** 다.
* *"If the Turn Player passes."* → 상대가 **상자 C** 로 간다.
* 다시 열리는 조건은 셋이다 — 턴 플레이어가 지나가고, 상대가 되돌려
  지나가고, 체인이 서 있지 않다.

그래서 **"체인이 비었다" 는 "판이 열렸다" 가 아니다.** 이 파일이 재는 것이
그 구분이다.

🔴 **유발 포기를 빠른 효과 포기로 간주하지 않는다**
---------------------------------------------------
``window_passed`` 와 ``priority`` 는 **다른 것을 센다** — 앞은 유발 처리
기회를 끝낸 자리들이고, 뒤는 빠른 효과 · 응답 단계의 우선권이다. 한쪽을
다른 쪽으로 읽으면 "임의 유발을 포기한 사람은 함정도 포기한 것" 이 되는데,
그런 규칙은 어디에도 없다. ``B`` 절이 양쪽을 따로 센다.

🔴 **PASS 세 개는 세 가지 뜻이다**
----------------------------------
``C`` 절이 그것을 센다 — 유발 처리 기회를 지나가는 PASS, 빠른 효과 기회를
지나가는 PASS, 체인을 푸는 PASS. 세 번째만 무엇인가를 해결하고, 어느 것도
페이즈 이동 동의가 아니다 (페이즈를 넘기는 것은 ``END_PHASE`` 이고 그것은
판이 열린 뒤에만 후보가 된다).

여기서 하지 않은 것
-------------------
두 번째 규칙 엔진 · 새 우선권 설계 · 상자 D~F (데미지 스텝 · 체인 중
타이밍의 세부) · 공식 자료에 없는 OCG 비공개 유발 세부. ``B`` 절의 실제
카드 하나(욕망의 선물)로 "빠른 효과가 실제로 실행된다" 까지 가지만, 그것이
스펠 스피드 2 전체를 지원한다는 뜻은 아니다.
"""

from __future__ import annotations

import pytest

from agent.simulation import Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.priority import ResponseWindow
from engine.response import ResponseStep
from engine.validation import ValidationCode
from engine.vocabulary import Phase
from tests.conftest import requires_official_db
from tests.engine.test_bilateral_trigger_order import _bilateral
from tests.engine.test_trigger_normal_path_integration import MINE, THEIRS
from tests.engine.test_trap_activation_free_chain import (
    GIFT_OF_GREED,
    next_turn,
    set_down,
    staged,
)

pytestmark = requires_official_db


# ======================================================================
# 공용 도구 — 전부 실제 엔진 경로를 지난다
# ======================================================================
def _kinds(duel, seat: int):
    return sorted({a.kind.value for a in duel.legal_actions(seat).allowed})


def _refs(duel, seat: int):
    return [
        a.effect_ref
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]


def _fingerprint(duel):
    """판 · 기회 · 우선권을 **한 묶음**으로. 하나라도 움직이면 달라진다."""
    return (
        duel.state.state_hash(),
        duel.state.turn.phase,
        len(duel.chain),
        duel.window_floor,
        duel.chain_floor,
        duel.window_passed,
        frozenset(duel.consumed_events),
        duel.priority.window,
        duel.priority.holder.seat,
        duel.priority.consecutive_passes,
        len(duel.journal.events),
    )


def _decline_triggers(duel):
    """
    유발 처리 기회를 **실제 PASS 로** 지나간다. 빠른 효과 기회는 **남긴다.**

    🔴 ``while priority.is_open`` 으로 돌리지 않는다 — 그러면 새로 열린 빠른
    효과 기회까지 삼켜 버리고, 이 파일이 재려는 자리가 사라진다 (보완5 의
    A-4 측정이 실제로 그 함정에 빠졌다).
    """
    steps = []
    for _ in range(4):
        actor = duel._window_actor()
        if actor is None:
            break
        passing = PlayerAction.passing(actor=actor)
        assert passing in duel.legal_actions(actor).allowed
        steps.append(duel.apply(passing))
    return steps


def _fast_window(repository, **kwargs):
    """유발 등재가 끝나고 **빠른 효과 기회가 열린** 판."""
    duel, chooser = _bilateral(repository, **kwargs)
    _decline_triggers(duel)
    return duel, chooser


# ======================================================================
# A. 기회가 열린다 — 체인이 비어도 판은 열리지 않는다
# ======================================================================
def test_a01_both_decline_opens_a_fast_window(repository):
    """양측이 임의 유발을 포기하면 **빠른 효과 기회**가 열린다."""
    duel, _ = _fast_window(repository)

    assert duel.chain.is_empty
    assert duel.window_passed == frozenset({MINE, THEIRS})
    assert duel.priority.is_open
    assert duel.priority.window is ResponseWindow.RESPONSE
    #: 🔴 쥔 쪽은 **턴 플레이어**다 — 도표의 상자 B 다.
    assert duel.priority.holder.seat == duel.turn_player
    assert duel.to_act == duel.turn_player


def test_a02_the_board_is_not_open(repository):
    """그 자리는 **열린 상태가 아니다** — 페이즈 이동이 수락되지 않는다."""
    duel, _ = _fast_window(repository)

    assert _kinds(duel, MINE) == ["pass"]
    before = duel.state.turn.phase
    step = duel.apply(PlayerAction.end_phase(actor=MINE))
    assert not step.accepted
    assert duel.state.turn.phase is before is Phase.MAIN1


def test_a03_one_sided_trigger_still_opens_both(repository):
    """
    유발 기회가 **한쪽에만** 있었어도 빠른 효과 기회는 양측에 보장된다.

    ①-2 가 요구하는 분리다 — 유발 기회의 수와 빠른 효과 기회의 수는 같지
    않다.
    """
    duel, _ = _fast_window(repository, give_theirs=False)

    #: 유발을 끝낸 자리는 **하나**다.
    assert duel.window_passed == frozenset({MINE})
    #: 그래도 빠른 효과 기회는 열렸고, 턴 플레이어가 쥐었다.
    assert duel.priority.is_open
    assert duel.priority.holder.seat == duel.turn_player
    #: 그리고 상대도 **반드시** 지나가야 한다 (``B`` 절의 ``b02`` · ``b03``).


def test_a04_a_board_action_with_no_trigger_opens_one(repository):
    """
    유발이 **없는** 판 변경 뒤에도 기회가 열린다.

    도표의 *"Whenever either player performs an action, the game state is
    no longer open"* 그대로다 — 유발이 있었는지는 묻지 않는다.
    """
    duel, _ = _fast_window(repository)
    #: 먼저 열린 상태로 돌아간다 (양측이 빠른 효과 기회를 지나간다).
    duel.apply(PlayerAction.passing(actor=MINE))
    duel.apply(PlayerAction.passing(actor=THEIRS))
    assert not duel.priority.is_open

    sets = [
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.SET_SPELL_TRAP
    ]
    assert sets, _kinds(duel, MINE)
    step = duel.apply(sets[0])

    assert step.accepted, step.reason
    assert duel.chain.is_empty
    assert duel.priority.is_open
    assert duel.priority.window is ResponseWindow.RESPONSE
    assert _kinds(duel, MINE) == ["pass"]


def test_a05_after_a_chain_resolves_a_fast_window_follows(repository):
    """
    체인이 풀린 **뒤에도** 유발 확인과 빠른 효과 기회를 거친다 (①-8).

    해결 직후에 유발이 올라오면 그쪽이 먼저다 — 그래서 여기서는 유발
    등재가 열려 있지 않은 것을 먼저 확인하고, 그 다음 기회를 센다.
    """
    duel, _ = _bilateral(repository)
    mine = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    )
    duel.apply(mine)
    theirs = next(
        a
        for a in duel.legal_actions(THEIRS).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    )
    duel.apply(theirs)
    assert len(duel.chain) == 2

    #: 체인을 푼다 — 양쪽이 연속으로 패스한다.
    duel.apply(PlayerAction.passing(actor=duel.priority.holder.seat))
    resolved = duel.apply(PlayerAction.passing(actor=duel.priority.holder.seat))
    assert "해결" in resolved.reason
    assert duel.chain.is_empty
    assert duel.chain.resolved_count == 0  # 새 Chain 으로 바뀌었다

    #: 🔴 **Phase 6-AC 가 이 판에서 유발을 하나 올렸다.** 기르수 ① 이
    #: 묘지로 보낸 카드가 성유물－『성장』 이고 6-AC 가 그 ② 를 등재했다.
    #: 그래서 해결 직후는 **등재 단계**이고, 도표가 그쪽을 먼저라고 적는다
    #: (box D). 이 시험이 재려는 것은 **그 뒤의 빠른 효과 기회**이므로,
    #: 단언을 느슨하게 하지 않고 등재 단계를 **지나는 걸음을 적는다.**
    assert duel._window_actor() == duel.turn_player
    #: 🔴 **양쪽이 지나간다** — 등재 기회는 한 자리의 것이 아니다 (보완4).
    passed = 0
    while (actor := duel._window_actor()) is not None and passed < 4:
        assert duel.apply(PlayerAction.passing(actor=actor)).accepted
        passed += 1
    assert passed == 2, passed
    #: 지난 뒤에는 등재가 남아 있지 않다 (남아 있으면 그쪽이 먼저다).
    assert duel._window_actor() is None
    #: 🔴 그리고 **빠른 효과 기회가 열려 있다** — 열린 상태가 아니다.
    assert duel.priority.is_open
    assert duel.priority.window is ResponseWindow.RESPONSE
    assert _kinds(duel, duel.turn_player) == ["pass"]


# ======================================================================
# B. 그 자리에서 할 수 있는 것 — 그리고 제어권
# ======================================================================
def test_b01_open_state_only_actions_are_withheld(repository):
    """소환 · 세트 · 기동 효과는 **열린 상태 전용**이므로 후보가 아니다 (①-3)."""
    duel, _ = _fast_window(repository)

    kinds = _kinds(duel, MINE)
    assert kinds == ["pass"]
    for forbidden in (
        PlayerActionKind.NORMAL_SUMMON,
        PlayerActionKind.SET_MONSTER,
        PlayerActionKind.SET_SPELL_TRAP,
        PlayerActionKind.END_PHASE,
    ):
        assert forbidden.value not in kinds


def test_b02_turn_player_passing_hands_control_over(repository):
    """턴 플레이어가 포기하면 **실제로** 상대 차례가 된다 (①-4)."""
    duel, _ = _fast_window(repository)
    assert duel.to_act == MINE

    step = duel.apply(PlayerAction.passing(actor=MINE))

    assert step.accepted
    assert step.code is ValidationCode.OK
    assert duel.priority.is_open
    assert duel.priority.holder.seat == THEIRS
    assert duel.to_act == THEIRS
    #: 🔴 **값만 바뀐 것이 아니다** — 허가도 따라 움직인다.
    assert _kinds(duel, THEIRS) == ["pass"]
    assert _kinds(duel, MINE) == []


def test_b03_both_passing_returns_to_the_open_state(repository):
    """양측이 포기한 뒤 판이 다시 열린다 (①-5)."""
    duel, _ = _fast_window(repository)
    duel.apply(PlayerAction.passing(actor=MINE))
    step = duel.apply(PlayerAction.passing(actor=THEIRS))

    assert step.accepted
    assert not duel.priority.is_open
    assert duel.priority.window is ResponseWindow.NONE
    assert duel.chain.is_empty
    #: 열린 상태 전용 행동이 **돌아왔다.**
    assert "end_phase" in _kinds(duel, MINE)
    assert duel.apply(PlayerAction.end_phase(actor=MINE)).accepted
    assert duel.state.turn.phase is Phase.BATTLE


def test_b04_a_real_set_trap_becomes_a_candidate(repository):
    """
    🔴 **실제 카드다** — 욕망의 선물(5915629)을 세우고 **다음 턴**에 판을
    바꾸면, 그때 열린 빠른 효과 기회에 그 함정이 후보로 오른다 (①-7 앞쪽).

    세트한 턴 제약은 그대로 지나간다 (``RULE-SPELLTRAP-009``) — 그래서
    :func:`next_turn` 으로 턴을 넘긴 뒤에 본다.
    """
    duel, sources, _ = staged(repository, mine=[GIFT_OF_GREED], fodder=3,
                              their_hand=2)
    set_down(duel, sources[0])
    next_turn(duel, to_seat=MINE)

    sets = [
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.SET_MONSTER
    ]
    assert sets
    assert duel.apply(sets[0]).accepted
    assert duel.priority.is_open

    refs = _refs(duel, MINE)
    assert any(ref.card_id == GIFT_OF_GREED for ref in refs), refs
    #: 그리고 **PASS 와 발동 둘뿐**이다 — 열린 상태 전용 행동은 없다.
    assert _kinds(duel, MINE) == ["activate_effect", "pass"]


def test_b05_the_real_trap_runs_the_normal_chain_path(repository):
    """
    그 발동이 **정상 체인 경로**로 가고 **실제 상태를 바꾼다** (①-7 뒤쪽).

    🔴 우선권 값이 움직인 것을 실행 성공으로 적지 않는다 — 재는 것은 상대
    패의 장수다 (욕망의 선물: *상대는 2장 드로우한다*).
    """
    duel, sources, _ = staged(repository, mine=[GIFT_OF_GREED], fodder=3,
                              their_hand=2)
    set_down(duel, sources[0])
    next_turn(duel, to_seat=MINE)
    sets = [
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.SET_MONSTER
    ]
    duel.apply(sets[0])

    their_hand = len([c for c in duel.state.player(THEIRS).hand if c])
    activation = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and a.effect_ref.card_id == GIFT_OF_GREED
    )
    step = duel.apply(activation)

    #: 체인이 서고 **상대의 응답 기회**가 열린다 (RULE-CHAIN-001).
    assert step.accepted, step.reason
    assert len(duel.chain) == 1
    assert duel.chain.links[0].effect_ref.card_id == GIFT_OF_GREED
    assert duel.priority.holder.seat == THEIRS

    #: 양쪽이 패스하면 풀린다.
    duel.apply(PlayerAction.passing(actor=THEIRS))
    resolved = duel.apply(PlayerAction.passing(actor=MINE))
    assert resolved.accepted
    assert "해결" in resolved.reason
    assert duel.chain.is_empty

    #: 🔴 **실제 변화** — 상대 패가 2장 늘었다.
    assert len([c for c in duel.state.player(THEIRS).hand if c]) == their_hand + 2

    #: 그 뒤에도 빠른 효과 기회를 거쳐 열린 상태로 돌아간다.
    assert duel.priority.is_open
    duel.apply(PlayerAction.passing(actor=duel.priority.holder.seat))
    duel.apply(PlayerAction.passing(actor=duel.priority.holder.seat))
    assert not duel.priority.is_open
    assert "end_phase" in _kinds(duel, MINE)


# ======================================================================
# C. PASS 세 개가 섞이지 않는다 (①-6)
# ======================================================================
def test_c01_this_window_has_no_chain_to_resolve(repository):
    """
    이 자리의 응답 단계는 ``NO_CHAIN`` 이고 ``ready_to_resolve`` 는 거절이다.

    즉 **여기서 PASS 가 풀 것이 없다** — 같은 PASS 가 체인 해결 PASS 로
    재사용되지 않는 이유가 그것이다.
    """
    duel, _ = _fast_window(repository)
    response = duel._response_state()

    assert response.step is ResponseStep.NO_CHAIN
    verdict = duel._response_loop.ready_to_resolve(response)
    assert not verdict.permits_execution
    assert verdict.code is ValidationCode.CHAIN_EMPTY


def test_c02_this_pass_is_not_a_phase_change_consent(repository):
    """창은 ``PHASE_CHANGE`` 가 아니고, 이 PASS 는 페이즈를 움직이지 않는다."""
    duel, _ = _fast_window(repository)
    before = duel.state.turn.phase

    assert duel.priority.window is not ResponseWindow.PHASE_CHANGE
    duel.apply(PlayerAction.passing(actor=MINE))
    assert duel.state.turn.phase is before
    duel.apply(PlayerAction.passing(actor=THEIRS))
    assert duel.state.turn.phase is before


def test_c03_the_three_passes_say_three_different_things(repository):
    """세 PASS 의 **이유 문장**이 서로 다르다 — 사람도 로그도 구별한다."""
    duel, _ = _bilateral(repository)

    #: ① 유발 처리 기회를 지나가는 PASS
    trigger_pass = duel.apply(PlayerAction.passing(actor=MINE))
    assert "유발" in trigger_pass.reason
    assert "해결" not in trigger_pass.reason
    duel.apply(PlayerAction.passing(actor=THEIRS))

    #: ② 빠른 효과 기회를 지나가는 PASS
    fast_pass = duel.apply(PlayerAction.passing(actor=MINE))
    assert "빠른 효과" in fast_pass.reason
    assert "해결" not in fast_pass.reason
    closing = duel.apply(PlayerAction.passing(actor=THEIRS))
    assert "빠른 효과" in closing.reason and "열렸" in closing.reason

    #: ③ 체인을 푸는 PASS — 체인을 세워야 나온다.
    duel2, _ = _bilateral(repository)
    duel2.apply(
        next(
            a
            for a in duel2.legal_actions(MINE).allowed
            if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        )
    )
    #: 🔴 상대의 **유발 등재**가 아직 열려 있다 — 그쪽이 먼저다. 그 자리의
    #: PASS 는 ①의 뜻이고, 그래서 우선권은 아직 아무도 쥐지 않았다.
    assert not duel2.priority.is_open
    assert duel2._window_actor() == THEIRS
    duel2.apply(PlayerAction.passing(actor=THEIRS))

    #: 이제 체인에 대한 응답 차례다.
    assert duel2.priority.is_open
    assert not duel2.chain.is_empty
    duel2.apply(PlayerAction.passing(actor=duel2.priority.holder.seat))
    chain_pass = duel2.apply(
        PlayerAction.passing(actor=duel2.priority.holder.seat)
    )
    assert "해결" in chain_pass.reason
    assert "빠른 효과" not in chain_pass.reason


# ======================================================================
# D. 종료된 기회가 되살아나지 않는다 (①-9)
# ======================================================================
def test_d01_a_finished_trigger_chance_is_gone_in_the_fast_window(repository):
    """빠른 효과 단계에 **끝난 유발**이 다시 후보로 오르지 않는다."""
    duel, _ = _bilateral(repository)
    before = _refs(duel, MINE)
    assert before, "유발 후보가 처음에는 있어야 이 시험이 뜻을 가진다"

    _decline_triggers(duel)

    assert duel.priority.is_open
    assert _refs(duel, MINE) == []
    assert _refs(duel, THEIRS) == []


def test_d02_and_it_is_still_gone_after_the_board_reopens(repository):
    """열린 상태로 돌아간 뒤에도 없다."""
    duel, _ = _fast_window(repository)
    duel.apply(PlayerAction.passing(actor=MINE))
    duel.apply(PlayerAction.passing(actor=THEIRS))

    assert not duel.priority.is_open
    assert _refs(duel, MINE) == []
    assert _refs(duel, THEIRS) == []


# ======================================================================
# E. 묻기와 거절은 아무것도 소비하지 않는다 (①-10)
# ======================================================================
def test_e01_repeated_queries_change_nothing(repository):
    """후보를 **몇 번 물어도** 판 · 기회 · 우선권이 그대로다."""
    duel, _ = _fast_window(repository)
    before = _fingerprint(duel)

    for _ in range(5):
        duel.legal_actions(MINE)
        duel.legal_actions(THEIRS)

    assert _fingerprint(duel) == before


def test_e02_refusals_do_not_pass_or_move_priority(repository):
    """불법 행동의 **거절**이 포기나 우선권 이동을 만들지 않는다."""
    duel, _ = _fast_window(repository)
    before = _fingerprint(duel)

    for action in (
        PlayerAction.end_phase(actor=MINE),
        PlayerAction.end_phase(actor=THEIRS),
        #: 🔴 **쥐지 않은 쪽의 PASS** — 이것이 통하면 제어권이 거꾸로 돈다.
        PlayerAction.passing(actor=THEIRS),
    ):
        step = duel.apply(action)
        assert not step.accepted, action
        assert _fingerprint(duel) == before, action

    #: 거절 뒤에도 쥔 쪽은 그대로이고 포기 수도 그대로다.
    assert duel.priority.holder.seat == MINE
    assert duel.priority.consecutive_passes == 0


# ======================================================================
# F. 사본 — 새 단계도 원본과 섞이지 않는다
# ======================================================================
def test_f01_a_fork_sees_the_same_stage(repository):
    """사본이 **같은 단계 · 같은 차례 · 같은 후보**를 본다."""
    duel, _ = _fast_window(repository)
    fork = Simulator(duel=duel)._fork()

    assert fork.priority.window is duel.priority.window
    assert fork.priority.holder.seat == duel.priority.holder.seat
    assert fork.to_act == duel.to_act
    assert fork.window_passed == duel.window_passed
    assert _kinds(fork, MINE) == _kinds(duel, MINE)
    assert _kinds(fork, THEIRS) == _kinds(duel, THEIRS)


def test_f02_a_forks_pass_does_not_touch_the_original(repository):
    """사본에서 지나가도 **원본의 기회는 그대로**다."""
    duel, _ = _fast_window(repository)
    before = _fingerprint(duel)
    fork = Simulator(duel=duel)._fork()

    assert fork.apply(PlayerAction.passing(actor=MINE)).accepted
    assert fork.priority.holder.seat == THEIRS
    assert fork.apply(PlayerAction.passing(actor=THEIRS)).accepted
    assert not fork.priority.is_open

    #: 🔴 원본은 **한 글자도** 달라지지 않았다.
    assert _fingerprint(duel) == before
    assert duel.priority.is_open
    assert duel.priority.holder.seat == MINE
