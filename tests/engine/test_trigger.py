"""
Phase 2-F-3-A — 타이밍과 트리거의 최소 구조.

    StateDelta / JournalEvent → TimingEvent → TriggerCandidate

세 가지를 본다.

1. **후보 발견과 체인에 넣기가 분리되어 있는가.** ``ELIGIBLE`` 이 "발동
   가능" 으로 새어 나가지 않는가.
2. **모르는 것을 후보에서 지우지 않는가.** 볼 수 없는 곳을 조용히 건너뛰고
   "후보 없음" 이라 답하지 않는가.
3. **수집이 순수한 관찰인가.** 판 · 기록 · 체인 · 우선권 어느 것도 바뀌지
   않는가.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

from engine.chain import Chain
from engine.condition import (
    Always,
    AttributeIs,
    ConditionResult,
    IsMonster,
    UnimplementedRule,
)
from engine.cost import CostPayment, CostSemantics
from engine.effect import (
    CardDrawn,
    DrawOperation,
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectEvent,
    EffectProvenance,
    EventJournal,
    LifeChanged,
    OperationKind,
    ZoneMoved,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.priority import PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerCandidate,
    TriggerCollection,
    TriggerCollector,
    TriggerError,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
    TriggerStatus,
    TriggerWording,
    timing_events,
)
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

MINE, THEIRS = 0, 1
WATCHER = 1000
"""이 카드에만 트리거를 등록한다."""
PLAIN = 1001


# ======================================================================
# 판
# ======================================================================


def new_state() -> GameState:
    """
    p0: ``WATCHER`` 2장 + ``PLAIN`` 1장이 패에, ``WATCHER`` 1장이 필드에.
    p1: ``PLAIN`` 2장이 패에.
    """
    game = GameState.create(
        decks=(
            [WATCHER, WATCHER, WATCHER, PLAIN, PLAIN, PLAIN],
            [PLAIN, PLAIN, PLAIN, PLAIN],
        ),
    )
    game.draw(MINE, 4)
    game.draw(THEIRS, 2)
    game.move(game.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=MINE)


def collector(view, *specs, definitions=None) -> TriggerCollector:
    return TriggerCollector(view, TriggerRegistry(tuple(specs)), definitions)


def drawn_event(player: int = MINE, instance: int = 2) -> TimingEvent:
    return TimingEvent.from_delta(CardDrawn(player, InstanceId(instance)))


def moved_event(
    operation: OperationKind = OperationKind.SEND_TO_GRAVE,
    from_zone: Zone = Zone.MZONE,
    to_zone: Zone = Zone.GRAVE,
) -> TimingEvent:
    return TimingEvent.from_delta(
        ZoneMoved(operation, InstanceId(3), MINE, from_zone, MINE, to_zone)
    )


# ======================================================================
# A. TimingPoint · TimingEvent
# ======================================================================


def test_a_delta_becomes_the_matching_timing_point():
    moved = TimingEvent.from_delta(
        ZoneMoved(OperationKind.RELEASE, InstanceId(4), MINE, Zone.MZONE, THEIRS, Zone.GRAVE)
    )
    drawn = TimingEvent.from_delta(CardDrawn(THEIRS, InstanceId(5)))
    life = TimingEvent.from_delta(LifeChanged(MINE, 8000, 7000))

    assert moved.point is TimingPoint.CARD_MOVED
    assert moved.operation is OperationKind.RELEASE
    assert moved.from_zone is Zone.MZONE and moved.to_zone is Zone.GRAVE
    assert moved.instance == InstanceId(4)
    assert moved.actor == THEIRS  # 도착한 존의 주인

    assert drawn.point is TimingPoint.CARD_DRAWN
    assert drawn.actor == THEIRS
    assert drawn.from_zone is Zone.DECK and drawn.to_zone is Zone.HAND

    assert life.point is TimingPoint.LIFE_CHANGED
    assert life.instance is None  # 수치만 바뀐 사건
    assert life.movement is None


def test_the_same_destination_is_not_the_same_event():
    """``operation`` 이 남아 있어야 트리거가 나중에 구분할 수 있다 (ADR-002)."""
    sent = moved_event(OperationKind.SEND_TO_GRAVE)
    released = moved_event(OperationKind.RELEASE)

    assert sent.to_zone is released.to_zone is Zone.GRAVE
    assert sent.operation is not released.operation
    assert sent.canonical_state() != released.canonical_state()


def test_a_journal_event_becomes_a_timing_point():
    effect = EffectEvent(0, EffectRef(WATCHER, 1), MINE)
    resolved = TimingEvent.from_journal_event(effect)

    assert resolved.point is TimingPoint.EFFECT_RESOLVED
    assert resolved.effect_ref == EffectRef(WATCHER, 1)
    assert resolved.actor == MINE
    assert resolved.delta is None


def test_one_journal_event_yields_the_movements_then_the_resolution():
    """
    카드는 해결 **중에** 움직이고, 해결이 끝난 것은 그 뒤다. 이 순서가
    규칙이라고 주장하지는 않는다.
    """
    event = EffectEvent(
        0,
        EffectRef(WATCHER, 0),
        MINE,
        deltas=(
            ZoneMoved(
                OperationKind.BANISH, InstanceId(2), MINE, Zone.MZONE, MINE, Zone.REMOVED
            ),
            CardDrawn(MINE, InstanceId(6)),
        ),
    )

    events = timing_events(event)

    assert [e.point for e in events] == [
        TimingPoint.CARD_MOVED,
        TimingPoint.CARD_DRAWN,
        TimingPoint.EFFECT_RESOLVED,
    ]


def test_a_cost_payment_is_a_different_timing_point_than_an_effect():
    """비용 지불과 효과 해결은 다른 사건이다."""
    from engine.effect import CostPaymentEvent

    paid = TimingEvent.from_journal_event(
        CostPaymentEvent(
            0,
            MINE,
            payments=(CostPayment(CostSemantics.DISCARD, (InstanceId(1),), player=MINE),),
        )
    )
    assert paid.point is TimingPoint.COST_PAID
    assert paid.point is not TimingPoint.EFFECT_RESOLVED


def test_battle_is_not_pretended_to_exist():
    """
    전투 · 데미지 계층이 **아직 없다.** 어떤 경로로도 생길 수 없는 시점
    이름을 미리 못박지 않는다. 대신 무엇을 표현할 수 없는지 적는다.

    소환은 반대다 — Phase 2-I 가 실제로 ``MonsterSummoned`` 를 만들어 내게
    된 **뒤에** 이름이 생겼다. 그것이 이 규칙의 지키는 방식이다: 계층이
    먼저고 이름이 나중이다.
    """
    names = {point.value for point in TimingPoint}
    assert "battle_event" not in names
    assert "damage_step" not in names
    assert "attack_declared" not in names
    assert "monster_summoned" in names  # 만들어 내는 계층이 생긴 뒤에 들어왔다

    honest = TimingEvent.unimplemented("일반 소환 (소환 계층 없음)", actor=MINE)
    assert honest.point is TimingPoint.UNIMPLEMENTED
    assert "소환" in honest.note

    with pytest.raises(TriggerError):
        TimingEvent.unimplemented("")  # 이유 없이 UNIMPLEMENTED 를 쓰지 못한다


def test_an_unknown_delta_is_not_guessed_into_a_timing_point():
    from engine.effect.delta import StateDelta

    with pytest.raises(TriggerError):
        TimingEvent.from_delta(StateDelta())


def test_a_timing_event_is_immutable():
    event = drawn_event()
    for field, value in [("point", TimingPoint.CARD_MOVED), ("actor", THEIRS)]:
        with pytest.raises(Exception):
            setattr(event, field, value)


# ======================================================================
# B~D. TriggerCandidate
# ======================================================================


def test_a_candidate_names_the_effect_the_instance_and_the_controller(view):
    spec = TriggerSpec(
        EffectRef(WATCHER, 0),
        TimingPoint.CARD_DRAWN,
        requirement=TriggerRequirement.MANDATORY,
        wording=TriggerWording.WHEN,
    )

    collection = collector(view, spec).collect(drawn_event())

    assert len(collection) == 3  # 필드 1장 + 패 2장
    for candidate in collection:
        assert candidate.point is TimingPoint.CARD_DRAWN
        assert candidate.effect_ref == EffectRef(WATCHER, 0)
        assert isinstance(candidate.source, InstanceId)
        assert candidate.controller == MINE
        assert candidate.requirement is TriggerRequirement.MANDATORY
        assert candidate.wording is TriggerWording.WHEN


def test_a_candidate_uses_the_effect_ref_never_the_lua_variable_name():
    candidate = TriggerCandidate(
        TimingPoint.CARD_DRAWN, EffectRef(WATCHER, 2), InstanceId(4), MINE
    )
    assert candidate.to_dict()["effect_ref"] == {"card_id": WATCHER, "ordinal": 2}
    assert "e1" not in json.dumps(candidate.to_dict(), ensure_ascii=False)


def test_a_candidate_identity_is_stable_and_plain():
    candidate = TriggerCandidate(
        TimingPoint.CARD_MOVED, EffectRef(WATCHER, 1), InstanceId(7), THEIRS
    )

    assert candidate.identity == ("card_moved", WATCHER, 1, 7, THEIRS)
    assert candidate.key == "card_moved:1000:1:#7:P1"
    text = json.dumps(candidate.identity)
    assert "0x" not in text and "object at" not in text
    # 같은 것을 두 번 만들면 같은 식별자다.
    twin = TriggerCandidate(
        TimingPoint.CARD_MOVED, EffectRef(WATCHER, 1), InstanceId(7), THEIRS
    )
    assert candidate.identity == twin.identity
    assert candidate == twin


def test_a_candidate_never_carries_a_board_or_a_card_instance():
    from dataclasses import fields

    from engine.state.card_instance import CardInstance

    candidate = TriggerCandidate(
        TimingPoint.CARD_DRAWN, EffectRef(WATCHER, 0), InstanceId(1), MINE
    )
    for field in fields(candidate):
        value = getattr(candidate, field.name)
        assert not isinstance(value, (GameState, GameStateView, CardInstance))


def test_a_candidate_is_immutable_and_refuses_a_bad_seat():
    candidate = TriggerCandidate(
        TimingPoint.CARD_DRAWN, EffectRef(WATCHER, 0), InstanceId(1), MINE
    )
    with pytest.raises(Exception):
        candidate.status = TriggerStatus.ELIGIBLE
    with pytest.raises(TriggerError):
        TriggerCandidate(
            TimingPoint.CARD_DRAWN, EffectRef(WATCHER, 0), InstanceId(1), 5
        )


# ======================================================================
# E~H. 상태
# ======================================================================


def test_a_true_condition_makes_the_candidate_eligible(view):
    spec = TriggerSpec(
        EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN, condition=Always()
    )

    collection = collector(view, spec).collect(drawn_event())

    assert len(collection.eligible) == 3
    assert all(c.status is TriggerStatus.ELIGIBLE for c in collection)
    assert all(c.code is ValidationCode.OK for c in collection)


def test_eligible_does_not_claim_the_effect_can_be_activated(view):
    """
    ``ELIGIBLE`` 은 **"타이밍이 맞고 조건이 참"** 일 뿐이다. 스펠 스피드 ·
    타이밍 윈도우 · 놓친 타이밍 · 턴 1회 · 비용 · 발동 합법성은 하나도 보지
    않았다.
    """
    spec = TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN)
    candidate = collector(view, spec).collect(drawn_event()).candidates[0]

    assert candidate.status is TriggerStatus.ELIGIBLE
    assert candidate.is_candidate is True
    assert "발동 합법성은 따로 판정" in candidate.reason
    # 후보는 체인에 들어간 것이 아니다.
    assert not hasattr(candidate, "sequence")
    assert not hasattr(candidate, "chain")


def test_a_false_condition_makes_the_candidate_ineligible(view):
    spec = TriggerSpec(
        EffectRef(WATCHER, 0),
        TimingPoint.CARD_DRAWN,
        condition=Always(ConditionResult.FALSE),
    )

    collection = collector(view, spec).collect(drawn_event())

    assert len(collection.ineligible) == 3
    assert collection.eligible == ()
    for candidate in collection:
        assert candidate.status is TriggerStatus.INELIGIBLE
        assert candidate.is_candidate is False


def test_an_unjudgeable_condition_is_unknown_not_ineligible(view):
    """**모르는 것을 거짓으로 접지 않는다.**"""
    spec = TriggerSpec(
        EffectRef(WATCHER, 0),
        TimingPoint.CARD_DRAWN,
        condition=UnimplementedRule("체인 위의 카드 수"),
    )

    collection = collector(view, spec).collect(drawn_event())

    assert len(collection.undecided) == 3
    assert collection.ineligible == ()
    for candidate in collection:
        assert candidate.status is TriggerStatus.UNKNOWN
        assert candidate.status is not TriggerStatus.INELIGIBLE
        assert candidate.code is ValidationCode.INFORMATION_UNAVAILABLE
        assert any("체인 위의 카드 수" in note for note in candidate.notes)
        assert candidate.is_candidate is False


def test_unknown_never_leaks_through_as_permission():
    """
    ``is_candidate`` 는 ``ELIGIBLE`` 일 때만 참이다 —
    ``if status is not INELIGIBLE:`` 같은 코드로 새어 나가지 못한다.
    """
    assert TriggerStatus.ELIGIBLE.is_candidate is True
    for status in TriggerStatus:
        if status is not TriggerStatus.ELIGIBLE:
            assert status.is_candidate is False


def test_a_false_condition_beats_an_unknown_one(view):
    """
    조건 계층의 삼치 논리 그대로다 — 하나가 확실히 거짓이면 나머지를 몰라도
    전체가 거짓이다.
    """
    definitions = EffectDefinitionRegistry(
        (
            EffectDefinition(
                EffectRef(WATCHER, 0),
                WATCHER,
                activation=Always(ConditionResult.FALSE),
                provenance=EffectProvenance.official_lua(),
            ),
        )
    )
    spec = TriggerSpec(
        EffectRef(WATCHER, 0),
        TimingPoint.CARD_DRAWN,
        condition=UnimplementedRule("모르는 규칙"),
    )

    collection = collector(view, spec, definitions=definitions).collect(drawn_event())

    assert all(c.status is TriggerStatus.INELIGIBLE for c in collection)


def test_mandatory_and_optional_are_kept_apart_without_being_judged(view):
    """
    데이터 모델은 구분하지만 **판정하지 않는다.** "임의면 반드시 선택
    가능" 같은 규칙으로 넓히지 않는다.
    """
    specs = [
        TriggerSpec(
            EffectRef(WATCHER, ordinal),
            TimingPoint.CARD_DRAWN,
            requirement=requirement,
        )
        for ordinal, requirement in enumerate(
            (TriggerRequirement.MANDATORY, TriggerRequirement.OPTIONAL)
        )
    ]

    collection = collector(view, *specs).collect(drawn_event())

    by_ordinal = {c.effect_ref.ordinal: c for c in collection}
    assert by_ordinal[0].requirement is TriggerRequirement.MANDATORY
    assert by_ordinal[1].requirement is TriggerRequirement.OPTIONAL
    # 강제/임의가 상태를 바꾸지 않는다.
    assert by_ordinal[0].status is by_ordinal[1].status
    assert TriggerRequirement.UNKNOWN in set(TriggerRequirement)


def test_when_and_if_are_vocabulary_only(view):
    """
    "WHEN 이므로 반드시 놓친다" · "IF 이므로 반드시 발동 가능" 같은 규칙을
    구현하지 않는다 — 타이밍 윈도우가 없으면 판정할 근거가 없다.
    """
    specs = [
        TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN, wording=TriggerWording.WHEN),
        TriggerSpec(EffectRef(WATCHER, 1), TimingPoint.CARD_DRAWN, wording=TriggerWording.IF),
    ]

    collection = collector(view, *specs).collect(drawn_event())

    by_ordinal = {c.effect_ref.ordinal: c for c in collection}
    assert by_ordinal[0].wording is TriggerWording.WHEN
    assert by_ordinal[1].wording is TriggerWording.IF
    assert by_ordinal[0].status is by_ordinal[1].status  # 문구가 상태를 바꾸지 않는다

    import engine.trigger as module

    source = __import__("pathlib").Path("engine/trigger.py").read_text(encoding="utf-8")
    assert "missed" not in source.lower()
    assert not hasattr(module, "MissedTiming")


# ======================================================================
# I~J. Condition 재사용
# ======================================================================


def test_the_existing_condition_evaluator_is_reused_not_replaced(view):
    """새 조건 평가 엔진을 만들지 않았다."""
    import engine.trigger as module

    source = __import__("pathlib").Path("engine/trigger.py").read_text(encoding="utf-8")
    assert "ConditionEvaluator" in source
    for forbidden in ("def evaluate_condition", "class TriggerConditionEvaluator"):
        assert forbidden not in source
    assert not hasattr(module, "TriggerConditionEvaluator")


def test_the_definitions_activation_condition_is_honoured(view):
    """
    선언에 조건이 없어도 정의의 ``activation`` 이 있으면 그것을 본다 —
    적지 않은 조건을 참으로 치지 않는다.
    """
    definitions = EffectDefinitionRegistry(
        (
            EffectDefinition(
                EffectRef(WATCHER, 0),
                WATCHER,
                activation=Always(ConditionResult.FALSE),
                provenance=EffectProvenance.official_lua(),
            ),
        )
    )
    spec = TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN)

    collection = collector(view, spec, definitions=definitions).collect(drawn_event())

    assert all(c.status is TriggerStatus.INELIGIBLE for c in collection)


def test_a_missing_definition_is_unknown_not_eligible(view):
    """
    정의를 찾을 수 없으면 조건을 확인할 수 없다. 그때는 **모름**이고,
    "조건이 없으니 후보" 로 넘기지 않는다.
    """
    spec = TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN)
    empty = EffectDefinitionRegistry()

    collection = collector(view, spec, definitions=empty).collect(drawn_event())

    for candidate in collection:
        assert candidate.status is TriggerStatus.UNKNOWN
        assert "정의 미등록" in candidate.notes


def test_an_unreadable_card_definition_keeps_the_candidate_unknown(view):
    """
    카드 정의를 읽을 수 없으면 속성 조건을 판정할 수 없다 — ``UNKNOWN`` 이다.
    """
    spec = TriggerSpec(
        EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN, condition=AttributeIs("DARK")
    )

    collection = collector(view, spec).collect(drawn_event())

    assert len(collection.undecided) == 3
    assert all(c.notes for c in collection)


# ======================================================================
# K~L. 수집과 순서
# ======================================================================


def test_several_candidates_are_collected_from_one_event(view):
    specs = [
        TriggerSpec(EffectRef(WATCHER, ordinal), TimingPoint.CARD_DRAWN)
        for ordinal in range(3)
    ]

    collection = collector(view, *specs).collect(drawn_event())

    assert len(collection) == 9  # 선언 3개 × 사본 3장
    assert len({c.identity for c in collection}) == 9


def test_a_spec_only_reacts_to_what_it_declared(view):
    spec = TriggerSpec(
        EffectRef(WATCHER, 0),
        TimingPoint.CARD_MOVED,
        operations=frozenset({OperationKind.SEND_TO_GRAVE}),
        to_zones=frozenset({Zone.GRAVE}),
    )
    watcher = collector(view, spec)

    assert len(watcher.collect(moved_event(OperationKind.SEND_TO_GRAVE))) == 3
    assert len(watcher.collect(moved_event(OperationKind.RELEASE))) == 0
    assert len(watcher.collect(drawn_event())) == 0
    assert (
        len(watcher.collect(moved_event(OperationKind.SEND_TO_GRAVE, to_zone=Zone.REMOVED)))
        == 0
    )


def test_a_filter_cannot_be_hung_on_an_event_that_has_no_zones():
    with pytest.raises(TriggerError):
        TriggerSpec(
            EffectRef(WATCHER, 0),
            TimingPoint.CARD_DRAWN,
            operations=frozenset({OperationKind.DRAW}),
        )
    with pytest.raises(TriggerError):
        TriggerSpec(
            EffectRef(WATCHER, 0),
            TimingPoint.LIFE_CHANGED,
            to_zones=frozenset({Zone.GRAVE}),
        )


def test_the_order_is_deterministic_but_is_not_the_rule_order(view):
    """
    등록 순서를 게임 규칙상의 우선순위라고 주장하지 않는다. 정렬은
    **재현성**을 위한 것이고 SEGOC 는 다음 단계다.
    """
    first = [
        TriggerSpec(EffectRef(WATCHER, 2), TimingPoint.CARD_DRAWN),
        TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN),
        TriggerSpec(EffectRef(WATCHER, 1), TimingPoint.CARD_DRAWN),
    ]
    second = list(reversed(first))

    forward = collector(view, *first).collect(drawn_event())
    backward = collector(view, *second).collect(drawn_event())

    assert forward.canonical_state() == backward.canonical_state()
    identities = [c.identity for c in forward]
    assert identities == sorted(identities)

    import engine.trigger as module

    for forbidden in ("SEGOC", "segoc", "order_triggers", "sort_by_rule"):
        assert not hasattr(module, forbidden), forbidden


def test_events_are_collected_separately_not_merged(view):
    """
    어느 사건에서 나온 후보인지가 사라지면 나중에 순서를 정할 근거가 없다.
    """
    spec_draw = TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN)
    spec_move = TriggerSpec(EffectRef(WATCHER, 1), TimingPoint.CARD_MOVED)

    collections = collector(view, spec_draw, spec_move).collect_all(
        [drawn_event(), moved_event()]
    )

    assert len(collections) == 2
    assert collections[0].event.point is TimingPoint.CARD_DRAWN
    assert collections[1].event.point is TimingPoint.CARD_MOVED
    assert all(c.point is TimingPoint.CARD_DRAWN for c in collections[0])
    assert all(c.point is TimingPoint.CARD_MOVED for c in collections[1])


def test_nothing_registered_means_no_candidates_and_nothing_claimed(view):
    collection = collector(view).collect(drawn_event())

    assert isinstance(collection, TriggerCollection)
    assert collection.candidates == ()
    # 등록된 선언이 없으면 "확인했다" 고도 말하지 않는다.
    assert collection.unchecked == ()
    assert len(collection) == 0


# ======================================================================
# M. 가려진 정보
# ======================================================================


def test_a_concealed_zone_is_reported_as_unchecked_not_as_empty(view):
    """
    **가장 중요한 테스트다.** 상대의 패에도 트리거가 있을 수 있다. 관측에
    없다고 "후보 없음" 이라 답하면 모르는 것을 거짓으로 접는 것이다.
    """
    spec = TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN)

    collection = collector(view, spec).collect(drawn_event())

    assert collection.fully_checked is False
    assert any("P1 HAND" in note for note in collection.unchecked)
    assert any("DECK" in note for note in collection.unchecked)


def test_a_face_down_card_is_reported_as_unchecked(state):
    facedown = state.move(
        state.player(THEIRS).hand[0], Zone.SZONE, position=Position.FACEDOWN
    )
    view = GameStateView.from_state(state, viewer=MINE)
    spec = TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN)

    collection = collector(view, spec).collect(drawn_event())

    assert any(
        f"#{facedown.instance_id.value} 뒷면" in note for note in collection.unchecked
    )
    assert collection.fully_checked is False


def test_a_hidden_card_never_becomes_a_candidate(state):
    """
    상대 패의 ``WATCHER`` 는 내 관측에서 ``card_id`` 가 없다. 후보가 되지도
    않고, 그 카드가 무엇인지 새어 나가지도 않는다.
    """
    hidden = state.create_instance(WATCHER, owner=THEIRS, zone=Zone.HAND)
    view = GameStateView.from_state(state, viewer=MINE)
    spec = TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN)

    collection = collector(view, spec).collect(drawn_event())

    # 문자열 검색이 아니라 **모양**으로 확인한다 — ``1000`` 안의 ``10`` 같은
    # 우연한 일치에 속지 않기 위해서다.
    assert hidden.instance_id not in {c.source for c in collection}
    assert all(c.controller == MINE for c in collection)
    assert hidden.instance_id.value not in {
        candidate.to_dict()["source"] for candidate in collection
    }
    # 상대 패는 "확인하지 못한 곳" 으로만 남는다.
    assert any("P1 HAND" in note for note in collection.unchecked)
    # 내 카드는 보이므로 후보가 된다.
    assert {c.to_dict()["effect_ref"]["card_id"] for c in collection} == {WATCHER}


def test_the_owner_of_a_hidden_card_sees_their_own_trigger(state):
    """
    같은 카드라도 관측자가 다르면 보이는 것이 다르다 — 그것이 정보 경계가
    살아 있다는 증거다.
    """
    spec = TriggerSpec(EffectRef(PLAIN, 0), TimingPoint.CARD_DRAWN)

    mine = collector(GameStateView.from_state(state, viewer=MINE), spec).collect(
        drawn_event()
    )
    theirs = collector(GameStateView.from_state(state, viewer=THEIRS), spec).collect(
        drawn_event()
    )

    assert len(mine) == 1  # 내 패의 PLAIN 1장
    assert len(theirs) == 2  # 상대 패의 PLAIN 2장
    assert mine.canonical_state() != theirs.canonical_state()


# ======================================================================
# N. TEXT_DERIVED 경계
# ======================================================================


def test_a_text_derived_effect_is_forbidden_not_eligible(view):
    """
    출처 금지가 **조건보다 먼저**다. 조건이 참이어도 실행 후보가 되지
    않는다 (ADR-004).
    """
    definitions = EffectDefinitionRegistry(
        (
            EffectDefinition(
                EffectRef(WATCHER, 0),
                WATCHER,
                operations=(DrawOperation(1),),
                activation=Always(),
                provenance=EffectProvenance.text_derived("공식 텍스트"),
            ),
        )
    )
    spec = TriggerSpec(
        EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN, condition=Always()
    )

    collection = collector(view, spec, definitions=definitions).collect(drawn_event())

    assert len(collection.forbidden) == 3
    assert collection.eligible == ()
    for candidate in collection:
        assert candidate.status is TriggerStatus.FORBIDDEN
        assert candidate.status is not TriggerStatus.INELIGIBLE
        assert candidate.is_candidate is False
        assert "ADR-004" in candidate.reason


def test_a_lua_verified_effect_is_not_forbidden(view):
    definitions = EffectDefinitionRegistry(
        (
            EffectDefinition(
                EffectRef(WATCHER, 0),
                WATCHER,
                operations=(DrawOperation(1),),
                activation=Always(),
                provenance=EffectProvenance.official_lua(),
            ),
        )
    )
    spec = TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN)

    collection = collector(view, spec, definitions=definitions).collect(drawn_event())

    assert len(collection.eligible) == 3
    assert collection.forbidden == ()


# ======================================================================
# O~S. Mutation safety
# ======================================================================


def test_collecting_candidates_never_touches_the_board(state):
    view = GameStateView.from_state(state, viewer=MINE)
    journal = EventJournal()
    chain = Chain().activate(MINE, EffectRef(WATCHER, 0))
    priority = PriorityState.opened(ResponseWindow.RESPONSE, THEIRS)

    before = (
        state.state_hash(),
        journal.canonical_state(),
        chain.canonical_state(),
        priority.canonical_state(),
        [(c.instance_id, c.zone, c.controller, c.owner) for c in state.all_instances()],
    )

    specs = [
        TriggerSpec(EffectRef(WATCHER, ordinal), TimingPoint.CARD_DRAWN, condition=Always())
        for ordinal in range(3)
    ]
    watcher = collector(view, *specs)
    watcher.collect(drawn_event())
    watcher.collect(moved_event())
    watcher.collect_all([drawn_event(), moved_event(), drawn_event(THEIRS)])

    assert state.state_hash() == before[0]
    assert journal.canonical_state() == before[1]
    assert chain.canonical_state() == before[2]
    assert priority.canonical_state() == before[3]
    assert [
        (c.instance_id, c.zone, c.controller, c.owner) for c in state.all_instances()
    ] == before[4]
    assert len(journal) == 0 and chain.resolved_count == 0


def test_the_collector_refuses_a_raw_game_state(state):
    with pytest.raises(TypeError):
        TriggerCollector(state, TriggerRegistry())
    view = GameStateView.from_state(state, viewer=MINE)
    with pytest.raises(TypeError):
        TriggerCollector(view, "not a registry")
    with pytest.raises(TypeError):
        TriggerCollector(view, TriggerRegistry(), object())


def test_the_trigger_layer_has_no_way_to_change_anything(view):
    watcher = collector(view, TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN))
    for forbidden in ("move", "draw", "apply", "execute", "push", "pay", "resolve"):
        assert not hasattr(watcher, forbidden), forbidden

    collection = watcher.collect(drawn_event())
    for forbidden in ("apply", "push", "to_chain", "activate"):
        assert not hasattr(collection, forbidden), forbidden
        assert not hasattr(collection.candidates[0], forbidden), forbidden


def test_a_cloned_board_is_unaffected_by_collection(state):
    copy = state.clone()
    spec = TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN)

    collector(GameStateView.from_state(copy, viewer=MINE), spec).collect(drawn_event())

    assert copy.state_hash() == state.state_hash()
    copy.move(copy.player(MINE).hand[0], Zone.GRAVE, to_player=MINE)
    assert copy.state_hash() != state.state_hash()
    assert len(state.player(MINE).grave) == 0


def test_a_candidate_never_becomes_a_chain_link(view):
    """
    ``TriggerCandidate`` 가 ``ChainLink`` 를 상속하지도, ``Chain`` 이 그것을
    받지도 않는다. 사이에 Action 과 비용 지불이 있다.
    """
    from engine.chain import ChainLink

    spec = TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN)
    candidate = collector(view, spec).collect(drawn_event()).candidates[0]

    assert not isinstance(candidate, ChainLink)
    with pytest.raises(TypeError):
        Chain().push(candidate)

    source = __import__("pathlib").Path("engine/trigger.py").read_text(encoding="utf-8")
    for module_name in ("engine.chain", "engine.priority"):
        assert f"from {module_name}" not in source
        assert f"import {module_name}" not in source


def test_triggers_do_not_touch_priority(view):
    """트리거가 우선권을 돌리지 않고, 우선권이 후보를 만들지 않는다."""
    import engine.priority as priority_module
    import engine.trigger as trigger_module

    assert not hasattr(trigger_module, "PriorityState")
    assert not hasattr(priority_module, "TriggerCandidate")

    priority = PriorityState.opened(ResponseWindow.ACTION, MINE)
    for forbidden in ("triggers", "candidates", "collect"):
        assert not hasattr(priority, forbidden), forbidden


def test_triggers_pay_no_costs(view):
    """
    비용은 후보 단계 뒤의 일이다 — Action → 비용 검증/지불 → ``ChainLink``.

    후보 자체는 비용을 담지도 부르지도 않는다. **지불기(``CostPayer``)를
    import 하지 않는지**로 확인한다 — 이름이 설명문에 나오는 것과 실제로
    쓰는 것은 다르다 (Phase 2-F-3-B 가 ``CostValidator`` 는 쓴다).
    """
    import ast

    import engine.trigger as module

    spec = TriggerSpec(EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN)
    candidate = collector(view, spec).collect(drawn_event()).candidates[0]

    tree = ast.parse(
        __import__("pathlib").Path("engine/trigger.py").read_text(encoding="utf-8")
    )
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "CostPayer" not in imported
    assert not hasattr(module, "CostPayer")
    assert not any(name.startswith("engine.payment") for name in modules)
    for forbidden in ("payments", "cost", "pay"):
        assert not hasattr(candidate, forbidden), forbidden


# ======================================================================
# T~U. 결정론
# ======================================================================


def test_the_same_board_and_event_give_the_same_candidates():
    spec = TriggerSpec(
        EffectRef(WATCHER, 0), TimingPoint.CARD_DRAWN, condition=IsMonster()
    )

    results = []
    for _ in range(2):
        board = new_state()
        results.append(
            collector(GameStateView.from_state(board, viewer=MINE), spec)
            .collect(drawn_event())
            .canonical_state()
        )

    assert results[0] == results[1]


def test_the_collection_serializes_to_plain_data(view):
    spec = TriggerSpec(
        EffectRef(WATCHER, 0),
        TimingPoint.CARD_MOVED,
        requirement=TriggerRequirement.OPTIONAL,
        wording=TriggerWording.IF,
        operations=frozenset({OperationKind.SEND_TO_GRAVE, OperationKind.RELEASE}),
    )

    collection = collector(view, spec).collect(moved_event())
    text = json.dumps(collection.to_dict(), ensure_ascii=False)

    assert "0x" not in text and "object at" not in text
    # frozenset 은 정렬된 목록으로 나간다 — 순회 순서에 의존하지 않는다.
    assert spec.to_dict()["operations"] == ["release", "send_to_grave"]


def test_the_serialization_does_not_depend_on_the_hash_seed():
    """
    ``frozenset`` 을 들고 있으므로 순회 순서가 새어 나갈 수 있다. 별도
    프로세스에서 실제로 확인한다.
    """
    snippet = textwrap.dedent(
        """
        import json
        from engine.effect import CardDrawn, OperationKind
        from engine.game_state_view import GameStateView
        from engine.ids import EffectRef, InstanceId
        from engine.state.game_state import GameState
        from engine.trigger import (
            TimingEvent, TimingPoint, TriggerCollector, TriggerRegistry, TriggerSpec,
        )
        from engine.vocabulary import Position, Zone

        game = GameState.create(decks=([1000, 1000, 1001], [1001, 1001]))
        game.draw(0, 3)
        game.draw(1, 2)
        game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
        view = GameStateView.from_state(game, viewer=0)

        spec = TriggerSpec(
            EffectRef(1000, 0),
            TimingPoint.CARD_MOVED,
            operations=frozenset(
                {OperationKind.SEND_TO_GRAVE, OperationKind.RELEASE, OperationKind.BANISH}
            ),
            from_zones=frozenset({Zone.MZONE, Zone.HAND, Zone.SZONE}),
        )
        drawn = TimingEvent.from_delta(CardDrawn(0, InstanceId(1)))
        collection = TriggerCollector(view, TriggerRegistry((spec,))).collect(drawn)
        print(json.dumps(
            [spec.canonical_state(), spec.to_dict(), collection.canonical_state()],
            ensure_ascii=False, sort_keys=True,
        ))
        """
    )
    outputs = []
    for seed in ("0", "1", "424242"):
        finished = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            env=dict(os.environ, PYTHONHASHSEED=seed),
            cwd=os.getcwd(),
        )
        assert finished.returncode == 0, finished.stderr
        outputs.append(finished.stdout)
    assert len(set(outputs)) == 1


def test_real_deltas_from_a_real_execution_feed_the_trigger_layer(state):
    """
    **기존 Event/Delta 와 실제로 이어지는지** 확인한다. 손으로 만든 Delta 가
    아니라 실행기가 낸 것을 쓴다.
    """
    from engine.effect import (
        EffectExecutor,
        EffectImplementationRegistry,
        LifeChangeOperation,
        ResolutionContext,
    )

    held = EffectDefinition(
        effect_ref=EffectRef(WATCHER, 0),
        source_card_id=WATCHER,
        operations=(DrawOperation(1), LifeChangeOperation(-500)),
        provenance=EffectProvenance.official_lua(),
    )
    journal = EventJournal()
    executor = EffectExecutor(
        EffectImplementationRegistry([held.effect_ref]), journal=journal
    )
    result = executor.execute(
        state, held, ResolutionContext(held.effect_ref, controller=MINE)
    )
    assert result.deltas

    # 실행 뒤의 판을 관측하고, 실행이 낸 기록을 사건으로 본다.
    view = GameStateView.from_state(state, viewer=MINE)
    events = timing_events(journal[0])
    assert [e.point for e in events] == [
        TimingPoint.CARD_DRAWN,
        TimingPoint.LIFE_CHANGED,
        TimingPoint.EFFECT_RESOLVED,
    ]

    specs = [
        TriggerSpec(EffectRef(WATCHER, 1), TimingPoint.CARD_DRAWN),
        TriggerSpec(EffectRef(WATCHER, 2), TimingPoint.LIFE_CHANGED),
        TriggerSpec(EffectRef(WATCHER, 3), TimingPoint.EFFECT_RESOLVED),
    ]
    collections = collector(view, *specs).collect_all(events)

    assert [len(c) for c in collections] == [3, 3, 3]
    assert {c.event.point for c in collections} == {
        TimingPoint.CARD_DRAWN,
        TimingPoint.LIFE_CHANGED,
        TimingPoint.EFFECT_RESOLVED,
    }
    # 수집이 판을 더 건드리지 않았다.
    assert journal.canonical_state() == EventJournal((journal[0],)).canonical_state()
