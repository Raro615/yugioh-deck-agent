"""
Phase 3-F-10 — ``TimingEvent.actor`` 와 ``EventContext.actor`` 의 **역할 분리**
감사.

이 파일이 답하는 단 하나의 질문
-------------------------------
두 필드를 **각각 어떤 의미의 actor 로 계약해야 하는가.**

측정으로 확정한 두 계약
-----------------------
``TimingEvent.actor``
    **그 변화(delta) 가 직접 가리키는 플레이어.** delta 의 사람 칸에서
    **파생**되고, 어느 칸인지는 사건군이 정한다 (3-F-9).

``EventContext.actor``
    **그 변화 묶음을 일으킨 행위의 주체로 부르는 쪽이 선언한 값.**
    ``read(result)`` 에 ``actor`` 를 주면 그것, 안 주면
    ``result.action.actor``, 그것도 없으면 ``None``.

둘의 성격이 반대다 (``test_01`` · ``test_02`` · ``test_19``)
----------------------------------------------------------
=================  ==========================  ==========================
                    ``TimingEvent.actor``        ``EventContext.actor``
=================  ==========================  ==========================
출처                delta (**파생**)              부르는 쪽 (**선언**)
뜻                  사건군마다 다르다              행위자 — **의도상**
언제 채워지는가      이름 붙은 5개 사건군           **action 경로에서만** 자동
delta 와의 일치      **언제나 일치**               **아무도 검증하지 않는다**
=================  ==========================  ==========================

🔴 실제 결함 (``test_03``)
-------------------------
**두 docstring 이 똑같은 것을 약속한다** — 둘 다 "일으킨" 이라고 적혀 있다.
그런데 하나는 당사자이고 하나는 행위자다. 즉 문서가 둘을 **구분하지
않는다.**

🟢 그런데 production 에서 **아무도 읽지 않는다** (``test_21``)
-------------------------------------------------------------
``engine/event_pipeline.py`` 와 ``engine/trigger.py`` 밖에서 사건의
``actor`` 를 읽는 production 코드가 **하나도 없다.** 그래서 지금 틀린
판정이 나오고 있지는 않다.

이 파일은 production 을 **한 줄도** 바꾸지 않는다 (``test_23``).
"""

import ast
import hashlib
import inspect
import pathlib

import pytest

from engine.action import PlayerAction
from engine.action_execution import ActionExecution
from engine.condition import ConditionContext, PlayerRef
from engine.duel import Duel
from engine.effect.delta import (
    CardDrawn,
    LifeChanged,
    MonsterSummoned,
    PhaseChanged,
    SummonKind,
    ZoneMoved,
)
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import CostPaymentEvent, EffectEvent, EventJournal
from engine.effect.library import definition_registry
from engine.effect.operation import OperationKind
from engine.effect.resolution import EffectResult, ResolutionContext
from engine.event_pipeline import EventContext, EventReader, ObservedEvent
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.summon import duel_executor
from engine.trigger import TimingEvent, TimingPoint, timing_events, timing_for
from engine.turn_progression import ProgressionResult
from engine.validation import ValidationResult
from engine.vocabulary import Phase, Position, Zone

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
POT_OF_GREED = 55144522
I = InstanceId


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from (PROJECT_ROOT / root).rglob("*.py")


def docstring_of(relative: str, class_name: str, attribute: str) -> str:
    """
    그 클래스 안에서 ``attribute`` 선언 **바로 뒤에 붙은 문자열**을 떼어낸다.

    dataclass 필드의 설명은 이 모양으로 적혀 있다 (`attr: type` 다음 줄의
    문자열 리터럴).
    """
    text = source_of(relative)
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            body = node.body
            for index, statement in enumerate(body):
                named = (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and statement.target.id == attribute
                )
                if not named:
                    continue
                following = body[index + 1] if index + 1 < len(body) else None
                if (
                    isinstance(following, ast.Expr)
                    and isinstance(following.value, ast.Constant)
                    and isinstance(following.value.value, str)
                ):
                    return following.value.value
                return ""
    raise AssertionError(f"{class_name}.{attribute} 를 찾지 못했습니다")


def method_body(relative: str, class_name: str, method: str) -> str:
    text = source_of(relative)
    for node in ast.walk(ast.parse(text)):
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
                    return "\n".join(ast.unparse(s) for s in body)
    raise AssertionError(f"{class_name}.{method} 를 찾지 못했습니다")


# ======================================================================
# 판 — 네 반례를 실제로 만든다
# ======================================================================


def live_duel(repository, *, seed: int = 3) -> Duel:
    duel = Duel.start(
        repository, decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20), seed=seed
    )
    while duel.advance() is not None:
        pass
    return duel


def summon_by(repository, actor: int):
    """``actor`` 가 특수 소환한다 — **행위가 있는** 경로."""
    duel = live_duel(repository)
    state = duel.state.clone()
    source = list(state.player(actor).hand)[0].instance_id
    action = PlayerAction.special_summon(actor=actor, source=source)
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid("감사가 직접 허가")
    )
    return state, execution


def battle_by(repository, attacker_seat: int):
    """``attacker_seat`` 가 직접 공격한다 — 3-F-9 의 반례와 같은 판."""
    duel = live_duel(repository)
    state = duel.state.clone()
    monster = list(state.player(attacker_seat).hand)[0]
    state.move(
        monster, Zone.MZONE, to_player=attacker_seat, position=Position.FACEUP_ATTACK
    )
    state.turn.turn_player = attacker_seat
    state.turn.set_phase(Phase.BATTLE)
    action = PlayerAction.attack_directly(
        actor=attacker_seat, source=monster.instance_id
    )
    #: **적용 전에** 맞는 쪽의 LP 를 읽어 둔다 — 적용 뒤에 읽으면 이미
    #: 깎인 값이고, 그러면 "줄었다" 를 확인할 수 없다 (처음에 그렇게 썼다).
    victim_before = state.player(1 - attacker_seat).life_points
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid()
    )
    return state, execution, action, victim_before


def draw_by_effect(repository, controller: int, *, journal: EventJournal | None = None):
    """욕망의 항아리를 해결한다 — **행위가 없는** 효과 경로."""
    state = GameState.create(
        repository, decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20), seed=1
    )
    state.create_instance(POT_OF_GREED, owner=controller, zone=Zone.SZONE)
    reference = EffectRef(POT_OF_GREED, 0)
    definition = definition_registry().definition_for(reference)
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((reference,)), journal=journal
    )
    result = executor.execute(
        state,
        definition,
        ResolutionContext(effect_ref=reference, controller=controller),
    )
    return state, result


def both_actors(state, result, *, viewer: int = MINE, actor=None):
    """같은 실행에서 두 ``actor`` 를 함께 읽는다."""
    view = GameStateView.from_state(state, viewer=viewer)
    reader = EventReader(view)
    observed = reader.read(result) if actor is None else reader.read(result, actor=actor)
    return [(o.point, o.actor, o.context.actor) for o in observed]


def moved(operation: OperationKind, *, owner: int, to_zone: Zone) -> ZoneMoved:
    return ZoneMoved(
        movement=operation,
        card=I(30),
        source_player=owner,
        source_zone=Zone.MZONE,
        destination_player=owner,
        destination_zone=to_zone,
    )


# ======================================================================
# A. §2 · §3 — 두 생성 경로와 두 계약
# ======================================================================


def test_01_the_timing_actor_is_derived_from_the_delta():
    """
    §2 A · §3 — ``TimingEvent.actor`` 는 **delta 에서 파생**된다.

    부르는 쪽이 끼어들 자리가 없다 — ``from_delta`` 가 delta 의 칸을 읽어
    정한다. 그래서 **언제나 delta 와 일치하고**, 대신 그 칸이 사건군마다
    다르다.
    """
    body = method_body("engine/trigger.py", "TimingEvent", "from_delta")
    assert "actor=delta.player" in body
    assert "actor=delta.to_player" in body
    #: delta 밖에서 값을 받는 통로가 없다.
    assert "actor=actor" not in body
    assert inspect.signature(TimingEvent.from_delta).parameters.keys() == {
        "cls",
        "delta",
    } or list(inspect.signature(TimingEvent.from_delta).parameters) == ["delta"]

    #: 그래서 같은 delta 는 **언제나 같은 actor** 를 준다.
    delta = LifeChanged(player=MINE, before=8000, after=6000)
    assert timing_for(delta).actor == timing_for(delta).actor == delta.player


def test_02_the_context_actor_is_declared_by_the_caller():
    """
    §2 B · §3 — ``EventContext.actor`` 는 **부르는 쪽이 선언**한다.

    세 단계로 정해진다: 넘긴 값 → ``result.action.actor`` → ``None``.
    """
    read = method_body("engine/event_pipeline.py", "EventReader", "read")
    #: 넘기지 않으면 **행위에서** 가져온다.
    assert "action" in read and "actor" in read
    assert "if actor is None" in read.replace("\n", " ") or "actor is None" in read

    of_body = method_body("engine/event_pipeline.py", "EventContext", "of")
    assert "actor=actor" in of_body

    #: `.action` 을 갖는 결과는 **하나**뿐이다 — 그래서 자동 충전은
    #: action 경로에서만 일어난다.
    assert "action" in ActionExecution.__dataclass_fields__
    assert "action" not in EffectResult.__dataclass_fields__
    assert "action" not in ProgressionResult.__dataclass_fields__

    #: 그리고 그 값은 0/1/None 만 받는다.
    assert EventContext(1, MINE, Phase.MAIN1, actor=None).actor is None
    with pytest.raises(ValueError):
        EventContext(1, MINE, Phase.MAIN1, actor=2)


def test_03_the_two_contracts_are_written_down_and_differ(repository):
    """
    **두 actor 의 계약이 서로 다르고, 그 다름이 문서에 적혀 있다.**

    .. note::
       **이 테스트는 Phase 3-F-10 에서 다른 것을 단정하고 있었다.**

       그때 이름은 ``test_03_both_docstrings_promise_the_same_thing`` 이고,
       두 설명에 **"일으킨" 이 둘 다 들어 있다**는 것을 근거로 "두 설명이
       똑같은 것을 약속한다" 고 적었다. 그 결론은 **그때도 너무 강했다.**

       * ``EventContext.actor`` 는 "일으킨 **행위의 주체**" 라고 적혀
         있었고 그것은 **맞는 설명**이었다 (행위자).
       * 틀린 것은 ``TimingEvent.actor`` 쪽 하나였다 — "이 **사건을**
         일으킨 플레이어" 라고 적어 **행위자라고 단정**했다.
       * 그리고 3-F-10 은 ``ObservedEvent.actor`` 의 **자기 docstring 을
         읽지 않았다.** 그 자리는 이미 "'누가 이 행위를 했는가' 와 '이
         사건이 누구의 것인가' 는 다른 질문이다" 라고 **구분해 두고
         있었다.**

       즉 결함은 "둘 다 틀렸다" 가 아니라 **"하나가 거짓이고, 구분은 세
       번째 자리에만 적혀 있었다"** 였다. Phase 3-F-11 이 그 한 문장을
       고쳤으므로, 이 테스트는 **고쳐진 계약**을 고정하는 쪽으로 바꾼다.

    §8 이 요구한 세 가지를 확인한다 — 같을 수 있고, 다를 수 있고, 달라도
    각자의 계약을 만족하면 정상이다.
    """
    timing_doc = docstring_of("engine/trigger.py", "TimingEvent", "actor")
    context_doc = docstring_of("engine/event_pipeline.py", "EventContext", "actor")

    #: ① ``TimingEvent.actor`` 는 **행위자라고 단정하지 않는다.**
    assert "귀속" in timing_doc
    assert "행위의 주체가 아니다" in timing_doc
    #: 금지된 단정이 사라졌다.
    assert "이 사건을 일으킨 플레이어" not in timing_doc
    #: 그리고 어느 쪽을 써야 하는지 가리킨다.
    assert "EventContext" in timing_doc

    #: ② ``EventContext.actor`` 는 **행위의 주체**라고 적고, 선언이라는
    #:    사실과 ``None`` 이 되는 두 까닭을 밝힌다.
    assert "행위의 주체" in context_doc
    assert "부르는 쪽이 선언" in context_doc
    assert "EffectResult" in context_doc
    assert "맞춰 보지 않는다" in context_doc

    #: ③ 세 번째 자리는 **원래부터** 구분해 두었다 — 그대로 둔다 (§5 A).
    observed_doc = inspect.getdoc(inspect.getattr_static(ObservedEvent, "actor").fget)
    assert "다른 질문이다" in observed_doc

    #: A. 두 actor 가 **같을 수 있다** — 소환.
    state, execution = summon_by(repository, MINE)
    point, timing_actor, context_actor = both_actors(state, execution)[0]
    assert point is TimingPoint.MONSTER_SUMMONED
    assert (timing_actor, context_actor) == (MINE, MINE)

    #: B. 두 actor 가 **다를 수 있다** — P1 이 P0 을 공격.
    state, execution, action, victim_before = battle_by(repository, THEIRS)
    life = [
        row for row in both_actors(state, execution) if row[0] is TimingPoint.LIFE_CHANGED
    ]
    assert len(life) == 1
    _, timing_actor, context_actor = life[0]
    assert timing_actor != context_actor

    #: C. 달라도 **각자의 계약을 만족한다.**
    #:    - context 쪽은 행위의 주체다.
    assert context_actor == action.actor
    #:    - timing 쪽은 변화가 귀속된 쪽이다 (= LP 가 줄어든 플레이어).
    assert timing_actor == MINE
    assert state.player(MINE).life_points < victim_before
    #:    그래서 "다르다" 가 결함이 아니다 — **둘이 다른 질문에 답한 것**이다.


# ======================================================================
# B. §4 · §5 — 사건별 비교
# ======================================================================


def test_04_a_summon_makes_the_two_actors_agree(repository):
    """
    §5 A — 소환은 **값도 뜻도 같다.** 소환한 사람이 곧 행위자다.

    그래도 "같은 값" 과 "같은 뜻" 은 다르다 — 여기서는 우연이 아니라
    두 계약이 같은 사람을 가리키는 경우다.
    """
    for actor in (MINE, THEIRS):
        state, execution = summon_by(repository, actor)
        rows = both_actors(state, execution)
        assert len(rows) == 1
        point, timing_actor, context_actor = rows[0]
        assert point is TimingPoint.MONSTER_SUMMONED
        assert timing_actor == context_actor == actor
        assert execution.action.actor == actor


def test_05_an_effect_draw_leaves_the_context_actor_empty(repository):
    """
    🔴 §4 2 — **효과 경로에서는 `context.actor` 가 비어 있다.**

    실제 카드(욕망의 항아리)를 해결했다. ``EffectResult`` 에 ``.action`` 이
    없으므로 자동 충전이 일어나지 않는다.
    """
    state, result = draw_by_effect(repository, MINE)
    assert result.status.value == "resolved"
    assert [type(d).__name__ for d in result.deltas] == ["CardDrawn", "CardDrawn"]

    #: 넘기지 않으면 `None` 이다.
    for point, timing_actor, context_actor in both_actors(state, result):
        assert point is TimingPoint.CARD_DRAWN
        assert timing_actor == MINE        # 뽑은 사람 — delta 에서 파생
        assert context_actor is None       # **비어 있다**

    #: 부르는 쪽이 controller 를 말해 주면 채워진다.
    for _, timing_actor, context_actor in both_actors(state, result, actor=MINE):
        assert timing_actor == MINE and context_actor == MINE


def test_06_a_battle_makes_the_two_actors_disagree(repository):
    """
    🔴 §5 C · §6 — **가장 강한 반례.** P1 이 P0 을 공격한다.

    ======================  =====
    ``action.actor``         P1
    ``context.actor``        P1     ← 행동한 쪽
    ``timing.actor``         P0     ← LP 가 변한 쪽
    피해 대상                 P0
    ======================  =====
    """
    state, execution, action, before = battle_by(repository, THEIRS)

    rows = [
        (point, timing_actor, context_actor)
        for point, timing_actor, context_actor in both_actors(state, execution)
        if point is TimingPoint.LIFE_CHANGED
    ]
    assert len(rows) == 1
    _, timing_actor, context_actor = rows[0]

    assert action.actor == THEIRS
    assert context_actor == THEIRS      # 행위자
    assert timing_actor == MINE         # 당사자
    assert timing_actor != context_actor
    assert state.player(MINE).life_points < before

    #: "상대가 나를 공격했다" 를 판단하려면 **context 쪽**이 필요하다.
    relation_from_context = (
        "OPPONENT"
        if context_actor == PlayerRef.OPPONENT.resolve(ConditionContext(player=MINE))
        else "SELF"
    )
    relation_from_timing = "SELF" if timing_actor == MINE else "OPPONENT"
    assert relation_from_context == "OPPONENT"   # 맞다
    assert relation_from_timing == "SELF"        # **틀리다**


def test_07_a_card_moved_to_the_opponent_field_has_no_action_at_all():
    """
    §5 D · §8 — 카드가 상대 필드로 가는 사건은 지금 **행위 경로가 없다.**

    그래서 `timing.actor` 만 있고(도착지 주인), `context.actor` 는 부르는
    쪽이 말해 주어야 한다. 다섯 개념이 사건에 어떻게 흩어져 있는지 센다.
    """
    delta = ZoneMoved(
        movement=OperationKind.MOVE,
        card=I(9),
        source_player=MINE,
        source_zone=Zone.MZONE,
        destination_player=THEIRS,
        destination_zone=Zone.MZONE,
    )
    event = timing_for(delta)

    #: source player / destination player 는 delta 가 들고 있다.
    assert delta.source_player == MINE
    assert delta.destination_player == THEIRS
    #: `timing.actor` 는 **도착지**를 고른다.
    assert event.actor == THEIRS
    #: actual action player 를 담을 칸이 delta 에 **없다.**
    assert not {
        name for name in ZoneMoved.__dataclass_fields__ if "actor" in name
    }
    #: 그래서 "상대가 내 필드로 옮겼다" 와 "카드가 상대 필드로 갔다" 가
    #: delta 만으로는 구분되지 않는다 — 두 경우의 delta 가 같다.
    assert event.actor == delta.destination_player


def test_08_destroy_banish_discard_and_return_share_the_timing_rule():
    """
    §4 5~9 — 네 "사건" 이 전부 ``ZoneMoved`` 이므로 `timing.actor` 규칙이
    하나다. 그리고 넷 다 지금 **행위 경로가 없다** — `context.actor` 는
    선언에 달려 있다.
    """
    cases = {
        "CardDestroyed": (OperationKind.DESTROY, Zone.GRAVE),
        "CardAddedToHand": (OperationKind.RETURN_TO_HAND, Zone.HAND),
        "CardDiscarded": (OperationKind.DISCARD, Zone.GRAVE),
        "CardBanished": (OperationKind.BANISH, Zone.REMOVED),
        "CardReturned": (OperationKind.RETURN_TO_DECK, Zone.DECK),
    }
    for label, (operation, to_zone) in cases.items():
        for owner in (MINE, THEIRS):
            event = timing_for(moved(operation, owner=owner, to_zone=to_zone))
            assert event.point is TimingPoint.CARD_MOVED, label
            assert event.actor == owner, label
            assert event.operation is operation, label
    #: 다섯 이름이 **한 시점 · 한 규칙**으로 들어온다.
    assert len({
        timing_for(moved(op, owner=MINE, to_zone=z)).point
        for op, z in cases.values()
    }) == 1


def test_09_phase_changed_has_neither_actor(repository):
    """
    §4 10·11 — 페이즈(와 턴) 전이는 **둘 다 비어 있다.**

    `timing.actor` 는 일부러 적지 않고, 규칙 진행 결과에는 `.action` 이
    없으므로 `context.actor` 도 자동으로 차지 않는다.
    """
    delta = PhaseChanged(
        from_turn=1,
        from_player=MINE,
        from_phase=Phase.MAIN1,
        to_turn=2,
        to_player=THEIRS,
        to_phase=Phase.DRAW,
    )
    event = timing_for(delta)
    assert event.point is TimingPoint.PHASE_CHANGED
    assert event.actor is None
    #: 턴 변화가 이 사건 **안에** 있다 — 별도 클래스가 아니다.
    assert (delta.from_turn, delta.to_turn) == (1, 2)

    #: 규칙 진행 결과에는 행위가 없다.
    assert "action" not in ProgressionResult.__dataclass_fields__
    #: `EventContext.__str__` 는 `None` 을 **"규칙"** 으로 읽는다 — 그것이
    #: 이 필드가 **행위자**를 뜻한다는 증거다.
    assert "규칙" in EventContext(1, MINE, Phase.MAIN1).__str__()


def test_10_the_two_actors_can_agree_by_value_but_differ_by_meaning(repository):
    """
    §4 의 핵심 주의 — **"같은 값" 과 "같은 뜻" 을 가른다.**

    소환에서는 둘이 같은 값이다. 그래도 계약은 다르다 — 하나는 delta 에서
    파생되고 하나는 선언된 것이며, **선언을 바꾸면 값이 갈라진다.**
    """
    state, execution = summon_by(repository, MINE)
    #: 같은 실행을 **다른 선언**으로 읽으면 갈라진다.
    agreed = both_actors(state, execution)
    declared_wrong = both_actors(state, execution, actor=THEIRS)

    assert agreed[0][1] == agreed[0][2] == MINE
    assert declared_wrong[0][1] == MINE       # 파생 — 그대로다
    assert declared_wrong[0][2] == THEIRS     # 선언 — 바뀐다
    #: 즉 값의 일치는 **우연일 수 있고**, 계약이 다르다는 사실은 남는다.
    assert declared_wrong[0][1] != declared_wrong[0][2]


# ======================================================================
# C. §7 · §8 — affected / cause / source / destination
# ======================================================================


def test_11_neither_actor_is_the_cause_of_a_life_change_by_effect(repository):
    """
    🔴 §7 — ``LifeChanged`` 의 **원인**을 묻는다.

    ============  ===================================  ==============
    affected      LP 가 실제로 변한 플레이어              `timing.actor`
    cause         LP 변화를 발생시킨 플레이어             **전투에서만**
                                                       `context.actor`
    ============  ===================================  ==============

    전투에서는 `context.actor` 가 원인을 들고 있다 (`test_06`). 그런데
    **효과로 LP 가 바뀌면** `context.actor` 가 기본 `None` 이므로
    (``EffectResult`` 에 행위가 없다) **둘 중 어느 것도 원인을 주지
    않는다.**
    """
    #: 효과 경로를 실제로 돌려 `context.actor` 가 비는 것을 확인한다
    #: (드로우로 확인하지만 결과 종류가 같으므로 LP 변화도 같다).
    state, result = draw_by_effect(repository, MINE)
    assert all(context is None for _, _, context in both_actors(state, result))

    #: `LifeChanged` 자신에 원인 칸이 없다.
    assert set(LifeChanged.__dataclass_fields__) == {"player", "before", "after"}
    #: 그리고 `timing.actor` 는 affected 쪽이다.
    hurt = LifeChanged(player=MINE, before=8000, after=6000)
    assert timing_for(hurt).actor == hurt.player


def test_12_the_effect_agent_lives_on_a_sibling_event(repository):
    """
    🟡 §7 의 보완 — **원인이 아주 없는 것은 아니다. 다른 사건에 있다.**

    효과 해결은 ``EffectEvent`` 로 기록되고 그 ``actor`` 가 효과의
    컨트롤러다. ``timing_events`` 가 그것을 ``EFFECT_RESOLVED`` 라는
    **별개 사건**의 ``actor`` 로 내놓는다 — delta 가 만든 사건과 같은
    사건이 아니다.
    """
    journal = EventJournal()
    state, result = draw_by_effect(repository, MINE, journal=journal)
    assert result.status.value == "resolved"
    assert len(journal.events) == 1

    recorded = journal.events[0]
    assert isinstance(recorded, EffectEvent)
    assert recorded.actor == MINE          # 효과의 **행위자**

    points = [(e.point, e.actor) for e in timing_events(recorded)]
    #: delta 쪽 사건들 뒤에 효과 해결 사건이 온다.
    assert points[-1] == (TimingPoint.EFFECT_RESOLVED, MINE)
    assert [p for p, _ in points[:-1]] == [
        TimingPoint.CARD_DRAWN,
        TimingPoint.CARD_DRAWN,
    ]
    #: 즉 행위자는 **세 번째 자리**에 있다 — delta 도 context 도 아니다.
    assert any(p is TimingPoint.EFFECT_RESOLVED for p, _ in points)
    #: 비용 지불도 같은 모양의 자리를 갖는다.
    assert "actor" in CostPaymentEvent.__dataclass_fields__


def test_13_source_and_destination_are_both_readable_but_the_agent_is_not():
    """
    §8 — ``ZoneMoved`` 의 다섯 개념 가운데 **넷은 읽을 수 있다.**

    없는 하나가 "actual action player" 이고, 그것이 `context.actor` 가
    채워질 때만 생긴다.
    """
    delta = moved(OperationKind.DESTROY, owner=THEIRS, to_zone=Zone.GRAVE)
    event = timing_for(delta)

    readable = {
        "source player": delta.source_player,
        "destination player": delta.destination_player,
        "card": event.instance,
        "operation": event.operation,
    }
    assert all(value is not None for value in readable.values())
    #: `timing.actor` 가 그 넷 중 **도착지**와 같다.
    assert event.actor == delta.destination_player
    #: 그리고 행위자는 그 넷에 없다.
    assert event.actor != "actual action player"


# ======================================================================
# D. §10 — EventRelation 은 어느 쪽을 써야 하는가
# ======================================================================


def test_14_the_relation_needs_the_context_actor_not_the_timing_actor(repository):
    """
    §10 — 여덟 사례에서 **어느 actor 가 올바른 관계를 주는가.**

    소환 · 드로우는 둘 다 맞는다. **데미지는 context 만 맞는다.**
    3-F-8 이 정한 최소 입력의 player relation 은 그러므로
    ``context.actor`` 쪽에서 와야 한다.
    """
    def relation(actor, controller) -> str:
        if actor is None:
            return "UNKNOWN"
        if actor == controller:
            return "SELF"
        if actor == PlayerRef.OPPONENT.resolve(ConditionContext(player=controller)):
            return "OPPONENT"
        return "UNREACHABLE"  # pragma: no cover - 2인 게임에서는 닿지 않는다

    #: 1·2 — 내가 / 상대가 소환
    for actor, expected in ((MINE, "SELF"), (THEIRS, "OPPONENT")):
        state, execution = summon_by(repository, actor)
        _, timing_actor, context_actor = both_actors(state, execution)[0]
        assert relation(timing_actor, MINE) == expected
        assert relation(context_actor, MINE) == expected

    #: 5 — 상대가 나에게 데미지. **둘이 갈린다.**
    state, execution, _, _ = battle_by(repository, THEIRS)
    life = [
        row for row in both_actors(state, execution) if row[0] is TimingPoint.LIFE_CHANGED
    ]
    _, timing_actor, context_actor = life[0]
    assert relation(timing_actor, MINE) == "SELF"        # **틀리다**
    assert relation(context_actor, MINE) == "OPPONENT"   # 맞다

    #: 6 — 내가 상대에게 데미지. 역시 context 가 맞는다.
    state, execution, _, _ = battle_by(repository, MINE)
    life = [
        row for row in both_actors(state, execution, viewer=MINE)
        if row[0] is TimingPoint.LIFE_CHANGED
    ]
    _, timing_actor, context_actor = life[0]
    assert relation(timing_actor, MINE) == "OPPONENT"    # **틀리다**
    assert relation(context_actor, MINE) == "SELF"       # 맞다


def test_15_the_relation_is_unknown_when_the_context_actor_is_absent(repository):
    """
    §10 — ``context.actor`` 를 쓰기로 하면 **효과 경로가 `UNKNOWN` 이 된다.**

    그것이 잘못된 `SELF` 보다 **옳다** — 모르는 것을 모른다고 적는다.
    """
    state, result = draw_by_effect(repository, MINE)
    rows = both_actors(state, result)
    assert rows and all(context is None for _, _, context in rows)

    def relation(actor, controller) -> str:
        return "UNKNOWN" if actor is None else ("SELF" if actor == controller else "OPPONENT")

    for _, timing_actor, context_actor in rows:
        assert relation(context_actor, MINE) == "UNKNOWN"
        #: timing 쪽은 값이 있어서 `SELF` 를 주지만, 그 값은 **당사자**다.
        assert relation(timing_actor, MINE) == "SELF"


def test_16_an_absent_actor_must_not_be_read_as_opponent():
    """§10 — `None` 을 "상대" 로 접지 않는다 (3-F-8 이 고정한 설계 요구)."""
    for actor in (None,):
        assert actor != MINE and actor != THEIRS
        for player in (MINE, THEIRS):
            assert (actor is not None and actor != player) is False


# ======================================================================
# E. §9 · §11 — consumer 와 이름
# ======================================================================


def test_17_the_observed_event_exposes_the_timing_actor_under_the_bare_name():
    """
    🔴 §11 — **이름이 위험한 자리.**

    ``ObservedEvent.actor`` 는 **`timing` 쪽**을 돌려준다. 그래서
    ``event.actor`` 라고 쓰면 당사자가 오고, 행위자를 받으려면
    ``event.context.actor`` 라고 써야 한다. **짧은 이름이 덜 안전한 값을
    가리킨다.**
    """
    body = method_body("engine/event_pipeline.py", "ObservedEvent", "actor")
    assert body.strip() == "return self.timing.actor"
    #: 사건 종류를 보지 않는다.
    assert "point" not in body and "isinstance" not in body

    #: 두 값이 모두 노출되어 있다 — 고를 수는 있다.
    assert "timing" in ObservedEvent.__dataclass_fields__
    assert "context" in ObservedEvent.__dataclass_fields__
    assert isinstance(
        inspect.getattr_static(ObservedEvent, "actor"), property
    )


def test_18_no_production_consumer_reads_either_actor():
    """
    🟢 §9 — **production 에서 아무도 읽지 않는다.**

    그래서 지금 틀린 판정이 나오고 있지 않다. 이것이 판정을
    "consumer misuse" 가 아니라 "계약 문서화" 로 만드는 근거다.
    """
    readers = []
    for path in production_files():
        relative = str(path.relative_to(PROJECT_ROOT))
        if relative in ("engine/event_pipeline.py", "engine/trigger.py"):
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("event.actor", "timing.actor", "context.actor"):
            if needle in text:
                readers.append((relative, needle))
    assert readers == [], readers

    #: live 경로도 dormant 경로도 읽지 않는다.
    for relative in (
        "engine/duel.py",
        "engine/timing.py",
        "engine/trigger_order.py",
        "engine/trigger_chain.py",
        "engine/activation.py",
        "engine/activation_timing.py",
    ):
        text = source_of(relative)
        assert "event.actor" not in text, relative
        assert "timing.actor" not in text, relative

    #: `event_pipeline` 자체가 여전히 production importer 0 이다.
    importers = [
        str(path.relative_to(PROJECT_ROOT))
        for path in production_files()
        if path.name != "event_pipeline.py"
        and (
            "from engine.event_pipeline import" in path.read_text(encoding="utf-8")
            or "import engine.event_pipeline" in path.read_text(encoding="utf-8")
        )
    ]
    assert importers == []


def test_19_nothing_checks_the_declared_actor_against_the_delta(repository):
    """
    🔴 §9 — ``context.actor`` 는 **검증되지 않는다.**

    delta 와 **모순되는** 값을 넣어도 아무도 막지 않는다. 즉 그 필드의
    정확성은 **부르는 쪽의 책임**이고, 그 책임이 어디에도 적혀 있지 않다.
    """
    state, execution = summon_by(repository, MINE)
    #: 소환한 사람은 P0 인데 P1 이라고 선언한다.
    rows = both_actors(state, execution, actor=THEIRS)
    assert rows[0][1] == MINE        # delta 는 P0 이라고 말한다
    assert rows[0][2] == THEIRS      # 선언은 P1 — **거절되지 않는다**

    #: `EventContext` 는 범위만 본다 (0/1/None).
    post_init = method_body("engine/event_pipeline.py", "EventContext", "__post_init__")
    assert "actor" in post_init
    assert "delta" not in post_init
    #: `read_deltas` 도 delta 와 비교하지 않는다.
    read_deltas = method_body("engine/event_pipeline.py", "EventReader", "read_deltas")
    assert "actor=actor" in read_deltas
    assert "delta.player" not in read_deltas


# ======================================================================
# F. 경계 보존 (§13 · §14 · §15)
# ======================================================================


def test_20_reading_both_actors_touches_no_hidden_information(repository):
    """§13 — 둘 다 공개 정보이고 관측 경계를 넓히지 않는다."""
    state, execution, _, _ = battle_by(repository, THEIRS)
    view = GameStateView.from_state(state, viewer=MINE)
    for event in EventReader(view).read(execution):
        assert event.actor in (None, MINE, THEIRS)
        assert event.context.actor in (None, MINE, THEIRS)

    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(THEIRS).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()


def test_21_the_state_and_the_rng_do_not_move(repository):
    """§14 — 두 actor 를 읽어도 판도 난수도 그대로다."""
    state, execution, _, _ = battle_by(repository, THEIRS)
    before_hash, before_rng = state.state_hash(), repr(state.rng)
    view = GameStateView.from_state(state, viewer=MINE)
    for _ in range(3):
        EventReader(view).read(execution)
        for delta in execution.deltas:
            timing_for(delta)
    assert state.state_hash() == before_hash
    assert repr(state.rng) == before_rng


def test_22_no_new_field_was_added():
    """
    §12 — 새 field 를 **만들지 않았다.** 후보 다섯을 기존 구조와 맞춰 본다.

    ====================  ==========================================
    `cause_player`         전투는 `context.actor` 가 준다 · 효과는
                          ``EffectEvent.actor`` 가 준다 → **새 칸 불필요**
    `affected_player`      `timing.actor` 가 이미 그것이다
    `destination_player`   ``ZoneMoved`` 에 **이미 있다**
    `source_player`        ``ZoneMoved`` 에 **이미 있다**
    `controller`           후보 쪽 값이다 (3-F-8)
    ====================  ==========================================
    """
    assert "cause_player" not in LifeChanged.__dataclass_fields__
    assert "affected_player" not in LifeChanged.__dataclass_fields__
    assert set(LifeChanged.__dataclass_fields__) == {"player", "before", "after"}

    #: 넷째·다섯째는 이미 있다.
    assert {"source_player", "destination_player"} <= set(
        ZoneMoved.__dataclass_fields__
    )
    #: 사건 쪽 필드 수가 그대로다.
    assert len(TimingEvent.__dataclass_fields__) == 5
    assert len(EventContext.__dataclass_fields__) == 5
    assert list(EventContext.__dataclass_fields__) == [
        "turn_number",
        "turn_player",
        "phase",
        "actor",
        "sequence",
    ]


def test_23_this_phase_changed_nothing(repository):
    """§14 · §15 — 구조 불변 · 순위 digest 불변."""
    assert list(TimingEvent.__dataclass_fields__) == [
        "point",
        "delta",
        "effect_ref",
        "actor",
        "note",
    ]
    assert len(list(TimingPoint)) == 8
    duel_source = source_of("engine/duel.py")
    for absent in ("TriggerRegistry", "engine.timing", "engine.event_pipeline"):
        assert absent not in duel_source, absent

    from agent.runner import DuelRunner
    from agent.search import search_policy

    deck = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [5915629] * 4
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
