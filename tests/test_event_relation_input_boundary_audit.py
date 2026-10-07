"""
Phase 3-F-8 — **EVENT_RELATION 의 입력 경계** 설계 감사.

이 파일이 답하는 단 하나의 질문
-------------------------------
관계 판단을 ``EVENT_RELATION`` 에 두려면 그 관문에 **무엇을 넘겨야 하는가.**

세 설계를 비교한다 (§5)
-----------------------
=====  ================================  ===========================
 A      ``(spec, event)``                 지금 그대로
 B      ``(candidate, event)``            후보 **전체**
 C      ``(spec, event, controller)``     **필요한 최소**
=====  ================================  ===========================

측정으로 확정한 것
------------------
* ``_event_relation`` 이 실제로 읽는 것은 event 6개 · spec 4개다
  (``test_02``). 서명에 있는 것과 읽는 것이 **정확히 일치한다** — 지금은
  남는 입력이 없다.
* 후보 10개 필드 중 **4개는 (spec, event) 의 복사본**, **2개는 새 사실**,
  **4개는 앞선 판정의 출력**이다 (``test_03``). 관계에 필요한 것은
  ``controller`` **하나**다.
* **B 와 C 의 변경 비용이 같다** (``test_19``) — 둘 다
  ``engine/trigger.py`` 두 줄이다. 그러므로 비용으로는 고를 수 없고
  **의미로만** 고를 수 있다.
* 🔴 그런데 ``event.actor`` 는 **사건군마다 다른 것을 가리킨다**
  (``test_15``). 소환·드로우는 "행한 사람", 라이프는 "당한 쪽", 이동은
  "도착지 주인" 이다. 이것은 세 설계 **모두의 상류** 문제이고 입력 경계와
  **별개**다.

이 파일은 production 을 **한 줄도** 바꾸지 않는다 (``test_20``).
"""

import ast
import hashlib
import inspect
import pathlib
import re

import pytest

from engine.action import PlayerAction
from engine.condition import ConditionContext, PlayerRef
from engine.duel import Duel
from engine.effect.delta import (
    CardDrawn,
    LifeChanged,
    MonsterSummoned,
    SummonKind,
    ZoneMoved,
)
from engine.effect.operation import OperationKind
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.summon import duel_executor
from engine.trigger import (
    EligibilityGate,
    TimingEvent,
    TimingPoint,
    TriggerCandidate,
    TriggerCollector,
    TriggerEligibility,
    TriggerEligibilityJudge,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
    timing_for,
)
from engine.validation import (
    CODE_VALIDITY,
    ActionValidity,
    ValidationCode,
    ValidationResult,
)
from engine.vocabulary import Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PRODUCTION_ROOTS = (
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
MINE, THEIRS = 0, 1

LUSTER_DRAGON = 11091375
AUDIT_GRANT = ValidationResult.valid("감사가 관문을 우회해 직접 허가했다")

WATCHING_SUMMONS = TriggerSpec(
    EffectRef(LUSTER_DRAGON, 0),
    TimingPoint.MONSTER_SUMMONED,
    requirement=TriggerRequirement.OPTIONAL,
    activates_from=frozenset({Zone.MZONE}),
)

#: §1 — 관계 판단에 **실제로** 필요한 최소 입력. 측정으로 채운다
#: (``test_02`` 가 앞의 둘을, ``test_09`` 가 세 번째를 고정한다).
MINIMAL_RELATION_INPUTS = (
    "spec.point",
    "spec.operations",
    "spec.from_zones",
    "spec.to_zones",
    "event.point",
    "event.operation",
    "event.from_zone",
    "event.to_zone",
    "event.note",
    "event.actor",
    "controller",
)


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from (PROJECT_ROOT / root).rglob("*.py")


def method_node(relative: str, class_name: str, method: str):
    text = source_of(relative)
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method:
                    return child, text
    raise AssertionError(f"{class_name}.{method} 를 찾지 못했습니다")


def attributes_read(relative: str, class_name: str, method: str) -> set[str]:
    """
    그 메서드가 **실제로 읽는** 속성 이름들. docstring 은 빼고 AST 로 센다.

    문자열 창으로 보면 설명에 적힌 단어가 코드처럼 걸린다 (3-F-7 에서
    실제로 그 실수를 했다).
    """
    node, _ = method_node(relative, class_name, method)
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    found: set[str] = set()
    for statement in body:
        for inner in ast.walk(statement):
            if isinstance(inner, ast.Attribute) and isinstance(inner.value, ast.Name):
                found.add(f"{inner.value.id}.{inner.attr}")
    return found


def params_of(function) -> list[str]:
    return [name for name in inspect.signature(function).parameters if name != "self"]


# ======================================================================
# 판 — 사건의 사람 칸만 바꿀 수 있게 고정한다 (3-F-7 과 같은 방법)
# ======================================================================


def summoned_board(repository):
    deck = [LUSTER_DRAGON] * 20
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=3)
    while duel.advance() is not None:
        pass
    state = duel.state.clone()
    source = list(state.player(MINE).hand)[0].instance_id
    execution = duel_executor().execute(
        state,
        PlayerAction.special_summon(actor=MINE, source=source),
        authorization=AUDIT_GRANT,
    )
    return state, execution.deltas[0]


def event_with_actor(landed: MonsterSummoned, player: int) -> TimingEvent:
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
    view = GameStateView.from_state(state, viewer=MINE)
    collection = TriggerCollector(view, TriggerRegistry((spec,))).collect(event)
    candidate = next(c for c in collection.candidates if c.source == landed.card)
    return candidate, TriggerEligibilityJudge(view).judge(candidate, spec, event)


# ======================================================================
# A. §2 — 서명과 실제 소비를 분리한다
# ======================================================================


def test_01_the_current_signature_and_its_single_caller():
    """
    §2 — 서명 · caller · caller 가 넘기는 값.

    production 에서 이 관문이 나오는 자리는 **정의 하나와 호출 하나**뿐이고,
    둘 다 같은 파일이다.
    """
    assert params_of(TriggerEligibilityJudge._event_relation) == ["spec", "event"]

    sites = [
        (str(path.relative_to(PROJECT_ROOT)), index, line.strip())
        for path in production_files()
        for index, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        )
        if "_event_relation(" in line
    ]
    assert len(sites) == 2, sites
    assert {path for path, _, _ in sites} == {"engine/trigger.py"}
    definition = [line for _, _, line in sites if line.startswith("def ")]
    call = [line for _, _, line in sites if not line.startswith("def ")]
    assert len(definition) == 1 and len(call) == 1
    #: caller 가 넘기는 것은 선언과 사건 **둘뿐**이다.
    assert call[0] == "self._event_relation(spec, event),"

    #: 그 호출 자리는 `judge` 안이고, **그 자리에 후보가 이미 있다.**
    assert params_of(TriggerEligibilityJudge.judge) == ["candidate", "spec", "event"]
    judge_node, text = method_node(
        "engine/trigger.py", "TriggerEligibilityJudge", "judge"
    )
    judge_source = ast.get_source_segment(text, judge_node)
    assert "self._event_relation(spec, event)" in judge_source
    assert "candidate" in judge_source


def test_02_the_signature_and_the_actual_reads_match_exactly():
    """
    §2 의 표 — **"서명에 있는 정보" 와 "실제로 읽는 정보" 를 분리한다.**

    지금은 **남는 입력이 없다**: 넘기는 둘을 둘 다 쓴다. 그래서 A 설계는
    "과하게 받고 있다" 는 비난을 받지 않는다 — 대신 **모자란다.**
    """
    read = attributes_read(
        "engine/trigger.py", "TriggerEligibilityJudge", "_event_relation"
    )
    event_read = {name for name in read if name.startswith("event.")}
    spec_read = {name for name in read if name.startswith("spec.")}

    assert event_read == {
        "event.point",
        "event.note",
        "event.operation",
        "event.from_zone",
        "event.to_zone",
    }
    assert spec_read == {
        "spec.point",
        "spec.operations",
        "spec.from_zones",
        "spec.to_zones",
        "spec.matches",
    }
    #: 넘긴 두 입력이 **둘 다** 실제로 쓰인다 — 죽은 매개변수가 없다.
    assert event_read and spec_read
    #: 그리고 **행위자도 후보도 읽지 않는다.**
    assert "event.actor" not in read
    assert not {name for name in read if name.startswith("candidate.")}
    assert not {name for name in read if name.startswith("controller")}


def test_03_what_passing_the_whole_candidate_would_actually_add():
    """
    §3 — 후보 10개 필드를 **출처로** 가른다.

    ====================================  ==========================
    (spec, event) 의 복사본                 4개 — 이미 손에 있다
    새 사실                                 2개 — ``source`` ·
                                           ``controller``
    **앞선 판정의 출력**                     4개 — ``status`` ·
                                           ``code`` · ``reason`` ·
                                           ``notes``
    ====================================  ==========================

    마지막 넷이 B 설계의 **실제 위험**이다. 관문이 수집기의 판정을 읽을 수
    있게 되면, 그 관문의 답이 **앞선 결정에 의존**할 수 있다 — 이 파일이
    Phase 3-E-26 으로 경고해 둔 "같은 사실을 두 어휘로" 의 다음 단계다.
    """
    fields = list(TriggerCandidate.__dataclass_fields__)
    assert fields == [
        "point",
        "effect_ref",
        "source",
        "controller",
        "status",
        "requirement",
        "wording",
        "code",
        "reason",
        "notes",
    ]

    #: 수집기가 후보를 만들 때 어디서 가져오는지 **코드에서** 읽는다.
    judge_node, text = method_node("engine/trigger.py", "TriggerCollector", "_judge")
    body = ast.get_source_segment(text, judge_node)
    for field, origin in (
        ("point", "event.point"),
        ("effect_ref", "spec.effect_ref"),
        ("source", "card.instance_id"),
        ("controller", "card.controller"),
        ("requirement", "spec.requirement"),
        ("wording", "spec.wording"),
    ):
        assert f'"{field}": {origin}' in body, (field, origin)

    duplicated = {"point", "effect_ref", "requirement", "wording"}
    fresh = {"source", "controller"}
    verdict_outputs = {"status", "code", "reason", "notes"}
    assert duplicated | fresh | verdict_outputs == set(fields)
    assert len(duplicated) == 4 and len(fresh) == 2 and len(verdict_outputs) == 4

    #: 넷이 **판정 출력**임을 확인한다 — 기본값이 있고, 판정 갈래마다 채워진다.
    for name in verdict_outputs:
        assert TriggerCandidate.__dataclass_fields__[name].default is not None
    for marker in ("status=TriggerStatus.", "code=ValidationCode.", "reason="):
        assert marker in body, marker


def test_04_the_spec_side_already_carries_what_the_relation_needs(repository):
    """
    §6 — 선언 쪽은 **이미 충분하다** (행위자 칸을 뺀 나머지는).

    관문이 읽는 선언 축 넷이 모두 `TriggerSpec` 에 있고, 관계를 적을 어휘도
    `PlayerRef` 로 **이미 존재한다** (3-F-7). 모자란 것은 선언이 아니라
    **비교 상대**다.
    """
    spec_fields = set(TriggerSpec.__dataclass_fields__)
    assert {"point", "operations", "from_zones", "to_zones"} <= spec_fields
    #: 관계 어휘는 있다 — 새 enum 이 필요하지 않다 (§7).
    assert {ref.value for ref in PlayerRef} == {"controller", "opponent"}
    assert PlayerRef.OPPONENT.resolve(ConditionContext(player=MINE)) == THEIRS
    #: 그러나 선언에 그것을 적는 칸은 없다 (3-F-6 이 측정한 것 — 재확인만).
    assert not {name for name in spec_fields if "actor" in name or "player" in name}


# ======================================================================
# B. §8 — SELF / OPPONENT / UNKNOWN
# ======================================================================


def test_05_self_relation_has_no_judgement(repository):
    """§8 A — `actor == controller`. 지금은 관계를 **보지 않은** 통과다."""
    state, landed = summoned_board(repository)
    event = event_with_actor(landed, MINE)
    candidate, eligibility = judge_same_candidate(state, landed, event)
    gate = eligibility.gate(EligibilityGate.EVENT_RELATION)

    assert (event.actor, candidate.controller) == (MINE, MINE)
    assert (gate.validity, gate.code) == (ActionValidity.VALID, ValidationCode.OK)


def test_06_opponent_relation_gives_the_same_answer(repository):
    """§8 B — `actor == opponent(controller)`. **A 와 같은 답**이 난다."""
    state, landed = summoned_board(repository)
    self_gate = judge_same_candidate(state, landed, event_with_actor(landed, MINE))[
        1
    ].gate(EligibilityGate.EVENT_RELATION)
    event = event_with_actor(landed, THEIRS)
    candidate, eligibility = judge_same_candidate(state, landed, event)
    gate = eligibility.gate(EligibilityGate.EVENT_RELATION)

    assert event.actor == PlayerRef.OPPONENT.resolve(
        ConditionContext(player=candidate.controller)
    )
    assert (gate.validity, gate.code) == (self_gate.validity, self_gate.code)


def test_07_an_absent_actor_must_not_read_as_opponent():
    """
    §8 C — **정보 부재와 FALSE 관계를 가른다.**

    `actor is None` 인 사건에서 `!=` 는 양쪽 모두 참이 된다. 그러므로 어느
    설계를 고르든 **존재를 먼저 묻는** 비교여야 한다 (3-F-7 이 측정한 것을
    설계 요구로 고정한다).
    """
    moved = timing_for(
        ZoneMoved(
            movement=OperationKind.SEND_TO_GRAVE,
            card=InstanceId(9),
            source_player=THEIRS,
            source_zone=Zone.MZONE,
            destination_player=THEIRS,
            destination_zone=Zone.GRAVE,
        )
    )
    assert moved.actor is not None  # 이동 사건에는 값이 있다

    unimplemented = TimingEvent.unimplemented("옮길 시점 이름이 없다")
    assert unimplemented.actor is None
    assert unimplemented.actor != MINE and unimplemented.actor != THEIRS

    #: 안전한 모양은 존재 확인이 먼저다.
    for player in (MINE, THEIRS):
        decided = unimplemented.actor is not None and unimplemented.actor != player
        assert decided is False


# ======================================================================
# C. §3 · §4 · §5 — 세 설계의 충분성
# ======================================================================


def test_08_design_b_passes_four_fields_the_gate_must_not_read():
    """
    §3 의 결론 — **B 는 필요 없는 것을 넘긴다.**

    관계 판단에 필요한 후보 정보는 ``controller`` 하나다. B 는 그 하나를
    주면서 **앞선 판정의 출력 넷**과 **이미 가진 복사본 넷**을 함께 준다.
    """
    needed = {"controller"}
    carried = set(TriggerCandidate.__dataclass_fields__)
    assert needed < carried
    assert len(carried - needed) == 9

    #: 관문이 지금 읽는 것 가운데 후보에서 와야 하는 것이 **없다.**
    read = attributes_read(
        "engine/trigger.py", "TriggerEligibilityJudge", "_event_relation"
    )
    assert not {name for name in read if name.startswith("candidate.")}

    #: 그리고 그 넷을 읽을 수 있게 되는 것이 왜 위험한가 — 같은 파일이
    #: 이미 그 위험을 이름으로 적어 두었다.
    trigger_source = source_of("engine/trigger.py")
    assert "Phase 3-E-26" in trigger_source
    assert "같은 사실이 두 코드로" in trigger_source


def test_09_controller_alone_is_enough_for_the_relation(repository):
    """
    §4 — **controller 하나로 지금의 관계를 전부 표현할 수 있다.**

    SELF · OPPONENT · ANY 세 범주를 `PlayerRef` 와 정수 하나로 계산해
    보인다. **production 을 바꾸지 않고** 감사 쪽에서만 계산한다.
    """
    state, landed = summoned_board(repository)

    def relation(actor: "int | None", controller: int) -> str:
        """감사용 계산. production 에 이 함수를 더하지 않았다."""
        if actor is None:
            return "UNKNOWN"
        if actor == controller:
            return "SELF"
        if actor == PlayerRef.OPPONENT.resolve(ConditionContext(player=controller)):
            return "OPPONENT"
        return "UNREACHABLE"  # 2인 게임에서는 닿지 않는다

    for player, expected in ((MINE, "SELF"), (THEIRS, "OPPONENT")):
        event = event_with_actor(landed, player)
        candidate, _ = judge_same_candidate(state, landed, event)
        assert relation(event.actor, candidate.controller) == expected

    assert relation(None, MINE) == "UNKNOWN"
    #: 2인 가정 아래에서 네 번째 답은 나오지 않는다.
    assert {relation(a, MINE) for a in (MINE, THEIRS, None)} == {
        "SELF",
        "OPPONENT",
        "UNKNOWN",
    }


def test_10_design_a_cannot_express_the_relation_at_all(repository):
    """
    §5 A — `(spec, event)` 만으로는 **원리적으로** 불가능하다.

    비교 상대가 서명에 없다. 사건만 보고 "상대인가" 를 답하려면 기준이
    필요하고, 그 기준은 사건에 없다 — 같은 사건이 후보에 따라 SELF 이기도
    OPPONENT 이기도 하다.
    """
    state, landed = summoned_board(repository)
    event = event_with_actor(landed, THEIRS)

    #: 같은 사건 하나가 두 기준에서 다른 관계가 된다.
    assert event.actor == THEIRS
    assert (event.actor == MINE, event.actor == THEIRS) == (False, True)
    #: 즉 사건 자체는 관계를 **결정하지 않는다.**
    assert "actor" not in TriggerSpec.__dataclass_fields__
    assert params_of(TriggerEligibilityJudge._event_relation) == ["spec", "event"]


def test_11_the_minimal_input_set_is_eleven_values():
    """
    §1 의 목표 — **관계 판단에 필요한 최소 입력 집합.**

    지금 읽는 열 개(event 5 · spec 4 · `matches`)에 **둘**을 더하면 된다 —
    `event.actor` 와 `controller`. 그 밖의 후보 metadata 는 하나도 필요하지
    않다.
    """
    read = attributes_read(
        "engine/trigger.py", "TriggerEligibilityJudge", "_event_relation"
    )
    current = {name for name in read if name.startswith(("event.", "spec."))}
    #: `matches` 는 값이 아니라 호출이므로 입력 집합에서 뺀다.
    current -= {"spec.matches"}
    assert len(current) == 9

    minimal = set(MINIMAL_RELATION_INPUTS)
    assert current < minimal
    assert minimal - current == {"event.actor", "controller"}
    assert len(minimal) == 11

    #: 후보에서 오는 것은 **정수 하나**뿐이다.
    from_candidate = {name for name in minimal if name == "controller"}
    assert len(from_candidate) == 1


# ======================================================================
# D. §9 · §10 — 요구사항과 확장
# ======================================================================


def test_12_the_special_summon_requirement_under_three_designs(repository):
    """
    §9 — "candidate controller 의 opponent 가 SPECIAL_SUMMON 을 수행한
    Event". 구현하지 않고 **어느 설계가 표현하는지만** 본다.

    다섯 조각 가운데 **네 조각은 세 설계 모두 같고**, 갈리는 것은 관계
    하나다.
    """
    state, landed = summoned_board(repository)
    event = event_with_actor(landed, THEIRS)
    candidate, _ = judge_same_candidate(state, landed, event)

    pieces = {
        "point": event.point is TimingPoint.MONSTER_SUMMONED,
        "summon_kind": event.delta.summon is SummonKind.SPECIAL,
        "actor": event.actor == THEIRS,
        "controller": candidate.controller == MINE,
        "relation": event.actor
        == PlayerRef.OPPONENT.resolve(ConditionContext(player=candidate.controller)),
    }
    assert all(pieces.values()), pieces

    #: A 는 마지막 둘을 받지 못한다 · B·C 는 둘 다 받는다.
    reachable = {
        "A": {"point", "summon_kind", "actor"},
        "B": set(pieces),
        "C": set(pieces),
    }
    assert reachable["A"] < reachable["C"]
    assert reachable["B"] == reachable["C"]
    #: 그러므로 **A 와 나머지**가 갈리고, B 와 C 는 표현력이 같다.
    assert "relation" not in reachable["A"]


def test_13_the_draw_relation_needs_nothing_more_than_the_summon_one():
    """
    §10 5·6 — "내가/상대가 드로우했다" 는 소환과 **같은 정보**로 된다.

    `CardDrawn.player` 가 뽑은 사람이므로 `event.actor` 가 행위자다.
    """
    mine = timing_for(CardDrawn(player=MINE, card=InstanceId(3)))
    theirs = timing_for(CardDrawn(player=THEIRS, card=InstanceId(4)))
    assert mine.point is TimingPoint.CARD_DRAWN
    assert (mine.actor, theirs.actor) == (MINE, THEIRS)
    #: 같은 두 입력(actor · controller)으로 갈린다 — 새 정보가 필요 없다.
    assert mine.actor != theirs.actor


def test_14_the_destroy_relation_is_about_the_owner_not_the_agent():
    """
    §10 3·4 — "내 카드가 파괴됨" / "상대 카드가 파괴됨" 은 **된다.**

    다만 그것이 되는 이유가 "행위자를 안다" 가 아니라 **"도착지 주인이
    곧 카드의 주인"** 이기 때문이다. 요구가 "누가 파괴했는가" 로 바뀌면
    **표현할 수 없다** (``test_15``).
    """
    def destroyed(owner: int) -> TimingEvent:
        return timing_for(
            ZoneMoved(
                movement=OperationKind.DESTROY,
                card=InstanceId(9),
                source_player=owner,
                source_zone=Zone.MZONE,
                destination_player=owner,
                destination_zone=Zone.GRAVE,
            )
        )

    assert destroyed(MINE).actor == MINE
    assert destroyed(THEIRS).actor == THEIRS
    #: 두 경우가 갈린다 — "누구의 카드가" 는 표현된다.
    assert destroyed(MINE).actor != destroyed(THEIRS).actor
    #: 그런데 `ZoneMoved` 에 **행위자 칸이 없다.**
    assert set(ZoneMoved.__dataclass_fields__) == {
        "movement",
        "card",
        "source_player",
        "source_zone",
        "destination_player",
        "destination_zone",
    }
    assert not {
        name for name in ZoneMoved.__dataclass_fields__ if "actor" in name
    }


def test_15_the_event_actor_means_different_things_per_event_family():
    """
    🔴 **이 Phase 가 새로 찾은 상류 결함.**

    ``TimingEvent.actor`` 는 사건군마다 다른 것을 가리킨다.

    ===================  ================================  =========
    ``MonsterSummoned``   ``delta.player`` = 소환한 사람      행위자 ○
    ``CardDrawn``         ``delta.player`` = 뽑은 사람        행위자 ○
    ``LifeChanged``       ``delta.player`` = LP 가 바뀐 쪽    **당한 쪽** ✗
    ``ZoneMoved``         ``delta.to_player`` = 도착지 주인    **주인** ✗
    ===================  ================================  =========

    이것은 **세 설계 모두의 상류** 문제다 — A·B·C 어느 쪽을 골라도 같은
    값을 비교하게 된다. 그래서 입력 경계 판정과 **분리해서** 기록한다.

    .. note::
       **이 테스트의 첫 단정이 바뀌었다** (Phase 3-F-11).

       3-F-8 당시에는 ``engine/trigger.py`` 안에 "이 사건을 일으킨 플레이어"
       라는 문장이 **그대로 적혀 있었고**, 이 테스트는 그 문장이 있다는 것을
       결함의 증거로 고정했다. 그 전제가 이제 잘못됐다 — 3-F-11 이 그 거짓
       문장을 **지웠기** 때문이다. 즉 이 테스트는 "설명이 틀렸다" 를 고정했고,
       설명이 고쳐지면 반드시 깨지는 모양이었다.

       **결함 자체는 사라지지 않았다.** 아래 실측 (라이프는 당한 쪽 · 이동은
       도착지 주인) 은 하나도 바뀌지 않았고, 그래서 이 테스트는 삭제되지 않는다.
       바뀐 것은 증거의 방향뿐이다: 거짓 문장이 **있다**가 아니라, 사건군별
       뜻을 밝힌 표와 "행위의 주체가 아니다" 라는 경고가 **있다** 를 고정한다.
    """
    #: 이제 설명이 사건군마다 다르다는 것을 **밝힌다** — 거짓 단정이 없다.
    trigger_source = source_of("engine/trigger.py")
    assert "이 사건을 일으킨 플레이어" not in trigger_source
    assert "**행위의 주체가 아니다**" in trigger_source
    assert "사건군마다 다르다" in trigger_source

    #: 그런데 `from_delta` 가 사건군마다 **다른 칸**에서 가져온다.
    from_delta, text = method_node("engine/trigger.py", "TimingEvent", "from_delta")
    body = ast.get_source_segment(text, from_delta)
    assert "actor=delta.to_player" in body      # ZoneMoved — 도착지 주인
    assert "actor=delta.player" in body         # 소환 · 드로우 · 라이프

    #: 라이프는 **당한 쪽**이다 — 깎은 쪽이 아니다.
    hurt = timing_for(LifeChanged(player=MINE, before=8000, after=6000))
    assert hurt.actor == MINE
    assert hurt.delta.before > hurt.delta.after   # 내가 피해를 입었다
    #: 그러나 그 피해를 **누가 입혔는지** 는 어디에도 없다.
    assert set(LifeChanged.__dataclass_fields__) == {"player", "before", "after"}

    #: 컨트롤이 넘어가는 이동에서는 출발지와 도착지가 **다른 사람**이고,
    #: `actor` 는 도착지를 고른다.
    handed_over = timing_for(
        ZoneMoved(
            movement=OperationKind.MOVE,
            card=InstanceId(9),
            source_player=MINE,
            source_zone=Zone.MZONE,
            destination_player=THEIRS,
            destination_zone=Zone.MZONE,
        )
    )
    assert handed_over.actor == THEIRS
    assert handed_over.delta.source_player == MINE
    #: "내가 내 카드를 상대에게 넘겼다" 인데 actor 는 상대다.

    #: 그리고 이 `actor` 는 `PlayerAction.actor` 와 **다른 값**이다 —
    #: 그쪽은 production 이 `actor == controller` 를 요구한다 (3-E-28).
    assert "actor" in PlayerAction.__dataclass_fields__
    assert "actor" in TimingEvent.__dataclass_fields__
    assert PlayerAction.__dataclass_fields__["actor"] is not (
        TimingEvent.__dataclass_fields__["actor"]
    )


# ======================================================================
# E. §12 · §13 · §14 · §15 — 손실 · 판정 · 숨은 정보 · 불변
# ======================================================================


def test_16_the_three_designs_lose_different_things(repository):
    """
    §12 — **"정보가 사라지는 것" 과 "이 계층에서 필요하지 않은 것" 을
    가른다.**

    세 설계 모두 **판정 결과에서 사건이 사라진다** (3-F-7 §5) — 그것은
    입력 경계와 무관한 별개 손실이다.
    """
    #: 어느 설계든 출력에 사건이 없다.
    assert "event" not in TriggerEligibility.__dataclass_fields__
    assert list(TriggerEligibility.__dataclass_fields__) == [
        "candidate",
        "status",
        "gates",
        "unchecked_rules",
    ]

    #: 그런데 **후보는 남으므로** controller 는 결과에서 되살릴 수 있다.
    state, landed = summoned_board(repository)
    event = event_with_actor(landed, THEIRS)
    candidate, eligibility = judge_same_candidate(state, landed, event)
    assert eligibility.candidate.controller == candidate.controller
    #: 행위자는 되살릴 수 없다 — 그것이 실제 손실이다.
    assert "actor" not in str(eligibility.to_dict())
    assert event.actor == THEIRS


def test_17_the_relation_result_fits_the_existing_validation_vocabulary():
    """
    §13 — 세 결과를 **새 코드 없이** 적을 수 있는가.

    ===========================  ================================
    SELF · OPPONENT 가 맞는다       ``VALID`` / ``OK``
    관계가 확실히 다르다             ``INVALID`` / ``CANDIDATE_NOT_ELIGIBLE``
    행위자를 모른다                  ``UNKNOWN`` / ``INFORMATION_UNAVAILABLE``
    ===========================  ================================

    셋 다 **이미 있는** 코드이고, 세 번째는 3-E-45 가 "적었는데 읽을 수
    없다" 에 쓰려고 만든 그 코드다. 새 코드를 더하지 않았다.
    """
    assert len(CODE_VALIDITY) == 48
    assert CODE_VALIDITY[ValidationCode.OK] is ActionValidity.VALID
    assert (
        CODE_VALIDITY[ValidationCode.CANDIDATE_NOT_ELIGIBLE] is ActionValidity.INVALID
    )
    assert (
        CODE_VALIDITY[ValidationCode.INFORMATION_UNAVAILABLE] is ActionValidity.UNKNOWN
    )
    #: 그 셋이 `_event_relation` 이 이미 쓰는 어휘 안에 있다.
    node, text = method_node(
        "engine/trigger.py", "TriggerEligibilityJudge", "_event_relation"
    )
    body = ast.get_source_segment(text, node)
    for code in ("OK", "CANDIDATE_NOT_ELIGIBLE", "INFORMATION_UNAVAILABLE"):
        assert code in body, code


def test_18_neither_design_widens_the_hidden_information_boundary(repository):
    """
    §14 — 후보 전체를 넘기는 설계가 **숨은 정보**를 끌고 오는가.

    지금은 **아니다** — 후보는 보이는 카드에서만 생기므로 열 필드 전부
    공개값이다. 위험은 숨은 정보가 아니라 **판정 출력 결합**이다
    (``test_03`` · ``test_08``).
    """
    state, landed = summoned_board(repository)
    event = event_with_actor(landed, THEIRS)
    candidate, _ = judge_same_candidate(state, landed, event)
    view = GameStateView.from_state(state, viewer=MINE)

    #: 후보의 출처 카드가 내 관측에서 보인다 — 가려진 카드가 후보가 되지 않는다.
    seen = view.find(candidate.source)
    assert seen is not None
    #: 상대 패 · 덱은 그대로 가려져 있다.
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(THEIRS).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()

    #: 후보에 카드 신원이나 비공개 metadata 를 담는 칸이 없다.
    assert not {
        name
        for name in TriggerCandidate.__dataclass_fields__
        if name in {"card_id", "metadata", "hand", "deck"}
    }
    #: 반대로 최소 입력 설계가 공개 정보를 **빼앗지도** 않는다 —
    #: 관계에 필요한 두 값이 다 들어온다.
    assert event.actor is not None and candidate.controller in (0, 1)


def test_19_designs_b_and_c_cost_the_same(repository):
    """
    §19 — **비용으로는 고를 수 없다.**

    호출 자리에 후보가 이미 있으므로 `candidate` 를 넘기는 것과
    `candidate.controller` 를 넘기는 것이 **같은 한 줄**이다. 그리고
    테스트에서 이 관문을 **직접 부르는 곳이 하나도 없다.**
    """
    #: production: 정의 1 · 호출 1, 같은 파일.
    sites = [
        str(path.relative_to(PROJECT_ROOT))
        for path in production_files()
        if "_event_relation(" in path.read_text(encoding="utf-8")
    ]
    assert sites == ["engine/trigger.py"]

    #: 테스트: 언급은 많지만 **직접 호출 0회**.
    #:
    #: .. note::
    #:    처음에는 정규식으로 셌고 **내 정규식 리터럴 자신이 두 번 걸렸다**
    #:    (`r"\._event_relation\("` 안에 그 글자가 들어 있다). 문자열이
    #:    아니라 **AST 의 Call 노드**를 세는 쪽으로 고쳤다 — 이 저장소가
    #:    3-E-44 부터 지켜 온 규칙이고, 이번엔 세는 쪽 코드에도 적용해야
    #:    했다.
    mentions = 0
    direct = 0
    files = set()
    for path in (PROJECT_ROOT / "tests").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "_event_relation" not in text:
            continue
        files.add(str(path.relative_to(PROJECT_ROOT)))
        mentions += text.count("_event_relation")
        for node in ast.walk(ast.parse(text)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_event_relation"
            ):
                direct += 1
    assert direct == 0
    assert mentions >= 40 and len(files) >= 10

    #: `judge` 의 서명은 **어느 설계에서도 바뀌지 않는다** — 이미 후보를 받는다.
    assert params_of(TriggerEligibilityJudge.judge) == ["candidate", "spec", "event"]
    #: `judge_all` 을 부르는 production 자리는 하나다.
    chain = [
        str(path.relative_to(PROJECT_ROOT))
        for path in production_files()
        if ".judge_all(" in path.read_text(encoding="utf-8")
    ]
    assert chain == ["engine/trigger_chain.py"]

    #: 반면 **선언에 칸을 더하는 쪽**은 비용이 다르다 — 28개 테스트 파일이
    #: `TriggerSpec(...)` 를 만든다 (기본값이 있으면 생성은 깨지지 않지만
    #: `canonical_state` 길이를 단정하는 자리는 깨진다).
    builders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in (PROJECT_ROOT / "tests").rglob("*.py")
        if "TriggerSpec(" in path.read_text(encoding="utf-8")
    ]
    assert len(builders) >= 25
    assert len(TriggerSpec(EffectRef(1, 0), TimingPoint.CARD_DRAWN).canonical_state()) == 9


def test_20_this_phase_changed_nothing(repository):
    """§15 · §16 · §17 — freeze · 불변 · 순위 digest."""
    #: 관문 서명 · 선언 필드 · 후보 필드 · 사건 필드 · 판정 어휘 전부 그대로.
    assert params_of(TriggerEligibilityJudge._event_relation) == ["spec", "event"]
    assert len(TriggerSpec.__dataclass_fields__) == 9
    assert len(TriggerCandidate.__dataclass_fields__) == 10
    assert list(TimingEvent.__dataclass_fields__) == [
        "point",
        "delta",
        "effect_ref",
        "actor",
        "note",
    ]
    assert len(CODE_VALIDITY) == 48

    #: dormant 파이프라인을 연결하지 않았다.
    duel_source = source_of("engine/duel.py")
    for absent in (
        "TriggerRegistry",
        "TriggerCollector",
        "TriggerEligibilityJudge",
        "engine.timing",
        "engine.event_pipeline",
    ):
        assert absent not in duel_source, absent

    #: 판과 난수는 판정으로 움직이지 않는다.
    state, landed = summoned_board(repository)
    before_hash, before_rng = state.state_hash(), repr(state.rng)
    judge_same_candidate(state, landed, event_with_actor(landed, THEIRS))
    assert state.state_hash() == before_hash
    assert repr(state.rng) == before_rng

    #: 탐색 순위를 실제로 돌려 확인한다.
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
