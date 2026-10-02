"""
Phase 3-E-9 — STRUCTURAL-128 Side-to-Move Audit (조사 전용).

이 파일은 **아무것도 고치지 않는다.** 지금 평가가 차례를 어떻게 다루는지를
실행 가능한 주장으로 고정한다. 다음 Phase 가 무엇을 바꾸는지 이 파일이 깨지는
것으로 보인다.

세 층을 가른다
--------------
=================  =====================================================
State              ``canonical_state`` · ``state_hash`` 가 ``turn_player``
                   를 **포함한다** (``TurnState.canonical_state``)
Observation        ``GameStateView.turn_player`` · ``is_my_turn`` 이
                   **있다**
Evaluation         ``StateValue`` 의 **어느 칸도** 차례를 반영하지 않는다
=================  =====================================================

그래서 "정보가 없다" 가 아니라 **"평가가 읽지 않는다"** 가 맞다.

그런데 그것이 지금 잘못된 순위를 만드는가
-----------------------------------------
**만들지 않는다** — 그리고 그 이유가 평가에 있지 않다. 차례를 바꾸는 행위는
``END_PHASE`` 하나이고, 그것이 차례를 넘기는 자리(END 페이즈)에서는 **후보가
그것뿐**이다 (실측 131/131). 한 결정 안의 모든 후보가 같은 차례를 공유하므로,
차례는 그 결정에서 **모든 후보에 공통인 상수**다 — 상수는 순위를 바꿀 수 없다.

그러므로 이것은 **지금 증상이 없는 구조적 공백**이다. 응답 창이 열리거나
(STRUCTURAL-34) END 페이즈에 발동이 후보로 오르면 바로 증상이 생긴다.

**viewer 와 turn_player 를 혼동하지 않는다.** 평가의 관점은 ``viewer`` 이고
차례는 ``turn_player`` 다. 결정 시점에는 둘이 **언제나 같지만**(실측
1053/1053), 미래에는 다를 수 있다 — 평가가 못 보는 것은 **미래의 차례**다.
"""

import ast
import pathlib
import random

import pytest

from agent.evaluation import StateEvaluator
from agent.simulation import Simulator
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
P0, P1 = 0, 1
EV = StateEvaluator()

LUSTER_DRAGON = 11091375  # ATK 1900 / DEF 1600
BATTLE_OX = 5053103  # ATK 1700 / DEF 1000
POT_OF_GREED = 55144522
CORPUS_DECK = [LUSTER_DRAGON] * 10 + [BATTLE_OX] * 6 + [POT_OF_GREED] * 4

#: 관측이 노출하는 **차례 문맥 전부.** 평가가 이 중 하나라도 읽으면
#: ``test_02`` 가 깨진다 — "이름이 ``turn_player`` 가 아니어서 못 찾았다" 가
#: 되지 않도록 간접 경로까지 함께 적는다.
TURN_CONTEXT = (
    "turn_player",
    "turn_number",
    "is_my_turn",
    "phase",
    "step",
    "normal_summons_used",
    "attacks_used",
    "attacks_by",
)


def board(repository, *, turn_player: int) -> GameState:
    """
    양쪽에 같은 몬스터 하나씩, **차례만 다른** 두 합법 상태를 만든다.

    ``GameState.create(turn_player=...)`` 는 엔진의 정상 입구다 — 어느 쪽이
    선공인지는 듀얼이 정상적으로 갖는 값이므로 가짜 상태가 아니다.
    """
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20),
        turn_player=turn_player,
        seed=1,
    )
    for seat in (P0, P1):
        card = state.create_instance(LUSTER_DRAGON, owner=seat, zone=Zone.HAND)
        state.move(
            card, Zone.MZONE, to_player=seat, position=Position.FACEUP_ATTACK
        )
    state.turn.turn_number = 2
    state.turn.turn_player = turn_player
    state.turn.set_phase(Phase.MAIN1)
    return state


def source_names(path: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text())
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }


def decisions(repository, *, seeds=range(1, 7), limit=300):
    """실제 듀얼의 결정을 하나씩 내준다. 무작위로 고르되 seed 로 고정한다."""
    for seed in seeds:
        rng = random.Random(seed)
        duel = Duel.start(
            repository, decks=(list(CORPUS_DECK), list(CORPUS_DECK)), seed=seed
        )
        for _ in range(limit):
            if duel.is_over:
                break
            if duel.advance() is not None:
                continue
            legal = duel.legal_actions()
            if not legal.allowed:
                break
            yield duel, legal
            duel.apply(rng.choice(legal.allowed))


# ======================================================================
# §17-1 · §17-4 — 정보는 관측에 있다. viewer 는 차례가 아니다
# ======================================================================


@pytest.mark.real_card
def test_01_the_observation_exposes_the_whole_turn_context(repository):
    """
    **§2-B — 정보가 없어서 읽지 못하는 것이 아니다.**

    ``GameStateView`` 는 차례 문맥을 전부 노출한다. 그리고 그것은 **공개
    정보**다 — 두 관점에서 같은 값이 나온다. 그래서 나중에 평가가 이것을
    읽기로 해도 관측 경계를 깨지 않는다 (§10).
    """
    state = board(repository, turn_player=P0)
    views = {viewer: GameStateView.from_state(state, viewer=viewer) for viewer in (P0, P1)}

    for name in ("turn_player", "turn_number", "phase", "step", "is_my_turn"):
        assert hasattr(views[P0], name), name

    # 차례는 **양쪽이 똑같이 아는 사실**이다 — 가려진 정보가 아니다.
    assert views[P0].turn_player == views[P1].turn_player == P0
    assert views[P0].turn_number == views[P1].turn_number
    assert views[P0].phase is views[P1].phase

    # ``is_my_turn`` 만 관점에 따라 달라진다 — 같은 사실을 각자 입장에서
    # 읽은 것이기 때문이다.
    assert views[P0].is_my_turn is True
    assert views[P1].is_my_turn is False


@pytest.mark.real_card
def test_02_the_evaluation_reads_no_part_of_the_turn_context(repository):
    """
    **§2-C · §2-D — 직접도 간접도 읽지 않는다.**

    "이름이 ``turn_player`` 가 아니어서 못 찾았다" 가 되지 않도록, 차례를
    알 수 있는 **모든** 관측 이름을 함께 본다.
    """
    names = source_names("agent/evaluation.py")
    for name in TURN_CONTEXT:
        assert name not in names, f"평가가 {name} 을 읽는다 — 이 Audit 의 전제가 깨졌다"

    # 평가가 실제로 읽는 것은 **관점과 자원**뿐이다.
    for name in ("viewer", "me", "opponent", "life_points", "winner", "is_over"):
        assert name in names, name


@pytest.mark.real_card
def test_03_viewer_changes_the_score_but_turn_player_does_not(repository):
    """
    **§9 — ``viewer`` 와 ``turn_player`` 는 다른 개념이다.**

    같은 판을 반대 자리에서 보면 점수가 **뒤집힌다**(관점이 바뀌었다).
    같은 판에서 차례만 바꾸면 점수가 **한 칸도 움직이지 않는다**(평가가
    차례를 읽지 않는다).

    둘이 같은 개념이라면 두 실험의 결과가 같아야 한다. 다르다 — 그래서
    "평가는 viewer 를 안다, 그러므로 차례도 안다" 는 추론은 성립하지 않는다.
    """
    state = board(repository, turn_player=P0)
    state.player(P1).change_life(-1000)  # 비대칭을 만들어 부호가 보이게 한다

    mine = EV.evaluate(GameStateView.from_state(state, viewer=P0))
    theirs = EV.evaluate(GameStateView.from_state(state, viewer=P1))
    assert mine.heuristic == -theirs.heuristic != 0, "관점을 바꾸면 뒤집힌다"


@pytest.mark.real_card
def test_04_the_three_layers_disagree_about_the_turn(repository):
    """
    **§5 · §6 — 차례만 다른 두 합법 상태를 끝까지 따라간다.**

    State 와 Observation 은 둘을 **구분하고**, Evaluation 만 구분하지 않는다.
    정보가 평가에서 **사라진다** — 이것이 STRUCTURAL-128 의 정확한 모양이다.

    이 시험은 **지금의 사실을 고정한다.** 다음 Phase 가 평가에 차례를 넣으면
    이 시험이 깨지고, 그것이 의도된 신호다.
    """
    first, second = board(repository, turn_player=P0), board(repository, turn_player=P1)

    # ① State — 구분한다.
    assert first.state_hash() != second.state_hash()
    assert first.canonical_state() != second.canonical_state()
    assert first.turn.canonical_state() != second.turn.canonical_state()

    for viewer in (P0, P1):
        a = GameStateView.from_state(first, viewer=viewer)
        b = GameStateView.from_state(second, viewer=viewer)

        # ② Observation — 구분한다.
        assert a.turn_player != b.turn_player
        assert a.is_my_turn is not b.is_my_turn

        # ③ Evaluation — **구분하지 않는다.** 모든 칸이 같다.
        x, y = EV.evaluate(a), EV.evaluate(b)
        assert x.terminal is y.terminal
        assert x.heuristic == y.heuristic
        assert x.terms == y.terms
        assert x.excluded == y.excluded
        assert x.partial == y.partial
        assert x.ordering_key() == y.ordering_key()


# ======================================================================
# §17-3 · §17-6 — 엔진이 스스로 만드는 사례와 Search 영향
# ======================================================================


@pytest.mark.real_card
def test_05_handing_over_the_turn_costs_nothing_in_the_score(repository):
    """
    **§5 — 가짜 상태 없이, 엔진이 스스로 만드는 쌍.**

    END 페이즈의 ``END_PHASE`` 는 판을 바꾸지 않고 **차례만** 넘긴다
    (``turn_player`` 가 뒤집히고 ``turn_number`` 가 하나 늘고 페이즈가
    ``DRAW`` 가 된다). 시뮬레이션은 ``advance()`` 를 돌리지 않으므로 다음
    턴의 드로우도 아직 일어나지 않는다.

    그래서 이 쌍은 "같은 판, 차례만 다름" 의 **실제 합법 사례**다. 점수는
    한 칸도 움직이지 않는다 — 평가에게 턴을 넘기는 일은 **공짜**다.
    """
    checked = 0
    for duel, legal in decisions(repository, seeds=(1, 2)):
        if duel.state.turn.phase is not Phase.END:
            continue
        seat = legal.seat
        before = EV.evaluate(duel.view(seat))
        result = Simulator(duel).simulate(legal.allowed[0], viewer=seat)
        assert result.future is not None
        after = EV.evaluate(result.future)

        # 차례 문맥은 바뀌었다.
        assert result.future.turn_player != seat
        assert result.future.turn_number == duel.state.turn.turn_number + 1
        assert result.future.phase is Phase.DRAW
        assert result.future.viewer == seat, "보는 사람은 그대로다"

        # 점수는 바뀌지 않았다.
        assert before.terminal is after.terminal
        assert before.heuristic == after.heuristic
        assert before.terms == after.terms
        assert before.ordering_key() == after.ordering_key()
        checked += 1
        if checked >= 3:
            break
    assert checked >= 3, checked


@pytest.mark.real_card
def test_06_within_one_decision_the_turn_is_the_same_for_every_candidate(
    repository,
):
    """
    **§7 · §13 — 그래서 지금 순위가 틀어지지 않는다.**

    한 결정의 모든 후보가 **같은 미래 차례**를 갖는다. 차례는 그 결정에서
    모든 후보에 공통인 **상수**이고, 상수는 순위를 바꿀 수 없다.

    이유는 평가에 있지 않고 **행동 공간에 있다**: 차례를 넘기는 유일한 행위
    (END 페이즈의 ``END_PHASE``)에게는 **형제 후보가 없다.** END 페이즈에
    발동이 후보로 오르면(STRUCTURAL-34 가 열리면) 그날 이 시험이 깨진다.
    """
    total = split = passing_alone = passing_total = 0
    for duel, legal in decisions(repository):
        seat = legal.seat
        simulator = Simulator(duel)
        futures = []
        for action in legal.allowed:
            result = simulator.simulate(action, viewer=seat)
            if result.future is None:
                continue
            futures.append((action, result.future.turn_player))
        if not futures:
            continue
        total += 1
        if len({turn_player for _, turn_player in futures}) > 1:
            split += 1
        handover = [a for a, tp in futures if tp != seat]
        if handover:
            passing_total += 1
            assert all(a.kind.name == "END_PHASE" for a in handover), handover
            if len(legal.allowed) == 1:
                passing_alone += 1

    assert total > 500, total
    # 차례가 갈린 결정이 **하나도 없다.**
    assert split == 0, split
    # 차례를 넘기는 행위는 **언제나 유일한 후보**였다.
    assert passing_total > 0, passing_total
    assert passing_alone == passing_total, (passing_alone, passing_total)


@pytest.mark.real_card
def test_07_the_actor_is_the_turn_player_at_every_decision(repository):
    """
    **§9 — 결정 시점에는 ``viewer`` 가 곧 차례다.**

    ``Duel.to_act`` 는 "우선권을 쥔 사람, 없으면 턴 플레이어" 이고, 지금은
    응답 창이 열리는 자리가 없으므로(STRUCTURAL-34) 언제나 턴 플레이어다.

    그래서 평가는 **현재** 상태의 차례를 ``viewer`` 로 사실상 알고 있다.
    모르는 것은 **미래**의 차례다 — ``test_05`` 가 그 자리를 짚는다.
    """
    same = different = 0
    for duel, legal in decisions(repository):
        if legal.seat == duel.turn_player:
            same += 1
        else:
            different += 1
    assert same > 500, same
    assert different == 0, different


@pytest.mark.real_card
def test_08_neither_policy_reads_the_turn_to_prefer_acting(repository):
    """
    **§14 — 두 정책 모두 차례를 읽지 않는다. 관찰만 한다.**

    둘 다 "턴을 넘기기보다 행동한다" 를 선호하지만, **근거가 서로 다르고
    어느 쪽도 차례가 아니다.**

        RuleBased  ``EndThePhaseAsLastResort`` 가 ``END_PHASE`` 에 평평하게
                   0 을 주고, 소환 규칙이 양수를 준다 — **행동의 종류**로
                   가른다
        Search     판이 좋아지는 쪽이 이긴다 — 소환은 자원이 필드로 올라와
                   점수가 오르고, ``END_PHASE`` 는 판을 그대로 둔다

    누가 더 좋은지는 판단하지 않는다.
    """
    for path in ("agent/heuristic.py", "agent/search.py", "agent/policy.py"):
        names = source_names(path)
        assert "turn_player" not in names, path
        assert "is_my_turn" not in names, path
