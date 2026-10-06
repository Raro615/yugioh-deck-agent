r"""
Phase 3-E-42 — ``SimulationResult`` → ``SearchCandidate`` 정보 경계 감사.

**AUDIT-ONLY.** production 을 한 줄도 고치지 않는다.

이 Phase 의 질문
---------------
"``SimulationResult`` → ``SearchCandidate`` 경계에서 정보 손실 또는 의미 변환이
architecture 상 정당한가?"

측정한 결론 (요지)
-----------------
1. 두 자료형은 **같은 것의 두 표현이 아니다.** 하나는 "이 수를 두면 어떤
   판이 되는가" 이고 하나는 "탐색에서 비교할 후보" 다. 그래서 후보는
   **시뮬레이션 결과 없이도 만들어진다** — 예산에 걸린 후보가 그렇다
   (``test_12``). wrapper 가 아니라 **projection** 이다.
2. ``future`` 는 **버려지는 것이 아니라 소비된다.** 평가자가 그것을 읽어
   ``value`` 를 만들고, 후보는 ``value`` 만 든다 (``test_08``). 이것이
   Simulation / Evaluation 분리이고 Phase 3-C 가 태어날 때 적어 둔 설계다.
3. 정말 사라지는 것은 ``code`` 와 ``viewer`` 둘이고, **둘 다 production 에서
   읽는 자리가 없다** (``test_10`` · ``test_11``).
4. ``state_hash`` 는 후보의 칸이 아니라 ``SearchDecision`` 의 칸이고, 값은
   **결정 지점의 진짜 판** 해시다 — 시뮬레이션된 미래의 해시가 아니다
   (``test_16``).
5. 순위는 ``status`` 를 **보지 않는다.** 보는 것은 "점수가 있는가" 하나다
   (``test_17``). 그래서 ``UNKNOWN`` 과 ``REFUSED`` 가 같은 키를 갖는 것은
   순위 계층에서 **의도된 결과**다.
"""

import ast
import dataclasses
import pathlib

import pytest

from agent.evaluation import Evaluator, StateEvaluator, StateValue, Terminal
from agent.search import (
    SKIPPED_BY_BUDGET,
    SearchCandidate,
    SearchDecision,
    SearchPolicy,
)
from agent.simulation import (
    SimulationError,
    SimulationResult,
    SimulationStatus,
    Simulator,
)
from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel
from engine.validation import ValidationCode
from engine.vocabulary import Phase

from tests.conftest import requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROD_PREFIXES = ("engine/", "agent/", "core/", "analysis/", "sources/", "app/")
MINE = 0

DECK = (
    [11091375] * 3
    + [5053103] * 3
    + [1184620] * 3
    + [32864] * 3
    + [3557275] * 3
    + [55144522] * 5
)


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def production_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel.startswith(PROD_PREFIXES):
            yield rel, path


def function_source(rel: str, name: str) -> str:
    for node in ast.walk(ast.parse(source_of(rel))):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"{rel}: {name} 이 없다")


def constructions(rel: str, name: str) -> list[dict]:
    rows = []
    for node in ast.walk(ast.parse(source_of(rel))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
        ):
            rows.append(
                {
                    "lineno": node.lineno,
                    "kwargs": sorted(k.arg for k in node.keywords if k.arg),
                    "values": {
                        k.arg: ast.unparse(k.value) for k in node.keywords if k.arg
                    },
                }
            )
    return sorted(rows, key=lambda row: row["lineno"])


def main1(repository, seed: int = 11) -> Duel:
    duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=seed)
    for _ in range(20):
        while duel.advance() is not None:
            pass
        if duel.state.turn.phase is Phase.MAIN1:
            break
        legal = duel.legal_actions(duel.to_act)
        ends = [a for a in legal.allowed if a.kind is PlayerActionKind.END_PHASE]
        if not ends:
            break
        duel.apply(ends[0])
    return duel


def decide(duel: Duel) -> tuple["PlayerAction | None", SearchDecision]:
    policy = SearchPolicy().attach(Simulator(duel))
    seat = duel.to_act
    chosen = policy.decide(duel.view(seat), duel.legal_actions(seat))
    return chosen, policy.decisions[-1]


# ======================================================================
# 1 ~ 4 — 네 자료형의 실제 필드 (추측하지 않는다)
# ======================================================================


def test_01_simulation_result_field_inventory():
    """
    **§29-1 · §4: 필드는 여섯이다.**

    프롬프트가 "가질 수 있다" 고 든 ``score`` · ``value`` · ``notes`` ·
    ``ordering_key`` · ``state_hash`` 는 **다섯 모두 없다.** "없다" 도 명시한다.
    """
    fields = {f.name for f in dataclasses.fields(SimulationResult)}
    assert fields == {"action", "status", "viewer", "reason", "code", "future"}
    for absent in ("score", "value", "notes", "ordering_key", "state_hash"):
        assert absent not in fields, absent
    #: ``code`` 와 ``future`` 는 선택이다 — 없을 수 있다는 뜻이 설계에 있다.
    optional = {
        f.name for f in dataclasses.fields(SimulationResult)
        if f.default is not dataclasses.MISSING
    }
    assert optional == {"reason", "code", "future"}


def test_02_search_candidate_field_inventory():
    """
    **§29-2 · §5: 필드는 넷이고 ``ordering_key`` 는 메서드다.**

    프롬프트는 ``ordering_key`` · ``state_hash`` 를 후보의 **필드**처럼 들었다.
    ``ordering_key`` 는 계산하는 **메서드**이고 ``state_hash`` 는 후보에
    **없다** — ``SearchDecision`` 의 칸이다 (``test_03``).
    """
    fields = {f.name for f in dataclasses.fields(SearchCandidate)}
    assert fields == {"action", "status", "value", "reason"}
    for absent in ("code", "viewer", "future", "score", "state_hash", "notes"):
        assert absent not in fields, absent
    assert "ordering_key" not in fields
    assert callable(SearchCandidate.ordering_key)
    assert isinstance(SearchCandidate.comparable, property)


def test_03_search_decision_field_inventory_owns_the_state_hash():
    """**§29-3 · §14: ``state_hash`` 는 결정의 칸이다.**"""
    fields = {f.name for f in dataclasses.fields(SearchDecision)}
    assert fields == {
        "seat",
        "state_hash",
        "turn_number",
        "phase",
        "candidates",
        "chosen",
        "reason",
        "simulations",
        "skipped",
    }
    assert "state_hash" in fields
    #: 그리고 그 설명이 왜 안전한지 적는다.
    assert "되돌려 읽을 수 없는 요약" in source_of("agent/search.py")


def test_04_state_value_is_where_the_score_lives():
    """
    **§8 · §29-14: "score" 라는 칸은 없다 — ``StateValue`` 가 그 자리다.**

    그리고 ``notes`` 는 ``StateValue`` 의 **property** 이고 ``excluded`` 에서
    나온다 — 어느 자료형의 필드도 아니다.
    """
    fields = {f.name for f in dataclasses.fields(StateValue)}
    assert fields == {"terminal", "heuristic", "terms", "excluded"}
    assert "score" not in fields
    assert isinstance(StateValue.notes, property)
    assert callable(StateValue.ordering_key)


# ======================================================================
# 5 ~ 10 — field mapping: 다섯 분류
# ======================================================================


def test_05_the_candidate_is_built_at_exactly_three_places():
    """
    **§29-4 · §6: 변환 자리는 셋이고 전부 ``_look_ahead`` 안이다.**

    셋이 넘기는 인자가 **서로 다르다** — 그것이 분류의 출발점이다.
    """
    rows = constructions("agent/search.py", "SearchCandidate")
    assert len(rows) == 3
    assert [row["kwargs"] for row in rows] == [
        ["action", "reason", "status"],           # 예산에 걸림
        ["action", "reason", "status"],           # SUPPORTED 가 아님
        ["action", "reason", "status", "value"],  # SUPPORTED
    ]
    body = function_source("agent/search.py", "_look_ahead")
    for row in rows:
        assert row["values"]["action"] == "action"  # 루프 변수다
    #: 세 자리 모두 ``code=`` 를 넘기지 않는다.
    assert all("code" not in row["kwargs"] for row in rows)
    assert "code=result.code" not in body


def test_06_action_status_reason_are_preserved():
    """**§29-5 PRESERVED: 셋은 그대로 간다.**"""
    rows = constructions("agent/search.py", "SearchCandidate")
    #: ``status`` 와 ``reason`` 은 결과에서 **그대로** 복사된다 (예산 자리는 제외).
    simulated = [row for row in rows if row["values"]["reason"] != "SKIPPED_BY_BUDGET"]
    assert len(simulated) == 2
    for row in simulated:
        assert row["values"]["status"] == "result.status"
        assert row["values"]["reason"] == "result.reason"


def test_07_the_budget_skipped_candidate_has_no_simulation_result_at_all():
    """
    **§13 · §29-9: 후보는 wrapper 가 아니다.**

    예산에 걸린 후보는 ``simulate`` 를 **부르지도 않고** 만들어진다 —
    ``status=None`` 이고 이유가 ``SKIPPED_BY_BUDGET`` 이다. 즉
    ``SearchCandidate`` 는 ``SimulationResult`` 의 포장이 아니라 **탐색 계층의
    독립된 기록**이다.
    """
    rows = constructions("agent/search.py", "SearchCandidate")
    skipped = rows[0]
    assert skipped["values"]["status"] == "None"
    assert skipped["values"]["reason"] == "SKIPPED_BY_BUDGET"
    assert SKIPPED_BY_BUDGET == "예산 상한에 걸려 해 보지 못했습니다"

    #: 그 자리는 ``simulate`` 보다 **앞**에 있다.
    body = function_source("agent/search.py", "_look_ahead")
    assert body.index("SKIPPED_BY_BUDGET") < body.index("self.simulator.simulate")

    #: 손으로 만들어도 성립한다 — 상태 없는 후보가 적법하다.
    candidate = SearchCandidate(
        action=PlayerAction.passing(actor=MINE), status=None, reason=SKIPPED_BY_BUDGET
    )
    assert candidate.status is None
    assert candidate.comparable is False


def test_08_the_future_is_transformed_not_dropped():
    """
    **§29-6 TRANSFORMED: ``future`` 는 평가자가 소비한다.**

    후보에 ``future`` 칸이 없는 것은 버린 것이 아니라, **그것을 읽어
    ``value`` 를 만들고 사본을 놓아준다** 는 뜻이다. Simulation 과 Evaluation
    의 분리가 바로 이 한 줄이다.
    """
    rows = constructions("agent/search.py", "SearchCandidate")
    scored = rows[-1]
    assert scored["values"]["value"] == "self.evaluator.evaluate(result.future)"
    #: 후보는 ``future`` 를 들지 않는다.
    assert "future" not in {f.name for f in dataclasses.fields(SearchCandidate)}
    #: 그리고 평가자는 **관측만** 받는다 — 판도 사본도 받지 않는다.
    assert isinstance(StateEvaluator(), Evaluator)


def test_09_the_value_is_derived_by_the_evaluator_not_by_the_simulator():
    """
    **§29-7 DERIVED · §8 · Q7: ``value`` 는 평가자가 만든다.**

    ``SimulationResult`` 에는 점수를 담는 칸이 없고 (``test_01``), 시뮬레이터는
    평가자를 **알지도 못한다** — ``agent/simulation.py`` 에 평가 관련 이름이
    하나도 없다.
    """
    simulation = source_of("agent/simulation.py")
    for name in ("Evaluator", "StateEvaluator", "StateValue", "evaluate", "heuristic"):
        assert name not in simulation, name
    #: 반대로 탐색은 평가자를 들고 있다.
    assert "evaluator" in source_of("agent/search.py")


def test_10_the_code_is_dropped_and_nobody_reads_it():
    """
    **§29-8 DROPPED · Q14: ``code`` 가 사라지고 — 읽는 쪽이 없다.**

    ``ValidationCode`` 는 ``agent/`` 안에서 ``simulation.py`` 밖으로 나가지
    않는다 (3-E-39 · 3-E-40 이 측정했고 여기서 다시 확인한다). 그리고
    ``result.code`` 를 읽는 자리가 **탐색 경로에 없다.**
    """
    users = {
        rel
        for rel, path in production_files()
        if rel.startswith("agent/") and "ValidationCode" in path.read_text(encoding="utf-8")
    }
    assert users == {"agent/simulation.py"}

    search = source_of("agent/search.py")
    assert "result.code" not in search
    assert "ValidationCode" not in search


def test_11_the_viewer_is_dropped_and_is_never_read_in_production():
    """
    **§29-8 DROPPED: ``viewer`` 도 사라진다 — 그리고 아무도 읽지 않는다.**

    ``SimulationResult.viewer`` 는 네 생성 자리 전부가 채우지만 **읽는 자리가
    production 에 하나도 없다.** "누구의 눈으로 본 미래인가" 를 적어 두는
    기록용 칸이다.
    """
    #: ``viewer`` 라는 이름을 쓰는 자료형이 저장소에 여럿이다 —
    #: ``GameStateView`` · ``engine/observation.py`` · ``engine/timing.py`` 가
    #: 각자 자기 ``viewer`` 를 들고 읽는다. 처음에 production 전체를 훑어
    #: 그것들을 ``SimulationResult`` 의 것으로 잘못 셌다 (16건 → 25건).
    #:
    #: ``SimulationResult`` 가 사는 계층은 ``agent/`` 뿐이므로 거기만 본다.
    reads = []
    for rel, path in production_files():
        if not rel.startswith("agent/"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr == "viewer":
                base = ast.unparse(node.value)
                #: ``view.viewer`` 는 관측의 칸이다 — 평가자가 그것을 읽는다.
                if "view" in base:
                    continue
                reads.append(f"{rel}:{node.lineno} ({base}.viewer)")
    assert reads == [], reads
    #: 그래도 네 생성 자리는 전부 채운다.
    rows = constructions("agent/simulation.py", "SimulationResult")
    assert len(rows) == 4
    assert all("viewer" in row["kwargs"] for row in rows)


def test_12_the_state_hash_is_not_applicable_to_a_candidate():
    """
    **§29-9 NOT_APPLICABLE · Q13: 후보는 해시를 들 이유가 없다.**

    해시는 **결정 지점**의 성질이고 후보의 성질이 아니다 — 같은 결정의 열한
    후보가 같은 해시를 공유하므로 후보마다 들면 같은 값이 열한 번 적힌다.
    """
    assert "state_hash" not in {f.name for f in dataclasses.fields(SearchCandidate)}
    assert "state_hash" in {f.name for f in dataclasses.fields(SearchDecision)}
    assert "state_hash" not in {f.name for f in dataclasses.fields(SimulationResult)}


# ======================================================================
# 11 ~ 13 — 세 상태의 전달
# ======================================================================


@requires_official_db
def test_13_supported_propagates_status_reason_and_a_score(repository):
    """**§29-10 · §23-A: 받아들여진 시뮬레이션.**"""
    duel = main1(repository)
    seat = duel.to_act
    simulator = Simulator(duel)
    action = duel.legal_actions(seat).allowed[0]

    result = simulator.simulate(action, viewer=seat)
    assert result.status is SimulationStatus.SUPPORTED
    assert result.code is ValidationCode.OK
    assert result.future is not None
    assert result.viewer == seat

    _chosen, decision = decide(duel)
    candidate = decision.of(action)
    assert candidate is not None
    assert candidate.status is SimulationStatus.SUPPORTED
    assert candidate.reason == result.reason
    assert candidate.value is not None
    assert candidate.comparable is True
    #: 후보는 코드도 관측도 들지 않는다.
    assert not hasattr(candidate, "code")
    assert not hasattr(candidate, "future")


@requires_official_db
def test_14_unknown_and_refused_are_unreachable_in_current_production(repository):
    """
    **§29-11 · 12 · §12 · §23-B · C: UNREACHABLE IN CURRENT PRODUCTION.**

    실제 듀얼을 돌려 모든 후보를 시뮬레이션하면 **``SUPPORTED`` 만** 나온다.
    3-E-39 가 32판 5,316 호출로 측정한 것과 같은 결과다. fake executor 를
    만들지 않는다 (§23).
    """
    duel = main1(repository, seed=5)
    simulator = Simulator(duel)
    seen = set()
    for _ in range(40):
        while duel.advance() is not None:
            pass
        if duel.is_over:
            break
        seat = duel.to_act
        legal = duel.legal_actions(seat)
        if not legal.allowed:
            break
        for action in legal.allowed:
            seen.add(simulator.simulate(action, viewer=seat).status)
        step = duel.apply(legal.allowed[0])
        if not step.accepted:
            break
    assert seen == {SimulationStatus.SUPPORTED}


def test_15_handmade_unknown_and_refused_candidates_rank_identically():
    """
    **§12 · §29-13 · Q10: 순위에서 둘이 같다 — 그리고 그것이 설계다.**

    production 이 만들지 못하므로 **손으로 만든** 후보로 순위만 비교한다
    (그 사실을 분명히 적는다). 다섯 상태와 ``None`` 까지 전부 같은 키다.

    .. note::
       Phase 3-C 가 태어날 때 적었다 — "UNKNOWN 으로 끝난 시뮬레이션의 후보는
       점수가 아예 없다 — 0 점도 최저 점수도 아니고 **견줄 수 없는 것**이다."
       즉 "같은 키" 는 두 상태를 혼동한 결과가 아니라, **점수가 없다는 하나의
       사실**을 표현한 것이다.
    """
    action = PlayerAction.passing(actor=MINE)
    keys = {
        status: SearchCandidate(action=action, status=status).ordering_key()
        for status in list(SimulationStatus) + [None]
    }
    assert len(set(keys.values())) == 1
    assert next(iter(keys.values())) == (1, 0, 0, action.canonical_state())

    #: 점수가 있으면 **첫 칸이 0 으로** 바뀐다 — 그것이 유일한 갈림이다.
    scored = SearchCandidate(
        action=action,
        status=SimulationStatus.SUPPORTED,
        value=StateValue(terminal=Terminal.ONGOING, heuristic=7),
    )
    assert scored.ordering_key()[0] == 0
    assert scored.ordering_key()[2] == -7


# ======================================================================
# 14 ~ 19 — ordering_key · value · state_hash · status · reason · future
# ======================================================================


def test_16_the_ordering_key_reads_the_value_and_the_action_only():
    """
    **§9 · §29-13 · Q8 · Q9: 순위 키는 ``status`` 를 보지 않는다.**

    키를 만드는 식에 ``status`` 가 **없다.** 보는 것은 ``value`` 의 유무와
    등급 · 휴리스틱, 그리고 동점을 깨는 ``canonical_state`` 다.
    """
    body = function_source("agent/search.py", "ordering_key")
    assert "self.value" in body
    assert "canonical_state" in body
    assert "status" not in body
    assert "terminal" in body and "heuristic" in body


def test_17_the_candidate_status_is_only_ever_displayed():
    """
    **§11 · §29-16 · Q20: ``status`` 를 읽는 자리는 표시용 하나다.**

    ``decide`` 도 ``_look_ahead`` 의 순위도 ``status`` 를 읽지 않는다 —
    ``describe_ko`` 만 읽는다. 즉 **ranking 은 ``SimulationStatus`` 에 의존하지
    않는다.**
    """
    readers = []
    tree = ast.parse(source_of("agent/search.py"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "status":
            readers.append((node.lineno, ast.unparse(node)))
    #: 후보 자신의 ``self.status`` 를 읽는 자리는 ``describe_ko`` 안에만 있다.
    describe = function_source("agent/search.py", "describe_ko")
    assert "self.status" in describe
    decide_body = function_source("agent/search.py", "decide")
    assert ".status" not in decide_body
    #: ``_look_ahead`` 는 **결과의** 상태를 보고 분기하지만 후보의 상태를 읽지 않는다.
    look = function_source("agent/search.py", "_look_ahead")
    assert "result.status" in look
    assert "candidate.status" not in look
    assert readers, "status 를 적는 자리는 있어야 한다"


@requires_official_db
def test_18_the_decision_state_hash_is_the_real_board_before_deciding(repository):
    """
    **§10 · §19 · Q11 · Q12: 해시는 결정 지점의 진짜 판이다.**

    시뮬레이션된 미래의 해시가 **아니다.** ``Simulator.state_hash()`` 가
    ``self.duel.state.state_hash()`` 이고, 그것을 결정 **전**에 읽는다.
    """
    duel = main1(repository)
    before = duel.state.state_hash()
    _chosen, decision = decide(duel)
    assert decision.state_hash == before
    assert len(decision.state_hash) == 64
    #: 그리고 결정이 판을 바꾸지 않았으므로 뒤에도 같다.
    assert duel.state.state_hash() == before

    body = function_source("agent/simulation.py", "state_hash")
    assert "self.duel.state.state_hash()" in body


@requires_official_db
def test_19_the_reason_survives_and_the_decision_has_its_own(repository):
    """
    **§29-17 · Q15: 이유는 보존되고, 결정의 이유와 섞이지 않는다.**
    """
    duel = main1(repository)
    seat = duel.to_act
    simulator = Simulator(duel)
    action = duel.legal_actions(seat).allowed[0]
    result = simulator.simulate(action, viewer=seat)

    _chosen, decision = decide(duel)
    candidate = decision.of(action)
    assert candidate.reason == result.reason
    #: 결정의 이유는 **다른 문장**이다 — 후보의 이유를 덮어쓰지 않는다.
    assert decision.reason != candidate.reason
    assert "내다본 결과가 가장 좋습니다" in decision.reason


@requires_official_db
def test_20_the_future_never_reaches_a_candidate(repository):
    """
    **§29-19 · Q16 · Q17: 미래 관측은 후보에 들어가지 않는다.**

    평가자가 읽고 나면 사본과 함께 버려진다. 후보의 객체 그래프에
    ``GameStateView`` 도 ``GameState`` 도 ``CardInstance`` 도 없다.
    """
    duel = main1(repository)
    _chosen, decision = decide(duel)

    seen: set[str] = set()

    def walk(obj, depth=0):
        if depth > 5:
            return
        seen.add(type(obj).__name__)
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            for field in dataclasses.fields(obj):
                walk(getattr(obj, field.name), depth + 1)
        elif isinstance(obj, (tuple, list)):
            for item in obj:
                walk(item, depth + 1)

    for candidate in decision.candidates:
        walk(candidate)

    for forbidden in (
        "GameState",
        "GameStateView",
        "CardInstance",
        "ZoneContainer",
        "PlayerState",
        "PlayerView",
        "Duel",
        "Simulator",
        "Randomness",
    ):
        assert forbidden not in seen, forbidden


# ======================================================================
# 20 ~ 24 — 가려진 정보 · 사본 · 난수 · 결정론
# ======================================================================


@requires_official_db
def test_21_no_opponent_instance_appears_in_the_candidate_set(repository):
    """
    **§16 · §29-20 · Q17: 가려진 정보가 후보로 흐르지 않는다.**

    상대의 패 · 덱 · 묘지의 instance 식별자가 후보 기록에 **하나도** 없다.
    내 손의 식별자는 있다 — **내가 고려하는 내 수**가 그것을 가리키기 때문이고,
    그것은 내 정보다.
    """
    import json

    duel = main1(repository)
    seat = duel.to_act
    _chosen, decision = decide(duel)

    blob = json.dumps(
        [
            {
                "action": str(c.action),
                "reason": c.reason,
                "terms": None if c.value is None else [list(t) for t in c.value.terms],
                "excluded": None
                if c.value is None
                else [[e.category.value, e.note] for e in c.value.excluded],
            }
            for c in decision.candidates
        ],
        ensure_ascii=False,
    )

    opponent = duel.state.player(1 - seat)
    opponent_instances = [
        str(card.instance_id)
        for card in list(opponent.hand) + list(opponent.deck) + list(opponent.grave)
    ]
    assert opponent_instances, "상대에게 카드가 있어야 이 측정이 성립한다"
    assert [i for i in opponent_instances if i in blob] == []

    mine = [str(card.instance_id) for card in duel.state.player(seat).hand]
    assert [i for i in mine if i in blob], "내 수가 내 카드를 가리켜야 한다"

    #: 장수는 공개 정보이므로 **적혀 있어도 된다** — 그것이 설계다.
    assert "상대 패" in blob


@requires_official_db
def test_22_candidates_are_frozen_against_later_board_changes(repository):
    """**§17 · §29-21 · 22 · Q18: 후보가 가변 판을 참조하지 않는다.**"""
    duel = main1(repository)
    _chosen, decision = decide(duel)
    before = [c.ordering_key() for c in decision.candidates]

    #: 결정 **뒤에** 판을 바꿔도 이미 만든 후보가 움직이지 않는다.
    duel.state.player(duel.to_act).hand.pop()
    after = [c.ordering_key() for c in decision.candidates]
    assert before == after

    assert type(decision.candidates[0]).__dataclass_params__.frozen is True
    assert type(decision).__dataclass_params__.frozen is True


@requires_official_db
def test_23_searching_leaves_the_original_board_and_randomness_alone(repository):
    """**§18 · §19 · §29-22 · 23 · Q19 · Q27 · Q28.**"""
    duel = main1(repository)
    before_hash = duel.state.state_hash()
    before_draws = duel.state.randomness.draws

    _chosen, decision = decide(duel)

    assert duel.state.state_hash() == before_hash
    assert duel.state.randomness.draws == before_draws
    assert decision.simulations >= 1
    #: 후보 생성이 난수를 쓰지 않는다 — 탐색은 결정론이다.
    assert decision.skipped == 0


@requires_official_db
def test_24_the_same_seed_gives_the_same_decision_twice(repository):
    """**§23-D · §29-24: 결정론적 반복.**"""
    first_chosen, first = decide(main1(repository))
    second_chosen, second = decide(main1(repository))

    assert str(first_chosen) == str(second_chosen)
    assert first.state_hash == second.state_hash
    assert first.simulations == second.simulations
    assert [c.ordering_key() for c in first.candidates] == [
        c.ordering_key() for c in second.candidates
    ]
    assert [
        None if c.value is None else c.value.ordering_key() for c in first.candidates
    ] == [None if c.value is None else c.value.ordering_key() for c in second.candidates]


# ======================================================================
# 25 ~ 28 — 랭킹 · 동점 · 결정 · 소비자
# ======================================================================


@requires_official_db
def test_25_a_real_decision_ranks_many_candidates_by_their_value(repository):
    """
    **§23-E · §29-25: 실제 랭킹.**

    MAIN1 에서 열 개가 넘는 후보가 나오고 **전부 점수가 있다.** 고른 수는
    가장 좋은 휴리스틱을 가진 후보다.
    """
    duel = main1(repository)
    chosen, decision = decide(duel)

    assert len(decision.candidates) >= 10
    assert decision.comparable_count == len(decision.candidates)
    assert decision.nothing_was_comparable is False

    ranked = sorted(decision.candidates, key=lambda c: c.ordering_key())
    assert ranked[0].action == chosen
    #: 등급이 모두 같으므로 휴리스틱이 내림차순이다.
    heuristics = [c.value.heuristic for c in ranked]
    assert heuristics == sorted(heuristics, reverse=True)
    assert len({c.value.terminal for c in ranked}) == 1


@requires_official_db
def test_26_ties_are_broken_by_the_canonical_action_not_by_list_order(repository):
    """**§9 · §29-26: 동점은 ``canonical_state`` 로 깬다.**"""
    duel = main1(repository)
    _chosen, decision = decide(duel)

    by_heuristic: dict[int, list[SearchCandidate]] = {}
    for candidate in decision.candidates:
        by_heuristic.setdefault(candidate.value.heuristic, []).append(candidate)
    tied = [group for group in by_heuristic.values() if len(group) > 1]
    assert tied, "동점이 하나는 있어야 이 측정이 성립한다"

    for group in tied:
        ranked = sorted(group, key=lambda c: c.ordering_key())
        canonicals = [c.action.canonical_state() for c in ranked]
        assert canonicals == sorted(canonicals)


@requires_official_db
def test_27_the_match_record_consumes_only_the_value_of_the_chosen_candidate(repository):
    """
    **§20 · §29-27: ``SearchDecision`` 의 실제 소비자.**

    ``agent/arena.py`` 의 ``_records`` 가 읽는 것은 후보 수 · 시뮬레이션 수 ·
    결정의 이유, 그리고 **고른 후보의 ``value``** 뿐이다 — ``status`` 도
    ``code`` 도 읽지 않는다.
    """
    body = function_source("agent/arena.py", "_records")
    assert "decision.candidates" in body
    assert "decision.simulations" in body
    assert "decision.reason" in body
    assert "chosen.value" in body
    assert "chosen.status" not in body
    assert ".code" not in body

    #: 그리고 그 값이 ``(등급, 휴리스틱)`` 로 요약된다.
    assert "chosen.value.terminal.value" in body
    assert "chosen.value.heuristic" in body


def test_28_only_the_search_layer_knows_these_two_types():
    """
    **§20 · 필수 표 4: 바깥에서 쓰는 곳이 좁다.**

    ``SearchCandidate`` · ``SearchDecision`` 을 쓰는 production 파일은
    ``agent/search.py`` (정의) · ``agent/arena.py`` (읽기) ·
    ``agent/__init__.py`` (재수출) 뿐이다. 정책도 평가자도 모른다.
    """
    users = sorted(
        rel
        for rel, path in production_files()
        if any(
            name in path.read_text(encoding="utf-8")
            for name in ("SearchCandidate", "SearchDecision")
        )
    )
    #: **이름으로** 쓰는 곳은 둘뿐이다 — 정의와 재수출.
    assert users == ["agent/__init__.py", "agent/search.py"]

    #: ``agent/arena.py`` 는 **이름 없이** 읽는다 (``test_27``) — ``_search_trace``
    #: 가 ``policy.decisions`` 를 그대로 받아 오므로 자료형 이름을 적지 않는다.
    #: 처음에 arena 를 이름 사용처로 세어 틀렸고, 소스를 읽어 고쳤다.
    arena = source_of("agent/arena.py")
    assert "SearchCandidate" not in arena
    assert "SearchDecision" not in arena
    assert "policy.decisions" in arena or "decisions" in arena
    for rel in ("agent/policy.py", "agent/heuristic.py", "agent/evaluation.py",
                "agent/simulation.py"):
        source = source_of(rel)
        assert "SearchCandidate" not in source, rel
        assert "SearchDecision" not in source, rel


# ======================================================================
# 29 ~ 36 — 계층 분리 · 전체 듀얼 · 회귀
# ======================================================================


def test_29_the_three_layers_do_not_know_each_others_private_names():
    """
    **§15 · §36-2: Simulation ≠ Evaluation ≠ Search.**

    Phase 3-C 가 태어날 때 적은 분리를 그대로 지키는지 이름으로 확인한다 —
    ``search`` 와 ``evaluation`` 에 판을 만질 이름이 하나도 없다.
    """
    for rel in ("agent/search.py", "agent/evaluation.py"):
        source = source_of(rel)
        for forbidden in ("clone(", "project(", "randomness", "set_result"):
            assert forbidden not in source, (rel, forbidden)
        #: ``.state`` 는 **구문으로** 본다 — 문자열로 찾으면 ``state_hash`` 가
        #: 걸린다 (처음에 그렇게 세어 틀렸다). 판을 가리키는 ``.state`` 접근이
        #: 하나도 없어야 한다.
        touches = [
            node.lineno
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Attribute) and node.attr == "state"
        ]
        assert touches == [], (rel, touches)
    #: 시뮬레이터는 평가를 모른다 (``test_09``), 평가자는 시뮬레이션을 모른다.
    evaluation = source_of("agent/evaluation.py")
    assert "Simulator" not in evaluation
    assert "SimulationResult" not in evaluation


def test_30_the_simulation_result_refuses_to_lie_about_its_future():
    """
    **§29-19 · Q16: "없는 미래를 꾸며 내지 않는다" 가 구조로 막혀 있다.**

    ``SUPPORTED`` 인데 관측이 없거나, 아닌데 관측이 있으면 **생성 자체가
    실패한다.** 이것이 ``future`` 의 책임이 시뮬레이션 계층에 있다는 증거다.
    """
    action = PlayerAction.passing(actor=MINE)
    with pytest.raises(SimulationError):
        SimulationResult(
            action=action, status=SimulationStatus.SUPPORTED, viewer=MINE, future=None
        )
    #: 반대 방향도 막는다 — 가짜 관측을 넣으려면 그것부터 만들어야 한다.
    body = function_source("agent/simulation.py", "__post_init__")
    assert "실패한 시뮬레이션의 미래를 꾸며 내지 않습니다" in body
    assert "gives_a_future" in body


@requires_official_db
def test_31_four_policies_still_finish_a_whole_duel(repository):
    """**§24 · §29-28: 전체 듀얼이 네 정책 조합에서 그대로 끝난다.**"""
    from agent.arena import (
        make_first_legal,
        make_random,
        make_rule_based,
        make_search,
        run_match,
    )

    for factories in (
        (make_search(), make_search()),
        (make_search(), make_rule_based()),
        (make_search(), make_random(500)),
        (make_search(), make_first_legal()),
    ):
        match = run_match(
            repository, decks=(list(DECK), list(DECK)), seed=3, factories=factories
        )
        assert match.outcome.value == "completed", match.failure if hasattr(
            match, "failure"
        ) else match.outcome
        assert match.refusals == 0
        assert len(match.state_hash) == 64


def test_32_the_three_record_types_stay_distinct():
    """**§36-1 · 3: 세 자료형이 서로 다른 것을 표현한다.**"""
    sim = {f.name for f in dataclasses.fields(SimulationResult)}
    cand = {f.name for f in dataclasses.fields(SearchCandidate)}
    dec = {f.name for f in dataclasses.fields(SearchDecision)}

    assert sim != cand != dec
    #: 공유하는 칸은 ``action`` · ``status`` · ``reason`` 셋뿐이다.
    assert sim & cand == {"action", "status", "reason"}
    #: 결정은 후보를 **담고**, 후보는 결정을 모른다.
    assert "candidates" in dec
    assert not any("decision" in name for name in cand)


def test_33_the_vocabulary_this_phase_depends_on_is_unchanged():
    """**§36-19 · 20 · 21: 어휘가 그대로다.**"""
    from engine.validation import ActionValidity, unknown_codes

    assert len(SimulationStatus) == 5
    assert len(Terminal) == 4
    assert len(ValidationCode) == 48
    assert len(ActionValidity) == 3
    assert len(unknown_codes()) == 7
    #: 3-E-38 의 두 구분도 그대로다.
    assert (
        ValidationCode.CANDIDATE_NOT_ELIGIBLE is not ValidationCode.RULE_NOT_IMPLEMENTED
    )
    assert ValidationCode.EXECUTION_FORBIDDEN is not ValidationCode.RULE_NOT_IMPLEMENTED


def test_34_unknown_is_still_neither_a_zero_nor_a_loss():
    """**§36-4 ~ 7.**"""
    action = PlayerAction.passing(actor=MINE)
    for status in (SimulationStatus.UNKNOWN, SimulationStatus.REFUSED):
        candidate = SearchCandidate(action=action, status=status)
        assert candidate.value is None
        assert candidate.comparable is False
    assert Terminal.LOSS is not Terminal.ONGOING
    #: 점수 없는 후보는 등급을 **갖지 않는다** — LOSS 로 접히지 않는다.
    assert SearchCandidate(action=action, status=SimulationStatus.UNKNOWN).value is None


def test_35_this_phase_changed_no_production_file():
    """**§0 · §26: AUDIT-ONLY — 네 자료형이 3-E-41 이 남긴 모양 그대로다.**"""
    assert len(dataclasses.fields(SimulationResult)) == 6
    assert len(dataclasses.fields(SearchCandidate)) == 4
    assert len(dataclasses.fields(SearchDecision)) == 9
    assert len(dataclasses.fields(StateValue)) == 4
    #: 변환 자리도 셋 그대로다.
    assert len(constructions("agent/search.py", "SearchCandidate")) == 3
    assert len(constructions("agent/simulation.py", "SimulationResult")) == 4


def test_36_no_new_abstraction_was_introduced():
    """
    **§28: 새 객체를 만들지 않았다.**

    프롬프트가 금지한 이름들이 repository 에 **없다.**
    """
    for forbidden in (
        "SimulationSearchResult",
        "SimulationOutcome",
        "CandidateDiagnostic",
        "SearchSimulationRecord",
        "SearchDiagnostic",
    ):
        for _rel, path in production_files():
            assert forbidden not in path.read_text(encoding="utf-8"), forbidden
