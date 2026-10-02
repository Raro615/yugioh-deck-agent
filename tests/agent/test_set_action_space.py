"""
Phase 3-E-2 — SET Action Space (AI 쪽).

    legal_actions          세트가 **후보**에 오르는가
      ↓
    Simulator              세트를 **해 볼** 수 있는가 (실제 판은 그대로)
      ↓
    StateEvaluator         세트한 미래에 **점수**가 붙는가
      ↓
    SearchPolicy           AI 가 **고르는가**
      ↓
    Duel.apply             실제로 **일어나는가**

네 가지를 하나로 뭉치지 않는다
------------------------------
**후보에 올랐다 ≠ 해 봤다 ≠ 골랐다 ≠ 실제로 일어났다.** 이 파일의 셈은
전부 넷을 따로 센다 — 뭉치면 "AI 가 세트를 쓴다" 가 측정이 아니라 인상이
된다. 실제로 이 Phase 의 가장 중요한 측정 결과가 그 차이에서 나온다:
``SET_MONSTER`` 는 **후보에 오르지만 탐색도 규칙 기반도 고르지 않는다.**

세트에 가산점을 주지 않는다
---------------------------
"AI 가 세트를 고르게 하려고" 평가에 보너스를 넣으면 그 뒤의 어떤 측정도
의미가 없어진다 (§9 · §15). 그래서 ``agent/`` 어디에도 세트의 이름이
없다는 것을 AST 로 지킨다 — 금지가 아니라 **불가능**으로 만든다.
"""

import ast
import collections
import inspect
import pathlib
import re

import pytest

from agent import (
    FirstLegalPolicy,
    RandomPolicy,
    play,
    rule_based_policy,
    search_policy,
)
from agent.arena import make_random, make_rule_based, make_search, run_series, summarize
from agent.evaluation import StateEvaluator
from agent.search import SearchPolicy
from agent.simulation import SimulationStatus, Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.priority import PriorityState
from engine.set_card import CardSet
from engine.state.game_state import GameState
from engine.state.rule_usage import RuleActionKind
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

LUSTER_DRAGON = 11091375  # 몬스터 · 레벨 4 · ATK 1900 / DEF 1600
BATTLE_OX = 5053103  # 몬스터 · 레벨 4 · ATK 1700 / DEF 1000
DARK_HOLE = 53129443  # 마법
TRAP_HOLE = 4206964  # 함정

#: 세트가 나오려면 패에 몬스터와 마법이 **둘 다** 있어야 한다.
DECK = ([LUSTER_DRAGON] * 8 + [DARK_HOLE] * 6 + [BATTLE_OX] * 6)
DECKS = (DECK, DECK)
SEEDS = (1, 2, 3, 4, 5, 6, 7, 8)


# ======================================================================
# 판 만들기 — 전부 실제 엔진으로
# ======================================================================


def staged(repository, *, hand, phase: Phase = Phase.MAIN1, turn: int = 1) -> Duel:
    """
    패를 지정한 메인 페이즈의 듀얼 하나.

    배치는 :meth:`GameState.create_instance` — 가짜 상태가 아니라는 것은
    :func:`test_01_a_staged_hand_is_one_the_engine_itself_accepts` 가 엔진에게
    직접 물어 확인한다.
    """
    state = GameState.create(repository, decks=(list(DECK), list(DECK)))
    for card_id in hand:
        state.create_instance(card_id, owner=MINE, zone=Zone.HAND)
    state.turn.turn_number = turn
    state.turn.turn_player = MINE
    state.turn.set_phase(phase)
    return Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=phase),
    )


def of_kind(duel: Duel, kind: PlayerActionKind, seat: int = MINE):
    return [a for a in duel.legal_actions(seat).allowed if a.kind is kind]


def snapshot(duel: Duel) -> tuple:
    """바뀔 수 있는 자리 전부 — 시뮬레이션이 실제 판을 건드렸는지 볼 때."""
    return (
        duel.state.state_hash(),
        duel.state.randomness.draws if duel.state.seed is not None else None,
        duel.state.turn.turn_number,
        duel.state.turn.phase,
        duel.step,
        duel.priority,
        duel.result,
        duel.state.rule_uses.canonical_state(),
        tuple(
            (
                duel.state.player(seat).life_points,
                tuple(
                    tuple(c.instance_id.value for c in duel.state.player(seat).zone(z))
                    for z in (
                        Zone.DECK, Zone.HAND, Zone.MZONE,
                        Zone.SZONE, Zone.GRAVE, Zone.REMOVED,
                    )
                ),
                tuple(
                    (c.instance_id.value, c.position.value)
                    for c in duel.state.player(seat).monster_zone
                ),
            )
            for seat in (MINE, THEIRS)
        ),
    )


def census(repository, factories, *, seeds=SEEDS, limit: int = 4000):
    """
    실제 듀얼을 끝까지 굴리며 **네 가지를 따로** 센다.

    ``legal`` 후보에 올랐다 · ``selected`` AI 가 골랐다 · ``executed`` 엔진이
    받아들였다 · ``positions`` 판에 실제로 나타난 표시 형식.
    """
    legal: collections.Counter = collections.Counter()
    selected: collections.Counter = collections.Counter()
    executed: collections.Counter = collections.Counter()
    positions = set()
    for seed in seeds:
        duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=seed)
        policies = [factory(duel, seat) for seat, factory in enumerate(factories)]
        for _ in range(limit):
            if duel.is_over:
                break
            if duel.advance() is not None:
                continue
            seat = duel.to_act
            allowed = duel.legal_actions(seat)
            if not allowed.allowed:
                break
            for action in allowed.allowed:
                legal[action.kind.value] += 1
            for side in (MINE, THEIRS):
                for card in duel.state.player(side).monster_zone:
                    positions.add(card.position.value)
            chosen = policies[seat].decide(duel.view(seat), allowed)
            selected[chosen.kind.value] += 1
            if duel.apply(chosen).accepted:
                executed[chosen.kind.value] += 1
    return legal, selected, executed, positions


# ======================================================================
# 1~5. 후보 (§12 · §13)
# ======================================================================


@pytest.mark.real_card
def test_01_a_staged_hand_is_one_the_engine_itself_accepts(repository):
    """만들어 둔 판이 가짜가 아니다 — 엔진이 그 판에서 직접 허가를 낸다."""
    duel = staged(repository, hand=(LUSTER_DRAGON, DARK_HOLE))
    kinds = {a.kind for a in duel.legal_actions(MINE).allowed}
    assert PlayerActionKind.SET_MONSTER in kinds
    assert PlayerActionKind.SET_SPELL_TRAP in kinds
    assert PlayerActionKind.NORMAL_SUMMON in kinds
    assert PlayerActionKind.END_PHASE in kinds


@pytest.mark.real_card
def test_02_both_set_kinds_appear_in_a_real_duel(repository):
    """
    **실제로 굴린 듀얼**에서 두 세트가 모두 후보에 오른다 (§12).

    만들어 둔 판이 아니라 ``Duel.start`` 로 시작해 정책이 둔 수로 도달한
    자리에서 센다.
    """
    legal, _, _, _ = census(
        repository, (make_rule_based(), make_rule_based()), seeds=SEEDS[:4]
    )
    assert legal["set_monster"] > 0, dict(legal)
    assert legal["set_spell_trap"] > 0, dict(legal)


@pytest.mark.real_card
def test_03_every_hand_card_gets_its_own_candidate(repository):
    """
    같은 이름 두 장은 **서로 다른 후보**다 — 카드 이름이 아니라 instance 로
    식별한다. 뭉치면 "어느 장을 세트했는지" 를 말할 수 없다.
    """
    duel = staged(repository, hand=(LUSTER_DRAGON, LUSTER_DRAGON, DARK_HOLE))
    hand = [c.instance_id for c in duel.state.player(MINE).hand]
    assert len(set(hand)) == len(hand)

    sets = of_kind(duel, PlayerActionKind.SET_MONSTER)
    assert {a.source for a in sets} == {
        c.instance_id for c in duel.state.player(MINE).hand
        if c.definition is not None and c.definition.is_monster
    }
    assert len(sets) == 2
    spell_sets = of_kind(duel, PlayerActionKind.SET_SPELL_TRAP)
    assert len(spell_sets) == 1


@pytest.mark.real_card
def test_04_one_hand_monster_yields_both_a_summon_and_a_set(repository):
    """
    **한 장이 두 후보를 만든다** — 소환과 세트는 다른 행위다
    (RULE-SUMMON-010). 하나로 합치면 AI 가 표시 형식을 고를 수 없다.
    """
    duel = staged(repository, hand=(LUSTER_DRAGON,))
    source = duel.state.player(MINE).hand[0].instance_id

    summon = of_kind(duel, PlayerActionKind.NORMAL_SUMMON)
    setting = of_kind(duel, PlayerActionKind.SET_MONSTER)
    assert [a.source for a in summon] == [source]
    assert [a.source for a in setting] == [source]
    assert summon[0] != setting[0]
    assert summon[0].canonical_state() != setting[0].canonical_state()


@pytest.mark.real_card
def test_05_the_set_candidates_vanish_when_the_right_is_spent(repository):
    """
    소환권을 쓰면 **몬스터 세트 후보가 사라지고** 마법 세트는 남는다
    (RULE-SUMMON-009).
    """
    duel = staged(repository, hand=(LUSTER_DRAGON, BATTLE_OX, DARK_HOLE))
    first = of_kind(duel, PlayerActionKind.SET_MONSTER)[0]
    assert duel.apply(first).accepted

    assert of_kind(duel, PlayerActionKind.SET_MONSTER) == []
    assert of_kind(duel, PlayerActionKind.NORMAL_SUMMON) == []
    assert len(of_kind(duel, PlayerActionKind.SET_SPELL_TRAP)) == 1


@pytest.mark.real_card
def test_06_the_set_candidates_vanish_outside_the_main_phase(repository):
    """세트는 메인 페이즈의 행위다 (RULE-TURN-004 · RULE-TURN-006)."""
    for phase in (Phase.DRAW, Phase.STANDBY, Phase.END):
        duel = staged(repository, hand=(LUSTER_DRAGON, DARK_HOLE), phase=phase)
        kinds = {a.kind for a in duel.legal_actions(MINE).allowed}
        assert PlayerActionKind.SET_MONSTER not in kinds, phase
        assert PlayerActionKind.SET_SPELL_TRAP not in kinds, phase


@pytest.mark.real_card
def test_07_a_full_spell_zone_removes_only_the_spell_set(repository):
    """존이 꽉 차면 그 세트만 사라진다 (§13)."""
    duel = staged(repository, hand=(LUSTER_DRAGON, DARK_HOLE))
    for _ in range(5):
        filler = duel.state.create_instance(TRAP_HOLE, owner=MINE, zone=Zone.HAND)
        duel.state.move(
            filler, Zone.SZONE, to_player=MINE, position=Position.FACEDOWN
        )

    kinds = {a.kind for a in duel.legal_actions(MINE).allowed}
    assert PlayerActionKind.SET_SPELL_TRAP not in kinds
    assert PlayerActionKind.SET_MONSTER in kinds


# ======================================================================
# 8~12. 시뮬레이션 (§14 · §16 · §17)
# ======================================================================


@pytest.mark.real_card
def test_08_the_simulator_supports_both_set_kinds(repository):
    """
    세트를 **해 볼 수 있다.** ``UNKNOWN`` 이 아니다.

    ``UNKNOWN`` 이면 그대로 둔다 — 자동으로 허가로 바꾸지 않는다. 지금은
    ``SUPPORTED`` 인 것이 사실이므로 그대로 적는다.
    """
    duel = staged(repository, hand=(LUSTER_DRAGON, DARK_HOLE))
    simulator = Simulator(duel)

    for kind in (PlayerActionKind.SET_MONSTER, PlayerActionKind.SET_SPELL_TRAP):
        action = of_kind(duel, kind)[0]
        result = simulator.simulate(action, viewer=MINE)
        assert result.status is SimulationStatus.SUPPORTED, kind
        assert result.future is not None
        assert isinstance(result.future, GameStateView)


@pytest.mark.real_card
def test_09_simulating_a_set_does_not_touch_the_real_duel(repository):
    """
    **SEARCH MUST NEVER CHANGE THE REAL GAME** (§16).

    소환권까지 본다 — 사본에서 쓴 권리가 원본에 남으면 그 턴의 실제 소환이
    조용히 막힌다.
    """
    duel = staged(repository, hand=(LUSTER_DRAGON, DARK_HOLE))
    simulator = Simulator(duel)
    before = snapshot(duel)

    for _ in range(3):
        for action in duel.legal_actions(MINE).allowed:
            simulator.simulate(action, viewer=MINE)

    assert snapshot(duel) == before
    assert not duel.state.rule_uses.used(1, MINE, RuleActionKind.NORMAL_SUMMON)


@pytest.mark.real_card
def test_10_the_simulated_set_really_happened_in_the_fork(repository):
    """
    사본에서는 **실제로** 일어난다 — 아무 일도 하지 않는 시뮬레이션이
    아니다. 뒷면 수비 표시가 사본의 몬스터 존에 있다.
    """
    duel = staged(repository, hand=(LUSTER_DRAGON,))
    action = of_kind(duel, PlayerActionKind.SET_MONSTER)[0]

    future = Simulator(duel).simulate(action, viewer=MINE).future
    placed = future.me.monster_zone.occupied()
    assert len(placed) == 1
    assert placed[0].position is Position.FACEDOWN_DEFENSE
    assert placed[0].instance_id == action.source
    assert len(duel.state.player(MINE).monster_zone) == 0


@pytest.mark.real_card
def test_11_the_simulation_matches_what_really_happens(repository):
    """
    **해 본 것과 실제로 한 것이 같다** (§17).

    다르면 탐색은 있지도 않은 미래를 보고 고르는 것이 된다.
    """
    duel = staged(repository, hand=(LUSTER_DRAGON, DARK_HOLE))
    action = of_kind(duel, PlayerActionKind.SET_MONSTER)[0]

    simulated = Simulator(duel).simulate(action, viewer=MINE).future
    assert duel.apply(action).accepted
    really = duel.view(MINE)

    assert simulated.canonical_state() == really.canonical_state()


@pytest.mark.real_card
def test_12_the_opponent_cannot_simulate_his_way_into_my_set(repository):
    """
    뒷면은 **시뮬레이션으로도** 새지 않는다 (§13 · ADR-007).

    상대 관점의 미래에서도 내가 세트한 카드의 정체가 보이지 않는다.
    """
    duel = staged(repository, hand=(LUSTER_DRAGON,))
    action = of_kind(duel, PlayerActionKind.SET_MONSTER)[0]

    theirs = Simulator(duel).simulate(action, viewer=THEIRS).future
    hidden = theirs.opponent.monster_zone.occupied()[0]
    assert hidden.instance_id == action.source
    assert hidden.card_id is None
    assert hidden.name is None
    assert hidden.definition is None
    assert hidden.position is Position.FACEDOWN_DEFENSE

    mine = Simulator(duel).simulate(action, viewer=MINE).future
    assert mine.me.monster_zone.occupied()[0].card_id == LUSTER_DRAGON


# ======================================================================
# 13~16. 평가 (§15) — 세트에 가산점이 없다
# ======================================================================


def test_13_the_agent_layer_does_not_know_the_word_set():
    """
    **구조적 보장**: ``agent/`` 어디에도 세트의 이름이 없다 (§9 · §15).

    **식별자 토큰을 뽑고, 토큰 안에서 찾는다.** 두 극단을 모두 피한다:

    - 원문 전체에서 문자열로 찾으면 설명문의 한국어 주석까지 걸린다.
    - 토큰이 금지어와 **정확히 같은지**만 보면 ``SET_MONSTER_BONUS`` 처럼
      **접두사로 쓴 것**을 놓친다. 실제로 이 시험을 처음 쓸 때 그렇게 했고,
      일부러 넣어 본 ``SET_MONSTER_BONUS = 0`` 을 잡지 못했다 — 그것이
      잘못된 가정이었다.

    금지어가 모두 길고 특징적이므로 (``set_monster`` · ``FACEDOWN`` 등)
    토큰 안에서 찾아도 ``set()`` · ``settings`` · ``supported`` 는 걸리지
    않는다. Phase 3-C 에서 ``ppo`` 가 ``supported`` 안에 걸린 사고는 금지어가
    **세 글자**였기 때문이고, 여기서는 그 조건이 없다.
    """
    forbidden = (
        "SET_MONSTER",
        "SET_SPELL_TRAP",
        "set_monster",
        "set_spell_trap",
        "CardSet",
        "FACEDOWN",
        "facedown",
        "monster_set",
    )
    for path in sorted((ROOT / "agent").glob("*.py")):
        tokens = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", path.read_text()))
        hits = {
            token
            for token in tokens
            for name in forbidden
            if name in token
        }
        assert not hits, (path.name, hits)

    # 이 시험이 실제로 무엇을 잡는지 확인한다 — 접두사로 숨긴 것도 잡는다.
    assert any(name in "SET_MONSTER_BONUS" for name in forbidden)
    # 그리고 무엇을 잡지 않는지도 확인한다 — 거짓 경보가 없다.
    for innocent in ("set", "settings", "supported", "offset", "dataset"):
        assert not any(name in innocent for name in forbidden), innocent


def test_14_the_evaluator_still_cannot_see_the_action():
    """
    세트가 들어와도 **평가는 행위를 보지 못한다** (Phase 3-C 의 구조적 보장).

    "SET 이면 점수를 더" 를 쓸 수가 없다 — 금지가 아니라 불가능이다.
    """
    signature = inspect.signature(StateEvaluator.evaluate)
    assert list(signature.parameters) == ["self", "view"]

    tree = ast.parse((ROOT / "agent/evaluation.py").read_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    for name in ("PlayerAction", "PlayerActionKind", "action", "kind"):
        assert name not in names, name


@pytest.mark.real_card
def test_15_the_evaluation_weights_are_unchanged(repository):
    """
    **STRUCTURAL-111 의 가중치를 건드리지 않았다** (§15).

    Phase 3-C 에서 실측으로 정한 값이다. 세트를 고르게 만들려고 여기를
    비틀면 그 뒤의 모든 측정이 의미를 잃는다.
    """
    from agent.evaluation import (
        ATK_IN_LP,
        DECK_CARD_IN_LP,
        HAND_CARD_IN_LP,
        MONSTER_IN_LP,
        SPELL_TRAP_IN_LP,
    )

    assert (ATK_IN_LP, MONSTER_IN_LP, SPELL_TRAP_IN_LP) == (1, 500, 300)
    assert (DECK_CARD_IN_LP, HAND_CARD_IN_LP) == (300, 200)


@pytest.mark.real_card
def test_16_setting_a_spell_scores_above_passing(repository):
    """
    세트에 **점수가 붙는다** — 가산점이 아니라 미래의 판에서 나온 값이다.

    마법을 세트하면 패 한 장(200)이 마법 존 한 장(300)이 되므로 턴을 넘기는
    것보다 100 만큼 높다. 이 100 은 세트라서 준 것이 아니라 **판이 달라져서**
    생긴 것이다.
    """
    duel = staged(repository, hand=(DARK_HOLE,))
    simulator, evaluator = Simulator(duel), StateEvaluator()

    setting = of_kind(duel, PlayerActionKind.SET_SPELL_TRAP)[0]
    ending = of_kind(duel, PlayerActionKind.END_PHASE)[0]
    after_set = evaluator.evaluate(simulator.simulate(setting, viewer=MINE).future)
    after_end = evaluator.evaluate(simulator.simulate(ending, viewer=MINE).future)

    assert after_set.heuristic == after_end.heuristic + 100
    assert dict(after_set.terms)["spells"] == 300
    assert dict(after_end.terms)["spells"] == 0


@pytest.mark.real_card
def test_17_the_evaluator_no_longer_contradicts_itself_about_a_face_down_monster(
    repository,
):
    """
    **STRUCTURAL-115 가 풀린 자리다** (Phase 3-E-6).

    Phase 3-E-2 에서 이 시험은 그 반대를 적었다 — 평가가 뒷면 몬스터에 대해
    두 가지를 **동시에** 말한다고:

        atk 항   1900   — 뒷면 몬스터의 공격력을 세었다
        excluded "내 뒷면 카드 N장은 값을 매기지 않았다"

    둘 다 참일 수 없었고, 그래서 ``set_monster`` 와 ``normal_summon`` 의
    점수가 정확히 같았다. 그 설명에 **"올바른 셈이 무엇인지는 설계 결정"**
    이라고 적어 두었고, Phase 3-E-6 이 그 결정을 내렸다 — 모듈 설명이 이미
    의도라고 적고 있던 쪽(뒷면의 공격력을 세지 않는다)으로 코드를 맞췄다.

    그래서 주장을 뒤집는다. 약화가 아니라 **모순의 해소**다.

    1. 뒷면 몬스터는 ``atk`` 에 들어가지 않는다 (0)
    2. 자리에 있다는 값(``monsters`` 500)은 **그대로 센다** — 뒷면도 칸을
       차지하고 나중에 쓸 수 있다
    3. ``excluded`` 가 이제 **사실**을 말한다 — "공격력은 세지 않았다"
    4. 그래서 ``set_monster`` 가 ``normal_summon`` 보다 **낮다**
    """
    duel = staged(repository, hand=(LUSTER_DRAGON,))
    simulator, evaluator = Simulator(duel), StateEvaluator()

    summon = of_kind(duel, PlayerActionKind.NORMAL_SUMMON)[0]
    setting = of_kind(duel, PlayerActionKind.SET_MONSTER)[0]
    after_summon = evaluator.evaluate(simulator.simulate(summon, viewer=MINE).future)
    after_set = evaluator.evaluate(simulator.simulate(setting, viewer=MINE).future)

    # 1 · 2 — 공격력은 빠지고 자리의 값은 남는다.
    assert dict(after_set.terms)["atk"] == 0
    assert dict(after_set.terms)["monsters"] == 500
    assert dict(after_summon.terms)["atk"] == 1900

    # 3 — 보고가 사실이다.
    assert any("공격력은 세지 않았다" in note for note in after_set.notes)
    assert not any("값을 매기지 않았다" in note for note in after_set.notes)
    assert after_summon.excluded == ()

    # 4 — 두 수가 구별된다. 차이가 정확히 그 카드의 공격력이다.
    assert after_summon.heuristic - after_set.heuristic == 1900

    # 상대 관점도 그대로 일관된다 — 보이지 않는 것을 세지 않는다.
    theirs = evaluator.evaluate(simulator.simulate(setting, viewer=THEIRS).future)
    assert dict(theirs.terms)["atk"] == 0
    assert any("모른다" in note for note in theirs.notes), theirs.excluded


# ======================================================================
# 18~22. 탐색이 고르는가 (§14 · §18)
# ======================================================================


@pytest.mark.real_card
def test_18_search_selects_a_spell_set_when_it_is_the_best_future(repository):
    """
    **탐색이 세트를 고른다** — 마법 세트 쪽이다. 하드코딩이 아니라 미래의
    점수가 높아서 고른다.
    """
    duel = staged(repository, hand=(DARK_HOLE,))
    policy = search_policy(duel)

    chosen = policy.decide(duel.view(MINE), duel.legal_actions(MINE))
    assert chosen.kind is PlayerActionKind.SET_SPELL_TRAP
    assert len(policy.last_decision.candidates) >= 2
    picked = next(
        c for c in policy.last_decision.candidates if c.action == chosen
    )
    assert picked.status is SimulationStatus.SUPPORTED
    assert picked.value is not None


@pytest.mark.real_card
def test_19_the_set_the_search_chose_really_executes(repository):
    """
    **고른 것이 실제로 일어난다** (§14). 후보에 있는 것 ≠ 일어난 것.
    """
    duel = staged(repository, hand=(DARK_HOLE,))
    policy = search_policy(duel)
    chosen = policy.decide(duel.view(MINE), duel.legal_actions(MINE))

    step = duel.apply(chosen)
    assert step.accepted, step.reason
    placed = list(duel.state.player(MINE).spell_zone)
    assert len(placed) == 1
    assert placed[0].position is Position.FACEDOWN
    assert placed[0].instance_id == chosen.source


@pytest.mark.real_card
def test_20_search_does_not_select_a_monster_set_and_we_say_why(repository):
    """
    **고르지 않는다는 사실을 숨기지 않는다** (§18 · §33).

    후보에는 오르고 시뮬레이션도 되지만 고르지 않는다. **이유가 Phase 3-E-6
    에서 달라졌다.**

    예전(3-E-2): 점수가 일반 소환과 **같았고**(둘 다 2400) ``canonical_state``
    순서에서 ``normal_summon`` 이 이겼다 — 즉 평가가 두 수를 구별하지 못한
    결과였다 (STRUCTURAL-115).

    지금(3-E-6): 평가가 두 수를 **구별한다.** 뒷면 몬스터의 공격력을 세지
    않으므로 ``set_monster`` 가 정확히 그 공격력만큼 낮다. 그래서 탐색이
    **점수를 보고** 일반 소환을 고른다 — 순서가 아니라 평가가 정한다.

    이것을 "AI 가 세트를 쓴다" 로 적지 않는다. 세트를 고르게 만들려면 뒷면
    수비 표시의 값(수비력 · 정보 은닉)을 세는 항이 필요하고, 그 설계는 이
    Phase 의 범위가 아니다 (Phase 3-E-5 §9 가 가중치 설계를 별도 Phase 로
    미뤄 두었다).
    """
    duel = staged(repository, hand=(LUSTER_DRAGON,))
    policy = search_policy(duel)
    chosen = policy.decide(duel.view(MINE), duel.legal_actions(MINE))

    assert chosen.kind is PlayerActionKind.NORMAL_SUMMON
    candidates = {c.action.kind: c for c in policy.last_decision.candidates}
    assert PlayerActionKind.SET_MONSTER in candidates
    monster_set = candidates[PlayerActionKind.SET_MONSTER]
    assert monster_set.status is SimulationStatus.SUPPORTED
    assert monster_set.value is not None

    summon = candidates[PlayerActionKind.NORMAL_SUMMON]
    # **점수가 갈린다** — 예전에는 같았다.
    assert monster_set.value.heuristic < summon.value.heuristic
    assert summon.value.heuristic - monster_set.value.heuristic == 1900

    # 그래서 순서가 아니라 점수가 결정한다 — 동점 타이브레이크에 닿지 않는다.
    assert summon.ordering_key()[:3] < monster_set.ordering_key()[:3]


@pytest.mark.real_card
def test_21_the_rule_based_policy_loses_the_set_by_exactly_one_rule(repository):
    """
    **왜 규칙 기반 정책이 세트를 고르지 않는가** — 측정한 그대로 적는다.

    두 세트가 서로 다른 이유로 진다.

    ``SET_MONSTER``
        능력치 규칙 둘(``higher-attack-first`` · ``higher-defence-breaks-tie``)
        은 세트 후보에도 값을 준다 — 놓는 카드가 몬스터이므로 그 규칙이 볼
        것이 있다. 값을 주지 않는 것은 ``summon-before-ending`` 하나이고
        (``BOARD_KINDS`` 가 ``{NORMAL_SUMMON}`` 뿐이다), 그 하나의 무게가
        ``BOARD_PRESENCE`` = 10,000,000 이다. 그래서 같은 카드의 일반 소환이
        **정확히 그 값만큼** 앞선다.

    ``SET_SPELL_TRAP``
        어떤 규칙도 보지 않는다 (``abstained`` 가 전부). 총점 0 으로
        ``END_PHASE`` 와 동점이 되고 ``canonical_state`` 순서에서 진다.

    세트를 보는 규칙을 새로 넣어 고치지 않는다 — 그러면 "AI 가 세트를
    고른다" 가 측정이 아니라 주문이 된다 (§9 · §15).
    """
    from agent.heuristic import BOARD_PRESENCE

    duel = staged(repository, hand=(LUSTER_DRAGON, DARK_HOLE))
    policy = rule_based_policy()
    evaluations = {
        e.action.kind: e
        for e in policy.evaluate(duel.view(MINE), duel.legal_actions(MINE))
    }

    monster_set = evaluations[PlayerActionKind.SET_MONSTER]
    summon = evaluations[PlayerActionKind.NORMAL_SUMMON]
    assert summon.total - monster_set.total == BOARD_PRESENCE
    assert "summon-before-ending" in monster_set.abstained
    assert "summon-before-ending" not in summon.abstained

    spell_set = evaluations[PlayerActionKind.SET_SPELL_TRAP]
    assert spell_set.total == 0
    assert spell_set.appraisals == ()
    assert len(spell_set.abstained) == len(policy.considerations)
    assert evaluations[PlayerActionKind.END_PHASE].total == 0
    assert "end_phase" < "set_spell_trap"

    chosen = policy.decide(duel.view(MINE), duel.legal_actions(MINE))
    assert chosen.kind is PlayerActionKind.NORMAL_SUMMON


@pytest.mark.real_card
def test_22_a_random_policy_does_select_and_execute_both_sets(repository):
    """
    **고르는 정책을 쓰면 둘 다 실제로 일어난다.**

    이것이 "엔진은 할 수 있다" 와 "이 AI 는 고르지 않는다" 를 가르는 자리다.
    """
    legal, selected, executed, positions = census(
        repository,
        (make_random(seed=31), make_random(seed=32)),
        seeds=SEEDS[:4],
    )
    for kind in ("set_monster", "set_spell_trap"):
        assert legal[kind] > 0, dict(legal)
        assert selected[kind] > 0, dict(selected)
        assert executed[kind] == selected[kind], (kind, dict(selected), dict(executed))
    assert Position.FACEDOWN_DEFENSE.value in positions, positions


# ======================================================================
# 23~26. 통계 · STRUCTURAL-108 (§18 · §20 · §22)
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize(
    "label,factories",
    [
        ("search-vs-search", (make_search(), make_search())),
        ("search-vs-rule", (make_search(), make_rule_based())),
        ("random-vs-random", (make_random(seed=5), make_random(seed=6))),
    ],
)
def test_23_every_matchup_still_finishes_with_the_set_space_open(
    repository, label, factories
):
    """
    행동 공간이 넓어졌는데도 **모든 판이 끝난다** — 거절도 예외도 상한도 없다.
    """
    results = run_series(repository, decks=DECKS, seeds=SEEDS[:4], factories=factories)
    summary = summarize(results)

    assert summary.all_completed, label
    assert summary.refusals == 0 and summary.errors == 0 and summary.limits == 0
    assert summary.actions > 0


@pytest.mark.real_card
def test_24_the_two_set_kinds_are_counted_separately(repository):
    """
    **``SET_MONSTER`` 와 ``SET_SPELL_TRAP`` 을 합치지 않는다** (§18).

    합치면 "세트가 N번 일어났다" 가 되는데, 그 N 안에서 하나는 한 번도
    선택되지 않았다는 사실이 사라진다.
    """
    legal, selected, executed, _ = census(
        repository, (make_search(), make_search()), seeds=SEEDS[:4]
    )

    assert legal["set_monster"] > 0
    assert legal["set_spell_trap"] > 0
    # 탐색은 마법 세트만 고른다 — 둘을 합치면 이 사실이 보이지 않는다.
    assert selected["set_monster"] == 0, dict(selected)
    assert selected["set_spell_trap"] > 0, dict(selected)
    assert executed["set_spell_trap"] == selected["set_spell_trap"]
    assert set(legal) != set(selected)


@pytest.mark.real_card
def test_25_structural_108_is_resolved_for_set_but_not_for_change_position(
    repository,
):
    """
    **STRUCTURAL-108 의 어느 절반이 풀렸는지 적는다** (§22).

    풀린 쪽: 뒷면 수비 표시를 만드는 길이 생겼다 (``SET_MONSTER``).
    남은 쪽: 이미 놓인 몬스터의 표시 형식을 바꾸는 길은 없다
    (``CHANGE_POSITION`` · Flip Summon — §24 가 범위 밖으로 두었다).
    """
    legal, _, _, positions = census(
        repository, (make_random(seed=41), make_random(seed=42)), seeds=SEEDS[:4]
    )

    assert legal["set_monster"] > 0
    assert Position.FACEDOWN_DEFENSE.value in positions
    assert legal.get("change_position", 0) == 0, dict(legal)


@pytest.mark.real_card
def test_26_a_set_leaves_its_own_kind_of_delta_in_the_transcript(repository):
    """
    기록에 **세트로** 남는다 — 소환으로 남지 않는다 (STRUCTURAL-113).
    """
    from engine.effect.delta import MonsterSummoned
    from engine.summon import duel_executor
    from engine.action_validation import ValidationResult

    duel = staged(repository, hand=(LUSTER_DRAGON, DARK_HOLE))
    deltas = []
    for kind in (PlayerActionKind.SET_MONSTER, PlayerActionKind.SET_SPELL_TRAP):
        action = of_kind(duel, kind)[0]
        executed = duel_executor().execute(
            duel.state, action, authorization=ValidationResult.valid()
        )
        deltas.extend(executed.deltas)

    assert len(deltas) == 2
    assert all(isinstance(d, CardSet) for d in deltas)
    assert not any(isinstance(d, MonsterSummoned) for d in deltas)
    assert [d.to_dict()["summoned"] for d in deltas] == [False, False]


# ======================================================================
# 27~29. 결정론 · 재현 (§16)
# ======================================================================


@pytest.mark.real_card
def test_27_the_same_seed_gives_the_same_duel_with_sets_open(repository):
    """같은 씨앗이면 같은 듀얼이다 — 세트가 들어와도 재현된다."""
    from agent.arena import run_match

    first = run_match(repository, decks=DECKS, seed=4, factories=(make_search(), make_search()))
    second = run_match(repository, decks=DECKS, seed=4, factories=(make_search(), make_search()))
    assert first.canonical_state() == second.canonical_state()
    assert [r.action for r in first.decisions] == [r.action for r in second.decisions]


@pytest.mark.real_card
def test_28_the_search_policy_decides_the_same_way_every_time(repository):
    """같은 판 · 같은 후보면 **언제나 같은 세트**를 고른다."""
    duel = staged(repository, hand=(DARK_HOLE, TRAP_HOLE))
    view, legal = duel.view(MINE), duel.legal_actions(MINE)

    first = search_policy(duel).decide(view, legal)
    for _ in range(5):
        assert search_policy(duel).decide(view, legal) == first


@pytest.mark.real_card
def test_29_the_policy_still_only_receives_a_view_and_a_list(repository):
    """
    Phase 3-A 의 경계가 그대로다 — 세트가 들어와도 정책은 관측과 목록만 본다.
    """
    duel = staged(repository, hand=(LUSTER_DRAGON, DARK_HOLE))
    seen = []

    class Spy:
        name = "spy"

        def decide(self, view, legal):
            seen.append((view, legal))
            return legal.allowed[0]

    spy = Spy()
    spy.decide(duel.view(MINE), duel.legal_actions(MINE))
    view, legal = seen[0]
    assert isinstance(view, GameStateView)
    assert not hasattr(view, "apply")
    assert all(isinstance(a, PlayerAction) for a in legal.allowed)
