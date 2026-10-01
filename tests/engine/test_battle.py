"""
engine/battle.py — 기본 전투 실행 (Phase 3-E-1-B).

    PlayerAction.attack(...)
          ↓  Duel.apply → ActionExecutor
    AttackHandler → BattleExecutor.judge()
          ↓  공식 조항
    BattleOutcome
          ↓  기존 primitive
    GameState.move() · PlayerState.change_life()

이 파일이 지키는 것
-------------------
**판정이 공식 조항에서 온다.** 모든 결과에 ``rule_id`` 가 붙어 있고, 그
조항이 ``rules`` 계층에 실제로 있는지 확인한다 — 추측한 규칙이 하나도
없다는 증거다.

**공격권은 카드마다 하나다** (RULE-BATTLE-002). 같은 이름의 두 몬스터가
서로 다른 권리를 갖고, 턴이 넘어가면 새로 생기고, 사본에서 쓴 것이 원본에
남지 않는다.

**모르는 능력치를 숫자로 바꾸지 않는다.** 공격력이 ``?`` 면 멈춘다.

**가짜 실행기가 없다.** LP 는 ``change_life``, 이동은 ``move`` 로만 바뀐다.
"""

import dataclasses

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_target import ActionTarget
from engine.action_validation import ActionValidator, ActionValidity, ValidationCode
from engine.battle import (
    ATTACKING_POSITIONS,
    DESTROYED_TO,
    AttackHandler,
    BattleDestruction,
    BattleError,
    BattleExecutor,
    BattleKind,
    BattleOutcome,
)
from engine.duel import Duel
from engine.effect.delta import CardMovement, LifeChanged
from engine.effect.operation import OperationKind
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.state.game_state import GameState
from engine.state.rule_usage import RuleActionKind, RuleUsageRegistry
from engine.summon import duel_executor
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

MINE, THEIRS = 0, 1

# 실제 통상 몬스터. 능력치는 :func:`test_the_cards_are_what_we_think_they_are`
# 가 공식 DB 에서 다시 읽어 확인한다 — 적어 둔 숫자를 믿지 않는다.
LUSTER_DRAGON = 11091375  # ATK 1900 / DEF 1600
BATTLE_OX = 5053103  # ATK 1700 / DEF 1000
KOJIKOCY = 1184620  # ATK 1500 / DEF 1200
THE_13TH_GRAVE = 32864  # ATK 1200 / DEF  900
WHITE_DUSTON = 3557275  # ATK    0 / DEF 1000
#: 공격을 **견디는** 벽. 공격권만 보고 싶은 시험에서 대상이 사라지지 않게
#: 하려면 ``DEF`` 가 공격자의 ``ATK`` 보다 높아야 한다 (RULE-BATTLE-012).
SOUL_TIGER = 15734813  # ATK 0 / DEF 2100

EXPECTED = {
    LUSTER_DRAGON: (1900, 1600),
    BATTLE_OX: (1700, 1000),
    KOJIKOCY: (1500, 1200),
    THE_13TH_GRAVE: (1200, 900),
    WHITE_DUSTON: (0, 1000),
    SOUL_TIGER: (0, 2100),
}


# ======================================================================
# 판 만들기 — 실제 엔진으로만 만든다
# ======================================================================


def board(
    repository,
    *,
    mine,
    theirs,
    turn_number: int = 2,
    turn_player: int = MINE,
    phase: Phase = Phase.BATTLE,
) -> GameState:
    """
    몬스터를 놓은 판 하나.

    ``mine`` · ``theirs`` 는 ``(card_id, position)`` 목록이다. 배치는
    :meth:`GameState.move` 로 한다 — 가짜 배치 경로를 만들지 않는다.

    턴 번호가 **2** 인 이유: 1턴은 선공의 첫 턴이고 공식 규칙은 그 턴에
    배틀 페이즈를 진행할 수 없다고 적는다 (RULE-BATTLE-001).
    """
    cards = [card_id for card_id, _ in mine] + [card_id for card_id, _ in theirs]
    filler = cards or [LUSTER_DRAGON]
    state = GameState.create(
        repository, decks=(list(filler) * 6, list(filler) * 6)
    )
    for seat, layout in ((MINE, mine), (THEIRS, theirs)):
        for card_id, position in layout:
            drawn = state.create_instance(card_id, owner=seat, zone=Zone.HAND)
            state.move(drawn, Zone.MZONE, to_player=seat, position=position)
    state.turn.turn_number = turn_number
    state.turn.turn_player = turn_player
    state.turn.set_phase(phase)
    return state


def attack_on(state: GameState, attacker_index: int = 0, target_index: int = 0):
    attacker = state.player(MINE).monster_zone[attacker_index]
    target = state.player(THEIRS).monster_zone[target_index]
    return PlayerAction.attack(
        MINE, attacker.instance_id, ActionTarget.instance(target.instance_id)
    )


def snapshot(state: GameState) -> tuple:
    """§21 이 요구하는 mutation surface 전부."""
    return (
        state.state_hash(),
        state.randomness.draws if state.seed is not None else None,
        state.turn.turn_number,
        state.turn.phase,
        state.result,
        tuple(
            (
                state.player(seat).life_points,
                tuple(
                    tuple(c.instance_id.value for c in state.player(seat).zone(z))
                    for z in (
                        Zone.DECK, Zone.HAND, Zone.MZONE,
                        Zone.SZONE, Zone.GRAVE, Zone.REMOVED,
                    )
                ),
            )
            for seat in (MINE, THEIRS)
        ),
        state.rule_uses.canonical_state(),
    )


# ======================================================================
# 0. 전제 확인
# ======================================================================


@pytest.mark.real_card
def test_the_cards_are_what_we_think_they_are(repository):
    """적어 둔 능력치를 믿지 않는다. 공식 DB 에서 다시 읽는다."""
    for card_id, (atk, defense) in EXPECTED.items():
        card = repository.get(card_id)
        assert card is not None and card.is_monster
        assert card.atk == atk, f"{card.name_en}: ATK {card.atk}"
        assert card.defense == defense, f"{card.name_en}: DEF {card.defense}"
        assert not card.has_printed_effect, f"{card.name_en} 은 효과 몬스터다"


@pytest.mark.real_card
def test_every_rule_id_the_executor_cites_really_exists(repository):
    """
    **추측한 규칙이 하나도 없다.** 인용한 조항이 ``rules`` 계층에 실제로 있다.

    ``BattleOutcome.rule_id`` 에 적힌 것이 공식 룰북의 조항 번호가 아니면
    이 시험이 깨진다 — 근거 없는 판정을 넣을 수 없게 만드는 자리다.
    """
    from rules.rule_repository import RuleRepository

    rules = RuleRepository.load()
    cited = {
        "RULE-BATTLE-001",
        "RULE-BATTLE-002",
        "RULE-BATTLE-011",
        "RULE-BATTLE-012",
        "RULE-BATTLE-013",
        "RULE-BATTLE-014",
    }
    for rule_id in sorted(cited):
        section = rules.get(rule_id)
        assert section is not None, f"{rule_id} 가 룰 계층에 없습니다"
        assert section.text, rule_id

    # 코드가 인용하는 것이 이 집합 안에 있는지 (소스에서 직접 읽는다)
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[2] / "engine/battle.py"
    ).read_text()
    import re

    used = set(re.findall(r"RULE-BATTLE-\d{3}", source))
    assert used <= cited | {"RULE-BATTLE-003", "RULE-BATTLE-010"}, used - cited


# ======================================================================
# 1 · 2 — 조립과 등록
# ======================================================================


def test_01_battle_executor_construction():
    executor = BattleExecutor()
    assert repr(executor) == "<BattleExecutor>"
    handler = AttackHandler()
    assert hasattr(handler, "apply")
    assert isinstance(handler.executor, BattleExecutor)


def test_02_the_attack_handler_is_registered_on_the_duel_executor():
    """§5: 기존 ``ActionExecutor`` 등록 패턴을 그대로 쓴다."""
    executor = duel_executor()
    assert PlayerActionKind.ATTACK in executor._handlers
    assert isinstance(executor._handlers[PlayerActionKind.ATTACK], AttackHandler)
    # 소환 전용 실행기는 **그대로**다 — 이름이 거짓이 되지 않게.
    from engine.summon import summon_executor

    assert PlayerActionKind.ATTACK not in summon_executor()._handlers


@pytest.mark.real_card
def test_02b_a_fresh_duel_uses_the_executor_that_knows_battle(repository):
    duel = Duel.start(repository, decks=([LUSTER_DRAGON] * 20,) * 2, seed=1)
    assert PlayerActionKind.ATTACK in duel._executor._handlers


# ======================================================================
# 3~8 — 적법성
# ======================================================================


@pytest.mark.real_card
def test_03_a_valid_attack_is_allowed(repository):
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    view = GameStateView.from_state(state, viewer=MINE)
    verdict = ActionValidator(view).validate(attack_on(state))

    assert verdict.validity is ActionValidity.VALID
    assert verdict.code is ValidationCode.OK


@pytest.mark.real_card
def test_04_an_opponent_monster_cannot_be_the_attacker(repository):
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    theirs = state.player(THEIRS).monster_zone[0].instance_id
    mine = state.player(MINE).monster_zone[0].instance_id
    view = GameStateView.from_state(state, viewer=MINE)

    verdict = ActionValidator(view).validate(
        PlayerAction.attack(MINE, theirs, ActionTarget.instance(mine))
    )
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.SOURCE_NOT_CONTROLLED


@pytest.mark.real_card
def test_05_your_own_monster_cannot_be_the_target(repository):
    state = board(
        repository,
        mine=[
            (LUSTER_DRAGON, Position.FACEUP_ATTACK),
            (BATTLE_OX, Position.FACEUP_ATTACK),
        ],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    first, second = (c.instance_id for c in state.player(MINE).monster_zone[:2])
    view = GameStateView.from_state(state, viewer=MINE)

    verdict = ActionValidator(view).validate(
        PlayerAction.attack(MINE, first, ActionTarget.instance(second))
    )
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.TARGET_SELF_CONTROLLED


@pytest.mark.real_card
def test_06_only_the_turn_player_may_attack(repository):
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
        turn_player=THEIRS,
    )
    view = GameStateView.from_state(state, viewer=MINE)
    verdict = ActionValidator(view).validate(attack_on(state))

    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.NOT_TURN_PLAYER


@pytest.mark.real_card
@pytest.mark.parametrize("phase", [Phase.MAIN1, Phase.MAIN2, Phase.DRAW, Phase.END])
def test_07_attacks_outside_the_battle_phase_are_refused(repository, phase):
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
        phase=phase,
    )
    view = GameStateView.from_state(state, viewer=MINE)
    verdict = ActionValidator(view).validate(attack_on(state))

    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.WRONG_PHASE


@pytest.mark.real_card
def test_07b_the_first_player_cannot_attack_on_turn_one(repository):
    """RULE-BATTLE-001 — 선공은 첫 턴에 배틀 페이즈를 진행할 수 없다."""
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
        turn_number=1,
    )
    view = GameStateView.from_state(state, viewer=MINE)
    verdict = ActionValidator(view).validate(attack_on(state))

    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.WRONG_PHASE
    assert "첫 턴" in verdict.reason


@pytest.mark.real_card
@pytest.mark.parametrize(
    "position",
    [Position.FACEUP_DEFENSE, Position.FACEDOWN_DEFENSE, Position.FACEDOWN_ATTACK],
)
def test_07c_only_a_face_up_attack_position_monster_may_attack(repository, position):
    """RULE-BATTLE-002 — "Each **face-up Attack Position** monster"."""
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, position)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    view = GameStateView.from_state(state, viewer=MINE)
    verdict = ActionValidator(view).validate(attack_on(state))

    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.SOURCE_WRONG_CARD_TYPE
    assert Position.FACEUP_ATTACK in ATTACKING_POSITIONS
    assert position not in ATTACKING_POSITIONS


@pytest.mark.real_card
def test_08_a_monster_that_already_attacked_cannot_attack_again(repository):
    """RULE-BATTLE-002 — "allowed **1 attack per turn**"."""
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[
            (KOJIKOCY, Position.FACEUP_ATTACK),
            (THE_13TH_GRAVE, Position.FACEUP_ATTACK),
        ],
    )
    action = attack_on(state)
    BattleExecutor().apply(state, action)

    view = GameStateView.from_state(state, viewer=MINE)
    again = attack_on(state, target_index=0)
    verdict = ActionValidator(view).validate(again)

    assert verdict.validity is ActionValidity.INVALID
    assert "이미 공격했습니다" in verdict.reason


@pytest.mark.real_card
def test_08b_one_monster_attacking_does_not_spend_another_ones_right(repository):
    """
    **공격권은 카드마다다.** 같은 이름의 두 장도 따로다 (STRUCTURAL-104).
    """
    state = board(
        repository,
        mine=[
            (LUSTER_DRAGON, Position.FACEUP_ATTACK),
            (LUSTER_DRAGON, Position.FACEUP_ATTACK),
        ],
        # DEF 2100 — ATK 1900 으로는 부수지 못한다. 대상이 남아 있어야
        # **둘째 공격자의 공격권**을 볼 수 있다 (RULE-BATTLE-012).
        theirs=[(SOUL_TIGER, Position.FACEUP_DEFENSE)],
    )
    first, second = (c.instance_id for c in state.player(MINE).monster_zone[:2])
    BattleExecutor().apply(state, attack_on(state, attacker_index=0))

    view = GameStateView.from_state(state, viewer=MINE)
    assert view.attacks_by(first) == 1
    assert view.attacks_by(second) == 0

    verdict = ActionValidator(view).validate(
        PlayerAction.attack(
            MINE,
            second,
            ActionTarget.instance(state.player(THEIRS).monster_zone[0].instance_id),
        )
    )
    assert verdict.validity is ActionValidity.VALID


# ======================================================================
# 9~14 — 전투 결과 (RULE-BATTLE-011 · 012)
# ======================================================================


@pytest.mark.real_card
def test_09_attack_beats_a_weaker_attack_position_monster(repository):
    """RULE-BATTLE-011 WIN — 대상 파괴 + 초과분이 상대 LP 에서."""
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],  # 1900
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],  # 1500
    )
    target = state.player(THEIRS).monster_zone[0].instance_id
    outcome = BattleExecutor().judge(state, attack_on(state))

    assert outcome.kind is BattleKind.VERSUS_ATTACK
    assert outcome.rule_id == "RULE-BATTLE-011"
    assert outcome.destroy_target and not outcome.destroy_attacker
    assert outcome.damage == 400 and outcome.damage_to == THEIRS

    deltas = BattleExecutor().apply(state, attack_on(state))
    assert state.player(THEIRS).life_points == 7600
    assert state.player(MINE).life_points == 8000
    assert len(state.player(THEIRS).zone(Zone.MZONE)) == 0
    assert target in [c.instance_id for c in state.player(THEIRS).zone(DESTROYED_TO)]
    assert len(state.player(MINE).zone(Zone.MZONE)) == 1
    kinds = [d.kind for d in deltas]
    assert "life_changed" in kinds and "battle_destruction" in kinds


@pytest.mark.real_card
def test_10_attack_loses_to_a_stronger_attack_position_monster(repository):
    """RULE-BATTLE-011 LOSE — 공격자 파괴 + 초과분이 **공격자 쪽** LP 에서."""
    state = board(
        repository,
        mine=[(KOJIKOCY, Position.FACEUP_ATTACK)],  # 1500
        theirs=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],  # 1900
    )
    attacker = state.player(MINE).monster_zone[0].instance_id
    outcome = BattleExecutor().judge(state, attack_on(state))

    assert outcome.rule_id == "RULE-BATTLE-011"
    assert outcome.destroy_attacker and not outcome.destroy_target
    assert outcome.damage == 400 and outcome.damage_to == MINE

    BattleExecutor().apply(state, attack_on(state))
    assert state.player(MINE).life_points == 7600
    assert state.player(THEIRS).life_points == 8000
    assert len(state.player(MINE).zone(Zone.MZONE)) == 0
    assert attacker in [c.instance_id for c in state.player(MINE).zone(DESTROYED_TO)]
    assert len(state.player(THEIRS).zone(Zone.MZONE)) == 1


@pytest.mark.real_card
def test_11_equal_attack_destroys_both_and_deals_no_damage(repository):
    """RULE-BATTLE-011 TIE — "both monsters are destroyed. Neither player
    takes any battle damage." """
    state = board(
        repository,
        mine=[(BATTLE_OX, Position.FACEUP_ATTACK)],  # 1700
        theirs=[(BATTLE_OX, Position.FACEUP_ATTACK)],  # 1700
    )
    outcome = BattleExecutor().judge(state, attack_on(state))

    assert outcome.rule_id == "RULE-BATTLE-011"
    assert outcome.destroy_attacker and outcome.destroy_target
    assert outcome.damage == 0

    BattleExecutor().apply(state, attack_on(state))
    assert state.player(MINE).life_points == 8000
    assert state.player(THEIRS).life_points == 8000
    assert len(state.player(MINE).zone(Zone.MZONE)) == 0
    assert len(state.player(THEIRS).zone(Zone.MZONE)) == 0
    assert len(state.player(MINE).zone(DESTROYED_TO)) == 1
    assert len(state.player(THEIRS).zone(DESTROYED_TO)) == 1


@pytest.mark.real_card
def test_11b_two_zero_attack_monsters_destroy_nothing(repository):
    """RULE-BATTLE-014 — "Monsters with 0 ATK cannot destroy anything by
    battle. If two Attack Position monsters with 0 ATK battle each other,
    neither monster is destroyed." """
    state = board(
        repository,
        mine=[(WHITE_DUSTON, Position.FACEUP_ATTACK)],  # 0
        theirs=[(WHITE_DUSTON, Position.FACEUP_ATTACK)],  # 0
    )
    outcome = BattleExecutor().judge(state, attack_on(state))

    assert outcome.rule_id == "RULE-BATTLE-014"
    assert not outcome.destroy_attacker and not outcome.destroy_target
    assert outcome.damage == 0

    deltas = BattleExecutor().apply(state, attack_on(state))
    assert len(state.player(MINE).zone(Zone.MZONE)) == 1
    assert len(state.player(THEIRS).zone(Zone.MZONE)) == 1
    assert deltas == ()  # 아무 변화도 적지 않는다
    # 그래도 공격권은 썼다 — 선언은 일어났다.
    assert GameStateView.from_state(state, viewer=MINE).attacks_used


@pytest.mark.real_card
def test_12_attack_beats_a_weaker_defence(repository):
    """RULE-BATTLE-012 WIN — 파괴하되 **데미지는 없다** (관통 미구현)."""
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],  # ATK 1900
        theirs=[(THE_13TH_GRAVE, Position.FACEUP_DEFENSE)],  # DEF 900
    )
    outcome = BattleExecutor().judge(state, attack_on(state))

    assert outcome.kind is BattleKind.VERSUS_DEFENCE
    assert outcome.rule_id == "RULE-BATTLE-012"
    assert outcome.target_value == 900, "수비력과 견뤘다"
    assert outcome.destroy_target and not outcome.destroy_attacker
    assert outcome.damage == 0

    BattleExecutor().apply(state, attack_on(state))
    assert state.player(THEIRS).life_points == 8000, "관통은 구현하지 않았다"
    assert len(state.player(THEIRS).zone(Zone.MZONE)) == 0


@pytest.mark.real_card
def test_13_equal_attack_and_defence_is_a_standstill(repository):
    """
    RULE-BATTLE-012 TIE — "When your attacking monster's ATK is **equal to
    the DEF** of the opponent's monster, neither monster is destroyed...
    Neither player takes any battle damage."

    공격력 1700 과 수비력 1700 을 실제 카드에서 찾아 맞붙인다.
    """
    card = repository.get(BATTLE_OX)
    assert card.atk == 1700
    # DEF 1700 인 통상 몬스터를 실제 DB 에서 찾는다.
    same = next(
        c
        for c in repository.all_cards()
        if c.is_monster
        and not c.is_extra_deck
        and not c.has_printed_effect
        and not c.effects
        and c.defense == 1700
        and (c.monster_level or 99) <= 4
    )
    state = board(
        repository,
        mine=[(BATTLE_OX, Position.FACEUP_ATTACK)],
        theirs=[(same.id, Position.FACEUP_DEFENSE)],
    )
    outcome = BattleExecutor().judge(state, attack_on(state))

    assert outcome.rule_id == "RULE-BATTLE-012"
    assert outcome.attacker_value == outcome.target_value == 1700
    assert not outcome.destroy_target and not outcome.destroy_attacker
    assert outcome.damage == 0

    assert BattleExecutor().apply(state, attack_on(state)) == ()


@pytest.mark.real_card
def test_14_attack_weaker_than_defence_hurts_the_attacker(repository):
    """RULE-BATTLE-012 LOSE — 초과분이 **공격자 쪽** LP 에서."""
    state = board(
        repository,
        mine=[(THE_13TH_GRAVE, Position.FACEUP_ATTACK)],  # ATK 1200
        theirs=[(LUSTER_DRAGON, Position.FACEUP_DEFENSE)],  # DEF 1600
    )
    outcome = BattleExecutor().judge(state, attack_on(state))

    assert outcome.rule_id == "RULE-BATTLE-012"
    assert not outcome.destroy_attacker and not outcome.destroy_target
    assert outcome.damage == 400 and outcome.damage_to == MINE

    BattleExecutor().apply(state, attack_on(state))
    assert state.player(MINE).life_points == 7600
    assert len(state.player(MINE).zone(Zone.MZONE)) == 1, "수비력에 막혀도 살아남는다"
    assert len(state.player(THEIRS).zone(Zone.MZONE)) == 1


# ======================================================================
# 15 · 16 — 다이렉트 어택 (RULE-BATTLE-013)
# ======================================================================


@pytest.mark.real_card
def test_15_a_direct_attack_takes_the_full_attack_off_the_opponent(repository):
    """RULE-BATTLE-013 — "The **full amount** of your attacking monster's
    ATK is subtracted from the opponent's LP." """
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[],
    )
    attacker = state.player(MINE).monster_zone[0].instance_id
    action = PlayerAction.attack_directly(MINE, attacker)

    view = GameStateView.from_state(state, viewer=MINE)
    assert ActionValidator(view).validate(action).validity is ActionValidity.VALID

    outcome = BattleExecutor().judge(state, action)
    assert outcome.kind is BattleKind.DIRECT
    assert outcome.rule_id == "RULE-BATTLE-013"
    assert outcome.damage == 1900 and outcome.damage_to == THEIRS
    assert not outcome.destroy_attacker and not outcome.destroy_target

    BattleExecutor().apply(state, action)
    assert state.player(THEIRS).life_points == 6100
    assert len(state.player(MINE).zone(Zone.MZONE)) == 1
    assert view.attacks_by(attacker) == 0  # 옛 관측은 그대로
    assert GameStateView.from_state(state, viewer=MINE).attacks_by(attacker) == 1


@pytest.mark.real_card
def test_16_a_direct_attack_is_refused_while_a_monster_stands(repository):
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(WHITE_DUSTON, Position.FACEDOWN_DEFENSE)],
    )
    attacker = state.player(MINE).monster_zone[0].instance_id
    view = GameStateView.from_state(state, viewer=MINE)

    verdict = ActionValidator(view).validate(
        PlayerAction.attack_directly(MINE, attacker)
    )
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.TARGET_NOT_OPPONENT
    assert "다이렉트" in verdict.reason


# ======================================================================
# 17 · 18 — 공격권의 수명
# ======================================================================


@pytest.mark.real_card
def test_17_the_attack_right_comes_back_next_turn(repository):
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(SOUL_TIGER, Position.FACEUP_DEFENSE)],  # 부서지지 않는 벽
    )
    attacker = state.player(MINE).monster_zone[0].instance_id
    BattleExecutor().apply(state, attack_on(state))
    assert GameStateView.from_state(state, viewer=MINE).attacks_by(attacker) == 1

    # 턴이 넘어가면 기록의 키가 달라진다 — 지울 것이 없다.
    state.turn.turn_number += 2
    state.turn.set_phase(Phase.BATTLE)
    view = GameStateView.from_state(state, viewer=MINE)

    assert view.attacks_by(attacker) == 0
    assert ActionValidator(view).validate(attack_on(state)).validity is (
        ActionValidity.VALID
    )


def test_18_attack_usage_survives_cloning_independently():
    """사본에서 쓴 공격권이 **원본에 남지 않는다** (§10 · §21)."""
    registry = RuleUsageRegistry()
    one, two = InstanceId(11), InstanceId(12)
    registry.record_card(3, MINE, one, RuleActionKind.ATTACK)

    copy = registry.clone()
    copy.record_card(3, MINE, two, RuleActionKind.ATTACK)

    assert registry.used_card(3, MINE, one, RuleActionKind.ATTACK)
    assert not registry.used_card(3, MINE, two, RuleActionKind.ATTACK)
    assert copy.used_card(3, MINE, two, RuleActionKind.ATTACK)
    assert registry.canonical_state() != copy.canonical_state()


@pytest.mark.real_card
def test_18b_a_simulated_attack_leaves_the_real_attack_right_alone(repository):
    """
    **탐색이 공격을 해 봐도 진짜 판의 공격권은 그대로다.**

    Phase 3-C 의 ``clone()`` 경로가 공격권까지 복제하는지 확인한다.
    """
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    attacker = state.player(MINE).monster_zone[0].instance_id
    before = snapshot(state)

    fork = state.clone()
    BattleExecutor().apply(fork, attack_on(fork))

    assert fork.player(THEIRS).life_points == 7600
    assert GameStateView.from_state(fork, viewer=MINE).attacks_by(attacker) == 1
    assert state.player(THEIRS).life_points == 8000
    assert GameStateView.from_state(state, viewer=MINE).attacks_by(attacker) == 0
    assert snapshot(state) == before


# ======================================================================
# 19 · 20 · 21 — 상태 변화와 원본 보호
# ======================================================================


@pytest.mark.real_card
def test_19_life_changes_only_through_the_existing_primitive(repository):
    """
    LP 변화가 :class:`LifeChanged` 로 기록된다 — 새 이벤트 모델이 없다 (§15).
    """
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[],
    )
    deltas = BattleExecutor().apply(
        state,
        PlayerAction.attack_directly(
            MINE, state.player(MINE).monster_zone[0].instance_id
        ),
    )
    life = [d for d in deltas if isinstance(d, LifeChanged)]
    assert len(life) == 1
    assert life[0].player == THEIRS
    assert life[0].before == 8000 and life[0].after == 6100
    assert life[0].amount == -1900 and life[0].is_loss


@pytest.mark.real_card
def test_20_destruction_is_recorded_as_a_battle_movement(repository):
    """
    파괴가 :class:`CardMovement` 로 세어지고 **이유가 ``BATTLE``** 이다.

    ``EFFECT`` 로 적으면 나중에 트리거 계층이 전투 파괴를 "효과로 파괴됐다"
    로 읽고, "효과로 파괴될 때" 를 조건으로 하는 카드가 잘못 발동한다.
    """
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    target = state.player(THEIRS).monster_zone[0].instance_id
    deltas = BattleExecutor().apply(state, attack_on(state))

    moves = [d for d in deltas if isinstance(d, CardMovement)]
    assert len(moves) == 1
    move = moves[0]
    assert isinstance(move, BattleDestruction)
    assert move.instance == target
    assert move.operation is OperationKind.DESTROY
    assert move.reason_names == ("DESTROY", "BATTLE")
    assert "EFFECT" not in move.reason_names
    assert move.from_zone is Zone.MZONE and move.to_zone is DESTROYED_TO
    assert move.from_player == move.to_player == THEIRS
    assert move.canonical_state()[0] == "battle_destruction"
    assert move.to_dict()["reasons"] == ["DESTROY", "BATTLE"]


@pytest.mark.real_card
def test_21_judging_a_battle_changes_nothing(repository):
    """``judge`` 는 **읽기만** 한다. 적용은 ``apply`` 하나다."""
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    before = snapshot(state)
    for _ in range(3):
        BattleExecutor().judge(state, attack_on(state))
    assert snapshot(state) == before


# ======================================================================
# 22 — 재현
# ======================================================================


@pytest.mark.real_card
def test_22_the_same_battle_always_gives_the_same_state(repository):
    """기본 전투는 난수를 쓰지 않는다 (§22)."""
    hashes = set()
    for _ in range(4):
        state = board(
            repository,
            mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
            theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
        )
        BattleExecutor().apply(state, attack_on(state))
        hashes.add(state.state_hash())
    assert len(hashes) == 1


@pytest.mark.real_card
def test_22b_a_full_duel_with_attacks_replays_exactly(repository):
    """실제 듀얼 한 판이 두 번 돌려도 같은 판으로 끝난다."""
    from agent import FirstLegalPolicy, play, rule_based_policy

    results = []
    for _ in range(2):
        duel = Duel.start(
            repository,
            decks=(
                [LUSTER_DRAGON] * 8 + [KOJIKOCY] * 8,
                [BATTLE_OX] * 8 + [THE_13TH_GRAVE] * 8,
            ),
            seed=19,
        )
        transcript = play(duel, (rule_based_policy(), FirstLegalPolicy()))
        results.append(
            (duel.state.state_hash(), transcript.canonical_state(), transcript.steps)
        )
    assert results[0] == results[1]
    assert "라이프 포인트가 0" in str(results[0][1])


# ======================================================================
# 모르는 값 · 잘못된 요청
# ======================================================================


@pytest.mark.real_card
def test_an_unknown_attack_value_stops_the_battle(repository):
    """
    공격력이 ``?`` 면 **멈춘다.** 0 으로도 큰 수로도 바꾸지 않는다.

    이 카드는 효과 몬스터라서 검증기가 후보로 내놓지 않지만, 필드에 서는
    경로가 생기면 전투에 들어올 수 있다. 그때 조용히 0 이 되지 않게 한다.
    """
    king = 36021814  # 저주받은 하인 킹 — ATK ?
    assert repository.get(king).atk == -2
    state = board(
        repository,
        mine=[(king, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    with pytest.raises(BattleError, match="'\\?' 입니다"):
        BattleExecutor().judge(state, attack_on(state))


@pytest.mark.real_card
def test_the_executor_refuses_requests_that_are_not_attacks(repository):
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(KOJIKOCY, Position.FACEUP_ATTACK)],
    )
    executor = BattleExecutor()
    with pytest.raises(BattleError, match="공격이 아닙니다"):
        executor.judge(state, PlayerAction.end_phase(MINE))
    with pytest.raises(BattleError, match="공격자가 없습니다"):
        executor.judge(state, PlayerAction(kind=PlayerActionKind.ATTACK, actor=MINE))

    gone = state.player(MINE).monster_zone[0]
    state.move(gone, Zone.GRAVE, to_player=MINE)
    with pytest.raises(BattleError, match="몬스터 존에 없습니다"):
        executor.judge(
            state,
            PlayerAction.attack(
                MINE, gone.instance_id, ActionTarget.player_target(THEIRS)
            ),
        )


def test_an_outcome_cannot_carry_damage_with_nobody_to_take_it():
    with pytest.raises(BattleError, match="데미지를 받을 사람이 없습니다"):
        BattleOutcome(
            BattleKind.DIRECT, "RULE-BATTLE-013",
            InstanceId(1), None, 100, 0, damage=100,
        )
    with pytest.raises(BattleError, match="음수가 될 수 없습니다"):
        BattleOutcome(
            BattleKind.DIRECT, "RULE-BATTLE-013",
            InstanceId(1), None, 100, 0, damage_to=THEIRS, damage=-1,
        )


# ======================================================================
# legal_actions 연결 (§18)
# ======================================================================


@pytest.mark.real_card
def test_legal_actions_offers_every_attacker_times_every_target(repository):
    state = board(
        repository,
        mine=[
            (LUSTER_DRAGON, Position.FACEUP_ATTACK),
            (BATTLE_OX, Position.FACEUP_ATTACK),
        ],
        theirs=[
            (KOJIKOCY, Position.FACEUP_ATTACK),
            (THE_13TH_GRAVE, Position.FACEUP_DEFENSE),
        ],
    )
    duel = Duel(state=state, priority=__import__(
        "engine.priority", fromlist=["PriorityState"]
    ).PriorityState.idle(turn_player=MINE, phase=Phase.BATTLE))

    legal = duel.legal_actions(MINE)
    attacks = [a for a in legal.allowed if a.kind is PlayerActionKind.ATTACK]

    assert len(attacks) == 4, [str(a) for a in attacks]
    assert len(set(a.canonical_state() for a in attacks)) == 4, "중복이 있습니다"
    # 다이렉트 어택은 **없다** — 상대 몬스터가 있다 (RULE-BATTLE-013).
    assert all(a.target.instance_id is not None for a in attacks)


@pytest.mark.real_card
def test_legal_actions_offers_a_direct_attack_on_an_empty_field(repository):
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[],
    )
    duel = Duel(state=state, priority=__import__(
        "engine.priority", fromlist=["PriorityState"]
    ).PriorityState.idle(turn_player=MINE, phase=Phase.BATTLE))

    attacks = [
        a for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ATTACK
    ]
    assert len(attacks) == 1
    assert attacks[0].target.player == THEIRS
    assert attacks[0].target.instance_id is None


@pytest.mark.real_card
def test_legal_actions_offers_nothing_to_a_monster_that_already_attacked(repository):
    state = board(
        repository,
        mine=[(LUSTER_DRAGON, Position.FACEUP_ATTACK)],
        theirs=[(SOUL_TIGER, Position.FACEUP_DEFENSE)],  # 부서지지 않는 벽
    )
    priority = __import__(
        "engine.priority", fromlist=["PriorityState"]
    ).PriorityState.idle(turn_player=MINE, phase=Phase.BATTLE)
    duel = Duel(state=state, priority=priority)

    first = [
        a for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ATTACK
    ]
    assert len(first) == 1
    assert duel.apply(first[0]).accepted

    again = [
        a for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ATTACK
    ]
    assert again == []
