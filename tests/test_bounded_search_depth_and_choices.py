"""
Phase 6-AH 보완 — **깊이를 고려한 중복 제거**와 **선택 조합의 지연 생성**.

두 문제를 좁혀서 고친 것을 고정한다.

======  ======================================================================
``A``   깊이 우선 탐색이 같은 상태를 **깊은 경로로 먼저** 보면, 나중에 더
        얕게 닿아도 "이미 봤다" 로 버렸다. 깊이 상한이 있으면 얕은 쪽에
        **남은 예산이 더 많으므로** 상한 안의 경로를 놓친다.
``B``   ``selection_options`` 가 ``combinations`` 의 결과를 **전부 만든 뒤**
        잘랐다. 반환 개수만 제한하고 **생성 비용은 제한하지 않았다.** 그리고
        선택 분기 상한이 0 이면 **생략 사실이 기록되지 않았다.**
======  ======================================================================

🔴 **A 절은 격리된 합성 그래프로 잰다 — 실제 카드 전개가 아니다.**
엔진이 실제로 내놓는 전개에서 같은 현상을 재현했다고 **주장하지 않는다.**
여기서 재는 것은 **탐색 알고리즘**이고, 그래서 판의 전이를 그래프로
바꿔 끼운다. 바꿔 끼우는 것은 "행동을 적용하면 어떤 상태가 되는가" 하나
(:meth:`_GraphSearch._attempts`)이고, **고리 · ``_open`` · ``node_key`` ·
``admit`` · ``superseded`` 는 production 그대로**다 — 시험이 제 알고리즘을
따로 적어 그것만 통과시키지 않도록 그렇게 두었다.

실제 카드로 재는 것은 `tests/test_bounded_search_first_pass.py` 가 들고
있고, 이 파일은 그것을 **대신하지 않는다.**

🔴 **최단 경로 탐색을 구현한 것이 아니다.** 이 파일이 지키는 사실은
하나다 — **깊이 상한 안의 경로를 "이미 봤다" 는 이유로 잘못 버리지
않는다.** 탐색의 완전성도 최적성도 주장하지 않는다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from itertools import combinations, islice

import pytest

import agent.bounded_search as bs
from agent.bounded_search import (
    Admission,
    BoundedSearch,
    BoundedSearchError,
    FieldGoal,
    SearchBudget,
    Termination,
    admit,
    alternative_options,
    iter_selections,
    selection_options,
    superseded,
)
from agent.choice import ChoiceAsk
from agent.simulation import Simulator
from engine.action import PlayerActionKind
from engine.vocabulary import Zone

P0 = 0

#: 🔴 **격리 그래프 전용 꼬리표다 — 실제 카드 ID 가 아니다.** 저장소의
#: 카드와 섞이지 않도록 어느 패스코드와도 겹치지 않는 값을 쓴다.
GRAPH_GOAL_CARD = 999_000_001


# ======================================================================
# 격리된 그래프 — Duel 처럼 보이게 한 최소한의 것
# ======================================================================
@dataclass(frozen=True, slots=True)
class Graph:
    """
    꼬리표와 간선만 있는 그래프. **상태는 꼬리표 하나**다.

    :attr:`goals` 의 꼬리표에서만 목표 카드가 자신 필드에 보인다.
    """

    edges: dict
    goals: frozenset

    def out(self, label: str) -> tuple:
        return tuple(self.edges.get(label, ()))


class _GraphCard:
    __slots__ = ("card_id", "is_faceup")

    def __init__(self, card_id: int):
        self.card_id = card_id
        self.is_faceup = True


class _GraphZone:
    __slots__ = ("_cards",)

    def __init__(self, cards):
        self._cards = tuple(cards)

    def cards(self):
        return list(self._cards)


class _GraphPlayer:
    __slots__ = ("_mzone", "_empty")

    def __init__(self, cards):
        self._mzone = _GraphZone(cards)
        self._empty = _GraphZone(())

    def zone(self, zone):
        return self._mzone if zone is Zone.MZONE else self._empty


class _GraphState:
    """``state_hash`` 가 **그래프의 꼬리표**다 — 같은 꼬리표가 같은 상태다."""

    __slots__ = ("label", "_player")

    def __init__(self, label: str, cards):
        self.label = label
        self._player = _GraphPlayer(cards)

    def state_hash(self) -> str:
        return f"graph:{self.label}"

    def player(self, seat: int):
        return self._player


class _GraphWindow:
    value = "none"


class _GraphPriority:
    is_open = False
    window = _GraphWindow()


class _GraphChain:
    is_empty = True

    def __len__(self):
        return 0


class _GraphTurnStep:
    value = "open"


class _GraphAction:
    """
    간선 하나. ``_order_key`` 가 읽는 두 가지만 들고 있다.

    🔴 ``END_PHASE`` 가 아닌 종류를 쓴다 — 그래야 탐색이 **펼친다**
    (``END_PHASE`` 는 이 턴을 벗어나는 수라 펼치지 않는다).
    """

    __slots__ = ("source", "target", "kind")

    def __init__(self, source: str, target: str):
        self.source = source
        self.target = target
        self.kind = PlayerActionKind.NORMAL_SUMMON

    def canonical_state(self) -> tuple:
        return ("edge", self.source, self.target)


class _GraphEnd:
    """
    ``end_phase`` 자리. **펼쳐지지 않지만 있어야 한다** — 목표 판정이
    "엔진이 그 자리에서 ``end_phase`` 를 허가하는가" 를 묻기 때문이다
    (``_is_settled``).
    """

    __slots__ = ("kind",)

    def __init__(self):
        self.kind = PlayerActionKind.END_PHASE

    def canonical_state(self) -> tuple:
        return ("end_phase",)


class _GraphLegal:
    __slots__ = ("allowed",)

    def __init__(self, allowed):
        self.allowed = tuple(allowed)

    def unsupported(self):
        return ()


class _GraphDuel:
    """그래프의 노드 하나를 ``Duel`` 처럼 보이게 한 것."""

    __slots__ = ("graph", "label", "state", "chain", "priority", "step",
                 "is_over", "to_act")

    def __init__(self, graph: Graph, label: str):
        self.graph = graph
        self.label = label
        self.state = _GraphState(
            label,
            (_GraphCard(GRAPH_GOAL_CARD),) if label in graph.goals else (),
        )
        self.chain = _GraphChain()
        self.priority = _GraphPriority()
        self.step = _GraphTurnStep()
        self.is_over = False
        self.to_act = P0

    def legal_actions(self, seat=None):
        return _GraphLegal(
            [_GraphEnd()]
            + [_GraphAction(self.label, nxt) for nxt in self.graph.out(self.label)]
        )


class _GraphSearch(BoundedSearch):
    """
    🔴 **바꿔 끼우는 것은 ``_attempts`` 하나다.**

    "그 행동을 적용하면 어떤 상태가 되는가" 만 그래프가 답하고, 고리 ·
    :meth:`BoundedSearch._open` · :func:`~agent.bounded_search.node_key` ·
    :func:`~agent.bounded_search.admit` ·
    :func:`~agent.bounded_search.superseded` 는 production 그대로 돈다.
    """

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
                duel=_GraphDuel(self.graph, action.target),
            )
        ]


def walk(
    graph: Graph,
    *,
    start: str = "R",
    max_depth: int = 4,
    max_nodes: int = 200,
    dedup: bool = True,
):
    """그 그래프를 **production 고리로** 걸어 본다."""
    search = _GraphSearch(
        graph,
        goal=FieldGoal(card_id=GRAPH_GOAL_CARD, seat=P0),
        budget=SearchBudget(
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_choice_branches=0,
            dedup=dedup,
        ),
    )
    ledger = bs._Ledger()
    root = bs._Node(Simulator(_GraphDuel(graph, start)), (), 0)
    termination, found = search._drive(root, ledger, time.monotonic())
    return search, ledger, termination, found


#: 외부 검토가 재현에 쓴 그래프 — `A` 쪽이 먼저 탐색되고, 깊이 상한 4 에서
#: `G` 는 **`B` 를 지나는 4걸음 경로로만** 닿는다.
#:
#: ===  ==========================================================
#: `A`  ``R → A → C → X → Y → G`` 는 5걸음 (상한 초과)
#: `B`  ``R → B → X → Y → G`` 는 **4걸음** (상한 안)
#: ===  ==========================================================
REVIEW_GRAPH = Graph(
    edges={
        "R": ("A", "B"),
        "A": ("C",),
        "C": ("X",),
        "B": ("X",),
        "X": ("Y",),
        "Y": ("G",),
    },
    goals=frozenset({"G"}),
)

#: 같은 깊이로 같은 상태(`X`)에 닿는 마름모. 🔴 **목표는 `X` 쪽이 아니다** —
#: 그래야 `A` 와 `B` 가 모두 펼쳐지고 두 번째 도달이 실제로 중복이 된다.
#: `X → D` 는 "`X` 를 몇 번 펼쳤는가" 를 세기 위한 막다른 간선이다.
DIAMOND = Graph(
    edges={
        "R": ("A", "B", "Z"),
        "A": ("X",),
        "B": ("X",),
        "X": ("D",),
        "Z": ("G",),
    },
    goals=frozenset({"G"}),
)

#: 순환이 있고 목표가 **없는** 그래프.
CYCLE_ONLY = Graph(
    edges={"R": ("A",), "A": ("B",), "B": ("A",)},
    goals=frozenset(),
)

#: 순환을 지나야 목표에 닿는 그래프.
CYCLE_THEN_GOAL = Graph(
    edges={"R": ("A",), "A": ("B", "G"), "B": ("A",)},
    goals=frozenset({"G"}),
)

#: 한 줄기 — 목표가 **정확히 4걸음**이다.
CHAIN4 = Graph(
    edges={"R": ("N1",), "N1": ("N2",), "N2": ("N3",), "N3": ("G",)},
    goals=frozenset({"G"}),
)


def _visited_only(seen, key, depth):
    """
    🔴 **보완 전의 규칙** — 방문 여부만 본다 (깊이를 보지 않는다).

    재현에만 쓴다. production 에는 이런 함수가 없다.
    """
    if key is None:
        return Admission.FRESH
    if key in seen:
        return Admission.DUPLICATE
    seen[key] = depth
    return Admission.FRESH


# ======================================================================
# A. 깊이를 고려한 중복 제거
# ======================================================================
def test_a01_the_old_rule_misses_the_four_step_path(monkeypatch):
    """
    🔴 **보완 전 규칙으로는 놓친다** — 그것이 고친 이유다.

    같은 그래프 · 같은 예산 · **입장 판정만** 옛 규칙으로 바꿔 끼운다.
    """
    monkeypatch.setattr(bs, "admit", _visited_only)
    monkeypatch.setattr(bs, "superseded", lambda seen, key, depth: False)
    search, ledger, termination, found = walk(REVIEW_GRAPH, max_depth=4)
    assert found is None
    assert termination is not Termination.GOAL_REACHED
    #: 🔴 **예산이 모자라서가 아니다** — 노드도 시간도 남았고, `X` 를
    #: 깊이 3 으로 먼저 본 뒤 깊이 2 로 다시 닿은 것을 버렸기 때문이다.
    assert ledger.nodes < 200
    assert ledger.deduped >= 1
    assert ledger.revisited == 0


def test_a02_the_depth_rule_finds_the_four_step_path():
    """🟢 **지금 규칙으로는 찾는다** — 같은 그래프 · 같은 예산 · dedup 켜짐."""
    search, ledger, termination, found = walk(REVIEW_GRAPH, max_depth=4)
    assert termination is Termination.GOAL_REACHED
    assert found is not None
    path, duel, verdict = found
    assert verdict.reached
    assert duel.label == "G"
    #: 🔴 **4걸음이고 `B` 를 지난다.**
    assert len(path) == 4
    assert [step.action_key[2] for step in path] == ["B", "X", "Y", "G"]
    #: 🔴 **더 얕게 다시 닿아 다시 펼쳤다** — 그것이 고친 동작이다.
    assert ledger.revisited >= 1


def test_a03_a_shallower_arrival_reopens_the_state():
    """
    🟢 같은 상태에 **더 얕게** 닿으면 다시 펼친다.

    `X` 를 깊이 3 (``A → C`` 경유)으로 먼저 보고, 깊이 2 (``B`` 경유)로
    다시 닿는다. 두 번 펼쳐진 것을 **production 이 부른 횟수**로 센다.
    """
    search, ledger, termination, found = walk(REVIEW_GRAPH, max_depth=4)
    assert search.opened.count("X→Y") == 2
    assert ledger.revisited >= 1
    #: 그리고 :func:`admit` 의 기록은 **가장 얕은 깊이**를 들고 있다.
    key = f"graph:X"
    depths = {
        label: depth for label, depth in (
            (name.split(":")[1], depth) for name, depth in
            ((k[0], v) for k, v in ledger.seen.items())
        )
    }
    assert depths["X"] == 2, depths


def test_a04_same_or_deeper_arrivals_are_not_reopened():
    """
    🟢 **같은 깊이·더 깊은 재방문은 펼치지 않는다.**

    마름모에서 `X` 는 두 길 모두 깊이 2 다 — 두 번째는 버린다.
    """
    search, ledger, termination, found = walk(DIAMOND, max_depth=6)
    assert termination is Termination.GOAL_REACHED
    #: `A → X` 가 먼저이고, `B → X` 는 **같은 깊이 2** 라 버려진다.
    assert ledger.deduped == 1
    assert ledger.revisited == 0
    #: 🔴 **`X` 를 한 번만 펼쳤다.**
    assert search.opened.count("X→D") == 1
    assert search.opened.count("A→X") == 1
    assert search.opened.count("B→X") == 1


def test_a05_cycles_terminate_under_dedup():
    """
    🟢 **순환이 있어도 끝난다.** 예산을 다 쓰지 않고 범위를 소진한다.

    🔴 뿌리도 같은 원칙을 받는다 — 뿌리로 돌아오는 간선도 중복이다.
    """
    search, ledger, termination, found = walk(
        CYCLE_ONLY, max_depth=8, max_nodes=100
    )
    assert found is None
    #: 🔴 **예산을 건드리지 않고 끝난다.** 순환이 중복으로 끊기므로 깊이
    #: 상한(8)에도, 노드 상한(100)에도 닿지 않는다 — 그래서 이 답은
    #: "지정된 범위를 다 펼쳤고 그 안에 목표가 없었다" 가 맞다.
    assert termination is Termination.EXHAUSTED
    assert ledger.budget_hit == []
    assert ledger.nodes < 10
    assert ledger.deduped >= 1

    #: 🔴 **중복 제거를 끄면 깊이 상한까지 돈다** — 끝나기는 하지만 그때의
    #: 답은 "예산 초과" 이고, 그 둘은 다른 사실이다.
    _os, off_ledger, off_end, off_found = walk(
        CYCLE_ONLY, max_depth=8, max_nodes=100, dedup=False
    )
    assert off_found is None
    assert off_end is Termination.BUDGET_EXCEEDED
    assert any("max_depth=8" in line for line in off_ledger.budget_hit)
    assert off_ledger.nodes > ledger.nodes

    #: 순환을 지나야 닿는 목표도 찾는다.
    _s, _l, done, hit = walk(CYCLE_THEN_GOAL, max_depth=6, max_nodes=100)
    assert done is Termination.GOAL_REACHED
    assert hit is not None


def test_a06_the_depth_boundary_is_exact():
    """
    🟢 **최대 깊이에서 정확히 닿는 목표**와 **한 단계 넘는 목표**를 가른다.
    """
    _s, _l, exactly, found = walk(CHAIN4, max_depth=4)
    assert exactly is Termination.GOAL_REACHED
    assert found is not None and len(found[0]) == 4

    _s2, ledger, over, missed = walk(CHAIN4, max_depth=3)
    assert missed is None
    assert over is Termination.BUDGET_EXCEEDED
    assert any("max_depth=3" in line for line in ledger.budget_hit)


@pytest.mark.parametrize(
    "graph,depth",
    [
        (REVIEW_GRAPH, 4),
        (REVIEW_GRAPH, 6),
        (DIAMOND, 6),
        (CYCLE_THEN_GOAL, 6),
        (CHAIN4, 4),
        (CHAIN4, 3),
        (CYCLE_ONLY, 5),
    ],
)
def test_a07_dedup_on_and_off_agree_when_the_budget_is_ample(graph, depth):
    """
    🟢 예산이 넉넉하면 **중복 제거의 on/off 가 같은 답**을 준다.

    🔴 이것이 "중복 제거가 경로를 버리지 않는다" 의 재는 방식이다 — 끈
    쪽을 기준으로 켠 쪽을 비교한다.
    """
    _on_s, _on_l, on_end, on_found = walk(
        graph, max_depth=depth, max_nodes=4000, dedup=True
    )
    _off_s, _off_l, off_end, off_found = walk(
        graph, max_depth=depth, max_nodes=4000, dedup=False
    )
    assert (on_found is not None) == (off_found is not None), (
        on_end.value, off_end.value
    )
    if on_found is not None:
        #: 🔴 **같은 경로일 필요는 없다** — 목표 도달 여부가 같으면 된다
        #: (최단 경로 탐색이 아니다). 걸음 수는 켠 쪽이 더 짧거나 같다.
        assert len(on_found[0]) <= len(off_found[0])


def test_a08_the_admission_rule_is_a_pure_decision():
    """
    🟢 입장 판정 셋을 **값으로** 센다 — 열쇠가 없으면 병합하지 않는다.
    """
    seen: dict = {}
    assert admit(seen, "k", 3) is Admission.FRESH and seen["k"] == 3
    assert admit(seen, "k", 3) is Admission.DUPLICATE and seen["k"] == 3
    assert admit(seen, "k", 4) is Admission.DUPLICATE and seen["k"] == 3
    assert admit(seen, "k", 1) is Admission.SHALLOWER and seen["k"] == 1
    assert admit(seen, "k", 2) is Admission.DUPLICATE and seen["k"] == 1
    #: 🔴 **열쇠가 없으면 언제나 받는다** (체인 중 등 — ``node_key`` 가
    #: 안전한 기준을 못 만든 자리).
    assert admit(seen, None, 0) is Admission.FRESH
    assert admit(seen, None, 99) is Admission.FRESH
    assert len(seen) == 1

    assert superseded(seen, "k", 2) is True
    assert superseded(seen, "k", 1) is False
    assert superseded(seen, "k", 0) is False
    assert superseded(seen, None, 9) is False
    assert superseded(seen, "없는열쇠", 1) is False

    assert Admission.FRESH.opens and Admission.SHALLOWER.opens
    assert not Admission.DUPLICATE.opens


def test_a09_depth_never_enters_the_state_key():
    """
    🔴 **깊이를 열쇠에 넣어 해결하지 않았다.** 넣으면 중복 제거가 사실상
    꺼진다 — 같은 상태가 깊이마다 다른 노드가 된다.

    마름모에서 `X` 의 열쇠가 **하나**임을 센다 (깊이 2 로 두 번 닿는다).
    """
    search, ledger, termination, found = walk(DIAMOND, max_depth=6)
    labels = [key[0] for key in ledger.seen]
    assert labels.count("graph:X") == 1, labels
    #: 그리고 열쇠의 모양은 6-AH 가 세운 다섯 칸 그대로다 (깊이가 없다).
    sample = next(iter(ledger.seen))
    assert len(sample) == 5
    assert all(not isinstance(part, int) or part == P0 for part in sample[:4])


# ======================================================================
# B. 선택 조합의 지연 생성과 생략 기록
# ======================================================================
def _ask(count: int, *, minimum: int, maximum: int, chosen=()) -> ChoiceAsk:
    """후보 ``count`` 장인 물음 하나. 인스턴스 번호는 1..count 다."""
    return ChoiceAsk(
        index=0,
        label="합성 물음",
        minimum=minimum,
        maximum=maximum,
        offered=tuple((number, 1000 + number) for number in range(1, count + 1)),
        chosen=tuple(chosen),
    )


#: 외부 검토가 재현에 쓴 물음 — 후보 20개에서 **정확히 10개**를 고른다.
#: 전부 만들면 ``C(20,10) = 184,756`` 개다.
BIG_ASK = _ask(20, minimum=10, maximum=10)
BIG_TOTAL = 184_756


def test_b01_the_returned_prefix_and_order_are_unchanged():
    """
    🟢 **반환 결과와 순서가 예전 앞부분과 같다.**

    예전 구현은 ``combinations`` 를 전부 만든 뒤 ``[:limit]`` 로 잘랐다.
    지금은 앞에서 ``limit`` 개만 만들므로, **같은 앞부분**이 나와야 한다.
    """
    options, truncated = selection_options(BIG_ASK, 4)
    assert truncated is True
    assert options == (
        (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        (1, 2, 3, 4, 5, 6, 7, 8, 9, 11),
        (1, 2, 3, 4, 5, 6, 7, 8, 9, 12),
        (1, 2, 3, 4, 5, 6, 7, 8, 9, 13),
    )
    #: 같은 것을 다른 방법으로 한 번 더 — 정규 순서의 앞 4개다.
    assert options == tuple(islice(combinations(range(1, 21), 10), 4))
    #: 🔴 그리고 **결정론적이다** — 두 번 불러도 같다.
    assert selection_options(BIG_ASK, 4)[0] == options


def test_b02_generation_stops_at_the_limit_plus_one(monkeypatch):
    """
    🔴 **조합 생성량이 제한된다** — 실행 시간이 아니라 **소비량**을 센다.

    ``combinations`` 를 세는 생성기로 바꿔 끼우고, 상한 + 1 을 넘기면
    **그 자리에서 실패**하게 한다.
    """
    real = bs.combinations
    counted = {"made": 0}

    def spy(pool, size):
        for item in real(pool, size):
            counted["made"] += 1
            if counted["made"] > 8:
                raise AssertionError(
                    f"조합을 {counted['made']}개 만들었다 — 상한 4 에서는 "
                    "5개면 충분하다 (예전 구현은 184,756개를 만들었다)."
                )
            yield item

    monkeypatch.setattr(bs, "combinations", spy)
    options, truncated = selection_options(BIG_ASK, 4)
    assert truncated is True
    assert len(options) == 4
    #: 🔴 **정확히 limit + 1 개**만 만들었다.
    assert counted["made"] == 5, counted
    #: 🔴 예전 구현이 만들었을 수를 적어 둔다 (이 시험이 그 수를 만들지는
    #: 않는다 — 만들면 이 시험 자체가 느려진다).
    assert len(tuple(islice(combinations(range(1, 21), 10), 1))) == 1
    assert BIG_TOTAL == 184_756


def test_b03_alternatives_are_also_bounded(monkeypatch):
    """🔴 대안 목록도 같다 — 많아도 상한 + 2 개만 만든다 (고른 것 하나를 건너뛴다)."""
    real = bs.combinations
    counted = {"made": 0}

    def spy(pool, size):
        for item in real(pool, size):
            counted["made"] += 1
            if counted["made"] > 10:
                raise AssertionError(f"조합을 {counted['made']}개 만들었다")
            yield item

    monkeypatch.setattr(bs, "combinations", spy)
    realized = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
    alternatives, more = alternative_options(BIG_ASK, realized, 3)
    assert more is True
    assert alternatives == (
        (1, 2, 3, 4, 5, 6, 7, 8, 9, 11),
        (1, 2, 3, 4, 5, 6, 7, 8, 9, 12),
        (1, 2, 3, 4, 5, 6, 7, 8, 9, 13),
    )
    assert counted["made"] == 5, counted


def test_b04_the_three_boundaries(monkeypatch):
    """
    🟢 상한 0 · 조합 수가 상한과 같음 · 상한보다 하나 많음.

    🔴 **대안이 전혀 없는 자리를 잘렸다고 적지 않는다.**
    """
    three = _ask(3, minimum=1, maximum=1)  # 조합 3개
    assert selection_options(three, 3) == (((1,), (2,), (3,)), False)
    assert selection_options(three, 2) == (((1,), (2,)), True)
    assert selection_options(three, 0) == ((), True)
    assert selection_options(three, 9) == (((1,), (2,), (3,)), False)

    #: 낼 조합이 하나도 없는 자리 — 상한 0 이어도 **잘리지 않았다**.
    none_at_all = _ask(0, minimum=1, maximum=1)
    assert selection_options(none_at_all, 0) == ((), False)
    assert selection_options(none_at_all, 5) == ((), False)
    assert tuple(iter_selections(none_at_all)) == ()

    #: 후보보다 많이 고르라는 자리도 같다 (조합이 없다).
    too_many = _ask(2, minimum=3, maximum=4)
    assert selection_options(too_many, 5) == ((), False)

    #: 대안이 **고른 것 하나뿐**이면 더 볼 것이 없다.
    one = _ask(1, minimum=1, maximum=1)
    assert alternative_options(one, (1,), 0) == ((), False)
    assert alternative_options(one, (1,), 5) == ((), False)

    with pytest.raises(BoundedSearchError):
        selection_options(three, -1)
    with pytest.raises(BoundedSearchError):
        alternative_options(three, (1,), -1)


def test_b05_an_empty_choice_is_a_real_option():
    """
    🟢 ``minimum == 0`` 이면 **빈 짝이 허용 조합의 하나**다 — 아무것도
    고르지 않는 선택이 적법하다는 뜻이고, "조합이 없다" 와 다르다.
    """
    zero = _ask(2, minimum=0, maximum=1)
    assert tuple(iter_selections(zero)) == ((), (1,), (2,))
    assert selection_options(zero, 9) == (((), (1,), (2,)), False)
    #: 빈 선택을 이미 했으면 대안은 나머지 둘이다.
    assert alternative_options(zero, (), 9) == (((1,), (2,)), False)

    #: 장수 범위가 여러 개인 자리 — 작은 쪽부터 나온다.
    span = _ask(3, minimum=1, maximum=3)
    assert tuple(iter_selections(span)) == (
        (1,), (2,), (3,),
        (1, 2), (1, 3), (2, 3),
        (1, 2, 3),
    )
    assert selection_options(span, 4)[1] is True
    assert selection_options(span, 7) == (tuple(iter_selections(span)), False)


# ======================================================================
# B-2. 생략 기록 — 실제 탐색 경로에서
# ======================================================================
@dataclass
class _ChoiceScript:
    """
    한 행동에 **해결 중 선택 물음 여럿**을 흉내 내는 각본 (격리).

    🔴 production 의 ``_attempts`` 를 그대로 돌리고, 바꿔 끼우는 것은
    ``_apply_once`` 하나다 — 각본이 주어졌을 때 어떤 물음과 어떤 답이
    나왔는지를 그래프처럼 적어 둔다.
    """

    offers: tuple
    """물음마다 ``(후보 수, minimum, maximum)``."""

    def asks_for(self, plan: tuple) -> tuple:
        asks = []
        for index, (count, lowest, highest) in enumerate(self.offers):
            if index < len(plan):
                chosen = tuple(plan[index])
            else:
                #: 기준점 — 앞쪽에서 ``minimum`` 장.
                chosen = tuple(range(1, lowest + 1))
            asks.append(
                ChoiceAsk(
                    index=index,
                    label=f"물음{index}",
                    minimum=lowest,
                    maximum=highest,
                    offered=tuple(
                        (number, 1000 + number)
                        for number in range(1, count + 1)
                    ),
                    chosen=chosen,
                    planned=index < len(plan),
                )
            )
        return tuple(asks)


class _ScriptSearch(BoundedSearch):
    """``_apply_once`` 만 바꿔 끼운 탐색 — ``_attempts`` 는 production 이다."""

    def __init__(self, script: _ChoiceScript, **kwargs):
        super().__init__(**kwargs)
        self.script = script
        self.plans: list[tuple] = []

    def _apply_once(self, parent, action, plan):
        self.plans.append(plan)
        return bs._Attempt(
            accepted=True,
            reason="합성",
            asks=self.script.asks_for(plan),
            duel=parent.duel,
        )


def _branch(script: _ChoiceScript, cap: int):
    search = _ScriptSearch(
        script,
        goal=FieldGoal(card_id=GRAPH_GOAL_CARD, seat=P0),
        budget=SearchBudget(
            max_depth=4, max_nodes=500, max_choice_branches=cap
        ),
    )
    ledger = bs._Ledger()
    parent = Simulator(_GraphDuel(REVIEW_GRAPH, "R"))
    results = search._attempts(
        parent, _GraphAction("R", "A"), ledger, time.monotonic()
    )
    return search, ledger, results


def test_b06_a_cap_of_zero_still_records_the_omission():
    """
    🔴 **상한 0 이어도 생략 사실이 남는다** — 보완 전에는 남지 않았다.

    보완 전 ``_attempts`` 는 ``branches >= cap`` 이면 분기 고리를 **즉시
    끊었고**, 그래서 상한 0 에서는 대안이 있어도 아무것도 적지 않았다.
    """
    script = _ChoiceScript(offers=((3, 1, 1),))
    search, ledger, results = _branch(script, 0)
    assert len(results) == 1  # 기본 선택 한 번만 돌았다
    assert search.plans == [()]
    assert ledger.choice_branches == 0
    assert ledger.choice_plans == 0
    assert ledger.choice_offers_truncated == 1
    assert any("확인하지 않은 대안이 남았습니다" in line
               for line in ledger.out_of_scope)
    #: 🔴 **상한의 뜻이 문장에 적혀 있다** (세 수치를 가른다).
    assert any("대기에 넣은 대안 각본의 수" in line
               for line in ledger.out_of_scope)
    #: 🔴 그리고 그것은 **예산에 걸린 것**이다 — 범위를 다 펼친 것이 아니다.
    assert "max_choice_branches=0" in ledger.budget_hit


def test_b07_no_alternatives_is_not_an_omission():
    """🔴 **대안이 전혀 없는 자리까지 잘렸다고 적지 않는다.**"""
    #: 후보 1장 · 1장 선택 → 조합이 하나뿐이고 그것이 이미 고른 것이다.
    script = _ChoiceScript(offers=((1, 1, 1),))
    for cap in (0, 1, 5):
        search, ledger, results = _branch(script, cap)
        assert ledger.choice_offers_truncated == 0, cap
        assert ledger.out_of_scope == [], cap
        assert ledger.budget_hit == [], cap
        assert ledger.choice_branches == 0, cap


def test_b08_an_earlier_offer_can_use_up_the_cap():
    """
    🟢 **앞선 물음이 상한을 다 쓰면** 뒤의 물음에 남은 대안이 기록된다.

    물음 둘 — 앞은 후보 **4장**(대안 3개), 뒤는 후보 3장. 상한 2 는 앞에서
    다 쓰이고, 앞에서도 하나가 남는다.
    """
    script = _ChoiceScript(offers=((4, 1, 1), (3, 1, 1)))
    search, ledger, results = _branch(script, 2)
    assert ledger.choice_branches == 2
    #: 🔴 **두 물음 모두** 확인하지 못한 대안이 남았다 — 앞은 상한에 걸려
    #: 셋 중 둘만, 뒤는 남은 자리가 없어 하나도 못 봤다.
    assert ledger.choice_offers_truncated == 2
    assert sum("물음0" in line for line in ledger.out_of_scope) == 1
    assert sum("물음1" in line for line in ledger.out_of_scope) == 1
    #: 대기에 넣은 각본이 전부 돌았다 (예산이 넉넉하다).
    assert ledger.choice_plans == 2
    assert len(results) == 3  # 기본 + 대안 둘
    #: 🔴 **이미 한 선택과 새로 해 본 대안을 가른다.**
    assert search.plans[0] == ()
    assert all(plan for plan in search.plans[1:])


def test_b09_several_offers_each_get_their_alternatives():
    """
    🟢 한 행동에 **물음이 여럿**이면 각자 대안을 받는다 (상한이 넉넉할 때).

    🔴 그리고 **생략이 없으면 아무 기록도 남지 않는다.**
    """
    script = _ChoiceScript(offers=((2, 1, 1), (2, 1, 1)))
    search, ledger, results = _branch(script, 8)
    #: 물음마다 대안 하나 — 둘이다. 그리고 첫 대안을 돌린 뒤 그 각본에서
    #: 둘째 물음의 대안이 한 번 더 생긴다.
    assert ledger.choice_branches >= 2
    assert ledger.choice_offers_truncated == 0
    assert ledger.out_of_scope == []
    assert ledger.budget_hit == []
    assert ledger.choice_plans == ledger.choice_branches
    assert len(results) == 1 + ledger.choice_plans


def test_b10_the_queued_and_run_counters_do_not_mix():
    """
    🔴 **대기에 넣은 수와 돌린 수를 섞지 않는다.** 노드 예산이 고리를
    끊으면 대기한 것보다 적게 돈다.
    """
    script = _ChoiceScript(offers=((5, 1, 1),))
    search = _ScriptSearch(
        script,
        goal=FieldGoal(card_id=GRAPH_GOAL_CARD, seat=P0),
        #: 🔴 노드 상한 2 — 기본 각본 하나와 대안 하나만 돌 수 있다.
        budget=SearchBudget(max_depth=4, max_nodes=2, max_choice_branches=8),
    )
    ledger = bs._Ledger()
    parent = Simulator(_GraphDuel(REVIEW_GRAPH, "R"))
    results = search._attempts(
        parent, _GraphAction("R", "A"), ledger, time.monotonic()
    )
    assert ledger.choice_branches == 4  # 대기에 넣은 대안 (후보 5 - 고른 1)
    assert ledger.choice_plans == 1  # 실제로 돌린 대안
    assert len(results) == 2
    assert any("max_nodes=2" in line for line in ledger.budget_hit)
    #: 🔴 대안을 다 확인했으므로 **선택 생략은 없다** — 끊은 것은 노드
    #: 예산이고, 그 둘은 다른 사실이다.
    assert ledger.choice_offers_truncated == 0
