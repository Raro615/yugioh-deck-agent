"""
engine/action_validation.py — 판 위의 사실까지 보는 검증 (Phase 2-B-2).

Phase 2-A 는 Action 의 **모양**만 봤다. 이제 관측을 읽고 확실한 위반을
잡아낸다 — 남의 카드를 소환하려 한다, 필드의 카드를 다시 소환하려 한다,
메인 페이즈에 공격을 선언한다, 몬스터 존이 꽉 찼다.

**아직 ``VALID`` 는 나오지 않는다.** 소환 절차 · 타이밍 · 체인이 없어서
마지막 한 걸음을 확인할 수 없기 때문이다. 그것이 정직한 상태다.
"""

import dataclasses
import json

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_target import ActionTarget
from engine.action_validation import (
    ActionValidator,
    ActionValidity,
    ValidationCode,
    ValidationResult,
)
from engine.condition import ConditionContext
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

BLUE_EYES = 89631139  # LIGHT / DRAGON / 레벨 8 / 3000
DARK_HOLE = 53129443  # 마법 카드
RED_EYES = 74677422  # 상대 전용
KUKLOK = 2511  # 라뷰린스 쿠클락 — 효과 3개


@pytest.fixture
def state(repository) -> GameState:
    """
    p0: 패 3장 · 앞면 몬스터 1 · 뒷면 마법 1
    p1: 패 3장 · 앞면 몬스터 1
    """
    game = GameState.create(
        repository,
        decks=([BLUE_EYES, DARK_HOLE] * 8, [RED_EYES, KUKLOK] * 8),
    )
    game.draw(0, 5)
    game.draw(1, 4)
    game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.move(game.player(0).hand[0], Zone.SZONE, position=Position.FACEDOWN)
    game.move(game.player(1).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    return game


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=0)


@pytest.fixture
def validator(view) -> ActionValidator:
    return ActionValidator(view)


@pytest.fixture
def my_monster(state) -> InstanceId:
    return state.player(0).monster_zone[0].instance_id


@pytest.fixture
def their_monster(state) -> InstanceId:
    return state.player(1).monster_zone[0].instance_id


@pytest.fixture
def my_hand_monster(state) -> InstanceId:
    return next(
        c.instance_id for c in state.player(0).hand if c.card_id == BLUE_EYES
    )


@pytest.fixture
def my_hand_spell(state) -> InstanceId:
    return next(
        c.instance_id for c in state.player(0).hand if c.card_id == DARK_HOLE
    )


def _battle(state) -> GameStateView:
    state.turn.set_phase(Phase.BATTLE)
    return GameStateView.from_state(state, viewer=0)


# ======================================================================
# 검증기는 관측만 받는다
# ======================================================================


def test_validator_refuses_a_raw_game_state(state):
    """
    ``GameState`` 를 쥐면 상대의 패와 덱이 보인다. 판정이 "없다" 와
    "안 보인다" 를 구분해 버리면, 검증을 반복하는 것만으로 상대 손패를
    탐지할 수 있다.
    """
    with pytest.raises(TypeError) as excinfo:
        ActionValidator(state)
    assert "GameStateView" in str(excinfo.value)


def test_validator_never_touches_the_card_repository():
    """정의는 관측이 실어 준 것만 읽는다 (§10)."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("engine/action_validation.py").read_text("utf-8"))
    offenders = [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").split(".")[0] in {"core", "analysis"}
    ]
    assert offenders == [], f"검증기가 {offenders} 를 가져옵니다."


def test_validator_exposes_no_mutation_path(validator):
    for forbidden in ("execute", "apply", "resolve", "move", "draw", "state"):
        assert not hasattr(validator, forbidden), (
            f"ActionValidator.{forbidden} 이 생겼습니다. 검증과 실행은 "
            "분리되어야 합니다."
        )


# ======================================================================
# 구조 검증 (§16 의 1~9)
# ======================================================================


@requires_official_db
def test_a_well_formed_action_passes_the_structure_layer(validator, my_hand_monster):
    result = validator.validate_structure(
        PlayerAction.normal_summon(0, my_hand_monster)
    )
    assert result.validity is ActionValidity.VALID
    assert result.code is ValidationCode.OK


def test_an_impossible_actor_is_refused_at_construction():
    """모양 자체가 성립하지 않으므로 Action 을 만들 수조차 없다."""
    from engine.action import MalformedAction

    with pytest.raises(MalformedAction):
        PlayerAction.end_phase(actor=2)


def test_the_validator_still_checks_the_actor_itself(validator):
    """
    생성자를 우회해 만든 Action 도 막는다. 검증기는 입력이 올바르게
    만들어졌다고 **가정하지 않는다.**
    """
    action = PlayerAction.end_phase(0)
    object.__setattr__(action, "actor", 7)
    result = validator.validate_structure(action)
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.ACTOR_INVALID


@requires_official_db
def test_missing_and_forbidden_fields_are_invalid(validator, my_hand_monster):
    cases = [
        (
            PlayerAction(kind=PlayerActionKind.NORMAL_SUMMON, actor=0),
            ValidationCode.SOURCE_REQUIRED,
        ),
        (
            PlayerAction(
                kind=PlayerActionKind.END_PHASE, actor=0, source=my_hand_monster
            ),
            ValidationCode.SOURCE_FORBIDDEN,
        ),
        (
            PlayerAction(
                kind=PlayerActionKind.ACTIVATE_EFFECT, actor=0, source=my_hand_monster
            ),
            ValidationCode.EFFECT_REF_REQUIRED,
        ),
        (
            PlayerAction(
                kind=PlayerActionKind.NORMAL_SUMMON,
                actor=0,
                source=my_hand_monster,
                effect_ref=EffectRef(BLUE_EYES, 0),
            ),
            ValidationCode.EFFECT_REF_FORBIDDEN,
        ),
        (
            PlayerAction(kind=PlayerActionKind.CHANGE_PHASE, actor=0),
            ValidationCode.PHASE_REQUIRED,
        ),
        (
            PlayerAction(
                kind=PlayerActionKind.NORMAL_SUMMON,
                actor=0,
                source=my_hand_monster,
                phase=Phase.MAIN1,
            ),
            ValidationCode.PHASE_FORBIDDEN,
        ),
    ]
    for action, code in cases:
        result = validator.validate(action)
        assert result.validity is ActionValidity.INVALID, action.kind
        assert result.code is code, f"{action.kind}: {result}"


@requires_official_db
def test_target_count_and_kind_are_checked(validator, my_monster, their_monster):
    no_target = PlayerAction(
        kind=PlayerActionKind.ATTACK, actor=0, source=my_monster
    )
    assert validator.validate(no_target).code is ValidationCode.TARGET_COUNT_MISMATCH

    two = PlayerAction(
        kind=PlayerActionKind.ATTACK,
        actor=0,
        source=my_monster,
        targets=(
            ActionTarget.instance(their_monster),
            ActionTarget.player_target(1),
        ),
    )
    assert validator.validate(two).code is ValidationCode.TARGET_COUNT_MISMATCH

    zone_target = PlayerAction.attack(
        0, my_monster, ActionTarget.zone_target(1, Zone.MZONE, 0)
    )
    assert validator.validate(zone_target).code is ValidationCode.TARGET_KIND_INVALID


def test_impossible_players_and_slots_cannot_be_named_at_all():
    """
    ``ActionTarget`` 이 생성 단계에서 막는다. 존재할 수 없는 자리를
    가리키는 Action 은 만들어지지 않는다.
    """
    with pytest.raises(ValueError):
        ActionTarget.player_target(5)
    with pytest.raises(ValueError):
        ActionTarget.zone_target(0, Zone.MZONE, 5)
    with pytest.raises(ValueError):
        ActionTarget.zone_target(0, Zone.EMZONE, 1)
    with pytest.raises(ValueError):
        ActionTarget.zone_target(0, Zone.HAND, 0)


@requires_official_db
def test_effect_ref_must_name_the_source_card(validator, my_monster):
    wrong = PlayerAction.activate_effect(0, my_monster, EffectRef(RED_EYES, 0))
    result = validator.validate(wrong)
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.EFFECT_REF_CARD_MISMATCH


@requires_official_db
def test_an_effect_ordinal_beyond_the_card_is_invalid(repository):
    """
    라뷰린스 쿠클락은 효과가 3개다. 4번째 효과는 없다.

    ``CardDefinitionView.effect_count`` 가 스크립트 내용을 내보내지 않고
    개수만 싣기 때문에 판정할 수 있다.
    """
    game = GameState.create(repository, decks=([KUKLOK], []))
    card = game.create_instance(KUKLOK, owner=0, zone=Zone.MZONE)
    card.set_position(Position.FACEUP_ATTACK)
    view = GameStateView.from_state(game, viewer=0)
    validator = ActionValidator(view)

    assert view.find(card.instance_id).definition.effect_count == 3

    inside = PlayerAction.activate_effect(0, card.instance_id, EffectRef(KUKLOK, 2))
    assert validator.validate(inside).validity is ActionValidity.UNKNOWN

    outside = PlayerAction.activate_effect(0, card.instance_id, EffectRef(KUKLOK, 3))
    result = validator.validate(outside)
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.EFFECT_REF_OUT_OF_RANGE


@requires_official_db
def test_an_empty_effect_list_is_unknown_not_invalid(repository, my_monster):
    """
    ``effect_count == 0`` 은 "효과가 없다" 를 뜻하지 않는다. 공유 라이브러리
    팩토리로 효과를 만드는 카드 195장도 0 이다 (ADR-006). 구분할 수 없으므로
    **모른다**고 답한다.
    """
    game = GameState.create(repository, decks=([BLUE_EYES], []))
    card = game.create_instance(BLUE_EYES, owner=0, zone=Zone.MZONE)
    card.set_position(Position.FACEUP_ATTACK)
    view = GameStateView.from_state(game, viewer=0)

    assert view.find(card.instance_id).definition.effect_count == 0
    result = ActionValidator(view).validate(
        PlayerAction.activate_effect(0, card.instance_id, EffectRef(BLUE_EYES, 0))
    )
    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.EFFECT_LIST_UNRELIABLE
    assert not result.permits_execution


# ======================================================================
# ActionKind 별 (§16 의 10~19)
# ======================================================================


@requires_official_db
def test_normal_summon_rejects_a_card_the_actor_does_not_control(
    validator, their_monster
):
    result = validator.validate(PlayerAction.normal_summon(0, their_monster))
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.SOURCE_NOT_CONTROLLED


@requires_official_db
def test_normal_summon_rejects_a_card_already_on_the_field(validator, my_monster):
    result = validator.validate(PlayerAction.normal_summon(0, my_monster))
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.SOURCE_WRONG_ZONE


@requires_official_db
def test_normal_summon_rejects_a_spell_card(validator, my_hand_spell):
    result = validator.validate(PlayerAction.normal_summon(0, my_hand_spell))
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.SOURCE_WRONG_CARD_TYPE


@requires_official_db
def test_normal_summon_rejects_a_full_monster_zone(state, my_hand_monster):
    for _ in range(4):
        state.create_instance(BLUE_EYES, owner=0, zone=Zone.MZONE)
    view = GameStateView.from_state(state, viewer=0)
    assert view.me.monster_zone.size == 5

    result = ActionValidator(view).validate(
        PlayerAction.normal_summon(0, my_hand_monster)
    )
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.ZONE_FULL


@requires_official_db
def test_normal_summon_rejects_the_non_turn_player(state):
    """p1 의 턴이 아닌데 p1 이 소환하려 한다."""
    view = GameStateView.from_state(state, viewer=1)
    hand_card = state.player(1).hand[0].instance_id
    result = ActionValidator(view).validate(
        PlayerAction.normal_summon(1, hand_card)
    )
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.NOT_TURN_PLAYER


@requires_official_db
def test_a_legitimate_normal_summon_is_unknown_not_valid(validator, my_hand_monster):
    """
    확인할 수 있는 것은 전부 통과했다. 그래도 허가가 아니다 — 릴리스 ·
    소환 제한 · 소환권을 판정할 계층이 아직 없다.
    """
    result = validator.validate(PlayerAction.normal_summon(0, my_hand_monster))
    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "summon-procedure" in result.missing_rule
    assert not result.permits_execution


@requires_official_db
def test_set_monster_follows_the_same_checks(validator, my_hand_spell, their_monster):
    assert (
        validator.validate(PlayerAction.set_monster(0, my_hand_spell)).code
        is ValidationCode.SOURCE_WRONG_CARD_TYPE
    )
    assert (
        validator.validate(PlayerAction.set_monster(0, their_monster)).code
        is ValidationCode.SOURCE_NOT_CONTROLLED
    )


@requires_official_db
def test_set_spell_trap_rejects_a_monster(validator, my_hand_monster, my_hand_spell):
    result = validator.validate(PlayerAction.set_spell_trap(0, my_hand_monster))
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.SOURCE_WRONG_CARD_TYPE

    ok = validator.validate(PlayerAction.set_spell_trap(0, my_hand_spell))
    assert ok.validity is ActionValidity.UNKNOWN


@requires_official_db
def test_set_spell_trap_rejects_a_full_zone(state, my_hand_spell):
    for _ in range(4):
        state.create_instance(DARK_HOLE, owner=0, zone=Zone.SZONE)
    view = GameStateView.from_state(state, viewer=0)
    assert view.me.spell_zone.size == 5

    result = ActionValidator(view).validate(
        PlayerAction.set_spell_trap(0, my_hand_spell)
    )
    assert result.code is ValidationCode.ZONE_FULL


@requires_official_db
def test_change_position_needs_a_card_in_a_monster_zone(
    validator, my_monster, my_hand_monster, their_monster
):
    assert (
        validator.validate(PlayerAction.change_position(0, my_monster)).validity
        is ActionValidity.UNKNOWN
    )
    assert (
        validator.validate(PlayerAction.change_position(0, my_hand_monster)).code
        is ValidationCode.SOURCE_WRONG_ZONE
    )
    assert (
        validator.validate(PlayerAction.change_position(0, their_monster)).code
        is ValidationCode.SOURCE_NOT_CONTROLLED
    )


@requires_official_db
def test_activate_card_does_not_require_it_to_be_your_turn(state):
    """
    상대 턴에 발동하는 함정과 퀵 효과가 정상이다. 그러므로 발동에
    ``IsTurnPlayer`` 를 걸면 안 된다.
    """
    view = GameStateView.from_state(state, viewer=1)
    their_card = state.player(1).monster_zone[0].instance_id
    result = ActionValidator(view).validate(
        PlayerAction.activate_card(1, their_card)
    )
    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is not ValidationCode.NOT_TURN_PLAYER


@requires_official_db
def test_activate_rejects_someone_elses_card(validator, their_monster):
    assert (
        validator.validate(PlayerAction.activate_card(0, their_monster)).code
        is ValidationCode.SOURCE_NOT_CONTROLLED
    )


@requires_official_db
def test_attack_outside_the_battle_phase_is_invalid(validator, my_monster):
    result = validator.validate(PlayerAction.attack_directly(0, my_monster))
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.WRONG_PHASE


@requires_official_db
def test_attack_in_the_battle_phase_reaches_the_missing_rule(state, my_monster):
    view = _battle(state)
    result = ActionValidator(view).validate(
        PlayerAction.attack_directly(0, my_monster)
    )
    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "attack-declaration" in result.missing_rule


@requires_official_db
def test_attacking_yourself_is_invalid(state, my_monster):
    view = _battle(state)
    action = PlayerAction.attack(0, my_monster, ActionTarget.player_target(0))
    result = ActionValidator(view).validate(action)
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.TARGET_NOT_OPPONENT


@requires_official_db
def test_attacking_your_own_monster_is_invalid(state, my_monster):
    view = _battle(state)
    other = state.create_instance(BLUE_EYES, owner=0, zone=Zone.MZONE)
    other.set_position(Position.FACEUP_ATTACK)
    view = GameStateView.from_state(state, viewer=0)

    action = PlayerAction.attack(
        0, my_monster, ActionTarget.instance(other.instance_id)
    )
    result = ActionValidator(view).validate(action)
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.TARGET_SELF_CONTROLLED


@requires_official_db
def test_attacking_a_card_outside_a_monster_zone_is_invalid(state, my_monster):
    _battle(state)
    buried = state.player(1).deck[0]
    state.move(buried, Zone.GRAVE, to_player=1)
    view = GameStateView.from_state(state, viewer=0)

    action = PlayerAction.attack(
        0, my_monster, ActionTarget.instance(buried.instance_id)
    )
    result = ActionValidator(view).validate(action)
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.TARGET_WRONG_ZONE


@requires_official_db
def test_attacking_with_a_card_that_is_not_on_the_field(state, my_hand_monster):
    view = _battle(state)
    result = ActionValidator(view).validate(
        PlayerAction.attack_directly(0, my_hand_monster)
    )
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.SOURCE_WRONG_ZONE


@requires_official_db
def test_change_phase_needs_the_turn_player(state):
    view = GameStateView.from_state(state, viewer=1)
    result = ActionValidator(view).validate(
        PlayerAction.change_phase(1, Phase.MAIN1)
    )
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.NOT_TURN_PLAYER


@requires_official_db
def test_changing_to_the_phase_you_are_already_in_is_invalid(validator, view):
    result = validator.validate(PlayerAction.change_phase(0, view.phase))
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.PHASE_UNCHANGED


@requires_official_db
def test_change_phase_to_a_different_phase_is_unknown(validator):
    result = validator.validate(PlayerAction.change_phase(0, Phase.MAIN1))
    assert result.validity is ActionValidity.UNKNOWN
    assert "turn-progression" in result.missing_rule


@requires_official_db
def test_end_phase_needs_the_turn_player(state):
    view = GameStateView.from_state(state, viewer=1)
    assert (
        ActionValidator(view).validate(PlayerAction.end_phase(1)).code
        is ValidationCode.NOT_TURN_PLAYER
    )
    mine = GameStateView.from_state(state, viewer=0)
    assert (
        ActionValidator(mine).validate(PlayerAction.end_phase(0)).validity
        is ActionValidity.UNKNOWN
    )


@requires_official_db
def test_pass_has_no_rules_to_check_yet(validator):
    """우선권 계층이 없다. 지금 판정할 수 있는 것이 하나도 없다."""
    result = validator.validate(PlayerAction.passing(0))
    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "priority" in result.missing_rule


@requires_official_db
def test_nothing_is_allowed_once_the_duel_is_over(state, my_hand_monster):
    state.set_result(winner=0, reason="테스트")
    view = GameStateView.from_state(state, viewer=0)
    result = ActionValidator(view).validate(
        PlayerAction.normal_summon(0, my_hand_monster)
    )
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.DUEL_ALREADY_OVER


# ======================================================================
# UNKNOWN (§16 의 20~23)
# ======================================================================


@requires_official_db
def test_no_action_kind_can_be_executed_yet(state, my_monster, my_hand_monster):
    """
    Phase 2-B-2 의 정의상, 어떤 Action 도 허가를 받지 못한다. 하나라도
    통과하면 실행 계층이 없는데 실행이 열린 것이다.
    """
    _battle(state)
    view = GameStateView.from_state(state, viewer=0)
    validator = ActionValidator(view)
    for action in (
        PlayerAction.normal_summon(0, my_hand_monster),
        PlayerAction.set_monster(0, my_hand_monster),
        PlayerAction.set_spell_trap(0, my_hand_monster),
        PlayerAction.activate_card(0, my_monster),
        PlayerAction.activate_effect(0, my_monster, EffectRef(BLUE_EYES, 0)),
        PlayerAction.change_position(0, my_monster),
        PlayerAction.attack_directly(0, my_monster),
        PlayerAction.change_phase(0, Phase.MAIN2),
        PlayerAction.end_phase(0),
        PlayerAction.passing(0),
    ):
        result = validator.validate(action)
        assert not result.permits_execution, f"{action.kind} 가 허가를 받았습니다."
        assert result.validity is not ActionValidity.VALID


@requires_official_db
def test_information_unknown_is_not_confused_with_rule_unknown(state):
    """
    "모른다" 의 두 원인이 코드로 구분된다. 하나는 정보가 없어서고,
    다른 하나는 규칙이 없어서다.
    """
    no_repo = GameState.create(decks=([1000], []))
    card = no_repo.player(0).deck[0]
    no_repo.move(card, Zone.HAND)
    view = GameStateView.from_state(no_repo, viewer=0)
    information = ActionValidator(view).validate(
        PlayerAction.normal_summon(0, card.instance_id)
    )
    assert information.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert information.notes  # 조건 계층이 왜 모르는지 전한다

    with_repo = GameStateView.from_state(state, viewer=0)
    rule = ActionValidator(with_repo).validate(PlayerAction.passing(0))
    assert rule.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert rule.missing_rule


@requires_official_db
def test_a_certain_violation_beats_missing_information(state):
    """
    ``FALSE`` 가 ``UNKNOWN`` 을 이긴다. 카드 정의를 못 읽어도, 남의 카드를
    소환하려 한다는 것은 확실하다.
    """
    no_repo = GameState.create(decks=([1000], [2000]))
    theirs = no_repo.player(1).deck[0]
    no_repo.move(theirs, Zone.MZONE, to_player=1, position=Position.FACEUP_ATTACK)
    view = GameStateView.from_state(no_repo, viewer=0)

    result = ActionValidator(view).validate(
        PlayerAction.normal_summon(0, theirs.instance_id)
    )
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.SOURCE_NOT_CONTROLLED


def test_unknown_never_grants_permission():
    assert not ValidationResult.unknown(
        ValidationCode.RULE_NOT_IMPLEMENTED, "모름"
    ).permits_execution
    assert not ValidationResult.invalid(
        ValidationCode.ZONE_FULL, "꽉 참"
    ).permits_execution
    assert ValidationResult.valid().permits_execution


def test_validation_result_cannot_be_used_as_a_boolean():
    """``if result:`` 로 UNKNOWN 이 허가가 되는 길을 막는다."""
    result = ValidationResult.unknown(ValidationCode.HIDDEN_CARD, "모름")
    with pytest.raises(TypeError):
        bool(result)
    with pytest.raises(TypeError):
        if result:  # noqa: SIM103
            pass


# ======================================================================
# Hidden information (§16 의 30)
# ======================================================================


@requires_official_db
def test_the_validator_reveals_nothing_about_a_hidden_card(state):
    """
    상대 패의 카드를 가리켜도, 판정 어디에도 그 카드의 정체가 나오면 안 된다.
    """
    hidden = state.player(1).hand[0]
    view = GameStateView.from_state(state, viewer=0)
    result = ActionValidator(view).validate(
        PlayerAction.normal_summon(0, hidden.instance_id)
    )

    assert result.validity is ActionValidity.UNKNOWN
    text = json.dumps(result.to_dict(), ensure_ascii=False)
    assert str(hidden.card_id) not in text
    definition = state.repository.get(hidden.card_id)
    assert definition.name not in text


@requires_official_db
def test_a_face_down_card_of_the_opponent_stays_anonymous(state):
    """
    뒷면 카드는 자리와 컨트롤러가 보이므로 "남의 카드" 라고 판정할 수 있다.
    그렇다고 정체가 새면 안 된다.
    """
    theirs = state.player(1).hand[0]
    state.move(theirs, Zone.SZONE, to_player=1, position=Position.FACEDOWN)
    view = GameStateView.from_state(state, viewer=0)

    result = ActionValidator(view).validate(
        PlayerAction.activate_card(0, theirs.instance_id)
    )
    assert result.code is ValidationCode.SOURCE_NOT_CONTROLLED  # 판정은 된다
    text = json.dumps(result.to_dict(), ensure_ascii=False)
    assert str(theirs.card_id) not in text


@requires_official_db
def test_the_two_viewers_can_get_different_answers(state):
    """
    같은 Action 이라도 누구의 관측으로 보느냐에 따라 답이 다를 수 있다.
    정보 은닉이 검증 계층까지 이어진다는 뜻이다.
    """
    their_hand_card = state.player(1).hand[0].instance_id
    action = PlayerAction.normal_summon(1, their_hand_card)

    foe = ActionValidator(GameStateView.from_state(state, viewer=0)).validate(action)
    owner = ActionValidator(GameStateView.from_state(state, viewer=1)).validate(action)

    assert foe.code is ValidationCode.HIDDEN_CARD
    assert owner.code is ValidationCode.NOT_TURN_PLAYER  # 실제 이유를 안다


# ======================================================================
# Mutation safety (§16 의 24~27)
# ======================================================================


def _snapshot(state: GameState) -> tuple:
    return (
        state.state_hash(),
        state.allocator.next_value,
        len(state.uses),
        state.turn.canonical_state(),
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
def test_validation_changes_nothing(state, my_monster, my_hand_monster, their_monster):
    before = _snapshot(state)
    view = GameStateView.from_state(state, viewer=0)
    validator = ActionValidator(view)

    for action in (
        PlayerAction.normal_summon(0, my_hand_monster),
        PlayerAction.normal_summon(0, their_monster),
        PlayerAction.set_spell_trap(0, my_hand_monster),
        PlayerAction.change_position(0, my_monster),
        PlayerAction.attack_directly(0, my_monster),
        PlayerAction.activate_effect(0, my_monster, EffectRef(BLUE_EYES, 0)),
        PlayerAction.change_phase(0, Phase.MAIN1),
        PlayerAction.end_phase(0),
        PlayerAction.passing(0),
        PlayerAction(kind=PlayerActionKind.NORMAL_SUMMON, actor=0),
    ):
        validator.validate(action)
        validator.validate_structure(action)
        validator.requirements(action)

    assert _snapshot(state) == before


@requires_official_db
def test_validation_does_not_record_a_summon_or_an_effect_use(state, my_hand_monster):
    """
    "검증을 위해 미리 실행해보기" 가 없는지 본다. 소환 횟수나 효과 사용을
    기록하면 같은 Action 을 두 번 검증하는 것만으로 판이 달라진다.
    """
    view = GameStateView.from_state(state, viewer=0)
    validator = ActionValidator(view)
    before_uses = state.uses.canonical_state()

    for _ in range(5):
        validator.validate(PlayerAction.normal_summon(0, my_hand_monster))
        validator.validate(
            PlayerAction.activate_effect(
                0, state.player(0).monster_zone[0].instance_id, EffectRef(BLUE_EYES, 0)
            )
        )

    assert state.uses.canonical_state() == before_uses
    assert len(state.uses) == 0


@requires_official_db
def test_the_validator_snapshot_does_not_follow_the_board(state, my_hand_monster):
    """Phase 2-A 의 스냅숏 의미론이 검증 계층에서도 유지된다."""
    validator = ActionValidator(GameStateView.from_state(state, viewer=0))
    first = validator.validate(PlayerAction.normal_summon(0, my_hand_monster))

    for _ in range(4):
        state.create_instance(BLUE_EYES, owner=0, zone=Zone.MZONE)

    # 옛 관측에는 몬스터 존이 아직 비어 있다.
    assert (
        validator.validate(PlayerAction.normal_summon(0, my_hand_monster)).code
        is first.code
    )
    fresh = ActionValidator(GameStateView.from_state(state, viewer=0))
    assert (
        fresh.validate(PlayerAction.normal_summon(0, my_hand_monster)).code
        is ValidationCode.ZONE_FULL
    )


# ======================================================================
# Determinism (§16 의 28~29)
# ======================================================================


@requires_official_db
def test_the_same_inputs_always_give_the_same_result(validator, my_hand_monster):
    action = PlayerAction.normal_summon(0, my_hand_monster)
    first = validator.validate(action)
    for _ in range(10):
        assert validator.validate(action).canonical_state() == first.canonical_state()


@requires_official_db
def test_a_fresh_validator_agrees_with_the_old_one(state, my_hand_monster):
    action = PlayerAction.normal_summon(0, my_hand_monster)
    a = ActionValidator(GameStateView.from_state(state, viewer=0)).validate(action)
    b = ActionValidator(GameStateView.from_state(state, viewer=0)).validate(action)
    assert a.canonical_state() == b.canonical_state()
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(
        b.to_dict(), sort_keys=True
    )


@requires_official_db
def test_the_first_violation_wins_and_the_order_is_fixed(state, their_monster):
    """
    여러 요구를 동시에 어겨도 같은 코드가 나와야 한다. 딕셔너리 순회
    순서에 답이 좌우되면 안 된다.
    """
    action = PlayerAction.normal_summon(0, their_monster)  # 남의 카드 + 필드에 있음
    for _ in range(10):
        view = GameStateView.from_state(state, viewer=0)
        assert (
            ActionValidator(view).validate(action).code
            is ValidationCode.SOURCE_NOT_CONTROLLED
        )


@requires_official_db
def test_requirement_lists_are_stable(validator, my_hand_monster):
    action = PlayerAction.normal_summon(0, my_hand_monster)
    first = tuple(r.condition.canonical_state() for r in validator.requirements(action))
    for _ in range(5):
        again = tuple(
            r.condition.canonical_state() for r in validator.requirements(action)
        )
        assert again == first


@requires_official_db
def test_the_result_serializes_to_value_types_only(validator, their_monster):
    result = validator.validate(PlayerAction.normal_summon(0, their_monster))

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
    for value in leaves(result.canonical_state()):
        assert value is None or isinstance(value, (int, str, bool)), value
    text = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "0x" not in text and "object at" not in text


def test_validation_result_is_immutable():
    result = ValidationResult.invalid(ValidationCode.ZONE_FULL, "꽉 참")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.validity = ActionValidity.VALID
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.code = ValidationCode.OK


def test_every_code_is_distinct():
    assert len({code.value for code in ValidationCode}) == len(list(ValidationCode))


# ======================================================================
# 조건 계층 연결 (§13)
# ======================================================================


@requires_official_db
def test_the_validator_uses_the_condition_layer(validator, my_hand_monster):
    """
    요구는 조건 객체다. 검증기가 규칙을 다시 짜는 것이 아니라 Phase 2-B-1 의
    조건을 쓴다.
    """
    from engine.condition import Condition

    requirements = validator.requirements(
        PlayerAction.normal_summon(0, my_hand_monster)
    )
    assert requirements
    for requirement in requirements:
        assert isinstance(requirement.condition, Condition)
        assert requirement.detail
        assert requirement.code is not ValidationCode.OK


@requires_official_db
def test_a_custom_context_is_honoured(state, my_monster):
    """
    문맥을 밖에서 줄 수 있다. 같은 Action 이라도 "누구의 조건인가" 가
    달라지면 답이 달라진다.
    """
    view = GameStateView.from_state(state, viewer=0)
    validator = ActionValidator(view)
    action = PlayerAction.change_position(0, my_monster)

    default = validator.validate(action)
    assert default.validity is ActionValidity.UNKNOWN

    as_opponent = validator.validate(action, ConditionContext(player=1))
    assert as_opponent.validity is ActionValidity.INVALID
    assert as_opponent.code is ValidationCode.NOT_TURN_PLAYER
