"""
Phase 3-E-24 — ``UNKNOWN`` · ``UNIMPLEMENTED`` · ``MISSING_RULE`` · ``INVALID`` 의
의미가 구조로 갈려 있는가 (감사).

이 Phase 는 production 코드를 바꾸지 않았다. 감사 테스트만 더했다.

한 문장
-------
**네 의미는 이미 구조로 갈려 있고, production 경로(``ActionValidator``)는 그것을
정확히 지킨다.** 느슨한 자리는 **잠든 트리거 계층 두 곳**이고, 둘 다 기존 구조로
표현할 수 있으므로 새 enum 이 필요하지 않다.

의미를 담는 것은 **두 축**이다
------------------------------
``ValidationResult`` 하나가 네 가지를 구분한다 ::

    validity      VALID · INVALID · UNKNOWN          ← 허가인가
    code          48개 (RULE_NOT_IMPLEMENTED · INFORMATION_UNAVAILABLE ·
                  HIDDEN_CARD · CARD_DEFINITION_UNAVAILABLE …)   ← 왜인가
    missing_rule  "없는 규칙 계층의 이름"             ← 무엇이 없는가
    notes         조건 계층이 남긴 말 그대로

그래서 네 문장이 각각 이렇게 적힌다 ::

    "조건이 참이다"                     VALID
    "조건이 거짓이다"                   INVALID + 요구별 코드
    "규칙은 있는데 정보가 없다"          UNKNOWN + INFORMATION_UNAVAILABLE
    "정보는 있는데 판정 구현이 없다"      UNKNOWN + RULE_NOT_IMPLEMENTED + missing_rule

``ActionValidator._check_requirements`` 가 그 갈림을 코드로 적어 두었다 —
"'정보가 없어서' 와 '규칙이 없어서' 는 다른 사실이다. 조건 자신이 안다 —
검증기가 추측하지 않는다."

찾은 느슨한 자리 둘 (둘 다 dormant)
-----------------------------------
1. ``TriggerCollector._judge`` 는 **조건이 거짓일 때도** ``code`` 를
   ``RULE_NOT_IMPLEMENTED`` 로 적는다. ``status`` 는 ``INELIGIBLE`` 로 맞게
   적히므로 **판정은 틀리지 않지만 이유가 틀린다.** 쓸 수 있는 코드
   (``CANDIDATE_NOT_ELIGIBLE``)가 이미 있다.
2. ``TriggerCollector(view, registry)`` 에서 ``definitions`` 를 **주지 않으면**
   "조건을 적지 않은 선언" 이 ``ELIGIBLE`` 이 되고, **주면** 같은 선언이
   ``UNKNOWN`` 이 된다. 즉 **"조건이 없다" 와 "확인하지 못했다" 가 생성자
   인자에 따라 갈린다.** 위험한 방향(모름 → 허가)이다.

둘 다 **구조의 한계가 아니라 기본값과 코드 선택**의 문제다. 그래서 이
Phase 는 신규 STRUCTURAL ID 를 만들지 않고, 잠든 계층을 연결할 때의 계약으로
남긴다 — **production 에서 ``TriggerCollector`` 를 만들 때 ``definitions`` 를
반드시 넘긴다.**
"""

import ast
import pathlib

import pytest

from analysis.predicate_model import EvalReadiness
from engine.action import PlayerAction, PlayerActionKind
from engine.condition.model import Always, UnimplementedRule
from engine.condition.result import ConditionResult
from engine.duel import Duel
from engine.effect.delta import ZoneMoved
from engine.effect.library import ExecutionAvailability, definition_registry
from engine.effect.semantics import OperationKind
from engine.ids import EffectRef
from engine.trigger import (
    EligibilityGate,
    GateVerdict,
    TimingEvent,
    TimingPoint,
    TriggerCandidate,
    TriggerCollector,
    TriggerEligibility,
    TriggerRegistry,
    TriggerSpec,
    TriggerStatus,
)
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
POT_OF_GREED = 55144522
FEATHERMAN = 21844576


def small_duel(repository, *, seed: int = 5) -> Duel:
    deck = [POT_OF_GREED] * 8 + [FEATHERMAN] * 8
    return Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)


def at_main1(duel: Duel) -> Duel:
    while duel.state.turn.phase is not Phase.MAIN1:
        duel.apply(PlayerAction(kind=PlayerActionKind.END_PHASE, actor=duel.turn_player))
        duel.advance()
    return duel


def destroyed(instance, *, seat: int) -> TimingEvent:
    return TimingEvent.from_delta(
        ZoneMoved(
            movement=OperationKind.DESTROY,
            card=instance,
            source_player=seat,
            source_zone=Zone.MZONE,
            destination_player=seat,
            destination_zone=Zone.GRAVE,
        )
    )


# ======================================================================
# §3 · §8 — 네 의미를 담는 두 축
# ======================================================================


def test_01_the_result_carries_both_the_verdict_and_the_reason():
    """
    **§8 — 허가 여부(3값)와 이유(48코드)가 따로 있다.**

    그래서 "거짓" 과 "모름" 과 "구현 없음" 이 같은 자리에 섞이지 않는다.
    ``missing_rule`` 이 **"무엇이 없는가"** 를 따로 들고 다닌다.
    """
    assert {v.value for v in ActionValidity} == {"valid", "invalid", "unknown"}
    assert {f for f in ValidationResult.__dataclass_fields__} == {
        "validity",
        "code",
        "reason",
        "missing_rule",
        "notes",
    }

    #: 네 의미의 대표 코드가 **따로** 있다.
    for name in (
        "RULE_NOT_IMPLEMENTED",
        "INFORMATION_UNAVAILABLE",
        "HIDDEN_CARD",
        "CARD_DEFINITION_UNAVAILABLE",
        "EFFECT_LIST_UNRELIABLE",
        "CANDIDATE_NOT_ELIGIBLE",
        "COST_NOT_IMPLEMENTED",
    ):
        assert hasattr(ValidationCode, name), name

    #: ``unknown`` 만 ``missing_rule`` 을 받는다 — 거짓에는 그 칸이 없다.
    unknown = ValidationResult.unknown(
        ValidationCode.RULE_NOT_IMPLEMENTED, "x", missing_rule="어떤 계층"
    )
    assert unknown.validity is ActionValidity.UNKNOWN
    assert unknown.missing_rule == "어떤 계층"
    invalid = ValidationResult.invalid(ValidationCode.NOT_TURN_PLAYER, "x")
    assert invalid.validity is ActionValidity.INVALID
    assert invalid.missing_rule is None

    #: **구조가 혼동을 막는다.** ``invalid()`` 는 ``missing_rule`` 을 **받지
    #: 못한다** — "규칙이 없다" 를 "규칙 위반" 으로 옮겨 적으려면 그 정보를
    #: 버려야 하고, 그러면 호출자가 즉시 깨진다 (고의 위반 B 가 그렇게 잡혔다).
    with pytest.raises(TypeError):
        ValidationResult.invalid(
            ValidationCode.RULE_NOT_IMPLEMENTED, "x", missing_rule="어떤 계층"
        )


def test_02_the_validator_splits_false_from_unknown_and_unknown_from_unimplemented():
    """
    **§4 · §8 — production 경로가 네 길을 정확히 가른다.**

    ``_check_requirements`` 의 구조가 그 자체로 증거다:
    ``FALSE`` → ``invalid(요구별 코드)`` · ``UNKNOWN`` + 규칙 이름 있음 →
    ``RULE_NOT_IMPLEMENTED`` · ``UNKNOWN`` + 없음 → ``INFORMATION_UNAVAILABLE``.
    """
    source = (PROJECT_ROOT / "engine/action_validation.py").read_text(encoding="utf-8")
    body = source.split("def _check_requirements")[1].split("\n    def ")[0]

    assert "if verdict.result is ConditionResult.FALSE:" in body
    assert "return ValidationResult.invalid(requirement.code, requirement.detail)" in body
    assert "if verdict.result is ConditionResult.UNKNOWN:" in body
    assert "missing_rules(self._view, context)" in body
    assert "ValidationCode.RULE_NOT_IMPLEMENTED" in body
    assert "ValidationCode.INFORMATION_UNAVAILABLE" in body
    #: 이 문장이 지워지면 경계가 흐려진 것이다.
    assert "는 다른 사실이다" in body


@pytest.mark.real_card
def test_03_unknown_actions_are_withheld_with_the_missing_rule_named(repository):
    """
    **§8 — UNKNOWN 은 후보가 되지 않고, 왜인지가 함께 남는다.**

    실제 듀얼에서 `ACTIVATE_CARD` 는 아직 판정할 규칙이 없어 `withheld` 로 가고
    ``missing`` 에 그 계층의 이름이 적힌다. **"허가 아님" 이 "금지" 로 바뀌지
    않는다.**
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    legal = duel.legal_actions(seat)

    held = [w for w in legal.withheld if w.kind is PlayerActionKind.ACTIVATE_CARD]
    assert held, [w.kind.value for w in legal.withheld]
    assert held[0].missing  # 무엇이 없는지 적혀 있다
    assert "activation-timing" in held[0].missing

    #: 그리고 그것은 허가 목록에 **없다**.
    assert not [a for a in legal.allowed if a.kind is PlayerActionKind.ACTIVATE_CARD]

    #: **가장 중요한 한 줄** — 검증기의 판정이 ``UNKNOWN`` 이어야 한다.
    #: ``INVALID`` 로 바꾸면 "규칙이 없다" 가 "규칙 위반" 으로 읽힌다.
    from engine.action_validation import ActionValidator

    validator = ActionValidator(duel.view(seat))
    verdict = validator.validate(
        PlayerAction.activate_card(
            actor=seat, source=duel.state.player(seat).hand[0].instance_id
        )
    )
    assert verdict.validity is ActionValidity.UNKNOWN, verdict
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert verdict.missing_rule  # 무엇이 없는지 이름이 있다


# ======================================================================
# §4 — 조건 계층의 3값 논리
# ======================================================================


def test_04_condition_logic_is_three_valued_and_false_beats_unknown():
    """
    **§4 — ``UNKNOWN`` 을 참으로도 거짓으로도 접지 않는다.**

    단, ``FALSE`` 는 ``UNKNOWN`` 을 이긴다 — 확실한 위반 하나면 나머지를 몰라도
    거부다. 그 규약이 `all_of`/`any_of` 에 적혀 있다.
    """
    T, F, U = ConditionResult.TRUE, ConditionResult.FALSE, ConditionResult.UNKNOWN
    assert ConditionResult.all_of([T, U]) is U
    assert ConditionResult.all_of([F, U]) is F
    assert ConditionResult.all_of([]) is T  # 조건이 없으면 막을 것이 없다
    assert ConditionResult.any_of([F, U]) is U
    assert ConditionResult.any_of([T, U]) is T
    assert ConditionResult.any_of([]) is F


def test_05_unimplemented_rule_is_unknown_and_names_what_is_missing():
    """
    **§6 — "판정할 규칙이 없다" 를 말하는 수단이 이미 있다.**

    ``UnimplementedRule`` 은 언제나 ``UNKNOWN`` 이고 ``missing_rules`` 로 이름을
    남긴다. ``Always``(언제나 참)와 **구조적으로 다르다** — 둘을 섞을 수 없다.
    """
    rule = UnimplementedRule("chain (Phase 2-F)")
    assert rule.evaluate(None, None) is ConditionResult.UNKNOWN
    assert rule.missing_rules(None, None) == ("chain (Phase 2-F)",)
    assert rule.unknown_reasons(None, None) == ("규칙 미구현: chain (Phase 2-F)",)

    assert Always().evaluate(None, None) is ConditionResult.TRUE
    assert Always().missing_rules(None, None) == ()


# ======================================================================
# §9 — 트리거 적격성의 접기 순서
# ======================================================================


def test_06_eligibility_folds_forbidden_then_false_then_unknown():
    """
    **§9 — 제안된 "안전한 원칙" 이 이미 구현되어 있다.**

    ``FORBIDDEN`` > ``INELIGIBLE`` > ``UNKNOWN`` > ``ELIGIBLE``. 그래서
    **모름 때문에 후보가 사라지지 않고**, 금지는 다른 통과를 덮는다.
    """
    candidate = TriggerCandidate(
        point=TimingPoint.CARD_MOVED,
        effect_ref=EffectRef(1, 0),
        source=__import__("engine.ids", fromlist=["InstanceId"]).InstanceId(1),
        controller=0,
    )

    def gate(
        result: ValidationResult, which: EligibilityGate = EligibilityGate.TRIGGER_CONDITION
    ) -> GateVerdict:
        """``GateVerdict`` 는 ``ValidationResult`` 를 그대로 싣는다 — 허가와 이유를
        따로 다시 적지 않는다."""
        return GateVerdict(gate=which, result=result)

    valid = ValidationResult.valid("감사용")
    unknown = ValidationResult.unknown(ValidationCode.RULE_NOT_IMPLEMENTED, "감사용")
    invalid = ValidationResult.invalid(ValidationCode.CANDIDATE_NOT_ELIGIBLE, "감사용")
    #: 금지는 **코드**로 알아본다 (ADR-004) — ``INVALID`` 중에서도 따로 구분한다.
    forbidden = ValidationResult.invalid(ValidationCode.EXECUTION_FORBIDDEN, "감사용")

    def fold(*verdicts) -> TriggerStatus:
        return TriggerEligibility.fold(candidate, tuple(verdicts)).status

    assert fold(gate(valid)) is TriggerStatus.ELIGIBLE
    assert fold(gate(unknown)) is TriggerStatus.UNKNOWN
    assert fold(gate(invalid)) is TriggerStatus.INELIGIBLE
    #: 거짓이 모름을 이긴다.
    assert (
        fold(gate(unknown), gate(invalid, EligibilityGate.ACTIVATION_ZONE))
        is TriggerStatus.INELIGIBLE
    )
    #: 금지가 전부를 덮는다 — 다른 관문이 통과해도.
    assert (
        fold(gate(valid), gate(forbidden, EligibilityGate.EXECUTION_AUTHORITY))
        is TriggerStatus.FORBIDDEN
    )
    #: 그리고 ``passed`` 는 ``VALID`` 일 때만 참이다.
    assert gate(valid).passed and not gate(unknown).passed
    assert gate(forbidden).forbids and not gate(invalid).forbids


def test_07_unknown_never_leaks_into_permission():
    """
    **§2 — ``UNKNOWN`` ≠ 허가.** ``is_candidate`` 는 ``ELIGIBLE`` 일 때만 참이다.
    """
    assert TriggerStatus.ELIGIBLE.is_candidate
    for status in (TriggerStatus.UNKNOWN, TriggerStatus.FORBIDDEN, TriggerStatus.INELIGIBLE):
        assert not status.is_candidate, status


# ======================================================================
# §10 · §11 — 발견된 느슨한 자리 둘
# ======================================================================


@pytest.mark.real_card
def test_08_a_false_condition_is_reported_with_the_unimplemented_code(repository):
    """
    **발견 ① — ``status`` 는 맞는데 ``code`` 가 틀렸다. Phase 3-E-26 에서 고쳤다.**

    이 함수 이름은 3-E-24 가 **결함을 측정했을 때** 붙인 이름이라 그대로 둔다
    (그 발견을 찾는 사람이 이 자리에 닿아야 한다). 이제 하는 일은 반대다 —
    고친 것이 **되돌아가지 않는지** 지킨다.

    고친 내용:

    * 조건이 거짓 → ``INELIGIBLE`` + ``CANDIDATE_NOT_ELIGIBLE``
      (``RULE_NOT_IMPLEMENTED`` 는 "이 엔진이 못 한다" 는 뜻이고, 조건을
      끝까지 보고 받은 거짓은 미구현이 아니다)
    * 출처 금지 → ``FORBIDDEN`` + ``EXECUTION_FORBIDDEN``
      (금지를 알아보는 ``GateVerdict.forbids`` 가 **코드로** 판단하므로, 같은
      사실을 두 계층이 다른 코드로 말하면 한쪽이 안 보인다)
    """
    source = (PROJECT_ROOT / "engine/trigger.py").read_text(encoding="utf-8")
    judge = source.split("def _judge")[1].split("\n    def ")[0]
    false_branch = judge.split("if combined is ConditionResult.FALSE:")[1].split(
        "return TriggerCandidate("
    )[1][:600]
    assert "TriggerStatus.INELIGIBLE" in false_branch  # 판정은 그대로 맞다
    assert "ValidationCode.CANDIDATE_NOT_ELIGIBLE" in false_branch  # 이유도 맞아졌다
    assert "조건이 거짓입니다" in false_branch

    #: 같은 사실을 말하는 관문(``_trigger_condition``)도 같은 코드를 쓴다 —
    #: 수집기와 판정기가 어긋나 있으면 한쪽을 고쳐도 다른 쪽이 남는다.
    gate = source.split("def _trigger_condition")[1].split("\n    def ")[0]
    gate_false = gate.split("if combined is ConditionResult.FALSE:")[1][:600]
    assert "ActionValidity.INVALID" in gate_false
    assert "ValidationCode.CANDIDATE_NOT_ELIGIBLE" in gate_false
    assert "ValidationCode.RULE_NOT_IMPLEMENTED" not in gate_false

    #: 금지는 **금지 코드로** 적는다. 그래야 ``GateVerdict.forbids`` 가 본다.
    forbidden_branch = judge.split("provenance.is_forbidden:")[1][:700]
    assert "TriggerStatus.FORBIDDEN" in forbidden_branch
    assert "ValidationCode.EXECUTION_FORBIDDEN" in forbidden_branch
    assert "ADR-004" in forbidden_branch
    forbids_source = source.split("def forbids")[1][:300]
    assert "ValidationCode.EXECUTION_FORBIDDEN" in forbids_source


@pytest.mark.real_card
def test_09_the_same_declaration_is_eligible_or_unknown_by_a_constructor_argument(
    repository,
):
    """
    **발견 ② — "조건이 없다" 와 "확인하지 못했다" 가 생성자 인자로 갈린다.**

    ``definitions`` 를 주지 않으면 조건을 적지 않은 선언이 ``ELIGIBLE`` 이 되고,
    주면 같은 선언이 ``UNKNOWN`` 이 된다. **모름이 허가로 새는 방향**이므로,
    연결할 때는 ``definitions`` 를 반드시 넘겨야 한다.
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    view = duel.view(seat)
    hand = duel.state.player(seat).hand

    #: 등록된 적 없는 효과 자리를 가리키는 선언 (조건도 적지 않았다).
    spec = TriggerSpec(
        effect_ref=EffectRef(hand[0].card_id, 3), point=TimingPoint.CARD_MOVED
    )
    registry = TriggerRegistry().register(spec)
    event = destroyed(hand[1].instance_id, seat=seat)

    without = TriggerCollector(view, registry).collect(event)
    with_definitions = TriggerCollector(view, registry, definition_registry()).collect(
        event
    )
    assert without.candidates and with_definitions.candidates

    assert {c.status for c in without.candidates} == {TriggerStatus.ELIGIBLE}
    assert {c.code for c in without.candidates} == {ValidationCode.OK}

    assert {c.status for c in with_definitions.candidates} == {TriggerStatus.UNKNOWN}
    assert {c.code for c in with_definitions.candidates} == {
        ValidationCode.RULE_NOT_IMPLEMENTED
    }
    assert "정의가 등록되어 있지 않아" in with_definitions.candidates[0].reason

    #: 선언 자신의 설명은 이미 올바른 원칙을 적어 두었다.
    source = (PROJECT_ROOT / "engine/trigger.py").read_text(encoding="utf-8")
    assert "조건이 없다는 뜻이 아니라 적지 않았다는 뜻" in source


# ======================================================================
# §6 · §7 — 기존 어휘가 네 축을 덮는가
# ======================================================================


def test_10_execution_availability_already_says_rule_exists_but_code_does_not():
    """
    **§6-1 · §7-④ — "규칙은 있고 구현이 없다" 를 말하는 어휘가 이미 있다.**

    ``ExecutionAvailability`` (ADR-006). ``no_implementation`` 과
    ``forbidden_source`` 와 ``unverified`` 가 **서로 다른 값**이다.
    """
    values = {a.value for a in ExecutionAvailability}
    assert values == {
        "executable",
        "no_implementation",
        "forbidden_source",
        "unverified",
        "unknown",
    }
    #: ADR-006 문서의 이름(``NOT_ADDRESSABLE`` · ``TEXT_DERIVED`` ·
    #: ``NO_EFFECT``)과 코드의 이름이 다르다 — 문서가 앞서 적힌 흔적이다.
    #: 의미는 같은 축이고, 이 Phase 는 **고치지 않고 기록만** 한다.
    adr = (PROJECT_ROOT / "docs/phase2-architecture-decisions.md").read_text(
        encoding="utf-8"
    )
    assert "NO_IMPLEMENTATION" in adr
    assert "NOT_ADDRESSABLE" in adr


def test_11_the_analysis_layer_stops_at_needs_context():
    """
    **§12 — 계층 책임 경계.**

    분석 계층은 "이 조건은 문맥이 필요하다" 까지만 말하고 **"구현이 없다" 를
    말하지 않는다** (``EvalReadiness`` 에 그런 값이 없다). "구현이 없다" 는
    엔진의 질문이고 ``ValidationCode.RULE_NOT_IMPLEMENTED`` ·
    ``ExecutionAvailability.NO_IMPLEMENTATION`` 이 답한다 — ADR-006 이
    "같은 카드 데이터를 쓰는 두 엔진 빌드가 서로 다른 답을 내야 한다" 고
    적어 둔 그 이유다.
    """
    assert {r.value for r in EvalReadiness} == {"evaluable", "needs_context", "unknown"}
    assert not [r for r in EvalReadiness if "implement" in r.value]

    #: 분석 모듈은 엔진의 구현 상태를 import 하지 않는다.
    for name in ("analysis/predicate_model.py", "analysis/effect_model.py"):
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        assert "ValidationCode" not in text, name
        assert "ExecutionAvailability" not in text, name


def test_12_hidden_information_has_its_own_code_separate_from_unimplemented():
    """
    **§13 — 가려진 정보와 미구현은 다른 코드다.**

    ``HIDDEN_CARD`` 는 "관측에 없다 — **없다는 뜻이 아니다**" 라고 스스로 적어
    두었고, ``RULE_NOT_IMPLEMENTED`` 와 다른 값이다. 그리고 후보 수집은 가려진
    자리를 ``unchecked`` 로 남긴다 (3-E-20).
    """
    assert ValidationCode.HIDDEN_CARD is not ValidationCode.RULE_NOT_IMPLEMENTED
    source = (PROJECT_ROOT / "engine/validation.py").read_text(encoding="utf-8")
    hidden_doc = source.split('HIDDEN_CARD = "hidden_card"')[1][:160]
    assert "없다는 뜻이 아니다" in hidden_doc

    #: 두 코드가 서로 다른 자리에서 쓰인다.
    used = {}
    for path in sorted((PROJECT_ROOT / "engine").rglob("*.py")):
        if path.name == "validation.py":
            continue
        text = path.read_text(encoding="utf-8")
        for code in ("HIDDEN_CARD", "RULE_NOT_IMPLEMENTED"):
            if f"ValidationCode.{code}" in text:
                used.setdefault(code, set()).add(path.name)
    assert used["HIDDEN_CARD"] & used["RULE_NOT_IMPLEMENTED"] != used["RULE_NOT_IMPLEMENTED"]


def test_13_search_marks_unknown_instead_of_scoring_it_zero():
    """
    **§14 — 탐색은 ``UNKNOWN`` 을 0점으로 접지 않는다.**

    평가에는 ``ExclusionCategory.UNKNOWN`` 과 ``partial`` 이 있고
    (Phase 3-E-7 · 3-E-8), 시뮬레이션에는 ``SimulationStatus.UNKNOWN`` 과
    ``REFUSED`` 가 따로 있다. 그리고 UNKNOWN 판정을 받은 행위는 애초에
    ``legal_actions().allowed`` 에 들어오지 않는다 (`test_03`).
    """
    from agent.evaluation import ExclusionCategory
    from agent.simulation import SimulationStatus

    assert "unknown" in {c.value for c in ExclusionCategory}
    assert {"unknown", "refused", "not_a_candidate"} <= {
        s.value for s in SimulationStatus
    }
    evaluation = (PROJECT_ROOT / "agent/evaluation.py").read_text(encoding="utf-8")
    assert "UNKNOWN`` 이 하나라도 있는가" in evaluation
