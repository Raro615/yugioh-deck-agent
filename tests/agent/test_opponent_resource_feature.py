r"""
Phase 3-F-2 — 상대 자원 feature 의 회귀 시험.

Phase 3-F-1 이 측정한 결함: 평가가 "내 필드가 강해졌다" 와 "상대에게 자원을
제공했다" 를 **구분하지 못했다.** 뒤쪽에 대응하는 feature 가 없었고, 움직이는
유일한 항(``deck``)이 **반대 방향으로** 움직였다.

이 Phase 가 더한 것은 **관측 둘**이고 **점수는 하나도 아니다.**

==============================  =============================================
:class:`OpponentResources`       **지금** 상대가 들고 있는 공개 자원의 장수
:class:`OpponentResourceDelta`   두 관측 **사이**의 장수 변화와,
                                 그중 안전하게 "상대가 얻었다" 고 말할 수
                                 있는 양(``drawn_from_deck``)
==============================  =============================================

이 파일이 지키는 것
-------------------
**장수만 읽는다.** 상대의 패 · 덱 · 엑스트라 덱은 ``size`` 가 관측에 들어오고
내용은 들어오지 않는다. 전자만 쓴다 (``test_03`` · ``test_04``).

**이동했다고 무조건 자원 +1 로 세지 않는다.** 덱이 줄고 그만큼 패가 늘어난
경우만 드로우로 센다. 나머지 변화는 **값으로 세지 않고** ``UNKNOWN`` 으로 적는다
(``test_08``–``test_11``).

**current 와 delta 를 섞지 않는다.** "상대에게 3장을 줬다" 와 "상대 패가 지금
3장이다" 는 다른 사실이다 (``test_06``).

**점수를 바꾸지 않았다.** ``StateValue`` 는 네 칸 그대로이고 가중치도 그대로다 —
상대 자원에 **가중치를 붙이지 않았다** (``test_16``–``test_18``).

**증G benchmark.** 전개량이 같고 상대에게 준 자원만 다른 두 상태(C · D)의 차이가
feature 에서 **사라지지 않는다** (``test_12``–``test_14``). 단 C 가 D 보다 낮은
점수가 되도록 **강제하지 않는다** — 그것은 가중치 문제이고 이 Phase 의 몫이
아니다.
"""

import dataclasses
import pathlib

import pytest

from agent.evaluation import (
    DECK_CARD_IN_LP,
    OPPONENT_RESOURCE_ZONES,
    EvaluationError,
    ExclusionCategory,
    OpponentResourceDelta,
    OpponentResources,
    StateEvaluator,
    StateValue,
)
from agent.search import SearchCandidate
from engine.game_state_view import GameStateView
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

LUSTER_DRAGON = 11091375  # ATK 1900
POT_OF_GREED = 55144522

#: 읽는 자리 일곱. 늘거나 줄면 feature 의 범위가 바뀐 것이다.
ZONE_NAMES = ("hand", "deck", "grave", "removed", "monsters", "spells", "extra")


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


@pytest.fixture
def evaluator() -> StateEvaluator:
    return StateEvaluator()


def start(repository) -> GameState:
    """양쪽이 대칭인 시작 판. 전개와 자원 제공을 **따로** 얹을 수 있다."""
    deck = [LUSTER_DRAGON] * 20 + [POT_OF_GREED] * 5
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    state.draw(MINE, 5)
    state.draw(THEIRS, 5)
    state.turn.turn_number = 2
    state.turn.turn_player = MINE
    state.turn.set_phase(Phase.MAIN1)
    return state


def view_of(state: GameState, viewer: int = MINE) -> GameStateView:
    return GameStateView.from_state(state, viewer=viewer)


def develop(state: GameState, summons: int) -> GameState:
    """내 전개 — 패의 몬스터를 필드에 세운다."""
    for _ in range(summons):
        card = next(c for c in state.player(MINE).hand if c.card_id == LUSTER_DRAGON)
        state.move(card, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK)
    return state


def give(state: GameState, cards: int) -> GameState:
    """상대에게 자원 제공 — 덱에서 패로 가져간다 (증식의 G 가 주는 모양)."""
    if cards:
        state.draw(THEIRS, cards)
    return state


def delta_after(repository, *, summons: int, given: int) -> OpponentResourceDelta:
    state = start(repository)
    before = view_of(state)
    develop(state, summons)
    give(state, given)
    return OpponentResourceDelta.between(before, view_of(state))


# ======================================================================
# A. 무엇을 읽는가 — 장수뿐이다
# ======================================================================


@pytest.mark.real_card
def test_01_the_feature_reads_exactly_these_seven_zones(repository):
    """
    **일곱 자리를 읽고 그 이름이 고정이다.** 늘거나 줄면 범위가 바뀐 것이다.
    """
    assert tuple(name for name, _ in OPPONENT_RESOURCE_ZONES) == ZONE_NAMES
    resources = OpponentResources.of(view_of(start(repository)))
    assert tuple(name for name, _ in resources.counts()) == ZONE_NAMES
    assert {f.name for f in dataclasses.fields(OpponentResources)} == set(ZONE_NAMES)


@pytest.mark.real_card
def test_02_the_counts_are_the_observed_sizes(repository):
    """장수가 관측의 ``size`` 와 **같다.** 세는 방법을 새로 만들지 않았다."""
    state = start(repository)
    view = view_of(state)
    resources = OpponentResources.of(view)
    opponent = view.opponent

    assert resources.hand == opponent.hand.size == 5
    assert resources.deck == opponent.deck.size == 20
    assert resources.grave == opponent.grave.size == 0
    assert resources.removed == opponent.removed.size == 0
    assert resources.monsters == opponent.monster_zone.size == 0
    assert resources.spells == opponent.spell_zone.size == 0
    assert resources.extra == opponent.extra.size == 0
    assert resources.total == 25


@pytest.mark.real_card
def test_03_the_concealed_zones_give_a_size_but_not_a_content(repository):
    """
    **장수는 공개 사실이고 내용은 아니다.**

    상대의 패 · 덱 · 엑스트라 덱은 ``concealed`` 이면서 ``size`` 를 준다 —
    그래서 장수를 읽는 것이 hidden information 접근이 **아니다.**
    """
    view = view_of(start(repository))
    for zone in (view.opponent.hand, view.opponent.deck, view.opponent.extra):
        assert zone.concealed is True
        assert zone.size >= 0
        #: 목록이 비어 있다 — 정체가 오지 않는다.
        assert [card for card in zone.cards if card is not None] == []


def test_04_the_feature_never_reads_an_identity():
    """
    **정체를 읽는 접근자를 쓰지 않는다.** 더한 코드가 보는 것은 ``size`` 뿐이다.
    """
    import ast

    tree = ast.parse(source_of("agent/evaluation.py"))
    added = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and node.name in ("OpponentResources", "OpponentResourceDelta")
    ]
    assert len(added) == 2

    attributes = {
        node.attr for owner in added for node in ast.walk(owner)
        if isinstance(node, ast.Attribute)
    }
    assert "size" in attributes
    for forbidden in ("name", "card_id", "cards", "definition", "is_identified",
                      "face_up", "revealed", "atk", "state", "rng", "randomness"):
        assert forbidden not in attributes, forbidden


@pytest.mark.real_card
def test_05_the_counts_are_relative_to_the_viewer(repository):
    """
    **관점이 "상대" 를 정한다.** 자리를 인수로 받지 않고 관측이 이미 안다.
    """
    state = start(repository)
    #: 비대칭으로 만든다 — 상대만 3장 더 뽑는다.
    give(state, 3)

    mine = OpponentResources.of(view_of(state, MINE))
    theirs = OpponentResources.of(view_of(state, THEIRS))

    assert mine.hand == 8  # P0 가 보는 "상대" 는 P1
    assert theirs.hand == 5  # P1 가 보는 "상대" 는 P0
    assert mine != theirs


# ======================================================================
# B. current 와 delta 를 섞지 않는다
# ======================================================================


@pytest.mark.real_card
def test_06_current_resource_and_resource_delta_are_different_facts(repository):
    """
    **§4 의 핵심 구분.** "상대에게 3장을 줬다" 와 "상대 패가 지금 3장이다" 는
    다른 사실이다.

    같은 ``drawn_from_deck = 3`` 인데 **현재 장수가 다른** 두 판을 만들어
    보인다 — 둘을 한 숫자로 합치면 이 구분이 사라진다.
    """
    #: 판 1 — 패 5장에서 3장 더 받는다 → 지금 8장, 받은 것 3장
    one = start(repository)
    before_one = view_of(one)
    give(one, 3)
    delta_one = OpponentResourceDelta.between(before_one, view_of(one))

    #: 판 2 — 먼저 2장 버리고 나서 3장 받는다 → 지금 6장, 받은 것 3장
    two = start(repository)
    for card in list(two.player(THEIRS).hand)[:2]:
        two.move(card, Zone.GRAVE, to_player=THEIRS)
    before_two = view_of(two)
    give(two, 3)
    delta_two = OpponentResourceDelta.between(before_two, view_of(two))

    #: **받은 양은 같다.**
    assert delta_one.drawn_from_deck == delta_two.drawn_from_deck == 3
    #: **현재 장수는 다르다.**
    assert delta_one.after.hand == 8
    assert delta_two.after.hand == 6
    assert delta_one.after != delta_two.after


@pytest.mark.real_card
def test_07_the_delta_reports_every_zone_even_the_unchanged_ones(repository):
    """``changes`` 는 일곱 자리를 다 적는다 — **안 변했다는 것도 사실**이다."""
    delta = delta_after(repository, summons=0, given=3)
    assert tuple(name for name, _ in delta.changes) == ZONE_NAMES
    assert dict(delta.changes) == {
        "hand": 3,
        "deck": -3,
        "grave": 0,
        "removed": 0,
        "monsters": 0,
        "spells": 0,
        "extra": 0,
    }


# ======================================================================
# C. 안전한 추론 하나 — 나머지는 UNKNOWN
# ======================================================================


@pytest.mark.real_card
def test_08_a_draw_is_the_one_movement_counted_as_a_gain(repository):
    """
    **덱이 줄고 그만큼 패가 늘었다** → 드로우다. 다른 이동이 이 모양을 만들지
    않으므로 안전하게 "상대가 얻었다" 고 말할 수 있다.
    """
    delta = delta_after(repository, summons=0, given=3)
    assert delta.drawn_from_deck == 3
    assert delta.gave_resource is True
    assert delta.fully_explained is True
    assert delta.unexplained == ()


@pytest.mark.real_card
@pytest.mark.parametrize(
    "label, mutate, expected_changes",
    [
        (
            "디스카드 (패→묘지)",
            lambda state: [
                state.move(card, Zone.GRAVE, to_player=THEIRS)
                for card in list(state.player(THEIRS).hand)[:2]
            ],
            {"hand": -2, "grave": 2},
        ),
        (
            "특수소환 (패→필드)",
            lambda state: [
                state.move(
                    card, Zone.MZONE, to_player=THEIRS,
                    position=Position.FACEUP_ATTACK,
                )
                for card in list(state.player(THEIRS).hand)[:2]
            ],
            {"hand": -2, "monsters": 2},
        ),
        (
            "제외 (패→제외)",
            lambda state: state.move(
                list(state.player(THEIRS).hand)[0], Zone.REMOVED, to_player=THEIRS
            ),
            {"hand": -1, "removed": 1},
        ),
        (
            "덱에서 묘지로 (덱→묘지)",
            lambda state: [
                state.move(card, Zone.GRAVE, to_player=THEIRS)
                for card in list(state.player(THEIRS).deck)[:2]
            ],
            {"deck": -2, "grave": 2},
        ),
    ],
)
def test_09_other_movements_are_unknown_not_a_gain(
    repository, label, mutate, expected_changes
):
    """
    **§6: 이동했다고 무조건 +1 자원으로 세지 않는다.**

    필드→묘지 · 패→필드 · 덱→묘지 는 전략적 의미가 서로 다르고, **장수만으로는
    어느 쪽인지 정해지지 않는다.** 그래서 값으로 세지 않고 ``UNKNOWN`` 으로
    적는다 — 0 으로도 득으로도 접지 않는다.
    """
    state = start(repository)
    before = view_of(state)
    mutate(state)
    delta = OpponentResourceDelta.between(before, view_of(state))

    assert delta.drawn_from_deck == 0, label
    assert delta.gave_resource is False, label
    #: **설명하지 못했다고 말한다.** 적지 않으면 "다 설명했다" 가 거짓이 된다.
    assert delta.fully_explained is False, label
    assert {name: amount for name, amount in delta.changes if amount} == (
        expected_changes
    ), label

    #: 범주는 ``UNKNOWN`` 하나다 — 새 어휘를 만들지 않았다.
    assert {item.category for item in delta.unexplained} == {
        ExclusionCategory.UNKNOWN
    }, label
    assert len(delta.unexplained) == len(expected_changes), label


@pytest.mark.real_card
def test_09b_a_hand_gain_without_a_deck_loss_is_not_a_draw(repository):
    """
    **덱이 줄지 않았는데 패가 늘었다** → 드로우가 아니다.

    필드의 몬스터가 패로 돌아오면 ``패+1 · 몬스터-1`` 이고 덱은 그대로다. 그것은
    상대가 **새 자원을 얻은 것이 아니라** 있던 것을 옮긴 것이다.

    .. note::
       **이 경우가 테스트에 없었다** (3-F-2 의 고의 위반 1 이 찾아냄).

       ``drawn = max(hand_gain, 0)`` 으로 바꿔도 26개가 전부 통과했다 — 패가
       늘면서 덱이 **안 줄어드는** 판을 하나도 만들지 않았기 때문이다. 그래서
       "덱이 줄었는가" 라는 조건이 실제로 무언가를 막는지 재지 못했다.
    """
    state = start(repository)
    #: 상대 필드에 몬스터를 하나 세워 둔다 (이 자체는 비교 전이다).
    state.move(
        list(state.player(THEIRS).hand)[0],
        Zone.MZONE,
        to_player=THEIRS,
        position=Position.FACEUP_ATTACK,
    )
    before = view_of(state)
    deck_before = OpponentResources.of(before).deck

    #: 필드 → 패. 덱은 건드리지 않는다.
    monster = next(
        card for card in state.player(THEIRS).monster_zone if card is not None
    )
    state.move(monster, Zone.HAND, to_player=THEIRS)
    after = view_of(state)

    delta = OpponentResourceDelta.between(before, after)
    assert dict(delta.changes)["hand"] == 1
    assert dict(delta.changes)["monsters"] == -1
    assert dict(delta.changes)["deck"] == 0
    assert delta.after.deck == deck_before  # 덱이 줄지 않았다

    #: **드로우로 세지 않는다.** 세면 "상대가 자원을 얻었다" 는 거짓이 된다.
    assert delta.drawn_from_deck == 0
    assert delta.gave_resource is False
    #: 그리고 모른다고 적는다 — 두 자리가 바뀐 까닭을 장수로는 정할 수 없다.
    assert delta.fully_explained is False
    assert len(delta.unexplained) == 2
    assert {item.category for item in delta.unexplained} == {
        ExclusionCategory.UNKNOWN
    }


@pytest.mark.real_card
def test_10_a_mixed_change_under_reports_rather_than_guessing(repository):
    """
    **섞인 변화에서는 적게 세고 남은 것을 적는다.**

    상대가 3장 뽑고 1장 버리면 장수는 ``패+2 · 덱-3 · 묘지+1`` 이다. 그런데
    그 장수는 "3장 뽑고 1장 버렸다" 와 "2장 뽑고 1장을 덱에서 묘지로 보냈다" 를
    **구분하지 못한다.**

    그래서 ``drawn_from_deck = 2`` 로 **적게** 세고 남은 변화를 ``UNKNOWN`` 에
    적는다. 3 이라고 적으면 그것은 추측이다.
    """
    state = start(repository)
    before = view_of(state)
    give(state, 3)
    state.move(list(state.player(THEIRS).hand)[0], Zone.GRAVE, to_player=THEIRS)
    delta = OpponentResourceDelta.between(before, view_of(state))

    assert dict(delta.changes)["hand"] == 2
    assert dict(delta.changes)["deck"] == -3
    assert dict(delta.changes)["grave"] == 1

    #: **실제로는 3장을 뽑았지만 2 로 센다** — 장수만으로는 확정할 수 없다.
    assert delta.drawn_from_deck == 2
    assert delta.gave_resource is True
    assert delta.fully_explained is False
    assert len(delta.unexplained) == 2  # 남은 deck -1 · grave +1


@pytest.mark.real_card
def test_11_no_change_is_fully_explained(repository):
    """
    **변화가 없으면 설명할 것도 없다.** 그리고 내 쪽만 변해도 상대 자원은
    그대로다 — 자리를 바꿔 세지 않는다.
    """
    quiet = delta_after(repository, summons=0, given=0)
    assert quiet.drawn_from_deck == 0
    assert quiet.gave_resource is False
    assert quiet.fully_explained is True
    assert all(amount == 0 for _, amount in quiet.changes)

    mine_only = delta_after(repository, summons=3, given=0)
    assert mine_only.fully_explained is True
    assert all(amount == 0 for _, amount in mine_only.changes)


# ======================================================================
# D. 증G benchmark — 차이가 사라지지 않는다
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize(
    "label, summons, given, expected_drawn",
    [
        ("A 아무것도 안 함", 0, 0, 0),
        ("B 전개0 · 자원 3", 0, 3, 3),
        ("C 전개3 · 자원 3", 3, 3, 3),
        ("D 전개3 · 자원 0", 3, 0, 0),
    ],
)
def test_12_the_four_benchmark_states_are_observable(
    repository, label, summons, given, expected_drawn
):
    """**§5 의 네 상태.** 넷 모두 받은 자원량이 feature 로 읽힌다."""
    delta = delta_after(repository, summons=summons, given=given)
    assert delta.drawn_from_deck == expected_drawn, label
    assert delta.gave_resource is (expected_drawn > 0), label
    assert delta.fully_explained is True, label


@pytest.mark.real_card
def test_13_c_and_d_differ_in_the_feature_though_my_board_is_identical(
    repository, evaluator
):
    """
    **이 Phase 의 핵심 결과.**

    C(전개3 + 자원3) 와 D(전개3 + 자원0) 는 **내 전개량이 같다.** 3-F-1 에서는
    그 둘의 차이를 표현할 feature 가 없었다. 이제 ``drawn_from_deck`` 이
    **3 과 0** 으로 갈린다.

    점수는 여전히 C 가 높다 — 그것을 뒤집지 **않는다.** 이 Phase 는 "차이를
    표현할 수 있는가" 를 묻고, 가중치는 다음 Phase 의 몫이다 (§5).
    """
    c_state, d_state = start(repository), start(repository)
    c_before, d_before = view_of(c_state), view_of(d_state)
    give(develop(c_state, 3), 3)
    give(develop(d_state, 3), 0)
    c_after, d_after = view_of(c_state), view_of(d_state)

    c_delta = OpponentResourceDelta.between(c_before, c_after)
    d_delta = OpponentResourceDelta.between(d_before, d_after)
    c_value = evaluator.evaluate(c_after)
    d_value = evaluator.evaluate(d_after)

    #: 내 전개량은 **같다** — 기존 평가로는 구분할 단서가 여기까지다.
    assert dict(c_value.terms)["monsters"] == dict(d_value.terms)["monsters"] == 1500
    assert dict(c_value.terms)["atk"] == dict(d_value.terms)["atk"]

    #: 새 feature 가 **갈라낸다.**
    assert (c_delta.drawn_from_deck, d_delta.drawn_from_deck) == (3, 0)
    assert c_delta.gave_resource is True
    assert d_delta.gave_resource is False
    assert c_delta != d_delta

    #: 점수는 아직 C 가 높다 — 3-F-1 이 측정한 그대로이고 **고치지 않았다.**
    assert c_value.heuristic > d_value.heuristic
    assert c_value.heuristic - d_value.heuristic == 3 * DECK_CARD_IN_LP


@pytest.mark.real_card
def test_14_a_and_b_differ_in_the_feature_with_no_board_change_at_all(
    repository, evaluator
):
    """
    **A vs B** — 내 판을 한 칸도 바꾸지 않고 상대에게만 3장을 준 경우.
    3-F-1 에서는 점수만 +900 올라가고 "줬다" 는 사실이 **어디에도** 없었다.
    """
    a_state, b_state = start(repository), start(repository)
    a_before, b_before = view_of(a_state), view_of(b_state)
    give(b_state, 3)
    a_after, b_after = view_of(a_state), view_of(b_state)

    a_delta = OpponentResourceDelta.between(a_before, a_after)
    b_delta = OpponentResourceDelta.between(b_before, b_after)

    assert (a_delta.drawn_from_deck, b_delta.drawn_from_deck) == (0, 3)
    #: 내 쪽 항은 하나도 다르지 않다.
    a_terms = dict(evaluator.evaluate(a_after).terms)
    b_terms = dict(evaluator.evaluate(b_after).terms)
    for name in ("lp", "atk", "monsters", "spells", "hand"):
        assert a_terms[name] == b_terms[name], name
    #: 그런데 점수는 올라간다 — 3-F-1 의 측정이 그대로 재현된다.
    assert b_terms["deck"] - a_terms["deck"] == 3 * DECK_CARD_IN_LP


# ======================================================================
# E. 순수성과 경계
# ======================================================================


@pytest.mark.real_card
def test_15_the_feature_is_pure_and_deterministic(repository):
    """**판을 읽기만 한다.** 30회 계산 뒤에도 판과 난수원이 그대로다."""
    state = start(repository)
    before = view_of(state)
    give(state, 3)
    after = view_of(state)

    hash_before, rng_before = state.state_hash(), state.rng.getstate()
    first = OpponentResourceDelta.between(before, after)
    for _ in range(30):
        assert OpponentResourceDelta.between(before, after) == first
        assert OpponentResources.of(after) == first.after

    assert state.state_hash() == hash_before
    assert state.rng.getstate() == rng_before

    #: clone 의 결과가 같다.
    cloned = view_of(state.clone())
    assert OpponentResources.of(cloned) == OpponentResources.of(after)


@pytest.mark.real_card
def test_16_the_guards_reject_the_two_wrong_inputs(repository):
    """
    **관측이 아니면 거부하고, 관점이 다르면 거부한다.**

    관점이 다른 두 관측을 비교하면 "상대" 가 서로 다른 사람이 되므로 delta 가
    뜻을 잃는다.
    """
    state = start(repository)
    with pytest.raises(EvaluationError, match="GameStateView"):
        OpponentResources.of(state)
    with pytest.raises(EvaluationError, match="GameStateView"):
        OpponentResourceDelta.between(view_of(state), state)
    with pytest.raises(EvaluationError, match="관점"):
        OpponentResourceDelta.between(view_of(state, MINE), view_of(state, THEIRS))


# ======================================================================
# F. 점수와 Search 를 건드리지 않았다
# ======================================================================


def test_17_no_weight_was_attached_to_the_opponent_resource():
    """
    **§9: 가중치를 붙이지 않았다.** 더한 두 자료형 어디에도 LP 환산이 없다.

    ``opponent_draws * -300`` 같은 값을 근거 없이 확정하지 않는다 — 이 Phase 는
    feature 를 만들고, 값을 매기는 일은 다음 Phase 다.
    """
    import ast

    tree = ast.parse(source_of("agent/evaluation.py"))
    added = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and node.name in ("OpponentResources", "OpponentResourceDelta")
    ]
    names = {
        node.id for owner in added for node in ast.walk(owner)
        if isinstance(node, ast.Name)
    }
    for weight in ("ATK_IN_LP", "MONSTER_IN_LP", "SPELL_TRAP_IN_LP",
                   "DECK_CARD_IN_LP", "HAND_CARD_IN_LP"):
        assert weight not in names, weight

    #: 점수 자료형을 만들지도 않는다.
    assert "StateValue" not in names


def test_18_the_scoring_types_kept_their_shape():
    """
    **``StateValue`` 와 ``SearchCandidate`` 가 네 칸 그대로다.**

    Phase 3-E-42 가 그 넷을 계약으로 고정했다 ("후보는 관측을 들고 있지
    않다"). 상대 자원을 그 안에 넣으면 그 계약을 뒤집게 되므로 **넣지
    않았다** — 별도 자료형으로 두었다.
    """
    assert len(dataclasses.fields(StateValue)) == 4
    assert len(dataclasses.fields(SearchCandidate)) == 4
    assert {f.name for f in dataclasses.fields(SearchCandidate)} == {
        "action",
        "status",
        "value",
        "reason",
    }


def test_19_search_was_not_touched_so_its_ranking_cannot_move():
    """
    **§10: Search 를 한 줄도 고치지 않았다.**

    ``agent/search.py`` 가 상대 자원을 **모른다** — 그래서 ranking ·
    tie-break · ``SimulationStatus`` · UNKNOWN/REFUSED 가 바뀔 자리가 없다.
    연결은 가중치가 정해진 뒤의 일이다.
    """
    search = source_of("agent/search.py")
    for absent in ("OpponentResource", "opponent_resource", "drawn_from_deck"):
        assert absent not in search, absent

    #: 비교는 여전히 ``StateValue.ordering_key`` 하나로만 한다.
    assert "terminal, heuristic = self.value.ordering_key()" in search


def test_20_the_evaluator_protocol_is_unchanged():
    """
    **평가자 Protocol 을 바꾸지 않았다.** ``evaluate(view)`` 그대로이므로
    기존 평가자와 Search 의 런타임 검사가 그대로 맞는다.

    delta 는 관측 **둘**을 받으므로 이 Protocol 에 들어갈 수 없고, 그래서
    별도 함수로 두었다 — Protocol 을 넓히면 Search 까지 닿는다 (3-F-1 §7).
    """
    import inspect

    from agent.evaluation import Evaluator

    assert list(inspect.signature(Evaluator.evaluate).parameters) == ["self", "view"]
    assert list(
        inspect.signature(OpponentResourceDelta.between).parameters
    ) == ["before_view", "after_view"]

    #: 인수 이름이 **관측임을 말한다.** 3-E-42 가 ``SimulationResult.viewer`` 에
    #: production 독자가 없음을 계약으로 고정해 두었고, 그 테스트는
    #: ``view`` 가 든 이름을 관측의 것으로 인정한다. 이름을 그렇게 두면 그
    #: 계약을 **고치지 않고** 지나간다 (3-F-2 의 회귀에서 실제로 걸렸다).
    assert all(
        "view" in name
        for name in inspect.signature(OpponentResourceDelta.between).parameters
    )
