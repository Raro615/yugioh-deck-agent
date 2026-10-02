"""
Phase 3-C — Search / Simulation AI.

    Observation + LegalActions
            ↓  후보마다
    Simulator.simulate(후보)        사본에 **진짜 엔진**을 적용
            ↓
    GameStateView(viewer)          넘어가는 것은 관측뿐이다
            ↓
    StateEvaluator → StateValue
            ↓  비교 (등급 먼저, 그 다음 휴리스틱)
        PlayerAction

이 파일이 지키는 것
-------------------
**SEARCH MUST NEVER CHANGE THE REAL GAME.** 탐색 뒤 ``state_hash`` ·
난수원의 ``draws`` · 턴 · 페이즈 · LP · 패 · 필드 · 덱이 그대로다.

**사본끼리 독립이다.** 후보 A 를 해 본 결과가 후보 B 에 닿지 않는다.

**난수원이 섞이지 않는다.** 시뮬레이션에서 난수를 꺼내도 진짜 판의 좌표가
움직이지 않는다. ``project()`` 는 반대로 움직이므로 탐색이 쓰지 않는다.

**가려진 정보가 새지 않는다.** 미래 관측은 ``viewer`` 의 눈이고, 흔적에는
판도 관측도 남지 않는다.

**후보를 만들어 내지 않는다.** 탐색하는 것은 ``legal.allowed`` 뿐이다 —
``ATTACK`` 은 지금 후보에 없으므로 탐색도 하지 않는다.

**모르는 것을 최악으로 바꾸지 않는다.** ``UNKNOWN`` 은 0 점도 패배도
아니고 **점수가 없는 것**이다.
"""

import ast
import collections
import dataclasses
import pathlib
import time

import pytest

from agent import (
    FirstLegalPolicy,
    RandomPolicy,
    play,
    rule_based_policy,
)
from agent.evaluation import (
    ATK_IN_LP,
    DECK_CARD_IN_LP,
    HAND_CARD_IN_LP,
    MONSTER_IN_LP,
    SPELL_TRAP_IN_LP,
    EvaluationError,
    ExclusionCategory,
    StateEvaluator,
    StateValue,
    Terminal,
    _zone_attack,
)
from agent.search import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_SIMULATIONS,
    SKIPPED_BY_BUDGET,
    SUPPORTED_DEPTH,
    SearchCandidate,
    SearchDecision,
    SearchError,
    SearchPolicy,
    search_policy,
)
from agent.simulation import (
    SimulationError,
    SimulationResult,
    SimulationStatus,
    Simulator,
)
from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel, LegalActions
from engine.game_state_view import CardDefinitionView, CardView, GameStateView
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

# Phase 3-A / 3-B 가 쓴 **같은 카드 풀**을 다시 쓴다 (§43).
LUSTER_DRAGON = 11091375  # ATK 1900 / DEF 1600 / 레벨 4
BATTLE_OX = 5053103  # ATK 1700 / DEF 1000 / 레벨 4
KOJIKOCY = 1184620  # ATK 1500 / DEF 1200 / 레벨 4
THE_13TH_GRAVE = 32864  # ATK 1200 / DEF  900 / 레벨 3
WHITE_DUSTON = 3557275  # ATK    0 / DEF 1000 / 레벨 1
POT_OF_GREED = 55144522
KING_OF_THE_SKULL_SERVANTS = 36021814  # ATK ?

TEST_DECK = (
    [LUSTER_DRAGON] * 3
    + [BATTLE_OX] * 3
    + [KOJIKOCY] * 3
    + [THE_13TH_GRAVE] * 3
    + [WHITE_DUSTON] * 3
    + [POT_OF_GREED] * 5
)


def duel_with(repository, *, seed: int = 7, deck=None) -> Duel:
    deck = TEST_DECK if deck is None else deck
    return Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)


def to_main_phase(duel: Duel) -> None:
    """메인 페이즈 1 까지 진행한다 — 후보가 둘 이상 생기는 유일한 자리다."""
    while duel.state.turn.phase is not Phase.MAIN1:
        if duel.advance() is not None:
            continue
        duel.apply(PlayerAction.end_phase(actor=duel.to_act))


def board_snapshot(duel: Duel) -> tuple:
    """
    탐색 전후로 **같아야 하는 것들** 전부 (§11).

    ``state_hash`` 만 보면 해시가 보지 않는 것을 놓친다. 그래서 턴 · 페이즈 ·
    LP · 각 존의 장수와 덱 순서를 따로 적는다.
    """
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
                    card.instance_id.value
                    for card in duel.state.player(seat).zone(Zone.DECK)
                ),
                tuple(
                    card.instance_id.value
                    for card in duel.state.player(seat).zone(Zone.HAND)
                ),
                tuple(
                    card.instance_id.value
                    for card in duel.state.player(seat).zone(Zone.MZONE)
                ),
                tuple(
                    card.instance_id.value
                    for card in duel.state.player(seat).zone(Zone.GRAVE)
                ),
                tuple(
                    card.instance_id.value
                    for card in duel.state.player(seat).zone(Zone.REMOVED)
                ),
            )
            for seat in (MINE, THEIRS)
        ),
    )


class SearchesThenPicksFirst:
    """
    탐색을 **전부 돌린 뒤 결과를 버리고** 첫 후보를 고른다.

    §14 의 비교군이다. 이 정책으로 돌린 듀얼은 ``FirstLegalPolicy`` 로 돌린
    듀얼과 **완전히 같아야** 한다 — 시뮬레이션을 100 번 넘게 했는데도.
    """

    name = "searches-then-first"

    def __init__(self, duel: Duel):
        self._search = search_policy(duel)

    @property
    def simulations(self) -> int:
        return self._search.simulation_count()

    def decide(self, view, legal):
        if not legal.allowed:
            return None
        self._search.decide(view, legal)  # 부수 효과만 쓴다
        return legal.allowed[0]


class AlwaysUnknown(Simulator):
    """
    무엇을 물어도 ``UNKNOWN`` 으로 답하는 시뮬레이터. **시험용이다.**

    진짜 듀얼을 들고 있으므로 ``state_hash`` · 턴 · 페이즈는 사실이다.
    이것이 필요한 이유: 지금 엔진에서 **허가된 후보는 모두 실행되므로**
    ``UNKNOWN`` 시뮬레이션이 실제 듀얼에서 일어나지 않는다. 일어나지 않는
    길을 시험하지 않으면, 일어났을 때 조용히 틀린다.
    """

    def simulate(self, action, *, viewer):
        self.simulations += 1
        return SimulationResult(
            action=action,
            status=SimulationStatus.UNKNOWN,
            viewer=viewer,
            reason="아직 구현하지 않은 규칙입니다 (시험용).",
        )


# ======================================================================
# Test 1 · 22 · 26 — 조립과 설정
# ======================================================================


@pytest.mark.real_card
def test_01_search_policy_construction(repository):
    duel = duel_with(repository)
    policy = search_policy(duel)

    assert policy.name == "search"
    assert policy.depth == SUPPORTED_DEPTH == 1
    assert policy.max_candidates == DEFAULT_MAX_CANDIDATES
    assert policy.max_simulations == DEFAULT_MAX_SIMULATIONS
    assert isinstance(policy.simulator, Simulator)
    assert isinstance(policy.evaluator, StateEvaluator)
    assert policy.decisions == []


def test_01b_a_policy_without_a_simulator_refuses_to_decide():
    """
    **붙지 않은 탐색 정책은 조용히 다른 방법으로 고르지 않는다.**

    고르면 "탐색했다" 고 믿는 결정이 실은 탐색이 아니게 된다.
    """
    policy = SearchPolicy()
    with pytest.raises(SearchError, match="붙지 않은 탐색 정책"):
        policy.decide(None, LegalActions(MINE, (PlayerAction.end_phase(actor=MINE),)))


def test_22_search_depth_configuration():
    """
    공식 지원 깊이는 **1 뿐이다** (§5 · §9 · §35).

    2 를 받아 두고 1 처럼 도는 것은 "지원한다" 는 거짓말이다.
    """
    assert SUPPORTED_DEPTH == 1
    assert SearchPolicy(depth=1).depth == 1
    for depth in (0, 2, 3, -1):
        with pytest.raises(SearchError, match="지원하는 깊이"):
            SearchPolicy(depth=depth)


def test_22b_a_broken_budget_or_evaluator_is_refused():
    for bad in (0, -1, 1.5, True):
        with pytest.raises(SearchError, match="1 이상의 정수"):
            SearchPolicy(max_candidates=bad)
        with pytest.raises(SearchError, match="1 이상의 정수"):
            SearchPolicy(max_simulations=bad)

    class NotAnEvaluator:
        name = "not-an-evaluator"

    with pytest.raises(SearchError, match="evaluate 가 없습니다"):
        SearchPolicy(evaluator=NotAnEvaluator())
    with pytest.raises(SearchError, match="Simulator 가 필요합니다"):
        SearchPolicy(simulator=object())


# ======================================================================
# Test 2 · 3 · 4 · 5 — 후보와 깊이 1
# ======================================================================


@pytest.mark.real_card
def test_02_empty_legal_actions(repository):
    """고를 것이 없으면 ``None`` 이고, 그것도 흔적에 남는다."""
    duel = duel_with(repository)
    policy = search_policy(duel)

    assert policy.decide(duel.view(MINE), LegalActions(MINE, ())) is None
    decision = policy.last_decision
    assert decision.chosen is None
    assert decision.candidates == ()
    assert decision.simulations == 0
    assert not decision.nothing_was_comparable


@pytest.mark.real_card
def test_03_single_candidate(repository):
    """후보가 하나면 그것을 고른다. 그래도 **해 보고** 고른다."""
    duel = duel_with(repository)
    policy = search_policy(duel)
    only = PlayerAction.end_phase(actor=MINE)

    chosen = policy.decide(duel.view(MINE), LegalActions(MINE, (only,)))

    assert chosen == only
    decision = policy.last_decision
    assert decision.simulations == 1
    assert len(decision.candidates) == 1
    assert decision.candidates[0].status is SimulationStatus.SUPPORTED
    assert decision.candidates[0].comparable


@pytest.mark.real_card
def test_04_multiple_candidate_evaluation(repository):
    """
    후보마다 **따로** 해 보고 따로 점수를 낸다.

    모든 후보에 점수가 붙고, 고른 것이 가장 높다.
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    legal = duel.legal_actions(MINE)
    assert len(legal.allowed) >= 3, "후보가 셋 이상인 자리가 필요합니다"

    policy = search_policy(duel)
    chosen = policy.decide(duel.view(MINE), legal)
    decision = policy.last_decision

    assert decision.simulations == len(legal.allowed)
    assert len(decision.candidates) == len(legal.allowed)
    assert all(candidate.comparable for candidate in decision.candidates)
    best = decision.of(chosen)
    assert best.value.ordering_key() == max(
        candidate.value.ordering_key() for candidate in decision.candidates
    )
    # 후보마다 점수가 다르다 — 미래가 실제로 달라졌다는 뜻이다.
    assert len({c.value.heuristic for c in decision.candidates}) > 1


@pytest.mark.real_card
def test_05_depth_one_search_looks_exactly_one_move_ahead(repository):
    """
    **한 수만 본다.** 후보 수와 포크 수와 시뮬레이션 수가 같다.

    더 깊이 봤다면 포크가 후보보다 많아진다.
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    legal = duel.legal_actions(MINE)
    policy = search_policy(duel)

    policy.decide(duel.view(MINE), legal)

    assert policy.simulator.simulations == len(legal.allowed)
    assert policy.simulator._forks == len(legal.allowed)


@pytest.mark.real_card
def test_05b_the_future_really_is_one_move_later(repository):
    """
    내다본 미래가 **그 수를 둔 뒤의 판**과 같다 — 가짜 실행기가 아니다 (§15).

    같은 수를 진짜 듀얼에 적용한 뒤의 관측과 시뮬레이션의 관측을 맞춰 본다.
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    legal = duel.legal_actions(MINE)
    action = next(
        a for a in legal.allowed if a.kind is PlayerActionKind.NORMAL_SUMMON
    )

    simulated = Simulator(duel).simulate(action, viewer=MINE)
    assert simulated.status is SimulationStatus.SUPPORTED

    # 이제 진짜로 둔다.
    assert duel.apply(action).accepted
    assert simulated.future.canonical_state() == duel.view(MINE).canonical_state()


# ======================================================================
# Test 6 · 7 — 끝난 판이 휴리스틱을 앞선다
# ======================================================================


@pytest.mark.real_card
def test_06_terminal_win_is_read_from_a_real_simulation(repository):
    """
    **진짜 시뮬레이션이 승리를 읽는다.**

    상대 LP 를 0 으로 만들어 두면(시험용 준비) 어떤 수를 두어도 엔진의
    ``_check_end`` 가 상대의 패배를 선언한다. 그 미래를 내다본 평가는
    ``WIN`` 이고 휴리스틱을 아예 재지 않는다.

    그리고 **진짜 판은 끝나지 않는다** — 탐색이 승리를 보았을 뿐이다.
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    duel.state.player(THEIRS).change_life(-duel.state.player(THEIRS).life_points)

    policy = search_policy(duel)
    before = board_snapshot(duel)
    policy.decide(duel.view(MINE), duel.legal_actions(MINE))

    decision = policy.last_decision
    assert decision.candidates
    for candidate in decision.candidates:
        assert candidate.value.terminal is Terminal.WIN
        assert candidate.value.heuristic == 0, "끝난 판에서는 자원을 세지 않는다"
    assert not duel.is_over, "탐색이 진짜 판을 끝냈습니다"
    assert board_snapshot(duel) == before


@pytest.mark.real_card
def test_07_terminal_loss_is_read_from_a_real_simulation(repository):
    duel = duel_with(repository)
    to_main_phase(duel)
    duel.state.player(MINE).change_life(-duel.state.player(MINE).life_points)

    policy = search_policy(duel)
    policy.decide(duel.view(MINE), duel.legal_actions(MINE))

    for candidate in policy.last_decision.candidates:
        assert candidate.value.terminal is Terminal.LOSS
    assert not duel.is_over


def test_06b_a_win_outranks_every_heuristic_and_a_loss_loses_to_all():
    """
    **승리는 어떤 휴리스틱보다 앞서고 패배는 어떤 휴리스틱보다 뒤다.**

    승리를 "매우 큰 수" 로 적지 않은 이유가 이것이다 — 큰 수는 휴리스틱이
    자라면 추월당하지만 등급은 추월당하지 않는다.

    후보 하나는 끝나고 하나는 진행 중인 경우가 **지금 엔진에서는 일어나지
    않는다** (엔진이 모든 수 뒤에 ``_check_end`` 를 돌리므로 한 지점의
    후보는 전부 끝나거나 전부 진행 중이다). 그래서 비교 자체를 시험한다.
    """
    huge = 10**12
    win = SearchCandidate(
        action=PlayerAction.end_phase(actor=MINE),
        status=SimulationStatus.SUPPORTED,
        value=StateValue(terminal=Terminal.WIN, heuristic=-huge),
    )
    ongoing = SearchCandidate(
        action=PlayerAction.passing(actor=MINE),
        status=SimulationStatus.SUPPORTED,
        value=StateValue(terminal=Terminal.ONGOING, heuristic=huge),
    )
    draw = SearchCandidate(
        action=PlayerAction.normal_summon(actor=MINE, source=None),
        status=SimulationStatus.SUPPORTED,
        value=StateValue(terminal=Terminal.DRAW, heuristic=huge),
    )
    loss = SearchCandidate(
        action=PlayerAction.change_phase(actor=MINE, phase=Phase.END),
        status=SimulationStatus.SUPPORTED,
        value=StateValue(terminal=Terminal.LOSS, heuristic=huge),
    )

    ranked = sorted((loss, draw, ongoing, win), key=lambda c: c.ordering_key())
    assert [c.value.terminal for c in ranked] == [
        Terminal.WIN,
        Terminal.ONGOING,
        Terminal.DRAW,
        Terminal.LOSS,
    ]


# ======================================================================
# Test 8 · 9 · 10 · 11 — 평가의 항들
# ======================================================================


@pytest.mark.real_card
def test_08_lp_evaluation(repository):
    """LP 차이가 **1:1 로** 들어간다. 단위가 LP 이기 때문이다."""
    duel = duel_with(repository)
    evaluator = StateEvaluator()
    before = evaluator.evaluate(duel.view(MINE))
    assert dict(before.terms)["lp"] == 0

    duel.state.player(THEIRS).change_life(-1200)
    after = evaluator.evaluate(duel.view(MINE))

    assert dict(after.terms)["lp"] == 1200
    assert after.heuristic - before.heuristic == 1200
    # 상대 관점에서는 정확히 반대다.
    assert dict(evaluator.evaluate(duel.view(THEIRS)).terms)["lp"] == -1200


@pytest.mark.real_card
def test_09_field_evaluation(repository):
    """
    몬스터 한 마리가 늘면 ``monsters`` 와 ``atk`` 가 함께 움직인다.

    공격력은 1:1, 몬스터 한 마리는 :data:`MONSTER_IN_LP` 다.
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    evaluator = StateEvaluator()
    before = evaluator.evaluate(duel.view(MINE))

    action = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
    )
    summoned = duel.view(MINE).find(action.source).definition
    result = Simulator(duel).simulate(action, viewer=MINE)
    after = evaluator.evaluate(result.future)

    assert dict(after.terms)["monsters"] - dict(before.terms)["monsters"] == (
        MONSTER_IN_LP
    )
    assert dict(after.terms)["atk"] - dict(before.terms)["atk"] == (
        summoned.atk * ATK_IN_LP
    )
    assert dict(after.terms)["spells"] == 0


@pytest.mark.real_card
def test_10_hand_and_resource_evaluation(repository):
    """
    손에서 한 장이 나가면 ``hand`` 가 :data:`HAND_CARD_IN_LP` 만큼 줄고,
    덱 장수는 :data:`DECK_CARD_IN_LP` 로 센다.

    덱이 패보다 무거운 이유는 **지금 도달 가능한 패배 조건이 덱아웃
    하나**이기 때문이다 (Phase 3-B 측정).
    """
    assert DECK_CARD_IN_LP > HAND_CARD_IN_LP

    duel = duel_with(repository)
    to_main_phase(duel)
    evaluator = StateEvaluator()
    before = evaluator.evaluate(duel.view(MINE))

    action = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
    )
    after = evaluator.evaluate(
        Simulator(duel).simulate(action, viewer=MINE).future
    )

    assert dict(before.terms)["hand"] - dict(after.terms)["hand"] == HAND_CARD_IN_LP
    assert dict(after.terms)["deck"] == 0, "양쪽 덱 장수가 같다"

    # 덱 장수가 한쪽으로 기울면 그만큼 들어온다.
    duel.state.draw(THEIRS, 2)
    tilted = evaluator.evaluate(duel.view(MINE))
    assert dict(tilted.terms)["deck"] == 2 * DECK_CARD_IN_LP


@pytest.mark.real_card
def test_11_side_to_move_evaluation(repository):
    """
    **같은 평가자가 두 자리에서 각자의 관점으로 돈다** (§23).

    공유 자원 항(LP · 공격력 · 몬스터 · 마법 · 덱)은 자리를 바꾸면 부호가
    뒤집힌다. ``hand`` 는 **뒤집히지 않는다** — 내 패만 세기 때문이고
    (상대 패의 값은 알 수 없다, §26), 그것이 의도다.
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    duel.state.player(THEIRS).change_life(-900)
    duel.apply(
        next(
            a
            for a in duel.legal_actions(MINE).allowed
            if a.kind is PlayerActionKind.NORMAL_SUMMON
        )
    )
    evaluator = StateEvaluator()
    mine = dict(evaluator.evaluate(duel.view(MINE)).terms)
    theirs = dict(evaluator.evaluate(duel.view(THEIRS)).terms)

    for term in ("lp", "atk", "monsters", "spells", "deck"):
        assert mine[term] == -theirs[term], term
    assert mine["lp"] > 0 and mine["monsters"] > 0
    assert mine["hand"] > 0 and theirs["hand"] > 0


def test_11b_the_evaluator_refuses_anything_that_is_not_an_observation():
    """
    평가자는 **관측만** 받는다. 판을 받으면 거부한다 (§18).
    """
    for wrong in (None, object(), {"me": 1}):
        with pytest.raises(EvaluationError, match="관측이 필요합니다"):
            StateEvaluator().evaluate(wrong)


# ======================================================================
# Test 12 — UNKNOWN 안전
# ======================================================================


@pytest.mark.real_card
def test_12_an_unknown_attack_is_excluded_not_counted_as_zero(repository):
    """
    공격력이 ``?`` 인 몬스터는 **합에서 빠지고 기록에 남는다** (§20 · §28).

    0 으로 넣으면 "약하다" 가 거짓이 되고 큰 수로 넣으면 "강하다" 가
    거짓이 된다. 카드와 정의는 실제 그대로이고, 필드에 세우는 부분만
    시험이 만든다 — 이 카드는 효과 몬스터라서 엔진이 소환 후보로 내놓지
    않기 때문이다 (Phase 3-B 측정).
    """
    card = repository.get(KING_OF_THE_SKULL_SERVANTS)
    definition = CardDefinitionView.of(card)
    assert definition.atk_is_question, "전제: 이 카드의 공격력은 ? 다"

    unknown = CardView(
        instance_id=None,
        card_id=card.id,
        zone=Zone.MZONE,
        sequence=0,
        controller=MINE,
        face_up=True,
        position=Position.FACEUP_ATTACK,
        definition=definition,
    )
    known = dataclasses.replace(
        unknown,
        sequence=1,
        card_id=LUSTER_DRAGON,
        definition=CardDefinitionView.of(repository.get(LUSTER_DRAGON)),
    )

    zone = dataclasses.replace(
        duel_with(repository).view(MINE).me.monster_zone,
        cards=(unknown, known, None, None, None),
        size=2,
    )
    # 반환값이 Phase 3-E-6 에서 셋, 3-E-8 에서 넷으로 갈라졌다 — 세지 못한
    # 이유가 서로 다른 범주로 가기 때문이다. 이 시험의 두 카드는 둘 다
    # **앞면이고 정의가 읽히므로** hidden 과 not_attacking 은 0 이고, 아래
    # 주장은 하나도 바뀌지 않았다. 바뀐 것은 **더 정확해진 것뿐**이다:
    # 예전에는 "unknown 1" 이었던 것이 이제 "정의는 읽히는데 숫자가 없다
    # (indeterminate)" 라고 말한다.
    counted = _zone_attack(zone)
    assert counted.not_attacking == 0, "앞면 카드는 세지 않는 쪽으로 가지 않는다"
    assert counted.hidden == 0, "정의가 읽히는 카드는 가려진 쪽으로 가지 않는다"

    assert counted.indeterminate == 1
    assert counted.total == 1900, "모르는 공격력이 0 으로 더해지지 않았다"


@pytest.mark.real_card
def test_12b_an_unknown_simulation_has_no_score_and_is_not_the_worst(repository):
    """
    ``UNKNOWN`` 으로 끝난 후보는 **점수가 없다.** 0 점도 패배도 아니다.

    점수 있는 후보가 하나도 없으면 고르기는 하지만 **내다봤다고 말하지
    않는다.**
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    legal = duel.legal_actions(MINE)
    policy = SearchPolicy(simulator=AlwaysUnknown(duel))

    chosen = policy.decide(duel.view(MINE), legal)
    decision = policy.last_decision

    assert chosen in legal.allowed
    assert decision.nothing_was_comparable
    assert decision.comparable_count == 0
    assert "견줄 수 있는 후보가 없었습니다" in decision.reason
    for candidate in decision.candidates:
        assert candidate.status is SimulationStatus.UNKNOWN
        assert candidate.value is None, "UNKNOWN 이 점수로 바뀌었습니다"


@pytest.mark.real_card
def test_12c_every_real_evaluation_records_the_opponent_hand_as_withheld(
    repository,
):
    """
    실제 듀얼의 모든 평가는 상대 패를 **기록한다** — 값을 모르므로.

    빠진 것을 기록하지 않으면 "다 재었다" 는 거짓이 된다. 그 주장은 그대로다.

    **``partial`` 주장만 뒤집혔다** (Phase 3-E-8). 이 시험은 "상대 패를
    모르므로 모든 평가가 **부분 평가**다" 라고 적고 있었는데, 그 전제가
    틀렸다: 상대 패의 내용은 **관측 경계 밖**이고, 그것을 모르는 것은 평가가
    아직 못 푼 것이 아니라 **규칙대로 처리한 결과**다. 어떤 평가자도 이보다
    잘할 수 없는데 "부분 평가" 라고 적으면 그 깃발은 영원히 참이 되고, 실제로
    실측 99.6% 가 참이었다 (STRUCTURAL-130).

    지금 ``partial`` 은 ``UNKNOWN`` — **보이는데 숫자가 안 나오는 것** — 만
    본다. 상대 패는 ``WITHHELD`` 이므로 ``partial`` 을 참으로 만들지 않는다.
    기록은 그대로 남는다.
    """
    duel = duel_with(repository)
    value = StateEvaluator().evaluate(duel.view(MINE))

    assert any("상대 패" in note for note in value.notes)
    assert "hand" in dict(value.terms)

    # 기록은 남는다 — 사라진 것이 아니라 범주가 붙었다.
    withheld = value.of_category(ExclusionCategory.WITHHELD)
    assert any("상대 패" in item.note for item in withheld), value.excluded
    # 그리고 그것은 "평가가 못 푼 것" 이 아니다.
    assert not value.partial
    assert value.of_category(ExclusionCategory.UNKNOWN) == ()


# ======================================================================
# Test 13 — 결정론
# ======================================================================


@pytest.mark.real_card
def test_13_deterministic_tie_breaking(repository):
    """
    점수가 **완전히 같은** 후보가 있어도 흔들리지 않는다.

    같은 카드 두 장은 같은 미래를 만든다. 그때는
    ``canonical_state`` 가 작은 쪽이다 — 목록 순서에 기대지 않는다.
    """
    duel = duel_with(repository, seed=4, deck=[LUSTER_DRAGON] * 20)
    to_main_phase(duel)
    legal = duel.legal_actions(MINE)
    summons = tuple(
        a for a in legal.allowed if a.kind is PlayerActionKind.NORMAL_SUMMON
    )
    assert len(summons) >= 2

    policy = search_policy(duel)
    forward = policy.decide(duel.view(MINE), LegalActions(MINE, summons))
    scores = {c.value.ordering_key() for c in policy.last_decision.candidates}
    assert len(scores) == 1, "같은 카드인데 미래가 다릅니다"

    backward = search_policy(duel).decide(
        duel.view(MINE), LegalActions(MINE, tuple(reversed(summons)))
    )
    assert forward == backward
    assert forward.canonical_state() == min(a.canonical_state() for a in summons)


@pytest.mark.real_card
def test_13b_the_same_board_always_gives_the_same_move(repository):
    """난수가 없으므로 같은 관측과 같은 후보면 언제나 같은 수다 (§41)."""
    duel = duel_with(repository)
    to_main_phase(duel)
    view, legal = duel.view(MINE), duel.legal_actions(MINE)

    first = search_policy(duel).decide(view, legal)
    for _ in range(5):
        assert search_policy(duel).decide(view, legal) == first
    # 흔적이 쌓여도 선택이 흔들리지 않는다 (§38 · §40).
    policy = search_policy(duel)
    for _ in range(4):
        assert policy.decide(view, legal) == first
    assert len(policy.decisions) == 4


# ======================================================================
# Test 14 · 15 · 16 · 17 — 안전
# ======================================================================


@pytest.mark.real_card
def test_14_the_original_state_is_unchanged(repository):
    """
    **가장 중요한 시험이다.** 탐색이 끝난 뒤 진짜 판이 글자 하나 다르지 않다.

    ``state_hash`` 만 보지 않는다 — 해시가 보지 않는 턴 · 페이즈 · 우선권 ·
    난수 좌표 · 덱 순서까지 함께 본다 (§11).
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    before = board_snapshot(duel)

    policy = search_policy(duel)
    policy.decide(duel.view(MINE), duel.legal_actions(MINE))

    assert policy.simulator.simulations >= 2
    assert board_snapshot(duel) == before


@pytest.mark.real_card
def test_15_clone_independence(repository):
    """
    사본끼리 서로 닿지 않고, 원본에도 닿지 않는다 (§12 · §30).

    서로 다른 수를 서로 다른 사본에 두면 **세 개의 판**이 따로 존재한다.
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    simulator = Simulator(duel)
    summons = [
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
    ]
    assert len(summons) >= 2

    original = board_snapshot(duel)
    first = simulator.simulate(summons[0], viewer=MINE)
    second = simulator.simulate(summons[1], viewer=MINE)

    assert first.future.canonical_state() != second.future.canonical_state()
    # 각 사본에는 **자기 수만** 반영되어 있다.
    for result, action in ((first, summons[0]), (second, summons[1])):
        on_field = {
            card.instance_id for card in result.future.me.monster_zone.occupied()
        }
        assert on_field == {action.source}
    assert board_snapshot(duel) == original


@pytest.mark.real_card
def test_16_rng_isolation(repository):
    """
    사본에서 난수를 꺼내도 **진짜 판의 좌표가 움직이지 않는다** (§13).

    사본에 닿는 길은 :meth:`Simulator.fork_after` 하나이고, 그 사본의
    난수원을 몇 번 돌려도 원본의 ``draws`` 는 그대로다.
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    simulator = Simulator(duel)
    action = duel.legal_actions(MINE).allowed[0]
    before = board_snapshot(duel)
    draws = duel.state.randomness.draws

    forked = simulator.fork_after(action)
    assert isinstance(forked, Simulator)
    for _ in range(50):
        forked.duel.state.randomness.shuffle([1, 2, 3, 4, 5])

    assert forked.duel.state.randomness.draws == draws + 50
    assert duel.state.randomness.draws == draws
    assert board_snapshot(duel) == before


@pytest.mark.real_card
def test_16b_search_uses_clone_and_never_project(repository):
    """
    ``project()`` 를 쓰지 않는다 — 그것은 난수원을 **원본과 함께 쓴다.**

    이 시험은 둘의 차이가 실제로 존재함을 먼저 보이고, 그 다음 탐색 계층의
    소스에 ``project`` 가 없음을 확인한다.
    """
    duel = duel_with(repository)
    draws = duel.state.randomness.draws

    shared = duel.state.project()
    shared.randomness.shuffle([1, 2, 3])
    assert duel.state.randomness.draws == draws + 1, (
        "project() 가 원본을 오염시키지 않는다면 이 Phase 의 전제가 바뀐 것이다"
    )

    for name in ("simulation.py", "search.py", "evaluation.py"):
        source = (ROOT / "agent" / name).read_text()
        tree = ast.parse(source)
        used = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        assert "project" not in used, name
    assert "clone" in {
        node.attr
        for node in ast.walk(ast.parse((ROOT / "agent/simulation.py").read_text()))
        if isinstance(node, ast.Attribute)
    }


@pytest.mark.real_card
def test_17_search_off_versus_search_on_leaves_the_game_identical(repository):
    """
    **같은 수를 두면 탐색을 했든 안 했든 완전히 같은 듀얼이다** (§14).

    비교군은 "탐색을 전부 돌린 뒤 결과를 버리고 첫 후보를 고르는" 정책이다.
    시뮬레이션을 100 번 넘게 하고도 듀얼이 한 글자도 달라지지 않아야 한다.
    """
    off = duel_with(repository, seed=11)
    play(off, (FirstLegalPolicy(), FirstLegalPolicy()))

    on = duel_with(repository, seed=11)
    searcher = SearchesThenPicksFirst(on)
    play(on, (searcher, FirstLegalPolicy()))

    # 전투가 들어온 뒤로 듀얼이 짧아졌다 — 덱아웃(196걸음)이 아니라 LP 0 으로
    # 끝난다 (실측 46~126걸음 · 시뮬레이션 41~83회). 상한을 재측정값에 맞춘다.
    assert searcher.simulations > 30, "탐색을 거의 하지 않았으면 시험이 무의미하다"
    assert board_snapshot(on) == board_snapshot(off)


# ======================================================================
# Test 18 · 19 — 경계
# ======================================================================


@pytest.mark.real_card
def test_18_hidden_information_boundary(repository):
    """
    미래 관측은 **viewer 의 눈**이다. 상대 패와 덱이 보이지 않는다 (§18).
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    result = Simulator(duel).simulate(
        duel.legal_actions(MINE).allowed[0], viewer=MINE
    )
    future = result.future

    assert future.viewer == MINE
    assert future.opponent.hand.size > 0
    assert future.opponent.hand.cards == (), "상대 패의 카드가 보입니다"
    assert future.me.deck.concealed and future.me.deck.cards == ()
    assert future.opponent.deck.cards == ()
    # 내 패는 보인다 — 그것은 내가 아는 사실이다.
    assert all(card.is_identified for card in future.me.hand.occupied())


def test_18b_a_simulation_result_carries_no_board():
    """
    :class:`SimulationResult` 에 판을 담는 칸이 **없다.**

    담으면 "시뮬레이션을 갖고 있다" 는 이유로 정책이 모든 것을 읽을 수
    있게 된다. 실패한 시뮬레이션이 미래를 들고 있지도 않다.
    """
    names = {field.name for field in dataclasses.fields(SimulationResult)}
    assert names == {"action", "status", "viewer", "reason", "code", "future"}

    with pytest.raises(SimulationError, match="꾸며 내지 않습니다"):
        SimulationResult(
            action=PlayerAction.end_phase(actor=MINE),
            status=SimulationStatus.UNKNOWN,
            viewer=MINE,
            future=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(SimulationError, match="함께 옵니다"):
        SimulationResult(
            action=PlayerAction.end_phase(actor=MINE),
            status=SimulationStatus.SUPPORTED,
            viewer=MINE,
        )


def test_18c_the_search_layer_never_reaches_for_the_board():
    """
    ``search.py`` 와 ``evaluation.py`` 는 판에 손을 뻗지 않는다.

    판을 복제하고 적용하는 일은 ``simulation.py`` 하나가 하고, 그 모듈이
    돌려주는 것은 관측뿐이다.
    """
    for name in ("search.py", "evaluation.py"):
        tree = ast.parse((ROOT / "agent" / name).read_text())
        attributes = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        for forbidden in ("state", "clone", "project", "set_result", "randomness"):
            assert forbidden not in attributes, f"{name}: {forbidden}"
        built = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "PlayerAction")
                or (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "PlayerAction"
                )
            )
        ]
        assert built == [], f"{name} 가 행위를 만듭니다: {built}"


@pytest.mark.real_card
def test_19_invalid_action_protection(repository):
    """
    후보 목록에 없는 수는 **해 보지도 않는다** (§16 · §47).

    ``ATTACK`` 은 지금 후보에 오르지 않으므로 탐색이 그것을 상상해도
    시뮬레이터가 되돌려 보낸다.
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    simulator = Simulator(duel)
    hand = list(duel.state.player(MINE).hand)
    before = board_snapshot(duel)

    attack = PlayerAction.attack_directly(actor=MINE, source=hand[0].instance_id)
    result = simulator.simulate(attack, viewer=MINE)

    assert result.status is SimulationStatus.NOT_A_CANDIDATE
    assert result.future is None
    assert board_snapshot(duel) == before

    with pytest.raises(SimulationError, match="PlayerAction 이 필요합니다"):
        simulator.simulate("end_phase", viewer=MINE)  # type: ignore[arg-type]
    with pytest.raises(SimulationError, match="보는 자리"):
        simulator.simulate(duel.legal_actions(MINE).allowed[0], viewer=7)


@pytest.mark.real_card
def test_19b_whatever_the_policy_chooses_is_legal(repository):
    """
    탐색이 고른 수는 **언제나** 후보 목록 안에 있다 (§47).
    """
    duel = duel_with(repository)
    policy = search_policy(duel)
    checked = 0
    while not duel.is_over and checked < 60:
        if duel.advance() is not None:
            continue
        seat = duel.to_act
        legal = duel.legal_actions(seat)
        if not legal.allowed:
            break
        chosen = policy.decide(duel.view(seat), legal)
        assert chosen in legal.allowed
        checked += 1
        duel.apply(chosen)
    assert checked > 10


# ======================================================================
# Test 20 · 21 — 흔적과 예산
# ======================================================================


@pytest.mark.real_card
def test_20_search_trace(repository):
    """
    개발자가 **무엇을 내다봤는지** 읽을 수 있다. 그리고 흔적에 판이 없다 (§31).
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    policy = search_policy(duel)
    policy.decide(duel.view(MINE), duel.legal_actions(MINE))

    decision = policy.last_decision
    assert decision.state_hash == duel.state.state_hash()
    assert decision.turn_number == duel.state.turn.turn_number
    assert decision.phase is Phase.MAIN1
    assert decision.seat == MINE
    assert decision.simulations == len(decision.candidates)
    assert decision.of(decision.chosen) is not None
    assert "내다본 결과" in decision.reason
    assert decision.describe_ko()

    # 흔적의 어느 칸에도 판도 관측도 없다.
    for record in (decision, *decision.candidates):
        for field in dataclasses.fields(record):
            value = getattr(record, field.name)
            assert not isinstance(value, (GameStateView, Duel)), field.name
            assert not isinstance(value, Simulator), field.name
    assert "state" not in {f.name for f in dataclasses.fields(SearchDecision)}


@pytest.mark.real_card
def test_21_search_budget(repository):
    """
    예산을 넘긴 후보는 **점수만 없다. 후보에서 빠지지 않는다** (§36 · §37).

    빼 버리면 규칙상 가능한 수가 사라지고, 그것은 탐색이 규칙을 바꾼 것이다.
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    legal = duel.legal_actions(MINE)
    assert len(legal.allowed) >= 3

    policy = SearchPolicy(simulator=Simulator(duel), max_simulations=1)
    chosen = policy.decide(duel.view(MINE), legal)
    decision = policy.last_decision

    assert decision.simulations == 1
    assert decision.skipped == len(legal.allowed) - 1
    assert len(decision.candidates) == len(legal.allowed), "후보가 사라졌습니다"
    assert chosen in legal.allowed
    skipped = [c for c in decision.candidates if c.reason == SKIPPED_BY_BUDGET]
    assert len(skipped) == decision.skipped
    assert all(c.value is None and c.status is None for c in skipped)
    # 해 본 하나가 선택된다 — 못 해 본 것은 견줄 수 없으므로 뒤에 선다.
    assert decision.of(chosen).comparable
    assert policy.skipped_count() == decision.skipped

    # 예산이 넉넉하면 하나도 빠지지 않는다.
    full = search_policy(duel)
    full.decide(duel.view(MINE), legal)
    assert full.last_decision.skipped == 0


@pytest.mark.real_card
def test_21b_the_budget_picks_candidates_in_a_declared_order(repository):
    """
    예산이 **누구를 해 볼지** 고르는 순서도 결정론적이다.

    목록 순서에 따라 평가받는 후보가 달라지면 같은 판에서 다른 수가 나온다.
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    legal = duel.legal_actions(MINE)
    assert len(legal.allowed) >= 3

    forward = SearchPolicy(simulator=Simulator(duel), max_simulations=1)
    backward = SearchPolicy(simulator=Simulator(duel), max_simulations=1)
    chosen_forward = forward.decide(duel.view(MINE), legal)
    chosen_backward = backward.decide(
        duel.view(MINE), LegalActions(MINE, tuple(reversed(legal.allowed)))
    )

    assert chosen_forward == chosen_backward
    tried = [c for c in forward.last_decision.candidates if c.status is not None]
    assert len(tried) == 1
    assert tried[0].action.canonical_state() == min(
        a.canonical_state() for a in legal.allowed
    )


# ======================================================================
# Test 23 — 정책 재사용
# ======================================================================


@pytest.mark.real_card
def test_23_policy_reuse_across_games(repository):
    """
    정책 객체를 다시 써도 **지난 듀얼이 남지 않는다** (§40).

    ``attach`` 가 흔적을 지우고, 다시 쓴 정책의 결정이 새로 만든 정책의
    결정과 똑같아야 한다.
    """
    first = duel_with(repository, seed=3)
    reused = search_policy(first)
    play(first, (reused, FirstLegalPolicy()))
    assert reused.decisions

    second = duel_with(repository, seed=5)
    reused.attach(Simulator(second))
    assert reused.decisions == [], "attach 가 지난 듀얼을 지우지 않았습니다"
    play(second, (reused, FirstLegalPolicy()))

    fresh_duel = duel_with(repository, seed=5)
    fresh = search_policy(fresh_duel)
    play(fresh_duel, (fresh, FirstLegalPolicy()))

    assert [d.chosen for d in reused.decisions] == [d.chosen for d in fresh.decisions]
    assert board_snapshot(second) == board_snapshot(fresh_duel)

    with pytest.raises(SearchError, match="Simulator 가 필요합니다"):
        reused.attach(first)


# ======================================================================
# Test 24 · 25 — 실제 듀얼
# ======================================================================


@pytest.mark.real_card
def test_24_a_full_duel_runs_through_the_ai_interface(repository):
    """
    탐색 정책으로 듀얼 한 판이 **끝까지** 간다. 거절이 0 건이다 (§42 · §48).

    끝은 엔진이 선언한다 — 탐색이 승패를 만들지 않는다.
    """
    duel = duel_with(repository, seed=7)
    policy = search_policy(duel)
    transcript = play(duel, (policy, FirstLegalPolicy()))

    assert transcript.finished
    assert transcript.refusals == ()
    assert transcript.result is not None
    # Phase 3-E-1-B 전에는 덱아웃이 **유일한** 종료였다. 전투가 들어온 뒤로는
    # LP 0 으로 끝난다 (실측 8씨앗 전부). 엔진이 자란 것이므로 사실을 고친다 —
    # "끝까지 간다 · 거절이 없다" 는 주장은 그대로다.
    assert "라이프 포인트가 0 이 되었다" in transcript.result.reason
    assert transcript.steps > 30
    assert policy.simulation_count() > len(policy.decisions) // 2
    assert policy.skipped_count() == 0
    assert all(d.chosen is not None for d in policy.decisions if d.candidates)


@pytest.mark.real_card
def test_25_multiple_seeds(repository):
    """여러 씨앗에서 모두 끝까지 가고, 거절도 예산 초과도 없다 (§44)."""
    for seed in (1, 2, 3, 4, 5):
        duel = duel_with(repository, seed=seed)
        policy = search_policy(duel)
        transcript = play(duel, (policy, rule_based_policy()))

        assert transcript.finished, seed
        assert transcript.refusals == (), seed
        assert policy.skipped_count() == 0, seed
        # 실측 41~80회 (전투 이후). 전에는 108~119회였다.
        assert policy.simulation_count() > 30, seed


@pytest.mark.real_card
def test_25b_the_search_policy_coexists_with_every_other_policy(repository):
    """
    다섯 정책이 **함께 산다** (§7 · §33). 어느 조합으로도 듀얼이 끝난다.
    """
    duel = duel_with(repository, seed=6)
    opponents = (
        FirstLegalPolicy(),
        RandomPolicy(seed=99),
        rule_based_policy(),
    )
    for opponent in opponents:
        duel = duel_with(repository, seed=6)
        transcript = play(duel, (search_policy(duel), opponent))
        assert transcript.finished, opponent.name
        assert transcript.refusals == (), opponent.name


# ======================================================================
# 추가 — 깊이를 늘릴 자리가 실제로 있는가 (§57.9)
# ======================================================================


@pytest.mark.real_card
def test_the_structure_can_go_deeper_without_being_rebuilt(repository):
    """
    ``fork_after`` 가 **사본에 묶인 새 시뮬레이터**를 돌려준다.

    depth-2 는 이것을 한 번 더 부르는 일이고, 그때도 정책에게 가는 것은
    여전히 관측뿐이다. Phase 3-C 의 정책은 ``depth=1`` 이므로 **부르지
    않는다** — 그래서 여기서 따로 시험한다.
    """
    duel = duel_with(repository)
    to_main_phase(duel)
    simulator = Simulator(duel)
    summon = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
    )
    before = board_snapshot(duel)

    deeper = simulator.fork_after(summon)

    assert isinstance(deeper, Simulator)
    assert deeper.duel is not duel
    assert deeper.view(MINE).me.monster_zone.size == 1
    assert duel.view(MINE).me.monster_zone.size == 0
    # 그 사본에서 다시 한 수를 해 볼 수 있다 — 이것이 depth-2 의 전부다.
    nested = deeper.simulate(deeper.legal_actions(MINE).allowed[0], viewer=MINE)
    assert nested.status is SimulationStatus.SUPPORTED
    assert board_snapshot(duel) == before

    # 적용할 수 없는 수로는 이어 가지 않는다.
    assert simulator.fork_after(
        PlayerAction.attack_directly(actor=MINE, source=summon.source)
    ) is None


def test_the_executor_carries_no_per_duel_state():
    """
    사본이 **진짜와 같은 수행기**를 쓴다. 그래도 안전한 이유를 확인한다.

    ``ActionExecutor`` 가 들고 있는 것은 수행기 등록부 하나뿐이다 — 듀얼마다
    달라지는 상태가 없으므로 공유해도 사본과 원본이 섞이지 않는다. 여기에
    칸이 늘어나면 이 시험이 먼저 깨져야 한다.
    """
    from engine.action_execution import ActionExecutor

    assert ActionExecutor.__slots__ == ("_handlers",)


@pytest.mark.real_card
def test_search_is_fast_enough_to_finish_a_duel(repository):
    """
    성능은 두 번째 목표지만 **듀얼이 불가능할 정도로 느리면** 안 된다 (§38).
    """
    duel = duel_with(repository, seed=7)
    policy = search_policy(duel)
    started = time.perf_counter()
    play(duel, (policy, FirstLegalPolicy()))
    elapsed = time.perf_counter() - started

    assert policy.simulation_count() > 30
    assert elapsed < 30.0, f"듀얼 한 판에 {elapsed:.1f}s"
