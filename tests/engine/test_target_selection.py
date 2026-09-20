"""
Phase 2-N — 대상 선택 계층.

    TargetSpec → CandidateSet → TargetValidation → EffectExecutor

네 가지를 본다.

1. **무엇을 고를 수 있는가** — 자리 · 주인 · 조건으로 걸러진 후보.
2. **고른 것이 적법한가** — ``LEGAL`` · ``ILLEGAL`` · ``UNKNOWN`` 셋이
   끝까지 갈린다.
3. **모르는 것을 고를 수 있다고 하지 않는가** — 가려진 정보는 ``UNKNOWN``
   이고, ``UNKNOWN`` 은 허가가 아니다.
4. **적법하지 않은 대상이 실행으로 새지 않는가.**

AI 는 없다. 무엇을 **선호하는가**는 이 계층의 질문이 아니다.
"""

import ast
import pathlib

import pytest

from engine.condition import ConditionContext, IsMonster, PlayerRef
from engine.cost import CandidateSource, CandidateSet, ChoiceSpec, Selection
from engine.effect.definition import EffectDefinition, EffectProvenance
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.operation import CardOperation, DrawOperation
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.target import (
    PRIMARY_TARGET,
    TargetBinding,
    TargetRef,
    TargetSpec,
)
from engine.effect.targeting import (
    TargetLegality,
    TargetResolver,
    TargetValidation,
    TargetVerdict,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1

FEATHERMAN = 21844576  # 레벨 3 통상 몬스터
DARK_HOLE = 53129443  # 마법 카드
LAB = 2511  # synthetic 정의의 껍데기

PRIMARY = PRIMARY_TARGET


# ======================================================================
# 판 · 도구
# ======================================================================


def new_state(repository) -> GameState:
    """
    p0: 패 3장 · 앞면 몬스터 1 · 묘지 1
    p1: 앞면 몬스터 1 · **뒷면** 마법 1 · 패 3장(가려짐)
    """
    game = GameState.create(
        repository,
        decks=([FEATHERMAN] * 10, [FEATHERMAN] * 6 + [DARK_HOLE] * 4),
    )
    game.draw(MINE, 5)
    game.draw(THEIRS, 5)
    game.move(
        game.player(MINE).hand[0], Zone.MZONE, to_player=MINE,
        position=Position.FACEUP_ATTACK,
    )
    game.move(game.player(MINE).hand[0], Zone.GRAVE, to_player=MINE)
    game.move(
        game.player(THEIRS).hand[0], Zone.MZONE, to_player=THEIRS,
        position=Position.FACEUP_ATTACK,
    )
    game.move(
        game.player(THEIRS).hand[-1], Zone.SZONE, to_player=THEIRS,
        position=Position.FACEDOWN,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def resolver(state: GameState, viewer: int = MINE) -> TargetResolver:
    return TargetResolver(GameStateView.from_state(state, viewer=viewer))


def context(state: GameState, player: int = MINE) -> ConditionContext:
    return ConditionContext(player=player)


def spec(
    *zones: Zone,
    owner: PlayerRef | None = PlayerRef.CONTROLLER,
    minimum: int = 1,
    maximum: int = 1,
    require=None,
) -> TargetSpec:
    return TargetSpec.targeting(
        ChoiceSpec(
            source=CandidateSource(
                zones=frozenset(zones), owner=owner, require=require
            ),
            minimum=minimum,
            maximum=maximum,
        )
    )


def my_monster(state: GameState) -> InstanceId:
    return state.player(MINE).monster_zone[0].instance_id


def their_monster(state: GameState) -> InstanceId:
    return state.player(THEIRS).monster_zone[0].instance_id


def their_facedown(state: GameState) -> InstanceId:
    return state.player(THEIRS).spell_zone[0].instance_id


# ======================================================================
# A. 후보 수집
# ======================================================================


@requires_official_db
def test_my_own_field_is_found(state):
    found = resolver(state).candidates(spec(Zone.MZONE), context(state))

    assert found.eligible == (my_monster(state),)
    assert found.fully_checked


@requires_official_db
def test_the_opponents_field_is_found_when_the_owner_says_so(state):
    found = resolver(state).candidates(
        spec(Zone.MZONE, owner=PlayerRef.OPPONENT), context(state)
    )

    assert found.eligible == (their_monster(state),)


@requires_official_db
def test_both_fields_are_found_when_the_owner_is_not_named(state):
    found = resolver(state).candidates(
        spec(Zone.MZONE, owner=None), context(state)
    )

    assert set(found.eligible) == {my_monster(state), their_monster(state)}


@requires_official_db
def test_the_zone_filter_actually_filters(state):
    grave = resolver(state).candidates(spec(Zone.GRAVE), context(state))
    field = resolver(state).candidates(spec(Zone.MZONE), context(state))

    assert grave.eligible
    assert field.eligible
    assert set(grave.eligible) & set(field.eligible) == set()


@requires_official_db
def test_a_condition_narrows_the_candidates(state):
    """조건 계층을 그대로 쓴다. 후보 전용 규칙 엔진을 만들지 않는다."""
    found = resolver(state).candidates(
        spec(Zone.MZONE, Zone.GRAVE, require=IsMonster()), context(state)
    )

    assert my_monster(state) in found.eligible


@requires_official_db
def test_a_spec_that_asks_for_nothing_finds_nothing(state):
    """
    **대상을 요구하지 않는 효과와 대상을 못 찾은 효과는 다르다** (§9).
    """
    found = resolver(state).candidates(TargetSpec.none(), context(state))

    assert found.eligible == ()
    assert found.unchecked == ()
    assert TargetSpec.none().requires_selection is False


# ======================================================================
# B. LEGAL · ILLEGAL · UNKNOWN
# ======================================================================


@requires_official_db
def test_a_card_in_the_named_zone_is_legal(state):
    target = my_monster(state)

    verdict = resolver(state).validate(
        spec(Zone.MZONE), Selection.of(target), context(state), PRIMARY
    )

    assert verdict.legality is TargetLegality.LEGAL
    assert verdict.permits_selection is True
    assert verdict.verdicts[0].instance == target


@requires_official_db
def test_a_card_in_the_wrong_zone_is_illegal(state):
    """필드를 대상으로 하는 규칙에 묘지의 카드를 고를 수 없다."""
    grave = state.player(MINE).grave[0].instance_id

    verdict = resolver(state).validate(
        spec(Zone.MZONE), Selection.of(grave), context(state), PRIMARY
    )

    assert verdict.legality is TargetLegality.ILLEGAL
    assert verdict.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert verdict.permits_selection is False


@requires_official_db
def test_the_opponents_card_is_illegal_when_the_spec_says_mine(state):
    verdict = resolver(state).validate(
        spec(Zone.MZONE), Selection.of(their_monster(state)), context(state)
    )

    assert verdict.legality is TargetLegality.ILLEGAL
    assert verdict.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE


@requires_official_db
def test_a_face_down_card_whose_identity_matters_is_unknown(state):
    """
    **가려진 정체 때문에 판정할 수 없다.** 조건이 카드 정의를 요구하는데
    상대의 뒷면 카드는 정체가 없다 — ``ILLEGAL`` 로 접지 않는다.
    """
    rule = spec(
        Zone.SZONE, owner=PlayerRef.OPPONENT, require=IsMonster()
    )
    hidden = their_facedown(state)

    found = resolver(state).candidates(rule, context(state))
    verdict = resolver(state).validate(
        rule, Selection.of(hidden), context(state), PRIMARY
    )

    assert hidden in found.undecided
    assert hidden not in found.eligible
    assert verdict.legality is TargetLegality.UNKNOWN
    assert verdict.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert verdict.permits_selection is False


@requires_official_db
def test_a_card_the_viewer_cannot_see_is_unknown_not_illegal(state):
    """없는 것과 숨은 것을 구분하지 못한다."""
    verdict = resolver(state).validate(
        spec(Zone.MZONE), Selection.of(InstanceId(9999)), context(state)
    )

    assert verdict.legality is TargetLegality.UNKNOWN
    assert verdict.code is ValidationCode.HIDDEN_CARD


def test_a_verdict_cannot_be_read_as_true_or_false():
    verdict = TargetVerdict(InstanceId(1), TargetLegality.UNKNOWN)
    validation = TargetValidation(TargetLegality.UNKNOWN)

    with pytest.raises(TypeError):
        bool(verdict)
    with pytest.raises(TypeError):
        bool(validation)


def test_only_legal_permits_selection():
    for legality in TargetLegality:
        assert legality.permits_selection is (legality is TargetLegality.LEGAL)


@requires_official_db
def test_a_certain_violation_beats_a_missing_judgement(state):
    """
    ``ILLEGAL`` 이 ``UNKNOWN`` 을 이긴다 — 확실한 위반이 하나라도 있으면
    나머지를 몰라도 위반이다.
    """
    rule = spec(
        Zone.MZONE, Zone.SZONE, owner=None, require=IsMonster(), maximum=2
    )
    grave_card = state.player(MINE).grave[0].instance_id

    verdict = resolver(state).validate(
        rule,
        Selection.of(their_facedown(state), grave_card),
        context(state),
        PRIMARY,
    )

    assert verdict.legality is TargetLegality.ILLEGAL
    assert {v.legality for v in verdict.verdicts} == {
        TargetLegality.UNKNOWN,
        TargetLegality.ILLEGAL,
    }


# ======================================================================
# C. 장수
# ======================================================================


@requires_official_db
def test_exactly_one_means_exactly_one(state):
    rule = spec(Zone.MZONE, owner=None, minimum=1, maximum=1)
    both = Selection.of(my_monster(state), their_monster(state))

    assert resolver(state).validate(
        rule, Selection.of(my_monster(state)), context(state)
    ).legality is TargetLegality.LEGAL

    too_many = resolver(state).validate(rule, both, context(state))
    assert too_many.legality is TargetLegality.ILLEGAL
    assert too_many.code is ValidationCode.TOO_MANY_SELECTED

    too_few = resolver(state).validate(rule, Selection(), context(state))
    assert too_few.legality is TargetLegality.ILLEGAL
    assert too_few.code is ValidationCode.TOO_FEW_SELECTED


@requires_official_db
def test_up_to_n_accepts_fewer(state):
    rule = spec(Zone.MZONE, owner=None, minimum=1, maximum=2)

    one = resolver(state).validate(
        rule, Selection.of(my_monster(state)), context(state)
    )
    two = resolver(state).validate(
        rule,
        Selection.of(my_monster(state), their_monster(state)),
        context(state),
    )

    assert one.legality is TargetLegality.LEGAL
    assert two.legality is TargetLegality.LEGAL


@requires_official_db
def test_an_optional_target_accepts_nothing_at_all(state):
    rule = spec(Zone.MZONE, minimum=0, maximum=1)

    verdict = resolver(state).validate(rule, Selection(), context(state))

    assert verdict.legality is TargetLegality.LEGAL
    assert rule.choice.is_optional


@requires_official_db
def test_the_same_card_cannot_be_chosen_twice(state):
    rule = spec(Zone.MZONE, maximum=2)
    target = my_monster(state)

    verdict = resolver(state).validate(
        rule, Selection.of(target, target), context(state)
    )

    assert verdict.legality is TargetLegality.ILLEGAL
    assert verdict.code is ValidationCode.DUPLICATE_SELECTION


@requires_official_db
def test_not_choosing_at_all_is_not_the_same_as_choosing_nothing(state):
    """
    ``None`` 은 "아직 고르지 않았다" 이고 빈 선택은 "고를 것이 없다고
    골랐다" 다. 대상을 요구하는 규칙에서는 둘 다 최소 장수를 못 채운다.
    """
    rule = spec(Zone.MZONE)

    assert resolver(state).validate(rule, None, context(state)).code is (
        ValidationCode.TOO_FEW_SELECTED
    )
    assert rule.is_pending(None) is True
    assert TargetSpec.none().is_pending(None) is False


# ======================================================================
# D. 후보가 충분한가
# ======================================================================


@requires_official_db
def test_enough_candidates_is_legal(state):
    verdict = resolver(state).availability(spec(Zone.MZONE), context(state))

    assert verdict.legality is TargetLegality.LEGAL


@requires_official_db
def test_no_candidates_anywhere_visible_is_illegal(state):
    """
    **전부 확인했을 때만** "후보가 없다" 고 말한다.
    """
    empty = GameState.create(decks=([], []))
    verdict = TargetResolver(
        GameStateView.from_state(empty, viewer=MINE)
    ).availability(spec(Zone.MZONE), context(empty))

    assert verdict.legality is TargetLegality.ILLEGAL
    assert verdict.code is ValidationCode.NO_CANDIDATES


@requires_official_db
def test_a_concealed_zone_leaves_the_count_unknown(state):
    """
    **STRUCTURAL-15.** 상대의 패는 통째로 가려져 있다. 후보가 0장으로
    보인다고 "후보가 없다" 고 답하면 모르는 것을 거짓으로 접는 것이다.
    """
    rule = spec(Zone.HAND, owner=PlayerRef.OPPONENT)

    found = resolver(state).candidates(rule, context(state))
    verdict = resolver(state).availability(rule, context(state))

    assert found.eligible == ()
    assert found.fully_checked is False
    assert any("HAND" in note for note in found.unchecked)
    assert verdict.legality is TargetLegality.UNKNOWN
    assert verdict.code is ValidationCode.INFORMATION_UNAVAILABLE


@requires_official_db
def test_what_could_not_be_looked_at_travels_with_the_verdict(state):
    verdict = resolver(state).validate(
        spec(Zone.HAND, owner=PlayerRef.OPPONENT),
        Selection.of(InstanceId(9999)),
        context(state),
        PRIMARY,
    )

    assert verdict.unchecked
    assert verdict.fully_checked is False


# ======================================================================
# E. 실행 연결
# ======================================================================


def synthetic(*operations, target: TargetSpec | None = None, ordinal: int = 0):
    """
    **synthetic 정의**다 — 실제 카드의 의미를 주장하지 않는다.
    대상 계층이 실행 경로에서 지켜지는지만 본다.
    """
    needs = any(operation.target_refs for operation in operations)
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        operations=tuple(operations),
        targets=(
            TargetBinding.single(target or spec(Zone.MZONE, owner=None))
            if needs
            else ()
        ),
        provenance=EffectProvenance.hand_written(verified=True, note="대상 계층 시험"),
    )


def execute(state: GameState, definition: EffectDefinition, *chosen, destruction=None):
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        destruction=destruction,
    )
    return executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref,
            controller=MINE,
            selections=(
                (TargetSelection(PRIMARY, Selection(chosen=tuple(chosen))),)
                if chosen
                else ()
            ),
        ),
    )


@requires_official_db
def test_a_legal_target_reaches_the_operation(state):
    target = their_monster(state)
    definition = synthetic(CardOperation.send_to_grave(PRIMARY))

    result = execute(state, definition, target)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(target).zone is Zone.GRAVE


@requires_official_db
def test_the_same_target_layer_serves_a_destruction(state):
    """
    대상 계층은 ``DESTROY`` 를 **모른다.** 같은 규칙이 파괴에도 쓰인다.
    """
    from engine.effect.semantics import DeclaredDestructionRuling

    target = their_monster(state)
    definition = synthetic(CardOperation.destroy(PRIMARY))

    result = execute(
        state,
        definition,
        target,
        destruction=DeclaredDestructionRuling(destructible=frozenset({target})),
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(target).zone is Zone.GRAVE


@requires_official_db
def test_an_illegal_target_never_reaches_the_operation(state):
    """규칙이 필드를 말하는데 묘지의 카드를 골랐다."""
    grave = state.player(MINE).grave[0].instance_id
    definition = synthetic(CardOperation.banish(PRIMARY))
    before = state.state_hash()

    result = execute(state, definition, grave)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert result.applied == ()
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_an_unknown_target_never_reaches_the_operation(state):
    """
    **모르는 것을 실행으로 바꾸지 않는다.** ``INVALID_TARGET`` 과 다른
    상태로 멈춘다.
    """
    definition = synthetic(
        CardOperation.banish(PRIMARY),
        target=spec(Zone.SZONE, owner=PlayerRef.OPPONENT, require=IsMonster()),
    )
    before = state.state_hash()

    result = execute(state, definition, their_facedown(state))

    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_too_many_targets_never_reach_the_operation(state):
    definition = synthetic(
        CardOperation.banish(PRIMARY),
        target=spec(Zone.MZONE, owner=None, minimum=1, maximum=1),
    )
    before = state.state_hash()

    result = execute(state, definition, my_monster(state), their_monster(state))

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_MANY_SELECTED
    assert state.state_hash() == before


@requires_official_db
def test_an_effect_with_no_target_still_runs(state):
    """
    §9 — 대상을 요구하지 않는 효과를 억지로 대상 효과로 만들지 않는다.
    """
    definition = synthetic(DrawOperation(count=1))

    result = execute(state, definition)

    assert definition.targets == ()
    assert result.status is ResolutionStatus.RESOLVED


@requires_official_db
def test_a_failed_target_check_stops_the_whole_effect(state):
    """앞에 멀쩡한 드로우가 있어도 뒤의 대상이 틀리면 뽑지 않는다."""
    grave = state.player(MINE).grave[0].instance_id
    definition = synthetic(DrawOperation(count=1), CardOperation.banish(PRIMARY))
    hand = len(state.player(MINE).hand)
    before = state.state_hash()

    result = execute(state, definition, grave)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert len(state.player(MINE).hand) == hand
    assert state.state_hash() == before


# ======================================================================
# F. 관측 경계
# ======================================================================


@requires_official_db
def test_the_resolver_refuses_a_mutable_board(state):
    with pytest.raises(TypeError):
        TargetResolver(state)


@requires_official_db
def test_the_opponents_hand_never_becomes_a_candidate(state):
    """상대의 패는 관측에 실리지 않으므로 후보가 될 수 없다."""
    found = resolver(state).candidates(
        spec(Zone.HAND, owner=PlayerRef.OPPONENT), context(state)
    )

    assert found.eligible == ()
    assert found.undecided == ()
    assert found.unchecked  # 대신 "못 봤다" 가 남는다


@requires_official_db
def test_no_hidden_card_id_leaks_through_a_verdict(state):
    verdict = resolver(state).validate(
        spec(Zone.SZONE, owner=PlayerRef.OPPONENT),
        Selection.of(their_facedown(state)),
        context(state),
        PRIMARY,
    )
    text = str(verdict.to_dict())

    assert str(DARK_HOLE) not in text
    for hidden in state.player(THEIRS).hand:
        assert str(hidden.card_id) not in text


@requires_official_db
def test_a_face_down_card_can_still_be_pointed_at(state):
    """
    정체는 가려도 **자리는 보인다.** 상대의 세트 카드를 지목할 수 있어야
    공격도 파괴도 표현된다.
    """
    verdict = resolver(state).validate(
        spec(Zone.SZONE, owner=PlayerRef.OPPONENT),
        Selection.of(their_facedown(state)),
        context(state),
    )

    assert verdict.legality is TargetLegality.LEGAL


# ======================================================================
# G. 결정론
# ======================================================================


@requires_official_db
def test_the_candidate_order_is_the_same_every_time(repository):
    first, second = new_state(repository), new_state(repository)
    rule = spec(Zone.MZONE, Zone.GRAVE, Zone.HAND, owner=None, maximum=9)

    left = TargetResolver(
        GameStateView.from_state(first, viewer=MINE)
    ).candidates(rule, context(first))
    right = TargetResolver(
        GameStateView.from_state(second, viewer=MINE)
    ).candidates(rule, context(second))

    assert left.eligible == right.eligible
    assert left.canonical_state() == right.canonical_state()


@requires_official_db
def test_the_candidate_order_does_not_depend_on_set_iteration(state):
    """
    같은 규칙을 여러 번 물어도 같은 순서다 — ``frozenset`` 을 그대로
    순회하면 순서가 흔들린다.
    """
    rule = spec(Zone.MZONE, Zone.GRAVE, Zone.HAND, owner=None, maximum=9)
    answers = {
        resolver(state).candidates(rule, context(state)).canonical_state()
        for _ in range(5)
    }

    assert len(answers) == 1


@requires_official_db
def test_the_same_verdict_every_time(state):
    rule = spec(Zone.MZONE)
    target = my_monster(state)

    left = resolver(state).validate(rule, Selection.of(target), context(state))
    right = resolver(state).validate(rule, Selection.of(target), context(state))

    assert left.canonical_state() == right.canonical_state()


@requires_official_db
def test_resolving_targets_never_changes_the_board(state):
    before = state.state_hash()
    rule = spec(Zone.MZONE, owner=None, maximum=2)

    for _ in range(3):
        resolver(state).candidates(rule, context(state))
        resolver(state).availability(rule, context(state))
        resolver(state).validate(rule, Selection.of(my_monster(state)), context(state))

    assert state.state_hash() == before


@requires_official_db
def test_a_clone_answers_the_same_way(state):
    copy = state.clone()
    rule = spec(Zone.MZONE, owner=None, maximum=2)

    assert resolver(state).candidates(rule, context(state)).canonical_state() == (
        resolver(copy).candidates(rule, context(copy)).canonical_state()
    )


# ======================================================================
# H. 계층 경계
# ======================================================================


def test_the_target_layer_knows_nothing_about_meanings():
    """
    §14 — 대상 계층에 ``DESTROY`` 전용 코드가 들어가면 같은 규칙을 다른
    의미에 쓸 수 없게 된다.
    """
    source = pathlib.Path("engine/effect/targeting.py").read_text("utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "engine.effect.semantics" not in imported
    assert "engine.effect.operation" not in imported

    # 설명문에 이름이 적혀 있는 것과 **쓰는** 것은 다르다 — 구조로 본다.
    used = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    for forbidden in (
        "DESTROY",
        "SEND_TO_GRAVE",
        "DISCARD",
        "OperationKind",
        "MoveOperation",
        "CardOperation",
    ):
        assert forbidden not in used


def test_the_target_layer_reuses_the_candidate_resolver():
    """후보를 세는 코드를 두 벌 만들지 않는다."""
    source = pathlib.Path("engine/effect/targeting.py").read_text("utf-8")
    tree = ast.parse(source)
    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }

    assert "CandidateResolver" not in defined
    assert "CandidateSet" not in defined
    assert "CandidateResolver" in source


def test_the_target_layer_changes_nothing():
    tree = ast.parse(pathlib.Path("engine/effect/targeting.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert not any(module.startswith("engine.state") for module in imported)
    assert "engine.chain" not in imported
    assert "engine.event_pipeline" not in imported
    for forbidden in ("move", "draw", "change_life"):
        assert forbidden not in called


def test_the_target_layer_makes_no_choice_of_its_own():
    """
    §7 — 무엇을 고를지는 엔진의 질문이 아니다. 엔진은 "이 대상이
    적법한가" 만 답한다.
    """
    source = pathlib.Path("engine/effect/targeting.py").read_text("utf-8")

    for forbidden in ("def choose", "def select_best", "score", "policy", "random"):
        assert forbidden not in source


def test_the_chain_layer_does_not_pick_targets():
    """§15 — 체인은 무엇을 언제만 정한다."""
    tree = ast.parse(pathlib.Path("engine/chain.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "engine.effect.targeting" not in imported


def test_the_trigger_layer_does_not_pick_targets():
    tree = ast.parse(pathlib.Path("engine/trigger.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "engine.effect.targeting" not in imported
