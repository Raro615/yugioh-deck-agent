"""
Phase 3-F-6 — **TriggerSpec 선언 스키마 감사.**

이 파일이 답하는 단 하나의 질문
-------------------------------
현재 :class:`~engine.trigger.TriggerSpec` 이 **"어떤 사건을 감지하는
효과인지"를 충분히 선언할 수 있는 자료 구조인가.**

선언 가능성 ≠ 실행 가능성 (§9)
------------------------------
이 파일은 ``TriggerSpec`` 을 production 에 **연결하지 않는다.** 선언 데이터가
충분한지만 본다. 실행 경로(3-F-5 가 측정한 Operation → … → Activation) 는
다시 재지 않는다.

측정으로 확정한 것
------------------
.. note::
   🔴 **Phase 6-E 가 이 감사의 결론 일부를 뒤집었다.** 이 파일이 §4 E 로
   적어 둔 *"SUMMON KIND: NOT REPRESENTABLE"* 이 그것인데, 트리거 컴파일러를
   만들면서 **그 칸이 없으면 거짓 양성이 난다**는 것이 드러났다 — Lua 는
   일반 소환(``EVENT_SUMMON_SUCCESS`` 1,093블록)과 특수 소환
   (``EVENT_SPSUMMON_SUCCESS`` 1,796블록)을 **다른 사건으로** 등록한다.
   그래서 ``summons`` 칸이 생겼고 필드가 **열 개**가 되었다.

   **뒤집히지 않은 것**: ``actor`` 축(§4 F)과 "어느 카드의 사건인가" 는
   여전히 선언할 수 없다. 6-E 는 그 사실을 조건으로 적어서
   (``UnimplementedRule``) 판정이 ``UNKNOWN`` 에서 멈추게 했다. 즉 이
   파일이 지적한 "빠져나갈 길 셋이 전부 막혀 있다" 는 **그대로 유효하고**,
   달라진 것은 소환 종류 하나다.

* ``TriggerSpec`` 은 필드 **열 개**이고 (6-E 전에는 아홉), production 에서
  그 이름을 아는 모듈은 **둘**이다 — ``engine/trigger.py`` 와
  ``engine/trigger_compiler.py`` (``test_11``).
* 사건을 좁히는 축은 **다섯**이다 — ``point`` · ``operations`` ·
  ``from_zones`` · ``to_zones`` · ``summons``. 가운데 셋은
  ``__post_init__`` 이 ``CARD_MOVED`` 에만, 마지막은
  ``MONSTER_SUMMONED`` 에만 허용한다.
* 그래서 **같은 선언 구조가 사건군에 따라 다르게 동작한다** (``test_10``):
  "카드가 패로 들어왔다" 는 좁힐 수 있고 "몬스터가 특수 소환되었다" 는
  좁힐 수 없다.
* 빠져나갈 길 셋이 전부 막혀 있다.

  1. ``condition`` — 평가 문맥(:class:`~engine.condition.ConditionContext`)
     에 **사건이 없다**. 조건 클래스 스무 개 중 사건을 묻는 것이 **0개**다.
  2. 판 상태 — 일반 소환된 몬스터와 특수 소환된 몬스터가 판에서
     **구별되지 않는다** (``test_16``). 그래서 어떤 상태 술어로도 복원할 수
     없다.
  3. 관문 — **사건과 후보를 동시에 보는 관문이 없다** (``test_17``).
     ``_event_relation`` 만 사건을 보고, 그 관문만 후보를 못 본다.

그래서 "상대가" 는 필드 하나를 더해서 해결되지 않는다 — 비교할 두 값이
서로 다른 계층에 있다.

이 파일은 production 을 **한 줄도** 바꾸지 않는다 (``test_19``).
"""

import ast
import hashlib
import inspect
import pathlib

import pytest

from engine.action import PlayerAction
from engine.condition import (
    ConditionContext,
    PlayerRef,
    ZoneCountAtLeast,
)
from engine.condition.model import Condition
from engine.duel import Duel
from engine.effect.delta import CardDrawn, MonsterSummoned, SummonKind, ZoneMoved
from engine.effect.operation import OperationKind
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.card_instance import CardInstance, PreviousState
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
    TriggerSubject,
    TriggerWording,
)
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MINE, THEIRS = 0, 1

LUSTER_DRAGON = 11091375  # 통상 몬스터 · 소환 절차에 쓴다

#: 감사가 직접 건네는 허가. 특수 소환 조건 계층을 대신하지 않는다 (3-F-5 §8).
AUDIT_GRANT = ValidationResult.valid("감사가 관문을 우회해 직접 허가했다")

#: **카드 이름도 패스코드도 쓰지 않는다** (§6 · §7 · §19). 세 패트랩의
#: 요구를 **구조로만** 적는다 — 어떤 정보가 필요한가, 그것이 지금 어디에
#: 있는가. 카드의 실제 ``code`` 증거는 3-F-5 §9 에 이미 측정되어 있다.
#:
#: 축 이름은 §2 의 여덟 개념에서 가져온다.
SPEC_OPPONENT_SPECIAL_SUMMON = (
    #: (축, 그 축을 들고 있는 자리, TriggerSpec 이 선언할 수 있는가)
    ("EVENT", "TimingEvent.point", True),
    ("EVENT TYPE", "TimingPoint.MONSTER_SUMMONED", True),
    ("SUMMON KIND", "event.delta.summon", False),
    ("ACTOR", "event.actor", False),
    ("SELF vs OPPONENT", "event.actor ↔ candidate.controller", False),
    ("TRIGGER CONDITION", "TriggerSpec.condition (상태만)", True),
)


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


# ======================================================================
# 사건 네 가지 — 두 축(종류 · 행위자)을 교차시킨다
# ======================================================================


def summoned(kind: SummonKind, player: int) -> MonsterSummoned:
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


def four_summon_events() -> "dict[str, TimingEvent]":
    """내/상대 × 일반/특수. **네 사건이 서로 다른 사실**이다."""
    return {
        "mine_normal": TimingEvent.from_delta(summoned(SummonKind.NORMAL, MINE)),
        "mine_special": TimingEvent.from_delta(summoned(SummonKind.SPECIAL, MINE)),
        "theirs_normal": TimingEvent.from_delta(summoned(SummonKind.NORMAL, THEIRS)),
        "theirs_special": TimingEvent.from_delta(summoned(SummonKind.SPECIAL, THEIRS)),
    }


def live_duel(repository, *, seed: int = 3, deck_size: int = 20) -> Duel:
    deck = [LUSTER_DRAGON] * deck_size
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
    while duel.advance() is not None:
        pass
    return duel


def execute_summon(duel: Duel, builder, actor: int):
    state = duel.state.clone()
    source = list(state.player(actor).hand)[0].instance_id
    action = builder(actor=actor, source=source)
    return state, duel_executor().execute(state, action, authorization=AUDIT_GRANT)


# ======================================================================
# A. §3 — 선언 스키마 그 자체
# ======================================================================


def test_01_the_declaration_has_exactly_ten_fields_and_five_event_axes():
    """
    §3 — 필드 목록과 타입을 **코드에서** 센다.

    🔴 아홉 → **열** (Phase 6-E 의 ``summons``). 사건을 좁히는 축은 넷 →
    **다섯**이고, 나머지 다섯은 사건과 상관이 없다 — 어느 효과인가
    (`effect_ref`) · 강제/임의(`requirement`) · 어법(`wording`) · 어느
    자리에서 발동하는가(`activates_from`) · 그때 무엇이 참이어야 하는가
    (`condition`).
    """
    fields = TriggerSpec.__dataclass_fields__
    assert list(fields) == [
        "effect_ref",
        "point",
        "requirement",
        "wording",
        "operations",
        "from_zones",
        "to_zones",
        "summons",
        "subject",
        "activates_from",
        "condition",
    ]

    #: **사건을 좁히는 축** — `matches` 가 실제로 비교하는 것만 센다.
    #:
    #: 🔴 **``subject`` 는 여기 들어가지 않는다** (Phase 6-F). 사건의 축이
    #: 맞는데도 ``matches`` 가 비교할 수 없다 — ``matches(event)`` 는 사건
    #: 하나만 받고 **비교 상대(후보의 인스턴스) 가 서명에 없기** 때문이다.
    #: 그래서 6-F 는 ``matches`` 를 넓히는 대신
    #: :func:`~engine.trigger.subject_relation` 을 따로 두고 **두 계층이 같은
    #: 함수를 부르게** 했다. 이 테스트가 세어 온 "다섯" 은 그대로다.
    body = _function_body("engine/trigger.py", "TriggerSpec", "matches")
    compared = {name for name in fields if f"self.{name}" in body}
    assert compared == {
        "point",
        "operations",
        "from_zones",
        "to_zones",
        "summons",
    }

    #: 나머지 **여섯**은 `matches` 가 보지 않는다. 그중 다섯은 사건 선별의
    #: 축이 아니고, ``subject`` 는 **축이지만 ``matches`` 로는 비교할 수
    #: 없는 것**이다 (위 주석).
    assert compared.isdisjoint(
        {
            "effect_ref",
            "requirement",
            "wording",
            "subject",
            "activates_from",
            "condition",
        }
    )
    assert len(fields) - len(compared) == 6

    #: 기본값이 있는 필드는 `point` 를 빼고 전부 "선언하지 않았다" 를 표현한다.
    spec = TriggerSpec(EffectRef(LUSTER_DRAGON, 0), TimingPoint.MONSTER_SUMMONED)
    assert spec.requirement is TriggerRequirement.UNKNOWN
    assert spec.wording is TriggerWording.UNKNOWN
    assert (spec.operations, spec.from_zones, spec.to_zones) == (None, None, None)
    assert spec.summons is None
    #: 🔴 ``subject`` 도 ``None`` 으로 "선언하지 않았다" 를 표현한다 — 그리고
    #: 그 ``None`` 은 **"어느 카드든" 이 아니다** (6-F 의 핵심 구분).
    assert spec.subject is None
    assert spec.activates_from is None and spec.condition is None


def _function_body(relative: str, class_name: str, method: str) -> str:
    """그 메서드의 **본문만** 떼어낸다 — 문자열 창으로 보지 않는다."""
    text = source_of(relative)
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method:
                    return ast.get_source_segment(text, child)
    raise AssertionError(f"{class_name}.{method} 를 찾지 못했습니다")


def test_02_the_only_event_axis_that_reaches_a_summon_is_the_point():
    """
    §4 A · B — **"어떤 Event 인가" 는 선언할 수 있다.** 그것이 `point` 다.

    그런데 소환이 든 `TimingPoint` 는 **하나**뿐이므로, 그 축으로는
    "소환되었다" 까지만 말할 수 있고 "**어떤** 소환" 은 말할 수 없다.
    """
    points = [point for point in TimingPoint if "summon" in point.value]
    assert [point.value for point in points] == ["monster_summoned"]
    assert len(list(TimingPoint)) == 8

    #: `point` 는 실제로 사건군을 가른다 — 공허한 축이 아니다.
    spec = TriggerSpec(EffectRef(LUSTER_DRAGON, 0), TimingPoint.MONSTER_SUMMONED)
    drawn = TimingEvent.from_delta(CardDrawn(player=MINE, card=InstanceId(3)))
    assert not spec.matches(drawn)
    assert spec.matches(four_summon_events()["mine_special"])


# ======================================================================
# B. §4 — 일곱 요구의 표현 가능성
# ======================================================================


def test_03_summon_kind_became_declarable_in_its_own_axis():
    """
    §4 E — **"SUMMON KIND: NOT REPRESENTABLE" 이 Phase 6-E 에서 뒤집혔다.**

    이 감사가 쓰여진 시점에 그 진술은 맞았다. 그리고 그것이 **단순한 빈
    칸이 아니라 결함**이라는 것이 트리거 컴파일러를 만들면서 드러났다 —
    Lua 는 일반 소환과 특수 소환을 다른 사건으로 등록하는데 엔진의
    ``MONSTER_SUMMONED`` 는 둘을 합친 하나이므로, 구분을 적을 수 없으면
    "일반 소환했을 때" 카드가 **특수 소환에도 후보가 된다.**

    셋 중 ①과 ③이 뒤집히고 ②는 그대로다.
    """
    #: ① 🔴 칸이 생겼다 — 그리고 **기존 셋과 다른 이름**이다.
    assert "summons" in TriggerSpec.__dataclass_fields__
    assert [
        name for name in TriggerSpec.__dataclass_fields__ if "summon" in name
    ] == ["summons"]

    #: ② `MONSTER_SUMMONED` 에는 기존 필터 셋이 전부 금지된다.
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

    #: ③ 🔴 사건에서 소환 종류를 꺼내는 접근자도 생겼다. ``operation`` 은
    #:    여전히 ``None`` 이다 — 소환은 효과의 어휘를 쓰지 않으므로 창구가
    #:    **그 셋과 다른 이름**으로 따로 났다.
    event = four_summon_events()["mine_special"]
    assert event.summon is SummonKind.SPECIAL
    assert event.operation is None
    assert event.delta.summon is SummonKind.SPECIAL

    #: 그래서 이제 선언이 둘을 **가른다.**
    special_only = TriggerSpec(
        EffectRef(LUSTER_DRAGON, 0),
        TimingPoint.MONSTER_SUMMONED,
        summons=frozenset({SummonKind.SPECIAL}),
    )
    assert special_only.matches(event) is True
    assert special_only.matches(four_summon_events()["mine_normal"]) is False


def test_04_the_actor_is_on_the_event_but_not_in_the_declaration():
    """
    §4 F · §5 — **ACTOR: NOT REPRESENTABLE.**

    사건은 행위자를 **들고 있다.** 선언에는 그것을 적을 칸이 없고,
    `matches` 는 그 값을 **보지 않는다.**
    """
    events = four_summon_events()
    assert events["mine_special"].actor == MINE
    assert events["theirs_special"].actor == THEIRS

    assert "actor" not in TriggerSpec.__dataclass_fields__
    assert "player" not in TriggerSpec.__dataclass_fields__

    body = _function_body("engine/trigger.py", "TriggerSpec", "matches")
    assert "actor" not in body
    assert "player" not in body

    #: 그래서 하나의 선언이 **내 것과 상대 것을 같게** 본다.
    spec = TriggerSpec(EffectRef(LUSTER_DRAGON, 0), TimingPoint.MONSTER_SUMMONED)
    assert spec.matches(events["mine_special"])
    assert spec.matches(events["theirs_special"])


def test_05_self_versus_opponent_needs_two_layers_at_once():
    """
    §4 C · D — **SELF vs OPPONENT: NOT REPRESENTABLE**, 그리고 **그 이유가
    필드 부재가 아니다.**

    "상대가" 는 `event.actor` 와 **반응하는 효과의 컨트롤러**를 비교하는
    일이다. 선언이 들고 있는 것은 사건 쪽 값뿐이고, 컨트롤러는 후보가
    생긴 뒤에야 존재한다.

    관계 어휘는 **이미 있다** — `PlayerRef.CONTROLLER` / `OPPONENT` 가
    카드 텍스트의 "자신" / "상대" 에 대응한다. 그런데 그것은 **조건 계층**의
    어휘이고, 조건 계층은 사건을 보지 못한다 (`test_07`).
    """
    assert {ref.value for ref in PlayerRef} == {"controller", "opponent"}
    assert str(PlayerRef.OPPONENT) == "상대"

    #: `PlayerRef` 는 문맥을 받아 **번호로 풀린다** — 절대 번호가 아니다.
    assert PlayerRef.OPPONENT.resolve(ConditionContext(player=MINE)) == THEIRS
    assert PlayerRef.OPPONENT.resolve(ConditionContext(player=THEIRS)) == MINE

    #: 그런데 선언이 거르는 자리들은 **후보를 모른다.**
    assert [
        name
        for name in inspect.signature(TriggerSpec.matches).parameters
        if name != "self"
    ] == ["event"]
    assert [
        name
        for name in inspect.signature(TriggerRegistry.watching).parameters
        if name != "self"
    ] == ["event"]
    assert [
        name
        for name in inspect.signature(TriggerCollector.collect).parameters
        if name != "self"
    ] == ["event"]

    #: `watching` 이 먼저 돌고 그 뒤에 후보가 생긴다 — `collect` 본문이
    #: 그 순서를 말한다.
    body = _function_body("engine/trigger.py", "TriggerCollector", "collect")
    assert body.index("watching(event)") < body.index("_candidates_for")


def test_06_one_declaration_cannot_separate_the_four_cases():
    """
    §4 A~D 를 **한 번에** 확인한다. 네 사건은 서로 다른 사실인데,
    선언 하나가 넷을 전부 잡는다.
    """
    events = four_summon_events()
    #: 네 사건이 실제로 서로 다르다.
    assert len({event.delta.canonical_state() for event in events.values()}) == 4
    #: 그런데 `point` 는 넷 다 같고, 선언이 볼 수 있는 축은 그것뿐이다.
    assert {event.point for event in events.values()} == {
        TimingPoint.MONSTER_SUMMONED
    }

    spec = TriggerSpec(EffectRef(LUSTER_DRAGON, 0), TimingPoint.MONSTER_SUMMONED)
    caught = {label for label, event in events.items() if spec.matches(event)}
    assert caught == set(events)

    registry = TriggerRegistry((spec,))
    assert {len(registry.watching(event)) for event in events.values()} == {1}


def test_07_the_condition_field_works_but_cannot_see_the_event(repository):
    """
    §4 G — **EVENT + CONDITION: 절반만 된다.**

    조건 절반은 **REPRESENTABLE WITH EXISTING FIELDS** 다 — 실제로 관문이
    뒤집힌다. 사건 절반은 **NOT REPRESENTABLE** 이고, 같은 판정에서
    `EVENT_RELATION` 이 조건과 **무관하게** 그대로다.

    그리고 조건 계층은 **구조적으로** 사건을 볼 수 없다.

    .. note::
       🔴 **Phase 6-F 가 "사건 절반" 을 표현 가능하게 만들었다 — 그런데 이
       감사의 구조적 발견은 그대로다.**

       이 감사는 "조건이 사건을 볼 구멍이 없다" 를 찾아냈고, 그래서 사건
       절반이 ``NOT REPRESENTABLE`` 이라고 적었다. 6-F 는 그 구멍을 뚫는
       대신 (``ConditionContext`` 는 **한 칸도** 바뀌지 않았다 — 아래에서
       그대로 단정한다) **사건 관계 쪽에 축을 두었다**
       (``TriggerSpec.subject``).

       그래서 아래의 단정 하나가 움직인다: 선언이 주체를 적지 않으면
       ``EVENT_RELATION`` 이 이제 ``UNKNOWN`` 이다. **조건을 바꿔도 사건
       판정이 그대로라는 이 테스트의 요지는 그대로이고** (두 판정이 여전히
       서로 같다), 값만 "보지 않은 통과" 에서 **"적지 않아서 모름"** 으로
       정확해졌다.
    """
    duel = live_duel(repository)
    state, execution = execute_summon(duel, PlayerAction.special_summon, MINE)
    view = GameStateView.from_state(state, viewer=MINE)
    event = TimingEvent.from_delta(execution.deltas[0])

    verdicts = {}
    for label, count in (("true", 1), ("false", 99)):
        spec = TriggerSpec(
            EffectRef(LUSTER_DRAGON, 0),
            TimingPoint.MONSTER_SUMMONED,
            requirement=TriggerRequirement.OPTIONAL,
            activates_from=frozenset({Zone.MZONE}),
            condition=ZoneCountAtLeast(
                who=PlayerRef.CONTROLLER, zone=Zone.MZONE, count=count
            ),
        )
        collection = TriggerCollector(view, TriggerRegistry((spec,))).collect(event)
        assert collection.candidates, label
        eligibility = TriggerEligibilityJudge(view).judge(
            collection.candidates[0], spec, event
        )
        verdicts[label] = {
            gate.gate: (gate.validity, gate.code) for gate in eligibility.gates
        }

    #: 조건 절반은 **실제로 작동한다.**
    assert verdicts["true"][EligibilityGate.TRIGGER_CONDITION] == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )
    assert verdicts["false"][EligibilityGate.TRIGGER_CONDITION] == (
        ActionValidity.INVALID,
        ValidationCode.CANDIDATE_NOT_ELIGIBLE,
    )
    #: 사건 절반은 **둘 다 똑같다** — 조건을 바꿔도 사건 판정은 그대로다.
    #: 🔴 값은 6-F 에서 "보지 않은 통과" → **"적지 않아서 모름"** 으로
    #: 바뀌었다 (위 note). 두 판정이 서로 같다는 이 테스트의 요지는 그대로다.
    assert (
        verdicts["true"][EligibilityGate.EVENT_RELATION]
        == verdicts["false"][EligibilityGate.EVENT_RELATION]
        == (ActionValidity.UNKNOWN, ValidationCode.RULE_NOT_IMPLEMENTED)
    )
    #: 그리고 주체를 **적으면** 그 자리가 통과로 바뀐다 — 표현 가능해졌다는
    #: 뜻이고, 이것이 6-F 가 더한 것이다.
    scoped = TriggerSpec(
        EffectRef(LUSTER_DRAGON, 0),
        TimingPoint.MONSTER_SUMMONED,
        requirement=TriggerRequirement.OPTIONAL,
        activates_from=frozenset({Zone.MZONE}),
        subject=TriggerSubject.ANY,
    )
    scoped_collection = TriggerCollector(view, TriggerRegistry((scoped,))).collect(event)
    scoped_eligibility = TriggerEligibilityJudge(view).judge(
        scoped_collection.candidates[0], scoped, event
    )
    scoped_gate = scoped_eligibility.gate(EligibilityGate.EVENT_RELATION)
    assert (scoped_gate.validity, scoped_gate.code) == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )

    #: 그리고 조건이 사건을 볼 **구멍이 없다.**
    assert list(ConditionContext.__dataclass_fields__) == [
        "player",
        "source",
        "effect_ref",
        "targets",
    ]
    assert [
        name
        for name in inspect.signature(Condition.evaluate).parameters
        if name != "self"
    ] == ["view", "context"]
    #: 조건 클래스 가운데 **사건을 묻는 것이 하나도 없다.**
    subclasses: list[type] = []

    def walk(klass: type) -> None:
        for child in klass.__subclasses__():
            subclasses.append(child)
            walk(child)

    walk(Condition)
    names = {klass.__name__ for klass in subclasses}
    assert names, "조건 클래스를 하나도 찾지 못했다"
    #: 공허하지 않음을 **실제로 있는 이름**으로 고정한다.
    assert {"ZoneCountAtLeast", "ControllerIs", "IsTurnPlayer", "PhaseIs"} <= names
    #: 사건 · 시점 · 행위자를 묻는 이름은 없다.
    assert not {
        name
        for name in names
        if any(word in name.lower() for word in ("event", "timing", "actor"))
    }
    #: 소환이 든 이름은 **정확히 셋**이고, 셋 다 "지금 소환을 할 수
    #: 있는가" 를 묻는 **상태** 술어다 — "소환이 일어났는가" 가 아니다.
    #:
    #: 🔴 둘 → **셋** (Phase 6-AD, ``SpecialSummonPermitted``). 그것도 판만
    #: 본다 — 양쪽 필드의 앞면 카드를 훑어 특수 소환을 금지하는 것이 있는지
    #: 보고, 사건도 시점도 읽지 않는다 (아래 루프가 그것을 센다).
    assert {name for name in names if "summon" in name.lower()} == {
        "_NormalSummonRightAvailable",
        "_NormalSummonProcedure",
        "SpecialSummonPermitted",
    }
    #: 🔴 새 술어도 **사건 어휘를 쓰지 않는다** — 다른 모듈에 있으므로 아래
    #: 루프와 따로 센다.
    permitted_body = _function_body(
        "engine/condition/model.py", "SpecialSummonPermitted", "evaluate"
    )
    assert "view" in permitted_body
    for absent in ("SummonKind", "MonsterSummoned", "TimingEvent", "delta"):
        assert absent not in permitted_body, absent
    validation = source_of("engine/action_validation.py")
    for predicate in ("_NormalSummonRightAvailable", "_NormalSummonProcedure"):
        body = _function_body("engine/action_validation.py", predicate, "evaluate")
        assert "view" in body
        for absent in ("SummonKind", "MonsterSummoned", "TimingEvent", "delta"):
            assert absent not in body, (predicate, absent)
    assert "_NormalSummonRightAvailable" in validation

    #: 🟡 판이 기억하는 소환 사실은 **하나**뿐이고 — 일반 소환권 사용 횟수 —
    #: 그것이 특수 소환에는 **쓸 수 없는** 하나다. 특수 소환은 그 권리를
    #: 쓰지 않으므로 아무것도 늘리지 않는다.
    from engine.state.rule_usage import RuleActionKind

    assert {kind.value for kind in RuleActionKind} == {
        "normal_summon",
        "attack",
        "set_spell_trap",
    }
    assert "special_summon" not in {kind.value for kind in RuleActionKind}
    assert [name for name in dir(view) if "summon" in name.lower()] == [
        "normal_summons_used"
    ]


# ======================================================================
# C. §6 · §7 · §8 — 세 요구를 specification 으로만
# ======================================================================


def test_08_the_opponent_special_summon_requirement_splits_into_six_axes():
    """
    §6 — "상대가 SPECIAL_SUMMON 을 성공적으로 수행한 사건에 반응" 을
    **구조로** 분해한다. 카드 이름도 패스코드도 쓰지 않는다.

    여섯 축 가운데 **셋이 선언 불가**이고, 그 셋이 정확히 이 요구를
    다른 요구와 구별하는 축이다.
    """
    events = four_summon_events()
    target = events["theirs_special"]

    #: 축마다 "그 값이 어디에 있는가" 를 실제로 확인한다.
    assert target.point is TimingPoint.MONSTER_SUMMONED       # EVENT · EVENT TYPE
    assert target.delta.summon is SummonKind.SPECIAL          # SUMMON KIND
    assert target.actor == THEIRS                             # ACTOR
    #: SELF vs OPPONENT 는 사건 하나로는 결정되지 않는다 — 비교 상대가 필요하다.
    assert events["mine_special"].delta.summon is target.delta.summon
    assert events["mine_special"].actor != target.actor

    declarable = {axis: ok for axis, _, ok in SPEC_OPPONENT_SPECIAL_SUMMON}
    assert declarable == {
        "EVENT": True,
        "EVENT TYPE": True,
        "SUMMON KIND": False,
        "ACTOR": False,
        "SELF vs OPPONENT": False,
        "TRIGGER CONDITION": True,
    }
    #: **성공한 특수 소환만 사건이 된다** — "성공적으로" 는 이미 보장된다
    #: (실패하면 delta 가 없고, 사건도 없다 — 3-F-5 §8).
    assert sum(1 for ok in declarable.values() if not ok) == 3

    #: 그리고 이 세 축이 빠진 결과, 선언은 네 경우를 가르지 못한다.
    spec = TriggerSpec(EffectRef(LUSTER_DRAGON, 0), TimingPoint.MONSTER_SUMMONED)
    assert all(spec.matches(event) for event in events.values())


def test_09_the_second_requirement_needs_the_same_axes_plus_more():
    """
    §7 — "특정 종류의 특수 소환 발생에 반응" 은 위와 **같은 세 축**을
    요구하고, 거기에 하나를 더 요구한다 — **어떤 특수 소환법인가.**

    그 축은 `SummonKind` 에 **값이 거의 없다**: `SPECIAL` 하나로
    융합 · 싱크로 · 엑시즈 · 의식 · 펜듈럼을 전부 덮는다
    (STRUCTURAL-62 가 그 결정을 적어 두었다).

    즉 두 요구는 "같은 정보가 필요한가?" 에 대해 **아니다** — 두 번째가
    한 축 더 깊다. 그러나 그 축은 **선언의 문제가 아니라 어휘의 문제**다.

    🔴 **Phase 6-AC 가 그 축에 값 하나를 더했다** — ``LINK``. 지어내서 더한
    것이 아니라 **그 절차를 실제로 구현해서** 더했다 (소재 조건 판정 · 소재
    이동 · 엑스트라 몬스터 존 배치). 그래서 아래 목록에서 ``link`` 만
    빠지고 나머지 다섯은 **여전히 없다** — 구현하지 않은 소환법의 이름을
    어휘에 적지 않는다는 것이 이 시험이 지키는 사실이고, 그것은 그대로다.
    """
    assert {kind.value for kind in SummonKind} == {"normal", "special", "link"}
    #: 구현하지 않은 소환법 이름이 하나도 없다 — 지어내지 않았기 때문이다.
    for method in ("fusion", "synchro", "xyz", "ritual", "pendulum"):
        assert method not in {kind.value for kind in SummonKind}

    #: 그래서 첫 요구가 막히는 세 축은 그대로 막히고,
    declarable = {axis: ok for axis, _, ok in SPEC_OPPONENT_SPECIAL_SUMMON}
    assert not declarable["SUMMON KIND"]
    #: 두 번째 요구는 그 위에 **값이 없는 축**을 하나 더 쌓는다.
    assert SummonKind.SPECIAL.value == "special"


def test_10_the_card_moved_family_can_be_narrowed_and_the_summon_family_cannot():
    """
    §8 — **드롤 쪽 요구는 다르다.** "상대가 카드를 손에 넣었다" 는 사건군이
    `CARD_MOVED` 이고, 거기서는 기존 필터가 **허용되고 실제로 걸러낸다.**

    같은 선언 구조가 사건군에 따라 다르게 동작한다는 것이 이 Phase 의
    가장 짧은 요약이다. 드롤 트리거를 **설계하지 않는다** — 차이만 적는다.
    """
    to_hand = TriggerSpec(
        EffectRef(LUSTER_DRAGON, 0),
        TimingPoint.CARD_MOVED,
        operations=frozenset({OperationKind.RETURN_TO_HAND}),
        to_zones=frozenset({Zone.HAND}),
    )
    returned = TimingEvent.from_delta(
        ZoneMoved(
            movement=OperationKind.RETURN_TO_HAND,
            card=InstanceId(9),
            source_player=THEIRS,
            source_zone=Zone.MZONE,
            destination_player=THEIRS,
            destination_zone=Zone.HAND,
        )
    )
    buried = TimingEvent.from_delta(
        ZoneMoved(
            movement=OperationKind.SEND_TO_GRAVE,
            card=InstanceId(9),
            source_player=THEIRS,
            source_zone=Zone.MZONE,
            destination_player=THEIRS,
            destination_zone=Zone.GRAVE,
        )
    )
    #: 좁혀진다 — 그리고 **실제로 거른다.**
    assert to_hand.matches(returned)
    assert not to_hand.matches(buried)
    #: 드로우는 별개의 시점이므로 이 선언에 걸리지 않는다.
    assert not to_hand.matches(
        TimingEvent.from_delta(CardDrawn(player=THEIRS, card=InstanceId(3)))
    )

    #: 같은 세 필터가 소환 사건군에서는 **선언 자체가 거절된다.**
    with pytest.raises(TriggerError):
        TriggerSpec(
            EffectRef(LUSTER_DRAGON, 0),
            TimingPoint.MONSTER_SUMMONED,
            operations=frozenset({OperationKind.SPECIAL_SUMMON}),
        )

    #: 다만 **행위자 축은 양쪽 다 선언 불가**다 — 드롤 쪽도 "상대가" 를
    #: 적을 수 없다. 사건군 차이는 종류 축에만 있다.
    assert "actor" not in TriggerSpec.__dataclass_fields__
    assert to_hand.matches(
        TimingEvent.from_delta(
            ZoneMoved(
                movement=OperationKind.RETURN_TO_HAND,
                card=InstanceId(9),
                source_player=MINE,
                source_zone=Zone.MZONE,
                destination_player=MINE,
                destination_zone=Zone.HAND,
            )
        )
    )


# ======================================================================
# D. §13 · §11 — 경계와 정규 표현
# ======================================================================


def test_11_the_declaration_type_has_exactly_one_production_module():
    """
    §13 — **"잘 설계되어 있다" 와 "duel 에서 작동한다" 를 가른다.**

    `TriggerSpec` 이라는 이름을 아는 production 모듈은 **하나**뿐이다 —
    자기 파일. dormant 다섯 모듈 중 넷조차 이 타입을 모른다.
    """
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
    mentioning = sorted(
        str(path.relative_to(PROJECT_ROOT))
        for root in roots
        for path in (PROJECT_ROOT / root).rglob("*.py")
        if "TriggerSpec" in path.read_text(encoding="utf-8")
    )
    #: 🔴 하나 → **둘** (Phase 6-E). ``trigger_compiler.py`` 가 카드
    #: 데이터에서 선언을 만든다 — STRUCTURAL-7 이 그것을 기다리고 있었다.
    #: **아래 두 단정은 그대로다** — live 경로는 여전히 아무것도 모른다.
    assert mentioning == ["engine/trigger.py", "engine/trigger_compiler.py"]

    #: live 경로는 선언 · 등록소 · 수집기를 **하나도** 모른다.
    duel_source = source_of("engine/duel.py")
    for absent in (
        "TriggerSpec",
        "TriggerRegistry",
        "TriggerCollector",
        "TriggerEligibilityJudge",
        "TriggerCandidate",
    ):
        assert absent not in duel_source, absent

    #: 🔴 **Phase 6-Z 가 칸 하나를 만들었다** — ``triggers``. 그러나 그 칸의
    #: 타입은 ``object`` 이고, 위의 단정이 그것을 지킨다: ``Duel`` 은 선언 ·
    #: 등록소 · 수집기 · 후보의 **이름을 하나도 모른다.** 받는 것은
    #: ``offers(duel, seat)`` 를 가진 아무 물건이다 (ADR-007).
    #:
    #: 그래서 이 시험의 §13 — "잘 설계되어 있다" 와 "duel 에서 작동한다" 를
    #: 가른다 — 는 **방향이 바뀐 채로 그대로 참이다**: 지금은 duel 에서
    #: 작동하고, 그 작동이 선언 타입을 live 경로로 들여오지 않았다.
    fields = Duel.__dataclass_fields__
    assert [name for name in fields if "trigger" in name] == ["triggers"], list(fields)
    assert fields["triggers"].type in ("object | None", '"object | None"'), fields[
        "triggers"
    ].type
    assert not any("registry" in name for name in Duel.__dataclass_fields__)


def test_12_the_declaration_has_a_canonical_state_over_all_ten_fields():
    """
    §11 — 정규 표현은 **열** 필드를 다 담고, 서로 다른 선언을 가른다.

    *"새 필드가 들어오면 이 길이와 내용이 바뀐다 — 그것이 직렬화 · replay
    에 미치는 영향이다."* 🔴 Phase 6-E 가 그 필드를 더했고, 이 핀이 정확히
    그것을 잡았다. 길이 9 → **10** 이고, 소환 종류가 다른 두 선언이 서로
    다른 정규 표현을 갖는다.
    """
    bare = TriggerSpec(EffectRef(LUSTER_DRAGON, 0), TimingPoint.MONSTER_SUMMONED)
    zoned = TriggerSpec(
        EffectRef(LUSTER_DRAGON, 0),
        TimingPoint.MONSTER_SUMMONED,
        activates_from=frozenset({Zone.MZONE}),
    )
    #: 6-E 10 → **6-F 11** (``subject``).
    assert len(bare.canonical_state()) == 11
    assert bare.canonical_state() != zoned.canonical_state()

    #: 🔴 소환 종류가 정규 표현에 **실제로 실린다** — 안 실리면 일반 소환
    #: 선언과 특수 소환 선언이 같은 것으로 직렬화된다.
    normal = TriggerSpec(
        EffectRef(LUSTER_DRAGON, 0),
        TimingPoint.MONSTER_SUMMONED,
        summons=frozenset({SummonKind.NORMAL}),
    )
    special = TriggerSpec(
        EffectRef(LUSTER_DRAGON, 0),
        TimingPoint.MONSTER_SUMMONED,
        summons=frozenset({SummonKind.SPECIAL}),
    )
    assert normal.canonical_state() != special.canonical_state()
    assert bare.canonical_state() not in (
        normal.canonical_state(),
        special.canonical_state(),
    )

    #: 정규 표현은 정수 · 문자열 · 튜플 · `None` 만으로 되어 있다
    #: (객체 주소가 들어가면 replay 가 깨진다).
    def leaves(value):
        if isinstance(value, tuple):
            for item in value:
                yield from leaves(item)
        else:
            yield value

    assert all(
        isinstance(leaf, (int, str, type(None)))
        for leaf in leaves(zoned.canonical_state())
    )

    #: `to_dict` 는 **선언하지 않은 축을 적지 않는다** — `None` 을 빈 값으로
    #: 바꿔 적으면 "전부 허용" 과 구별되지 않는다.
    assert set(bare.to_dict()) == {"effect_ref", "point", "requirement", "wording"}
    assert "activates_from" in zoned.to_dict()


def test_13_the_registry_touches_neither_state_hash_nor_rng(repository):
    """§11 · §16 13·14 — 선언은 판의 모양이 아니다."""
    duel = live_duel(repository)
    before_hash = duel.state.state_hash()
    before_rng = repr(duel.state.rng)

    registry = TriggerRegistry(
        (
            TriggerSpec(EffectRef(LUSTER_DRAGON, 0), TimingPoint.MONSTER_SUMMONED),
            TriggerSpec(EffectRef(LUSTER_DRAGON, 1), TimingPoint.CARD_DRAWN),
        )
    )
    assert len(registry) == 2

    #: 사건을 읽고 후보를 모으는 일까지 해도 판은 그대로다.
    state, execution = execute_summon(duel, PlayerAction.special_summon, MINE)
    view = GameStateView.from_state(state, viewer=MINE)
    event = TimingEvent.from_delta(execution.deltas[0])
    collection = TriggerCollector(view, registry).collect(event)
    assert collection.event is event

    assert duel.state.state_hash() == before_hash
    assert repr(duel.state.rng) == before_rng


# ======================================================================
# E. 왜 필드 추가로 끝나지 않는가 (§5 · §10 · §12)
# ======================================================================


def test_14_four_different_refusals_stay_four_different_things():
    """
    §12 — 네 가지를 같은 `UNKNOWN` 으로 뭉개지 않는다.

    ======================================  ==================================
    선언에 행위자 칸이 없다                   **이 Phase 의 발견** — 코드가
                                              아니라 스키마의 사실
    지금 행위자를 판단할 수 없다              사건에는 `actor` 가 **있다**
    지금 조건이 거짓이다                      `INVALID/CANDIDATE_NOT_ELIGIBLE`
    규칙이 미구현이다                         `UNKNOWN/RULE_NOT_IMPLEMENTED`
    ======================================  ==================================
    """
    #: ① 스키마의 사실 — 어떤 `ValidationCode` 로도 표현되지 않는다.
    assert "actor" not in TriggerSpec.__dataclass_fields__

    #: ② 사건은 행위자를 **안다** — "판단할 수 없다" 가 아니다.
    events = four_summon_events()
    assert events["theirs_special"].actor == THEIRS
    assert events["theirs_special"].actor is not None

    #: ③ · ④ 두 코드는 서로 다른 뜻이고 둘 다 실재한다.
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert (
        ValidationCode.INFORMATION_UNAVAILABLE
        is not ValidationCode.RULE_NOT_IMPLEMENTED
    )

    #: 그리고 선언이 행위자를 못 적는다는 사실이 `UNKNOWN` 으로 **새지
    #: 않는다** — `EVENT_RELATION` 은 `VALID/OK` 를 낸다. 틀린 승인이지
    #: 정직한 보류가 아니다 (3-F-5 §10 이 측정했고, 여기서는 그것이
    #: **스키마 때문**임을 말한다).
    spec = TriggerSpec(EffectRef(LUSTER_DRAGON, 0), TimingPoint.MONSTER_SUMMONED)
    assert spec.matches(events["theirs_special"])
    assert spec.matches(events["mine_normal"])


def test_15_no_gate_sees_the_event_and_the_candidate_together():
    """
    **이 Phase 의 중심 발견.** "상대가" 를 판정할 자리가 관문에 없다.

    다섯 관문 중 사건을 받는 것은 `_event_relation` **하나**이고, 그 관문은
    후보를 받지 **않는다.** 후보를 받는 세 관문은 사건을 받지 않는다.

    `event.actor` 와 `candidate.controller` 를 비교해야 하는데, **두 값이
    같은 함수 안에 있는 관문이 하나도 없다.** 그래서 이것은 필드 추가가
    아니라 계층 경계의 문제다.
    """
    gates = {}
    for name in (
        "_event_relation",
        "_activation_zone",
        "_trigger_condition",
        "_execution_authority",
        "_cost_feasibility",
    ):
        params = [
            parameter
            for parameter in inspect.signature(
                getattr(TriggerEligibilityJudge, name)
            ).parameters
            if parameter != "self"
        ]
        gates[name] = ("event" in params, "candidate" in params)

    assert gates == {
        "_event_relation": (True, False),
        "_activation_zone": (False, True),
        "_trigger_condition": (False, True),
        "_execution_authority": (False, False),
        "_cost_feasibility": (False, True),
    }
    #: 사건을 보는 관문은 하나뿐이고, 둘 다 보는 관문은 **없다.**
    assert sum(1 for sees_event, _ in gates.values() if sees_event) == 1
    assert not [name for name, (ev, cand) in gates.items() if ev and cand]

    #: `judge` 는 둘 다 받지만 **관문의 답을 접기만 한다** — 스스로
    #: 비교하지 않는다.
    judge_params = [
        parameter
        for parameter in inspect.signature(TriggerEligibilityJudge.judge).parameters
        if parameter != "self"
    ]
    assert judge_params == ["candidate", "spec", "event"]
    body = _function_body("engine/trigger.py", "TriggerEligibilityJudge", "judge")
    assert "fold" in body
    assert "actor" not in body

    #: **딱 한 군데**는 둘을 함께 들고 있다 — 수집기의 `_judge` 다.
    #: 그런데 그것은 관문이 아니라 후보를 **만드는** 자리이고, 거기서
    #: 거부하면 같은 사실이 `EVENT_RELATION` 과 `TriggerStatus` 두 어휘로
    #: 갈려 적힌다 (이 파일이 Phase 3-E-26 으로 경고해 둔 모양이다).
    collector_judge = [
        parameter
        for parameter in inspect.signature(TriggerCollector._judge).parameters
        if parameter != "self"
    ]
    assert collector_judge == ["spec", "event", "card", "definition"]
    collector_body = _function_body("engine/trigger.py", "TriggerCollector", "_judge")
    assert "card.controller" in collector_body
    #: 그 자리에서도 조건 문맥에 사건을 **넣지 않는다.**
    assert "ConditionContext(" in collector_body
    assert "event" not in collector_body.split("ConditionContext(")[1][:200]
    assert "Phase 3-E-26" in collector_body


def test_16_the_board_cannot_remember_which_summon_it_was(repository):
    """
    §10 2·3 — **상태 술어로 복원할 수도 없다.**

    일반 소환된 몬스터와 패에서 특수 소환된 몬스터가 판에서 **완전히 같다.**
    그래서 "이 몬스터는 특수 소환되었다" 를 묻는 조건을 만들 수가 없다 —
    물어볼 값이 판에 없다.

    이것이 `condition` 우회를 닫는 두 번째 자물쇠다 (첫째는 `test_07` 의
    문맥에 사건이 없다는 것).
    """
    duel = live_duel(repository)

    def describe(builder) -> dict:
        state, execution = execute_summon(duel, builder, MINE)
        card: CardInstance = state.find_instance(execution.deltas[0].card)
        return {
            "zone": card.zone,
            "position": card.position,
            "controller": card.controller,
            "owner": card.owner,
            "previous": card.previous.as_tuple(),
            "counters": dict(card.counters),
            "status_flags": card.status_flags,
            "materials": list(card.materials),
            "equipped_to": card.equipped_to,
            "temporary_effects": len(card.temporary_effects),
        }

    normal = describe(PlayerAction.normal_summon)
    special = describe(PlayerAction.special_summon)
    assert normal == special
    assert normal["previous"] == ("HAND", "FACEDOWN", MINE)

    #: `CardInstance` 에 소환 종류를 적는 칸이 없다.
    assert not any("summon" in name for name in CardInstance.__dataclass_fields__)
    assert list(PreviousState.__dataclass_fields__) == [
        "location",
        "position",
        "controller",
    ]
    #: `engine/state/` 전체에서 "summon" 은 **일반 소환권** 하나뿐이다.
    state_sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "engine" / "state").glob("*.py")
    }
    with_summon = {
        name for name, text in state_sources.items() if "summon" in text.lower()
    }
    assert with_summon == {"rule_usage.py"}


# ======================================================================
# F. 경계 보존 (§14 · §15 · §19)
# ======================================================================


def test_17_engine_v1_stayed_frozen():
    """
    §14 — dormant 파이프라인을 production 에 **연결하지 않았다.**

    3-F-5 가 측정한 경계를 그대로 유지한다. `event_pipeline` 과 `timing` 은
    production importer 가 **0** 이다.
    """
    roots = ("engine", "agent", "app", "core", "analysis", "rules", "rulings", "sources", "scripts")
    def importers(module: str) -> set[str]:
        found = set()
        needle_a, needle_b = f"from engine.{module} import", f"import engine.{module}"
        for root in roots:
            for path in (PROJECT_ROOT / root).rglob("*.py"):
                if path.name == f"{module}.py" and path.parent.name == "engine":
                    continue
                text = path.read_text(encoding="utf-8")
                if needle_a in text or needle_b in text:
                    found.add(str(path.relative_to(PROJECT_ROOT)))
        return found

    #: 🔴 **Phase 6-I 에서 ``event_pipeline`` 의 importer 가 0 → 1 이 되었다.**
    #: 그것이 이 Phase 의 산출물이다 — 실제 ``Duel`` 기록을 기존 수집기에
    #: 넘기는 자리다. ``timing`` 은 **여전히 0곳**이고, 그쪽이 체인 삽입까지
    #: 잇는 윗층이다 (6-I 는 체인을 만들지 않는다).
    #:
    #: 이 테스트가 지키는 Engine V1 경계는 그대로다 — 아래
    #: ``activation_timing`` 단정이 여전히 참이고, ``engine/duel.py`` 는
    #: 손대지 않았다.
    assert importers("event_pipeline") == {"engine/trigger_observation.py"}
    assert importers("timing") == set()
    #: `trigger` 는 어휘만 새어 나간다 — `activation_timing` 이 `TimingPoint`
    #: 하나를 읽는다 (3-F-5 §6 이 그 소켓을 측정했다).
    assert "engine/activation_timing.py" in importers("trigger")
    timing_source = source_of("engine/activation_timing.py")
    assert "from engine.trigger import TimingPoint" in timing_source
    for absent in ("TriggerSpec", "TriggerRegistry", "TriggerCollector", "TimingEvent"):
        assert absent not in timing_source, absent


def test_18_the_search_ranking_is_unchanged(repository):
    """§15 — Evaluation/Search 를 건드리지 않았다. 순위를 **돌려서** 확인한다."""
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

    #: 🔴 **Phase 6-Q 가 이 수와 digest 를 바꿨다.** 세트된 일반 함정이
    #: ``legal_actions`` 에 오르게 되었으므로 (RULE-SPELLTRAP-008 · 009)
    #: 탐색이 고를 수 있는 수가 늘고 체인 응답(``pass``)이 생긴다 —
    #: 실측 611 → 689 결정, ``pass`` 73건 · ``activate_effect`` 60건.
    #: 의도한 변화이므로 핀을 갱신했다 (근거: docs/phase6q-…md §18).
    #: 🔴 **보완5 가 이 수와 digest 를 다시 바꿨다: 689 → 979.** 판을 바꾸는
    #: 행위 뒤마다 빠른 효과 기회를 지나는 ``PASS`` 둘이 **필수 절차**로
    #: 끼어든다 (공식 Fast Effect Timing — box B · C). 그래서 탐색이 내리는
    #: 결정의 수가 늘고 (``pass`` 442건 · 전체 979), 궤적이 갈라져 digest 도
    #: 바뀐다. 🔴 **순위 로직은 한 줄도 바뀌지 않았다** — 늘어난 것은
    #: 거쳐야 하는 절차다. 두 번 돌려 같은 값이 나오는 것을 확인했다.
    #: 🔴 **보완6 가 이 수와 digest 를 다시 바꿨다: 979 → 1065.** 빠른 효과
    #: 기회에서 스펠 스피드 1 발동을 막았으므로 (공식 Fast Effect Timing —
    #: 상자 A 에서만 할 수 있는 행동이다) 탐색이 그 자리에서 고를 수 있는
    #: 수가 줄고, 대신 판이 열린 뒤로 밀려 **궤적이 달라진다.**
    #: 실측 종류별: pass 459 · end_phase 378 · set_spell_trap 71 ·
    #: normal_summon 66 · attack 60 · activate_effect 31.
    #: 🔴 **순위 로직은 한 줄도 바뀌지 않았다.** 두 번 돌려 같은 값이
    #: 나오는 것을 확인했다.
    assert decisions == 1065
    assert digest.hexdigest() == (
        "9bc5fadbec28446322b9065e40285df41118caa3f2da8c0737cd875410ddc440"
    )


def test_19_that_phase_added_no_field_but_phase_6e_added_exactly_one():
    """
    §10 · §19 — **3-F-6 은** 선언에 필드를 더하지 않았고, 카드 이름 ·
    패스코드를 production 에 넣지 않았다.

    🔴 **Phase 6-E 가 정확히 하나를 더했다** (``summons``). 이 핀이 그것을
    잡았고, 그것이 이 핀을 둔 이유다 — 3-F-6 은 "필드 하나를 더해서
    해결되지 않는다" 고 적으면서 **아무도 몰래 더하지 못하게** 수를 박아
    두었다.

    🔴 **3-F-6 의 그 문장은 여전히 맞다.** 더한 하나로 해결된 것은 소환
    **종류**뿐이고, 같은 절이 지적한 ``actor`` 축과 "어느 카드의 사건인가"
    는 그대로 선언할 수 없다 (``test_04`` 가 계속 고정한다).

    카드 이름 · 패스코드 쪽 단정은 **그대로**다 — 6-E 가 production 에
    카드를 넣지 않았다.
    """
    #: 아홉 → **열**. 더한 하나가 무엇인지까지 못박는다.
    #: 🔴 3-F-6 은 "필드 하나를 더해서 해결되지 않는다" 며 9 로 박았고,
    #: 6-E 가 정확히 하나(``summons``) 를, 6-F 가 또 하나(``subject``) 를
    #: 더했다. **3-F-6 의 그 문장은 여전히 맞다** — 두 축이 가른 것은
    #: 소환 종류와 주체뿐이고, ``actor`` 관계는 아직 아무 관문도 보지 않는다.
    assert len(TriggerSpec.__dataclass_fields__) == 11
    assert "summons" in TriggerSpec.__dataclass_fields__

    #: 세 예시 카드의 패스코드가 **이 Phase 때문에** production 에 들어온
    #: 자리가 없다.
    #:
    #: .. note::
    #:    처음에는 "production 어디에도 없다" 고 단정했고 **그것이 틀렸다.**
    #:    ``23434538`` 은 ``scripts/fetch_ocg_rulings.py`` 의 **재정 수집
    #:    표본 표**에 이미 있다 (Phase 2 의 rulings 작업에서 들어온 것이고,
    #:    트리거와 무관하다). 금지된 것은 **더하는 것**이므로, 기존 자리를
    #:    정확히 못박아 **새로 생기면 걸리게** 한다.
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
    EXAMPLE_PASSCODES = ("23434538", "42141493", "94145021", "94145022")
    where: dict[str, set[str]] = {code: set() for code in EXAMPLE_PASSCODES}
    for root in roots:
        for path in (PROJECT_ROOT / root).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for passcode in EXAMPLE_PASSCODES:
                if passcode in text:
                    where[passcode].add(str(path.relative_to(PROJECT_ROOT)))

    assert where["23434538"] == {"scripts/fetch_ocg_rulings.py"}
    assert where["42141493"] == set()
    assert where["94145021"] == set()
    assert where["94145022"] == set()
    #: 그 하나뿐인 자리도 **트리거가 아니라 재정 수집**이다.
    sampler = source_of("scripts/fetch_ocg_rulings.py")
    for absent in ("TriggerSpec", "TimingPoint", "SummonKind", "MONSTER_SUMMONED"):
        assert absent not in sampler, absent

    #: `agent/` 는 트리거 어휘를 모른다.
    for relative in (
        "agent/evaluation.py",
        "agent/search.py",
        "agent/heuristic.py",
        "agent/policy.py",
        "agent/simulation.py",
    ):
        text = source_of(relative)
        for absent in ("engine.trigger", "TriggerSpec", "SummonKind"):
            assert absent not in text, (relative, absent)
