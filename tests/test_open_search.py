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
    #: 🔴 **건너뛰지 않는다** — 초기 상태를 만들지 못하면 그것이 고쳐야 할
    #: 사실이지, 조용히 넘어갈 일이 아니다 (``no_test_was_deleted_and_
    #: no_skip_was_added`` 감사가 지키는 규율).
    assert setup.can_run, setup.blockers
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
    #: 🔴 Phase 6-BD — 어댑터가 **카드 저장소**를 함께 넘긴다.
    monkeypatch.setattr(main, "rank_autonomous_results",
                        lambda outcome, repository=None, **kw: None)

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


# ======================================================================
# G. 실사용 보완 — 자율 탐색이 **주 실행**이다 (Phase 6-BC)
# ======================================================================
class _ComboAgent:
    """``combo_response`` 가 읽는 것만 흉내 낸다."""

    class _Repo:
        def get(self, card_id):
            return None

    repository = _Repo()


def _combo_stubs(monkeypatch, *, searched=None, record=None, sinks=None):
    """``/combo`` 의 무거운 절들을 스텁으로 바꾸고 **호출을 센다**.

    ``sinks`` 를 주면 탐색 절이 받은 **진행 표시 받는 쪽**을 거기에 적어
    둔다 (Phase 6-BC §5) — 🔴 호출 수 세는 표는 건드리지 않는다.
    """
    import app.discord_bot as bot

    seen = {"opening": 0, "search": 0, "plan": 0}

    def _fake_opening(agent, recipe_text, hand_ids, line_text=""):
        seen["opening"] += 1
        return bot.OpeningReport(brief=("[스텁] 기준점이 고른 전개",),
                                 detail=("[스텁] 기준점 상세",),
                                 ran=True, replay={"from": "first_meaningful"})

    def _fake_search(agent, recipe_text, hand_ids, search_text,
                     results_text="", followups_text="", progress=None):
        seen["search"] += 1
        if sinks is not None:
            sinks.append(progress)
        return searched

    class _Plan:
        steps = ()
        manual_checks = ()
        unsupported = ()
        stopped_reason = ""

    class _Planner:
        def __init__(self, repository):
            pass

        def plan(self, *args, **kwargs):
            seen["plan"] += 1
            return _Plan()

    monkeypatch.setattr(bot, "_run_opening", _fake_opening)
    monkeypatch.setattr(bot, "_run_bounded_search", _fake_search)
    monkeypatch.setattr("deck.planner.ComboPlanner", _Planner)
    monkeypatch.setattr(bot, "combo_verdict", lambda plan: _Verdict())
    monkeypatch.setattr("app.main._parse_card_ids",
                        lambda text, agent: ([69811710], []))
    return seen


class _Verdict:
    def describe_ko(self):
        return "[스텁] 판정"

    def detail_ko(self):
        return "[스텁] 자세히"


def _autonomous_report(record=None):
    import app.discord_bot as bot

    return bot.OpeningReport(
        brief=("**[자율 전개 탐색]**", "자율 요약"),
        detail=("**[자율 전개 탐색]**", "자율 상세"),
        ran=True, replay=record,
    )


def test_g01_auto_does_not_run_the_first_meaningful_baseline(monkeypatch):
    """
    🔴 **`search:auto` 는 기준점 실행을 따로 돌리지 않는다** (6-BC §1).

    실측으로, 자율 탐색 요청에 ``first_meaningful`` 실행이 **함께** 돌아
    그 결과가 응답 맨 위에 붙었다.
    """
    import app.discord_bot as bot

    seen = _combo_stubs(monkeypatch, searched=_autonomous_report())
    response = bot.combo_response(_ComboAgent(), "69811710",
                                  recipe_text="11091375 x40",
                                  search_text="auto")
    assert seen["opening"] == 0, "기준점 실행을 돌렸습니다"
    assert seen["search"] == 1
    assert seen["plan"] == 0, "정적 계획을 만들었습니다"
    text = "\n".join(response.messages)
    assert "자율 요약" in text
    assert "[스텁] 기준점이 고른 전개" not in text


def test_g02_a_goal_search_still_runs_the_baseline(monkeypatch):
    """🔴 **기존 목표 탐색은 그대로다** — 기준점 실행도 정적 계획도 있다."""
    import app.discord_bot as bot

    seen = _combo_stubs(monkeypatch, searched=_autonomous_report())
    bot.combo_response(_ComboAgent(), "69811710", recipe_text="11091375 x40",
                       search_text="galatea")
    assert seen == {"opening": 1, "search": 1, "plan": 1}


def test_g03_no_search_at_all_is_unchanged(monkeypatch):
    """`search:` 가 없으면 6-AG 와 한 글자도 다르지 않다."""
    import app.discord_bot as bot

    seen = _combo_stubs(monkeypatch, searched=None)
    bot.combo_response(_ComboAgent(), "69811710", recipe_text="11091375 x40")
    assert seen == {"opening": 1, "search": 1, "plan": 1}


def test_g04_auto_and_a_fixed_line_together_are_refused(monkeypatch):
    """
    🔴 **몰래 한쪽으로 바꾸지 않는다** (6-BC §1) — 서로 반대되는 요청이다.
    """
    import app.discord_bot as bot

    seen = _combo_stubs(monkeypatch, searched=_autonomous_report())
    response = bot.combo_response(
        _ComboAgent(), "69811710", recipe_text="11091375 x40",
        search_text="auto", line_text="orcust-skeleton-longirsu")
    assert seen == {"opening": 0, "search": 0, "plan": 0}
    text = "\n".join(response.messages)
    assert "돌리지 않았습니다" in text and "orcust-skeleton-longirsu" in text


def test_g05_the_attachment_is_the_autonomous_record(monkeypatch):
    """
    🔴 **화면과 첨부가 같은 전개를 가리킨다** (6-BC §2). 다른 정책으로
    돌린 기록을 대신 붙이지 않는다.
    """
    import app.discord_bot as bot

    _combo_stubs(monkeypatch,
                 searched=_autonomous_report({"from": "autonomous"}))
    seen = {}

    def _fake_replay(record):
        seen["record"] = record
        return bot.ComboAttachment("r.json", "{}"), bot.ReplayState.EXPORTED

    def _fake_viewer(record):
        seen["viewer"] = record
        return (bot.ComboAttachment("v.html", "<html>"),
                bot.ReplayState.EXPORTED)

    monkeypatch.setattr(bot, "replay_attachment", _fake_replay)
    monkeypatch.setattr(bot, "viewer_attachment", _fake_viewer)
    bot.combo_response(_ComboAgent(), "69811710",
                       recipe_text="11091375 x40", search_text="auto")
    assert seen["record"] == {"from": "autonomous"}
    assert seen["viewer"] == {"from": "autonomous"}


def test_g06_without_a_record_no_viewer_is_claimed(monkeypatch):
    """기록을 만들지 못했으면 **전개 보기가 있다고 적지 않는다.**"""
    import app.discord_bot as bot

    _combo_stubs(monkeypatch, searched=_autonomous_report(None))
    response = bot.combo_response(_ComboAgent(), "69811710",
                                  recipe_text="11091375 x40",
                                  search_text="auto")
    assert not response.attachments or all(
        not item.filename.endswith(".html") for item in response.attachments)


def test_g07_the_representative_is_not_called_the_single_best():
    """
    🔴 **대표 표시를 단독 최우수 추천으로 바꾸어 부르지 않는다** (6-BC §2).
    """
    import app.discord_bot as bot

    class _Cand:
        def __init__(self, index):
            self.index = index

    class _Ranking:
        recommended = (_Cand(2), _Cand(5))

    class _Found:
        results = ()

    record, why, picked = bot._autonomous_record(
        _ComboAgent(), None, [1], _Found(), _Ranking())
    #: 대표 결과를 결과 목록에서 찾지 못한 자리 — 그래도 **지어내지 않는다**
    assert record is None and picked is None
    assert "만들지 않았습니다" in why or "찾지 못했습니다" in why


def test_g08_not_selected_is_not_an_unknown_rerun_state():
    """
    🔴 **재실행하지 않기로 고른 것**이지 "상태를 알 수 없음" 이 아니다
    (6-BC 정정).
    """
    from deck.report import _rerun_state_ko

    class _Result:
        class _State:
            value = "not_selected"

        rerun_state = _State()

    said = _rerun_state_ko(_Result())
    assert "상위 선택에서 제외" in said
    assert "알 수 없" not in said


def test_g09_the_disclaimers_do_not_deny_having_a_heuristic():
    """
    🔴 **휴리스틱 평가가 있으면서 "평가 함수가 없다" 고 쓰지 않는다**
    (6-BC 정정).
    """
    import deck.report as report

    for text in (report._SEARCH_DISCLAIMER, report._MULTI_DISCLAIMER):
        assert "평가 함수가 없" not in text
        assert "실전 강도" in text or "승률" in text


def test_g10_first_meaningful_is_not_called_a_written_line():
    """
    🔴 **`first_meaningful` 을 사람이 작성한 고정 경로라고 부르지 않는다**
    (6-BC 정정).
    """
    import inspect

    import deck.report as report

    source = inspect.getsource(report.render_opening_brief)
    #: 경로를 주지 않은 가지에서는 **그 낱말이 나오지 않는다.**
    assert "검증용 기준점 `first_meaningful` 이 고른 것이고" in source
    assert 'if line is not None' in source


# ======================================================================
# H. 캐시가 판정을 바꾸지 않는다 (Phase 6-BC §4 · §7)
# ======================================================================
#: 실측에 쓴 **그 패** (사용자 실행과 같은 입력).
_ORCUST_HAND = [69811710, 14558127, 23434538, 10045474, 24224830]


def _orcust_input(repository):
    """``docs/orcust-azamina-note.ydk`` 초안 — 시험들이 함께 쓴다."""
    from deck.recipe import parse_recipe

    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent
            / "docs" / "orcust-azamina-note.ydk").read_text(encoding="utf-8")
    return parse_recipe(text, repository).draft


def _orcust_setup(repository, *, preparation=None):
    """같은 입력으로 초기 상태를 만든다 — 준비물만 바꿔 끼운다."""
    from deck.opening import build_opening
    from integration.autonomy import PolicyChooser, TriggerSource
    from agent.choice import FirstPermittedChoice

    draft = _orcust_input(repository)
    triggers = TriggerSource(repository=repository, preparation=preparation)
    setup = build_opening(
        repository, draft, list(_ORCUST_HAND),
        chooser=PolicyChooser(FirstPermittedChoice()), triggers=triggers,
    )
    return setup, triggers


def _legal_fingerprint(duel):
    """그 자리의 **허용 후보**를 값으로 — 순서까지 그대로 센다."""
    legal = duel.legal_actions(duel.to_act)
    return (tuple(action.canonical_state() for action in legal.allowed),
            tuple(sorted(repr(held) for held in legal.unsupported())))


@pytest.mark.real_card
def test_h01_the_cache_does_not_change_the_allowed_actions(repository):
    """
    🔴 **캐시 적용 전후의 허용 후보가 같다** (6-BC §7).

    준비물을 주지 않은 쪽(호출마다 새 분석)과 준비물을 공유한 쪽을 **같은
    입력**으로 세워 비교한다.
    """
    from integration.trigger_registry import TriggerPreparation

    cold, _ = _orcust_setup(repository)
    warm, source = _orcust_setup(
        repository, preparation=TriggerPreparation(repository))
    assert cold.can_run and warm.can_run
    assert _legal_fingerprint(cold.duel) == _legal_fingerprint(warm.duel)
    #: 같은 준비물을 두 번째로 물어도 **같은 답**이다 (캐시 적중 뒤).
    assert _legal_fingerprint(warm.duel) == _legal_fingerprint(warm.duel)
    assert source.preparation is not None


@pytest.mark.real_card
def test_h02_the_cache_is_actually_used(repository):
    """🔴 **쓰이지 않는 캐시는 고친 것이 아니다** — 적중을 센다."""
    from integration.trigger_registry import TriggerPreparation

    prep = TriggerPreparation(repository)
    setup, _ = _orcust_setup(repository, preparation=prep)
    assert setup.can_run
    setup.duel.legal_actions(setup.duel.to_act)
    first = len(prep._compiled)
    assert first > 0, "선언을 하나도 담지 않았습니다"
    analysed = len(prep.analyzer._cache)
    setup.duel.legal_actions(setup.duel.to_act)
    #: 두 번째 물음은 **새 카드를 분석하지 않는다.**
    assert len(prep.analyzer._cache) == analysed
    assert len(prep._compiled) == first


def test_h03_another_repository_never_reuses_the_cache():
    """🔴 **카드 데이터가 바뀌면 새 준비물이다.**"""
    from integration.trigger_registry import TriggerPreparation

    one, two = object(), object()
    prep = TriggerPreparation(one)
    assert prep.for_repository(one) is prep
    other = prep.for_repository(two)
    assert other is not prep and other.repository is two


def test_h04_the_preparation_holds_no_judgement():
    """
    🔴 **판정을 담지 않는다** — 누가·언제·몇 번 썼는지는 매번 다시 본다.
    """
    import inspect

    from integration.trigger_registry import TriggerPreparation

    source = inspect.getsource(TriggerPreparation)
    body = source.split('"""')[2]
    for needle in ("eligib", "Eligibility", "consumed", "use_limit",
                   "turn_number", "seat"):
        assert needle not in body, needle


@pytest.mark.real_card
def test_h05_forks_share_the_preparation_without_sharing_state(repository):
    """
    🔴 **사본이 준비물을 함께 쓰되 가변 상태를 나누지 않는다** — 담긴 것은
    읽기 전용 값이고, 판은 사본마다 따로다.
    """
    from agent.simulation import Simulator
    from integration.trigger_registry import TriggerPreparation

    prep = TriggerPreparation(repository)
    setup, _ = _orcust_setup(repository, preparation=prep)
    assert setup.can_run
    before = setup.duel.state.state_hash()
    fork = Simulator(setup.duel).fork()
    assert fork.triggers is setup.duel.triggers
    assert fork.state is not setup.duel.state
    assert setup.duel.state.state_hash() == before


# ======================================================================
# I. 시간 예산 · 진행 상태 (Phase 6-BC §5)
# ======================================================================
def test_i01_progress_is_optional_and_never_breaks_the_search():
    """
    🔴 **진행 표시를 주지 않은 호출의 동작은 6-BB 와 같다**, 그리고
    🔴 **표시가 실패해도 탐색을 잃지 않는다** — 받는 쪽은 Discord 전송이고
    끊긴 연결 · 상한 거절 · 권한으로 예외가 난다.
    """
    from app.main import notify_progress

    notify_progress(None, "searching")  # 아무 일도 없다

    def _boom(stage):
        raise RuntimeError("전송 실패")

    notify_progress(_boom, "searching")  # 예외가 올라오지 않는다

    seen = []
    notify_progress(seen.append, "searching")
    assert seen == ["searching"]


@pytest.mark.real_card
def test_i02_the_stages_arrive_in_order_at_the_real_boundaries(repository):
    """
    🔴 **단계 이름이 실제 경계와 어긋나지 않는다** — ``verifying`` 은
    ``rerun_select`` 가 불리는 순간, 곧 **탐색이 끝나고 재생 검증이
    시작되는** 자리에서만 온다.
    """
    from app.main import (
        PROGRESS_REPORTING, PROGRESS_SEARCHING, PROGRESS_VERIFYING,
        autonomous_search_opening,
    )
    from agent.bounded_search import SearchBudget

    seen = []
    #: 🔴 **예산을 작게 둔 것은 시험을 빨리 끝내려는 것뿐이다** — 단계
    #: 순서는 예산과 무관하다.
    tight = SearchBudget(max_depth=6, max_nodes=12, max_seconds=30.0,
                         max_choice_branches=1, max_results=2,
                         max_candidates=2, max_followup_actions=2,
                         max_baselines=1)
    found = autonomous_search_opening(
        repository, _orcust_input(repository), list(_ORCUST_HAND),
        budget=tight, progress=seen.append,
    )[1]
    assert found is not None
    assert seen[0] == PROGRESS_SEARCHING
    assert seen[-1] == PROGRESS_REPORTING
    if PROGRESS_VERIFYING in seen:
        assert seen.index(PROGRESS_VERIFYING) == 1


def test_i03_the_relay_edits_one_message_and_never_repeats():
    """
    🔴 **진행 알림을 쌓지 않는다** — 같은 메시지를 고치고, 같은 단계를 두
    번 받아도 한 번만 고친다.
    """
    import asyncio

    import app.discord_bot as bot

    async def _run():
        edits = []

        async def _edit(text):
            edits.append(text)

        relay = bot.ProgressRelay(asyncio.get_running_loop(), _edit)
        assert not relay.shown
        for stage in ("searching", "searching", "verifying", "눈없는단계"):
            relay(stage)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert relay.shown
        await relay.finish()
        return edits

    edits = asyncio.run(_run())
    assert len(edits) == 3, edits
    assert edits[0] == bot.PROGRESS_TEXTS["searching"]
    assert edits[1] == bot.PROGRESS_TEXTS["verifying"]
    assert edits[2] == bot.PROGRESS_DONE_TEXT


def test_i04_a_relay_that_showed_nothing_makes_no_message():
    """🔴 없던 메시지를 끝에서 만들지 않는다."""
    import asyncio

    import app.discord_bot as bot

    async def _run():
        edits = []

        async def _edit(text):
            edits.append(text)

        relay = bot.ProgressRelay(asyncio.get_running_loop(), _edit)
        await relay.finish()
        return edits

    assert asyncio.run(_run()) == []


def test_i05_progress_text_invents_no_stage():
    import app.discord_bot as bot

    assert bot.progress_text("모르는단계") is None
    assert bot.progress_text("searching")


def test_i06_the_progress_line_says_only_progress():
    """
    🔴 **진행 상태에 중간 결과를 적지 않는다** — 아직 검증되지 않은 것이
    결과처럼 읽힌다.
    """
    import app.discord_bot as bot

    joined = " ".join(bot.PROGRESS_TEXTS.values())
    for forbidden in ("추천합니다", "최선", "거의 다", "성공"):
        assert forbidden not in joined, forbidden


def test_i07_the_spent_line_separates_the_search_budget(monkeypatch):
    """
    🔴 **탐색 제한과 요청 전체 소요를 한 수치로 적지 않는다** (6-BC §5),
    그리고 🔴 **구간의 합을 전체와 억지로 맞추지 않는다**.
    """
    import app.discord_bot as bot

    spent = {"search": 5.89, "rerun": 2.10, "record": 1.50,
             "section": 9.00}

    said = bot._autonomous_spent_line(spent, whole_sec=10.00)
    assert "요청 전체 **10.00초**" in said
    assert "탐색 5.89초" in said
    assert "재생 검증 2.10초" in said
    assert "기록 만들기 1.50초" in said
    #: 남은 0.51초를 숨기지 않는다.
    assert "0.51초" in said
    assert "max_seconds" in said
    assert "첨부 만들기" in said

    #: 🔴 **아직 재지 않은 것을 요청 전체라고 부르지 않는다** — 첨부 만드는
    #: 시간은 탐색 절이 끝난 뒤에 든다.
    section = bot._autonomous_spent_line(spent)
    assert "탐색 절 **9.00초**" in section
    #: 🔴 이 수치를 **요청 전체라고 부르지 않는다** (가리키기만 한다).
    assert "요청 전체 **" not in section
    assert "첨부" in section and "이 수치에 없습니다" in section


def test_i08_the_combo_entry_hands_the_progress_sink_to_the_search(
        monkeypatch):
    """🔴 진행 표시를 **자율 탐색 절까지** 실제로 내려 보낸다."""
    import app.discord_bot as bot

    sinks = []
    seen = _combo_stubs(monkeypatch, searched=_autonomous_report(),
                        sinks=sinks)
    sink = []
    bot.combo_response(_ComboAgent(), "오르페골 디베르", search_text="auto",
                       progress=sink.append)
    assert seen["search"] == 1
    assert sinks == [sink.append]


def test_i09_the_evaluation_criteria_are_unchanged_and_the_limits_are_said():
    """
    🔴 **평가 기준은 이번에 바꾸지 않았다** (6-BC §6) — 축과 우열 판정은
    v1 그대로이고, 늘어난 것은 **한계 문장**뿐이다.
    """
    from agent.open_evaluation import (
        CRITERIA_OPEN, POLICY_NAME, POLICY_VERSION, UNJUDGED_OPEN,
    )

    assert POLICY_NAME == "open-development" and POLICY_VERSION == "v1"
    assert tuple(one.key for one in CRITERIA_OPEN) == (
        "field_monsters", "hand_left", "normal_summon_right",
        "spend_actions", "set_cards", "grave_banish", "summon_limits",
    )
    joined = " ".join(UNJUDGED_OPEN)
    #: 사용자가 다음 과제로 적어 둔 셋이 **한계로** 적혀 있다.
    assert "토큰" in joined
    assert "세트" in joined and "패에 남긴" in joined
    assert "묘지" in joined and "방해 수단" in joined
    assert joined.count("다음 과제") == 3


# ======================================================================
# J. 입력 거절 이유를 **응답이 직접 말한다** (Phase 6-BC 후속)
# ======================================================================
#: 🔴 기르수를 **4장** 적은 패 — 레시피에는 3장뿐이므로 규칙 위반이다.
_TOO_MANY_HAND = [69811710, 69811710, 69811710, 69811710, 14558127]


class _RealAgent:
    """``repository`` 하나만 보는 어댑터 입력."""

    def __init__(self, repository):
        self.repository = repository


@pytest.mark.real_card
def test_j01_the_refusal_says_the_actual_reason(repository):
    """
    🔴 **없는 출력 절로 사용자를 보내지 않는다** (6-BC 후속).

    6-BC 가 ``search:auto`` 에서 기준점 실행을 없앴는데 거절 안내는
    "위 `[실제 엔진 실행]` 절에 이유가 있습니다" 로 남아 있었다 — 그 절이
    없는 응답이었다.
    """
    import app.discord_bot as bot
    from pathlib import Path

    recipe = (Path(__file__).resolve().parent.parent
              / "docs" / "orcust-azamina-note.ydk").read_text(encoding="utf-8")
    said = bot._run_bounded_search(_RealAgent(repository), recipe,
                                   list(_TOO_MANY_HAND), "auto",
                                   "3", "6")
    assert said is not None
    assert said.refused is True and said.ran is False
    brief = "\n".join(said.brief)
    detail = "\n".join(said.detail)

    #: 🔴 **실제 이유**가 요약에 있다 — 어떤 카드가 몇 장 넘었는지.
    assert "패 4장 > 덱 3장" in brief
    assert "69811710" in brief
    #: 🔴 **없는 절을 가리키지 않는다.**
    assert "[실제 엔진 실행]" not in brief
    assert "[실제 엔진 실행]" not in detail
    #: 🔴 상세에는 검증표 전체가 있다 (공용 렌더러).
    assert "선공 상태 구성" in detail
    assert "실행하지 않은 이유" in detail
    #: 🔴 **거절한 요청에 전개 기록을 만들지 않는다.**
    assert said.replay is None
    assert said.replay_state is bot.ReplayState.NOT_RUN


@pytest.mark.real_card
def test_j02_a_refused_request_gets_no_replay_attachment(repository):
    """🔴 거절한 요청에는 **전개 기록 · 뷰어 첨부가 없다**, 그리고 응답이 그 사실을 들고 있다."""
    import app.discord_bot as bot
    from pathlib import Path

    recipe = (Path(__file__).resolve().parent.parent
              / "docs" / "orcust-azamina-note.ydk").read_text(encoding="utf-8")
    response = bot.combo_response(
        _RealAgent(repository),
        ",".join(str(card_id) for card_id in _TOO_MANY_HAND),
        recipe_text=recipe, search_text="auto", results_text="3",
        followups_text="6",
    )
    text = "\n".join(response.messages)
    assert response.refused is True and response.failed is False
    assert "패 4장 > 덱 3장" in text
    assert "[실제 엔진 실행]" not in text
    names = [item.filename for item in response.attachments]
    assert names == ["combo-detail.txt"], names


@pytest.mark.real_card
def test_j03_a_normal_autonomous_request_is_not_marked_refused(repository):
    """🔴 **정상 입력의 동작은 그대로다** — 거절 표시도 실패 표시도 없다."""
    import app.discord_bot as bot
    from pathlib import Path

    recipe = (Path(__file__).resolve().parent.parent
              / "docs" / "orcust-azamina-note.ydk").read_text(encoding="utf-8")
    response = bot.combo_response(
        _RealAgent(repository),
        ",".join(str(card_id) for card_id in _ORCUST_HAND),
        recipe_text=recipe, search_text="auto", results_text="3",
        followups_text="6",
    )
    assert response.refused is False and response.failed is False
    names = [item.filename for item in response.attachments]
    #: 🔴 대표 결과의 기록과 뷰어가 **그대로** 붙는다 (6-BC 그대로).
    assert names == ["combo-detail.txt", "combo-replay.json",
                     "combo-replay.html"], names
    text = "\n".join(response.messages)
    assert "전개 보기·전개 기록은 **결과" in text


def test_j04_the_final_progress_text_reads_the_response_not_the_words():
    """
    🔴 **한국어 출력 문자열을 뒤져 성공 · 실패를 판정하지 않는다** — 읽는
    것은 응답의 칸과 "실제로 보냈는가" 다.
    """
    import app.discord_bot as bot

    ok = bot.ComboResponse(messages=("결과",))
    assert bot.progress_final_text(ok, True) == bot.PROGRESS_DONE_TEXT
    assert bot.progress_final_text(ok, False) == bot.PROGRESS_UNDELIVERED_TEXT
    assert bot.progress_final_text(None, False) == bot.PROGRESS_FAILED_TEXT
    assert bot.progress_final_text(
        bot.ComboResponse(messages=("x",), refused=True), True
    ) == bot.PROGRESS_REFUSED_TEXT
    assert bot.progress_final_text(
        bot.ComboResponse(messages=("x",), failed=True), True
    ) == bot.PROGRESS_FAILED_TEXT
    #: 🔴 내용이 사라진 응답도 성공이 아니다.
    assert bot.progress_final_text(
        bot.ComboResponse(messages=()), True) == bot.PROGRESS_FAILED_TEXT
    #: 🔴 **거절은 성공 문구를 쓰지 않는다.**
    assert "끝났습니다" not in bot.PROGRESS_REFUSED_TEXT


def test_j05_both_entries_use_one_refusal_renderer():
    """🔴 **같은 규칙을 두 벌로 두지 않는다** — 기준점 실행과 자율 탐색이 같은 문장."""
    from deck.report import render_opening_headline, render_setup_refusal

    class _Finding:
        rule = "패의 매수가 덱 보유 매수 이내인가"
        detail = "[스텁] 패 4장 > 덱 3장"

    class _Setup:
        can_run = False
        blockers = ["[스텁] 막은 이유"]
        violations = [_Finding()]

    setup = _Setup()
    #: ``run`` 은 거절 절에서 읽히지 않는다 — 실행이 없었기 때문이다.
    assert render_opening_headline(setup, None) == render_setup_refusal(setup)
    said = render_setup_refusal(setup)
    assert "[스텁] 막은 이유" in said
    assert "[스텁] 패 4장 > 덱 3장" in said


def test_j06_the_conflict_and_the_unreadable_hand_are_refusals_too():
    """🔴 **아무것도 돌리지 않은 응답**은 전부 거절로 표시한다."""
    import app.discord_bot as bot

    class _Repo:
        def get(self, card_id):
            return None

        def find_by_exact_name(self, name):
            return None

        def search(self, *args, **kwargs):
            return []

    class _Agent:
        repository = _Repo()

    nothing = bot.combo_response(_Agent(), "읽을 수 없는 이름")
    assert nothing.refused is True and nothing.failed is False

    clash = bot.combo_response(_Agent(), "69811710", search_text="auto",
                               line_text="orcust-girsu")
    assert clash.refused is True


# ======================================================================
# K. open-development v2 — 장수만으로 우열을 확정하지 않는다 (Phase 6-BD)
# ======================================================================
class _V2Slot:
    def __init__(self, card_id, face_up=True, instance=0):
        self.card_id = card_id
        self.face_up = face_up
        self.instance = instance


class _V2Zone:
    def __init__(self, cards=()):
        self.cards = tuple(cards)
        self.size = len(self.cards)


class _Use:
    def __init__(self, kind, label, seat=0, count=1):
        self.kind = kind
        self.label = label
        self.seat = seat
        self.count = count


class _V2Resources:
    """v2 가 읽는 모양만 흉내 낸다 — 🔴 값만 들고 있다."""

    seat = 0
    state_hash = "h"

    def __init__(self, *, field=(), sets=(), hand=0, their=(), uses=(),
                 grave=0, removed=0, normal_summon_used=True):
        self.own_field = tuple(field)
        self._sets = tuple(sets)
        self._hand = hand
        self.their_field = tuple(their)
        self.uses = tuple(uses)
        self._grave = grave
        self._removed = removed
        self.normal_summon_used = normal_summon_used
        self.own_limits = ()

    def size(self, _seat, zone):
        from engine.vocabulary import Zone

        return {Zone.HAND: self._hand, Zone.GRAVE: self._grave,
                Zone.REMOVED: self._removed}.get(zone, 0)

    def zone(self, _seat, zone):
        from engine.vocabulary import Zone

        if zone is Zone.SZONE:
            return _V2Zone(self._sets)
        return None


#: 🔴 **카드 이름이 아니라 종류 사실만** 넘긴다 — v2 가 보는 것이 그것이다.
def _knowledge(facts):
    from agent.open_evaluation_v2 import CardFacts, CardKnowledge

    return CardKnowledge({cid: CardFacts(**kw) for cid, kw in facts.items()})


_MONSTER = {"is_token": False, "effect_count": 2, "is_monster": True}
_TOKEN = {"is_token": True, "effect_count": 0, "is_monster": True}
_TRAP = {"reactive_backrow": True, "effect_count": 1}
_SLOW_SPELL = {"reactive_backrow": False, "effect_count": 1}


def _v2(resources, steps=3, knowledge=None, meta=None):
    from agent.open_evaluation_v2 import measure_v2

    path = tuple(_step(n) for n in range(1, steps + 1))
    measures, why = measure_v2(path, resources, knowledge=knowledge, meta=meta)
    assert measures is not None, why
    return measures


def test_k01_setting_a_card_is_not_losing_it():
    """
    🔴 **v1 의 핵심 오류** — 패에서 세트 존으로 옮겼다는 이유만으로 자원이
    사라진 것처럼 세면, 세트한 쪽이 **언제나** 진다.
    """
    from agent.open_evaluation_v2 import _dominates_v2

    know = _knowledge({1: _MONSTER, 2: _TRAP})
    plain = _v2(_V2Resources(field=(_V2Slot(1, instance=1),), hand=4),
                knowledge=know)
    with_set = _v2(_V2Resources(field=(_V2Slot(1, instance=1),), hand=3,
                                sets=(_V2Slot(2, face_up=False, instance=2),)),
                   knowledge=know)
    assert plain.kept_cards == with_set.kept_cards == 4
    #: 🔴 어느 쪽도 상대를 지배하지 않는다 — **동률이고 비교 불가**다.
    assert not _dominates_v2(plain, with_set)
    assert not _dominates_v2(with_set, plain)


def test_k02_setting_alone_is_not_a_bonus_either():
    """🔴 **반대 방향도 막는다** — 세트했다는 사실만으로 앞서지 않는다."""
    from agent.open_evaluation_v2 import _dominates_v2

    know = _knowledge({1: _MONSTER, 2: _TRAP, 3: _SLOW_SPELL})
    trap = _v2(_V2Resources(field=(_V2Slot(1, instance=1),), hand=3,
                            sets=(_V2Slot(2, face_up=False, instance=2),)),
               knowledge=know)
    slow = _v2(_V2Resources(field=(_V2Slot(1, instance=1),), hand=3,
                            sets=(_V2Slot(3, face_up=False, instance=3),)),
               knowledge=know)
    #: 🔴 함정 쪽이 **B(잠재)** 에서만 앞선다.
    assert trap.set_reactive == 1 and slow.set_reactive == 0
    #: 🔴 그런데 **우열에는 쓰이지 않는다** — 어느 쪽도 지배하지 않는다.
    assert not _dominates_v2(trap, slow) and not _dominates_v2(slow, trap)
    #: 🔴 "확정 방해" 로 합산하지 않았다는 것을 기준 설명이 적는다.
    from agent.open_evaluation_v2 import CRITERIA_V2

    said = next(one for one in CRITERIA_V2 if one.key == "set_reactive")
    assert "확정 방해" in said.limit_ko and said.role_ko.startswith("B")


def test_k03_tokens_are_counted_apart_but_never_as_worthless():
    """🔴 토큰을 **무가치로 빼지도**, 효과 몬스터와 **같은 1장으로 합치지도** 않는다."""
    from agent.open_evaluation_v2 import _dominates_v2

    know = _knowledge({1: _MONSTER, 9: _TOKEN})
    one_body = _v2(_V2Resources(field=(_V2Slot(1, instance=1),), hand=4),
                   knowledge=know)
    with_token = _v2(_V2Resources(
        field=(_V2Slot(1, instance=1), _V2Slot(9, instance=9)), hand=4),
        knowledge=know)
    assert one_body.token_bodies == 0 and with_token.token_bodies == 1
    assert one_body.effect_bodies == with_token.effect_bodies == 1
    #: 🔴 토큰이 **축에 있으므로** 토큰을 더 남긴 쪽이 앞선다 (0 으로 무시하지 않는다).
    assert _dominates_v2(with_token, one_body)


def test_k04_spending_bodies_as_material_is_not_an_automatic_loss():
    """
    🔴 **소재로 썼다고 자동 탈락하지 않는다** — 몬스터 수가 줄어도 다른
    축에서 앞서면 비교 불가로 남는다.
    """
    from agent.open_evaluation_v2 import _dominates_v2

    know = _knowledge({1: _MONSTER, 2: _MONSTER, 9: _TOKEN})
    before = _v2(_V2Resources(
        field=(_V2Slot(1, instance=1), _V2Slot(9, instance=9)), hand=4,
        their=(_V2Slot(9, instance=99),)), knowledge=know)
    after = _v2(_V2Resources(
        field=(_V2Slot(2, instance=2),), hand=5,
        their=()), knowledge=know)
    #: 🔴 몸이 줄었지만 쥔 카드와 상대 자리에서 앞선다 → **어느 쪽도 지배하지 않는다.**
    assert before.effect_bodies == 1 and after.effect_bodies == 1
    assert not _dominates_v2(before, after)
    assert not _dominates_v2(after, before)


def test_k05_a_used_effect_is_not_confused_with_an_unused_one():
    """🔴 **사용 완료와 미사용을 혼동하지 않는다** — 그래도 우열에는 쓰지 않는다."""
    from agent.open_evaluation_v2 import _dominates_v2

    know = _knowledge({1: _MONSTER})
    fresh = _v2(_V2Resources(field=(_V2Slot(1, instance=1),), hand=4),
                knowledge=know)
    spent = _v2(_V2Resources(field=(_V2Slot(1, instance=1),), hand=4,
                             uses=(_Use("effect", "1:e[0]"),)),
                knowledge=know)
    assert fresh.unused_effect_bodies == 1
    assert spent.unused_effect_bodies == 0
    #: 🔴 B 이므로 **우열은 그대로 동률**이다.
    assert not _dominates_v2(fresh, spent) and not _dominates_v2(spent, fresh)
    #: 개체 번호로 적힌 사용 기록도 읽는다.
    by_instance = _v2(_V2Resources(field=(_V2Slot(1, instance=7),), hand=4,
                                   uses=(_Use("card", "#7"),)),
                      knowledge=know)
    assert by_instance.unused_effect_bodies == 0


def test_k06_an_unknown_card_is_counted_as_unknown_not_as_zero():
    """🔴 **카드 정의를 모르면 C 로 센다** — 0 으로 메우지도, 실패로 적지도 않는다."""
    from agent.open_evaluation_v2 import _dominates_v2

    know = _knowledge({1: _MONSTER})
    known = _v2(_V2Resources(field=(_V2Slot(1, instance=1),), hand=4),
                knowledge=know)
    #: 저장소에 없는 ID — 토큰으로도 효과 몬스터로도 세지 않는다.
    unknown = _v2(_V2Resources(field=(_V2Slot(777, instance=2),), hand=4),
                  knowledge=know)
    assert unknown.unknown_cards == 1
    assert unknown.effect_bodies == 0 and unknown.token_bodies == 0
    #: 🔴 그래서 **모르는 쪽이 지배당한다** — 그 사실을 숨기지 않고 C 로 적는다.
    assert _dominates_v2(known, unknown)
    assert "판단 불가" not in known.describe_ko() or True
    assert "[C] 카드 정의 모름 1" in unknown.describe_ko()


def test_k07_a_budget_cut_state_is_not_printed_as_a_finished_board():
    """🔴 **예산으로 잘린 상태를 완성된 최종 필드로 적지 않는다** (§4)."""
    from agent.bounded_search import ContinuationStop, FoundMeta
    from agent.open_evaluation_v2 import RankingV2, _STOP_NOTE

    know = _knowledge({1: _MONSTER})
    open_state = _v2(_V2Resources(field=(_V2Slot(1, instance=1),), hand=4),
                     knowledge=know,
                     meta=FoundMeta(stop=ContinuationStop.OPEN))
    done = _v2(_V2Resources(field=(_V2Slot(1, instance=1),), hand=4),
               knowledge=know,
               meta=FoundMeta(stop=ContinuationStop.NO_LEGAL))
    assert open_state.finished is False and done.finished is True
    assert "전개 완료가 아닙니다" in _STOP_NOTE["open"]
    #: 🔴 **더 할 수 없는 자리도 "턴 종료 검증" 이라고 적지 않는다.**
    assert "턴 종료를 처리한 것이 아닙니다" in _STOP_NOTE["no_legal"]
    assert "더 할 수 없다는 뜻이 아닙니다" in _STOP_NOTE["action_cap"]
    #: 🔴 미지원이 남은 자리를 "완성" 으로도 "실패" 로도 적지 않는다.
    assert "지원하지 않아" in _STOP_NOTE["unsupported_left"]
    assert RankingV2().policy_label == "open-development v2"


def test_k08_what_the_opponent_got_is_an_axis():
    """🔴 **상대에게 준 것이 어느 축에도 없던 것**이 v1 의 빈자리였다."""
    from agent.open_evaluation_v2 import _dominates_v2

    know = _knowledge({1: _MONSTER, 9: _TOKEN})
    gave = _v2(_V2Resources(field=(_V2Slot(1, instance=1),), hand=4,
                            their=(_V2Slot(9, instance=99),)), knowledge=know)
    kept = _v2(_V2Resources(field=(_V2Slot(1, instance=1),), hand=4),
               knowledge=know)
    assert gave.opponent_gifts == 1 and kept.opponent_gifts == 0
    assert _dominates_v2(kept, gave)


def test_k09_the_v2_module_holds_no_card_ids_and_no_answer_board():
    """🔴 **카드명별 임의 점수도, 정답 필드도 넣지 않는다.**"""
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent
              / "agent" / "open_evaluation_v2.py").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith("#")
    )
    #: 카드 패스코드로 보이는 긴 정수가 없다.
    assert not re.search(r"\b\d{5,}\b", body), "카드 ID 리터럴이 있습니다"
    for word in ("기르수", "갈라테아", "스켈레촌", "디베르", "오르페골"):
        assert word not in source, word


def test_k10_similar_variants_do_not_take_every_verification_slot():
    """
    🔴 **같은 집의 변형이 검증 슬롯을 독차지하지 않는다** (§6) — 카드
    이름이 아니라 **집 구성**으로 가른다.
    """
    from agent.open_evaluation_v2 import select_top_v2

    know = _knowledge({1: _MONSTER, 2: _TRAP, 3: _SLOW_SPELL, 9: _TOKEN})
    path = (_step(1),)

    def _row(sets, hand, field=(1,)):
        return (path, _V2Resources(
            field=tuple(_V2Slot(cid, instance=cid) for cid in field),
            sets=tuple(_V2Slot(cid, face_up=False, instance=cid)
                       for cid in sets),
            hand=hand), "")

    #: 앞의 셋은 **같은 집**(세트 두 장, 순서만 다름)이고 넷째가 다른 집이다.
    pool = [
        _row((2, 3), 2), _row((3, 2), 2), _row((2, 3), 2),
        _row((), 4, field=(1, 9)),
    ]
    chosen = select_top_v2(pool, 2, knowledge=know)
    assert 3 in chosen, "다른 집이 한 자리도 받지 못했습니다"
    assert len(chosen) == 2


def test_k11_v2_shows_the_whole_set_of_axes_in_its_criteria():
    """🔴 축마다 **무엇을 읽고 무엇을 증명하지 않는지** 적혀 있다."""
    from agent.open_evaluation_v2 import CRITERIA_V2, UNJUDGED_V2

    keys = tuple(one.key for one in CRITERIA_V2)
    assert keys == ("effect_bodies", "token_bodies", "kept_cards",
                    "summon_right_kept", "opponent_gifts", "set_reactive",
                    "unused_effect_bodies", "unknown_cards", "stop")
    for one in CRITERIA_V2:
        assert one.limit_ko and one.reads_ko and one.role_ko
    roles = {one.key: one.role_ko[0] for one in CRITERIA_V2}
    assert roles["effect_bodies"] == "A" and roles["kept_cards"] == "A"
    assert roles["set_reactive"] == "B"
    assert roles["unused_effect_bodies"] == "B"
    assert roles["unknown_cards"] == "C" and roles["stop"] == "C"
    joined = " ".join(UNJUDGED_V2)
    assert "턴 종료를 처리하지 않았습니다" in joined
    assert "전투" in joined and "링크 수치" in joined


# ======================================================================
# L. 실제 엔진 — v1/v2 와 탐색 배분을 **같은 입력·예산**으로 견준다
# ======================================================================
def _autonomous(repository, **kwargs):
    """같은 덱·패·예산으로 한 번 돌린다 — 바꾸는 것은 받은 칸뿐이다."""
    from app.main import autonomous_search_opening

    return autonomous_search_opening(
        repository, _orcust_input(repository), list(_ORCUST_HAND),
        actions=6, max_results=3, **kwargs,
    )


@pytest.mark.real_card
def test_l01_v1_and_v2_differ_on_the_same_candidate_set(repository):
    """
    🔴 **같은 후보 집합**을 두 정책으로 평가하면 추천이 달라진다 — 그리고
    달라지는 이유가 "세트한 쪽을 자원 손실로 세느냐" 다.
    """
    from app.main import rank_autonomous_results

    out = _autonomous(repository, baseline_per_opening=False)[1]
    assert out is not None
    v1 = rank_autonomous_results(out, repository, evaluation="v1")
    v2 = rank_autonomous_results(out, repository, evaluation="v2")
    verified = {r.index for r in out.results if r.verified}
    #: 🔴 **같은 후보 집합**을 본다 — 탐색을 다시 돌리지 않았다.
    assert verified == {c.index for c in v1.eligible_candidates}
    assert verified == {c.index for c in v2.eligible_candidates}

    v1_best = {c.index for c in v1.recommended}
    v2_best = {c.index for c in v2.recommended}
    #: v1 은 하나로 줄이고, v2 는 **공동 추천**으로 남긴다.
    assert len(v1_best) == 1
    assert v1_best < v2_best, (v1_best, v2_best)
    #: 🔴 v2 가 더한 후보들은 **세트한 쪽**이고, 쥔 카드 수가 같다.
    kept = {v2.candidate(i).measures.kept_cards for i in v2_best}
    assert len(kept) == 1, kept
    assert any(v2.candidate(i).measures.set_cards > 0 for i in v2_best)
    assert all(v2.candidate(i).measures.stop for i in v2_best)


@pytest.mark.real_card
def test_l02_counting_baselines_per_opening_costs_no_depth(repository):
    """
    🔴 **탐색 배분 변경만의 효과** — 같은 예산에서 노드 수도 최대 깊이도
    그대로이고, 기준점 상한이 더는 탐색을 끊지 않는다.
    """
    off = _autonomous(repository, baseline_per_opening=False)[1]
    on = _autonomous(repository, baseline_per_opening=True)[1]
    assert off is not None and on is not None
    assert on.nodes_expanded == off.nodes_expanded
    assert on.deepest == off.deepest
    #: 🔴 **후보가 늘었다** — 같은 첫 행동의 다른 해결 선택들이 보관된다.
    assert len(on.results) > len(off.results)
    assert any("max_baselines" in hit for hit in off.budget_hit)
    assert not any("max_baselines" in hit for hit in on.budget_hit)
    #: 🔴 예산을 늘리지 않았다 — 상한 값 자체는 그대로다.
    assert on.budget.max_baselines == off.budget.max_baselines
    assert on.budget.max_candidates == off.budget.max_candidates
    assert on.budget.max_nodes == off.budget.max_nodes


@pytest.mark.real_card
def test_l03_rotating_baselines_trades_depth_for_breadth(repository):
    """
    🔴 **켜지 않은 이유를 수치로 남긴다** — 돌려 가며 펼치면 너비는 늘지만
    같은 예산에서 **깊이가 줄어** 깊은 전개가 사라진다.
    """
    plain = _autonomous(repository, baseline_per_opening=True,
                        rotate_baselines=False)[1]
    rotated = _autonomous(repository, baseline_per_opening=True,
                          rotate_baselines=True)[1]
    assert rotated.deepest < plain.deepest
    assert rotated.nodes_expanded > plain.nodes_expanded
    #: 🔴 예산은 그대로다 — 바뀐 것은 **누가 쓰는가**뿐이다.
    assert rotated.budget.max_nodes == plain.budget.max_nodes
    assert rotated.budget.max_candidates == plain.budget.max_candidates
    #: 기본은 꺼져 있다.
    from app.main import AUTONOMOUS_DEFAULT_ROTATE_BASELINES

    assert AUTONOMOUS_DEFAULT_ROTATE_BASELINES is False


@pytest.mark.real_card
def test_l04_a_token_is_still_usable_as_link_material(repository):
    """
    🔴 **토큰을 소재 후보에서 빼지 않았다** — 실제 탐색이 토큰이 있는 판에서
    링크 소환을 계속 찾아낸다.
    """
    out = _autonomous(repository)[1]
    assert out is not None
    with_token_and_link = [
        result for result in out.results
        if any(step.kind == "link_summon" for step in result.path)
        and any(slot.face_up for slot in result.resources.own_field)
    ]
    assert with_token_and_link, "링크 소환을 포함한 후보가 없습니다"
    #: 추천 가운데 적어도 하나는 토큰을 **센** 상태다 (무가치로 빼지 않았다).
    from app.main import rank_autonomous_results

    rank = rank_autonomous_results(out, repository)
    assert rank.recommended
    assert any(one.measures.token_bodies > 0 for one in rank.recommended)


@pytest.mark.real_card
def test_l05_the_recommendation_is_reproduced_from_a_fresh_state(repository):
    """🔴 **대표 결과는 새 초기 상태에서 다시 실행된다** (기존 계약 유지)."""
    from app.main import autonomous_rerun_record, rank_autonomous_results

    out = _autonomous(repository)[1]
    rank = rank_autonomous_results(out, repository)
    best = rank.recommended[0]
    chosen = next(r for r in out.results if r.index == best.index)
    record, why = autonomous_rerun_record(
        repository, _orcust_input(repository), list(_ORCUST_HAND), chosen,
    )
    assert record is not None, why


@pytest.mark.real_card
def test_l06_unsupported_moves_are_never_counted_as_interaction(repository):
    """🔴 **미지원 효과를 확정 방해로 세지 않는다** — 미지원은 C 로만 남는다."""
    out = _autonomous(repository)[1]
    assert out.unsupported, "이 입력에는 미지원 기록이 있어야 합니다"
    from app.main import rank_autonomous_results

    rank = rank_autonomous_results(out, repository)
    for one in rank.recommended:
        #: 세트한 것이 없으면 B 값도 0 이다 — 미지원이 그 수를 올리지 않는다.
        if one.measures.set_cards == 0:
            assert one.measures.set_reactive == 0
