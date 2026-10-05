"""
Phase 3-E-34 — ``engine/`` 전역 ``Condition | None`` 계약 정합성 감사.

핵심 질문: **같은 Python 타입(``Condition | None``)이 계층마다 다른 뜻을 갖는가,
그리고 그 차이가 실제 production 경로에서 충돌하는가.**

타입이 같다고 의미가 같다고 보지 않고, docstring 만 보고 안전하다고 보지도
않는다. AST 로 전수 수집하고, 각 자리의 **실제 consumer** 를 production
코드로 불러서 결과를 고정한다.

측정으로 드러난 일곱 가지
-------------------------

1. **``engine/`` 의 ``Condition | None`` 필드는 정확히 5곳이다.**
   ``CandidateSource.require`` · ``CardCost.require`` ·
   ``EffectDefinition.activation`` · ``ObservationGrant.condition`` ·
   ``TriggerSpec.condition``. (파일 65개 전수 AST.)

2. **``None`` 의 뜻이 적힌 것은 3곳, 안 적힌 것은 2곳이다.**
   비용 계층의 두 ``require`` 는 ``None`` 의 뜻을 **적지 않는다** — 다만
   `cost/resolver.py` 가 "필터 없음" 으로 읽고, 그것이 유일한 읽기다.

3. **적힌 3곳 중 2곳은 "적지 않았다", 1곳은 "조건이 없다" 다.**
   ``EffectDefinition.activation`` · ``TriggerSpec.condition`` 이 앞쪽,
   ``ObservationGrant.condition`` 이 뒤쪽이다.

4. **그런데 그 차이가 production 에서 충돌하지 않는다.**
   ``ObservationGrant`` 는 production 에서 **한 번도 생성되지 않는다**
   (생성처 5곳 전부 ``tests/``). 계약이 다른 두 값이 같은 경로에서 만나지
   않는다.

5. **"적지 않았다" 를 막는 관문이 조건 칸이 아니라 다른 자리에 있다.**
   발동기·실행기·트리거 넷 모두 ``activation`` 을 읽기 **전에** "정의가
   등록되어 있는가" 와 "출처가 금지인가" 를 먼저 묻는다. 그래서
   ``activation=None`` 은 **"사람이 등재하면서 조건이 없다고 단언한 것"**
   만 의미하게 된다.

6. **같은 이름이 ``Condition`` 이 아닌 자리도 있다.**
   ``engine/activation.py`` · ``engine/effect/executor.py`` 의 지역 변수
   ``condition`` 은 **막는 결과**(``ActivationResult | None``)이고 ``None``
   은 "막는 것이 없다" 다. ``ResponseResult.activation`` 은
   ``ActivationResult | None`` 이고 ``None`` 은 "발동 계층까지 가지 않았다"
   다. 이름이 같아도 계약이 다르다.

7. **부재를 ``None`` 없이 적는 설계가 이미 두 개 있다.**
   ``Requirement.condition`` 은 ``Condition`` (Optional 아님) — 조건이
   없으면 ``Requirement`` 자체를 만들지 않는다. ``EffectAnalysis.activation``
   은 ``ActivationCondition`` (Optional 아님) — 유무를
   ``has_condition_function`` 이라는 **다른 칸**에 적는다.

이 Phase 는 production 을 고치지 않았다. 감사다.
"""

import ast
import dataclasses
import pathlib

import pytest

from analysis.effect_model import ActivationCondition, EffectAnalysis
from engine.action import PlayerAction
from engine.action_validation import ActionValidator, Requirement
from engine.activation import ActivationStatus
from engine.condition import (
    Always,
    Condition,
    ConditionContext,
    ConditionResult,
    IsMonster,
    UnimplementedRule,
)
from engine.cost.choice import CandidateSource, CandidateSet, ChoiceSpec
from engine.cost.model import CardCost
from engine.cost.resolver import CandidateResolver
from engine.effect.definition import EffectDefinition
from engine.effect.resolution import ResolutionStatus
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.observation_grant import ObservationGrant, derive_policy
from engine.observation import ObservationPermission
from engine.trigger import TriggerSpec
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Zone

#: 발동·해결 계층을 **그대로** 부르는 기존 도구를 다시 쓴다. 새 하네스를
#: 만들면 production 이 아니라 하네스를 시험하게 된다.
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
ENGINE = PROJECT_ROOT / "engine"

MINE, THEIRS = 0, 1


# ======================================================================
# 측정값 — 전부 저장소에서 센 수다. 바뀌면 그것이 신호다.
# ======================================================================

#: ``engine/`` 의 ``Condition | None`` **필드** 전수.
#: ``(파일, 클래스, 필드)`` — 줄 번호는 넣지 않는다 (줄이 밀려도 계약은 같다).
CONDITION_OPTIONAL_FIELDS = {
    ("engine/cost/choice.py", "CandidateSource", "require"),
    ("engine/cost/model.py", "CardCost", "require"),
    ("engine/effect/definition.py", "EffectDefinition", "activation"),
    ("engine/observation_grant.py", "ObservationGrant", "condition"),
    ("engine/trigger.py", "TriggerSpec", "condition"),
}

#: ``Condition`` 을 **반드시** 받는 자리 (Optional 이 아니다).
CONDITION_REQUIRED_FIELDS = {
    ("engine/action_validation.py", "Requirement", "condition"),
    ("engine/condition/model.py", "And", "children"),
    ("engine/condition/model.py", "Or", "children"),
    ("engine/condition/model.py", "Not", "child"),
}

#: ``engine/`` 의 ``*.py`` 파일 수. 전수 주사의 분모다.
ENGINE_FILE_COUNT = 65

#: 조건·요구·발동 이름에 대한 ``None`` 검사 수. ``engine/`` **패키지만** 센다
#: (``tests/engine/`` 까지 세면 분모가 오염된다 — 한 번 틀렸던 자리다).
NONE_CHECKS = {"is None": 4, "is not None": 23}

#: ``None`` 을 **특별히 처리하는** 네 자리.
NONE_BRANCHES = {
    ("engine/activation.py", "activation"),
    ("engine/effect/executor.py", "activation"),
    ("engine/cost/resolver.py", "require"),
    ("engine/response.py", "activation"),
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


def engine_files() -> list[pathlib.Path]:
    return sorted(ENGINE.rglob("*.py"))


def annotated_fields(predicate):
    """
    ``engine/`` 의 모든 dataclass 필드 주석을 훑어 ``predicate`` 가 참인 것만.

    문자열 검색이 아니라 AST 다 — 주석이나 docstring 의 같은 글자를 세지
    않는다. 돌려주는 것은 ``(상대경로, 클래스, 필드, 주석, 기본값)``.
    """
    found = []
    for path in engine_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if not (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                ):
                    continue
                annotation = _unparse(stmt.annotation)
                if not predicate(annotation, stmt.target.id):
                    continue
                default = (
                    _unparse(stmt.value) if stmt.value is not None else "<없음>"
                )
                found.append((rel, node.name, stmt.target.id, annotation, default))
    return found


def field_docstring(path: str, class_name: str, field_name: str) -> str:
    """dataclass **필드**의 docstring. 없으면 빈 문자열."""
    tree = ast.parse(source_of(path))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        body = node.body
        for index, stmt in enumerate(body):
            if not (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id == field_name
            ):
                continue
            following = body[index + 1] if index + 1 < len(body) else None
            if (
                isinstance(following, ast.Expr)
                and isinstance(following.value, ast.Constant)
                and isinstance(following.value.value, str)
            ):
                return following.value.value
            return ""
    raise AssertionError(f"{path}:{class_name}.{field_name} 를 찾지 못했습니다.")


def view_of(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=MINE)


def candidates(require, *, state=None) -> CandidateSet:
    """
    비용 계층의 **실제** 후보 해결기를 부른다. 양쪽 MZONE 을 본다.

    ``new_state()`` 는 양쪽에 몬스터를 1장씩 올려 두므로, 필터가 없으면
    후보가 2장이다.
    """
    board = state if state is not None else new_state()
    spec = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.MZONE}), owner=None, require=require
        ),
        minimum=1,
        maximum=1,
    )
    context = ConditionContext(player=MINE, source=None)
    return CandidateResolver(view_of(board)).resolve(spec, context)


def grant(condition) -> ObservationGrant:
    """
    ``ObservationGrant`` 하나. **production 에는 없는 모양이다** —
    ``test_14`` 가 그 사실 자체를 고정한다. 여기서는 계약을 시험하려고만
    만든다.
    """
    state = new_state()
    holder = state.player(MINE).monster_zone[0].instance_id
    return ObservationGrant(
        permission=ObservationPermission.REVEAL_HAND,
        source=synthetic().effect_ref,
        holder=holder,
        active_zones=frozenset({Zone.MZONE}),
        condition=condition,
    ), state


# ======================================================================
# §4 — 전수 수집
# ======================================================================


def test_01_the_optional_condition_corpus_in_engine_is_exactly_five_fields():
    """
    **§4 전수 주사.** ``engine/`` 의 ``Condition | None`` 필드는 5곳이다.

    여섯 번째가 생기면 여기서 깨진다 — 그때 그 자리의 ``None`` 이 무슨
    뜻인지 적어야 한다. 줄 번호는 고정하지 않는다 (줄이 밀려도 계약은 같다).
    """
    assert len(engine_files()) == ENGINE_FILE_COUNT

    def is_optional_condition(annotation: str, name: str) -> bool:
        text = annotation.replace(" ", "")
        if "Condition" not in text:
            return False
        if "ConditionContext" in text or "ConditionResult" in text:
            return False
        return "|None" in text or text.startswith("Optional[")

    found = {(r[0], r[1], r[2]) for r in annotated_fields(is_optional_condition)}
    assert found == CONDITION_OPTIONAL_FIELDS

    #: 다섯 자리 **모두** 기본값이 ``None`` 이다 — 즉 적지 않으면 ``None`` 이다.
    for rel, cls, name, annotation, default in annotated_fields(
        is_optional_condition
    ):
        assert annotation.replace(" ", "") == "Condition|None", (rel, cls, name)
        assert default == "None", (rel, cls, name)

    #: ``Optional[...]`` 표기는 ``engine/`` 에 **하나도 없다** — 한 가지 표기만
    #: 쓰므로 AST 주사가 빠뜨릴 변형이 없다.
    for path in engine_files():
        assert "Optional[" not in path.read_text(encoding="utf-8"), path

    #: ``None`` 검사 전수. 그리고 **참/거짓 축약은 0곳**이다 — ``if condition:``
    #: 이나 ``condition or ...`` 로 읽으면 ``Condition`` 객체의 진릿값에
    #: 기대게 되고, 그것은 ``None`` 과 ``FALSE`` 를 섞는 첫걸음이다.
    names = {"condition", "activation", "require", "requires", "predicate", "guard"}
    checks = {"is None": 0, "is not None": 0}
    shortcuts = []
    branches = set()
    for path in engine_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Compare)
                and len(node.ops) == 1
                and isinstance(node.ops[0], (ast.Is, ast.IsNot))
                and isinstance(node.comparators[0], ast.Constant)
                and node.comparators[0].value is None
            ):
                left = node.left
                attr = (
                    left.attr
                    if isinstance(left, ast.Attribute)
                    else (left.id if isinstance(left, ast.Name) else None)
                )
                if attr in names:
                    if isinstance(node.ops[0], ast.Is):
                        checks["is None"] += 1
                        branches.add((rel, attr))
                    else:
                        checks["is not None"] += 1
            for operand in (
                [node.operand]
                if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
                else list(node.values)
                if isinstance(node, ast.BoolOp)
                else []
            ):
                attr = (
                    operand.attr
                    if isinstance(operand, ast.Attribute)
                    else (operand.id if isinstance(operand, ast.Name) else None)
                )
                if attr in names:
                    shortcuts.append(f"{rel}:{node.lineno}")

    assert checks == NONE_CHECKS
    assert shortcuts == [], shortcuts
    assert branches == NONE_BRANCHES


def test_02_absence_is_also_modelled_without_optional_in_two_places():
    """
    **부재를 ``None`` 없이 적는 설계가 이미 있다.**

    ``Requirement.condition`` 은 ``Condition`` 이고 기본값이 없다 — 조건이
    없으면 **``Requirement`` 를 만들지 않는다.** ``And``/``Or``/``Not`` 도
    자식을 반드시 받는다.

    그리고 ``analysis`` 쪽 ``EffectAnalysis.activation`` 은 Optional 이
    아니다 — 유무를 ``has_condition_function`` 이라는 **다른 칸**에 적는다.
    이 두 가지가 §24 Q4 의 답을 이미 들고 있다.
    """

    def is_required_condition(annotation: str, name: str) -> bool:
        text = annotation.replace(" ", "")
        if "Condition" not in text or "ConditionContext" in text:
            return False
        if "ConditionResult" in text or "ConditionKind" in text:
            return False
        return "|None" not in text and not text.startswith("Optional[")

    found = {(r[0], r[1], r[2]) for r in annotated_fields(is_required_condition)}
    assert found == CONDITION_REQUIRED_FIELDS

    #: ``Requirement`` 는 기본값이 없다 — 조건 없는 요구를 만들 수 없다.
    condition_field = next(
        f for f in dataclasses.fields(Requirement) if f.name == "condition"
    )
    assert condition_field.default is dataclasses.MISSING
    assert condition_field.default_factory is dataclasses.MISSING
    with pytest.raises(TypeError):
        Requirement(code=ValidationCode.OK, detail="조건 없는 요구")  # type: ignore[call-arg]

    #: analysis 쪽은 Optional 이 아니고, 유무가 별도 칸이다.
    analysis_field = next(
        f for f in dataclasses.fields(EffectAnalysis) if f.name == "activation"
    )
    assert analysis_field.type == "ActivationCondition"
    assert "None" not in analysis_field.type
    assert ActivationCondition().has_condition_function is False
    assert ActivationCondition().tree is None
    assert ActivationCondition().raw is None


def test_03_three_of_the_five_document_what_none_means_and_two_do_not():
    """
    **§5 분류의 입력.** 계약이 적힌 자리와 안 적힌 자리를 가른다.

    "안 적혀 있다" 를 "문제다" 로 바로 읽지 않는다 — ``test_04`` 가 그
    두 자리의 **실제 읽기**를 production 으로 확인한다.
    """
    documented = {
        ("engine/effect/definition.py", "EffectDefinition", "activation"),
        ("engine/observation_grant.py", "ObservationGrant", "condition"),
        ("engine/trigger.py", "TriggerSpec", "condition"),
    }
    undocumented = {
        ("engine/cost/choice.py", "CandidateSource", "require"),
        ("engine/cost/model.py", "CardCost", "require"),
    }
    assert documented | undocumented == CONDITION_OPTIONAL_FIELDS

    for path, cls, name in documented:
        doc = field_docstring(path, cls, name)
        assert "None" in doc or "``None``" in doc, (path, cls, name)

    for path, cls, name in undocumented:
        doc = field_docstring(path, cls, name)
        assert doc.strip(), f"{cls}.{name} 에는 docstring 이 있다"
        #: 있지만 ``None`` 을 말하지 않는다.
        assert "None" not in doc, (path, cls, name)


# ======================================================================
# Test 1 (§16) — ``None`` = 조건 없음 인 계층
# ======================================================================


def test_04_in_the_cost_layer_none_means_no_filter():
    """
    **Test 1 (§16): ``None`` = 조건 없음 인 계층 = 비용 후보 계층.**

    ``cost/resolver.py`` 가 ``source.require is None`` 이면 **보이는 카드
    전부**를 후보로 돌려준다. 즉 ``None`` 은 "추가 제약 없음" 이다 —
    필터 칸에서 유일하게 말이 되는 읽기다.

    그리고 "모르면 후보가 아니다" 가 유지된다 — ``UnimplementedRule`` 은
    ``eligible`` 이 아니라 ``undecided`` 로 간다.
    """
    #: ``None`` → 양쪽 몬스터 2장이 전부 확정 후보.
    unfiltered = candidates(None)
    assert unfiltered.certain_count == 2
    assert unfiltered.has_undecided is False

    #: 거짓 조건 → 후보 0, **모르는 것도 0**.
    refused = candidates(Always(ConditionResult.FALSE))
    assert refused.certain_count == 0
    assert refused.has_undecided is False

    #: 규칙이 없어서 모름 → 확정 0, **미확정 2**. 모름을 허가로 접지 않는다.
    undecided = candidates(UnimplementedRule("아직 없는 규칙"))
    assert undecided.certain_count == 0
    assert undecided.has_undecided is True
    assert len(undecided.undecided) == 2
    assert any("아직 없는 규칙" in reason for reason in undecided.reasons)

    #: 세 결과가 **서로 다르다** — ``None`` 이 ``FALSE`` 도 ``UNKNOWN`` 도 아니다.
    shapes = {
        (c.certain_count, c.has_undecided)
        for c in (unfiltered, refused, undecided)
    }
    assert len(shapes) == 3

    #: 팩토리를 통해도 같다 — ``CardCost.release(1)`` 은 ``require=None``.
    assert CardCost.release(1).require is None
    assert CardCost.release(1, require=Always()).require is not None


# ======================================================================
# Test 2 (§16) — ``None`` = 아직 공급되지 않았음 인 계층
# ======================================================================


def test_05_in_action_validation_a_none_context_means_not_provided_yet():
    """
    **Test 2 (§16): ``None`` = 아직 공급되지 않았음.**

    ``ActionValidator.validate(action, context=None)`` 의 ``None`` 은
    "조건 문맥이 없다" 가 아니라 **"아직 안 건넸으니 내가 만든다"** 다.
    실제로 ``context_for(action)`` 과 같은 결과를 낸다.

    이것은 ``Condition | None`` 이 아니라 ``ConditionContext | None`` 이고,
    **같은 ``None`` 이 전혀 다른 계약을 갖는다**는 §6 의 예다.
    """
    state = new_state()
    validator = ActionValidator(view_of(state))
    action = PlayerAction.passing(actor=MINE)

    implicit = validator.validate(action)
    explicit = validator.validate(action, validator.context_for(action))

    assert implicit.canonical_state() == explicit.canonical_state()

    #: 주석이 ``Condition`` 이 아니다 — 이름만 비슷하다.
    tree = ast.parse(source_of("engine/action_validation.py"))
    found = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef,)) and node.name == "validate":
            for arg in node.args.args + node.args.kwonlyargs:
                if arg.arg == "context" and arg.annotation is not None:
                    found = _unparse(arg.annotation)
    assert found == "ConditionContext | None"


# ======================================================================
# Test 3·4 (§16) — UNKNOWN 과 FALSE
# ======================================================================


def test_06_an_unknown_condition_keeps_its_own_verdict_in_every_layer():
    """
    **Test 3 (§16): ``UNKNOWN`` condition.**

    네 계층이 전부 ``UNKNOWN`` 을 그대로 들고 있고, 까닭(규칙 없음 /
    정보 없음)까지 가른다. 3-E-24~26 이 세운 것이 그대로다.
    """
    #: 발동 · 해결 — 규칙이 없어서 모른다.
    missing_rule = synthetic(activation=UnimplementedRule("아직 없는 규칙"))
    assert activate(new_state(), missing_rule).status is (
        ActivationStatus.CONDITION_UNKNOWN
    )
    assert activate(new_state(), missing_rule).code is (
        ValidationCode.RULE_NOT_IMPLEMENTED
    )
    assert resolve(new_state(), missing_rule).status is (
        ResolutionStatus.CONDITION_UNKNOWN
    )

    #: 발동 — 정보가 없어서 모른다. **같은 UNKNOWN, 다른 까닭.**
    no_info = synthetic(activation=IsMonster(InstanceId(9999)))
    assert activate(new_state(), no_info).status is (
        ActivationStatus.CONDITION_UNKNOWN
    )
    assert activate(new_state(), no_info).code is (
        ValidationCode.INFORMATION_UNAVAILABLE
    )

    #: 비용 후보 — 미확정으로 간다 (``test_04`` 와 같은 사실).
    assert candidates(UnimplementedRule("아직 없는 규칙")).has_undecided is True

    #: 관측 권한 — 권한이 **생기지 않는다**.
    declaration, state = grant(UnimplementedRule("아직 없는 규칙"))
    assert derive_policy(state, (declaration,)).permissions == ()


def test_07_a_false_condition_is_a_refusal_not_a_missing_rule():
    """
    **Test 4 (§16): ``FALSE`` condition.**

    ``FALSE`` 는 ``UNKNOWN`` 과 **다른 칸**이고, 네 계층이 모두 그렇다.
    """
    false = synthetic(activation=Always(ConditionResult.FALSE))
    assert activate(new_state(), false).status is ActivationStatus.CONDITION_FALSE
    assert resolve(new_state(), false).status is ResolutionStatus.CONDITION_FALSE

    #: 비용 후보 — 미확정이 **아니다**. 확실한 거부다.
    refused = candidates(Always(ConditionResult.FALSE))
    assert refused.certain_count == 0 and refused.has_undecided is False

    #: 관측 권한 — 거짓도 ``UNKNOWN`` 도 권한이 아니지만, 같은 칸이 아니다.
    declaration, state = grant(Always(ConditionResult.FALSE))
    assert derive_policy(state, (declaration,)).permissions == ()

    #: 참이면 권한이 생긴다 — 셋이 **서로 다른 결과**임을 확인한다.
    declaration, state = grant(Always())
    assert len(derive_policy(state, (declaration,)).permissions) == 1


# ======================================================================
# Test 5·6 (§16) — None 이 UNKNOWN 으로도 FALSE 로도 바뀌지 않는다
# ======================================================================


def test_08_none_is_never_turned_into_unknown():
    """
    **Test 5 (§16): ``None`` → ``UNKNOWN`` 변환이 없다.**

    ``activation=None`` 인 정의는 발동·해결 둘 다 **통과**한다. 조건 칸이
    비었다는 이유로 ``CONDITION_UNKNOWN`` 을 만들지 않는다.

    ``ObservationGrant`` 도 같다 — ``condition=None`` 이면 조건 평가를
    아예 건너뛰고 권한이 **생긴다**.
    """
    silent = synthetic(activation=None)
    activated = activate(new_state(), silent)
    assert activated.status is ActivationStatus.ACTIVATED
    assert activated.status is not ActivationStatus.CONDITION_UNKNOWN
    assert resolve(new_state(), silent).status is not (
        ResolutionStatus.CONDITION_UNKNOWN
    )

    declaration, state = grant(None)
    assert len(derive_policy(state, (declaration,)).permissions) == 1

    assert candidates(None).has_undecided is False


def test_09_none_is_never_turned_into_false():
    """
    **Test 6 (§16): ``None`` → ``FALSE`` 변환이 없다.**

    ``None`` 과 ``Always(FALSE)`` 가 **다른 결과**를 낸다. 같은 결과를
    내면 "안 적은 것" 과 "거짓" 이 구분되지 않는다.
    """
    silent = activate(new_state(), synthetic(activation=None))
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))

    assert silent.status is ActivationStatus.ACTIVATED
    assert false.status is ActivationStatus.CONDITION_FALSE
    assert silent.status is not false.status

    assert candidates(None).certain_count == 2
    assert candidates(Always(ConditionResult.FALSE)).certain_count == 0


# ======================================================================
# Test 7 (§16) — Condition 객체가 전달될 때 의미가 보존된다
# ======================================================================


def test_10_a_condition_object_keeps_its_meaning_across_the_boundary():
    """
    **Test 7 (§16): ``Condition`` 이 전달될 때 의미 유지.**

    같은 ``Condition`` 객체를 다섯 자리에 넣고, 직렬화
    (``canonical_state``)가 **같은 값**을 내는지 본다. 계층을 지나면서
    조건이 다른 것으로 바뀌면 여기서 깨진다.
    """
    condition = UnimplementedRule("아직 없는 규칙")
    expected = condition.canonical_state()

    definition = synthetic(activation=condition)
    assert definition.activation is condition
    assert definition.canonical_state()[3] == expected

    spec = TriggerSpec(
        definition.effect_ref,
        __import__("engine.trigger", fromlist=["TimingPoint"]).TimingPoint.CARD_DRAWN,
        condition=condition,
        activates_from=frozenset({Zone.HAND}),
    )
    assert spec.condition is condition
    assert spec.canonical_state()[-1] == expected

    source = CandidateSource(zones=frozenset({Zone.MZONE}), require=condition)
    assert source.canonical_state()[2] == expected

    cost = CardCost.release(1, require=condition)
    assert cost.require is condition

    declaration, _ = grant(condition)
    assert declaration.condition is condition
    assert declaration.canonical_state()[-1] == expected


# ======================================================================
# Test 8 (§16) — 두 계약이 **반대**다
# ======================================================================


def test_11_activation_and_observation_grant_document_opposite_contracts():
    """
    **Test 8 (§16): ``EffectDefinition.activation`` 과
    ``ObservationGrant.condition`` 의 ``None`` 뜻이 다르다.**

    어느 쪽이 맞다고 주장하지 않는다 — 두 계약이 같은 저장소에 함께
    적혀 있다는 **사실**을 고정한다 (3-E-33 의 중심 발견).

    그리고 ``TriggerSpec.condition`` 이 어느 편인지도 함께 적는다 —
    ``activation`` 과 **같은 편**이고, 그래서 트리거 계층이 정의의
    ``activation`` 까지 함께 본다.
    """
    activation = field_docstring(
        "engine/effect/definition.py", "EffectDefinition", "activation"
    )
    observation = field_docstring(
        "engine/observation_grant.py", "ObservationGrant", "condition"
    )
    trigger = field_docstring("engine/trigger.py", "TriggerSpec", "condition")

    #: 타입과 기본값이 같다.
    for owner, name in (
        (EffectDefinition, "activation"),
        (ObservationGrant, "condition"),
        (TriggerSpec, "condition"),
    ):
        field = next(f for f in dataclasses.fields(owner) if f.name == name)
        assert field.type == "Condition | None"
        assert field.default is None

    #: 뜻은 반대다.
    assert "조건이 없다는 뜻이 아니라" in activation
    assert "적지 않았다는 뜻" in activation
    assert "조건이 없다" in observation
    assert "적지 않았다는 뜻" not in observation
    #: 트리거는 ``activation`` 과 같은 편이고, 완화책까지 적는다.
    assert "조건이 없다는 뜻이 아니라" in trigger
    assert "activation" in trigger
    assert "TriggerCollector" in trigger

    #: ``UnimplementedRule`` 로 적으라는 탈출구는 관측 쪽만 적는다.
    assert "UnimplementedRule" in observation
    assert "UnimplementedRule" not in activation


# ======================================================================
# Test 9 (§16) — 실제 consumer 가 None 을 어떻게 처리하는가
# ======================================================================


def test_12_every_consumer_of_activation_reads_none_the_same_way():
    """
    **Test 9 (§16): 실제 production consumer 의 ``None`` 처리를 고정한다.**

    ``EffectDefinition.activation`` 을 읽는 네 자리를 AST 로 찾고, 넷 모두
    **"정의가 등록되어 있는가" 를 먼저 묻는다**는 것을 확인한다. 그래서
    ``activation=None`` 이 "아직 안 적었다" 를 가리킬 가능성은 조건 칸이
    아니라 **다른 관문**이 막는다.
    """
    #: 발동 · 해결 — 모두 ``None`` 을 통과로 읽는다.
    for path in ("engine/activation.py", "engine/effect/executor.py"):
        assert "if definition.activation is None:" in source_of(path)

    #: 그리고 **그 앞에** 정의 등록 / 실행 권위 관문이 있다.
    activation_source = source_of("engine/activation.py")
    assert activation_source.index("definition is None") < activation_source.index(
        "if definition.activation is None:"
    )
    executor_source = source_of("engine/effect/executor.py")
    assert executor_source.index("_check_authority") < executor_source.index(
        "if definition.activation is None:"
    )

    #: 트리거 두 자리 — ``spec.condition`` 과 ``definition.activation`` 을
    #: **함께** 모으고, 둘 다 없는데 정의도 없으면 ``UNKNOWN`` 이다.
    trigger_source = source_of("engine/trigger.py")
    assert trigger_source.count(
        "definition.activation if definition is not None else None"
    ) == 2
    assert trigger_source.count("정의가 등록되어 있지 않아") == 1
    assert trigger_source.count("정의가 없어 조건을 확인할 수 없습니다") == 1
    assert trigger_source.count('notes=("정의 미등록",)') == 4

    #: 등록되지 않은 정의는 조건 칸을 보기도 전에 막힌다 — 실제로 돌려본다.
    from engine.chain import Chain
    from engine.effect import EffectDefinitionRegistry, EffectImplementationRegistry

    definition = synthetic(activation=None)
    empty = __import__("engine.activation", fromlist=["EffectActivator"]).EffectActivator(
        EffectDefinitionRegistry(()), EffectImplementationRegistry(())
    )
    state = new_state()
    action = PlayerAction.activate_effect(
        actor=MINE,
        source=state.player(MINE).monster_zone[0].instance_id,
        effect_ref=definition.effect_ref,
    )
    blocked = empty.activate(
        state,
        Chain(),
        action,
        authorization=__import__(
            "engine.validation", fromlist=["ValidationResult"]
        ).ValidationResult.valid("테스트가 허가했다"),
    )
    assert blocked.status is ActivationStatus.NOT_IMPLEMENTED
    assert blocked.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert blocked.missing == "effect definition"


def test_13_the_name_condition_also_marks_things_that_are_not_conditions():
    """
    **§6 이름 충돌.** 같은 이름이 ``Condition`` 이 아닌 자리도 있다.

    - ``engine/activation.py`` · ``engine/effect/executor.py`` 의 지역 변수
      ``condition`` 은 **막는 결과**이고 ``None`` 은 "막는 것이 없다" 다.
    - ``ResponseResult.activation`` 은 ``ActivationResult | None`` 이고
      ``None`` 은 "발동 계층까지 가지 않았다" 다.

    이름만 보고 계약을 읽으면 틀린다는 사실을 고정한다.
    """
    #: 결과 채널 — ``None`` 이면 통과한다는 문장이 그대로 있다.
    assert "막는 것이 있으면 그 결과, 없으면 ``None``" in source_of(
        "engine/activation.py"
    )
    assert "condition = self._check_condition(" in source_of("engine/activation.py")
    assert "if condition is not None:" in source_of("engine/activation.py")

    #: 반환 주석이 ``Condition`` 이 아니다.
    tree = ast.parse(source_of("engine/activation.py"))
    returns = {
        node.name: _unparse(node.returns)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.returns is not None
    }
    assert returns["_check"] == "ActivationResult | None"
    assert returns["_check_condition"] == "ActivationResult | None"

    #: ``ResponseResult.activation`` 은 Condition 이 아니다.
    from engine.response import ResponseResult

    field = next(
        f for f in dataclasses.fields(ResponseResult) if f.name == "activation"
    )
    assert field.type == "ActivationResult | None"
    assert "Condition" not in field.type
    doc = field_docstring("engine/response.py", "ResponseResult", "activation")
    assert "Phase 2-Q" in doc


# ======================================================================
# §15 · §20 — 계약 차이가 production 경로에서 만나는가
# ======================================================================


def test_14_observation_grant_is_never_constructed_in_production():
    """
    **§20 의 두 번째 조건이 충족되지 않는다** — 반대 계약을 들고 있는
    ``ObservationGrant`` 는 production 에서 **한 번도 생성되지 않는다.**

    생성처를 AST 로 전수 수집한다 (문자열 검색이면 주석도 세어진다).
    그래서 "계약이 반대다" 는 사실이지만 "같은 경로에서 충돌한다" 는
    사실이 **아니다**. 이것이 ``D. CONTRACT_CONFLICT`` 를 고르지 않는 근거다.
    """
    production = []
    tests = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel.startswith((".venv", "build")):
            continue
        if rel == "tests/test_engine_condition_none_contract_audit.py":
            #: **이 감사 파일 자신은 세지 않는다** — 계약을 시험하려고 만든
            #: 것이고, 세면 "생성처가 늘었다" 는 신호가 나 자신 때문에 흐려진다.
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ObservationGrant"
            ):
                (tests if rel.startswith("tests/") else production).append(
                    f"{rel}:{node.lineno}"
                )

    assert production == [], f"production 생성처가 생겼다: {production}"
    assert len(tests) == 5

    #: ``derive_policy`` 를 부르는 production 코드도 없다.
    callers = []
    for pkg in ("engine", "agent", "core", "analysis", "sources"):
        for path in sorted((PROJECT_ROOT / pkg).rglob("*.py")):
            rel = str(path.relative_to(PROJECT_ROOT))
            if rel == "engine/observation_grant.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "derive_policy"
                ):
                    callers.append(f"{rel}:{node.lineno}")
    assert callers == []


def test_15_no_single_none_value_is_read_with_two_meanings_on_one_path():
    """
    **§15 propagation audit.** 같은 ``None`` 이 한 경로에서 두 뜻으로
    읽히는 자리를 찾는다 — **없다.**

    ``EffectDefinition.activation=None`` 하나를 네 consumer 에 모두 넣고,
    넷 모두 "정의가 등록되어 있다" 는 전제 아래 **통과/적격**으로 읽는지
    확인한다. 트리거 쪽은 정의가 없으면 ``UNKNOWN`` 이므로 두 경우를
    따로 본다.
    """
    from engine.condition.evaluator import ConditionEvaluator
    from engine.effect import CardDrawn, EffectDefinitionRegistry
    from engine.trigger import (
        TimingEvent,
        TimingPoint,
        TriggerCollector,
        TriggerRegistry,
        TriggerStatus,
    )

    #: 판에 실제로 있는 카드(``WATCHER``)의 효과를 쓴다 — 기존 하네스가
    #: 쓰는 것 그대로다. 아무 카드의 의미도 주장하지 않는다.
    definition = watched_definition(activation=None)
    state = new_state()
    view = view_of(state)
    event = drawn_event()
    spec = watching(None)
    assert spec.condition is None and definition.activation is None

    #: (1) 정의가 **등록되어 있으면** — 둘 다 None 이어도 적격이다.
    registered = TriggerCollector(
        view,
        TriggerRegistry((spec,)),
        definitions=EffectDefinitionRegistry((definition,)),
    ).collect(event)
    #: ``WATCHER`` 가 패에 3장 있으므로 후보가 3개다 — 셋 다 적격이다.
    assert [c.status for c in registered] == [TriggerStatus.ELIGIBLE] * 3
    assert registered.undecided == ()

    #: (2) 정의가 **없으면** — 같은 None 인데 ``UNKNOWN`` 이다.
    #: 조건 칸의 뜻이 바뀐 것이 아니라 **다른 관문**이 막은 것이다.
    missing = TriggerCollector(
        view,
        TriggerRegistry((spec,)),
        definitions=EffectDefinitionRegistry(()),
    ).collect(event)
    assert [c.status for c in missing] == [TriggerStatus.UNKNOWN] * 3
    for candidate in missing:
        assert candidate.code is ValidationCode.RULE_NOT_IMPLEMENTED
        assert "정의 미등록" in candidate.notes

    #: (3) 발동 · 해결 — 등록되어 있으므로 통과한다.
    assert activate(new_state(), definition).status is ActivationStatus.ACTIVATED
    assert resolve(new_state(), definition).status is not (
        ResolutionStatus.CONDITION_UNKNOWN
    )

    #: 조건 평가기는 ``None`` 을 받지 않는다 — 평가 자체가 일어나지 않는다.
    with pytest.raises((AttributeError, TypeError)):
        ConditionEvaluator(view).evaluate(None, ConditionContext(player=MINE))


# ======================================================================
# Test 10 (§16) — 3-E-24~33 semantics regression
# ======================================================================


def test_16_the_four_distinctions_from_phase_3e24_to_3e33_still_hold():
    """
    **Test 10 (§16): 앞선 Phase 들이 세운 구분이 그대로인지.**

    - ``UNKNOWN`` != ``FALSE``
    - ``INFORMATION_UNAVAILABLE`` != ``RULE_NOT_IMPLEMENTED``
    - ``INVALID`` != ``EXECUTION_FORBIDDEN``
    - ``CANDIDATE_NOT_ELIGIBLE`` != ``RULE_NOT_IMPLEMENTED``
    """
    assert ConditionResult.UNKNOWN is not ConditionResult.FALSE
    assert ActionValidity.UNKNOWN is not ActionValidity.INVALID
    assert (
        ValidationCode.INFORMATION_UNAVAILABLE
        is not ValidationCode.RULE_NOT_IMPLEMENTED
    )
    assert ValidationCode.EXECUTION_FORBIDDEN is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert (
        ValidationCode.CANDIDATE_NOT_ELIGIBLE is not ValidationCode.RULE_NOT_IMPLEMENTED
    )
    assert ActivationStatus.CONDITION_UNKNOWN is not ActivationStatus.CONDITION_FALSE
    assert ResolutionStatus.CONDITION_UNKNOWN is not ResolutionStatus.CONDITION_FALSE

    #: 세 값만 있고 네 번째(예: NOT_WRITTEN)는 **없다** — 이번 Phase 가
    #: 새 상태를 만들지 않았다는 증거다.
    assert len(ConditionResult) == 3
    assert len(ActionValidity) == 3
    assert "NOT_WRITTEN" not in ConditionResult.__members__
    assert "NOT_PROVIDED" not in ConditionResult.__members__

    #: 그리고 발동 계층의 두 까닭이 실제로 갈린다 (3-E-26).
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    assert rule.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert rule.status is info.status is ActivationStatus.CONDITION_UNKNOWN


def test_17_no_consumer_outside_the_five_layers_reads_a_condition_field():
    """
    **§18 AI/Search 영향 없음** — ``agent/`` 의 어느 파일도 다섯 조건 칸을
    읽지 않는다. AST 로 센다 (주석·docstring 은 세지 않는다).
    """
    names = {"activation", "condition", "require"}
    offenders = []
    for path in sorted((PROJECT_ROOT / "agent").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr in names
                and isinstance(node.value, ast.Name)
                and node.value.id in {"definition", "spec", "grant", "source", "cost"}
            ):
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} {_unparse(node)}"
                )
    assert offenders == [], offenders
