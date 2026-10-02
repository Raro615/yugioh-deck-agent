"""
Phase 3-E-13 — 발동 관문 하나 · 판 하나 (STRUCTURAL-134 의 해결).

    legal_actions 가 허가한 발동은 **apply 할 수 있다.**

Phase 3-E-12 가 응답 창에 발동 후보를 넣었고, 거기서 후보가 되었는데
``apply`` 가 거절하는 카드가 하나 나왔다 (리로드). 그 자리를 STRUCTURAL-134
로 적어 두고 이 Phase 가 닫는다.

원인은 **둘**이었다
-------------------
① **관문이 두 벌이었고, 두 벌이 서로 다른 판을 읽었다.**

    ``_activation_actions``   배치 **전**의 판에서 세 관문
    ``_apply_activation``     배치 **뒤**의 판에서 ``activate`` 의 재검사

   발동한 마법은 필드에 놓이면서 패를 떠나므로 (RULE-SPELLTRAP-002), 자기
   패를 읽는 조건은 그 사이에 답이 뒤집혔다.

② **조건이 자기 자신을 셀지 적지 않았다.** 리로드의 공식 스크립트는 제외
   카드를 분명히 적는다.

       c22589918.lua 의 ``s.target`` —
       ``Duel.IsExistingMatchingCard(
           Card.IsAbleToDeck, tp, LOCATION_HAND, 0, 1, e:GetHandler())``

   마지막 ``e:GetHandler()`` 가 리로드 자신이다. 엔진은 그 인자를 옮기지
   않았고, 그래서 "자신 패에 1장 이상" 이 되어 **배치 전에는 자신까지
   세었다.**

②가 ①의 **증상이 드러난 이유**다. 자기를 셀지 적어 둔 조건은 자리를 옮겨도
답이 뒤집히지 않으므로, ``_zone`` 을 읽는 조건이 뒤집히는 것은 **그 조건이
덜 옮겨졌다는 신호**다.

이 Phase 가 하지 않은 것
------------------------
- ``can_activate`` 를 무조건 통과시키지 않았다. 리로드는 패에 자신 하나뿐일
  때 **여전히 거절된다** — 공식 스크립트가 그렇게 적었기 때문이다.
- ``apply`` 의 판정을 생략하지 않았다. 오히려 **늘었다** — 예전에는 손으로
  만든 허가(``ValidationResult.valid("legal_actions 가 허가한 발동입니다")``)
  가 ``ActionValidator`` 를 건너뛰었고, 지금은 실제 검증기가 판정한다.
- rollback 계층을 만들지 않았다 (ADR-008 은 그대로). **필요를 없앴다** —
  관문이 배치 앞에 있으면 거절된 발동은 판을 건드리지 않는다.
"""

import inspect

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidator
from engine.condition import PlayerRef, ZoneCountAtLeast
from engine.condition.context import ConditionContext
from engine.condition.result import ConditionResult
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.priority import PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.validation import ActionValidity
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db, settle_chain

pytestmark = requires_official_db

P0, P1 = 0, 1

LUSTER_DRAGON = 11091375  # 통상 몬스터
POT_OF_GREED = 55144522  # 통상 마법 — 스펠 스피드 1
RELOAD = 22589918  # 리로드 — 속공 마법 (스펠 스피드 2) · 자기 패를 읽는다
TYPHOON = 5318639  # 싸이크론 — 속공 마법 · 대상 있음
GIFT_OF_GREED = 5915629  # 욕망의 선물 — 함정 (범위 밖)


def duel_at(
    repository,
    *,
    mine=(),
    theirs=(),
    szone=(),
    their_szone=(),
    turn_player=P0,
    phase=Phase.MAIN1,
):
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
    for card_id in szone:
        state.create_instance(
            card_id, owner=P0, zone=Zone.SZONE, position=Position.FACEDOWN
        )
    for card_id in their_szone:
        # **앞면**으로 둔다. 뒷면 카드는 정체가 가려져 있어 "마법 · 함정인가"
        # 를 확정할 수 없고, 그래서 대상 후보가 되지 않는다 (관측 경계).
        state.create_instance(
            card_id, owner=P1, zone=Zone.SZONE, position=Position.FACEUP
        )
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


def hand_action(duel, seat, card_id, ordinal=0):
    """후보 목록을 **거치지 않고** 만든 발동 행위 하나."""
    card = next(c for c in duel.state.player(seat).hand if c.card_id == card_id)
    return PlayerAction.activate_effect(
        actor=seat, source=card.instance_id, effect_ref=EffectRef(card_id, ordinal)
    )


def board(duel, seat=P0):
    """판이 바뀌었는지 보기 위한 최소 스냅숏."""
    player = duel.state.player(seat)
    return (
        len(player.zones[Zone.HAND]),
        len(player.zones[Zone.SZONE]),
        len(player.zones[Zone.GRAVE]),
        len(player.zones[Zone.DECK]),
    )


# ======================================================================
# §7 — 권위 있는 관문은 하나다
# ======================================================================


def test_01_there_is_exactly_one_activation_gate():
    """
    **§7 · §22 — 관문을 **한 곳**에만 적는다.**

    ``legal_actions`` 쪽과 ``apply`` 쪽이 모두 ``_activation_gate`` 를 부르고,
    **자기 관문을 따로 세우지 않는다.** 판정이 두 곳에 적히면 그 둘은 반드시
    갈라지고, 갈라진 결과가 STRUCTURAL-134 였다.
    """
    candidates = inspect.getsource(Duel._activation_actions)
    apply_path = inspect.getsource(Duel._apply_activation)

    assert "_activation_gate(" in candidates
    assert "_activation_gate(" in apply_path

    for source, where in ((candidates, "후보 생성"), (apply_path, "적용")):
        assert "ActivationTimingChecker(" not in source, where
        assert "can_activate(" not in source, where
        assert "validator.validate(" not in source, where


def test_02_apply_no_longer_hands_itself_a_verdict():
    """
    **§5-3 · §22 — ``apply`` 가 자기에게 허가를 써 주지 않는다.**

    Phase 3-E-3 은 ``activate`` 에 이것을 넣어 줬다.

        ``authorization=ValidationResult.valid(
            "legal_actions 가 허가한 발동입니다.")``

    그 문자열이 하는 일은 ``EffectActivator._verdict`` 가 **실제 검증기를
    부르지 않게** 만드는 것이었다. 넣어 줘야 했던 이유는 ``test_04`` 가
    실행으로 보여 준다 — 배치 뒤의 판에서는 검증기가 판정을 할 수 없다.

    지금은 그 자리에 ``_activation_gate`` 의 **실제 판정**이 들어간다.
    """
    source = inspect.getsource(Duel._apply_activation)
    assert "legal_actions 가 허가한 발동입니다" not in source
    assert "authorization=gate" in source
    # 그리고 관문은 배치보다 **앞**에 있다.
    assert source.index("_activation_gate(") < source.index("_placement.place(")
    assert source.index("_activator.activate(") < source.index("_placement.place(")


# ======================================================================
# §10 — 후보 ↔ 적용 파리티
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize(
    "mine,theirs,their_szone",
    [
        ((POT_OF_GREED,), (), ()),
        ((RELOAD, LUSTER_DRAGON), (), ()),
        ((POT_OF_GREED, RELOAD, LUSTER_DRAGON), (LUSTER_DRAGON,), ()),
        # 싸이크론은 **대상이 있어야** 후보가 된다 (Phase 3-E-4). 상대 필드에
        # 세트한 카드 둘을 두면 후보가 **둘**이고, 그 둘이 서로 다른 수다.
        ((TYPHOON, LUSTER_DRAGON), (), (GIFT_OF_GREED, GIFT_OF_GREED)),
        (
            (POT_OF_GREED, POT_OF_GREED, RELOAD, TYPHOON, LUSTER_DRAGON),
            (),
            (GIFT_OF_GREED,),
        ),
    ],
)
def test_03_every_candidate_can_be_applied(repository, mine, theirs, their_szone):
    """
    **§6 · §10 — LEGAL ACTION → APPLY 가능한 Action.**

    후보 하나하나를 **새 판**에서 적용한다. 같은 판에서 이어 적용하면 앞의
    발동이 뒤의 조건을 바꾸므로, 파리티를 재는 것이 아니라 다른 것을 재게
    된다.

    이 시험이 STRUCTURAL-134 를 **실행으로** 재는 자리다. 고치기 전에는
    두 번째 줄(리로드 하나뿐인 패)에서 깨졌다.
    """
    duel = duel_at(
        repository, mine=mine, theirs=theirs, their_szone=their_szone
    )
    candidates = activations(duel, P0)
    assert candidates, "후보가 없으면 아무것도 증명하지 못한다"

    for candidate in candidates:
        fork = duel_at(
            repository, mine=mine, theirs=theirs, their_szone=their_szone
        )
        same = next(
            a
            for a in activations(fork, P0)
            if a.effect_ref == candidate.effect_ref
            and a.targets == candidate.targets
            and a.source == candidate.source
        )
        step = fork.apply(same)
        assert step.accepted, f"{same.effect_ref} 를 허가했는데 거절했다: {step.reason}"


@pytest.mark.real_card
def test_04_after_placement_nothing_can_be_judged(repository):
    """
    **§4 · §7 — 배치 뒤의 판은 판정할 수 없는 판이다.**

    이것이 "관문을 배치 **앞**에 둔다" 의 근거다. 의견이 아니라 측정이다.

    카드가 패를 떠나면 ``_activation_out_of_scope`` 가 "패가 아니라 … 에서의
    발동이다" 로 범위 밖을 선언한다 (필드에서의 발동은 실제 규칙에서 적법
    하므로 ``INVALID`` 가 아니라 ``UNKNOWN`` 이다). 그래서 배치 뒤에는
    **지금 잘 되는 욕망의 항아리까지** 판정이 ``UNKNOWN`` 이 된다.

    ``UNKNOWN`` 은 허가가 아니므로, 배치 뒤의 판을 권위 있는 판으로 삼으면
    ``apply`` 는 **아무것도 발동할 수 없다.** 예전 순서가 손으로 만든 허가를
    필요로 했던 이유가 이것이다.
    """
    for card_id in (POT_OF_GREED, RELOAD):
        duel = duel_at(repository, mine=(card_id, LUSTER_DRAGON))
        action = activations(duel, P0, card_id)[0]

        before = ActionValidator(duel.view(P0)).validate(action)
        assert before.validity is ActionValidity.VALID

        duel._placement.place(duel.state, action.source, action.actor)

        after = ActionValidator(duel.view(P0)).validate(action)
        assert after.validity is ActionValidity.UNKNOWN, card_id
        # 발동 계층도 같다 — 허가를 받지 못한다.
        refused = duel._activator.can_activate(duel.state, duel.chain, action)
        assert refused.validity is ActionValidity.UNKNOWN, card_id


# ======================================================================
# §11 — 거절되는 경우들. 후보도 아니고, 적용도 안 되고, 판도 안 바뀐다
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize(
    "case,setup,build,fragment",
    [
        (
            # 관측이 행위자의 시점이므로 **보이지 않는다** 가 먼저 나온다 —
            # ``INVALID`` 가 아니라 ``UNKNOWN`` 이고, ``UNKNOWN`` 은 허가가
            # 아니므로 결과는 같다 (거절 · 판 그대로).
            "상대 자리에서 내 카드를 발동한다",
            {"mine": (POT_OF_GREED,)},
            lambda duel: PlayerAction.activate_effect(
                actor=P1,
                source=next(iter(duel.state.player(P0).hand)).instance_id,
                effect_ref=EffectRef(POT_OF_GREED, 0),
            ),
            "관측에 보이지 않습니다",
        ),
        (
            "상대 턴에 패의 속공 마법을 발동한다 (RULE-SPELLTRAP-007)",
            {"mine": (RELOAD, LUSTER_DRAGON), "turn_player": P1},
            lambda duel: hand_action(duel, P0, RELOAD),
            "자신의 턴이 아닙니다",
        ),
        (
            "메인 페이즈가 아닌 때 통상 마법을 발동한다 (RULE-SPELLTRAP-001)",
            {"mine": (POT_OF_GREED,), "phase": Phase.END},
            lambda duel: hand_action(duel, P0, POT_OF_GREED),
            "메인 페이즈가 아닙니다",
        ),
        (
            "마법 & 함정 존이 꽉 찼다 (RULE-SPELLTRAP-002)",
            {
                "mine": (POT_OF_GREED,),
                "szone": (LUSTER_DRAGON,) * 5,
            },
            lambda duel: hand_action(duel, P0, POT_OF_GREED),
            "빈 칸이 없습니다",
        ),
        (
            "발동 조건이 거짓이다 (리로드 · e:GetHandler 제외)",
            {"mine": (RELOAD,)},
            lambda duel: hand_action(duel, P0, RELOAD),
            "발동 조건이 거짓입니다",
        ),
        (
            "함정은 이 Phase 가 판정하지 못한다 (RULE-SPELLTRAP-009)",
            {"mine": (GIFT_OF_GREED, LUSTER_DRAGON)},
            lambda duel: hand_action(duel, P0, GIFT_OF_GREED),
            "아직 구현하지 않은 규칙",
        ),
    ],
)
def test_05_a_refused_activation_changes_nothing(
    repository, case, setup, build, fragment
):
    """
    **§11 — 거절은 세 가지를 함께 만족한다.**

        ① 후보가 아니다
        ② 발동 경로가 **스스로** 거절한다 (바깥의 후보 검사에 기대지 않는다)
        ③ 판이 **한 줄도** 바뀌지 않는다

    ③이 이 Phase 가 새로 얻은 것이다. 예전에는 카드를 놓았다가 되돌렸으므로
    "바뀌었다가 돌아왔다" 였고, 지금은 **떠나지 않는다.**
    """
    duel = duel_at(repository, **setup)
    action = build(duel)
    before = board(duel, action.actor)

    assert action not in duel.legal_actions(action.actor).allowed, case

    step = duel._apply_activation(action)
    assert not step.accepted, case
    assert fragment in step.reason, (case, step.reason)

    assert board(duel, action.actor) == before, case
    assert duel.chain.is_empty, case
    assert duel.priority.window is ResponseWindow.NONE, case
    assert duel.pending_spells == (), case


@pytest.mark.real_card
def test_06_spell_speed_one_cannot_join_a_chain(repository):
    """
    **§11 · §8 — 체인이 쌓이면 스펠 스피드 1 은 후보도 적용도 아니다**
    (RULE-CHAIN-004 — "cannot be activated in response to any other
    effects").

    관문 셋 중 **두 번째**가 혼자 막는 자리이고, 그것이 공용 관문 안에
    들어와 있는지를 실행으로 잰다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED, POT_OF_GREED, RELOAD))
    # 체인 1 — 욕망의 항아리. 응답 창이 상대에게 열린다.
    assert duel.apply(activations(duel, P0, POT_OF_GREED)[0]).accepted
    # 상대가 패스하면 발동한 쪽이 응답 자리가 된다 (RULE-CHAIN-001).
    assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted
    assert duel.priority.holder.is_seat(P0)

    # 스펠 스피드 1 은 후보가 아니다.
    assert activations(duel, P0, POT_OF_GREED) == []
    # 스펠 스피드 2 는 후보다 — 창 자체가 닫힌 것이 아니다.
    assert activations(duel, P0, RELOAD)

    forced = hand_action(duel, P0, POT_OF_GREED)
    before = board(duel)
    step = duel._apply_activation(forced)
    assert not step.accepted
    assert "스펠 스피드" in step.reason, step.reason
    assert board(duel) == before


# ======================================================================
# §13 — Phase 3-E-12 의 체인 링크 2 가 그대로 동작한다
# ======================================================================


@pytest.mark.real_card
def test_07_chain_link_two_still_works(repository):
    """
    **§12 · §13 — 실제 체인 링크 2 가 깨지지 않았다.**

    RULE-CHAIN-001 — "If your opponent does not respond, **you may activate a
    second effect** and create a Chain to your own card's activation."

    순서를 바꾼 것이 체인을 건드렸는지 재는 자리다. 링크 2 가 쌓이고, 두
    카드가 모두 필드에 놓여 있고(RULE-SPELLTRAP-002), 해결은 위에서부터
    (RULE-CHAIN-007) 내려온다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED, RELOAD, LUSTER_DRAGON))
    deck_before = len(duel.state.player(P0).zones[Zone.DECK])

    assert duel.apply(activations(duel, P0, POT_OF_GREED)[0]).accepted
    assert len(duel.chain) == 1
    assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted  # 상대 패스

    second = activations(duel, P0, RELOAD)
    assert second, "링크 2 후보가 없다"
    assert duel.apply(second[0]).accepted
    assert len(duel.chain) == 2
    # 두 장 모두 앞면으로 필드에 있다 — 놓는 걸음이 사라지지 않았다.
    assert len(duel.state.player(P0).zones[Zone.SZONE]) == 2
    assert len(duel.pending_spells) == 2

    assert settle_chain(duel).accepted
    assert duel.chain.is_empty
    assert len(duel.state.player(P0).zones[Zone.SZONE]) == 0
    assert duel.pending_spells == ()
    # 두 장 모두 묘지로 갔다.
    graves = sorted(
        c.card_id for c in duel.state.player(P0).zones[Zone.GRAVE]
    )
    assert graves == sorted((POT_OF_GREED, RELOAD))
    # 덱이 실제로 움직였다 — 해결이 일어났다는 뜻이다.
    assert len(duel.state.player(P0).zones[Zone.DECK]) != deck_before


# ======================================================================
# ② 조건 쪽 — 공식 스크립트의 제외 인자
# ======================================================================


@pytest.mark.real_card
def test_08_reload_does_not_count_itself(repository):
    """
    **§4 — ``e:GetHandler()`` 를 옮겼다.**

    c22589918.lua 의 ``s.target`` 이 제외 카드를 적는다. 그래서 "자신 패에
    1장 이상" 이 아니라 "**리로드 말고** 자신 패에 1장 이상" 이다.

    공식 재정이 이 조건의 다른 쪽도 확인해 준다 — ``data/rulings/ocg/
    5849.json`` 의 보충에 "デッキが０枚の状況でも発動できます" 가 있다. 즉
    막는 것은 **덱 장수가 아니라 패**다.
    """
    duel = duel_at(repository, mine=(RELOAD,))
    definition = duel._activator.definitions.definition_for(EffectRef(RELOAD, 0))
    assert definition is not None
    assert definition.activation == ZoneCountAtLeast(
        PlayerRef.CONTROLLER, Zone.HAND, 1, excluding_source=True
    )

    # 패에 자신 하나뿐 → 거짓. 한 장 더 있으면 참.
    alone = duel_at(repository, mine=(RELOAD,))
    assert activations(alone, P0, RELOAD) == []
    with_spare = duel_at(repository, mine=(RELOAD, LUSTER_DRAGON))
    assert activations(with_spare, P0, RELOAD)


@pytest.mark.real_card
def test_09_a_complete_condition_does_not_flip_when_the_card_moves(repository):
    """
    **STRUCTURAL-134 의 일반형 — 뒤집히는 조건은 덜 옮겨진 조건이다.**

    자기를 셀지 적어 둔 조건은 **배치 전과 후에 같은 답**을 낸다. 리로드의
    조건을 두 자리에서 각각 재서 그것을 보인다.

    왜 중요한가: 관문을 한 자리로 모으는 것(①)만으로는 "어느 판이 맞는가" 를
    답하지 못한다. 조건이 자기를 셀지 적으면 **그 질문 자체가 사라진다.**
    """
    duel = duel_at(repository, mine=(RELOAD, LUSTER_DRAGON))
    action = activations(duel, P0, RELOAD)[0]
    condition = duel._activator.definitions.definition_for(
        action.effect_ref
    ).activation
    context = ConditionContext(player=P0, source=action.source)

    before = condition.evaluate(duel.view(P0), context)
    duel._placement.place(duel.state, action.source, action.actor)
    after = condition.evaluate(duel.view(P0), context)
    assert before is after is ConditionResult.TRUE

    # 자신 하나뿐인 패에서도 양쪽이 같다 — 둘 다 거짓이다.
    alone = duel_at(repository, mine=(RELOAD,))
    only = hand_action(alone, P0, RELOAD)
    lone_context = ConditionContext(player=P0, source=only.source)
    before = condition.evaluate(alone.view(P0), lone_context)
    alone._placement.place(alone.state, only.source, only.actor)
    after = condition.evaluate(alone.view(P0), lone_context)
    assert before is after is ConditionResult.FALSE

    # 옮기지 않은 조건은 **뒤집혔다.** 그 사실을 같은 자리에서 확인한다.
    naive = ZoneCountAtLeast(PlayerRef.CONTROLLER, Zone.HAND, 1)
    assert naive.evaluate(alone.view(P0), lone_context) is ConditionResult.FALSE
    fresh = duel_at(repository, mine=(RELOAD,))
    assert (
        naive.evaluate(
            fresh.view(P0),
            ConditionContext(
                player=P0, source=hand_action(fresh, P0, RELOAD).source
            ),
        )
        is ConditionResult.TRUE
    )


def test_10_excluding_source_is_unknown_when_the_card_is_not_known(repository):
    """
    **§5-6 — 모르는 것을 참으로 읽지 않는다.**

    제외할 카드를 가리키지 않았거나 그 카드가 보이지 않으면, 세는 수를
    **모르는** 것이다. ``UNKNOWN`` 이고, ``UNKNOWN`` 은 허가가 아니다.
    """
    state = GameState.create(
        repository, decks=([LUSTER_DRAGON] * 5, [LUSTER_DRAGON] * 5), seed=1
    )
    for _ in range(3):
        state.create_instance(LUSTER_DRAGON, owner=P0, zone=Zone.HAND)
    hidden = state.create_instance(LUSTER_DRAGON, owner=P1, zone=Zone.HAND)
    view = GameStateView.from_state(state, viewer=P0)
    condition = ZoneCountAtLeast(
        PlayerRef.CONTROLLER, Zone.HAND, 1, excluding_source=True
    )

    # ① source 가 없다.
    assert (
        condition.evaluate(view, ConditionContext(player=P0))
        is ConditionResult.UNKNOWN
    )
    # ② source 가 보이지 않는다 (상대 패).
    assert (
        condition.evaluate(
            view, ConditionContext(player=P0, source=hidden.instance_id)
        )
        is ConditionResult.UNKNOWN
    )
    # ③ 보이는 카드면 확정된다.
    mine = next(iter(state.player(P0).hand))
    assert (
        condition.evaluate(
            view, ConditionContext(player=P0, source=mine.instance_id)
        )
        is ConditionResult.TRUE
    )


def test_11_the_exception_is_off_unless_the_card_says_so():
    """
    **§5-9 — 켜지 않은 카드의 조건은 **한 글자도** 달라지지 않았다.**

    ``excluding_source`` 는 기본값이 ``False`` 이고, 그때의 정규 표현과
    직렬화는 예전과 같다. 같은 ``ZoneCountAtLeast`` 를 쓰는 다른 7개 정의의
    뜻을 이 Phase 가 바꾸지 않았다는 뜻이다.
    """
    plain = ZoneCountAtLeast(PlayerRef.CONTROLLER, Zone.DECK, 2)
    assert plain.excluding_source is False
    assert plain.canonical_state() == (
        "zone_count_at_least",
        "controller",
        "DECK",
        2,
    )
    assert plain.to_dict() == {
        "kind": "zone_count_at_least",
        "who": "controller",
        "zone": "DECK",
        "count": 2,
    }
    assert "말고" not in plain.describe_ko()

    marked = ZoneCountAtLeast(
        PlayerRef.CONTROLLER, Zone.HAND, 1, excluding_source=True
    )
    assert marked.canonical_state() != ZoneCountAtLeast(
        PlayerRef.CONTROLLER, Zone.HAND, 1
    ).canonical_state()
    assert marked.to_dict()["excluding_source"] is True
    assert "이 카드 말고" in marked.describe_ko()


# ======================================================================
# §9 — 평소의 발동이 그대로다
# ======================================================================


@pytest.mark.real_card
def test_12_the_ordinary_activation_is_unchanged(repository):
    """
    **§9 — 욕망의 항아리 한 장의 처음부터 끝까지.**

    순서를 바꾼 것이 평소의 발동을 건드리지 않았는지 잰다. 걸음마다 판이
    어디 있어야 하는지를 적는다 (RULE-SPELLTRAP-002).
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    deck_before = len(duel.state.player(P0).zones[Zone.DECK])

    step = duel.apply(activations(duel, P0, POT_OF_GREED)[0])
    assert step.accepted
    # 발동 뒤 — 앞면으로 마법 & 함정 존에 있고, 패를 떠났다.
    assert len(duel.state.player(P0).zones[Zone.HAND]) == 0
    szone = [c for c in duel.state.player(P0).zones[Zone.SZONE] if c is not None]
    assert [c.card_id for c in szone] == [POT_OF_GREED]
    assert szone[0].position is Position.FACEUP
    assert len(duel.chain) == 1
    assert duel.priority.window is ResponseWindow.RESPONSE

    assert settle_chain(duel).accepted
    # 해결 뒤 — 묘지로, 그리고 두 장을 뽑았다.
    assert [
        c.card_id for c in duel.state.player(P0).zones[Zone.GRAVE]
    ] == [POT_OF_GREED]
    assert len(duel.state.player(P0).zones[Zone.DECK]) == deck_before - 2
    assert len(duel.state.player(P0).zones[Zone.HAND]) == 2
    assert duel.pending_spells == ()


@pytest.mark.real_card
def test_13_the_gate_returns_the_first_refusal_as_it_stands(repository):
    """
    **§5-1 · §18-A — 관문은 **첫 거절을 그대로** 돌려준다.**

    왜 이 시험이 필요했는가: ``ActionValidator`` 의 판정이 ``VALID`` 가 아닐
    때 돌아가는 분기를 지워 보는 고의 위반을 넣었더니 **아무 테스트도 잡지
    못했다.** 안쪽의 ``EffectActivator._verdict`` 가 같은 허가를 다시 보고
    독립적으로 막기 때문이다 (``permits_execution`` 이 아니면 ``UNAUTHORIZED``).
    결과만 보면 거절이므로 구별이 되지 않았다.

    구별되는 것은 **이유**다. 관문이 제대로 서 있으면 거절의 코드와 문장이
    **검증기의 것**이고, 분기가 지워지면 ``can_activate`` 가 다시 만든
    "지금 이 발동이 허가되지 않았습니다: …" 가 나온다. 같은 거절이라도
    **누가 막았는지**를 잃으면 ``withheld`` 설명과 디버깅이 거짓말을 한다.

    ``INVALID`` 와 ``UNKNOWN`` 을 모두 잰다 — 둘은 다른 사실이다.
    """
    from engine.validation import ValidationCode

    # ① INVALID — 메인 페이즈가 아니다 (RULE-SPELLTRAP-001).
    duel = duel_at(repository, mine=(POT_OF_GREED,), phase=Phase.END)
    action = hand_action(duel, P0, POT_OF_GREED)
    gate = duel._activation_gate(
        action, validator=ActionValidator(duel.view(P0)), selections=()
    )
    assert gate.validity is ActionValidity.INVALID
    assert gate.code is ValidationCode.WRONG_PHASE
    assert "메인 페이즈가 아닙니다" in gate.reason
    assert "허가되지 않았습니다" not in gate.reason

    # ② UNKNOWN — 함정의 발동 타이밍을 아직 판정하지 못한다.
    duel = duel_at(repository, mine=(GIFT_OF_GREED, LUSTER_DRAGON))
    action = hand_action(duel, P0, GIFT_OF_GREED)
    gate = duel._activation_gate(
        action, validator=ActionValidator(duel.view(P0)), selections=()
    )
    assert gate.validity is ActionValidity.UNKNOWN
    assert "허가되지 않았습니다" not in gate.reason
