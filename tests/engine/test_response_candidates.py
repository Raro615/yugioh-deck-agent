"""
Phase 3-E-12 — 응답 창의 Action 후보 (STRUCTURAL-34 의 두 번째 조각).

Phase 3-E-11 이 **창을 열었고**, 후보는 ``PASS`` 하나뿐이었다. 이번 Phase 가
그 창에 **실제 발동 후보**를 넣는다.

    창이 열린다  →  ActivationTimingChecker  →  legal PlayerAction

세 관문을 **모두** 통과해야 후보가 된다 (``Duel._activation_actions``).

1. ``ActionValidator``        규칙 쪽 — 자기 카드인가 · 자기 턴인가 · 페이즈 ·
                              빈 칸 · 이번 Phase 가 판정할 수 있는 발동인가
2. ``ActivationTimingChecker`` 스펠 스피드 — RULE-CHAIN-003/004 (**신규**)
3. ``EffectActivator.can_activate`` 구현 쪽 — 등록 · 발동 조건 · 대상

**창이 열렸다 ≠ 무엇이든 발동할 수 있다.** 그리고 ``UNKNOWN`` 은 통과가
아니다 — 세 관문 중 하나라도 ``VALID`` 가 아니면 후보가 되지 않는다.

이번 Phase 가 넓힌 범위는 **한 줄**이다
---------------------------------------
``RULE-SPELLTRAP-007`` 이 속공 마법을 두 문장으로 적는다.

    "These are special Spell Cards that can be activated during **any Phase of
     your turn**, not just your Main Phase. You can **also** activate them
     during your opponent's turn **if you Set the card face-down first**, but
     then you cannot activate the card in the same turn you Set it."

첫 문장은 **세트를 요구하지 않는다** → 패에 있는 속공 마법을 자기 턴에 발동하는
것은 지금 판정할 수 있다. 두 번째 문장은 "세트한 턴" 추적을 요구하고 그 자리가
엔진에 없으므로 → **``UNKNOWN`` 으로 남긴다.**

그래서 **상대 턴의 응답은 여전히 불가능하다.** 그것은 누락이 아니라 규칙이다 —
패에 있는 동안 상대 턴에는 쓸 수 없다 (``test_03``).
"""

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidator
from engine.activation_timing import (
    ActivationTiming,
    ActivationTimingChecker,
    SpellSpeed,
)
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.priority import PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

P0, P1 = 0, 1

LUSTER_DRAGON = 11091375  # 통상 몬스터
POT_OF_GREED = 55144522  # 통상 마법 — 스펠 스피드 1
RELOAD = 22589918  # 리로드 — 속공 마법 (스펠 스피드 2) · 대상 없음
TYPHOON = 5318639  # 싸이크론 — 속공 마법 · 대상 있음
GIFT_OF_GREED = 5915629  # 욕망의 선물 — 함정 (스펠 스피드 2)


def duel_at(repository, *, mine=(), theirs=(), turn_player=P0, phase=Phase.MAIN1):
    """실제 엔진으로 만든 판 하나."""
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


def open_a_window(duel):
    """P0 가 욕망의 항아리를 발동해 체인 1 을 쌓고 창을 연다."""
    step = duel.apply(activations(duel, P0, POT_OF_GREED)[0])
    assert step.accepted, step.reason
    return step


# ======================================================================
# §21-1 · §21-3 — 창에는 PASS 가 있고, 자리는 상대다
# ======================================================================


@pytest.mark.real_card
def test_01_the_response_window_still_has_pass(repository):
    """**§21-1 — ``PASS`` 가 사라지지 않았다** (Phase 3-E-11 의 결과 유지)."""
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    open_a_window(duel)

    assert duel.priority.window is ResponseWindow.RESPONSE
    assert duel.priority.holder.is_seat(P1)
    assert [a.kind for a in duel.legal_actions(P1).allowed] == [
        PlayerActionKind.PASS
    ]


@pytest.mark.real_card
def test_02_the_response_candidate_actor_is_the_window_holder(repository):
    """
    **§21-3 · §12 — 후보의 ``actor`` 는 창을 쥔 자리다.**

    ``RULE-CHAIN-001`` 이 적는다 — "If your opponent does not respond, **you
    may activate a second effect** and create a Chain to your own card's
    activation." 그래서 상대가 패스하면 **발동한 쪽**이 응답 자리가 되고,
    거기서 후보가 생긴다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED, RELOAD, LUSTER_DRAGON))
    open_a_window(duel)

    # 창을 쥔 쪽(P1)에게는 발동 후보가 없다 — 아래 test_03 의 이유다.
    assert activations(duel, P1) == []

    assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted
    assert duel.priority.holder.is_seat(P0)

    candidates = activations(duel, P0)
    assert candidates, duel.legal_actions(P0).allowed
    for candidate in candidates:
        assert candidate.actor == P0 == duel.priority.holder.seat
        assert candidate.effect_ref.card_id == RELOAD


@pytest.mark.real_card
def test_03_the_opponent_cannot_respond_from_hand_and_that_is_the_rule(
    repository,
):
    """
    **상대 턴의 응답이 없는 것은 누락이 아니라 규칙이다.**

    ``RULE-SPELLTRAP-007`` 이 상대 턴의 발동에 "**if you Set the card
    face-down first**" 를 요구한다. 패에 있는 동안은 상대 턴에 쓸 수 없고,
    그래서 이것은 ``UNKNOWN`` 이 아니라 **``INVALID``** 다 — 규칙이 금지한다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,), theirs=(RELOAD, TYPHOON))
    open_a_window(duel)

    assert activations(duel, P1) == []

    validator = ActionValidator(duel.view(P1))
    source = next(
        c.instance_id
        for c in duel.state.player(P1).zones[Zone.HAND]
        if c.card_id == RELOAD
    )
    verdict = validator.validate(
        PlayerAction.activate_effect(
            actor=P1, source=source, effect_ref=EffectRef(RELOAD, 0)
        )
    )
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.NOT_TURN_PLAYER
    assert "세트" in verdict.reason


@pytest.mark.real_card
def test_04_a_trap_in_hand_stays_unknown_not_a_candidate(repository):
    """
    **함정은 여전히 ``UNKNOWN``** 이다 — ``RULE-SPELLTRAP-009`` 가 세트를
    앞세우고 "세트한 턴" 제약까지 요구하는데 그 자리가 없다.

    후보가 아니면서 **규칙 위반으로도 적히지 않는다.**
    """
    duel = duel_at(repository, mine=(POT_OF_GREED, GIFT_OF_GREED))
    assert activations(duel, P0, GIFT_OF_GREED) == []

    validator = ActionValidator(duel.view(P0))
    source = next(
        c.instance_id
        for c in duel.state.player(P0).zones[Zone.HAND]
        if c.card_id == GIFT_OF_GREED
    )
    verdict = validator.validate(
        PlayerAction.activate_effect(
            actor=P0, source=source, effect_ref=EffectRef(GIFT_OF_GREED, 0)
        )
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert "activation-timing" in (verdict.missing_rule or "")


# ======================================================================
# §21-4 — 창이 없으면 아무것도 변하지 않는다
# ======================================================================


@pytest.mark.real_card
def test_05_the_normal_window_candidates_are_unchanged(repository):
    """
    **§21-4 · §20 — 창이 닫혀 있으면 기존 후보가 그대로다.**

    ``legal_actions`` 에 더한 분기는 "창이 열려 있고 이 자리가 그것을 쥐고
    있으면" 이고, 닫혀 있으면 기존 경로로 떨어진다. 그리고 체인이 비어 있을
    때 타이밍 관문은 **아무것도 거르지 않는다** — checker 가 "체인이 비어 있어
    스펠 스피드 제약이 걸리지 않습니다" 로 통과시킨다.
    """
    duel = duel_at(repository, mine=(LUSTER_DRAGON, POT_OF_GREED))
    assert not duel.priority.is_open
    assert sorted({a.kind.name for a in duel.legal_actions(P0).allowed}) == [
        "ACTIVATE_EFFECT",
        "END_PHASE",
        "NORMAL_SUMMON",
        "SET_MONSTER",
        "SET_SPELL_TRAP",
    ]
    assert duel.legal_actions(P1).allowed == ()

    # 체인이 비어 있을 때 관문이 통과시키는 것을 직접 확인한다.
    checker = ActivationTimingChecker(duel.view(P0))
    verdict = checker.check(
        ActivationTiming(duel.chain, duel.priority),
        activations(duel, P0, POT_OF_GREED)[0],
    )
    assert verdict.validity is ActionValidity.VALID
    assert "체인이 비어 있어" in verdict.reason


# ======================================================================
# §21-5 · §21-6 — 스펠 스피드 관문과 UNKNOWN
# ======================================================================


@pytest.mark.real_card
def test_06_spell_speed_one_is_not_a_response_candidate(repository):
    """
    **§21-5 — 스펠 스피드 1 은 응수할 수 없다** (``RULE-CHAIN-004``).

        "Spells (Normal, Equip, Continuous, Field, Ritual) … **cannot be
         activated in response to any other effects.**"

    패에 욕망의 항아리가 두 장 있어도, 체인이 쌓인 뒤에는 두 번째 장이 후보가
    되지 않는다. 관문이 ``SPELL_SPEED_TOO_LOW`` 로 거절한다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED, POT_OF_GREED, RELOAD, LUSTER_DRAGON))
    open_a_window(duel)
    assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted

    # 속공 마법은 후보이고, 두 번째 욕망의 항아리는 후보가 아니다.
    assert {a.effect_ref.card_id for a in activations(duel, P0)} == {RELOAD}

    # 관문이 왜 거절했는지 직접 확인한다.
    checker = ActivationTimingChecker(duel.view(P0))
    source = next(
        c.instance_id
        for c in duel.state.player(P0).zones[Zone.HAND]
        if c.card_id == POT_OF_GREED
    )
    verdict = checker.check(
        ActivationTiming(duel.chain, duel.priority),
        PlayerAction.activate_effect(
            actor=P0, source=source, effect_ref=EffectRef(POT_OF_GREED, 0)
        ),
    )
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.SPELL_SPEED_TOO_LOW
    assert checker.spell_speed(source).speed is SpellSpeed.NORMAL


@pytest.mark.real_card
def test_07_an_unknown_timing_is_not_promoted_to_a_candidate(repository):
    """
    **§21-6 — ``UNKNOWN`` 은 ``VALID`` 가 아니다.**

    관문이 "모른다" 고 하면 후보가 되지 않는다. 뒷면 카드가 그 자리다 —
    정체를 모르므로 스펠 스피드를 판정할 수 없다. 그 답은 ``INVALID`` 도
    아니다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED, RELOAD, LUSTER_DRAGON))
    open_a_window(duel)
    assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted

    # ``UNKNOWN`` 이 나오는 자리 — 뒷면 카드의 스펠 스피드.
    hidden = duel.state.create_instance(RELOAD, owner=P1, zone=Zone.HAND)
    duel.state.move(hidden, Zone.SZONE, to_player=P1, position=Position.FACEDOWN)
    mine_view = ActivationTimingChecker(duel.view(P0))
    classified = mine_view.spell_speed(hidden.instance_id)
    assert not classified.is_known
    unknown = mine_view.check(
        ActivationTiming(duel.chain, duel.priority),
        PlayerAction.activate_effect(
            actor=P0, source=hidden.instance_id, effect_ref=EffectRef(RELOAD, 0)
        ),
    )
    assert unknown.validity is ActionValidity.UNKNOWN
    assert not unknown.permits_execution
    # 그리고 후보 목록에 들어가지 않는다.
    assert hidden.instance_id not in {a.source for a in activations(duel, P0)}


# ======================================================================
# §21-7 · §21-8 — 턴 플레이어와 가려진 정보
# ======================================================================


@pytest.mark.real_card
def test_08_the_turn_player_never_changes(repository):
    """
    **§21-7 · §13 — 응답 후보를 만들려고 ``turn_player`` 를 바꾸지 않는다.**

    응답 창은 **우선권의 문맥**이다. 턴 자체가 넘어가는 것이 아니다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED, RELOAD, LUSTER_DRAGON))
    assert duel.turn_player == P0

    open_a_window(duel)
    assert duel.turn_player == P0
    assert duel.priority.holder.is_seat(P1)  # 우선권만 옮겨 갔다

    assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted
    assert duel.turn_player == P0
    assert duel.priority.holder.is_seat(P0)

    assert duel.apply(activations(duel, P0)[0]).accepted
    assert duel.turn_player == P0
    assert duel.state.turn.turn_number == 2


@pytest.mark.real_card
def test_09_candidate_generation_leaks_nothing_hidden(repository):
    """
    **§21-8 · §14 — 후보를 만들려고 가려진 정보를 읽지 않는다.**

    상대의 패에 무엇이 있든 내 후보 목록과 내 관측이 같아야 한다. 달라지면
    후보 생성이 상대 패를 읽은 것이다.
    """
    seen = []
    for theirs in ((), (RELOAD,), (TYPHOON, GIFT_OF_GREED), (POT_OF_GREED,) * 3):
        duel = duel_at(
            repository, mine=(POT_OF_GREED, RELOAD, LUSTER_DRAGON), theirs=theirs
        )
        open_a_window(duel)
        assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted
        seen.append(
            tuple(sorted(a.canonical_state() for a in activations(duel, P0)))
        )
        view = duel.view(P0)
        assert view.opponent.hand.concealed
        assert view.opponent.hand.cards == ()
    assert len(set(seen)) == 1, seen


# ======================================================================
# §17 — Chain Link 2
# ======================================================================


@pytest.mark.real_card
def test_10_a_second_link_is_added_and_resolves_in_reverse(repository):
    """
    **§17 — 체인 링크 2 가 실제로 쌓이고 역순으로 풀린다.**

    ``RULE-CHAIN-007`` 이 적는다 — "Once the Chain is completed, the outcome is
    resolved **starting with the most recent card** to be activated at the top
    of the Chain and proceeding down to Chain Link 1."

    기존 ``ChainResolver.resolve_all`` 을 그대로 쓴다 — 새 Chain Engine 을
    만들지 않았다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED, RELOAD, LUSTER_DRAGON))
    player = duel.state.player(P0)

    open_a_window(duel)
    assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted
    assert duel.apply(activations(duel, P0, RELOAD)[0]).accepted

    # 두 링크가 쌓였고, 둘 다 P0 이 만들었다 (RULE-CHAIN-001 의 두 번째 발동).
    assert [(l.chain_number, l.actor, l.effect_ref.card_id) for l in duel.chain.links] == [
        (1, P0, POT_OF_GREED),
        (2, P0, RELOAD),
    ]
    assert len(duel.pending_spells) == 2
    # 창이 다시 열렸고, 자리는 링크 2 를 만든 쪽의 상대다.
    assert duel.priority.holder.is_seat(P1)

    # 둘 다 패스 → 역순 해결.
    assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted
    final = duel.apply(duel.legal_actions(P0).allowed[0])
    assert final.accepted, final.reason

    assert duel.chain.is_empty
    assert duel.pending_spells == ()
    # 두 장 모두 묘지로 갔다 (RULE-SPELLTRAP-002).
    assert sorted(c.card_id for c in player.zones[Zone.GRAVE]) == sorted(
        [POT_OF_GREED, RELOAD]
    )
    # 리로드(링크 2)가 먼저 풀려 패를 덱에 넣고 1장 뽑았고, 그 다음에
    # 욕망의 항아리(링크 1)가 2장 뽑았다 — 덱 20 → 18.
    assert len(player.deck) == 18


# ======================================================================
# 이번 Phase 가 드러낸 한계 — 숨기지 않고 적는다
# ======================================================================


@pytest.mark.real_card
def test_11_a_candidate_can_still_be_refused_when_its_condition_reads_its_own_zone(
    repository,
):
    """
    **STRUCTURAL-134 — 해결되었다** (Phase 3-E-13).

    이 시험이 Phase 3-E-12 에서 처음 적힌 모습은 **"후보가 되었는데 ``apply``
    가 거절한다"** 를 고정하는 것이었다. 그때의 설명은 이랬다.

        ``_activation_actions`` 는 ``can_activate`` 를 배치 **전**에 묻고,
        ``_apply_activation`` 은 배치 **뒤**에 발동한다. 그 사이에 발동한
        카드가 패를 떠나므로 자기 패를 읽는 조건은 답이 뒤집힌다. 리로드가
        그 첫 카드다.

    **그 시험이 가졌던 잘못된 가정은 하나다** — "리로드의 조건은 '자신 패에
    1장 이상' 이다". 공식 스크립트는 그렇게 적지 않았다.

        c22589918.lua 의 ``s.target`` —
        ``Duel.IsExistingMatchingCard(
            Card.IsAbleToDeck, tp, LOCATION_HAND, 0, 1, e:GetHandler())``

    마지막 ``e:GetHandler()`` 가 **제외 카드**다. 즉 조건은 "**리로드 말고**
    자신 패에 1장 이상" 이고, 엔진의 정의가 그 인자를 옮기지 않았다.

    그래서 두 가지가 함께 고쳐졌다.

    1. 조건이 **자기 자신을 셀지 적는다** (``excluding_source=True``). 그러면
       조건의 답이 배치 전과 후에 **같다** — 뒤집히는 조건은 "자기를 셀지
       적지 않은 조건" 이었다는 뜻이다.
    2. 관문을 ``legal_actions`` 와 ``apply`` 가 **같은 함수로, 같은 판에서**
       지난다 (``Duel._activation_gate``).

    지금 고정하는 것은 **파리티**다 — 패에 리로드 하나뿐이면 후보가 되지
    **않고**, 그 행위를 발동 경로에 직접 넣어도 **같은 이유로** 거절된다.
    둘의 판정이 갈라지지 않는다.

    ``_apply_activation`` 을 직접 부르는 이유
    ----------------------------------------
    ``Duel.apply`` 는 들어온 행위가 ``legal_actions`` 에 있는지부터 보고
    (``"… 는 지금 허가된 행위가 아닙니다"``), 없으면 발동 경로에 **닿지도
    않는다.** 그 바깥 문이 막아 주는 것과 **안쪽 관문이 스스로 막는 것**은
    다른 주장이고, 뒤쪽이 이 Phase 가 고친 것이다. 그래서 둘을 따로 재고,
    바깥 문도 함께 확인한다.
    """
    duel = duel_at(repository, mine=(RELOAD,))  # 패에 리로드 **하나뿐**
    assert activations(duel, P0, RELOAD) == [], "후보가 되어서는 안 된다"

    # 후보가 아닌 그 행위를 손으로 만든다.
    reload_card = next(
        c for c in duel.state.player(P0).hand if c.card_id == RELOAD
    )
    forced = PlayerAction.activate_effect(
        actor=P0, source=reload_card.instance_id, effect_ref=EffectRef(RELOAD, 0)
    )

    # ① 바깥 문 — 후보에 없으므로 발동 경로에 닿지 않는다.
    outer = duel.apply(forced)
    assert not outer.accepted
    assert "허가된 행위가 아닙니다" in outer.reason, outer.reason

    # ② 안쪽 관문 — 바깥 문을 건너뛰어도 **같은 판에서 스스로** 거절한다.
    inner = duel._apply_activation(forced)
    assert not inner.accepted
    assert "발동 조건이 거짓" in inner.reason, inner.reason

    # 판은 **한 번도** 바뀌지 않았다 — 되돌린 것이 아니라 건드리지 않았다.
    assert len(duel.state.player(P0).zones[Zone.HAND]) == 1
    assert len(duel.state.player(P0).zones[Zone.SZONE]) == 0
    assert duel.chain.is_empty
    assert duel.priority.window is ResponseWindow.NONE
    assert duel.pending_spells == ()

    # 패에 한 장이 더 있으면 조건이 성립한다 — 후보가 되고 발동도 된다.
    duel = duel_at(repository, mine=(RELOAD, LUSTER_DRAGON))
    candidates = activations(duel, P0, RELOAD)
    assert candidates
    assert duel.apply(candidates[0]).accepted


@pytest.mark.real_card
def test_12_only_the_window_holder_ever_gets_activation_candidates(repository):
    """
    **§12 — 후보를 받는 자리는 **정확히 하나**다.**

    세 가지를 함께 고정한다. 셋 다 "상대 패에 발동할 수 있는 카드가 있어도"
    라는 조건을 붙이는 것이 핵심이다 — 패가 비어 있으면 어떤 잘못된 조건도
    후보 0개를 내므로 아무것도 증명하지 못한다.

    ① 창이 **닫혀** 있으면 턴 플레이어만 받는다 (상대는 0개)
    ② 창이 **열려** 있으면 **쥔 자리만** 받는다 (턴 플레이어라도 0개)
    ③ 창이 쥔 자리로 넘어오면 그때 받는다

    이 시험이 없을 때 고의 위반 ``holds(seat)`` → ``seat == turn_player`` 가
    **아무 테스트도 깨뜨리지 못했다.** 지금은 ②가 잡는다.

    **잡히지 않는 위반 하나를 적어 둔다.** 분기 조건에서 창 조건을 없애
    (``holds(seat) or seat != turn_player``) 창이 닫혀 있을 때도 상대가
    ``_activation_actions`` 에 들어가게 만들어도 후보는 0개다 — 안쪽에서
    ``ActionValidator`` 의 ``IsTurnPlayer`` 가 다시 막기 때문이다. 관문이
    **둘 다 독립적으로** 같은 것을 막고 있으므로 하나를 약하게 해도 결과가
    보이지 않는다. 숨기지 않고 적는다: 이것은 구멍이 아니라 이중 방어다.
    """
    # 양쪽 모두 자기 턴이라면 발동할 수 있는 카드를 패에 들고 있다.
    duel = duel_at(
        repository,
        mine=(POT_OF_GREED, RELOAD, LUSTER_DRAGON),
        theirs=(POT_OF_GREED, RELOAD, LUSTER_DRAGON),
    )

    # ① 창이 닫혀 있다 — 턴 플레이어만.
    assert not duel.priority.is_open
    assert activations(duel, P0), "턴 플레이어는 받는다"
    assert activations(duel, P1) == [], "창이 없는데 상대가 후보를 받았다"

    # ② 창이 열렸고 P1 이 쥐고 있다 — **턴 플레이어 P0 도 0개**다.
    open_a_window(duel)
    assert duel.priority.holder.is_seat(P1)
    assert duel.turn_player == P0
    assert activations(duel, P0) == [], "창을 쥐지 않은 턴 플레이어가 받았다"
    assert activations(duel, P1) == [], "상대는 패에서 상대 턴에 발동할 수 없다"

    # ③ 우선권이 P0 으로 넘어오면 그때 받는다.
    assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted
    assert duel.priority.holder.is_seat(P0)
    assert activations(duel, P0), "창을 쥐었는데 받지 못했다"
    assert activations(duel, P1) == []


def test_13_the_timing_gate_refuses_anything_that_is_not_valid():
    """
    **§7 — 관문은 ``VALID`` 만 통과시킨다. ``UNKNOWN`` 도 아니다.**

    ``is not ActionValidity.VALID`` 가 ``is ActionValidity.INVALID`` 로
    약해지면 ``UNKNOWN`` 이 후보로 올라간다. 그 위반을 주입했을 때 **아무
    테스트도 잡지 못했다** — 후보가 관문에 닿으려면 이미 ``ActionValidator``
    를 통과해야 하고, 그러려면 카드가 패에서 보여야 하므로 스펠 스피드가
    언제나 판정된다. 즉 ``UNKNOWN`` 분기가 **후보 생성 경로에서는 도달
    불가**다.

    그래서 지금 잡을 수 있는 방법으로 잡는다 — 비교가 약해지면 깨진다.
    세트된 카드의 발동이 범위 안으로 들어오는 날 실행으로 다시 재야 한다.

    **읽는 자리가 바뀌었다** (Phase 3-E-13)
    ---------------------------------------
    이 시험은 처음에 ``Duel._activation_actions`` 의 원문을 읽었다. 그때는
    관문 셋이 그 함수 안에 적혀 있었기 때문이다. 그 가정이 **틀렸음이
    드러났다** — 관문이 거기 있었던 것이 바로 STRUCTURAL-134 의 원인이었다.
    ``apply`` 가 자기 관문을 따로 세웠고, 두 벌이 서로 다른 판을 읽었다.

    지금 관문은 :meth:`Duel._activation_gate` 하나이고 ``legal_actions`` 와
    ``apply`` 가 둘 다 그것을 부른다. 그래서 읽을 자리도 그 하나다 — 주장은
    그대로이고 (``VALID`` 만 통과한다), **어디에 적혀 있어야 하는가**에 대한
    가정만 고쳤다.
    """
    import inspect

    source = inspect.getsource(Duel._activation_gate)
    assert "ActivationTimingChecker(validator.view).check(" in source
    assert "is not ActionValidity.VALID" in source, source
    # "INVALID 가 아니면 통과" 로 약해지지 않았다.
    assert "is ActionValidity.INVALID" not in source
    # 그리고 후보 생성 쪽은 **자기 관문을 다시 세우지 않는다.**
    candidates = inspect.getsource(Duel._activation_actions)
    assert "_activation_gate(" in candidates
    assert "ActivationTimingChecker(" not in candidates
    assert "can_activate(" not in candidates
