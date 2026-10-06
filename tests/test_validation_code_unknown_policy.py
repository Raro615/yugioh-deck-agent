r"""
Phase 3-E-40 — ``ValidationCode`` UNKNOWN policy 정식화의 회귀 시험.

Phase 3-E-39 가 측정한 것: ``agent/simulation.py`` 의 ``_UNKNOWN_CODES`` 는
48개 중 5개를 **손으로 고른 사본**이고, ``ValidationResult`` 가 실제로
``UNKNOWN`` 과 함께 생산하는 코드는 **7개**였다. 빠진 둘은 ``HIDDEN_CARD`` ·
``PRIORITY_STATE_STALE``. 그리고 "어느 코드가 모름인가" 를 적은 자리가 **둘**
이었다 — enum 의 묶음 **주석**(기계가 못 읽는다)과 agent 의 **리터럴 집합**.

이 Phase 가 한 것
----------------
원본을 기계가 읽을 수 있게 적었다. ``engine.validation.CODE_VALIDITY`` 가
48개 **전부**를 기존 :class:`ActionValidity` 어휘로 분류하고, agent 의 집합은
거기서 **파생**된다. 새 enum · 새 멤버는 하나도 만들지 않았다.

이 파일이 지키는 것
------------------
1. policy 가 **총함수**다 — 멤버를 더하고 분류를 빠뜨리면 import 가 깨진다
2. policy 가 **production 과 어긋나지 않는다** — ``unknown`` 으로 생산되는
   코드와 policy 가 말하는 집합이 같고(``test_09``), ``invalid`` 쪽도 같다
   (``test_10``), 묶음 주석과도 같다(``test_11``)
3. **사본이 돌아오지 않는다** — agent 계층에 코드 리터럴이 0개다(``test_19``)
4. **행동이 바뀌지 않았다** — 판 · 난수 · 순위 · 가려진 정보 · 탐색 결정이
   전부 그대로다(``test_21`` ~ ``test_27``)
"""

import ast
import dataclasses
import pathlib

import pytest

from agent.search import SearchCandidate, SearchPolicy
from agent.simulation import SimulationStatus, Simulator, _UNKNOWN_CODES
from engine.action import PlayerAction
from engine.activation import ActivationStatus
from engine.condition import Always, ConditionResult, IsMonster, UnimplementedRule
from engine.duel import Duel, DuelStep, WithheldAction
from engine.effect import EffectProvenance
from engine.effect.resolution import ResolutionStatus
from engine.ids import InstanceId
from engine.validation import (
    CODE_VALIDITY,
    ActionValidity,
    ValidationCode,
    ValidationResult,
    codes_declaring,
    unknown_codes,
)

from tests.conftest import requires_official_db
from tests.test_validation_code_consistency import (
    activate,
    new_state,
    resolve,
    synthetic,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MINE = 0
PROD_PREFIXES = ("engine/", "agent/", "core/", "analysis/", "sources/", "app/")

#: Phase 3-E-39 가 측정한 **기존** 다섯. 이 Phase 가 그것을 지우지 않았다.
FIVE_BEFORE = frozenset(
    {
        "RULE_NOT_IMPLEMENTED",
        "COST_NOT_IMPLEMENTED",
        "INFORMATION_UNAVAILABLE",
        "CARD_DEFINITION_UNAVAILABLE",
        "EFFECT_LIST_UNRELIABLE",
    }
)

#: 이 Phase 가 **측정으로** 더한 둘.
ADDED_BY_MEASUREMENT = frozenset({"HIDDEN_CARD", "PRIORITY_STATE_STALE"})

#: 분류를 비워 둔 코드 — "정할 수 없다" 이고 "모른다" 가 아니다.
UNCLASSIFIABLE = frozenset({"CHAIN_DEFINITION_UNAVAILABLE"})


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def production_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel.startswith(PROD_PREFIXES):
            yield rel, path


def validity_productions() -> dict[str, set[str]]:
    """
    production 이 ``ValidationResult`` 에 **직접 선언한** validity 를 코드별로.

    문자열 검색이 아니라 AST 다 — ``as`` 별명을 붙인 import 를 놓치지 않는다.
    """
    members = set(ValidationCode.__members__)
    found: dict[str, set[str]] = {}
    for rel, path in production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func, args, validity = node.func, list(node.args), None
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in ("ValidationResult", "_VR")
            ):
                validity = {"unknown": "UNKNOWN", "invalid": "INVALID", "valid": "VALID"}.get(
                    func.attr
                )
            elif isinstance(func, ast.Name) and func.id == "ValidationResult":
                if args and isinstance(args[0], ast.Attribute):
                    if args[0].attr in ActionValidity.__members__:
                        validity = args[0].attr
                        args = args[1:]
            if validity is None:
                continue
            for arg in args:
                if isinstance(arg, ast.Attribute) and arg.attr in members:
                    found.setdefault(arg.attr, set()).add(validity)
                    break
    return found


def section_labels() -> dict[str, str | None]:
    """enum 의 묶음 주석이 ``(INVALID)`` · ``(UNKNOWN)`` 로 적은 라벨."""
    labels: dict[str, str | None] = {}
    current: str | None = None
    for line in source_of("engine/validation.py").splitlines():
        stripped = line.strip()
        if stripped.startswith("# ---"):
            current = (
                "INVALID"
                if "(INVALID)" in stripped
                else "UNKNOWN"
                if "(UNKNOWN)" in stripped
                else None
            )
        for name in ValidationCode.__members__:
            if stripped.startswith(f"{name} = "):
                labels[name] = current
    return labels


def forbidden_definition():
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
# 1 ~ 4 — enum 과 policy 의 모양
# ======================================================================


def test_01_the_enum_still_has_exactly_forty_eight_members():
    """**§17-1: 멤버 수가 그대로다.**"""
    assert len(ValidationCode) == 48
    #: 그리고 ``str`` enum 이라는 성질도 그대로다 — policy 가 멤버를 만들지 않았다.
    assert issubclass(ValidationCode, str)


def test_02_no_new_member_was_added_and_none_was_renamed():
    """
    **§17-2 · §0: 새 멤버 0 · 이름 변경 0 · 삭제 0.**

    AST 로 enum 본문의 할당을 세어 **구문으로** 확인한다 — 문자열을 세면
    enum 밖의 상수까지 걸린다 (3-E-39 에서 실제로 틀렸다).
    """
    tree = ast.parse(source_of("engine/validation.py"))
    classes = {
        node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
    }
    declared = [
        stmt.targets[0].id
        for stmt in classes["ValidationCode"].body
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant)
    ]
    assert len(declared) == 48
    assert declared == list(ValidationCode.__members__)
    #: 값도 이름의 소문자형 그대로다.
    for name in declared:
        assert ValidationCode[name].value == name.lower()


def test_03_the_policy_lives_next_to_the_enum_not_in_the_agent_layer():
    """
    **§17-3 · §8: policy source 가 엔진에 있다.**

    의미를 **만드는 곳**이 그것을 선언한다. 소비하는 쪽(``agent``)이 선언하면
    소비자가 늘 때마다 사본이 늘고, 그것이 3-E-39 가 찾은 문제였다.
    """
    validation = source_of("engine/validation.py")
    assert "CODE_VALIDITY" in validation
    assert "def unknown_codes()" in validation
    assert "def codes_declaring(" in validation

    #: agent 는 **읽기만** 한다.
    simulation = source_of("agent/simulation.py")
    assert "CODE_VALIDITY" not in simulation
    assert "unknown_codes()" in simulation


def test_04_the_policy_is_total_and_breaks_at_import_if_a_member_is_missed():
    """
    **§17-4 · §16-8: 빠뜨릴 수 없는 구조다.**

    policy 가 48개 **전부**를 다루고, 빠지면 **import 할 때** 터지는 검사가
    소스에 있다. 집합이 조용히 낡던 바로 그 길을 막는다.
    """
    assert set(CODE_VALIDITY) == set(ValidationCode)
    assert len(CODE_VALIDITY) == 48

    #: 검사가 실제로 있는지 구문으로 확인한다.
    source = source_of("engine/validation.py")
    assert "_UNCLASSIFIED = set(ValidationCode) - set(CODE_VALIDITY)" in source
    assert "raise RuntimeError" in source

    #: 그리고 그 검사가 **정말 터지는지** 재현한다 — production 을 고치지 않고
    #: 같은 식을 여기서 평가한다.
    pretend_missing = set(ValidationCode) - (set(CODE_VALIDITY) - {ValidationCode.OK})
    assert pretend_missing == {ValidationCode.OK}


def test_05_the_policy_speaks_only_in_the_existing_three_value_vocabulary():
    """
    **§0 · §9: 새 enum 을 만들지 않았다.**

    분류의 값은 기존 :class:`ActionValidity` 세 값과 ``None`` 뿐이다.
    ``None`` 은 **"이 코드만으로는 정할 수 없다"** 이고 "모른다" 와 다르다.
    """
    assert len(ActionValidity) == 3
    allowed = set(ActionValidity) | {None}
    assert set(CODE_VALIDITY.values()) <= allowed
    #: 세 값과 ``None`` 이 모두 실제로 쓰인다 — 쓰지 않는 값을 두지 않았다.
    assert set(CODE_VALIDITY.values()) == allowed


# ======================================================================
# 5 ~ 8 — UNKNOWN 집합과 두 추가 멤버
# ======================================================================


def test_06_the_unknown_policy_has_exactly_seven_members():
    """**§17-5: policy 가 모름으로 선언하는 코드 전체.**"""
    assert {code.name for code in unknown_codes()} == FIVE_BEFORE | ADDED_BY_MEASUREMENT
    assert len(unknown_codes()) == 7


def test_07_all_five_earlier_members_are_still_unknown():
    """
    **§17-6 · §9: 기존 다섯 중 빠진 것이 없다.**

    이 Phase 는 집합을 **다시 쓰지 않았다** — 측정으로 둘을 더했을 뿐이다.
    다섯 중 하나라도 빠지면 그것은 의미 변경이고 이 Phase 의 범위가 아니다.
    """
    names = {code.name for code in unknown_codes()}
    assert FIVE_BEFORE <= names
    for name in FIVE_BEFORE:
        assert CODE_VALIDITY[ValidationCode[name]] is ActionValidity.UNKNOWN, name


def test_08_hidden_card_is_unknown_and_three_kinds_of_evidence_agree():
    """
    **§17-7: ``HIDDEN_CARD`` 는 모름이다** — 추측이 아니라 세 근거가 모두 같다.

    1. production 이 ``ValidationResult.unknown`` 으로만 생산한다
    2. enum 의 묶음 주석이 ``(UNKNOWN)`` 이다 — 그 묶음의 **첫 멤버**다
    3. 설명이 "**없다는 뜻이 아니다** — 가려진 것일 수 있다" 고 적는다
    """
    code = ValidationCode.HIDDEN_CARD
    assert CODE_VALIDITY[code] is ActionValidity.UNKNOWN
    assert validity_productions()["HIDDEN_CARD"] == {"UNKNOWN"}
    assert section_labels()["HIDDEN_CARD"] == "UNKNOWN"
    assert "가려진 것일 수 있다" in source_of("engine/validation.py")

    #: 가려진 정보를 **거절로 접지 않는다** — 이 Phase 의 요지다.
    hidden = ValidationResult.unknown(code, "가려졌다")
    assert hidden.validity is ActionValidity.UNKNOWN
    assert hidden.is_structural_failure is False
    assert code in _UNKNOWN_CODES


def test_09_priority_state_stale_is_unknown_because_its_own_note_says_so():
    """
    **§17-8: ``PRIORITY_STATE_STALE`` 도 모름이다.**

    설명이 직접 적는다 — "``INVALID`` 가 아니라 ``UNKNOWN`` 에 쓴다". 그리고
    production 도 그대로 한다 (``ValidationResult(UNKNOWN, …)`` 한 자리).
    """
    code = ValidationCode.PRIORITY_STATE_STALE
    assert CODE_VALIDITY[code] is ActionValidity.UNKNOWN
    assert validity_productions()["PRIORITY_STATE_STALE"] == {"UNKNOWN"}
    assert "``INVALID`` 가 아니라 ``UNKNOWN`` 에 쓴다" in source_of("engine/validation.py")
    assert code in _UNKNOWN_CODES


# ======================================================================
# 9 ~ 11 — policy 와 production 이 어긋나지 않는다 (drift 감지)
# ======================================================================


def test_10_every_code_produced_as_unknown_is_declared_unknown():
    """
    **§17-9 · §19: policy 가 production 과 정확히 같다.**

    ``ValidationResult.unknown(...)`` 또는 ``ValidationResult(UNKNOWN, …)`` 로
    생산되는 코드 집합과 policy 가 모름이라고 하는 집합이 **같다.**

    이것이 이 Phase 의 핵심 장치다 — 누군가 새 자리에서 어떤 코드를
    ``unknown`` 으로 생산하기 시작하면, policy 에 적지 않는 한 **여기서
    깨진다.** 3-E-39 가 손으로 찾아낸 어긋남을 앞으로는 테스트가 찾는다.
    """
    produced = {
        name
        for name, validities in validity_productions().items()
        if validities == {"UNKNOWN"}
    }
    declared = {code.name for code in unknown_codes()}
    assert produced == declared == FIVE_BEFORE | ADDED_BY_MEASUREMENT


def test_11_no_code_is_produced_with_two_different_validities():
    """
    **§10: "코드의 semantic" 과 "이번 결과의 validity" 가 어긋나지 않는다.**

    policy 가 코드 → 판정의 **함수**로 성립하려면, 같은 코드가 두 판정으로
    생산되는 자리가 없어야 한다. 측정 결과 **그런 코드는 없다** — 그래서
    함수로 적을 수 있었다.
    """
    for name, validities in validity_productions().items():
        assert len(validities) == 1, (name, validities)


def test_12_every_code_produced_as_invalid_is_declared_invalid():
    """
    **§17-10 역방향: 반대쪽도 어긋나지 않는다.**

    ``invalid(...)`` 로 생산되는 코드를 policy 가 모름이라고 하면, 거부가
    조용히 모름이 된다. 그 길도 막는다.
    """
    for name, validities in validity_productions().items():
        if validities == {"INVALID"}:
            assert CODE_VALIDITY[ValidationCode[name]] is ActionValidity.INVALID, name
        if validities == {"VALID"}:
            assert CODE_VALIDITY[ValidationCode[name]] is ActionValidity.VALID, name


def test_13_the_section_comments_are_now_a_checked_fact():
    """
    **§8: 주석이 **검사되는** 사실이 되었다.**

    묶음 주석이 ``(INVALID)`` · ``(UNKNOWN)`` 라벨을 붙인 멤버는 policy 도 같은
    말을 한다. 전에는 주석이 기계가 못 읽는 자리에 있어서 집합과 어긋나도
    아무도 몰랐다.
    """
    labels = section_labels()
    labelled = {name: label for name, label in labels.items() if label is not None}
    assert len(labelled) == 28  # 구조 11 · 판 위의 사실 12 · 모른다 5
    for name, label in labelled.items():
        declared = CODE_VALIDITY[ValidationCode[name]]
        assert declared is ActionValidity[label], (name, label, declared)


def test_14_a_real_unknown_result_carries_a_code_the_policy_calls_unknown():
    """
    **§17-10: policy → ``ValidationResult.UNKNOWN`` 연결을 실행으로 확인한다.**

    소스 분석만이 아니라 실제로 엔진을 돌려 본다.
    """
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    for result in (rule, info):
        assert result.status is ActivationStatus.CONDITION_UNKNOWN
        assert CODE_VALIDITY[result.code] is ActionValidity.UNKNOWN
        assert result.code in _UNKNOWN_CODES


# ======================================================================
# 11 ~ 16 — 섞지 않는다
# ======================================================================


def test_15_unknown_is_not_false():
    """**§17-11 · §29-1: 모름은 거짓이 아니다.**"""
    unknown = ValidationResult.unknown(ValidationCode.RULE_NOT_IMPLEMENTED, "모른다")
    assert unknown.permits_execution is False
    assert unknown.is_structural_failure is False
    with pytest.raises(TypeError):
        bool(unknown)
    #: 조건 계층에서도 세 값이 그대로다.
    assert len(ConditionResult) == 3
    assert ConditionResult.UNKNOWN is not ConditionResult.FALSE


def test_16_unknown_is_not_invalid():
    """**§17-12 · §29-2: 모름은 확정 거부가 아니다.**"""
    assert ActionValidity.UNKNOWN is not ActionValidity.INVALID
    unknown_set = codes_declaring(ActionValidity.UNKNOWN)
    invalid_set = codes_declaring(ActionValidity.INVALID)
    assert unknown_set & invalid_set == frozenset()
    assert len(unknown_set) == 7
    assert len(invalid_set) == 39


def test_17_unknown_is_not_a_loss_and_not_a_zero_score():
    """**§17-13 · §29-3 · 4 · 5: 모름도 거절도 패배가 아니다.**"""
    action = PlayerAction.passing(actor=MINE)
    for status in (SimulationStatus.UNKNOWN, SimulationStatus.REFUSED):
        candidate = SearchCandidate(action=action, status=status)
        assert candidate.value is None
        assert candidate.comparable is False
    assert not hasattr(SimulationStatus.UNKNOWN, "winner")


def test_18_rule_not_implemented_keeps_its_meaning():
    """
    **§17-14 · §6: ``RULE_NOT_IMPLEMENTED`` 가 항상 모름인지 확인했다.**

    자동으로 가정하지 않았다 — production 생산이 ``unknown`` 뿐이고, enum 의
    묶음도 ``(UNKNOWN)`` 이고, 설명이 "이 엔진이 아직 못 한다" 고 적는다.

    .. note::
       3-E-36 이 이 코드를 **확정 거부에 붙인** 자리 13곳을 기록해 두었다.
       그것은 ``ValidationResult`` 가 아니라 다른 carrier 들이므로 이 policy 의
       근거(1번)에는 들어오지 않는다. policy 는 "코드의 뜻" 을 적고, 그 13곳은
       "그 뜻을 잘못 쓴 자리" 로 따로 남아 있다 — 섞지 않는다.
    """
    code = ValidationCode.RULE_NOT_IMPLEMENTED
    assert CODE_VALIDITY[code] is ActionValidity.UNKNOWN
    assert validity_productions()["RULE_NOT_IMPLEMENTED"] == {"UNKNOWN"}
    assert section_labels()["RULE_NOT_IMPLEMENTED"] == "UNKNOWN"


def test_19_candidate_not_eligible_semantics_are_preserved():
    """**§17-15 · §29-6: 3-E-38 의 M1 이 그대로이고 policy 는 확정 거부라 한다.**"""
    false = synthetic(activation=Always(ConditionResult.FALSE))
    assert activate(new_state(), false).code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert resolve(new_state(), false).code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert (
        CODE_VALIDITY[ValidationCode.CANDIDATE_NOT_ELIGIBLE] is ActionValidity.INVALID
    )
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE not in _UNKNOWN_CODES


def test_20_execution_forbidden_semantics_are_preserved():
    """**§17-16 · §29-7: M2 도 그대로이고 모름이 아니다.**"""
    forbidden = forbidden_definition()
    assert activate(new_state(), forbidden).code is ValidationCode.EXECUTION_FORBIDDEN
    assert resolve(new_state(), forbidden).code is ValidationCode.EXECUTION_FORBIDDEN
    assert CODE_VALIDITY[ValidationCode.EXECUTION_FORBIDDEN] is ActionValidity.INVALID
    assert ValidationCode.EXECUTION_FORBIDDEN not in _UNKNOWN_CODES


# ======================================================================
# 17 ~ 20 — 사본이 돌아오지 않는다
# ======================================================================


def test_21_the_agent_set_is_derived_not_written_by_hand():
    """
    **§11 · §17-3: 이중 source 가 사라졌다.**

    ``agent/simulation.py`` 에 ``ValidationCode.<멤버>`` 리터럴이 **하나도
    없다.** 전에는 다섯 줄이 있었고 그것이 사본이었다.
    """
    tree = ast.parse(source_of("agent/simulation.py"))
    literals = [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "ValidationCode"
        and node.attr in ValidationCode.__members__
    ]
    assert literals == []
    #: 파생이라는 것이 한 줄로 보인다.
    assert "_UNKNOWN_CODES: frozenset[ValidationCode] = unknown_codes()" in source_of(
        "agent/simulation.py"
    )


def test_22_only_one_place_in_production_enumerates_the_unknown_codes():
    """
    **§19: UNKNOWN 집합을 손으로 적은 자리가 production 에 하나뿐이다.**

    ``engine/validation.py`` 의 policy 가 그 하나다. 다른 곳에서 모름 코드를
    셋 이상 한꺼번에 나열하는 자리가 생기면 사본이 돌아왔다는 뜻이다.
    """
    unknown_names = {code.name for code in unknown_codes()}
    offenders = []
    for rel, path in production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Set, ast.Tuple, ast.List, ast.Dict)):
                continue
            elements = node.keys if isinstance(node, ast.Dict) else node.elts
            names = {
                e.attr
                for e in elements
                if isinstance(e, ast.Attribute) and e.attr in unknown_names
            }
            if len(names) >= 3:
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == ["engine/validation.py:" + str(
        next(
            node.lineno
            for node in ast.walk(ast.parse(source_of("engine/validation.py")))
            if isinstance(node, ast.Dict)
            and len(
                {
                    k.attr
                    for k in node.keys
                    if isinstance(k, ast.Attribute) and k.attr in unknown_names
                }
            )
            >= 3
        )
    )], offenders


def test_23_the_unclassifiable_code_is_explicit_and_is_not_unknown():
    """
    **§7 · §17-5: 정하지 못한 것을 모름으로 밀어 넣지 않았다.**

    ``CHAIN_DEFINITION_UNAVAILABLE`` 은 두 생성 자리가 서로 다른 말을 한다
    (``ChainInsertion.UNKNOWN`` ↔ ``ChainResolutionStatus.INVALID_CHAIN_LINK``).
    그래서 분류를 **비워 두었고**, 비워 둔 것은 모름 집합에 들어가지 않는다 —
    이 Phase 전의 동작과 같다.
    """
    assert {code.name for code in codes_declaring(None)} == UNCLASSIFIABLE
    for name in UNCLASSIFIABLE:
        code = ValidationCode[name]
        assert CODE_VALIDITY[code] is None
        assert code not in _UNKNOWN_CODES
        assert code not in codes_declaring(ActionValidity.UNKNOWN)
        assert code not in codes_declaring(ActionValidity.INVALID)

    #: 두 자리가 정말 다른 말을 하는지 소스에서 확인한다.
    assert "ChainInsertion.UNKNOWN" in source_of("engine/trigger_chain.py")
    assert "ChainResolutionStatus.INVALID_CHAIN_LINK" in source_of("engine/chain.py")


def test_24_the_four_buckets_partition_the_enum_without_a_remainder():
    """**분류가 48 을 남김없이 나눈다: 1 + 39 + 7 + 1.**"""
    valid = codes_declaring(ActionValidity.VALID)
    invalid = codes_declaring(ActionValidity.INVALID)
    unknown = codes_declaring(ActionValidity.UNKNOWN)
    undecided = codes_declaring(None)
    assert (len(valid), len(invalid), len(unknown), len(undecided)) == (1, 39, 7, 1)
    assert len(valid | invalid | unknown | undecided) == 48 == len(ValidationCode)
    assert valid == frozenset({ValidationCode.OK})


# ======================================================================
# 21 ~ 27 — 행동이 바뀌지 않았다
# ======================================================================


def test_25_the_simulation_statuses_are_untouched():
    """**§17-20 · §14: ``SimulationStatus`` 를 건드리지 않았다.**"""
    assert len(SimulationStatus) == 5
    assert {s.name for s in SimulationStatus} == {
        "SUPPORTED",
        "NOT_A_CANDIDATE",
        "UNKNOWN",
        "REFUSED",
        "ERROR",
    }
    #: ``gives_a_future`` 가 그대로다 (3-E-39 가 ``is_usable`` 이 없다고 기록).
    for status in SimulationStatus:
        assert status.gives_a_future is (status is SimulationStatus.SUPPORTED)


def test_26_ordering_keys_are_untouched():
    """**§17-18: 순위 키가 상태를 보지 않는다 — 전과 같다.**"""
    action = PlayerAction.passing(actor=MINE)
    keys = {
        status: SearchCandidate(action=action, status=status).ordering_key()
        for status in list(SimulationStatus) + [None]
    }
    assert len(set(keys.values())) == 1
    assert next(iter(keys.values())) == (1, 0, 0, action.canonical_state())


def test_27_the_duel_step_and_withheld_action_shapes_are_untouched():
    """**§17-25 · 26 · §15: 두 자료형을 건드리지 않았다.**"""
    assert {f.name for f in dataclasses.fields(DuelStep)} == {
        "action",
        "accepted",
        "code",
        "reason",
        "result",
    }
    assert {f.name for f in dataclasses.fields(WithheldAction)} == {
        "kind",
        "reason",
        "missing",
    }


def test_28_the_trigger_pipeline_is_still_dormant():
    """**§29-17: 트리거 파이프라인을 연결하지 않았다.**"""
    constructed = []
    for rel, path in production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("TriggerSpec", "TriggerRegistry")
            ):
                constructed.append(f"{rel}:{node.lineno}")
    assert constructed == []
    assert "trigger" not in source_of("engine/duel.py")


@requires_official_db
def test_29_the_board_and_the_randomness_do_not_move(repository):
    """**§17-22 · 23 · §29-12 · 13: ``state_hash`` 와 RNG 가 그대로다.**"""
    duel = small_duel(repository)
    simulator = Simulator(duel)
    before_hash = duel.state.state_hash()
    before_draws = duel.state.randomness.draws
    seat = duel.to_act
    SearchPolicy().attach(simulator).decide(duel.view(seat), duel.legal_actions(seat))
    assert duel.state.state_hash() == before_hash
    assert duel.state.randomness.draws == before_draws
    #: 3-E-39 가 적은 그 해시다 — policy 를 바꿔도 판은 움직이지 않는다.
    assert before_hash == (
        "d1d66338781bdb9565557f06c6e4b1357900471c8bce8f319d0807407939be40"
    )


@requires_official_db
def test_30_the_search_decision_is_byte_identical_to_before(repository):
    """
    **§17-19 · §13 · §22: 탐색 결정이 그대로다.**

    3-E-40 전의 측정값을 그대로 박아 둔다 — 후보 1개 · 상태 ``supported`` ·
    순위 키 ``(1, 0, 0, …)`` 가 아니라 점수 있는 키 · 고른 수 ``end_phase P0``.
    """
    duel = small_duel(repository)
    simulator = Simulator(duel)
    policy = SearchPolicy().attach(simulator)
    seat = duel.to_act
    chosen = policy.decide(duel.view(seat), duel.legal_actions(seat))
    decision = policy.decisions[-1]

    assert str(chosen) == "end_phase P0"
    assert len(decision.candidates) == 1
    assert decision.simulations == 1
    assert [c.status for c in decision.candidates] == [SimulationStatus.SUPPORTED]
    #: 점수가 있는 후보이므로 키의 첫 칸이 0 이다.
    assert decision.candidates[0].ordering_key()[0] == 0
    assert decision.candidates[0].comparable is True


@requires_official_db
def test_31_hidden_information_is_still_hidden(repository):
    """**§17-24 · §29-14: 관측 경계가 그대로다.**"""
    duel = small_duel(repository)
    simulator = Simulator(duel)
    seat = duel.to_act
    result = simulator.simulate(duel.legal_actions(seat).allowed[0], viewer=seat)
    future = result.future
    theirs = future.player(1 - seat).hand
    assert theirs.concealed is True
    assert theirs.cards == ()
    assert theirs.size == len(duel.state.player(1 - seat).hand)
    assert future.player(seat).hand.concealed is False


@requires_official_db
def test_32_a_real_duel_still_never_rejects_an_action_it_offered(repository):
    """
    **§13 · §22: policy 를 바꿔도 분기가 깨어나지 않는다.**

    모름 집합이 5 → 7 로 늘었지만, 그 집합을 읽는 분기 자체가 실제 플레이에서
    실행되지 않는다 (3-E-39 가 32판 · 11,609 걸음으로 측정했고 이 Phase 의
    BEFORE/AFTER 도 같았다). 한 판으로 그 사실을 고정한다.
    """
    duel = small_duel(repository, seed=5)
    simulator = Simulator(duel)
    steps, statuses = set(), set()
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
            statuses.add(simulator.simulate(action, viewer=seat).status)
        step = duel.apply(legal.allowed[0])
        steps.add((step.accepted, step.code))
    assert steps == {(True, ValidationCode.OK)}
    assert statuses == {SimulationStatus.SUPPORTED}


def test_33_the_only_thing_this_phase_changed_is_where_the_policy_lives():
    """
    **§22: 바뀐 것은 "source of truth" 하나다.**

    엔진에 policy 가 생기고 agent 의 사본이 없어졌다. 그 밖의 모양은 전부
    그대로다 — 멤버 수 · 상태 수 · 자료형 · 분기 한 자리.
    """
    assert len(ValidationCode) == 48
    assert len(SimulationStatus) == 5
    assert len(ActionValidity) == 3
    assert len(ResolutionStatus) == 14

    simulation = source_of("agent/simulation.py")
    #: 분기가 여전히 한 자리이고, 여전히 집합 멤버십으로 가른다.
    assert simulation.count("step.code in _UNKNOWN_CODES") == 1

    #: 두 상태를 **코드로** 쓰는 자리가 각각 하나다 — 문자열을 세면 이 Phase 가
    #: 새로 쓴 설명 문구까지 걸린다 (처음에 그렇게 세어 2 가 나왔다). 구문으로
    #: 센다.
    def member_uses(rel: str, enum_name: str) -> dict[str, int]:
        uses: dict[str, int] = {}
        for node in ast.walk(ast.parse(source_of(rel))):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == enum_name
            ):
                uses[node.attr] = uses.get(node.attr, 0) + 1
        return uses

    simulation_uses = member_uses("agent/simulation.py", "SimulationStatus")
    assert simulation_uses["UNKNOWN"] == 1
    assert simulation_uses["REFUSED"] == 1
    #: 탐색의 분기도 한 자리 그대로다.
    assert member_uses("agent/search.py", "SimulationStatus") == {"SUPPORTED": 1}
