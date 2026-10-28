"""
Phase 6-AB 보완6 ① — **빈 체인의 빠른 효과 기회에서 열린 상태 전용 발동 차단.**

보완5 가 열어 둔 구멍
---------------------
보완5 는 공식 Fast Effect Timing 도표의 상자 B · C 를 엔진에 실었다 —
판을 바꾸는 행위 뒤에는 체인이 비어 있어도 양측의 빠른 효과 기회를 거쳐야
한다. 그 자리에서 **열린 상태 전용 행동은 후보가 되지 않는다**는 것도
함께 실었다 (소환 · 세트 · 페이즈 이동).

🔴 **그런데 발동은 막지 않았다.** 정상 ``legal_actions`` → ``Duel.apply``
경로로 재현한 실측 (보완6 §2):

    몬스터 세트 accepted=True
    → priority.window=RESPONSE holder=0 chain=0
    🔴 욕망의 항아리(55144522, **통상 마법**) 후보 1건
    🔴 Duel.apply accepted=True code=OK → 체인 링크 1개
    🔴 어니스트(37742478:e[0], **기동 효과**) 도 같다

도표가 그것을 금지한다: *"Many actions can ONLY be performed when the game
state is open (when you're in box A)."* 상자 B · C 에서 발동할 수 있는
것은 **스펠 스피드 2 이상**이다.

왜 "체인이 비었다" 로는 판정할 수 없었나
----------------------------------------
``ActivationTimingChecker`` 는 *"체인이 비어 있으면 스펠 스피드 제약이
걸리지 않는다"* 로 이른 통과를 했고, **보완5 까지 그 말이 맞았다** —
체인이 비어 있다는 것이 곧 판이 열려 있다는 뜻이었기 때문이다. 보완5 가
그 등식을 깼다.

체인이 비어 있는 자리가 **셋**이고 셋의 답이 다르다.

====================================  ==================================
:attr:`ActivationStage.OPEN`          스펠 스피드 1 도 발동할 수 있다
:attr:`ActivationStage.               유발은 대개 스펠 스피드 1 이므로
TRIGGER_REGISTRATION`                 **막으면 유발이 발동되지 않는다**
:attr:`ActivationStage.FAST_WINDOW`   스펠 스피드 2 이상만
====================================  ==================================

그래서 보완6 은 **단계를 값으로 넘긴다** — ``point`` · ``set_this_turn`` ·
``simultaneous`` 와 같은 자리다 (ADR-007). 아는 쪽은 판을 들고 있는
:meth:`~engine.duel.Duel._activation_stage` 이고, 판정하는 쪽은 **기존
관문 하나** 그대로다 (새 규칙 엔진을 만들지 않았다 —
``test_activation_timing.test_f_no_second_timing_system_was_built``).

여기서 하지 않은 것
-------------------
"스펠 스피드 1 은 무조건 금지" 로 고치는 것 (유발 등재까지 막힌다) ·
후보 목록에서만 숨기는 것 (직접 ``apply`` 가 통한다) · 카드 ID 별 예외 ·
상자 D~F (데미지 스텝 세부) · 새 소환 기능.
"""

from __future__ import annotations

import pytest

from agent.simulation import Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.activation_timing import ActivationStage
from engine.duel import Duel, duel_components
from engine.ids import EffectRef
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

#: 실제 기동 효과 — 어니스트 ①. ``EFFECT_TYPE_IGNITION`` +
#: ``SetRange(LOCATION_MZONE)`` 이고 대상이 없다 (``c37742478.lua``).
HONEST = 37742478
HONEST_REF = EffectRef(HONEST, 0)
POT_REF = EffectRef(POT_OF_GREED, 0)


# ======================================================================
# 공용 도구
# ======================================================================
def _kinds(duel, seat: int = P0):
    return sorted({a.kind.value for a in duel.legal_actions(seat).allowed})


def _activations(duel, seat: int = P0, card_id: int | None = None):
    return [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and (card_id is None or a.effect_ref.card_id == card_id)
    ]


def _fingerprint(duel):
    """판 · 체인 · 우선권 · 기록 · 소비를 **한 묶음**으로."""
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
    )


def _gate(duel, action, seat: int = P0):
    """후보를 만든 **그 관문**에 직접 묻는다 (``legal_actions`` 가 쓰는 것)."""
    offers = duel._trigger_offers(seat)
    return duel._activation_gate(
        action,
        validator=duel.activation_validator(seat, offers),
        selections=action.targets,
    )


def _into_fast_window(duel, seat: int = P0):
    """
    **실제 행위로** 빠른 효과 기회에 들어간다 — 몬스터 세트 하나.

    🔴 손으로 우선권을 돌리지 않는다. 판을 바꾸는 행위 뒤에 기회가 열리는
    것이 보완5 가 실은 규칙이고, 이 도구는 그 규칙을 지난다.
    """
    sets = [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.SET_MONSTER
    ]
    assert sets, _kinds(duel, seat)
    step = duel.apply(sets[0])
    assert step.accepted, step.reason
    assert duel.chain.is_empty
    assert duel._activation_stage() is ActivationStage.FAST_WINDOW
    return step


def _honest_board(repository, *, my_hand=(LUSTER_DRAGON, LUSTER_DRAGON)):
    """
    어니스트가 **앞면으로 내 몬스터 존에 있는** 판.

    🔴 초기 판 구성이다 — 실행 중에 상태를 주입하는 것이 아니다. 이 뒤의
    모든 변화는 ``Duel.apply`` 가 만든다.

    🔴 **왜 손으로 두는가.** 등재된 기동 효과는 ``EFFECT_LIBRARY`` 에 하나
    뿐이고 (``37742478:e[0]``), 그 카드를 필드에 내놓는 소환 경로는 이
    범위가 아니다. 두는 것은 **시작 판**뿐이고 허가도 상태 변경도 주입하지
    않는다 — ``C`` 절이 열린 상태에서 **실제로 발동되고 해결되는 것**을
    먼저 센다.
    """
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [LUSTER_DRAGON] * 30),
        turn_player=P0,
        seed=1,
    )
    card = state.create_instance(HONEST, owner=P0, zone=Zone.MZONE)
    state.move(card, Zone.MZONE, to_player=P0, position=Position.FACEUP_ATTACK)
    for card_id in my_hand:
        state.create_instance(card_id, owner=P0, zone=Zone.HAND)
    state.turn.turn_number = 5
    state.turn.turn_player = P0
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(),
    )
    return duel, card.instance_id


# ======================================================================
# A. 단계 판정 — 네 갈래가 실제 행위에서 나온다
# ======================================================================
def test_a01_the_stage_follows_the_real_flow(repository):
    """``_activation_stage`` 의 네 갈래가 **실제 경로**에서 차례로 나온다."""
    duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=2)

    #: ① 열린 상태
    assert duel._activation_stage() is ActivationStage.OPEN

    #: ② 판을 바꾸면 빠른 효과 기회
    _into_fast_window(duel)
    assert duel._activation_stage() is ActivationStage.FAST_WINDOW

    #: ③ 양측이 지나가면 다시 열린다
    pass_fast_window(duel)
    assert duel._activation_stage() is ActivationStage.OPEN

    #: ④ 체인이 쌓이면 응답 단계
    duel.apply(_activations(duel, P0, POT_OF_GREED)[0])
    assert len(duel.chain) == 1
    assert duel._activation_stage() is ActivationStage.CHAIN_RESPONSE


def test_a02_the_trigger_registration_stage_is_its_own(repository):
    """유발 등재 단계는 **열린 상태도 빠른 효과 기회도 아니다**."""
    from tests.engine.test_bilateral_trigger_order import _bilateral

    duel, _ = _bilateral(repository)

    assert duel.chain.is_empty
    assert not duel.priority.is_open
    assert duel._activation_stage() is ActivationStage.TRIGGER_REGISTRATION


def test_a03_the_stage_is_computed_without_the_gate(repository):
    """
    🔴 **단계 계산이 관문을 지나지 않는다.**

    보완6 이 처음에 :meth:`~engine.duel.Duel._registration_is_open` 으로
    물었고, 그쪽이 ``_window_actor`` → ``_window_can_act`` → 관문을 지나므로
    **재귀가 났다** (실측: ``RecursionError``). 관문의 입력을 관문으로
    구하면 그렇게 된다.

    그래서 ``_window_claims`` (관문을 돌리지 않는다) 로 묻는다. 이 시험은
    강제 묶음이 있는 판 — 즉 ``_window_can_act`` 가 관문을 **실제로**
    돌리는 판 — 에서 단계를 묻고 터지지 않는 것을 센다.
    """
    from engine.trigger import TriggerRequirement
    from tests.engine.test_bilateral_trigger_order import _bilateral

    duel, _ = _bilateral(repository, theirs=TriggerRequirement.MANDATORY)

    #: 관문을 돌리는 자리가 살아 있다 (이것이 없으면 재귀가 재현되지 않는다).
    assert duel._window_actor() == P1
    assert duel._duty_seat() == P1
    #: 그리고 단계를 물어도 터지지 않는다.
    assert duel._activation_stage() is ActivationStage.TRIGGER_REGISTRATION


# ======================================================================
# B. 통상 마법 — 열린 상태에서는 되고 빠른 효과 기회에서는 안 된다
# ======================================================================
def test_b01_a_normal_spell_is_allowed_while_the_board_is_open(repository):
    """
    🔴 **먼저 열린 상태에서 실제로 허용됨을 확인한다.**

    이것을 확인하지 않으면 뒤의 차단 시험은 "원래 후보가 없었다" 와
    구별되지 않는다.
    """
    duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=2)

    offered = _activations(duel, P0, POT_OF_GREED)
    assert offered, duel.legal_actions(P0).withheld
    assert _gate(duel, offered[0]).validity is ActionValidity.VALID

    deck_before = len([c for c in duel.state.player(P0).zone(Zone.DECK) if c])
    assert duel.apply(offered[0]).accepted
    assert len(duel.chain) == 1
    duel.apply(PlayerAction.passing(actor=P1))
    resolved = duel.apply(PlayerAction.passing(actor=P0))
    assert "해결" in resolved.reason
    #: 욕망의 항아리는 2장 드로우다 — **실제 변화**를 센다.
    assert (
        len([c for c in duel.state.player(P0).zone(Zone.DECK) if c])
        == deck_before - 2
    )


def test_b02_a_normal_spell_is_not_a_candidate_in_the_fast_window(repository):
    """같은 판 · 같은 카드인데 빠른 효과 기회에서는 후보가 아니다."""
    duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=2)
    assert _activations(duel, P0, POT_OF_GREED)

    _into_fast_window(duel)

    assert _activations(duel, P0, POT_OF_GREED) == []
    assert _kinds(duel, P0) == ["pass"]


def test_b03_and_a_direct_apply_is_refused_by_the_rule(repository):
    """
    🔴 **후보 목록에서 숨기는 것으로 끝내지 않는다** — 직접 넣어도 거절이고,
    거절의 **코드가 규칙**이다.

    ``RULE_NOT_IMPLEMENTED``("이 저장소가 그 규칙을 모른다") 가 아니라
    ``SPELL_SPEED_TOO_LOW`` 다. 그 둘을 섞으면 ``/combo`` 가 규칙이 막은
    발동을 "엔진 미지원" 으로 적는다 (``F`` 절이 센다).
    """
    duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=2)
    action = _activations(duel, P0, POT_OF_GREED)[0]
    _into_fast_window(duel)

    before = _fingerprint(duel)
    step = duel.apply(action)

    assert step.accepted is False
    assert step.code is ValidationCode.SPELL_SPEED_TOO_LOW
    assert "판이 열려 있지 않아" in step.reason
    assert "스펠 스피드 1" in step.reason
    #: 🔴 거절은 **아무것도 바꾸지 않는다.**
    assert _fingerprint(duel) == before


def test_b04_the_candidate_gate_and_the_direct_apply_agree(repository):
    """
    후보를 만든 관문과 ``apply`` 의 거절이 **같은 판정**이다 (같은 코드 ·
    같은 이유). 둘이 갈라지면 "목록에 없으니 안전하다" 에 기대게 된다.
    """
    duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=2)
    action = _activations(duel, P0, POT_OF_GREED)[0]
    _into_fast_window(duel)

    verdict = _gate(duel, action)
    step = duel.apply(action)

    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is step.code is ValidationCode.SPELL_SPEED_TOO_LOW
    assert verdict.reason == step.reason
    #: 🔴 그리고 **"모자란 규칙" 이 아니다** — 규칙이 막은 것이다.
    assert verdict.missing_rule is None


def test_b05_after_both_pass_it_is_allowed_again(repository):
    """양측이 그 기회를 지나가면 **같은 발동이 다시 허용된다**."""
    duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=2)
    action = _activations(duel, P0, POT_OF_GREED)[0]
    _into_fast_window(duel)
    assert duel.apply(action).accepted is False

    pass_fast_window(duel)

    assert duel._activation_stage() is ActivationStage.OPEN
    assert _activations(duel, P0, POT_OF_GREED)
    assert duel.apply(action).accepted is True
    assert len(duel.chain) == 1


# ======================================================================
# C. 기동 효과 — **별도로** 확인한다
# ======================================================================
def test_c01_an_ignition_effect_is_allowed_while_the_board_is_open(repository):
    """
    🔴 **기동 효과를 통상 마법과 따로 센다.** 한쪽이 재현됐다는 이유로
    다른 쪽까지 재현됐다고 보지 않는다.

    실제 카드 어니스트 ① (``EFFECT_TYPE_IGNITION``) 이 열린 상태에서
    발동되고 **해결까지** 된다 — 그 카드가 패로 돌아간다.
    """
    duel, honest = _honest_board(repository)

    assert duel._activation_stage() is ActivationStage.OPEN
    offered = _activations(duel, P0, HONEST)
    assert offered, duel.legal_actions(P0).withheld
    assert offered[0].effect_ref == HONEST_REF

    assert duel.apply(offered[0]).accepted
    duel.apply(PlayerAction.passing(actor=P1))
    resolved = duel.apply(PlayerAction.passing(actor=P0))
    assert "해결" in resolved.reason

    #: **실제 변화** — 몬스터 존에서 패로 갔다.
    assert [c.card_id for c in duel.state.player(P0).zone(Zone.MZONE) if c] == []
    assert HONEST in [c.card_id for c in duel.state.player(P0).hand if c]


def test_c02_an_ignition_effect_is_blocked_in_the_fast_window(repository):
    """
    그 기동 효과가 빠른 효과 기회에서는 후보도 아니고 ``apply`` 도 거절이다.

    🔴 **그러나 거절의 코드가 통상 마법과 다르다 — 그 사실을 적어 둔다.**

    통상 마법은 ``INVALID`` / ``SPELL_SPEED_TOO_LOW`` 로 막힌다 (``B`` 절).
    기동 효과는 ``UNKNOWN`` / ``RULE_NOT_IMPLEMENTED`` 로 막힌다. 이유는
    **스펠 스피드를 판정하지 못하기 때문**이다 — 실측:

        발동하려는 카드의 스펠 스피드를 판정할 수 없습니다 (몬스터 효과).
        missing = monster effect classification
                  (기동 · 유발 · 플립 vs 유발즉시)

    즉 이 자리에서 막는 것은 *"판이 열려 있지 않다"* 가 아니라 *"이 몬스터
    효과가 빠른 효과인지 모른다"* 이고, **모름은 허가가 아니므로** 결과적으로
    막힌다. 차단은 성립하고 **코드의 구분은 성립하지 않는다.**

    🔴 **고칠 정보는 이 저장소에 있다** — 그 정의의 ``activation_kind`` 가
    ``IGNITION`` 이고, 모자란 축의 이름이 바로 그 구분이다. 다만 그 축은
    ``MONSTER_CLASSIFICATION_MISSING`` 으로 저장소 전체가 쓰는 자리이므로
    보완6 이 건드리지 않았다 (보고서 BLOCKER-F6-1).
    """
    duel, honest = _honest_board(repository)
    action = _activations(duel, P0, HONEST)[0]

    _into_fast_window(duel)

    #: ① 차단은 성립한다 — 후보가 아니다.
    assert _activations(duel, P0, HONEST) == []
    assert _kinds(duel, P0) == ["pass"]

    #: ② 직접 넣어도 거절이고 **아무것도 바뀌지 않는다.**
    before = _fingerprint(duel)
    step = duel.apply(action)
    assert step.accepted is False
    assert _fingerprint(duel) == before

    #: ③ 🔴 그러나 코드는 규칙 거절이 아니라 **모름**이다.
    from engine.activation_timing import MONSTER_CLASSIFICATION_MISSING

    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    verdict = _gate(duel, action)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == MONSTER_CLASSIFICATION_MISSING
    #: 🔴 그리고 그 모름은 **보완6 이 만든 것이 아니다** — 판이 열려 있어도
    #: 같은 축이 모자라고, 거기서는 다른 관문이 통과시킨다 (``c01``).

    #: ④ 지나가면 다시 허용된다 — 막은 것이 단계였음을 그것이 말한다.
    pass_fast_window(duel)
    assert _activations(duel, P0, HONEST)
    assert duel.apply(action).accepted is True


# ======================================================================
# D. 허용되는 빠른 효과는 **그대로** 허용된다
# ======================================================================
def test_d01_a_real_set_trap_still_works_in_the_fast_window(repository):
    """
    🔴 실제 카드 욕망의 선물(5915629)이 그 기회에서 발동 · 해결되고 판을
    바꾼다 — 보완6 이 좁힌 것은 **스펠 스피드 1** 뿐이다.
    """
    duel, sources, _ = staged(
        repository, mine=[GIFT_OF_GREED], fodder=3, their_hand=2
    )
    set_down(duel, sources[0])
    next_turn(duel, to_seat=P0)
    _into_fast_window(duel)

    offered = _activations(duel, P0, GIFT_OF_GREED)
    assert offered, duel.legal_actions(P0).withheld
    assert _kinds(duel, P0) == ["activate_effect", "pass"]

    their_hand = len([c for c in duel.state.player(P1).hand if c])
    assert duel.apply(offered[0]).accepted
    assert len(duel.chain) == 1
    duel.apply(PlayerAction.passing(actor=P1))
    resolved = duel.apply(PlayerAction.passing(actor=P0))

    assert "해결" in resolved.reason
    assert len([c for c in duel.state.player(P1).hand if c]) == their_hand + 2


def test_d02_an_ss1_trigger_still_registers(repository):
    """
    🔴 **유발 등재를 막지 않았다.** "스펠 스피드 1 은 무조건 금지" 로 고치면
    유발 효과가 발동되지 않는다 — 기르수 ①은 몬스터 효과(스펠 스피드 1)다.
    """
    from tests.engine.test_bilateral_trigger_order import _bilateral

    duel, _ = _bilateral(repository)
    assert duel._activation_stage() is ActivationStage.TRIGGER_REGISTRATION

    offered = _activations(duel, P0)
    assert offered, duel.legal_actions(P0).withheld
    step = duel.apply(offered[0])
    assert step.accepted is True
    assert step.code is ValidationCode.OK
    assert len(duel.chain) == 1


def test_d03_two_triggers_of_one_opportunity_keep_their_order(repository):
    """같은 기회의 복수 등재와 **묶음 안의 순서**가 그대로다."""
    from tests.engine.test_trigger_window_completion import (
        REAL_REF,
        SYNTH_REF,
        _paired_board,
    )

    duel, _ = _paired_board(repository)
    assert duel._activation_stage() is ActivationStage.TRIGGER_REGISTRATION

    first = next(a for a in _activations(duel, P0) if a.effect_ref == SYNTH_REF)
    assert duel.apply(first).accepted
    second = next(a for a in _activations(duel, P0) if a.effect_ref == REAL_REF)
    assert duel.apply(second).accepted

    assert [l.effect_ref for l in duel.chain.links] == [SYNTH_REF, REAL_REF]


def test_d04_the_chain_response_constraint_is_untouched(repository):
    """
    체인이 쌓여 있을 때의 기존 스펠 스피드 제약이 **한 줄도 바뀌지 않았다** —
    이유 문장도 예전 것이다.
    """
    duel, sources, _ = staged(
        repository, mine=[POT_OF_GREED, POT_OF_GREED], fodder=1
    )
    assert duel.apply(_activations(duel, P0, POT_OF_GREED)[0]).accepted
    assert duel._activation_stage() is ActivationStage.CHAIN_RESPONSE

    assert _activations(duel, P0, POT_OF_GREED) == []
    step = duel.apply(
        PlayerAction.activate_effect(
            actor=P0, source=sources[1], effect_ref=POT_REF
        )
    )
    assert step.accepted is False
    assert step.code is ValidationCode.SPELL_SPEED_TOO_LOW
    #: 🔴 **빠른 효과 기회의 문장이 아니다** — 다른 규칙이므로 다른 말이다.
    assert "어떤 효과에도 응수할 수 없습니다" in step.reason
    assert "판이 열려 있지 않아" not in step.reason


def test_d05_the_same_limit_holds_after_a_chain_resolves(repository):
    """체인이 풀린 뒤 열리는 **새 기회**에서도 같은 제한이다."""
    duel, sources, _ = staged(
        repository, mine=[POT_OF_GREED, POT_OF_GREED], fodder=1
    )
    duel.apply(_activations(duel, P0, POT_OF_GREED)[0])
    duel.apply(PlayerAction.passing(actor=P1))
    resolved = duel.apply(PlayerAction.passing(actor=P0))
    assert "해결" in resolved.reason

    assert duel._activation_stage() is ActivationStage.FAST_WINDOW
    assert _activations(duel, P0, POT_OF_GREED) == []
    assert _kinds(duel, P0) == ["pass"]

    pass_fast_window(duel)
    assert duel._activation_stage() is ActivationStage.OPEN
    assert _activations(duel, P0, POT_OF_GREED)


# ======================================================================
# E. 원본 · 사본
# ======================================================================
def test_e01_a_fork_sees_the_same_stage_and_the_same_candidates(repository):
    """사본의 **단계**와 합법 후보가 원본과 같다."""
    duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=2)
    action = _activations(duel, P0, POT_OF_GREED)[0]
    _into_fast_window(duel)
    fork = Simulator(duel=duel)._fork()

    assert fork._activation_stage() is duel._activation_stage()
    assert _kinds(fork, P0) == _kinds(duel, P0)
    assert _activations(fork, P0) == _activations(duel, P0)
    #: 직접 적용의 판정도 같다.
    mine, theirs = duel.apply(action), fork.apply(action)
    assert (mine.accepted, mine.code) == (theirs.accepted, theirs.code)


def test_e02_a_forks_pass_does_not_reopen_the_parent(repository):
    """사본이 그 기회를 지나가도 **원본의 단계는 그대로**다."""
    duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=2)
    _into_fast_window(duel)
    before = _fingerprint(duel)
    fork = Simulator(duel=duel)._fork()

    pass_fast_window(fork)
    assert fork._activation_stage() is ActivationStage.OPEN
    assert _activations(fork, P0, POT_OF_GREED)

    assert _fingerprint(duel) == before
    assert duel._activation_stage() is ActivationStage.FAST_WINDOW
    assert _activations(duel, P0, POT_OF_GREED) == []


# ======================================================================
# F. 보고 계층 — 규칙이 막은 것을 "미지원" 으로 적지 않는다
# ======================================================================
def test_f01_a_rule_refusal_is_not_reported_as_unsupported(repository):
    """
    🔴 규칙이 막은 발동이 ``unsupported()`` 에 들어가지 않는다.

    들어가면 ``/combo`` 가 *"엔진이 그 수단을 모른다"* 로 적고, 사람은
    그것을 고쳐야 할 공백으로 읽는다. 공백이 아니라 **규칙**이다.
    """
    duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=2)
    _into_fast_window(duel)

    legal = duel.legal_actions(P0)
    missing = [w.missing for w in legal.unsupported()]
    #: 스펠 스피드 때문에 막힌 것이 "모자란 규칙" 으로 올라오지 않는다.
    assert not any("spell" in (m or "").lower() for m in missing), missing
    assert not any(
        w.kind is PlayerActionKind.ACTIVATE_EFFECT for w in legal.unsupported()
    ), legal.unsupported()


def test_f02_the_three_outcomes_carry_three_different_codes(repository):
    """
    🔴 **세 사실이 섞이지 않는다** (§3-10).

    ================================  ==================================
    규칙이 막는다                      ``INVALID`` / ``SPELL_SPEED_TOO_LOW``
    단계를 알려주지 않았다              ``UNKNOWN`` / ``INFORMATION_UNAVAILABLE``
    통과했다                          ``VALID`` / ``OK``
    ================================  ==================================

    가운데 갈래는 ``ActivationTimingChecker`` 단위로 센다 — 생산 경로는
    단계를 반드시 넘기므로 (``G`` 절) 그 자리로는 닿지 않는다.
    """
    from engine.activation_timing import (
        STAGE_MISSING,
        ActivationTiming,
        ActivationTimingChecker,
    )

    duel, sources, _ = staged(repository, mine=[POT_OF_GREED], fodder=2)
    action = _activations(duel, P0, POT_OF_GREED)[0]
    checker = ActivationTimingChecker(duel.view(P0))

    blocked = checker.check(
        ActivationTiming(
            duel.chain, duel.priority, stage=ActivationStage.FAST_WINDOW
        ),
        action,
    )
    assert blocked.validity is ActionValidity.INVALID
    assert blocked.code is ValidationCode.SPELL_SPEED_TOO_LOW
    assert blocked.missing_rule is None

    silent = checker.check(
        ActivationTiming(duel.chain, duel.priority), action
    )
    assert silent.validity is ActionValidity.UNKNOWN
    assert silent.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert silent.missing_rule == STAGE_MISSING

    opened = checker.check(
        ActivationTiming(duel.chain, duel.priority, stage=ActivationStage.OPEN),
        action,
    )
    assert opened.validity is ActionValidity.VALID
    assert opened.code is ValidationCode.OK


# ======================================================================
# G. 단계를 누가 책임지는가
# ======================================================================
def test_g01_the_production_gate_always_receives_a_stage():
    """
    🔴 **생산 경로는 단계를 반드시 넘긴다.** 넘기지 않으면 모든 발동이
    ``UNKNOWN`` 이 되므로, 그 자리를 구문으로 못박는다.

    ``engine/duel.py`` 의 ``ActivationTiming(`` 는 한 자리이고 그 자리가
    ``stage=`` 를 넘긴다.
    """
    import ast
    import pathlib

    source = pathlib.Path("engine/duel.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    built = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ActivationTiming"
    ]
    assert len(built) == 1, len(built)
    assert "stage" in {kw.arg for kw in built[0].keywords}


def test_g02_the_response_loop_says_what_it_can_and_no_more():
    """
    ``ResponseLoop`` 도 같은 관문을 쓰고, **자기가 아는 것까지만** 말한다.

    그 루프는 쌓인 체인에 링크를 더하는 자리이므로 단계가 체인 하나로
    정해진다 — 그래서 넘기지 않는다. 체인이 비어 있는 발동을 그 길로
    넣으려는 호출자는 :meth:`~engine.response.ResponseLoop.check_timing` 에
    단계를 직접 줄 수 있다.
    """
    import inspect

    from engine.response import ResponseLoop

    signature = inspect.signature(ResponseLoop.check_timing)
    assert "stage" in signature.parameters
    assert signature.parameters["stage"].default is None
    assert signature.parameters["stage"].kind is inspect.Parameter.KEYWORD_ONLY


def test_g03_no_second_stage_engine_was_built():
    """
    🔴 **같은 책임의 두 번째 규칙 엔진을 만들지 않았다.**

    단계를 **쓰는** 자리는 관문 하나이고, 단계를 **읽는** 자리는 판을 든
    쪽 하나다. 문자열 ``reason`` 을 분석해 단계를 판별하는 자리도 없다.
    """
    import pathlib

    timing = pathlib.Path("engine/activation_timing.py").read_text("utf-8")
    duel_source = pathlib.Path("engine/duel.py").read_text("utf-8")

    #: 단계로 갈래를 치는 자리는 관문 하나다.
    assert timing.count("def _by_stage(") == 1
    assert duel_source.count("def _activation_stage(") == 1

    #: 🔴 **문자열을 보고 단계를 정하지 않는다.** 단계를 읽는 함수에
    #: ``reason`` 이라는 말이 없다 — 있으면 문장을 해석하는 길이 생긴다.
    body = duel_source.split("def _activation_stage(")[1].split("\n    def ")[0]
    assert "reason" not in body, body
