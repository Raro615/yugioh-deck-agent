"""
Phase 3-E-10 — STRUCTURAL-34 Priority / Response Seat Audit (조사 전용).

이 파일은 **아무것도 고치지 않는다.** 지금 엔진에서 "누가 언제 행동할 수
있는가" 가 어떻게 결정되는지를 실행 가능한 주장으로 고정한다.

한 줄 요약
----------
**우선권을 여는 자리가 아무 데도 없다.** 그래서 ``PriorityState`` 는 평생
``holder=NOBODY · window=NONE`` 이고, ``Duel.to_act`` 는 언제나 턴 플레이어로
떨어지고, 상대는 어떤 순간에도 후보를 하나도 받지 못한다.

세 층을 가른다 — "있다" 와 "쓰인다" 는 다르다
---------------------------------------------
=========================  ==========================================
존재한다                     ``PriorityState`` · ``ResponseWindow`` ·
                            ``ResponseLoop`` · ``ActivationTimingChecker``
                            · ``SpellSpeed`` · ``RESPONSE_TABLE``
단위 시험이 있다              위 전부
**실행 경로에 연결된다**      ``PriorityState`` 의 ``idle`` · ``passed`` ·
                            ``closed`` **셋뿐**. ``opened`` 는 ``Duel`` 에서
                            **한 번도 불리지 않는다**
=========================  ==========================================

그런데 틀린 Action 을 만들지는 않는다
-------------------------------------
빠진 자리를 **UNKNOWN 으로 남기고 이유를 적는다.** 상대 자리의 ``PASS`` 는
``withheld`` 로 가고 ``missing`` 에 "우선권을 여는 규칙 (Phase 2-F)" 이
적힌다. 없는 권한을 허가로 바꾸지 않는다 — 그래서 이것은 BLOCKER 가 아니다.

공식 근거
---------
``RULE-CHAIN-001``  "If a card's effect is activated, the opponent is
                    **always** given a chance to respond with a card effect
                    of their own, creating a Chain."
``RULE-CHAIN-009``  "The turn player **always starts with Priority** … A
                    player **must pass Priority** to the opponent when moving
                    on to the next phase or step."
``RULE-CHAIN-011``  "Summoning a monster, Tributing, changing a monster's
                    battle position and paying costs **are not effect
                    activations** and therefore you cannot respond to those
                    actions using a Chain."
``RULE-CHAIN-005``  "Traps (Normal, Continuous), Quick-Play Spells … can
                    typically be activated **during any phase**."
"""

import ast
import pathlib

import pytest

from engine.action import PlayerActionKind
from engine.duel import Duel
from engine.effect.library import EFFECT_LIBRARY
from engine.priority import PriorityHolder, PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
P0, P1 = 0, 1

LUSTER_DRAGON = 11091375
POT_OF_GREED = 55144522

#: ``EFFECT_LIBRARY`` 에 **이미 등록된** 스펠 스피드 2 이상 카드.
#: ``RULE-CHAIN-005`` 가 "can typically be activated during any phase" 라고
#: 적는 카드들인데, 우선권을 여는 자리가 없어 **한 번도 발동할 수 없다.**
SPELL_SPEED_2_PLUS = {
    5915629: "욕망의 선물 (TRAP)",
    92595643: "벌금 (TRAP)",
    94192409: "강제 탈출 장치 (TRAP)",
    24623598: "로스트 (TRAP)",
    69091732: "의적의 입문서 (TRAP)",
    5318639: "싸이크론 (QUICKPLAY)",
    15103313: "육신보살 (QUICKPLAY)",
    22589918: "리로드 (QUICKPLAY)",
}


def source_of(path: str) -> str:
    return (ROOT / path).read_text()


def attributes_in(path: str) -> set[str]:
    tree = ast.parse(source_of(path))
    return {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}


def duel_at(repository, *, turn_player=P0, phase=Phase.MAIN1, hand=(), setzone=()):
    """실제 엔진으로 만든 판 하나. ``create_instance`` 는 엔진의 정상 입구다."""
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20),
        turn_player=turn_player,
        seed=1,
    )
    for card_id in hand:
        state.create_instance(card_id, owner=P0, zone=Zone.HAND)
    for card_id in setzone:
        card = state.create_instance(card_id, owner=P0, zone=Zone.HAND)
        state.move(card, Zone.SZONE, to_player=P0, position=Position.FACEDOWN)
    state.turn.turn_number = 2
    state.turn.turn_player = turn_player
    state.turn.set_phase(phase)
    return Duel(
        state=state,
        priority=PriorityState.idle(turn_player=turn_player, phase=phase),
    )


def play(repository, *, seeds=(1, 2), limit=200):
    """실제 듀얼의 결정을 하나씩 내준다."""
    deck = [POT_OF_GREED] * 4 + [LUSTER_DRAGON] * 16
    for seed in seeds:
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
        for _ in range(limit):
            if duel.is_over:
                break
            if duel.advance() is not None:
                continue
            legal = duel.legal_actions()
            if not legal.allowed:
                break
            yield duel, legal
            duel.apply(legal.allowed[0])


# ======================================================================
# §5 — PriorityState 는 존재하고 전이도 다 있다
# ======================================================================


def test_01_the_priority_vocabulary_is_complete():
    """
    **개념은 모자라지 않다.** 자리 · 기회 · 전이가 전부 있다.

    그래서 STRUCTURAL-34 는 "표현할 데이터 구조가 없다" 가 아니다.
    """
    assert {h.name for h in PriorityHolder} >= {"NOBODY", "PLAYER_0", "PLAYER_1"}
    assert {w.name for w in ResponseWindow} == {
        "NONE",
        "ACTION",
        "RESPONSE",
        "PHASE_CHANGE",
    }
    for field in ("holder", "window", "consecutive_passes", "turn_player", "phase"):
        assert field in PriorityState.__annotations__, field
    for transition in ("idle", "opened", "give_to", "passed", "acted", "closed"):
        assert callable(getattr(PriorityState, transition)), transition


def test_02_the_duel_now_opens_exactly_one_window():
    """
    **``opened`` 가 연결되었다 — 자리 하나에서만** (Phase 3-E-11).

    Phase 3-E-10 Audit 에서 이 시험은 그 반대를 적었다 — ``Duel`` 이
    ``opened`` 를 한 번도 부르지 않는다고. 그것이 STRUCTURAL-34 의 모양이었고,
    이 Phase 가 그 중 **절반**을 이었다.

    **왜 기존 전제가 바뀌었는가.** 규칙이 없었던 것이 아니라 그 자리의 규칙을
    쓰지 않았던 것이다. ``RULE-CHAIN-001`` 이 "the opponent is **always**
    given a chance to respond" 라고 한 문장으로 적으므로 지어낼 것이 없었다.

    나머지 절반은 그대로 비어 있다 — ``give_to``(체인 해결 뒤 누구에게)와
    ``PHASE_CHANGE``(페이즈 전환 · RULE-CHAIN-009). 룰북이 한 문장으로 못
    박지 않거나 이번 범위 밖이므로 **열지 않았다.**
    """
    used = attributes_in("engine/duel.py")
    source = source_of("engine/duel.py")
    assert "idle" in used
    assert "passed" in used

    # **``closed`` 가 ``duel.py`` 에서 사라졌다.** 기회를 닫는 것은 이제
    # ``ResponseLoop.resolve`` 가 한다 — 닫는 이유(``AFTER_CHAIN_RULE``)를
    # 응답 계층이 들고 있으므로 거기서 닫는 것이 맞다. 흐름을 두 곳에서
    # 닫으면 둘이 갈라진다.
    assert "closed" not in used
    assert "closed(AFTER_CHAIN_RULE)" in source_of("engine/response.py")

    # 이번 Phase 가 이은 것 — 기회를 여는 자리가 **하나뿐**이다.
    assert "opened" in used
    assert source.count("ResponseLoop.opened(") == 1

    # 아직 잇지 않은 것.
    assert "give_to" not in used
    assert "acted" not in used
    assert "PHASE_CHANGE" not in source

    # 여는 능력은 처음부터 있었다 — 부르는 쪽이 없었을 뿐이다.
    assert "PriorityState.opened(" in source_of("engine/response.py")
    assert "priority.acted()" in source_of("engine/activation.py")


def test_03_the_response_loop_is_now_imported_by_the_duel_and_only_the_duel():
    """
    **끊겼던 사슬이 이어졌다** (Phase 3-E-11).

    Phase 3-E-10 Audit 은 ``ResponseLoop`` 를 import 하는 production 모듈이
    0개라고 적었다 — ``activation_timing`` → ``response`` → (아무도 없음).

    지금은 ``duel.py`` 가 그 끝을 잡는다. **그리고 그것 하나뿐이다** — agent
    계층은 여전히 우선권을 모른다 (``test_10`` 이 지킨다).
    """
    importers = []
    for path in sorted(ROOT.glob("engine/**/*.py")) + sorted(ROOT.glob("agent/*.py")):
        if path.name == "response.py":
            continue
        text = path.read_text()
        if "from engine.response import" in text or "import engine.response" in text:
            importers.append(path.name)
    assert importers == ["duel.py"], importers

    # 사슬의 위쪽은 그대로다.
    assert "from engine.activation_timing import" in source_of("engine/response.py")


# ======================================================================
# §7 — legal_actions 는 우선권을 **읽지만** 언제나 닫혀 있다
# ======================================================================


@pytest.mark.real_card
def test_04_the_window_is_closed_at_every_decision_of_a_real_duel(repository):
    """
    **실제 대국 전체에서 기회가 한 번도 열리지 않는다.**

    그래서 ``to_act`` 는 언제나 턴 플레이어이고 (Phase 3-E-9 의 1053/1053 과
    같은 사실), ``legal_actions`` 의 우선권 분기는 **한쪽만** 돈다.
    """
    checked = 0
    for duel, legal in play(repository):
        assert duel.priority.holder is PriorityHolder.NOBODY
        assert duel.priority.window is ResponseWindow.NONE
        assert duel.priority.is_open is False
        assert duel.to_act == duel.turn_player
        assert legal.seat == duel.turn_player
        checked += 1
    assert checked > 100, checked


@pytest.mark.real_card
def test_05_the_opponent_never_receives_a_candidate(repository):
    """
    **상대 자리의 후보가 언제나 비어 있다.** 그리고 그 이유가 적혀 있다.

    ``withheld`` 의 ``missing`` 이 "우선권을 여는 규칙 (Phase 2-F)" 이라고
    말한다 — 없는 권한을 허가로 바꾸지 않는다. 이것이 이 공백을 BLOCKER 가
    아니게 만드는 성질이다.
    """
    checked = 0
    for duel, legal in play(repository):
        other = duel.legal_actions(1 - legal.seat)
        assert other.allowed == (), other.allowed
        passes = [w for w in other.withheld if w.kind is PlayerActionKind.PASS]
        assert len(passes) == 1, other.withheld
        assert "우선권" in passes[0].reason
        assert passes[0].missing is not None
        assert "우선권" in passes[0].missing
        checked += 1
    assert checked > 100, checked


@pytest.mark.real_card
def test_06_no_registered_fast_effect_can_ever_be_activated(repository):
    """
    **§14 — 어떤 '정상 Action' 이 누락되는가.**

    ``EFFECT_LIBRARY`` 에 **이미 등록된** 함정 5장과 속공 마법 3장이 있다.
    ``RULE-CHAIN-005`` 는 이들이 "can typically be activated **during any
    phase**" 라고 적는다. 그런데 상대 턴에는 후보가 **하나도** 나오지 않는다 —
    우선권을 여는 자리가 없기 때문이다.

    가설이 아니라 이름이 있는 카드들이다.
    """
    registered = {entry.effect_ref.card_id for entry in EFFECT_LIBRARY}
    assert set(SPELL_SPEED_2_PLUS) <= registered, set(SPELL_SPEED_2_PLUS) - registered

    for card_id, name in SPELL_SPEED_2_PLUS.items():
        for where in ("hand", "set"):
            duel = duel_at(
                repository,
                turn_player=P1,  # **상대 턴**이다
                hand=(card_id,) if where == "hand" else (),
                setzone=(card_id,) if where == "set" else (),
            )
            legal = duel.legal_actions(P0)
            assert legal.allowed == (), (name, where, legal.allowed)
            # 그리고 그 이유가 우선권이라고 적혀 있다.
            reasons = {w.missing for w in legal.withheld}
            assert any(r and "우선권" in r for r in reasons), (name, where, reasons)


# ======================================================================
# §9 — Chain 이 남아 있는 결정 시점이 없다
# ======================================================================


@pytest.mark.real_card
def test_07_the_chain_now_stays_up_while_the_opponent_may_respond(repository):
    """
    **Scenario 4~7 이 이제 도달 가능하다** (Phase 3-E-11).

    Phase 3-E-10 Audit 에서 이 시험은 그 반대를 적었다 — ``_apply_activation``
    이 놓기 → 발동 → 해결 → 묘지로 를 한 ``apply`` 안에서 끝내므로 "체인 링크
    1 이 남아 있고 상대가 응답할 수 있는 결정 시점" 이 존재하지 않는다고.
    그때는 그것이 사실이었고, 없는 상태를 억지로 만들지 않은 것이 옳았다.

    **왜 기존 전제가 바뀌었는가.** ``RULE-CHAIN-001`` 이 요구하는 응답 기회를
    이 Phase 가 이었다. 그래서 발동과 해결 사이에 **결정 시점이 하나 생겼고**,
    그 자리에서 체인은 **쌓인 채로** 있다.

    결정 시점이 아닌 자리(발동 전·해결 후)에서는 체인이 여전히 비어 있다.
    """
    checked = 0
    for duel, legal in play(repository):
        # 응답 창이 열려 있지 않은 결정에서는 체인이 비어 있다.
        if not duel.priority.is_open:
            assert len(duel.chain) == 0, len(duel.chain)
            assert duel.chain.is_complete
        checked += 1
    assert checked > 100, checked

    # 발동 직후 — **체인이 쌓여 있고 상대가 결정할 차례다.**
    duel = duel_at(repository, hand=(POT_OF_GREED,))
    activate = next(
        a
        for a in duel.legal_actions().allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    )
    step = duel.apply(activate)
    assert step.accepted, step.reason
    assert len(duel.chain) == 1
    assert duel.priority.window is ResponseWindow.RESPONSE
    assert duel.priority.holder.is_seat(P1)
    # 상대에게 **기회가 간다** — 이것이 이 Phase 가 만든 것이다.
    assert [a.kind for a in duel.legal_actions(P1).allowed] == [
        PlayerActionKind.PASS
    ]
    # 그리고 턴 플레이어는 지금 판을 바꿀 수 없다 (RULE-CHAIN-011).
    assert duel.legal_actions(P0).allowed == ()

    # 둘 다 패스하면 해결되고, 체인은 다시 비워진다.
    assert duel.apply(duel.legal_actions(P1).allowed[0]).accepted
    assert duel.apply(duel.legal_actions(P0).allowed[0]).accepted
    assert len(duel.chain) == 0
    assert duel.priority.window is ResponseWindow.NONE


# ======================================================================
# §10 — END_PHASE 는 우선권을 넘기지 않는다
# ======================================================================


@pytest.mark.real_card
def test_08_end_phase_resets_priority_instead_of_passing_it(repository):
    """
    **``RULE-CHAIN-009`` 와 어긋나는 자리.**

        "A player **must pass Priority** to the opponent when moving on to
        the next phase or step. … announcing the end of your phases or steps
        **implies giving up Priority**."

    공식 규칙은 페이즈를 넘길 때 **상대에게 기회가 생긴다**고 적는다. 지금
    구현은 ``PriorityState.idle()`` 로 **되돌린다** — 넘기는 것이 아니라
    없애는 것이다. ``ResponseWindow.PHASE_CHANGE`` 가 그 자리를 위해 이미
    정의되어 있는데 쓰이지 않는다.

    세 가지를 가른다 (§10): ① 페이즈를 끝내는 행위 ② 우선권을 넘기는 것
    ③ 실제로 다음 페이즈로 전이하는 것. 지금 ``END_PHASE`` 는 ①과 ③을 하고
    **②를 하지 않는다.**
    """
    assert ResponseWindow.PHASE_CHANGE in set(ResponseWindow)
    assert "PHASE_CHANGE" not in source_of("engine/duel.py")

    duel = duel_at(repository, phase=Phase.MAIN1)
    end = next(
        a
        for a in duel.legal_actions().allowed
        if a.kind is PlayerActionKind.END_PHASE
    )
    before = duel.state.turn.phase
    assert duel.apply(end).accepted
    assert duel.state.turn.phase is not before  # ③ 전이는 했다
    assert duel.priority.window is ResponseWindow.NONE  # ② 넘기지 않았다
    assert duel.priority.holder is PriorityHolder.NOBODY
    assert duel.legal_actions(P1).allowed == ()  # 상대에게 기회가 없다


@pytest.mark.real_card
def test_09_a_summon_correctly_opens_no_window(repository):
    """
    **여기는 지금 구현이 규칙과 맞는 자리다** (``RULE-CHAIN-011``).

        "Summoning a monster, Tributing, changing a monster's battle position
        and paying costs **are not effect activations** and therefore you
        cannot respond to those actions using a Chain."

    소환 뒤에 응답 기회가 없는 것은 **누락이 아니라 규칙대로**다. 공백을
    고칠 때 여기까지 열면 틀린다 — 그래서 함께 고정한다.
    """
    duel = duel_at(repository, hand=(LUSTER_DRAGON,))
    summon = next(
        a
        for a in duel.legal_actions().allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
    )
    assert duel.apply(summon).accepted
    assert duel.priority.window is ResponseWindow.NONE
    assert duel.legal_actions(P1).allowed == ()


# ======================================================================
# §11 · §12 — 경계는 지켜져 있다
# ======================================================================


def test_10_priority_is_not_in_the_observation_and_not_in_the_agent():
    """
    **우선권은 관측에도, agent 에도 없다.**

    ``GameStateView`` 가 ``priority`` 를 노출하지 않으므로 평가도 탐색도 그것을
    읽을 수 없다. Phase 3-E-5 ~ 3-E-9 가 세운 경계("Evaluation = State Value,
    행동 가능성은 Action Space / Engine 의 일")가 **구조로** 지켜진다.

    그래서 STRUCTURAL-34 를 고칠 때 ``GameStateView`` 를 넓힐 이유가 없다.
    """
    assert "priority" not in source_of("engine/game_state_view.py")
    for path in ("agent/evaluation.py", "agent/search.py", "agent/policy.py",
                 "agent/heuristic.py"):
        assert "priority" not in source_of(path), path
        assert "Priority" not in source_of(path), path


def test_11_the_simulator_shares_the_frozen_priority_safely():
    """
    **§11 — 사본이 우선권을 공유하지만 안전하다.**

    ``Simulator._fork`` 는 판만 복제하고 ``priority`` 와 ``chain`` 은 참조를
    공유한다. 둘 다 ``frozen=True`` 이고, ``Duel`` 은 전이할 때 **새 값을
    대입**하므로 사본의 전이가 진짜를 건드리지 않는다.

    그러므로 지금 우선권이 Search 를 망치지 않는다 — 열리지 않아서가 아니라
    **구조가 안전해서**다.
    """
    from engine.chain import Chain

    assert PriorityState.__dataclass_params__.frozen
    assert Chain.__dataclass_params__.frozen
    source = source_of("engine/duel.py")
    # 전이는 전부 **대입**이다 — 제자리 변경이 없다.
    assert "self.priority = " in source
    assert "self.chain = " in source
