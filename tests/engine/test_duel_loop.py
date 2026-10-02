"""
Phase 2-AO — 듀얼 한 판을 처음부터 끝까지 (Engine V1).

    Duel.start(...)          섞고 5장씩 뽑는다
      ↓
    duel.advance()           **고르지 않아도 일어나는 일** (드로우)
    duel.legal_actions()     허가가 난 행위들
    duel.apply(action)       적용
      ↓
    duel.result              승패

이 파일이 증명하는 것
---------------------
**``PlayerAction`` 만으로 듀얼이 끝까지 간다.** 판을 직접 건드리지 않고,
허가가 난 행위만 고르고, 덱이 떨어지면 끝난다.

무엇을 아직 못 하는지도 함께 증명한다 — 마법 · 함정을 발동할 수 없고
(``activation-timing`` 계층이 없다), 우선권 창이 열리지 않는다. 그 둘은
**감춰지지 않는다**: ``legal_actions().withheld`` 가 이유를 들고 있다.
"""

import ast
import collections
import json
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.duel import (
    LOSS_BY_DECK_OUT,
    LOSS_BY_LIFE,
    OPENING_HAND,
    Duel,
    TurnStep,
)
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
FEATHERMAN = 21844576
POT_OF_GREED = 55144522
MINE, THEIRS = 0, 1


def small_duel(repository, *, seed: int = 5, size: int = 12) -> Duel:
    """양쪽 12장. 짧게 끝나도록 일부러 작은 덱이다."""
    deck = [FEATHERMAN] * (size - 2) + [POT_OF_GREED] * 2
    return Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)


def play_out(duel: Duel, *, limit: int = 600):
    """
    **아주 단순한 정책**으로 끝까지 둔다 — 소환할 수 있으면 하고 아니면
    페이즈를 넘긴다. AI 가 아니다; 고르는 자리가 있다는 것만 보인다.
    """
    taken: collections.Counter = collections.Counter()
    for _ in range(limit):
        if duel.is_over:
            return taken
        if duel.advance() is not None:
            continue
        legal = duel.legal_actions()
        if not legal.allowed:
            raise AssertionError(f"고를 것이 없습니다: {duel.describe_ko()}")
        chosen = next(
            (a for a in legal.allowed if a.kind is PlayerActionKind.NORMAL_SUMMON),
            legal.allowed[-1],
        )
        taken[chosen.kind] += 1
        step = duel.apply(chosen)
        assert step.accepted, step.reason
    raise AssertionError("듀얼이 끝나지 않았습니다.")


# ======================================================================
# A. 시작 — 룰북이 정한 대로
# ======================================================================


def rulebook_text() -> str:
    data = json.loads(
        (ROOT / "data/rules/documents/sd-rulebook-en-v10.json").read_text()
    )

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)
        elif isinstance(node, str):
            yield node

    return " ".join(" ".join(t.split()) for t in walk(data)).replace(
        "ﬁ", "fi"
    ).replace("ﬂ", "fl")


def test_a_the_rules_this_loop_follows_are_in_the_rulebook():
    """**인용을 지어내지 않았다.** 넷 다 저장소의 공식 룰북에 있다."""
    text = rulebook_text()

    assert "draw 5 cards from the top of your Deck; this is your starting hand" in text
    assert (
        "The player who goes first cannot draw during the Draw Phase of "
        "their first turn." in text
    )
    assert (
        "A player with no cards left in their Deck and unable to draw loses "
        "the Duel." in text
    )
    assert "you reduce your opponent’s LP to 0" in text


@pytest.mark.real_card
def test_a_both_players_open_with_five_cards(repository):
    duel = small_duel(repository)

    assert OPENING_HAND == 5
    for seat in (MINE, THEIRS):
        assert len(duel.state.player(seat).hand) == 5
        assert len(duel.state.player(seat).deck) == 7
    assert duel.state.turn.phase is Phase.DRAW
    assert duel.turn_player == duel.first_player


@pytest.mark.real_card
def test_a_the_first_player_does_not_draw_on_turn_one(repository):
    """
    룰북이 명시한 예외다. 첫 드로우 페이즈는 **뽑을 것이 없는** 상태로
    시작하고, 두 번째 플레이어의 첫 턴에는 뽑는다.
    """
    duel = small_duel(repository)

    assert duel.step is TurnStep.OPEN
    assert duel.advance() is None  # 뽑을 것이 없다
    assert len(duel.state.player(MINE).hand) == 5

    # 턴이 넘어가면 그때부터는 뽑는다.
    while duel.turn_player == duel.first_player:
        duel.advance()
        legal = duel.legal_actions()
        duel.apply(legal.allowed[-1])

    assert duel.step is TurnStep.DRAW_PENDING
    before = len(duel.state.player(THEIRS).hand)
    assert duel.advance() is not None
    assert len(duel.state.player(THEIRS).hand) == before + 1


# ======================================================================
# B. 끝까지 간다
# ======================================================================


@pytest.mark.real_card
def test_b_a_duel_runs_from_start_to_finish(repository):
    """
    **이 단계의 목표다.** 판을 직접 건드리지 않고 ``PlayerAction`` 만으로
    듀얼이 끝난다.
    """
    duel = small_duel(repository)

    taken = play_out(duel)

    assert duel.is_over
    assert duel.result is not None
    assert duel.result.winner in (0, 1)
    assert LOSS_BY_DECK_OUT in duel.result.reason
    # 실제로 고르는 자리가 있었다 — 넘기기만 한 것이 아니다.
    assert taken[PlayerActionKind.NORMAL_SUMMON] > 0
    assert taken[PlayerActionKind.END_PHASE] > 0


@pytest.mark.real_card
def test_b_the_loser_is_the_one_who_ran_out(repository):
    duel = small_duel(repository)

    play_out(duel)

    loser = 1 - duel.result.winner
    assert len(duel.state.player(loser).deck) == 0
    assert f"P{loser}" in duel.result.reason


@pytest.mark.real_card
def test_b_every_phase_is_visited(repository):
    """턴이 한 바퀴 도는 것을 확인한다 — 드로우에서 엔드까지."""
    duel = small_duel(repository)
    seen = set()

    for _ in range(600):
        if duel.is_over:
            break
        if duel.advance() is not None:
            continue
        seen.add(duel.state.turn.phase)
        legal = duel.legal_actions()
        duel.apply(legal.allowed[-1])

    assert seen == {
        Phase.DRAW,
        Phase.STANDBY,
        Phase.MAIN1,
        Phase.BATTLE,
        Phase.MAIN2,
        Phase.END,
    }
    assert duel.state.turn.turn_number > 5


@pytest.mark.real_card
def test_b_the_same_seed_gives_the_same_duel(repository):
    """같은 씨앗 · 같은 정책이면 **같은 판**이다 (2-Z)."""
    results, hashes = [], []
    for _ in range(3):
        duel = small_duel(repository, seed=11)
        play_out(duel)
        results.append((duel.result.winner, duel.result.reason))
        hashes.append(duel.state.state_hash())

    assert len(set(results)) == 1
    assert len(set(hashes)) == 1


@pytest.mark.real_card
def test_b_a_different_seed_can_give_a_different_duel(repository):
    """씨앗이 다르면 배치가 다르다 — 결정론이 '언제나 같다' 는 뜻이 아니다."""
    hashes = set()
    for seed in (3, 11, 29):
        duel = small_duel(repository, seed=seed)
        play_out(duel)
        hashes.add(duel.state.state_hash())

    assert len(hashes) > 1


# ======================================================================
# C. 허가가 나지 않은 것은 내놓지 않는다
# ======================================================================


@pytest.mark.real_card
def test_c_an_action_outside_the_list_is_refused(repository):
    """
    ``legal_actions`` 가 목록이고, :meth:`Duel.apply` 는 **그 자리에서 다시
    묻는다.** 목록을 믿고 적용하면 그 사이의 변화를 놓친다.
    """
    duel = small_duel(repository)
    stranger = PlayerAction.normal_summon(
        actor=THEIRS, source=duel.state.player(THEIRS).hand[0].instance_id
    )

    step = duel.apply(stranger)

    assert not step.accepted
    assert "허가된 행위가 아닙니다" in step.reason


@pytest.mark.real_card
def test_c_spells_are_withheld_with_the_reason(repository):
    """
    **마법을 발동할 수 없다.** 감추지 않는다 — 이유가 목록에 함께 온다.

    ``ActionValidator`` 가 ``ACTIVATE_CARD`` 에 아직 ``UNKNOWN`` 을
    돌려주고 (``_COMPLETE_RULES`` 에 일반 소환뿐이다), ``UNKNOWN`` 은
    허가가 아니므로 후보가 되지 않는다.
    """
    duel = small_duel(repository)
    # 패에 욕망의 항아리가 오도록 몇 턴 돌린다.
    for _ in range(40):
        if any(c.card_id == POT_OF_GREED for c in duel.state.player(MINE).hand):
            break
        duel.advance()
        legal = duel.legal_actions()
        duel.apply(legal.allowed[-1])

    legal = duel.legal_actions(MINE)
    assert PlayerActionKind.ACTIVATE_CARD not in legal.kinds()
    withheld = [
        w for w in legal.withheld if w.kind is PlayerActionKind.ACTIVATE_CARD
    ]
    assert withheld
    assert withheld[0].missing == "activation-timing (Phase 2-C/2-F)"


@pytest.mark.real_card
def test_c_drawing_is_a_rule_not_a_choice(repository):
    """
    드로우는 **고르는 일이 아니다.** 뽑지 않겠다고 고를 수 없으므로 행위
    목록에 없고, :meth:`Duel.advance` 가 수행한다.
    """
    duel = small_duel(repository)
    while duel.step is not TurnStep.DRAW_PENDING:
        duel.advance()
        duel.apply(duel.legal_actions().allowed[-1])

    assert duel.legal_actions().allowed == ()
    assert duel.advance() is not None
    assert duel.step is TurnStep.OPEN


@pytest.mark.real_card
def test_c_nothing_is_accepted_after_the_duel_ends(repository):
    duel = small_duel(repository)
    play_out(duel)
    winner = duel.result.winner

    step = duel.apply(PlayerAction.passing(actor=winner))

    assert not step.accepted
    assert step.code is ValidationCode.DUEL_ALREADY_OVER
    assert duel.legal_actions(winner).allowed == ()
    assert duel.advance() is None


# ======================================================================
# D. 패배 조건 둘
# ======================================================================


@pytest.mark.real_card
def test_d_zero_life_ends_the_duel(repository):
    """
    룰북의 다른 패배 조건이다. **등재된 카드로는 재현할 수 없다** — 지금
    실행되는 13장 중 상대 라이프를 줄이는 카드가 없다. 그래서 규칙 자체를
    본다: 라이프가 0 이면 다음 걸음에서 끝난다.
    """
    duel = small_duel(repository)
    duel.state.player(THEIRS).change_life(
        -duel.state.player(THEIRS).life_points
    )

    duel.advance()
    step = duel.apply(duel.legal_actions().allowed[-1])

    assert duel.is_over
    assert duel.result.winner == MINE
    assert LOSS_BY_LIFE in duel.result.reason
    assert step.result is duel.result


@pytest.mark.real_card
def test_d_deck_out_is_checked_when_the_draw_is_due(repository):
    """
    **덱이 0장인 것만으로는 지지 않는다.** 뽑아야 할 때 뽑을 수 없어야
    진다 — 룰북이 "unable to draw" 라고 적는다.
    """
    duel = small_duel(repository)
    duel.state.player(THEIRS).deck.clear()

    assert not duel.is_over  # 아직은 아니다
    while not duel.is_over:
        if duel.advance() is not None:
            continue
        duel.apply(duel.legal_actions().allowed[-1])

    assert duel.result.winner == MINE
    assert LOSS_BY_DECK_OUT in duel.result.reason


# ======================================================================
# E. 경계 — 듀얼이 규칙을 새로 만들지 않는다
# ======================================================================


def test_e_the_duel_makes_no_rules_of_its_own():
    """
    :mod:`engine.duel` 은 **부르기만 한다.** 새 조건 · 새 판정 · 새 조작을
    만들지 않는다.

    판을 바꾸는 것은 셋뿐이다 — 시작 드로우, 페이즈 드로우, 승패 기록.
    앞의 둘은 룰북이 시키는 일이고 (5장 · 매 턴 1장), 마지막은 결과를
    적는 일이다. 카드를 옮기거나 라이프를 건드리는 코드는 없다.
    """
    source = (ROOT / "engine/duel.py").read_text()
    tree = ast.parse(source)

    changed = sorted(
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in {"draw", "move", "set_result", "change_life"}
    )
    assert changed == ["draw", "draw", "set_result", "set_result"]

    # 조건 · 판정 · 조작 계층을 import 하지 않는다.
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(
        name.startswith("engine.effect") or name.startswith("engine.condition")
        for name in imported
    )


@pytest.mark.real_card
def test_e_each_seat_only_sees_its_own_hand(repository):
    """관측 경계는 그대로다 — 듀얼 루프가 우회하지 않는다."""
    duel = small_duel(repository)

    mine = duel.view(MINE)
    assert all(c.card_id is not None for c in mine.player(MINE).hand.cards)
    assert mine.player(THEIRS).zone(Zone.HAND).concealed
    assert mine.player(THEIRS).zone(Zone.HAND).cards == ()
    assert mine.player(THEIRS).zone(Zone.HAND).size == 5


@pytest.mark.real_card
def test_e_priority_opens_only_where_a_rule_says_so(repository):
    """
    **발동이 없는 듀얼에서는 우선권 창이 한 번도 열리지 않는다.**

    Phase 3-E-11 전에는 "한 번도" 가 **모든** 듀얼에 참이었고, 그것이
    STRUCTURAL-34 였다. 지금은 공식 근거가 있는 자리 하나에서 열린다 —
    효과 발동 직후의 응답 기회(``RULE-CHAIN-001``). 이 듀얼의 덱에는 발동할
    효과가 없으므로 그 자리에 닿지 않고, 그래서 주장이 그대로 참이다.

    아직 열리지 않는 자리는 남아 있다 — 페이즈 전환(``RULE-CHAIN-009``)과
    체인 해결 뒤. 감추지 않고 여기 적어 둔다.
    """
    duel = small_duel(repository)
    opened = False

    for _ in range(200):
        if duel.is_over:
            break
        if duel.advance() is not None:
            continue
        opened = opened or duel.priority.is_open
        legal = duel.legal_actions()
        assert PlayerActionKind.PASS not in legal.kinds()
        duel.apply(legal.allowed[-1])

    assert not opened
