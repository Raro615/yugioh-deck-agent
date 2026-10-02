"""
Phase 3-E-5 — Evaluation Alignment Audit (조사 전용).

이 파일은 평가 함수를 **고치지 않는다.** 지금 평가가 실제로 무엇을 세고
무엇을 세지 않는지, 그리고 상태 변화와 점수 방향이 일치하는지를 **실행 가능한
주장으로 고정한다.** 다음 Phase 가 무엇을 바꾸는지 이 파일이 깨지는 것으로
보인다.

맞게 되어 있는 것
-----------------
- ``evaluate(self, view)`` — 행위를 **볼 수 없다.** 같은 관측이면 같은 점수다
- LP · 필드 · 덱의 방향이 옳다 (내 것이 늘면 올라가고 상대 것이 늘면 내려간다)
- 끝난 판의 등급이 휴리스틱을 **언제나** 이긴다
- ``UNKNOWN`` 이 0 · False · 패배로 바뀌지 않는다
- 가려진 정보를 읽지 않는다 (상대 패 · 상대 뒷면의 정체)
- 대상의 ``instance_id`` 자체를 점수에 넣지 않는다
- 시뮬레이션의 점수가 실제로 적용한 뒤의 점수와 **같다**

어긋나 있는 것 (고치지 않고 적는다)
-----------------------------------
- **``excluded`` 가 거짓을 말한다** — 내 뒷면 카드의 공격력을 세면서 "값을
  매기지 않았다" 고 보고한다 (STRUCTURAL-115). 실측 93.3%
- **side-to-move 를 읽지 않는다** — 관측에 ``turn_player`` 가 있는데도
  차례가 누구인지가 점수에 들어가지 않는다 (STRUCTURAL-128)
- **``hand`` 만 차분이 아니다** — 다른 모든 항은 ``me - opponent`` 인데
  패는 내 것만 센다. 그래서 영합이 깨진다 (STRUCTURAL-129)
- **``partial`` 이 신호가 아니다** — 실측 99.6% 가 참이다 (STRUCTURAL-130)
- 드로우가 손해로 읽힌다 (STRUCTURAL-122) · 두 정책이 다른 양을 센다
  (STRUCTURAL-123)
"""

import ast
import inspect
import pathlib

import pytest

from agent import rule_based_policy, search_policy
from agent.evaluation import (
    ATK_IN_LP,
    DECK_CARD_IN_LP,
    GRAVE_IS_COUNTED,
    HAND_CARD_IN_LP,
    MONSTER_IN_LP,
    SPELL_TRAP_IN_LP,
    StateEvaluator,
    StateValue,
    Terminal,
)
from agent.search import SearchCandidate
from agent.simulation import SimulationStatus, Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.state.rule_usage import RuleActionKind
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1
EV = StateEvaluator()

LUSTER_DRAGON = 11091375  # ATK 1900 / DEF 1600
BATTLE_OX = 5053103  # ATK 1700 / DEF 1000
KOJIKOCY = 1184620  # ATK 1500 / DEF 1200
WHITE_DUSTON = 3557275  # ATK 0 / DEF 1000
KING_OF_THE_SKULL_SERVANTS = 36021814  # ATK ?
POT_OF_GREED = 55144522
RUTHLESS_DENIAL = 73148972
TRAP_HOLE = 4206964


# ======================================================================
# 판 만들기 — 전부 실제 엔진으로
# ======================================================================


def board(
    repository,
    *,
    mine=(),
    theirs=(),
    my_facedown=(),
    their_facedown=(),
    my_hand=(),
    their_hand: int = 0,
    my_lp: int = 8000,
    their_lp: int = 8000,
    turn_player: int = MINE,
    phase: Phase = Phase.MAIN1,
    turn: int = 2,
) -> GameState:
    """원하는 판 하나. 배치는 ``create_instance`` + ``GameState.move`` 다."""
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20),
        turn_player=turn_player,
        seed=1,
    )
    for seat, faceup, facedown in (
        (MINE, mine, my_facedown),
        (THEIRS, theirs, their_facedown),
    ):
        for card_id in faceup:
            card = state.create_instance(card_id, owner=seat, zone=Zone.HAND)
            state.move(
                card, Zone.MZONE, to_player=seat, position=Position.FACEUP_ATTACK
            )
        for card_id in facedown:
            card = state.create_instance(card_id, owner=seat, zone=Zone.HAND)
            state.move(
                card,
                Zone.MZONE,
                to_player=seat,
                position=Position.FACEDOWN_DEFENSE,
            )
    for card_id in my_hand:
        state.create_instance(card_id, owner=MINE, zone=Zone.HAND)
    for _ in range(their_hand):
        state.create_instance(LUSTER_DRAGON, owner=THEIRS, zone=Zone.HAND)
    state.player(MINE).change_life(my_lp - state.player(MINE).life_points)
    state.player(THEIRS).change_life(their_lp - state.player(THEIRS).life_points)
    state.turn.turn_number = turn
    state.turn.turn_player = turn_player
    state.turn.set_phase(phase)
    return state


def duel_of(state: GameState, *, turn_player: int = MINE) -> Duel:
    return Duel(
        state=state,
        priority=PriorityState.idle(
            turn_player=turn_player, phase=state.turn.phase
        ),
    )


def value(state: GameState, viewer: int = MINE) -> StateValue:
    return EV.evaluate(GameStateView.from_state(state, viewer=viewer))


def term(state: GameState, name: str, viewer: int = MINE) -> int:
    return dict(value(state, viewer).terms)[name]


def source_names(path: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text())
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }


# ======================================================================
# §2 · §3 — 평가가 읽는 것과 읽지 않는 것
# ======================================================================


def test_01_the_evaluator_receives_only_an_observation():
    """
    **§3 — 경로가 ``Simulation State → GameStateView → StateValue`` 하나다.**

    ``GameState`` 를 주면 거부한다. 주면 상대 패와 덱이 그대로 보인다.
    """
    from agent.evaluation import EvaluationError

    signature = inspect.signature(StateEvaluator.evaluate)
    assert list(signature.parameters) == ["self", "view"]

    with pytest.raises(EvaluationError, match="GameStateView"):
        EV.evaluate(object())  # type: ignore[arg-type]


def test_02_the_evaluator_reads_no_hidden_channel():
    """
    **§2-8 · §16-6 — 가려진 정보가 점수에 들어가지 않는다.**

    난수원 · 체인 · 우선권 · 행위를 소스에서 **한 글자도** 읽지 않는다.
    """
    names = source_names("agent/evaluation.py")
    for forbidden in (
        "randomness",
        "GameState",
        "Chain",
        "PriorityState",
        "PlayerAction",
        "PlayerActionKind",
        "action",
        "kind",
        "instance_id",
        "InstanceId",
        "target",
        "targets",
        "card_id",
        "name",
    ):
        if forbidden == "name":
            continue  # ``StateEvaluator.name`` 은 평가자 이름이다
        assert forbidden not in names, forbidden


def test_03_the_evaluator_reads_these_and_not_side_to_move():
    """
    **§2 의 열 질문에 대한 답을 한 자리에 적는다.**

    ``turn_player`` · ``is_my_turn`` 이 관측에 **있는데도** 읽지 않는다 —
    이것이 STRUCTURAL-128 이다.
    """
    names = source_names("agent/evaluation.py")

    # 읽는다
    for present in (
        "life_points",
        "monster_zone",
        "spell_zone",
        "deck",
        "hand",
        "grave",
        "size",
        "occupied",
        "atk",
        "definition",
        "is_monster",
        "atk_is_question",
        "has_atk",
        "face_up",
        "winner",
        "viewer",
        "is_over",
    ):
        assert present in names, present

    # 읽지 않는다 — 그런데 관측에는 있다.
    assert "turn_player" not in names
    assert "is_my_turn" not in names
    assert "turn_player" in GameStateView.__dataclass_fields__
    assert hasattr(GameStateView, "is_my_turn")


# ======================================================================
# §4 — Action Independence
# ======================================================================


@pytest.mark.real_card
def test_04_the_same_observation_scores_the_same_through_any_route(repository):
    """
    **§4 — 같은 future state 면 같은 점수다.** 구조적으로 그렇다.

    서명에 행위가 없으니 쓸 수가 없고, 경로가 달라도 결과가 같다는 것을
    **실제로 두 경로로** 만들어 확인한다.

        경로 A  패에서 일반 소환한다
        경로 B  같은 자리에 직접 놓고 소환권 사용까지 맞춘다

    두 ``GameState`` 는 다른 역사를 갖지만 관측이 같고, 점수도 같다.
    """
    # 경로 A — 실제 일반 소환
    left = GameState.create(
        repository, decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20), seed=1
    )
    left.create_instance(LUSTER_DRAGON, owner=MINE, zone=Zone.HAND)
    left.turn.turn_number = 2
    left.turn.set_phase(Phase.MAIN1)
    duel = duel_of(left)
    summon = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
    )
    assert duel.apply(summon).accepted
    through_summon = duel.view(MINE)

    # 경로 B — 직접 배치 + 소환권 기록
    right = GameState.create(
        repository, decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20), seed=1
    )
    placed = right.create_instance(LUSTER_DRAGON, owner=MINE, zone=Zone.HAND)
    right.move(
        placed, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK
    )
    right.turn.turn_number = 2
    right.turn.set_phase(Phase.MAIN1)
    right.rule_uses.record(2, MINE, RuleActionKind.NORMAL_SUMMON)
    through_placement = GameStateView.from_state(right, viewer=MINE)

    assert through_summon.canonical_state() == through_placement.canonical_state()
    assert (
        EV.evaluate(through_summon).ordering_key()
        == EV.evaluate(through_placement).ordering_key()
    )

    # 그리고 같은 관측을 몇 번 평가해도 같다 — 상태를 들고 있지 않다.
    assert len({EV.evaluate(through_summon).ordering_key() for _ in range(50)}) == 1


@pytest.mark.real_card
def test_05_a_whole_duel_never_scores_one_observation_two_ways(repository):
    """
    **같은 관측에 두 점수가 나오는 일이 없다.** 실제 듀얼을 굴려 센다.

    관측(``canonical_state``)을 열쇠로 점수를 쌓아 두고, 같은 열쇠가 다시
    나오면 점수가 같은지 본다.
    """
    deck = (
        [LUSTER_DRAGON] * 10
        + [BATTLE_OX] * 6
        + [POT_OF_GREED] * 4
        + [RUTHLESS_DENIAL] * 4
    )
    seen: dict[tuple, tuple] = {}
    checked = 0
    for seed in (1, 2, 3):
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
        for _ in range(300):
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
                key = result.future.canonical_state()
                score = EV.evaluate(result.future).ordering_key()
                checked += 1
                if key in seen:
                    assert seen[key] == score, (key, seen[key], score)
                seen[key] = score
            duel.apply(legal.allowed[0])
    assert checked > 300, checked


# ======================================================================
# §5 — Side-to-move  (STRUCTURAL-128)
# ======================================================================


@pytest.mark.real_card
def test_06_side_to_move_does_not_change_the_score(repository):
    """
    **STRUCTURAL-128 — 차례가 누구인지가 점수에 들어가지 않는다.**

    같은 필드 · 같은 LP · 같은 패 · 같은 덱에서 차례만 바꿔도 점수가 같다.
    관측에는 ``turn_player`` 가 실려 있으므로 **읽을 수 있는데 읽지 않는다.**

    지금 이것이 왜 중요한가: Depth-1 탐색은 ``END_PHASE`` 의 미래도 평가하는데,
    그 미래는 **상대 차례**다. 차례를 세지 않으면 "내가 한 수 더 둘 수 있다" 와
    "상대가 한 수 둔다" 가 같은 값으로 읽힌다.

    현재 설계가 의도적으로 뺀 것인지는 코드에 적혀 있지 않다 — 평가 모듈의
    설명은 ``viewer`` 관점만 말하고 차례는 언급하지 않는다. 그래서
    **의도인지 누락인지 알 수 없다**는 것이 이 Audit 의 결론이다.
    """
    shape = dict(
        mine=(LUSTER_DRAGON,),
        theirs=(BATTLE_OX,),
        my_hand=(POT_OF_GREED,),
        their_hand=2,
    )
    mine_turn = value(board(repository, **shape, turn_player=MINE))
    their_turn = value(board(repository, **shape, turn_player=THEIRS))

    assert mine_turn.heuristic == their_turn.heuristic
    assert mine_turn.ordering_key() == their_turn.ordering_key()
    # 관측 자체는 둘을 구분한다 — 평가만 구분하지 않는다.
    assert (
        GameStateView.from_state(
            board(repository, **shape, turn_player=MINE), viewer=MINE
        ).turn_player
        != GameStateView.from_state(
            board(repository, **shape, turn_player=THEIRS), viewer=MINE
        ).turn_player
    )


# ======================================================================
# §6 — LP
# ======================================================================


@pytest.mark.real_card
def test_07_lp_is_a_difference_and_points_the_right_way(repository):
    """
    **§6 — 내 LP 와 상대 LP 를 반대로 세지 않는다.** 1:1 차분이다.
    """
    even = board(repository)
    assert term(even, "lp") == 0

    assert term(board(repository, my_lp=7000), "lp") == -1000
    assert term(board(repository, my_lp=6000), "lp") == -2000
    assert term(board(repository, their_lp=7000), "lp") == +1000
    assert term(board(repository, their_lp=6000), "lp") == +2000

    # 상대 관점에서는 부호가 뒤집힌다 — 같은 평가자가 각자의 관점으로 돈다.
    assert term(board(repository, my_lp=7000), "lp", viewer=THEIRS) == +1000


# ======================================================================
# §7 — Field
# ======================================================================


@pytest.mark.real_card
def test_08_field_separates_existing_from_being_strong(repository):
    """
    **§7 — "몬스터가 있다" 와 "몬스터가 강하다" 가 다른 항이다.**

    공격력 0 인 몬스터도 **있다는 값**(500)을 받는다. 그래서 "약한 몬스터는
    없는 것과 같다" 가 되지 않는다.
    """
    assert MONSTER_IN_LP == 500 and ATK_IN_LP == 1

    empty = value(board(repository))
    assert empty.heuristic == 0

    duston = board(repository, mine=(WHITE_DUSTON,))
    assert term(duston, "atk") == 0
    assert term(duston, "monsters") == MONSTER_IN_LP

    luster = board(repository, mine=(LUSTER_DRAGON,))
    assert term(luster, "atk") == 1900
    assert term(luster, "monsters") == MONSTER_IN_LP

    # 상대 쪽은 부호가 반대다 — 자기와 상대를 뒤집어 세지 않는다.
    theirs = board(repository, theirs=(LUSTER_DRAGON,))
    assert term(theirs, "atk") == -1900
    assert term(theirs, "monsters") == -MONSTER_IN_LP

    # 두 마리는 한 마리보다 낫고, 센 쪽이 더 낫다.
    two = value(board(repository, mine=(LUSTER_DRAGON, LUSTER_DRAGON))).heuristic
    mixed = value(board(repository, mine=(LUSTER_DRAGON, BATTLE_OX))).heuristic
    one = value(luster).heuristic
    assert two > mixed > one


@pytest.mark.real_card
def test_09_an_unknown_attack_is_excluded_not_zeroed(repository):
    """
    **§10 — 공격력 ``?`` 를 0 으로 바꾸지 않는다.**

    세지 않고 ``excluded`` 에 적는다. 0 으로 넣으면 "약하다" 는 거짓이 되고
    큰 수로 넣으면 "강하다" 는 거짓이 된다.
    """
    unknown = value(board(repository, mine=(KING_OF_THE_SKULL_SERVANTS,)))
    assert dict(unknown.terms)["atk"] == 0
    assert dict(unknown.terms)["monsters"] == MONSTER_IN_LP
    assert any("공격력을 모른다" in note for note in unknown.excluded)
    assert unknown.partial


@pytest.mark.real_card
def test_10_an_opponent_face_down_monster_is_excluded(repository):
    """
    **§3 · §10 — 상대 뒷면의 정체를 추측하지 않는다.**

    자리와 장수는 세고(``monsters``) 공격력은 세지 않는다.
    """
    hidden = value(board(repository, their_facedown=(LUSTER_DRAGON,)))
    assert dict(hidden.terms)["atk"] == 0, "상대 뒷면의 공격력을 읽었다"
    assert dict(hidden.terms)["monsters"] == -MONSTER_IN_LP
    assert any("상대 몬스터" in note for note in hidden.excluded)
    assert hidden.terminal is Terminal.ONGOING, "모르는 것을 패배로 바꾸지 않는다"


# ======================================================================
# §16-9 — STRUCTURAL-115: excluded 가 거짓을 말한다
# ======================================================================


@pytest.mark.real_card
def test_11_my_own_face_down_card_is_no_longer_counted_against_the_report(
    repository,
):
    """
    **STRUCTURAL-115 가 풀린 자리다** (Phase 3-E-6).

    Phase 3-E-5 에서 이 시험은 그 반대를 적었다 — 평가가 내 뒷면 카드의
    공격력을 **세면서** ``excluded`` 에 "값을 매기지 않았다" 고 보고한다고.
    앞면 공격 1900 과 뒷면 수비 1900 이 둘 다 ``+2400`` 이었다.

    3층으로 나눠 추적한 결과 **Evaluation 층의 결함**이었다.

        Battle       position 을 올바르게 읽는다 (RULE-BATTLE-011 vs 012) ✔
        Observation  position · face_up · defense 를 모두 제공한다 ✔
        Evaluation   ``_zone_attack`` 이 position 을 **한 번도 읽지 않았다** ✘

    고친 것은 ``_zone_attack`` 하나다. 이제 셋이 각자 사실을 말한다.

        atk        뒷면은 **세지 않는다** (0)
        monsters   뒷면도 **센다** (500) — 칸을 차지하고 나중에 쓸 수 있다
        excluded   "공격력은 세지 않았다" — **참이다**

    **"수비력을 어떻게 점수화할 것인가" 는 정하지 않았다** (Phase 3-E-5 §9).
    정한 것은 "뒷면의 공격력은 지금 들어올 피해가 아니다" 하나이고, 그것은
    평가 모듈의 설명이 이미 의도라고 적고 있던 것이다.
    """
    face_up = value(board(repository, mine=(LUSTER_DRAGON,)))
    face_down = value(board(repository, my_facedown=(LUSTER_DRAGON,)))

    # ① 두 상태가 **구별된다** — 차이가 정확히 그 카드의 공격력이다.
    assert face_up.heuristic == 2400
    assert face_down.heuristic == 500
    assert face_up.heuristic - face_down.heuristic == 1900

    # ② 공격력은 빠지고 자리의 값은 남는다.
    assert dict(face_down.terms)["atk"] == 0
    assert dict(face_down.terms)["monsters"] == MONSTER_IN_LP

    # ③ 보고가 사실이다 — "모른다" 가 아니라 "세지 않았다" 다.
    assert face_up.excluded == ()
    assert any("공격력은 세지 않았다" in note for note in face_down.excluded)
    assert not any("값을 매기지 않았다" in note for note in face_down.excluded)
    assert not any("모른다" in note for note in face_down.excluded), (
        "내 카드의 정체는 안다 — 모른다고 적으면 그것이 새 거짓이다"
    )

    # ④ 뒷면 마법 · 함정은 제외 항목이 **없다** — 뺀 것이 없기 때문이다.
    state = board(repository)
    trap = state.create_instance(TRAP_HOLE, owner=MINE, zone=Zone.HAND)
    state.move(trap, Zone.SZONE, to_player=MINE, position=Position.FACEDOWN)
    set_spell = value(state)
    assert dict(set_spell.terms)["spells"] == SPELL_TRAP_IN_LP
    assert set_spell.excluded == (), set_spell.excluded


@pytest.mark.real_card
def test_11b_a_face_down_monster_is_now_symmetric_between_the_two_seats(
    repository,
):
    """
    **고친 결과 뒷면도 영합(zero-sum)이 되었다.**

    고치기 전에는 내 뒷면 몬스터가 P0 에게 ``+2400``, P1 에게 ``-500`` 이어서
    합이 ``+1900`` 이었다 — 같은 판인데 두 자리의 값이 어긋났다. 평가 모듈의
    설명이 **바로 이것을 피하려 했다**고 적고 있었다: "넣으면 같은 판이 보는
    자리에 따라 다른 점수가 되어 §23 의 일관된 관점이 깨지기 때문이다."

    이것은 STRUCTURAL-129(``hand`` 항이 차분이 아니라 영합이 깨진다)를 고친
    것이 **아니다.** 패는 그대로이고, 여기서 맞춰진 것은 뒷면 몬스터뿐이다.
    """
    face_up = board(repository, mine=(LUSTER_DRAGON,))
    assert value(face_up, MINE).heuristic + value(face_up, THEIRS).heuristic == 0

    face_down = board(repository, my_facedown=(LUSTER_DRAGON,))
    assert value(face_down, MINE).heuristic == +MONSTER_IN_LP
    assert value(face_down, THEIRS).heuristic == -MONSTER_IN_LP
    assert (
        value(face_down, MINE).heuristic + value(face_down, THEIRS).heuristic == 0
    )

    # 상대 뒷면은 여전히 **모른다** — 관측 경계가 그대로다.
    theirs = value(board(repository, their_facedown=(LUSTER_DRAGON,)), MINE)
    assert any("모른다" in note for note in theirs.excluded)
    assert not any("세지 않았다" in note for note in theirs.excluded)


@pytest.mark.real_card
def test_12_partial_is_true_on_almost_every_real_board(repository):
    """
    **STRUCTURAL-130 — ``partial`` 이 신호가 되지 못한다.**

    실제 듀얼에서 평가한 미래의 **99% 이상**이 ``partial`` 이다. 늘 참인
    깃발은 "이 평가는 불완전하다" 를 알려주지 못한다.

    가장 큰 사유 둘이 **묘지**(설계상 세지 않는다)와 **내 뒷면**
    (STRUCTURAL-115 의 거짓 보고)이다.
    """
    assert GRAVE_IS_COUNTED is False

    deck = [LUSTER_DRAGON] * 10 + [BATTLE_OX] * 6 + [POT_OF_GREED] * 4
    total = partial = 0
    for seed in (1, 2):
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
                total += 1
                partial += EV.evaluate(result.future).partial
            duel.apply(legal.allowed[0])

    assert total > 200, total
    assert partial / total > 0.95, (partial, total)


# ======================================================================
# §8 — Hand / Resource  (STRUCTURAL-129)
# ======================================================================


@pytest.mark.real_card
def test_13_hand_is_the_only_term_that_is_not_a_difference(repository):
    """
    **STRUCTURAL-129 — ``hand`` 만 차분이 아니라서 영합이 깨진다.**

    다른 모든 항은 ``me - opponent`` 이고, 그래서 앞면만 있는 판에서는
    P0 의 점수와 P1 의 점수를 더하면 0 이다. ``hand`` 는 내 것만 세므로
    둘을 더해도 0 이 되지 않는다.

    **설계 의도는 적혀 있다** — "상대 패는 장수가 보이지만 값을 매기려면
    내용을 알아야 한다". 적혀 있지 않은 것은 **그 결과**다: 평가가 영합이
    아니므로, 두 자리의 점수를 견주는 어떤 계산(minimax · 후회 · 상대
    관점 추정)도 지금 값으로는 성립하지 않는다.
    """
    # 앞면만 있는 판은 영합이다.
    symmetric = board(repository, mine=(LUSTER_DRAGON,), theirs=(BATTLE_OX,))
    assert (
        value(symmetric, MINE).heuristic + value(symmetric, THEIRS).heuristic == 0
    )

    # 패가 들어오면 깨진다.
    for mine_hand, their_hand in ((3, 0), (0, 3), (3, 3)):
        state = board(
            repository,
            my_hand=(POT_OF_GREED,) * mine_hand,
            their_hand=their_hand,
        )
        p0 = value(state, MINE).heuristic
        p1 = value(state, THEIRS).heuristic
        assert p0 == mine_hand * HAND_CARD_IN_LP
        assert p1 == their_hand * HAND_CARD_IN_LP
        assert p0 + p1 == (mine_hand + their_hand) * HAND_CARD_IN_LP
    # 3/3 일 때 둘 다 +600 이고 합이 +1200 이다 — 영합이면 0 이어야 한다.
    both = board(repository, my_hand=(POT_OF_GREED,) * 3, their_hand=3)
    assert value(both, MINE).heuristic == value(both, THEIRS).heuristic == 600


@pytest.mark.real_card
def test_14_a_deck_card_outweighs_a_hand_card(repository):
    """
    **STRUCTURAL-122 의 뿌리를 숫자로 적는다.**

    덱 한 장(300)이 패 한 장(200)보다 무겁다. 그래서 2장을 뽑으면

        덱 −600 + 패 +400 = **−200**

    이고, 발동한 카드가 패를 떠나는 것까지 치면 −400 이다. 드로우가 손해로
    읽히는 것이 이 두 상수의 **산술적 귀결**이고, 버그가 아니다.

    근거도 적혀 있다 — "지금 도달 가능한 패배 조건이 덱아웃 하나이므로,
    덱의 한 장은 패배로부터의 거리 1 이다". 그 근거는 Phase 3-B 측정
    시점에 옳았고, 전투가 들어온 뒤에도 그대로 쓰이고 있다.
    """
    assert DECK_CARD_IN_LP == 300
    assert HAND_CARD_IN_LP == 200
    assert DECK_CARD_IN_LP > HAND_CARD_IN_LP

    full = board(repository)
    assert term(full, "deck") == 0
    thin = board(repository)
    deck = thin.player(MINE).deck
    while len(deck) > 10:
        thin.move(deck.cards()[0], Zone.REMOVED, to_player=MINE)
    assert term(thin, "deck") == -10 * DECK_CARD_IN_LP


# ======================================================================
# §9 — Terminal
# ======================================================================


@pytest.mark.real_card
def test_15_terminal_always_beats_heuristic(repository):
    """
    **§9 — 패배 상태가 필드 우위 때문에 좋은 점수를 받지 않는다.**

    끝난 판은 휴리스틱을 아예 재지 않는다 (``heuristic == 0``, ``terms``
    비어 있음). 그리고 등급이 먼저 비교된다.
    """
    winning_shape = dict(mine=(LUSTER_DRAGON, LUSTER_DRAGON), my_lp=8000)

    ongoing = value(board(repository, **winning_shape, their_lp=100))
    assert ongoing.terminal is Terminal.ONGOING
    assert ongoing.heuristic > 10000

    # 필드가 유리한데 **졌다**.
    lost = board(repository, **winning_shape, their_lp=8000)
    lost.player(MINE).change_life(-8000)
    lost.set_result(THEIRS, "라이프 포인트가 0")
    defeat = value(lost)
    assert defeat.terminal is Terminal.LOSS
    assert defeat.heuristic == 0
    assert defeat.terms == ()
    assert defeat.ordering_key() < ongoing.ordering_key()

    # 필드가 불리한데 **이겼다**.
    won = board(repository, theirs=(LUSTER_DRAGON, LUSTER_DRAGON))
    won.player(THEIRS).change_life(-8000)
    won.set_result(MINE, "라이프 포인트가 0")
    victory = value(won)
    assert victory.terminal is Terminal.WIN
    assert victory.heuristic == 0
    assert victory.ordering_key() > ongoing.ordering_key()

    # 등급 순서가 설계대로다.
    assert (
        Terminal.WIN.rank
        > Terminal.ONGOING.rank
        > Terminal.DRAW.rank
        > Terminal.LOSS.rank
    )


# ======================================================================
# §12 — Search Ranking
# ======================================================================


def test_16_an_unscored_candidate_is_not_zero_and_not_a_loss():
    """
    **§12-3 · §12-4 — 시뮬레이션 실패를 0점이나 패배로 바꾸지 않는다.**

    점수가 없는 후보는 ``ordering_key`` 의 첫 항이 1 이라서 **점수가 있는
    모든 후보 뒤로** 간다. 패배 후보는 첫 항이 0 이므로 비교에 들어간다 —
    "견줄 수 없다" 와 "나쁘다" 가 구분된다.
    """
    scored = SearchCandidate(
        action=PlayerAction.end_phase(actor=MINE),
        status=SimulationStatus.SUPPORTED,
        value=StateValue(terminal=Terminal.ONGOING, heuristic=0),
    )
    losing = SearchCandidate(
        action=PlayerAction.passing(actor=MINE),
        status=SimulationStatus.SUPPORTED,
        value=StateValue(terminal=Terminal.LOSS, heuristic=0),
    )
    unscored = SearchCandidate(
        action=PlayerAction.normal_summon(MINE, InstanceId(99)),
        status=SimulationStatus.UNKNOWN,
        value=None,
        reason="규칙 계층이 없다",
    )

    assert unscored.value is None
    assert unscored.ordering_key()[0] == 1
    assert scored.ordering_key()[0] == losing.ordering_key()[0] == 0
    assert not unscored.comparable

    order = sorted((unscored, losing, scored), key=lambda c: c.ordering_key())
    assert [c.status for c in order] == [
        SimulationStatus.SUPPORTED,
        SimulationStatus.SUPPORTED,
        SimulationStatus.UNKNOWN,
    ]
    assert order[0] is scored and order[1] is losing


@pytest.mark.real_card
def test_17_every_candidate_is_scored_by_the_same_yardstick(repository):
    """
    **§12-1 · §12-2 — 행위 종류와 대상이 달라도 같은 자로 잰다.**

    후보마다 다른 평가자를 쓰지 않는다. 그리고 동점은 ``canonical_state``
    로 갈라서 결정론적이다 (§12-5).
    """
    state = board(
        repository,
        mine=(LUSTER_DRAGON, BATTLE_OX),
        my_hand=(POT_OF_GREED, RUTHLESS_DENIAL),
        their_hand=2,
    )
    duel = duel_of(state)
    policy = search_policy(duel)
    policy.decide(duel.view(MINE), duel.legal_actions(MINE))
    decision = policy.last_decision

    kinds = {c.action.kind for c in decision.candidates}
    assert len(kinds) >= 3, kinds
    assert all(c.value is not None for c in decision.candidates)
    assert all(
        c.value.terminal is Terminal.ONGOING for c in decision.candidates
    )

    # 같은 상태에서 되풀이하면 같은 선택이다.
    first = search_policy(duel_of(state)).decide(
        GameStateView.from_state(state, viewer=MINE),
        duel_of(state).legal_actions(MINE),
    )
    for _ in range(3):
        again = search_policy(duel_of(state)).decide(
            GameStateView.from_state(state, viewer=MINE),
            duel_of(state).legal_actions(MINE),
        )
        assert again.canonical_state() == first.canonical_state()


# ======================================================================
# §11 · §13 — 대상 선택과 시나리오
# ======================================================================


@pytest.mark.real_card
def test_18_different_targets_score_by_their_result_not_their_identity(
    repository,
):
    """
    **§11 — 대상의 ``instance_id`` 가 아니라 결과 상태를 본다.**

    무정한 말살로 공격력 1900 을 보내는 미래와 1700 을 보내는 미래의 차이가
    **정확히 200** 이다 — 남는 몬스터의 공격력 차이이고, 대상 번호와 무관하다.
    """
    state = board(
        repository,
        mine=(LUSTER_DRAGON, BATTLE_OX),
        my_hand=(RUTHLESS_DENIAL,),
        their_hand=2,
    )
    duel = duel_of(state)
    simulator = Simulator(duel)

    scored = {}
    for action in duel.legal_actions(MINE).allowed:
        if action.kind is not PlayerActionKind.ACTIVATE_EFFECT:
            continue
        instance = action.instance_targets()[0]
        result = simulator.simulate(action, viewer=MINE)
        assert result.status is SimulationStatus.SUPPORTED
        scored[duel.state.find_instance(instance).card_id] = EV.evaluate(
            result.future
        ).heuristic

    assert set(scored) == {LUSTER_DRAGON, BATTLE_OX}
    # 약한 쪽(1700)을 보내는 미래가 더 좋고, 차이가 공격력 차이와 같다.
    assert scored[BATTLE_OX] - scored[LUSTER_DRAGON] == 1900 - 1700 == 200


@pytest.mark.real_card
@pytest.mark.parametrize(
    "label,shape,kind,expected_sign",
    [
        ("이기는 공격", dict(mine=(LUSTER_DRAGON,), theirs=(KOJIKOCY,)), PlayerActionKind.ATTACK, +1),
        ("지는 공격", dict(mine=(KOJIKOCY,), theirs=(LUSTER_DRAGON,)), PlayerActionKind.ATTACK, -1),
        ("다이렉트 어택", dict(mine=(LUSTER_DRAGON,)), PlayerActionKind.ATTACK, +1),
        ("일반 소환", dict(my_hand=(LUSTER_DRAGON,)), PlayerActionKind.NORMAL_SUMMON, +1),
        ("몬스터 세트", dict(my_hand=(LUSTER_DRAGON,)), PlayerActionKind.SET_MONSTER, +1),
    ],
)
def test_19_the_score_moves_the_same_direction_as_the_board(
    repository, label, shape, kind, expected_sign
):
    """
    **§13 · §16-① · §16-② — 좋아진 판에 낮은 점수를 주지 않는다.**

    다섯 시나리오에서 **시뮬레이션 점수와 실제 적용 뒤 점수가 같고**,
    변화의 방향이 판의 변화와 일치한다.
    """
    phase = (
        Phase.BATTLE if kind is PlayerActionKind.ATTACK else Phase.MAIN1
    )
    state = board(repository, **shape, phase=phase)
    duel = duel_of(state)
    before = EV.evaluate(duel.view(MINE))

    action = next(
        (a for a in duel.legal_actions(MINE).allowed if a.kind is kind), None
    )
    assert action is not None, f"{label}: 후보가 없다"

    simulated = EV.evaluate(Simulator(duel).simulate(action, viewer=MINE).future)
    assert duel.apply(action).accepted, label
    after = EV.evaluate(duel.view(MINE))

    # ① 해 본 것과 실제로 한 것이 같다.
    assert simulated.ordering_key() == after.ordering_key(), label
    # ② 방향이 판의 변화와 맞다.
    delta = after.heuristic - before.heuristic
    assert delta * expected_sign > 0, (label, before.heuristic, after.heuristic)


# ======================================================================
# §17 · §18 — 두 정책은 같은 자를 쓰지 않는다 (STRUCTURAL-123)
# ======================================================================


@pytest.mark.real_card
def test_20_the_two_policies_measure_different_quantities(repository):
    """
    **STRUCTURAL-123 — 구조적 차이를 숫자로 적는다.**

    ``RuleBasedPolicy`` 는 **지금 판의 카드 수치**를 세고
    (``BOARD_PRESENCE`` 10,000,000 · ``ATK_WEIGHT`` 1000),
    ``SearchPolicy`` 는 **미래 관측을 LP 로 환산**한다
    (``MONSTER_IN_LP`` 500 · ``ATK_IN_LP`` 1).

    단위도 자릿수도 다르므로 **두 점수를 견줄 수 없다.** 어느 쪽이 옳은지를
    말하는 것이 아니라, 둘이 같은 척도가 아니라는 사실을 적는다.

    그 결과: 규칙 기반은 규칙이 보지 않는 후보 전부에 0 을 주고, 0 끼리는
    ``canonical_state`` 순서로 갈린다 — 알파벳 순서가 정책이 된다.
    """
    from agent.heuristic import ATK_WEIGHT, BOARD_PRESENCE

    assert BOARD_PRESENCE == 10_000_000 and ATK_WEIGHT == 1000
    assert MONSTER_IN_LP == 500 and ATK_IN_LP == 1
    assert BOARD_PRESENCE / MONSTER_IN_LP == 20_000

    state = board(repository, my_hand=(POT_OF_GREED,))
    duel = duel_of(state)
    legal = duel.legal_actions(MINE)

    rules = rule_based_policy()
    appraisals = {e.action.kind: e for e in rules.evaluate(duel.view(MINE), legal)}
    # 규칙 기반은 발동과 세트에 **아무 규칙도 적용하지 않는다.**
    for kind in (PlayerActionKind.ACTIVATE_EFFECT, PlayerActionKind.SET_SPELL_TRAP):
        assert appraisals[kind].total == 0
        assert appraisals[kind].appraisals == ()
    assert appraisals[PlayerActionKind.END_PHASE].total == 0

    # 탐색은 같은 후보들에 **서로 다른** 점수를 준다.
    policy = search_policy(duel_of(state))
    policy.decide(duel.view(MINE), duel_of(state).legal_actions(MINE))
    scores = {
        c.action.kind: c.value.heuristic for c in policy.last_decision.candidates
    }
    assert len({scores[k] for k in scores}) > 1, scores

    # 그래서 선택이 갈린다.
    rule_choice = rule_based_policy().decide(duel.view(MINE), legal)
    search_choice = policy.last_decision.chosen
    assert rule_choice.kind is PlayerActionKind.ACTIVATE_EFFECT
    assert search_choice.kind is not PlayerActionKind.ACTIVATE_EFFECT
    assert "activate_effect" < "end_phase" < "set_spell_trap"


@pytest.mark.real_card
def test_21_search_declines_a_losing_attack_that_the_rules_take(repository):
    """
    **§18 — 두 정책이 갈리는 자리를 관측만 기록한다.** 승패를 선언하지 않는다.

    공격력 1500 이 1900 을 공격하면 내 몬스터가 파괴된다. 규칙 기반은
    공격을 고르고(규칙에 "지는 공격을 피한다" 가 없다), 탐색은 미래를 보고
    턴을 넘긴다.

    **어느 쪽이 옳다고 적지 않는다.** 다만 이 자리에서 두 정책의 차이가
    "척도의 차이" 가 아니라 **"미래를 보는가" 의 차이**임을 분해해 둔다.
    """
    state = board(
        repository,
        mine=(KOJIKOCY,),
        theirs=(LUSTER_DRAGON,),
        phase=Phase.BATTLE,
    )
    legal = duel_of(state).legal_actions(MINE)

    rule_choice = rule_based_policy().decide(
        GameStateView.from_state(state, viewer=MINE), legal
    )
    assert rule_choice.kind is PlayerActionKind.ATTACK

    policy = search_policy(duel_of(state))
    search_choice = policy.decide(
        GameStateView.from_state(state, viewer=MINE),
        duel_of(state).legal_actions(MINE),
    )
    assert search_choice.kind is PlayerActionKind.END_PHASE

    scores = {
        c.action.kind: c.value.heuristic for c in policy.last_decision.candidates
    }
    # 공격한 미래가 턴을 넘긴 미래보다 낮다 — 그것이 탐색이 피한 이유다.
    assert scores[PlayerActionKind.ATTACK] < scores[PlayerActionKind.END_PHASE]
