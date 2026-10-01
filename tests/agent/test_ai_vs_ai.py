"""
Phase 3-D — AI vs AI / Search Validation.

    make_search()      ─┐
                        ├→ run_match(seed) → MatchResult
    make_rule_based()  ─┘

        DuelRunner (Phase 3-A, 그대로)
          ↓ view(0) / legal_actions(0)        ↓ view(1) / legal_actions(1)
        Policy P0                            Policy P1
          ↓ PlayerAction                       ↓ PlayerAction
                      Duel.apply() — 같은 엔진

이 파일이 증명하는 것
---------------------
**두 정책이 같은 엔진에서 서로 독립적으로 둔다.** 각자 자기 자리의 관측만
받고, 한쪽 관측이 다른 쪽에 넘어가지 않는다.

**탐색이 진짜 판을 바꾸지 않는다** — 양쪽이 동시에 탐색할 때도.

**같은 씨앗이면 같은 대국이다.** 수의 순서 · ``state_hash`` · 시뮬레이션
횟수까지 같다.

**승패로 우열을 말하지 않는다.** 지금 행동 공간에서는 승패가 정책과
무관하다 (Phase 3-B 측정). 그래서 이 파일은 승자를 **세기만** 한다.
"""

import dataclasses
import pathlib

import pytest

from agent.arena import (
    ArenaError,
    DecisionRecord,
    MatchOutcome,
    MatchResult,
    make_first_legal,
    make_random,
    make_rule_based,
    make_search,
    run_match,
    run_series,
    summarize,
)
from agent.evaluation import StateEvaluator
from agent.search import SearchPolicy
from agent.simulation import Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.vocabulary import Phase, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

# Phase 3-A / 3-B / 3-C 와 **같은 카드 풀** (§3 — 풀을 넓히지 않는다).
LUSTER_DRAGON = 11091375
BATTLE_OX = 5053103
KOJIKOCY = 1184620
THE_13TH_GRAVE = 32864
WHITE_DUSTON = 3557275
POT_OF_GREED = 55144522

DECK = (
    [LUSTER_DRAGON] * 3
    + [BATTLE_OX] * 3
    + [KOJIKOCY] * 3
    + [THE_13TH_GRAVE] * 3
    + [WHITE_DUSTON] * 3
    + [POT_OF_GREED] * 5
)
DECKS = (DECK, DECK)

#: §24 가 요구하는 씨앗 범위. 시험은 시간을 아끼려 8개를 쓰고, 1~16 전체는
#: 측정 스크립트가 돌린다 (문서 §6 에 결과가 있다).
SEEDS = (1, 2, 3, 4, 5, 6, 7, 8)


def match(seed: int, factories, **kwargs) -> MatchResult:
    return run_match(
        REPOSITORY, decks=DECKS, seed=seed, factories=factories, **kwargs
    )


REPOSITORY = None  # fixture 가 채운다


@pytest.fixture(autouse=True)
def _bind_repository(repository):
    """모듈 수준 헬퍼가 쓰도록 리포지토리를 묶는다."""
    global REPOSITORY
    REPOSITORY = repository
    yield
    REPOSITORY = None


def board_snapshot(duel: Duel) -> tuple:
    """Phase 3-C 와 **같은 mutation surface** 를 본다 (§6)."""
    return (
        duel.state.state_hash(),
        duel.state.randomness.draws,
        duel.state.turn.turn_number,
        duel.state.turn.phase,
        duel.step,
        duel.priority,
        duel.result,
        tuple(
            (
                duel.state.player(seat).life_points,
                tuple(
                    tuple(
                        card.instance_id.value
                        for card in duel.state.player(seat).zone(zone)
                    )
                    for zone in (
                        Zone.DECK,
                        Zone.HAND,
                        Zone.MZONE,
                        Zone.SZONE,
                        Zone.GRAVE,
                        Zone.REMOVED,
                    )
                ),
            )
            for seat in (MINE, THEIRS)
        ),
    )


# ======================================================================
# §20 Policy Pair — 세 조합이 실제로 돈다
# ======================================================================


@pytest.mark.real_card
def test_search_versus_rule_based(repository):
    result = match(7, (make_search(), make_rule_based()))

    assert result.outcome is MatchOutcome.COMPLETED
    assert result.refusals == 0
    assert result.winner is not None
    assert result.simulations > 0, "P0 가 탐색하지 않았습니다"
    assert result.names == ("search-p0", "rule-based-p1")


@pytest.mark.real_card
def test_rule_based_versus_search(repository):
    """**좌우를 뒤집는다.** 탐색이 후공 자리에서도 똑같이 돌아야 한다."""
    result = match(7, (make_rule_based(), make_search()))

    assert result.outcome is MatchOutcome.COMPLETED
    assert result.refusals == 0
    assert result.simulations > 0, "P1 이 탐색하지 않았습니다"
    searched = {record.seat for record in result.decisions if record.searched}
    assert searched == {THEIRS}, "탐색한 자리가 P1 하나여야 합니다"


@pytest.mark.real_card
def test_search_versus_search(repository):
    """
    **탐색 둘이 서로 둔다.** 양쪽이 각자 자기 자리를 내다본다.
    """
    result = match(7, (make_search(), make_search()))

    assert result.outcome is MatchOutcome.COMPLETED
    assert result.refusals == 0
    searched = {record.seat for record in result.decisions if record.searched}
    assert searched == {MINE, THEIRS}, "양쪽이 탐색해야 합니다"
    for seat in (MINE, THEIRS):
        assert sum(
            record.simulations or 0
            for record in result.decisions
            if record.seat == seat
        ) > 0


@pytest.mark.real_card
@pytest.mark.parametrize(
    "factories",
    [
        (make_search(), make_random(500)),
        (make_random(500), make_search()),
        (make_search(), make_first_legal()),
        (make_first_legal(), make_search()),
    ],
)
def test_search_coexists_with_the_other_policies(repository, factories):
    """§17 의 나머지 조합. 어느 쪽에 앉아도 끝까지 간다."""
    result = match(3, factories)

    assert result.outcome is MatchOutcome.COMPLETED
    assert result.refusals == 0
    assert result.simulations > 0


@pytest.mark.real_card
def test_a_malformed_matchup_is_refused(repository):
    with pytest.raises(ArenaError, match="자리마다 하나씩 둘"):
        match(1, (make_search(),))
    with pytest.raises(ArenaError, match="집계할 판이 없습니다"):
        summarize(())


# ======================================================================
# §20 Viewer — 관측 분리
# ======================================================================


class Watcher:
    """
    자기가 받은 관측을 **모아 둔다.** 고르는 것은 안쪽에 맡긴다.

    두 자리에 하나씩 앉혀 두면 "P0 가 받은 것" 과 "P1 이 받은 것" 을 나란히
    놓고 볼 수 있다.
    """

    def __init__(self, inner, name: str):
        self.inner = inner
        self.name = name
        self.seen: list[GameStateView] = []

    def decide(self, view, legal):
        self.seen.append(view)
        return self.inner.decide(view, legal)


@pytest.mark.real_card
def test_each_policy_sees_only_its_own_side(repository):
    """
    **관측이 자리마다 따로다.** 하나를 양쪽이 나눠 쓰지 않는다 (§5).

    P0 의 관측에서 P1 의 패가 보이지 않고, 그 반대도 같다. 그리고 두
    관측은 **같은 객체가 아니다.**
    """
    watchers: dict[int, Watcher] = {}

    def watched(build, label):
        def factory(duel, seat):
            watcher = Watcher(build(duel, seat), f"{label}-p{seat}")
            watchers[seat] = watcher
            return watcher

        return factory

    result = match(
        5,
        (
            watched(make_search(), "search"),
            watched(make_rule_based(), "rule-based"),
        ),
    )
    assert result.outcome is MatchOutcome.COMPLETED

    for seat, watcher in watchers.items():
        assert watcher.seen, f"P{seat} 가 관측을 받지 못했습니다"
        for view in watcher.seen:
            assert view.viewer == seat
            # 내 패는 보이고 상대 패는 장수만 보인다.
            assert all(card.is_identified for card in view.me.hand.occupied())
            assert view.opponent.hand.cards == ()
            assert view.me.deck.cards == ()
            assert view.opponent.deck.cards == ()

    # 두 자리가 **같은 객체를 돌려 쓰지 않는다.**
    shared = {id(view) for view in watchers[MINE].seen} & {
        id(view) for view in watchers[THEIRS].seen
    }
    assert shared == set(), "두 정책이 같은 관측 객체를 공유했습니다"


@pytest.mark.real_card
def test_no_policy_ever_receives_the_board(repository):
    """정책에게 가는 것은 관측이다 — ``Duel`` 도 ``GameState`` 도 아니다."""
    seen: list[object] = []

    def factory(duel, seat):
        class Spy:
            name = f"spy-p{seat}"

            def decide(self, view, legal):
                seen.append(view)
                return legal.allowed[0] if legal.allowed else None

        return Spy()

    match(2, (factory, factory))

    assert seen
    for view in seen:
        assert isinstance(view, GameStateView)
        assert not isinstance(view, Duel)
        for forbidden in ("draw", "move", "set_result", "apply", "state_hash"):
            assert not hasattr(view, forbidden), forbidden


# ======================================================================
# §20 Simulation — 원본 보호 · 사본 독립 · 실패 격리
# ======================================================================


@pytest.mark.real_card
def test_both_searches_leave_the_real_board_untouched(repository):
    """
    **양쪽이 동시에 탐색해도** 진짜 판은 그 수를 둔 것만 반영한다 (§6).

    결정마다 판을 찍어 두고, 탐색이 끝난 직후의 판이 **고르기 전과 같은지**
    확인한다. 적용은 그 뒤에 일어난다.
    """
    snapshots: list[tuple] = []

    def factory(duel, seat):
        inner = make_search()(duel, seat)

        class Checked:
            name = f"checked-p{seat}"

            def decide(self, view, legal):
                before = board_snapshot(duel)
                chosen = inner.decide(view, legal)
                snapshots.append((before, board_snapshot(duel)))
                return chosen

        return Checked()

    result = match(4, (factory, factory))

    assert result.outcome is MatchOutcome.COMPLETED
    assert len(snapshots) > 100
    for before, after in snapshots:
        assert before == after, "탐색이 진짜 판을 바꿨습니다"


@pytest.mark.real_card
def test_clone_independence_while_both_sides_search(repository):
    """
    한쪽의 사본이 다른 쪽의 관측에 닿지 않는다 (§10).

    P0 가 후보를 전부 해 본 **직후** P1 의 관측을 뜨면, P1 이 보는 것은
    P0 가 내다본 미래가 아니라 **지금의 판**이어야 한다.
    """
    duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=6)
    while duel.state.turn.phase is not Phase.MAIN1:
        if duel.advance() is not None:
            continue
        duel.apply(PlayerAction.end_phase(actor=duel.to_act))

    simulator = Simulator(duel)
    before_theirs = duel.view(THEIRS).canonical_state()
    futures = [
        simulator.simulate(action, viewer=MINE)
        for action in duel.legal_actions(MINE).allowed
    ]

    assert len(futures) >= 2
    assert len({f.future.canonical_state() for f in futures}) == len(futures)
    assert duel.view(THEIRS).canonical_state() == before_theirs


@pytest.mark.real_card
def test_a_simulation_that_fails_does_not_corrupt_the_real_game(repository):
    """
    시뮬레이션이 실패해도 **판은 그대로이고 대국은 계속된다** (§14 · §17).

    후보가 아닌 수를 해 보게 하고, 그 다음 대국이 정상적으로 끝나는지 본다.
    """
    duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=8)
    simulator = Simulator(duel)
    before = board_snapshot(duel)

    hand = list(duel.state.player(MINE).hand)
    bogus = PlayerAction.attack_directly(actor=MINE, source=hand[0].instance_id)
    failed = simulator.simulate(bogus, viewer=MINE)

    assert not failed.status.gives_a_future
    assert failed.future is None
    assert board_snapshot(duel) == before

    # 같은 시뮬레이터로 계속 쓸 수 있다.
    policy = SearchPolicy(simulator=simulator, evaluator=StateEvaluator())
    chosen = policy.decide(duel.view(MINE), duel.legal_actions(MINE))
    assert chosen in duel.legal_actions(MINE).allowed
    assert board_snapshot(duel) == before


# ======================================================================
# §20 RNG — 격리
# ======================================================================


@pytest.mark.real_card
def test_the_game_rng_never_moves_while_both_sides_search(repository):
    """
    대국 내내 **진짜 판의 난수 좌표가 탐색 때문에 움직이지 않는다** (§7).

    이번 엔진에서는 초기 셔플 뒤로 난수를 꺼내는 수가 없으므로, 좌표는
    처음 값에서 끝까지 **그대로여야** 한다. 탐색이 원본 난수원을 건드리면
    이 값이 올라간다.
    """
    draws: list[int] = []

    def factory(duel, seat):
        inner = make_search()(duel, seat)

        class Watched:
            name = f"rng-p{seat}"

            def decide(self, view, legal):
                chosen = inner.decide(view, legal)
                draws.append(duel.state.randomness.draws)
                return chosen

        return Watched()

    result = match(9, (factory, factory))

    assert result.outcome is MatchOutcome.COMPLETED
    assert draws
    assert len(set(draws)) == 1, f"탐색이 난수 좌표를 움직였습니다: {sorted(set(draws))}"


@pytest.mark.real_card
def test_search_on_and_search_off_leave_the_same_game(repository):
    """
    **같은 수를 두면 탐색을 했든 안 했든 완전히 같은 대국이다** (§7 Test A/B).

    비교군은 "탐색을 전부 돌린 뒤 결과를 버리고 첫 후보를 고르는" 정책이다.
    시뮬레이션을 수백 번 하고도 대국이 한 글자도 달라지지 않아야 한다.
    """
    off = match(11, (make_first_legal(), make_first_legal()))

    counted: list[int] = []

    def searches_then_picks_first(duel, seat):
        inner = make_search()(duel, seat)

        class Both:
            name = f"first-legal-p{seat}"  # 이름까지 같게 두어 비교를 쉽게 한다

            def decide(self, view, legal):
                if not legal.allowed:
                    return None
                inner.decide(view, legal)  # 부수 효과만 쓴다
                counted.append(inner.simulation_count())
                return legal.allowed[0]

        return Both()

    on = match(11, (searches_then_picks_first, searches_then_picks_first))

    assert counted and counted[-1] > 100, "탐색을 거의 하지 않으면 시험이 무의미하다"
    assert on.state_hash == off.state_hash
    assert on.winner == off.winner
    assert on.turns == off.turns
    assert on.actions == off.actions
    assert on.life_points == off.life_points
    assert [record.action for record in on.decisions] == [
        record.action for record in off.decisions
    ]


# ======================================================================
# §20 Determinism — 재현
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize(
    "factories",
    [
        (make_search(), make_rule_based()),
        (make_rule_based(), make_search()),
        (make_search(), make_search()),
        (make_search(), make_random(500)),
    ],
)
def test_the_same_seed_replays_exactly(repository, factories):
    """
    같은 씨앗 · 같은 설정이면 **같은 대국**이다 (§8).

    수의 순서 · ``state_hash`` · 턴 · 시뮬레이션 횟수 · 후보 수 · 점수까지
    같다 — ``canonical_state`` 가 그 전부를 담고 시간만 빼 둔다.
    """
    first = match(6, factories)
    second = match(6, factories)

    assert first.canonical_state() == second.canonical_state()
    assert first.state_hash == second.state_hash
    assert first.simulations == second.simulations


@pytest.mark.real_card
def test_different_seeds_give_different_games(repository):
    """재현이 "언제나 같다" 가 아니라는 것도 확인한다."""
    hashes = {
        match(seed, (make_search(), make_search())).state_hash
        for seed in (1, 2, 3, 4)
    }
    assert len(hashes) == 4


@pytest.mark.real_card
def test_the_timing_wrapper_does_not_change_the_game(repository):
    """
    아레나가 정책을 시간 재기용으로 감싸지만 **고른 것을 바꾸지 않는다.**

    감싸지 않은 경로(``play``)와 감싼 경로(``run_match``)가 같은 대국을
    만드는지 본다.
    """
    from agent import play, rule_based_policy, search_policy

    bare = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=12)
    transcript = play(bare, (search_policy(bare), rule_based_policy()))
    wrapped = match(12, (make_search(), make_rule_based()))

    assert bare.state.state_hash() == wrapped.state_hash
    assert [
        entry.action for entry in transcript.entries
    ] == [record.action for record in wrapped.decisions]


# ======================================================================
# §20 Decision — 고른 것은 언제나 합법이다
# ======================================================================


@pytest.mark.real_card
def test_every_chosen_action_was_legal_and_accepted(repository):
    """
    대국의 모든 수가 **엔진이 받아들인 수**다 (§14 · §26.5).

    아레나는 엔진을 우회하지 않는다 — 거절이 하나라도 있으면 결과가
    ``POLICY_REFUSED`` 로 적힌다.
    """
    for factories in (
        (make_search(), make_rule_based()),
        (make_search(), make_search()),
    ):
        result = match(13, factories)
        assert result.outcome is MatchOutcome.COMPLETED
        assert result.refusals == 0
        for record in result.decisions:
            assert record.accepted
            assert record.action is not None
            assert record.legal_count >= 1


@pytest.mark.real_card
def test_a_policy_that_returns_nothing_is_recorded_not_forced(repository):
    """
    정책이 ``None`` 을 돌려주면 **엔진을 우회해 강제 실행하지 않는다** (§14).

    거절로 적히고 대국은 거기서 멈춘다 — 승패로 바꾸지 않는다.
    """

    def sulks(duel, seat):
        class Sulks:
            name = f"sulks-p{seat}"

            def decide(self, view, legal):
                return None

        return Sulks()

    result = match(1, (sulks, make_rule_based()))

    assert result.outcome is MatchOutcome.POLICY_REFUSED
    assert result.refusals == 1
    assert result.winner is None, "거절이 승패가 되었습니다"
    assert not result.completed


@pytest.mark.real_card
def test_a_policy_that_returns_an_illegal_action_is_rejected(repository):
    """후보 밖의 수는 **적용되지 않는다.** 판도 바뀌지 않는다."""

    def rogue(duel, seat):
        class Rogue:
            name = f"rogue-p{seat}"

            def decide(self, view, legal):
                hand = view.me.hand.occupied()
                if hand:
                    return PlayerAction.attack_directly(
                        actor=seat, source=hand[0].instance_id
                    )
                return None

        return Rogue()

    result = match(1, (rogue, make_rule_based()))

    assert result.outcome is MatchOutcome.POLICY_REFUSED
    assert result.winner is None
    assert result.decisions[-1].action.kind is PlayerActionKind.ATTACK
    assert not result.decisions[-1].accepted


@pytest.mark.real_card
def test_an_exploding_policy_is_recorded_not_swallowed(repository):
    """
    정책이 터지면 **결과로 적는다.** 여러 판을 돌릴 때 나머지를 못 보게
    되는 것이 더 나쁘다 (§14).
    """

    def explodes(duel, seat):
        class Explodes:
            name = f"explodes-p{seat}"

            def decide(self, view, legal):
                raise ZeroDivisionError("시험용 폭발")

        return Explodes()

    result = match(1, (explodes, make_rule_based()))

    assert result.outcome is MatchOutcome.ERROR
    assert "ZeroDivisionError" in result.reason
    assert result.winner is None


@pytest.mark.real_card
def test_the_safety_budget_is_not_a_win(repository):
    """
    걸음 상한에 걸리면 ``GAME_LIMIT_REACHED`` 이고 **승자가 없다** (§15).

    상한은 무한 반복을 막는 장치이고 정상 종료를 **대체하지 않는다.**
    """
    result = match(1, (make_search(), make_rule_based()), max_steps=5)

    assert result.outcome is MatchOutcome.GAME_LIMIT_REACHED
    assert result.winner is None
    assert not result.completed
    assert "끝나지 않았습니다" in result.reason


# ======================================================================
# §20 Trace — 양쪽에 남고 가려진 정보는 없다
# ======================================================================


@pytest.mark.real_card
def test_the_decision_trace_is_the_same_shape_for_every_policy(repository):
    """
    **공통 결정 흔적**이 어느 정책에서든 남는다 (§12).

    자리 · 턴 · 페이즈 · 후보 수 · 고른 수 · 정책 이름은 전부 채워지고,
    탐색 쪽 네 칸은 탐색일 때만 채워진다 — 아니면 ``None`` 이다. 0 이
    아니다.
    """
    result = match(7, (make_search(), make_rule_based()))

    assert result.decisions
    for record in result.decisions:
        assert record.seat in (MINE, THEIRS)
        assert record.policy
        assert record.turn_number >= 1
        assert isinstance(record.phase, Phase)
        assert record.legal_count >= 1
        assert record.describe_ko()

    searched = [r for r in result.decisions if r.seat == MINE]
    plain = [r for r in result.decisions if r.seat == THEIRS]
    assert all(r.searched for r in searched)
    assert all(not r.searched for r in plain)
    for record in plain:
        assert record.candidate_count is None
        assert record.simulations is None
        assert record.score is None


@pytest.mark.real_card
def test_the_search_trace_lines_up_with_the_actions_that_were_played(repository):
    """
    **점수가 엉뚱한 수에 붙지 않는다.**

    아레나는 "자리 ``s`` 의 ``n`` 번째 걸음 = 그 정책의 ``n`` 번째 결정" 이라는
    대응을 쓴다. 그 대응을 가정하지 않고 확인한다 — 탐색 흔적이 고른 수와
    실제로 둔 수가 같은지 맞춰 본다.
    """
    policies: dict[int, SearchPolicy] = {}

    def factory(duel, seat):
        built = make_search()(duel, seat)
        policies[seat] = built
        return built

    result = match(7, (factory, make_rule_based()))

    trace = policies[MINE].decisions
    played = [record for record in result.decisions if record.seat == MINE]
    assert len(trace) == len(played)
    for decision, record in zip(trace, played):
        assert decision.chosen == record.action
        assert len(decision.candidates) == record.candidate_count
        assert decision.simulations == record.simulations
        assert decision.turn_number == record.turn_number
        assert decision.phase is record.phase


@pytest.mark.real_card
def test_no_trace_record_holds_hidden_information(repository):
    """
    흔적에 **판도 관측도 상대 카드도** 없다 (§11).

    남는 것은 자리표 · 수 · 점수뿐이다. ``state_hash`` 는 되돌려 읽을 수
    없는 요약이므로 탐색 흔적에만 남는다.
    """
    result = match(7, (make_search(), make_search()))

    for record in result.decisions:
        for field in dataclasses.fields(record):
            value = getattr(record, field.name)
            assert not isinstance(value, (GameStateView, Duel)), field.name
            assert not isinstance(value, Simulator), field.name
    names = {field.name for field in dataclasses.fields(DecisionRecord)}
    assert "state" not in names
    assert "future" not in names
    assert "view" not in names

    # MatchResult 자체에도 판이 없다 — 지문과 LP 숫자만 있다.
    for field in dataclasses.fields(MatchResult):
        value = getattr(result, field.name)
        assert not isinstance(value, (Duel, GameStateView))


# ======================================================================
# §20 Runner — 여러 씨앗 · 집계
# ======================================================================


@pytest.mark.real_card
def test_a_whole_series_completes_on_every_seed(repository):
    """§24: 세 조합 × 씨앗 1~8 이 전부 완주하고 거절도 예외도 없다."""
    for factories in (
        (make_search(), make_rule_based()),
        (make_rule_based(), make_search()),
        (make_search(), make_search()),
    ):
        results = run_series(
            repository, decks=DECKS, seeds=SEEDS, factories=factories
        )
        summary = summarize(results)

        assert summary.games == len(SEEDS)
        assert summary.all_completed, summary.describe_ko()
        assert summary.refusals == 0
        assert summary.errors == 0
        assert summary.limits == 0
        assert summary.simulations > 0
        assert summary.draws == 0, "승패가 정해지지 않은 판이 있습니다"
        assert max(result.longest_repeat for result in results) <= 2


@pytest.mark.real_card
def test_the_summary_counts_wins_without_calling_them_strength(repository):
    """
    집계는 승수를 **센다.** 그것이 강함이라고 말하지 않는다 (§18).

    여기서 확인하는 것은 숫자의 일관성이다 — 승수의 합과 무승부 수가
    판 수와 맞아야 한다.
    """
    results = run_series(
        repository, decks=DECKS, seeds=SEEDS, factories=(make_search(), make_rule_based())
    )
    summary = summarize(results)

    assert sum(summary.wins) + summary.draws == summary.games
    assert summary.average_turns > 1
    assert summary.simulations_per_decision > 0
    assert summary.average_decision_ms > 0
    assert summary.max_decision_ms >= summary.average_decision_ms


@pytest.mark.real_card
def test_swapping_sides_does_not_change_whether_the_game_finishes(repository):
    """
    §9: 좌우를 뒤집어도 완주한다. **승자가 누구인지는 결론에 쓰지 않는다.**
    """
    forward = summarize(
        run_series(
            repository, decks=DECKS, seeds=SEEDS,
            factories=(make_search(), make_rule_based()),
        )
    )
    reversed_sides = summarize(
        run_series(
            repository, decks=DECKS, seeds=SEEDS,
            factories=(make_rule_based(), make_search()),
        )
    )

    assert forward.all_completed and reversed_sides.all_completed
    assert forward.refusals == reversed_sides.refusals == 0
    assert forward.simulations > 0 and reversed_sides.simulations > 0


@pytest.mark.real_card
def test_a_policy_object_is_built_fresh_for_every_match(repository):
    """
    §40 (3-C) 의 연장: 판마다 정책이 새로 생기므로 지난 판이 남지 않는다.

    공장이 매번 새 객체를 만드는지 세어 본다.
    """
    built: list[int] = []

    def factory(duel, seat):
        policy = make_search()(duel, seat)
        built.append(id(policy))
        return policy

    for seed in (1, 2, 3):
        match(seed, (factory, make_rule_based()))

    assert len(built) == 3
    assert len(set(built)) == 3, "같은 정책 객체가 두 판에 쓰였습니다"
