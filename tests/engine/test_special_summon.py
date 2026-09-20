"""
Phase 2-T — 특수 소환의 **공통 실행 경로**.

    PlayerAction(SPECIAL_SUMMON)
        ↓  ActionValidator          해도 되는가 → **언제나 UNKNOWN**
        ↓  ActionExecutor           허가된 것만 넘긴다
        ↓  SpecialSummonHandler
        ↓  SummonProcedure          계획 → 적용 → 확인  (일반 소환과 **같은 코드**)
    GameState  +  MonsterSummoned(summon=SPECIAL)
        ↓  EventReader
    TimingEvent(MONSTER_SUMMONED)  →  TriggerCandidate

이 파일이 지키려는 것은 넷이다.

1. **소환법을 구현한 것이 아니다.** "이 카드를 특수 소환할 수 있는가" 는
   여전히 모르고, 모르는 것은 허가가 아니다.
2. **일반 소환과 같은 코드를 쓴다.** 복사한 두 번째 시스템이 아니다.
3. **소환권을 먹지 않는다.**
4. **체인을 만들지 않는다.** 사건까지만 내보내고 트리거 수집은 밖의 일이다.
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionExecutor, ActionStatus
from engine.action_validation import ActionValidator
from engine.effect.delta import MonsterSummoned, SummonKind
from engine.effect.library import EFFECT_LIBRARY
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.normal_summon import (
    NORMAL_SUMMON_PROCEDURE,
    NormalSummonError,
    summoning_executor,
)
from engine.special_summon import (
    SPECIAL_SUMMON_FROM_ZONES,
    SPECIAL_SUMMON_POSITION,
    SPECIAL_SUMMON_PROCEDURE,
    SPECIAL_SUMMON_TO_ZONE,
    SpecialSummonError,
    SpecialSummonExecutor,
    SpecialSummonHandler,
    special_summoning_executor,
)
from engine.state.game_state import GameState
from engine.state.rule_usage import RuleActionKind
from engine.summon import SummonError, SummonPlacement, SummonProcedure, summon_executor
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
)
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1

FEATHERMAN = 21844576  # 엘리멘틀 히어로 페더맨 — 통상 몬스터
BURSTINATRIX = 58932615  # 엘리멘틀 히어로 버스트레이디 — 다른 통상 몬스터
DARK_HOLE = 53129443  # 블랙홀 — 마법 카드 (몬스터가 아닌 것)

#: **테스트가 명시적으로 건네는 허가.** 특수 소환 조건 계층을 대신하지
#: 않는다 — "이 판정의 책임은 건넨 쪽에 있다" 를 값으로 적는 것뿐이다
#: (Phase 2-Q · 2-S 와 같은 자리).
GRANTED = ValidationResult.valid("테스트가 특수 소환 조건을 허가했다")


# ======================================================================
# 판 · 도구
# ======================================================================


def new_state(repository) -> GameState:
    """
    p0(MINE) 패: 페더맨 ×2 · 버스트레이디 · 블랙홀
             묘지: 페더맨 1장 · 제외: 페더맨 1장
    p1(THEIRS) 패: 페더맨 ×3 (가려져 있다)
    """
    game = GameState.create(
        repository,
        decks=(
            [FEATHERMAN, FEATHERMAN, BURSTINATRIX, DARK_HOLE]
            + [FEATHERMAN] * 16,
            [FEATHERMAN] * 20,
        ),
    )
    game.draw(MINE, 6)
    game.draw(THEIRS, 3)
    # 묘지에 몬스터 한 장 — 패가 아닌 자리에서도 나오는지 보려고.
    game.move(game.player(MINE).hand[-1], Zone.GRAVE, to_player=MINE)
    # 제외 존에 한 장 — **보이지만 아직 옮기지 못한** 자리다.
    game.move(game.player(MINE).hand[-1], Zone.REMOVED, to_player=MINE)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def hand_card(state: GameState, card_id: int = FEATHERMAN) -> InstanceId:
    for card in state.player(MINE).hand:
        if card.card_id == card_id:
            return card.instance_id
    raise AssertionError(f"패에 {card_id} 가 없습니다.")


def grave_card(state: GameState) -> InstanceId:
    return state.player(MINE).grave[0].instance_id


def banished_card(state: GameState) -> InstanceId:
    """제외된 카드 — **보이지만** 이번 단계가 옮기지 못한 자리."""
    return state.player(MINE).removed[0].instance_id


def their_hand_card(state: GameState) -> InstanceId:
    return state.player(THEIRS).hand[0].instance_id


def summon(state: GameState, card: InstanceId | None = None) -> PlayerAction:
    return PlayerAction.special_summon(
        MINE, card if card is not None else hand_card(state)
    )


def validate(state: GameState, action: PlayerAction) -> ValidationResult:
    return ActionValidator(
        GameStateView.from_state(state, viewer=action.actor)
    ).validate(action)


def execute(state: GameState, action: PlayerAction, *, granted: bool = True):
    return special_summoning_executor().execute(
        state, action, authorization=GRANTED if granted else None
    )


def fill_monster_zone(state: GameState, player: int = MINE) -> None:
    """몬스터 존을 가득 채운다. 카드는 덱에서 가져온다."""
    zone = state.zone(player, Zone.MZONE)
    while zone.free_slots():
        state.move(
            state.player(player).deck[0],
            Zone.MZONE,
            to_player=player,
            index=zone.free_slots()[0],
            position=Position.FACEUP_ATTACK,
        )


# ======================================================================
# A. 어휘 — 특수 소환이 일반 소환과 다른 것임을 값으로 말한다
# ======================================================================


def test_a_special_summon_is_its_own_action_kind():
    assert PlayerActionKind.SPECIAL_SUMMON is not PlayerActionKind.NORMAL_SUMMON
    assert PlayerActionKind.SPECIAL_SUMMON.value == "special_summon"


def test_a_the_action_carries_only_stable_identity():
    """§4 — Action 에 객체 참조를 넣지 않는다."""
    action = PlayerAction.special_summon(MINE, InstanceId(3))

    assert isinstance(action.source, InstanceId)
    assert action.targets == ()
    assert action.effect_ref is None
    assert action.canonical_state()  # 값만으로 직렬화된다


def test_a_the_summon_kind_does_not_claim_a_method():
    """
    §7 — "어떤 카드가 특수 소환되었는가" 와 "어떤 방법으로" 는 다른 질문이다.
    융합 · 싱크로 · 엑시즈 · 링크는 각자의 절차가 생길 때 이름을 갖는다.
    """
    assert [k.value for k in SummonKind] == ["normal", "special"]


def test_a_the_procedure_says_what_it_supports():
    assert SPECIAL_SUMMON_FROM_ZONES == frozenset({Zone.HAND, Zone.GRAVE})
    assert SPECIAL_SUMMON_TO_ZONE is Zone.MZONE
    assert SPECIAL_SUMMON_PROCEDURE.summon is SummonKind.SPECIAL
    assert SPECIAL_SUMMON_PROCEDURE.kind is PlayerActionKind.SPECIAL_SUMMON


# ======================================================================
# B. 검증 — 조건을 모른다는 것이 허가가 아니다
# ======================================================================


@requires_official_db
def test_b_the_validator_never_authorizes_a_special_summon(state):
    """
    **이 테스트가 깨지는 날은 소환 조건 계층이 생긴 날이다.**

    "이 카드를 특수 소환할 수 있는가" 는 카드마다 다르고, 그것을 읽는
    계층이 없다.
    """
    verdict = validate(state, summon(state))

    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.permits_execution is False
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "special-summon-condition" in verdict.missing_rule


@requires_official_db
def test_b_without_a_grant_nothing_is_summoned(state):
    before = state.state_hash()

    result = execute(state, summon(state), granted=False)

    assert result.status is ActionStatus.UNKNOWN_ACTION
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_b_a_non_monster_is_definitely_refused(state):
    """
    **"모른다" 와 "안 된다" 를 나눈다.** 마법 카드를 몬스터 존에 놓는 것은
    조건 미상이 아니라 확정된 위반이다.
    """
    verdict = validate(state, summon(state, hand_card(state, DARK_HOLE)))

    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.SOURCE_WRONG_CARD_TYPE


@requires_official_db
def test_b_someone_elses_card_is_definitely_refused(state):
    verdict = validate(state, summon(state, their_hand_card(state)))

    # 상대의 패는 관측에 없다 — **없는 것이 아니라 못 보는 것**이다.
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.HIDDEN_CARD


@requires_official_db
def test_b_a_full_monster_zone_is_definitely_refused(state):
    fill_monster_zone(state)

    verdict = validate(state, summon(state))

    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.ZONE_FULL


@requires_official_db
def test_b_an_unsupported_source_zone_is_unknown_not_illegal(state):
    """
    §10 — 제외 존에서 나오는 특수 소환은 **실제로 있다.** 우리가 아직 옮기지
    못한 것이고, ``INVALID`` 로 적으면 거짓이 된다.

    덱이 아니라 제외 존을 쓰는 이유: 덱은 자기 것이라도 **가려져 있어서**
    관측에 실리지 않고, 그러면 ``HIDDEN_CARD`` 로 먼저 걸린다. 그것은 또
    다른 사실이고 아래 ``test_g_3`` 이 따로 본다.
    """
    banished = banished_card(state)

    verdict = validate(state, summon(state, banished))

    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "REMOVED" in verdict.missing_rule


@requires_official_db
def test_b_a_card_in_the_deck_is_not_even_visible(state):
    """
    자기 덱이라도 관측에 없다 — "덱에서 특수 소환" 은 **다른 사실 둘**에
    걸린다: 보이지 않는다, 그리고 그 자리를 아직 옮기지 못했다.
    """
    from_deck = state.player(MINE).deck[0].instance_id

    verdict = validate(state, summon(state, from_deck))

    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.HIDDEN_CARD


@requires_official_db
def test_b_the_validator_does_not_look_at_the_normal_summon_right(state):
    """§12 — 특수 소환은 일반 소환권과 무관하다."""
    state.rule_uses.record(state.turn.turn_number, MINE, RuleActionKind.NORMAL_SUMMON)

    verdict = validate(state, summon(state))

    assert verdict.code is not ValidationCode.NORMAL_SUMMON_ALREADY_USED
    assert verdict.validity is ActionValidity.UNKNOWN  # 여전히 조건 미상일 뿐


# ======================================================================
# C. 실행 — 성공 경로
# ======================================================================


@requires_official_db
def test_c_a_granted_special_summon_moves_the_card(state):
    card = hand_card(state)
    before = state.state_hash()

    result = execute(state, summon(state, card))

    assert result.status is ActionStatus.EXECUTED
    assert state.locate(card).zone is Zone.MZONE
    assert state.state_hash() != before


@requires_official_db
def test_c_owner_and_controller_survive_the_summon(state):
    card = hand_card(state)
    instance = state.find_instance(card)
    owner_before, card_id_before = instance.owner, instance.card_id

    execute(state, summon(state, card))

    after = state.find_instance(card)
    assert after.instance_id == card  # 같은 CardInstance 다
    assert after.card_id == card_id_before
    assert after.owner == owner_before == MINE
    assert after.controller == MINE
    assert after.position is SPECIAL_SUMMON_POSITION


@requires_official_db
def test_c_a_monster_can_come_from_the_graveyard(state):
    """§10 — 패만이 아니다. 지금 옮긴 자리가 둘이라는 사실 그대로."""
    card = grave_card(state)

    result = execute(state, summon(state, card))

    assert result.status is ActionStatus.EXECUTED
    assert state.locate(card).zone is Zone.MZONE
    assert result.deltas[0].from_zone is Zone.GRAVE


@requires_official_db
def test_c_the_normal_summon_right_is_untouched(state):
    """§12 — **특수 소환은 소환권을 먹지 않는다.**"""
    execute(state, summon(state))

    assert len(state.rule_uses) == 0
    # 같은 턴에 일반 소환도 할 수 있다.
    normal = PlayerAction.normal_summon(MINE, hand_card(state))
    assert (
        validate(state, normal).code is not ValidationCode.NORMAL_SUMMON_ALREADY_USED
    )


def test_c_the_special_summon_module_never_touches_the_usage_registry():
    """구조적으로 불가능해야 한다 — 이름조차 나오지 않는다."""
    source = pathlib.Path("engine/special_summon.py").read_text("utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert "engine.state.rule_usage" not in imported
    assert "RuleUsageRegistry" not in used
    assert "rule_uses" not in used


@requires_official_db
def test_c_two_special_summons_in_a_row_are_possible(state):
    """소환권을 쓰지 않으므로 한 턴에 여러 번 나올 수 있다."""
    first, second = hand_card(state), grave_card(state)

    execute(state, summon(state, first))
    execute(state, summon(state, second))

    assert state.locate(first).zone is Zone.MZONE
    assert state.locate(second).zone is Zone.MZONE
    assert len(state.player(MINE).monster_zone) == 2


# ======================================================================
# D. MonsterSummoned — 사건이 의미를 잃지 않는다
# ======================================================================


@requires_official_db
def test_d_the_delta_says_it_was_a_special_summon(state):
    card = hand_card(state)

    result = execute(state, summon(state, card))
    delta = result.deltas[0]

    assert isinstance(delta, MonsterSummoned)
    assert delta.summon is SummonKind.SPECIAL
    assert delta.card == card
    assert delta.player == MINE
    assert delta.owner == MINE
    assert (delta.from_zone, delta.to_zone) == (Zone.HAND, Zone.MZONE)
    assert delta.position is SPECIAL_SUMMON_POSITION


@requires_official_db
def test_d_a_special_summon_is_not_a_normal_summon(state):
    """
    같은 자리에서 같은 자리로 가도 **다른 사건**이다 (ADR-002 가 파괴와
    묘지로 보내기를 가른 것과 같은 이유).
    """
    special = execute(state, summon(state, hand_card(state)))
    normal = summoning_executor().execute(
        state,
        PlayerAction.normal_summon(MINE, hand_card(state, BURSTINATRIX)),
        authorization=GRANTED,
    )

    assert special.deltas[0].summon is SummonKind.SPECIAL
    assert normal.deltas[0].summon is SummonKind.NORMAL
    assert special.deltas[0].canonical_state() != normal.deltas[0].canonical_state()


@requires_official_db
def test_d_the_event_reader_turns_it_into_a_summon_event(state):
    """§8 — 기존 통로를 그대로 쓴다. 새 EventBus 가 없다."""
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))

    result = execute(state, summon(state, hand_card(state)))
    observed = reader.read(result, actor=MINE)

    assert len(observed) == 1
    assert observed[0].timing.point is TimingPoint.MONSTER_SUMMONED
    assert observed[0].is_observable
    assert observed[0].event_id


@requires_official_db
def test_d_the_event_carries_the_turn_and_phase(state):
    """§7 — 사건이 언제 일어났는지 잃지 않는다."""
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))

    result = execute(state, summon(state, hand_card(state)))
    event = reader.read(result, actor=MINE)[0]

    assert event.context.turn_number == state.turn.turn_number
    assert event.context.phase is Phase.MAIN1
    assert event.instance == result.deltas[0].card
    assert event.actor == MINE


@requires_official_db
def test_d_a_summon_event_is_not_a_card_move(state):
    """
    ``CARD_MOVED`` 와 합치지 않는다 — "소환되었을 때" 와 "필드로 보내졌을
    때" 는 전혀 다른 사건이다.
    """
    result = execute(state, summon(state, hand_card(state)))
    timing = TimingEvent.from_delta(result.deltas[0])

    assert timing.point is TimingPoint.MONSTER_SUMMONED
    assert timing.point is not TimingPoint.CARD_MOVED


# ======================================================================
# E. Trigger pipeline — 사건까지만 내보낸다
# ======================================================================


@requires_official_db
def test_e_several_triggers_share_one_summon_event(state):
    """
    §9 — 하나의 ``MonsterSummoned`` 에서 여러 후보가 나와도 **같은 사건**
    에서 나왔다는 사실이 남아야 한다.
    """
    from engine.trigger import TriggerCollector

    result = execute(state, summon(state, hand_card(state)))
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))
    event = reader.read(result, actor=MINE)[0]

    registry = TriggerRegistry(
        (
            TriggerSpec(
                EffectRef(FEATHERMAN, 0),
                TimingPoint.MONSTER_SUMMONED,
                requirement=TriggerRequirement.OPTIONAL,
                activates_from=frozenset({Zone.MZONE}),
            ),
            TriggerSpec(
                EffectRef(FEATHERMAN, 1),
                TimingPoint.MONSTER_SUMMONED,
                requirement=TriggerRequirement.OPTIONAL,
                activates_from=frozenset({Zone.MZONE}),
            ),
        )
    )
    collected = TriggerCollector(
        GameStateView.from_state(state, viewer=MINE), registry
    ).collect(event.timing)

    assert len(collected.candidates) >= 2
    # 후보가 여럿이어도 **사건은 하나**다 — 그 관계가
    # ``TriggerCollection.event`` 하나로 남는다.
    assert collected.event.canonical_state() == event.timing.canonical_state()
    assert {c.point for c in collected.candidates} == {TimingPoint.MONSTER_SUMMONED}
    # 소환된 카드도 후보의 출처 중 하나다. **어느 카드들이 후보가 되는가**는
    # 트리거 계층의 질문이고 여기서 다시 정하지 않는다 (Phase 2-F-3-A).
    assert result.deltas[0].card in {c.source for c in collected.candidates}


def test_e_the_summon_layer_never_builds_a_chain():
    """§8 · §20 — 여기서 트리거를 모으거나 체인을 만들지 않는다."""
    for path in ("engine/special_summon.py", "engine/summon.py"):
        tree = ast.parse(pathlib.Path(path).read_text("utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        for module in ("engine.chain", "engine.trigger", "engine.trigger_chain"):
            assert module not in imported, path
        for name in (
            "ChainResolver",
            "TriggerCollector",
            "TriggerChainIntegrator",
            "Chain",
            "EffectExecutor",
        ):
            assert name not in used, (path, name)


# ======================================================================
# F. 일반 소환과 **같은 코드**를 쓴다
# ======================================================================


def test_f_both_summons_are_the_same_procedure_class():
    """§3 — 복사한 두 번째 시스템이 아니다."""
    assert isinstance(NORMAL_SUMMON_PROCEDURE, SummonProcedure)
    assert isinstance(SPECIAL_SUMMON_PROCEDURE, SummonProcedure)
    assert type(NORMAL_SUMMON_PROCEDURE) is type(SPECIAL_SUMMON_PROCEDURE)
    # 다른 것은 **값**뿐이다.
    assert NORMAL_SUMMON_PROCEDURE.summon is not SPECIAL_SUMMON_PROCEDURE.summon
    assert NORMAL_SUMMON_PROCEDURE.from_zones != SPECIAL_SUMMON_PROCEDURE.from_zones


def test_f_the_special_summon_module_defines_no_placement_logic():
    """자리 찾기 · 이동 · 착지 확인이 두 벌 있으면 한쪽만 고쳐지는 날이 온다."""
    tree = ast.parse(pathlib.Path("engine/special_summon.py").read_text("utf-8"))
    used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    assert "free_slots" not in used
    assert "move" not in used
    assert "locate" not in used


def test_f_the_errors_share_one_root():
    assert issubclass(SpecialSummonError, SummonError)
    assert issubclass(NormalSummonError, SummonError)
    assert SpecialSummonError is not NormalSummonError


def test_f_no_second_summon_engine_was_built():
    """§20 — 별도의 ``SpecialSummonEngine`` 을 만들지 않았다."""
    tree = ast.parse(pathlib.Path("engine/special_summon.py").read_text("utf-8"))
    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }

    assert defined == {
        "SpecialSummonError",
        "SpecialSummonExecutor",
        "SpecialSummonHandler",
    }
    for forbidden in ("GameState", "ActionExecutor", "SummonProcedure"):
        assert forbidden not in defined


def test_f_one_executor_can_know_both_summons():
    assert summon_executor().supported == frozenset(
        {PlayerActionKind.NORMAL_SUMMON, PlayerActionKind.SPECIAL_SUMMON}
    )
    # 기본 실행기는 여전히 비어 있다 (ADR-006).
    assert ActionExecutor().supported == frozenset()


# ======================================================================
# G. 실패 행렬 (§15)
# ======================================================================


@requires_official_db
def test_g_1_an_empty_source_has_nothing_to_summon(state):
    """소환할 카드를 지목하지 않은 Action 은 **모양부터** 틀렸다."""
    action = PlayerAction(kind=PlayerActionKind.SPECIAL_SUMMON, actor=MINE)
    before = state.state_hash()

    verdict = validate(state, action)

    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.SOURCE_REQUIRED
    with pytest.raises(SpecialSummonError):
        SpecialSummonExecutor().apply(state, action)
    assert state.state_hash() == before


@requires_official_db
def test_g_2_a_full_zone_stops_the_execution(state):
    fill_monster_zone(state)
    card = hand_card(state)
    before = state.state_hash()

    with pytest.raises(SpecialSummonError):
        SpecialSummonExecutor().apply(state, summon(state, card))

    assert state.locate(card).zone is Zone.HAND
    assert state.state_hash() == before


@requires_official_db
def test_g_3_an_instance_that_never_existed_is_hidden_not_missing(state):
    before = state.state_hash()

    verdict = validate(state, summon(state, InstanceId(9999)))

    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.HIDDEN_CARD
    assert state.state_hash() == before


@requires_official_db
def test_g_4_the_opponents_hand_cannot_be_probed(state):
    """§17 — 가려진 카드는 "없다" 가 아니라 "못 본다" 다."""
    verdict = validate(state, summon(state, their_hand_card(state)))

    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.HIDDEN_CARD


@requires_official_db
def test_g_5_an_unsupported_source_stops_the_execution(state):
    """덱에서 나오는 특수 소환은 아직 수행할 수 없다."""
    from_deck = state.player(MINE).deck[0].instance_id
    before = state.state_hash()

    with pytest.raises(SpecialSummonError):
        SpecialSummonExecutor().apply(state, summon(state, from_deck))

    assert state.locate(from_deck).zone is Zone.DECK
    assert state.state_hash() == before


@requires_official_db
def test_g_6_a_normal_summon_action_is_refused_by_the_special_procedure(state):
    """절차가 자기 행위만 수행한다 — 표를 잘못 타지 않는다."""
    action = PlayerAction.normal_summon(MINE, hand_card(state))
    before = state.state_hash()

    with pytest.raises(SpecialSummonError):
        SpecialSummonExecutor().apply(state, action)

    assert state.state_hash() == before


@requires_official_db
def test_g_7_a_stale_card_is_refused(state):
    """고른 뒤에 그 카드가 자리를 떠났다."""
    card = hand_card(state)
    action = summon(state, card)
    state.move(card, Zone.REMOVED, to_player=MINE)
    before = state.state_hash()

    with pytest.raises(SpecialSummonError):
        SpecialSummonExecutor().apply(state, action)

    assert state.locate(card).zone is Zone.REMOVED
    assert state.state_hash() == before


@requires_official_db
def test_g_8_a_card_the_actor_does_not_control_is_refused(state):
    card = their_hand_card(state)
    action = PlayerAction.special_summon(MINE, card)
    before = state.state_hash()

    with pytest.raises(SpecialSummonError):
        SpecialSummonExecutor().apply(state, action)

    assert state.state_hash() == before


@requires_official_db
def test_g_every_refusal_leaves_the_board_alone(state):
    """
    실패 갈래를 한 자리에서 돌린다. 전부 ``applied == ()`` · ``deltas == ()``
    · ``state_hash`` 불변.
    """
    cases = {
        "몬스터가 아님": lambda: summon(state, hand_card(state, DARK_HOLE)),
        "가려진 카드": lambda: summon(state, their_hand_card(state)),
        "없는 카드": lambda: summon(state, InstanceId(9999)),
        "지원하지 않는 자리": lambda: summon(state, banished_card(state)),
        "덱 안의 카드": lambda: summon(state, state.player(MINE).deck[0].instance_id),
    }
    for name, build in cases.items():
        action = build()
        before = state.state_hash()

        result = execute(state, action, granted=False)

        assert result.executed is False, name
        assert result.deltas == (), name
        assert state.state_hash() == before, name


# ======================================================================
# H. 결정론 · 복제 독립성
# ======================================================================


@requires_official_db
def test_h_the_same_input_gives_the_same_delta(repository):
    first, second = new_state(repository), new_state(repository)

    left = execute(first, summon(first, hand_card(first)))
    right = execute(second, summon(second, hand_card(second)))

    assert left.canonical_state() == right.canonical_state()
    assert first.state_hash() == second.state_hash()


@requires_official_db
def test_h_the_event_id_comes_from_the_content(repository):
    """§16 — 실행 순서에 따라 흔들리지 않는다."""
    first, second = new_state(repository), new_state(repository)

    left = EventReader(GameStateView.from_state(first, viewer=MINE)).read(
        execute(first, summon(first, hand_card(first))), actor=MINE
    )
    right = EventReader(GameStateView.from_state(second, viewer=MINE)).read(
        execute(second, summon(second, hand_card(second))), actor=MINE
    )

    assert [e.event_id for e in left] == [e.event_id for e in right]


@requires_official_db
def test_h_summoning_on_a_clone_leaves_the_original_alone(state):
    copy = state.clone()
    card = hand_card(copy)
    before = state.state_hash()

    result = execute(copy, summon(copy, card))

    assert result.status is ActionStatus.EXECUTED
    assert copy.locate(card).zone is Zone.MZONE
    assert state.locate(card).zone is Zone.HAND
    assert state.state_hash() == before


@requires_official_db
def test_h_planning_never_changes_the_board(state):
    before = state.state_hash()

    for _ in range(3):
        SpecialSummonExecutor().plan(state, summon(state, hand_card(state)))
        validate(state, summon(state))

    assert state.state_hash() == before


@requires_official_db
def test_h_the_slot_is_the_lowest_free_one(state):
    """
    🟠 STRUCTURAL-41 — 칸을 **고르지 않는다.** 일반 소환이 쓰던 방식을 그대로
    쓴다. 이것이 규칙이라고 주장하지 않는다.
    """
    execute(state, summon(state, hand_card(state)))
    second = grave_card(state)

    execute(state, summon(state, second))

    assert state.zone(MINE, Zone.MZONE).slot(0) is not None
    assert state.find_instance(second) is state.zone(MINE, Zone.MZONE).slot(1)


# ======================================================================
# I. 정보 경계 · 실제 카드
# ======================================================================


@requires_official_db
def test_i_a_refusal_names_no_hidden_card(state):
    hidden = state.player(THEIRS).hand[0]

    verdict = validate(state, summon(state, hidden.instance_id))
    text = str(verdict.to_dict())

    assert str(hidden.card_id) not in text


@requires_official_db
def test_i_the_summon_delta_shows_only_what_the_viewer_may_know(state):
    """
    소환은 **공개된 자리**에서 일어난다 — 앞면으로 나온 카드는 상대도 본다.
    숨길 것이 없다는 사실을 확인해 둔다.
    """
    card = hand_card(state)
    execute(state, summon(state, card))

    theirs = GameStateView.from_state(state, viewer=THEIRS)
    landed = theirs.find(card)

    assert landed is not None
    assert landed.card_id == FEATHERMAN  # 앞면이므로 보인다


def test_i_no_library_effect_special_summons_anything():
    """
    §14 — 실제 카드를 쓰려 했으나 조건을 만족하는 카드가 **없다.**

    라이브러리의 실행 가능한 효과 셋(욕망의 항아리 · 은혜의 단비 ·
    싸이크론) 중 특수 소환을 하는 것은 하나도 없고, 특수 소환하는 실제
    카드의 조건을 추측해서 구현하지 않는다. 그래서 이번 단계의 end-to-end
    는 **실제 카드 정체**(페더맨 · 버스트레이디)를 쓰되 소환 절차 자체는
    synthetic 시나리오로 검증한다.
    """
    from engine.effect.operation import OperationKind

    executable = [entry for entry in EFFECT_LIBRARY if entry.executable]
    kinds = {
        operation.kind
        for entry in executable
        for operation in entry.definition.operations
    }

    assert executable  # 실행 가능한 효과가 있기는 하다
    assert OperationKind.DRAW in kinds  # 드로우 · 라이프 · 파괴뿐이다
    assert not any("summon" in kind.value for kind in kinds)


@requires_official_db
def test_i_real_cards_are_summoned_as_themselves(state):
    """
    실제 카드 두 장(페더맨 · 버스트레이디)이 각자의 정체를 유지한 채 나온다.
    """
    feather, burst = hand_card(state), hand_card(state, BURSTINATRIX)

    execute(state, summon(state, feather))
    execute(state, summon(state, burst))

    assert state.find_instance(feather).card_id == FEATHERMAN
    assert state.find_instance(burst).card_id == BURSTINATRIX
    assert state.find_instance(feather).instance_id != state.find_instance(burst).instance_id


def test_i_the_handler_holds_no_rules_of_its_own():
    """§20 — 핸들러는 넘기는 것이 전부다."""
    handler = SpecialSummonHandler()

    assert isinstance(handler.executor, SpecialSummonExecutor)
    source = pathlib.Path("engine/special_summon.py").read_text("utf-8")
    for forbidden in ("def choose", "score", "policy", "random"):
        assert forbidden not in source
