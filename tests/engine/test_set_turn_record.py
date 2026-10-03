"""
Phase 3-E-15 — 세트한 턴의 기록 (``SET_ACTIVATION_MISSING`` 의 마지막 칸).

    SET  →  RECORD          쓰는 곳은 ``SetExecutor.apply`` 하나다
    READ ←  TIMING          후보 생성 · 타이밍 · 발동은 **읽기만** 한다

Phase 3-E-14 가 측정해 둔 것이 이 Phase 의 출발점이었다.

    "``RuleUsageRegistry`` 는 키에 턴 번호를 담으므로 담을 자리가 이미 있다.
     그런데 마법 · 함정 세트는 거기에 아무것도 적지 않는다."

그래서 이 Phase 는 **새 필드를 만들지 않았다.** 쓰는 쪽 하나를 더했다.

세 조항이 서로 다르게 적는다
---------------------------
====================  =====================================================
세트한 **통상 마법**   RULE-SPELLTRAP-012 — "Spell Cards can be activated
                      during the Main Phases **even in the same turn that you
                      Set them** (except for Quick-Play Spell Cards)."
                      → 세트한 턴이 **걸리지 않는다**
세트한 **속공 마법**   RULE-SPELLTRAP-007 — "You can **also** activate them
                      during your opponent's turn if you Set the card
                      face-down first, but then you **cannot activate the card
                      in the same turn you Set it**."
                      → 같은 턴 금지. 그 뒤로는 자기 턴의 아무 페이즈 ·
                        **상대 턴에도** 발동한다
세트한 **함정**        RULE-SPELLTRAP-009 — 같은 제약. 그런데 **아직 범위
                      밖**이다. 모자란 것이 세트한 턴 하나가 아니라 발동
                      타이밍 계층 자체이기 때문이다 (유발 · 응답 타이밍)
====================  =====================================================

그래서 ``SET_TURN`` 과 ``ACTIVATION_INVALID`` 는 같은 것이 아니다. 기록은
카드 종류와 **결합해야** 답이 된다.

무엇을 어디에 적었는가
----------------------
``GameState.rule_uses`` — ``(턴 번호, 플레이어, instance_id, "set_spell_trap")``

``GameStateView`` 에는 **넣지 않았다.** 상대가 언제 세웠는지는 공개 정보가
아니다. 그래서 검증기도 타이밍 관문도 스스로 알 수 없고, 판을 들고 있는
``Duel`` 이 읽어서 ``ActivationTiming.set_this_turn`` 으로 넘긴다 — 체인과
우선권을 넘기는 것과 같은 자리다 (ADR-007).

    Internal legality state  ≠  GameStateView
    SET STATE                ≠  SET HISTORY
    CARD ID                  ≠  CARD INSTANCE ID
"""

import pytest

from agent.evaluation import StateEvaluator
from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidator
from engine.activation_timing import ActivationTiming, ActivationTimingChecker
from engine.duel import Duel
from engine.ids import EffectRef
from engine.priority import PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.state.rule_usage import PER_CARD_ACTIONS, RuleActionKind
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db, settle_chain

pytestmark = requires_official_db

P0, P1 = 0, 1

LUSTER_DRAGON = 11091375  # 통상 몬스터
POT_OF_GREED = 55144522  # 통상 마법 — 스펠 스피드 1
RELOAD = 22589918  # 속공 마법 — 스펠 스피드 2 · 대상 없음
GIFT_OF_GREED = 5915629  # 함정 — 스펠 스피드 2
SET_ACTION = RuleActionKind.SET_SPELL_TRAP


def duel_at(repository, *, mine=(), theirs=(), turn_player=P0, phase=Phase.MAIN1,
            turn=5):
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
    state.turn.turn_number = turn
    state.turn.turn_player = turn_player
    state.turn.set_phase(phase)
    return Duel(
        state=state,
        priority=PriorityState.idle(turn_player=turn_player, phase=phase),
    )


def set_down(duel, seat, card_id):
    card = next(c for c in duel.state.player(seat).hand if c.card_id == card_id)
    step = duel.apply(PlayerAction.set_spell_trap(actor=seat, source=card.instance_id))
    assert step.accepted, step.reason
    return card.instance_id


def activations(duel, seat, card_id=None):
    return [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and (card_id is None or a.effect_ref.card_id == card_id)
    ]


def made(seat, instance, card_id):
    return PlayerAction.activate_effect(
        actor=seat, source=instance, effect_ref=EffectRef(card_id, 0)
    )


def next_own_turn(duel, seat=P0):
    """같은 플레이어의 **다음 턴**으로 넘긴다 (턴 번호가 둘 늘어난다)."""
    duel.state.turn.turn_number += 2
    duel.state.turn.turn_player = seat
    duel.state.turn.set_phase(Phase.MAIN1)
    duel.priority = PriorityState.idle(turn_player=seat, phase=Phase.MAIN1)


def szone(duel, seat=P0):
    return [c for c in duel.state.player(seat).zones[Zone.SZONE] if c is not None]


# ======================================================================
# §29-1 · §5 — 기록이 남는다. 그리고 **그 표에 적는 것이 맞는가**
# ======================================================================


@pytest.mark.real_card
def test_01_setting_a_spell_trap_records_the_turn(repository):
    """
    **§29-1 — ``SET_SPELL_TRAP`` 이 턴을 적는다.**

    적는 곳은 ``rule_uses`` 의 **카드별 표**다. 플레이어별 표에는 적지 않는다 —
    마법 · 함정 세트에는 횟수 제한이 없으므로 "이 플레이어가 세트권을 썼다" 는
    말이 성립하지 않는다 (``RuleActionKind.SET_SPELL_TRAP`` 의 설명).
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    turn = duel.state.turn.turn_number
    assert duel.state.rule_uses.card_counts == {}

    instance = set_down(duel, P0, POT_OF_GREED)

    uses = duel.state.rule_uses
    assert uses.used_card(turn, P0, instance, SET_ACTION)
    assert uses.count_card(turn, P0, instance, SET_ACTION) == 1
    assert uses.counts == {}, "플레이어별 표에 적었다 — 세트는 횟수 제한이 없다"


def test_02_the_set_action_is_counted_per_card_not_per_player():
    """
    **§5-Q2 · §5-Q3 · §21 — 이 표에 적는 것이 왜 맞는가.**

    ``PER_CARD_ACTIONS`` 에 들어 있어야 ``card_key`` 가 받아 준다. 그리고
    플레이어별 ``key`` 는 **거부해야** 한다 — 거부하지 않으면 "이 플레이어가
    이번 턴에 뭔가 세웠다" 까지만 아는 기록이 섞여 들어오고, 같은 턴에 두 장을
    세운 판에서 남은 장이 언제 세워졌는지 말할 수 없게 된다.
    """
    from engine.state.rule_usage import RuleUsageRegistry

    assert SET_ACTION in PER_CARD_ACTIONS
    assert RuleUsageRegistry.card_key(5, P0, 40, SET_ACTION) == (
        5,
        P0,
        40,
        "set_spell_trap",
    )
    with pytest.raises(ValueError) as refused:
        RuleUsageRegistry.key(5, P0, SET_ACTION)
    assert "카드마다 세는 행위" in str(refused.value)


@pytest.mark.real_card
def test_03_the_record_is_per_card_instance_not_per_card_id(repository):
    """
    **§21 · §29-2 — 같은 ``card_id`` 두 장이 서로 섞이지 않는다.**

    리로드 두 장을 **다른 턴**에 세운다. 카드 이름으로 셌다면 둘이 같은 답을
    내지만, ``instance_id`` 로 세므로 다른 답을 낸다.
    """
    duel = duel_at(repository, mine=(RELOAD, RELOAD, LUSTER_DRAGON))
    first_turn = duel.state.turn.turn_number
    early = set_down(duel, P0, RELOAD)

    next_own_turn(duel)
    later_turn = duel.state.turn.turn_number
    late = set_down(duel, P0, RELOAD)

    assert early != late
    uses = duel.state.rule_uses
    assert uses.used_card(first_turn, P0, early, SET_ACTION)
    assert not uses.used_card(later_turn, P0, early, SET_ACTION)
    assert uses.used_card(later_turn, P0, late, SET_ACTION)
    assert not uses.used_card(first_turn, P0, late, SET_ACTION)

    # 그래서 엔진의 답도 둘이 다르다.
    assert duel._set_this_turn(made(P0, early, RELOAD)) is False
    assert duel._set_this_turn(made(P0, late, RELOAD)) is True


@pytest.mark.real_card
def test_04_two_cards_set_on_the_same_turn_stay_independent(repository):
    """
    **§8 · §29-4 — 한 장을 발동해도 남은 장의 기록이 바뀌지 않는다.**

    §8 이 적어 둔 상황 그대로다. 플레이어 단위로 적었다면 한 장을 발동한 뒤
    "이 플레이어가 이번 턴에 세웠다" 가 사라질지 남을지가 애매해진다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED, RELOAD, LUSTER_DRAGON))
    turn = duel.state.turn.turn_number
    pot = set_down(duel, P0, POT_OF_GREED)
    reload_id = set_down(duel, P0, RELOAD)

    # 통상 마법은 같은 턴에 발동할 수 있다 (RULE-SPELLTRAP-012).
    assert duel.apply(activations(duel, P0, POT_OF_GREED)[0]).accepted
    assert settle_chain(duel).accepted

    uses = duel.state.rule_uses
    assert uses.used_card(turn, P0, reload_id, SET_ACTION), "남은 장의 기록이 사라졌다"
    assert uses.used_card(turn, P0, pot, SET_ACTION), "발동했다고 기록을 지웠다"
    assert duel._set_this_turn(made(P0, reload_id, RELOAD)) is True


# ======================================================================
# §9 · §10 — 세 종류의 timing semantics
# ======================================================================


@pytest.mark.real_card
def test_05_a_set_normal_spell_ignores_the_set_turn(repository):
    """
    **§10 · §29-10 — 세트한 통상 마법에는 이 제약이 걸리지 않는다**
    (RULE-SPELLTRAP-012: "even in the same turn that you Set them").

    기록은 남지만 **답이 바뀌지 않는다.** ``SET_TURN`` 을 곧
    ``ACTIVATION_INVALID`` 로 읽으면 이 카드가 틀리게 막힌다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    instance = set_down(duel, P0, POT_OF_GREED)

    assert duel._set_this_turn(made(P0, instance, POT_OF_GREED)) is True
    assert [a.source for a in activations(duel, P0, POT_OF_GREED)] == [instance]
    assert duel.apply(activations(duel, P0, POT_OF_GREED)[0]).accepted


@pytest.mark.real_card
def test_06_a_set_quick_play_cannot_be_activated_on_the_turn_it_was_set(repository):
    """
    **§19-B · §29-11 — 세트한 턴에는 발동할 수 없다** (RULE-SPELLTRAP-007).

    그리고 **``UNKNOWN`` 이 아니라 ``INVALID``** 다. 이것이 Phase 3-E-14 와
    갈리는 자리다 — 전에는 "세는 자리가 없다" 였으므로 모르는 것이었고, 지금은
    규칙이 금지하는 것을 안다.
    """
    duel = duel_at(repository, mine=(RELOAD, LUSTER_DRAGON))
    instance = set_down(duel, P0, RELOAD)
    action = made(P0, instance, RELOAD)

    assert duel._set_this_turn(action) is True
    assert activations(duel, P0, RELOAD) == []

    gate = duel._activation_gate(
        action, validator=ActionValidator(duel.view(P0)), selections=()
    )
    assert gate.validity is ActionValidity.INVALID
    assert gate.code is ValidationCode.SET_THIS_TURN
    assert "세트한 턴에는 발동할 수 없습니다" in gate.reason

    step = duel._apply_activation(action)
    assert not step.accepted
    assert szone(duel)[0].position is Position.FACEDOWN, "거절하고도 판을 바꿨다"


@pytest.mark.real_card
def test_07_a_set_trap_is_still_out_of_scope_for_a_wider_reason(repository):
    """
    **§19-C · §29-12 — 함정은 여전히 ``UNKNOWN`` 이고, 이유가 다르다.**

    세트한 턴 제약은 함정에도 있다 (RULE-SPELLTRAP-009). 그런데 함정에
    모자란 것은 **그것만이 아니다** — 유발 · 응답 타이밍 계층이 없다. 그래서
    세트한 턴을 세게 되었어도 범위 밖이고, ``missing_rule`` 이 그 이유를
    "세트한 턴" 이 아니라 "함정 · 몬스터 효과의 발동 타이밍" 으로 말한다.

    **여기서 함정을 열지 않는 것이 이 Phase 의 경계다.** 기록이 생겼다는
    이유로 통과시키면 없는 규칙을 있는 것처럼 쓰게 된다.
    """
    duel = duel_at(repository, mine=(GIFT_OF_GREED, LUSTER_DRAGON))
    instance = set_down(duel, P0, GIFT_OF_GREED)

    # 기록은 함정에도 남는다 — 쓰는 쪽은 카드 종류를 보지 않는다.
    assert duel._set_this_turn(made(P0, instance, GIFT_OF_GREED)) is True

    next_own_turn(duel)
    assert duel._set_this_turn(made(P0, instance, GIFT_OF_GREED)) is False

    verdict = ActionValidator(duel.view(P0)).validate(made(P0, instance, GIFT_OF_GREED))
    assert verdict.validity is ActionValidity.UNKNOWN
    assert "함정" in (verdict.missing_rule or ""), verdict.missing_rule
    assert "set-turn" not in (verdict.missing_rule or "")
    assert activations(duel, P0, GIFT_OF_GREED) == []


@pytest.mark.real_card
def test_08_a_set_quick_play_opens_on_the_next_turn(repository):
    """
    **§19-D · §29-13 — 다음 턴부터 발동할 수 있다.**

    같은 판 · 같은 카드 · 바뀐 것은 턴 번호 하나다. 그래서 이 시험이 재는 것은
    **기록이 실제로 답을 가른다**는 것이다.
    """
    duel = duel_at(repository, mine=(RELOAD, LUSTER_DRAGON))
    instance = set_down(duel, P0, RELOAD)
    assert activations(duel, P0, RELOAD) == []

    next_own_turn(duel)

    assert duel._set_this_turn(made(P0, instance, RELOAD)) is False
    candidates = activations(duel, P0, RELOAD)
    assert [a.source for a in candidates] == [instance]

    step = duel.apply(candidates[0])
    assert step.accepted, step.reason
    # 세트된 카드는 **옮기지 않고 돌린다** (Phase 3-E-14 의 ``reveal``).
    card = duel.state.find_instance(instance)
    assert card.zone is Zone.SZONE
    assert card.position is Position.FACEUP
    assert settle_chain(duel).accepted
    assert [c.card_id for c in duel.state.player(P0).zones[Zone.GRAVE]] == [RELOAD]


@pytest.mark.real_card
def test_09_a_set_quick_play_can_respond_on_the_opponent_turn(repository):
    """
    **§29-15 · RULE-SPELLTRAP-007 의 두 번째 절이 실제로 열렸다.**

        "You can **also** activate them during your opponent's turn if you Set
        the card face-down first."

    이것이 ``SET_ACTIVATION_MISSING`` 이 막고 있던 바로 그 자리다. 체인 링크
    2 가 되고, 그때 **턴 플레이어는 바뀌지 않는다** (§11).

    세트한 턴에는 이 길이 **열리지 않는다** — 자기 턴에 세웠으므로 상대 턴은
    언제나 다음 턴이고, 그래서 여기서는 턴을 넘긴 뒤를 잰다.
    """
    duel = duel_at(repository, mine=(RELOAD, LUSTER_DRAGON), theirs=(POT_OF_GREED,))
    instance = set_down(duel, P0, RELOAD)

    # 상대 턴으로 넘긴다.
    duel.state.turn.turn_number += 1
    duel.state.turn.turn_player = P1
    duel.state.turn.set_phase(Phase.MAIN1)
    duel.priority = PriorityState.idle(turn_player=P1, phase=Phase.MAIN1)

    # 상대가 발동해 응답 창이 열린다 (RULE-CHAIN-001).
    assert duel.apply(activations(duel, P1, POT_OF_GREED)[0]).accepted
    assert duel.priority.window is ResponseWindow.RESPONSE
    assert duel.priority.holder.is_seat(P0)
    assert duel.turn_player == P1, "턴 플레이어가 바뀌었다"

    candidates = activations(duel, P0, RELOAD)
    assert [a.source for a in candidates] == [instance], "상대 턴의 응답 후보가 없다"

    step = duel.apply(candidates[0])
    assert step.accepted, step.reason
    assert len(duel.chain) == 2, "체인 링크 2 가 되지 않았다"
    assert duel.turn_player == P1
    assert settle_chain(duel).accepted


@pytest.mark.real_card
def test_10_the_same_board_differs_only_by_when_it_was_set(repository):
    """
    **§6 · §9 — set state 가 같고 set history 만 다른 두 판.**

    둘 다 "마법 & 함정 존에 뒷면 리로드 한 장" 이다. 자리도 표시 형식도 같다.
    다른 것은 **언제 세웠는가** 뿐이고, 그래서 한쪽만 발동할 수 있다.
    """
    same_turn = duel_at(repository, mine=(RELOAD, LUSTER_DRAGON))
    set_down(same_turn, P0, RELOAD)

    earlier = duel_at(repository, mine=(RELOAD, LUSTER_DRAGON))
    set_down(earlier, P0, RELOAD)
    next_own_turn(earlier)

    for duel in (same_turn, earlier):
        [card] = szone(duel)
        assert card.card_id == RELOAD
        assert card.position is Position.FACEDOWN

    assert activations(same_turn, P0, RELOAD) == []
    assert activations(earlier, P0, RELOAD) != []


# ======================================================================
# §14 · §15 · §16 — 해시 · 복제 · 난수
# ======================================================================


@pytest.mark.real_card
def test_11_the_state_hash_keeps_the_difference(repository):
    """
    **§14 · §29-5 — 같은 판이라도 세트한 턴이 다르면 다른 해시다.**

    ``canonical_state`` 가 이 차이를 잃으면 탐색이 두 판을 같은 것으로 보고,
    한쪽에서만 적법한 수를 다른 쪽에 쓰게 된다.

    ``rule_uses`` 가 이미 ``canonical_state`` 에 들어 있으므로 **새로 넣은 것이
    없다** — 키에 턴 번호가 있는 덕분이다.
    """
    duel = duel_at(repository, mine=(RELOAD, LUSTER_DRAGON))
    before = duel.state.state_hash()
    set_down(duel, P0, RELOAD)
    after = duel.state.state_hash()
    assert before != after

    # 세트한 턴만 다른 두 판의 해시가 다르다.
    one = duel_at(repository, mine=(RELOAD, LUSTER_DRAGON))
    set_down(one, P0, RELOAD)
    other = duel_at(repository, mine=(RELOAD, LUSTER_DRAGON))
    set_down(other, P0, RELOAD)
    assert one.state.state_hash() == other.state.state_hash()

    other.state.rule_uses.card_counts.clear()
    assert one.state.state_hash() != other.state.state_hash(), (
        "기록을 지워도 해시가 같다 — canonical_state 가 이 차이를 잃었다"
    )


@pytest.mark.real_card
def test_12_the_record_survives_clone_and_stays_independent(repository):
    """
    **§15 · §29-5 · §29-6 — 복제는 정확히 옮기고, 사본의 변경은 번지지 않는다.**

    탐색은 ``clone`` 으로 굴린다. 기록이 복제되지 않으면 사본에서 "세운 적이
    없다" 가 되어 세트한 턴에도 발동할 수 있게 되고, 공유되면 읽어 본 수가
    실제 판을 바꾼다.
    """
    duel = duel_at(repository, mine=(RELOAD, RELOAD, LUSTER_DRAGON))
    turn = duel.state.turn.turn_number
    instance = set_down(duel, P0, RELOAD)

    clone = duel.state.clone()
    assert clone.rule_uses.used_card(turn, P0, instance, SET_ACTION), "복제가 잃었다"
    assert clone.state_hash() == duel.state.state_hash()

    # 사본에서 한 장 더 세운다 — 원본은 그대로여야 한다.
    before = duel.state.state_hash()
    before_counts = dict(duel.state.rule_uses.card_counts)
    fork = Duel(state=clone, priority=duel.priority)
    set_down(fork, P0, RELOAD)

    assert duel.state.state_hash() == before
    assert duel.state.rule_uses.card_counts == before_counts
    assert len(clone.rule_uses.card_counts) == len(before_counts) + 1


@pytest.mark.real_card
def test_13_setting_consumes_no_randomness(repository):
    """**§16 · §29-9 — 세트는 난수를 쓰지 않는다.** 기록도 결정론적이다."""
    duel = duel_at(repository, mine=(RELOAD, POT_OF_GREED, LUSTER_DRAGON))
    before = duel.state.randomness.draws

    set_down(duel, P0, RELOAD)
    set_down(duel, P0, POT_OF_GREED)

    assert duel.state.randomness.draws == before, "세트가 난수를 소비했다"


# ======================================================================
# §12 · §13 · §22 — 관측 경계
# ======================================================================


@pytest.mark.real_card
def test_14_the_set_turn_never_reaches_the_observation(repository):
    """
    **§12 · §13 · §22 · §29-7 — 세트한 턴은 관측에 없다.**

    셋을 함께 잰다.

    ① ``GameStateView`` 의 어떤 필드도 세트한 턴을 말하지 않는다
    ② 상대의 세트 카드는 정체도 가려져 있다 (장수만 공개)
    ③ ``GameStateView`` 에 새 getter 가 생기지 않았다 — 간접 노출도 금지다

    ``rule_uses`` 중 관측으로 나가는 것은 **둘뿐**이다
    (``normal_summons_used`` · ``attacks_used``). 셋째가 생기지 않았다는 것을
    필드 집합으로 고정한다.
    """
    duel = duel_at(repository, mine=(RELOAD, GIFT_OF_GREED, LUSTER_DRAGON))
    set_down(duel, P0, RELOAD)
    set_down(duel, P0, GIFT_OF_GREED)

    for viewer in (P0, P1):
        payload = duel.view(viewer).to_dict()
        leaked = [
            key
            for key in payload
            if "set_turn" in key or "set_this" in key or "set_history" in key
        ]
        assert leaked == [], (viewer, leaked)

    # ① 상대는 정체를 모르고 ② 장수는 안다.
    theirs = duel.view(P1)
    seen = [c for c in theirs.opponent.zone(Zone.SZONE).cards if c is not None]
    assert [(c.card_id, c.name, c.definition) for c in seen] == [
        (None, None, None),
        (None, None, None),
    ]
    assert theirs.opponent.zone(Zone.SZONE).size == 2

    # ③ 관측이 들고 있는 rule-usage 는 여전히 둘뿐이다.
    from engine.game_state_view import GameStateView

    usage_fields = {
        name
        for name in GameStateView.__dataclass_fields__
        if "used" in name or "uses" in name
    }
    assert usage_fields == {"normal_summons_used", "attacks_used"}, usage_fields


# ======================================================================
# §18 · §23 — 방향성과 Evaluation
# ======================================================================


@pytest.mark.real_card
def test_15_reading_the_record_never_writes_it(repository):
    """
    **§18 — SET 은 쓰고, 후보 생성과 타이밍은 읽기만 한다.**

    후보를 몇 번 만들어도 · 타이밍을 몇 번 물어도 기록이 변하지 않아야 한다.
    변한다면 "읽어 보는 것" 이 판을 바꾸는 것이고, 탐색이 실제 판을 오염시킨다.
    """
    duel = duel_at(repository, mine=(RELOAD, POT_OF_GREED, LUSTER_DRAGON))
    reload_id = set_down(duel, P0, RELOAD)
    set_down(duel, P0, POT_OF_GREED)
    snapshot = dict(duel.state.rule_uses.card_counts)
    hash_before = duel.state.state_hash()

    for _ in range(3):
        duel.legal_actions(P0)
        duel.legal_actions(P1)
        duel._set_this_turn(made(P0, reload_id, RELOAD))
        ActivationTimingChecker(duel.view(P0)).check(
            ActivationTiming(duel.chain, duel.priority, set_this_turn=True),
            made(P0, reload_id, RELOAD),
        )

    assert duel.state.rule_uses.card_counts == snapshot
    assert duel.state.state_hash() == hash_before


@pytest.mark.real_card
def test_16_evaluation_does_not_read_the_set_turn(repository):
    """
    **§23 · §29-8 — 평가 점수가 세트한 턴에 반응하지 않는다.**

    같은 판에서 기록만 다르게 만들어 점수를 비교한다. 평가는 **판의 값**을
    읽어야 하고 (``agent/evaluation.py``), 세트한 턴은 규칙 상태다.
    """
    duel = duel_at(repository, mine=(RELOAD, LUSTER_DRAGON))
    set_down(duel, P0, RELOAD)
    evaluator = StateEvaluator()
    before = evaluator.evaluate(duel.view(P0))

    # 기록만 지운다 — 판은 한 칸도 움직이지 않는다.
    duel.state.rule_uses.card_counts.clear()
    after = evaluator.evaluate(duel.view(P0))

    assert before.heuristic == after.heuristic
    assert before.terms == after.terms
    assert before.terminal == after.terminal
    assert before.excluded == after.excluded

    source = (
        __import__("pathlib").Path("agent/evaluation.py").read_text(encoding="utf-8")
    )
    for forbidden in ("rule_uses", "set_this_turn", "SET_SPELL_TRAP", "set_turn"):
        assert forbidden not in source, forbidden


def test_17_no_new_action_kind_and_no_new_engine():
    """
    **§28-16 · §26 — 새 ActionKind 도 새 엔진도 만들지 않았다.**

    세트는 기존 ``SET_SPELL_TRAP`` 행위 하나이고, 기록은 기존
    ``RuleUsageRegistry`` 가 받는다. 그리고 **쓰는 곳이 하나**인지도 센다 —
    둘이면 같은 세트가 두 번 적힐 수 있다.
    """
    import pathlib

    kinds = {k.value for k in PlayerActionKind}
    assert "set_spell_trap" in kinds
    for invented in ("record_set", "set_turn_mark", "flip_set"):
        assert invented not in kinds

    for module in ("engine/duel.py", "engine/set_card.py", "engine/activation_timing.py"):
        source = pathlib.Path(module).read_text(encoding="utf-8")
        for forbidden in ("class SetEngine", "class HistoryEngine", "class TimingEngine"):
            assert forbidden not in source, (module, forbidden)

    # 기록을 **쓰는** 자리는 하나다. ``rule_usage.py`` 는 그릇이므로 센다고
    # 해서 쓰는 쪽이 아니다 — ``record_card(`` 를 **부르는** 곳만 센다.
    callers = [
        module.name
        for module in pathlib.Path("engine").rglob("*.py")
        if "rule_uses.record_card(" in module.read_text(encoding="utf-8")
        and "SET_SPELL_TRAP" in module.read_text(encoding="utf-8")
    ]
    assert callers == ["set_card.py"], callers
