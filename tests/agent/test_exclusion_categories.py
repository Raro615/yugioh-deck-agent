"""
Phase 3-E-8 — ``partial`` 의 진리표와 범주 보존.

이 파일이 고정하는 것은 단 하나다.

    ``partial = any(범주 is UNKNOWN)``

그리고 그것이 **왜** 맞는가.

====================  ===============================================  =======
범주                   왜 그렇게 두는가                                  partial
====================  ===============================================  =======
``DESIGNED_OUT``      값이 보이는데 항으로 두지 않기로 했다 —            아니다
                      **질문을 하지 않았다.** 평가가 못 푼 것이 아니다
``WITHHELD``          관측 경계 밖이다 — **어떤 평가자도 이보다 잘할      아니다
                      수 없다.** 규칙대로 처리한 결과다
``UNKNOWN``           다 보이는데 숫자가 나오지 않는다 —                 **그렇다**
                      **여기서만** 평가가 답을 못 냈다
====================  ===============================================  =======

여덟 가지 조합을 실제 엔진 상태로 전부 만들어 확인한다. 조합을 글로만 적고
넘어가면 "그랬을 것이다" 가 되므로, 한 줄도 추측하지 않는다.
"""

import pytest

from agent.evaluation import (
    HAND_CARD_IN_LP,
    MONSTER_IN_LP,
    Exclusion,
    ExclusionCategory,
    StateEvaluator,
    StateValue,
    Terminal,
)
from engine.game_state_view import GameStateView
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

MINE, THEIRS = 0, 1
EV = StateEvaluator()

LUSTER_DRAGON = 11091375  # ATK 1900 / DEF 1600
KING_OF_THE_SKULL_SERVANTS = 36021814  # ATK ?
FACEUP = Position.FACEUP_ATTACK
SET = Position.FACEDOWN_DEFENSE

DESIGNED_OUT = ExclusionCategory.DESIGNED_OUT
UNKNOWN = ExclusionCategory.UNKNOWN
WITHHELD = ExclusionCategory.WITHHELD


def board(
    repository,
    *,
    places: tuple[tuple[int, Zone, Position, int], ...] = (),
    their_hand: int = 0,
    viewer: int = MINE,
) -> GameStateView:
    """실제 엔진으로 만든 판 하나의 관측. 가짜 상태를 만들지 않는다."""
    game = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20),
        turn_player=MINE,
        seed=1,
    )
    for seat, zone, position, card_id in places:
        card = game.create_instance(card_id, owner=seat, zone=Zone.HAND)
        game.move(card, zone, to_player=seat, position=position)
    for _ in range(their_hand):
        game.create_instance(LUSTER_DRAGON, owner=THEIRS, zone=Zone.HAND)
    game.turn.turn_number = 2
    game.turn.set_phase(Phase.MAIN1)
    return GameStateView.from_state(game, viewer=viewer)


#: 각 조합을 만드는 재료. **한 재료가 한 범주를 만든다.**
#:
#: ``DESIGNED_OUT``  내 뒷면 통상 몬스터 — 값을 알지만 뒷면은 공격하지 않는다
#: ``UNKNOWN``       내 앞면 공격력 ``?`` 몬스터 — 다 보이는데 숫자가 없다
#: ``WITHHELD``      상대 패 — 장수는 보이고 내용은 보이지 않는다
INGREDIENT = {
    DESIGNED_OUT: ((MINE, Zone.MZONE, SET, LUSTER_DRAGON),),
    UNKNOWN: ((MINE, Zone.MZONE, FACEUP, KING_OF_THE_SKULL_SERVANTS),),
}

#: §13 의 진리표. 빈 조합까지 **여덟 가지 전부**.
TRUTH_TABLE: tuple[tuple[frozenset, bool], ...] = (
    (frozenset(), False),
    (frozenset({DESIGNED_OUT}), False),
    (frozenset({UNKNOWN}), True),
    (frozenset({WITHHELD}), False),
    (frozenset({DESIGNED_OUT, UNKNOWN}), True),
    (frozenset({DESIGNED_OUT, WITHHELD}), False),
    (frozenset({UNKNOWN, WITHHELD}), True),
    (frozenset({DESIGNED_OUT, UNKNOWN, WITHHELD}), True),
)


def make(repository, wanted: frozenset) -> StateValue:
    places: tuple = ()
    for category in (DESIGNED_OUT, UNKNOWN):
        if category in wanted:
            places += INGREDIENT[category]
    view = board(
        repository, places=places, their_hand=3 if WITHHELD in wanted else 0
    )
    return EV.evaluate(view)


# ======================================================================
# §13-1 ~ §13-7 — 진리표
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize("wanted,expected_partial", TRUTH_TABLE)
def test_01_the_partial_truth_table(repository, wanted, expected_partial):
    """
    **``partial`` 은 ``UNKNOWN`` 이 있을 때만 참이다.**

    조합을 실제로 만들어 확인한다. 각 조합에서 **원한 범주만** 나와야 하고
    (재료가 섞이면 진리표가 아무것도 증명하지 못한다), ``partial`` 은 표와
    같아야 한다.
    """
    result = make(repository, wanted)
    assert {item.category for item in result.excluded} == set(wanted), result.excluded
    assert result.partial is expected_partial, result.excluded
    # 같은 질문을 두 번 묻지 않는다 — 깃발과 ``UNKNOWN`` 의 존재가 같다.
    assert result.partial is bool(result.of_category(UNKNOWN))


@pytest.mark.real_card
def test_02_designed_out_alone_never_raises_the_flag(repository):
    """
    **§13-1 · STRUCTURAL-130 의 핵심.**

    묘지 · 제외 존 · 필드 존 · 펜듈럼 존 · 엑스트라 덱 · 내 뒷면 몬스터의
    공격력 — 전부 ``DESIGNED_OUT`` 이고, 전부 깃발을 세우지 않는다.

    예전에는 이 중 **하나만 있어도** ``partial`` 이 참이었다. 실제 듀얼에서
    묘지는 거의 언제나 비어 있지 않으므로 깃발이 늘 참이었고 (실측 99.6%),
    그래서 깃발은 "평가가 불완전하다" 가 아니라 "묘지에 카드가 있다" 를
    뜻했다.
    """
    cases = (
        ((MINE, Zone.GRAVE, FACEUP, LUSTER_DRAGON),),
        ((MINE, Zone.REMOVED, FACEUP, LUSTER_DRAGON),),
        ((MINE, Zone.FZONE, FACEUP, LUSTER_DRAGON),),
        ((MINE, Zone.PZONE, FACEUP, LUSTER_DRAGON),),
        ((MINE, Zone.MZONE, SET, LUSTER_DRAGON),),
    )
    for places in cases:
        result = EV.evaluate(board(repository, places=places))
        assert result.excluded, places
        assert {i.category for i in result.excluded} == {DESIGNED_OUT}, result.excluded
        assert not result.partial, result.excluded


# ======================================================================
# §13-8 — 점수는 바뀌지 않는다
# ======================================================================


@pytest.mark.real_card
def test_03_the_score_did_not_move(repository):
    """
    **§5 — 이번 변경은 메타데이터의 의미만 가른다.**

    범주를 붙이면서 점수가 움직였다면 그것은 가중치 변경이고, 이번 Phase 가
    금지한 일이다. 대표 판의 점수를 **숫자로** 못 박는다.
    """
    expected = (
        ((), 0, 0),
        (((MINE, Zone.MZONE, FACEUP, LUSTER_DRAGON),), 2400, 0),
        (((MINE, Zone.MZONE, SET, LUSTER_DRAGON),), 500, 0),
        (((THEIRS, Zone.MZONE, FACEUP, LUSTER_DRAGON),), -2400, 0),
        (((THEIRS, Zone.MZONE, SET, LUSTER_DRAGON),), -500, 0),
        (((MINE, Zone.MZONE, FACEUP, KING_OF_THE_SKULL_SERVANTS),), 500, 0),
        (((MINE, Zone.EMZONE, FACEUP, LUSTER_DRAGON),), 2400, 0),
        (((MINE, Zone.REMOVED, FACEUP, LUSTER_DRAGON),), 0, 0),
        ((), 0, 3),  # 상대 패는 세지 않으므로 내 점수는 움직이지 않는다
    )
    for places, heuristic, their_hand in expected:
        result = EV.evaluate(
            board(repository, places=places, their_hand=their_hand)
        )
        assert result.terminal is Terminal.ONGOING
        assert result.heuristic == heuristic, (places, their_hand, result.terms)

    # 같은 판을 상대 자리에서 보면 ``hand`` 가 ``+600`` 이다 — ``hand`` 만
    # 차분이 아니라서 두 자리의 합이 0 이 되지 않는다 (STRUCTURAL-129).
    # 이번 Phase 는 손대지 않았고, 범주 분리가 이 비대칭을 건드리지 않았음을
    # 확인만 한다.
    assert dict(EV.evaluate(board(repository, their_hand=3)).terms)["hand"] == 0
    theirs = EV.evaluate(board(repository, their_hand=3, viewer=THEIRS))
    assert dict(theirs.terms)["hand"] == 3 * HAND_CARD_IN_LP == 600


@pytest.mark.real_card
def test_04_the_extra_monster_zone_fix_still_holds(repository):
    """
    **§9 Case D — STRUCTURAL-132 가 그대로 유지된다.**

    이번 Phase 는 EMZ 로직을 다시 설계하지 않는다. 같은 몬스터가 메인 몬스터
    존에 있을 때와 엑스트라 몬스터 존에 있을 때 점수가 같아야 한다.
    """
    main = EV.evaluate(
        board(repository, places=((MINE, Zone.MZONE, FACEUP, LUSTER_DRAGON),))
    )
    extra = EV.evaluate(
        board(repository, places=((MINE, Zone.EMZONE, FACEUP, LUSTER_DRAGON),))
    )
    assert main.heuristic == extra.heuristic == 2400
    assert dict(extra.terms)["atk"] == 1900
    assert dict(extra.terms)["monsters"] == MONSTER_IN_LP
    assert extra.excluded == ()


# ======================================================================
# §13-9 — 가려진 정보는 그대로 가려져 있다
# ======================================================================


@pytest.mark.real_card
def test_05_withheld_never_leaks_what_it_withholds(repository):
    """
    **§8 — ``WITHHELD`` 를 ``card_id`` 로 해결하지 않는다.**

    상대의 뒷면 카드가 무엇이든 점수와 범주가 같아야 한다. 하나라도 달라지면
    정체가 점수로 새어 나온 것이다.
    """
    scores = set()
    for card_id in (LUSTER_DRAGON, KING_OF_THE_SKULL_SERVANTS):
        result = EV.evaluate(
            board(repository, places=((THEIRS, Zone.MZONE, SET, card_id),))
        )
        assert {i.category for i in result.excluded} == {WITHHELD}, result.excluded
        assert not result.partial
        scores.add(result.heuristic)
    assert len(scores) == 1, scores

    # 상대 패도 같다 — 장수만 쓰고 내용은 쓰지 않는다.
    notes = EV.evaluate(board(repository, their_hand=2)).notes
    assert any("상대 패 2장" in note for note in notes), notes


# ======================================================================
# §13-10 — 범주가 보존된다
# ======================================================================


@pytest.mark.real_card
def test_06_the_category_survives_and_the_wording_agrees(repository):
    """
    **범주와 문구가 같은 것을 말한다.**

    사람은 문구를 읽고 기계는 범주를 읽는다. 둘이 어긋나면 어느 한쪽이
    거짓이고, 어긋난 것을 고치지 못한 것이 STRUCTURAL-115 였다.
    """
    result = make(repository, frozenset({DESIGNED_OUT, UNKNOWN, WITHHELD}))
    by_category = {
        item.category: item.note for item in result.excluded
    }
    assert set(by_category) == {DESIGNED_OUT, UNKNOWN, WITHHELD}
    assert "세지 않았다" in by_category[DESIGNED_OUT]
    assert "모른다" in by_category[UNKNOWN]
    assert "모른다" in by_category[WITHHELD]
    # 범주가 다른데 문구만 보면 둘을 가를 수 없다 — 그래서 범주가 필요했다.
    assert by_category[UNKNOWN] != by_category[WITHHELD]

    for item in result.excluded:
        assert isinstance(item, Exclusion)
        assert isinstance(item.category, ExclusionCategory)
        assert item.note and isinstance(item.note, str)


@pytest.mark.real_card
def test_07_an_ended_duel_has_no_exclusions_at_all(repository):
    """
    끝난 판은 휴리스틱을 재지 않으므로 **빠진 것도 없다.**

    등급이 모든 것을 말하는 자리에서 "빠진 것이 있다" 고 적으면 거짓이다.
    """
    game = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20),
        turn_player=MINE,
        seed=1,
    )
    card = game.create_instance(LUSTER_DRAGON, owner=MINE, zone=Zone.HAND)
    game.move(card, Zone.GRAVE, to_player=MINE)
    game.player(THEIRS).change_life(-8000)
    game.set_result(winner=MINE, reason="테스트")

    result = EV.evaluate(GameStateView.from_state(game, viewer=MINE))
    assert result.terminal is Terminal.WIN
    assert result.excluded == ()
    assert not result.partial
