"""
Phase 2-AC — 몇 장을 고르는가.

    Effect
      → SelectionCount        **몇 개**를 고르는가   (판을 읽는다)
      → CandidateResolver     **무엇**을 고를 수 있는가 (판을 읽는다)
      → RandomSource          자리 번호를 고른다      (둘 다 모른다)
      → 기존 Operation        상태 변경

Phase 2-AB 는 "아무도 고르지 않는다" 를 세웠고, 이번 단계는 그 위에서
**수와 후보를 가른다.**

두 질문은 서로를 읽지 않는다
----------------------------
========================  ==========================================
무엇을 고를 수 있는가        ``CandidateSource`` · ``CandidateResolver``
몇 개를 고르는가            ``SelectionCount``
========================  ==========================================

한쪽이 다른 쪽을 읽기 시작하면 "후보를 세다가 수가 정해지는" 코드가 생기고,
그러면 확률이 어디서 정해졌는지 추적할 수 없다.

실제 카드가 요구한 것
---------------------
``RandomSelect`` 호출 142건 중 **12건이 고정 수가 아니다.** 그 12건의
수가 오는 곳은 넷이고, 이 엔진이 판에서 계산할 수 있는 것은 그중
**자리 장수 산술** 하나뿐이다. 나머지 셋은 ``UNKNOWN`` 으로 남는다 —
숫자로 바꾸지 않는다.
"""

import ast
import pathlib

import pytest

from engine.condition import PlayerRef, UnimplementedRule
from engine.cost import CandidateSource, ChoiceSpec, CostGroup
from engine.cost.resolver import CandidateResolver
from engine.condition import ConditionContext
from engine.effect.definition import EffectDefinition, EffectProvenance
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.operation import CardOperation, DrawOperation
from engine.effect.resolution import ResolutionContext, ResolutionStatus
from engine.effect.target import (
    PRIMARY_TARGET,
    CountKind,
    CountOutcome,
    RandomSelectionSpec,
    ResolvedCount,
    SelectionCount,
    Shortfall,
    TargetBinding,
    TargetSpec,
    ZoneCountTerm,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.observation import ObservationPermission
from engine.observation_grant import ObservationGrant, derive_policy
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
P1, P2 = 0, 1
LAB = 999_005  # synthetic 정의의 자리. 실제 카드 번호가 아니다.

A, B, C, D = 55144522, 66719324, 5318639, 83764718
MINE_1, MINE_2 = 70368879, 15103313
FILLER = 21844576


def new_state(repository, seed: int | None = 7, opponent_hand: int = 4) -> GameState:
    """P1 패 2장 · MZONE 1장 / P2 패 ``opponent_hand`` 장."""
    game = GameState.create(
        repository,
        decks=(
            [FILLER] * 3 + [MINE_1, MINE_2] + [FILLER] * 12,
            [A, B, C, D] + [FILLER] * 12,
        ),
        seed=seed,
    )
    game.draw(P1, 4)
    game.draw(P2, opponent_hand)
    game.move(
        game.player(P1).hand[0].instance_id, Zone.MZONE, to_player=P1,
        position=Position.FACEUP_ATTACK,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def spec_of(count, owner=PlayerRef.OPPONENT, zones=(Zone.HAND,), **kwargs):
    return RandomSelectionSpec(
        source=CandidateSource(zones=frozenset(zones), owner=owner),
        count=count,
        **kwargs,
    )


def synthetic(spec, operations=None, ordinal=0):
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        targets=TargetBinding.single(TargetSpec.at_random(spec)),
        operations=operations or (CardOperation.send_to_grave(PRIMARY_TARGET),),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(verified=True, note="Phase 2-AC 시험"),
    )


def run(state, definition, journal=None):
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        journal=journal,
    )
    return executor.execute(
        state,
        definition,
        ResolutionContext(effect_ref=definition.effect_ref, controller=P1),
    )


def hand_ids(game, owner):
    return [card.card_id for card in game.player(owner).hand]


def unchanged(game, before_hash, before_hand, result, journal=None):
    """판이 그대로이고 난수도 꺼내지 않았다."""
    assert result.status is not ResolutionStatus.RESOLVED
    assert result.applied == ()
    assert result.deltas == ()
    assert game.state_hash() == before_hash
    assert hand_ids(game, P2) == before_hand
    assert game.randomness.draws == 0
    if journal is not None:
        assert len(journal) == 0


# ======================================================================
# A. 고정 수 (§21 A)
# ======================================================================


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_a_a_fixed_count_chooses_that_many(state, count):
    result = run(state, synthetic(spec_of(count)))

    assert result.status is ResolutionStatus.RESOLVED, count
    (applied,) = result.applied
    assert len(applied.instances) == count
    assert len(set(applied.instances)) == count  # 같은 카드를 두 번 고르지 않는다
    # **꺼낸 횟수는 고른 장수만큼**이다 (Phase 2-Z 의 ``draws`` 는 호출 수가
    # 아니라 재현 좌표다). N 장을 고르려면 번호를 N 번 뽑는다.
    assert state.randomness.draws == count


def test_a_a_bare_number_is_read_as_a_fixed_count():
    """
    숫자 하나를 적는 길을 막지 않았다. **뜻이 같기 때문**이다 — 값을
    바꾸는 것이 아니라 같은 뜻을 제 타입으로 적는다.
    """
    assert spec_of(2).count == SelectionCount.fixed(2)
    assert spec_of(SelectionCount.fixed(2)).count.kind is CountKind.FIXED


# ======================================================================
# B. 계산되는 수 (§21 B · §3)
# ======================================================================


def half_of_opponent_hand() -> SelectionCount:
    """
    "상대 패 장수 - 2". 멀차미 세 장의 ``패 - (상대 필드 + 6)`` 과
    **같은 모양**이고, 실제 카드를 등재한 것은 아니다.
    """
    return SelectionCount.derived(
        (ZoneCountTerm(PlayerRef.OPPONENT, Zone.HAND, 1),), constant=-2
    )


def test_b_a_derived_count_is_computed_from_the_board(state):
    assert len(state.player(P2).hand) == 4

    result = run(state, synthetic(spec_of(half_of_opponent_hand())))

    assert result.status is ResolutionStatus.RESOLVED
    assert len(result.applied[0].instances) == 2


def test_b_the_same_board_gives_the_same_count(repository):
    """§21 B — state → count 가 **함수**다."""
    counts = []
    for _ in range(3):
        game = new_state(repository, seed=5)
        counts.append(
            half_of_opponent_hand().resolve(
                lambda ref, zone: len(game.player(ref.resolve(
                    ConditionContext(player=P1))).zone(zone))
            ).value
        )
    assert counts == [2, 2, 2]


def test_b_a_different_board_gives_a_different_count(repository):
    small = new_state(repository, opponent_hand=3)
    large = new_state(repository, opponent_hand=5)

    left = run(small, synthetic(spec_of(half_of_opponent_hand())))
    right = run(large, synthetic(spec_of(half_of_opponent_hand())))

    assert len(left.applied[0].instances) == 1
    assert len(right.applied[0].instances) == 3


def test_b_the_count_reads_the_board_not_an_observation(state):
    """
    §9 — **engine authority ≠ viewer visibility.**

    수는 상대 패의 장수에서 나온다. 컨트롤러는 그 패를 볼 수 없지만
    규칙은 장수를 안다 — 그래서 계산이 된다.
    """
    view = GameStateView.from_state(state, viewer=P1)
    assert view.player(P2).zone(Zone.HAND).concealed is True

    result = run(state, synthetic(spec_of(half_of_opponent_hand())))

    assert result.status is ResolutionStatus.RESOLVED
    assert len(result.applied[0].instances) == 2


# ======================================================================
# C. 모르는 수 (§21 C · §10)
# ======================================================================


def test_c_an_unknown_count_stops_before_anything_happens(state):
    """
    §3 — 수를 모르면 **숫자로 바꾸지 않는다.** 1 로 접으면 "1장 고른다"
    는 틀린 규칙이 되고, 0 으로 접으면 효과가 조용히 사라진다.
    """
    before, hand = state.state_hash(), hand_ids(state, P2)
    journal = EventJournal()

    result = run(
        state,
        synthetic(spec_of(SelectionCount.unknown("player-declared number"))),
        journal,
    )

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert result.missing == "player-declared number"
    unchanged(state, before, hand, result, journal)


def test_c_an_unknown_count_must_say_what_is_missing():
    with pytest.raises(ValueError, match="무엇이 없어서"):
        SelectionCount(kind=CountKind.UNKNOWN)


def test_c_an_unknown_result_carries_no_number():
    answer = SelectionCount.unknown("chain parameter").resolve(lambda ref, zone: 3)

    assert answer.outcome is CountOutcome.UNKNOWN
    assert answer.value is None
    with pytest.raises(TypeError):
        bool(answer)


# ======================================================================
# D. 잘못된 수 (§21 D · §11)
# ======================================================================


@pytest.mark.parametrize("bad", [0, -1, -5])
def test_d_a_fixed_count_below_one_is_refused_at_birth(bad):
    """§11 — 0장을 무작위로 고르는 것은 고르지 않는 것이다."""
    with pytest.raises(ValueError, match="1 이상"):
        SelectionCount.fixed(bad)


def test_d_a_derived_count_that_comes_out_zero_is_invalid(state):
    """
    계산해 보니 0 이하였다. **조용히 넘기지 않는다** — 실제 카드는 이
    경우를 발동 조건으로 막는다 (``if dif>0``).
    """
    before, hand = state.state_hash(), hand_ids(state, P2)
    zero = SelectionCount.derived(
        (ZoneCountTerm(PlayerRef.OPPONENT, Zone.HAND, 1),), constant=-4
    )

    result = run(state, synthetic(spec_of(zero)))

    assert result.status is ResolutionStatus.INVALID_OPERATION
    assert result.code is ValidationCode.INVALID_AMOUNT
    unchanged(state, before, hand, result)


def test_d_a_count_cannot_be_two_things_at_once():
    with pytest.raises(ValueError):
        SelectionCount(kind=CountKind.DERIVED, value=2)
    with pytest.raises(ValueError):
        SelectionCount(
            kind=CountKind.FIXED,
            value=1,
            terms=(ZoneCountTerm(PlayerRef.CONTROLLER, Zone.HAND),),
        )
    with pytest.raises(ValueError):
        ResolvedCount(CountOutcome.UNKNOWN, value=1)


# ======================================================================
# E · F. 정확히 N (§21 E · F)
# ======================================================================


def test_e_exactly_n_takes_exactly_n(state):
    result = run(state, synthetic(spec_of(3)))

    assert len(result.applied[0].instances) == 3
    assert len(state.player(P2).hand) == 1


def test_f_exactly_n_refuses_when_there_are_fewer(repository):
    """
    §11 · §12 — 모자라면 **하지 않는다.** 있는 대로 고르는 것은 다른
    규칙이고, 그 규칙은 카드가 적어 둔 경우에만 쓴다.
    """
    state = new_state(repository, opponent_hand=2)
    before, hand = state.state_hash(), hand_ids(state, P2)
    journal = EventJournal()

    result = run(state, synthetic(spec_of(3)), journal)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    unchanged(state, before, hand, result, journal)


# ======================================================================
# G. 모자랄 때 (§21 G · §12)
# ======================================================================


def test_g_a_card_may_declare_that_it_takes_what_is_there(repository):
    """
    §12 — 공식 카드 텍스트 두 장이 부족할 때의 처리를 **자기 텍스트에**
    적어 두었다 ("or their entire hand, if less than 2").

    그래서 규칙이 아니라 **선언**이다. 선언한 정의만 이 길을 탄다.
    """
    state = new_state(repository, opponent_hand=2)

    result = run(
        state, synthetic(spec_of(3, on_shortfall=Shortfall.TAKE_ALL))
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert len(result.applied[0].instances) == 2
    assert len(state.player(P2).hand) == 0


def test_g_taking_what_is_there_still_needs_something_there(repository):
    state = new_state(repository, opponent_hand=0)
    before, hand = state.state_hash(), hand_ids(state, P2)

    result = run(state, synthetic(spec_of(2, on_shortfall=Shortfall.TAKE_ALL)))

    assert result.code is ValidationCode.NO_CANDIDATES
    unchanged(state, before, hand, result)


def test_g_up_to_n_is_not_a_shortfall_rule():
    """
    **"최대 2장" 과 "모자라면 전부" 를 섞지 않는다.**

    실제 카드의 "up to 2 random cards" (10691144 · 45222299)는 플레이어가
    1 이나 2 를 **선언한 뒤** 그 수만큼 무작위로 고르는 것이다
    (``Duel.SelectOption`` · ``Duel.AnnounceNumber``). 수를 정하는 방법의
    문제이지 부족할 때의 처리가 아니다.

    그 선언 계층이 없으므로 이런 카드의 수는 ``UNKNOWN`` 이다.
    """
    declared = SelectionCount.unknown("player-declared number (SelectOption/AnnounceNumber)")

    assert declared.kind is CountKind.UNKNOWN
    assert declared.resolve(lambda ref, zone: 2).outcome is CountOutcome.UNKNOWN
    # 기본값은 여전히 "하지 않는다" 다.
    assert spec_of(1).on_shortfall is Shortfall.REFUSE


# ======================================================================
# H. 모르는 후보 (§21 H · §5 · §7)
# ======================================================================


def test_h_an_undecidable_candidate_is_never_quietly_dropped(state):
    """
    §7 — 넷 중 하나가 후보인지 모르는 채로 셋에서 고르면 확률이 1/4 이
    아니라 1/3 이 된다. **다른 규칙이다.**
    """
    before, hand = state.state_hash(), hand_ids(state, P2)

    result = run(
        state,
        synthetic(
            RandomSelectionSpec(
                source=CandidateSource(
                    zones=frozenset({Zone.HAND}),
                    owner=PlayerRef.OPPONENT,
                    require=UnimplementedRule("아직 옮기지 않은 조건"),
                ),
                count=1,
            )
        ),
    )

    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.INFORMATION_UNAVAILABLE
    unchanged(state, before, hand, result)


def test_h_all_unknown_and_some_unknown_are_different_sentences(state):
    """
    §5 — 어느 쪽이든 고르지 않는다. 그러나 **무엇을 고쳐야 하는지**가
    다르므로 한 문장으로 뭉치지 않는다.
    """
    everything = run(
        state,
        synthetic(
            RandomSelectionSpec(
                source=CandidateSource(
                    zones=frozenset({Zone.HAND}),
                    owner=PlayerRef.OPPONENT,
                    require=UnimplementedRule("전부 모른다"),
                ),
                count=1,
            )
        ),
    )

    assert "전부" in everything.reason
    assert everything.status is ResolutionStatus.UNCHECKED_TARGET


def test_h_a_hidden_zone_is_a_different_failure_from_an_unknown_rule():
    """
    **UNKNOWN ≠ HIDDEN.** 둘은 다른 사실이고 다른 코드로 답한다.

    무작위 선택은 자리마다 그 주인의 눈으로 세므로 가려진 자리가 생기지
    않는다. 그래도 그 길을 지우지 않은 이유는, 닿는다면 그것은 "모른다"
    가 아니라 "못 봤다" 이기 때문이다.
    """
    source = (ROOT / "engine" / "effect" / "executor.py").read_text("utf-8")
    tree = ast.parse(source)
    (function,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_authoritative_candidates"
    ]
    body = ast.unparse(function)

    # 두 길이 **따로** 있다.
    assert "if unchecked:" in body
    assert "if undecided:" in body
    # 그리고 어느 쪽도 후보를 빼지 않는다.
    assert "remove" not in body and "discard" not in body


# ======================================================================
# §4. 수와 후보는 서로를 읽지 않는다
# ======================================================================


def test_counting_candidates_does_not_look_at_how_many_are_wanted(state):
    """
    §4 — 같은 후보 규칙이면 장수가 무엇이든 **같은 후보**가 나온다.
    """
    view = GameStateView.from_state(state, viewer=P2, looked_at=frozenset({Zone.HAND}))
    source = CandidateSource(zones=frozenset({Zone.HAND}), owner=PlayerRef.CONTROLLER)
    context = ConditionContext(player=P2)

    one = CandidateResolver(view).resolve(
        ChoiceSpec(source=source, minimum=1, maximum=1), context
    )
    many = CandidateResolver(view).resolve(
        ChoiceSpec(source=source, minimum=0, maximum=99), context
    )

    assert one.eligible == many.eligible
    assert one.canonical_state() == many.canonical_state()


def test_the_candidate_counter_never_reads_the_count():
    """§4 — 코드에서도 그렇다."""
    tree = ast.parse((ROOT / "engine" / "effect" / "executor.py").read_text("utf-8"))
    (counting,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_authoritative_candidates"
    ]
    attributes = {
        node.attr for node in ast.walk(counting) if isinstance(node, ast.Attribute)
    }
    assert "count" not in attributes
    assert "minimum" not in attributes and "maximum" not in attributes


def test_the_count_resolver_never_counts_candidates():
    """
    §4 — 반대 방향도 막는다.

    Phase 2-AD 에서 이름이 ``_resolve_count`` → ``_resolve_number`` 로
    바뀌었다. 답하는 것이 "고를 장수" 만이 아니게 됐기 때문이다 — 드로우
    매수도 같은 자리에서 답한다. **하는 일이 넓어졌지, 후보를 보게 된
    것은 아니다.**
    """
    tree = ast.parse((ROOT / "engine" / "effect" / "executor.py").read_text("utf-8"))
    (counting,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_number"
    ]
    names = {node.id for node in ast.walk(counting) if isinstance(node, ast.Name)}
    assert "CandidateResolver" not in names
    assert "GameStateView" not in names


def test_a_random_spec_has_no_minimum_or_maximum():
    """
    **장수를 두 이름으로 부르지 않는다.** ``minimum``/``maximum`` 을
    남겨 두면 후보를 세는 쪽이 그것을 읽을 수 있게 된다.
    """
    spec = spec_of(2)
    assert not hasattr(spec, "minimum")
    assert not hasattr(spec, "maximum")


def test_the_random_source_still_knows_nothing_about_counts():
    """§6 — 난수원은 몇 개인지 **받을** 뿐 계산하지 않는다."""
    tree = ast.parse((ROOT / "engine" / "randomness.py").read_text("utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "SelectionCount" not in names
    assert "ZoneCountTerm" not in names
    assert not names & {"locate", "player", "zone", "hand", "deck", "grave"}


# ======================================================================
# I · J. 숨은 정보 (§21 I · J · §8 · §9)
# ======================================================================


def test_i_a_derived_count_does_not_open_the_opponent_hand(state):
    """
    §8 — 수가 상대 패의 **장수**에서 나와도, 그 패의 **정체**는 열리지
    않는다. 장수와 정체는 다른 정보다.
    """
    result = run(state, synthetic(spec_of(half_of_opponent_hand())))
    assert result.status is ResolutionStatus.RESOLVED

    view = GameStateView.from_state(state, viewer=P1)
    assert view.player(P2).zone(Zone.HAND).concealed is True
    assert view.player(P2).zone(Zone.HAND).cards == ()
    # 남은 패의 정체가 결과에도 실리지 않는다.
    remaining = [card.card_id for card in state.player(P2).hand]
    rendered = repr(result.to_dict())
    for card_id in remaining:
        assert str(card_id) not in rendered


def test_j_a_reveal_permission_changes_visibility_not_the_count(repository):
    """
    §21 J — 권한이 있어도 **고른 것도 수도 그대로**다. 권한은 보이는
    것만 바꾼다.
    """
    plain, revealed = new_state(repository, seed=11), new_state(repository, seed=11)

    left = run(plain, synthetic(spec_of(half_of_opponent_hand())))
    right = run(revealed, synthetic(spec_of(half_of_opponent_hand())))

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
    granted = GameStateView.from_state(revealed, viewer=P1, policy=policy)

    assert without.player(P2).zone(Zone.HAND).concealed is True
    assert granted.player(P2).zone(Zone.HAND).concealed is False


# ======================================================================
# K · L. 결정론 · 복제 (§21 K · L · §17 · §18)
# ======================================================================


def test_k_the_same_seed_gives_the_same_answer(repository):
    picks = []
    for _ in range(2):
        game = new_state(repository, seed=31)
        picks.append(
            run(game, synthetic(spec_of(half_of_opponent_hand()))).applied[0].instances
        )
    assert picks[0] == picks[1]


def test_k_a_different_seed_gives_a_different_answer(repository):
    seen = set()
    for seed in (1, 2, 3, 4, 5, 6):
        game = new_state(repository, seed=seed)
        result = run(game, synthetic(spec_of(half_of_opponent_hand())))
        seen.add(tuple(result.applied[0].instances))
    assert len(seen) > 1


def test_k_the_candidate_order_is_not_left_to_a_set(state):
    """§17 — 후보 순서가 흔들리면 같은 seed 라도 답이 달라진다."""
    source = (ROOT / "engine" / "cost" / "resolver.py").read_text("utf-8")
    assert "visible.sort(key=_sort_key)" in source


def test_l_a_clone_rolls_its_own_dice(repository):
    original = new_state(repository, seed=77)
    copy = original.clone()

    left = run(copy, synthetic(spec_of(half_of_opponent_hand())))

    assert original.randomness.draws == 0
    assert copy.randomness.draws == 2
    assert original.state_hash() != copy.state_hash()

    # 같은 자리에서 시작한 또 하나의 복제는 같은 답을 낸다.
    twin = original.clone()
    right = run(twin, synthetic(spec_of(half_of_opponent_hand())))
    assert left.applied[0].instances == right.applied[0].instances


# ======================================================================
# M · N · O · P. 실패 안전성 · 조작 · 저널 · 해시 (§21 M ~ P)
# ======================================================================


def test_m_a_failure_after_the_count_leaves_the_board_alone(state):
    """
    수를 정하고 후보를 세고 난수까지 꺼낸 **뒤** 다른 일이 막힌다.
    계획이 전부 끝난 뒤에야 적용이 시작되므로 부분 적용이 없다.
    """
    before, hand = state.state_hash(), hand_ids(state, P2)
    journal = EventJournal()

    result = run(
        state,
        synthetic(
            spec_of(half_of_opponent_hand()),
            operations=(
                CardOperation.send_to_grave(PRIMARY_TARGET),
                DrawOperation(count=99),
            ),
        ),
        journal,
    )

    assert result.status is ResolutionStatus.INSUFFICIENT_CARDS
    assert result.applied == ()
    assert result.deltas == ()
    assert state.state_hash() == before
    assert hand_ids(state, P2) == hand
    assert len(journal) == 0
    # 난수는 이미 꺼냈다. 감추지 않는다.
    assert state.randomness.draws == 2


def test_n_the_chosen_cards_go_through_the_existing_operation(state):
    result = run(state, synthetic(spec_of(2)))

    (applied,) = result.applied
    assert applied.kind.value == "send_to_grave"
    assert len(result.deltas) == 2
    for instance in applied.instances:
        assert state.locate(instance).zone is Zone.GRAVE


def test_o_the_journal_records_the_move_not_the_dice(state):
    journal = EventJournal()

    run(state, synthetic(spec_of(2)), journal)

    assert len(journal) == 1
    rendered = repr(journal.to_dict() if hasattr(journal, "to_dict") else list(journal))
    assert "random" not in rendered.lower()
    assert "draw" not in rendered.lower()


def test_p_only_a_real_change_moves_the_hash(repository):
    """§19 — 이번 단계 때문에 해시의 뜻을 바꾸지 않았다."""
    left, right = new_state(repository, seed=8), new_state(repository, seed=8)
    assert left.state_hash() == right.state_hash()

    # 수만 계산해 본다 — 판을 읽기만 하므로 아무것도 바뀌지 않는다.
    half_of_opponent_hand().resolve(
        lambda ref, zone: len(left.player(P2).zone(zone))
    )
    assert left.state_hash() == right.state_hash()

    run(left, synthetic(spec_of(1)))
    assert left.state_hash() != right.state_hash()


def test_p_the_count_declaration_is_part_of_the_definition_not_the_state(state):
    """
    수는 정의에 적힌 것이고 판의 모양이 아니다 — ``canonical_state`` 에
    정의가 섞이지 않는다.
    """
    rendered = repr(state.canonical_state())
    assert "derived" not in rendered and "selection_count" not in rendered


# ======================================================================
# Q. 실제 카드의 수식 (§21 Q · §13)
# ======================================================================


def test_q_the_four_shapes_of_a_dynamic_count_are_recorded():
    """
    §13 — 실제 ``RandomSelect`` 142건 중 12건이 고정 수가 아니다. 그 수가
    오는 곳은 넷이고, 이 엔진이 판에서 계산할 수 있는 것은 하나뿐이다.

    ========================================  ====  ==========
    수가 오는 곳                                건수  지금
    ========================================  ====  ==========
    자리 장수 산술                               4    DERIVED
    플레이어가 선언한 수                          4    UNKNOWN
    앞선 조작의 결과 수                           3    UNKNOWN
    체인 파라미터                                1    UNKNOWN
    ========================================  ====  ==========

    이 시험은 **모르는 것을 모른다고 적을 수 있는가**를 본다.
    """
    board = SelectionCount.derived(
        (ZoneCountTerm(PlayerRef.CONTROLLER, Zone.HAND, 1),), constant=-6
    )
    declared = SelectionCount.unknown("player-declared number")
    carried = SelectionCount.unknown("count of a previous operation's result")
    chained = SelectionCount.unknown("chain parameter")

    assert board.resolve(lambda ref, zone: 9).value == 3
    for unknown in (declared, carried, chained):
        answer = unknown.resolve(lambda ref, zone: 9)
        assert answer.outcome is CountOutcome.UNKNOWN
        assert answer.value is None
        assert answer.missing


def test_q_mirage_of_nightmare_has_a_shape_we_can_write_but_not_a_card_we_run():
    """
    악몽의 신기루(41482598)의 수는 ``4 - 패 장수`` 다 (``SetLabel(4-ht)``).
    **모양은 적을 수 있지만 카드는 등재하지 않았다** — 스탠바이 페이즈
    유발과 효과 간 라벨 전달 계층이 없다.

    모양을 적을 수 있다는 것과 카드를 실행할 수 있다는 것은 다른 말이고,
    그 둘을 섞지 않는 것이 이 시험의 일이다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    shape = SelectionCount.derived(
        (ZoneCountTerm(PlayerRef.CONTROLLER, Zone.HAND, -1),), constant=4
    )
    assert shape.resolve(lambda ref, zone: 1).value == 3

    assert 41482598 not in {entry.card_id for entry in EFFECT_LIBRARY}


# ======================================================================
# Q. 실제 카드 — 의적의 입문서 (69091732) (§21 Q · §14 · §18)
# ======================================================================
#
# 무정한 말살에 이은 **두 번째** 실제 무작위 카드다. 새로 보여 주는 것은
# 하나다 — **발동 조건이 상대 패의 장수**다. 장수는 규칙이 아는 사실이고,
# 정체는 아니다.


GALLANTRY_HAND = [A, B, C, D, MINE_1]


def gallantry_board(repository, seed=3, opponent_hand=5) -> GameState:
    from engine.effect.library import INTRODUCTION_TO_GALLANTRY

    game = GameState.create(
        repository,
        decks=(
            [INTRODUCTION_TO_GALLANTRY] + [FILLER] * 15,
            GALLANTRY_HAND + [FILLER] * 11,
        ),
        seed=seed,
    )
    game.draw(P1, 1)
    game.draw(P2, opponent_hand)
    game.move(
        game.player(P1).hand[0].instance_id, Zone.SZONE, to_player=P1,
        position=Position.FACEUP_ATTACK,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


def resolve_gallantry(game, journal=None):
    from engine.effect.library import (
        INTRODUCTION_TO_GALLANTRY,
        build_executor,
        entry_for,
    )

    entry = entry_for(EffectRef(INTRODUCTION_TO_GALLANTRY, 0))
    assert entry is not None and entry.executable is True
    return build_executor(journal=journal).execute(
        game,
        entry.definition,
        ResolutionContext(
            effect_ref=entry.definition.effect_ref, controller=P1
        ),
    )


@pytest.mark.real_card
def test_q_gallantry_discards_one_random_card(repository):
    game = gallantry_board(repository)
    journal = EventJournal()
    before = [card.card_id for card in game.player(P2).hand]

    result = resolve_gallantry(game, journal)

    assert result.status is ResolutionStatus.RESOLVED
    (applied,) = result.applied
    assert applied.kind.value == "discard"
    assert len(applied.instances) == 1
    assert len(game.player(P2).hand) == 4
    assert len(game.player(P2).grave) == 1
    assert game.player(P2).grave[0].card_id in before
    assert game.randomness.draws == 1
    assert len(journal) == 1


@pytest.mark.real_card
def test_q_gallantry_is_reproducible(repository):
    same = [
        resolve_gallantry(gallantry_board(repository, seed=3)).applied[0].instances
        for _ in range(2)
    ]
    assert same[0] == same[1]

    seen = {
        tuple(resolve_gallantry(gallantry_board(repository, seed=s)).applied[0].instances)
        for s in range(1, 8)
    }
    assert len(seen) > 1


@pytest.mark.real_card
def test_q_gallantry_needs_five_cards_in_the_opponent_hand(repository):
    """
    ``Duel.GetFieldGroupCount(tp,0,LOCATION_HAND)>4`` — 공식 한국어 텍스트도
    "상대의 패가 5장 이상일 경우에 발동할 수 있다" 다.
    """
    game = gallantry_board(repository, opponent_hand=4)
    before, hand = game.state_hash(), hand_ids(game, P2)
    journal = EventJournal()

    result = resolve_gallantry(game, journal)

    assert result.status is not ResolutionStatus.RESOLVED
    unchanged(game, before, hand, result, journal)


@pytest.mark.real_card
def test_q_gallantry_counts_a_hand_it_cannot_see(repository):
    """
    §8 · §9 — 컨트롤러는 상대의 패를 **볼 수 없는데** 발동 조건은
    그 패의 장수를 읽는다. 둘이 모순이 아니라는 것이 이 카드로 확인된다.
    """
    game = gallantry_board(repository)

    view = GameStateView.from_state(game, viewer=P1)
    assert view.player(P2).zone(Zone.HAND).concealed is True
    assert view.player(P2).zone(Zone.HAND).size == 5  # 장수는 보인다

    result = resolve_gallantry(game)
    assert result.status is ResolutionStatus.RESOLVED

    # 버려진 카드만 공개되고, 남은 패는 그대로 가려져 있다.
    after = GameStateView.from_state(game, viewer=P1)
    assert after.player(P2).zone(Zone.HAND).concealed is True
    assert after.player(P2).zone(Zone.GRAVE).concealed is False
