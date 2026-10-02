"""
engine/set_card.py — 카드를 뒷면으로 놓는 것 (Phase 3-E-2).

    PlayerAction.set_monster(...) / set_spell_trap(...)
          ↓  ActionExecutor (등록된 핸들러)
    SetMonsterHandler / SetSpellTrapHandler → SetExecutor
          ↓  SummonProcedure (표시 형식만 바꿔 재사용)
    CardSet delta

이 파일이 지키는 것
-------------------
**세트는 소환이 아니다** (RULE-SUMMON-010). ``MonsterSummoned`` 가 나오지
않는다 — 나오면 "소환했을 때" 를 조건으로 하는 카드가 세트에 반응하게 되고,
그것은 규칙 위반이다. 이것이 STRUCTURAL-113 이다.

**소환권은 하나다** (RULE-SUMMON-009). 일반 소환과 몬스터 세트가 같은 권리를
나눠 쓴다. 이름을 나누면 한 턴에 둘 다 할 수 있게 된다.

**마법 · 함정 세트는 그 권리를 쓰지 않는다.** 칸이 있는 한 몇 장이든 놓는다.

**뒷면은 상대에게 보이지 않는다.** 장수와 표시 형식은 공개이고 정체는
비공개다 — "없다" 와 "안 보인다" 가 구분된다.

**가짜 배치 경로가 없다.** 자리를 고르고 놓는 일은 전부
:class:`~engine.summon.SummonProcedure` 의 것이다.
"""

import dataclasses
import pathlib
import re

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionStatus
from engine.action_validation import (
    ActionValidator,
    ActionValidity,
    ValidationCode,
    ValidationResult,
)
from engine.duel import Duel
from engine.effect.delta import CardMovement, MonsterSummoned
from engine.effect.operation import OperationKind
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.set_card import (
    SET_FROM_ZONE,
    SET_MONSTER_POSITION,
    SET_MONSTER_PROCEDURE,
    SET_SPELL_TRAP_POSITION,
    SET_SPELL_TRAP_PROCEDURE,
    CardSet,
    SetError,
    SetExecutor,
    SetMonsterHandler,
    SetSpellTrapHandler,
)
from engine.state.game_state import GameState
from engine.state.rule_usage import RuleActionKind
from engine.summon import duel_executor
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

MINE, THEIRS = 0, 1

# 실제 카드. 능력치 · 종류는 :func:`test_the_cards_are_what_we_think_they_are`
# 가 공식 DB 에서 다시 읽어 확인한다 — 적어 둔 것을 믿지 않는다.
LUSTER_DRAGON = 11091375  # 몬스터 · 레벨 4 · ATK 1900 / DEF 1600
BATTLE_OX = 5053103  # 몬스터 · 레벨 4 · ATK 1700 / DEF 1000
SOUL_TIGER = 15734813  # 몬스터 · 레벨 4 · ATK    0 / DEF 2100
BLUE_EYES = 89631139  # 몬스터 · 레벨 8 — 제물이 필요하다 (RULE-SUMMON-011)
DARK_HOLE = 53129443  # 마법
TRAP_HOLE = 4206964  # 함정


# ======================================================================
# 판 만들기 — 실제 엔진으로만 만든다
# ======================================================================


def hand_state(
    repository,
    *,
    hand=(LUSTER_DRAGON, DARK_HOLE),
    phase: Phase = Phase.MAIN1,
    turn_number: int = 1,
    turn_player: int = MINE,
) -> GameState:
    """
    패에 지정한 카드를 쥔 판 하나. 배치는 :meth:`GameState.create_instance` 다.

    세트는 **패에서만** 하는 행위이므로 (``SET_FROM_ZONE``) 필드에 미리
    놓아 둘 것이 없다.
    """
    state = GameState.create(
        repository, decks=(list(hand) * 6 or [LUSTER_DRAGON] * 6, [LUSTER_DRAGON] * 12)
    )
    for card_id in hand:
        state.create_instance(card_id, owner=MINE, zone=Zone.HAND)
    state.turn.turn_number = turn_number
    state.turn.turn_player = turn_player
    state.turn.set_phase(phase)
    return state


#: 두 세트의 (만드는 함수, 쓸 카드). **문자열로 고르는 이유**: 바운드
#: 메서드는 접근할 때마다 새 객체여서 ``build is PlayerAction.set_monster``
#: 가 언제나 거짓이다 — 그것으로 가르면 시험이 조용히 다른 카드를 쓴다.
_SET_KINDS = {
    "monster": (PlayerAction.set_monster, LUSTER_DRAGON),
    "spell_trap": (PlayerAction.set_spell_trap, DARK_HOLE),
}


def _only(zone):
    """존에 든 카드 하나. 둘 이상이면 시험의 전제가 틀린 것이다."""
    cards = list(zone)
    assert len(cards) == 1, [c.instance_id for c in cards]
    return cards[0]


def in_hand(state: GameState, card_id: int, *, seat: int = MINE) -> InstanceId:
    return next(
        c.instance_id for c in state.player(seat).hand if c.card_id == card_id
    )


def validate(state: GameState, action: PlayerAction, *, viewer: int = MINE):
    return ActionValidator(GameStateView.from_state(state, viewer=viewer)).validate(
        action
    )


def execute(state: GameState, action: PlayerAction):
    """등록된 실행기로 적용한다. **여기에 가짜 실행기가 없다.**"""
    return duel_executor().execute(
        state, action, authorization=ValidationResult.valid()
    )


def snapshot(state: GameState) -> tuple:
    """바뀔 수 있는 자리 전부 — 시뮬레이션이 판을 건드리지 않았는지 볼 때."""
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
                tuple(
                    (c.instance_id.value, c.position.value)
                    for c in state.player(seat).monster_zone
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
    """적어 둔 것을 믿지 않는다. 공식 DB 에서 다시 읽는다."""
    for card_id in (LUSTER_DRAGON, BATTLE_OX, SOUL_TIGER, BLUE_EYES):
        card = repository.get(card_id)
        assert card is not None, card_id
        assert card.is_monster, card.name
    assert repository.get(LUSTER_DRAGON).level == 4
    assert repository.get(BLUE_EYES).level == 8
    assert repository.get(SOUL_TIGER).defense == 2100
    assert repository.get(LUSTER_DRAGON).atk == 1900

    for card_id in (DARK_HOLE, TRAP_HOLE):
        card = repository.get(card_id)
        assert card is not None, card_id
        assert not card.is_monster, card.name


def test_every_rule_id_the_set_layer_cites_really_exists():
    """
    **추측한 규칙이 하나도 없다.** 세트 계층이 인용한 조항이 ``rules`` 에
    실제로 있다.

    근거 없는 판정을 넣을 수 없게 만드는 자리다 — ``engine/set_card.py`` 와
    ``engine/action_validation.py`` 의 세트 부분에서 조항 번호를 **소스에서
    직접 읽어** 확인한다.
    """
    from rules.rule_repository import RuleRepository

    rules = RuleRepository.load()
    root = pathlib.Path(__file__).resolve().parents[2]
    source = (root / "engine/set_card.py").read_text()
    cited = set(re.findall(r"RULE-[A-Z]+-\d{3}", source))

    assert cited >= {
        "RULE-SUMMON-009",
        "RULE-SUMMON-010",
        "RULE-TERM-021",
        "RULE-TURN-004",
    }, cited
    for rule_id in sorted(cited):
        section = rules.get(rule_id)
        assert section is not None, f"{rule_id} 가 룰 계층에 없습니다"
        assert section.text, rule_id


def test_the_set_rule_says_a_set_monster_is_not_summoned():
    """
    **이 Phase 의 설계 근거를 원문에서 확인한다.**

    ``CardSet`` 이 존재하는 이유 전부가 RULE-SUMMON-010 의 한 문장이다.
    그 문장이 룰 계층에 실제로 있는지 본다 — 없으면 이 설계의 근거가
    "모델의 기억" 이 되고, 그것은 근거가 아니다.
    """
    from rules.rule_repository import RuleRepository

    # 공식 원문에는 줄바꿈이 들어 있다. **원문을 고치지 않고** 읽는 쪽에서
    # 공백만 정규화한다 — 원문 훼손은 이 저장소가 한 번 겪은 사고다.
    text = " ".join(RuleRepository.load().get("RULE-SUMMON-010").text.split())
    assert "in face-down Defense" in text
    assert "is NOT considered Summoned" in text


# ======================================================================
# 1~3. 조립 · 등록 · 절차
# ======================================================================


def test_01_set_executor_construction():
    executor = SetExecutor()
    assert repr(executor) == "<SetExecutor>"
    assert SetExecutor() is not executor  # 상태가 없다


def test_02_both_set_handlers_are_registered_on_the_duel_executor():
    """
    ADR-006 — 등록하지 않은 것은 ``UNKNOWN`` 이다. 등록을 확인한다.
    """
    executor = duel_executor()
    assert isinstance(
        executor.handler_for(PlayerActionKind.SET_MONSTER), SetMonsterHandler
    )
    assert isinstance(
        executor.handler_for(PlayerActionKind.SET_SPELL_TRAP), SetSpellTrapHandler
    )


@pytest.mark.real_card
def test_02b_a_fresh_duel_uses_the_executor_that_knows_set(repository):
    """``Duel.start`` 가 세트를 아는 실행기를 쓴다."""
    duel = Duel.start(repository, decks=([LUSTER_DRAGON] * 12,) * 2, seed=1)
    executor = duel._executor
    assert isinstance(
        executor.handler_for(PlayerActionKind.SET_MONSTER), SetMonsterHandler
    )


def test_03_the_set_procedures_say_they_are_not_summons():
    """
    **STRUCTURAL-113 의 타입 쪽 증거.** 절차의 ``summon`` 칸이 비어 있다.

    ``SummonKind`` 에 ``SET`` 을 더하지 않은 이유: 그 열거형의 이름이
    "어떤 **소환**인가" 이므로 거기에 세트를 넣는 것은 범주 오류다.
    """
    assert SET_MONSTER_PROCEDURE.summon is None
    assert SET_SPELL_TRAP_PROCEDURE.summon is None
    assert SET_MONSTER_PROCEDURE.position is SET_MONSTER_POSITION
    assert SET_SPELL_TRAP_PROCEDURE.position is SET_SPELL_TRAP_POSITION
    assert SET_MONSTER_PROCEDURE.to_zone is Zone.MZONE
    assert SET_SPELL_TRAP_PROCEDURE.to_zone is Zone.SZONE
    assert SET_MONSTER_PROCEDURE.from_zones == frozenset({SET_FROM_ZONE})
    assert SET_FROM_ZONE is Zone.HAND
    # 표시 형식은 고를 수 없다 (RULE-TERM-021).
    assert SET_MONSTER_POSITION is Position.FACEDOWN_DEFENSE
    assert SET_SPELL_TRAP_POSITION is Position.FACEDOWN


def test_03b_the_executor_refuses_an_action_that_is_not_a_set():
    executor = SetExecutor()
    summon = PlayerAction.normal_summon(MINE, InstanceId(0))
    with pytest.raises(SetError, match="세트가 아닙니다"):
        executor.procedure(summon)
    with pytest.raises(SetError, match="세트가 아닙니다"):
        executor.spends_summon_right(summon)


def test_03c_only_a_monster_set_spends_the_summon_right():
    executor = SetExecutor()
    assert executor.spends_summon_right(
        PlayerAction.set_monster(MINE, InstanceId(0))
    )
    assert not executor.spends_summon_right(
        PlayerAction.set_spell_trap(MINE, InstanceId(0))
    )


# ======================================================================
# 4~6. SET MONSTER 실행 (§4 · §5 · §6)
# ======================================================================


@pytest.mark.real_card
def test_04_set_monster_puts_the_card_face_down_in_defence_position(repository):
    """패 → 몬스터 존, **뒷면 수비 표시**. 표시 형식은 고를 수 없다."""
    state = hand_state(repository)
    card = in_hand(state, LUSTER_DRAGON)

    executed = execute(state, PlayerAction.set_monster(MINE, card))
    assert executed.status is ActionStatus.EXECUTED

    placed = state.player(MINE).monster_zone[0]
    assert placed.instance_id == card
    assert placed.position is Position.FACEDOWN_DEFENSE
    assert not placed.is_faceup
    assert placed.controller == MINE
    assert placed.owner == MINE
    assert card not in [c.instance_id for c in state.player(MINE).hand]


@pytest.mark.real_card
def test_05_a_set_monster_is_not_summoned(repository):
    """
    **STRUCTURAL-113.** ``MonsterSummoned`` 가 하나도 나오지 않는다.

    이것이 깨지면 "소환했을 때" 를 조건으로 하는 카드가 세트에 반응한다
    (RULE-SUMMON-010 위반).
    """
    state = hand_state(repository)
    executed = execute(
        state, PlayerAction.set_monster(MINE, in_hand(state, LUSTER_DRAGON))
    )

    assert not any(isinstance(d, MonsterSummoned) for d in executed.deltas)
    assert [type(d).__name__ for d in executed.deltas] == ["CardSet"]
    assert executed.deltas[0].to_dict()["summoned"] is False


@pytest.mark.real_card
def test_06_the_set_delta_claims_nothing_it_did_not_do(repository):
    """
    세트 델타가 **주장하는 것과 주장하지 않는 것** (§6).

    ``reason_names`` 가 비어 있는 것이 사실이다 — 세트는 파괴도 송치도
    아니다. 거기에 ``EFFECT`` 를 적으면 트리거 계층이 세트를 "효과로
    움직였다" 로 읽는다.
    """
    state = hand_state(repository)
    card = in_hand(state, LUSTER_DRAGON)
    executed = execute(state, PlayerAction.set_monster(MINE, card))
    delta = executed.deltas[0]

    assert isinstance(delta, CardSet)
    assert isinstance(delta, CardMovement)  # "움직인 카드" 를 세는 코드가 센다
    assert delta.kind == "card_set"
    assert delta.instance == card
    assert delta.operation is OperationKind.MOVE
    assert delta.reason_names == ()
    assert delta.from_zone is Zone.HAND
    assert delta.from_player == MINE
    assert delta.to_zone is Zone.MZONE
    assert delta.to_player == MINE
    assert delta.position is Position.FACEDOWN_DEFENSE
    assert delta.is_monster_set
    assert "소환이 아니다" in delta.describe_ko()
    assert delta.canonical_state()[0] == "card_set"


def test_06b_a_card_set_cannot_claim_a_face_up_position():
    """뒷면이 아니면 세트가 아니다 (RULE-TERM-021). 타입이 거부한다."""
    with pytest.raises(SetError, match="세트는 뒷면입니다"):
        CardSet(
            card=InstanceId(0),
            player=MINE,
            owner=MINE,
            source_player=MINE,
            source_zone=Zone.HAND,
            destination_zone=Zone.MZONE,
            destination_index=0,
            position=Position.FACEUP_ATTACK,
        )


# ======================================================================
# 7. SET SPELL / TRAP 실행 (§7)
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize("card_id", [DARK_HOLE, TRAP_HOLE])
def test_07_set_spell_trap_puts_the_card_face_down_in_the_spell_zone(
    repository, card_id
):
    state = hand_state(repository, hand=(card_id,))
    card = in_hand(state, card_id)

    executed = execute(state, PlayerAction.set_spell_trap(MINE, card))
    assert executed.status is ActionStatus.EXECUTED

    placed = state.player(MINE).spell_zone[0]
    assert placed.instance_id == card
    assert placed.position is Position.FACEDOWN
    assert not placed.is_faceup
    delta = executed.deltas[0]
    assert isinstance(delta, CardSet)
    assert delta.to_zone is Zone.SZONE
    assert not delta.is_monster_set
    assert len(state.player(MINE).monster_zone) == 0


@pytest.mark.real_card
def test_07b_setting_a_spell_does_not_activate_it(repository):
    """
    **발동하지 않는다.** 놓기만 한다.

    다크 홀은 발동하면 필드의 몬스터를 전부 파괴한다. 세트했을 때 아무
    몬스터도 사라지지 않는 것이 "발동하지 않았다" 의 증거다.
    """
    state = hand_state(repository, hand=(DARK_HOLE,))
    guard = state.create_instance(LUSTER_DRAGON, owner=THEIRS, zone=Zone.HAND)
    state.move(guard, Zone.MZONE, to_player=THEIRS, position=Position.FACEUP_ATTACK)

    execute(state, PlayerAction.set_spell_trap(MINE, in_hand(state, DARK_HOLE)))

    assert len(state.player(THEIRS).monster_zone) == 1
    assert len(state.player(THEIRS).grave) == 0


# ======================================================================
# 8~11. 소환권 (§11) — RULE-SUMMON-009
# ======================================================================


@pytest.mark.real_card
def test_08_a_monster_set_spends_the_normal_summon_right(repository):
    state = hand_state(repository, hand=(LUSTER_DRAGON, BATTLE_OX))
    assert not state.rule_uses.used(1, MINE, RuleActionKind.NORMAL_SUMMON)

    execute(state, PlayerAction.set_monster(MINE, in_hand(state, LUSTER_DRAGON)))

    assert state.rule_uses.used(1, MINE, RuleActionKind.NORMAL_SUMMON)
    assert state.rule_uses.count(1, MINE, RuleActionKind.NORMAL_SUMMON) == 1


@pytest.mark.real_card
def test_09_set_and_normal_summon_share_one_right_in_both_orders(repository):
    """
    **같은 권리다** (RULE-SUMMON-009: "Normal Summon **OR** Normal Set once
    per turn"). 순서를 바꿔도 두 번째가 거절된다 — 이름을 따로 두면 한 턴에
    둘 다 할 수 있게 된다.
    """
    # 세트 → 소환
    state = hand_state(repository, hand=(LUSTER_DRAGON, BATTLE_OX))
    execute(state, PlayerAction.set_monster(MINE, in_hand(state, LUSTER_DRAGON)))
    blocked = validate(
        state, PlayerAction.normal_summon(MINE, in_hand(state, BATTLE_OX))
    )
    assert blocked.validity is ActionValidity.INVALID
    assert blocked.code is ValidationCode.NORMAL_SUMMON_ALREADY_USED

    # 소환 → 세트
    other = hand_state(repository, hand=(LUSTER_DRAGON, BATTLE_OX))
    execute(other, PlayerAction.normal_summon(MINE, in_hand(other, LUSTER_DRAGON)))
    blocked2 = validate(
        other, PlayerAction.set_monster(MINE, in_hand(other, BATTLE_OX))
    )
    assert blocked2.validity is ActionValidity.INVALID
    assert blocked2.code is ValidationCode.NORMAL_SUMMON_ALREADY_USED
    assert "세트와 소환은 같은 권리" in blocked2.reason


@pytest.mark.real_card
def test_10_a_spell_trap_set_does_not_spend_the_summon_right(repository):
    """마법 · 함정 세트는 **몇 장이든** 놓는다. 소환권과 무관하다."""
    state = hand_state(repository, hand=(DARK_HOLE, TRAP_HOLE, LUSTER_DRAGON))

    execute(state, PlayerAction.set_spell_trap(MINE, in_hand(state, DARK_HOLE)))
    execute(state, PlayerAction.set_spell_trap(MINE, in_hand(state, TRAP_HOLE)))

    assert len(state.player(MINE).spell_zone) == 2
    assert not state.rule_uses.used(1, MINE, RuleActionKind.NORMAL_SUMMON)

    still_allowed = validate(
        state, PlayerAction.set_monster(MINE, in_hand(state, LUSTER_DRAGON))
    )
    assert still_allowed.validity is ActionValidity.VALID


@pytest.mark.real_card
def test_11_the_right_comes_back_on_the_next_turn(repository):
    """권리는 **턴마다** 새로 생긴다 — 기록 열쇠에 턴 번호가 들어 있다."""
    state = hand_state(repository, hand=(LUSTER_DRAGON, BATTLE_OX))
    execute(state, PlayerAction.set_monster(MINE, in_hand(state, LUSTER_DRAGON)))
    assert state.rule_uses.used(1, MINE, RuleActionKind.NORMAL_SUMMON)

    state.turn.turn_number = 3
    assert not state.rule_uses.used(3, MINE, RuleActionKind.NORMAL_SUMMON)
    assert (
        validate(state, PlayerAction.set_monster(MINE, in_hand(state, BATTLE_OX))).validity
        is ActionValidity.VALID
    )


# ======================================================================
# 12~17. 적법성 (§9 · §10 · §13)
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize(
    "phase", [Phase.DRAW, Phase.STANDBY, Phase.BATTLE, Phase.END]
)
@pytest.mark.parametrize("kind", ["monster", "spell_trap"])
def test_12_a_set_outside_the_main_phase_is_refused(repository, phase, kind):
    """
    세트는 **메인 페이즈**의 행위다 (RULE-TURN-004 · RULE-TURN-006).

    Phase 3-E-2 전까지 이 요구가 **없었고**, ``UNKNOWN`` 이 그 사실을 가리고
    있었다 (STRUCTURAL-114). ``_COMPLETE_RULES`` 로 올리기 전에 채웠다.
    """
    build, card_id = _SET_KINDS[kind]
    state = hand_state(repository, hand=(card_id,), phase=phase)

    result = validate(state, build(MINE, in_hand(state, card_id)))
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.WRONG_PHASE
    assert not result.permits_execution


@pytest.mark.real_card
@pytest.mark.parametrize("kind", ["monster", "spell_trap"])
def test_13_a_set_in_both_main_phases_is_allowed(repository, kind):
    """메인 1 과 메인 2 **둘 다**다 (RULE-TURN-006)."""
    build, card_id = _SET_KINDS[kind]
    for phase in (Phase.MAIN1, Phase.MAIN2):
        state = hand_state(repository, hand=(card_id,), phase=phase)
        result = validate(state, build(MINE, in_hand(state, card_id)))
        assert result.validity is ActionValidity.VALID, phase
        assert result.permits_execution


@pytest.mark.real_card
@pytest.mark.parametrize("kind", ["monster", "spell_trap"])
def test_14_only_the_turn_player_may_set(repository, kind):
    build, card_id = _SET_KINDS[kind]
    state = hand_state(repository, hand=(card_id,))
    card = in_hand(state, card_id)
    # 상대가 쥐고 있는 것이 아니라, **내 턴에 상대가** 놓으려 한다.
    state.turn.turn_player = THEIRS

    result = validate(state, build(MINE, card))
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.NOT_TURN_PLAYER


@pytest.mark.real_card
def test_15_set_monster_refuses_a_full_monster_zone(repository):
    state = hand_state(repository)
    for _ in range(5):
        filler = state.create_instance(BATTLE_OX, owner=MINE, zone=Zone.HAND)
        state.move(filler, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK)
    assert len(state.player(MINE).monster_zone) == 5

    result = validate(
        state, PlayerAction.set_monster(MINE, in_hand(state, LUSTER_DRAGON))
    )
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.ZONE_FULL


@pytest.mark.real_card
def test_15b_set_spell_trap_refuses_a_full_spell_zone(repository):
    state = hand_state(repository, hand=(DARK_HOLE,))
    for _ in range(5):
        filler = state.create_instance(TRAP_HOLE, owner=MINE, zone=Zone.HAND)
        state.move(filler, Zone.SZONE, to_player=MINE, position=Position.FACEDOWN)
    assert len(state.player(MINE).spell_zone) == 5

    result = validate(
        state, PlayerAction.set_spell_trap(MINE, in_hand(state, DARK_HOLE))
    )
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.ZONE_FULL


@pytest.mark.real_card
def test_16_the_card_types_do_not_cross(repository):
    """몬스터는 마법 존에, 마법은 몬스터 존에 세트되지 않는다."""
    state = hand_state(repository, hand=(LUSTER_DRAGON, DARK_HOLE))
    monster = in_hand(state, LUSTER_DRAGON)
    spell = in_hand(state, DARK_HOLE)

    wrong_a = validate(state, PlayerAction.set_monster(MINE, spell))
    assert wrong_a.code is ValidationCode.SOURCE_WRONG_CARD_TYPE
    wrong_b = validate(state, PlayerAction.set_spell_trap(MINE, monster))
    assert wrong_b.code is ValidationCode.SOURCE_WRONG_CARD_TYPE


@pytest.mark.real_card
def test_17_a_card_that_is_not_in_the_hand_cannot_be_set(repository):
    """세트는 **패에서만** 한다 (``SET_FROM_ZONE``)."""
    state = hand_state(repository)
    card = in_hand(state, LUSTER_DRAGON)
    state.move(card, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK)

    result = validate(state, PlayerAction.set_monster(MINE, card))
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.SOURCE_WRONG_ZONE


@pytest.mark.real_card
def test_18_a_tribute_set_is_unknown_not_valid(repository):
    """
    **제물 규칙은 소환과 세트에 똑같이 걸린다** (RULE-SUMMON-011: "If you
    Tribute Summon in face-down Defense Position, it is called a Tribute
    Set"). 레벨 8 은 제물이 필요하고 그 절차가 아직 없다.

    ``INVALID`` 가 아니다 — 실제 규칙에서는 제물을 바치면 세트할 수 있고,
    없는 것은 그 절차뿐이다. **``UNKNOWN`` 을 허가로 바꾸지 않는다.**
    """
    state = hand_state(repository, hand=(BLUE_EYES,))

    result = validate(state, PlayerAction.set_monster(MINE, in_hand(state, BLUE_EYES)))
    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "tribute" in result.missing_rule
    assert not result.permits_execution


@pytest.mark.real_card
def test_19_both_set_kinds_are_complete_rules_now(repository):
    """
    **STRUCTURAL-114 의 범위를 적는다.** 둘만 올렸다.

    ``_COMPLETE_RULES`` 를 넓게 풀면 구현하지 않은 행위가 함께 허가된다.
    표시 형식 변경 · 발동은 그대로 ``UNKNOWN`` 이다.
    """
    from engine.action_validation import _COMPLETE_RULES

    assert PlayerActionKind.SET_MONSTER in _COMPLETE_RULES
    assert PlayerActionKind.SET_SPELL_TRAP in _COMPLETE_RULES
    assert PlayerActionKind.CHANGE_POSITION not in _COMPLETE_RULES
    assert PlayerActionKind.ACTIVATE_CARD not in _COMPLETE_RULES

    state = hand_state(repository)
    card = in_hand(state, LUSTER_DRAGON)
    state.move(card, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK)
    still_unknown = validate(state, PlayerAction.change_position(MINE, card))
    assert still_unknown.validity is ActionValidity.UNKNOWN


# ======================================================================
# 20~22. 같은 이름 여러 장 · 자리 (§12 · §13)
# ======================================================================


@pytest.mark.real_card
def test_20_two_copies_of_one_card_are_two_different_candidates(repository):
    """
    같은 이름 두 장은 **서로 다른 후보**다. 카드 이름으로 식별하면 하나로
    뭉치고, 그러면 "어느 쪽을 세트했는지" 를 말할 수 없다.
    """
    state = hand_state(repository, hand=(LUSTER_DRAGON, LUSTER_DRAGON))
    ids = [c.instance_id for c in state.player(MINE).hand]
    assert len(set(ids)) == 2

    actions = {PlayerAction.set_monster(MINE, instance) for instance in ids}
    assert len(actions) == 2
    for action in actions:
        assert validate(state, action).validity is ActionValidity.VALID

    chosen = PlayerAction.set_monster(MINE, ids[0])
    execute(state, chosen)
    assert state.player(MINE).monster_zone[0].instance_id == ids[0]
    assert [c.instance_id for c in state.player(MINE).hand] == [ids[1]]


@pytest.mark.real_card
def test_21_the_set_lands_in_a_free_slot_the_procedure_chose(repository):
    """자리를 고르는 일은 **기존 절차**가 한다. 여기서 새로 만들지 않았다."""
    state = hand_state(repository)
    occupied = state.create_instance(BATTLE_OX, owner=MINE, zone=Zone.HAND)
    state.move(occupied, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK)

    action = PlayerAction.set_monster(MINE, in_hand(state, LUSTER_DRAGON))
    planned = SetExecutor().plan(state, action)
    assert planned.slot in state.player(MINE).monster_zone.free_slots()

    executed = execute(state, action)
    assert executed.deltas[0].destination_index == planned.slot


@pytest.mark.real_card
def test_22_planning_a_set_changes_nothing(repository):
    """``plan`` 은 **읽기만 한다** — 두 번 불러도 판이 그대로다."""
    state = hand_state(repository)
    action = PlayerAction.set_monster(MINE, in_hand(state, LUSTER_DRAGON))

    before = snapshot(state)
    for _ in range(3):
        SetExecutor().plan(state, action)
    assert snapshot(state) == before


# ======================================================================
# 23~25. 숨은 정보 (§8 · §13)
# ======================================================================


@pytest.mark.real_card
def test_23_the_owner_sees_the_set_card_and_the_opponent_does_not(repository):
    """
    **"없다" 와 "안 보인다" 가 구분된다.** 장수와 표시 형식은 공개이고,
    정체는 비공개다.
    """
    state = hand_state(repository)
    card = in_hand(state, LUSTER_DRAGON)
    execute(state, PlayerAction.set_monster(MINE, card))

    mine_view = GameStateView.from_state(state, viewer=MINE).me.monster_zone
    their_view = GameStateView.from_state(state, viewer=THEIRS).opponent.monster_zone

    assert mine_view.size == their_view.size == 1
    owner_card = mine_view.occupied()[0]
    hidden_card = their_view.occupied()[0]

    assert owner_card.card_id == LUSTER_DRAGON
    assert owner_card.name
    assert hidden_card.card_id is None
    assert hidden_card.name is None
    assert hidden_card.definition is None
    # 자리와 표시 형식은 숨기지 않는다 — 공격 대상으로 고를 수 있어야 한다.
    assert hidden_card.instance_id == card
    assert hidden_card.position is Position.FACEDOWN_DEFENSE
    assert hidden_card.face_up is False


@pytest.mark.real_card
def test_24_a_set_spell_is_hidden_the_same_way(repository):
    state = hand_state(repository, hand=(TRAP_HOLE,))
    card = in_hand(state, TRAP_HOLE)
    execute(state, PlayerAction.set_spell_trap(MINE, card))

    hidden = (
        GameStateView.from_state(state, viewer=THEIRS).opponent.spell_zone.occupied()[0]
    )
    assert hidden.instance_id == card
    assert hidden.card_id is None
    assert hidden.position is Position.FACEDOWN


@pytest.mark.real_card
def test_25_the_opponent_cannot_read_the_set_card_through_validation(repository):
    """
    검증을 반복해서 뒷면을 읽을 수 없다 (ADR-007).

    상대의 뒷면 몬스터를 **자기 것처럼** 세트/소환하려 해도 돌아오는 것은
    "컨트롤러가 아니다" 하나이고, 그 카드가 무엇인지는 새지 않는다.
    """
    state = hand_state(repository)
    card = in_hand(state, LUSTER_DRAGON)
    execute(state, PlayerAction.set_monster(MINE, card))
    state.turn.turn_number, state.turn.turn_player = 2, THEIRS
    state.turn.set_phase(Phase.MAIN1)

    result = validate(state, PlayerAction.set_monster(THEIRS, card), viewer=THEIRS)
    assert result.validity is ActionValidity.INVALID
    assert result.code in (
        ValidationCode.SOURCE_NOT_CONTROLLED,
        ValidationCode.SOURCE_WRONG_ZONE,
    )
    assert str(LUSTER_DRAGON) not in result.reason


# ======================================================================
# 26~28. 안전 (§16 · §17)
# ======================================================================


@pytest.mark.real_card
def test_26_a_refused_set_leaves_the_board_untouched(repository):
    """거절된 세트는 **아무것도** 바꾸지 않는다 — 권리도 쓰지 않는다."""
    state = hand_state(repository, hand=(LUSTER_DRAGON,), phase=Phase.BATTLE)
    action = PlayerAction.set_monster(MINE, in_hand(state, LUSTER_DRAGON))
    before = snapshot(state)

    assert validate(state, action).validity is ActionValidity.INVALID
    assert snapshot(state) == before
    assert not state.rule_uses.used(1, MINE, RuleActionKind.NORMAL_SUMMON)


@pytest.mark.real_card
def test_27_a_set_on_a_clone_does_not_touch_the_original(repository):
    """
    시뮬레이션이 실제 판을 바꾸지 않는다 (§17).

    ``clone()`` 은 난수원까지 복제하므로 사본에서 뽑은 것이 원본의 뽑기 수에
    남지 않는다 — 탐색이 반드시 이것을 써야 하는 이유다.
    """
    state = hand_state(repository)
    before = snapshot(state)

    copy = state.clone()
    execute(copy, PlayerAction.set_monster(MINE, in_hand(copy, LUSTER_DRAGON)))

    assert len(copy.player(MINE).monster_zone) == 1
    assert len(state.player(MINE).monster_zone) == 0
    assert snapshot(state) == before
    assert not state.rule_uses.used(1, MINE, RuleActionKind.NORMAL_SUMMON)
    assert copy.rule_uses.used(1, MINE, RuleActionKind.NORMAL_SUMMON)


@pytest.mark.real_card
def test_28_the_same_set_on_the_same_board_gives_the_same_result(repository):
    """결정적이다 — 같은 판에 같은 세트면 판도 델타도 같다."""
    results = []
    for _ in range(3):
        state = hand_state(repository)
        executed = execute(
            state, PlayerAction.set_monster(MINE, in_hand(state, LUSTER_DRAGON))
        )
        results.append(
            (snapshot(state), tuple(d.canonical_state() for d in executed.deltas))
        )
    assert results[0] == results[1] == results[2]


def test_29_the_delta_is_immutable():
    """델타는 **불변**이다 — 기록을 나중에 고칠 수 없다."""
    delta = CardSet(
        card=InstanceId(7),
        player=MINE,
        owner=MINE,
        source_player=MINE,
        source_zone=Zone.HAND,
        destination_zone=Zone.MZONE,
        destination_index=2,
        position=Position.FACEDOWN_DEFENSE,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        delta.destination_index = 0  # type: ignore[misc]


# ======================================================================
# 30. SET 으로 만든 수비 표시와의 전투 (§19)
# ======================================================================


def _drive_to(duel: Duel, *, want, seat: int, limit: int = 400):
    """
    **실제 후보 목록에서만** 골라 가며 원하는 행위를 찾는다.

    ``want(action)`` 이 참인 후보가 나오면 그것을 적용하고 멈춘다. 그때까지는
    ``END_PHASE`` 로 흘려보낸다 — 판을 손으로 고치지 않는다.
    """
    for _ in range(limit):
        if duel.is_over:
            return False
        if duel.advance() is not None:
            continue
        legal = duel.legal_actions()
        if not legal.allowed:
            return False
        if legal.seat == seat:
            found = [a for a in legal.allowed if want(a)]
            if found:
                assert duel.apply(found[0]).accepted
                return True
        passing = [
            a for a in legal.allowed if a.kind is PlayerActionKind.END_PHASE
        ]
        if not passing:
            return False
        duel.apply(passing[0])
    return False


@pytest.mark.real_card
def test_30_attacking_a_really_set_monster_resolves_against_its_defence(repository):
    """
    **§19 — 가짜 상태도 손으로 바꾼 표시 형식도 쓰지 않는다.**

    뒷면 수비 표시를 만드는 길이 ``legal_actions`` 의 ``SET_MONSTER`` 하나다.
    그렇게 만든 몬스터를 상대가 공격하면 **수비력**으로 판정된다
    (RULE-BATTLE-012).

        소울 타이거  ATK 0 / DEF 2100   — p0 이 세트한다
        수성의 기사  ATK 1900           — p1 이 소환해서 공격한다

    1900 < 2100 이므로 **어느 쪽도 파괴되지 않고** 공격한 쪽이 200 을 받는다
    (RULE-BATTLE-012). 공격력 0 으로 판정했다면 1900 데미지가 반대쪽으로
    갔을 것이므로, 숫자의 **크기와 방향** 둘이 "수비력으로 판정했다" 를
    증명한다.

    남은 한계: 이 엔진은 공격받은 뒷면 몬스터를 **앞면으로 뒤집지 않는다**
    (실제 데미지 스텝은 뒤집는다). 그 사실을 아래에서 그대로 적는다 —
    STRUCTURAL-116.
    """
    duel = Duel.start(
        repository,
        decks=([SOUL_TIGER] * 20, [LUSTER_DRAGON] * 20),
        seed=3,
    )

    # 1) p0 이 **실제 후보에서** 세트를 고른다.
    assert _drive_to(
        duel, want=lambda a: a.kind is PlayerActionKind.SET_MONSTER, seat=MINE
    ), "세트 후보에 도달하지 못했습니다"
    set_monster = _only(duel.state.player(MINE).monster_zone)
    assert set_monster.position is Position.FACEDOWN_DEFENSE
    assert set_monster.card_id == SOUL_TIGER

    # 2) p1 이 공격자를 **실제 후보에서** 소환한다.
    assert _drive_to(
        duel, want=lambda a: a.kind is PlayerActionKind.NORMAL_SUMMON, seat=THEIRS
    ), "상대가 소환할 자리에 도달하지 못했습니다"
    attacker = _only(duel.state.player(THEIRS).monster_zone)
    assert attacker.card_id == LUSTER_DRAGON

    # 3) p1 이 공격한다 — 후보에 있는 공격만 쓴다.
    before = duel.state.player(THEIRS).life_points
    assert _drive_to(
        duel,
        want=lambda a: a.kind is PlayerActionKind.ATTACK
        and a.target is not None
        and a.target.instance_id == set_monster.instance_id,
        seat=THEIRS,
    ), "세트한 몬스터를 노리는 공격 후보가 없습니다"

    # 4) 수비력으로 판정됐다.
    assert duel.state.player(THEIRS).life_points == before - 200
    assert duel.state.player(MINE).life_points == 8000

    # **어느 쪽도 파괴되지 않는다.** 공격 표시끼리와 다른 점이다 —
    # RULE-BATTLE-012 는 수비력이 더 높을 때 데미지만 말하고 파괴를 말하지
    # 않는다. (이 시험을 처음 쓸 때 공격자가 파괴된다고 적었는데, 그것이
    # 잘못된 가정이었다. 파괴는 공격 표시끼리의 전투에만 있다.)
    assert attacker.instance_id in [
        c.instance_id for c in duel.state.player(THEIRS).monster_zone
    ]
    survivor = _only(duel.state.player(MINE).monster_zone)
    assert survivor.instance_id == set_monster.instance_id

    # 5) 남은 한계를 숨기지 않는다 — STRUCTURAL-116.
    assert survivor.position is Position.FACEDOWN_DEFENSE, (
        "공격받은 뒷면 몬스터가 뒤집히지 않는다는 사실이 바뀌었다면 "
        "STRUCTURAL-116 을 다시 적어야 한다"
    )
