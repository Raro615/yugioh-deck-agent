"""
Phase 6-AI — **복수 전개 경로 수집과 최종 자원 비교**.

이 파일이 고정하는 사실은 다섯이다.

======  ======================================================================
``A``   같은 초기 상태에서 **서로 다른** 성공 결과 여럿을 모은다. 목표에
        닿은 분기는 **더 펼치지 않고**, 결과 수 상한에 닿으면 그 사실이
        종료 사유에 남는다.
``B``   **탐색 중의 중복 제거와 성공 결과의 중복 제거는 목적이 다르다.**
        전자는 ``node_key``, 후자는 ``outcome_key`` 이고 두 기준은 섞이지
        않는다. 필드가 같아도 **사용 제한이 다르면 다른 결과**다.
``C``   제시하는 **대표 경로를 전부 새 초기 상태에서 재생**한다. 재생
        실패는 그 결과에만 적히고, 하나가 실패해도 다른 결과를 버리지
        않으며, 재생 오류를 "탐색이 아무것도 못 찾았다" 로 바꾸지 않는다.
``D``   **실제 카드 입력**에서 서로 다른 결과가 둘 이상 나오고, 요약이
        재생된 상태와 같다.
``E``   6-AH · 6-AH 보완의 동작과 **단일 결과 모드**가 그대로다.
======  ======================================================================

🔴 **A · B · C 절의 일부는 격리된 합성 그래프와 스텁으로 잰다 — 실제 카드
전개가 아니다.** 바꿔 끼우는 것은 "그 행동을 적용하면 어떤 상태가
되는가"(``_attempts``)와, C 절 일부에서 "재생이 어떻게 끝났는가"
(``rerun_steps``) 둘뿐이고, **고리 · ``_open`` · ``_collect`` ·
``outcome_key`` · ``representative_order`` · ``rerun_results`` 의 집계 ·
``_many_outcome`` 은 production 그대로** 돈다. 실제 카드로 재는 것은 D
절과 ``tests/test_bounded_search_first_pass.py`` 이고, 이 파일은 그것을
**대신하지 않는다.**

🔴 **"모은 결과가 가능한 모든 전개" 라고 주장하지 않는다.** 이 파일은
탐색의 완전성도 최적성도 재지 않는다 — 돌려준 것이 **서로 다르고 재생으로
뒷받침되는가**만 잰다.

🔴 **강약 평가가 아니다.** 어느 결과가 더 좋은지 고르는 코드도 시험도
여기 없다.
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass

import pytest

import agent.bounded_search as bs
from agent.bounded_search import (
    BoundedSearch,
    BoundedSearchError,
    CONCEALED_CARD,
    FieldGoal,
    MULTI_DEFAULT_MAX_RESULTS,
    PathResult,
    RESULTS_CAP,
    RerunResult,
    ResourceSummary,
    SearchBudget,
    Termination,
    outcome_key,
    representative_order,
    rerun_steps,
    summarize_resources,
)
from agent.simulation import Simulator
from engine.action import PlayerActionKind
from engine.state.rule_usage import RuleActionKind, RuleUsageRegistry
from engine.state.summon_usage import SummonUsageRegistry
from engine.state.use_registry import UseRegistry
from engine.vocabulary import Zone

P0 = 0

#: 🔴 **격리 그래프 전용 꼬리표다 — 실제 카드 ID 가 아니다.**
GRAPH_GOAL_CARD = 999_000_002


# ======================================================================
# 격리된 그래프 — Duel 처럼 보이게 한 최소한의 것
# ======================================================================
@dataclass(frozen=True, slots=True)
class Graph:
    """꼬리표와 간선. :attr:`goals` 의 꼬리표에서 목표 카드가 보인다."""

    edges: dict
    goals: frozenset
    #: 꼬리표 → 그 상태에서 **이미 쓰였다고 기록할** 카드명 사용.
    #: §2 가 요구하는 "필드가 같아도 사용 제한이 다르면 다른 결과" 를
    #: 격리해 재려고 둔다.
    marks: dict = dataclasses.field(default_factory=dict)

    def out(self, label: str) -> tuple:
        return tuple(self.edges.get(label, ()))


class _MPosition:
    def __init__(self, value: str):
        self.value = value


class _MInstance:
    def __init__(self, value: int):
        self.value = value


class _MCard:
    """``_slots_of`` 가 읽는 것만 들고 있는 카드."""

    def __init__(self, card_id: int, instance: int, *, face_up: bool = True):
        self.card_id = card_id
        self.instance_id = _MInstance(instance)
        self.is_faceup = face_up
        self.position = _MPosition(
            "FACEUP_ATTACK" if face_up else "FACEDOWN_DEFENSE"
        )
        self.sequence = 0


class _MZone:
    def __init__(self, cards=()):
        self._cards = tuple(cards)

    def cards(self):
        return list(self._cards)

    def __len__(self):
        return len(self._cards)


class _MPlayer:
    def __init__(self, player_id: int, zones: dict):
        self.player_id = player_id
        self.zones = zones

    def zone(self, zone):
        return self.zones.get(zone, _MZone(()))


class _MPhase:
    value = "MAIN1"


class _MTurn:
    turn_number = 1
    phase = _MPhase()


class _MState:
    """
    ``state_hash`` 가 **꼬리표 + 기록된 사용 제한**이다.

    🔴 **진짜 ``GameState`` 를 흉내 낸 것이 아니다.** 진짜 쪽은
    ``canonical_state`` 에 존과 ``uses`` 를 모두 담아 해시를 만든다 —
    여기서는 그 성질만 따와 "사용 제한이 다르면 해시가 다르다" 를 지킨다.
    """

    def __init__(self, label: str, *, goal: bool, mark=None):
        self.label = label
        mine = {
            Zone.MZONE: _MZone(()),
            Zone.EMZONE: _MZone(
                (_MCard(GRAPH_GOAL_CARD, 1),) if goal else ()
            ),
            Zone.HAND: _MZone((_MCard(11091375, 2),)),
            Zone.SZONE: _MZone(()),
            Zone.GRAVE: _MZone(()),
            Zone.REMOVED: _MZone(()),
            Zone.DECK: _MZone(()),
            Zone.EXTRA: _MZone(()),
        }
        theirs = {
            Zone.MZONE: _MZone(()),
            Zone.EMZONE: _MZone(()),
            Zone.SZONE: _MZone(()),
            Zone.GRAVE: _MZone(()),
            Zone.REMOVED: _MZone(()),
            Zone.HAND: _MZone(()),
            Zone.DECK: _MZone(()),
            Zone.EXTRA: _MZone(()),
        }
        self._players = (_MPlayer(0, mine), _MPlayer(1, theirs))
        self.turn = _MTurn()
        self.uses = UseRegistry()
        self.summon_uses = SummonUsageRegistry()
        self.rule_uses = RuleUsageRegistry()
        if mark is not None:
            self.uses.mark_card_name_used(0, mark)

    @property
    def players(self):
        return self._players

    def state_hash(self) -> str:
        return f"graph:{self.label}:{self.uses.canonical_state()}"

    def player(self, seat: int):
        return self._players[seat]


class _MWindow:
    value = "none"


class _MPriority:
    is_open = False
    window = _MWindow()


class _MChain:
    is_empty = True

    def __len__(self):
        return 0


class _MStep:
    value = "open"


class _MAction:
    """간선 하나. ``END_PHASE`` 가 아니어야 탐색이 펼친다."""

    def __init__(self, source: str, target: str):
        self.source = source
        self.target = target
        self.kind = PlayerActionKind.NORMAL_SUMMON

    def canonical_state(self) -> tuple:
        return ("edge", self.source, self.target)


class _MEnd:
    """``end_phase`` 자리 — ``_is_settled`` 가 이것을 묻는다."""

    kind = PlayerActionKind.END_PHASE

    def canonical_state(self) -> tuple:
        return ("end_phase",)


class _MLegal:
    def __init__(self, allowed):
        self.allowed = tuple(allowed)

    def unsupported(self):
        return ()


class _MDuel:
    def __init__(self, graph: Graph, label: str):
        self.graph = graph
        self.label = label
        self.state = _MState(
            label, goal=label in graph.goals, mark=graph.marks.get(label)
        )
        self.chain = _MChain()
        self.priority = _MPriority()
        self.step = _MStep()
        self.is_over = False
        self.to_act = P0

    def legal_actions(self, seat=None):
        return _MLegal(
            [_MEnd()]
            + [_MAction(self.label, nxt) for nxt in self.graph.out(self.label)]
        )


class _MSearch(BoundedSearch):
    """🔴 **바꿔 끼우는 것은 ``_attempts`` 하나다.**"""

    def __init__(self, graph: Graph, **kwargs):
        super().__init__(**kwargs)
        self.graph = graph
        self.opened: list[str] = []

    def _attempts(self, parent, action, ledger, started):
        self.opened.append(f"{action.source}→{action.target}")
        ledger.nodes += 1
        return [
            bs._Attempt(
                accepted=True,
                reason=f"{action.source}→{action.target}",
                duel=_MDuel(self.graph, action.target),
            )
        ]


def walk_many(
    graph: Graph,
    *,
    start: str = "R",
    max_depth: int = 6,
    max_nodes: int = 200,
    max_results: int = 3,
    dedup: bool = True,
):
    """
    그 그래프를 **production 고리로** 걸어 복수 결과를 모은다.

    돌려주는 것은 ``(search, ledger, outcome)`` 이고, ``outcome`` 은
    ``_many_outcome`` 이 만든 진짜 :class:`MultiSearchOutcome` 이다 —
    재생은 돌리지 않는다 (``rerun_steps`` 는 진짜 ``Duel`` 을 요구한다).
    """
    search = _MSearch(
        graph,
        goal=FieldGoal(card_id=GRAPH_GOAL_CARD, seat=P0),
        budget=SearchBudget(
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_choice_branches=0,
            max_results=max_results,
            dedup=dedup,
        ),
    )
    ledger = bs._Ledger()
    root = bs._Node(Simulator(_MDuel(graph, start)), (), 0)
    started = time.monotonic()
    termination, found = search._drive(root, ledger, started)
    results = tuple(
        PathResult(
            index=slot + 1,
            path=path,
            resources=summary,
            goal_reason=reason,
            duplicates=ledger.result_dups.get(slot, 0),
        )
        for slot, (path, summary, reason) in enumerate(ledger.results)
    )
    outcome = search._many_outcome(
        termination, ledger, time.monotonic() - started, 0.0, results
    )
    assert found is None, "복수 결과 모드는 목표를 찾아도 고리를 멈추지 않는다"
    return search, ledger, outcome


#: 서로 다른 두 목표. ``R`` 에서 갈라져 각각 한 걸음.
TWO_GOALS = Graph(
    edges={"R": ("A", "B"), "A": ("G1",), "B": ("G2",)},
    goals=frozenset({"G1", "G2"}),
)

#: 목표 뒤에 **또 목표**가 있다. 🔴 목표에 닿은 분기를 더 펼치면 ``G1b`` 도
#: 결과가 되고, 그것은 "같은 경로에서 한 수 더 한 것" 이다.
GOAL_THEN_MORE = Graph(
    edges={"R": ("G1",), "G1": ("G1b",)},
    goals=frozenset({"G1", "G1b"}),
)

#: 목표 셋 — 결과 수 상한을 재려고 둔다.
THREE_GOALS = Graph(
    edges={"R": ("A", "B", "C"), "A": ("G1",), "B": ("G2",), "C": ("G3",)},
    goals=frozenset({"G1", "G2", "G3"}),
)

#: 두 경로가 **같은 상태**에 닿는다. 🔴 긴 쪽(``R→A→C→G``)이 먼저,
#: 짧은 쪽(``R→B→G``)이 나중이다 — 대표가 교체되어야 한다.
SAME_GOAL_TWICE = Graph(
    edges={"R": ("A", "B"), "A": ("C",), "C": ("G",), "B": ("G",)},
    goals=frozenset({"G"}),
)

#: 필드는 같고(``G``) **기록된 사용 제한만 다른** 두 목표.
SAME_FIELD_OTHER_USES = Graph(
    edges={"R": ("A", "B"), "A": ("Gx",), "B": ("Gy",)},
    goals=frozenset({"Gx", "Gy"}),
    marks={"Gy": 11091375},
)


# ======================================================================
# A. 복수 성공 결과 수집
# ======================================================================
def test_a01_collects_two_distinct_results():
    """서로 다른 두 결과를 **둘 다** 모은다."""
    _search, ledger, outcome = walk_many(TWO_GOALS)
    assert outcome.found == 2
    assert len({result.resources.state_hash for result in outcome.results}) == 2
    assert ledger.duplicate_results == 0


def test_a02_goal_branch_is_not_expanded_further():
    """
    🔴 **목표에 닿은 분기를 더 펼치지 않는다.**

    ``G1b`` 도 목표이지만 ``G1`` 뒤에 있으므로 결과가 되지 않는다 — 같은
    경로에서 한 수 더 한 것을 별개의 전개로 늘리지 않는다 (§1).
    """
    search, _ledger, outcome = walk_many(GOAL_THEN_MORE)
    assert outcome.found == 1
    assert "G1→G1b" not in search.opened
    assert all("G1b" not in result.resources.state_hash
               for result in outcome.results)


def test_a03_result_cap_is_recorded_in_the_termination():
    """결과 수 상한에 닿은 **사실이 종료 사유에 남는다.**"""
    _search, ledger, outcome = walk_many(THREE_GOALS, max_results=2)
    assert outcome.found == 2
    assert outcome.hit_result_cap
    assert "max_results=2" in outcome.budget_hit
    assert outcome.termination is Termination.BUDGET_EXCEEDED
    #: 🔴 상한이 고리를 끊었으므로 **끝까지 펼친 것이 아니다.**
    assert not ledger.stack_emptied
    assert not outcome.search_exhausted


def test_a04_results_survive_a_spent_budget():
    """🔴 **예산이 끝나도 찾은 결과는 보존한다.**"""
    _search, _ledger, outcome = walk_many(
        THREE_GOALS, max_results=5, max_nodes=4
    )
    assert outcome.found >= 1
    assert any("max_nodes=" in line for line in outcome.budget_hit)
    assert outcome.reached
    assert not outcome.search_exhausted


def test_a05_found_and_exhausted_are_separate_facts():
    """🔴 **"찾은 결과가 있음" 과 "탐색을 끝까지 수행함" 을 가른다.**"""
    _search, ledger, outcome = walk_many(TWO_GOALS, max_results=5)
    assert outcome.reached and outcome.found == 2
    assert ledger.stack_emptied
    assert outcome.search_exhausted
    assert not outcome.budget_hit
    #: 🔴 그래도 "가능한 모든 전개" 라는 말은 어디에도 없다 — 이 사실은
    #: 보고 문장이 들고 있다 (E 절).


def test_a06_duplicate_paths_do_not_raise_the_result_count():
    """🔴 **중복을 발견했다는 이유로 서로 다른 결과 수가 늘지 않는다.**"""
    _search, ledger, outcome = walk_many(SAME_GOAL_TWICE, max_results=5)
    assert outcome.found == 1
    assert outcome.duplicate_results == 1
    assert ledger.duplicate_results == 1
    assert outcome.results[0].duplicates == 1


def test_a07_single_result_mode_is_selected_by_the_budget():
    """복수 모드는 **명시적으로** 고른다 — 기본은 단일 결과다."""
    assert SearchBudget().max_results == 1
    assert not SearchBudget().many
    assert SearchBudget(max_results=2).many
    assert MULTI_DEFAULT_MAX_RESULTS == 3


def test_a08_result_cap_is_small_and_explicit():
    """작고 분명한 상한. 0 도 상한 초과도 **거절한다.**"""
    assert RESULTS_CAP == 5
    for bad in (0, -1, RESULTS_CAP + 1, True, 2.5):
        with pytest.raises(BoundedSearchError):
            SearchBudget(max_results=bad)


def test_a09_run_many_refuses_single_result_budgets(real_duel):
    """``run_many`` 를 단일 결과 예산으로 부르면 **거절한다.**"""
    search = BoundedSearch(goal=FieldGoal(card_id=GALATEA, seat=P0))
    with pytest.raises(BoundedSearchError, match="max_results"):
        search.run_many(real_duel)


def test_a10_run_many_checks_both_duels(real_duel):
    """격리 그래프를 ``run_many`` 에 바로 넣지 않는다 — **거절한다.**"""
    search = BoundedSearch(
        goal=FieldGoal(card_id=GALATEA, seat=P0),
        budget=SearchBudget(max_results=2),
    )
    with pytest.raises(BoundedSearchError, match="Duel 이 필요합니다"):
        search.run_many(_MDuel(TWO_GOALS, "R"))
    with pytest.raises(BoundedSearchError, match="재생할 Duel"):
        search.run_many(real_duel, rerun_from=object())


def test_a11_budget_describes_the_result_count_only_when_many():
    said = SearchBudget(max_results=3).describe_ko()
    assert "결과 3개" in said and "재생" in said
    assert "결과" not in SearchBudget().describe_ko()


# ======================================================================
# B. 결과 동일성과 대표 경로
# ======================================================================
def test_b01_node_key_and_outcome_key_have_different_purposes():
    """
    🔴 **두 기준을 명시적으로 가른다** (§2).

    ``node_key`` 는 "이 상태를 또 펼칠 필요가 있는가" 를 묻고, 정리되지
    않은 자리(체인 중)에서는 ``None`` 을 돌려 **중복 제거를 끈다.**
    ``outcome_key`` 는 "이것이 같은 성공 결과인가" 를 묻고, 정리되지 않은
    자리를 성공으로 **세지 않는다** — 그래서 거절한다.
    """
    duel = _MDuel(TWO_GOALS, "G1")
    legal = duel.legal_actions()
    assert bs.node_key(duel, legal) is not None
    assert outcome_key(duel, legal, P0)

    class _Busy(_MChain):
        is_empty = False

        def __len__(self):
            return 1

    duel.chain = _Busy()
    assert bs.node_key(duel, legal) is None
    with pytest.raises(BoundedSearchError, match="정리되지 않은"):
        outcome_key(duel, legal, P0)


def test_b02_same_field_other_uses_are_different_results():
    """
    🔴 **필드가 같아도 사용 제한이 다르면 다른 결과다** (§2).

    두 꼬리표는 목표 카드가 같은 자리에 있고, **기록된 카드명 사용만**
    다르다.
    """
    _search, _ledger, outcome = walk_many(SAME_FIELD_OTHER_USES, max_results=5)
    assert outcome.found == 2
    fields = {result.resources.own_field_rows for result in outcome.results}
    assert len(fields) == 1, "두 결과의 자신 필드는 같다"
    uses = {
        tuple((record.kind, record.label) for record in result.resources.uses)
        for result in outcome.results
    }
    assert len(uses) == 2, "기록된 사용 제한은 다르다"
    assert outcome.duplicate_results == 0


def test_b03_card_name_lists_alone_do_not_merge_results():
    """
    🔴 **카드명 목록만 같다는 이유로 합치지 않는다.**

    :func:`outcome_key` 는 카드 목록이 아니라 **상태 해시와 그 자리의 허용
    후보**를 본다 — 위 두 결과가 그 증거다 (카드 목록은 완전히 같다).
    """
    _search, _ledger, outcome = walk_many(SAME_FIELD_OTHER_USES, max_results=5)
    ids = {
        tuple(sorted(
            card_id
            for zone in result.resources.zones
            for card_id in zone.card_ids
            if card_id is not None
        ))
        for result in outcome.results
    }
    assert len(ids) == 1, "두 결과의 카드 ID 목록은 같다"
    assert outcome.found == 2, "그래도 따로 세었다"


def test_b04_representative_prefers_the_shorter_path():
    """
    대표는 **명시적이고 결정론적인 기준**으로 고른다 — 걸음이 적은 쪽이
    먼저이고, 같으면 행동 · 선택의 안정된 순서다.

    🔴 **발견한 경로 중의 대표이고, 전체 최단 경로 보장이 아니다.**
    """
    _search, ledger, outcome = walk_many(SAME_GOAL_TWICE, max_results=5)
    assert outcome.found == 1
    kept = outcome.results[0]
    assert kept.action_count == 2, "나중에 온 짧은 경로가 대표가 되었다"
    assert [step.action_key[2] for step in kept.path] == ["B", "G"]
    assert ledger.duplicate_results == 1


def test_b05_representative_order_is_deterministic():
    """같은 경로 묶음이면 **같은 답**이 나온다."""
    _s1, _l1, first = walk_many(SAME_GOAL_TWICE, max_results=5)
    _s2, _l2, again = walk_many(SAME_GOAL_TWICE, max_results=5)
    assert (representative_order(first.results[0].path)
            == representative_order(again.results[0].path))
    short = first.results[0].path
    assert representative_order(short) < representative_order(short + short)


def test_b06_identity_is_judged_on_both_seats():
    """
    동일성은 **양쪽 자리**를 본다 — 요약이 상대 자리의 존까지 들고 있다.

    🔴 상대의 가려진 자리는 **장수만** 들고 있다 (§3).
    """
    duel = _MDuel(TWO_GOALS, "G1")
    summary = summarize_resources(duel, P0)
    assert summary.zone(1, Zone.MZONE) is not None
    for zone in (Zone.HAND, Zone.DECK, Zone.EXTRA):
        theirs = summary.zone(1, zone)
        assert theirs is not None and theirs.counted_only
        assert theirs.cards == ()


# ======================================================================
# C. 재생
# ======================================================================
def _stub_ledger(graph, **kwargs):
    """그래프를 걸어 ``ledger.results`` 를 채운다."""
    search = _MSearch(
        graph,
        goal=FieldGoal(card_id=GRAPH_GOAL_CARD, seat=P0),
        budget=SearchBudget(
            max_depth=6, max_nodes=200, max_choice_branches=0, **kwargs
        ),
    )
    ledger = bs._Ledger()
    root = bs._Node(Simulator(_MDuel(graph, "R")), (), 0)
    search._drive(root, ledger, time.monotonic())
    return search, ledger


def test_c01_one_failed_rerun_does_not_discard_the_others(monkeypatch):
    """
    🔴 **하나가 실패해도 다른 결과를 버리지 않는다.**

    바꿔 끼운 것은 "재생이 어떻게 끝났는가" 하나이고, 집계는
    ``rerun_results`` production 그대로다.
    """
    search, ledger = _stub_ledger(TWO_GOALS, max_results=3)
    assert len(ledger.results) == 2
    calls = []

    def fake(duel, path, target, *, expect_field=(), expect_hash="",
             reached_at=0, deadline=None):
        #: 🔴 Phase 6-AL — production ``rerun_steps`` 가 ``reached_at``
        #: (최초 목표 도달 걸음)을 받는다. 가짜 구현도 **같은 서명**을
        #: 받아야 한다 — 안 맞추면 이 시험은 재생 판정이 아니라
        #: ``TypeError`` 를 보고, 결과별 예외 격리(6-AJ §B)가 그것을
        #: "그 결과의 실패" 로 적어 **조용히 통과하는 쪽**이 될 수도
        #: 있다. 첫 도달 모드에서는 0 이어야 한다 (기준점은 기존
        #: 검증과 같은 길을 지난다).
        assert reached_at == 0, reached_at
        assert isinstance(deadline, bs.RerunDeadline), deadline
        calls.append(expect_hash)
        if len(calls) == 1:
            return RerunResult(ok=False, reason="[스텁] 첫 결과만 실패")
        return RerunResult(
            ok=True, reason="[스텁] 성공", steps=len(path), goal_reached=True,
            final_field=expect_field, final_state_hash=expect_hash,
            matches_search=True,
            resources=ledger.results[1][1],
        )

    monkeypatch.setattr(bs, "rerun_steps", fake)
    results = search.rerun_results(_MDuel(TWO_GOALS, "R"), ledger)
    outcome = search._many_outcome(
        Termination.EXHAUSTED, ledger, 0.0, 0.0, results
    )
    assert outcome.found == 2
    assert len(outcome.failed_results) == 1
    assert len(outcome.verified_results) == 1
    assert outcome.verified_results[0].index == 2
    assert not outcome.results[0].verified


def test_c02_a_rerun_error_is_not_turned_into_nothing_found(monkeypatch):
    """🔴 **재생 오류를 "탐색이 아무것도 못 찾았다" 로 바꾸지 않는다.**"""
    search, ledger = _stub_ledger(TWO_GOALS, max_results=3)

    def boom(duel, path, target, *, expect_field=(), expect_hash="",
             reached_at=0, deadline=None):
        #: 🔴 Phase 6-AL — production ``rerun_steps`` 가 ``reached_at``
        #: (최초 목표 도달 걸음)을 받는다. 가짜 구현도 **같은 서명**을
        #: 받아야 한다 — 안 맞추면 이 시험은 재생 판정이 아니라
        #: ``TypeError`` 를 보고, 결과별 예외 격리(6-AJ §B)가 그것을
        #: "그 결과의 실패" 로 적어 **조용히 통과하는 쪽**이 될 수도
        #: 있다. 첫 도달 모드에서는 0 이어야 한다 (기준점은 기존
        #: 검증과 같은 길을 지난다).
        assert reached_at == 0, reached_at
        assert isinstance(deadline, bs.RerunDeadline), deadline
        raise BoundedSearchError("[스텁] 재생이 예외로 멈췄다")

    monkeypatch.setattr(bs, "rerun_steps", boom)
    results = search.rerun_results(_MDuel(TWO_GOALS, "R"), ledger)
    outcome = search._many_outcome(
        Termination.EXHAUSTED, ledger, 0.0, 0.0, results
    )
    assert outcome.found == 2, "결과가 사라지지 않았다"
    assert outcome.reached
    assert len(outcome.verified_results) == 0
    assert len(outcome.failed_results) == 2
    assert all("예외" in result.rerun.reason for result in outcome.results)


def test_c03_matching_resources_are_required_for_verification(monkeypatch):
    """
    목표와 최종 판이 같아도 **자원 요약이 다르면 검증된 비교에 쓰지
    않는다.**
    """
    search, ledger = _stub_ledger(TWO_GOALS, max_results=3)
    other = summarize_resources(_MDuel(TWO_GOALS, "G2"), P0)

    def fake(duel, path, target, *, expect_field=(), expect_hash="",
             reached_at=0, deadline=None):
        #: 🔴 Phase 6-AL — production ``rerun_steps`` 가 ``reached_at``
        #: (최초 목표 도달 걸음)을 받는다. 가짜 구현도 **같은 서명**을
        #: 받아야 한다 — 안 맞추면 이 시험은 재생 판정이 아니라
        #: ``TypeError`` 를 보고, 결과별 예외 격리(6-AJ §B)가 그것을
        #: "그 결과의 실패" 로 적어 **조용히 통과하는 쪽**이 될 수도
        #: 있다. 첫 도달 모드에서는 0 이어야 한다 (기준점은 기존
        #: 검증과 같은 길을 지난다).
        assert reached_at == 0, reached_at
        assert isinstance(deadline, bs.RerunDeadline), deadline
        return RerunResult(
            ok=True, reason="[스텁] 성공", steps=len(path), goal_reached=True,
            matches_search=True, resources=other,
        )

    monkeypatch.setattr(bs, "rerun_steps", fake)
    results = search.rerun_results(_MDuel(TWO_GOALS, "R"), ledger)
    assert [result.resources_match for result in results] == [False, True]
    assert sum(result.verified for result in results) == 1
    assert any("자원 요약이" in note for note in ledger.rerun_notes)


def test_c04_rerun_time_cap_keeps_results_unverified(monkeypatch):
    """
    🔴 **재생 실행량에 상한을 둔다.** 상한에 걸린 결과는 버리지 않고
    **검증되지 않은 것으로** 남기고, 그 사실을 적는다.
    """
    search, ledger = _stub_ledger(TWO_GOALS, max_results=3)
    search.budget = dataclasses.replace(
        search.budget, max_rerun_seconds=1e-9
    )
    called = []

    def fake(duel, path, target, **kwargs):  # pragma: no cover - 불리지 않는다
        called.append(path)
        return RerunResult(ok=True, reason="[스텁]")

    monkeypatch.setattr(bs, "rerun_steps", fake)
    results = search.rerun_results(_MDuel(TWO_GOALS, "R"), ledger)
    outcome = search._many_outcome(
        Termination.EXHAUSTED, ledger, 0.0, 0.0, results
    )
    assert called == []
    assert outcome.found == 2
    assert len(outcome.unverified_results) == 2
    assert all(result.rerun is None for result in outcome.results)
    #: 🔴 **Phase 6-AJ 가 두 사유를 가른다** — 재생 쪽에서 걸린 칸은
    #: ``rerun_budget_hit`` 이고, 탐색 쪽 ``budget_hit`` 에는 **섞이지
    #: 않는다.** 이 시험이 틀린 가정을 갖고 있었던 것이 아니다 — 6-AI 에서는
    #: 한 칸에 담았고, 그러면 "재생 시간이 끝났다" 가 "탐색 범위를 끝까지
    #: 펼치지 못했다" 로 읽혔다. 기대를 **좁혀서** 더 세게 센다.
    assert any("max_rerun_seconds" in line
               for line in outcome.rerun_budget_hit)
    assert not any("max_rerun_seconds" in line for line in outcome.budget_hit)
    assert len(outcome.rerun_notes) == 2
    #: 🔴 시작조차 하지 못한 것이다 — 재생 도중 넘긴 것과 가른다 (§C).
    assert len(outcome.not_started_results) == 2
    assert not outcome.timed_out_results
    assert not outcome.verified_results


def test_c05_the_final_representative_is_the_one_rerun(monkeypatch):
    """
    🔴 **대표가 교체되면 교체된 쪽이 검증된다.** 그래서 재생은 탐색이
    **끝난 뒤** 돈다.
    """
    search, ledger = _stub_ledger(SAME_GOAL_TWICE, max_results=5)
    seen = []

    def fake(duel, path, target, *, expect_field=(), expect_hash="",
             reached_at=0, deadline=None):
        #: 🔴 Phase 6-AL — production ``rerun_steps`` 가 ``reached_at``
        #: (최초 목표 도달 걸음)을 받는다. 가짜 구현도 **같은 서명**을
        #: 받아야 한다 — 안 맞추면 이 시험은 재생 판정이 아니라
        #: ``TypeError`` 를 보고, 결과별 예외 격리(6-AJ §B)가 그것을
        #: "그 결과의 실패" 로 적어 **조용히 통과하는 쪽**이 될 수도
        #: 있다. 첫 도달 모드에서는 0 이어야 한다 (기준점은 기존
        #: 검증과 같은 길을 지난다).
        assert reached_at == 0, reached_at
        assert isinstance(deadline, bs.RerunDeadline), deadline
        seen.append(tuple(step.action_key for step in path))
        return RerunResult(
            ok=True, reason="[스텁] 성공", steps=len(path), goal_reached=True,
            matches_search=True, resources=ledger.results[0][1],
        )

    monkeypatch.setattr(bs, "rerun_steps", fake)
    results = search.rerun_results(_MDuel(SAME_GOAL_TWICE, "R"), ledger)
    assert len(seen) == 1
    assert len(seen[0]) == 2, "재생된 것은 짧아진 최종 대표다"
    assert results[0].verified


def test_c06_search_and_rerun_durations_are_reported_apart():
    """🔴 **탐색 소요와 재생 소요를 합치지 않는다.**"""
    search, ledger = _stub_ledger(TWO_GOALS, max_results=3)
    outcome = search._many_outcome(Termination.EXHAUSTED, ledger, 1.5, 0.25, ())
    assert outcome.search_seconds == 1.5
    assert outcome.rerun_seconds == 0.25
    said = outcome.describe_ko()
    assert "1.50초" in said and "0.25초" in said


def test_c07_rerun_can_be_switched_off_and_nothing_is_verified():
    """``rerun=False`` 면 **아무 결과도 검증되지 않는다** — 그 사실을 적는다."""
    budget = SearchBudget(max_results=2)
    search = BoundedSearch(
        goal=FieldGoal(card_id=GRAPH_GOAL_CARD, seat=P0), budget=budget
    )
    assert search.budget.many
    #: 실제 ``Duel`` 없이 이 분기만 재려고 ledger 를 직접 넘긴다.
    _graph_search, ledger = _stub_ledger(TWO_GOALS, max_results=2)
    results = tuple(
        PathResult(index=slot + 1, path=path, resources=summary,
                   goal_reason=reason)
        for slot, (path, summary, reason) in enumerate(ledger.results)
    )
    assert all(not result.verified for result in results)
    assert all(result.rerun is None for result in results)


# ======================================================================
# D. 실제 카드 입력 — 🔴 **합성 그래프가 아니다**
# ======================================================================
#: 실제 카드 ID. 🔴 위 격리 그래프의 꼬리표와 섞지 않는다.
GALATEA = 30741503
GALATEA_I = 48835607
GIRSU = 69811710
GROWTH = 93920420
CLIMAX = 703897


@pytest.fixture(scope="module")
def repository():
    from core.card_repository import CardRepository

    return CardRepository.build(db_path="data/cards.cdb", script_dir=".")


@pytest.fixture(scope="module")
def growth_setup(repository):
    """기존 『성장』 입력으로 만든 **초기 상태** (탐색하지 않는다)."""
    from app.main import opening_wiring
    from deck.combo_policy import ORCUST_GIRSU_LINE
    from deck.opening import build_opening
    from deck.recipe import parse_recipe

    parsed = parse_recipe(ORCUST_GIRSU_LINE.recipe_ydk, repository)
    chooser, triggers = opening_wiring(repository, None)
    setup = build_opening(
        repository, parsed.draft, list(ORCUST_GIRSU_LINE.hand),
        chooser=chooser, triggers=triggers,
    )
    assert setup.can_run, setup.blockers
    return setup


@pytest.fixture(scope="module")
def real_duel(growth_setup):
    """입력 검사를 재는 데 쓰는 **진짜** ``Duel`` 하나."""
    return growth_setup.duel


@pytest.fixture(scope="module")
def growth_many(repository):
    """
    같은 입력에서 **서로 다른 결과 셋**을 모으고 전부 재생한다.

    모듈 범위로 둔 이유는 하나 — 이 탐색 한 번이 1분을 넘는다. 🔴 **결과를
    공유하지만 판을 공유하지 않는다**: 요약은 값이고, 재생은
    ``bounded_search_many_opening`` 이 **새로 만든** 초기 상태에서 한다.
    """
    from app.main import bounded_search_many_opening
    from deck.combo_policy import ORCUST_GIRSU_LINE
    from deck.recipe import parse_recipe

    parsed = parse_recipe(ORCUST_GIRSU_LINE.recipe_ydk, repository)
    return bounded_search_many_opening(
        repository, parsed.draft, list(ORCUST_GIRSU_LINE.hand),
        card_id=GALATEA, max_results=3,
        budget=SearchBudget(max_depth=6, max_nodes=400),
    )


def test_d01_real_input_yields_more_than_one_distinct_result(growth_many):
    """
    🔴 **실제 카드로 서로 다른 결과가 둘 이상 나온다** (§7-D).

    적어 둔 경로(``ORCUST_GIRSU_LINE``)를 **호출하지 않았다** — 그 상수에서
    가져온 것은 레시피와 시작 패, 즉 **입력**뿐이다.
    """
    _setup, outcome = growth_many
    assert outcome is not None
    assert outcome.found >= 2
    assert len(outcome.verified_results) >= 2
    hashes = {result.resources.state_hash for result in outcome.results}
    assert len(hashes) == outcome.found, "모은 결과는 서로 다른 상태다"


def test_d02_every_presented_result_was_rerun(growth_many):
    """🔴 **제시하는 대표 경로를 전부 재생했다.**"""
    _setup, outcome = growth_many
    for result in outcome.results:
        assert result.rerun is not None, f"결과 {result.index} 를 재생하지 않았다"
        assert result.rerun.ok, result.rerun.reason
        assert result.rerun.goal_reached
        assert result.rerun.matches_search
        assert result.resources_match
        assert result.verified
    assert not outcome.failed_results
    assert not outcome.unverified_results


def test_d03_the_summary_matches_the_rerun_state(growth_many):
    """요약이 **재생된 실제 상태**와 같다 — 요약만 보고 지어낸 것이 아니다."""
    _setup, outcome = growth_many
    for result in outcome.results:
        assert result.rerun.resources == result.resources
        assert result.rerun.final_field == result.resources.own_field_rows
        assert result.rerun.final_state_hash == result.resources.state_hash


def test_d04_results_differ_in_real_resources(growth_many):
    """
    결과들이 **실제 자원에서** 다르다 — 행동 수만 다른 것이 아니다.

    🔴 어느 쪽이 나은지 고르지 않는다. 다르다는 사실만 센다.
    """
    _setup, outcome = growth_many
    results = outcome.verified_results
    hands = {result.resources.card_ids(0, Zone.HAND) for result in results}
    graves = {result.resources.card_ids(0, Zone.GRAVE) for result in results}
    uses = {
        tuple((record.kind, record.label) for record in result.resources.uses)
        for result in results
    }
    #: 실측 (보고서 §5): 패 구성 · 묘지 구성 · 기록된 소환 사용이 갈린다.
    assert len(hands | graves | uses) >= 2
    assert len(graves) >= 2 or len(uses) >= 2


def test_d05_the_goal_card_is_on_the_field_in_every_result(growth_many):
    """모든 결과에서 목표 카드가 **자신 필드에 앞면으로** 있다."""
    _setup, outcome = growth_many
    for result in outcome.results:
        rows = result.resources.own_field_rows
        assert any(card_id == GALATEA and face_up for _zone, card_id, face_up
                   in rows), rows


def test_d06_hidden_information_is_not_invented(growth_many):
    """🔴 **상대의 비공개 정보를 만들어 평가하지 않는다** (§3)."""
    _setup, outcome = growth_many
    for result in outcome.results:
        summary = result.resources
        for zone in (Zone.HAND, Zone.DECK, Zone.EXTRA):
            theirs = summary.zone(1, zone)
            assert theirs is not None, f"상대 {zone} 가 요약에서 사라졌다"
            assert theirs.counted_only and theirs.cards == ()
        for slot in summary.their_field:
            if not slot.face_up:
                assert slot.card_id is CONCEALED_CARD


def test_d07_the_summary_is_a_frozen_value(growth_many):
    """🔴 **살아 있는 ``Duel`` 을 들고 있지 않다.**"""
    _setup, outcome = growth_many
    summary = outcome.results[0].resources
    assert isinstance(summary, ResourceSummary)
    with pytest.raises(dataclasses.FrozenInstanceError):
        summary.seat = 1
    #: 요약의 어느 칸에도 ``Duel`` · ``Simulator`` 가 없다.
    for field_ in dataclasses.fields(summary):
        value = getattr(summary, field_.name)
        assert not hasattr(value, "legal_actions")


def test_d08_tampered_actions_fail_the_rerun(growth_many, growth_setup,
                                             repository):
    """
    🔴 **기록된 행동이 그 자리의 허용 후보인지 다시 본다.**

    한 걸음의 행동 열쇠를 **없는 것**으로 바꾸면 재생이 실패한다 — 객체를
    들고 다니며 억지로 적용하지 않는다는 뜻이다.
    """
    _setup, outcome = growth_many
    good = outcome.verified_results[0]
    broken = list(good.path)
    broken[0] = dataclasses.replace(
        broken[0], action_key=("edge", "없는", "후보")
    )
    done = rerun_steps(
        growth_setup.duel, tuple(broken),
        FieldGoal(card_id=GALATEA, seat=P0),
        expect_field=good.resources.own_field_rows,
        expect_hash=good.resources.state_hash,
    )
    assert not done.ok
    assert "허용 후보에 없습니다" in done.reason
    assert done.steps == 0


def test_d09_tampered_choices_fail_the_rerun(growth_many, growth_setup):
    """
    🔴 **기록된 선택이 그 자리의 허용 후보인지 다시 본다.**

    고른 개체를 없는 번호로 바꾸면 재생이 실패한다.
    """
    _setup, outcome = growth_many
    good = next(
        (result for result in outcome.verified_results
         if any(step.choices for step in result.path)),
        None,
    )
    assert good is not None, "해결 중 선택이 있는 결과가 없다"
    broken = []
    tampered = False
    for step in good.path:
        if step.choices and not tampered:
            #: 🔴 **없는 개체 번호**로 바꾼다 — 그 자리의 후보에 없다.
            asks = tuple(
                dataclasses.replace(ask, chosen=(999_999,))
                for ask in step.choices
            )
            broken.append(dataclasses.replace(step, choices=asks))
            tampered = True
            continue
        broken.append(step)
    assert tampered
    done = rerun_steps(
        growth_setup.duel, tuple(broken),
        FieldGoal(card_id=GALATEA, seat=P0),
        expect_field=good.resources.own_field_rows,
        expect_hash=good.resources.state_hash,
    )
    assert not done.ok
    assert "허용 후보에 없었습니다" in done.reason or "기록과 다릅니다" in done.reason


def test_d10_no_interference_and_current_turn_only(growth_many):
    """🔴 **무방해 · 이번 턴만**이라는 조건이 그대로다 (6-AH)."""
    _setup, outcome = growth_many
    assert any("이 턴을 벗어나는" in note for note in outcome.out_of_scope)
    assert not outcome.opponent_declined or all(
        "방해" in note or "넘겼" in note for note in outcome.opponent_declined
    )
    for result in outcome.results:
        assert result.resources.turn_number == 1


def test_d11_the_original_duel_is_untouched(growth_many, growth_setup):
    """🔴 **탐색이 원본 판을 밀지 않았다** (``_assert_untouched``)."""
    _setup, outcome = growth_many
    assert outcome.errors == ()
    #: 같은 입력으로 **다시** 만든 판과 탐색이 쓴 판의 해시가 같다.
    assert growth_setup.duel.state.state_hash()
    assert all(result.resources.state_hash
               != growth_setup.duel.state.state_hash()
               for result in outcome.results)


# ======================================================================
# E. 보고와 회귀
# ======================================================================
def test_e01_brief_states_the_five_required_things(growth_many, repository):
    """
    기본 응답이 **다섯 가지**를 적는다 (§6): 검증된 결과 수 · 목표와 무방해
    조건 · 자원 비교 · 종료 사유와 생략 여부 · 아직 강약 평가가 아니라는 것.
    """
    from deck.report import render_multi_search_brief

    _setup, outcome = growth_many
    said = render_multi_search_brief(outcome, repository)
    assert f"검증된 서로 다른 결과 {len(outcome.verified_results)}개" in said
    assert "상대 방해 없음" in said and "이번 턴만" in said
    assert "남은 패" in said and "자신 묘지" in said
    assert "결과들의 차이" in said
    assert "종료:" in said
    assert "아직 강약 평가가 아닙니다" in said
    assert "가능한 모든 전개가" in said or "더 있을 수 있습니다" in said


def test_e02_brief_never_ranks_or_totals(growth_many, repository):
    """🔴 **자동 순위도 승자도 총점도 적지 않는다** (§4)."""
    from deck.report import render_multi_search, render_multi_search_brief

    import deck.report as report

    _setup, outcome = growth_many
    for said in (render_multi_search_brief(outcome, repository),
                 render_multi_search(outcome, repository)):
        #: 🔴 **부인하는 문장은 빼고 본다.** "점수도 총점도 순위도 없습니다"
        #: 는 그 말을 **하지 않겠다는 선언**이므로 금칙어 검사의 대상이
        #: 아니다 — 그것까지 걸면 선언을 지우게 된다.
        body = said.replace(report._MULTI_DISCLAIMER, "").replace(
            report._SEARCH_DISCLAIMER, "")
        for forbidden in ("총점", "순위", "1위", "추천 전개", "가장 강",
                          "더 강한", "최선의 결과", "점수"):
            assert forbidden not in body, forbidden
        #: 그리고 그 선언은 **반드시 있어야 한다.**
        assert report._MULTI_DISCLAIMER in said


def test_e03_korean_names_come_from_the_render_layer(growth_many, repository):
    """
    🔴 **한국어 이름은 표시 층이 붙인다.** ``agent`` 의 요약은 ID 만 들고
    있으므로, 저장소를 주지 않으면 이름이 나오지 않는다.
    """
    from deck.report import render_multi_search_brief

    _setup, outcome = growth_many
    with_names = render_multi_search_brief(outcome, repository)
    without = render_multi_search_brief(outcome, None)
    assert "오르페골 갈라테아" in with_names
    assert "오르페골 갈라테아" not in without
    assert f"[{GALATEA}]" in without


def test_e04_detail_keeps_every_step_and_zone(growth_many, repository):
    """상세 기록은 **줄이지 않는다** — 걸음과 모든 존이 그대로 있다."""
    from deck.report import render_multi_search

    _setup, outcome = growth_many
    said = render_multi_search(outcome, repository)
    for result in outcome.results:
        assert f"[결과 {result.index}]" in said
        for step in result.path:
            assert str(step.action_key) in said
    assert "남은 메인 덱" in said and "제외" in said
    assert "기록된 사용 제한" in said
    assert "재생 (새 초기 상태에서 다시 실행)" in said


def test_e05_detail_reports_omissions_and_budget(growth_many, repository):
    """미지원 · 예산 · 생략의 상세가 **첨부에 그대로** 있다."""
    from deck.report import render_multi_search

    _setup, outcome = growth_many
    said = render_multi_search(outcome, repository)
    assert "지원하지 않아 후보가 되지 못한 수" in said
    assert "범위 밖으로 둔 분기" in said
    assert "재생 메모" in said
    assert "예산" in said


def test_e06_one_result_is_shown_as_one(repository):
    """🔴 **결과가 하나면 하나로 적는다** — 중복으로 수를 채우지 않는다."""
    from deck.report import render_multi_search_brief

    search, ledger = _stub_ledger(GOAL_THEN_MORE, max_results=3)
    results = (PathResult(
        index=1, path=ledger.results[0][0], resources=ledger.results[0][1],
        goal_reason=ledger.results[0][2],
        rerun=RerunResult(ok=True, reason="[스텁] 성공", goal_reached=True,
                          matches_search=True,
                          resources=ledger.results[0][1]),
        resources_match=True,
    ),)
    outcome = search._many_outcome(
        Termination.EXHAUSTED, ledger, 0.1, 0.1, results
    )
    said = render_multi_search_brief(outcome, repository)
    assert "검증된 서로 다른 결과 1개" in said
    assert "검증된 결과가 **하나**입니다" in said
    assert "비교할 다른 결과가 없습니다" in said


def test_e07_no_results_is_not_impossible(repository):
    """🔴 **못 찾은 것을 "불가능" 으로 바꾸지 않는다.**"""
    from deck.report import render_multi_search_brief

    search, ledger = _stub_ledger(
        Graph(edges={"R": ("A",)}, goals=frozenset()), max_results=3
    )
    outcome = search._many_outcome(Termination.EXHAUSTED, ledger, 0.1, 0.0, ())
    said = render_multi_search_brief(outcome, repository)
    assert "찾은 결과가 없습니다" in said
    assert "불가능하다는 뜻이 아닙니다" in said


def test_e08_single_result_mode_is_unchanged():
    """
    🔴 **단일 결과 모드가 그대로다** (6-AH). 목표를 찾으면 **그 자리에서**
    고리가 멈추고, 결과 수집은 일어나지 않는다.
    """
    search = _MSearch(
        TWO_GOALS,
        goal=FieldGoal(card_id=GRAPH_GOAL_CARD, seat=P0),
        budget=SearchBudget(max_depth=6, max_nodes=200,
                            max_choice_branches=0),
    )
    ledger = bs._Ledger()
    root = bs._Node(Simulator(_MDuel(TWO_GOALS, "R")), (), 0)
    termination, found = search._drive(root, ledger, time.monotonic())
    assert termination is Termination.GOAL_REACHED
    assert found is not None
    assert ledger.results == []
    assert ledger.duplicate_results == 0


def test_e09_depth_aware_dedup_still_works():
    """
    🔴 **6-AH 보완 A 의 동작이 그대로다** — 같은 상태에 **더 얕게** 다시
    닿으면 다시 펼친다.
    """
    graph = Graph(
        edges={"R": ("A", "B"), "A": ("C",), "C": ("X",), "B": ("X",),
               "X": ("Y",), "Y": ("G",)},
        goals=frozenset({"G"}),
    )
    _search, ledger, outcome = walk_many(graph, max_depth=4, max_results=3)
    assert outcome.found == 1, "깊이 4 안에서 B 쪽 경로로 목표에 닿는다"
    assert ledger.revisited >= 1
    assert outcome.results[0].action_count == 4


def test_e10_cli_defaults_to_single_result():
    """``--results`` 를 주지 않으면 **단일 결과 모드**다."""
    from app.main import search_result_count

    assert search_result_count("") == (1, "")
    assert search_result_count(None) == (1, "")
    assert search_result_count("3") == (3, "")
    count, why = search_result_count(str(RESULTS_CAP + 1))
    assert count is None and str(RESULTS_CAP) in why
    count, why = search_result_count("둘")
    assert count is None and "정수가 아닙니다" in why


def test_e11_discord_option_is_trailing_and_optional():
    """
    ``/combo`` 의 ``results`` 는 **맨 뒤의 선택 인자**다 — 기존 호출이 한
    글자도 달라지지 않는다 (6-T ``recipe`` · 6-AC ``line`` 과 같은 규율).
    """
    import inspect

    from app.discord_bot import SearchService, combo_response

    #: 🔴 **Phase 6-AL 이 ``followups_text`` 를 그 뒤에 더했다** — 그래서
    #: ``results_text`` 는 이제 **마지막에서 두 번째**다. 이 시험이 재는
    #: 사실은 바뀌지 않았다: **선택 인자이고 기본값이 빈 문자열이며 뒤쪽에
    #: 붙어 있어 기존 호출이 그대로 돈다.**
    for func in (combo_response, SearchService.combo_response):
        params = list(inspect.signature(func).parameters)
        assert params[-2] == "results_text"
        assert params[-1] == "followups_text"
        for name in ("results_text", "followups_text"):
            assert inspect.signature(func).parameters[name].default == ""


def test_e12_search_without_results_does_not_change_behaviour():
    """``search:`` 도 ``results:`` 도 없으면 **아무것도 돌리지 않는다.**"""
    from app.discord_bot import _run_bounded_search

    assert _run_bounded_search(None, "", [], "") is None
    assert _run_bounded_search(None, "", [], "", "") is None
    assert _run_bounded_search(None, "", [], "", "3") is None


def test_e13_a_bad_result_count_refuses_without_searching():
    """읽지 못한 결과 수로는 **탐색하지 않는다.**"""
    from app.discord_bot import _run_bounded_search

    said = _run_bounded_search(None, "욕망의 항아리 x3", [55144522],
                               "galatea", "99")
    assert said is not None and not said.ran
    assert any("results:99" in line for line in said.brief)


def test_e14_report_does_not_import_agent():
    """🔴 ``deck`` → ``agent`` 방향의 import 는 이 저장소에 **0곳**이다."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("deck/report.py").read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert "agent" not in roots
    assert "integration" not in roots


def test_e15_production_never_says_replay():
    """
    🔴 **production 식별자에 ``replay`` 가 없다** (3-F-19 감사).

    이 저장소의 말로 이것은 **재실행**이고, ``ChainResolution`` 직렬화
    재생이 없다는 증명이 그 단어의 부재다.

    🔴 **정정 (Phase 6-BB).** 6-AR 이 **전개 기록 내보내기 모듈**
    ``deck.replay_export`` 를 더하면서 그 모듈 **이름**이 세 파일에
    들어왔다 (``deck/report.py`` 는 6-AR 부터, ``app/main.py`` 는 6-BB
    부터). 그 이름은 `` ChainResolution`` 직렬화 재생이 아니라 **외부
    연동용 기록 형식**(``engine-replay/N``) 을 가리킨다. 그래서 감사가
    막으려던 것 — **재실행을 재생이라고 부르는 식별자** — 만 남기고,
    그 모듈 이름은 예외로 둔다. 🔴 예외를 늘리지 않는다: 아래 목록에
    없는 ``replay`` 는 그대로 실패다.
    """
    import pathlib
    import re

    #: 🔴 **이름 그대로만 허용한다** — ``replay_viewer`` 같은 다른 이름을
    #: 조용히 통과시키지 않는다.
    allowed = re.compile(r"deck\.replay_export|export_opening_replay")
    for path in ("agent/bounded_search.py", "deck/report.py", "app/main.py"):
        text = pathlib.Path(path).read_text(encoding="utf-8")
        left = allowed.sub("", text)
        assert "replay" not in left, path
