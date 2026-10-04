"""
Phase 3-E-26 — UNKNOWN / ValidationCode 정합성 최소 수정의 회귀 시험.

3-E-24 와 3-E-25 가 **측정**한 결함을 3-E-26 이 고쳤다. 이 파일은 고친 것이
되돌아가지 않는지 지키고, **고치지 않기로 한 것도 그 자리에 그대로 있는지**
적어 둔다 (측정값은 주석에 남긴다 — 나중에 숫자가 변하면 그것이 신호다).

고친 것 — 이미 있는 코드를 **의미가 맞는 자리에 연결**했을 뿐이고, 새
enum · 새 status · 새 계층은 하나도 만들지 않았다.

1. ``TriggerCollector._judge`` 조건 거짓
   ``RULE_NOT_IMPLEMENTED`` → ``CANDIDATE_NOT_ELIGIBLE``
2. ``TriggerCollector._judge`` 출처 금지
   ``RULE_NOT_IMPLEMENTED`` → ``EXECUTION_FORBIDDEN``
3. ``TriggerEligibilityJudge._trigger_condition`` 조건 거짓 (같은 사실 · 같은 문장)
   ``RULE_NOT_IMPLEMENTED`` → ``CANDIDATE_NOT_ELIGIBLE``
4. ``EffectActivator._check_condition`` 조건 UNKNOWN
   → 원인이 **없는 규칙**이면 ``RULE_NOT_IMPLEMENTED``, **없는 정보**면
   ``INFORMATION_UNAVAILABLE``
5. ``EffectExecutor._check_activation_condition`` — 4 와 **같은 태도**.
   발동기의 docstring 이 "실행기와 같은 태도" 라고 적고 있으므로, 한쪽만
   고치면 같은 정의가 두 계층에서 다른 뜻이 된다.

**가장 중요한 불변식**: 네 번째·다섯 번째는 ``UNKNOWN`` 안에서 이유만
갈랐다. 판정(``validity`` · ``status``)은 한 칸도 움직이지 않았다.
"""

import ast
import collections
import pathlib

import pytest

from engine.activation import ActivationStatus, EffectActivator
from engine.action import PlayerAction
from engine.chain import Chain
from engine.condition import (
    Always,
    ConditionResult,
    IsMonster,
    UnimplementedRule,
)
from engine.effect import (
    DrawOperation,
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectImplementationRegistry,
    EffectExecutor,
    EffectProvenance,
    ResolutionContext,
    ResolutionStatus,
    CardDrawn,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
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
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

MINE, THEIRS = 0, 1
WATCHER = 1000
"""트리거를 등록할 카드. 이 카드의 **의미를 주장하지 않는다** — 껍데기다."""
PLAIN = 1001
LAB = 2511
"""synthetic 정의의 껍데기. 실제 카드의 의미를 주장하지 않는다."""

SYNTHETIC = EffectRef(LAB, 0)
WATCHED = EffectRef(WATCHER, 0)

#: 테스트가 명시적으로 건네는 허가. 발동 타이밍 계층을 대신하지 않는다.
GRANTED = ValidationResult.valid("테스트가 발동 타이밍을 허가했다")


# ======================================================================
# 판 — 셔플하지 않는다
# ======================================================================


def new_state() -> GameState:
    game = GameState.create(
        decks=(
            [WATCHER, WATCHER, WATCHER, PLAIN, PLAIN, PLAIN, PLAIN, PLAIN],
            [PLAIN, PLAIN, PLAIN, PLAIN, PLAIN],
        ),
    )
    game.draw(MINE, 4)
    game.draw(THEIRS, 2)
    game.move(game.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.move(
        game.player(THEIRS).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=MINE)


# ======================================================================
# 도구 — 전부 기존 계층을 그대로 부른다
# ======================================================================


def watching(condition=None) -> TriggerSpec:
    return TriggerSpec(
        WATCHED,
        TimingPoint.CARD_DRAWN,
        condition=condition,
        activates_from=frozenset({Zone.HAND, Zone.MZONE}),
    )


def drawn_event() -> TimingEvent:
    return TimingEvent.from_delta(CardDrawn(MINE, InstanceId(2)))


def synthetic(*, activation=None, provenance=None) -> EffectDefinition:
    """패를 1장 뽑는 모양만 가진 정의. 대상이 없어서 흔들릴 것이 없다."""
    return EffectDefinition(
        effect_ref=SYNTHETIC,
        source_card_id=LAB,
        operations=(DrawOperation(1),),
        activation=activation,
        provenance=provenance or EffectProvenance.official_lua(),
    )


def watched_definition(*, activation=None, provenance=None) -> EffectDefinition:
    """``watching()`` 이 가리키는 ``effect_ref`` 를 가진 같은 모양의 정의."""
    return EffectDefinition(
        effect_ref=WATCHED,
        source_card_id=WATCHER,
        operations=(DrawOperation(1),),
        activation=activation,
        provenance=provenance or EffectProvenance.official_lua(),
    )


def activator(definition: EffectDefinition) -> EffectActivator:
    return EffectActivator(
        EffectDefinitionRegistry((definition,)),
        EffectImplementationRegistry((definition.effect_ref,)),
    )


def executor(definition: EffectDefinition) -> EffectExecutor:
    registry = EffectImplementationRegistry()
    registry.register(definition.effect_ref)
    return EffectExecutor(registry)


def activate(state: GameState, definition: EffectDefinition):
    source = state.player(MINE).monster_zone[0].instance_id
    action = PlayerAction.activate_effect(
        actor=MINE, source=source, effect_ref=definition.effect_ref
    )
    return activator(definition).activate(
        state, Chain(), action, authorization=GRANTED
    )


def resolve(state: GameState, definition: EffectDefinition):
    context = ResolutionContext(definition.effect_ref, controller=MINE)
    return executor(definition).execute(state, definition, context)


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


# ======================================================================
# A. 트리거 계층 — 거부는 거부로, 금지는 금지로
# ======================================================================


def test_01_a_false_condition_is_a_refusal_not_a_missing_rule(view):
    """
    조건을 **끝까지 보고 거짓을 받았다.** 이것은 "이 엔진이 못 한다" 가
    아니라 확실한 거부다.

    ``CANDIDATE_NOT_ELIGIBLE`` 은 이미 ``engine/effect/targeting.py`` ·
    ``engine/cost/validation.py`` ·  ``engine/effect/executor.py`` 가
    ``ConditionResult.FALSE`` 에 쓰고 있던 코드다 — 새로 만들지 않았다.
    """
    collection = TriggerCollector(
        view, TriggerRegistry((watching(Always(ConditionResult.FALSE)),))
    ).collect(drawn_event())

    assert collection.ineligible, "거짓 조건인데 거부 후보가 없다"
    for candidate in collection:
        assert candidate.status is TriggerStatus.INELIGIBLE
        assert candidate.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
        assert candidate.code is not ValidationCode.RULE_NOT_IMPLEMENTED
        assert candidate.is_candidate is False


def test_02_a_forbidden_source_uses_the_code_that_forbids(view):
    """
    출처 금지(ADR-004)를 **금지 코드로** 적는다.

    까닭이 구조에 있다: 금지를 알아보는 유일한 자리인
    ``GateVerdict.forbids`` 는 ``code is EXECUTION_FORBIDDEN`` 으로
    판단한다. 수집기가 다른 코드로 적으면 **그 금지는 보이지 않는다.**
    """
    forbidden = watched_definition(provenance=EffectProvenance.text_derived())
    collection = TriggerCollector(
        view,
        TriggerRegistry((watching(),)),
        EffectDefinitionRegistry((forbidden,)),
    ).collect(drawn_event())

    assert collection.candidates, "후보가 하나도 없다"
    for candidate in collection:
        assert candidate.status is TriggerStatus.FORBIDDEN
        assert candidate.code is ValidationCode.EXECUTION_FORBIDDEN
        assert "ADR-004" in candidate.reason
        #: 수집기의 코드를 그대로 싣고도 금지로 읽힌다 — 두 계층이 이어질 때
        #: 필요한 성질이다.
        from engine.trigger import GateVerdict

        carried = GateVerdict(
            EligibilityGate.EXECUTION_AUTHORITY,
            ValidationResult.invalid(candidate.code, candidate.reason),
        )
        assert carried.forbids is True


def test_03_the_collector_and_the_gate_agree_on_a_false_condition(view):
    """
    **같은 사실을 두 계층이 같은 코드로 말한다.**

    수집기(``_judge``)와 판정 관문(``_trigger_condition``)은 같은 조건을
    각자 평가한다. 어긋나 있으면 한쪽을 고쳐도 다른 쪽이 남는다.
    """
    spec = watching(Always(ConditionResult.FALSE))
    collection = TriggerCollector(view, TriggerRegistry((spec,))).collect(drawn_event())
    candidate = collection.candidates[0]

    eligibility = TriggerEligibilityJudge(view).judge(candidate, spec, drawn_event())
    gate = next(
        verdict
        for verdict in eligibility.gates
        if verdict.gate is EligibilityGate.TRIGGER_CONDITION
    )

    assert eligibility.status is TriggerStatus.INELIGIBLE
    assert gate.validity is ActionValidity.INVALID
    assert gate.code is candidate.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE


def test_04_an_unjudgeable_trigger_condition_is_still_unknown(view):
    """
    §6 — **고친 것은 거부의 이유뿐이다.** 모름은 건드리지 않았다.

    ``UnimplementedRule`` 이 걸린 후보는 그대로 ``UNKNOWN`` 이고, 거부로도
    허가로도 접히지 않는다.
    """
    collection = TriggerCollector(
        view, TriggerRegistry((watching(UnimplementedRule("체인 위의 카드 수")),))
    ).collect(drawn_event())

    assert collection.undecided
    assert collection.ineligible == ()
    for candidate in collection:
        assert candidate.status is TriggerStatus.UNKNOWN
        assert candidate.status is not TriggerStatus.INELIGIBLE
        assert candidate.code is not ValidationCode.CANDIDATE_NOT_ELIGIBLE
        assert candidate.code is not ValidationCode.EXECUTION_FORBIDDEN
        assert candidate.is_candidate is False


# ======================================================================
# B. 발동 · 해결 계층 — 모르는 **까닭**을 가른다
# ======================================================================


def test_05_a_missing_rule_is_not_missing_information(state):
    """
    **"규칙이 없어서 모른다" 와 "정보가 없어서 모른다" 는 다른 사실이다.**

    앞은 코드가 생겨야 풀리고 뒤는 판이 바뀌면 풀린다.
    ``ActionValidator._check_requirements`` 가 이미 ``missing_rules`` 로
    가르고 있었고, 발동기는 그것을 하지 않고 있었다 (3-E-24 발견).
    """
    definition = synthetic(activation=UnimplementedRule("체인 위의 카드 수"))
    before = state.state_hash()

    result = activate(state, definition)

    assert result.status is ActivationStatus.CONDITION_UNKNOWN
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert result.code is not ValidationCode.INFORMATION_UNAVAILABLE
    assert "체인 위의 카드 수" in (result.missing or "")
    assert len(result.chain) == 0
    assert state.state_hash() == before


def test_06_missing_information_keeps_its_own_code(state):
    """
    같은 ``UNKNOWN`` 이지만 까닭이 다르다 — 이 조건이 묻는 카드는 관측에
    없다. 빠진 규칙이 없으므로 ``INFORMATION_UNAVAILABLE`` 그대로다.
    """
    definition = synthetic(activation=IsMonster(InstanceId(9999)))
    before = state.state_hash()

    result = activate(state, definition)

    assert result.status is ActivationStatus.CONDITION_UNKNOWN
    assert result.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert result.code is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert len(result.chain) == 0
    assert state.state_hash() == before


def test_07_the_activator_and_the_executor_say_the_same_thing(state):
    """
    발동기의 ``_check_condition`` docstring 은 "실행기와 같은 태도이고,
    여기서 다르게 읽으면 같은 정의가 두 곳에서 다른 뜻이 된다" 고 적는다.

    **그 약속을 시험으로 고정한다** — 한쪽만 고치면 여기서 깨진다.
    """
    for condition, expected in (
        (UnimplementedRule("체인 위의 카드 수"), ValidationCode.RULE_NOT_IMPLEMENTED),
        (IsMonster(InstanceId(9999)), ValidationCode.INFORMATION_UNAVAILABLE),
    ):
        definition = synthetic(activation=condition)

        activated = activate(new_state(), definition)
        resolved = resolve(new_state(), definition)

        assert activated.status is ActivationStatus.CONDITION_UNKNOWN
        assert resolved.status is ResolutionStatus.CONDITION_UNKNOWN
        assert activated.code is resolved.code is expected


def test_08_the_split_never_turns_unknown_into_a_verdict(state):
    """
    §6 의 핵심 — 코드를 갈랐지만 **판정은 한 칸도 움직이지 않았다.**

    ``UnimplementedRule`` 은 여전히 ``CONDITION_UNKNOWN`` 이고, 거짓 조건만
    ``CONDITION_FALSE`` 다. 모름이 거부로 접히지 않는다.
    """
    unknown = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))

    assert unknown.status is ActivationStatus.CONDITION_UNKNOWN
    assert unknown.status is not ActivationStatus.CONDITION_FALSE
    assert false.status is ActivationStatus.CONDITION_FALSE
    #: 둘 다 판을 바꾸지 않는다. 모름도 거부도 **실행이 아니다.**
    assert len(unknown.chain) == len(false.chain) == 0


# ======================================================================
# C. 범위 — 무엇을 만들지 않았고, 무엇을 남겼는가
# ======================================================================


def test_09_no_new_vocabulary_was_added():
    """
    §7 — 새 enum · 새 status · 새 판정 어휘를 하나도 만들지 않았다.

    측정값(3-E-24 에서 센 그대로): ``ValidationCode`` 48개.
    """
    assert len(list(ValidationCode)) == 48
    #: 고칠 때 쓴 코드 셋은 전부 **이미 있던** 것이다.
    for code in (
        ValidationCode.CANDIDATE_NOT_ELIGIBLE,
        ValidationCode.EXECUTION_FORBIDDEN,
        ValidationCode.RULE_NOT_IMPLEMENTED,
        ValidationCode.INFORMATION_UNAVAILABLE,
    ):
        assert isinstance(code, ValidationCode)
    #: 상태 어휘도 그대로다.
    assert len(list(ActionValidity)) == 3
    assert len(list(TriggerStatus)) == 4


def test_10_the_agent_layer_treats_both_unknown_codes_alike():
    """
    §8 · §9 — **ValidationCode 값으로 분기하는 production 자리는 두 곳이다.**

    1. ``GateVerdict.forbids`` — ``is EXECUTION_FORBIDDEN``
    2. ``agent/simulation.py`` 의 ``_UNKNOWN_CODES`` — 집합 멤버십

    두 번째가 이번 수정의 안전을 결정한다. ``RULE_NOT_IMPLEMENTED`` 와
    ``INFORMATION_UNAVAILABLE`` 이 **둘 다** 그 집합에 있으므로, 둘을 가른
    것은 시뮬레이터의 분류를 바꾸지 않는다.
    """
    from agent.simulation import SimulationStatus, _UNKNOWN_CODES

    assert ValidationCode.RULE_NOT_IMPLEMENTED in _UNKNOWN_CODES
    assert ValidationCode.INFORMATION_UNAVAILABLE in _UNKNOWN_CODES

    #: 거부 쪽 코드는 그 집합에 없다 — 그래서 ``REFUSED`` 로 분류된다. 트리거
    #: 계층이 이어지는 날 **그것이 맞는 답이다**: 조건이 거짓인 것과 출처가
    #: 금지된 것은 "규칙이 아직 없다" 가 아니다.
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE not in _UNKNOWN_CODES
    assert ValidationCode.EXECUTION_FORBIDDEN not in _UNKNOWN_CODES

    #: 그리고 ``UNKNOWN`` 은 0점이 아니다 — 탐색이 점수를 **주지 않는다.**
    assert SimulationStatus.UNKNOWN.gives_a_future is False
    search = source_of("agent/search.py")
    assert "0 점도" in search  # "점수가 없다. 0 점도, 최저 … 아니다"


def test_11_the_remaining_invalid_sites_are_the_measured_three():
    """
    **고치지 않은 것을 숨기지 않는다.**

    ``INVALID`` 판정에 ``RULE_NOT_IMPLEMENTED`` 를 붙이는 자리가 **3곳**
    남았다. 셋 다 "조건이 거짓" · "이 사건과 무관" 이라는 사실이고, 그것을
    말하는 코드가 enum 에 **없다.** §7 이 새 enum 을 금지하므로 억지로
    맞추지 않았다 — 판정(``CONDITION_FALSE`` · ``INVALID``)이 사실을
    정확히 싣고 있어서 지금 해가 없다.

    (3-E-26 이전에는 6곳이었다. 숫자가 늘면 새 자리가 생긴 것이다.)
    """
    #: **자리마다 센다.** 한 파일 안에 같은 모양이 하나 더 생기는 것이 바로
    #: 되돌아가는 모습이라서, 집합으로 묶으면 그것을 놓친다.
    expected = {
        ("engine/activation.py", "ActivationStatus.CONDITION_FALSE"): 1,
        ("engine/effect/executor.py", "ResolutionStatus.CONDITION_FALSE"): 1,
        ("engine/trigger.py", "ActionValidity.INVALID"): 1,  # _event_relation 하나뿐
    }
    found: "collections.Counter[tuple[str, str]]" = collections.Counter()
    root = PROJECT_ROOT / "engine"
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            names = [
                ast.unparse(inner)
                for argument in list(node.args) + [kw.value for kw in node.keywords]
                for inner in ast.walk(argument)
                if isinstance(inner, ast.Attribute)
            ]
            if not any(n.endswith("RULE_NOT_IMPLEMENTED") for n in names):
                continue
            verdicts = {
                n
                for n in names
                if n.endswith("INVALID")
                or n.endswith("CONDITION_FALSE")
                or "INELIGIBLE" in n
            }
            for verdict in verdicts:
                found[(str(path.relative_to(PROJECT_ROOT)), verdict)] += 1

    assert dict(found) == expected, f"측정된 3곳과 다르다: {dict(found)}"


def test_12_the_duel_loop_still_does_not_import_the_trigger_layer():
    """
    §8 — 트리거 계층은 **여전히 잠들어 있다** (3-E-20 에서 측정).

    ``engine/duel.py`` 가 ``engine.trigger`` · ``engine.timing`` ·
    ``engine.event_pipeline`` 을 import 하지 않으므로, 수정 ①②③ 의 코드는
    ``DuelStep.code`` 에 닿지 않는다. 즉 이번 Phase 는 **production 동작을
    바꾸지 않았고**, 바뀐 것은 ④⑤ 의 이유뿐이다 (그리고 §10 이 보인 대로
    시뮬레이터의 분류도 그대로다).
    """
    tree = ast.parse(source_of("engine/duel.py"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    for dormant in ("engine.trigger", "engine.timing", "engine.event_pipeline"):
        assert dormant not in imported


def test_13_rule_not_implemented_now_says_what_it_means():
    """
    드리프트의 뿌리는 ``RULE_NOT_IMPLEMENTED`` 에 **docstring 이 없었던**
    것이다 (3-E-24 측정: 62곳에서 최소 네 뜻으로 쓰였다). 뜻을 적어 두면
    다음 사람이 같은 자리에 같은 실수를 하지 않는다.
    """
    #: enum 멤버의 docstring 은 런타임에 남지 않는다 (클래스 docstring 으로
    #: 가려진다). 그래서 **원본에서** 읽는다.
    source = source_of("engine/validation.py")
    after = source.split('RULE_NOT_IMPLEMENTED = "rule_not_implemented"')[1]
    doc = " ".join(after.split('"""')[1].split())
    assert "이 엔진이 아직 못 한다" in doc
    #: 섞이던 뜻들에 각각 어디로 가야 하는지 적혀 있다.
    for alternative in (
        "INFORMATION_UNAVAILABLE",
        "EXECUTION_FORBIDDEN",
        "CANDIDATE_NOT_ELIGIBLE",
    ):
        assert alternative in doc
