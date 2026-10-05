"""
Phase 3-E-35 — ``UnimplementedRule`` 의미 · 사용처 전수 감사.

핵심 질문: **``UnimplementedRule`` 은 정확히 무엇이고, 그 의미가 계층을
지나면서 안전한가.**

"미구현" 이라고 적혀 있다고 runtime 미구현이라 단정하지 않고, 파일에
있다고 production 에서 실행된다고 단정하지 않는다. 정의 → 생성 → 전달 →
소비까지 AST 와 **실제 실행**으로 따라간다.

측정으로 드러난 여덟 가지
-------------------------

1. **네 가지가 서로 다른 것이다.** 이름이 비슷해서 하나로 보기 쉽다.

   =============================== ==========================================
   ``UnimplementedRule``           ``Condition`` **클래스** 하나.
                                   언제나 ``UNKNOWN``
   ``Condition.missing_rules()``   **메서드(프로토콜)**. 비어 있지 않으면
                                   "규칙이 없어서 모른다"
   ``ValidationResult.missing_rule`` **필드**. 문자열 하나
   ``ValidationCode.RULE_NOT_IMPLEMENTED`` **enum 멤버**
   =============================== ==========================================

2. **``RULE_NOT_IMPLEMENTED`` 는 거의 전부 ``UnimplementedRule`` 없이
   만들어진다.** production 에서 그 코드는 **75곳**에 등장하는데
   ``UnimplementedRule(...)`` 생성은 **2곳**뿐이다 (둘 다
   ``engine/action_validation.py`` 의 ``_special_summon``).

3. **``missing_rules()`` 는 ``UnimplementedRule`` 의 전유물이 아니다.**
   production 의 두 조건 ``_NormalSummonProcedure`` ·
   ``_NormalSpellActivation`` 이 그것을 **조건부로** 구현한다 —
   ``UnimplementedRule`` 은 무조건 ``UNKNOWN`` 이라 그렇게 할 수 없다.
   그래서 ``_NormalSummonProcedure`` 는 진짜 거부(``FALSE``)일 때
   ``missing_rules()`` 가 **빈 튜플**이다.

4. **``library.py`` 에는 ``UnimplementedRule`` 이 하나도 없다** (0개).
   3-E-33/34 가 가리킨 공백이 여기서 확정된다 — 등재 효과는 조건을
   ``None`` 아니면 실제 ``Condition`` 으로만 적는다.

5. **production 도달은 "조건부"다.** ``ActionValidator`` 는 production
   클래스이고 ``requirements(special_summon)`` 이 실제로 두
   ``UnimplementedRule`` 을 돌려주지만, ``Duel.legal_actions()`` 는
   ``SPECIAL_SUMMON`` 을 **한 번도 만들지 않는다.** 즉 그 입력을 만드는
   production 호출자가 없다.

6. **``UNKNOWN`` 안에서 까닭이 갈린다.** ``missing_rules()`` 가 비어
   있지 않으면 ``RULE_NOT_IMPLEMENTED``, 비어 있으면
   ``INFORMATION_UNAVAILABLE`` 이다. 상태(``UNKNOWN``)는 한 칸도 움직이지
   않는다.

7. **``FALSE`` 가 ``UNKNOWN`` 을 이긴다.** 같은 요구 목록에 확실한 거부와
   미구현이 함께 있으면 결과는 ``INVALID`` 다 — 미구현이 거부를 덮지 않는다.

8. **AI 경계에서 두 코드가 한 상태로 합쳐지지만 사실은 보존된다.**
   ``agent/simulation.py`` 의 ``_UNKNOWN_CODES`` 가
   ``RULE_NOT_IMPLEMENTED`` 와 ``INFORMATION_UNAVAILABLE`` 을 모두
   ``SimulationStatus.UNKNOWN`` 으로 보내지만, ``SimulationResult.code`` 가
   원래 코드를 그대로 들고 있다. 그리고 ``UNKNOWN`` 후보는 점수가
   **``None``** 이고 줄 세우기에서 뒤로 간다 — **0 도 패배도 아니다.**

이 Phase 는 production 을 고치지 않았다. 감사다.
"""

import ast
import dataclasses
import pathlib

import pytest

from agent.search import SearchCandidate
from agent.simulation import SimulationResult, SimulationStatus, _UNKNOWN_CODES
from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import (
    ActionValidator,
    Requirement,
    SPECIAL_SUMMON_CONDITION_RULE,
    _NormalSpellActivation,
    _NormalSummonProcedure,
)
from engine.activation import ActivationStatus
from engine.condition import (
    Always,
    Condition,
    ConditionContext,
    ConditionResult,
    IsMonster,
    UnimplementedRule,
)
from engine.cost.model import UnimplementedCost
from engine.duel import Duel
from engine.effect.resolution import ResolutionStatus
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.state.game_state import GameState
from engine.summon_rules import SummonAssessment
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

#: 발동 · 해결 계층을 **그대로** 부르는 기존 도구를 다시 쓴다.
from tests.test_validation_code_consistency import (
    activate,
    new_state,
    resolve,
    synthetic,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
ENGINE = PROJECT_ROOT / "engine"

MINE, THEIRS = 0, 1


# ======================================================================
# 측정값 — 전부 저장소에서 센 수다. 바뀌면 그것이 신호다.
# ======================================================================

#: ``UnimplementedRule(...)`` 를 **production 에서** 만드는 자리. 두 곳뿐이고
#: 둘 다 ``_special_summon`` 요구 목록이다.
PRODUCTION_CONSTRUCTIONS = {
    ("engine/action_validation.py", "_special_summon"),
}
PRODUCTION_CONSTRUCTION_COUNT = 2

#: ``RULE_NOT_IMPLEMENTED`` 가 production (``engine/`` + ``agent/``) 에
#: 등장하는 총 횟수. 생성 2곳과 대비하는 수다.
#:
#: 75 → **76** (Phase 3-E-38). 네 자리를 정확한 코드로 바꾸면서 코드 등장이
#: 2 줄어들고(69 → 67) 그 까닭을 적은 주석이 3 늘었다(6 → 9). 이 수가
#: 가리키는 요지("코드 등장이 생성의 수십 배다")는 그대로다.
RULE_NOT_IMPLEMENTED_MENTIONS = 76

#: ``missing_rules`` 를 override 하는 production 클래스 — 7개.
#: ``UnimplementedRule`` 은 그중 **하나**일 뿐이다.
MISSING_RULES_OVERRIDES = {
    ("engine/condition/model.py", "Condition"),
    ("engine/condition/model.py", "UnimplementedRule"),
    ("engine/condition/model.py", "And"),
    ("engine/condition/model.py", "Or"),
    ("engine/condition/model.py", "Not"),
    ("engine/action_validation.py", "_NormalSpellActivation"),
    ("engine/action_validation.py", "_NormalSummonProcedure"),
}

#: ``_NormalSummonProcedure`` · ``_NormalSpellActivation`` 이 실제로 내놓는
#: 규칙 이름들 (실측). ``UnimplementedRule`` 을 쓰지 않고 만든 것들이다.
MEASURED_RULE_NAMES = {
    "summoning-condition (카드 텍스트의 소환 제약)",
    "tribute-summon (제물 선택 · 릴리스)",
    "monster-activation-timing (기동 · 유발 · 플립 · 유발즉시 분류가 없다)",
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


def _enclosing_functions(tree) -> dict[int, str]:
    """줄 번호 → 그 줄을 품은 가장 가까운 함수 이름."""
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                line = getattr(inner, "lineno", None)
                if line is not None:
                    owner[line] = node.name
    return owner


def unimplemented_rule_sites() -> dict[str, list[tuple[str, int, str]]]:
    """
    ``UnimplementedRule(...)`` 생성처 전수. ``{"production"/"tests": [...]}``.

    문자열 검색이 아니라 AST ``Call`` 이다 — 주석·docstring·import 는 세지
    않는다.
    """
    found: dict[str, list[tuple[str, int, str]]] = {"production": [], "tests": []}
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel.startswith((".venv", "build")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        owner = _enclosing_functions(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "UnimplementedRule"
            ):
                bucket = "tests" if rel.startswith("tests/") else "production"
                found[bucket].append(
                    (rel, node.lineno, owner.get(node.lineno, "<모듈 수준>"))
                )
    return found


def missing_rules_overrides() -> set[tuple[str, str]]:
    """``missing_rules`` 를 정의하는 ``engine/`` 의 클래스 전수."""
    found: set[tuple[str, str]] = set()
    for path in sorted(ENGINE.rglob("*.py")):
        rel = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef) and stmt.name == "missing_rules":
                    found.add((rel, node.name))
    return found


@pytest.fixture(scope="module")
def board(repository):
    """
    앞면 몬스터가 내 MZONE 에 있는 판. 셔플하지 않는다.

    ``MZONE`` 은 ``SPECIAL_SUMMON_FROM_ZONES`` **밖**이고 관측에 **보인다** —
    그래서 두 ``UnimplementedRule`` 이 **둘 다** 요구 목록에 들어온다.
    """
    from core.constants import TYPE_MONSTER, TYPE_SPELL

    monsters = [c.id for c in repository.all_cards() if c.type_mask & TYPE_MONSTER][:4]
    spells = [c.id for c in repository.all_cards() if c.type_mask & TYPE_SPELL][:4]
    #: 몬스터와 마법을 **섞어** 둔다 — ``test_08`` 이 몬스터가 아닌 카드를
    #: 필요로 하고, 섞지 않으면 그 테스트가 조용히 skip 된다.
    deck = [monsters[0], spells[0], monsters[1], spells[1], monsters[2], spells[2],
            monsters[3], spells[3]]
    state = GameState.create(repository, decks=(list(deck), list(deck)))
    state.draw(MINE, 5)
    state.draw(THEIRS, 5)
    #: MZONE 에는 **반드시 몬스터**를 올린다. 마법이 올라가면 ``IsMonster`` 가
    #: ``FALSE`` 가 되어 ``test_10`` 이 다른 것을 재게 된다 (뽑는 순서에
    #: 기대지 않는다).
    monster_in_hand = next(
        card
        for card in state.player(MINE).hand
        if repository.get(card.card_id).type_mask & TYPE_MONSTER
    )
    state.move(monster_in_hand, Zone.MZONE, position=Position.FACEUP_ATTACK)
    state.turn.set_phase(Phase.MAIN1)
    return state


@pytest.fixture(scope="module")
def validator(board) -> ActionValidator:
    return ActionValidator(GameStateView.from_state(board, viewer=MINE))


def special_summon_of(board) -> PlayerAction:
    return PlayerAction.special_summon(
        actor=MINE, source=board.player(MINE).monster_zone[0].instance_id
    )


# ======================================================================
# Test 1 — 정의 / 필드 semantics
# ======================================================================


def test_01_unimplemented_rule_is_a_condition_that_is_always_unknown():
    """
    **Test 1 (§20): ``UnimplementedRule`` 의 정의와 필드.**

    ``Condition`` 하위 클래스이고, 필드는 ``rule: str`` **하나**다.
    언제나 ``UNKNOWN`` 이고, ``missing_rules()`` 가 그 이름을 돌려준다.

    "규칙이 없다" 와 "규칙이 있지만 구현되지 않았다" 를 구분하는 칸은
    **없다** — 둘을 한 문자열로 적는다. 그 문자열이 유일한 정보다.
    """
    assert issubclass(UnimplementedRule, Condition)

    fields = [f.name for f in dataclasses.fields(UnimplementedRule)]
    assert fields == ["rule"]
    #: 기본값이 없다 — 이름을 적지 않고 만들 수 없다.
    assert dataclasses.fields(UnimplementedRule)[0].default is dataclasses.MISSING
    with pytest.raises(TypeError):
        UnimplementedRule()  # type: ignore[call-arg]

    #: 불변이다.
    rule = UnimplementedRule("chain (Phase 2-F)")
    with pytest.raises(dataclasses.FrozenInstanceError):
        rule.rule = "다른 규칙"  # type: ignore[misc]

    view = GameStateView.from_state(new_state(), viewer=MINE)
    context = ConditionContext(player=MINE)

    #: **판을 보지 않고** 언제나 UNKNOWN 이다 — 조건부가 아니다.
    assert rule.evaluate(view, context) is ConditionResult.UNKNOWN
    assert rule.evaluate(None, None) is ConditionResult.UNKNOWN

    assert rule.missing_rules(view, context) == ("chain (Phase 2-F)",)
    assert rule.unknown_reasons(view, context) == ("규칙 미구현: chain (Phase 2-F)",)
    assert rule.canonical_state() == ("unimplemented", "chain (Phase 2-F)")
    assert rule.to_dict() == {"kind": "unimplemented", "rule": "chain (Phase 2-F)"}
    assert "chain (Phase 2-F)" in rule.describe_ko()

    #: 같은 이름이면 같다 — 등식이 이름 하나로 정해진다.
    assert UnimplementedRule("a") == UnimplementedRule("a")
    assert UnimplementedRule("a") != UnimplementedRule("b")


def test_02_the_base_contract_says_an_empty_missing_rules_means_missing_information():
    """
    **``missing_rules()`` 의 기본값이 계약이다.**

    ``Condition.missing_rules`` 는 ``()`` 를 돌려주고, docstring 이
    "비어 있으면 '정보가 없어서 모른다' 는 뜻" 이라고 적는다. 그래서
    ``UnimplementedRule`` 은 **그 기본값을 뒤집는 유일하게 무조건적인**
    구현이다.
    """
    view = GameStateView.from_state(new_state(), viewer=MINE)
    context = ConditionContext(player=MINE)

    #: ``Always(UNKNOWN)`` 도 ``UNKNOWN`` 이지만 규칙 이름이 **없다**.
    vague = Always(ConditionResult.UNKNOWN)
    assert vague.evaluate(view, context) is ConditionResult.UNKNOWN
    assert vague.missing_rules(view, context) == ()

    #: 그래서 둘은 **같은 UNKNOWN 이 아니다** — 까닭이 다르다.
    rule = UnimplementedRule("chain")
    assert rule.evaluate(view, context) is vague.evaluate(view, context)
    assert rule.missing_rules(view, context) != vague.missing_rules(view, context)

    doc = Condition.missing_rules.__doc__ or ""
    assert "정보가 없어서 모른다" in doc

    #: 그리고 ``Always`` 의 docstring 이 ``UnimplementedRule`` 을 권한다.
    assert "UnimplementedRule" in (Always.__doc__ or "")


# ======================================================================
# Test 2·3 — RULE_NOT_IMPLEMENTED / missing_rule 과의 관계
# ======================================================================


def test_03_rule_not_implemented_is_almost_never_produced_by_unimplemented_rule():
    """
    **Test 2 (§20): ``RULE_NOT_IMPLEMENTED`` mapping.**

    둘은 같은 개념이 **아니다.** 코드는 production 에 75곳 등장하는데
    ``UnimplementedRule`` 생성은 2곳뿐이다. 즉 **그 코드의 거의 전부가
    ``UnimplementedRule`` 과 무관하게 만들어진다.**
    """
    sites = unimplemented_rule_sites()
    assert len(sites["production"]) == PRODUCTION_CONSTRUCTION_COUNT
    assert {(rel, func) for rel, _, func in sites["production"]} == (
        PRODUCTION_CONSTRUCTIONS
    )
    #: 테스트에서는 널리 쓰인다 — 그것은 dormant 가 아니라 **시험 도구**다.
    assert len(sites["tests"]) > 40

    mentions = 0
    for pkg in ("engine", "agent"):
        for path in sorted((PROJECT_ROOT / pkg).rglob("*.py")):
            mentions += path.read_text(encoding="utf-8").count("RULE_NOT_IMPLEMENTED")
    assert mentions == RULE_NOT_IMPLEMENTED_MENTIONS
    assert mentions > 30 * PRODUCTION_CONSTRUCTION_COUNT


def test_04_four_different_things_share_a_similar_name():
    """
    **Test 3 (§20): ``missing_rule`` mapping.**

    네 가지를 하나로 취급하면 안 된다 — 타입이 전부 다르다.

    1. ``UnimplementedRule`` — ``Condition`` 클래스
    2. ``Condition.missing_rules()`` — 메서드, ``tuple[str, ...]``
    3. ``ValidationResult.missing_rule`` — 필드, ``str | None``
    4. ``ValidationCode.RULE_NOT_IMPLEMENTED`` — enum 멤버

    그리고 비용 계층에는 **다른 이름의 형제**가 있다 —
    ``UnimplementedCost`` 는 ``RULE_NOT_IMPLEMENTED`` 가 아니라
    ``COST_NOT_IMPLEMENTED`` 로 간다.
    """
    #: 1. 클래스
    assert isinstance(UnimplementedRule("x"), Condition)
    #: 2. 메서드 — 튜플
    view = GameStateView.from_state(new_state(), viewer=MINE)
    assert isinstance(
        UnimplementedRule("x").missing_rules(view, ConditionContext(player=MINE)), tuple
    )
    #: 3. 필드 — 문자열 하나
    field = next(
        f for f in dataclasses.fields(ValidationResult) if f.name == "missing_rule"
    )
    assert field.type == "str | None"
    assert field.default is None
    #: 4. enum 멤버
    assert isinstance(ValidationCode.RULE_NOT_IMPLEMENTED, ValidationCode)

    #: 비용 쪽 형제 — 코드가 다르다.
    assert UnimplementedCost("x").rule == "x"
    assert ValidationCode.COST_NOT_IMPLEMENTED is not (
        ValidationCode.RULE_NOT_IMPLEMENTED
    )

    #: 소환 판정에도 독립적인 ``missing_rule`` 필드가 있다.
    summon_field = next(
        f for f in dataclasses.fields(SummonAssessment) if f.name == "missing_rule"
    )
    assert summon_field.type == "str | None"


def test_05_missing_rules_is_a_protocol_not_a_privilege_of_unimplemented_rule():
    """
    **``missing_rules()`` 를 구현하는 production 클래스는 7개다.**

    그중 둘(``_NormalSummonProcedure`` · ``_NormalSpellActivation``)은
    ``UnimplementedRule`` 이 **아니면서** 규칙 이름을 낸다. 그리고
    ``UnimplementedRule`` 이 못 하는 일을 한다 — **조건부**로 낸다.
    """
    assert missing_rules_overrides() == MISSING_RULES_OVERRIDES

    #: ``UnimplementedRule`` 은 무조건이다 — 판을 보지 않는다.
    tree = ast.parse(source_of("engine/condition/model.py"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "UnimplementedRule":
            body = next(
                stmt
                for stmt in node.body
                if isinstance(stmt, ast.FunctionDef) and stmt.name == "evaluate"
            )
            #: 본문이 ``return ConditionResult.UNKNOWN`` 한 줄이다.
            assert len(body.body) == 1
            assert isinstance(body.body[0], ast.Return)
            assert _unparse(body.body[0].value) == "ConditionResult.UNKNOWN"


# ======================================================================
# Test 4·5 — UNKNOWN / INFORMATION_UNAVAILABLE 과의 구분
# ======================================================================


def test_06_unknown_splits_into_two_reasons_and_the_status_never_moves():
    """
    **Test 4·5 (§20): ``UNKNOWN`` · ``INFORMATION_UNAVAILABLE`` 과의 구분.**

    production 발동기를 그대로 부른다. 두 경우 모두 ``CONDITION_UNKNOWN``
    이고, **코드만** 갈린다.

    - ``UnimplementedRule`` → ``RULE_NOT_IMPLEMENTED``
    - 관측에 없는 카드를 묻는 조건 → ``INFORMATION_UNAVAILABLE``
    """
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))

    assert rule.status is info.status is ActivationStatus.CONDITION_UNKNOWN
    assert rule.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert rule.code is not info.code
    assert "없는 규칙" in (rule.missing or "")

    #: **그런데 ``ActivationResult.missing`` 은 ``missing_rules`` 가 아니다.**
    #: ``engine/activation.py`` 가 ``unknown_reasons`` 를 넣으므로, 정보 부족
    #: 쪽에도 문장이 **들어 있다** (``ValidationResult.missing_rule`` 과 다른
    #: 칸이다 — 저쪽은 규칙 이름만 받는다). 이름이 비슷한 다섯 번째 자리다.
    assert info.missing is not None
    assert "관측에 보이지 않음" in info.missing
    assert info.unchecked == (info.missing,)
    #: 코드가 갈리는 근거는 ``missing`` 이 아니라 ``missing_rules()`` 다.
    view = GameStateView.from_state(new_state(), viewer=MINE)
    context = ConditionContext(player=MINE)
    assert UnimplementedRule("없는 규칙").missing_rules(view, context) == ("없는 규칙",)
    assert IsMonster(InstanceId(9999)).missing_rules(view, context) == ()

    #: 해결 계층도 같은 태도다 (3-E-26 이 세운 고정).
    assert resolve(
        new_state(), synthetic(activation=UnimplementedRule("없는 규칙"))
    ).code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert resolve(
        new_state(), synthetic(activation=IsMonster(InstanceId(9999)))
    ).code is ValidationCode.INFORMATION_UNAVAILABLE


def test_07_a_missing_rule_never_becomes_false_or_a_permission():
    """
    **§18 invariant 1 · 2 · 5 · 6.**

    ``UnimplementedRule`` 은 ``FALSE`` 도 ``ACTIVATED`` 도 되지 않고,
    **판을 바꾸지 않는다.** 미구현 때문에 임의로 성공하지도 실패하지도
    않는다.
    """
    state = new_state()
    before = state.state_hash()
    result = activate(state, synthetic(activation=UnimplementedRule("없는 규칙")))

    assert result.status is ActivationStatus.CONDITION_UNKNOWN
    assert result.status is not ActivationStatus.CONDITION_FALSE
    assert result.status is not ActivationStatus.ACTIVATED
    assert len(result.chain) == 0
    assert state.state_hash() == before

    #: 거짓 조건은 **다른 칸**이다.
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))
    assert false.status is ActivationStatus.CONDITION_FALSE
    assert false.status is not ActivationStatus.CONDITION_UNKNOWN

    #: ``ValidationResult`` 도 ``UNKNOWN`` 을 허가로 읽지 못하게 막는다.
    verdict = ValidationResult.unknown(
        ValidationCode.RULE_NOT_IMPLEMENTED, "없는 규칙", missing_rule="없는 규칙"
    )
    assert verdict.permits_execution is False
    assert verdict.validity is ActionValidity.UNKNOWN
    with pytest.raises(TypeError):
        bool(verdict)


# ======================================================================
# Test 6·7 — INVALID / EXECUTION_FORBIDDEN 과의 구분
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_08_a_certain_refusal_beats_a_missing_rule(board, repository):
    """
    **Test 6 (§20): ``INVALID`` 과의 구분 — 그리고 §18 invariant 6.**

    같은 요구 목록에 ``FALSE`` 와 ``UnimplementedRule`` 이 함께 있으면
    결과는 ``INVALID`` 다. **미구현이 확실한 거부를 덮지 않는다.**

    몬스터가 아닌 카드로 특수 소환을 시도하면 ``IsMonster`` 가 ``FALSE`` 가
    되고, 그 뒤의 두 ``UnimplementedRule`` 은 결과를 바꾸지 않는다.
    """
    from core.constants import TYPE_MONSTER

    #: 몬스터가 아닌 카드를 내 SZONE 에 앞면으로 둔다.
    non_monster = next(
        (
            card
            for card in board.player(MINE).hand
            if not (repository.get(card.card_id).type_mask & TYPE_MONSTER)
        ),
        None,
    )
    if non_monster is None:
        pytest.skip("이 판에 몬스터가 아닌 카드가 없습니다.")

    fork = board.clone()
    target = fork.find_instance(non_monster.instance_id)
    fork.move(target, Zone.SZONE, position=Position.FACEUP_ATTACK)
    checker = ActionValidator(GameStateView.from_state(fork, viewer=MINE))
    action = PlayerAction.special_summon(actor=MINE, source=non_monster.instance_id)

    kinds = [type(r.condition).__name__ for r in checker.requirements(action)]
    assert "IsMonster" in kinds
    assert kinds.count("UnimplementedRule") >= 1

    verdict = checker.validate(action)
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.SOURCE_WRONG_CARD_TYPE
    assert verdict.code is not ValidationCode.RULE_NOT_IMPLEMENTED
    #: 거부에는 규칙 이름을 적지 않는다 — 모르는 것이 아니기 때문이다.
    assert verdict.missing_rule is None


def test_09_a_missing_rule_is_not_a_forbidden_execution():
    """
    **Test 7 (§20): ``EXECUTION_FORBIDDEN`` 과의 구분 — §18 invariant 4.**

    "규칙을 구현하지 않았다" 와 "이 근거로는 실행하지 않는다" (ADR-004,
    ``TEXT_DERIVED``) 는 **다른 사실**이다. enum 멤버가 다르고, 어느 쪽도
    다른 쪽으로 변환되지 않는다.
    """
    assert ValidationCode.RULE_NOT_IMPLEMENTED is not (
        ValidationCode.EXECUTION_FORBIDDEN
    )
    assert ValidationCode.RULE_NOT_IMPLEMENTED is not (
        ValidationCode.CANDIDATE_NOT_ELIGIBLE
    )

    #: 출처 금지는 **조건을 보기도 전에** 막는다 (3-E-34 가 고정한 관문 순서).
    from engine.effect import EffectProvenance

    forbidden = synthetic(
        activation=UnimplementedRule("없는 규칙"),
        provenance=EffectProvenance.text_derived("공식 텍스트에서 유추했다"),
    )
    result = activate(new_state(), forbidden)
    #: 조건이 미구현이어도 **조건 때문에 막힌 것이 아니다.**
    assert result.status is not ActivationStatus.CONDITION_UNKNOWN
    assert result.status in {
        ActivationStatus.FORBIDDEN,
        ActivationStatus.UNVERIFIED,
        ActivationStatus.NOT_IMPLEMENTED,
    }


# ======================================================================
# Test 8·9 — production 도달 / dormant 구분
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_10_both_production_unimplemented_rules_are_reachable_through_the_validator(
    board, validator
):
    """
    **Test 8 (§20): production path 도달.**

    ``ActionValidator`` 는 production 클래스이고, ``MZONE`` 의 앞면 몬스터로
    특수 소환을 물으면 **두 ``UnimplementedRule`` 이 둘 다** 요구 목록에
    들어온다. 결과는 ``UNKNOWN`` + ``RULE_NOT_IMPLEMENTED`` 이고
    ``missing_rule`` 이 채워진다.

    그리고 **까닭이 둘이면 둘 다 남는다** — ``missing_rule`` 에는 첫 번째가,
    ``notes`` 에는 전부가 들어간다. 정보가 사라지지 않는다 (§F 반증).
    """
    action = special_summon_of(board)
    rules = [
        r.condition.rule
        for r in validator.requirements(action)
        if isinstance(r.condition, UnimplementedRule)
    ]
    assert len(rules) == 2
    assert SPECIAL_SUMMON_CONDITION_RULE in rules
    assert any("special summon from MZONE" in rule for rule in rules)

    verdict = validator.validate(action)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert verdict.missing_rule == rules[0]
    assert verdict.permits_execution is False

    #: 두 까닭이 모두 ``notes`` 에 남는다.
    assert len(verdict.notes) == 2
    for rule in rules:
        assert any(rule in note for note in verdict.notes)
        assert any("규칙 미구현" in note for note in verdict.notes)


@requires_official_db
@pytest.mark.real_card
def test_11_legal_actions_never_builds_the_action_that_reaches_them(repository):
    """
    **Test 9 (§20): dormant 구분 — "F. 조건부 도달".**

    ``UnimplementedRule`` 은 dead code 도 테스트 전용도 아니다. 그러나
    ``Duel.legal_actions()`` 는 ``SPECIAL_SUMMON`` 을 **allowed 에도
    withheld 에도** 넣지 않으므로, 그 입력을 만드는 production 호출자가
    없다.

    그리고 ``Duel.apply`` 로 직접 넣으면 **목록 멤버십 관문**이 먼저
    거절한다 — 조건 평가까지 가지 않는다. 판은 바뀌지 않는다.
    """
    deck = [card.id for card in list(repository.all_cards())[:12]]
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=5)
    while duel.advance() is not None:
        pass

    legal = duel.legal_actions()
    assert all(a.kind is not PlayerActionKind.SPECIAL_SUMMON for a in legal.allowed)
    assert all(w.kind is not PlayerActionKind.SPECIAL_SUMMON for w in legal.withheld)

    seat = duel.to_act
    source = duel.state.player(seat).hand[0].instance_id
    action = PlayerAction.special_summon(actor=seat, source=source)

    before = duel.state.state_hash()
    step = duel.apply(action)
    assert step.accepted is False
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    #: **멤버십 거절이다** — 조건이 아니라 목록에 없어서다.
    assert "허가된 행위가 아닙니다" in step.reason
    assert duel.state.state_hash() == before

    #: 그래도 검증기에게 직접 물으면 조건이 돌아간다 — 같은 코드, 다른 까닭.
    verdict = ActionValidator(duel.view(seat)).validate(action)
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert verdict.missing_rule == SPECIAL_SUMMON_CONDITION_RULE


def test_12_the_cost_layer_sibling_is_dormant_but_its_consumer_is_live():
    """
    **dormant 의 종류를 가른다.** ``UnimplementedCost`` 는 production 에서
    **한 번도 생성되지 않는다** (테스트 전용). 그러나 그것을 **읽는**
    ``CostValidator.validate`` 는 production 코드이고, 받으면
    ``COST_NOT_IMPLEMENTED`` 를 돌려준다.

    즉 "B. library / registration metadata" 도 "D. dead code" 도 아니라
    **"A. 아직 연결하지 않은 미래 기능"** 이다.
    """
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
                and node.func.id == "UnimplementedCost"
            ):
                production.append(f"{rel}:{node.lineno}")
    assert production == []

    #: 소비자는 살아 있다.
    validation = source_of("engine/cost/validation.py")
    assert "isinstance(cost, UnimplementedCost)" in validation
    assert "ValidationCode.COST_NOT_IMPLEMENTED" in validation
    assert "missing_rule=cost.rule" in validation


# ======================================================================
# Test 10·11 — library.py / 실제 Lua
# ======================================================================


def test_13_the_effect_library_contains_no_unimplemented_rule_at_all():
    """
    **Test 10 (§20): ``library.py`` 사례 — 0개다.**

    §8 이 "library.py 에 왜 ``UnimplementedRule`` 이 있는가" 를 묻지만,
    **하나도 없다.** 3-E-33 (`activation` 8개 중 `UnimplementedRule` 0개) 과
    3-E-34 (같은 측정) 가 가리킨 공백이 여기서 확정된다.

    등재 효과는 조건을 ``None`` 아니면 **실제 판정 가능한 ``Condition``**
    으로만 적는다. 즉 "아직 옮기지 못한 조건" 을 ``UNKNOWN`` 으로 적는
    수단이 **쓰이지 않고 있다.**
    """
    library = source_of("engine/effect/library.py")
    assert "UnimplementedRule" not in library

    from engine.effect.library import EFFECT_LIBRARY

    activations = [
        entry.definition.activation
        for entry in EFFECT_LIBRARY
        if entry.definition.activation is not None
    ]
    assert len(EFFECT_LIBRARY) == 16
    assert len(activations) == 8
    assert not any(isinstance(a, UnimplementedRule) for a in activations)

    #: 여덟 개 전부 **판정 가능한** 조건이다 — UNKNOWN 을 내지 않는다.
    view = GameStateView.from_state(new_state(), viewer=MINE)
    context = ConditionContext(player=MINE)
    for activation in activations:
        assert activation.missing_rules(view, context) == ()


@requires_official_db
@pytest.mark.real_card
def test_14_two_real_conditions_report_missing_rules_without_unimplemented_rule(board):
    """
    **Test 11 (§20): 실제 Lua / 카드 기반 사례.**

    ``_NormalSummonProcedure`` 와 ``_NormalSpellActivation`` 은 실제
    카드 정의를 읽고 **조건부로** 규칙 이름을 낸다.

    - 제물이 필요한 몬스터 → ``UNKNOWN`` + ``tribute-summon ...``
    - 효과 몬스터 → ``UNKNOWN`` + ``summoning-condition ...``
    - 엑스트라 덱 · 의식 · 토큰 → ``FALSE`` + **빈 튜플** (거부다, 미구현이 아니다)

    ``UnimplementedRule`` 은 이것을 할 수 없다 — 무조건 ``UNKNOWN`` 이다.
    """
    view = GameStateView.from_state(board, viewer=MINE)
    seen_rules: set[str] = set()
    refusals = 0
    unknowns = 0

    for card in list(board.player(MINE).hand) + list(board.player(MINE).monster_zone):
        instance = card.instance_id
        context = ConditionContext(player=MINE, source=instance)
        for condition in (
            _NormalSummonProcedure(instance),
            _NormalSpellActivation(instance),
        ):
            verdict = condition.evaluate(view, context)
            rules = condition.missing_rules(view, context)
            if verdict is ConditionResult.FALSE:
                refusals += 1
                #: **거부에는 규칙 이름이 없다.**
                assert rules == ()
            elif verdict is ConditionResult.UNKNOWN:
                unknowns += 1
                assert rules, "UNKNOWN 인데 까닭이 없다"
                seen_rules.update(rules)
            else:
                assert rules == ()

    assert unknowns > 0
    assert seen_rules & MEASURED_RULE_NAMES, seen_rules
    #: 그리고 그 조건들은 ``UnimplementedRule`` 이 아니다.
    assert not isinstance(_NormalSummonProcedure(None), UnimplementedRule)
    assert not isinstance(_NormalSpellActivation(None), UnimplementedRule)


# ======================================================================
# Test 12 — AI / Search 영향
# ======================================================================


def test_15_the_ai_boundary_merges_two_codes_into_one_status_but_keeps_the_code():
    """
    **Test 12 (§20) · §19: AI / Search 영향.**

    ``agent/simulation.py`` 의 ``_UNKNOWN_CODES`` 는
    ``RULE_NOT_IMPLEMENTED`` 와 ``INFORMATION_UNAVAILABLE`` 을 **같은**
    ``SimulationStatus.UNKNOWN`` 으로 보낸다. 그것은 계층에 맞는 축약이다 —
    둘 다 "미래를 볼 수 없다" 이기 때문이다.

    **그러나 사실은 보존된다**: ``SimulationResult.code`` 가 원래 코드를
    그대로 들고 있다. 그리고 ``UNKNOWN`` 은 **0 도 패배도 아니다** —
    점수가 ``None`` 이고 줄 세우기에서 뒤로 간다.
    """
    assert ValidationCode.RULE_NOT_IMPLEMENTED in _UNKNOWN_CODES
    assert ValidationCode.INFORMATION_UNAVAILABLE in _UNKNOWN_CODES
    #: 거절은 섞이지 않는다.
    assert ValidationCode.EXECUTION_FORBIDDEN not in _UNKNOWN_CODES
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE not in _UNKNOWN_CODES
    assert ValidationCode.OK not in _UNKNOWN_CODES

    action = PlayerAction.passing(actor=MINE)
    rule = SimulationResult(
        action=action,
        status=SimulationStatus.UNKNOWN,
        viewer=MINE,
        code=ValidationCode.RULE_NOT_IMPLEMENTED,
    )
    info = SimulationResult(
        action=action,
        status=SimulationStatus.UNKNOWN,
        viewer=MINE,
        code=ValidationCode.INFORMATION_UNAVAILABLE,
    )
    #: 상태는 같고 **코드는 다르다** — 축약이지 유실이 아니다.
    assert rule.status is info.status
    assert rule.code is not info.code

    #: 미래를 꾸며 내지 않는다.
    assert rule.status.gives_a_future is False
    assert rule.future is None

    #: 점수가 없고, 줄 세우기에서 **뒤로** 간다. 0 도 패배도 아니다.
    candidate = SearchCandidate(action=action, status=SimulationStatus.UNKNOWN)
    assert candidate.value is None
    assert candidate.comparable is False
    assert candidate.ordering_key()[0] == 1
    assert "나쁜 것이 아니라" in (SearchCandidate.ordering_key.__doc__ or "")

    #: ``agent/`` 는 ``UnimplementedRule`` 자체를 **읽지 않는다.**
    for path in sorted((PROJECT_ROOT / "agent").rglob("*.py")):
        assert "UnimplementedRule" not in path.read_text(encoding="utf-8"), path


def test_16_no_production_code_converts_a_missing_rule_into_a_verdict():
    """
    **§10 · §18 — 잘못된 변환이 있는지 AST 로 찾는다.**

    네 가지를 찾았고 **하나도 없다.**

    - ``RULE_NOT_IMPLEMENTED`` → ``FALSE`` / ``INVALID``
    - ``UNKNOWN`` → ``FALSE``
    - ``INFORMATION_UNAVAILABLE`` → ``RULE_NOT_IMPLEMENTED``
    - ``RULE_NOT_IMPLEMENTED`` → ``EXECUTION_FORBIDDEN``

    ``RULE_NOT_IMPLEMENTED`` 를 ``ValidationResult.invalid(...)`` 에 넣는
    production 호출이 **0건**임을 확인한다 — 들어가면 미구현이 거부가 된다.
    """
    offenders = []
    for pkg in ("engine", "agent"):
        for path in sorted((PROJECT_ROOT / pkg).rglob("*.py")):
            rel = str(path.relative_to(PROJECT_ROOT))
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (
                    func.attr
                    if isinstance(func, ast.Attribute)
                    else (func.id if isinstance(func, ast.Name) else "")
                )
                if name not in {"invalid", "refuse", "forbid"}:
                    continue
                text = " ".join(_unparse(a) for a in node.args)
                if "RULE_NOT_IMPLEMENTED" in text or "COST_NOT_IMPLEMENTED" in text:
                    offenders.append(f"{rel}:{node.lineno} {name}({text[:60]})")
    assert offenders == [], offenders

    #: ``ValidationResult.unknown`` 만 ``missing_rule`` 을 받는다 — 거부에는
    #: 규칙 이름을 적을 자리가 없다.
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
    assert "unknown" in takes_missing_rule
    assert "invalid" not in takes_missing_rule
    assert "valid" not in takes_missing_rule


def test_17_the_distinctions_from_phase_3e24_to_3e34_still_hold():
    """
    **§21 regression — 앞선 열한 Phase 가 세운 구분이 그대로인지.**
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

    #: 상태 수가 늘지 않았다 — 이번 Phase 가 새 enum 을 만들지 않았다.
    assert len(ConditionResult) == 3
    assert len(ActionValidity) == 3
    assert len(ValidationCode) == 48
    assert len(SimulationStatus) == 5

    #: ``Requirement`` 는 조건을 반드시 받는다 (3-E-34).
    condition_field = next(
        f for f in dataclasses.fields(Requirement) if f.name == "condition"
    )
    assert condition_field.default is dataclasses.MISSING
