"""
Phase 3-E-1 — ATTACK Action Space 정식 검증.

    GameState → GameStateView → legal_actions(seat)
        ↓
    ATTACK candidate (attacker × target, direct)
        ↓  SearchPolicy
    Simulator.simulate → clone → **진짜** Duel.apply → BattleExecutor
        ↓
    future GameStateView → StateEvaluator → 점수
        ↓  비교
    PlayerAction → 진짜 Duel.apply()

네 가지를 **따로** 증명한다
---------------------------
이 파일이 섞지 않는 네 단계가 있다 (§최종원칙).

1. ATTACK 을 **할 수 있다** — ``legal_actions`` 에 오른다
2. ATTACK 을 **내다볼 수 있다** — 시뮬레이션이 진짜 전투를 거친다
3. AI 가 ATTACK 을 **고른다** — 평가 결과로, 강제 없이
4. 진짜 듀얼에서 ATTACK 이 **실행된다** — AI 대 AI 에서

앞의 것이 참이어도 뒤의 것은 따로 보여야 한다.

강제하지 않는다
---------------
평가 함수는 **행위를 보지 않는다.** ``evaluate(view)`` 의 인수에 행위가
없다는 것이 그 보장이고, 그래서 "ATTACK 이니까 점수를 더" 가 구조적으로
불가능하다. 탐색에도 ``if action == ATTACK`` 이 없다.
"""

import ast
import collections
import inspect
import pathlib

import pytest

from agent import FirstLegalPolicy, RandomPolicy, play, rule_based_policy, search_policy
from agent.arena import make_rule_based, make_search, run_match, run_series, summarize
from agent.evaluation import StateEvaluator
from agent.search import SearchPolicy
from agent.simulation import SimulationStatus, Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.action_target import ActionTarget
from engine.action_validation import ActionValidator, ActionValidity
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

LUSTER_DRAGON = 11091375  # ATK 1900 / DEF 1600
BATTLE_OX = 5053103  # ATK 1700 / DEF 1000
KOJIKOCY = 1184620  # ATK 1500 / DEF 1200
THE_13TH_GRAVE = 32864  # ATK 1200 / DEF  900
WHITE_DUSTON = 3557275  # ATK    0 / DEF 1000
POT_OF_GREED = 55144522

DECK = (
    [LUSTER_DRAGON] * 3
    + [BATTLE_OX] * 3
    + [KOJIKOCY] * 3
    + [THE_13TH_GRAVE] * 3
    + [WHITE_DUSTON] * 3
    + [POT_OF_GREED] * 5
)
DECKS = (DECK, DECK)
SEEDS = (1, 2, 3, 4, 5, 6, 7, 8)


# ======================================================================
# 판 만들기
# ======================================================================


def staged(repository, *, mine, theirs, turn=2, turn_player=MINE) -> Duel:
    """
    배틀 페이즈의 판 하나. 배치는 :meth:`GameState.move` — **엔진의 것**이다.

    ``mine`` · ``theirs`` 는 ``(card_id, position)`` 목록이다. 가짜 상태가
    아니라는 것을 :func:`test_a_staged_board_is_one_the_engine_itself_accepts`
    가 확인한다 — 이 판에서 엔진이 직접 ``VALID`` 를 돌려준다.

    ``FACEUP_ATTACK`` 만 쓰는 판은 **실제 듀얼에서도 도달한다** (일반 소환이
    정확히 그 표시 형식으로 놓는다). 뒷면 수비 표시도 Phase 3-E-2 부터
    도달하며, 그 사실은
    :func:`test_defence_position_is_now_reachable_through_legal_actions` 가
    적는다.
    """
    ids = [c for c, _ in mine] + [c for c, _ in theirs] or [LUSTER_DRAGON]
    state = GameState.create(repository, decks=(list(ids) * 6, list(ids) * 6))
    for seat, layout in ((MINE, mine), (THEIRS, theirs)):
        for card_id, position in layout:
            instance = state.create_instance(card_id, owner=seat, zone=Zone.HAND)
            state.move(instance, Zone.MZONE, to_player=seat, position=position)
    state.turn.turn_number = turn
    state.turn.turn_player = turn_player
    state.turn.set_phase(Phase.BATTLE)
    return Duel(
        state=state,
        priority=PriorityState.idle(turn_player=turn_player, phase=Phase.BATTLE),
    )


def attacks(duel: Duel, seat: int = MINE):
    return [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ATTACK
    ]


def snapshot(duel: Duel) -> tuple:
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
            )
            for seat in (MINE, THEIRS)
        ),
    )


def battle_point(repository, seed: int):
    """
    **실제 듀얼을 굴려서** 공격 후보가 있는 자리에 도달한다.

    만들어 둔 판이 아니라 정책이 둔 수로 도달한 자리다 — §35 가 "legal_actions
    에 ATTACK 이 있기만 한 것" 을 성공으로 인정하지 않기 때문이다.
    """
    duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=seed)
    policies = (rule_based_policy(), rule_based_policy())
    for _ in range(4000):
        if duel.is_over:
            break
        if duel.advance() is not None:
            continue
        seat = duel.to_act
        legal = duel.legal_actions(seat)
        if not legal.allowed:
            break
        if any(a.kind is PlayerActionKind.ATTACK for a in legal.allowed):
            return duel, seat, legal
        duel.apply(policies[seat].decide(duel.view(seat), legal))
    return None, None, None


# ======================================================================
# 0. 만든 판이 가짜가 아니라는 것
# ======================================================================


@pytest.mark.real_card
def test_a_staged_board_is_one_the_engine_itself_accepts(repository):
    """
    만들어 둔 판에서 **엔진이 직접** 공격을 허가한다. 가짜 상태가 아니다.
    """
    duel = staged(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    action = attacks(duel)[0]
    verdict = ActionValidator(duel.view(MINE)).validate(action)

    assert verdict.validity is ActionValidity.VALID
    # 일반 소환이 놓는 표시 형식과 같다 — 실제 듀얼에서도 도달하는 상태다.
    from engine.normal_summon import SUMMON_POSITION

    assert SUMMON_POSITION is Position.FACEUP_ATTACK
    for seat in (MINE, THEIRS):
        for card in duel.state.player(seat).zone(Zone.MZONE):
            assert card.position is Position.FACEUP_ATTACK


def _played(repository, factories, *, seeds=SEEDS[:4]):
    """
    실제 듀얼을 끝까지 굴리면서 **후보 · 고른 수 · 나타난 표시 형식**을 센다.

    셋을 따로 세는 것이 이 함수의 전부다 — "후보에 올랐다" 와 "AI 가 골랐다"
    와 "판에 실제로 생겼다" 는 서로 다른 사실이고, 하나로 뭉치면 어느 것이
    참인지 말할 수 없게 된다.
    """
    seen: collections.Counter = collections.Counter()
    chosen: collections.Counter = collections.Counter()
    positions = set()
    for seed in seeds:
        duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=seed)
        policies = [factory() for factory in factories]
        for _ in range(4000):
            if duel.is_over:
                break
            if duel.advance() is not None:
                continue
            seat = duel.to_act
            legal = duel.legal_actions(seat)
            if not legal.allowed:
                break
            for action in legal.allowed:
                seen[action.kind] += 1
            for side in (MINE, THEIRS):
                for card in duel.state.player(side).zone(Zone.MZONE):
                    positions.add(card.position)
            action = policies[seat].decide(duel.view(seat), legal)
            chosen[action.kind] += 1
            duel.apply(action)
    return seen, chosen, positions


@pytest.mark.real_card
def test_defence_position_is_now_reachable_through_legal_actions(repository):
    """
    **STRUCTURAL-108 이 풀린 자리다** — 그리고 절반만 풀렸다.

    Phase 3-E-1 에서 이 시험은 그 반대를 적었다: "수비 표시를 만들 길이
    없다". 그때는 사실이었다 — ``SET_MONSTER`` 가 후보에 오르지 않았고
    (검증기가 ``UNKNOWN``), 그래서 ATK vs DEF 경로는 ``NOT_REACHED`` 였다.
    그 설명에 **"여기서 통과시키려고 가짜 상태를 만들지 않는다"** 고
    적어 두었고, Phase 3-E-2 가 가짜 상태가 아니라 **세트 실행 계층**을
    넣어서 길을 냈다. 그래서 주장을 뒤집는다 — 약화가 아니라 반대 방향의
    강화다.

    다만 **뒤집는 범위를 정확히 적는다.** 네 가지를 따로 센다:

    1. ``SET_MONSTER`` 가 후보에 **오른다** (규칙 기반 판에서 104회 실측)
    2. 규칙 기반 정책은 그것을 **한 번도 고르지 않는다** — 그래서 그
       정책만 굴리면 뒷면 수비 표시가 판에 **생기지 않는다**
    3. 난수 정책은 고르고, 그때 뒷면 수비 표시가 **실제로 생긴다**
    4. ``CHANGE_POSITION`` 은 여전히 후보에 오르지 않는다 (Phase 3-E-2 §24
       가 범위 밖으로 둔 부분 — STRUCTURAL-108 의 나머지 절반)

    2번이 규칙 기반 AI 의 흠이 아니라 **측정된 사실**인 이유: ``agent/
    heuristic.py`` 의 ``SummonBeforeEndingThePhase.BOARD_KINDS`` 는
    ``{NORMAL_SUMMON}`` 하나이고, 세트를 보는 규칙이 하나도 없다. 그래서
    모든 세트 후보가 0 점으로 ``END_PHASE`` 와 동점이 되고, 동점은
    ``canonical_state()`` 가 가르는데 ``"end_phase" < "set_monster"`` 다.
    **세트에 가산점을 주어 고르게 만들지 않는다** — Phase 3-E-2 §9 · §15 가
    금지한 일이고, 그렇게 하면 "AI 가 세트를 고른다" 가 측정이 아니라
    주문이 된다.
    """
    seen, chosen, positions = _played(
        repository, (rule_based_policy, rule_based_policy)
    )

    # 1. 후보에는 오른다.
    assert seen[PlayerActionKind.SET_MONSTER] == 104, dict(seen)
    assert seen[PlayerActionKind.SET_SPELL_TRAP] == 190, dict(seen)

    # 2. 규칙 기반 정책은 고르지 않는다 — 그래서 판에도 생기지 않는다.
    assert chosen[PlayerActionKind.SET_MONSTER] == 0, dict(chosen)
    assert positions == {Position.FACEUP_ATTACK}, positions

    # 4. 표시 형식 변경은 여전히 길이 없다 (§24 범위 밖).
    assert seen[PlayerActionKind.CHANGE_POSITION] == 0, dict(seen)

    # 3. 고르는 정책을 쓰면 뒷면 수비 표시가 **실제로** 생긴다.
    rseen, rchosen, rpositions = _played(
        repository,
        (lambda: RandomPolicy(seed=31), lambda: RandomPolicy(seed=32)),
    )
    assert rchosen[PlayerActionKind.SET_MONSTER] > 0, dict(rchosen)
    assert Position.FACEDOWN_DEFENSE in rpositions, rpositions
    assert rseen[PlayerActionKind.CHANGE_POSITION] == 0, dict(rseen)


# ======================================================================
# 1~4. Legal Action (§4 · §5 · §13 · §17)
# ======================================================================


@pytest.mark.real_card
def test_01_attack_appears_in_legal_actions_of_a_real_duel(repository):
    """**실제로 굴린 듀얼**에서 공격 후보가 나온다."""
    duel, seat, legal = battle_point(repository, seed=3)
    assert duel is not None, "공격 후보가 있는 자리에 도달하지 못했습니다"

    found = [a for a in legal.allowed if a.kind is PlayerActionKind.ATTACK]
    assert found
    assert duel.state.turn.phase is Phase.BATTLE
    assert seat == duel.state.turn.turn_player
    # 턴을 넘기는 선택도 함께 있다 — 공격이 강제가 아니다 (RULE-BATTLE-002).
    assert any(a.kind is PlayerActionKind.END_PHASE for a in legal.allowed)


@pytest.mark.real_card
def test_02_candidate_identity_is_per_instance_not_per_card_name(repository):
    """
    같은 이름 두 장 × 같은 이름 두 장 = **서로 다른 네 후보** (§5).

    카드 이름으로 식별하면 네 개가 하나로 뭉친다.
    """
    duel = staged(
        repository,
        mine=[
            (LUSTER_DRAGON, Position.FACEUP_ATTACK),
            (LUSTER_DRAGON, Position.FACEUP_ATTACK),
        ],
        theirs=[
            (KOJIKOCY, Position.FACEUP_ATTACK),
            (KOJIKOCY, Position.FACEUP_ATTACK),
        ],
    )
    found = attacks(duel)

    assert len(found) == 4
    assert len({a.canonical_state() for a in found}) == 4, "후보가 뭉쳤습니다"
    attackers = {a.source for a in found}
    targets = {a.target.instance_id for a in found}
    assert len(attackers) == 2 and len(targets) == 2
    for action in found:
        assert action.kind is PlayerActionKind.ATTACK
        assert action.source is not None
        assert action.target.instance_id is not None
        # 카드 이름 · card_id 가 action 에 들어 있지 않다.
        assert "card_id" not in action.to_dict()


@pytest.mark.real_card
def test_03_a_direct_attack_candidate_appears_on_an_empty_field(repository):
    duel = staged(
        repository, mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)], theirs=[]
    )
    found = attacks(duel)

    assert len(found) == 1
    assert found[0].target.instance_id is None
    assert found[0].target.player == THEIRS

    # 상대 몬스터가 생기면 사라진다 (RULE-BATTLE-013).
    blocked = staged(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(WHITE_DUSTON, Position.FACEUP_ATTACK)],
    )
    assert all(a.target.instance_id is not None for a in attacks(blocked))


@pytest.mark.real_card
def test_04_every_target_gets_its_own_candidate(repository):
    """§17 Scenario D — 대상마다 따로 후보가 된다."""
    duel = staged(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[
            (WHITE_DUSTON, Position.FACEUP_ATTACK),
            (BATTLE_OX, Position.FACEUP_ATTACK),
        ],
    )
    found = attacks(duel)

    assert len(found) == 2
    assert {a.target.instance_id for a in found} == {
        c.instance_id for c in duel.state.player(THEIRS).zone(Zone.MZONE)
    }


@pytest.mark.real_card
def test_04b_multiple_targets_really_happen_in_real_duels(repository):
    """
    만든 판이 아니라 **실제 듀얼**에서도 대상이 둘 이상인 자리가 나온다.
    """
    multi = 0
    for seed in SEEDS:
        duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=seed)
        policies = (rule_based_policy(), rule_based_policy())
        for _ in range(4000):
            if duel.is_over:
                break
            if duel.advance() is not None:
                continue
            seat = duel.to_act
            legal = duel.legal_actions(seat)
            if not legal.allowed:
                break
            if sum(1 for a in legal.allowed if a.kind is PlayerActionKind.ATTACK) >= 2:
                multi += 1
            duel.apply(policies[seat].decide(duel.view(seat), legal))
    assert multi > 0, "실제 듀얼에서 대상이 둘 이상인 자리가 없었습니다"


# ======================================================================
# 5~9. Search (§6 · §7 · §9 · §11)
# ======================================================================


@pytest.mark.real_card
def test_05_search_simulates_an_attack_through_the_real_engine(repository):
    """§14 Scenario A — 공격이 **진짜 전투 실행기**를 지난다."""
    duel = staged(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],  # 1900
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],  # 1500
    )
    action = attacks(duel)[0]
    result = Simulator(duel).simulate(action, viewer=MINE)

    assert result.status is SimulationStatus.SUPPORTED
    assert result.future is not None
    future = result.future
    assert future.opponent.monster_zone.size == 0, "대상이 파괴되지 않았다"
    assert future.opponent.grave.size == 1
    assert future.me.monster_zone.size == 1, "공격자가 남아야 한다"
    assert future.opponent.life_points == 7600, "초과분 400 이 들어가야 한다"
    assert future.me.life_points == 8000
    assert future.attacks_by(action.source) == 1, "공격권이 기록되어야 한다"


@pytest.mark.real_card
def test_06_a_losing_attack_shows_the_attacker_dying_in_the_future(repository):
    """§15 Scenario B — 공격자가 죽고 **내** LP 가 깎이는 미래."""
    duel = staged(
        repository,
        mine=[(KOJIKOCY, Position.FACEUP_ATTACK)],  # 1500
        theirs=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],  # 1900
    )
    action = attacks(duel)[0]
    future = Simulator(duel).simulate(action, viewer=MINE).future

    assert future.me.monster_zone.size == 0
    assert future.me.grave.size == 1
    assert future.opponent.monster_zone.size == 1
    assert future.me.life_points == 7600
    assert future.opponent.life_points == 8000
    assert future.attacks_by(action.source) == 1


@pytest.mark.real_card
def test_07_a_direct_attack_future_shows_the_full_damage(repository):
    """§16 Scenario C — 공격력 전액이 상대 LP 에서."""
    duel = staged(
        repository, mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)], theirs=[]
    )
    action = attacks(duel)[0]
    future = Simulator(duel).simulate(action, viewer=MINE).future

    assert future.opponent.life_points == 8000 - 1900
    assert future.me.monster_zone.size == 1
    assert future.attacks_by(action.source) == 1


@pytest.mark.real_card
def test_08_the_evaluator_sees_the_battle_result(repository):
    """
    평가가 **미래 상태**를 보고 달라진다 (§9).

    평가 함수는 행위를 받지 않으므로 "ATTACK 이니까" 가 불가능하다.
    """
    duel = staged(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    evaluator = StateEvaluator()
    simulator = Simulator(duel)

    attack = attacks(duel)[0]
    end = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.END_PHASE
    )
    after_attack = evaluator.evaluate(simulator.simulate(attack, viewer=MINE).future)
    after_end = evaluator.evaluate(simulator.simulate(end, viewer=MINE).future)

    assert after_attack.heuristic > after_end.heuristic
    terms = dict(after_attack.terms)
    assert terms["lp"] == 400, "LP 차이가 평가에 들어갔다"
    assert terms["monsters"] == 500, "상대 몬스터가 사라진 것이 들어갔다"
    assert terms["atk"] == 1900, "상대 공격력이 사라진 것이 들어갔다"


def test_08b_the_evaluator_cannot_see_the_action_at_all():
    """
    **구조적 보장**: ``evaluate`` 의 인수에 행위가 없다 (§9 · §35).

    그래서 "ATTACK 이면 점수를 더" 를 쓸 수가 없다. 금지가 아니라 불가능이다.
    """
    signature = inspect.signature(StateEvaluator.evaluate)
    assert list(signature.parameters) == ["self", "view"]

    tree = ast.parse((ROOT / "agent/evaluation.py").read_text())
    names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    for forbidden in ("PlayerAction", "PlayerActionKind", "ATTACK", "kind", "action"):
        assert forbidden not in names, forbidden


def test_08c_the_search_layer_has_no_attack_shortcut():
    """``if action == ATTACK`` 같은 분기가 탐색에 없다 (§6 · §35)."""
    for name in ("search.py", "simulation.py"):
        tree = ast.parse((ROOT / "agent" / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.Module)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                ):
                    node.body = body[1:] or [ast.Pass()]
        code = ast.unparse(tree)
        assert "ATTACK" not in code, name
        assert "attack" not in code, name


@pytest.mark.real_card
def test_09_attack_and_end_phase_compete_on_their_futures(repository):
    """
    §11 — 둘 다 후보로 받고 **평가로** 고른다. 공격 우대가 없다.

    증거: 공격이 **손해**인 판에서는 탐색이 턴을 넘긴다.
    """
    good = staged(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],  # 1900 vs 1500 → 이득
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    policy = search_policy(good)
    chosen = policy.decide(good.view(MINE), good.legal_actions(MINE))
    assert chosen.kind is PlayerActionKind.ATTACK
    assert len(policy.last_decision.candidates) >= 2

    bad = staged(
        repository,
        mine=[(KOJIKOCY, Position.FACEUP_ATTACK)],  # 1500 vs 1900 → 손해
        theirs=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
    )
    policy = search_policy(bad)
    chosen = policy.decide(bad.view(MINE), bad.legal_actions(MINE))
    assert chosen.kind is PlayerActionKind.END_PHASE, (
        "손해인 공격을 골랐습니다 — 평가가 아니라 공격 우대가 작동했습니다"
    )
    attack_candidate = next(
        c
        for c in policy.last_decision.candidates
        if c.action.kind is PlayerActionKind.ATTACK
    )
    assert attack_candidate.status is SimulationStatus.SUPPORTED
    assert attack_candidate.value is not None, "해 보고 점수를 냈다"


@pytest.mark.real_card
def test_09b_two_winning_targets_produce_different_futures(repository):
    """
    §17 — 대상마다 **미래가 다르다.** (평가가 다른지는 다음 시험이 본다.)
    """
    duel = staged(
        repository,
        mine=[(BATTLE_OX, Position.FACEUP_ATTACK)],  # 1700
        theirs=[
            (WHITE_DUSTON, Position.FACEUP_ATTACK),  # 0    → 1700 데미지
            (KOJIKOCY, Position.FACEUP_ATTACK),  # 1500 →  200 데미지
        ],
    )
    simulator = Simulator(duel)
    futures = {
        action.target.instance_id: simulator.simulate(action, viewer=MINE).future
        for action in attacks(duel)
    }
    assert len(futures) == 2

    lives = {f.opponent.life_points for f in futures.values()}
    survivors = {
        tuple(c.card_id for c in f.opponent.monster_zone.occupied())
        for f in futures.values()
    }
    assert lives == {6300, 7800}, lives
    assert len(survivors) == 2, "남은 몬스터가 같습니다 — 미래가 구별되지 않습니다"


@pytest.mark.real_card
def test_09c_the_evaluator_is_indifferent_between_winning_targets(repository):
    """
    **STRUCTURAL-111 을 사실로 적는다.** 이기는 공격들 사이에서 평가가 같다.

    왜 같은지가 산술로 설명된다. 공격자가 이기는 전투에서는 언제나

        (입힌 데미지) + (지운 상대 공격력) = 공격자의 공격력

    이고, ``ATK_IN_LP == 1`` 이므로 두 항이 **정확히 상쇄된다.**

        대상 ATK 0    → lp +1700 · atk  +200 → 1300
        대상 ATK 1500 → lp  +200 · atk +1700 → 1300

    Phase 3-C 가 공격력을 1:1 로 둔 근거("공격력은 그대로 LP 로 들어오는
    피해")는 그대로 옳지만, **파괴가 지우는 미래의 공격·방어 기회**는 담지
    않는다. 그래서 어느 대상을 치는지가 점수로 갈리지 않고
    ``canonical_state`` 순서로 갈린다.

    **가중치를 고쳐서 이 시험을 통과시키지 않았다** (§9 · §35). 숫자를 비틀어
    결과를 만드는 것은 측정이 아니다. 사실로 적고 TODO 로 남긴다.
    """
    from agent.evaluation import ATK_IN_LP

    assert ATK_IN_LP == 1, "1:1 이 아니면 이 설명이 성립하지 않는다"

    duel = staged(
        repository,
        mine=[(BATTLE_OX, Position.FACEUP_ATTACK)],  # 1700
        theirs=[
            (WHITE_DUSTON, Position.FACEUP_ATTACK),  # 0
            (KOJIKOCY, Position.FACEUP_ATTACK),  # 1500
        ],
    )
    policy = search_policy(duel)
    chosen = policy.decide(duel.view(MINE), duel.legal_actions(MINE))

    scored = {
        candidate.action.target.instance_id: dict(candidate.value.terms)
        for candidate in policy.last_decision.candidates
        if candidate.action.kind is PlayerActionKind.ATTACK
    }
    assert len(scored) == 2
    totals = {
        candidate.value.heuristic
        for candidate in policy.last_decision.candidates
        if candidate.action.kind is PlayerActionKind.ATTACK
    }
    assert len(totals) == 1, (
        f"평가가 갈라졌습니다 — STRUCTURAL-111 이 해결되었다면 보고서를 "
        f"다시 써야 합니다: {totals}"
    )

    # 항별로는 분명히 다르다 — 합이 같을 뿐이다.
    lp_terms = {terms["lp"] for terms in scored.values()}
    atk_terms = {terms["atk"] for terms in scored.values()}
    assert lp_terms == {1700, 200}
    assert atk_terms == {200, 1700}
    for terms in scored.values():
        assert terms["lp"] + terms["atk"] == 1900

    # 공격 자체는 턴 넘기기보다 낫다고 평가된다 — 그 판단은 살아 있다.
    end_value = next(
        candidate.value.heuristic
        for candidate in policy.last_decision.candidates
        if candidate.action.kind is PlayerActionKind.END_PHASE
    )
    assert totals.pop() > end_value
    assert chosen.kind is PlayerActionKind.ATTACK


# ======================================================================
# 10~12. 안전 (§18 · §19 · §20)
# ======================================================================


@pytest.mark.real_card
def test_10_the_original_board_is_untouched_after_searching_attacks(repository):
    duel = staged(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[
            (KOJIKOCY, Position.FACEUP_ATTACK),
            (BATTLE_OX, Position.FACEUP_ATTACK),
        ],
    )
    before = snapshot(duel)
    policy = search_policy(duel)
    policy.decide(duel.view(MINE), duel.legal_actions(MINE))

    assert policy.last_decision.simulations >= 3
    assert snapshot(duel) == before
    assert duel.state.player(THEIRS).life_points == 8000
    assert duel.state.player(THEIRS).zone(Zone.MZONE)
    assert duel.view(MINE).attacks_used == ()


@pytest.mark.real_card
def test_11_two_attack_candidates_do_not_bleed_into_each_other(repository):
    """§19 — 두 공격 시뮬레이션이 같은 원본에서 독립적으로 시작한다."""
    duel = staged(
        repository,
        mine=[(BATTLE_OX, Position.FACEUP_ATTACK)],
        theirs=[
            (WHITE_DUSTON, Position.FACEUP_ATTACK),
            (KOJIKOCY, Position.FACEUP_ATTACK),
        ],
    )
    simulator = Simulator(duel)
    first, second = attacks(duel)
    before = snapshot(duel)

    future_a = simulator.simulate(first, viewer=MINE).future
    future_b = simulator.simulate(second, viewer=MINE).future

    # 각 미래에는 **자기 공격만** 반영되어 있다.
    assert future_a.opponent.monster_zone.size == 1
    assert future_b.opponent.monster_zone.size == 1
    survivors_a = {c.instance_id for c in future_a.opponent.monster_zone.occupied()}
    survivors_b = {c.instance_id for c in future_b.opponent.monster_zone.occupied()}
    assert survivors_a != survivors_b
    assert first.target.instance_id not in survivors_a
    assert second.target.instance_id not in survivors_b
    assert future_a.opponent.life_points != future_b.opponent.life_points
    assert snapshot(duel) == before


@pytest.mark.real_card
def test_12_searching_attacks_never_moves_the_game_rng(repository):
    """§20 — 전투는 난수를 쓰지 않고, 탐색도 진짜 난수원을 건드리지 않는다."""
    draws = []

    def factory(duel, seat):
        inner = search_policy(duel)

        class Watched:
            name = f"watched-p{seat}"

            def decide(self, view, legal):
                chosen = inner.decide(view, legal)
                draws.append(duel.state.randomness.draws)
                return chosen

        return Watched()

    result = run_match(
        repository, decks=DECKS, seed=5, factories=(factory, factory)
    )
    assert result.completed
    assert draws and len(set(draws)) == 1, f"난수 좌표가 움직였습니다: {set(draws)}"


@pytest.mark.real_card
def test_12b_search_on_and_off_leave_the_same_game_even_with_attacks(repository):
    """같은 수를 두면 탐색을 했든 안 했든 완전히 같은 대국이다."""
    off = run_match(
        repository,
        decks=DECKS,
        seed=7,
        factories=(
            lambda d, s: FirstLegalPolicy(name=f"first-legal-p{s}"),
            lambda d, s: FirstLegalPolicy(name=f"first-legal-p{s}"),
        ),
    )

    counted = []

    def searches_then_first(duel, seat):
        inner = search_policy(duel)

        class Both:
            name = f"first-legal-p{seat}"

            def decide(self, view, legal):
                if not legal.allowed:
                    return None
                inner.decide(view, legal)
                counted.append(inner.simulation_count())
                return legal.allowed[0]

        return Both()

    on = run_match(
        repository,
        decks=DECKS,
        seed=7,
        factories=(searches_then_first, searches_then_first),
    )

    assert counted and counted[-1] > 10
    assert on.state_hash == off.state_hash
    assert on.winner == off.winner and on.turns == off.turns
    assert on.life_points == off.life_points
    assert [r.action for r in on.decisions] == [r.action for r in off.decisions]


@pytest.mark.real_card
def test_a_simulated_attack_matches_the_real_one(repository):
    """
    §8 — 사본에서 내다본 결과와 원본에 실제로 둔 결과가 **같다.**

    ``fork_after`` 로 사본 자체를 받아 ``state_hash`` 까지 맞춰 본다.
    """
    duel = staged(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    action = attacks(duel)[0]
    forked = Simulator(duel).fork_after(action)
    assert forked is not None

    assert duel.apply(action).accepted

    assert forked.duel.state.state_hash() == duel.state.state_hash()
    assert forked.view(MINE).canonical_state() == duel.view(MINE).canonical_state()
    for seat in (MINE, THEIRS):
        assert (
            forked.duel.state.player(seat).life_points
            == duel.state.player(seat).life_points
        )
    assert (
        forked.duel.state.rule_uses.canonical_state()
        == duel.state.rule_uses.canonical_state()
    )


# ======================================================================
# 13. Trace (§24)
# ======================================================================


@pytest.mark.real_card
def test_13_the_search_trace_records_attack_candidates(repository):
    duel = staged(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[
            (KOJIKOCY, Position.FACEUP_ATTACK),
            (BATTLE_OX, Position.FACEUP_ATTACK),
        ],
    )
    policy = search_policy(duel)
    policy.decide(duel.view(MINE), duel.legal_actions(MINE))
    decision = policy.last_decision

    attack_records = [
        c for c in decision.candidates if c.action.kind is PlayerActionKind.ATTACK
    ]
    assert len(attack_records) == 2
    for record in attack_records:
        assert record.status is SimulationStatus.SUPPORTED
        assert record.value is not None
        assert record.action.source is not None
        assert record.action.target.instance_id is not None
    assert decision.phase is Phase.BATTLE
    assert decision.state_hash == duel.state.state_hash()
    assert decision.describe_ko()

    # 가려진 정보가 없다 — 판도 관측도 담기지 않는다.
    import dataclasses

    for record in (decision, *decision.candidates):
        for field in dataclasses.fields(record):
            value = getattr(record, field.name)
            assert not isinstance(value, (GameStateView, Duel, Simulator)), field.name


# ======================================================================
# 14 · 15. AI 가 실제로 고르고 실행한다 (§21)
# ======================================================================


@pytest.mark.real_card
def test_14_the_ai_actually_selects_an_attack_in_a_real_duel(repository):
    """
    **3단계의 증거**: AI 가 ATTACK 을 고른다 — 결정 흔적에서 관측된다.
    """
    duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=3)
    policy = search_policy(duel)
    play(duel, (policy, rule_based_policy()))

    chosen_attacks = [
        d for d in policy.decisions
        if d.chosen is not None and d.chosen.kind is PlayerActionKind.ATTACK
    ]
    assert chosen_attacks, "탐색이 공격을 한 번도 고르지 않았습니다"
    for decision in chosen_attacks:
        record = decision.of(decision.chosen)
        assert record.status is SimulationStatus.SUPPORTED
        assert record.value is not None, "해 보지 않고 골랐습니다"
        # 턴을 넘기는 후보도 함께 있었는데 공격을 골랐다.
        assert any(
            c.action.kind is PlayerActionKind.END_PHASE
            for c in decision.candidates
        )


@pytest.mark.real_card
def test_15_the_engine_actually_executes_those_attacks(repository):
    """
    **4단계의 증거**: 고른 공격이 진짜 ``Duel.apply`` 를 지나 판을 바꾼다.
    """
    duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=3)
    transcript = play(duel, (search_policy(duel), rule_based_policy()))

    executed = [
        e for e in transcript.entries
        if e.action is not None
        and e.action.kind is PlayerActionKind.ATTACK
        and e.accepted
    ]
    assert executed, "실행된 공격이 없습니다"
    assert transcript.refusals == ()
    # 전투가 판을 바꿨다 — LP 가 움직이고 묘지가 찼다.
    life = (
        duel.state.player(MINE).life_points,
        duel.state.player(THEIRS).life_points,
    )
    assert life != (8000, 8000)
    assert 0 in life
    assert "라이프 포인트가 0" in transcript.result.reason
    assert (
        len(duel.state.player(MINE).zone(Zone.GRAVE))
        + len(duel.state.player(THEIRS).zone(Zone.GRAVE))
    ) > 0


@pytest.mark.real_card
def test_15b_direct_attacks_really_happen_too(repository):
    """다이렉트 어택도 실제 듀얼에서 실행된다."""
    direct = 0
    for seed in SEEDS:
        duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=seed)
        transcript = play(duel, (search_policy(duel), rule_based_policy()))
        direct += sum(
            1
            for e in transcript.entries
            if e.action is not None
            and e.action.kind is PlayerActionKind.ATTACK
            and e.accepted
            and e.action.target.instance_id is None
        )
    assert direct > 0, "다이렉트 어택이 한 번도 실행되지 않았습니다"


# ======================================================================
# 16~18. 정책 조합 (§21)
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize(
    "label,factories",
    [
        ("search-vs-search", (make_search(), make_search())),
        ("search-vs-rule", (make_search(), make_rule_based())),
        ("rule-vs-search", (make_rule_based(), make_search())),
    ],
)
def test_16_each_matchup_runs_and_uses_attacks(repository, label, factories):
    results = run_series(repository, decks=DECKS, seeds=SEEDS, factories=factories)
    summary = summarize(results)

    assert summary.all_completed, summary.describe_ko()
    assert summary.refusals == 0
    assert summary.errors == 0
    assert summary.distribution.get("attack", 0) > 0, f"{label}: 공격이 없었습니다"
    for result in results:
        assert 0 in result.life_points, result.describe_ko()


@pytest.mark.real_card
def test_18_rule_based_policy_is_recorded_not_improved(repository):
    """
    §12 · §29 — ``RuleBasedPolicy`` 가 무엇을 고르는지 **사실만** 적는다.

    측정된 사실: 공격 후보가 있으면 공격을 고른다. 공격자의 공격력만 보고
    고르므로 **대상과 견주지 않는다** (STRUCTURAL-109). 손해인 공격도 한다 —
    고치지 않고 기록한다.
    """
    losing = staged(
        repository,
        mine=[(KOJIKOCY, Position.FACEUP_ATTACK)],  # 1500
        theirs=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],  # 1900
    )
    policy = rule_based_policy()
    chosen = policy.decide(losing.view(MINE), losing.legal_actions(MINE))

    assert chosen.kind is PlayerActionKind.ATTACK, (
        "측정된 사실이 바뀌었습니다 — 보고서를 다시 써야 합니다"
    )
    judgement = policy.last_judgement
    evaluation = judgement.of(chosen)
    names = {name for name, _ in evaluation.appraisals}
    assert "higher-attack-first" in names
    # 대상을 보는 규칙은 **없다** — 그것이 STRUCTURAL-109 다.
    assert all("target" not in name for name in names)

    # 같은 판에서 탐색은 턴을 넘긴다. 둘의 차이가 측정값이다.
    search = search_policy(losing)
    assert (
        search.decide(losing.view(MINE), losing.legal_actions(MINE)).kind
        is PlayerActionKind.END_PHASE
    )


# ======================================================================
# 19 · 20. 재현과 거절
# ======================================================================


@pytest.mark.real_card
def test_19_attacking_duels_replay_exactly(repository):
    for factories in (
        (make_search(), make_search()),
        (make_search(), make_rule_based()),
    ):
        first = run_match(repository, decks=DECKS, seed=4, factories=factories)
        second = run_match(repository, decks=DECKS, seed=4, factories=factories)
        assert first.canonical_state() == second.canonical_state()
        assert first.state_hash == second.state_hash
        assert [r.action for r in first.decisions] == [
            r.action for r in second.decisions
        ]


@pytest.mark.real_card
def test_19b_multi_seed_runs_stay_clean(repository):
    results = run_series(
        repository,
        decks=DECKS,
        seeds=SEEDS,
        factories=(make_search(), make_search()),
    )
    summary = summarize(results)
    assert summary.completed == len(SEEDS)
    assert summary.refusals == 0 and summary.errors == 0 and summary.limits == 0
    assert summary.distribution.get("attack", 0) > 0


@pytest.mark.real_card
def test_20_illegal_attacks_are_still_refused(repository):
    """공격이 생겼다고 해서 아무 공격이나 되는 것은 아니다."""
    duel = staged(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    simulator = Simulator(duel)
    mine = duel.state.player(MINE).zone(Zone.MZONE)[0].instance_id
    theirs = duel.state.player(THEIRS).zone(Zone.MZONE)[0].instance_id
    before = snapshot(duel)

    # 상대 몬스터로 공격 · 자기 몬스터를 공격 · 상대 필드가 있는데 다이렉트
    for bogus in (
        PlayerAction.attack(MINE, theirs, ActionTarget.instance(mine)),
        PlayerAction.attack(MINE, mine, ActionTarget.instance(mine)),
        PlayerAction.attack_directly(MINE, mine),
    ):
        assert bogus not in duel.legal_actions(MINE).allowed
        result = simulator.simulate(bogus, viewer=MINE)
        assert result.status is SimulationStatus.NOT_A_CANDIDATE
        assert result.future is None
        assert not duel.apply(bogus).accepted

    # 한 번 공격한 몬스터는 다시 못 한다.
    assert duel.apply(attacks(duel)[0]).accepted
    assert attacks(duel) == []
    assert snapshot(duel) != before  # 적용했으니 달라졌다
