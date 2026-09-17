"""
engine/effect/ — 하는 일과 대상의 **연결**.

Phase 2-D-1 은 ``TargetSpec`` 과 ``operations`` 를 따로 두어서
"대상으로 지정한 몬스터 1장을 파괴한다" 를 표현할 수 없었다. 대상에 이름을
붙이고 하는 일이 그 이름을 가리키게 해서 잇는다.

    targets    = (TargetBinding(PRIMARY_TARGET, TargetSpec.targeting(...)),)
    operations = (CardOperation.destroy(PRIMARY_TARGET),)
    selections = (TargetSelection(PRIMARY_TARGET, Selection.of(#7)),)   ← 문맥

정의는 **무엇을 대상으로 하는가**, 문맥은 **이번에 무엇이 골라졌는가** 다.
"""

import dataclasses
import json

import pytest

from engine.condition import PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.effect import (
    PRIMARY_TARGET,
    CardOperation,
    DrawOperation,
    EffectDefinition,
    EffectDefinitionError,
    EffectProvenance,
    ExecutionAvailability,
    LifeChangeOperation,
    OperationKind,
    ResolutionContext,
    ResolutionStatus,
    TargetBinding,
    TargetRef,
    TargetSelection,
    TargetSpec,
    UnimplementedOperation,
    UnimplementedResolver,
    execution_availability,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.vocabulary import Position, Zone

KUKLOK = 2511
SECOND = TargetRef("second")


def monsters(owner: PlayerRef = PlayerRef.CONTROLLER) -> ChoiceSpec:
    return ChoiceSpec(
        source=CandidateSource(zones=frozenset({Zone.MZONE, Zone.EMZONE}), owner=owner)
    )


def targeting(owner: PlayerRef = PlayerRef.CONTROLLER) -> TargetSpec:
    return TargetSpec.targeting(monsters(owner))


@pytest.fixture
def state() -> GameState:
    game = GameState.create(decks=(list(range(1000, 1040)), list(range(2000, 2040))))
    game.draw(0, 5)
    game.draw(1, 5)
    game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.move(game.player(1).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    return game


# ======================================================================
# 1~2. 이름으로 잇는다
# ======================================================================


def test_a_card_operation_names_the_target_it_uses():
    destroy = CardOperation.destroy(PRIMARY_TARGET)
    assert destroy.target_ref == PRIMARY_TARGET
    assert destroy.target_refs == (PRIMARY_TARGET,)


def test_the_name_resolves_to_the_declared_rule():
    """
    "상대 몬스터 1장을 대상으로 지정하고 **그것을** 파괴한다."
    """
    definition = EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        targets=TargetBinding.single(targeting(PlayerRef.OPPONENT)),
        operations=(CardOperation.destroy(PRIMARY_TARGET),),
    )
    destroy = definition.operations[0]
    spec = definition.target_spec(destroy.target_ref)

    assert spec.is_targeting
    assert spec.choice is not None
    assert spec.choice.source.owner is PlayerRef.OPPONENT
    assert definition.target_refs == (PRIMARY_TARGET,)


def test_several_operations_can_share_one_target():
    """"대상 몬스터를 파괴하고, 그 후 1장 드로우" 같은 형태."""
    definition = EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        targets=TargetBinding.single(targeting()),
        operations=(CardOperation.destroy(PRIMARY_TARGET), DrawOperation(1)),
    )
    assert definition.operations[0].target_refs == (PRIMARY_TARGET,)
    assert definition.operations[1].target_refs == ()


def test_an_effect_can_declare_two_different_targets():
    definition = EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        targets=(
            TargetBinding(PRIMARY_TARGET, targeting(PlayerRef.OPPONENT)),
            TargetBinding(SECOND, targeting(PlayerRef.CONTROLLER)),
        ),
        operations=(
            CardOperation.destroy(PRIMARY_TARGET),
            CardOperation.return_to_hand(SECOND),
        ),
    )
    assert definition.target_refs == (PRIMARY_TARGET, SECOND)
    assert (
        definition.target_spec(PRIMARY_TARGET).choice.source.owner
        is PlayerRef.OPPONENT
    )
    assert (
        definition.target_spec(SECOND).choice.source.owner is PlayerRef.CONTROLLER
    )


def test_asking_for_an_undeclared_name_raises():
    """조용히 ``None`` 을 돌려주지 않는다 — 정의와 해결이 어긋났다는 뜻이다."""
    definition = EffectDefinition(EffectRef(KUKLOK, 0), KUKLOK)
    with pytest.raises(KeyError):
        definition.target_spec(PRIMARY_TARGET)


# ======================================================================
# 3~4. 잘못된 연결은 거부한다
# ======================================================================


def test_an_operation_pointing_at_an_undeclared_name_is_refused():
    with pytest.raises(EffectDefinitionError) as excinfo:
        EffectDefinition(
            EffectRef(KUKLOK, 0),
            KUKLOK,
            targets=TargetBinding.single(targeting()),
            operations=(CardOperation.destroy(SECOND),),
        )
    assert "선언되지 않은 대상" in str(excinfo.value)


def test_an_operation_with_no_declared_targets_at_all_is_refused():
    with pytest.raises(EffectDefinitionError):
        EffectDefinition(
            EffectRef(KUKLOK, 0),
            KUKLOK,
            operations=(CardOperation.destroy(PRIMARY_TARGET),),
        )


def test_a_card_operation_cannot_be_built_without_a_name():
    """
    카드를 다루는 일인데 어느 카드인지 말하지 않으면 그것은 일이 아니다.
    ``None`` 을 허용하면 "대상이 없다" 와 "빠뜨렸다" 가 같아진다.
    """
    with pytest.raises(TypeError):
        CardOperation(OperationKind.DESTROY, None)
    with pytest.raises(TypeError):
        CardOperation(OperationKind.DESTROY, "primary")
    with pytest.raises(TypeError):
        CardOperation(OperationKind.DESTROY, targeting())


def test_a_declared_target_nobody_uses_is_refused():
    """고르게 해 놓고 아무 일도 쓰지 않는 정의는 모순이다."""
    with pytest.raises(EffectDefinitionError) as excinfo:
        EffectDefinition(
            EffectRef(KUKLOK, 0),
            KUKLOK,
            targets=TargetBinding.single(targeting()),
            operations=(DrawOperation(1),),
        )
    assert "아무 일도" in str(excinfo.value)


def test_an_unused_target_is_allowed_while_the_effect_is_unwritten():
    """
    하는 일을 아직 적지 않았으면 넘어간다. **"미완성" 과 "모순" 은 다르다** —
    Phase 2-D-1 이 세운 "적지 않음 ≠ 없음" 원칙 그대로다.
    """
    definition = EffectDefinition(
        EffectRef(KUKLOK, 0), KUKLOK, targets=TargetBinding.single(targeting())
    )
    assert not definition.is_described
    assert definition.requires_target


def test_a_duplicated_target_name_is_refused():
    with pytest.raises(EffectDefinitionError) as excinfo:
        EffectDefinition(
            EffectRef(KUKLOK, 0),
            KUKLOK,
            targets=(
                TargetBinding(PRIMARY_TARGET, targeting()),
                TargetBinding(PRIMARY_TARGET, targeting(PlayerRef.OPPONENT)),
            ),
            operations=(CardOperation.destroy(PRIMARY_TARGET),),
        )
    assert "두 번 선언" in str(excinfo.value)


def test_a_binding_needs_a_rule_that_actually_selects():
    """고를 것이 없는 대상은 이름을 가질 이유가 없다."""
    with pytest.raises(ValueError):
        TargetBinding(PRIMARY_TARGET, TargetSpec.none())


def test_an_empty_target_name_is_refused():
    for bad in ("", "  ", " primary"):
        with pytest.raises(ValueError):
            TargetRef(bad)


# ======================================================================
# 5. 대상이 없는 일
# ======================================================================


def test_operations_without_targets_need_no_name():
    """
    드로우와 라이프 변화에는 ``target_ref`` **칸 자체가 없다.** 없는 것을
    ``None`` 으로 표현하면 "빠뜨렸다" 와 구분되지 않는다.
    """
    for operation in (
        DrawOperation(2),
        LifeChangeOperation(-1000),
        UnimplementedOperation("special summon"),
    ):
        assert operation.target_refs == ()
        assert not hasattr(operation, "target_ref")

    definition = EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        operations=(DrawOperation(1), LifeChangeOperation(-500)),
    )
    assert not definition.requires_target
    assert definition.is_described


def test_every_card_operation_kind_requires_a_name():
    builders = (
        CardOperation.destroy,
        CardOperation.send_to_grave,
        CardOperation.banish,
        CardOperation.release,
        CardOperation.discard,
        CardOperation.return_to_hand,
        CardOperation.return_to_deck,
    )
    for build in builders:
        operation = build(PRIMARY_TARGET)
        assert operation.target_refs == (PRIMARY_TARGET,)
    assert len(builders) == len(
        [k for k in OperationKind if k.name in {b.__name__.upper() for b in builders}]
    )


# ======================================================================
# 7~8. 정의와 문맥의 경계
# ======================================================================


def test_no_instance_id_is_baked_into_a_definition(state):
    """
    정의는 어느 카드가 골라질지 모른다. 알면 그 정의는 한 판에서 한 번밖에
    쓸 수 없다.
    """
    card = state.player(1).monster_zone[0]
    definition = EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        targets=TargetBinding.single(targeting(PlayerRef.OPPONENT)),
        operations=(CardOperation.destroy(PRIMARY_TARGET),),
        provenance=EffectProvenance.official_lua(),
    )

    text = json.dumps(definition.to_dict(), ensure_ascii=False)
    assert str(card.instance_id.value) not in text
    assert "instance" not in text

    def leaves(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from leaves(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from leaves(item)
        else:
            yield value

    assert not any(
        isinstance(value, InstanceId) for value in leaves(definition.canonical_state())
    )


def test_the_same_definition_serves_two_different_selections(state):
    """
    정의 하나로 두 해결을 표현할 수 있어야 한다. 그것이 정의와 문맥을
    나눈 이유다.
    """
    definition = EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        targets=TargetBinding.single(targeting(PlayerRef.OPPONENT)),
        operations=(CardOperation.destroy(PRIMARY_TARGET),),
    )
    mine = state.player(0).monster_zone[0].instance_id
    theirs = state.player(1).monster_zone[0].instance_id

    first = ResolutionContext(
        EffectRef(KUKLOK, 0),
        controller=0,
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(theirs)),),
    )
    second = ResolutionContext(
        EffectRef(KUKLOK, 0),
        controller=1,
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(mine)),),
    )

    assert first.canonical_state() != second.canonical_state()
    assert first.selection_for(PRIMARY_TARGET) == Selection.of(theirs)
    assert second.selection_for(PRIMARY_TARGET) == Selection.of(mine)


def test_a_target_spec_is_not_a_selection():
    spec = targeting()
    selection = TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(7)))
    assert type(spec) is not type(selection)
    assert spec.canonical_state() != selection.canonical_state()


def test_what_is_still_pending_is_read_from_the_definition(state):
    """문맥은 자기가 무엇을 요구받았는지 모른다. 요구는 정의에 있다."""
    definition = EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        targets=(
            TargetBinding(PRIMARY_TARGET, targeting()),
            TargetBinding(SECOND, targeting(PlayerRef.OPPONENT)),
        ),
        operations=(
            CardOperation.destroy(PRIMARY_TARGET),
            CardOperation.banish(SECOND),
        ),
    )
    mine = state.player(0).monster_zone[0].instance_id

    nothing = ResolutionContext(EffectRef(KUKLOK, 0), controller=0)
    assert nothing.pending_targets(definition) == (PRIMARY_TARGET, SECOND)

    half = dataclasses.replace(
        nothing, selections=(TargetSelection(PRIMARY_TARGET, Selection.of(mine)),)
    )
    assert half.pending_targets(definition) == (SECOND,)


def test_an_empty_selection_is_not_the_same_as_no_selection():
    """"고른 결과가 없음" 과 "아직 고르지 않음" 은 다르다."""
    context = ResolutionContext(
        EffectRef(KUKLOK, 0),
        controller=0,
        selections=(TargetSelection(PRIMARY_TARGET, Selection()),),
    )
    assert context.selection_for(PRIMARY_TARGET) == Selection()
    assert context.selection_for(PRIMARY_TARGET) is not None
    assert context.selection_for(SECOND) is None


# ======================================================================
# 6, 9~12. 불변 · 결정론 · 경계 유지
# ======================================================================


def test_the_link_pieces_are_immutable():
    ref = TargetRef("primary")
    binding = TargetBinding(ref, targeting())
    chosen = TargetSelection(ref, Selection.of(InstanceId(1)))
    operation = CardOperation.destroy(ref)

    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.name = "other"
    with pytest.raises(dataclasses.FrozenInstanceError):
        binding.spec = TargetSpec.none()
    with pytest.raises(dataclasses.FrozenInstanceError):
        chosen.selection = Selection()
    with pytest.raises(dataclasses.FrozenInstanceError):
        operation.target_ref = SECOND


def test_the_link_is_deterministic():
    def build() -> EffectDefinition:
        return EffectDefinition(
            EffectRef(KUKLOK, 1),
            KUKLOK,
            targets=(
                TargetBinding(PRIMARY_TARGET, targeting(PlayerRef.OPPONENT)),
                TargetBinding(SECOND, targeting()),
            ),
            operations=(
                CardOperation.destroy(PRIMARY_TARGET),
                CardOperation.send_to_grave(SECOND),
            ),
            provenance=EffectProvenance.official_lua(),
        )

    a, b = build(), build()
    assert a == b
    assert a.canonical_state() == b.canonical_state()
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(
        b.to_dict(), sort_keys=True
    )

    for value in (a.canonical_state(), a.to_dict()):
        text = json.dumps(value, ensure_ascii=False)
        assert "0x" not in text and "object at" not in text


def test_target_name_order_is_preserved():
    """선언 순서는 의미를 가질 수 있다. 정렬하지 않는다."""
    first = TargetBinding(PRIMARY_TARGET, targeting())
    second = TargetBinding(SECOND, targeting())
    operations = (
        CardOperation.destroy(PRIMARY_TARGET),
        CardOperation.banish(SECOND),
    )
    a = EffectDefinition(
        EffectRef(KUKLOK, 0), KUKLOK, targets=(first, second), operations=operations
    )
    b = EffectDefinition(
        EffectRef(KUKLOK, 0), KUKLOK, targets=(second, first), operations=operations
    )
    assert a.canonical_state() != b.canonical_state()
    assert a.target_refs == (PRIMARY_TARGET, SECOND)
    assert b.target_refs == (SECOND, PRIMARY_TARGET)


def test_the_operation_meanings_are_still_apart():
    """연결을 붙이면서 파괴 · 묘지送り · 릴리스가 합쳐지지 않았는지 본다."""
    destroy = CardOperation.destroy(PRIMARY_TARGET)
    send = CardOperation.send_to_grave(PRIMARY_TARGET)
    release = CardOperation.release(PRIMARY_TARGET)

    assert destroy.target_ref == send.target_ref == release.target_ref
    assert destroy.kind is not send.kind is not release.kind
    assert destroy.canonical_state() != send.canonical_state()
    assert send.canonical_state() != release.canonical_state()
    assert "DESTROY" in destroy.reason_names
    assert "DESTROY" not in send.reason_names
    assert "DESTROY" not in release.reason_names


def test_text_derived_is_still_refused_with_the_new_link(state):
    definition = EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        targets=TargetBinding.single(targeting(PlayerRef.OPPONENT)),
        operations=(CardOperation.destroy(PRIMARY_TARGET),),
        provenance=EffectProvenance.text_derived(),
    )

    class Everything:
        def has_implementation(self, effect_ref):
            return True

    assert (
        execution_availability(definition, Everything())
        is ExecutionAvailability.FORBIDDEN_SOURCE
    )

    view = GameStateView.from_state(state, viewer=0)
    context = ResolutionContext(
        EffectRef(KUKLOK, 0),
        controller=0,
        selections=(
            TargetSelection(
                PRIMARY_TARGET,
                Selection.of(state.player(1).monster_zone[0].instance_id),
            ),
        ),
    )
    result = UnimplementedResolver(Everything()).resolve(definition, context, view)
    assert result.status is ResolutionStatus.FORBIDDEN
    assert not result.changed_state


def _snapshot(state: GameState) -> tuple:
    return (
        state.state_hash(),
        state.allocator.next_value,
        state.uses.canonical_state(),
        tuple(
            card.canonical_state()
            for card in sorted(state.all_instances(), key=lambda c: c.instance_id)
        ),
    )


def test_linking_a_target_to_a_destroy_destroys_nothing(state):
    before = _snapshot(state)
    theirs = state.player(1).monster_zone[0]
    view = GameStateView.from_state(state, viewer=0)

    definition = EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        targets=TargetBinding.single(targeting(PlayerRef.OPPONENT)),
        operations=(CardOperation.destroy(PRIMARY_TARGET),),
        provenance=EffectProvenance.official_lua(),
    )
    context = ResolutionContext(
        EffectRef(KUKLOK, 0),
        controller=0,
        selections=(
            TargetSelection(PRIMARY_TARGET, Selection.of(theirs.instance_id)),
        ),
    )
    for _ in range(5):
        UnimplementedResolver().resolve(definition, context, view)
        context.pending_targets(definition)

    assert _snapshot(state) == before
    assert theirs.zone is Zone.MZONE  # 파괴 대상이었던 카드가 그대로 있다
