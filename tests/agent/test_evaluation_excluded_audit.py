"""
Phase 3-E-7 / 3-E-8 — STRUCTURAL-130: ``partial`` / ``excluded`` 의 의미.

이 파일이 고정하는 것은 **excluded 가 왜 excluded 인가**다.

3-E-7 은 그것을 **문구로** 갈랐다 — ``excluded`` 가 문자열 목록이었으므로 그
수밖에 없었다. 3-E-8 에서 :class:`ExclusionCategory` 가 생겼으므로 이제
**구조로** 가른다. 아래 주장들은 그대로이고, 판정이 문구에서 범주로 옮겨
갔으므로 **더 강해졌다.**

==================  =======================================================
``DESIGNED_OUT``    값이 보이는데 **항으로 두지 않기로 했다.** 묘지 · 제외
                    존 · 필드 존 · 펜듈럼 존 · 엑스트라 덱 · **내 뒷면
                    몬스터의 공격력**. 질문을 하지 않은 것이다
``UNKNOWN``         **다 보이는데 숫자가 나오지 않는다.** 공격력이 ``?`` 인
                    카드. 이것만이 평가의 미해결이다
``WITHHELD``        **합법적으로 볼 수 없다.** 상대 뒷면의 정체 · 상대 패의
                    내용. 규칙대로 처리한 결과다
IMPLEMENTATION      관측에 있고, 평가 목적에 들어가고, 그런데 평가가
GAP                 **읽지 않는다.** ``excluded`` 에 아무 기록도 남지
                    않으므로 네 범주 중 **유일한 결함**이다
==================  =======================================================

3-E-7 Audit 이 찾은 IMPLEMENTATION GAP 은 **STRUCTURAL-132** 하나다 —
엑스트라 몬스터 존이 평가에서 통째로 빠져 있었다 (``test_09`` ~ ``test_11``).

**3-E-7 의 분류와 달라진 자리 하나.** 3-E-7 은 "내 뒷면 몬스터의 공격력" 을
``WITHHELD`` 로 적었다. 문구가 "세지 않았다" 였기 때문이다. 그 분류가
틀렸다 — 내 카드는 **아무것도 가려져 있지 않다.** 값을 알면서 항으로 두지
않기로 한 것이므로 ``DESIGNED_OUT`` 이다. ``WITHHELD`` 는 관측 경계 밖인
것(상대 뒷면 · 상대 패)에만 쓴다.
"""

import ast
import pathlib
import random
import re

import pytest

from agent.evaluation import (
    GRAVE_IS_COUNTED,
    MONSTER_IN_LP,
    Exclusion,
    ExclusionCategory,
    StateEvaluator,
    StateValue,
    _field_monster_zones,
    _UNSCORED_ZONES,
)
from agent.simulation import Simulator
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1
EV = StateEvaluator()

LUSTER_DRAGON = 11091375  # ATK 1900 / DEF 1600
BATTLE_OX = 5053103  # ATK 1700 / DEF 1000
KING_OF_THE_SKULL_SERVANTS = 36021814  # ATK ?
POT_OF_GREED = 55144522

#: 문구에 반드시 들어 있어야 하는 말. **문구와 범주가 어긋나면 둘 중 하나가
#: 거짓이다** — 사람은 문구를 읽고 기계는 범주를 읽으므로, 둘이 같은 것을
#: 말해야 한다.
WORDING_OF: dict[ExclusionCategory, tuple[str, ...]] = {
    ExclusionCategory.DESIGNED_OUT: ("값을 매기지 않았다", "세지 않았다"),
    ExclusionCategory.UNKNOWN: ("모른다",),
    ExclusionCategory.WITHHELD: ("모른다",),
}


def categories(value) -> set[ExclusionCategory]:
    return {item.category for item in value.excluded}


#: 한 장을 어디에 어떻게 둘지. ``(seat, zone, position, card_id)``.
Placement = tuple[int, Zone, Position, int]

FACEUP = Position.FACEUP_ATTACK
SET = Position.FACEDOWN_DEFENSE


def state(repository, *placements: Placement) -> GameState:
    """원하는 자리에 카드를 둔 판 하나. 전부 실제 엔진으로 옮긴다."""
    game = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20),
        turn_player=MINE,
        seed=1,
    )
    for seat, zone, position, card_id in placements:
        card = game.create_instance(card_id, owner=seat, zone=Zone.HAND)
        game.move(card, zone, to_player=seat, position=position)
    game.turn.turn_number = 2
    game.turn.set_phase(Phase.MAIN1)
    return game


def value(game: GameState, viewer: int = MINE):
    return EV.evaluate(GameStateView.from_state(game, viewer=viewer))


def source_of(path: str) -> str:
    return (ROOT / path).read_text()


# ======================================================================
# §1 · §7 — partial 과 excluded 의 정의를 코드에서 읽는다
# ======================================================================


def test_01_partial_is_no_longer_one_bit_over_the_whole_excluded_list():
    """
    **STRUCTURAL-130 이 풀린 자리다** (Phase 3-E-8).

    3-E-7 에서 이 시험은 그 반대를 적었다 — ``partial`` 이
    ``return bool(self.excluded)`` 한 줄이고, 그래서 서로 다른 세 사실이
    **같은 한 비트**로 묶인다고.

    **왜 기존 전제가 틀렸는가.** 틀린 것은 시험이 아니라 코드였다. "빠진 것이
    있는가" 와 "평가가 못 푼 것이 있는가" 는 다른 질문인데 한 이름을 쓰고
    있었다. 묘지에 카드가 한 장 있으면 깃발이 참이 되었으므로, 깃발은 사실상
    "이 판에 묘지가 있는가" 를 뜻했다 (실측 99.6%).

    지금은 ``UNKNOWN`` 만 본다. 그리고 ``excluded`` 는 범주를 든다.
    """
    source = source_of("agent/evaluation.py")
    tree = ast.parse(source)
    (partial,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "partial"
    ]
    body = [n for n in partial.body if not isinstance(n, ast.Expr)]
    assert len(body) == 1
    returned = ast.unparse(body[0])
    assert returned != "return bool(self.excluded)", "다시 한 비트로 돌아갔다"
    assert "ExclusionCategory.UNKNOWN" in returned, returned

    # 그리고 그 목록은 **범주를 담는다.**
    assert StateValue.__annotations__["excluded"] == "tuple[Exclusion, ...]"
    assert {category.name for category in ExclusionCategory} == {
        "DESIGNED_OUT",
        "UNKNOWN",
        "WITHHELD",
    }


def test_02_each_exclusion_carries_the_category_that_matches_its_wording(
    repository,
):
    """
    **§3 — 하나의 제외 사유가 하나의 범주를 든다.**

    3-E-7 은 문구로 갈랐다. 지금은 **범주 필드**로 가르고, 문구가 그 범주와
    같은 말을 하는지도 함께 본다 — 사람은 문구를 읽고 기계는 범주를 읽으므로
    둘이 어긋나면 어느 한쪽이 거짓이다.
    """
    cases = {
        # 내 뒷면 몬스터 — 다 보이는데 항으로 두지 않기로 했다
        ExclusionCategory.DESIGNED_OUT: state(
            repository, (MINE, Zone.MZONE, SET, LUSTER_DRAGON)
        ),
        # 내 앞면 ``?`` 몬스터 — 다 보이는데 숫자가 없다
        ExclusionCategory.UNKNOWN: state(
            repository, (MINE, Zone.MZONE, FACEUP, KING_OF_THE_SKULL_SERVANTS)
        ),
        # 상대 뒷면 몬스터 — 관측 경계 밖이다
        ExclusionCategory.WITHHELD: state(
            repository, (THEIRS, Zone.MZONE, SET, LUSTER_DRAGON)
        ),
    }
    for expected, game in cases.items():
        result = value(game)
        assert result.excluded, expected
        assert categories(result) == {expected}, result.excluded
        for item in result.excluded:
            assert any(
                word in item.note for word in WORDING_OF[item.category]
            ), (item.category, item.note)


def test_03_real_duels_produce_only_designed_out_and_withheld(repository):
    """
    **§2 — 실제 대국에서 나오는 제외 사유를 전부 모아 범주를 센다.**

    사례를 만들지 않고 실제 듀얼에서 모은다. 통상 몬스터만 든 덱에서는
    ``UNKNOWN`` 이 **하나도 나오지 않는다** — 공격력이 ``?`` 인 카드가 없기
    때문이다. 그래서 ``partial`` 도 0 이다.

    **빠진 것이 줄어서가 아니다.** ``DESIGNED_OUT`` 과 ``WITHHELD`` 는 여전히
    평가 횟수보다 많이 쌓인다 — 기록은 하나도 사라지지 않았고 범주만 갈렸다.
    """
    deck = [LUSTER_DRAGON] * 10 + [BATTLE_OX] * 6 + [POT_OF_GREED] * 4
    counts = {category: 0 for category in ExclusionCategory}
    evaluated = partial = 0
    for seed in (1, 2, 3):
        rng = random.Random(seed)
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
        for _ in range(200):
            if duel.is_over:
                break
            if duel.advance() is not None:
                continue
            legal = duel.legal_actions()
            if not legal.allowed:
                break
            simulator = Simulator(duel)
            for action in legal.allowed:
                result = simulator.simulate(action, viewer=legal.seat)
                if result.future is None:
                    continue
                evaluated += 1
                evaluation = EV.evaluate(result.future)
                partial += evaluation.partial
                for item in evaluation.excluded:
                    counts[item.category] += 1
            duel.apply(rng.choice(legal.allowed))

    assert evaluated > 500, evaluated
    assert counts[ExclusionCategory.DESIGNED_OUT] > 0, counts
    assert counts[ExclusionCategory.WITHHELD] > 0, counts
    assert counts[ExclusionCategory.UNKNOWN] == 0, counts
    assert partial == 0, (partial, evaluated)


# ======================================================================
# §3 CATEGORY A — 설계상 세지 않는 자리
# ======================================================================


def test_04_an_unscored_zone_is_observable_and_says_so(repository):
    """
    **CATEGORY A — 관측되지만 설계상 세지 않는다.**

    다섯 자리 모두 **장수가 공개된 사실**이다. 그래서 문구는 "모른다" 가
    아니라 "값을 매기지 않았다" 여야 한다 — 둘을 섞으면 Phase 3-E-6 에서
    없앤 거짓이 되살아난다.
    """
    assert GRAVE_IS_COUNTED is False
    assert [label for label, _ in _UNSCORED_ZONES] == [
        "제외 존",
        "필드 존",
        "펜듈럼 존",
        "엑스트라 덱",
    ]
    # 묘지는 ``GRAVE_IS_COUNTED`` 가 따로 쥐고 있으므로 목록 밖이다.
    placements: tuple[tuple[str, Zone | None], ...] = (
        ("묘지", Zone.GRAVE),
        ("제외 존", Zone.REMOVED),
        ("필드 존", Zone.FZONE),
        ("펜듈럼 존", Zone.PZONE),
        ("엑스트라 덱", None),  # extra_decks 로 이미 채워 둔다
    )
    for label, zone in placements:
        game = GameState.create(
            repository,
            decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20),
            extra_decks=([LUSTER_DRAGON] * 2, ()),
            turn_player=MINE,
            seed=1,
        )
        if zone is not None:
            card = game.create_instance(LUSTER_DRAGON, owner=MINE, zone=Zone.HAND)
            game.move(card, zone, to_player=MINE, position=Position.FACEUP_ATTACK)
        game.turn.turn_number = 2
        game.turn.set_phase(Phase.MAIN1)

        result = EV.evaluate(GameStateView.from_state(game, viewer=MINE))
        found = [item for item in result.excluded if item.note.startswith(label)]
        assert len(found) == 1, (label, result.excluded)
        assert found[0].category is ExclusionCategory.DESIGNED_OUT
        assert "모른다" not in found[0].note
        # 설계상 제외는 **평가의 미해결이 아니다.**
        assert not result.partial, result.excluded


def test_05_a_card_in_an_unscored_zone_no_longer_vanishes_silently(repository):
    """
    **STRUCTURAL-130 — 조용히 빠지던 네 자리.**

    예전에는 묘지 하나만 적었다. 제외 존 · 필드 존 · 펜듈럼 존 · 엑스트라
    덱에 카드가 있어도 ``excluded`` 가 **비었고**, 그래서 아무 기록도 남지
    않았다 — 적지 않았으므로 고칠 단서조차 없었다.

    **``partial`` 주장만 뒤집혔다** (Phase 3-E-8). 3-E-7 은 이 자리에서
    ``partial`` 이 참이 되는 것을 성과로 적었는데, 그 전제가 틀렸다: 다섯
    자리 모두 **보이는데 세지 않기로 한 것**이므로 평가의 미해결이 아니다.
    기록은 남아야 하고 (``excluded``), 깃발은 서지 않아야 한다 (``partial``)
    — 그 둘이 다른 질문이라는 것이 STRUCTURAL-130 의 전부다.
    """
    for zone in (Zone.REMOVED, Zone.FZONE, Zone.PZONE):
        game = state(repository, (MINE, zone, FACEUP, LUSTER_DRAGON))
        result = value(game)
        assert result.excluded, zone
        assert categories(result) == {ExclusionCategory.DESIGNED_OUT}, zone
        assert not result.partial, zone
        # 점수는 **움직이지 않는다** — 세기 시작한 것이 아니라 적기 시작했다.
        assert result.heuristic == 0, (zone, result.terms)

    # 엑스트라 덱도 같다.
    game = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20),
        extra_decks=([LUSTER_DRAGON] * 3, [LUSTER_DRAGON] * 3),
        turn_player=MINE,
        seed=1,
    )
    game.turn.turn_number = 2
    game.turn.set_phase(Phase.MAIN1)
    result = value(game)
    assert any(n.startswith("엑스트라 덱") for n in result.notes), result.excluded
    assert categories(result) == {ExclusionCategory.DESIGNED_OUT}
    assert not result.partial
    assert result.heuristic == 0


# ======================================================================
# §3 CATEGORY B — 관측할 수 없는 것
# ======================================================================


def test_06_an_opponent_face_down_card_stays_withheld(repository):
    """
    **CATEGORY B — 공개해서 해결하지 않는다 (§5).**

    상대의 뒷면 몬스터는 ``WITHHELD`` 로 남는다. 정체도, 공격력도 평가에
    들어오지 않고, 점수가 0 으로 바뀌지도 않는다.

    **3-E-7 은 이것을 ``UNKNOWN`` 으로 적었다.** 문구가 "모른다" 였기
    때문인데, 3-E-7 Audit 자신의 분류표에는 이미 **Category B(관측 불가)** 로
    적혀 있었다 — 문구와 분류가 어긋나 있었고, 범주를 담을 자리가 없어서
    문구가 이겼다. 그것이 STRUCTURAL-130 이다.

    왜 ``WITHHELD`` 가 맞는가: 못 세는 이유가 **공격력에 숫자가 없어서가 아니라
    정체가 가려져서**다. 어떤 평가자도 이보다 잘할 수 없으므로 평가의 미해결이
    아니다.
    """
    hidden = state(repository, (THEIRS, Zone.MZONE, SET, LUSTER_DRAGON))
    result = value(hidden, MINE)
    assert categories(result) == {ExclusionCategory.WITHHELD}, result.excluded
    assert all("세지 않았다" not in n for n in result.notes)
    assert not result.partial

    # 정체가 점수에 **전혀** 들어오지 않는다: 어떤 카드를 세트해도 같은 점수다.
    other = state(repository, (THEIRS, Zone.MZONE, SET, BATTLE_OX))
    assert value(other, MINE).heuristic == result.heuristic
    # 그리고 "몬스터가 없다" 와는 **다르다** — 0 으로 바뀌지 않았다.
    assert value(state(repository), MINE).heuristic != result.heuristic


def test_07_an_unknown_attack_is_never_turned_into_zero(repository):
    """
    **§8 — ``UNKNOWN`` 도 ``WITHHELD`` 도 0 점이 되지 않는다.**

    공격력이 ``?`` 인 몬스터는 ``atk`` 에 들어가지 않지만, 그 몬스터가
    **자리에 있다는 값**(``MONSTER_IN_LP``)은 그대로 센다. 0 으로 바꾸면
    "자리에 없다" 는 거짓이 된다.
    """
    question = state(
        repository, (MINE, Zone.MZONE, FACEUP, KING_OF_THE_SKULL_SERVANTS)
    )
    result = value(question)
    assert dict(result.terms)["atk"] == 0
    assert dict(result.terms)["monsters"] == MONSTER_IN_LP
    assert categories(result) == {ExclusionCategory.UNKNOWN}, result.excluded
    assert result.partial, "보이는데 숫자가 없는 것은 평가가 못 푼 것이다"
    assert result.heuristic != value(state(repository)).heuristic


def test_07b_unreadable_beats_face_down_when_both_are_true(repository):
    """
    **읽을 수 없는 것이 뒷면보다 먼저다** — 순서가 규칙이다 (Phase 3-E-6).

    내가 세트한 공격력 ``?`` 몬스터는 두 조건을 **동시에** 만족한다. 정체는
    알지만 공격력에 숫자가 없다. 그래서 범주는 ``DESIGNED_OUT``
    ("뒷면이라 세지 않았다") 가 아니라 ``UNKNOWN`` 이다 — 앞면으로 뒤집어도
    여전히 셀 수 없으므로 "숫자가 없다" 가 더 근본적인 사실이다.

    두 판정의 순서를 바꾸면 이 테스트가 깨진다. 실제로 그 위반을 주입해
    확인했고, 이 테스트가 없을 때는 **아무 테스트도 잡지 못했다.**
    """
    face_down = state(
        repository, (MINE, Zone.MZONE, SET, KING_OF_THE_SKULL_SERVANTS)
    )
    result = value(face_down)
    assert categories(result) == {ExclusionCategory.UNKNOWN}, result.excluded
    assert all("세지 않았다" not in n for n in result.notes), result.notes
    assert result.partial

    # 평범한 몬스터를 세트하면 그때는 ``DESIGNED_OUT`` 이다 — 둘이 갈린다.
    ordinary = value(state(repository, (MINE, Zone.MZONE, SET, LUSTER_DRAGON)))
    assert categories(ordinary) == {ExclusionCategory.DESIGNED_OUT}
    assert not ordinary.partial


# ======================================================================
# §3 CATEGORY C — STRUCTURAL-132: 엑스트라 몬스터 존
# ======================================================================


def test_08_the_engine_itself_counts_the_extra_monster_zone_as_the_field():
    """
    **§4 조건 4 를 코드로 증명한다.**

    "EMZ 의 몬스터가 평가 목적에 포함되는가" 는 내 의견이 아니다. 엔진이
    이미 다섯 자리에서 ``MZONE`` 과 ``EMZONE`` 을 **함께** 센다. 그래서
    EMZ 의 몬스터는 공격하고, 공격 대상이 되고, 직접 공격을 막는다 —
    ``ATK_IN_LP`` 와 ``MONSTER_IN_LP`` 의 근거가 글자 그대로 성립한다.
    """
    from engine.action_validation import MONSTER_ZONES
    from engine.battle import BATTLE_ZONES
    from engine.cost.model import FIELD_MONSTER_ZONES
    from engine.duel import BATTLE_TARGET_ZONES

    for group in (BATTLE_ZONES, BATTLE_TARGET_ZONES, MONSTER_ZONES, FIELD_MONSTER_ZONES):
        assert set(group) == {Zone.MZONE, Zone.EMZONE}, group

    # RULE-BATTLE-013(직접 공격)도 두 자리를 함께 센다.
    source = source_of("engine/action_validation.py")
    assert "opponent.zone(zone).size for zone in (Zone.MZONE, Zone.EMZONE)" in source


def test_08b_the_evaluation_now_reads_the_same_two_zones(repository):
    """평가가 보는 자리가 엔진이 보는 자리와 **같은 둘**이다."""
    view = GameStateView.from_state(state(repository), viewer=MINE)
    assert tuple(z.zone for z in _field_monster_zones(view.me)) == (
        Zone.MZONE,
        Zone.EMZONE,
    )


def test_09_an_extra_monster_zone_monster_is_scored_like_any_field_monster(repository):
    """
    **STRUCTURAL-132 재현 — IMPLEMENTATION GAP 이었다.**

    같은 몬스터를 ``MZONE`` 에 두었을 때와 ``EMZONE`` 에 두었을 때 점수가
    같아야 한다. 예전에는 EMZ 쪽이 **빈 필드와 완전히 같은 점수**(+0)였고,
    ``excluded`` 도 비어서 ``partial`` 이 "다 셌다" 고 했다.

    정보는 사라진 적이 없다 — ``GameState`` 에도, ``canonical_state`` 에도,
    ``GameStateView.extra_monster_zone`` 에도 있었다. **평가만** 읽지
    않았다 (§9).
    """
    empty = state(repository)
    main = state(repository, (MINE, Zone.MZONE, FACEUP, LUSTER_DRAGON))
    extra = state(repository, (MINE, Zone.EMZONE, FACEUP, LUSTER_DRAGON))

    # §9 — 정보는 모든 단계에 있었다.
    assert empty.state_hash() != extra.state_hash()
    assert empty.canonical_state() != extra.canonical_state()
    emz = GameStateView.from_state(extra, viewer=MINE).me.extra_monster_zone
    assert emz.size == 1
    assert emz.occupied()[0].definition.atk == 1900
    assert emz.occupied()[0].face_up is True

    # 그리고 이제 평가도 읽는다.
    assert value(extra).heuristic == value(main).heuristic
    assert value(extra).heuristic != value(empty).heuristic
    assert dict(value(extra).terms)["atk"] == 1900
    assert dict(value(extra).terms)["monsters"] == MONSTER_IN_LP


def test_10_an_extra_monster_zone_monster_is_zero_sum(repository):
    """
    EMZ 의 몬스터가 **두 자리 사이에서 영합**이다.

    예전에는 EMZ 에 몬스터를 둔 쪽만 손해였다 — 자기 몬스터는 세지 않고
    상대 몬스터는 세었기 때문이다.
    """
    game = state(
        repository,
        (MINE, Zone.MZONE, FACEUP, LUSTER_DRAGON),
        (THEIRS, Zone.EMZONE, FACEUP, BATTLE_OX),
    )
    mine, theirs = value(game, MINE), value(game, THEIRS)
    assert mine.heuristic == 1900 - 1700
    assert mine.heuristic + theirs.heuristic == 0


def test_11_the_duel_offers_an_attack_on_a_monster_the_evaluation_can_see(repository):
    """
    **§10 — 경로가 깨지지 않는다.**

    legal action → simulation → future state → ``GameStateView`` → evaluation.

    엔진이 EMZ 의 몬스터를 공격 대상으로 제시하는데 평가가 그 몬스터를
    **없는 것으로** 보면, 탐색은 자기가 왜 공격하는지 모르는 상태가 된다.
    """
    game = state(
        repository,
        (MINE, Zone.MZONE, FACEUP, LUSTER_DRAGON),
        (THEIRS, Zone.EMZONE, FACEUP, BATTLE_OX),
    )
    game.turn.set_phase(Phase.BATTLE)
    duel = Duel(
        state=game,
        priority=PriorityState.idle(turn_player=MINE, phase=Phase.BATTLE),
    )
    legal = duel.legal_actions()
    attacks = [a for a in legal.allowed if a.kind.name == "ATTACK"]
    assert attacks, [a.kind.name for a in legal.allowed]

    simulator = Simulator(duel)
    result = simulator.simulate(attacks[0], viewer=legal.seat)
    assert result.future is not None
    before = EV.evaluate(GameStateView.from_state(game, viewer=MINE))
    after = EV.evaluate(result.future)
    # 1900 이 1700 을 쳤다 — 상대 몬스터가 사라지고 LP 200 이 깎인다.
    assert after.heuristic > before.heuristic, (before.terms, after.terms)
