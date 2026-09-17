"""
engine/game_state_view.py — AI 가 보는 만큼만 보이고, 봐도 못 바꾼다.

두 가지를 지킨다.

1. **정보 은닉이 구조적이다.** 숨긴 값을 들고 플래그로 가리는 것이 아니라,
   값 자체가 ``None`` 이거나 없다.
2. **스냅숏이다.** 만들어진 뒤 원본이 바뀌어도 관측은 그대로다.
"""

import dataclasses

import pytest

from engine.game_state_view import CardView, GameStateView, PlayerView, ZoneView
from engine.ids import InstanceId
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone, ZoneKind, ZoneVisibility

DECK_A = list(range(1000, 1040))
DECK_B = list(range(2000, 2040))
EXTRA_A = list(range(3000, 3015))


@pytest.fixture
def state() -> GameState:
    game = GameState.create(decks=(DECK_A, DECK_B), extra_decks=(EXTRA_A, []))
    game.draw(0, 5)
    game.draw(1, 5)
    # p0: 앞면 몬스터 하나, 뒷면 마법 하나
    game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.move(game.player(0).hand[0], Zone.SZONE, position=Position.FACEDOWN)
    # p1: 뒷면 몬스터 하나
    game.move(game.player(1).hand[0], Zone.MZONE, position=Position.FACEDOWN_DEFENSE)
    game.player(1).change_life(-1500)
    return game


@pytest.fixture
def mine(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=0)


@pytest.fixture
def theirs(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=1)


# ----------------------------------------------------------------------
# 만들기 · 기본 읽기
# ----------------------------------------------------------------------


def test_view_is_created_for_one_viewer(state, mine):
    assert mine.viewer == 0
    assert mine.me.player_id == 0
    assert mine.opponent.player_id == 1
    assert mine.opponent_id == 1


def test_viewer_must_be_a_real_player(state):
    with pytest.raises(ValueError):
        GameStateView.from_state(state, viewer=2)


def test_life_points_are_readable_for_both_players(mine):
    assert mine.me.life_points == 8000
    assert mine.opponent.life_points == 6500


def test_turn_and_phase_are_readable(state, mine):
    assert mine.turn_number == 1
    assert mine.turn_player == 0
    assert mine.phase is Phase.DRAW
    assert mine.step == 0
    assert mine.is_my_turn is True

    state.turn.advance_phase()
    later = GameStateView.from_state(state, viewer=1)
    assert later.phase is Phase.STANDBY
    assert later.is_my_turn is False


def test_my_own_hand_is_fully_visible(mine):
    hand = mine.me.hand
    assert hand.concealed is False
    assert hand.size == 3
    assert len(hand.cards) == 3
    for card in hand.cards:
        assert card is not None
        assert card.is_identified
        assert card.card_id in DECK_A


def test_public_field_is_visible_to_both(mine, theirs):
    for view in (mine, theirs):
        monsters = view.player(0).monster_zone
        assert monsters.size == 1
        face_up = monsters.cards[0]
        assert face_up is not None
        assert face_up.is_identified
        assert face_up.face_up is True


def test_graveyard_is_public_even_for_cards_that_never_turned_face_up(state):
    """
    ``move_card`` 는 표시 형식을 건드리지 않으므로, 덱에서 바로 묘지로 간
    카드는 ``position`` 이 ``FACEDOWN`` 인 채로 남는다. 앞뒷면만 보고
    가리면 **상대 묘지가 통째로 안 보인다.** 묘지에 뒷면은 없다.
    """
    buried = state.player(1).deck[0]
    state.move(buried, Zone.GRAVE, to_player=1)
    assert buried.is_faceup is False  # 표시 형식은 뒷면 그대로다

    view = GameStateView.from_state(state, viewer=0)
    assert view.opponent.grave.concealed is False
    assert view.opponent.grave.size == 1
    assert view.opponent.grave.cards[0].is_identified
    assert view.opponent.grave.cards[0].card_id == buried.card_id


def test_face_down_banished_cards_stay_hidden_from_the_opponent(state):
    """제외 존은 다르다 — 뒷면 제외가 실제로 있고, 제외한 쪽만 안다."""
    state.move(
        state.player(0).deck[0], Zone.REMOVED, to_player=0, position=Position.FACEDOWN
    )
    state.move(
        state.player(0).deck[0],
        Zone.REMOVED,
        to_player=0,
        position=Position.FACEUP,
    )
    mine_view = GameStateView.from_state(state, viewer=0)
    foe_view = GameStateView.from_state(state, viewer=1)

    assert all(c.is_identified for c in mine_view.me.removed.cards)
    identified = [c.is_identified for c in foe_view.player(0).removed.cards]
    assert identified == [False, True]
    assert foe_view.player(0).removed.size == 2  # 장수는 공개다


# ----------------------------------------------------------------------
# 숨겨진 정보
# ----------------------------------------------------------------------


def test_opponent_hand_shows_a_count_and_nothing_else(mine):
    """
    장수는 실제 대전에서도 보인다. 내용은 보이지 않는다.
    ``instance_id`` 도 주지 않는다 — 주면 "3턴에 뽑은 그 카드가 아직 손에
    있다" 는 것이 드러나고, 그것은 알 수 없는 사실이다.
    """
    hand = mine.opponent.hand
    assert hand.size == 4
    assert hand.concealed is True
    assert hand.cards == ()


def test_nobody_sees_any_deck_contents(mine):
    """자기 덱도 마찬가지다. 그것이 규칙이다."""
    assert mine.me.deck.concealed is True
    assert mine.me.deck.cards == ()
    assert mine.me.deck.size == 35
    assert mine.opponent.deck.concealed is True
    assert mine.opponent.deck.cards == ()


def test_my_extra_deck_is_mine_to_see_but_not_theirs(mine, theirs):
    assert mine.me.extra.concealed is False
    assert mine.me.extra.size == 15
    assert all(c.is_identified for c in mine.me.extra.cards)

    assert theirs.player(0).extra.concealed is True
    assert theirs.player(0).extra.cards == ()
    assert theirs.player(0).extra.size == 15  # 장수는 공개다


def test_a_face_down_card_hides_its_identity_from_the_opponent(mine, theirs):
    """
    상대의 세트 카드는 **자리는 보이지만 정체는 모른다.**
    지목은 할 수 있어야 하므로 instance_id 는 남는다.
    """
    seen_by_owner = mine.me.spell_zone.cards[0]
    seen_by_foe = theirs.player(0).spell_zone.cards[0]

    assert seen_by_owner is not None and seen_by_foe is not None
    assert seen_by_owner.is_identified is True  # 내가 세트한 카드다
    assert seen_by_foe.is_identified is False
    assert seen_by_foe.card_id is None
    assert seen_by_foe.name is None
    assert seen_by_foe.owner is None

    # 그래도 지목은 가능하다 — 공격 · 파괴 대상이 되어야 하므로.
    assert seen_by_foe.is_targetable is True
    assert seen_by_foe.instance_id == seen_by_owner.instance_id
    assert seen_by_foe.zone is Zone.SZONE
    assert seen_by_foe.sequence == 0


def test_hidden_identity_is_absent_not_merely_flagged(theirs):
    """
    플래그로 가리면 그 플래그를 안 보는 코드 한 줄이 곧 유출이다.
    값 자체가 없어야 한다.
    """
    concealed = theirs.player(0).spell_zone.cards[0]
    assert concealed.card_id is None
    assert concealed.name is None
    # 직렬화에도 새어나가지 않는다.
    assert "card_id" not in concealed.to_dict()
    assert str(DECK_A[1]) not in str(concealed.canonical_state())


def test_no_card_id_of_a_hidden_zone_appears_anywhere_in_the_view(state):
    """
    상대 관점 관측 전체를 훑어서 상대 패·덱의 카드 ID 가 단 하나도
    나타나지 않는지 본다. 어느 경로로든 새면 여기서 걸린다.
    """
    view = GameStateView.from_state(state, viewer=1)
    secret_ids = {
        card.card_id
        for card in list(state.player(0).hand) + list(state.player(0).deck)
    }
    # 필드로 나간 카드는 공개이므로 비밀 목록에서 뺀다.
    public_ids = {
        card.card_id
        for zone in (Zone.MZONE, Zone.SZONE, Zone.GRAVE, Zone.REMOVED)
        for card in state.player(0).zone(zone)
    }
    secret_ids -= public_ids
    assert secret_ids, "숨겨야 할 카드가 없으면 테스트가 헛돕니다."

    text = str(view.to_dict())
    for card_id in secret_ids:
        assert f": {card_id}" not in text and f"{card_id}," not in text, (
            f"카드 ID {card_id} 가 상대 관측에 새어 나왔습니다."
        )


# ----------------------------------------------------------------------
# 칸 · EMZ
# ----------------------------------------------------------------------


def test_zone_slots_are_readable_with_their_holes(state):
    # 0번 칸은 이미 차 있다. 4번에 하나 더 놓아 가운데를 비워 둔다.
    state.create_instance(1500, owner=0, zone=Zone.MZONE, index=4)
    view = GameStateView.from_state(state, viewer=0)
    zone = view.me.monster_zone

    assert zone.kind is ZoneKind.SLOTTED
    assert zone.capacity == 5
    assert len(zone.cards) == 5
    assert zone.cards[0] is not None
    assert zone.cards[1] is None
    assert zone.free_slots() == (1, 2, 3)
    assert zone.size == 2


def test_extra_monster_zone_is_readable_and_separate(mine):
    """EMZ 를 메인 몬스터 존과 같이 취급하면 안 된다 (칸 수부터 다르다)."""
    emz = mine.me.extra_monster_zone
    assert emz.zone is Zone.EMZONE
    assert emz.capacity == 1
    assert emz.kind is ZoneKind.SLOTTED
    assert len(emz.cards) == 1
    assert emz.cards[0] is None
    assert mine.me.monster_zone.capacity == 5
    assert emz is not mine.me.monster_zone


def test_every_player_zone_is_present_in_the_view(mine):
    from engine.vocabulary import PLAYER_ZONES

    assert {z.zone for z in mine.me.zones} == set(PLAYER_ZONES)


def test_zone_visibility_is_reported(mine):
    assert mine.me.deck.visibility is ZoneVisibility.HIDDEN
    assert mine.me.hand.visibility is ZoneVisibility.OWNER_ONLY
    assert mine.me.grave.visibility is ZoneVisibility.PUBLIC


# ----------------------------------------------------------------------
# 읽기 전용 · 변경 불가
# ----------------------------------------------------------------------


def test_view_exposes_no_mutation_methods(mine):
    for forbidden in (
        "move_card",
        "move",
        "change_life",
        "add_card",
        "remove_card",
        "draw",
        "shuffle",
        "set_phase",
        "apply_effect",
        "mark_used",
        "create_instance",
        "set_result",
        "clone",
    ):
        assert not hasattr(mine, forbidden), f"View 가 {forbidden} 을 노출합니다."
    for holder in (mine.me, mine.me.hand):
        for forbidden in ("append", "insert", "pop", "remove", "place", "clear"):
            assert not hasattr(holder, forbidden), (
                f"{type(holder).__name__} 이 {forbidden} 을 노출합니다."
            )


def test_view_does_not_expose_engine_internals(mine):
    """AI 가 알 필요 없고, 노출하면 내부 구현을 관측에 묶게 된다."""
    for forbidden in ("uses", "allocator", "repository", "rng", "seed", "journal"):
        assert not hasattr(mine, forbidden), f"View 가 {forbidden} 을 노출합니다."


def test_view_objects_are_frozen(mine):
    with pytest.raises(dataclasses.FrozenInstanceError):
        mine.turn_number = 99
    with pytest.raises(dataclasses.FrozenInstanceError):
        mine.me.life_points = 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        mine.me.hand.size = 0
    card = mine.me.hand.cards[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        card.card_id = 1


def test_zone_contents_are_tuples_not_lists(mine):
    assert isinstance(mine.me.hand.cards, tuple)
    assert isinstance(mine.me.zones, tuple)
    assert isinstance(mine.players, tuple)
    with pytest.raises(AttributeError):
        mine.me.hand.cards.append(None)


def test_view_shares_no_mutable_object_with_the_state(state, mine):
    """
    ``return state.hand`` 로는 안 된다. 받은 쪽이 건드리면 원본이 바뀐다.
    """
    assert mine.me.hand.cards is not state.player(0).hand
    for card_view in mine.me.hand.cards:
        for instance in state.player(0).hand:
            assert card_view is not instance
    # counters 도 공유하지 않는다.
    field_card = state.player(0).monster_zone[0]
    field_card.add_counter("SPELL", 2)
    fresh = GameStateView.from_state(state, viewer=0)
    assert fresh.me.monster_zone.cards[0].counters == (("SPELL", 2),)
    field_card.add_counter("SPELL", 1)
    assert fresh.me.monster_zone.cards[0].counters == (("SPELL", 2),)  # 스냅숏 그대로


# ----------------------------------------------------------------------
# 스냅숏 의미론
# ----------------------------------------------------------------------


def test_the_view_does_not_follow_the_state_afterwards(state, mine):
    """
    관측은 만들어진 순간에 고정된다. MCTS 가 한 노드를 평가하는 동안
    원본이 바뀌어도 흔들리지 않아야 한다.
    """
    hand_before = mine.me.hand.size
    lp_before = mine.me.life_points
    phase_before = mine.phase

    state.draw(0, 3)
    state.player(0).change_life(-2000)
    state.turn.advance_phase()
    state.move(state.player(0).monster_zone[0], Zone.GRAVE, to_player=0)

    assert mine.me.hand.size == hand_before
    assert mine.me.life_points == lp_before
    assert mine.phase is phase_before
    assert mine.me.monster_zone.size == 1

    # 다시 만들면 새 값이 보인다.
    fresh = GameStateView.from_state(state, viewer=0)
    assert fresh.me.hand.size == hand_before + 3
    assert fresh.me.life_points == lp_before - 2000
    assert fresh.me.monster_zone.size == 0


def test_two_views_of_the_same_state_are_equal(state):
    a = GameStateView.from_state(state, viewer=0)
    b = GameStateView.from_state(state, viewer=0)
    assert a == b
    assert a.canonical_state() == b.canonical_state()


def test_the_two_viewers_see_different_things(state):
    a = GameStateView.from_state(state, viewer=0)
    b = GameStateView.from_state(state, viewer=1)
    assert a.canonical_state() != b.canonical_state()


# ----------------------------------------------------------------------
# 조회 편의
# ----------------------------------------------------------------------


def test_find_returns_only_what_the_viewer_can_see(state, mine, theirs):
    hidden_hand_card = state.player(0).hand[0]
    public_monster = state.player(0).monster_zone[0]

    assert mine.find(hidden_hand_card.instance_id) is not None
    assert theirs.find(hidden_hand_card.instance_id) is None
    assert theirs.find(public_monster.instance_id) is not None
    assert mine.find(InstanceId(99999)) is None


def test_visible_instances_bound_what_an_action_may_target(state, theirs):
    visible = set(theirs.visible_instances())
    for card in state.player(0).hand:
        assert card.instance_id not in visible
    for card in state.player(0).deck:
        assert card.instance_id not in visible
    # 상대 필드의 뒷면 카드는 지목할 수 있다.
    assert state.player(0).spell_zone[0].instance_id in visible


def test_result_is_readable_once_the_duel_ends(state):
    assert GameStateView.from_state(state, viewer=0).is_over is False
    state.set_result(winner=0, reason="테스트")
    over = GameStateView.from_state(state, viewer=0)
    assert over.is_over is True
    assert over.winner == 0
    assert over.result_reason == "테스트"


# ----------------------------------------------------------------------
# 직렬화
# ----------------------------------------------------------------------


def test_view_serialization_holds_only_value_types(mine):
    def leaves(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from leaves(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from leaves(item)
        else:
            yield value

    for value in leaves(mine.to_dict()):
        assert value is None or isinstance(value, (int, str, bool)), (
            f"관측 직렬화에 값 타입이 아닌 것이 있습니다: {value!r}"
        )
    text = str(mine.to_dict())
    assert "0x" not in text and "object at" not in text


def test_view_serialization_is_deterministic(state):
    a = GameStateView.from_state(state, viewer=0).to_dict()
    b = GameStateView.from_state(state, viewer=0).to_dict()
    import json

    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ----------------------------------------------------------------------
# View -> Action (§18)
# ----------------------------------------------------------------------


def test_an_action_can_be_built_from_what_the_view_shows(state, mine):
    """
    이것이 Phase 2-A 의 목표다. 관측을 보고 의도를 만들 수 있지만,
    만들어도 판은 그대로다.
    """
    from engine.action import PlayerAction
    from engine.action_validation import ActionValidator, ActionValidity

    before = state.state_hash()

    summonable = mine.me.hand.cards[0]
    assert summonable.is_targetable
    action = PlayerAction.normal_summon(actor=mine.viewer, source=summonable.instance_id)

    result = ActionValidator().validate(state, action)
    assert result.validity is ActionValidity.UNKNOWN  # 구조는 맞고, 규칙은 아직 없다
    assert not result.permits_execution
    assert state.state_hash() == before  # 아무 일도 일어나지 않았다
