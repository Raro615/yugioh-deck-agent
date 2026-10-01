"""
Phase 3-A — AI Action Interface.

    GameState
      ↓ view(viewer)
    GameStateView        정책이 보는 전부
      ↓ legal_actions(seat)
    LegalActions         정책이 고를 수 있는 전부
      ↓ Policy.decide(...)
    PlayerAction
      ↓ Duel.apply(...)
    GameState'

이 파일이 지키는 경계
---------------------
**정책은 관측과 후보 목록만 본다.** :class:`Duel` 도 :class:`GameState` 도
정책에게 가지 않는다 — 가면 정책이 상대 패를 읽거나 판을 바꿀 수 있고, 그
순간 "AI 가 엔진을 쓴다" 가 "AI 가 엔진이다" 가 된다.

**정책의 말은 허가가 아니다.** 돌려준 것을 그대로 적용하지 않고 후보
목록에서 다시 확인한다 — 엔진이 ``UNKNOWN`` 을 허가로 바꾸지 않는 것과
같은 자리다.

**정책의 난수는 듀얼의 난수가 아니다.** 이것은 이번에 정한 것이 아니라
``RandomPurpose`` 가 이미 적어 둔 결정이다: "AI 가 한 번 더 생각했다는
이유로 듀얼의 결과가 달라진다" 를 막는다.
"""

import ast
import collections
import pathlib

import pytest

from agent import (
    DuelRunner,
    FirstLegalPolicy,
    Policy,
    PolicyError,
    RandomPolicy,
    RunnerError,
    ScriptedPolicy,
    play,
)
from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.vocabulary import Phase, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
FEATHERMAN = 21844576
POT_OF_GREED = 55144522
MINE, THEIRS = 0, 1


def small_duel(repository, *, seed: int = 5) -> Duel:
    deck = [FEATHERMAN] * 10 + [POT_OF_GREED] * 2
    return Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)


class Spy:
    """정책이 **무엇을 받았는지** 기록한다. 고르지는 않는다."""

    name = "spy"

    def __init__(self):
        self.seen = []

    def decide(self, view, legal):
        self.seen.append((view, legal))
        return legal.allowed[0] if legal.allowed else None


# ======================================================================
# A. 경계 — 정책이 무엇을 받는가
# ======================================================================


@pytest.mark.real_card
def test_a_the_policy_only_ever_receives_a_view_and_a_list(repository):
    """
    **이것이 이 단계의 핵심이다.** 정책에게 가는 것은 둘뿐이다.
    """
    duel = small_duel(repository)
    spy = Spy()

    DuelRunner(duel, (spy, FirstLegalPolicy())).run()

    assert spy.seen
    for view, legal in spy.seen:
        assert isinstance(view, GameStateView)
        assert not isinstance(view, Duel)
        assert legal.seat == MINE
        # 관측은 스냅숏이다 — 판을 가리키는 손잡이가 없다.
        assert not hasattr(view, "draw")
        assert not hasattr(view, "move")
        assert not hasattr(view, "set_result")


def test_a_the_runner_hands_over_nothing_else():
    """
    AST 로 못박는다. ``decide`` 를 부르는 자리가 넘기는 것은
    ``self.duel.view(seat)`` 와 ``legal`` 뿐이다.
    """
    source = (ROOT / "agent/runner.py").read_text()
    tree = ast.parse(source)

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "decide"
    ]
    assert calls, "정책을 부르는 자리가 없습니다."
    for call in calls:
        assert not call.keywords
        assert len(call.args) == 2
        first, second = call.args
        assert ast.unparse(first) == "self.duel.view(seat)"
        assert ast.unparse(second) == "legal"


@pytest.mark.real_card
def test_a_the_policy_cannot_see_the_opponents_hand(repository):
    """관측 경계는 그대로다. 정책이 우회할 틈이 없다."""
    duel = small_duel(repository)
    spy = Spy()

    DuelRunner(duel, (spy, FirstLegalPolicy())).run()

    for view, _ in spy.seen:
        theirs = view.player(THEIRS).zone(Zone.HAND)
        assert theirs.concealed
        assert theirs.cards == ()
        assert theirs.size >= 0  # 장수는 공개다


@pytest.mark.real_card
def test_a_thinking_harder_does_not_change_the_duel(repository):
    """
    **``RandomPurpose`` 가 이미 적어 둔 결정을 지킨다.**

        "AI 가 한 번 더 생각했다는 이유로 듀얼의 결과가 달라진다" — 그것을
        막으려고 정책의 난수원을 따로 둔다.

    정책이 500번을 더 뽑아도 덱 셔플은 그대로다.
    """
    quiet = small_duel(repository, seed=13)
    noisy = small_duel(repository, seed=13)
    assert quiet.state.state_hash() == noisy.state.state_hash()

    busy = RandomPolicy(7)
    for _ in range(500):
        busy._rng.random()  # 일부러 많이 생각한다

    play(quiet, (FirstLegalPolicy(), FirstLegalPolicy()))
    play(noisy, (FirstLegalPolicy(), FirstLegalPolicy()))

    assert quiet.state.state_hash() == noisy.state.state_hash()


def test_a_the_agent_package_does_not_touch_the_engine():
    """
    ``engine/`` 은 얼렸다 (V1 FREEZE). ``agent/`` 는 **고치지 않고 쓴다.**

    판을 바꾸는 메서드를 부르는 코드가 하나도 없다 — 바꾸는 것은 엔진의
    일이고, 러너는 전달만 한다.
    """
    forbidden = {"draw", "move", "set_result", "change_life", "set_phase", "clear"}
    for path in sorted((ROOT / "agent").glob("*.py")):
        tree = ast.parse(path.read_text())
        touched = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden
        }
        assert touched == set(), (path.name, touched)


# ======================================================================
# B. 정책의 말은 허가가 아니다
# ======================================================================


class Rogue:
    """목록에 없는 것을 돌려주는 정책."""

    name = "rogue"

    def __init__(self, action):
        self._action = action

    def decide(self, view, legal):
        return self._action


@pytest.mark.real_card
def test_b_an_action_outside_the_list_is_refused(repository):
    duel = small_duel(repository)
    before = duel.state.state_hash()
    stranger = PlayerAction.normal_summon(actor=MINE, source=InstanceId(9999))

    transcript = DuelRunner(duel, (Rogue(stranger), FirstLegalPolicy())).run()

    assert transcript.refusals
    assert "허가된 후보가 아닙니다" in transcript.refusals[0].reason
    assert duel.state.state_hash() == before  # 판은 그대로다
    assert not transcript.finished


@pytest.mark.real_card
def test_b_acting_for_the_other_seat_is_refused(repository):
    duel = small_duel(repository)
    theirs = PlayerAction.passing(actor=THEIRS)

    transcript = DuelRunner(duel, (Rogue(theirs), FirstLegalPolicy())).run()

    assert transcript.refusals
    assert "차례인데" in transcript.refusals[0].reason


@pytest.mark.real_card
def test_b_something_that_is_not_an_action_is_refused(repository):
    duel = small_duel(repository)

    transcript = DuelRunner(duel, (Rogue("end_phase"), FirstLegalPolicy())).run()

    assert transcript.refusals
    assert "PlayerAction 이 아닌" in transcript.refusals[0].reason


@pytest.mark.real_card
def test_b_refusing_to_choose_when_there_are_options_is_refused(repository):
    """
    **고를 것이 없는 것과 안 고르는 것은 다른 사실이다.** 후자는
    ``PASS`` 라는 행위이고, ``None`` 은 행위가 아니다.
    """
    duel = small_duel(repository)

    transcript = DuelRunner(duel, (Rogue(None), FirstLegalPolicy())).run()

    assert transcript.refusals
    assert "아무것도 고르지 않았습니다" in transcript.refusals[0].reason


@pytest.mark.real_card
def test_b_a_refusal_stops_the_run_instead_of_repeating(repository):
    """
    거절 뒤에도 계속 돌리면 같은 거절이 끝없이 반복되고 기록이 그것으로
    채워진다.
    """
    duel = small_duel(repository)
    stranger = PlayerAction.normal_summon(actor=MINE, source=InstanceId(9999))

    transcript = DuelRunner(duel, (Rogue(stranger), FirstLegalPolicy())).run()

    assert len(transcript.refusals) == 1
    assert transcript.entries[-1] is transcript.refusals[0]


# ======================================================================
# C. 한 판이 돈다
# ======================================================================


@pytest.mark.real_card
def test_c_two_random_policies_finish_a_duel(repository):
    """**§1 의 흐름이 끝까지 돈다.** 거절 하나 없이."""
    transcript = play(
        small_duel(repository), (RandomPolicy(1, "r0"), RandomPolicy(2, "r1"))
    )

    assert transcript.finished
    assert transcript.result.winner in (0, 1)
    assert transcript.refusals == ()
    assert transcript.rule_steps > 0  # 드로우는 고르는 일이 아니다
    assert transcript.by_seat(MINE) and transcript.by_seat(THEIRS)


@pytest.mark.real_card
def test_c_the_transcript_records_who_chose_what(repository):
    transcript = play(
        small_duel(repository), (RandomPolicy(1, "alpha"), RandomPolicy(2, "beta"))
    )

    names = {entry.policy for entry in transcript.entries}
    assert names == {"alpha", "beta"}
    for entry in transcript.entries:
        assert entry.action is not None
        assert entry.action.actor == entry.seat
        assert entry.accepted


@pytest.mark.real_card
def test_c_a_scripted_policy_can_steer_the_duel(repository):
    """
    정책이 **실제로 영향을 준다.** 소환을 먼저 고르게 하면 그 자리에
    몬스터가 선다.
    """
    duel = small_duel(repository)
    plan = ScriptedPolicy(
        (PlayerActionKind.END_PHASE,) * 2 + (PlayerActionKind.NORMAL_SUMMON,)
    )

    runner = DuelRunner(duel, (plan, FirstLegalPolicy()))
    for _ in range(12):
        runner.step()

    assert len(duel.state.player(MINE).monster_zone) >= 1


# ======================================================================
# D. 재현
# ======================================================================


@pytest.mark.real_card
def test_d_the_same_seeds_give_the_same_duel(repository):
    """듀얼 씨앗과 정책 씨앗이 같으면 **같은 판**이다."""
    runs = [
        play(small_duel(repository, seed=11), (RandomPolicy(3), RandomPolicy(4)))
        for _ in range(3)
    ]

    assert len({run.canonical_state() for run in runs}) == 1


@pytest.mark.real_card
def test_d_a_different_policy_seed_gives_a_different_duel(repository):
    """
    듀얼 씨앗이 같아도 **정책이 다르면 판이 다르다.** 그렇지 않으면
    정책이 아무 일도 하지 않는다는 뜻이다.
    """
    one = play(small_duel(repository, seed=11), (RandomPolicy(3), RandomPolicy(4)))
    two = play(small_duel(repository, seed=11), (RandomPolicy(31), RandomPolicy(41)))

    assert one.canonical_state() != two.canonical_state()


@pytest.mark.real_card
def test_d_a_different_duel_seed_gives_a_different_duel(repository):
    one = play(small_duel(repository, seed=11), (RandomPolicy(3), RandomPolicy(4)))
    two = play(small_duel(repository, seed=29), (RandomPolicy(3), RandomPolicy(4)))

    assert one.canonical_state() != two.canonical_state()


def test_d_a_policy_without_a_seed_is_refused():
    """씨앗 없는 무작위는 재현할 수 없다 (Phase 2-Z 와 같은 규칙)."""
    with pytest.raises(PolicyError, match="씨앗은 정수"):
        RandomPolicy("아무거나")  # type: ignore[arg-type]
    with pytest.raises(PolicyError):
        RandomPolicy(True)  # type: ignore[arg-type]


@pytest.mark.real_card
def test_d_the_runner_needs_one_policy_per_seat(repository):
    duel = small_duel(repository)

    with pytest.raises(RunnerError, match="자리마다 하나씩"):
        DuelRunner(duel, (FirstLegalPolicy(),))
    with pytest.raises(RunnerError, match="decide 가 없습니다"):
        DuelRunner(duel, (FirstLegalPolicy(), object()))


# ======================================================================
# E. 지금 AI 에게 주어진 방의 크기
# ======================================================================


@pytest.mark.real_card
def test_e_how_much_room_a_policy_actually_has(repository):
    """
    **정직하게 적는다.** 결정 지점의 3분의 1에만 고를 것이 둘 이상 있고,
    그 자리는 전부 메인 페이즈다. 나머지는 페이즈 넘기기 하나뿐이다.

    ::

        후보 1개     60곳     페이즈를 넘기는 것 말고 할 것이 없다
        후보 4~11개  30곳     메인 페이즈 — 패의 몬스터를 소환할 수 있다

    방이 좁은 이유는 Engine V1 의 알려진 한계다 — 마법 발동과 우선권 창이
    아직 없다 (STRUCTURAL-103). AI 가 할 일이 적은 것이지, 인터페이스가
    좁은 것이 아니다.
    """
    duel = small_duel(repository)
    sizes: collections.Counter = collections.Counter()
    branching_phases = set()

    while not duel.is_over:
        if duel.advance() is not None:
            continue
        legal = duel.legal_actions()
        sizes[len(legal.allowed)] += 1
        if len(legal.allowed) > 1:
            branching_phases.add(duel.state.turn.phase)
        duel.apply(legal.allowed[-1])

    total = sum(sizes.values())
    branching = sum(count for size, count in sizes.items() if size > 1)

    assert sizes[1] == 60
    assert branching == 30
    assert total == 90
    assert branching_phases == {Phase.MAIN1, Phase.MAIN2}
    assert max(sizes) == 11


@pytest.mark.real_card
def test_e_the_runner_gives_up_loudly_rather_than_spinning(repository):
    """
    상한에 닿으면 **소리를 낸다.** 조용히 멈추면 "끝난 듀얼" 과 "멈춘
    듀얼" 이 같은 모양이 된다.
    """
    duel = small_duel(repository)

    with pytest.raises(RunnerError, match="걸음 안에 끝나지"):
        DuelRunner(duel, (FirstLegalPolicy(), FirstLegalPolicy())).run(max_steps=3)


def test_e_the_baseline_policies_are_not_ai():
    """
    이 꾸러미에 **평가 함수도 탐색도 학습도 없다.** 기준점 셋은
    인터페이스가 도는지 보이기 위한 것이다.
    """
    source = "\n".join(
        path.read_text() for path in sorted((ROOT / "agent").glob("*.py"))
    )
    for word in ("evaluate", "minimax", "mcts", "rollout", "reward", "train"):
        assert word not in source.lower(), word

    assert isinstance(FirstLegalPolicy(), Policy)
    assert isinstance(RandomPolicy(1), Policy)
    assert isinstance(ScriptedPolicy(()), Policy)
