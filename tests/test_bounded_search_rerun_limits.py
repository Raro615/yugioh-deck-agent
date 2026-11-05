"""
Phase 6-AJ — **복수 경로 재생의 공유 시간 제한과 결과별 예외 격리**.

이 파일이 고정하는 사실은 넷이다.

======  ======================================================================
``A``   재생은 **마감 하나를 모든 결과가 돌려 쓴다.** 결과마다 예산을 새로
        시작하지 않고, 단조 시계로 재며, 경로 시작 전 · 각 행동 전후 ·
        필수 걸음 반복의 안전한 경계 · 최종 검증과 자원 요약 뒤에서 마감을
        본다. 넘긴 결과는 **검증 성공이 되지 않는다.**
``B``   결과 하나의 재생에서 난 **일반 실행 예외**는 그 결과의 실패로만
        적히고, 남은 예산이 있으면 다음 결과가 **새 초기 상태에서** 계속
        검증된다. 🔴 ``KeyboardInterrupt`` · ``SystemExit`` 같은 종료
        신호는 삼키지 않는다.
``C``   여섯 가지 재생 상태(검증 · 불일치 · 예외 · 시간 초과 · 미시작 ·
        끔)가 **구분되고 집계가 맞아떨어진다.** 하나가 실패해도 다른
        결과의 비교표는 유지되고, 찾은 경로는 사라지지 않는다.
``D``   실제 카드 입력의 **정상 경로**가 그대로다 — 서로 다른 결과를 모아
        각각 재생하고 자원을 비교한다.
======  ======================================================================

🔴 **A · B · C 는 제어 가능한 단조 시계와 주입된 예외로 잰다 — 실제 sleep
이나 기계 성능에 기대지 않고, 실제 카드 실행이 그 시간을 썼다는 뜻도
아니다.** "예산 1초에 10초가 걸렸다" 는 **가상 시계의 숫자**이고 실제
전개의 소요가 아니다.

🔴 **그러나 바꿔 끼우는 것은 최소한이다.** 시계(와 B 절의 예외 자리)만
격리하고, :func:`~agent.bounded_search.rerun_steps` 의 재생 반복문 ·
:func:`~agent.bounded_search._settle` 의 필수 걸음 반복 ·
:meth:`~agent.bounded_search.BoundedSearch.rerun_results` 의 결과별 고리 ·
:meth:`~agent.bounded_search.BoundedSearch._rerun_one` 의 예외 경계 ·
:meth:`~agent.bounded_search.BoundedSearch._many_outcome` 의 집계는 **전부
production 그대로** 돈다. A 절의 경계는 **실제 카드 경로**로 잰다.

🔴 **강약 평가가 아니다.** 어느 결과가 더 좋은지 고르는 코드도 시험도
여기 없다.
"""

from __future__ import annotations

import ast
import dataclasses
import io

import pytest

import agent.bounded_search as bs
from agent.bounded_search import (
    BoundedSearch,
    BoundedSearchError,
    FieldGoal,
    PathResult,
    RerunDeadline,
    RerunResult,
    RerunState,
    ResultTally,
    SearchBudget,
    Termination,
    rerun_steps,
)

#: 실제 카드 — 갈라테아 (목표), 『성장』 입력의 레시피는 아래 픅스처가 읽는다.
GALATEA = 30741503
P0 = 0


# ======================================================================
# 제어 가능한 단조 시계
# ======================================================================
class _Clock:
    """
    시험이 **직접 돌리는 단조 시계**.

    🔴 **뒤로 가지 않는다** — ``step`` 과 ``jump`` 가 모두 0 이상이므로
    읽을수록 커진다. 실제 :func:`time.monotonic` 을 대신하는 자리이고,
    실제 ``sleep`` 을 쓰지 않는 이유는 하나다: 기계가 빠르거나 느리다고
    경계 판정이 달라지면 그 시험은 경계를 재는 것이 아니다.
    """

    def __init__(self, *, start: float = 0.0, step: float = 0.0,
                 jump_at: "int | None" = None, jump: float = 0.0):
        assert step >= 0 and jump >= 0
        self.now = float(start)
        self.step = float(step)
        self.jump_at = jump_at
        self.jump = float(jump)
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        if self.jump_at is not None and self.reads == self.jump_at:
            self.now += self.jump
        value = self.now
        self.now += self.step
        return value

    def advance(self, seconds: float) -> None:
        assert seconds >= 0
        self.now += float(seconds)


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
    """
    **새 초기 상태를 만드는 공장.**

    🔴 재생마다 새로 만든다 — 같은 판을 돌려 쓰면 "새 초기 상태에서 다시
    밟았다" 가 거짓이 된다 (6-AI §5).
    """
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
        return setup

    return make


@pytest.fixture(scope="module")
def goal():
    return FieldGoal(card_id=GALATEA, seat=P0)


@pytest.fixture(scope="module")
def searcher(goal):
    return BoundedSearch(
        goal=goal,
        budget=SearchBudget(max_depth=6, max_nodes=400, max_results=3),
    )


@pytest.fixture(scope="module")
def collected(searcher, opening):
    """
    실제 카드 입력에서 **서로 다른 결과 셋을 모은다 (재생은 끄고).**

    모듈 범위인 이유는 하나 — 이 탐색 한 번이 30초에 가깝다. 🔴 결과를
    공유하지만 **판을 공유하지 않는다**: 요약은 값이고, 재생은 아래
    시험들이 ``opening()`` 으로 **새로 만든** 판에서 한다.
    """
    outcome = searcher.run_many(opening().duel, rerun=False)
    assert outcome.found >= 2, outcome.describe_ko()
    #: 🔴 재생을 끈 것이므로 **검증된 결과가 하나도 없다** — 그리고 그
    #: 사실이 "시간이 없었다" 와 구분된다 (§C).
    assert outcome.tally.disabled == outcome.found
    assert not outcome.not_started_results
    return outcome


def _ledger_of(outcome) -> "bs._Ledger":
    """
    모은 결과를 **production 재생 고리가 받는 모양**으로 담는다.

    🔴 **경로와 자원 요약은 실제 카드 탐색이 만든 것 그대로다.** 여기서
    새로 만드는 것은 담는 그릇(:class:`~agent.bounded_search._Ledger`)뿐이고,
    :meth:`~agent.bounded_search.BoundedSearch.rerun_results` 는
    production 그대로 돈다.
    """
    ledger = bs._Ledger()
    for result in outcome.results:
        ledger.results.append(
            (result.path, result.resources, result.goal_reason)
        )
    return ledger


# ======================================================================
# A. 공유 재생 마감
# ======================================================================
def test_a01_an_expired_deadline_never_calls_the_rerun(
    monkeypatch, searcher, opening, collected
):
    """
    🔴 **시작 전에 이미 만료됐으면 재생 함수가 불리지 않는다** (§D-시간-1).

    기준 코드(6-AI)에서는 마감을 **결과를 시작하기 전에만** 봤으므로 이
    경우는 이미 막혀 있었다 — 이 시험은 그 동작을 **잃지 않았다**는 쪽을
    센다.
    """
    clock = _Clock()
    deadline = RerunDeadline(limit=1.0, clock=clock)
    clock.advance(10.0)  # 🔴 가상 시계다 — 실제로 10초를 쓰지 않았다.

    calls = []
    real = bs.rerun_steps

    def spy(*args, **kwargs):  # pragma: no cover - 불리면 시험이 깨진다
        calls.append(kwargs.get("expect_hash"))
        return real(*args, **kwargs)

    monkeypatch.setattr(bs, "rerun_steps", spy)
    ledger = _ledger_of(collected)
    results = searcher.rerun_results(opening().duel, ledger, deadline=deadline)

    assert calls == []
    assert len(results) == collected.found
    assert all(result.rerun is None for result in results)
    assert all(result.rerun_state is RerunState.NOT_STARTED
               for result in results)
    #: 🔴 **경로는 그대로 남는다** — 재생을 못 한 것이 경로를 지우지 않는다.
    assert all(result.path for result in results)
    assert any("max_rerun_seconds" in line
               for line in ledger.rerun_budget_hit)
    assert not ledger.budget_hit, "🔴 탐색 쪽 사유와 섞지 않는다"


@pytest.fixture(scope="module")
def check_points(searcher, opening, collected, goal):
    """
    실제 카드 경로에서 **마감을 보는 자리가 몇 곳인지** 센다.

    🔴 **자리 수를 손으로 적지 않는다.** 필수 걸음이 몇 번 도는지는 엔진이
    정하므로, 적어 두면 엔진이 바뀔 때 시험이 거짓이 된다. 그래서 한 번
    재생해 보고 **시계를 읽은 횟수**를 센다.
    """
    result = collected.results[0]
    probe = _Clock()
    deadline = RerunDeadline(limit=1e9, clock=probe)
    rerun = rerun_steps(
        opening().duel, result.path, goal,
        expect_field=result.resources.own_field_rows,
        expect_hash=result.resources.state_hash,
        deadline=deadline,
    )
    assert rerun.ok, rerun.reason
    assert not rerun.timed_out
    #: 생성(1) + 경로 시작 전(1) + 걸음마다 여러 곳 + 최종(1).
    assert probe.reads >= 2 + 2 * len(result.path)
    return result, probe.reads


def test_a02_every_check_point_stops_the_rerun(
    opening, goal, check_points
):
    """
    🔴 **어느 자리에서 만료되든 재생이 멈추고, 성공이 되지 않는다**
    (§D-시간-2 · 3 · 4 · 5).

    마감을 보는 **모든 자리**를 차례로 겨눈다 — 경로 시작 전, 각 행동 앞,
    필수 걸음 반복의 경계, 각 행동 뒤, 최종 검증과 자원 요약 뒤. 자리마다
    가상 시계를 마감 뒤로 **점프**시키고, 그 재생이

    * ``timed_out`` 이고 ``ok`` 가 아니며,
    * 밟은 걸음이 경로 전체를 넘지 않고,
    * 어느 단계에서 멈췄는지(``stage``) 를 적는가

    를 센다. 🔴 **마지막 행동과 최종 검증도 포함한다** — 거기서 넘긴 경우를
    놓치면 "시간을 넘겼는데 검증 성공" 이 된다.
    """
    result, reads = check_points
    stages = []
    walked = []
    for index in range(2, reads + 1):
        clock = _Clock(jump_at=index, jump=10.0)
        deadline = RerunDeadline(limit=1.0, clock=clock)
        rerun = rerun_steps(
            opening().duel, result.path, goal,
            expect_field=result.resources.own_field_rows,
            expect_hash=result.resources.state_hash,
            deadline=deadline,
        )
        assert rerun.timed_out, (index, rerun.reason)
        assert not rerun.ok, (index, rerun.reason)
        assert rerun.steps <= len(result.path), (index, rerun.steps)
        assert rerun.stage, index
        stages.append(rerun.stage)
        walked.append(rerun.steps)

    #: 🔴 네 종류의 자리가 **모두** 겨눠졌다.
    assert stages[0] == "경로 시작 전"
    assert any(stage.endswith("앞") for stage in stages)
    assert any(stage.endswith("뒤") for stage in stages)
    assert any("필수 걸음" in stage for stage in stages)
    assert stages[-1] == "최종 검증 · 자원 요약 뒤"
    #: 🔴 **마지막 행동을 밟은 뒤에도 잡힌다** — 경로를 끝까지 밟고 나서
    #: 넘긴 시간 초과가 있다 (여기서 놓치면 "시간을 넘겼는데 검증 성공" 이
    #: 된다).
    assert max(walked) == len(result.path)


def test_a03_the_forced_step_loop_stops_at_a_safe_boundary(
    opening, goal
):
    """
    🔴 **필수 처리 반복은 안전한 경계에서 멈춘다** (§D-시간-3).

    :func:`~agent.bounded_search._settle` 를 **직접** 부른다 (production
    함수 그대로). 이미 만료된 마감을 주면 패스를 **하나도 적용하지 않고**
    ``timed_out`` 으로 돌아온다 — 돌고 있는 ``apply`` 를 끊는 것이 아니라
    **다음 걸음을 시작하지 않는** 방식이다.
    """
    duel = opening().duel
    before = duel.state.state_hash()
    clock = _Clock()
    deadline = RerunDeadline(limit=1.0, clock=clock)
    clock.advance(10.0)

    settled = bs._settle(duel, P0, deadline=deadline)
    assert settled.timed_out
    assert settled.forced == ()
    #: 🔴 막힌 것이 아니다 — 시간이 끝난 것이다. 두 사실을 섞지 않는다.
    assert settled.blocked == ()
    #: 🔴 **아무것도 밟지 않았으므로 판이 그대로다.**
    assert duel.state.state_hash() == before

    #: 마감을 주지 않으면 기본 동작이 그대로다 (6-AI 와 같다).
    plain = bs._settle(opening().duel, P0)
    assert plain.timed_out is False


def test_a04_one_deadline_is_shared_by_every_result(
    searcher, opening, collected
):
    """
    🔴 **여러 결과가 재생 예산 하나를 돌려 쓴다** (§D-시간-7 · 6).

    시계를 **읽을 때마다** 0.6초씩 흐르게 하고 마감을 1.0초로 둔다. 결과
    하나를 재생하는 동안 시계를 여러 번 읽으므로 **첫 결과에서 예산이
    끝나고**, 뒤의 결과는 **시작조차 하지 않는다.**

    🔴 결과마다 예산을 새로 시작했다면 뒤의 결과도 모두 돌았을 것이다 —
    그 사실을 ``not_started`` 수로 센다. 그리고 **그때까지 모은 결과와
    경로는 그대로 보존된다.**
    """
    clock = _Clock(step=0.6)
    deadline = RerunDeadline(limit=1.0, clock=clock)
    ledger = _ledger_of(collected)
    results = searcher.rerun_results(opening().duel, ledger, deadline=deadline)

    outcome = searcher._many_outcome(
        Termination.BUDGET_EXCEEDED, ledger, 0.0, 0.0, results
    )
    assert outcome.found == collected.found
    assert outcome.tally.total == outcome.found
    assert outcome.tally.not_started >= 1
    assert outcome.tally.verified == 0
    #: 🔴 첫 결과는 **시작했고** 뒤의 결과는 **시작하지 못했다** — 두
    #: 사실이 구분된다.
    assert results[0].rerun_state is RerunState.TIMED_OUT
    assert results[-1].rerun_state is RerunState.NOT_STARTED
    #: 🔴 경로는 하나도 사라지지 않는다.
    assert all(result.path for result in results)
    #: 🔴 재생 쪽 사유만 적힌다.
    assert outcome.rerun_budget_hit
    assert not outcome.budget_hit


def test_a05_a_verified_result_survives_a_later_timeout(
    monkeypatch, searcher, opening, collected
):
    """
    🔴 **첫 결과가 시간 안에 성공하면 그 성공을 보존한다** (§D-시간-6).

    첫 결과는 마감 안에서 **production 재생**으로 검증하고, 두 번째
    재생이 시작된 뒤에 가상 시계를 마감 밖으로 보낸다. 그러면

    * 첫 결과는 **검증 성공으로 남고**,
    * 두 번째는 **시작했지만 시간이 끝난** 것(``TIMED_OUT``)이 되고,
    * 남은 결과는 **시작조차 못 한** 것(``NOT_STARTED``)이 된다.

    🔴 세 상태가 **서로 다른 사실**이고, 앞의 성공은 뒤의 초과에 지워지지
    않는다.
    """
    clock = _Clock()
    deadline = RerunDeadline(limit=100.0, clock=clock)
    real = bs.rerun_steps
    seen = []

    def staged(*args, **kwargs):
        seen.append(1)
        if len(seen) == 2:
            #: 🔴 두 번째 재생이 **시작한 뒤** 가상 시계를 마감 밖으로
            #: 보낸다 (실제로 1000초를 쓴 것이 아니다).
            clock.advance(1000.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(bs, "rerun_steps", staged)
    ledger = _ledger_of(collected)
    results = searcher.rerun_results(opening().duel, ledger, deadline=deadline)

    assert len(seen) == 2, "🔴 세 번째 결과는 시작하지 않았다"
    assert results[0].rerun_state is RerunState.VERIFIED
    assert results[0].verified
    assert results[1].rerun_state is RerunState.TIMED_OUT
    assert results[1].rerun is not None and results[1].rerun.stage
    assert all(result.rerun_state is RerunState.NOT_STARTED
               for result in results[2:])
    outcome = searcher._many_outcome(
        Termination.BUDGET_EXCEEDED, ledger, 0.0, 0.0, results
    )
    assert outcome.tally.verified == 1
    assert outcome.tally.timed_out == 1
    assert outcome.tally.not_started == outcome.found - 2
    assert outcome.tally.total == outcome.found
    assert len(outcome.verified_results) == 1


def test_a06_a_slow_single_call_cannot_pass_as_verified(
    monkeypatch, searcher, opening, collected
):
    """
    🔴 **외부 검토의 A 재현 그대로** — 재생 예산 1초, 재생 함수가 가상
    시계를 10초 진행하고 **정상 결과를 반환**한다.

    기준 코드(6-AI)는 ``verified=True`` 를 내놓고 재생 예산 기록도 남기지
    않았다. 협력적 제한이므로 **돌고 있던 호출 하나는 끊지 않지만**, 그
    호출이 반환한 자리에서 초과를 보고 **성공 처리를 막는다.**

    🔴 이것은 가상 시계와 대체 재생 함수를 쓴 **격리 재현**이다 — 실제 카드
    전개가 1초 예산에서 10초를 썼다는 뜻이 아니다.
    """
    clock = _Clock()
    deadline = RerunDeadline(limit=1.0, clock=clock)

    def slow(duel, path, target, *, expect_field=(), expect_hash="",
             deadline=None):
        clock.advance(10.0)  # 🔴 가상 시계다.
        return RerunResult(
            ok=True, reason="[주입] 정상 결과를 반환했다", steps=len(path),
            goal_reached=True, matches_search=True,
            final_field=expect_field, final_state_hash=expect_hash,
            resources=collected.results[0].resources,
        )

    monkeypatch.setattr(bs, "rerun_steps", slow)
    ledger = _ledger_of(collected)
    results = searcher.rerun_results(opening().duel, ledger, deadline=deadline)

    first = results[0]
    assert first.verified is False
    assert first.rerun.timed_out is True
    assert first.rerun.ok is False
    assert first.rerun_state is RerunState.TIMED_OUT
    #: 🔴 먼저 적힌 판정을 **지우지 않는다** — 이유에 함께 남는다.
    assert "[주입] 정상 결과를 반환했다" in first.rerun.reason
    assert any("max_rerun_seconds" in line
               for line in ledger.rerun_budget_hit)
    #: 🔴 뒤의 결과는 시작하지 않는다.
    assert all(result.rerun_state is RerunState.NOT_STARTED
               for result in results[1:])


def test_a07_an_observed_mismatch_is_not_relabelled_as_a_timeout(
    monkeypatch, searcher, opening, collected
):
    """
    🔴 **실제로 본 불일치를 시간 초과로 덮어쓰지 않는다.**

    덮으면 "재현되지 않는 경로" 가 "시간이 없었다" 로 바뀌어, 재생이 밝힌
    사실이 사라진다. 성공만 막는다.
    """
    clock = _Clock()
    deadline = RerunDeadline(limit=1.0, clock=clock)

    def mismatch(duel, path, target, *, expect_field=(), expect_hash="",
                 deadline=None):
        clock.advance(10.0)
        return RerunResult(
            ok=False, reason="[주입] 최종 판이 달랐다", steps=len(path),
            goal_reached=True, matches_search=False,
        )

    monkeypatch.setattr(bs, "rerun_steps", mismatch)
    results = searcher.rerun_results(
        opening().duel, _ledger_of(collected), deadline=deadline
    )
    assert results[0].rerun_state is RerunState.MISMATCHED
    assert results[0].rerun.timed_out is False
    assert "[주입] 최종 판이 달랐다" in results[0].rerun.reason


def test_a08_the_boundary_is_expired_when_exactly_equal():
    """
    🔴 **마감과 정확히 같은 순간은 만료로 본다** (§D-시간-8).

    한쪽으로 고정해 두지 않으면 "같을 때" 가 구현마다 달라진다.
    """
    clock = _Clock()
    deadline = RerunDeadline(limit=1.0, clock=clock)
    assert deadline.expired() is False
    clock.advance(0.999)
    assert deadline.expired() is False
    clock.advance(0.001)  # 정확히 1.0
    assert deadline.spent == pytest.approx(1.0)
    assert deadline.expired() is True
    #: 넘어서도 만료다.
    clock.advance(5.0)
    assert deadline.expired() is True


def test_a09_the_deadline_refuses_nonsense():
    """🔴 **마감 값을 지어내지 않는다** — 수가 아니거나 0 이하면 거절한다."""
    for bad in (0, -1.0, True, "1", None):
        with pytest.raises(BoundedSearchError):
            RerunDeadline(limit=bad)
    with pytest.raises(BoundedSearchError):
        RerunDeadline(limit=1.0, clock=object())
    #: 🔴 ``rerun_results`` 도 아무 물건이나 받지 않는다.
    search = BoundedSearch(
        goal=FieldGoal(card_id=GALATEA, seat=P0),
        budget=SearchBudget(max_results=2),
    )
    with pytest.raises(BoundedSearchError):
        search.rerun_results(object(), bs._Ledger(), deadline=object())


def test_a10_the_default_single_path_rerun_has_no_deadline():
    """
    🔴 **기존 호출 방식과 기본 동작을 유지한다** (§A 마지막 줄).

    단일 경로 재생(:func:`~agent.bounded_search.rerun_path` ·
    :func:`~agent.bounded_search.rerun_steps`) 에 시간 제한이 **없었고,
    지금도 기본은 없다.** 인자는 **맨 뒤의 선택 인자**다.
    """
    import inspect

    for function in (bs.rerun_path, bs.rerun_steps):
        parameters = inspect.signature(function).parameters
        assert list(parameters)[-1] == "deadline"
        assert parameters["deadline"].default is None
        assert parameters["deadline"].kind is inspect.Parameter.KEYWORD_ONLY
    #: ``_settle`` 도 같다 — 주지 않으면 6-AI 와 한 글자도 다르지 않다.
    settle = inspect.signature(bs._settle).parameters
    assert settle["deadline"].default is None
    #: ``run_many`` 와 ``rerun_results`` 도 맨 뒤의 선택 인자다.
    assert list(inspect.signature(
        BoundedSearch.run_many).parameters)[-1] == "deadline"
    assert list(inspect.signature(
        BoundedSearch.rerun_results).parameters)[-1] == "deadline"


def test_a11_search_and_rerun_reasons_are_never_mixed(searcher, collected):
    """
    🔴 **탐색 시간과 재생 시간, 각각의 종료 사유를 혼용하지 않는다**
    (§A-9).

    기준 코드(6-AI)는 두 사유를 ``budget_hit`` **한 칸**에 담았다 — 그러면
    "재생 시간이 끝났다" 가 "탐색 범위를 끝까지 펼치지 못했다" 로 읽힌다.
    """
    ledger = _ledger_of(collected)
    ledger.stack_emptied = True
    ledger.note(ledger.rerun_budget_hit, "max_rerun_seconds=1")
    outcome = searcher._many_outcome(Termination.EXHAUSTED, ledger, 1.0, 2.0)

    assert outcome.rerun_budget_hit == ("max_rerun_seconds=1",)
    assert outcome.budget_hit == ()
    #: 🔴 재생 예산이 끊긴 것이 **탐색 소진 판정을 뒤집지 않는다.**
    assert outcome.search_exhausted is True
    assert outcome.search_seconds == 1.0
    assert outcome.rerun_seconds == 2.0


# ======================================================================
# B. 결과별 예외 격리
# ======================================================================
def _raise_once(error, *, real):
    """첫 호출만 터지고 그 뒤에는 production 재생을 그대로 쓴다."""
    state = {"n": 0}

    def wrapped(*args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise error
        return real(*args, **kwargs)

    return wrapped, state


def test_b01_a_runtime_error_in_the_first_result_does_not_stop_the_rest(
    monkeypatch, searcher, opening, collected
):
    """
    🔴 **첫 결과의 ``RuntimeError`` 뒤에 두 번째 정상 결과가 검증된다**
    (§D-예외-1).

    기준 코드(6-AI)는 ``BoundedSearchError`` **만** 결과별 실패로 받았고,
    그 밖의 예외는 호출자까지 올라가 **두 번째 결과가 재생되지 않았다.**
    """
    real = bs.rerun_steps
    wrapped, state = _raise_once(RuntimeError("[주입] 재생이 터졌다"),
                                 real=real)
    monkeypatch.setattr(bs, "rerun_steps", wrapped)

    ledger = _ledger_of(collected)
    results = searcher.rerun_results(opening().duel, ledger)

    assert state["n"] == collected.found, "🔴 남은 결과를 모두 재생했다"
    assert results[0].rerun_state is RerunState.ERRORED
    assert results[0].rerun.error_type == "RuntimeError"
    assert results[0].rerun.stage
    assert not results[0].verified
    #: 🔴 뒤의 결과들은 **새 초기 상태에서** 정상으로 검증된다.
    assert all(result.rerun_state is RerunState.VERIFIED
               for result in results[1:])
    #: 🔴 예외를 조용히 삼키지 않는다 — 진단이 남는다.
    assert any("RuntimeError" in note for note in ledger.rerun_notes)


def test_b02_a_value_error_in_the_middle_keeps_both_neighbours(
    monkeypatch, searcher, opening, collected
):
    """
    🔴 **중간 결과의 ``ValueError`` 가 앞뒤 결과를 지우지 않는다**
    (§D-예외-2).
    """
    if collected.found < 3:
        pytest.skip(f"결과가 {collected.found}개뿐이다 (가운데가 없다)")
    real = bs.rerun_steps
    calls = {"n": 0}

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("[주입] 가운데 결과만 터진다")
        return real(*args, **kwargs)

    monkeypatch.setattr(bs, "rerun_steps", wrapped)
    ledger = _ledger_of(collected)
    results = searcher.rerun_results(opening().duel, ledger)
    outcome = searcher._many_outcome(
        Termination.EXHAUSTED, ledger, 0.0, 0.0, results
    )

    assert [result.rerun_state for result in results][1] is RerunState.ERRORED
    assert results[0].rerun_state is RerunState.VERIFIED
    assert results[2].rerun_state is RerunState.VERIFIED
    assert outcome.tally.errored == 1
    assert outcome.tally.verified == collected.found - 1
    assert outcome.tally.total == outcome.found
    assert outcome.errored_results[0].rerun.error_type == "ValueError"


def test_b03_an_error_while_summarising_stays_on_that_result(
    monkeypatch, searcher, opening, collected
):
    """
    🔴 **최종 상태 확인 · 자원 요약 단계의 예외도 그 결과에만 남는다**
    (§D-예외-3).

    여기서 격리하는 것은 ``summarize_resources`` 하나다 — 재생 반복문과
    결과별 경계는 production 그대로 돈다.
    """
    real_summary = bs.summarize_resources
    calls = {"n": 0}

    def wrapped(duel, seat):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("[주입] 자원 요약이 터졌다")
        return real_summary(duel, seat)

    monkeypatch.setattr(bs, "summarize_resources", wrapped)
    ledger = _ledger_of(collected)
    results = searcher.rerun_results(opening().duel, ledger)

    assert results[0].rerun_state is RerunState.ERRORED
    assert results[0].rerun.error_type == "RuntimeError"
    assert all(result.rerun_state is RerunState.VERIFIED
               for result in results[1:])


def test_b04_an_error_does_not_restart_the_budget(
    monkeypatch, searcher, opening, collected
):
    """
    🔴 **예외 이후 재생 예산이 소진됐다면 다음 결과는 시작하지 않는다**
    (§D-예외-4).
    """
    clock = _Clock()
    deadline = RerunDeadline(limit=10.0, clock=clock)

    def boom(*args, **kwargs):
        clock.advance(100.0)  # 🔴 가상 시계다.
        raise RuntimeError("[주입] 터지면서 시간도 다 썼다")

    monkeypatch.setattr(bs, "rerun_steps", boom)
    ledger = _ledger_of(collected)
    results = searcher.rerun_results(opening().duel, ledger, deadline=deadline)

    assert results[0].rerun_state is RerunState.ERRORED
    assert all(result.rerun_state is RerunState.NOT_STARTED
               for result in results[1:])
    #: 🔴 예외와 시간 초과가 **서로 다른 이유**로 적힌다.
    assert any("RuntimeError" in note for note in ledger.rerun_notes)
    assert any("시작하지 못했습니다" in note for note in ledger.rerun_notes)


def test_b05_a_failed_rerun_never_leaks_its_state_to_the_next(
    monkeypatch, searcher, opening, collected
):
    """
    🔴 **실패한 재생의 중간 상태를 다음 결과의 초기 상태로 쓰지 않는다**
    (§D-예외-5).

    받은 판의 해시를 재생 **전후**로 재고, 각 재생이 **같은 초기 해시**에서
    시작했는지 센다.
    """
    duel = opening().duel
    before = duel.state.state_hash()
    seen_starts = []
    real = bs.rerun_steps

    def wrapped(given, path, target, **kwargs):
        seen_starts.append(given.state.state_hash())
        if len(seen_starts) == 1:
            raise RuntimeError("[주입] 첫 결과만 터진다")
        return real(given, path, target, **kwargs)

    monkeypatch.setattr(bs, "rerun_steps", wrapped)
    searcher.rerun_results(duel, _ledger_of(collected))

    assert len(set(seen_starts)) == 1, seen_starts
    assert seen_starts[0] == before
    #: 🔴 **원본도 변하지 않는다.**
    assert duel.state.state_hash() == before


@pytest.mark.parametrize("signal", [KeyboardInterrupt, SystemExit])
def test_b06_exit_signals_are_never_swallowed(
    monkeypatch, searcher, opening, collected, signal
):
    """
    🔴 **종료 신호를 결과 실패로 삼키지 않는다** (§D-예외-6).

    삼키면 "멈춰라" 가 사라진다. ``except Exception`` 이므로
    ``BaseException`` 의 직계인 이 둘은 그대로 올라간다.
    """
    def boom(*args, **kwargs):
        raise signal("[주입] 종료 신호")

    monkeypatch.setattr(bs, "rerun_steps", boom)
    with pytest.raises(signal):
        searcher.rerun_results(opening().duel, _ledger_of(collected))


def test_b07_the_rerun_boundary_never_catches_baseexception():
    """
    🔴 **``BaseException`` 전체를 잡는 방식을 쓰지 않는다** (§B-9).

    ``agent/bounded_search.py`` 전체에 벌거벗은 ``except:`` 도,
    ``except BaseException`` 도 없다. 그리고 예외 경계는 **복수 결과 재생에
    필요한 범위로 한정한다** — ``except Exception`` 을 쓰는 자리는
    :meth:`~agent.bounded_search.BoundedSearch._rerun_one` 과, 6-AH 부터
    있던 :func:`~agent.bounded_search.rerun_steps` · ``_apply_once`` 의
    한 수 적용 자리뿐이다.
    """
    source = io.open("agent/bounded_search.py", encoding="utf-8").read()
    tree = ast.parse(source)
    broad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is None:
            broad.append(("bare", node.lineno))
            continue
        names = {
            inner.id for inner in ast.walk(node.type)
            if isinstance(inner, ast.Name)
        }
        if "BaseException" in names:
            broad.append(("BaseException", node.lineno))
    assert broad == [], broad

    #: ``except Exception`` 을 쓰는 함수의 **이름을 고정한다** — 범위가
    #: 번지면 이 단정이 깨진다.
    holders = set()
    for parent in ast.walk(tree):
        if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(parent):
            if not isinstance(node, ast.ExceptHandler) or node.type is None:
                continue
            names = {
                inner.id for inner in ast.walk(node.type)
                if isinstance(inner, ast.Name)
            }
            if "Exception" in names:
                holders.add(parent.name)
    assert holders == {"_rerun_one", "rerun_steps", "_apply_once"}, holders


def test_b08_an_error_is_never_turned_into_nothing_found(
    monkeypatch, searcher, opening, collected
):
    """
    🔴 **오류를 "탐색 미발견" · UNKNOWN · 정상 무효과 해결로 바꾸지
    않는다** (§B-5 · 8).
    """
    def boom(*args, **kwargs):
        raise RuntimeError("[주입] 전부 터진다")

    monkeypatch.setattr(bs, "rerun_steps", boom)
    ledger = _ledger_of(collected)
    results = searcher.rerun_results(opening().duel, ledger)
    outcome = searcher._many_outcome(
        Termination.EXHAUSTED, ledger, 0.0, 0.0, results
    )

    #: 🔴 **찾은 경로 수는 줄지 않는다.**
    assert outcome.found == collected.found
    assert outcome.reached is True
    assert outcome.tally.errored == outcome.found
    assert outcome.tally.verified == 0
    #: 🔴 탐색 쪽 오류 칸에 섞어 넣지도 않는다 (거기는 탐색의 오류다).
    assert outcome.errors == ()
    #: 🔴 성공 기본값으로 바꾸지 않는다.
    assert all(result.rerun.ok is False for result in results)
    assert all(result.rerun.error_type == "RuntimeError"
               for result in results)


def test_b09_a_bounded_search_error_is_still_a_per_result_failure(
    monkeypatch, searcher, opening, collected
):
    """
    🔴 6-AI 부터 있던 ``BoundedSearchError`` 경계가 **그대로**다 — 그리고
    이제 형 이름과 단계가 함께 적힌다.
    """
    def boom(*args, **kwargs):
        raise BoundedSearchError("[주입] 정리되지 않은 자리")

    monkeypatch.setattr(bs, "rerun_steps", boom)
    results = searcher.rerun_results(opening().duel, _ledger_of(collected))
    assert all(result.rerun_state is RerunState.ERRORED
               for result in results)
    assert all(result.rerun.error_type == "BoundedSearchError"
               for result in results)


# ======================================================================
# C. 상태 · 집계 · 출력
# ======================================================================
def _stub_result(index, resources, *, state):
    """상태만 다른 :class:`PathResult` — 집계와 출력을 재는 데 쓴다."""
    if state is RerunState.DISABLED:
        return PathResult(index=index, path=(), resources=resources,
                          goal_reason="[스텁]", rerun_disabled=True)
    if state is RerunState.NOT_STARTED:
        return PathResult(index=index, path=(), resources=resources,
                          goal_reason="[스텁]")
    rerun = {
        RerunState.VERIFIED: RerunResult(ok=True, reason="[스텁] 성공",
                                         resources=resources),
        RerunState.MISMATCHED: RerunResult(ok=False, reason="[스텁] 어긋남"),
        RerunState.ERRORED: RerunResult(ok=False, reason="[스텁] 예외",
                                        error_type="RuntimeError",
                                        stage="재생 호출"),
        RerunState.TIMED_OUT: RerunResult(ok=False, reason="[스텁] 시간 초과",
                                          timed_out=True, stage="행동 2 앞"),
    }[state]
    return PathResult(
        index=index, path=(), resources=resources, goal_reason="[스텁]",
        rerun=rerun, resources_match=(state is RerunState.VERIFIED),
    )


def test_c01_every_state_is_counted_exactly_once(collected):
    """
    🔴 **여섯 상태가 구분되고 집계가 맞아떨어진다** (§C).

    하나라도 어느 칸에도 들어가지 않으면 결과가 조용히 사라진 것이다.
    """
    resources = collected.results[0].resources
    states = list(RerunState)
    assert len(states) == 6
    results = tuple(
        _stub_result(number + 1, resources, state=state)
        for number, state in enumerate(states)
    )
    assert [result.rerun_state for result in results] == states

    outcome = dataclasses.replace(collected, results=results)
    tally = outcome.tally
    assert tally.total == outcome.found == 6
    assert (tally.verified, tally.mismatched, tally.errored,
            tally.timed_out, tally.not_started, tally.disabled) == (
        1, 1, 1, 1, 1, 1
    )
    assert tally.ran == 4
    assert tally.incomplete == 3
    #: 🔴 **검증된 비교에는 검증 성공만 들어간다.**
    assert len(outcome.verified_results) == 1
    assert len(outcome.timed_out_results) == 1
    assert len(outcome.errored_results) == 1
    assert len(outcome.not_started_results) == 1
    assert len(outcome.disabled_results) == 1
    assert len(outcome.mismatched_results) == 1
    #: 🔴 **경로를 찾았다는 사실은 재생 결과에 따라 줄지 않는다.**
    assert outcome.reached is True


def test_c02_an_empty_tally_is_consistent():
    """결과가 없으면 모든 칸이 0 이다 (수가 맞아떨어진다)."""
    tally = ResultTally()
    assert (tally.total, tally.ran, tally.incomplete) == (0, 0, 0)
    assert "검증 0" in tally.describe_ko()


def test_c03_the_report_tells_the_reasons_apart(repository, collected):
    """
    🔴 **시간 초과와 예외를 서로 다른 이유로 표시한다** (§C).

    그리고 하나가 실패해도 **정상 검증된 다른 결과의 비교표는 유지된다.**
    """
    from deck import report

    resources = [result.resources for result in collected.results]
    results = (
        _stub_result(1, resources[0], state=RerunState.VERIFIED),
        _stub_result(2, resources[1], state=RerunState.VERIFIED),
        _stub_result(3, resources[-1], state=RerunState.ERRORED),
    )
    outcome = dataclasses.replace(collected, results=results)
    detail = report.render_multi_search(outcome, repository)

    assert "일반 실행 예외" in detail
    assert "RuntimeError" in detail
    #: 🔴 검증된 둘의 비교표가 그대로 있다.
    head, _, tail = detail.partition("결과들의 차이 (검증된 것만)")
    assert "결과 1 대비 결과 2" in tail
    assert "결과 3" not in tail.split("\n\n")[0]
    #: 🔴 실패한 결과의 **경로와 자원도 사라지지 않는다.**
    assert "[결과 3]" in head

    timed = dataclasses.replace(
        outcome,
        results=(results[0], results[1],
                 _stub_result(3, resources[-1], state=RerunState.TIMED_OUT)),
    )
    timed_detail = report.render_multi_search(timed, repository)
    assert "공유 재생 마감을 넘긴 자리" in timed_detail
    assert "RuntimeError" not in timed_detail
    #: 🔴 두 사유의 **말이 다르다.**
    assert "일반 실행 예외" not in timed_detail


def test_c04_not_started_and_disabled_are_told_apart(repository, collected):
    """🔴 **시간 부족으로 미시작**과 **재생을 끈 것**을 가른다 (§C)."""
    from deck import report

    resources = collected.results[0].resources
    outcome = dataclasses.replace(collected, results=(
        _stub_result(1, resources, state=RerunState.NOT_STARTED),
        _stub_result(2, resources, state=RerunState.DISABLED),
    ))
    detail = report.render_multi_search(outcome, repository)
    assert "시작하지 못했습니다" in detail
    assert "끄고" in detail
    assert outcome.tally.not_started == 1
    assert outcome.tally.disabled == 1


def test_c05_the_brief_stays_short_and_the_detail_carries_the_reason(
    repository, collected
):
    """
    🔴 **기본 응답은 간결하게, 결과별 상세 사유는 첨부 기록에** (§C).

    요약에는 상태 한 줄만 적고, 예외 형 이름과 단계는 **상세에만** 적는다.
    """
    from deck import report

    resources = collected.results[0].resources
    outcome = dataclasses.replace(collected, results=(
        _stub_result(1, resources, state=RerunState.VERIFIED),
        _stub_result(2, resources, state=RerunState.ERRORED),
    ))
    brief = report.render_multi_search_brief(outcome, repository)
    detail = report.render_multi_search(outcome, repository)

    assert "일반 실행 예외" in brief, "요약도 이유는 밝힌다"
    assert "단계 재생 호출" not in brief, "🔴 상세 사유는 요약에 넣지 않는다"
    assert "단계 재생 호출" in detail
    assert len(brief.splitlines()) < len(detail.splitlines())
    #: 🔴 **찾은 경로가 사라지지 않았다는 말이 요약에 있다.**
    assert "찾은 경로" in brief


def test_c06_the_brief_marks_an_unverified_comparison(repository, collected):
    """
    🔴 **검증된 결과가 없을 때 비교표를 "검증된 비교" 로 적지 않는다** (§C).
    """
    from deck import report

    resources = [result.resources for result in collected.results]
    outcome = dataclasses.replace(collected, results=(
        _stub_result(1, resources[0], state=RerunState.TIMED_OUT),
        _stub_result(2, resources[1], state=RerunState.TIMED_OUT),
    ))
    brief = report.render_multi_search_brief(outcome, repository)
    assert "검증되지 않은 결과입니다" in brief
    assert "검증된 서로 다른 결과 0개" in brief


def test_c07_the_rerun_budget_line_is_separate_in_the_report(
    repository, collected, searcher
):
    """🔴 **탐색 예산과 재생 예산의 줄을 따로 적는다** (§A-9)."""
    from deck import report

    ledger = _ledger_of(collected)
    ledger.note(ledger.rerun_budget_hit, "max_rerun_seconds=1")
    outcome = searcher._many_outcome(
        Termination.EXHAUSTED, ledger, 0.0, 0.0, collected.results
    )
    brief = report.render_multi_search_brief(outcome, repository)
    assert "탐색 예산에 걸린 칸: 없음" in brief
    assert "재생 예산에 걸린 칸: max_rerun_seconds=1" in brief


# ======================================================================
# D. 실제 카드 정상 경로
# ======================================================================
@pytest.fixture(scope="module")
def verified_many(repository, draft):
    """
    실제 카드 입력의 **정상 경로** — 모으고, 각각 재생하고, 비교한다.

    🔴 어댑터가 부르는 자리(:func:`app.main.bounded_search_many_opening`)를
    그대로 쓴다. 마감은 **기본값**(예산의 ``max_rerun_seconds``)이다.
    """
    from app.main import bounded_search_many_opening
    from deck.combo_policy import ORCUST_GIRSU_LINE

    return bounded_search_many_opening(
        repository, draft, list(ORCUST_GIRSU_LINE.hand),
        card_id=GALATEA, max_results=3,
        budget=SearchBudget(max_depth=6, max_nodes=400),
    )


def test_d01_the_real_input_still_verifies_every_distinct_result(
    verified_many
):
    """
    🔴 **실제 카드 정상 경로가 그대로다** — 서로 다른 결과를 모아 각각
    재생하고 자원을 비교한다 (§D-정상).

    적어 둔 경로(``ORCUST_GIRSU_LINE``)를 **호출하지 않았다** — 거기서
    가져온 것은 레시피와 시작 패, 즉 **입력**뿐이다.
    """
    _setup, outcome = verified_many
    assert outcome is not None
    assert outcome.found >= 2, outcome.describe_ko()
    #: 🔴 전부 검증됐고, 집계가 맞아떨어진다.
    assert outcome.tally.verified == outcome.found
    assert outcome.tally.total == outcome.found
    assert outcome.tally.incomplete == 0
    assert outcome.tally.errored == 0
    assert outcome.tally.timed_out == 0
    assert not outcome.rerun_budget_hit, "🔴 재생 예산에 걸리지 않았다"
    #: 🔴 결과가 **서로 다르다** (해시로).
    hashes = {result.resources.state_hash for result in outcome.results}
    assert len(hashes) == outcome.found
    #: 🔴 재생된 상태의 자원 요약이 탐색이 적어 둔 것과 같다.
    for result in outcome.results:
        assert result.rerun is not None
        assert result.rerun.timed_out is False
        assert result.rerun.error_type == ""
        assert result.rerun.resources == result.resources
        assert result.rerun_state is RerunState.VERIFIED


def test_d02_the_single_result_mode_is_unchanged(repository, draft):
    """
    🔴 **단일 결과 모드가 그대로다** (§D-정상).

    ``run()`` 은 ``MultiSearchOutcome`` 도 재생도 거치지 않는다 — 6-AH 와
    같은 자리다.
    """
    from app.main import bounded_search_opening
    from deck.combo_policy import ORCUST_GIRSU_LINE

    setup, outcome, rerun = bounded_search_opening(
        repository, draft, list(ORCUST_GIRSU_LINE.hand),
        card_id=GALATEA,
        budget=SearchBudget(max_depth=6, max_nodes=400),
    )
    assert setup.can_run
    assert outcome is not None
    assert outcome.reached, outcome.describe_ko()
    #: 🔴 단일 결과 모드는 복수 결과의 집계를 거치지 않는다.
    assert not hasattr(outcome, "tally")
    assert not hasattr(outcome, "rerun_budget_hit")
    #: 🔴 단일 경로 재생에는 마감이 **없다** (기본 동작 유지) — 그래서
    #: 시간 초과로 적히는 일이 없다.
    assert rerun is not None
    assert rerun.ok, rerun.reason
    assert rerun.timed_out is False
    assert rerun.error_type == ""


def test_d03_the_dedup_and_choice_caps_are_unchanged(verified_many):
    """
    🔴 **깊이를 고려한 중복 제거와 선택 조합 제한이 그대로다** (§D-정상).

    6-AH 보완이 더한 수치가 여전히 집계에 남고, 재생 쪽 변경이 탐색 쪽
    수치를 건드리지 않았다.
    """
    _setup, outcome = verified_many
    for name in ("deduped", "revisited", "stale", "choice_branches",
                 "choice_plans", "choice_offers_truncated"):
        assert isinstance(getattr(outcome, name), int), name
    #: 🔴 탐색 쪽 종료 사유는 **탐색** 칸에만 적힌다.
    assert all("max_rerun" not in line for line in outcome.budget_hit)
    assert outcome.search_seconds > 0
    assert outcome.rerun_seconds > 0
