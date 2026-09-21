"""
Phase 2-Y — 관측 경계와 이동 관문의 분리 (STRUCTURAL-69).

세 가지를 **절대 합치지 않는다** (§3).

    A. INTERNAL_STATE_KNOWLEDGE   엔진이 실제 상태를 아는가   → GameState
    B. PLAYER_OBSERVABILITY       그 사람이 볼 수 있는가      → GameStateView
    C. 규칙 판정에 그 정보가 필요한가                          → 효과의 후보 규칙

STRUCTURAL-69 는 셋 중 **B 에 표현할 수 없는 경우가 있던 것**이다.
``_zone_view`` 가 자리 이름만 보고 공개 범위를 정했고, "이 효과는 자기
덱을 들여다본다" 를 말할 자리가 없었다. 룰북은 그 경우를 명시한다:

    "If a card effect requires you to reveal cards from your Deck, or look
    through it, shuffle it and put it back in this space afterwards."
    — sd-rulebook-en-v10, Deck

그래서 고친 것은 **기본 공개 범위가 아니라 표현력**이다. 기본값은 한
글자도 바뀌지 않았고, 효과가 자기 자리를 이름으로 말할 때만 열린다.

네 상태를 구분하는 것이 이 파일의 목표다 (§8).

    CASE 1  관측 가능 + 관문 TRUE      → 실행
    CASE 2  관측 가능 + 관문/조건 FALSE → ILLEGAL
    CASE 3  관측 불가                  → HIDDEN_CARD
    CASE 4  관측 가능 + 관문 근거 없음  → UNCHECKED_RULES
"""

import pathlib

import pytest

from engine.condition import IsMonster, PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, CostGroup, Selection
from engine.effect.definition import EffectDefinition, EffectProvenance
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.operation import CardOperation, OperationKind
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.semantics import MISSING_GATE, DeclaredMovementRuling
from engine.effect.target import PRIMARY_TARGET, TargetBinding, TargetSpec
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone, ZoneVisibility, zone_visibility

from tests.conftest import requires_official_db

pytestmark = requires_official_db

MINE, THEIRS = 0, 1
FEATHERMAN = 21844576  # 통상 몬스터
MST = 5318639  # 마법 — 몬스터가 아니다
LAB = 999002  # synthetic 정의의 자리. 실제 카드 번호가 아니다.

#: 플레이어 한 명이 갖는 자리 전부. 빠뜨리면 조사가 반쪽이 된다.
ALL_ZONES = (
    Zone.DECK,
    Zone.HAND,
    Zone.EXTRA,
    Zone.MZONE,
    Zone.SZONE,
    Zone.GRAVE,
    Zone.REMOVED,
)


def new_state(repository) -> GameState:
    """
    양쪽에 같은 모양의 판을 만든다.

    p0(MINE) · p1(THEIRS) 각각:
      MZONE 앞면 몬스터 · SZONE **뒷면** 세트 · GRAVE 1장 · 패 2장 · 덱 다수
    """
    # 마법은 **덱 깊은 곳**에 둔다 — 초기 드로우에 딸려 나오면 "덱에
    # 몬스터가 아닌 카드가 있다" 를 시험할 수 없다.
    deck = [FEATHERMAN] * 8 + [MST] + [FEATHERMAN] * 11
    game = GameState.create(repository, decks=(list(deck), list(deck)))
    for seat in (MINE, THEIRS):
        game.draw(seat, 5)
        hand = game.player(seat).hand
        game.move(hand[0].instance_id, Zone.MZONE, to_player=seat,
                  position=Position.FACEUP_ATTACK)
        game.move(game.player(seat).hand[0].instance_id, Zone.SZONE, to_player=seat,
                  position=Position.FACEDOWN)
        game.move(game.player(seat).hand[0].instance_id, Zone.GRAVE, to_player=seat)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def deck_card(game: GameState, seat: int, card_id: int) -> InstanceId:
    """
    그 자리 덱에서 그 번호의 카드. **엔진 내부 지식이다** (§3 의 A).

    테스트가 이것을 쓸 수 있다는 사실 자체가 A 와 B 가 다르다는 증거다 —
    엔진은 알고 있고, 관측은 모를 수 있다.
    """
    for card in game.player(seat).deck:
        if card.card_id == card_id:
            return card.instance_id
    raise AssertionError(f"p{seat} 덱에 {card_id} 가 없습니다.")


def ids_in(view: GameStateView, seat: int, zone: Zone):
    zv = view.player(seat).zone(zone)
    if zv is None or zv.concealed:
        return None
    return tuple(c.card_id for c in zv.cards if c is not None)


# ======================================================================
# A. 기본 관측 정책 — 무엇이 보이는가 (§2)
# ======================================================================


def test_a_the_default_policy_is_unchanged_and_written_down(state):
    """
    **"자기 카드니까 보인다" 로 일반화하지 않는다.** 실제 코드가 정하는
    것을 자리마다 적는다. 이것이 Phase 2-Y 이전과 **똑같은** 기본값이다.
    """
    view = GameStateView.from_state(state, viewer=MINE)

    seen = {
        (owner, zone): view.player(owner).zone(zone).concealed
        for owner in (MINE, THEIRS)
        for zone in ALL_ZONES
    }

    assert seen == {
        # 자기 자리
        (MINE, Zone.DECK): True,  # **자기 덱도 가려진다** — 그것이 기본 규칙이다
        (MINE, Zone.HAND): False,
        (MINE, Zone.EXTRA): False,
        (MINE, Zone.MZONE): False,
        (MINE, Zone.SZONE): False,
        (MINE, Zone.GRAVE): False,
        (MINE, Zone.REMOVED): False,
        # 상대 자리
        (THEIRS, Zone.DECK): True,
        (THEIRS, Zone.HAND): True,
        (THEIRS, Zone.EXTRA): True,
        (THEIRS, Zone.MZONE): False,
        (THEIRS, Zone.SZONE): False,  # 자리는 보이지만 **카드는 가려진다**
        (THEIRS, Zone.GRAVE): False,
        (THEIRS, Zone.REMOVED): False,
    }


def test_a_a_face_down_set_card_is_concealed_card_by_card(state):
    """
    존이 공개라고 카드가 공개인 것이 아니다. 상대의 뒷면 세트 카드는
    ``card_id`` 가 없고, **자기 것은 보인다.**
    """
    view = GameStateView.from_state(state, viewer=MINE)

    (mine_set,) = [c for c in view.player(MINE).zone(Zone.SZONE).cards if c is not None]
    (their_set,) = [
        c for c in view.player(THEIRS).zone(Zone.SZONE).cards if c is not None
    ]

    assert mine_set.card_id is not None
    assert their_set.card_id is None


def test_a_the_zone_visibility_table_is_the_source_of_truth():
    """공개 범위는 자리마다 표가 정한다. 추론하지 않는다."""
    assert zone_visibility(Zone.DECK) is ZoneVisibility.HIDDEN
    assert zone_visibility(Zone.HAND) is ZoneVisibility.OWNER_ONLY
    assert zone_visibility(Zone.EXTRA) is ZoneVisibility.OWNER_ONLY
    assert zone_visibility(Zone.GRAVE) is ZoneVisibility.PUBLIC
    assert zone_visibility(Zone.MZONE) is ZoneVisibility.PUBLIC


def test_a_size_is_public_even_when_the_contents_are_not(state):
    """
    "빈 덱" 과 "안 보이는 덱" 은 다르다. 장수는 공개다 — 룰북의
    ``count_public`` 그대로.
    """
    view = GameStateView.from_state(state, viewer=MINE)

    for owner in (MINE, THEIRS):
        deck = view.player(owner).zone(Zone.DECK)
        assert deck.concealed is True
        assert deck.cards == ()
        assert deck.size == len(state.player(owner).deck)
        assert deck.size > 0


# ======================================================================
# B. 엔진이 아는 것 ≠ 플레이어가 보는 것 (§3)
# ======================================================================


def test_b_the_engine_knows_what_the_observation_does_not(state):
    """
    §3 A/B — 둘을 하나의 boolean 으로 합치지 않는다.

    엔진은 자기 덱의 카드를 **알고 있다.** 그래도 기본 관측은 모른다.
    """
    card = deck_card(state, MINE, MST)

    # A — 엔진 내부 지식
    assert state.find_instance(card) is not None
    assert state.find_instance(card).card_id == MST
    assert state.locate(card).zone is Zone.DECK

    # B — 기본 관측
    view = GameStateView.from_state(state, viewer=MINE)
    assert view.player(MINE).zone(Zone.DECK).concealed is True
    assert ids_in(view, MINE, Zone.DECK) is None


def test_b_looking_opens_only_the_viewers_own_zone(state):
    """
    **이 테스트가 §4 · §16 의 방어선이다.**

    자기 덱을 들여다보게 해도 **상대 덱은 열리지 않는다.** 그 방어는
    ``_zone_view`` 한 곳에 있고, ``owner == viewer`` 가 그것이다.
    """
    view = GameStateView.from_state(
        state, viewer=MINE, looked_at=frozenset({Zone.DECK})
    )

    assert view.player(MINE).zone(Zone.DECK).concealed is False
    assert view.player(THEIRS).zone(Zone.DECK).concealed is True
    assert ids_in(view, THEIRS, Zone.DECK) is None


def test_b_looking_at_every_zone_still_opens_nothing_of_the_opponents(state):
    """
    **최악의 경우**를 본다. 부르는 쪽이 모든 자리를 넘겨도 상대의 가려진
    자리는 하나도 열리지 않는다.
    """
    view = GameStateView.from_state(
        state, viewer=MINE, looked_at=frozenset(ALL_ZONES)
    )

    assert view.player(THEIRS).zone(Zone.DECK).concealed is True
    assert view.player(THEIRS).zone(Zone.HAND).concealed is True
    assert view.player(THEIRS).zone(Zone.EXTRA).concealed is True
    # 뒷면 세트도 여전히 가려진다 — 카드 단위 판정은 별개다.
    (their_set,) = [
        c for c in view.player(THEIRS).zone(Zone.SZONE).cards if c is not None
    ]
    assert their_set.card_id is None


def test_b_the_default_is_exactly_the_old_behaviour(state):
    """
    ``looked_at`` 을 주지 않으면 **한 글자도 달라지지 않는다.**
    빈 집합을 주는 것과도 같다.
    """
    plain = GameStateView.from_state(state, viewer=MINE)
    empty = GameStateView.from_state(state, viewer=MINE, looked_at=frozenset())

    assert plain.canonical_state() == empty.canonical_state()
    assert plain.to_dict() == empty.to_dict()


def test_b_the_observation_never_changes_the_board(state):
    """관측을 만드는 것은 읽기다. 들여다봐도 판은 그대로다."""
    before = state.state_hash()

    GameStateView.from_state(state, viewer=MINE, looked_at=frozenset(ALL_ZONES))
    GameStateView.from_state(state, viewer=THEIRS, looked_at=frozenset(ALL_ZONES))

    assert state.state_hash() == before


# ======================================================================
# C. 무엇을 들여다볼지는 **규칙이 스스로 말한다** (§3 C)
# ======================================================================


def source_of(zones, owner=PlayerRef.CONTROLLER, chooser=PlayerRef.CONTROLLER):
    return ChoiceSpec(
        source=CandidateSource(zones=frozenset(zones), owner=owner), chooser=chooser
    )


def test_c_a_rule_that_reads_its_own_deck_says_so():
    spec = TargetSpec.choosing(source_of({Zone.DECK}))
    assert spec.looked_at_zones() == frozenset({Zone.DECK})


def test_c_a_rule_over_the_opponents_zone_grants_nothing():
    """
    **남의 자리에서 고르라는 규칙이 남의 자리를 볼 권리를 주지는
    않는다.** 상대 패에서 고르게 하는 효과는 공개 효과가 따로 필요하다.
    """
    spec = TargetSpec.choosing(source_of({Zone.HAND}, owner=PlayerRef.OPPONENT))
    assert spec.looked_at_zones() == frozenset()


def test_c_a_rule_over_both_sides_names_the_zone_and_the_view_narrows_it(state):
    """
    ``owner=None`` (양쪽) 이면 자리 이름은 그대로 나오지만, 실제로 열리는
    것은 **보는 사람 자신의 자리뿐**이다. 두 계층이 각자 자기 몫을 한다.
    """
    spec = TargetSpec.choosing(source_of({Zone.DECK}, owner=None))
    assert spec.looked_at_zones() == frozenset({Zone.DECK})

    view = GameStateView.from_state(
        state, viewer=MINE, looked_at=spec.looked_at_zones()
    )
    assert view.player(MINE).zone(Zone.DECK).concealed is False
    assert view.player(THEIRS).zone(Zone.DECK).concealed is True


def test_c_a_rule_the_opponent_chooses_grants_the_controller_nothing():
    """
    고르는 사람이 상대면 컨트롤러의 관측을 넓히지 않는다 — 엉뚱한 사람이
    보게 된다.
    """
    spec = TargetSpec.choosing(
        source_of({Zone.DECK}, owner=PlayerRef.CONTROLLER, chooser=PlayerRef.OPPONENT)
    )
    assert spec.looked_at_zones() == frozenset()


def test_c_a_rule_with_nothing_to_choose_looks_at_nothing():
    assert TargetSpec().looked_at_zones() == frozenset()


def test_c_the_declaration_is_read_not_inferred():
    """
    자리 이름은 **규칙이 적어 둔 것**이다. 엔진이 "덱에서 고르니까 덱을
    보겠지" 하고 넓히는 것이 아니라, ``CandidateSource.zones`` 를 그대로
    읽는다.
    """
    for zones in ({Zone.GRAVE}, {Zone.HAND}, {Zone.DECK, Zone.GRAVE}):
        assert TargetSpec.choosing(source_of(zones)).looked_at_zones() == frozenset(
            zones
        )


# ======================================================================
# synthetic 정의 — 아무 카드의 의미도 주장하지 않는다
# ======================================================================


def synthetic(zones, *, gated: bool, owner=PlayerRef.CONTROLLER, ordinal=0):
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.choosing(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=frozenset(zones), owner=owner, require=IsMonster()
                    )
                )
            )
        ),
        operations=(CardOperation.send_to_grave(PRIMARY_TARGET, gated=gated),),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(
            verified=True, note="Phase 2-Y 관측 시험"
        ),
    )


def run(state, definition, *chosen, movement=None, journal=None):
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        journal=journal,
        movement=movement,
    )
    return executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref,
            controller=MINE,
            selections=(
                (TargetSelection(PRIMARY_TARGET, Selection(chosen=tuple(chosen))),)
                if chosen
                else ()
            ),
        ),
    )


# ======================================================================
# D. 네 상태를 합치지 않는다 (§5 · §8)
# ======================================================================


def test_d_case_1_observable_and_the_gate_says_yes(state):
    """CASE 1 — 관측 가능 + 관문 TRUE → 실행."""
    card = deck_card(state, MINE, FEATHERMAN)
    before = state.state_hash()

    result = run(
        state,
        synthetic({Zone.DECK}, gated=True),
        card,
        movement=DeclaredMovementRuling(sendable=frozenset({card})),
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(card).zone is Zone.GRAVE
    assert state.state_hash() != before


def test_d_case_2_observable_and_plainly_not_a_candidate(state):
    """
    CASE 2 — 관측 가능한데 **규칙상 후보가 아니다.** 덱이 보이니까
    "몬스터가 아니다" 를 말할 수 있다. 관측 문제가 아니다.
    """
    spell = deck_card(state, MINE, MST)
    before = state.state_hash()

    result = run(
        state,
        synthetic({Zone.DECK}, gated=True),
        spell,
        movement=DeclaredMovementRuling(sendable=frozenset({spell})),
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert result.code is not ValidationCode.HIDDEN_CARD
    assert state.state_hash() == before


def test_d_case_3_not_observable(state):
    """CASE 3 — 상대 덱은 여전히 안 보인다. **관문에 닿지 않는다.**"""
    theirs = deck_card(state, THEIRS, FEATHERMAN)
    before = state.state_hash()

    result = run(
        state,
        synthetic({Zone.DECK}, gated=True),
        theirs,
        movement=DeclaredMovementRuling(sendable=frozenset({theirs})),
    )

    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.HIDDEN_CARD
    assert result.missing != MISSING_GATE[OperationKind.SEND_TO_GRAVE]
    assert state.state_hash() == before


def test_d_case_4_observable_but_the_gate_has_no_grounds(state):
    """
    CASE 4 — 볼 수 있다. 그런데 **이 카드가 묘지로 갈 수 있는지 모른다.**
    추측하지 않는다.
    """
    card = deck_card(state, MINE, FEATHERMAN)
    before = state.state_hash()

    result = run(state, synthetic({Zone.DECK}, gated=True), card)

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert result.missing == MISSING_GATE[OperationKind.SEND_TO_GRAVE]
    assert state.state_hash() == before


def test_d_the_four_cases_give_four_different_answers(state):
    """
    **네 상태를 절대로 합치지 않는다** (§8). 네 답이 서로 다르다.
    """
    monster = deck_card(state, MINE, FEATHERMAN)
    spell = deck_card(state, MINE, MST)
    theirs = deck_card(state, THEIRS, FEATHERMAN)
    definition = synthetic({Zone.DECK}, gated=True)
    allow = DeclaredMovementRuling(sendable=frozenset({monster, spell, theirs}))

    answers = {
        "CASE 2 규칙상 아니다": run(state, definition, spell, movement=allow),
        "CASE 3 안 보인다": run(state, definition, theirs, movement=allow),
        "CASE 4 관문을 모른다": run(state, definition, monster),
        # CASE 1 은 판을 바꾸므로 **마지막에** 잰다.
        "CASE 1 실행": run(state, definition, monster, movement=allow),
    }

    pairs = {name: (r.status, r.code) for name, r in answers.items()}
    assert len(set(pairs.values())) == 4, pairs
    assert answers["CASE 1 실행"].status is ResolutionStatus.RESOLVED
    for name in ("CASE 2 규칙상 아니다", "CASE 3 안 보인다", "CASE 4 관문을 모른다"):
        assert answers[name].applied == (), name
        assert answers[name].deltas == (), name


def test_d_observation_failure_and_gate_failure_name_different_missing_layers(state):
    """
    §5 — 두 UNKNOWN 이 **서로 다른 이유로 기록된다.** ``missing`` 이
    다르다는 것이 그 증거다.
    """
    theirs = deck_card(state, THEIRS, FEATHERMAN)
    mine = deck_card(state, MINE, FEATHERMAN)
    definition = synthetic({Zone.DECK}, gated=True)

    hidden = run(state, definition, theirs)
    gate = run(state, definition, mine)

    assert hidden.code is ValidationCode.HIDDEN_CARD
    assert gate.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert hidden.missing != gate.missing
    assert gate.missing == MISSING_GATE[OperationKind.SEND_TO_GRAVE]


def test_d_an_ungated_operation_reaches_the_board_once_it_is_observable(state):
    """
    관문을 선언하지 않은 효과는 관측만 통과하면 실행된다. 관측과 관문이
    **따로 움직인다**는 것을 반대쪽에서 확인한다.
    """
    card = deck_card(state, MINE, FEATHERMAN)

    result = run(state, synthetic({Zone.DECK}, gated=False, ordinal=1), card)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(card).zone is Zone.GRAVE


# ======================================================================
# E. 실패 안전성 (§9)
# ======================================================================


def test_e_no_failure_touches_the_board_or_the_record(state):
    monster = deck_card(state, MINE, FEATHERMAN)
    spell = deck_card(state, MINE, MST)
    theirs = deck_card(state, THEIRS, FEATHERMAN)
    gated = synthetic({Zone.DECK}, gated=True)

    cases = {
        "HIDDEN_CARD": lambda j: run(state, gated, theirs, journal=j),
        "CANDIDATE_NOT_ELIGIBLE": lambda j: run(
            state, gated, spell,
            movement=DeclaredMovementRuling(sendable=frozenset({spell})), journal=j,
        ),
        "UNCHECKED_RULES": lambda j: run(state, gated, monster, journal=j),
        "관문이 거절": lambda j: run(
            state, gated, monster,
            movement=DeclaredMovementRuling(unsendable=frozenset({monster})),
            journal=j,
        ),
        "안 고름": lambda j: run(state, gated, journal=j),
        "없는 카드": lambda j: run(state, gated, InstanceId(9999), journal=j),
    }

    for label, invoke in cases.items():
        journal = EventJournal()
        before = state.state_hash()
        result = invoke(journal)

        assert result.status is not ResolutionStatus.RESOLVED, label
        assert result.applied == (), label
        assert result.deltas == (), label
        assert state.state_hash() == before, label
        assert len(journal) == 0, label
        observed = EventReader(
            GameStateView.from_state(state, viewer=MINE)
        ).read(result, actor=MINE)
        assert observed == (), label


def test_e_a_refusal_never_names_a_card_the_viewer_cannot_see(state):
    """§13 — 상대 덱 카드를 골라도 그 정체가 결과에 실리지 않는다."""
    theirs = deck_card(state, THEIRS, MST)
    identity = state.find_instance(theirs).card_id

    result = run(state, synthetic({Zone.DECK}, gated=True), theirs)

    rendered = repr(result.to_dict()) + (result.reason or "")
    assert str(identity) not in rendered
    assert str(theirs.value) not in rendered


# ======================================================================
# F. 결정론 · 복제 (§10)
# ======================================================================


def test_f_the_observation_is_deterministic(repository):
    first, second = new_state(repository), new_state(repository)
    looked = frozenset({Zone.DECK})

    left = GameStateView.from_state(first, viewer=MINE, looked_at=looked)
    right = GameStateView.from_state(second, viewer=MINE, looked_at=looked)

    assert left.canonical_state() == right.canonical_state()
    assert first.state_hash() == second.state_hash()


def test_f_the_same_look_twice_gives_the_same_answer(state):
    looked = frozenset({Zone.DECK})

    first = GameStateView.from_state(state, viewer=MINE, looked_at=looked)
    second = GameStateView.from_state(state, viewer=MINE, looked_at=looked)

    assert first.canonical_state() == second.canonical_state()


def test_f_the_gate_result_is_deterministic(repository):
    first, second = new_state(repository), new_state(repository)

    left = run(first, synthetic({Zone.DECK}, gated=True), deck_card(first, MINE, FEATHERMAN))
    right = run(second, synthetic({Zone.DECK}, gated=True), deck_card(second, MINE, FEATHERMAN))

    assert left.canonical_state() == right.canonical_state()
    assert first.state_hash() == second.state_hash()


def test_f_a_clone_is_independent(state):
    """§14-10 — 복제본에서 들여다보고 실행해도 원본은 그대로다."""
    clone = state.clone()
    card = deck_card(clone, MINE, FEATHERMAN)
    before = state.state_hash()

    result = run(
        clone,
        synthetic({Zone.DECK}, gated=True),
        card,
        movement=DeclaredMovementRuling(sendable=frozenset({card})),
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert state.state_hash() == before
    assert clone.state_hash() != before
    assert state.locate(card).zone is Zone.DECK


def test_f_no_choice_logic_entered_the_observation():
    """
    §11 — 관측은 "볼 수 있는가" 만 답한다. 무엇을 고를지는 AI 의
    영역이고 이 계층에 들어오지 않았다.
    """
    import ast

    root = pathlib.Path(__file__).resolve().parents[2]
    source = (root / "engine" / "game_state_view.py").read_text("utf-8")
    tree = ast.parse(source)
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }

    for forbidden in ("choose", "score", "policy", "best", "prefer"):
        assert not any(forbidden in name.lower() for name in names), forbidden
    assert "random" not in source
