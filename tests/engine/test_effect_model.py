"""
engine/effect/ — 효과 정의 · 하는 일 · 대상 규칙.

**아무것도 실행하지 않는다.** 이 파일은 모델이 의미를 합치지 않는지,
불변인지, 결정론적인지를 본다. 해결 계약은 test_effect_resolution.py.
"""

import dataclasses
import json

import pytest

from engine.condition import AttributeIs, LevelAtLeast, PlayerRef
from engine.cost import CandidateSource, CardCost, ChoiceSpec, CostGroup, LifeCost, Selection
from engine.effect import (
    PRIMARY_TARGET,
    CardOperation,
    DrawOperation,
    EffectDefinition,
    EffectDefinitionError,
    EffectProvenance,
    EffectSource,
    EmptyImplementationLookup,
    ExecutionAvailability,
    LifeChangeOperation,
    Operation,
    OperationKind,
    TargetBinding,
    TargetRef,
    TargetRequirement,
    TargetSpec,
    UnimplementedOperation,
    execution_availability,
)
from engine.ids import EffectRef, InstanceId
from engine.vocabulary import Zone, default_vocabulary

KUKLOK = 2511


def monsters(owner: PlayerRef = PlayerRef.CONTROLLER) -> ChoiceSpec:
    return ChoiceSpec(
        source=CandidateSource(zones=frozenset({Zone.MZONE, Zone.EMZONE}), owner=owner)
    )


def one_target(owner: PlayerRef = PlayerRef.CONTROLLER) -> tuple[TargetBinding, ...]:
    """대상 하나를 ``@primary`` 라는 이름으로 선언한다."""
    return TargetBinding.single(TargetSpec.targeting(monsters(owner)))


# ======================================================================
# 1~4. EffectRef identity
# ======================================================================


def test_effect_ref_is_the_identity():
    definition = EffectDefinition(EffectRef(KUKLOK, 2), KUKLOK)
    assert definition.effect_ref == EffectRef(KUKLOK, 2)
    assert definition.ordinal == 2


def test_a_definition_refuses_a_mismatched_source_card():
    """한 효과는 한 카드의 것이다. 어긋나면 스스로 모순인 정의다."""
    with pytest.raises(EffectDefinitionError) as excinfo:
        EffectDefinition(EffectRef(KUKLOK, 0), 9999)
    assert "다릅니다" in str(excinfo.value)


def test_ordinal_not_the_lua_variable_name_is_the_identity():
    """
    ``EffectSpec.index`` 는 Lua 변수명(``"e1"``)이고 한 카드 안에서 중복된다
    (실측 4,884장). 정의는 그것을 쓰지 않는다.
    """
    definition = EffectDefinition(EffectRef(KUKLOK, 1), KUKLOK)
    fields = {f.name for f in dataclasses.fields(definition)}
    assert "index" not in fields

    text = json.dumps(definition.to_dict(), ensure_ascii=False)
    assert "e1" not in text
    assert definition.to_dict()["effect_ref"] == {"card_id": KUKLOK, "ordinal": 1}


def test_two_effects_of_one_card_are_different_definitions():
    a = EffectDefinition(EffectRef(KUKLOK, 0), KUKLOK)
    b = EffectDefinition(EffectRef(KUKLOK, 1), KUKLOK)
    assert a != b
    assert a.canonical_state() != b.canonical_state()


def test_the_engine_effect_model_is_not_the_analysis_one():
    """
    ``core.card_model.EffectSpec`` 은 Lua 를 읽은 **기록**이다 — 가변이고
    ``index`` 가 변수명이다. 실행 계약과 합치면 "스크립트에 무엇이 적혀
    있는가" 와 "무엇을 실행하는가" 가 섞인다.
    """
    from core.card_model import EffectSpec

    assert EffectDefinition is not EffectSpec
    spec = EffectSpec(index="e1")
    spec.index = "e2"  # 가변이다
    assert spec.index == "e2"

    definition = EffectDefinition(EffectRef(KUKLOK, 0), KUKLOK)
    with pytest.raises(dataclasses.FrozenInstanceError):
        definition.source_card_id = 1


def test_the_effect_package_borrows_nothing_from_analysis_or_core():
    import ast
    import pathlib

    offenders: list[str] = []
    for path in sorted(pathlib.Path("engine/effect").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[
                0
            ] in {"analysis", "core"}:
                offenders.append(f"{path}: {node.module}")
    assert offenders == [], f"효과 계층이 {offenders} 를 가져옵니다."


def test_the_effect_package_does_not_depend_on_player_actions():
    """
    ``Effect`` 와 ``PlayerAction`` 은 다른 개념이고, 의존 방향도 한쪽이다.
    효과가 Action 을 가져오면 Phase 2-D-2 에서 순환이 생긴다.
    """
    import ast
    import pathlib

    offenders: list[str] = []
    for path in sorted(pathlib.Path("engine/effect").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "engine.action"
            ):
                offenders.append(f"{path}: {node.module}")
    assert offenders == [], f"효과 계층이 Action 을 가져옵니다: {offenders}"


# ======================================================================
# 12~14. Operation 의 의미는 합쳐지지 않는다
# ======================================================================


def test_destroy_and_send_to_grave_are_different_operations():
    """
    둘 다 묘지로 간다. **목적지로는 절대 구분할 수 없다.** 구분은
    ``REASON_DESTROY`` 비트 하나다 (ADR-002).
    """
    destroy = CardOperation.destroy(PRIMARY_TARGET)
    send = CardOperation.send_to_grave(PRIMARY_TARGET)

    assert destroy.kind is not send.kind
    assert destroy.canonical_state() != send.canonical_state()
    assert destroy != send
    assert "DESTROY" in destroy.reason_names
    assert "DESTROY" not in send.reason_names


def test_release_is_neither_destroy_nor_send_to_grave():
    release = CardOperation.release(PRIMARY_TARGET)
    destroy = CardOperation.destroy(PRIMARY_TARGET)
    send = CardOperation.send_to_grave(PRIMARY_TARGET)

    assert release.kind is not destroy.kind
    assert release.kind is not send.kind
    assert release.reason_names == ("RELEASE",)
    assert "DESTROY" not in release.reason_names
    assert "EFFECT" not in release.reason_names


def test_banish_and_send_to_grave_are_different_operations():
    banish = CardOperation.banish(PRIMARY_TARGET)
    send = CardOperation.send_to_grave(PRIMARY_TARGET)
    assert banish.kind is not send.kind
    assert banish.canonical_state() != send.canonical_state()


def test_the_reason_bits_actually_separate_them():
    """
    이름이 아니라 실제 비트값으로도 달라야 한다. 값은 ``constant.lua``
    에서 읽는다 — 여기에 숫자를 적어 두지 않는다.
    """
    vocabulary = default_vocabulary()
    destroy = CardOperation.destroy(PRIMARY_TARGET).reason_mask(vocabulary)
    send = CardOperation.send_to_grave(PRIMARY_TARGET).reason_mask(vocabulary)
    release = CardOperation.release(PRIMARY_TARGET).reason_mask(vocabulary)

    assert destroy != send != release
    assert destroy != release
    destroy_bit = vocabulary.reasons.value("DESTROY")
    assert destroy & destroy_bit
    assert not send & destroy_bit
    assert not release & destroy_bit


def test_an_unknown_reason_name_is_refused_rather_than_silently_zero():
    """0 으로 접으면 '이유 없음' 과 '이름을 못 읽음' 이 같아진다."""

    @dataclasses.dataclass(frozen=True, slots=True)
    class Bogus(Operation):
        @property
        def kind(self):
            return OperationKind.DESTROY

        @property
        def reason_names(self):
            return ("NO_SUCH_REASON",)

    with pytest.raises(KeyError):
        Bogus().reason_mask()


def test_operations_do_not_become_player_actions():
    """
    ``DestroyOperation`` 에 대응하는 ``PlayerActionKind.DESTROY`` 는 없다
    (ADR-001 · ADR-002). 있으면 AI 가 "파괴한다" 를 직접 고르게 된다.
    """
    from engine.action import PlayerActionKind

    action_names = {member.value for member in PlayerActionKind}
    for operation in ("destroy", "banish", "send_to_grave", "release", "discard"):
        assert operation not in action_names


def test_operation_vocabulary_is_not_the_analysis_one():
    from analysis.effect_model import ACTION_DESTINATION, ActionKind

    assert OperationKind is not ActionKind
    # analysis 는 파괴와 묘지送り를 같은 목적지로 합친다 — 그래서 못 쓴다.
    assert (
        ACTION_DESTINATION[ActionKind.DESTROY]
        == ACTION_DESTINATION[ActionKind.TO_GRAVE]
    )
    assert (
        CardOperation.destroy(PRIMARY_TARGET).reason_names
        != CardOperation.send_to_grave(PRIMARY_TARGET).reason_names
    )


def test_a_non_card_kind_cannot_be_a_card_operation():
    with pytest.raises(ValueError):
        CardOperation(OperationKind.DRAW, PRIMARY_TARGET)


def test_draw_and_life_operations():
    draw = DrawOperation(2)
    assert draw.kind is OperationKind.DRAW
    assert draw.count == 2

    loss = LifeChangeOperation(-1000, PlayerRef.OPPONENT)
    assert loss.is_loss
    gain = LifeChangeOperation(500)
    assert not gain.is_loss
    assert loss.canonical_state() != gain.canonical_state()


def test_meaningless_amounts_are_refused():
    with pytest.raises(ValueError):
        DrawOperation(0)
    with pytest.raises(ValueError):
        LifeChangeOperation(0)


def test_an_unimplementable_operation_says_so():
    operation = UnimplementedOperation("special summon (Phase 2-G)")
    assert operation.kind is OperationKind.UNKNOWN
    assert operation.reason_names == ()
    assert "special summon" in operation.describe_ko()


# ======================================================================
# 16~18. TargetSpec
# ======================================================================


def test_no_target_and_target_required_are_different_states():
    """
    **§11 의 구분.** "대상이 없어도 되는 효과" 와 "대상을 빠뜨린 효과" 를
    같은 상태로 만들면 안 된다.
    """
    none = TargetSpec.none()
    required = TargetSpec.targeting(monsters())

    assert none.requirement is TargetRequirement.NONE
    assert not none.requires_selection
    assert required.requires_selection

    # 대상을 요구하지 않는 효과는 **기다리지 않는다.**
    assert not none.is_pending(None)
    assert not none.is_pending(Selection())
    # 요구하는데 안 골랐으면 기다리는 중이다.
    assert required.is_pending(None)
    assert required.is_pending(Selection())
    assert not required.is_pending(Selection.of(InstanceId(1)))


def test_targeting_and_choosing_are_different_rules():
    """
    유희왕에서 "대상으로 한다" 와 "고른다" 는 다른 규칙이다. 대상 지정만
    발동 시점에 확정되고 무효화·회피의 대상이 된다.
    """
    targeting = TargetSpec.targeting(monsters())
    choosing = TargetSpec.choosing(monsters())

    assert targeting.is_targeting
    assert not choosing.is_targeting
    assert targeting.requires_selection and choosing.requires_selection
    assert targeting.canonical_state() != choosing.canonical_state()
    assert "대상으로 지정" in targeting.describe_ko()
    assert "선택" in choosing.describe_ko()


def test_a_contradictory_target_spec_is_refused():
    with pytest.raises(ValueError):
        TargetSpec(requirement=TargetRequirement.NONE, choice=monsters())
    with pytest.raises(ValueError):
        TargetSpec(requirement=TargetRequirement.TARGETING, choice=None)


def test_target_spec_holds_stable_identity_only():
    """``ChoiceSpec`` 은 존과 조건만 담는다. 카드 객체를 담지 않는다."""
    spec = TargetSpec.targeting(
        ChoiceSpec(
            source=CandidateSource(
                zones=frozenset({Zone.MZONE}), require=AttributeIs("DARK")
            )
        )
    )
    text = json.dumps(spec.to_dict(), ensure_ascii=False)
    assert "0x" not in text and "object at" not in text


# ======================================================================
# 5~11. EffectDefinition
# ======================================================================


def test_a_definition_links_cost_condition_target_and_operations():
    """
    "상대 몬스터 1장을 대상으로 지정하고, **그것을** 파괴한 뒤 1장 드로우."
    하는 일이 어느 대상을 쓰는지 이름으로 이어진다.
    """
    definition = EffectDefinition(
        effect_ref=EffectRef(KUKLOK, 0),
        source_card_id=KUKLOK,
        activation=LevelAtLeast(4),
        cost=CostGroup((LifeCost(1000), CardCost.release(1))),
        targets=one_target(PlayerRef.OPPONENT),
        operations=(CardOperation.destroy(PRIMARY_TARGET), DrawOperation(1)),
        provenance=EffectProvenance.official_lua(),
    )

    assert definition.has_cost
    assert definition.requires_target
    assert definition.is_described
    assert definition.activation is not None
    assert len(definition.operations) == 2
    assert definition.provenance.source is EffectSource.OFFICIAL_LUA

    # 파괴가 가리키는 이름이 정의가 선언한 규칙으로 이어진다.
    destroy = definition.operations[0]
    assert destroy.target_refs == (PRIMARY_TARGET,)
    assert definition.target_spec(PRIMARY_TARGET).is_targeting
    # 드로우는 대상이 없다.
    assert definition.operations[1].target_refs == ()


def test_an_empty_definition_does_not_claim_the_effect_does_nothing():
    """
    ``operations`` 가 비었다는 것은 **효과가 없다는 뜻이 아니라** 아직
    적지 않았다는 뜻이다. ``activation=None`` 도 마찬가지다.
    """
    definition = EffectDefinition(EffectRef(KUKLOK, 0), KUKLOK)
    assert not definition.is_described
    assert definition.activation is None
    assert definition.cost.is_free
    assert not definition.requires_target


def test_definitions_are_immutable():
    definition = EffectDefinition(EffectRef(KUKLOK, 0), KUKLOK)
    for name in ("effect_ref", "source_card_id", "operations", "cost", "targets"):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(definition, name, None)
    with pytest.raises(TypeError):
        EffectDefinition(EffectRef(KUKLOK, 0), KUKLOK, operations=[DrawOperation(1)])
    with pytest.raises(AttributeError):
        definition.operations.append(DrawOperation(1))


def test_every_model_piece_is_immutable():
    for value in (
        CardOperation.destroy(PRIMARY_TARGET),
        TargetBinding(PRIMARY_TARGET, TargetSpec.targeting(monsters())),
        DrawOperation(1),
        LifeChangeOperation(-100),
        UnimplementedOperation("x"),
        TargetSpec.none(),
        EffectProvenance.official_lua(),
    ):
        field_name = next(
            (f.name for f in dataclasses.fields(value)), None
        )
        if field_name is None:
            continue
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, field_name, None)


# ======================================================================
# 22~24. 실행 권위
# ======================================================================


def test_text_derived_is_never_executable():
    """
    ADR-004. 구현이 등록되어 있어도 실행하지 않는다 — 출처 금지가 가장
    먼저 걸린다.
    """
    definition = EffectDefinition(
        EffectRef(KUKLOK, 0), KUKLOK, provenance=EffectProvenance.text_derived()
    )
    assert definition.provenance.verified  # 의미는 공식 텍스트에서 왔지만
    assert definition.provenance.is_forbidden  # 실행 근거는 아니다

    class Everything:
        def has_implementation(self, effect_ref):
            return True

    availability = execution_availability(definition, Everything())
    assert availability is ExecutionAvailability.FORBIDDEN_SOURCE
    assert not availability.permits_execution


def test_verified_semantics_is_not_execution_availability():
    """
    **ADR-006 의 핵심.** 공식 스크립트에서 나온 효과라도 구현이 등록되어
    있지 않으면 실행할 수 없다.
    """
    definition = EffectDefinition(
        EffectRef(KUKLOK, 0), KUKLOK, provenance=EffectProvenance.official_lua()
    )
    assert definition.provenance.verified is True

    availability = execution_availability(definition)
    assert availability is ExecutionAvailability.NO_IMPLEMENTATION
    assert not availability.permits_execution


def test_nothing_is_executable_with_the_current_engine():
    """
    등록된 구현이 하나도 없다는 것이 지금의 사실이다. 기본 조회기가
    그것을 표현한다.
    """
    lookup = EmptyImplementationLookup()
    for provenance in (
        EffectProvenance.official_lua(),
        EffectProvenance.text_derived(),
        EffectProvenance.hand_written(verified=True),
        EffectProvenance(),
    ):
        definition = EffectDefinition(
            EffectRef(KUKLOK, 0), KUKLOK, provenance=provenance
        )
        assert not execution_availability(definition, lookup).permits_execution


def test_unverified_semantics_is_not_executable():
    definition = EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        provenance=EffectProvenance.hand_written(verified=False),
    )
    assert execution_availability(definition) is ExecutionAvailability.UNVERIFIED


def test_only_executable_permits_execution():
    """``is not FORBIDDEN`` 으로 나머지가 허가로 새는 것을 막는다."""
    permitted = [a for a in ExecutionAvailability if a.permits_execution]
    assert permitted == [ExecutionAvailability.EXECUTABLE]


def test_a_registered_implementation_makes_a_verified_effect_executable():
    """경계가 한쪽으로만 막혀 있지 않은지 확인한다."""

    class Registry:
        def has_implementation(self, effect_ref):
            return effect_ref == EffectRef(KUKLOK, 0)

    definition = EffectDefinition(
        EffectRef(KUKLOK, 0), KUKLOK, provenance=EffectProvenance.official_lua()
    )
    assert execution_availability(definition, Registry()) is (
        ExecutionAvailability.EXECUTABLE
    )

    other = EffectDefinition(
        EffectRef(KUKLOK, 1), KUKLOK, provenance=EffectProvenance.official_lua()
    )
    assert execution_availability(other, Registry()) is (
        ExecutionAvailability.NO_IMPLEMENTATION
    )


# ======================================================================
# 28~29. 결정론
# ======================================================================


def _definition() -> EffectDefinition:
    return EffectDefinition(
        effect_ref=EffectRef(KUKLOK, 1),
        source_card_id=KUKLOK,
        activation=AttributeIs("DARK"),
        cost=CostGroup((LifeCost(800), CardCost.discard(1))),
        targets=one_target(PlayerRef.OPPONENT),
        operations=(CardOperation.destroy(PRIMARY_TARGET),),
        provenance=EffectProvenance.official_lua("테스트"),
    )


def test_identical_definitions_have_identical_representations():
    a, b = _definition(), _definition()
    assert a == b
    assert a.canonical_state() == b.canonical_state()
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(
        b.to_dict(), sort_keys=True
    )


def test_representations_hold_only_value_types():
    definition = _definition()

    def leaves(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from leaves(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from leaves(item)
        else:
            yield value

    for value in leaves(definition.canonical_state()):
        assert value is None or isinstance(value, (int, str, bool)), value
    for value in leaves(definition.to_dict()):
        assert value is None or isinstance(value, (int, str, bool)), value
    text = json.dumps(definition.to_dict(), ensure_ascii=False)
    assert "0x" not in text and "object at" not in text


def test_representation_is_stable_across_processes():
    import pathlib
    import subprocess
    import sys

    snippet = (
        "import json;"
        "from engine.effect import (PRIMARY_TARGET, CardOperation, "
        "EffectDefinition, EffectProvenance, TargetBinding, TargetSpec);"
        "from engine.cost import CandidateSource, ChoiceSpec, CostGroup, LifeCost;"
        "from engine.ids import EffectRef;"
        "from engine.vocabulary import Zone;"
        "spec = ChoiceSpec(source=CandidateSource(zones=frozenset({Zone.MZONE})));"
        "d = EffectDefinition(EffectRef(2511, 1), 2511,"
        " targets=TargetBinding.single(TargetSpec.targeting(spec)),"
        " operations=(CardOperation.destroy(PRIMARY_TARGET),),"
        " cost=CostGroup((LifeCost(800),)),"
        " provenance=EffectProvenance.official_lua());"
        "print(json.dumps(d.canonical_state()))"
    )
    outputs = set()
    for seed in ("0", "12345"):
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
            cwd=str(pathlib.Path(__file__).resolve().parents[2]),
        )
        assert result.returncode == 0, result.stderr
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1


def test_operation_order_is_part_of_the_definition():
    """효과가 하는 일의 순서는 의미를 갖는다. 정렬하지 않는다."""
    draw, destroy = DrawOperation(1), CardOperation.destroy(PRIMARY_TARGET)
    a = EffectDefinition(
        EffectRef(KUKLOK, 0), KUKLOK, targets=one_target(), operations=(draw, destroy)
    )
    b = EffectDefinition(
        EffectRef(KUKLOK, 0), KUKLOK, targets=one_target(), operations=(destroy, draw)
    )
    assert a.canonical_state() != b.canonical_state()
