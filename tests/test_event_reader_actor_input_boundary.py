"""
Phase 3-F-13 — ``EventReader.read()`` 의 **actor 입력 경계**와 **semantic
responsibility** 감사.

이 파일이 답하는 단 하나의 질문
-------------------------------
``read()`` 는 actor 를 **어떻게 받아야** 하고, **누가 그 의미에 책임**을
지는가.

세 설계 (§2 의 이름을 그대로 쓴다)
----------------------------------
설계 A — **result 가 준다**: ``read()`` 가 ``execution.action.actor`` 같은
authoritative source 에서 읽는다.

설계 B — **호출자가 준다**: ``read(result, actor)`` 로 명시 선언한다.

설계 C — **문맥이 정한다**: ``read(result, context)`` 로 이미 있는 문맥에서
가져온다.

.. warning::
   §14 의 판정 글자와 §2 의 설계 글자가 **다르다.** §14 의 **B** 가 §2 의
   **설계 A** (result 파생) 이고, §14 의 **C** 가 §2 의 **설계 B** (호출자
   선언) 다. 이 파일은 §2 의 이름으로 적고, 판정만 §14 의 글자로 적는다.

측정이 가른 것
--------------
1. ``read()`` 의 외부 production 호출자는 **0개**다. 유일한 production 호출은
   ``EventPipeline.observe`` 가 **같은 모듈 안에서** 넘기는 것이다.
2. 테스트 호출 **72곳** 중 **36곳이 actor 를 생략한다.** 즉 지금 API 는
   "선언하지 않아도 되는 것" 으로 쓰이고 있다.
3. 🔴 **강욕의 보은** (실제 카드): P0 이 발동하면 **P1 이 2장 드로우한다.**
   delta 의 **모든 사람 칸이 1** 이고, 행위자 **0 은 delta 어디에도 없다.**
   → 설계 A 로는 이 사건의 행위자를 **영원히 알 수 없다.**
4. 🔴 **자비의 비** (실제 카드): 한 번의 실행이 **귀속자가 다른 delta 둘**
   (P0 · P1) 을 낸다. 행위자는 **하나** (P0) 다. 즉 두 actor 는 값만 다른 것이
   아니라 **개수가 다르다** — 귀속자는 delta 마다, 행위자는 **묶음마다**다.
5. 파괴 · 패로 · 버리기 · 제외 · 덱으로 — 다섯 사건이 전부 ``ZoneMoved`` 이고
   두 사람 칸이 **모두 카드 주인**이다. **가해자를 담는 칸이 없다.**
6. 그런데 ``MonsterSummoned`` 은 ``player`` (소환한 사람) 와 ``owner`` (카드
   주인) 를 **둘 다** 들고 있다. → **delta 가 행위자를 담을 때도 있고 안 담을
   때도 있다.** 그래서 "delta 에서 파생" 은 계약이 될 수 없다.
7. ``read()`` 는 ``GameStateView`` 하나만 들고 있다. 체인도, 우선권도,
   실행기도 **모른다** — 추론할 재료가 애초에 없다.

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
from engine.activation import ActivationResult
from engine.cost import Selection
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
from engine.event_pipeline import (
    EventContext,
    EventPipeline,
    EventReader,
    ObservedEvent,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.payment import CostPaymentResult, PaymentContext
from engine.state.game_state import GameState
from engine.summon import duel_executor
from engine.trigger import TimingEvent, TimingPoint, timing_for
from engine.turn_progression import ProgressionResult, TurnProgressor
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
FEATHERMAN = 71925487
POT_OF_GREED = 55144522
#: 강욕의 보은 — **상대가** 2장 드로우한다. 행위자와 귀속자가 갈리는 실제 카드.
THE_GIFT_OF_GREED = 5915629
#: 자비의 비 — **양쪽이** 1000 회복한다. 한 실행에 귀속자가 둘이다.
RAIN_OF_MERCY = 66719324
I = InstanceId


# ======================================================================
# 측정 도구
# ======================================================================


def source_of(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from (PROJECT_ROOT / root).rglob("*.py")


def method_code(relative: str, class_name: str, method: str) -> str:
    """메서드 본문을 **docstring 을 떼고** 돌려준다 (3-F-7 의 교훈)."""
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


def code_only(relative: str) -> str:
    """
    그 파일의 **코드만** — 모든 문자열 리터럴을 ``"<str>"`` 로 바꾼 뒤
    ``ast.unparse`` 한 것.

    .. note::
       **이 파일이 처음 쓸 때 또 당했다.** ``"ActionExecutor" not in source``
       로 쟀더니 모듈 설명의 "실행기(``ActionExecutor``)는 이 파일을 **모른다**"
       라는 문장에 걸렸다. 설명이 그 이름을 **부정하려고** 적고 있는데 존재로
       센 것이다 — 3-F-7 이 같은 실수를 하고 교훈까지 적어 두었는데 반복했다.
       그래서 코드를 볼 때는 반드시 이 함수를 쓴다.
    """

    class _Strip(ast.NodeTransformer):
        def visit_Constant(self, node):  # noqa: N802
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value="<str>"), node)
            return node

    return ast.unparse(_Strip().visit(ast.parse(source_of(relative))))


def imported_names(relative: str) -> set[str]:
    """그 모듈이 **실제로 import 하는** 이름 전부."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source_of(relative))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            names.update(alias.name for alias in node.names)
    return names


def pipeline_call_sites() -> list[tuple[str, int, str, str | None]]:
    """
    저장소 전체에서 ``reader``/``pipeline`` 계열의
    ``read``/``read_deltas``/``observe``/``collect`` 호출을 **AST 로** 모은다.

    .. note::
       정규식으로 세지 않는다 — 3-F-8 에서 ``re.findall`` 이 **자기 소스를**
       세어 숫자가 둘 늘었다.
    """
    targets = {"read", "read_deltas", "observe", "collect"}
    rows: list[tuple[str, int, str, str | None]] = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        #: ``with pytest.raises(...)`` 안의 줄 번호 — **거부를 시험하는 자리**다.
        #: 생략이 거부되는 것을 보려면 반드시 생략해야 하므로, 그 자리를 "계약을
        #: 지키지 않은 호출" 로 세면 틀린다 (Phase 3-F-14).
        refusal_lines: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            if not any(
                isinstance(item.context_expr, ast.Call)
                and "raises" in ast.unparse(item.context_expr.func)
                for item in node.items
            ):
                continue
            refusal_lines.update(
                range(node.lineno, (getattr(node, "end_lineno", node.lineno) or 0) + 1)
            )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in targets:
                continue
            receiver = ast.unparse(func.value)
            if not any(
                key in receiver.lower() for key in ("reader", "pipeline")
            ):
                continue
            declared = next(
                (ast.unparse(k.value) for k in node.keywords if k.arg == "actor"),
                None,
            )
            if declared is None and any(k.arg is None for k in node.keywords):
                #: ``**kwargs`` 로 **그대로 넘기는** 헬퍼다. actor 를 정하는 것은
                #: 이 자리가 아니라 헬퍼를 부르는 쪽이므로 위반이 아니다.
                declared = "<전달>"
            elif declared is None and node.lineno in refusal_lines:
                #: 거부를 시험하는 자리 — 생략이 **의도**다.
                declared = "<거부 시험>"
            rows.append(
                (
                    str(path.relative_to(PROJECT_ROOT)),
                    node.lineno,
                    f"{receiver}.{func.attr}",
                    declared,
                )
            )
    return rows


def every_delta_bearing_result() -> dict[str, tuple[bool, bool]]:
    """``deltas`` 칸을 가진 production dataclass 전수 → (``.action``, ``.actor``)."""
    for module in pkgutil.walk_packages(engine.__path__, prefix="engine."):
        try:
            importlib.import_module(module.name)
        except Exception:  # pragma: no cover
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
                rows[obj.__name__] = ("action" in fields, "actor" in fields)
    return rows


# ======================================================================
# 판 — 실제 카드
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


def battle(repository, attacker: int):
    """P1 이 P0 을 직접 공격한다 — 3-F-9 ~ 3-F-12 와 같은 반례."""
    duel = live_duel(repository)
    state = duel.state.clone()
    monster = list(state.player(attacker).hand)[0]
    state.move(
        monster, Zone.MZONE, to_player=attacker, position=Position.FACEUP_ATTACK
    )
    state.turn.turn_player = attacker
    state.turn.set_phase(Phase.BATTLE)
    action = PlayerAction.attack_directly(actor=attacker, source=monster.instance_id)
    victim_before = state.player(1 - attacker).life_points
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid()
    )
    return state, execution, action, victim_before


def resolve_spell(repository, passcode: int, controller: int, *, journal=None):
    """
    실제 마법 한 장을 **해결만** 한다 (발동 절차를 거치지 않는다).

    돌려주는 것은 ``EffectResult`` — 즉 **``action`` 을 들고 있지 않은**
    결과다. 그것이 이 Phase 가 보려는 경계다.
    """
    reference = EffectRef(passcode, 0)
    state = GameState.create(
        repository,
        decks=([passcode] * 4 + [FEATHERMAN] * 12, [FEATHERMAN] * 16),
    )
    card = state.create_instance(passcode, owner=controller, zone=Zone.SZONE)
    state.turn.set_phase(Phase.MAIN1)
    result = EffectExecutor(
        lookup=EffectImplementationRegistry((reference,)), journal=journal
    ).execute(
        state,
        definition_registry().definition_for(reference),
        ResolutionContext(
            effect_ref=reference, controller=controller, source=card.instance_id
        ),
    )
    return state, result


def zone_move(kind: OperationKind, destination: Zone, *, owner: int = MINE) -> ZoneMoved:
    """주인의 카드가 자기 자리에서 움직인다 — **가해자는 적히지 않는다.**"""
    return ZoneMoved(
        movement=kind,
        card=I(9),
        source_player=owner,
        source_zone=Zone.MZONE,
        destination_player=owner,
        destination_zone=destination,
    )


# ======================================================================
# A. §1 — 현재 read() API 를 정확히 적는다
# ======================================================================


def test_01_the_actor_boundary_is_exactly_four_methods():
    """
    §1 A · B — actor 를 받는 자리는 **넷**이고 기본값은 전부 ``None`` 이다.

    ``collect_events`` 는 **받지 않는다** — 이미 읽어 둔 사건을 받으므로 그때는
    actor 가 이미 정해져 있다. 즉 **입력 경계가 한 군데로 좁혀져 있다.**
    """
    from engine.event_pipeline import _ACTOR_OMITTED

    boundary = {
        "EventReader.read": EventReader.read,
        "EventReader.read_deltas": EventReader.read_deltas,
        "EventPipeline.observe": EventPipeline.observe,
        "EventPipeline.collect": EventPipeline.collect,
    }
    #: 🔴 **Phase 3-F-14 가 기본값을 바꿨다.** 전에는 넷 다 ``None`` 이었고,
    #: 그래서 생략과 "없다고 말한 것" 이 구분되지 않았다 (``test_08`` 참조).
    #: 이제 넷 다 **같은 보초값 하나**를 쓴다 — 넷 중 하나만 ``None`` 으로
    #: 남으면 그 자리가 계약의 구멍이 되므로, **같은 것**임을 고정한다.
    for name, function in boundary.items():
        parameters = inspect.signature(function).parameters
        assert "actor" in parameters, name
        assert parameters["actor"].default is _ACTOR_OMITTED, name
        #: 문자열 주석이다 — 보초값 타입이 모듈 안에서만 쓰이는 비공개
        #: 이름이라 ``from __future__ import annotations`` 아래에서 그대로 적었다.
        assert parameters["actor"].annotation == "'int | None | _ActorOmitted'", name

    #: 보초값은 **하나**다 — 매번 새로 만들면 ``is`` 비교가 깨진다.
    assert len({id(f.__defaults__[-1]) for f in boundary.values()}) == 1

    #: 사건을 이미 들고 있는 자리는 actor 를 받지 않는다.
    assert "actor" not in inspect.signature(EventPipeline.collect_events).parameters
    assert list(inspect.signature(EventReader.read).parameters) == [
        "self",
        "result",
        "actor",
    ]


def test_02_the_actor_only_flows_into_the_context_and_is_never_compared():
    """
    §1 C — ``read()`` 안에서 actor 가 가는 곳은 **``EventContext.of`` 하나**다.

    delta 와 비교되지 않고, 검증되지 않고, 다른 어디에도 쓰이지 않는다.
    """
    read = method_code("engine/event_pipeline.py", "EventReader", "read")
    read_deltas = method_code("engine/event_pipeline.py", "EventReader", "read_deltas")

    #: read 는 그대로 넘긴다.
    assert "self.read_deltas(deltas, actor=actor)" in read
    #: read_deltas 는 문맥을 만들 때만 쓴다.
    assert "EventContext.of(self._view, actor=actor)" in read_deltas
    #: delta 와 맞춰 보는 코드가 없다.
    for forbidden in ("delta.player", "delta.to_player", "timing.actor", "== actor"):
        assert forbidden not in read_deltas, forbidden

    #: 그리고 timing 쪽은 actor 를 **받지 않는다** — 파생이다 (3-F-11 계약).
    timing_for_code = method_code("engine/event_pipeline.py", "EventReader", "_timing_for")
    assert "actor" not in timing_for_code


def test_03_no_production_code_outside_the_module_calls_read():
    """
    §1 D — **외부 production 호출자가 0개다.**

    유일한 production 호출은 ``EventPipeline.observe`` 가 **같은 모듈 안에서**
    넘기는 것이다. 즉 지금 이 입력 경계를 쓰는 production 코드가 없다 — 그래서
    계약을 고쳐도 지금 깨질 것이 없고, 반대로 **계약을 고정할 기회**다.
    """
    rows = pipeline_call_sites()
    production = [row for row in rows if not row[0].startswith("tests")]

    #: 줄 번호는 고정하지 않는다 — 3-F-11 에서 줄 번호 snapshot 이 줄줄이
    #: 깨졌고, 이 파일을 쓰면서 또 한 번 당했다. 고정하는 것은 **어느 파일의
    #: 어느 호출이 무엇을 넘기는가**다.
    assert [(row[0], row[2], row[3]) for row in production] == [
        ("engine/event_pipeline.py", "self._reader.read", "actor")
    ], production


def test_04_no_caller_omits_the_actor_any_more():
    """
    🟢 §1 E — **Phase 3-F-14 가 생략 호출을 전부 없앴다.**

    .. note::
       **이 테스트는 "절반이 선언하지 않는다" 를 pin 하고 있었다.**

       3-F-13(이 Phase)은 테스트 호출 72곳 중 **36곳이 생략**한다는 것을
       재고, 그 숫자를 근거로 "지금 필수화하면 36 자리가 바뀌므로 §10 조건 3 이
       깨진다" 고 적어 production 을 고치지 않았다.

       3-F-14 가 사용자 지시로 그 36 자리를 **전부 판단해서 고쳤다.** 그래서
       이 테스트의 고정 대상이 **반대로 뒤집힌다** — 이제 재는 것은 "생략이
       하나도 없다" 다. 이것이 계약이 실제로 지켜지는지를 보는 가장 강한
       단정이고, 새 생략이 하나라도 들어오면 걸린다.
    """
    myself = "tests/test_event_reader_actor_input_boundary.py"
    rows = [row for row in pipeline_call_sites() if row[0].startswith("tests")]

    omitted = [row for row in rows if row[3] is None]
    #: 🔴 **계약을 지키지 않은 생략이 0곳이다.** 숫자가 늘면 새는 자리가 생긴
    #: 것이다. (``with pytest.raises`` 안의 생략은 **거부를 시험하는 자리**라서
    #: ``<거부 시험>`` 으로 따로 센다 — 그것을 위반으로 세면 "생략이 거부된다"
    #: 를 시험할 방법 자체가 없어진다.)
    assert omitted == [], omitted
    #: 거부를 **직접** 시험하는 자리가 여럿 있다. (헬퍼를 거쳐 거부를 시험하는
    #: 자리는 여기 안 잡힌다 — ``reader.read(...)`` 모양만 센다.)
    refusal = [row for row in rows if row[3] == "<거부 시험>"]
    assert len(refusal) >= 3, refusal
    assert len(rows) >= 72, len(rows)

    #: production 쪽도 생략하지 않는다 (유일한 호출이 그대로 넘긴다).
    production = [row for row in pipeline_call_sites() if not row[0].startswith("tests")]
    assert all(row[3] == "actor" for row in production), production

    #: ``actor=None`` 을 **명시**하는 자리는 이제 여럿이다 — 페이즈 전환처럼
    #: 행위자가 없는 사건을 읽는 곳들이고, 그것이 계약이 요구하는 모양이다.
    said_none = [row for row in rows if row[3] == "None"]
    assert len(said_none) >= 3, said_none
    assert any(row[0] == myself for row in rows)


def test_05_read_has_nothing_to_infer_an_actor_from():
    """
    §1 F · G — ``read()`` 가 actor 를 **추론할 재료가 없다.**

    들고 있는 것은 ``GameStateView`` 하나다. 체인도, 우선권도, 실행기도
    **모른다** — 모듈 설명이 "실행기를 알면 실행기가 사건을 만들어야 한다는
    뜻이 된다" 고 적어 둔 그대로다.

    그래서 §1 G 의 답은 **"아니다"** — ``read()`` 가 추론해야 하는 구조가
    아니다. 추론하려면 지금 일부러 거부하고 있는 의존을 들여와야 한다.
    """
    assert EventReader.__slots__ == ("_view",)

    #: **코드**에 실행기가 없다 — 설명에는 "모른다" 는 문장으로 나오므로
    #: 문자열을 지운 뒤 센다 (``code_only`` 의 note 참고).
    pipeline_code = code_only("engine/event_pipeline.py")
    for absent in (
        "ActionExecutor",
        "TurnProgressor",
        "EffectExecutor",
        "Chain",
        "PriorityState",
        "Duel",
    ):
        assert absent not in pipeline_code, absent

    #: import 목록으로 한 번 더 확인한다 — 들여온 것이 값 타입과 관측뿐이다.
    imports = imported_names("engine/event_pipeline.py")
    assert not {
        name
        for name in imports
        if any(
            key in name
            for key in ("duel", "executor", "progression", "chain", "activation")
        )
    }, imports
    assert "engine.game_state_view" in imports

    #: 그리고 관측에는 actor 라는 말이 없다.
    assert "actor" not in source_of("engine/game_state_view.py")


# ======================================================================
# B. §11 1~3 — 세 가지 입력 방식
# ======================================================================


def test_06_declaring_an_actor_explicitly_wins(repository):
    """§11 1 — **명시 전달**: 선언이 파생을 이긴다."""
    state, execution, action, _ = battle(repository, THEIRS)
    assert action.actor == THEIRS

    declared = read_with(state, execution, actor=MINE)
    assert [o.context.actor for o in declared] == [MINE]
    #: 파생값과 달라도 예외가 없다 — 3-F-11 이 적은 "넘기는 쪽의 책임" 이다.
    assert action.actor != MINE


def test_07_omitting_the_actor_is_now_refused(repository):
    """
    🟢 §11 2 — **생략은 거부된다.**

    .. note::
       **전에는 ``action.actor`` 가 들어왔다.** 3-F-13 은 그 자동 파생을 "설계
       A 가 이미 켜져 있다" 는 사실로 고정했고, 같은 Phase 가 그것을 계약에서
       빼라고 판정했다 (C). 3-F-14 가 지웠으므로 이 테스트는 **거부**를
       고정한다.
    """
    state, execution, action, _ = battle(repository, THEIRS)
    assert action.actor == THEIRS
    assert execution.action.actor == THEIRS  # 결과는 여전히 알고 있다

    with pytest.raises(TypeError) as omitted:
        read_with(state, execution)
    #: 그런데 ``read()`` 는 그것을 **쓰지 않는다** — 부르는 쪽이 말해야 한다.
    assert "부르는 쪽만 압니다" in str(omitted.value)


def test_08_an_explicit_none_is_now_different_from_an_omission(repository):
    """
    🟢 §11 3 · §6 B — **세 모양이 서로 다른 결과를 낸다.**

    .. note::
       **이 테스트가 이 Phase 계열의 핵심 결함을 pin 하고 있었다.**

       3-F-12 가 "구별되지 않는다" 를 측정하고, 3-F-13(이 Phase)이 "보초값
       하나로 가를 수 있는데 그 자리가 비어 있다" 고 적었고, 3-F-14 가 그
       보초값을 넣었다. 그래서 고정 대상이 **구별 불가**에서 **구별**로
       뒤집힌다.
    """
    state, execution, _, _ = battle(repository, THEIRS)

    #: ① 생략 → TypeError
    with pytest.raises(TypeError):
        read_with(state, execution)
    #: ② 없다고 말함 → None
    assert [o.context.actor for o in read_with(state, execution, actor=None)] == [None]
    #: ③ 값 → 그 값
    assert [o.context.actor for o in read_with(state, execution, actor=MINE)] == [MINE]

    #: 코드가 그렇게 쓰여 있다 — 보초값이 있고 ``actor is None`` 분기가 없다.
    read_deltas = method_code("engine/event_pipeline.py", "EventReader", "read_deltas")
    assert "actor is _ACTOR_OMITTED" in read_deltas
    read = method_code("engine/event_pipeline.py", "EventReader", "read")
    assert "if actor is None" not in read


# ======================================================================
# C. §4 · §7 — 사건별 입력 책임
# ======================================================================


def test_09_the_gift_of_greed_hides_the_actor_from_every_delta_field(repository):
    """
    🔴 §4 의 결정적 사례 — **강욕의 보은** (실제 카드 `5915629`).

    P0 이 발동하면 **P1 이 2장 드로우한다.** delta 의 **모든 사람 칸이 1**
    이고, 행위자 **0 은 delta 어디에도 없다.**

    → 설계 A (delta 파생) 로는 이 사건의 행위자를 **영원히 알 수 없다.**
    행위자를 아는 곳은 셋뿐이다: ``ResolutionContext.controller`` ·
    ``EffectEvent.actor`` · **호출자**.
    """
    journal = EventJournal()
    state, result = resolve_spell(
        repository, THE_GIFT_OF_GREED, MINE, journal=journal
    )
    assert isinstance(result, EffectResult)
    assert len(result.deltas) == 2

    #: 모든 delta 의 사람 칸이 **상대**다.
    for delta in result.deltas:
        assert isinstance(delta, CardDrawn)
        people = {
            name: getattr(delta, name)
            for name in dir(delta)
            if "player" in name and not name.startswith("_")
        }
        assert people and set(people.values()) == {THEIRS}, people

    #: 귀속자는 상대가 맞다 — 그것은 틀린 값이 아니다.
    #: 🔴 3-F-14: 행위자를 **말해야** 읽을 수 있다. 전에는 생략하면 비어 있었다.
    with pytest.raises(TypeError):
        read_with(state, result)
    observed = read_with(state, result, actor=None)
    assert [o.actor for o in observed] == [THEIRS, THEIRS]
    #: "없다" 고 말했으므로 비어 있다 — 자동으로 채워지지 않는다.
    assert [o.context.actor for o in observed] == [None, None]
    #: 선언하면 들어간다.
    assert [o.context.actor for o in read_with(state, result, actor=MINE)] == [
        MINE,
        MINE,
    ]

    #: journal 은 알고 있었다 — 그런데 ``read()`` 가 보지 않는다 (3-F-12).
    assert journal.events[0].actor == MINE
    assert [
        o.context.actor for o in read_with(state, journal.events[0], actor=None)
    ] == [None, None]


def test_10_rain_of_mercy_proves_the_two_actors_have_different_cardinality(repository):
    """
    🔴 §4 — **자비의 비** (실제 카드 `66719324`).

    한 번의 실행이 **귀속자가 다른 delta 둘** 을 낸다 (P0 · P1). 행위자는
    **하나** (P0) 다.

    즉 두 actor 는 값만 다른 것이 아니라 **개수가 다르다.**

    * ``TimingEvent.actor`` — **delta 마다** 하나 (파생)
    * ``EventContext.actor`` — **묶음마다** 하나 (선언)

    그래서 ``EventContext.at(index)`` 가 같은 actor 를 옮겨 적는 설계가 맞다.
    사건마다 다른 행위자를 넣을 자리는 **있어서는 안 된다** — 한 번의 행위가
    여러 사람의 상태를 바꾸는 것이 정상이기 때문이다.
    """
    state, result = resolve_spell(repository, RAIN_OF_MERCY, MINE)
    assert len(result.deltas) == 2
    assert all(isinstance(delta, LifeChanged) for delta in result.deltas)

    #: 귀속자가 둘이다.
    observed = read_with(state, result, actor=MINE)
    assert sorted(o.actor for o in observed) == [MINE, THEIRS]
    #: 행위자는 하나다 — 두 사건이 **같은 문맥 actor** 를 공유한다.
    assert {o.context.actor for o in observed} == {MINE}
    #: 순번만 다르다.
    assert [o.context.sequence for o in observed] == [0, 1]


def test_11_the_zone_moved_family_records_the_owner_not_the_agent():
    """
    🔴 §4 6~10 — 파괴 · 패로 · 버리기 · 제외 · 덱으로.

    다섯 **다 클래스가 아니다.** 전부 ``ZoneMoved`` 이고 ``OperationKind`` 로만
    갈린다 (3-F-9 가 센 그대로다). 그리고 ``ZoneMoved`` 의 두 사람 칸은
    **모두 카드 주인**이다 — **가해자를 담는 칸이 없다.**

    그래서 "상대가 내 카드를 파괴했다" 를 delta 만 보고는 알 수 없다.
    """
    delta_names = set()

    def collect(cls):
        for child in cls.__subclasses__():
            delta_names.add(child.__name__)
            collect(child)

    for module in pkgutil.walk_packages(engine.__path__, prefix="engine."):
        try:
            importlib.import_module(module.name)
        except Exception:  # pragma: no cover
            continue
    from engine.effect.delta import StateDelta

    collect(StateDelta)
    for absent in (
        "CardDestroyed",
        "CardAddedToHand",
        "CardDiscarded",
        "CardBanished",
        "CardReturned",
    ):
        assert absent not in delta_names, absent

    for kind, destination in (
        (OperationKind.DESTROY, Zone.GRAVE),
        (OperationKind.RETURN_TO_HAND, Zone.HAND),
        (OperationKind.DISCARD, Zone.GRAVE),
        (OperationKind.BANISH, Zone.REMOVED),
        (OperationKind.RETURN_TO_DECK, Zone.DECK),
    ):
        delta = zone_move(kind, destination, owner=MINE)
        timing = timing_for(delta)
        assert timing.point is TimingPoint.CARD_MOVED
        #: 귀속자는 **도착지 주인** = 카드 주인이다.
        assert timing.actor == MINE
        assert delta.source_player == delta.destination_player == MINE

    #: 칸 자체가 둘뿐이고, 같은 주인 안에서 움직이면 둘이 같다.
    assert {
        name for name in ZoneMoved.__dataclass_fields__ if "player" in name
    } == {"source_player", "destination_player"}

    #: 🔴 **두 칸이 갈리는 경우를 반드시 같이 고정한다.**
    #:
    #: 위의 다섯 사건은 출발지와 도착지 주인이 **같아서**, 귀속자가
    #: ``destination_player`` 인지 ``source_player`` 인지 가려 주지 못한다.
    #: (실제로 이 Phase 의 고의 위반 7번 — ``actor=delta.source_player`` 로
    #: 바꾸는 주입 — 이 여기서 **걸리지 않았다.** 그래서 이 단정을 더했다.)
    #:
    #: 컨트롤이 넘어가는 이동에서 귀속자는 **도착지 주인**이다 (3-F-9 계약).
    handed_over = ZoneMoved(
        movement=OperationKind.MOVE,
        card=I(12),
        source_player=MINE,
        source_zone=Zone.MZONE,
        destination_player=THEIRS,
        destination_zone=Zone.MZONE,
    )
    assert timing_for(handed_over).actor == THEIRS
    assert handed_over.source_player == MINE
    #: 즉 "내가 내 카드를 넘겼다" 인데 귀속자는 상대다 — 행위자가 아니다.


def test_12_but_a_summon_delta_does_carry_the_agent():
    """
    §4 1 — **``MonsterSummoned`` 은 행위자를 담는다.**

    ``player`` (소환한 사람) 와 ``owner`` (카드 주인) 를 **둘 다** 들고 있고,
    ``from_delta`` 는 ``player`` 를 고른다.

    🔴 **그래서 "delta 에서 파생" 은 계약이 될 수 없다.** delta 가 행위자를
    담을 때도 있고 (``MonsterSummoned``) 안 담을 때도 있는데
    (``ZoneMoved`` · ``CardDrawn`` · ``LifeChanged``), ``read()`` 는 둘을
    **구분할 근거가 없다.** 같은 규칙으로 읽으면 어떤 사건에서는 행위자를,
    어떤 사건에서는 피해자를 집는다.
    """
    fields = {f.name for f in dataclasses.fields(MonsterSummoned)}
    assert {"player", "owner"} <= fields

    #: 남의 묘지에서 내가 특수 소환하는 모양 — 두 칸이 갈린다.
    delta = MonsterSummoned(
        summon=SummonKind.SPECIAL,
        card=I(4),
        player=MINE,
        owner=THEIRS,
        from_zone=Zone.GRAVE,
        to_zone=Zone.MZONE,
        to_index=0,
        position=Position.FACEUP_ATTACK,
    )
    assert timing_for(delta).actor == MINE != delta.owner

    #: 반면 드로우 · 라이프에는 사람 칸이 **하나뿐**이고 그것이 귀속자다.
    assert {f.name for f in dataclasses.fields(CardDrawn) if "player" in f.name} == {
        "player"
    }
    assert {f.name for f in dataclasses.fields(LifeChanged) if "player" in f.name} == {
        "player"
    }


def test_13_the_phase_change_has_player_fields_yet_contracts_actor_to_none():
    """
    🔴 §6 A — ``INTENTIONAL_NONE`` 은 **데이터가 없어서가 아니다.**

    ``PhaseChanged`` 는 ``from_player`` · ``to_player`` 를 **들고 있다.** 그런데
    ``from_delta`` 가 actor 를 **일부러 넣지 않는다.** 즉 ``None`` 은 **계약이
    정한 것**이고, 그래서 "actor 가 없다" 와 "actor 를 안 넣었다" 가 코드에서
    같은 모양으로 나온다.
    """
    fields = {f.name for f in dataclasses.fields(PhaseChanged) if "player" in f.name}
    assert fields == {"from_player", "to_player"}

    delta = PhaseChanged(
        from_turn=1,
        from_player=MINE,
        from_phase=Phase.MAIN1,
        to_turn=1,
        to_player=MINE,
        to_phase=Phase.BATTLE,
    )
    assert delta.from_player == delta.to_player == MINE
    #: 데이터가 있는데도 actor 는 None 이다.
    assert timing_for(delta).actor is None

    from_delta = method_code("engine/trigger.py", "TimingEvent", "from_delta")
    assert "TimingPoint.PHASE_CHANGED, delta=delta)" in from_delta
    assert "actor=delta.from_player" not in from_delta
    assert "actor=delta.to_player" in from_delta  # ZoneMoved 쪽에만 있다


def test_14_the_battle_actor_lives_only_in_the_action(repository):
    """
    §7 — Battle 반례. LP 8000 → **6100**.

    delta 는 ``LifeChanged(player=0)`` **하나뿐**이고 그 사람 칸은 **맞은 쪽**
    이다. 공격한 P1 은 **``action.actor`` 에만** 있다.

    §7 의 질문에 답한다.

    * "``read()`` 가 스스로 P1 을 읽어야 하는가?" — ``action.actor`` 는
      **행위의 정의**이므로 읽어도 틀리지 않는다. 다만 그것은 **``action`` 을
      들고 있는 결과에서만** 가능하고, 7개 result 중 **둘**뿐이다.
    * "호출자가 P1 을 책임져야 하는가?" — 나머지 **다섯**에서는 호출자밖에
      답할 수 없다. 그래서 책임은 호출자에게 있고, 파생은 **편의**다.
    """
    state, execution, action, victim_before = battle(repository, THEIRS)
    assert victim_before == 8000
    assert state.player(MINE).life_points == 6100

    assert len(execution.deltas) == 1
    delta = execution.deltas[0]
    assert isinstance(delta, LifeChanged)
    assert delta.player == MINE  # 맞은 쪽

    #: 공격자는 delta 어디에도 없다.
    people = {
        name: getattr(delta, name)
        for name in dir(delta)
        if "player" in name and not name.startswith("_")
    }
    assert set(people.values()) == {MINE}
    #: action 에만 있다.
    assert action.actor == THEIRS
    assert execution.action.actor == THEIRS

    observed = read_with(state, execution, actor=action.actor)
    assert observed[0].actor == MINE
    assert observed[0].context.actor == THEIRS


# ======================================================================
# D. §5 — 결과 타입별 경계
# ======================================================================


def test_15_the_seven_results_split_into_three_responsibility_groups():
    """
    §5 — 7개 result 를 **책임**으로 가른다 (3-F-12 는 구조로 갈랐다).

    ============================  ================  ==========================
    result                         actor 를 아는가    누가 책임지는가
    ============================  ================  ==========================
    ``ActionExecution``            ``action.actor``  파생 가능 — **정의상 안전**
    ``ActivationResult``           ``action.actor``  파생 가능 — **정의상 안전**
    ``EffectEvent``                ``actor``         🟡 **개념이 다르다** (지배자)
    ``CostPaymentEvent``           ``actor``         🟡 **개념이 다르다** (지불자)
    ``EffectResult``               모른다             **호출자뿐**
    ``CostPaymentResult``          모른다             **호출자뿐**
    ``ProgressionResult``          없다               **아무도** (의도된 없음)
    ============================  ================  ==========================
    """
    rows = every_delta_bearing_result()
    assert rows == {
        "ActionExecution": (True, False),
        "ActivationResult": (True, False),
        "EffectEvent": (False, True),
        "CostPaymentEvent": (False, True),
        "EffectResult": (False, False),
        "CostPaymentResult": (False, False),
        "ProgressionResult": (False, False),
    }, rows

    derivable_from_action = {name for name, (a, _) in rows.items() if a}
    carries_own_actor = {name for name, (_, b) in rows.items() if b}
    knows_nothing = {
        name for name, (a, b) in rows.items() if not a and not b
    }
    assert len(derivable_from_action) == 2
    assert len(carries_own_actor) == 2
    assert knows_nothing == {
        "EffectResult",
        "CostPaymentResult",
        "ProgressionResult",
    }

    #: 설계 A 가 덮을 수 있는 최대치는 **4/7** 이고, 안전한 것은 **2/7** 이다.
    assert len(derivable_from_action | carries_own_actor) == 4


def test_16_the_journal_actor_is_a_different_concept_not_a_free_win():
    """
    🟡 §5 — journal 의 actor 를 그대로 쓰면 **개념을 바꿔 쓰는 것**이다.

    ``EffectEvent.actor = ResolutionContext.controller`` 이고
    ``CostPaymentEvent.actor = PaymentContext.payer`` 다. 둘 다 "행위의 주체" 와
    **지금은 값이 같지만** (Engine V1 에 컨트롤 이동이 없다) **뜻이 다르다.**

    그래서 설계 A 의 "4/7" 중 **둘은 공짜가 아니다.** 사용자의 기준 — 추측해서
    구조화하지 않는다 — 에 따라 이것을 파생 근거로 세지 않는다.
    """
    executor = method_code("engine/effect/executor.py", "EffectExecutor", "execute")
    assert "actor=context.controller" in executor
    assert "actor=context.actor" not in executor
    assert "actor=context.payer" in source_of("engine/payment.py")

    #: 두 문맥에 ``actor`` 칸이 **없다** — 개념이 다르다는 구조적 증거다.
    assert "actor" not in {f.name for f in dataclasses.fields(ResolutionContext)}
    assert "controller" in {f.name for f in dataclasses.fields(ResolutionContext)}
    assert "actor" not in {f.name for f in dataclasses.fields(PaymentContext)}
    assert "payer" in {f.name for f in dataclasses.fields(PaymentContext)}


# ======================================================================
# E. §6 — None 을 세 가지로 가른다
# ======================================================================


def test_17_intentional_none_a_phase_change_has_no_agent(repository):
    """
    §6 A — ``INTENTIONAL_NONE``.

    페이즈 전환에는 semantic actor 가 **없다.** 두 actor 가 다 ``None`` 이고,
    그것이 **맞는 값**이다. 이 테스트는 ``None`` 을 **기대한다** — 실패로
    보지 않는다.
    """
    duel = live_duel(repository)
    state = duel.state.clone()
    progression = TurnProgressor().advance(state)
    assert isinstance(progression, ProgressionResult)
    assert progression.deltas

    #: 🔴 3-F-14: "행위자가 없다" 를 **적어서** 말한다. 그것이
    #: ``INTENTIONAL_NONE`` 의 새 모양이다.
    for event in read_with(state, progression, actor=None):
        assert event.point is TimingPoint.PHASE_CHANGED
        assert event.actor is None
        assert event.context.actor is None

    #: 결과 어디에도 사람 칸이 없다 — 채울 값이 없다.
    assert not {
        f.name for f in dataclasses.fields(ProgressionResult)
    } & {"actor", "action", "player"}


def test_18_the_omitted_input_class_no_longer_exists(repository):
    """
    🟢 §6 B — **``OMITTED_INPUT`` 이 사라졌다.**

    .. note::
       **이 테스트가 §6 이 금지한 바로 그 상태를 pin 하고 있었다.**

       3-F-13(이 Phase)은 "강욕의 보은의 행위자는 P0 으로 **존재하는데** 선언
       없이 읽으면 ``None`` 이 되고, 그 ``None`` 이 페이즈 전환의 ``None`` 과
       **같은 값**이다" 를 결함으로 고정했다 — 즉 **B 를 A 로 처리**하는 것이
       기본 동작이었다.

       3-F-14 가 생략을 ``TypeError`` 로 바꿨으므로 **B 라는 분류 자체가
       사라졌다.** 남은 것은 A(없다고 말함)와 선언값뿐이다. 그래서 이 테스트는
       "구별 불가능성" 대신 **"B 가 더 이상 만들어지지 않는다"** 를 고정한다.
    """
    state, result = resolve_spell(repository, THE_GIFT_OF_GREED, MINE)

    #: 🔴 전에는 여기서 ``None`` 이 나왔다. 이제 거부된다 — B 가 생기지 않는다.
    with pytest.raises(TypeError) as omitted:
        read_with(state, result)
    assert "actor 를 말해야 합니다" in str(omitted.value)

    #: 행위자는 **존재했다** — 선언하면 그 값이 들어온다.
    assert [o.context.actor for o in read_with(state, result, actor=MINE)] == [
        MINE,
        MINE,
    ]

    #: 그리고 A(없다고 말함)는 여전히 ``None`` 이다 — 두 뜻이 이제 **입력 쪽에서**
    #: 갈린다. 문맥에 까닭을 적는 칸이 없어도 되는 이유가 그것이다.
    duel = live_duel(repository)
    phase_state = duel.state.clone()
    intentional = read_with(
        phase_state, TurnProgressor().advance(phase_state), actor=None
    )
    assert intentional[0].context.actor is None
    #: 칸은 그대로 다섯이다 — ``provenance`` 를 더하지 않았다 (§9).
    assert not {f.name for f in dataclasses.fields(EventContext)} & {
        "actor_source",
        "provenance",
        "note",
    }


def test_19_unknown_a_cost_payment_result_is_not_even_mentioned():
    """
    §6 C — ``UNKNOWN``.

    ``CostPaymentResult`` 는 actor 칸도 없고, ``read()`` 의 설명에 **예시로도
    나오지 않는다.** 그래서 "선언해야 하는가" 조차 코드에 적혀 있지 않다 —
    ``OMITTED_INPUT`` 으로 분류하기에도 근거가 모자란다.
    """
    fields = {f.name for f in dataclasses.fields(CostPaymentResult)}
    assert "deltas" in fields
    assert not fields & {"actor", "action"}

    read_doc = ast.get_docstring(
        next(
            child
            for node in ast.walk(ast.parse(source_of("engine/event_pipeline.py")))
            if isinstance(node, ast.ClassDef) and node.name == "EventReader"
            for child in node.body
            if isinstance(child, ast.FunctionDef) and child.name == "read"
        )
    )
    #: 🔴 **Phase 3-F-14 가 설명을 고쳤다 — 이제 일곱을 전부 적는다.**
    #: 그래서 ``CostPaymentResult`` 가 "언급조차 없다" 는 근거는 **사라졌다.**
    #: 그렇다고 이 result 의 actor 를 알게 된 것은 아니다 — 아래 단정이 그
    #: 사실을 그대로 고정한다.
    for named in (
        "ActionExecution",
        "ActivationResult",
        "EffectResult",
        "CostPaymentResult",
        "ProgressionResult",
        "EffectEvent",
        "CostPaymentEvent",
    ):
        assert named in read_doc, named

    #: 🟡 분류는 ``UNKNOWN`` 그대로다 — 이제 **반드시 선언해야** 하므로, 부르는
    #: 쪽이 무엇을 선언해야 하는지는 여전히 코드가 말해 주지 않는다. 3-F-14 가
    #: 고친 것은 "말하지 않아도 통과하는 것" 이고, "무엇을 말해야 하는지" 가
    #: 아니다.
    assert "actor" not in {f.name for f in dataclasses.fields(CostPaymentResult)}


# ======================================================================
# F. §2 — 설계 C 를 코드 근거로 배제한다
# ======================================================================


def test_20_design_c_would_create_a_new_disagreement(repository):
    """
    §2 설계 C — **문맥을 주입하면 새 불일치가 생긴다.**

    ``EventContext.of`` 는 turn · phase 를 **관측에서 읽는다.** 호출자가 문맥을
    만들어 넘기면 그 셋이 관측과 **갈릴 수 있고**, 아무도 맞춰 보지 않는다.

    지금은 그런 자리가 **없다** — 문맥은 ``read_deltas`` 안에서만 생기므로
    turn · phase 는 **언제나** 관측과 같다. 설계 C 는 그 보장을 **버리는**
    선택이다.
    """
    of_code = method_code("engine/event_pipeline.py", "EventContext", "of")
    for field in ("view.turn_number", "view.turn_player", "view.phase"):
        assert field in of_code, field

    #: 실제로 관측과 일치한다.
    duel = live_duel(repository)
    state = duel.state.clone()
    progression = TurnProgressor().advance(state)
    view = GameStateView.from_state(state, viewer=MINE)
    for event in EventReader(view).read(progression, actor=None):
        assert event.context.turn_number == view.turn_number
        assert event.context.turn_player == view.turn_player
        assert event.context.phase == view.phase

    #: 그리고 ``read`` 는 문맥을 **받지 않는다** — 설계 C 는 새 매개변수다.
    assert "context" not in inspect.signature(EventReader.read).parameters
    assert "context" not in inspect.signature(EventReader.read_deltas).parameters


# ======================================================================
# G. §12 · §13 — 계약 유지와 AUDIT-ONLY
# ======================================================================


def test_21_the_three_f_eleven_contracts_are_untouched():
    """
    §12 — 3-F-11 의 계약을 그대로 둔다.

    ``TimingEvent.actor`` = 귀속자 · ``EventContext.actor`` = 행위자 ·
    ``ObservedEvent.actor`` = 사건 자체가 밝히는 주체 (문맥으로 떨어지지
    않는다).
    """
    timing_doc = source_of("engine/trigger.py")
    assert "**행위의 주체가 아니다**" in timing_doc
    assert "이 사건을 일으킨 플레이어" not in timing_doc

    pipeline = source_of("engine/event_pipeline.py")
    assert "부르는 쪽이 선언한다" in pipeline
    assert "맞춰 보지 않는다" in pipeline

    observed = method_code("engine/event_pipeline.py", "ObservedEvent", "actor")
    assert observed == "return self.timing.actor"

    #: EVENT_RELATION · TriggerRegistry 는 production 에 연결되지 않았다.
    assert "EVENT_RELATION" not in source_of("engine/duel.py")
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


def test_22_this_phase_changed_no_production_file():
    """
    §13 — **이 Phase(3-F-13)는 production 을 한 줄도 바꾸지 않았다.**

    .. note::
       **Phase 3-F-14 에서 재는 방법을 바꿨다.**

       전에는 ``git diff HEAD`` 와 ``read`` 본문 전문을 고정했다. 둘 다 **뒤의
       Phase 가 production 을 바꾸면 그 Phase 때문에 깨진다** — 재려던 것은
       "3-F-13 이 무엇을 바꿨나" 인데 잰 것은 "지금 나무가 어떤가" 였다.

       그래서 **이 Phase 의 작업 commit 자체**를 본다. ``2eef3f9`` 가 건드린
       파일 목록은 영원히 바뀌지 않는다. 그리고 본문 고정은 §9 의 금지 항목
       확인으로 바꾼다 — 그것은 어느 Phase 에서도 참이어야 하는 것이다.
    """
    PHASE_3F13_WORK = "2eef3f9"
    shown = subprocess.run(
        ["git", "show", "--stat", "--format=", PHASE_3F13_WORK],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    touched = [line.split("|")[0].strip() for line in shown.splitlines() if "|" in line]
    assert touched == ["tests/test_event_reader_actor_input_boundary.py"], touched
    for path in touched:
        assert not path.startswith(PRODUCTION_ROOTS), path

    #: §9 의 금지 항목은 **지금도** 들어오지 않았다.
    pipeline = source_of("engine/event_pipeline.py")
    for forbidden in (
        "cause_player",
        "affected_player",
        "action_player",
        "actor_player",
        "ActorKind",
        "ActorSource",
        "EventActor",
    ):
        assert forbidden not in pipeline, forbidden

    #: 그리고 3-F-14 가 더한 것은 **보초값 하나**뿐이다 — 새 field 도, 새 enum 도
    #: 아니다. ``EventContext`` 의 칸이 다섯 그대로인 것이 그 증거다.
    assert [f.name for f in dataclasses.fields(EventContext)] == [
        "turn_number",
        "turn_player",
        "phase",
        "actor",
        "sequence",
    ]


def test_23_reading_events_leaves_the_board_and_the_rng_alone(repository):
    """§13 — ``state_hash`` · RNG 불변. 관측만 들고 있어서 바꿀 것이 없다."""
    state, execution, _, _ = battle(repository, THEIRS)
    before = state.state_hash()
    read_with(state, execution, actor=THEIRS)
    read_with(state, execution, actor=MINE)
    read_with(state, execution, actor=None)
    view = GameStateView.from_state(state, viewer=MINE)
    EventReader(view).read_deltas(execution.deltas, actor=THEIRS)
    assert state.state_hash() == before

    spell_state, result = resolve_spell(repository, RAIN_OF_MERCY, MINE)
    spell_before = spell_state.state_hash()
    read_with(spell_state, result, actor=MINE)
    assert spell_state.state_hash() == spell_before

    assert (
        live_duel(repository, seed=11).state.state_hash()
        == live_duel(repository, seed=11).state.state_hash()
    )

    with pytest.raises(TypeError):
        EventReader(state)  # GameState 를 거부한다 — hidden-information 경계
