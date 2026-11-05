"""
Phase 6-AJ 후속 — **행동 실행 예외의 상태 분류**.

6-AJ 가 `RerunState` 여섯 가지와 `RerunResult.error_type` · `stage` 를
더했는데, :func:`~agent.bounded_search.rerun_steps` 안의 **행동 실행**
(``fork.apply``) 예외 분기는 6-AH 부터 있던 그대로여서 그 두 칸을 채우지
않았다. 그래서 실제 ``apply`` 예외가 `ERRORED` 가 아니라 **`MISMATCHED`**
로 집계됐다 — 성공으로 인정한 것은 아니지만, 이번에 도입한 분류가 **실제
행동 실행 예외를 놓치고** 있었다.

이 파일이 고정하는 사실은 넷이다.

======  ======================================================================
``A``   ``apply`` 가 터지면 ``error_type`` 과 ``stage`` 가 채워지고 상태가
        `ERRORED` 다. 🔴 **기존 ``reason`` 과 완료 걸음 수의 뜻은 그대로**다.
``B``   한 결과의 ``apply`` 예외가 **다른 경로를 버리지 않는다.** 예산이
        남아 있으면 다음 결과를 **원래 초기 상태**에서 계속 재생하고, 정상
        결과는 검증 성공한다. 원본 판은 변하지 않는다.
``C``   집계와 보고가 그 실패를 **예외**로 센다 — 불일치도, 검증 성공도
        아니다. 상세에 예외 종류와 발생 단계가 보인다.
``D``   ``apply`` 에서 난 ``KeyboardInterrupt`` · ``SystemExit`` 은 **상위로
        전파된다.**
======  ======================================================================

🔴 **``rerun_steps`` 를 가짜로 바꾸지 않는다.** 바꿔 끼우는 것은
``Duel.apply`` **하나**이고, 그것도 **기록된 그 행동의 열쇠일 때만** 터지게
한다(필수 걸음이 적용하는 패스에는 손대지 않는다). 재생 반복문 · 허용 후보
재조회 · 필수 걸음 처리 · 결과별 경계(``_rerun_one``) · 집계
(``_many_outcome``) · 두 렌더러는 **production 그대로** 돈다.

🔴 **실제 카드를 쓰지만 탐색을 돌리지 않는다.** 선공 판에서 엔진이 허가한
수 둘로 짧은 경로를 만들어 쓴다 — 30초짜리 탐색을 반복할 이유가 없고, 이
파일이 재는 것은 **예외 분류**이지 탐색이 아니다.

🔴 **강약 평가가 아니다.**
"""

from __future__ import annotations

import dataclasses

import pytest

import agent.bounded_search as bs
from agent.bounded_search import (
    BoundedSearch,
    FieldGoal,
    PathStep,
    RerunState,
    SearchBudget,
    Termination,
    rerun_steps,
)
from engine.duel import Duel

#: 잭나이츠 오르페골 기르수 — 선공 패의 첫 카드이고, 일반 소환으로 앞면
#: 필드에 선다. 🔴 **목표를 이것으로 둔 이유는 하나** — 두 걸음이면 닿아서
#: 긴 탐색이 필요 없다.
GIRSU = 69811710
P0 = 0

#: 선공 판에서 엔진이 내놓은 허용 후보의 열쇠들. 🔴 **지어낸 값이 아니다** —
#: 아래 ``paths`` 픅스처가 production ``rerun_steps`` 로 **실제로 밟아 보고**
#: 목표에 닿는지 확인한다(안 맞으면 픅스처가 깨진다).
SUMMON_KEY = ("normal_summon", P0, 75, (), None, None, ())
PASS_KEY = ("pass", P0, None, (), None, None, ())
SET_KEY = ("set_spell_trap", P0, 76, (), None, None, ())


# ======================================================================
# 픅스처 — 실제 카드, 탐색 없음
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


@pytest.fixture(scope="module")
def searcher(goal):
    #: 🔴 탐색을 돌리지 않는다 — ``rerun_results`` 가 보는 목표와 예산을
    #: 들고 있는 자리로만 쓴다.
    return BoundedSearch(
        goal=goal, budget=SearchBudget(max_depth=4, max_nodes=50,
                                       max_results=3),
    )


@pytest.fixture(scope="module")
def paths(opening, goal):
    """
    짧은 경로 둘과, 목표에 닿는 쪽의 **최종 판·자원 요약**.

    * ``reaching`` — 일반 소환 → 패스. 🔴 목표에 **닿는다**(소환 유발의
      발동 기회를 패스로 넘겨 자리가 정리된다).
    * ``failing_late`` — 마·함 세트 → 일반 소환. 두 번째 걸음에서 예외를
      주입해 **완료 걸음 수**가 1 인 실패를 만드는 데 쓴다.

    🔴 **production ``rerun_steps`` 로 실제로 밟아 확인한다.** 열쇠가
    틀렸다면 여기서 깨진다.
    """
    reaching = (
        PathStep(order=1, kind="normal_summon", action_key=SUMMON_KEY),
        PathStep(order=2, kind="pass", action_key=PASS_KEY),
    )
    failing_late = (
        PathStep(order=1, kind="set_spell_trap", action_key=SET_KEY),
        PathStep(order=2, kind="normal_summon", action_key=SUMMON_KEY),
    )
    clean = rerun_steps(opening(), reaching, goal)
    assert clean.ok, clean.reason
    assert clean.goal_reached and clean.steps == 2
    assert clean.resources is not None
    return reaching, failing_late, clean


@pytest.fixture
def ledger_of(paths):
    """
    모은 결과를 **production 재생 고리가 받는 모양**으로 담는다.

    🔴 새로 만드는 것은 담는 그릇뿐이고, 경로와 자원 요약은 위 픅스처가
    **실제로 밟아 얻은 것**이다.
    """
    reaching, _failing, clean = paths

    def make(count=1):
        ledger = bs._Ledger()
        for _ in range(count):
            ledger.results.append(
                (reaching, clean.resources, "[짧은 경로] 목표 도달")
            )
        return ledger

    return make


def _explode(monkeypatch, key, error, *, nth=None):
    """
    **기록된 그 행동을 적용할 때만** 터지게 한다.

    🔴 ``Duel.apply`` 를 통째로 막지 않는다 — 열쇠가 맞을 때만 터지므로,
    필수 걸음이 적용하는 패스와 다른 걸음은 그대로 돈다. 그래서 예외가
    **행동 실행 지점**에서만 들어간다.

    ``nth`` 를 주면 그 **몇 번째** 적용에서만 터진다(뒤의 결과는 정상으로
    돈다). 주지 않으면 매번 터진다.
    """
    real = Duel.apply
    hits = {"n": 0, "calls": 0}

    def patched(self, action, *args, **kwargs):
        hits["calls"] += 1
        if tuple(action.canonical_state()) == tuple(key):
            hits["n"] += 1
            if nth is None or hits["n"] == nth:
                raise error
        return real(self, action, *args, **kwargs)

    monkeypatch.setattr(Duel, "apply", patched)
    return hits


# ======================================================================
# A. 분류
# ======================================================================
def test_a01_an_apply_error_fills_the_type_and_stage(
    monkeypatch, opening, goal, paths
):
    """
    🔴 **``apply`` 예외가 예외로 적힌다** (§A).

    수정 전에는 ``error_type`` 과 ``stage`` 가 **빈 문자열**이어서, 바깥
    `_rerun_one` 이 이 결과를 `MISMATCHED` 로 분류했다.
    """
    reaching, _failing, _clean = paths
    _explode(monkeypatch, SUMMON_KEY, RuntimeError("[주입] 소환이 터졌다"))

    rerun = rerun_steps(opening(), reaching, goal)

    assert rerun.ok is False
    assert rerun.error_type == "RuntimeError"
    assert "행동 1" in rerun.stage, rerun.stage
    #: 🔴 **기존 ``reason`` 의 뜻이 그대로다** — 몇 번째 행동에서 무엇이
    #: 터졌는지 그대로 적힌다.
    assert rerun.reason.startswith("1번째 행동에서 예외가 났습니다")
    assert "RuntimeError" in rerun.reason
    assert "[주입] 소환이 터졌다" in rerun.reason
    #: 🔴 **완료 걸음 수의 뜻도 그대로다** — 첫 걸음에서 터졌으니 0 이다.
    assert rerun.steps == 0
    #: 🔴 성공도, 시간 초과도, 정상 무효과도 아니다.
    assert rerun.timed_out is False
    assert rerun.goal_reached is False
    assert rerun.matches_search is False


def test_a02_a_late_apply_error_keeps_the_completed_step_count(
    monkeypatch, opening, goal, paths
):
    """🔴 **완료 걸음 수와 단계가 몇 번째 행동인지 말한다** (§A)."""
    _reaching, failing_late, _clean = paths
    _explode(monkeypatch, SUMMON_KEY, RuntimeError("[주입] 두 번째가 터졌다"))

    rerun = rerun_steps(opening(), failing_late, goal)

    assert rerun.error_type == "RuntimeError"
    assert "행동 2" in rerun.stage, rerun.stage
    assert rerun.reason.startswith("2번째 행동에서 예외가 났습니다")
    #: 첫 걸음은 **밟았다.**
    assert rerun.steps == 1


def test_a03_the_result_is_errored_and_never_mismatched(
    monkeypatch, searcher, opening, goal, paths, ledger_of
):
    """
    🔴 **결과별 경계를 지나도 `ERRORED` 다** (§A).

    수정 전 격리 재현에서는 이 자리에서 `MISMATCHED` 가 나왔다 —
    ``error_type`` 이 비어 있어 `_rerun_one` 이 "어긋났다" 로 읽었다.
    """
    _explode(monkeypatch, SUMMON_KEY, RuntimeError("[주입] 소환이 터졌다"))
    ledger = ledger_of(1)

    results = searcher.rerun_results(opening(), ledger)

    assert len(results) == 1
    only = results[0]
    assert only.rerun_state is RerunState.ERRORED
    assert only.rerun_state is not RerunState.MISMATCHED
    assert only.verified is False
    assert only.rerun.error_type == "RuntimeError"
    assert "행동 1" in only.rerun.stage
    #: 🔴 예외를 조용히 삼키지 않는다 — 진단이 남는다.
    assert any("RuntimeError" in note for note in ledger.rerun_notes)
    #: 🔴 경로는 그대로 남는다.
    assert only.path == paths[0]


# ======================================================================
# B. 다른 결과를 버리지 않는다
# ======================================================================
def test_b01_only_the_failing_result_is_lost(
    monkeypatch, searcher, opening, goal, paths, ledger_of
):
    """
    🔴 **첫 결과의 ``apply`` 만 터지면 두 번째는 검증 성공한다** (§B).

    그리고 두 재생이 **같은 초기 상태**에서 시작하고, 받은 원본 판은 변하지
    않는다.
    """
    duel = opening()
    before = duel.state.state_hash()
    #: 🔴 **첫 번째 소환만** 터뜨린다.
    hits = _explode(monkeypatch, SUMMON_KEY,
                    RuntimeError("[주입] 첫 결과만 터진다"), nth=1)
    ledger = ledger_of(2)

    results = searcher.rerun_results(duel, ledger)
    outcome = searcher._many_outcome(
        Termination.EXHAUSTED, ledger, 0.0, 0.0, results
    )

    assert hits["n"] == 2, "🔴 두 번째 결과도 그 행동을 실행했다"
    assert results[0].rerun_state is RerunState.ERRORED
    assert results[1].rerun_state is RerunState.VERIFIED
    assert results[1].verified is True
    #: 🔴 모은 결과 수와 경로가 보존된다.
    assert outcome.found == 2
    assert all(result.path == paths[0] for result in results)
    #: 🔴 **원본 초기 상태가 변하지 않는다** — 다음 결과도 거기서 시작했다.
    assert duel.state.state_hash() == before
    assert results[1].rerun.resources == results[1].resources


# ======================================================================
# C. 집계와 보고
# ======================================================================
def test_c01_the_tally_and_report_call_it_an_exception(
    monkeypatch, repository, searcher, opening, goal, ledger_of
):
    """
    🔴 **예외 수에 들어가고, 불일치 수와 검증 수에는 들어가지 않는다**
    (§C). 상세 출력에 **예외 종류와 발생 단계**가 보인다.
    """
    from deck import report

    _explode(monkeypatch, SUMMON_KEY,
             RuntimeError("[주입] 첫 결과만 터진다"), nth=1)
    ledger = ledger_of(2)
    results = searcher.rerun_results(opening(), ledger)
    outcome = searcher._many_outcome(
        Termination.EXHAUSTED, ledger, 0.0, 0.0, results
    )

    tally = outcome.tally
    assert tally.errored == 1
    assert tally.mismatched == 0
    assert tally.verified == 1
    assert tally.total == outcome.found == 2
    assert len(outcome.errored_results) == 1
    assert not outcome.mismatched_results

    detail = report.render_multi_search(outcome, repository)
    assert "일반 실행 예외" in detail
    assert "RuntimeError" in detail
    assert "단계 행동 1" in detail, "🔴 발생 단계가 보여야 한다"
    brief = report.render_multi_search_brief(outcome, repository)
    assert "일반 실행 예외로 멈춘 결과 1개" in brief
    #: 🔴 기본 응답은 간결하게 — 단계는 상세에만 적는다.
    assert "단계 행동 1" not in brief


# ======================================================================
# D. 종료 신호
# ======================================================================
@pytest.mark.parametrize("signal", [KeyboardInterrupt, SystemExit])
def test_d01_exit_signals_from_apply_are_never_swallowed(
    monkeypatch, searcher, opening, goal, paths, ledger_of, signal
):
    """
    🔴 **``apply`` 에서 난 종료 신호를 결과 실패로 삼키지 않는다** (§D).

    ``rerun_steps`` 의 분기도, 결과별 경계도 ``except Exception`` 이므로
    ``BaseException`` 직계인 이 둘은 그대로 올라간다.
    """
    reaching, _failing, _clean = paths
    _explode(monkeypatch, SUMMON_KEY, signal("[주입] 종료 신호"))

    with pytest.raises(signal):
        rerun_steps(opening(), reaching, goal)

    with pytest.raises(signal):
        searcher.rerun_results(opening(), ledger_of(1))
