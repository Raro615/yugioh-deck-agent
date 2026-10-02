"""
Phase 3-E-7 — STRUCTURAL-130: ``partial`` / ``excluded`` 분류 Audit.

이 파일이 고정하는 것은 **excluded 가 왜 excluded 인가**다. 네 가지를 섞지
않는다.

=================  ========================================================
DESIGNED OUT       관측되지만 **설계상 세지 않는다**. 묘지 · 제외 존 ·
                   필드 존 · 펜듈럼 존 · 엑스트라 덱. 문구는 "값을 매기지
                   않았다"
UNKNOWN            값을 **읽을 수 없다**. 상대의 뒷면 카드, 공격력이 ``?``
                   인 카드. 문구는 "모른다"
WITHHELD           정체는 **알지만** 그 값이 지금 들어올 피해가 아니다.
                   내 뒷면 몬스터의 공격력. 문구는 "세지 않았다"
IMPLEMENTATION     관측에 있고, 평가 목적에 들어가고, 그런데 평가가
GAP                **읽지 않는다.** 고칠 것은 이것 하나뿐이다
=================  ========================================================

이번 Audit 이 찾은 IMPLEMENTATION GAP 은 **STRUCTURAL-132** 하나다 —
엑스트라 몬스터 존이 평가에서 통째로 빠져 있었다 (``test_05`` · ``test_06``).

남아 있는 것 (고치지 않고 적는다)
---------------------------------
- **``partial`` 은 여전히 한 비트다** — 위 네 가지가 모두 같은 ``excluded``
  문자열 목록으로 들어가고, ``partial`` 은 그 목록이 비었는지만 본다.
  그래서 "설계상 제외" 와 "모른다" 를 **기계가 구분할 수 없다**
  (STRUCTURAL-130 은 이 Phase 로 해결되지 않는다 · ``test_09``)
"""

import ast
import pathlib
import random
import re

import pytest

from agent.evaluation import (
    GRAVE_IS_COUNTED,
    MONSTER_IN_LP,
    StateEvaluator,
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

#: 문구 → 범주. **문구가 범주를 말한다** — 이 표에 없는 문구가 나오면
#: 분류되지 않은 제외 사유가 생긴 것이고, ``test_03`` 이 깨진다.
CATEGORY_OF: tuple[tuple[str, str], ...] = (
    ("값을 매기지 않았다", "DESIGNED_OUT"),
    ("공격력은 세지 않았다", "WITHHELD"),
    ("모른다", "UNKNOWN"),
)


def categorize(note: str) -> str:
    for marker, category in CATEGORY_OF:
        if marker in note:
            return category
    raise AssertionError(f"분류되지 않은 제외 사유: {note!r}")


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


def test_01_partial_is_exactly_one_bit_over_the_excluded_list():
    """
    **§7 — ``partial`` 은 ``excluded`` 가 비었는지 하나뿐이다.**

    세 가지 다른 뜻("일부 항만 계산됐다" · "일부 값이 UNKNOWN 이다" ·
    "설계상 빠진 것이 있다")이 **같은 한 비트**로 묶여 있다. 그래서
    ``partial`` 하나로는 무엇이 빠졌는지 알 수 없다 — STRUCTURAL-130 의
    본체이고, 이 Phase 는 그것을 **해결하지 않는다.**
    """
    source = source_of("agent/evaluation.py")
    tree = ast.parse(source)
    (partial,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "partial"
    ]
    body = [n for n in partial.body if not isinstance(n, ast.Expr)]
    assert len(body) == 1, "partial 이 한 줄이 아니면 정의가 바뀐 것이다"
    assert ast.unparse(body[0]) == "return bool(self.excluded)"

    # 그 목록은 **자유 문자열**이다 — 범주를 담는 자리가 없다.
    from agent.evaluation import StateValue

    assert StateValue.__annotations__["excluded"] == "tuple[str, ...]"


def test_02_every_excluded_note_names_its_own_category(repository):
    """
    **§3 — 문구 하나가 범주 하나를 말한다.**

    같은 ``excluded`` 목록에 세 범주가 섞여 들어가므로, 적어도 **문구로는**
    갈라져 있어야 한다. "모른다"(UNKNOWN) · "세지 않았다"(WITHHELD) ·
    "값을 매기지 않았다"(DESIGNED OUT) 가 서로 겹치지 않는다.
    """
    cases = {
        # 상대 뒷면 몬스터 — 정의를 읽을 수 없다
        "UNKNOWN": state(repository, (THEIRS, Zone.MZONE, SET, LUSTER_DRAGON)),
        # 내 뒷면 몬스터 — 정의는 알지만 공격하지 않는다
        "WITHHELD": state(repository, (MINE, Zone.MZONE, SET, LUSTER_DRAGON)),
        # 제외 존 — 공개되어 있지만 설계상 세지 않는다
        "DESIGNED_OUT": state(repository, (MINE, Zone.REMOVED, FACEUP, LUSTER_DRAGON)),
    }
    for expected, game in cases.items():
        notes = value(game).excluded
        assert notes, expected
        assert {categorize(note) for note in notes} == {expected}, notes


def test_03_no_real_duel_produces_an_unclassified_excluded_note(repository):
    """
    **§2 — 실제 대국에서 나오는 모든 제외 사유가 분류된다.**

    사례를 만들지 않고 실제 듀얼에서 모아 분류한다. 분류되지 않은 문구가
    하나라도 나오면 :func:`categorize` 가 터진다.
    """
    deck = [LUSTER_DRAGON] * 10 + [BATTLE_OX] * 6 + [POT_OF_GREED] * 4
    seen: dict[str, set[str]] = {}
    evaluated = 0
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
                for note in EV.evaluate(result.future).excluded:
                    shape = re.sub(r"\d+", "N", note)
                    seen.setdefault(categorize(note), set()).add(shape)
            duel.apply(rng.choice(legal.allowed))

    assert evaluated > 500, evaluated
    # 실제 대국에서 세 범주가 모두 나온다 — 어느 하나도 이론상의 것이 아니다.
    assert set(seen) == {"UNKNOWN", "WITHHELD", "DESIGNED_OUT"}, seen


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
        note = [n for n in result.excluded if n.startswith(label)]
        assert len(note) == 1, (label, result.excluded)
        assert categorize(note[0]) == "DESIGNED_OUT"
        assert "모른다" not in note[0]


def test_05_a_card_in_an_unscored_zone_no_longer_vanishes_silently(repository):
    """
    **STRUCTURAL-130 — 조용히 빠지던 네 자리.**

    예전에는 묘지 하나만 적었다. 제외 존 · 필드 존 · 펜듈럼 존 · 엑스트라
    덱에 카드가 있어도 ``excluded`` 가 **비었고**, 그래서 ``partial`` 이
    "다 셌다" 는 거짓을 말했다 — 적지 않았으므로 고칠 단서조차 없었다.
    """
    for zone in (Zone.REMOVED, Zone.FZONE, Zone.PZONE):
        game = state(repository, (MINE, zone, FACEUP, LUSTER_DRAGON))
        result = value(game)
        assert result.partial, zone
        assert result.excluded, zone
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
    assert result.partial
    assert any(n.startswith("엑스트라 덱") for n in result.excluded), result.excluded
    assert result.heuristic == 0


# ======================================================================
# §3 CATEGORY B — 관측할 수 없는 것
# ======================================================================


def test_06_an_opponent_face_down_card_stays_unknown(repository):
    """
    **CATEGORY B — 공개해서 해결하지 않는다 (§5).**

    상대의 뒷면 몬스터는 ``UNKNOWN`` 으로 남는다. 정체도, 공격력도 평가에
    들어오지 않고, 점수가 0 으로 바뀌지도 않는다.
    """
    hidden = state(repository, (THEIRS, Zone.MZONE, SET, LUSTER_DRAGON))
    result = value(hidden, MINE)
    assert any(categorize(n) == "UNKNOWN" for n in result.excluded)
    assert all("세지 않았다" not in n for n in result.excluded)

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
    assert any(categorize(n) == "UNKNOWN" for n in result.excluded)
    assert result.heuristic != value(state(repository)).heuristic


def test_07b_unreadable_beats_face_down_when_both_are_true(repository):
    """
    **읽을 수 없는 것이 뒷면보다 먼저다** — 순서가 규칙이다 (Phase 3-E-6).

    내가 세트한 공격력 ``?`` 몬스터는 두 조건을 **동시에** 만족한다. 정체는
    알지만(뒷면이 아니어도) 공격력에 숫자가 없다. 그래서 범주는 ``WITHHELD``
    ("뒷면이라 세지 않았다") 가 아니라 ``UNKNOWN`` ("읽을 수 없다") 다 —
    앞면으로 뒤집어도 여전히 셀 수 없기 때문이다.

    두 판정의 순서를 바꾸면 이 테스트가 깨진다. 실제로 그 위반을 주입해
    확인했고, 이 테스트가 없을 때는 **아무 테스트도 잡지 못했다.**
    """
    face_down = state(
        repository, (MINE, Zone.MZONE, SET, KING_OF_THE_SKULL_SERVANTS)
    )
    notes = value(face_down).excluded
    assert [categorize(n) for n in notes] == ["UNKNOWN"], notes
    assert all("세지 않았다" not in n for n in notes), notes

    # 평범한 몬스터를 세트하면 그때는 ``WITHHELD`` 다 — 둘이 갈린다.
    ordinary = state(repository, (MINE, Zone.MZONE, SET, LUSTER_DRAGON))
    assert [categorize(n) for n in value(ordinary).excluded] == ["WITHHELD"]


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
