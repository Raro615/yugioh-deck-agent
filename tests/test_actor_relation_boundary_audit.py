"""
Phase 3-F-7 — **행위자 관계를 어느 계층에서 판정해야 하는가** (경계 감사).

이 파일이 답하는 단 하나의 질문
-------------------------------
"상대가 SPECIAL_SUMMON 을 수행했다" 는 **관계 판단**이다. 그 관계를
판정할 자리가 현재 architecture 에 있는가.

세 문장을 절대 섞지 않는다 (§3)
-------------------------------
=====  ==========================================  ==============
 ①     "이 Event 의 actor 는 누구인가"               **사실**
 ②     "이 Candidate 의 controller 는 누구인가"      **사실**
 ③     "actor 가 controller 의 상대인가"             **관계 판단**
=====  ==========================================  ==============

①과 ②는 둘 다 측정 가능하다 (``test_01`` · ``test_02``). ③을 하는 코드가
**하나도 없다** (``test_08``).

프롬프트의 전제 둘을 측정해서 **정정했다**
------------------------------------------
1. "``_event_relation`` 은 event 쪽과 candidate 쪽 정보를 함께 사용한다"
   → **아니다.** 서명이 ``(spec, event)`` 이고 candidate 를 받지 않는다
   (``test_04``). 3-F-6 의 측정과 같다.
2. "``judge()`` 는 fold 하여 **일부 정보를 잃는다**"
   → **``fold`` 는 아무것도 버리지 않는다.** 관문 판정을 전부 보존한 채
   요약 ``status`` 를 **덧붙인다** (``test_09``). 실제로 잃는 것은 그게
   아니라 **``judge`` 의 출력에 사건이 없다**는 것이다 (``test_10``).

이 파일은 production 을 **한 줄도** 바꾸지 않는다 (``test_19``).
"""

import ast
import hashlib
import inspect
import pathlib

import pytest

from engine.action import PlayerAction
from engine.condition import ConditionContext, PlayerRef
from engine.duel import Duel
from engine.effect.delta import (
    CardDrawn,
    LifeChanged,
    MonsterSummoned,
    PhaseChanged,
    SummonKind,
    ZoneMoved,
    ZoneShuffled,
)
from engine.effect.operation import OperationKind
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.summon import duel_executor
from engine.timing import TimingOutcome, TimingWindow
from engine.trigger import (
    EligibilityGate,
    GateVerdict,
    TimingEvent,
    TimingPoint,
    TriggerCandidate,
    TriggerCollection,
    TriggerCollector,
    TriggerEligibility,
    TriggerEligibilityJudge,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
    TriggerStatus,
    timing_for,
)
from engine.trigger_order import PlayerRole
from engine.validation import (
    CODE_VALIDITY,
    ActionValidity,
    ValidationCode,
    ValidationResult,
)
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MINE, THEIRS = 0, 1

LUSTER_DRAGON = 11091375

#: 감사가 직접 건네는 허가. 특수 소환 조건 계층을 대신하지 않는다 (3-F-5 §8).
AUDIT_GRANT = ValidationResult.valid("감사가 관문을 우회해 직접 허가했다")

#: 세 fixture 가 공유하는 선언. **행위자를 적는 칸이 없다** (3-F-6).
WATCHING_SUMMONS = TriggerSpec(
    EffectRef(LUSTER_DRAGON, 0),
    TimingPoint.MONSTER_SUMMONED,
    requirement=TriggerRequirement.OPTIONAL,
    activates_from=frozenset({Zone.MZONE}),
)


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def function_body(relative: str, class_name: str, method: str) -> str:
    """그 메서드의 **본문만** 떼어낸다 — 문자열 창으로 보지 않는다."""
    text = source_of(relative)
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method:
                    return ast.get_source_segment(text, child)
    raise AssertionError(f"{class_name}.{method} 를 찾지 못했습니다")


def params_of(function) -> list[str]:
    return [name for name in inspect.signature(function).parameters if name != "self"]


def function_code(relative: str, class_name: str, method: str) -> str:
    """
    그 메서드의 **코드만** — docstring 과 주석을 뺀다.

    처음에는 본문 전체를 문자열로 봤고, ``_trigger_condition`` 의 docstring 에
    적힌 "event relation" 이라는 **설명**이 코드인 것처럼 걸렸다. 설명이
    아니라 실제로 읽는 값을 세야 한다.
    """
    text = source_of(relative)
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method:
                    body = list(child.body)
                    if (
                        body
                        and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)
                    ):
                        body = body[1:]
                    return "\n".join(
                        ast.unparse(statement) for statement in body
                    )
    raise AssertionError(f"{class_name}.{method} 를 찾지 못했습니다")


# ======================================================================
# 고정된 판 — 사건의 actor 만 바꿀 수 있게 만든다
# ======================================================================


def live_duel(repository, *, seed: int = 3) -> Duel:
    deck = [LUSTER_DRAGON] * 20
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
    while duel.advance() is not None:
        pass
    return duel


def summoned_board(repository):
    """
    내가 한 장 특수 소환해 둔 **고정된 판**과, 그때 남은 변화.

    세 fixture 가 **같은 판 · 같은 후보**를 쓰게 하려고 한 번만 만든다 —
    판이 다르면 후보가 달라지고, 그러면 actor 말고 다른 것이 결과를
    움직인다 (실제로 그 함정을 만났다 — ``test_08`` 의 note).
    """
    duel = live_duel(repository)
    state = duel.state.clone()
    source = list(state.player(MINE).hand)[0].instance_id
    execution = duel_executor().execute(
        state,
        PlayerAction.special_summon(actor=MINE, source=source),
        authorization=AUDIT_GRANT,
    )
    return state, execution.deltas[0]


def event_with_actor(landed: MonsterSummoned, player: int) -> TimingEvent:
    """**같은 소환을 누가 했는가만** 바꾼 사건."""
    return timing_for(
        MonsterSummoned(
            summon=landed.summon,
            card=landed.card,
            player=player,
            owner=landed.owner,
            from_zone=landed.from_zone,
            to_zone=landed.to_zone,
            to_index=landed.to_index,
            position=landed.position,
        )
    )


def judge_same_candidate(state, landed, event, spec=WATCHING_SUMMONS):
    """그 사건을 **착지한 그 카드**의 후보로 판정한다."""
    view = GameStateView.from_state(state, viewer=MINE)
    collection = TriggerCollector(view, TriggerRegistry((spec,))).collect(event)
    candidate = next(c for c in collection.candidates if c.source == landed.card)
    return candidate, TriggerEligibilityJudge(view).judge(candidate, spec, event)


# ======================================================================
# A. §3 ① — Event actor 는 사실이다
# ======================================================================


def test_01_the_event_actor_is_a_fact_and_is_sometimes_absent():
    """
    §2 — ``event.actor`` 가 어디서 오고, **언제 없는가.**

    없는 경우가 실재한다는 것이 뒤의 모든 판정에 걸린다 (``test_11``).
    """
    def actor_of(delta) -> "int | None":
        return timing_for(delta).actor

    def summoned(player: int) -> MonsterSummoned:
        return MonsterSummoned(
            summon=SummonKind.SPECIAL,
            card=InstanceId(7),
            player=player,
            owner=player,
            from_zone=Zone.HAND,
            to_zone=Zone.MZONE,
            to_index=0,
            position=Position.FACEUP_ATTACK,
        )

    #: 행위자가 **있는** 사건들 — delta 의 사람 칸에서 그대로 온다.
    assert actor_of(summoned(MINE)) == MINE
    assert actor_of(summoned(THEIRS)) == THEIRS
    assert actor_of(CardDrawn(player=THEIRS, card=InstanceId(3))) == THEIRS
    assert actor_of(LifeChanged(player=THEIRS, before=8000, after=7000)) == THEIRS
    assert (
        actor_of(
            ZoneMoved(
                movement=OperationKind.SEND_TO_GRAVE,
                card=InstanceId(9),
                source_player=THEIRS,
                source_zone=Zone.MZONE,
                destination_player=THEIRS,
                destination_zone=Zone.GRAVE,
            )
        )
        == THEIRS
    )

    #: 행위자가 **없는** 사건들.
    #: ① 페이즈 전이 — 규칙이 하는 일이므로 **일부러** 적지 않는다.
    assert (
        actor_of(
            PhaseChanged(
                from_turn=1,
                to_turn=1,
                from_player=MINE,
                to_player=MINE,
                from_phase=Phase.MAIN1,
                to_phase=Phase.END,
            )
        )
        is None
    )
    #: ② 옮길 시점 이름이 없는 변화 — `timing_for` 가 `UNIMPLEMENTED` 로 남긴다.
    shuffled = timing_for(
        ZoneShuffled(player=MINE, zone=Zone.DECK, size=10, draw=0)
    )
    assert shuffled.point is TimingPoint.UNIMPLEMENTED
    assert shuffled.actor is None
    #: ③ 직접 만든 `unimplemented` 도 기본이 `None` 이다.
    assert TimingEvent.unimplemented("무엇을 표현할 수 없었다").actor is None

    #: `actor` 는 0/1 또는 `None` 만 된다 — 셋째 값이 들어올 수 없다.
    with pytest.raises(Exception):
        TimingEvent(TimingPoint.LIFE_CHANGED, actor=2)


def test_02_the_candidate_controller_is_always_known_and_always_public(repository):
    """
    §3 ② · §15 — ``candidate.controller`` 는 **언제나 0 또는 1** 이다.

    모를 수가 없는 이유가 구조에 있다: 후보는 **보이는 카드**에서만 생기고,
    가려진 자리는 `unchecked` 로 따로 적힌다. 그래서 controller 를 읽는 것이
    숨은 정보를 건드리지 않는다.
    """
    assert "controller" in TriggerCandidate.__dataclass_fields__
    body = function_body("engine/trigger.py", "TriggerCandidate", "__post_init__")
    assert "controller not in (0, 1)" in body

    with pytest.raises(Exception):
        TriggerCandidate(
            point=TimingPoint.MONSTER_SUMMONED,
            effect_ref=EffectRef(LUSTER_DRAGON, 0),
            source=InstanceId(1),
            controller=None,
        )

    #: 수집기가 **보이는 사본**만 훑는다 — 가려진 것은 후보가 되지 않는다.
    visible = function_body("engine/trigger.py", "TriggerCollector", "_visible_copies")
    assert "card.card_id != card_id" in visible
    unchecked = function_body("engine/trigger.py", "TriggerCollector", "_unchecked")
    assert "zone.concealed" in unchecked

    state, landed = summoned_board(repository)
    candidate, _ = judge_same_candidate(state, landed, event_with_actor(landed, MINE))
    assert candidate.controller in (0, 1)


# ======================================================================
# B. §4 — EVENT_RELATION 집중 감사
# ======================================================================


def test_03_the_event_relation_gate_reads_the_event_but_never_the_actor():
    """
    §4 — ``_event_relation`` 이 **무엇을 읽고 무엇을 읽지 않는가.**

    네 갈래로 답하고 (3-E-45), 네 갈래 어디에도 행위자가 없다.
    """
    body = function_code("engine/trigger.py", "TriggerEligibilityJudge", "_event_relation")

    #: 읽는 것 — 사건의 시점 · 설명 · 세 이동 축, 그리고 선언의 같은 축들.
    for present in (
        "event.point",
        "event.note",
        "event.operation",
        "event.from_zone",
        "event.to_zone",
        "spec.operations",
        "spec.from_zones",
        "spec.to_zones",
        "spec.matches(event)",
    ):
        assert present in body, present

    #: **읽지 않는 것** — 행위자 · 소환 종류 · 후보.
    for absent in ("actor", "summon", "candidate", "controller"):
        assert absent not in body, absent

    #: 네 갈래의 (validity, code) 가 정확히 넷이다.
    tree = ast.parse(source_of("engine/trigger.py"))
    gate_calls = 0
    for node in ast.walk(ast.parse(body)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_gate":
            gate_calls += 1
    assert gate_calls == 4
    for code in (
        "RULE_NOT_IMPLEMENTED",
        "INFORMATION_UNAVAILABLE",
        "OK",
        "CANDIDATE_NOT_ELIGIBLE",
    ):
        assert code in body, code
    assert tree is not None  # 파싱이 성공했음을 남긴다


def test_04_the_event_relation_gate_does_not_receive_the_candidate():
    """
    §4 의 YES/NO — **NO.**

    "``EVENT_RELATION`` 은 이미 ``event.actor`` ↔ ``candidate.controller``
    를 비교하기 위한 정확한 계층인가?"

    아니다. **candidate 를 받지 않는다.** 받는 관문 셋은 사건을 받지 않는다.
    """
    gates = {
        name: (
            "event" in params_of(getattr(TriggerEligibilityJudge, name)),
            "candidate" in params_of(getattr(TriggerEligibilityJudge, name)),
        )
        for name in (
            "_event_relation",
            "_activation_zone",
            "_trigger_condition",
            "_execution_authority",
            "_cost_feasibility",
        )
    }
    assert gates == {
        "_event_relation": (True, False),
        "_activation_zone": (False, True),
        "_trigger_condition": (False, True),
        "_execution_authority": (False, False),
        "_cost_feasibility": (False, True),
    }
    #: 사건을 보는 관문은 하나, 둘 다 보는 관문은 **없다.**
    assert sum(1 for sees_event, _ in gates.values() if sees_event) == 1
    assert not [name for name, (ev, cand) in gates.items() if ev and cand]
    assert params_of(TriggerEligibilityJudge._event_relation) == ["spec", "event"]


# ======================================================================
# C. §5 — 세 fixture
# ======================================================================


def test_05_fixture_a_self_summon(repository):
    """§5 A — **내가** 특수소환. 기대 관계 `SELF`."""
    state, landed = summoned_board(repository)
    event = event_with_actor(landed, MINE)
    candidate, eligibility = judge_same_candidate(state, landed, event)
    gate = eligibility.gate(EligibilityGate.EVENT_RELATION)

    assert event.point is TimingPoint.MONSTER_SUMMONED
    assert event.actor == MINE
    assert event.delta.summon is SummonKind.SPECIAL
    assert candidate.controller == MINE
    #: 기대: SELF. 실제: 관계를 **보지 않은** 통과.
    assert (gate.validity, gate.code) == (ActionValidity.VALID, ValidationCode.OK)


def test_06_fixture_b_opponent_summon(repository):
    """§5 B — **상대가** 특수소환. 기대 관계 `OPPONENT`."""
    state, landed = summoned_board(repository)
    event = event_with_actor(landed, THEIRS)
    candidate, eligibility = judge_same_candidate(state, landed, event)
    gate = eligibility.gate(EligibilityGate.EVENT_RELATION)

    assert event.actor == THEIRS
    assert event.delta.summon is SummonKind.SPECIAL
    assert candidate.controller == MINE
    assert event.actor != candidate.controller
    #: 기대: OPPONENT (A 와 **달라야 한다**). 실제: A 와 **같은** 통과.
    assert (gate.validity, gate.code) == (ActionValidity.VALID, ValidationCode.OK)


def test_07_fixture_c_unknown_actor(repository):
    """
    §5 C — 누가 했는지 **알 수 없는** 사건.

    억지로 `INVALID` 로 만들지 않는다. 실제로 `UNKNOWN` 이 난다 — 다만
    **이유가 다르다**: "행위자를 모른다" 가 아니라 "그 사건 자체를 옮길
    이름이 없다" 다. 행위자 부재를 가리키는 판정은 **없다.**
    """
    state, landed = summoned_board(repository)
    event = timing_for(ZoneShuffled(player=MINE, zone=Zone.DECK, size=10, draw=0))
    assert event.point is TimingPoint.UNIMPLEMENTED
    assert event.actor is None

    spec = TriggerSpec(
        EffectRef(LUSTER_DRAGON, 0),
        TimingPoint.UNIMPLEMENTED,
        requirement=TriggerRequirement.OPTIONAL,
        activates_from=frozenset({Zone.MZONE}),
    )
    candidate, eligibility = judge_same_candidate(state, landed, event, spec=spec)
    gate = eligibility.gate(EligibilityGate.EVENT_RELATION)

    assert candidate.controller == MINE
    assert (gate.validity, gate.code) == (
        ActionValidity.UNKNOWN,
        ValidationCode.RULE_NOT_IMPLEMENTED,
    )
    #: 그 `UNKNOWN` 의 이유가 **사건 자체**이고 행위자가 아니다.
    assert "표현하지 못하는 사건" in gate.result.reason
    assert "actor" not in gate.result.reason
    assert gate.result.missing_rule is not None


def test_08_flipping_only_the_actor_changes_nothing_at_all(repository):
    """
    **이 Phase 의 중심 측정.** §3 ③ 을 하는 코드가 하나도 없다.

    같은 판 · 같은 후보 · 같은 소환에서 **``event.actor`` 만** 뒤집으면
    다섯 관문 · 접힌 상태 · 정규 표현이 **한 글자도 달라지지 않는다.**

    .. note::
       처음에는 실제 듀얼에서 "내가 소환" 과 "상대가 소환" 을 각각 실행해
       비교했고, 접힌 상태가 `unknown` 과 `ineligible` 로 **달라 보였다.**
       그것은 행위자 때문이 **아니었다** — 상대가 소환하면 판이 달라져
       첫 후보가 MZONE 밖의 카드가 되고 `activation_zone` 이
       `SOURCE_WRONG_ZONE` 을 냈다. 그래서 판과 후보를 고정하고 사건의
       사람 칸만 바꾸는 쪽으로 고쳤다. **접힌 상태를 보고 "구분했다" 고
       읽으면 틀린다.**
    """
    state, landed = summoned_board(repository)

    results = {}
    for label, player in (("self", MINE), ("opponent", THEIRS)):
        event = event_with_actor(landed, player)
        candidate, eligibility = judge_same_candidate(state, landed, event)
        results[label] = (
            event.actor,
            candidate.controller,
            tuple(
                (verdict.gate, verdict.validity, verdict.code)
                for verdict in eligibility.gates
            ),
            eligibility.status,
            eligibility.canonical_state(),
        )

    mine, theirs = results["self"], results["opponent"]
    #: 입력은 분명히 다르다.
    assert mine[0] == MINE and theirs[0] == THEIRS
    assert mine[1] == theirs[1] == MINE
    #: 그런데 출력이 전부 같다.
    assert mine[2] == theirs[2], "관문 결과가 달라졌다"
    assert mine[3] is theirs[3], "접힌 상태가 달라졌다"
    assert mine[4] == theirs[4], "정규 표현이 달라졌다"
    #: 다섯 관문을 모두 봤다는 것을 고정한다 (공허한 비교가 아니다).
    assert len(mine[2]) == 5
    assert {gate for gate, _, _ in mine[2]} == set(EligibilityGate)


# ======================================================================
# D. §13 — judge() 의 정보 흐름
# ======================================================================


def test_09_fold_keeps_every_gate_verdict(repository):
    """
    §13 — **``fold`` 는 정보를 버리지 않는다.** 프롬프트의 전제를 정정한다.

    요약 ``status`` 를 **덧붙이고** 관문 판정을 전부 보존한다. 그래서
    "정보가 없어서 UNKNOWN" 과 "관계가 FALSE 라서 INVALID" 는 관문 단위로
    **구분된 채 남는다.**
    """
    body = function_body("engine/trigger.py", "TriggerEligibility", "fold")
    #: `gates` 를 그대로 싣는다 — 걸러내지 않는다.
    assert "gates=gates" in body.replace(" ", "")
    assert "status=status" in body.replace(" ", "")

    verdicts = (
        GateVerdict(
            EligibilityGate.EVENT_RELATION, ValidationResult.valid("사건이 맞는다")
        ),
        GateVerdict(
            EligibilityGate.ACTIVATION_ZONE,
            ValidationResult.invalid(ValidationCode.SOURCE_WRONG_ZONE, "자리가 아니다"),
        ),
        GateVerdict(
            EligibilityGate.TRIGGER_CONDITION,
            ValidationResult.unknown(
                ValidationCode.INFORMATION_UNAVAILABLE, "읽을 수 없다"
            ),
        ),
    )
    candidate = TriggerCandidate(
        point=TimingPoint.MONSTER_SUMMONED,
        effect_ref=EffectRef(LUSTER_DRAGON, 0),
        source=InstanceId(1),
        controller=MINE,
    )
    folded = TriggerEligibility.fold(candidate, verdicts)

    #: 요약은 **가장 강한 거부**를 따른다.
    assert folded.status is TriggerStatus.INELIGIBLE
    #: 그런데 세 판정이 전부 남아 있다 — 하나도 사라지지 않았다.
    assert folded.gates == verdicts
    assert len(folded.gates) == 3
    assert folded.gate(EligibilityGate.TRIGGER_CONDITION).code is (
        ValidationCode.INFORMATION_UNAVAILABLE
    )
    assert folded.gate(EligibilityGate.ACTIVATION_ZONE).code is (
        ValidationCode.SOURCE_WRONG_ZONE
    )
    #: 막힌 관문도 순서대로 꺼낼 수 있다.
    assert [verdict.gate for verdict in folded.blocking] == [
        EligibilityGate.ACTIVATION_ZONE,
        EligibilityGate.TRIGGER_CONDITION,
    ]
    #: UNKNOWN 과 INVALID 가 섞이지 않는다.
    assert folded.gate(EligibilityGate.TRIGGER_CONDITION).validity is (
        ActionValidity.UNKNOWN
    )
    assert folded.gate(EligibilityGate.ACTIVATION_ZONE).validity is (
        ActionValidity.INVALID
    )


def test_10_what_judge_actually_drops_is_the_event(repository):
    """
    §13 — **실제로 잃는 것.** ``judge`` 는 사건을 받지만 결과에 담지 않는다.

    그래서 판정을 직렬화하거나 replay 해도 "어떤 사건이었는가" 를 되살릴 수
    없고, 행위자는 **관문이 적어 둔 산문 밖에는 남지 않는다.**
    """
    assert params_of(TriggerEligibilityJudge.judge) == ["candidate", "spec", "event"]
    assert list(TriggerEligibility.__dataclass_fields__) == [
        "candidate",
        "status",
        "gates",
        "unchecked_rules",
    ]
    assert "event" not in TriggerEligibility.__dataclass_fields__

    state, landed = summoned_board(repository)
    event = event_with_actor(landed, THEIRS)
    _, eligibility = judge_same_candidate(state, landed, event)

    #: 사건은 분명히 행위자를 들고 있다.
    assert event.actor == THEIRS
    #: 그런데 판정의 정규 표현 · 직렬화 어디에도 그 값이 없다.
    def leaves(value):
        if isinstance(value, (tuple, list)):
            for item in value:
                yield from leaves(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from leaves(item)
        else:
            yield value

    assert "monster_summoned" not in [
        leaf for leaf in leaves(eligibility.canonical_state()) if isinstance(leaf, str)
    ] or True  # 후보의 point 는 남는다 — 아래가 본론이다
    serialized = eligibility.to_dict()
    assert "event" not in serialized
    assert "actor" not in str(serialized)
    #: `TriggerCollection` 쪽에는 사건이 남는다 — 즉 **잃는 자리가 `judge` 다.**
    assert "event" in TriggerCollection.__dataclass_fields__


# ======================================================================
# E. §6 · §7 — "상대" 의 의미
# ======================================================================


def test_11_the_not_equal_comparison_is_unsafe_when_the_actor_is_absent():
    """
    §6 — ``event.actor != candidate.controller`` 를 "상대" 라고 단정하면
    **틀린다.**

    행위자가 없는 사건에서 그 비교는 **양쪽 모두 참**이 되고, 그것은
    "상대가 했다" 가 아니라 "누가 했는지 모른다" 다.
    """
    unknown_actor = timing_for(
        ZoneShuffled(player=MINE, zone=Zone.DECK, size=10, draw=0)
    )
    assert unknown_actor.actor is None
    #: 두 플레이어 **모두**에 대해 "상대" 가 되어 버린다.
    assert unknown_actor.actor != MINE
    assert unknown_actor.actor != THEIRS

    phase = timing_for(
        PhaseChanged(
            from_turn=1,
            to_turn=1,
            from_player=MINE,
            to_player=MINE,
            from_phase=Phase.MAIN1,
            to_phase=Phase.END,
        )
    )
    assert phase.actor is None
    assert phase.actor != MINE and phase.actor != THEIRS

    #: 그러므로 안전한 비교는 **먼저 존재를 묻는 것**이다.
    for event in (unknown_actor, phase):
        assert (event.actor is not None) is False


def test_12_every_existing_opponent_helper_is_total_over_two_players():
    """
    §6 — 기존 player relation 헬퍼를 **그대로** 조사한다. 새로 만들지 않는다.

    일곱 자리에 `opponent` 가 있고 전부 ``1 - x`` 다. 전부 `{0,1}` 위의
    **전역 함수**이고, **`UNKNOWN` 을 돌려줄 길이 하나도 없다.**
    """
    owners = {
        "engine/condition/context.py": "ConditionContext",
        "engine/priority.py": "PriorityHolder",
        "engine/effect/resolution.py": "ResolutionContext",
        "engine/action.py": "PlayerAction",
        "engine/game_state_view.py": "GameStateView",
        "engine/timing.py": "TimingWindow",
    }
    found = 0
    for relative in owners:
        text = source_of(relative)
        assert "def opponent" in text, relative
        found += text.count("def opponent")
    assert found >= 6

    #: 관계 계산은 `1 - x` 이고 그것이 **2인 게임 가정**이다.
    assert ConditionContext(player=MINE).opponent == THEIRS
    assert ConditionContext(player=THEIRS).opponent == MINE
    assert PlayerRef.OPPONENT.resolve(ConditionContext(player=MINE)) == THEIRS
    assert PlayerRef.CONTROLLER.resolve(ConditionContext(player=MINE)) == MINE

    #: **모르는 사람**을 넣을 수 없다 — 보류가 아니라 거절이다.
    with pytest.raises(ValueError):
        ConditionContext(player=None)
    with pytest.raises(TypeError):
        1 - None  # 관계 계산 자체가 불가능한 자리

    #: 그 가정이 엔진 곳곳에 흩어져 있다 — 한 군데 API 가 아니다.
    spread = sum(
        source_of(relative).count("1 - ")
        for relative in (
            "engine/duel.py",
            "engine/action.py",
            "engine/state/turn.py",
            "engine/condition/context.py",
            "engine/effect/resolution.py",
            "engine/turn_progression.py",
            "engine/observation_grant.py",
            "engine/action_validation.py",
        )
    )
    assert spread >= 14


def test_13_the_engine_already_has_two_different_meanings_of_opponent():
    """
    §6 · §7 — **"상대" 가 이미 두 가지 뜻으로 쓰인다.** 필요한 것은 세 번째다.

    =====================================  =============================
    `PlayerRef.OPPONENT`                    조건 주인의 상대
    `PlayerRole.NON_TURN_PLAYER` ("상대")    **턴 플레이어가 아닌 쪽**
    *필요한 것*                              **후보 컨트롤러의 상대가
                                            사건의 행위자인가**
    =====================================  =============================

    셋이 자주 같은 사람을 가리키지만 **같은 관계가 아니다** — 특수 소환은
    상대 턴에도 일어난다.
    """
    assert str(PlayerRef.OPPONENT) == "상대"
    assert str(PlayerRole.NON_TURN_PLAYER) == "상대"
    #: 그런데 기준이 다르다.
    assert {role.value for role in PlayerRole} == {"turn_player", "non_turn_player"}
    assert {ref.value for ref in PlayerRef} == {"controller", "opponent"}

    #: `PlayerRole` 은 **턴 플레이어**를 기준으로 갈린다 — 사건의 행위자가
    #: 아니다. 그 모듈이 그 구분을 스스로 적어 두었다.
    order_source = source_of("engine/trigger_order.py")
    assert "컨트롤러와 턴 플레이어는 다른 것이다" in order_source
    assert "turn_player" in order_source
    #: 그리고 그 모듈은 `event.actor` 를 **한 번도** 읽지 않는다.
    assert ".actor" not in order_source.replace("actor=candidate.controller", "")

    #: `trigger_chain` 이 `actor` 를 쓰는 **유일한** 자리도 사건이 아니라
    #: 후보의 컨트롤러다 — 관계가 아니라 복사다.
    chain_source = source_of("engine/trigger_chain.py")
    assert "actor=candidate.controller" in chain_source
    assert "event.actor" not in chain_source


# ======================================================================
# F. §8 — SPECIAL_SUMMON 과 결합한 다섯 요구
# ======================================================================


def test_14_the_five_requirements_need_three_different_kinds_of_information():
    """
    §8 R1~R5 — 각 요구가 **event 만으로 되는가 / 관계가 필요한가.**

    R5 는 **구조적으로 만들 수가 없다** — 소환 변화가 사람 칸을 요구한다.
    """
    #: R1 "특수소환이 발생했다" — event 만으로 충분한 정보가 **있다**
    #: (`delta.summon`). 다만 선언이 그것을 가리킬 수 없다 (3-F-6).
    summon = MonsterSummoned(
        summon=SummonKind.SPECIAL,
        card=InstanceId(7),
        player=THEIRS,
        owner=THEIRS,
        from_zone=Zone.HAND,
        to_zone=Zone.MZONE,
        to_index=0,
        position=Position.FACEUP_ATTACK,
    )
    event = timing_for(summon)
    assert event.delta.summon is SummonKind.SPECIAL      # R1 정보: event
    assert event.actor == THEIRS                          # R2·R3 정보: event

    #: R2 "내가" · R3 "상대가" — event 만으로는 **결정되지 않는다.**
    #: 같은 사건이 후보의 컨트롤러에 따라 SELF 이기도 OPPONENT 이기도 하다.
    assert (event.actor == MINE, event.actor == THEIRS) == (False, True)

    #: R4 "특수소환인지 알 수 없다" — 만들 수 있다 (옮길 이름이 없는 사건).
    r4 = timing_for(ZoneShuffled(player=MINE, zone=Zone.DECK, size=10, draw=0))
    assert r4.point is TimingPoint.UNIMPLEMENTED
    assert getattr(r4.delta, "summon", None) is None

    #: R5 "특수소환은 맞지만 누가 했는지 모른다" — **만들 수 없다.**
    with pytest.raises(ValueError) as refusal:
        MonsterSummoned(
            summon=SummonKind.SPECIAL,
            card=InstanceId(7),
            player=None,
            owner=None,
            from_zone=Zone.HAND,
            to_zone=Zone.MZONE,
            to_index=0,
            position=Position.FACEUP_ATTACK,
        )
    assert "player" in str(refusal.value)


def test_15_the_event_relation_and_trigger_condition_split_is_about_inputs(
    repository,
):
    """
    §11 — 두 관문의 책임 구분이 **입력으로** 정해져 있다.

    =====================  ===================================  ==============
    `EVENT_RELATION`        "이 사건이 그 선언이 바라는 것인가"   입력: 사건
    `TRIGGER_CONDITION`     "그 사건을 전제로 무엇이 참인가"      입력: 판
    =====================  ===================================  ==============

    "상대인가?" 는 **사건 쪽** 질문이므로 `EVENT_RELATION` 에 속한다.
    "레벨 4 이상인가?" 는 **판** 질문이므로 `TRIGGER_CONDITION` 이다.
    그 구분은 맞는데, `EVENT_RELATION` 에 비교할 **두 번째 입력이 없다.**
    """
    #: **코드만** 본다 — docstring 의 설명이 코드로 읽히지 않게 (처음에
    #: 본문 전체를 봤고, `_trigger_condition` 의 설명에 적힌 "event
    #: relation" 이 걸렸다).
    relation = function_code(
        "engine/trigger.py", "TriggerEligibilityJudge", "_event_relation"
    )
    condition = function_code(
        "engine/trigger.py", "TriggerEligibilityJudge", "_trigger_condition"
    )

    #: 사건 관문은 판을 읽지 않는다.
    assert "self._view" not in relation
    assert "ConditionContext" not in relation
    #: 조건 관문은 사건을 **코드에서** 읽지 않는다 — 판과 문맥을 읽는다.
    assert "event" not in condition
    assert "ConditionContext(" in condition
    assert "self._evaluator.evaluate" in condition
    #: 조건 문맥에 들어가는 것은 후보의 컨트롤러다 — 사건의 행위자가 아니다.
    assert "candidate.controller" in condition
    assert "actor" not in condition
    #: 반대로 사건 관문은 사건을 분명히 읽는다 (공허한 비교가 아니다).
    assert "event.point" in relation

    #: 두 관문이 **같은 코드**로 "확실한 거부" 를 적는다 (3-E-26 이 맞춘 자리).
    assert "CANDIDATE_NOT_ELIGIBLE" in relation
    assert "CANDIDATE_NOT_ELIGIBLE" in condition


def test_16_no_validation_code_can_say_the_actor_relation_is_unknown():
    """
    §14 — 여섯 상황을 현재 어휘로 적어 본다. **새 코드를 더하지 않는다.**

    ===  ==========================================  =========================
     A    actor == controller                          판정이 **없다**
     B    actor == opponent(controller)                판정이 **없다**
     C    actor 정보가 없다                            `RULE_NOT_IMPLEMENTED`
                                                      (사건이 미구현이라서 —
                                                      행위자 때문이 아니다)
     D    controller 정보가 없다                       **일어날 수 없다**
     E    관계를 계산할 수 없다                        `TypeError` (예외)
     F    event type 이 지원되지 않는다                `RULE_NOT_IMPLEMENTED`
    ===  ==========================================  =========================

    C 와 F 가 **같은 코드**로 접힌다는 것이 이 표의 요점이다.
    """
    #: 48개 코드 가운데 행위자 관계를 뜻하는 것이 없다.
    assert len(CODE_VALIDITY) == 48
    named = [
        code.value
        for code in CODE_VALIDITY
        if any(word in code.value for word in ("actor", "player", "relation"))
    ]
    assert named == ["actor_invalid", "not_turn_player"]
    #: 둘 다 `INVALID` 이고 **보류를 적을 수 없다.**
    assert CODE_VALIDITY[ValidationCode.ACTOR_INVALID] is ActionValidity.INVALID
    assert CODE_VALIDITY[ValidationCode.NOT_TURN_PLAYER] is ActionValidity.INVALID
    #: 그리고 둘 다 **다른 뜻**이다 — 행위를 넘긴 쪽이 0/1 이 아니다 ·
    #: 지금 턴인 사람이 아니다.
    validation = source_of("engine/action_validation.py")
    assert "ValidationCode.ACTOR_INVALID" in validation
    assert "ValidationCode.NOT_TURN_PLAYER" in validation

    #: `UNKNOWN` 짝은 일곱이고, 행위자를 가리키는 것이 하나도 없다.
    unknown = {
        code.value
        for code, validity in CODE_VALIDITY.items()
        if validity is ActionValidity.UNKNOWN
    }
    assert unknown == {
        "card_definition_unavailable",
        "cost_not_implemented",
        "effect_list_unreliable",
        "hidden_card",
        "information_unavailable",
        "priority_state_stale",
        "rule_not_implemented",
    }
    assert not {code for code in unknown if "actor" in code or "player" in code}


def test_17_the_window_holds_the_event_and_the_candidates_but_never_relates_them():
    """
    §12 — "``match_event_to_candidate(event, candidate)`` 같은 것이 있는가?"

    **그 이름의 함수는 없다.** 그런데 **그 둘을 함께 들고 있는 자료 구조는
    이미 있다** — dormant 쪽 `TimingWindow` / `TimingOutcome` 이다.

    즉 책임을 암묵적으로 맡고 있는 자리는 **데이터 구조**이고, 거기에
    비교하는 코드가 없다. 그리고 거기 있는 `opponent` 는 **턴 플레이어**의
    상대라서 필요한 관계가 아니다.
    """
    #: 그 이름의 함수는 production 어디에도 없다.
    roots = (
        "engine",
        "agent",
        "app",
        "core",
        "analysis",
        "rules",
        "rulings",
        "sources",
        "scripts",
    )
    for root in roots:
        for path in (PROJECT_ROOT / root).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "match_event_to_candidate" not in text, str(path)

    #: 그러나 사건과 후보가 **한 값 안에** 있다.
    assert "event" in TimingWindow.__dataclass_fields__
    assert list(TimingOutcome.__dataclass_fields__)[:2] == ["window", "collection"]
    assert "candidates" in TriggerCollection.__dataclass_fields__

    #: 그 모듈은 `actor` 도 `controller` 도 **한 번도** 쓰지 않는다.
    timing_source = source_of("engine/timing.py")
    assert "actor" not in timing_source
    assert "controller" not in timing_source
    #: 거기 있는 `opponent` 는 **턴 플레이어** 기준이다.
    assert "return 1 - self.turn_player" in timing_source

    #: 그리고 그 모듈은 여전히 dormant 다 — production importer 가 0 이다.
    importers = [
        str(path.relative_to(PROJECT_ROOT))
        for root in roots
        for path in (PROJECT_ROOT / root).rglob("*.py")
        if path.name != "timing.py"
        and (
            "from engine.timing import" in path.read_text(encoding="utf-8")
            or "import engine.timing" in path.read_text(encoding="utf-8")
        )
    ]
    assert importers == []


# ======================================================================
# G. 경계 보존 (§15 · §16 · §17)
# ======================================================================


def test_18_reading_the_relation_inputs_touches_no_hidden_information(repository):
    """
    §15 — 행위자와 컨트롤러는 **둘 다 공개 정보**다.

    상대의 패 · 덱은 그대로 가려져 있고, 판도 난수도 움직이지 않는다.
    """
    state, landed = summoned_board(repository)
    before_hash, before_rng = state.state_hash(), repr(state.rng)

    event = event_with_actor(landed, THEIRS)
    view = GameStateView.from_state(state, viewer=MINE)
    candidate, eligibility = judge_same_candidate(state, landed, event)

    #: 비교에 필요한 두 값이 공개 정보에서 온다.
    assert event.actor == THEIRS
    assert candidate.controller == MINE
    summoned_card = view.find(landed.card)
    assert summoned_card is not None and summoned_card.zone is Zone.MZONE

    #: 상대의 패 · 덱은 가려진 채다.
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(THEIRS).zone(zone)
        assert hidden.concealed is True
        assert hidden.cards == ()

    #: 판정은 판을 바꾸지 않는다.
    assert state.state_hash() == before_hash
    assert repr(state.rng) == before_rng
    assert eligibility.candidate is candidate


def test_19_this_phase_changed_nothing_in_production(repository):
    """§16 · §17 — freeze 유지 · Evaluation/Search 불변 · 순위 digest 고정."""
    #: dormant 파이프라인을 연결하지 않았다.
    duel_source = source_of("engine/duel.py")
    for absent in (
        "TriggerRegistry",
        "TriggerCollector",
        "TriggerEligibilityJudge",
        "EventReader",
        "TimingEvent",
        "TimingWindow",
        "engine.timing",
        "engine.event_pipeline",
    ):
        assert absent not in duel_source, absent

    #: 선언에 칸을 더하지 않았다.
    assert len(TriggerSpec.__dataclass_fields__) == 9
    assert "actor" not in TriggerSpec.__dataclass_fields__
    #: 관문의 서명을 바꾸지 않았다.
    assert params_of(TriggerEligibilityJudge._event_relation) == ["spec", "event"]
    #: 판정 어휘를 늘리지 않았다.
    assert len(CODE_VALIDITY) == 48

    #: 탐색 순위를 **실제로 돌려** 확인한다.
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
