"""
Phase 6-AL — **목표 도달 이후 제한적 후속 전개 탐색**.

이 파일이 고정하는 사실은 다섯이다.

======  ======================================================================
``A``   **첫 도달 모드는 기본값으로 남는다.** 후속 모드는 명시적으로 골라야
        켜지고, 켜지면 기준점 뒤의 허가된 행동을 **작은 상한 안에서** 더
        펼친다. 흐름 행동은 그 상한에 세지 않는다.
``B``   **목표 도달 이력과 최종 목표 유지는 다른 사실이다.** 후속 전개에서
        목표 카드를 소재·비용으로 써도 최초 도달 기록은 남고, 최종 상태에
        목표가 남아 있다고 적지 않는다.
``C``   **중복 제거와 중단 이유.** 목표 도달 이력과 남은 후속 예산이 방문
        판정에 들어가므로 더 갈 수 있는 경로를 버리지 않고, 상한·합법 불가·
        미지원·예산을 서로 구분한다.
``D``   **전체 경로 재생 검증.** 원래 시작 상태에서 최초 도달 지점을 다시
        확인하고, 그 뒤의 행동과 선택도 다시 실행하고, 최종 판과 자원 요약
        까지 견준다. 실패·예외·시간 초과는 검증 성공으로 세지 않는다.
``E``   **출력과 어댑터.** 요약·첨부가 §6 의 항목을 담고, 후속 모드에는
        자원 보존 추천을 연결하지 않았다는 사실을 밝힌다. CLI 와 Discord 는
        같은 실행 함수를 쓴다.
======  ======================================================================

🔴 **A · B · D 의 핵심은 실제 카드로 잰다.** 기르수(``69811710``) 를 목표로
두면 **두 걸음**이면 닿으므로, 30초짜리 긴 탐색을 반복하지 않고도 "목표에
도달한 뒤 더 간다" 를 실제 엔진으로 셀 수 있다. 🔴 **새 카드 효과를
구현하거나 허용 판정을 우회하지 않았다** — 쓰는 수는 전부 엔진이 그 자리에서
허가한 것이다.

🔴 **C 의 열쇠와 중단 이유는 작은 결정적 fixture 로 잰다** — 그 두 함수는
값만 보는 순수 함수이고, 경계를 재려면 값을 직접 주는 것이 정확하다.
production 함수(``_dedup_key`` · ``_stop_of`` · ``_collect``)를 그대로
부른다.

🔴 **이 단계는 최선 전개도, 최종 집 완성도, 실전 강도 검증도 아니다.**
"""

from __future__ import annotations

import dataclasses
import io
from dataclasses import dataclass

import pytest

import agent.bounded_search as bs
from agent.bounded_search import (
    BoundedSearch,
    BoundedSearchError,
    ContinuationStop,
    FLOW_ACTION_KINDS,
    FOLLOWUP_CAP,
    FieldGoal,
    FoundMeta,
    RerunDeadline,
    RerunState,
    ResultRole,
    SearchBudget,
    rerun_steps,
)

#: 잭나이츠 오르페골 기르수 — **두 걸음이면 자신 필드에 선다.**
GIRSU = 69811710
#: 오르페골 갈라테아 — 기존 입력의 목표 (어댑터 통합에서 쓴다).
GALATEA = 30741503
P0 = 0


# ======================================================================
# 실제 카드 픅스처
# ======================================================================
@pytest.fixture(scope="module")
def repository():
    from core.card_repository import CardRepository

    return CardRepository.build(db_path="data/cards.cdb", script_dir=".")


@pytest.fixture(scope="module")
def draft(repository):
    from deck.combo_policy import ORCUST_GIRSU_LINE
    from deck.recipe import parse_recipe

    parsed = parse_recipe(ORCUST_GIRSU_LINE.recipe_ydk, repository)
    assert parsed.draft is not None
    return parsed.draft


@pytest.fixture(scope="module")
def opening(repository, draft):
    """**새 초기 상태를 만드는 공장** — 재생마다 새로 만든다."""
    from app.main import opening_wiring
    from deck.combo_policy import ORCUST_GIRSU_LINE
    from deck.opening import build_opening

    def make():
        chooser, triggers = opening_wiring(repository, None)
        setup = build_opening(
            repository, draft, list(ORCUST_GIRSU_LINE.hand),
            chooser=chooser, triggers=triggers,
        )
        assert setup.can_run, setup.blockers
        return setup.duel

    return make


@pytest.fixture(scope="module")
def goal():
    return FieldGoal(card_id=GIRSU, seat=P0)


def _run(opening, goal, **budget):
    search = BoundedSearch(
        goal=goal, budget=SearchBudget(max_seconds=240, **budget)
    )
    return search, search.run_many(opening(), rerun_from=opening())


@pytest.fixture(scope="module")
def first_only(opening, goal):
    """**기본 모드** — 목표에 처음 도달하면 그 분기를 더 펼치지 않는다."""
    return _run(opening, goal, max_depth=3, max_nodes=60, max_results=3)


@pytest.fixture(scope="module")
def continued(opening, goal):
    """**후속 모드 (상한 1)** — 기준점 하나에서 한 걸음 더."""
    return _run(opening, goal, max_depth=4, max_nodes=120, max_results=5,
                max_followup_actions=1, max_baselines=1)


@pytest.fixture(scope="module")
def no_room(opening, goal):
    """
    후속 모드이지만 **깊이가 남지 않은** 경우 — 기준점이 깊이 상한이다.

    🔴 "후속이 없다" 와 "깊이가 없었다" 를 가르는 자리다.
    """
    return _run(opening, goal, max_depth=2, max_nodes=60, max_results=5,
                max_followup_actions=2, max_baselines=1)


def _after(result):
    """기준점 **뒤**의 걸음들."""
    return result.path[result.meta.reached_at:]


# ======================================================================
# A. 모드 계약
# ======================================================================
def test_a01_the_default_mode_still_stops_at_the_first_arrival(first_only):
    """
    🔴 **기본값은 그대로다** (§1). 후속 상한이 0 이면 목표에 처음 도달한
    분기를 더 펼치지 않는다 — 6-AI 와 한 글자도 다르지 않다.
    """
    search, outcome = first_only
    assert search.budget.max_followup_actions == 0
    assert search.budget.continues is False
    assert outcome.continues is False
    assert outcome.found >= 2
    #: 🔴 **전부 기준점이다** — 후속 후보가 없다.
    assert outcome.continued_results == ()
    assert len(outcome.baselines) == outcome.found
    for one in outcome.results:
        assert one.role is ResultRole.FIRST_ARRIVAL
        assert one.is_baseline
        #: 🔴 목표에 닿은 걸음이 **마지막 걸음**이다 (거기서 멈췄다).
        assert one.meta.reached_at == len(one.path)
        assert one.meta.followup_actions == 0
        assert one.goal_kept is True
        assert one.verified, one.rerun.reason


def test_a02_the_follow_up_mode_acts_after_the_first_arrival(continued):
    """
    🔴 **후속 모드는 최초 도달 이후 허가된 행동을 실행한다** (§1).

    쓰는 수는 전부 **엔진이 그 자리에서 허가한 것**이고, 이 시험은 새 카드
    효과를 만들지도 허용 판정을 우회하지도 않는다.
    """
    search, outcome = continued
    assert search.budget.continues is True
    assert outcome.continues is True
    assert outcome.reached_first_goal is True
    assert len(outcome.baselines) == 1
    assert len(outcome.continued_results) >= 1, outcome.describe_ko()

    baseline = outcome.baselines[0]
    for one in outcome.continued_results:
        assert one.role is ResultRole.CONTINUED
        assert one.is_baseline is False
        #: 🔴 기준점의 경로가 **앞부분으로 그대로** 들어 있다.
        assert one.meta.reached_at == baseline.meta.reached_at
        assert tuple(step.action_key for step in
                     one.path[:one.meta.reached_at]) == \
            tuple(step.action_key for step in baseline.path)
        assert len(one.path) > len(baseline.path)
        assert one.meta.followup_actions >= 1
        assert one.verified, one.rerun.reason
    #: 🔴 **기준점도 결과로 남는다** (§1-4).
    assert baseline.verified


def test_a03_a_zero_cap_returns_only_the_baselines(opening, goal):
    """🔴 **후속 상한 0 이면 기준점만 돌려준다** (§7)."""
    _search, outcome = _run(opening, goal, max_depth=3, max_nodes=60,
                            max_results=3, max_followup_actions=0,
                            max_baselines=3)
    assert outcome.continues is False
    assert outcome.continued_results == ()
    assert outcome.baselines == outcome.results
    assert all(one.meta.stop is ContinuationStop.OPEN
               for one in outcome.results)


def test_a04_the_action_cap_stops_the_expansion(continued):
    """
    🔴 **상한에 도달하면 더 확장하지 않는다** (§7) — 그리고 그 사실이 종료
    사유와 후보의 멈춘 이유에 남는다.
    """
    search, outcome = continued
    cap = search.budget.max_followup_actions
    assert cap == 1
    for one in outcome.continued_results:
        assert one.meta.followup_actions <= cap
    stops = {one.meta.stop for one in outcome.continued_results}
    assert ContinuationStop.ACTION_CAP in stops, stops
    assert any(f"max_followup_actions={cap}" in line
               for line in outcome.budget_hit), outcome.budget_hit
    #: 🔴 **"다 봤다" 가 아니다.**
    assert outcome.search_exhausted is False


def test_a05_flow_actions_are_not_charged_to_the_cap(continued, first_only):
    """
    🔴 **흐름 행동을 후속 전개 비용으로 세지 않는다** (§3 · §7).

    실제 경로에서 센다 — 기준점 뒤의 걸음 중 흐름이 아닌 것만
    ``followup_actions`` 이고, 흐름은 ``followup_flow`` 에 따로 남는다.
    """
    #: 정의가 **한 곳에만** 있다 (평가 v1 과 같은 집합을 본다).
    from agent.result_ranking import FLOW_ACTION_KINDS as RANKING_FLOW

    assert RANKING_FLOW is FLOW_ACTION_KINDS
    assert "pass" in FLOW_ACTION_KINDS

    _search, outcome = continued
    for one in outcome.continued_results:
        tail = _after(one)
        spend = [step for step in tail
                 if step.kind not in FLOW_ACTION_KINDS]
        flow = [step for step in tail if step.kind in FLOW_ACTION_KINDS]
        assert one.meta.followup_actions == len(spend), [s.kind for s in tail]
        assert one.meta.followup_flow == len(flow), [s.kind for s in tail]

    #: 🔴 기준점 **앞**의 흐름 행동(패스)도 후속 수에 들어가지 않는다 —
    #: 기본 모드의 기준점이 패스를 포함해도 ``followup_actions`` 는 0 이다.
    _s, plain = first_only
    assert any("pass" in [step.kind for step in one.path]
               for one in plain.results)
    assert all(one.meta.followup_actions == 0 for one in plain.results)


def test_a06_a_consumed_goal_keeps_its_arrival_record(continued):
    """
    🔴 **목표 카드를 나중에 소재·비용으로 써도 최초 도달 기록은 남는다**
    (§2 · §7).

    그리고 **최종 상태에 목표가 남아 있다고 적지 않는다** — 둘은 다른
    사실이고, 재생이 그 둘을 각각 확인한다.
    """
    _search, outcome = continued
    spent = [one for one in outcome.continued_results if not one.goal_kept]
    assert spent, (
        "목표를 소재로 쓰는 후속이 하나도 없었다 — 실제 전개가 바뀌었는지"
        " 확인해야 한다: "
        + str([(one.index, [s.kind for s in one.path]) for one
               in outcome.continued_results])
    )
    for one in spent:
        #: 최초 도달 기록은 그대로다.
        assert one.meta.reached_at >= 1
        assert one.meta.goal_kept is False
        #: 🔴 **재생이 둘을 따로 확인했다.**
        assert one.rerun is not None
        assert one.rerun.first_arrival_confirmed is True
        assert one.rerun.first_arrival_at == one.meta.reached_at
        assert one.rerun.goal_kept is False
        #: 🔴 **그래도 검증된 결과다** — 최종 상태에 목표가 없다는 이유만으로
        #: 실패시키지 않는다.
        assert one.verified
        assert one.rerun_state is RerunState.VERIFIED
        #: 🔴 그렇다고 "목표가 있는 집" 으로 적지도 않는다.
        assert one.goal_kept is False


def test_a07_the_budget_is_not_restarted_for_each_baseline(opening, goal):
    """
    🔴 **시간 · 노드 · 결과 예산을 기준점마다 초기화하지 않는다** (§3 · §7).

    노드 예산을 기준점 하나를 찾는 비용보다 조금 크게 두면, 후속을 다 보지
    못한 채 **노드 예산**에 걸려야 한다.
    """
    _search, outcome = _run(opening, goal, max_depth=4, max_nodes=11,
                            max_results=5, max_followup_actions=2,
                            max_baselines=3)
    assert any("max_nodes=11" in line for line in outcome.budget_hit), \
        outcome.budget_hit
    assert outcome.nodes_expanded <= 11 + 1
    assert outcome.search_exhausted is False
    #: 🔴 예산이 끊겨도 **그때까지 모은 것은 보존된다.**
    assert outcome.found >= 1


def test_a08_no_continued_candidate_still_keeps_the_first_arrival(no_room):
    """
    🔴 **후속 후보를 하나도 찾지 못해도 최초 도달 결과와 그 이유를
    보존한다** (§4 · §7).
    """
    search, outcome = no_room
    assert search.budget.continues is True
    assert outcome.reached_first_goal is True
    assert len(outcome.baselines) >= 1
    assert outcome.continued_results == ()
    assert outcome.baselines[0].verified
    #: 🔴 **왜 못 갔는지**가 남는다 — 깊이 상한은 후속 상한과 다른 상한이다.
    joined = " ".join(outcome.followup_notes)
    assert "깊이 상한" in joined, outcome.followup_notes
    assert "후속 행동 상한과 다른 상한" in joined


def test_a09_the_input_is_untouched_and_ids_stay_bound(opening, goal):
    """🔴 **원본 상태 불변과 결과 ID·경로 연결 유지** (§7)."""
    duel = opening()
    before = duel.state.state_hash()
    draws = duel.state.randomness.draws
    search = BoundedSearch(
        goal=goal,
        budget=SearchBudget(max_depth=4, max_nodes=60, max_seconds=240,
                            max_results=4, max_followup_actions=1,
                            max_baselines=1),
    )
    outcome = search.run_many(duel, rerun_from=opening())

    assert duel.state.state_hash() == before
    assert duel.state.randomness.draws == draws
    #: 🔴 결과 ID 는 1부터 차례이고, 각 ID 가 자기 경로를 들고 있다.
    assert [one.index for one in outcome.results] == \
        list(range(1, outcome.found + 1))
    assert len({one.index for one in outcome.results}) == outcome.found
    for one in outcome.results:
        assert one.path
        assert one.rerun is None or one.rerun.steps in (0, len(one.path))


# ======================================================================
# C. 열쇠와 중단 이유 (작은 결정적 fixture)
# ======================================================================
@dataclass(frozen=True, slots=True)
class _Action:
    kind: object
    key: tuple = ()

    def canonical_state(self):
        return self.key


@dataclass(frozen=True, slots=True)
class _Legal:
    allowed: tuple = ()
    held: tuple = ()

    def unsupported(self):
        return self.held


def _searcher(goal, **budget):
    return BoundedSearch(goal=goal, budget=SearchBudget(**budget))


def test_c01_the_dedup_key_separates_before_and_after_the_goal(
    opening, goal
):
    """
    🔴 **목표 도달 전후에 같은 상태를 방문하는 경우를 가른다** (§3 · §7).

    같은 판이라도 목표를 지난 뒤에는 할 수 있는 일(후속 수집)이 다르므로,
    같은 열쇠로 묶으면 후속 탐색이 시작되지 못한다.
    """
    duel = opening()
    legal = duel.legal_actions(duel.to_act)
    follow = _searcher(goal, max_results=3, max_followup_actions=2)
    plain = _searcher(goal, max_results=3)

    before = follow._dedup_key(duel, legal, reached_at=0, followups=0)
    after = follow._dedup_key(duel, legal, reached_at=2, followups=0)
    assert before != after
    assert before[:5] == after[:5] == bs.node_key(duel, legal)

    #: 🔴 **첫 도달 모드에서는 ``node_key`` 그대로다** — 한 글자도 다르지
    #: 않다.
    assert plain._dedup_key(duel, legal, reached_at=0, followups=0) == \
        bs.node_key(duel, legal)
    assert plain._dedup_key(duel, legal, reached_at=2, followups=1) == \
        bs.node_key(duel, legal)


def test_c02_a_path_with_more_follow_up_budget_is_not_discarded(
    opening, goal
):
    """
    🔴 **같은 상태에 도착했다는 이유만으로 더 많은 탐색 기회를 가진 경로를
    버리지 않는다** (§3 · §7).

    남은 후속 예산이 열쇠에 들어가므로 두 경로가 다른 노드가 되고,
    :func:`~agent.bounded_search.admit` 이 뒤의 것을 중복으로 버리지 않는다.
    """
    duel = opening()
    legal = duel.legal_actions(duel.to_act)
    follow = _searcher(goal, max_results=3, max_followup_actions=2)

    poor = follow._dedup_key(duel, legal, reached_at=2, followups=2)
    rich = follow._dedup_key(duel, legal, reached_at=2, followups=0)
    assert poor != rich
    #: 남은 예산이 열쇠의 마지막 칸이다 — 많은 쪽이 다른 값이다.
    assert poor[-1] == 0 and rich[-1] == 2

    seen: dict = {}
    assert bs.admit(seen, poor, 3) is bs.Admission.FRESH
    #: 🔴 예산이 더 많은 쪽은 **중복이 아니다.**
    assert bs.admit(seen, rich, 3) is bs.Admission.FRESH
    #: 같은 열쇠로 같은 깊이에 다시 오면 그때는 중복이다.
    assert bs.admit(seen, rich, 3) is bs.Admission.DUPLICATE


def test_c03_the_stop_reasons_are_told_apart(goal):
    """
    🔴 **상한 · 합법 불가 · 미지원 · 깊이를 서로 구분한다** (§3 · §4 · §7).

    특히 **미지원이 남아 있으면 "더 할 수 있는 것이 없다" 고 단정하지
    않는다.**
    """
    from engine.action import PlayerActionKind

    follow = _searcher(goal, max_depth=5, max_results=3,
                       max_followup_actions=2)
    plain = _searcher(goal, max_results=3)
    play = _Action(kind=PlayerActionKind.NORMAL_SUMMON)
    leave = _Action(kind=PlayerActionKind.END_PHASE)

    #: 허가된 수가 없고 미지원도 없다 → 합법적으로 불가.
    assert follow._stop_of(_Legal(allowed=(leave,)), 0, 1) is \
        ContinuationStop.NO_LEGAL
    #: 🔴 허가된 수가 없지만 **미지원이 남아 있다** → 단정하지 않는다.
    assert follow._stop_of(_Legal(allowed=(leave,), held=("x",)), 0, 1) is \
        ContinuationStop.UNSUPPORTED_LEFT
    #: 상한에 닿았다.
    assert follow._stop_of(_Legal(allowed=(play,)), 2, 1) is \
        ContinuationStop.ACTION_CAP
    #: 🔴 깊이 상한은 **다른 상한**이다.
    assert follow._stop_of(_Legal(allowed=(play,)), 0, 5) is \
        ContinuationStop.DEPTH_CAP
    #: 더 갈 수 있다 — 🔴 **전개 완료가 아니다.**
    assert follow._stop_of(_Legal(allowed=(play,)), 0, 1) is \
        ContinuationStop.OPEN
    #: 첫 도달 모드에서는 이 판정을 쓰지 않는다.
    assert plain._stop_of(_Legal(allowed=(leave,)), 0, 1) is \
        ContinuationStop.OPEN


def test_c04_the_role_is_part_of_the_outcome_key(opening, goal):
    """
    🔴 **기준점과 후속 후보는 같은 최종 상태라도 합치지 않는다** (§4).

    합치면 흐름 행동만 한 후속 후보가 기준점을 덮어쓴다 — 둘은 다른
    사실이다.
    """
    duel = opening()
    legal = duel.legal_actions(duel.to_act)
    verdict = goal.judge(duel, legal)
    follow = _searcher(goal, max_results=5, max_followup_actions=2)
    ledger = bs._Ledger()
    step = bs.PathStep(order=1, kind="normal_summon", action_key=("a",))

    follow._collect(ledger, (step,), duel, legal, verdict,
                    FoundMeta(reached_at=1))
    follow._collect(ledger, (step,), duel, legal, verdict,
                    FoundMeta(role=ResultRole.CONTINUED, reached_at=1,
                              followup_actions=1))
    assert len(ledger.results) == 2
    assert ledger.count_of(ResultRole.FIRST_ARRIVAL) == 1
    assert ledger.count_of(ResultRole.CONTINUED) == 1
    assert ledger.duplicate_results == 0


def test_c05_merged_paths_keep_every_arrival_record(opening, goal):
    """
    🔴 **서로 다른 최초 도달 기록이 합쳐질 때 그 이력을 지우지 않는다**
    (§4).

    대표는 기존 기준(:func:`~agent.bounded_search.representative_order` —
    걸음 수 → 행동 열쇠 → 선택)이 고르고, 합쳐진 쪽의 도달 위치는
    ``merged_arrivals`` 에 남는다.
    """
    duel = opening()
    legal = duel.legal_actions(duel.to_act)
    verdict = goal.judge(duel, legal)
    follow = _searcher(goal, max_results=5, max_followup_actions=2)
    ledger = bs._Ledger()
    long_path = (
        bs.PathStep(order=1, kind="a", action_key=("a",)),
        bs.PathStep(order=2, kind="b", action_key=("b",)),
        bs.PathStep(order=3, kind="c", action_key=("c",)),
    )
    short_path = (
        bs.PathStep(order=1, kind="a", action_key=("a",)),
        bs.PathStep(order=2, kind="z", action_key=("z",)),
    )

    follow._collect(ledger, long_path, duel, legal, verdict,
                    FoundMeta(role=ResultRole.CONTINUED, reached_at=2,
                              followup_actions=1))
    follow._collect(ledger, short_path, duel, legal, verdict,
                    FoundMeta(role=ResultRole.CONTINUED, reached_at=1,
                              followup_actions=1))

    assert len(ledger.results) == 1
    assert ledger.duplicate_results == 1
    kept_path, _summary, _reason = ledger.results[0]
    #: 🔴 **더 짧은 경로가 대표다** (기존 기준 그대로).
    assert kept_path == short_path
    meta = ledger.result_meta[0]
    assert meta.reached_at == 1
    #: 🔴 **합쳐진 쪽의 도달 걸음이 남아 있다.**
    assert meta.merged_arrivals == (2,)


# ======================================================================
# D. 전체 경로 재생 검증
# ======================================================================
def test_d01_the_rerun_confirms_the_arrival_and_the_final_state(
    opening, goal, continued
):
    """
    🔴 **원래 시작 상태에서 최초 도달 지점을 다시 확인하고, 그 뒤의 행동과
    선택도 다시 실행하고, 최종 판과 자원 요약까지 견준다** (§2 · §7).
    """
    _search, outcome = continued
    for one in outcome.continued_results:
        rerun = rerun_steps(
            opening(), one.path, goal,
            expect_field=one.resources.own_field_rows,
            expect_hash=one.resources.state_hash,
            reached_at=one.meta.reached_at,
        )
        assert rerun.ok, rerun.reason
        assert rerun.first_arrival_confirmed is True
        assert rerun.first_arrival_at == one.meta.reached_at
        assert rerun.matches_search is True
        assert rerun.resources == one.resources
        assert rerun.steps == len(one.path)
        assert rerun.goal_kept == one.meta.goal_kept
        assert "최초 도달" not in rerun.reason or "확인" in rerun.reason


def test_d02_a_wrong_arrival_point_fails_the_rerun(opening, goal, continued):
    """
    🔴 **최초 도달 확인을 생략하고 성공시키지 않는다** (§2).

    기록이 "걸음 1에서 도달" 이라고 말하는데 실제로 그 걸음에서 닿지
    않았으면 **실패**다.
    """
    _search, outcome = continued
    one = outcome.continued_results[0]
    assert one.meta.reached_at >= 2

    rerun = rerun_steps(
        opening(), one.path, goal,
        expect_field=one.resources.own_field_rows,
        expect_hash=one.resources.state_hash,
        reached_at=1,
    )
    assert rerun.ok is False
    assert rerun.first_arrival_confirmed is False
    assert "최초 도달 확인" in rerun.stage
    assert rerun.first_arrival_at == 1


def test_d03_an_impossible_arrival_point_is_refused(opening, goal, continued):
    """🔴 **도달 지점을 지어내지 않는다** — 경로 밖이면 거절한다."""
    _search, outcome = continued
    one = outcome.continued_results[0]
    for bad in (len(one.path) + 1, -1, True, "2"):
        with pytest.raises(BoundedSearchError):
            rerun_steps(opening(), one.path, goal, reached_at=bad)


def test_d04_a_tampered_follow_up_step_is_not_verified(
    opening, goal, continued
):
    """
    🔴 **재생 실패를 검증 성공으로 세지 않는다** (§7).

    기준점 **뒤**의 행동을 바꿔 놓으면 그 자리의 허용 후보에 없으므로
    실패한다 — 최초 도달이 확인됐더라도 그렇다.
    """
    _search, outcome = continued
    one = outcome.continued_results[0]
    tail = _after(one)
    assert tail
    broken = one.path[:one.meta.reached_at] + tuple(
        dataclasses.replace(step, action_key=("없는-행동",))
        for step in tail
    )
    rerun = rerun_steps(
        opening(), broken, goal,
        expect_field=one.resources.own_field_rows,
        expect_hash=one.resources.state_hash,
        reached_at=one.meta.reached_at,
    )
    assert rerun.ok is False
    assert "허용 후보에" in rerun.reason
    #: 🔴 그 결과는 검증된 것이 아니다.
    spoiled = dataclasses.replace(one, rerun=rerun, resources_match=False)
    assert spoiled.verified is False


def test_d05_a_timeout_in_follow_up_mode_is_not_verified(
    opening, goal, continued
):
    """🔴 **시간 초과 결과를 검증 성공으로 세지 않는다** (§7)."""
    class _Clock:
        def __init__(self):
            self.now = 0.0

        def __call__(self):
            return self.now

    _search, outcome = continued
    one = outcome.continued_results[0]
    clock = _Clock()
    deadline = RerunDeadline(limit=1.0, clock=clock)
    clock.now = 10.0  # 🔴 가상 시계다.

    rerun = rerun_steps(
        opening(), one.path, goal,
        expect_field=one.resources.own_field_rows,
        expect_hash=one.resources.state_hash,
        reached_at=one.meta.reached_at,
        deadline=deadline,
    )
    assert rerun.timed_out is True
    assert rerun.ok is False
    spoiled = dataclasses.replace(one, rerun=rerun, resources_match=False)
    assert spoiled.rerun_state is RerunState.TIMED_OUT
    assert spoiled.verified is False


def test_d06_the_first_arrival_mode_rerun_is_unchanged(opening, goal,
                                                      first_only):
    """
    🔴 **첫 도달 모드의 재생은 한 글자도 달라지지 않았다** (§2).

    도달 지점을 주지 않으면 기존대로 **최종 상태의 목표**를 본다.
    """
    _search, outcome = first_only
    one = outcome.results[0]
    rerun = rerun_steps(
        opening(), one.path, goal,
        expect_field=one.resources.own_field_rows,
        expect_hash=one.resources.state_hash,
    )
    assert rerun.ok is True
    assert rerun.first_arrival_at == 0
    assert rerun.goal_reached is True
    assert rerun.first_arrival_confirmed is True
    assert rerun.goal_kept is True


# ======================================================================
# E. 출력과 어댑터
# ======================================================================
def test_e01_the_brief_carries_the_five_items(repository, continued):
    """🔴 **기본 응답의 다섯 항목** (§6)."""
    from deck import report

    _search, outcome = continued
    text = report.render_multi_search_brief(outcome, repository)

    assert "최초 목표 도달: 예" in text
    assert "재생 검증된 후속 후보" in text
    assert "뒤에 더 한 것:" in text
    assert "기준점(결과 1) 대비 자원 변화" in text
    assert "멈춘 이유:" in text
    #: 🔴 범위와 금칙이 요약에 있다.
    assert "최선 전개도, 최종 집 완성도, 실전 강도 검증도 아닙니다" in text
    #: 🔴 **단정하는 말은 없다.** (부정문 안의 같은 낱말은 그 부정문이
    #: 있어야 하는 말이므로, 단정형만 센다.)
    for banned in ("최선 전개입니다", "최종 집이 완성", "최종 집 완성입니다",
                   "실전 강도 검증 완료", "최강"):
        assert banned not in text, banned


def test_e02_the_detail_carries_the_six_items(repository, continued):
    """🔴 **상세 첨부의 여섯 항목** (§6)."""
    from deck import report

    _search, outcome = continued
    text = report.render_multi_search(outcome, repository)

    assert "후속 전개 (기준점과 전체 경로)" in text
    assert "최초 도달 걸음:" in text
    assert "[기준점 앞]" in text and "[기준점 뒤]" in text
    assert "최종 상태에 목표 카드:" in text
    assert "최초 도달 확인" in text
    assert "쓴 예산 — 후속 비흐름 행동 상한" in text
    assert "검증 한계" in text
    assert "가능한 전부가 아닙니다" in text
    #: 🔴 중복 제거가 약해진다는 사실도 적는다.
    assert "중복 제거가" in text and "약해져" in text


def test_e03_no_ranking_is_attached_in_follow_up_mode(repository, continued):
    """
    🔴 **후속 모드에 자원 보존 추천을 연결하지 않고, 그 사실을 밝힌다**
    (§5).
    """
    from app.main import rank_search_results
    from deck import report

    _search, outcome = continued
    assert rank_search_results(outcome) is None

    text = report.render_multi_search_brief(outcome, repository)
    assert "추천 — 어느 후보를 먼저 볼까" not in text
    assert "추천(resource-preservation v1)을 연결하지 않았습니다" in text
    assert "패를 쓰는 행동을 불리하게 보므로" in text
    #: 🔴 기준점보다 패가 줄었다고 "나빠진 전개" 라고 적지 않는다.
    for banned in ("나빠진", "강해진 집", "약해진"):
        assert banned not in text


def test_e04_the_first_arrival_mode_output_is_unchanged(
    repository, first_only
):
    """🔴 **첫 도달 모드의 출력에는 후속 절이 한 줄도 붙지 않는다** (§1)."""
    from app.main import rank_search_results
    from deck import report

    _search, outcome = first_only
    brief = report.render_multi_search_brief(outcome, repository)
    detail = report.render_multi_search(outcome, repository)
    assert "후속 전개" not in brief
    assert "후속 전개 (기준점과 전체 경로)" not in detail
    #: 🔴 추천은 그대로 붙는다 (6-AK 동작 유지).
    ranking = rank_search_results(outcome)
    assert ranking is not None
    with_rank = report.render_multi_search_brief(outcome, repository, ranking)
    assert "추천 — 어느 후보를 먼저 볼까" in with_rank
    assert "후속 전개" not in with_rank


def test_e05_both_adapters_select_the_mode_through_one_function():
    """
    🔴 **CLI 와 Discord 는 같은 실행 함수를 쓴다** (§6) — 각자 탐색 로직을
    만들지 않는다. 그리고 **새 명령어 체계를 만들지 않았다.**
    """
    import inspect

    import app.discord_bot as bot
    from app.main import (
        bounded_search_many_opening, build_parser, search_followup_count,
    )

    assert "followups" in inspect.signature(
        bounded_search_many_opening).parameters

    cli = io.open("app/main.py", encoding="utf-8").read()
    chat = io.open("app/discord_bot.py", encoding="utf-8").read()
    for source in (cli, chat):
        assert "search_followup_count" in source
        assert "followups=extra" in source
    #: 🔴 어댑터는 ``agent`` 를 직접 import 하지 않는다 (기존 경계).
    assert "result_ranking" not in chat
    assert "bounded_search import" not in chat

    #: 모드 선택은 **맨 뒤의 선택 인자** 하나다.
    parser = build_parser()
    combo = parser._subparsers._group_actions[0].choices["combo"]
    flags = {
        option for action in combo._actions
        for option in action.option_strings if option.startswith("--")
    }
    assert "--followups" in flags
    pytest.importorskip("discord", reason="봇 전용 의존성")
    _client, tree = bot.build_client(dev_guild_id=None, service=object())
    names = [one.name for one in
             {c.name: c for c in tree.get_commands()}["combo"].parameters]
    assert names[-1] == "followups"
    assert names == ["hand", "board", "deck", "recipe", "line", "search",
                     "results", "followups"]

    #: 🔴 읽지 못하면 **탐색하지 않는다** — 조용히 깎아 주지 않는다.
    assert search_followup_count("") == (0, "")
    assert search_followup_count(str(FOLLOWUP_CAP))[0] == FOLLOWUP_CAP
    assert search_followup_count(str(FOLLOWUP_CAP + 1))[0] is None
    assert search_followup_count("둘")[0] is None


def test_e06_the_follow_up_flag_needs_the_multi_mode(capsys, repository):
    """
    🔴 **후속 모드를 조용히 켜 주지 않는다** — ``results`` 없이 ``followups``
    만 주면 탐색하지 않고 무엇을 더 주어야 하는지 적는다.
    """
    from app.main import DeckAgent, _print_bounded_search

    agent = DeckAgent(repository=repository)
    _print_bounded_search(agent, "욕망의 항아리 x3, 11091375 x37", [GIRSU],
                          "galatea", "", "2")
    said = capsys.readouterr().out
    assert "하지 않았습니다" in said
    assert "--results 2 이상과" in said


# ======================================================================
# F. 실제 카드 통합 — 기존 오르페골 입력과 기존 목표
# ======================================================================
@pytest.fixture(scope="module")
def galatea_followup(repository, draft):
    """기존 입력 · 기존 목표(갈라테아)로 **어댑터 경로**를 그대로 돈다."""
    from app.main import bounded_search_many_opening
    from deck.combo_policy import ORCUST_GIRSU_LINE

    return bounded_search_many_opening(
        repository, draft, list(ORCUST_GIRSU_LINE.hand),
        card_id=GALATEA, max_results=2, followups=1,
    )


def test_f01_the_real_orcust_input_continues_past_the_goal(galatea_followup):
    """
    🔴 **기존 오르페골 입력에서 목표 도달 뒤 실제로 더 간다** (§7).

    엔진이 허가한 수만 쓰고, 추가 행동이 무엇이었는지는 **실제로 나타난
    것만** 센다 — 세트뿐이면 세트뿐이라고 적힌다.
    """
    _setup, outcome = galatea_followup
    assert outcome is not None
    assert outcome.continues is True
    assert outcome.reached_first_goal
    assert len(outcome.baselines) >= 1
    assert len(outcome.continued_results) >= 1, outcome.describe_ko()

    #: 🔴 **깊이 상한을 후속 상한만큼 올려 잡았다** — 상한을 무시한 것이
    #: 아니라 두 상한이 서로를 잡아먹지 않게 둔 것이고, 예산 설명에 보인다.
    assert outcome.budget.max_followup_actions == 1
    assert outcome.budget.max_depth == \
        bs.DEFAULT_MAX_DEPTH + outcome.budget.max_followup_actions
    assert "후속 행동 1회" in outcome.budget.describe_ko()

    kinds = set()
    for one in outcome.continued_results:
        assert one.verified, one.rerun.reason
        assert one.meta.followup_actions == 1
        assert one.rerun.first_arrival_confirmed is True
        kinds |= {step.kind for step in _after(one)}
    #: 실제로 수행한 행동은 엔진이 허가한 것들이다 (무엇이었는지는 아래가
    #: 그대로 보여 준다 — 과장하지 않는다).
    assert kinds, kinds
    assert not (kinds - {"set_spell_trap", "link_summon", "activate_effect",
                         "normal_summon", "set_monster", "special_summon",
                         "change_position", "pass"}), kinds


def test_f02_the_real_run_tells_the_arrival_from_the_final_board(
    galatea_followup
):
    """
    🔴 **최초 도달과 최종 목표 유지를 실제 입력에서도 가른다** (§2).
    """
    _setup, outcome = galatea_followup
    for one in outcome.continued_results:
        assert one.meta.reached_at < len(one.path)
        assert one.rerun.first_arrival_at == one.meta.reached_at
        #: 재생이 센 최종 목표 유지와 탐색이 적어 둔 것이 같다.
        assert one.goal_kept == one.rerun.goal_kept == one.meta.goal_kept
