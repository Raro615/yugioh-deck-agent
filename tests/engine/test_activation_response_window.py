"""
Phase 3-E-11 — 발동 직후의 RESPONSE 창 (STRUCTURAL-34 의 절반).

이 Phase 가 이은 것은 **한 줄**이다.

    ACTIVATE_EFFECT → ChainLink → **상대의 응답 기회** → (패스) → 해결

공식 근거 ``RULE-CHAIN-001``

    "If a card's effect is activated, the opponent is **always** given a chance
     to respond with a card effect of their own, creating a Chain. … Both
     players continue to add effects to the Chain until **they both wish to
     add nothing else**, then you resolve the outcome in reverse order."

그래서 패스가 **두 번** 필요하다 — 상대가 한 번, 발동한 쪽이 한 번.

이지 않은 것 (이 Phase 가 손대지 않은 자리)
-------------------------------------------
- 페이즈 전환의 우선권 (``RULE-CHAIN-009`` · ``ResponseWindow.PHASE_CHANGE``)
- 체인 해결 뒤의 우선권 (``AFTER_CHAIN_RULE``)
- Trigger 자동 발동 · Damage Step · Depth-2

**열렸다 ≠ 무엇이든 발동할 수 있다.** 창은 열리지만 각 후보의 적법성은
기존 검증기와 타이밍 관문이 정한다. 지금 응답 후보는 **하나도 생기지 않는다** —
``Duel._activation_actions`` 가 체인이 빈 자리만 보고, 발동 범위가 "자기 메인
페이즈의 패에 있는 통상 마법" 으로 좁혀져 있기 때문이다 (Phase 3-E-3). 그
사실을 ``test_e`` · ``test_f`` 가 적는다. UNKNOWN 을 VALID 로 승격하지 않았다.
"""

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel
from engine.priority import PriorityHolder, PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db, settle_chain

pytestmark = requires_official_db

P0, P1 = 0, 1

LUSTER_DRAGON = 11091375  # 통상 몬스터
POT_OF_GREED = 55144522  # 통상 마법 (스펠 스피드 1) — 덱에서 2장 뽑는다
TRAP_HOLE = 4206964  # 함정 (스펠 스피드 2) — 발동 계층에 없다


def duel_at(repository, *, mine=(), theirs=(), turn_player=P0, phase=Phase.MAIN1):
    """실제 엔진으로 만든 판 하나. ``create_instance`` 는 엔진의 정상 입구다."""
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


def the_activation(duel, seat=P0):
    return next(
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    )


def kinds(duel, seat):
    return sorted({a.kind.name for a in duel.legal_actions(seat).allowed})


# ======================================================================
# §19-A · §19-B — 창이 열리고, 열린 자리가 상대다
# ======================================================================


@pytest.mark.real_card
def test_a_activation_opens_a_response_window(repository):
    """
    **§19-A — 발동이 ``ResponseWindow.RESPONSE`` 를 연다.**

    예전에는 ``window`` 가 평생 ``NONE`` 이었다 (Phase 3-E-10 Audit).
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    assert duel.priority.window is ResponseWindow.NONE
    assert duel.priority.holder is PriorityHolder.NOBODY

    step = duel.apply(the_activation(duel))
    assert step.accepted, step.reason

    assert duel.priority.window is ResponseWindow.RESPONSE
    assert duel.priority.is_open
    assert duel.priority.consecutive_passes == 0
    # 연 이유가 적혀 있다 — 지어낸 규칙이 아니다.
    assert "RULE-CHAIN-001" in duel.priority.reason


@pytest.mark.real_card
def test_b_the_response_seat_is_the_opponent_of_the_activator(repository):
    """
    **§19-B — P0 가 발동했으면 P1 에게 기회가 간다.**

    ``turn_player`` 가 아니라 **발동한 쪽의 상대**다. 셋을 혼동하지 않는다 —
    턴 플레이어 ≠ 우선권 홀더 ≠ 응답 자리.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    assert duel.apply(the_activation(duel)).accepted

    assert duel.priority.holder.is_seat(P1)
    assert duel.to_act == P1
    assert duel.turn_player == P0, "턴 플레이어는 그대로다"
    assert duel.priority.holder_is_turn_player is False

    # 기회를 받은 자리에만 후보가 있다.
    assert kinds(duel, P1) == ["PASS"]
    assert kinds(duel, P0) == []


# ======================================================================
# §19-C · §19-D — 응답하지 않으면 기존 해결로 간다
# ======================================================================


@pytest.mark.real_card
def test_c_two_passes_resolve_the_chain(repository):
    """
    **§19-C — 둘 다 그만하겠다고 하면 해결된다** (``RULE-CHAIN-001``).

    한 번의 패스로는 풀지 않는다. 상대가 패스하면 우선권이 발동한 쪽으로
    가고, 거기서도 패스해야 "둘 다 그만하겠다" 가 된다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    assert duel.apply(the_activation(duel)).accepted
    assert len(duel.chain) == 1

    # ① 상대가 패스 — 아직 풀지 않는다.
    first = duel.apply(duel.legal_actions(P1).allowed[0])
    assert first.accepted
    assert len(duel.chain) == 1, "한 번의 패스로 풀렸다"
    assert duel.priority.holder.is_seat(P0)
    assert duel.priority.consecutive_passes == 1
    assert duel.priority.both_passed is False

    # ② 발동한 쪽도 패스 — 여기서 푼다.
    second = duel.apply(duel.legal_actions(P0).allowed[0])
    assert second.accepted
    assert "해결했습니다" in second.reason
    assert len(duel.chain) == 0
    assert duel.priority.window is ResponseWindow.NONE
    assert duel.pending_spells == ()


@pytest.mark.real_card
def test_d_the_state_mutation_is_exactly_what_it_was(repository):
    """
    **§19-D — 욕망의 항아리의 결과가 한 개도 바뀌지 않았다.**

    덱 −2 · 패 −1+2 · 발동한 카드는 묘지 (``RULE-SPELLTRAP-002``).
    바뀐 것은 **걸음 수**이고 결과가 아니다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    player = duel.state.player(P0)
    deck_before, hand_before = len(player.deck), len(player.zones[Zone.HAND])
    assert (deck_before, hand_before) == (20, 1)

    activation = the_activation(duel)
    pot = activation.source
    assert duel.apply(activation).accepted

    # 해결 전 — 카드는 필드에 있고 아직 뽑지 않았다 (RULE-SPELLTRAP-002).
    assert len(player.deck) == deck_before
    assert [c.instance_id for c in player.zones[Zone.SZONE]] == [pot]
    assert len(duel.pending_spells) == 1

    assert settle_chain(duel).accepted

    assert len(player.deck) == deck_before - 2 == 18
    assert len(player.zones[Zone.HAND]) == hand_before - 1 + 2 == 2
    assert [c.instance_id for c in player.zones[Zone.GRAVE]] == [pot]
    assert len(player.zones[Zone.SZONE]) == 0


# ======================================================================
# §19-E · §19-F — 창이 열린 것과 발동할 수 있는 것은 다르다
# ======================================================================


@pytest.mark.real_card
def test_e_a_spell_speed_1_card_is_not_a_response_candidate(repository):
    """
    **§19-E — 스펠 스피드 1 은 응답 후보가 되지 않는다** (``RULE-CHAIN-004``).

        "Spells (Normal, Equip, Continuous, Field, Ritual) … **cannot be
         activated in response to any other effects.**"

    상대 패에 욕망의 항아리(통상 마법 · 스펠 스피드 1)가 있어도, 열린 응답
    기회의 후보는 ``PASS`` 뿐이다. 그것이 규칙과 맞다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,), theirs=(POT_OF_GREED,))
    assert duel.apply(the_activation(duel)).accepted

    assert duel.priority.holder.is_seat(P1)
    assert kinds(duel, P1) == ["PASS"]
    assert PlayerActionKind.ACTIVATE_EFFECT not in {
        a.kind for a in duel.legal_actions(P1).allowed
    }


@pytest.mark.real_card
def test_f_no_response_candidate_is_generated_yet_and_we_say_why(repository):
    """
    **§19-F · §6 — 지금은 응답 후보가 하나도 생기지 않는다.**

    창은 열린다. 그러나 ``Duel._activation_actions`` 는 **체인이 빈 자리만**
    보고, 발동 범위도 "자기 메인 페이즈의 패에 있는 통상 마법" 으로 좁혀져
    있다 (Phase 3-E-3). 그래서 스펠 스피드 2 이상 카드(함정 · 속공)가
    ``EFFECT_LIBRARY`` 에 등록되어 있어도 후보가 되지 않는다.

    **억지로 승격하지 않았다.** 응답 후보를 만들려면 ``ActivationTimingChecker``
    를 행동 공간에 이어야 하고, 그것은 이 Phase 의 범위 밖이다.

    이 시험은 **그 한계를 고정한다.** 응답 후보가 생기기 시작하면 깨지고,
    그때가 다음 걸음이다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,), theirs=(TRAP_HOLE,))
    assert duel.apply(the_activation(duel)).accepted

    legal = duel.legal_actions(P1)
    assert [a.kind for a in legal.allowed] == [PlayerActionKind.PASS]

    # 왜 안 되는지가 적혀 있다 — 조용히 빠지지 않는다.
    missing = {w.missing for w in legal.withheld}
    assert any(m and "activation" in m for m in missing), missing


@pytest.mark.real_card
def test_g_chain_link_2_is_not_reachable_yet(repository):
    """
    **§15 — 체인 링크 2 는 아직 도달 불가다.** 이유를 분리해 적는다.

    기존 ``Chain`` 은 링크 2 를 **들 수 있다** (``Chain.push`` 와
    ``ChainResolver.resolve_all`` 이 이미 여러 링크를 다룬다). 막혀 있는 곳은
    체인이 아니라 **행동 공간**이다 — 응답 후보가 생기지 않는다 (``test_f``).

    그래서 새 Chain Engine 을 만들지 않았다. STRUCTURAL-124 와 다른 문제다:
    124 는 "응답할 자리가 없다" 였고 그 자리는 이제 **있다.** 남은 것은
    "그 자리에서 고를 것이 없다" 다.
    """
    from engine.chain import Chain, ChainResolver

    assert hasattr(Chain, "push")
    assert hasattr(ChainResolver, "resolve_all")

    duel = duel_at(repository, mine=(POT_OF_GREED, POT_OF_GREED))
    assert duel.apply(the_activation(duel)).accepted
    assert len(duel.chain) == 1

    # 두 번째 욕망의 항아리가 패에 있지만 응답으로 쓸 수 없다 — 두 가지
    # 이유가 겹친다: 체인이 비어 있지 않고 (행동 공간), 스펠 스피드 1 이다
    # (규칙). 둘 다 맞다.
    assert kinds(duel, P0) == []
    assert kinds(duel, P1) == ["PASS"]


# ======================================================================
# §19-G · §19-H — 창이 없으면 아무것도 변하지 않는다
# ======================================================================


@pytest.mark.real_card
def test_h_the_normal_action_space_is_untouched_without_a_window(repository):
    """
    **§19-G · §12 — 응답 창이 없을 때 후보가 한 건도 변하지 않는다.**

    ``legal_actions`` 에 더한 조건은 ``and not self.priority.is_open`` 하나이고,
    창이 닫혀 있으면 그 조건은 **늘 참**이므로 기존 경로가 그대로다.
    """
    duel = duel_at(repository, mine=(LUSTER_DRAGON, POT_OF_GREED))
    assert not duel.priority.is_open
    assert kinds(duel, P0) == [
        "ACTIVATE_EFFECT",
        "END_PHASE",
        "NORMAL_SUMMON",
        "SET_MONSTER",
        "SET_SPELL_TRAP",
    ]
    # 소환은 응답 기회를 열지 않는다 (RULE-CHAIN-011).
    summon = next(
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
    )
    assert duel.apply(summon).accepted
    assert duel.priority.window is ResponseWindow.NONE
    assert kinds(duel, P1) == []


@pytest.mark.real_card
def test_i_the_chain_link_is_preserved_while_the_window_is_open(repository):
    """**§19-H — 쌓인 링크가 사라지지 않는다.** 응답 기회 동안 그대로 있다."""
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    activation = the_activation(duel)
    assert duel.apply(activation).accepted

    (link,) = duel.chain.links
    assert link.actor == P0
    assert link.effect_ref == activation.effect_ref
    assert link.source == activation.source
    assert link.chain_number == 1

    # 패스 한 번으로도 링크는 그대로다.
    assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted
    assert duel.chain.links == (link,)


# ======================================================================
# §19-I · §19-J · §19-K — 사본 · RNG · 가려진 정보
# ======================================================================


@pytest.mark.real_card
def test_j_the_simulation_leaves_the_real_duel_alone(repository):
    """
    **§19-I · §19-J — 사본이 원본을 건드리지 않는다.**

    사본은 응답 창까지 열고 강제된 패스까지 밟는다. 그래도 원본의 우선권 ·
    체인 · 대기 목록 · 난수 뽑기 수가 **하나도** 변하지 않는다.
    """
    from agent.simulation import Simulator

    duel = duel_at(repository, mine=(POT_OF_GREED,))
    before = (
        duel.state.state_hash(),
        duel.priority.canonical_state(),
        duel.chain.canonical_state(),
        duel.pending_spells,
        duel.state.randomness.draws,
    )

    simulator = Simulator(duel)
    result = simulator.simulate(the_activation(duel), viewer=P0)
    assert result.future is not None

    after = (
        duel.state.state_hash(),
        duel.priority.canonical_state(),
        duel.chain.canonical_state(),
        duel.pending_spells,
        duel.state.randomness.draws,
    )
    assert before == after

    # 사본의 미래는 **해결까지 끝난 자리**다 — 강제된 패스는 고르는 일이
    # 아니므로 시뮬레이터가 대신 밟는다.
    assert result.future.me.deck.size == 18


@pytest.mark.real_card
def test_k_the_opponent_learns_nothing_hidden_from_the_window(repository):
    """
    **§19-K · §16 — 창이 열려도 가려진 것은 가려져 있다.**

    응답 기회를 주려고 상대의 패를 읽지 않는다. 그리고 상대도 발동한 쪽이
    무엇을 뽑았는지 알지 못한다.
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,), theirs=(TRAP_HOLE, LUSTER_DRAGON))
    assert duel.apply(the_activation(duel)).accepted

    # 창이 열린 동안의 관측 — 상대 패의 정체가 보이지 않는다.
    mine = duel.view(P0)
    assert mine.opponent.hand.concealed
    assert mine.opponent.hand.cards == ()
    assert mine.opponent.hand.size == 2  # 장수는 공개

    assert settle_chain(duel).accepted

    theirs = duel.view(P1)
    assert theirs.opponent.hand.concealed
    assert theirs.opponent.hand.cards == ()
    assert theirs.opponent.hand.size == 2
    # 발동한 카드는 묘지에서 양쪽에 보인다 (앞면으로 놓았으므로).
    assert [c.card_id for c in theirs.opponent.grave.occupied()] == [POT_OF_GREED]


@pytest.mark.real_card
def test_l_a_refused_activation_opens_no_window(repository):
    """
    발동이 성립하지 않으면 **창도 열리지 않는다.**

    기회는 "발동했다" 의 결과다. 발동이 거절되면 판도 흐름도 그대로여야
    하고, 놓았던 카드는 패로 돌아간다 (``NormalSpellPlacement.restore``).
    """
    duel = duel_at(repository, mine=(POT_OF_GREED,))

    # 허가되지 않은 발동 — 상대 자리에서 내 카드를 발동하려 한다.
    activation = the_activation(duel)
    stolen = PlayerAction.activate_effect(
        actor=P1, source=activation.source, effect_ref=activation.effect_ref
    )
    step = duel.apply(stolen)
    assert not step.accepted
    assert duel.priority.window is ResponseWindow.NONE
    assert duel.chain.is_empty
    assert duel.pending_spells == ()
    assert len(duel.state.player(P0).zones[Zone.HAND]) == 1


@pytest.mark.real_card
def test_m_the_simulator_only_settles_what_is_not_a_choice(repository):
    """
    **시뮬레이터는 '고를 것이 없는' 자리만 대신 밟는다** (``§17``).

    ``Simulator._settle_forced_passes`` 는 후보가 ``PASS`` **하나뿐**일 때만
    그 걸음을 밟는다. 고를 것이 하나라도 있으면 멈춘다 — 그 자리가 진짜 결정
    지점이고, 거기까지가 깊이 1 이다. 상대의 **선택을 예측하지 않는다.**

    **이 주장은 지금 실행으로 깨뜨릴 수 없다.** 응답 창이 열린 자리의 후보가
    언제나 ``PASS`` 하나뿐이라서(``test_f``), 조건의 두 번째 절이 참이 되는
    상태가 아직 없다. 고의 위반(조건에서 그 절을 지우기)을 주입해도 아무
    테스트가 잡지 못했다 — 그래서 **지금 잡을 수 있는 방법으로** 잡는다:
    조건이 약해지면 이 시험이 깨진다.

    응답 후보가 생기기 시작하면 이 자리를 실행으로 다시 재야 한다.
    """
    import inspect

    from agent.simulation import Simulator

    source = inspect.getsource(Simulator._settle_forced_passes)
    # 두 절이 **함께** 있어야 한다: 패스가 있고, 패스가 **전부**여야 한다.
    assert "if not passes or len(passes) != len(legal.allowed):" in source, source
    assert "break" in source

    # 지금 도달 가능한 자리에서는 후보가 하나뿐이고, 그래서 밟는다.
    duel = duel_at(repository, mine=(POT_OF_GREED,))
    assert duel.apply(the_activation(duel)).accepted
    assert len(duel.legal_actions(P1).allowed) == 1

    duel = duel_at(repository, mine=(POT_OF_GREED,))
    result = Simulator(duel).simulate(the_activation(duel), viewer=P0)
    assert result.future is not None
    assert result.future.me.deck.size == 18, "강제된 패스를 밟지 않았다"
