r"""
Phase 3-E-38 — M1 · M2 최소 수정의 회귀 시험, M3 dormant 기록.

3-E-37 이 "기존 ``ValidationCode`` 로 정확히 표현된다" 를 측정했고, 이 Phase 가
**네 자리**를 그 코드로 바꿨다. 이 파일은 바꾼 것이 되돌아가지 않는지 지키고,
**바꾸지 않기로 한 것도 그 자리에 그대로 있는지** 적어 둔다.

고친 것 — 이미 있는 코드를 **의미가 맞는 자리에 연결**했을 뿐이고, 새
``ValidationCode`` · 새 status · 새 계층을 하나도 만들지 않았다.

======  ===========================================  =========================
M1-a    ``EffectActivator._check_condition`` 조건 거짓   ``RULE_NOT_IMPLEMENTED``
        → ``CANDIDATE_NOT_ELIGIBLE``
M1-b    ``EffectExecutor._check_condition`` 조건 거짓    같음
M2-a    ``EffectActivator._check_authority``            ``RULE_NOT_IMPLEMENTED``
        ``FORBIDDEN_SOURCE`` → ``EXECUTION_FORBIDDEN``
M2-b    ``EffectExecutor._check_authority`` 같음        같음
======  ===========================================  =========================

고치지 않은 것

- **M3** (``engine/trigger.py`` ``_event_relation``) — 트리거 파이프라인이
  dormant 다. ``TriggerSpec`` · ``TriggerRegistry`` production 생성이 **0곳**
  이고 ``engine/duel.py`` 는 "trigger" 를 **한 번도** 쓰지 않는다. 게다가
  ``judge_all`` 은 사건이 **이미 맞은** 후보만 넘기므로 그 ``INVALID`` 분기는
  공개 ``judge()`` 를 직접 부를 때만 닿는다 (production 호출 0곳).
- **``engine/effect/resolution.py``** 의 같은 출처 금지 (``UnimplementedResolver``)
  — 이번 Phase 의 범위(M1·M2 가 지목한 네 자리) 밖이고 production 생성이
  **0곳**이다. 범위를 넓히지 않았다.
- **J\* 12곳** (구조 오류 · 예외 · 응답 거절) — 맞는 ``ValidationCode`` 가
  **없다.** 새 멤버를 만들지 않는다.

**가장 중요한 불변식**: 이유만 바꿨다. 판정(``status``) · 판
(``state_hash``) · 난수(RNG) · 합법 행동 · 탐색 순위는 **한 칸도 움직이지
않았다** (``test_13``~``test_19``).
"""

import ast
import pathlib

import pytest

from agent.search import SearchCandidate, SearchPolicy
from agent.simulation import SimulationStatus, Simulator, _UNKNOWN_CODES
from engine.action import PlayerAction
from engine.activation import ActivationStatus, _AVAILABILITY_REFUSAL, _UNKNOWN_STATUSES
from engine.condition import Always, ConditionResult, IsMonster, UnimplementedRule
from engine.duel import Duel
from engine.effect import EffectProvenance
from engine.effect.definition import ExecutionAvailability
from engine.effect.resolution import ResolutionStatus
from engine.ids import InstanceId
from engine.validation import ActionValidity, ValidationCode, ValidationResult

from tests.conftest import requires_official_db

from tests.test_validation_code_consistency import (
    activate,
    new_state,
    resolve,
    synthetic,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MINE = 0

#: 트리거 파이프라인이 dormant 임을 보이는 생성자들 — production 생성이 0 이어야 한다.
DORMANT_CONSTRUCTORS = ("TriggerSpec", "TriggerRegistry")


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def method_source(path: str, class_name: str, method: str) -> str:
    """
    한 메서드의 **본문만** 떼어 온다.

    파일 전체를 문자열로 세면 **같은 코드를 쓰는 다른 자리**까지 걸린다 —
    이 파일을 처음 쓸 때 실제로 그렇게 틀렸다 (``executor.py`` 의
    ``CANDIDATE_NOT_ELIGIBLE`` 은 이번 수정 말고도 **세 자리**에서 이미
    쓰이고 있었다). 자리를 지목할 때는 구문으로 집는다.
    """
    tree = ast.parse(source_of(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == method
                ):
                    return ast.unparse(child)
    raise AssertionError(f"{path}: {class_name}.{method} 가 없다")


def forbidden_definition():
    """``TEXT_DERIVED`` 출처 — ADR-004 가 실행을 금지한다."""
    return synthetic(
        activation=None,
        provenance=EffectProvenance.text_derived("공식 텍스트에서 유추했다"),
    )


# ======================================================================
# A · B · C — M1
# ======================================================================


def test_01_a_false_condition_is_a_candidate_refusal_in_the_activation_layer():
    """
    **A (§15): M1-a — 조건이 ``FALSE`` 로 확정되면 ``CANDIDATE_NOT_ELIGIBLE``.**

    평가기가 끝까지 보고 거짓을 받았으므로 **규칙은 있었다.** "이 엔진이
    아직 못 한다" 는 코드를 붙이면 판정과 이유가 어긋난다.
    """
    result = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))

    assert result.status is ActivationStatus.CONDITION_FALSE
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert result.code is not ValidationCode.RULE_NOT_IMPLEMENTED
    #: 상태가 "모른다" 쪽이 아니고, 코드도 이제 "모른다" 묶음이 아니다.
    assert result.status not in _UNKNOWN_STATUSES
    assert result.code not in _UNKNOWN_CODES
    #: 규칙 이름은 적지 않는다 — 모르는 것이 아니다.
    assert result.missing is None


def test_02_a_false_condition_is_a_candidate_refusal_in_the_resolution_layer():
    """**A (§15): M1-b — 해결 계층도 같은 코드다.**"""
    result = resolve(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))

    assert result.status is ResolutionStatus.CONDITION_FALSE
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert result.code not in _UNKNOWN_CODES


def test_03_the_two_layers_say_the_same_thing_about_a_false_condition():
    """
    **두 계층이 같은 코드를 써야 한다** (3-E-26 이 맞춰 둔 약속).

    한쪽만 고치면 같은 정의가 두 곳에서 다른 이유를 낸다.
    """
    false = synthetic(activation=Always(ConditionResult.FALSE))
    assert activate(new_state(), false).code is resolve(new_state(), false).code

    #: 소스에서도 둘이 같은 말을 적는다.
    for rel in ("engine/activation.py", "engine/effect/executor.py"):
        source = source_of(rel)
        assert "ValidationCode.CANDIDATE_NOT_ELIGIBLE" in source, rel
        assert "확실한 거부이고 미구현이 아니다" in source, rel


def test_04_an_unknown_condition_keeps_its_old_codes():
    """
    **B (§15): ``UNKNOWN`` → ``CANDIDATE_NOT_ELIGIBLE`` 변환은 없다.**

    모름의 두 까닭이 **그대로**다 — 이것이 이번 수정에서 가장 지켜야 할 선이다.
    """
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))

    assert rule.status is info.status is ActivationStatus.CONDITION_UNKNOWN
    assert rule.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE
    #: **어느 쪽도 거부 코드로 바뀌지 않았다.**
    assert rule.code is not ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert info.code is not ValidationCode.CANDIDATE_NOT_ELIGIBLE

    #: 해결 계층도 같다.
    assert resolve(
        new_state(), synthetic(activation=UnimplementedRule("없는 규칙"))
    ).code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert resolve(
        new_state(), synthetic(activation=IsMonster(InstanceId(9999)))
    ).code is ValidationCode.INFORMATION_UNAVAILABLE


def test_05_a_true_condition_still_activates():
    """**C (§15): ``TRUE`` 는 그대로 통과한다.**"""
    for activation in (Always(), None):
        result = activate(new_state(), synthetic(activation=activation))
        assert result.status is ActivationStatus.ACTIVATED
        assert result.code is ValidationCode.OK
        assert len(result.chain) == 1


# ======================================================================
# D · E · F — M2
# ======================================================================


def test_06_a_text_derived_source_is_execution_forbidden_in_both_layers():
    """
    **D (§15): M2 — ``TEXT_DERIVED`` 출처는 ``EXECUTION_FORBIDDEN``.**

    "모른다" 가 아니라 **"이 근거로는 절대 실행하지 않는다"** 다 (ADR-004).
    그 멤버의 docstring 이 바로 이 경우를 위해 쓰여 있다.
    """
    forbidden = forbidden_definition()
    activated = activate(new_state(), forbidden)
    resolved = resolve(new_state(), forbidden)

    assert activated.status is ActivationStatus.FORBIDDEN
    assert resolved.status is ResolutionStatus.FORBIDDEN
    assert activated.code is ValidationCode.EXECUTION_FORBIDDEN
    assert resolved.code is ValidationCode.EXECUTION_FORBIDDEN
    assert activated.code is not ValidationCode.RULE_NOT_IMPLEMENTED
    #: 설명과 "없는 것" 은 그대로다 — 이유 코드만 정확해졌다.
    assert activated.missing == "executable implementation from official script"


def test_07_the_other_two_availabilities_keep_rule_not_implemented():
    """
    **E (§15): ``TEXT_DERIVED`` 가 아닌 갈래는 바뀌지 않았다.**

    미검증(``UNVERIFIED``)과 미등록(``NO_IMPLEMENTATION``)은 **모른다** 쪽이고
    그대로 ``RULE_NOT_IMPLEMENTED`` 다. 세 갈래를 한 줄로 뭉개지 않았다.
    """
    expected = {
        ExecutionAvailability.FORBIDDEN_SOURCE: ValidationCode.EXECUTION_FORBIDDEN,
        ExecutionAvailability.UNVERIFIED: ValidationCode.RULE_NOT_IMPLEMENTED,
        ExecutionAvailability.NO_IMPLEMENTATION: ValidationCode.RULE_NOT_IMPLEMENTED,
    }
    assert set(_AVAILABILITY_REFUSAL) == set(expected)
    for availability, code in expected.items():
        status, actual, reason, missing = _AVAILABILITY_REFUSAL[availability]
        assert actual is code, availability
        assert reason and missing

    #: 표가 네 칸짜리다 — 코드가 **한 자리에서** 상태와 함께 정해진다.
    for entry in _AVAILABILITY_REFUSAL.values():
        assert len(entry) == 4
        assert isinstance(entry[1], ValidationCode)

    #: 해결 계층의 세 갈래도 **그 자리에서** 확인한다.
    #: ``ResolutionStatus`` 에는 ``UNVERIFIED`` 멤버가 **없다** — 미검증은
    #: ``ResolutionStatus.UNKNOWN`` 으로 간다. 이 파일을 처음 쓸 때 상태
    #: 이름을 발동 계층에서 그대로 옮겨 적어 틀렸고, 소스를 읽어 고쳤다.
    assert not hasattr(ResolutionStatus, "UNVERIFIED")
    authority = method_source(
        "engine/effect/executor.py", "EffectExecutor", "_check_authority"
    )
    #: 금지는 **한 갈래**뿐이고, 나머지 두 갈래가 "모른다" 코드를 그대로 쓴다.
    assert authority.count("ValidationCode.EXECUTION_FORBIDDEN") == 1
    assert authority.count("ValidationCode.RULE_NOT_IMPLEMENTED") == 2
    assert "ResolutionStatus.UNKNOWN" in authority
    assert "ResolutionStatus.NOT_IMPLEMENTED" in authority


def test_08_a_forbidden_source_is_not_missing_information():
    """
    **F (§15): ``TEXT_DERIVED`` 를 숨은 정보와 혼동하지 않는다.**

    세 코드가 모두 다른 멤버이고, 가려진 정보는 여전히 ``UNKNOWN`` 계열이다.
    """
    for name in (
        "RULE_NOT_IMPLEMENTED",
        "INFORMATION_UNAVAILABLE",
        "CARD_DEFINITION_UNAVAILABLE",
        "HIDDEN_CARD",
    ):
        assert getattr(ValidationCode, name) is not ValidationCode.EXECUTION_FORBIDDEN

    #: 가려진 카드를 묻는 조건은 **금지가 아니다.**
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert info.code is not ValidationCode.EXECUTION_FORBIDDEN
    assert info.unchecked and "관측에 보이지 않음" in info.unchecked[0]


# ======================================================================
# G · H · I — M3
# ======================================================================


def test_09_the_trigger_pipeline_is_dormant_so_m3_was_left_alone():
    """
    **G · H (§15): M3 는 dormant 이므로 production 을 고치지 않았다.**

    ``TriggerSpec`` · ``TriggerRegistry`` 를 production 에서 **한 번도 만들지
    않는다.** 그 둘 없이는 수집기도 판정기도 돌지 않는다.
    """
    production: dict[str, list[str]] = {name: [] for name in DORMANT_CONSTRUCTORS}
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
                and node.func.id in production
            ):
                production[node.func.id].append(f"{rel}:{node.lineno}")
    for name, sites in production.items():
        assert sites == [], f"{name} 이 production 에서 생성되기 시작했다: {sites}"

    #: 그리고 ``Duel`` 은 트리거를 **한 번도 언급하지 않는다.**
    duel = source_of("engine/duel.py")
    assert "trigger" not in duel
    assert "Trigger" not in duel


def test_10_m3_still_carries_the_old_code_and_that_is_recorded_not_hidden():
    """
    **I (§15): M3 를 고치지 않았다는 사실을 숨기지 않는다.**

    ``_event_relation`` 은 여전히 ``ActionValidity.INVALID`` 에
    ``RULE_NOT_IMPLEMENTED`` 를 붙인다. dormant 라서 지금 해가 없고, "그
    사건에 반응하지 않는다" 를 ``INVALID`` 로 적는 것이 맞는지 자체가 구조
    질문이므로 이 Phase 의 범위 밖이다.
    """
    source = source_of("engine/trigger.py")
    index = source.index("EligibilityGate.EVENT_RELATION")
    window = source[index : index + 700]
    assert "ActionValidity.INVALID" in window
    assert "ValidationCode.RULE_NOT_IMPLEMENTED" in window

    #: 그리고 ``_refusal_code`` 의 기본값이 여전히 정확한 답을 들고 있다.
    assert "return ValidationCode.CANDIDATE_NOT_ELIGIBLE" in source_of(
        "engine/trigger_chain.py"
    )


def test_11_the_dormant_resolver_was_left_alone_too():
    """
    **범위를 넓히지 않았다.** ``engine/effect/resolution.py`` 의 같은 출처
    금지는 ``UnimplementedResolver`` 안이고 production 생성이 0곳이다.
    M1·M2 가 지목한 네 자리에만 손댔다.
    """
    source = source_of("engine/effect/resolution.py")
    index = source.index("ResolutionStatus.FORBIDDEN")
    assert "ValidationCode.RULE_NOT_IMPLEMENTED" in source[index : index + 240]

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
                and node.func.id == "UnimplementedResolver"
            ):
                production.append(f"{rel}:{node.lineno}")
    assert production == []


# ======================================================================
# J · T — 고치지 않은 것 / 새 코드 없음
# ======================================================================


def test_12_genuine_unimplemented_rules_still_use_the_old_code():
    """
    **J (§15): 진짜 미구현은 그대로다.** 일괄 치환을 하지 않았다.
    """
    #: 정의 미등록 — ``NOT_IMPLEMENTED`` + 옛 코드.
    from engine.chain import Chain
    from engine.effect import EffectDefinitionRegistry, EffectImplementationRegistry
    from engine.activation import EffectActivator

    definition = synthetic(activation=None)
    state = new_state()
    result = EffectActivator(
        EffectDefinitionRegistry(()), EffectImplementationRegistry(())
    ).activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE,
            source=state.player(MINE).monster_zone[0].instance_id,
            effect_ref=definition.effect_ref,
        ),
        authorization=ValidationResult.valid("테스트가 허가했다"),
    )
    assert result.status is ActivationStatus.NOT_IMPLEMENTED
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED

    #: 그리고 그 코드가 여전히 널리 쓰인다 — 지운 것이 아니다.
    total = 0
    for pkg in ("engine", "agent"):
        for path in sorted((PROJECT_ROOT / pkg).rglob("*.py")):
            total += path.read_text(encoding="utf-8").count("RULE_NOT_IMPLEMENTED")
    assert total > 50


def test_13_no_new_validation_code_was_added():
    """**T (§15): ``ValidationCode`` 가 한 칸도 늘지 않았다.**"""
    assert len(ValidationCode) == 48
    for name in ("CONDITION_FALSE", "EXECUTION_ERROR", "INVALID_CONTEXT"):
        assert name not in ValidationCode.__members__
    #: 두 코드는 **이미 있던** 멤버다.
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE.value == "candidate_not_eligible"
    assert ValidationCode.EXECUTION_FORBIDDEN.value == "execution_forbidden"


# ======================================================================
# K · L — UNKNOWN_CODES / SimulationStatus
# ======================================================================


def test_14_the_unknown_codes_set_is_now_derived_from_the_engine_policy():
    """
    **K (§15): ``_UNKNOWN_CODES`` 의 멤버를 건드리지 않았다.**

    달라진 것은 **어떤 사실이 그 집합에 들어가는가**이고, 집합 자체는 그대로다.
    """
    #: .. note::
    #:    **다섯 → 일곱** (Phase 3-E-40). 3-E-38 이 이 줄을 쓸 때 집합은
    #:    ``agent/simulation.py`` 에 손으로 적힌 다섯이었고, 이 테스트의 요지는
    #:    "M1·M2 를 고치면서 이 집합을 건드리지 않았다" 였다 — **그 요지는
    #:    그대로 맞다.** 집합이 바뀐 것은 3-E-40 이 policy 를 엔진으로 옮기고
    #:    사본을 없앤 결과이고, 그때 ``HIDDEN_CARD`` ·
    #:    ``PRIORITY_STATE_STALE`` 이 빠져 있었다는 3-E-39 의 측정이 반영됐다.
    #:    M1·M2 의 두 코드는 **여전히 집합에 없다** (바로 아래).
    assert {code.name for code in _UNKNOWN_CODES} == {
        "RULE_NOT_IMPLEMENTED",
        "COST_NOT_IMPLEMENTED",
        "INFORMATION_UNAVAILABLE",
        "CARD_DEFINITION_UNAVAILABLE",
        "EFFECT_LIST_UNRELIABLE",
        "HIDDEN_CARD",
        "PRIORITY_STATE_STALE",
    }
    assert len(_UNKNOWN_CODES) == 7
    #: 두 거부 코드는 여전히 집합 **밖**이다 — 이 Phase 가 지킨 선이다.
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE not in _UNKNOWN_CODES
    assert ValidationCode.EXECUTION_FORBIDDEN not in _UNKNOWN_CODES


def test_15_the_two_fixed_facts_now_classify_as_refused_instead_of_unknown():
    """
    **L (§15): 이 수정의 유일한 관측 가능한 결과.**

    조건 거짓과 출처 금지가 시뮬레이션에서 ``UNKNOWN`` 이 아니라 ``REFUSED``
    로 분류된다. **그것이 정확한 분류다** — 둘 다 확실한 거부다.

    그리고 **순위는 바뀌지 않는다** (``test_17``).
    """
    for code in (
        ValidationCode.CANDIDATE_NOT_ELIGIBLE,
        ValidationCode.EXECUTION_FORBIDDEN,
    ):
        assert code not in _UNKNOWN_CODES  # → SimulationStatus.REFUSED

    #: 반대로 진짜 모름은 여전히 ``UNKNOWN`` 으로 간다.
    for code in (
        ValidationCode.RULE_NOT_IMPLEMENTED,
        ValidationCode.INFORMATION_UNAVAILABLE,
    ):
        assert code in _UNKNOWN_CODES

    #: 분류 로직 자체를 바꾸지 않았다.
    assert "step.code in _UNKNOWN_CODES" in source_of("agent/simulation.py")
    assert len(SimulationStatus) == 5


# ======================================================================
# M · N · O — GateVerdict / legal_actions / 탐색
# ======================================================================


def test_16_gate_verdict_still_reads_only_execution_forbidden_in_the_trigger_layer():
    """
    **M (§15): ``GateVerdict.forbids`` 를 건드리지 않았다.**

    그 독자는 트리거 계층의 ``GateVerdict`` 만 보고, 발동·해결 결과는 그
    타입이 아니다. M2 를 고쳐도 그 독자의 입력은 늘지 않는다.
    """
    from engine.trigger import GateVerdict

    assert "self.result.code is ValidationCode.EXECUTION_FORBIDDEN" in source_of(
        "engine/trigger.py"
    )
    result = activate(new_state(), forbidden_definition())
    assert not isinstance(result, GateVerdict)
    assert not hasattr(result, "forbids")


@requires_official_db
@pytest.mark.real_card
def test_17_legal_actions_and_search_are_unchanged(repository):
    """
    **N · O · P · Q (§15): 판 · 난수 · 합법 행동 · 탐색이 그대로다.**

    같은 seed 로 같은 시나리오를 돌려 측정한 값들이다. 이유만 바꾸는 수정이
    맞다면 여기 **아무것도** 달라지지 않아야 한다.
    """
    deck = [card.id for card in list(repository.all_cards())[:16]]
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=11)
    while duel.advance() is not None:
        pass

    #: 3-E-38 **전에** 측정한 값 그대로다.
    assert duel.state.state_hash() == (
        "5adaf2a465ee9f3d7e2b1e229adbb7465202f18e3cd36e4dd947fd162927af9e"
    )
    legal = duel.legal_actions()
    assert sorted(a.kind.value for a in legal.allowed) == ["end_phase"]
    assert sorted(w.kind.value for w in legal.withheld) == ["activate_card"]
    assert sorted({w.missing for w in legal.withheld if w.missing}) == [
        "activation-timing (Phase 2-C/2-F)"
    ]

    rng_before = duel.state.rng.getstate()
    policy = SearchPolicy().attach(Simulator(duel))
    chosen = policy.decide(duel.view(legal.seat), legal)
    decision = policy.last_decision

    assert len(decision.candidates) == 1
    assert decision.simulations == 1
    assert [c.status.value for c in decision.candidates] == ["supported"]
    assert sum(1 for c in decision.candidates if c.comparable) == 1
    assert str(chosen) == "end_phase P0"
    assert [list(c.ordering_key()[:3]) for c in decision.candidates] == [[0, -1, -1000]]

    #: **Q — 난수가 소비되지 않았다.**
    assert duel.state.rng.getstate() == rng_before
    #: **P — 판이 바뀌지 않았다.**
    assert duel.state.state_hash() == (
        "5adaf2a465ee9f3d7e2b1e229adbb7465202f18e3cd36e4dd947fd162927af9e"
    )


def test_18_the_fix_never_touches_the_board_or_the_rng():
    """
    **P · Q (§15): 네 자리 모두 판을 바꾸지 않고 난수를 쓰지 않는다.**
    """
    for activation, provenance in (
        (Always(ConditionResult.FALSE), None),
        (UnimplementedRule("없는 규칙"), None),
        (IsMonster(InstanceId(9999)), None),
        (None, EffectProvenance.text_derived("유추")),
    ):
        definition = synthetic(activation=activation, provenance=provenance)
        state = new_state()
        before = state.state_hash()
        result = activate(state, definition)
        assert result.status is not ActivationStatus.ACTIVATED
        assert state.state_hash() == before
        assert result.deltas == ()
        assert len(result.chain) == 0


# ======================================================================
# R — hidden information
# ======================================================================


def test_19_hidden_information_did_not_become_forbidden():
    """
    **R (§15): 가려진 정보가 금지로 바뀌지 않았다.**

    상대 패는 여전히 ``card_id`` 를 보여 주지 않고, 그것을 묻는 조건은
    ``INFORMATION_UNAVAILABLE`` 이다.
    """
    from engine.game_state_view import GameStateView

    state = new_state()
    view = GameStateView.from_state(state, viewer=MINE)
    opponent_hand = state.player(1 - MINE).hand
    assert opponent_hand, "상대 패가 비어 있으면 이 시험이 아무것도 보이지 않는다."
    hidden = view.find(opponent_hand[0].instance_id)
    assert hidden is None or hidden.card_id is None

    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert info.code is not ValidationCode.EXECUTION_FORBIDDEN
    assert info.code is not ValidationCode.CANDIDATE_NOT_ELIGIBLE


# ======================================================================
# §16 — negative tests (여섯 가지 잘못된 변환)
# ======================================================================


def test_20_the_six_forbidden_conversions_are_all_absent():
    """
    **§16: 여섯 가지 잘못된 변환이 다시 생기지 않는다.**

    1. ``UNKNOWN`` → ``CANDIDATE_NOT_ELIGIBLE``
    2. ``TEXT_DERIVED`` → ``RULE_NOT_IMPLEMENTED``
    3. hidden information → ``EXECUTION_FORBIDDEN``
    4. 진짜 미구현 → ``CANDIDATE_NOT_ELIGIBLE``
    5. 조건 ``FALSE`` → ``RULE_NOT_IMPLEMENTED``
    6. 출처 금지 → ``RULE_NOT_IMPLEMENTED``
    """
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))
    forbidden = activate(new_state(), forbidden_definition())

    #: 1 · 4
    assert rule.code is not ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert info.code is not ValidationCode.CANDIDATE_NOT_ELIGIBLE
    #: 2 · 6
    assert forbidden.code is not ValidationCode.RULE_NOT_IMPLEMENTED
    #: 3
    assert info.code is not ValidationCode.EXECUTION_FORBIDDEN
    #: 5
    assert false.code is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: 네 사실이 **서로 다른 코드**를 받는다.
    assert len({rule.code, info.code, false.code, forbidden.code}) == 4


def test_21_unknown_is_still_neither_false_nor_a_permission():
    """
    **§17-5 · §17-6: ``UNKNOWN`` 이 ``FALSE`` 도 허가도 되지 않는다.**
    """
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))

    assert rule.status is ActivationStatus.CONDITION_UNKNOWN
    assert rule.status is not ActivationStatus.CONDITION_FALSE
    assert false.status is ActivationStatus.CONDITION_FALSE
    for result in (rule, false):
        assert result.status is not ActivationStatus.ACTIVATED

    assert ValidationResult.unknown(
        ValidationCode.RULE_NOT_IMPLEMENTED, ""
    ).permits_execution is False


def test_22_unknown_is_not_a_loss_and_not_a_zero_score():
    """**§17-7 · §17-8 · §17-10: 모름이 패배도 0점도 아니다.**"""
    action = PlayerAction.passing(actor=MINE)
    unknown = SearchCandidate(action=action, status=SimulationStatus.UNKNOWN)
    refused = SearchCandidate(action=action, status=SimulationStatus.REFUSED)
    assert unknown.value is refused.value is None
    assert unknown.comparable is refused.comparable is False
    #: 분류가 달라져도 **순위는 같다** — 그래서 선택이 바뀌지 않는다.
    assert unknown.ordering_key() == refused.ordering_key()
    assert unknown.ordering_key()[0] == 1


# ======================================================================
# S — regression
# ======================================================================


def test_23_the_distinctions_from_phase_3e24_to_3e37_still_hold():
    """**S (§15): 열네 Phase 가 세운 구분이 그대로인지.**"""
    assert ConditionResult.UNKNOWN is not ConditionResult.FALSE
    assert ActionValidity.UNKNOWN is not ActionValidity.INVALID
    assert ActivationStatus.CONDITION_UNKNOWN is not ActivationStatus.CONDITION_FALSE
    assert ResolutionStatus.CONDITION_UNKNOWN is not ResolutionStatus.CONDITION_FALSE
    for name in (
        "INFORMATION_UNAVAILABLE",
        "EXECUTION_FORBIDDEN",
        "CANDIDATE_NOT_ELIGIBLE",
        "COST_NOT_IMPLEMENTED",
    ):
        assert getattr(ValidationCode, name) is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: enum 크기가 하나도 늘지 않았다.
    assert len(ValidationCode) == 48
    assert len(ConditionResult) == 3
    assert len(ActionValidity) == 3
    assert len(SimulationStatus) == 5


def test_24_only_four_production_lines_changed_their_code():
    """
    **§18: production diff 가 네 자리에만 있다.**

    ``git`` 을 부르지 않고 **현재 소스가 기대하는 모양**인지로 확인한다 —
    고친 네 자리와, 고치지 않기로 한 자리들이다.
    """
    activation = source_of("engine/activation.py")
    executor = source_of("engine/effect/executor.py")

    #: 고친 것 — 네 자리. **메서드 단위로 집는다.**
    #: ``executor.py`` 는 ``CANDIDATE_NOT_ELIGIBLE`` 을 이번 수정 말고도
    #: **세 자리**에서 이미 쓰고 있었다 (고른 카드를 규칙이 전부 막음 ·
    #: 특수 소환 실패 · 대상 조건 거짓). 파일 전체를 세면 그것까지 걸린다 —
    #: 이 파일을 처음 쓸 때 1 로 적어 틀렸다. 그리고 그 세 자리는 이번
    #: 수정이 **옳다는 근거**다: 같은 파일이 "확실한 거부" 에 이미 이 코드를
    #: 쓰고 있었다 (3-E-37 §가 지목한 바로 그 사실).
    assert executor.count("ValidationCode.CANDIDATE_NOT_ELIGIBLE") == 4
    for path, cls in (
        ("engine/activation.py", "EffectActivator"),
        ("engine/effect/executor.py", "EffectExecutor"),
    ):
        condition = method_source(path, cls, "_check_condition")
        authority = method_source(path, cls, "_check_authority")
        assert condition.count("ValidationCode.CANDIDATE_NOT_ELIGIBLE") == 1, path
        assert condition.count("ValidationCode.EXECUTION_FORBIDDEN") == 0, path
        #: 발동 계층은 표(``_AVAILABILITY_REFUSAL``)에서 코드를 읽으므로
        #: 메서드 본문에는 코드가 없다 — 그래서 **한 자리 이하**로 센다.
        assert authority.count("ValidationCode.EXECUTION_FORBIDDEN") <= 1, path

    #: 발동 계층의 금지 코드는 표에 **한 번** 적힌다.
    assert activation.count("ValidationCode.EXECUTION_FORBIDDEN") == 1
    assert executor.count("ValidationCode.EXECUTION_FORBIDDEN") == 1
    assert activation.count("ValidationCode.CANDIDATE_NOT_ELIGIBLE") == 1

    #: 고치지 않은 것 — enum 과 분류 집합.
    validation = source_of("engine/validation.py")
    assert validation.count('RULE_NOT_IMPLEMENTED = "rule_not_implemented"') == 1
    assert validation.count('CANDIDATE_NOT_ELIGIBLE = "candidate_not_eligible"') == 1
    assert validation.count('EXECUTION_FORBIDDEN = "execution_forbidden"') == 1
