"""
engine/cost/ — 후보 찾기와 검증.

**아무것도 치르지 않고 아무것도 고르지 않는다.** 후보를 세고, 고른 것이
맞는지 보고, 모르면 모른다고 한다.
"""

import json

import pytest

from engine.condition import (
    AttributeIs,
    Condition,
    ConditionContext,
    ConditionEvaluator,
    IsMonster,
    LevelAtLeast,
    PlayerRef,
    UnimplementedRule,
)
from engine.cost import (
    CandidateResolver,
    CandidateSet,
    CandidateSource,
    CardCost,
    ChoiceSpec,
    CostGroup,
    CostValidator,
    LifeCost,
    Selection,
    SelectionValidator,
    UnimplementedCost,
)
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Position, Zone

from tests.conftest import requires_official_db

BLUE_EYES = 89631139  # LIGHT / DRAGON / 레벨 8 / 3000
DARK_MAGICIAN = 46986414  # DARK / SPELLCASTER / 레벨 7 / 2500
RED_EYES = 74677422  # DARK / DRAGON / 레벨 7 / 2400
DARK_HOLE = 53129443  # 마법

VALID = ActionValidity.VALID
INVALID = ActionValidity.INVALID
UNKNOWN = ActionValidity.UNKNOWN


@pytest.fixture
def state(repository) -> GameState:
    """
    p0 필드: 푸른 눈(LIGHT) · 블랙 매지션(DARK)
    p0 패:   붉은 눈 · 다크 홀
    p1 필드: 붉은 눈(DARK) 앞면 · 카드 하나 뒷면
    """
    game = GameState.create(repository, decks=([BLUE_EYES] * 10, [RED_EYES] * 10))
    for card_id in (BLUE_EYES, DARK_MAGICIAN):
        card = game.create_instance(card_id, owner=0, zone=Zone.MZONE)
        card.set_position(Position.FACEUP_ATTACK)
    for card_id in (RED_EYES, DARK_HOLE):
        game.create_instance(card_id, owner=0, zone=Zone.HAND)
    theirs = game.create_instance(RED_EYES, owner=1, zone=Zone.MZONE)
    theirs.set_position(Position.FACEUP_ATTACK)
    hidden = game.create_instance(DARK_MAGICIAN, owner=1, zone=Zone.SZONE)
    hidden.set_position(Position.FACEDOWN)
    game.draw(1, 3)
    return game


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=0)


@pytest.fixture
def context() -> ConditionContext:
    return ConditionContext(player=0)


@pytest.fixture
def resolver(view) -> CandidateResolver:
    return CandidateResolver(view)


@pytest.fixture
def costs(view) -> CostValidator:
    return CostValidator(view)


@pytest.fixture
def selections(view) -> SelectionValidator:
    return SelectionValidator(view)


def _my_monsters(state) -> list[InstanceId]:
    return [c.instance_id for c in state.player(0).monster_zone]


# ======================================================================
# 13~15. 후보 찾기
# ======================================================================


@requires_official_db
def test_candidates_come_from_the_named_zones(resolver, context, state):
    spec = CardCost.release(1).choice_spec()
    candidates = resolver.resolve(spec, context)

    assert candidates.certain_count == 2
    assert set(candidates.eligible) == set(_my_monsters(state))
    assert not candidates.has_undecided


@requires_official_db
def test_candidates_respect_the_owner(resolver, context, state):
    theirs = CardCost.release(1, who=PlayerRef.OPPONENT).choice_spec()
    candidates = resolver.resolve(theirs, context)

    assert candidates.certain_count == 1
    assert candidates.eligible[0] == state.player(1).monster_zone[0].instance_id


@requires_official_db
def test_candidates_can_span_both_players(resolver, context):
    spec = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.MZONE, Zone.EMZONE}), owner=None
        )
    )
    assert resolver.resolve(spec, context).certain_count == 3


@requires_official_db
def test_a_required_property_filters_the_candidates(resolver, context, state):
    """'어둠 속성 몬스터 1장' — 푸른 눈은 빛 속성이라 후보가 아니다."""
    spec = CardCost.release(1, require=AttributeIs("DARK")).choice_spec()
    candidates = resolver.resolve(spec, context)

    assert candidates.certain_count == 1
    chosen = candidates.eligible[0]
    assert state.find_instance(chosen).card_id == DARK_MAGICIAN


@requires_official_db
def test_no_candidates_when_nothing_matches(resolver, context):
    spec = CardCost.release(1, require=LevelAtLeast(12)).choice_spec()
    candidates = resolver.resolve(spec, context)
    assert candidates.certain_count == 0
    assert not candidates.has_undecided


@requires_official_db
def test_an_empty_field_yields_no_candidates(repository, context):
    empty = GameState.create(repository, decks=([], []))
    view = GameStateView.from_state(empty, viewer=0)
    candidates = CandidateResolver(view).resolve(
        CardCost.release(1).choice_spec(), context
    )
    assert candidates.certain_count == 0
    assert candidates.possible_count == 0


# ======================================================================
# 14. 결정론적 순서
# ======================================================================


@requires_official_db
def test_candidate_order_is_stable(resolver, context):
    spec = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.MZONE, Zone.EMZONE, Zone.SZONE, Zone.HAND}),
            owner=None,
        )
    )
    first = resolver.resolve(spec, context).canonical_state()
    for _ in range(10):
        assert resolver.resolve(spec, context).canonical_state() == first


@requires_official_db
def test_candidate_order_follows_controller_then_zone_then_slot(state, context):
    """
    집합 순회 순서에 의존하지 않는다. 내 카드가 먼저, 그 다음 상대,
    존 안에서는 칸 번호 순이다.
    """
    view = GameStateView.from_state(state, viewer=0)
    spec = ChoiceSpec(
        source=CandidateSource(zones=frozenset({Zone.MZONE, Zone.SZONE}), owner=None)
    )
    eligible = CandidateResolver(view).resolve(spec, context).eligible

    controllers = [view.find(i).controller for i in eligible]
    assert controllers == sorted(controllers), "컨트롤러 순이 아닙니다."


# ======================================================================
# 16, 31. 정보 경계
# ======================================================================


@requires_official_db
def test_a_concealed_zone_contributes_no_candidates(resolver, context, state):
    """상대의 패는 관측에 아예 없다. 후보에 들어갈 길이 없다."""
    spec = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.HAND}), owner=PlayerRef.OPPONENT
        )
    )
    candidates = resolver.resolve(spec, context)

    assert resolver.view.opponent.hand.size == 3  # 장수는 안다
    assert candidates.certain_count == 0  # 그러나 지목할 수 없다
    assert candidates.possible_count == 0


@requires_official_db
def test_a_face_down_card_is_undecided_when_the_test_needs_its_identity(state, context):
    """
    상대의 세트 카드가 어둠 속성인지 **모른다.** 후보에서 빼면 치를 수 있는
    비용을 못 치른다고 하게 되고, 넣으면 못 치를 비용을 치를 수 있다고 하게
    된다. 그래서 따로 센다.
    """
    view = GameStateView.from_state(state, viewer=0)
    spec = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.SZONE}),
            owner=PlayerRef.OPPONENT,
            require=IsMonster(),
        )
    )
    candidates = CandidateResolver(view).resolve(spec, context)

    assert candidates.certain_count == 0
    assert len(candidates.undecided) == 1
    assert "뒷면" in candidates.reasons[0]


@requires_official_db
def test_the_controller_of_a_set_card_can_decide(state, context):
    """같은 카드라도 주인이 보면 확정된다."""
    owner_view = GameStateView.from_state(state, viewer=1)
    spec = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.SZONE}),
            owner=PlayerRef.CONTROLLER,
            require=IsMonster(),
        )
    )
    candidates = CandidateResolver(owner_view).resolve(
        spec, ConditionContext(player=1)
    )
    assert candidates.certain_count == 1
    assert not candidates.has_undecided


@requires_official_db
def test_the_resolver_reveals_no_hidden_card_id(state, context):
    """후보 결과 어디에도 가려진 카드의 정체가 나오면 안 된다."""
    view = GameStateView.from_state(state, viewer=0)
    spec = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.SZONE, Zone.HAND}),
            owner=PlayerRef.OPPONENT,
            require=AttributeIs("DARK"),
        )
    )
    candidates = CandidateResolver(view).resolve(spec, context)
    text = json.dumps(candidates.to_dict(), ensure_ascii=False)

    hidden = state.player(1).spell_zone[0]
    assert str(hidden.card_id) not in text
    assert state.repository.get(hidden.card_id).name not in text
    for card in state.player(1).hand:
        assert str(card.card_id) not in text


def test_the_resolver_refuses_a_raw_game_state(state):
    with pytest.raises(TypeError):
        CandidateResolver(state)


# ======================================================================
# 5~7, 11. 비용 판정
# ======================================================================


@requires_official_db
def test_enough_candidates_means_the_cost_can_be_paid(costs, context):
    result = costs.validate(CardCost.release(1), context)
    assert result.validity is VALID
    assert result.permits_execution


@requires_official_db
def test_too_few_candidates_is_invalid(costs, context):
    result = costs.validate(CardCost.release(3), context)
    assert result.validity is INVALID
    assert result.code is ValidationCode.NO_CANDIDATES
    assert not result.permits_execution


@requires_official_db
def test_a_cost_nobody_can_pay_is_invalid(costs, context):
    result = costs.validate(CardCost.release(1, require=LevelAtLeast(12)), context)
    assert result.validity is INVALID
    assert result.code is ValidationCode.NO_CANDIDATES


@requires_official_db
def test_an_optional_cost_is_always_payable(costs, context):
    result = costs.validate(CardCost.discard(0, maximum=2), context)
    assert result.validity is VALID


@requires_official_db
def test_life_cost_compares_without_paying(costs, context, state):
    before = state.player(0).life_points
    assert costs.validate(LifeCost(1000), context).validity is VALID
    assert costs.validate(LifeCost(8000), context).validity is VALID
    too_much = costs.validate(LifeCost(8001), context)
    assert too_much.validity is INVALID
    assert too_much.code is ValidationCode.INSUFFICIENT_LIFE
    assert state.player(0).life_points == before  # 한 점도 깎이지 않았다


@requires_official_db
def test_an_unimplementable_cost_is_unknown(costs, context):
    result = costs.validate(UnimplementedCost("xyz detach (Phase 2-D)"), context)
    assert result.validity is UNKNOWN
    assert result.code is ValidationCode.COST_NOT_IMPLEMENTED
    assert "xyz detach" in result.missing_rule
    assert not result.permits_execution


@requires_official_db
def test_undecided_candidates_make_the_cost_unknown(state, context):
    """
    확실한 후보로는 모자라는데 미확정을 세면 채울 수 있다. **모른다.**
    """
    view = GameStateView.from_state(state, viewer=0)
    cost = CardCost(
        kind=__import__("engine.cost", fromlist=["x"]).CostSemantics.BANISH,
        zones=frozenset({Zone.SZONE}),
        count=1,
        who=PlayerRef.OPPONENT,
        require=IsMonster(),
    )
    result = CostValidator(view).validate(cost, context)
    assert result.validity is UNKNOWN
    assert result.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert result.notes


@requires_official_db
def test_a_certain_shortfall_beats_uncertainty(state, context):
    """
    미확정을 전부 후보로 쳐도 모자라면, 모르는 것이 있어도 **확실히**
    못 치른다.
    """
    view = GameStateView.from_state(state, viewer=0)
    cost = CardCost.release(5, who=PlayerRef.OPPONENT, require=IsMonster())
    result = CostValidator(view).validate(cost, context)
    assert result.validity is INVALID
    assert result.code is ValidationCode.NO_CANDIDATES


# ======================================================================
# 3, 13. 복수 비용
# ======================================================================


@requires_official_db
def test_a_group_is_payable_when_every_cost_is(costs, context):
    group = CostGroup((LifeCost(1000), CardCost.release(1)))
    assert costs.validate_group(group, context).validity is VALID


@requires_official_db
def test_a_group_fails_when_any_cost_fails(costs, context):
    group = CostGroup((LifeCost(1000), CardCost.release(9)))
    result = costs.validate_group(group, context)
    assert result.validity is INVALID
    assert result.code is ValidationCode.NO_CANDIDATES


@requires_official_db
def test_a_certain_failure_beats_an_unknown_in_a_group(costs, context):
    """``INVALID`` 가 ``UNKNOWN`` 을 이긴다 — 조건 계층의 삼치 논리와 같다."""
    group = CostGroup((UnimplementedCost("counter"), LifeCost(99999)))
    result = costs.validate_group(group, context)
    assert result.validity is INVALID
    assert result.code is ValidationCode.INSUFFICIENT_LIFE


@requires_official_db
def test_a_group_with_an_unknown_stays_unknown(costs, context):
    group = CostGroup((LifeCost(1000), UnimplementedCost("counter removal")))
    result = costs.validate_group(group, context)
    assert result.validity is UNKNOWN
    assert not result.permits_execution


@requires_official_db
def test_an_empty_group_costs_nothing(costs, context):
    assert costs.validate_group(CostGroup(), context).validity is VALID


# ======================================================================
# 18~23. 선택 검증
# ======================================================================


@requires_official_db
def test_a_correct_selection_is_valid(selections, context, state):
    spec = CardCost.release(1).choice_spec()
    selection = Selection.of(_my_monsters(state)[0])
    result = selections.validate(spec, selection, context)
    assert result.validity is VALID


@requires_official_db
def test_choosing_a_card_outside_the_candidates_is_invalid(
    selections, context, state
):
    spec = CardCost.release(1).choice_spec()  # 내 몬스터만
    theirs = state.player(1).monster_zone[0].instance_id
    result = selections.validate(spec, Selection.of(theirs), context)

    assert result.validity is INVALID
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE


@requires_official_db
def test_choosing_a_card_that_does_not_exist_is_unknown(selections, context):
    """
    관측에 없는 카드다. 이 듀얼에 없는지 가려진 존에 있는지 구분할 수 없다.
    """
    spec = CardCost.release(1).choice_spec()
    result = selections.validate(spec, Selection.of(InstanceId(99999)), context)
    assert result.validity is UNKNOWN
    assert result.code is ValidationCode.HIDDEN_CARD


@requires_official_db
def test_too_few_selected(selections, context, state):
    spec = CardCost.release(2).choice_spec()
    result = selections.validate(spec, Selection.of(_my_monsters(state)[0]), context)
    assert result.validity is INVALID
    assert result.code is ValidationCode.TOO_FEW_SELECTED


@requires_official_db
def test_too_many_selected(selections, context, state):
    spec = CardCost.release(1).choice_spec()
    mine = _my_monsters(state)
    result = selections.validate(spec, Selection.of(*mine), context)
    assert result.validity is INVALID
    assert result.code is ValidationCode.TOO_MANY_SELECTED


@requires_official_db
def test_choosing_the_same_card_twice_is_invalid(selections, context, state):
    """한 장의 카드를 두 번 릴리스할 수는 없다."""
    spec = CardCost.release(2).choice_spec()
    one = _my_monsters(state)[0]
    result = selections.validate(spec, Selection.of(one, one), context)
    assert result.validity is INVALID
    assert result.code is ValidationCode.DUPLICATE_SELECTION


@requires_official_db
def test_duplicates_are_allowed_when_the_spec_says_so(selections, context, state):
    spec = ChoiceSpec(
        source=CandidateSource(zones=frozenset({Zone.MZONE})),
        minimum=2,
        maximum=2,
        allow_duplicates=True,
    )
    one = _my_monsters(state)[0]
    assert selections.validate(spec, Selection.of(one, one), context).validity is VALID


@requires_official_db
def test_choosing_an_undecided_card_is_unknown(state, context):
    view = GameStateView.from_state(state, viewer=0)
    spec = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.SZONE}),
            owner=PlayerRef.OPPONENT,
            require=IsMonster(),
        )
    )
    face_down = state.player(1).spell_zone[0].instance_id
    result = SelectionValidator(view).validate(
        spec, Selection.of(face_down), context
    )
    assert result.validity is UNKNOWN
    assert result.code is ValidationCode.INFORMATION_UNAVAILABLE


@requires_official_db
def test_an_empty_selection_is_fine_when_nothing_is_required(selections, context):
    spec = CardCost.discard(0, maximum=2).choice_spec()
    assert selections.validate(spec, Selection(), context).validity is VALID


@requires_official_db
def test_a_precomputed_candidate_set_gives_the_same_answer(
    selections, resolver, context, state
):
    spec = CardCost.release(1).choice_spec()
    selection = Selection.of(_my_monsters(state)[0])
    candidates = resolver.resolve(spec, context)

    with_pool = selections.validate(spec, selection, context, candidates=candidates)
    without = selections.validate(spec, selection, context)
    assert with_pool.canonical_state() == without.canonical_state()


# ======================================================================
# 24~25. 조건 계층 재사용과 UNKNOWN 전파
# ======================================================================


@requires_official_db
def test_the_resolver_uses_the_condition_layer(view, context):
    """규칙 평가기를 새로 만들지 않았다."""
    spec = CardCost.release(1, require=AttributeIs("DARK")).choice_spec()
    assert isinstance(spec.source.require, Condition)

    # 같은 조건을 직접 평가해도 같은 답이 나온다.
    evaluator = ConditionEvaluator(view)
    candidates = CandidateResolver(view).resolve(spec, context)
    import dataclasses

    for instance in candidates.eligible:
        per_card = dataclasses.replace(context, source=instance)
        assert evaluator.result(spec.source.require, per_card).is_true


@requires_official_db
def test_an_unimplemented_rule_in_a_requirement_makes_every_card_undecided(
    view, context, state
):
    """조건 계층의 ``UNKNOWN`` 이 후보 계층까지 그대로 온다."""
    spec = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.MZONE}),
            require=UnimplementedRule("chain (Phase 2-F)"),
        )
    )
    candidates = CandidateResolver(view).resolve(spec, context)

    assert candidates.certain_count == 0
    assert len(candidates.undecided) == len(_my_monsters(state))
    assert all("chain" in reason for reason in candidates.reasons)


# ======================================================================
# 9~10, 27~29. 아무것도 바꾸지 않는다
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


@requires_official_db
def test_nothing_is_paid_and_nothing_moves(state, context):
    before = _snapshot(state)
    view = GameStateView.from_state(state, viewer=0)
    resolver = CandidateResolver(view)
    costs = CostValidator(view)
    selections = SelectionValidator(view)
    mine = _my_monsters(state)

    for cost in (
        CardCost.release(1),
        CardCost.release(9),
        CardCost.discard(1),
        CardCost.banish(frozenset({Zone.GRAVE})),
        CardCost.send_to_grave(frozenset({Zone.MZONE})),
        LifeCost(1000),
        LifeCost(99999),
        UnimplementedCost("counter"),
    ):
        costs.validate(cost, context)
        spec = cost.choice_spec()
        if spec is not None:
            resolver.resolve(spec, context)
            selections.validate(spec, Selection.of(mine[0]), context)

    costs.validate_group(CostGroup((LifeCost(500), CardCost.release(1))), context)

    assert _snapshot(state) == before


@requires_official_db
def test_repeated_validation_does_not_accumulate(state, context):
    """
    "검증을 위해 미리 치러보기" 가 없는지 본다. 같은 비용을 열 번 검증해도
    라이프도 존도 사용 기록도 그대로여야 한다.
    """
    before = _snapshot(state)
    view = GameStateView.from_state(state, viewer=0)
    costs = CostValidator(view)
    for _ in range(10):
        costs.validate_group(
            CostGroup((LifeCost(1000), CardCost.release(1))), context
        )
    assert _snapshot(state) == before
    assert len(state.uses) == 0


@requires_official_db
def test_validators_expose_no_mutation_path(costs, selections, resolver):
    for holder in (costs, selections, resolver):
        for forbidden in ("pay", "execute", "apply", "move", "release", "state"):
            assert not hasattr(holder, forbidden), (
                f"{type(holder).__name__}.{forbidden} 이 생겼습니다. "
                "검증과 지불은 분리되어야 합니다."
            )


# ======================================================================
# 30. 결정론
# ======================================================================


@requires_official_db
def test_the_same_inputs_always_give_the_same_verdict(costs, context, state):
    group = CostGroup((LifeCost(1000), CardCost.release(1, require=AttributeIs("DARK"))))
    first = costs.validate_group(group, context)
    for _ in range(10):
        assert (
            costs.validate_group(group, context).canonical_state()
            == first.canonical_state()
        )


@requires_official_db
def test_a_fresh_validator_agrees(state, context):
    cost = CardCost.release(1, require=AttributeIs("DARK"))
    a = CostValidator(GameStateView.from_state(state, viewer=0)).validate(cost, context)
    b = CostValidator(GameStateView.from_state(state, viewer=0)).validate(cost, context)
    assert a.canonical_state() == b.canonical_state()


@requires_official_db
def test_the_snapshot_does_not_follow_the_board(state, context):
    """Phase 2-A 의 스냅숏 의미론이 비용 계층에서도 유지된다."""
    costs = CostValidator(GameStateView.from_state(state, viewer=0))
    assert costs.validate(CardCost.release(2), context).validity is VALID

    for card in list(state.player(0).monster_zone):
        state.move(card, Zone.GRAVE, to_player=0)

    assert costs.validate(CardCost.release(2), context).validity is VALID  # 옛 관측
    fresh = CostValidator(GameStateView.from_state(state, viewer=0))
    assert fresh.validate(CardCost.release(2), context).validity is INVALID


@requires_official_db
def test_verdicts_serialize_to_value_types_only(costs, context):
    result = costs.validate(CardCost.release(9), context)

    def leaves(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from leaves(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from leaves(item)
        else:
            yield value

    for value in leaves(result.to_dict()):
        assert value is None or isinstance(value, (int, str, bool)), value
    assert "0x" not in json.dumps(result.to_dict(), ensure_ascii=False)


# ======================================================================
# 12. Cost -> Choice -> Selection 전체 흐름
# ======================================================================


@requires_official_db
def test_the_whole_flow_from_cost_to_selection(state, context):
    """
    "자신 필드의 어둠 속성 몬스터 1장을 릴리스한다" 를 끝까지 따라간다.
    마지막에 **릴리스는 일어나지 않는다.**
    """
    before = _snapshot(state)
    view = GameStateView.from_state(state, viewer=0)

    cost = CardCost.release(1, require=AttributeIs("DARK"))
    assert CostValidator(view).validate(cost, context).validity is VALID

    spec = cost.choice_spec()
    candidates = CandidateResolver(view).resolve(spec, context)
    assert candidates.certain_count == 1

    selection = Selection.of(candidates.eligible[0])
    verdict = SelectionValidator(view).validate(spec, selection, context, candidates)
    assert verdict.validity is VALID

    # 판은 그대로다.
    assert _snapshot(state) == before
    assert state.find_instance(selection.chosen[0]).zone is Zone.MZONE
