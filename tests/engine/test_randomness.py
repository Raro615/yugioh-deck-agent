"""
Phase 2-Z — 재현 가능한 무작위 (deterministic randomness).

두 원칙이 이 파일이 지키는 전부다.

    1. 랜덤이어도 재현 가능해야 한다.
    2. 게임 규칙의 랜덤과 AI 의 랜덤은 서로 다른 계층이다.

    seed → RandomSource → RandomOutcome → EventJournal
                  ↓
           ShuffleOperation → ZoneShuffled → ObservedEvent   (기존 통로)

**실제 카드를 늘리는 단계가 아니다.** 여기 있는 정의는 전부 synthetic
이고, 출처가 ``hand_written`` 이라고 적혀 있다 — 아무 카드의 의미도
주장하지 않는다 (§13).
"""

import ast
import pathlib
import random

import pytest

from engine.condition import PlayerRef
from engine.cost import CostGroup
from engine.effect.definition import EffectDefinition, EffectProvenance
from engine.effect.delta import ZoneShuffled
from engine.effect.executor import (
    OPERATION_HANDLERS,
    SUPPORTED,
    EffectExecutor,
    EffectImplementationRegistry,
)
from engine.effect.journal import EventJournal
from engine.effect.operation import (
    SHUFFLEABLE_ZONES,
    OperationKind,
    ShuffleOperation,
)
from engine.effect.resolution import ResolutionContext, ResolutionStatus
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.randomness import (
    RandomError,
    RandomOutcome,
    RandomPurpose,
    RandomSource,
)
from engine.state.game_state import GameState
from engine.state.zones import ZoneReorderError
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1
LAB = 999003  # synthetic 정의의 자리. 실제 카드 번호가 아니다.

#: 서로 다른 네 장. 섞였는지 보려면 구분되는 카드가 필요하다.
A, B, C, D = 55144522, 66719324, 5318639, 83764718
FEATHERMAN = 21844576


def cards(*values: int) -> tuple[InstanceId, ...]:
    return tuple(InstanceId(v) for v in values)


# ======================================================================
# A. 난수원 — 같은 seed 는 같은 결과 (§12 A · B · C)
# ======================================================================


def test_a_the_same_seed_gives_the_same_choice():
    left, right = RandomSource.seeded(42), RandomSource.seeded(42)
    pool = cards(1, 2, 3, 4, 5)

    first = [left.choose(pool).selected for _ in range(10)]
    second = [right.choose(pool).selected for _ in range(10)]

    assert first == second


def test_a_the_same_seed_gives_the_same_shuffle():
    left, right = RandomSource.seeded(7), RandomSource.seeded(7)
    pool = cards(1, 2, 3, 4)

    assert left.shuffle(pool).selected == right.shuffle(pool).selected
    assert left.shuffle(pool).selected == right.shuffle(pool).selected


def test_a_a_different_seed_may_give_a_different_answer():
    """
    "달라야 한다" 가 아니라 **"달라질 수 있다"** 이다. 한 번 뽑아서
    우연히 같을 수 있으므로 여러 번 뽑아 수열 전체를 본다.
    """
    pool = cards(*range(1, 9))
    first = [RandomSource.seeded(1).shuffle(pool).selected for _ in range(1)]
    other = [RandomSource.seeded(2).shuffle(pool).selected for _ in range(1)]

    assert first != other


def test_a_the_draw_number_is_the_replay_coordinate():
    """
    실패한 시나리오를 **몇 번째 무작위에서 갈렸는가**로 되짚을 수 있어야
    한다.
    """
    source = RandomSource.seeded(3)
    pool = cards(1, 2, 3)

    assert source.draws == 0
    first = source.choose(pool)
    second = source.choose(pool)

    assert (first.draw, second.draw) == (0, 1)
    assert source.draws == 2

    # 같은 좌표로 되짚으면 같은 답이 나온다.
    replay = RandomSource.seeded(3)
    replay.choose(pool)
    assert replay.choose(pool).selected == second.selected


def test_a_the_global_random_module_is_refused():
    """전역 난수를 받아들이면 다른 코드가 재현을 깨뜨릴 수 있다."""
    with pytest.raises(TypeError, match="전역"):
        RandomSource(random)  # type: ignore[arg-type]


def test_a_an_empty_pool_is_refused():
    """§11 — 빈 후보에서 고르지 않는다. 조용히 넘어가지도 않는다."""
    source = RandomSource.seeded(1)

    with pytest.raises(RandomError, match="고를 것이 없습니다"):
        source.choose(())
    # **꺼내지 않았으므로 좌표도 움직이지 않는다.**
    assert source.draws == 0


# ======================================================================
# B. 복제 독립 (§12 D · E)
# ======================================================================


def test_b_a_clone_carries_the_same_position():
    source = RandomSource.seeded(11)
    source.choose(cards(1, 2, 3))

    copy = source.clone()

    assert copy.draws == source.draws
    assert copy.canonical_state() == source.canonical_state()
    assert copy == source


def test_b_consuming_the_original_does_not_disturb_the_clone():
    """§12 E — 원본에서 꺼내도 사본의 다음 결과는 그대로다."""
    source = RandomSource.seeded(11)
    copy = source.clone()
    pool = cards(1, 2, 3, 4, 5)

    expected = [copy.choose(pool).selected for _ in range(5)]
    # 원본을 실컷 소비한다.
    for _ in range(50):
        source.choose(pool)

    again = RandomSource.seeded(11).clone()
    assert [again.choose(pool).selected for _ in range(5)] == expected


def test_b_the_clone_and_the_original_diverge_independently():
    source = RandomSource.seeded(11)
    copy = source.clone()

    left = [source.choose(cards(1, 2, 3)).selected for _ in range(3)]
    right = [copy.choose(cards(1, 2, 3)).selected for _ in range(3)]

    assert left == right  # 같은 자리에서 갈라졌으므로 같은 길을 간다
    assert source.canonical_state() == copy.canonical_state()


# ======================================================================
# C. 셔플 — 카드 집합 보존 (§6 · §12 F · G)
# ======================================================================


def test_c_a_shuffle_keeps_exactly_the_same_cards():
    pool = cards(1, 2, 3, 4, 5, 6, 7)
    source = RandomSource.seeded(9)

    for _ in range(20):
        outcome = source.shuffle(pool)
        assert sorted(i.value for i in outcome.selected) == [1, 2, 3, 4, 5, 6, 7]
        assert len(set(outcome.selected)) == len(outcome.selected)


def test_c_a_shuffle_of_nothing_is_nothing():
    """0장을 섞어도 거부하지 않는다 — 고를 것이 없는 것과 다른 일이다."""
    outcome = RandomSource.seeded(1).shuffle(())

    assert outcome.selected == ()
    assert outcome.candidates == ()


def test_c_an_outcome_that_loses_or_invents_a_card_is_refused():
    """
    :class:`RandomOutcome` 이 **생성 시점에** 확인한다. 카드가 복제되거나
    사라진 결과는 만들어지지 않는다.
    """
    with pytest.raises(ValueError, match="후보에 없던 것"):
        RandomOutcome(
            purpose=RandomPurpose.RANDOM_SELECTION,
            draw=0,
            candidates=cards(1, 2),
            selected=cards(3),
        )
    with pytest.raises(ValueError, match="잃거나 만들지"):
        RandomOutcome(
            purpose=RandomPurpose.DECK_SHUFFLE,
            draw=0,
            candidates=cards(1, 2, 3),
            selected=cards(1, 2),
        )


def test_c_the_primitive_never_sees_a_card():
    """
    원시 연산은 **자리 번호만** 다룬다. 정체를 손에 쥐지 않으므로 난수원을
    통해 숨은 정보가 샐 수 없다.
    """
    source = RandomSource.seeded(4)

    order = source.next_permutation(5)
    assert sorted(order) == [0, 1, 2, 3, 4]
    assert all(isinstance(i, int) for i in order)
    assert 0 <= source.next_index(5) < 5


# ======================================================================
# D. 판과의 연결 (§2 · §9)
# ======================================================================


def board(repository, seed: int | None = 1, deck=(A, B, C, D)) -> GameState:
    game = GameState.create(repository, decks=(list(deck), [FEATHERMAN] * 5), seed=seed)
    game.turn.set_phase(Phase.MAIN1)
    return game


@requires_official_db
def test_d_a_state_without_a_seed_has_no_randomness(repository):
    """조용히 전역 난수로 넘어가지 않는다."""
    game = board(repository, seed=None)

    with pytest.raises(RuntimeError, match="seed 없이"):
        game.randomness


@requires_official_db
def test_d_the_same_seed_builds_the_same_shuffled_deck(repository):
    left = GameState.create(repository, decks=([A, B, C, D], []), seed=5, shuffle=True)
    right = GameState.create(repository, decks=([A, B, C, D], []), seed=5, shuffle=True)

    assert left.player(MINE).deck.card_ids() == right.player(MINE).deck.card_ids()
    assert sorted(left.player(MINE).deck.card_ids()) == sorted([A, B, C, D])


@requires_official_db
def test_d_shuffling_without_a_seed_is_refused(repository):
    with pytest.raises(ValueError, match="seed 가 필요"):
        GameState.create(repository, decks=([A, B], []), shuffle=True)


@requires_official_db
def test_d_the_board_hash_does_not_carry_the_rng_position(repository):
    """
    §9 — **난수원의 위치는 판의 모양이 아니다.**

    ``chain`` · ``journal`` · 우선권을 해시에서 뺀 것과 같은 이유다.
    넣으면 "같은 판은 어떤 경로로 왔든 같은 해시" 가 깨진다 — 판이
    똑같은데 몇 번 뽑았느냐로 해시가 달라진다.
    """
    left, right = board(repository), board(repository)
    assert left.state_hash() == right.state_hash()

    # 한쪽만 난수를 잔뜩 꺼낸다. **판은 건드리지 않는다.**
    for _ in range(10):
        left.randomness.choose(cards(1, 2, 3))

    assert left.randomness.draws == 10
    assert right.randomness.draws == 0
    assert left.state_hash() == right.state_hash()
    assert left.canonical_state() == right.canonical_state()


@requires_official_db
def test_d_the_rng_position_has_its_own_canonical_form(repository):
    """
    해시에 넣지 않는다고 **값으로 비교할 수 없는 것은 아니다.**
    객체 주소도 ``repr`` 도 아닌 표현이 따로 있다.
    """
    left, right = board(repository), board(repository)

    assert left.randomness.canonical_state() == right.randomness.canonical_state()
    left.randomness.choose(cards(1, 2, 3))
    assert left.randomness.canonical_state() != right.randomness.canonical_state()

    # 주소도 repr 도 들어가지 않는다.
    rendered = repr(left.randomness.canonical_state())
    assert "0x" not in rendered
    assert "object at" not in rendered


@requires_official_db
def test_d_cloning_the_board_clones_the_rng_position(repository):
    """§12 D · E — 판을 복제하면 난수원도 **꺼낸 횟수까지** 복제된다."""
    game = board(repository)
    game.randomness.choose(cards(1, 2, 3))

    copy = game.clone()
    assert copy.randomness.draws == game.randomness.draws == 1
    assert copy.randomness.canonical_state() == game.randomness.canonical_state()

    expected = copy.randomness.choose(cards(1, 2, 3, 4)).selected
    for _ in range(20):
        game.randomness.choose(cards(1, 2, 3, 4))

    fresh = board(repository)
    fresh.randomness.choose(cards(1, 2, 3))
    assert fresh.clone().randomness.choose(cards(1, 2, 3, 4)).selected == expected


# ======================================================================
# synthetic 정의 — 아무 카드의 의미도 주장하지 않는다
# ======================================================================


def shuffle_effect(zone: Zone = Zone.DECK, who=PlayerRef.CONTROLLER, ordinal=0):
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        operations=(ShuffleOperation(zone, who),),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(
            verified=True, note="Phase 2-Z 무작위 시험"
        ),
    )


def run(state, definition, journal=None):
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        journal=journal,
    )
    return executor.execute(
        state,
        definition,
        ResolutionContext(effect_ref=definition.effect_ref, controller=MINE),
    )


# ======================================================================
# E. Operation 통합 (§5 · §12 H · I)
# ======================================================================


def test_e_shuffle_joined_the_existing_handler_table():
    """
    §5 — 새 실행 통로를 만들지 않았다. 표에 **한 줄**이 늘었을 뿐이다.
    """
    assert OperationKind.SHUFFLE in SUPPORTED
    handler = OPERATION_HANDLERS[OperationKind.SHUFFLE]
    assert callable(handler.plan) and callable(handler.apply)
    assert handler.note


def test_e_shuffle_claims_no_reason():
    """
    섞기는 카드에 **아무 일도 하지 않는다.** ``MOVE`` 처럼 ``REASON_*`` 을
    주장하지 않는 것이 사실이다.
    """
    assert ShuffleOperation(Zone.DECK).reason_names == ()
    assert ShuffleOperation(Zone.DECK).target_refs == ()


def test_e_only_ordered_zones_may_be_shuffled():
    """
    칸 방식 존은 "몇 번째" 가 칸 번호라 순서를 바꾸는 것이 곧 이동이고,
    묘지는 룰북이 순서를 바꾸지 말라고 말한다.
    """
    assert SHUFFLEABLE_ZONES == frozenset({Zone.DECK, Zone.EXTRA})
    for zone in (Zone.MZONE, Zone.SZONE, Zone.GRAVE, Zone.HAND):
        with pytest.raises(ValueError, match="섞을 수 있는 존이 아닙니다"):
            ShuffleOperation(zone)


@requires_official_db
def test_e_a_shuffle_runs_the_whole_pipeline(repository):
    """§5 — plan → apply → StateDelta → EventReader → EventJournal."""
    game = board(repository)
    before = game.player(MINE).deck.card_ids()
    hash_before = game.state_hash()
    journal = EventJournal()

    result = run(game, shuffle_effect(), journal)

    assert result.status is ResolutionStatus.RESOLVED
    (applied,) = result.applied
    assert applied.kind is OperationKind.SHUFFLE
    (delta,) = result.deltas
    assert isinstance(delta, ZoneShuffled)
    assert (delta.player, delta.zone, delta.size) == (MINE, Zone.DECK, 4)
    assert len(journal) == 1
    assert game.state_hash() != hash_before
    assert sorted(game.player(MINE).deck.card_ids()) == sorted(before)


@requires_official_db
def test_e_the_same_seed_shuffles_the_deck_the_same_way(repository):
    """§6 — Deck [A,B,C,D] + seed → 언제나 같은 결과."""
    left, right = board(repository), board(repository)

    run(left, shuffle_effect())
    run(right, shuffle_effect())

    assert left.player(MINE).deck.card_ids() == right.player(MINE).deck.card_ids()
    assert left.state_hash() == right.state_hash()


@requires_official_db
def test_e_a_different_seed_may_shuffle_differently(repository):
    left = board(repository, seed=1)
    right = board(repository, seed=2)

    run(left, shuffle_effect())
    run(right, shuffle_effect())

    assert left.player(MINE).deck.card_ids() != right.player(MINE).deck.card_ids()
    assert sorted(left.player(MINE).deck.card_ids()) == sorted(
        right.player(MINE).deck.card_ids()
    )


@requires_official_db
def test_e_the_delta_does_not_reveal_the_new_order(repository):
    """
    §7 — 섞은 뒤의 덱 순서는 **아무도 모르는 것이 규칙**이다. 변화에
    적어 두면 그것을 읽는 쪽이 알게 된다.
    """
    game = board(repository)

    result = run(game, shuffle_effect())
    (delta,) = result.deltas
    rendered = repr(delta.to_dict()) + delta.describe_ko()

    for card_id in (A, B, C, D):
        assert str(card_id) not in rendered
    assert set(delta.to_dict()) == {"kind", "player", "zone", "size", "draw"}


@requires_official_db
def test_e_the_event_layer_is_honest_about_having_no_name(repository):
    """
    "덱을 섞었을 때" 라는 시점이 **없다.** 지어내지 않고
    ``UNIMPLEMENTED`` 로 남긴다 — "사건이 없었다" 가 아니라 "옮길 이름이
    없었다" 다.
    """
    game = board(repository)

    result = run(game, shuffle_effect())
    (event,) = EventReader(
        GameStateView.from_state(game, viewer=MINE)
    ).read(result, actor=MINE)

    assert event.is_observable is False
    assert event.timing.note
    assert event.event_id


@requires_official_db
def test_e_the_random_happens_while_planning_not_while_applying(repository):
    """
    계획 단계에서 결과를 확정한다. 적용 중에 난수를 꺼내면 "계획을 전부
    확인한 뒤에 적용한다" 가 깨진다.
    """
    game = board(repository)

    run(game, shuffle_effect())

    # 한 번의 셔플에 **한 번**만 꺼냈다.
    assert game.randomness.draws == 1


@requires_official_db
def test_e_reordering_refuses_a_broken_permutation(repository):
    """카드를 잃거나 만드는 재배열은 존이 거부한다."""
    game = board(repository)
    deck = game.player(MINE).zone(Zone.DECK)

    with pytest.raises(ZoneReorderError, match="순열이 맞지 않습니다"):
        deck.reorder((0, 0, 1, 2))
    with pytest.raises(ZoneReorderError, match="칸 방식"):
        game.player(MINE).zone(Zone.MZONE).reorder(())


# ======================================================================
# F. 실패 안전성 (§11 · §12 J)
# ======================================================================


@requires_official_db
def test_f_a_shuffle_without_a_seed_changes_nothing(repository):
    """§11 — 실패는 **변경 전에** 끝난다."""
    game = board(repository, seed=None)
    before = game.state_hash()
    order = game.player(MINE).deck.card_ids()
    journal = EventJournal()

    result = run(game, shuffle_effect(), journal)

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "seed" in (result.missing or "")
    assert result.applied == ()
    assert result.deltas == ()
    assert game.state_hash() == before
    assert game.player(MINE).deck.card_ids() == order
    assert len(journal) == 0
    assert EventReader(
        GameStateView.from_state(game, viewer=MINE)
    ).read(result, actor=MINE) == ()


@requires_official_db
def test_f_a_failed_shuffle_does_not_consume_the_rng(repository):
    """
    실패한 뒤 같은 판을 다시 돌리면 **같은 결과**가 나와야 한다. 실패가
    난수원만 소비하고 끝나면 그것이 깨진다.
    """
    game = board(repository)
    # 섞을 수 없는 존은 조작 생성 시점에 막히므로, 여기서는 빈 덱을 쓴다.
    empty = board(repository, deck=())
    assert empty.randomness.draws == 0

    result = run(empty, shuffle_effect())

    # 0장을 섞는 것은 실패가 아니다 — 할 일이 없을 뿐이다.
    assert result.status is ResolutionStatus.RESOLVED
    assert empty.randomness.draws == 1
    assert game.randomness.draws == 0


# ======================================================================
# G. 숨은 정보 (§7 · §12 K)
# ======================================================================


@requires_official_db
def hidden_hand(repository) -> GameState:
    game = GameState.create(
        repository, decks=([FEATHERMAN] * 10, [A, B, C, D] + [FEATHERMAN] * 6), seed=3
    )
    game.draw(MINE, 2)
    game.draw(THEIRS, 4)
    game.turn.set_phase(Phase.MAIN1)
    return game


@requires_official_db
def test_g_the_engine_knows_the_pick_but_the_observation_does_not(repository):
    """
    §7 — 상대 패 [A,B,C,D] 에서 무작위로 1장.

    엔진 내부는 어느 ``InstanceId`` 인지 안다. **관측은 여전히 모른다** —
    무작위였다는 사실이 정체를 공개하는 근거가 되지 않는다.
    """
    game = hidden_hand(repository)
    pool = tuple(card.instance_id for card in game.player(THEIRS).hand)
    assert len(pool) == 4

    outcome = game.randomness.choose(pool, RandomPurpose.RANDOM_SELECTION)

    # A — 엔진은 안다.
    assert outcome.selected[0] in pool
    chosen = game.find_instance(outcome.selected[0])
    assert chosen is not None and chosen.card_id in (A, B, C, D)

    # B — MINE 의 관측은 상대 패를 여전히 보지 못한다.
    view = GameStateView.from_state(game, viewer=MINE)
    assert view.player(THEIRS).zone(Zone.HAND).concealed is True
    assert view.player(THEIRS).zone(Zone.HAND).cards == ()


@requires_official_db
def test_g_the_public_summary_names_nothing(repository):
    """
    §4 — 밖으로 나가는 요약에는 **몇 장 중 몇 장**만 있다.
    """
    game = hidden_hand(repository)
    pool = tuple(card.instance_id for card in game.player(THEIRS).hand)
    identities = [game.find_instance(i).card_id for i in pool]

    outcome = game.randomness.choose(pool, RandomPurpose.RANDOM_SELECTION)
    summary = outcome.public_summary()

    assert summary == {
        "purpose": "random_selection",
        "candidate_count": 4,
        "selected_count": 1,
    }
    rendered = repr(summary) + outcome.describe_ko()
    for card_id in identities:
        assert str(card_id) not in rendered
    for instance in pool:
        assert str(instance.value) not in rendered


def test_g_the_internal_record_is_marked_as_internal():
    """
    ``to_dict`` 은 정체를 담는다 — **엔진 내부 기록**이기 때문이다.
    둘을 한 메서드로 합치지 않는다.
    """
    outcome = RandomOutcome(
        purpose=RandomPurpose.RANDOM_SELECTION,
        draw=0,
        candidates=cards(7, 8, 9),
        selected=cards(8),
    )

    assert outcome.to_dict()["selected"] == [8]
    assert "selected" not in outcome.public_summary()
    assert "candidates" not in outcome.public_summary()


# ======================================================================
# H. 경계 — 게임 RNG ≠ AI RNG (§8 · §14)
# ======================================================================


def test_h_only_rule_randomness_has_a_purpose():
    """
    §8 — ``AI_*`` 목적이 **없다.** 한 열거형에 섞으면 같은 난수원을 쓰게
    되고, AI 가 한 번 더 생각했다는 이유로 듀얼의 결과가 달라진다.
    """
    assert {p.value for p in RandomPurpose} == {"deck_shuffle", "random_selection"}
    for name in dir(RandomPurpose):
        assert not name.startswith("AI")


def test_h_the_engine_never_touches_the_global_random():
    """
    §2 — 엔진 코드가 ``random.choice`` · ``random.shuffle`` 을 직접 부르지
    않는다. 전역 :mod:`random` 을 import 해도 되는 곳은 난수원을 만드는
    두 파일뿐이다.
    """
    allowed = {"engine/randomness.py", "engine/state/game_state.py"}
    offenders = []
    for path in sorted(ROOT.glob("engine/**/*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if relative in allowed:
            continue
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == "random" for alias in node.names
            ):
                offenders.append(relative)
            if isinstance(node, ast.ImportFrom) and node.module == "random":
                offenders.append(relative)
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "random"
            ):
                offenders.append(relative)

    assert offenders == []


def test_h_no_ai_policy_entered_the_randomness_layer():
    """
    §14 — 무작위는 "규칙이 요구하니까" 일어난다. "무엇이 더 좋은가" 는
    AI 의 질문이고 이 계층에 들어오지 않았다.
    """
    source = (ROOT / "engine" / "randomness.py").read_text("utf-8")
    tree = ast.parse(source)
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }

    for forbidden in ("policy", "score", "best", "prefer", "evaluate", "search"):
        assert not any(forbidden in name.lower() for name in names), forbidden


def test_h_no_new_execution_architecture_was_built():
    """§14 — 새 RandomBus · RandomEngine · EventBus 가 없다."""
    defined = set()
    for path in sorted(ROOT.glob("engine/**/*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        defined |= {
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        }

    for forbidden in ("RandomBus", "RandomEngine", "EventBus", "ReplayEngine"):
        assert forbidden not in defined
    assert not any("Bus" in name for name in defined)


# ======================================================================
# I. 결정론 전체 (§12 L · M)
# ======================================================================


@requires_official_db
def test_i_the_whole_run_is_reproducible(repository):
    """
    §12 L · M — 같은 seed · 같은 입력이면 결과도 판도 기록도 같다.
    """
    def once():
        game = board(repository)
        journal = EventJournal()
        result = run(game, shuffle_effect(), journal)
        return (
            result.canonical_state(),
            game.state_hash(),
            game.canonical_state(),
            game.randomness.canonical_state(),
            tuple(
                event.event_id
                for event in EventReader(
                    GameStateView.from_state(game, viewer=MINE)
                ).read(result, actor=MINE)
            ),
        )

    assert once() == once()


@requires_official_db
def test_i_a_clone_runs_without_disturbing_the_original(repository):
    """§12 D — 사본에서 섞어도 원본의 판도 난수원도 그대로다."""
    game = board(repository)
    order = game.player(MINE).deck.card_ids()
    before = game.state_hash()
    position = game.randomness.canonical_state()

    copy = game.clone()
    result = run(copy, shuffle_effect())

    assert result.status is ResolutionStatus.RESOLVED
    assert game.player(MINE).deck.card_ids() == order
    assert game.state_hash() == before
    assert game.randomness.canonical_state() == position
    assert copy.randomness.canonical_state() != position


# ======================================================================
# J. 실제 Lua 조사 (§13) — 무엇이 있고 무엇을 안 옮겼는가
# ======================================================================


def test_j_the_real_scripts_use_these_random_primitives():
    """
    §13 — **실제 카드를 늘리지 않는다.** 대신 코퍼스에 무엇이 있는지
    세어서, 이번에 옮긴 것과 옮기지 않은 것을 사실로 적어 둔다.

    추측해서 고른 이름이 하나도 없다는 것을 이 테스트가 고정한다.
    """
    import re

    scripts = sorted(ROOT.glob("c*.lua"))
    assert len(scripts) > 12_000

    def used(pattern: str) -> int:
        compiled = re.compile(pattern)
        return sum(
            1
            for path in scripts
            if compiled.search(path.read_text("utf-8", errors="replace"))
        )

    # 이번에 기반을 만든 것 — 덱 셔플
    assert used(r"SEQ_DECKSHUFFLE") > 400
    assert used(r"Duel\.ShuffleDeck") > 200

    # 이번에 **만들지 않은 것.** 있다는 것은 알지만 옮기지 않았다.
    assert used(r"\bRandomSelect\b") > 100  # "무작위로 고른다"
    assert used(r"Duel\.TossDice") > 0  # 주사위
    assert used(r"Duel\.TossCoin") > 0  # 동전
    assert used(r"Duel\.ShuffleHand") > 400  # 패 셔플


def test_j_coin_and_dice_were_deliberately_left_out():
    """
    §3 — "실제 카드 효과용 API 를 과도하게 확장하지 않는다."

    동전(30장) · 주사위(57장)는 코퍼스에 있지만 API 를 만들지 않았다.
    만들면 결과 범위 · 재굴림 · "동전을 던졌을 때" 트리거까지 규칙이
    따라오는데 그 계층이 없다. 없는 것을 있는 척 만들지 않는다.
    """
    assert not hasattr(RandomSource, "toss_coin")
    assert not hasattr(RandomSource, "roll_dice")
    assert not hasattr(RandomSource, "randint")
    # 원시 연산 둘과 그 위의 둘이 전부다.
    public = {
        name
        for name in dir(RandomSource)
        if not name.startswith("_")
    }
    assert public == {
        "choose",
        "choose_many",  # Phase 2-AB — 한 장을 고르는 것의 수가 늘었을 뿐이다
        "shuffle",
        "next_index",
        "next_permutation",
        "clone",
        "canonical_state",
        "draws",
        "raw",
        "seeded",
    }
