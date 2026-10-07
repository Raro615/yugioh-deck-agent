"""
Phase 3-F-12 — ``EventContext.actor`` 의 **provenance** 와 **None 경계** 감사.

이 파일이 답하는 단 하나의 질문
-------------------------------
Phase 3-F-11 이 고정한 계약 —

    ``EventContext.actor`` = 이 변화를 일으킨 **행위의 주체**이고,
    **부르는 쪽이 선언**한다 (넘긴 값 → ``result.action.actor`` → ``None``)

— 이 **실제 production 실행 경로**에서 성립하는가. 성립하지 않는 자리가
있다면 그것이 **의도된 ``None``** 인가 **빠진 actor** 인가.

측정으로 나온 것 (요지)
-----------------------
1. ``EventContext`` 를 만드는 production 자리는 **두 곳뿐**이고 둘 다
   ``engine/event_pipeline.py`` 안이다. 값을 **받는** 자리는 ``of`` 하나다.
2. ``PlayerAction.actor`` 는 **절대 ``None`` 이 되지 않는다** (필수 ``int``,
   0/1 검증). 그래서 행위가 있는 경로에서는 actor 가 비지 않는다.
3. 🔴 **delta 를 들고 있는 production result 는 7개다.** 그중 ``.action`` 을
   가진 것은 **둘** (``ActionExecution`` · ``ActivationResult``) — 3-F-10 ·
   3-F-11 이 "``ActionExecution`` 하나뿐" 이라 적은 것은 **덜 센 것**이었다.
4. 🔴 ``EffectEvent`` · ``CostPaymentEvent`` 는 ``actor`` 를 **자기 칸에 직접
   들고 있는데** ``read()`` 가 그 칸을 **보지 않는다** — ``.action`` 만 본다.
   정보가 객체에 있는데 떨어진다.
5. 🔴 ``read()`` 로는 **"actor 가 없다" 를 선언할 수 없다.**
   ``actor=None`` 은 "안 넘긴 것" 과 구별되지 않아서 언제나 fallback 이
   이긴다. ``read_deltas`` 는 표현할 수 있다 — 두 메서드의 표현력이 다르다.
6. ``EventContext.actor is None`` 에는 **까닭이 적히지 않는다.** 의도된
   ``None`` 과 빠진 actor 가 **같은 값**으로 나온다.
7. live 경로는 ``DuelStep`` 에서 끊긴다 — ``deltas`` 도 ``ActionExecution``
   도 보관하지 않는다. 그런데 그 둘은 **같은 함수의 지역변수**로 동시에
   존재한다.

이 파일은 production 을 **한 줄도** 바꾸지 않는다 (``test_22``).
"""

import ast
import dataclasses
import importlib
import inspect
import pathlib
import pkgutil
import subprocess
import sys

import pytest

import engine
from engine.action import PlayerAction
from engine.action_execution import ActionExecution
from engine.activation import ActivationResult, EffectActivator
from engine.chain import Chain
from engine.duel import Duel, DuelStep
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import CostPaymentEvent, EffectEvent, EventJournal
from engine.effect.library import definition_registry
from engine.effect.resolution import EffectResult, ResolutionContext
from engine.event_pipeline import EventContext, EventReader, ObservedEvent
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.payment import CostPaymentResult, PaymentContext
from engine.state.game_state import GameState
from engine.summon import duel_executor
from engine.trigger import TimingPoint
from engine.turn_progression import (
    PhaseTransition,
    ProgressionResult,
    TransitionPlan,
    TurnProgressor,
)
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


# ======================================================================
# 측정 도구 — 문자열이 아니라 AST 로 센다
# ======================================================================


def source_of(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from (PROJECT_ROOT / root).rglob("*.py")


def method_code(relative: str, class_name: str, method: str) -> str:
    """
    메서드 본문을 **docstring 을 떼고** 돌려준다.

    .. note::
       3-F-7 에서 docstring 을 그대로 두고 문자열을 찾았다가, 설명에 적힌
       말을 코드로 착각했다. 그 뒤로는 반드시 떼고 센다.
    """
    for node in ast.walk(ast.parse(source_of(relative))):
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


def method_doc(relative: str, class_name: str, method: str) -> str:
    for node in ast.walk(ast.parse(source_of(relative))):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method:
                    return ast.get_docstring(child) or ""
    raise AssertionError(f"{class_name}.{method} 를 찾지 못했습니다")


def prose_lines(relative: str) -> set[int]:
    """
    그 파일에서 **문자열 리터럴이 차지하는 줄 번호** 전부.

    "코드에 있는가" 와 "설명에 적혀 있는가" 를 가르는 데 쓴다 — 줄 번호를
    고정하지 않고 **성격**을 고정한다 (Phase 3-F-11 에서 줄 번호 snapshot 이
    docstring 때문에 줄줄이 깨졌다).
    """
    lines: set[int] = set()
    for node in ast.walk(ast.parse(source_of(relative))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            start = node.lineno
            end = getattr(node, "end_lineno", start) or start
            lines.update(range(start, end + 1))
    return lines


def construction_sites(name: str) -> dict[str, int]:
    """
    ``name(...)`` 을 **호출 노드로** 센다 — 정규식이 자기 소스를 세는 사고를
    피한다 (3-F-8 에서 실제로 당했다).
    """
    found: dict[str, int] = {}
    for path in production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
        )
        if count:
            found[str(path.relative_to(PROJECT_ROOT))] = count
    return found


def every_delta_bearing_result() -> dict[str, tuple[bool, bool]]:
    """
    ``deltas`` 칸을 가진 production dataclass 전수 → (``.action`` 있음,
    ``.actor`` 있음).

    .. note::
       **``engine`` 전체를 import 해야 전수가 된다** (3-F-9 의 교훈).
       ``engine.battle`` 처럼 아무도 import 하지 않는 모듈 안의 클래스는
       ``__subclasses__`` 로도, 이 파일의 import 로도 보이지 않는다.
    """
    for module in pkgutil.walk_packages(engine.__path__, prefix="engine."):
        try:
            importlib.import_module(module.name)
        except Exception:  # pragma: no cover - 측정이 끊기지 않게 한다
            continue
    rows: dict[str, tuple[bool, bool]] = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith("engine"):
            continue
        for attribute in dir(module):
            obj = getattr(module, attribute, None)
            if not isinstance(obj, type) or not dataclasses.is_dataclass(obj):
                continue
            fields = {f.name for f in dataclasses.fields(obj)}
            if "deltas" in fields:
                rows[f"{obj.__module__}.{obj.__name__}"] = (
                    "action" in fields,
                    "actor" in fields,
                )
    return rows


# ======================================================================
# 판 — 실제 카드로 만든다
# ======================================================================


def live_duel(repository, *, seed: int = 3) -> Duel:
    duel = Duel.start(
        repository, decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20), seed=seed
    )
    while duel.advance() is not None:
        pass
    return duel


def read_with(state, result, *, viewer: int = MINE, **kwargs):
    view = GameStateView.from_state(state, viewer=viewer)
    return EventReader(view).read(result, **kwargs)


def summon(repository, actor: int, kind: str = "special_summon"):
    """``actor`` 가 소환한다 — **행위가 있는** 경로."""
    duel = live_duel(repository)
    state = duel.state.clone()
    state.turn.turn_player = actor
    state.turn.set_phase(Phase.MAIN1)
    source = list(state.player(actor).hand)[0].instance_id
    action = getattr(PlayerAction, kind)(actor=actor, source=source)
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid("감사가 직접 허가")
    )
    return state, execution


def battle(repository, attacker: int):
    """3-F-9 ~ 3-F-11 과 **같은 반례** — P1 이 P0 을 직접 공격한다."""
    duel = live_duel(repository)
    state = duel.state.clone()
    monster = list(state.player(attacker).hand)[0]
    state.move(
        monster, Zone.MZONE, to_player=attacker, position=Position.FACEUP_ATTACK
    )
    state.turn.turn_player = attacker
    state.turn.set_phase(Phase.BATTLE)
    action = PlayerAction.attack_directly(actor=attacker, source=monster.instance_id)
    #: 적용 **전에** 읽어 둔다 — 뒤에 읽으면 이미 깎인 값이다 (3-F-10 에서
    #: 실제로 그렇게 썼다가 틀렸다).
    victim_before = state.player(1 - attacker).life_points
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid()
    )
    return state, execution, action, victim_before


def effect_draw(repository, controller: int, *, journal: EventJournal | None = None):
    """욕망의 항아리를 해결한다 — **행위를 들고 있지 않은** 결과."""
    state = GameState.create(
        repository, decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20), seed=1
    )
    state.create_instance(POT_OF_GREED, owner=controller, zone=Zone.SZONE)
    reference = EffectRef(POT_OF_GREED, 0)
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((reference,)), journal=journal
    )
    result = executor.execute(
        state,
        definition_registry().definition_for(reference),
        ResolutionContext(effect_ref=reference, controller=controller),
    )
    return state, result


def activation(repository, actor: int):
    """발동 하나 — ``ActivationResult`` 를 얻는다."""
    state = GameState.create(
        repository, decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20), seed=1
    )
    card = state.create_instance(POT_OF_GREED, owner=actor, zone=Zone.SZONE)
    reference = EffectRef(POT_OF_GREED, 0)
    action = PlayerAction.activate_effect(
        actor=actor, source=card.instance_id, effect_ref=reference
    )
    activator = EffectActivator(
        definition_registry(), EffectImplementationRegistry((reference,))
    )
    result = activator.activate(
        state, Chain(), action, authorization=ValidationResult.valid()
    )
    return state, result, action


# ======================================================================
# A. §2 A · B — EventContext 는 어디에서 생기고, actor 는 어디에서 들어오는가
# ======================================================================


def test_01_the_context_is_built_in_exactly_two_places_both_inside_one_module():
    """
    §2 A — ``EventContext`` 를 만드는 production 자리는 **둘**이다.

    ``of`` (분류 메서드 — ``cls(...)``) 와 ``at`` (다음 순번 — 이름으로
    부른다). 둘 다 ``engine/event_pipeline.py`` 안이다. 즉 **밖에서 문맥을
    만드는 production 코드가 없다.**
    """
    #: 이름으로 부르는 자리는 하나뿐이다 (``at``).
    assert construction_sites("EventContext") == {"engine/event_pipeline.py": 1}

    #: ``of`` 는 ``cls(...)`` 로 만든다 — 이름 검색으로는 안 잡힌다.
    of_code = method_code("engine/event_pipeline.py", "EventContext", "of")
    assert "cls(" in of_code
    at_code = method_code("engine/event_pipeline.py", "EventContext", "at")
    assert "EventContext(" in at_code

    #: 그래서 둘을 합쳐 **두 자리**이고, 둘 다 같은 파일이다.
    classes_in_file = {
        node.name
        for node in ast.walk(ast.parse(source_of("engine/event_pipeline.py")))
        if isinstance(node, ast.ClassDef)
    }
    assert "EventContext" in classes_in_file


def test_02_only_of_accepts_an_actor_value_and_at_merely_copies_it():
    """
    §2 B — actor 값을 **받는** 자리는 ``of`` 하나다.

    ``at`` 은 같은 값을 그대로 옮겨 적는다 — 순번만 바꾼다. 그래서 한
    변화 묶음의 모든 사건이 **같은 actor** 를 갖는다.
    """
    assert list(inspect.signature(EventContext.of).parameters) == [
        "view",
        "actor",
        "sequence",
    ]
    assert list(inspect.signature(EventContext.at).parameters) == ["self", "sequence"]

    at_code = method_code("engine/event_pipeline.py", "EventContext", "at")
    assert "self.actor" in at_code

    #: 실제로 묶음 전체가 한 actor 를 공유한다 — 순번만 올라간다.
    base = EventContext(turn_number=1, turn_player=MINE, phase=Phase.MAIN1, actor=THEIRS)
    assert [base.at(i).actor for i in range(3)] == [THEIRS, THEIRS, THEIRS]
    assert [base.at(i).sequence for i in range(3)] == [0, 1, 2]


def test_03_the_code_never_writes_result_action_actor_it_duck_types_twice():
    """
    §2 C — 실제 코드는 ``result.action.actor`` 라고 **쓰지 않는다.**

    ``getattr(getattr(result, "action", None), "actor", None)`` 이다. 겹
    ``getattr`` 이라서 **타입을 보지 않고**, 없으면 **조용히 ``None``** 이
    된다. 그 조용함이 §5 의 핵심이다 — 왜 ``None`` 인지 아무 데도 남지 않는다.
    """
    read_code = method_code("engine/event_pipeline.py", "EventReader", "read")
    #: 점 표기법은 코드에 없다 — 이것은 그대로다.
    assert "result.action.actor" not in read_code
    #: 🔴 **Phase 3-F-14 에서 겹 getattr 자체가 사라졌다.** 이 Phase(3-F-12)는
    #: "조용히 None 이 된다" 를 결함으로 적었고, 3-F-13 이 호출자 책임으로
    #: 판정했고, 3-F-14 가 fallback 을 지웠다. 그래서 고정 대상이 **존재**에서
    #: **부재**로 바뀐다 — 아래 결함 서술(§5)은 그 역사로 그대로 둔다.
    assert read_code.count("getattr") == 1  # deltas 하나만 남았다
    assert "getattr(getattr(result, 'action', None), 'actor', None)" not in read_code
    assert "'action'" not in read_code

    #: 그런데 **설명에는** 점 표기법으로 적혀 있다 — 그래서 이 Phase 가
    #: 코드를 먼저 읽었다.
    assert "result.action.actor" in method_doc(
        "engine/event_pipeline.py", "EventContext", "of"
    ) or "result.action.actor" in source_of("engine/event_pipeline.py")

    #: production 전체에서 점 표기법이 나오는 곳은 ``engine/event_pipeline.py``
    #: **한 파일**이고, 그 자리는 전부 **산문**이다 (코드가 아니다).
    #:
    #: 줄 번호를 적지 않는다 — 3-F-11 에서 줄 번호 snapshot 이 docstring
    #: 한 줄 때문에 줄줄이 깨졌다. 고정하는 것은 **성격**이다.
    dotted: dict[str, list[int]] = {}
    for path in production_files():
        hits = [
            index
            for index, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "result.action.actor" in line
        ]
        if hits:
            dotted[str(path.relative_to(PROJECT_ROOT))] = hits
    assert list(dotted) == ["engine/event_pipeline.py"], dotted
    assert len(dotted["engine/event_pipeline.py"]) == 1
    prose = prose_lines("engine/event_pipeline.py")
    assert set(dotted["engine/event_pipeline.py"]) <= prose


def test_04_the_action_actor_can_never_be_none():
    """
    §2 E — ``action.actor`` 는 **None 이 될 수 없다.**

    필수 ``int`` 이고 ``__post_init__`` 이 0/1 만 받는다. 그래서 **행위가
    있는 경로에서는 ``EventContext.actor`` 가 절대 비지 않는다** — ``None``
    경계는 전부 "행위가 없는" 쪽에서만 생긴다.
    """
    field = {f.name: f for f in dataclasses.fields(PlayerAction)}["actor"]
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING
    assert "None" not in str(field.type)

    for bad in (None, 2, -1):
        with pytest.raises(Exception):
            PlayerAction.passing(actor=bad)

    assert PlayerAction.passing(actor=MINE).actor == MINE
    assert PlayerAction.passing(actor=THEIRS).actor == THEIRS


# ======================================================================
# B. §2 D · F — delta 를 들고 있는 result 전수
# ======================================================================


def test_05_seven_production_results_carry_deltas_and_only_two_carry_an_action():
    """
    🔴 §2 F — **3-F-10 · 3-F-11 이 덜 셌다.**

    그 두 Phase 는 "``.action`` 을 가진 것은 ``ActionExecution`` 하나뿐" 이라
    적었다. 전수로 세면 **둘**이다 — ``ActivationResult`` 도 ``action`` 칸을
    가지고 있고, 그것도 **필수** ``PlayerAction`` 이다.

    =========================  =========  ========
    result                      .action    .actor
    =========================  =========  ========
    ``ActionExecution``          ○          ✗
    ``ActivationResult``         ○          ✗
    ``EffectEvent``              ✗          **○**
    ``CostPaymentEvent``         ✗          **○**
    ``EffectResult``             ✗          ✗
    ``CostPaymentResult``        ✗          ✗
    ``ProgressionResult``        ✗          ✗
    =========================  =========  ========
    """
    rows = every_delta_bearing_result()
    assert rows == {
        "engine.action_execution.ActionExecution": (True, False),
        "engine.activation.ActivationResult": (True, False),
        "engine.effect.journal.CostPaymentEvent": (False, True),
        "engine.effect.journal.EffectEvent": (False, True),
        "engine.effect.resolution.EffectResult": (False, False),
        "engine.payment.CostPaymentResult": (False, False),
        "engine.turn_progression.ProgressionResult": (False, False),
    }, rows

    with_action = {name for name, (has_action, _) in rows.items() if has_action}
    assert len(with_action) == 2
    with_actor = {name for name, (_, has_actor) in rows.items() if has_actor}
    assert len(with_actor) == 2
    #: 두 집합이 **겹치지 않는다** — 한 result 가 둘을 다 갖는 일은 없다.
    assert with_action & with_actor == set()


def test_06_both_action_bearing_results_hand_a_real_actor_to_the_context(repository):
    """
    §4 A. ACTION_ACTOR — ``.action`` 이 있으면 actor 가 **언제나** 들어온다.

    ``ActivationResult`` 는 비용이 없으면 delta 가 0개라 사건이 안 생긴다.
    그래서 **같은 결과에 delta 하나를 얹어** (``dataclasses.replace``)
    ``read()`` 가 어느 칸을 보는지 확인한다 — 판을 바꾸지 않는다.
    """
    #: ① ActionExecution.
    state, execution = summon(repository, THEIRS)
    assert isinstance(execution, ActionExecution)
    assert execution.deltas
    #: 🔴 3-F-14: **선언한다.** 전에는 생략하면 엔진이 채워 주었다.
    for observed in read_with(state, execution, actor=execution.action.actor):
        assert observed.context.actor == execution.action.actor == THEIRS

    #: ② ActivationResult — 발동만으로는 delta 가 없다.
    state2, result, action = activation(repository, THEIRS)
    assert isinstance(result, ActivationResult)
    assert result.activated and result.deltas == ()
    assert read_with(state2, result, viewer=THEIRS, actor=action.actor) == ()

    #: delta 를 하나 얹으면 actor 가 ``action`` 에서 온다.
    borrowed = execution.deltas[:1]
    with_delta = dataclasses.replace(result, deltas=borrowed)
    observed = read_with(state2, with_delta, viewer=THEIRS, actor=action.actor)
    assert len(observed) == 1
    assert observed[0].context.actor == action.actor == THEIRS


def test_07_the_journal_events_carry_an_actor_that_read_refuses_to_look_at(repository):
    """
    🔴 §4 D. MISSING — **정보가 객체에 있는데 떨어진다.**

    ``EffectEvent.actor`` 는 **필수 ``int``** 다. 그런데 ``read()`` 는
    ``.action`` 만 찾으므로 그 칸을 **보지 않고** ``None`` 을 만든다.
    "actor 가 없는 결과" 가 아니라 **"actor 가 있는데 안 읽는 결과"** 다.

    이것은 의도된 ``None`` (``ProgressionResult``) 과 **같은 값으로** 나와서
    구분되지 않는다 — 그래서 ``INTENTIONALLY_NONE`` 과 묶지 않고 따로 적는다.
    """
    journal = EventJournal()
    state, _ = effect_draw(repository, MINE, journal=journal)
    event = journal.events[0]
    assert isinstance(event, EffectEvent)

    #: actor 가 거기 있다. ``None`` 이 아니다.
    actor_field = {f.name: f for f in dataclasses.fields(EffectEvent)}["actor"]
    assert actor_field.default is dataclasses.MISSING
    assert str(actor_field.type) == "int"
    assert event.actor == MINE

    #: 🔴 **Phase 3-F-14 뒤에도 공백은 그대로다 — 오히려 드러났다.**
    #:
    #: 전에는 생략하면 조용히 ``None`` 이 되었다. 이제 생략은 거부되므로,
    #: ``EffectEvent`` 를 읽는 쪽은 **반드시 actor 를 말해야** 한다. 즉 객체가
    #: 들고 있는 ``event.actor`` 를 ``read()`` 가 여전히 **쓰지 않는다** —
    #: 다만 그 사실이 조용한 ``None`` 이 아니라 **TypeError** 로 나타난다.
    with pytest.raises(TypeError) as omitted:
        read_with(state, event)
    assert "actor 를 말해야 합니다" in str(omitted.value)

    #: 객체에 값이 있는데도 **부르는 쪽이 옮겨 적어야** 한다.
    observed = read_with(state, event, actor=event.actor)
    assert observed
    assert all(o.context.actor == MINE for o in observed)

    #: 그리고 "없다" 고 말하면 그대로 ``None`` 이 된다 — ``event.actor`` 를
    #: 보지 않는다는 증거다.
    assert all(o.context.actor is None for o in read_with(state, event, actor=None))

    #: 코드에 result 자신의 actor 칸을 보는 줄이 **없다** (그대로다).
    read_code = method_code("engine/event_pipeline.py", "EventReader", "read")
    assert "getattr(result, 'actor'" not in read_code
    #: ``action`` 을 보는 줄도 이제 없다 (3-F-14).
    assert "'action'" not in read_code


def test_08_the_read_docstring_names_three_of_the_seven_result_types():
    """
    §2 F — ``read()`` 의 설명은 **세 타입만** 예로 든다.

    "변화를 들고 있는 것이면 무엇이든 된다" 는 맞지만, 괄호 안의 예시가
    ``ActionExecution`` · ``ProgressionResult`` · ``EffectResult`` 셋이라서
    **journal 사건 둘** 과 ``ActivationResult`` · ``CostPaymentResult`` 가
    빠져 있다. 설명을 읽은 사람은 7개 중 3개만 알게 된다.
    """
    doc = method_doc("engine/event_pipeline.py", "EventReader", "read")
    named = {
        name
        for name in (
            "ActionExecution",
            "ActivationResult",
            "EffectResult",
            "CostPaymentResult",
            "ProgressionResult",
            "EffectEvent",
            "CostPaymentEvent",
        )
        if name in doc
    }
    #: 🔴 **Phase 3-F-14 가 설명을 고쳤다 — 이제 일곱을 전부 적는다.**
    #: 이 Phase(3-F-12)가 "셋만 적혀 있다" 를 결함으로 찾았고, 그것이 고쳐졌다.
    assert named == {
        "ActionExecution",
        "ActivationResult",
        "EffectResult",
        "CostPaymentResult",
        "ProgressionResult",
        "EffectEvent",
        "CostPaymentEvent",
    }, named
    assert len(every_delta_bearing_result()) == 7 == len(named)


# ======================================================================
# C. §5 — None 경계 전수
# ======================================================================


def test_09_the_effect_result_has_no_actor_anywhere_on_it(repository):
    """
    §5 — ``EffectResult`` → ``None``. **칸 자체가 없다.**

    그런데 그 효과를 **누가 해결했는지는 상류가 알고 있었다** —
    ``ResolutionContext.controller`` 다. 결과가 그것을 들고 나오지 않으므로
    부르는 쪽이 선언해야 한다. 선언하면 들어간다.
    """
    fields = {f.name for f in dataclasses.fields(EffectResult)}
    assert "actor" not in fields and "action" not in fields

    state, result = effect_draw(repository, MINE)
    assert isinstance(result, EffectResult)
    assert result.deltas

    #: 🔴 3-F-14: 선언이 **없으면 거부된다.** 전에는 비어 있었다.
    with pytest.raises(TypeError):
        read_with(state, result)
    #: "없다" 고 말하면 비어 있다.
    assert all(o.context.actor is None for o in read_with(state, result, actor=None))
    #: 선언하면 들어간다 — 즉 **경로가 막힌 것이 아니라 비어 있는 것**이다.
    assert all(
        o.context.actor == MINE for o in read_with(state, result, actor=MINE)
    )

    #: 상류가 알고 있었다는 근거: 실행기는 controller 를 받는다.
    assert "controller" in {f.name for f in dataclasses.fields(ResolutionContext)}


def test_10_the_progression_result_is_intentionally_actorless():
    """
    §5 ``INTENTIONALLY_NONE`` — ``ProgressionResult`` 는 **사람 칸이 없다.**

    결과도, 그 안의 ``TransitionPlan`` 도, 그 안의 ``PhaseTransition`` 도
    사람을 담지 않는다. 그래서 ``None`` 이 "빠진 것" 이 아니라 **구조상
    없는 것**이다 — 페이즈가 넘어가는 일은 규칙이 한다 (3-F-9 가
    ``PhaseChanged`` 의 ``actor`` 를 ``None`` 으로 측정한 것과 같은 자리다).
    """
    for cls in (ProgressionResult, TransitionPlan, PhaseTransition):
        fields = {f.name for f in dataclasses.fields(cls)}
        assert not (fields & {"actor", "action", "player", "turn_player"}), (
            cls.__name__,
            fields,
        )


def test_11_a_phase_change_gives_none_on_both_actors(repository):
    """
    §5 — 실제 페이즈 전환을 돌려서 **둘 다 ``None``** 인 것을 본다.

    ``timing.actor`` 도 ``None`` 이고 ``context.actor`` 도 ``None`` 이다.
    두 계약이 **여기서는 같은 답**을 낸다 — 값이 같은 것이 의미가 같다는
    뜻은 아니지만, 이 자리에서는 둘 다 "사람이 없다" 를 말한다.
    """
    duel = live_duel(repository)
    state = duel.state.clone()
    progression = TurnProgressor().advance(state)
    assert progression.deltas

    #: 🔴 3-F-14: 규칙이 한 일이라고 **적어서** 말한다.
    observed = read_with(state, progression, actor=None)
    assert observed
    for event in observed:
        assert event.point is TimingPoint.PHASE_CHANGED
        assert event.actor is None          # TimingEvent.actor
        assert event.context.actor is None  # EventContext.actor


def test_12_read_now_distinguishes_an_explicit_none_from_an_omission(repository):
    """
    🟢 §5 ``EXPLICIT_NONE`` — **Phase 3-F-14 가 이 결함을 고쳤다.**

    .. note::
       **이 테스트는 결함을 pin 하고 있었다.**

       3-F-12(이 Phase)는 ``read(result, actor=None)`` 이 생략과 **같은 값**을
       낸다는 것을 결함의 증거로 고정했다. 그 모양은 **고치면 반드시 깨진다** —
       3-F-8 의 ``test_15`` 가 거짓 docstring 의 존재를 pin 했다가 3-F-11 에서
       깨진 것과 똑같다. 3-F-13 §12 가 "다음 Phase 가 고치면 이 테스트가
       깨진다" 고 미리 적어 두었고, 그대로 되었다.

       **삭제하지 않는다.** 결함이 사라졌으므로 고정 대상을 **고쳐진 계약**으로
       바꾼다 — 세 모양이 **서로 다른 결과**를 낸다는 것. 단정 수는 5 → 9 로
       늘었다.
    """
    state, execution, action, _ = battle(repository, THEIRS)

    #: ① 생략 → **거부된다.**
    with pytest.raises(TypeError) as omitted:
        read_with(state, execution)
    message = str(omitted.value)
    assert "actor 를 말해야 합니다" in message
    #: 무엇을 해야 하는지 알려 준다.
    assert "actor=None" in message and "말하지 않았다" in message

    #: ② ``actor=None`` → **"행위자가 없다" 는 선언으로** 받아들인다.
    said_none = read_with(state, execution, actor=None)
    assert [o.context.actor for o in said_none] == [None]

    #: ③ 값을 주면 그 값이다 — 행위가 P1 이어도 선언이 이긴다.
    assert [o.context.actor for o in read_with(state, execution, actor=THEIRS)] == [
        THEIRS
    ]
    assert action.actor == THEIRS

    #: 세 모양이 서로 다르다 — 그것이 이 Phase 가 못 하던 일이다.
    assert said_none[0].context.actor is not THEIRS

    #: 코드가 그렇게 쓰여 있다 — 보초값이 있고, ``actor is None`` 분기가 없다.
    read_code = method_code("engine/event_pipeline.py", "EventReader", "read")
    assert "if actor is None" not in read_code
    deltas_code = method_code("engine/event_pipeline.py", "EventReader", "read_deltas")
    assert "_ACTOR_OMITTED" in deltas_code


def test_13_read_and_read_deltas_now_have_the_same_expressive_power(repository):
    """
    🟢 §5 — **Phase 3-F-14 가 두 메서드의 표현력 차이를 없앴다.**

    .. note::
       **이 테스트도 결함을 pin 하고 있었다.**

       3-F-12 는 ``read`` 가 "주체 없음" 을 말할 수 없고 ``read_deltas`` 만 말할
       수 있다는 **비대칭**을 고정했다 — "표현하려면 더 낮은 API 로 내려가야
       한다". 3-F-14 가 두 메서드에 같은 보초값을 두었으므로 그 비대칭이
       사라졌다. 고정 대상을 **대칭**으로 바꾼다.
    """
    state, execution, _, _ = battle(repository, THEIRS)
    view = GameStateView.from_state(state, viewer=MINE)
    reader = EventReader(view)

    #: 둘 다 생략을 거부한다. (``lambda`` 로 묶지 않는다 — 호출이
    #: ``with pytest.raises`` 블록 **안에** 있어야 "거부를 시험하는 자리" 로
    #: 읽히고, 그러지 않으면 계약 위반 호출로 세어진다.)
    with pytest.raises(TypeError) as omitted_read:
        reader.read(execution)
    assert "actor 를 말해야 합니다" in str(omitted_read.value)

    with pytest.raises(TypeError) as omitted_deltas:
        reader.read_deltas(execution.deltas)
    assert "actor 를 말해야 합니다" in str(omitted_deltas.value)

    #: 둘 다 "없다" 를 말할 수 있다.
    assert [o.context.actor for o in reader.read(execution, actor=None)] == [None]
    assert [
        o.context.actor for o in reader.read_deltas(execution.deltas, actor=None)
    ] == [None]

    #: 둘 다 값을 받는다.
    assert [o.context.actor for o in reader.read(execution, actor=THEIRS)] == [THEIRS]
    assert [
        o.context.actor for o in reader.read_deltas(execution.deltas, actor=THEIRS)
    ] == [THEIRS]

    #: ``read_deltas`` 는 여전히 result 를 보지 않는다 — 그것은 그대로다.
    deltas_code = method_code("engine/event_pipeline.py", "EventReader", "read_deltas")
    assert "action" not in deltas_code
    #: 그리고 ``read`` 는 **판정을 한 곳에 맡긴다** — 규칙이 한 벌뿐이다.
    read_code = method_code("engine/event_pipeline.py", "EventReader", "read")
    assert "_ACTOR_OMITTED" not in read_code
    assert "self.read_deltas(deltas, actor=actor)" in read_code


def test_14_the_declared_actor_is_never_checked_against_the_deltas(repository):
    """
    §5 — 선언값은 **검증되지 않는다.**

    공격한 쪽이 P1 인데 ``actor=P0`` 이라고 선언하면 그대로 들어간다. 3-F-11
    의 docstring 이 "delta 와 맞춰 보지 않는다 · 사실인지는 넘기는 쪽의
    책임" 이라고 적어 둔 그대로다 — **설계된 느슨함**이고 결함이 아니다.
    다만 그래서 ``actor`` 가 **틀릴 수 있다**는 것을 여기 못박는다.
    """
    state, execution, action, _ = battle(repository, THEIRS)
    assert action.actor == THEIRS

    lied = read_with(state, execution, actor=MINE)
    assert [o.context.actor for o in lied] == [MINE]
    #: 거짓말을 해도 예외가 나지 않고, timing 쪽은 영향을 받지 않는다.
    assert [o.actor for o in lied] == [MINE]  # LifeChanged — 맞은 쪽도 P0 이다

    #: 0/1 밖만 막는다.
    with pytest.raises(ValueError):
        EventContext(turn_number=1, turn_player=MINE, phase=Phase.MAIN1, actor=2)


def test_15_a_none_actor_records_no_reason_at_all():
    """
    🔴 §5 6번 — **``None`` 의 까닭이 코드에 남지 않는다.**

    ``EventContext`` 에는 note · provenance · source 칸이 없다. 그래서
    ``context.actor is None`` 을 받은 쪽은 셋을 구분할 수 없다:

    * ``INTENTIONALLY_NONE`` — 페이즈 전환처럼 원래 사람이 없다
    * ``MISSING_ACTOR`` — ``EffectEvent.actor`` 가 있는데 안 읽었다
    * 부르는 쪽이 **그냥 선언을 잊었다**

    ``TimingEvent`` 에는 ``note`` 칸이 있어서 "옮길 이름이 없었다" 를 적을 수
    있다. 문맥 쪽에는 그 자리가 없다 — **비대칭**이다.
    """
    context_fields = {f.name for f in dataclasses.fields(EventContext)}
    assert context_fields == {
        "turn_number",
        "turn_player",
        "phase",
        "actor",
        "sequence",
    }
    assert not (context_fields & {"note", "provenance", "actor_source", "reason"})

    #: 비교 대상 — timing 쪽에는 까닭을 적는 칸이 있다.
    from engine.trigger import TimingEvent

    assert "note" in {f.name for f in dataclasses.fields(TimingEvent)}


# ======================================================================
# D. §7 — Battle 반례 재검증
# ======================================================================


def test_16_the_battle_case_keeps_both_meanings_by_two_independent_routes(repository):
    """
    §7 — P1 이 P0 을 직접 공격한다. LP 8000 → **6100**.

    ``timing.actor = P0`` (맞은 쪽) · ``context.actor = P1`` (공격한 쪽).

    **값이 우연히 맞은 것이 아니다.** 두 값의 출처가 서로 다르다:

    * ``context.actor`` ← ``execution.action.actor`` ← ``PlayerAction(actor=1)``
    * ``timing.actor``  ← ``delta.player`` ← LP 가 바뀐 쪽

    그래서 공격자를 바꾸면 **둘이 같이 뒤집힌다** — 한쪽만 바뀌면 그것이
    파생이 아니라 우연이었다는 증거가 된다.
    """
    state, execution, action, victim_before = battle(repository, THEIRS)
    assert victim_before == 8000
    assert state.player(MINE).life_points == 6100

    observed = read_with(state, execution, actor=action.actor)
    assert len(observed) == 1
    event = observed[0]
    assert event.point is TimingPoint.LIFE_CHANGED
    assert event.actor == MINE            # 귀속 — 맞은 쪽
    assert event.context.actor == THEIRS  # 행위 — 공격한 쪽
    assert event.actor != event.context.actor

    #: 출처가 둘이다.
    assert event.context.actor == execution.action.actor == action.actor
    assert event.actor == event.delta.player

    #: 공격자를 뒤집으면 둘이 함께 뒤집힌다.
    state2, execution2, action2, before2 = battle(repository, MINE)
    assert before2 == 8000
    assert state2.player(THEIRS).life_points == 6100
    flipped = read_with(state2, execution2, viewer=THEIRS, actor=action2.actor)
    assert len(flipped) == 1
    assert flipped[0].actor == THEIRS
    assert flipped[0].context.actor == MINE
    assert flipped[0].actor != flipped[0].context.actor


# ======================================================================
# E. §6 — 실제 실행 경로별 provenance
# ======================================================================


def test_17_each_execution_path_maps_to_one_result_type_and_one_actor_source(
    repository,
):
    """
    §6 — 경로마다 **어느 result 를 내고, actor 가 어디서 오는가.**

    ====================  =========================  ====================
    경로                   result                      actor 출처
    ====================  =========================  ====================
    통상 소환              ``ActionExecution``          ``action.actor``
    특수 소환              ``ActionExecution``          ``action.actor``
    직접 공격              ``ActionExecution``          ``action.actor``
    마법·함정 세트          ``ActionExecution``          ``action.actor``
    효과 발동              ``ActivationResult``         ``action.actor``
    효과 해결 (드로우)      ``EffectResult``             **없음** → 선언 필요
    journal 기록           ``EffectEvent``              **있는데 안 읽는다**
    페이즈 전환            ``ProgressionResult``        **없음** (의도)
    ====================  =========================  ====================
    """
    rows: dict[str, tuple[str, object]] = {}

    for label, kind in (
        ("통상 소환", "normal_summon"),
        ("특수 소환", "special_summon"),
        ("마법·함정 세트", "set_spell_trap"),
    ):
        state, execution = summon(repository, THEIRS, kind)
        if not execution.deltas:
            continue
        actors = {
            o.context.actor
            for o in read_with(state, execution, actor=execution.action.actor)
        }
        rows[label] = (type(execution).__name__, actors)

    state, execution, _, _ = battle(repository, THEIRS)
    rows["직접 공격"] = (
        type(execution).__name__,
        {
            o.context.actor
            for o in read_with(state, execution, actor=execution.action.actor)
        },
    )

    journal = EventJournal()
    state, result = effect_draw(repository, MINE, journal=journal)
    #: 🔴 3-F-14: 행위를 들고 있지 않은 결과도 **말해야** 한다. 여기서는 이
    #: 표가 "선언하지 않으면 무엇이 되는가" 를 재던 자리였으므로, **없다고
    #: 말한 경우**를 재서 같은 질문을 유지한다 — 자동으로 채워지지 않는다는
    #: 사실이 요점이기 때문이다.
    rows["효과 해결"] = (
        type(result).__name__,
        {o.context.actor for o in read_with(state, result, actor=None)},
    )
    rows["journal 기록"] = (
        type(journal.events[0]).__name__,
        {o.context.actor for o in read_with(state, journal.events[0], actor=None)},
    )

    duel = live_duel(repository)
    progression_state = duel.state.clone()
    progression = TurnProgressor().advance(progression_state)
    rows["페이즈 전환"] = (
        type(progression).__name__,
        {o.context.actor for o in read_with(progression_state, progression, actor=None)},
    )

    #: 행위가 있는 경로는 **전부** 실제 행위자를 준다.
    for label in ("통상 소환", "특수 소환", "마법·함정 세트", "직접 공격"):
        if label in rows:
            assert rows[label] == ("ActionExecution", {THEIRS}), (label, rows[label])

    #: 행위가 없는 경로는 **전부** 비어 있다 — 까닭은 서로 다르다.
    assert rows["효과 해결"] == ("EffectResult", {None})
    assert rows["journal 기록"] == ("EffectEvent", {None})
    assert rows["페이즈 전환"] == ("ProgressionResult", {None})

    #: 적어도 네 경로를 실제로 돌렸다.
    assert len(rows) >= 6, rows


# ======================================================================
# F. §8 — journal 의 actor 는 어디서 오는가
# ======================================================================


def test_18_the_journal_actor_comes_from_controller_and_payer_not_from_an_action():
    """
    🟡 §8 ``STRUCTURAL_RISK`` — journal 의 actor 는 **지배자 · 지불자**다.

    ``EffectEvent.actor = context.controller`` 이고
    ``CostPaymentEvent.actor = context.payer`` 다. 둘 다 "행위의 주체" 와
    **지금은 같은 값**이지만 (Engine V1 에 컨트롤 이동이 없다) **같은 뜻이
    아니다.** 그래서 "journal 의 actor 를 그대로 ``EventContext.actor`` 로
    쓰면 된다" 고 결론하지 않는다 — 고치지 않고 위험으로 적는다.
    """
    executor_code = method_code("engine/effect/executor.py", "EffectExecutor", "execute")
    assert "actor=context.controller" in executor_code
    assert "actor=context.actor" not in executor_code

    payer_source = source_of("engine/payment.py")
    assert "actor=context.payer" in payer_source

    #: 두 문맥에 행위자 칸이 **없다** — 지배자/지불자뿐이다.
    assert {f.name for f in dataclasses.fields(ResolutionContext)} & {
        "controller"
    } == {"controller"}
    assert "actor" not in {f.name for f in dataclasses.fields(ResolutionContext)}
    assert "payer" in {f.name for f in dataclasses.fields(PaymentContext)}
    assert "actor" not in {f.name for f in dataclasses.fields(PaymentContext)}


# ======================================================================
# G. §3 — call graph 는 어디에서 끊기는가
# ======================================================================


def test_19_the_live_path_drops_the_deltas_one_assignment_before_the_pipeline():
    """
    🔴 §3 — live 경로가 ``DuelStep`` 에서 끊긴다.

    ``DuelStep`` 은 ``{action, accepted, code, reason, result}`` 다.
    ``result`` 는 ``DuelResult | None`` — **듀얼의 승패**이고 실행 결과가
    아니다. 그래서 ``deltas`` 도 ``ActionExecution`` 도 남지 않는다.

    **그런데 둘이 같은 함수의 지역변수로 동시에 존재한다** —
    ``Duel._apply_board`` 안에서 ``executed`` (deltas 를 들고 있다) 와
    ``action`` (actor 를 들고 있다) 이 나란히 있다. ``read()`` 가 필요한 입력
    둘이 **한 자리에** 있고, 보관되지 않는 것뿐이다.
    """
    step_fields = [f.name for f in dataclasses.fields(DuelStep)]
    assert step_fields == ["action", "accepted", "code", "reason", "result"]
    assert "deltas" not in step_fields

    #: ``result`` 는 승패다.
    assert "DuelResult" in str(
        {f.name: f.type for f in dataclasses.fields(DuelStep)}["result"]
    )

    #: 같은 함수 안에 둘이 있다.
    apply_board = method_code("engine/duel.py", "Duel", "_apply_board")
    assert "self._executor.execute(" in apply_board
    assert "executed.deltas" not in apply_board   # 보지 않는다
    assert "DuelStep(" in apply_board

    #: duel.py 전체가 사건 파이프라인을 **모른다.**
    duel_source = source_of("engine/duel.py")
    for absent in ("EventReader", "EventContext", "ObservedEvent", "deltas"):
        assert absent not in duel_source, absent


def test_20_nothing_in_production_imports_the_pipeline_or_reads_a_context_actor():
    """
    §3 — 마지막 두 화살표가 **DORMANT** 다 (3-F-5 ~ 3-F-11 과 같은 측정).

    ``engine.event_pipeline`` 을 import 하는 production 파일이 **0개**이고,
    ``context.actor`` 를 읽는 production 코드도 **0줄**이다. 그래서 지금
    틀린 판정이 나오고 있지는 않다 — 공백이 **아직 아무도 밟지 않은**
    자리라는 뜻이다.
    """
    importers = {
        str(path.relative_to(PROJECT_ROOT))
        for path in production_files()
        if path.name != "event_pipeline.py"
        and (
            "from engine.event_pipeline import" in path.read_text(encoding="utf-8")
            or "import engine.event_pipeline" in path.read_text(encoding="utf-8")
        )
    }
    assert importers == set(), importers

    readers = {
        str(path.relative_to(PROJECT_ROOT))
        for path in production_files()
        if "context.actor" in path.read_text(encoding="utf-8")
    }
    assert readers == set(), readers


# ======================================================================
# H. §9 — AI 는 actor 를 보는가
# ======================================================================


def test_21_the_observation_boundary_never_exposes_an_event_actor():
    """
    §9 — ``GameStateView`` 에 ``actor`` 라는 **말이 한 번도 없다.**

    그래서 ``EventContext.actor`` 는 AI 가 관측하는 정보에 **들어가지
    않는다.** ``agent/`` 가 읽는 ``actor`` 는 전부 **자기가 고른 행위의**
    actor (``action.actor``) 이고, 사건의 actor 가 아니다.
    """
    assert "actor" not in source_of("engine/game_state_view.py")

    agent_actor_lines = [
        (str(path.relative_to(PROJECT_ROOT)), line.strip())
        for path in (PROJECT_ROOT / "agent").rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if ".actor" in line
    ]
    #: 전부 ``action``/``chosen`` 의 actor 다 — 사건에서 온 것이 없다.
    for where, line in agent_actor_lines:
        assert "action.actor" in line or "chosen.actor" in line, (where, line)
    assert agent_actor_lines, "agent 쪽 actor 사용을 하나도 못 찾았다"

    #: 사건 타입이 agent 안으로 들어오지 않는다.
    agent_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (PROJECT_ROOT / "agent").rglob("*.py")
    )
    for absent in ("ObservedEvent", "EventContext", "TimingEvent", "EventReader"):
        assert absent not in agent_source, absent


# ======================================================================
# I. §14 — AUDIT-ONLY
# ======================================================================


def test_22_this_phase_changed_no_production_file():
    """
    §14 — **이 Phase(3-F-12)는 production 을 한 줄도 바꾸지 않았다.**

    .. note::
       **Phase 3-F-14 에서 재는 방법을 바꿨다.**

       전에는 ``git diff HEAD -- engine …`` 이 비어 있는지를 봤다. 그것은 "작업
       나무가 깨끗한가" 이지 "**이 Phase** 가 무엇을 바꿨는가" 가 아니다. 뒤의
       Phase 가 production 을 바꾸는 순간 (3-F-14 가 그렇게 했다) 이 단정은
       **그 Phase 때문에** 깨진다 — 재는 대상이 틀렸던 것이다.

       그래서 **이 Phase 의 작업 commit 자체**를 본다. ``3a10656`` 이 건드린
       파일 목록은 영원히 바뀌지 않으므로, 이 단정은 뒤의 어떤 Phase 에도
       흔들리지 않는다.
    """
    PHASE_3F12_WORK = "3a10656"
    shown = subprocess.run(
        ["git", "show", "--stat", "--format=", PHASE_3F12_WORK],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    touched = [
        line.split("|")[0].strip()
        for line in shown.splitlines()
        if "|" in line
    ]
    assert touched == ["tests/test_event_context_actor_provenance.py"], touched
    for path in touched:
        assert not path.startswith(PRODUCTION_ROOTS), path

    #: §9 의 금지 항목은 **지금도** 들어오지 않았다 (현재 나무를 본다).
    pipeline_source = source_of("engine/event_pipeline.py")
    for forbidden in (
        "cause_player",
        "affected_player",
        "action_player",
        "actor_player",
    ):
        assert forbidden not in pipeline_source, forbidden
    #: ``EventBus`` 라는 말은 "만들지 않는다" 는 설명으로 한 번 나온다.
    assert pipeline_source.count("EventBus") == 1

    trigger_source = source_of("engine/trigger.py")
    assert "EVENT_RELATION" in trigger_source  # dormant 그대로 있다
    assert "EVENT_RELATION" not in source_of("engine/duel.py")


def test_23_reading_events_changes_neither_the_board_nor_the_rng(repository):
    """
    §14 — ``state_hash`` 불변 · RNG 불변.

    ``EventReader`` 는 ``GameStateView`` 만 들고 있어서 **바꿀 수 있는 것을
    애초에 갖고 있지 않다.** 그것을 말로 두지 않고 실제로 잰다 — actor 를
    선언해서 읽든, 선언하지 않고 읽든, journal 사건을 읽든 ``state_hash`` 가
    한 글자도 움직이지 않는다.
    """
    state, execution, _, _ = battle(repository, THEIRS)
    before = state.state_hash()

    read_with(state, execution, actor=THEIRS)
    read_with(state, execution, actor=MINE)
    view = GameStateView.from_state(state, viewer=MINE)
    EventReader(view).read_deltas(execution.deltas, actor=None)
    assert state.state_hash() == before

    journal = EventJournal()
    effect_state, _ = effect_draw(repository, MINE, journal=journal)
    effect_before = effect_state.state_hash()
    read_with(effect_state, journal.events[0], actor=MINE)
    assert effect_state.state_hash() == effect_before

    #: 같은 seed 는 같은 판을 준다 — 이 Phase 가 RNG 를 건드리지 않았다.
    assert (
        live_duel(repository, seed=7).state.state_hash()
        == live_duel(repository, seed=7).state.state_hash()
    )
    assert EventReader(view).view is view


def test_24_the_reader_cannot_mutate_because_it_only_holds_a_view():
    """
    §14 — hidden-information 경계 불변.

    ``EventReader`` 는 ``GameState`` 를 **거부**한다. 그래서 "사건을 읽는
    일" 이 "판을 바꾸는 일" 로 번질 수 없다. 이 Phase 가 그 경계를 손대지
    않았다는 것을 타입 거부로 확인한다.
    """
    with pytest.raises(TypeError):
        EventReader(object())

    init_code = method_code("engine/event_pipeline.py", "EventReader", "__init__")
    assert "isinstance(view, GameStateView)" in init_code
    assert {"_view"} == set(EventReader.__slots__)
