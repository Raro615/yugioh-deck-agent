"""
Phase 3-E-36 — ``ValidationCode.RULE_NOT_IMPLEMENTED`` 정밀 의미 감사.

핵심 질문: **이 코드 하나가 서로 다른 의미를 담고 있는가.**

75 라는 숫자 자체를 문제로 보지 않는다. 파일에 있다는 것과 실제 게임에서
미구현으로 판정된다는 것을 구분하고, 각 자리의 **짝지은 상태**를 읽어서
의미를 정한다. 이름이나 파일명으로 분류하지 않는다.

측정으로 드러난 일곱 가지
-------------------------

1. **75 는 문자열 등장 수이고, 코드 등장은 69곳이다.** 나머지 6곳은 주석과
   docstring 이다 (`special_summon.py:77` · `trigger.py:978` ·
   `trigger_chain.py:553` · `:569` · `validation.py:129` · `:180`).

2. **69곳 중 생성이 아닌 것이 17곳이다** — enum 정의 1 · ``code`` 필드
   기본값 8 · 집합 멤버십 1 · 비교 1 · 닿지 않는 자리표시 1 · 올바르게
   가르는 ``IfExp`` 5.

3. **enum 자신이 금지선을 적어 두었다.**
   ``RULE_NOT_IMPLEMENTED`` 의 docstring 이 "``UNKNOWN`` 쪽의 코드다 —
   **확실한 거부(``INVALID``)에 붙이지 않는다**" 고 말한다.

4. **그 금지선을 어기는 자리가 결과 계층에 남아 있다.** 상태를 기계로 읽어
   가르면 **16곳**이 "모른다" 쪽이 아닌 상태와 짝지어 있다
   (``CONDITION_FALSE`` · ``FORBIDDEN`` · ``INVALID_ACTION`` ·
   ``CHAIN_REFUSED`` · ``INVALID_OPERATION`` · ``INVALID_CONTEXT`` ·
   ``EXECUTION_ERROR`` · ``REFUSED``), **16곳**은 올바르다.

5. **그중 넷은 정확한 코드가 이미 enum 에 있다.** 조건 거짓 ×2 →
   ``CANDIDATE_NOT_ELIGIBLE``, 출처 금지 ×2 → ``EXECUTION_FORBIDDEN``.
   **3-E-26 이 트리거 계층에서 고친 바로 그 두 가지**이고, 발동·해결
   계층에는 그대로 남아 있다.

6. **그런데 판정은 바뀌지 않는다.** ``.code`` 를 **판단 입력으로 읽는**
   production 자리는 넷뿐이고, 넷 다 이 오분류 때문에 다른 결론을 내지
   않는다. ``GateVerdict.forbids`` 는 트리거 계층만 보고,
   ``_undecided_code`` 는 ``UNKNOWN`` 관문만 보며,
   ``agent/simulation.py`` 는 ``UNKNOWN`` 과 ``REFUSED`` 를 **같은 순위**로
   줄 세운다.

7. **정보가 사라지지 않는다.** 정확한 사실은 **상태**가 들고 있다
   (``CONDITION_FALSE`` · ``FORBIDDEN`` · ``INVALID_CONTEXT``), 코드는 그
   옆에 붙은 거친 이름표다.

이 Phase 는 production 을 고치지 않았다. 감사다.
"""

import ast
import dataclasses
import pathlib

import pytest

from agent.search import SearchCandidate
from agent.simulation import SimulationResult, SimulationStatus, _UNKNOWN_CODES
from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionStatus, UNSUPPORTED_REASON
from engine.action_validation import ActionValidator
from engine.activation import ActivationStatus, _UNKNOWN_STATUSES
from engine.condition import Always, ConditionResult, IsMonster, UnimplementedRule
from engine.duel import Duel
from engine.effect import EffectProvenance
from engine.effect.resolution import ResolutionStatus, UnimplementedResolver
from engine.ids import InstanceId
from engine.trigger import (
    EligibilityGate,
    GateVerdict,
    TriggerCollector,
    TriggerRegistry,
    TriggerStatus,
)
from engine.validation import ActionValidity, ValidationCode, ValidationResult

from tests.conftest import requires_official_db

#: 발동 · 해결 계층을 **그대로** 부르는 기존 도구를 다시 쓴다.
from tests.test_validation_code_consistency import (
    activate,
    drawn_event,
    new_state,
    resolve,
    synthetic,
    watched_definition,
    watching,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MINE = 0


# ======================================================================
# 측정값 — 전부 저장소에서 센 수다. 바뀌면 그것이 신호다.
# ======================================================================

#: ``engine/`` + ``agent/`` 의 **문자열** 등장 수. 프롬프트가 말하는 75다.
STRING_OCCURRENCES = 75

#: 그중 주석 · docstring (코드가 아니다).
PROSE_OCCURRENCES = {
    ("engine/special_summon.py", 77),
    ("engine/trigger.py", 978),
    ("engine/trigger_chain.py", 553),
    ("engine/trigger_chain.py", 569),
    ("engine/validation.py", 129),
    ("engine/validation.py", 180),
}

#: 실제 코드 등장 = 75 - 6.
CODE_OCCURRENCES = 69

#: ``code: ValidationCode = ValidationCode.RULE_NOT_IMPLEMENTED`` 기본값 8곳.
FIELD_DEFAULT_OWNERS = {
    ("engine/action_execution.py", "ActionExecution"),
    ("engine/activation.py", "ActivationResult"),
    ("engine/chain.py", "ChainResolution"),
    ("engine/effect/resolution.py", "EffectResult"),
    ("engine/payment.py", "CostPaymentResult"),
    ("engine/response.py", "ResponseResult"),
    ("engine/trigger.py", "TriggerCandidate"),
    ("engine/trigger_chain.py", "TriggerChainEntry"),
}

#: 결과 계층에서 **"모른다" 쪽이 아닌 상태**와 짝지은 자리 (기계로 센다).
#: 줄 번호는 ``Call`` 의 첫 인자 줄이다.
CONTRACT_VIOLATIONS = {
    ("engine/action_execution.py", 316, "ActionStatus.EXECUTION_ERROR"),
    ("engine/activation.py", 554, "ActivationStatus.INVALID_ACTION"),
    ("engine/activation.py", 586, "ActivationStatus.CHAIN_REFUSED"),
    ("engine/activation.py", 667, "ActivationStatus.CONDITION_FALSE"),
    ("engine/effect/executor.py", 488, "ResolutionStatus.EXECUTION_ERROR"),
    ("engine/effect/executor.py", 630, "ResolutionStatus.INVALID_OPERATION"),
    ("engine/effect/executor.py", 643, "ResolutionStatus.INVALID_OPERATION"),
    ("engine/effect/executor.py", 766, "ResolutionStatus.INVALID_CONTEXT"),
    ("engine/effect/executor.py", 865, "ResolutionStatus.INVALID_CONTEXT"),
    ("engine/effect/executor.py", 920, "ResolutionStatus.FORBIDDEN"),
    ("engine/effect/executor.py", 979, "ResolutionStatus.CONDITION_FALSE"),
    ("engine/effect/executor.py", 1134, "ResolutionStatus.INVALID_CONTEXT"),
    ("engine/effect/executor.py", 1329, "ResolutionStatus.INVALID_CONTEXT"),
    ("engine/effect/resolution.py", 499, "ResolutionStatus.FORBIDDEN"),
    ("engine/payment.py", 372, "PaymentStatus.EXECUTION_ERROR"),
    ("engine/response.py", 476, "ResponseOutcome.REFUSED"),
}

#: 같은 주사에서 **올바른** 자리 (모른다 쪽 상태와 짝지었다).
CONFORMING_SITES = 17

#: 해결 계층의 "모른다" 쪽 상태 — `resolution.py` 의 docstring 을 읽어 모았다.
RESOLUTION_UNKNOWN_NAMES = {
    "UNKNOWN",
    "NOT_IMPLEMENTED",
    "CONDITION_UNKNOWN",
    "UNCHECKED_RULES",
    "UNSUPPORTED_OPERATION",
}

#: ``.code`` 를 **판단 입력**으로 읽는 production 자리 — 넷뿐이다.
CODE_READERS = {
    ("engine/trigger.py", "self.result.code is ValidationCode.EXECUTION_FORBIDDEN"),
    ("engine/trigger_chain.py", "verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED"),
    ("engine/trigger_chain.py", "verdict.code is not ValidationCode.OK"),
    ("agent/simulation.py", "step.code in _UNKNOWN_CODES"),
}


# ======================================================================
# 도구
# ======================================================================


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def _unparse(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - 방어
        return "<?>"


def production_files() -> list[pathlib.Path]:
    files = []
    for pkg in ("engine", "agent"):
        files.extend(sorted((PROJECT_ROOT / pkg).rglob("*.py")))
    return files


def mentions_code(node) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Attribute) and inner.attr == "RULE_NOT_IMPLEMENTED":
            return True
    return False


def prose_lines(path: pathlib.Path) -> set[int]:
    """
    주석과 docstring 이 차지하는 줄 번호. AST 가 **코드로 보지 않는** 줄이다.

    주석은 ``#`` 로, docstring 은 문자열 ``Expr`` 노드의 줄 범위로 찾는다.
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    found = {
        index + 1
        for index, line in enumerate(lines)
        if line.lstrip().startswith("#")
    }
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            end = node.end_lineno or node.lineno
            found.update(range(node.lineno, end + 1))
    return found


def code_sites() -> list[tuple[str, int, str]]:
    """
    ``RULE_NOT_IMPLEMENTED`` 가 **코드로** 등장하는 줄 전수.

    돌려주는 것은 ``(상대경로, 줄, 그 줄의 내용)``. 주석·docstring 은 뺀다.
    """
    sites = []
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        source = path.read_text(encoding="utf-8")
        if "RULE_NOT_IMPLEMENTED" not in source:
            continue
        prose = prose_lines(path)
        for index, line in enumerate(source.splitlines(), start=1):
            if "RULE_NOT_IMPLEMENTED" not in line:
                continue
            if index in prose:
                continue
            sites.append((rel, index, line.strip()))
    return sites


def status_paired_sites() -> tuple[list, list]:
    """
    결과 생성자의 **첫 인자(상태)** 와 ``RULE_NOT_IMPLEMENTED`` 를 짝지어,
    "모른다" 쪽인지 가른다.

    상태 enum 자신이 적어 둔 묶음을 쓴다 — 내가 새로 정하지 않는다
    (``engine.activation._UNKNOWN_STATUSES`` · ``RESOLUTION_UNKNOWN_NAMES``).
    """
    violations, conforming = [], []
    for rel in (
        "engine/activation.py",
        "engine/effect/executor.py",
        "engine/effect/resolution.py",
        "engine/response.py",
        "engine/action_execution.py",
        "engine/payment.py",
    ):
        tree = ast.parse(source_of(rel))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if not any(
                isinstance(a, ast.Attribute) and a.attr == "RULE_NOT_IMPLEMENTED"
                for a in node.args
            ):
                continue
            first = node.args[0]
            if not isinstance(first, ast.Attribute):
                continue
            owner = _unparse(first.value)
            name = first.attr
            if owner == "ActivationStatus":
                unknown_side = getattr(ActivationStatus, name) in _UNKNOWN_STATUSES
            elif owner == "ResolutionStatus":
                unknown_side = name in RESOLUTION_UNKNOWN_NAMES
            elif owner == "ActionStatus" and name == "UNSUPPORTED_ACTION":
                #: "할 줄 모른다" — docstring 이 그렇게 적는다. 적합하다.
                unknown_side = True
            else:
                unknown_side = False
            row = (rel, first.lineno, f"{owner}.{name}")
            (conforming if unknown_side else violations).append(row)
    return violations, conforming


# ======================================================================
# A. enum 정의
# ======================================================================


def test_01_the_enum_itself_forbids_attaching_this_code_to_a_refusal():
    """
    **A (§20): enum 정의.**

    이 Phase 의 기준선은 내 의견이 아니라 **enum 자신의 docstring** 이다.

        "**이 엔진이 아직 못 한다.** 판이 어떻든 달라지지 않고, 코드가
        생겨야 풀린다. ``UNKNOWN`` 쪽의 코드다 — 확실한
        거부(``INVALID``)에 붙이지 않는다."

    그 문장을 고정한다. 문장이 바뀌면 이 Phase 의 판정 근거가 바뀐다.
    """
    tree = ast.parse(source_of("engine/validation.py"))
    doc = None
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "ValidationCode"):
            continue
        body = node.body
        for index, stmt in enumerate(body):
            if not (
                isinstance(stmt, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "RULE_NOT_IMPLEMENTED"
                    for t in stmt.targets
                )
            ):
                continue
            following = body[index + 1] if index + 1 < len(body) else None
            if (
                isinstance(following, ast.Expr)
                and isinstance(following.value, ast.Constant)
                and isinstance(following.value.value, str)
            ):
                doc = following.value.value
    assert doc is not None, "RULE_NOT_IMPLEMENTED 의 docstring 을 찾지 못했습니다."

    assert "이 엔진이 아직 못 한다" in doc
    assert "코드가 생겨야 풀린다" in doc
    #: **금지선.**
    assert "확실한 거부" in doc and "붙이지 않는다" in doc
    assert "``UNKNOWN`` 쪽의 코드다" in doc

    assert ValidationCode.RULE_NOT_IMPLEMENTED.value == "rule_not_implemented"
    assert len(ValidationCode) == 48


def test_02_the_string_count_is_75_but_the_code_count_is_69():
    """
    **75 는 문자열 등장 수다.** 코드로 센 것은 69곳이고, 차이 6곳은
    주석·docstring 이다. 숫자를 그대로 믿지 않고 다시 센다.
    """
    strings = 0
    for path in production_files():
        strings += path.read_text(encoding="utf-8").count("RULE_NOT_IMPLEMENTED")
    assert strings == STRING_OCCURRENCES

    sites = code_sites()
    assert len(sites) == CODE_OCCURRENCES
    assert strings - len(sites) == len(PROSE_OCCURRENCES) == 6

    #: 산문 자리를 정확히 집는다 — 어디가 설명이고 어디가 코드인지 고정한다.
    prose = set()
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        source = path.read_text(encoding="utf-8")
        if "RULE_NOT_IMPLEMENTED" not in source:
            continue
        lines = prose_lines(path)
        for index, line in enumerate(source.splitlines(), start=1):
            if "RULE_NOT_IMPLEMENTED" in line and index in lines:
                prose.add((rel, index))
    assert prose == PROSE_OCCURRENCES


# ======================================================================
# B · C. ValidationResult / missing_rule 매핑
# ======================================================================


def test_03_only_unknown_can_carry_this_code_in_validation_result():
    """
    **B (§20): ``ValidationResult`` 매핑.**

    ``ValidationResult.invalid(...)`` 에 이 코드를 넣는 production 호출이
    **0건**이다. 그리고 ``missing_rule`` 을 받는 생성자는 ``unknown`` 뿐이다
    — 구조가 금지선을 지킨다.
    """
    offenders = []
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"invalid", "valid"}
            ):
                continue
            if mentions_code(node):
                offenders.append(f"{rel}:{node.lineno} {_unparse(node)[:70]}")
    assert offenders == [], offenders

    tree = ast.parse(source_of("engine/validation.py"))
    takes_missing_rule = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            arg.arg == "missing_rule"
            for arg in list(node.args.args) + list(node.args.kwonlyargs)
        )
    }
    assert takes_missing_rule == {"unknown"}


def test_04_the_code_and_a_missing_rule_are_not_the_same_fact():
    """
    **C (§20): ``missing_rule`` 매핑.**

    "``missing_rule`` 이 있는 결과" 와 "코드가 ``RULE_NOT_IMPLEMENTED`` 인
    결과" 는 **같지 않다.** 양방향으로 반례를 만든다.
    """
    #: 코드는 있는데 규칙 이름이 없다 — 흔하다.
    bare = ValidationResult.unknown(ValidationCode.RULE_NOT_IMPLEMENTED, "까닭 없이")
    assert bare.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert bare.missing_rule is None

    #: 규칙 이름은 있는데 코드가 다르다.
    other = ValidationResult.unknown(
        ValidationCode.INFORMATION_UNAVAILABLE, "정보가 없다", missing_rule="어떤 규칙"
    )
    assert other.missing_rule == "어떤 규칙"
    assert other.code is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: 실제 production 에서도 그렇다 — 조건 거짓은 코드가 있고 규칙 이름이 없다.
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))
    assert false.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert false.missing is None


# ======================================================================
# D. status / code 정합성 — **이 Phase 의 중심 측정**
# ======================================================================


def test_05_sixteen_result_sites_attach_this_code_to_a_definite_refusal():
    """
    **D (§20): status/code 정합성 — enum 의 금지선을 어기는 자리를 센다.**

    상태가 "모른다" 쪽인지는 **상태 enum 자신이 적어 둔 묶음**으로 가른다
    (``engine.activation._UNKNOWN_STATUSES``). 내가 새 기준을 만들지 않는다.

    결과: **16곳 위반 · 17곳 적합.** 목록을 그대로 고정한다 — 늘어나면
    여기서 깨지고, 고쳐서 줄어도 여기서 깨진다. 어느 쪽이든 신호다.
    """
    violations, conforming = status_paired_sites()
    assert set(violations) == CONTRACT_VIOLATIONS
    assert len(violations) == 16
    assert len(conforming) == CONFORMING_SITES

    #: 위반 쪽 상태는 **하나도** ``_UNKNOWN_STATUSES`` 에 없다.
    for _, _, status in violations:
        owner, name = status.split(".")
        if owner == "ActivationStatus":
            assert getattr(ActivationStatus, name) not in _UNKNOWN_STATUSES


def test_06_the_four_combinations_the_prompt_asks_about():
    """
    **§7 이 지목한 네 조합의 실재 여부.**

    | 조합 | 실재? |
    |---|---|
    | ``RULE_NOT_IMPLEMENTED`` + ``UNKNOWN`` | **있다** (정상) |
    | ``RULE_NOT_IMPLEMENTED`` + ``INVALID`` | **ValidationResult 에는 없다** |
    | ``RULE_NOT_IMPLEMENTED`` + ``VALID``/``ELIGIBLE`` | **없다** |
    | ``RULE_NOT_IMPLEMENTED`` + ``missing_rule=None`` | **있다** (정상) |
    """
    #: UNKNOWN + 코드 — 정상.
    unknown = ValidationResult.unknown(ValidationCode.RULE_NOT_IMPLEMENTED, "")
    assert unknown.validity is ActionValidity.UNKNOWN
    assert unknown.permits_execution is False

    #: VALID 와 함께는 **만들 수 없다** — ``valid()`` 가 코드를 받지 않는다.
    assert ValidationResult.valid("되었다").code is ValidationCode.OK

    #: ELIGIBLE 과 함께도 없다 — 트리거 계층에서 적격은 ``OK`` 다.
    state = new_state()
    from engine.game_state_view import GameStateView
    from engine.effect import EffectDefinitionRegistry

    definition = watched_definition(activation=None)
    collection = TriggerCollector(
        GameStateView.from_state(state, viewer=MINE),
        TriggerRegistry((watching(None),)),
        definitions=EffectDefinitionRegistry((definition,)),
    ).collect(drawn_event())
    for candidate in collection:
        assert candidate.status is TriggerStatus.ELIGIBLE
        assert candidate.code is ValidationCode.OK
        assert candidate.code is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: missing_rule=None 과 함께는 흔하다 (``test_04``).
    assert unknown.missing_rule is None


def test_07_eight_dataclasses_use_this_code_as_a_conservative_default():
    """
    **생성이 아닌 자리 — ``code`` 필드의 기본값 8곳.**

    "아무도 말하지 않으면 이유는 '우리가 못 한다'" 라는 **보수적 기본값**
    이다. 판정이 아니라 자리표시이므로 금지선을 어기지 않는다.
    """
    owners = set()
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.target.id == "code"
                    and stmt.value is not None
                    and mentions_code(stmt.value)
                ):
                    owners.add((rel, node.name))
    assert owners == FIELD_DEFAULT_OWNERS
    assert len(owners) == 8

    #: 기본값이 실제로 그 값이다.
    from engine.activation import ActivationResult
    from engine.effect.resolution import EffectResult

    for cls in (ActivationResult, EffectResult):
        field = next(f for f in dataclasses.fields(cls) if f.name == "code")
        assert field.default is ValidationCode.RULE_NOT_IMPLEMENTED


# ======================================================================
# E · F · G · H. 네 가지 구분
# ======================================================================


def test_08_unknown_and_this_code_are_different_axes():
    """
    **E (§20): ``UNKNOWN`` 과의 분리.**

    상태와 코드는 **다른 축**이다. 같은 ``CONDITION_UNKNOWN`` 상태에 두
    코드가 붙을 수 있고, 같은 코드가 여러 상태에 붙는다.
    """
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    assert rule.status is info.status is ActivationStatus.CONDITION_UNKNOWN
    assert rule.code is not info.code

    #: 거꾸로 — 같은 코드가 **다른 상태**에 붙는다 (바로 이것이 §5 의 질문).
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))
    missing = activate(new_state(), synthetic(activation=None))
    assert false.code is rule.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert false.status is not rule.status
    assert missing.status is ActivationStatus.ACTIVATED


def test_09_information_unavailable_is_still_separate():
    """
    **F (§20): ``INFORMATION_UNAVAILABLE`` 과의 분리.**

    발동·해결·트리거·타이밍 네 자리가 모두 ``missing_rules()`` 로 가른다.
    가르는 자리를 AST 로 센다 — ``IfExp`` 다섯 곳.
    """
    splits = []
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.IfExp) and mentions_code(node):
                text = _unparse(node)
                if "INFORMATION_UNAVAILABLE" in text:
                    splits.append(rel)
    assert sorted(splits) == [
        "engine/activation.py",
        "engine/activation_timing.py",
        "engine/effect/executor.py",
        "engine/trigger.py",
        "engine/trigger.py",
    ]

    assert activate(
        new_state(), synthetic(activation=IsMonster(InstanceId(9999)))
    ).code is ValidationCode.INFORMATION_UNAVAILABLE
    assert resolve(
        new_state(), synthetic(activation=IsMonster(InstanceId(9999)))
    ).code is ValidationCode.INFORMATION_UNAVAILABLE


def test_10_execution_forbidden_exists_but_the_effect_layers_do_not_use_it():
    """
    **G (§20): ``EXECUTION_FORBIDDEN`` 과의 분리 — 그리고 발견 M2.**

    출처 금지(ADR-004)는 ``EXECUTION_FORBIDDEN`` 이 정확하고, 트리거 계층은
    3-E-26 에서 그렇게 고쳤다. **발동·해결 계층은 아직 ``RULE_NOT_IMPLEMENTED``
    를 쓴다.**

    고치지 않는다 — 현재 상태를 고정해서 바뀌면 알게 한다.
    """
    assert ValidationCode.EXECUTION_FORBIDDEN is not (
        ValidationCode.RULE_NOT_IMPLEMENTED
    )

    forbidden = synthetic(
        activation=None, provenance=EffectProvenance.text_derived("공식 텍스트에서 유추")
    )
    activated = activate(new_state(), forbidden)
    resolved = resolve(new_state(), forbidden)

    #: 상태는 정확하다.
    assert activated.status is ActivationStatus.FORBIDDEN
    assert resolved.status is ResolutionStatus.FORBIDDEN
    #: 코드는 거친 이름표다 — **현재 상태를 고정한다.**
    assert activated.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert resolved.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert activated.code is not ValidationCode.EXECUTION_FORBIDDEN

    #: 트리거 계층은 **다르게** 적는다 — 같은 사실, 정확한 코드.
    assert "ValidationCode.EXECUTION_FORBIDDEN" in source_of("engine/trigger.py")
    #: 그리고 그 코드를 **읽는** 자리가 트리거 계층에만 있다.
    assert GateVerdict.forbids.__doc__ is not None
    assert "EXECUTION_FORBIDDEN" in source_of("engine/trigger.py")


def test_11_candidate_not_eligible_exists_but_the_effect_layers_do_not_use_it():
    """
    **H (§20): ``CANDIDATE_NOT_ELIGIBLE`` 과의 분리 — 그리고 발견 M1.**

    조건을 끝까지 보고 **거짓**을 받은 자리는 확실한 거부다. 트리거 계층은
    3-E-26 에서 ``CANDIDATE_NOT_ELIGIBLE`` 로 고쳤고, 그 이유를 주석에
    적어 두었다. **발동·해결 계층은 아직 ``RULE_NOT_IMPLEMENTED`` 다.**
    """
    false = synthetic(activation=Always(ConditionResult.FALSE))
    activated = activate(new_state(), false)
    resolved = resolve(new_state(), false)

    assert activated.status is ActivationStatus.CONDITION_FALSE
    assert resolved.status is ResolutionStatus.CONDITION_FALSE
    #: **현재 상태를 고정한다** — 조건 거짓인데 "엔진이 못 한다" 고 적는다.
    assert activated.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert resolved.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert activated.code is not ValidationCode.CANDIDATE_NOT_ELIGIBLE

    #: 트리거 계층의 같은 사실은 정확한 코드를 쓴다 (3-E-26).
    trigger_source = source_of("engine/trigger.py")
    assert "code=ValidationCode.CANDIDATE_NOT_ELIGIBLE" in trigger_source
    assert "확실한 거부이고 미구현이 아니다" in trigger_source
    assert "판정과 이유가 어긋난다" in trigger_source


# ======================================================================
# I · J · K · L · M. 계층별
# ======================================================================


def test_12_the_trigger_layer_uses_this_code_only_on_unknown():
    """
    **I (§20): 트리거 계층.**

    ``TriggerCollector`` 와 ``TriggerEligibilityJudge`` 는 이 코드를
    ``UNKNOWN`` 에만 쓴다. 3-E-26/27 이 세운 것이 그대로다.
    """
    from engine.game_state_view import GameStateView
    from engine.effect import EffectDefinitionRegistry

    view = GameStateView.from_state(new_state(), viewer=MINE)

    #: 조건 거짓 → ``INELIGIBLE`` + ``CANDIDATE_NOT_ELIGIBLE``.
    refused = TriggerCollector(
        view, TriggerRegistry((watching(Always(ConditionResult.FALSE)),))
    ).collect(drawn_event())
    for candidate in refused:
        assert candidate.status is TriggerStatus.INELIGIBLE
        assert candidate.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE

    #: 규칙 없음 → ``UNKNOWN`` + ``RULE_NOT_IMPLEMENTED``.
    undecided = TriggerCollector(
        view, TriggerRegistry((watching(UnimplementedRule("없는 규칙")),))
    ).collect(drawn_event())
    for candidate in undecided:
        assert candidate.status is TriggerStatus.UNKNOWN
        assert candidate.code is ValidationCode.RULE_NOT_IMPLEMENTED

    #: 정의 미등록 → ``UNKNOWN`` + 같은 코드 (다른 까닭, 같은 쪽).
    missing = TriggerCollector(
        view,
        TriggerRegistry((watching(None),)),
        definitions=EffectDefinitionRegistry(()),
    ).collect(drawn_event())
    for candidate in missing:
        assert candidate.status is TriggerStatus.UNKNOWN
        assert candidate.code is ValidationCode.RULE_NOT_IMPLEMENTED


@requires_official_db
@pytest.mark.real_card
def test_13_the_action_validator_uses_this_code_only_on_unknown(repository):
    """
    **J (§20): ``ActionValidator``.**

    종류마다 코드가 같은 뜻인지 실제 판으로 확인한다. ``UNKNOWN`` 에만
    붙고, 확실한 위반은 **다른 코드**를 받는다.
    """
    deck = [card.id for card in list(repository.all_cards())[:12]]
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=5)
    while duel.advance() is not None:
        pass
    seat = duel.to_act
    validator = ActionValidator(duel.view(seat))
    source = duel.state.player(seat).hand[0].instance_id

    seen: dict[str, tuple[str, str]] = {}
    for build in (
        PlayerAction.normal_summon,
        PlayerAction.set_monster,
        PlayerAction.set_spell_trap,
        PlayerAction.activate_card,
        PlayerAction.special_summon,
    ):
        action = build(actor=seat, source=source)
        verdict = validator.validate(action)
        seen[action.kind.value] = (verdict.validity.value, verdict.code.value)
        if verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED:
            #: **금지선이 지켜진다** — 이 코드는 UNKNOWN 에만 붙는다.
            assert verdict.validity is ActionValidity.UNKNOWN
        if verdict.validity is ActionValidity.INVALID:
            assert verdict.code is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: 종류마다 **다른** 답이 나온다 — 코드가 한 뜻으로 뭉개지지 않는다.
    assert len(set(seen.values())) >= 2


def test_14_the_effect_layer_mixes_two_meanings_in_one_code():
    """
    **K (§20): 효과 실행 계층 — 가장 많이 쓰는 자리 (22곳).**

    같은 코드가 세 가지에 붙는다.

    - 조작 종류 미지원 (``UNSUPPORTED_OPERATION``) → **정확**
    - 문맥 불일치 (``INVALID_CONTEXT``) → 구조 오류, 미구현이 아니다
    - 조건 거짓 (``CONDITION_FALSE``) → 확실한 거부

    세 가지가 한 코드를 공유한다는 사실을 고정한다.
    """
    violations, conforming = status_paired_sites()
    executor_violations = {
        status for rel, _, status in violations if rel == "engine/effect/executor.py"
    }
    executor_conforming = {
        status for rel, _, status in conforming if rel == "engine/effect/executor.py"
    }
    assert executor_violations == {
        "ResolutionStatus.EXECUTION_ERROR",
        "ResolutionStatus.INVALID_OPERATION",
        "ResolutionStatus.INVALID_CONTEXT",
        "ResolutionStatus.FORBIDDEN",
        "ResolutionStatus.CONDITION_FALSE",
    }
    assert executor_conforming == {
        "ResolutionStatus.UNCHECKED_RULES",
        "ResolutionStatus.UNSUPPORTED_OPERATION",
        "ResolutionStatus.UNKNOWN",
        "ResolutionStatus.NOT_IMPLEMENTED",
    }
    #: 두 묶음이 겹치지 않는다 — 분류가 모호하지 않다.
    assert executor_violations & executor_conforming == set()


def test_15_the_cost_layer_has_its_own_code_and_does_not_borrow_this_one():
    """
    **L (§20): 비용 계층.**

    비용은 ``COST_NOT_IMPLEMENTED`` 를 쓴다 — 이 코드를 빌리지 않는다.
    ``engine/cost/`` 에 ``RULE_NOT_IMPLEMENTED`` 가 **하나도 없다.**
    """
    for path in sorted((PROJECT_ROOT / "engine" / "cost").rglob("*.py")):
        assert "RULE_NOT_IMPLEMENTED" not in path.read_text(encoding="utf-8"), path

    assert ValidationCode.COST_NOT_IMPLEMENTED is not (
        ValidationCode.RULE_NOT_IMPLEMENTED
    )
    #: 다만 지불 **실행** 쪽(``engine/payment.py``)은 예외 처리에서 쓴다.
    assert "RULE_NOT_IMPLEMENTED" in source_of("engine/payment.py")


def test_16_the_targeting_layer_uses_candidate_codes_not_this_one():
    """
    **M (§20): 대상 계층.**

    대상 선택은 ``CANDIDATE_NOT_ELIGIBLE`` · ``TOO_FEW_SELECTED`` 같은
    자기 코드를 쓴다. ``engine/effect/targeting.py`` 에 이 코드가 **없다.**
    """
    targeting = PROJECT_ROOT / "engine" / "effect" / "targeting.py"
    if not targeting.is_file():  # pragma: no cover - 경로가 바뀌면 알려 준다
        pytest.fail("engine/effect/targeting.py 가 없습니다 — 경로를 다시 확인하세요.")
    source = targeting.read_text(encoding="utf-8")
    assert "RULE_NOT_IMPLEMENTED" not in source
    assert "CANDIDATE_NOT_ELIGIBLE" in source


# ======================================================================
# N · O. production 도달 / dormant
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_17_the_misclassified_code_reaches_the_duel_boundary(repository):
    """
    **N (§20): production 도달.**

    ``Duel.apply`` 가 발동기의 코드를 **그대로** ``DuelStep.code`` 에 넣는다
    (``duel.py:912``). 즉 오분류가 공개 경계까지 간다.

    그리고 ``Duel.apply`` 자신도 목록 멤버십 거절에 이 코드를 쓴다 —
    "미구현" 이 아니라 "지금 후보가 아니다" 인데 같은 코드다.
    """
    duel = Duel.start(
        repository,
        decks=([card.id for card in list(repository.all_cards())[:12]],) * 2,
        seed=5,
    )
    while duel.advance() is not None:
        pass
    seat = duel.to_act
    source = duel.state.player(seat).hand[0].instance_id

    before = duel.state.state_hash()
    step = duel.apply(PlayerAction.special_summon(actor=seat, source=source))
    assert step.accepted is False
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "허가된 행위가 아닙니다" in step.reason
    assert duel.state.state_hash() == before

    #: 발동기의 코드가 그대로 흘러간다는 것을 소스로 확인한다.
    assert "DuelStep(action, False, activated.code, activated.reason)" in source_of(
        "engine/duel.py"
    )


def test_18_the_unimplemented_resolver_sites_are_dormant():
    """
    **O (§20): dormant 구분.**

    ``engine/effect/resolution.py`` 의 네 자리는 ``UnimplementedResolver``
    안에 있고, 그 클래스는 **production 에서 한 번도 만들어지지 않는다.**
    (생성처 전부 ``tests/``.) 그래서 거기의 M2 패턴은 dormant 다.
    """
    production, tests = [], []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel.startswith((".venv", "build")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "UnimplementedResolver"
            ):
                (tests if rel.startswith("tests/") else production).append(
                    f"{rel}:{node.lineno}"
                )
    assert production == []
    assert len(tests) > 10

    #: 그런데 소비자 계약은 살아 있다 — 받으면 올바른 상태를 돌려준다.
    assert issubclass(UnimplementedResolver, object)
    #: 마지막 자리는 소스 자신이 "여기까지 오는 경우는 아직 없다" 고 적는다.
    assert "여기까지 오는 경우는 아직 없다" in source_of("engine/effect/resolution.py")


def test_19_the_three_exception_handlers_are_defensive_not_normal_paths():
    """
    **O (§20): dormant 의 다른 종류 — 예외 처리.**

    세 자리(``action_execution`` · ``effect/executor`` · ``payment``)는
    ``except Exception`` 안이고 전부 ``# pragma: no cover - 일어나서는 안
    된다`` 가 붙어 있다. **예외는 미구현이 아니다** — 그러나 더 정확한
    ``ValidationCode`` 가 enum 에 없다.
    """
    for rel in (
        "engine/action_execution.py",
        "engine/effect/executor.py",
        "engine/payment.py",
    ):
        source = source_of(rel)
        assert "except Exception as error:  # pragma: no cover" in source
        assert "일어나서는 안 된다" in source

    #: 더 정확한 코드가 **없다** — 그래서 고치려면 enum 을 늘려야 한다.
    assert "EXECUTION_ERROR" not in ValidationCode.__members__
    assert "UNSUPPORTED_OPERATION" not in ValidationCode.__members__
    assert "INVALID_CONTEXT" not in ValidationCode.__members__


# ======================================================================
# P · Q · R. AI / Simulation / Hidden information
# ======================================================================


def test_20_only_four_production_sites_read_the_code_as_a_decision():
    """
    **P (§20): AI/Search 영향 — 먼저 "누가 코드를 읽는가" 를 센다.**

    ``.code`` 를 **판단 입력**으로 읽는 production 자리는 넷뿐이다. 넷을
    고정한다 — 다섯 번째가 생기면 오분류가 판정을 바꿀 수 있으므로 여기서
    깨져야 한다.
    """
    readers = set()
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            text = _unparse(node)
            if ".code" in text and ("ValidationCode" in text or "CODES" in text):
                readers.add((rel, text))
    assert readers == CODE_READERS
    assert len(readers) == 4


def test_21_the_ai_sees_unknown_instead_of_refused_but_ranks_them_the_same():
    """
    **Q (§20): ``SimulationStatus``.**

    오분류의 **유일한 관측 가능한 결과**가 여기다 — 확실한 거부가
    ``SimulationStatus.UNKNOWN`` 으로 읽힌다 (``REFUSED`` 가 아니다).

    그런데 **줄 세우기가 같다**: 둘 다 점수가 ``None`` 이고 같은
    ``ordering_key`` 를 낸다. 그래서 AI 의 **선택**은 바뀌지 않는다 —
    보고만 거칠어진다.
    """
    assert ValidationCode.RULE_NOT_IMPLEMENTED in _UNKNOWN_CODES
    #: 정확한 코드였다면 ``REFUSED`` 로 갔을 것이다.
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE not in _UNKNOWN_CODES
    assert ValidationCode.EXECUTION_FORBIDDEN not in _UNKNOWN_CODES

    action = PlayerAction.passing(actor=MINE)
    unknown = SearchCandidate(action=action, status=SimulationStatus.UNKNOWN)
    refused = SearchCandidate(action=action, status=SimulationStatus.REFUSED)
    assert unknown.value is refused.value is None
    assert unknown.ordering_key() == refused.ordering_key()
    assert unknown.ordering_key()[0] == 1

    #: 그리고 원래 코드가 보존된다 — 유실이 아니다.
    carried = SimulationResult(
        action=action,
        status=SimulationStatus.UNKNOWN,
        viewer=MINE,
        code=ValidationCode.RULE_NOT_IMPLEMENTED,
    )
    assert carried.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert carried.future is None

    #: ``agent/`` 는 이 코드를 **한 자리에서만** 읽는다.
    hits = sum(
        path.read_text(encoding="utf-8").count("RULE_NOT_IMPLEMENTED")
        for path in sorted((PROJECT_ROOT / "agent").rglob("*.py"))
    )
    assert hits == 1


def test_22_hidden_information_never_becomes_this_code():
    """
    **R (§20): hidden information.**

    가려진 정보는 ``HIDDEN_CARD`` · ``INFORMATION_UNAVAILABLE`` ·
    ``CARD_DEFINITION_UNAVAILABLE`` 로 가고 이 코드로 바뀌지 않는다.
    """
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert info.code is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert info.unchecked and "관측에 보이지 않음" in info.unchecked[0]

    #: 세 "정보 없음" 코드가 모두 따로 있다.
    for name in (
        "HIDDEN_CARD",
        "INFORMATION_UNAVAILABLE",
        "CARD_DEFINITION_UNAVAILABLE",
        "EFFECT_LIST_UNRELIABLE",
    ):
        assert name in ValidationCode.__members__
        assert getattr(ValidationCode, name) is not ValidationCode.RULE_NOT_IMPLEMENTED


# ======================================================================
# S. safety invariant (§19 의 열 항목)
# ======================================================================


def test_23_all_ten_safety_invariants_hold():
    """
    **S (§20) · §19: 열 가지 invariant.**

    오분류가 있어도 **안전선은 전부 지켜진다** — 그것이 이 Phase 가
    ``D. MISCLASSIFIED_PRODUCTION`` 을 고르지 않는 근거다.
    """
    #: 1 · 6 — UNKNOWN 과 FALSE 가 서로 바뀌지 않는다.
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))
    assert rule.status is ActivationStatus.CONDITION_UNKNOWN
    assert false.status is ActivationStatus.CONDITION_FALSE
    assert rule.status is not false.status

    #: 2 · 3 — 까닭이 섞이지 않는다.
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE

    #: 4 · 5 — 코드가 서로 다른 멤버다.
    for name in ("EXECUTION_FORBIDDEN", "CANDIDATE_NOT_ELIGIBLE"):
        assert getattr(ValidationCode, name) is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: 7 · 10 — 패배도 0점도 아니다.
    action = PlayerAction.passing(actor=MINE)
    candidate = SearchCandidate(action=action, status=SimulationStatus.UNKNOWN)
    assert candidate.value is None
    assert candidate.comparable is False

    #: 8 — 허가가 되지 않는다.
    assert (
        ValidationResult.unknown(
            ValidationCode.RULE_NOT_IMPLEMENTED, ""
        ).permits_execution
        is False
    )
    for result in (rule, false, info):
        assert result.status is not ActivationStatus.ACTIVATED
        assert len(result.chain) == 0

    #: 9 — 가려진 정보가 이 코드로 바뀌지 않는다 (``test_22``).
    assert ValidationCode.HIDDEN_CARD is not ValidationCode.RULE_NOT_IMPLEMENTED


def test_24_a_misclassified_code_never_changes_the_board():
    """
    **§19-5 · §19-6 을 판으로 확인한다.** 오분류된 코드를 받은 시도는
    어느 쪽도 판을 바꾸지 않는다.
    """
    for activation in (
        Always(ConditionResult.FALSE),
        UnimplementedRule("없는 규칙"),
        IsMonster(InstanceId(9999)),
    ):
        state = new_state()
        before = state.state_hash()
        result = activate(state, synthetic(activation=activation))
        assert result.status is not ActivationStatus.ACTIVATED
        assert state.state_hash() == before
        assert result.deltas == ()


# ======================================================================
# T. 실제 corpus · regression
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_25_real_corpus_sample_of_this_code(repository):
    """
    **T (§20): 실제 corpus 사례.**

    실제 카드로 한 판을 돌리고, 받아들여진 수와 거절된 수의 코드를 모은다.

    **``WithheldAction`` 은 코드를 들고 있지 않다** — 필드가 ``kind`` ·
    ``reason``(문자열) · ``missing`` 뿐이다 (3-E-28 이 이미 측정한 모양).
    그래서 보류 쪽은 문장으로, 적용 쪽은 코드로 센다.
    """
    deck = [card.id for card in list(repository.all_cards())[:16]]
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=11)
    seen_codes: set[ValidationCode] = set()
    withheld_missing: set[str] = set()

    for _ in range(80):
        if duel.is_over:
            break
        if duel.advance() is not None:
            continue
        legal = duel.legal_actions()
        for withheld in legal.withheld:
            assert not hasattr(withheld, "code")
            if withheld.missing:
                withheld_missing.add(withheld.missing)
        if not legal.allowed:
            break
        #: 허가된 수 하나와 **허가되지 않은 수 하나**를 둘 다 넣어 본다.
        seen_codes.add(duel.apply(legal.allowed[0]).code)
        source = duel.state.player(duel.to_act).hand
        if source:
            rejected = duel.apply(
                PlayerAction.special_summon(
                    actor=duel.to_act, source=source[0].instance_id
                )
            )
            seen_codes.add(rejected.code)

    #: 여러 코드가 나온다 — 이 코드가 전부를 삼키지 않는다.
    assert len(seen_codes) >= 2, seen_codes
    #: 그리고 거절 쪽에서 실제로 이 코드가 나온다.
    assert ValidationCode.RULE_NOT_IMPLEMENTED in seen_codes
    assert ValidationCode.OK in seen_codes
    #: 보류 쪽은 **규칙 이름**을 들고 있다 (코드가 아니다).
    assert withheld_missing, "보류에 missing 문장이 하나도 없습니다."


def test_26_the_distinctions_from_phase_3e24_to_3e35_still_hold():
    """
    **§21 regression — 열두 Phase 가 세운 구분이 그대로인지.**
    """
    assert ConditionResult.UNKNOWN is not ConditionResult.FALSE
    assert ActionValidity.UNKNOWN is not ActionValidity.INVALID
    for name in (
        "INFORMATION_UNAVAILABLE",
        "EXECUTION_FORBIDDEN",
        "CANDIDATE_NOT_ELIGIBLE",
        "COST_NOT_IMPLEMENTED",
    ):
        assert getattr(ValidationCode, name) is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert ActivationStatus.CONDITION_UNKNOWN is not ActivationStatus.CONDITION_FALSE
    assert ResolutionStatus.CONDITION_UNKNOWN is not ResolutionStatus.CONDITION_FALSE

    #: enum 크기가 늘지 않았다 — 이번 Phase 가 새 코드를 만들지 않았다.
    assert len(ValidationCode) == 48
    assert len(ConditionResult) == 3
    assert len(ActionValidity) == 3
    assert len(SimulationStatus) == 5
    assert len(ActionStatus) == 5

    #: 3-E-35 가 센 수가 그대로다.
    assert len(UNSUPPORTED_REASON) == len(PlayerActionKind)
