"""
engine/action_validation.py — 구조는 본다. 규칙은 아직 안 본다. 상태는 안 바꾼다.

이 파일은 Phase 2-A 의 가장 중요한 불변식 두 개를 지킨다.

1. **UNKNOWN 은 허가가 아니다.** 규칙이 없어서 모르는 것을 통과로 바꾸지 않는다.
2. **검증은 상태를 바꾸지 않는다.** ``state_hash()`` 로 확인한다.
"""

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_target import ActionTarget
from engine.action_validation import (
    ActionValidator,
    ActionValidity,
    ValidationCode,
    ValidationResult,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

DECK_A = list(range(1000, 1040))
DECK_B = list(range(2000, 2040))


@pytest.fixture
def state() -> GameState:
    game = GameState.create(decks=(DECK_A, DECK_B), extra_decks=(list(range(3000, 3015)), []))
    game.draw(0, 5)
    game.draw(1, 5)
    game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.move(game.player(1).hand[0], Zone.MZONE, position=Position.FACEDOWN_DEFENSE)
    return game


@pytest.fixture
def validator(state) -> ActionValidator:
    """
    검증기는 **관측**을 받는다. ``GameState`` 를 주면 상대의 패와 덱이
    보이고, 판정이 "없다" 와 "안 보인다" 를 구분해 버려 정보가 샌다.
    """
    return ActionValidator(GameStateView.from_state(state, viewer=0))


# ----------------------------------------------------------------------
# 구조가 틀리면 INVALID
# ----------------------------------------------------------------------


def test_missing_source_is_a_structural_failure(validator, state):
    action = PlayerAction(kind=PlayerActionKind.NORMAL_SUMMON, actor=0)
    result = validator.validate(action)

    assert result.validity is ActionValidity.INVALID
    assert "source" in result.reason
    assert not result.permits_execution


def test_activate_effect_without_an_effect_ref_is_invalid(validator, state):
    action = PlayerAction(
        kind=PlayerActionKind.ACTIVATE_EFFECT, actor=0, source=InstanceId(0)
    )
    result = validator.validate(action)

    assert result.validity is ActionValidity.INVALID
    assert "effect_ref" in result.reason


def test_change_phase_without_a_phase_is_invalid(validator, state):
    action = PlayerAction(kind=PlayerActionKind.CHANGE_PHASE, actor=0)
    assert validator.validate(action).validity is ActionValidity.INVALID


def test_fields_that_do_not_belong_to_the_kind_are_invalid(validator, state):
    card = state.player(0).monster_zone[0]

    # end_phase 에 카드가 붙어 있다.
    assert (
        validator.validate(
            PlayerAction(
                kind=PlayerActionKind.END_PHASE, actor=0, source=card.instance_id
            ),
        ).validity
        is ActionValidity.INVALID
    )
    # 일반 소환에 페이즈가 붙어 있다.
    assert (
        validator.validate(
            PlayerAction(
                kind=PlayerActionKind.NORMAL_SUMMON,
                actor=0,
                source=card.instance_id,
                phase=Phase.MAIN1,
            ),
        ).validity
        is ActionValidity.INVALID
    )
    # 일반 소환에 effect_ref 가 붙어 있다.
    assert (
        validator.validate(
            PlayerAction(
                kind=PlayerActionKind.NORMAL_SUMMON,
                actor=0,
                source=card.instance_id,
                effect_ref=EffectRef(1000, 0),
            ),
        ).validity
        is ActionValidity.INVALID
    )


def test_attack_needs_exactly_one_target(validator, state):
    card = state.player(0).monster_zone[0]

    none_at_all = PlayerAction(
        kind=PlayerActionKind.ATTACK, actor=0, source=card.instance_id
    )
    assert validator.validate(none_at_all).validity is ActionValidity.INVALID

    two = PlayerAction(
        kind=PlayerActionKind.ATTACK,
        actor=0,
        source=card.instance_id,
        targets=(
            ActionTarget.instance(InstanceId(0)),
            ActionTarget.instance(InstanceId(1)),
        ),
    )
    assert validator.validate(two).validity is ActionValidity.INVALID


def test_attacking_a_zone_is_a_structural_failure(validator, state):
    card = state.player(0).monster_zone[0]
    action = PlayerAction.attack(
        0, card.instance_id, ActionTarget.zone_target(1, Zone.MZONE, 0)
    )
    result = validator.validate(action)

    assert result.validity is ActionValidity.INVALID
    assert "몬스터" in result.reason


def test_pointing_at_a_card_the_viewer_cannot_see_is_unknown(validator, state):
    """
    Phase 2-A 는 ``GameState`` 를 직접 읽어 이것을 INVALID 라고 단정했다.
    그런데 그러려면 **상대의 패와 덱까지 들여다봐야** 한다. 검증을 반복하는
    것만으로 상대 손패를 탐지할 수 있게 되므로, 관측만 보고 판정한다.

    관측에 없는 카드는 이 듀얼에 없는 것일 수도, 가려진 존에 있는 것일
    수도 있다. **구분할 수 없으므로 UNKNOWN 이다.**
    """
    result = validator.validate(PlayerAction.normal_summon(0, InstanceId(99999)))
    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.HIDDEN_CARD
    assert not result.permits_execution


def test_a_card_hidden_in_the_opponent_hand_is_also_unknown(validator, state):
    """같은 이유로, 실제로 존재하지만 안 보이는 카드도 UNKNOWN 이다."""
    hidden = state.player(1).hand[0].instance_id
    result = validator.validate(PlayerAction.normal_summon(0, hidden))
    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.HIDDEN_CARD


def test_effect_ref_must_belong_to_the_source_card(validator, state):
    """
    ``EffectRef.card_id`` 가 source 카드와 다르면 그 효과는 그 카드의 것이
    아니다. 규칙이 아니라 **참조 무결성** 문제다.
    """
    card = state.player(0).monster_zone[0]
    wrong = PlayerAction.activate_effect(
        0, card.instance_id, EffectRef(card.card_id + 1, 0)
    )
    result = validator.validate(wrong)

    assert result.validity is ActionValidity.INVALID
    assert "effect_ref" in result.reason

    right = PlayerAction.activate_effect(0, card.instance_id, EffectRef(card.card_id, 0))
    assert validator.validate(right).validity is ActionValidity.UNKNOWN


# ----------------------------------------------------------------------
# 구조가 맞으면 UNKNOWN — 아직 규칙이 없기 때문이다
# ----------------------------------------------------------------------


def test_a_well_formed_action_is_unknown_not_valid(validator, state):
    """
    Phase 2-A 에는 적법성 계층이 없다. **모른다고 말하는 것이 정직하다.**
    """
    card = state.player(0).monster_zone[0]
    result = validator.validate(PlayerAction.change_position(0, card.instance_id))

    assert result.validity is ActionValidity.UNKNOWN
    assert result.missing_rule is not None
    assert not result.permits_execution


def test_every_action_kind_reports_which_rule_layer_is_missing(validator, state):
    """어느 Phase 가 이 판정을 담당하는지 결과에 남는다."""
    card = state.player(0).monster_zone[0]
    hand_card = state.player(0).hand[0]
    samples = {
        PlayerActionKind.NORMAL_SUMMON: PlayerAction.normal_summon(
            0, hand_card.instance_id
        ),
        PlayerActionKind.SPECIAL_SUMMON: PlayerAction.special_summon(
            0, hand_card.instance_id
        ),
        PlayerActionKind.SET_MONSTER: PlayerAction.set_monster(
            0, hand_card.instance_id
        ),
        PlayerActionKind.SET_SPELL_TRAP: PlayerAction.set_spell_trap(
            0, hand_card.instance_id
        ),
        PlayerActionKind.ACTIVATE_CARD: PlayerAction.activate_card(
            0, hand_card.instance_id
        ),
        PlayerActionKind.ACTIVATE_EFFECT: PlayerAction.activate_effect(
            0, card.instance_id, EffectRef(card.card_id, 0)
        ),
        PlayerActionKind.CHANGE_POSITION: PlayerAction.change_position(
            0, card.instance_id
        ),
        PlayerActionKind.ATTACK: PlayerAction.attack_directly(0, card.instance_id),
        PlayerActionKind.CHANGE_PHASE: PlayerAction.change_phase(0, Phase.MAIN1),
        PlayerActionKind.END_PHASE: PlayerAction.end_phase(0),
        PlayerActionKind.PASS: PlayerAction.passing(0),
    }
    assert set(samples) == set(PlayerActionKind), "새 행위가 생겼으면 여기도 채우세요."

    for kind, action in samples.items():
        result = validator.validate(action)
        assert result.validity is not ActionValidity.VALID, (
            f"{kind} 가 허가를 받았습니다. 아직 어떤 행위도 실행 가능하다고 "
            f"말할 수 없습니다: {result}"
        )
        # 판정이 무엇이든 **이유를 말해야** 한다.
        assert result.code is not ValidationCode.OK, f"{kind}: {result}"
        assert result.reason, f"{kind} 가 이유를 말하지 않습니다."
        if result.code is ValidationCode.RULE_NOT_IMPLEMENTED:
            assert result.missing_rule, f"{kind} 가 어느 규칙 계층이 없는지 말하지 않습니다."
        if result.code is ValidationCode.INFORMATION_UNAVAILABLE:
            assert result.notes, f"{kind} 가 무엇을 모르는지 말하지 않습니다."


def test_structure_check_alone_says_valid(validator, state):
    """
    두 층을 따로 물어볼 수 있어야 한다. 구조만 보면 VALID 가 나온다 —
    그것이 "실행해도 된다" 는 뜻이 아니라는 것이 핵심이다.
    """
    card = state.player(0).monster_zone[0]
    action = PlayerAction.change_position(0, card.instance_id)

    assert validator.validate_structure(action).validity is ActionValidity.VALID
    assert validator.validate(action).validity is ActionValidity.UNKNOWN


def test_structure_is_checked_without_looking_at_the_board(validator):
    """
    모양 검사는 판을 보지 않는다. 있지도 않은 카드를 가리켜도 **모양은**
    올바르다 — 그것이 실제로 소환 가능한지는 다음 층의 질문이다.
    """
    assert (
        validator.validate_structure(
            PlayerAction.normal_summon(0, InstanceId(9999))
        ).validity
        is ActionValidity.VALID
    )


# ----------------------------------------------------------------------
# UNKNOWN ≠ INVALID
# ----------------------------------------------------------------------


def test_unknown_is_not_invalid(validator, state):
    card = state.player(0).monster_zone[0]

    unknown = validator.validate(PlayerAction.change_position(0, card.instance_id))
    invalid = validator.validate(
        PlayerAction(kind=PlayerActionKind.NORMAL_SUMMON, actor=0)
    )

    assert unknown.validity is not invalid.validity
    assert ActionValidity.UNKNOWN is not ActionValidity.INVALID
    assert unknown.is_structural_failure is False
    assert invalid.is_structural_failure is True


def test_unknown_never_grants_permission():
    """
    ``if result.validity is not INVALID: execute`` 를 쓰면 UNKNOWN 이 허가로
    새어 나간다. ``permits_execution`` 은 VALID 하나에만 참이다.
    """
    assert (
        ValidationResult.unknown(
            ValidationCode.RULE_NOT_IMPLEMENTED, "모름", "rule"
        ).permits_execution
        is False
    )
    assert (
        ValidationResult.invalid(
            ValidationCode.SOURCE_REQUIRED, "틀림"
        ).permits_execution
        is False
    )
    assert ValidationResult.valid().permits_execution is True


def test_no_action_kind_can_be_executed_in_phase_2a(validator, state):
    """
    Phase 2-A 의 정의상, 어떤 Action 도 실행 허가를 받지 못한다.
    하나라도 통과하면 실행 계층이 없는데 실행이 열린 것이다.
    """
    card = state.player(0).monster_zone[0]
    for action in (
        PlayerAction.normal_summon(0, state.player(0).hand[0].instance_id),
        PlayerAction.attack_directly(0, card.instance_id),
        PlayerAction.change_phase(0, Phase.MAIN1),
        PlayerAction.end_phase(0),
        PlayerAction.passing(0),
    ):
        assert not validator.validate(action).permits_execution


# ----------------------------------------------------------------------
# 상태 변경 경계 (§26 · §27 의 30~32)
# ----------------------------------------------------------------------


def _snapshot(state: GameState) -> tuple:
    """해시 + 해시에 안 들어가는 것들까지 함께 본다."""
    return (
        state.state_hash(),
        state.allocator.next_value,
        len(state.uses),
        [len(state.player(p).zone(z)) for p in (0, 1) for z in (Zone.HAND, Zone.MZONE)],
    )


def test_creating_an_action_does_not_touch_the_state(state):
    before = _snapshot(state)

    hand_card = state.player(0).hand[0]
    PlayerAction.normal_summon(0, hand_card.instance_id)
    PlayerAction.set_monster(0, hand_card.instance_id)
    PlayerAction.attack_directly(0, state.player(0).monster_zone[0].instance_id)
    PlayerAction.change_phase(0, Phase.END)

    assert _snapshot(state) == before
    # 카드는 여전히 패에 있다 — 일반 소환은 **일어나지 않았다.**
    assert hand_card in state.player(0).hand
    assert hand_card.zone is Zone.HAND


def test_creating_a_view_does_not_touch_the_state(state):
    before = _snapshot(state)
    GameStateView.from_state(state, viewer=0)
    GameStateView.from_state(state, viewer=1)
    assert _snapshot(state) == before


def test_validating_does_not_touch_the_state(validator, state):
    before = _snapshot(state)
    card = state.player(0).monster_zone[0]

    validator.validate(PlayerAction.normal_summon(0, state.player(0).hand[0].instance_id))
    validator.validate(PlayerAction.attack_directly(0, card.instance_id))
    validator.validate(PlayerAction.change_phase(0, Phase.MAIN1))
    validator.validate(PlayerAction(kind=PlayerActionKind.NORMAL_SUMMON, actor=0))
    validator.validate_structure(PlayerAction.end_phase(1))

    assert _snapshot(state) == before


def test_validator_holds_no_state_of_its_own(validator, state):
    """
    Validator 가 상태를 쌓으면 같은 Action 이 호출 순서에 따라 다른 답을
    낸다. 판정은 결정론적이어야 한다.
    """
    action = PlayerAction.end_phase(0)
    first = validator.validate(action)
    for _ in range(5):
        assert validator.validate(action).canonical_state() == first.canonical_state()
    fresh = ActionValidator(GameStateView.from_state(state, viewer=0))
    assert fresh.validate(action).canonical_state() == first.canonical_state()


def test_validator_exposes_no_mutation_path(validator):
    for forbidden in ("execute", "apply", "resolve", "move", "draw"):
        assert not hasattr(validator, forbidden), (
            f"ActionValidator.{forbidden} 이 생겼습니다. 검증과 실행은 "
            "분리되어야 합니다 (ADR-007)."
        )
