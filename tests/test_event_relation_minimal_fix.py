r"""
Phase 3-E-45 — ``_event_relation`` 판정 조합 최소 수정의 회귀 시험.

Phase 3-E-44 가 **R-3** 로 측정한 한 자리를 고쳤다 —
``TriggerEligibilityJudge._event_relation`` 이 ``ActionValidity.INVALID`` 와
``ValidationCode.RULE_NOT_IMPLEMENTED`` 를 **짝지어** 내고 있었고, Phase 3-E-40
의 :data:`~engine.validation.CODE_VALIDITY` 는 그 코드를 ``UNKNOWN`` 으로
분류한다.

고치면서 드러난 것이 더 중요하다 — ``TriggerSpec.matches`` 의 ``False`` 는
**한 가지 사실이 아니었다.** 그래서 코드만 치환하지 않고 세 갈래로 갈랐다.

======================================  ===================================
같은 입력                                 판정 / 코드
======================================  ===================================
선언과 사건이 맞는다                        ``VALID`` / ``OK``
양쪽 값이 다 있고 **다르다**                 ``INVALID`` / ``CANDIDATE_NOT_ELIGIBLE``
사건이 ``UNIMPLEMENTED`` 다                ``UNKNOWN`` / ``RULE_NOT_IMPLEMENTED``
선언이 건 필터를 사건이 안 들고 있다           ``UNKNOWN`` / ``INFORMATION_UNAVAILABLE``
======================================  ===================================

**왜 코드만 바꾸면 안 됐는가.** 뒤의 둘을 ``INVALID`` 로 적으면 "규칙이
막았다" 는 거짓이 되고, 그것이 이 Phase 가 고치려던 바로 그 섞임이다.
그리고 ``UNIMPLEMENTED`` 사건은 가정이 아니다 — ``timing_for`` 가 옮길 이름이
없는 변화(리로드의 셔플) 를 실제로 그 시점으로 남긴다 (STRUCTURAL-74,
``test_12``).

**새 enum 도 새 어휘도 만들지 않았다.** ``UNKNOWN`` 안에서 까닭을 가르는
방법은 ``_trigger_condition`` 이 이미 쓰는 것 그대로다.

**이 Phase 는 ``EVENT_RELATION`` 하나만 다뤘다.** 3-E-44 가 기록한
``ACTIVATION_ZONE`` · ``COST_FEASIBILITY`` 의 ``DIFFERENT_RESULT`` 는 **그대로
남아 있다** (``test_18``).
"""

import ast
import pathlib

import pytest

from engine.effect import (
    CardDrawn,
    LifeChanged,
    DrawOperation,
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectImplementationRegistry,
    EffectProvenance,
    OperationKind,
    ZoneMoved,
)
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
    TriggerStatus,
    timing_for,
)
from engine.trigger_chain import _refusal_code, _undecided_code
from engine.validation import CODE_VALIDITY, ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

MINE, THEIRS = 0, 1
WATCHER = 1000
"""트리거를 등록할 카드. **의미를 주장하지 않는다** — 껍데기다."""
WATCHED = EffectRef(WATCHER, 0)
HAND_OR_FIELD = frozenset({Zone.HAND, Zone.MZONE})


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def gate_function() -> ast.FunctionDef:
    """``_event_relation`` 의 **함수 본문 노드**. 문자열 창으로 재지 않는다."""
    for node in ast.walk(ast.parse(source_of("engine/trigger.py"))):
        if isinstance(node, ast.FunctionDef) and node.name == "_event_relation":
            return node
    raise AssertionError("engine/trigger.py 에 _event_relation 이 없습니다")


# ======================================================================
# 판과 도구 — 셔플하지 않고, 판을 바꾸지 않는다
# ======================================================================


@pytest.fixture
def state() -> GameState:
    #: seed 를 준다 — ``state.rng`` 를 읽으려면 난수원이 있어야 한다
    #: (``test_19``). 셔플은 하지 않으므로 판은 결정적이다.
    game = GameState.create(decks=([WATCHER] * 8, [WATCHER] * 5), seed=1)
    game.draw(MINE, 4)
    game.draw(THEIRS, 2)
    game.move(game.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.turn.set_phase(Phase.MAIN1)
    return game


def definition() -> EffectDefinition:
    return EffectDefinition(
        effect_ref=WATCHED,
        source_card_id=WATCHER,
        operations=(DrawOperation(1),),
        activation=None,
        provenance=EffectProvenance.official_lua(),
    )


def judge(state: GameState, spec: TriggerSpec, event: TimingEvent):
    """그 선언과 그 사건으로 다섯 관문을 돌린다. **판을 읽기만 한다.**"""
    view = GameStateView.from_state(state, viewer=MINE)
    effect = definition()
    candidate = TriggerCandidate(
        point=spec.point,
        effect_ref=WATCHED,
        source=state.player(MINE).monster_zone[0].instance_id,
        controller=MINE,
    )
    return TriggerEligibilityJudge(
        view,
        EffectDefinitionRegistry((effect,)),
        EffectImplementationRegistry((WATCHED,)),
    ).judge(candidate, spec, event)


def relation(eligibility):
    verdict = eligibility.gate(EligibilityGate.EVENT_RELATION)
    assert verdict is not None
    return verdict


def drawn_event() -> TimingEvent:
    return TimingEvent.from_delta(CardDrawn(MINE, InstanceId(2)))


def moved_event(destination=Zone.GRAVE, movement=OperationKind.SEND_TO_GRAVE):
    return TimingEvent.from_delta(
        ZoneMoved(
            movement=movement,
            card=InstanceId(2),
            source_player=MINE,
            source_zone=Zone.MZONE,
            destination_player=MINE,
            destination_zone=destination,
        )
    )


def drawn_spec() -> TriggerSpec:
    return TriggerSpec(
        WATCHED, TimingPoint.CARD_DRAWN, activates_from=HAND_OR_FIELD
    )


def filtered_spec(**filters) -> TriggerSpec:
    filters.setdefault("operations", frozenset({OperationKind.SEND_TO_GRAVE}))
    return TriggerSpec(
        WATCHED, TimingPoint.CARD_MOVED, activates_from=HAND_OR_FIELD, **filters
    )


# ======================================================================
# A. 맞는 짝 — 바뀌지 않았다
# ======================================================================


def test_01_a_matching_declaration_still_passes(state):
    """**R1** 선언과 사건이 맞으면 ``VALID`` / ``OK`` 다. 이 쪽은 손대지 않았다."""
    verdict = relation(judge(state, drawn_spec(), drawn_event()))
    assert (verdict.validity, verdict.code) == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )
    assert verdict.passed is True


def test_02_a_matching_filtered_declaration_still_passes(state):
    """**R2** 필터까지 맞는 경우도 그대로다."""
    verdict = relation(
        judge(state, filtered_spec(to_zones=frozenset({Zone.GRAVE})), moved_event())
    )
    assert (verdict.validity, verdict.code) == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )


# ======================================================================
# B. 값이 다 있고 다르다 → 확정된 거부
# ======================================================================


@pytest.mark.parametrize(
    "label, spec_factory, event_factory",
    [
        (
            "R3 시점이 다르다 (LIFE_CHANGED 선언 ← CARD_DRAWN 사건)",
            lambda: TriggerSpec(
                WATCHED, TimingPoint.LIFE_CHANGED, activates_from=HAND_OR_FIELD
            ),
            drawn_event,
        ),
        (
            "R4 의미 필터가 다르다 (SEND_TO_GRAVE 선언 ← DESTROY 사건)",
            filtered_spec,
            lambda: moved_event(movement=OperationKind.DESTROY),
        ),
        (
            "R5 도착 존 필터가 다르다 ({GRAVE} 선언 ← MZONE 도착)",
            lambda: filtered_spec(to_zones=frozenset({Zone.GRAVE})),
            lambda: moved_event(destination=Zone.MZONE),
        ),
        (
            "R6 출발 존 필터가 다르다 ({GRAVE} 선언 ← MZONE 출발)",
            lambda: filtered_spec(from_zones=frozenset({Zone.GRAVE})),
            moved_event,
        ),
    ],
)
def test_03_an_informed_mismatch_is_a_definite_refusal(
    state, label, spec_factory, event_factory
):
    """
    **R3–R6: 네 모양 모두 확정된 거부다.**

    사건이 비교에 필요한 값을 **다 들고 있고** 그것이 선언과 다르다.
    :meth:`TriggerSpec.matches` 는 규칙 판단이 아니라 데이터 비교이므로
    여기서 답이 확정된다 — "엔진이 아직 못 한다" 가 아니다.

    코드는 저장소가 같은 사실에 이미 쓰는 것이다 (``_trigger_condition`` ·
    ``TriggerCollector._judge`` · ``EffectActivator._check_condition``,
    Phase 3-E-26 · 3-E-38).
    """
    verdict = relation(judge(state, spec_factory(), event_factory()))
    assert (verdict.validity, verdict.code) == (
        ActionValidity.INVALID,
        ValidationCode.CANDIDATE_NOT_ELIGIBLE,
    ), label
    assert verdict.passed is False
    #: 금지가 아니다 — ADR-004 의 "이 근거로는 실행하지 않는다" 와 다른 말이다.
    assert verdict.forbids is False


def test_04_an_informed_mismatch_folds_to_ineligible(state):
    """확정된 거부는 ``INELIGIBLE`` 로 접힌다 — ``UNKNOWN`` 이 아니다."""
    eligibility = judge(
        state,
        TriggerSpec(WATCHED, TimingPoint.LIFE_CHANGED, activates_from=HAND_OR_FIELD),
        drawn_event(),
    )
    assert eligibility.status is TriggerStatus.INELIGIBLE
    assert eligibility.may_activate is False


# ======================================================================
# C. 맞춰 볼 수 없었다 → 모름 (이 Phase 가 새로 가른 자리)
# ======================================================================


def test_05_an_unimplemented_event_is_unknown_not_a_refusal(state):
    """
    **R7 — 이 Phase 의 핵심.**

    사건이 ``UNIMPLEMENTED`` 면 **무슨 일이 있었는지 모른다.** 거기에
    "이 선언은 반응하지 않는다" 는 확정 거부를 적을 근거가 없다.

    고치기 전에는 이 자리가 ``INVALID`` / ``RULE_NOT_IMPLEMENTED`` 였고,
    후보 상태가 ``INELIGIBLE`` 로 접혔다 — **셔플 하나 때문에 "규칙이
    막았다" 고 말하는 셈**이었다.
    """
    event = TimingEvent.unimplemented("전투 데미지 계층이 없다", actor=MINE)
    eligibility = judge(state, drawn_spec(), event)
    verdict = relation(eligibility)

    assert (verdict.validity, verdict.code) == (
        ActionValidity.UNKNOWN,
        ValidationCode.RULE_NOT_IMPLEMENTED,
    )
    #: **모름이 통과로도 거부로도 접히지 않는다.**
    assert verdict.passed is False
    assert eligibility.status is TriggerStatus.UNKNOWN
    assert eligibility.may_activate is False

    #: 무엇을 표현할 수 없었는지 그대로 실어 보낸다 — 새 필드를 만들지 않았다.
    assert verdict.result.missing_rule == "전투 데미지 계층이 없다"
    assert verdict.result.notes == ("전투 데미지 계층이 없다",)


def test_06_an_unimplemented_event_is_unknown_for_a_filtered_spec_too(state):
    """**R8** 필터가 걸린 선언에도 같다. 사건을 모르면 어느 선언이든 모른다."""
    event = TimingEvent.unimplemented("ZoneShuffled 를 옮길 시점 이름이 없다")
    verdict = relation(judge(state, filtered_spec(), event))
    assert (verdict.validity, verdict.code) == (
        ActionValidity.UNKNOWN,
        ValidationCode.RULE_NOT_IMPLEMENTED,
    )


@pytest.mark.parametrize(
    "label, filters, expected_notes",
    [
        (
            "R9 의미 필터를 읽을 수 없다",
            {"operations": frozenset({OperationKind.SEND_TO_GRAVE})},
            ("operations",),
        ),
        (
            "R10 도착 존 필터를 읽을 수 없다",
            {"to_zones": frozenset({Zone.GRAVE})},
            ("to_zones",),
        ),
        (
            "R11 세 필터를 다 읽을 수 없다",
            {
                "operations": frozenset({OperationKind.SEND_TO_GRAVE}),
                "from_zones": frozenset({Zone.MZONE}),
                "to_zones": frozenset({Zone.GRAVE}),
            },
            ("operations", "from_zones", "to_zones"),
        ),
    ],
)
def test_07_an_unreadable_filter_is_unknown(state, label, filters, expected_notes):
    """
    **R9–R11** 선언이 필터를 걸었는데 사건이 그 값을 **들고 있지 않다.**

    ``None not in {...}`` 는 참이므로 ``matches`` 가 ``False`` 를 돌려주지만,
    그것은 "다르다" 가 아니라 **"비교하지 못했다"** 다. 무엇을 읽지 못했는지
    ``notes`` 로 남긴다.
    """
    spec = TriggerSpec(
        WATCHED,
        TimingPoint.CARD_MOVED,
        activates_from=HAND_OR_FIELD,
        **filters,
    )
    #: 선언이 **실제로** 필터를 들고 있어야 이 테스트가 무언가를 잰다.
    assert any(
        getattr(spec, name) is not None
        for name in ("operations", "from_zones", "to_zones")
    ), label
    #: ``delta`` 가 없는 ``CARD_MOVED`` — ``movement`` 를 읽을 수 없는 사건이다.
    event = TimingEvent(TimingPoint.CARD_MOVED)
    verdict = relation(judge(state, spec, event))

    assert (verdict.validity, verdict.code) == (
        ActionValidity.UNKNOWN,
        ValidationCode.INFORMATION_UNAVAILABLE,
    ), label
    assert verdict.result.notes == expected_notes, label


def test_08_an_unfiltered_spec_still_matches_a_deltaless_event(state):
    """
    **R12** 필터를 걸지 않은 선언은 ``movement`` 를 읽을 필요가 없다.
    그래서 ``delta`` 가 없어도 시점만 맞으면 ``VALID`` 다 — 모름 분기가
    **필요 없는 곳까지 번지지 않는다.**
    """
    spec = TriggerSpec(
        WATCHED, TimingPoint.CARD_MOVED, activates_from=HAND_OR_FIELD
    )
    verdict = relation(judge(state, spec, TimingEvent(TimingPoint.CARD_MOVED)))
    assert (verdict.validity, verdict.code) == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )


def test_09_a_point_mismatch_wins_over_an_unreadable_filter(state):
    """
    **R13** 시점이 다르면 그것으로 **이미 답이 확정된다** — 필터를 읽을 수
    있는지 묻지 않는다. 그래서 확정된 거부가 모름으로 약해지지 않는다.

    .. note::
       **이 테스트의 첫 입력이 아무것도 재지 않았다** (3-E-45 의 고의 위반 4
       가 찾아냄).

       처음에는 ``CARD_DRAWN`` 사건을 썼다. 그런데 ``CardDrawn`` 은
       ``CardMovement`` 라서 ``event.operation`` 이 ``draw`` 로 **읽힌다** —
       즉 ``unreadable`` 이 애초에 비어 있어서, 시점 검사를 빼도 결과가
       같았다. 그래서 가드를 지워도 테스트가 통과했다.

       ``LIFE_CHANGED`` 사건으로 바꿨다. ``LifeChanged`` 는
       ``CardMovement`` 가 **아니므로** ``operation`` 이 ``None`` 이고, 그때
       비로소 "시점 검사가 먼저 걸러 주는가" 를 잰다.
    """
    #: ``LifeChanged`` 는 ``CardMovement`` 가 아니다 → ``operation`` 이 ``None``.
    #: 그래도 **시점이 다르므로** 답은 확정된 거부여야 한다.
    event = TimingEvent.from_delta(LifeChanged(MINE, 8000, 7000))
    assert event.operation is None
    assert event.point is not TimingPoint.CARD_MOVED

    verdict = relation(judge(state, filtered_spec(), event))
    assert (verdict.validity, verdict.code) == (
        ActionValidity.INVALID,
        ValidationCode.CANDIDATE_NOT_ELIGIBLE,
    )

    #: 같은 선언에 **값이 읽히는** 다른 시점의 사건도 확정 거부다
    #: (``CardDrawn`` 은 ``CardMovement`` 라서 ``operation`` 이 있다).
    drawn = drawn_event()
    assert drawn.operation is not None
    assert relation(judge(state, filtered_spec(), drawn)).code is (
        ValidationCode.CANDIDATE_NOT_ELIGIBLE
    )


# ======================================================================
# D. 하류 전파 — _refusal_code · _undecided_code
# ======================================================================


def test_10_refusal_code_no_longer_reports_a_missing_rule(state):
    """
    ``_refusal_code`` 는 **첫 ``INVALID`` 관문의 코드**를 올리고
    ``_event_relation`` 이 첫 관문이다. 그래서 고치기 전에는 그 함수가
    **자기 docstring 을 어기고** ``RULE_NOT_IMPLEMENTED`` 를 올렸다.
    """
    eligibility = judge(
        state,
        TriggerSpec(WATCHED, TimingPoint.LIFE_CHANGED, activates_from=HAND_OR_FIELD),
        drawn_event(),
    )
    assert _refusal_code(eligibility) is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert _refusal_code(eligibility) is not ValidationCode.RULE_NOT_IMPLEMENTED


def test_11_undecided_code_now_carries_the_missing_rule(state):
    """
    사건을 모를 때는 ``_undecided_code`` 가 그 까닭을 올린다 —
    "규칙이 없다" 가 "정보가 없다" 를 이기는 그 함수의 우선순위 그대로다.

    고치기 전에는 ``EVENT_RELATION`` 이 ``INVALID`` 였으므로 이 함수가
    그 관문을 **아예 보지 못했다.**
    """
    unimplemented = judge(
        state, drawn_spec(), TimingEvent.unimplemented("셔플을 옮길 이름이 없다")
    )
    assert _undecided_code(unimplemented) is ValidationCode.RULE_NOT_IMPLEMENTED

    unreadable = judge(state, filtered_spec(), TimingEvent(TimingPoint.CARD_MOVED))
    assert _undecided_code(unreadable) is ValidationCode.INFORMATION_UNAVAILABLE


# ======================================================================
# E. 모름 분기가 가정이 아니다
# ======================================================================


def test_12_timing_for_really_produces_unimplemented_events():
    """
    **``UNIMPLEMENTED`` 사건은 실제로 만들어진다.**

    ``timing_for`` 가 옮길 시점 이름이 없는 변화를 그 시점으로 남긴다
    (STRUCTURAL-74 · Phase 2-AJ). 등재된 실제 카드(리로드)의 해결에 셔플이
    들어 있고, ``tests/engine/test_real_card_semantics.py`` 가 그 사건이
    **네 번째 자리**에 남는 것을 이미 고정해 두었다.

    그러므로 ``test_05`` 의 분기는 가상의 입력이 아니다.
    """
    from engine.effect.delta import ZoneShuffled

    shuffled = ZoneShuffled(player=MINE, zone=Zone.DECK, size=3, draw=0)
    event = timing_for(shuffled)
    assert event.point is TimingPoint.UNIMPLEMENTED
    assert "ZoneShuffled" in event.note

    real = source_of("tests/engine/test_real_card_semantics.py")
    assert "TimingPoint.UNIMPLEMENTED,  # 셔플" in real


# ======================================================================
# F. policy 와 맞는다 · 새 어휘를 만들지 않았다
# ======================================================================


def test_13_every_pair_the_gate_can_emit_agrees_with_the_unknown_policy():
    """
    이 관문이 낼 수 있는 ``(validity, code)`` 짝 전부가 Phase 3-E-40 의
    :data:`CODE_VALIDITY` 와 **맞는다.** 어긋남이 0개인 것이 R-3 의 해소다.
    """
    pairs = set()
    for node in ast.walk(gate_function()):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_gate"
        ):
            continue
        validity, code = node.args[1], node.args[2]
        assert isinstance(validity, ast.Attribute)
        assert isinstance(code, ast.Attribute), "코드를 조건부로 적지 않았다"
        pairs.add((ActionValidity[validity.attr], ValidationCode[code.attr]))

    assert pairs == {
        (ActionValidity.VALID, ValidationCode.OK),
        (ActionValidity.INVALID, ValidationCode.CANDIDATE_NOT_ELIGIBLE),
        (ActionValidity.UNKNOWN, ValidationCode.RULE_NOT_IMPLEMENTED),
        (ActionValidity.UNKNOWN, ValidationCode.INFORMATION_UNAVAILABLE),
    }
    for declared, code in pairs:
        assert CODE_VALIDITY[code] is declared, (declared, code)


def test_14_no_validation_code_was_added_or_redefined():
    """
    **새 ``ValidationCode`` 를 만들지 않았다.** 48개 그대로이고, 쓴 코드 셋은
    전부 이 Phase **이전부터** 있던 것이다.
    """
    assert len(ValidationCode) == 48
    assert len(CODE_VALIDITY) == 48
    for name in (
        "OK",
        "CANDIDATE_NOT_ELIGIBLE",
        "RULE_NOT_IMPLEMENTED",
        "INFORMATION_UNAVAILABLE",
    ):
        assert name in ValidationCode.__members__

    #: ``CHAIN_DEFINITION_UNAVAILABLE`` 의 policy 를 건드리지 않았다.
    assert CODE_VALIDITY[ValidationCode.CHAIN_DEFINITION_UNAVAILABLE] is None


def test_15_matches_itself_was_not_touched():
    """
    **데이터 비교를 바꾸지 않았다.** ``TriggerSpec.matches`` 는 그대로이고,
    이 Phase 는 그 ``bool`` 을 **어떤 판정으로 옮기는가**만 고쳤다.
    """
    matches = next(
        node
        for node in ast.walk(ast.parse(source_of("engine/trigger.py")))
        if isinstance(node, ast.FunctionDef) and node.name == "matches"
    )
    #: ``ast.walk`` 는 **소스 순서를 보장하지 않는다** — ``lineno`` 로 정렬한다.
    returns = [
        node.value.value
        for node in sorted(
            (
                node
                for node in ast.walk(matches)
                if isinstance(node, ast.Return)
                and isinstance(node.value, ast.Constant)
            ),
            key=lambda node: node.lineno,
        )
    ]
    assert returns == [False, False, False, False, True]
    #: 판정 어휘를 끌어들이지 않았다 — 여전히 ``bool`` 하나다.
    assert "ValidationCode" not in ast.unparse(matches)
    assert "ActionValidity" not in ast.unparse(matches)


# ======================================================================
# G. 범위를 넓히지 않았다
# ======================================================================


def test_16_only_the_event_relation_gate_changed():
    """
    나머지 네 관문의 코드 집합이 **Phase 3-E-44 가 측정한 그대로**다.
    """
    tree = ast.parse(source_of("engine/trigger.py"))
    bodies = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    def codes(name):
        return {
            node.attr
            for node in ast.walk(bodies[name])
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "ValidationCode"
        }

    assert codes("_activation_zone") == {
        "RULE_NOT_IMPLEMENTED",
        "HIDDEN_CARD",
        "OK",
        "SOURCE_WRONG_ZONE",
    }
    assert codes("_trigger_condition") == {
        "RULE_NOT_IMPLEMENTED",
        "OK",
        "CANDIDATE_NOT_ELIGIBLE",
        "INFORMATION_UNAVAILABLE",
    }
    assert codes("_execution_authority") == {
        "RULE_NOT_IMPLEMENTED",
        "OK",
        "EXECUTION_FORBIDDEN",
    }
    assert codes("_cost_feasibility") == {"RULE_NOT_IMPLEMENTED", "OK"}


def test_17_the_gate_is_still_dormant_and_nothing_was_connected():
    """
    **파이프라인을 연결하지 않았다.** ``duel.py`` 는 여전히 트리거를 한 번도
    언급하지 않고, ``spec.matches`` 를 부르는 자리도 ``engine/trigger.py``
    두 곳뿐이다.
    """
    duel = source_of("engine/duel.py")
    assert "trigger" not in duel
    assert "Trigger" not in duel

    callers = []
    for path in sorted(PROJECT_ROOT.glob("engine/**/*.py")) + sorted(
        PROJECT_ROOT.glob("agent/**/*.py")
    ):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "matches"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "spec"
            ):
                callers.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert callers == ["engine/trigger.py"] * 2

    #: ``agent/`` 가 trigger 모듈을 import 하지 않는다 — AI 는 live 만 본다.
    for path in sorted(PROJECT_ROOT.glob("agent/**/*.py")):
        text = path.read_text(encoding="utf-8")
        assert "engine.trigger" not in text, path


def test_18_the_two_different_result_gates_were_left_alone():
    """
    **3-E-44 의 ``ACTIVATION_ZONE`` · ``COST_FEASIBILITY`` 를 고치지 않았다.**

    둘 다 live 와 답이 갈리는 구조적 위험으로 기록만 유지한다 — 그 결정은
    "dormant 를 연결하는가" 라는 더 큰 질문에 달려 있다.
    """
    #: 자리 관문은 여전히 선언과 대조하고 ``SOURCE_WRONG_ZONE`` 을 낸다.
    assert "ValidationCode.SOURCE_WRONG_ZONE" in source_of("engine/trigger.py")
    #: 비용 관문은 여전히 ``validate_group`` 을 부른다 (live 는 부르지 않는다).
    assert "self._costs.validate_group(" in source_of("engine/trigger.py")
    #: live 열거는 여전히 비용 있는 효과를 범위에서 뺀다.
    assert "if definition.cost.costs:" in source_of("engine/duel.py")
    #: live 는 여전히 발동의 자리를 ``INVALID`` 로 적지 않는다.
    activate = next(
        node
        for node in ast.walk(ast.parse(source_of("engine/action_validation.py")))
        if isinstance(node, ast.FunctionDef) and node.name == "_activate_effect"
    )
    assert "SOURCE_WRONG_ZONE" not in ast.unparse(activate)


def test_19_judging_changes_neither_state_hash_nor_rng(state):
    """
    고친 뒤에도 판정은 **판을 읽기만 한다.** 네 갈래를 100번 돌려도
    ``state_hash`` 와 RNG 가 한 비트도 바뀌지 않는다.
    """
    before_hash = state.state_hash()
    before_rng = state.rng.getstate()

    events = (
        drawn_event(),
        moved_event(movement=OperationKind.DESTROY),
        TimingEvent.unimplemented("셔플"),
        TimingEvent(TimingPoint.CARD_MOVED),
    )
    for _ in range(25):
        for event in events:
            judge(state, filtered_spec(), event)

    assert state.state_hash() == before_hash
    assert state.rng.getstate() == before_rng
