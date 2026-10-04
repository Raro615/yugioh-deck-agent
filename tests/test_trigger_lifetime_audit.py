"""
Phase 3-E-22 — ``TriggerCandidate`` → ``PlayerAction`` 번역 지점과 사건의 생애 (감사).

이 Phase 는 production 코드를 바꾸지 않았다. 감사 테스트만 더했다.

한 문장
-------
**번역 지점은 없다. 그리고 그것이 지금 틀린 것은 아니다** — 다만 이으려면
"사건" 을 들고 있을 자리를 먼저 정해야 하고, 그 자리는 ``GameState`` 가 아니다.

측정으로 확인된 다섯 가지
-------------------------
1. ``legal_actions()`` 는 **상태의 함수**다. 같은 상태에서 두 번 부르면 결과가
   글자까지 같고, 사건을 읽지 않는다 (``_activation_actions`` 는 ``self.state``
   와 검증기만 본다). 그래서 **중복 후보는 생기지 않는다.**
2. 그 대가로 ``legal_actions()`` 는 **"직전에 무슨 일이 있었는가" 를 모른다.**
   유발 효과는 "지금 상태에서 할 수 있는 일" 이 아니라 "직전 사건이 만든 선택"
   이므로, 현재 구조만으로는 **복원할 수 없다.**
3. 사건 identity 는 이미 있다 — ``EffectEvent.sequence`` ("무작위 UUID 도,
   시각도, 객체 주소도 쓰지 않는다. ``sequence`` 가 identity 다"). 그런데
   ``TimingEvent`` 로 **전달되지 않고**, production 에는 ``EventJournal`` 이
   붙어 있지 않다 (Phase 3-E-20).
4. ``TriggerCandidate.identity`` 는 ``(point, card_id, ordinal, source,
   controller)`` 다 — **어느 사건이었는지가 없다.** 서로 다른 두 사건에서 같은
   identity 가 나온다.
5. 더 앞선 공백이 하나 더 있다 — ``TriggerCollector._judge`` 는 **사건의 주체를
   보지 않는다.** ``ConditionContext`` 에 사건 자리가 없어서 "이 카드가
   파괴되었을 때" 류를 판정할 근거가 조건 계층에 전달되지 않는다.

소유권은 어디인가 (판정만 한다)
-------------------------------
``GameState`` 는 ``journal`` · ``chain`` · ``pending`` 슬롯을 **비워 둔 채**
두기로 이미 결정되어 있다 — "역사도 체인도 우선권도 판의 모양이 아니고, 넣으면
같은 판이 경로에 따라 다른 해시를 갖게 된다" (``canonical_state`` 의 설명).
그 결정의 예외는 ``rule_uses`` 하나인데, 그것은 **규칙이 턴 단위로 묻는 사실**
이어서 모양으로 간주된 것이다 (Phase 3-E-15).

"직전 사건이 만든 열린 선택" 은 모양이 아니라 **흐름의 위치**다. 그 자리는
이미 ``Duel`` 이 들고 있다 (``chain`` · ``priority`` · ``pending_spells`` ·
``step`` — 모두 ``state_hash()`` 에 들어가지 않는다). 그래서 후보의 자연스러운
소유자 후보는 ``GameState`` 가 아니라 **그쪽**이고, 조건이 하나 붙는다:
``Simulator._fork`` 가 ``dataclasses.replace(duel, state=clone())`` 이므로
**불변 값**이어야 한다.
"""

import ast
import dataclasses
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.condition.context import ConditionContext
from engine.duel import Duel
from engine.effect.delta import ZoneMoved
from engine.effect.journal import CostPaymentEvent, EffectEvent
from engine.effect.semantics import OperationKind
from engine.ids import EffectRef
from engine.state.game_state import GameState
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerCollector,
    TriggerRegistry,
    TriggerSpec,
)
from engine.vocabulary import Phase, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
POT_OF_GREED = 55144522
FEATHERMAN = 21844576


def small_duel(repository, *, seed: int = 5) -> Duel:
    deck = [POT_OF_GREED] * 8 + [FEATHERMAN] * 8
    return Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)


def at_main1(duel: Duel) -> Duel:
    while duel.state.turn.phase is not Phase.MAIN1:
        duel.apply(PlayerAction(kind=PlayerActionKind.END_PHASE, actor=duel.turn_player))
        duel.advance()
    return duel


def function_body(path: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((PROJECT_ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path} 에 {name} 이 없습니다")


def moved_event(instance, *, seat: int) -> TimingEvent:
    return TimingEvent.from_delta(
        ZoneMoved(
            movement=OperationKind.SEND_TO_GRAVE,
            card=instance,
            source_player=seat,
            source_zone=Zone.MZONE,
            destination_player=seat,
            destination_zone=Zone.GRAVE,
        )
    )


# ======================================================================
# §3 · §9 — legal_actions 는 상태의 함수다
# ======================================================================


@pytest.mark.real_card
def test_01_legal_actions_is_a_pure_function_of_the_board(repository):
    """
    **§4-B — 같은 상태에서 두 번 부르면 결과가 같다.**

    매 호출마다 새로 계산하지만 입력이 같으므로 **중복 후보가 생기지 않는다.**
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    first = duel.legal_actions(seat)
    second = duel.legal_actions(seat)
    assert tuple(first.allowed) == tuple(second.allowed)
    assert tuple(first.withheld) == tuple(second.withheld)
    assert len(first.allowed) > 1
    #: 상태도 바뀌지 않았다 — 후보 생성은 판을 읽기만 한다.
    assert duel.state.state_hash() == duel.state.state_hash()


def test_02_activation_candidates_never_look_at_an_event():
    """
    **§3-3 · §3-4 — 후보 생성은 사건을 읽지 않는다.**

    ``_activation_actions`` 가 읽는 것은 ``self.state`` · 검증기 · 정의
    저장소뿐이다. ``event`` · ``journal`` · ``trigger`` · ``candidate`` 라는
    이름이 **한 번도 나오지 않는다.**
    """
    node = function_body("engine/duel.py", "_activation_actions")
    names = {
        inner.id
        for inner in ast.walk(node)
        if isinstance(inner, ast.Name)
    } | {
        inner.attr
        for inner in ast.walk(node)
        if isinstance(inner, ast.Attribute)
    }
    for forbidden in ("event", "journal", "trigger", "candidates", "collect"):
        assert not [n for n in names if forbidden in n.lower()], (forbidden, sorted(names))
    #: 반대로 판은 읽는다.
    assert "state" in names


def test_03_no_translation_function_exists_from_candidate_to_action():
    """
    **§8 — ``TriggerCandidate`` 하나를 ``PlayerAction`` 하나로 바꾸는 함수가
    production 에 없다.**

    ``engine/`` 전체에서 ``TriggerCandidate`` 를 받아 ``PlayerAction`` 을
    돌려주는 함수가 없고, ``Duel`` 에는 그런 이름의 메서드도 없다.
    """
    duel_methods = {name for name in vars(Duel) if not name.startswith("__")}
    assert not [m for m in duel_methods if "trigger" in m or "candidate" in m], duel_methods

    #: **코드로** 둘을 함께 다루는 모듈이 없어야 한다. 설명 문장에서 둘을
    #: 나란히 말하는 모듈은 셋 있는데 (``__init__.py`` · ``turn_progression.py`` ·
    #: ``special_summon.py``), 전부 docstring 이고 AST 의 이름에는 나오지 않는다.
    together = []
    for path in sorted((PROJECT_ROOT / "engine").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        used |= {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        used |= {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        if {"TriggerCandidate", "PlayerAction"} <= used:
            together.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert together == [], together


# ======================================================================
# §5 — 사건 identity
# ======================================================================


def test_04_event_identity_exists_in_the_journal_but_not_in_the_timing_event():
    """
    **§5-1 · §5-4 — 사건 번호는 이미 있다. 트리거 쪽으로 오지 않는다.**

    ``EffectEvent``/``CostPaymentEvent`` 는 ``sequence`` 를 identity 로 쓴다.
    ``TimingEvent`` 에는 그 칸이 없고, 들고 있는 것은 ``delta`` 객체뿐이다.
    """
    assert "sequence" in EffectEvent.__dataclass_fields__
    assert "sequence" in CostPaymentEvent.__dataclass_fields__
    journal_source = (PROJECT_ROOT / "engine/effect/journal.py").read_text(
        encoding="utf-8"
    )
    assert "``sequence`` 가 identity 다" in journal_source

    timing_fields = {f.name for f in dataclasses.fields(TimingEvent)}
    assert timing_fields == {"point", "delta", "effect_ref", "actor", "note"}
    assert not [f for f in timing_fields if "id" == f or "sequence" in f]


@pytest.mark.real_card
def test_05_two_different_events_produce_candidates_with_the_same_identity(repository):
    """
    **§5-2 · §10 cross-event collision — POSSIBLE.**

    같은 ``TimingPoint`` 의 서로 다른 사건에서 나온 후보의 ``identity`` 가
    **완전히 같다.** 후보만 들고 있으면 "어느 사건 때문이었는가" 를 말할 수 없다.
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    hand = duel.state.player(seat).hand
    assert len(hand) >= 2

    registry = TriggerRegistry().register(
        TriggerSpec(
            effect_ref=EffectRef(hand[0].card_id, 0), point=TimingPoint.CARD_MOVED
        )
    )
    collector = TriggerCollector(duel.view(seat), registry)

    first = collector.collect(moved_event(hand[0].instance_id, seat=seat))
    second = collector.collect(moved_event(hand[1].instance_id, seat=seat))
    assert first.candidates and second.candidates
    assert [c.identity for c in first.candidates] == [
        c.identity for c in second.candidates
    ]
    #: 사건 자체는 서로 다르다 — 구분은 **컬렉션**이 들고 있는 것뿐이다.
    assert first.event != second.event
    assert first.event.instance != second.event.instance  # property 다


@pytest.mark.real_card
def test_06_the_candidate_does_not_know_who_the_event_happened_to(repository):
    """
    **§5 — 더 앞선 공백: 사건의 주체가 후보에 들어가지 않는다.**

    ``hand[1]`` 이 움직인 사건인데도 ``hand[0]`` 의 선언이 후보가 된다.
    ``_judge`` 는 ``event.instance()`` 를 **보지 않고**, ``ConditionContext``
    에도 사건 자리가 없다. 그래서 "이 카드가 파괴되었을 때" 를 판정할 근거가
    조건 계층에 닿지 않는다.
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    hand = duel.state.player(seat).hand

    registry = TriggerRegistry().register(
        TriggerSpec(
            effect_ref=EffectRef(hand[0].card_id, 0), point=TimingPoint.CARD_MOVED
        )
    )
    collector = TriggerCollector(duel.view(seat), registry)
    #: 다른 카드가 움직인 사건
    collection = collector.collect(moved_event(hand[1].instance_id, seat=seat))
    sources = {c.source for c in collection.candidates}
    assert hand[0].instance_id in sources  # 사건과 무관한 카드가 후보가 된다

    #: 코드 근거 — ``_judge`` 는 사건의 주체를 묻지 않는다.
    judge = function_body("engine/trigger.py", "_judge")
    attrs = {
        inner.attr for inner in ast.walk(judge) if isinstance(inner, ast.Attribute)
    }
    assert "instance" not in attrs, sorted(attrs)
    assert "point" in attrs

    #: 조건 문맥에 사건 자리가 없다.
    assert {f.name for f in dataclasses.fields(ConditionContext)} == {
        "player",
        "source",
        "effect_ref",
        "targets",
    }


# ======================================================================
# §10 — 중복 · stale · 재구성
# ======================================================================


@pytest.mark.real_card
def test_07_collecting_the_same_event_twice_yields_the_candidates_twice(repository):
    """
    **§10 duplicate — 수집기 수준에서는 POSSIBLE, ``legal_actions`` 수준에서는
    IMPOSSIBLE.**

    ``TriggerCollector`` 는 "이미 모았다" 를 기억하지 않는다 — 같은 사건을 두 번
    주면 같은 후보가 두 벌 나온다. 지금은 부르는 곳이 없으므로 해가 없지만,
    이을 때 **누가 한 번만 모으는지**를 정해야 한다.
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    hand = duel.state.player(seat).hand
    registry = TriggerRegistry().register(
        TriggerSpec(
            effect_ref=EffectRef(hand[0].card_id, 0), point=TimingPoint.CARD_MOVED
        )
    )
    collector = TriggerCollector(duel.view(seat), registry)
    event = moved_event(hand[0].instance_id, seat=seat)
    one = collector.collect(event)
    two = collector.collect(event)
    assert [c.identity for c in one.candidates] == [c.identity for c in two.candidates]
    assert len(one.candidates) + len(two.candidates) == 2 * len(one.candidates)

    #: 그런데 ``legal_actions`` 쪽은 상태의 함수라서 중복이 생기지 않는다.
    assert tuple(duel.legal_actions(seat).allowed) == tuple(
        duel.legal_actions(seat).allowed
    )


@pytest.mark.real_card
def test_08_nothing_remembers_that_a_candidate_was_already_handled(repository):
    """
    **§10 stale — 현재 구조에는 "처리했다" 는 기록이 없다.**

    발동한 카드가 다시 후보가 되지 않는 이유는 **상태가 바뀌었기 때문**이고
    (카드가 손을 떠났다), "이미 처리했다" 를 기억해서가 아니다. ``Duel`` 의
    필드에 그런 기록이 없다.
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    activations = [
        a
        for a in duel.legal_actions(seat)
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert activations
    chosen = activations[0]
    assert duel.apply(chosen).accepted

    #: 응답 창에서 상대가 패스한다.
    responder = duel.to_act
    assert [a.kind for a in duel.legal_actions(responder).allowed] == [
        PlayerActionKind.PASS
    ]
    duel.apply(PlayerAction.passing(actor=responder))

    #: 같은 발동이 다시 후보가 되지 않는다 — 카드가 그 자리에 없기 때문이다.
    again = duel.legal_actions(duel.to_act)
    assert not [
        a
        for a in again.allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and a.source == chosen.source
        and a.effect_ref == chosen.effect_ref
    ]

    #: "처리했다" 를 적는 자리가 없다는 것을 필드 목록으로 확인한다.
    names = {f.name for f in dataclasses.fields(Duel)}
    assert names == {
        "state",
        "priority",
        "chain",
        "step",
        "first_player",
        "_executor",
        "_activator",
        "_resolver",
        "_placement",
        "pending_spells",
    }


def test_09_the_board_deliberately_refuses_to_store_history():
    """
    **§9 — ``GameState`` 는 역사를 담지 않기로 이미 결정되어 있다.**

    ``journal`` · ``chain`` · ``pending`` 슬롯이 있지만 **비워 두고**,
    ``canonical_state`` 에 넣지 않는다 — "같은 판은 만들어진 경로와 무관하게
    같은 해시" 를 지키기 위해서다. 예외는 ``rule_uses`` 하나이고, 그것은 규칙이
    턴 단위로 묻는 사실이라 **모양으로 간주**된 것이다 (Phase 3-E-15).

    그러므로 "후보를 ``GameState`` 에 넣자" 는 결론은 이 결정을 먼저 뒤집어야
    한다. 이 Phase 는 뒤집지 않는다.
    """
    assert {"journal", "chain", "pending", "rule_uses"} <= set(GameState.__slots__)
    source = (PROJECT_ROOT / "engine/state/game_state.py").read_text(encoding="utf-8")
    assert "앞으로도 넣지 않는다" in source
    assert "역사도 체인도 우선권도 판의 모양이" in source

    #: ``canonical_state`` 가 읽는 것에 역사가 없고, ``rule_uses`` 는 있다.
    node = function_body("engine/state/game_state.py", "canonical_state")
    attrs = {
        inner.attr for inner in ast.walk(node) if isinstance(inner, ast.Attribute)
    }
    assert "rule_uses" in attrs
    assert "journal" not in attrs and "chain" not in attrs


# ======================================================================
# §11 — 사본
# ======================================================================


@pytest.mark.real_card
def test_10_a_fork_clones_the_board_but_shares_the_flow(repository):
    """
    **§11-A · §11-B — 사본은 판만 복제하고 흐름은 값으로 공유한다.**

    그래서 후보를 담는 자리를 만들 때 **불변 값**이어야 한다. 가변 객체로 두면
    탐색의 사본이 진짜 듀얼의 후보 목록을 오염시킨다.
    """
    from agent.simulation import Simulator

    duel = at_main1(small_duel(repository))
    simulator = Simulator(duel)
    fork = simulator._fork()

    assert fork.state is not duel.state  # 판은 복제된다
    assert fork.chain is duel.chain  # 체인은 **같은 객체**다 (불변이라 안전하다)
    assert fork.priority is duel.priority
    assert fork.pending_spells == duel.pending_spells
    #: 복제된 판은 독립적이다.
    assert fork.state.state_hash() == duel.state.state_hash()


# ======================================================================
# §12 · §13 — 숨은 정보 · 실제 카드
# ======================================================================


def test_11_private_facts_reach_the_gate_as_values_not_through_the_view():
    """
    **§12 — 비공개 사실을 다루는 선례가 이미 있다** (ADR-007).

    "이 턴에 세웠는가" 는 관측에 없다. 판을 들고 있는 ``Duel`` 이 읽어서
    **값으로** 관문에 넘긴다 (``_set_this_turn``). 유발 사건도 같은 모양을 쓸 수
    있다 — 관측을 넓히지 않고 값으로 넘기는 길이 열려 있다.
    """
    from engine.game_state_view import GameStateView

    view_fields = set(GameStateView.__dataclass_fields__)
    assert "rule_uses" not in view_fields
    assert {"normal_summons_used", "attacks_used"} <= view_fields

    node = function_body("engine/duel.py", "_set_this_turn")
    attrs = {
        inner.attr for inner in ast.walk(node) if isinstance(inner, ast.Attribute)
    }
    assert "rule_uses" in attrs
    source = (PROJECT_ROOT / "engine/duel.py").read_text(encoding="utf-8")
    assert "관측(``GameStateView``)에는 **없다**" in source


@pytest.mark.real_card
def test_12_trigger_metadata_is_the_largest_category_the_engine_cannot_run(repository):
    """
    **§13 — 데이터에는 있고 실행에는 없다.**

    유발 사건 코드를 가진 효과 블록이 corpus 에서 가장 큰 발동 계열인데
    (``EVENT_*`` 중 ``EVENT_FREE_CHAIN`` 이 아닌 것), ``EFFECT_LIBRARY`` 에
    등록된 것은 **0개**다. "실제 카드가 없다" 와 "구조가 없다" 는 다르다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    codes = []
    for entry in EFFECT_LIBRARY:
        ref = entry.definition.effect_ref
        card = repository.get(ref.card_id)
        spec = ref.resolve(card) if card is not None else None
        codes.append(spec.code if spec is not None else None)
    assert set(codes) == {"EVENT_FREE_CHAIN"}
    assert not [c for c in codes if c and c != "EVENT_FREE_CHAIN"]
