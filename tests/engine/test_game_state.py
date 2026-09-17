"""engine/state/game_state.py — 초기화, 존 이동, clone 독립, state_hash 결정론."""

import pytest

from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.state.player import DEFAULT_LIFE_POINTS
from engine.state.turn import TurnState
from engine.vocabulary import Phase, Position, Zone

DECK_A = list(range(1000, 1040))  # 40장
DECK_B = list(range(2000, 2040))
EXTRA_A = list(range(3000, 3015))  # 15장


def make_state(**kwargs) -> GameState:
    defaults = dict(decks=(DECK_A, DECK_B), extra_decks=(EXTRA_A, []))
    defaults.update(kwargs)
    return GameState.create(**defaults)


# ----------------------------------------------------------------------
# 초기화
# ----------------------------------------------------------------------


def test_initial_state_has_two_players_with_forty_card_decks():
    state = make_state()

    assert len(state.players) == 2
    for player_id in (0, 1):
        player = state.player(player_id)
        assert player.player_id == player_id
        assert player.life_points == DEFAULT_LIFE_POINTS
        assert len(player.deck) == 40
        assert len(player.hand) == 0
        assert len(player.monster_zone) == 0
        assert len(player.spell_zone) == 0
        assert len(player.grave) == 0

    assert len(state.player(0).extra) == 15
    assert len(state.player(1).extra) == 0


def test_initial_turn_state():
    state = make_state()
    assert state.turn.turn_number == 1
    assert state.turn.turn_player == 0
    assert state.turn.phase is Phase.DRAW
    assert state.turn_player is state.player(0)
    assert state.result is None


def test_deck_order_is_preserved_exactly_as_given():
    """셔플하지 않는다 — 무작위가 들어가면 결정론이 깨진다."""
    state = make_state()
    assert state.player(0).deck.card_ids() == DECK_A
    assert state.player(1).deck.card_ids() == DECK_B


def test_instance_ids_are_unique_across_both_players():
    state = make_state()
    ids = [card.instance_id for card in state.all_instances()]
    assert len(ids) == 40 + 15 + 40
    assert len(set(ids)) == len(ids)


def test_same_card_id_appears_as_distinct_instances():
    state = GameState.create(decks=([2511] * 3, []))
    deck = state.player(0).deck
    assert [c.card_id for c in deck] == [2511, 2511, 2511]
    assert len({c.instance_id for c in deck}) == 3


def test_create_rejects_mismatched_player_ids():
    from engine.state.player import PlayerState

    with pytest.raises(ValueError):
        GameState(players=(PlayerState(player_id=1), PlayerState(player_id=0)))
    with pytest.raises(ValueError):
        GameState(players=(PlayerState(player_id=0),))  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# 존 이동
# ----------------------------------------------------------------------


def test_moving_five_cards_from_deck_to_hand_keeps_counts_exact():
    state = make_state()
    drawn = state.draw(0, 5)

    assert len(drawn) == 5
    assert len(state.player(0).hand) == 5
    assert len(state.player(0).deck) == 35
    assert len(state.player(1).deck) == 40  # 상대는 그대로
    assert state.player(0).hand.card_ids() == DECK_A[:5]
    assert state.player(0).deck.card_ids() == DECK_A[5:]
    assert all(card.zone is Zone.HAND for card in drawn)
    assert all(card.previous.location is Zone.DECK for card in drawn)


def test_draw_from_an_empty_deck_stops_without_deciding_the_duel():
    state = GameState.create(decks=([1, 2], []))
    drawn = state.draw(0, 5)
    assert len(drawn) == 2
    assert len(state.player(0).deck) == 0
    assert state.result is None  # 덱 소진 패배 판정은 Phase 1 의 일이 아니다


def test_move_between_players_changes_controller_not_owner():
    state = make_state()
    card = state.player(0).deck[0]
    state.move(card, Zone.MZONE, to_player=1, position=Position.FACEUP_ATTACK)

    assert card.owner == 0
    assert card.controller == 1
    assert card in state.player(1).monster_zone
    assert card not in state.player(0).deck
    assert len(state.player(0).deck) == 39


def test_move_accepts_an_instance_id():
    state = make_state()
    instance_id = state.player(0).deck[0].instance_id
    state.move(instance_id, Zone.GRAVE)
    assert len(state.player(0).grave) == 1


def test_move_of_an_unknown_instance_raises():
    state = make_state()
    with pytest.raises(KeyError):
        state.move(InstanceId(9999), Zone.GRAVE)


def test_find_instance_and_locate_across_players():
    state = make_state()
    card = state.player(1).deck[3]
    assert state.find_instance(card.instance_id) is card
    assert state.locate(card.instance_id) is state.player(1).deck
    assert state.find_instance(InstanceId(9999)) is None
    assert state.locate(InstanceId(9999)) is None


# ----------------------------------------------------------------------
# clone
# ----------------------------------------------------------------------


def test_clone_does_not_leak_changes_back_to_the_original():
    state = make_state()
    state.draw(0, 5)
    before = state.state_hash()

    copy = state.clone()
    copy.draw(0, 3)
    copy.player(0).change_life(-2000)
    copy.player(0).record_normal_summon()
    copy.player(0).turn_flags.drew_for_turn = True
    copy.player(0).uses.record_card(InstanceId(0))
    copy.player(0).hand[0].add_counter("SPELL")
    copy.player(0).hand[0].materials.append(InstanceId(99))
    copy.turn.begin_next_turn()
    copy.set_result(winner=0, reason="테스트")

    assert len(state.player(0).hand) == 5
    assert state.player(0).life_points == DEFAULT_LIFE_POINTS
    assert state.player(0).normal_summon_used == 0
    assert state.player(0).turn_flags.drew_for_turn is False
    assert len(state.player(0).uses) == 0
    assert state.player(0).hand[0].counter("SPELL") == 0
    assert state.player(0).hand[0].materials == []
    assert state.turn.turn_number == 1
    assert state.result is None
    assert state.state_hash() == before


def test_clone_card_instances_are_distinct_objects():
    state = make_state()
    copy = state.clone()
    for original, cloned in zip(state.all_instances(), copy.all_instances()):
        assert original is not cloned
        assert original.instance_id == cloned.instance_id


def test_clone_shares_the_card_definition_repository():
    state = make_state()
    copy = state.clone()
    assert copy.repository is state.repository


def test_clone_allocator_does_not_collide_with_the_original():
    state = make_state()
    copy = state.clone()
    new_in_copy = copy.create_instance(5555, owner=0, zone=Zone.HAND)
    new_in_original = state.create_instance(5555, owner=0, zone=Zone.HAND)
    # 서로 다른 분기이므로 같은 번호를 쓰는 것이 맞다 (결정론).
    assert new_in_copy.instance_id == new_in_original.instance_id
    assert copy.find_instance(new_in_copy.instance_id) is not new_in_original


# ----------------------------------------------------------------------
# state_hash
# ----------------------------------------------------------------------


def test_identical_states_hash_identically():
    assert make_state().state_hash() == make_state().state_hash()


def test_same_operations_produce_the_same_hash():
    def run() -> str:
        state = make_state()
        state.draw(0, 5)
        state.draw(1, 5)
        state.move(state.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
        state.player(1).change_life(-1500)
        state.player(0).uses.record_effect(0, EffectRef(2511, 1))
        state.turn.advance_phase()
        return state.state_hash()

    assert run() == run()


def test_hash_changes_with_every_tracked_dimension():
    base = make_state()
    baseline = base.state_hash()

    def mutated(fn) -> str:
        state = make_state()
        fn(state)
        return state.state_hash()

    assert mutated(lambda s: s.draw(0, 1)) != baseline
    assert mutated(lambda s: s.player(0).change_life(-1)) != baseline
    assert mutated(lambda s: s.turn.advance_phase()) != baseline
    assert mutated(lambda s: s.turn.begin_next_turn()) != baseline
    assert mutated(lambda s: s.player(0).record_normal_summon()) != baseline
    assert mutated(lambda s: s.player(0).uses.record_card(InstanceId(0))) != baseline
    assert mutated(lambda s: s.player(0).deck[0].add_counter("SPELL")) != baseline
    assert mutated(lambda s: s.set_result(0, "승")) != baseline
    assert (
        mutated(lambda s: s.player(0).deck[0].set_position(Position.FACEUP_ATTACK))
        != baseline
    )


def test_hash_depends_on_zone_order():
    a = make_state()
    b = make_state()
    assert a.state_hash() == b.state_hash()
    b.player(0).deck.insert(0, b.player(0).deck.pop())
    assert a.state_hash() != b.state_hash()


def test_hash_is_a_sha256_hex_digest_not_a_python_hash():
    digest = make_state().state_hash()
    assert len(digest) == 64
    assert all(ch in "0123456789abcdef" for ch in digest)


def test_hash_is_stable_across_processes():
    """``PYTHONHASHSEED`` 가 달라도 같은 값이어야 한다."""
    import subprocess
    import sys

    snippet = (
        "from engine.state.game_state import GameState;"
        "print(GameState.create(decks=(list(range(1000,1040)), [])).state_hash())"
    )
    outputs = set()
    for seed in ("0", "12345"):
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
            cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]),
        )
        assert result.returncode == 0, result.stderr
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1


def test_equality_uses_the_canonical_state():
    a = make_state()
    b = make_state()
    assert a == b
    b.draw(0, 1)
    assert a != b
    assert a != "not a game state"


def test_turn_state_progression_is_state_only():
    turn = TurnState()
    assert turn.phase is Phase.DRAW
    assert turn.advance_phase() is Phase.STANDBY
    turn.set_phase(Phase.END)
    assert turn.advance_phase() is Phase.END  # 엔드에서 더 가지 않는다

    turn.begin_next_turn()
    assert turn.turn_number == 2
    assert turn.turn_player == 1
    assert turn.phase is Phase.DRAW


def test_turn_state_rejects_impossible_values():
    with pytest.raises(ValueError):
        TurnState(turn_number=0)
    with pytest.raises(ValueError):
        TurnState(turn_player=2)
    with pytest.raises(ValueError):
        TurnState(step=-1)
    with pytest.raises(ValueError):
        TurnState().set_phase(Phase.MAIN1, step=-1)
    with pytest.raises(ValueError):
        TurnState(phase=Phase.DAMAGE).advance_phase()  # 턴 순서에 없는 페이즈
