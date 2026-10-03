"""
Phase 3-E-14 — 세트해 둔 카드의 발동 (``SET_ACTIVATION_MISSING`` 감사와 해결).

감사의 결론은 **하나가 아니라 둘**이다. 세트된 카드의 발동은 한 덩어리가
아니라 공식 조항이 **서로 다르게 적어 둔 세 갈래**였고, 그중 하나는 엔진이
이미 판정할 수 있는 정보만으로 끝난다.

====================  =====================================================
세트한 **통상 마법**   RULE-SPELLTRAP-012 — "Spell Cards can be activated
                      during the Main Phases **even in the same turn that you
                      Set them** (except for Quick-Play Spell Cards). Setting
                      them does not allow you to use them on your opponent's
                      turn; they still can only be activated during your Main
                      Phase."
                      → **세트한 턴을 셀 필요가 없다.** 이번 Phase 가 연다
세트한 **속공 마법**   RULE-SPELLTRAP-007 — "You can also activate them during
                      your opponent's turn if you Set the card face-down
                      first, but then you **cannot activate the card in the
                      same turn you Set it**."
                      → 세트한 턴을 세야 한다. ``UNKNOWN`` 으로 남는다
세트한 **함정**        RULE-SPELLTRAP-009 — "You cannot activate a Trap in the
                      same turn that you Set it, but you can activate it at
                      any time after that—starting from the beginning of the
                      next turn."
                      → 세트한 턴을 세야 한다. ``UNKNOWN`` 으로 남는다
====================  =====================================================

그래서 ``SET_ACTIVATION_MISSING`` **자체는 아직 열려 있다.** 이번 Phase 가
닫은 것은 그 옆에 있던, 이름이 붙어 있지 않던 자리다 — 조항이 **같은 턴을
명시적으로 허락**하는 통상 마법을 엔진이 "모른다" 고 말하고 있었다.

**Phase 3-E-15 가 그 다음 칸을 채웠다.** 세트한 턴이
``GameState.rule_uses`` 에 ``(턴, 플레이어, instance_id, set_spell_trap)`` 으로
적히고, ``ActivationTimingChecker`` 가 ``ActivationTiming.set_this_turn`` 으로
받아 판정한다. 그래서 위 표의 **둘째 줄(세트한 속공 마법)이 열렸다** — 같은
턴이면 ``INVALID``, 다음 턴부터 ``VALID`` 다. 셋째 줄(함정)은 그대로 남아
있고, 이 파일의 ``test_10`` 이 그 이유가 "세트한 턴" 이 **아님**을 잰다.
세트한 턴 자체의 기록과 판정은 ``test_set_turn_record.py`` 가 잰다.

RULE ≠ TIMING ≠ EXECUTION
-------------------------
세 층을 따로 쟀고, 세트된 카드가 후보가 되지 않는 이유가 **층마다 달랐다.**

- Action Space  ``_activation_actions`` 가 **패만** 훑었다 → 어떤 관문도
  판정할 기회를 얻지 못했다 (``test_02``)
- Timing        ``ActivationTimingChecker`` 는 **이미 판정할 수 있었다** —
  세트된 카드에도 ``VALID`` 를 내고 스펠 스피드를 정확히 본다. 막고 있던 것이
  **아니다** (``test_03``)
- Validation    ``ActionValidator`` 가 ``UNKNOWN`` 을 냈다 (올바른 태도다 —
  ``INVALID`` 이 아니다)
- Execution     ``NormalSpellPlacement.place`` 가 패에서만 꺼낸다 →
  ``SpellActivationError`` (``test_04``)
"""

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidator
from engine.activation_timing import ActivationTiming, ActivationTimingChecker
from engine.duel import Duel
from engine.ids import EffectRef
from engine.priority import PriorityState, ResponseWindow
from engine.spell_activation import SpellActivationError, SpellRevealed
from engine.state.game_state import GameState
from engine.state.rule_usage import RuleActionKind
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db, settle_chain

pytestmark = requires_official_db

P0, P1 = 0, 1

LUSTER_DRAGON = 11091375  # 통상 몬스터
POT_OF_GREED = 55144522  # 통상 마법 — 스펠 스피드 1
RELOAD = 22589918  # 속공 마법 — 세트하면 "세트한 턴" 이 걸린다
GIFT_OF_GREED = 5915629  # 함정 — 세트가 앞서고 "세트한 턴" 이 걸린다


def duel_at(repository, *, mine=(), theirs=(), turn_player=P0, phase=Phase.MAIN1):
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20),
        turn_player=turn_player,
        seed=1,
    )
    for card_id in mine:
        state.create_instance(card_id, owner=P0, zone=Zone.HAND)
    for card_id in theirs:
        state.create_instance(card_id, owner=P1, zone=Zone.HAND)
    state.turn.turn_number = 2
    state.turn.turn_player = turn_player
    state.turn.set_phase(phase)
    return Duel(
        state=state,
        priority=PriorityState.idle(turn_player=turn_player, phase=phase),
    )


def activations(duel, seat, card_id=None):
    return [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and (card_id is None or a.effect_ref.card_id == card_id)
    ]


def set_down(duel, seat, card_id):
    """그 카드를 실제로 세트한다 — 상태를 손으로 만들지 않는다."""
    card = next(c for c in duel.state.player(seat).hand if c.card_id == card_id)
    step = duel.apply(PlayerAction.set_spell_trap(actor=seat, source=card.instance_id))
    assert step.accepted, step.reason
    return card.instance_id


def hand_made(seat, instance, card_id):
    """후보 목록을 **거치지 않고** 만든 발동 행위."""
    return PlayerAction.activate_effect(
        actor=seat, source=instance, effect_ref=EffectRef(card_id, 0)
    )


def szone(duel, seat=P0):
    return [c for c in duel.state.player(seat).zones[Zone.SZONE] if c is not None]


# ======================================================================
# §7 — 세트 상태는 보존되고, 세트한 **턴**은 적혀 있지 않다
# ======================================================================


@pytest.mark.real_card
def test_01_the_set_state_and_the_set_turn_are_both_recorded(repository):
    """
    **§7 · §8 — 무엇이 있는지 실행으로 적는다.**

    **이 시험의 주장이 뒤집혔다** (Phase 3-E-15)
    -------------------------------------------
    처음 적을 때는 **"세트한 턴은 적혀 있지 않다"** 를 고정했다. 그것이 당시의
    사실이었고, 그 한 줄이 다음 단계를 가리켰다 — 설명에 "다음 단계가 무엇인지가
    이 한 줄에 달려 있다" 고 적어 두었다.

    Phase 3-E-15 가 그 단계를 밟았다. ``RuleUsageRegistry`` 는 키에 턴 번호를
    담고 있었으므로 (``(턴, 플레이어, instance_id, 행위)``) 담을 자리가 이미
    있었고, 쓰는 쪽만 없었다. 이제 ``SetExecutor.apply`` 가 적는다.

    그래서 주장을 **반대 방향으로 강화한다** — 약화가 아니다. 존 · 표시 형식 ·
    직전 상태에 더해 **세트한 턴까지** 적혀 있고, 그것이 카드마다 따로다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    turn = duel.state.turn.turn_number
    instance = set_down(duel, P0, POT_OF_GREED)

    card = duel.state.find_instance(instance)
    assert card.zone is Zone.SZONE
    assert card.position is Position.FACEDOWN
    assert card.is_faceup is False
    assert card.previous.location is Zone.HAND

    # 세트한 턴이 **카드마다** 적혀 있다.
    uses = duel.state.rule_uses
    assert uses.used_card(turn, P0, instance, RuleActionKind.SET_SPELL_TRAP)
    assert not uses.used_card(turn + 1, P0, instance, RuleActionKind.SET_SPELL_TRAP)
    # 플레이어별 표에는 적지 않는다 — 세트는 횟수 제한이 없다.
    assert uses.counts == {}
    # 카드 자신에게는 새 필드를 만들지 않았다.
    assert card.status_flags == 0
    assert not hasattr(card, "set_turn")


# ======================================================================
# §12 — 타이밍 관문은 막고 있던 쪽이 아니었다
# ======================================================================


@pytest.mark.real_card
def test_02_the_action_space_was_the_omission(repository):
    """
    **§4-A — 후보가 0건이었던 첫 번째 이유는 '보지 않았다' 다.**

    ``_activation_sources`` 가 패만 돌려주면 세트된 카드는 **어떤 관문에도
    닿지 못한다.** 막혔다는 기록도 남지 않는다 — 이것이 "``UNKNOWN`` 으로
    막혔다" 와 다른 사실이고, 그래서 둘을 따로 적는다.

    지금은 둘 다 출발지다. 그리고 거기서 **거르지 않는다** — 세트된 속공 마법
    과 함정도 나오고, 관문이 그것을 ``UNKNOWN`` 으로 막는다 (``test_07``).
    """
    duel = duel_at(repository, mine=(POT_OF_GREED, RELOAD, GIFT_OF_GREED, LUSTER_DRAGON))
    pot = set_down(duel, P0, POT_OF_GREED)
    reload_id = set_down(duel, P0, RELOAD)
    gift = set_down(duel, P0, GIFT_OF_GREED)

    sources = {card.instance_id for card in duel._activation_sources(P0)}
    assert {pot, reload_id, gift} <= sources, "세트된 카드가 출발지에 없다"
    assert {card.instance_id for card in duel.state.player(P0).hand} <= sources


@pytest.mark.real_card
def test_03_the_timing_gate_now_reads_the_set_turn_it_is_given(repository):
    """
    **§12 — ``ActivationTimingChecker`` 는 세트된 카드도 판정한다.**

    감사에서 가장 중요한 측정이다. "세트 카드가 후보가 아니다" 를 타이밍 관문
    탓으로 적으면 틀린 곳을 고치게 된다 — 이 관문은 **스펠 스피드만** 보고,
    세트된 통상 마법 · 속공 마법 · 함정 모두에 ``VALID`` 를 낸다 (체인이 비어
    있을 때).

    그리고 자기가 **보지 않은 것**을 숨기지 않는다 — 이유에 "다른 타이밍 규칙은
    판정하지 않았습니다" 가 들어 있다.

    **한 가지가 늘었다** (Phase 3-E-15)
    ----------------------------------
    이 관문은 이제 **세트한 턴도 본다** — 단, 스스로 알아내는 것이 아니라
    ``ActivationTiming.set_this_turn`` 으로 **받아서** 본다. 그 사실이 관측에
    없기 때문이다.

    그래서 같은 카드가 세 가지 답을 낸다.

    ==========================  ==========================================
    ``set_this_turn`` 을 안 줌    ``UNKNOWN`` — 모르는 것을 통과시키지 않는다
    ``set_this_turn=True``      ``INVALID`` — 세트한 턴이다 (스펠 스피드 2 · 3)
    ``set_this_turn=False``     ``VALID`` — 스펠 스피드만 남는다
    ==========================  ==========================================

    스펠 스피드 1(세트한 통상 마법)은 **셋 다 ``VALID``** 다 —
    RULE-SPELLTRAP-012 가 같은 턴을 허락하므로 이 규칙의 자리가 아니다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED, RELOAD, GIFT_OF_GREED, LUSTER_DRAGON))
    instances = {
        card_id: set_down(duel, P0, card_id)
        for card_id in (POT_OF_GREED, RELOAD, GIFT_OF_GREED)
    }

    # 스펠 스피드 1 — 세트한 턴 제약이 걸리지 않는다 (RULE-SPELLTRAP-012).
    for given in (None, True, False):
        verdict = checker_for(duel, P0).check(
            ActivationTiming(duel.chain, duel.priority, set_this_turn=given),
            hand_made(P0, instances[POT_OF_GREED], POT_OF_GREED),
        )
        assert verdict.validity is ActionValidity.VALID, (given, verdict.reason)
        assert "판정하지 않았습니다" in verdict.reason

    # 스펠 스피드 2 — 세트한 턴을 받아야 판정한다.
    for card_id in (RELOAD, GIFT_OF_GREED):
        action = hand_made(P0, instances[card_id], card_id)
        unknown = checker_for(duel, P0).check(
            ActivationTiming(duel.chain, duel.priority), action
        )
        assert unknown.validity is ActionValidity.UNKNOWN, card_id
        assert "set-turn" in (unknown.missing_rule or ""), card_id

        refused = checker_for(duel, P0).check(
            ActivationTiming(duel.chain, duel.priority, set_this_turn=True), action
        )
        assert refused.validity is ActionValidity.INVALID, card_id
        assert refused.code is ValidationCode.SET_THIS_TURN, card_id

        allowed = checker_for(duel, P0).check(
            ActivationTiming(duel.chain, duel.priority, set_this_turn=False), action
        )
        assert allowed.validity is ActionValidity.VALID, (card_id, allowed.reason)

    # 관문은 관측만 읽는다 — 판을 바꾸지 않았다.
    assert len(szone(duel)) == 3
    assert all(c.position is Position.FACEDOWN for c in szone(duel))


def checker_for(duel, seat):
    return ActivationTimingChecker(duel.view(seat))


@pytest.mark.real_card
def test_04_the_hand_only_placement_was_the_other_omission(repository):
    """
    **§4-E — 두 번째 이유는 '실행 경로가 패만 안다' 다.**

    ``place`` 는 ``HAND`` 에서만 꺼낸다. 세트된 카드로 그것을 부르면 거절한다 —
    그리고 **거절하는 것이 옳다.** 세트된 마법의 발동은 이동이 아니라 **그
    자리에서 앞면으로 돌리는 것**이므로 (``reveal``), 같은 함수로 덮으면 "패에서
    나왔다" 가 거짓이 된다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    instance = set_down(duel, P0, POT_OF_GREED)

    with pytest.raises(SpellActivationError) as refused:
        duel._placement.place(duel.state, instance, P0)
    assert "HAND 에서만" in str(refused.value)

    # 그리고 ``reveal`` 은 앞면인 카드를 다시 돌리지 않는다.
    duel._placement.reveal(duel.state, instance, P0)
    with pytest.raises(SpellActivationError) as twice:
        duel._placement.reveal(duel.state, instance, P0)
    assert "이미 앞면" in str(twice.value)


# ======================================================================
# §23 — 세트한 통상 마법: 같은 턴 · 다음 턴 · 상대 턴 · 페이즈
# ======================================================================


@pytest.mark.real_card
def test_05_a_set_normal_spell_activates_in_the_same_turn(repository):
    """
    **§23-2 — 세트한 **그 턴**에 발동할 수 있다** (RULE-SPELLTRAP-012).

    조항이 이 경우를 **직접** 적는다 — "even in the same turn that you Set
    them". 그래서 여기에는 "세트한 턴" 을 세는 자리가 필요하지 않다.

    그리고 끝까지 따라간다. 칸 번호가 그대로인 것이 이 시험의 핵심이다 —
    발동이 **이동이 아니기** 때문이다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    instance = set_down(duel, P0, POT_OF_GREED)
    slot = duel.state.find_instance(instance).sequence
    deck_before = len(duel.state.player(P0).zones[Zone.DECK])

    candidates = activations(duel, P0, POT_OF_GREED)
    assert len(candidates) == 1, "세트한 통상 마법이 후보가 아니다"
    assert candidates[0].source == instance

    step = duel.apply(candidates[0])
    assert step.accepted, step.reason

    card = duel.state.find_instance(instance)
    assert card.zone is Zone.SZONE, "발동이 카드를 옮겼다 — 돌리기만 해야 한다"
    assert card.sequence == slot, "칸 번호가 바뀌었다"
    assert card.position is Position.FACEUP
    assert len(duel.chain) == 1
    assert duel.priority.window is ResponseWindow.RESPONSE
    assert duel.priority.holder.is_seat(P1)
    assert [type(p) for p in duel.pending_spells] == [SpellRevealed]

    assert settle_chain(duel).accepted
    # 해결 뒤는 패에서 발동한 것과 **같다** (RULE-SPELLTRAP-002 의 마지막 문장).
    assert [c.card_id for c in duel.state.player(P0).zones[Zone.GRAVE]] == [
        POT_OF_GREED
    ]
    assert szone(duel) == []
    assert duel.pending_spells == ()
    assert len(duel.state.player(P0).zones[Zone.DECK]) == deck_before - 2


@pytest.mark.real_card
def test_06_a_set_normal_spell_activates_in_a_later_turn_too(repository):
    """**§23-3 — 다음 턴에도 같다.** 세트한 턴이 조건이 아니기 때문이다."""
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    instance = set_down(duel, P0, POT_OF_GREED)

    duel.state.turn.turn_number += 2  # 내 다음 턴
    duel.priority = PriorityState.idle(turn_player=P0, phase=Phase.MAIN1)

    candidates = activations(duel, P0, POT_OF_GREED)
    assert [a.source for a in candidates] == [instance]
    assert duel.apply(candidates[0]).accepted


@pytest.mark.real_card
@pytest.mark.parametrize(
    "case,turn_player,phase,fragment",
    [
        (
            "상대 턴에는 발동할 수 없다",
            P1,
            Phase.MAIN1,
            "자신의 턴이 아닙니다",
        ),
        (
            "메인 페이즈가 아니면 발동할 수 없다",
            P0,
            Phase.END,
            "메인 페이즈가 아닙니다",
        ),
    ],
)
def test_07_a_set_normal_spell_is_still_main_phase_only(
    repository, case, turn_player, phase, fragment
):
    """
    **§23-4 — 세트했다고 상대 턴에 쓸 수 있게 되지 않는다** (RULE-SPELLTRAP-012:
    "Setting them does not allow you to use them on your opponent's turn; they
    still can only be activated during your Main Phase").

    이 둘은 ``UNKNOWN`` 이 **아니다.** 조항이 금지하므로 ``INVALID`` 다 —
    "모른다" 고 적으면 알고 있는 것을 모른다고 말하는 것이 된다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    instance = set_down(duel, P0, POT_OF_GREED)

    duel.state.turn.turn_player = turn_player
    duel.state.turn.set_phase(phase)
    duel.priority = PriorityState.idle(turn_player=turn_player, phase=phase)

    action = hand_made(P0, instance, POT_OF_GREED)
    verdict = ActionValidator(duel.view(P0)).validate(action)
    assert verdict.validity is ActionValidity.INVALID, (case, verdict.reason)
    assert fragment in verdict.reason, (case, verdict.reason)

    assert activations(duel, P0, POT_OF_GREED) == [], case
    step = duel._apply_activation(action)
    assert not step.accepted, case
    assert szone(duel)[0].position is Position.FACEDOWN, "거절하고도 판을 바꿨다"


@pytest.mark.real_card
def test_08_a_set_normal_spell_is_no_response_candidate(repository):
    """
    **§23-5 · §11 — 응답 창을 쥐어도 스펠 스피드 1 은 올라가지 못한다.**

    두 가지를 한 번에 고정한다.

    ① 상대 턴의 응답 자리에서는 ``IsTurnPlayer`` 가 막는다 (조항이 금지한다)
    ② 자기 턴이어도 체인이 쌓여 있으면 **스펠 스피드**가 막는다
       (RULE-CHAIN-004)

    ②는 ``turn_player`` 와 ``응답 자리``가 섞이지 않았다는 증거이기도 하다 —
    응답 자리가 P0 이고 턴 플레이어도 P0 인데, 그래도 올라가지 못한다.
    """
    # ① 상대 턴
    duel = duel_at(repository, mine=(POT_OF_GREED,), theirs=(POT_OF_GREED,))
    mine_set = set_down(duel, P0, POT_OF_GREED)
    duel.state.turn.turn_number += 1
    duel.state.turn.turn_player = P1
    duel.priority = PriorityState.idle(turn_player=P1, phase=Phase.MAIN1)
    assert duel.apply(activations(duel, P1, POT_OF_GREED)[0]).accepted
    assert duel.priority.holder.is_seat(P0), "응답 자리는 P0 이다"
    assert duel.turn_player == P1, "턴 플레이어는 바뀌지 않았다"
    assert activations(duel, P0, POT_OF_GREED) == []
    refused = duel._apply_activation(hand_made(P0, mine_set, POT_OF_GREED))
    assert not refused.accepted
    assert "자신의 턴이 아닙니다" in refused.reason

    # ② 자기 턴, 체인 위
    duel = duel_at(repository, mine=(POT_OF_GREED, POT_OF_GREED))
    set_instance = set_down(duel, P0, POT_OF_GREED)
    from_hand = [a for a in activations(duel, P0, POT_OF_GREED) if a.source != set_instance]
    assert duel.apply(from_hand[0]).accepted
    assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted  # 상대 패스
    assert duel.priority.holder.is_seat(P0)
    assert duel.turn_player == P0
    assert activations(duel, P0, POT_OF_GREED) == []
    refused = duel._apply_activation(hand_made(P0, set_instance, POT_OF_GREED))
    assert not refused.accepted
    assert "스펠 스피드" in refused.reason


@pytest.mark.real_card
def test_09_a_full_spell_trap_zone_does_not_block_its_own_card(repository):
    """
    **자기 칸에 있는 카드는 새 칸을 필요로 하지 않는다.**

    ``ZoneHasFreeSlot(SZONE)`` 을 세트된 카드에도 걸면, 마법 & 함정 존이 꽉 찬
    판에서 **그 존에 있는 카드**를 발동할 수 없게 된다. 규칙이 금지하지 않는
    것을 금지하는 것이므로 거짓이다.

    5칸을 전부 세트한 뒤 그중 하나를 발동한다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,) * 5)
    instances = [set_down(duel, P0, POT_OF_GREED) for _ in range(5)]
    assert len(szone(duel)) == 5
    assert len(duel.state.player(P0).zones[Zone.HAND]) == 0

    candidates = activations(duel, P0, POT_OF_GREED)
    assert len(candidates) == 5, "꽉 찬 존이 자기 카드의 발동을 막았다"
    assert {a.source for a in candidates} == set(instances)
    assert duel.apply(candidates[0]).accepted


# ======================================================================
# SET_ACTIVATION_MISSING — **아직 열려 있다**
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize(
    "card_id,label,missing",
    [
        # 함정은 **더 넓은 이유**로 범위 밖이다. 세트한 턴 제약 말고도 발동
        # 타이밍 계층 자체가 없다 (유발 · 응답 타이밍). 세트한 턴을 세게 된
        # 뒤에도 이것은 그대로다 — 둘을 같은 이유로 적으면 "세트한 턴만 세면
        # 함정이 열린다" 는 거짓이 된다.
        (GIFT_OF_GREED, "세트한 함정 (RULE-SPELLTRAP-009)", "함정"),
    ],
)
def test_10_unknown_is_not_promoted_for_cards_that_need_the_set_turn(
    repository, card_id, label, missing
):
    """
    **§12 · §22-6 — ``UNKNOWN`` 을 허가로 바꾸지 않았다.**

    ``UNKNOWN`` 은 허가가 아니므로 후보가 되지 않는다. **``INVALID`` 도
    아니다** — 실제 규칙에서는 다음 턴부터 적법하기 때문이다.

    그리고 **막힌 이유가 기록으로 남는다.** 이것이 Phase 3-E-14 전과 다른
    점이다 — 전에는 출발지에서조차 보이지 않아 "왜 없는지" 가 어디에도 적히지
    않았다.

    **세트한 속공 마법이 이 목록에서 빠졌다** (Phase 3-E-15)
    -----------------------------------------------------
    처음에는 둘이었다 — 세트한 속공 마법과 세트한 함정. 둘을 **다른 이유**로
    적어 둔 것이 그때의 핵심이었고, 그 구분이 지금 값을 했다.

    속공 마법은 모자란 것이 **"세트한 턴" 하나뿐**이었고 그것이 채워졌으므로
    (``GameState.rule_uses``) 이제 판정된다 — 같은 턴이면 ``INVALID``, 다음
    턴부터 ``VALID`` 다 (``tests/engine/test_set_turn_record.py``).

    함정은 모자란 것이 **더 많았다.** 그래서 여기 남아 있고, 남아 있는 이유가
    "세트한 턴" 이 아니라 ``함정 · 몬스터 효과의 발동 타이밍`` 임을 아래
    단정이 그대로 잰다.
    """
    duel = duel_at(repository, mine=(card_id, LUSTER_DRAGON))
    instance = set_down(duel, P0, card_id)
    duel.state.turn.turn_number += 2  # 다음 턴이어도 마찬가지다
    duel.priority = PriorityState.idle(turn_player=P0, phase=Phase.MAIN1)

    action = hand_made(P0, instance, card_id)
    verdict = ActionValidator(duel.view(P0)).validate(action)
    assert verdict.validity is ActionValidity.UNKNOWN, (label, verdict.reason)
    assert verdict.missing_rule is not None
    assert missing in verdict.missing_rule, (label, verdict.missing_rule)

    assert activations(duel, P0, card_id) == [], label
    # 그래도 출발지에는 **있다** — 보지 않은 것과 막힌 것은 다르다.
    assert instance in {c.instance_id for c in duel._activation_sources(P0)}

    step = duel._apply_activation(action)
    assert not step.accepted, label
    assert szone(duel)[0].position is Position.FACEDOWN


# ======================================================================
# §10 — 파리티 · §15 — 숨은 정보 · §9 회귀
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize("set_count", [0, 1, 2, 3])
def test_11_every_candidate_is_applyable(repository, set_count):
    """
    **§10 · §22-9 — Phase 3-E-13 의 계약을 유지한다.**

        LEGAL ACTION → APPLY 가능한 Action

    세트된 카드가 후보에 들어와도 그대로여야 한다. 세트 장수를 바꿔 가며
    후보 전부를 **새 판**에서 적용한다.
    """

    def build():
        duel = duel_at(
            repository,
            mine=(POT_OF_GREED, POT_OF_GREED, POT_OF_GREED, RELOAD, LUSTER_DRAGON),
        )
        for _ in range(set_count):
            set_down(duel, P0, POT_OF_GREED)
        return duel

    duel = build()
    candidates = activations(duel, P0)
    assert candidates, "후보가 없으면 아무것도 증명하지 못한다"

    for index in range(len(candidates)):
        fork = build()
        same = activations(fork, P0)[index]
        step = fork.apply(same)
        assert step.accepted, f"허가한 발동을 거절했다: {step.reason}"


@pytest.mark.real_card
def test_12_the_opponent_never_learns_what_is_set(repository):
    """
    **§15 · §16 — 세트 카드를 후보로 만들려고 상대의 정체를 읽지 않았다.**

    컨트롤러는 자기 세트 카드를 알고 (알아야 발동할 수 있다), 상대는 모른다.
    그리고 **상대 자리에서는 발동 후보가 되지 않는다** — 정체를 모르므로
    ``UNKNOWN`` 이고, 그것은 허가가 아니다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    instance = set_down(duel, P0, POT_OF_GREED)

    mine = duel.view(P0)
    theirs = duel.view(P1)
    [owned] = [c for c in mine.me.zone(Zone.SZONE).cards if c is not None]
    [seen] = [c for c in theirs.opponent.zone(Zone.SZONE).cards if c is not None]

    assert owned.card_id == POT_OF_GREED
    assert owned.definition is not None
    assert seen.card_id is None, "상대가 세트 카드의 정체를 읽었다"
    assert seen.name is None
    assert seen.definition is None
    assert seen.face_up is False
    # 장수는 공개다 — 가려진 것은 정체뿐이다.
    assert theirs.opponent.zone(Zone.SZONE).size == 1

    # 상대 자리에서 그 카드를 발동하려 해도 후보가 아니고 허가도 아니다.
    assert activations(duel, P1, POT_OF_GREED) == []
    stolen = hand_made(P1, instance, POT_OF_GREED)
    verdict = ActionValidator(duel.view(P1)).validate(stolen)
    assert verdict.validity is not ActionValidity.VALID
    assert not duel._apply_activation(stolen).accepted


@pytest.mark.real_card
def test_13_the_hand_activation_path_is_unchanged(repository):
    """
    **§9 — 패에서의 발동이 한 걸음도 달라지지 않았다.**

    출발지가 둘이 되었으므로, 원래 있던 쪽이 그대로인지 따로 잰다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    deck_before = len(duel.state.player(P0).zones[Zone.DECK])

    candidates = activations(duel, P0, POT_OF_GREED)
    assert len(candidates) == 1
    assert duel.apply(candidates[0]).accepted

    # 패에서 발동한 카드는 **옮겨진다** — 세트된 카드와 다른 사건이다.
    card = duel.state.find_instance(candidates[0].source)
    assert card.zone is Zone.SZONE
    assert card.previous.location is Zone.HAND
    assert card.position is Position.FACEUP
    assert len(duel.state.player(P0).zones[Zone.HAND]) == 0

    assert settle_chain(duel).accepted
    assert [c.card_id for c in duel.state.player(P0).zones[Zone.GRAVE]] == [
        POT_OF_GREED
    ]
    assert len(duel.state.player(P0).zones[Zone.DECK]) == deck_before - 2


def test_14_no_new_action_kind_and_no_new_engine():
    """
    **§22-13 · §22-14 · §22-15 — 새 것을 만들지 않았다.**

    세트 카드의 발동은 기존 ``ACTIVATE_EFFECT`` 하나로 표현된다. 새 Action
    종류도, 새 엔진도 없다 — 바뀐 것은 **출발지가 둘이 되었다**는 것뿐이다.
    """
    import engine.duel as duel_module

    kinds = {k.value for k in PlayerActionKind}
    assert "activate_set_card" not in kinds
    assert "flip_set_card" not in kinds
    assert "reveal_spell" not in kinds

    source = duel_module.__dict__
    for forbidden in (
        "SetCardEngine",
        "SpellTrapEngine",
        "ResponseEngine",
        "TimingEngine",
    ):
        assert forbidden not in source, forbidden

    # 발동 경로는 하나다 — 세트 전용 분기를 따로 만들지 않았다.
    import inspect

    apply_source = inspect.getsource(duel_module.Duel.apply)
    assert apply_source.count("_apply_activation(") == 1


@pytest.mark.real_card
def test_15_only_a_face_down_spell_counts_as_a_set_card(repository):
    """
    **§13 — "세트된 카드" 의 뜻을 한 자리에서 고정한다.**

    왜 이 시험이 필요했는가: ``_is_set_normal_spell`` 에서 "마법인가" 를 지워
    보는 고의 위반을 넣었더니 **아무 테스트도 잡지 못했다.** 앞선 관문이
    이미 함정(``통상 마법이 아니다``)과 속공 마법(``_OUT_OF_SCOPE_TYPES``)을
    걸러내므로, 이 판정이 느슨해져도 결과가 보이지 않는다 — 이중 방어다.

    결과로 보이지 않는 것은 **직접** 잰다. 이 술어 하나가 "세트된 카드" 의
    정의이고, 그것이 넓어지면 ``ZoneHasFreeSlot`` 면제와 ``IsTurnPlayer``
    문장이 **엉뚱한 카드에** 붙는다. 그때 보이는 것은 틀린 이유 문장이고,
    그것은 거짓말이다.

    카드 종류를 이름으로 적지 않는다 — 정의와 판 상태만 읽는다 (§13).
    """
    from engine.action_validation import activation_is_set_card
    from engine.condition.context import ConditionContext  # noqa: F401

    duel = duel_at(
        repository,
        # 통상 마법을 **두 장** 쥔다 — 한 장은 세트하고 한 장은 패에 남겨서
        # 같은 카드의 두 자리를 비교한다.
        mine=(POT_OF_GREED, POT_OF_GREED, RELOAD, GIFT_OF_GREED, LUSTER_DRAGON),
    )
    set_spell = set_down(duel, P0, POT_OF_GREED)
    set_quick = set_down(duel, P0, RELOAD)
    set_trap = set_down(duel, P0, GIFT_OF_GREED)
    hand_spell = next(
        c.instance_id for c in duel.state.player(P0).hand if c.card_id == POT_OF_GREED
    )

    def is_set_card(instance):
        view = duel.view(P0)
        context = ConditionContext(player=P0, source=instance)
        return activation_is_set_card(view, context, instance)

    assert is_set_card(set_spell) is True

    # 세트된 **속공 마법도 세트된 마법이다** (Phase 3-E-15). 처음에는 ``False``
    # 를 기대했고, 근거는 "RULE-SPELLTRAP-007 이 세트한 턴을 요구하므로 다른
    # 조항의 자리다" 였다. 그 가정이 둘을 섞었다 —
    #
    #   "세트된 마법인가"        자리와 표시 형식의 문제다. 발동이 **놓는 것이
    #                           아니라 돌리는 것**이므로 빈 칸을 요구하지 않는다
    #   "세트한 턴이 걸리는가"   **조항**의 문제다. 통상 마법은 안 걸리고
    #                           속공 마법은 걸린다
    #
    # 앞의 것은 둘 다 참이고 뒤의 것만 다르다. 한 술어로 둘을 다 적으면 세트한
    # 속공 마법이 ``ZoneHasFreeSlot`` 을 지게 되고, 마법 & 함정 존이 꽉 찬 판에서
    # **자기 칸에 있는 카드**를 발동할 수 없게 된다 (``test_09`` 가 그것을 잰다).
    #
    # 그래서 뒤의 판정은 타이밍 관문으로 옮겼다 (``test_03``).
    assert is_set_card(set_quick) is True
    # 세트된 **함정**은 아니다 — 발동 타이밍 계층 자체가 더 넓게 비어 있다.
    assert is_set_card(set_trap) is False
    # 패에 있는 통상 마법은 세트된 카드가 아니다 (옮겨 놓아야 한다).
    assert is_set_card(hand_spell) is False

    # **앞면**인 마법도 아니다 — 이미 발동했거나 다른 종류다.
    duel._placement.reveal(duel.state, set_spell, P0)
    assert is_set_card(set_spell) is False
