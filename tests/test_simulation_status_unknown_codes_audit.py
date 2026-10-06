r"""
Phase 3-E-39 — ``SimulationStatus`` / ``_UNKNOWN_CODES`` semantic audit.

**AUDIT-ONLY.** production 을 한 줄도 고치지 않는다. 이 파일은 "이래야 한다" 를
적지 않고 **지금 그렇다** 를 적는다. 그래서 테스트 이름이 대부분 현재 사실의
서술형이다 — 사실이 바뀌면 깨지고, 그때 바꾼 사람이 왜 바꿨는지 적게 된다.

재는 것
-------
1. ``SimulationStatus`` 다섯 상태와 그 뜻
2. ``UNKNOWN`` / ``REFUSED`` 가 **어디서** 만들어지는가 (단 한 자리다)
3. ``_UNKNOWN_CODES`` 다섯 멤버와, ``UNKNOWN`` validity 로 **실제 생산되는**
   일곱 코드의 차이
4. 두 상태를 consumer 가 가르는가 (``search`` 의 분기 · ``ordering_key``)
5. 정보가 어디서 보존되고 어디서 사라지는가
   (``SimulationResult.code`` 는 보존 · ``SearchCandidate`` 에는 칸이 없다)
6. 판 · 난수 · 가려진 정보가 탐색 때문에 움직이지 않는가

이 Phase 가 **하지 않는** 말
---------------------------
- "``UNKNOWN`` 과 ``REFUSED`` 는 반드시 달라야 한다" — 아직 결론이 아니다.
- "``_UNKNOWN_CODES`` 를 늘려야 한다" — 측정만 하고 고치지 않는다.
"""

import ast
import dataclasses
import pathlib
import re

import pytest

from agent.search import SearchCandidate, SearchPolicy
from agent.simulation import (
    SimulationResult,
    SimulationStatus,
    Simulator,
    _UNKNOWN_CODES,
)
from engine.action import PlayerAction
from engine.activation import ActivationStatus
from engine.condition import Always, ConditionResult, IsMonster, UnimplementedRule
from engine.duel import Duel, WithheldAction
from engine.effect import EffectProvenance
from engine.effect.resolution import ResolutionStatus
from engine.ids import InstanceId
from engine.validation import ActionValidity, ValidationCode

from tests.conftest import requires_official_db
from tests.test_validation_code_consistency import (
    activate,
    new_state,
    resolve,
    synthetic,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MINE = 0

#: ``_UNKNOWN_CODES`` 의 현재 전체 멤버 — 2026-10-01 ``40ea6c8`` 이후 **한 번도
#: 바뀌지 않았다** (``git log -L`` 로 확인).
#:
#: **Phase 3-E-40 이 일곱으로 맞췄다.** 3-E-39 가 "다섯이고 둘이 빠졌다" 를
#: 측정했고, 3-E-40 이 policy 를 ``engine.validation.CODE_VALIDITY`` 로 옮겨
#: 사본을 없애면서 빠진 둘이 들어왔다. 아래 ``MEASURED_...`` 와 **같아졌다** —
#: 그것이 3-E-40 의 결과다.
UNKNOWN_CODE_NAMES = frozenset(
    {
        "RULE_NOT_IMPLEMENTED",
        "COST_NOT_IMPLEMENTED",
        "INFORMATION_UNAVAILABLE",
        "CARD_DEFINITION_UNAVAILABLE",
        "EFFECT_LIST_UNRELIABLE",
        "HIDDEN_CARD",
        "PRIORITY_STATE_STALE",
    }
)

#: production 에서 ``ActionValidity.UNKNOWN`` 과 **함께** 생산되는 코드 전체.
#: AST 로 ``ValidationResult.unknown`` · ``ValidationResult(UNKNOWN, …)`` 를
#: 전수 조사해 얻었다 (Phase 3-E-39 §5).
MEASURED_UNKNOWN_VALIDITY_CODES = frozenset(
    {
        "RULE_NOT_IMPLEMENTED",
        "COST_NOT_IMPLEMENTED",
        "INFORMATION_UNAVAILABLE",
        "CARD_DEFINITION_UNAVAILABLE",
        "EFFECT_LIST_UNRELIABLE",
        "HIDDEN_CARD",
        "PRIORITY_STATE_STALE",
    }
)

#: 위 둘의 차이 — ``_UNKNOWN_CODES`` 에 빠져 있던 것.
#:
#: 3-E-39 에서는 ``{"HIDDEN_CARD", "PRIORITY_STATE_STALE"}`` 였다. 그 Phase 는
#: AUDIT-ONLY 라서 고치지 않고 숫자만 고정해 두었고, **3-E-40 이 그 틈을
#: 닫았다.** 지금은 비어 있어야 한다 — 다시 벌어지면 ``test_10`` 이 깨진다.
UNKNOWN_GAP = frozenset()

PROD_PREFIXES = ("engine/", "agent/", "core/", "analysis/", "sources/")


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def member_note(path: str, member: str) -> str:
    """
    enum 멤버 **바로 아래**에 적힌 설명 문구.

    ``Enum`` 멤버의 ``__doc__`` 은 **클래스의 docstring** 이다 — 멤버 밑의
    ``\"\"\"...\"\"\"`` 는 런타임에 남지 않는다 (Sphinx 가 소스에서 읽는다).
    이 파일을 처음 쓸 때 ``SimulationStatus.UNKNOWN.__doc__`` 을 그 문구로
    착각해 틀렸고, 소스에서 읽는 것으로 고쳤다.
    """
    source = source_of(path)
    match = re.search(
        rf'^    {member} = "[^"]*"\n(?:    """(?P<block>.*?)"""|    """(?P<line>[^"\n]*)""")',
        source,
        re.M | re.S,
    )
    if match is None:
        return ""
    return (match.group("block") or match.group("line") or "").strip()


def production_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel.startswith(PROD_PREFIXES):
            yield rel, path


def forbidden_definition():
    """``TEXT_DERIVED`` 출처 — ADR-004 가 실행을 금지한다 (Phase 3-E-38 M2)."""
    return synthetic(
        activation=None,
        provenance=EffectProvenance.text_derived("공식 텍스트에서 유추했다"),
    )


def small_duel(repository, seed: int = 11):
    deck = (
        [11091375] * 3
        + [5053103] * 3
        + [1184620] * 3
        + [32864] * 3
        + [3557275] * 3
        + [55144522] * 5
    )
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
    while duel.advance() is not None:
        pass
    return duel


# ======================================================================
# 1 ~ 3 — SimulationStatus 전체
# ======================================================================


def test_01_the_five_simulation_statuses_and_what_each_promises():
    """
    **§22-1: 상태는 다섯이고 미래를 주는 것은 하나뿐이다.**

    ``gives_a_future`` 가 이 enum 의 **유일한** 파생 성질이다. 이름이
    ``is_usable`` 인 것은 없다 — §25 가 그것을 따로 고정한다.
    """
    expected = {
        "SUPPORTED": ("supported", True),
        "NOT_A_CANDIDATE": ("not_a_candidate", False),
        "UNKNOWN": ("unknown", False),
        "REFUSED": ("refused", False),
        "ERROR": ("error", False),
    }
    assert {s.name for s in SimulationStatus} == set(expected)
    for name, (value, future) in expected.items():
        status = SimulationStatus[name]
        assert status.value == value
        assert status.gives_a_future is future, name


def test_02_unknown_means_the_engine_cannot_tell_not_that_it_is_bad():
    """**§22-2: ``UNKNOWN`` 은 "모른다" 이고 "나쁘다" 가 아니다.**"""
    note = member_note("agent/simulation.py", "UNKNOWN")
    assert "규칙이 아직 없다" in note
    assert "모른다는 것이지 나쁘다는 것이 아니다" in note
    #: 미래를 주지 않는다 — 없는 미래를 꾸며 내지 않는다.
    assert SimulationStatus.UNKNOWN.gives_a_future is False


def test_03_refused_means_the_engine_judged_and_said_no():
    """**§22-3: ``REFUSED`` 는 "판단했고 거절했다" 다.**"""
    note = member_note("agent/simulation.py", "REFUSED")
    assert "규칙에 따라 거절했다" in note
    assert SimulationStatus.REFUSED.gives_a_future is False
    #: 둘은 **다른 멤버**다. 같은 뜻이라서 합쳐져 있는 것이 아니다.
    assert SimulationStatus.REFUSED is not SimulationStatus.UNKNOWN


# ======================================================================
# 4 ~ 5 — 생성 경로
# ======================================================================


def test_04_unknown_and_refused_are_decided_at_exactly_one_place():
    """
    **§22-4 · §22-5: 두 상태를 가르는 자리는 production 에 단 하나다.**

    ``agent/simulation.py`` 의 삼항 하나이고, 입력은 ``DuelStep.code`` 다 —
    즉 **``Duel.apply`` 가 거절한 걸음**에서만 갈린다.
    """
    sites = {"UNKNOWN": [], "REFUSED": []}
    for rel, path in production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr in ("UNKNOWN", "REFUSED")
                and isinstance(node.value, ast.Name)
                and node.value.id == "SimulationStatus"
            ):
                sites[node.attr].append(f"{rel}:{node.lineno}")
    assert len(sites["UNKNOWN"]) == 1, sites["UNKNOWN"]
    assert len(sites["REFUSED"]) == 1, sites["REFUSED"]
    assert sites["UNKNOWN"][0].startswith("agent/simulation.py:")
    assert sites["REFUSED"][0].startswith("agent/simulation.py:")

    #: 그 자리가 **같은 삼항**이다 — 한 줄 차이로 붙어 있다.
    unknown_line = int(sites["UNKNOWN"][0].split(":")[1])
    refused_line = int(sites["REFUSED"][0].split(":")[1])
    assert abs(unknown_line - refused_line) <= 3

    #: 그리고 그 삼항의 조건이 ``step.code in _UNKNOWN_CODES`` 다.
    source = source_of("agent/simulation.py")
    assert "step.code in _UNKNOWN_CODES" in source


def test_05_the_classifier_only_runs_on_a_rejected_duel_step():
    """
    **분류기의 입력 영역이 좁다** — ``accepted`` 가 참인 걸음은 그 앞에서
    ``SUPPORTED`` 로 끝나고, 후보 목록에 없는 수는 ``NOT_A_CANDIDATE`` 로
    **그보다도 먼저** 끝난다.
    """
    tree = ast.parse(source_of("agent/simulation.py"))
    simulate = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "simulate"
    )
    body = ast.unparse(simulate)
    #: 세 관문의 순서 — 후보 여부 → 예외 → 수락 → 그다음이 분류기다.
    assert body.index("NOT_A_CANDIDATE") < body.index("SimulationStatus.ERROR")
    assert body.index("SimulationStatus.ERROR") < body.index("SUPPORTED")
    assert body.index("SUPPORTED") < body.index("_UNKNOWN_CODES")


# ======================================================================
# 6 ~ 10 — _UNKNOWN_CODES
# ======================================================================


def test_06_the_unknown_code_set_has_exactly_these_seven_members():
    """
    **§22-6: 집합 전체를 원소 단위로 고정한다.**

    .. note::
       **다섯 → 일곱** (Phase 3-E-40). 이 테스트는 틀린 가정을 갖고 있지
       않았다 — 3-E-39 당시의 사실을 정확히 세고 **고치면 깨지도록** 일부러
       고정했다. 그 설계가 의도대로 작동해서 3-E-40 이 무엇을 바꿨는지 여기서
       먼저 드러났다.
    """
    assert {c.name for c in _UNKNOWN_CODES} == set(UNKNOWN_CODE_NAMES)
    assert len(UNKNOWN_CODE_NAMES) == 7


def test_07_seven_of_forty_eight_codes_are_in_the_set():
    """
    **§22-7: 48개 중 7개다.**

    3-E-39 는 이 자리에 "손으로 고른 집합" 이라고 적었다. 3-E-40 이후로는
    **엔진의 policy 에서 파생된 집합**이다 — 그 사실은 ``test_17`` 이 센다.
    """
    assert len(_UNKNOWN_CODES) == 7
    assert len(ValidationCode) == 48
    #: 집합의 정의가 ``frozenset`` 이다 — 런타임에 늘어날 수 없다.
    assert isinstance(_UNKNOWN_CODES, frozenset)


def test_08_every_member_is_a_validation_code():
    """**§22-8: 문자열이 섞여 있지 않다.**"""
    for member in _UNKNOWN_CODES:
        assert isinstance(member, ValidationCode)
        assert ValidationCode[member.name] is member


def test_09_every_member_has_at_least_one_production_construction_site():
    """
    **§22-9: 다섯 멤버가 모두 production 에서 실제로 만들어진다.**

    "enum 에 있다" 와 "production 이 만든다" 는 다른 사실이므로 따로 센다.
    """
    counts = dict.fromkeys(UNKNOWN_CODE_NAMES, 0)
    for _rel, path in production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in counts:
                counts[node.attr] += 1
    for name, n in counts.items():
        assert n >= 1, f"{name} 의 production 등장이 0 이다"


def test_10_the_gap_that_this_audit_found_has_since_been_closed():
    """
    **§22-10 · §8: 집합과 생산 경로가 이제 정확히 같다.**

    3-E-39 가 측정했을 때는 ``ValidationResult.unknown(...)`` 으로 생산되는
    코드가 **일곱**이고 ``_UNKNOWN_CODES`` 는 **다섯**이었다. 빠진 둘은
    ``HIDDEN_CARD`` 와 ``PRIORITY_STATE_STALE`` 이었다.

    .. note::
       **3-E-40 이 그 틈을 닫았다.** 집합을 손으로 늘린 것이 아니라,
       ``engine.validation.CODE_VALIDITY`` 가 48개 전부를 분류하고
       ``agent`` 가 거기서 파생하게 만든 결과다. 그래서 이 테스트는 이제
       "틈이 없다" 를 지킨다 — 누군가 어떤 코드를 ``unknown`` 으로 생산하기
       시작하고 policy 에 적지 않으면 여기서 깨진다.
    """
    names = {c.name for c in _UNKNOWN_CODES}
    assert MEASURED_UNKNOWN_VALIDITY_CODES - names == UNKNOWN_GAP == frozenset()
    #: 양쪽이 **같다.**
    assert names == MEASURED_UNKNOWN_VALIDITY_CODES
    #: 반대 방향 — ``UNKNOWN`` 이 아닌데 집합에 들어가 있는 것도 없다.
    assert names - MEASURED_UNKNOWN_VALIDITY_CODES == frozenset()

    #: 빠진 둘이 정말 ``UNKNOWN`` 쪽인지 enum 자신의 말로 확인한다.
    hidden = member_note("engine/validation.py", "HIDDEN_CARD")
    assert "가려진 것일 수 있다" in hidden
    stale = member_note("engine/validation.py", "PRIORITY_STATE_STALE")
    assert "``INVALID`` 가 아니라 ``UNKNOWN`` 에 쓴다" in stale


def test_11_the_enum_section_is_now_contained_in_the_set():
    """
    **enum 이 선언한 묶음과 집합이 더 이상 어긋나지 않는다.**

    3-E-39 당시: 묶음 다섯과 집합 다섯이 **크기는 같고 내용이 달랐다** —
    묶음에만 ``HIDDEN_CARD`` 가, 집합에만 ``COST_NOT_IMPLEMENTED`` 가 있었다.

    3-E-40 이후: 묶음 다섯이 **집합에 전부 들어 있다.** 집합이 둘 더 큰 것은
    묶음 밖에서 온 코드가 둘 있기 때문이고 (``COST_NOT_IMPLEMENTED`` 는 비용
    묶음, ``PRIORITY_STATE_STALE`` 은 발동 타이밍 묶음), 둘 다 설명과 생산
    경로가 모름이라고 말한다. **묶음은 이제 policy 의 부분집합**이다.
    """
    source = source_of("engine/validation.py")
    start = source.index("# --- 모른다 (UNKNOWN) ---")
    end = source.index("# --- 비용 · 선택")
    section = {
        name for name in ValidationCode.__members__ if f"    {name} = " in source[start:end]
    }
    assert section == {
        "HIDDEN_CARD",
        "INFORMATION_UNAVAILABLE",
        "CARD_DEFINITION_UNAVAILABLE",
        "EFFECT_LIST_UNRELIABLE",
        "RULE_NOT_IMPLEMENTED",
    }
    names = {c.name for c in _UNKNOWN_CODES}
    assert len(section) == 5
    assert len(names) == 7
    #: 묶음이 집합에 **온전히** 들어 있다 — 3-E-39 에서는 그렇지 않았다.
    assert section <= names
    assert section - names == frozenset()
    #: 집합에만 있는 둘은 다른 묶음에서 온다.
    assert names - section == {"COST_NOT_IMPLEMENTED", "PRIORITY_STATE_STALE"}


# ======================================================================
# 11 ~ 12 — consumer 가 두 상태를 가르는가
# ======================================================================


def test_12_the_search_consumer_puts_both_statuses_in_the_same_branch():
    """
    **§22-11 · §10: 탐색은 ``SUPPORTED`` 인가만 본다.**

    ``UNKNOWN`` 과 ``REFUSED`` 를 가르는 비교가 ``agent/`` 에 **없다.**
    """
    compared = []
    for rel, path in production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            text = ast.unparse(node)
            if "SimulationStatus" not in text:
                continue
            compared.append((rel, node.lineno, text))
    #: 비교하는 멤버는 ``SUPPORTED`` 뿐이다.
    for rel, lineno, text in compared:
        assert "SUPPORTED" in text, f"{rel}:{lineno} {text}"
        assert "UNKNOWN" not in text, f"{rel}:{lineno} {text}"
        assert "REFUSED" not in text, f"{rel}:{lineno} {text}"
    assert compared, "SimulationStatus 를 비교하는 자리가 하나도 없다"


def test_13_every_status_including_none_gets_the_same_ordering_key():
    """
    **§22-12 · §11: 순위 키가 상태를 보지 않는다.**

    키는 **점수가 있는가** 로만 갈린다. 점수가 없으면 다섯 상태와 ``None``
    까지 **전부 같은 키**이고, 동점은 ``canonical_state`` 로 깬다.

    .. note::
       키가 같다는 것이 "두 상태의 뜻이 같다" 는 뜻은 아니다 (§11 이 그
       추론을 금지한다). 여기서 재는 것은 **순위에 영향이 없다** 는 사실
       하나다.
    """
    action = PlayerAction.passing(actor=MINE)
    keys = {
        status: SearchCandidate(action=action, status=status).ordering_key()
        for status in list(SimulationStatus) + [None]
    }
    assert len(set(keys.values())) == 1
    only = next(iter(keys.values()))
    assert only[:3] == (1, 0, 0)
    assert only[3] == action.canonical_state()

    #: 점수가 있으면 **첫 칸이 0 으로 바뀐다** — 그것이 유일한 갈림이다.
    from agent.evaluation import StateValue, Terminal

    scored = SearchCandidate(
        action=action,
        status=SimulationStatus.SUPPORTED,
        value=StateValue(terminal=Terminal.ONGOING, heuristic=7),
    )
    assert scored.ordering_key()[0] == 0
    assert only[0] == 1


# ======================================================================
# 13 ~ 15 — 정보 보존 / 손실
# ======================================================================


def test_14_the_simulation_result_preserves_the_original_validation_code():
    """**§22-13: ``SimulationResult.code`` 가 원래 코드를 들고 있다.**"""
    fields = {f.name for f in dataclasses.fields(SimulationResult)}
    assert "code" in fields
    result = SimulationResult(
        action=PlayerAction.passing(actor=MINE),
        status=SimulationStatus.REFUSED,
        viewer=MINE,
        reason="거절",
        code=ValidationCode.CANDIDATE_NOT_ELIGIBLE,
    )
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert result.status is SimulationStatus.REFUSED
    #: 상태가 코드를 지우지 않는다 — 둘이 **따로** 산다.
    assert result.code not in _UNKNOWN_CODES


def test_15_the_reason_string_survives_too():
    """**§22-14: 사람이 읽는 이유도 그대로 넘어온다.**"""
    fields = {f.name for f in dataclasses.fields(SimulationResult)}
    assert "reason" in fields
    source = source_of("agent/simulation.py")
    #: 거절 경로가 ``step.reason`` 을 **그대로** 전한다.
    assert "reason=step.reason" in source


def test_16_the_simulation_result_has_no_score_notes_or_state_hash():
    """
    **§22-15 · §13: 프롬프트가 든 칸 중 실제로 있는 것과 없는 것.**

    ``score`` · ``value`` · ``notes`` · ``ordering_key`` · ``state_hash`` 는
    ``SimulationResult`` 에 **없다.** 점수와 순위는 ``SearchCandidate`` 의
    일이고 ``state_hash`` 는 ``SearchDecision`` 의 일이다. 계층을 섞지 않는다.
    """
    fields = {f.name for f in dataclasses.fields(SimulationResult)}
    assert fields == {"action", "status", "viewer", "reason", "code", "future"}
    for absent in ("score", "value", "notes", "ordering_key", "state_hash"):
        assert absent not in fields, absent


def test_17_the_code_is_dropped_when_a_candidate_is_built():
    """
    **정보가 사라지는 자리를 지목한다** (§14).

    ``SearchCandidate`` 에는 ``code`` 칸이 **없다.** 그래서 오래 사는 흔적
    (``SearchDecision``)에는 ``status`` 와 ``reason`` 문자열만 남고 기계가
    읽을 코드는 남지 않는다.

    .. note::
       이것을 "손실" 로 적되 **"버그" 로 적지 않는다.** ``code`` 를 읽는
       consumer 가 ``agent/`` 에 하나도 없으므로(``test_18``) 지금 잃는 것은
       **쓰이지 않는 정보**다. 쓰려면 칸을 만들어야 한다는 사실만 기록한다.
    """
    fields = {f.name for f in dataclasses.fields(SearchCandidate)}
    assert fields == {"action", "status", "value", "reason"}
    assert "code" not in fields

    source = source_of("agent/search.py")
    #: 후보를 만드는 두 자리 모두 ``code=`` 를 넘기지 않는다.
    assert "code=result.code" not in source
    assert "status=result.status" in source
    assert "reason=result.reason" in source


def test_18_nobody_in_the_agent_layer_reads_the_code():
    """
    **``ValidationCode`` 는 ``agent/`` 에서 ``simulation.py`` 밖으로 나가지
    않는다** — 그리고 그 안에서도 **읽는** 자리는 분류기 하나뿐이다.
    """
    users = {}
    for rel, path in production_files():
        if not rel.startswith("agent/"):
            continue
        text = path.read_text(encoding="utf-8")
        if "ValidationCode" in text:
            users[rel] = text.count("ValidationCode")
    assert set(users) == {"agent/simulation.py"}

    #: ``.code`` 를 **읽는** 자리 — 분류기의 멤버십 검사 하나다.
    reads = []
    for rel, path in production_files():
        if not rel.startswith("agent/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and ".code" in ast.unparse(node):
                reads.append(f"{rel}:{node.lineno}")
    assert len(reads) == 1, reads
    assert reads[0].startswith("agent/simulation.py:")


# ======================================================================
# 16 ~ 18 — 판 · 난수 · 가려진 정보
# ======================================================================


@requires_official_db
def test_19_a_full_search_decision_never_moves_the_board(repository):
    """**§22-16: ``state_hash`` 불변.**"""
    duel = small_duel(repository)
    simulator = Simulator(duel)
    before = duel.state.state_hash()
    seat = duel.to_act
    SearchPolicy().attach(simulator).decide(duel.view(seat), duel.legal_actions(seat))
    assert duel.state.state_hash() == before


@requires_official_db
def test_20_a_full_search_decision_never_consumes_randomness(repository):
    """**§22-17: RNG 불변.** 사본이 꺼낸 난수가 진짜 판을 밀지 않는다."""
    duel = small_duel(repository)
    simulator = Simulator(duel)
    before = duel.state.randomness.draws
    seat = duel.to_act
    SearchPolicy().attach(simulator).decide(duel.view(seat), duel.legal_actions(seat))
    assert duel.state.randomness.draws == before
    assert simulator.random_draws() == before


@requires_official_db
def test_21_the_simulated_future_still_hides_the_opponents_hand(repository):
    """
    **§22-18: 시뮬레이션이 관측 경계를 넓히지 않는다.**

    상대의 패와 양쪽 덱은 ``concealed`` 이고 ``cards`` 가 비어 있다 — 장수만
    공개다.
    """
    duel = small_duel(repository)
    simulator = Simulator(duel)
    seat = duel.to_act
    result = simulator.simulate(duel.legal_actions(seat).allowed[0], viewer=seat)
    assert result.status is SimulationStatus.SUPPORTED
    future = result.future

    mine = future.player(seat).hand
    theirs = future.player(1 - seat).hand
    assert mine.concealed is False
    assert all(card.is_identified for card in mine.occupied())
    assert theirs.concealed is True
    assert theirs.cards == ()
    #: 장수는 정확하다 — "안 보인다" 가 "없다" 가 되지 않는다.
    assert theirs.size == len(duel.state.player(1 - seat).hand)
    for owner in (seat, 1 - seat):
        assert future.player(owner).deck.concealed is True


# ======================================================================
# 19 ~ 21 — M1 / M2 / 진짜 미구현
# ======================================================================


def test_22_the_m1_path_still_produces_candidate_not_eligible():
    """
    **§22-19: Phase 3-E-38 의 M1 이 그대로다.**

    그리고 그 코드는 ``_UNKNOWN_CODES`` 에 **없으므로**, 만약 그 걸음이
    ``DuelStep`` 까지 내려온다면 ``REFUSED`` 로 분류된다. 그것이 **현재의
    설계**이고, 이 Phase 는 그것이 옳은지 고치지 않는다.
    """
    false = synthetic(activation=Always(ConditionResult.FALSE))
    activated = activate(new_state(), false)
    resolved = resolve(new_state(), false)

    assert activated.status is ActivationStatus.CONDITION_FALSE
    assert activated.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert resolved.status is ResolutionStatus.CONDITION_FALSE
    assert resolved.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert activated.code not in _UNKNOWN_CODES  # → REFUSED 쪽


def test_23_the_m2_path_still_produces_execution_forbidden():
    """**§22-20: M2 도 그대로다.** 역시 ``REFUSED`` 쪽으로 분류된다."""
    forbidden = forbidden_definition()
    activated = activate(new_state(), forbidden)
    resolved = resolve(new_state(), forbidden)

    assert activated.status is ActivationStatus.FORBIDDEN
    assert activated.code is ValidationCode.EXECUTION_FORBIDDEN
    assert resolved.status is ResolutionStatus.FORBIDDEN
    assert resolved.code is ValidationCode.EXECUTION_FORBIDDEN
    assert activated.code not in _UNKNOWN_CODES  # → REFUSED 쪽


def test_24_a_genuine_missing_rule_still_lands_on_unknown():
    """
    **§22-21: 진짜 미구현은 ``UNKNOWN`` 쪽이다.**

    그리고 가려진 정보는 ``INFORMATION_UNAVAILABLE`` 로 **따로** 간다 —
    그쪽도 집합에 있으므로 ``UNKNOWN`` 이다.
    """
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))

    assert rule.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert rule.code in _UNKNOWN_CODES
    assert info.code in _UNKNOWN_CODES
    assert rule.status is info.status is ActivationStatus.CONDITION_UNKNOWN


# ======================================================================
# 22 — 새 enum 없음 / production diff 0
# ======================================================================


def test_25_no_new_enum_member_was_added_anywhere():
    """**§22-22 · §20: 이번 Phase 는 enum 을 하나도 건드리지 않았다.**"""
    assert len(ValidationCode) == 48
    assert len(SimulationStatus) == 5
    assert len(ActionValidity) == 3
    assert len(ConditionResult) == 3
    assert len(ResolutionStatus) == 14


def test_26_is_usable_does_not_exist_anywhere_in_the_repository():
    """
    **프롬프트와 Phase 3-E-38 보고서의 전제를 바로잡는다.**

    §10 은 "``search.py:311`` 의 ``is_usable()``" 을 읽으라고 했고 3-E-38
    보고서도 ``agent/simulation.py:85`` 를 ``is_usable`` 이라고 적었다.
    **그런 이름은 repository 에 없다.** 실제로 있는 것은 둘이다.

    * ``SimulationStatus.gives_a_future`` — property, production 사용처는
      ``SimulationResult.__post_init__`` 의 불변식 검사 두 줄
    * ``agent/search.py`` 의 ``result.status is not SimulationStatus.SUPPORTED``
      — 후보를 점수 없는 쪽으로 보내는 분기

    이름을 잘못 적은 것이 결론을 바꾸지는 않았다 (두 자리 모두 ``SUPPORTED``
    만 보므로 ``UNKNOWN``/``REFUSED`` 를 가르지 않는다). 그래도 **측정한
    이름으로** 고쳐 적는다.
    """
    for _rel, path in production_files():
        assert "is_usable" not in path.read_text(encoding="utf-8")

    assert hasattr(SimulationStatus, "gives_a_future")
    users = [
        f"{rel}:{node.lineno}"
        for rel, path in production_files()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and node.attr == "gives_a_future"
    ]
    assert len(users) == 2, users
    assert all(u.startswith("agent/simulation.py:") for u in users)


# ======================================================================
# 도달 가능성 — dormant 인가
# ======================================================================


@requires_official_db
def test_27_a_real_duel_never_rejects_an_action_it_offered(repository):
    """
    **분류기가 dormant 인 구조적 까닭.**

    ``legal_actions`` 는 ``VALID`` 만 후보에 넣고, ``apply`` 는 **같은 함수로
    같은 판**을 다시 본다 (STRUCTURAL-134). 그래서 후보로 내놓은 수가
    거절되는 자리가 없고, ``Simulator`` 는 후보만 적용한다.

    실제 듀얼 한 판의 **모든 걸음**이 ``accepted`` 이고 코드가 ``OK`` 인지
    확인한다. (전체 코퍼스 32판 · 11,609 걸음 측정은 보고서 §13 에 있다.)
    """
    duel = small_duel(repository, seed=5)
    simulator = Simulator(duel)
    seen_steps, seen_sims = set(), set()
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
            outcome = simulator.simulate(action, viewer=seat)
            seen_sims.add(outcome.status)
        step = duel.apply(legal.allowed[0])
        seen_steps.add((step.accepted, step.code))
    assert seen_steps == {(True, ValidationCode.OK)}, seen_steps
    assert seen_sims == {SimulationStatus.SUPPORTED}, seen_sims


@requires_official_db
def test_28_the_codes_that_block_a_candidate_never_reach_the_simulator(repository):
    """
    **거절 코드는 ``withheld`` 로 간다 — 그런데 ``withheld`` 는 코드를 들고
    있지 않다.**

    후보가 되지 못한 이유는 ``WithheldAction`` 에 남는데 그 자료형에
    ``code`` 칸이 **없다** (``kind`` · ``reason`` · ``missing`` 셋뿐이다).
    그래서 M1/M2 가 고친 코드도, ``HIDDEN_CARD`` 도 이 길로는 기계가 읽을
    형태로 나오지 않는다.
    """
    assert {f.name for f in dataclasses.fields(WithheldAction)} == {
        "kind",
        "reason",
        "missing",
    }
    duel = small_duel(repository)
    withheld = duel.legal_actions(duel.to_act).withheld
    assert withheld, "보류가 하나도 없는 판이면 이 측정이 무의미하다"
    for entry in withheld:
        assert not hasattr(entry, "code")


# ======================================================================
# §32 — Safety invariants
# ======================================================================


def test_29_unknown_is_neither_false_nor_a_loss_nor_a_zero_score():
    """**§32-1 · 2 · 3 · 4 · 6 · 7 · 8.**"""
    #: ``UNKNOWN`` validity 는 허가가 아니다 — 그리고 거부도 아니다.
    from engine.validation import ValidationResult

    unknown = ValidationResult.unknown(
        ValidationCode.RULE_NOT_IMPLEMENTED, "모른다", missing_rule="r"
    )
    assert unknown.permits_execution is False
    assert unknown.is_structural_failure is False
    with pytest.raises(TypeError):
        bool(unknown)

    #: 점수가 **없다** — 0 이 아니다.
    action = PlayerAction.passing(actor=MINE)
    for status in (SimulationStatus.UNKNOWN, SimulationStatus.REFUSED):
        candidate = SearchCandidate(action=action, status=status)
        assert candidate.value is None
        assert candidate.comparable is False
        assert candidate.value != 0

    #: 그리고 어느 쪽도 승패를 만들지 않는다 — 승패는 ``DuelResult`` 의 일이다.
    assert not hasattr(SimulationStatus.UNKNOWN, "winner")
    assert not hasattr(SimulationResult, "winner")


def test_30_the_distinctions_from_phase_3e24_to_3e38_still_hold():
    """**§32-5 · 6: 앞선 Phase 들이 세운 구분이 그대로다.**"""
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert ValidationCode.EXECUTION_FORBIDDEN is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert ValidationCode.INFORMATION_UNAVAILABLE is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert ValidationCode.HIDDEN_CARD is not ValidationCode.INFORMATION_UNAVAILABLE
    assert ActionValidity.UNKNOWN is not ActionValidity.INVALID


def test_31_hidden_information_is_not_a_refusal_on_either_axis_now():
    """
    **§32-7 · 8: 가려진 정보는 거절이 아니다 — 이제 두 축이 같은 말을 한다.**

    3-E-39 가 측정했을 때 두 축이 어긋나 있었다. validity 축에서는
    ``HIDDEN_CARD`` 가 ``UNKNOWN`` 인데 ``_UNKNOWN_CODES`` 축에서는 집합에
    없어서, 그 코드가 ``DuelStep`` 까지 내려온다면 "규칙에 따라 거절했다" 로
    읽힐 상태였다 (도달 경로가 없어 해는 없었다).

    .. note::
       **3-E-40 이 그 어긋남을 없앴다.** 이제 두 축이 모두 모름이라고 한다.
       이 테스트는 "어긋남을 기록하는 것" 에서 "어긋나지 않음을 지키는 것" 으로
       역할이 바뀌었다 — 어느 쪽이 다시 어긋나면 여기서 깨진다.
    """
    from engine.validation import CODE_VALIDITY, ValidationResult

    #: validity 축 — 가려진 카드는 ``UNKNOWN`` 이고 ``INVALID`` 가 아니다.
    hidden = ValidationResult.unknown(ValidationCode.HIDDEN_CARD, "가려졌다")
    assert hidden.validity is ActionValidity.UNKNOWN
    assert hidden.is_structural_failure is False

    #: policy 축 — 같은 말을 한다.
    assert CODE_VALIDITY[ValidationCode.HIDDEN_CARD] is ActionValidity.UNKNOWN

    #: ``_UNKNOWN_CODES`` 축 — 이제 집합에 **있다.**
    assert ValidationCode.HIDDEN_CARD in _UNKNOWN_CODES

    #: 그래서 그 코드가 ``DuelStep`` 까지 내려온다면 ``UNKNOWN`` 이다.
    #: **그런 경로는 여전히 없다** (``test_27`` · ``test_28``) — 분류기의
    #: 정의를 그대로 적용한 결과이고 실제 관측이 아니다.
    would_be = (
        SimulationStatus.UNKNOWN
        if ValidationCode.HIDDEN_CARD in _UNKNOWN_CODES
        else SimulationStatus.REFUSED
    )
    assert would_be is SimulationStatus.UNKNOWN


def test_32_the_agent_layer_no_longer_writes_the_policy_down():
    """
    **이 Phase(3-E-39)가 재던 자리가 3-E-40 에서 어떻게 바뀌었는가.**

    3-E-39 는 AUDIT-ONLY 였고 이 테스트로 "production diff 0" 을 지켰다 —
    ``agent/simulation.py`` 에 코드 다섯 줄이 적혀 있는 모양 그대로였다.
    3-E-40 이 그 다섯 줄을 **엔진으로 옮겼다.** 그래서 여기서는 이제
    "에이전트가 policy 를 적지 않는다" 를 센다.
    """
    simulation = source_of("agent/simulation.py")
    search = source_of("agent/search.py")
    #: 코드 이름을 적은 줄이 **하나도 없다.**
    assert simulation.count("ValidationCode.") == 0
    for name in UNKNOWN_CODE_NAMES:
        assert f"ValidationCode.{name}," not in simulation
    #: 대신 엔진에서 파생한다.
    assert "unknown_codes()" in simulation
    #: 분류기가 한 자리 그대로다 (정의 + 사용).
    assert simulation.count("_UNKNOWN_CODES") == 2
    #: 탐색의 분기가 한 자리 그대로다.
    assert search.count("SimulationStatus.SUPPORTED") == 1
    #: 그리고 enum 에 새 멤버가 없다 — **구문으로** 센다. 문자열 할당을
    #: 세면 enum 밖의 상수까지 걸린다 (처음에 51 을 기대했는데 53 이었다).
    tree = ast.parse(source_of("engine/validation.py"))
    sizes = {
        node.name: sum(
            1
            for stmt in node.body
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant)
        )
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    assert sizes["ValidationCode"] == 48
    assert sizes["ActionValidity"] == 3


def test_33_the_forty_eight_codes_partition_without_a_remainder():
    """
    **§15 의 분류가 48 을 남김 없이 나눈다.**

    보고서의 표를 손으로 더하다 ``TRUE INVALID`` 를 37 로 적어 합이 49 가 된
    적이 있다. 분할을 코드로 적어 두면 그 실수가 여기서 걸린다.
    """
    unknown = MEASURED_UNKNOWN_VALIDITY_CODES
    context_dependent = {"CANDIDATE_NOT_FOUND", "CHAIN_DEFINITION_UNAVAILABLE"}
    named = {"OK"} | unknown | {"CANDIDATE_NOT_ELIGIBLE", "EXECUTION_FORBIDDEN"} | context_dependent
    all_names = set(ValidationCode.__members__)

    #: 이름을 붙인 범주들이 서로 겹치지 않는다.
    assert len(named) == 1 + len(unknown) + 2 + len(context_dependent) == 12
    #: 나머지가 전부 확정 거부 쪽이다.
    rest = all_names - named
    assert len(rest) == 36
    assert len(all_names) == 48 == len(named) + len(rest)
