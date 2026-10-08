"""
Phase 3-F-5 — **SPECIAL_SUMMON: 행위(Operation)와 사건(Event)의 데이터 계층 감사.**

이 파일이 답하는 단 하나의 질문
-------------------------------
"특수 소환" 이 지금 코드에서 **무엇으로 표현되어 있는가** — 효과가 *하려는
일*인가, 게임에서 *일어난 일*인가, 둘을 잇는 데이터가 있는가, 없다면 어디서
끊기는가.

두 문장을 절대 합치지 않는다
----------------------------
======  ==========================================  ===========================
   A    "이 효과가 특수 소환을 **수행한다**"          Operation
   B    "게임에서 특수 소환이 **발생했다**"           Event
======  ==========================================  ===========================

측정으로 확정한 경로 (``test_04`` ~ ``test_08`` · ``test_09``)
-------------------------------------------------------------
=========================  ===========  ===================================
Operation → Mutation       CONNECTED    실행기가 실제로 판을 바꾼다
Mutation → Delta           CONNECTED    ``MonsterSummoned(summon=SPECIAL)``
Delta → Event              CONNECTED*   ``EventReader`` 가 그대로 읽는다
Event → TimingPoint        PARTIAL      이름은 **하나**뿐 (소환 종류를 잃는다)
TimingPoint → Candidate    DORMANT      수집기는 되지만 production 호출 0
Candidate → Eligibility    DORMANT      판정기는 되지만 production 호출 0
Eligibility → Activation   MISSING      후보를 행위로 되돌리는 다리가 없다
=========================  ===========  ===================================

``*`` **구조로는 이어져 있고 production 에서 호출되지 않는다.** ``Duel`` 은
``ActionExecution`` 을 받아 ``.status`` · ``.code`` · ``.reason`` 만 읽고
``DuelStep`` 으로 돌려주며, ``DuelStep`` 에는 ``deltas`` 칸이 **없다**
(``test_09``). 끊긴 것은 데이터 구조가 아니라 **건네주는 손**이다.

이 파일은 production 을 **한 줄도** 바꾸지 않는다 (``test_19``).
"""

import ast
import hashlib
import pathlib
import re

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import (
    SPECIAL_SUMMON_CONDITION_RULE,
    ActionValidator,
    UnimplementedRule,
    _COMPLETE_RULES,
    _MISSING_RULE,
    _special_summon,
)
from engine.duel import Duel, DuelStep
from engine.effect.delta import CardMovement, MonsterSummoned, SummonKind
from engine.effect.executor import OPERATION_HANDLERS
from engine.effect.library import EFFECT_LIBRARY, entry_for
from engine.effect.operation import OperationKind, SpecialSummonOperation
from engine.effect.target import PRIMARY_TARGET
from engine.event_pipeline import EventReader, ObservedEvent
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId, iter_effects
from engine.special_summon import (
    SPECIAL_SUMMON_FROM_ZONES,
    SPECIAL_SUMMON_POSITION,
    SPECIAL_SUMMON_PROCEDURE,
    SPECIAL_SUMMON_TO_ZONE,
)
from engine.summon import duel_executor
from engine.trigger import (
    EligibilityGate,
    TimingEvent,
    TimingPoint,
    TriggerCollector,
    TriggerEligibilityJudge,
    TriggerError,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
)
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MINE, THEIRS = 0, 1

LUSTER_DRAGON = 11091375   # 통상 몬스터 · 소환 절차에 쓴다
MONSTER_REBORN = 83764718  # 죽은 자의 소생 — **등재되어 있고 실행되지 않는다**

#: 감사가 **직접** 건네는 허가. 소환 조건 계층을 대신하지 않는다 —
#: 그 계층이 없다는 것이 이 Phase 의 측정 결과이고 (``test_10``), 그것을
#: 우회해야만 그 뒤의 경로를 볼 수 있다.
AUDIT_GRANT = ValidationResult.valid("감사가 관문을 우회해 직접 허가했다")


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


# ======================================================================
# 판 — 실제 ``Duel`` 에서 가져온다 (손으로 만든 판이 아니다)
# ======================================================================


def live_duel(repository, *, seed: int = 3, deck_size: int = 20) -> Duel:
    """실제 ``Duel.start`` 로 시작해 규칙 걸음을 끝낸 판."""
    deck = [LUSTER_DRAGON] * deck_size
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
    while duel.advance() is not None:
        pass
    return duel


def execute_summon(duel: Duel, builder, actor: int):
    """
    그 소환을 **실제 실행기**로 수행한다. 판은 사본이다.

    ``builder`` 는 ``PlayerAction.normal_summon`` 또는
    ``PlayerAction.special_summon`` 이다 — 두 경로가 **같은 실행기**를
    쓴다는 것이 측정 대상이므로 여기서 갈라 두지 않는다.
    """
    state = duel.state.clone()
    source = list(state.player(actor).hand)[0].instance_id
    action = builder(actor=actor, source=source)
    return state, duel_executor().execute(state, action, authorization=AUDIT_GRANT)


def observed(state, execution, *, viewer: int, actor: int):
    return EventReader(GameStateView.from_state(state, viewer=viewer)).read(
        execution, actor=actor
    )


def monster_summoned(kind: SummonKind, *, player: int = MINE) -> MonsterSummoned:
    """합성 변화 하나. 열거 · 금지 확인처럼 판이 필요 없는 자리에만 쓴다."""
    return MonsterSummoned(
        summon=kind,
        card=InstanceId(7),
        player=player,
        owner=player,
        from_zone=Zone.HAND,
        to_zone=Zone.MZONE,
        to_index=0,
        position=Position.FACEUP_ATTACK,
    )


# ======================================================================
# A. 어휘 — Operation · SummonKind · Delta 는 **서로 다른 세 가지**다
# ======================================================================


def test_01_the_operation_kind_is_a_job_not_an_event():
    """
    §3 Q1 — ``OperationKind.SPECIAL_SUMMON`` 은 **효과가 하려는 일**이다.

    근거 셋을 **코드에서** 확인한다.

    1. 실행기 표에 **계획 함수와 적용 함수**가 달려 있다 — 사건에는 그런
       것이 붙지 않는다.
    2. 그 일을 나르는 ``Operation`` 은 ``TargetRef`` 를 **요구한다** —
       "누구를" 없이는 일이 성립하지 않는다.
    3. 같은 이름이 ``PlayerActionKind`` 에도 있고 **다른 enum** 이다
       (ADR-001). 셋을 하나로 합치면 "하려는 일" 과 "고른 행위" 와
       "일어난 사건" 이 같은 표를 쓰게 된다.
    """
    handler = OPERATION_HANDLERS[OperationKind.SPECIAL_SUMMON]
    assert callable(handler.plan) and callable(handler.apply)

    operation = SpecialSummonOperation(target_ref=PRIMARY_TARGET)
    assert operation.kind is OperationKind.SPECIAL_SUMMON
    assert operation.target_refs == (PRIMARY_TARGET,)
    with pytest.raises(TypeError):
        SpecialSummonOperation(target_ref="primary")  # 이름만으로는 일이 아니다

    #: 세 어휘는 서로 다른 타입이다 — 값이 같은 문자열이어도.
    assert OperationKind.SPECIAL_SUMMON is not PlayerActionKind.SPECIAL_SUMMON
    assert OperationKind.SPECIAL_SUMMON.value == PlayerActionKind.SPECIAL_SUMMON.value
    assert not isinstance(TimingPoint.MONSTER_SUMMONED, OperationKind)
    #: 그리고 ``TimingPoint`` 에는 특수 소환이라는 이름이 **아예 없다.**
    assert "special" not in {point.value for point in TimingPoint}


def test_02_summon_kind_says_which_summon_and_only_that():
    """
    §3 — ``SummonKind`` 는 **소환의 종류**이고, 지금 두 값뿐이다.

    ``SPECIAL`` 은 실제로 쓰이는 값이다 — 특수 소환 절차가 그것을 들고 있다.

    .. note::
       ``SummonKind`` 의 docstring 첫 줄은 **"지금 있는 것은 일반 소환뿐이다"**
       라고 말한다. 그것은 ``SPECIAL`` 이 들어오기 전(Phase 2-T 이전)의
       문장이고 **지금은 사실이 아니다.** 이 Phase 는 문서가 아니라 값을
       측정했다 — 그래서 아래가 docstring 이 아니라 멤버 목록을 센다.
    """
    assert {kind.value for kind in SummonKind} == {"normal", "special"}
    assert SPECIAL_SUMMON_PROCEDURE.summon is SummonKind.SPECIAL

    #: 절차의 네 값은 **범위**이고 규칙이 아니다 (파일이 그렇게 적어 두었다).
    assert SPECIAL_SUMMON_FROM_ZONES == frozenset({Zone.HAND, Zone.GRAVE})
    assert SPECIAL_SUMMON_TO_ZONE is Zone.MZONE
    assert SPECIAL_SUMMON_POSITION is Position.FACEUP_ATTACK
    assert SPECIAL_SUMMON_PROCEDURE.kind is PlayerActionKind.SPECIAL_SUMMON


def test_03_monster_summoned_is_the_fact_not_the_job():
    """
    §3 Q2 — ``MonsterSummoned`` 는 **일어난 일**이다.

    ``CardMovement`` 가 **아니다.** 그래서 효과의 어휘(``OperationKind``)를
    달지 않고, 대신 ``summon`` 이 의미를 말한다. 그 선택의 대가가
    ``test_07`` 에서 측정된다.
    """
    delta = monster_summoned(SummonKind.SPECIAL)
    assert not isinstance(delta, CardMovement)
    assert not hasattr(delta, "operation")
    assert delta.summon is SummonKind.SPECIAL
    assert delta.kind == "monster_summoned"

    #: 종류가 정규 표현에 **들어간다** — 기록에서 사라지지 않는다.
    assert "special" in delta.canonical_state()
    assert delta.to_dict()["summon"] == "special"
    #: 그리고 일반 소환과 다른 기록이 된다.
    assert (
        monster_summoned(SummonKind.NORMAL).canonical_state()
        != delta.canonical_state()
    )


# ======================================================================
# B. Operation → Mutation → Delta (§6 1~3)
# ======================================================================


def test_04_the_operation_actually_changes_the_board(repository):
    """§6 ①②  Operation → State Mutation = **CONNECTED.**"""
    duel = live_duel(repository)
    before = len(duel.state.player(MINE).zone(Zone.MZONE))

    state, execution = execute_summon(duel, PlayerAction.special_summon, MINE)

    assert execution.status.value == "executed"
    assert len(state.player(MINE).zone(Zone.MZONE)) == before + 1
    #: 그리고 **원본 판은 그대로다** — 사본에서만 바뀌었다.
    assert len(duel.state.player(MINE).zone(Zone.MZONE)) == before


def test_05_the_mutation_leaves_a_special_summon_delta(repository):
    """§6 ③  Mutation → Delta = **CONNECTED**, 종류까지 실려 있다."""
    duel = live_duel(repository)
    _, execution = execute_summon(duel, PlayerAction.special_summon, MINE)

    assert len(execution.deltas) == 1
    delta = execution.deltas[0]
    assert isinstance(delta, MonsterSummoned)
    assert delta.summon is SummonKind.SPECIAL
    assert (delta.from_zone, delta.to_zone) == (Zone.HAND, Zone.MZONE)

    #: **같은 실행기**가 일반 소환에서는 ``NORMAL`` 을 남긴다 — 두 경로가
    #: 한 절차를 쓰면서도 기록은 갈라진다.
    _, normal = execute_summon(duel, PlayerAction.normal_summon, MINE)
    assert normal.deltas[0].summon is SummonKind.NORMAL


def test_06_the_delta_becomes_an_event_without_anything_new(repository):
    """
    §6 ④⑤  Delta → Event = **CONNECTED.**

    새 자료 구조를 만들 필요가 없다 — ``EventReader`` 가 "변화를 들고 있는
    것이면 무엇이든" 받는다고 적어 두었고, 실제로 ``ActionExecution`` 을
    그대로 읽는다.
    """
    duel = live_duel(repository)
    state, execution = execute_summon(duel, PlayerAction.special_summon, MINE)

    events = observed(state, execution, viewer=MINE, actor=MINE)

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ObservedEvent)
    assert event.point is TimingPoint.MONSTER_SUMMONED
    assert event.point is not TimingPoint.CARD_MOVED
    #: **종류가 사건에서 되살아난다** — delta 를 참조로 들고 있기 때문이다.
    assert event.delta.summon is SummonKind.SPECIAL
    assert event.actor == MINE
    assert event.event_id  # 내용에서 나온 식별자


def test_07_the_event_keeps_the_summon_kind_but_exposes_no_way_to_read_it(
    repository,
):
    """
    §6 ⑤ 의 **정확한 한계.** Event → TimingPoint = **PARTIAL.**

    사실은 보존된다 (``event.delta.summon``). 그런데 ``TimingEvent`` 가
    **꺼내 주는 창구가 없다** — ``operation`` · ``from_zone`` · ``to_zone``
    셋 다 ``None`` 이다. ``MonsterSummoned`` 가 ``CardMovement`` 가 아니라서
    ``movement`` 가 ``None`` 이고, 그 세 속성이 모두 ``movement`` 를 거친다.

    **delta 는 그 값을 갖고 있다.** 즉 정보가 없는 것이 아니라 **창구가
    없다.**
    """
    duel = live_duel(repository)
    state, execution = execute_summon(duel, PlayerAction.special_summon, MINE)
    timing = observed(state, execution, viewer=MINE, actor=MINE)[0].timing

    assert timing.movement is None
    assert timing.operation is None
    assert timing.from_zone is None
    assert timing.to_zone is None
    #: 그런데 delta 는 그 둘을 분명히 들고 있다.
    assert timing.delta.from_zone is Zone.HAND
    assert timing.delta.to_zone is Zone.MZONE

    #: 소환 종류를 꺼내는 **속성이 없다** — delta 를 직접 들여다봐야 한다.
    assert not hasattr(timing, "summon")
    assert "summon" not in {
        name
        for name in dir(TimingEvent)
        if not name.startswith("_") and name != "from_delta"
    }
    #: 사건의 카드는 읽을 수 있다 (소환은 ``CardMovement`` 가 아니어도
    #: 분명히 카드 한 장의 사건이고, ``instance`` 가 그 예외를 처리한다).
    assert timing.instance is not None


def test_08_the_event_does_reach_a_trigger_candidate(repository):
    """
    §6 ⑥  TimingPoint → Trigger Candidate = **구조로는 이어진다.**

    손으로 등록한 선언 하나로 실제 후보가 나온다. 즉 "자료 구조가 없다" 가
    아니다 — ``test_09`` 가 보여 주듯 **production 이 부르지 않는다.**
    """
    duel = live_duel(repository)
    state, execution = execute_summon(duel, PlayerAction.special_summon, MINE)
    view = GameStateView.from_state(state, viewer=MINE)
    timing = observed(state, execution, viewer=MINE, actor=MINE)[0].timing

    registry = TriggerRegistry(
        (
            TriggerSpec(
                EffectRef(LUSTER_DRAGON, 0),
                TimingPoint.MONSTER_SUMMONED,
                requirement=TriggerRequirement.OPTIONAL,
                activates_from=frozenset({Zone.MZONE}),
            ),
        )
    )
    collected = TriggerCollector(view, registry).collect(timing)

    assert len(collected.candidates) >= 1
    assert collected.event.canonical_state() == timing.canonical_state()


# ======================================================================
# C. LIVE / DORMANT 경계 (§3 Q7 · Q8)
# ======================================================================


def test_09_the_live_duel_drops_the_delta_at_its_own_door(repository):
    """
    §3 Q8 — **끊기는 자리는 정확히 여기다.**

    ``Duel._apply_board`` 는 ``ActionExecution`` 을 받는다. 그 안에는 소환
    delta 가 분명히 들어 있다. 그런데 ``DuelStep`` 에는 그것을 담을 칸이
    **없고**, ``Duel`` 은 ``EventReader`` 를 부르지도 않는다.

    일반 소환으로 보인다 — 특수 소환은 관문에서 막히므로 (``test_10``),
    **live 에서 실제로 일어나는** 소환으로 측정해야 거짓이 섞이지 않는다.
    """
    duel = live_duel(repository)
    chosen = None
    for _ in range(80):
        if duel.advance() is not None:
            continue
        legal = duel.legal_actions()
        candidates = [
            action
            for action in legal.allowed
            if action.kind is PlayerActionKind.NORMAL_SUMMON
        ]
        if candidates:
            chosen = candidates[0]
            break
        if not legal.allowed:
            break
        duel.apply(legal.allowed[0])
    assert chosen is not None, "live 에서 일반 소환이 한 번도 허가되지 않았다"

    #: 같은 행위를 사본에서 실행기에 직접 주면 delta 가 **있다.**
    probe = duel.state.clone()
    execution = duel_executor().execute(
        probe, chosen, authorization=ValidationResult.valid()
    )
    assert [type(delta).__name__ for delta in execution.deltas] == ["MonsterSummoned"]

    #: 그런데 live 경로로 같은 것을 적용하면 돌아오는 것에 delta 가 **없다.**
    step = duel.apply(chosen)
    assert step.accepted and step.code is ValidationCode.OK
    assert set(DuelStep.__dataclass_fields__) == {
        "action",
        "accepted",
        "code",
        "reason",
        "result",
    }
    assert not hasattr(step, "deltas")

    #: 그리고 ``duel.py`` 는 사건 · 트리거 계층의 이름을 **하나도** 모른다.
    duel_source = source_of("engine/duel.py")
    for absent in (
        "EventReader",
        "TimingEvent",
        "TimingPoint",
        "timing_for",
        "TriggerRegistry",
        "TriggerCollector",
        "MonsterSummoned",
        "SummonKind",
    ):
        assert absent not in duel_source, absent


def test_10_the_live_gate_refuses_a_special_summon_and_says_unknown(repository):
    """
    §3 Q7 · §8 — live 에서 특수 소환은 **UNKNOWN 으로 막힌다.**

    ``INVALID`` 가 아니다. "특수 소환할 수 없다" 가 아니라 **"조건을 읽을
    계층이 없다"** 이고, 두 답을 합치면 거짓이 된다.

    그런데 실행기 쪽은 **이미 연결되어 있다** — ``duel_executor`` 가
    ``SpecialSummonHandler`` 를 등록한다. 즉 막는 것은 실행기가 아니라 관문
    하나다.
    """
    duel = live_duel(repository)
    source = list(duel.state.player(MINE).hand)[0].instance_id
    action = PlayerAction.special_summon(actor=MINE, source=source)

    verdict = ActionValidator(duel.view(MINE)).validate(action)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.validity is not ActionValidity.INVALID
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert verdict.missing_rule == SPECIAL_SUMMON_CONDITION_RULE

    step = duel.apply(action)
    assert not step.accepted
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED

    #: 후보에도 없고 **보류 목록에도 없다** — ``legal_actions`` 가 특수 소환
    #: 행위를 아예 만들어 보지 않기 때문이다 (패의 카드마다 세 가지만
    #: 만든다). 그래서 "아직 못 한다" 는 정직한 기록조차 남지 않는다.
    legal = duel.legal_actions(MINE)
    assert PlayerActionKind.SPECIAL_SUMMON not in legal.kinds()
    assert PlayerActionKind.SPECIAL_SUMMON not in {
        held.kind for held in legal.withheld
    }

    #: 그러나 실행기는 그 일을 **안다.**
    assert PlayerActionKind.SPECIAL_SUMMON in duel_executor()._handlers

    #: ``UNKNOWN`` 을 지키는 것이 **둘**이다. 하나만 확인하면 다른 하나를
    #: 떼어낸 변경이 조용히 지나간다 (고의 위반 4번에서 실제로 그랬다).
    #:
    #: ① 요구 목록에 실린 "없는 규칙" 하나.
    assert UnimplementedRule in {
        type(requirement.condition)
        for requirement in _special_summon(ActionValidator(duel.view(MINE)), action)
    }
    #: ② 그리고 종류 자체가 **"끝까지 볼 수 있는 것" 목록에 없다** — 그쪽이
    #: 최종 결정권이고 (``validate`` 가 그 집합만 ``VALID`` 로 올린다),
    #: 둘이 겹치지 않는다는 것은 import 시점에 단정되어 있다.
    assert PlayerActionKind.SPECIAL_SUMMON not in _COMPLETE_RULES
    assert _MISSING_RULE[PlayerActionKind.SPECIAL_SUMMON] == (
        SPECIAL_SUMMON_CONDITION_RULE
    )
    assert not (_COMPLETE_RULES & set(_MISSING_RULE))


def test_11_a_failed_special_summon_leaves_no_event_at_all(repository):
    """
    §8 — **"시도했다" 는 표현되지 않는다.**

    몬스터 존을 채워 실패시키면 delta 가 0건이고, 사건도 0건이며, 판은
    **한 글자도** 바뀌지 않는다.

    이것은 결함이 아니라 **올바른 침묵**이다 (일어나지 않은 일에 사건을
    만들지 않는다). 다만 그 결과로 공식 스크립트의 ``EVENT_SPSUMMON``
    (선언, 50블록) 과 ``EVENT_SPSUMMON_NEGATED`` (무효, 3블록) 에 대응하는
    것이 **없다** — 성공한 특수 소환만 사건이 된다.
    """
    duel = live_duel(repository, deck_size=30)
    state = duel.state.clone()
    player = state.player(MINE)
    while len(player.zone(Zone.MZONE)) < 5:
        state.move(
            player.deck.top(),
            Zone.MZONE,
            to_player=MINE,
            position=Position.FACEUP_ATTACK,
        )
    assert len(player.zone(Zone.MZONE)) == 5

    before_hash = state.state_hash()
    source = list(player.hand)[0].instance_id
    execution = duel_executor().execute(
        state,
        PlayerAction.special_summon(actor=MINE, source=source),
        authorization=AUDIT_GRANT,
    )

    assert execution.status.value != "executed"
    assert execution.deltas == ()
    assert state.state_hash() == before_hash
    assert observed(state, execution, viewer=MINE, actor=MINE) == ()


# ======================================================================
# D. 선언이 종류를 말할 수 없다 (이 Phase 의 중심 발견)
# ======================================================================


def test_12_no_registered_effect_performs_a_special_summon():
    """
    §5 A — 등재 16효과 중 ``SPECIAL_SUMMON`` 을 쓰는 것은 **0개**다.

    그런데 **죽은 자의 소생은 목록에 있다** — ``operations=()`` 와
    ``executable=False`` 로, **왜 못 옮겼는지 적어 둔 채**로. 즉 데이터
    계층은 "아직 안 했다" 가 아니라 **"읽고 나서 거절했다"** 다.
    """
    kinds = [
        operation.kind
        for entry in EFFECT_LIBRARY
        for operation in entry.definition.operations
    ]
    assert OperationKind.SPECIAL_SUMMON not in kinds
    #: 열거가 공허하지 않음을 **실제로 있는 종류**로 고정한다.
    assert {kind.value for kind in kinds} == {
        "change_life",
        "destroy",
        "discard",
        "draw",
        "return_to_deck",
        "return_to_hand",
        "send_to_grave",
        "shuffle",
    }

    reborn = entry_for(EffectRef(MONSTER_REBORN, 0))
    assert reborn is not None, "죽은 자의 소생은 목록에 있다"
    assert reborn.definition.operations == ()
    assert reborn.executable is False
    #: 거절의 **이유가 둘 다 적혀 있다.**
    assert "IsCanBeSpecialSummoned" in reborn.note
    assert "STRUCTURAL-61" in reborn.note
    #: 실행 불가 항목은 셋이고, 그 중 하나가 이것이다.
    assert sum(1 for entry in EFFECT_LIBRARY if not entry.executable) == 3


def test_13_a_declaration_cannot_say_special_nor_whose(repository):
    """
    **이 Phase 의 중심 발견.** 선언 계층은 특수 소환을 **가리킬 수 없다.**

    셋이 겹쳐 있다.

    1. ``TriggerSpec`` 에 소환 종류를 적을 칸이 **없다.**
    2. ``MONSTER_SUMMONED`` 시점에는 기존 세 필터조차 **금지**된다 —
       ``__post_init__`` 가 거절한다.
    3. 그래서 ``matches`` 는 **내 일반 소환 · 내 특수 소환 · 상대의 특수
       소환을 전부 같은 것으로 본다.** ``actor`` 도 보지 않는다.

    결과가 ``UNKNOWN`` 이 아니라는 점이 핵심이다. 3-E-45 가 ``CARD_MOVED``
    에서 "적었는데 읽을 수 없으면 ``UNKNOWN``" 을 만들어 두었는데, 여기서는
    **적을 수가 없으므로** 그 정직한 길에 닿지 못하고 ``VALID/OK`` 가 난다.
    """
    assert "summon" not in TriggerSpec.__dataclass_fields__
    assert set(TriggerSpec.__dataclass_fields__) == {
        "effect_ref",
        "point",
        "requirement",
        "wording",
        "operations",
        "from_zones",
        "to_zones",
        "activates_from",
        "condition",
    }

    for name, keyword in (
        ("operations", {"operations": frozenset({OperationKind.SPECIAL_SUMMON})}),
        ("from_zones", {"from_zones": frozenset({Zone.GRAVE})}),
        ("to_zones", {"to_zones": frozenset({Zone.MZONE})}),
    ):
        with pytest.raises(TriggerError) as refusal:
            TriggerSpec(
                EffectRef(LUSTER_DRAGON, 0), TimingPoint.MONSTER_SUMMONED, **keyword
            )
        assert name in str(refusal.value)

    spec = TriggerSpec(EffectRef(LUSTER_DRAGON, 0), TimingPoint.MONSTER_SUMMONED)
    mine_normal = TimingEvent.from_delta(monster_summoned(SummonKind.NORMAL))
    mine_special = TimingEvent.from_delta(monster_summoned(SummonKind.SPECIAL))
    their_special = TimingEvent.from_delta(
        monster_summoned(SummonKind.SPECIAL, player=THEIRS)
    )

    #: 셋 다 같은 시점이고, 하나의 선언이 셋 다 잡는다.
    assert mine_normal.point is mine_special.point is their_special.point
    assert spec.matches(mine_normal)
    assert spec.matches(mine_special)
    assert spec.matches(their_special)
    #: ``actor`` 는 사건에 분명히 실려 있는데도 비교에 쓰이지 않는다.
    assert (mine_special.actor, their_special.actor) == (MINE, THEIRS)
    registry = TriggerRegistry((spec,))
    assert (
        len(registry.watching(mine_normal))
        == len(registry.watching(mine_special))
        == len(registry.watching(their_special))
        == 1
    )
    #: ``matches`` 의 본문이 ``actor`` 를 읽지 않는다는 것을 구문으로 확인한다
    #: (문자열 창이 아니라 그 함수의 본문만 본다).
    body = ast.get_source_segment(
        source_of("engine/trigger.py"),
        next(
            node
            for node in ast.walk(ast.parse(source_of("engine/trigger.py")))
            if isinstance(node, ast.ClassDef) and node.name == "TriggerSpec"
            for node in node.body
            if isinstance(node, ast.FunctionDef) and node.name == "matches"
        ),
    )
    assert "actor" not in body
    assert "summon" not in body


def test_14_the_dormant_gate_answers_valid_for_all_three(repository):
    """
    ``test_13`` 의 **결과를 판정기에서 확인한다.**

    dormant 다섯 관문 중 ``EVENT_RELATION`` 은 세 경우 모두 ``VALID/OK`` 를
    낸다 — 내 일반 소환에도 **확신 있는 승인**이 난다. 이것이
    "구조가 일부만 있다" 보다 나쁜 상태인 이유다: 틀린 답이 ``UNKNOWN`` 으로
    표시되지 않는다.
    """
    duel = live_duel(repository)
    spec = TriggerSpec(
        EffectRef(LUSTER_DRAGON, 0),
        TimingPoint.MONSTER_SUMMONED,
        requirement=TriggerRequirement.OPTIONAL,
        activates_from=frozenset({Zone.MZONE}),
    )
    registry = TriggerRegistry((spec,))

    verdicts = {}
    for label, actor, builder in (
        ("mine_normal", MINE, PlayerAction.normal_summon),
        ("mine_special", MINE, PlayerAction.special_summon),
        ("their_special", THEIRS, PlayerAction.special_summon),
    ):
        state, execution = execute_summon(duel, builder, actor)
        view = GameStateView.from_state(state, viewer=MINE)
        timing = observed(state, execution, viewer=MINE, actor=actor)[0].timing
        collection = TriggerCollector(view, registry).collect(timing)
        assert collection.candidates, label
        eligibility = TriggerEligibilityJudge(view).judge(
            collection.candidates[0], spec, timing
        )
        gate = next(
            verdict
            for verdict in eligibility.gates
            if verdict.gate is EligibilityGate.EVENT_RELATION
        )
        verdicts[label] = (
            timing.delta.summon,
            timing.actor,
            gate.validity,
            gate.code,
        )

    #: 소환 종류와 행위자는 **서로 다르다.**
    assert verdicts["mine_normal"][0] is SummonKind.NORMAL
    assert verdicts["mine_special"][0] is SummonKind.SPECIAL
    assert verdicts["their_special"][1] == THEIRS
    #: 그런데 관문의 답은 **셋 다 똑같다.**
    answers = {(validity, code) for _, _, validity, code in verdicts.values()}
    assert answers == {(ActionValidity.VALID, ValidationCode.OK)}
    assert ActionValidity.UNKNOWN not in {validity for _, _, validity, _ in verdicts.values()}


# ======================================================================
# E. 실제 카드 corpus (§5)
# ======================================================================


def test_15_the_script_corpus_separates_events_from_restrictions(repository):
    """
    §5 — 공식 스크립트는 **사건과 정적 제약을 다른 이름**으로 적는다.

    ``EVENT_*`` 는 "일어났다" 이고 ``EFFECT_*`` 는 "이렇게 할 수 없다/이런
    절차다" 다. 둘이 ``EffectSpec.code`` 라는 **한 칸**에 섞여 들어온다 —
    즉 그 칸을 그대로 "사건" 으로 읽으면 안 된다.
    """
    counts: dict[str, int] = {}
    blocks = 0
    for card in repository.all_cards():
        for _, spec in iter_effects(card):
            blocks += 1
            if spec.code:
                counts[spec.code] = counts.get(spec.code, 0) + 1

    #: 🔴 Phase 3-F-28 에서 34,631 → 34,632, ``code`` 있는 블록 30,084 →
    #: 30,085. 로더가 블록 주석 안의 효과를 세던 것을 그만두고
    #: (``c9409625`` −1), ``c:RegisterEffect`` 로 이 카드에 등록되는
    #: ``local`` 없는 / ``e`` 로 시작하지 않는 블록을 세기 시작했다
    #: (``c9839115`` · ``c74506079`` +2). ``code`` 종류 수 298 은 그대로다.
    assert blocks == 34632
    #: 🔴 Phase 3-F-31 에서 ``code`` 있는 블록 30,085 → **30,084**.
    #: ``c44887817`` ordinal 1 의 ``code`` 가 귀속 오류로 생긴 값이었고
    #: 이제 ``None`` 이다. 블록 수 34,632 는 그대로다.
    assert sum(counts.values()) == 30084
    assert len(counts) == 298

    summon_codes = {code: n for code, n in counts.items() if "SUMMON" in code}
    assert len(summon_codes) == 26
    #: 🔴 Phase 3-F-28 에서 5,979 → 5,980 — ``c9839115`` 의 ``e1`` 에 흘러든
    #: 값이 치워지면서 ``EVENT_SPSUMMON_SUCCESS`` 가 제 블록으로 돌아왔다.
    assert sum(summon_codes.values()) == 5980

    events = {code: n for code, n in summon_codes.items() if code.startswith("EVENT_")}
    statics = {
        code: n for code, n in summon_codes.items() if code.startswith("EFFECT_")
    }
    assert set(summon_codes) == set(events) | set(statics)
    #: 사건 쪽이 더 많고, 둘이 섞여 있다.
    #: 🔴 Phase 3-F-28 에서 사건 쪽만 3,622 → 3,623 (위 참고).
    assert sum(events.values()) == 3623
    assert sum(statics.values()) == 2357

    #: 성공 · 선언 · 무효가 **서로 다른 이름**으로 구분되어 있다.
    #: 🔴 Phase 3-F-28 에서 2,114 → 2,115.
    assert summon_codes["EVENT_SPSUMMON_SUCCESS"] == 2115
    assert summon_codes["EVENT_SPSUMMON"] == 50
    assert summon_codes["EVENT_SPSUMMON_NEGATED"] == 3
    #: 엔진의 ``TimingPoint`` 에는 그 셋에 해당하는 이름이 **하나**뿐이다.
    assert len([point for point in TimingPoint if "summon" in point.value]) == 1


def test_16_five_real_cards_show_the_four_relationships(repository):
    """
    §5 A~D — **실제 카드 다섯 장**이 네 관계를 각각 보인다.

    ``card`` / ``source`` (Lua) / ``code`` (파서) / ``등재`` 를 **한 장씩
    실제로 읽는다** — 이름으로 추론하지 않는다.
    """
    cases = {
        #: A·D — 특수 소환을 **수행**하고, 그 사건을 참조하지 않는다.
        83764718: ("죽은 자의 소생", ("Duel.SpecialSummon(",), ["EVENT_FREE_CHAIN"]),
        #: B — 특수 소환 **발생에 반응**한다 (몬스터).
        23434538: (
            "증식의 G",
            ("EVENT_SPSUMMON_SUCCESS",),
            ["EVENT_FREE_CHAIN", "EVENT_SPSUMMON_SUCCESS", "EVENT_SPSUMMON_SUCCESS", "EVENT_CHAIN_SOLVED"],
        ),
        #: B — 같은 사건에 반응하는 **함정**. 함정은 live 범위 밖이다 (3-F-4).
        1005587: (
            "연옥의 함정 속으로",
            ("EVENT_SPSUMMON_SUCCESS",),
            ["EVENT_SPSUMMON_SUCCESS", "EFFECT_DISABLE"],
        ),
        #: A+B+정적제약이 한 장에 겹친 경우.
        10117149: (
            "분보그005",
            ("Duel.SpecialSummon(", "EVENT_SPSUMMON_SUCCESS"),
            [
                "EFFECT_CANNOT_SPECIAL_SUMMON",
                "EVENT_SUMMON_SUCCESS",
                "EVENT_SPSUMMON_SUCCESS",
                "EFFECT_UPDATE_ATTACK",
                "EVENT_DESTROYED",
            ],
        ),
        #: C·D — 특수 소환을 **수행하고 조건으로도 참조**하는데, ``code``
        #: 에는 그 사실이 **한 글자도 없다.**
        10065487: (
            "낙인상실",
            ("Duel.SpecialSummonStep(", "IsSpecialSummoned"),
            ["EVENT_FREE_CHAIN", "EVENT_PHASE"],
        ),
    }

    for passcode, (name, lua_marks, codes) in cases.items():
        card = repository.get(passcode)
        assert card is not None, passcode
        assert (card.name_ko or card.name) == name, passcode

        script = PROJECT_ROOT / f"c{passcode}.lua"
        assert script.is_file(), passcode
        text = script.read_text(encoding="utf-8", errors="replace")
        for mark in lua_marks:
            assert mark in text, (passcode, mark)

        assert [spec.code for _, spec in iter_effects(card)] == codes, passcode

    #: **다섯 장 중 등재된 것은 죽은 자의 소생 하나**이고 실행되지 않는다.
    registered = [
        passcode
        for passcode in cases
        if any(entry.definition.source_card_id == passcode for entry in EFFECT_LIBRARY)
    ]
    assert registered == [83764718]

    #: 그리고 ``낙인상실`` 이 §7 을 그대로 보여 준다 — **행위는 Lua 에 있고
    #: ``code`` 는 그것을 모른다.** ``code`` 를 Operation 으로 읽으면 틀린다.
    assert "SPSUMMON" not in " ".join(cases[10065487][2])


def test_17_the_three_example_cards_need_three_different_things(repository):
    """
    §13 — 증G · 후와로스 · 드롤을 **구현하지 않고**, 각자 무엇을 요구하는지만
    읽는다.

    셋이 요구하는 것이 **서로 다르다** — 하나의 "특수소환 사건" 으로 묶이지
    않는다. 이것이 이번 Phase 가 패트랩을 범위 밖으로 둔 이유다.
    """
    wanted = {
        23434538: ("증식의 G", {"EVENT_SPSUMMON_SUCCESS", "EVENT_CHAIN_SOLVED"}),
        42141493: (
            "마루챠미 후와로스",
            {"EVENT_SPSUMMON_SUCCESS", "EVENT_PHASE", "EVENT_CHAIN_SOLVED"},
        ),
        #: 드롤은 특수 소환과 **상관이 없다** — 스크립트가 자기 사건을
        #: 직접 만든다 (``EVENT_CUSTOM``).
        94145021: ("드롤 & 로크 버드", {"EVENT_CUSTOM"}),
    }
    for passcode, (name, needed) in wanted.items():
        card = repository.get(passcode)
        assert (card.name_ko or card.name) == name, passcode
        codes = {spec.code for _, spec in iter_effects(card) if spec.code}
        assert needed <= codes, (passcode, needed - codes)

    drole = {spec.code for _, spec in iter_effects(repository.get(94145021)) if spec.code}
    assert not any("SPSUMMON" in code for code in drole)
    assert {"EFFECT_CANNOT_TO_HAND", "EFFECT_CANNOT_DRAW"} <= drole

    #: 엔진이 들고 있는 시점 이름은 여덟 개이고, 그 중 ``EVENT_CUSTOM`` ·
    #: ``EVENT_CHAIN_SOLVED`` 에 대응하는 것은 **없다.**
    points = {point.value for point in TimingPoint}
    assert len(points) == 8
    assert "chain_solved" not in points
    assert "custom" not in points
    #: ``EFFECT_RESOLVED`` 는 효과 하나의 해결이고 체인 전체의 해결이 아니다.
    assert TimingPoint.EFFECT_RESOLVED.value == "effect_resolved"


# ======================================================================
# F. 경계 보존 (§12 · §14 · §15 · §19)
# ======================================================================


def test_18_reading_summon_events_breaks_no_boundary(repository):
    """
    §14 · §15 — 상대의 특수 소환을 **관측으로** 읽어도 숨은 정보는 새지 않고,
    판도 난수도 움직이지 않는다.

    소환된 카드는 앞면으로 필드에 나왔으므로 공개 정보다. 상대의 **남은
    패**는 그대로 가려져 있다 (``size`` 만 읽힌다 — 3-F-2 와 같은 경계).
    """
    duel = live_duel(repository)
    state, execution = execute_summon(duel, PlayerAction.special_summon, THEIRS)

    before_hash, before_rng = state.state_hash(), repr(state.rng)
    view = GameStateView.from_state(state, viewer=MINE)
    event = EventReader(view).read(execution, actor=THEIRS)[0]

    assert event.actor == THEIRS
    assert event.delta.summon is SummonKind.SPECIAL

    #: 소환된 카드는 내 쪽에서 보인다 — 필드에 앞면으로 있으므로.
    summoned = view.find(event.delta.card)
    assert summoned is not None
    assert summoned.zone is Zone.MZONE

    #: 상대의 남은 패는 **여전히 가려져 있다.**
    opponent_hand = view.player(THEIRS).zone(Zone.HAND)
    assert opponent_hand.concealed is True
    assert opponent_hand.cards == ()
    assert opponent_hand.size >= 0

    #: 읽는 일은 판을 바꾸지 않는다.
    assert state.state_hash() == before_hash
    assert repr(state.rng) == before_rng


def test_19_this_phase_changed_no_production_code_and_no_ranking(repository):
    """
    §12 · §19 — production 은 **한 줄도** 바뀌지 않았고 탐색 순위도 그대로다.

    순위는 **실제로 돌려서** 확인한다 — 6판 611결정의 digest 를 못박는다.
    이 숫자가 바뀌면 Evaluation 이나 Search 가 움직였다는 뜻이다.
    """
    from agent.runner import DuelRunner
    from agent.search import search_policy

    deck = [LUSTER_DRAGON] * 12 + [55144522] * 4 + [5915629] * 4
    digest = hashlib.sha256()
    decisions = 0
    for seed in (1, 2, 3, 4, 5, 6):
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
        transcript = DuelRunner(
            duel, (search_policy(duel), search_policy(duel))
        ).run()
        decisions += len(transcript.entries)
        digest.update(
            repr(
                [
                    (
                        entry.seat,
                        entry.policy,
                        entry.action.kind.value if entry.action is not None else None,
                        entry.action.source.value
                        if entry.action is not None and entry.action.source is not None
                        else None,
                        entry.accepted,
                    )
                    for entry in transcript.entries
                ]
            ).encode()
        )

    assert decisions == 611
    assert digest.hexdigest() == (
        "30fa3597a24d4511d8c92ce9f9921412ffada7546675c4d7d5765381402c4175"
    )

    #: 그리고 ``agent/`` 는 소환 · 사건 · 트리거 어휘를 **모른다.**
    for relative in (
        "agent/evaluation.py",
        "agent/search.py",
        "agent/heuristic.py",
        "agent/policy.py",
        "agent/simulation.py",
    ):
        text = source_of(relative)
        for absent in (
            "engine.trigger",
            "engine.event_pipeline",
            "SummonKind",
            "MonsterSummoned",
            "SPECIAL_SUMMON",
        ):
            assert absent not in text, (relative, absent)
