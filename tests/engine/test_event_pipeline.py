"""
Phase 2-J — 사건 파이프라인.

    GameState 변경 → StateDelta → ObservedEvent → TriggerCollection

Phase 2-I 에서 판이 처음으로 바뀌었지만, 그 변화는 아무 데도 닿지 않았다.
이번 단계가 잇는 것은 **그 한 구간뿐이다.**

다섯 가지를 본다.

1. **소환과 페이즈 전이가 시점으로 옮겨지는가.** 옮길 이름이 없던 것이
   ``STRUCTURAL-39`` 였다.
2. **사건 하나에 여러 후보가 붙는 관계가 보존되는가.**
3. **사건을 읽는 일이 판을 바꾸지 않는가.**
4. **관찰자가 볼 수 없는 것이 ``unchecked`` 로 남는가** — 후보 없음과
   확인 못 함은 다른 사실이다.
5. **여기서 멈추는가.** 체인도, 효과 실행도, 우선권 이동도 없다.
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction
from engine.effect.delta import (
    CardDrawn,
    LifeChanged,
    MonsterSummoned,
    PhaseChanged,
    StateDelta,
    SummonKind,
    ZoneMoved,
)
from engine.effect.operation import OperationKind
from engine.event_pipeline import (
    EventContext,
    EventObservation,
    EventPipeline,
    EventPipelineError,
    EventReader,
    ObservedEvent,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.normal_summon import summoning_executor
from engine.state.game_state import GameState
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerCollection,
    TriggerRegistry,
    TriggerSpec,
    TriggerStatus,
)
from engine.turn_progression import TurnProgressor
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1

FEATHERMAN = 21844576  # 엘리멘틀 히어로 페더맨 — 레벨 3 통상 몬스터
BLUE_EYES = 89631139  # 푸른 눈의 백룡 — 레벨 8 통상
DARK_HOLE = 53129443  # 블랙홀 — 마법 카드


# ======================================================================
# 판 · 도구
# ======================================================================


def new_state(repository) -> GameState:
    game = GameState.create(
        repository,
        decks=(
            [FEATHERMAN, FEATHERMAN, BLUE_EYES, DARK_HOLE] * 3,
            [BLUE_EYES, DARK_HOLE] * 6,
        ),
    )
    game.draw(MINE, 4)
    game.draw(THEIRS, 2)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


@pytest.fixture
def registry() -> TriggerRegistry:
    """
    **손으로 등록한다** — 카드 데이터에서 트리거를 뽑는 컴파일러는 없다
    (STRUCTURAL-7). 페더맨에게 "소환되었을 때" 선언 하나를 붙인다.
    """
    return TriggerRegistry().register(
        TriggerSpec(EffectRef(FEATHERMAN, 0), TimingPoint.MONSTER_SUMMONED)
    )


def view_of(state: GameState, viewer: int = MINE) -> GameStateView:
    return GameStateView.from_state(state, viewer=viewer)


def in_hand(state: GameState, card_id: int, player: int = MINE) -> InstanceId:
    return next(
        card.instance_id
        for card in state.player(player).hand
        if card.card_id == card_id
    )


def summon_execution(state: GameState, card_id: int = FEATHERMAN):
    return summoning_executor().execute(
        state, PlayerAction.normal_summon(MINE, in_hand(state, card_id))
    )


def a_summon_delta(card: int = 1, player: int = MINE) -> MonsterSummoned:
    return MonsterSummoned(
        SummonKind.NORMAL, InstanceId(card), player, player,
        Zone.HAND, Zone.MZONE, 0, Position.FACEUP_ATTACK,
    )


# ======================================================================
# 1. 소환 → 시점
# ======================================================================


def test_a_summon_delta_becomes_a_summon_timing_point():
    """**STRUCTURAL-39 의 핵심.** 여기서 예외가 나던 자리다."""
    event = TimingEvent.from_delta(a_summon_delta())

    assert event.point is TimingPoint.MONSTER_SUMMONED
    assert event.actor == MINE
    assert event.instance == InstanceId(1)


def test_a_summon_is_not_folded_into_a_card_move():
    """
    "소환되었을 때" 와 "필드로 보내졌을 때" 는 다른 사건이다. 한 시점으로
    합치면 트리거 계층이 영영 구분할 수 없다.
    """
    summoned = TimingEvent.from_delta(a_summon_delta())
    moved = TimingEvent.from_delta(
        ZoneMoved(OperationKind.SEND_TO_GRAVE, InstanceId(1), MINE,
                  Zone.HAND, MINE, Zone.GRAVE)
    )

    assert summoned.point is not moved.point
    assert summoned.point is TimingPoint.MONSTER_SUMMONED
    assert moved.point is TimingPoint.CARD_MOVED


def test_the_summon_event_keeps_the_card_and_the_players():
    delta = MonsterSummoned(
        SummonKind.NORMAL, InstanceId(7), MINE, THEIRS,
        Zone.HAND, Zone.MZONE, 2, Position.FACEUP_ATTACK,
    )
    event = TimingEvent.from_delta(delta)

    assert event.instance == InstanceId(7)
    assert event.delta.player == MINE  # 소환한 쪽 = 컨트롤러
    assert event.delta.owner == THEIRS  # 주인은 그대로
    assert event.delta.summon is SummonKind.NORMAL


def test_a_summon_is_not_a_card_movement_event():
    """
    ``CardMovement`` 는 **효과의 어휘**(``OperationKind``)를 들고 다닌다.
    소환은 효과가 아니므로 그 자리에 들어가지 않는다 — 대신 사건 종류가
    의미를 말한다.
    """
    event = TimingEvent.from_delta(a_summon_delta())

    assert event.movement is None
    assert event.operation is None
    assert event.from_zone is None
    assert event.instance is not None  # 그래도 카드 한 장의 사건이다


# ======================================================================
# 2. 페이즈 전이 → 시점
# ======================================================================


def test_a_phase_change_becomes_a_phase_timing_point():
    event = TimingEvent.from_delta(
        PhaseChanged(1, MINE, Phase.MAIN1, 1, MINE, Phase.BATTLE)
    )

    assert event.point is TimingPoint.PHASE_CHANGED
    assert event.delta.to_phase is Phase.BATTLE


def test_a_phase_change_names_no_actor():
    """
    페이즈 전이는 **규칙이 하는 일**이다. 턴 플레이어를 행위자로 적어 넣으면
    "그 사람이 한 일" 로 읽히고, 누가 선언했는가는 우선권 계층의 질문이다.
    """
    event = TimingEvent.from_delta(
        PhaseChanged(1, MINE, Phase.END, 2, THEIRS, Phase.DRAW)
    )

    assert event.actor is None
    assert event.instance is None
    assert event.delta.changes_turn is True


@requires_official_db
def test_a_turn_progression_result_can_be_read(state, registry):
    """Phase 2-H 의 결과도 같은 입구로 들어온다."""
    result = TurnProgressor().advance(state)
    events = EventReader(view_of(state)).read(result)

    assert len(events) == 1
    assert events[0].point is TimingPoint.PHASE_CHANGED
    assert events[0].is_observable is True
    assert events[0].actor is None


@requires_official_db
def test_reading_a_phase_change_does_not_move_the_board_again(state):
    """§16 — 사건을 읽는 것 자체는 판을 건드리지 않는다."""
    result = TurnProgressor().advance(state)
    after = state.state_hash()

    EventReader(view_of(state)).read(result)

    assert state.state_hash() == after


# ======================================================================
# 3. 실행 결과 → 사건
# ======================================================================


@requires_official_db
def test_a_summon_execution_becomes_one_observed_event(state):
    execution = summon_execution(state)
    events = EventReader(view_of(state)).read(execution)

    assert len(events) == 1
    event = events[0]
    assert event.point is TimingPoint.MONSTER_SUMMONED
    assert event.actor == MINE
    assert event.context.actor == MINE
    assert event.is_observable is True


@requires_official_db
def test_the_event_remembers_when_it_happened(state):
    """§5 — 턴 · 페이즈 · 턴 플레이어가 사건과 함께 남는다."""
    state.turn.set_phase(Phase.MAIN2)
    events = EventReader(view_of(state)).read(summon_execution(state))

    context = events[0].context
    assert context.turn_number == 1
    assert context.turn_player == MINE
    assert context.phase is Phase.MAIN2
    assert context.sequence == 0


@requires_official_db
def test_the_event_carries_the_instance_not_the_card_object(state):
    card = in_hand(state, FEATHERMAN)
    execution = summoning_executor().execute(
        state, PlayerAction.normal_summon(MINE, card)
    )
    event = EventReader(view_of(state)).read(execution)[0]

    assert event.instance == card
    assert isinstance(event.instance, InstanceId)
    assert not hasattr(event.delta, "card_instance")


def test_several_deltas_keep_their_order():
    """순서가 곧 사실이다 — 뒤섞으면 무엇이 먼저였는지 사라진다."""
    reader = EventReader(GameStateView.from_state(GameState.create(), viewer=MINE))
    events = reader.read_deltas(
        (
            CardDrawn(MINE, InstanceId(1)),
            a_summon_delta(2),
            LifeChanged(MINE, 8000, 7000),
        ),
        actor=MINE,
    )

    assert [e.point for e in events] == [
        TimingPoint.CARD_DRAWN,
        TimingPoint.MONSTER_SUMMONED,
        TimingPoint.LIFE_CHANGED,
    ]
    assert [e.context.sequence for e in events] == [0, 1, 2]


def test_a_delta_with_no_timing_name_is_kept_not_dropped():
    """
    옮길 이름이 없어도 **버리지 않는다.** "사건이 없었다" 와 "옮길 이름이
    없었다" 는 다른 사실이다.
    """
    reader = EventReader(GameStateView.from_state(GameState.create(), viewer=MINE))

    class _UnknownChange(StateDelta):
        @property
        def kind(self):
            return "unknown_change"

        def canonical_state(self):
            return ("unknown_change",)

        def to_dict(self):
            return {"kind": "unknown_change"}

        def describe_ko(self):
            return "아직 이름이 없는 변화"

    events = reader.read_deltas((_UnknownChange(),))

    assert len(events) == 1
    assert events[0].point is TimingPoint.UNIMPLEMENTED
    assert events[0].is_observable is False
    assert "_UnknownChange" in events[0].timing.note


def test_the_reader_refuses_a_result_without_deltas():
    reader = EventReader(GameStateView.from_state(GameState.create(), viewer=MINE))

    with pytest.raises(TypeError):
        reader.read(object())


def test_the_reader_refuses_a_mutable_board():
    """관측만 받는다 — 받는 순간 사건을 읽는 일이 판을 바꿀 수 있게 된다."""
    with pytest.raises(TypeError):
        EventReader(GameState.create())


# ======================================================================
# 4. 사건 식별자
# ======================================================================


@requires_official_db
def test_the_same_board_and_action_give_the_same_event_id(repository):
    first, second = new_state(repository), new_state(repository)

    left = EventReader(view_of(first)).read(summon_execution(first))[0]
    right = EventReader(view_of(second)).read(summon_execution(second))[0]

    assert left.event_id == right.event_id
    assert left.canonical_state() == right.canonical_state()


@requires_official_db
def test_a_clone_produces_the_same_event(state):
    copy = state.clone()
    original = EventReader(view_of(state)).read(summon_execution(state))[0]
    cloned = EventReader(view_of(copy)).read(summon_execution(copy))[0]

    assert original.event_id == cloned.event_id


def test_the_event_id_uses_no_addresses_or_clocks():
    """
    두 번 만든 같은 사건이 같은 값을 가져야 한다. 객체 주소나 시각이 섞여
    있으면 같을 수 없다.
    """
    context = EventContext(1, MINE, Phase.MAIN1, actor=MINE)
    left = ObservedEvent(context, TimingEvent.from_delta(a_summon_delta()))
    right = ObservedEvent(context, TimingEvent.from_delta(a_summon_delta()))

    assert left.event_id == right.event_id
    assert left is not right


def test_different_events_in_one_batch_get_different_ids():
    reader = EventReader(GameStateView.from_state(GameState.create(), viewer=MINE))
    events = reader.read_deltas((a_summon_delta(1), a_summon_delta(2)))

    assert events[0].event_id != events[1].event_id


def test_the_context_rejects_impossible_values():
    with pytest.raises(ValueError):
        EventContext(0, MINE, Phase.MAIN1)
    with pytest.raises(ValueError):
        EventContext(1, 2, Phase.MAIN1)
    with pytest.raises(ValueError):
        EventContext(1, MINE, Phase.MAIN1, actor=5)
    with pytest.raises(ValueError):
        EventContext(1, MINE, Phase.MAIN1, sequence=-1)


# ======================================================================
# 5. 후보 수집 연결
# ======================================================================


@requires_official_db
def test_a_summon_reaches_the_existing_candidate_collector(state, registry):
    """§7 — 새 수집기를 만들지 않는다. 있는 것에 사건을 넣을 뿐이다."""
    execution = summon_execution(state)
    pipeline = EventPipeline(view_of(state), registry)

    observations = pipeline.collect(execution)

    assert len(observations) == 1
    assert isinstance(observations[0].collection, TriggerCollection)
    assert observations[0].candidates


@requires_official_db
def test_one_event_can_carry_several_candidates(state, registry):
    """
    §9 — 사건 하나에서 여러 후보가 나올 수 있다는 사실을 잃지 않는다.
    페더맨이 두 장 보이므로 후보도 둘이다.
    """
    observations = EventPipeline(view_of(state), registry).collect(
        summon_execution(state)
    )
    candidates = observations[0].candidates

    assert len(candidates) >= 2
    assert len({c.identity for c in candidates}) == len(candidates)
    assert all(c.point is TimingPoint.MONSTER_SUMMONED for c in candidates)


@requires_official_db
def test_the_candidates_stay_tied_to_their_event(state, registry):
    observation = EventPipeline(view_of(state), registry).collect(
        summon_execution(state)
    )[0]

    assert observation.collection.event is observation.event.timing
    assert observation.event_id == observation.event.event_id


def test_a_collection_from_another_event_cannot_be_attached():
    """
    어느 사건에서 나온 후보인지가 사라지면 순서를 정할 근거가 없어진다.
    """
    context = EventContext(1, MINE, Phase.MAIN1)
    mine = ObservedEvent(context, TimingEvent.from_delta(a_summon_delta(1)))
    other = TimingEvent.from_delta(a_summon_delta(2))

    with pytest.raises(EventPipelineError):
        EventObservation(mine, TriggerCollection(event=other))


@requires_official_db
def test_a_summon_with_no_registered_trigger_finds_nothing(state):
    """
    등록되지 않은 카드는 후보가 나오지 않는다 — **그것이 지금의 사실이다**
    (자동 생성 컴파일러는 없다).
    """
    observations = EventPipeline(view_of(state), TriggerRegistry()).collect(
        summon_execution(state)
    )

    assert observations[0].candidates == ()


@requires_official_db
def test_what_the_observer_cannot_see_is_recorded_not_ignored(state, registry):
    """
    §15 — 상대의 패 · 덱에도 트리거가 있을 수 있다. 관측에 없다고 "후보가
    없다" 고 답하면 모르는 것을 거짓으로 접는 것이다.
    """
    observation = EventPipeline(view_of(state), registry).collect(
        summon_execution(state)
    )[0]

    assert observation.fully_checked is False
    assert any("HAND" in note for note in observation.unchecked)
    assert any("DECK" in note for note in observation.unchecked)


@requires_official_db
def test_the_opponents_hand_does_not_leak_through_the_pipeline(state, registry):
    """확인하지 못한 곳은 **장수만** 남는다. 카드 정체가 새지 않는다."""
    observation = EventPipeline(view_of(state), registry).collect(
        summon_execution(state)
    )[0]
    text = str(observation.to_dict())

    for hidden in state.player(THEIRS).hand:
        assert str(hidden.card_id) not in text


@requires_official_db
def test_an_unknown_candidate_stays_unknown(state):
    """
    §8 — 판정할 수 없는 것은 ``UNKNOWN`` 으로 남는다. ``INELIGIBLE`` 로
    바꾸지 않는다.
    """
    from engine.condition import UnimplementedRule

    registry = TriggerRegistry().register(
        TriggerSpec(
            EffectRef(FEATHERMAN, 0),
            TimingPoint.MONSTER_SUMMONED,
            condition=UnimplementedRule("소환 반응 규칙"),
        )
    )
    observation = EventPipeline(view_of(state), registry).collect(
        summon_execution(state)
    )[0]

    assert observation.candidates
    for candidate in observation.candidates:
        assert candidate.status is TriggerStatus.UNKNOWN
        assert candidate.status is not TriggerStatus.INELIGIBLE
        assert candidate.is_candidate is False


# ======================================================================
# 6. 변경 안전성
# ======================================================================


@requires_official_db
def test_observing_never_changes_the_board(state, registry):
    """§16 — 사건을 읽고 후보를 모아도 판은 그대로다."""
    execution = summon_execution(state)
    after = state.state_hash()
    pipeline = EventPipeline(view_of(state), registry)

    for _ in range(3):
        pipeline.collect(execution)

    assert state.state_hash() == after


@requires_official_db
def test_collecting_the_same_events_twice_gives_the_same_answer(state, registry):
    pipeline = EventPipeline(view_of(state), registry)
    execution = summon_execution(state)

    first = pipeline.collect(execution)
    second = pipeline.collect(execution)

    assert [o.canonical_state() for o in first] == [
        o.canonical_state() for o in second
    ]


@requires_official_db
def test_the_pipeline_holds_a_snapshot_not_the_board(state, registry):
    """
    관측은 만들어진 순간의 값이다. 뒤에 판이 바뀌어도 파이프라인이 든 것은
    흔들리지 않는다.
    """
    pipeline = EventPipeline(view_of(state), registry)
    before = pipeline.view.canonical_state()

    state.move(state.player(MINE).hand[0], Zone.GRAVE, to_player=MINE)

    assert pipeline.view.canonical_state() == before


@requires_official_db
def test_a_clone_is_observed_on_its_own(state, registry):
    copy = state.clone()
    execution = summon_execution(copy)
    before = state.state_hash()

    EventPipeline(view_of(copy), registry).collect(execution)

    assert state.state_hash() == before
    assert len(state.player(MINE).monster_zone) == 0
    assert len(copy.player(MINE).monster_zone) == 1


# ======================================================================
# 7. 계층 경계
# ======================================================================


def test_the_pipeline_does_not_know_who_produced_the_deltas():
    """
    §11 · §12 — 실행기를 가져오면 "실행기가 사건을 만든다" 가 되고, 상태
    변경과 사건 관찰이 다시 붙는다.
    """
    tree = ast.parse(pathlib.Path("engine/event_pipeline.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    for forbidden in (
        "engine.action_execution",
        "engine.normal_summon",
        "engine.turn_progression",
        "engine.effect.executor",
        "engine.state.game_state",
    ):
        assert forbidden not in imported, f"{forbidden} 를 가져오면 안 됩니다."


def test_the_pipeline_builds_no_chain_and_runs_no_effect():
    """§10 · §21 — 체인 생성 · 해결 · 효과 실행은 여기서 하지 않는다."""
    tree = ast.parse(pathlib.Path("engine/event_pipeline.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    for forbidden in (
        "engine.chain",
        "engine.trigger_chain",
        "engine.trigger_order",
        "engine.timing",
        "engine.priority",
        "engine.payment",
    ):
        assert forbidden not in imported
    for forbidden in ("Chain", "ChainLink", "ChainResolver", "EffectExecutor",
                      "PriorityState", "TimingCoordinator"):
        assert forbidden not in called


def test_the_summon_handler_still_creates_no_candidates():
    """§21-A — 소환 핸들러가 직접 후보를 만들면 두 경로가 갈린다."""
    source = pathlib.Path("engine/normal_summon.py").read_text("utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "engine.event_pipeline" not in imported
    assert "engine.trigger" not in imported
    assert "TriggerCandidate" not in source


def test_the_action_executor_still_knows_nothing_about_events():
    source = pathlib.Path("engine/action_execution.py").read_text("utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "engine.event_pipeline" not in imported
    assert "engine.trigger" not in imported


def test_the_pipeline_reuses_the_existing_collector_instead_of_making_one():
    """§7 · §17-21 — 중복 수집기를 만들지 않는다."""
    source = pathlib.Path("engine/event_pipeline.py").read_text("utf-8")
    tree = ast.parse(source)
    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }

    assert "TriggerCollector" not in defined
    assert "TriggerCandidate" not in defined
    assert "TriggerCollection" not in defined
    assert "TriggerCollector" in source  # 가져다 쓴다


def test_the_pipeline_does_not_judge_eligibility_or_order():
    """§8 · §17-22 · §17-23 — 적격성과 정렬은 각자의 계층이 한다."""
    source = pathlib.Path("engine/event_pipeline.py").read_text("utf-8")

    for forbidden in (
        "EligibilityGate",
        "TriggerEligibilityJudge",
        "TriggerOrderer",
        "TriggerChainIntegrator",
    ):
        assert forbidden not in source


@requires_official_db
def test_the_timing_coordinator_still_takes_events_from_outside(state, registry):
    """
    §17-25 — F-4 의 조정자는 그대로다. 파이프라인이 만든 사건을 **그대로**
    받아 자기 일을 한다.
    """
    from engine.chain import Chain
    from engine.priority import PriorityHolder, PriorityState, ResponseWindow
    from engine.timing import TimingCoordinator

    event = EventReader(view_of(state)).read(summon_execution(state))[0]
    coordinator = TimingCoordinator(view_of(state), registry)
    priority = PriorityState(
        holder=PriorityHolder.PLAYER_0,
        window=ResponseWindow.ACTION,
        turn_player=MINE,
        phase=state.turn.phase,
    )
    before = state.state_hash()

    window = coordinator.open_window(event.timing, priority, Chain())
    collection = coordinator.collect_triggers(window)

    assert collection.event is event.timing
    assert state.state_hash() == before
