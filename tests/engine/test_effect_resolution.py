"""
engine/effect/resolution.py — 해결 **계약**.

실행기는 없다. 있는 것은 계약과, 그 계약을 지키는 유일한 구현
(:class:`UnimplementedResolver`)뿐이다. 그것은 언제나 실패를 돌려주고
**판을 바꾸지 않는다** — 등록된 효과 구현이 하나도 없다는 사실 그대로다.
"""

import dataclasses
import json

import pytest

from engine.condition import ConditionContext, PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.effect import (
    PRIMARY_TARGET,
    CardOperation,
    DrawOperation,
    EffectDefinition,
    EffectProvenance,
    EffectResolver,
    EffectResult,
    ResolutionContext,
    ResolutionStatus,
    TargetBinding,
    TargetRef,
    TargetSelection,
    TargetSpec,
    UnimplementedResolver,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Position, Zone

KUKLOK = 2511
DECK_A = list(range(1000, 1040))
DECK_B = list(range(2000, 2040))


@pytest.fixture
def state() -> GameState:
    game = GameState.create(decks=(DECK_A, DECK_B))
    game.draw(0, 5)
    game.draw(1, 5)
    game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    return game


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=0)


def monsters() -> ChoiceSpec:
    return ChoiceSpec(source=CandidateSource(zones=frozenset({Zone.MZONE})))


@pytest.fixture
def definition() -> EffectDefinition:
    """"대상으로 지정한 몬스터 1장을 파괴하고 1장 드로우."" """
    return EffectDefinition(
        effect_ref=EffectRef(KUKLOK, 0),
        source_card_id=KUKLOK,
        targets=TargetBinding.single(TargetSpec.targeting(monsters())),
        operations=(CardOperation.destroy(PRIMARY_TARGET), DrawOperation(1)),
        provenance=EffectProvenance.official_lua(),
    )


@pytest.fixture
def context() -> ResolutionContext:
    return ResolutionContext(EffectRef(KUKLOK, 0), controller=0)


# ======================================================================
# 19~21. ResolutionContext
# ======================================================================


def test_the_context_keeps_what_the_resolution_needs():
    context = ResolutionContext(
        effect_ref=EffectRef(KUKLOK, 1),
        controller=1,
        source=InstanceId(4),
        selections=(
            TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(7), InstanceId(9))),
        ),
        cost_selections=(Selection.of(InstanceId(3)),),
    )
    assert context.effect_ref == EffectRef(KUKLOK, 1)
    assert context.controller == 1
    assert context.opponent == 0
    assert context.source == InstanceId(4)
    assert context.chosen_instances == (InstanceId(7), InstanceId(9))
    assert len(context.cost_selections) == 1


def test_a_selection_is_looked_up_by_name():
    """
    이름으로 잇는다. 고르지 않은 이름은 **빈 선택이 아니라 ``None``** 이다 —
    "고른 결과가 없음" 과 "아직 고르지 않음" 은 다르다.
    """
    context = ResolutionContext(
        EffectRef(KUKLOK, 0),
        controller=0,
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(7))),),
    )
    assert context.selection_for(PRIMARY_TARGET) == Selection.of(InstanceId(7))
    assert context.selection_for(TargetRef("other")) is None


def test_the_same_name_cannot_be_chosen_twice():
    with pytest.raises(ValueError):
        ResolutionContext(
            EffectRef(KUKLOK, 0),
            controller=0,
            selections=(
                TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(1))),
                TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(2))),
            ),
        )


def test_the_context_is_immutable():
    context = ResolutionContext(EffectRef(KUKLOK, 0), controller=0)
    for name in ("effect_ref", "controller", "source", "selections"):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(context, name, None)
    with pytest.raises(TypeError):
        ResolutionContext(
            EffectRef(KUKLOK, 0), 0, cost_selections=[Selection()]
        )
    with pytest.raises(TypeError):
        ResolutionContext(EffectRef(KUKLOK, 0), 0, selections=[])


def test_the_context_refuses_an_impossible_controller():
    with pytest.raises(ValueError):
        ResolutionContext(EffectRef(KUKLOK, 0), controller=2)


def test_the_context_holds_no_object_references():
    """
    ``CardInstance`` 나 ``GameState`` 를 담으면 문맥이 특정 판에 묶이고
    직렬화도 replay 도 불가능해진다.
    """
    context = ResolutionContext(
        EffectRef(KUKLOK, 1),
        controller=0,
        source=InstanceId(4),
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(7))),),
        cost_selections=(Selection.of(InstanceId(3)),),
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

    for value in leaves(context.canonical_state()):
        assert value is None or isinstance(value, (int, str, bool)), value
    for value in leaves(context.to_dict()):
        assert value is None or isinstance(value, (int, str, bool)), value
    text = json.dumps(context.to_dict(), ensure_ascii=False)
    assert "0x" not in text and "InstanceId(" not in text


def test_the_context_converts_to_a_condition_context():
    """
    조건 계층이 자기 문맥 타입을 갖고 있다. 두 타입을 합치지 않고 변환한다 —
    조건은 비용 선택을 알 필요가 없다.
    """
    context = ResolutionContext(
        EffectRef(KUKLOK, 1),
        controller=1,
        source=InstanceId(4),
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(7))),),
        cost_selections=(Selection.of(InstanceId(3)),),
    )
    condition_context = context.condition_context()

    assert isinstance(condition_context, ConditionContext)
    assert condition_context.player == 1
    assert condition_context.source == InstanceId(4)
    assert condition_context.effect_ref == EffectRef(KUKLOK, 1)
    assert condition_context.targets == (InstanceId(7),)
    # 비용 선택은 조건 문맥에 없다.
    assert not hasattr(condition_context, "cost_selections")


def test_an_empty_target_selection_is_not_the_same_as_no_target(definition):
    """
    §11 의 구분이 문맥에서도 유지된다. 고른 것이 없는 것과 고를 것이
    없는 것은 다르다. 무엇을 기다리는지는 **정의를 봐야** 알 수 있다 —
    문맥은 자기가 무엇을 요구받았는지 모른다.
    """
    nothing_chosen = ResolutionContext(EffectRef(KUKLOK, 0), controller=0)
    assert definition.requires_target
    assert nothing_chosen.pending_targets(definition) == (PRIMARY_TARGET,)

    chosen = dataclasses.replace(
        nothing_chosen,
        selections=(TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(7))),),
    )
    assert chosen.pending_targets(definition) == ()

    # 대상을 요구하지 않는 효과는 아무것도 기다리지 않는다.
    no_target = EffectDefinition(
        EffectRef(KUKLOK, 0), KUKLOK, operations=(DrawOperation(1),)
    )
    assert not no_target.requires_target
    assert nothing_chosen.pending_targets(no_target) == ()


# ======================================================================
# EffectResult
# ======================================================================


def test_a_result_that_is_not_resolved_never_claims_a_state_change():
    for status in ResolutionStatus:
        result = EffectResult(status)
        assert result.changed_state is (status is ResolutionStatus.RESOLVED)


def test_a_result_cannot_be_used_as_a_boolean():
    """``if result:`` 로 실패가 성공으로 읽히는 길을 막는다."""
    result = EffectResult(ResolutionStatus.NOT_IMPLEMENTED)
    with pytest.raises(TypeError):
        bool(result)
    with pytest.raises(TypeError):
        if result:  # noqa: SIM103
            pass


def test_a_result_is_immutable():
    result = EffectResult(ResolutionStatus.UNKNOWN)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.status = ResolutionStatus.RESOLVED


# ======================================================================
# 해결 계약
# ======================================================================


def test_the_only_resolver_satisfies_the_protocol():
    assert isinstance(UnimplementedResolver(), EffectResolver)


def test_the_resolver_refuses_a_raw_game_state(state, definition, context):
    """
    ``GameState`` 를 받으면 ``move()`` 가 손에 닿는다. 계약이 판을 바꿀 수
    있게 되므로 타입 단계에서 막는다.
    """
    with pytest.raises(TypeError) as excinfo:
        UnimplementedResolver().resolve(definition, context, state)
    assert "GameStateView" in str(excinfo.value)


def test_nothing_resolves_today(view, definition, context):
    """
    등록된 효과 구현이 하나도 없다. 자리표시가 아니라 **지금의 사실**이다.
    """
    result = UnimplementedResolver().resolve(definition, context, view)
    assert result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert not result.changed_state
    assert result.missing


def test_text_derived_is_refused_before_anything_else(view, context):
    """출처 금지가 가장 먼저 걸린다 (ADR-004)."""
    forbidden = EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        targets=TargetBinding.single(TargetSpec.targeting(monsters())),
        operations=(CardOperation.destroy(PRIMARY_TARGET),),
        provenance=EffectProvenance.text_derived(),
    )

    class Everything:
        def has_implementation(self, effect_ref):
            return True

    result = UnimplementedResolver(Everything()).resolve(forbidden, context, view)
    assert result.status is ResolutionStatus.FORBIDDEN
    assert not result.changed_state


def test_unverified_semantics_resolve_to_unknown(view, context):
    unverified = EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        provenance=EffectProvenance.hand_written(verified=False),
    )
    result = UnimplementedResolver().resolve(unverified, context, view)
    assert result.status is ResolutionStatus.UNKNOWN
    assert result.missing == "verified semantics"


def test_a_context_pointing_at_another_effect_is_refused(view, definition):
    """
    문맥이 다른 효과를 가리키면 무엇을 하든 잘못된 카드를 건드린다.
    그 상태로 진행하지 않는다.
    """
    wrong = ResolutionContext(EffectRef(KUKLOK, 1), controller=0)
    result = UnimplementedResolver().resolve(definition, wrong, view)
    assert result.status is ResolutionStatus.INVALID_CONTEXT
    assert result.code is ValidationCode.EFFECT_REF_CARD_MISMATCH


def test_a_registered_implementation_still_does_not_execute_here(view, definition, context):
    """
    구현이 등록되어 있어도 **이 실행기는 실행하지 않는다.** Phase 2-D-1 은
    계약만 정의하고, 실제 실행기는 Phase 2-D-2 가 만든다.
    """

    class Registry:
        def has_implementation(self, effect_ref):
            return True

    result = UnimplementedResolver(Registry()).resolve(definition, context, view)
    assert result.status is not ResolutionStatus.RESOLVED
    assert not result.changed_state
    assert "Phase 2-D-2" in (result.missing or "")


def test_no_resolver_in_this_phase_ever_reports_resolved(view, definition, context):
    class Everything:
        def has_implementation(self, effect_ref):
            return True

    for lookup in (None, Everything()):
        for provenance in (
            EffectProvenance.official_lua(),
            EffectProvenance.text_derived(),
            EffectProvenance.hand_written(verified=True),
            EffectProvenance(),
        ):
            candidate = dataclasses.replace(definition, provenance=provenance)
            result = UnimplementedResolver(lookup).resolve(candidate, context, view)
            assert result.status is not ResolutionStatus.RESOLVED
            assert not result.changed_state


# ======================================================================
# 25~27. 아무것도 바꾸지 않는다
# ======================================================================


def _snapshot(state: GameState) -> tuple:
    return (
        state.state_hash(),
        state.allocator.next_value,
        state.uses.canonical_state(),
        state.turn.canonical_state(),
        tuple(state.player(p).life_points for p in (0, 1)),
        tuple(
            len(state.player(p).zone(z))
            for p in (0, 1)
            for z in Zone
            if z in state.player(p).zones
        ),
        tuple(
            card.canonical_state()
            for card in sorted(state.all_instances(), key=lambda c: c.instance_id)
        ),
    )


def test_building_a_definition_changes_nothing(state):
    before = _snapshot(state)
    for _ in range(5):
        EffectDefinition(
            EffectRef(KUKLOK, 0),
            KUKLOK,
            targets=TargetBinding.single(TargetSpec.targeting(monsters())),
            operations=(
                CardOperation.destroy(PRIMARY_TARGET),
                CardOperation.banish(PRIMARY_TARGET),
                DrawOperation(3),
            ),
            provenance=EffectProvenance.official_lua(),
        )
    assert _snapshot(state) == before


def test_building_a_context_changes_nothing(state):
    before = _snapshot(state)
    card = state.player(0).monster_zone[0]
    for _ in range(5):
        ResolutionContext(
            EffectRef(KUKLOK, 0),
            controller=0,
            source=card.instance_id,
            selections=(
                TargetSelection(PRIMARY_TARGET, Selection.of(card.instance_id)),
            ),
        )
    assert _snapshot(state) == before


def test_calling_the_contract_changes_nothing(state, definition, context):
    """
    **핵심 불변식.** 해결을 시도해도 판은 그대로다 — 반쯤 실행해 놓고
    실패를 알리는 일이 없다.
    """
    before = _snapshot(state)
    view = GameStateView.from_state(state, viewer=0)
    resolver = UnimplementedResolver()

    for _ in range(10):
        resolver.resolve(definition, context, view)

    assert _snapshot(state) == before
    # 파괴 대상이 될 뻔한 카드가 그대로 필드에 있다.
    assert len(state.player(0).monster_zone) == 1


def test_a_destroy_operation_does_not_destroy_anything(state):
    """
    ``CardOperation.destroy`` 를 만드는 것은 청구서를 쓰는 일이지 돈을
    내는 일이 아니다.
    """
    before = _snapshot(state)
    card = state.player(0).monster_zone[0]
    CardOperation.destroy(PRIMARY_TARGET)
    EffectDefinition(
        EffectRef(KUKLOK, 0),
        KUKLOK,
        targets=TargetBinding.single(TargetSpec.targeting(monsters())),
        operations=(CardOperation.destroy(PRIMARY_TARGET),),
    )
    assert _snapshot(state) == before
    assert card.zone is Zone.MZONE


def test_the_resolver_exposes_no_mutation_path():
    resolver = UnimplementedResolver()
    for forbidden in ("execute", "apply", "move", "draw", "state", "mutate"):
        assert not hasattr(resolver, forbidden), (
            f"UnimplementedResolver.{forbidden} 이 생겼습니다. 계약과 실행은 "
            "분리되어야 합니다."
        )


# ======================================================================
# 28~29. 결정론
# ======================================================================


def test_the_same_inputs_always_give_the_same_result(view, definition, context):
    resolver = UnimplementedResolver()
    first = resolver.resolve(definition, context, view)
    for _ in range(10):
        assert (
            resolver.resolve(definition, context, view).canonical_state()
            == first.canonical_state()
        )


def test_a_fresh_resolver_agrees(view, definition, context):
    a = UnimplementedResolver().resolve(definition, context, view)
    b = UnimplementedResolver().resolve(definition, context, view)
    assert a.canonical_state() == b.canonical_state()
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(
        b.to_dict(), sort_keys=True
    )


def test_the_context_representation_is_deterministic():
    picked = (TargetSelection(PRIMARY_TARGET, Selection.of(InstanceId(7))),)
    a = ResolutionContext(EffectRef(KUKLOK, 1), 0, InstanceId(3), picked)
    b = ResolutionContext(EffectRef(KUKLOK, 1), 0, InstanceId(3), picked)
    assert a == b
    assert a.canonical_state() == b.canonical_state()
    assert (
        a.canonical_state()
        != ResolutionContext(EffectRef(KUKLOK, 1), 1).canonical_state()
    )
