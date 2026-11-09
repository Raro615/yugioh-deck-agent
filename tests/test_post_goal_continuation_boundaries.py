"""
Phase 6-AL 후속 — **후속 탐색의 두 경계 문제**.

기존 시험이 모두 통과한 뒤에도 남아 있던 두 결함을 고정한다.

======  ======================================================================
``A``   **후속 행동 상한이 패스까지 막았다.** 마지막 허용 비흐름 행동 뒤에
        아직 처리할 유발 기회가 남아 있으면, 비용으로 세지 않는 패스까지
        막혀 **정리된 후속 후보가 누락**됐다. 상한은 **새 비흐름 행동만**
        막아야 한다.
``B``   **서로 다른 선택 경로를 같은 기준점으로 연결했다.**
        :func:`~deck.report._baseline_of` 가 ``action_key`` 만 비교해서,
        같은 효과 발동이라도 **해결 중 고른 카드가 다른** 기준점을 구분하지
        못했다 — 그러면 자원 변화가 **다른 경로를 기준으로** 계산된다.
======  ======================================================================

🔴 **A 의 핵심은 production 확장 경로를 그대로 지난다.** 바꿔 끼우는 것은
``_attempts`` 하나이고(격리 그래프), 고리 · ``_open`` · ``_collect`` ·
``_dedup_key`` · ``admit`` · ``_stop_of`` · ``_many_outcome`` 은 전부
production 그대로다. 🔴 **격리 검증과 실제 엔진 검증을 가른다** — 격리
그래프는 "미정리 → 패스 → 정리" 를 만들어 상한 계약을 재고, 실제 카드
시험은 같은 분기가 **진짜 엔진에서도 돈다**는 것과 전체 경로 재생을 잰다.

🔴 **B 는 실제 선택 기록 자료형**(:class:`~agent.choice.ChoiceAsk`)으로
잰다 — 임의의 문자열로 대체하지 않는다.

🔴 **새 전개 능력도, 실전 강도 평가도 아니다.** 상한의 뜻과 기준점 연결을
고친 것뿐이다.
"""

from __future__ import annotations

import dataclasses

import pytest

import agent.bounded_search as bs
from agent.bounded_search import (
    BoundedSearch,
    ContinuationStop,
    FLOW_ACTION_KINDS,
    FieldGoal,
    FoundMeta,
    PathStep,
    ResultRole,
    SearchBudget,
    Termination,
)
from agent.choice import ChoiceAsk
from engine.action import PlayerActionKind

#: 🔴 진짜 ``GameState`` 를 흉내 낸 조각들은 **6-AI 의 격리 그래프에서
#: 그대로 가져온다** — ``summarize_resources`` 가 읽는 모양이 거기 이미
#: 맞춰져 있고, 두 벌로 두면 조용히 갈라진다.
from tests.test_bounded_search_multi_results import (  # noqa: E402
    GRAPH_GOAL_CARD,
    P0,
    _MChain,
    _MEnd,
    _MPriority,
    _MState,
    _MStep,
)

GIRSU = 69811710
GALATEA = 30741503


# ======================================================================
# A. 격리 그래프 — 미정리 상태와 패스
# ======================================================================
class _Edge:
    """간선 하나. ``kind`` 로 흐름 행동과 비흐름 행동을 가른다."""

    def __init__(self, source: str, target: str, kind):
        self.source = source
        self.target = target
        self.kind = kind

    def canonical_state(self) -> tuple:
        return ("edge", self.source, self.target, self.kind.value)


class _Legal:
    def __init__(self, allowed, held=()):
        self.allowed = tuple(allowed)
        self._held = tuple(held)

    def unsupported(self):
        return self._held


class _Duel:
    """
    꼬리표 하나. ``settled`` 가 거짓인 꼬리표는 ``end_phase`` 를 내놓지
    않으므로 :func:`~agent.bounded_search._is_settled` 가 **정리되지
    않았다**고 본다 — 실제 엔진에서 **선택적 유발 기회가 열려 있는** 자리와
    같은 모양이다.
    """

    def __init__(self, graph: "_Graph", label: str):
        self.graph = graph
        self.label = label
        self.state = _MState(label, goal=label in graph.goals)
        self.chain = _MChain()
        self.priority = _MPriority()
        self.step = _MStep()
        self.is_over = False
        self.to_act = P0

    def legal_actions(self, seat=None):
        out = [
            _Edge(self.label, target, kind)
            for target, kind in self.graph.out(self.label)
        ]
        if self.label in self.graph.settled:
            #: 🔴 ``end_phase`` 는 **범위 밖**이고 탐색이 건너뛴다 — 그래도
            #: ``_is_settled`` 는 이것이 허가되었는지로 "정리됨" 을 본다.
            out.append(_MEnd())
        return _Legal(out, held=self.graph.held.get(self.label, ()))


@dataclasses.dataclass(frozen=True)
class _Graph:
    edges: dict
    goals: frozenset
    settled: frozenset
    held: dict = dataclasses.field(default_factory=dict)

    def out(self, label):
        return tuple(self.edges.get(label, ()))


class _Search(BoundedSearch):
    """🔴 **바꿔 끼우는 것은 ``_attempts`` 하나다.**"""

    def __init__(self, graph: _Graph, **kwargs):
        super().__init__(**kwargs)
        self.graph = graph
        self.opened: list = []

    def _attempts(self, parent, action, ledger, started):
        self.opened.append((action.source, action.target, action.kind.value))
        ledger.nodes += 1
        return [
            bs._Attempt(
                accepted=True,
                reason=f"{action.source}→{action.target}",
                duel=_Duel(self.graph, action.target),
            )
        ]


NS = PlayerActionKind.NORMAL_SUMMON
PASS = PlayerActionKind.PASS

#: 최초 목표 도달(``G``) → 비흐름 행동 1회(``M``, **미정리**) → 패스(``D``,
#: 정리) → 또 비흐름 행동(``E``). ``X`` 는 기준점에서 바로 정리되는 다른
#: 후속이다.
TRIGGER_THEN_PASS = _Graph(
    edges={
        "S": (("G", NS),),
        "G": (("M", NS), ("X", NS)),
        "M": (("D", PASS),),
        "D": (("E", NS),),
    },
    goals=frozenset({"G", "M", "D", "X", "E"}),
    #: 🔴 ``M`` 만 정리되지 않았다 — 거기서 패스가 필요하다.
    settled=frozenset({"S", "G", "D", "X", "E"}),
)


def _walk(graph, **budget):
    search = _Search(
        graph,
        goal=FieldGoal(card_id=GRAPH_GOAL_CARD, seat=P0),
        budget=SearchBudget(max_seconds=30, **budget),
    )
    ledger = bs._Ledger()
    root = bs._Node(bs.Simulator.__new__(bs.Simulator), (), 0)
    #: 🔴 뿌리의 판만 손으로 꽂는다 — 그 뒤는 production 고리가 돈다.
    object.__setattr__(root, "sim", _RootSim(_Duel(graph, "S")))
    import time

    termination, _found = search._drive(root, ledger, time.monotonic())
    outcome = search._many_outcome(termination, ledger, 0.0, 0.0, tuple(
        bs.PathResult(
            index=slot + 1, path=path, resources=summary, goal_reason=reason,
            meta=ledger.result_meta.get(slot, FoundMeta()),
        )
        for slot, (path, summary, reason) in enumerate(ledger.results)
    ))
    return search, outcome


class _RootSim:
    """``_Node.sim`` 이 요구하는 것은 ``.duel`` 하나다."""

    def __init__(self, duel):
        self.duel = duel


def _labels(result):
    """그 결과가 밟은 꼬리표들 (간선의 목적지)."""
    return [step.action_key[2] for step in result.path]


def test_a01_the_cap_still_allows_the_pass_that_settles_the_board():
    """
    🔴 **상한 1에서 비흐름 행동 1회 뒤 패스를 거쳐 정리된 후보를
    수집한다** (§3-A-1 · 2).

    수정 전에는 패스가 막혀 ``M`` 에서 끝났고, 기준점만 남았다 — 실제로
    필요한 비흐름 행동은 1회인데 상한 2를 줘야 결과가 나왔다.
    """
    _search, outcome = _walk(TRIGGER_THEN_PASS, max_depth=4, max_nodes=40,
                             max_results=5, max_followup_actions=1,
                             max_baselines=1)
    assert len(outcome.baselines) == 1
    assert _labels(outcome.baselines[0]) == ["G"]

    passed = [one for one in outcome.continued_results
              if _labels(one) == ["G", "M", "D"]]
    assert passed, [(_labels(one), one.meta.followup_actions)
                    for one in outcome.continued_results]
    only = passed[0]
    #: 🔴 **비흐름 후속 행동은 1회이고 패스는 흐름으로 기록된다.**
    assert only.meta.followup_actions == 1
    assert only.meta.followup_flow == 1
    assert only.meta.reached_at == 1
    assert only.path[-1].kind == "pass"
    assert only.path[-1].kind in FLOW_ACTION_KINDS


def test_a02_a_second_spending_action_is_still_blocked():
    """
    🔴 **같은 상태에서 가능한 두 번째 비흐름 행동은 실행하지 않는다**
    (§3-A-3).

    ``D`` 에서 ``E`` 로 가는 간선은 비흐름이므로 상한 1 에서는 열리지
    않는다.
    """
    search, outcome = _walk(TRIGGER_THEN_PASS, max_depth=5, max_nodes=60,
                            max_results=5, max_followup_actions=1,
                            max_baselines=1)
    assert all("E" not in _labels(one) for one in outcome.results), \
        [_labels(one) for one in outcome.results]
    #: 🔴 **그 간선을 적용조차 하지 않았다** (노드를 만들지 않았다).
    assert ("D", "E", "normal_summon") not in search.opened
    #: 그리고 그 사실이 종료 사유에 남는다.
    assert any("max_followup_actions=1" in line
               for line in outcome.budget_hit), outcome.budget_hit


def test_a03_an_unsettled_state_is_never_a_candidate():
    """🔴 **아직 정리되지 않은 상태를 결과로 내놓지 않는다** (§3-A-5)."""
    _search, outcome = _walk(TRIGGER_THEN_PASS, max_depth=4, max_nodes=40,
                             max_results=5, max_followup_actions=1,
                             max_baselines=1)
    for one in outcome.results:
        assert _labels(one)[-1] != "M", _labels(one)
        assert ":M:" not in one.resources.state_hash
    #: 🔴 **그래도 그 자리를 지나갔다는 사실은 적힌다.**
    assert any("정리되지 않아" in note for note in outcome.followup_notes), \
        outcome.followup_notes


def test_a04_end_phase_is_still_out_of_scope():
    """
    🔴 **"흐름 행동" 이라는 이유로 ``end_phase`` 를 허용하지 않는다**
    (§3-A-7).
    """
    search, outcome = _walk(TRIGGER_THEN_PASS, max_depth=5, max_nodes=60,
                            max_results=5, max_followup_actions=1,
                            max_baselines=1)
    assert "end_phase" in " ".join(outcome.out_of_scope)
    for one in outcome.results:
        assert all(step.kind != "end_phase" for step in one.path)
    assert all(kind != "end_phase" for _s, _t, kind in search.opened)


def test_a05_the_depth_cap_still_binds_during_flow_processing():
    """
    🔴 **흐름 처리 중에도 깊이 상한이 작동한다** (§3-A-6).

    ``G``(1) → ``M``(2) → ``D``(3) 인데 깊이 2 로 두면 패스를 밟지
    못하고, **그 이유가 깊이 상한으로 적힌다** (후속 상한과 다른 상한이다).
    """
    _search, outcome = _walk(TRIGGER_THEN_PASS, max_depth=2, max_nodes=40,
                             max_results=5, max_followup_actions=1,
                             max_baselines=1)
    assert all(_labels(one) != ["G", "M", "D"] for one in outcome.results)
    assert any("max_depth=2" in line for line in outcome.budget_hit)
    joined = " ".join(outcome.followup_notes)
    assert "깊이 상한" in joined, outcome.followup_notes


def test_a06_a_cap_bound_node_without_flow_says_why_it_stopped():
    """
    🔴 **가능한 흐름 처리 없이 멈추면 그 이유를 기록한다** (§3-A-H).

    ``D`` 는 정리됐지만 남은 간선이 비흐름뿐이므로 상한 때문에 멈춘다 —
    "흐름 처리가 없다" 와 "상한에 닿았다" 를 함께 적는다.
    """
    _search, outcome = _walk(TRIGGER_THEN_PASS, max_depth=5, max_nodes=60,
                             max_results=5, max_followup_actions=1,
                             max_baselines=1)
    joined = " ".join(outcome.followup_notes)
    assert "상한" in joined
    assert "흐름 처리" in joined, outcome.followup_notes
    #: 🔴 상한에 닿은 뒤에도 **흐름 처리는 이어 갔다**는 사실이 적힌다.
    assert "이어" in joined or "계속" in joined, outcome.followup_notes


def test_a07_the_flow_only_node_cannot_loop_forever():
    """
    🔴 **반복 방지가 흐름 처리에도 적용된다** (§3-A-6 · F).

    패스가 같은 자리로 돌아오는 그래프에서도 중복 제거와 노드 상한이
    고리를 끊는다.
    """
    loop = _Graph(
        edges={
            "S": (("G", NS),),
            "G": (("M", NS),),
            #: 🔴 패스가 제자리로 돌아온다.
            "M": (("M", PASS),),
        },
        goals=frozenset({"G", "M"}),
        settled=frozenset({"S", "G"}),
    )
    search, outcome = _walk(loop, max_depth=6, max_nodes=12, max_results=5,
                            max_followup_actions=1, max_baselines=1)
    assert outcome.nodes_expanded <= 12 + 1
    assert len(search.opened) <= 12 + 1
    #: 미정리 상태는 결과가 아니므로 후속 후보가 없고, 기준점은 남는다.
    assert len(outcome.baselines) == 1
    assert outcome.termination in (
        Termination.EXHAUSTED, Termination.BUDGET_EXCEEDED,
    )


def test_a08_the_stop_reason_names_the_action_cap():
    """수집한 후보의 멈춘 이유가 **상한**으로 적힌다 (§3-A-D)."""
    _search, outcome = _walk(TRIGGER_THEN_PASS, max_depth=4, max_nodes=40,
                             max_results=5, max_followup_actions=1,
                             max_baselines=1)
    stops = {one.meta.stop for one in outcome.continued_results}
    assert ContinuationStop.ACTION_CAP in stops, stops


# ======================================================================
# A-실제 엔진 — 같은 분기가 진짜 엔진에서도 돈다
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
def real_capped(opening):
    """
    실제 카드 · 후속 상한 1. 🔴 **선택적 유발을 발동하지 않고 패스하는
    자리**가 실제로 나오는 입력이다 (기르수 소환 뒤의 발동 기회).
    """
    search = BoundedSearch(
        goal=FieldGoal(card_id=GIRSU, seat=0),
        budget=SearchBudget(max_depth=4, max_nodes=120, max_seconds=240,
                            max_results=5, max_followup_actions=1,
                            max_baselines=1),
    )
    return search, search.run_many(opening(), rerun_from=opening())


def test_a09_the_real_engine_takes_the_optional_trigger_pass(real_capped):
    """
    🔴 **실제 엔진에서도 선택적 유발을 발동하지 않고 패스하는 자리를
    지난다** (§3-A-4).

    기준점 자체가 `일반 소환 → 패스` 이고, 그 패스는 **후속 비흐름 행동으로
    세지 않는다.**
    """
    _search, outcome = real_capped
    baseline = outcome.baselines[0]
    kinds = [step.kind for step in baseline.path]
    assert "pass" in kinds, kinds
    assert baseline.meta.followup_actions == 0
    assert baseline.meta.followup_flow == 0
    #: 🔴 상한에 닿은 뒤 **흐름 처리를 이어 간다**는 사실이 실제 실행에서도
    #: 적힌다 (수정 전에는 "더 펼치지 않았습니다" 였다).
    joined = " ".join(outcome.followup_notes)
    assert "흐름 처리" in joined, outcome.followup_notes


def test_a10_the_real_follow_up_path_replays_from_the_start(
    opening, real_capped
):
    """
    🔴 **수집한 전체 경로를 원래 초기 상태에서 재생해 최초 도달과 최종
    상태를 확인한다** (§3-A-8).
    """
    _search, outcome = real_capped
    goal = FieldGoal(card_id=GIRSU, seat=0)
    assert outcome.continued_results
    for one in outcome.continued_results:
        rerun = bs.rerun_steps(
            opening(), one.path, goal,
            expect_field=one.resources.own_field_rows,
            expect_hash=one.resources.state_hash,
            reached_at=one.meta.reached_at,
        )
        assert rerun.ok, rerun.reason
        assert rerun.first_arrival_confirmed is True
        assert rerun.first_arrival_at == one.meta.reached_at
        assert rerun.matches_search is True
        assert rerun.goal_kept == one.meta.goal_kept


# ======================================================================
# B. 기준점 식별 — 실제 선택 기록 자료형으로
# ======================================================================
def _ask(index, instance, card_id):
    """실제 :class:`~agent.choice.ChoiceAsk` 하나."""
    return ChoiceAsk(
        index=index, label="테스트 선택", minimum=1, maximum=1,
        offered=((10, 111), (11, 222)),
        chosen=(instance,), chosen_card_ids=(card_id,),
    )


def _step(order, kind, key, choices=()):
    return PathStep(order=order, kind=kind, action_key=key,
                    choices=tuple(choices))


@pytest.fixture
def choice_paths():
    """
    같은 ``action_key``, **다른 선택**인 두 기준점과 그 각각의 후속.

    🔴 실제 카드가 아니라 경로 자료형으로 만든 격리 fixture다 — 재는 것은
    **기준점 식별**이고 전개가 아니다.
    """
    summon = ("normal_summon", 0, 75, (), None, None, ())
    effect = ("activate_effect", 0, 75, (), (GIRSU, 0), None, ())
    extra = ("set_spell_trap", 0, 76, (), None, None, ())

    first = (
        _step(1, "normal_summon", summon),
        _step(2, "activate_effect", effect, (_ask(0, 10, 111),)),
    )
    second = (
        _step(1, "normal_summon", summon),
        #: 🔴 같은 행동, **다른 카드를 골랐다.**
        _step(2, "activate_effect", effect, (_ask(0, 11, 222),)),
    )
    return first, second, extra


def _result(index, path, resources, *, reached_at, role, followups=0):
    """
    경로 자료형만으로 만든 결과 하나.

    🔴 **검증된 것으로 만든다** — 요약은 **재생 검증된** 후속 후보만 그리므로
    (6-AL §6), 검증되지 않은 스텁으로는 기준점 연결이 출력에 나타나지
    않는다. 재생 결과도 **그 경로의 자원 요약 그대로** 넣어, "검증됐다" 는
    말이 거짓이 되지 않게 한다.
    """
    return bs.PathResult(
        index=index, path=path, resources=resources, goal_reason="[스텁]",
        rerun=bs.RerunResult(
            ok=True, reason="[스텁] 같은 판에 닿았다", steps=len(path),
            goal_reached=True, matches_search=True, resources=resources,
            first_arrival_at=(reached_at
                              if role is ResultRole.CONTINUED else 0),
            first_arrival_confirmed=True, goal_kept=True,
        ),
        resources_match=True,
        meta=FoundMeta(role=role, reached_at=reached_at,
                       followup_actions=followups,
                       goal_kept=True),
    )


@pytest.fixture
def two_baselines(opening, choice_paths):
    """두 기준점과, **두 번째** 기준점에서 이어진 후속 후보 하나."""
    first, second, extra = choice_paths
    resources = bs.summarize_resources(opening(), 0)
    base_one = _result(1, first, resources, reached_at=2,
                       role=ResultRole.FIRST_ARRIVAL)
    base_two = _result(2, second, resources, reached_at=2,
                       role=ResultRole.FIRST_ARRIVAL)
    candidate = _result(
        3, second + (_step(3, "set_spell_trap", extra),), resources,
        reached_at=2, role=ResultRole.CONTINUED, followups=1,
    )
    outcome = bs.MultiSearchOutcome(
        goal=FieldGoal(card_id=GIRSU, seat=0),
        budget=SearchBudget(max_results=5, max_followup_actions=1,
                            max_baselines=2),
        termination=Termination.EXHAUSTED,
        results=(base_one, base_two, candidate),
    )
    return outcome, base_one, base_two, candidate


def test_b01_two_baselines_differ_by_their_choices(two_baselines):
    """
    🔴 **``action_key`` 가 같고 선택이 다른 두 기준점을 구별한다**
    (§3-B-1 · 2).

    수정 전에는 첫 기준점을 돌려주었고, 그러면 자원 변화가 **다른 경로를
    기준으로** 계산됐다.
    """
    from deck import report

    outcome, _base_one, base_two, candidate = two_baselines
    found = report._baseline_of(outcome, candidate)
    assert found is base_two, getattr(found, "index", None)
    assert found.index == 2


def test_b02_the_link_survives_a_reordered_baseline_list(two_baselines):
    """🔴 **기준점 목록 순서를 바꿔도 연결이 유지된다** (§3-B-3)."""
    from deck import report

    outcome, base_one, base_two, candidate = two_baselines
    flipped = dataclasses.replace(
        outcome, results=(base_two, base_one, candidate),
    )
    assert report._baseline_of(flipped, candidate) is base_two


def test_b03_a_different_choice_order_is_not_a_match(opening, choice_paths):
    """
    🔴 **선택 순서나 선택 대상이 다르면 잘못 일치시키지 않는다** (§3-B-4).
    """
    from deck import report

    first, _second, extra = choice_paths
    resources = bs.summarize_resources(opening(), 0)
    #: 같은 두 선택을 **순서만 바꿔** 적은 기준점.
    swapped_step = _step(
        2, "activate_effect", first[1].action_key,
        (_ask(1, 10, 111), _ask(0, 11, 222)),
    )
    swapped = (first[0], swapped_step)
    base = _result(1, swapped, resources, reached_at=2,
                   role=ResultRole.FIRST_ARRIVAL)
    candidate = _result(
        2, first + (_step(3, "set_spell_trap", extra),), resources,
        reached_at=2, role=ResultRole.CONTINUED, followups=1,
    )
    outcome = bs.MultiSearchOutcome(
        goal=FieldGoal(card_id=GIRSU, seat=0),
        budget=SearchBudget(max_results=5, max_followup_actions=1),
        termination=Termination.EXHAUSTED,
        results=(base, candidate),
    )
    #: 🔴 **일치하는 기준점이 없다** — 임의의 첫 기준점으로 대체하지 않는다.
    assert report._baseline_of(outcome, candidate) is None


def test_b04_a_path_without_choices_still_links(opening, choice_paths):
    """🔴 **선택이 없는 기존 경로는 그대로 연결된다** (§3-B-5)."""
    from deck import report

    _first, _second, extra = choice_paths
    resources = bs.summarize_resources(opening(), 0)
    plain = (_step(1, "normal_summon", ("normal_summon", 0, 75)),)
    base = _result(1, plain, resources, reached_at=1,
                   role=ResultRole.FIRST_ARRIVAL)
    candidate = _result(
        2, plain + (_step(2, "set_spell_trap", extra),), resources,
        reached_at=1, role=ResultRole.CONTINUED, followups=1,
    )
    outcome = bs.MultiSearchOutcome(
        goal=FieldGoal(card_id=GIRSU, seat=0),
        budget=SearchBudget(max_results=5, max_followup_actions=1),
        termination=Termination.EXHAUSTED,
        results=(base, candidate),
    )
    assert report._baseline_of(outcome, candidate) is base


def test_b05_the_report_omits_the_comparison_when_nothing_matches(
    repository, opening, choice_paths
):
    """
    🔴 **기준점을 찾지 못하면 비교를 생략하고 이유를 적는다 — 후속 경로
    자체는 보존한다** (§3-B-6).
    """
    from deck import report

    first, _second, extra = choice_paths
    resources = bs.summarize_resources(opening(), 0)
    orphan = _result(
        1, first + (_step(3, "set_spell_trap", extra),), resources,
        reached_at=2, role=ResultRole.CONTINUED, followups=1,
    )
    outcome = bs.MultiSearchOutcome(
        goal=FieldGoal(card_id=GIRSU, seat=0),
        budget=SearchBudget(max_results=5, max_followup_actions=1),
        termination=Termination.EXHAUSTED,
        results=(orphan,),
    )
    brief = report.render_multi_search_brief(outcome, repository)
    assert "기준점을 찾지 못해" in brief
    #: 🔴 경로 자체는 남는다.
    assert "[결과 1]" in brief
    assert "뒤에 더 한 것:" in brief


def test_b06_the_output_names_the_right_baseline(repository, two_baselines):
    """
    🔴 **요약·상세에 올바른 기준점 ID 와 자원 변화가 나타난다** (§3-B-8).
    """
    from deck import report

    outcome, _base_one, _base_two, _candidate = two_baselines
    brief = report.render_multi_search_brief(outcome, repository)
    detail = report.render_multi_search(outcome, repository)
    #: 🔴 **결과 2** 가 기준점이다 (결과 1 이 아니다).
    assert "기준점(결과 2) 대비 자원 변화" in brief
    assert "기준점(결과 1) 대비 자원 변화" not in brief
    assert "후속 전개 (기준점과 전체 경로)" in detail


def test_b07_a_real_run_links_every_candidate_to_its_own_prefix(
    repository, draft
):
    """
    🔴 **실제 실행에서도 후속 후보가 자기 경로의 앞부분과 이어진다**
    (§3-B-7).

    대표 교체·병합을 거친 결과에서도 기준점의 경로가 후보 경로의
    **앞부분과 똑같아야** 한다 — 선택 기록까지 포함해서.
    """
    from app.main import bounded_search_many_opening
    from deck import report
    from deck.combo_policy import ORCUST_GIRSU_LINE

    _setup, outcome = bounded_search_many_opening(
        repository, draft, list(ORCUST_GIRSU_LINE.hand),
        card_id=GALATEA, max_results=2, followups=1,
    )
    assert outcome is not None
    assert outcome.continued_results
    for one in outcome.continued_results:
        base = report._baseline_of(outcome, one)
        assert base is not None, one.index
        reached = one.meta.reached_at
        assert len(base.path) == reached
        for mine, theirs in zip(base.path, one.path[:reached]):
            assert tuple(mine.action_key) == tuple(theirs.action_key)
            assert len(mine.choices) == len(theirs.choices)
            for left, right in zip(mine.choices, theirs.choices):
                assert left.index == right.index
                assert tuple(left.chosen) == tuple(right.chosen)
                assert tuple(left.chosen_card_ids) == \
                    tuple(right.chosen_card_ids)
    #: 🔴 **실제 선택 기록이 들어 있는 경로다** (빈 경로로 통과하지 않는다).
    assert any(step.choices for one in outcome.continued_results
               for step in one.path)
