"""
Phase 3-E-37 — ``ValidationCode`` 거부 코드 의미 정밀 감사.

핵심 질문: **거부된 이유를 현재 ``ValidationCode`` 체계가 충분히 구분해서
표현하고 있는가.** "어디서 쓰느냐" 가 아니다.

측정으로 드러난 아홉 가지
-------------------------

1. **``ValidationCode`` 는 48개이고 전부 쓰인다** (생성 0회 멤버 0개, 총
   251회). 프롬프트가 말하는 "48개 rejection usage" 는 **enum 크기**이고
   사용처 수가 아니다 — 거부를 **만드는** 자리는 **58곳**이다.

2. **enum 이 섹션 주석으로 validity 를 선언한다.**
   ``# --- 구조 (INVALID) ---`` 11개 · ``# --- 판 위의 사실 (INVALID) ---``
   12개 · ``# --- 모른다 (UNKNOWN) ---`` **5개**(여기에
   ``RULE_NOT_IMPLEMENTED`` 가 있다) · 그 뒤로 계층별 묶음.

3. **45개 코드는 한 번도 비교되지 않는다.** ``.code`` 를 **판단 입력으로
   읽는** 자리에 등장하는 멤버는 ``OK`` · ``RULE_NOT_IMPLEMENTED`` ·
   ``EXECUTION_FORBIDDEN`` **셋뿐**이다. 나머지 45개는 **보고용**이고,
   결정은 ``status``/``validity`` 가 쥐고 있다.

4. **M1 — 조건 거짓에 "미구현" 을 적는다** (발동 1 · 해결 1). 실측:
   `Always(FALSE)` → `status=condition_false, code=rule_not_implemented`.

5. **M2 — 출처 금지에 "미구현" 을 적는다** (발동 1 · 해결 1 · dormant 1).
   ``EXECUTION_FORBIDDEN`` 의 docstring 이 **바로 이 경우를 위해** 쓰여
   있다: "출처가 실행을 금지한다 (``TEXT_DERIVED``, ADR-004)".

6. **M3 (이번에 새로 찾았다) — ``_event_relation`` 이 ``INVALID`` 관문에
   이 코드를 붙인다** (`engine/trigger.py:1318`). 그리고
   ``_refusal_code`` 가 그것을 그대로 올린다 — **그 함수의 docstring 이
   금지하는 바로 그 일**이다. 3-E-36 은 이 자리를 "진짜 미구현" 으로
   분류했는데, 틀렸다.

7. **그런데 새 enum 이 필요하지 않다.** M1·M2·M3 모두 **기존 코드**로
   표현된다 (``CANDIDATE_NOT_ELIGIBLE`` · ``EXECUTION_FORBIDDEN``). 구조
   오류·예외 10곳은 코드가 없지만 **``status`` 가 이미 정확한 사실을
   들고 있고 아무 consumer 도 코드를 읽지 않는다.**

8. **``ValidationResult`` 는 5칸이다** — ``validity`` · ``code`` ·
   ``reason`` · ``missing_rule`` · ``notes``. ``value`` 와
   ``ordering_key`` 는 **``SearchCandidate``** 의 것이고 이 타입에 없다.

9. **``ValidationResult.invalid(...)`` 로 이 코드가 들어가는 간접 경로가
   있다** — ``_check_requirements`` 가 조건이 ``FALSE`` 일 때
   ``requirement.code`` 를 그대로 넘긴다. 다만 이 코드를 든 세
   ``Requirement`` 의 조건이 **모두 ``FALSE`` 를 내지 않으므로** 닿지
   않는다. 3-E-36 의 "0건" 은 **리터럴 호출**에 대해서만 참이었다.

이 Phase 는 production 을 고치지 않았다. 감사다.
"""

import ast
import dataclasses
import pathlib
import re

import pytest

from agent.search import SearchCandidate
from agent.simulation import SimulationStatus, _UNKNOWN_CODES
from engine.action import PlayerAction
from engine.action_validation import ActionValidator, Requirement
from engine.activation import ActivationStatus
from engine.condition import Always, ConditionResult, IsMonster, UnimplementedRule
from engine.duel import Duel
from engine.effect import CardDrawn, EffectDefinitionRegistry, EffectProvenance
from engine.effect.resolution import ResolutionStatus
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.trigger import (
    EligibilityGate,
    TimingEvent,
    TimingPoint,
    TriggerCollector,
    TriggerEligibilityJudge,
    TriggerRegistry,
    TriggerSpec,
    TriggerStatus,
)
from engine.trigger_chain import _refusal_code, _undecided_code
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Zone

from tests.conftest import requires_official_db

#: 발동 · 해결 계층을 **그대로** 부르는 기존 도구를 다시 쓴다.
from tests.test_validation_code_consistency import (
    WATCHED,
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

#: ``ValidationCode`` 멤버 수. 프롬프트가 "48개 rejection usage" 라고 말한 48 은
#: **이 수**이고 사용처 수가 아니다.
CODE_MEMBER_COUNT = 48

#: ``engine/`` + ``agent/`` 에서 코드가 **등장하는** 줄.
#: 69 → **67** (Phase 3-E-38 이 M1 ×2 · M2 ×2 를 고치면서 2 감소).
CODE_OCCURRENCES = 67

#: 그중 **거부를 만드는** 자리.
#:
#: 58 → **54** (Phase 3-E-38). 넷을 고쳤는데 둘만 줄어든 것이 아니라 넷이
#: 줄었다 — M1 두 자리는 코드가 바뀌어 사라지고, M2 의 발동 쪽은 생성 자리의
#: 리터럴이 ``_AVAILABILITY_REFUSAL`` **표의 값**으로 옮겨 갔기 때문이다.
#: 표 안의 값은 조회용 데이터이므로 "거부를 만드는 자리" 가 아니라
#: **멤버십**으로 센다 (집합 멤버십 1 → **3**).
#:
#: 나머지는 enum 정의 1 · 필드 기본값 8 · 멤버십 3 · 비교 1 = 13.
#: 54 + 13 = 67 로 맞는다.
REJECTION_PRODUCTIONS = 54

#: enum 이 **섹션 주석으로 선언한** 묶음 → 멤버 수.
DECLARED_SECTIONS = {
    "구조 (INVALID)": 11,
    "판 위의 사실 (INVALID)": 12,
    "모른다 (UNKNOWN)": 5,
    "비용 · 선택 (Phase 2-C)": 8,
    "효과 실행 (Phase 2-D-2)": 2,
    "우선권 · 응답 기회 (Phase 2-F-1)": 5,
    "일반 소환 (Phase 2-I)": 2,
    "발동 타이밍 · 스펠 스피드 (Phase 2-S)": 2,
}

#: ``# --- 모른다 (UNKNOWN) ---`` 섹션의 멤버. 여기 있는 코드는
#: **확실한 거부에 붙이지 않는다** 는 것이 enum 의 계약이다.
UNKNOWN_SECTION_MEMBERS = {
    "HIDDEN_CARD",
    "INFORMATION_UNAVAILABLE",
    "CARD_DEFINITION_UNAVAILABLE",
    "EFFECT_LIST_UNRELIABLE",
    "RULE_NOT_IMPLEMENTED",
}

#: ``.code`` 를 **판단 입력으로** 읽는 자리에 등장하는 멤버 — 셋뿐이다.
COMPARED_MEMBERS = {"OK", "RULE_NOT_IMPLEMENTED", "EXECUTION_FORBIDDEN"}

#: 이 코드를 들고 있는 ``Requirement`` 세 곳. 셋 다 조건이 ``FALSE`` 를
#: **내지 않으므로** ``ValidationResult.invalid`` 로 가는 간접 경로가 닫혀 있다.
REQUIREMENT_CARRIERS = 3


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


def declared_sections() -> dict[str, list[str]]:
    """
    ``ValidationCode`` 의 멤버를 **섹션 주석**으로 묶는다.

    enum 자신이 ``# --- 구조 (INVALID) ---`` 처럼 적어 둔 것을 읽는다 —
    내가 새 기준을 만들지 않는다.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in source_of("engine/validation.py").splitlines():
        header = re.match(r"\s*# --- (.+?) -+$", line)
        if header:
            current = header.group(1).strip()
            continue
        member = re.match(r"\s{4}([A-Z_]+) = \"", line)
        if member and current is not None:
            sections.setdefault(current, []).append(member.group(1))
    #: ``생성자`` 섹션은 메서드 묶음이므로 멤버가 없다.
    return {name: members for name, members in sections.items() if members}


def member_docstrings() -> dict[str, str]:
    """멤버 → docstring (한 줄로 접어서)."""
    tree = ast.parse(source_of("engine/validation.py"))
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "ValidationCode"):
            continue
        body = node.body
        for index, stmt in enumerate(body):
            if not (
                isinstance(stmt, ast.Assign)
                and isinstance(stmt.targets[0], ast.Name)
            ):
                continue
            name = stmt.targets[0].id
            following = body[index + 1] if index + 1 < len(body) else None
            if (
                isinstance(following, ast.Expr)
                and isinstance(following.value, ast.Constant)
                and isinstance(following.value.value, str)
            ):
                found[name] = " ".join(following.value.value.split())
            else:
                found[name] = ""
    return found


def _reads_a_code(node: ast.Compare) -> bool:
    """
    이 비교가 ``.code`` 를 ``ValidationCode`` 와 견주는가.

    3-E-36 의 고의 위반이 찾아낸 구멍을 피한다 — 문자열로
    ``"ValidationCode"`` 를 찾으면 별명 import 를 놓친다. **멤버 이름**을
    맞춰 본다.
    """
    if ".code" not in _unparse(node):
        return False
    members = set(ValidationCode.__members__)
    for side in [node.left, *node.comparators]:
        if isinstance(side, ast.Attribute) and side.attr in members:
            return True
        name = (
            side.id
            if isinstance(side, ast.Name)
            else (side.attr if isinstance(side, ast.Attribute) else "")
        )
        if name.endswith("CODES"):
            return True
    return False


def prose_lines(path: pathlib.Path) -> set[int]:
    source = path.read_text(encoding="utf-8")
    found = {
        index + 1
        for index, line in enumerate(source.splitlines())
        if line.lstrip().startswith("#")
    }
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return found


def rejection_productions() -> list[tuple[str, int]]:
    """
    ``RULE_NOT_IMPLEMENTED`` 가 **거부를 만드는** 줄 전수.

    enum 정의 · ``code`` 필드 기본값 · 집합 멤버십 · 비교를 뺀 나머지다.
    """
    rows: list[tuple[str, int]] = []
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        source = path.read_text(encoding="utf-8")
        if "RULE_NOT_IMPLEMENTED" not in source:
            continue
        tree = ast.parse(source)
        prose = prose_lines(path)
        skip: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "RULE_NOT_IMPLEMENTED"
                for t in node.targets
            ):
                skip.add(node.lineno)
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "code"
                and node.value is not None
                and "RULE_NOT_IMPLEMENTED" in _unparse(node.value)
            ):
                skip.add(node.lineno)
            if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
                for element in getattr(node, "elts", []):
                    if (
                        isinstance(element, ast.Attribute)
                        and element.attr == "RULE_NOT_IMPLEMENTED"
                    ):
                        skip.add(element.lineno)
            if isinstance(node, ast.Compare) and "RULE_NOT_IMPLEMENTED" in _unparse(
                node
            ):
                for inner in ast.walk(node):
                    if (
                        isinstance(inner, ast.Attribute)
                        and inner.attr == "RULE_NOT_IMPLEMENTED"
                    ):
                        skip.add(inner.lineno)
        for index, line in enumerate(source.splitlines(), start=1):
            if "RULE_NOT_IMPLEMENTED" not in line:
                continue
            if index in prose or index in skip:
                continue
            rows.append((rel, index))
    return rows


def view_of(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=MINE)


# ======================================================================
# A. ValidationCode enum inventory
# ======================================================================


def test_01_the_enum_has_48_members_and_every_one_is_produced():
    """
    **A (§21): enum 전수.** 48개이고 **생성 0회 멤버가 없다.**

    프롬프트가 말한 "48" 은 **멤버 수**다 — 사용처 수가 아니다 (``test_03``).
    """
    assert len(ValidationCode) == CODE_MEMBER_COUNT

    produced: set[str] = set()
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel == "engine/validation.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in (
                ValidationCode.__members__
            ):
                produced.add(node.attr)

    missing = set(ValidationCode.__members__) - produced
    assert missing == set(), f"쓰이지 않는 코드가 생겼다: {sorted(missing)}"


def test_02_the_enum_declares_its_validity_groups_with_section_comments():
    """
    **A (§21): enum 이 스스로 묶음을 선언한다.**

    섹션 주석이 각 코드가 어느 ``ActionValidity`` 쪽인지 말한다. 이 Phase 의
    측정 기준이 **내 의견이 아니라 저장소의 선언**이라는 근거다.
    """
    sections = declared_sections()
    assert {name: len(members) for name, members in sections.items()} == (
        DECLARED_SECTIONS
    )

    #: ``RULE_NOT_IMPLEMENTED`` 는 **모른다 (UNKNOWN)** 묶음에 있다.
    assert set(sections["모른다 (UNKNOWN)"]) == UNKNOWN_SECTION_MEMBERS
    assert "RULE_NOT_IMPLEMENTED" in UNKNOWN_SECTION_MEMBERS

    #: 그리고 그 docstring 이 금지선을 적는다.
    docs = member_docstrings()
    assert "확실한 거부" in docs["RULE_NOT_IMPLEMENTED"]
    assert "붙이지 않는다" in docs["RULE_NOT_IMPLEMENTED"]

    #: 멤버 합이 48 이다 — 섹션 밖에 숨은 멤버가 ``OK`` 하나뿐이다.
    assert sum(DECLARED_SECTIONS.values()) == CODE_MEMBER_COUNT - 1


# ======================================================================
# B. RULE_NOT_IMPLEMENTED inventory
# ======================================================================


def test_03_the_rejection_usage_count_is_54_not_48():
    """
    **B (§21): 거부 사용처 수를 다시 센다.**

    코드 등장 67곳 = **거부 생성 54** + 필드 기본값 8 + enum 정의 1 +
    멤버십 3 + 비교 1.

    **48 은 enum 크기였다.** 숫자를 그대로 믿지 않고 다시 셌다.

    (3-E-38 이 네 자리를 고쳐 69 → 67 · 58 → 56 이 되었다.)
    """
    productions = rejection_productions()
    assert len(productions) == REJECTION_PRODUCTIONS
    assert len(productions) != CODE_MEMBER_COUNT

    #: 69 와의 차이가 정확히 11 이다 (8 + 1 + 1 + 1).
    occurrences = 0
    for path in production_files():
        prose = prose_lines(path)
        for index, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "RULE_NOT_IMPLEMENTED" in line and index not in prose:
                occurrences += 1
    assert occurrences == CODE_OCCURRENCES
    #: 11 → **13** (3-E-38 이 표에 값 둘을 더해 멤버십이 1 → 3 이 되었다).
    assert occurrences - len(productions) == 13


def test_04_only_three_members_are_ever_compared():
    """
    **B (§21) · §14 의 핵심.** 45개 코드는 **한 번도 비교되지 않는다.**

    즉 `code` 는 거의 전부 **보고용**이고, 결정은 ``status``/``validity`` 가
    쥐고 있다. 이것이 "오분류가 판정을 바꾸지 않는" 구조적 이유다.
    """
    compared: set[str] = set()
    for path in production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare) or not _reads_a_code(node):
                continue
            for side in [node.left, *node.comparators]:
                if (
                    isinstance(side, ast.Attribute)
                    and side.attr in ValidationCode.__members__
                ):
                    compared.add(side.attr)
    #: ``_UNKNOWN_CODES`` 집합의 멤버도 간접적으로 읽히므로 함께 센다.
    compared |= {code.name for code in _UNKNOWN_CODES}

    assert COMPARED_MEMBERS <= compared
    #: 직접 비교되는 것은 셋뿐이다.
    direct = compared - {code.name for code in _UNKNOWN_CODES}
    assert direct <= COMPARED_MEMBERS
    #: 그리고 48개 중 대부분은 어느 쪽으로도 읽히지 않는다.
    assert len(compared) <= 8
    assert CODE_MEMBER_COUNT - len(compared) >= 40


# ======================================================================
# C · W. condition_false — M1
# ======================================================================


def test_05_condition_false_now_uses_candidate_not_eligible_in_activation_layer():
    """
    **C · W (§21 · §22): M1 을 명시적으로 잡는 negative test.**

    조건을 끝까지 보고 **거짓**을 받았는데 코드가 "이 엔진이 못 한다" 다.
    production 을 고치는 것이 아니라 **지금 이런 불일치가 있다는 사실**을
    고정한다.
    """
    false = synthetic(activation=Always(ConditionResult.FALSE))
    activated = activate(new_state(), false)

    #: 상태는 (전에도 지금도) 정확하다.
    assert activated.status is ActivationStatus.CONDITION_FALSE
    #: 상태가 "모른다" 쪽이 **아니다** — 그것이 이 자리의 핵심이었다.
    from engine.activation import _UNKNOWN_STATUSES

    assert activated.status not in _UNKNOWN_STATUSES

    #: .. note::
    #:    **Phase 3-E-38 이 고쳤다 (M1).** 원래 이 negative test 는
    #:    ``RULE_NOT_IMPLEMENTED`` (``모른다 (UNKNOWN)`` 묶음)를 고정해서
    #:    "확실한 거부에 모른다 코드가 붙어 있다" 를 드러냈다. 그 불일치가
    #:    없어졌으므로 **코드가 선언 묶음과 맞는다**는 새 사실을 고정한다.
    assert activated.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert activated.code.name not in UNKNOWN_SECTION_MEMBERS

    #: 규칙 이름을 적지 않는다 — 모르는 것이 아니기 때문이다 (그대로다).
    assert activated.missing is None


def test_06_condition_false_now_uses_candidate_not_eligible_in_resolution_layer():
    """
    **C · W (§21 · §22): M1 의 해결 계층 쌍.**

    같은 불일치가 해결 계층에도 있다. 두 계층이 **같은 태도**를 유지하므로
    (3-E-26 이 그렇게 맞췄다) 한쪽만 고치면 어긋난다.
    """
    false = synthetic(activation=Always(ConditionResult.FALSE))
    resolved = resolve(new_state(), false)

    assert resolved.status is ResolutionStatus.CONDITION_FALSE
    #: **3-E-38 이 고쳤다** — 발동 계층과 같은 코드다.
    assert resolved.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE

    #: 소스에서도 두 자리가 같은 모양임을 확인한다 — **고친 뒤에도** 같다.
    #: (한쪽만 고치면 여기서 깨진다.)
    for rel, status in (
        ("engine/activation.py", "ActivationStatus.CONDITION_FALSE"),
        ("engine/effect/executor.py", "ResolutionStatus.CONDITION_FALSE"),
    ):
        source = source_of(rel)
        index = source.index(status)
        window = source[index : index + 260]
        assert "ValidationCode.CANDIDATE_NOT_ELIGIBLE" in window, rel


def test_07_the_trigger_and_action_layers_now_agree_on_the_same_fact():
    """
    **L (§21): Trigger vs Action/Resolution 비교.**

    같은 "조건이 거짓" 을 트리거 계층은 ``CANDIDATE_NOT_ELIGIBLE`` 로
    적는다 (3-E-26). 즉 M1 은 **정보 부족이 아니라 선택의 불일치**다.
    """
    view = view_of(new_state())
    refused = TriggerCollector(
        view, TriggerRegistry((watching(Always(ConditionResult.FALSE)),))
    ).collect(drawn_event())
    assert list(refused), "후보가 하나는 나와야 비교할 수 있다."
    for candidate in refused:
        assert candidate.status is TriggerStatus.INELIGIBLE
        assert candidate.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE

    #: .. note::
    #:    **3-E-38 이 맞췄다.** 원래 이 자리는 "두 계층의 코드가 **다르다** —
    #:    같은 사실인데" 를 고정했다. 이제 **같다.**
    activated = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))
    assert activated.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert activated.code is not ValidationCode.RULE_NOT_IMPLEMENTED


# ======================================================================
# D · F · X. source forbidden — M2
# ======================================================================


def test_08_source_forbidden_now_uses_execution_forbidden_in_action_layer():
    """
    **D · X (§21 · §22): M2 를 명시적으로 잡는 negative test.**

    ADR-004 출처 금지인데 코드가 "미구현" 이다. 발동·해결 둘 다.
    """
    forbidden = synthetic(
        activation=None, provenance=EffectProvenance.text_derived("공식 텍스트에서 유추")
    )
    activated = activate(new_state(), forbidden)
    resolved = resolve(new_state(), forbidden)

    assert activated.status is ActivationStatus.FORBIDDEN
    assert resolved.status is ResolutionStatus.FORBIDDEN
    #: **3-E-38 이 고쳤다 (M2).** 원래 이 negative test 는
    #: ``RULE_NOT_IMPLEMENTED`` 를 고정해 불일치를 드러냈다.
    assert activated.code is ValidationCode.EXECUTION_FORBIDDEN
    assert resolved.code is ValidationCode.EXECUTION_FORBIDDEN
    assert activated.code is not ValidationCode.RULE_NOT_IMPLEMENTED


def test_09_the_enum_created_execution_forbidden_for_exactly_this_case():
    """
    **F (§21): ``EXECUTION_FORBIDDEN`` 의 docstring 이 M2 를 위해 쓰여 있다.**

    "출처가 실행을 금지한다 (``TEXT_DERIVED``, ADR-004). ``INVALID`` 중에서도
    **따로 구분한다** — '조건이 거짓' 과 '이 근거로는 절대 실행하지 않는다'
    는 전혀 다른 말이고 …"

    즉 M2 가 "더 정확한 코드가 없어서" 생긴 것이 **아니다.**
    """
    docs = member_docstrings()
    forbidden = docs["EXECUTION_FORBIDDEN"]
    assert "출처가 실행을 금지한다" in forbidden
    assert "TEXT_DERIVED" in forbidden and "ADR-004" in forbidden
    assert "따로 구분한다" in forbidden
    assert "조건이 거짓" in forbidden

    #: **이제 세 계층이 모두 그것을 쓴다** (3-E-38). 원래 이 자리는
    #: "발동·해결 계층은 쓰지 않는다" 를 고정했다.
    for rel in (
        "engine/trigger.py",
        "engine/activation.py",
        "engine/effect/executor.py",
    ):
        assert "ValidationCode.EXECUTION_FORBIDDEN" in source_of(rel), rel


def test_10_source_forbidden_is_a_different_code_from_structural_source_forbidden():
    """
    **D (§21): ``SOURCE_FORBIDDEN`` 과 혼동하지 않는다.**

    ``SOURCE_FORBIDDEN`` 은 **구조 (INVALID)** 묶음이고 "행위에 ``source``
    를 적으면 안 되는데 적었다" 는 뜻이다 — provenance 와 무관하다.
    M2 의 정확한 코드는 ``EXECUTION_FORBIDDEN`` 이다.
    """
    sections = declared_sections()
    assert "SOURCE_FORBIDDEN" in sections["구조 (INVALID)"]
    assert "EXECUTION_FORBIDDEN" in sections["우선권 · 응답 기회 (Phase 2-F-1)"]
    assert ValidationCode.SOURCE_FORBIDDEN is not ValidationCode.EXECUTION_FORBIDDEN

    #: ``SOURCE_FORBIDDEN`` 은 한 자리에서만 나온다 — 구조 검사다.
    hits = [
        (str(path.relative_to(PROJECT_ROOT)), node.lineno)
        for path in production_files()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and node.attr == "SOURCE_FORBIDDEN"
    ]
    assert hits == [("engine/action_validation.py", 201)]


# ======================================================================
# M3 — 이번에 새로 찾은 것
# ======================================================================


def test_11_event_relation_attaches_this_code_to_an_invalid_gate():
    """
    **M3: ``_event_relation`` 이 ``INVALID`` 관문에 "미구현" 을 붙인다.**

    "이 선언은 그 사건에 반응하지 않는다" 는 **확실하고 올바른 거부**다 —
    엔진이 못 하는 것이 아니다. 3-E-36 은 이 자리를 "진짜 미구현" 으로
    분류했는데 **틀렸다.**
    """
    state = new_state()
    view = view_of(state)
    event = drawn_event()
    definition = watched_definition(activation=None)

    #: 사건이 맞는 선언으로 후보를 하나 만든다.
    collection = TriggerCollector(
        view,
        TriggerRegistry((watching(None),)),
        definitions=EffectDefinitionRegistry((definition,)),
    ).collect(event)
    candidate = list(collection)[0]

    #: 그리고 **사건이 맞지 않는** 선언으로 공개 메서드 ``judge`` 를 부른다.
    mismatched = TriggerSpec(
        WATCHED,
        TimingPoint.LIFE_CHANGED,
        condition=None,
        activates_from=frozenset({Zone.HAND, Zone.MZONE}),
    )
    judge = TriggerEligibilityJudge(view, EffectDefinitionRegistry((definition,)))
    eligibility = judge.judge(candidate, mismatched, event)

    gates = {
        verdict.gate: (verdict.validity, verdict.code) for verdict in eligibility.blocking
    }
    assert EligibilityGate.EVENT_RELATION in gates
    validity, code = gates[EligibilityGate.EVENT_RELATION]
    #: **확실한 거부인데 "모른다" 쪽 코드다.**
    assert validity is ActionValidity.INVALID
    assert code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert code.name in UNKNOWN_SECTION_MEMBERS


def test_12_refusal_code_picks_up_m3_against_its_own_docstring():
    """
    **M3 의 결과 — ``_refusal_code`` 가 자기 docstring 을 어기게 된다.**

    그 함수는 "자리가 틀려서 막힌 후보에 ``RULE_NOT_IMPLEMENTED`` 를 적으면
    '엔진이 못 한다' 와 '규칙이 막았다' 가 다시 섞인다" 고 적어 두었고,
    기본값으로 ``CANDIDATE_NOT_ELIGIBLE`` 을 돌려준다. 그런데
    ``_event_relation`` 이 그 코드를 ``INVALID`` 관문에 붙여 두었으므로
    **첫 번째 ``INVALID`` 관문의 코드**로 그것이 올라간다.
    """
    doc = _refusal_code.__doc__ or ""
    assert "확실한 거부" in doc
    assert "RULE_NOT_IMPLEMENTED" in doc
    assert "다시 섞인다" in doc
    #: 기본값이 정확한 코드다 — 즉 저장소가 답을 이미 알고 있다.
    assert "ValidationCode.CANDIDATE_NOT_ELIGIBLE" in source_of(
        "engine/trigger_chain.py"
    )

    state = new_state()
    view = view_of(state)
    definition = watched_definition(activation=None)
    candidate = list(
        TriggerCollector(
            view,
            TriggerRegistry((watching(None),)),
            definitions=EffectDefinitionRegistry((definition,)),
        ).collect(drawn_event())
    )[0]
    mismatched = TriggerSpec(
        WATCHED,
        TimingPoint.LIFE_CHANGED,
        condition=None,
        activates_from=frozenset({Zone.HAND, Zone.MZONE}),
    )
    eligibility = TriggerEligibilityJudge(
        view, EffectDefinitionRegistry((definition,))
    ).judge(candidate, mismatched, drawn_event())

    #: **지금 상태를 고정한다** — 거부인데 "미구현" 이 올라간다.
    assert _refusal_code(eligibility) is ValidationCode.RULE_NOT_IMPLEMENTED
    assert _refusal_code(eligibility) is not ValidationCode.CANDIDATE_NOT_ELIGIBLE


def test_13_undecided_code_is_not_affected_because_it_filters_to_unknown():
    """
    **왜 ``_undecided_code`` 는 멀쩡한가.** ``validity is UNKNOWN`` 인 관문만
    걸러 보기 때문이다 — ``INVALID`` 관문이 섞여 들어올 수 없다.

    같은 파일의 두 함수가 **다르게 방어한다**: 하나는 필터로 막고 (안전),
    하나는 첫 ``INVALID`` 를 그대로 올린다 (M3 에 노출).
    """
    doc = _undecided_code.__doc__ or ""
    assert "``UNKNOWN`` 관문만 본다" in doc
    source = source_of("engine/trigger_chain.py")
    assert "verdict.validity is ActionValidity.UNKNOWN" in source
    assert "verdict.validity is ActionValidity.INVALID" in source


# ======================================================================
# E · G · H. 다른 코드들과의 구분 / status·code 조합
# ======================================================================


def test_14_candidate_not_eligible_is_declared_in_the_cost_section():
    """
    **E (§21): ``CANDIDATE_NOT_ELIGIBLE`` 의 선언 위치를 정직하게 적는다.**

    docstring 은 "고른 카드가 후보 조건을 만족하지 않는다" 이고 섹션은
    **비용 · 선택 (Phase 2-C)** 다. 즉 트리거 계층이 "조건 거짓" 에 쓰는
    것은 **다른 묶음에서 빌려 온 것**이다 — 완벽한 맞춤이 아니다.

    그래도 M1·M3 에 쓸 수 있는 가장 가까운 기존 코드이고, 저장소가 이미
    그렇게 쓰고 있다.
    """
    sections = declared_sections()
    assert "CANDIDATE_NOT_ELIGIBLE" in sections["비용 · 선택 (Phase 2-C)"]
    docs = member_docstrings()
    assert "고른 카드가 후보 조건을 만족하지 않는다" in docs["CANDIDATE_NOT_ELIGIBLE"]

    #: "발동 조건이 거짓이다" 를 뜻하는 전용 멤버는 **없다**.
    assert "CONDITION_FALSE" not in ValidationCode.__members__
    assert "ACTIVATION_CONDITION_FALSE" not in ValidationCode.__members__


def test_15_information_unavailable_stays_separate_everywhere():
    """
    **G (§21): ``INFORMATION_UNAVAILABLE`` 과의 분리.**

    같은 ``UNKNOWN`` 묶음 안에서도 까닭이 갈린다. 네 계층 모두
    ``missing_rules()`` 에게 되묻는다.
    """
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    assert rule.status is info.status is ActivationStatus.CONDITION_UNKNOWN
    assert rule.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE

    #: 둘 다 ``모른다 (UNKNOWN)`` 묶음이다 — 묶음은 같고 멤버가 다르다.
    assert {"RULE_NOT_IMPLEMENTED", "INFORMATION_UNAVAILABLE"} <= (
        UNKNOWN_SECTION_MEMBERS
    )


def test_16_the_status_carries_the_decision_and_the_code_carries_the_reason():
    """
    **H · §14: status 가 최종 판정, code 가 원인이다.**

    ``permits_execution`` · ``activated`` · ``gives_a_future`` 가 전부
    **상태**만 본다. 코드가 판정을 뒤집는 자리가 없다.
    """
    #: 같은 코드, 다른 판정 — 3-E-38 뒤에는 **조건 거짓이 아니라** 정의
    #: 미등록과 규칙 미구현이 그 짝이다.
    unknown = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))
    assert unknown.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert false.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert false.status is not unknown.status

    #: 허가 판단은 상태만 본다.
    assert ValidationResult.unknown(
        ValidationCode.RULE_NOT_IMPLEMENTED, ""
    ).permits_execution is False
    assert ValidationResult.valid("되었다").permits_execution is True

    #: ``permits_execution`` 이 ``validity`` 만 읽는다 (AST).
    tree = ast.parse(source_of("engine/validation.py"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "permits_execution":
            body = _unparse(node.body[-1])
            assert "validity" in body
            assert "code" not in body


# ======================================================================
# I. ValidationResult 계약
# ======================================================================


def test_17_validation_result_has_five_fields_not_seven():
    """
    **I (§21) · §13 의 전제를 고친다.**

    ``ValidationResult`` 는 ``validity`` · ``code`` · ``reason`` ·
    ``missing_rule`` · ``notes`` **다섯 칸**이다. ``value`` 와
    ``ordering_key`` 는 **``SearchCandidate``** 의 것이고 이 타입에 없다.
    """
    names = [f.name for f in dataclasses.fields(ValidationResult)]
    assert names == ["validity", "code", "reason", "missing_rule", "notes"]
    assert "value" not in names
    assert not hasattr(ValidationResult, "ordering_key")

    #: 그 둘은 탐색 쪽에 있다.
    assert "value" in [f.name for f in dataclasses.fields(SearchCandidate)]
    assert hasattr(SearchCandidate, "ordering_key")

    #: 네 칸이 함께 의미를 완성한다 — 코드 하나가 다 짊어지지 않는다.
    verdict = ValidationResult.unknown(
        ValidationCode.RULE_NOT_IMPLEMENTED,
        "아직 구현하지 않은 규칙이 걸려 있습니다.",
        missing_rule="tribute-summon (제물 선택 · 릴리스)",
        notes=("레벨 10 이라 제물이 필요합니다",),
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule and verdict.notes
    assert verdict.reason


def test_18_the_indirect_path_into_invalid_exists_but_is_closed_by_construction():
    """
    **§9 의 새 발견 — 3-E-36 의 "0건" 을 정밀하게 고친다.**

    ``_check_requirements`` 는 조건이 ``FALSE`` 면 ``requirement.code`` 를
    **``ValidationResult.invalid`` 에 그대로** 넘긴다. 이 코드를 든
    ``Requirement`` 가 3개 있으므로 간접 경로가 **구조적으로는 있다.**

    그런데 셋의 조건이 **모두 ``FALSE`` 를 내지 않는다** —
    ``UnimplementedRule`` ×2 는 언제나 ``UNKNOWN`` 이고,
    ``_NormalSpellActivation`` 은 ``TRUE``/``UNKNOWN`` 만 낸다. 그래서
    닫혀 있다. **타입이 막는 것이 아니라 조건의 성질이 막는다.**
    """
    source = source_of("engine/action_validation.py")
    assert "return ValidationResult.invalid(requirement.code, requirement.detail)" in (
        source
    )

    #: 이 코드를 든 ``Requirement`` 생성처를 **그 조건과 함께** 센다.
    #: 수만 세면 조건을 바꿔치기한 변경을 놓친다 — 고의 위반이 그 구멍을
    #: 찾았다. 그래서 **각 carrier 의 조건 종류**를 고정한다.
    carriers: list[tuple[int, str]] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Requirement"
            and "RULE_NOT_IMPLEMENTED" in _unparse(node)
        ):
            continue
        condition = node.args[0] if node.args else None
        kind = (
            condition.func.id
            if isinstance(condition, ast.Call) and isinstance(condition.func, ast.Name)
            else _unparse(condition)
        )
        carriers.append((node.lineno, kind))
    assert len(carriers) == REQUIREMENT_CARRIERS

    #: **조건 종류가 둘뿐이다** — 둘 다 ``FALSE`` 를 내지 않는 것들이다.
    kinds = sorted(kind for _, kind in carriers)
    assert kinds == ["UnimplementedRule", "UnimplementedRule", "scope"], kinds

    #: 그 둘이 정말 ``FALSE`` 를 내지 않는지 실제로 돌려 본다.
    from engine.action_validation import _NormalSpellActivation
    from engine.condition import ConditionContext

    view = view_of(new_state())
    context = ConditionContext(player=MINE)
    assert UnimplementedRule("x").evaluate(view, context) is ConditionResult.UNKNOWN
    #: ``UnimplementedRule`` 은 판을 보지 않고 언제나 ``UNKNOWN`` 이다.
    assert UnimplementedRule("x").evaluate(None, None) is ConditionResult.UNKNOWN
    scope = _NormalSpellActivation(None).evaluate(view, context)
    assert scope in {ConditionResult.TRUE, ConditionResult.UNKNOWN}
    assert scope is not ConditionResult.FALSE
    #: ``_NormalSpellActivation.evaluate`` 의 본문에 ``FALSE`` 가 **없다**.
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "_NormalSpellActivation":
            body = next(
                stmt
                for stmt in node.body
                if isinstance(stmt, ast.FunctionDef) and stmt.name == "evaluate"
            )
            assert "ConditionResult.FALSE" not in _unparse(body)

    #: 소스도 그 사실을 적어 둔다.
    assert "이 조건은 ``FALSE`` 를 **돌려주지 않는다**" in source


# ======================================================================
# J · K. GateVerdict / ActionValidator
# ======================================================================


def test_19_gate_verdict_reads_only_execution_forbidden():
    """
    **J (§21): ``GateVerdict`` 가 코드를 읽는 유일한 방식.**

    ``forbids`` 가 ``EXECUTION_FORBIDDEN`` 하나만 본다. 그래서 M2 가
    발동·해결 계층에 있어도 **그 독자는 영향을 받지 않는다** — 다른
    타입이기 때문이다.
    """
    from engine.trigger import GateVerdict

    doc = GateVerdict.forbids.__doc__ or ""
    assert "출처가 실행을 금지했는가" in doc
    assert "self.result.code is ValidationCode.EXECUTION_FORBIDDEN" in source_of(
        "engine/trigger.py"
    )

    #: 발동·해결 결과는 ``GateVerdict`` 가 아니다.
    forbidden = synthetic(
        activation=None, provenance=EffectProvenance.text_derived("유추")
    )
    result = activate(new_state(), forbidden)
    assert not isinstance(result, GateVerdict)
    assert not hasattr(result, "forbids")


@requires_official_db
@pytest.mark.real_card
def test_20_the_action_validator_keeps_the_declared_grouping(repository):
    """
    **K (§21): ``ActionValidator`` 는 선언된 묶음을 지킨다.**

    실제 판에서 종류별로 물어보면, ``INVALID`` 에는 ``INVALID`` 묶음의
    코드가, ``UNKNOWN`` 에는 ``UNKNOWN`` 묶음의 코드가 붙는다.
    """
    deck = [card.id for card in list(repository.all_cards())[:12]]
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=5)
    while duel.advance() is not None:
        pass
    seat = duel.to_act
    validator = ActionValidator(duel.view(seat))
    source = duel.state.player(seat).hand[0].instance_id

    sections = declared_sections()
    invalid_members = set(sections["구조 (INVALID)"]) | set(
        sections["판 위의 사실 (INVALID)"]
    )

    checked = 0
    for build in (
        PlayerAction.normal_summon,
        PlayerAction.set_monster,
        PlayerAction.set_spell_trap,
        PlayerAction.activate_card,
        PlayerAction.special_summon,
    ):
        verdict = validator.validate(build(actor=seat, source=source))
        checked += 1
        if verdict.validity is ActionValidity.UNKNOWN:
            assert verdict.code.name in UNKNOWN_SECTION_MEMBERS, verdict.code
        if verdict.validity is ActionValidity.INVALID:
            #: ``INVALID`` 쪽은 다른 계층 묶음도 쓸 수 있으나, **``UNKNOWN``
            #: 묶음의 코드는 쓰지 않는다.**
            assert verdict.code.name not in UNKNOWN_SECTION_MEMBERS, verdict.code
    assert checked == 5


# ======================================================================
# M · N · O. Effect / Cost / Target
# ======================================================================


def test_21_the_effect_layer_is_where_the_grouping_breaks_most():
    """
    **M (§21): 효과 실행 계층.**

    22곳 중 ``INVALID_CONTEXT`` ×4 · ``INVALID_OPERATION`` ×2 ·
    ``FORBIDDEN`` · ``CONDITION_FALSE`` · ``EXECUTION_ERROR`` 가 선언된
    묶음과 어긋난다. 그 상태 이름들이 코드보다 **더 정확하다.**
    """
    source = source_of("engine/effect/executor.py")
    statuses = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if "RULE_NOT_IMPLEMENTED" not in _unparse(node):
            continue
        first = node.args[0]
        if isinstance(first, ast.Attribute) and _unparse(first.value) == (
            "ResolutionStatus"
        ):
            statuses.add(first.attr)

    #: 3-E-38 이 ``FORBIDDEN`` 과 ``CONDITION_FALSE`` 를 지웠다 — 남은 셋은
    #: **맞는 ``ValidationCode`` 가 없어서** 그대로다.
    assert {
        "INVALID_CONTEXT",
        "INVALID_OPERATION",
        "EXECUTION_ERROR",
    } <= statuses
    assert "FORBIDDEN" not in statuses
    assert "CONDITION_FALSE" not in statuses
    assert {"UNSUPPORTED_OPERATION", "UNCHECKED_RULES", "NOT_IMPLEMENTED"} <= statuses
    #: 상태 이름이 코드보다 정확하다 — 그것이 "새 코드가 필요없다" 의 근거다.
    for name in ("INVALID_CONTEXT", "EXECUTION_ERROR", "UNSUPPORTED_OPERATION"):
        assert name in ResolutionStatus.__members__
        assert name not in ValidationCode.__members__


def test_22_the_cost_and_target_layers_use_their_own_codes():
    """
    **N · O (§21): 비용 · 대상 계층.**

    둘 다 이 코드를 빌리지 않는다. ``engine/cost/`` 는
    ``COST_NOT_IMPLEMENTED`` 를, 대상 계층은 ``CANDIDATE_NOT_ELIGIBLE`` ·
    ``TOO_FEW_SELECTED`` 를 쓴다.
    """
    for path in sorted((PROJECT_ROOT / "engine" / "cost").rglob("*.py")):
        assert "RULE_NOT_IMPLEMENTED" not in path.read_text(encoding="utf-8"), path

    targeting = source_of("engine/effect/targeting.py")
    assert "RULE_NOT_IMPLEMENTED" not in targeting
    assert "CANDIDATE_NOT_ELIGIBLE" in targeting

    sections = declared_sections()
    assert "COST_NOT_IMPLEMENTED" in sections["비용 · 선택 (Phase 2-C)"]


# ======================================================================
# P · Q. Simulation / AI
# ======================================================================


def test_23_the_simulation_boundary_reads_five_codes_and_preserves_them():
    """
    **P · Q (§21): ``SimulationStatus`` 매핑.**

    ``_UNKNOWN_CODES`` 가 다섯 코드를 ``UNKNOWN`` 으로 보낸다. 거부 코드는
    **하나도 들어 있지 않다** — 그래서 M1·M3 가 고쳐지면 그 수들이
    ``REFUSED`` 로 옮겨 간다.
    """
    assert {code.name for code in _UNKNOWN_CODES} == {
        "RULE_NOT_IMPLEMENTED",
        "COST_NOT_IMPLEMENTED",
        "INFORMATION_UNAVAILABLE",
        "CARD_DEFINITION_UNAVAILABLE",
        "EFFECT_LIST_UNRELIABLE",
    }
    for name in ("CANDIDATE_NOT_ELIGIBLE", "EXECUTION_FORBIDDEN", "OK"):
        assert getattr(ValidationCode, name) not in _UNKNOWN_CODES

    #: 네 코드 중 넷이 ``모른다 (UNKNOWN)`` 묶음이고 하나는 비용 묶음이다.
    assert len({code.name for code in _UNKNOWN_CODES} & UNKNOWN_SECTION_MEMBERS) == 4


def test_24_unknown_is_neither_zero_nor_a_loss_and_ranks_the_same_as_refused():
    """
    **Q (§21) · §20-6/10: AI 쪽 invariant.**

    오분류 때문에 확실한 거부가 ``UNKNOWN`` 으로 보고되지만, **순위가
    같으므로 선택이 바뀌지 않는다.**
    """
    action = PlayerAction.passing(actor=MINE)
    unknown = SearchCandidate(action=action, status=SimulationStatus.UNKNOWN)
    refused = SearchCandidate(action=action, status=SimulationStatus.REFUSED)
    assert unknown.value is refused.value is None
    assert unknown.ordering_key() == refused.ordering_key()
    assert unknown.ordering_key()[0] == 1
    assert unknown.comparable is False

    #: ``agent/`` 가 이 코드를 읽는 자리는 하나다.
    hits = sum(
        path.read_text(encoding="utf-8").count("RULE_NOT_IMPLEMENTED")
        for path in sorted((PROJECT_ROOT / "agent").rglob("*.py"))
    )
    assert hits == 1


# ======================================================================
# R. hidden information
# ======================================================================


def test_25_hidden_information_never_becomes_this_code():
    """
    **R (§21) · §18: 가려진 정보가 "미구현" 으로 바뀌지 않는다.**

    네 코드가 따로 있고 실측에서도 그렇다.
    """
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert info.unchecked and "관측에 보이지 않음" in info.unchecked[0]

    docs = member_docstrings()
    assert "가려진 것일 수 있다" in docs["HIDDEN_CARD"]
    for name in (
        "HIDDEN_CARD",
        "INFORMATION_UNAVAILABLE",
        "CARD_DEFINITION_UNAVAILABLE",
        "EFFECT_LIST_UNRELIABLE",
    ):
        assert getattr(ValidationCode, name) is not ValidationCode.RULE_NOT_IMPLEMENTED


# ======================================================================
# S · T. production reachability / dormant
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_26_m1_and_m2_reach_the_duel_boundary_but_m3_is_dormant(repository):
    """
    **S · T (§21): 도달 여부를 가른다.**

    M1·M2 는 발동기를 지나 ``DuelStep.code`` 까지 간다. M3 는 트리거
    파이프라인 안이고 그 파이프라인은 **production 에서 ``TriggerSpec`` 을
    하나도 만들지 않는다.**
    """
    #: M3 의 dormancy — production 에서 ``TriggerSpec(...)`` 생성이 없다.
    production = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel.startswith(("tests/", ".venv", "build")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "TriggerSpec"
            ):
                production.append(f"{rel}:{node.lineno}")
    assert production == []

    #: M1·M2 는 발동기의 코드가 그대로 전달된다.
    assert "DuelStep(action, False, activated.code, activated.reason)" in source_of(
        "engine/duel.py"
    )

    deck = [card.id for card in list(repository.all_cards())[:12]]
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=5)
    while duel.advance() is not None:
        pass
    seat = duel.to_act
    before = duel.state.state_hash()
    step = duel.apply(
        PlayerAction.special_summon(
            actor=seat, source=duel.state.player(seat).hand[0].instance_id
        )
    )
    assert step.accepted is False
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert duel.state.state_hash() == before


# ======================================================================
# U · V. 기존 코드로 되는가 / 새 코드가 필요한가
# ======================================================================


def test_27_every_mismatch_is_expressible_with_an_existing_code():
    """
    **U (§21): 세 불일치 모두 기존 코드로 표현된다.**

    | 불일치 | 정확한 기존 코드 |
    |---|---|
    | M1 조건 거짓 | ``CANDIDATE_NOT_ELIGIBLE`` (트리거 계층이 이미 쓴다) |
    | M2 출처 금지 | ``EXECUTION_FORBIDDEN`` (docstring 이 이 경우를 위해 쓰여 있다) |
    | M3 사건 불일치 | ``CANDIDATE_NOT_ELIGIBLE`` (``_refusal_code`` 의 기본값이다) |

    즉 **새 enum 없이 고칠 수 있다.**
    """
    for name in ("CANDIDATE_NOT_ELIGIBLE", "EXECUTION_FORBIDDEN"):
        assert name in ValidationCode.__members__

    #: 저장소가 이미 그 둘을 쓴다 — 가정이 아니다.
    trigger = source_of("engine/trigger.py")
    assert "code=ValidationCode.CANDIDATE_NOT_ELIGIBLE" in trigger
    assert "ValidationCode.EXECUTION_FORBIDDEN" in trigger
    assert "ValidationCode.CANDIDATE_NOT_ELIGIBLE" in source_of(
        "engine/trigger_chain.py"
    )


def test_28_no_new_code_is_required_because_the_status_already_carries_it():
    """
    **V (§21) · §12: 새 코드 후보 판정 — 일곱 조건 중 셋이 빠진다.**

    코드가 없는 10곳(구조 오류 · 예외 · 멤버십 거절)에 대해:

    - 조건 3 "``status`` 만으로도 의미를 잃는다" → **거짓.** 상태 이름이
      정확하다 (``INVALID_CONTEXT`` · ``EXECUTION_ERROR``).
    - 조건 4 "consumer 가 그 차이를 필요로 한다" → **거짓.** 45개 코드가
      한 번도 읽히지 않는다 (``test_04``).
    - 조건 6 "기존 ADR/TODO 로 설명 안 됨" → **거짓.** 3-E-26 이 같은
      문제를 설명하고 고친 기록이 있다.

    그래서 ``NEW_CODE_CANDIDATE`` 가 **0개**다.
    """
    #: 상태 쪽에는 정확한 이름이 있고 코드 쪽에는 없다.
    for name in ("INVALID_CONTEXT", "EXECUTION_ERROR", "UNSUPPORTED_OPERATION"):
        assert name in ResolutionStatus.__members__
        assert name not in ValidationCode.__members__

    #: 그리고 enum 은 늘지 않았다 — 이 Phase 가 아무것도 더하지 않았다.
    assert len(ValidationCode) == CODE_MEMBER_COUNT


# ======================================================================
# §20. safety invariant 열두 항목
# ======================================================================


def test_29_all_twelve_safety_invariants_hold():
    """
    **§20: 열두 항목.** "자동 변환" 은 하나도 없다 — 불일치는 **변환이
    아니라 처음부터의 선택**이다.
    """
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))

    #: 1 · 2 · 3 · 4 — 코드가 서로 다른 멤버이고 변환 함수가 없다.
    for name in (
        "INFORMATION_UNAVAILABLE",
        "EXECUTION_FORBIDDEN",
        "CANDIDATE_NOT_ELIGIBLE",
    ):
        assert getattr(ValidationCode, name) is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE

    #: 5 — 코드가 판정을 거짓으로 바꾸지 않는다.
    assert rule.status is ActivationStatus.CONDITION_UNKNOWN
    assert false.status is ActivationStatus.CONDITION_FALSE

    #: 6 · 10 — 패배도 0점도 아니다.
    action = PlayerAction.passing(actor=MINE)
    assert SearchCandidate(action=action, status=SimulationStatus.UNKNOWN).value is None

    #: 7 · 8 — 허가도 적격도 되지 않는다.
    assert ValidationResult.unknown(
        ValidationCode.RULE_NOT_IMPLEMENTED, ""
    ).permits_execution is False
    for result in (false, rule, info):
        assert result.status is not ActivationStatus.ACTIVATED
        assert len(result.chain) == 0

    #: 9 — 가려진 정보 변환 없음 (``test_25``).
    assert ValidationCode.HIDDEN_CARD is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: 11 — ``GateVerdict`` 가 이 코드를 금지로 바꾸지 않는다.
    from engine.trigger import GateVerdict

    assert "EXECUTION_FORBIDDEN" in (
        source_of("engine/trigger.py").split("def forbids")[1][:200]
    )

    #: 12 — 트리거와 발동 계층이 "조건 거짓" 에 **다른** 코드를 쓴다.
    #: 충돌이 아니라 **불일치**다 — 두 코드를 읽는 공통 consumer 가 없다.
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE not in _UNKNOWN_CODES
    assert ValidationCode.RULE_NOT_IMPLEMENTED in _UNKNOWN_CODES


# ======================================================================
# Y. regression
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_30_real_corpus_rejection_codes_span_several_groups(repository):
    """
    **§19: 실제 카드 corpus.** 한 판을 돌려 거부 코드를 모은다.

    여러 묶음의 코드가 나오면 이 코드 하나가 전부를 삼키지 않는다는 뜻이다.
    """
    deck = [card.id for card in list(repository.all_cards())[:16]]
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=11)
    seen: set[ValidationCode] = set()

    for _ in range(60):
        if duel.is_over:
            break
        if duel.advance() is not None:
            continue
        legal = duel.legal_actions()
        if not legal.allowed:
            break
        seen.add(duel.apply(legal.allowed[0]).code)
        hand = duel.state.player(duel.to_act).hand
        if hand:
            for build in (PlayerAction.special_summon, PlayerAction.activate_card):
                seen.add(
                    duel.apply(
                        build(actor=duel.to_act, source=hand[0].instance_id)
                    ).code
                )

    assert len(seen) >= 2, seen
    assert ValidationCode.OK in seen
    assert ValidationCode.RULE_NOT_IMPLEMENTED in seen


def test_31_the_distinctions_from_phase_3e24_to_3e36_still_hold():
    """**Y (§21) · §21 regression.**"""
    assert ConditionResult.UNKNOWN is not ConditionResult.FALSE
    assert ActionValidity.UNKNOWN is not ActionValidity.INVALID
    assert ActivationStatus.CONDITION_UNKNOWN is not ActivationStatus.CONDITION_FALSE
    assert ResolutionStatus.CONDITION_UNKNOWN is not ResolutionStatus.CONDITION_FALSE

    #: enum 크기가 하나도 늘지 않았다.
    assert len(ValidationCode) == 48
    assert len(ConditionResult) == 3
    assert len(ActionValidity) == 3
    assert len(SimulationStatus) == 5
    assert len(TimingPoint) == 8

    #: 거부 생성 수가 측정값과 맞는다 (3-E-38 뒤 56).
    assert len(rejection_productions()) == REJECTION_PRODUCTIONS
