"""
Phase 2-AB — 무작위 선택 (random selection).

    Effect
      → CandidateResolver     후보를 **센다**
      → RandomSource          자리 번호를 **고른다**
      → Selection             골라진 카드
      → 기존 Operation        실제 상태 변경
      → StateDelta → Event → Journal

한 줄 목표: **Phase 2-Z 의 재현 가능한 난수를 실제 효과의 무작위 선택에
잇는다.**

두 가지를 끝까지 나눈다
-----------------------
========================  ==========================================
후보가 무엇인가             ``CandidateResolver`` — 판을 읽는다
그중 무엇을 고르는가         ``RandomSource`` — **카드를 보지 않는다**
========================  ==========================================

난수원이 판을 뒤지며 카드를 고르지 않는다. 자리 번호만 답한다.

플레이어 선택과 다르다
----------------------
"상대 패에서 1장을 고른다" 는 고르는 사람이 후보를 **봐야** 하고,
"상대 패에서 무작위로 1장" 은 아무도 볼 필요가 없다. 그래서 명세가
다르다 — :class:`RandomSelectionSpec` 에는 ``chooser`` 칸이 없다.

실제 카드
---------
**무정의 말살 (73148972)** — 한 카드 안에 플레이어 선택과 무작위 선택이
나란히 있다. 이 구분을 검증하기에 이보다 나은 카드가 없다.
"""

import ast
import pathlib
import re

import pytest

from engine.action import PlayerAction
from engine.activation import ActivationStatus, EffectActivator
from engine.chain import Chain, ChainResolver
from engine.condition import IsMonster, PlayerRef, UnimplementedRule
from engine.cost import CandidateSource, ChoiceSpec, CostGroup, Selection
from engine.effect.definition import EffectDefinition, EffectProvenance
from engine.effect.delta import ZoneMoved
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.library import (
    RUTHLESS_DENIAL,
    build_executor,
    definition_registry,
    entry_for,
    implementation_registry,
)
from engine.effect.operation import CardOperation, DrawOperation, OperationKind
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.target import (
    PRIMARY_TARGET,
    RandomSelectionSpec,
    TargetBinding,
    TargetRef,
    TargetRequirement,
    TargetSpec,
)
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.observation import ObservationPermission
from engine.observation_grant import ObservationGrant, derive_policy
from engine.randomness import RandomPurpose, RandomSource
from engine.state.game_state import GameState
from engine.validation import ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
P1, P2 = 0, 1
LAB = 999_004  # synthetic 정의의 자리. 실제 카드 번호가 아니다.
GRANTED = ValidationResult.valid()

# 서로 다른 네 장. 같은 카드로 채우면 "어느 것이 골라졌는가" 를 알 수 없다.
A, B, C, D = 55144522, 66719324, 5318639, 83764718
MINE_1, MINE_2 = 70368879, 15103313
FILLER = 21844576


def new_state(repository, seed: int | None = 7) -> GameState:
    """
    P1 MZONE: 몬스터 / 패: 2장 / 묘지: 1장
    P2 패: A B C D / MZONE: 몬스터 / 묘지: 1장
    """
    game = GameState.create(
        repository,
        decks=(
            [FILLER] * 4 + [MINE_1, MINE_2] + [FILLER] * 10,
            [A, B, C, D] + [FILLER] * 12,
        ),
        seed=seed,
    )
    game.draw(P1, 5)
    game.draw(P2, 6)
    game.move(
        game.player(P1).hand[0].instance_id, Zone.MZONE, to_player=P1,
        position=Position.FACEUP_ATTACK,
    )
    game.move(game.player(P1).hand[0].instance_id, Zone.GRAVE, to_player=P1)
    game.move(
        game.player(P2).hand[-1].instance_id, Zone.MZONE, to_player=P2,
        position=Position.FACEUP_ATTACK,
    )
    game.move(game.player(P2).hand[-1].instance_id, Zone.GRAVE, to_player=P2)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def random_spec(zones, owner, count=1, require=None, replacement=False):
    return RandomSelectionSpec(
        source=CandidateSource(
            zones=frozenset(zones), owner=owner, require=require
        ),
        count=count,
        replacement=replacement,
    )


def synthetic(spec, operation=None, ordinal=0, provenance=None):
    """
    **synthetic 정의.** 출처가 ``hand_written`` 이라고 적혀 있고, 아무
    카드의 의미도 주장하지 않는다.
    """
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        targets=TargetBinding.single(TargetSpec.at_random(spec)),
        operations=(
            operation or CardOperation.send_to_grave(PRIMARY_TARGET),
        ),
        cost=CostGroup(),
        provenance=provenance
        or EffectProvenance.hand_written(verified=True, note="Phase 2-AB 시험"),
    )


def run(state, definition, journal=None, registered=True):
    executor = EffectExecutor(
        lookup=(
            EffectImplementationRegistry((definition.effect_ref,))
            if registered
            else None
        ),
        journal=journal,
    )
    return executor.execute(
        state,
        definition,
        ResolutionContext(effect_ref=definition.effect_ref, controller=P1),
    )


def hand_ids(game, owner):
    return [card.card_id for card in game.player(owner).hand]


def grave_ids(game, owner):
    return [card.card_id for card in game.player(owner).grave]


# ======================================================================
# A. 후보군 — 자리마다 (§19 A)
# ======================================================================


ZONE_CASES = [
    ("자기 패", (Zone.HAND,), PlayerRef.CONTROLLER, P1),
    ("상대 패", (Zone.HAND,), PlayerRef.OPPONENT, P2),
    ("자기 필드", (Zone.MZONE,), PlayerRef.CONTROLLER, P1),
    ("상대 필드", (Zone.MZONE,), PlayerRef.OPPONENT, P2),
    ("자기 묘지", (Zone.GRAVE,), PlayerRef.CONTROLLER, P1),
    ("상대 묘지", (Zone.GRAVE,), PlayerRef.OPPONENT, P2),
]


@pytest.mark.parametrize("label,zones,owner,side", ZONE_CASES)
def test_a_every_zone_can_be_a_candidate_source(state, label, zones, owner, side):
    """
    §5 — 여섯 자리 전부에서 후보를 셀 수 있다.

    **상대 패도 된다.** 고르는 사람이 없으므로 볼 필요가 없고, 후보를
    세는 것은 엔진이다.
    """
    expected = len(state.player(side).zone(zones[0]))
    assert expected > 0, label

    result = run(state, synthetic(random_spec(zones, owner)))

    assert result.status is ResolutionStatus.RESOLVED, label
    (applied,) = result.applied
    assert len(applied.instances) == 1, label
    picked = applied.instances[0]
    # 고른 것이 **그 자리에 있던 카드**다.
    assert state.locate(picked).zone is Zone.GRAVE, label


def test_a_counting_candidates_is_not_choosing_them():
    """
    §3 — 난수원은 **판을 뒤지지 않는다.** 후보를 세는 코드와 고르는
    코드가 다른 파일에 있다.
    """
    source = (ROOT / "engine" / "randomness.py").read_text("utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "engine.state.game_state" not in imported
    assert "engine.game_state_view" not in imported
    assert "engine.cost.resolver" not in imported

    # 문서에 이름이 적히는 것과 **코드가 그것을 만지는 것**은 다르다.
    # 문자열 검색은 그 둘을 구별하지 못하므로 식별자만 본다.
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    used |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "GameState" not in used
    assert not used & {"locate", "player", "zone", "hand", "deck", "grave"}


# ======================================================================
# B · C. 단일 선택과 결정론 (§19 B · C)
# ======================================================================


def test_b_exactly_one_card_is_chosen(state):
    before = len(state.player(P2).hand)

    result = run(state, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)))

    (applied,) = result.applied
    assert len(applied.instances) == 1
    assert len(state.player(P2).hand) == before - 1
    assert state.randomness.draws == 1


def test_b_a_count_of_two_chooses_two_distinct_cards(state):
    result = run(
        state, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT, count=2))
    )

    (applied,) = result.applied
    assert len(applied.instances) == 2
    assert len(set(applied.instances)) == 2  # 같은 카드를 두 번 고르지 않는다


def test_c_the_same_seed_chooses_the_same_card(repository):
    """§19 C — 같은 seed · 같은 판 · 같은 순서 → 같은 결과."""
    picks = []
    for _ in range(3):
        game = new_state(repository, seed=1234)
        result = run(game, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)))
        picks.append(game.find_instance(result.applied[0].instances[0]).card_id)

    assert len(set(picks)) == 1
    assert picks[0] in (A, B, C, D)


def test_c_a_different_seed_may_choose_differently(repository):
    seen = set()
    for seed in range(1, 15):
        game = new_state(repository, seed=seed)
        result = run(game, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)))
        seen.add(game.find_instance(result.applied[0].instances[0]).card_id)

    assert len(seen) > 1, "seed 를 바꿔도 언제나 같은 카드가 나온다"


def test_c_candidate_ordering_is_the_existing_deterministic_one(repository):
    """
    §10 — 후보 순서가 결정론의 일부다. ``set()`` 으로 순서를 부수지
    않는다. 같은 판을 두 번 만들면 결과도 같다.
    """
    left, right = new_state(repository, seed=5), new_state(repository, seed=5)

    first = run(left, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)))
    second = run(right, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)))

    assert first.canonical_state() == second.canonical_state()
    assert left.state_hash() == right.state_hash()


# ======================================================================
# D. 복제 독립 (§19 D)
# ======================================================================


def test_d_a_clone_does_not_disturb_the_original(state):
    clone = state.clone()
    before = state.state_hash()
    position = state.randomness.canonical_state()

    result = run(clone, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)))

    assert result.status is ResolutionStatus.RESOLVED
    assert state.state_hash() == before
    assert state.randomness.canonical_state() == position
    assert state.randomness.draws == 0
    assert clone.randomness.draws == 1


def test_d_original_and_clone_pick_the_same_card_from_the_same_position(state):
    clone = state.clone()

    left = run(state, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)))
    right = run(clone, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)))

    assert left.applied[0].instances == right.applied[0].instances

    # 이후 원본을 더 소비해도 사본은 흔들리지 않는다.
    for _ in range(10):
        state.randomness.choose(tuple(c.instance_id for c in state.player(P2).hand))
    assert clone.randomness.draws == 1


# ======================================================================
# E · F. 실패 안전성 (§19 E · F · §12)
# ======================================================================


def test_e_an_empty_candidate_set_changes_nothing(state):
    """§19 E — 후보가 없으면 안전하게 실패한다."""
    while state.player(P2).grave:
        state.move(
            state.player(P2).grave[0].instance_id, Zone.REMOVED, to_player=P2
        )
    before = state.state_hash()
    journal = EventJournal()

    result = run(
        state,
        synthetic(random_spec((Zone.GRAVE,), PlayerRef.OPPONENT)),
        journal,
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    assert result.applied == ()
    assert result.deltas == ()
    assert state.state_hash() == before
    assert len(journal) == 0
    # **난수원도 소비되지 않았다** — 실패가 좌표를 흔들지 않는다.
    assert state.randomness.draws == 0


def test_f_asking_for_more_than_exists_changes_nothing(state):
    """§19 F — 네 장 중 아홉 장을 겹치지 않게 고를 수 없다."""
    before = state.state_hash()

    result = run(
        state, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT, count=99))
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.applied == ()
    assert state.state_hash() == before
    assert state.randomness.draws == 0


def test_f_a_count_below_one_is_refused_at_declaration():
    """0장을 무작위로 고르는 것은 고르지 않는 것이다."""
    with pytest.raises(ValueError, match="1 이상"):
        RandomSelectionSpec(
            source=CandidateSource(zones=frozenset({Zone.HAND})), count=0
        )


def test_e_a_board_without_a_seed_refuses(repository):
    """§12 — 난수원이 없으면 조용히 전역 난수로 넘어가지 않는다."""
    game = new_state(repository, seed=None)
    before = game.state_hash()
    journal = EventJournal()

    result = run(game, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)), journal)

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "seed" in (result.missing or "")
    assert result.applied == ()
    assert game.state_hash() == before
    assert len(journal) == 0


def test_j_a_later_failure_leaves_the_board_alone(state):
    """
    §19 J — 무작위로 고른 **뒤** 다른 일이 막히면 판은 그대로다.

    계획이 전부 끝난 뒤에야 적용이 시작되므로 부분 적용이 없다. 다만
    **난수는 이미 꺼냈다** — 그것이 사실이고, 같은 seed 로 다시 돌리면
    같은 자리에서 같은 답이 나오므로 재현은 깨지지 않는다.
    """
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 3),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.at_random(random_spec((Zone.HAND,), PlayerRef.OPPONENT))
        ),
        operations=(
            CardOperation.send_to_grave(PRIMARY_TARGET),
            # 덱보다 많이 뽑으라고 한다 — 계획 단계에서 막힌다.
            DrawOperation(count=99),
        ),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True, note="Phase 2-AB"),
    )
    before = state.state_hash()
    hand = hand_ids(state, P2)
    journal = EventJournal()

    result = run(state, definition, journal)

    assert result.status is not ResolutionStatus.RESOLVED
    assert result.applied == ()
    assert result.deltas == ()
    assert state.state_hash() == before
    assert hand_ids(state, P2) == hand
    assert len(journal) == 0
    # 난수는 꺼냈다. 감추지 않는다.
    assert state.randomness.draws == 1


# ======================================================================
# G · H. UNKNOWN · FORBIDDEN (§19 G · H · §13)
# ======================================================================


def test_g_an_undecidable_candidate_stops_before_the_draw(state):
    """
    §13 — 후보를 **다 세지 못하면** 무작위를 돌리지 않는다. 몇 개 중에서
    고르는지 모르는 채로 돌리면 확률이 틀린다.
    """
    before = state.state_hash()

    result = run(
        state,
        synthetic(
            random_spec(
                (Zone.HAND,),
                PlayerRef.OPPONENT,
                require=UnimplementedRule("이 엔진이 읽지 못하는 조건"),
            )
        ),
    )

    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert result.applied == ()
    assert state.state_hash() == before
    assert state.randomness.draws == 0


def test_h_a_forbidden_source_never_reaches_the_draw(state):
    """§13 — ``TEXT_DERIVED`` 는 무작위 선택도 하지 않는다 (ADR-004)."""
    before = state.state_hash()

    result = run(
        state,
        synthetic(
            random_spec((Zone.HAND,), PlayerRef.OPPONENT),
            provenance=EffectProvenance.text_derived("텍스트에서 유추"),
        ),
    )

    assert result.status is ResolutionStatus.FORBIDDEN
    assert result.applied == ()
    assert state.state_hash() == before
    assert state.randomness.draws == 0


def test_h_an_unregistered_implementation_never_reaches_the_draw(state):
    before = state.state_hash()

    result = run(
        state,
        synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)),
        registered=False,
    )

    assert result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert state.state_hash() == before
    assert state.randomness.draws == 0


# ======================================================================
# I · N. Operation 연결 · Journal (§19 I · N · §7 · §17)
# ======================================================================


@pytest.mark.parametrize(
    "factory,kind",
    [
        (CardOperation.send_to_grave, OperationKind.SEND_TO_GRAVE),
        (CardOperation.banish, OperationKind.BANISH),
        (CardOperation.return_to_hand, OperationKind.RETURN_TO_HAND),
    ],
)
def test_i_the_selected_card_flows_into_an_existing_operation(state, factory, kind):
    """
    §7 — 무작위 선택은 **고르기만** 한다. 카드를 옮기는 것은 기존
    Operation 이고, 어느 일이든 같은 선택 결과를 받는다.
    """
    journal = EventJournal()

    result = run(
        state,
        synthetic(
            random_spec((Zone.HAND,), PlayerRef.OPPONENT),
            operation=factory(PRIMARY_TARGET),
        ),
        journal,
    )

    assert result.status is ResolutionStatus.RESOLVED
    (applied,) = result.applied
    assert applied.kind is kind
    (delta,) = result.deltas
    assert isinstance(delta, ZoneMoved)
    assert delta.movement is kind
    assert delta.source_zone is Zone.HAND
    assert len(journal) == 1


def test_n_a_random_mutation_uses_the_existing_event_pipeline(state):
    """§17 — 새 EventBus 를 만들지 않았다."""
    journal = EventJournal()

    result = run(
        state, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)), journal
    )
    observed = EventReader(
        GameStateView.from_state(state, viewer=P1)
    ).read(result, actor=P1)

    assert [event.timing.point.name for event in observed] == ["CARD_MOVED"]
    assert all(event.event_id for event in observed)
    assert len(journal) == 1


def test_i_random_selection_itself_moves_nothing():
    """
    §7 — 난수원을 직접 불러도 판이 바뀌지 않는다. 선택과 이동은 다른
    일이다.
    """
    source = RandomSource.seeded(3)
    cards = tuple(InstanceId(i) for i in range(1, 5))

    outcome = source.choose_many(cards, 2, purpose=RandomPurpose.RANDOM_SELECTION)

    assert len(outcome.selected) == 2
    assert set(outcome.selected) <= set(cards)
    # ``RandomOutcome`` 은 값이다. 판을 바꿀 수 있는 것을 들고 있지 않다.
    assert not hasattr(outcome, "apply")
    assert not hasattr(outcome, "move")


# ======================================================================
# K · L · M. 숨은 정보 (§19 K · L · M · §6 · §16)
# ======================================================================


def test_k_choosing_from_a_hidden_hand_reveals_nothing(state):
    """
    §6 — **Random Selection ≠ Information Reveal.**

    엔진은 어느 카드가 골라졌는지 안다. P1 의 관측은 여전히 상대 패를
    보지 못한다.
    """
    result = run(state, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)))
    picked = result.applied[0].instances[0]

    # 엔진은 안다.
    assert state.find_instance(picked) is not None

    # 관측은 모른다 — 남은 패는 여전히 가려져 있다.
    view = GameStateView.from_state(state, viewer=P1)
    assert view.player(P2).zone(Zone.HAND).concealed is True
    assert view.player(P2).zone(Zone.HAND).cards == ()


def test_m_a_refusal_never_names_a_hidden_card(state):
    """§19 M — 실패 결과에 상대 패의 정체가 실리지 않는다."""
    hidden = [card.card_id for card in state.player(P2).hand]

    result = run(
        state,
        synthetic(
            random_spec(
                (Zone.HAND,),
                PlayerRef.OPPONENT,
                require=UnimplementedRule("읽지 못하는 조건"),
            )
        ),
    )

    rendered = repr(result.to_dict()) + (result.reason or "") + (result.missing or "")
    for card_id in hidden:
        assert str(card_id) not in rendered


def test_m_the_outcome_summary_names_nothing():
    """
    §9 — ``public_summary()`` 와 ``to_dict()`` 의 정보량이 다르다.
    """
    source = RandomSource.seeded(1)
    cards = tuple(InstanceId(i) for i in range(10, 14))

    outcome = source.choose_many(cards, 1)

    assert outcome.to_dict()["selected"]
    summary = outcome.public_summary()
    assert set(summary) == {"purpose", "candidate_count", "selected_count"}
    for instance in cards:
        assert str(instance.value) not in repr(summary)


def test_l_a_reveal_permission_changes_what_is_seen_not_what_is_chosen(repository):
    """
    §16 — 권한은 **보이는 것**을 바꾸지, 골라지는 것을 바꾸지 않는다.

    같은 seed 로 두 판을 돌리되 한쪽에만 ``REVEAL_HAND`` 를 준다. 고른
    카드는 같고, 보이는 것만 다르다.
    """
    plain, revealed = new_state(repository, seed=42), new_state(repository, seed=42)

    left = run(plain, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)))
    right = run(revealed, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)))

    assert left.applied[0].instances == right.applied[0].instances

    holder = revealed.player(P1).monster_zone[0].instance_id
    policy = derive_policy(
        revealed,
        [
            ObservationGrant(
                permission=ObservationPermission.REVEAL_HAND,
                source=EffectRef(LAB, 9),
                holder=holder,
                active_zones=frozenset({Zone.MZONE}),
                beneficiary=PlayerRef.CONTROLLER,
                subject=PlayerRef.OPPONENT,
            )
        ],
    )

    without = GameStateView.from_state(plain, viewer=P1)
    with_permission = GameStateView.from_state(revealed, viewer=P1, policy=policy)

    assert without.player(P2).zone(Zone.HAND).concealed is True
    assert with_permission.player(P2).zone(Zone.HAND).concealed is False
    assert len(with_permission.player(P2).zone(Zone.HAND).cards) == 3


# ======================================================================
# O. state_hash 의 뜻은 그대로 (§19 O · §18)
# ======================================================================


def test_o_the_rng_position_is_still_not_in_the_hash(repository):
    """
    §18 — Phase 2-Z 의 결정을 바꾸지 않았다. 난수원의 위치는 판의 모양이
    아니다.
    """
    left, right = new_state(repository, seed=9), new_state(repository, seed=9)
    assert left.state_hash() == right.state_hash()

    for _ in range(5):
        left.randomness.choose(
            tuple(card.instance_id for card in left.player(P2).hand)
        )

    assert left.state_hash() == right.state_hash()
    assert "draw" not in repr(left.canonical_state())


def test_o_a_selection_that_moves_a_card_does_change_the_hash(state):
    """
    반면 **선택의 결과가 판을 바꾸면** 해시는 달라진다. 그것은 카드가
    움직였기 때문이지 난수를 꺼냈기 때문이 아니다.
    """
    before = state.state_hash()

    run(state, synthetic(random_spec((Zone.HAND,), PlayerRef.OPPONENT)))

    assert state.state_hash() != before


# ======================================================================
# P. 플레이어 선택과의 구분 (§14)
# ======================================================================


def test_p_a_random_spec_has_no_chooser():
    """
    §14 — **의미를 합치지 않는다.** 무작위 명세에는 "누가 고르는가" 칸이
    아예 없다.
    """
    spec = random_spec((Zone.HAND,), PlayerRef.OPPONENT)

    assert not hasattr(spec, "chooser")
    assert hasattr(ChoiceSpec(source=spec.source), "chooser")
    assert TargetSpec.at_random(spec).is_random is True
    assert TargetSpec.choosing(ChoiceSpec(source=spec.source)).is_random is False


def test_p_the_two_kinds_of_spec_cannot_be_swapped():
    plain = ChoiceSpec(source=CandidateSource(zones=frozenset({Zone.HAND})))
    rolled = random_spec((Zone.HAND,), PlayerRef.OPPONENT)

    with pytest.raises(ValueError, match="RandomSelectionSpec"):
        TargetSpec.at_random(plain)
    with pytest.raises(ValueError, match="ChoiceSpec"):
        TargetSpec.choosing(rolled)


def test_p_a_random_target_is_never_pending():
    """기다릴 사람이 없다 — "아직 안 골랐다" 라는 상태가 없다."""
    spec = TargetSpec.at_random(random_spec((Zone.HAND,), PlayerRef.OPPONENT))

    assert spec.is_pending(None) is False
    assert spec.requires_selection is True


def test_p_a_random_target_looks_at_nothing():
    """
    §6 — 고르는 사람이 없으므로 아무도 들여다보지 않는다 (Phase 2-Y 의
    ``looked_at`` 은 "고르려면 봐야 한다" 였다).
    """
    spec = TargetSpec.at_random(random_spec((Zone.DECK,), PlayerRef.CONTROLLER))

    assert spec.looked_at_zones() == frozenset()


def test_p_no_new_operation_kind_was_added():
    """
    §8 — 무작위 선택은 **Operation 이 아니다.** 고르는 일이지 판을 바꾸는
    일이 아니므로 ``OperationKind`` 에 들어가지 않는다.
    """
    assert not any("random" in kind.value for kind in OperationKind)
    assert TargetRequirement.RANDOM.value == "random"


# ======================================================================
# Q. 실제 카드 (§15 · §19)
# ======================================================================


def test_q_the_corpus_was_surveyed_for_random_primitives():
    """
    §15 — 실제 Lua 를 authoritative source 로 쓴다. 142장이
    ``RandomSelect`` 를 부르고, 이 엔진이 닿는 것은 네 장뿐이다.
    """
    scripts = sorted(ROOT.glob("c*.lua"))
    users = [
        path
        for path in scripts
        if re.search(r"\bRandomSelect\b", path.read_text("utf-8", errors="replace"))
    ]

    assert len(users) > 100
    assert (ROOT / "c73148972.lua").is_file()
    script = (ROOT / "c73148972.lua").read_text("utf-8")
    assert "RandomSelect(tp,1)" in script
    assert "Duel.SelectTarget(tp,nil,tp,LOCATION_MZONE,0,1,1,nil)" in script
    assert "Duel.GetFieldGroup(tp,0,LOCATION_HAND)" in script


@pytest.mark.real_card
def test_q_ruthless_denial_uses_both_kinds_of_selection():
    """
    **무정의 말살 (73148972)** — 한 카드 안에 플레이어 선택과 무작위
    선택이 나란히 있다.
    """
    entry = entry_for(EffectRef(RUTHLESS_DENIAL, 0))
    assert entry is not None and entry.executable is True

    kinds = [binding.spec.requirement for binding in entry.definition.targets]
    assert kinds == [TargetRequirement.TARGETING, TargetRequirement.RANDOM]

    (player_choice, rolled) = entry.definition.targets
    assert player_choice.spec.choice.source.owner is PlayerRef.CONTROLLER
    assert rolled.spec.choice.source.owner is PlayerRef.OPPONENT
    assert rolled.spec.choice.count == 1
    assert not hasattr(rolled.spec.choice, "chooser")


def _denial_board(repository, seed=7) -> GameState:
    game = GameState.create(
        repository,
        decks=(
            [RUTHLESS_DENIAL, FILLER] + [FILLER] * 10,
            [A, B, C, D] + [FILLER] * 8,
        ),
        seed=seed,
    )
    game.draw(P1, 2)
    game.draw(P2, 4)
    game.move(
        game.player(P1).hand[0].instance_id, Zone.SZONE, to_player=P1,
        position=Position.FACEUP,
    )
    game.move(
        game.player(P1).hand[0].instance_id, Zone.MZONE, to_player=P1,
        position=Position.FACEUP_ATTACK,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


def _activate_denial(game: GameState):
    registry = definition_registry()
    source = game.player(P1).spell_zone[0].instance_id
    mine = game.player(P1).monster_zone[0].instance_id
    return registry, EffectActivator(registry, implementation_registry()).activate(
        game,
        Chain(),
        PlayerAction.activate_effect(
            actor=P1, source=source, effect_ref=EffectRef(RUTHLESS_DENIAL, 0)
        ),
        (TargetSelection(PRIMARY_TARGET, Selection.of(mine)),),
        authorization=GRANTED,
    )


@pytest.mark.real_card
def test_q_ruthless_denial_runs_end_to_end(repository):
    """
    §19 I · N — 실제 카드가 발동 → 체인 → 해결을 지나며 **두 장**을
    묘지로 보낸다. 한 장은 플레이어가 고르고 한 장은 무작위다.
    """
    game = _denial_board(repository)
    mine = game.player(P1).monster_zone[0].instance_id
    opponent_hand = hand_ids(game, P2)
    journal = EventJournal()

    registry, activated = _activate_denial(game)
    assert activated.status is ActivationStatus.ACTIVATED

    resolved = ChainResolver(build_executor(journal), registry).resolve_top(
        game, activated.chain
    )
    result = resolved.result

    assert result.status is ResolutionStatus.RESOLVED
    assert [applied.kind for applied in result.applied] == [
        OperationKind.SEND_TO_GRAVE,
        OperationKind.SEND_TO_GRAVE,
    ]
    assert game.locate(mine).zone is Zone.GRAVE
    assert len(hand_ids(game, P2)) == len(opponent_hand) - 1
    assert len(grave_ids(game, P2)) == 1
    assert grave_ids(game, P2)[0] in opponent_hand
    assert len(journal) == 1
    assert game.randomness.draws == 1

    observed = EventReader(
        GameStateView.from_state(game, viewer=P1)
    ).read(result, actor=P1)
    assert [event.timing.point.name for event in observed] == [
        "CARD_MOVED",
        "CARD_MOVED",
    ]


@pytest.mark.real_card
def test_q_ruthless_denial_is_reproducible(repository):
    """같은 seed 면 같은 카드가 묘지로 간다."""
    picked = []
    for _ in range(3):
        game = _denial_board(repository, seed=2024)
        registry, activated = _activate_denial(game)
        ChainResolver(build_executor(), registry).resolve_top(game, activated.chain)
        picked.append(grave_ids(game, P2))

    assert len({tuple(p) for p in picked}) == 1


@pytest.mark.real_card
def test_q_ruthless_denial_refuses_a_supplied_random_choice(repository):
    """
    §14 — 무작위 자리에 **고른 결과를 밖에서 넣을 수 없다.** 넣을 수
    있으면 그것은 무작위가 아니다.
    """
    game = _denial_board(repository)
    registry = definition_registry()
    source = game.player(P1).spell_zone[0].instance_id
    mine = game.player(P1).monster_zone[0].instance_id
    victim = game.player(P2).hand[0].instance_id
    before = game.state_hash()

    activated = EffectActivator(registry, implementation_registry()).activate(
        game,
        Chain(),
        PlayerAction.activate_effect(
            actor=P1, source=source, effect_ref=EffectRef(RUTHLESS_DENIAL, 0)
        ),
        (
            TargetSelection(PRIMARY_TARGET, Selection.of(mine)),
            TargetSelection(TargetRef("random"), Selection.of(victim)),
        ),
        authorization=GRANTED,
    )

    assert activated.status is ActivationStatus.INVALID_TARGET
    assert len(activated.chain) == 0
    assert game.state_hash() == before
    assert game.randomness.draws == 0


@pytest.mark.real_card
def test_q_ruthless_denial_never_reveals_the_opponents_hand(repository):
    """
    §6 — 무작위로 한 장이 묘지로 갔다고 **남은 패**가 보이지는 않는다.
    """
    game = _denial_board(repository)
    registry, activated = _activate_denial(game)
    ChainResolver(build_executor(), registry).resolve_top(game, activated.chain)

    view = GameStateView.from_state(game, viewer=P1)

    assert view.player(P2).zone(Zone.HAND).concealed is True
    assert view.player(P2).zone(Zone.HAND).cards == ()
    # 묘지로 간 카드는 공개다 — 그것은 묘지가 공개 자리이기 때문이지
    # 무작위로 골라졌기 때문이 아니다.
    assert view.player(P2).zone(Zone.GRAVE).concealed is False
