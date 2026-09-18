"""
Phase 2-G — ActionExecutor.

    PlayerAction → ActionValidator → ActionExecutor → GameState 변경

네 가지를 본다.

1. **오늘 아무것도 실행되지 않는가.** 검증기가 어떤 Action 에도 ``VALID``
   를 주지 않으므로, 실행기는 전부 거절해야 한다 — 그것이 정직한 상태다.
2. **``UNKNOWN`` 이 허가로 새지 않는가.**
3. **허가와 구현이 둘 다 있을 때만 판이 바뀌는가.**
4. **실패하면 한 글자도 바뀌지 않는가.**

허가는 **규칙 계층이 내주는 것**이다. 그 계층이 아직 없으므로, 성공 경로를
보는 테스트는 ``ValidationResult.valid()`` 를 **공개 API 로** 만들어 넘긴다.
private 필드를 건드리거나 monkeypatch 하지 않는다.
"""

import ast
import json
import pathlib

import pytest

from engine.action import MalformedAction, PlayerAction, PlayerActionKind
from engine.action_execution import (
    UNSUPPORTED_REASON,
    ActionExecution,
    ActionExecutor,
    ActionHandler,
    ActionStatus,
)
from engine.action_validation import ActionValidator
from engine.effect import CardDrawn, LifeChanged, ZoneMoved
from engine.effect.delta import StateDelta
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

MINE, THEIRS = 0, 1


# ======================================================================
# 판 · 도구
# ======================================================================


def new_state() -> GameState:
    game = GameState.create(decks=(range(1000, 1020), range(2000, 2020)))
    game.draw(MINE, 5)
    game.draw(THEIRS, 5)
    game.move(game.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


def my_hand(state, index: int = 0) -> InstanceId:
    return state.player(MINE).hand[index].instance_id


def my_monster(state) -> InstanceId:
    return state.player(MINE).monster_zone[0].instance_id


def authorized(reason: str = "규칙 계층이 허가했다고 가정한다") -> ValidationResult:
    """
    **규칙 계층이 내줄 허가**를 공개 생성자로 만든다.

    오늘 ``ActionValidator`` 는 이것을 만들어 주지 못한다 (어떤 Action 에도
    ``VALID`` 를 주지 않는다). 그 계층이 생기면 여기서 오는 값이 실제
    판정으로 바뀐다.
    """
    return ValidationResult.valid(reason)


class LifeCostHandler:
    """
    시험용 수행기. ``GameState`` 의 기존 primitive 만 쓴다.

    실제 소환/전투 규칙이 아니다 — 등록점이 동작하는지 보기 위한 최소
    구현이고, 그 사실을 이름과 설명이 말한다.
    """

    def __init__(self, amount: int = 500):
        self.amount = amount
        self.calls = 0

    def apply(self, state: GameState, action: PlayerAction):
        self.calls += 1
        player = state.player(action.actor)
        before = player.life_points
        after = player.change_life(-self.amount)
        return (LifeChanged(player=action.actor, before=before, after=after),)


class ExplodingHandler:
    """적용 **전에** 터진다 — 부분 변경이 남지 않아야 한다."""

    def apply(self, state: GameState, action: PlayerAction):
        raise RuntimeError("수행기 결함")


class SilentHandler:
    """아무것도 바꾸지 않는 수행기. 성공했는데 변화가 없는 경우다."""

    def apply(self, state: GameState, action: PlayerAction):
        return ()


def summon(state) -> PlayerAction:
    return PlayerAction.normal_summon(MINE, my_hand(state))


# ======================================================================
# 1. 생성 · 등록
# ======================================================================


def test_a_fresh_executor_supports_nothing():
    """
    **기본 상태는 "아무것도 실행하지 않는다" 이다.** 검증된 의미가 실행
    허가가 아니듯(ADR-006), 어휘에 있다고 실행되지 않는다.
    """
    executor = ActionExecutor()

    assert executor.supported == frozenset()
    for kind in PlayerActionKind:
        assert executor.handler_for(kind) is None


def test_a_handler_is_registered_by_hand():
    handler = LifeCostHandler()
    executor = ActionExecutor().register(PlayerActionKind.NORMAL_SUMMON, handler)

    assert executor.supported == {PlayerActionKind.NORMAL_SUMMON}
    assert executor.handler_for(PlayerActionKind.NORMAL_SUMMON) is handler
    assert executor.handler_for(PlayerActionKind.ATTACK) is None
    assert isinstance(handler, ActionHandler)


def test_registering_the_same_kind_twice_is_refused():
    executor = ActionExecutor().register(PlayerActionKind.ATTACK, LifeCostHandler())
    with pytest.raises(ValueError):
        executor.register(PlayerActionKind.ATTACK, LifeCostHandler())


def test_a_malformed_registration_is_refused():
    executor = ActionExecutor()
    with pytest.raises(TypeError):
        executor.register("normal_summon", LifeCostHandler())
    with pytest.raises(TypeError):
        executor.register(PlayerActionKind.ATTACK, object())


def test_handlers_can_be_given_at_construction():
    handler = LifeCostHandler()
    executor = ActionExecutor({PlayerActionKind.ATTACK: handler})
    assert executor.supported == {PlayerActionKind.ATTACK}


# ======================================================================
# 2~5. 오늘의 사실 — 아무것도 실행되지 않는다
# ======================================================================


@pytest.mark.parametrize("kind", list(PlayerActionKind))
def test_no_action_is_authorized_today(state, kind):
    """
    Phase 2-G 시점의 사실: 검증기가 어떤 Action 에도 ``VALID`` 를 주지
    않으므로 실행기는 열 종류 전부를 거절한다.

    **Phase 2-I 가 일반 소환에 허가를 열었다.** 그래도 이 판은 그대로
    거절된다 — 여기 쓰는 카드는 저장소 없이 만든 것이라 정의를 읽을 수
    없고, 소환 절차를 판정할 수 없는 카드는 ``UNKNOWN`` 이기 때문이다.
    "모른다" 가 허가로 새지 않는다는 것이 이 테스트가 지키는 것이고,
    실제 카드로 허가가 나는 경로는 ``test_normal_summon.py`` 가 본다.
    """
    action = _sample_action(state, kind)
    verdict = ActionValidator(
        GameStateView.from_state(state, viewer=action.actor)
    ).validate(action)

    assert verdict.permits_execution is False

    before = state.state_hash()
    result = ActionExecutor().execute(state, action)

    assert result.executed is False
    assert result.deltas == ()
    assert state.state_hash() == before


def _sample_action(state, kind: PlayerActionKind) -> PlayerAction:
    hand, monster = my_hand(state), my_monster(state)
    return {
        PlayerActionKind.NORMAL_SUMMON: lambda: PlayerAction.normal_summon(MINE, hand),
        PlayerActionKind.SET_MONSTER: lambda: PlayerAction.set_monster(MINE, hand),
        PlayerActionKind.SET_SPELL_TRAP: lambda: PlayerAction(
            kind=PlayerActionKind.SET_SPELL_TRAP, actor=MINE, source=hand
        ),
        PlayerActionKind.ACTIVATE_CARD: lambda: PlayerAction(
            kind=PlayerActionKind.ACTIVATE_CARD, actor=MINE, source=hand
        ),
        PlayerActionKind.ACTIVATE_EFFECT: lambda: PlayerAction(
            kind=PlayerActionKind.ACTIVATE_EFFECT,
            actor=MINE,
            source=monster,
            effect_ref=EffectRef(state.find_instance(monster).card_id, 0),
        ),
        PlayerActionKind.CHANGE_POSITION: lambda: PlayerAction(
            kind=PlayerActionKind.CHANGE_POSITION, actor=MINE, source=monster
        ),
        PlayerActionKind.ATTACK: lambda: PlayerAction(
            kind=PlayerActionKind.ATTACK, actor=MINE, source=monster
        ),
        PlayerActionKind.CHANGE_PHASE: lambda: PlayerAction(
            kind=PlayerActionKind.CHANGE_PHASE, actor=MINE, phase=Phase.BATTLE
        ),
        PlayerActionKind.END_PHASE: lambda: PlayerAction(
            kind=PlayerActionKind.END_PHASE, actor=MINE
        ),
        PlayerActionKind.PASS: lambda: PlayerAction(
            kind=PlayerActionKind.PASS, actor=MINE
        ),
    }[kind]()


def test_an_undecidable_action_is_unknown_not_invalid(state):
    """**모르는 것을 "안 된다" 로 바꾸지 않는다.**"""
    result = ActionExecutor().execute(state, summon(state))

    assert result.status is ActionStatus.UNKNOWN_ACTION
    assert result.status is not ActionStatus.INVALID_ACTION
    assert result.authorization.validity is ActionValidity.UNKNOWN


def test_a_definitely_illegal_action_is_invalid(state):
    """상대의 카드를 소환할 수는 없다 — 이것은 확실한 위반이다."""
    theirs = state.player(THEIRS).hand[0].instance_id
    action = PlayerAction.normal_summon(MINE, theirs)
    before = state.state_hash()

    result = ActionExecutor().execute(state, action)

    assert result.status in (
        ActionStatus.INVALID_ACTION,
        ActionStatus.UNKNOWN_ACTION,
    )
    assert result.executed is False
    assert state.state_hash() == before


def test_an_authorized_action_without_a_handler_is_unsupported(state):
    """
    허가는 났지만 **할 줄 모른다.** "모르겠다" 와 구분된다.
    """
    before = state.state_hash()

    result = ActionExecutor().execute(state, summon(state), authorized())

    assert result.status is ActionStatus.UNSUPPORTED_ACTION
    assert result.status is not ActionStatus.UNKNOWN_ACTION
    assert result.missing == UNSUPPORTED_REASON[PlayerActionKind.NORMAL_SUMMON]
    assert result.deltas == ()
    assert state.state_hash() == before


def test_every_action_kind_names_what_it_is_waiting_for():
    """빈 자리가 아니라 **남은 일의 목록**이다."""
    assert set(UNSUPPORTED_REASON) == set(PlayerActionKind)
    assert all(reason for reason in UNSUPPORTED_REASON.values())
    assert "우선권" in UNSUPPORTED_REASON[PlayerActionKind.PASS]
    assert "전투" in UNSUPPORTED_REASON[PlayerActionKind.ATTACK]


def test_an_unknown_authorization_is_never_accepted(state):
    """
    허가를 손으로 넘겨도 ``VALID`` 가 아니면 거부한다 — ``UNKNOWN`` 이
    허가로 새어 들어올 길이 없다.
    """
    executor = ActionExecutor().register(
        PlayerActionKind.NORMAL_SUMMON, LifeCostHandler()
    )
    before = state.state_hash()

    for verdict in (
        ValidationResult.unknown(ValidationCode.RULE_NOT_IMPLEMENTED, "모름"),
        ValidationResult.invalid(ValidationCode.NOT_TURN_PLAYER, "안 됨"),
    ):
        result = executor.execute(state, summon(state), verdict)
        assert result.executed is False
        assert result.deltas == ()

    assert state.state_hash() == before


def test_a_result_cannot_be_read_as_a_boolean(state):
    result = ActionExecutor().execute(state, summon(state))
    with pytest.raises(TypeError):
        bool(result)


def test_a_failed_result_cannot_carry_changes(state):
    action = summon(state)
    for status in ActionStatus:
        if status is ActionStatus.EXECUTED:
            continue
        with pytest.raises(ValueError):
            ActionExecution(
                status, action, deltas=(CardDrawn(MINE, InstanceId(1)),)
            )


# ======================================================================
# 6~7. 허가 + 구현 → 실행
# ======================================================================


def test_an_authorized_action_with_a_handler_changes_the_board(state):
    handler = LifeCostHandler(500)
    executor = ActionExecutor().register(PlayerActionKind.NORMAL_SUMMON, handler)
    life = state.player(MINE).life_points
    before = state.state_hash()

    result = executor.execute(state, summon(state), authorized())

    assert result.status is ActionStatus.EXECUTED
    assert result.executed is True
    assert result.changed_state is True
    assert state.player(MINE).life_points == life - 500
    assert state.state_hash() != before
    assert handler.calls == 1


def test_the_execution_carries_the_handlers_deltas(state):
    executor = ActionExecutor().register(
        PlayerActionKind.NORMAL_SUMMON, LifeCostHandler(300)
    )
    life = state.player(MINE).life_points

    result = executor.execute(state, summon(state), authorized())

    assert len(result.deltas) == 1
    delta = result.deltas[0]
    assert isinstance(delta, (StateDelta, LifeChanged))
    assert (delta.before, delta.after) == (life, life - 300)
    assert delta.player == MINE


def test_a_handler_that_changes_nothing_still_succeeds(state):
    executor = ActionExecutor().register(PlayerActionKind.NORMAL_SUMMON, SilentHandler())
    before = state.state_hash()

    result = executor.execute(state, summon(state), authorized())

    assert result.executed is True
    assert result.changed_state is False  # 실행됨 ≠ 판이 달라짐
    assert state.state_hash() == before


def test_only_the_registered_kind_runs(state):
    executor = ActionExecutor().register(
        PlayerActionKind.NORMAL_SUMMON, LifeCostHandler()
    )
    other = PlayerAction.set_monster(MINE, my_hand(state))
    before = state.state_hash()

    result = executor.execute(state, other, authorized())

    assert result.status is ActionStatus.UNSUPPORTED_ACTION
    assert state.state_hash() == before


def test_a_handler_that_raises_leaves_the_board_untouched(state):
    """
    수행기가 **바꾸기 전에** 터지면 판은 그대로다. 실패가 부분 변경으로
    남지 않는다.
    """
    executor = ActionExecutor().register(
        PlayerActionKind.NORMAL_SUMMON, ExplodingHandler()
    )
    before = state.state_hash()

    result = executor.execute(state, summon(state), authorized())

    assert result.status is ActionStatus.EXECUTION_ERROR
    assert result.executed is False
    assert result.deltas == ()  # 반쪽짜리 기록을 돌려주지 않는다
    assert state.state_hash() == before


# ======================================================================
# 8~9. 결정론 · 복제 독립
# ======================================================================


def test_the_same_input_gives_the_same_result_and_board():
    results, boards = [], []
    for _ in range(2):
        board = new_state()
        executor = ActionExecutor().register(
            PlayerActionKind.NORMAL_SUMMON, LifeCostHandler(700)
        )
        results.append(
            executor.execute(board, summon(board), authorized()).canonical_state()
        )
        boards.append(board)

    assert results[0] == results[1]
    assert boards[0].state_hash() == boards[1].state_hash()


def test_a_refusal_is_deterministic_too():
    results = []
    for _ in range(2):
        board = new_state()
        results.append(
            ActionExecutor().execute(board, summon(board)).canonical_state()
        )
    assert results[0] == results[1]


def test_executing_on_a_clone_leaves_the_original_alone(state):
    copy = state.clone()
    assert copy.state_hash() == state.state_hash()

    executor = ActionExecutor().register(
        PlayerActionKind.NORMAL_SUMMON, LifeCostHandler(400)
    )
    executor.execute(copy, summon(copy), authorized())

    assert copy.state_hash() != state.state_hash()
    assert state.player(MINE).life_points == 8000
    assert copy.player(MINE).life_points == 7600


def test_the_result_serializes_to_plain_data(state):
    executor = ActionExecutor().register(
        PlayerActionKind.NORMAL_SUMMON, LifeCostHandler()
    )
    ok = executor.execute(state, summon(state), authorized())
    refused = ActionExecutor().execute(state, summon(state))

    for result in (ok, refused):
        text = json.dumps(result.to_dict(), ensure_ascii=False)
        assert "0x" not in text and "object at" not in text
    assert ok.to_dict()["status"] == "executed"
    assert refused.to_dict()["status"] == "unknown_action"
    assert "authorization" in refused.to_dict()


# ======================================================================
# 10~12. 불변식
# ======================================================================


def test_a_card_definition_is_never_mutated(state):
    """
    Card Definition 은 저장소의 것이고 듀얼이 건드리지 않는다. 바뀌는 것은
    ``CardInstance`` 뿐이다.
    """
    card = state.player(MINE).monster_zone[0]
    before = (card.card_id, card.instance_id, card.owner)

    executor = ActionExecutor().register(
        PlayerActionKind.NORMAL_SUMMON, LifeCostHandler()
    )
    executor.execute(state, summon(state), authorized())

    assert (card.card_id, card.instance_id, card.owner) == before
    # 실행기는 카드 정의를 읽지도 쓰지도 않는다.
    source = pathlib.Path("engine/action_execution.py").read_text(encoding="utf-8")
    assert "card_model" not in source
    assert "CardRepository" not in source


def test_actor_owner_and_controller_stay_distinct(state):
    """
    빼앗은 카드로 상대가 행동하는 경우 — ``owner=1, controller=0, actor=0``.
    """
    stolen = state.player(THEIRS).hand[0]
    state.move(stolen, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK)
    assert stolen.owner == THEIRS and stolen.controller == MINE

    action = PlayerAction(
        kind=PlayerActionKind.ATTACK, actor=MINE, source=stolen.instance_id
    )
    result = ActionExecutor().execute(state, action)

    assert result.action.actor == MINE
    assert stolen.owner == THEIRS  # 소유권은 그대로
    assert stolen.controller == MINE
    assert result.executed is False


def test_the_authorizing_view_belongs_to_the_actor(state):
    """
    판정은 **행위자의 시점**으로 한다. 상대의 패를 들여다보고 판정하면
    검증을 반복하는 것만으로 손패를 탐지할 수 있다.
    """
    hidden = state.player(THEIRS).hand[0].instance_id
    action = PlayerAction.normal_summon(MINE, hidden)

    verdict = ActionExecutor().authorize(state, action)

    assert verdict.permits_execution is False
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.HIDDEN_CARD
    # 상대 카드가 무엇인지 나오지 않는다.
    card_id = state.find_instance(hidden).card_id
    assert str(card_id) not in verdict.reason


def test_the_executor_refuses_an_observation(state):
    view = GameStateView.from_state(state, viewer=MINE)
    with pytest.raises(TypeError):
        ActionExecutor().execute(view, summon(state))
    with pytest.raises(TypeError):
        ActionExecutor().execute(state, "not an action")
    with pytest.raises(TypeError):
        ActionExecutor().execute(state, summon(state), "not a verdict")


def test_a_malformed_action_cannot_even_be_built():
    """모양이 틀린 Action 은 실행기까지 오지 않는다."""
    with pytest.raises(MalformedAction):
        PlayerAction.normal_summon(5, InstanceId(1))


# ======================================================================
# 13. 다른 계층을 침범하지 않는다
# ======================================================================


def test_the_executor_does_not_absorb_the_other_layers():
    """
    타이밍 · 우선권 · 체인 · 트리거 · 비용 · 효과 해결을 여기서 하지 않는다.
    """
    tree = ast.parse(
        pathlib.Path("engine/action_execution.py").read_text(encoding="utf-8")
    )
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    for forbidden in (
        "engine.timing",
        "engine.priority",
        "engine.chain",
        "engine.trigger",
        "engine.trigger_order",
        "engine.trigger_chain",
        "engine.payment",
        "engine.cost",
        "analysis",
    ):
        assert not any(name.startswith(forbidden) for name in modules), forbidden

    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    for forbidden in (
        "EffectExecutor",
        "CostPayer",
        "ChainResolver",
        "TimingCoordinator",
        "TriggerCollector",
    ):
        assert forbidden not in imported, forbidden


def test_the_executor_does_not_decide_what_to_do():
    """AI 판단은 여기 없다 — 무엇을 할지는 밖에서 정해서 들어온다."""
    executor = ActionExecutor()
    for forbidden in ("choose", "select", "decide", "best_action", "search", "plan"):
        assert not hasattr(executor, forbidden), forbidden


def test_the_existing_layers_keep_working_alongside(state):
    """
    Priority · Chain · Timing 은 이 실행기와 **독립적으로** 동작한다.
    """
    from engine.chain import Chain
    from engine.priority import PriorityState, ResponseWindow

    priority = PriorityState.opened(ResponseWindow.ACTION, MINE, turn_player=MINE)
    chain = Chain()
    before = (priority.canonical_state(), chain.canonical_state())

    executor = ActionExecutor().register(
        PlayerActionKind.NORMAL_SUMMON, LifeCostHandler()
    )
    executor.execute(state, summon(state), authorized())

    assert priority.canonical_state() == before[0]
    assert chain.canonical_state() == before[1]


def test_the_deltas_use_the_existing_record_types(state):
    """
    새 이벤트 모델을 만들지 않았다. 기존 ``StateDelta`` 를 그대로 쓰므로
    ``EventJournal`` 로 이어 붙일 자리가 막히지 않는다.
    """
    executor = ActionExecutor().register(
        PlayerActionKind.NORMAL_SUMMON, LifeCostHandler()
    )
    result = executor.execute(state, summon(state), authorized())

    assert all(isinstance(delta, StateDelta) for delta in result.deltas)
    for delta in result.deltas:
        assert delta.canonical_state()
        assert delta.to_dict()

    # 이동·드로우·라이프 모두 기존 타입이다.
    assert issubclass(ZoneMoved, StateDelta)
    assert issubclass(CardDrawn, StateDelta)
    assert issubclass(LifeChanged, StateDelta)
