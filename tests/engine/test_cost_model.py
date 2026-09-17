"""
engine/cost/ — 비용과 선택의 **표현**.

청구서이지 영수증이 아니다. 이 파일은 모델이 의미를 합치지 않는지,
불변인지, 결정론적인지만 본다. 판정은 test_cost_validation.py 가 본다.
"""

import dataclasses
import json

import pytest

from engine.condition import AttributeIs, LevelAtLeast, PlayerRef
from engine.cost import (
    CandidateSet,
    CandidateSource,
    CardCost,
    ChoiceSpec,
    CostGroup,
    CostSemantics,
    LifeCost,
    Selection,
    UnimplementedCost,
)
from engine.ids import InstanceId
from engine.vocabulary import Zone


# ----------------------------------------------------------------------
# 1~4. 비용 구조
# ----------------------------------------------------------------------


def test_a_release_cost_names_what_it_takes():
    cost = CardCost.release(1)
    assert cost.semantics is CostSemantics.RELEASE
    assert cost.count == 1
    assert cost.upper_bound == 1
    assert cost.zones == frozenset({Zone.MZONE, Zone.EMZONE})
    assert cost.who is PlayerRef.CONTROLLER


def test_a_cost_can_take_several_cards():
    cost = CardCost.release(2)
    spec = cost.choice_spec()
    assert spec.minimum == 2
    assert spec.maximum == 2
    assert spec.is_exact


def test_a_cost_can_have_a_range():
    """'1장 이상 3장까지' 처럼 수량에 폭이 있는 비용."""
    cost = CardCost.discard(1, maximum=3)
    spec = cost.choice_spec()
    assert (spec.minimum, spec.maximum) == (1, 3)
    assert not spec.is_exact
    assert not spec.is_optional


def test_a_cost_can_be_optional():
    spec = CardCost.discard(0, maximum=2).choice_spec()
    assert spec.is_optional
    assert spec.maximum == 2


def test_a_cost_can_require_a_card_property():
    """'어둠 속성 몬스터 1장' 처럼 후보에 조건이 붙는다."""
    cost = CardCost.release(1, require=AttributeIs("DARK"))
    assert cost.require is not None
    assert cost.choice_spec().source.require is cost.require


def test_life_cost_states_an_amount():
    cost = LifeCost(1000)
    assert cost.semantics is CostSemantics.PAY_LIFE
    assert cost.amount == 1000
    assert cost.choice_spec() is None  # 고를 것이 없다


def test_life_cost_refuses_a_meaningless_amount():
    with pytest.raises(ValueError):
        LifeCost(0)
    with pytest.raises(ValueError):
        LifeCost(-500)


def test_a_cost_group_holds_several_costs():
    """'라이프 1000 지불 그리고 몬스터 1장 릴리스'."""
    group = CostGroup((LifeCost(1000), CardCost.release(1)))
    assert len(group) == 2
    assert not group.is_free
    assert "그리고" in group.describe_ko()
    # 고를 것이 있는 비용만 선택 명세를 낸다.
    assert len(group.choice_specs()) == 1


def test_an_empty_cost_group_is_free():
    group = CostGroup()
    assert group.is_free
    assert group.choice_specs() == ()


def test_unimplemented_cost_says_what_is_missing():
    cost = UnimplementedCost("xyz material detach (Phase 2-D)")
    assert cost.semantics is CostSemantics.UNKNOWN
    assert cost.choice_spec() is None
    assert "xyz material" in cost.describe_ko()


# ----------------------------------------------------------------------
# 8. 의미를 합치지 않는다
# ----------------------------------------------------------------------


def test_release_and_send_to_grave_are_different_costs():
    """
    둘 다 결국 묘지로 가지만 **다른 사건**이다. "릴리스되었을 때" 트리거는
    묘지로 보내진 몬스터로 발동하지 않는다.
    """
    release = CardCost.release(1)
    send = CardCost.send_to_grave(frozenset({Zone.MZONE, Zone.EMZONE}), 1)

    assert release.semantics is not send.semantics
    assert release.semantics is CostSemantics.RELEASE
    assert send.semantics is CostSemantics.SEND_TO_GRAVE
    assert release.canonical_state() != send.canonical_state()
    assert release != send


def test_discard_and_send_to_grave_are_different_costs():
    discard = CardCost.discard(1)
    send = CardCost.send_to_grave(frozenset({Zone.HAND}), 1)
    assert discard.semantics is not send.semantics
    assert discard.canonical_state() != send.canonical_state()


def test_destroy_is_not_a_cost():
    """
    유희왕에서 카드를 파괴하는 것은 **효과의 결과**이지 발동 비용이 아니다.
    ``analysis.CostKind`` 에도 없다. 여기에 넣으면 ADR-002 의
    ``Destroy ≠ Send to Graveyard`` 가 비용 쪽에서 무너진다.
    """
    names = {member.value for member in CostSemantics}
    assert "destroy" not in names

    from analysis.effect_model import CostKind

    assert "destroy" not in {member.value for member in CostKind}


def test_engine_cost_semantics_is_not_the_analysis_vocabulary():
    """
    ``analysis.CostKind`` 는 Lua 비용 함수를 읽은 **기록**이다. 두 어휘를
    합치면 "스크립트에 무엇이 적혀 있는가" 와 "지금 치를 수 있는가" 가 섞인다.
    """
    from analysis.effect_model import CostKind

    assert CostSemantics is not CostKind
    assert CostSemantics.RELEASE is not CostKind.RELEASE


def test_the_cost_package_borrows_nothing_from_analysis():
    import ast
    import pathlib

    offenders: list[str] = []
    for path in sorted(pathlib.Path("engine/cost").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[
                0
            ] in {"analysis", "core"}:
                offenders.append(f"{path}: {node.module}")
    assert offenders == [], f"비용 계층이 {offenders} 를 가져옵니다."


def test_life_cost_cannot_be_expressed_as_a_card_cost():
    with pytest.raises(ValueError):
        CardCost(kind=CostSemantics.PAY_LIFE, zones=frozenset({Zone.HAND}))


# ----------------------------------------------------------------------
# 7. 후보와 선택은 다른 것이다
# ----------------------------------------------------------------------


def test_a_candidate_set_is_not_a_selection():
    candidates = CandidateSet(eligible=(InstanceId(3), InstanceId(7), InstanceId(9)))
    selection = Selection.of(InstanceId(7))

    assert type(candidates) is not type(selection)
    assert candidates.certain_count == 3
    assert len(selection) == 1
    assert candidates.contains(InstanceId(7))
    assert not candidates.contains(InstanceId(4))


def test_a_candidate_set_keeps_undecided_apart_from_eligible():
    """
    미확정을 확정에 넣으면 못 치를 비용을 치를 수 있다고 하게 되고,
    버리면 치를 수 있는 비용을 못 치른다고 하게 된다.
    """
    candidates = CandidateSet(
        eligible=(InstanceId(1),),
        undecided=(InstanceId(2), InstanceId(3)),
        reasons=("#2: 뒷면", "#3: 뒷면"),
    )
    assert candidates.certain_count == 1
    assert candidates.possible_count == 3
    assert candidates.has_undecided
    assert not candidates.contains(InstanceId(2))
    assert len(candidates) == 1  # __len__ 은 확실한 후보만 센다


def test_a_card_cannot_be_both_decided_and_undecided():
    with pytest.raises(ValueError):
        CandidateSet(eligible=(InstanceId(1),), undecided=(InstanceId(1),))


def test_selection_keeps_the_order_it_was_given():
    a, b = InstanceId(5), InstanceId(2)
    assert Selection.of(a, b).chosen == (a, b)
    assert Selection.of(a, b) != Selection.of(b, a)


def test_selection_notices_duplicates():
    assert Selection.of(InstanceId(1), InstanceId(1)).has_duplicates
    assert not Selection.of(InstanceId(1), InstanceId(2)).has_duplicates


# ----------------------------------------------------------------------
# 11~12. ChoiceSpec
# ----------------------------------------------------------------------


def test_choice_spec_describes_what_to_pick():
    spec = ChoiceSpec(
        source=CandidateSource(zones=frozenset({Zone.MZONE}), owner=PlayerRef.CONTROLLER),
        minimum=1,
        maximum=1,
    )
    assert spec.is_exact
    assert not spec.is_optional
    assert spec.chooser is PlayerRef.CONTROLLER


def test_choice_spec_refuses_an_impossible_range():
    source = CandidateSource(zones=frozenset({Zone.MZONE}))
    with pytest.raises(ValueError):
        ChoiceSpec(source=source, minimum=2, maximum=1)
    with pytest.raises(ValueError):
        ChoiceSpec(source=source, minimum=-1, maximum=1)


def test_a_candidate_source_needs_at_least_one_zone():
    with pytest.raises(ValueError):
        CandidateSource(zones=frozenset())
    with pytest.raises(TypeError):
        CandidateSource(zones={Zone.MZONE})  # type: ignore[arg-type]


def test_a_candidate_source_can_span_both_players():
    source = CandidateSource(zones=frozenset({Zone.MZONE}), owner=None)
    assert source.owner is None
    assert "양쪽" in source.describe_ko()


# ----------------------------------------------------------------------
# 불변성
# ----------------------------------------------------------------------


def test_every_model_is_immutable():
    for value in (
        CardCost.release(1),
        LifeCost(1000),
        UnimplementedCost("x"),
        CostGroup((LifeCost(500),)),
        ChoiceSpec(source=CandidateSource(zones=frozenset({Zone.MZONE}))),
        CandidateSet(eligible=(InstanceId(1),)),
        Selection.of(InstanceId(1)),
    ):
        field_name = next(f.name for f in dataclasses.fields(value))
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, field_name, None)


def test_collections_are_tuples_not_lists():
    with pytest.raises(TypeError):
        CostGroup([LifeCost(500)])  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        CandidateSet(eligible=[InstanceId(1)])  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Selection(chosen=[InstanceId(1)])  # type: ignore[arg-type]

    candidates = CandidateSet(eligible=(InstanceId(1),))
    with pytest.raises(AttributeError):
        candidates.eligible.append(InstanceId(2))


def test_a_cost_refuses_a_mutable_zone_set():
    with pytest.raises(TypeError):
        CardCost(kind=CostSemantics.RELEASE, zones={Zone.MZONE})  # type: ignore[arg-type]


def test_a_cost_refuses_an_impossible_amount():
    with pytest.raises(ValueError):
        CardCost.release(-1)
    with pytest.raises(ValueError):
        CardCost.release(3, maximum=1)
    with pytest.raises(ValueError):
        CardCost(kind=CostSemantics.RELEASE, zones=frozenset())


# ----------------------------------------------------------------------
# 결정론
# ----------------------------------------------------------------------


def test_identical_costs_have_identical_representations():
    a = CardCost.release(2, require=LevelAtLeast(4))
    b = CardCost.release(2, require=LevelAtLeast(4))
    assert a == b
    assert a.canonical_state() == b.canonical_state()
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(
        b.to_dict(), sort_keys=True
    )


def test_different_costs_have_different_representations():
    base = CardCost.release(1)
    assert base.canonical_state() != CardCost.release(2).canonical_state()
    assert (
        base.canonical_state()
        != CardCost.release(1, who=PlayerRef.OPPONENT).canonical_state()
    )
    assert (
        base.canonical_state()
        != CardCost.release(1, require=LevelAtLeast(4)).canonical_state()
    )


def test_zone_sets_serialize_in_a_stable_order():
    """집합은 순회 순서가 보장되지 않는다. 정렬해서 내보낸다."""
    zones = frozenset({Zone.GRAVE, Zone.HAND, Zone.MZONE})
    a = CardCost.banish(zones)
    for _ in range(10):
        assert a.canonical_state() == CardCost.banish(zones).canonical_state()
    assert a.to_dict()["zones"] == sorted(a.to_dict()["zones"])


def test_representations_hold_only_value_types():
    group = CostGroup(
        (
            LifeCost(1000),
            CardCost.release(1, require=AttributeIs("DARK")),
            UnimplementedCost("counter removal"),
        )
    )

    def leaves(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from leaves(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from leaves(item)
        else:
            yield value

    for value in leaves(group.canonical_state()):
        assert value is None or isinstance(value, (int, str, bool)), value
    for value in leaves(group.to_dict()):
        assert value is None or isinstance(value, (int, str, bool)), value
    text = json.dumps(group.to_dict(), ensure_ascii=False)
    assert "0x" not in text and "object at" not in text


def test_representation_is_stable_across_processes():
    import pathlib
    import subprocess
    import sys

    snippet = (
        "import json;"
        "from engine.cost import CardCost, CostGroup, LifeCost;"
        "from engine.condition import AttributeIs;"
        "g = CostGroup((LifeCost(1000), CardCost.release(2, require=AttributeIs('DARK'))));"
        "print(json.dumps(g.canonical_state()))"
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
