"""
Phase 3-F-15 — **Actor Declaration Scope** / actor 없는 result 의 계약 감사.

이 파일이 답하는 단 하나의 질문
-------------------------------
어떤 result 에서 actor 를 **선언해야** 하고, 어떤 result 에서 ``actor=None`` 이
**정당**하며, actor 가 없는 result 에 ``controller``/``player`` 를 억지로 actor 로
넣으면 **안 되는가**.

3-F-14 의 계약은 그대로 둔다 (``test_23``)
------------------------------------------
``read(r, actor=0|1)`` → 선언 · ``read(r, actor=None)`` → 없음 · ``read(r)`` →
``TypeError``.

🔴 이 Phase 가 새로 찾은 것 셋
-----------------------------
1. **``CostPaymentResult`` 는 UNKNOWN 이 아니다.** 3-F-14 가 그렇게 분류했는데,
   실제로는 payer 가 상류(``PaymentContext.payer``)에 **있고** 결과가 들고 나오지
   않는 것이다 — §7 의 **B(ACTOR_EXISTS_BUT_NOT_CARRIED)** 다.
2. 🔴 **``CostPayment.player`` 는 actor 가 아니라 affected player 다.**
   ``LifeCost(who=OPPONENT)`` 로 재면 ``CostPayment.player == 1`` 인데
   ``CostPaymentEvent.actor == 0`` 이다. 결과 안에 사람 칸이 **있지만** 그것을
   actor 로 쓰면 §3 이 금지한 바로 그 혼동이다.
3. 🟡 **``controller == actor`` 는 게임 규칙이 아니라 대입 때문이다.**
   ``PlayerAction.actor`` → ``ChainLink.actor`` → ``ResolutionContext.controller``
   로 **한 줄씩 대입**된다 (``engine/activation.py`` → ``engine/chain.py``). 지금
   참인 까닭이 구조이므로, 컨트롤 이동이 구현되면 다시 봐야 한다.

네 개념을 섞지 않는다 (§3)
--------------------------
=====================  ====================================================
``actor``               사건을 **일으킨** 행위 주체
``controller``          **둘이다** — 효과의 컨트롤러(= actor) 와 **카드의**
                        컨트롤러(≠ actor). 같은 말이 다른 것을 가리킨다.
``player``              결과·상태가 **귀속**되는 플레이어
affected player         변화의 **영향을 받은** 플레이어
=====================  ====================================================
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
from engine.chain import Chain, ChainLink
from engine.condition import PlayerRef
from engine.cost import Selection
from engine.cost.model import CostGroup, LifeCost
from engine.cost.receipt import CostPayment, CostSemantics
from engine.duel import Duel
from engine.effect.delta import CardDrawn, LifeChanged, ZoneMoved
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import CostPaymentEvent, EffectEvent, EventJournal
from engine.effect.library import definition_registry
from engine.effect.operation import OperationKind
from engine.effect.resolution import (
    EffectResult,
    ResolutionContext,
    TargetSelection,
)
from engine.effect.target import PRIMARY_TARGET
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.payment import CostPayer, CostPaymentResult, PaymentContext
from engine.state.game_state import GameState
from engine.summon import duel_executor
from engine.trigger import TimingPoint, timing_for
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
#: 욕망의 항아리 — 내가 2장 뽑는다.
POT_OF_GREED = 55144522
#: 천사의 자비(Dian Keto) — 내 LP 가 1000 늘어난다.
DIAN_KETO = 84257639
#: 자비의 비 — **양쪽** LP 가 늘어난다.
RAIN_OF_MERCY = 66719324
#: 강욕의 보은 — **상대가** 2장 뽑는다.
THE_GIFT_OF_GREED = 5915629
#: 졸부 고블린 — 내가 1장 뽑고 **상대** LP 가 1000 늘어난다.
UPSTART_GOBLIN = 70368879
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


def reader_for(state, *, viewer: int = MINE) -> EventReader:
    return EventReader(GameStateView.from_state(state, viewer=viewer))


def resolve_spell(repository, passcode: int, controller: int, *, journal=None):
    """실제 마법 한 장을 **해결만** 한다 → ``EffectResult``."""
    reference = EffectRef(passcode, 0)
    state = GameState.create(
        repository, decks=([passcode] * 4 + [FEATHERMAN] * 12, [FEATHERMAN] * 16)
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


def pay_life(repository, who: PlayerRef, *, payer: int = MINE):
    """
    **synthetic 비용**을 치른다.

    .. note::
       실제 카드로는 이 경로를 밟을 수 없다 — 라이브러리 16장 전부
       ``CostGroup(costs=())`` 다 (``test_22``). 그래서 어떤 실제 카드의 의미도
       주장하지 않는 synthetic 비용을 쓴다. 보는 것은 **비용 계층이 사람을 어느
       칸에 적는가** 하나다.
    """
    state = GameState.create(
        repository, decks=([LUSTER_DRAGON] * 12, [LUSTER_DRAGON] * 12)
    )
    state.turn.set_phase(Phase.MAIN1)
    journal = EventJournal()
    result = CostPayer(journal=journal).pay(
        state,
        CostGroup(costs=(LifeCost(amount=1000, who=who),)),
        PaymentContext(payer=payer, effect_ref=EffectRef(LUSTER_DRAGON, 0)),
    )
    return state, result, journal


def battle(repository, attacker: int):
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


def summon(repository, actor: int):
    duel = live_duel(repository)
    state = duel.state.clone()
    state.turn.turn_player = actor
    state.turn.set_phase(Phase.MAIN1)
    source = list(state.player(actor).hand)[0].instance_id
    action = PlayerAction.normal_summon(actor=actor, source=source)
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid("감사가 직접 허가")
    )
    return state, execution, action


# ======================================================================
# A. §4 — Result 타입별 actor 계약
# ======================================================================


def test_01_an_action_execution_carries_the_actor_through_its_action(repository):
    """
    §4 — ``ActionExecution`` → **REQUIRED_ACTOR**.

    ``action.actor`` 가 **필수 int** 다. 행위자가 언제나 존재하므로 ``actor=None``
    은 **사실과 다른 선언**이 된다 (막지는 않는다 — 3-F-14 §5 가 그 까닭을 적었다).
    """
    state, execution, action = summon(repository, MINE)
    assert isinstance(execution, ActionExecution)
    assert execution.action.actor == MINE
    #: actor 칸은 없고 action 을 통해서만 닿는다.
    fields = {f.name for f in dataclasses.fields(ActionExecution)}
    assert "action" in fields and "actor" not in fields

    #: 선언하면 그 값이 들어온다.
    observed = reader_for(state).read(execution, actor=action.actor)
    assert all(event.context.actor == MINE for event in observed)


def test_02_an_activation_result_carries_it_the_same_way(repository):
    """§4 — ``ActivationResult`` → **REQUIRED_ACTOR**. 같은 모양이다."""
    reference = EffectRef(POT_OF_GREED, 0)
    state = GameState.create(
        repository, decks=([POT_OF_GREED] * 4 + [FEATHERMAN] * 12, [FEATHERMAN] * 16)
    )
    card = state.create_instance(POT_OF_GREED, owner=THEIRS, zone=Zone.SZONE)
    action = PlayerAction.activate_effect(
        actor=THEIRS, source=card.instance_id, effect_ref=reference
    )
    result = EffectActivator(
        definition_registry(), EffectImplementationRegistry((reference,))
    ).activate(state, Chain(), action, authorization=ValidationResult.valid())

    assert isinstance(result, ActivationResult)
    assert result.action.actor == THEIRS
    fields = {f.name for f in dataclasses.fields(ActivationResult)}
    assert "action" in fields and "actor" not in fields


def test_03_the_effect_event_carries_an_actor_that_is_the_effect_controller(repository):
    """
    §4 — ``EffectEvent`` → **REQUIRED_ACTOR**, actor 를 **직접** 들고 있다.

    그 값은 ``ResolutionContext.controller`` 다 — **효과의** 컨트롤러이고,
    §6 ①에서 보듯 ``action.actor`` 에서 대입된 것이다.
    """
    journal = EventJournal()
    state, _ = resolve_spell(repository, POT_OF_GREED, MINE, journal=journal)
    event = journal.events[0]
    assert isinstance(event, EffectEvent)

    field = {f.name: f for f in dataclasses.fields(EffectEvent)}["actor"]
    assert field.default is dataclasses.MISSING      # 필수다
    assert str(field.type) == "int"                  # None 이 될 수 없다
    assert event.actor == MINE

    #: 그런데 ``read()`` 는 그 칸을 **보지 않는다** (3-F-12 의 공백, 3-F-14 에서
    #: 조용한 ``None`` 대신 ``TypeError`` 로 드러난다).
    with pytest.raises(TypeError):
        reader_for(state).read(event)
    #: 부르는 쪽이 **옮겨 적어야** 한다.
    assert all(
        o.context.actor == MINE
        for o in reader_for(state).read(event, actor=event.actor)
    )


def test_04_the_cost_payment_event_carries_the_payer_as_actor(repository):
    """
    §4 — ``CostPaymentEvent`` → **REQUIRED_ACTOR**, actor 를 직접 들고 있다.

    그 값은 ``PaymentContext.payer`` 다. 🟢 **상대가 비용을 내도 actor 는
    지불을 일으킨 쪽이다** — 그래서 이 칸은 actor 로 **옳다** (``test_08`` 이
    같은 판에서 ``CostPayment.player`` 와 갈리는 것을 보인다).
    """
    state, result, journal = pay_life(repository, PlayerRef.OPPONENT, payer=MINE)
    assert result.paid
    event = journal.events[0]
    assert isinstance(event, CostPaymentEvent)

    field = {f.name: f for f in dataclasses.fields(CostPaymentEvent)}["actor"]
    assert field.default is dataclasses.MISSING
    assert str(field.type) == "int"
    #: 🔴 상대의 LP 가 줄었는데 actor 는 **나**다.
    assert event.actor == MINE
    assert state.player(THEIRS).life_points == 7000
    assert state.player(MINE).life_points == 8000


def test_05_an_effect_result_has_no_actor_but_the_upstream_knew(repository):
    """
    §4 — ``EffectResult`` → **CONTEXT_DEPENDENT**.

    actor 칸도 action 칸도 없다. 그런데 **상류가 알고 있었다** —
    ``ResolutionContext.controller`` 다. 그래서 §7 의 **B** 이고 UNKNOWN 이
    아니다.
    """
    fields = {f.name for f in dataclasses.fields(EffectResult)}
    assert not fields & {"actor", "action", "controller", "player"}

    state, result = resolve_spell(repository, POT_OF_GREED, MINE)
    assert isinstance(result, EffectResult)
    assert result.deltas

    #: 상류의 칸 이름은 ``controller`` 다.
    assert "controller" in {f.name for f in dataclasses.fields(ResolutionContext)}
    #: 선언하면 들어오고, 생략은 거부된다.
    with pytest.raises(TypeError):
        reader_for(state).read(result)
    assert all(
        o.context.actor == MINE for o in reader_for(state).read(result, actor=MINE)
    )


def test_06_the_cost_payment_result_is_not_unknown_it_is_not_carried(repository):
    """
    🔴 §5 — **``CostPaymentResult`` 는 UNKNOWN 이 아니다.**

    3-F-14 는 이것을 ``UNKNOWN`` 으로 남겼다. 그 분류가 **너무 약했다.**

    * ``CostPaymentResult`` 에 actor · action 칸이 없다 — 여기까지는 같다.
    * 🔴 그런데 **``payments[*].player`` 가 있다.** 즉 결과 안에 사람 칸이
      있는데, 그것이 actor 가 **아니다** (``test_08``).
    * 그리고 payer 는 상류 ``PaymentContext.payer`` 에 **있다.**

    "정보가 없다" 가 아니라 **"있는데 전달되지 않는다"** — §7 의 **B** 다.
    """
    fields = {f.name for f in dataclasses.fields(CostPaymentResult)}
    assert not fields & {"actor", "action"}
    assert "payments" in fields

    #: 🔴 payments 안에는 사람 칸이 **있다.**
    payment_fields = {f.name for f in dataclasses.fields(CostPayment)}
    assert "player" in payment_fields

    #: 그리고 상류에 payer 가 있다.
    assert "payer" in {f.name for f in dataclasses.fields(PaymentContext)}

    state, result, journal = pay_life(repository, PlayerRef.CONTROLLER, payer=MINE)
    assert result.paid and result.payments
    #: 여기서는 둘이 **같다** — 그래서 "같으니까 써도 된다" 고 결론하면 틀린다.
    assert result.payments[0].player == journal.events[0].actor == MINE


def test_07_a_progression_result_has_no_actor_by_semantics(repository):
    """
    §4 — ``ProgressionResult`` → **EXPLICIT_NONE** (§7 의 **A**).

    결과 어디에도 사람 칸이 없고, 상류에도 "페이즈를 넘긴 사람" 이라는 개념이
    없다. ``TurnProgressor.advance(state)`` 는 **사람을 받지 않는다** — 그것이
    "행위자가 존재하지 않는다" 의 구조적 증거다.
    """
    fields = {f.name for f in dataclasses.fields(ProgressionResult)}
    assert not fields & {"actor", "action", "player", "controller"}

    #: 🟢 상류조차 사람을 받지 않는다.
    parameters = list(inspect.signature(TurnProgressor.advance).parameters)
    assert "actor" not in parameters and "player" not in parameters

    duel = live_duel(repository)
    state = duel.state.clone()
    progression = TurnProgressor().advance(state)
    assert progression.deltas

    observed = reader_for(state).read(progression, actor=None)
    for event in observed:
        assert event.point is TimingPoint.PHASE_CHANGED
        assert event.actor is None and event.context.actor is None


def test_08_the_cost_payment_player_is_the_affected_player_not_the_actor(repository):
    """
    🔴 §3 · §5 — **``CostPayment.player`` 는 actor 가 아니다.**

    ``LifeCost(who=OPPONENT)`` 로 재면 한 판에서 둘이 **갈린다**.

    ====================================  =====  ==========================
    ``PaymentContext.payer``               0      행위자 — 지불을 일으킨 쪽
    ``CostPaymentEvent.actor``             0      행위자 (payer 에서 온다)
    ``CostPayment.player``                 **1**  **affected** — LP 가 줄어든 쪽
    ``LifeChanged.player``                 **1**  귀속자
    ====================================  =====  ==========================

    그래서 "결과 안에 사람 칸이 있으니 그것을 actor 로 쓰자" 는 §3 이 금지한
    바로 그 혼동이다.
    """
    state, result, journal = pay_life(repository, PlayerRef.OPPONENT, payer=MINE)
    assert result.paid and len(result.payments) == 1

    payment = result.payments[0]
    assert payment.semantics is CostSemantics.PAY_LIFE
    #: 🔴 결과의 사람 칸은 **당한 쪽**이다.
    assert payment.player == THEIRS
    #: 행위자는 **나**다.
    assert journal.events[0].actor == MINE
    assert payment.player != journal.events[0].actor

    #: delta 도 당한 쪽을 가리킨다.
    assert len(result.deltas) == 1
    delta = result.deltas[0]
    assert isinstance(delta, LifeChanged)
    assert delta.player == THEIRS
    assert timing_for(delta).actor == THEIRS

    #: 올바른 선언은 **payer** 다.
    observed = reader_for(state).read(result, actor=MINE)
    assert observed[0].context.actor == MINE       # 행위자
    assert observed[0].actor == THEIRS             # 귀속자


# ======================================================================
# B. §3 · §6 — 네 개념이 갈리는 자리
# ======================================================================


def test_09_the_word_controller_names_two_different_things(repository):
    """
    🔴 §3 · §6 ② — **``controller`` 가 두 가지를 가리킨다.**

    * ``ResolutionContext.controller`` — **효과의** 컨트롤러 = 행위자
    * ``CardInstance.controller`` — **카드의** 컨트롤러 ≠ 행위자

    상대 카드를 건드리는 효과에서 둘이 갈린다. 그래서 "controller 를 actor 로
    쓴다" 는 문장은 **어느 controller 인지** 말하지 않으면 뜻이 없다.
    """
    state = GameState.create(
        repository, decks=([POT_OF_GREED] * 8, [FEATHERMAN] * 8)
    )
    theirs = state.create_instance(FEATHERMAN, owner=THEIRS, zone=Zone.MZONE)

    #: 카드의 컨트롤러는 **상대**다.
    assert state.find_instance(theirs.instance_id).controller == THEIRS
    #: 그 카드를 건드리는 효과의 컨트롤러는 **나**일 수 있다.
    context = ResolutionContext(effect_ref=EffectRef(POT_OF_GREED, 0), controller=MINE)
    assert context.controller == MINE
    assert context.controller != state.find_instance(theirs.instance_id).controller

    #: 두 클래스에 같은 이름의 칸이 **둘 다** 있다 — 이름만으로는 구분되지 않는다.
    assert "controller" in {f.name for f in dataclasses.fields(ResolutionContext)}
    assert hasattr(state.find_instance(theirs.instance_id), "controller")


def test_10_the_delta_player_is_never_the_actor_in_general(repository):
    """
    §3 — ``delta.player`` 를 actor 로 쓰면 틀린다. **강욕의 보은**이 증거다.

    P0 이 발동하면 P1 이 뽑는다 — delta 의 사람 칸이 전부 P1 이다.
    """
    state, result = resolve_spell(repository, THE_GIFT_OF_GREED, MINE)
    assert len(result.deltas) == 2
    for delta in result.deltas:
        assert isinstance(delta, CardDrawn)
        assert delta.player == THEIRS            # affected
        assert timing_for(delta).actor == THEIRS  # 귀속자

    #: 행위자는 P0 이고 **선언으로만** 들어온다.
    observed = reader_for(state).read(result, actor=MINE)
    assert [o.context.actor for o in observed] == [MINE, MINE]
    assert [o.actor for o in observed] == [THEIRS, THEIRS]


def test_11_the_timing_actor_is_never_the_actor_in_general(repository):
    """§3 — ``timing.actor`` 를 actor 로 쓰면 틀린다. **Battle** 이 증거다."""
    state, execution, action, victim_before = battle(repository, THEIRS)
    assert victim_before == 8000
    assert state.player(MINE).life_points == 6100

    observed = reader_for(state).read(execution, actor=action.actor)
    assert len(observed) == 1
    assert observed[0].actor == MINE              # 귀속자 = 맞은 쪽
    assert observed[0].context.actor == THEIRS    # 행위자 = 공격한 쪽
    assert observed[0].actor != observed[0].context.actor


def test_12_the_controller_is_assigned_from_the_action_actor_one_line_at_a_time():
    """
    🟡 §6 ① · ④ — **``controller == actor`` 는 대입의 결과다.**

    production 경로가 한 줄씩 잇는다.

    ====================================  ==========================================
    ``engine/activation.py``               ``ChainLink(actor=action.actor)``
    ``engine/chain.py``                    ``ResolutionContext(controller=self.actor)``
    ``engine/activation.py``               ``PaymentContext(payer=action.actor)``
    ====================================  ==========================================

    그래서 지금 ``controller`` 와 ``payer`` 가 행위자인 것은 **코드 구조** 때문이고,
    "효과는 컨트롤러가 해결한다" 는 게임 규칙과 **결론만 같다.** 컨트롤 이동이
    구현되면 "발동한 사람" 과 "해결 시점의 컨트롤러" 가 갈리고, 그때
    ``ChainLink.actor`` 하나로는 둘을 표현할 수 없다.

    **그래서 이 Phase 는 ``controller`` 를 actor 로 쓰는 계약을 만들지 않는다.**
    """
    activation = source_of("engine/activation.py")
    assert "actor=action.actor" in activation
    assert "payer=action.actor" in activation

    #: ``ChainLink`` 의 칸 이름은 ``actor`` 다 — 거기서는 행위자라고 부른다.
    assert "actor" in {f.name for f in dataclasses.fields(ChainLink)}
    #: 그런데 문맥으로 넘어갈 때 **이름이 바뀐다**.
    context_code = method_code("engine/chain.py", "ChainLink", "resolution_context")
    assert "controller=self.actor" in context_code

    #: production 생성 자리가 각각 **하나**다 — 다른 값이 들어올 길이 없다.
    builders = [
        line
        for path in production_files()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "ResolutionContext(" in line and "class " not in line
    ]
    assert len(builders) == 1, builders
    payment_builders = [
        line
        for path in production_files()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "PaymentContext(" in line and "class " not in line
    ]
    assert len(payment_builders) == 1, payment_builders


# ======================================================================
# C. §7 — actor 없는 result 의 삼분
# ======================================================================


def test_13_the_seven_results_split_into_three_classes():
    """
    §7 — 일곱 result 를 **A · B · C** 로 가른다.

    =====================================  ==========================================
    **A. NO_ACTOR_BY_SEMANTICS**            ``ProgressionResult``
    **B. ACTOR_EXISTS_BUT_NOT_CARRIED**     ``EffectResult`` · ``CostPaymentResult``
    (actor 를 들고 있다)                     ``EffectEvent`` · ``CostPaymentEvent``
    (action 으로 닿는다)                     ``ActionExecution`` · ``ActivationResult``
    **C. ACTOR_NOT_DETERMINABLE**           **없다**
    =====================================  ==========================================

    🔴 **C 가 비어 있다는 것이 이 Phase 의 결론 하나다.** 일곱 중 어느 것도
    "현재 데이터로 결정할 수 없는" 것이 없다 — 상류가 전부 알고 있다. 3-F-14 가
    ``CostPaymentResult`` 를 UNKNOWN 으로 남긴 것은 **상류를 보지 않았기**
    때문이다.
    """
    rows = every_delta_bearing_result()
    assert set(rows) == {
        "ActionExecution",
        "ActivationResult",
        "EffectEvent",
        "CostPaymentEvent",
        "EffectResult",
        "CostPaymentResult",
        "ProgressionResult",
    }

    carries_actor = {name for name, (_, has_actor) in rows.items() if has_actor}
    reaches_via_action = {name for name, (has_action, _) in rows.items() if has_action}
    assert carries_actor == {"EffectEvent", "CostPaymentEvent"}
    assert reaches_via_action == {"ActionExecution", "ActivationResult"}

    #: 남은 셋 중 둘은 상류가 알고(B), 하나는 개념이 없다(A).
    neither = set(rows) - carries_actor - reaches_via_action
    assert neither == {"EffectResult", "CostPaymentResult", "ProgressionResult"}

    upstream_knows = {
        "EffectResult": ("ResolutionContext", "controller"),
        "CostPaymentResult": ("PaymentContext", "payer"),
    }
    for name, (context_name, field) in upstream_knows.items():
        module = sys.modules[
            "engine.effect.resolution" if context_name == "ResolutionContext"
            else "engine.payment"
        ]
        context = getattr(module, context_name)
        assert field in {f.name for f in dataclasses.fields(context)}, name

    #: ``ProgressionResult`` 만 상류에도 사람이 없다.
    assert "actor" not in inspect.signature(TurnProgressor.advance).parameters


def test_14_an_explicit_none_is_right_for_a_phase_change(repository):
    """§12 8 — ``actor=None`` 이 **정당한** 경우. A 분류다."""
    duel = live_duel(repository)
    state = duel.state.clone()
    progression = TurnProgressor().advance(state)
    observed = reader_for(state).read(progression, actor=None)
    assert observed
    assert all(event.context.actor is None for event in observed)
    #: 그리고 귀속자도 없다 — 두 계약이 같은 답을 낸다.
    assert all(event.actor is None for event in observed)


def test_15_an_explicit_none_can_hide_a_known_actor(repository):
    """
    🔴 §12 9 — ``actor=None`` 이 **UNKNOWN 을 숨기는** 경우.

    강욕의 보은의 행위자는 P0 으로 **존재한다.** 그런데 ``actor=None`` 이라고
    선언하면 그대로 들어가고, 받는 쪽에서는 페이즈 전환의 ``None`` 과
    **구별되지 않는다.**

    3-F-14 가 막은 것은 **말하지 않는 것**이고, **틀리게 말하는 것**은 그대로
    열려 있다. 이것이 이 Phase 가 B 분류를 "해결됨" 으로 적지 않는 까닭이다.
    """
    state, result = resolve_spell(repository, THE_GIFT_OF_GREED, MINE)
    hidden = reader_for(state).read(result, actor=None)
    assert [o.context.actor for o in hidden] == [None, None]

    duel = live_duel(repository)
    phase_state = duel.state.clone()
    legitimate = reader_for(phase_state).read(
        TurnProgressor().advance(phase_state), actor=None
    )

    #: 두 ``None`` 이 **같은 값**이고, 문맥에 까닭을 적는 칸이 없다.
    assert hidden[0].context.actor is legitimate[0].context.actor is None
    from engine.event_pipeline import EventContext

    assert not {f.name for f in dataclasses.fields(EventContext)} & {
        "actor_source",
        "provenance",
        "note",
    }

    #: 그런데 행위자는 존재했다 — 상류가 알고 있었다.
    assert "controller" in {f.name for f in dataclasses.fields(ResolutionContext)}


# ======================================================================
# D. §8 — 실제 듀얼 시나리오
# ======================================================================


@pytest.mark.parametrize(
    "passcode,label,expected_points,expected_affected",
    [
        (POT_OF_GREED, "욕망의 항아리 — 내가 2장 뽑는다", ["card_drawn"] * 2, [MINE, MINE]),
        (DIAN_KETO, "천사의 자비 — 내 LP 가 늘어난다", ["life_changed"], [MINE]),
        (RAIN_OF_MERCY, "자비의 비 — **양쪽** LP 가 늘어난다", ["life_changed"] * 2, [MINE, THEIRS]),
        (THE_GIFT_OF_GREED, "강욕의 보은 — **상대가** 뽑는다", ["card_drawn"] * 2, [THEIRS, THEIRS]),
        (UPSTART_GOBLIN, "졸부 고블린 — 내가 뽑고 **상대** LP 가 늘어난다", ["card_drawn", "life_changed"], [MINE, THEIRS]),
    ],
)
def test_16_five_real_cards_keep_the_actor_apart_from_the_affected(
    repository, passcode, label, expected_points, expected_affected
):
    """
    §8 — **실제 카드 다섯 장.** 행위자는 **하나** (P0), affected 는 카드마다 다르다.

    =====================================  ==========  ================
    카드                                    affected    행위자
    =====================================  ==========  ================
    욕망의 항아리                             나           나
    천사의 자비                               나           나
    자비의 비                                 **양쪽**     나
    강욕의 보은                               **상대**     나
    졸부 고블린                               **양쪽**     나
    =====================================  ==========  ================

    같은 선언(``actor=MINE``) 하나가 다섯 경우를 전부 옳게 적는다 — 그래서
    actor 는 **invocation 의 속성**이고 delta 의 속성이 아니다.
    """
    journal = EventJournal()
    state, result = resolve_spell(repository, passcode, MINE, journal=journal)
    assert result.deltas, label

    observed = reader_for(state).read(result, actor=MINE)
    assert [event.point.value for event in observed] == expected_points, label
    #: 귀속자(= affected)는 카드마다 다르다.
    assert [event.actor for event in observed] == expected_affected, label
    #: 🟢 행위자는 **언제나 하나**다.
    assert {event.context.actor for event in observed} == {MINE}, label
    #: journal 도 같은 답을 적는다.
    assert journal.events[0].actor == MINE, label


def test_17_one_invocation_can_affect_both_players_at_once(repository):
    """
    §8 — **졸부 고블린**이 가장 또렷하다.

    한 번의 발동이 **종류가 다른 두 사건**을 내고, affected 가 서로 다르다.
    행위자는 하나다.
    """
    state, result = resolve_spell(repository, UPSTART_GOBLIN, MINE)
    observed = reader_for(state).read(result, actor=MINE)
    assert len(observed) == 2

    drawn, life = observed
    assert drawn.point is TimingPoint.CARD_DRAWN
    assert drawn.actor == MINE                 # 내가 뽑았다
    assert life.point is TimingPoint.LIFE_CHANGED
    assert life.actor == THEIRS                # 상대 LP 가 늘었다
    #: 행위자는 둘 다 나다.
    assert drawn.context.actor == life.context.actor == MINE
    #: 순번으로 구분된다.
    assert [event.context.sequence for event in observed] == [0, 1]


def test_18_a_card_movement_scenario_names_only_the_owner(repository):
    """
    §8 — **카드 이동.** 가해자 칸이 없다.

    .. note::
       실제 카드로 "상대 카드 파괴" delta 를 얻지 못했다 — 싸이크론은
       ``unchecked_target``(가려진 정보), 강제 탈출 장치는 관문에서 멈춘다. 그래서
       **이동의 의미만** synthetic ``ZoneMoved`` 로 본다. 어떤 실제 카드의 재정도
       주장하지 않는다.
    """
    state = GameState.create(
        repository, decks=([LUSTER_DRAGON] * 8, [LUSTER_DRAGON] * 8)
    )
    destroyed = ZoneMoved(
        movement=OperationKind.DESTROY,
        card=I(9),
        source_player=THEIRS,
        source_zone=Zone.MZONE,
        destination_player=THEIRS,
        destination_zone=Zone.GRAVE,
    )
    #: 두 사람 칸이 **모두 주인**이다.
    assert destroyed.source_player == destroyed.destination_player == THEIRS
    assert timing_for(destroyed).actor == THEIRS

    #: "내가 상대 카드를 파괴했다" 를 **선언으로** 적는다.
    observed = reader_for(state).read_deltas((destroyed,), actor=MINE)
    assert observed[0].point is TimingPoint.CARD_MOVED
    assert observed[0].actor == THEIRS            # 귀속자 = 주인
    assert observed[0].context.actor == MINE      # 행위자 = 나


# ======================================================================
# E. §9 — 현재 read() 하나로 충분한가
# ======================================================================


def test_19_one_api_expresses_all_seven_contracts(repository):
    """
    §9 — **A. 모든 호출자가 actor 또는 explicit None 을 선언하는 것이 맞다.**

    일곱 타입이 두 모양으로 전부 표현된다 — ``actor=<값>`` 과 ``actor=None``.
    타입마다 다른 API 가 필요하다는 증거가 **없다.**
    """
    #: 값을 선언하는 쪽 — 다섯 타입.
    state, execution, action = summon(repository, MINE)
    assert reader_for(state).read(execution, actor=action.actor)

    journal = EventJournal()
    effect_state, effect_result = resolve_spell(
        repository, POT_OF_GREED, MINE, journal=journal
    )
    assert reader_for(effect_state).read(effect_result, actor=MINE)
    assert reader_for(effect_state).read(journal.events[0], actor=journal.events[0].actor)

    cost_state, cost_result, cost_journal = pay_life(
        repository, PlayerRef.CONTROLLER, payer=MINE
    )
    assert reader_for(cost_state).read(cost_result, actor=MINE)
    assert reader_for(cost_state).read(
        cost_journal.events[0], actor=cost_journal.events[0].actor
    )

    #: ``None`` 을 선언하는 쪽 — 한 타입.
    duel = live_duel(repository)
    phase_state = duel.state.clone()
    assert reader_for(phase_state).read(TurnProgressor().advance(phase_state), actor=None)

    #: 그리고 API 는 **하나**다 — 타입별 분기가 없다.
    read_code = method_code("engine/event_pipeline.py", "EventReader", "read")
    for absent in ("isinstance", "ActionExecution", "EffectResult", "ProgressionResult"):
        assert absent not in read_code, absent


def test_20_the_reader_never_looks_at_the_result_type(repository):
    """
    §9 — ``read()`` 가 **타입을 보지 않는다.**

    duck typing 으로 ``deltas`` 만 본다. 그래서 result 가 일곱이든 여덟이든 계약이
    갈라지지 않는다 — 타입별 계약을 만들면 **그 분기가 곧 갈라질 자리**가 된다
    (``_timing_for`` 가 Phase 2-AJ 에서 겪은 일과 같다).
    """
    read_code = method_code("engine/event_pipeline.py", "EventReader", "read")
    assert "getattr(result, 'deltas', None)" in read_code
    assert "isinstance(result" not in read_code

    read_deltas = method_code("engine/event_pipeline.py", "EventReader", "read_deltas")
    #: delta 쪽은 타입을 본다 — 그것은 **StateDelta 인지**만 본다.
    assert "isinstance(delta, StateDelta)" in read_deltas
    assert "ActionExecution" not in read_deltas


# ======================================================================
# F. §11 · §14 — AUDIT-ONLY 와 불변
# ======================================================================


def test_21_every_real_card_in_the_library_declares_an_empty_cost():
    """
    🔴 §5 8 — **실제 카드 16장 전부 ``CostGroup(costs=())`` 다.**

    그래서 ``CostPaymentResult`` 가 delta 를 들고 나오는 경로는 production 에
    **없다.** 이 Phase 가 synthetic 비용을 쓴 까닭이고, 동시에 "지금 틀린 값이
    production 판단을 오염시키고 있지 않다" 의 근거다.

    향후 비용 있는 카드가 들어오면 이 테스트가 **깨진다** — 그때가 §5 8 이 물은
    "Trigger/EventRelation 이 이 값을 읽을 가능성" 이 실제가 되는 시점이다.
    """
    import engine.effect.library as library

    entries = [value for name, value in vars(library).items() if name.endswith("_ENTRY")]
    assert len(entries) == 16, len(entries)
    for entry in entries:
        assert entry.definition.cost.costs == (), entry.definition.source_card_id


def test_22_the_three_f_fourteen_contract_is_unchanged(repository):
    """§13 — 3-F-14 의 세 모양 계약을 그대로 둔다."""
    state, execution, action, _ = battle(repository, THEIRS)
    reader = reader_for(state)

    with pytest.raises(TypeError) as omitted:
        reader.read(execution)
    assert "actor 를 말해야 합니다" in str(omitted.value)
    assert [o.context.actor for o in reader.read(execution, actor=None)] == [None]
    assert [o.context.actor for o in reader.read(execution, actor=THEIRS)] == [THEIRS]

    #: 귀속자 계약도 그대로다.
    assert "**행위의 주체가 아니다**" in source_of("engine/trigger.py")
    assert method_code("engine/event_pipeline.py", "ObservedEvent", "actor") == (
        "return self.timing.actor"
    )


def test_23_this_phase_changed_no_production_file():
    """
    §11 — **AUDIT-ONLY: 이 Phase(3-F-15)는 production 을 한 줄도 바꾸지 않았다.**

    §10 의 금지 field/enum 도 하나도 들어오지 않았다. 그리고 dormant 가 그대로다.

    .. note::
       **Phase 3-F-17 에서 재는 방법을 바꿨다 — 세 번째다.**

       ``git diff HEAD -- engine …`` 은 "지금 작업 나무가 깨끗한가" 이지 "**이
       Phase** 가 무엇을 바꿨는가" 가 아니다. 뒤의 Phase 가 production 을 바꾸는
       순간 그 Phase 때문에 깨진다 — 3-F-17 이 docstring 셋을 고치면서 실제로
       그렇게 되었다.

       3-F-14 가 3-F-12 · 3-F-13 의 같은 단정을 **자기 작업 commit 을 보는** 쪽으로
       고쳤는데, 그 뒤에 쓴 이 Phase 가 **낡은 모양을 다시 썼다.** 교훈을 한 번
       적용하고 패턴으로 만들지 않은 탓이다. 이제 같은 모양으로 고친다 —
       commit 이 건드린 파일 목록은 영원히 바뀌지 않는다.
    """
    PHASE_3F15_WORK = "6ae89e8"
    shown = subprocess.run(
        ["git", "show", "--stat", "--format=", PHASE_3F15_WORK],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    touched = [line.split("|")[0].strip() for line in shown.splitlines() if "|" in line]
    assert touched == ["tests/test_actor_declaration_scope_audit.py"], touched
    for path in touched:
        assert not path.startswith(PRODUCTION_ROOTS), path

    pipeline = source_of("engine/event_pipeline.py")
    for forbidden in (
        "actor_type",
        "actor_source",
        "actor_kind",
        "cause_player",
        "affected_player",
        "controller_player",
        "ActorOrigin",
        "ActorRequirement",
    ):
        assert forbidden not in pipeline, forbidden

    #: EventRelation · Trigger pipeline 은 연결되지 않았다.
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


def test_24_reading_events_changes_nothing(repository):
    """§14 — ``state_hash`` · RNG · hidden-information 불변."""
    state, execution, action, _ = battle(repository, THEIRS)
    before_hash, before_rng = state.state_hash(), repr(state.rng)

    reader = reader_for(state)
    reader.read(execution, actor=action.actor)
    reader.read(execution, actor=None)
    with pytest.raises(TypeError):
        reader.read(execution)

    assert state.state_hash() == before_hash
    assert repr(state.rng) == before_rng
    assert (
        live_duel(repository, seed=17).state.state_hash()
        == live_duel(repository, seed=17).state.state_hash()
    )

    view = GameStateView.from_state(state, viewer=MINE)
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(THEIRS).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()
