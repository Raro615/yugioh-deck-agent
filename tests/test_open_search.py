"""
Phase 6-BB — **고정 경로 없는 자율 전개 탐색**.

이 파일이 고정하는 사실은 여섯이다.

======  ======================================================================
``A``   :class:`OpenGoal` 은 **목표 카드를 지정하지 않는다** — 자신 필드에
        앞면 카드가 있고 판이 정리되면 도달이다. 빈 필드는 도달이 아니다.
``B``   **후보 풀과 제시 결과 수가 다른 칸**이다. ``max_candidates`` 를
        주지 않으면 기존 동작 그대로이고, 상한에 걸리면 **어느 칸이**
        걸렸는지가 종료 사유에 남는다.
``C``   **평가 순위 밖이라 재생하지 않은 것**과 **재생이 실패한 것**을
        가른다 (``RerunState.NOT_SELECTED``).
``D``   자율 탐색의 평가는 **필드를 축으로 센다** — 두 보존 축만 보면
        "아무것도 하지 않은 쪽" 이 언제나 이긴다.
``E``   자율 탐색 입구는 **고정 경로 정책을 부르지 않는다** (``ComboLine`` ·
        ``VerificationLinePolicy`` 가 들어오지 않는다).
``F``   디스코드 입구가 **자율 탐색과 고정 목표 탐색을 가른다**. 기존
        ``search:`` 목표와 ``line:`` 고정 경로는 그대로 돈다.
======  ======================================================================

🔴 **이 파일은 "이 패의 최적 전개" 를 고정하지 않는다.** 탐색이 무엇을
찾는지는 예산과 엔진 지원 범위가 정하고, 그것은 바뀔 수 있다. 여기서 재는
것은 **구조**다 — 목표가 없는가, 예산이 적용되는가, 평가가 무엇을 보는가,
어긋난 재실행을 성공으로 바꾸지 않는가.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent.bounded_search import (
    CANDIDATE_CAP,
    FOLLOWUP_CAP,
    BoundedSearch,
    BoundedSearchError,
    FieldGoal,
    OpenGoal,
    PathResult,
    PathStep,
    RerunState,
    SearchBudget,
)


# ======================================================================
# A. 목표 카드가 없다
# ======================================================================
def test_a01_the_open_goal_names_no_card():
    """🔴 설명에 **카드 ID 가 들어가지 않는다** — 목표를 지정하지 않는다."""
    said = OpenGoal(card_id=0, seat=0).describe_ko()
    assert "목표 카드를 지정하지 않는" in said
    assert "[0]" not in said


def test_a02_the_open_goal_is_accepted_wherever_a_field_goal_is():
    """
    🔴 **탐색기를 한 벌 더 만들지 않는다** — 같은 ``BoundedSearch`` 가 돈다.
    """
    search = BoundedSearch(goal=OpenGoal(card_id=0, seat=0))
    assert isinstance(search.goal, FieldGoal)
    assert search.goal.seat == 0


def test_a03_an_empty_field_is_not_reached(repository):
    """
    🔴 **뿌리에서 바로 끝나지 않는다** — 필드가 비어 있으면 도달이 아니다.
    그렇지 않으면 ``run_many`` 가 "받은 판이 이미 목표" 로 멈춘다.
    """
    from deck.opening import build_opening
    from deck.recipe import parse_recipe

    from app.main import opening_wiring

    draft = parse_recipe("11091375 x40", repository).draft
    chooser, triggers = opening_wiring(repository, None)
    setup = build_opening(repository, draft, [11091375] * 5,
                          chooser=chooser, triggers=triggers)
    if not setup.can_run:
        pytest.skip(f"초기 상태를 만들지 못했습니다: {setup.blockers}")
    verdict = OpenGoal(card_id=0, seat=0).judge(setup.duel)
    assert not verdict.reached and not verdict.present
    assert "앞면 카드가 없습니다" in verdict.reason


# ======================================================================
# B. 후보 풀과 제시 결과 수는 다른 칸이다
# ======================================================================
def test_b01_candidate_pool_defaults_to_the_result_count():
    """🔴 주지 않으면 **기존 동작 그대로**다."""
    budget = SearchBudget(max_results=3)
    search = BoundedSearch(goal=OpenGoal(card_id=0, seat=0), budget=budget)
    assert budget.max_candidates == 0
    assert search.candidate_cap == 3


def test_b02_candidate_pool_is_used_when_given():
    budget = SearchBudget(max_results=3, max_candidates=20)
    search = BoundedSearch(goal=OpenGoal(card_id=0, seat=0), budget=budget)
    assert search.candidate_cap == 20
    assert "후보 풀 20개" in budget.describe_ko()


def test_b03_candidate_pool_has_a_small_explicit_cap():
    with pytest.raises(BoundedSearchError) as caught:
        SearchBudget(max_candidates=CANDIDATE_CAP + 1)
    assert "max_candidates" in str(caught.value)


def test_b04_the_note_says_which_cap_stopped_it():
    """🔴 **어느 칸이 끊었는지** 적는다 — 둘을 섞지 않는다."""
    plain = BoundedSearch(goal=OpenGoal(card_id=0, seat=0),
                          budget=SearchBudget(max_results=3))
    pooled = BoundedSearch(goal=OpenGoal(card_id=0, seat=0),
                           budget=SearchBudget(max_results=3,
                                               max_candidates=9))
    assert plain._candidate_cap_note() == "max_results=3"
    assert pooled._candidate_cap_note() == "max_candidates=9"


def test_b05_the_followup_cap_is_large_enough_for_a_whole_line():
    """
    🔴 자율 탐색은 **전개 전체가 후속 행동**이다 — 3 으로 두면 세 걸음에서
    끊기고 그것이 "더 갈 수 없다" 로 읽힌다.
    """
    assert FOLLOWUP_CAP >= 6
    SearchBudget(max_results=2, max_followup_actions=FOLLOWUP_CAP)


# ======================================================================
# C. 순위 밖과 재생 실패는 다른 사실이다
# ======================================================================
def _result(index: int, *, skipped: bool = False, rerun=None,
            resources=None, path=()) -> PathResult:
    return PathResult(index=index, path=tuple(path), resources=resources,
                      goal_reason="", rerun=rerun, rerun_skipped=skipped)


def test_c01_not_selected_is_its_own_state():
    one = _result(1, skipped=True)
    assert one.rerun_state is RerunState.NOT_SELECTED
    assert not one.verified
    assert not RerunState.NOT_SELECTED.ran


def test_c02_not_selected_is_not_not_started():
    """🔴 시간이 없어 시작하지 못한 것과 **다른 사실**이다."""
    assert _result(1).rerun_state is RerunState.NOT_STARTED
    assert _result(2, skipped=True).rerun_state is RerunState.NOT_SELECTED


def test_c03_the_tally_counts_every_result():
    """🔴 하나라도 어느 칸에도 들어가지 않으면 결과가 조용히 사라진다."""
    from agent.bounded_search import ResultTally

    tally = ResultTally(verified=1, not_selected=4)
    assert tally.total == 5
    assert tally.incomplete == 4


# ======================================================================
# D. 평가는 필드를 축으로 센다
# ======================================================================
class _Zone:
    def __init__(self, size, cards=()):
        self.size = size
        self.cards = tuple(cards)


class _Slot:
    def __init__(self, face_up=True):
        self.face_up = face_up


class _Resources:
    """자원 요약의 **읽는 모양**만 흉내 낸다."""

    seat = 0
    normal_summon_used = True
    state_hash = "h"

    def __init__(self, field=0, hand=5, sets=0):
        self._field = field
        self._hand = hand
        self._sets = sets
        self.own_limits = ()

    @property
    def own_field(self):
        return tuple(_Slot() for _ in range(self._field))

    def size(self, _seat, zone):
        from engine.vocabulary import Zone

        return {Zone.HAND: self._hand}.get(zone, 0)

    def zone(self, _seat, zone):
        from engine.vocabulary import Zone

        if zone is Zone.SZONE:
            return _Zone(self._sets, [_Slot(face_up=False)] * self._sets)
        return None


def _step(order, kind="normal_summon"):
    return PathStep(order=order, kind=kind, action_key=(kind, order))


def test_d01_the_field_is_an_axis():
    """
    🔴 **두 보존 축만 보면 "아무것도 하지 않은 쪽" 이 이긴다.** 필드를 축에
    넣어야 전개한 쪽이 비교 대상이 된다.
    """
    from agent.open_evaluation import measure_open, _dominates

    idle, _ = measure_open((_step(1),), _Resources(field=1, hand=4))
    built, _ = measure_open((_step(1), _step(2)),
                            _Resources(field=3, hand=4))
    assert not _dominates(idle, built)
    assert _dominates(built, idle)


def test_d02_spending_the_hand_is_not_automatically_better():
    """🔴 패를 더 쓴 쪽이 **필드를 늘리지 못하면** 더 낫지 않다."""
    from agent.open_evaluation import measure_open, _dominates

    kept, _ = measure_open((_step(1),), _Resources(field=2, hand=4))
    spent, _ = measure_open((_step(1), _step(2)),
                            _Resources(field=2, hand=2))
    assert _dominates(kept, spent)
    assert not _dominates(spent, kept)


def test_d03_set_cards_are_counted_but_not_an_axis():
    """🔴 세트한 카드는 **방해 수단으로 세지 않는다.**"""
    from agent.open_evaluation import CRITERIA_OPEN, measure_open, _dominates

    plain, _ = measure_open((_step(1),), _Resources(field=2, hand=3))
    with_set, _ = measure_open((_step(1),),
                               _Resources(field=2, hand=3, sets=2))
    assert with_set.set_cards == 2
    assert not _dominates(with_set, plain) and not _dominates(plain, with_set)
    said = next(one for one in CRITERIA_OPEN if one.key == "set_cards")
    assert "방해" in said.limit_ko


def test_d04_unjudged_limits_are_spelled_out():
    """🔴 **무엇을 판정하지 않는지** 적어 두지 않으면 수치가 강함으로 읽힌다."""
    from agent.open_evaluation import UNJUDGED_OPEN

    joined = " ".join(UNJUDGED_OPEN)
    assert "금지·제한" in joined and "확정 방해" in joined


def test_d05_a_not_selected_result_is_not_called_a_failed_rerun():
    """🔴 평가가 **보지도 않은 후보**를 검증 실패로 적지 않는다."""
    from agent.open_evaluation import rank_open

    class _Outcome:
        results = (_result(1, skipped=True),)

    ranking = rank_open(_Outcome())
    said = ranking.reason_ko(1)
    assert "상위에 들지 못해" in said
    assert "재생 검증을 통과하지 못해" not in said


def test_d06_only_verified_results_are_recommended():
    from agent.open_evaluation import rank_open

    class _Rerun:
        pass

    class _Outcome:
        results = (_result(1, rerun=None),)

    ranking = rank_open(_Outcome())
    assert not ranking.has_recommendation


# ======================================================================
# E. 고정 경로 정책이 들어오지 않는다
# ======================================================================
def test_e01_the_autonomous_entry_never_touches_a_combo_line():
    """🔴 **적어 둔 경로를 부르지 않는다** — 그 이름이 소스에 없다."""
    import inspect

    import app.main as main

    source = inspect.getsource(main.autonomous_search_opening)
    #: 🔴 **설명이 아니라 코드를 본다** — 문서 문자열은 "부르지 않는다" 는
    #: 말을 적는 자리이므로 그 이름이 들어 있다.
    body = source.split('"""')[2]
    for needle in ("COMBO_LINES", "ComboLine", "line_named",
                   "VerificationLinePolicy", "resolution_preferences",
                   "ORCUST", "69811710"):
        assert needle not in body, needle
    assert "opening_wiring(repository, None)" in body


def test_e02_the_autonomous_modules_hold_no_card_ids():
    """🔴 평가에 **카드 이름도 링크 수치도** 없다."""
    import inspect

    import agent.open_evaluation as evaluation

    source = inspect.getsource(evaluation)
    for needle in ("69811710", "30741503", "76145142", "기르수", "갈라테아",
                   "롱기르수", "link_rating"):
        assert needle not in source, needle


def test_e03_the_scripted_replay_policy_refuses_to_substitute():
    """
    🔴 기록된 행동이 그 자리의 허용 후보에 없으면 **비슷한 것으로 메꾸지
    않는다** — ``None`` 을 돌려주고 멈춘다.
    """
    from app.main import ScriptedActionPolicy

    class _Action:
        def __init__(self, key):
            self._key = key

        def canonical_state(self):
            return self._key

    class _Legal:
        def __init__(self, *keys):
            self.allowed = [_Action(key) for key in keys]

    policy = ScriptedActionPolicy([("a",), ("b",)])
    assert policy(None, _Legal(("a",))) is not None
    assert policy(None, _Legal(("z",))) is None
    assert not policy.done and policy.left == 1


# ======================================================================
# F. 디스코드 입구
# ======================================================================
def test_f01_auto_is_recognised_and_other_names_are_not():
    from app.main import AUTONOMOUS_SEARCH_NAME, is_autonomous_search

    assert is_autonomous_search(AUTONOMOUS_SEARCH_NAME)
    assert is_autonomous_search(" AUTO ")
    assert not is_autonomous_search("galatea")
    assert not is_autonomous_search("")


def test_f02_the_fixed_goals_still_resolve():
    """🔴 기존 ``search:`` 목표가 그대로 돈다."""
    from app.main import search_goal_card_id

    assert search_goal_card_id("galatea") == 30741503
    assert search_goal_card_id("longirsu") == 76145142
    assert search_goal_card_id("auto") is None


def test_f03_the_brief_says_which_mode_ran(monkeypatch):
    """🔴 **자율 탐색임을 제목이 말한다** — 고정 경로와 한눈에 갈려야 한다."""
    import app.discord_bot as bot
    import app.main as main

    class _Agent:
        repository = None

    seen = {}

    def _fake_search(repository, draft, hand, **kwargs):
        seen.update(kwargs)
        return object(), _Outcome()

    class _Outcome:
        results = ()

    monkeypatch.setattr(main, "autonomous_search_opening", _fake_search)
    monkeypatch.setattr(main, "rank_autonomous_results", lambda outcome: None)

    class _Parsed:
        draft = object()
        unresolved = ()
        notes = ()

    monkeypatch.setattr("deck.recipe.parse_recipe",
                        lambda text, repo=None: _Parsed())
    monkeypatch.setattr("deck.report.render_open_search_brief",
                        lambda *a, **k: "자율 요약")
    monkeypatch.setattr("deck.report.render_open_search",
                        lambda *a, **k: "자율 상세")
    report = bot._run_bounded_search(_Agent(), "recipe", [1], "auto")
    assert report.ran
    assert report.brief[0] == "**[자율 전개 탐색]**"
    assert seen.get("max_results", 0) >= 2


def test_f04_an_unknown_goal_points_at_the_autonomous_mode():
    """🔴 **없는 명령을 안내하지 않는다** — 실제로 되는 값을 적는다."""
    import app.discord_bot as bot

    class _Agent:
        repository = None

    report = bot._run_bounded_search(_Agent(), "recipe", [1], "없는목표")
    assert not report.ran
    assert any("search:auto" in line for line in report.brief)


def test_f05_share_replay_routes_auto_to_the_autonomous_path(monkeypatch):
    """``/share-replay line:auto`` 가 **고정 경로를 부르지 않는다.**"""
    import app.discord_bot as bot

    class _Agent:
        repository = None

    called = {"fixed": 0, "auto": 0}

    def _fixed(*args, **kwargs):
        called["fixed"] += 1
        return bot.OpeningReport(ran=False)

    def _auto(agent, recipe_text, hand_ids):
        called["auto"] += 1
        return bot.OpeningReport(brief=("머리", "자율"), ran=True)

    monkeypatch.setattr(bot, "_run_opening", _fixed)
    monkeypatch.setattr(bot, "_run_autonomous_share", _auto)

    class _Runner:
        def share(self, *a, **k):
            raise AssertionError("기록 없이 공유를 시작했습니다")

    lines = bot.share_replay_response(
        _Agent(), "11", recipe_text="11091375 x1", line_text="auto",
        runner=_Runner())
    assert called == {"fixed": 0, "auto": 1}
    assert any("자율 탐색 모드" in line for line in lines)


def test_f06_share_replay_still_uses_the_fixed_line(monkeypatch):
    """🔴 **기존 고정 경로 입력이 그대로 돈다.**"""
    import app.discord_bot as bot

    class _Agent:
        repository = None

    called = {"fixed": 0, "auto": 0}
    monkeypatch.setattr(bot, "_run_opening",
                        lambda *a, **k: called.__setitem__("fixed", 1)
                        or bot.OpeningReport(ran=False))
    monkeypatch.setattr(bot, "_run_autonomous_share",
                        lambda *a, **k: called.__setitem__("auto", 1)
                        or bot.OpeningReport(ran=False))
    bot.share_replay_response(_Agent(), "11", recipe_text="11091375 x1",
                              line_text="orcust-skeleton-longirsu",
                              runner=object())
    assert called == {"fixed": 1, "auto": 0}
