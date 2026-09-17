"""
engine/condition/ — 조건 표현과 평가.

지키는 것 네 가지.

1. ``UNKNOWN`` 이 참/거짓으로 접히지 않는다.
2. 평가가 ``GameState`` 를 바꾸지 않는다.
3. 조건은 ``GameStateView`` 를 통해서만 판을 읽는다.
4. 같은 조건 · 같은 문맥이면 언제나 같은 표현과 같은 답이 나온다.
"""

import dataclasses
import json

import pytest

from engine.condition import (
    Always,
    And,
    CardIsFaceUp,
    CardIsInZone,
    ConditionContext,
    ConditionEvaluator,
    ConditionResult,
    IsTurnPlayer,
    LifePointsAtLeast,
    Not,
    Or,
    PhaseIs,
    PlayerRef,
    UnimplementedRule,
    ZoneCountAtLeast,
    ZoneHasFreeSlot,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

DECK_A = list(range(1000, 1040))
DECK_B = list(range(2000, 2040))

TRUE = ConditionResult.TRUE
FALSE = ConditionResult.FALSE
UNKNOWN = ConditionResult.UNKNOWN


@pytest.fixture
def state() -> GameState:
    game = GameState.create(decks=(DECK_A, DECK_B), extra_decks=(list(range(3000, 3015)), []))
    game.draw(0, 5)
    game.draw(1, 5)
    game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.move(game.player(1).hand[0], Zone.SZONE, position=Position.FACEDOWN)
    game.player(1).change_life(-1500)
    return game


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=0)


@pytest.fixture
def evaluator(view) -> ConditionEvaluator:
    return ConditionEvaluator(view)


@pytest.fixture
def context() -> ConditionContext:
    return ConditionContext(player=0)


# ----------------------------------------------------------------------
# 상수 조건
# ----------------------------------------------------------------------


def test_always_returns_what_it_was_given(view, context):
    assert Always(TRUE).evaluate(view, context) is TRUE
    assert Always(FALSE).evaluate(view, context) is FALSE
    assert Always(UNKNOWN).evaluate(view, context) is UNKNOWN


def test_unimplemented_rule_is_always_unknown_and_says_why(view, context):
    """
    체인 · 트리거 · 타이밍이 아직 없다. 없는 규칙을 추측해서 참/거짓을
    지어내는 대신, 무엇이 없는지 밝히고 모른다고 답한다.
    """
    condition = UnimplementedRule("chain (Phase 2-F)")
    assert condition.evaluate(view, context) is UNKNOWN
    assert condition.unknown_reasons(view, context) == (
        "규칙 미구현: chain (Phase 2-F)",
    )


# ----------------------------------------------------------------------
# B. 논리 결합 — 트리에서도 진리표가 그대로 성립한다
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "left,right,expected",
    [
        (TRUE, TRUE, TRUE),
        (TRUE, FALSE, FALSE),
        (TRUE, UNKNOWN, UNKNOWN),
        (FALSE, UNKNOWN, FALSE),
        (UNKNOWN, UNKNOWN, UNKNOWN),
    ],
)
def test_and_node_follows_the_truth_table(view, context, left, right, expected):
    assert And((Always(left), Always(right))).evaluate(view, context) is expected


@pytest.mark.parametrize(
    "left,right,expected",
    [
        (TRUE, TRUE, TRUE),
        (TRUE, FALSE, TRUE),
        (TRUE, UNKNOWN, TRUE),
        (FALSE, UNKNOWN, UNKNOWN),
        (UNKNOWN, UNKNOWN, UNKNOWN),
        (FALSE, FALSE, FALSE),
    ],
)
def test_or_node_follows_the_truth_table(view, context, left, right, expected):
    assert Or((Always(left), Always(right))).evaluate(view, context) is expected


@pytest.mark.parametrize(
    "value,expected", [(TRUE, FALSE), (FALSE, TRUE), (UNKNOWN, UNKNOWN)]
)
def test_not_node_follows_the_truth_table(view, context, value, expected):
    assert Not(Always(value)).evaluate(view, context) is expected


def test_empty_and_is_true_empty_or_is_false(view, context):
    assert And(()).evaluate(view, context) is TRUE
    assert Or(()).evaluate(view, context) is FALSE


def test_nested_trees_propagate_correctly(view, context):
    """OR 아래에 확실한 참이 있으면 형제의 UNKNOWN 이 전체를 흐리지 않는다."""
    tree = And(
        (
            Or((Always(UNKNOWN), Always(TRUE))),  # -> TRUE
            Not(Always(FALSE)),  # -> TRUE
        )
    )
    assert tree.evaluate(view, context) is TRUE

    spoiled = And((tree, Always(UNKNOWN)))
    assert spoiled.evaluate(view, context) is UNKNOWN

    settled = And((spoiled, Always(FALSE)))
    assert settled.evaluate(view, context) is FALSE


# ----------------------------------------------------------------------
# C. UNKNOWN 전파 — 어디에서도 접히지 않는다
# ----------------------------------------------------------------------


def test_unknown_never_becomes_true_or_false_on_its_own(view, context):
    unknown_tree = And(
        (
            Always(TRUE),
            Or((Always(FALSE), UnimplementedRule("timing"))),
            Not(UnimplementedRule("chain")),
        )
    )
    assert unknown_tree.evaluate(view, context) is UNKNOWN


def test_unknown_reasons_are_collected_from_the_whole_tree(view, context):
    tree = And((UnimplementedRule("chain"), Always(TRUE), UnimplementedRule("timing")))
    reasons = tree.unknown_reasons(view, context)
    assert reasons == ("규칙 미구현: chain", "규칙 미구현: timing")


def test_a_decided_tree_reports_no_reasons(view, context):
    """``FALSE AND UNKNOWN`` 은 이미 거짓이다. 모를 이유가 없다."""
    tree = And((Always(FALSE), UnimplementedRule("chain")))
    assert tree.evaluate(view, context) is FALSE
    assert tree.unknown_reasons(view, context) == ()


# ----------------------------------------------------------------------
# 상태 술어 — 관측으로 확정되는 것들
# ----------------------------------------------------------------------


def test_phase_is(view, context):
    assert PhaseIs((Phase.DRAW,)).evaluate(view, context) is TRUE
    assert PhaseIs((Phase.MAIN1,)).evaluate(view, context) is FALSE
    assert PhaseIs((Phase.MAIN1, Phase.DRAW)).evaluate(view, context) is TRUE


def test_phase_is_needs_at_least_one_phase():
    with pytest.raises(ValueError):
        PhaseIs(())


def test_is_turn_player_is_context_relative(view):
    assert IsTurnPlayer(PlayerRef.CONTROLLER).evaluate(
        view, ConditionContext(player=0)
    ) is TRUE
    assert IsTurnPlayer(PlayerRef.CONTROLLER).evaluate(
        view, ConditionContext(player=1)
    ) is FALSE
    assert IsTurnPlayer(PlayerRef.OPPONENT).evaluate(
        view, ConditionContext(player=1)
    ) is TRUE


def test_life_points_at_least(view, context):
    assert LifePointsAtLeast(PlayerRef.CONTROLLER, 8000).evaluate(view, context) is TRUE
    assert LifePointsAtLeast(PlayerRef.CONTROLLER, 8001).evaluate(view, context) is FALSE
    assert LifePointsAtLeast(PlayerRef.OPPONENT, 6500).evaluate(view, context) is TRUE
    assert LifePointsAtLeast(PlayerRef.OPPONENT, 6501).evaluate(view, context) is FALSE


def test_life_points_refuses_a_negative_threshold():
    with pytest.raises(ValueError):
        LifePointsAtLeast(PlayerRef.CONTROLLER, -1)


def test_zone_count_is_decidable_even_for_a_concealed_zone(view, context):
    """
    상대 패의 **장수**는 실제 대전에서도 보인다. 모르는 것은 *무엇이*
    있는가이지 *몇 장*이 아니다. 그러니 UNKNOWN 이 아니라 확정된다.
    """
    assert view.opponent.hand.concealed is True  # 내용은 가려져 있고
    assert view.opponent.hand.size == 4  # 장수는 정확하다

    assert ZoneCountAtLeast(PlayerRef.OPPONENT, Zone.HAND, 4).evaluate(view, context) is TRUE
    assert ZoneCountAtLeast(PlayerRef.OPPONENT, Zone.HAND, 5).evaluate(view, context) is FALSE
    assert ZoneCountAtLeast(PlayerRef.CONTROLLER, Zone.DECK, 35).evaluate(view, context) is TRUE


def test_zone_has_free_slot(view, context):
    assert ZoneHasFreeSlot(PlayerRef.CONTROLLER, Zone.MZONE).evaluate(view, context) is TRUE
    assert ZoneHasFreeSlot(PlayerRef.CONTROLLER, Zone.EMZONE).evaluate(view, context) is TRUE
    # 칸 수가 없는 존은 언제나 자리가 있다.
    assert ZoneHasFreeSlot(PlayerRef.CONTROLLER, Zone.GRAVE).evaluate(view, context) is TRUE


def test_zone_has_free_slot_turns_false_when_the_zone_fills(state, context):
    for _ in range(4):
        state.create_instance(1500, owner=0, zone=Zone.MZONE)
    view = GameStateView.from_state(state, viewer=0)
    assert view.me.monster_zone.size == 5
    assert ZoneHasFreeSlot(PlayerRef.CONTROLLER, Zone.MZONE).evaluate(view, context) is FALSE


# ----------------------------------------------------------------------
# H. 가려진 정보와 빠진 문맥 — 예외도 임의의 값도 아니고 UNKNOWN
# ----------------------------------------------------------------------


def test_a_card_hidden_from_the_viewer_is_unknown_not_false(state, context):
    """
    **"안 보인다" 와 "없다" 는 다르다.** 상대 패에 있는 카드를 두고
    "묘지에 없다" 고 단정할 수 없다.
    """
    hidden = state.player(1).hand[0]
    view = GameStateView.from_state(state, viewer=0)
    assert view.find(hidden.instance_id) is None

    condition = CardIsInZone(Zone.GRAVE, PlayerRef.OPPONENT, hidden.instance_id)
    result = condition.evaluate(view, context)
    assert result is UNKNOWN
    assert result is not FALSE
    assert "보이지 않" in condition.unknown_reasons(view, context)[0]


def test_the_same_card_is_decidable_for_its_owner(state):
    """같은 조건이라도 보는 사람이 다르면 답이 다르다. 그것이 맞다."""
    card = state.player(1).hand[0]
    condition = CardIsInZone(Zone.HAND, PlayerRef.CONTROLLER, card.instance_id)

    owner_view = GameStateView.from_state(state, viewer=1)
    assert condition.evaluate(owner_view, ConditionContext(player=1)) is TRUE

    foe_view = GameStateView.from_state(state, viewer=0)
    assert condition.evaluate(foe_view, ConditionContext(player=1)) is UNKNOWN


def test_a_visible_card_in_another_zone_is_decidably_false(state, view, context):
    """보이는데 다른 존에 있으면 그건 확실히 거짓이다."""
    on_field = state.player(0).monster_zone[0]
    assert view.find(on_field.instance_id) is not None
    assert (
        CardIsInZone(Zone.MZONE, PlayerRef.CONTROLLER, on_field.instance_id).evaluate(
            view, context
        )
        is TRUE
    )
    assert (
        CardIsInZone(Zone.GRAVE, PlayerRef.CONTROLLER, on_field.instance_id).evaluate(
            view, context
        )
        is FALSE
    )


def test_missing_context_source_yields_unknown_not_an_exception(view, context):
    """
    조건이 문맥의 ``source`` 를 필요로 하는데 없다. 예외를 던지거나 임의로
    참/거짓을 고르지 않고 **정의된 방식으로** 모른다고 답한다.
    """
    assert context.source is None
    condition = CardIsInZone(Zone.MZONE)  # instance 를 비워 두면 문맥을 본다

    result = condition.evaluate(view, context)
    assert result is UNKNOWN
    assert condition.unknown_reasons(view, context) == (
        "문맥에 source 가 없어 어느 카드인지 알 수 없음",
    )


def test_the_same_condition_decides_once_the_context_carries_a_source(state, view):
    on_field = state.player(0).monster_zone[0]
    condition = CardIsInZone(Zone.MZONE)

    without = ConditionContext(player=0)
    withal = ConditionContext(player=0, source=on_field.instance_id)

    assert condition.evaluate(view, without) is UNKNOWN
    assert condition.evaluate(view, withal) is TRUE


def test_face_up_of_an_opponent_set_card_is_decidable_but_its_identity_is_not(state):
    """
    상대의 세트 카드는 **뒷면이라는 사실**은 보인다. 정체만 모른다.
    그러니 CardIsFaceUp 은 확정되고, 조건이 그 이상을 캐낼 수는 없다.
    """
    set_card = state.player(1).spell_zone[0]
    foe_view = GameStateView.from_state(state, viewer=0)
    seen = foe_view.find(set_card.instance_id)

    assert seen is not None and seen.is_identified is False
    assert CardIsFaceUp(set_card.instance_id).evaluate(
        foe_view, ConditionContext(player=0)
    ) is FALSE


def test_face_up_of_a_card_in_a_hidden_zone_is_unknown(state, context):
    deck_card = state.player(1).deck[0]
    view = GameStateView.from_state(state, viewer=0)
    assert CardIsFaceUp(deck_card.instance_id).evaluate(view, context) is UNKNOWN


def test_missing_context_source_yields_unknown_for_face_up(view, context):
    condition = CardIsFaceUp()
    assert condition.evaluate(view, context) is UNKNOWN
    assert "source" in condition.unknown_reasons(view, context)[0]


# ----------------------------------------------------------------------
# 불변성
# ----------------------------------------------------------------------


def test_conditions_are_immutable():
    condition = PhaseIs((Phase.MAIN1,))
    with pytest.raises(dataclasses.FrozenInstanceError):
        condition.phases = (Phase.END,)

    tree = And((Always(TRUE),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        tree.children = ()
    with pytest.raises(AttributeError):
        tree.children.append(Always(FALSE))


def test_a_list_of_children_is_refused():
    with pytest.raises(TypeError):
        And([Always(TRUE)])  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Or([Always(TRUE)])  # type: ignore[arg-type]


def test_context_is_immutable():
    context = ConditionContext(player=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.player = 1
    with pytest.raises(TypeError):
        ConditionContext(player=0, targets=[InstanceId(1)])  # type: ignore[arg-type]


def test_context_refuses_an_impossible_player():
    with pytest.raises(ValueError):
        ConditionContext(player=2)


# ----------------------------------------------------------------------
# F. 결정론
# ----------------------------------------------------------------------


def test_identical_conditions_have_identical_representations():
    a = And((PhaseIs((Phase.MAIN1,)), LifePointsAtLeast(PlayerRef.CONTROLLER, 2000)))
    b = And((PhaseIs((Phase.MAIN1,)), LifePointsAtLeast(PlayerRef.CONTROLLER, 2000)))

    assert a == b
    assert a.canonical_state() == b.canonical_state()
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(
        b.to_dict(), sort_keys=True
    )


def test_different_conditions_have_different_representations():
    base = LifePointsAtLeast(PlayerRef.CONTROLLER, 2000)
    assert base.canonical_state() != LifePointsAtLeast(
        PlayerRef.OPPONENT, 2000
    ).canonical_state()
    assert base.canonical_state() != LifePointsAtLeast(
        PlayerRef.CONTROLLER, 2001
    ).canonical_state()


def test_child_order_is_part_of_the_representation():
    """구조를 평탄화하거나 정렬하지 않는다."""
    one, two = Always(TRUE), Always(FALSE)
    assert And((one, two)).canonical_state() != And((two, one)).canonical_state()


def test_representation_holds_only_value_types():
    condition = And(
        (
            PhaseIs((Phase.MAIN1, Phase.MAIN2)),
            Not(CardIsInZone(Zone.MZONE, PlayerRef.OPPONENT, InstanceId(3))),
            UnimplementedRule("chain"),
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

    for value in leaves(condition.canonical_state()):
        assert value is None or isinstance(value, (int, str, bool)), value
    for value in leaves(condition.to_dict()):
        assert value is None or isinstance(value, (int, str, bool)), value

    text = json.dumps(condition.to_dict(), ensure_ascii=False)
    assert "0x" not in text and "object at" not in text


def test_the_same_condition_and_context_always_give_the_same_answer(view, context):
    condition = And(
        (PhaseIs((Phase.DRAW,)), ZoneCountAtLeast(PlayerRef.OPPONENT, Zone.HAND, 4))
    )
    first = condition.evaluate(view, context)
    for _ in range(10):
        assert condition.evaluate(view, context) is first


def test_representation_is_stable_across_processes():
    """``PYTHONHASHSEED`` 가 달라도 같은 값이어야 한다."""
    import pathlib
    import subprocess
    import sys

    snippet = (
        "import json;"
        "from engine.condition import And, PhaseIs, LifePointsAtLeast, PlayerRef;"
        "from engine.vocabulary import Phase;"
        "c = And((PhaseIs((Phase.MAIN1, Phase.MAIN2)),"
        " LifePointsAtLeast(PlayerRef.OPPONENT, 2000)));"
        "print(json.dumps(c.canonical_state()))"
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


def test_context_representation_is_deterministic():
    a = ConditionContext(player=0, source=InstanceId(3), effect_ref=EffectRef(2511, 1))
    b = ConditionContext(player=0, source=InstanceId(3), effect_ref=EffectRef(2511, 1))
    assert a == b
    assert a.canonical_state() == b.canonical_state()
    assert a.canonical_state() != ConditionContext(
        player=1, source=InstanceId(3), effect_ref=EffectRef(2511, 1)
    ).canonical_state()
