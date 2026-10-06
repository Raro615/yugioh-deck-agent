r"""
Phase 3-E-44 — Dormant 판정기와 Live Gate 의 **판정 일치성** 측정.

**AUDIT-ONLY.** production 을 한 줄도 고치지 않는다. 이 파일은 "같은 질문을
하는 것처럼 보이는 두 판정 계층이 **실제로 같은 답을 내는가**" 를 동일 입력으로
재어, 그 결과를 재현 가능한 형태로 고정한다.

Base: Phase 3-E-43 (결과 ``35e156e`` · 보고서 ``40a7766`` · STRUCTURAL_RISK_IDENTIFIED).
3-E-43 이 기록한 **R-2** — dormant ``TriggerEligibilityJudge`` 의 다섯 관문 중
넷이 live 세 관문과 같은 질문을 묻는다 — 를 **이름 비교가 아니라 실측**으로
확정한다.

측정 결과 (요지)
---------------
=====================  ==================================================
``EVENT_RELATION``     **E. NO_LIVE_COUNTERPART** — ``spec.matches`` 를
                       부르는 자리가 ``engine/trigger.py`` 둘뿐이다
``ACTIVATION_ZONE``    **D. DIFFERENT_RESULT** — 같은 판에서 답이 갈린다
                       (Z2 · Z4 · Z6). live 는 발동에 ``SOURCE_WRONG_ZONE``
                       을 **아예 쓰지 않는다**
``TRIGGER_CONDITION``  **B. 표현만 다르다** — 공유 입력 5건 전부
                       ``(validity, code)`` 가 같다. 입력 **영역**만 다르다
                       (``TriggerSpec.condition`` 에 live 대응이 없다)
``EXECUTION_AUTHORITY``**A. EQUIVALENT** — 판단 자체가 한 벌이다
                       (``execution_availability``). 5개 availability 전부 같다
``COST_FEASIBILITY``   **D. DIFFERENT_RESULT** — dormant 는 판정하고 live 는
                       **묻지 않는다** (열거에서 통째로 뺀다)
=====================  ==================================================

새로 찾은 위험 **R-3**
---------------------
``_event_relation`` 의 불일치 분기가 ``ActionValidity.INVALID`` 와
``ValidationCode.RULE_NOT_IMPLEMENTED`` 를 **짝지어** 낸다. Phase 3-E-40 의
``CODE_VALIDITY`` 는 그 코드를 ``UNKNOWN`` 으로 분류한다. ``engine/trigger.py``
의 ``_gate(...)`` 생산 17자리 중 **이 한 자리만** policy 와 어긋나고, 그 자리가
**live 대응이 없는 유일한 관문**이다 (``test_28`` · ``test_29``).

고치지 않는다 — 이번 Phase 는 측정이다.
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction
from engine.action_validation import ActionValidator, _activation_out_of_scope
from engine.activation import EffectActivator
from engine.chain import Chain
from engine.condition import Always, IsMonster, PlayerRef, UnimplementedRule
from engine.cost import CostGroup, LifeCost
from engine.effect import (
    CardDrawn,
    DrawOperation,
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectImplementationRegistry,
    EffectProvenance,
    LifeChanged,
    OperationKind,
    ZoneMoved,
)
from engine.effect.definition import ExecutionAvailability, execution_availability
from engine.effect.library import EFFECT_LIBRARY
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.trigger import (
    EligibilityGate,
    TimingEvent,
    TimingPoint,
    TriggerCandidate,
    TriggerEligibilityJudge,
    TriggerSpec,
)
from engine.validation import (
    CODE_VALIDITY,
    ActionValidity,
    ValidationCode,
    ValidationResult,
)
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

MINE, THEIRS = 0, 1

#: 범주마다 한 장. **규칙을 추측하지 않는다** — 종류는 공식 DB 가 말하고,
#: 여기서는 "통상 마법 · 속공 마법 · 함정" 이라는 사실만 쓴다.
POT_OF_GREED = 55144522
MYSTICAL_SPACE_TYPHOON = 5318639
FINE = 92595643

#: 테스트가 명시적으로 건네는 허가. **발동 타이밍 계층을 대신하지 않는다** —
#: 관문 1·2 를 건너뛰고 관문 3(``can_activate``) 만 재기 위한 것이다.
GRANTED = ValidationResult.valid("테스트가 발동 타이밍을 허가했다")

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


def function_of(path: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(source_of(path))):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path} 에 {name} 이 없습니다")


def codes_in(node) -> set[str]:
    """``ValidationCode.X`` 를 **AST 로** 센다. 문자열 포함 검사가 아니다."""
    return {
        n.attr
        for n in ast.walk(node)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "ValidationCode"
    }


# ======================================================================
# 동일 입력 — 두 계층에 **같은 판 · 같은 정의 · 같은 인스턴스**를 건넨다
# ======================================================================


def board(repository, card_id=POT_OF_GREED, zone=Zone.HAND):
    """그 카드 한 장을 ``zone`` 에 둔 판. 셔플 결과에 의존하지 않도록 seed 고정."""
    state = GameState.create(
        repository, decks=([card_id] * 6, [POT_OF_GREED] * 6), seed=1
    )
    state.draw(MINE, 2)
    state.draw(THEIRS, 2)
    instance = state.create_instance(card_id, owner=MINE, zone=Zone.HAND)
    if zone is not Zone.HAND:
        instance = state.move(
            instance, zone, to_player=MINE, position=Position.FACEDOWN
        )
    state.turn.turn_number = 2
    state.turn.turn_player = MINE
    state.turn.set_phase(Phase.MAIN1)
    return state, instance.instance_id


def definition_of(card_id=POT_OF_GREED, *, activation=None, provenance=None, cost=None):
    """패를 1장 뽑는 **모양만** 가진 정의. 대상이 없어서 흔들릴 것이 없다."""
    kwargs = {
        "effect_ref": EffectRef(card_id, 0),
        "source_card_id": card_id,
        "operations": (DrawOperation(1),),
        "activation": activation,
        "provenance": provenance or EffectProvenance.official_lua(),
    }
    if cost is not None:
        kwargs["cost"] = cost
    return EffectDefinition(**kwargs)


def hand_spec(ref, **kwargs):
    kwargs.setdefault("activates_from", frozenset({Zone.HAND}))
    return TriggerSpec(ref, TimingPoint.CARD_DRAWN, **kwargs)


def drawn_event() -> TimingEvent:
    return TimingEvent.from_delta(CardDrawn(MINE, InstanceId(1)))


def dormant_gates(
    state, definition, instance, spec, event, *, viewer=MINE, defs=True, imps=True
):
    """dormant 다섯 관문의 ``(validity, code)``. **판을 바꾸지 않는다.**"""
    view = GameStateView.from_state(state, viewer=viewer)
    judge = TriggerEligibilityJudge(
        view,
        EffectDefinitionRegistry((definition,) if defs else ()),
        EffectImplementationRegistry((definition.effect_ref,) if imps else ()),
    )
    candidate = TriggerCandidate(
        point=spec.point,
        effect_ref=spec.effect_ref,
        source=instance,
        controller=MINE,
    )
    eligibility = judge.judge(candidate, spec, event)
    gates = {
        verdict.gate: (verdict.validity, verdict.code) for verdict in eligibility.gates
    }
    return gates, eligibility


def live_verdicts(state, definition, instance, *, viewer=MINE, defs=True, imps=True):
    """live 관문 1(``ActionValidator``) 과 3(``can_activate``). 관문 2 는 체인 쪽이다."""
    view = GameStateView.from_state(state, viewer=viewer)
    action = PlayerAction.activate_effect(
        actor=MINE, source=instance, effect_ref=definition.effect_ref
    )
    validator = ActionValidator(view)
    verdict = validator.validate(action)
    activator = EffectActivator(
        EffectDefinitionRegistry((definition,) if defs else ()),
        EffectImplementationRegistry((definition.effect_ref,) if imps else ()),
    )
    can = activator.can_activate(state, Chain(), action, authorization=GRANTED)
    return {
        "validator": (verdict.validity, verdict.code),
        "can_activate": (can.validity, can.code),
        "out_of_scope": tuple(
            why
            for why, _ in _activation_out_of_scope(
                view, validator.context_for(action), instance
            )
        ),
    }


# ======================================================================
# A. ACTIVATION_ZONE — 같은 판에서 답이 갈린다 (D. DIFFERENT_RESULT)
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_01_zone_agrees_for_a_normal_spell_in_hand(repository):
    """
    **Z1** 패의 통상 마법 · 선언 ``{HAND}``. 범위 안의 유일한 모양이고,
    두 계층이 **같은 답**을 낸다.
    """
    state, instance = board(repository)
    definition = definition_of()
    gates, _ = dormant_gates(
        state, definition, instance, hand_spec(definition.effect_ref), drawn_event()
    )
    live = live_verdicts(state, definition, instance)

    assert gates[EligibilityGate.ACTIVATION_ZONE] == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )
    assert live["validator"] == (ActionValidity.VALID, ValidationCode.OK)
    assert live["out_of_scope"] == ()


@pytest.mark.real_card
@requires_official_db
def test_02_zone_diverges_for_a_set_spell_declared_as_hand_only(repository):
    """
    **Z2 — 결과가 실제로 갈리는 자리.**

    세트해 둔 통상 마법 하나, 선언은 ``activates_from={HAND}``.

    * dormant → ``INVALID`` / ``SOURCE_WRONG_ZONE`` ("규칙이 금지한다")
    * live    → ``VALID`` / ``OK`` (세트한 통상 마법은 **범위 안**이다 —
      RULE-SPELLTRAP-012)

    같은 판 · 같은 카드 · 같은 정의인데 한쪽은 금지라고 하고 한쪽은 허가한다.
    """
    state, instance = board(repository, zone=Zone.SZONE)
    definition = definition_of()
    gates, _ = dormant_gates(
        state, definition, instance, hand_spec(definition.effect_ref), drawn_event()
    )
    live = live_verdicts(state, definition, instance)

    assert gates[EligibilityGate.ACTIVATION_ZONE] == (
        ActionValidity.INVALID,
        ValidationCode.SOURCE_WRONG_ZONE,
    )
    assert live["validator"] == (ActionValidity.VALID, ValidationCode.OK)
    assert live["out_of_scope"] == ()


@pytest.mark.real_card
@requires_official_db
def test_03_zone_agrees_when_the_declaration_matches_the_set_zone(repository):
    """**Z3** 같은 세트 카드인데 선언이 ``{SZONE}`` 이면 dormant 도 ``VALID`` 다."""
    state, instance = board(repository, zone=Zone.SZONE)
    definition = definition_of()
    spec = hand_spec(definition.effect_ref, activates_from=frozenset({Zone.SZONE}))
    gates, _ = dormant_gates(state, definition, instance, spec, drawn_event())

    assert gates[EligibilityGate.ACTIVATION_ZONE] == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )
    assert live_verdicts(state, definition, instance)["validator"] == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )


@pytest.mark.real_card
@requires_official_db
def test_04_zone_diverges_when_the_spec_declares_nothing(repository):
    """
    **Z4** ``activates_from=None``.

    dormant 는 **적지 않은 것을 "어디서든" 으로 읽지 않으므로** ``UNKNOWN`` 이고,
    live 는 그런 선언 자체가 없으므로 판정이 통과한다. 이것은 입력 영역의
    차이이면서 **같은 판에서 답이 다르다**.
    """
    state, instance = board(repository)
    definition = definition_of()
    spec = hand_spec(definition.effect_ref, activates_from=None)
    gates, _ = dormant_gates(state, definition, instance, spec, drawn_event())

    assert gates[EligibilityGate.ACTIVATION_ZONE] == (
        ActionValidity.UNKNOWN,
        ValidationCode.RULE_NOT_IMPLEMENTED,
    )
    assert live_verdicts(state, definition, instance)["validator"] == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )


@pytest.mark.real_card
@requires_official_db
def test_05_zone_agrees_exactly_on_hidden_cards(repository):
    """
    **Z5 — 두 계층이 가장 정확하게 일치하는 자리.**

    관측에 보이지 않는 카드를 출처로 주면 **둘 다** ``UNKNOWN`` /
    ``HIDDEN_CARD`` 다. 모름을 거부로 접지 않는 태도가 양쪽에 있다.
    """
    state, instance = board(repository)
    hidden = state.create_instance(POT_OF_GREED, owner=THEIRS, zone=Zone.HAND)
    definition = definition_of()
    gates, _ = dormant_gates(
        state,
        definition,
        hidden.instance_id,
        hand_spec(definition.effect_ref),
        drawn_event(),
    )
    live = live_verdicts(state, definition, hidden.instance_id)

    assert gates[EligibilityGate.ACTIVATION_ZONE] == (
        ActionValidity.UNKNOWN,
        ValidationCode.HIDDEN_CARD,
    )
    assert live["validator"] == (ActionValidity.UNKNOWN, ValidationCode.HIDDEN_CARD)


@pytest.mark.real_card
@requires_official_db
def test_06_zone_diverges_in_the_dangerous_direction_for_a_trap(repository):
    """
    **Z6 — 위험한 방향으로 갈린다.**

    패의 함정, 선언은 ``{HAND}``.

    * dormant → ``VALID`` / ``OK`` ("이 자리에서 발동할 수 있다")
    * live    → ``UNKNOWN`` / ``RULE_NOT_IMPLEMENTED``
      (``_activation_out_of_scope`` 가 "함정이다" 를 든다)

    dormant 가 **더 많이 허가한다.** 이 쪽 답을 믿으면 유발 조건을 구분할 수
    없는 함정이 조용히 발동 가능해진다.
    """
    state, instance = board(repository, FINE)
    definition = definition_of(FINE)
    gates, _ = dormant_gates(
        state, definition, instance, hand_spec(definition.effect_ref), drawn_event()
    )
    live = live_verdicts(state, definition, instance)

    assert gates[EligibilityGate.ACTIVATION_ZONE] == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )
    assert live["validator"] == (
        ActionValidity.UNKNOWN,
        ValidationCode.RULE_NOT_IMPLEMENTED,
    )
    assert "함정이다" in live["out_of_scope"]


@pytest.mark.real_card
@requires_official_db
def test_07_zone_agrees_for_a_quick_play_spell_in_hand(repository):
    """**Z7** 패의 속공 마법은 범위 안이고, 두 계층이 같은 답을 낸다."""
    state, instance = board(repository, MYSTICAL_SPACE_TYPHOON)
    definition = definition_of(MYSTICAL_SPACE_TYPHOON)
    gates, _ = dormant_gates(
        state, definition, instance, hand_spec(definition.effect_ref), drawn_event()
    )

    assert gates[EligibilityGate.ACTIVATION_ZONE] == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )
    assert live_verdicts(state, definition, instance)["validator"] == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )


def test_08_live_never_calls_an_activation_wrong_zone_invalid():
    """
    ``SOURCE_WRONG_ZONE`` 을 내는 live 생산자는 **발동이 아니다.**

    소환 · 세트 · 표시형식 변경 · 공격 넷뿐이고, ``_activate_effect`` 의 코드
    집합에는 그 코드가 **없다**. 그래서 ACTIVATION_ZONE 의 의미 차이는
    우연이 아니라 **구조**다 — live 는 발동의 자리를 ``INVALID`` 로 적지
    않기로 했고, 그 까닭이 ``_activation_out_of_scope`` 의 docstring 에 있다.
    """
    path = "engine/action_validation.py"
    producers = {
        node.name
        for node in ast.walk(ast.parse(source_of(path)))
        if isinstance(node, ast.FunctionDef) and "SOURCE_WRONG_ZONE" in codes_in(node)
    }
    assert producers == {
        "_summon_like",
        "_set_spell_trap",
        "_change_position",
        "_attack",
    }

    activate_codes = codes_in(function_of(path, "_activate_effect"))
    assert "SOURCE_WRONG_ZONE" not in activate_codes
    assert activate_codes == {
        "NOT_TURN_PLAYER",
        "RULE_NOT_IMPLEMENTED",
        "SOURCE_NOT_CONTROLLED",
        "WRONG_PHASE",
        "ZONE_FULL",
    }
    assert "SOURCE_WRONG_ZONE 같은 ``INVALID`` 로 적으면" in source_of(path).replace(
        "\n    ", " "
    ).replace("``SOURCE_WRONG_ZONE``", "SOURCE_WRONG_ZONE")


# ======================================================================
# B. TRIGGER_CONDITION — 공유 입력에서는 한 칸도 다르지 않다
# ======================================================================


@pytest.mark.real_card
@requires_official_db
@pytest.mark.parametrize(
    "label, activation, expected",
    [
        ("C1 조건 없음", None, (ActionValidity.VALID, ValidationCode.OK)),
        ("C2 조건 참", Always(), (ActionValidity.VALID, ValidationCode.OK)),
        (
            "C3 조건 거짓",
            IsMonster(),
            (ActionValidity.INVALID, ValidationCode.CANDIDATE_NOT_ELIGIBLE),
        ),
        (
            "C4 조건 UNKNOWN · 없는 규칙",
            UnimplementedRule("테스트용 없는 규칙"),
            (ActionValidity.UNKNOWN, ValidationCode.RULE_NOT_IMPLEMENTED),
        ),
    ],
)
def test_09_condition_gives_the_same_answer_in_both_layers(
    repository, label, activation, expected
):
    """
    **C1–C4 — 네 입력 전부 ``(validity, code)`` 가 같다.**

    두 계층이 같은 ``ConditionEvaluator`` 를 쓰고, 삼치 논리를 같은 코드로
    적는다 (Phase 3-E-26 · 3-E-38 이 그렇게 맞춰 두었다). ``C3`` 의
    ``IsMonster()`` 는 출처(통상 마법)를 보므로 확실한 **거짓**이다.
    """
    state, instance = board(repository)
    definition = definition_of(activation=activation)
    gates, _ = dormant_gates(
        state, definition, instance, hand_spec(definition.effect_ref), drawn_event()
    )
    live = live_verdicts(state, definition, instance)

    assert gates[EligibilityGate.TRIGGER_CONDITION] == expected, label
    assert live["can_activate"] == expected, label


@pytest.mark.real_card
@requires_official_db
def test_10_condition_agrees_when_the_definition_is_missing(repository):
    """
    **C5** 정의를 못 찾았을 때. 두 계층 모두 ``UNKNOWN`` /
    ``RULE_NOT_IMPLEMENTED`` 다 — dormant 는 조건 관문에서, live 는 그보다
    앞선 자리(``_check`` 의 정의 조회)에서 멈춘다. **관문은 다르고 답은 같다.**
    """
    state, instance = board(repository)
    definition = definition_of()
    gates, _ = dormant_gates(
        state,
        definition,
        instance,
        hand_spec(definition.effect_ref),
        drawn_event(),
        defs=False,
    )
    live = live_verdicts(state, definition, instance, defs=False)

    expected = (ActionValidity.UNKNOWN, ValidationCode.RULE_NOT_IMPLEMENTED)
    assert gates[EligibilityGate.TRIGGER_CONDITION] == expected
    assert live["can_activate"] == expected


@pytest.mark.real_card
@requires_official_db
def test_11_condition_input_domain_is_wider_in_the_dormant_layer(repository):
    """
    **C6 — 입력 영역의 차이.** ``TriggerSpec.condition`` 에는 live 대응이 없다.

    같은 정의(``activation=None``)에 **spec 쪽 조건만** 걸면 dormant 는 그것을
    읽어 ``UNKNOWN`` 을 내고 live 는 그 조건을 **받을 통로 자체가 없다.**

    이것을 ``DIFFERENT_RESULT`` 로 적지 않는다 — **같은 입력이 아니다.**
    """
    state, instance = board(repository)
    definition = definition_of(activation=None)
    spec = hand_spec(
        definition.effect_ref, condition=UnimplementedRule("spec 쪽 없는 규칙")
    )
    gates, _ = dormant_gates(state, definition, instance, spec, drawn_event())
    live = live_verdicts(state, definition, instance)

    assert gates[EligibilityGate.TRIGGER_CONDITION] == (
        ActionValidity.UNKNOWN,
        ValidationCode.RULE_NOT_IMPLEMENTED,
    )
    assert live["can_activate"] == (ActionValidity.VALID, ValidationCode.OK)

    # live 가 읽는 조건은 정의의 ``activation`` 하나다 — spec 을 모른다.
    live_condition = function_of("engine/activation.py", "_check_condition")
    attributes = {
        node.attr for node in ast.walk(live_condition) if isinstance(node, ast.Attribute)
    }
    assert "activation" in attributes
    assert "condition" not in attributes


def test_12_both_condition_layers_split_unknown_the_same_way():
    """
    ``UNKNOWN`` 안에서 **까닭을 가르는 방법**이 두 계층에서 같다 —
    ``missing_rules`` 가 비면 ``INFORMATION_UNAVAILABLE``, 있으면
    ``RULE_NOT_IMPLEMENTED``.
    """
    dormant = function_of("engine/trigger.py", "_trigger_condition")
    live = function_of("engine/activation.py", "_check_condition")

    for node, name in ((dormant, "_trigger_condition"), (live, "_check_condition")):
        codes = codes_in(node)
        assert "RULE_NOT_IMPLEMENTED" in codes, name
        assert "INFORMATION_UNAVAILABLE" in codes, name
        assert "CANDIDATE_NOT_ELIGIBLE" in codes, name
        calls = {
            n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "missing_rules" in calls, name


# ======================================================================
# C. EXECUTION_AUTHORITY — 판단이 한 벌이다 (A. EQUIVALENT)
# ======================================================================


@pytest.mark.real_card
@requires_official_db
@pytest.mark.parametrize(
    "label, provenance, imps, defs, availability, expected",
    [
        (
            "A1 official_lua + 구현 등록",
            None,
            True,
            True,
            ExecutionAvailability.EXECUTABLE,
            (ActionValidity.VALID, ValidationCode.OK),
        ),
        (
            "A2 구현 없음",
            None,
            False,
            True,
            ExecutionAvailability.NO_IMPLEMENTATION,
            (ActionValidity.UNKNOWN, ValidationCode.RULE_NOT_IMPLEMENTED),
        ),
        (
            "A3 정의 미등록",
            None,
            True,
            False,
            ExecutionAvailability.EXECUTABLE,
            (ActionValidity.UNKNOWN, ValidationCode.RULE_NOT_IMPLEMENTED),
        ),
    ],
)
def test_13_authority_agrees_on_registration(
    repository, label, provenance, imps, defs, availability, expected
):
    """**A1–A3** 등록 상태가 어떻든 두 계층의 ``(validity, code)`` 가 같다."""
    state, instance = board(repository)
    definition = definition_of(provenance=provenance)
    gates, _ = dormant_gates(
        state,
        definition,
        instance,
        hand_spec(definition.effect_ref),
        drawn_event(),
        defs=defs,
        imps=imps,
    )
    live = live_verdicts(state, definition, instance, defs=defs, imps=imps)
    lookup = EffectImplementationRegistry((definition.effect_ref,) if imps else ())

    assert execution_availability(definition, lookup) is availability, label
    assert gates[EligibilityGate.EXECUTION_AUTHORITY] == expected, label
    assert live["can_activate"] == expected, label


@pytest.mark.real_card
@requires_official_db
def test_14_authority_agrees_that_a_text_derived_effect_is_forbidden(repository):
    """
    **A4 — ADR-004.** 공식 텍스트에서 유추한 효과는 **실행하지 않는다.**
    두 계층 모두 ``INVALID`` / ``EXECUTION_FORBIDDEN`` 이다 (Phase 3-E-38 의
    M2 가 live 쪽을 이 코드로 맞춰 두었다).
    """
    state, instance = board(repository)
    definition = definition_of(provenance=EffectProvenance.text_derived())
    gates, _ = dormant_gates(
        state, definition, instance, hand_spec(definition.effect_ref), drawn_event()
    )
    live = live_verdicts(state, definition, instance)

    lookup = EffectImplementationRegistry((definition.effect_ref,))
    assert (
        execution_availability(definition, lookup)
        is ExecutionAvailability.FORBIDDEN_SOURCE
    )
    expected = (ActionValidity.INVALID, ValidationCode.EXECUTION_FORBIDDEN)
    assert gates[EligibilityGate.EXECUTION_AUTHORITY] == expected
    assert live["can_activate"] == expected


@pytest.mark.real_card
@requires_official_db
def test_15_authority_agrees_that_an_unverified_effect_is_unknown(repository):
    """
    **A5** 미검증은 금지가 아니라 **모름**이다. 두 계층 모두
    ``UNKNOWN`` / ``RULE_NOT_IMPLEMENTED`` 다.
    """
    state, instance = board(repository)
    definition = definition_of(provenance=EffectProvenance.hand_written(verified=False))
    gates, _ = dormant_gates(
        state, definition, instance, hand_spec(definition.effect_ref), drawn_event()
    )
    live = live_verdicts(state, definition, instance)

    lookup = EffectImplementationRegistry((definition.effect_ref,))
    assert execution_availability(definition, lookup) is ExecutionAvailability.UNVERIFIED
    expected = (ActionValidity.UNKNOWN, ValidationCode.RULE_NOT_IMPLEMENTED)
    assert gates[EligibilityGate.EXECUTION_AUTHORITY] == expected
    assert live["can_activate"] == expected


def test_16_both_authority_layers_call_the_same_function():
    """
    **왜 EXECUTION_AUTHORITY 만 A(EQUIVALENT) 인가** — 판단이 **한 벌**이다.

    dormant 와 live 가 모두 ``execution_availability`` 를 부른다. 두 구현을
    맞춰 둔 것이 아니라 하나를 공유한다. 그래서 availability 다섯 값 전부에서
    같은 답이 나오는 것이 우연이 아니다.
    """
    for path, name in (
        ("engine/trigger.py", "_execution_authority"),
        ("engine/activation.py", "_check_authority"),
    ):
        calls = {
            node.func.id
            for node in ast.walk(function_of(path, name))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "execution_availability" in calls, f"{path}:{name}"

    assert len(ExecutionAvailability) == 5


# ======================================================================
# D. COST_FEASIBILITY — dormant 는 판정하고 live 는 묻지 않는다
# ======================================================================


def costed(amount):
    return definition_of(
        cost=CostGroup((LifeCost(amount=amount, who=PlayerRef.CONTROLLER),))
    )


@pytest.mark.real_card
@requires_official_db
def test_17_cost_agrees_only_when_there_is_no_cost(repository):
    """**K1** 비용이 없으면 dormant 는 ``VALID`` 고 live 는 열거에서 빼지 않는다."""
    state, instance = board(repository)
    definition = definition_of()
    gates, _ = dormant_gates(
        state, definition, instance, hand_spec(definition.effect_ref), drawn_event()
    )

    assert definition.cost.is_free
    assert gates[EligibilityGate.COST_FEASIBILITY] == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )
    assert not definition.cost.costs  # live 열거의 실제 술어


@pytest.mark.real_card
@requires_official_db
def test_18_cost_diverges_when_the_cost_is_payable(repository):
    """
    **K2 — 치를 수 있는 비용.** 라이프 8000 에 비용 1000.

    * dormant → ``VALID`` / ``OK`` ("치를 수 있다")
    * live    → 그 행동을 **열거에서 통째로 뺀다** (``cost.costs`` 가 비지
      않으면 ``continue``). 그러면서 관문 3(``can_activate``) 은 ``VALID`` 다 —
      비용을 **보지 않기 때문**이다.

    즉 live 의 "안 된다" 는 비용 판정이 아니라 **범위 제한**이고, 그래서 두
    계층의 답이 같은 뜻을 갖지 않는다.
    """
    state, instance = board(repository)
    definition = costed(1000)
    assert state.player(MINE).life_points == 8000

    gates, _ = dormant_gates(
        state, definition, instance, hand_spec(definition.effect_ref), drawn_event()
    )
    live = live_verdicts(state, definition, instance)

    assert gates[EligibilityGate.COST_FEASIBILITY] == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )
    assert bool(definition.cost.costs) is True  # live 열거가 빼는 조건
    assert live["can_activate"] == (ActionValidity.VALID, ValidationCode.OK)


@pytest.mark.real_card
@requires_official_db
def test_19_cost_diverges_hardest_when_the_cost_is_unpayable(repository):
    """
    **K3 — 치를 수 없는 비용.** 라이프 8000 에 비용 9000.

    * dormant → ``INVALID`` / ``INSUFFICIENT_LIFE`` — **확실한 거부**
    * live    → ``VALID`` / ``OK`` (``can_activate`` 는 비용을 판정하지 않는다
      고 docstring 이 직접 적는다)

    같은 판에서 한쪽은 불가능이라 하고 한쪽은 가능이라 한다. 이것이 이 관문의
    ``DIFFERENT_RESULT`` 근거다.
    """
    state, instance = board(repository)
    definition = costed(9000)
    gates, _ = dormant_gates(
        state, definition, instance, hand_spec(definition.effect_ref), drawn_event()
    )
    live = live_verdicts(state, definition, instance)

    assert gates[EligibilityGate.COST_FEASIBILITY] == (
        ActionValidity.INVALID,
        ValidationCode.INSUFFICIENT_LIFE,
    )
    assert live["can_activate"] == (ActionValidity.VALID, ValidationCode.OK)
    assert "비용은 **치르지 않는다.**" in ast.get_docstring(
        function_of("engine/activation.py", "can_activate")
    )


def test_20_validate_group_has_exactly_one_caller_and_it_is_dormant():
    """
    비용 **가능성**을 묻는 함수(``CostValidator.validate_group``) 를 부르는
    자리는 repo 전체에서 **하나**이고, 그것이 dormant 관문이다.

    live 지불 경로(``CostPayer._preflight``) 는 ``validate`` 를 비용마다 부른다 —
    다른 단계의 다른 질문이다.
    """
    callers = []
    for path in sorted(PROJECT_ROOT.glob("engine/**/*.py")) + sorted(
        PROJECT_ROOT.glob("agent/**/*.py")
    ):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "validate_group"
            ):
                callers.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert callers == ["engine/trigger.py"]


def test_21_no_registered_effect_has_a_cost_so_the_live_filter_removes_nothing():
    """
    등재 효과 **16개 전부 비용이 없다.** 그래서 live 의 ``cost.costs`` 거름은
    지금 아무것도 빼지 않고, 두 계층의 차이도 **현재 production 결과를 바꾸지
    않는다**. 숫자가 변하면 그것이 신호다.
    """
    costed_entries = [
        entry.definition.effect_ref
        for entry in EFFECT_LIBRARY
        if entry.definition.cost.costs
    ]
    assert len(EFFECT_LIBRARY) == 16
    assert costed_entries == []
    assert "if definition.cost.costs:" in source_of("engine/duel.py")


# ======================================================================
# E. EVENT_RELATION — live 대응이 없다 (E. NO_LIVE_COUNTERPART)
# ======================================================================


@pytest.mark.real_card
@requires_official_db
@pytest.mark.parametrize(
    "label, expected",
    [
        ("E1 같은 시점", (ActionValidity.VALID, ValidationCode.OK)),
        ("E2 다른 시점", (ActionValidity.INVALID, ValidationCode.RULE_NOT_IMPLEMENTED)),
    ],
)
def test_22_event_relation_is_a_data_comparison(repository, label, expected):
    """**E1 · E2** 선언이 적어 둔 것과 사건을 **데이터로** 비교한다."""
    state, instance = board(repository)
    definition = definition_of()
    event = (
        drawn_event()
        if label.startswith("E1")
        else TimingEvent.from_delta(LifeChanged(MINE, 8000, 7000))
    )
    gates, _ = dormant_gates(
        state, definition, instance, hand_spec(definition.effect_ref), event
    )
    assert gates[EligibilityGate.EVENT_RELATION] == expected, label


@pytest.mark.real_card
@requires_official_db
@pytest.mark.parametrize(
    "label, to_zone, operations, expected",
    [
        (
            "E3 존 필터 불일치",
            Zone.MZONE,
            None,
            (ActionValidity.INVALID, ValidationCode.RULE_NOT_IMPLEMENTED),
        ),
        ("E4 존 필터 일치", Zone.GRAVE, None, (ActionValidity.VALID, ValidationCode.OK)),
        (
            "E5 의미 필터 불일치",
            Zone.GRAVE,
            frozenset({OperationKind.DESTROY}),
            (ActionValidity.INVALID, ValidationCode.RULE_NOT_IMPLEMENTED),
        ),
    ],
)
def test_23_event_relation_reads_zone_and_operation_filters(
    repository, label, to_zone, operations, expected
):
    """**E3–E5** 존 · 의미 필터까지 본다. 셋 다 live 에는 묻는 자리가 없다."""
    state, instance = board(repository)
    definition = definition_of()
    spec = TriggerSpec(
        definition.effect_ref,
        TimingPoint.CARD_MOVED,
        to_zones=frozenset({Zone.GRAVE}),
        operations=operations,
        activates_from=frozenset({Zone.HAND}),
    )
    event = TimingEvent.from_delta(
        ZoneMoved(
            movement=OperationKind.SEND_TO_GRAVE,
            card=InstanceId(1),
            source_player=MINE,
            source_zone=Zone.MZONE,
            destination_player=MINE,
            destination_zone=to_zone,
        )
    )
    gates, _ = dormant_gates(state, definition, instance, spec, event)
    assert gates[EligibilityGate.EVENT_RELATION] == expected, label


def test_24_spec_matches_is_called_only_inside_the_dormant_module():
    """
    ``TriggerSpec.matches`` 를 부르는 자리는 ``engine/trigger.py`` **두 곳**뿐이다
    (``TriggerRegistry.watching`` · ``_event_relation``). 그래서
    ``EVENT_RELATION`` 은 **live 대응이 없는 유일한 관문**이다.
    """
    callers = []
    for path in sorted(PROJECT_ROOT.glob("engine/**/*.py")) + sorted(
        PROJECT_ROOT.glob("agent/**/*.py")
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "matches"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "spec"
            ):
                callers.append(
                    (path.relative_to(PROJECT_ROOT).as_posix(), node.lineno)
                )
    assert [path for path, _ in callers] == ["engine/trigger.py"] * 2


# ======================================================================
# F. 실행 경로 — production 이 dormant 판정기를 **한 번도** 부르지 않는다
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_25_real_duels_never_reach_any_of_the_five_dormant_gates(repository):
    """
    실제 듀얼 8판을 돌리는 동안 다섯 관문의 호출 횟수가 **전부 0** 이고,
    live 쪽은 수만 번 불린다. **간접 호출조차 없다.**
    """
    import collections
    import types

    import engine.action_validation as live_validation
    import engine.activation as live_activation
    import engine.duel as live_duel
    import engine.trigger as dormant
    from agent.arena import make_first_legal, make_search, run_match

    calls = collections.Counter()
    restore = []

    def probe(owner, name, key):
        original = getattr(owner, name)
        assert isinstance(original, types.FunctionType), f"{key} 를 감쌀 수 없습니다"

        def wrapper(*args, **kwargs):
            calls[key] += 1
            return original(*args, **kwargs)

        setattr(owner, name, wrapper)
        restore.append((owner, name, original))

    try:
        for method in (
            "judge",
            "judge_all",
            "_event_relation",
            "_activation_zone",
            "_trigger_condition",
            "_execution_authority",
            "_cost_feasibility",
        ):
            probe(dormant.TriggerEligibilityJudge, method, f"dormant.{method}")
        probe(live_duel.Duel, "_activation_gate", "live._activation_gate")
        probe(live_validation.ActionValidator, "validate", "live.validate")
        probe(live_activation.EffectActivator, "can_activate", "live.can_activate")
        probe(
            live_activation.EffectActivator, "_check_authority", "live._check_authority"
        )
        probe(
            live_activation.EffectActivator, "_check_condition", "live._check_condition"
        )

        actions = 0
        for seed in range(1, 5):
            for factories in (
                (make_search(), make_search()),
                (make_search(), make_first_legal()),
            ):
                match = run_match(
                    repository,
                    decks=(list(DECK), list(DECK)),
                    seed=seed,
                    factories=factories,
                )
                actions += match.actions
    finally:
        for owner, name, original in restore:
            setattr(owner, name, original)

    assert actions > 0
    dormant_calls = {k: v for k, v in calls.items() if k.startswith("dormant.")}
    assert sum(dormant_calls.values()) == 0, dormant_calls
    assert calls["live._activation_gate"] > 0
    assert calls["live._check_authority"] > 0
    assert calls["live._check_condition"] > 0


@pytest.mark.real_card
@requires_official_db
def test_26_dormant_judging_changes_neither_state_hash_nor_rng(repository):
    """
    dormant 판정을 100번 돌려도 ``state_hash`` 와 RNG 상태가 **한 비트도**
    바뀌지 않는다. 그래서 이 측정 자체가 production 결과를 건드리지 않는다.
    """
    state, instance = board(repository)
    free, paid = definition_of(), costed(1000)
    spec = hand_spec(free.effect_ref)
    event = drawn_event()

    before_hash = state.state_hash()
    before_rng = state.rng.getstate()
    for _ in range(50):
        dormant_gates(state, free, instance, spec, event)
        dormant_gates(state, paid, instance, spec, event)

    assert state.state_hash() == before_hash
    assert state.rng.getstate() == before_rng


@pytest.mark.real_card
@requires_official_db
def test_27_dormant_judging_is_viewer_relative_and_leaks_nothing(repository):
    """
    관측에 따라 답이 **달라진다** — 그리고 그것이 올바른 동작이다. 각 시점은
    자기 카드만 판정할 수 있고, 남의 패는 ``HIDDEN_CARD`` 로 남는다.

    ``GameState`` 를 직접 넘기면 **구조적으로 거부**한다. 그 거부가
    ``TriggerEligibilityJudge.__init__`` **자기 자리**에 있는지까지 본다 —
    런타임 ``TypeError`` 만 보면 아래 계층(``CostValidator`` 도 같은 문장으로
    막는다)이 대신 던진 것을 제 보호로 착각한다 (고의 위반 10 이 그것을
    드러냈다).
    """
    state, mine = board(repository)
    theirs = state.create_instance(POT_OF_GREED, owner=THEIRS, zone=Zone.HAND)
    definition = definition_of()
    spec = hand_spec(definition.effect_ref)

    answers = {}
    for viewer in (MINE, THEIRS):
        for name, instance in (("mine", mine), ("theirs", theirs.instance_id)):
            _, eligibility = dormant_gates(
                state, definition, instance, spec, drawn_event(), viewer=viewer
            )
            answers[(viewer, name)] = eligibility.may_activate

    assert answers[(MINE, "mine")] is True
    assert answers[(MINE, "theirs")] is False
    assert answers[(THEIRS, "mine")] is False
    assert answers[(THEIRS, "theirs")] is True

    with pytest.raises(TypeError, match="GameStateView"):
        TriggerEligibilityJudge(state)

    # 그 보호가 **이 클래스의 __init__ 안**에 있는가 (AST 로 확인한다).
    init = None
    for node in ast.walk(ast.parse(source_of("engine/trigger.py"))):
        if isinstance(node, ast.ClassDef) and node.name == "TriggerEligibilityJudge":
            init = next(
                child
                for child in node.body
                if isinstance(child, ast.FunctionDef) and child.name == "__init__"
            )
    assert init is not None
    guarded = [
        node
        for node in ast.walk(init)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
        and any(
            isinstance(arg, ast.Name) and arg.id == "GameStateView" for arg in node.args
        )
    ]
    assert len(guarded) == 1
    assert any(isinstance(node, ast.Raise) for node in ast.walk(init))


def test_28_no_agent_module_imports_any_trigger_module():
    """
    **AI / Search 는 live 계층만 소비한다.** ``agent/`` 의 어느 모듈도 다섯
    trigger 모듈을 import 하지 않는다 — ``duel`` · ``action`` ·
    ``game_state_view`` · ``validation`` · ``vocabulary`` 뿐이다.
    """
    trigger_modules = {
        "engine.trigger",
        "engine.trigger_chain",
        "engine.trigger_order",
        "engine.timing",
        "engine.event_pipeline",
    }
    offenders = {}
    for path in sorted(PROJECT_ROOT.glob("agent/**/*.py")):
        modules = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
        hits = modules & trigger_modules
        if hits:
            offenders[path.relative_to(PROJECT_ROOT).as_posix()] = sorted(hits)
    assert offenders == {}


# ======================================================================
# G. R-1 과 R-3 — 3-E-40 의 UNKNOWN policy 와 닿는 자리
# ======================================================================


def test_29_r1_chain_code_appears_in_none_of_the_five_gates():
    """
    **R-1 은 이번 측정에서 의미 차이를 만들지 않는다.**

    ``CHAIN_DEFINITION_UNAVAILABLE`` 은 다섯 관문의 코드 집합에 **없다**.
    그 코드가 ``CODE_VALIDITY`` 에서 ``None`` 인 사실은 그대로지만, 관문
    일치성 측정과는 닿지 않는다. 추측 대신 **코드 집합을 세어** 확인한다.
    """
    gate_names = (
        "_event_relation",
        "_activation_zone",
        "_trigger_condition",
        "_execution_authority",
        "_cost_feasibility",
    )
    union = set()
    for name in gate_names:
        union |= codes_in(function_of("engine/trigger.py", name))

    assert union == {
        "OK",
        "RULE_NOT_IMPLEMENTED",
        "HIDDEN_CARD",
        "SOURCE_WRONG_ZONE",
        "CANDIDATE_NOT_ELIGIBLE",
        "INFORMATION_UNAVAILABLE",
        "EXECUTION_FORBIDDEN",
    }
    assert "CHAIN_DEFINITION_UNAVAILABLE" not in union
    assert CODE_VALIDITY[ValidationCode.CHAIN_DEFINITION_UNAVAILABLE] is None


def test_30_r3_exactly_one_gate_production_contradicts_the_unknown_policy():
    """
    **R-3 (이번 Phase 의 새 발견).**

    ``engine/trigger.py`` 의 ``_gate(...)`` 생산 **17자리** 중 코드가 리터럴인
    16자리를 ``CODE_VALIDITY`` 와 맞춰 보면 **정확히 한 자리**가 어긋난다 —
    ``_event_relation`` 의 불일치 분기가 ``INVALID`` 와
    ``RULE_NOT_IMPLEMENTED`` (policy 로는 ``UNKNOWN``) 를 짝짓는다.

    그 한 자리가 **live 대응이 없는 유일한 관문**에 있다. 고치지 않는다 —
    이번 Phase 는 측정이고, UNKNOWN 을 INVALID 로 접는 쪽도 그 반대쪽도
    production 변경이다.
    """
    tree = ast.parse(source_of("engine/trigger.py"))
    literal, conditional = [], []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_gate"
        ):
            continue
        gate, validity, code = node.args[0], node.args[1], node.args[2]
        if not isinstance(code, ast.Attribute):
            conditional.append(node.lineno)
            continue
        declared = ActionValidity[validity.attr]
        policy = CODE_VALIDITY[ValidationCode[code.attr]]
        literal.append(
            {
                "line": node.lineno,
                "gate": gate.attr,
                "declared": declared,
                "code": code.attr,
                "policy": policy,
            }
        )

    assert len(literal) + len(conditional) == 17
    assert len(conditional) == 1  # _trigger_condition 의 UNKNOWN 분기

    disagreements = [row for row in literal if row["policy"] is not row["declared"]]
    assert len(disagreements) == 1, disagreements
    only = disagreements[0]
    assert only["gate"] == "EVENT_RELATION"
    assert only["declared"] is ActionValidity.INVALID
    assert only["code"] == "RULE_NOT_IMPLEMENTED"
    assert only["policy"] is ActionValidity.UNKNOWN


def test_31_the_live_layer_never_pairs_invalid_with_rule_not_implemented():
    """
    R-3 의 짝(``INVALID`` + ``RULE_NOT_IMPLEMENTED``) 을 **직접 적는 자리**가
    ``engine/trigger.py`` 밖에는 하나도 없다.

    재는 것은 정확히 이것이다 — ``ValidationResult.invalid(...)`` 의 첫 인자로
    ``RULE_NOT_IMPLEMENTED`` 를 쓰는 **구문상의** 자리. 이것이 "live 가 그 짝을
    절대 내지 않는다" 는 증명은 **아니다**: ``EffectActivator._fail`` 처럼
    상태(``ActivationStatus``) 로 ``UNKNOWN`` 여부를 가르는 경로는 코드만 바꿔도
    그 짝을 낼 수 있다 (고의 위반 3 이 실제로 그렇게 만들었다). 그 경로를
    막는 것은 **코드 선택**이고, Phase 3-E-38 의 M1 이 그 선택을 고쳐 두었다.
    """
    offenders = []
    for path in sorted(PROJECT_ROOT.glob("engine/**/*.py")) + sorted(
        PROJECT_ROOT.glob("agent/**/*.py")
    ):
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        if relative == "engine/trigger.py":
            continue  # dormant — R-3 이 사는 자리
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "invalid"
                and node.args
            ):
                continue
            first = node.args[0]
            if (
                isinstance(first, ast.Attribute)
                and isinstance(first.value, ast.Name)
                and first.value.id == "ValidationCode"
                and first.attr == "RULE_NOT_IMPLEMENTED"
            ):
                offenders.append((relative, node.lineno))
    assert offenders == []


def test_32_the_dormant_judge_still_keeps_unknown_out_of_pass():
    """
    **모름이 통과로 새지 않는다** — ``GateVerdict.passed`` 는 ``VALID`` 일 때만
    참이다. R-3 이 있어도 이 불변식은 깨지지 않는다 (어긋난 짝은 더 엄격한
    쪽으로 접혀 있다).
    """
    passed = function_of("engine/trigger.py", "passed")
    attributes = {
        node.attr for node in ast.walk(passed) if isinstance(node, ast.Attribute)
    }
    assert "VALID" in attributes
    assert "UNKNOWN" not in attributes


# ======================================================================
# H. 측정이 production 을 바꾸지 않았다
# ======================================================================


def test_33_this_phase_changed_no_production_file():
    """
    감사 파일 하나와 보고서 하나가 이번 Phase 의 전부다. 다섯 관문도 live
    관문도 **한 줄도 고치지 않았다** — 측정만 한다.
    """
    for path, needle in (
        ("engine/trigger.py", "EligibilityGate.EVENT_RELATION"),
        ("engine/duel.py", "if definition.cost.costs:"),
        ("engine/activation.py", "_AVAILABILITY_REFUSAL[availability]"),
        ("engine/action_validation.py", "_NormalSpellActivation(action.source)"),
    ):
        assert needle in source_of(path), f"{path} 에 {needle} 이 없습니다"
