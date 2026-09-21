"""
Phase 2-AA — 동적 관측 권한 (dynamic observation permission).

    Effect
      → ObservationGrant      효과가 **선언**한다
      → derive_policy         지금 살아 있는 것만 남는다
      → ObservationPolicy     값
      → GameStateView         viewer 마다 다른 것을 본다

한 줄 목표: **효과가 플레이어에게 정보를 볼 권한을 동적으로 부여하고,
각 플레이어의 관측이 그 권한에 따라 서로 다른 정보를 보여준다.**

카드 이름을 보지 않는다
-----------------------
관측 계층에 카드 번호도 이름도 없다. 그것을 테스트가 직접 확인한다
(``test_k_the_observation_layer_knows_no_card``).

검증에 쓰는 실제 카드
---------------------
**마인드 온 에어 (66690411)** — ``EFFECT_PUBLIC`` 을 쓰는 실제
``LUA_VERIFIED`` 카드다. 요청받은 마인드 스캔(34298391)은 이 저장소에
**스크립트가 없어서** 그 자체로는 실행 권위를 가질 수 없다 (§K 가 그
사실을 고정한다).
"""

import ast
import pathlib
import sqlite3

import pytest

from engine.condition import Always, PlayerRef, UnimplementedRule
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.observation import (
    EMPTY_POLICY,
    LUA_PERMISSION_SOURCES,
    ActivePermission,
    ObservationPermission,
    ObservationPolicy,
)
from engine.observation_grant import ObservationGrant, derive_policy
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
P1, P2 = 0, 1

#: 실제 카드. ``EFFECT_PUBLIC`` · ``SetRange(LOCATION_MZONE)`` ·
#: ``SetTargetRange(0, LOCATION_HAND)`` — "상대는 패를 공개하고 플레이한다".
MIND_ON_AIR = 66690411
#: 실제 카드. ``SetTargetRange(LOCATION_HAND, LOCATION_HAND)`` — "양쪽 모두".
CEREMONIAL_BELL = 20228463
#: 요청받은 검증 사례. **이 저장소에 스크립트가 없다.**
MIND_SCAN = 34298391

# 서로 구분되는 카드들. 같은 카드로 채우면 "보인다" 를 확인할 수 없다.
# **전부 다른 번호여야 한다.** 하나라도 겹치면 "새지 않았다" 를 확인할 수
# 없다 — 공개된 카드의 번호가 가려진 카드의 번호와 같아지기 때문이다.
A, B, C = 55144522, 66719324, 5318639  # P1 의 패
D, E, F = 83764718, 53129443, 40640057  # P2 의 패
X, Y = 70368879, 15103313  # P2 의 뒷면
Z = 92595643  # P2 의 앞면 (원래부터 공개)
FILLER = 21844576


def new_state(repository) -> GameState:
    """
    P1 MZONE: 마인드 온 에어 (앞면) / 패: A B C
    P2 SZONE: 뒷면 X · 뒷면 Y / MZONE: 앞면 Z / 패: D E F
    """
    game = GameState.create(
        repository,
        decks=(
            [MIND_ON_AIR, A, B, C] + [FILLER] * 10,
            [X, Y, Z, D, E, F] + [FILLER] * 10,
        ),
    )
    game.draw(P1, 4)
    game.draw(P2, 3)
    game.move(
        game.player(P1).hand[0].instance_id, Zone.MZONE, to_player=P1,
        position=Position.FACEUP_ATTACK,
    )
    for _ in range(2):  # 뒷면 세트 두 장
        game.move(
            game.player(P2).hand[0].instance_id, Zone.SZONE, to_player=P2,
            position=Position.FACEDOWN,
        )
    game.move(
        game.player(P2).hand[0].instance_id, Zone.MZONE, to_player=P2,
        position=Position.FACEUP_ATTACK,
    )
    game.draw(P2, 3)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def holder_of(game: GameState) -> InstanceId:
    """P1 의 몬스터 존에 있는 그 카드 — 권한을 들고 있는 카드."""
    return game.player(P1).monster_zone[0].instance_id


def hand_of(view: GameStateView, owner: int):
    """관측에서 본 패. 가려져 있으면 ``None`` — **빈 패와 다르다.**"""
    zone = view.player(owner).zone(Zone.HAND)
    return None if zone.concealed else [card.card_id for card in zone.cards]


def spell_zone_of(view: GameStateView, owner: int):
    zone = view.player(owner).zone(Zone.SZONE)
    return [None if card is None else card.card_id for card in zone.cards]


def reveal_grant(holder, source=EffectRef(MIND_ON_AIR, 0), condition=None):
    """
    마인드 온 에어의 모양 그대로.

    ``SetRange(LOCATION_MZONE)`` → ``active_zones``
    ``SetTargetRange(0, LOCATION_HAND)`` → 앞의 ``0`` 이 "자신 쪽 없음",
    뒤가 상대 패 → ``subject=OPPONENT``
    """
    return ObservationGrant(
        permission=ObservationPermission.REVEAL_HAND,
        source=source,
        holder=holder,
        active_zones=frozenset({Zone.MZONE}),
        beneficiary=PlayerRef.CONTROLLER,
        subject=PlayerRef.OPPONENT,
        condition=condition,
    )


def inspect_grant(holder, source=EffectRef(999_001, 0), condition=None):
    return ObservationGrant(
        permission=ObservationPermission.INSPECT_FACE_DOWN,
        source=source,
        holder=holder,
        active_zones=frozenset({Zone.MZONE}),
        beneficiary=PlayerRef.CONTROLLER,
        subject=PlayerRef.OPPONENT,
        condition=condition,
    )


# ======================================================================
# A. 기본 숨은 정보 (§17 A)
# ======================================================================


def test_a_without_any_permission_the_opponent_is_opaque(state):
    """권한이 없으면 예전과 **한 글자도 다르지 않다.**"""
    for viewer in (P1, P2):
        view = GameStateView.from_state(state, viewer=viewer)

        assert hand_of(view, viewer) is not None  # 자기 패는 본다
        assert hand_of(view, 1 - viewer) is None  # 상대 패는 못 본다

    view = GameStateView.from_state(state, viewer=P1)
    assert spell_zone_of(view, P2)[:2] == [None, None]  # 상대 뒷면


def test_a_passing_an_empty_policy_changes_nothing(state):
    plain = GameStateView.from_state(state, viewer=P1)
    empty = GameStateView.from_state(state, viewer=P1, policy=EMPTY_POLICY)

    assert plain.canonical_state() == empty.canonical_state()
    assert plain.to_dict() == empty.to_dict()
    assert EMPTY_POLICY.is_empty is True


def test_a_the_owner_still_sees_their_own_face_down_card(state):
    """자기가 세트한 카드는 당연히 안다 — 권한과 무관하다."""
    view = GameStateView.from_state(state, viewer=P2)

    assert spell_zone_of(view, P2)[:2] == [X, Y]


# ======================================================================
# B. REVEAL_HAND (§17 B · §6)
# ======================================================================


def test_b_the_permission_holder_sees_the_opponents_hand(state):
    """
    §6 의 표 그대로.

        View(P1): 자기 패 → A B C · 상대 패 → D E F
        View(P2): 자기 패 → D E F · 상대 패 → hidden
    """
    policy = derive_policy(state, [reveal_grant(holder_of(state))])

    first = GameStateView.from_state(state, viewer=P1, policy=policy)
    second = GameStateView.from_state(state, viewer=P2, policy=policy)

    assert hand_of(first, P1) == [A, B, C]
    assert hand_of(first, P2) == [D, E, F]

    assert hand_of(second, P2) == [D, E, F]
    assert hand_of(second, P1) is None  # **여전히 못 본다**


def test_b_the_permission_is_not_symmetric(state):
    """`permission(P1) != permission(P2)`."""
    policy = derive_policy(state, [reveal_grant(holder_of(state))])

    assert policy.permits(ObservationPermission.REVEAL_HAND, P1, P2) is True
    assert policy.permits(ObservationPermission.REVEAL_HAND, P2, P1) is False


def test_b_both_sides_can_be_granted_separately(state):
    """
    세레모니 벨(20228463)은 ``SetTargetRange(LOCATION_HAND, LOCATION_HAND)``
    — **양쪽**이다. 선언 둘로 표현된다. 한 boolean 을 뒤집는 것이 아니다.
    """
    holder = holder_of(state)
    both = [
        reveal_grant(holder, source=EffectRef(CEREMONIAL_BELL, 0)),
        ObservationGrant(
            permission=ObservationPermission.REVEAL_HAND,
            source=EffectRef(CEREMONIAL_BELL, 0),
            holder=holder,
            active_zones=frozenset({Zone.MZONE}),
            beneficiary=PlayerRef.OPPONENT,
            subject=PlayerRef.CONTROLLER,
        ),
    ]
    policy = derive_policy(state, both)

    assert hand_of(GameStateView.from_state(state, viewer=P1, policy=policy), P2) == [D, E, F]
    assert hand_of(GameStateView.from_state(state, viewer=P2, policy=policy), P1) == [A, B, C]


def test_b_revealing_a_hand_does_not_open_the_deck(state):
    """권한은 **적어 둔 것만** 연다. 패를 공개해도 덱은 그대로다."""
    policy = derive_policy(state, [reveal_grant(holder_of(state))])
    view = GameStateView.from_state(state, viewer=P1, policy=policy)

    assert view.player(P2).zone(Zone.DECK).concealed is True
    assert view.player(P2).zone(Zone.EXTRA).concealed is True


# ======================================================================
# C. INSPECT_FACE_DOWN (§17 C · §7)
# ======================================================================


def test_c_the_permission_holder_inspects_face_down_cards(state):
    """
        View(P1): X → 확인 가능 · Y → 확인 가능 · Z → 원래부터 공개
    """
    policy = derive_policy(state, [inspect_grant(holder_of(state))])

    view = GameStateView.from_state(state, viewer=P1, policy=policy)

    assert spell_zone_of(view, P2)[:2] == [X, Y]
    (monster,) = [c for c in view.player(P2).zone(Zone.MZONE).cards if c is not None]
    assert monster.card_id == Z  # 원래 공개였던 것은 그대로


def test_c_inspecting_does_not_publish_the_card(state):
    """
    §7 — **P1 이 확인했다고 카드가 전체 공개되지 않는다.**

    권한이 없는 viewer 의 관측은 그대로이고, 카드 자체도 뒷면 그대로다.
    """
    policy = derive_policy(state, [inspect_grant(holder_of(state))])
    facedown = state.player(P2).zone(Zone.SZONE)[0].instance_id

    GameStateView.from_state(state, viewer=P1, policy=policy)  # P1 이 확인한다

    # 권한 없는 관측 — 아무것도 달라지지 않았다.
    plain = GameStateView.from_state(state, viewer=P1)
    assert spell_zone_of(plain, P2)[:2] == [None, None]
    # 카드 자체도 뒷면 그대로다.
    assert state.find_instance(facedown).is_faceup is False


def test_c_reveal_hand_and_inspect_face_down_are_different_permissions(state):
    """§3 — 둘을 합치지 않는다. 하나가 다른 하나를 주지 않는다."""
    only_hand = derive_policy(state, [reveal_grant(holder_of(state))])
    only_face = derive_policy(state, [inspect_grant(holder_of(state))])

    hand_view = GameStateView.from_state(state, viewer=P1, policy=only_hand)
    assert hand_of(hand_view, P2) == [D, E, F]
    assert spell_zone_of(hand_view, P2)[:2] == [None, None]  # 뒷면은 그대로

    face_view = GameStateView.from_state(state, viewer=P1, policy=only_face)
    assert spell_zone_of(face_view, P2)[:2] == [X, Y]
    assert hand_of(face_view, P2) is None  # 패는 그대로


def test_c_no_real_card_grants_face_down_inspection_yet():
    """
    **정직한 결과.** "상대의 세트 카드를 언제든 확인한다" 에 해당하는
    EDOPro 상수가 코퍼스에 없다. 있는 것은 ``EFFECT_PUBLIC`` 뿐이고,
    그렇게 적힌 카드(마인드 스캔)에는 스크립트가 아예 없다.

    권한의 **모양**은 만들어 두었지만 그것을 주는 실제 카드는 아직 없다.
    빈 칸 대신 ``None`` 으로 적어 두었다.
    """
    assert LUA_PERMISSION_SOURCES[ObservationPermission.INSPECT_FACE_DOWN] is None
    assert "EFFECT_PUBLIC" in (
        LUA_PERMISSION_SOURCES[ObservationPermission.REVEAL_HAND] or ""
    )

    constants = (ROOT / "data" / "constants" / "constant.lua").read_text("utf-8")
    assert "EFFECT_PUBLIC" in constants


# ======================================================================
# D · E. 생명주기 — 권한은 저장되지 않는다 (§17 D · E · §5)
# ======================================================================


def test_d_the_permission_dies_with_the_card(state):
    """
    **지우는 코드가 없다.** 카드가 그 자리를 떠나면 애초에 계산되지 않는다.
    """
    holder = holder_of(state)
    grants = [reveal_grant(holder)]

    assert derive_policy(state, grants).is_empty is False

    state.move(holder, Zone.GRAVE, to_player=P1)
    after = derive_policy(state, grants)

    assert after.is_empty is True
    assert hand_of(GameStateView.from_state(state, viewer=P1, policy=after), P2) is None


def test_d_the_permission_dies_when_the_card_leaves_its_zone(state):
    """
    ``SetRange(LOCATION_MZONE)`` 그대로다. 같은 카드라도 **그 자리에 없으면**
    권한이 없다.
    """
    holder = holder_of(state)
    grants = [reveal_grant(holder)]
    assert derive_policy(state, grants).is_empty is False

    state.move(holder, Zone.HAND, to_player=P1)  # 패로 돌아갔다

    assert derive_policy(state, grants).is_empty is True


def test_e_a_false_condition_gives_no_permission(state):
    holder = holder_of(state)

    from engine.condition import Not

    assert derive_policy(state, [reveal_grant(holder, condition=Always())]).is_empty is False
    assert derive_policy(
        state, [reveal_grant(holder, condition=Not(Always()))]
    ).is_empty is True


def test_e_an_unknown_condition_gives_no_permission(state):
    """
    §16 — **``UNKNOWN`` 을 ``TRUE`` 로 취급하지 않는다.** 모르는데 보여
    주면 숨은 정보가 새는 쪽으로 틀린다.
    """
    holder = holder_of(state)
    unknown = UnimplementedRule("이 엔진이 아직 읽지 못하는 조건")

    policy = derive_policy(state, [reveal_grant(holder, condition=unknown)])

    assert policy.is_empty is True
    assert hand_of(GameStateView.from_state(state, viewer=P1, policy=policy), P2) is None


def test_e_the_permission_comes_back_when_the_condition_does(state):
    """켜고 끄는 상태가 없으므로 **다시 계산하면 다시 살아난다.**"""
    holder = holder_of(state)

    assert derive_policy(state, [reveal_grant(holder, condition=Always())]).is_empty is False
    state.move(holder, Zone.HAND, to_player=P1)
    assert derive_policy(state, [reveal_grant(holder, condition=Always())]).is_empty is True
    state.move(
        holder, Zone.MZONE, to_player=P1, position=Position.FACEUP_ATTACK
    )
    assert derive_policy(state, [reveal_grant(holder, condition=Always())]).is_empty is False


# ======================================================================
# F. 여러 효과 (§17 F · §11)
# ======================================================================


def test_f_two_effects_grant_two_permissions(state):
    holder = holder_of(state)
    first = EffectRef(MIND_ON_AIR, 0)
    second = EffectRef(999_001, 0)

    policy = derive_policy(
        state,
        [reveal_grant(holder, source=first), inspect_grant(holder, source=second)],
    )

    assert policy.permits(ObservationPermission.REVEAL_HAND, P1, P2) is True
    assert policy.permits(ObservationPermission.INSPECT_FACE_DOWN, P1, P2) is True
    assert policy.sources(ObservationPermission.REVEAL_HAND, P1, P2) == (first,)
    assert policy.sources(ObservationPermission.INSPECT_FACE_DOWN, P1, P2) == (second,)


def test_f_removing_one_source_keeps_the_other(state):
    """
    §11 — **boolean 을 덮어쓰지 않는다.** 하나가 사라져도 나머지는 남는다.
    """
    first_holder = holder_of(state)
    # 두 번째 효과는 **다른 카드**가 들고 있다.
    second_holder = state.player(P1).hand[0].instance_id
    state.move(
        second_holder, Zone.MZONE, to_player=P1, position=Position.FACEUP_ATTACK
    )

    grants = [
        reveal_grant(first_holder, source=EffectRef(MIND_ON_AIR, 0)),
        inspect_grant(second_holder, source=EffectRef(999_001, 0)),
    ]
    assert len(derive_policy(state, grants).permissions) == 2

    state.move(first_holder, Zone.GRAVE, to_player=P1)  # 첫 효과만 사라진다
    policy = derive_policy(state, grants)

    assert policy.permits(ObservationPermission.REVEAL_HAND, P1, P2) is False
    assert policy.permits(ObservationPermission.INSPECT_FACE_DOWN, P1, P2) is True

    view = GameStateView.from_state(state, viewer=P1, policy=policy)
    assert hand_of(view, P2) is None  # 패는 다시 가려졌다
    assert spell_zone_of(view, P2)[:2] == [X, Y]  # 뒷면은 여전히 보인다


def test_f_two_sources_of_the_same_permission_are_both_tracked(state):
    """출처를 추적할 수 있다 — 같은 권한을 둘이 줘도 둘 다 적힌다."""
    holder = holder_of(state)
    left, right = EffectRef(MIND_ON_AIR, 0), EffectRef(CEREMONIAL_BELL, 0)

    policy = derive_policy(
        state, [reveal_grant(holder, source=left), reveal_grant(holder, source=right)]
    )

    assert policy.sources(ObservationPermission.REVEAL_HAND, P1, P2) == (left, right)


# ======================================================================
# G. looked_at 과의 공존 (§8)
# ======================================================================


def test_g_looked_at_and_policy_are_different_things(state):
    """
    §8 — Phase 2-Y 의 ``looked_at`` 을 대체하지 않는다.

    ``looked_at`` 은 **자기** 자리를 일시적으로 연다.
    ``policy`` 는 효과가 살아 있는 동안 **남의** 자리를 연다.
    """
    policy = derive_policy(state, [reveal_grant(holder_of(state))])

    view = GameStateView.from_state(
        state, viewer=P1, looked_at=frozenset({Zone.DECK}), policy=policy
    )

    assert view.player(P1).zone(Zone.DECK).concealed is False  # 내 덱 (looked_at)
    assert hand_of(view, P2) == [D, E, F]  # 상대 패 (policy)
    assert view.player(P2).zone(Zone.DECK).concealed is True  # 남의 덱은 여전히


def test_g_each_one_works_without_the_other(state):
    policy = derive_policy(state, [reveal_grant(holder_of(state))])

    only_look = GameStateView.from_state(
        state, viewer=P1, looked_at=frozenset({Zone.DECK})
    )
    assert only_look.player(P1).zone(Zone.DECK).concealed is False
    assert hand_of(only_look, P2) is None

    only_policy = GameStateView.from_state(state, viewer=P1, policy=policy)
    assert only_policy.player(P1).zone(Zone.DECK).concealed is True
    assert hand_of(only_policy, P2) == [D, E, F]


def test_g_a_policy_cannot_open_a_zone_it_did_not_name(state):
    """
    ``REVEAL_HAND`` 는 **패만** 연다. 권한이 자리 이름을 넘지 않는다.
    """
    policy = derive_policy(state, [reveal_grant(holder_of(state))])
    view = GameStateView.from_state(state, viewer=P1, policy=policy)

    assert view.player(P2).zone(Zone.DECK).concealed is True
    assert spell_zone_of(view, P2)[:2] == [None, None]


# ======================================================================
# H. 판을 바꾸지 않는다 (§17 H · I · §9 · §13)
# ======================================================================


def test_h_building_a_view_never_touches_the_board(state):
    """§9 — 보는 것 자체가 상태 변경이 되지 않는다."""
    policy = derive_policy(
        state, [reveal_grant(holder_of(state)), inspect_grant(holder_of(state))]
    )
    before = state.state_hash()
    canonical = state.canonical_state()
    deck = state.player(P2).deck.card_ids()

    for _ in range(5):
        for viewer in (P1, P2):
            GameStateView.from_state(
                state, viewer=viewer, looked_at=frozenset({Zone.DECK}), policy=policy
            )
            derive_policy(state, [reveal_grant(holder_of(state))])

    assert state.state_hash() == before
    assert state.canonical_state() == canonical
    assert state.player(P2).deck.card_ids() == deck
    assert state.journal == []


def test_h_the_board_hash_does_not_carry_who_is_looking(state):
    """
    §13 — 권한은 판 + 효과에서 **파생되는 값**이다. 판에 저장된 것이
    아니므로 해시에 넣을 것이 없다. ``state_hash`` 의 뜻을 바꾸지 않았다.
    """
    policy = derive_policy(state, [reveal_grant(holder_of(state))])
    before = state.state_hash()

    GameStateView.from_state(state, viewer=P1, policy=policy)
    GameStateView.from_state(state, viewer=P2, policy=EMPTY_POLICY)

    assert state.state_hash() == before
    assert "permission" not in repr(state.canonical_state())


def test_g_clone_independence(repository):
    """§17 G — 사본에서 권한이 사라져도 원본의 관측은 그대로다."""
    original = new_state(repository)
    clone = original.clone()
    holder = holder_of(original)
    grants = [reveal_grant(holder)]

    # 사본에서만 카드를 치운다.
    clone.move(holder, Zone.GRAVE, to_player=P1)

    assert derive_policy(clone, grants).is_empty is True
    assert derive_policy(original, grants).is_empty is False

    assert hand_of(
        GameStateView.from_state(original, viewer=P1, policy=derive_policy(original, grants)),
        P2,
    ) == [D, E, F]
    assert hand_of(
        GameStateView.from_state(clone, viewer=P1, policy=derive_policy(clone, grants)),
        P2,
    ) is None


def test_h_the_same_board_gives_the_same_observation(repository):
    """결정론 — 같은 판 · 같은 권한 · 같은 viewer 면 같은 관측이다."""
    left, right = new_state(repository), new_state(repository)
    grants_left = [reveal_grant(holder_of(left))]
    grants_right = [reveal_grant(holder_of(right))]

    first = GameStateView.from_state(
        left, viewer=P1, policy=derive_policy(left, grants_left)
    )
    second = GameStateView.from_state(
        right, viewer=P1, policy=derive_policy(right, grants_right)
    )

    assert first.canonical_state() == second.canonical_state()
    assert derive_policy(left, grants_left).canonical_state() == derive_policy(
        right, grants_right
    ).canonical_state()


# ======================================================================
# I · J. 정보 유출 (§17 J · §10)
# ======================================================================


def test_j_a_viewer_without_permission_leaks_nothing(state):
    """
    §10 — ``repr`` · ``str`` · ``to_dict`` 어느 경로로도 새지 않는다.
    """
    policy = derive_policy(state, [reveal_grant(holder_of(state))])
    view = GameStateView.from_state(state, viewer=P2, policy=policy)

    rendered = repr(view.to_dict()) + repr(view) + str(view)
    for secret in (A, B, C):
        assert str(secret) not in rendered

    # ``instance_id`` 는 작은 정수라 문자열로 찾으면 ``viewer: 1`` 같은
    # 엉뚱한 자리에 걸린다. **구조로** 확인한다 — 가려진 자리는 카드를
    # 하나도 담지 않는다.
    secret_instances = {card.instance_id for card in state.player(P1).hand}
    assert secret_instances
    hidden = view.player(P1).zone(Zone.HAND)
    assert hidden.concealed is True
    assert hidden.cards == ()

    visible = {
        card.instance_id
        for player in view.players
        for zone in player.zones
        for card in (zone.cards or ())
        if card is not None
    }
    assert not (visible & secret_instances)


def test_j_the_policy_itself_names_no_card(state):
    """
    권한의 **존재**는 공개 정보지만 그것이 보여 주는 **내용**은 아니다.
    ``ActivePermission.to_dict`` 에 카드의 정체가 없다.
    """
    policy = derive_policy(state, [reveal_grant(holder_of(state))])
    (active,) = policy.permissions

    rendered = repr(policy.to_dict()) + policy.describe_ko()
    for secret in (D, E, F, X, Y):
        assert str(secret) not in rendered
    assert set(active.to_dict()) == {"permission", "viewer", "about", "source"}
    # holder 의 instance_id 도 밖으로 나가는 표현에는 없다.
    assert "holder" not in active.to_dict()


def test_j_the_authoritative_state_still_knows_everything(state):
    """
    **엔진이 아는 것은 그대로다.** 문제는 잘못된 viewer 에게 노출되는
    것이지 엔진이 아는 것 자체가 아니다.
    """
    for card in state.player(P1).hand:
        assert card.card_id in (A, B, C)
    facedown = state.player(P2).zone(Zone.SZONE)[0]
    assert facedown.card_id == X
    assert facedown.is_faceup is False


# ======================================================================
# K. 마인드 스캔 검증 (§4 · §17 K)
# ======================================================================


def test_k_mind_scan_is_in_the_official_database(repository):
    """**카드 텍스트를 추측하지 않는다.** 저장소의 공식 데이터를 읽는다."""
    with sqlite3.connect(ROOT / "data" / "cards.cdb") as connection:
        row = connection.execute(
            "SELECT name, desc FROM texts WHERE id = ?", (MIND_SCAN,)
        ).fetchone()

    assert row is not None
    name, text = row
    assert name == "Mind Scan"
    # 이번 Phase 가 다루는 첫 번째 효과의 두 부분이 원문에 있다.
    assert "keep their hand revealed" in text
    assert "look at their Set cards" in text
    assert "Toon" in text


def test_k_mind_scan_has_no_script_in_this_repository():
    """
    **정직한 결과.** 공식 DB 에 텍스트는 있지만 EDOPro 스크립트가 없다.
    그러므로 이 카드의 의미는 ``LUA_VERIFIED`` 가 아니고, 목록에 실행
    가능한 항목으로 올릴 수 없다 (ADR-004).

    그래서 이 카드는 **구조를 검증하는 시나리오**로만 쓴다.
    """
    assert not (ROOT / f"c{MIND_SCAN}.lua").is_file()
    # 대신 검증에 쓰는 카드는 스크립트가 있다.
    assert (ROOT / f"c{MIND_ON_AIR}.lua").is_file()
    script = (ROOT / f"c{MIND_ON_AIR}.lua").read_text("utf-8")
    assert "EFFECT_PUBLIC" in script
    assert "SetRange(LOCATION_MZONE)" in script
    assert "SetTargetRange(0,LOCATION_HAND)" in script


def test_k_mind_scans_shape_is_expressible_but_its_condition_is_not(state):
    """
    §4 · §16 — 마인드 스캔이 요구하는 **두 권한의 모양**은 그대로 적힌다.

    막는 것은 조건이다. "자신의 필드나 묘지에 '툰' 카드가 존재" 를
    판정하려면 아키타입(setcode) 조건이 필요한데 이 엔진에 없다. 그래서
    :class:`UnimplementedRule` 로 적고, 결과는 ``UNKNOWN`` → **권한 없음**
    이다. 추측해서 켜지 않는다.
    """
    holder = holder_of(state)
    toon = UnimplementedRule("'툰' 카드가 자신 필드나 묘지에 존재 (setcode 조건 없음)")
    declared = [
        reveal_grant(holder, source=EffectRef(MIND_SCAN, 0), condition=toon),
        inspect_grant(holder, source=EffectRef(MIND_SCAN, 0), condition=toon),
    ]

    policy = derive_policy(state, declared)

    assert policy.is_empty is True
    view = GameStateView.from_state(state, viewer=P1, policy=policy)
    assert hand_of(view, P2) is None
    assert spell_zone_of(view, P2)[:2] == [None, None]


def test_k_with_the_condition_answered_the_whole_path_runs(state):
    """
    같은 선언에 조건만 **밖에서 답을 받아** 끼우면 둘 다 살아난다 —
    구조가 작동한다는 것이 확인된다.

    ``Always()`` 는 "툰 카드가 있다" 를 주장하지 않는다. 판정 계층이
    없어서 테스트가 답을 대신 준 것이고, 저장소는 여전히 모른다
    (싸이크론의 파괴 판정과 같은 자리).
    """
    holder = holder_of(state)
    declared = [
        reveal_grant(holder, source=EffectRef(MIND_SCAN, 0), condition=Always()),
        inspect_grant(holder, source=EffectRef(MIND_SCAN, 0), condition=Always()),
    ]

    policy = derive_policy(state, declared)
    view = GameStateView.from_state(state, viewer=P1, policy=policy)
    other = GameStateView.from_state(state, viewer=P2, policy=policy)

    assert hand_of(view, P2) == [D, E, F]
    assert spell_zone_of(view, P2)[:2] == [X, Y]
    # 상대에게는 아무것도 열리지 않았다.
    assert hand_of(other, P1) is None


def test_k_the_observation_layer_knows_no_card():
    """
    **가장 중요한 단언.** 관측 계층에 카드 번호도 카드 이름도 없다.

    ``if card.name == "마인드 스캔": reveal_hand = True`` 같은 것이 들어오면
    이 계층은 일반화된 경계가 아니라 특수 처리 목록이 된다.
    """
    import re

    for relative in (
        "engine/observation.py",
        "engine/observation_grant.py",
        "engine/game_state_view.py",
    ):
        source = (ROOT / relative).read_text("utf-8")
        tree = ast.parse(source)

        # 1. 카드 번호를 뜻하는 큰 정수 상수가 없다.
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, int):
                assert node.value < 100_000, (relative, node.value)

        # 2. ``card_id`` · ``name`` 을 **구체적인 값과** 비교하지 않는다.
        #
        #    ``self.card_id is not None`` 은 "공개되었는가" 를 묻는 것이지
        #    어느 카드인지 보는 것이 아니다. 금지해야 하는 것은
        #    ``card.card_id == 34298391`` 처럼 **특정 카드를 지목하는** 비교다.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            sides = [node.left, *node.comparators]
            names = {
                side.attr
                for side in sides
                if isinstance(side, ast.Attribute)
            }
            if not names & {"card_id", "name", "name_ko", "name_en"}:
                continue
            for side in node.comparators:
                assert not (
                    isinstance(side, ast.Constant) and side.value is not None
                ), (relative, ast.dump(node)[:160])

        # 3. 주석이 아닌 코드에 카드 이름이 없다.
        assert not re.search(r"Mind Scan|마인드 스캔", "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")
        ))
