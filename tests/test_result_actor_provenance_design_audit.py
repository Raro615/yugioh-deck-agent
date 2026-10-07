"""
Phase 3-F-16 — ``EffectResult`` / ``CostPaymentResult`` actor provenance **설계
결정** 감사.

이 파일이 답하는 단 하나의 질문
-------------------------------
이 두 result 가 만들어진 **행위자의 identity 를 result 자체에 저장해야 하는가.**

🔴 결론부터: **저장하지 않아야 한다.** 그리고 3-F-15 의 B 판정이 **너무 강했다.**
---------------------------------------------------------------------------------
3-F-15 는 두 result 를 **따로 떼어 놓고** 보고 "actor 가 존재하지만 전달되지
않는다" 고 적었다. 그때 보지 않은 것이 **운반자(carrier)** 다.

====================  ==========================================  ==========
result                 production 에서 함께 오는 것                  actor 복원
====================  ==========================================  ==========
``EffectResult``        ``ChainResolution.link`` (= ``ChainLink``)   ``link.actor``
``CostPaymentResult``   ``ActivationResult.action``                  ``action.actor``
====================  ==========================================  ==========

둘 다 **한 객체 안에** 결과와 행위자가 같이 있다. 외부 context 도, 저장소도,
직렬화도 필요 없다 (``test_05`` · ``test_06``).

🟡 그런데 journal 은 production 에서 비어 있다
---------------------------------------------
``EffectEvent.actor`` · ``CostPaymentEvent.actor`` 는 actor 를 **제대로** 들고
있다. 그런데 **production 은 journal 을 넘기지 않는다** —
``duel_resolver()`` 가 ``build_executor()`` 를 journal 없이 만들고,
``EffectActivator`` 도 ``CostPayer()`` 를 그냥 만든다. 그래서 **그 두 사건은
production 에서 한 번도 기록되지 않는다** (``test_09``).

즉 "journal 이 provenance 를 들고 있다" 는 **production 에서 거짓**이고,
actor 의 유일한 production 집은 **운반자**다.
"""

import ast
import dataclasses
import inspect
import json
import pathlib
import subprocess

import pytest

from engine.action import PlayerAction
from engine.activation import ActivationResult, ActivationStatus, EffectActivator
from engine.chain import (
    Chain,
    ChainLink,
    ChainResolution,
    ChainResolutionStatus,
    ChainResolver,
)
from engine.condition import PlayerRef
from engine.cost.model import CostGroup, LifeCost
from engine.cost.receipt import CostPayment, CostSemantics
from engine.duel import Duel
from engine.effect.delta import CardDrawn, LifeChanged
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import CostPaymentEvent, EffectEvent, EventJournal
from engine.effect.library import build_executor, definition_registry
from engine.effect.resolution import EffectResult, ResolutionContext, ResolutionStatus
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.payment import CostPayer, CostPaymentResult, PaymentContext
from engine.spell_activation import duel_resolver
from engine.state.game_state import GameState
from engine.trigger import TimingPoint
from engine.turn_progression import TurnProgressor
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
#: 강욕의 보은 — **상대가** 2장 뽑는다.
THE_GIFT_OF_GREED = 5915629
#: 자비의 비 — **양쪽** LP 가 늘어난다.
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


def code_only(relative: str) -> str:
    """
    그 파일의 **코드만** — 문자열 리터럴을 전부 ``"<str>"`` 로 바꾼 것.

    .. note::
       **이 파일을 쓰면서 또 당했다.** ``"EffectResult" in source`` 로 보유자를
       셌더니 **설명 속 상호 참조**가 전부 걸렸다 — 3-F-13 이 같은 실수를 하고
       교훈까지 적었는데 반복했다. 타입이 **코드로** 쓰이는 자리를 셀 때는 반드시
       이 함수를 쓴다.
    """

    class _Strip(ast.NodeTransformer):
        def visit_Constant(self, node):  # noqa: N802
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value="<str>"), node)
            return node

    return ast.unparse(_Strip().visit(ast.parse(source_of(relative))))


def code_holders(name: str) -> set[str]:
    """그 이름을 **코드로** 쓰는 production 파일 전수 (설명 속 언급은 뺀다)."""
    found: set[str] = set()
    for path in production_files():
        relative = str(path.relative_to(PROJECT_ROOT))
        try:
            if name in code_only(relative):
                found.add(relative)
        except SyntaxError:  # pragma: no cover
            continue
    return found


def construction_sites(name: str, relative: str) -> list[tuple[int, set[str]]]:
    """``name(...)`` 호출을 **AST 로** 센다 — 정규식이 자기 소스를 세는 사고를 피한다."""
    found: list[tuple[int, set[str]]] = []
    for node in ast.walk(ast.parse(source_of(relative))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
        ):
            found.append((node.lineno, {k.arg for k in node.keywords if k.arg}))
    return found


def callers_of(name: str) -> dict[str, int]:
    """production 전체에서 ``name(`` 호출을 파일별로 센다 (정의 자체는 뺀다)."""
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
            and isinstance(node.func, (ast.Name, ast.Attribute))
            and (
                getattr(node.func, "id", None) == name
                or getattr(node.func, "attr", None) == name
            )
        )
        if count:
            found[str(path.relative_to(PROJECT_ROOT))] = count
    return found


# ======================================================================
# 판
# ======================================================================


def live_duel(repository, *, seed: int = 3) -> Duel:
    duel = Duel.start(
        repository, decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20), seed=seed
    )
    while duel.advance() is not None:
        pass
    return duel


def spell_on_field(repository, passcode: int, owner: int):
    #: seed 를 **반드시** 준다 — 없으면 난수원이 없어 ``state.rng`` 를 읽을 수
    #: 없고, 그러면 RNG 불변을 잴 수 없다 (``test_25`` 가 그것을 잰다).
    state = GameState.create(
        repository,
        decks=([passcode] * 4 + [FEATHERMAN] * 12, [FEATHERMAN] * 16),
        seed=5,
    )
    card = state.create_instance(passcode, owner=owner, zone=Zone.SZONE)
    state.turn.set_phase(Phase.MAIN1)
    return state, card.instance_id


def resolve_through_the_chain(repository, passcode: int, actor: int):
    """
    **production 해결기**로 체인 하나를 해결한다.

    ``duel_resolver()`` 가 ``Duel`` 이 실제로 쓰는 해결기이므로, 여기서 나오는
    ``ChainResolution`` 이 production 의 모양 그대로다.
    """
    state, source = spell_on_field(repository, passcode, actor)
    chain = Chain().activate(
        actor=actor, effect_ref=EffectRef(passcode, 0), source=source
    )
    return state, duel_resolver().resolve_top(state, chain)


def activate_with_cost(repository, who: PlayerRef, *, actor: int = MINE):
    """
    **synthetic 비용**을 붙인 발동. ``ActivationResult`` 를 얻는다.

    .. note::
       실제 카드로는 이 경로를 밟을 수 없다 — 라이브러리 16장 전부 비용이 비어
       있다 (3-F-15 ``test_21``). 어떤 실제 카드의 재정도 주장하지 않는다.
    """
    state, source = spell_on_field(repository, POT_OF_GREED, actor)
    reference = EffectRef(POT_OF_GREED, 0)
    definition = definition_registry().definition_for(reference)
    with_cost = dataclasses.replace(
        definition, cost=CostGroup(costs=(LifeCost(amount=1000, who=who),))
    )

    class _OneDefinition:
        def definition_for(self, ref):
            return with_cost if ref == reference else None

    activator = EffectActivator(
        _OneDefinition(), EffectImplementationRegistry((reference,))
    )
    action = PlayerAction.activate_effect(
        actor=actor, source=source, effect_ref=reference
    )
    result = activator.activate(
        state, Chain(), action, authorization=ValidationResult.valid()
    )
    return state, result, action


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
    from engine.summon import duel_executor

    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid()
    )
    return state, execution, action


# ======================================================================
# A. §2 — call graph 를 따라간다
# ======================================================================


def test_01_the_effect_result_has_exactly_one_production_producer():
    """
    §2 — ``EffectResult`` 를 만드는 production 자리와 그것을 부르는 자리.

    ``EffectExecutor.execute`` 가 만들고, production 에서 그것을 부르는 곳은
    ``ChainResolver.resolve_top`` **하나**다. 그래서 운반자가 하나로 정해진다.
    """
    chain_source = source_of("engine/chain.py")
    assert "self._executor.execute(state, definition, link.resolution_context())" in (
        chain_source
    )

    #: production 에서 ``EffectExecutor`` 를 만드는 자리는 하나다.
    builders = {
        path: count
        for path, count in callers_of("EffectExecutor").items()
        if not path.endswith("executor.py")
    }
    assert builders == {"engine/effect/library.py": 1}, builders

    #: 그 공장을 부르는 production 자리도 하나다 — 듀얼의 해결기다.
    assert "build_executor()" in source_of("engine/spell_activation.py")


def test_02_the_cost_payment_result_has_exactly_one_production_producer():
    """
    §2 — ``CostPaymentResult`` 는 ``CostPayer.pay`` 가 만들고, production 에서
    그것을 부르는 곳은 ``EffectActivator.activate`` **하나**다.
    """
    activation = source_of("engine/activation.py")
    assert "self._payer.pay(" in activation
    assert "payer=action.actor" in activation

    payers = {
        path: count
        for path, count in callers_of("CostPayer").items()
        if not path.endswith("payment.py")
    }
    assert payers == {"engine/activation.py": 1}, payers


def test_03_the_chain_link_carries_the_actor_from_the_action():
    """
    §2 · §3 — actor 가 어디서 오는가: ``PlayerAction.actor`` 하나다.

    ``ChainLink(actor=action.actor)`` → ``ResolutionContext(controller=self.actor)``.
    생성 자리가 각각 하나라서 다른 값이 들어올 길이 없다 (3-F-15 가 센 그대로다).
    """
    activation_sites = construction_sites("ChainLink", "engine/activation.py")
    assert activation_sites, "ChainLink 생성 자리를 못 찾았다"
    assert all("actor" in keywords for _, keywords in activation_sites)
    assert "actor=action.actor" in source_of("engine/activation.py")

    chain_sites = construction_sites("ResolutionContext", "engine/chain.py")
    assert len(chain_sites) == 1
    assert "controller" in chain_sites[0][1]
    assert "controller=self.actor" in source_of("engine/chain.py")

    #: ``ChainLink.actor`` 는 **필수** 필드다 — 비어 있을 수 없다.
    field = {f.name: f for f in dataclasses.fields(ChainLink)}["actor"]
    assert field.default is dataclasses.MISSING
    assert str(field.type) == "int"


def test_04_the_actor_survives_every_step_of_the_graph(repository):
    """
    §2 표 — 단계마다 actor 가 보존되는지 실측한다.

    =====================================  ==============  ==========
    단계                                     actor source    보존
    =====================================  ==============  ==========
    ``PlayerAction``                         자기 칸         ○ 필수
    ``ActivationResult``                     ``action``      ○ 필수
    ``ChainLink``                            ``action``      ○ 필수
    ``ResolutionContext``                    ``link``        ○ 필수
    ``EffectResult``                         **없다**         ✗
    ``ChainResolution``                      ``link``        **○**
    =====================================  ==============  ==========
    """
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, THEIRS)

    assert resolution.status is ChainResolutionStatus.RESOLVED
    #: 🔴 result 자체에는 없다.
    assert not {f.name for f in dataclasses.fields(EffectResult)} & {"actor", "action"}
    #: 🟢 그런데 운반자가 들고 있다.
    assert resolution.link is not None
    assert resolution.link.actor == THEIRS
    assert resolution.result is not None
    assert resolution.result.status is ResolutionStatus.RESOLVED
    #: 그리고 문맥도 같은 값을 받았다.
    assert resolution.link.resolution_context().controller == THEIRS


# ======================================================================
# B. §4 · §5 — 운반자가 결과와 actor 를 묶는다
# ======================================================================


def test_05_the_chain_resolution_pairs_the_result_with_the_actor(repository):
    """
    🟢 §4 Case A — **``ChainResolution`` 이 ``{link, result}`` 를 함께 들고 있다.**

    그래서 "``EffectResult`` 의 actor 를 ``ChainLink.actor`` 로 복원해도 안전하다"
    는 §3 의 문장은 **참**이다 — 외부 context 가 필요하지 않다. 운반자 **안에**
    둘이 있다.
    """
    fields = [f.name for f in dataclasses.fields(ChainResolution)]
    assert fields == ["status", "chain", "code", "reason", "link", "result"]

    state, resolution = resolve_through_the_chain(repository, THE_GIFT_OF_GREED, MINE)
    assert resolution.result is not None and resolution.link is not None
    assert resolution.link.actor == MINE

    #: 복원한 actor 로 사건을 읽으면 3-F-14 계약이 그대로 맞는다.
    observed = EventReader(
        GameStateView.from_state(state, viewer=MINE)
    ).read(resolution.result, actor=resolution.link.actor)
    assert [event.context.actor for event in observed] == [MINE, MINE]
    #: 귀속자는 상대다 — 강욕의 보은이므로.
    assert [event.actor for event in observed] == [THEIRS, THEIRS]


def test_06_a_result_never_appears_without_a_link_in_the_chain_resolution():
    """
    🟢 §4 — **불변식: ``result`` 가 있으면 ``link`` 도 있다.**

    ``ChainResolution`` 생성 자리 다섯을 AST 로 전수 조사했다. ``result`` 를 주는
    두 자리는 ``link`` 도 **같이** 준다. 그래서 result 만 있고 actor 가 없는
    ``ChainResolution`` 은 **만들어질 수 없다.**

    🟡 다만 ``__post_init__`` 이 이것을 **강제하지는 않는다** — 지금은 생성
    자리가 지키고 있을 뿐이다. 그 사실을 함께 고정한다.
    """
    sites = construction_sites("ChainResolution", "engine/chain.py")
    assert len(sites) == 5, sites

    with_result = [keywords for _, keywords in sites if "result" in keywords]
    assert len(with_result) == 2, with_result
    for keywords in with_result:
        assert "link" in keywords, keywords

    #: ``link`` 만 주는 자리도 있다 (정의를 못 찾은 링크) — 그 반대는 없다.
    link_only = [k for _, k in sites if "link" in k and "result" not in k]
    assert len(link_only) == 1

    #: 🟡 강제 장치는 deltas 쪽뿐이다.
    post_init = inspect.getsource(ChainResolution.__post_init__)
    assert "deltas" in post_init
    assert "link" not in post_init and "result" not in post_init


def test_07_the_activation_result_pairs_the_payment_with_the_actor(repository):
    """
    🟢 §5 — ``CostPaymentResult`` 쪽은 **더 강하다.**

    ``ActivationResult.action`` 은 **필수** 필드이므로, ``payment`` 가 있으면
    ``action.actor`` 가 **언제나** 있다. 조건부가 아니다.
    """
    action_field = {f.name: f for f in dataclasses.fields(ActivationResult)}["action"]
    assert action_field.default is dataclasses.MISSING
    assert str(action_field.type) == "PlayerAction"

    state, result, action = activate_with_cost(repository, PlayerRef.CONTROLLER)
    assert result.payment is not None
    assert isinstance(result.payment, CostPaymentResult)
    #: 운반자가 actor 를 들고 있다.
    assert result.action.actor == action.actor == MINE

    #: production 에서 ``CostPaymentResult`` 를 **코드로** 쓰는 자리는 둘뿐이다.
    #: (``engine/event_pipeline.py`` 에도 이름이 나오지만 그것은 3-F-14 가
    #: ``read()`` 설명에 적은 **일곱 타입 목록**이고 코드가 아니다.)
    assert code_holders("CostPaymentResult") == {
        "engine/payment.py",
        "engine/activation.py",
    }, code_holders("CostPaymentResult")
    assert "CostPaymentResult" in source_of("engine/event_pipeline.py")
    assert "CostPaymentResult" not in code_only("engine/event_pipeline.py")


def test_08_a_standalone_result_really_cannot_name_its_actor(repository):
    """
    §4 Case B — **결과만 떼어 놓으면 복원할 수 없다.** 그것은 사실이다.

    ``EffectResult`` 에는 운반자로 돌아갈 역참조가 없다. 그래서 §10 의 질문 —
    data model 문제인가 API 문제인가 — 의 답이 갈린다: **정보가 소실되는 것이
    아니라, 운반자를 버리면 못 찾는 것**이다.
    """
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, THEIRS)
    orphan = resolution.result
    assert orphan is not None

    #: 역참조가 하나도 없다.
    for name in ("link", "chain", "context", "action", "actor", "controller"):
        assert not hasattr(orphan, name), name
    #: 직렬화해도 사람이 나오지 않는다.
    payload = json.dumps(orphan.to_dict(), ensure_ascii=False, default=str)
    assert "actor" not in payload
    assert "controller" not in payload

    #: 그래서 3-F-14 계약이 **거부**한다 — 조용히 틀린 값을 만들지 않는다.
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))
    with pytest.raises(TypeError) as omitted:
        reader.read(orphan)
    assert "부르는 쪽만 압니다" in str(omitted.value)


# ======================================================================
# C. §2 · §8 — journal 은 production 에서 비어 있다
# ======================================================================


def test_09_production_never_records_the_journal_events():
    """
    🔴 §8 — **production 은 journal 을 넘기지 않는다.**

    ``EffectEvent.actor`` 와 ``CostPaymentEvent.actor`` 는 actor 를 제대로 들고
    있지만, 그 두 사건은 **production 에서 한 번도 기록되지 않는다.**

    그래서 "journal 이 provenance 를 들고 있다" 는 production 에서 **거짓**이고,
    actor 의 유일한 production 집은 **운반자**다. 이것이 B 안(기존 provenance 를
    쓴다)을 고를 때 **journal 을 근거로 삼을 수 없는** 까닭이다.
    """
    resolver = duel_resolver()
    assert isinstance(resolver, ChainResolver)
    #: 듀얼의 해결기가 든 실행기에 journal 이 없다.
    assert getattr(resolver.executor, "_journal", "없음") is None

    #: 공장도 기본값이 ``None`` 이다.
    assert inspect.signature(build_executor).parameters["journal"].default is None
    #: 그리고 ``duel_resolver`` 는 journal 을 주지 않는다.
    assert "build_executor()" in source_of("engine/spell_activation.py")

    #: 비용 쪽도 같다 — ``CostPayer()`` 를 그냥 만든다.
    assert "CostPayer()" in source_of("engine/activation.py")

    #: production 어디에도 ``EventJournal`` 을 만드는 자리가 없다.
    journal_builders = {
        path: count
        for path, count in callers_of("EventJournal").items()
        if not path.endswith("journal.py")
    }
    assert journal_builders == {}, journal_builders


def test_10_the_journal_events_do_carry_the_actor_when_asked(repository):
    """
    §3 — journal 을 **주면** actor 가 기록된다. 그 값은 올바르다.

    production 이 쓰지 않을 뿐이고, 구조가 틀린 것은 아니다 — 그래서 이 Phase 는
    journal 을 고치자고 말하지 않는다.
    """
    state, source = spell_on_field(repository, POT_OF_GREED, MINE)
    reference = EffectRef(POT_OF_GREED, 0)
    journal = EventJournal()
    EffectExecutor(
        lookup=EffectImplementationRegistry((reference,)), journal=journal
    ).execute(
        state,
        definition_registry().definition_for(reference),
        ResolutionContext(effect_ref=reference, controller=MINE, source=source),
    )
    assert len(journal.events) == 1
    event = journal.events[0]
    assert isinstance(event, EffectEvent)
    assert event.actor == MINE
    #: 직렬화에도 남는다.
    assert "actor" in event.to_dict()


# ======================================================================
# D. §3 — ChainLink.actor 와 EffectEvent.actor 비교
# ======================================================================


def test_11_the_two_actors_come_from_the_same_single_source(repository):
    """
    §3 1 · 2 — ``ChainLink.actor`` 와 ``EffectEvent.actor`` 는 **같은 값**이다.

    둘 다 ``PlayerAction.actor`` 에서 온다.

    * ``ChainLink.actor`` ← ``action.actor`` (직접)
    * ``EffectEvent.actor`` ← ``ResolutionContext.controller`` ← ``link.actor``

    즉 **한 뿌리 두 가지**다. 그래서 지금은 갈릴 수 없다.
    """
    state, source = spell_on_field(repository, POT_OF_GREED, THEIRS)
    reference = EffectRef(POT_OF_GREED, 0)
    link = ChainLink(sequence=0, actor=THEIRS, effect_ref=reference, source=source)

    journal = EventJournal()
    EffectExecutor(
        lookup=EffectImplementationRegistry((reference,)), journal=journal
    ).execute(
        state,
        definition_registry().definition_for(reference),
        link.resolution_context(),
    )
    assert journal.events[0].actor == link.actor == THEIRS

    #: 실행기가 쓰는 값이 문맥의 ``controller`` 라는 것도 코드로 고정한다.
    executor_source = source_of("engine/effect/executor.py")
    assert "actor=context.controller" in executor_source


def test_12_the_two_actors_would_diverge_only_if_control_could_change(repository):
    """
    🟡 §3 3 · 4 · 5 — **갈릴 수 있는 조건은 하나다: 컨트롤 이동.**

    ``ChainLink.actor`` 는 **발동한 사람**이다 (발동 시점에 박힌다). "해결 시점의
    컨트롤러" 와 뜻이 다른데, 지금은 **값이 같다** — 컨트롤을 바꾸는 효과가 없기
    때문이다.

    그래서 링크를 만든 뒤 카드의 컨트롤러를 옮겨도 ``link.actor`` 는 **그대로**
    다. 그것이 "발동한 사람" 이라는 증거이고, 동시에 컨트롤 이동이 들어오면 둘을
    한 칸으로 표현할 수 없게 되는 자리다.
    """
    state, source = spell_on_field(repository, POT_OF_GREED, MINE)
    link = ChainLink(
        sequence=0, actor=MINE, effect_ref=EffectRef(POT_OF_GREED, 0), source=source
    )
    assert state.find_instance(source).controller == MINE

    #: 카드를 상대 쪽으로 옮긴다 — 컨트롤러가 바뀐다.
    state.move(state.find_instance(source), Zone.SZONE, to_player=THEIRS)
    assert state.find_instance(source).controller == THEIRS

    #: 🔴 그래도 링크의 actor 는 **발동한 사람**이다.
    assert link.actor == MINE
    assert link.resolution_context().controller == MINE
    #: 즉 ``controller`` 라는 이름이 **카드의 컨트롤러를 따라가지 않는다.**
    assert link.resolution_context().controller != state.find_instance(source).controller

    #: 그리고 production 에 컨트롤을 바꾸는 효과가 없다 — 조작 종류를 전수로 본다.
    from engine.effect.operation import OperationKind

    assert not [
        kind for kind in OperationKind if "control" in kind.value
    ]


def test_13_a_copy_or_lingering_effect_has_no_production_path():
    """
    §3 6 — **copy / lingering / triggered effect 는 production 에 없다.**

    그래서 "그 경우에도 같은가" 는 **지금 답할 수 없는 질문**이고, 추측해서
    답하지 않는다. 구조로 확인되는 것만 적는다.

    * 지속 효과 계층이 없다 — ``ChainLink`` 는 발동 하나를 가리킨다.
    * 트리거 파이프라인은 dormant 다 (production importer 0).
    """
    #: 체인 링크에 "어느 카드의 효과를 베꼈는가" 를 적는 칸이 없다.
    link_fields = {f.name for f in dataclasses.fields(ChainLink)}
    assert link_fields == {
        "sequence",
        "actor",
        "effect_ref",
        "source",
        "selections",
        "payments",
    }
    assert not link_fields & {"copied_from", "original_actor", "lingering"}

    #: 트리거 계층은 여전히 production 에서 쓰이지 않는다.
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


# ======================================================================
# E. §5 · §6 — 네 주체를 갈라 본다
# ======================================================================


def test_14_the_four_subjects_separate_in_one_measured_board(repository):
    """
    🔴 §6 — **네 개를 한 판에서 갈라 본다.** `LifeCost(who=OPPONENT)`.

    ====================================  =====  =======================
    ① effect actor (``action.actor``)      **0**  발동한 사람
    ② ``PaymentContext.payer``             **0**  **비용을 지는 사람** = ①
    ③ ``CostPayment.player``               **1**  자원이 줄어든 쪽
    ④ affected player (``delta.player``)   **1**  영향을 받은 쪽
    ====================================  =====  =======================

    🔴 즉 **"cost payer" 라는 말 자체가 두 가지를 가리킨다** — ``payer``(=①) 와
    "실제로 자원을 낸 쪽"(=③) 이다. 3-F-15 가 ③을 affected 로 판정한 것이 맞고,
    여기서는 ②가 ①과 **같다**는 것을 더한다.
    """
    state, result, action = activate_with_cost(repository, PlayerRef.OPPONENT)
    assert result.payment is not None
    payment = result.payment
    assert payment.paid and len(payment.payments) == 1

    receipt = payment.payments[0]
    assert receipt.semantics is CostSemantics.PAY_LIFE
    #: ① = ② = 0
    assert action.actor == MINE
    assert result.action.actor == MINE
    #: ③ = ④ = 1
    assert receipt.player == THEIRS
    assert len(payment.deltas) == 1
    assert isinstance(payment.deltas[0], LifeChanged)
    assert payment.deltas[0].player == THEIRS
    #: 실제로 상대 LP 가 줄었다.
    assert state.player(THEIRS).life_points == 7000
    assert state.player(MINE).life_points == 8000
    #: ①②와 ③④가 갈린다.
    assert result.action.actor != receipt.player


def test_15_a_single_actor_field_would_still_be_well_defined(repository):
    """
    §6 — **한 result 안에서는 "단일 actor" 가 모호하지 않다.**

    ``CostPaymentResult`` 의 행위자는 ①②(= `action.actor`) 하나다. ③④는
    **payment 마다 / delta 마다** 있는 별개 정보이고 이미 각자의 칸에 있다.

    그래서 §6 의 "하나의 actor 로 모두 표현할 수 있는가" 의 답은 **그럴 필요가
    없다** — 네 개를 한 칸에 넣으려는 것이 애초에 잘못된 질문이다. 네 칸이 이미
    따로 있다.
    """
    state, result, action = activate_with_cost(repository, PlayerRef.OPPONENT)
    payment = result.payment
    assert payment is not None

    #: ③은 payment 마다 있다.
    assert all(hasattr(receipt, "player") for receipt in payment.payments)
    #: ④는 delta 마다 있다.
    assert all(hasattr(delta, "player") for delta in payment.deltas)
    #: ①②는 운반자에 하나 있다.
    assert result.action.actor == MINE

    #: 즉 셋이 서로 다른 **기수(cardinality)** 를 갖는다 — 한 칸에 못 들어간다.
    assert len(payment.payments) == 1 and len(payment.deltas) == 1
    assert isinstance(result.action.actor, int)


def test_16_the_semantic_actor_of_a_cost_payment_is_the_activator(repository):
    """
    §5 — **``CostPaymentResult.actor`` 를 정의한다면 그것은 "발동한 사람" 이다.**

    후보 넷 중 셋이 탈락한다.

    * "비용을 지불한 사람" — ③은 자원이 줄어든 쪽이다. ``who=OPPONENT`` 면 상대다
    * "controller" — 카드의 컨트롤러와 효과의 컨트롤러가 다르다 (3-F-15)
    * "affected player" — ④다. 행위가 아니다
    * **"효과를 발동한 사람"** — ``PaymentContext.payer`` 이고 ``action.actor`` 다

    그리고 그 값은 **운반자에 이미 있다.** 그래서 칸을 만들지 않는다.
    """
    state, result, action = activate_with_cost(repository, PlayerRef.OPPONENT)

    #: ``PaymentContext.payer`` 가 발동한 사람이라는 것을 코드로 고정한다.
    assert "payer=action.actor" in source_of("engine/activation.py")
    #: 그리고 journal 이 그 값을 actor 라고 부른다.
    assert "actor=context.payer" in source_of("engine/payment.py")

    #: 같은 값이 운반자에 있다.
    assert result.action.actor == action.actor == MINE


# ======================================================================
# F. §7 — result 에 actor 를 더하면 생기는 비용
# ======================================================================


def test_17_adding_an_actor_field_would_duplicate_the_carrier(repository):
    """
    🔴 §7 — **중복 provenance 가 된다.**

    ``EffectResult.actor`` 를 더하면 ``ChainResolution.link.actor`` 와 **같은
    사실이 두 곳**에 저장된다. 둘이 갈리면 어느 쪽이 authoritative 인지 코드가
    말해 주지 않는다 — 그리고 지금 구조에서는 **갈릴 수 있다.** 운반자가
    ``dataclasses.replace`` 로 바꿀 수 있는 frozen dataclass 이기 때문이다.
    """
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, THEIRS)
    assert resolution.link is not None and resolution.result is not None

    #: 운반자를 바꿔 쓰면 두 값이 갈린다 — actor 칸이 있었다면 여기서 모순이 된다.
    relinked = dataclasses.replace(
        resolution, link=dataclasses.replace(resolution.link, actor=MINE)
    )
    assert relinked.link.actor == MINE
    assert resolution.link.actor == THEIRS
    #: result 는 **같은 객체**다 — 그래서 result 에 actor 를 넣었다면 어느 쪽이
    #: 맞는지 알 수 없다.
    assert relinked.result is resolution.result

    #: 지금은 사실의 출처가 **하나**다.
    assert not {f.name for f in dataclasses.fields(EffectResult)} & {"actor"}
    assert "actor" in {f.name for f in dataclasses.fields(ChainLink)}

    #: 🔴 ``CostPaymentResult`` 쪽도 **같은 위험**이다 — 고의 위반 2번이 처음에
    #: 이 자리를 비워 두어 포괄 테스트에만 걸렸다. 그래서 같이 못박는다.
    cost_state, activation, cost_action = activate_with_cost(
        repository, PlayerRef.CONTROLLER
    )
    assert activation.payment is not None
    #: 결과에 사람 칸이 없고, 운반자(``action``)에 있다.
    assert not {f.name for f in dataclasses.fields(CostPaymentResult)} & {"actor"}
    assert "actor" in {f.name for f in dataclasses.fields(PlayerAction)}
    #: 운반자를 바꿔 쓰면 갈린다 — 그래서 result 쪽에 복제하면 모순이 생긴다.
    relabelled = dataclasses.replace(
        activation, action=dataclasses.replace(cost_action, actor=THEIRS)
    )
    assert relabelled.action.actor == THEIRS
    assert activation.action.actor == MINE
    assert relabelled.payment is activation.payment


def test_18_adding_a_field_would_move_the_canonical_state(repository):
    """
    §7 — ``canonical_state`` · ``to_dict`` 가 바뀐다.

    두 result 의 정규 상태에 사람이 들어 있지 않다. 칸을 더하면 **직렬화와
    동등성이 둘 다** 바뀌고, 기존 replay 기록이 호환되지 않는다.
    """
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, MINE)
    result = resolution.result
    assert result is not None

    canonical = result.canonical_state()
    assert MINE not in canonical or True  # 값 자체가 아니라 **칸**이 없다는 것이 요점
    payload = json.dumps(result.to_dict(), ensure_ascii=False, default=str)
    for word in ("actor", "controller", "payer"):
        assert word not in payload, word

    #: 반면 운반자 쪽 정규 상태에는 사람이 있다.
    link_canonical = resolution.link.canonical_state()
    assert MINE in link_canonical


def test_19_the_state_hash_does_not_see_these_results(repository):
    """
    §7 — ``state_hash`` 는 result 를 보지 않는다. 그래서 칸을 더해도 판 해시는
    바뀌지 않는다 — **그것이 안전하다는 뜻은 아니다.** 바뀌는 것은 직렬화와
    동등성이다 (``test_18``).
    """
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, MINE)
    before = state.state_hash()
    #: 결과를 여러 번 읽어도 판은 그대로다.
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))
    reader.read(resolution.result, actor=resolution.link.actor)
    reader.read(resolution.result, actor=None)
    assert state.state_hash() == before

    #: 그리고 ``state_hash`` 가 result 타입을 전혀 모른다.
    game_state_source = source_of("engine/state/game_state.py")
    for absent in ("EffectResult", "CostPaymentResult", "ChainResolution"):
        assert absent not in game_state_source, absent


# ======================================================================
# G. §8 — actor 를 더하지 않는 경우의 비용
# ======================================================================


def test_20_no_production_consumer_holds_a_bare_result(repository):
    """
    §8 — **운반자를 버리는 production 소비자가 없다.**

    ``EffectResult`` 는 ``ChainResolution`` 안에서만, ``CostPaymentResult`` 는
    ``ActivationResult`` 안에서만 돌아다닌다. 저장되지도, 직렬화되어 나중에
    쓰이지도 않는다.
    """
    #: ``EffectResult`` 를 **코드로** 쓰는 production 파일 전수. 만드는 자리,
    #: 운반자, 타입 선언 — 셋뿐이고 **저장하는 자리가 없다.**
    holders = code_holders("EffectResult")
    assert holders == {
        "engine/chain.py",              # 운반자가 쓴다
        "engine/effect/executor.py",    # 만든다
        "engine/effect/resolution.py",  # 타입을 선언한다
        "engine/effect/__init__.py",    # 🟡 re-export 뿐이다 (아래에서 확인)
    }, holders

    #: ``engine/effect/__init__.py`` 는 **다시 내보내기만** 한다 — 들고 있지 않다.
    reexport = code_only("engine/effect/__init__.py")
    assert "EffectResult" in reexport
    #: 쓰는 모양이 import 와 ``__all__`` 뿐이다.
    for node in ast.walk(ast.parse(source_of("engine/effect/__init__.py"))):
        if isinstance(node, ast.Attribute) and node.attr == "EffectResult":
            raise AssertionError("re-export 가 아니라 실제로 쓰고 있다")

    #: ``ChainResolution`` 을 코드로 쓰는 자리도 좁다 — 운반자를 밖으로 내보내는
    #: 자리가 응답 계층과 듀얼뿐이다.
    carriers = code_holders("ChainResolution")
    assert "engine/chain.py" in carriers
    assert "agent" not in " ".join(carriers)

    #: AI 쪽은 셋 다 **코드로** 모른다.
    for absent in ("EffectResult", "CostPaymentResult", "ChainResolution"):
        for path in (PROJECT_ROOT / "agent").rglob("*.py"):
            relative = str(path.relative_to(PROJECT_ROOT))
            assert absent not in code_only(relative), (absent, relative)


def test_21_a_hypothetical_standalone_consumer_is_refused_not_misled(repository):
    """
    🟢 §8 · §9 7 — **가상의 단독 소비자**를 실제로 만들어 본다.

    "result 만 받아서 사건을 읽는" 소비자가 지금 들어오면 어떻게 되는가. 3-F-14 의
    계약이 **거부**한다 — 조용히 틀린 actor 를 만들지 않는다. 그리고 운반자를
    함께 넘기면 **그대로 통과**한다.

    즉 "지금 consumer 가 없다" 가 **"없어도 된다"** 의 근거가 아니라, "들어와도
    안전하다" 가 근거다.
    """
    state, resolution = resolve_through_the_chain(repository, RAIN_OF_MERCY, MINE)
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))

    def consume_well(step: ChainResolution):
        """운반자를 함께 받는 소비자 — **이것이 올바른 모양**이다."""
        assert step.link is not None
        return reader.read(step.result, actor=step.link.actor)

    #: 🔴 **운반자를 버린 소비자.** 호출을 ``with pytest.raises`` 블록 **안에**
    #: 둔다 — 중첩 함수 안에 두면 3-F-13 의 ``test_04`` 가 "계약을 지키지 않은
    #: 생략" 으로 센다 (그 테스트는 ``with`` 블록의 줄 범위로 거부 시험 자리를
    #: 가린다). 실제로 그렇게 썼다가 전체 회귀에서 걸렸다.
    with pytest.raises(TypeError):
        reader.read(resolution.result)

    observed = consume_well(resolution)
    #: 자비의 비 — 귀속자 둘, 행위자 하나.
    assert sorted(event.actor for event in observed) == [MINE, THEIRS]
    assert {event.context.actor for event in observed} == {MINE}


def test_22_a_clone_keeps_the_carrier_intact(repository):
    """
    §2 · §14 12 — **clone 후에도 복원된다.** 운반자는 값 타입이다.

    ``ChainResolution`` · ``ChainLink`` 모두 frozen dataclass 이고 판을 들고 있지
    않다. 그래서 판을 복제해도 운반자가 흔들리지 않는다.
    """
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, THEIRS)
    copy = state.clone()
    assert copy.state_hash() == state.state_hash()

    #: 운반자는 판과 무관하므로 그대로 쓸 수 있다.
    assert resolution.link.actor == THEIRS
    reader = EventReader(GameStateView.from_state(copy, viewer=MINE))
    observed = reader.read(resolution.result, actor=resolution.link.actor)
    assert all(event.context.actor == THEIRS for event in observed)

    #: 그리고 frozen 이다 — 몰래 바뀌지 않는다.
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolution.link.actor = MINE  # type: ignore[misc]


def test_23_the_carrier_survives_serialization_but_the_result_alone_does_not(
    repository,
):
    """
    §2 · §14 14 — **직렬화**: 운반자 쪽에는 사람이 남고 result 쪽에는 안 남는다.

    그래서 replay 를 만들 때 저장해야 하는 것은 **운반자**다. 이것이 B 안의
    실질적인 요구사항이고, 새 field 가 필요하다는 뜻은 아니다.
    """
    state, resolution = resolve_through_the_chain(repository, THE_GIFT_OF_GREED, MINE)

    result_payload = json.dumps(
        resolution.result.to_dict(), ensure_ascii=False, default=str
    )
    assert "actor" not in result_payload

    link_payload = json.dumps(
        resolution.link.to_dict(), ensure_ascii=False, default=str
    )
    assert "actor" in link_payload
    #: 그 값이 실제로 복원된다.
    assert json.loads(link_payload)["actor"] == MINE


# ======================================================================
# H. §12 · §13 · §14 — 불변과 AUDIT-ONLY
# ======================================================================


def test_24_the_three_f_fourteen_contract_is_unchanged(repository):
    """§14 20~22 — 3-F-14 의 세 모양 계약을 그대로 둔다."""
    state, execution, action = battle(repository, THEIRS)
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))

    with pytest.raises(TypeError) as omitted:
        reader.read(execution)
    assert "actor 를 말해야 합니다" in str(omitted.value)
    assert [o.context.actor for o in reader.read(execution, actor=None)] == [None]
    assert [o.context.actor for o in reader.read(execution, actor=THEIRS)] == [THEIRS]

    #: 페이즈 전환의 ``actor=None`` 도 그대로 정당하다.
    duel = live_duel(repository)
    phase_state = duel.state.clone()
    phase_reader = EventReader(GameStateView.from_state(phase_state, viewer=MINE))
    for event in phase_reader.read(TurnProgressor().advance(phase_state), actor=None):
        assert event.point is TimingPoint.PHASE_CHANGED
        assert event.context.actor is None


def test_25_hidden_information_and_the_rng_are_untouched(repository):
    """§14 15~19 — hidden-information · ``state_hash`` · RNG 불변."""
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, MINE)
    before_hash, before_rng = state.state_hash(), repr(state.rng)

    reader = EventReader(GameStateView.from_state(state, viewer=MINE))
    for _ in range(3):
        reader.read(resolution.result, actor=resolution.link.actor)
    assert state.state_hash() == before_hash
    assert repr(state.rng) == before_rng

    assert (
        live_duel(repository, seed=19).state.state_hash()
        == live_duel(repository, seed=19).state.state_hash()
    )

    view = GameStateView.from_state(state, viewer=MINE)
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(THEIRS).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()


def test_26_this_phase_changed_no_production_file():
    """
    §12 — **AUDIT-ONLY: 이 Phase(3-F-16)는 production 을 한 줄도 바꾸지 않았다.**

    §13 의 금지 항목도 하나도 들어오지 않았다 — 두 result 에 actor 칸이 없고,
    새 provenance 객체도 enum 도 없다.

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
    PHASE_3F16_WORK = "57da2f6"
    shown = subprocess.run(
        ["git", "show", "--stat", "--format=", PHASE_3F16_WORK],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    touched = [line.split("|")[0].strip() for line in shown.splitlines() if "|" in line]
    assert touched == ["tests/test_result_actor_provenance_design_audit.py"], touched
    for path in touched:
        assert not path.startswith(PRODUCTION_ROOTS), path

    #: 두 result 에 사람 칸이 없다 (이 Phase 가 더하지 않았다).
    assert not {f.name for f in dataclasses.fields(EffectResult)} & {
        "actor",
        "controller",
        "player",
        "affected_player",
    }
    assert not {f.name for f in dataclasses.fields(CostPaymentResult)} & {
        "actor",
        "controller",
        "affected_player",
    }

    #: 새 provenance 추상도 없다.
    for forbidden in ("ActorProvenance", "ActorOrigin", "ActorRequirement", "EventBus"):
        for relative in (
            "engine/chain.py",
            "engine/payment.py",
            "engine/effect/resolution.py",
            "engine/event_pipeline.py",
        ):
            source = source_of(relative)
            if forbidden == "EventBus" and relative == "engine/event_pipeline.py":
                #: "만들지 않는다" 는 설명으로 한 번 나온다.
                assert source.count("EventBus") == 1
                continue
            assert forbidden not in source, (forbidden, relative)
